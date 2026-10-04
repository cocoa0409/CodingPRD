# Defibrillator Program API — Product Requirements Document

## 1. Introduction

Public-access defibrillation programs live or die on a chain of small, verifiable facts: the cabinet is where the floor plan says it is, the pads have not silently expired, the battery passed its last self-test, a certified responder is within walking distance, and a physician is willing to sign off on the case afterward. When any link breaks, the program is not merely non-compliant — it is a liability. This document specifies the Defibrillator Program API, a system that manages the full lifecycle of an automated external defibrillator (AED) program across a campus: placement planning driven by response-time modeling, equipment registration with pad and battery expiration tracking, periodic readiness inspections, responder training and certification, emergency response integration from the moment a cabinet door opens, and post-event case review conducted with the receiving hospital under formal medical direction.

The API serves two audiences simultaneously. Operationally, it is the system of record for `ProgramManager` staff who site cabinets, install devices, stock consumable lots, schedule training, and close the loop on replenishment after an event. Clinically, it enforces the segregation of duties that regulators expect: the physician who directs the program may not review his or her own events, inspections follow strict temporal windows, and a device may not return to service until the evidence — a passing inspection, fresh consumables, resolved replenishment — is actually in hand.

A defining characteristic of the domain is that readiness is never asserted, only derived. Every device continuously computes a `readiness_posture` from its consumables, inspection history, and self-test telemetry; every campus aggregates those device postures into an overall posture that gates further operations. The system is therefore deliberately conservative: an expired pad or a failed self-test does not merely annotate a record, it removes the device from service until the underlying cause is corrected.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request that omits either header, or names a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication and authorization checks run before any resource-existence or business-rule evaluation.

The system recognizes seven roles, spelled exactly as follows: `PlatformAdmin`, `ProgramManager`, `Inspector`, `MedicalDirector`, `Responder`, `System`, and `Anonymous`.

- A `PlatformAdmin` holds full read access and exclusive write access over the device-model catalog, campus creation, and the test-driving clock capability.
- A `ProgramManager` is the operational owner of a campus program — creating zones, cabinets, devices, consumable lots, responders, training sessions, and executing installs, removals, replenishment receipts, and cancellations.
- An `Inspector` performs and submits readiness inspections and is the only role permitted to return a device from maintenance to service.
- A `MedicalDirector` performs case reviews — opening, submitting, accepting, and reopening them.
- A `Responder` is a certified on-site responder who acknowledges, resolves, or closes emergency events.
- The `System` role represents automated device integrations and is used exclusively for self-test report ingestion.
- The `Anonymous` role represents the unauthenticated cabinet door sensor and is used exclusively for the cabinet-open event.

The binding between `X-User-ID` and persisted entities depends on the role. When `X-User-Role` is `Inspector`, `MedicalDirector`, or `Responder`, `X-User-ID` is the `id` of the acting `Responder` record; ownership and identity checks — such as comparing a case review's `reviewer_id` to the caller, or verifying that an acknowledge comes from a specific certified responder — compare the resource's foreign-key field against `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ProgramManager`, `System`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`.

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

Endpoints that return lists of resources are paginated via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, or a `limit` outside 1–100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed fields. The `id` field is a server-minted UUID with no type prefix — identifiers are bare UUIDs, not namespaced strings. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded at creation, and `updated_at` is the same style of timestamp refreshed on every mutation. The `version` field is an integer that starts at 1 at creation and increments by one on every mutation of the resource, including mutations driven by cascades and recomputed fields rather than direct client writes.

One resource deliberately departs from this convention: the `SelfTestReport` carries only `id` and `created_at`. Because self-test reports are immutable telemetry records that are never modified after ingestion, both `updated_at` and `version` are absent from the resource — clients must not expect them in the response body.

Any change to a derived or computed field — a recomputed `readiness_posture`, an adjusted `quantity_available`, an extended `certified_through` — is itself a mutation on the owning entity and therefore refreshes `updated_at` and increments `version`, even when the change was triggered indirectly by an operation on another resource.

### 2.5. The Readiness Posture Principle

Readiness in this system is always computed, never asserted. Each `Device` carries a derived `readiness_posture` whose value is one of `READY`, `DEGRADED`, or `OUT_OF_SERVICE`, recomputed whenever any of its inputs change: the state of its pad install, the state of its battery install, its `last_inspection_at`, its `last_selftest_status`, or its own lifecycle `status`.

The device-level rule is evaluated as a strict priority ladder, in this order. First, if the device's lifecycle `status` is `POST_EVENT`, `MAINTENANCE`, or `DECOMMISSIONED`, the posture is `OUT_OF_SERVICE` regardless of anything else. Second, if the device has no active pad install or no active battery install, the posture is `OUT_OF_SERVICE`. Third, if the active pad install's `expires_at` is at or before the current time, or the active battery install's `expires_at` is at or before the current time, the posture is `OUT_OF_SERVICE`. Fourth, if the device's most recent submitted inspection failed — a latched condition set by a `FAIL` inspection submission and cleared only by a later `PASS` submission — the posture is `OUT_OF_SERVICE`; and if the device's `last_selftest_status` is `FAIL`, the posture is `OUT_OF_SERVICE` only while that failure is the latest telemetry relative to the last passing inspection — that is, when there is no recorded self-test report, no passing inspection, or the failing report's `reported_at` is at or after `last_inspection_at`; a passing inspection submitted after the failing report clears this condition. Fifth, if the device has never had a passing inspection — its `last_inspection_at` is null — or the current time is later than thirty days after `last_inspection_at`, the posture is `DEGRADED`. Sixth, if any active install will expire within the next seven days — that is, its `expires_at` is strictly after the current time but at or before seven days from now — the posture is `DEGRADED`. Only when none of these conditions hold is the posture `READY`.

Time-driven transitions — an active install whose date-computed expiration has passed moving to `EXPIRED_REMOVED`, and a `SCHEDULED` inspection whose window has lapsed moving to `OVERDUE` — are applied by a lazy system sweep: the sweep runs whenever a device, campus, inspection, or install resource is read or written, evaluating the device's time-based state at that moment and recomputing postures. The install-expiry leg of the sweep compares against the install's date-computed expiration (`base_expires_at`), so an `expires_at` clamped earlier by a `BATT-` fault self-test report does not by itself cause the sweep to remove the install.

Each `Campus` likewise carries a derived `readiness_posture`, one of `OPERATIONAL`, `DEGRADED`, or `CRITICAL`, recomputed whenever any device posture within the campus changes. The aggregation considers every device belonging to the campus whose lifecycle `status` is not `DECOMMISSIONED`. If that set is empty, the campus posture is `OPERATIONAL`. Otherwise, let the number of `OUT_OF_SERVICE` devices be the outage count and the number of `DEGRADED` devices be the degraded count. The campus posture is `CRITICAL` when the outage count is at least the larger of one and the total device count multiplied by 0.25 and rounded up to a whole number. If the campus is not `CRITICAL`, it is `DEGRADED` when the outage count is greater than zero, or when the degraded count is at least the larger of one and the total device count multiplied by 0.50 and rounded down to a whole number. Otherwise the campus posture is `OPERATIONAL`.

Because posture is recomputed on every relevant mutation, and because each recomputation is itself a mutation, posture changes propagate `updated_at` refreshes and `version` increments on both the device and its campus.

### 2.6. Nested Resource Validation

The API enforces strict, left-to-right validation of hierarchical resource references. When a request targets a resource nested under another — whether by path parameters or by foreign-key fields in the request body — the system validates the existence of each referenced resource in order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first reference that does not resolve. Existence is always validated before state checks and before business-rule checks: a request that names a nonexistent cabinet and also violates a state rule receives the 404, not the 409. The same discipline applies to body-carried references such as `campus_id`, `zone_id`, `device_id`, `consumable_lot_id`, `inspector_id`, `instructor_id`, `responder_id`, `reviewer_id`, and `emergency_event_id`.

### 2.7. Optimistic Concurrency Control

Two write operations on a `Device` are guarded by optimistic concurrency control, and only those two. Any client calling the device-install operation or the consumable-install operation must include `expected_device_version` in the request payload, carrying the value of the target device's `version` the client most recently observed. This field is not optional on these two endpoints: a request that omits it, or carries a value that is not an integer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). If the supplied value does not equal the device's current `version` at the moment the write is evaluated — because another writer has advanced the version since the client last read the device — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from installing against, or superseding installs on, a device state it has not observed. Endpoints other than these two do not accept a version field; the version guard applies exactly where named and nowhere else. The stale-version check is evaluated after existence checks and before state-transition and business-rule checks.

### 2.8. The Logical Clock

All temporal reasoning in the system — expiration of installs, inspection windows, certification validity, session start and end comparisons, lot expiry — is evaluated against a server-side logical clock rather than the host wall clock. At startup the logical clock reads 2026-09-01T00:00:00Z. A `PlatformAdmin` may advance it through an admin-only test-driving capability that accepts a `current_utc` value and sets the server's current logical time to that instant; the capability returns the now-current `current_utc`. Every rule in §3 that says "now" refers to this logical clock.

### 2.9. Validation Ordering

When a single request could fail several rules, the failure reported is determined by a fixed evaluation order. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then optimistic-concurrency version matching (`ERR_STALE_VERSION`) on the endpoints that declare it, then the target resource's lifecycle state (`ERR_INVALID_STATE`), then the medical-direction segregation rules (`ERR_MEDICAL_DIRECTION_CONFLICT`), then prescription requirements (`ERR_PRESCRIPTION_REQUIRED`), then responder certification (`ERR_RESPONDER_NOT_CERTIFIED`), then temporal windows (`ERR_TEMPORAL_WINDOW_VIOLATION`), then cross-reference compatibility (`ERR_INCOMPATIBLE_REFERENCE`), then capacity constraints (`ERR_CAPACITY_EXCEEDED`), then consumable-lot availability (`ERR_LOT_UNAVAILABLE`), then replenishment-receipt payload validity (`ERR_REPLENISHMENT_INVALID`), and finally general request shape (`ERR_INVALID_REQUEST`). A reader can therefore predict, for any pair of simultaneously-violated rules, which error the API will surface.

### 2.10. Precision and Calendar Arithmetic

Datetime fields are ISO 8601 UTC. Expiration computations compare at second precision. Wherever month arithmetic is required — adding a shelf life in months to an install timestamp, or extending a certification by a number of months — the addition preserves the day-of-month and clamps to the last day of the target month when the target month is shorter (for example, adding one month to January 31 yields the last day of February). Response-time computations in the coverage report are rounded half-up to whole seconds per leg before summing, and the coverage percentage is rounded half-up once at the final step; the exact procedures are defined in §3.8.

## 3. Business Logic & Workflows

### 3.1. Founding a Campus Program

A defibrillator program begins when a `PlatformAdmin` creates a **Campus**, supplying a display `name`, the regulatory `jurisdiction_code`, the program's `jurisdiction_registration_number` with that jurisdiction, the `response_time_target_seconds` that placement planning will treat as the maximum acceptable response time, and the `medical_director_id` of the physician who will oversee the program. All five fields are required; `medical_director_id` must be a string and is recorded as supplied — because the medical director's responder record is itself registered under a campus, the campus write does not validate `medical_director_id` against the persisted responder population. A newly created campus starts with `readiness_posture` equal to `OPERATIONAL`.

Within a campus, a `ProgramManager` carves the physical space into **Zones**. Each zone is created with a `campus_id` placing it under its parent campus, a human-readable `zone_code` such as a building-and-floor label, the `floor_area_sqm` served, the `avg_walk_speed_mps` used for response-time modeling, a boolean `requires_elevator` indicating whether reaching the zone adds a fixed vertical-traversal delay, and the `elevator_delay_seconds` that apply when `requires_elevator` is true — which is 0 otherwise. Zones are the unit against which coverage is later attested.

The equipment catalog is global rather than campus-scoped. A `PlatformAdmin` registers each **DeviceModel** with its `model_code`, `manufacturer`, the `pad_shelf_life_months` and `battery_shelf_life_months` that govern how long consumables remain valid after installation, and a `prescription_required` flag declaring whether units of this model may only be installed under an active prescription.

Cabinets are the physical siting points. A `ProgramManager` creates a **Cabinet** under a zone by providing the `zone_id`, a human-readable `location_label`, and the cabinet's position within the zone as `centroid_x_m` and `centroid_y_m` coordinates measured in zone meters. A new cabinet starts with `status` equal to `EMPTY` and with `installed_device_id` null. Cabinet status thereafter moves among `EMPTY`, `OCCUPIED`, and `ALARM_OPEN` as devices are installed, alarms are raised, and events are resolved — never directly by client command, only as a side effect of device and event workflows.

The people of the program are **Responders**. A `ProgramManager` registers a responder under a campus with the responder's `full_name`, `badge_number`, and a `responder_role` of exactly one of `LAY_RESPONDER`, `MEDICAL_DIRECTOR`, `PROGRAM_MANAGER`, or `INSPECTOR`. A new responder starts with `status` equal to `ACTIVE` and `certified_through` null, meaning the responder has never been certified and cannot yet acknowledge emergency events until a completed training session establishes a certification window. A responder's lifecycle `status` moves among `ACTIVE`, `SUSPENDED`, and `INACTIVE`.

### 3.2. Equipping Devices: Registration, Consumables, and Installation

A `ProgramManager` registers a **Device** against a campus by supplying the `campus_id`, the `device_model_id` of its catalog model, and a `serial_number`. The serial number must be unique within its campus among devices that are not `DECOMMISSIONED` — a decommissioned device's serial number may be reused by a later registration on the same campus; registering a duplicate is rejected with `ERR_SERIAL_NUMBER_CONFLICT`. The device also carries a `prescription_number`: when the device's model has `prescription_required` true, a prescription reference must be present for install and commission to proceed, and the field is otherwise the empty string. A freshly registered device starts with lifecycle `status` equal to `REGISTERED`, with `cabinet_id` null, with `current_pad_install_id` and `current_battery_install_id` both null, with `last_inspection_at` null, with `last_selftest_status` equal to `UNKNOWN`, and — because it has no consumables — with `readiness_posture` equal to `OUT_OF_SERVICE` per the posture ladder in §2.5.

Consumables arrive as **ConsumableLots**. A `ProgramManager` creates a lot with its `campus_id`, the `device_model_id` the lot is compatible with, a `kind` of exactly `PAD` or `BATTERY`, the manufacturer's `lot_code`, the manufacturer-printed `manufacturer_expires_at`, and the `quantity_received`. On creation the lot's `quantity_available` equals `quantity_received`; thereafter `quantity_available` is the quantity received minus units installed, minus units consumed, minus expired write-offs — it decreases by one each time a unit from the lot is installed into a device and is never restored when an install is later replaced.

Installing a consumable is a distinct operation from installing the device into a cabinet. When a `ProgramManager` installs a pad or battery — supplying the `device_id`, the `consumable_lot_id`, and the OCC guard `expected_device_version` — a new **Install** record is created with `disposition` equal to `ACTIVE` and `installed_at` set to the current logical time. A consumable install is permitted on a device in any lifecycle status except `DECOMMISSIONED`; attempting it on a decommissioned device is rejected with `ERR_INVALID_STATE`. The lot must be compatible with the device's model; a lot whose `device_model_id` does not match the target device's model is rejected with `ERR_INCOMPATIBLE_REFERENCE`. The lot must also be usable: if the lot's `quantity_available` is not greater than zero, or its `manufacturer_expires_at` is not later than the current time, the install is rejected with `ERR_LOT_UNAVAILABLE`.

The install's `expires_at` is computed at creation and never recalculated. The shelf-life input is the model's `pad_shelf_life_months` when the install's `kind` is `PAD`, and the model's `battery_shelf_life_months` when the `kind` is `BATTERY`. The shelf-life end is `installed_at` advanced by that many calendar months using the day-preserving, end-of-month-clamping arithmetic of §2.10. The install's `expires_at` is then the earlier of the lot's `manufacturer_expires_at` and that shelf-life end; this date-computed value is also retained on the install as `base_expires_at`. One battery-specific exception overrides any date arithmetic: when a self-test report arrives with `result` equal to `FAIL` and a `fault_code` beginning with `BATT-`, the battery expires immediately — its active install's `expires_at` is clamped to the current time — regardless of dates, and the posture recomputation that follows reflects it. The clamp is recoverable: when a later self-test report for the same device arrives with `result` equal to `PASS`, an active battery install whose `expires_at` had been clamped below its `base_expires_at` by such a fault report has its `expires_at` restored to `base_expires_at`.

Install supersede semantics are strict. If the device already has an `ACTIVE` install of the same `kind`, that prior install transitions to `REPLACED` and its `removed_at` is set; the prior lot's `quantity_available` is unchanged by the replacement because the unit was already drawn when it was first installed. The device's `current_pad_install_id` or `current_battery_install_id` — whichever matches the install's `kind` — is set to the new install, the device's `version` increments, and the device's `readiness_posture` is recomputed. A `ProgramManager` may also remove an install explicitly; removal sets the install's `disposition` to `EXPIRED_REMOVED`, clears the device's corresponding `current_pad_install_id` or `current_battery_install_id` when it points at the removed install, and recomputes posture — which will typically fall to `DEGRADED` or `OUT_OF_SERVICE`. Removal is permitted when the install's `expires_at` is at or before the current time, or as an explicit manual removal; the same `EXPIRED_REMOVED` outcome may also be produced by a system sweep when an install's `expires_at` passes.

With consumables in place, a `ProgramManager` installs the device into a cabinet. The request names the target `cabinet_id` and carries `expected_device_version` per §2.7; a stale version is rejected with `ERR_STALE_VERSION` before any state evaluation. The cabinet must exist in a zone under the same campus as the device — a cabinet in a different campus rejects the install with `ERR_INCOMPATIBLE_REFERENCE` — its `status` must be `EMPTY` — an occupied cabinet rejects the install with `ERR_CABINET_NOT_EMPTY` — and when the device model's `prescription_required` is true the device must carry a valid `prescription_number`, else the operation is rejected with `ERR_PRESCRIPTION_REQUIRED`. Pads and batteries are not required at this step; readiness consumables may be installed separately before commissioning. On success the device's `status` moves from `REGISTERED` to `INSTALLED`, its `cabinet_id` is set, its `version` increments, the cabinet's `status` becomes `OCCUPIED` with `installed_device_id` pointing at the device, and the device's `readiness_posture` is recomputed.

Commissioning advances the device from `INSTALLED` to `IN_SERVICE` and is gated entirely on posture: the device's `readiness_posture` must be `READY`, otherwise the attempt is rejected with `ERR_DEVICE_NOT_READY`. A successful commission recomputes the campus `readiness_posture`. The prescription requirement is re-applied at commission: commissioning a prescription-required model without a valid prescription reference is rejected with `ERR_PRESCRIPTION_REQUIRED`.

### 3.3. Readiness Inspections and Self-Test Telemetry

Readiness is verified by two independent channels: human inspections and machine self-tests.

An `Inspector` schedules an **Inspection** for a device by providing the `device_id`, the `inspector_id` of the responder performing it, and the `scheduled_for` window start in UTC. The new inspection's `outcome` is `SCHEDULED`. Submitting the inspection is the pivotal act: the `Inspector` supplies the `checklist_items`, a list of entries each pairing an `item_code` with its result, and a `fail_reason` when any item fails. A submission missing required checklist entries is rejected with `ERR_INSPECTION_CHECKLIST_INCOMPLETE`.

The temporal discipline is exact. Submission is only valid once the window has opened — `scheduled_for` must be at or before the current time, and a submission attempted before the window opens is rejected with `ERR_TEMPORAL_WINDOW_VIOLATION` — and no later than seven days after `scheduled_for`; a submission attempted after it is rejected with `ERR_INSPECTION_OVERDUE`. The submission takes no client-supplied completion time: the inspection's `completed_at` is set by the server to the current logical time at submission, which therefore always falls within the enforced window. An inspection whose window lapses unsubmitted is moved to `OVERDUE` by the lazy system sweep of §2.5, after which the owning device's posture is recomputed under the ordinary ladder — the lapse itself does not force a posture change. The device being inspected must not be `DECOMMISSIONED`; a submission against a decommissioned device is rejected with `ERR_INVALID_STATE`. Each checklist entry must pair a non-empty string `item_code` with a `result` of exactly `PASS` or `FAIL`, and `fail_reason` must be a non-empty string whenever any item fails; violations are rejected with `ERR_INSPECTION_CHECKLIST_INCOMPLETE`.

When every checklist item passes, the inspection's `outcome` becomes `PASS`, the device's `last_inspection_at` is set to the submission's `completed_at`, and the device's posture is recomputed. When any item fails, the outcome becomes `FAIL`, the `fail_reason` is recorded, and the device's `readiness_posture` is forced to `OUT_OF_SERVICE` until the underlying problem is corrected and a passing inspection restores it.

The second channel is the **SelfTestReport**, ingested through a webhook acting as the `System` role. Each report carries the owning `device_id`, the `reported_at` timestamp of the self-test run, a `result` of exactly `PASS` or `FAIL`, and a `fault_code` when the result is `FAIL`. Ingestion updates the device's `last_selftest_status` to the reported result, records the report's `reported_at` on the device as `last_selftest_reported_at`, and recomputes the device's posture — a `FAIL` drives the posture to `OUT_OF_SERVICE` under the posture ladder, and the battery-specific rule of §3.2 applies when the `fault_code` begins with `BATT-`. Self-test reports are immutable telemetry: they carry `id` and `created_at` only, and are retrievable in list form filterable by `device_id` and `result`.

### 3.4. Responder Training and Certification

Certification is conferred only through completed training. A `ProgramManager` schedules a **TrainingSession** for a campus with an `instructor_id`, a `starts_at` and `ends_at`, a `capacity` bounding enrollment, and the `certification_months_granted` that completion will add to each attendee's certification window. The session's `status` begins at `SCHEDULED`. The session's timing must be sane — `ends_at` must be later than `starts_at`, and a new session's `starts_at` must be later than the current time; violations are rejected with `ERR_TEMPORAL_WINDOW_VIOLATION`, and this timing validation is evaluated before the instructor-role check. The instructor must be a responder whose `responder_role` is `MEDICAL_DIRECTOR` or `PROGRAM_MANAGER`; any other role is rejected with `ERR_INSTRUCTOR_ROLE_INVALID`.

Enrollment appends a `responder_id` to the session's attendee list. Enrollment is only possible while the session's `status` is `SCHEDULED`, before the session starts — an attempt at or after `starts_at` is rejected with `ERR_SESSION_ALREADY_STARTED` — and only while seats remain; enrolling beyond the session's `capacity` is rejected with `ERR_TRAINING_FULL`. The named responder must exist; no certification or responder-status eligibility check is applied at enrollment — any persisted responder may be enrolled while seats remain.

Completion is the certifying act and is only possible once the session has ended; completing before `ends_at` is rejected with `ERR_SESSION_NOT_ENDED`. The completing call carries the `attendee_ids` actually present, which must number at least one; every listed id must reference an existing responder who is enrolled in the session, otherwise the request is rejected with `ERR_INVALID_REQUEST`. On completion the session's `status` becomes `COMPLETED`, and each listed attendee's certification is extended as follows, processing attendees in the order their enrollments were created, earliest first: the base is the later of the responder's current `certified_through` and the session's `ends_at` — or simply the session's `ends_at` when the responder has never been certified and `certified_through` is null — and the new `certified_through` is that base advanced by the session's `certification_months_granted` calendar months, preserving the day-of-month and clamping to the last day of a shorter month per §2.10. Each extension is a mutation on the responder, refreshing `updated_at` and incrementing `version`.

Cancellation is possible only while the session has not started; cancelling at or after `starts_at` is rejected with `ERR_SESSION_ALREADY_STARTED`. A cancelled session's `status` becomes `CANCELLED` and confers nothing.

### 3.5. Emergency Response: From Cabinet Alarm to Resolution

The emergency workflow begins with a physical act no one authenticates for: a cabinet door opens. The door sensor, acting as `Anonymous`, reports the open against a specific cabinet. The cabinet must hold an installed device whose lifecycle `status` is `IN_SERVICE`; any other configuration is rejected with `ERR_INVALID_STATE`. On acceptance, an **EmergencyEvent** is created under the cabinet's campus with `status` equal to `OPEN`, `opened_at` set to the current logical time, and `cabinet_id` and `device_id` bound to the opened cabinet and its installed device. The cascade is immediate and multi-entity: the cabinet's `status` becomes `ALARM_OPEN`; the device's `status` becomes `POST_EVENT`; and the device's `readiness_posture` is recomputed — under the posture ladder a `POST_EVENT` device is necessarily `OUT_OF_SERVICE`, which in turn recomputes the campus posture.

Acknowledgement is the first human response. A `Responder` acknowledges the event; the acknowledging responder must have `status` equal to `ACTIVE` and a `certified_through` later than the current time, else the acknowledgement is rejected with `ERR_RESPONDER_NOT_CERTIFIED`. The first acknowledgement moves the event from `OPEN` to `RESPONDING` and records the first-acknowledged responder as the event's `first_responder_id`; a second acknowledgement attempt — against an event no longer `OPEN` — is rejected with `ERR_EVENT_ALREADY_ACKED`, and this already-acknowledged check is evaluated before the responder-certification check.

Resolution closes the operational phase. A `Responder` resolves an event that is in `RESPONDING` — resolving from any other state is rejected with `ERR_EVENT_NOT_RESPONDING` — by declaring the `hospital_code` of the receiving hospital, the `patient_transported` flag, and the `pads_consumed` flag. All three declarations are required. On resolution the event's `status` becomes `RESOLVED` and its `closed_at` is set; the cabinet's `status` returns to `OCCUPIED`; and readiness is recomputed across the affected entities. When `pads_consumed` is declared true, the consumable cascade fires: the device's active pad install transitions to `CONSUMED_IN_EVENT`, the device's `current_pad_install_id` is cleared, and a **ReplenishmentOrder** is auto-created with `kind` equal to `PAD`, `quantity` equal to exactly 1 — the v1 rule pins replenishment at one pad unit per event — `status` equal to `PENDING`, and its `emergency_event_id` bound to the resolved event. The replenishment-quantity rule is deliberately fixed: when `pads_consumed` is true the quantity is 1, otherwise no order is created at all.

A false alarm takes a shorter path. When a responder determines there was no patient and no pads were used, closing the event without a patient moves it directly from `OPEN` to `CLOSED`. The close-no-patient call takes no payload: because an `OPEN` event has not yet been resolved, its `pads_consumed` is necessarily false, so the pads-not-consumed precondition is always satisfied on this path and `ERR_PADS_NOT_CONSUMED` does not arise from it. The responder closing the event must be certified per the acknowledgement rule, else the close is rejected with `ERR_RESPONDER_NOT_CERTIFIED`. On a no-patient close the cabinet's `status` returns to `OCCUPIED` and the device's lifecycle `status` returns to `IN_SERVICE`, with posture recomputed accordingly.

### 3.6. Post-Event Case Review and Medical Direction

Clinical review is governed by strict segregation of duties. Once an event is `RESOLVED`, a `MedicalDirector` opens a **CaseReview** against it by supplying the `emergency_event_id`, the `reviewer_id`, the `hospital_reviewer_name` at the receiving hospital, whether `device_data_retrieved` has been performed, the clinical `outcome_code` — exactly one of `SURVIVED_TO_DISCHARGE`, `SURVIVED_TO_ADMISSION`, `DECEASED`, or `NO_SHOCK_INDICATED` — and free-text `notes`; an attempt against an event not in `RESOLVED` is rejected with `ERR_INVALID_STATE`. Creating the first case review moves the parent event from `RESOLVED` to `CASE_REVIEW`, and the review begins in `DRAFT` status.

Two segregation rules guard this workflow, and violations surface as `ERR_MEDICAL_DIRECTION_CONFLICT`. First, the `reviewer_id` must name a responder whose `responder_role` is `MEDICAL_DIRECTOR`, and that reviewer must not be the same responder named by the campus's `medical_director_id`: the physician who directs the program may not review his or her own program's events, so a second medical director is required. Second, at acceptance time, the accepting medical director must not be the review's `reviewer_id` and must likewise hold `responder_role` equal to `MEDICAL_DIRECTOR`.

A review in `DRAFT` is submitted by a `MedicalDirector`; submission requires that `outcome_code`, `hospital_reviewer_name`, and `device_data_retrieved` are all set, and an incomplete submission is rejected with `ERR_CASE_REVIEW_INCOMPLETE`. Submission moves the review from `DRAFT` to `SUBMITTED`. A submitted review may be returned to `DRAFT` — a state also referred to as `REOPENED` in the review lifecycle when reached via this path — by reopening it. Acceptance moves the review from `SUBMITTED` to `ACCEPTED` — its terminal state — subject to the segregation rule above, and requires that the review's `device_data_retrieved` is true; an acceptance attempt on a review whose `device_data_retrieved` is not true is rejected with `ERR_CASE_REVIEW_INCOMPLETE`. Acceptance cascades upward: the parent emergency event's `status` moves from `CASE_REVIEW` to `CLOSED`, which is the event's terminal state.

### 3.7. Replenishment, Return to Service, and Decommissioning

After an event consumes pads, the auto-created replenishment order drives restocking. A `ProgramManager` receives a `PENDING` order by supplying the `lot_code` and `manufacturer_expires_at` for the incoming shipment. Receipt is valid only while the order is still `PENDING` and only when both payload fields are provided; otherwise it is rejected with `ERR_REPLENISHMENT_INVALID`. On receipt the order's `status` becomes `RECEIVED`, a new **ConsumableLot** is created of the order's `kind` with `quantity_received` equal to the order's `quantity` — its `device_model_id` copied from the model of the device named by the order's originating emergency event when that can be resolved, and null otherwise — and the order's `received_lot_id` is set to the new lot. An order may instead be cancelled, moving it from `PENDING` to `CANCELLED`.

A device in `POST_EVENT` cannot be recommissioned directly; it must pass through maintenance. A `ProgramManager` sends it to maintenance, but only once every emergency event referencing the device has reached `RESOLVED`, `CASE_REVIEW`, or `CLOSED` — an open event blocks the transition with `ERR_DEVICE_IN_EVENT`. The device's `status` becomes `MAINTENANCE`. Maintenance is also reachable directly from `INSTALLED` for routine service. In either direction, if the device is still associated with a cabinet, the cabinet is freed — its `status` returns to `EMPTY` and `installed_device_id` is cleared — and the device's `cabinet_id` is set to null.

Return to service is the `Inspector`'s exclusive act and is the most heavily gated transition in the system. From `MAINTENANCE`, returning a device to `INSTALLED` requires three things, evaluated in this order: the most recent completed inspection for the device has `outcome` equal to `PASS` with a `completed_at` no more than thirty days in the past — any shortfall here is rejected with `ERR_DEVICE_NOT_READY`; no `PENDING` replenishment orders reference the device — via the `emergency_event_id` binding of orders created for the device's events — with a violation rejected as `ERR_INVALID_STATE`; and the device's `readiness_posture` is `READY`, meaning post-replenishment consumable installs are complete and unexpired — any attempt while the posture is not `READY` is rejected with `ERR_DEVICE_NOT_READY`. On success the device's `status` becomes `INSTALLED` and the campus posture is recomputed; re-installation into a cabinet and commissioning proceed per §3.2.

Decommissioning ends a device's lifecycle. From `MAINTENANCE`, a `ProgramManager` may decommission provided every open emergency event referencing the device has been closed. A device still in `REGISTERED` — never installed — may be decommissioned directly with no preconditions. Decommissioning from an installed state frees the cabinet exactly as the maintenance transition does. The device's terminal `status` is `DECOMMISSIONED`, and a decommissioned device is excluded from the campus posture aggregation of §2.5.

### 3.8. Coverage Reporting and Placement Planning

Placement decisions rest on the coverage report, computed for a campus on demand. The report expresses, for each zone, whether that zone is covered, and rolls the per-zone results up into a single integer `coverage_pct` for the campus alongside a `per_zone` array of per-zone detail. Each `per_zone` entry carries exactly `zone_id`, `zone_code`, `cabinet_id`, `optimistic_response_time_seconds`, `pessimistic_response_time_seconds`, and `covered`: the cabinet named is the zone's cabinet with the lowest pessimistic response time, the two response-time fields report that cabinet's optimistic and pessimistic estimates, and `covered` is the integer 1 or 0. A zone with no cabinets yields an entry whose `cabinet_id` and both response-time fields are null and whose `covered` is 0.

The response-time estimate between a zone's centroid and a cabinet is computed in two pinned variants that deliberately produce different numbers for the same inputs. The zone centroid is the origin of the zone's coordinate frame: zones carry no centroid fields of their own, so in both variants the horizontal and vertical offsets are simply the absolute values of the cabinet's `centroid_x_m` and `centroid_y_m`, and the walk distance is divided by the zone's `avg_walk_speed_mps` to obtain walking seconds. The **optimistic, straight-line variant** — used for placement plan drafts — takes the distance as the Euclidean straight line: the square root of the sum of the squared horizontal and vertical offsets, with no obstruction adjustment. The **pessimistic, walk-path variant** — used for compliance attestation — takes the distance as the Manhattan walk path: the horizontal offset plus the vertical offset, multiplied by a 1.30 obstruction multiplier. In both variants, when the zone's `requires_elevator` is true, the zone's `elevator_delay_seconds` is added as a fixed vertical-traversal leg; when false, that leg is zero. Rounding is per leg and canonical: each walking leg is rounded half-up to a whole number of seconds before the elevator leg is added, so the final estimate for each variant is a whole number of seconds.

A zone counts as covered when it has at least one cabinet whose pessimistic, walk-path response time from the zone centroid is at or below the campus's `response_time_target_seconds`. The campus `coverage_pct` is computed in a pinned order: each zone first contributes a whole 1 when covered or 0 when not; those per-zone integers are summed; the sum is multiplied by 100 and divided by the total number of zones; and the result is rounded half-up exactly once at that final step to an integer percent. A campus with no zones has a `coverage_pct` of 0. Computing fractional per-zone coverage first and rounding the sum is not the same calculation and is not acceptable.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`; operations that modify an existing resource return `200 OK`. All endpoints are mounted under the `/api` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/api/campuses` | Create a Campus | PlatformAdmin |
| GET | `/api/campuses` | List Campuses | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| GET | `/api/campuses/{campusId}` | Get a Campus | PlatformAdmin, ProgramManager, MedicalDirector, Inspector, Responder |
| GET | `/api/campuses/{campusId}/coverage-report` | Compute per-zone coverage with both response-time variants | PlatformAdmin, ProgramManager, MedicalDirector |
| POST | `/api/zones` | Create a Zone | ProgramManager |
| GET | `/api/zones` | List Zones, filterable by `campus_id` | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| GET | `/api/zones/{zoneId}` | Get a Zone | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| POST | `/api/device-models` | Create a DeviceModel catalog entry | PlatformAdmin |
| GET | `/api/device-models/{deviceModelId}` | Get a DeviceModel | PlatformAdmin, ProgramManager |
| POST | `/api/cabinets` | Create a Cabinet | ProgramManager |
| GET | `/api/cabinets` | List Cabinets, filterable by `zone_id` and `status` | PlatformAdmin, ProgramManager, Inspector |
| GET | `/api/cabinets/{cabinetId}` | Get a Cabinet | PlatformAdmin, ProgramManager, Inspector |
| POST | `/api/cabinets/{cabinetId}/open` | Cabinet door open event; triggers the emergency cascade | Anonymous |
| POST | `/api/devices` | Register a Device | ProgramManager |
| GET | `/api/devices` | List Devices, filterable by `campus_id`, `cabinet_id`, `device_model_id`, `status`, `readiness_posture` (the literal value `null` for `cabinet_id` matches devices not installed in any cabinet) | PlatformAdmin, ProgramManager, Inspector, MedicalDirector |
| GET | `/api/devices/{deviceId}` | Get a Device | PlatformAdmin, ProgramManager, Inspector, MedicalDirector |
| POST | `/api/devices/{deviceId}/install` | Install a Device into a Cabinet | ProgramManager |
| POST | `/api/devices/{deviceId}/commission` | Commission a Device into service | ProgramManager |
| POST | `/api/devices/{deviceId}/send_to_maintenance` | Send a Device to maintenance | ProgramManager |
| POST | `/api/devices/{deviceId}/return_to_service` | Return a Device from maintenance | Inspector |
| POST | `/api/devices/{deviceId}/decommission` | Decommission a Device | ProgramManager |
| POST | `/api/consumable-lots` | Create a ConsumableLot | ProgramManager |
| GET | `/api/consumable-lots` | List ConsumableLots, filterable by `campus_id`, `device_model_id`, `kind` | PlatformAdmin, ProgramManager, Inspector |
| GET | `/api/consumable-lots/{lotId}` | Get a ConsumableLot | PlatformAdmin, ProgramManager, Inspector |
| POST | `/api/installs` | Install a pad or battery from a lot into a device | ProgramManager |
| GET | `/api/installs` | List Installs, filterable by `device_id`, `consumable_lot_id`, `kind`, `disposition` | PlatformAdmin, ProgramManager, Inspector |
| GET | `/api/installs/{installId}` | Get an Install | PlatformAdmin, ProgramManager, Inspector |
| POST | `/api/installs/{installId}/remove` | Remove an install | ProgramManager |
| POST | `/api/inspections` | Schedule an Inspection | Inspector |
| GET | `/api/inspections` | List Inspections, filterable by `device_id`, `inspector_id`, `outcome` | PlatformAdmin, ProgramManager, Inspector |
| GET | `/api/inspections/{inspectionId}` | Get an Inspection | PlatformAdmin, ProgramManager, Inspector |
| POST | `/api/inspections/{inspectionId}/submit` | Submit an inspection checklist | Inspector |
| POST | `/api/self-test-reports` | Ingest a device self-test report | System |
| GET | `/api/self-test-reports` | List SelfTestReports, filterable by `device_id`, `result` | PlatformAdmin, ProgramManager, Inspector |
| POST | `/api/responders` | Register a Responder | ProgramManager |
| GET | `/api/responders` | List Responders, filterable by `campus_id`, `responder_role`, `status` | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| GET | `/api/responders/{responderId}` | Get a Responder | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| POST | `/api/training-sessions` | Schedule a training session | ProgramManager |
| GET | `/api/training-sessions` | List TrainingSessions, filterable by `campus_id`, `instructor_id`, `status` | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| GET | `/api/training-sessions/{sessionId}` | Get a TrainingSession | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| POST | `/api/training-sessions/{sessionId}/enroll` | Enroll a responder | ProgramManager |
| POST | `/api/training-sessions/{sessionId}/complete` | Complete a session and extend certifications | ProgramManager |
| POST | `/api/training-sessions/{sessionId}/cancel` | Cancel a session | ProgramManager |
| GET | `/api/emergency-events` | List EmergencyEvents, filterable by `campus_id`, `cabinet_id`, `device_id`, `status` | PlatformAdmin, ProgramManager, MedicalDirector, Inspector |
| GET | `/api/emergency-events/{eventId}` | Get an EmergencyEvent | PlatformAdmin, ProgramManager, MedicalDirector, Responder |
| POST | `/api/emergency-events/{eventId}/acknowledge` | Responder acknowledges dispatch | Responder |
| POST | `/api/emergency-events/{eventId}/resolve` | Resolve an event with hospital handoff | Responder |
| POST | `/api/emergency-events/{eventId}/close_no_patient` | Close a false alarm without case review | Responder |
| POST | `/api/case-reviews` | Open a CaseReview for a resolved event | MedicalDirector |
| GET | `/api/case-reviews` | List CaseReviews, filterable by `emergency_event_id`, `reviewer_id`, `status` | PlatformAdmin, ProgramManager, MedicalDirector |
| GET | `/api/case-reviews/{reviewId}` | Get a CaseReview | PlatformAdmin, ProgramManager, MedicalDirector |
| POST | `/api/case-reviews/{reviewId}/submit` | Submit a review | MedicalDirector |
| POST | `/api/case-reviews/{reviewId}/accept` | Accept a review | MedicalDirector |
| POST | `/api/case-reviews/{reviewId}/reopen` | Reopen a submitted review | MedicalDirector |
| GET | `/api/replenishment-orders` | List ReplenishmentOrders, filterable by `campus_id`, `emergency_event_id`, `received_lot_id`, `status` | PlatformAdmin, ProgramManager |
| GET | `/api/replenishment-orders/{orderId}` | Get a ReplenishmentOrder | PlatformAdmin, ProgramManager |
| POST | `/api/replenishment-orders/{orderId}/receive` | Receive a replenishment, creating a ConsumableLot | ProgramManager |
| POST | `/api/replenishment-orders/{orderId}/cancel` | Cancel a replenishment order | ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEDICAL_DIRECTION_CONFLICT` | 422 |
| `ERR_PRESCRIPTION_REQUIRED` | 422 |
| `ERR_RESPONDER_NOT_CERTIFIED` | 422 |
| `ERR_TEMPORAL_WINDOW_VIOLATION` | 422 |
| `ERR_INCOMPATIBLE_REFERENCE` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_LOT_UNAVAILABLE` | 409 |
| `ERR_REPLENISHMENT_INVALID` | 422 |
| `ERR_CABINET_NOT_EMPTY` | 409 |
| `ERR_DEVICE_NOT_READY` | 409 |
| `ERR_DEVICE_IN_EVENT` | 409 |
| `ERR_EVENT_ALREADY_ACKED` | 409 |
| `ERR_EVENT_NOT_RESPONDING` | 409 |
| `ERR_INSPECTION_OVERDUE` | 409 |
| `ERR_INSPECTION_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_SESSION_ALREADY_STARTED` | 409 |
| `ERR_SESSION_NOT_ENDED` | 409 |
| `ERR_TRAINING_FULL` | 409 |
| `ERR_INSTRUCTOR_ROLE_INVALID` | 422 |
| `ERR_CASE_REVIEW_INCOMPLETE` | 422 |
| `ERR_PADS_NOT_CONSUMED` | 409 |
| `ERR_SERIAL_NUMBER_CONFLICT` | 409 |
