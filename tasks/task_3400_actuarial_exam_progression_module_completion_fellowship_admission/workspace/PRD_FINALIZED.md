# Actuarial Exam Progression API — Product Requirements Document

## 1. Introduction

A professional actuarial society runs one of the longest qualification pipelines in any credentialed profession: a candidate progresses through a sequence of preliminary examinations delivered in computer-based testing windows, substitutes certain requirements with university coursework under Validation by Educational Experience transcript review, selects a fellowship specialty track of modules capped by a capstone, defends a written project assessment graded by volunteer committees, attends a professionalism course at a defined stage, and only then petitions for admission as an Associate and later as a Fellow. Along the way the society must contend with pass marks proposed and ratified by committee, registration deadlines and seating capacity, syllabus editions that change mid-candidacy and force credit mapping from retired exams onto their successors, transfer credit claimed from other actuarial bodies under mutual recognition agreements, continuing professional development attestation for members, and a discipline process for professional-conduct violations.

This document specifies the API through which candidates, registrars, examination committees, academic reviewers, volunteer graders, and the discipline board operate that pipeline. All resources are mounted under the `/actuarial` prefix. Two design commitments shape everything that follows. First, all time-dependent behavior — registration windows opening and closing, testing periods, course sessions being held, suspensions expiring — is driven by a single logical clock that administrators advance explicitly, never by wall-clock time, so that every lifecycle transition is deterministic and auditable. Second, the society's compliance posture is enforced by segregation of duties: the volunteer who grades a project may never grade it twice, the committee that proposes a pass mark ratifies and publishes it through separate acts, and optimistic concurrency checks protect the two most contended records in the system — an examination window awaiting its pass mark and a candidate record awaiting credential evaluation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly seven roles: `Anonymous`, `Candidate`, `Registrar`, `ExamCommittee`, `AcademicReviewer`, `Grader`, and `DisciplineBoard`. A request whose `X-User-Role` header is missing or names no declared role — or whose `X-User-ID` header is missing for any role other than `Anonymous` — is rejected with `ERR_MISSING_HEADERS` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Anonymous`, the caller is unauthenticated and self-registering; `X-User-ID` is an opaque value that is not required and is never compared to any persisted entity.
- When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; ownership checks on any resource that references a `Candidate` compare the resource's foreign-key field (its `candidate_id`, or the candidate id appearing in the request path) to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403).
- When `X-User-Role` is `Registrar`, `ExamCommittee`, `AcademicReviewer`, `Grader`, or `DisciplineBoard`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `verified_by` on a `CourseAttendance` when a `Registrar` verifies attendance, or appended to `grader_ids` on a `ProjectAssessment` when a `Grader` submits a score) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order — a stable ordering that never falls back to identifier-based ordering. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time-dependent behavior in the system reads a single logical clock, never wall-clock time. Before any administrative set call, the clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time under any circumstance. A `Registrar`-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The clock is monotonic: an attempt to set it to a timestamp earlier than its current reading is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Each accepted clock-set call runs an operations sweep — including one whose `to_iso8601` equals the current reading, so an entity whose threshold sits exactly at the current reading transitions on such a call just as it would on an advancing one — applied as a single mutation per affected entity. Every examination window whose thresholds have passed advances directly to its furthest due status — passing through all intermediate states whose thresholds have passed — and its `version` increments once per window per sweep, not once per state crossed. A window reaching `SCORING` in a sweep marks each of its `REGISTERED` registrations as `SAT` in the same sweep. Professionalism course sessions whose `ends_at` has been reached become `HELD`. Suspended candidates whose `suspended_until` has been reached return to `ACTIVE`. The clock-set response reports the new `current_utc` together with the counters `windows_advanced`, `registrations_marked_sat`, `sessions_held`, and `suspensions_lifted`. A set call that changes nothing — that is, one whose sweep finds no entity due for transition, whether or not the call advanced the clock reading — performs no mutations at all: no `version` changes and all four counters report zero.

### 2.5. Common Resource Properties

Every resource in this API — candidates, syllabus versions, exams, exam windows, exam registrations, pass-mark settings, VEE submissions, track enrollments, modules, module attempts, project assessments, course sessions, course attendances, transfer credit requests, CPD attestations, discipline cases, and credential applications — carries a uniform set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any modification to the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including modifications performed by automatic cascades, sweeps, and bubble-up reconciliations.

No resource type in this system omits `updated_at` or `version`; the convention applies to all seventeen resource types without exception, providing a consistent audit trail and unique addressability for every record. Unless a workflow narrative in §3 specifies a creation-time value, system-managed and computed fields begin null — or empty, for list-valued fields — and acquire their values only at the events that define them: a `ratified_mark` exists only after ratification, a `score` and `submitted_at` only after submission, a `refund_cents` only after cancellation, and so on.

### 2.6. Optimistic Concurrency Control

Two write operations in this API participate in optimistic concurrency control, and both require the client to present the version of a parent entity that it last observed.

A `POST /actuarial/exam-windows/{wid}/pass-mark-settings` request must carry `expected_exam_window_version` matching the target window's current `version`. If the window's version has advanced since the client last read it — because another committee writer has just created a setting (which legitimately supersedes the prior one), or because a clock sweep advanced the window — the create is rejected with `ERR_STALE_WINDOW_VERSION` (HTTP 412), preventing the client from building on a window state it has not observed.

A `POST /actuarial/credential-applications` request must carry `expected_candidate_version` matching the acting candidate's current `version`. Every credential application, whether approved or denied, advances the candidate's `version` (the evaluation stamps `last_evaluated_at`, and an approval additionally advances the membership tier), so a second application carrying a previously observed version is stale — for example, a candidate whose ASA was just approved must re-read their record before filing for FSA. A mismatch is rejected with `ERR_STALE_CANDIDATE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field; no other optimistic-concurrency check exists anywhere in the API.

### 2.7. Numeric Precision, Fees, and Rounding

Numeric values follow fixed precision rules per domain. Scaled examination scores are kept to exactly one decimal place using the standard round-half-up method. Committee pass marks, both `proposed_mark` and `ratified_mark`, lie between 0 and 10 inclusive and carry exactly one decimal place. All monetary values are integer cents: the processing component of a registration fee and any half-rate refund are each rounded half-up to a whole cent. Track completion percentages are rounded half-up to exactly two decimal places. CPD requirement proration rounds up to a whole hour, and all hour comparisons use an at-least boundary in which equality satisfies the requirement. Transfer-credit grants are whole hours, rounded half-up where a ratio is applied. Project assessment final scores are whole points, with a two-grader mean rounded half-up. Transcript grade points lie between 0.0 and 4.0 inclusive, and the approval threshold admits a grade of exactly 2.7.

### 2.8. Nested Resource Retrieval and Validation Priority

The API enforces a strict, hierarchical validation protocol for requests that target nested resources. When an endpoint path contains multiple resource identifiers, the system resolves each identifier in sequential, left-to-right order — candidate, syllabus version, exam, window, registration, pass-mark setting, submission, attempt, project, session, attendance, attestation, case — and rejects the request immediately with the `404 Not Found` error of the *first* identifier that does not resolve, before examining anything further down the path. Foreign keys supplied in a request body (such as `exam_id`, `syllabus_version_id`, `prerequisite_exam_id`, `exam_window_id`, `module_id`, `track_enrollment_id`, or `course_session_id`) are likewise resolved to existing resources, each failure producing the not-found error of the referenced resource type.

When a single request violates several rules, the violation reported is determined by a fixed priority order, evaluated from first to last:

1. **Authentication headers.** Presence of `X-User-Role` and, for non-`Anonymous` roles, `X-User-ID` — violations yield `ERR_MISSING_HEADERS`.
2. **Role authorization.** The declared role must appear in the endpoint's authorized roles — violations yield `ERR_UNAUTHORIZED_ROLE`.
3. **Structural schema gate.** The request body must be structurally sound: required fields present, types correct, enum values in range, conditional requirements met (for example, `suspension_days` is required exactly when the resolution is `SUSPENSION`), an exam's prerequisite graph acyclic and confined to the same syllabus version, a `credit_map` resolvable at syllabus activation, window dates ordered, and clock monotonicity preserved. All such violations yield `ERR_INVALID_REQUEST`. Unknown body fields are ignored rather than rejected, including attempts to set system-managed or computed fields.
4. **Path resolution.** Path parameters resolve left to right, each failure producing the per-resource not-found error.
5. **Ownership.** For `Candidate`-scoped endpoints, the resource's `candidate_id` (or the path candidate id) must equal `X-User-ID` — violations yield `ERR_FORBIDDEN_OWNER`. `Grader` endpoints carry no ownership restriction beyond the segregation-of-duties rule.
6. **Body foreign keys.** Foreign keys in the payload must resolve — failures yield the referenced resource's not-found error.
7. **Optimistic concurrency.** The two OCC-bearing writes compare their `expected_exam_window_version` or `expected_candidate_version` against the parent entity's current `version` — mismatches yield `ERR_STALE_WINDOW_VERSION` or `ERR_STALE_CANDIDATE_VERSION`.
8. **State preconditions.** Target and parent states must admit the operation — the state-guard errors of §3, all HTTP 422.
9. **Candidate standing.** Candidate-initiated writes and discipline sanctions require the candidate to be `ACTIVE` — violations yield `ERR_CANDIDATE_NOT_ACTIVE`.
10. **Uniqueness and progression gates.** Duplicate active registrations, duplicate credited VEE topics, duplicate active enrollments, and duplicate cycle attestations are conflicts (HTTP 409); prerequisite, sequencing, stage, and segregation gates are unprocessable (HTTP 422).
11. **Temporal windows.** The module retake cooldown and session bookability are unprocessable (HTTP 422); window schedule conflicts and same-calendar-day attendance conflicts are conflicts (HTTP 409).
12. **Capacity.** A full professionalism session rejects with `ERR_SESSION_FULL` (HTTP 409). Note by contrast that exam-window capacity overflow is never an error — it waitlists the registration instead.

### 2.9. Candidate Standing and the Credential Ladder

Every candidate record evolves along two parallel, independent dimensions. The **standing** dimension, `status`, takes the values `ACTIVE`, `SUSPENDED`, and `EXPELLED`; a new candidate begins `ACTIVE`, a suspension is a timed removal that lifts automatically when the logical clock reaches `suspended_until` (completing the `ACTIVE` → `SUSPENDED` → `ACTIVE` cycle), and `EXPELLED` is terminal, reachable from either `ACTIVE` or `SUSPENDED`. The **credential ladder** dimension, `membership_tier`, takes the values `CANDIDATE`, `ASSOCIATE`, and `FELLOW`; it only advances, never retreats, and each advancement is stamped (`associate_admitted_at`, then `fellow_admitted_at`) at the moment of approval.

Standing gates nearly every candidate-initiated write in the system: only an `ACTIVE` candidate may register for an examination window, submit VEE coursework, enroll in a fellowship track, start a module attempt, submit a project assessment, book a professionalism session, request transfer credit, attest CPD hours, or file a credential application; every one of these attempts by a non-`ACTIVE` candidate is rejected with `ERR_CANDIDATE_NOT_ACTIVE`. Stage gating stacks on top of standing: track enrollment and professionalism-course booking are reserved for members holding the `ASSOCIATE` or `FELLOW` tier (`ERR_REQUIRES_ASSOCIATE`), and CPD attestation is a member obligation that a `CANDIDATE`-tier user cannot perform (`ERR_CPD_NOT_MEMBER`).

### 2.10. Syllabus Editions and Transition Credit

The examination catalogue is versioned. A `SyllabusVersion` begins life `DRAFT`, becomes `ACTIVE` through an explicit activation, and ends `RETIRED`; at most one version is `ACTIVE` at any moment, and retirement is never invoked directly — it happens only as the cascade of another version's activation. Every `Exam` mirrors the lifecycle of its owning version: created `DRAFT`, turned `ACTIVE` when its syllabus activates, and turned `RETIRED` when its syllabus retires.

Syllabus change mid-candidacy is handled by transition credit. Each version carries a `credit_map` whose keys are exam codes of the version being retired and whose values are exam codes of exams belonging to the incoming version; the map is validated at activation time. A `PASS` credit earned on an exam whose version later retires confers credit on the mapped exam of the version whose activation retired it, whenever such a mapping key exists; an unmapped credit remains a historical credit on the original exam, still counting toward credit totals but satisfying only that exam's own prerequisite. Where several retirements have occurred, mapping chains are evaluated in version activation order — chronological by each version's `activated_at` — so a credit mapped into a second-edition exam is treated as a second-edition credit when a third edition activates and may map again. A retired exam's credit is never double-counted toward the totals described in §3.1.

## 3. Business Logic & Workflows

### 3.1. Joining the Society: Candidate Registration and the Candidate Record

Entry into the pipeline begins with self-service registration: an `Anonymous` visitor opens a candidate record by supplying an `email` and a `full_name`. The `email` must be a non-empty, well-formed address and is unique across all candidates — a duplicate is rejected with `ERR_INVALID_REQUEST`. A freshly created record starts with `status` of `ACTIVE` and `membership_tier` of `CANDIDATE`; the standing fields `suspended_until`, `associate_admitted_at`, `fellow_admitted_at`, and `last_evaluated_at` all begin null.

The candidate record is also the society's ledger of credit. Three computed totals ride on every read of the record. `earned_exam_credit_hours` sums the `credit_hours` of the distinct exams on which the candidate holds a `PASS` credit, with a pass earned on a `RETIRED` exam counting toward its mapped `ACTIVE` exam per the transition-credit mapping and never counted twice. `transfer_credit_hours` sums `granted_hours` over the candidate's transfer-credit requests whose status is `GRANTED`. `total_credit_hours` is the sum of the two. These totals are recomputed on every read of the candidate and on every mutation touching the candidate's registrations, the syllabus versions, or the transfer requests, so the record always reflects current entitlements.

Record access is owner-scoped: a `Candidate` reading a record whose path id differs from their own `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNER`, while a `Registrar` may read any record as part of candidate record maintenance.

### 3.2. Curating the Syllabus: Versions, Exams, and the Activation Cascade

A `Registrar` authors the examination catalogue edition by edition. Creating a syllabus version requires a unique `version_code` (an edition code such as a year-and-letter pair; duplicates are rejected with `ERR_INVALID_REQUEST`) and accepts an optional `credit_map` describing how credits on outgoing exams carry forward; when omitted, the map defaults to empty. The new version is born `DRAFT`, and its `activated_at` remains null until activation.

Under a version, the `Registrar` defines exams. Each exam takes a unique `exam_code`, a `title`, an integer `credit_hours` of at least 1, an optional `is_prelim` flag marking membership in the preliminary sequence required for Associateship (defaulting to true when omitted), a nullable `prerequisite_exam_id`, and the `syllabus_version_id` of its owning edition. Two structural rules guard the prerequisite declaration, both enforced with `ERR_INVALID_REQUEST`: the prerequisite must reference an exam on the same syllabus version, and the prerequisite graph across all exams of one version must remain acyclic. An exam's `status` is never set directly — it is `DRAFT` at creation and thereafter mirrors its owning syllabus, turning `ACTIVE` at activation and `RETIRED` at retirement.

Activation is the pivotal act of syllabus governance, performed by a `Registrar` on a version still `DRAFT` — activating a version in any other state is rejected with `ERR_SYLLABUS_ACTIVATION_INVALID`. Before the cascade runs, the `credit_map` is validated: its keys must be exam codes of the currently `ACTIVE` version (or the map must be empty when no version is `ACTIVE`), and its values must be exam codes of exams belonging to the version being activated; an unresolvable map is rejected with `ERR_INVALID_REQUEST`. On success the activation stamps `activated_at` with the current logical-clock reading and then cascades through four links. First, the previously `ACTIVE` version, if any, transitions `ACTIVE` → `RETIRED`. Second, every exam of the retired version transitions `ACTIVE` → `RETIRED`, and every exam of the newly activated version transitions `DRAFT` → `ACTIVE`. Third, every exam window of a retired exam whose status is `SCHEDULED`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED` transitions to `CANCELLED`. Fourth, every registration on a cancelled window whose `logistics_status` is `REGISTERED` or `WAITLISTED` transitions to `CANCELLED` with `cancel_reason` of `SYLLABUS_RETIREMENT` and a full refund — `refund_cents` is set to the `fee_charged_cents` that was charged. No waitlist promotion fires from a window that was cancelled; freed seats in a cancelled window are simply void. From that moment on, pass credits on the retired exams continue to count through the transition-credit mapping described in §2.10.

Committee members and registrars may read a syllabus version to inspect its `status`, `credit_map`, and `activated_at`, and may browse the exam catalogue through filtered lists — narrowing by `syllabus_version_id`, by `prerequisite_exam_id`, or by `status` — or read a single exam by id; candidates may read exams as well when planning their progression.

### 3.3. Examination Windows, Registration, Fees, and Results

Before any candidate can sit an exam, a `Registrar` schedules a computer-based testing window for it. The exam must be `ACTIVE` — scheduling a window for an exam in any other state is rejected with `ERR_EXAM_NOT_ACTIVE`. The window takes a unique `window_code`, the administering `exam_id`, four timestamps — `registration_opens_at`, `registration_deadline`, `testing_starts_at`, and `testing_ends_at` — a `capacity` of at least 1, a `base_fee_cents` of at least 0, and an optional `late_surcharge_cents` of at least 0 that defaults to 0 when omitted. The four timestamps must be ordered so that registration opens no later than the deadline, the deadline is no later than the start of testing, and the start of testing is no later than its end; any mis-ordering is rejected with `ERR_INVALID_REQUEST`. One scheduling safety rule protects the same exam against double administration: the new window's testing interval, treated as half-open from `testing_starts_at` up to but not including `testing_ends_at`, must not overlap the testing interval of any other window of the same exam — though two windows whose intervals merely touch, one ending exactly when the other begins, are permitted. An overlap is rejected with `ERR_WINDOW_SCHEDULE_CONFLICT`. A window's derived seating posture is always visible on the record: `seats_held` is the count of its registrations whose `logistics_status` is `REGISTERED` and is kept equal to that count at all times, and `waitlist_count` is the count of its `WAITLISTED` registrations.

Once scheduled, a window's lifecycle is driven entirely by the logical clock sweep described in §2.4. A `SCHEDULED` window becomes `REGISTRATION_OPEN` once the clock reaches `registration_opens_at`, becomes `REGISTRATION_CLOSED` once the clock reaches `registration_deadline`, becomes `TESTING` once the clock reaches `testing_starts_at`, and becomes `SCORING` once the clock reaches `testing_ends_at` — at which moment every registration still `REGISTERED` on the window is marked `SAT` with `sat_at` stamped to the current clock reading, while `WAITLISTED` registrations remain waitlisted. Because the sweep closes registration the instant the clock reaches the deadline, a registration attempted at exactly the `registration_deadline` is already too late and is rejected as if the deadline had passed. A window ends in one of two terminal states: `RESULTS_PUBLISHED`, reached when the committee publishes the ratified pass mark, or `CANCELLED`, reached only through the syllabus-retirement cascade of §3.2 — in which case its `REGISTERED` and `WAITLISTED` registrations are cancelled with `cancel_reason` of `SYLLABUS_RETIREMENT` and a full refund, and no waitlist promotion fires.

Registration itself is a candidate act carrying just the `exam_window_id`. Four gates guard it. The window must be `REGISTRATION_OPEN` — a registration against a window in any other status, including the exact-deadline boundary above, is rejected with `ERR_WINDOW_NOT_OPEN`. The candidate must be `ACTIVE`, per the standing rule of §2.9. When the exam declares a `prerequisite_exam_id`, the candidate must already hold credit on that prerequisite — either a direct `PASS` or a mapped credit through transition mapping — else the registration is rejected with `ERR_PREREQUISITE_NOT_MET`. And the candidate must not already hold a registration for the same window whose `logistics_status` is `REGISTERED` or `WAITLISTED`; such a duplicate is rejected with `ERR_DUPLICATE_REGISTRATION`. Every registration is born with `grading_status` of `PENDING` and a `logistics_status` decided by capacity: when `seats_held` is below `capacity` the seat is granted and the registration is `REGISTERED`; when `seats_held` has reached `capacity` — the boundary is inclusive, so equality waitlists — the registration is `WAITLISTED`, and this overflow is expressly not an error. A waitlisted row carries no charge: its `fee_charged_cents` stays null until promotion.

The registration fee is computed at the moment a seat is held, whether at creation for a `REGISTERED` row or at promotion for a formerly waitlisted one, and is recorded as `fee_charged_cents`. Registering at or after the point fourteen days before the `registration_deadline` is late; the fee's subtotal is the window's `base_fee_cents` plus, only when late, its `late_surcharge_cents`. A processing component of one and a half percent of that subtotal, rounded half-up to a whole cent, is then added to produce the charge. The rounding order is pinned: the processing component is computed once on the summed subtotal and rounded half-up before being added — rounding each component's share of the processing separately and summing afterward is not the rule and can differ by one cent.

A registration can be cancelled by the owning candidate or by a `Registrar`, but only while its `logistics_status` is `REGISTERED` or `WAITLISTED`, its `grading_status` is still `PENDING`, and its window is `REGISTRATION_OPEN` or `REGISTRATION_CLOSED`; any other combination is rejected with `ERR_REGISTRATION_NOT_CANCELLABLE`. A voluntary cancellation records `cancel_reason` of `CANDIDATE` and computes `refund_cents` by timing: cancelling before the `registration_deadline` refunds the entire `fee_charged_cents`, while cancelling at or after the deadline — which, given the window states above, means while the window is `REGISTRATION_CLOSED` — refunds half of the fee, rounded half-up to a whole cent. The boundary is explicit: a cancellation landing exactly on the deadline receives the half refund. A waitlisted row, never having been charged, has a null fee and so a null refund. Whenever a `REGISTERED` row is cancelled the window's `seats_held` is recomputed one seat down, and if the window is still `REGISTRATION_OPEN` that freed seat immediately promotes a waitlisted registration.

Waitlist promotion draws only from the window's own `WAITLISTED` rows, promoting the earliest-created one — ties broken by the promoting candidate records' own `created_at` in ascending order, never by identifier — and when no row is waiting the promotion is a no-op. The promoted row becomes `REGISTERED` and its `fee_charged_cents` is computed by the same fee rule at the promotion timestamp. Candidates and registrars can review a candidate's registrations, and registrars and committee members a window's registrations, through filtered lists supporting a `logistics_status` filter.

When the window reaches `SCORING`, the `ExamCommittee` enters results. Recording a score targets a `SAT` registration of the window and is permitted only while that window is `SCORING`; it writes the registration's `raw_score`, an integer from 0 to the maximum raw score of 60. The `scaled_score` is then derived: the raw score is divided by sixty, multiplied by ten, and rounded half-up to one decimal place; it remains null until a raw score exists. Alongside it the provisional `projected_result` refreshes — `PASS` when the scaled score is at least the current projection mark, `FAIL` otherwise — where the projection mark is the `ratified_mark` of the window's latest non-`SUPERSEDED` pass-mark setting when that setting is `RATIFIED`, and its `proposed_mark` otherwise. The `projected_result` is null whenever the registration's `grading_status` is `RELEASED` or when no pass mark or raw score exists yet.

The pass mark itself moves through a committee workflow of three acts. A committee member proposes a mark for the window, supplying a `proposed_mark` between 0 and 10 inclusive with one decimal place; the window must be `REGISTRATION_CLOSED`, `TESTING`, or `SCORING` — a proposal at any other window state is rejected with `ERR_PASS_MARK_INVALID_STATE` — and the proposal carries the optimistic-concurrency field `expected_exam_window_version` per §2.6. The proposal is created `PROPOSED`, its creation supersedes any existing setting of the same window in `PROPOSED` or `RATIFIED` (which becomes `SUPERSEDED`), and the window's `version` increments by one. Ratification moves a `PROPOSED` setting to `RATIFIED` and records the `ratified_mark` from the request, which may differ from the `proposed_mark`; ratifying a setting in any other state is rejected with `ERR_PASS_MARK_INVALID_STATE`. Publication is the terminal act: the setting must be `RATIFIED` and the window `SCORING`, else `ERR_PASS_MARK_INVALID_STATE`. On publication the setting becomes `PUBLISHED`, the window transitions `SCORING` → `RESULTS_PUBLISHED`, and every `SAT` registration of the window is graded at once — its official `result` is set to `PASS` when its `scaled_score` is at least the `ratified_mark` (equality passes) and to `FAIL` otherwise, and its `grading_status` moves `PENDING` → `RELEASED`. A registration may thus be observed in any independent combination of its two parallel dimensions, such as `SAT` with `PENDING` or `SAT` with `RELEASED`; the grading and logistics dimensions never constrain one another. Registrars and committee members can trace this workflow through the list of a window's pass-mark settings.

### 3.4. Validation by Educational Experience

University coursework can substitute for certain requirements through Validation by Educational Experience. An `ACTIVE` candidate files a VEE submission naming a `topic` — one of `ECONOMICS`, `CORPORATE_FINANCE`, or `APPLIED_STATISTICS` — together with the `university` whose coursework is offered, the `course_title` as it appears on the transcript, and the `grade_points` earned on the 4.0 scale, which must lie between 0.0 and 4.0 inclusive. The society credits a topic at most once: when an `APPROVED` submission already exists for the same candidate and topic, a fresh submission is rejected with `ERR_VEE_TOPIC_ALREADY_CREDITED`. A new submission enters `SUBMITTED` and awaits transcript review.

Review is performed by an `AcademicReviewer`, who records a `decision` of approve or reject along with an optional `reviewer_note`. Only a `SUBMITTED` submission is reviewable — a review attempted on an already-decided submission is rejected with `ERR_VEE_NOT_REVIEWABLE`. Approval additionally requires the transcript grade to meet the floor: an approve decision on a submission whose `grade_points` is below 2.7 is rejected with `ERR_VEE_GRADE_BELOW_THRESHOLD`, while a grade of exactly 2.70 approves. Either decision stamps `reviewer_note` and `reviewed_at` with the acting reviewer's note and the current logical-clock reading, moving the submission to `APPROVED` or `REJECTED`. Rejection is terminal for that record; the resubmission path is simply to file a fresh submission for the same topic. Candidates, reviewers, and registrars can browse a candidate's submissions through filtered lists supporting `topic` and `status` filters.

### 3.5. Fellowship Tracks, Module Attempts, and the Capstone Gate

An Associate or Fellow chooses a specialty by opening a track enrollment with a `track_code` of `QFI`, `ILA`, `CFE`, `RET`, or `GH`. Enrollment requires the candidate to be `ACTIVE` and, per the stage gate of §2.9, to hold the `ASSOCIATE` or `FELLOW` tier — a `CANDIDATE`-tier attempt is rejected with `ERR_REQUIRES_ASSOCIATE`. A candidate may hold only one live enrollment at a time: when an enrollment in `ENROLLED` or `CAPSTONE_ELIGIBLE` already exists, another enrollment is rejected with `ERR_ENROLLMENT_ACTIVE_EXISTS`. A new enrollment begins `ENROLLED`, with `modules_passed_count` at zero and `completion_pct` reflecting an empty track.

The `Registrar` defines the modules of each track. A module takes a unique `module_code`, the `track_code` it belongs to, a `sequence_index` of at least 1 that is unique within its track and fixes the attempt order, a `title`, an optional `is_capstone` flag defaulting to false, a `passing_score` between 1 and 100 inclusive, and an optional `cooldown_days` of at least 0 that defaults to 14 days when omitted.

Starting an attempt names the `track_enrollment_id` — which must be one of the acting candidate's own enrollments — and the `module_id`. Five gates apply. The candidate must be `ACTIVE`. The enrollment must be `ENROLLED` or `CAPSTONE_ELIGIBLE`; an attempt under any other enrollment status is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The module's `track_code` must equal the enrollment's `track_code`, failing which the request is rejected with `ERR_INVALID_REQUEST`. A capstone module additionally requires the enrollment to have reached `CAPSTONE_ELIGIBLE`, and a non-capstone module at sequence position k beyond the first requires a `PASSED` attempt on the module at sequence position k−1 of the same track under the same enrollment; either violation is rejected with `ERR_MODULE_SEQUENCE_LOCKED`. Finally, the retake cooldown: a new attempt on a module is blocked while a `FAILED` attempt on the same module under the same enrollment has a `submitted_at` plus the module's `cooldown_days` lying strictly later than the current logical clock — reaching that moment exactly is enough, and the retake is allowed — and a blocked retake is rejected with `ERR_MODULE_COOLDOWN_ACTIVE`. A created attempt is `IN_PROGRESS` and is numbered by the system: its `attempt_number` is one plus the count of prior attempts on the same module under the same enrollment.

Submitting the attempt supplies the `score`, an integer from 0 to 100 — a grade outside that range is rejected with `ERR_INVALID_REQUEST` — and grades synchronously: a score at least equal to the module's `passing_score` passes, anything below fails, with the boundary counting as a pass. Submission stamps `score` and `submitted_at`, and a failed submission's `submitted_at` is what starts the retake cooldown clock. A decided attempt is terminal; submitting an attempt no longer `IN_PROGRESS` is rejected with `ERR_INVALID_REQUEST`.

A passing submission bubbles up the hierarchy. The enrollment's `modules_passed_count` — the count of distinct modules of the track with at least one `PASSED` attempt under this enrollment — is recomputed. When every non-capstone module of the track has been passed, the enrollment transitions `ENROLLED` → `CAPSTONE_ELIGIBLE`; when the capstone module itself is passed while the enrollment is `CAPSTONE_ELIGIBLE`, the enrollment transitions to `COMPLETED`. The only route to `WITHDRAWN` is the expulsion cascade of §3.9. Each transition recomputes the enrollment's `completion_pct`, which is also recomputed on every read of the enrollment and on every module-attempt or project-assessment mutation. The percentage's evaluation order is pinned so the capstone gate never depends on a figure that itself includes the capstone: first, the eligibility gate reads only non-capstone module passes; second, the reported percentage is computed as one hundred times a weighted sum — two for each passed non-capstone module, three more if the capstone module is passed, and two more if the project assessment is passed — divided by the weighted whole of two per non-capstone module in the track plus three for the capstone plus two for the project, with the result rounded half-up to two decimal places. Candidates and registrars can follow attempts through single reads or through filtered lists narrowing by `track_enrollment_id`, `module_id`, or `status`, and can list a candidate's enrollments with a `status` filter.

### 3.6. The Written Project Assessment and Volunteer Grading

Once an enrollment reaches the capstone stage, the candidate submits a written project assessment with a `title` under that `track_enrollment_id`. Submission requires the candidate to be `ACTIVE` and the enrollment to be `CAPSTONE_ELIGIBLE` or `COMPLETED`; a submission under an enrollment in any earlier state is rejected with `ERR_PROJECT_REQUIRES_CAPSTONE`. The assessment begins `SUBMITTED` with empty `grader_ids` and `scores` lists and a null `final_score` and `result`.

Grading is performed by volunteer `Grader` operators, each submitting an integer `score` from 0 to 100 — a grade outside that range is rejected with `ERR_INVALID_REQUEST`. The workflow is a fork-and-join over at most three grades, governed throughout by segregation of duties: the acting grader's `X-User-ID` must not already appear in the assessment's `grader_ids`, and a repeat grading by the same grader is rejected with `ERR_GRADER_CONFLICT`. An assessment is gradable only while `SUBMITTED`, `IN_REVIEW`, or `SPLIT`; once `DECIDED` it is terminal and further grades are rejected with `ERR_PROJECT_NOT_GRADABLE`. Each accepted grade appends the grader to `grader_ids` and the score to `scores`, keeping the two lists parallel and ordered.

The first grade moves the assessment `SUBMITTED` → `IN_REVIEW`. The second grade decides the fork: when the two scores differ by at most ten points — the consensus tolerance — the assessment joins to `DECIDED` and its `final_score` is the mean of the two grades rounded half-up to a whole point; when they differ by more than ten points the assessment forks to `SPLIT` with both scores recorded and no final score yet. A `SPLIT` assessment is resolved by a third grade from a grader distinct from both prior graders, moving it to `DECIDED` with `final_score` equal to the median of the three scores. Either path then sets the `result`: `PASS` when the `final_score` is at least seventy, `FAIL` otherwise. Candidates, registrars, and graders can read an assessment by id or browse filtered lists narrowing by `candidate_id`, `track_enrollment_id`, or `status`.

### 3.7. The Professionalism Course

At a defined stage of the pathway every member must attend the professionalism course. A `Registrar` schedules a course session with a unique `session_code`, a `starts_at`, an `ends_at`, and a `capacity` of at least 1. The session is `SCHEDULED` until the logical clock reaches `ends_at`, at which point the sweep marks it `HELD`; its `attendance_booked` is the live count of its `BOOKED` attendances.

Booking is a candidate act carrying just the `course_session_id`, and it is stage-gated: the candidate must be `ACTIVE` and hold the `ASSOCIATE` or `FELLOW` tier, with a `CANDIDATE`-tier booking rejected with `ERR_REQUIRES_ASSOCIATE`. The session must still be bookable — `SCHEDULED` with a `starts_at` strictly later than the current logical clock; booking a session already held or whose start has been reached is rejected with `ERR_SESSION_NOT_BOOKABLE`. Capacity is a hard ceiling here, unlike examination windows: when `attendance_booked` has reached `capacity` — equality rejects — the booking is refused with `ERR_SESSION_FULL`. One calendar rule prevents double-booking a day's attention: a candidate may not hold a `BOOKED` or `ATTENDED` attendance to any other session whose `starts_at` falls on the same UTC calendar date as this session's, a pure date-equality test rather than any interval overlap; a violation is rejected with `ERR_SESSION_SAME_DAY_CONFLICT`. A successful booking is created `BOOKED` and the session's `attendance_booked` is recomputed one seat up.

After the session is `HELD`, a `Registrar` verifies each booking by recording an `outcome` of `ATTENDED` or `NO_SHOW`. Verification requires the attendance to be `BOOKED` and the session `HELD`; any other combination is rejected with `ERR_ATTENDANCE_NOT_VERIFIABLE`. Verification stamps `verified_at` with the current logical clock and `verified_by` with the acting `Registrar`'s opaque operator id. Candidates and registrars can read an attendance by id or browse filtered lists narrowing by `course_session_id`, `candidate_id`, or `status`.

### 3.8. Transfer Credit and Continuing Professional Development

Candidates arriving from other actuarial bodies claim credit under mutual recognition. An `ACTIVE` candidate files a transfer-credit request naming the `source_body` — one of `IFOA`, `CIA`, `IAA`, `CAS`, or `OTHER` — and the `claimed_hours`, an integer of at least 1. The request is decided synchronously at creation, with no review queue. The `source_body` fixes the derived `agreement_class`: `BILATERAL` for `IFOA` and `CIA`, `NON_BILATERAL` for `IAA` and `CAS`, and `UNRECOGNIZED` for `OTHER`. The class fixes `granted_hours`: a bilateral request grants the smaller of the claimed hours and thirty; a non-bilateral request grants the smaller of half the claimed hours — rounded half-up to a whole hour — and fifteen; an unrecognized request grants zero. The `status` is `GRANTED` for the two recognized classes and `DENIED` for an unrecognized body. On a grant, the candidate's `transfer_credit_hours` and `total_credit_hours` are recomputed immediately. Candidates and registrars can browse a candidate's requests through a filtered list supporting a `status` filter.

Members — candidates holding the `ASSOCIATE` or `FELLOW` tier — owe the society continuing professional development each cycle. A member files an attestation for a calendar `cycle_year` with self-reported `attested_hours` of at least 0 and an optional `carryover_hours` of at least 0 that defaults to 0. Attestation requires `ACTIVE` standing; a `CANDIDATE`-tier filing is rejected with `ERR_CPD_NOT_MEMBER`; and only one attestation may exist per candidate per cycle year, a duplicate being rejected with `ERR_CPD_CYCLE_DUPLICATE`. Creation fixes the `required_hours` for the cycle. The base requirement is thirty hours, prorated in the admission year: when the candidate's `associate_admitted_at` falls within the attested cycle year, the base is thirty multiplied by the number of months remaining in that year — counted as thirteen minus the admission month, so the admission month itself counts in full — divided by twelve and rounded up to a whole hour; in any other year the base is the full thirty hours. Carryover then reduces the requirement, but only up to a cap of ten hours: the requirement is the base minus the smaller of `carryover_hours` and ten, never below zero. The attestation begins `ATTESTED`, and between creation and the first verification the self-reported `attested_hours` serve as a provisional standing against the requirement without ever changing the attestation's status.

Official standing is established only by evidence. A `Registrar` verifies an attestation by recording `verified_hours`; the attestation must be `ATTESTED` or `SHORTFALL` — verifying one already `VERIFIED` is rejected with `ERR_CPD_NOT_VERIFIABLE`. When the recorded `verified_hours` are at least the `required_hours`, the attestation becomes `VERIFIED`; when they fall short, it becomes `SHORTFALL`. A shortfall is curable: a later verification on a `SHORTFALL` attestation whose new `verified_hours` meets the requirement moves it to `VERIFIED`. Every verification stamps `verified_at` with the current logical clock. Candidates and registrars can browse a candidate's attestations through filtered lists supporting `cycle_year` and `status` filters.

### 3.9. Discipline, Sanctions, and Credential Admission

Professional-conduct enforcement begins when a `Registrar` files a discipline case against a candidate, supplying the `candidate_id`, the `charge` text, and a `severity` from 1 to 10 inclusive recorded for the file. The subject must exist and must not already be `EXPELLED` — filing against such a candidate is rejected with `ERR_CANDIDATE_NOT_ACTIVE`. The case is born `FILED`.

Resolution belongs to the `DisciplineBoard`, which sanctions a case with a `resolution` of `DISMISSED`, `REPRIMAND`, `SUSPENSION`, or `EXPULSION`. Only a `FILED` case can be resolved; sanctioning an already-resolved case is rejected with `ERR_DISCIPLINE_ALREADY_RESOLVED`. A `SUSPENSION` resolution must carry `suspension_days` of at least 1 — its absence is a structural failure rejected with `ERR_INVALID_REQUEST` — and requires the candidate to be `ACTIVE`. An `EXPULSION` resolution requires the candidate to be `ACTIVE` or `SUSPENDED`; any other standing is rejected with `ERR_CANDIDATE_NOT_ACTIVE`. Resolution records `resolution`, `suspension_days`, and `resolved_at` on the case, and a suspension's `suspended_until` — computed as the resolution moment plus `suspension_days` days — is likewise recorded and copied onto the candidate. `DISMISSED` and `REPRIMAND` mutate no candidate state at all.

A suspension runs the candidate's `ACTIVE` → `SUSPENDED` transition with a four-link cascade. The candidate's `version` increments and `suspended_until` is set as above. Every registration of the candidate whose `logistics_status` is `REGISTERED` or `WAITLISTED` is cancelled with `cancel_reason` of `DISCIPLINE_SUSPENSION`. Each such cancellation refunds in full regardless of timing — a formerly `REGISTERED` row's `refund_cents` is set to its `fee_charged_cents`, while a formerly `WAITLISTED` row, never charged, receives no refund. And each freed seat on a window still `REGISTRATION_OPEN` triggers the waitlist promotion of §3.3, with the promoted row's fee computed at promotion time. The suspension lifts itself: when a clock sweep finds the current reading has reached a suspended candidate's `suspended_until` — the boundary inclusive — the candidate returns `SUSPENDED` → `ACTIVE`, `suspended_until` is cleared to null, and the candidate's `version` increments. Cancelled registrations are not restored by reinstatement; the candidate must register anew.

An expulsion runs the terminal cascade. The candidate's `status` becomes `EXPELLED` — from which there is no return — and `version` increments. The candidate's registrations in `REGISTERED` or `WAITLISTED` are cancelled with `cancel_reason` of `DISCIPLINE_EXPULSION` and `refund_cents` of zero, the fees forfeited; freed seats still trigger waitlist promotion on `REGISTRATION_OPEN` windows. And the candidate's track enrollment in `ENROLLED` or `CAPSTONE_ELIGIBLE` is withdrawn to `WITHDRAWN`. Candidates, registrars, and board members can review a candidate's cases through a filtered list supporting a `status` filter.

The pathway culminates in a credential application: the candidate applies for the `ASA` or the `FSA` credential, carrying the optimistic-concurrency field `expected_candidate_version` per §2.6. The candidate must be `ACTIVE`, and the credential must not already be held — applying for `ASA` while `ASSOCIATE` or `FELLOW`, or for `FSA` while `FELLOW`, is rejected with `ERR_CREDENTIAL_ALREADY_HELD`. Evaluation is synchronous, and its outcome is either `APPROVED` or `DENIED_DEFICIENCY` with an ordered `deficiency_codes` list.

For the `ASA`, the evaluation collects, in canonical order: `MISSING_PRELIM_CREDIT` when any exam flagged `is_prelim` of the `ACTIVE` syllabus lacks a credit — a direct `PASS` or one mapped through transition credit — a deficiency also emitted when no syllabus version is `ACTIVE` at all; `MISSING_VEE_TOPIC` when any of the three VEE topics lacks an `APPROVED` submission; and `INSUFFICIENT_TOTAL_CREDITS` when the candidate's earned exam credit hours plus transfer credit hours capped at fifteen fall below a total of ten. For the `FSA`, it collects: `MISSING_ASA` when the candidate's tier is still `CANDIDATE`; `TRACK_INCOMPLETE` when the candidate holds no `COMPLETED` track enrollment; `MISSING_PROJECT_PASS` when the candidate holds no project assessment whose `result` is `PASS`; and `MISSING_PROFESSIONALISM` when the candidate holds no course attendance whose status is `ATTENDED`. The full canonical ordering across both evaluations is `MISSING_PRELIM_CREDIT`, `MISSING_VEE_TOPIC`, `INSUFFICIENT_TOTAL_CREDITS`, `MISSING_ASA`, `TRACK_INCOMPLETE`, `MISSING_PROJECT_PASS`, `MISSING_PROFESSIONALISM`; an empty list approves, a non-empty list denies.

Every application stamps the candidate's `last_evaluated_at` with the current logical clock and increments the candidate's `version` — even when the application is denied — and stamps the application's own `evaluated_at`. An approved application additionally advances the membership ladder: `CANDIDATE` → `ASSOCIATE` stamps `associate_admitted_at`, and `ASSOCIATE` → `FELLOW` stamps `fellow_admitted_at`, the fellowship admission, each advancement incrementing `version` again per the candidate's tier transition. Resubmission after a deficiency is cured is simply a new application — and because the previous application advanced the candidate's `version`, the client must re-read the record before refiling, or the stale-version rejection of §2.6 will turn the second filing away. Candidates and registrars can review a candidate's applications through a filtered list supporting `credential` and `status` filters.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — including state transitions, reviews, verifications, sanctions, and the clock-set sweep — return a `200 OK` status code. The table below is a summary only; the complete request and response semantics of each operation are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/actuarial/_clock/set_current_utc` | Advance the logical clock and run the time-driven sweep | Registrar |
| POST | `/actuarial/candidates` | Register a new candidate (self-service) | Anonymous |
| GET | `/actuarial/candidates/{id}` | Read a candidate record including computed credit totals | Candidate, Registrar |
| POST | `/actuarial/syllabus-versions` | Create a syllabus edition in DRAFT with its transition credit map | Registrar |
| POST | `/actuarial/syllabus-versions/{id}/activate` | Activate a DRAFT syllabus, retiring the current ACTIVE one with the full cascade | Registrar |
| GET | `/actuarial/syllabus-versions/{id}` | Read one syllabus version | Registrar, ExamCommittee |
| POST | `/actuarial/exams` | Create an exam under a syllabus version | Registrar |
| GET | `/actuarial/exams/{id}` | Read one exam | Registrar, Candidate, ExamCommittee |
| GET | `/actuarial/exams` | List exams with filters | Registrar, Candidate, ExamCommittee |
| POST | `/actuarial/exam-windows` | Schedule a testing window for an ACTIVE exam | Registrar |
| GET | `/actuarial/exam-windows/{id}` | Read one window including version and computed seat counts | Registrar, Candidate, ExamCommittee |
| GET | `/actuarial/exam-windows` | List windows with filters | Registrar, Candidate, ExamCommittee |
| POST | `/actuarial/exam-registrations` | Register the acting candidate for a window; overflow waitlists | Candidate |
| POST | `/actuarial/exam-registrations/{id}/cancel` | Cancel a cancellable registration; computes refund and promotes the waitlist | Candidate, Registrar |
| POST | `/actuarial/exam-registrations/{id}/record-score` | Enter the raw score for a SAT registration while the window is SCORING | ExamCommittee |
| GET | `/actuarial/candidates/{id}/registrations` | List a candidate's registrations | Candidate, Registrar |
| GET | `/actuarial/exam-windows/{id}/registrations` | List a window's registrations | Registrar, ExamCommittee |
| POST | `/actuarial/exam-windows/{wid}/pass-mark-settings` | Propose a pass mark for the window (supersedes any non-PUBLISHED setting; OCC) | ExamCommittee |
| POST | `/actuarial/pass-mark-settings/{id}/ratify` | Ratify a PROPOSED pass mark | ExamCommittee |
| POST | `/actuarial/pass-mark-settings/{id}/publish` | Publish a RATIFIED mark, grading all SAT registrations and closing the window | ExamCommittee |
| GET | `/actuarial/exam-windows/{id}/pass-mark-settings` | List a window's pass-mark settings | Registrar, ExamCommittee |
| POST | `/actuarial/vee-submissions` | Submit university coursework for VEE transcript review | Candidate |
| POST | `/actuarial/vee-submissions/{id}/review` | Approve or reject a SUBMITTED VEE submission | AcademicReviewer |
| GET | `/actuarial/candidates/{id}/vee-submissions` | List a candidate's VEE submissions | Candidate, AcademicReviewer, Registrar |
| POST | `/actuarial/track-enrollments` | Select a fellowship track (requires ASSOCIATE or FELLOW tier) | Candidate |
| GET | `/actuarial/candidates/{id}/track-enrollments` | List a candidate's track enrollments | Candidate, Registrar |
| POST | `/actuarial/modules` | Define a specialty module within a track | Registrar |
| POST | `/actuarial/module-attempts` | Start an attempt on a module under the acting candidate's enrollment | Candidate |
| POST | `/actuarial/module-attempts/{id}/submit` | Submit the attempt with its score; grades synchronously and bubbles up | Candidate |
| GET | `/actuarial/module-attempts/{id}` | Read one module attempt | Candidate, Registrar |
| GET | `/actuarial/module-attempts` | List module attempts with filters | Candidate, Registrar |
| POST | `/actuarial/project-assessments` | Submit a written project assessment (requires CAPSTONE_ELIGIBLE or COMPLETED) | Candidate |
| POST | `/actuarial/project-assessments/{id}/grades` | Submit a grader's score under segregation of duties | Grader |
| GET | `/actuarial/project-assessments/{id}` | Read one project assessment | Candidate, Registrar, Grader |
| GET | `/actuarial/project-assessments` | List project assessments with filters | Candidate, Registrar, Grader |
| POST | `/actuarial/course-sessions` | Schedule a professionalism course session | Registrar |
| POST | `/actuarial/course-attendances` | Book the acting candidate into a professionalism session | Candidate |
| POST | `/actuarial/course-attendances/{id}/verify` | Verify attendance once the session is HELD | Registrar |
| GET | `/actuarial/course-attendances/{id}` | Read one attendance | Candidate, Registrar |
| GET | `/actuarial/course-attendances` | List attendances with filters | Candidate, Registrar |
| POST | `/actuarial/transfer-credit-requests` | Claim transfer credit from another actuarial body; decided synchronously | Candidate |
| GET | `/actuarial/candidates/{id}/transfer-credit-requests` | List a candidate's transfer credit requests | Candidate, Registrar |
| POST | `/actuarial/cpd-attestations` | Attest CPD hours for a cycle year | Candidate |
| POST | `/actuarial/cpd-attestations/{id}/verify` | Record evidence-backed hours; verifies or shortfalls the attestation | Registrar |
| GET | `/actuarial/candidates/{id}/cpd-attestations` | List a candidate's CPD attestations | Candidate, Registrar |
| POST | `/actuarial/discipline-cases` | File a professional-conduct case against a non-EXPELLED candidate | Registrar |
| POST | `/actuarial/discipline-cases/{id}/sanction` | Resolve a FILED case; SUSPENSION and EXPULSION run the candidate cascades | DisciplineBoard |
| GET | `/actuarial/candidates/{id}/discipline-cases` | List a candidate's discipline cases | Candidate, Registrar, DisciplineBoard |
| POST | `/actuarial/credential-applications` | Apply for ASA or FSA; synchronous evaluation with OCC | Candidate |
| GET | `/actuarial/candidates/{id}/credential-applications` | List a candidate's credential applications | Candidate, Registrar |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier the API can return and the HTTP status that accompanies it. The conditions under which each error is raised are defined by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_HEADERS` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_WINDOW_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CANDIDATE_VERSION` | 412 Precondition Failed |
| `ERR_CANDIDATE_NOT_FOUND` | 404 Not Found |
| `ERR_SYLLABUS_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_PASS_MARK_SETTING_NOT_FOUND` | 404 Not Found |
| `ERR_VEE_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_MODULE_NOT_FOUND` | 404 Not Found |
| `ERR_MODULE_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_TRACK_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_ATTENDANCE_NOT_FOUND` | 404 Not Found |
| `ERR_CPD_ATTESTATION_NOT_FOUND` | 404 Not Found |
| `ERR_DISCIPLINE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_CANCELLABLE` | 422 Unprocessable Entity |
| `ERR_PASS_MARK_INVALID_STATE` | 422 Unprocessable Entity |
| `ERR_VEE_NOT_REVIEWABLE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_GRADABLE` | 422 Unprocessable Entity |
| `ERR_SESSION_NOT_BOOKABLE` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_NOT_VERIFIABLE` | 422 Unprocessable Entity |
| `ERR_CPD_NOT_VERIFIABLE` | 422 Unprocessable Entity |
| `ERR_DISCIPLINE_ALREADY_RESOLVED` | 422 Unprocessable Entity |
| `ERR_SYLLABUS_ACTIVATION_INVALID` | 422 Unprocessable Entity |
| `ERR_EXAM_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_ALREADY_HELD` | 409 Conflict |
| `ERR_CANDIDATE_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_VEE_TOPIC_ALREADY_CREDITED` | 409 Conflict |
| `ERR_VEE_GRADE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_REQUIRES_ASSOCIATE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_MODULE_SEQUENCE_LOCKED` | 422 Unprocessable Entity |
| `ERR_PROJECT_REQUIRES_CAPSTONE` | 422 Unprocessable Entity |
| `ERR_GRADER_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CPD_NOT_MEMBER` | 422 Unprocessable Entity |
| `ERR_CPD_CYCLE_DUPLICATE` | 409 Conflict |
| `ERR_MODULE_COOLDOWN_ACTIVE` | 422 Unprocessable Entity |
| `ERR_WINDOW_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SESSION_SAME_DAY_CONFLICT` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
