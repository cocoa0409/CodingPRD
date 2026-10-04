# Live Event Touring API — Product Requirements Document

## 1. Introduction

Running a touring live-event promotion means holding three calendars in your head at once: the road schedule of arenas and house shows, the weekly television grid that anchors the entire creative cycle, and the premium-event distribution windows that must open and close in step with exclusive territory rights negotiated with streaming partners. Layered on top of that calendar is the human side — independent-contractor talent with downside guarantees and per-quarter appearance obligations, likeness rights that gate merchandise sales, wellness scores that drift with every fulfilled or missed booking, medical clearances governed by strict segregation of duties, and visas that must land before the tour crosses a border.

This document specifies the Live Event Touring API, a system that manages performer agreements, schedule construction, storyline continuity, premium-event windowing, venue merchandise royalty accounting, medical and wellness protocols, developmental call-ups, and international visa logistics. The API is built around a server-maintained logical clock: agreement expiry, weekly wellness decay, and same-day correction windows are all evaluated against this clock rather than wall-clock time, so the whole touring calendar can be driven forward deterministically. All resources are mounted under the `/touring` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorization matrix (§4); an authenticated operator attempting an operation outside their role's remit is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `ContractAdmin`, `TourPlanner`, `TalentRelations`, `StorylineEditor`, `DistributionManager`, `MerchOps`, `Medic`, and `LogisticsCoordinator`. For every role, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity; the server may record it where a workflow calls for attribution — for example, as `evaluator_id` on a medical evaluation, as `cleared_by` on a clearance, or as `decided_by` on a call-up decision — but it never compares the header value to any entity's `id` for ownership purposes. This opacity matters most for the `Medic` role: the segregation-of-duties rule on clearances compares `cleared_by` against every `evaluator_id` recorded on the case, and both of those values are simply the `X-User-ID` strings supplied by the operators.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Driven Sweeps

The system does not consult wall-clock time for business decisions. Instead, a server-side **logical clock** governs every date- or time-sensitive rule: agreement expiry, wellness decay, same-day no-show corrections, visa deadlines, appearance-quarter boundaries, and event-date filtering all read from this clock. At server startup the logical clock is pinned to exactly `2026-09-01T00:00:00Z`; until an operator explicitly advances it, the clock reads this default and never falls back to wall-clock time.

A `ContractAdmin` advances the clock by supplying a `to_iso8601` instant through the clock-advance capability, which responds with the new `current_utc`. Advancing the clock triggers two automatic sweeps. First, every `ACTIVE` talent agreement whose `end_date` has been reached or passed by the new clock date flips to `EXPIRED`. Second, the weekly wellness decay runs: each time the clock crosses a Monday 00:00 UTC boundary, every talent holding the `MAIN_ROSTER` tier loses wellness per the accrual rule in §3.6; developmental talent is exempt from this decay. Both sweeps are side effects of the clock advance itself — no separate call exists for them.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields unless stated otherwise:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last mutation.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation to the resource.

The single exception is the **MerchSale** line, which is an immutable ledger entry: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent. Any mutation to a resource — including system-driven mutations from cascades and sweeps — refreshes its `updated_at` and increments its `version`. In particular, when a cascade recomputes a talent's `likeness_granted` or `booking_mode` and the value actually changes, the talent's `version` is bumped and `updated_at` refreshed.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Activating a talent agreement requires the request to carry `expected_agreement_version`, set to the agreement's current `version` as last observed by the client; if another writer has advanced the agreement's version since then — for example by editing its window or royalty terms — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before proceeding. Locking an event likewise requires `expected_event_version` matching the event's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because roster minimums or event timing may have changed under the client's feet. No other endpoint takes a version field; clients must not send one elsewhere.

### 2.7. Validation Ordering

Every request is validated against an ordered cascade, and the order matters because a single request may violate several rules at once. The cascade evaluates, in this exact sequence: first authentication of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`); then role authorization for the endpoint (`ERR_FORBIDDEN`); then existence of every path identifier, resolved left to right (`ERR_NOT_FOUND`); then existence of every foreign-key identifier in the request body (`ERR_REFERENCE_NOT_FOUND`); then state-machine legality of the requested transition, including the requirement that a royalty statement be `OPEN` before it can be recomputed (`ERR_INVALID_STATE`); then the event-mutability gate for booking creation and scratching (`ERR_EVENT_NOT_MUTABLE`); and only then the domain-specific business, temporal, and fiscal rules described throughout §3 (including the medical clearance protocol, booking eligibility, visa coverage, agreement overlap, arena and talent scheduling conflicts, anchor-day alignment, territory-right conflicts, distribution-window timing, territory licensing, likeness rights, event type, roster minimums, readiness thresholds, visa windows, and merch windows), with malformed payloads, invalid enums, non-positive quantities, and end-before-start dates caught last as `ERR_INVALID_REQUEST` (HTTP 400). A failure at any step short-circuits the cascade, so the error returned is always the earliest applicable one in this ordering.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integer cents — `downside_guarantee_cents`, `unit_price_cents`, `royalty_cents`, `total_sales_cents`, and `total_royalty_cents` are integers, never fractional. Royalty rates are expressed in basis points (`royalty_rate_bp`), an integer from 0 to 5000 inclusive. Royalty arithmetic rounds **per line** using round-half-up to the nearest cent before any summation takes place; summing first and rounding once is explicitly not the rule. Wellness scores are decimal numbers kept to exactly 2 decimal places with round-half-up rounding, bounded between 0.00 and 100.00. Dates are `YYYY-MM-DD` strings, local times are 24-hour `HH:MM` strings, and instants are ISO 8601 UTC datetimes.

### 2.9. Nested Resource Retrieval and Path Validation

When an endpoint path contains multiple resource identifiers, the system validates each identifier's existence in strict left-to-right order, rejecting the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. For example, recording a same-day no-show correction addresses a booking through its parent event; if the event id does not exist, the request fails there before the booking id is ever examined. Reverse-lookup listings (a talent's agreements, a storyline's chapters, an event's merch sales, and so on) follow the same rule for their single path identifier.

## 3. Business Logic & Workflows

### 3.1. Talent Roster and Wellness Standing

A `TalentRelations` operator registers a performer by supplying their `ring_name`, their `legal_name`, and a `contractor_status` declaration. The only accepted value for `contractor_status` is `INDEPENDENT_CONTRACTOR`; any other value is rejected with `ERR_INVALID_REQUEST`, reflecting that the promotion engages every performer strictly as an independent contractor. New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score. The `roster_tier` is never edited directly; it changes only through the call-up decision described in §3.8.

A talent's `booking_mode` is a derived standing recomputed whenever `availability_status` changes, whenever `wellness_score` changes, or whenever a medical case opens or clears for that talent. The derivation is strictly ordered: a talent whose `availability_status` is `SUSPENDED` is `UNBOOKABLE`; otherwise a talent who is `INJURED` is `UNBOOKABLE`; otherwise a talent with any medical case still `OPEN` is `UNBOOKABLE`; otherwise a `wellness_score` of at least 70.00 makes the talent `BOOKABLE`; otherwise a score of at least 40.00 makes them `LIMITED`; anything below 40.00 is `UNBOOKABLE`. The boundaries are inclusive — a score of exactly 70.00 is `BOOKABLE`, while 69.99 is `LIMITED`. A `LIMITED` talent may only be booked onto `HOUSE_SHOW` events; an `UNBOOKABLE` talent may not be booked at all.

Suspension and reinstatement are `TalentRelations` prerogatives. Suspending a talent — the request carries a free-text `reason` — flips `availability_status` to `SUSPENDED` and re-derives `booking_mode`. Reinstating flips `availability_status` back from `SUSPENDED` to `ACTIVE`, unless a medical case for the talent is still `OPEN`, in which case the talent comes back as `INJURED` instead; either way `booking_mode` is re-derived. Both operations return the updated talent record.

### 3.2. Talent Agreements and Likeness Rights

A `ContractAdmin` drafts a **TalentAgreement** by naming the `talent_id`, an inclusive `start_date`, an exclusive `end_date`, an annual `downside_guarantee_cents` that may not be negative, a per-talent `royalty_rate_bp` between 0 and 5000 basis points, a `likeness_rights_granted` flag stating whether the promotion may sell merchandise bearing the performer's likeness, and a `min_appearances_per_quarter` floor (zero or greater) that drives the appearance-compliance calculation in §3.7. The `end_date` must be strictly after the `start_date`; a malformed window is rejected with `ERR_INVALID_REQUEST`. A new agreement begins life with its `status` set to `DRAFT`.

Windows for a single talent must never overlap under half-open semantics — two agreements for the same talent whose `[start_date, end_date)` intervals intersect are illegal, and adjacent agreements where one ends exactly when the next begins are fine. This rule is enforced twice: at draft creation, and again at activation, both rejections carrying `ERR_AGREEMENT_OVERLAP` (HTTP 422). While an agreement is still `DRAFT`, the `ContractAdmin` may revise any of its terms — `start_date`, `end_date`, `downside_guarantee_cents`, `royalty_rate_bp`, `likeness_rights_granted`, or `min_appearances_per_quarter` — through a partial edit; each accepted edit increments the agreement's `version` by 1, which is precisely the version the OCC guard in §2.6 watches.

Activation moves an agreement `DRAFT → ACTIVE`. Beyond the OCC version guard and the overlap re-check, activation requires that no other agreement for the same talent is currently `ACTIVE` or overlaps the window while in `DRAFT`; a violated precondition surfaces as `ERR_AGREEMENT_OVERLAP`, while an attempt to activate an agreement that is not in `DRAFT` surfaces as `ERR_INVALID_STATE`. A successful activation increments the agreement's `version` and recomputes the talent's `likeness_granted` flag: the flag is true exactly when the talent has at least one `ACTIVE` agreement with `likeness_rights_granted` set to true, and false otherwise. When the recomputation changes the flag, the talent's `version` is bumped. The same recomputation runs when an agreement later leaves `ACTIVE` — whether by clock-driven expiry at the agreement's `end_date` or by explicit termination — so the likeness flag always reflects the live contract position.

Termination is the disruptive path. A `ContractAdmin` terminating an `ACTIVE` agreement flips it to `TERMINATED`, recomputes `likeness_granted` as above, and then fires a two-hop cascade. Hop 1 scratches forward bookings: every booking of that talent still in `BOOKED` status on an event that is `SCHEDULED` with an `event_date` on or after the current logical clock date flips `BOOKED → SCRATCHED`. Hop 2 protects storyline continuity: for every storyline in `ACTIVE` status, if the hop-1 scratches leave that storyline with zero `BOOKED` bookings tagged with its id, the storyline flips `ACTIVE → CONCLUDED`. Both `EXPIRED` and `TERMINATED` are terminal.

### 3.3. Arenas, Broadcast Anchors, and the Touring Calendar

The touring calendar is built by a `TourPlanner`. Arenas are registered with a `name`, a `city`, an ISO 3166-1 alpha-2 `country_code`, a positive integer seating `capacity`, a non-negative `merch_booths` count, and an IANA `timezone`. Broadcast anchors model the weekly television grid: each anchor has a `name`, a `weekly_day_of_week` encoded as an integer from 1 (Monday) through 7 (Sunday), a `territory_code` naming where the broadcast airs, and a `must_have_event_each_week` flag which, when true, expresses the scheduling intent that exactly one `TELEVISION` event be scheduled on the anchor's day in every ISO week.

Events are created with a `name`, an `event_type` of `TELEVISION`, `PREMIUM`, or `HOUSE_SHOW`, the `arena_id` of the host venue, an `event_date` in the arena's local calendar, a `start_time` and `end_time` as 24-hour local times with the end strictly later than the start on the same day, a `tour_country_code` that drives visa logic, and the roster minimums `roster_min_main` and `roster_min_total` — the former zero or greater, the latter at least as large as the former. A `TELEVISION` event must reference an `anchor_id` and must actually land on that anchor's `weekly_day_of_week`; a missing anchor or a day mismatch is rejected with `ERR_ANCHOR_DATE_MISMATCH`. For `PREMIUM` and `HOUSE_SHOW` events the `anchor_id` is simply omitted. One further guard protects the calendar: an arena hosts at most one event per calendar date, evaluated at whole-day granularity regardless of hour overlap, so a second event on a date the arena is already taken is rejected with `ERR_ARENA_DATE_CONFLICT`. New events start in `SCHEDULED` status.

### 3.4. Bookings, Storylines, and Chapter Continuity

With an event `SCHEDULED`, the `TourPlanner` books talent onto segments. A booking names the `event_id`, the `talent_id`, the `segment_label` the talent is booked into (labels such as `MATCH_1` or `PROMO_2`), and optionally a `storyline_id` tagging the booking as advancing a storyline; the storyline tag is nullable and may be omitted. Booking creation enforces a battery of checks, evaluated in the order presented here — event mutability, then booking-mode eligibility, then visa coverage, then the double-booking conflict — so when several checks fail at once the earliest failing check's error is returned. The target event must still be `SCHEDULED` — booking onto an event that has moved on is rejected with `ERR_EVENT_NOT_MUTABLE`. The talent's `booking_mode` must permit the booking: `BOOKABLE` talent may be booked anywhere, `LIMITED` talent only onto `HOUSE_SHOW` events, and `UNBOOKABLE` talent nowhere, with violations rejected as `ERR_TALENT_UNBOOKABLE`. International travel requires paperwork: booking onto an event whose `tour_country_code` is anything other than `US` requires a `GRANTED` visa case for that talent whose `country_code` matches the event's `tour_country_code` and whose `required_by_date` is on or after the `event_date`, else the booking is rejected with `ERR_VISA_REQUIRED`. Finally, a talent may not be `BOOKED` on two `SCHEDULED` or `LOCKED` events on the same calendar date whose half-open `[start_time, end_time)` intervals overlap; such a conflict is rejected with `ERR_TALENT_DOUBLE_BOOKED`. A fresh booking starts in `BOOKED` status.

Storylines give the tour its narrative spine. A `StorylineEditor` creates a storyline with a `title`; it begins `PLANNED` with a `gap_count` of zero. Chapters attach the storyline to the calendar: planning a chapter names the `storyline_id` and the `event_id`, and the system assigns a `chapter_index` — the chapter's 1-based position within its storyline, ordered by the event's `event_date` ascending, with ties broken by the event's `created_at` ascending. A chapter starts `PLANNED`. A storyline can only be activated — `PLANNED → ACTIVE` — while it has at least one chapter still `PLANNED`; activation with none is rejected with `ERR_INVALID_STATE`.

Completing and cancelling events drive the chapter machinery. When an event completes, each of its `PLANNED` chapters flips to `COMPLETED` and the owning storyline's `gap_count` resets to 0 — consecutive-gap semantics mean a completed chapter wipes the slate. When an event is cancelled, each of its `PLANNED` chapters flips to `MISSED` and the owning storyline's `gap_count` increases by 1; a storyline whose `gap_count` reaches 3 flips `ACTIVE → SHELVED`, and the shelving sweep then flips all of its remaining `PLANNED` chapters to `MISSED` **without** further incrementing `gap_count`. A `SHELVED` storyline may be revived by the `StorylineEditor`, returning to `ACTIVE` with `gap_count` reset to 0. A storyline may be concluded manually once every one of its chapters sits in a terminal state (`COMPLETED` or `MISSED`); it may also be concluded by the system when a terminating agreement scratches its last `BOOKED` booking, as described in §3.2. Both `SHELVED` and `CONCLUDED` are terminal from the storyline's perspective, with revive as the single escape hatch from `SHELVED`.

Scratches interact with the gap rule from the other direction. A `TourPlanner` may scratch a booking while its event is still `SCHEDULED`, flipping it `BOOKED → SCRATCHED`; scratching against an event in any other state is rejected with `ERR_EVENT_NOT_MUTABLE`. When a scratched booking carried a `storyline_id`, the gap rule is re-evaluated for that storyline on the chapter's event — a scratch that leaves the storyline with no `BOOKED` presence there contributes to the consecutive-gap accounting. Individual scratches never increment `gap_count` by themselves; the increments arrive through the chapter miss path.

### 3.5. Running the Event: Lock, Complete, Cancel, No-Show

Locking is the point of no return for the card. A `TourPlanner` locks a `SCHEDULED` event once the roster minimums are satisfied: the count of `BOOKED` bookings on the event must reach `roster_min_total`, and among those the count whose talent holds the `MAIN_ROSTER` tier must reach `roster_min_main`. A shortfall in either count is rejected with `ERR_ROSTER_MINIMUM_UNMET` (HTTP 422); the OCC guard of §2.6 applies to the lock call, and a stale `expected_event_version` is rejected with `ERR_STALE_VERSION` before the roster counts are even consulted. A successful lock moves the event `SCHEDULED → LOCKED` and increments its `version` by 1.

Completing a `LOCKED` event fires a broad sweep. Every booking still `BOOKED` flips to `FULFILLED`, and each fulfilled booking credits its talent 3.00 wellness points via the accrual rule, with the score ceiling at 100.00 and `booking_mode` re-derived afterward. Every `PLANNED` chapter attached to the event flips to `COMPLETED`, resetting its storyline's `gap_count` to 0. And the merchandise window slams shut: from completion onward, any attempt to record a merch sale against the event is rejected with `ERR_MERCH_WINDOW_CLOSED` — the same rejection that applies to `CANCELLED` events.

Cancelling a `SCHEDULED` event unwinds everything downstream. Every `BOOKED` booking flips to `SCRATCHED`; every `PLANNED` chapter flips to `MISSED` with the gap-count increments and shelving rule of §3.4; and every distribution window on the event still `PROVISIONAL` or `PUBLISHED` flips to `REVOKED`.

One correction path survives completion. On the same calendar day as the event — the logical clock date must equal the event's `event_date` — a `TourPlanner` may flip a `FULFILLED` booking to `NO_SHOW` through the nested event-and-booking path. This same-day correction first reverses the 3.00 fulfilled credit and then applies the 8.00 no-show penalty, for a net swing of 11.00 points against the fulfilled state, floored at 0.00; the talent's `booking_mode` is re-derived after the adjustment. Once the clock rolls past the event date the correction window closes and any no-show attempt is rejected. `SCRATCHED` and `NO_SHOW` are terminal booking states alongside `FULFILLED`.

### 3.6. Wellness Accrual and Decay

The `wellness_score` is a clamped accumulator over the range 0.00 to 100.00, kept to two decimal places. Fulfilled bookings add 3.00 points; no-shows subtract 8.00 (applied after the fulfilled-credit reversal, per §3.5); and the weekly decay subtracts 1.00 each time the logical clock crosses a Monday 00:00 UTC boundary — but only for talent holding the `MAIN_ROSTER` tier, since `DEVELOPMENTAL` talent is skipped by the decay sweep. Every change to the score, from whatever source, triggers a fresh `booking_mode` derivation per §3.1.

### 3.7. Premium Distribution: Partners, Rights, and Windows

Premium events are monetized through streaming partners, managed end-to-end by a `DistributionManager`. A partner is registered with a `name` and a short `partner_code` and starts `ACTIVE`; partners may be `SUSPENDED`, a status with no outgoing transitions in this version of the system.

Territory rights license a partner to carry programming in a territory over a window. Creating a right names the `partner_id`, the `territory_code`, an inclusive `window_start_date`, an exclusive `window_end_date` strictly after the start, and an `exclusive` flag. Overlap rules run at half-open date granularity, so adjacent rights where one window's end equals the other's start are legal. An **exclusive** right conflicts with any other right on the same `territory_code` whose window intersects it. Two **non-exclusive** rights for the same territory and the *same* partner may not overlap (the self-overlap ban), while non-exclusive rights across *different* partners may overlap freely. Any conflict is rejected with `ERR_TERRITORY_RIGHT_CONFLICT` (HTTP 422).

A distribution window opens a specific premium event to a partner in a territory, and it is where the timing rules bite. Creation names the `event_id`, the `partner_id`, the `territory_code`, a `window_type` of `LIVE` or `REPLAY`, and half-open UTC instants `opens_at` (inclusive) and `closes_at` (exclusive, strictly after the open). The target event must be `PREMIUM` — otherwise `ERR_EVENT_NOT_PREMIUM`. The territory must be licensed: the same partner must hold a `TerritoryRight` on the `territory_code` whose window spans the distribution window's dates, and that partner's status must be `ACTIVE`; a gap in licensing is rejected with `ERR_TERRITORY_NOT_LICENSED`. Timing depends on the window type: a `LIVE` window may open no earlier than 30 minutes before the event's start instant in UTC, and a `REPLAY` window may open no earlier than 24 hours after the event's end instant in UTC. Because an event's `event_date`, `start_time`, and `end_time` are expressed in the host arena's local calendar (§3.3), the event's start and end instants in UTC are derived by interpreting those local date/time fields through the host arena's IANA `timezone`. Two windows from the same partner on the same territory for the same event must not overlap under half-open semantics — touching windows, where one's `closes_at` equals the other's `opens_at`, do not conflict. Timing or overlap violations are rejected with `ERR_WINDOW_OVERLAP`. Different partners never collide on an event-and-territory pair because territory exclusivity is enforced upstream by the right-level rules. A new window starts `PROVISIONAL`.

Publishing a `PROVISIONAL` window moves it to `PUBLISHED`; the owning event must be `SCHEDULED` or `LOCKED` at publish time, and the windowing rules — the `LIVE` pre-open bound, the `REPLAY` delay bound, and half-open non-overlap per partner and territory — are re-checked at publish, with violations again rejected as `ERR_WINDOW_OVERLAP`. Licensing, by contrast, is pinned at creation: publish does **not** re-check territory licensing, so a right that lapses after creation does not block publishing. Revocation flips a window to `REVOKED` from either `PROVISIONAL` or `PUBLISHED`, and the same destination is reached automatically for any `PROVISIONAL` or `PUBLISHED` window when its event is cancelled. `REVOKED` is terminal.

### 3.8. Merchandise Sales and Royalty Statements

Venue merchandise is run by `MerchOps`, who record each sale line with the `event_id`, the `talent_id` whose likeness the item bears, a positive integer `quantity`, a non-negative `unit_price_cents`, and the UTC `sold_at` instant. Two gates guard the sale. First, likeness rights: the talent must have `likeness_granted` set true — which, per §3.2, means an `ACTIVE` agreement with `likeness_rights_granted` — else the sale is rejected with `ERR_LIKENESS_NOT_GRANTED`. Second, the merch window: a sale against a `COMPLETED` or `CANCELLED` event is rejected with `ERR_MERCH_WINDOW_CLOSED`. A non-positive `quantity` is rejected with `ERR_INVALID_REQUEST`. Each accepted line is immutable and carries a computed `royalty_cents`.

The royalty rate applied to a line is tiered, and the tier is chosen by the talent's **event-day gross**, not by the line's own value: the day gross is the sum of `quantity` times `unit_price_cents` across all of that talent's merch lines on the same event with the same `sold_at` calendar date. When the day gross exceeds 250,000 cents, the rate is the agreement's `royalty_rate_bp` plus a 200-basis-point bonus. When the day gross is at least 100,000 cents but does not exceed the upper threshold, the rate is the agreement's `royalty_rate_bp` unchanged. Below 100,000 cents, the rate is the agreement's rate minus a 100-basis-point discount. Each line's `royalty_cents` is then the line's `quantity` times `unit_price_cents` times the applicable rate in basis points, divided by 10,000, rounded half-up to a whole cent — and this rounding happens per line, before any summation.

Royalty statements aggregate lines for a talent over a period. A `ContractAdmin` opens a statement with the `talent_id`, an inclusive `period_start_date`, an exclusive `period_end_date`, and a `basis_mode` of `PROVISIONAL` or `FINAL` that selects the royalty variant. The statement's `total_sales_cents` is the sum of `quantity` times `unit_price_cents` over the included lines, and its `total_royalty_cents` is the sum of the per-line rounded `royalty_cents` under the selected variant; a denormalized `event_id` pointer records the merch event context when the statement draws from a single event, and is null when it spans several. The variant determines which lines are included: a `PROVISIONAL`-basis statement includes only lines on events that are `LOCKED` or `COMPLETED` at recompute time, while a `FINAL`-basis statement includes only lines on events that are `COMPLETED` at finalize time. Included lines are those whose `sold_at` date falls within the half-open period. Opening a statement performs an initial recompute immediately; a statement still `OPEN` may be recomputed on demand (recompute against a non-`OPEN` statement is rejected with `ERR_INVALID_STATE`). Finalization is reserved for `FINAL`-basis statements: attempting to finalize a `PROVISIONAL`-basis statement is rejected with `ERR_STATEMENT_NOT_FINALIZABLE`. A finalized statement — `status` moved from `OPEN` to `FINALIZED` — has its totals frozen and the record becomes read-only, with `FINALIZED` terminal.

### 3.9. Appearance Compliance

Each agreement's `min_appearances_per_quarter` floor is audited on demand through the talent's appearance-compliance readout, available to `TalentRelations` and `ContractAdmin`. The readout reports the current calendar `quarter` — the quarter containing the logical clock date — together with three integer counts. `committed` counts the talent's `FULFILLED` bookings on events dated within the elapsed part of the quarter. `projected` counts the talent's `BOOKED` bookings on `SCHEDULED` or `LOCKED` events dated in the remainder of the quarter after the logical clock date. The `shortfall` is the agreement's floor minus committed minus projected, floored at zero. The evaluation order is pinned despite its circular look: first resolve the set of the talent's bookings whose event dates fall inside the quarter; then select the agreement that is `ACTIVE` on the **last** day of the quarter — not the first; then compute the counts against that agreement's floor. A quarter boundary where agreements switch therefore uses the successor agreement's floor.

### 3.10. Medical Cases, Clearances, and the Segregation of Duties

When a performer is hurt, a `Medic` opens a **MedicalCase** with the `talent_id` and a `severity` of `MINOR` or `MAJOR`. Creation alone has teeth: the talent's `availability_status` flips `ACTIVE → INJURED` immediately, and every `BOOKED` booking of that talent on `SCHEDULED` events whose `event_date` falls within 30 days of the logical clock flips to `SCRATCHED` — the injury scratch horizon — with each scratch re-evaluating storyline gaps per §3.4. The case record accumulates an `evaluation_ids` list as evaluations attach, holds a `clearance_id` that stays null until the case clears, and sits in `OPEN` status.

Evaluations are added to an open case by any `Medic`; the evaluation record carries the `medical_case_id` of the case it attaches to along with the `evaluator_id` (the evaluating medic's `X-User-ID`), a `findings` narrative, and a `recommends_clearance` boolean. Clearance is deliberately hard. Issuing a clearance requires the case to be `OPEN`, requires at least two evaluations with `recommends_clearance` true from **distinct** evaluator ids, and requires the clearing medic — identified by the request's `cleared_by`, the issuing medic's `X-User-ID` — to differ from every evaluator on the case; any shortfall is rejected with `ERR_CLEARANCE_PROTOCOL_VIOLATION` (HTTP 422). The clearance record itself carries its own `medical_case_id` pointing back to the case. A successful clearance creates the **MedicalClearance** record with the system-stamped `cleared_at` instant taken from the logical clock, flips the case `OPEN → CLEARED`, points `clearance_id` at the new clearance, flips the talent `INJURED → ACTIVE`, bumps the talent's `version`, and re-derives `booking_mode`. `CLEARED` is terminal.

### 3.11. International Logistics and Visa Processing

A `LogisticsCoordinator` opens a **VisaCase** for a talent with the destination `country_code` and a `required_by_date` naming the latest acceptable grant date. The case begins `DRAFT`. Submitting the application moves it to `SUBMITTED` and is only allowed while the `required_by_date` is strictly after the current logical clock date; a submit attempted once the date has been reached or passed is rejected with `ERR_VISA_WINDOW_PASSED`. From `SUBMITTED`, the case resolves one of two ways. Recording a grant moves it to `GRANTED`, permitted only while the logical clock date is on or before the `required_by_date` — a grant recorded after the deadline is likewise rejected with `ERR_VISA_WINDOW_PASSED`. Recording a denial moves it to `DENIED` and fires the booking cascade: every `BOOKED` booking of that talent on `SCHEDULED` events whose `tour_country_code` matches the case's `country_code` and whose `event_date` is on or before the `required_by_date` flips to `SCRATCHED`, and each scratch re-evaluates storyline gaps. Both `GRANTED` and `DENIED` are terminal. The `GRANTED` state is what the booking rule of §3.4 consults for international events.

### 3.12. Developmental Call-Ups

Moving a performer from developmental to the main roster is a `TalentRelations` decision recorded as a **CallUpDecision**. The request carries a `decision` of `PROMOTE` or `DEFER`; the deciding operator's `X-User-ID` is recorded as `decided_by`. At decision time the system computes and stores a `readiness_score` from the trailing 90 days relative to the logical clock: take the count of the talent's `FULFILLED` bookings on `HOUSE_SHOW` events in the window, multiply by 4; subtract the count of `NO_SHOW` bookings in the window multiplied by 10; add the talent's current `wellness_score` multiplied by 0.5 and rounded half-up to a whole number; then clamp the result into the 0-to-100 range as an integer score. When several decisions land for different talents on the same day, their ordering ties are broken by the talents' `created_at` ascending — never by id.

A `PROMOTE` decision succeeds only when the readiness score reaches at least 60 and the talent has no `OPEN` medical case; otherwise the decision is rejected with `ERR_READINESS_THRESHOLD_UNMET` (HTTP 422). A successful promotion flips the talent's `roster_tier` from `DEVELOPMENTAL` to `MAIN_ROSTER` — the only path by which that field ever changes — which in turn subjects the talent to the weekly wellness decay of §3.6. A `DEFER` decision simply records the score and leaves the roster tier untouched. The full decision history for a talent can be listed back by `TalentRelations`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or advance the logical clock return `200 OK`. All list endpoints follow the pagination contract of §2.3 and the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/touring/_clock/set_current_utc` | Advance the logical clock; triggers wellness decay and agreement expiry sweeps | ContractAdmin |
| POST | `/touring/talents` | Register a performer (independent contractor, developmental tier) | TalentRelations |
| GET | `/touring/talents` | List talents with optional filters | TalentRelations, TourPlanner, StorylineEditor, MerchOps, Medic, ContractAdmin, LogisticsCoordinator, DistributionManager |
| GET | `/touring/talents/{id}` | Fetch one talent | TalentRelations, TourPlanner, StorylineEditor, MerchOps, Medic, ContractAdmin, LogisticsCoordinator, DistributionManager |
| POST | `/touring/talents/{id}/suspend` | Suspend a talent (wellness/disciplinary) | TalentRelations |
| POST | `/touring/talents/{id}/reinstate` | Lift a suspension | TalentRelations |
| POST | `/touring/talents/{id}/call-up` | Developmental to main roster call-up decision | TalentRelations |
| GET | `/touring/talents/{id}/call-up-decisions` | List call-up decisions for a talent | TalentRelations |
| GET | `/touring/talents/{id}/appearance-compliance` | Appearance obligation shortfall for the current quarter | TalentRelations, ContractAdmin |
| GET | `/touring/talents/{id}/medical-cases` | Reverse lookup of medical cases for a talent | Medic, TalentRelations |
| GET | `/touring/talents/{id}/visa-cases` | Reverse lookup of visa cases for a talent | LogisticsCoordinator, TalentRelations |
| GET | `/touring/talents/{id}/agreements` | Reverse lookup of agreements for a talent | ContractAdmin, TalentRelations |
| POST | `/touring/agreements` | Draft a talent agreement | ContractAdmin |
| GET | `/touring/agreements` | List agreements (reverse lookup by talent) | ContractAdmin, TalentRelations |
| GET | `/touring/agreements/{id}` | Fetch one agreement | ContractAdmin, TalentRelations |
| PATCH | `/touring/agreements/{id}` | Edit DRAFT agreement terms | ContractAdmin |
| POST | `/touring/agreements/{id}/activate` | Activate a DRAFT agreement (OCC-guarded) | ContractAdmin |
| POST | `/touring/agreements/{id}/terminate` | Terminate an ACTIVE agreement | ContractAdmin |
| POST | `/touring/arenas` | Register an arena | TourPlanner |
| GET | `/touring/arenas/{id}` | Fetch one arena | TourPlanner, LogisticsCoordinator, MerchOps |
| POST | `/touring/broadcast-anchors` | Register a weekly television broadcast anchor | TourPlanner |
| GET | `/touring/broadcast-anchors/{id}` | Fetch one anchor | TourPlanner |
| POST | `/touring/events` | Schedule an event (TELEVISION requires anchor and anchor-day match) | TourPlanner |
| GET | `/touring/events` | List events with optional filters | TourPlanner, StorylineEditor, MerchOps, DistributionManager, LogisticsCoordinator, TalentRelations |
| GET | `/touring/events/{id}` | Fetch one event | TourPlanner, StorylineEditor, MerchOps, DistributionManager, LogisticsCoordinator, TalentRelations |
| POST | `/touring/events/{id}/lock` | Lock an event after roster minimums are met (OCC-guarded) | TourPlanner |
| POST | `/touring/events/{id}/complete` | Complete a locked event; fulfills bookings, advances chapters, freezes merch | TourPlanner |
| POST | `/touring/events/{id}/cancel` | Cancel a scheduled event; scratches bookings, gaps storylines, revokes windows | TourPlanner |
| POST | `/touring/bookings` | Book a talent onto an event segment | TourPlanner |
| GET | `/touring/bookings` | List bookings with optional filters | TourPlanner, TalentRelations, StorylineEditor, MerchOps |
| GET | `/touring/bookings/{id}` | Fetch one booking | TourPlanner, TalentRelations, StorylineEditor, MerchOps |
| POST | `/touring/bookings/{id}/scratch` | Scratch a booking from a still-scheduled event | TourPlanner |
| POST | `/touring/events/{event_id}/bookings/{id}/no-show` | Same-day correction: flip a FULFILLED booking to NO_SHOW on a COMPLETED event | TourPlanner |
| POST | `/touring/storylines` | Create a storyline | StorylineEditor |
| GET | `/touring/storylines/{id}` | Fetch one storyline | StorylineEditor, TourPlanner |
| GET | `/touring/storylines/{id}/chapters` | Reverse lookup of chapters for a storyline | StorylineEditor, TourPlanner |
| POST | `/touring/storylines/{id}/activate` | Activate a planned storyline | StorylineEditor |
| POST | `/touring/storylines/{id}/conclude` | Conclude an active storyline whose chapters are all terminal | StorylineEditor |
| POST | `/touring/storylines/{id}/revive` | Revive a shelved storyline, resetting gap_count | StorylineEditor |
| POST | `/touring/chapters` | Plan a chapter of a storyline for an event | StorylineEditor |
| GET | `/touring/chapters` | List chapters with optional filters | StorylineEditor, TourPlanner |
| GET | `/touring/events/{id}/chapters` | Reverse lookup of chapters for an event | StorylineEditor, TourPlanner |
| POST | `/touring/streaming-partners` | Register a streaming partner | DistributionManager |
| GET | `/touring/streaming-partners` | List streaming partners | DistributionManager |
| GET | `/touring/streaming-partners/{id}` | Fetch one partner | DistributionManager |
| POST | `/touring/territory-rights` | Grant a territory right window to a partner | DistributionManager |
| GET | `/touring/territory-rights` | List territory rights (reverse lookup by partner) | DistributionManager |
| GET | `/touring/territory-rights/{id}` | Fetch one territory right | DistributionManager |
| POST | `/touring/distribution-windows` | Open a distribution window for a PREMIUM event in a licensed territory | DistributionManager |
| GET | `/touring/distribution-windows` | List windows (reverse lookup by event/partner) | DistributionManager |
| GET | `/touring/distribution-windows/{id}` | Fetch one window | DistributionManager |
| POST | `/touring/distribution-windows/{id}/publish` | Publish a provisional window | DistributionManager |
| POST | `/touring/distribution-windows/{id}/revoke` | Revoke a window | DistributionManager |
| POST | `/touring/merch-sales` | Record a venue merchandise sale line (immutable) | MerchOps |
| GET | `/touring/merch-sales/{id}` | Fetch one merch sale line | MerchOps, ContractAdmin |
| GET | `/touring/merch-sales` | List merch sale lines (reverse lookup by event/talent) | MerchOps, ContractAdmin |
| GET | `/touring/events/{id}/merch-sales` | Reverse lookup of merch sales for an event | MerchOps, ContractAdmin |
| POST | `/touring/royalty-statements` | Open a royalty statement for a talent and period | ContractAdmin |
| GET | `/touring/royalty-statements/{id}` | Fetch one statement | ContractAdmin |
| GET | `/touring/royalty-statements` | List statements (reverse lookup by talent) | ContractAdmin |
| POST | `/touring/royalty-statements/{id}/recompute` | Recompute an OPEN statement's totals | ContractAdmin |
| POST | `/touring/royalty-statements/{id}/finalize` | Finalize a FINAL-basis statement | ContractAdmin |
| POST | `/touring/medical-cases` | Open a medical case; talent becomes INJURED and near-term bookings scratch | Medic |
| GET | `/touring/medical-cases/{id}` | Fetch one medical case | Medic |
| GET | `/touring/medical-cases/{id}/evaluations` | Reverse lookup of evaluations for a case | Medic |
| POST | `/touring/medical-cases/{id}/evaluations` | Add a medical evaluation to an open case | Medic |
| POST | `/touring/medical-cases/{id}/clearances` | Issue clearance; requires 2 recommending evaluations and a different clearing medic | Medic |
| GET | `/touring/medical-cases/{id}/clearances` | Reverse lookup of clearances for a case (0 or 1) | Medic |
| POST | `/touring/visa-cases` | Open a visa case for international tour logistics | LogisticsCoordinator |
| GET | `/touring/visa-cases/{id}` | Fetch one visa case | LogisticsCoordinator |
| POST | `/touring/visa-cases/{id}/submit` | Submit the visa application | LogisticsCoordinator |
| POST | `/touring/visa-cases/{id}/grant` | Record visa grant | LogisticsCoordinator |
| POST | `/touring/visa-cases/{id}/deny` | Record visa denial; scratches affected bookings | LogisticsCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EVENT_NOT_MUTABLE` | 409 |
| `ERR_AGREEMENT_OVERLAP` | 422 |
| `ERR_ARENA_DATE_CONFLICT` | 422 |
| `ERR_TALENT_DOUBLE_BOOKED` | 422 |
| `ERR_ANCHOR_DATE_MISMATCH` | 422 |
| `ERR_TERRITORY_RIGHT_CONFLICT` | 422 |
| `ERR_WINDOW_OVERLAP` | 422 |
| `ERR_TERRITORY_NOT_LICENSED` | 422 |
| `ERR_EVENT_NOT_PREMIUM` | 422 |
| `ERR_LIKENESS_NOT_GRANTED` | 422 |
| `ERR_TALENT_UNBOOKABLE` | 422 |
| `ERR_VISA_REQUIRED` | 422 |
| `ERR_CLEARANCE_PROTOCOL_VIOLATION` | 422 |
| `ERR_ROSTER_MINIMUM_UNMET` | 422 |
| `ERR_READINESS_THRESHOLD_UNMET` | 422 |
| `ERR_VISA_WINDOW_PASSED` | 422 |
| `ERR_MERCH_WINDOW_CLOSED` | 422 |
| `ERR_STATEMENT_NOT_FINALIZABLE` | 422 |
