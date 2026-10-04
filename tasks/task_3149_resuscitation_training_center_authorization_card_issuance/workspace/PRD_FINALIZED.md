# Resuscitation Training Center Authorization & Card Issuance API — Product Requirements Document

## 1. Introduction

Training centers that teach resuscitation — Basic Life Support, Advanced Cardiovascular Life Support, Pediatric Advanced Life Support, and Heartsaver first aid — operate inside a tightly regulated ecosystem. The national authorizing body (this document uses an American Heart Association–style model) must be able to vouch for every card its network issues: who taught the course, under which edition of the guidelines, on which manikins, in which physical site, and whether the instructor's own credentials were current at the moment of teaching. When a card is challenged in court after a bad outcome, the answers must come from data, not from memory.

This document specifies the API for that authorizing body's training-center operations platform. It covers the full lifecycle of an authorized training center (provisional onboarding, site alignment, suspension, probation, revocation), the instructor candidate pathway (monitoring, teaching evaluation, certification, renewal), the scheduling of individual course sessions with equipment and instructor-student ratio enforcement, checklist-based skills testing with a remediation pathway, the issuance of electronic completion cards with a verification surface for employers, and the quality assurance audit loop that holds the whole system honest. Guidelines updates — issued every few years by the national body — cascade through scheduled sessions with a defined transition deadline.

The platform is used by several distinct operator populations whose duties are deliberately segregated: the national office, training center administrators, scheduling coordinators, certified instructors acting as session leads, faculty who evaluate candidates, quality assurance auditors, and external employers verifying a provider's card. Every cross-cutting rule in §2 applies across the entire API; §3 walks the business workflows in narrative form and is the place to look for how the rules combine in practice.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to specific operations is restricted by role; an attempt to perform an action outside of a user's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes seven roles, with the following exact spellings: `NationalAdmin`, `TCAdmin`, `TCCoordinator`, `Instructor`, `TrainingFaculty`, `QAAuditor`, and `Employer`.

Two of the roles are entity-backed. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor` resource; session-lead and skills-evaluation ownership checks compare the session's `primary_instructor_id` to `X-User-ID`. When `X-User-Role` is `TrainingFaculty`, `X-User-ID` is likewise the `id` of an `Instructor` resource, and additionally that instructor must have `is_faculty` set to `true` and current `status` of `CERTIFIED`; monitoring and teaching-evaluation endpoints resolve the faculty's `id` from this header so the candidate cannot act on their own behalf.

The remaining five roles — `NationalAdmin`, `TCAdmin`, `TCCoordinator`, `QAAuditor`, and `Employer` — are opaque. For these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `opened_by` on a `QualityAudit` opened by a `QAAuditor`) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time-aware behavior in the platform is driven by a server-maintained logical clock, not by wall-clock time. At startup the clock is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time thereafter; it advances only when a `NationalAdmin` operator explicitly sets it to a supplied `to_iso8601` instant. Setting the clock performs an expiry sweep across the entire dataset, and the response body reports the new value as `current_utc`.

The sweep has two effects. Every `Instructor` in `CERTIFIED` status whose `renewal_due_at` is strictly earlier than the new clock value transitions to `EXPIRED`. Every `CourseCompletionCard` in `ACTIVE` status whose `expires_at` is strictly earlier than the new clock value transitions to `EXPIRED`, and the issuing center's `active_card_count` is decremented by one for each card expired (the lifetime `cards_issued_count` is never touched by an expiry). A card whose `expires_at` equals the new clock value exactly is still `ACTIVE` after the sweep; likewise an instructor whose `renewal_due_at` equals the new clock remains `CERTIFIED`. The boundary is strict-greater in both cases.

### 2.5. Validation Pipeline and Priority Ordering

Every mutating request passes through a validation pipeline whose checks run in a fixed order. A request that fails an earlier check is rejected immediately and never reaches a later check; the `error_id` returned is always the first failing rule.

1. **Authentication context (highest priority).** Both `X-User-ID` and `X-User-Role` headers must be present and non-empty, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The caller's role must be permitted for the endpoint per the authorization matrix in §4. This stage also enforces the identity checks that ride on role: a `TrainingFaculty` caller whose underlying instructor record lacks `is_faculty` or whose status is not `CERTIFIED` is rejected with `ERR_INSUFFICIENT_PERMISSIONS`, as is an `Instructor` caller whose `X-User-ID` does not match the session's `primary_instructor_id` when the endpoint requires session-lead ownership (the dedicated code `ERR_INSTRUCTOR_NOT_SESSION_LEAD` is used for that case).
3. **Existence of path resources.** Path identifiers are validated left to right; the first identifier that does not resolve yields the corresponding entity-specific not-found error. Body-supplied foreign keys are validated in endpoint input declaration order. See §2.6.
4. **Request shape.** Required fields present, enum members drawn from the declared sets, integer fields carrying integer values within sane ranges, and `end_at` strictly after `start_at`. Failures yield `ERR_INVALID_REQUEST`. An empty skills-checklist `items` array, or a checklist with no critical item, fails here as well.
5. **Optimistic concurrency.** When the endpoint declares an OCC input, the supplied `expected_training_center_version` must equal the center's current `version`, otherwise `ERR_STALE_VERSION`. See §2.10.
6. **State preconditions.** The target resource must be in the state required by the transition (`SCHEDULED` or `IN_PROGRESS` for a session, `ENROLLED` for a roster entry, `CANDIDATE`/`MONITORED`/`CERTIFIED`/`SUSPENDED`/`EXPIRED` for an instructor, `OPEN` for an audit, `ACTIVE` for a card, `DRAFT` for a guidelines version, and so on). State errors carry codes like `ERR_SESSION_NOT_IN_PROGRESS`, `ERR_INSTRUCTOR_NOT_MONITORED`, `ERR_AUDIT_NOT_OPEN`, `ERR_CARD_NOT_ACTIVE`, and `ERR_GUIDELINES_VERSION_CONFLICT`.
7. **Regulatory and safety gates.** Center status permits the operation (`ERR_CENTER_NOT_ACTIVE`, `ERR_CENTER_ON_PROBATION`, `ERR_CENTER_SUSPENDED`); site is `ALIGNED` and not suspended (`ERR_SITE_SUSPENDED`, `ERR_SITE_NOT_ALIGNED`); instructor is `CERTIFIED` and unexpired (`ERR_INSTRUCTOR_NOT_CERTIFIED`); faculty oversight is present when site alignment requires it (`ERR_NO_FACULTY_OVERSIGHT`); segregation of duties (`ERR_SELF_EVALUATION_FORBIDDEN`); discipline match between faculty and candidate, or between instructor and course (`ERR_FACULTY_DISCIPLINE_MISMATCH`, `ERR_INSTRUCTOR_DISCIPLINE_MISMATCH`); faculty required for `BLS_INSTRUCTOR` courses (`ERR_FACULTY_REQUIRED_FOR_INSTRUCTOR_COURSE`); the center has at least one `ALIGNED` site at activation time (`ERR_NO_ALIGNED_SITE`); the renewal window is open at renewal time (`ERR_RENEWAL_WINDOW_CLOSED`).
8. **Structural and capacity constraints.** Capacity does not exceed the site's `capacity_students` (`ERR_CAPACITY_EXCEEDS_SITE`); the equipment-sufficiency rule holds (`ERR_EQUIPMENT_RATIO_VIOLATION`); at most one `ACTIVE` alignment exists per (`training_center_id`, `instructor_id`) pair (`ERR_DUPLICATE_ACTIVE_ALIGNMENT`); renewal session-count floor (`ERR_RENEWAL_SESSION_SHORTFALL`); the two-evaluation minimum and 4.00 average floor at certification (`ERR_INSUFFICIENT_TEACHING_EVALUATIONS`, `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD`).
9. **Temporal checks.** The instructor double-booking rule (`ERR_SESSION_OVERLAP_INSTRUCTOR`), the site turnover-buffer rule (`ERR_SESSION_OVERLAP_SITE`), and the requirement that the guidelines version be `ACTIVE` at session creation (`ERR_GUIDELINES_VERSION_NOT_ACTIVE`).
10. **Cross-entity referential checks.** The session's `site_id` must belong to the supplied `training_center_id` (`ERR_SITE_CENTER_MISMATCH`); the `primary_instructor_id` must hold an `ACTIVE` alignment to the center (`ERR_INSTRUCTOR_NOT_ALIGNED`); a renewal enrollment's `prior_card_id` must point to a card whose `holder_email` matches the roster entry's `student_email` (`ERR_PRIOR_CARD_HOLDER_MISMATCH`); the two-attempt cap on skills evaluations (`ERR_REMEDIATION_LIMIT_EXCEEDED`).
11. **Quota check (lowest priority).** The session must have at least one seat available for a roster add (`ERR_SESSION_FULL`). This check runs last so that every other problem with the request surfaces first.

### 2.6. Nested Resource Retrieval

The API enforces strict hierarchical validation for any request that targets nested resources. When an endpoint path contains multiple resource identifiers (for example, a site nested under a center), the system validates the existence of each identifier in left-to-right order along the path. The request is rejected immediately with the 404 `error_id` corresponding to the *first* path identifier that does not resolve — `ERR_TRAINING_CENTER_NOT_FOUND` when the center id is unknown, `ERR_TRAINING_SITE_NOT_FOUND` when the site id is unknown, `ERR_INSTRUCTOR_NOT_FOUND` for an instructor, `ERR_ALIGNMENT_NOT_FOUND` for an alignment, `ERR_GUIDELINES_VERSION_NOT_FOUND` for a guidelines version, `ERR_SESSION_NOT_FOUND` for a course session, `ERR_ROSTER_ENTRY_NOT_FOUND` for a roster entry, `ERR_CARD_NOT_FOUND` when neither the card id nor the supplied card code resolves, `ERR_AUDIT_NOT_FOUND` for an audit, and the generic `ERR_NOT_FOUND` for any unmatched resource that does not fit a more specific code. A request for a site under a non-existent center is rejected with `ERR_TRAINING_CENTER_NOT_FOUND` before the site lookup is even attempted. Foreign keys supplied in the request body are then validated in the order the endpoint declares them in its input list.

### 2.7. Common Resource Properties

Most resources in the system share a standard set of system-managed fields. These entities are: `TrainingCenter`, `TrainingSite`, `Instructor`, `TCAlignment`, `GuidelinesVersion`, `CourseSession`, `RosterEntry`, `CourseCompletionCard`, and `QualityAudit`.

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified; refreshed on any mutation.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource; used for optimistic concurrency control where declared.

Four resource types are ledger-style, append-only records and intentionally carry only `id` and `created_at`. These are `CourseMonitoring`, `TeachingEvaluation`, `SkillsEvaluation`, and `AuditFinding`, plus the `CardVerification` event. For these five entities both `updated_at` and `version` are absent — the server must not return them and must not expect them on input.

### 2.8. Numeric Precision and Rounding

Two precision disciplines apply across the platform.

**Two-decimal monetary-style rounding.** Percentages and score-like quantities — specifically a skills evaluation's `score_percent`, the certification evaluation average, an audit finding's `deduction_points`, and an audit's `compliance_score` — are rounded to exactly 2 decimal places using round-half-up. The rounding is applied per finding before summing (see §3.8); sum-then-round is a forbidden alternative because it produces different cents.

**Whole-second and integer quantities.** Card expiry, instructor renewal deadlines, and all clock comparisons operate at whole-second precision. Capacity, seat counts, and card counts are integers with no rounding. Equipment-ratio requirements are computed as integer ceilings (rounded up to the next whole manikin, AED trainer, or instructor) and never involve fractional rounding.

### 2.9. Hierarchical Cascade Consistency

State changes at a parent level propagate to children. When a center, site, or instructor becomes non-operational, the system cancels dependent work and releases the affected seats; when a guidelines version is superseded, sessions tied to it are reconciled against the new version's transition deadline. Each cascade recomputes derived counters (the session's `seats_available`, the center's `active_card_count`) so that the seat-conservation and card-stock invariants described in §3 hold at every observable instant. A mutation of a center bumps its `version` and refreshes `updated_at`; cascades that originate from a center action therefore increment the center's version exactly once per originating call, not once per affected child.

### 2.10. Optimistic Concurrency Control

Two write endpoints take an optimistic-concurrency field, and only those two. Any endpoint not listed here takes no version field, and the server ignores a version field if one is supplied.

Aligning a site — moving it from `PENDING_ALIGNMENT` to `ALIGNED` — requires the request to carry `expected_training_center_version` matching the current `version` of the center that owns the site. If another writer has advanced the center's version since the client last read it (for example by aligning a different site, or by opening an audit), the align request is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client refreshes its view of the center before retrying.

Opening a quality audit against a center likewise requires the request to carry `expected_training_center_version` matching the center's current `version`. The audit's baseline must reflect the center's current governance state — its status and the set of aligned sites — so a stale version means the baseline has moved and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

## 3. Business Logic & Workflows

### 3.1. Authorizing a Training Center

A `NationalAdmin` operator onboards a new training organization by creating a `TrainingCenter` with its `legal_name`, `region`, and `contact_email`. The new center starts in `PROVISIONAL` status with `cards_issued_count` and `active_card_count` both at zero, `probation_started_at` null, and `last_audit_opened_at` null until the first audit is opened against it. The center is not yet permitted to deliver courses.

Before the center can go live it needs two things in place. First, a `TCAdmin` creates at least one physical site under the center, supplying the `name`, `street_address`, `city`, two-letter `state_code`, and the maximum number of students the site can host per session as `capacity_students` (an integer of at least 1). Newly created sites start in `PENDING_ALIGNMENT`. Second, the center must have faculty oversight: at least one `TCAlignment` row whose `status` is `ACTIVE`, whose `as_faculty` flag is `true`, and whose referenced instructor is currently `CERTIFIED`. Alignments are created by a `TCAdmin` with the `instructor_id` of a certified instructor and an optional `as_faculty` flag (defaulting to `false`); each alignment starts in `ACTIVE` and at most one `ACTIVE` alignment may exist for a given (`training_center_id`, `instructor_id`) pair — a second alignment for the same pair is rejected with `ERR_DUPLICATE_ACTIVE_ALIGNMENT`.

With oversight in place, a `TCAdmin` moves a site from `PENDING_ALIGNMENT` to `ALIGNED`. The align call carries `expected_training_center_version` per §2.10. Three preconditions run in order: the version must match the center's current `version` (otherwise `ERR_STALE_VERSION`); the owning center's status must be one of `PROVISIONAL`, `ACTIVE`, or `PROBATION` (a `SUSPENDED` or `REVOKED` center rejects the align with `ERR_CENTER_SUSPENDED`); and the center must have faculty oversight as described above (otherwise `ERR_NO_FACULTY_OVERSIGHT`). A successful align increments the center's `version` by 1.

Only once at least one site is `ALIGNED` may a `NationalAdmin` activate the center, moving it from `PROVISIONAL` to `ACTIVE`. If no site is `ALIGNED` the activation is rejected with `ERR_NO_ALIGNED_SITE`. Activation increments the center's `version` by 1.

A center that has drifted out of good standing moves through `PROBATION` and `SUSPENDED` on its way to terminal `REVOKED`. Reinstatement from `PROBATION` returns the center to `ACTIVE`; reinstatement from `SUSPENDED` returns it to `PROBATION`, not directly to `ACTIVE`. The reinstate endpoint requires the center to currently be `PROBATION` or `SUSPENDED`; any other status is rejected with `ERR_CENTER_NOT_ACTIVE`. (The `ERR_CENTER_REVOKED` code is reserved for the center lifecycle endpoints that special-case a `REVOKED` target — activation, suspension, and revocation itself — and is not used by reinstatement.) Both reinstatements require that no `QualityAudit` targeting the center is still `OPEN` — otherwise `ERR_AUDIT_STILL_OPEN`. When a center leaves `PROBATION` (reinstate to `ACTIVE`), its `probation_started_at` is cleared to null; when it enters `PROBATION` (either from `ACTIVE` via corrective-action audit close, or from `SUSPENDED` via reinstate), `probation_started_at` is stamped with the current clock. Sites that were suspended by the cascade remain `SUSPENDED` after the center is reinstated; each site must be individually reinstated by a `TCAdmin`. Revoking a `SUSPENDED` center is terminal and irreversible: every site that is not already `DECOMMISSIONED` becomes `DECOMMISSIONED`, every `ACTIVE` alignment becomes `ENDED`, and every remaining `SCHEDULED` session of the center is cancelled with `cancel_reason` set to `CENTER_SUSPENDED`, with `ENROLLED` roster entries on those sessions cancelled in turn.

### 3.2. The Instructor Candidate Pathway

Instructors enter the system through a `NationalAdmin` registration carrying `full_name`, `email`, a `discipline` drawn from `BLS`, `ACLS`, `PALS`, or `HEARTSAVER`, and the `home_training_center_id` of their home center. The default entry state is `CANDIDATE`. A `legacy_certified` boolean on the registration payload (defaulting to `false`) supports bulk import of instructors who are already certified in a legacy system: when set to `true` the instructor is created directly in `CERTIFIED` status, `certified_since` is stamped with the current clock, and `renewal_due_at` is set to twenty-four months after the current clock.

A candidate's road to certification has three gates. First, a `TrainingFaculty` operator records a course monitoring against the candidate, supplying the `monitored_at` timestamp and the `course_type_observed` — one of `BLS_PROVIDER`, `ACLS_PROVIDER`, `PALS_PROVIDER`, or `HEARTSAVER` — together with an `outcome` of `SATISFACTORY` or `UNSATISFACTORY`. Five preconditions guard this step, evaluated in this order: the candidate must currently be in `CANDIDATE` status (otherwise `ERR_INSTRUCTOR_NOT_CANDIDATE`); the calling faculty's underlying instructor record must satisfy the §2.5 level-2 faculty-identity gate — `is_faculty` true and status `CERTIFIED` (otherwise `ERR_INSUFFICIENT_PERMISSIONS`, which therefore takes precedence over the two checks that follow whenever the caller's own record has lapsed, for example after an expiry-sweep and candidacy reset); the calling faculty must not be the candidate themself (otherwise `ERR_SELF_EVALUATION_FORBIDDEN` — segregation of duties is absolute, and the same rule applies to teaching evaluations); and the calling faculty's `discipline` must equal the candidate's `discipline` (otherwise `ERR_FACULTY_DISCIPLINE_MISMATCH`). The system records the evaluating faculty on the resulting `CourseMonitoring` row as `monitoring_faculty_id`, taken from the caller's `X-User-ID`, and the candidate on the row as `instructor_id`. When `outcome` is `SATISFACTORY` the candidate advances from `CANDIDATE` to `MONITORED`; when `outcome` is `UNSATISFACTORY` the monitoring row is still appended but the candidate remains in `CANDIDATE` and may be monitored again.

Second, while the candidate is in `MONITORED` (or still in `CANDIDATE` — evaluations are not gated on candidate status), faculty record `TeachingEvaluation` rows with a `score` from 1 to 5 inclusive and free-text `notes`. As with monitorings, the evaluating faculty is recorded as `evaluator_faculty_id` from the caller's `X-User-ID`, and the same self-evaluation and discipline-match preconditions apply.

Third, a `TCAdmin` certifies the candidate. Certification requires the instructor to currently be in `MONITORED` status (otherwise `ERR_INSTRUCTOR_NOT_MONITORED`), at least two `TeachingEvaluation` rows recorded across the instructor's entire history (otherwise `ERR_INSUFFICIENT_TEACHING_EVALUATIONS` — there is no time window on this count, and rows persist across candidacy resets), and a certification evaluation average of at least 4.00 (otherwise `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD`). The average is the sum of all `score` values divided by the number of evaluations, rounded half-up to two decimal places. Successful certification sets `certified_since` to the current clock, sets `renewal_due_at` to twenty-four months after the current clock, and leaves `renewal_count` at its current value (zero for a first certification).

A certified instructor may be granted faculty status by a `NationalAdmin`, which sets `is_faculty` to `true`. Only `CERTIFIED` instructors are eligible — the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (or `ERR_INSTRUCTOR_NOT_CERTIFIED` for the state mismatch) when made against a non-certified instructor. Faculty status is what allows the instructor to monitor and evaluate candidates, and what qualifies them to lead a `BLS_INSTRUCTOR` course.

### 3.3. Certification Renewal and the Expiry Sweep

Certification is valid for twenty-four months from `certified_since`. Renewal extends `renewal_due_at` by a further twenty-four months from the current clock and increments `renewal_count` by 1. A `TCAdmin` may renew a `CERTIFIED` instructor when both of the following hold.

The renewal window must be open: the current clock must be on or after ninety days before `renewal_due_at`, and on or before `renewal_due_at` itself. Both boundaries are inclusive — a renewal submitted at the exact `renewal_due_at` instant still succeeds, and a renewal submitted ninety days before the due instant also succeeds. Outside that window the renewal is rejected with `ERR_RENEWAL_WINDOW_CLOSED`.

Within the trailing twenty-four-month window (sessions whose `start_at` is on or after the instant twenty-four months before the current clock, and on or before the current clock — again inclusive on both ends), the instructor must have been the `primary_instructor_id` of at least two `CourseSession` rows whose `status` is `COMPLETED`. Sessions in `SCHEDULED`, `IN_PROGRESS`, or `CANCELLED` do not count. Falling short of two completed sessions rejects the renewal with `ERR_RENEWAL_SESSION_SHORTFALL`.

If the window lapses without renewal, the next clock advance that takes the current time strictly past `renewal_due_at` moves the instructor from `CERTIFIED` to `EXPIRED`. An `EXPIRED` instructor re-enters the candidate pathway when a `TCAdmin` resets candidacy — the move from `EXPIRED` back to `CANDIDATE` requires the instructor to currently be in `EXPIRED` (otherwise `ERR_INSTRUCTOR_NOT_EXPIRED`). The reset does not erase history: `is_faculty` is unchanged, any `TCAlignment` rows are unchanged, and prior monitorings and teaching evaluations persist (which is why a candidate who was once certified can re-certify quickly — the evaluation floor counts lifetime rows).

A certified instructor can also be suspended by a `QAAuditor`. The transition from `CERTIFIED` to `SUSPENDED` cancels every session they are scheduled to lead (every `CourseSession` whose `primary_instructor_id` is the instructor and whose `status` is `SCHEDULED`) with `cancel_reason` set to `INSTRUCTOR_SUSPENDED`; `ENROLLED` roster entries on those sessions are cancelled in turn and the sessions' `seats_available` recompute. Reinstatement from `SUSPENDED` back to `CERTIFIED` may be performed by either a `QAAuditor` or a `TCAdmin`, and requires the instructor to currently be `SUSPENDED` (otherwise `ERR_INSTRUCTOR_NOT_SUSPENDED`).

### 3.4. Scheduling a Course Session

A `TCCoordinator` schedules a `CourseSession` by supplying the `training_center_id` of the delivering center, the `site_id` of the delivery site, the `primary_instructor_id` of the instructor of record, the `guidelines_version_id` of the curriculum in force, the `course_type` (one of `BLS_PROVIDER`, `ACLS_PROVIDER`, `PALS_PROVIDER`, `HEARTSAVER`, or `BLS_INSTRUCTOR`), the `delivery_format` (either `CLASSROOM` or `BLENDED_SKILLS_SESSION`), the `start_at` and `end_at` timestamps (with `end_at` strictly after `start_at`), the `capacity` (an integer of at least 1), the `manikin_count` and `aed_trainer_count` (both integers of at least 0), and an optional `assisting_instructor_count` (an integer of at least 0, defaulting to 0). The session is created in `SCHEDULED` status with `seats_available` initialized to `capacity` and `cancel_reason` null.

Session creation walks a layered set of gates, and the order matters — these run after the §2.5 auth, existence, shape, and concurrency stages, in the following relative order within business rules.

The center gate runs first. The session's center must be in a status that permits scheduling; a `SUSPENDED` or `REVOKED` center rejects with `ERR_CENTER_SUSPENDED`, and a `PROVISIONAL` or `PROBATION` center rejects with `ERR_CENTER_NOT_ACTIVE`. The site must be `ALIGNED`: a `SUSPENDED` site rejects with `ERR_SITE_SUSPENDED`; a `PENDING_ALIGNMENT` or `DECOMMISSIONED` site rejects with `ERR_SITE_NOT_ALIGNED`. The instructor must be `CERTIFIED` (otherwise `ERR_INSTRUCTOR_NOT_CERTIFIED`). For a `BLS_INSTRUCTOR` course the primary instructor must additionally hold `is_faculty` (otherwise `ERR_FACULTY_REQUIRED_FOR_INSTRUCTOR_COURSE`). The instructor's `discipline` must match the discipline the course type demands — `BLS_PROVIDER` and `BLS_INSTRUCTOR` require `BLS`, `ACLS_PROVIDER` requires `ACLS`, `PALS_PROVIDER` requires `PALS`, and `HEARTSAVER` requires `HEARTSAVER` — otherwise `ERR_INSTRUCTOR_DISCIPLINE_MISMATCH`.

The structural gate runs next. The session's `capacity` must not exceed the site's `capacity_students` (otherwise `ERR_CAPACITY_EXCEEDS_SITE`). The equipment-sufficiency rule then applies; it is detailed in §3.5 and rejects with `ERR_EQUIPMENT_RATIO_VIOLATION` when its three floors are not all met.

The temporal gate follows. The guidelines version referenced by `guidelines_version_id` must currently be `ACTIVE` (otherwise `ERR_GUIDELINES_VERSION_NOT_ACTIVE`); sessions may not be scheduled on `DRAFT` or `SUPERSEDED` versions. The instructor must not be double-booked: if the same `primary_instructor_id` already leads another session in `SCHEDULED` or `IN_PROGRESS` status whose time interval overlaps the new session's, the create is rejected with `ERR_SESSION_OVERLAP_INSTRUCTOR`. Overlap is computed on a half-open basis — the existing session occupies the interval from its `start_at` up to but not including its `end_at` — so a back-to-back session that begins at the exact instant the prior session ends is permitted. The site has a looser rule with a turnover buffer: if the site already hosts a `SCHEDULED` or `IN_PROGRESS` session such that the gap between the two sessions is less than sixty minutes, the create is rejected with `ERR_SESSION_OVERLAP_SITE`. A gap of exactly sixty minutes is permitted.

The referential gate runs last among the non-quota checks. The supplied `site_id` must belong to the supplied `training_center_id` — a site registered under a different center rejects with `ERR_SITE_CENTER_MISMATCH`. The instructor referenced by `primary_instructor_id` must hold an `ACTIVE` `TCAlignment` to the center; an instructor who is certified but not aligned to this center rejects with `ERR_INSTRUCTOR_NOT_ALIGNED`.

A session moves from `SCHEDULED` to `IN_PROGRESS` when started by either a `TCCoordinator` or an `Instructor`. The session must currently be `SCHEDULED` (otherwise `ERR_SESSION_NOT_SCHEDULED`); when the actor is an `Instructor`, their `X-User-ID` must equal the session's `primary_instructor_id` (otherwise `ERR_INSTRUCTOR_NOT_SESSION_LEAD`). A `TCCoordinator` may also cancel a session from either `SCHEDULED` or `IN_PROGRESS`; the manual cancel from `SCHEDULED` requires the session to still be `SCHEDULED` (otherwise `ERR_SESSION_NOT_SCHEDULED`). Either way `cancel_reason` is set to `MANUAL`, no cards are issued for any roster entry on the session, every `ENROLLED` roster entry is cancelled, and `seats_available` is recomputed back to `capacity`.

### 3.5. Equipment Sufficiency and the Session Floor Rules

Three independent floors govern whether a session may be scheduled, all evaluated at creation time. Each floor is an integer ceiling — the requirement is always rounded up to the next whole unit — and the session must clear all three; failure of any one rejects the create with `ERR_EQUIPMENT_RATIO_VIOLATION`.

The manikin floor depends on the `delivery_format`. For a `CLASSROOM` session the required number of manikins is the session's `capacity` divided by 3, rounded up. For a `BLENDED_SKILLS_SESSION` session the divisor is 6 instead of 3 — the format assumes students have completed the cognitive portion online, so the equipment density is halved. The supplied `manikin_count` must be at least the required number.

The AED trainer floor has a baseline and an advanced variant. The baseline requirement is `capacity` divided by 6, rounded up. When the `course_type` is either `ACLS_PROVIDER` or `PALS_PROVIDER` the floor rises to `capacity` divided by 4, rounded up, and the requirement is the larger of the baseline and the advanced figure — for those advanced courses the advanced figure always dominates. The supplied `aed_trainer_count` must meet that floor.

The instructor floor covers the lead plus assistants. The requirement is one instructor for the first six students plus one additional instructor for every further block of six students, rounded up — equivalently, 1 plus the ceiling of (`capacity` minus 6) divided by 6, with the ceiling treated as no less than zero so a six-student session needs only the lead. The supplied `assisting_instructor_count`, plus 1 for the primary instructor, must meet that floor.

### 3.6. Roster Management and Skills Evaluation

A `TCCoordinator` enrolls a student into a `SCHEDULED` session by supplying `student_name` and `student_email`, plus an optional `prior_card_id` when the enrollment is a renewal against an expiring card. Enrollment creates a `RosterEntry` — its `course_session_id` is taken from the path — in `ENROLLED` status with `remediation_used` initially `false`, and decrements the session's `seats_available` by 1. The session must be `SCHEDULED` (otherwise `ERR_SESSION_NOT_SCHEDULED`) and must have at least one seat available — `seats_available` greater than zero — otherwise the enrollment is rejected with `ERR_SESSION_FULL`. That quota check runs last in the §2.5 pipeline so that other request problems surface first. When `prior_card_id` is supplied the referenced card's `holder_email` must match the enrollment's `student_email`; a mismatch rejects with `ERR_PRIOR_CARD_HOLDER_MISMATCH`. A `TCCoordinator` may cancel an `ENROLLED` roster entry (otherwise `ERR_ROSTER_ENTRY_NOT_ENROLLED`); the entry moves to `CANCELLED` and the session's `seats_available` increments by 1.

Skills evaluation is the instructor's responsibility and is only available while the session is `IN_PROGRESS` and the roster entry is `ENROLLED`. An `Instructor` whose `X-User-ID` equals the session's `primary_instructor_id` (otherwise `ERR_INSTRUCTOR_NOT_SESSION_LEAD`) records a checklist `SkillsEvaluation` by supplying an `items` array. Each element of `items` carries an `item_code` string, a `critical` boolean, and a `passed` boolean. The array must contain at least one item, and at least one of those items must be marked `critical` — failures of either shape rule are `ERR_INVALID_REQUEST`. The server derives `total_items` as the number of items, `passed_items` as the count of items whose `passed` is `true`, and `score_percent` as `passed_items` multiplied by 100 and divided by `total_items`, rounded half-up to two decimal places. The evaluating instructor is recorded on the row as `evaluated_by_instructor_id`, taken from `X-User-ID`, and the roster entry as `roster_entry_id`.

The `outcome` of an evaluation depends on which attempt this is. The system tracks `attempt_number` per roster entry: 1 for the initial attempt and 2 for the remediation retest, with `is_remediation_retest` set to `true` on the second attempt. An initial attempt yields `PASS` when no critical item has `passed` false *and* `score_percent` is at least 84.00; otherwise it yields `REMEDIATION_REQUIRED`. A remediation retest — permitted only when a prior attempt on this roster entry returned `REMEDIATION_REQUIRED` — yields `PASS` when no critical item failed *and* `score_percent` is at least 90.00; otherwise it yields `FAIL`, which is terminal. The two-attempt cap is absolute: a third attempt, or a second attempt without a prior `REMEDIATION_REQUIRED`, is rejected with `ERR_REMEDIATION_LIMIT_EXCEEDED`. Per the §2.5 pipeline, this cap check runs at level 10 and is therefore reached only after the level-6 state preconditions on the same request — session-lead ownership, the session being `IN_PROGRESS`, and the roster entry being `ENROLLED` — have all passed. Because a terminal `FAIL` on the second attempt moves the entry to `FAILED`, a subsequent attempt against that entry is rejected with `ERR_ROSTER_ENTRY_NOT_ENROLLED` before the attempt-count check is ever evaluated.

A `PASS` outcome moves the roster entry from `ENROLLED` to `PASSED`; when the passing attempt was the remediation retest, the entry's `remediation_used` flag is set to `true` as part of the same transition. A `REMEDIATION_REQUIRED` outcome leaves the entry `ENROLLED` and sets `remediation_used` to `true`. A `FAIL` outcome moves the entry from `ENROLLED` to `FAILED`.

### 3.7. Session Completion and Card Issuance

When a session's teaching is finished the primary instructor completes it, moving the session from `IN_PROGRESS` to `COMPLETED`. Completion is gated: the session must currently be `IN_PROGRESS` (otherwise `ERR_SESSION_NOT_IN_PROGRESS`); the caller must be the session's `primary_instructor_id` (otherwise `ERR_INSTRUCTOR_NOT_SESSION_LEAD`); the owning center must be `ACTIVE` (a `PROBATION` center rejects with `ERR_CENTER_ON_PROBATION`, any other non-`ACTIVE` status with `ERR_CENTER_NOT_ACTIVE`); and every roster entry on the session must already be in a resolved state — one of `PASSED`, `FAILED`, or `CANCELLED` — otherwise the completion is rejected with `ERR_SESSION_HAS_UNRESOLVED_ROSTER` and the instructor must record a skills outcome or cancel each outstanding `ENROLLED` entry first.

A successful completion issues one `CourseCompletionCard` per `PASSED` roster entry. The card carries the `roster_entry_id` it was issued from; the `training_center_id` denormalized from the session for center-level card counts; the `prior_card_id` copied from the roster entry when this is a renewal (otherwise null); an `is_renewal` boolean set to `true` exactly when `prior_card_id` is set; the `holder_email` copied from the roster entry's `student_email`; the `course_type` copied from the session; the `guidelines_version_code` copied from the session's guidelines version's `code`; an `issued_at` timestamp taken from the current clock; and a server-minted `card_code` in the format `AHA-XXXXXX-XXXXXX` together with a secret `verification_token` used for employer verification. The card starts in `ACTIVE` status. Issuance increments both the center's lifetime `cards_issued_count` and its `active_card_count` by the number of cards issued, and increments the primary instructor's `sessions_taught_count` by 1.

Card expiry is end-of-month snapped. For an initial-issue card (`is_renewal` false), `expires_at` is computed by adding twenty-four months to `issued_at` and then snapping the result to the last day of that month at 23:59:59 UTC. For a renewal card (`is_renewal` true), the system first checks whether the prior card's `expires_at` is still in the future relative to the new card's `issued_at`. If it is, the new card's `expires_at` is computed by adding twenty-four months to the *prior card's* `expires_at` and then end-of-month snapping the result — renewal extends the chain, it does not reset it. If the prior card has already expired by the time the new card is issued, the renewal falls back to the initial-issue rule: twenty-four months from `issued_at`, end-of-month snapped.

A card leaves `ACTIVE` in two ways. A `QAAuditor` or `NationalAdmin` may revoke it, which requires the card to currently be `ACTIVE` (otherwise `ERR_CARD_NOT_ACTIVE`) and moves it to terminal `REVOKED`, decrementing the issuing center's `active_card_count` by 1 without touching `cards_issued_count`. The clock sweep moves a card from `ACTIVE` to terminal `EXPIRED` when the new clock value passes its `expires_at`, with the same decrement behavior. Both terminal states are irreversible.

### 3.8. Quality Audits and the Compliance Score

A `QAAuditor` opens a `QualityAudit` against a center by supplying `target_training_center_id` and `expected_training_center_version`. The OCC check of §2.10 applies: a stale version rejects with `ERR_STALE_VERSION`. A successful open increments the center's `version` by 1, stamps the center's `last_audit_opened_at` with the current clock, records the caller's `X-User-ID` on the audit as `opened_by`, stamps `opened_at` with the current clock, and initializes `compliance_score` to 100. The audit starts in `OPEN` status with `closed_at` null.

While the audit is `OPEN` the auditor appends `AuditFinding` rows — the row's `audit_id` is taken from the path — each carrying a `severity` drawn from `OBSERVATION`, `MINOR`, `MAJOR`, or `CRITICAL`, a free-text `description`, and an optional `is_repeat_offense` boolean (defaulting to `false`) that flags whether the same finding class was raised on a prior audit of this center. Each finding's `deduction_points` is computed as the severity's base points — 1.25 for `OBSERVATION`, 4.5 for `MINOR`, 12.5 for `MAJOR`, and 40 for `CRITICAL` — multiplied by 1.5 when `is_repeat_offense` is true and by 1.0 otherwise, with the per-finding result rounded half-up to two decimal places *before* being summed. The rounding order is pinned: round each finding first, then sum. Sum-then-round is a forbidden alternative because it produces different cents — for instance, two `OBSERVATION` repeat findings each contribute 1.88 (1.875 rounded half-up), totalling 3.76; summing the raw values first would yield 3.75. The audit's `compliance_score` is then 100 minus the total deduction, floored at zero so the score never goes negative.

A `CRITICAL` finding does more than deduct points: the moment it is appended, the target center — whether `ACTIVE` or `PROBATION` — moves to `SUSPENDED`, and the full center-suspension cascade of §3.1 fires: every `ALIGNED` site of the center moves to `SUSPENDED`, every `SCHEDULED` session at those sites is cancelled with `cancel_reason` set to `CENTER_SUSPENDED`, every `ENROLLED` roster entry on those sessions is cancelled, and each affected session's `seats_available` recomputes to `capacity`.

Closing the audit has two variants, both requiring the audit to currently be `OPEN` (otherwise `ERR_AUDIT_NOT_OPEN`). Closing with `outcome` set to `CLEAN` moves the audit to `CLOSED_CLEAN` and is only permitted when no finding on the audit has `severity` `CRITICAL` — otherwise `ERR_AUDIT_HAS_OPEN_CRITICAL_FINDINGS`. Closing with `outcome` set to `CORRECTIVE_ACTION` moves the audit to `CLOSED_CORRECTIVE` and has no critical-finding restriction. Both variants stamp `closed_at` with the current clock. A corrective-action close additionally moves the target center from `ACTIVE` to `PROBATION` (stamping `probation_started_at` with the current clock); a center that is already `SUSPENDED` remains `SUSPENDED` — the close does not demote it further, and the path back is the reinstate flow of §3.1.

### 3.9. Guidelines Versions and the Transition Sweep

The national office publishes a `GuidelinesVersion` by supplying a unique `code` (for example `G2020` or `G2025`), a human-readable `title`, the `published_at` publication timestamp, and a `transition_deadline_at` instant after which `SCHEDULED` sessions on the superseded version are cancelled. A new version starts in `DRAFT` status.

A `NationalAdmin` activates a `DRAFT` version; attempting to activate a version that is already `ACTIVE` or already `SUPERSEDED` is rejected with `ERR_GUIDELINES_VERSION_CONFLICT`. Activation supersedes the previously `ACTIVE` version (if any), moving it to `SUPERSEDED`, and runs the transition sweep against the just-superseded version: every `CourseSession` whose `guidelines_version_id` references the superseded version, whose `status` is `SCHEDULED`, and whose `start_at` is strictly after the new version's `transition_deadline_at` is cancelled with `cancel_reason` set to `GUIDELINES_TRANSITION`, and its `ENROLLED` roster entries are cancelled in turn with `seats_available` recomputing to `capacity`. The boundary is strict-greater: a session whose `start_at` equals the deadline exactly survives the sweep. Sessions on the superseded version whose `start_at` is on or before the deadline remain `SCHEDULED`, and every session on the superseded version has its `curriculum_flag` recomputed to `LEGACY`. Sessions in `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` are untouched by the sweep.

A session's `curriculum_flag` is `CURRENT` whenever its referenced guidelines version's `status` is `ACTIVE`, and `LEGACY` otherwise. The flag is derived, not stored as a static value — when a version is superseded the flag flips for every session that references it.

### 3.10. Employer Verification and the Public Card Surface

Employers verify a provider's card by submitting the card's `card_code` and `verification_token` together with a `verifier_reference` identifying themselves (a name or an employer id). The card is resolved by `card_code`; an unknown code rejects with `ERR_CARD_NOT_FOUND`. A `verification_token` that does not match the resolved card rejects with `ERR_CARD_VERIFICATION_MISMATCH` and no verification event is recorded. A successful verification appends a `CardVerification` event stamped with the current clock as `verified_at` and the resolved card's `id` as `card_id`. The event's `result` echoes the card's standing: `VALID` when the card is `ACTIVE` and the token matched; otherwise the card's own status, `EXPIRED` or `REVOKED`. The event also surfaces `card_expires_at`, a copy of the card's `expires_at`, so the employer can schedule the provider's renewal without a second call.

### 3.11. Reconciliation Invariants

Two invariants must hold at every observable instant, across every operation described above.

Seat conservation: for every session, `seats_available` plus the number of roster entries on that session whose status is `ENROLLED` equals the session's `capacity`. Roster adds decrement the seat count, manual roster cancels increment it, and any session-level cancellation (manual or cascade) recomputes `seats_available` to `capacity` because no entry remains `ENROLLED`.

Card stock partition: for every center, `cards_issued_count` equals `active_card_count` plus the count of that center's cards in `EXPIRED` status plus the count in `REVOKED` status. Issuance increments both `cards_issued_count` and `active_card_count`; revocation and clock-sweep expiry each move one unit out of `active_card_count` into the corresponding terminal bucket without touching `cards_issued_count`. The lifetime counter is monotonic and never decrements.

## 4. Endpoint Definitions

Operations that create new resources — whether a stand-alone top-level resource or a child appended to a parent — return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions, return `200 OK`. List endpoints and single-resource reads return `200 OK`. All endpoints are mounted under the `/aha` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aha/_clock/set_current_utc` | Set the logical clock; runs instructor and card expiry sweeps | NationalAdmin |
| POST | `/aha/training-centers` | Create a training center (status PROVISIONAL) | NationalAdmin |
| GET | `/aha/training-centers/{id}` | Get a training center | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| POST | `/aha/training-centers/{id}/activate` | PROVISIONAL to ACTIVE; requires at least one ALIGNED site | NationalAdmin |
| POST | `/aha/training-centers/{id}/reinstate` | PROBATION to ACTIVE, or SUSPENDED to PROBATION; requires no OPEN audits | NationalAdmin, QAAuditor |
| POST | `/aha/training-centers/{id}/suspend` | ACTIVE or PROBATION to SUSPENDED with site/session/roster cascade | QAAuditor |
| POST | `/aha/training-centers/{id}/revoke` | SUSPENDED to REVOKED (terminal); decommissions sites, ends alignments | NationalAdmin |
| POST | `/aha/training-centers/{id}/sites` | Create a site under a center (status PENDING_ALIGNMENT) | TCAdmin |
| GET | `/aha/training-centers/{id}/sites` | List sites of a center | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| GET | `/aha/training-sites/{id}` | Get a site | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| POST | `/aha/training-sites/{id}/align` | PENDING_ALIGNMENT to ALIGNED; requires faculty oversight; OCC on center version | TCAdmin |
| POST | `/aha/training-sites/{id}/suspend` | ALIGNED to SUSPENDED; cancels SCHEDULED sessions at the site | TCAdmin, QAAuditor |
| POST | `/aha/training-sites/{id}/reinstate` | SUSPENDED to ALIGNED; blocked while center SUSPENDED or REVOKED | TCAdmin |
| POST | `/aha/training-sites/{id}/decommission` | ALIGNED to DECOMMISSIONED; requires no SCHEDULED or IN_PROGRESS sessions | TCAdmin |
| POST | `/aha/instructors` | Register an instructor (CANDIDATE; CERTIFIED when legacy_certified true) | NationalAdmin |
| GET | `/aha/instructors/{id}` | Get an instructor | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/training-centers/{id}/instructors` | List instructors whose home_training_center_id is this center | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| POST | `/aha/instructors/{id}/grant-faculty` | Grant faculty status; instructor must be CERTIFIED | NationalAdmin |
| POST | `/aha/instructors/{id}/monitor` | Record a course monitoring for a candidate; SATISFACTORY moves CANDIDATE to MONITORED | TrainingFaculty |
| GET | `/aha/instructors/{id}/monitorings` | List course monitorings for an instructor | NationalAdmin, TCAdmin, QAAuditor, TrainingFaculty, Instructor |
| POST | `/aha/instructors/{id}/teaching-evaluations` | Record a teaching evaluation (score 1 to 5) for a candidate | TrainingFaculty |
| GET | `/aha/instructors/{id}/teaching-evaluations` | List teaching evaluations for an instructor | NationalAdmin, TCAdmin, QAAuditor, TrainingFaculty, Instructor |
| POST | `/aha/instructors/{id}/certify` | MONITORED to CERTIFIED; requires two or more evaluations averaging at least 4.00 | TCAdmin |
| POST | `/aha/instructors/{id}/renew` | CERTIFIED to CERTIFIED with renewal_due_at extended; requires open renewal window and two completed sessions in trailing 24 months | TCAdmin |
| POST | `/aha/instructors/{id}/suspend` | CERTIFIED to SUSPENDED; cancels their SCHEDULED sessions | QAAuditor |
| POST | `/aha/instructors/{id}/reinstate` | SUSPENDED to CERTIFIED | QAAuditor, TCAdmin |
| POST | `/aha/instructors/{id}/reset-candidacy` | EXPIRED to CANDIDATE | TCAdmin |
| POST | `/aha/training-centers/{id}/alignments` | Align a CERTIFIED instructor to the center, optionally as faculty | TCAdmin |
| GET | `/aha/training-centers/{id}/alignments` | List alignments of a center | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| GET | `/aha/instructors/{id}/alignments` | List alignments of an instructor | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| POST | `/aha/alignments/{id}/end` | ACTIVE to ENDED | TCAdmin |
| POST | `/aha/guidelines-versions` | Create a guidelines version (status DRAFT); code unique | NationalAdmin |
| GET | `/aha/guidelines-versions` | List guidelines versions | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/guidelines-versions/{id}` | Get a guidelines version | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| POST | `/aha/guidelines-versions/{id}/activate` | DRAFT to ACTIVE; supersedes the current ACTIVE version and runs the transition sweep | NationalAdmin |
| GET | `/aha/guidelines-versions/{id}/course-sessions` | List sessions teaching this guidelines version | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| POST | `/aha/course-sessions` | Schedule a course session; enforces center/site/instructor gates, equipment ratios, capacity, overlap rules | TCCoordinator |
| GET | `/aha/course-sessions/{id}` | Get a session | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/training-centers/{id}/course-sessions` | List sessions of a center | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| GET | `/aha/training-sites/{id}/course-sessions` | List sessions at a site | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor |
| GET | `/aha/instructors/{id}/course-sessions` | List sessions whose primary_instructor_id is this instructor | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| POST | `/aha/course-sessions/{id}/start` | SCHEDULED to IN_PROGRESS | TCCoordinator, Instructor |
| POST | `/aha/course-sessions/{id}/complete` | IN_PROGRESS to COMPLETED; issues one card per PASSED roster entry | Instructor |
| POST | `/aha/course-sessions/{id}/cancel` | SCHEDULED or IN_PROGRESS to CANCELLED with cancel_reason MANUAL; no cards issued | TCCoordinator |
| POST | `/aha/course-sessions/{id}/roster` | Enroll a student into a SCHEDULED session | TCCoordinator |
| GET | `/aha/course-sessions/{id}/roster` | List roster entries of a session | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/roster-entries/{id}` | Get a roster entry | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| POST | `/aha/roster-entries/{id}/cancel` | ENROLLED to CANCELLED; releases the seat | TCCoordinator |
| POST | `/aha/roster-entries/{id}/skills-evaluations` | Record a checklist skills evaluation; caller must be session's primary instructor; at most two attempts | Instructor |
| GET | `/aha/roster-entries/{id}/skills-evaluations` | List skills evaluations of a roster entry | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/instructors/{id}/skills-evaluations` | List skills evaluations performed by an instructor | NationalAdmin, TCAdmin, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/cards/{id}` | Get a completion card | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty, Employer |
| GET | `/aha/roster-entries/{id}/cards` | List cards issued from a roster entry (zero or one) | NationalAdmin, TCAdmin, TCCoordinator, QAAuditor, Instructor, TrainingFaculty |
| GET | `/aha/training-centers/{id}/cards` | List cards issued by a center | NationalAdmin, TCAdmin, QAAuditor |
| GET | `/aha/cards/{id}/renewals` | List renewal cards whose prior_card_id is this card (zero or one) | NationalAdmin, TCAdmin, QAAuditor |
| POST | `/aha/cards/{id}/revoke` | ACTIVE to REVOKED | QAAuditor, NationalAdmin |
| GET | `/aha/cards/{id}/roster-entries` | List roster entries referencing this card as prior_card_id | NationalAdmin, TCAdmin, QAAuditor |
| GET | `/aha/cards/{id}/verifications` | List verification events for a card | NationalAdmin, TCAdmin, QAAuditor, Employer |
| POST | `/aha/card-verifications` | Employer verification of provider status by card_code and verification_token | Employer, NationalAdmin, QAAuditor |
| POST | `/aha/quality-audits` | Open a quality audit against a center; OCC on center version | QAAuditor |
| GET | `/aha/quality-audits/{id}` | Get an audit | NationalAdmin, TCAdmin, QAAuditor |
| GET | `/aha/training-centers/{id}/quality-audits` | List audits of a center | NationalAdmin, TCAdmin, QAAuditor |
| POST | `/aha/quality-audits/{id}/findings` | Append a finding to an OPEN audit; recomputes compliance_score; a CRITICAL finding suspends the center | QAAuditor |
| GET | `/aha/quality-audits/{id}/findings` | List findings of an audit | NationalAdmin, TCAdmin, QAAuditor |
| POST | `/aha/quality-audits/{id}/close` | OPEN to CLOSED_CLEAN (no CRITICAL findings) or CLOSED_CORRECTIVE (center ACTIVE to PROBATION) | QAAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 Not Found |
| `ERR_ALIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GUIDELINES_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ROSTER_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CENTER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CENTER_ON_PROBATION` | 409 Conflict |
| `ERR_CENTER_SUSPENDED` | 409 Conflict |
| `ERR_CENTER_REVOKED` | 409 Conflict |
| `ERR_SITE_NOT_ALIGNED` | 409 Conflict |
| `ERR_SITE_SUSPENDED` | 409 Conflict |
| `ERR_SITE_HAS_SCHEDULED_SESSIONS` | 409 Conflict |
| `ERR_NO_ALIGNED_SITE` | 409 Conflict |
| `ERR_NO_FACULTY_OVERSIGHT` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_CANDIDATE` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_MONITORED` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_SUSPENDED` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_EXPIRED` | 409 Conflict |
| `ERR_ALIGNMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SESSION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SESSION_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_SESSION_HAS_UNRESOLVED_ROSTER` | 409 Conflict |
| `ERR_ROSTER_ENTRY_NOT_ENROLLED` | 409 Conflict |
| `ERR_AUDIT_NOT_OPEN` | 409 Conflict |
| `ERR_AUDIT_HAS_OPEN_CRITICAL_FINDINGS` | 409 Conflict |
| `ERR_AUDIT_STILL_OPEN` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_GUIDELINES_VERSION_CONFLICT` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_SESSION_LEAD` | 403 Forbidden |
| `ERR_SELF_EVALUATION_FORBIDDEN` | 403 Forbidden |
| `ERR_FACULTY_DISCIPLINE_MISMATCH` | 409 Conflict |
| `ERR_INSTRUCTOR_DISCIPLINE_MISMATCH` | 409 Conflict |
| `ERR_FACULTY_REQUIRED_FOR_INSTRUCTOR_COURSE` | 403 Forbidden |
| `ERR_CAPACITY_EXCEEDS_SITE` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_RATIO_VIOLATION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_ALIGNMENT` | 409 Conflict |
| `ERR_INSUFFICIENT_TEACHING_EVALUATIONS` | 409 Conflict |
| `ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_RENEWAL_SESSION_SHORTFALL` | 409 Conflict |
| `ERR_SESSION_OVERLAP_INSTRUCTOR` | 409 Conflict |
| `ERR_SESSION_OVERLAP_SITE` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_GUIDELINES_VERSION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SITE_CENTER_MISMATCH` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_ALIGNED` | 409 Conflict |
| `ERR_PRIOR_CARD_HOLDER_MISMATCH` | 409 Conflict |
| `ERR_SESSION_FULL` | 422 Unprocessable Entity |
| `ERR_REMEDIATION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CARD_VERIFICATION_MISMATCH` | 409 Conflict |
