# Veteran Disaster Response API — Product Requirements Document

## 1. Introduction

When a hurricane makes landfall or a flood inundates a county, the difference between a chaotic volunteer turnout and an effective relief effort is coordination discipline. This document specifies the Veteran Volunteer Disaster Response API, the readiness and deployment backbone for a veteran-led disaster response organization in the mold of Team Rubicon. The platform maintains a roster of volunteers — their skills, certifications, and deployment availability — and drives the full arc of a response: an incident is reported, assessed, and typed; operations are planned against that typing with a required team size, duration, and capability set; volunteers are called up, travel to the affected region, lodge in forward operating bases, and rotate through duty shifts; work orders flow in from homeowners and municipalities and are prioritized so that vulnerable residents are served first; and when the operation winds down, the system accounts for stipends, lodging costs, volunteer fatigue, wellness follow-up, and after-action review.

Two principles shape every workflow below. First, **safety is credentialed, not asserted**: chainsaw, heavy-equipment, structural, and medical work is gated on verified certifications, and losing a credential mid-operation has immediate, cascading consequences for deployments and work orders alike. Second, **people are a finite, fatiguing resource**: readiness is scored, fatigue accumulates with every completed shift, rest buffers separate deployments, and demobilization can automatically raise a wellness check. The API is mounted under `/vdr` and is consumed by command staff, operations leads, safety officers, intake coordinators, partner-agency liaisons, training directors, and the volunteers themselves.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is restricted by role; an attempt to perform an action outside the acting role's granted set, or one that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `SystemAdmin`, `IncidentCommander`, `OperationsLead`, `SafetyOfficer`, `IntakeCoordinator`, `PartnerLiaison`, `TrainingDirector`, and `Volunteer`.

- A `SystemAdmin` is the platform operator: registers volunteers and partner agencies, and exclusively drives the logical clock and the ops-run housekeeping epochs.
- An `IncidentCommander` owns the incident lifecycle — report, assess, type, stand down, close — creates operations under typed incidents, and adopts after-action reviews (but may never submit them).
- An `OperationsLead` runs operations day to day: opens, musters, activates, demobilizes, and retypes operations; offers deployments; checks volunteers in and demobilizes them; establishes forward operating bases; schedules duty shifts; works work orders in the field; and submits after-action reviews (but may never adopt them).
- A `SafetyOfficer` is the credentialing and wellness authority: vets volunteers and manages readiness transitions, verifies, rejects, revokes, and renews certifications, clears safety holds, and resolves wellness checks.
- An `IntakeCoordinator` staffs the work-order desk: direct intake, triage, scheduling to operations, final verification, and cancellation.
- A `PartnerLiaison` is an external partner coordinator — emergency management, nonprofit, or long-term recovery group — who refers work orders on behalf of their agency.
- A `TrainingDirector` owns the training pipeline: creates courses, enrolls volunteers, records certifications, and marks completions.
- A `Volunteer` is a rostered disaster-response volunteer who manages their own availability, accepts or declines their own deployment offers, and drops their own training enrollments.

**Identity semantics.** For six of the eight roles — `SystemAdmin`, `IncidentCommander`, `OperationsLead`, `SafetyOfficer`, `IntakeCoordinator`, and `TrainingDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `verified_by_user_id` on a `Certification` when a `SafetyOfficer` verifies a credential) but never compares it to any entity's `id`. When `X-User-Role` is `PartnerLiaison`, `X-User-ID` is the `id` of the acting `PartnerAgency`; a liaison creating a work order must set `source_partner_id` equal to their own `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a volunteer — a deployment offer, a volunteer record's `availability_windows`, a training enrollment — compare the resource's volunteer foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Ops-Run Epoch

Every time-dependent behavior in this system — certification expiry, offer expiry, no-show detection, shift completion, fatigue reset, waitlist promotion — is evaluated against a server-maintained **logical clock**, referred to throughout as `current_utc`. The logical clock never reads wall-clock time. At server startup, before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must not fall back to wall-clock time under any circumstance.

A `SystemAdmin` advances the logical clock by submitting a `to_iso8601` instant through the admin-only clock-setting capability. Advancing the clock mutates nothing by itself: no certification expires, no offer lapses, and no shift completes until a housekeeping epoch is executed. The response carries the new `current_utc`.

The **ops run** is the second admin-only test-driving capability: one housekeeping epoch that applies six sweeps in a fixed, listed order. First, every `Certification` in `VERIFIED` status whose `expires_at` is strictly earlier than `current_utc` flips to `EXPIRED` — a certification remains `VERIFIED` while `current_utc` is less than or equal to `expires_at` and expires only once `current_utc` is strictly greater. Second, any volunteer left holding zero `VERIFIED` certifications by that sweep, and whose `readiness_status` is `DEPLOYABLE`, is automatically downgraded to `VETTED`. Third, every `OFFERED` deployment older than 48 hours without a response — that is, whose `created_at` lies more than `CALL_UP_RESPONSE_HOURS` (48 hours) in the past — flips to `EXPIRED`. Fourth, every deployment still `ACCEPTED` once `current_utc` has passed the operation's `start_date` by more than the 24-hour no-show grace (`NO_SHOW_GRACE_HOURS`) flips to `NO_SHOW`. Fifth, every `SCHEDULED` duty shift whose `ends_at` has been reached or passed is completed, accruing fatigue hours to its volunteer, after which the fatigue reset is evaluated for each volunteer. Sixth, waitlisted training enrollments are promoted into free seats in `created_at` ascending order. The epoch's response reports how many records each sweep touched: `certs_expired`, `offers_expired`, `no_shows`, `shifts_completed`, `fatigue_resets`, `enrollments_promoted`, and `volunteers_downgraded`. Every entity mutated by an ops run has its `version` incremented and its `updated_at` refreshed, exactly as if a client had written it.

### 2.5. Common Resource Properties

All twelve primary resources — `Volunteer`, `Certification`, `Incident`, `Operation`, `Deployment`, `FobSite`, `DutyShift`, `WorkOrder`, `PartnerAgency`, `TrainingCourse`, `TrainingEnrollment`, and `WellnessCheck` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Recomputing a derived field — a readiness score, a rostered count, a capability gap, an occupancy counter, a lodging ledger — is a mutation like any other: it refreshes `updated_at` and increments `version` on the owning entity. Cascading transitions (for example, a certification revocation that pushes deployments into `SAFETY_HOLD`) mutate every entity they touch under the same rule.

Lifecycle-gated fields share one convention: a field that acquires meaning only at a specific transition is null until that transition occurs. This covers `severity`, `affected_households`, and `incident_type` on an incident; `fob_site_id`, `checked_in_at`, `demobed_at`, and `stipend_final_cents` on a deployment; `priority_score` and `priority_tier` on a work order; `aar_notes` on an operation; `resolved_notes` on a wellness check; `waitlist_position` on an enrollment; `verified_by_user_id` on a certification; and a work order's `operation_id` before scheduling. Counters and accumulators — `renewal_count`, `rostered_count`, `seats_taken`, `bunks_occupied`, `lodging_cost_cents`, and the two readiness scores together with `fatigue_hours` — all start at 0 on a newly created resource.

### 2.6. Nested Resource Resolution and Validation Ordering

The API enforces strict, hierarchical validation for every request that targets nested resources. When an endpoint path contains multiple resource identifiers, the system validates each identifier in sequential, left-to-right order: volunteer before certification; incident before operation, and operation before deployment, forward operating base, or duty shift; work order; training course before enrollment; wellness check. The request is rejected immediately with a `404 Not Found` carrying the per-entity error of the *first* path segment that does not resolve: `ERR_VOLUNTEER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_OPERATION_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_FOB_SITE_NOT_FOUND`, `ERR_DUTY_SHIFT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_TRAINING_COURSE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, or `ERR_WELLNESS_CHECK_NOT_FOUND`. The same per-entity errors apply when a request body references a nonexistent entity, such as a `volunteer_id` or `operation_id` that does not resolve.

When a single request violates several rules, exactly one error is returned, chosen by a fixed validation priority — lower priority numbers win. The ordering is:

1. **Schema validation.** The request body must be well-formed: required fields present, types correct, enum members valid, `planned_end` strictly after `planned_start`, `ends_at` strictly after `starts_at`, and no unknown fields. Violations are rejected with `ERR_VALIDATION` (HTTP 400).
2. **Authentication.** `X-User-ID` and `X-User-Role` must be present and well-formed, else `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Authorization and ownership.** The acting role must be listed for the endpoint, and entity-backed ownership checks must pass — a `Volunteer` acting on their own record, enrollment, or deployment; a `PartnerLiaison` setting `source_partner_id` to their own agency; an after-action review submitter may not adopt it. Violations are rejected with `ERR_UNAUTHORIZED` (HTTP 403).
4. **Existence.** Path and body identifiers must resolve, per the left-to-right rule above, with the appropriate `404` error.
5. **Optimistic concurrency.** On the two version-guarded writes, `expected_operation_version` or `expected_work_order_version` must match the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **State legality.** The target entity must be in a from-state for the requested transition; repeated transitions and transitions out of terminal states are rejected with `ERR_INVALID_STATE` (HTTP 409).
7. **Business rules.** Domain rules follow in their own pinned order, detailed in §3: credential and readiness safety gates first, then instructor eligibility, then temporal rules (availability containment, rest buffer, shift overlap), then capacity and coverage constraints (fatigue cap, capability coverage, hazard alignment, offer ceiling, duplicate enrollment), then referential gates (operation state, incident typing, wind-down gates), and finally lodging capacity.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Re-typing an operation requires the request to carry `expected_operation_version`, holding the `version` of the `Operation` the client last observed. If the operation's version has advanced since that observation — because another writer has already applied a typing change — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a stale view from silently overwriting a typing the client never saw. Typing determines `team_size_required`, `duration_days`, and `required_capabilities`, so an unobserved rewrite would corrupt every downstream gate. Triaging a work order works the same way: the request must carry `expected_work_order_version` matching the work order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A second triage legitimately supersedes an earlier priority verdict, so the version check is what tells the client a superseding triage already landed. No other endpoint accepts or requires a version field.

### 2.8. Precision, Rounding, and Monetary Conventions

All monetary amounts in this system are integer counts of cents — stipends, travel allowances, nightly bunk rates, and lodging ledgers alike. Stipend arithmetic is exact integer arithmetic and requires no rounding. The forward-operating-base lodging ledger is the one place rounding occurs, and its order is pinned: each night's charge is rounded half up to integer cents first, and only then are the per-night charges summed into the stay cost. Summing unrounded charges and rounding once at the end yields different cents and is forbidden. Readiness scores, priority scores, and fatigue figures are all integer quantities; where a duration or count must be derived from a finer-grained quantity, the derivation is stated alongside the rule that uses it.

### 2.9. Readiness, Fatigue, and Wellness Doctrine

Volunteer readiness is tracked as two scores computed from the same inputs but answering different questions. The **operational readiness** score, `operational_readiness_score`, is a pure credentialing view: a volunteer holding no `VERIFIED` certification scores 0; otherwise the score is a base of 10 points plus a per-kind weight for each distinct certification kind the volunteer currently holds in `VERIFIED` status — 30 for `CHAINSAW`, 25 for `HEAVY_EQUIPMENT`, 25 for `STRUCTURAL`, and 20 for `MEDICAL`. Certifications in `PENDING_VERIFICATION`, `EXPIRED`, `REVOKED`, or `REJECTED` status contribute nothing. The **wellness-adjusted** score, `readiness_score`, starts from the same operational figure and subtracts a fatigue penalty of 2 points per accumulated `fatigue_hours`, floored at 0 so the score can never go negative. The two scores therefore agree exactly when a volunteer carries no fatigue, and diverge whenever they do. Both are recomputed whenever a certification of the volunteer is verified, expires, is revoked, or is renewed; whenever the volunteer's readiness transitions into `DEPLOYABLE`; and whenever `fatigue_hours` changes.

Fatigue is the counterweight. Every completed duty shift adds its duration in hours to the volunteer's `fatigue_hours`, and a volunteer who has had no on-duty shift for at least 24 hours — `REST_RESET_HOURS` — has `fatigue_hours` reset to 0 at the next ops run, provided no shift is currently in progress. Fatigue is not merely advisory: it feeds the wellness-adjusted score, it caps further shift scheduling, and it is one of the two triggers that raise an automatic wellness check at demobilization.

### 2.10. Capability Governance and Hazard Typing

Operational safety rests on a pinned mapping from hazard work to the certification kind that authorizes it. `TREE_REMOVAL` work requires `CHAINSAW`; `DEBRIS` work requires `HEAVY_EQUIPMENT`; both `STRUCTURAL` and `TARPING` work require `STRUCTURAL`; and `MUCK_OUT` maps to no capability at all, which exempts it from capability-coverage checks. Only certifications in `VERIFIED` status confer capability. An operation declares the capabilities its roster must cover through `required_capabilities`, a non-empty subset of the four certifiable kinds, and the system continuously tracks the operation's `capability_gap`: for each required capability, the shortfall is 1 minus the number of rostered volunteers holding a `VERIFIED` certification of that kind, clamped so it never goes below zero, with zero-shortfall entries omitted from the map entirely. A non-empty `capability_gap` blocks mustering, blocks work-order scheduling and unblocking for the affected hazard, and is the mechanism by which a mid-operation credential loss propagates into blocked field work.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Registration, Vetting, and Credentialing

A volunteer's journey begins when a `SystemAdmin` registers them with their `full_name`, `email`, `home_region` (a region code such as TX-GULF), and `skills` — a set of skill tags drawn from `CHAINSAW`, `HEAVY_EQUIPMENT`, `STRUCTURAL`, `MEDICAL`, `LOGISTICS`, and `DEBRIS`. Registration may also carry `availability_windows`, a list of deployment availability intervals each described by a `start_iso8601` and an `end_iso8601` treated as a closed interval, and `instructor_certified`, a flag defaulting to false that marks whether the volunteer may lead training courses; an empty availability list is the default when none is supplied. The `email` must be unique across all volunteers. A freshly registered volunteer has `readiness_status` `REGISTERED`, both readiness scores at 0, and `fatigue_hours` at 0.

From `REGISTERED`, a `SafetyOfficer` moves the volunteer to `VETTED` once the record is complete — `full_name`, `email`, `home_region`, and at least one skill present. The decisive step is `VETTED` to `DEPLOYABLE`, which the same officer may take only once the volunteer holds at least one certification in `VERIFIED` status (`MIN_VERIFIED_CERTS_FOR_DEPLOYABLE` is 1); crossing into `DEPLOYABLE` recomputes both readiness scores. A deployable volunteer can be suspended at any time — `DEPLOYABLE` to `SUSPENDED` carries no precondition — and a suspended volunteer is ineligible for new deployment offers for as long as the suspension stands. Reinstatement from `SUSPENDED` back to `DEPLOYABLE` is gated twice over: the volunteer must again hold at least one `VERIFIED` certification, and there must be no `OPEN` wellness check attached to any of the volunteer's deployments — an unresolved check surfaces as `ERR_OPEN_WELLNESS_CHECKS` (HTTP 409). Reinstatement likewise recomputes both scores. A volunteer in `VETTED` or `SUSPENDED` may be moved to the terminal `INACTIVE` state, but only while they hold no deployment in `OFFERED`, `ACCEPTED`, `ON_SITE`, or `SAFETY_HOLD`. Separately from these officer-driven transitions, a `Volunteer` acting on their own record may update only their `availability_windows`; every readiness transition is the `SafetyOfficer`'s alone.

Certifications are the substance behind readiness. A `TrainingDirector` records a credential for a volunteer with its `kind` — one of `CHAINSAW`, `HEAVY_EQUIPMENT`, `STRUCTURAL`, or `MEDICAL` — plus `issued_at` and `expires_at`; it lands in `PENDING_VERIFICATION`. A `SafetyOfficer` then disposes of it. Verification moves `PENDING_VERIFICATION` to `VERIFIED` and is refused when the credential is already past its `expires_at` at the acting moment; a successful verification stamps `verified_by_user_id` with the acting officer's `X-User-ID` and recomputes the owner's readiness scores. Rejection moves the credential to the terminal `REJECTED` state with no further ceremony. Expiry is never client-driven: the ops run flips `VERIFIED` to `EXPIRED` once `current_utc` is strictly greater than `expires_at`, recomputes the owner's scores, and — when that expiry leaves the owner with zero `VERIFIED` certifications while `readiness_status` is `DEPLOYABLE` — automatically downgrades the volunteer to `VETTED`. An `EXPIRED` credential is not dead: the officer may renew it back to `VERIFIED` by supplying a new `expires_at` strictly later than `current_utc`, which increments `renewal_count` by 1, replaces `expires_at`, restamps `verified_by_user_id`, and recomputes the owner's scores.

Revocation is the dangerous transition, and its blast radius is deliberate. When a `SafetyOfficer` moves a `VERIFIED` certification to the terminal `REVOKED` state, the cascade runs in hops. First, every deployment of the credential's owner that is currently `ON_SITE`, serving an operation whose `required_capabilities` contains the revoked kind, and for which the owner holds no other `VERIFIED` certification of that kind, is moved to `SAFETY_HOLD`. Second, for each operation touched by the first hop, the `capability_gap` is recomputed, and if the gap for the affected kind is now positive, every work order of that operation that is `IN_PROGRESS` and whose `hazard_kind` maps to that capability is moved to `BLOCKED` with `blocked_reason` set to `CAPABILITY_LOST`. Finally, the owner's readiness scores are recomputed. A single revoked chainsaw card can therefore sideline a volunteer, open a capability gap, and halt tree-removal work in one motion.

### 3.2. From Disaster Report to Typed Incident

An incident enters the system when an `IncidentCommander` reports it with a `name` (for example, Hurricane Helena) and the affected `region`. It lands in `REPORTED` with `reported_at` stamped by the server, and with `severity`, `affected_households`, and `incident_type` all still null. Assessment is the first judgment call: moving `REPORTED` to `ASSESSED` requires the request to carry a `severity` between 1 and 5 inclusive and an `affected_households` count of zero or more, and both values are recorded on the incident at that moment. Typing follows: moving `ASSESSED` to `TYPED` requires a valid `incident_type` — `WIND`, `FLOOD`, `FIRE`, or `EARTHQUAKE` — which is likewise recorded at transition time. An incident that proves to be a false alarm or is otherwise abandoned may be cancelled from either `REPORTED` or `ASSESSED`, landing in the terminal `CANCELLED` state with no preconditions. Once an incident is `TYPED`, however, it can only leave through the stand-down and closure path described in §3.8 — typing is the point of commitment, because only a `TYPED` incident may host operations.

### 3.3. Standing Up and Steering an Operation

An `IncidentCommander` creates an operation under a `TYPED` incident — attempting it under any other incident status is rejected with `ERR_INCIDENT_NOT_TYPED` (HTTP 409) — and the new operation permanently records the incident it serves in its `incident_id`. The creation payload fixes the plan of record: a `title`, a `hazard_focus` drawn from `TREE_REMOVAL`, `MUCK_OUT`, `TARPING`, `DEBRIS`, and `STRUCTURAL`; a `team_size_required` of at least 2 and at most 40 (`MAX_TEAM_SIZE`); a `duration_days` of at least 1 and at most 30 (`MAX_OPERATION_DURATION_DAYS`); the `required_capabilities` the roster must cover; and the planned `start_date` as an ISO calendar date. A new operation stands in `DRAFT` with `aar_status` `NONE`, `rostered_count` 0, and an empty `capability_gap` until volunteers are rostered against it.

The operation's `status` ladder is climbed by the `OperationsLead`. `DRAFT` to `OPEN` is permitted only while the parent incident is `TYPED`. `OPEN` to `MUSTERED` is the readiness gate for the whole plan: the `rostered_count` must equal `team_size_required` exactly — not merely reach it — and the `capability_gap` must be empty, meaning every required capability is covered by at least one rostered volunteer holding a `VERIFIED` certification of that kind; a gap surfaces as `ERR_CAPABILITY_GAP` (HTTP 422). `MUSTERED` to `ACTIVE` requires that at least one deployment of the operation has actually reached `ON_SITE`. Two counters keep these gates honest. `rostered_count` counts the operation's deployments in `ACCEPTED` or `ON_SITE` — `SAFETY_HOLD` is deliberately excluded. The `capability_gap` recomputation, which runs on every deployment status change of the operation and on the certification-revocation cascade, counts coverage over that same rostered set. Both are recomputed as side effects wherever the narrative below says so, and each recomputation is a mutation of the operation.

Plans change, and retyping is how they change safely. An `OperationsLead` may re-type an operation while it is in `DRAFT` or `OPEN`, replacing `team_size_required`, `duration_days`, and `required_capabilities` in one write and recomputing the `capability_gap` against the new requirements. Because typing drives every downstream rostering gate, this write is OCC-guarded exactly as §2.7 describes: it requires `expected_operation_version`, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful retype increments the operation's `version` by 1. Once an operation has reached `MUSTERED` it can no longer be retyped — a retype attempted against such an operation is an invalid transition and is rejected with `ERR_INVALID_STATE` (HTTP 409).

The remaining rungs of the ladder — demobilization, completion, and cancellation — belong to the wind-down narrative of §3.8, where the after-action review dimension that gates completion is also introduced.

### 3.4. Call-Up: The Deployment Journey from Offer to Demobilization

When an operation is `OPEN`, an `OperationsLead` issues call-up offers, one deployment per volunteer, naming the `volunteer_id`, the `travel_mode` (`SELF` or `TEAM_TRANSPORT`), the planned window as `planned_start` and `planned_end` (the end must be strictly after the start), and optionally `needs_lodging`, which defaults to true and records whether a bunk is required at check-in. Offering against an operation that is not `OPEN` is rejected with `ERR_OPERATION_NOT_OPEN` (HTTP 409). Two business gates apply at offer time, evaluated after the schema, auth, existence, and state checks of §2.6: the readiness gate fires first, rejecting with `ERR_VOLUNTEER_NOT_DEPLOYABLE` (HTTP 409) unless the volunteer's `readiness_status` is `DEPLOYABLE`, and the offer ceiling fires second, rejecting with `ERR_TEAM_SIZE_EXCEEDED` (HTTP 422) when the operation's active offers — deployments in `OFFERED`, `ACCEPTED`, `ON_SITE`, or `SAFETY_HOLD` — already number `team_size_required`, so that the offer that would exceed the ceiling is the one refused. A created offer stands in `OFFERED`.

Answering an offer belongs to the volunteer alone: the acting `X-User-ID` must equal the deployment's `volunteer_id`, or the request fails authorization. Declining moves `OFFERED` to the terminal `DECLINED` state with no further conditions. Accepting — `OFFERED` to `ACCEPTED` — is the most heavily gated transition in the system, and its checks run in a fixed order. After the generic schema, auth, existence, and state checks, the safety-credential gate requires the volunteer to hold at least one `VERIFIED` certification whose kind appears in the operation's `required_capabilities`, else `ERR_CERT_NOT_VERIFIED` (HTTP 422). Next the readiness gate requires `readiness_status` `DEPLOYABLE`, else `ERR_VOLUNTEER_NOT_DEPLOYABLE`. Next, availability containment: the interval from `planned_start` to `planned_end` must lie entirely inside a single entry of the volunteer's `availability_windows`, else `ERR_AVAILABILITY_WINDOW_MISMATCH` (HTTP 422). Then the rest buffer: no other deployment of the same volunteer in `ACCEPTED`, `ON_SITE`, `SAFETY_HOLD`, or `DEMOBED` may have its window ending within 24 hours (`REST_BUFFER_HOURS`) before the new `planned_start` — a gap of at least 24 hours is required, and a gap of exactly 24 hours is admissible — else `ERR_DEPLOYMENT_WINDOW_CONFLICT` (HTTP 409). Finally, the operation-state gate requires the operation to be in `OPEN` or `MUSTERED`, else `ERR_OPERATION_NOT_OPEN`. A successful acceptance computes `stipend_provisional_cents` and recomputes the operation's `rostered_count` and `capability_gap`.

An offer left unanswered does not linger: at an ops run, any `OFFERED` deployment whose `created_at` lies more than 48 hours in the past flips to the terminal `EXPIRED` state.

Check-in turns an accepted volunteer into a presence on the ground. An `OperationsLead` moves `ACCEPTED` to `ON_SITE`, which stamps `checked_in_at` with `current_utc`. When the deployment's `needs_lodging` is true, a bunk must exist: some forward operating base of the operation must have `bunks_occupied` strictly less than `bunks_total` — a base at exactly full capacity admits no one, while one short by exactly one bunk admits exactly one more arrival — and if every base is full the check-in is rejected with `ERR_FOB_CAPACITY_EXCEEDED` (HTTP 422). The bunk is allocated from the base with the most free bunks, ties broken by the earliest `created_at`; the deployment's `fob_site_id` is set to that base and its `bunks_occupied` increases by 1. Check-in then recomputes the operation's `rostered_count` and `capability_gap`. A volunteer who never shows is caught by the ops run: a deployment still `ACCEPTED` once `current_utc` has passed the operation's `start_date` by more than the 24-hour grace flips to the terminal `NO_SHOW` state, with the operation's counters recomputed.

Two detours exist off the happy path. The certification-revocation cascade of §3.1 can push an `ON_SITE` deployment into `SAFETY_HOLD`, and a deployment on hold is excluded from new duty-shift scheduling until cleared. A `SafetyOfficer` clears the hold — `SAFETY_HOLD` back to `ON_SITE` — once the volunteer again holds `VERIFIED` certifications covering all of the operation's `required_capabilities`, recomputing the operation's `capability_gap`.

Demobilization ends the journey. An `OperationsLead` moves a deployment from `ON_SITE` or `SAFETY_HOLD` to the terminal `DEMOBED` state — the stand-down cascade of §3.8 can drive the same transition — provided no duty shift of the deployment is still `SCHEDULED` with an `ends_at` in the future. Demobilization is a bundle of side effects: `demobed_at` is stamped with `current_utc` and `duty_status` returns to `RESTING`; if a bunk was held, the base's `bunks_occupied` decreases by 1 and the stay is finalized into the base's `lodging_cost_cents`; `stipend_final_cents` is computed; any duty shifts of the deployment still `SCHEDULED` are moved to `CANCELLED`; and the wellness screen runs — if the volunteer's `fatigue_hours` has reached 30 (`WELLNESS_FATIGUE_THRESHOLD_HOURS`) or the actual on-site stay spans at least 10 days (`WELLNESS_LONG_DEPLOYMENT_DAYS`), an `OPEN` `WellnessCheck` is created for the deployment with `reason` `FATIGUE_THRESHOLD` or `LONG_DEPLOYMENT` respectively. The operation's `rostered_count` and `capability_gap` are recomputed last.

**The stipend** is computed twice, by the same pinned recipe with a different day count, which is why the provisional and final figures differ whenever actual days on site differ from the plan. The recipe's evaluation order is fixed: first determine the day count; then the per-diem subtotal is the day count multiplied by the daily per-diem of 6500 cents (`PER_DIEM_DAILY_CENTS`); then the travel tier is `LONG` when the per-diem subtotal reaches 200000 cents (`TRAVEL_TIER_THRESHOLD_CENTS`) and `SHORT` below it — the tier is keyed on the per-diem subtotal alone, which resolves the apparent circularity between tier and total; then the travel allowance is 45000 cents (`TRAVEL_TIER_LONG_CENTS`) for the long tier or 15000 cents (`TRAVEL_TIER_SHORT_CENTS`) for the short; finally the stipend is the per-diem subtotal plus the travel allowance, an exact integer number of cents. The **provisional** variant, computed at acceptance and stored in `stipend_provisional_cents`, takes its day count from the operation's `duration_days` — the forward-looking plan. The **final** variant, computed at demobilization and stored in `stipend_final_cents`, takes its day count from the chronological actuals: the elapsed time from `checked_in_at` to `demobed_at`, divided by 24 hours and rounded up to a whole day, with a minimum of 1 day.

**The lodging ledger** follows its own pinned rounding order. The stay length in nights is the count of UTC calendar dates from the date of `checked_in_at` inclusive to the date of `demobed_at` exclusive, with a minimum of 1 night. Each night's charge is the base's `nightly_rate_cents` increased by the 7% utility surcharge (`FOB_UTILITY_SURCHARGE_PCT` of 0.07), and that product is rounded half up to integer cents per night first. The stay cost is then the night count multiplied by that per-night integer charge, and the stay cost is added into the base's `lodging_cost_cents`. Rounding only a grand total at the end is forbidden — the per-night rounding is the contract.

### 3.5. Duty Rotation and Fatigue Accounting

Once volunteers are on site, an `OperationsLead` schedules duty shifts against individual deployments, naming the `deployment_id`, the shift `kind` — `OPERATIONS`, `SAFETY_WATCH`, or `LOGISTICS` — and the half-open interval from `starts_at` to `ends_at`. The end must be strictly after the start, and a single shift may not exceed 12 hours (`MAX_SHIFT_HOURS`). The target deployment must be `ON_SITE`; a deployment on `SAFETY_HOLD` is excluded from new scheduling until the hold clears. Beyond those basics, three safety checks guard shift creation, and they fire in this order after the generic checks of §2.6. The credential gate applies to `SAFETY_WATCH` shifts: the deployment's volunteer must hold a `VERIFIED` `MEDICAL` or `STRUCTURAL` certification, else `ERR_CERT_NOT_VERIFIED` (HTTP 422). The overlap rule treats every shift as a half-open interval — the start is inclusive, the end exclusive — and rejects the new shift with `ERR_SHIFT_OVERLAP` (HTTP 409) when another `SCHEDULED` or `COMPLETED` shift of the same deployment starts before the new shift ends and ends after the new shift starts; two shifts that merely touch, one ending exactly when the other begins, are admissible. The fatigue cap rejects with `ERR_FATIGUE_LIMIT_EXCEEDED` (HTTP 422) when the new shift's hours, added to the volunteer's current `fatigue_hours`, would exceed 40 (`MAX_FATIGUE_HOURS`); landing exactly on 40 is admissible. A shift's hours are the elapsed time from `starts_at` to `ends_at` divided by one hour and rounded up, with a minimum of 1 hour.

A deployment's `duty_status` is a parallel dimension that the system manages by itself. It flips from `RESTING` to `ON_DUTY` the moment a shift is created for the deployment whose window already contains `current_utc` — that is, whose `starts_at` has been reached while `ends_at` has not. It flips back to `RESTING` at the ops run when the in-window shift completes and no other scheduled shift currently contains `current_utc`, and demobilization always returns it to `RESTING`.

Shift completion is ops-run work. Every `SCHEDULED` shift whose `ends_at` has been reached or passed at evaluation time moves to the terminal `COMPLETED` state, and its hours accrue to the volunteer's `fatigue_hours`. Completions are processed in chronological order of `ends_at`, ties broken by the shift's `created_at`, so fatigue accumulates deterministically. Only after all of the epoch's completions are booked does the reset rule run, per volunteer: if at least 24 hours have passed since the end of the volunteer's most recently completed shift, and no `SCHEDULED` shift currently contains `current_utc`, the volunteer's `fatigue_hours` returns to 0. Every change to `fatigue_hours` — accrual or reset — recomputes the wellness-adjusted `readiness_score` of §2.9.

### 3.6. Work Order Intake, Triage, and Field Execution

Work orders are how the disaster's needs reach the roster. Before referrals can exist, a `SystemAdmin` registers each partner agency with its `name`, `contact_email`, and `kind` — `EMERGENCY_MANAGEMENT`, `NONPROFIT`, or `LTRG`, the long-term recovery group. Intake itself is shared between two roles: an `IntakeCoordinator` records direct homeowner or municipal requests, while a `PartnerLiaison` refers a request on behalf of their agency and must set `source_partner_id` to their own `PartnerAgency` id — a direct intake leaves `source_partner_id` null, and a liaison quoting another agency's id fails authorization. Intake is accepted while the incident is `ASSESSED`, `TYPED`, or `STANDING_DOWN`, and every work order records the incident it was filed under in its `incident_id`. The request carries the `requester_name`, the `hazard_kind`, and two prioritization flags that default to false: `vulnerable_resident`, marking households with elderly, disabled, or medically fragile residents, and `municipality_sourced`, marking requests that arrived from a municipality rather than a homeowner. A new work order stands in `INTAKE` with `priority_score` and `priority_tier` still null, and its `operation_id` unbound.

Triage is the `IntakeCoordinator`'s OCC-guarded judgment: the request must carry `expected_work_order_version` matching the work order's current `version`, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412) because a superseding triage has already landed. A successful triage moves `INTAKE` to `TRIAGED` and stamps both priority fields. The score starts from a per-hazard base — 60 for `STRUCTURAL`, 50 for `TREE_REMOVAL`, 35 for `TARPING`, 30 for `MUCK_OUT`, and 20 for `DEBRIS`. A `vulnerable_resident` household adds a bonus of 40. Age then adds its own boost: the number of whole 24-hour days between the work order's `created_at` and the triage moment, multiplied by 5 points per day, capped at 20. The score is the sum of base, bonus, and age boost, capped at 100. The tier reads off the score: at least 80 is `P1`, at least 50 but below 80 is `P2`, and anything lower is `P3`.

Scheduling binds a `TRIAGED` work order to an operation through `operation_id`, and it is the most gated step on the work-order path. The incident must be `TYPED`, else `ERR_INCIDENT_NOT_TYPED` (HTTP 409). The target operation must be `MUSTERED` or `ACTIVE`, else `ERR_OPERATION_NOT_OPEN` (HTTP 409). The operation's `hazard_focus` must equal the work order's `hazard_kind`, else `ERR_HAZARD_MISMATCH` (HTTP 422). And unless the hazard is `MUCK_OUT` — which maps to no capability and skips this check — the operation's `capability_gap` must hold no positive entry for the capability the pinned map of §2.10 assigns to the hazard, else `ERR_CAPABILITY_GAP` (HTTP 422). Among these business rules the capability check is evaluated first, then hazard alignment, then the operation-state gate, then the incident-typing gate. A successful scheduling records the binding in `operation_id`.

From `SCHEDULED`, an `OperationsLead` starts the work — moving it to `IN_PROGRESS` — only while the operation is `ACTIVE`. Field reality intrudes in two ways. The lead may block an `IN_PROGRESS` order by supplying a non-empty `blocked_reason`, and the revocation cascade of §3.1 can block it automatically with `blocked_reason` `CAPABILITY_LOST`; `blocked_reason` is null at all other times. Unblocking returns `BLOCKED` to `SCHEDULED`, clears `blocked_reason` back to null, and re-runs the capability check: if the hazard maps to a capability, the operation's `capability_gap` must again show no positive entry for it, else `ERR_CAPABILITY_GAP`. When the work is finished the lead moves the order to `DONE_PENDING_VERIFICATION`, and the `IntakeCoordinator` — the desk that owns the resident relationship — closes it into the terminal `VERIFIED_DONE` state. Cancellation is the coordinator's as well, available from `INTAKE`, `TRIAGED`, or `SCHEDULED`, landing in the terminal `CANCELLED` state; work already in progress or beyond may not be cancelled, and attempting it is an invalid transition.

### 3.7. The Training Pipeline: Courses, Seats, and the Waitlist

Readiness is manufactured as much as it is hired, and the training pipeline is where certifications begin. A `TrainingDirector` creates a course with a `title`, the `grants_cert_kind` it confers on completion — one of the four certifiable kinds — a `capacity` of at least 1 and at most 50 seats (`MAX_COURSE_CAPACITY`), a `starts_at` instant, and a `lead_instructor_volunteer_id`. The instructor reference is validated at creation: it must resolve to an existing volunteer whose `instructor_certified` flag is true, else the course is rejected with `ERR_INSTRUCTOR_NOT_CERTIFIED` (HTTP 422). A new course opens with `seats_taken` at 0.

Enrollment is the director's as well: the request names the `volunteer_id`, and the enrollment records the course it belongs to in its `course_id`. The seat check happens at creation: when `seats_taken` is still below `capacity` the enrollment lands in `ENROLLED` and `seats_taken` increases by 1; when the course is full the enrollment lands in `WAITLISTED` instead, and its `waitlist_position` is its 1-based position among the course's waitlisted enrollments ordered by `created_at` ascending — a field that is null for any enrollment not currently waitlisted. One volunteer may hold at most one live enrollment per course: a second enrollment in `ENROLLED` or `WAITLISTED` status for the same volunteer and course is rejected with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409).

Outcomes arrive after the course has begun. The director may move an `ENROLLED` enrollment to the terminal `COMPLETED` state only once `current_utc` has reached the course's `starts_at`; completion mints a `Certification` for the volunteer with `kind` copied from `grants_cert_kind`, status `PENDING_VERIFICATION`, `issued_at` stamped at `current_utc`, and `expires_at` set 730 days out (`CERT_GRANT_VALIDITY_DAYS`) — two years of validity that still requires a `SafetyOfficer`'s verification before it counts toward readiness. Completion does not free the seat. Marking `FAILED` under the same course-begun precondition frees nothing either and is likewise terminal. Dropping is the release valve: from `ENROLLED` or `WAITLISTED`, an enrollment moves to the terminal `DROPPED` state at the request of the `TrainingDirector` or of the enrolled `Volunteer` acting on their own record — the acting `X-User-ID` must equal the enrollment's `volunteer_id`. Dropping an `ENROLLED` enrollment decrements the course's `seats_taken` by 1, so that enroll-then-drop restores the seat count exactly; dropping a waitlisted entry changes no seat count.

The waitlist drains at the ops run. While a course has `seats_taken` below `capacity`, its `WAITLISTED` enrollments are promoted to `ENROLLED` in `created_at` ascending order, each promotion adding 1 to `seats_taken`, until no free seats remain; `waitlist_position` values are recomputed for whoever is still waiting.

### 3.8. Wind-Down: Demobilization, Wellness, and the After-Action Review

Ending an operation is a governed process, not a door anyone can slam. The parallel `aar_status` dimension on each operation tracks the after-action review independently of the operational ladder. An `OperationsLead` submits the review — `NONE` to `SUBMITTED` — while the operation is `ACTIVE` or `DEMOBILIZING`, carrying a non-empty `aar_notes` body; the server records the submitting role in `aar_submitted_by_role`. Adoption is deliberately someone else's job: an `IncidentCommander` moves `SUBMITTED` to the terminal `ADOPTED` state, and the segregation-of-duties rule requires the adopting role to differ from the role recorded in `aar_submitted_by_role` — a submission by an `OperationsLead` cannot be adopted by an `OperationsLead`, and the attempt fails authorization with `ERR_UNAUTHORIZED` (HTTP 403).

The operational wind-down enforces both closure and conscience. Moving an operation from `ACTIVE` to `DEMOBILIZING` is refused while any of its work orders is `IN_PROGRESS` — the rejection carries `ERR_WORK_ORDER_BLOCKING` (HTTP 409). Moving from `DEMOBILIZING` to the terminal `COMPLETE` state demands two things: the after-action review must be `ADOPTED`, else `ERR_AAR_NOT_ADOPTED` (HTTP 409), and no deployment of the operation may remain in `ON_SITE` or `SAFETY_HOLD`. Abandonment is simpler: from `DRAFT` or `OPEN` an operation may be cancelled — by the `OperationsLead`, or by the system during an incident stand-down — and cancellation moves every deployment of the operation still in `OFFERED` or `ACCEPTED` to `EXPIRED`.

The incident-level stand-down is the largest cascade in the system. When an `IncidentCommander` moves a `TYPED` incident to `STANDING_DOWN`, the cascade runs hop by hop. Every operation of the incident in `MUSTERED` or `ACTIVE` moves to `DEMOBILIZING`. From each demobilizing operation, every deployment in `ON_SITE` or `SAFETY_HOLD` is demobilized with the full demobe bundle of §3.4 — `demobed_at` stamped, `duty_status` returned to `RESTING`, bunk released and lodging finalized where a `fob_site_id` was set, `stipend_final_cents` computed, remaining `SCHEDULED` shifts cancelled, the wellness screen run, and the operation's counters recomputed — while every deployment still in `OFFERED` or `ACCEPTED` flips to `EXPIRED`. Separately, operations of the incident still in `DRAFT` or `OPEN` are moved to `CANCELLED`, their own `OFFERED` and `ACCEPTED` deployments expiring with them. Closing the incident — `STANDING_DOWN` to the terminal `CLOSED` state — is then permitted only once every operation of the incident rests in a terminal state, `COMPLETE` or `CANCELLED`.

Wellness closes the loop on the human cost. A `WellnessCheck` is never created by hand; it is raised only by the demobilization screen, `OPEN` with `reason` `FATIGUE_THRESHOLD` or `LONG_DEPLOYMENT`, attached to the deployment that triggered it. Anyone on the command staff can list the checks a deployment raised. A `SafetyOfficer` resolves a check by supplying non-empty `resolved_notes`, moving it to the terminal `RESOLVED` state; the notes are required, and the field stays null while the check is open. Open checks are not inert paperwork: as §3.1 records, any `OPEN` check on a volunteer's deployments blocks that volunteer's reinstatement from `SUSPENDED` to `DEPLOYABLE` with `ERR_OPEN_WELLNESS_CHECKS` until a safety officer has signed off.

## 4. Endpoint Definitions

All endpoints are mounted under `/vdr`. Status code rules are uniform: creating a new resource returns `201 Created`; every other successful call — reads, transitions, and the admin epochs — returns `200 OK`. The table below is a summary only: request payloads, response fields, and side effects are defined by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /vdr/volunteers | Register a volunteer | SystemAdmin |
| GET | /vdr/volunteers/{id} | Get a volunteer by id, including readiness scores and fatigue | SystemAdmin, SafetyOfficer, OperationsLead, IncidentCommander, TrainingDirector, Volunteer |
| PATCH | /vdr/volunteers/{id} | Readiness transitions (SafetyOfficer); own availability updates (Volunteer) | SafetyOfficer, Volunteer |
| POST | /vdr/volunteers/{id}/certifications | Record a certification for a volunteer | TrainingDirector |
| GET | /vdr/certifications | List certifications, filterable by volunteer and status | SystemAdmin, SafetyOfficer, TrainingDirector, OperationsLead, IncidentCommander, Volunteer |
| GET | /vdr/certifications/{id} | Get a certification by id | SystemAdmin, SafetyOfficer, TrainingDirector, OperationsLead, IncidentCommander, Volunteer |
| PATCH | /vdr/certifications/{id} | Verify, reject, renew, or revoke a certification | SafetyOfficer |
| POST | /vdr/incidents | Report an incident | IncidentCommander |
| GET | /vdr/incidents/{id} | Get an incident by id | SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, SafetyOfficer, TrainingDirector, PartnerLiaison, Volunteer |
| PATCH | /vdr/incidents/{id} | Incident transitions: assess, type, stand down, close, cancel | IncidentCommander |
| POST | /vdr/incidents/{id}/operations | Create an operation under a typed incident | IncidentCommander |
| GET | /vdr/operations | List operations, filterable by incident and status | SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, SafetyOfficer, Volunteer |
| GET | /vdr/operations/{id} | Get an operation by id, including roster counts and capability gap | SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, SafetyOfficer, Volunteer |
| PATCH | /vdr/operations/{id} | Operation status transitions and after-action review submission/adoption | OperationsLead, IncidentCommander |
| POST | /vdr/operations/{id}/retype | Re-type a draft or open operation (OCC-guarded) | OperationsLead |
| POST | /vdr/operations/{id}/deployments | Offer a deployment to a volunteer (call-up) | OperationsLead |
| GET | /vdr/deployments | List deployments, filterable by volunteer, operation, FOB site, and status | SystemAdmin, OperationsLead, IncidentCommander, SafetyOfficer, Volunteer |
| GET | /vdr/deployments/{id} | Get a deployment by id, including stipend fields and duty status | SystemAdmin, OperationsLead, IncidentCommander, SafetyOfficer, Volunteer |
| PATCH | /vdr/deployments/{id} | Deployment transitions: accept, decline, check in, demobilize, clear hold | Volunteer, OperationsLead, SafetyOfficer |
| POST | /vdr/operations/{id}/fob-sites | Establish a forward operating base for an operation | OperationsLead |
| GET | /vdr/operations/{id}/fob-sites | List an operation's forward operating bases | SystemAdmin, OperationsLead, IncidentCommander, SafetyOfficer |
| POST | /vdr/operations/{id}/duty-shifts | Schedule a duty shift for an on-site deployment | OperationsLead |
| GET | /vdr/duty-shifts | List duty shifts, filterable by operation, deployment, and status | SystemAdmin, OperationsLead, IncidentCommander, SafetyOfficer, Volunteer |
| GET | /vdr/duty-shifts/{id} | Get a duty shift by id | SystemAdmin, OperationsLead, IncidentCommander, SafetyOfficer, Volunteer |
| POST | /vdr/incidents/{id}/work-orders | Intake a work order (direct or partner referral) | IntakeCoordinator, PartnerLiaison |
| GET | /vdr/work-orders | List work orders, filterable by incident, operation, partner, status, and priority tier | SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, PartnerLiaison |
| GET | /vdr/work-orders/{id} | Get a work order by id, including priority fields | SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, PartnerLiaison |
| POST | /vdr/work-orders/{id}/triage | Triage a work order (OCC-guarded) | IntakeCoordinator |
| PATCH | /vdr/work-orders/{id} | Work-order transitions: schedule, start, block, unblock, finish, verify, cancel | IntakeCoordinator, OperationsLead |
| POST | /vdr/partners | Register a partner agency | SystemAdmin |
| POST | /vdr/training-courses | Create a training course | TrainingDirector |
| GET | /vdr/training-courses/{id} | Get a training course by id, including seats taken | SystemAdmin, TrainingDirector, SafetyOfficer, OperationsLead, Volunteer |
| POST | /vdr/training-courses/{id}/enrollments | Enroll a volunteer in a course | TrainingDirector |
| GET | /vdr/training-enrollments | List enrollments, filterable by course, volunteer, and status | SystemAdmin, TrainingDirector, SafetyOfficer, Volunteer |
| GET | /vdr/training-enrollments/{id} | Get an enrollment by id | SystemAdmin, TrainingDirector, SafetyOfficer, Volunteer |
| PATCH | /vdr/training-enrollments/{id} | Enrollment transitions: complete, fail, drop | TrainingDirector, Volunteer |
| GET | /vdr/deployments/{id}/wellness-checks | List the wellness checks raised by a deployment | SystemAdmin, SafetyOfficer, OperationsLead, IncidentCommander |
| PATCH | /vdr/wellness-checks/{id} | Resolve a wellness check | SafetyOfficer |
| POST | /vdr/_clock/set_current_utc | Set the logical clock | SystemAdmin |
| POST | /vdr/_ops/run | Run one housekeeping epoch (the six sweeps of §2.4) | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below is a reference index only. The conditions that trigger each error are defined where the corresponding rules live, in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_VALIDATION | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VOLUNTEER_NOT_FOUND | 404 |
| ERR_CERTIFICATION_NOT_FOUND | 404 |
| ERR_INCIDENT_NOT_FOUND | 404 |
| ERR_OPERATION_NOT_FOUND | 404 |
| ERR_DEPLOYMENT_NOT_FOUND | 404 |
| ERR_FOB_SITE_NOT_FOUND | 404 |
| ERR_DUTY_SHIFT_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_PARTNER_NOT_FOUND | 404 |
| ERR_TRAINING_COURSE_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_WELLNESS_CHECK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_OPERATION_NOT_OPEN | 409 |
| ERR_INCIDENT_NOT_TYPED | 409 |
| ERR_WORK_ORDER_BLOCKING | 409 |
| ERR_AAR_NOT_ADOPTED | 409 |
| ERR_VOLUNTEER_NOT_DEPLOYABLE | 409 |
| ERR_OPEN_WELLNESS_CHECKS | 409 |
| ERR_CERT_NOT_VERIFIED | 422 |
| ERR_INSTRUCTOR_NOT_CERTIFIED | 422 |
| ERR_AVAILABILITY_WINDOW_MISMATCH | 422 |
| ERR_DEPLOYMENT_WINDOW_CONFLICT | 409 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_FATIGUE_LIMIT_EXCEEDED | 422 |
| ERR_CAPABILITY_GAP | 422 |
| ERR_HAZARD_MISMATCH | 422 |
| ERR_TEAM_SIZE_EXCEEDED | 422 |
| ERR_FOB_CAPACITY_EXCEEDED | 422 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
