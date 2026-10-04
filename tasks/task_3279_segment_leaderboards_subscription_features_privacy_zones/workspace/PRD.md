# Segment Leaderboards, Subscription Features & Privacy Zones API — Product Requirements Document

## 1. Introduction

Endurance athletes train with devices from many vendors, upload the same workout from two different apps, share routes with followers, and compete on user-defined course sections called segments. This document specifies the Segment Leaderboards, Subscription Features & Privacy Zones API: the server-side platform that receives activity uploads from devices and applications, reconciles cross-device duplicates, matches activities against athlete-authored segments, and maintains the integrity of the leaderboards those athletes care about. Leaderboard integrity is a first-class concern: impossible efforts are flagged automatically by speed heuristics, community members can flag suspected vehicle-assisted or miscategorized efforts, and a moderation workflow resolves disputes with a safety-score system that can automatically hide a repeat offender's public presence.

The platform is also a business. A subscription tier unlocks full leaderboard depth, unlimited route planning, and live location sharing, while free athletes operate under explicit weekly caps and truncated leaderboard views. Privacy is treated as seriously as performance: every athlete may define a privacy zone around a home anchor so that the public representation of an activity hides its true start and end points, and any athlete may opt out of contributing to the public heat map. Clubs, challenges, and virtual events layer social structure on top of the activity graph, each with its own participation rules and administrative cascade behavior. Finally, the platform honors data-portability and erasure obligations: any athlete can export a complete copy of their data, and account deletion triggers a deterministic cascade that scrubs personal information and unwinds every competitive and social footprint the account leaves behind.

All time-sensitive behavior in the system — subscription lapse, challenge closure, event completion, and all window validations — is driven by a single logical clock rather than wall-clock time, so that behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When a request is authenticated but the role is not permitted for the endpoint — including entity-backed ownership violations, such as an athlete acting on another athlete's resource or a club-administrative action attempted by someone without an `ACTIVE` admin membership in that club — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three roles are recognized. The role names must appear exactly as follows:

- `Athlete` — a registered athlete acting on their own resources. When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting Athlete; ownership checks on any resource that references an Athlete compare the resource's athlete-referencing foreign-key field (for example `athlete_id`, `creator_id`, `owner_id`, or `reporter_id`) to `X-User-ID`.
- `Moderator` — the leaderboard-integrity role that adjudicates flags. When `X-User-Role` is `Moderator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `PlatformAdmin` — an operator role with superset access across all business endpoints and exclusive control of the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Self-targeted operations (self-deletion, leaving a membership, withdrawing a participation, declining or rejoining one's own RSVP, stopping one's own beacon session, flagging only other athletes' efforts) compare the relevant athlete-referencing field of the target resource against `X-User-ID` when the caller's role is `Athlete`.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and its acceptable range is a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order (`created_at` ascending).

List responses carry pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, used for optimistic concurrency control.

All entities in this system — athletes, subscriptions, privacy zones, activities, segments, efforts, flags, clubs, memberships, challenges, participations, events, RSVPs, safety contacts, beacon sessions, heat map cells, and route plans — carry the full common-field set. Any cascade that mutates a resource (for example, exclusion of an effort or a flag adjudication touching an activity) refreshes that resource's `updated_at` and increments its `version` as with any other mutation.

### 2.5. Nested Resource Retrieval and Validation Order

The API validates identifiers in nested URL paths strictly left to right. A request to a child resource under a nonexistent parent is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that fails to resolve, without inspecting later path segments. Existence checks apply to athletes, zones, activities, segments, efforts, flags, clubs, memberships, challenges, participations, events, RSVPs, and beacon sessions alike. One deliberate wrinkle: an activity that has been automatically hidden (see the safety-score rules in §3) reads as `ERR_NOT_FOUND` to any caller who is not its owner, exactly as if it did not exist.

Beyond existence, validation across the API proceeds in a fixed priority order so that the *first* failing check determines the error the client sees. Authentication comes first (missing or malformed headers), then role and ownership authorization, then existence of path-referenced resources, then existence of body-referenced foreign-key targets (`creator_id`, `reporter_id`, `segment_id`, and `athlete_id` on joins — failures here surface as `ERR_VALIDATION`), then state-permission checks on the target resource, then the club-archived gate on club-scoped writes, then safety rules, then temporal-window rules, then overlap-conflict rules, then uniqueness and membership constraints, then duplicate-upload detection, then capacity checks, then subscription gating, and finally cross-entity referential consistency. When several of these checks could fail on the same request, the earlier check in this ordering wins and its error code is the one returned.

### 2.6. The Logical Clock and Lazy Transitions

All time-dependent behavior in the system is driven by a single logical clock, never by wall-clock time. At startup the logical clock reads exactly 2026-09-01T00:00:00Z; before any administrative action it stays at that instant and never falls back to real time. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied instant `to_iso8601` and returns the new `current_utc`.

Three lifecycle flips are **lazy**: they are not performed by a background job but are evaluated on the first read or write that touches the resource after the boundary has been crossed. A subscription whose period end has been reached flips from `ACTIVE` to `LAPSED` on the next access; a challenge whose window end has passed flips from `ACTIVE` to `CLOSED` on the next read; and a published event whose scheduled start has passed flips from `PUBLISHED` to `COMPLETED` on the next read. Tests cross these boundaries by advancing the logical clock and then reading.

### 2.7. Optimistic Concurrency Control

Exactly one write in the system is protected by optimistic concurrency control: updating a privacy zone's geometry. Because that mutation re-obfuscates every activity belonging to the owning athlete — a cascading write across the athlete aggregate — the request must carry `expected_athlete_version`, a non-optional field holding the athlete's `version` as last observed by the client. If that value does not match the athlete's current `version` — because another writer has already advanced the athlete aggregate since the client last read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and no zone or activity fields are changed. No other endpoint takes a version field.

### 2.8. Numeric Precision and Distance Measurement

Distances between coordinates are computed with the haversine formula in double precision, using an Earth radius of 6,371,000 meters. Zone-containment and segment-overlap comparisons against a radius or epsilon use an at-most-or-less-than boundary as stated in the relevant rule: containment inside a privacy zone includes points exactly on the radius, while a segment-overlap conflict requires both endpoint distances to be strictly less than the 50-meter epsilon, so a distance of exactly 50 meters on either endpoint is not an overlap.

Speeds and scores carry their own precision rules, stated where they are computed: `avg_speed_kmh` is rounded half-up to two decimal places, the speed-check threshold comparison is performed in unrounded double precision, and `estimated_load_score` is rounded half-up to one decimal place.

### 2.9. Subscription Gating and the Free Tier

An athlete's *effective tier* is `SUMMIT` while they hold a subscription in `ACTIVE` status and `FREE` otherwise (including after cancellation or lapse, regardless of the tier recorded at registration). Three features are gated on an `ACTIVE` subscription:

1. Reading a leaderboard with a `limit` greater than 10. Free-tier callers may only view the top 10 rows plus their own rank; asking for more is rejected with `ERR_SUBSCRIPTION_REQUIRED` (HTTP 402).
2. Creating a route plan beyond the free weekly allowance. A free athlete may create at most three route plans sharing the same `week_start`; the fourth and subsequent plans in the same week require an active subscription. When the cap is hit by an athlete with no active subscription the request is rejected with `ERR_FREE_TIER_ROUTE_CAP` (HTTP 402) — note that the free-tier cap is evaluated *before* the generic subscription gate, so the cap error, not `ERR_SUBSCRIPTION_REQUIRED`, is what a free athlete sees on the fourth plan.
3. Starting a beacon sharing session, which requires an active subscription and is otherwise rejected with `ERR_SUBSCRIPTION_REQUIRED`.

Feature gating flips immediately when a subscription is cancelled or lapses: leaderboard full-board reads, route-plan creation, and beacon activation become free-tier gated for the owner from that moment on.

### 2.10. Reverse-Reachability Listing

In addition to nested collection reads, the system exposes flat list endpoints for activities, efforts, flags, memberships, participations, RSVPs, challenges, and events. Each accepts foreign-key filters as query parameters (for example `athlete_id`, `segment_id`, `activity_id`, `club_id`, `challenge_id`, `event_id`, `reporter_id`, plus status and category filters where applicable), allowing clients to reach every child record without knowing its parent's identifier — including walking duplicate chains via `duplicate_of_id` on activities.

## 3. Business Logic & Workflows

### 3.1. Athlete Registration, Data Export, and Erasure

Anyone registering provides a unique `email` (stored lowercased; uniqueness is enforced globally and a taken address is rejected with `ERR_UNIQUE_VIOLATION`), a public `display_name` of at most 60 characters, and a home anchor as `home_lat` and `home_lng` — the latitude between minus 90 and 90 inclusive, the longitude between minus 180 and 180 inclusive. Registration optionally accepts a `tier` of `FREE` or `SUMMIT` (defaulting to `FREE`) and a `heatmap_opt_out` flag (defaulting to false). A new athlete begins with `status` `ACTIVE` and a `safety_score` of 100.

An athlete (or a `PlatformAdmin`) may request a complete export of their account at any time. The export bundles the profile, all activities with their raw track data, all efforts, all segments the athlete created, memberships, challenge participations, event RSVPs, privacy zones, safety contacts, and subscriptions — returned as an object with keys `profile`, `activities`, `efforts`, `segments`, `memberships`, `participations`, `rsvps`, `privacy_zones`, `safety_contacts`, and `subscriptions`.

Account deletion is self-service only for athletes: the athlete identified in the path must equal the caller's `X-User-ID`, otherwise `ERR_FORBIDDEN`. Deletion moves the athlete from `ACTIVE` to `DELETED` and runs a deterministic erasure cascade. Personal information is scrubbed in place — the `email` is overwritten to the literal address `deleted-{id}@erased.invalid` and the `display_name` is overwritten to the literal string `Deleted Athlete`. Every effort the athlete has ever recorded is excluded, with its `exclusion_reason` left unchanged if one is already set and otherwise stamped `FLAG_UPHELD`. Every `COMPLETED` activity the athlete owns moves to `REJECTED` (activities already `DUPLICATE` or `REJECTED` are untouched). Every still-`OPEN` flag the athlete filed as a reporter moves to `REJECTED`. Every `ACTIVE` club membership moves to `LEFT`. Every `JOINED` challenge participation moves to `WITHDRAWN`. Every `GOING` event RSVP moves to `DECLINED`, decrementing the host event's `rsvp_count` by one per row. Every `LIVE` beacon session moves to `ENDED`. And every club the athlete owns moves to `ARCHIVED`, running the full club-archive cascade described in §3.6.

### 3.2. Subscriptions: Creation, Cancellation, and Lazy Lapse

A subscription is created for an athlete from a `plan` of either `SUMMIT_MONTHLY` or `SUMMIT_ANNUAL`, a `started_at` instant in ISO 8601 UTC, and an `expires_at` instant that must be strictly after `started_at` (otherwise `ERR_VALIDATION`). A new subscription begins `ACTIVE`. At most one subscription per athlete may be `ACTIVE` at any time; attempting to create a second one is rejected with `ERR_INVALID_STATE`.

Cancellation — by the owning athlete or by a `PlatformAdmin`, who may cancel any subscription — records an optional free-text `cancel_reason` and moves the subscription from `ACTIVE` to `CANCELLED`. A subscription that simply runs out of time moves from `ACTIVE` to `LAPSED` lazily: the flip happens on the first read or write that touches it after the logical clock reaches `expires_at`. Both outcomes flip the owner's effective tier to free immediately, per §2.9. Subscriptions may be listed per athlete with an optional `status` filter, and both listing and single-read paths evaluate lazy lapse before responding.

### 3.3. Privacy Zones and Route Obfuscation

Each athlete may define exactly one privacy zone — a second attempt is rejected with `ERR_UNIQUE_VIOLATION`. A zone is created with a `center_lat`, `center_lng`, and an integer `radius_m` between 200 and 2000 meters inclusive, and begins in `ACTIVE` status.

The zone drives **route obfuscation**. For every activity of the owner, the public route is derived from the raw `track_points` by walking the ordered points and dropping each one whose haversine distance to the center of *any* of the owner's `ACTIVE` zones is at most that zone's radius (a point exactly on the boundary counts as inside and is dropped). The surviving ordered points form the activity's `obfuscated_track`; `obfuscated_start_lat` and `obfuscated_start_lng` hold the first surviving point's coordinates, and `obfuscated_end_lat` and `obfuscated_end_lng` hold the last surviving point's coordinates. If every track point lies inside at least one active zone, the activity is fully swallowed: `obfuscated_track` is empty and all four obfuscated coordinate fields are null — yet the activity still completes and still matches segments, because matching always uses the raw track, never the obfuscated one.

Obfuscation is recomputed on four occasions: when an activity finishes uploading, when the zone is created, when its geometry is updated, and when it flips between `ACTIVE` and `DISABLED`. Disabling a zone recomputes every owner activity with that zone excluded; re-enabling recomputes with it included again. The zone's `status` is `ACTIVE` or `DISABLED`, and both transitions are owner-only (`ERR_FORBIDDEN` otherwise).

Updating a zone's geometry is the system's OCC-guarded write (§2.7): the request carries `center_lat`, `center_lng`, `radius_m`, and `expected_athlete_version`; a stale athlete version is rejected with `ERR_STALE_VERSION`, and a successful update increments the athlete's `version` by one and recomputes obfuscation across all of the owner's activities.

Public reads expose only the obfuscated route: a caller who is not the activity's owner (or a privileged role) receives the obfuscated coordinates and `obfuscated_track` in place of the raw fields.

### 3.4. Activity Upload, Duplicate Detection, and the Segment Sweep

Uploading an activity is the busiest write in the system. The payload carries a `device_source` tag (for example `wahoo-elemnt`, `garmin-edge`, or `mobile-app`), a declared `sport_type` of `RIDE`, `RUN`, `VIRTUAL_RIDE`, `VIRTUAL_RUN`, `SWIM`, or `EBikeRide`, a `started_at` instant, a `duration_s` in seconds strictly greater than zero, a `distance_m` in meters strictly greater than zero, an ordered `track_points` array of at least two `{lat, lng, t_offset_s}` entries, the raw corner coordinates `start_lat`, `start_lng`, `end_lat`, `end_lng`, and a client-supplied `idempotency_key`. An optional `effort_hints` array of `{segment_id, elapsed_time_s, elevation_gain_m}` entries lets a device supply authoritative per-segment timings; it defaults to empty. An optional `strict_duplicate` flag changes duplicate handling as described below.

A fresh upload begins in `PROCESSING`. What happens next depends on the duplicate check. A candidate is a duplicate when another non-`REJECTED` activity of the same athlete exists with the same `idempotency_key`, **or** with the same `device_source` and a `started_at` within 120 seconds of the earlier activity's start and a `distance_m` within five percent of the earlier activity's distance (the five percent is measured against the earlier activity). By default the duplicate completes with HTTP 201 in `DUPLICATE` status, its `duplicate_of_id` pointing at the canonical candidate — the one with the earliest `created_at` — and no further processing: no segment sweep, no challenge accumulation, no heat map contribution. When `strict_duplicate` is true on the upload, the same detection instead rejects the request outright with `ERR_DUPLICATE_ACTIVITY` (HTTP 409). An upload whose payload violates referential or shape rules beyond ordinary field validation — an unusable `track_points` array, for instance — is parked in `REJECTED`.

When no duplicate is detected, the activity completes and the system runs four follow-on processes, in this order. First, route obfuscation against the owner's active zones, as described in §3.3. Second, the **segment match sweep**: for every `ACTIVE` segment with a `hazard_index` of zero whose `sport_type` matches the activity's effective category (the `corrected_sport_type` if one is set, otherwise the declared `sport_type`), a new effort is created. Category matching has three deliberate asymmetries: `RIDE` segments also match `EBikeRide` activities, `VIRTUAL_RIDE` and `VIRTUAL_RUN` activities match `RIDE` and `RUN` segments respectively, and `SWIM` matches only `SWIM`. An activity that has been auto-hidden never participates in sweeps. Third, challenge progress accumulation (§3.6). Fourth, heat map contribution for `RIDE` and `RUN` activities (§3.7).

Each matched effort is authored as follows. When the activity's `effort_hints` contains a hint whose `segment_id` equals the matched segment, the hint's `elapsed_time_s` and `elevation_gain_m` are used verbatim; otherwise the effort's `elapsed_time_s` defaults to the activity's whole `duration_s` and `elevation_gain_m` defaults to zero. Either way `distance_m` is copied from the segment's `distance_m` at match time, `elapsed_time_s` must be at least one second, and the effort begins with `flag_status` `ELIGIBLE` and no `exclusion_reason`. Each created effort increments the segment's `effort_count` by one. The effort's `avg_speed_kmh` is then computed as its `distance_m` divided by its `elapsed_time_s` and multiplied by 3.6, rounded half-up to two decimal places.

Immediately after creation, each new effort passes through the **speed and vehicle integrity check**. The check computes the minimum plausible elapsed time for the effort: the segment's `distance_m` multiplied by 3.6, divided by the maximum plausible speed for the activity's effective category, and then multiplied by that category's assist factor. The maximum speeds are 80 km/h for `RIDE`, 30 km/h for `RUN`, 10 km/h for `SWIM`, 45 km/h for `EBikeRide`, and 100 km/h for both `VIRTUAL_RIDE` and `VIRTUAL_RUN`. The assist factors are 0.8 for `RIDE`, 0.8 for `RUN`, 0.8 for `SWIM`, 0.7 for `EBikeRide`, and 0.9 for both virtual categories. The comparison is strict and performed in unrounded double precision: an elapsed time exactly equal to the threshold passes, while anything faster flags the effort as `SPEED_IMPOSSIBLE`. For example, on a 500-meter `RIDE` segment the threshold works out to exactly 18 seconds, so a 17-second effort is flagged while an 18-second effort passes; on a 500-meter virtual ride the threshold is 16.2 seconds, so 16 seconds is flagged while 17 passes. Separately, an effort whose effective category is `EBikeRide` matched onto a `RIDE` segment is flagged `VEHICLE_ASSISTED` — it is not speed-checked against the bicycle limits, though the e-bike maximum of 45 km/h governs the speed half of its own evaluation. In either flagging case the effort moves from `ELIGIBLE` to `FLAGGED` with the corresponding `exclusion_reason`, and the host activity's `flag_status` moves from `NONE` to `FLAGGED` if it was still `NONE`.

The owner (or a `PlatformAdmin` or `Moderator`) may later correct an activity's category by supplying a `corrected_sport_type`, which must be one of the six valid categories and must differ from the activity's current effective category — a correction equal to the existing category, or an invalid value, is rejected with `ERR_INCONSISTENT_REFERENCE`. A correction re-runs eligibility: every still-`ELIGIBLE` effort whose segment's `sport_type` no longer matches the corrected category is excluded with `exclusion_reason` `CATEGORY_MISMATCH`, the speed and vehicle check re-runs over the remaining `ELIGIBLE` efforts under the new category, rank snapshots are recomputed on affected segments, and affected heat map cells are recounted.

Every activity also carries a denormalized `elevation_gain_m`, computed as the sum of the `elevation_gain_m` of its efforts currently in `ELIGIBLE` status. Whenever an effort enters or leaves eligibility — flagging, clearing, upholding, category correction, segment retirement, account deletion — the host activity's `elevation_gain_m` is recomputed so the segment-total invariant holds.

### 3.5. Segments: Authoring, Activation, Leaderboards, and Retirement

Any athlete may author a segment, supplying a `creator_id`, a `name` of 3 to 80 characters, a `sport_type` of `RIDE`, `RUN`, or `SWIM`, the section corners `start_lat`, `start_lng`, `end_lat`, `end_lng`, a `distance_m` strictly greater than zero, a `city` label used for heat map grouping, and an optional `hazard_index` from 0 to 10 that defaults to 0. A new segment begins in `DRAFT` with `effort_count` zero. The `(name, sport_type)` pair must be unique among all segments not in `RETIRED` status — and because a retired segment keeps its name reserved, a `DRAFT` segment that recreates the name and sport of an `ACTIVE` *or* `RETIRED` segment is rejected with `ERR_UNIQUE_VIOLATION`.

Activation — by the segment's creator — moves a segment from `DRAFT` to `ACTIVE`, subject to two guards evaluated in the validation priority order of §2.5. First, safety: a segment with `hazard_index` greater than zero can never be activated; the attempt is rejected with `ERR_SAFETY_VIOLATION`, because hazardous segments must never appear on leaderboards. Second, overlap: activation is rejected with `ERR_SEGMENT_OVERLAP` when another `ACTIVE` segment of the same sport has both its start point within 50 meters of the candidate's start *and* its end point within 50 meters of the candidate's end — strictly within, so a 50-meter-exact distance on either endpoint is not an overlap. A successful activation runs a **retroactive match sweep**: every `COMPLETED`, non-auto-hidden activity whose effective category matches the segment's sport (with the same `EBikeRide`-onto-`RIDE` and virtual-onto-road accommodations as the upload sweep) receives an effort authored per the matching rules of §3.4, each new effort passes through the speed and vehicle check, and `effort_count` is updated accordingly.

A segment's **leaderboard** is the ordered list of its `ELIGIBLE` efforts, sorted by `elapsed_time_s` ascending with ties broken by the effort's `created_at` ascending — never by id. Each effort carries a `rank_snapshot`: its one-based position in that ordering, refreshed on every leaderboard-relevant mutation — new efforts, flag transitions, exclusion cascades. Free-tier readers see only the top ten rows plus their own rank; requesting a `limit` above ten is the subscription-gated read of §2.9. Efforts may also be browsed per segment with an optional `flag_status` filter, per athlete across segments, or through the flat effort list filtered by `activity_id`, `segment_id`, `athlete_id`, or `flag_status`.

Retirement — by the creator — moves a segment from `ACTIVE` to `RETIRED` and runs an exclusion cascade: every `ELIGIBLE` effort on the segment moves to `EXCLUDED` with `exclusion_reason` `SEGMENT_HAZARDOUS`, the `elevation_gain_m` of each affected host activity is recomputed, the contribution counts of affected heat map cells are recomputed, and the segment drops out of all future match sweeps. A `DRAFT` segment may also be retired directly (the discarded-draft path), which skips the exclusion cascade because no efforts exist but likewise removes the segment from future sweeps.

One cyclic edge exists: a `RETIRED` segment may return to `ACTIVE` — by its creator, through the same activation path — but only while its `effort_count` is exactly zero and its `hazard_index` is zero. Once any effort has ever been recorded against it, the segment can never be re-activated; the attempt is rejected with `ERR_INVALID_STATE`.

### 3.6. Flags, Moderation, Safety Scores, and Leaderboard Integrity

Leaderboard integrity has two dimensions that evolve in parallel on every activity: the lifecycle `status` (`PROCESSING`, `COMPLETED`, `DUPLICATE`, `REJECTED`) and the integrity `flag_status` (`NONE`, `FLAGGED`, `CLEARED`, `CONFIRMED`). An activity's `flag_status` begins at `NONE`.

Any athlete may flag an effort of another athlete's completed activity, supplying a `reporter_id`, a `reason` of `IMPOSSIBLE_TIME`, `VEHICLE_ASSISTED`, or `WRONG_CATEGORY`, and an optional `note` of at most 500 characters. Four preconditions guard flag creation: the target effort's activity must be `COMPLETED`; that activity's `flag_status` must not be `CONFIRMED`; the reporter must differ from the activity's owner — flagging one's own effort is rejected with `ERR_FLAG_SELF`; and no other `OPEN` flag may already exist on the same effort (a second one is rejected with `ERR_UNIQUE_VIOLATION`). A state violation on the first two conditions surfaces as `ERR_INVALID_STATE`. Creating the flag opens it (`OPEN`), moves the target effort — and every other `ELIGIBLE` effort of the same activity — to `FLAGGED` (community-flagged efforts carry no `exclusion_reason`; only auto-flagged ones do), and moves the host activity's `flag_status` from `NONE` to `FLAGGED`. Whenever an effort leaves `ELIGIBLE`, rank snapshots for the remaining eligible efforts on its segment are recomputed.

Flags are adjudicated by `Moderator`s (and `PlatformAdmin`s). Only an `OPEN` flag may be resolved; acting on a resolved flag is `ERR_INVALID_STATE`. **Upholding** a flag moves it to `UPHELD` and triggers the confirmation cascade: the effort moves from `FLAGGED` to `EXCLUDED` with `exclusion_reason` `FLAG_UPHELD`, the host activity's `flag_status` moves from `FLAGGED` to `CONFIRMED` (the first upheld flag on the activity is enough), the athlete's `safety_score` drops by 10 with a floor of zero, and rank snapshots plus the host activity's `elevation_gain_m` are recomputed. **Rejecting** a flag moves it to `REJECTED`; when the rejected flag was the last `OPEN` flag on its activity, the effort moves back from `FLAGGED` to `ELIGIBLE` with `exclusion_reason` cleared to null, the activity's `flag_status` moves from `FLAGGED` to `CLEARED`, the athlete's `safety_score` rises by 5 with a cap of 100, and rank snapshots are recomputed.

The `safety_score` starts at 100, loses 10 per upheld flag (never below zero), and gains 5 per rejected flag (never above 100). Its consequential threshold is 50: the moment an athlete's score falls below 50, every `COMPLETED` activity they own is marked `auto_hidden` true. Auto-hidden activities stop matching new segments, are excluded from public reads (non-owners receive `ERR_NOT_FOUND`), and are withdrawn from heat map contribution. Flags may be browsed per effort, individually, or through the flat flag list filtered by `effort_id`, `reporter_id`, or `status`.

### 3.7. Clubs, Memberships, Challenges, and Virtual Events

**Clubs.** An athlete founds a club by supplying an `owner_id`, a `name` of 3 to 60 characters that is globally unique among non-`ARCHIVED` clubs, a `sport_type` of `RIDE`, `RUN`, `SWIM`, or `MULTI`, and a `join_policy` of `OPEN` or `APPROVAL`. The club begins `ACTIVE`, and the founder automatically receives a membership with `role` `ADMIN` and `status` `ACTIVE`.

**Memberships.** Joining a club creates a membership for the supplied `athlete_id`. Under an `OPEN` policy the membership is immediately `ACTIVE`; under `APPROVAL` it parks in `PENDING` until an admin acts. An athlete who already holds a `PENDING` or `ACTIVE` membership in the club is rejected with `ERR_DUPLICATE_MEMBERSHIP`. Later joins carry `role` `MEMBER`. A club admin — meaning the caller holds an `ACTIVE` membership with `role` `ADMIN` in that same club — may approve a `PENDING` membership to `ACTIVE`, or remove a `PENDING` or `ACTIVE` membership to `REMOVED`; the club owner's own membership can never be removed. A member may also leave on their own, moving the membership from `ACTIVE` to `LEFT`. Both removal and leaving trigger the same withdrawal cascade: the athlete's `JOINED` participations in that club's challenges move to `WITHDRAWN`, and their `GOING` RSVPs in that club's events move to `DECLINED` with each host event's `rsvp_count` decremented by one.

**Archiving** a club — by its owner, or by the system when the owner is deleted — moves it from `ACTIVE` to `ARCHIVED` and cascades: all `PENDING` or `ACTIVE` memberships move to `REMOVED`; all `DRAFT` or `ACTIVE` challenges of the club move to `CANCELLED`; and all `PUBLISHED` events of the club move to `CANCELLED`, with their `rsvp_count` retained for audit. Once a club is archived, club-scoped writes — joining, creating, starting, or cancelling challenges, and creating or cancelling events — are rejected with `ERR_CLUB_ARCHIVED`.

**Challenges.** A club admin creates a challenge with a `name` of 3 to 80 characters, a `goal_type` of `DISTANCE_M`, `ELEVATION_M`, or `ACTIVE_DAYS`, a `goal_target` strictly greater than zero, an inclusive window from `start_date` to `end_date` (both YYYY-MM-DD, with `end_date` no earlier than `start_date` — otherwise `ERR_WINDOW_VIOLATION`), and a `join_mode` of `OPEN` or `INVITE`. A new challenge is `DRAFT`. Starting it — a club-admin action requiring the club still be `ACTIVE` and the logical clock's date be no later than `end_date` (a late start is `ERR_WINDOW_VIOLATION`) — moves it to `ACTIVE`. A challenge whose end date passes closes lazily from `ACTIVE` to `CLOSED` on the next read. Cancellation — by a club admin, or by the club-archive cascade — moves a `DRAFT` or `ACTIVE` challenge to `CANCELLED` and withdraws every `JOINED` participation.

**Participation.** Joining works differently by mode: under `OPEN`, any `ACTIVE` club member may join; under `INVITE`, membership is restricted to members an admin has invited, with the invitation modeled as the admin pre-joining that athlete. Joining a challenge that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`; an athlete who already holds a `JOINED` or `COMPLETED` participation is rejected with `ERR_ALREADY_JOINED`. A participation begins `JOINED` with `progress_value` zero and a server-stamped `joined_at`.

Progress accumulates whenever one of the athlete's activities completes. For each `JOINED` participation whose challenge window covers the activity's `started_at` UTC date, the activity contributes if it is `COMPLETED`, not auto-hidden, and its `flag_status` is `NONE` or `CLEARED`; each activity contributes at most once per challenge. The contribution depends on the goal type: for `DISTANCE_M` the activity's `distance_m` is added; for `ELEVATION_M` the host activity's `elevation_gain_m` is added; for `ACTIVE_DAYS` the count of distinct UTC calendar dates across contributing activities is taken. The moment `progress_value` reaches `goal_target` — the boundary is inclusive — the participation moves automatically from `JOINED` to `COMPLETED`. Athletes who join late are subject to the late-join baseline: the retroactive sweep at join time counts only qualifying activities whose completion instant is strictly after `joined_at`; anything completed before the join contributes zero, so two athletes with identical histories but different join instants finish with different progress. A member may withdraw at any time, moving their participation from `JOINED` to `WITHDRAWN`; membership removal, challenge cancellation, and account deletion force the same transition.

**Virtual events.** A club admin creates an event with a `name` of 3 to 80 characters, a `segment_id`, a `scheduled_at` instant that must be strictly in the future relative to the logical clock (otherwise `ERR_WINDOW_VIOLATION`), and a `capacity` between 1 and 500. The referenced segment must be `ACTIVE` with a `hazard_index` of zero; pointing an event at a retired, draft, or hazardous segment is rejected with `ERR_INCONSISTENT_REFERENCE`. Each event occupies a half-open one-hour window from `scheduled_at` to `scheduled_at` plus 3600 seconds, and creating an event whose window intersects any other `PUBLISHED` event of the same club is rejected with `ERR_EVENT_TIME_OVERLAP` — back-to-back scheduling, where the new start equals an existing event's end, is allowed because the intervals are half-open. A new event is `PUBLISHED` with `rsvp_count` zero. Events complete lazily: once the logical clock passes `scheduled_at`, the next read observes the event as `COMPLETED`. A club admin may cancel a `PUBLISHED` event, and the club-archive cascade cancels all of the club's published events.

**RSVPs.** An `ACTIVE` club member responds to an event by creating an RSVP for an `athlete_id`, which begins `GOING` and increments the event's `rsvp_count` by one. Creating or rejoining is refused once the event is full — `rsvp_count` equal to `capacity` — with `ERR_CAPACITY_EXCEEDED`; refused after `scheduled_at` has passed or once the event has left `PUBLISHED`, with `ERR_WINDOW_VIOLATION` or `ERR_INVALID_STATE` respectively; and refused when the athlete already holds an RSVP, with `ERR_UNIQUE_VIOLATION`. The responder may later decline, moving their RSVP from `GOING` to `DECLINED` and decrementing `rsvp_count` by one. Declining is cyclic: a `DECLINED` RSVP may return to `GOING` — only by its owner, only while the event is still `PUBLISHED`, and only while the event is under capacity — incrementing `rsvp_count` again. Membership removal and account deletion force RSVPs to `DECLINED` through the same decrement.

### 3.8. Safety Beacon, Heat Map, and Route Planning

**Safety contacts and beacon.** An athlete maintains safety contacts — each a `contact_email` unique per athlete (duplicates are `ERR_UNIQUE_VIOLATION`) and a `label` of at most 40 characters. Starting a beacon session is a subscription-gated safety feature with three guards: the athlete must hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_REQUIRED` otherwise), must have at least one safety contact (`ERR_SAFETY_VIOLATION` otherwise), and must not already have a `LIVE` session (a second is `ERR_UNIQUE_VIOLATION`). A new session is `LIVE`, stamped with the logical clock's current instant as `started_at`, and `last_location` null until the first ping. While `LIVE`, the athlete may ping the session with a `lat` and `lng`, which replaces `last_location`; pinging or stopping a session that is not `LIVE` is `ERR_INVALID_STATE`. Stopping — by the athlete, or by the account-deletion cascade — moves the session from `LIVE` to `ENDED`.

**Heat map.** The public heat map aggregates completed activities into cells keyed by `city` and `sport_type`. Only `RIDE` and `RUN` activities contribute. A contribution counts one toward the cell for each activity that is `COMPLETED`, not auto-hidden, has `flag_status` `NONE` or `CLEARED`, and belongs to an athlete whose `heatmap_opt_out` is false. The cell's city comes from any matched segment's `city`, defaulting to `UNMAPPED` when the activity matched no segment. Counts are recomputed exactly — incremented on new uploads, decremented on exclusion cascades (flag upheld, account deletion, auto-hide), on segment retirement, and in full when an athlete toggles `heatmap_opt_out` from false to true, which withdraws every existing contribution immediately. A cell surfaces publicly only once its `contribution_count` reaches 3; the boundary is inclusive, and the heat map endpoint may be filtered by `city` or `sport_type`.

**Route planning.** An athlete creates a route plan with a `name` of 1 to 80 characters, an ordered `waypoints` array of 2 to 50 `{lat, lng}` points, a `distance_m` strictly greater than zero, and a `week_start` — the YYYY-MM-DD of the Monday of the training week the plan counts against. Free-tier athletes are capped at three plans sharing the same `week_start`: creating the third plan succeeds, and the fourth is rejected with `ERR_FREE_TIER_ROUTE_CAP` unless the athlete holds an active subscription (§2.9). Each plan computes an `estimated_load_score` at creation: first sum the `distance_m` of the athlete's `COMPLETED` activities — any sport — whose `started_at` falls in the trailing 28 days before `week_start` (zero when there are none); then take the plan's `distance_m` divided by 1000, add the recent-distance sum divided by 2000; and, when the recent-distance sum is greater than zero and the plan's distance exceeds one and a half times that sum, add a further 25 as a spike bonus. The result is rounded half-up to one decimal place. The evaluation order is pinned exactly as stated — recent distance first, then the base sum, then the conditional bonus — so the bonus never feeds back into the base.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, including state transitions and action endpoints, return `200 OK`. The table below is a summary only; request payloads, response shapes, and side effects are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/athletes` | Register an athlete | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}` | Get an athlete | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/athletes/{id}/export` | Export the athlete's complete data | Athlete, PlatformAdmin |
| DELETE | `/v1/athletes/{id}` | Delete (erase) the athlete account | Athlete |
| POST | `/v1/athletes/{id}/subscriptions` | Create a subscription for an athlete | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/subscriptions` | List subscriptions of an athlete | Athlete, PlatformAdmin |
| GET | `/v1/subscriptions/{id}` | Get a subscription | Athlete, PlatformAdmin |
| POST | `/v1/subscriptions/{id}/cancel` | Cancel an active subscription | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/privacy_zones` | Create the athlete's privacy zone | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/privacy_zones` | List the athlete's privacy zones (0 or 1) | Athlete, PlatformAdmin |
| GET | `/v1/privacy-zones/{id}` | Get a privacy zone | Athlete, PlatformAdmin |
| PUT | `/v1/privacy-zones/{id}` | Update zone geometry (OCC on the owning athlete) | Athlete, PlatformAdmin |
| POST | `/v1/privacy-zones/{id}/disable` | Disable the zone | Athlete, PlatformAdmin |
| POST | `/v1/privacy-zones/{id}/enable` | Re-enable the zone | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/activities` | Upload an activity from a device or application | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/activities` | List activities of an athlete | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/activities` | Flat activity list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/activities/{id}` | Get an activity (non-owners see the obfuscated route) | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/activities/{id}/correct_category` | Correct the sport category of an activity | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/segments` | Create a segment (starts DRAFT) | Athlete, PlatformAdmin |
| GET | `/v1/segments/{id}` | Get a segment | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/segments` | List segments | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/segments/{id}/activate` | Activate a DRAFT (or zero-effort RETIRED) segment | Athlete, PlatformAdmin |
| POST | `/v1/segments/{id}/retire` | Retire a segment | Athlete, PlatformAdmin |
| GET | `/v1/segments/{id}/efforts` | List efforts of a segment | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/segments/{id}/leaderboard` | Leaderboard of ELIGIBLE efforts (free tier: top 10 + own rank) | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/athletes/{id}/efforts` | List efforts of an athlete across segments | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/efforts` | Flat effort list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/efforts/{id}` | Get a single effort | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/flags` | Flat flag list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/efforts/{id}/flags` | Flag an effort | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/efforts/{id}/flags` | List flags on an effort | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/flags/{id}` | Get a flag | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/flags/{id}/uphold` | Moderator upholds a flag | Moderator, PlatformAdmin |
| POST | `/v1/flags/{id}/reject` | Moderator rejects a flag | Moderator, PlatformAdmin |
| POST | `/v1/clubs` | Create a club; founder joins as ACTIVE ADMIN | Athlete, PlatformAdmin |
| GET | `/v1/clubs/{id}` | Get a club | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/clubs` | List clubs | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/challenges` | Flat challenge list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/events` | Flat event list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/clubs/{id}/archive` | Archive a club | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/memberships` | Join a club | Athlete, PlatformAdmin |
| GET | `/v1/clubs/{id}/memberships` | List memberships of a club | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/memberships` | Flat membership list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/memberships/{id}` | Get a membership | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/clubs/{id}/memberships/{id}/approve` | Approve a PENDING membership (club admin) | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/memberships/{id}/remove` | Remove a member (club admin; cannot remove the owner) | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/memberships/{id}/leave` | Leave a club (self) | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/challenges` | Create a challenge (club admin) | Athlete, PlatformAdmin |
| GET | `/v1/clubs/{id}/challenges` | List challenges of a club | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/challenges/{id}` | Get a challenge | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/clubs/{id}/challenges/{id}/start` | Start a DRAFT challenge (club admin) | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/challenges/{id}/cancel` | Cancel a challenge (club admin) | Athlete, PlatformAdmin |
| POST | `/v1/challenges/{id}/participations` | Join a challenge | Athlete, PlatformAdmin |
| GET | `/v1/challenges/{id}/participations` | List participations of a challenge | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/participations` | Flat participation list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/participations/{id}` | Get a participation | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/challenges/{id}/participations/{id}/withdraw` | Withdraw from a challenge (self) | Athlete, PlatformAdmin |
| POST | `/v1/clubs/{id}/events` | Create a virtual event on a segment (club admin) | Athlete, PlatformAdmin |
| GET | `/v1/clubs/{id}/events` | List events of a club | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/events/{id}` | Get an event | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/clubs/{id}/events/{id}/cancel` | Cancel an event (club admin) | Athlete, PlatformAdmin |
| POST | `/v1/events/{id}/rsvps` | RSVP to an event (capacity-gated) | Athlete, PlatformAdmin |
| GET | `/v1/events/{id}/rsvps` | List RSVPs of an event | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/rsvps` | Flat RSVP list with foreign-key filters | Athlete, PlatformAdmin, Moderator |
| GET | `/v1/rsvps/{id}` | Get an RSVP | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/events/{id}/rsvps/{id}/decline` | Decline an RSVP (self) | Athlete, PlatformAdmin |
| POST | `/v1/events/{id}/rsvps/{id}/rejoin` | Rejoin a DECLINED RSVP (self, capacity-gated) | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/safety_contacts` | Add a safety contact | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/safety_contacts` | List safety contacts | Athlete, PlatformAdmin |
| GET | `/v1/safety_contacts/{id}` | Get a safety contact | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/beacon_sessions` | Start a beacon sharing session | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/beacon_sessions` | List beacon sessions of an athlete | Athlete, PlatformAdmin |
| GET | `/v1/beacon_sessions/{id}` | Get a beacon session | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/beacon_sessions/{id}/ping` | Update the live location of a beacon session | Athlete, PlatformAdmin |
| POST | `/v1/athletes/{id}/beacon_sessions/{id}/stop` | Stop a beacon session (self) | Athlete, PlatformAdmin |
| GET | `/v1/heatmap` | Heat map aggregation (cells at or above the minimum count) | Athlete, PlatformAdmin, Moderator |
| POST | `/v1/athletes/{id}/route_plans` | Create a route plan (free-tier weekly cap; computes load score) | Athlete, PlatformAdmin |
| GET | `/v1/athletes/{id}/route_plans` | List route plans of an athlete | Athlete, PlatformAdmin |
| GET | `/v1/route_plans/{id}` | Get a route plan | Athlete, PlatformAdmin |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_ACTIVITY` | 409 |
| `ERR_UNIQUE_VIOLATION` | 409 |
| `ERR_SAFETY_VIOLATION` | 422 |
| `ERR_WINDOW_VIOLATION` | 422 |
| `ERR_SUBSCRIPTION_REQUIRED` | 402 |
| `ERR_FREE_TIER_ROUTE_CAP` | 402 |
| `ERR_INCONSISTENT_REFERENCE` | 422 |
| `ERR_FLAG_SELF` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_CLUB_ARCHIVED` | 409 |
| `ERR_SEGMENT_OVERLAP` | 409 |
| `ERR_EVENT_TIME_OVERLAP` | 409 |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 |
| `ERR_ALREADY_JOINED` | 409 |
