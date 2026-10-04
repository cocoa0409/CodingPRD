# Test Center Network Score Security API — Product Requirements Document

## 1. Introduction

Running a defensible high-stakes testing program means being able to prove two things at once: that every seat in every room was administered under controlled, auditable conditions, and that every reported score survived a rigorous integrity screen before it reached an institution. This document specifies the Test Center Network, Score Cancellation & Security Investigation API (mounted under `/ets`), the operational backbone for that program. It governs how test centers apply for and retain authorization through a periodic audit program, how test sessions are scheduled against physical seat capacity with a protected accommodation pool, and how examinees are verified at the door through document and biometric checks before a single answer is scored.

Beyond test-day logistics, the API carries the full post-administration integrity pipeline: psychometric score analysis screens every record for anomalous gains and response similarity, security investigations open formal review cases in which the examinee is notified and given a structured window to respond, and adjudication can uphold or cancel a score — with cancellation recalling every institutional report already sent and, in content-exposure cases, barring the examinee from future registrations. The specification is written for the engineering team that will implement the service; every rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. If either header is missing or malformed, or the role name is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the role is declared but not permitted on the target endpoint, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles: `ProgramAdmin`, `Auditor`, `CenterManager`, `Proctor`, `Examinee`, and `ScoreAnalyst`.

- A `ProgramAdmin` is the program operator: this role owns test-center applications, audit scheduling, staffing, session creation, accommodation decisions, irregularity resolution, review-case adjudication, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by` on an accommodation decision, as `adjudicator_id` on an adjudicated review case, or as `flagged_by_analyst_id` when the operator substantiates a content-exposure irregularity) but never compares it against any entity's `id`.
- An `Auditor` is the field auditor who records audit findings. An Auditor never schedules the audits they complete — scheduling belongs to `ProgramAdmin`. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `CenterManager` drives the session-day lifecycle and proctor assignments. When `X-User-Role` is `CenterManager`, `X-User-ID` is the `id` of the acting `Staff` row whose `staff_role` is `CENTER_MANAGER`; ownership-style checks on any resource that references a `Staff` record compare the resource's foreign-key field to `X-User-ID`.
- A `Proctor` performs check-in and files irregularity reports. When `X-User-Role` is `Proctor`, `X-User-ID` is the `id` of the acting `Staff` row whose `staff_role` is `PROCTOR`; the value is recorded as `recorded_by_staff_id` on check-in records and as `reported_by_staff_id` on irregularity reports, and filing rights are evaluated against the session's assigned proctor list.
- An `Examinee` is the test taker. When `X-User-Role` is `Examinee`, `X-User-ID` is the `id` of the acting `Examinee` record; an Examinee caller may act only on their own resources, so any operation whose target resolves to a different examinee's record is rejected with `ERR_UNAUTHORIZED`.
- A `ScoreAnalyst` performs psychometric operations: score entry, score analysis, examinee notification, and score reporting. When `X-User-Role` is `ScoreAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `flagged_by_analyst_id` on review cases the analysis opens, and segregation of duties forbids that same identifier from adjudicating the case.

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

A request whose path matches no defined route — or whose method is not defined on the matched route — fails with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and any supplied value must be at least 1 and at most 100. The `offset` parameter controls how many items are skipped and defaults to 0. A `limit` or `offset` that is not a valid integer, a `limit` outside its range, or a negative `offset` fails with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the full number of matching resources before pagination, and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped by the server when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including mutations performed by the system itself as cascade or recompute side effects. This is the field on which optimistic concurrency control operates.

Both `created_at` and `updated_at` are stamped from the logical clock (§2.5), forced strictly increasing in one-millisecond steps, so no two stamps ever tie.

One deliberate exception exists. A `CheckInRecord` is an immutable evidentiary artifact: it is appended once and never modified, so it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from check-in records.

### 2.5. The Logical Clock

All temporal rules in this document — registration windows, lock windows, late-arrival cut-offs, response deadlines, turnaround gaps — are evaluated against a server-maintained logical UTC clock, never against wall-clock time. Before any administrative set operation, the clock reads exactly `2026-09-01T00:00:00Z`. Fields rendered directly from the clock — `current_utc`, `response_deadline`, and `hold_until` — render without a fractional part when the value falls on a whole second, as in that literal.

A `ProgramAdmin`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, the clock adopts it, and the response reports the resulting value as `current_utc`. Advancing the clock is not a passive act — when the new clock value falls strictly later than the `response_deadline` of any review case still in `NOTIFIED` status, that case is swept into `WINDOW_EXPIRED` as part of the same operation (see §3.6).

### 2.6. Validation Pipeline and Priority Ordering

Every request passes through a single ordered validation pipeline. Checks are evaluated in the priority order below, and a failure at an earlier step masks every later step — for example, a missing header surfaces `ERR_UNAUTHENTICATED` before any other check runs, and a duplicate-registration conflict is reported only after authentication, authorization, body shape, path existence, state, compliance, referential, and temporal checks have all passed.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and well-formed, and the role names one of the six declared roles. Failure: `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Endpoint role authorization.** The caller's role is listed among the roles authorized for the endpoint. Failure: `ERR_UNAUTHORIZED` (HTTP 403).
3. **Request body shape.** Required fields are present and enum values and formats are valid: `institution_code` must be a string of 4 to 8 characters, each an uppercase letter A–Z or a digit 0–9; `section_raws` must be exactly 3 integers, each between 0 and 50 inclusive; `end_time` must be later than `start_time`; `reserved_accommodation_seats` must not exceed `total_seats`. Failure: `ERR_INVALID_REQUEST` (HTTP 400).
4. **Examinee ownership.** An `Examinee` caller may act only on their own resources: the `examinee_id` in a registration-create body must equal the caller's `X-User-ID`, and the respond, cancel, accommodation-create, and examinee-read paths must resolve to the caller's own examinee record. Failure: `ERR_UNAUTHORIZED` (HTTP 403). Ownership decidable by comparison alone — a body's `examinee_id` or an examinee-scoped path id — is enforced before any existence check; ownership that is an attribute of a resource that must first be loaded (registration-, score-, and review-case-scoped paths) is evaluated after loading, so a missing id there fails with `ERR_NOT_FOUND` under step 5 before the ownership comparison runs.
5. **Path existence.** Path-template resources are validated left to right — center first, then session, audit, or staff, then registration, score record, review case, or report. The first id that does not exist fails the request with `ERR_NOT_FOUND` (HTTP 404).
6. **State-machine preconditions.** The target resource is in a state from which the attempted transition is defined. Specific violations carry specific codes — registration against a session that is not `PUBLISHED` yields `ERR_SESSION_NOT_PUBLISHED`; publishing while the center is not `AUTHORIZED` yields `ERR_CENTER_NOT_AUTHORIZED`; check-in against a booking that is not `CONFIRMED` yields `ERR_INVALID_STATE`, against an attendance status that is not `PENDING` yields `ERR_ALREADY_CHECKED_IN`, or against a session that is not `LOCKED` yields `ERR_SESSION_NOT_LOCKED`; score entry or analysis against a session that is not `ADMINISTERED` yields `ERR_SESSION_NOT_ADMINISTERED`; analysis while some `COMPLETED` registration lacks a score record yields `ERR_SCORES_INCOMPLETE`; report sending against a `PENDING_ANALYSIS` score yields `ERR_SCORE_NOT_RELEASED` and against a `CANCELLED` score yields `ERR_SCORE_CANCELLED`; adjudication of a case that is neither `RESPONSE_RECEIVED` nor `WINDOW_EXPIRED` yields `ERR_ADJUDICATION_NOT_READY`. Every other from-state violation (a double completion of an audit, cancelling a `COMPLETED` registration, responding on an already-responded case, and so on) yields `ERR_INVALID_STATE` (HTTP 409).
7. **Compliance gates.** Registration creation rejects an examinee in `BANNED` status with `ERR_EXAMINEE_BANNED` (HTTP 403); adjudication rejects a caller whose `X-User-ID` equals the case's `flagged_by_analyst_id` with `ERR_SOD_VIOLATION` (HTTP 403) — the segregation-of-duties rule.
8. **Referenced-context integrity.** Proctor assignment requires the staff member's `center_id` to equal the session's `center_id` (failure: `ERR_PROCTOR_NOT_AT_CENTER`, HTTP 422); irregularity filing requires the caller's `X-User-ID` to be an element of the session's `proctor_staff_ids` (failure: `ERR_PROCTOR_NOT_ASSIGNED`, HTTP 403).
9. **Temporal conflicts.** A new session at the same `(center, test_date, room_label)` must leave a gap of at least 60 minutes to every existing non-`CANCELLED` session there (failure: `ERR_SESSION_OVERLAP`, HTTP 409); a proctor may not be assigned to two sessions on the same `test_date` whose half-open start-to-end intervals strictly overlap — back-to-back touching intervals are allowed (failure: `ERR_PROCTOR_OVERLAP`, HTTP 409); session lock requires the current UTC date to equal the session's `test_date` (failure: `ERR_LOCK_WINDOW_NOT_OPEN`, HTTP 422); a case response requires the current clock to be no later than `response_deadline` (failure: `ERR_RESPONSE_WINDOW_CLOSED`, HTTP 422); registration requires the current UTC date to be strictly earlier than the session's `test_date` — registration closes on the test date itself (failure: `ERR_REGISTRATION_WINDOW_CLOSED`, HTTP 422).
10. **Uniqueness and optimistic concurrency.** At most one live registration — `booking_status` `CONFIRMED` or `WAITLISTED` — may exist per (session, examinee) pair (failure: `ERR_DUPLICATE_REGISTRATION`, HTTP 409); the OCC fields `expected_session_version` and `expected_case_version` must equal the parent entity's current `version` (failure: `ERR_STALE_VERSION`, HTTP 412, detailed in §2.7).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each against the current `version` of a named parent entity.

Creating a registration under a session requires the request body to carry `expected_session_version`, holding the session `version` the client last observed. If the session's current `version` no longer matches — because another writer has registered, cancelled, or been promoted against the same session in the meantime, each of which legitimately changes the seat picture — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and no registration is created. Reading the session is the supported way to learn its current version before attempting the write.

Adjudicating a score review case requires the request body to carry `expected_case_version`, holding the case `version` the adjudicator last observed. If the case's current `version` has advanced — for example because an examinee response was recorded after the adjudicator read the file — the adjudication is rejected with `ERR_STALE_VERSION` (HTTP 412), so no adjudicator ever decides on a superseded view of the case. The review-case listing of a registration is the supported read path for a case's current version.

Both OCC fields are non-optional on their endpoints. Endpoints not named in this section do not accept a version field at all.

### 2.8. Numeric Precision and Rounding

All score, compliance, and similarity arithmetic in the system follows fixed precision rules; the rounding method throughout is round-half-up unless a rule states otherwise.

- Provisional scaled scores are integers: each section's weighted raw is rounded half-up to an integer first, and only then are the three section integers summed.
- Equated final scaled scores are integers. The session mean raw score is kept at exactly 2 decimal places, rounded half-up. The equating adjustment added to the provisional score is itself rounded half-up, where half-up is defined as the floor of the value plus one half — so a negative half rounds toward zero (an adjustment of minus six and a half becomes minus six, not minus seven).
- Audit compliance scores are integers, with the unannounced-audit deduction multiplier applied and rounded half-up before subtraction.
- Response similarity indices are computed to exactly 4 decimal places, rounded half-up, and then compared against the flagging threshold with an at-least comparison.
- Waitlist positions and seat counts are plain integers; waitlist positions are 1-based.

No monetary values exist in this domain; no other rounding conventions apply.

## 3. Business Logic & Workflows

### 3.1. Center Applications, Staffing, and the Audit Program

A test center enters the network when a `ProgramAdmin` files an application carrying the center's legal `name`, its declared `facility_seat_capacity` — an informational ceiling on physical seats that must be at least 1 — and an `equipment_list`, an array of strings (possibly empty), of required equipment items the operator attests to. A new center begins life with `authorization_status` set to `APPLIED`, `last_audit_outcome` set to `NONE`, and `active_staff_count` at zero.

Staffing is managed per center. A `ProgramAdmin` adds each staff member with a `full_name`, a `staff_role` of either `PROCTOR` or `CENTER_MANAGER`, and a `certification_level` of either `BASIC` or `ADVANCED`. Every staff creation recomputes the owning center's `active_staff_count`, which is defined as the number of staff rows whose `center_id` points at that center.

Authorization is earned — and lost — through audits. A `ProgramAdmin` schedules a `CenterAudit` for a center by supplying a `scheduled_date` in `YYYY-MM-DD` form and an `audit_type` of `ANNOUNCED` or `UNANNOUNCED`; the audit's `status` is born `SCHEDULED`, and its `outcome` remains `PENDING` until completion. Completion is the `Auditor`'s exclusive act: the auditor records four non-negative finding counts — `facility_findings`, `staffing_findings`, `equipment_findings`, and `high_severity_findings` — at which point the audit moves from `SCHEDULED` to `COMPLETED` and the compliance arithmetic runs. The base deduction is five points per facility finding, seven per staffing finding, and three per equipment finding. For an `ANNOUNCED` audit the `compliance_score` is 100 minus that base deduction, floored at zero; for an `UNANNOUNCED` audit the base deduction is first multiplied by one and a half and rounded half-up, then subtracted from 100 with the same zero floor. The `outcome` is `FAILED` whenever the `compliance_score` is below 80, and also whenever `high_severity_findings` is at least 1 — the severity branch is independent of the score, so a spotless count sheet with a single high-severity finding still fails at a score of 100. Otherwise the outcome is `PASSED`. The two variants can flip a result on identical evidence: findings of one facility, one staffing, and two equipment items score 82 and pass when announced, but score 73 and fail when unannounced.

The completed audit's outcome then drives the center's authorization state. A `PASSED` audit moves an `APPLIED` center to `AUTHORIZED`, and a `PASSED` audit likewise reinstates a `SUSPENDED` center back to `AUTHORIZED`, closing the suspension cycle; in both cases `last_audit_outcome` becomes `PASSED`. A `FAILED` audit on an `APPLIED` center is a self-loop — the center stays `APPLIED`, `last_audit_outcome` becomes `FAILED`, and nothing else fires, because a center that was never authorized has no live sessions to protect. A `FAILED` audit on an `AUTHORIZED` center is the severe path: the center transitions to `SUSPENDED`, `last_audit_outcome` becomes `FAILED`, and a three-hop cascade runs. First, every session of that center still in `DRAFT` or `PUBLISHED` status is cancelled outright. Second, for each session cancelled in the first hop, every registration whose `booking_status` is `CONFIRMED` or `WAITLISTED` has its `booking_status` moved to `CANCELLED`, while `attendance_status` is left untouched as historical record. Third, each cancelled session's `confirmed_count` and `waitlist_count` are recomputed — both become zero after the second hop — and each cancelled session's `version` increments by 1. The remaining combinations are inert beyond the ledger: a `PASSED` audit on an already-`AUTHORIZED` center changes only `last_audit_outcome`, and a `FAILED` audit on an already-`SUSPENDED` center sets `last_audit_outcome` to `FAILED` while the center stays `SUSPENDED` and no cascade fires.

### 3.2. Session Scheduling, Proctoring, and the Test-Day Lifecycle

Sessions are the bookable units of the network. A `ProgramAdmin` creates a session under a center by supplying the `test_date` (a `YYYY-MM-DD` UTC date), the `start_time` and `end_time` (both `HH:MM` UTC, with `end_time` strictly later than `start_time`), a `room_label` identifying the room within the center, the `total_seats` available for booking (at least 1), and the `reserved_accommodation_seats` carved out for accommodation registrations (at least 0 and never more than `total_seats`). A new session starts in `DRAFT` status with an empty `proctor_staff_ids` list, a `confirmed_count` of zero, and a `waitlist_count` of zero. Its `effective_general_cap` — the ceiling on confirmed general-pool bookings — is computed as `total_seats` minus `reserved_accommodation_seats` and tracks those fields.

Rooms turn over between administrations, so scheduling enforces a turnaround rule: a new session must leave a gap of at least 60 minutes to every existing non-`CANCELLED` session sharing the same center, `test_date`, and `room_label`, counting the new session's own start-to-end interval against each existing one. A tighter gap rejects the create with `ERR_SESSION_OVERLAP`.

From `DRAFT`, a `CenterManager` publishes the session, moving it to `PUBLISHED`. Publication requires the owning center's `authorization_status` to be `AUTHORIZED`; attempting it while the center is `APPLIED` or `SUSPENDED` is rejected with `ERR_CENTER_NOT_AUTHORIZED`. On the morning of the administration, the `CenterManager` locks the session: publication-to-lock moves `PUBLISHED` to `LOCKED` and requires the current logical-clock UTC date to equal the session's `test_date` exactly, failing with `ERR_LOCK_WINDOW_NOT_OPEN` on any other day. Locking is what opens check-in. Both publication and locking increment the session's `version` by 1.

Proctor staffing happens on the session. A `CenterManager` assigns a proctor by naming a `staff_id`; the named staff member's `center_id` must equal the session's `center_id`, else the assignment fails with `ERR_PROCTOR_NOT_AT_CENTER` — and a `staff_id` naming no existing staff member fails the same way with the same error. One proctor may not cover two sessions on the same `test_date` whose half-open start-to-end intervals strictly overlap — touching intervals, where one session ends exactly as another begins, are allowed — and a violating assignment fails with `ERR_PROCTOR_OVERLAP`. Only non-`CANCELLED` sessions count as existing coverage for this check, and the target session's own interval counts as coverage once the proctor is on it, so re-assigning a proctor already assigned to that same session fails with `ERR_PROCTOR_OVERLAP`. Each successful assignment appends the staff id to `proctor_staff_ids` and increments the session's `version` by 1.

Once the administration window has passed — the current logical-clock UTC datetime is at or later than the session's `test_date` combined with its `end_time` — the `CenterManager` closes administration, moving the session from `LOCKED` to `ADMINISTERED`; an attempt to close before that moment fails with `ERR_INVALID_STATE`. Closing triggers the no-show sweep: every registration of the session still holding `booking_status` `CONFIRMED` with `attendance_status` `PENDING` — a confirmed seat whose examinee never checked in — is moved to `NO_SHOW`. The session's `version` increments by 1. After score analysis completes (§3.5), the session moves from `ADMINISTERED` to `SCORED`. The only way a session reaches `CANCELLED` is the failed-audit cascade of §3.1, which can strike a session in `DRAFT` or `PUBLISHED`.

### 3.3. Examinees, Accommodations, Registration, and the Waitlist

Before anyone can sit a test, a `ProgramAdmin` creates the examinee's record: the `full_name` exactly as it appears on the identity document, the `date_of_birth` in `YYYY-MM-DD` form, the `id_document_type` — one of `PASSPORT`, `NATIONAL_ID`, or `DRIVERS_LICENSE` — the `id_document_number` that must later be presented verbatim at check-in, and the `id_document_expiry` in `YYYY-MM-DD` form (a document is expired when its expiry date is strictly earlier than the current UTC date). An examinee's `status` begins as `ACTIVE` and stays registrable unless a content-exposure cancellation later moves them to `BANNED` (§3.6). Their `biometric_template_ref` is null until the first successful check-in captures a template.

Accommodations follow their own approval lifecycle. An `Examinee` files a request naming an `accommodation_type` of `EXTENDED_TIME`, `SCREEN_READER`, `LARGE_PRINT`, or `SEPARATE_ROOM`; the request is born `SUBMITTED`. A `ProgramAdmin` then decides it by supplying a `decision` of `APPROVED` or `DENIED`, which stamps `decided_by` with the decider's identifier and moves the request to the chosen terminal state. Two types — `SCREEN_READER` and `LARGE_PRINT` — call for alternate-format test delivery, so the system derives `requires_alternate_format` as true for exactly those two types and false for the others. An approval has a lasting booking consequence: every future registration by that examinee computes `requires_accommodation_seat` as true.

Registration is the examinee's own act. An `Examinee` registers for a session with a payload carrying their `examinee_id` — which must equal the caller's `X-User-ID`, or the request fails `ERR_UNAUTHORIZED` — and the OCC field `expected_session_version` described in §2.7. The gate conditions, in the pipeline order of §2.6, are: the session must be `PUBLISHED` (else `ERR_SESSION_NOT_PUBLISHED`); the examinee must be `ACTIVE` (else `ERR_EXAMINEE_BANNED`); the current UTC date must be strictly earlier than the session's `test_date` — registration closes on test day itself (else `ERR_REGISTRATION_WINDOW_CLOSED`); no registration may already exist for the same session and examinee with `booking_status` `CONFIRMED` or `WAITLISTED` (else `ERR_DUPLICATE_REGISTRATION`); and the session version must not have advanced past the client's view (else `ERR_STALE_VERSION`).

Seat allocation runs on two pools. At creation the system — ignoring any client-supplied value — computes `requires_accommodation_seat` as true exactly when the examinee holds at least one `APPROVED` accommodation request at that moment, and derives the registration's `pool` as `ACCOMMODATION` when that flag is true and `GENERAL` otherwise. The general pool's size is the session's `effective_general_cap`; the accommodation pool's size is `reserved_accommodation_seats`. A pool's occupancy is the count of this session's registrations in that pool with `booking_status` `CONFIRMED`. When occupancy is below the pool size, the registration is created `CONFIRMED` with `attendance_status` `PENDING` and the session's `confirmed_count` increases by 1. A confirmed registration's `waitlist_position` is null — the field is only ever set while `booking_status` is `WAITLISTED`, and it returns to null on promotion or cancellation. When occupancy equals the pool size — the boundary is inclusive on the full side, never an error — the registration is instead created `WAITLISTED`, with `waitlist_position` set to the number of already-`WAITLISTED` registrations in the same session and pool plus one, and the session's `waitlist_count` increases by 1. Either way the session's `version` increments by 1. The seat invariant holds at all times for every session: confirmed plus waitlisted plus cancelled bookings equals the total registrations ever created for the session, and `confirmed_count` never exceeds `total_seats`.

Cancellation frees a seat and triggers promotion. An `Examinee` cancels their own registration, or a `ProgramAdmin` cancels any, provided the booking is still `CONFIRMED` or `WAITLISTED` and `attendance_status` is not `COMPLETED` — any other combination fails with `ERR_INVALID_STATE`. The cancelled booking's `waitlist_position` is cleared to null. When the cancelled booking was `WAITLISTED`, no seat opens: no promotion fires and the remaining waitlist positions are not renumbered. When the cancelled booking was `CONFIRMED` and a free seat therefore opens in its pool, exactly one waitlisted registration in the same session and pool is promoted: the one with the smallest `created_at` (server-stamped at millisecond precision, so ties cannot occur and no further tie-break exists). The promoted registration's `waitlist_position` becomes null, its `booking_status` becomes `CONFIRMED`, and the remaining waitlisted registrations in that pool have their positions recomputed as 1 through n in `created_at` ascending order. The session's `confirmed_count` and `waitlist_count` are recomputed and its `version` increments by 1. Cascade cancellations from a failed audit are the exception: because the session itself is being cancelled, no waitlist promotion fires for them.

### 3.4. Test-Day Identity Verification and Irregularity Reporting

On test day, admission is decided at the door by a `Proctor`; unlike irregularity filing, check-in carries no assignment gate — any caller in the `Proctor` role may perform it. Check-in requires the registration's `booking_status` to be `CONFIRMED` (else `ERR_INVALID_STATE`), its `attendance_status` to still be `PENDING` (else `ERR_ALREADY_CHECKED_IN`), and the session to be `LOCKED` (else `ERR_SESSION_NOT_LOCKED`). The proctor presents three observations: the `id_document_number` and `id_document_expiry` shown on the examinee's document, and a live `biometric_sample`, which must be present and a scalar value.

From these the system computes an immutable `CheckInRecord`. The `document_check_result` is `PASS` when the presented document number matches the examinee's stored `id_document_number` and the presented expiry is not strictly earlier than the current UTC date; otherwise it is `FAIL`. The `biometric_result` is `FIRST_CAPTURE` when the examinee's `biometric_template_ref` is still null, `MATCH` when the sample equals the stored template, and `MISMATCH` otherwise; a `FIRST_CAPTURE` sample is stored as the examinee's template only when the check-in is `ADMITTED` — a denied first capture stores nothing. The `admission_decision` is `ADMITTED` exactly when the document check passes, the biometric result is anything other than `MISMATCH`, and the arrival is no later than fifteen minutes after the session's `start_time`; in every other case it is `DENIED`. A denied record carries a `denial_reason` chosen by strict priority when several grounds fail at once — `DOCUMENT_MISMATCH` outranks `DOCUMENT_EXPIRED`, which outranks `BIOMETRIC_MISMATCH`, which outranks `LATE_ARRIVAL` — while an admitted record carries `NONE`. The record also stores the acting proctor's identifier as `recorded_by_staff_id`, a plain operator reference rather than a join key. The check-in moves the registration's `attendance_status` from `PENDING` to `ADMITTED` or `DENIED` to match the decision, and the record, once appended, can never be modified.

When something goes wrong in the room, an assigned proctor files an irregularity report against a registration of that session, supplying the `registration_id`, a `category` of `SEATING_VIOLATION`, `PROHIBITED_ITEM`, `BREAK_VIOLATION`, `SUSPECTED_IMPERSONATION`, or `CONTENT_EXPOSURE`, a reporter-assessed `severity` of `LOW` or `HIGH`, and a free-text `narrative`. A `registration_id` that names no registration of the session — whether because the id does not exist or because it belongs to another session — fails with `ERR_NOT_FOUND`. Filing is restricted to proctors actually assigned to the session: the caller's identifier must be an element of the session's `proctor_staff_ids`, else the filing is rejected with `ERR_PROCTOR_NOT_ASSIGNED`. The report stores the caller as `reported_by_staff_id` and denormalizes the session into a plain `session_id` field, and it begins life `FILED`.

Resolution belongs to a `ProgramAdmin`, who supplies a `resolution` of `SUBSTANTIATED` or `DISMISSED`; only a `FILED` report can be resolved. Dismissal simply closes the report as `DISMISSED`. Substantiation closes it as `SUBSTANTIATED` and, for the `CONTENT_EXPOSURE` category, reaches into the scoring pipeline: if a score record already exists for the report's registration, the system opens a `ScoreReviewCase` in `OPENED` status with `trigger_reason` `CONTENT_EXPOSURE` and `flagged_by_analyst_id` set to the resolver's identifier, and moves that score record into `UNDER_REVIEW` whether it was still `PENDING_ANALYSIS` or already `RELEASED`. If the record is already `UNDER_REVIEW` (or already `CANCELLED`), substantiation opens no further case and leaves the record unchanged. If no score record exists yet for the registration, substantiation opens no case. A record dragged from `RELEASED` back into `UNDER_REVIEW` does not disturb its institutional reports at this point: they stay `RELEASED` until adjudication decides the outcome. Substantiated reports of the other four categories carry no scoring side effect.

### 3.5. Score Entry and the Score Analysis Run

Once a session is `ADMINISTERED`, a `ScoreAnalyst` enters the raw results for each registration whose examinee was admitted. Score entry is valid only while the session is `ADMINISTERED` (else `ERR_SESSION_NOT_ADMINISTERED`) and only for a registration whose `attendance_status` is `ADMITTED`; it both creates the `ScoreRecord` — born `PENDING_ANALYSIS` with `scaled_score` still null and `released_report_count` at zero — and completes the attendance dimension, moving the registration from `ADMITTED` to `COMPLETED`. The analyst supplies the `section_raws` (exactly three integer section scores, each between 0 and 50 inclusive), the examinee's `prior_best_scaled_score` as the baseline for anomalous-gain detection, the `matched_responses_count` observed against the nearest seated peer (at least 0 and at most `total_scored_items`), the `total_scored_items` on the form (at least 1), and two booleans, `same_form` and `adjacent_seated`, describing the pairing.

Two quantities are derived immediately at entry. The `raw_total` is the plain sum of the three section raws. The `provisional_scaled_score` applies per-section weights — 1.2 to the first section, 0.8 to the second, 1.0 to the third — by multiplying each raw by its weight, rounding each product half-up to an integer first, and only then summing the three integers. The rounding order is pinned: summing the weighted raws first and rounding once is a rejected variant, and the difference is real — raws of 33, 21, and 40 yield per-section integers of 40, 17, and 40 for a provisional of 97, whereas the rejected sum-first order would round 96.4 to 96.

The analysis run itself is a `ScoreAnalyst` capability over a whole session, requested by `session_id`. The session must be `ADMINISTERED` (else `ERR_SESSION_NOT_ADMINISTERED`), and every registration of the session whose attendance is `COMPLETED` must already have exactly one score record — a gap fails the run with `ERR_SCORES_INCOMPLETE`. Because score entry is only possible for `COMPLETED` attendance, the analyzed set is exactly the session's score records.

Equated final scoring runs in a pinned order. First, the `raw_total` and `provisional_scaled_score` of every score record in the session are established. Second, the session mean raw is computed as the sum of all those raw totals divided by the number of records — the mean includes the record being scored — rounded half-up to 2 decimal places. Third, each record's `scaled_score` is its provisional score plus the equating adjustment, where the adjustment is half of the difference between the record's own raw total and the session mean raw, rounded half-up with half-up defined as the floor of the value plus one half, so negative halves round toward zero: an adjustment of minus six and a half lands on minus six. The provisional and equated variants genuinely diverge — a record with raw total 94 in a session whose mean raw is 107.00 finishes at 91 rather than its provisional 97.

Each record is then screened by two integrity signals. The anomalous-gain check subtracts `prior_best_scaled_score` from the new `scaled_score` and flags the record when the gain is at least 30 — a gain of exactly 30 flags, while 29 does not. The response-similarity check multiplies the match ratio (`matched_responses_count` divided by `total_scored_items`) by a form factor of 1.0 when `same_form` is true and 0.5 otherwise, and by an adjacency factor of 1.0 when `adjacent_seated` is true and 0.7 otherwise, rounds the product half-up to 4 decimal places, and flags the record only when that similarity index is at least 0.85 and, conjunctively, `matched_responses_count` is at least 20. The two gates interact non-linearly: 34 matches out of 40 items for a same-form adjacent pair yields 0.85 and flags, 33 of 40 yields 0.825 and does not, and 34 of 40 for a non-adjacent pair yields 0.595 and does not.

Records with no firing signal transition straight from `PENDING_ANALYSIS` to `RELEASED`, their `scaled_score` now final. A record with at least one firing signal transitions to `UNDER_REVIEW` — still receiving its final `scaled_score` — and the run opens a `ScoreReviewCase` for it in `OPENED` status, with `flagged_by_analyst_id` set to the running analyst's identifier and `trigger_reason` chosen by priority when several signals fire at once: `CONTENT_EXPOSURE` outranks `ANOMALOUS_GAIN`, which outranks `RESPONSE_SIMILARITY`. The run's response summarizes the sweep as `processed_count`, `flagged_count`, `released_count`, and the `opened_case_ids`. A record already `UNDER_REVIEW` when the run begins — possible only through a pre-existing content-exposure case — still receives its equated `scaled_score` and counts toward `processed_count`, but it stays `UNDER_REVIEW`, opens no new case, and counts toward neither `flagged_count` nor `released_count`. A run over a session with no score records at all succeeds with all three counts at zero and an empty `opened_case_ids`. When the run completes, the session itself transitions from `ADMINISTERED` to `SCORED`, incrementing its `version` by 1.

### 3.6. Score Review Cases: Notification, Response, and Adjudication

A `ScoreReviewCase` tracks one registration's score through the due-process pipeline. Whether the case was opened by the analysis run or by a substantiated exposure report, it begins `OPENED` with `response_deadline`, `examinee_response`, `adjudicator_id`, and `adjudication_rationale` all null and `adjudication_outcome` at `NONE`.

A `ScoreAnalyst` notifies the examinee, moving the case from `OPENED` to `NOTIFIED`; notification stamps the `response_deadline` as the current logical clock plus 30 days and increments the case's `version` by 1. From that moment the examinee holds a 30-day window to respond in writing.

The examinee's response is their own act: the caller must be the examinee whose registration the case concerns — a caller whose `X-User-ID` differs from that examinee's id is rejected with `ERR_UNAUTHORIZED`. The case must be in `NOTIFIED` or `WINDOW_EXPIRED` status at the state level, and the current clock must be no later than the case's `response_deadline`, or the submission fails with `ERR_RESPONSE_WINDOW_CLOSED`. A valid submission stores the supplied `response_text` as `examinee_response`, moves the case to `RESPONSE_RECEIVED`, and increments its `version` by 1. Separately, time itself can close the window: when the logical clock is advanced strictly past a `NOTIFIED` case's `response_deadline`, the set-clock sweep moves that case to `WINDOW_EXPIRED` (§2.5).

Adjudication is reserved for a `ProgramAdmin` and becomes available once the file is complete — the case must be `RESPONSE_RECEIVED` or `WINDOW_EXPIRED`, and an attempt while it is `OPENED`, or still `NOTIFIED` with the window open, fails with `ERR_ADJUDICATION_NOT_READY`. Two further guards apply: segregation of duties forbids the adjudicator from being the analyst who flagged the case, so a caller whose `X-User-ID` equals the case's `flagged_by_analyst_id` is rejected with `ERR_SOD_VIOLATION`; and the OCC field `expected_case_version` must match the case's current `version` per §2.7, else `ERR_STALE_VERSION`. The adjudicator supplies an `outcome` of `UPHELD` or `CANCELLED` together with a `rationale`; the decision stamps `adjudicator_id`, `adjudication_rationale`, and `adjudication_outcome`, increments the case's `version` by 1, and moves the case to `ADJUDICATED_UPHELD` or `ADJUDICATED_CANCELLED` respectively.

An `UPHELD` adjudication vindicates the score: the score record moves from `UNDER_REVIEW` to `VALIDATED` and then immediately on to `RELEASED` as a single mutation — `VALIDATED` is transient and never persisted, so the record's `version` increments exactly once — and every institutional report of that record still `HELD` is released with it — `released_at` set to the clock, `hold_until` cleared to null, and the record's `released_report_count` increased by 1 for each such report.

A `CANCELLED` adjudication detonates the record. The score moves to `CANCELLED` — this holds whether it sat `UNDER_REVIEW` or had been `RELEASED` before a content-exposure case dragged it back under review — and a cascade runs in hops. First, every score report of the record in `HELD` or `RELEASED` status is recalled to `RECALLED` with `recalled_at` set to the clock. Second, the ledger resyncs: the record's `released_report_count` is recomputed and becomes 0. Third, when the case's `trigger_reason` is `CONTENT_EXPOSURE`, the owning examinee transitions from `ACTIVE` to `BANNED`; existing registrations are left untouched as historical record, but every future registration attempt by that examinee is rejected with `ERR_EXAMINEE_BANNED`.

### 3.7. Score Reporting to Institutions

The outward face of the pipeline is the `ScoreReport`, created by a `ScoreAnalyst` naming the recipient's `institution_code`. The code must be 4 to 8 characters drawn solely from uppercase letters and digits, or the request fails shape validation with `ERR_INVALID_REQUEST`.

What a new report becomes depends entirely on the score record's `status` at creation. For a score in `RELEASED`, the report is born `RELEASED`: its `released_at` is stamped with the clock, its `hold_until` stays null, and the record's `released_report_count` increases by 1. A score that reached `RELEASED` by surviving an upheld review — passing through `VALIDATED` — reports identically to one released directly by the analysis run. For a score in `UNDER_REVIEW`, the report is instead born `HELD`, and its `hold_until` is set to the `response_deadline` of the review case currently open on that score's registration. A score still in `PENDING_ANALYSIS` rejects the send with `ERR_SCORE_NOT_RELEASED`, and a `CANCELLED` score rejects it with `ERR_SCORE_CANCELLED`. In all cases the report's `score_record_id` binds it to the record it was created from, and both `released_at` and `recalled_at` remain null until the report first enters the corresponding state.

Reports then track the investigation's outcome without further operator action. When an upheld adjudication releases the underlying score, each `HELD` report flips to `RELEASED`, stamping `released_at` with the clock and clearing `hold_until`. When a cancellation fires, every report of the record — whether `HELD` or already `RELEASED` — moves to `RECALLED` with `recalled_at` stamped, and the record's `released_report_count` falls accordingly, each recalled formerly-released report subtracting one until the count reaches zero. The `released_report_count` is, at every moment, exactly the number of this record's reports currently in `RELEASED` status, recomputed on every report creation, release, and recall. The score record's own `version` (and `updated_at`) advances only when the recomputed count actually changes — so creating a `HELD` report leaves the record untouched, while creating a `RELEASED` report bumps it exactly once.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a test center, staff member, audit, session, examinee, accommodation request, registration, check-in record, irregularity report, score record, or score report — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions such as publish, lock, administer, cancel, resolve, decide, notify, respond, adjudicate, the analysis run, and the clock set — return `200 OK`. The full request and response semantics of each operation live in §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ets/test-centers` | Create a test-center application (starts `APPLIED`) | ProgramAdmin |
| GET | `/ets/test-centers/{id}` | Read one test center | ProgramAdmin, Auditor, CenterManager, Proctor, ScoreAnalyst |
| POST | `/ets/test-centers/{id}/audits` | Schedule a periodic audit for a center | ProgramAdmin |
| GET | `/ets/test-centers/{id}/audits` | List audits of a center | ProgramAdmin, Auditor |
| POST | `/ets/audits/{id}/complete` | Record audit findings; computes compliance score and outcome and drives the center authorization transition | Auditor |
| POST | `/ets/test-centers/{id}/staff` | Add a staff member to a center | ProgramAdmin |
| GET | `/ets/test-centers/{id}/staff` | List staff of a center | ProgramAdmin, CenterManager |
| POST | `/ets/test-centers/{id}/sessions` | Create a session (`DRAFT`); enforces the 60-minute same-room turnaround | ProgramAdmin |
| GET | `/ets/test-centers/{id}/sessions` | List sessions of a center | ProgramAdmin, CenterManager, Proctor, ScoreAnalyst |
| GET | `/ets/sessions/{id}` | Read one session (source of the current version for `expected_session_version`) | ProgramAdmin, CenterManager, Proctor, ScoreAnalyst, Examinee |
| POST | `/ets/sessions/{id}/publish` | Publish a `DRAFT` session; requires the center `AUTHORIZED` | CenterManager |
| POST | `/ets/sessions/{id}/lock` | Lock a `PUBLISHED` session on its test date; opens check-in | CenterManager |
| POST | `/ets/sessions/{id}/administer` | Close administration of a `LOCKED` session after end time; sweeps no-shows | CenterManager |
| POST | `/ets/sessions/{id}/proctors` | Assign a proctor to a session | CenterManager |
| POST | `/ets/examinees` | Create an examinee record (`ACTIVE`) | ProgramAdmin |
| GET | `/ets/examinees/{id}` | Read one examinee; an Examinee caller may only read their own record | ProgramAdmin, ScoreAnalyst, Examinee |
| GET | `/ets/examinees/{id}/registrations` | List registrations of an examinee | ProgramAdmin, ScoreAnalyst, Examinee |
| POST | `/ets/examinees/{id}/accommodation-requests` | File an accommodation request (`SUBMITTED`) | Examinee |
| GET | `/ets/examinees/{id}/accommodation-requests` | List accommodation requests of an examinee | Examinee, ProgramAdmin |
| POST | `/ets/accommodation-requests/{id}/decide` | Approve or deny a `SUBMITTED` accommodation request | ProgramAdmin |
| POST | `/ets/sessions/{id}/registrations` | Register an examinee for a `PUBLISHED` session before the test date; pool selection, waitlisting, and session-version OCC apply | Examinee |
| GET | `/ets/sessions/{id}/registrations` | List registrations of a session | ProgramAdmin, CenterManager, Proctor, ScoreAnalyst |
| GET | `/ets/registrations/{id}` | Read one registration | ProgramAdmin, CenterManager, Proctor, ScoreAnalyst, Examinee |
| POST | `/ets/registrations/{id}/cancel` | Cancel a `CONFIRMED` or `WAITLISTED` registration (an Examinee cancels their own); auto-promotes the pool waitlist | Examinee, ProgramAdmin |
| POST | `/ets/registrations/{id}/check-in` | Perform identity verification; computes document, biometric, and admission outcomes and appends an immutable check-in record | Proctor |
| GET | `/ets/registrations/{id}/check-ins` | List check-in records of a registration | ProgramAdmin, CenterManager, Proctor |
| POST | `/ets/sessions/{id}/irregularity-reports` | An assigned proctor files an irregularity report against a registration of the session | Proctor |
| GET | `/ets/registrations/{id}/irregularity-reports` | List irregularity reports of a registration | ProgramAdmin, CenterManager, ScoreAnalyst |
| POST | `/ets/irregularity-reports/{id}/resolve` | Substantiate or dismiss a `FILED` report; a substantiated `CONTENT_EXPOSURE` opens a review case when a score record exists | ProgramAdmin |
| POST | `/ets/registrations/{id}/score-entry` | Enter the raw score for an `ADMITTED` registration of an `ADMINISTERED` session; creates the score record and completes attendance | ScoreAnalyst |
| GET | `/ets/registrations/{id}/score` | Return the score record of a registration as a zero-or-one-element array | ProgramAdmin, ScoreAnalyst, Examinee |
| GET | `/ets/registrations/{id}/review-cases` | List review cases of a registration (read path for a case's current version) | ProgramAdmin, ScoreAnalyst, Examinee |
| POST | `/ets/score-analysis/run` | Run score analysis over an `ADMINISTERED` session: equated scores, anomaly flags, case openings, auto-release; session becomes `SCORED` | ScoreAnalyst |
| POST | `/ets/score-review-cases/{id}/notify` | Notify the examinee that their score is under review; opens the 30-day response window | ScoreAnalyst |
| POST | `/ets/score-review-cases/{id}/respond` | The examinee submits their response within the response window | Examinee |
| POST | `/ets/score-review-cases/{id}/adjudicate` | Adjudicate a case after response or window expiry; segregation of duties and case-version OCC apply | ProgramAdmin |
| POST | `/ets/score-records/{id}/reports` | Send the score to an institution; a `RELEASED` score yields a `RELEASED` report, an `UNDER_REVIEW` score a `HELD` one | ScoreAnalyst |
| GET | `/ets/score-records/{id}/reports` | List reports of a score record | ProgramAdmin, ScoreAnalyst |
| GET | `/ets/score-records/{id}` | Read one score record | ProgramAdmin, ScoreAnalyst |
| POST | `/ets/_clock/set_current_utc` | Set the logical clock; sweeps `NOTIFIED` cases whose response deadline has passed into `WINDOW_EXPIRED` | ProgramAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return. Trigger conditions are specified in §2 and §3 where each error guards its workflow; this table fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CENTER_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_SESSION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SESSION_NOT_LOCKED` | 409 Conflict |
| `ERR_ALREADY_CHECKED_IN` | 409 Conflict |
| `ERR_SESSION_NOT_ADMINISTERED` | 409 Conflict |
| `ERR_SCORES_INCOMPLETE` | 409 Conflict |
| `ERR_SCORE_NOT_RELEASED` | 409 Conflict |
| `ERR_SCORE_CANCELLED` | 409 Conflict |
| `ERR_EXAMINEE_BANNED` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PROCTOR_NOT_AT_CENTER` | 422 Unprocessable Entity |
| `ERR_PROCTOR_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_PROCTOR_OVERLAP` | 409 Conflict |
| `ERR_LOCK_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_RESPONSE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_ADJUDICATION_NOT_READY` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
