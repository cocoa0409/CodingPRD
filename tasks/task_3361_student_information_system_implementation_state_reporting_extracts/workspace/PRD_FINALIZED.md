# Student Information System API — Product Requirements Document

## 1. Introduction

Districts rolling out a new student information system discover quickly that the hard problems are not the day-to-day records but the boundaries: converting historical data at a school-year seam, standing up a master schedule before students arrive, and — above all — satisfying a state reporting regime in which every state publishes its own data-collection specification, its own coding dictionaries for attendance, discipline, and program participation, and its own statutory submission window. This document specifies an API, modeled on a PowerSchool-style district implementation, that treats those boundaries as first-class concerns rather than afterthoughts.

The system covers the full implementation arc. A vendor operations team onboards districts and encodes each state's collection specification; district administrators plan school years, provision parent and student portals, register roster-synchronization feeds to assessment, food service, transportation, and learning platforms, and drive year-end rollover with promotion, graduation, and archival; registrars own students, the course catalog, sections and rosters, enrollment, attendance, and discipline; and a state reporting officer builds, validates, submits, and reworks reporting extracts against the state's specification. Because submission deadlines are fixed in statute and support escalations spike near them, the API evaluates every time-dependent rule against a controllable logical clock rather than the wall clock, and it derives an escalation priority for rejected extracts from the time remaining in the submission window.

All resources are mounted under the `/sis` prefix; the only exception is the administrative clock endpoint described in §2.4. Every mutation in the system is atomic within its request, including the multi-entity cascades that rollover execution and extract creation perform.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, time, resource metadata, numeric precision, validation ordering, referential boundaries, concurrency control, and interval conventions.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are exactly `PlatformAdmin`, `DistrictAdmin`, `Registrar`, `StateReporter`, and `PortalUser`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. A well-identified caller whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

Write surfaces are disjoint across the four operator roles. A `PlatformAdmin` — the vendor implementation and operations team — owns districts, state collection specs, and the logical clock. A `DistrictAdmin` — the district implementation office — owns school years, rollover runs, portal account provisioning, and integration feeds. A `Registrar` owns student registration, the course catalog, sections and their rosters, enrollment, attendance, and discipline. A `StateReporter` — the district's state-reporting officer — owns the reporting-extract lifecycle from snapshot through submission and resolution. A `PortalUser` holds no write surface at all and may read exactly one resource: the portal account whose `id` equals the caller's own `X-User-ID`.

Identity semantics differ by role, and the difference is contractual. When `X-User-Role` is `PlatformAdmin`, `DistrictAdmin`, `Registrar`, or `StateReporter`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. When `X-User-Role` is `PortalUser`, the `X-User-ID` value is the `id` of the acting `PortalAccount`, and ownership checks compare the requested account's `id` to `X-User-ID`: a `PortalUser` request targeting any other portal account is rejected with `ERR_FORBIDDEN`.

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

Endpoints that return lists accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless a list states its own ordering, items are returned sorted by `created_at` in ascending order. (The attendance-event list is the one exception: it orders by `attendance_date` ascending with ties broken by `created_at` ascending, as §3.5 describes.)

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. In addition to the pagination pair, each list endpoint accepts the documented filter query parameters for its resource — for example `district_id`, `state_code`, `status`, `student_id`, `school_year_id`, `course_id`, `teacher_ref`, `room`, `lifecycle`, `absence_posture`, `enrollment_id`, `collection_spec_id`, `supersedes_extract_id`, `platform`, `source_school_year_id`, or `target_school_year_id` — as enumerated per endpoint in §4.

### 2.4. The Logical Clock

All time-dependent rules in the system — submission windows, sync timestamps, truancy inference, escalation math — evaluate against a **logical clock** maintained by the server, never against wall-clock time. Before any client call, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability, the `POST /_clock/set_current_utc` endpoint, accepts a `current_utc` instant in the request body and advances the clock to it; the response echoes the applied `current_utc`. Once set, the clock holds at the supplied instant until set again — it never falls back to wall-clock time on its own.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

One entity is the exception. An `AttendanceEvent` is an immutable ledger entry: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent — an attendance mark is never modified after posting, and every derived quantity it influences is recomputed onto its owning enrollment instead.

### 2.6. Counts, Rates, and Rounding

Numeric precision is contractual, because state funding math leaves no room for floating-point drift.

- **Membership and head counts.** `membership_days`, `prior_segment_days`, `roster_count`, `record_count`, `invalid_record_count`, `chronic_absentee_count`, `promoted_count`, `graduated_count`, `archived_student_count`, and `last_synced_roster_count` are all integers. Membership math counts whole calendar days.
- **Full-time-equivalent values.** `fte_adm` and `fte_count_date` are rounded half-up to exactly three decimal places, and neither can exceed the cap of 1.0.
- **Extract totals.** `total_fte_millis` is an integer count of thousandths. Each contributing record's FTE is rounded half-up to three decimals and multiplied by one thousand *before* the sum is taken — never summed raw and rounded once at the end.
- **Absence rates.** `absence_rate` is carried as an exact rational value and compared against thresholds without rounding. `absence_weight_sum` accumulates the fixed weights 0.0, 0.5, and 1.0 supplied by the state's coding map.
- **Severity.** `severity_score` and `severity_base` are integers.
- **Escalation math.** Time remaining in a submission window is measured in whole hours, truncating any partial hour.

### 2.7. The Validation Pipeline

Every request passes through a fixed sequence of validation stages, and the first failing stage determines the error returned — earlier stages mask later ones. The order is:

1. **Caller context.** `X-User-ID` and `X-User-Role` are present and the role is one of the declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Request well-formedness.** Required body fields are present, enum values fall inside their declared sets, and numeric ranges are sane; otherwise `ERR_INVALID_REQUEST` (HTTP 400).
3. **Authorization.** The role is permitted for the endpoint, and a `PortalUser` caller targets only the portal account whose `id` equals their `X-User-ID`; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. **Path existence.** Resource identifiers in the URL path exist, validated left to right (see §2.8); the first missing resource yields its `ERR_*_NOT_FOUND` (HTTP 404).
5. **State preconditions.** The target resource is in a state that permits the requested transition, including the district-`LIVE` gates; otherwise the transition's specific 409 code.
6. **Body referential integrity.** Foreign keys in the request body reference existing entities that belong to the same district; otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND` or `ERR_DISTRICT_MISMATCH` (HTTP 422).
7. **Temporal coherence.** Date and interval rules hold — ends after starts, dates inside their windows, no overlapping year windows, no buffered section conflicts, submission window open; otherwise the corresponding temporal error.
8. **Coding maps and uniqueness.** Raw codes resolve through the district state's `PUBLISHED` spec, and uniqueness constraints hold; otherwise the `ERR_UNMAPPED_*`, `ERR_SPEC_NOT_PUBLISHED`, `ERR_DUPLICATE_*`, or `ERR_TEACHER_REQUIRED` family.
9. **Capacity.** Roster additions respect seat counts; otherwise `ERR_CAPACITY_EXCEEDED` (HTTP 409).

The ordering matters operationally: an unauthenticated caller learns nothing about resource existence, a caller pointing at a nonexistent section is never told whether its time slot would have conflicted, and a roster addition to a full section fails on seat count only after every state, referential, temporal, and uniqueness check has passed.

### 2.8. Path Resources and District Boundaries

Requests that address a resource by path validate each identifier in strict left-to-right order, and the first identifier that does not resolve to an existing resource determines the response: `ERR_DISTRICT_NOT_FOUND`, `ERR_SCHOOL_YEAR_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_EXTRACT_NOT_FOUND`, `ERR_PORTAL_ACCOUNT_NOT_FOUND`, `ERR_FEED_NOT_FOUND`, or `ERR_ROLLOVER_RUN_NOT_FOUND`, each an HTTP 404. For the nested attendance-event routes beneath an enrollment, the enrollment identifier is validated before any event-level consideration, so a post against a nonexistent enrollment surfaces `ERR_ENROLLMENT_NOT_FOUND` before the body is ever examined.

Foreign keys carried in request bodies follow a separate rule at pipeline stage 6: a reference to an entity that does not exist is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422), and a body that stitches together entities from different districts is rejected with `ERR_DISTRICT_MISMATCH` (HTTP 422) — this covers a student enrolled into another district's school year, a section whose course and year belong to different districts, an incident booked against an enrollment of a different district's student, and an extract whose spec `state_code` does not match the year's district `state_code`.

### 2.9. Optimistic Concurrency Control

Two creation endpoints participate in optimistic concurrency control, because each of them mutates a parent aggregate's `version` as a side effect and a client working from an outdated read must not silently proceed.

Creating a reporting extract requires the request to carry `expected_school_year_version`, set to the `version` of the target school year as the client last observed it. Extract creation itself supersedes prior extracts and increments the school year's `version`, so a request whose `expected_school_year_version` no longer matches the year entity's current `version` is stale — its view of the year's extract lineage is outdated — and is rejected with `ERR_STALE_SCHOOL_YEAR_VERSION` (HTTP 412).

Creating a rollover run requires the request to carry `expected_district_version`, set to the `version` of the district as the client last observed it. Run creation supersedes pending runs and increments the district's `version`, so a request whose `expected_district_version` no longer matches the district entity's current `version` is stale and is rejected with `ERR_STALE_DISTRICT_VERSION` (HTTP 412).

No other endpoint accepts a version field. All other writes rely on the state preconditions of §2.7 rather than client-supplied versions.

### 2.10. Half-Open Windows and the Ten-Minute Buffer

Every date or time window in the system is **half-open**: it includes its start instant and excludes its end instant. This convention applies uniformly to school-year windows (from `start_date` inclusive to `end_date` exclusive), to enrollment membership segments, and to spec submission windows (from `submission_window_opens_at` inclusive to `submission_window_closes_at` exclusive — a logical-clock reading exactly at the close instant is already outside the window).

Two consequences deserve emphasis. First, school-year windows within one district may *abut* — one year's `end_date` equal to the next year's `start_date` — but may never overlap; any true overlap is rejected with `ERR_YEAR_WINDOW_OVERLAP`. Second, section meeting windows follow the opposite treatment: because teachers and rooms need turnover time, two sections sharing a `room` or a `teacher_ref` conflict unless at least ten minutes separate their meeting windows — exact abutment is *rejected* there, per the buffered-overlap rule of §3.3.

## 3. Business Logic & Workflows

### 3.1. District Onboarding and Activation

A `PlatformAdmin` onboards a district by supplying its display `name` and the `state_code` of the state whose collection specifications will bind it. Every district begins life in `IMPLEMENTATION`, and its `status` only ever moves among `IMPLEMENTATION`, `LIVE`, and `SUSPENDED`.

Activation is the pivotal transition: a district in `IMPLEMENTATION` moves to `LIVE`, and a `SUSPENDED` district can be reinstated to `LIVE` the same way. Attempting activation from any other state — in practice, activating a district that is already `LIVE` — is rejected with `ERR_DISTRICT_NOT_ACTIVATABLE`. Suspension moves a `LIVE` district to `SUSPENDED`; suspending anything that is not `LIVE` is rejected with `ERR_DISTRICT_NOT_LIVE`. Both transitions increment the district's `version` by one.

A district that is not `LIVE` is operationally frozen in three places: opening a school year, creating an enrollment, and executing a rollover run are each rejected with `ERR_DISTRICT_NOT_LIVE`. (Roster synchronization treats a non-`LIVE` district differently — as a business outcome rather than an error — as §3.8 describes.)

### 3.2. School Years and State Collection Specifications

With a district in place, a `DistrictAdmin` plans its academic calendar. Creating a school year requires the owning `district_id`, a display `label` such as "2026-2027", the window endpoints `start_date` and `end_date`, the `instructional_days` denominator used for funding proration (a positive integer, conventionally 180), and the `count_date` snapshot instant used by count-date funding regimes. The window must end after it begins — otherwise `ERR_INVALID_DATE_RANGE` — and the `count_date` must fall inside the window, on or after `start_date` and strictly before `end_date`, on pain of `ERR_COUNT_DATE_OUTSIDE_YEAR`. Within one district, the half-open windows of two school years must never overlap, though adjacency is welcome: a year whose `start_date` equals the predecessor's `end_date` tiles cleanly, while any genuine overlap is rejected with `ERR_YEAR_WINDOW_OVERLAP`. A new year starts in `PLANNING`.

The year lifecycle runs `PLANNING` → `OPEN` → `CLOSED_FOR_REPORTING` → `ROLLED_OVER` → `ARCHIVED`. Opening requires the year to be `PLANNING` (else `ERR_YEAR_NOT_PLANNING`) and the district to be `LIVE` (else `ERR_DISTRICT_NOT_LIVE`). Closing for reporting requires `OPEN` (else `ERR_YEAR_NOT_OPEN`). The move from `CLOSED_FOR_REPORTING` to `ROLLED_OVER` is never performed directly — it happens inside rollover execution (§3.9), which also locks the year's committed sections. Archiving requires `ROLLED_OVER` (else `ERR_YEAR_NOT_ROLLED_OVER`). Each operator-driven transition increments the year's `version` by one.

In parallel, a `PlatformAdmin` encodes each state's data-collection rules as a **StateCollectionSpec**. The spec carries the `state_code` it encodes; the `funding_method` — `ADM` or `COUNT_DATE` — that selects which FTE variant feeds extract totals; three coding maps; and the submission window. The `attendance_code_map` translates each district `raw_code` into a state `state_code`, an `absence_weight` drawn from exactly 0.0, 0.5, or 1.0, and an `is_excused` flag. The `discipline_code_map` translates each raw offense into a `state_offense_code` and a `severity_base`. The `program_code_map` translates each raw program code into a `state_program_code` and a `weight_factor`. The window endpoints `submission_window_opens_at` (inclusive) and `submission_window_closes_at` (exclusive) must form a valid half-open window — close after open, else `ERR_INVALID_DATE_RANGE`. Three tunables carry defaults: `chronic_absence_threshold` defaults to 0.10, `auto_withdraw_streak` defaults to 10 consecutive days, and `min_membership_days` defaults to 10 days.

A spec is born `DRAFT`. Publishing requires it to be `DRAFT` (else `ERR_SPEC_NOT_DRAFT`) and requires all three coding maps to be non-empty (else `ERR_SPEC_MAPS_INCOMPLETE`). Publication is exclusive: at most one spec per `state_code` may be `PUBLISHED` at a time, so publishing a spec automatically retires any other `PUBLISHED` spec for the same state, and the newly published spec's `version` increments by one. A `PUBLISHED` spec may later be retired explicitly — retire requires `PUBLISHED`, else `ERR_SPEC_NOT_PUBLISHED`. Every raw-code mapping in the system resolves against the `PUBLISHED` spec of the district's state; where no such spec exists, the operation fails with `ERR_SPEC_NOT_PUBLISHED`.

### 3.3. Course Catalog and Master Schedule Construction

A `Registrar` builds the master schedule from the catalog outward. Each course is created with its owning `district_id`, a `course_code` unique within the district (a collision is `ERR_DUPLICATE_COURSE_CODE`), a `title`, the `credit_hours` granted on completion (a positive number), a `grade_band` of `ELEMENTARY`, `MIDDLE`, `HIGH`, or `ALL`, and the `state_course_code` under which the course is reported to the state.

Sections instantiate courses into a school year. A section is created against a `course_id` and a `school_year_id` — both must exist (else `ERR_REFERENCED_ENTITY_NOT_FOUND`) and must belong to the same district (else `ERR_DISTRICT_MISMATCH`) — together with a free-form `term_label` such as "SEM_1", the `room` where the section meets daily, the meeting window as `period_start_min` and `period_end_min` in minutes after midnight (so 480 means 08:00), the seat `capacity` (a positive integer), and optionally the `teacher_ref`, an opaque staff reference that may remain null until assigned. The end of the meeting window must fall after its start, else `ERR_INVALID_DATE_RANGE`. New sections begin `DRAFT` with `roster_count` at zero; that count is computed from active roster links, and any client-supplied value for it is ignored.

Teacher assignment is a distinct act: the registrar may set or replace a section's `teacher_ref`, or null it to unassign, while the section is `DRAFT` or `COMMITTED`, and each such update increments the section's `version`.

Committing a section — moving it `DRAFT` → `COMMITTED` — is the schedule's gate, and its checks run in pipeline order: the section must be `DRAFT` (else `ERR_SECTION_NOT_DRAFT`); its school year must be `OPEN` (else `ERR_YEAR_NOT_OPEN`); a non-null `teacher_ref` must be present (else `ERR_TEACHER_REQUIRED`); the meeting window must clear the buffered-overlap check; and the roster must already fit within `capacity`. The buffered-overlap check compares the candidate against every `COMMITTED` section of the same school year that shares its `room` or its `teacher_ref`: if the two meeting windows overlap, abut exactly, or are separated by less than ten minutes, the commit is rejected with `ERR_SECTION_TIME_OVERLAP`. Only a gap of ten minutes or more clears — recall from §2.10 that year windows allow exact adjacency but section windows do not.

Cancellation moves a `DRAFT` or `COMMITTED` section to `CANCELLED` (from any other state, `ERR_SECTION_NOT_CANCELLABLE`) and clears the roster: every active roster link is removed and `roster_count` returns to zero. `LOCKED` and `CANCELLED` are terminal; sections reach `LOCKED` only through rollover (§3.9).

Roster management keeps a section's seats honest. Adding an enrollment to a roster requires the section to be `DRAFT` or `COMMITTED` (else `ERR_SECTION_NOT_ROSTERABLE`), the enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`), and no active link to already exist for that enrollment in that section (else `ERR_DUPLICATE_ROSTER`); only then is the seat check applied — when `roster_count` has already reached `capacity`, the addition is rejected with `ERR_CAPACITY_EXCEEDED`, the equality boundary included: a full section is full. A successful add creates the link and increments `roster_count` by one. Dropping removes the active link — where none exists, `ERR_ROSTER_NOT_FOUND` — and decrements the count. Adding and then dropping the same enrollment leaves `roster_count` exactly as it was before the pair, a compensating invariant the roster listing reflects by exposing only currently active links.

### 3.4. Student Registration and the Enrollment Lifecycle

A `Registrar` registers a student with the owning `district_id`, a district-scoped `student_number`, `first_name`, `last_name`, `birth_date`, and the `entry_grade_level` at district entry — one of `KG`, `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`. The `student_number` must be unique within the district among students who are not `ARCHIVED`; a live collision is `ERR_DUPLICATE_STUDENT_NUMBER`, while archiving eventually frees a number for reuse. Students begin `PRE_REGISTERED`, and the student list keeps historical clutter out of view by excluding `ARCHIVED` students unless the caller explicitly passes a `status` filter of `ARCHIVED`.

Enrollment binds a student to a school year. Creating one requires the `student_id`, the `school_year_id`, the student's `grade_level` for that year (the same `KG`-through-`12` set), the `entry_date`, and optionally a `program_code`. The gates, in pipeline order: the district must be `LIVE` (else `ERR_DISTRICT_NOT_LIVE`); the year must be `OPEN` (else `ERR_YEAR_NOT_OPEN`); the referenced student must exist (else `ERR_REFERENCED_ENTITY_NOT_FOUND`) and belong to the same district as the year (else `ERR_DISTRICT_MISMATCH`); the `entry_date` must fall inside the year window, on or after `start_date` and strictly before `end_date` (else `ERR_ENTRY_OUTSIDE_YEAR`); and the student must not already hold an enrollment in that year in any lifecycle state (else `ERR_DUPLICATE_ENROLLMENT`).

Program participation is mapped at creation through the district state's `PUBLISHED` spec: a supplied `program_code` is looked up in the spec's `program_code_map`, populating the computed `state_program_code` and setting `program_weight` to the map's `weight_factor`. An unmapped code is rejected with `ERR_UNMAPPED_PROGRAM_CODE`, and — as everywhere — the absence of a `PUBLISHED` spec for the district's state is `ERR_SPEC_NOT_PUBLISHED`. When `program_code` is omitted, `state_program_code` remains null and `program_weight` defaults to 1.0.

A new enrollment starts with `lifecycle` `ACTIVE` and `absence_posture` `CLEAR`, with `exit_date` null, `prior_segment_days` zero, `absence_weight_sum` zero, and `absence_rate` 0.0; its `membership_days`, `fte_adm`, and `fte_count_date` are computed immediately. The student's first `ACTIVE` enrollment moves the student from `PRE_REGISTERED` to `ENROLLED`.

Membership accounting follows one formula everywhere it is needed. The current segment's effective start is the later of the enrollment's `entry_date` and the year's `start_date`; its effective end is the earlier of the `exit_date` — or the year's `end_date` while no exit exists — and the year's `end_date`. The segment contributes the whole calendar days in that half-open span, never fewer than zero, and `membership_days` is the sum of `prior_segment_days` and those current-segment days.

The two FTE variants diverge by design. `fte_adm` prorates membership: `membership_days` divided by the year's `instructional_days`, multiplied by `program_weight`, capped at 1.0, and rounded half-up to three decimal places — a 100-day membership in a 180-day year with weight 1.0 yields 0.556. `fte_count_date` is a binary snapshot: when the enrollment spans the year's `count_date` — `entry_date` on or before the count date, and either no `exit_date` or an `exit_date` strictly after it — the value is `program_weight` capped at 1.0 and rounded half-up to three decimals, so that same 100-day enrollment spanning the count date yields 1.000; when the enrollment does not span the count date, the value is 0.0. §3.7 explains how a spec's `funding_method` selects between them.

Withdrawal moves an `ACTIVE` enrollment to `WITHDRAWN` (from any other lifecycle, `ERR_ENROLLMENT_NOT_ACTIVE`). The caller may supply an `exit_date`, which must fall strictly after the current `entry_date` and no later than the year's `end_date` — violations are `ERR_WITHDRAWAL_OUTSIDE_YEAR`. When `exit_date` is omitted, the system infers one from the attendance record via the truancy rule of §3.5. Either way, withdrawal closes the segment: the `exit_date` is set, the days of the closing segment — counted half-open and intersected with the year window — are folded into `prior_segment_days`, and `membership_days`, `absence_rate`, both FTE variants, and `absence_posture` are recomputed. If the student then holds no other `ACTIVE` enrollment, the student moves from `ENROLLED` to `INACTIVE`.

Re-entry reverses the direction. A `WITHDRAWN` enrollment (only — else `ERR_ENROLLMENT_NOT_WITHDRAWN`) may be re-entered with a `reentry_date` strictly after the current `exit_date` and no later than the year's `end_date` (violations are `ERR_REENTRY_OUTSIDE_YEAR`). Re-entry opens a fresh segment: `entry_date` becomes the `reentry_date`, `exit_date` returns to null, the accumulated `prior_segment_days` are retained, the derived quantities recompute, and an `INACTIVE` student returns to `ENROLLED`. A completed enrollment, by contrast, never re-enters — `COMPLETED` is terminal and arrives only through rollover.

### 3.5. Attendance Capture and the Absence Posture Dimension

Attendance is posted per enrollment. A `Registrar` records a mark by supplying the `attendance_date` and the district's `raw_code`. The date must lie inside the enrollment's current membership segment — on or after the current `entry_date` and, while an `exit_date` exists, strictly before it — otherwise the post is rejected with `ERR_ATTENDANCE_OUTSIDE_ENROLLMENT`. The `raw_code` must resolve through the district state's `PUBLISHED` spec `attendance_code_map`; an unmapped code is `ERR_UNMAPPED_ATTENDANCE_CODE`, and the absence of a `PUBLISHED` spec is `ERR_SPEC_NOT_PUBLISHED`. A successful post persists the mapped `state_attendance_code`, the `absence_weight` (0.0, 0.5, or 1.0), and the `is_excused` flag onto the immutable `AttendanceEvent`, whose `enrollment_id` comes from the sub-resource path. Listing an enrollment's events returns them in a pinned order: `attendance_date` ascending, ties broken by `created_at` ascending.

Every posted mark feeds a single, pinned recomputation. First, `absence_weight_sum` accumulates the `absence_weight` of every attendance event on the enrollment plus the full `action_days` of each `APPROVED` discipline incident whose `action_type` is `OSS` — each out-of-school suspension day weighs a full 1.0 day. Second, `membership_days` recomputes per §3.4 as the denominator. Third, `absence_rate` is the sum divided by the membership, or exactly 0.0 when membership stands at zero — and it is carried as an exact rational, so threshold comparisons never see a rounded value. Fourth, the rate maps onto the parallel `absence_posture` dimension: a rate at or above the spec's `chronic_absence_threshold` is `CHRONIC` — the comparison is inclusive, so a rate of exactly the threshold is chronic — a rate at or above 0.05 but below the chronic threshold is `AT_RISK`, and anything below 0.05 is `CLEAR`.

Because `absence_posture` is an independent dimension of the enrollment, it moves freely in any direction — `CLEAR` ↔ `AT_RISK`, `AT_RISK` ↔ `CHRONIC`, and direct `CLEAR` ↔ `CHRONIC` jumps — and it re-derives after every attendance post, every withdrawal, every re-entry, and every discipline approval or void. A re-entry that lengthens membership can pull a `CHRONIC` enrollment back to `AT_RISK` or `CLEAR`, just as a voided suspension can.

The same pinned event order drives **truancy exit inference**. When a withdrawal arrives without an `exit_date`, the system collects the enrollment's attendance events in the current segment — those with `attendance_date` on or after the current `entry_date` — in `attendance_date`-then-`created_at` order, and scans for the first run of `auto_withdraw_streak` consecutive calendar days on each of which the student holds an unexcused full-day absence (an event whose `is_excused` is false and whose `absence_weight` is 1.0). The inferred `exit_date` is the `attendance_date` of the streak's final event — the Nth day of that first qualifying run, where N is the configured streak length. If no qualifying run exists, the inferred exit is the logical clock's current date. The segment then closes half-open around that exit: membership recomputes with the exit exclusive, and `absence_weight_sum` counts only events whose `attendance_date` falls strictly before the exit — an event on the exit date itself is excluded. A caller-supplied `exit_date` skips inference entirely.

### 3.6. Discipline Incidents and Severity Scoring

Discipline begins with a report. A `Registrar` records the `student_id`, the `enrollment_id` the incident is booked against, the `incident_date` (which must fall inside that enrollment's school-year window), the district's `raw_offense_code`, the `action_type` — one of `NONE`, `ISS`, `OSS`, or `EXPULSION` — and the `action_days` duration. The duration must be exactly 0 when the action is `NONE` and strictly positive for any real action; a mismatch is a malformed request, `ERR_INVALID_REQUEST`. The `raw_offense_code` resolves through the district state's `PUBLISHED` spec `discipline_code_map` into the computed `state_offense_code` and `severity_base`; an unmapped offense is `ERR_UNMAPPED_DISCIPLINE_CODE`, and a missing `PUBLISHED` spec is `ERR_SPEC_NOT_PUBLISHED`.

Severity is scored at creation and comes in two variants. The raw score is `severity_base` multiplied by `action_days`. For the capped variant — actions `NONE`, `ISS`, and `OSS` — the recorded `severity_score` is that raw product clipped at 100. For the uncapped variant — `EXPULSION` — the raw product stands unclipped. So a `severity_base` of 25 with 6 `action_days` records 100 for an `OSS` incident but 150 for an `EXPULSION`. A new incident starts `REPORTED`.

Approval moves a `REPORTED` incident to `APPROVED` (from anything else, `ERR_INCIDENT_NOT_REPORTED`), and approval is what makes a suspension bite: when the incident's `action_type` is `OSS`, the enrollment's `absence_weight_sum` grows by the full `action_days`, each day weighing 1.0, after which `absence_rate` and `absence_posture` recompute per §3.5.

Voiding runs from either `REPORTED` or `APPROVED` to the terminal `VOIDED`; an incident already `VOIDED` rejects further transitions with `ERR_INCIDENT_ALREADY_VOIDED`. Voiding an `APPROVED` out-of-school suspension compensates the earlier cascade: the enrollment's `absence_weight_sum` shrinks back by the `action_days`, and the rate and posture recompute — one of the paths by which a `CHRONIC` posture can fall back to `AT_RISK` or `CLEAR`.

### 3.7. Reporting Extracts: Snapshot, Submission, and Resolution

Once a year closes for reporting, a `StateReporter` builds the state's extract. Creating one requires the `school_year_id`, the `collection_spec_id`, and — per §2.9 — the `expected_school_year_version`. The school year must be `CLOSED_FOR_REPORTING`; the spec must be `PUBLISHED` (else `ERR_SPEC_NOT_PUBLISHED`) and its `state_code` must match the state of the year's district (else `ERR_DISTRICT_MISMATCH`).

Creation snapshots the year's entire enrollment population — every enrollment of the year in any lifecycle, `ACTIVE`, `WITHDRAWN`, or `COMPLETED` — and freezes four totals. `record_count` is the size of that population. `chronic_absentee_count` is the number of snapshot records whose `absence_posture` stands at `CHRONIC` at creation. `total_fte_millis` sums, across the population, each record's FTE variant — `fte_adm` when the spec's `funding_method` is `ADM`, `fte_count_date` when it is `COUNT_DATE` — with each record's value first rounded half-up to three decimals and multiplied by one thousand before any summation: two records each rounding to 0.444 contribute 888 thousandths in total, never the 889 a sum-then-round order could produce, and the per-record order is the required one. `invalid_record_count` counts snapshot records whose `membership_days` fall below the spec's `min_membership_days`. The extract's `generation` is one plus the count of prior extracts created for the same year-and-spec pairing.

Creation also maintains the revision lineage. Every prior extract for the same year-and-spec pairing that has not been submitted — those standing in `DRAFT`, `VALIDATED`, or `REJECTED` — moves to `SUPERSEDED`, while `SUBMITTED` and `ACCEPTED` extracts stand untouched. The new extract records, in its `supersedes_extract_id`, the most recently created of the extracts it just superseded (null when it supersedes nothing), and the school year's `version` increments by one — the very mutation that the `expected_school_year_version` guard of §2.9 protects against a stale client. The new extract begins `DRAFT` with `submitted_at` null and `escalation_priority` at `NONE`.

Validation moves a `DRAFT` extract to `VALIDATED` (from anything else, `ERR_EXTRACT_NOT_DRAFT`) and recomputes exactly one number: `invalid_record_count` is re-derived against current enrollment data, while `record_count`, `total_fte_millis`, and `chronic_absentee_count` remain pinned to the creation snapshot.

Reopening moves a `VALIDATED` or `REJECTED` extract back to `DRAFT` for rework (from anything else, `ERR_EXTRACT_NOT_DRAFT`) and clears `escalation_priority` back to `NONE`. `SUPERSEDED` and `ACCEPTED` extracts accept no further mutation of any kind — every attempt is `ERR_EXTRACT_NOT_DRAFT`.

Submission is the windowed gate. A `VALIDATED` extract (else `ERR_EXTRACT_NOT_VALIDATED`) may be submitted only while the logical clock reads inside the spec's half-open submission window — on or after `submission_window_opens_at` and strictly before `submission_window_closes_at`, a reading exactly at the close already failing with `ERR_SUBMISSION_WINDOW_CLOSED` — and only while `invalid_record_count` stands at zero (else `ERR_EXTRACT_HAS_ERRORS`). Submission stamps `submitted_at` with the current logical clock and moves the extract to `SUBMITTED`.

Resolution records the state authority's verdict: a `SUBMITTED` extract (else `ERR_EXTRACT_NOT_SUBMITTED`) moves to `ACCEPTED` or to `REJECTED` according to the supplied `outcome`. `ACCEPTED` is terminal. A `REJECTED` verdict recomputes `escalation_priority` from the time pressure: the whole hours remaining from the current logical clock until `submission_window_closes_at`, truncating partial hours, are compared against the escalation window of 48 hours — 48 hours or fewer remaining yields `URGENT` (exactly 48 is urgent), anything more yields `STANDARD`. From `REJECTED`, the path forward is reopen-and-rework or supersession by a fresh extract.

### 3.8. Portal Provisioning and Platform Integration

Parent and student access is provisioned deliberately. A `DistrictAdmin` creates a portal account for a `student_id`, choosing the `account_type` — `PARENT` or `STUDENT` — and the `access_level` — `FULL`, `GRADES_ONLY`, or `ATTENDANCE_ONLY`. The `grade_visibility` setting — `ALL_GRADES`, `CURRENT_TERM_ONLY`, or `HIDDEN` — defaults to `CURRENT_TERM_ONLY` when omitted. Accounts begin `INVITED`; activation moves `INVITED` → `ACTIVE` (from anything else, `ERR_PORTAL_ACCOUNT_NOT_INVITED`), and revocation moves `INVITED` or `ACTIVE` to the terminal `REVOKED` (an already-`REVOKED` account rejects further transitions and updates with `ERR_PORTAL_ACCOUNT_REVOKED`). While an account is not `REVOKED`, the district administrator may update its `access_level` and/or `grade_visibility`, each update incrementing the account's `version`. Two outside forces also touch accounts: graduation revokes every `INVITED` or `ACTIVE` account of the graduating student (§3.9), and a `PortalUser` may read only the account whose `id` equals their own `X-User-ID`, per §2.1.

Roster synchronization to external platforms runs through integration feeds. A `DistrictAdmin` registers a feed with its `district_id` and a `platform` — `ASSESSMENT`, `FOOD_SERVICE`, `TRANSPORTATION`, or `LMS` — with at most one feed per district-and-platform pair (a second registration is `ERR_DUPLICATE_FEED`). Feeds begin `PENDING` and have no terminal state: synchronization may be attempted from `PENDING`, `FAILED`, or `IN_SYNC` alike. When the district is `LIVE`, a sync succeeds — the feed moves to `IN_SYNC` (re-syncing an already-`IN_SYNC` feed is legal and simply refreshes), `last_synced_roster_count` records the number of the district's students currently in `ENROLLED` status, and `last_synced_at` stamps the current logical clock; until the first success both remain null. When the district is not `LIVE` — still `IMPLEMENTATION`, or `SUSPENDED` — the sync does not error; it lands the feed in `FAILED` as a plain business outcome, leaving the snapshot fields untouched.

### 3.9. Year-End Rollover: Promotion, Graduation, and Compensation

Rollover closes one year and opens the next as a single, reversible saga. A `DistrictAdmin` creates a rollover run with the `district_id`, the `source_school_year_id`, the `target_school_year_id` — which must differ from the source — and, per §2.9, the `expected_district_version`. Creating a run supersedes any still-`PENDING` run of the same district and increments the district's `version` by one; the new run begins `PENDING`.

Execution is where the district freezes its gates. Moving a run `PENDING` → `COMMITTED` requires, in pipeline order: the run to be `PENDING` (else `ERR_ROLLOVER_NOT_PENDING`); the source year to be `CLOSED_FOR_REPORTING` (else `ERR_SOURCE_YEAR_NOT_CLOSED`); the target year to be `OPEN` (else `ERR_TARGET_YEAR_NOT_OPEN`); the district to be `LIVE` (else `ERR_DISTRICT_NOT_LIVE`); and no other `COMMITTED` run to exist for the same source year (else `ERR_ROLLOVER_ALREADY_COMMITTED`). The committed run then executes its cascade atomically:

- Every `ACTIVE` enrollment of the source year completes, moving `ACTIVE` → `COMPLETED`.
- Grade-12 completions graduate their students — `ENROLLED` → `GRADUATED` — and each graduation revokes that student's `INVITED` or `ACTIVE` portal accounts, moving them to `REVOKED`.
- Each completion below grade 12 promotes the student by creating a new `ACTIVE` enrollment in the target year, with `grade_level` advanced by one and `entry_date` set to the target year's `start_date`.
- `INACTIVE` students holding no `ACTIVE` enrollment in the source year are archived, moving to `ARCHIVED`.
- The source year itself moves `CLOSED_FOR_REPORTING` → `ROLLED_OVER`, and its `COMMITTED` sections move to `LOCKED`.
- The run records its tallies — `promoted_count` of promoted enrollments, `graduated_count` of grade-12 completions, and `archived_student_count` of archived students — and the district's `version` increments by one.

Compensation unwinds a committed run. Moving `COMMITTED` → `COMPENSATED` (from anything else, `ERR_ROLLOVER_NOT_COMMITTED`) reverses each arm of the cascade: the target-year enrollments the run created are deleted; the source-year enrollments it completed return from `COMPLETED` to `ACTIVE` with their `exit_date` values unchanged; students it graduated return from `GRADUATED` to `ENROLLED`, and students it archived return from `ARCHIVED` to `INACTIVE`; the portal accounts its graduations revoked return from `REVOKED` to `ACTIVE`; the source year returns from `ROLLED_OVER` to `CLOSED_FOR_REPORTING` with its `LOCKED` sections restored to `COMMITTED`; and the run's counters reset to zero while the district's `version` increments once more.

The conservation invariant binds the pair: an execute followed by a compensate on the same run must restore the count of `ACTIVE` enrollments in each school year, every student's `status`, every portal account status the run touched, and the source year with its sections, all to their pre-execute values. A run that completes execute but leaves any of these drifted after compensate violates the invariant.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a district, a school year, a student, an extract) or add a new, distinct resource to a collection (an attendance event, a roster link) return `201 Created`. Operations that modify or transition an existing resource, and all reads, return `200 OK`. The table below is a structural index only; request payloads, response payloads, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/sis/districts` | Create a district in `IMPLEMENTATION` | PlatformAdmin |
| GET | `/sis/districts` | List districts | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/districts/{id}` | Get one district | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/districts/{id}/activate` | Activate (or reinstate) a district to `LIVE` | PlatformAdmin |
| POST | `/sis/districts/{id}/suspend` | Suspend a `LIVE` district | PlatformAdmin |
| POST | `/sis/school-years` | Create a school year in `PLANNING` | DistrictAdmin |
| GET | `/sis/school-years` | List school years | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/school-years/{id}` | Get one school year | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/school-years/{id}/open` | Open a year (`PLANNING` → `OPEN`) | DistrictAdmin |
| POST | `/sis/school-years/{id}/close-for-reporting` | Close a year for reporting | DistrictAdmin |
| POST | `/sis/school-years/{id}/archive` | Archive a rolled-over year | DistrictAdmin |
| POST | `/sis/collection-specs` | Create a state collection spec in `DRAFT` | PlatformAdmin |
| GET | `/sis/collection-specs` | List collection specs | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/collection-specs/{id}/publish` | Publish a spec, auto-retiring same-state predecessors | PlatformAdmin |
| POST | `/sis/collection-specs/{id}/retire` | Retire a `PUBLISHED` spec | PlatformAdmin |
| POST | `/sis/students` | Register a student (`PRE_REGISTERED`) | Registrar |
| GET | `/sis/students` | List students; `ARCHIVED` excluded unless filtered | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/students/{id}` | Get one student | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/courses` | Create a course catalog entry | Registrar |
| GET | `/sis/courses` | List courses | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/courses/{id}` | Get one course | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/sections` | Create a section in `DRAFT` | Registrar |
| GET | `/sis/sections` | List sections | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/sections/{id}` | Get one section | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/sections/{id}/roster` | List actively rostered enrollments of the section | DistrictAdmin, Registrar |
| POST | `/sis/sections/{id}/commit` | Commit a section (`DRAFT` → `COMMITTED`) | Registrar |
| POST | `/sis/sections/{id}/cancel` | Cancel a section and clear its roster | Registrar |
| POST | `/sis/sections/{id}/assign-teacher` | Assign, replace, or unassign the section's teacher | Registrar |
| POST | `/sis/sections/{id}/roster-adds` | Add an `ACTIVE` enrollment to the roster | Registrar |
| POST | `/sis/sections/{id}/roster-drops` | Drop an enrollment from the roster | Registrar |
| POST | `/sis/enrollments` | Create an `ACTIVE` enrollment | Registrar |
| GET | `/sis/enrollments` | List enrollments | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/enrollments/{id}` | Get one enrollment | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/enrollments/{id}/withdraw` | Withdraw an enrollment (`ACTIVE` → `WITHDRAWN`) | Registrar |
| POST | `/sis/enrollments/{id}/reenter` | Re-enter a withdrawn enrollment | Registrar |
| POST | `/sis/enrollments/{id}/attendance-events` | Post an attendance mark to the enrollment | Registrar |
| GET | `/sis/enrollments/{id}/attendance-events` | List the enrollment's attendance events in pinned order | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/discipline-incidents` | Report a discipline incident | Registrar |
| GET | `/sis/discipline-incidents` | List discipline incidents | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/discipline-incidents/{id}` | Get one incident | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/discipline-incidents/{id}/approve` | Approve an incident (`REPORTED` → `APPROVED`) | Registrar |
| POST | `/sis/discipline-incidents/{id}/void` | Void an incident, reversing any OSS absence cascade | Registrar |
| POST | `/sis/reporting-extracts` | Create a `DRAFT` extract snapshot | StateReporter |
| GET | `/sis/reporting-extracts` | List reporting extracts | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/reporting-extracts/{id}` | Get one extract | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/reporting-extracts/{id}/validate` | Validate an extract, recomputing invalid-record count | StateReporter |
| POST | `/sis/reporting-extracts/{id}/reopen` | Reopen an extract for rework | StateReporter |
| POST | `/sis/reporting-extracts/{id}/submit` | Submit an extract inside the submission window | StateReporter |
| POST | `/sis/reporting-extracts/{id}/resolve` | Record the state authority's `ACCEPTED`/`REJECTED` outcome | StateReporter |
| POST | `/sis/portal-accounts` | Provision a portal account (`INVITED`) | DistrictAdmin |
| GET | `/sis/portal-accounts` | List portal accounts | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/portal-accounts/{id}` | Get one portal account; `PortalUser` callers only their own | DistrictAdmin, PortalUser |
| POST | `/sis/portal-accounts/{id}/activate` | Activate an invited account | DistrictAdmin |
| POST | `/sis/portal-accounts/{id}/revoke` | Revoke an account | DistrictAdmin |
| POST | `/sis/portal-accounts/{id}/update-access` | Update access level and/or grade visibility | DistrictAdmin |
| POST | `/sis/integration-feeds` | Register an integration feed (`PENDING`) | DistrictAdmin |
| GET | `/sis/integration-feeds` | List integration feeds | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/integration-feeds/{id}` | Get one integration feed | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/integration-feeds/{id}/sync` | Synchronize the roster snapshot | DistrictAdmin |
| POST | `/sis/rollover-runs` | Create a `PENDING` rollover run | DistrictAdmin |
| GET | `/sis/rollover-runs` | List rollover runs | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| GET | `/sis/rollover-runs/{id}` | Get one rollover run | PlatformAdmin, DistrictAdmin, Registrar, StateReporter |
| POST | `/sis/rollover-runs/{id}/execute` | Execute a run, committing the full rollover cascade | DistrictAdmin |
| POST | `/sis/rollover-runs/{id}/compensate` | Compensate a committed run, reversing the cascade | DistrictAdmin |

## 5. Error Code Catalogue

The catalogue below is an index of identifiers and statuses only; the conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_DISTRICT_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_YEAR_NOT_FOUND` | 404 Not Found |
| `ERR_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PORTAL_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_FEED_NOT_FOUND` | 404 Not Found |
| `ERR_ROLLOVER_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_ROSTER_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRICT_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_DISTRICT_NOT_LIVE` | 409 Conflict |
| `ERR_YEAR_NOT_PLANNING` | 409 Conflict |
| `ERR_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_YEAR_NOT_ROLLED_OVER` | 409 Conflict |
| `ERR_SPEC_NOT_DRAFT` | 409 Conflict |
| `ERR_SPEC_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SPEC_MAPS_INCOMPLETE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_WITHDRAWN` | 409 Conflict |
| `ERR_SECTION_NOT_DRAFT` | 409 Conflict |
| `ERR_SECTION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SECTION_NOT_ROSTERABLE` | 409 Conflict |
| `ERR_INCIDENT_NOT_REPORTED` | 409 Conflict |
| `ERR_INCIDENT_ALREADY_VOIDED` | 409 Conflict |
| `ERR_EXTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_EXTRACT_NOT_VALIDATED` | 409 Conflict |
| `ERR_EXTRACT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_EXTRACT_HAS_ERRORS` | 409 Conflict |
| `ERR_PORTAL_ACCOUNT_NOT_INVITED` | 409 Conflict |
| `ERR_PORTAL_ACCOUNT_REVOKED` | 409 Conflict |
| `ERR_SOURCE_YEAR_NOT_CLOSED` | 409 Conflict |
| `ERR_TARGET_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_ROLLOVER_NOT_PENDING` | 409 Conflict |
| `ERR_ROLLOVER_ALREADY_COMMITTED` | 409 Conflict |
| `ERR_ROLLOVER_NOT_COMMITTED` | 409 Conflict |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_DISTRICT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_COUNT_DATE_OUTSIDE_YEAR` | 422 Unprocessable Entity |
| `ERR_ENTRY_OUTSIDE_YEAR` | 422 Unprocessable Entity |
| `ERR_WITHDRAWAL_OUTSIDE_YEAR` | 422 Unprocessable Entity |
| `ERR_REENTRY_OUTSIDE_YEAR` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_OUTSIDE_ENROLLMENT` | 422 Unprocessable Entity |
| `ERR_YEAR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SECTION_TIME_OVERLAP` | 409 Conflict |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_UNMAPPED_ATTENDANCE_CODE` | 422 Unprocessable Entity |
| `ERR_UNMAPPED_DISCIPLINE_CODE` | 422 Unprocessable Entity |
| `ERR_UNMAPPED_PROGRAM_CODE` | 422 Unprocessable Entity |
| `ERR_TEACHER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STUDENT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_COURSE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_ROSTER` | 409 Conflict |
| `ERR_DUPLICATE_FEED` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STALE_SCHOOL_YEAR_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DISTRICT_VERSION` | 412 Precondition Failed |
