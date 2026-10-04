# Family Safety Network API — Product Requirements Document

## 1. Introduction

Family Location Sharing, Place Alerts & Crash Detection is a circle-based safety coordination system that lets families share real-time location, define geofenced places, and react to crash events on the road. The product must balance two opposing pressures that live in the same data flow: the safety promise ("we will notice when something goes wrong") and the privacy promise ("each member controls exactly what is shared, with whom, and for how long"). Every location read, every place alert, and every crash escalation is gated by a per-member privacy posture, a per-circle subscription entitlement, and — for minors — a parental consent lattice whose failure modes must be explicit and audit-traceable.

The system described here models the full lifecycle: a circle is created around an owner, members are invited and consent to share, devices stream location fixes whose cadence adapts to battery and motion, places produce arrival and departure alerts that respect dwell-time buckets and accuracy tolerances, and driving trips roll up into distance, speed, and phone-use metrics that feed a driver score. On top of this base, crash detection fans out a transitive cascade — CrashEvent to WellnessCheck to EmergencyDispatch — that consumes roadside-assistance budget from the circle's subscription and that must be compensatable if the event turns out to be a false alarm. Consent revocation, minor aging, disclosure version bumps, and subscription posture changes all retroactively re-filter what the circle can see and what it is allowed to act on.

This document is the contract between the product organization and the engineering team that will build the API. It specifies the resource model, the state machines that govern lifecycle transitions, the calculation rules that turn raw sensor data into safety signals, and the error catalogue that defines how the system refuses work. Implementation decisions (storage, transport, push-delivery) are out of scope; behaviour on the wire is not.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Subsections 2.4 through 2.10 cover the cross-cutting concerns that recur across every workflow in §3 — read them once and they apply everywhere.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user is acting. The system recognizes exactly five role names: `Owner`, `Admin`, `Member`, `Minor`, and `System`. A request that omits either header, or that carries a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four member-facing roles — `Owner`, `Admin`, `Member`, and `Minor` — are entity-backed by the `Member` resource. When `X-User-Role` is `Owner`, `Admin`, `Member`, or `Minor`, the `X-User-ID` header carries the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (a fix's `member_id`, a crash's `member_id`, a consent record's `granted_by_member_id`, and so on) compare the resource's foreign-key field to `X-User-ID`. For `Owner` and `Admin` the actor must additionally be a `Member` of the same circle as the resource being acted on, with `role` equal to `OWNER` or `ADMIN` respectively.

The `System` role is opaque. When `X-User-Role` is `System`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on resources it writes, but it does not compare it to any entity's `id`, and `System` is not a member of any circle.

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

All list endpoints accept the `limit` and `offset` query parameters. The `limit` parameter controls the maximum number of items returned in a single page; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter controls how many items to skip from the head of the result set; it defaults to 0. Unless otherwise noted, list endpoints sort by `created_at` ascending. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every entity in this system carries the standard system-managed fields unless explicitly stated otherwise. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation. The `version` is an integer that increments on every mutation to the resource — including mutations driven by cascades from elsewhere in the system (for example, when a circle's posture transition forces a member's `consent_state` to change, the member's `version` also advances). All twelve top-level entity kinds in this domain — Circle, Member, Place, LocationFix, PlaceAlert, TripReport, CrashEvent, WellnessCheck, EmergencyDispatch, SubscriptionEvent, ConsentRecord, and ComplianceHold — carry `id`, `created_at`, `updated_at`, and `version`; none omit `updated_at` or `version`.

### 2.5. Nested Resource Retrieval

Nested paths are validated strictly left to right. A request addressed at `/api/circles/{circle_id}/members/{member_id}/fixes/{fix_id}` resolves the `circle_id` first, then the `member_id` (which must be a member of that circle), then the `fix_id` (which must belong to that member). The first identifier that fails to resolve — or that resolves but belongs to a different parent than the path implies — produces `ERR_NOT_FOUND` (HTTP 404), and no further identifiers are consulted. The same rule applies to every path parameter the scaffold names: `place_id` resolves within the circle, `crash_event_id` resolves within the member, `dispatch_id` resolves within the crash event, `check_id` resolves within the crash event's wellness check, and `hold_id` resolves within the circle.

### 2.6. Circle Posture as a Derived Gate

A circle's `circle_posture` is not stored as a free-standing enum; it is recomputed from two inputs on every mutation of either: the circle's `subscription_status` and the set of `ComplianceHold` rows whose `hold_status` is `OPEN` for that circle. The posture takes the value `RESTRICTED` when the subscription is `PAST_DUE` or at least one open compliance hold exists; it takes the value `FROZEN` when the subscription is `SUSPENDED` or `CANCELLED`; otherwise it is `OPEN`. Because posture is derived, any endpoint that mutates `subscription_status` or opens/closes a `ComplianceHold` triggers the recomputation immediately, increments the circle's `version`, and refreshes `updated_at`. Posture gates behaviour throughout §3: while the posture is `RESTRICTED`, roadside-assistance consumption and crash-escalation attempts are rejected with `ERR_CIRCLE_RESTRICTED`; while the posture is `FROZEN`, every mutation under the circle other than subscription reactivation or compliance-hold resolution is rejected with `ERR_CIRCLE_FROZEN`, and location-sharing reads to non-`Owner` members are refused with the same code.

### 2.7. Optimistic Concurrency Control

Two write endpoints are protected by optimistic concurrency control, and they are the only ones. A request to change a circle's subscription tier must carry `expected_circle_version` matching the circle's current `version`; a request to patch a member's `privacy_mode` must carry `expected_member_version` matching the member's current `version`. In both cases the field is non-optional. If the supplied value does not match the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This rule does not depend on requests arriving concurrently: a client acting on a stale read of the circle's or member's `version` is rejected regardless of when the prior write occurred. Endpoints not named here do not accept a version field at all.

### 2.8. The Assistance-Unit and Identity-Credit Ledgers

Each circle tracks two consumable budgets whose semantics are bound to its subscription tier. The `assistance_units_balance` replenishes at each billing anchor to a per-window allotment that depends on the tier: 0 units on `FREE`, 2 on `PLUS`, and 4 on `PROTECT`. Crash escalations and manual roadside-assistance requests each consume one unit. The balance must never go negative under normal circumstances; as a safety valve, a `PROTECT` circle may overdraw to exactly -1 within a single billing window, but `FREE` and `PLUS` circles may not. Attempting to consume a unit when the balance is exhausted for the tier (0 for `FREE`/`PLUS`, -1 already reached for `PROTECT`) is rejected with `ERR_ASSISTANCE_UNITS_EXHAUSTED` (HTTP 402). A companion compensating invariant governs crash escalations that are later retracted: an escalation that is followed by a false-alarm retraction restores exactly one unit to the circle, leaving the balance identical to what it was before the escalation — but only if the retraction happens before the dispatch reaches `DISPATCHED`; once a dispatch has been staged, the unit is burned with the responder and is not returned.

The `identity_protection_credits` budget is `PROTECT`-only: it starts each billing window at 1 for a `PROTECT` circle and is 0 on every other tier. Consumption requires the balance to be strictly positive; a request that would drive the balance below zero is rejected with `ERR_NO_IDENTITY_CREDIT` (HTTP 402), does not append a `SubscriptionEvent`, and leaves the balance unchanged. Across a single billing window the invariant `identity_protection_credits == start_of_window - consumed_this_window` holds at every observable point, where `start_of_window` is 1 on `PROTECT` and 0 otherwise and `consumed_this_window` counts the `IDENTITY_CREDIT_CONSUME` events whose `billing_period_index` matches the current window.

### 2.9. Numerical Precision and Rounding

Locations are compared in metres. Haversine distances are computed to one decimal place (0.1 m) using an earth radius of 6,371,000 metres, and geofence membership comparisons are exact: a fix whose distance from the place centre is less than or equal to the effective radius is inside, including the boundary. Trip distances are summed in integer metres after each per-segment leg has been rounded half-up to a whole metre — the rounding happens per segment, never once on the polyline total. Crash-severity comparisons evaluate `delta_v` at two decimal places. The adaptive sampling interval is an integer number of seconds produced by applying round-half-up exactly once at the final step of the calculation (no nested rounding anywhere earlier in the chain). Driver scores are integers in the range 0 to 100.

### 2.10. The Server Logical Clock

The server maintains a logical clock that is independent of wall-clock time. At boot, the logical clock reads `2026-09-01T00:00:00Z`; it never falls back to the host's wall clock. The clock can be advanced only through a `System`-only test-driving capability that accepts a target `current_utc` instant; setting the clock also triggers any daily sweeps that have come due (the age sweep, the retention sweep, and the wellness-deadline sweep) so that the observable state after the call reflects the new logical time. All timestamps emitted by the server — `created_at`, `updated_at`, `detected_at`, `staged_at`, `effective_at`, `deadline_at`, and the response envelope's `api_request_timestamp` — are read from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Forming a Circle and Its Subscription Lifecycle

A family safety network begins when a user creates a circle. The creation call carries the circle's `name`, the chosen `subscription_tier` (one of `FREE`, `PLUS`, or `PROTECT`), the `billing_anchor_day` — an integer between 1 and 28 on which the rolling 30-day billing window is anchored — and the owner's identifying details: `owner_display_name`, `owner_birthdate`, and `owner_email`. The server creates the circle with `subscription_status` set to `TRIALING` and `circle_posture` set to `OPEN`. It simultaneously creates the first `Member` row, assigns that member the `OWNER` role, records their consent as self-granted with `scope` `FULL`, and points the circle's `owner_member_id` at the new member. The circle's tier-derived budgets are initialized at this moment: `assistance_units_balance` starts at 0 for `FREE`, 2 for `PLUS`, or 4 for `PROTECT`; `identity_protection_credits` starts at 1 for `PROTECT` and 0 on every other tier; `history_retention_days` starts at 7 for `FREE`, 30 for `PLUS`, or 60 for `PROTECT`. A circle may have at most one `OWNER` at any time.

Tier changes and posture changes are owner-driven from this point on. An owner may change the circle's tier by naming the `to_tier` and presenting the `expected_circle_version` last observed; a mismatch against the circle's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful change appends a `SubscriptionEvent` of kind `TIER_CHANGE` recording the `from_tier`, the `to_tier`, and the `effective_at` instant, recomputes `history_retention_days` for the new tier, sets `identity_protection_credits` to 1 if the circle is entering `PROTECT` or resets it to 0 if the circle is leaving `PROTECT`, and replenishes `assistance_units_balance` only if the tier change happens to cross a billing anchor — otherwise the unit balance is unchanged. The change increments the circle's `version`.

Two operator-only simulations move the subscription through its lifecycle. Simulating a failed renewal payment moves `subscription_status` from `ACTIVE` to `PAST_DUE`, appends a `PAYMENT_FAILED` event, recomputes posture to `RESTRICTED`, and increments the circle's `version`. Simulating a suspend moves `subscription_status` to `SUSPENDED`, appends a `SUSPENDED` event, recomputes posture to `FROZEN`, and increments `version`. The owner can later reverse the suspend by reactivating the subscription: `subscription_status` returns to `ACTIVE`, a `REACTIVATED` event is appended, posture is recomputed — landing on `RESTRICTED` instead of `OPEN` if any compliance hold is still open — and the circle's `version` increments again. When the subscription returns to `ACTIVE` or `TRIALING` and no open compliance hold remains, the circle's posture settles back to `OPEN`, and any place alerts that were frozen mid-window in `PENDING_DWELL` resume evaluation against their original `window_open_fix_id` without resetting the dwell window.

Every subscription mutation — tier change, `RENEWAL`, payment failure, suspension, reactivation, cancellation, `ASSISTANCE_GRANT` events that replenish units, and the consumption of assistance units and identity credits — is recorded as a row in the circle's subscription ledger. Each ledger row carries its `event_kind`, the `from_tier` and `to_tier` where applicable, the `effective_at` instant, the signed `units_delta` applied to whichever balance the event mutates, and the `billing_period_index` (a monotonic counter starting at 0 for the creation window and incrementing at each anchor roll).

### 3.2. Membership, Roles, and the Consent Lattice

Once a circle exists, the owner (or an admin) invites further members by supplying the invitee's `display_name`, `birthdate`, and `email`. The server computes the invitee's `age_years` as the floor of the difference between the current logical-clock date and the `birthdate`, expressed in units of 365.25 days. If that age is less than 16 the new member is assigned the `MINOR` role; otherwise they are assigned `MEMBER`. Newly invited members always start with `consent_state` `PENDING`, and the invite increments the circle's `version`. Adults whose consent is granted on join transition directly to `GRANTED`; minors remain `PENDING` until a parent or guardian grants on their behalf.

Consent is its own lifecycle with four values — `PENDING`, `GRANTED`, `REVOKED`, and `EXPIRED` — and an explicit actor matrix. Granting consent on a target member accepts a `scope` (one of `LOCATION`, `DRIVING`, `CRASH`, or `FULL`; `FULL` implies every narrower scope is also granted) and a `monetization_opt_in` boolean (defaulting to `false`) that records whether the member agrees to anonymized location-data monetization under the circle's data-sharing disclosure. For an adult target, the actor must be the target themselves (a self-grant) or the circle's `OWNER`. For a `MINOR` target, the actor must be the `OWNER` or an `ADMIN` of the circle, and the actor must not be the target — a minor may not self-grant. A successful grant appends a `ConsentRecord` with `consent_action` `GRANT`, flips the member's `consent_state` to `GRANTED`, recomputes the member's `effective_sample_interval_seconds`, and increments the member's `version`. A member whose consent has been revoked may re-enter `GRANTED` via the same call and the same actor rules. A member whose consent has expired — see §3.8 — may also re-enter `GRANTED`, but only with a `FULL` scope: a partial re-grant from `EXPIRED` is rejected.

Revoking consent is subject to a stricter rule for minors. For an adult member the actor may be the member themselves, an `ADMIN`, or the `OWNER`. For a `MINOR` target, only the `OWNER` may revoke; an attempt by an `ADMIN`, by another member, or by the minor themselves is rejected with `ERR_MINOR_CONSENT_LOCKED` (HTTP 403). A successful revocation appends a `ConsentRecord` with `consent_action` `REVOKE`, flips the member's `consent_state` to `REVOKED`, increments the member's `version`, and triggers three compensations across the rest of the system: every location fix the member's device subsequently submits is recorded as `REJECTED_CONSENT` rather than accepted; every `OPEN` crash event on that member transitions to `FALSE_ALARM`; and every wellness check still `SENT` for that member is `CANCELLED`. The same revocation abandons any open trip the member had been driving.

Role changes within the circle are owner-driven. Promoting a `MEMBER` to `ADMIN` requires that the target's `consent_state` is `GRANTED` and that the circle's posture is not `FROZEN`; a successful promotion sets the target's `role` to `ADMIN` and increments the member's `version`. Demoting an `ADMIN` back to `MEMBER` has no preconditions beyond the circle being writable, and likewise increments the member's `version`. Promoting a `MINOR` to `ADMIN` is rejected with `ERR_ROLE_INCOMPATIBLE`. Ownership transfer is the most consequential role change: the owner names a `target_member_id`, the target's `consent_state` must be `GRANTED`, and the target's role must not be `MINOR` — violations are rejected with `ERR_ROLE_INCOMPATIBLE`. On a successful transfer the prior `OWNER` is demoted to `ADMIN`, the target's role becomes `OWNER`, the circle's `owner_member_id` is updated to the target, and the circle's `version` increments. A circle always has exactly one `OWNER`.

### 3.3. Privacy Modes and the Parent-Teen Tension Flag

Each member's `privacy_mode` is one of `PRECISE`, `BLURRED`, or `HIDDEN`, defaulting to `PRECISE` at join. `PRECISE` shares the member's exact coordinates with the circle. `BLURRED` shares a jittered centroid within a 1.6 km radius — presence is revealed, but coordinates are not. `HIDDEN` suppresses location sharing entirely.

Changing `privacy_mode` is governed by an anti-coercion rule and a tension flag. The mutation request carries the new `privacy_mode` and the `expected_member_version` last observed; a stale `expected_member_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Moving from `PRECISE` to `BLURRED` may be performed by the owner, an admin, or the member themselves; if the target is a `MINOR` and the actor is not the target, the change sets the member's `tension_flag` to `true`. Moving from either `PRECISE` or `BLURRED` to `HIDDEN` may also be performed by the owner, an admin, or the member themselves, but it requires the target's `consent_state` to be `GRANTED` — attempting to apply `HIDDEN` while the target is `REVOKED` or `EXPIRED` is rejected with `ERR_CONSENT_NOT_GRANTED` — and likewise raises `tension_flag` when the target is a `MINOR` and the actor is not the target. Open crash events on the member are not interrupted by a switch to `HIDDEN` — safety overrides privacy for an in-flight emergency — but subsequent place alerts confirmed under `HIDDEN` are not visible to the owner. Moving from `HIDDEN` back to `PRECISE` is the strictest transition: only the member themselves may perform it, by presenting an `X-User-ID` that equals the target `member_id`. Any other actor attempting to lift `HIDDEN` to `PRECISE` is rejected with `ERR_PRIVACY_SELF_ONLY` (HTTP 403). A successful lift to `PRECISE` also clears the `tension_flag`. Every successful `privacy_mode` mutation increments the member's `version`, and future place-alert confirmations on that member recompute `visible_to_owner` from the new mode at confirmation time (it is `true` under `PRECISE` or `BLURRED` and `false` under `HIDDEN`).

The `tension_flag` is the system's record that a parent-imposed privacy override on a minor is being contested. It is set when an `OWNER` or `ADMIN` changes a `MINOR`'s `privacy_mode` away from `PRECISE` (or into `HIDDEN`) without the minor's own action. It is cleared in exactly two ways: the minor lifts their own `HIDDEN` back to `PRECISE`, or the minor ages out of the `MINOR` role (see §3.9). When a member's role is promoted from `MINOR` to `MEMBER` on their 16th birthday, the `tension_flag` is cleared and the parent-imposed override lock is released, but the `privacy_mode` itself is preserved as-is.

### 3.4. Location Ingestion and the Adaptive Sample Interval

A member's device streams location fixes to the system. Each fix carries a client-stamped `recorded_at`, a `lat` between -90 and 90, a `lng` between -180 and 180, an `accuracy_m` strictly greater than 0, a `speed_mps` greater than or equal to 0, a `battery_pct` between 0 and 100, a `phone_in_use` boolean indicating active foreground phone interaction at capture, and a `motion_context` of `STILL`, `WALKING`, `DRIVING`, or `UNKNOWN`. The server validates that the `recorded_at` is within 300 seconds, in either direction, of its own logical clock; a skew beyond that, a non-positive `accuracy_m`, a negative `speed_mps`, a `battery_pct` outside the 0-to-100 range, or an unrecognized `motion_context` is rejected with `ERR_FIX_CLOCK_SKEW` (HTTP 422). Ingestion requires the member's `consent_state` to be `GRANTED`; a fix submitted while consent is `REVOKED` or `EXPIRED` is recorded but with `fix_status` set to `REJECTED_CONSENT` rather than accepted.

Each accepted fix updates three things on the member row: the `last_known_fix_id` points at the new fix, the `current_battery_pct` is overwritten with the fix's `battery_pct`, and the member's `effective_sample_interval_seconds` is recomputed. The fix's `fix_status` is one of `ACCEPTED`, `REJECTED_ACCURACY`, `REJECTED_STALE`, `REJECTED_CONSENT`, or `RETIRED`.

The adaptive sample interval blends four inputs: the member's `sampling_profile` (`HIGH`, `BALANCED`, or `SAVER`, defaulting to `BALANCED`), the fix's `motion_context`, the fix's `battery_pct`, and the circle's `subscription_tier`. The calculation proceeds in a pinned order with no nested rounding. First, the base seconds are chosen from the profile: 15 seconds for `HIGH`, 60 for `BALANCED`, 300 for `SAVER`. Second, the base is multiplied by a motion modifier: a quarter when the fix reports `DRIVING`, half when `WALKING`, doubled when `STILL`, and unchanged when `UNKNOWN`. Third, that intermediate product is multiplied by a battery modifier: doubled when the battery is at or below 15 percent, multiplied by 1.5 when the battery is between 16 and 30 percent inclusive, and unchanged above 30 percent. Fourth, the result is floored at a per-tier minimum: 60 seconds on `FREE`, 30 seconds on `PLUS`, 15 seconds on `PROTECT` — meaning the interval is the larger of the raw product and the tier floor. Fifth and finally, the value is rounded half-up to an integer number of seconds and clamped to the inclusive range from 15 to 900. The same recompute runs on every accepted fix, on every `sampling_profile` change, and on every tier change of the owning circle.

### 3.5. Places, Geofence Membership, and Arrival/Departure Alerts

A place is a geofenced landmark owned by the circle. Its `label` is human-facing — "Home", "School". The geofence is a `center_lat` between -90 and 90, a `center_lng` between -180 and 180, and a `radius_m` between 50 and 5,000 metres inclusive. The `accuracy_floor_m`, between 10 and 500 inclusive and defaulting to 100, bounds how much of a fix's reported accuracy may contribute to the geofence's effective radius. The `notify_on_arrive` and `notify_on_depart` booleans default to `true`. The `dwell_bucket_seconds` — one of 60, 180, or 300, defaulting to 180 — is the minimum dwell a member must accumulate inside the geofence before an arrival is confirmed. A place's `place_status` is `ACTIVE` or `ARCHIVED`. Any violation of these ranges on create or update is rejected with `ERR_PLACE_CONFIG_INVALID` (HTTP 422).

Two places in the same circle may not substantially overlap. When a new place is created or an existing place's `radius_m` or centre is updated, the server compares the candidate against every other `ACTIVE` place in the circle; if the candidate's geofence intersects an existing place's geofence by more than 50 percent of the smaller of the two radii areas, the operation is rejected with `ERR_PLACE_OVERLAP` (HTTP 409). This rule treats two places as covering the same physical fence and prevents double-counting of arrivals.

Geofence membership is evaluated for every accepted fix against every `ACTIVE` place of the member's circle. For a given place, the effective radius is the place's `radius_m` plus the smaller of the fix's `accuracy_m` and the place's `accuracy_floor_m` — the accuracy contribution is capped at the floor. The haversine distance between the fix and the place's centre is computed in metres to 0.1 m precision using an earth radius of 6,371,000 metres, and the fix is inside the place exactly when that distance is less than or equal to the effective radius (the comparison is inclusive — a fix exactly at the effective radius is inside). A fix whose reported `accuracy_m` exceeds the place's `accuracy_floor_m` cannot trigger alerts for that place — it is `REJECTED_ACCURACY` for that place's purposes only, though the same fix may still be `ACCEPTED` for trip purposes, because acceptance and per-place evaluation are independent. The list of places the fix landed inside at acceptance time is frozen onto the fix row as `place_ids_inside` and never recomputed thereafter.

Place alerts are created and resolved by the system as fixes arrive. A candidate alert opens in `PENDING_DWELL` when a fix places a member inside a place they were not previously inside (an `ARRIVAL` candidate) or outside a place they were previously inside (a `DEPARTURE` candidate). The alert records the `place_id`, the `member_id`, the `event_kind`, and the `window_open_fix_id`. The candidate is confirmed when a subsequent fix from the same member lands inside the same geofence (under the membership rule above) and the elapsed dwell — the difference between the candidate's `window_close_fix_id` recorded time and the `window_open_fix_id` recorded time — is at least the place's `dwell_bucket_seconds`, provided the circle's posture is `OPEN` at confirmation time. Confirmation stamps the `window_close_fix_id`, computes `visible_to_owner` from the member's `privacy_mode` at that moment (`true` under `PRECISE` or `BLURRED`, `false` under `HIDDEN`), and freezes both.

There is a subtle precondition on confirmation that exists to reject implausible resampling. The dwell window's two fixes must be separated by at least half of the member's `effective_sample_interval_seconds` as computed at the window-open fix — a window whose two fixes are closer together than that could not have been produced by the device's actual sampling cadence. The evaluation order is pinned: first compute the effective interval at the window-open fix; then, if the inter-fix gap is less than half that interval, suppress the alert with `suppressed_reason` `DUPLICATE_EVENT`; otherwise, if the dwell is at least the bucket, confirm; otherwise suppress with `suppressed_reason` left null.

Candidates that do not confirm resolve to `SUPPRESSED` or `CANCELLED`; those that do confirm land in `CONFIRMED`. Suppression carries a `suppressed_reason`: `DUPLICATE_EVENT` when the window is closed by an opposite-direction fix or by the implausible-resampling rule above; `TIER_HISTORY` when the circle's posture leaves `OPEN` before confirmation (the alert is held back and the eventual freeze on `FROZEN` sweeps these into `SUPPRESSED`); or `PRIVACY_HIDDEN` when the member flips to `HIDDEN` mid-window and the alert would otherwise have fired. Cancellation is reserved for the case where the member's consent leaves `GRANTED` before the candidate resolves; it carries no reason. Archiving a place also cancels every `PENDING_DWELL` alert open against that place.

Place alerts are listed for non-self readers through a privacy filter: alerts belonging to members whose current `privacy_mode` is `HIDDEN` are excluded from the response when the reader is not the alert's subject. List endpoints on place alerts accept optional filter parameters — `alert_status`, `member_id`, `event_kind`, `place_id`, `window_open_fix_id`, and `window_close_fix_id` — to narrow the result set; the member-scoped fix list similarly accepts `fix_status` and a `since` cutoff timestamp.

### 3.6. Driving Trips, Speed Events, and the Driver Score

A trip opens the first time a member with `consent_state` `GRANTED` posts a fix whose `motion_context` is `DRIVING` and no `OPEN` trip exists for that member. The trip's `started_at` is the timestamp of that first `DRIVING` fix. Subsequent `DRIVING` fixes extend the trip. The trip closes — `trip_status` becomes `CLOSED` — on the first accepted non-`DRIVING` fix or after 600 seconds have elapsed without a `DRIVING` fix (a timeout sweep); `ended_at` is the timestamp of the last `DRIVING` fix before close. A trip instead transitions to `ABANDONED` if the member's circle posture becomes `FROZEN` mid-trip or if the member's `consent_state` leaves `GRANTED` mid-trip; an abandoned trip computes no `driver_score` (the field is left null) and does not contribute to the member's rolling driver score.

On trip close, three aggregates are finalized. The list of trips for a member accepts an optional `trip_status` filter, and a single trip is read by `trip_id` against the member's trip collection. The `distance_m` is the sum, over each consecutive pair of `ACCEPTED` `DRIVING` fixes within the trip's window, of the haversine distance between the pair — and the rounding is per-segment: each leg is rounded half-up to a whole metre before being added to the running total. Computing haversine on the full polyline and rounding once at the end is forbidden and produces a different value. The pair sequence is the member's accepted `DRIVING` fixes whose `recorded_at` falls within the trip's `started_at`-to-`ended_at` window, ordered by `recorded_at` ascending with ties broken by `created_at` ascending. The `max_speed_mps` is the largest `speed_mps` observed on the trip's fixes. The `speed_event_count` counts consecutive-fix pairs whose average speed exceeds the tier's speed-event threshold. The `phone_use_event_count` counts accepted `DRIVING` fixes on the trip where `phone_in_use` is true and `speed_mps` is at least 1.0.

The driver score has two variants that share a single weighted formula and differ only in input set. The score starts at 100 and subtracts three penalties: 8 points per speed event, capped at 5 events; 5 points per phone-use event, capped at 6 events; and 1 point per whole mile of distance, where a mile is 1,609 metres and the per-mile count is the floor of `distance_m` divided by 1,609. The result is clamped to the inclusive range from 0 to 100 and is an integer. The trip-level variant is computed when a trip closes, against that single trip's aggregates, and is written to the trip's `driver_score`. The rolling variant is computed on read of the member's driver profile against all of the member's `CLOSED` trips whose `ended_at` is within the trailing 30 days and whose consent was `GRANTED` at end time; `ABANDONED` trips are excluded from both variants. The rolling variant is never persisted on the trip row — the same physical trips can produce a different rolling score than the trip-level view.

### 3.7. Crash Detection, Wellness Checks, and Emergency Dispatch

A crash candidate is reported against an open trip. The report names the `trip_report_id`, supplies the observed deceleration `delta_v` (in metres per second squared), and may include a free-text `note`. Two preconditions gate the report. First, the named trip must currently be `OPEN` and must belong to the same member the crash is reported against; otherwise the report is rejected with `ERR_TRIP_NOT_OPEN` (HTTP 409). Second, the `delta_v` must meet the minimum severity floor: a `delta_v` strictly less than 8.0 is rejected with `ERR_CRASH_BELOW_THRESHOLD` (HTTP 422) and no crash event is created. The severity ladder itself is a strict-threshold mapping compared at two decimal places: at least 8.0 but less than 16.0 maps to `MINOR`; at least 16.0 but less than 24.0 maps to `MAJOR`; 24.0 or more maps to `SEVERE`. The boundary is inclusive on the lower edge — a `delta_v` of exactly 16.0 is `MAJOR`, not `MINOR` — and a `delta_v` of exactly 7.99 is rejected.

A successfully reported crash event enters `DETECTED` and immediately transitions to `WELLNESS_PENDING`. The transition creates a wellness check in `SENT` with a `deadline_at` derived from the severity: `detected_at` plus 300 seconds for `SEVERE`, plus 600 seconds otherwise. The crash event's `crash_status` field tracks its position in the lifecycle (`DETECTED`, `WELLNESS_PENDING`, `CONFIRMED_OK`, `ESCALATED`, `DISPATCHED`, `RESOLVED`, or `FALSE_ALARM`), and the wellness check's `check_status` field tracks its own (`SENT`, `ACKNOWLEDGED`, `UNANSWERED`, or `CANCELLED`). The dispatch's `dispatch_status` similarly walks `PENDING_VERIFICATION`, `VERIFIED`, `STAGED`, `COMPLETED`, and `CANCELLED`. The crash event records the `wellness_check_id`, the `member_id`, the `trip_report_id`, the `detected_at` instant, and the computed `severity`; its `dispatch_id` stays null until escalation. The crash event's `version` increments on this and every subsequent state change.

While the crash is `WELLNESS_PENDING`, the member on whom the crash was detected may acknowledge the wellness check. Acknowledgement is accepted only while the logical clock is strictly before the check's `deadline_at`, and only from the crash-subject member themselves — the `X-User-ID` must equal the crash event's `member_id`. A successful acknowledgement moves the wellness check to `ACKNOWLEDGED`, records the `acknowledged_by_member_id`, transitions the crash event to `CONFIRMED_OK`, and — as a compensation — cancels any emergency dispatch that already exists in `PENDING_VERIFICATION`. An acknowledgement attempted at or after the deadline is rejected with `ERR_WELLNESS_EXPIRED` (HTTP 409); by then the system has already escalated.

When the wellness deadline passes with the check still `SENT`, the system escalates: the wellness check transitions to `UNANSWERED`, an emergency dispatch is created in `PENDING_VERIFICATION`, the circle's `assistance_units_balance` is decremented by 1, and the crash event moves to `ESCALATED`. Escalation is blocked — `ERR_ASSISTANCE_UNITS_EXHAUSTED` (HTTP 402) — when the balance is exhausted for the tier (0 on `FREE`/`PLUS`, or already -1 on `PROTECT`), and it is also blocked with `ERR_CIRCLE_RESTRICTED` (HTTP 409) when the circle's posture is `RESTRICTED`. Escalation increments both the crash event's `version` and the circle's `version`.

From `ESCALATED`, the circle's `OWNER` verifies the dispatch by supplying a `verification_note` of at least 10 characters. Verification moves the dispatch from `PENDING_VERIFICATION` to `VERIFIED` and then, atomically as a follow-on, to `STAGED` with `staged_at` stamped from the logical clock; the crash event transitions from `ESCALATED` to `DISPATCHED` in the same step, and its `version` increments. From `DISPATCHED`, the owner completes the dispatch: the dispatch moves from `STAGED` to `COMPLETED`, the crash event moves to `RESOLVED`, and the crash event's `version` increments. The owner may also cancel a dispatch directly while it is in `PENDING_VERIFICATION` — moving it to `CANCELLED` — but cancellation from `STAGED` or `COMPLETED` is rejected with `ERR_DISPATCH_ALREADY_STAGED` (HTTP 409).

A crash can be retracted as a false alarm by the owner, by an admin, or by the crash-subject member, from any of `DETECTED`, `WELLNESS_PENDING`, or `ESCALATED` — but never from `DISPATCHED`, because by then the assistance unit has been burned with the responder. The retraction requires a `false_alarm_reason` of at least 5 characters. On a successful retraction the crash event moves to `FALSE_ALARM`, the wellness check is `CANCELLED` if still `SENT`, the emergency dispatch is `CANCELLED` if it is `PENDING_VERIFICATION` or `VERIFIED`, and — critically — if the crash had previously consumed an assistance unit (that is, it was retracted from `ESCALATED`), one unit is returned to the circle's `assistance_units_balance`. This is the compensating invariant on the assistance budget: a compensated escalation leaves the balance exactly as it was before the escalation. A retraction from `DISPATCHED` or beyond does not refund. Retraction increments the crash event's `version`. Once a crash is `RESOLVED`, it cannot re-enter `ESCALATED` — that path is forbidden.

### 3.8. Compliance Holds and Disclosure-Driven Consent Expiry

A compliance hold is an open issue against the entire circle. Its `hold_kind` is one of `DATA_SHARING_DISCLOSURE`, `MONETIZATION_OPT_OUT_SWEEP`, or `MINOR_PRIVACY_AUDIT`; it is opened with a machine-readable `opened_reason` such as `disclosure_version_bump`; its `hold_status` is `OPEN` or `RESOLVED`; and when resolved it records the `resolved_by_member_id` of the `OWNER` who acknowledged it. Holds are opened only by the `System` role, and resolving one is owner-only. Opening a hold recomputes the circle's posture (typically to `RESTRICTED`) and increments the circle's `version`; resolving one recomputes posture again and increments `version` again. A circle's posture remains `RESTRICTED` until every hold on the circle is resolved.

The disclosure-bump sweep is the system's mechanism for forcing re-consent when the data-sharing disclosure changes. When a `DATA_SHARING_DISCLOSURE` hold is open on a circle, every member whose `consent_state` is `GRANTED`, whose `monetization_opt_in` is true, and who has not acknowledged the new disclosure within 30 days of the hold opening transitions their `consent_state` to `EXPIRED`. The transition appends a `ConsentRecord` with `consent_action` `EXPIRE`, forces the member's `privacy_mode` to `HIDDEN` until re-grant, and — when the affected member is a `MINOR` — opens a follow-up `MINOR_PRIVACY_AUDIT` hold on the circle. A member whose consent has expired re-enters `GRANTED` only by accepting a `FULL`-scope grant.

### 3.9. Aging, Retention, and the Daily Sweep

Several housekeeping concerns share a single daily sweep, which is triggered by the test-driving capability described in §2.10 and may also be invoked directly by `System` through the sweep capability.

The age sweep recomputes every member's `age_years` from the current logical date and the member's `birthdate`. When a `MINOR` member's recomputed age reaches 16, the member's `role` is promoted to `MEMBER`, the parent-imposed privacy override lock is released, the `tension_flag` is cleared, and the `privacy_mode` itself is preserved unchanged.

The retention sweep enforces each circle's history window. The window's depth is the circle's `history_retention_days` — 7 days on `FREE`, 30 on `PLUS`, 60 on `PROTECT`. On every list of location fixes or trip reports, the server applies a projection: a row is visible exactly when its `recorded_at` is on or after the cutoff computed as the current logical time minus the circle's `history_retention_days` expressed in days (86,400 seconds each). The comparison is inclusive — a row exactly at the cutoff is included. Rows older than the cutoff are not deleted; instead the daily sweep flips their `fix_status` to `RETIRED`, which is when the exclusion becomes observable on a direct read of the fix.

The wellness-deadline sweep finds every wellness check still `SENT` whose `deadline_at` has passed and transitions it to `UNANSWERED`, escalating the owning crash event as described in §3.7.

The sweep capability returns a summary containing the `promoted_member_ids` aged up by the age sweep, the `expired_consent_member_ids` whose consent was expired by the disclosure sweep, and the `retired_fix_count` of fixes marked `RETIRED` by the retention sweep.

Roadside assistance and identity protection consumption sit alongside the sweep as the explicit fiscal endpoints the circle exposes. Consuming a roadside-assistance unit requires a `reason`, consumes 1 from the circle's `assistance_units_balance` (a `PROTECT` circle may overdraw to exactly -1 within the current window as a safety valve), and appends a `SubscriptionEvent` of kind `ASSISTANCE_CONSUME` with `units_delta` -1. Attempting consumption on a circle whose posture is `RESTRICTED` is rejected with `ERR_CIRCLE_RESTRICTED`; attempting it on a `FREE`/`PLUS` circle at balance 0 or a `PROTECT` circle already at -1 is rejected with `ERR_ASSISTANCE_UNITS_EXHAUSTED`. Consuming an identity-protection credit likewise requires a `reason`, is `PROTECT`-only and owner-only, decrements `identity_protection_credits` by 1, and appends an `IDENTITY_CREDIT_CONSUME` event with `units_delta` -1; a non-positive balance rejects the call with `ERR_NO_IDENTITY_CREDIT` without appending any event.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a circle, a place, a location fix, a crash event, a compliance hold, a roadside-assistance consumption, an identity-credit consumption — return `201 Created`. Operations that modify an existing resource, transition a state, or acknowledge an existing entity return `200 OK`. All endpoints are mounted under the `/api` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/_clock/set_current_utc` | Advance the server logical clock and run any due sweeps | System |
| POST   | `/api/_sweeps/age-and-retention` | Run the daily age, retention, and wellness-deadline sweeps | System |
| POST   | `/api/circles` | Create a circle; creating user becomes the first member with role OWNER | Owner |
| GET    | `/api/circles` | List circles (paginated; supports filters on subscription_status, subscription_tier, owner_member_id) | System |
| GET    | `/api/circles/{id}` | Read a circle | Owner, Admin, Member, Minor, System |
| POST   | `/api/circles/{id}/members` | Invite a member to the circle | Owner, Admin |
| GET    | `/api/circles/{id}/members` | List members of a circle | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/members/{member_id}` | Read a member (nested path) | Owner, Admin, Member, Minor, System |
| POST   | `/api/circles/{id}/members/{member_id}/promote` | Promote MEMBER to ADMIN | Owner |
| POST   | `/api/circles/{id}/members/{member_id}/demote` | Demote ADMIN to MEMBER | Owner |
| POST   | `/api/circles/{id}/transfer-ownership` | Transfer OWNER role to another member | Owner |
| POST   | `/api/circles/{id}/members/{member_id}/consent/grant` | Grant consent for a member | Owner, Admin, Member, Minor |
| POST   | `/api/circles/{id}/members/{member_id}/consent/revoke` | Revoke consent for a member | Owner, Admin, Member, Minor |
| GET    | `/api/circles/{id}/members/{member_id}/consent-records` | List the consent ledger for a member | Owner, Admin, Member, Minor, System |
| GET    | `/api/consent-records` | Filtered list of consent records (by member_id, granted_by_member_id) | System |
| GET    | `/api/consent-records/{id}` | Read a single consent record | Owner, Admin, Member, Minor, System |
| PATCH  | `/api/circles/{id}/members/{member_id}/privacy` | Update a member's privacy_mode (OCC on member version) | Owner, Admin, Member, Minor |
| POST   | `/api/circles/{id}/places` | Create a geofenced place | Owner, Admin |
| GET    | `/api/circles/{id}/places` | List places of a circle | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/places/{place_id}` | Read a place (nested path) | Owner, Admin, Member, Minor, System |
| PATCH  | `/api/circles/{id}/places/{place_id}` | Update a place's radius, accuracy floor, dwell bucket, or notify flags | Owner, Admin |
| POST   | `/api/circles/{id}/places/{place_id}/archive` | Archive a place; PENDING_DWELL alerts are cancelled | Owner, Admin |
| GET    | `/api/places/{id}` | Read a place (top-level) | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/places/{place_id}/alerts` | List place alerts for a place | Owner, Admin, Member, Minor, System |
| GET    | `/api/place-alerts` | Filtered list of place alerts (by place_id, member_id, window fix ids, alert_status, event_kind) | System |
| GET    | `/api/place-alerts/{id}` | Read a single place alert | Owner, Admin, Member, Minor, System |
| POST   | `/api/circles/{id}/members/{member_id}/fixes` | Ingest a location fix; runs geofence, trip continuity, battery/motion tracking, sampling recompute | Owner, Admin, Member, Minor |
| GET    | `/api/circles/{id}/members/{member_id}/fixes` | List location fixes for a member (retention-windowed) | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/members/{member_id}/fixes/{fix_id}` | Read a single fix (nested path) | Owner, Admin, Member, Minor, System |
| GET    | `/api/location-fixes` | Filtered list of fixes (by member_id) | System |
| GET    | `/api/location-fixes/{id}` | Read a single fix (top-level) | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/members/{member_id}/trips` | List trip reports for a member (retention-windowed) | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/members/{member_id}/trips/{trip_id}` | Read a trip report (nested path) | Owner, Admin, Member, Minor, System |
| GET    | `/api/trip-reports` | Filtered list of trip reports (by member_id) | System |
| GET    | `/api/trip-reports/{id}` | Read a trip report (top-level) | Owner, Admin, Member, Minor, System |
| POST   | `/api/circles/{id}/members/{member_id}/crash-events` | Report a crash candidate against an OPEN trip; creates the crash event and its wellness check | Owner, Admin, Member, Minor, System |
| GET    | `/api/circles/{id}/members/{member_id}/crash-events` | List crash events for a member | Owner, Admin, Member, Minor, System |
| GET    | `/api/crash-events` | Filtered list of crash events (by member_id, trip_report_id, wellness_check_id, dispatch_id) | System |
| GET    | `/api/crash-events/{id}` | Read a crash event | Owner, Admin, Member, Minor, System |
| POST   | `/api/crash-events/{id}/wellness-checks/{check_id}/acknowledge` | Member acknowledges the wellness check before the deadline | Owner, Admin, Member, Minor |
| POST   | `/api/crash-events/{id}/mark-false-alarm` | Mark a crash as a false alarm | Owner, Admin, Member, Minor |
| GET    | `/api/wellness-checks` | Filtered list of wellness checks (by crash_event_id, acknowledged_by_member_id) | System |
| GET    | `/api/wellness-checks/{id}` | Read a wellness check | Owner, Admin, Member, Minor, System |
| GET    | `/api/emergency-dispatches` | Filtered list of dispatches (by crash_event_id) | System |
| GET    | `/api/emergency-dispatches/{id}` | Read a dispatch | Owner, Admin, System |
| POST   | `/api/emergency-dispatches/{id}/verify` | Owner verifies the dispatch, moving it VERIFIED then STAGED | Owner |
| POST   | `/api/emergency-dispatches/{id}/complete` | Owner completes a staged dispatch | Owner |
| POST   | `/api/emergency-dispatches/{id}/cancel` | Owner cancels a pending-verification dispatch | Owner |
| POST   | `/api/circles/{id}/subscription/change-tier` | Change the circle's subscription tier (OCC on circle version) | Owner |
| POST   | `/api/circles/{id}/subscription/reactivate` | Reactivate a SUSPENDED circle | Owner |
| POST   | `/api/circles/{id}/subscription/simulate-payment-failed` | Operator action: simulate a failed renewal payment | System |
| POST   | `/api/circles/{id}/subscription/simulate-suspend` | Operator action: suspend the circle | System |
| GET    | `/api/circles/{id}/subscription-events` | List the circle's subscription ledger | Owner, Admin, System |
| GET    | `/api/subscription-events` | Filtered list of subscription events (by circle_id, event_kind) | System |
| GET    | `/api/subscription-events/{id}` | Read a single subscription event | Owner, Admin, System |
| POST   | `/api/circles/{id}/roadside-assistance` | Consume one roadside-assistance unit | Owner, Admin |
| POST   | `/api/circles/{id}/identity-protection/consume` | Consume one identity-protection credit (PROTECT only) | Owner |
| POST   | `/api/circles/{id}/compliance-holds` | Open a compliance hold (e.g., disclosure version bump) | System |
| GET    | `/api/circles/{id}/compliance-holds` | List compliance holds for a circle | Owner, Admin, System |
| POST   | `/api/circles/{id}/compliance-holds/{hold_id}/resolve` | Owner resolves a hold | Owner |
| GET    | `/api/compliance-holds` | Filtered list of compliance holds (by circle_id, resolved_by_member_id) | System |
| GET    | `/api/compliance-holds/{id}` | Read a compliance hold | Owner, Admin, System |
| GET    | `/api/members` | List members; supports filters on circle_id, last_known_fix_id, role, consent_state | System |
| GET    | `/api/members/{id}` | Read a member (top-level) | Owner, Admin, Member, Minor, System |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API may return. The trigger condition for each error is described in the workflow narratives of §2 and §3; this table is purely a reference for the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CIRCLE_FROZEN` | 409 |
| `ERR_CIRCLE_RESTRICTED` | 409 |
| `ERR_WELLNESS_EXPIRED` | 409 |
| `ERR_DISPATCH_ALREADY_STAGED` | 409 |
| `ERR_TRIP_NOT_OPEN` | 409 |
| `ERR_CONSENT_NOT_GRANTED` | 409 |
| `ERR_MINOR_CONSENT_LOCKED` | 403 |
| `ERR_PRIVACY_SELF_ONLY` | 403 |
| `ERR_PLACE_CONFIG_INVALID` | 422 |
| `ERR_FIX_CLOCK_SKEW` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ROLE_INCOMPATIBLE` | 409 |
| `ERR_PLACE_OVERLAP` | 409 |
| `ERR_ASSISTANCE_UNITS_EXHAUSTED` | 402 |
| `ERR_NO_IDENTITY_CREDIT` | 402 |
| `ERR_CRASH_BELOW_THRESHOLD` | 422 |
| `ERR_STALE_VERSION` | 412 |
