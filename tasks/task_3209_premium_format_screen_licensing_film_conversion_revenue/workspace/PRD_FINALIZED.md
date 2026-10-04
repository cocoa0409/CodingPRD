# Premium Format Screen Licensing API — Product Requirements Document

## 1. Introduction

Premium-format exhibition runs on a three-way negotiation that never stops moving: the format operator licenses its projection and sound system to exhibitors under per-market capacity caps, studios pay to convert their films into the premium format under tight post-production schedules, and a finite pool of premium screen-seconds must be allocated across competing titles each release window. The Premium Format Screen Licensing API is the system of record for this entire commercial and operational loop. It tracks markets from prospecting through build-out to live operation, exhibitor agreements from negotiation to expiry or termination, auditoriums from design through calibration into daily service, studio films from announcement through their eighty-four-day distribution window, conversion orders through post-production and quality review, release windows and the screen slots booked against them, box office reporting that feeds tiered revenue-share statements, and the quality-assurance alert pipeline that can pull an auditorium out of service — and suspend every showing on it — in a single event.

The platform serves nine operational roles, from the `NetworkPlanner` who opens new territories to the `ExhibitorFinanceUser` who disputes a revenue-share statement. Because multiple schedulers compete for the same window capacity pool, slot creation carries an optimistic-concurrency check against the parent window; because exhibitors dispute settlements, statements support a dispute–adjustment–reissue cycle with a compensating invariant that exhibitor-retained plus agreed-share always equals gross-reported; and because a single `CRITICAL` quality alert degrades an auditorium mid-week, cascading side effects reach three levels deep — from the auditorium, through every suspended screen slot, to the window's committed capacity ledger and any revenue-share statements that reference those slots.

A logical clock drives every time-dependent behavior — film distribution windows, agreement expiries, window closures, calibration-overdue flags — and never falls back to the wall clock. This document specifies the API contract, the business rules that govern each lifecycle, and the calculations that determine conversion cost estimates, screen-second commitments, hold-over eligibility, quality scores, and the dual provisional-versus-final revenue share totals.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing. When the role is recognized but not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform recognizes exactly nine roles, spelled as follows: `NetworkPlanner`, `PlatformContractManager`, `StudioRelationshipManager`, `PostProductionScheduler`, `QualityAssuranceReviewer`, `ReleaseScheduler`, `BoxOfficeAnalyst`, `ExhibitorFinanceUser`, and `FieldEngineer`.

For eight of these roles — `NetworkPlanner`, `PlatformContractManager`, `StudioRelationshipManager`, `PostProductionScheduler`, `QualityAssuranceReviewer`, `ReleaseScheduler`, `BoxOfficeAnalyst`, and `FieldEngineer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it against any entity's `id`. When `X-User-Role` is `ExhibitorFinanceUser`, by contrast, `X-User-ID` is the `id` of the acting `ExhibitorAgreement`; ownership checks on any resource that references an `ExhibitorAgreement` — such as an agreement-scoped statement listing or a box-office report on a slot of one of that agreement's auditoriums — compare the resource's foreign-key field to `X-User-ID`.

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

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above the maximum of 100. The `offset` parameter says how many items to skip from the front of the result set and defaults to 0. Every list response is sorted by `created_at` in ascending order unless the endpoint documentation states otherwise, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — Market, ExhibitorAgreement, Auditorium, Studio, StudioFilm, ConversionOrder, ReleaseWindow, ScreenSlot, RevenueShareStatement, QAAlert, and TechDispatch — carries a standard quartet of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation. The `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` is an integer that starts at 1 on creation and increments by one on every mutation, including mutations driven by cascading side effects from other entities.

The BoxOfficeReport is the single exception: it is an immutable, ledger-style record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from BoxOfficeReport resources; once created, a report is never modified, only transitioned between `RECEIVED`, `VALIDATED`, and `FLAGGED_DISCREPANCY`.

Whenever any mutation touches a resource — including an automatic state transition fired by the logical clock or a cascade from a parent — that resource's `updated_at` is refreshed and its `version` incremented. A client that observes `version` 4 of a ReleaseWindow and later sees `version` 7 can infer that three mutations have landed in between.

### 2.5. The Logical Clock and Time-Driven Transitions

The platform runs on a logical clock, not the wall clock. Before any client call, the clock reads `2026-09-01T00:00:00Z`. The clock is advanced only through an explicit test-driving capability that accepts a target instant in the `to_iso8601` field and sets the server's logical time to that instant; a companion read capability returns the current value as `current_utc`. Both are available to every role. The clock never falls back to wall-clock time: if a client forgets to set it, every date-dependent rule evaluates against the default instant.

Advancing the clock can fire automatic transitions. A StudioFilm whose `worldwide_release_date` has been reached moves from `ANNOUNCED` to `IN_DISTRIBUTION`. A StudioFilm whose distribution window has elapsed — the logical clock reaching `worldwide_release_date` plus 84 days — moves from `IN_DISTRIBUTION` to `OUT_OF_WINDOW`, and every ConversionOrder for that film in a non-terminal state is cancelled as a side effect. An ExhibitorAgreement whose `term_end_date` has been reached moves from `ACTIVE` to `EXPIRED`, and every ScreenSlot on that agreement's auditoriums still sitting in `PROPOSED` is moved to `REJECTED`. A ReleaseWindow in `LOCKED` whose `window_end_date` is reached moves to `CLOSED`, firing the statement-issuance and hold-over cascades described in §3.5. Finally, the `calibration_overdue` flag on every Auditorium is recomputed against the new clock value.

All dates and datetimes in the API are UTC. Day-boundary fields such as `term_start_date`, `term_end_date`, `slot_start_date`, `slot_end_date`, `window_start_date`, `window_end_date`, `worldwide_release_date`, `scheduled_post_start_date`, `scheduled_post_end_date`, and `reported_date` are interpreted as UTC midnight of the named day.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts flow through the API as integer cents — never floating-point dollars. Fields such as `annual_lease_fee_cents`, `post_cost_estimate_cents`, `gross_receipts_cents`, `weekly_gross_cents`, `gross_reported_cents`, `exhibitor_retained_cents`, `agreed_share_cents`, `provisional_total_cents`, `final_total_cents`, and `adjustment_cents` are all integer cents.

Revenue-share calculations are the exception to integer-only arithmetic, because tier percentages produce fractional cents. Two precision rules govern them, and the rounding order is load-bearing. For the provisional revenue share, each statement line's share is rounded to 2 decimal places using round-half-up, and only then are the rounded line values summed into `provisional_total_cents`; the rounding happens per line, not after the sum. For the final revenue share, each individual day's share is rounded to 2 decimal places using round-half-up, those rounded per-day shares are summed to produce the line's `agreed_share_cents`, and the line totals are summed into `final_total_cents` with no further rounding at the line level. Ratios and scores — `per_screen_attendance_ratio`, `quality_score_arithmetic`, and `quality_score_recency` — are reported to 4 decimal places, round-half-up. Because revenue-share results may carry fractional cents, the revenue-share output fields (`agreed_share_cents`, `exhibitor_retained_cents`, `provisional_total_cents`, `final_total_cents`) are emitted as a JSON integer when their rounded value is a whole number of cents, and as a JSON number carrying the fractional cents otherwise; they are never truncated to integers.

### 2.7. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: the creation of a screen slot against a release window. Because any confirmation against a window mutates that window's committed-capacity ledger (and therefore its `version`), a client proposing a new slot must include the `expected_window_version` field carrying the `version` of the parent ReleaseWindow the client last observed. If the parent window's current `version` does not match the supplied `expected_window_version` — because, for instance, another scheduler's confirmation has advanced it since the client last read the window — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from booking against a capacity picture it has not observed: the rejection is the signal to re-read the window and resubmit. No other endpoint accepts a version field; mutations on all other resources proceed without an OCC check.

### 2.8. Hierarchical Consistency and Cascading Side Effects

Parent entities enforce consistency over their children, and certain parent transitions cascade. The cascades are always immediate — the platform's consistency model is immediate, not eventual — and every cascaded mutation refreshes the child's `updated_at` and increments its `version` independently.

Abandoning a Market in `BUILDING` terminates every ExhibitorAgreement in that market still sitting in `NEGOTIATING`. Terminating an ExhibitorAgreement decommissions every Auditorium under it that is not already `DECOMMISSIONED`, and resolves every ScreenSlot on those auditoriums: slots in `PROPOSED` become `REJECTED`; slots in `CONFIRMED` become `PULLED`, and a pull itself releases the slot's committed screen-seconds back to its window's pool (the capacity-release cascade continues downward). Suspending a Studio cancels every ConversionOrder on that studio's films that is still in `SUBMITTED`; terminating a Studio cancels every non-terminal ConversionOrder regardless of state. A ConversionOrder cancelled from `APPROVED_FOR_RELEASE` rejects every ScreenSlot still in `PROPOSED` that references it.

The deepest cascade runs three levels. When a `CRITICAL` QAAlert is created against an Auditorium in `OPERATING`, the auditorium auto-transitions to `DEGRADED`; every ScreenSlot on that auditorium whose status is `CONFIRMED` and whose `slot_start_date` is on or before the logical clock and whose `slot_end_date` is strictly after the logical clock moves to `SUSPENDED`; for each suspended slot, the parent ReleaseWindow's `committed_premium_screen_seconds` is decremented by that slot's `committed_screen_seconds`; and any RevenueShareStatement covering those slots recomputes its `statement_lines`, `provisional_total_cents`, and `final_total_cents`. The return-to-service transition unwinds the mirror image of this cascade, as detailed in §3.7.

### 2.9. Nested Resource Retrieval and Validation Order

For every endpoint whose URL or payload references multiple resources, the server validates identifiers left to right. Path parameters are checked first, in path order — a request naming a non-existent market under a nested path is rejected with `ERR_MARKET_NOT_FOUND` before the system even looks for the child resource. Body foreign keys are then checked in their declared input order: each missing referenced resource produces the corresponding `ERR_{RESOURCE}_NOT_FOUND` (HTTP 404) — `ERR_AGREEMENT_NOT_FOUND`, `ERR_AUDITORIUM_NOT_FOUND`, `ERR_STUDIO_NOT_FOUND`, `ERR_FILM_NOT_FOUND`, `ERR_CONVERSION_ORDER_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND` as applicable.

Validation across the whole API follows a fixed priority ladder, evaluated in order: (1) the `X-User-ID` and `X-User-Role` headers are present and valid (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) the role is permitted for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); (3) resource identifiers in the path exist, left to right; (4) foreign keys in the request body exist, in declared input order; (5) the target resource's state permits the requested transition (`ERR_INVALID_STATE` or the transition's domain-specific error); (6) cross-entity state references hold — for example that a referenced ConversionOrder is `APPROVED_FOR_RELEASE`, the Auditorium is `CERTIFIED` or `OPERATING`, the parent Market is past the approval gate, or a `SIGNED` agreement exists (`ERR_CONVERSION_NOT_APPROVED`, `ERR_AUDITORIUM_NOT_READY`, `ERR_MARKET_NOT_APPROVED`, `ERR_NO_SIGNED_AGREEMENT`); (7) temporal validity — slot intervals inside their window's bounds, conversion post-production windows not overlapping on a studio, calibration freshness (`ERR_SLOT_OVERLAP`, `ERR_POST_SCHEDULE_OVERLAP`, `ERR_SLOT_OUTSIDE_WINDOW`, `ERR_WINDOW_IN_PAST`); (8) safety and quality gates (`ERR_UNRESOLVED_CRITICAL_ALERTS`, `ERR_FILMMAKER_SIGNOFF_MISSING`, `ERR_CANNOT_DEFER_CRITICAL`); (9) capacity and fiscal limits (`ERR_WINDOW_CAPACITY_EXCEEDED`, `ERR_MARKET_CAPACITY_EXCEEDED`); and (10) aggregate invariants (`ERR_UNRESOLVED_REPORTS`, `ERR_NO_OPERATING_AUDITORIUM`). Malformed payloads — a missing required field, a type mismatch, an unrecognized enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.10. Capacity Ledgers and the Screen-Seconds Pool

Two capacity ledgers constrain the platform. Each Market declares a `screen_capacity_cap` — the maximum number of premium screens permitted in that market — and tracks `opened_screen_count`, the current count of its auditoriums in `OPERATING`. Opening an auditorium is allowed only while the cap strictly exceeds the current count of `OPERATING` auditoriums in the market; a market at its cap rejects further openings with `ERR_MARKET_CAPACITY_EXCEEDED`. The `opened_screen_count` increments on each opening and decrements on each decommissioning of an `OPERATING` auditorium.

Each ReleaseWindow declares a `total_premium_screen_seconds_pool` — the global premium screen-seconds budget for that window — and tracks `committed_premium_screen_seconds`, the sum of `committed_screen_seconds` over every slot of the window in `CONFIRMED` or `HELD_OVER` status. Confirming a slot is allowed only while the committed total plus the new slot's `committed_screen_seconds` is less than or equal to the pool; otherwise the confirmation is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`. Committed seconds are added on confirmation, subtracted on pulls and on degradation-driven suspensions, and restored when a suspended slot returns to `CONFIRMED`. Each ExhibitorAgreement also tracks `total_slots_committed_count`, the count of ScreenSlots in `CONFIRMED` or `HELD_OVER` across all auditoriums owned by that agreement, which starts at zero when the agreement is created.

### 2.11. Revenue Recognition: Provisional versus Final

RevenueShareStatements carry two totals with deliberately different semantics, and readers must not conflate them. The `provisional_total_cents` is forward-looking: it forecasts the still-unreported days of each slot at half of that slot's mean reported daily gross and adds the forecast to the validated gross before applying tiered shares. The `final_total_cents` is strictly chronological: it sums only validated reports, applying tiered shares day by day against the slot's cumulative running gross. While unreported days remain, the provisional total exceeds the final total for identical underlying reports; once every day of every slot has a validated report, the forecast term vanishes and the two totals coincide. A statement is created in `DRAFT` with `statement_lines` initialized empty and both totals at zero; lines and totals are recomputed whenever a relevant box-office report is validated, whenever a slot is confirmed, pulled, suspended, or restored, and on every read of the statement.

## 3. Business Logic & Workflows

### 3.1. Opening a Territory: Markets, Agreements, and Auditoriums

Network expansion begins when a `NetworkPlanner` creates a Market, supplying a `market_name` (for example, "Greater Tokyo"), a `country_code` in ISO 3166-1 alpha-2 form, a `screen_capacity_cap` giving the maximum premium screens the market will ever host, and a `target_format_mix` — an ordered list of the premium formats the market will support, drawn from `PREMIUM_2D`, `PREMIUM_3D`, and `PREMIUM_70MM`. A new market enters in `PROSPECT`.

From `PROSPECT`, a `NetworkPlanner` begins evaluation, moving the market to `EVALUATING`. Approval requires the `screen_capacity_cap` to be greater than zero and moves the market to `APPROVED`; abandonment is permitted from either `EVALUATING` or `BUILDING` and lands the market in its terminal `ABANDONED` state. Beginning the build — `APPROVED → BUILDING` — requires that at least one ExhibitorAgreement referencing this market already sits in `SIGNED`; without one the transition is rejected with `ERR_NO_SIGNED_AGREEMENT`. Going live — `BUILDING → LIVE` — requires the market's `opened_screen_count` to be at least one. When a market in `BUILDING` is abandoned, every ExhibitorAgreement in that market still in `NEGOTIATING` is automatically moved to `TERMINATED`; the market's `status` is the system-managed field that records where each market stands on this `PROSPECT → EVALUATING → APPROVED → BUILDING → LIVE` path.

An ExhibitorAgreement is drafted by a `PlatformContractManager`, who supplies the `exhibitor_legal_name`, the `market_id` of the market it operates in, an `agreement_type` of either `REVENUE_SHARE` or `LEASE`, the `committed_screen_count` the exhibitor commits to install, and the contract's `term_start_date` (UTC midnight, inclusive) and `term_end_date` (UTC midnight, exclusive). For a `REVENUE_SHARE` agreement, three tier fractions are required: `revenue_share_tier1_pct`, `revenue_share_tier2_pct`, and `revenue_share_tier3_pct` (each a fraction such as 0.12 for twelve percent). For a `LEASE` agreement, the `annual_lease_fee_cents` is required instead; the lease fee is ignored when the agreement is a revenue share, and the tier percentages are ignored for a lease. A new agreement enters in `NEGOTIATING` with `total_slots_committed_count` at zero.

Signing — `NEGOTIATING → SIGNED` — is gated on the market: the referenced market must be in `APPROVED`, `BUILDING`, or `LIVE`, and signing against a market in any other state is rejected with `ERR_MARKET_NOT_APPROVED`. Activation — `SIGNED → ACTIVE` — requires at least one Auditorium under the agreement to be in `OPERATING`; without one the activation is rejected with `ERR_NO_OPERATING_AUDITORIUM`. Termination is available from `NEGOTIATING`, `SIGNED`, or `ACTIVE` and always lands in `TERMINATED`. Terminating from `SIGNED` or `ACTIVE` decommissions every auditorium under the agreement that is not already `DECOMMISSIONED`; terminating from `ACTIVE` additionally moves every `PROPOSED` slot on those auditoriums to `REJECTED` and every `CONFIRMED` slot to `PULLED`, with each pull releasing the slot's committed screen-seconds back to its window. Expiry is automatic: when the logical clock reaches the agreement's `term_end_date`, an `ACTIVE` agreement moves to `EXPIRED` and its remaining `PROPOSED` slots are rejected.

An Auditorium is registered under an agreement by a `PlatformContractManager` with an `agreement_id`, an on-site `auditorium_label` (for example, "Screen 7"), a `screen_geometry` object carrying `width_m`, `height_m`, and `curvature_deg`, a `seating_capacity`, a `supported_formats` list that must be a subset of `PREMIUM_2D`, `PREMIUM_3D`, and `PREMIUM_70MM`, and a `sound_calibration_profile` object carrying `spl_target_db`, `eq_curve_id`, and `channel_count`. A new auditorium enters in `DESIGN`.

Construction begins — `DESIGN → CONSTRUCTION` — only while the parent agreement is `SIGNED` or `ACTIVE`. A `FieldEngineer` then drives `CONSTRUCTION → CALIBRATION` and certification, `CALIBRATION → CERTIFIED`; certification stamps the auditorium's `last_calibration_at` with the current logical clock and resets `calibration_overdue` to false. Opening — `CERTIFIED → OPERATING` — is performed by a `PlatformContractManager` and increments the parent market's `opened_screen_count` by one, subject to the capacity check of §2.10. The auditorium's serviceable life runs `OPERATING → DEGRADED → OPERATING` as quality events fire and resolve, and ends in the terminal `DECOMMISSIONED` state, reachable from either `OPERATING` or `DEGRADED`. Decommissioning from `OPERATING` decrements the parent market's `opened_screen_count` by one and resolves that auditorium's slots — `PROPOSED` to `REJECTED`, `CONFIRMED` to `PULLED`; decommissioning from `DEGRADED` resolves `PROPOSED` slots to `REJECTED` and `SUSPENDED` slots to `PULLED` instead.

An auditorium's `calibration_overdue` flag is recomputed on every read: it is true exactly when the logical clock is strictly later than `last_calibration_at` plus 90 days. At precisely 90 days the auditorium is not yet overdue — the comparison is strict. The auditorium also surfaces `current_week_admissions`, the admissions summed over `VALIDATED` box-office reports on its slots whose `reported_date` falls in the current calendar week of the logical clock, and two quality-score variants, `quality_score_arithmetic` and `quality_score_recency`, whose calculation appears in §3.8.

### 3.2. The Studio Pipeline: Films and Their Distribution Window

A `StudioRelationshipManager` registers a Studio with its `studio_legal_name` and `contact_email`; the studio enters in `ONBOARDING`. Activation moves it to `ACTIVE`, and activation is idempotent across the suspension cycle — a `SUSPENDED` studio is reactivated to `ACTIVE` by the same action. Suspension — `ACTIVE → SUSPENDED` — immediately cancels every ConversionOrder on that studio's films still in `SUBMITTED`. Termination — `ACTIVE → TERMINATED` — is the terminal state and cancels every ConversionOrder on the studio's films in any non-terminal state.

Films are registered against a studio with the parent `studio_id`, a `title`, a `runtime_minutes` that must be strictly greater than zero, a `worldwide_release_date` at UTC midnight, and `format_targets` listing the formats the studio intends to ship. A film enters in `ANNOUNCED`. Two transitions are clock-driven: when the logical clock reaches `worldwide_release_date`, the film moves `ANNOUNCED → IN_DISTRIBUTION`; when the clock reaches `worldwide_release_date` plus 84 days, the film moves `IN_DISTRIBUTION → OUT_OF_WINDOW` and every non-terminal ConversionOrder for the film is cancelled. From `OUT_OF_WINDOW`, a `StudioRelationshipManager` archives the film into its terminal `ARCHIVED` state. The film's `status` field therefore walks `ANNOUNCED → IN_DISTRIBUTION → OUT_OF_WINDOW → ARCHIVED`, with the middle two transitions owned by the clock.

### 3.3. Converting a Film: The Conversion Order Lifecycle

A conversion order commissions the post-production work that turns a studio master into a premium-format deliverable. A `StudioRelationshipManager` submits one with the `studio_film_id` of the film, a `target_format` of `PREMIUM_2D`, `PREMIUM_3D`, or `PREMIUM_70MM`, a `scheduled_post_start_date` and `scheduled_post_end_date` (both UTC midnight, and both inclusive — the post window is a closed-closed interval), and an optional `filmmaker_approval_required` flag that defaults to false. On creation the order enters `SUBMITTED`, its `filmmaker_signoff` is initialized to false, and its `post_cost_estimate_cents` is computed immediately.

The estimate is a base rate plus a per-minute rate times the parent film's `runtime_minutes`, with the rates keyed by target format. A `PREMIUM_2D` conversion carries a base of 200,000,000 cents plus 1,200,000 cents per minute of runtime. A `PREMIUM_3D` conversion carries a base of 350,000,000 cents plus 1,800,000 cents per minute. A `PREMIUM_70MM` conversion carries a base of 500,000,000 cents plus 2,500,000 cents per minute. The result is an integer number of cents; no rounding is needed.

Beginning post-production — `SUBMITTED → IN_POST`, driven by a `PostProductionScheduler` — enforces two gates, and the order of the full validation ladder is the one in §2.9. First, the parent film must still be `ANNOUNCED`; beginning post on a film that has already entered distribution is rejected with `ERR_FILM_NOT_ANNOUNCED`. Second, no other ConversionOrder on a film of the same studio may have status `IN_POST` or `QC_REVIEW` with a post window that lies within one day of this order's window: because post windows are closed-closed, a one-day handoff is required between consecutive conversions — the other order's end date plus one day must not be strictly after this order's start while this order's end date plus one day is also strictly after the other order's start. A violation is rejected with `ERR_POST_SCHEDULE_OVERLAP`.

Submitting for quality control — `IN_POST → QC_REVIEW` — requires the logical clock to have reached the order's `scheduled_post_end_date`; an early submission is rejected with `ERR_POST_NOT_ELAPSED`. In `QC_REVIEW`, a `QualityAssuranceReviewer` either approves the master for release or requests rework. Approval — `QC_REVIEW → APPROVED_FOR_RELEASE` — requires that whenever `filmmaker_approval_required` is true, the request sets `filmmaker_signoff` to true; approval without the signoff is rejected with `ERR_FILMMAKER_SIGNOFF_MISSING`. A rework request moves the order to `REWORK_REQUESTED`, and the cycle closes when a `PostProductionScheduler` begins post again: that `REWORK_REQUESTED → IN_POST` transition resets the rework window by setting `scheduled_post_end_date` to the current logical clock plus 7 days and clears `filmmaker_signoff` back to false, so a filmmaker signoff given before rework never carries across the cycle. The order may loop `QC_REVIEW → REWORK_REQUESTED → IN_POST → QC_REVIEW` any number of times.

Delivery — `APPROVED_FOR_RELEASE → DELIVERED` — is performed by a `PostProductionScheduler` and requires the `delivered_master_url` to be non-empty; an empty or missing URL is rejected with `ERR_MASTER_URL_REQUIRED` (HTTP 400). Once an order reaches `APPROVED_FOR_RELEASE`, any ScreenSlot referencing it that sits in `PROPOSED` becomes eligible for confirmation — the next confirmation attempt against such a slot will clear the conversion gate. Cancellation is available from `SUBMITTED`, `IN_POST`, `QC_REVIEW`, or `APPROVED_FOR_RELEASE` and lands in the terminal `CANCELLED` state; cancelling from `APPROVED_FOR_RELEASE` additionally rejects every `PROPOSED` ScreenSlot that references the order.

### 3.4. Programming the Slate: Release Windows

A `ReleaseScheduler` creates a ReleaseWindow with a `window_label` (for example, "W42-2026") that must be unique across the platform, a `window_start_date` (UTC midnight, inclusive) and `window_end_date` (UTC midnight, exclusive — the window interval is half-open), and the `total_premium_screen_seconds_pool` for the window. The window enters in `DRAFT` with `committed_premium_screen_seconds` at zero.

Opening the window — `DRAFT → OPEN_FOR_BOOKING` — requires the `window_start_date` to be strictly in the future relative to the logical clock; opening a window whose start has already passed is rejected with `ERR_WINDOW_IN_PAST`. Locking — `OPEN_FOR_BOOKING → LOCKED` — is the scheduling freeze: every slot in the window still in `PROPOSED` that was never confirmed is moved to `REJECTED`. A locked window can be amended: `LOCKED → REOPENED → OPEN_FOR_BOOKING` forms a cycle (lock, reopen, resume booking) that lets the scheduler adjust the slate, and the window can then be locked again. When the logical clock reaches `window_end_date` on a `LOCKED` window, the window closes automatically, firing the settlement cascade of §3.5.

### 3.5. Booking a Screen: Slots, Capacity, and Hold-Over

A `ReleaseScheduler` proposes a ScreenSlot by naming its `window_id`, `auditorium_id`, `studio_film_id`, and `conversion_order_id`, the `slot_start_date` (inclusive) and `slot_end_date` (exclusive — the slot interval is half-open) bounding the run, the planned `showings_per_day` which must be at least 1, an optional `priority_tier` of `BLOCKBUSTER`, `STANDARD`, or `FILLER` defaulting to `STANDARD`, and the OCC field `expected_window_version` described in §2.7. The slot's interval must lie within its window's bounds — a `slot_start_date` earlier than the window's `window_start_date`, or a `slot_end_date` later than the window's `window_end_date`, is rejected with `ERR_SLOT_OUTSIDE_WINDOW`. A new slot enters in `PROPOSED`.

Every slot's `committed_screen_seconds` is computed at creation and recomputed whenever the slot's dates or showings change: take the slot length in whole days (the difference between `slot_end_date` and `slot_start_date`, which must be at least 1), multiply by `showings_per_day`, multiply by the parent film's `runtime_minutes`, and multiply by 60 to reach seconds. The result is an integer.

Confirmation — `PROPOSED → CONFIRMED`, and identically `HELD_OVER → CONFIRMED` for the next-window extension — runs its checks in the §2.9 order. The parent window must be `OPEN_FOR_BOOKING`, else `ERR_WINDOW_NOT_OPEN`. The parent auditorium must be `CERTIFIED` or `OPERATING`, else `ERR_AUDITORIUM_NOT_READY`. The referenced conversion order must be `APPROVED_FOR_RELEASE`, else `ERR_CONVERSION_NOT_APPROVED`. The slot's interval must not overlap another `CONFIRMED` or `HELD_OVER` slot on the same auditorium — overlap arithmetic is half-open, so a slot ending exactly when another begins does not overlap — else `ERR_SLOT_OVERLAP`. Finally, the window's `committed_premium_screen_seconds` plus the candidate slot's `committed_screen_seconds` must not exceed the `total_premium_screen_seconds_pool`, else `ERR_WINDOW_CAPACITY_EXCEEDED`. On success, the window's committed total increases by the slot's committed seconds and the slot's `per_screen_attendance_ratio` is initialized to 0. Rejection moves a `PROPOSED` slot to its terminal `REJECTED` state with no side effects.

Pulling a slot is the scheduler's pre-release retraction. From `CONFIRMED`, a pull requires the logical clock to be strictly earlier than `slot_start_date`; once the slot has started, the pull is rejected with `ERR_SLOT_ALREADY_STARTED`. A successful pull releases the slot's committed screen-seconds back to the window and then runs a waitlist promotion: if any `PROPOSED` slot in the same window previously failed with `ERR_WINDOW_CAPACITY_EXCEEDED` and now fits, the platform auto-confirms the highest-priority eligible candidate — `BLOCKBUSTER` beats `STANDARD` beats `FILLER`, with ties broken by `created_at` ascending. If that auto-confirmed slot's conversion order is `APPROVED_FOR_RELEASE` and its `delivered_master_url` is non-empty, the conversion order itself advances to `DELIVERED` — a third-level cascade from a single pull. Pulling from `SUSPENDED` or `HELD_OVER` is always permitted and, for a `HELD_OVER` slot, likewise releases its committed seconds from the window.

Suspension and restoration are clock-free cascades owned by the auditorium lifecycle: a slot moves `CONFIRMED → SUSPENDED` only when its auditorium degrades mid-run (see §3.7), and `SUSPENDED → CONFIRMED` when the auditorium returns to service, re-adding the slot's committed seconds to the window.

Hold-over is the platform's reward for a slot that out-performs. When a locked window closes at its `window_end_date`, every slot in `CONFIRMED` is scored. The score combines three terms with fixed weights: half of the slot's `per_screen_attendance_ratio`, three-tenths of a format-premium uplift, and one-fifth of the week-over-week gross growth capped at 1.0. The uplift is 0.10 if this slot is the only slot for its film in the window, 0.05 if exactly one other slot for the same film exists in the window, and 0.00 otherwise; it is computed using only the slots already `CONFIRMED` at the start of the evaluation, never counting the candidate's own hypothetical held-over state. The growth term divides the difference between this week's gross and the same film's prior-week gross by the prior-week gross, using 1 in place of the denominator when the prior week's gross is zero, and is computed using only `VALIDATED` reports from prior windows. The evaluation order is pinned — uplift first, growth second, weighted sum third — to avoid any circular dependency. If the final score is at least 0.65 (the comparison is inclusive: exactly 0.65 qualifies), the slot moves `CONFIRMED → HELD_OVER`; otherwise it remains `CONFIRMED` until the window finishes closing. Independently, the hold-over eligibility check on `per_screen_attendance_ratio` uses the same 0.65 threshold, again inclusive.

A held-over slot causes the platform to auto-create a follow-on ScreenSlot for the same auditorium and the same film in the chronologically next ReleaseWindow (by `window_start_date`): the new slot enters in `PROPOSED`, with `slot_start_date` equal to the next window's `window_start_date` and `slot_end_date` seven days later. That follow-on slot still has to earn its own confirmation — including the capacity check — in the next window.

Window close also issues the settlements: every RevenueShareStatement for the closing window still in `DRAFT` moves to `ISSUED`.

### 3.6. Counting the House: Box Office Reports and Revenue-Share Statements

Each day of a confirmed run, the exhibitor's take is reported as a BoxOfficeReport. Either an `ExhibitorFinanceUser` or a `BoxOfficeAnalyst` submits one with the `screen_slot_id`, the `reported_date` (UTC midnight of the day covered), the day's `gross_receipts_cents` (which must be zero or greater), the day's `admissions` (also zero or greater), and a `submission_channel` of `EXHIBITOR_PORTAL`, `API_INGEST`, or `MANUAL_UPLOAD`. A report enters in `RECEIVED` and is immutable thereafter — it carries no `updated_at` and no `version` (see §2.4).

A `BoxOfficeAnalyst` then dispositions the report. Validation — `RECEIVED → VALIDATED` — requires the parent slot to be in `CONFIRMED`, `HELD_OVER`, `PULLED`, or `SUSPENDED`. On validation, the parent slot's `weekly_gross_cents` increases by the report's `gross_receipts_cents`, its `weekly_admissions` increases by the report's `admissions`, its `per_screen_attendance_ratio` is recomputed, and every RevenueShareStatement covering that slot and window recomputes its lines and both totals. Flagging — `RECEIVED → FLAGGED_DISCREPANCY` — is the alternative terminal disposition for reports that do not reconcile.

The `per_screen_attendance_ratio` divides the slot's `weekly_admissions` by the product of the parent auditorium's `seating_capacity`, the slot's `showings_per_day`, and the days elapsed in the slot — where days elapsed is the whole-day difference between the earlier of the logical clock's current day and `slot_end_date`, and `slot_start_date`, clamped to be at least zero. When that denominator is zero, the ratio is defined as 0. The ratio is recomputed on every report validation and on slot confirmation, and is reported to 4 decimal places with round-half-up.

A RevenueShareStatement is drafted by a `BoxOfficeAnalyst` for a given `agreement_id` and `window_id`, entering in `DRAFT` with empty `statement_lines` and both totals at zero. The lines materialize on recompute: one line per ScreenSlot in the window whose status is `CONFIRMED`, `HELD_OVER`, or `PULLED`. Each line carries the `screen_slot_id`, the `gross_reported_cents` (the slot's running validated gross), the `agreed_share_cents` produced by the tiered marginal share, the `exhibitor_retained_cents`, the `day_count`, and an `adjustments` list that starts empty.

The tiered marginal share applies the agreement's three tier fractions against cumulative weekly gross per slot, with two fixed boundaries: 10,000,000 cents of gross per slot per week for tier 1 (one hundred thousand dollars), and 25,000,000 cents for tier 2 (two hundred fifty thousand dollars). Gross up to and including the first boundary is shared at `revenue_share_tier1_pct` — at exactly the boundary, tier 1 still applies, and the very next cent spills into tier 2. Gross between the two boundaries is shared at `revenue_share_tier2_pct` on the portion above the first boundary, on top of the full tier-1 amount. Gross beyond the second boundary is shared at `revenue_share_tier3_pct` on the portion above it, on top of the full tier-1 and tier-2 amounts.

The two totals diverge in how they treat unreported days. For `provisional_total_cents`, each slot with status `CONFIRMED`, `HELD_OVER`, `PULLED`, or `SUSPENDED` contributes a line whose provisional gross is the sum of its validated reports plus a forecast: the count of unreported days (total slot days minus days with validated reports) times the mean validated daily gross for the slot, times one-half. A slot with no validated reports forecasts zero. The tiered share is applied to each line's provisional gross, rounded to 2 decimal places round-half-up per line, and the rounded line shares are summed. For `final_total_cents`, only slots in `CONFIRMED`, `HELD_OVER`, or `PULLED` contribute, and only validated reports count: the reports are processed in `reported_date` ascending order with `created_at` ascending as the tie-break, the day's receipts are added to the slot's running gross, and the tiered share for that day is computed against the running total — so a tier boundary crossed mid-day splits that day's receipts across tiers, each portion at its own rate. Each day's share is rounded to 2 decimal places round-half-up, the rounded per-day shares sum to the line's `agreed_share_cents`, the line's `exhibitor_retained_cents` is its `gross_reported_cents` minus its `agreed_share_cents`, and the line shares sum to `final_total_cents` with no further rounding.

Issuing a statement — `DRAFT → ISSUED` by a `BoxOfficeAnalyst` — is gated on completeness: for every slot in the window with status `CONFIRMED`, `HELD_OVER`, or `PULLED`, every box-office report on that slot must already be `VALIDATED` or `FLAGGED_DISCREPANCY`; a single report still in `RECEIVED` blocks issuance with `ERR_UNRESOLVED_REPORTS`. Issuance sets `final_total_cents` to the sum of the lines' `agreed_share_cents` and recomputes the provisional total, which at that point equals the final total because no unreported days remain.

An issued statement can be disputed by an `ExhibitorFinanceUser` — `ISSUED → DISPUTED` — and then adjusted by a `BoxOfficeAnalyst` — `DISPUTED → ADJUSTED` — by naming a `screen_slot_id`, an `adjustment_cents` amount, and an `adjustment_reason`. The adjustment is appended to that line's `adjustments` list such that the sum of all lines' `agreed_share_cents` plus the sum of all adjustments equals the recomputed total, and the compensating invariant holds after every adjustment: for each line, exhibitor-retained plus agreed-share always equals gross-reported. The `final_total_cents` is then recomputed. Reissuing — `ADJUSTED → ISSUED` — closes the cycle, and a statement can loop `ISSUED → DISPUTED → ADJUSTED → ISSUED` as often as the parties require. Final reconciliation — `ISSUED → RECONCILED` by a `PlatformContractManager` — is the terminal state.

### 3.7. Keeping the Lights On: QA Alerts, Degradation, and Technician Dispatch

Remote monitoring surfaces problems as QA alerts. A `FieldEngineer` or `NetworkPlanner` raises one with the `auditorium_id`, an `alert_code` of `LAMP_DEGRADED`, `SOUND_DRIFT`, `PROJECTOR_TEMP`, `NETWORK_LOSS`, or `CALIBRATION_OVERDUE`, a `severity` of `INFO`, `WARNING`, or `CRITICAL`, and optional freeform `notes`. The alert enters in `RAISED` with `raised_at` stamped from the logical clock. If the severity is `CRITICAL` and the auditorium is `OPERATING`, the auditorium immediately degrades to `DEGRADED`, firing the full cascade of §2.8: every currently-running `CONFIRMED` slot on the auditorium — one whose `slot_start_date` is on or before the logical clock and whose `slot_end_date` is strictly after it — moves to `SUSPENDED`, each suspended slot's committed screen-seconds are subtracted from its window's `committed_premium_screen_seconds`, and every covering statement recomputes.

A `FieldEngineer` acknowledges a raised alert (`RAISED → ACKNOWLEDGED`) or defers it — but deferral is forbidden for `CRITICAL` alerts from either `RAISED` or `ACKNOWLEDGED`, rejected with `ERR_CANNOT_DEFER_CRITICAL`; non-critical alerts may be deferred from either state into the terminal `DEFERRED` state. When a TechDispatch is created against an acknowledged alert, the alert auto-advances to `DISPATCHED`; when every dispatch for the alert is `COMPLETE`, the alert auto-advances to the terminal `RESOLVED`.

A `FieldEngineer` schedules a dispatch with the `qa_alert_id`, the `auditorium_id` (denormalized for routing, and it must equal the alert's own `auditorium_id`), a `scheduled_visit_date`, and a `tech_specialty` of `PROJECTION`, `SOUND`, `NETWORK`, or `GENERAL`. The dispatch enters in `SCHEDULED`. The technician's journey walks `SCHEDULED → EN_ROUTE → ON_SITE → COMPLETE`, and from any of `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` the dispatch can instead be aborted into the terminal `ABORTED` state. Completion requires non-empty `resolution_notes`; an empty note is rejected with `ERR_RESOLUTION_NOTES_REQUIRED` (HTTP 400). On completion, the parent alert resolves if no other non-terminal dispatches remain against it, and — when the alert's `alert_code` is `CALIBRATION_OVERDUE` — the parent auditorium's `last_calibration_at` is restamped to the logical clock and `calibration_overdue` resets to false.

Returning a degraded auditorium to service — `DEGRADED → OPERATING`, by a `FieldEngineer` — is gated on safety: every `CRITICAL` alert on the auditorium must be `RESOLVED`; any unresolved critical alert rejects the transition with `ERR_UNRESOLVED_CRITICAL_ALERTS`. On success, every `SUSPENDED` slot on the auditorium returns to `CONFIRMED`, each restored slot's committed screen-seconds are added back to its window's committed total, and covering statements recompute their lines.

### 3.8. Measuring the Fleet: Auditorium Quality Scores

Each auditorium surfaces two quality-score variants computed over the same input set: every QAAlert on the auditorium whose `raised_at` falls within the trailing 30 days of the logical clock. Severity weights are fixed — `INFO` counts 1, `WARNING` counts 3, `CRITICAL` counts 10.

The arithmetic variant, surfaced as `quality_score_arithmetic`, is the flat severity-weighted mean: the sum of severity weights divided by the count of alerts, using 1 in place of the count when there are no alerts. The recency variant, surfaced as `quality_score_recency`, weights each alert by linear decay: the alert's age in whole days is the floor of the elapsed seconds between `raised_at` and the logical clock divided by 86,400, clamped to the range 0 through 29; the recency weight is 1 minus the age in days divided by 30, so an alert raised today weighs 1.0 and an alert 29 days old weighs one-thirtieth. The recency score is the sum of severity-weight-times-recency-weight divided by the same clamped count. Both variants are reported to 4 decimal places with round-half-up, both are recomputed on every alert creation and resolution, and the two values differ for identical input sets whenever the alert population is not uniformly aged.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every lifecycle transition — return `200 OK`. List endpoints return `200 OK` with the pagination envelope of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/markets` | Create a market | NetworkPlanner |
| GET | `/v1/markets` | List markets | NetworkPlanner, PlatformContractManager, ReleaseScheduler, BoxOfficeAnalyst |
| GET | `/v1/markets/{marketId}` | Get a market | NetworkPlanner, PlatformContractManager, ReleaseScheduler, BoxOfficeAnalyst |
| GET | `/v1/markets/{marketId}/agreements` | List agreements in a market | NetworkPlanner, PlatformContractManager |
| POST | `/v1/markets/{marketId}/begin-evaluation` | PROSPECT → EVALUATING | NetworkPlanner |
| POST | `/v1/markets/{marketId}/approve` | EVALUATING → APPROVED | NetworkPlanner |
| POST | `/v1/markets/{marketId}/begin-build` | APPROVED → BUILDING | NetworkPlanner |
| POST | `/v1/markets/{marketId}/go-live` | BUILDING → LIVE | NetworkPlanner |
| POST | `/v1/markets/{marketId}/abandon` | EVALUATING or BUILDING → ABANDONED | NetworkPlanner |
| POST | `/v1/agreements` | Create an exhibitor agreement | PlatformContractManager |
| GET | `/v1/agreements` | List agreements | NetworkPlanner, PlatformContractManager, BoxOfficeAnalyst, ExhibitorFinanceUser |
| GET | `/v1/agreements/{agreementId}` | Get an agreement | NetworkPlanner, PlatformContractManager, BoxOfficeAnalyst, ExhibitorFinanceUser |
| POST | `/v1/agreements/{agreementId}/sign` | NEGOTIATING → SIGNED | PlatformContractManager |
| POST | `/v1/agreements/{agreementId}/activate` | SIGNED → ACTIVE | PlatformContractManager |
| POST | `/v1/agreements/{agreementId}/terminate` | Any non-terminal state → TERMINATED | PlatformContractManager |
| GET | `/v1/agreements/{agreementId}/auditoriums` | List auditoriums for an agreement | NetworkPlanner, PlatformContractManager, FieldEngineer, ReleaseScheduler |
| GET | `/v1/agreements/{agreementId}/revenue-share-statements` | List statements for an agreement | PlatformContractManager, BoxOfficeAnalyst, ExhibitorFinanceUser |
| POST | `/v1/auditoriums` | Create an auditorium | PlatformContractManager |
| GET | `/v1/auditoriums` | List auditoriums | NetworkPlanner, PlatformContractManager, FieldEngineer, ReleaseScheduler |
| GET | `/v1/auditoriums/{auditoriumId}` | Get an auditorium | NetworkPlanner, PlatformContractManager, FieldEngineer, ReleaseScheduler |
| POST | `/v1/auditoriums/{auditoriumId}/begin-construction` | DESIGN → CONSTRUCTION | PlatformContractManager |
| POST | `/v1/auditoriums/{auditoriumId}/begin-calibration` | CONSTRUCTION → CALIBRATION | FieldEngineer |
| POST | `/v1/auditoriums/{auditoriumId}/certify` | CALIBRATION → CERTIFIED | FieldEngineer |
| POST | `/v1/auditoriums/{auditoriumId}/open` | CERTIFIED → OPERATING | PlatformContractManager |
| POST | `/v1/auditoriums/{auditoriumId}/return-to-service` | DEGRADED → OPERATING | FieldEngineer |
| POST | `/v1/auditoriums/{auditoriumId}/decommission` | OPERATING or DEGRADED → DECOMMISSIONED | PlatformContractManager |
| GET | `/v1/auditoriums/{auditoriumId}/qa-alerts` | List QA alerts on an auditorium | FieldEngineer, NetworkPlanner, PlatformContractManager |
| GET | `/v1/auditoriums/{auditoriumId}/screen-slots` | List screen slots on an auditorium | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager |
| POST | `/v1/studios` | Register a studio | StudioRelationshipManager |
| GET | `/v1/studios` | List studios | StudioRelationshipManager, PostProductionScheduler, ReleaseScheduler |
| GET | `/v1/studios/{studioId}` | Get a studio | StudioRelationshipManager, PostProductionScheduler, ReleaseScheduler |
| POST | `/v1/studios/{studioId}/activate` | ONBOARDING or SUSPENDED → ACTIVE | StudioRelationshipManager |
| POST | `/v1/studios/{studioId}/suspend` | ACTIVE → SUSPENDED | StudioRelationshipManager |
| POST | `/v1/studios/{studioId}/terminate` | ACTIVE → TERMINATED | StudioRelationshipManager |
| GET | `/v1/studios/{studioId}/films` | List films for a studio | StudioRelationshipManager, PostProductionScheduler, ReleaseScheduler |
| POST | `/v1/films` | Register a film | StudioRelationshipManager |
| GET | `/v1/films` | List films | StudioRelationshipManager, PostProductionScheduler, ReleaseScheduler, BoxOfficeAnalyst |
| GET | `/v1/films/{filmId}` | Get a film | StudioRelationshipManager, PostProductionScheduler, ReleaseScheduler, BoxOfficeAnalyst |
| POST | `/v1/films/{filmId}/archive` | OUT_OF_WINDOW → ARCHIVED | StudioRelationshipManager |
| GET | `/v1/films/{filmId}/conversion-orders` | List conversion orders for a film | StudioRelationshipManager, PostProductionScheduler, QualityAssuranceReviewer, ReleaseScheduler |
| GET | `/v1/films/{filmId}/screen-slots` | List screen slots for a film | ReleaseScheduler, BoxOfficeAnalyst, StudioRelationshipManager |
| POST | `/v1/conversion-orders` | Submit a conversion order | StudioRelationshipManager |
| GET | `/v1/conversion-orders` | List conversion orders | StudioRelationshipManager, PostProductionScheduler, QualityAssuranceReviewer |
| GET | `/v1/conversion-orders/{orderId}` | Get a conversion order | StudioRelationshipManager, PostProductionScheduler, QualityAssuranceReviewer, ReleaseScheduler |
| POST | `/v1/conversion-orders/{orderId}/begin-post` | SUBMITTED or REWORK_REQUESTED → IN_POST | PostProductionScheduler |
| POST | `/v1/conversion-orders/{orderId}/submit-for-qc` | IN_POST → QC_REVIEW | PostProductionScheduler |
| POST | `/v1/conversion-orders/{orderId}/approve-release` | QC_REVIEW → APPROVED_FOR_RELEASE | QualityAssuranceReviewer |
| POST | `/v1/conversion-orders/{orderId}/request-rework` | QC_REVIEW → REWORK_REQUESTED | QualityAssuranceReviewer |
| POST | `/v1/conversion-orders/{orderId}/deliver` | APPROVED_FOR_RELEASE → DELIVERED | PostProductionScheduler |
| POST | `/v1/conversion-orders/{orderId}/cancel` | Any non-terminal state → CANCELLED | StudioRelationshipManager |
| POST | `/v1/release-windows` | Create a release window | ReleaseScheduler |
| GET | `/v1/release-windows` | List release windows | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager, NetworkPlanner |
| GET | `/v1/release-windows/{windowId}` | Get a release window | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager, NetworkPlanner |
| POST | `/v1/release-windows/{windowId}/open` | DRAFT → OPEN_FOR_BOOKING | ReleaseScheduler |
| POST | `/v1/release-windows/{windowId}/lock` | OPEN_FOR_BOOKING → LOCKED | ReleaseScheduler |
| POST | `/v1/release-windows/{windowId}/reopen` | LOCKED → REOPENED | ReleaseScheduler |
| POST | `/v1/release-windows/{windowId}/resume-booking` | REOPENED → OPEN_FOR_BOOKING | ReleaseScheduler |
| GET | `/v1/release-windows/{windowId}/screen-slots` | List slots in a window | ReleaseScheduler, BoxOfficeAnalyst |
| GET | `/v1/release-windows/{windowId}/revenue-share-statements` | List statements in a window | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager |
| POST | `/v1/screen-slots` | Propose a screen slot | ReleaseScheduler |
| GET | `/v1/screen-slots` | List screen slots | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager |
| GET | `/v1/screen-slots/{slotId}` | Get a screen slot | ReleaseScheduler, BoxOfficeAnalyst, PlatformContractManager, StudioRelationshipManager |
| POST | `/v1/screen-slots/{slotId}/confirm` | PROPOSED or HELD_OVER → CONFIRMED | ReleaseScheduler |
| POST | `/v1/screen-slots/{slotId}/reject` | PROPOSED → REJECTED | ReleaseScheduler |
| POST | `/v1/screen-slots/{slotId}/pull` | CONFIRMED, SUSPENDED, or HELD_OVER → PULLED | ReleaseScheduler |
| GET | `/v1/screen-slots/{slotId}/box-office-reports` | List reports for a slot | BoxOfficeAnalyst, ReleaseScheduler, ExhibitorFinanceUser |
| POST | `/v1/box-office-reports` | Submit a daily box office report | ExhibitorFinanceUser, BoxOfficeAnalyst |
| GET | `/v1/box-office-reports` | List box office reports | BoxOfficeAnalyst, ExhibitorFinanceUser |
| GET | `/v1/box-office-reports/{reportId}` | Get a box office report | BoxOfficeAnalyst, ExhibitorFinanceUser |
| POST | `/v1/box-office-reports/{reportId}/validate` | RECEIVED → VALIDATED | BoxOfficeAnalyst |
| POST | `/v1/box-office-reports/{reportId}/flag-discrepancy` | RECEIVED → FLAGGED_DISCREPANCY | BoxOfficeAnalyst |
| POST | `/v1/revenue-share-statements` | Create a draft statement | BoxOfficeAnalyst |
| GET | `/v1/revenue-share-statements` | List statements | BoxOfficeAnalyst, PlatformContractManager, ExhibitorFinanceUser |
| GET | `/v1/revenue-share-statements/{statementId}` | Get a statement | BoxOfficeAnalyst, PlatformContractManager, ExhibitorFinanceUser |
| POST | `/v1/revenue-share-statements/{statementId}/issue` | DRAFT → ISSUED | BoxOfficeAnalyst |
| POST | `/v1/revenue-share-statements/{statementId}/reconcile` | ISSUED → RECONCILED | PlatformContractManager |
| POST | `/v1/revenue-share-statements/{statementId}/dispute` | ISSUED → DISPUTED | ExhibitorFinanceUser |
| POST | `/v1/revenue-share-statements/{statementId}/apply-adjustment` | DISPUTED → ADJUSTED | BoxOfficeAnalyst |
| POST | `/v1/revenue-share-statements/{statementId}/reissue` | ADJUSTED → ISSUED | BoxOfficeAnalyst |
| POST | `/v1/qa-alerts` | Raise a QA alert | FieldEngineer, NetworkPlanner |
| GET | `/v1/qa-alerts` | List QA alerts | FieldEngineer, NetworkPlanner, PlatformContractManager |
| GET | `/v1/qa-alerts/{alertId}` | Get a QA alert | FieldEngineer, NetworkPlanner, PlatformContractManager |
| POST | `/v1/qa-alerts/{alertId}/acknowledge` | RAISED → ACKNOWLEDGED | FieldEngineer |
| POST | `/v1/qa-alerts/{alertId}/defer` | RAISED or ACKNOWLEDGED → DEFERRED | FieldEngineer |
| GET | `/v1/qa-alerts/{alertId}/dispatches` | List dispatches for an alert | FieldEngineer, NetworkPlanner |
| POST | `/v1/tech-dispatches` | Schedule a tech dispatch | FieldEngineer |
| GET | `/v1/tech-dispatches` | List tech dispatches | FieldEngineer, NetworkPlanner |
| GET | `/v1/tech-dispatches/{dispatchId}` | Get a tech dispatch | FieldEngineer, NetworkPlanner |
| POST | `/v1/tech-dispatches/{dispatchId}/mark-en-route` | SCHEDULED → EN_ROUTE | FieldEngineer |
| POST | `/v1/tech-dispatches/{dispatchId}/mark-on-site` | EN_ROUTE → ON_SITE | FieldEngineer |
| POST | `/v1/tech-dispatches/{dispatchId}/complete` | ON_SITE → COMPLETE | FieldEngineer |
| POST | `/v1/tech-dispatches/{dispatchId}/abort` | SCHEDULED, EN_ROUTE, or ON_SITE → ABORTED | FieldEngineer |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock (default 2026-09-01T00:00:00Z; never falls back to wall clock) | All roles |
| GET | `/v1/_clock/current_utc` | Read the current logical clock | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MARKET_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_AUDITORIUM_NOT_FOUND` | 404 |
| `ERR_STUDIO_NOT_FOUND` | 404 |
| `ERR_FILM_NOT_FOUND` | 404 |
| `ERR_CONVERSION_ORDER_NOT_FOUND` | 404 |
| `ERR_WINDOW_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MARKET_NOT_APPROVED` | 409 |
| `ERR_NO_SIGNED_AGREEMENT` | 409 |
| `ERR_NO_OPERATING_AUDITORIUM` | 409 |
| `ERR_MARKET_CAPACITY_EXCEEDED` | 409 |
| `ERR_FILM_NOT_ANNOUNCED` | 409 |
| `ERR_POST_NOT_ELAPSED` | 409 |
| `ERR_FILMMAKER_SIGNOFF_MISSING` | 409 |
| `ERR_MASTER_URL_REQUIRED` | 400 |
| `ERR_RESOLUTION_NOTES_REQUIRED` | 400 |
| `ERR_WINDOW_IN_PAST` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_AUDITORIUM_NOT_READY` | 409 |
| `ERR_CONVERSION_NOT_APPROVED` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_POST_SCHEDULE_OVERLAP` | 409 |
| `ERR_SLOT_OUTSIDE_WINDOW` | 409 |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 409 |
| `ERR_UNRESOLVED_CRITICAL_ALERTS` | 409 |
| `ERR_CANNOT_DEFER_CRITICAL` | 409 |
| `ERR_UNRESOLVED_REPORTS` | 409 |
| `ERR_SLOT_ALREADY_STARTED` | 409 |
| `ERR_STALE_VERSION` | 412 |
