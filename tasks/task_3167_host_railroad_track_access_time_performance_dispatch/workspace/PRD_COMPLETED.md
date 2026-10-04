# Host Railroad Dispatch API - Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Host Railroad Dispatch API, a platform for administering passenger rail service over track owned by freight railroads. Under the host-tenant operating model, a passenger operator runs scheduled trains over corridors that belong to freight railroads under negotiated operating agreements; the agreements fix on-time performance targets, penalty and incentive rates, and schedule-pad allowances, and the system records what actually happened on each run so that settlement between the parties is auditable rather than argued.

The API covers the full commercial and operational loop: registering host railroads and the physical corridor network, negotiating and amending operating agreements, constructing and publishing timetables subject to the host's capacity grants and maintenance windows, recording actual train movements segment by segment, coding delay minutes to root causes, resolving dispatch-priority disputes when a passenger train is held for freight, funding capital improvements such as sidings and signal upgrades, allocating corridor costs across state sponsors of state-supported routes, and producing periodic settlement statements that convert on-time performance and attributed delay minutes into penalty or incentive dollars. A service-disruption workflow handles bus bridging and the automatic reaccommodation bookkeeping when a corridor goes out of service.

The system is mounted under the `/rail` URL prefix. All workflow state changes are immediate and strongly consistent, and every rule described in this document is enforced at the server on each request.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `SystemAdmin`, `PassengerOperator`, `HostRailroadRep`, and `StateSponsor`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the endpoint, or — in the case of a host representative — whose identity does not match the owning railroad of the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is defined as follows. When `X-User-Role` is `HostRailroadRep`, `X-User-ID` is the `id` of the acting `HostRailroad`; ownership checks on any resource that references a `HostRailroad` — directly, or through the corridor/agreement chain that links corridors, agreements, timetables, runs, incidents, projects, windows, and disruptions back to a host railroad — compare the resource's owning-railroad identifier to `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `PassengerOperator`, or `StateSponsor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_VALIDATION`. Unless a list endpoint declares a different ordering, resources are returned sorted by `created_at` in ascending order, with ties on `created_at` broken by creation sequence. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in this API carries a standard set of system-managed fields: `id`, a server-minted unique identifier formatted as a UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification; and `version`, an integer starting at 1 at creation that increments by exactly one on every mutation of the resource and underpins optimistic concurrency control.

The server maintains a **logical clock** that drives all time-dependent system behavior, including agreement expiry. The clock is set exclusively through an admin-only capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; before any such call, the clock stands at exactly 2026-09-01T00:00:00Z, and the server never falls back to wall-clock time. When the logical clock is advanced past an `ACTIVE` operating agreement's `effective_to`, that agreement transitions to `EXPIRED` automatically.

### 2.5. Track Capacity and Single-Line Occupancy Discipline

Host railroads grant passenger access in trains-per-day on each segment, recorded as `capacity_trains_per_day`. No timetable may schedule more runs across a segment on a service date than that grant allows; a proposal that would is rejected with `ERR_CAPACITY_EXCEEDED`.

Segments are either `SINGLE` or `DOUBLE` track. On `DOUBLE` segments, occupancy intervals never conflict. On `SINGLE` segments, no two occupancy intervals on the same segment may overlap. Overlap is judged with half-open intervals: two passages conflict if and only if each one's entry instant precedes the other's exit instant, while one passage's exit instant coinciding exactly with the other's entry instant is **not** a conflict — exact adjacency is permitted. This rule is enforced on planned passages when a timetable is proposed or published, and again on actual occupancy intervals when a passage is actualized, where a violation is rejected with `ERR_SEGMENT_OCCUPANCY_CONFLICT`.

### 2.6. Maintenance Windows, Clearance Buffers, and the Equipment Hours Budget

Maintenance work is scheduled as windows on individual segments. Each window carries a `clearance_buffer_minutes` safety margin (defaulting to 15 minutes when not supplied) that is applied on **both** sides of the window: for conflict purposes the window occupies an expanded interval stretching from the buffer minutes before `window_start_at` to the buffer minutes after `window_end_at`. A train passage — planned or actual — conflicts with a `LOCKED` window on the same segment when the passage's entry instant precedes the window's expanded end and the passage's exit instant follows the window's expanded start; exact equality at either buffer boundary is **not** a conflict. Occupancy that would intersect a locked window under these clearance-buffer semantics is rejected with `ERR_MAINTENANCE_CONFLICT`.

Maintenance equipment is budgeted weekly. Every maintenance unit identified by `equipment_unit_id` may consume at most 40.00 hours of locked window time per ISO week, where weeks start Monday at 00:00:00Z and a window belongs to the week containing its `window_start_at`. A window's `window_hours` is the elapsed time from `window_start_at` to `window_end_at`, expressed in hours rounded half-up to two decimal places. Locking a window is permitted only if the sum of `window_hours` over that unit's already-locked windows in the same week plus the new window's `window_hours` does not exceed 40.00 — a total of exactly 40.00 hours is allowed — and is otherwise rejected with `ERR_EQUIPMENT_ALLOWANCE_EXCEEDED`. Each window exposes `equipment_week_hours_available`, the unit's remaining allowance for that week, computed as 40.00 hours minus the hours consumed by the unit's locked windows in the window's ISO week. Releasing a locked window restores exactly its `window_hours` to the allowance and recomputes this field.

### 2.7. Validation Order

When several checks apply to one request, the server evaluates them in a fixed priority order so that the reported failure is deterministic. The order is: first, request format — the body must be valid JSON with all required fields present, enum fields holding declared members, and numeric fields within range; when a body is present it must be a JSON object, and an absent or empty body is treated as an empty object (a segment's `milepost_end` must be strictly greater than its `milepost_start`, a window's `window_end_at` must be strictly greater than its `window_start_at`, and coded `delay_minutes` must be at least zero), violations yielding `ERR_VALIDATION`; second, authentication (`ERR_UNAUTHENTICATED`); third, role authorization and host-ownership (`ERR_FORBIDDEN`); fourth, existence of every path identifier and every foreign-key identifier in the body (`ERR_NOT_FOUND`); fifth, the stale-version concurrency check (`ERR_STALE_VERSION`); sixth, state-machine legality of the requested transition (`ERR_INVALID_STATE`); seventh, the requirement that the operating agreement be `ACTIVE` where applicable (`ERR_AGREEMENT_NOT_ACTIVE`); eighth, the run-completion passage-finality check (`ERR_RUN_PASSAGES_OPEN`); ninth, the maintenance clearance conflict (`ERR_MAINTENANCE_CONFLICT`); tenth, single-track actual occupancy conflict (`ERR_SEGMENT_OCCUPANCY_CONFLICT`); eleventh, internal schedule feasibility of a proposed timetable (`ERR_SCHEDULE_INFEASIBLE`); twelfth, segment capacity (`ERR_CAPACITY_EXCEEDED`); thirteenth, the equipment weekly allowance (`ERR_EQUIPMENT_ALLOWANCE_EXCEEDED`); fourteenth, cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`); fifteenth, settlement period validity (`ERR_SETTLEMENT_PERIOD_INVALID`); and sixteenth, funding period overlap (`ERR_FUNDING_PERIOD_OVERLAP`). The priority order states which error is *reported* when several rules fail on one request; it does not require that later-tier checks be short-circuited, so earlier-tier checks may run even when a request would fail an earlier tier. Authentication and authorization (tiers 2–3) must always be enforced before existence (tier 4) and before any state or business rule, but format validation (tier 1) may run before authentication: when a request would fail both format and authentication, `ERR_VALIDATION` is reported.

### 2.8. Optimistic Concurrency Control

Two write operations on this API carry mandatory optimistic-concurrency guards, both keyed to the parent `OperatingAgreement`:

- Amending an operating agreement requires the request to carry `expected_operating_agreement_version`, the agreement `version` the client last observed. If the agreement's current `version` does not match — for example because another amendment or a capital-project approval landed since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Approving funding for a capital project likewise requires `expected_operating_agreement_version` matching the funding agreement's current `version`. Approval pins the commercial terms the approver observed, and `ERR_STALE_VERSION` (HTTP 412) prevents pinning terms that have already been superseded.

No other endpoint accepts or requires a version field.

### 2.9. Monetary and Measurement Precision

All monetary amounts are integer cents — funding amounts, allocated costs, penalty and incentive figures — and any rounding applied while deriving them is round half-up. Delay measurements are whole minutes, computed as max(0, floor((later − earlier) in whole minutes)) — a difference of zero or less yields zero, and a positive difference is truncated down to whole minutes. On-time percentages are carried to four decimal places with round half-up. Running-time pads are computed in whole minutes, with the padded run time rounded up to the next whole minute before dwell is added.

## 3. Business Logic & Workflows

### 3.1. The Physical Network: Railroads, Corridors, and Segments

A `SystemAdmin` registers each host freight railroad with its legal `name` and its AAR `reporting_mark` (for example, UP or BNSF). Corridors are then created against a railroad by supplying the owning `host_railroad_id`, a short `code`, a human-readable `name`, the terminal station codes `endpoint_a` and `endpoint_b`, a `service_type` of `LONG_DISTANCE` or `STATE_SUPPORTED`, and the `annual_cost_cents` — the annualized allocatable route cost in cents (zero or more) that later drives state funding allocation. A corridor's `status` begins as `ACTIVE` and may later be `SUSPENDED`.

Each corridor is divided into **track segments**, added in order along the line with an ascending `sequence_no` from the origin. A segment records its `milepost_start` and `milepost_end`, the two-letter `state_code` it lies in (which drives the funding allocation waterfall), its `track_class` (`SINGLE` or `DOUBLE`), the host's grant of `capacity_trains_per_day` (zero or more), the unimpeded `pure_run_minutes` needed to traverse it (zero or more), and optionally a `dwell_after_minutes` for the station dwell scheduled after the segment (defaulting to zero when omitted; zero or more when supplied). Segments begin with `status` `OPERABLE` and can be placed on `CAPITAL_HOLD` while construction is underway. The list of segments is returned sorted by corridor and then by ascending `sequence_no`.

### 3.2. Operating Agreements: Negotiation, Activation, Amendment, and Suspension

The commercial heart of the system is the **OperatingAgreement**, drafted by a `PassengerOperator` with a payload carrying the `host_railroad_id`, the `corridor_id`, the `effective_from` and `effective_to` instants, the `on_time_threshold_minutes` (an arrival delayed by at most this many minutes counts as on time; zero or more), the `penalty_rate_cents_per_minute` charged per host-attributed delay minute (zero or more), the `incentive_rate_cents_per_train_mile` paid per completed train-mile when the OTP target is met (zero or more), the `otp_target_pct` fraction (for example 0.80), and the `running_time_allowance_pct` — the host-negotiated schedule pad expressed as a fraction of pure running time. A new agreement is born in `DRAFT` with `amendment_seq` starting at zero.

Activation is the host's act: a `HostRailroadRep` whose identity matches the agreement's `host_railroad_id` moves the agreement from `DRAFT` to `ACTIVE`, which bumps the agreement's `version` by one. While `ACTIVE`, the passenger operator may amend the commercial terms — optionally changing `penalty_rate_cents_per_minute`, `incentive_rate_cents_per_train_mile`, `otp_target_pct`, or `running_time_allowance_pct` — but the amendment request must carry `expected_operating_agreement_version` equal to the agreement's current `version`, per §2.8. An accepted amendment leaves the agreement `ACTIVE`, increments `amendment_seq` by one, bumps the agreement's `version` by one, and forces every timetable of this agreement sitting in `PROPOSED` or `UNDER_REVIEW` back to `DRAFT`, since the negotiated basis of those schedules has changed.

Suspension is also the host's act, restricted to a `HostRailroadRep` who owns the agreement, and it is deliberately severe: the agreement moves `ACTIVE` → `SUSPENDED`, its `version` increments, and the suspension cascades outward — every `PUBLISHED` timetable of the agreement moves to `SUSPENDED`, and each suspended timetable's `SCHEDULED` train runs are cancelled with `cancellation_reason` set to `AGREEMENT_SUSPENDED`. Finally, when the logical clock reaches the agreement's `effective_to`, the system itself moves the agreement from `ACTIVE` to its terminal `EXPIRED` state.

### 3.3. Timetable Construction and the Review Loop

A `PassengerOperator` builds schedules as **timetables** under an operating agreement, supplying the `corridor_id`, the `operating_agreement_id`, the inclusive `service_date_start` and `service_date_end` in YYYY-MM-DD form (with `service_date_end` on or after `service_date_start`, else `ERR_VALIDATION`), the number of daily frequencies `trains_per_day` (at least 1), the first departure `departure_time_of_day` in HH:MM form, and the `headway_minutes` between successive daily departures (zero or more). The timetable's `corridor_id` must equal the operating agreement's `corridor_id`; a mismatch is rejected with `ERR_REFERENTIAL_INTEGRITY`. A new timetable is `DRAFT` with `revision_no` zero.

Proposing a draft timetable submits it to the host for review and triggers a full **schedule feasibility** evaluation. For each daily frequency k (counting from zero), the run's scheduled departure is its service date at `departure_time_of_day` plus k times `headway_minutes`. The schedule walk proceeds segment by segment in ascending `sequence_no` — strictly chronological, with no ties possible since `sequence_no` is unique per corridor: the first segment's planned entry equals the scheduled departure; each segment's planned exit is its planned entry plus its padded running time, the pad being the `pure_run_minutes` multiplied by one plus the agreement's `running_time_allowance_pct` and then rounded up to the next whole minute; and each following segment's planned entry is the previous segment's planned exit plus that segment's `dwell_after_minutes`. The proposal is rejected with `ERR_MAINTENANCE_CONFLICT` if any planned passage conflicts with a `LOCKED` maintenance window on the same segment under the clearance-buffer semantics of §2.6, with `ERR_SCHEDULE_INFEASIBLE` if any two planned passages on a `SINGLE` segment overlap under the half-open rule of §2.5, and with `ERR_CAPACITY_EXCEEDED` if any segment's per-service-date run count would exceed its `capacity_trains_per_day`. When more than one of these rules fails, they are evaluated in the priority order of §2.7 — the maintenance clearance conflict (tier 9) precedes schedule feasibility (tier 11), which precedes segment capacity (tier 12).

The review loop then alternates between the parties. A `HostRailroadRep` who owns the corridor's host railroad opens review, moving `PROPOSED` → `UNDER_REVIEW`. The operator may return an under-review timetable to `PROPOSED` for another negotiation round, incrementing `revision_no` by one on each such return — the loop is cyclic (PROPOSED → UNDER_REVIEW → PROPOSED → …) rather than terminal, and proposing again requires the timetable to be back in `DRAFT`. Ratification by the owning `HostRailroadRep` moves `UNDER_REVIEW` → `RATIFIED` and requires the operating agreement to be `ACTIVE` — otherwise the request fails with `ERR_AGREEMENT_NOT_ACTIVE`.

Publication by the operator moves `RATIFIED` → `PUBLISHED`, re-checking at that moment that no planned passage conflicts with a `LOCKED` maintenance window on the same segment under clearance-buffer semantics (`ERR_MAINTENANCE_CONFLICT`) and that no planned passage overlaps a passage of another `PUBLISHED` timetable on the same `SINGLE` segment, again half-open — only the other timetable's `PLANNED` and `ACTUALIZED` passages count (never `SKIPPED` ones), and an `ACTUALIZED` passage is compared on its actual interval rather than its planned one. Publication **materializes the operating plan**: one `TrainRun` is created per service date from `service_date_start` through `service_date_end` inclusive, per daily frequency, each in `SCHEDULED` status with a sequence-based `train_number` (a global counter across all timetables, incremented by one per run created and rendered as its decimal string), its `timetable_id` set, and its `scheduled_departure_at` and `scheduled_arrival_at` computed from the schedule walk (`scheduled_arrival_at` is the planned exit of the final segment of the walk). For each run, one `SegmentPassage` per track segment of the corridor is created in `PLANNED` status, ordered by `segment_sequence_no` copied from the segment, with `planned_entry_at` and `planned_exit_at` per the walk. When another timetable for the same corridor publishes with overlapping service dates, the previously published timetable is automatically moved to `SUPERSEDED`.

### 3.4. Running the Railroad: Departures, Passages, and Arrivals

Train movements are recorded by the `HostRailroadRep` who owns the run's host railroad. Recording the actual origin departure with an `actual_departure_at` instant moves a run from `SCHEDULED` to `EN_ROUTE` and computes `origin_departure_delay_minutes`: the difference between actual and scheduled departure, floored to whole minutes, with negative values clamped to zero. The operator may instead cancel a still-`SCHEDULED` run — the request may optionally carry a `reason`, which is accepted but not persisted — which sets `cancellation_reason` to `OPERATOR_CANCEL`.

While a run is en route, each of its `PLANNED` passages is actualized by recording `actual_entry_at` and `actual_exit_at`, moving the passage `PLANNED` → `ACTUALIZED`. Actualization is accepted only for a passage whose owning run is `EN_ROUTE`; actualizing against a run in any other status is rejected with `ERR_INVALID_STATE`. Actualization enforces two guards, in the priority order of §2.7: the actual interval must not intersect a `LOCKED` maintenance window on the same segment under clearance-buffer semantics (`ERR_MAINTENANCE_CONFLICT`), and on a `SINGLE` segment the actual interval must not overlap any other `ACTUALIZED` passage on that segment, half-open so exact adjacency is allowed (`ERR_SEGMENT_OCCUPANCY_CONFLICT`). A passage can also flip from `PLANNED` to `SKIPPED` by system action — a maintenance lock conflict or a disruption cascade — and when such a skip completes a disrupted run's passage set, the incident auto-creation of §3.6 fires.

Recording the actual destination arrival with an `actual_arrival_at` instant completes the run — but only when every one of its passages is already `ACTUALIZED` or `SKIPPED`; completing with a passage still `PLANNED` is rejected with `ERR_RUN_PASSAGES_OPEN`. Completion moves `EN_ROUTE` → `COMPLETED` and computes three results: `destination_arrival_delay_minutes`, the actual-minus-scheduled arrival difference floored to whole minutes and clamped at zero; `on_time_endpoint`, true when the destination arrival delay is at most the agreement's `on_time_threshold_minutes`; and `on_time_all_stations`, true when `on_time_endpoint` holds **and** every `ACTUALIZED` passage of the run exited within threshold — each passage's exit delay being its actual exit minus planned exit, floored to whole minutes, clamped at zero, and compared against the same threshold. These are deliberately two variants of the same measurement: identical run data can yield `on_time_endpoint` true while `on_time_all_stations` is false.

### 3.5. Delay Coding and Attribution

When a run is delayed, the host codes **delay incidents** against it: a `HostRailroadRep` supplies the `train_run_id`, a `cause_code`, and the coded `delay_minutes` (zero or more), optionally with a `segment_passage_id` localizing the delay — and when a passage is supplied it must belong to that run, else `ERR_REFERENTIAL_INTEGRITY`. A coded incident is born `OPEN` with `origin` `CODED`, and its `host_attributable` flag is derived from the cause: exactly the codes `HOST_FREIGHT_HOLD`, `HOST_SIGNAL`, and `HOST_TRACK` are host-attributable, while `MECHANICAL`, `STATION_DWELL`, `WEATHER`, and `DISRUPTION` are not.

The passenger operator countersigns the host's coding by confirming an `OPEN` incident, moving it to `CONFIRMED`. Either party — operator or host representative — may instead dispute an `OPEN` incident, which moves the incident to `DISPUTED` and creates a **DispatchPriorityDispute** in `UNDER_REVIEW`, carrying a free-text `reason`, the incident's `delay_incident_id`, and the denormalized `train_run_id`. Only one dispute may exist per incident; this is guaranteed structurally because disputing requires `OPEN` status, and a resolved dispute returns its incident to `CONFIRMED` or `REVERSED`, where the state check rejects any further dispute with `ERR_INVALID_STATE`.

Every confirmation and every reversal recomputes the owning run's `attributed_host_delay_minutes`: the sum of `delay_minutes` over that run's `CONFIRMED` host-attributable incidents only.

### 3.6. Service Disruptions and Bus Bridging

When a corridor goes out of service, the host declares a **ServiceDisruption** with the `corridor_id`, a `disruption_type` of `WEATHER`, `TRACK_FAILURE`, `GRADE_CROSSING`, or `SECURITY`, the `started_at` instant, and a `reaccommodation_policy` of `BUS_BRIDGE`, `REFUND`, or `REBOOK_NEXT`. The disruption opens in `OPEN` status with `bus_bridge_active` false.

Activating bus bridging moves the disruption `OPEN` → `BRIDGED`, sets `bus_bridge_active` true, and fires a three-link cascade. Link one: every `SCHEDULED` or `EN_ROUTE` train run of any timetable on the corridor whose `scheduled_departure_at` is at or after `started_at` moves to `DISRUPTED` with `cancellation_reason` `DISRUPTION` — no further service-date filter applies. Link two: each disrupted run's still-`PLANNED` segment passages flip to `SKIPPED`. Link three: when a run's final `PLANNED` passage flips to `SKIPPED`, the system auto-creates a delay incident for that run — at most once per run, regardless of how many cascades touch it — with `cause_code` `DISRUPTION`, `origin` `SYSTEM_DISRUPTION`, `delay_minutes` equal to the whole minutes from the disruption's `started_at` to the run's `scheduled_arrival_at` with negative values clamped to zero, and `status` `OPEN` — ready for the normal confirm/dispute flow of §3.5.

Recovering the disruption moves `BRIDGED` → `RECOVERED`, clears `bus_bridge_active` back to false, and stamps `cleared_at` with the current logical clock.

### 3.7. Dispatch-Priority Dispute Adjudication

Disputes over delay incidents follow a fork-join shape. From `UNDER_REVIEW`, the operator may escalate the dispute to formal adjudication (`ESCALATED`). Resolution is the arbiter's act: a `SystemAdmin` resolves a dispute by supplying a `resolution` of `UPHELD` or `OVERTURNED`. From `UNDER_REVIEW`, only `UPHELD` is accepted — attempting `OVERTURNED` without prior escalation is rejected with `ERR_INVALID_STATE` — while from `ESCALATED` either outcome is accepted. Resolution stamps `resolved_at`, moves the dispute to `RESOLVED`, and feeds back into the incident: an `UPHELD` resolution returns the incident `DISPUTED` → `CONFIRMED`, and an `OVERTURNED` resolution moves it `DISPUTED` → `REVERSED`; both outcomes recompute the owning run's `attributed_host_delay_minutes`, which counts only incidents currently `CONFIRMED` (per §3.5), so an incident still `DISPUTED` at that moment contributes nothing until it resolves to `CONFIRMED`.

### 3.8. Capital Investment Projects

Additional frequencies are earned through capital investment. A `PassengerOperator` proposes a **CapitalProject** with the `operating_agreement_id`, the `track_segment_id` being improved (which must belong to the agreement's corridor, else `ERR_REFERENTIAL_INTEGRITY`), a `project_type` of `SIDING`, `SIGNAL`, or `DOUBLE_TRACK`, the committed `funded_amount_cents` (zero or more), and the `added_frequency_capacity` the project will unlock on the segment (zero or more). The project is born `PROPOSED`.

The host approves funding by moving `PROPOSED` → `FUNDED`. Approval requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and, per §2.8, the request must carry `expected_operating_agreement_version` matching the agreement's current `version`; an accepted approval pins those terms by incrementing the agreement's `version` by one — which also means any amendment drafted against the old version will now fail its stale-version check. Starting construction moves `FUNDED` → `IN_PROGRESS` and places the segment's `status` on `CAPITAL_HOLD`; the same start action also resumes a `SUSPENDED` project back to `IN_PROGRESS`. Construction may be paused (`IN_PROGRESS` → `SUSPENDED`; the request may optionally carry a `reason`, which is accepted but not persisted). Completion moves `IN_PROGRESS` → `COMPLETED` and, exactly once per project, adds the project's `added_frequency_capacity` to the segment's `capacity_trains_per_day` while returning the segment to `OPERABLE`.

### 3.9. Maintenance Window Operations

Beyond the global rules of §2.6, maintenance windows have their own lifecycle. The host plans a window with the `track_segment_id`, `window_start_at`, `window_end_at`, the `equipment_unit_id` whose weekly budget it will consume, and an optional `clearance_buffer_minutes` (zero or more when supplied). The window is created `PLANNED` with its `window_hours` computed.

Locking a window moves `PLANNED` → `LOCKED`: the equipment-hours budget check runs first (`ERR_EQUIPMENT_ALLOWANCE_EXCEEDED` when the unit's week would exceed 40.00 hours), and on success the lock consumes the window's hours from the unit's weekly allowance and immediately cascades — every `PLANNED` segment passage on this segment whose clearance-expanded planned interval intersects the window flips to `SKIPPED`, with the incident auto-creation of §3.6 applying if that skip completes a disrupted run's passage set. Releasing a window moves it from `PLANNED` or `LOCKED` to `RELEASED`; releasing a locked window restores exactly its `window_hours` to the unit's weekly allowance and recomputes `equipment_week_hours_available`.

### 3.10. State-Supported Route Funding

For `STATE_SUPPORTED` corridors, a `StateSponsor` drafts a **FundingAgreement** with the `corridor_id`, the funding `state_code` (which must match at least one segment's `state_code` on the corridor, else `ERR_REFERENTIAL_INTEGRITY`), and the inclusive `period_start` and `period_end` dates (with `period_end` on or after `period_start`, else `ERR_VALIDATION`). The agreement is born `DRAFT` with `allocated_cost_cents` unset (null).

Committing the funding computes the state's share via a fixed-order waterfall. First, the period's allocatable cost is the corridor's `annual_cost_cents` prorated by the inclusive day count of the period over 365, rounded half-up to whole cents — this is rounding step one. Second, the corridor's total mileage is the sum over its segments (of any status) of `milepost_end` minus `milepost_start`, and each state's line is the rounded period cost multiplied by the sum of segment miles lying in that state and divided by the corridor's total miles, rounded half-up to whole cents per line — this is rounding step two, applied to each state line independently. The committed agreement's `allocated_cost_cents` is its own state's rounded line. The authoritative corridor total is the **sum of the rounded per-state lines**; the rounding remainder is deliberately not redistributed, so the total of all states' lines may differ from the rounded period cost. Commitment is refused with `ERR_FUNDING_PERIOD_OVERLAP` when another `COMMITTED` funding agreement for the same corridor and state already covers an overlapping period. A committed agreement is closed out by settling it, moving `COMMITTED` → `SETTLED`.

### 3.11. Settlement: On-Time Performance, Penalties, and Incentives

Periodically, a `PassengerOperator` generates a **SettlementStatement** for an agreement by supplying the `operating_agreement_id` and the inclusive `period_start` and `period_end` dates (`period_end` must be on or after `period_start`, else `ERR_VALIDATION`). The statement period must lie within the agreement's effective range — `period_start` on or after the `effective_from` date and `period_end` on or before the `effective_to` date — and must not overlap an existing `ISSUED` or `PAID` statement for the same agreement (inclusive date-interval overlap; `DRAFT`, `DISPUTED`, and `REISSUED` statements do not block); violations are rejected with `ERR_SETTLEMENT_PERIOD_INVALID`. Creation also requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`). A new statement is `DRAFT` with `computation_variant` `GROSS`, and its computed fields are filled at once.

The statement's inputs are the `COMPLETED` train runs of the agreement's corridor whose `service_date` falls within the period (inclusive on both ends). From these: `completed_run_count` is the count of such runs; `train_miles` is that count multiplied by the corridor's total mileage (the sum over segments of `milepost_end` minus `milepost_start`); and `otp_pct` is the percentage of completed runs whose `on_time_endpoint` flag is true — one hundred times the on-time count divided by `completed_run_count`, rounded half-up to four decimal places. When `completed_run_count` is zero, `otp_pct` is null — not zero, and not an error.

Host delay attribution comes in two variants governed by `computation_variant`. The eligible incident population is delay incidents on the period's completed runs of the corridor with `status` `CONFIRMED`; `DISPUTED` and `REVERSED` incidents are excluded from both sets. Under `GROSS` — used at creation and issuance — `host_delay_minutes` is the raw sum of confirmed host-attributable minutes. Under `NET` — used when a disputed statement is reissued — `host_delay_minutes` is the confirmed host-attributable sum minus the confirmed non-host sum, clamped at zero; identical incident data therefore yields NET no greater than GROSS.

Penalty and incentive figures follow a tiered rule over the agreement's terms. When `otp_pct` is null, both `penalty_cents` and `incentive_cents` are zero. When the OTP fraction (the percentage divided by one hundred) is at least the agreement's `otp_target_pct`, the host earns an incentive: `incentive_cents` is the `incentive_rate_cents_per_train_mile` multiplied by `train_miles` and by the excess of the OTP fraction over the target, rounded half-up to whole cents, and `penalty_cents` is zero. Otherwise the host owes a penalty: a tier multiplier applies — one when the OTP fraction is within 0.05 of the target (at least target minus 0.05), two when it is at least target minus 0.15, and three when it falls below that — and `penalty_cents` is the `penalty_rate_cents_per_minute` multiplied by the statement's `host_delay_minutes` and by the tier multiplier, rounded half-up to whole cents, with `incentive_cents` zero. The `net_cents` of the statement is `incentive_cents` minus `penalty_cents`.

The statement's lifecycle mirrors the parties' negotiation: the operator issues a draft (`DRAFT` → `ISSUED`); the host may dispute an issued statement (the request may optionally carry a `reason`, which is accepted but not persisted) (`ISSUED` → `DISPUTED`); the operator reissues a disputed statement (`DISPUTED` → `REISSUED`), which flips `computation_variant` from `GROSS` to `NET` and recomputes `otp_pct`, `host_delay_minutes`, `penalty_cents`, `incentive_cents`, and `net_cents` from the currently `CONFIRMED` incidents; and the host pays either an issued or a reissued statement (`ISSUED` or `REISSUED` → `PAID`).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. List endpoints accept the pagination parameters of §2.3 plus the filters implied by the narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rail/_clock/set_current_utc` | Set the logical clock | SystemAdmin |
| POST | `/rail/host-railroads` | Register a host freight railroad | SystemAdmin |
| GET | `/rail/host-railroads/{id}` | Get one host railroad | Any |
| POST | `/rail/corridors` | Create a corridor on a host railroad | SystemAdmin |
| GET | `/rail/corridors` | List corridors; filters: `host_railroad_id`, `status` | Any |
| GET | `/rail/corridors/{id}` | Get one corridor | Any |
| POST | `/rail/track-segments` | Add a track segment to a corridor | SystemAdmin |
| GET | `/rail/track-segments` | List segments, sorted by corridor then sequence_no ascending; filters: `corridor_id`, `state_code`, `status` | Any |
| GET | `/rail/track-segments/{id}` | Get one segment | Any |
| POST | `/rail/operating-agreements` | Draft an operating agreement | PassengerOperator |
| GET | `/rail/operating-agreements` | List operating agreements; filters: `host_railroad_id`, `corridor_id`, `status` | Any |
| GET | `/rail/operating-agreements/{id}` | Get one agreement | Any |
| POST | `/rail/operating-agreements/{id}/activate` | Host accepts the drafted agreement | HostRailroadRep |
| POST | `/rail/operating-agreements/{id}/amend` | Amend commercial terms; OCC-guarded; returns in-flight timetables to draft | PassengerOperator |
| POST | `/rail/operating-agreements/{id}/suspend` | Host suspends access; cascades to published timetables and their scheduled runs | HostRailroadRep |
| POST | `/rail/timetables` | Create a draft timetable under an operating agreement | PassengerOperator |
| GET | `/rail/timetables` | List timetables; filters: `corridor_id`, `operating_agreement_id`, `status` | Any |
| GET | `/rail/timetables/{id}` | Get one timetable | Any |
| POST | `/rail/timetables/{id}/propose` | Submit draft timetable for host review; runs schedule feasibility | PassengerOperator |
| POST | `/rail/timetables/{id}/review` | Host opens review of a proposed timetable | HostRailroadRep |
| POST | `/rail/timetables/{id}/revise` | Return an under-review timetable to proposed for another negotiation round | PassengerOperator |
| POST | `/rail/timetables/{id}/ratify` | Host ratifies the reviewed timetable; requires an active agreement | HostRailroadRep |
| POST | `/rail/timetables/{id}/publish` | Publish a ratified timetable; materializes train runs and segment passages; supersedes overlapping published timetables of the same corridor | PassengerOperator |
| GET | `/rail/train-runs` | List train runs, sorted by scheduled_departure_at ascending then created_at ascending; filters: `timetable_id`, `service_date`, `status` | Any |
| GET | `/rail/train-runs/{id}` | Get one train run | Any |
| POST | `/rail/train-runs/{id}/depart` | Record actual origin departure | HostRailroadRep |
| POST | `/rail/train-runs/{id}/complete` | Record actual destination arrival; requires all passages final | HostRailroadRep |
| POST | `/rail/train-runs/{id}/cancel` | Operator cancels a scheduled run | PassengerOperator |
| GET | `/rail/segment-passages` | List passages, sorted by segment_sequence_no ascending then created_at ascending; filters: `train_run_id`, `track_segment_id`, `status` | Any |
| GET | `/rail/segment-passages/{id}` | Get one passage | Any |
| POST | `/rail/segment-passages/{id}/actualize` | Record actual occupancy of a segment; enforces maintenance clearance and single-track occupancy rules | HostRailroadRep |
| POST | `/rail/delay-incidents` | Code delay minutes against a run with a root-cause code | HostRailroadRep |
| GET | `/rail/delay-incidents` | List delay incidents, sorted by created_at ascending; filters: `train_run_id`, `segment_passage_id`, `status`, `cause_code` | Any |
| GET | `/rail/delay-incidents/{id}` | Get one incident | Any |
| POST | `/rail/delay-incidents/{id}/confirm` | Passenger operator countersigns the host's coding | PassengerOperator |
| POST | `/rail/delay-incidents/{id}/dispute` | Open a dispatch-priority dispute on an incident | PassengerOperator, HostRailroadRep |
| GET | `/rail/disputes` | List disputes, sorted by created_at ascending; filters: `train_run_id`, `delay_incident_id`, `status` | Any |
| GET | `/rail/disputes/{id}` | Get one dispute | Any |
| POST | `/rail/disputes/{id}/escalate` | Escalate a dispute to formal adjudication | PassengerOperator |
| POST | `/rail/disputes/{id}/resolve` | Arbiter resolves; UPHELD from under review or escalated, OVERTURNED only from escalated | SystemAdmin |
| POST | `/rail/capital-projects` | Propose a capital improvement (siding, signal, or double-track) | PassengerOperator |
| GET | `/rail/capital-projects` | List capital projects; filters: `operating_agreement_id`, `track_segment_id`, `status` | Any |
| GET | `/rail/capital-projects/{id}` | Get one capital project | Any |
| POST | `/rail/capital-projects/{id}/approve` | Host approves funding; OCC-pins the agreement terms observed | HostRailroadRep |
| POST | `/rail/capital-projects/{id}/start` | Begin or resume construction | HostRailroadRep |
| POST | `/rail/capital-projects/{id}/suspend` | Pause construction | HostRailroadRep |
| POST | `/rail/capital-projects/{id}/complete` | Finish construction; adds frequency capacity to the segment | HostRailroadRep |
| POST | `/rail/maintenance-windows` | Plan a maintenance window for an equipment unit on a segment | HostRailroadRep |
| GET | `/rail/maintenance-windows` | List maintenance windows, sorted by window_start_at ascending then created_at ascending; filters: `track_segment_id`, `equipment_unit_id`, `status` | Any |
| GET | `/rail/maintenance-windows/{id}` | Get one maintenance window | Any |
| POST | `/rail/maintenance-windows/{id}/lock` | Lock the window; consumes weekly equipment hours; skips conflicting planned passages | HostRailroadRep |
| POST | `/rail/maintenance-windows/{id}/release` | Release the window; restores equipment hours | HostRailroadRep |
| POST | `/rail/service-disruptions` | Declare a service disruption on a corridor | HostRailroadRep |
| GET | `/rail/service-disruptions` | List disruptions; filters: `corridor_id`, `status` | Any |
| GET | `/rail/service-disruptions/{id}` | Get one disruption | Any |
| POST | `/rail/service-disruptions/{id}/bridge` | Activate bus bridging; cascades to runs, passages, and auto-coded incidents | HostRailroadRep |
| POST | `/rail/service-disruptions/{id}/recover` | Mark the disruption recovered | HostRailroadRep |
| POST | `/rail/funding-agreements` | Draft a state funding agreement for a corridor | StateSponsor |
| GET | `/rail/funding-agreements` | List funding agreements; filters: `corridor_id`, `state_code`, `status` | Any |
| GET | `/rail/funding-agreements/{id}` | Get one funding agreement | Any |
| POST | `/rail/funding-agreements/{id}/commit` | Commit funding; computes the state's allocated cost share | StateSponsor |
| POST | `/rail/funding-agreements/{id}/settle` | Settle a committed funding agreement | StateSponsor |
| POST | `/rail/settlement-statements` | Generate a settlement statement for an agreement and period (GROSS variant) | PassengerOperator |
| GET | `/rail/settlement-statements` | List settlement statements; filters: `operating_agreement_id`, `status` | Any |
| GET | `/rail/settlement-statements/{id}` | Get one settlement statement | Any |
| POST | `/rail/settlement-statements/{id}/issue` | Issue a draft statement | PassengerOperator |
| POST | `/rail/settlement-statements/{id}/dispute` | Host disputes an issued statement | HostRailroadRep |
| POST | `/rail/settlement-statements/{id}/reissue` | Recompute a disputed statement with the NET variant | PassengerOperator |
| POST | `/rail/settlement-statements/{id}/pay` | Host pays an issued or reissued statement | HostRailroadRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RUN_PASSAGES_OPEN` | 409 Conflict |
| `ERR_MAINTENANCE_CONFLICT` | 409 Conflict |
| `ERR_SEGMENT_OCCUPANCY_CONFLICT` | 409 Conflict |
| `ERR_SCHEDULE_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EQUIPMENT_ALLOWANCE_EXCEEDED` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_FUNDING_PERIOD_OVERLAP` | 409 Conflict |
