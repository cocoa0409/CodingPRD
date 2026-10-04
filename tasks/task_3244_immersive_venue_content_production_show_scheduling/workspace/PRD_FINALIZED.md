# Immersive Venue Show Scheduling API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Immersive Venue Show Scheduling API, a platform built for a purpose-built immersive venue whose wraparound display demands content captured in a bespoke format at extreme resolution, staged through a capture/render/quality-control pipeline operating at extreme file sizes. The venue's commercial reality is that a single calendar must be shared among original productions, concert residencies, and one-off corporate rentals, while every programming decision must respect technical rehearsal and changeover buffers, the differing visual and haptic experience of each seating zone, and the readiness of the venue's audio beamforming, haptic seating, and environmental effects systems.

The platform therefore couples several concerns that are traditionally siloed. Content production is governed by a render wall whose availability is contested by environmental effects maintenance; show confirmation is gated on both approved media and venue-system readiness; ticket pricing reflects both the current production slate (via a venue-wide gain signal) and per-zone experience differentials, with a separate variant when a production drives haptic seating; sponsorship contracts occupy the exterior display and accrue impressions whenever a confirmed show completes, with under-delivery compensated by make-good credits. Booking, settlement, and campaign completion all run against a venue-controlled logical clock rather than wall-clock time, so that every hold window, flight window, and maintenance start is reproducible.

The audience for this document is the engineering team implementing the API. All state names, field names, error identifiers, and constants are contractual and must be reproduced exactly; prose narratives explain the business reasoning behind each rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and boilerplate that apply to every endpoint and entity in the platform.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the principal acts. The platform recognizes exactly seven roles: `ProductionDirector`, `ContentProducer`, `VenueScheduler`, `VenueOpsEngineer`, `SponsorshipManager`, `BoxOfficeAgent`, and `Guest`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

All seven roles are *opaque* with respect to identity: `X-User-ID` is a caller-supplied operator identifier that is not tied to any persisted entity. The server may record it for audit purposes, but it never compares it to the `id` of any `Production`, `Asset`, `Show`, `Booking`, `VenueSystem`, `MaintenanceWindow`, `Sponsor`, `Campaign`, or `Settlement`. In particular, when a `Guest` or `BoxOfficeAgent` acts on a booking, ownership checks are not identity-based; authorization is enforced purely by role membership for the endpoint.

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

List endpoints are paginated via two query parameters: `limit`, which caps the number of items returned, and `offset`, which specifies how many items to skip before collecting the page. If `limit` is omitted, it defaults to 10; the minimum accepted value is 1 and the maximum is 100. If `offset` is omitted, it defaults to 0.

All list endpoints return resources sorted by their `created_at` timestamp in ascending order unless otherwise specified.

The `meta` object on every list response contains four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. These appear on both paginated and non-paginated list responses.

### 2.4. Common Resource Properties

Every primary resource in the platform — `Production`, `Asset`, `RenderBatch`, `Show`, `Booking`, `VenueSystem`, `MaintenanceWindow`, `Sponsor`, `Campaign`, and `Settlement` — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation to the resource, including mutations triggered by cascading side effects from a parent or sibling resource.

Because cascading changes (for example, a production going dark and cancelling all of its shows, which in turn cancel bookings) are themselves mutations, each affected resource has its `updated_at` refreshed and its `version` incremented independently. No resource in this platform omits `updated_at` or `version`; all entities are managed under this uniform contract.

### 2.5. Nested Resource Retrieval and Existence Ordering

When an endpoint path contains multiple resource identifiers (for example, `/venue/productions/{pid}/shows/{sid}/confirm` or `/venue/sponsors/{sid}/campaigns/{cid}/activate`), the platform validates the existence of each identifier in a strict left-to-right order along the path. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource; subsequent path segments and payload checks are not evaluated. The same ordering applies to request-body foreign keys: a payload referencing a non-existent `production_id`, `sponsor_id`, or `venue_system_id` is rejected with `ERR_NOT_FOUND` before any business validation runs.

### 2.6. Validation Ordering

Every endpoint applies its validation checks in a globally defined priority order. Authentication and authorization are evaluated first: a missing or invalid role header yields `ERR_UNAUTHENTICATED` before any authorization question is asked, and a role that is recognized but not authorized for the endpoint yields `ERR_FORBIDDEN`. Only after both auth checks pass does the server evaluate resource existence (`ERR_NOT_FOUND`), then state-machine admissibility (`ERR_INVALID_STATE`), then domain-specific business checks in the order their priority numbers specify (scheduling conflicts, maintenance conflicts, capacity, accessibility, content readiness, technical readiness, single-active-production, sponsor overlap, batch availability, render-wall availability, hold expiry, asset-in-QC, optimistic-concurrency version matching, and capture-format compatibility). When a request could fail more than one of these checks, the response carries the error from the check with the lowest priority number — so, for example, a confirm request that would fail both the stale-version check and the no-approved-asset check reports the no-approved-asset condition, because that check has the lower priority number.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to pin the version of a parent entity observed at read time, so that the caller cannot overwrite changes they have not seen. The mechanism is identical for both:

- Confirming a show via the confirm endpoint requires the request payload to carry `expected_production_version`, equal to the current `version` of the parent `Production` that owns the show. If the production's version has advanced since the scheduler last read it — for example because another `ProductionDirector` activated, deactivated, or retired the production in the interim — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Activating a campaign via the activate endpoint requires the request payload to carry `expected_sponsor_version`, equal to the current `version` of the parent `Sponsor` that owns the campaign. If the sponsor's version has advanced — for example because another `SponsorshipManager` activated or paused a sibling campaign — the activate is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint in the platform accepts a version field; optimistic concurrency is enforced only on these two write paths.

### 2.8. The Logical Clock

The platform does not use wall-clock time. All temporal reasoning — show completion eligibility, campaign completion, booking hold expiry, maintenance window activation, render batch settling — is evaluated against a single logical clock maintained by the server. The logical clock starts at exactly `2026-09-01T00:00:00Z` when the server boots and never falls back to wall-clock time. A `ProductionDirector` may advance the logical clock by issuing a test-driving capability that accepts a `to_iso8601` timestamp and moves the clock to that instant; the move may be forward to any supplied instant. Advancing the clock is itself an event that triggers a sweep across all pending time-based transitions described in §3.

### 2.9. Monetary Precision and Rounding

All monetary quantities in the platform are expressed as integer or decimal cents. Where the platform computes a monetary value from a formula — for example a booking line total, a render cost, or a settlement figure — the final stored value is rounded to exactly 2 decimal places using the round-half-up convention, unless a specific rule states otherwise. Intermediate zone-level price computations use 4 decimal places, rounded half-up, before being aggregated into 2-decimal-place final values; this pinned intermediate precision is part of the contract and must not be skipped. Minutes, impression counts, and seat counts are integers and are not subject to decimal rounding.

### 2.10. Hierarchical Consistency and Cascading Lifecycle

The platform maintains strict consistency between parent and child resources. When a parent undergoes a state change that renders its children non-operational, the system cascades that change: a production going dark cancels its non-terminal shows, which in turn cancel their bookings, with refunds applied per booking status. When a child resource's state depends on the parent's, the platform prevents child transitions that would violate the parent state — for example, a show cannot be confirmed while its production is dark, and a campaign cannot be activated while its sponsor's flight window has not opened. Cascades always update `updated_at` and increment `version` on every affected resource.

### 2.11. Venue Render Wall Exclusion

The venue's render wall and its environmental effects (`ENV_FX`) maintenance windows are mutually exclusive: a render batch cannot be dispatched if any `ENV_FX` maintenance window is `SCHEDULED` or `ACTIVE` overlapping the projected render window from the dispatch instant through the computed render duration. This is a hard constraint enforced at dispatch time.

## 3. Business Logic & Workflows

This section narrates the operational workflows. State names appear in their exact UPPERCASE form so they can be matched against the endpoint table in §4.

### 3.1. The Production Slate

A `ProductionDirector` opens a new production by providing a `title`, a `production_type` (one of `ORIGINAL`, `RESIDENCY`, or `CORPORATE`), a `base_price_cents` (the per-seat price in cents at multiplier 1.0, before any experience differential is applied), and an `is_haptic_capable` flag indicating whether the production drives the venue's haptic seating zones (RING and APEX). On creation the production lands in `DRAFT` status, with `gain_cents` initialized to 0 because a draft production contributes nothing to the venue-wide gain.

The production's lifecycle is `DRAFT → ACTIVE → DARK → RETIRED`, with a `DARK → ACTIVE` reactivation path and a direct `DRAFT → RETIRED` shortcut. Activation is exclusive: at most one production may be `ACTIVE` at any moment, so attempting to activate while another production is already `ACTIVE` is rejected with `ERR_PRODUCTION_ALREADY_ACTIVE` (HTTP 409). Whenever a production transitions into `ACTIVE`, the platform recomputes the venue-wide `gain_cents` as the sum of `base_price_cents` across all productions currently in `ACTIVE` status, including the production that just activated; productions in any other status are excluded from this sum. The same recomputation is triggered on the remaining `ACTIVE` production (if any) when a peer is deactivated or retired. Each transition increments the production's `version` and refreshes its `updated_at`.

Deactivation is a much heavier operation. A production may only move `ACTIVE → DARK` when none of its shows is in `CONFIRMED` status. When the deactivation succeeds, every show of that production still in `TENTATIVE` or `REHEARSAL` is cancelled outright. Each `HELD` booking on a cancelled show is itself cancelled with `refund_cents` set to 0 — the guest had not yet paid. Each `CONFIRMED` booking on a cancelled show is cancelled with `refund_cents` set equal to that booking's `line_total_cents`, refunding the full amount. After the cascade, the platform recomputes `gain_cents` on whichever production remains `ACTIVE` (if any). Retirement (`DRAFT → RETIRED` or `DARK → RETIRED`) carries no preconditions and no cascades — a retired production simply leaves the slate.

### 3.2. The Content Pipeline: Capture, Render, Quality Control

Media for the wraparound display is captured as an `Asset` under a specific production. A `ContentProducer` captures an asset by supplying the `production_id` of its parent, a `title`, a `capture_format` (one of `WRAP_16K` or `WRAP_8K`), the captured master size `storage_gb`, and `render_hours_base` — the baseline number of render hours the asset is expected to require before any rush overhead is applied. Newly captured assets land in `CAPTURED` status with `render_cost_cents` equal to 0; the render cost is only computed when the asset passes quality control.

The capture format is constrained by the parent production's haptic capability: when the production's `is_haptic_capable` is `true`, the asset must be captured in `WRAP_16K`. Submitting a `WRAP_8K` asset under a haptic-capable production is rejected with `ERR_FORMAT_MISMATCH` (HTTP 422).

Rendering is a batched operation. A `ContentProducer` creates a `RenderBatch` by supplying a `dispatch_mode` (one of `STANDARD` or `RUSH`) and an `asset_ids` array. The batch is created in `OPEN` status, with `submitted_asset_ids` pinned to the supplied list and `submitted_asset_count` set to the number of assets in that list. The batch's `failed_asset_count` starts at 0, and `render_minutes` and `batch_cost_cents` remain uncomputed until dispatch.

Dispatching a batch (`OPEN → RENDERING`) is gated by three checks. First, the batch must have at least one submitted asset. Second, no other batch may currently be in `RENDERING` or `SETTLING` — the render wall can only host one batch at a time. Either violation is rejected with `ERR_BATCH_BUSY` (HTTP 409). Third, the render wall must be free of environmental effects maintenance: no `ENV_FX` maintenance window may be `SCHEDULED` or `ACTIVE` overlapping the projected render window from the dispatch instant through the computed render duration. A violation is rejected with `ERR_RENDER_BLOCKED_BY_MAINTENANCE` (HTTP 422).

At dispatch, every submitted asset transitions from `CAPTURED` to `RENDERING`, and the platform computes the batch's `render_minutes`. The render duration is the sum of three terms: a fixed 90 minutes of base render time, plus 45 minutes of peak rush overhead for each asset in the batch when the batch's `dispatch_mode` is `RUSH` (zero when `STANDARD`), plus 30 minutes for each `ACTIVE` campaign whose sponsor's `brand_tier` is `PREMIUM` and whose flight window covers the dispatch instant. The `batch_cost_cents` is the total render minutes multiplied by 1000 cents per render minute. The batch also derives a `render_hours` figure for reporting by dividing `render_minutes` by 60 and rounding half-up to 4 decimal places.

While the batch is `RENDERING`, advancing the logical clock past the projected completion instant moves it to `SETTLING`. A `ContentProducer` then settles the batch (`SETTLING → SETTLED`), which transitions every asset still in `RENDERING` within the batch into `QC`. Once in `QC`, an asset can be approved or failed. Approval (`QC → APPROVED`) assigns the asset's `render_cost_cents` as the asset's own `render_hours_base` multiplied by 360000 cents per hour, divided by 60 to convert to the per-minute rate, then rounded half-up to 2 decimal places; the parent batch's `submitted_asset_count` decrements by 1. Failing (`QC → QC_FAILED`) increments the batch's `failed_asset_count` by 1 and likewise decrements `submitted_asset_count` by 1. Attempting either QC action on an asset that is not in `QC` — for example, because its batch has not yet settled — is rejected with `ERR_ASSET_NOT_IN_QC` (HTTP 409).

A failed asset may be retried: the retry action returns it from `QC_FAILED` to `CAPTURED`, but only while the asset's parent production is `DRAFT` or `ACTIVE`. If the production has been `RETIRED`, the retry is rejected with `ERR_INVALID_STATE` (HTTP 409). An approved asset may be archived (`APPROVED → ARCHIVED`); archiving is unconditional. Finally, a batch may be aborted while `OPEN`, `RENDERING`, or `SETTLING`; aborting moves it to `FAILED`, transitions any assets still in `RENDERING` to `QC_FAILED`, and leaves any `CAPTURED` assets untouched in `CAPTURED`. The same cascade fires automatically if an `ENV_FX` venue system goes `OFFLINE` while a batch is mid-flight — see §3.6.

### 3.3. Programming the Calendar: Shows and the Changeover Buffer

A `VenueScheduler` programmes the calendar by creating a `Show` under an `ACTIVE` production. The scheduler supplies the `production_id`, a `show_format` (one of `FILM`, `CONCERT`, or `CORPORATE`), the `start_time` as an ISO 8601 timestamp, the `length_minutes`, and optionally `peak_rush_minutes` (the number of minutes within the show that carry peak effects density, defaulting to 0 when omitted). New shows are created in `TENTATIVE` status, and their reserved window for conflict detection has not yet been computed.

The reserved window is materialized when the scheduler schedules rehearsal, transitioning the show `TENTATIVE → REHEARSAL`. The rehearsal always reserves 120 minutes preceding the show's `start_time`. The changeover that follows the show is computed from the base 60 minutes, plus 30 minutes for each format transition between this show and its temporally adjacent prior or next non-cancelled show — non-cancelled means any status other than `CANCELLED`, so `TENTATIVE`, `REHEARSAL`, `CONFIRMED`, and `COMPLETED` shows all count as neighbours (a "format transition" occurs whenever the neighbour's `show_format` differs from this show's), plus an additional 20 minutes when the show's `peak_rush_minutes` is at least 30. The show's reserved window for conflict detection is the half-open interval from `start_time` minus the rehearsal minutes through `start_time` plus `length_minutes` plus the changeover minutes. Two shows conflict whenever their reserved windows overlap strictly — that is, one's start precedes the other's end and vice versa.

The conflict rule is enforced at rehearsal scheduling, which is the moment the show's reserved window is materialized: because a freshly created `TENTATIVE` show has no reserved window yet, show creation performs no conflict check; if the newly-rehearsed show's reserved window overlaps the reserved window of any non-cancelled show on the calendar, the rehearsal request is rejected with `ERR_SHOW_CONFLICT` (HTTP 422). For the purpose of this comparison, a `TENTATIVE` neighbour whose rehearsal and changeover have not yet been computed is treated as occupying its bare show window, from its `start_time` through `start_time` plus `length_minutes`. Scheduling rehearsal also requires the parent production to be `ACTIVE`; otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409).

Confirmation (`REHEARSAL → CONFIRMED`) is the show's commitment point and is guarded by three additional conditions, all of which must hold simultaneously. First, the parent production must still be `ACTIVE`. Second, at least one asset of the production must have reached `APPROVED` — a show cannot be confirmed without media ready to play. Failing this check is rejected with `ERR_NO_APPROVED_ASSET` (HTTP 422). Third, the show's `tech_readiness` must be `READY`, meaning no venue system whose kind the show requires is currently `DEGRADED` or `OFFLINE`; otherwise the confirm is rejected with `ERR_TECH_NOT_READY` (HTTP 422). The confirm request is also subject to the optimistic-concurrency rule described in §2.7 — the request must carry `expected_production_version` matching the production's current `version`, else the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

On a successful confirm, the platform pins two pricing-relevant snapshots on the show: `utilization_at_lock` records the venue's current zone utilization as a number between 0 and 1, and `haptic_surcharge_cents_at_lock` records the current haptic surcharge in cents per seat. Both default to 0 on a freshly created show and are only meaningfully populated at confirm time; they are not recomputed afterwards.

Completion (`CONFIRMED → COMPLETED`) becomes eligible once the logical clock has advanced past `start_time` plus `length_minutes`. At completion, the platform runs settlement (see §3.5), creates a `Settlement` record whose `status` is `FINAL`, stores the settlement's `id` on the show's `settlement_snapshot_id`, and accrues impressions to every `ACTIVE` campaign whose flight window overlaps the show window (see §3.7). Cancellation (`TENTATIVE`, `REHEARSAL`, or `CONFIRMED → CANCELLED`) compensates bookings: `HELD` bookings are cancelled with `refund_cents` equal to 0, and `CONFIRMED` bookings are cancelled with `refund_cents` equal to their `line_total_cents`. Cancellation can be initiated either directly by a `VenueScheduler` or `ProductionDirector`, or indirectly when the parent production is deactivated.

### 3.4. Ticketing: Zones, Accessibility, and Pricing Variants

A `Guest` or a `BoxOfficeAgent` acting on a guest's behalf books seats by posting a payload with the target `zone` (one of `MAIN`, `RING`, or `APEX`), the number of `seats` (at least 1), and an optional `seat_kind` (one of `STANDARD`, `WHEELCHAIR`, or `COMPANION`, defaulting to `STANDARD` when omitted). The new booking is created in `HELD` status.

The venue has three seating zones with fixed capacities and experience weights. `MAIN` has 300 seats at multiplier 1.0. `RING` has 200 seats at multiplier 1.4. `APEX` has 100 seats at multiplier 1.8. A booking may not exceed the remaining capacity of its zone for the show — that is, the zone's fixed capacity minus the seats already committed by non-cancelled bookings on the same show in that zone. Exceeding the remaining capacity is rejected with `ERR_ZONE_CAPACITY_EXCEEDED` (HTTP 422). Accessibility is zone-constrained: `WHEELCHAIR` and `COMPANION` seat kinds are only available in `MAIN` and `RING`; the `APEX` zone is not wheelchair accessible and bookings there must use `STANDARD`. Violating this rule is rejected with `ERR_ACCESSIBILITY_ZONE` (HTTP 422).

Pricing is computed at booking creation time and pinned on the booking. The venue-wide `gain_cents` — the sum of `base_price_cents` over all productions currently `ACTIVE` — drives a zone multiplier specific to the production P that owns the show: for each zone, the multiplier is one plus the product of `gain_cents` and the zone's experience weight, divided by the sum across all three zones of the zone's capacity multiplied by its experience weight. The zone base `B0` for the active production is then the production's `base_price_cents` multiplied by that zone multiplier, rounded half-up to 4 decimal places.

Two pricing variants are possible, and the booking records which one produced its quote on `quoted_variant`. The default variant is `EXPERIENCE_DIFF`, used when the production is not haptic-capable, or when the booked zone is `MAIN`. Under this variant, the per-seat `unit_price_cents` is `B0` multiplied by 1.06 (a venue fee of 6 percent), rounded half-up to 2 decimal places, and the booking's `line_total_cents` is the number of `seats` multiplied by `B0`, multiplied by 1.06, rounded half-up to 2 decimal places. The line total is computed from the 4-decimal-place pinned `B0`, not by multiplying `seats` by `unit_price_cents`; this ordering is contractual.

The second variant is `HAPTIC_SURCHARGE`, used when the production's `is_haptic_capable` is `true` *and* the booked zone is `RING` or `APEX`. Under this variant, the per-seat `unit_price_cents` is `B0` multiplied by 1.08 (an 8 percent haptic surcharge), rounded half-up to 2 decimal places, and `line_total_cents` is `seats` multiplied by `B0`, multiplied by 1.08, rounded half-up to 2 decimal places. A `MAIN` booking on a haptic-capable production does not receive the haptic surcharge — it falls through to the `EXPERIENCE_DIFF` variant and is priced at the 6 percent venue fee instead.

The booking's `refund_cents` is 0 at creation and is only populated when the booking is cancelled. Bookings are only accepted when the parent show is in `REHEARSAL` or `CONFIRMED`; a booking attempt against a `TENTATIVE`, `COMPLETED`, or `CANCELLED` show is rejected with `ERR_INVALID_STATE` (HTTP 409).

A held booking must be confirmed within 15 minutes of its creation, measured against the logical clock. Confirming after this hold window has elapsed is rejected with `ERR_BOOKING_HOLD_EXPIRED` (HTTP 422). Confirming within the window transitions the booking `HELD → CONFIRMED` and finalizes the seat inventory for the zone. Cancellation from `HELD` sets `refund_cents` to 0; cancellation from `CONFIRMED` sets `refund_cents` to the booking's `line_total_cents`. Hold expiry also fires automatically when the logical clock advances past the 15-minute mark on a `HELD` booking, transitioning it to `CANCELLED` with `refund_cents` of 0.

### 3.5. Settlement

Settlement runs automatically when a show completes. The platform computes a `Settlement` record under the show, in `FINAL` status, with the following fields. `gross_cents` is the sum of `line_total_cents` over the show's `CONFIRMED` bookings. `refunds_cents` is the sum of `refund_cents` over the show's `CANCELLED` bookings. `net_cents` is `gross_cents` minus `refunds_cents`.

The sponsor payout follows a waterfall allocation across every campaign that is `ACTIVE` and whose flight window overlaps the show window. Campaigns are processed in order of their `created_at` in ascending order, with ties broken by `exterior_slots` in descending order. Each campaign's payout share is the show's `net_cents` multiplied by 10 percent, divided by the number of overlapping campaigns (treating the count as at least 1 to avoid division by zero), rounded half-up to 2 decimal places. `sponsor_payout_cents` is the sum of these per-campaign shares, capped at `net_cents`. `venue_retain_cents` is `net_cents` minus `sponsor_payout_cents`. The settlement's `id` is pinned on the show's `settlement_snapshot_id`.

Reading a show's settlement via `GET /venue/shows/{show_id}/settlement` is a list retrieval over the settlements recorded under that show. Because the show identifier exists, the `ERR_NOT_FOUND` existence check of §2.5 passes regardless of the show's status; when no `Settlement` has been recorded for the show yet — for example while the show is still in `TENTATIVE`, `REHEARSAL`, or `CONFIRMED` — the endpoint responds with HTTP 200 and an empty list rather than an error. Once the show completes and settlement has run, the list contains the single `FINAL` settlement.

### 3.6. Venue Systems and Maintenance

The venue's technical infrastructure is modelled as a set of `VenueSystem` resources, each with a `name`, a `kind` (one of `AUDIO_BEAM`, `HAPTIC`, or `ENV_FX`), a `status`, and a `consecutive_failed_windows` counter that starts at 0. A `VenueOpsEngineer` registers a new system; it comes up in `ONLINE` status.

Maintenance is scheduled as a `MaintenanceWindow` under a specific system, with a `start_time`, an `end_time`, and a `buffer_minutes` specifying how many minutes after the window closes must remain show-free. The window is created in `SCHEDULED` status. Two constraints govern scheduling: the window's `end_time` must be strictly later than its `start_time`, and the window plus its buffer must not overlap the reserved window of any non-cancelled show on the calendar. The overlap test uses the same strict (half-open) comparison as the show-vs-show rule in §3.3: the window-plus-buffer interval conflicts with a show's reserved window only when each interval's start precedes the other's end, so a window-plus-buffer end that merely touches a show's reserved start (or vice versa) does not conflict. A `TENTATIVE` show, whose rehearsal and changeover minutes have not yet been computed, is treated as occupying its bare show window from `start_time` through `start_time` plus `length_minutes`. Either violation is rejected with `ERR_MAINTENANCE_CONFLICT` (HTTP 422).

When the logical clock reaches a window's `start_time`, the window transitions `SCHEDULED → ACTIVE` and the parent venue system transitions `ONLINE → MAINTENANCE`. Closing the window is a deliberate action: the engineer marks it `COMPLETED` once the logical clock has passed `end_time`, which returns the parent system to `ONLINE` and resets its `consecutive_failed_windows` to 0; or marks it `FAILED`, which leaves the window in `FAILED`, increments the parent system's `consecutive_failed_windows` by 1, and does not change the system's current status by itself.

The system's health is then derived from the consecutive failure counter. When `consecutive_failed_windows` reaches 2, the system — whether currently `ONLINE` or `MAINTENANCE` — flips to `DEGRADED`, and every show whose window requires this system's kind has its `tech_readiness` recomputed to `DEGRADED`. When the counter reaches 3, the system goes `OFFLINE`; this transition additionally aborts any `RENDERING` render batch, cascading its assets into `QC_FAILED` per §3.2. An engineer can also repair a `DEGRADED` system back to `ONLINE` directly, which resets `consecutive_failed_windows` to 0.

### 3.7. Sponsorships and Exterior Display Advertising

A `SponsorshipManager` registers a `Sponsor` by supplying a `name` and a `brand_tier` (one of `STANDARD` or `PREMIUM`). The sponsor is created with `active_campaign_count` equal to 0. Campaigns are created under a sponsor by supplying the `sponsor_id`, a `start_time`, an `end_time`, the number of `exterior_slots` the campaign books (at least 1), the `spot_seconds` length of each spot, and the `contracted_impressions` total. The campaign is created in `DRAFT` status with `delivered_impressions` equal to 0.

Activation (`DRAFT → ACTIVE`, or `PAUSED → ACTIVE` when resuming) requires the campaign's flight window to be currently open — the logical clock must be at or after `start_time` and strictly before `end_time`. The activate call is also subject to the optimistic-concurrency rule described in §2.7, requiring `expected_sponsor_version` matching the sponsor's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Additionally, a sponsor may not have two `ACTIVE` campaigns whose flight windows overlap; an activation that would create such an overlap is rejected with `ERR_CAMPAIGN_OVERLAP` (HTTP 422). On successful activation, the sponsor's `active_campaign_count` increments by 1 and the sponsor's `version` increments by 1.

A campaign may be paused (`ACTIVE → PAUSED`), which decrements the sponsor's `active_campaign_count` by 1. Resuming a paused campaign goes through the same activation endpoint and increments the count again. Cancellation is permitted from `DRAFT`, `ACTIVE`, or `PAUSED`; it decrements `active_campaign_count` by 1 only if the campaign was `ACTIVE` at the moment of cancellation, and leaves the count unchanged otherwise.

Completion is system-driven: when the logical clock reaches or passes the campaign's `end_time`, the campaign transitions `ACTIVE → COMPLETED`. At completion the platform finalizes two figures. `under_delivery` is the larger of zero and the difference between `contracted_impressions` and `delivered_impressions`. `make_good_credits` is twice `under_delivery` — the impressions owed to the sponsor as compensation. The sponsor's `active_campaign_count` also decrements by 1.

Impressions accrue at show completion: every campaign that is `ACTIVE` and whose flight window overlaps the completing show's window has its `delivered_impressions` incremented by the per-show impression count. That count is the campaign's `exterior_slots` multiplied by the show's `length_minutes`, multiplied by the campaign's `spot_seconds`, divided by 60. Both `STANDARD` and `PREMIUM` tiers use a multiplier of 1.0 for this calculation — premium tier affects cost, not impression count.

### 3.8. The Logical Clock as a Sweep Driver

The logical clock described in §2.8 doubles as a sweep driver. When the clock is advanced to a new instant, the platform applies every pending time-based transition whose condition now holds, in dependency order. Specifically: any `CONFIRMED` show whose completion instant (`start_time` plus `length_minutes`) has been reached is completed, firing the settlement and impression accrual described in §3.5 and §3.7; any `ACTIVE` campaign whose `end_time` has been reached is completed, finalizing `under_delivery` and `make_good_credits`; any `HELD` booking whose 15-minute hold window has elapsed is expired to `CANCELLED` with `refund_cents` of 0; any `SCHEDULED` maintenance window whose `start_time` has been reached transitions to `ACTIVE` and brings its parent system into `MAINTENANCE`; and any `RENDERING` render batch whose projected completion instant has been reached transitions to `SETTLING`, awaiting the settle action.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions, confirmations, cancellations, and lifecycle actions — return `200 OK`. The table below summarizes each endpoint; the full request payload, response body, and side effects for each endpoint are specified by the narrative in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venue/productions` | Create a production | ProductionDirector |
| GET | `/venue/productions` | List productions | ProductionDirector, ContentProducer, VenueScheduler, VenueOpsEngineer, SponsorshipManager, BoxOfficeAgent |
| GET | `/venue/productions/{production_id}` | Get a production | ProductionDirector, ContentProducer, VenueScheduler, VenueOpsEngineer, SponsorshipManager, BoxOfficeAgent |
| POST | `/venue/productions/{production_id}/activate` | Activate production (DRAFT or DARK → ACTIVE) | ProductionDirector |
| POST | `/venue/productions/{production_id}/deactivate` | Deactivate production (ACTIVE → DARK); cancels non-terminal shows | ProductionDirector |
| POST | `/venue/productions/{production_id}/retire` | Retire production (DRAFT/DARK → RETIRED) | ProductionDirector |
| POST | `/venue/assets` | Capture a new asset under a production | ContentProducer |
| GET | `/venue/assets` | List assets, optionally filtered by production | ContentProducer, ProductionDirector |
| GET | `/venue/assets/{asset_id}` | Get an asset | ContentProducer, ProductionDirector |
| POST | `/venue/assets/{asset_id}/qc/approve` | Approve asset QC | ContentProducer |
| POST | `/venue/assets/{asset_id}/qc/fail` | Fail asset QC | ContentProducer |
| POST | `/venue/assets/{asset_id}/retry` | Retry a QC_FAILED asset (back to CAPTURED) | ContentProducer |
| POST | `/venue/assets/{asset_id}/archive` | Archive an APPROVED asset | ContentProducer |
| POST | `/venue/render-batches` | Create a render batch | ContentProducer |
| GET | `/venue/render-batches/{batch_id}` | Get a render batch | ContentProducer, ProductionDirector |
| POST | `/venue/render-batches/{batch_id}/dispatch` | Dispatch batch to rendering | ContentProducer |
| POST | `/venue/render-batches/{batch_id}/settle` | Settle a SETTLING batch (assets → QC) | ContentProducer |
| POST | `/venue/render-batches/{batch_id}/abort` | Abort a batch | ContentProducer |
| POST | `/venue/shows` | Create a show under a production | VenueScheduler |
| GET | `/venue/shows` | List shows, optionally filtered by production | VenueScheduler, ProductionDirector, BoxOfficeAgent |
| GET | `/venue/shows/{show_id}` | Get a show | VenueScheduler, ProductionDirector, BoxOfficeAgent, Guest |
| POST | `/venue/shows/{show_id}/schedule-rehearsal` | Compute rehearsal/changeover windows and move show to REHEARSAL | VenueScheduler |
| POST | `/venue/shows/{show_id}/confirm` | Confirm a show (REHEARSAL → CONFIRMED), OCC on Production.version | VenueScheduler |
| POST | `/venue/shows/{show_id}/complete` | Complete a CONFIRMED show; runs settlement | VenueScheduler |
| POST | `/venue/shows/{show_id}/cancel` | Cancel a show | VenueScheduler, ProductionDirector |
| POST | `/venue/shows/{id}/bookings` | Create a booking (HELD) | Guest, BoxOfficeAgent |
| GET | `/venue/shows/{id}/bookings` | List bookings for a show | BoxOfficeAgent, VenueScheduler, Guest |
| GET | `/venue/shows/{id}/settlement` | Get settlement for a completed show | VenueScheduler, ProductionDirector |
| GET | `/venue/bookings/{booking_id}` | Get a booking | Guest, BoxOfficeAgent |
| POST | `/venue/bookings/{booking_id}/confirm` | Confirm a HELD booking | Guest, BoxOfficeAgent |
| POST | `/venue/bookings/{booking_id}/cancel` | Cancel a booking (HELD or CONFIRMED) | Guest, BoxOfficeAgent |
| POST | `/venue-systems` | Register a venue system | VenueOpsEngineer |
| GET | `/venue-systems` | List venue systems | VenueOpsEngineer, VenueScheduler, ProductionDirector |
| GET | `/venue-systems/{system_id}` | Get a venue system | VenueOpsEngineer, VenueScheduler |
| POST | `/venue-systems/{system_id}/repair` | Repair a DEGRADED system back to ONLINE | VenueOpsEngineer |
| POST | `/venue/maintenance-windows` | Schedule a maintenance window | VenueOpsEngineer |
| GET | `/venue/maintenance-windows` | List maintenance windows, optionally filtered by venue system | VenueOpsEngineer, VenueScheduler |
| GET | `/venue/maintenance-windows/{window_id}` | Get a maintenance window | VenueOpsEngineer, VenueScheduler |
| POST | `/venue/maintenance-windows/{window_id}/complete` | Mark an ACTIVE window COMPLETED | VenueOpsEngineer |
| POST | `/venue/maintenance-windows/{window_id}/fail` | Mark an ACTIVE window FAILED | VenueOpsEngineer |
| POST | `/venue/sponsors` | Register a sponsor | SponsorshipManager |
| GET | `/venue/sponsors` | List sponsors | SponsorshipManager, ProductionDirector |
| GET | `/venue/sponsors/{sponsor_id}` | Get a sponsor | SponsorshipManager |
| POST | `/venue/campaigns` | Create a campaign | SponsorshipManager |
| GET | `/venue/campaigns` | List campaigns, optionally filtered by sponsor | SponsorshipManager |
| GET | `/venue/campaigns/{campaign_id}` | Get a campaign | SponsorshipManager |
| POST | `/venue/campaigns/{campaign_id}/activate` | Activate a campaign (OCC on Sponsor.version) | SponsorshipManager |
| POST | `/venue/campaigns/{campaign_id}/pause` | Pause an ACTIVE campaign | SponsorshipManager |
| POST | `/venue/campaigns/{campaign_id}/cancel` | Cancel a campaign | SponsorshipManager |
| POST | `/venue/_clock/set_current_utc` | Set the logical clock (server default is 2026-09-01T00:00:00Z) | ProductionDirector |

## 5. Error Code Catalogue

The table below lists every error identifier the platform may return. Trigger conditions for each error are described in the relevant §2 or §3 narrative; the table exists to fix the spelling of each identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SHOW_CONFLICT` | 422 |
| `ERR_MAINTENANCE_CONFLICT` | 422 |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 422 |
| `ERR_ACCESSIBILITY_ZONE` | 422 |
| `ERR_NO_APPROVED_ASSET` | 422 |
| `ERR_TECH_NOT_READY` | 422 |
| `ERR_PRODUCTION_ALREADY_ACTIVE` | 409 |
| `ERR_CAMPAIGN_OVERLAP` | 422 |
| `ERR_BATCH_BUSY` | 409 |
| `ERR_RENDER_BLOCKED_BY_MAINTENANCE` | 422 |
| `ERR_BOOKING_HOLD_EXPIRED` | 422 |
| `ERR_ASSET_NOT_IN_QC` | 409 |
| `ERR_FORMAT_MISMATCH` | 422 |
