# Driver Safety Camera Coaching API — Product Requirements Document

## 1. Introduction

Commercial fleets increasingly rely on in-cab cameras and telematics to detect risky driving behavior — harsh braking, tailgating, distraction, seat belt violations, and collisions — but detection alone does not change behavior. What changes behavior is a disciplined operational loop: detected events must be uploaded under real-world bandwidth constraints, reviewed by a human safety manager who can confirm, dismiss, or reclassify them, converted into coaching conversations that drivers acknowledge and complete, and escalated when risky behavior repeats within a rolling window. Alongside that loop sits a second, equally sensitive track: drivers must be able to contest confirmed collisions through an exoneration workflow that preserves footage evidence, respects segregation of duties between the reviewer and the claims adjuster, and unwinds the operational consequences of a confirmation when the evidence clears the driver.

This document specifies the Driver Safety Camera Coaching API, a fleet-safety platform in the style of Samsara's video-based safety product. The platform serves fleets organized into terminals, each terminal staffed with drivers and vehicles fitted with camera units. Camera policies govern what is captured and how long footage is retained; union agreements constrain what may be done with inward-facing footage at each terminal; litigation holds freeze footage for legal matters regardless of retention schedules. Safety scoring runs at driver, terminal, and fleet granularity, feeding a leaderboard and a tiered incentive program whose payouts are bounded by a per-fleet season budget.

The specification is written for the engineering team implementing the service. Global conventions — authentication, response envelopes, pagination, concurrency control, the logical clock, and privacy gating — are described in Section 2. Business workflows are described in Section 3, deliberately organized by operational narrative rather than by resource. Section 4 provides the endpoint summary table and Section 5 the error code catalogue; both are intentionally minimal, and readers must reconstruct complete request and response semantics from Sections 2 and 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which that principal acts. A request missing either header, or carrying a role name the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the target endpoint — or which violates an ownership rule — is rejected with `ERR_FORBIDDEN`.

Six roles are declared:

- `PlatformAdmin` — the fleet operator administrator. Owns configuration: fleets, terminals, vehicles, union agreements, camera policies, driver registration, fleet posture, the logical clock, and maintenance runs. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `TelematicsIngest` — the device-side ingest pipeline. Pushes safety events and footage clips and drives clip upload state transitions. When `X-User-Role` is `TelematicsIngest`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `SafetyManager` — the safety reviewer. Owns the review queue, coaching sessions, escalation cases, manual driver status changes, footage purges, and litigation holds. When `X-User-Role` is `SafetyManager`, `X-User-ID` is an opaque operator identifier; the server records it where a workflow requires attribution (for example, as `reviewer_id` on a review decision, `assigned_by` on a manually created coaching session, or `placed_by` on a litigation hold) but does not compare it to any entity's `id` for ownership.
- `ClaimsAdjuster` — the insurance-side adjuster. Owns exoneration claim review and decision. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier; the server records it as `decided_by` on a decided claim and consults it for the segregation-of-duties check, but does not compare it to any entity's `id` for ownership.
- `Driver` — a fleet driver. Acknowledges their own coaching sessions and files exoneration claims for their own events. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on any resource that references a `Driver` compare the resource's `driver_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.
- `FleetAdmin` — the fleet executive. Owns score snapshot computation and incentive award approval and payment. When `X-User-Role` is `FleetAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All six roles may invoke any read (GET) endpoint. Read endpoints apply no ownership scoping: a `Driver` may read any resource, including other drivers' resources, and the `driver_id` ownership comparison is enforced only on the two Driver write operations that carry an ownership rule (acknowledging a coaching session and submitting an exoneration claim). Write endpoints are restricted per Section 4.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope. Unless a more specific ordering is stated for a given list (the review queue and the leaderboard each define their own), list endpoints return resources sorted by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id`, a server-minted UUID with no type prefix. All entities other than review decisions additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and an integer `version` that starts at 1 on creation and increments by exactly one on every mutation of that resource, including system-driven mutations such as automatic status transitions. Review decisions are the deliberate exception: as an append-only audit record, a `ReviewDecision` carries only `id` and `created_at` among the common fields; both `updated_at` and `version` are absent from it entirely.

When one operation mutates several resources — for example, a confirmation that also opens an escalation case and moves the driver onto a coaching hold — each affected resource's `version` increments independently and each affected resource's `updated_at` refreshes.

### 2.5. The Logical Clock

The platform evaluates all temporal rules against a logical clock, never against wall-clock time. Before the clock is explicitly set, it reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` moves the clock through an admin-only capability that accepts a target instant `to_iso8601`, moves the clock unconditionally in either direction (there is no monotonicity constraint), and returns the new `current_utc`. Event occurrence timestamps, capture timestamps, deadlines, retention windows, exoneration windows, rolling score windows, and the overdue sweep all compare against this logical clock. Datetime comparisons in workflows operate at second precision.

### 2.6. Optimistic Concurrency Control

Two write operations require the caller to present the version of the resource it last observed, protecting workflows where one reader's decision must not silently overwrite state advanced by another writer.

A review action on a safety event must carry `expected_event_version` equal to the event's current `version`. If the event's version has advanced since the client last read it — whether through a prior review action or through the automatic transition into review triggered by the first uploaded clip — the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), and no review decision is recorded.

A camera policy patch must carry `expected_policy_version` equal to the policy's current `version`. If a prior patch or a status transition has advanced the policy since the client last observed it, the patch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field.

### 2.7. Precision, Rounding, and Monetary Conventions

Scores are decimal values carried at exactly two decimal places, rounded half-up at every rounding step. Where the scoring rules require rounding, each event's penalty is rounded to two decimal places before penalties are summed; rounding only the final sum is a rejected evaluation order. The upload priority score, event counts, session reassignment counts, escalation offense counts, maintenance run indices, retention megabytes, and leaderboard ranks are integers computed with integer arithmetic and no rounding. Monetary values are integer cents: incentive budgets and award amounts are expressed in cents with no fractional component.

### 2.8. Privacy, Consent, and Union Gating

Inward-facing footage is the most sensitive data the platform handles, and three independent switches must all permit it before an inward clip may be registered or an event carrying an inward clip may be reviewed. First, the fleet's currently `ACTIVE` camera policy must have `inward_capture_enabled` set to true; if the fleet has no `ACTIVE` policy at all, the gate fails. Second, looking at the driver's terminal at the logical clock, either no `RATIFIED` union agreement covers that instant, or the covering agreement has `inward_camera_allowed` set to true. Third, the driver's own `inward_camera_consent` must be true. Failure of any of the three conditions is rejected with `ERR_INWARD_FOOTAGE_RESTRICTED`. Union agreements additionally declare `live_view_allowed` and `audio_recording_allowed` as negotiated capabilities recorded on the agreement, and `coaching_requires_steward_present`, which feeds the steward computation on coaching sessions described in Section 3.7.

### 2.9. Fleet Lockdown Posture

A fleet operates in one of two postures: `NORMAL` or `INCIDENT_LOCKDOWN`. Posture is a gate, not a cascade: moving a fleet into or out of lockdown changes the fleet's own `posture` and bumps its `version`, but never touches the state of any child resource. While a fleet is in `INCIDENT_LOCKDOWN`, three operations are blocked across the platform: confirming an event in review, completing a coaching session, and computing a score snapshot. Each is rejected with `ERR_FLEET_LOCKED`. All other operations — ingest, uploads, dismissals, reclassification, claim decisions, purges, holds — remain available during lockdown.

### 2.10. Validation Order and Error Precedence

When a request violates several rules at once, checks are evaluated in a fixed priority order so the returned error is deterministic. Authentication comes first (missing or unknown headers yield `ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_FORBIDDEN`). Next the request body is validated as JSON with all required fields present, enum members declared, datetimes parseable, integer ranges respected, and the session-window shape constraints — `starts_at` strictly before `ends_at`, and `due_at` no earlier than `ends_at` — enforced (`ERR_VALIDATION`). Then path identifiers are resolved left-to-right, each missing segment producing its resource-specific not-found error, followed by body foreign keys, checked in the order the endpoint's input list declares them. State-machine legality is checked next (`ERR_INVALID_STATE`), then the safety and privacy gates (the inward-footage gate, segregation of duties on exoneration decisions, and the litigation-hold block on purge), then the temporal window rules (exoneration window, future timestamps, session window overlap, agreement window overlap), then optimistic-concurrency staleness (`ERR_STALE_EVENT_VERSION` on review and `ERR_STALE_POLICY_VERSION` on policy patch), then referenced-entity state (driver activity, fleet posture, confirmed-collision claim prerequisites, confirmed-event session prerequisites, final-snapshot award prerequisites, active-policy upload prerequisites), then uniqueness and capacity constraints, and finally the fiscal check on incentive payment. Because the safety gate runs before the temporal and referential checks, a privacy-blocked inward review surfaces `ERR_INWARD_FOOTAGE_RESTRICTED` rather than being masked by a posture or driver-status failure that would also apply.

### 2.11. Nested Resource Retrieval

List endpoints that hang beneath a parent path resolve their path identifiers strictly left-to-right. Each segment that does not resolve to an existing resource fails with the resource-specific not-found error — `ERR_FLEET_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_CLIP_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND` as appropriate — before any later segment is examined.

## 3. Business Logic & Workflows

### 3.1. Fleet and Terminal Onboarding

A `PlatformAdmin` begins by creating a fleet with a display `name` and a season incentive budget cap `incentive_budget_cents` (a non-negative integer number of cents). A new fleet starts with `posture` `NORMAL`, an `ops_run_index` of 0, and `retention_used_mb` of 0; the latter two are maintained by the platform and are described further in Sections 3.5 and 3.8. Terminals are then registered against the fleet by `fleet_id`, each with a `name` and a two-letter `region_code`. Every terminal exposes a computed `safety_score_cached` holding the terminal-level aggregation defined in Section 3.9.

Drivers are registered against a terminal by `terminal_id`, carrying an external HR reference `employee_ref` (unique within the fleet — a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`), a `name`, a `hire_date`, and the driver's signed `inward_camera_consent` flag. A new driver starts in status `ACTIVE`. Vehicles are registered against a terminal by `terminal_id`, carrying a `vin` (likewise unique within the fleet, with duplicates rejected as `ERR_DUPLICATE_RESOURCE`), the installed `camera_unit_id`, and a `bandwidth_tier` of `LOW`, `STANDARD`, or `HIGH`, which feeds upload prioritization. A new vehicle starts `ACTIVE`; decommissioning moves it to `DECOMMISSIONED` and is only permitted while the vehicle has no events still sitting in `DETECTED` or `IN_REVIEW`.

A `SafetyManager` may move a driver manually between `ACTIVE`, `SUSPENDED`, and `INACTIVE` by submitting a `to_status` (optionally annotated with a `reason`). `COACHING_HOLD` is never accepted as a manual target — that status is entered and exited only by the escalation machinery of Section 3.7. `INACTIVE` is terminal. The accepted manual transitions are exactly `ACTIVE` → `SUSPENDED`, `SUSPENDED` → `ACTIVE`, `ACTIVE` → `INACTIVE`, and `SUSPENDED` → `INACTIVE`; a driver in `COACHING_HOLD` rejects every manual status change, and every other pairing is rejected with `ERR_INVALID_STATE`.

### 3.2. Union Agreements and Camera Policies

Union agreements are registered per terminal with an `agreement_code` unique within that terminal, the four negotiated capability flags (`inward_camera_allowed`, `live_view_allowed`, `audio_recording_allowed`, `coaching_requires_steward_present`), and a closed effectiveness window from `effective_from` (inclusive) to `effective_until` (inclusive), where the end must be strictly after the start (equality fails validation). A new agreement is `DRAFT`. The `agreement_code` uniqueness is enforced at creation against all agreements of the terminal regardless of their status. Ratification moves it to `RATIFIED` and enforces window exclusivity: no other `RATIFIED` agreement of the same terminal may have a closed window sharing any instant with the ratifying window — and because both windows are closed, one window ending exactly when another begins still counts as overlap, rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. A `RATIFIED` agreement may later be moved to `EXPIRED`, which is terminal.

Camera policies are the fleet's detection and retention configuration: `retention_days_standard` (at least 1 day), `retention_days_collision` (at least as many days as the standard retention), `daily_upload_cap_mb` (at least 1), the master `inward_capture_enabled` switch, two detection switches `distraction_detection_enabled` and `seatbelt_detection_enabled`, and an `effective_from` start. A new policy is `DRAFT`. While `DRAFT`, its fields may be patched under optimistic concurrency (Section 2.6). Activating a `DRAFT` policy moves it to `ACTIVE` and, in the same request, moves the fleet's previously `ACTIVE` policy (if any) to `ARCHIVED`, so exactly one policy is ever `ACTIVE` per fleet. Archival of a `DRAFT` policy is always permitted; attempting to archive the fleet's currently `ACTIVE` policy directly is rejected with `ERR_POLICY_IN_USE`, because the only way out of `ACTIVE` is replacement by activation. When the active policy disables a detection switch, ingesting an event of the disabled type is rejected with `ERR_EVENT_TYPE_DISABLED` — this applies to `DISTRACTION` and `SEAT_BELT` events. When the fleet has no `ACTIVE` policy at all, ingest is not blocked by any detection switch, and this check does not apply.

### 3.3. Event Ingestion and Upload Prioritization

The `TelematicsIngest` pipeline registers a detected safety event with the `fleet_id`, `driver_id`, and `vehicle_id` it concerns, an `event_type` of `HARSH_BRAKE`, `FOLLOWING_DISTANCE`, `DISTRACTION`, `SEAT_BELT`, or `COLLISION`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and the `occurred_at` instant, which must not lie after the logical clock (a future timestamp is rejected with `ERR_EVENT_IN_FUTURE`). The server stamps `detected_at` with the logical clock at ingest, initializes the event to `DETECTED` with `review_count` 0 and `confirmed_at` unset, and computes the event's `upload_priority_score` exactly once; the score is stored and never recomputed afterward.

The priority score rewards severe, fresh events on well-connected vehicles. The event's age in whole hours is the elapsed time from `occurred_at` to `detected_at`, computed as the floor of the elapsed seconds divided by 3600. The age contributes a step multiplier: 4 when the age is at most 6 hours, 2 when the age is greater than 6 hours and at most 24 hours, and 1 beyond 24 hours. The base score is the severity weight — 1 for `LOW`, 3 for `MEDIUM`, 6 for `HIGH`, 10 for `CRITICAL` — multiplied by the age step, multiplied by the vehicle's bandwidth tier multiplier (1 for `LOW`, 2 for `STANDARD`, 3 for `HIGH`). A `COLLISION` event additionally receives a flat boost of 1000 points. All arithmetic is integer arithmetic with no rounding.

The review queue listing presents the fleet's events ordered by `upload_priority_score` descending; ties break by `occurred_at` ascending, then by `created_at` ascending, and a resource's `id` is never used as a tie-break input. The queue may be filtered by `status`, `event_type`, `driver_id`, or `vehicle_id`.

### 3.4. The Event Review Cycle

An event becomes reviewable when its evidence arrives: the first footage clip of the event to complete upload transitions the event from `DETECTED` to `IN_REVIEW` automatically, bumps the event's `version`, and brings the event into the provisional scoring input set described in Section 3.9.

A `SafetyManager` then applies review actions, each of which appends an immutable `ReviewDecision` to the event's decision log and increments `review_count`. The log records, for every action, the acting manager's identifier as `reviewer_id`, the `action` (`CONFIRM`, `DISMISS`, `RECLASSIFY`, or `REOPEN`), the event's `prior_event_type` and `prior_severity`, the `new_event_type` and `new_severity` (both recorded only for `RECLASSIFY`, and left unset otherwise), the reviewer-supplied `rationale`, and the `decided_at` logical-clock instant. Review actions are submitted with the chosen `action`, a `rationale`, the optimistic-concurrency field `expected_event_version` (Section 2.6), and — for reclassification only — the replacement `new_event_type` and/or `new_severity`.

Confirming an event from `IN_REVIEW` to `CONFIRMED` is the most consequential action in the system and is guarded by three preconditions: the fleet must be in `NORMAL` posture (otherwise `ERR_FLEET_LOCKED`), the driver must be in `ACTIVE` or `COACHING_HOLD` status (otherwise `ERR_DRIVER_NOT_ACTIVE`), and if the event carries an inward-facing clip the privacy gate of Section 2.8 must pass (otherwise `ERR_INWARD_FOOTAGE_RESTRICTED`). On confirmation the server stamps `confirmed_at` with the logical clock and executes a four-link cascade in order. First, if the event's severity is `HIGH` or `CRITICAL`, a coaching session is auto-created in `ASSIGNED` status with `assigned_by` recorded as `SYSTEM`, its window starting at the current logical clock and ending seven days later, and `due_at` equal to that same end; auto-created sessions are exempt from the session-window overlap rule that constrains manual assignment. Second, the driver's `confirmed_events_90d` count and both safety score variants are recomputed. Third, if this confirmation moved the driver's rolling 90-day confirmed count from exactly 2 to 3 or more and the driver is currently `ACTIVE`, an escalation case opens automatically in `OPEN` status with `trigger_event_id` pointing at this event and `offense_count` recording the new count. Fourth, that case opening transitions the driver from `ACTIVE` to `COACHING_HOLD`; a confirmation on a driver already in `COACHING_HOLD` therefore never opens a case.

Dismissing an event moves it from `IN_REVIEW` to `DISMISSED` and removes it from the provisional scoring input set. Reclassifying moves it from `IN_REVIEW` to `RECLASSIFIED`, applying the supplied `new_event_type` and/or `new_severity`; at least one of the two must be supplied and differ from the current value — a reclassification that changes neither field is rejected with `ERR_INVALID_STATE`. A `RECLASSIFIED` or `DISMISSED` event may be returned to `IN_REVIEW` by the reopen action; reopening a reclassified event leaves `confirmed_at` unset as it was. An event may be reviewed repeatedly — there is no cap on `review_count`.

The final transition out of `CONFIRMED` belongs to the exoneration workflow: when a claim decides `EXONERATE`, the event moves to the terminal state `EXONERATED`, `confirmed_at` resets to unset, and the compensation cascade of Section 3.8 fires.

### 3.5. Footage: Upload, Retention, Purge, and Litigation Holds

Footage clips are registered by the ingest pipeline against an `event_id`, with a `camera_angle` of `FORWARD`, `INWARD`, or `SIDE`, a `size_mb` of at least 1, and a `captured_at` instant that must not lie after the logical clock (`ERR_EVENT_IN_FUTURE`). Registering an `INWARD` clip passes through the privacy gate of Section 2.8, which applies to all three camera angles of every event type, including `COLLISION` events. Every clip carries two independent state dimensions that evolve in parallel and never influence one another: `upload_status` (`QUEUED`, `UPLOADING`, `UPLOADED`, `PURGED`) and `retention_class` (`STANDARD`, `COLLISION`, `LITIGATION_HOLD`). At registration the clip starts `QUEUED`, and its retention class initializes to `COLLISION` when the parent event's type is `COLLISION`, otherwise `STANDARD`.

Beginning an upload moves the clip `QUEUED` → `UPLOADING`. Completing it moves `UPLOADING` → `UPLOADED`, stamps `uploaded_at` with the logical clock, and enforces the fleet's daily upload budget: completing is rejected with `ERR_ACTIVE_POLICY_REQUIRED` when the fleet has no `ACTIVE` camera policy, and with `ERR_DAILY_UPLOAD_CAP_EXCEEDED` when the sum of `size_mb` over the fleet's clips already uploaded on the same UTC calendar day as the logical clock, plus this clip's `size_mb`, would exceed the policy's `daily_upload_cap_mb` — a total exactly equal to the cap is admitted. A completed upload also adds the clip's `size_mb` to the fleet's `retention_used_mb`, and if this is the event's first clip to reach `UPLOADED`, the event bubbles up from `DETECTED` to `IN_REVIEW` as described in Section 3.4.

Purging moves an `UPLOADED` clip to `PURGED`, stamps `purged_at`, and subtracts `size_mb` from the fleet's `retention_used_mb`. Two preconditions guard the purge. First, no `ACTIVE` litigation hold may cover the clip's event or its driver — a covered purge is rejected with `ERR_LITIGATION_HOLD_ACTIVE`, and a clip sitting in retention class `LITIGATION_HOLD` is never purgeable while it remains in that class. Second, retention must have expired: a `STANDARD` clip is purgeable once the logical clock has reached `captured_at` plus the active policy's `retention_days_standard`, and a `COLLISION` clip once the clock has reached `captured_at` plus `retention_days_collision`; the boundary is inclusive, so a clip exactly at its retention deadline may be purged, and an earlier attempt is rejected with `ERR_RETENTION_NOT_EXPIRED`. The fleet's `retention_used_mb` is defined at all times as the sum of `size_mb` over the fleet's clips whose `upload_status` is not `PURGED`; placing or releasing a hold never changes it.

Litigation holds are placed by a `SafetyManager` with a `fleet_id`, a `scope` of `DRIVER` or `EVENT`, and a `reason` matter reference. A driver-scoped hold supplies `driver_id` and leaves `event_id` unset; an event-scoped hold supplies `event_id` and leaves `driver_id` unset. The referencing field for the chosen scope must exist (`ERR_DRIVER_NOT_FOUND` or `ERR_EVENT_NOT_FOUND`), but its membership in the hold's fleet is not re-verified. The server records `placed_by` and `placed_at` and starts the hold `ACTIVE`. Only one `ACTIVE` hold may exist per driver and per event — a second placement of the same scope over an already-covered target is rejected with `ERR_ACTIVE_HOLD_EXISTS`; a driver-scoped hold and an event-scoped hold over the same driver do not conflict. Placement immediately reclassifies every covered clip that has not been purged: its `retention_class` becomes `LITIGATION_HOLD` while `upload_status` is left untouched. Releasing a hold stamps `released_at`, moves the hold to `RELEASED`, and reverts each covered clip still carrying the `LITIGATION_HOLD` class — provided no other `ACTIVE` hold still covers it — deterministically by the parent event's type: clips of `COLLISION` events return to `COLLISION`, all others return to `STANDARD`.

### 3.6. Coaching Sessions: Assignment Through Completion

Coaching sessions bind a confirmed event to a structured conversation with the driver. They arise in two ways: automatically on confirmation of a `HIGH` or `CRITICAL` event (Section 3.4), or manually when a `SafetyManager` assigns a session against a driver by supplying the `event_id` of a confirmed event plus a `starts_at`, `ends_at`, and `due_at`. Manual assignment requires the referenced event to be in `CONFIRMED` status (otherwise `ERR_EVENT_NOT_CONFIRMED`) and its window must not overlap the driver's other occupying sessions: session windows are half-open — inclusive at `starts_at`, exclusive at `ends_at` — so a session beginning exactly when another ends does not overlap, and any true overlap is rejected with `ERR_SESSION_WINDOW_OVERLAP`. The deadline `due_at` must not precede `ends_at`. Manually assigned sessions start `ASSIGNED` with the assigning manager recorded in `assigned_by`; auto-created sessions carry `SYSTEM` there instead.

Whether a union steward must attend is derived, not chosen: `steward_required` is true when the driver's terminal has a `RATIFIED` agreement whose closed window covers the session's `starts_at` and whose `coaching_requires_steward_present` flag is true.

The driver acknowledges their own session, moving it `ASSIGNED` → `ACKNOWLEDGED`; the acting `X-User-ID` must equal the session's `driver_id`, otherwise the attempt is rejected with `ERR_FORBIDDEN`. Sessions still occupying `ASSIGNED` or `ACKNOWLEDGED` past their deadline are moved to `OVERDUE` by the maintenance sweep (Section 3.8). An overdue session may be reassigned by a `SafetyManager` with a fresh `starts_at`, `ends_at`, and `due_at` (optionally annotated with a `reason`), returning it to `ASSIGNED`; reassignment replaces the three timestamps, increments `reassign_count`, and enforces the same non-overlap rule as manual assignment, excluding the reassigned session itself from the overlap comparison.

Completion is recorded by a `SafetyManager` against an `ACKNOWLEDGED` session with an `outcome` of `PASS` or `FAIL` (optionally with `notes`), stamping `completed_at`; completion is blocked while the fleet is in `INCIDENT_LOCKDOWN` (`ERR_FLEET_LOCKED`). A session in `ASSIGNED` or `OVERDUE` may instead be cancelled outright (optionally with a `reason`), and cancellation also arrives automatically when the session's underlying event is exonerated — every session tied to the exonerated event that is still `ASSIGNED`, `ACKNOWLEDGED`, or `OVERDUE` moves to `CANCELLED`. `COMPLETED` and `CANCELLED` are terminal.

### 3.7. Escalation: Repeat Offenses and the Coaching Hold

Escalation converts repeated confirmed risk into formal process. The driver-level counter `confirmed_events_90d` counts the driver's events in `CONFIRMED` status whose `occurred_at` falls within the rolling window from 90 days before the logical clock through the logical clock, inclusive at both ends — an event exactly 90 days old still counts. When a confirmation moves this count from exactly 2 to 3 or more, the platform opens an `EscalationCase` in `OPEN` status, recording the confirming event in `trigger_event_id`, the new count in `offense_count`, and the window length in `window_days` (always 90), and simultaneously moves the driver `ACTIVE` → `COACHING_HOLD`. The second confirmed event triggers nothing; the third does.

A `SafetyManager` picks up an open case by moving it `OPEN` → `UNDER_REVIEW` (optionally with a `note`), may return it `UNDER_REVIEW` → `OPEN` via send-back, and ultimately resolves it from `UNDER_REVIEW` with a `resolution` and a `resolution_note`. Resolving with `ACTION_TAKEN` lands the case in `RESOLVED_ACTION` and suspends the driver — `COACHING_HOLD` → `SUSPENDED`, applied only when the driver is currently in `COACHING_HOLD` and leaving any other status untouched. Resolving with `CLOSED_NO_ACTION` lands the case in `RESOLVED_NO_ACTION`, and if the driver then has no remaining cases in `OPEN` or `UNDER_REVIEW`, the driver returns `COACHING_HOLD` → `ACTIVE`. Both resolved states are terminal.

Exoneration unwinds escalation symmetrically. When an exonerated event's removal drops the driver's `confirmed_events_90d` below 3, every case for that driver in `OPEN` or `UNDER_REVIEW` auto-transitions to `RESOLVED_NO_ACTION`, and if no `OPEN` or `UNDER_REVIEW` cases remain afterward, a driver sitting in `COACHING_HOLD` returns to `ACTIVE`.

### 3.8. Exoneration Claims and Segregation of Duties

After a collision, the evidence captured by the platform may clear the driver. A `Driver` submits an exoneration claim against their own confirmed collision event, supplying a `claim_ref` and optionally a `police_report_ref`; the server copies `driver_id` from the event, stamps `submitted_at` with the logical clock, and starts the claim `SUBMITTED`. Submission is guarded on three axes: the event must be in `CONFIRMED` status and of type `COLLISION` (otherwise `ERR_CLAIM_REQUIRES_CONFIRMED_COLLISION`); the claim must be submitted no later than 30 days after the event's `confirmed_at`, with exactly 30 days admitted and anything later rejected as `ERR_EXONERATION_WINDOW_EXPIRED`; and no other non-`REJECTED` claim may already exist for the event (otherwise `ERR_DUPLICATE_CLAIM`).

A `ClaimsAdjuster` moves the claim `SUBMITTED` → `EVIDENCE_REVIEW` via begin-review, then decides it with a `decision` of `EXONERATE` or `REJECT` and a `rationale`, stamping `decided_at` and recording `decided_by`. Segregation of duties is enforced on the decision: the deciding adjuster's `X-User-ID` must differ from the `reviewer_id` on the review decision that last confirmed the event, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` — the person who confirmed the event may never be the person who exonerates it.

A decision of `EXONERATE` fires the full compensation cascade on the event: the event moves `CONFIRMED` → `EXONERATED` with `confirmed_at` reset to unset (if the event has since left `CONFIRMED`, the claim still decides `EXONERATED` but the event cascade is skipped); the driver's `confirmed_events_90d` and both score variants are recomputed with the exonerated event leaving the final input set; all coaching sessions tied to the event in `ASSIGNED`, `ACKNOWLEDGED`, or `OVERDUE` move to `CANCELLED`; and the escalation unwinding of Section 3.7 applies. A decision of `REJECT` moves the claim to `REJECTED` and leaves the event untouched. `EXONERATED` and `REJECTED` are terminal for the claim, and `EXONERATED` is terminal for the event.

### 3.9. Maintenance, Scoring, Snapshots, and Incentives

The platform recomputes derived state through an ops-run checkpoint: a `PlatformAdmin` invokes run-maintenance on a fleet, which increments the fleet's `ops_run_index` by one, sweeps coaching sessions, and refreshes derived score fields for all drivers of the fleet. The sweep examines the fleet's sessions in `ASSIGNED` or `ACKNOWLEDGED` whose `due_at` is strictly earlier than the logical clock — a session whose deadline equals the clock exactly is not yet overdue — and moves each to `OVERDUE`, processing them in `due_at` ascending order with ties broken by `created_at` ascending.

Driver safety scoring aggregates the driver's events over the rolling 90-day window ending at the logical clock (both ends inclusive), in two variants. For each event in the variant's input set, an age factor applies: 1.00 when the event occurred at most 30 days before the clock, 0.33 when it occurred more than 30 and at most 90 days before, events older than 90 days are excluded from the window entirely, and an event whose `occurred_at` lies after the logical clock contributes nothing. The raw penalty per event is the severity weight (1/3/6/10 for `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) multiplied by the penalty factor 2.5, multiplied by the age factor; each event's penalty is rounded half-up to two decimal places before any summation, and the rounded per-event penalties are then summed — rounding the unrounded sum instead is a rejected evaluation order. The driver score is 100 minus the total penalty, clamped to the range 0 through 100, and carried at exactly two decimal places. The two variants differ only in their input sets: `safety_score_provisional` includes events in `IN_REVIEW`, `CONFIRMED`, and `RECLASSIFIED`, serving the live operational view, the review queue, and projected incentive pricing; `safety_score_final` includes only `CONFIRMED` events and serves season close, finalized snapshots, the leaderboard, and payouts. `DETECTED`, `DISMISSED`, and `EXONERATED` events are excluded from both variants, so identical inputs always yield a final score greater than or equal to the provisional score. Both variants are computed on read and recomputed after every review action, every exoneration decision, and every clock movement observed via maintenance. The driver's `incentive_tier` derives from `safety_score_final` per the pricing table below.

Terminal and fleet scores aggregate upward. Driver, terminal, and fleet scores are returned as JSON numbers carrying exactly two decimal places. The terminal score is the mean of `safety_score_final` over the terminal's drivers in `ACTIVE`, `SUSPENDED`, or `COACHING_HOLD` status — `INACTIVE` drivers are excluded — rounded half-up to two decimal places, and a terminal with no such drivers scores 100.00. The fleet score is the mean of the terminal scores over terminals having at least one non-`INACTIVE` driver, rounded half-up to two decimal places, and a fleet with no such terminal scores 100.00.

A `FleetAdmin` freezes a score into a `SafetyScoreSnapshot` by requesting a computation with `scope_type` `DRIVER`, `TERMINAL`, or `FLEET`, a `period_start` and `period_end` (the end no earlier than the start), an optional `scope_id`, and an optional `finalize` flag that defaults to false when omitted. `scope_id` is a polymorphic reference, not a foreign key: it carries the driver's `id` for `DRIVER` scope, the terminal's `id` for `TERMINAL` scope, and is left unset for `FLEET` scope (any supplied value is discarded). For `DRIVER` or `TERMINAL` scope the referenced entity must exist, else `ERR_DRIVER_NOT_FOUND` or `ERR_TERMINAL_NOT_FOUND`; membership in the path fleet is not re-verified. Computation is blocked while the fleet is in `INCIDENT_LOCKDOWN` (`ERR_FLEET_LOCKED`). The snapshot row freezes the computed `score` at the logical clock instant `computed_at`: with `finalize` false the row is `PROVISIONAL` and prices off the provisional score variant; with `finalize` true the row is created directly in `FINAL` status pricing off the final variant. A snapshot never mutates its own `status` after creation. `rank` is null on creation except as assigned by the rank recompute below. Finalizing is what triggers the follow-ons below: award upsert and rank recompute run only for a DRIVER-scope snapshot computed with `finalize` true, with one exception — the award upsert also runs for a DRIVER-scope provisional computation, pricing the award off the provisional score.

Finalizing a driver-scope snapshot triggers two follow-ons. First, the platform upserts the driver's `IncentiveAward` for the period: creating one in `PROJECTED` status if none exists — or directly in `FORFEITED` status when the recomputed tier is `NONE` — or recomputing `amount_cents` and `tier` in place — and if the recomputed tier is `NONE`, the award moves `PROJECTED` → `FORFEITED` (the upsert reprices an award in any status, but only an award still in `PROJECTED` makes that transition; `FORFEITED` and `PAID` awards never return to `PROJECTED`). Award pricing reads the snapshot's `score` at exactly two decimal places: at least 95.00 earns `GOLD` (50000 cents), at least 90.00 earns `SILVER` (25000 cents), at least 80.00 earns `BRONZE` (10000 cents), and anything below 80.00 is `NONE` (0 cents); thresholds are inclusive, so 95.00 is `GOLD` while 94.99 is `SILVER`. The award records the pricing `snapshot_id` and copies `period_start` and `period_end` from the snapshot; because provisional snapshots price off the provisional score, the projected amount can differ from the final amount for identical period data. Second, the platform recomputes `rank` across all driver-scope `FINAL` snapshots of the same fleet and period: a snapshot's rank is 1 plus the number of candidates with a strictly higher `score`, or an equal `score` with fewer of their driver's confirmed events whose `occurred_at` falls inside the period (inclusive at both ends), or an equal score and equal event count whose driver was created earlier; a resource's `id` is never a tie-break input. Ranks are dense integers from 1, and snapshots that are not driver-scope `FINAL` carry no rank (their `rank` is null). The fleet's leaderboard returns its driver-scope `FINAL` snapshots for a requested `period_start` and `period_end`, ordered by `rank` ascending.

Awards are settled by a `FleetAdmin`. Approving a `PROJECTED` award requires its pricing snapshot to be in `FINAL` status (otherwise `ERR_SNAPSHOT_NOT_FINAL`) and its tier to be anything other than `NONE`; an attempt on a `NONE`-tier award fails state legality with `ERR_INVALID_STATE`. Paying an `APPROVED` award enforces the season budget: the sum of `amount_cents` over the fleet's awards in `APPROVED` or `PAID` status, after counting this payment, must not exceed the fleet's `incentive_budget_cents` — a total exactly equal to the budget is admitted, and an excess is rejected with `ERR_INCENTIVE_BUDGET_EXCEEDED`. `PAID` and `FORFEITED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource return HTTP 201 with the created resource; endpoints that modify an existing resource or perform a read return HTTP 200 with the affected resource (or resource list). Errors follow the Section 2.2 error envelope with the codes catalogued in Section 5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock to `to_iso8601`; initial value 2026-09-01T00:00:00Z | PlatformAdmin |
| POST | /api/fleets | Create a fleet (`posture` NORMAL, `ops_run_index` 0, `retention_used_mb` 0) | PlatformAdmin |
| GET | /api/fleets/{id} | Get a fleet | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/fleets/{id}/posture | Set fleet posture `NORMAL` or `INCIDENT_LOCKDOWN` | PlatformAdmin |
| GET | /api/fleets/{id}/leaderboard | Driver-scope FINAL snapshots for a period, ordered `rank` ascending | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/fleets/{id}/run-maintenance | Ops-run checkpoint: overdue sweep plus score recomputation; increments `ops_run_index` | PlatformAdmin |
| GET | /api/fleets/{id}/terminals | List terminals of a fleet | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/fleets/{id}/camera-policies | List camera policies of a fleet (filterable by `status`) | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/fleets/{id}/safety-events | Review queue: `upload_priority_score` desc, `occurred_at` asc, `created_at` asc; filterable | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/fleets/{id}/litigation-holds | List litigation holds of a fleet | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/fleets/{id}/score-snapshots | List score snapshots of a fleet | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/fleets/{id}/incentive-awards | List incentive awards of a fleet | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/fleets/{id}/score-snapshots/compute | Compute a DRIVER/TERMINAL/FLEET snapshot; `finalize` true creates FINAL and triggers award upsert and rank recompute | FleetAdmin |
| POST | /api/terminals | Create a terminal | PlatformAdmin |
| GET | /api/terminals/{id} | Get a terminal | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/terminals/{id}/drivers | List drivers of a terminal | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/terminals/{id}/vehicles | List vehicles of a terminal | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/terminals/{id}/union-agreements | List union agreements of a terminal | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/union-agreements | Create a union agreement in DRAFT | PlatformAdmin |
| GET | /api/union-agreements/{id} | Get a union agreement | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/union-agreements/{id}/ratify | Ratify a DRAFT agreement; closed-window overlap with other RATIFIED agreements of the terminal is rejected | PlatformAdmin |
| POST | /api/union-agreements/{id}/expire | Expire a RATIFIED agreement | PlatformAdmin |
| POST | /api/drivers | Create a driver (ACTIVE) | PlatformAdmin |
| GET | /api/drivers/{id} | Get a driver, including computed score fields and `confirmed_events_90d` | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/drivers/{id}/status | Manual driver status change; `to_status` one of ACTIVE/SUSPENDED/INACTIVE (COACHING_HOLD is system-only) | SafetyManager |
| GET | /api/drivers/{id}/safety-events | List a driver's safety events | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/drivers/{id}/coaching-sessions | List a driver's coaching sessions | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/drivers/{id}/coaching-sessions | Manually assign a coaching session for a CONFIRMED event; half-open window overlap rejected | SafetyManager |
| GET | /api/drivers/{id}/escalation-cases | List a driver's escalation cases | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/drivers/{id}/exoneration-claims | List a driver's exoneration claims | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/drivers/{id}/litigation-holds | List litigation holds covering a driver | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/drivers/{id}/incentive-awards | List a driver's incentive awards | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/drivers/{id}/score-snapshots | List DRIVER-scope snapshots for a driver | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/vehicles | Create a vehicle (ACTIVE) | PlatformAdmin |
| GET | /api/vehicles/{id} | Get a vehicle | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/vehicles/{id}/decommission | Decommission a vehicle with no DETECTED/IN_REVIEW events | PlatformAdmin |
| GET | /api/vehicles/{id}/safety-events | List a vehicle's safety events | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/camera-policies | Create a camera policy in DRAFT | PlatformAdmin |
| GET | /api/camera-policies/{id} | Get a camera policy | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| PATCH | /api/camera-policies/{id} | Update a DRAFT policy's fields; OCC on `expected_policy_version` | PlatformAdmin |
| POST | /api/camera-policies/{id}/activate | Activate a DRAFT policy; the fleet's previously ACTIVE policy auto-archives | PlatformAdmin |
| POST | /api/camera-policies/{id}/archive | Archive a DRAFT policy; archiving the ACTIVE policy is rejected | PlatformAdmin |
| POST | /api/safety-events | Ingest a detected safety event; computes `upload_priority_score`; status DETECTED | TelematicsIngest |
| GET | /api/safety-events/{id} | Get a safety event | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/safety-events/{id}/review | Review action CONFIRM/DISMISS/RECLASSIFY/REOPEN; OCC on `expected_event_version`; appends a ReviewDecision | SafetyManager |
| GET | /api/safety-events/{id}/footage-clips | List an event's footage clips | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/safety-events/{id}/review-decisions | Append-only decision log of an event, chronological by `decided_at` | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/safety-events/{id}/coaching-sessions | List coaching sessions tied to an event | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/safety-events/{id}/escalation-cases | List escalation cases triggered by an event | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/safety-events/{id}/exoneration-claims | Driver submits an exoneration claim for their own CONFIRMED COLLISION event within 30 days of confirmation | Driver |
| GET | /api/safety-events/{id}/exoneration-claims | List an event's exoneration claims | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/safety-events/{id}/litigation-holds | List litigation holds covering an event | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/footage-clips | Register a footage clip (QUEUED); INWARD angle passes the privacy gate; `retention_class` initialized from event type | TelematicsIngest |
| GET | /api/footage-clips/{id} | Get a footage clip (both parallel state dimensions) | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/footage-clips/{id}/upload-begin | QUEUED to UPLOADING | TelematicsIngest |
| POST | /api/footage-clips/{id}/upload-complete | UPLOADING to UPLOADED; enforces the daily upload cap; bubbles the event DETECTED to IN_REVIEW on first clip | TelematicsIngest |
| POST | /api/footage-clips/{id}/purge | UPLOADED to PURGED after retention expiry; blocked under an ACTIVE covering litigation hold | SafetyManager |
| GET | /api/coaching-sessions/{id} | Get a coaching session | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/coaching-sessions/{id}/acknowledge | Driver acknowledges own session (ASSIGNED to ACKNOWLEDGED) | Driver |
| POST | /api/coaching-sessions/{id}/complete | Complete an ACKNOWLEDGED session with outcome PASS/FAIL; blocked during INCIDENT_LOCKDOWN | SafetyManager |
| POST | /api/coaching-sessions/{id}/reassign | OVERDUE to ASSIGNED with a fresh non-overlapping window | SafetyManager |
| POST | /api/coaching-sessions/{id}/cancel | Cancel an ASSIGNED or OVERDUE session | SafetyManager |
| GET | /api/escalation-cases/{id} | Get an escalation case | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/escalation-cases/{id}/review | OPEN to UNDER_REVIEW | SafetyManager |
| POST | /api/escalation-cases/{id}/send-back | UNDER_REVIEW to OPEN | SafetyManager |
| POST | /api/escalation-cases/{id}/resolve | UNDER_REVIEW to RESOLVED_ACTION or RESOLVED_NO_ACTION with driver status side effects | SafetyManager |
| GET | /api/exoneration-claims/{id} | Get an exoneration claim | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/exoneration-claims/{id}/begin-review | SUBMITTED to EVIDENCE_REVIEW | ClaimsAdjuster |
| POST | /api/exoneration-claims/{id}/decide | EVIDENCE_REVIEW to EXONERATED or REJECTED; segregation of duties against the confirming reviewer | ClaimsAdjuster |
| POST | /api/litigation-holds | Place a litigation hold (scope DRIVER or EVENT); one ACTIVE hold per driver and per event | SafetyManager |
| GET | /api/litigation-holds/{id} | Get a litigation hold | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/litigation-holds/{id}/release | ACTIVE to RELEASED; covered clips revert to their deterministic retention class | SafetyManager |
| GET | /api/score-snapshots/{id} | Get a score snapshot | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/score-snapshots/{id}/incentive-awards | List awards priced from a snapshot | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| GET | /api/incentive-awards/{id} | Get an incentive award | PlatformAdmin, SafetyManager, ClaimsAdjuster, Driver, TelematicsIngest, FleetAdmin |
| POST | /api/incentive-awards/{id}/approve | PROJECTED to APPROVED; requires a FINAL snapshot and a tier other than NONE | FleetAdmin |
| POST | /api/incentive-awards/{id}/pay | APPROVED to PAID; enforces the fleet incentive budget | FleetAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_FLEET_NOT_FOUND | 404 |
| ERR_TERMINAL_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_DRIVER_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_POLICY_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_CLIP_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_HOLD_NOT_FOUND | 404 |
| ERR_SNAPSHOT_NOT_FOUND | 404 |
| ERR_AWARD_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_EVENT_VERSION | 412 |
| ERR_STALE_POLICY_VERSION | 412 |
| ERR_EVENT_IN_FUTURE | 422 |
| ERR_EVENT_TYPE_DISABLED | 422 |
| ERR_INWARD_FOOTAGE_RESTRICTED | 422 |
| ERR_LITIGATION_HOLD_ACTIVE | 409 |
| ERR_ACTIVE_HOLD_EXISTS | 409 |
| ERR_EXONERATION_WINDOW_EXPIRED | 422 |
| ERR_SESSION_WINDOW_OVERLAP | 409 |
| ERR_AGREEMENT_WINDOW_OVERLAP | 409 |
| ERR_DAILY_UPLOAD_CAP_EXCEEDED | 422 |
| ERR_ACTIVE_POLICY_REQUIRED | 409 |
| ERR_POLICY_IN_USE | 409 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_DUPLICATE_CLAIM | 409 |
| ERR_DRIVER_NOT_ACTIVE | 409 |
| ERR_FLEET_LOCKED | 409 |
| ERR_EVENT_NOT_CONFIRMED | 409 |
| ERR_CLAIM_REQUIRES_CONFIRMED_COLLISION | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_SNAPSHOT_NOT_FINAL | 409 |
| ERR_INCENTIVE_BUDGET_EXCEEDED | 402 |
| ERR_RETENTION_NOT_EXPIRED | 409 |
