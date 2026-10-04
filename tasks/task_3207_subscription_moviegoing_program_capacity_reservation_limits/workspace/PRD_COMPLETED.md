# Subscription Moviegoing API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Subscription Moviegoing Program Capacity & Reservation Limits API — the backend for a flat-fee cinema membership service in the style of AMC Stubs A-List. For a fixed monthly fee, a member receives a bounded number of seat reservations per program week, with unused weekly entitlements rolling over into the following week up to a plan-defined cap. The program grants qualifying members access to premium presentation formats (IMAX, Dolby, 3D) at no surcharge, which compresses yield on high-demand showings and forces the system to manage capacity deliberately rather than treat subscription seats as free inventory.

The operating tensions the API must resolve are threefold. First, anti-hoarding and fairness: subscribers may hold only a limited number of future-dated reservations at once, must cancel inside a defined window, and incur no-show strikes that escalate to account suspension when attendance abuse accumulates. Second, yield protection: on a film's opening weekend, subscription reservations may occupy no more than a configurable percentage of an auditorium, so full-price ticket buyers are not displaced. Third, settlement integrity: studios are owed an admission report for every subscription reservation that reached check-in or no-show, valued at a flat contract rate rather than zero, even though the theater collected no per-ticket revenue from the subscriber.

Membership itself is a first-class lifecycle: plans are drafted, published, and retired by program administration; members enroll, pause, resume, cancel, and face a mandatory rejoin waiting period after cancellation. All of this runs on a controllable logical clock that drives week rollovers, credit bucket grants, hold expiries, no-show sweeps, strike expirations, suspension lifts, and showtime locking, so that the entire temporal surface of the program is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `ProgramAdmin`, `MemberServices`, `Member`, `TheaterStaff`, and `StudioRep`.

- A `ProgramAdmin` is the platform operator: they manage subscription plans, theaters, auditoriums, showtimes, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's foreign key.
- A `MemberServices` operator handles the member lifecycle — registration, activation, unsuspension, closure, goodwill strike reversals, loyalty adjustments, and agent-assisted enrollment. When `X-User-Role` is `MemberServices`, `X-User-ID` is likewise an opaque operator identifier with no entity backing.
- A `Member` is the subscribing moviegoer and acts only on their own resources. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a member compare the resource's `member_id` field against `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- A `TheaterStaff` operator performs check-ins, rings up concession purchases, and prepares settlement reports for their theater. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; because no theater binding is persisted for staff operators, no per-theater scope check is enforced — any `TheaterStaff` operator may act on any theater.
- A `StudioRep` is the studio's settlement counterparty, empowered to acknowledge or dispute submitted reports and to read settlement data, theaters, and showtimes. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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
- Requests to undefined routes, or to a defined route with an unsupported method, are rejected in the same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. All list endpoints sort by `created_at` in ascending order unless otherwise specified, breaking ties by `id` ascending. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix, emitted in the canonical hyphenated 8-4-4-4-12 hexadecimal form (for example `3f6b1c2e-4a5d-4e6f-8a9b-0c1d2e3f4a5b`). The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is a system-managed integer that increments by exactly one on every mutation to the resource and underpins optimistic concurrency control. Every ISO 8601 timestamp the server emits on a resource or in a response — not only `created_at` and `updated_at`, but also instants such as `starts_at`, `cancel_deadline`, `paused_at`, `pause_resume_at`, `cancelled_at`, `rejoin_locked_until`, `suspended_until`, `issued_at`, `expires_at`, `period_start`, `period_end`, and `current_utc` — carries exactly three fractional digits and the `Z` suffix (for example `2026-09-01T00:00:00.000Z`). Date-only fields such as `cycle_anchor_date` are plain ISO 8601 dates with no time component.

Two resources are deliberately leaner. A `LoyaltyLedgerEntry` and a `SettlementLine` are append-only records: each carries `id` and `created_at` only, and both `updated_at` and `version` are absent from them entirely. Every other entity in this document — `Member`, `SubscriptionPlan`, `Subscription`, `ReservationCreditBucket`, `Theater`, `Auditorium`, `Showtime`, `Reservation`, `NoShowStrike`, `ConcessionPurchase`, and `SettlementReport` — carries the full four-field set.

### 2.5. The Logical Clock and Temporal Determinism

The system does not consult the wall clock for any business decision. A single logical clock governs every time-based transition: week rollovers and credit-bucket granting, bucket and hold expiry, no-show sweeps, strike expiry, suspension lifts, pause auto-resume, billing-cycle rollover, and showtime locking. At startup the clock reads exactly 2026-09-01T00:00:00Z, and before any explicit set call it continues to read exactly that instant. A `ProgramAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant; a `to_iso8601` earlier than the current clock value is rejected with `ERR_INVALID_REQUEST` (the clock never moves backward). When the clock crosses any deadline, every time-based transition whose deadline is at or before the new clock value fires, and the response reports the new `current_utc`. Crossing a program-week boundary lazily creates the next week's `ReservationCreditBucket`; crossing a monthly billing-cycle boundary (the subscription's `cycle_anchor_date` plus a whole number of 30-day cycles) increments `current_cycle_index` and resets `pause_count_in_cycle` to zero.

### 2.6. Money, Points, and Seat Arithmetic

All money is integer cents; there is no floating-point money anywhere in the system. Discounts and valuations round down (floor) at the step the rule specifies and never elsewhere — in particular the concession discount is floored before subtraction, never after. Loyalty points are integers, computed with a single floor applied at the final step of the earn rule only. Reservation credits and seat counts are integers with no rounding at any step. The opening-weekend displacement comparison uses integer multiplication exclusively and never floating-point division.

### 2.7. Hierarchical Consistency and Cascading Mutations

The aggregate hierarchy runs from `Member` down through `Subscription` to `ReservationCreditBucket`, and separately from `Theater` through `Auditorium` to `Showtime`, with `Reservation` bridging the two trees. When a parent undergoes a transition that invalidates children — a member suspension, a subscription cancellation, a showtime cancellation — the system cascades the resolution into the child resources atomically with the parent transition: reservations are cancelled or expired, credits are refunded or forfeited per the refund rule, buckets expire, and seat counters are adjusted. Any such mutation to a resource refreshes its `updated_at` and increments its `version`, including mutations performed by the system itself without a client request on that specific resource.

### 2.8. Nested Resource Retrieval

Endpoints whose paths contain multiple resource identifiers validate existence strictly left-to-right. A request referencing a non-existent parent is rejected with `ERR_NOT_FOUND` (HTTP 404) before any child identifier is examined, and each subsequent path identifier is checked in turn. Body-supplied foreign keys are validated for existence under the same `ERR_NOT_FOUND` code before business rules run.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Reservation creation requires the request to carry `expected_showtime_version`, the client-observed `version` of the target `Showtime`. Plan change on a subscription requires `expected_subscription_version`, the client-observed `version` of the target `Subscription`. In both cases, if the supplied value does not match the parent entity's current `version` — because another writer has advanced the resource since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field, and requests must not include one.

### 2.10. Validation Priority Order

When several validations could reject the same request, they are evaluated in a fixed priority order, and the first failure encountered determines the error returned. The order is: (1) authentication header presence, (2) role permission for the endpoint, (3) existence of every path id and body foreign key, (4) entity-backed identity and scope (a `Member` acting only on resources whose `member_id` equals `X-User-ID`), (5) state admissibility of the requested transition — the gate at which reservation creation or confirmation against a `LOCKED`, `COMPLETED`, or `CANCELLED` showtime fails with `ERR_SHOWTIME_LOCKED` (a showtime still `SCHEDULED` fails this gate with `ERR_INVALID_STATE` instead), (6) optimistic-concurrency version match, (7) member-level suspension gates, (8) the rejoin lock on enrollment, (9) the member-initiated cancellation window, (10) the check-in window — which for the check-in endpoint itself is evaluated before the reservation-state gate, per §3.5, (11) premium-format eligibility, (12) weekly quota availability, (13) the anti-hoarding future-reservation cap, (14) seat capacity including the opening-weekend displacement cap, (15) pause policy, (16) settlement line settleability and report non-emptiness, and (17) plan enrollability — which is deliberately evaluated after the rejoin lock, so an enrollment that violates both surfaces `ERR_REJOIN_LOCKED`, not `ERR_PLAN_NOT_ENROLLABLE`.

## 3. Business Logic & Workflows

### 3.1. Members: Registration, Activation, and Account Lifecycle

A `MemberServices` operator registers a new member by supplying an `email` and a `full_name`. The account is created in `REGISTERED` status with `loyalty_points_balance` starting at zero. Account activation — the `REGISTERED → ACTIVE` transition performed by `MemberServices` — is account-level only: no subscription is required to activate a member, and activation simply flips `status` to `ACTIVE`.

A member's account status is deliberately distinct from their subscription status. The member lifecycle spans `REGISTERED`, `ACTIVE`, `SUSPENDED`, and `CLOSED`, while the subscription lifecycle (§3.3) spans its own states `ACTIVE`, `PAUSED`, and `CANCELLED`. `suspended_until` stays null except while the member is `SUSPENDED`, where it records the instant at which the suspension auto-lifts.

Closure is the terminal account event: `MemberServices` may move a member from `REGISTERED`, `ACTIVE`, or `SUSPENDED` to `CLOSED`, but only when the member holds no subscription in `ACTIVE` or `PAUSED` status; an open subscription blocks closure with `ERR_INVALID_STATE`. `CLOSED` is terminal — no transition leaves it.

### 3.2. Subscription Plans: Definition, Publication, Retirement

Program administration defines a `SubscriptionPlan` with a `code` (for example `ALIST_BASIC`; recorded as supplied, with no uniqueness enforcement), a `tier` of `BASIC`, `PLUS`, or `PREMIER`, a `monthly_fee_cents` price charged at each cycle anchor, a `weekly_reservation_quota` of base reservations per program week, a `max_rollover_credits` cap on week-to-week carryover, a `premium_format_allowed` flag governing no-surcharge premium access, a `max_future_reservations` anti-hoarding cap, a `loyalty_points_multiplier_pct` (100 for `BASIC`, 125 for `PLUS`, 150 for `PREMIER`), and a `concession_discount_pct` (0 for `BASIC`, 10 for `PLUS`, 15 for `PREMIER`).

Plans are born `DRAFT` and are not enrollable in that state. Publishing moves a plan `DRAFT → PUBLISHED` with no preconditions, making it enrollable. Retirement moves a plan `PUBLISHED → RETIRED`; from that moment new subscriptions referencing the plan are rejected with `ERR_PLAN_NOT_ENROLLABLE`, while existing subscriptions keep their current plan snapshot until their next cycle rollover. `RETIRED` is terminal.

### 3.3. Subscriptions: Enrollment, Pause, Resume, Cancellation, Rejoin

A member enrolls by supplying a `plan_id`, an operation open to the member themselves or to `MemberServices` acting on their behalf. Two temporal and catalog gates guard enrollment, in this order: first the rejoin lock — if any of the member's `CANCELLED` subscriptions still has `rejoin_locked_until` in the future (the greatest such instant governs), enrollment is rejected with `ERR_REJOIN_LOCKED`; then plan enrollability — a plan not currently `PUBLISHED` yields `ERR_PLAN_NOT_ENROLLABLE`. On success the subscription is created `ACTIVE` with `cycle_anchor_date` set to the enrollment date, `current_cycle_index` at zero, and the current week's credit bucket granted under the fresh-enrollment rule (§3.4). Enrollment while the member is `SUSPENDED` is blocked with `ERR_MEMBER_SUSPENDED` by the member-level gates described in §2.10; enrollment of a `CLOSED` member is rejected with `ERR_INVALID_STATE`. A `REGISTERED` (not yet activated) member may enroll — account activation is not a precondition. Enrollment does not require the absence of another `ACTIVE` subscription: a member may hold several concurrently, and wherever a rule resolves "the member's `ACTIVE` subscription plan" (§3.9) it uses the earliest-enrolled `ACTIVE` subscription.

Pausing is a member-initiated right with strict rationing. A pause moves the subscription `ACTIVE → PAUSED` (any other subscription state fails with `ERR_INVALID_STATE`), requires the member account itself to be `ACTIVE` — a `SUSPENDED` member's pause request is rejected with `ERR_MEMBER_SUSPENDED` — and is permitted at most once per billing cycle: if `pause_count_in_cycle` has already reached 1, the request fails with `ERR_PAUSE_LIMIT_REACHED`. The requested `pause_days` must lie between 7 and 30 inclusive; anything outside that range is rejected with `ERR_INVALID_REQUEST`, and this range check runs before the once-per-cycle limit check. On pause the system stamps `paused_at` with the current instant, schedules `pause_resume_at` at that instant plus the requested number of days, and increments `pause_count_in_cycle` by one. While `PAUSED`, no new reservations may be created against the subscription — existing `HELD` or `CONFIRMED` reservations remain valid — and weekly granting halts in the sense of §3.4: a bucket whose week opens during the pause is still created, but with `base_granted` of zero.

Resumption happens two ways. The system auto-resumes the subscription when the clock reaches `pause_resume_at` (inclusive — a clock value exactly equal to `pause_resume_at` fires the resume), or the member resumes early by explicit request; the manual path requires the subscription to be `PAUSED` (else `ERR_INVALID_STATE`) and the member account to be `ACTIVE` — a non-`ACTIVE` member's manual resume is rejected with `ERR_MEMBER_SUSPENDED`. Either path clears `paused_at` and `pause_resume_at` to null and restores `ACTIVE` status, and if the resume lands mid-week the current bucket receives the pro-rata top-up described in §3.4 — which, by construction of the rule, always restores the full weekly quota for the current week.

Cancellation is available from either `ACTIVE` or `PAUSED`. Cancelling stamps `cancelled_at`, sets `rejoin_locked_until` thirty days (the `REJOIN_WAIT_DAYS` constant) into the future, and moves the subscription to `CANCELLED`, which is terminal for that subscription row. The persisted and reported status of a cancelled subscription is `CANCELLED` in every read, whether or not the rejoin lock has elapsed — the lock is conveyed solely by the `rejoin_locked_until` timestamp, which the enrollment gate consults directly; no `REJOIN_LOCKED` status is ever stored or returned. Cancellation cascades in a fixed order: first every reservation of the subscription still in `HELD` or `CONFIRMED` is force-cancelled with its credit refunded per the refund rule of §3.5 regardless of the member-facing cancellation window — evaluated against the still-live bucket posture, so an `OPEN` or `EXHAUSTED` bucket is refunded — and only then are the current plus all future credit buckets moved to posture `EXPIRED`. After the lock window has elapsed, the member may enroll again on a fresh subscription row.

A plan change is a version-guarded operation available to the member or `MemberServices` from an `ACTIVE` or `PAUSED` subscription (any other state fails with `ERR_INVALID_STATE`). The request carries a `new_plan_id` together with `expected_subscription_version`; the new plan must exist but need not be `PUBLISHED` — plan enrollability is not re-checked on change, and no member-suspension gate applies. If the supplied version does not match the subscription's current `version` — because a pause, resume, or cycle rollover has advanced it since the client last read — the change is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the subscription's `plan_id` is updated, `version` increments by one, and bucket granting from the next week onward uses the new plan's quota and caps.

### 3.4. Weekly Credit Buckets: Granting, Rollover, and Posture

Every subscription accrues its entitlement through weekly `ReservationCreditBucket` records. A program week is anchored to the subscription: week `week_index` k covers the seven-day span beginning at `cycle_anchor_date` plus 7 times k days, and the pair (`subscription_id`, `week_index`) is unique.

At the moment a week opens for an `ACTIVE` subscription, the new bucket's `base_granted` is set to the plan's `weekly_reservation_quota`, and `rollover_in` is computed from the immediately previous week's bucket: take that bucket's `base_granted` plus its `rollover_in` minus its `credits_used`, cap the result at the plan's `max_rollover_credits`, and never let it fall below zero. The fresh-enrollment variant applies to week zero of a new subscription: `rollover_in` is unconditionally zero (there is no previous week), and `base_granted` is the full weekly quota regardless of which day within the week enrollment occurs. The paused-week variant applies when the subscription is `PAUSED` at the week-open instant: `base_granted` is zero, but `rollover_in` is still carried from the previous week as usual, so `credits_available` may be positive while paused — reservations remain blocked by state validation, not by credit exhaustion.

Resumption mid-week triggers the top-up: the current bucket's `base_granted` is raised up to the plan's `weekly_reservation_quota` — formally the pro-rata increase of the quota times the remaining days divided by 7 rounded up always evaluates to the full quota — so resuming always restores the full weekly quota for the current week, and a bucket already at full quota is left unchanged. The top-up applies only while the week is still live and the bucket has not been force-expired by a cancellation cascade.

A bucket's `credits_used` counts credits consumed by reservations created against it that sit in `HELD` or `CONFIRMED` status, and `credits_available` is `base_granted` plus `rollover_in` minus `credits_used`, never negative. The derived `posture` is `OPEN` while the week is live and credits remain, `EXHAUSTED` when `credits_available` reaches zero while the week is still open, and `EXPIRED` once the clock has passed the week's end (or once a cancellation cascade has expired it early). Reading a subscription's bucket list lazily materializes the current week's bucket if the clock has crossed a boundary since the last grant.

### 3.5. Reservations: Creation, Confirmation, Cancellation, Check-In, No-Show

A member creates a subscription reservation by supplying the `subscription_id` of an `ACTIVE` subscription, the target `showtime_id`, and `expected_showtime_version` — the client-observed `version` of the showtime. If that version no longer matches the showtime's current `version`, because another writer has taken or released seats on the same showing since the client last read it, creation is rejected with `ERR_STALE_VERSION` (HTTP 412); this is the serialization point that keeps a client from acting on a stale capacity view. Subscription reservations are single-seat: `seat_count` is fixed at exactly 1.

Creation runs the validation cascade of §2.10 against the member, the subscription, and the showtime. The member must be `ACTIVE` — a `SUSPENDED` member is rejected with `ERR_MEMBER_SUSPENDED` even if their subscription row still reads `ACTIVE`, while a member in any other non-`ACTIVE` state (`REGISTERED` or `CLOSED`) is rejected with `ERR_INVALID_STATE`. A subscription not in `ACTIVE` status likewise fails with `ERR_INVALID_STATE` — except that a `SUSPENDED` member whose subscription was force-paused by the suspension cascade surfaces `ERR_MEMBER_SUSPENDED` instead. The showtime must admit new reservations; a showtime that is `LOCKED`, `COMPLETED`, or `CANCELLED` fails the state gate with `ERR_SHOWTIME_LOCKED`. Premium-format showings — any showtime whose `format` is not `STANDARD`, a fact denormalized onto the reservation as `is_premium_format` — require the plan's `premium_format_allowed` to be true, else `ERR_PREMIUM_NOT_INCLUDED`. The current week's bucket must be in posture `OPEN` with at least one credit available, else `ERR_WEEKLY_QUOTA_EXHAUSTED`. The anti-hoarding cap of §3.8 must admit one more future reservation, else `ERR_FUTURE_RESERVATION_LIMIT`. Finally the capacity check of §3.7 must pass, else `ERR_CAPACITY_EXCEEDED`.

On success the reservation is created in `HELD` status: the current week's bucket is debited (`credits_used` increases by one and `credit_consumed` flips true), the showtime's `seats_held_subscription` increases by one, the showtime's `version` increments by one, and the reservation is stamped with its `bucket_id` and its `cancel_deadline` — the showtime's `starts_at` minus the program's cancellation window of 30 minutes (`CANCELLATION_WINDOW_MINUTES`).

A `HELD` reservation is provisional: the member must confirm it within 15 minutes of creation (`HOLD_TTL_MINUTES`), and confirmation additionally requires the showtime to be `ON_SALE`. The hold's lifetime boundary is inclusive on the expiry side: a hold is swept to `EXPIRED` once the clock reaches creation plus 15 minutes — at exactly that instant it is already expired — and the sweep fires lazily on a confirmation attempt as well as on clock advancement, so confirming an out-of-window hold moves it to `EXPIRED` on the spot and is rejected with `ERR_INVALID_STATE`. A hold that outlives its window without confirmation is auto-swept to `EXPIRED` by the system, releasing the seat and refunding the consumed credit in full whenever the originating bucket is not `EXPIRED` — hold expiry always refunds.

Cancellation distinguishes who asks. A member-initiated cancel of a `HELD` or `CONFIRMED` reservation is free strictly before `cancel_deadline`; at or after that instant it is rejected with `ERR_CANCEL_WINDOW_CLOSED` and no refund computation runs. System-cascade cancels — driven by subscription cancellation, member suspension, or showtime cancellation — carry no precondition and refund regardless of the deadline. The refund itself is governed by the originating bucket's posture: when the bucket is `OPEN` or `EXHAUSTED`, its `credits_used` decreases by one (an `EXHAUSTED` bucket may thereby reopen to `OPEN`); when the bucket is `EXPIRED`, the credit is forfeited and `credits_used` is unchanged. Every cancellation that succeeds, from `HELD` or `CONFIRMED`, releases the seat by decrementing the showtime's `seats_held_subscription` by one.

Check-in is performed by `TheaterStaff` on a `CONFIRMED` reservation. The showtime must be `ON_SALE` or `LOCKED` — a showtime in any other state fails with `ERR_INVALID_STATE` — and the instant must fall inside the window from 45 minutes before `starts_at` to 30 minutes after it, both bounds inclusive; a check-in outside that window is rejected with `ERR_CHECKIN_WINDOW`. For this endpoint the window is evaluated before the reservation-state gate: because the no-show grace of §3.5 below is exactly the window's upper bound, a `CONFIRMED` reservation presented after `starts_at` plus 30 minutes is definitionally outside the window — the system sweeps that overdue reservation to `NO_SHOW` on the spot and rejects the check-in with `ERR_CHECKIN_WINDOW` rather than `ERR_INVALID_STATE`. A successful check-in moves the reservation to `CHECKED_IN`, makes it settleable as an admission, and appends an `EARN_ADMISSION` loyalty ledger entry per §3.9.

A `CONFIRMED` reservation that is never checked in is swept to `NO_SHOW` once the clock passes `starts_at` plus 30 minutes of grace (`NO_SHOW_GRACE_MINUTES`) — strictly after that instant: the grace boundary and the inclusive check-in upper bound coincide, and at exactly `starts_at` plus 30 minutes the no-show sweep does not fire, so a check-in at that instant is evaluated against a reservation still in `CONFIRMED` and succeeds. The sweep instant is anchored to `starts_at` plus grace alone, independent of the film's `runtime_minutes`; the runtime enters only the showtime's own `LOCKED → COMPLETED` sweep of §3.6. The no-show cascade has four consequences: the showtime's `seats_held_subscription` decreases by one (the seat is released); the consumed credit is not refunded; a `NoShowStrike` is appended for the member with `issued_at` at the sweep instant and `expires_at` ninety days later (`STRIKE_WINDOW_DAYS`); and the member's `no_show_strikes_active` is recomputed, firing the suspension ladder of §3.10. Critically, a `NO_SHOW` reservation remains settleable — studios are owed an admission report regardless of attendance.

### 3.6. Theaters, Auditoriums, and Showtimes

A `ProgramAdmin` registers a `Theater` with a `name` and an IANA `timezone` used for showtime-local computations (the string is stored as supplied, with no format validation); the theater is born `OPERATING`. A theater may go `DARK`, and a `DARK` theater rejects new showtimes with `ERR_INVALID_STATE`. Within a theater, administration adds each `Auditorium` with a `label`, a fixed physical `seat_count`, and `supported_formats` drawn from `STANDARD`, `IMAX`, `DOLBY`, and `THREE_D`.

Scheduling a showtime requires an `auditorium_id`, the `film_title`, the `studio_code` used for settlement grouping, a `format` that must be among the auditorium's `supported_formats` (a mismatch is rejected with `ERR_FORMAT_UNSUPPORTED`), a `starts_at` instant (futurity is not checked at scheduling time — it is enforced at open-sales time instead), the film's `runtime_minutes`, a `base_price_cents` general-admission price used for settlement valuation, a `premium_surcharge_cents` applied over base price for premium formats on paid tickets (subscriptions waive this surcharge), an `opening_weekend` flag marking showings inside the film's opening weekend (Friday 00:00 through Sunday 23:59 of release week), and an optional `subscriber_displacement_cap_pct` that defaults to 40. The showtime is created `SCHEDULED` with `seats_held_subscription` and `seats_held_paid` at zero and `seats_available` equal to the auditorium's `seat_count` minus both held counters.

Opening sales moves the showtime `SCHEDULED → ON_SALE` (any other showtime state fails with `ERR_INVALID_STATE`) and requires the theater to be `OPERATING` and `starts_at` still strictly in the future (a `starts_at` at or before the current instant fails with `ERR_INVALID_STATE`). From `ON_SALE`, the system locks the showtime automatically when the clock reaches ten minutes before start (`LOCK_MINUTES_BEFORE_START`): the `ON_SALE → LOCKED` transition rejects any further reservation creation or confirmation at the state gate with `ERR_SHOWTIME_LOCKED`, while check-ins remain allowed. After the film ends and the no-show grace elapses — when the clock reaches or passes `starts_at` plus `runtime_minutes` plus the 30-minute grace — the showtime is swept `LOCKED → COMPLETED`: every remaining `CONFIRMED` reservation is swept to `NO_SHOW` (firing the full no-show cascade per reservation) and every remaining `HELD` reservation is swept to `EXPIRED`. Administration may also cancel a showtime outright from `SCHEDULED` or `ON_SALE` as a force-majeure act: every `HELD` or `CONFIRMED` reservation is cancelled with a full credit refund regardless of `cancel_deadline`, and both seat-held counters reset to zero. `COMPLETED` and `CANCELLED` are terminal.

### 3.7. Capacity and the Opening-Weekend Displacement Cap

Seat availability is derived, never stored independently: `seats_available` is the auditorium's `seat_count` minus the showtime's `seats_held_subscription` minus its `seats_held_paid`. Creating any reservation requires at least one seat available.

Opening-weekend showings carry a second gate. When the showtime's `opening_weekend` flag is true, a new subscription reservation is allowed only if, after taking the seat, the subscriber share stays within the cap: one hundred times the sum of `seats_held_subscription` plus one must be less than or equal to `subscriber_displacement_cap_pct` times the auditorium's `seat_count`. The comparison is performed with integer multiplication, never floating-point division. When the cap is not supplied at scheduling time it defaults to 40 percent, and on showings outside the opening weekend the cap is ignored entirely — subscribers may fill the house to the last seat. A failure of either the availability check or the displacement gate is reported as `ERR_CAPACITY_EXCEEDED`.

### 3.8. The Anti-Hoarding Future-Reservation Cap

To prevent subscribers from squatting on prime seats across many future dates, each plan sets `max_future_reservations`, a cap on how many future-dated reservations a member may hold simultaneously. The count that matters, computed at reservation-creation time and on member reservation summaries, is the number of the member's reservations in `HELD` or `CONFIRMED` status whose showtime's `starts_at` is still in the future. Creation requires that count to be strictly below the effective cap.

The cap has one dynamic modifier: a member carrying exactly 2 active no-show strikes (`FLAG_LEVEL`) sees their effective cap halved, computed as the plan's `max_future_reservations` divided by two and rounded down. A member at that flag level therefore lives under a materially tighter holding limit even though no account state has changed. Breaching the effective cap rejects creation with `ERR_FUTURE_RESERVATION_LIMIT`.

### 3.9. Loyalty Points and Concession Discounts

Concession purchases are recorded by the member or by `TheaterStaff` ringing them up, supplying the `member_id`, the `theater_id`, and the `pre_discount_cents` list price; each purchase is individually addressable by its `purchase_id`. The member must be `ACTIVE` — a suspended member's purchase is rejected with `ERR_MEMBER_SUSPENDED`, and a member in any other non-`ACTIVE` state (`REGISTERED` or `CLOSED`) is rejected with `ERR_INVALID_STATE`.

The discount resolves against the member's `ACTIVE` subscription plan; if there is no active subscription the discount percentage is zero. `discount_cents` is `pre_discount_cents` multiplied by the plan's `concession_discount_pct` and divided by one hundred, rounded down to a whole cent; `charged_cents` is then `pre_discount_cents` minus `discount_cents`. The rounding order is pinned: floor the discount first, then subtract — never floor the charged amount. For a 999-cent list price at a 15 percent tier, the discount is the floor of 149.85, which is 149 cents, and the charge is 850 cents.

Points accrue on two events. A concession purchase earns base points equal to the whole-dollar portion of `charged_cents` — the charged amount divided by one hundred and rounded down — multiplied by 20 points per dollar (`POINTS_PER_DOLLAR`), and the resulting award is stored on the purchase as `points_earned`. A reservation check-in earns a flat 50 points (`ADMISSION_POINTS`). The tier multiplier from the member's `ACTIVE` subscription plan then applies: the final award is the base points multiplied by the plan's `loyalty_points_multiplier_pct`, divided by one hundred, and rounded down — with the floor applied once, at this final step only. If the subscription is `PAUSED` or `CANCELLED` at the moment of earning, the multiplier falls back to 100. The evaluation order is pinned: compute `charged_cents` first, derive base points from it, then apply the tier multiplier, then floor once. Each earning appends a `LoyaltyLedgerEntry` of `kind` `EARN_CONCESSION` or `EARN_ADMISSION` carrying the signed `points` delta and the `source_id` of the originating purchase or reservation; redemptions and expirations post negative `points` under `REDEEM` and `EXPIRE`, and `MemberServices` may post a manual `ADJUST` entry carrying a mandatory signed integer `points` delta and an optional free-text `note` (no member-state gate applies to adjustments). Each ledger entry is individually addressable by its `entry_id`. The member's `loyalty_points_balance` is recomputed from the ledger after every append.

### 3.10. No-Show Strikes and the Suspension Ladder

Strikes are the program's attendance-abuse instrument. Each strike records the penalized `member_id`, the `reservation_id` that produced it, an `issued_at` instant, and an `expires_at` set ninety days (`STRIKE_WINDOW_DAYS`) after issue. A strike is `ACTIVE` while within its window — identifiable individually by its `strike_id`; the expiry sweep moves strikes whose `expires_at` has been reached or passed (the boundary is inclusive: at exactly `expires_at` the strike is `EXPIRED` and no longer counts as active) to `EXPIRED`, both eagerly via clock advancement and lazily whenever the member record is read. `MemberServices` may reverse a strike as a goodwill correction, supplying a `reversal_reason`; the strike moves to `REVERSED` and the member's active count is recomputed, but a reversal that drops the count below the suspension threshold does not lift an in-progress suspension early.

The member's `no_show_strikes_active` is the count of their strikes in `ACTIVE` status whose `expires_at` is still in the future — a rolling ninety-day window. The ladder evaluates in order and the first matching rung wins. At 3 or more active strikes (`SUSPENSION_THRESHOLD`), the member's account transitions `ACTIVE → SUSPENDED` with `suspended_until` set thirty days (`SUSPENSION_DAYS`) ahead. At exactly 2 active strikes the member is flagged: no state change occurs, but their future-reservation cap is halved as described in §3.8. At 1 or fewer, there is no effect.

Suspension cascades through the member's world. Every reservation the member holds in `HELD` or `CONFIRMED` is cancelled, with each credit refunded to its originating bucket only when that bucket's posture is `OPEN` — an `EXHAUSTED` or `EXPIRED` bucket forfeits the credit. If the member has an `ACTIVE` subscription it is force-paused, with `paused_at` set to the suspension instant and `pause_resume_at` aligned to `suspended_until`; a suspension-driven force-pause does not consume the member's once-per-cycle pause allowance (`pause_count_in_cycle` is unchanged). When the clock reaches `suspended_until`, or when `MemberServices` lifts the suspension early by explicit request (which carries no precondition beyond the member being `SUSPENDED`, else `ERR_INVALID_STATE`), the member returns to `ACTIVE`, `suspended_until` clears to null, and a subscription that was force-paused by that suspension auto-resumes to `ACTIVE` alongside it — recognizable because its `pause_resume_at` equals the suspension's `suspended_until`; a subscription the member paused voluntarily never auto-resumes on unsuspension even if its `pause_resume_at` coincides.

### 3.11. Studio Settlement: Reports, Lines, Valuation, and Disputes

Settlement reconciles the theater against each studio for a period, counting every admission whether the seat was paid or subscription-funded. `TheaterStaff` opens a `SettlementReport` for their theater by supplying the `studio_code`, an inclusive `period_start`, and an exclusive `period_end` that must fall after the start; the report is created `DRAFT`.

Lines are added to a `DRAFT` report one reservation at a time; the checks run in the order: report still `DRAFT` (else `ERR_INVALID_STATE`), then duplication, then settleability. A line's reservation must be settleable: in `CHECKED_IN` or `NO_SHOW` status (never `CANCELLED`, `EXPIRED`, or `HELD`), with `settlement_reported` still false, attached to a showtime of the reporting theater whose `studio_code` matches the report and whose showtime falls within the report's period. Any of these failures rejects the add with `ERR_LINE_NOT_SETTLEABLE`; adding the same reservation twice to one report is rejected with `ERR_DUPLICATE_LINE`. Each line — individually addressable by its `line_id` — captures the `report_id`, the `reservation_id`, and a denormalized `showtime_id`, and is stamped with a `line_kind` of `SUBSCRIPTION` or `PAID`.

Valuation follows a fixed rule per line. A `PAID` line is valued at the showtime's `base_price_cents` plus, when the format is not `STANDARD`, the `premium_surcharge_cents`. A `SUBSCRIPTION` line is valued at the flat studio contract rate of 899 cents (`STUDIO_CONTRACT_RATE_CENTS`) regardless of format, surcharge, or attendance — a checked-in admission and a no-show both count. While the report is `DRAFT` or `DISPUTED` (including a report returned to `DRAFT` after dispute), its totals are provisional: `total_admissions` counts the included lines, `total_subscription_admissions` counts the `SUBSCRIPTION` lines among them, and `total_gross_cents` sums the lines' `reported_value_cents`, all recomputed live from the current line set.

Submitting the report — a `TheaterStaff` action requiring at least one line, else `ERR_EMPTY_REPORT` — moves it `DRAFT → SUBMITTED`, freezes the totals as stored fields, locks the line set (further line additions or removals are rejected with `ERR_INVALID_STATE`), and flips `settlement_reported` to true on every included reservation. Because the line set and its valuations freeze at submit, a later change to a showtime's `base_price_cents` does not alter a submitted report — provisional draft totals and finalized submitted totals can legitimately diverge across a price change.

The studio then adjudicates. A `StudioRep` may acknowledge a `SUBMITTED` report, moving it to the terminal `ACKNOWLEDGED` state, or dispute it by supplying a mandatory `dispute_note`, moving it to `DISPUTED`; dispute reverts `settlement_reported` to false on every included reservation so a corrected report may re-include them. `TheaterStaff` returns a `DISPUTED` report to `DRAFT` via revision, reopening the line set for additions and removals with totals recomputed live.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, confirmations, cancels, submissions, and the like — return `200 OK`. All endpoints are mounted under the `/cinemas` prefix. Request payloads must contain only the fields declared for the endpoint; unknown keys, missing required fields, type mismatches, enum violations, and out-of-range scalars are rejected with `ERR_INVALID_REQUEST`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cinemas/_clock/set_current_utc` | Advance the logical clock and fire all due temporal transitions | ProgramAdmin |
| POST | `/cinemas/members` | Register a member | MemberServices |
| GET | `/cinemas/members` | List members (paginated, filterable by status) | MemberServices, ProgramAdmin |
| GET | `/cinemas/members/{member_id}` | Read a member (lazily expires out-of-window strikes) | MemberServices, Member, ProgramAdmin |
| POST | `/cinemas/members/{member_id}/activate` | Activate a member account | MemberServices |
| POST | `/cinemas/members/{member_id}/unsuspend` | Manually lift a suspension early | MemberServices |
| POST | `/cinemas/members/{member_id}/close` | Close a member account | MemberServices |
| GET | `/cinemas/members/{member_id}/strikes` | List a member's no-show strikes | MemberServices, Member, ProgramAdmin |
| GET | `/cinemas/members/{member_id}/loyalty-ledger` | List a member's loyalty ledger entries | MemberServices, Member, ProgramAdmin |
| POST | `/cinemas/members/{member_id}/loyalty-adjustments` | Append a manual ADJUST loyalty entry | MemberServices |
| POST | `/cinemas/subscription-plans` | Create a subscription plan (DRAFT) | ProgramAdmin |
| GET | `/cinemas/subscription-plans/{plan_id}` | Read a plan | ProgramAdmin, MemberServices, Member |
| POST | `/cinemas/subscription-plans/{plan_id}/publish` | Publish a plan | ProgramAdmin |
| POST | `/cinemas/subscription-plans/{plan_id}/retire` | Retire a plan | ProgramAdmin |
| GET | `/cinemas/subscription-plans/{plan_id}/subscriptions` | List subscriptions enrolled on a plan | ProgramAdmin, MemberServices |
| POST | `/cinemas/members/{member_id}/subscriptions` | Enroll a member in a plan | Member, MemberServices |
| GET | `/cinemas/members/{member_id}/subscriptions` | List a member's subscriptions | Member, MemberServices, ProgramAdmin |
| GET | `/cinemas/subscriptions` | List subscriptions (filterable by member, plan, status) | ProgramAdmin, MemberServices |
| GET | `/cinemas/subscriptions/{subscription_id}` | Read a subscription | Member, MemberServices, ProgramAdmin |
| POST | `/cinemas/subscriptions/{subscription_id}/pause` | Pause a subscription (7–30 days, once per cycle) | Member |
| POST | `/cinemas/subscriptions/{subscription_id}/resume` | Resume a paused subscription early | Member |
| POST | `/cinemas/subscriptions/{subscription_id}/cancel` | Cancel a subscription | Member |
| POST | `/cinemas/subscriptions/{subscription_id}/change-plan` | Change plan at next cycle boundary (OCC-guarded) | Member, MemberServices |
| GET | `/cinemas/subscriptions/{subscription_id}/credit-buckets` | List a subscription's weekly credit buckets | Member, MemberServices, ProgramAdmin |
| GET | `/cinemas/subscriptions/{subscription_id}/reservations` | List reservations drawn on a subscription | Member, MemberServices, ProgramAdmin |
| GET | `/cinemas/credit-buckets` | List credit buckets (filterable by subscription, posture) | ProgramAdmin, MemberServices |
| GET | `/cinemas/credit-buckets/{bucket_id}` | Read a single credit bucket | Member, MemberServices, ProgramAdmin |
| GET | `/cinemas/credit-buckets/{bucket_id}/reservations` | List reservations that drew from a bucket | Member, MemberServices, ProgramAdmin |
| POST | `/cinemas/theaters` | Register a theater | ProgramAdmin |
| GET | `/cinemas/theaters/{theater_id}` | Read a theater | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| POST | `/cinemas/theaters/{theater_id}/auditoriums` | Add an auditorium to a theater | ProgramAdmin |
| GET | `/cinemas/theaters/{theater_id}/auditoriums` | List a theater's auditoriums | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| GET | `/cinemas/theaters/{theater_id}/concession-purchases` | List concession purchases at a theater | TheaterStaff, ProgramAdmin, MemberServices |
| GET | `/cinemas/theaters/{theater_id}/settlement-reports` | List settlement reports for a theater | TheaterStaff, StudioRep, ProgramAdmin |
| GET | `/cinemas/auditoriums` | List auditoriums (filterable by theater) | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| GET | `/cinemas/auditoriums/{auditorium_id}` | Read a single auditorium | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| GET | `/cinemas/auditoriums/{auditorium_id}/showtimes` | List showtimes for an auditorium | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| POST | `/cinemas/showtimes` | Schedule a showtime (SCHEDULED) | ProgramAdmin |
| GET | `/cinemas/showtimes` | List showtimes (filterable by auditorium, studio, status) | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| GET | `/cinemas/showtimes/{showtime_id}` | Read a showtime including seat counters | ProgramAdmin, TheaterStaff, MemberServices, Member, StudioRep |
| POST | `/cinemas/showtimes/{showtime_id}/open_sales` | Open a showtime for sales | ProgramAdmin |
| POST | `/cinemas/showtimes/{showtime_id}/cancel` | Cancel a showtime (force-majeure) | ProgramAdmin |
| GET | `/cinemas/showtimes/{showtime_id}/reservations` | List reservations against a showtime (house view) | TheaterStaff, ProgramAdmin, MemberServices |
| GET | `/cinemas/showtimes/{showtime_id}/settlement-lines` | List settlement lines valued against a showtime | TheaterStaff, StudioRep, ProgramAdmin |
| POST | `/cinemas/reservations` | Create a subscription reservation (HELD; OCC on showtime) | Member |
| GET | `/cinemas/reservations` | List reservations (filterable by member, subscription, showtime, bucket, status) | ProgramAdmin, MemberServices, TheaterStaff |
| GET | `/cinemas/reservations/{reservation_id}` | Read a reservation | Member, MemberServices, TheaterStaff, ProgramAdmin |
| GET | `/cinemas/members/{member_id}/reservations` | List a member's reservations | Member, MemberServices, ProgramAdmin |
| POST | `/cinemas/reservations/{reservation_id}/confirm` | Confirm a held reservation | Member |
| POST | `/cinemas/reservations/{reservation_id}/cancel` | Cancel a reservation within the cancellation window | Member |
| POST | `/cinemas/reservations/{reservation_id}/check_in` | Theater check-in for a confirmed reservation | TheaterStaff |
| GET | `/cinemas/reservations/{reservation_id}/strikes` | List strikes issued against a reservation | MemberServices, ProgramAdmin, Member |
| GET | `/cinemas/reservations/{reservation_id}/settlement-lines` | List settlement lines referencing a reservation | TheaterStaff, StudioRep, ProgramAdmin |
| GET | `/cinemas/strikes` | List strikes (filterable by member, reservation, status) | ProgramAdmin, MemberServices |
| GET | `/cinemas/strikes/{strike_id}` | Read a single no-show strike | MemberServices, ProgramAdmin |
| POST | `/cinemas/strikes/{strike_id}/reverse` | Reverse an active strike (goodwill correction) | MemberServices |
| GET | `/cinemas/concession-purchases` | List concession purchases (filterable by member, theater) | ProgramAdmin, MemberServices, TheaterStaff |
| POST | `/cinemas/concession-purchases` | Record a concession purchase with tier discount and points | Member, TheaterStaff |
| GET | `/cinemas/concession-purchases/{purchase_id}` | Read a single concession purchase | Member, MemberServices, TheaterStaff, ProgramAdmin |
| GET | `/cinemas/members/{member_id}/concession-purchases` | List a member's concession purchases | Member, MemberServices, ProgramAdmin |
| GET | `/cinemas/loyalty-ledger` | List loyalty ledger entries (filterable by member, kind) | ProgramAdmin, MemberServices |
| GET | `/cinemas/loyalty-ledger/{entry_id}` | Read a single loyalty ledger entry | ProgramAdmin, MemberServices, Member |
| GET | `/cinemas/settlement-reports` | List settlement reports (filterable by theater, studio, status) | ProgramAdmin, MemberServices, TheaterStaff, StudioRep |
| POST | `/cinemas/theaters/{theater_id}/settlement-reports` | Create a DRAFT settlement report for a studio and period | TheaterStaff |
| GET | `/cinemas/settlement-reports/{report_id}` | Read a settlement report including totals | TheaterStaff, StudioRep, ProgramAdmin, MemberServices |
| GET | `/cinemas/settlement-reports/{report_id}/lines` | List lines of a report | TheaterStaff, StudioRep, ProgramAdmin |
| POST | `/cinemas/settlement-reports/{report_id}/lines` | Add a settleable reservation line to a DRAFT report | TheaterStaff |
| POST | `/cinemas/settlement-reports/{report_id}/submit` | Submit a report to the studio (freezes totals) | TheaterStaff |
| POST | `/cinemas/settlement-reports/{report_id}/acknowledge` | Studio acknowledges a submitted report | StudioRep |
| POST | `/cinemas/settlement-reports/{report_id}/dispute` | Studio disputes a submitted report | StudioRep |
| POST | `/cinemas/settlement-reports/{report_id}/revise` | Return a disputed report to DRAFT | TheaterStaff |
| GET | `/cinemas/settlement-lines` | List settlement lines (filterable by report, reservation, showtime, kind) | ProgramAdmin, MemberServices, TheaterStaff, StudioRep |
| GET | `/cinemas/settlement-lines/{line_id}` | Read a single settlement line | TheaterStaff, StudioRep, ProgramAdmin, MemberServices |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_REJOIN_LOCKED` | 409 |
| `ERR_PLAN_NOT_ENROLLABLE` | 422 |
| `ERR_PAUSE_LIMIT_REACHED` | 422 |
| `ERR_WEEKLY_QUOTA_EXHAUSTED` | 422 |
| `ERR_FUTURE_RESERVATION_LIMIT` | 422 |
| `ERR_PREMIUM_NOT_INCLUDED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_SHOWTIME_LOCKED` | 409 |
| `ERR_CANCEL_WINDOW_CLOSED` | 409 |
| `ERR_CHECKIN_WINDOW` | 409 |
| `ERR_FORMAT_UNSUPPORTED` | 422 |
| `ERR_LINE_NOT_SETTLEABLE` | 422 |
| `ERR_EMPTY_REPORT` | 422 |
| `ERR_DUPLICATE_LINE` | 422 |
