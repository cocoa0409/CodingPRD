# Continuous Term Enrollment API — Product Requirements Document

## 1. Introduction

A rolling-admission online university lives and dies by the density of its start dates: the more frequently new terms begin, the more often a prospective student can convert interest into enrollment — and the more coordination burden falls on enrollment counselors, academic advisors, financial aid officers, and the registrar. This document specifies an API that operates that model end to end. It tracks the full student funnel from prospect through application, admission decision, transfer-credit evaluation, enrollment conversion, financial aid packaging and disbursement, in-term advising interventions, withdrawal and refund processing, and between-term re-enrollment outreach, all against an academic calendar of continuous term starts.

Three regulatory and operational realities shape every workflow in this system. First, state authorization and licensure disclosure obligations follow the student's location, and the corresponding gates are enforced at admission decision time and again at enrollment conversion. Second, incentive-compensation regulation bars conversion attribution to counselors paid on an incentive plan, and financial aid certification is segregated from packaging so that no single officer both creates and certifies the same package. Third, every temporal rule in the system — enrollment windows, census snapshots, disbursement releases, refund schedules, contact and outreach cadences — is evaluated against a controllable logical clock rather than wall-clock time, so an entire academic year is deterministic and replayable under test.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly seven roles: `SystemAdmin`, `RegistrarAdmin`, `ComplianceOfficer`, `FinancialAidOfficer`, `Counselor`, `Advisor`, and `Applicant`. Access to each operation is restricted by role per the endpoint table in Section 4; a caller whose role is not permitted for an operation, or who violates an ownership rule attached to that operation, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles carry opaque operator identities. When `X-User-Role` is `SystemAdmin`, `RegistrarAdmin`, `ComplianceOfficer`, or `FinancialAidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it against any entity's `id`. The single place such an identifier is recorded is financial aid: the creating `FinancialAidOfficer`'s `X-User-ID` is stamped onto the package as `created_by_officer_id`, where it later serves as the segregation-of-duties anchor at certification time.

The remaining three roles are entity-backed. When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Staff` member, whose `staff_type` must be `COUNSELOR`; ownership checks on any resource that references a counselor — an applicant's `assigned_counselor_id` — compare that field against `X-User-ID`. When `X-User-Role` is `Advisor`, `X-User-ID` is likewise a `Staff` `id` whose `staff_type` must be `ADVISOR`, and ownership checks compare an enrollment's `advisor_id` against `X-User-ID`. A role header that contradicts the referenced staff member's `staff_type` is itself an ownership violation and is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`, and that caller may act only on its own records: an applicant creating or withdrawing an application must be that application's `applicant_id`. Applicant ownership is enforced only where an operation states it; the read operations open to the `Applicant` role in Section 4 are not further restricted by ownership, and the server does not resolve the referenced `Applicant` entity at authentication time.

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
- A request to an unknown path, or to a known path with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100 — an out-of-range integer is clamped into those bounds rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter sets the number of items skipped and defaults to 0, with negative values clamped to 0. Unless otherwise specified, every list endpoint returns resources in creation order — equivalent to `created_at` ascending, with identical timestamps (or a logically regressed clock) resolved by creation sequence. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock

All temporal evaluation in the system — clock gates on term advancement, cadence windows, refund windows, disbursement releases, outreach expiry, financial holds — is resolved against a server-side **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time before the first clock-setting call arrives.

A test-driving capability restricted to `SystemAdmin` sets the logical clock to a caller-supplied `to_iso8601` instant. Every lazy evaluation described later in this document consumes whatever the logical clock reports at the moment the evaluation runs.

### 2.5. Common Resource Properties and Versioning

Every primary resource — Term, Program, Staff, Applicant, Application, TransferCreditEvaluation, Enrollment, CourseSection, FinancialAidPackage, EarlyAlert, and RetentionOutreach — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed counter that starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource. Every state transition, every counter update, and every cascade that touches a resource is a mutation and therefore bumps its `version` and refreshes its `updated_at`. This field is the basis of the optimistic concurrency rules in §2.8.

The StateAuthorization row is the one exception to this convention: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent on state authorization rows, and no operation mutates one in place.

### 2.6. Nested Resource Retrieval

Several endpoints address a resource through its parent's path — for example the sections of a term under `/api/terms/{id}/sections`, the transfer-credit evaluations of an application under `/api/applications/{id}/transfer-credit-evaluations`, or the aid packages of an enrollment under `/api/enrollments/{id}/financial-aid-packages`. For every such request the server validates path identifiers strictly left to right: the parent `id` is resolved first, and only if it exists does the server proceed to the child context. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier — path variable or body-supplied reference — that does not correspond to an existing resource, and later checks never run for a request that has already failed an earlier one. On endpoints that create a sub-resource under a parent path this means the parent's existence is confirmed — `ERR_NOT_FOUND` if missing — before the request body is validated; on action endpoints that target a single resource directly, request-shape validation of the body precedes existence resolution.

### 2.7. Validation Order Across the Request Lifecycle

When a request violates several rules at once, the error it receives is determined by a fixed priority order; the first matching check wins and later checks are never evaluated. The global order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and ownership.** The role must be permitted for the endpoint, an entity-backed caller's `staff_type` must match the role, and ownership rules (an advisor acting on someone else's advisee, an applicant acting on another applicant's record) must hold; otherwise `ERR_FORBIDDEN` (HTTP 403). Ownership checks are evaluated as early as their inputs allow: a rule expressed over payload fields (such as an applicant creating for itself) runs once the request body has been parsed, while a rule that must read the target resource runs immediately after that resource resolves — so a request naming a nonexistent target reports `ERR_NOT_FOUND` before any resource-dependent ownership check, never after.
3. **Request shape.** Required fields must be present, enum values valid, and types correct; otherwise `ERR_INVALID_REQUEST` (HTTP 400). A request body that is not a JSON object at all also fails here. Two shape-level rules have their own codes: a term whose dates violate the required ordering is rejected with `ERR_TERM_DATE_INVALID` (HTTP 422), and an enrollment payload whose `advisor_id` references a staff member whose `staff_type` is not `ADVISOR` fails here as `ERR_INVALID_REQUEST`.
4. **Existence.** Referenced resources must exist, validated left to right; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **State legality.** The target resource must be in a state from which the requested transition is defined — a decision only on a `SUBMITTED` application, a withdrawal only on a `REGISTERED` or `ACTIVE` enrollment, an advance only along a declared edge; otherwise `ERR_INVALID_STATE` (HTTP 409).
6. **Business rules.** Domain-specific safety, constraint, temporal, and fiscal checks, in the pinned relative orders stated below.

Within the business tier, relative order matters on the endpoints that stack several checks. An admission decision evaluates the state-authorization status before the restricted-state disclosure check, so a missing or prohibited authorization surfaces as `ERR_STATE_NOT_AUTHORIZED` rather than being masked by a missing acknowledgement. Enrollment conversion continues that ordering: authorization status, then the restricted-state disclosure, then the licensure disclosure, then the incentive-compensation bar, then transfer-credit evaluation completeness, and finally advisor caseload capacity. Application creation runs its duplicate-application check before the term-open gate, so a second live application for the same applicant and term reports `ERR_DUPLICATE_APPLICATION` even when the term is also closed to enrollment. A roster add checks the section's own status before the add-drop deadline, so a `PLANNED`, `STAFFING`, or `STAFFED` section reports `ERR_SECTION_NOT_OPEN` (and a `LOCKED` section reports `ERR_SECTION_FULL`) even when the deadline has also passed. A section advance to `OPEN` checks state legality before the term-open gate, a deferral back to `REGISTERED` checks the term-open gate before the financial-hold gate, and an enrollment withdrawal checks state legality before the withdrawal window.

### 2.8. Optimistic Concurrency Control on Conversion and Certification

Exactly two write operations in the system carry an optimistic concurrency check, each pinned to the version of a parent entity the client has previously read.

Creating an enrollment requires the request to carry `expected_application_version`, a non-optional field holding the `version` of the application as the client last observed it. If the application's current `version` has advanced since that observation — for example because another writer has already converted the same admitted application, which flips it from `ADMITTED` to `CONVERTED` and bumps `Application.version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an application state it has not observed.

Certifying a financial aid package requires the request to carry `expected_enrollment_version`, a non-optional field holding the `version` of the parent enrollment as the certifying officer last observed it. Certification itself mutates the enrollment by bumping its `version`, so a mismatch against the enrollment's current `version` means another certification-relevant mutation has landed in the interim; the certification is rejected with `ERR_STALE_VERSION` (HTTP 412).

Within the §2.7 priority order, the conversion version check is evaluated after the referenced application and advisor have been resolved and before the application's `ADMITTED` state check; the certification version check is evaluated last, after the package's `PACKAGED` state check and the segregation-of-duties check.

No other endpoint accepts a version field; requests to any other operation must not include one, and a version field sent to any other operation is ignored rather than rejected.

### 2.9. Money, Cents, and Rounding

Every monetary value in the system — tuition, expected family contribution, award amounts, disbursement amounts, returned and retained funds, refunds — is represented as an integer number of cents. Award packaging arithmetic is exact integer arithmetic with no rounding at all. Where a computation can produce a fractional cent — the pro-rata federal funds return and the half-tuition institutional refund — the result is rounded half-up to the nearest whole cent. Grade percentages are compared exactly at two decimal places (for example `70.00` and `60.00`).

### 2.10. Cascading State Propagation and Lazy Evaluation

The academic calendar is the root of the system's dependency graph, and state changes propagate downward from it without requiring per-resource requests. Advancing a term cascades to the term's enrollments, from each enrollment to its financial aid package, and from each package to its individual disbursement schedule entries; the full cascade contract is specified with the term lifecycle in §3.1. Withdrawal propagates in the opposite direction of intent but with the same discipline: a single withdrawal by a `RegistrarAdmin` resolves the enrollment, the applicant's funnel position, every roster seat the enrollment occupies, and the aid package with its schedule entries in one atomic cascade (§3.8). Each resource mutated by a cascade independently increments its own `version` and refreshes its own `updated_at`.

A second family of derivations is evaluated lazily rather than event-driven. The release of scheduled disbursement entries, the expiry of queued or sent retention outreaches, and the `financial_hold` flag on an enrollment are not pushed by background jobs; they are resolved at the moment the affected resource is read or mutated, using the logical clock as of that moment. A client therefore always observes these derived values as of the current logical instant, and an advance attempt on a stale resource can change the resource's state before the requested operation is evaluated.

## 3. Business Logic & Workflows

### 3.1. Academic Calendar: Terms and Their Gates

Everything in the system hangs off the **Term**. A `RegistrarAdmin` creates a term by supplying its `name` (a label such as "2026 Fall A"), the `start_date` on which instruction begins, the `add_drop_end_date` after which roster adds are no longer allowed, the `census_date` at which the enrollment snapshot for aid is taken, and the `end_date` on which the term closes. The four dates must obey a strict ordering: `start_date` strictly before `add_drop_end_date`, `add_drop_end_date` on or before `census_date`, and `census_date` strictly before `end_date`; a term whose dates violate this ordering is rejected with `ERR_TERM_DATE_INVALID`. A new term begins life in `SCHEDULED` status.

A term advances along a fixed path — `SCHEDULED` → `ENROLLMENT_OPEN` → `IN_SESSION` → `CLOSED` — driven by a `RegistrarAdmin` naming a `to_state`, and each step is gated by the logical clock. Opening enrollment is permitted only once the logical clock has reached the point thirty days before `start_date`; attempting it earlier is rejected with `ERR_TERM_CLOCK_NOT_REACHED`. Moving into session requires the logical clock to have reached `start_date` itself, with the same `ERR_TERM_CLOCK_NOT_REACHED` on a premature attempt. Closing the term requires the logical clock to have reached `end_date`, again with `ERR_TERM_CLOCK_NOT_REACHED` otherwise. Requesting a transition that does not exist from the term's current status — for example any advance on a `CLOSED` term — is rejected with `ERR_INVALID_STATE`, and every successful advance increments `Term.version`.

The two later advances carry heavy cascades. When a term moves `ENROLLMENT_OPEN` → `IN_SESSION`, every enrollment of that term still in `REGISTERED` transitions to `ACTIVE`, and for each enrollment that became active, a financial aid package in `CERTIFIED` transitions to `DISBURSING` while every schedule entry whose `release_date` is on or before the current logical date flips from `SCHEDULED` to `DISBURSED`, adding its amount into the package's `disbursed_cents`. When a term moves `IN_SESSION` → `CLOSED`, every enrollment of the term still `ACTIVE` transitions to `COMPLETED`; for each affected enrollment's aid package in `CERTIFIED` or `DISBURSING`, schedule entries still `SCHEDULED` whose `release_date` falls on or before `end_date` transition to `DISBURSED`, while entries whose `release_date` falls after `end_date` transition to `CANCELLED` with their amounts added into `cancelled_cents`, and any such package whose entries have all reached a terminal entry state transitions to `SETTLED`. `CLOSED` is the term's terminal state.

### 3.2. Programs, State Authorization, and Disclosure Obligations

A `RegistrarAdmin` registers each degree program with a unique `code` (for example "BS-CS"), a `title`, the `total_credits_required` to complete the degree, and a `licensure_flag` marking whether the program leads to licensure. The uniqueness of `code` is a data-entry convention and is not validated by the server. The flag is not decorative: it arms a disclosure obligation that must be satisfied before any student may enroll into the program, as described in §3.6.

Because the university enrolls students nationwide, each program's legality varies by the student's state of residence. A `ComplianceOfficer` appends a state authorization row to a program, supplying the `state_code` (conventionally a two-letter US state code; the value is accepted as supplied, with no format validation), an `authorization_status` of `AUTHORIZED`, `RESTRICTED`, `PROHIBITED`, or `PENDING`, the `effective_from` date on which the row takes effect, and optionally the `effective_to` date on which it stops applying; a null `effective_to` marks an open-ended authorization. When the row's `authorization_status` is `RESTRICTED`, a `disclosure_text` describing the restriction must accompany it, and its absence is rejected with `ERR_INVALID_REQUEST`.

Each row governs a half-open window: it applies from `effective_from` inclusive up to `effective_to` exclusive. Two rows for the same `program_id` and `state_code` may not have overlapping windows — an overlapping append is rejected with `ERR_AUTHORIZATION_WINDOW_OVERLAP` — but adjacency is explicitly permitted, so a new row whose `effective_from` equals an existing row's `effective_to` is accepted, allowing a program's status in a state to change over time without gaps or collisions. The current authorization for a program and state pair is the row whose window covers the relevant date as reported by the logical clock, and it is this current row that the admission and enrollment gates consult: an `AUTHORIZED` row clears the gate, a `RESTRICTED` row clears it only with an acknowledged disclosure, and a missing, `PENDING`, or `PROHIBITED` row blocks it outright (§3.4 and §3.6).

### 3.3. Counselors, Advisors, and Caseload Management

The advising workforce is modeled as **Staff**. A `SystemAdmin` creates each staff member with a `full_name`, an `email`, a `staff_type` of `COUNSELOR` or `ADVISOR`, and a `caseload_cap` bounding how many active charges the member may carry — active prospects for a counselor, active advisees for an advisor. An optional `compensation_plan` of `NON_INCENTIVE` or `INCENTIVE` defaults to `NON_INCENTIVE` when omitted; the `INCENTIVE` value is a regulatory marker that later bars conversion attribution (§3.6).

The system maintains a computed `active_caseload_count` on every staff member. For a `COUNSELOR` it counts the applicants whose `assigned_counselor_id` is that member's `id` and whose `status` is `PROSPECT`, `APPLIED`, or `ADMITTED`. For an `ADVISOR` it counts the enrollments whose `advisor_id` is that member's `id` and whose `status` is `REGISTERED`, `ACTIVE`, or `DEFERRED`. Reading a staff member returns this live count alongside the stored fields.

When a prospect enters the system, counselor assignment is automatic rather than requested. The selector considers every staff member with `staff_type` `COUNSELOR` whose `active_caseload_count` is strictly below their `caseload_cap`, ranks the candidates by `active_caseload_count` ascending, breaks ties by `caseload_cap` descending, and breaks remaining ties by creation order (equivalent to `created_at` ascending when the logical clock has not regressed) — never by `id`. The first candidate in that ranking receives the assignment, recorded as the applicant's `assigned_counselor_id`. If the candidate pool is empty, creation still succeeds and `assigned_counselor_id` is simply null; an empty pool is not an error.

Counselor outreach is rate-limited by a rolling contact cadence. A `Counselor` logs a contact attempt against an applicant by supplying a `channel` and an `outcome`; the caller must be that applicant's assigned counselor, and any other caller is rejected with `ERR_FORBIDDEN`. Before appending, the system counts the entries already in the applicant's `contact_log` whose `attempted_at` falls within the trailing half-open window from 168 hours before the current logical instant up to and including that instant — an attempt exactly 168 hours old is excluded from the count, and attempts on every channel and with every outcome count toward the total. If the window already holds three attempts, the new attempt is rejected with `ERR_CONTACT_CADENCE_EXCEEDED`. Otherwise the entry — `channel`, `outcome`, and `attempted_at` stamped with the current logical timestamp — is appended to the append-only `contact_log`, and the applicant's `version` increments by 1. The response is `201 Created` carrying the updated applicant object, including its `contact_log`.

### 3.4. Recruitment: Prospects, Applications, and Admission Decisions

A prospective student enters the funnel as an **Applicant** in `PROSPECT` status, created by a `RegistrarAdmin` or a `Counselor` with a `full_name`, an `email`, and a `state_code` of residence — the state code that will drive every authorization check downstream. The counselor assignment selector of §3.3 runs at creation, and the applicant record accumulates an append-only `contact_log` over its lifetime. From `PROSPECT`, the applicant's status is advanced only as a side effect of application events: submitting an application moves the applicant to `APPLIED`, an admission decision moves them to `ADMITTED`, enrollment conversion moves them to `ENROLLED`, and a later enrollment withdrawal returns them to `ADMITTED` so the student may re-enroll. Each of those transitions increments the applicant's `version`. A side-effect transition fires only when the applicant currently holds the expected source status; an applicant already past that point is left unchanged, with no status change and no `version` bump.

An application is created by an `Applicant` acting for itself or by a `Counselor`, via a payload naming the `applicant_id`, the targeted `term_id`, and the `program_id`, with optional `disclosure_acknowledged` and `licensure_disclosure_acknowledged` booleans that both default to false. An `Applicant` caller may only create for itself — `X-User-ID` must equal the payload's `applicant_id` — and a violation is rejected with `ERR_FORBIDDEN`. Two business gates then apply in a fixed order. First, a duplicate check: if any application already exists for the same `applicant_id` and `term_id` in `SUBMITTED` or `ADMITTED` status, the create is rejected with `ERR_DUPLICATE_APPLICATION` (HTTP 409). Second, a temporal gate: the targeted term must be in `ENROLLMENT_OPEN`, otherwise the create is rejected with `ERR_TERM_NOT_OPEN`. A successful create starts the application in `SUBMITTED` and moves the applicant `PROSPECT` → `APPLIED`, bumping the applicant's `version`. Applications can be listed with the optional filters `applicant_id`, `term_id`, `program_id`, and `status`, combined with the standard `limit` and `offset` pagination.

The admission decision belongs to the `RegistrarAdmin`, who submits a `decision` of `ADMIT` or `DENY` with an optional `reason` that is recorded on the application as `decision_reason`. Decisions are defined only on `SUBMITTED` applications; any other status is rejected with `ERR_INVALID_STATE`. A `DENY` simply moves the application to `DENIED`, a terminal state, and bumps its `version`. An `ADMIT` passes through two compliance gates, evaluated in order: first the current state authorization for the program and the applicant's `state_code` must be `AUTHORIZED` or `RESTRICTED` — a missing row, a `PENDING` row, or a `PROHIBITED` row is rejected with `ERR_STATE_NOT_AUTHORIZED` — and second, when the current row is `RESTRICTED`, the application's `disclosure_acknowledged` must be true, otherwise the decision is rejected with `ERR_DISCLOSURE_REQUIRED`. A successful admit moves the application `SUBMITTED` → `ADMITTED`, moves the applicant `APPLIED` → `ADMITTED`, and bumps both resources' `version` counters.

Either the applicant owner or the assigned counselor may withdraw an application that is still `SUBMITTED` or `ADMITTED`; for a `Counselor` caller the applicant's `assigned_counselor_id` must equal `X-User-ID`, and for an `Applicant` caller `X-User-ID` must equal the application's `applicant_id`, with violations rejected as `ERR_FORBIDDEN`. Withdrawing a `SUBMITTED` application moves it to terminal `WITHDRAWN`. Withdrawing an `ADMITTED` application additionally rolls the applicant back from `ADMITTED` to `APPLIED`, bumping the applicant's `version` as well as the application's.

### 3.5. Transfer Credit Evaluation and the Personalized Degree Path

Before a student enrolls, the registrar evaluates how prior coursework maps onto the degree so the admitted student sees a personalized remaining path. A `RegistrarAdmin` opens a **TransferCreditEvaluation** against an application — the payload carries the `application_id` implicitly through the nested path plus the `accepted_credits` the evaluator is prepared to honor and the `in_progress_credits` the student is completing elsewhere — and the evaluation starts in `DRAFT` with `capped_credits` and `remaining_credits` both zero until completion computes them.

From `DRAFT`, an advance by a `RegistrarAdmin` naming a `to_state` moves the evaluation `DRAFT` → `IN_REVIEW`, and a further advance moves it `IN_REVIEW` → `COMPLETED`. Completion is the moment the degree path is computed, in a pinned order: first the program's `total_credits_required` is read through the evaluation's application; then the transfer cap is computed as three quarters of that total, rounded down to a whole credit; then `capped_credits` is set to the smaller of `accepted_credits` and that cap; and finally `remaining_credits` is set to `total_credits_required` minus `capped_credits` minus `in_progress_credits`, floored at zero so it can never go negative. A completed evaluation may be returned to `IN_REVIEW` for a re-evaluation cycle — but only while no enrollment derived from the same application exists in `REGISTERED`, `ACTIVE`, or `DEFERRED`; once such an enrollment exists the degree path is locked and the attempt is rejected with `ERR_INVALID_STATE`. An evaluation in `DRAFT` or `IN_REVIEW` may instead be advanced to `VOID`, which is terminal. Every advance increments the evaluation's `version`.

### 3.6. Enrollment Conversion and Advisor Assignment

Enrollment conversion is the system's most heavily guarded write: it is the moment a recruited student becomes a registered one, and it concentrates the compliance gates of the whole funnel. A `RegistrarAdmin` converts an application by supplying the `application_id`, the `advisor_id` of the academic advisor who will own the student, an `enrollment_intensity` of `FULL_TIME`, `HALF_TIME`, or `LESS_THAN_HALF_TIME`, the `tuition_cents` charged for the term, and the optimistic-concurrency field `expected_application_version` described in §2.8. A stale application version is rejected with `ERR_STALE_VERSION` (HTTP 412).

The business gates then fire in their pinned order. The application must currently be `ADMITTED`, otherwise `ERR_INVALID_STATE`. The current state authorization for the program and the applicant's `state_code` must be `AUTHORIZED` or `RESTRICTED`, otherwise `ERR_STATE_NOT_AUTHORIZED`. If that row is `RESTRICTED`, `disclosure_acknowledged` must be true, otherwise `ERR_DISCLOSURE_REQUIRED`. If the program's `licensure_flag` is true, `licensure_disclosure_acknowledged` must be true, otherwise `ERR_LICENSURE_DISCLOSURE_REQUIRED`. If the applicant's assigned counselor is on an `INCENTIVE` compensation plan, the conversion would attribute an enrollment to an incentive-paid counselor and is barred outright with `ERR_INCENTIVE_COMP_VIOLATION`. The most recent non-`VOID` transfer credit evaluation for the application must be `COMPLETED` — the degree path must be finalized before enrollment — otherwise `ERR_EVALUATION_INCOMPLETE`. Finally, the chosen advisor must actually be an advisor: an `advisor_id` referencing a staff member whose `staff_type` is not `ADVISOR` fails request validation with `ERR_INVALID_REQUEST`, and an advisor whose `active_caseload_count` has reached their `caseload_cap` is rejected with `ERR_CASELOAD_CAP_EXCEEDED`.

A successful conversion performs several writes at once. The application moves `ADMITTED` → `CONVERTED` (terminal) and its `version` increments; the applicant moves `ADMITTED` → `ENROLLED` and its `version` increments; and the new **Enrollment** is created in `REGISTERED` status with its `term_id` copied from the application's `term_id`, its `withdrawal_date` null, its `institutional_refund_cents` zero, and its `financial_hold` false. Enrollments can be listed with the optional filters `advisor_id`, `term_id`, `application_id`, and `status`, combined with the standard `limit` and `offset` pagination.

### 3.7. Course Sections, Adjunct Staffing, and Roster Management

Capacity planning happens per term through **CourseSection** records. A `RegistrarAdmin` creates a section under a term with a `course_code` (for example "CS-101"), a `capacity` of seats staffed by core faculty, and a `forecast_enrollment` representing expected demand. A new section starts in `PLANNED` status with `seats_available` initialized to `capacity`, `enrolled_count` at zero, and `adjunct_hires` at zero.

Demand beyond core capacity is met by adjunct hiring, and the system computes the gap itself. For each section, `adjuncts_required` is the shortfall of `forecast_enrollment` over `capacity` — never below zero — divided by 30 students per adjunct section and rounded up to a whole adjunct. The rounding order is pinned and matters: the ceiling is applied per section first, and the term-level hiring plan is the sum of the per-section requirements. Summing the shortfalls first and rounding once is wrong and under-hires — with two sections short by 35 and 1 student respectively, the per-section ceilings are 2 and 1 for a plan of 3, whereas summing first would yield 2.

Staffing then proceeds along the section's own state machine, each advance named by a `to_state` from a `RegistrarAdmin` and each incrementing the section's `version`. A section with an unfilled adjunct gap moves `PLANNED` → `STAFFING`, and that move is defined only when `adjuncts_required` is greater than zero — a section with no gap has nothing to staff, and the attempt is rejected with `ERR_INVALID_STATE`. Symmetrically, a section with no gap moves directly `PLANNED` → `STAFFED`, defined only when `adjuncts_required` is exactly zero, with an unfilled gap again rejected as `ERR_INVALID_STATE`. From `STAFFING`, the advance to `STAFFED` carries an `adjunct_hires` payload recording how many adjuncts were actually hired; the payload must be at least `adjuncts_required`, and a missing or insufficient hire count is rejected with `ERR_INVALID_STATE` (a non-integer value fails shape validation as `ERR_INVALID_REQUEST`); a successful advance stores the payload value on the section as its `adjunct_hires`.

A `STAFFED` section may be opened for registration: the advance to `OPEN` requires the parent term to be `ENROLLMENT_OPEN`, and a term in any other status is rejected with `ERR_TERM_NOT_OPEN`. The state-legality check runs before this temporal gate, so an advance requested from the wrong section status reports `ERR_INVALID_STATE` first.

Roster management is a `RegistrarAdmin` operation that adds an `enrollment_id` to a section. Only the referenced enrollment's existence is validated — neither its status nor its term is checked. The section must be `OPEN`: a section in `PLANNED`, `STAFFING`, or `STAFFED` rejects the add with `ERR_SECTION_NOT_OPEN`, while a `LOCKED` section rejects it with `ERR_SECTION_FULL`. Independently, the current logical date must be on or before the term's `add_drop_end_date`; a later add is rejected with `ERR_ADD_DROP_CLOSED`. A successful add increments `enrolled_count` by 1, decrements `seats_available` by 1 — the two are stored counters maintaining the invariant that `enrolled_count` plus `seats_available` always equals `capacity` — and bumps the section's `version`. When an add brings `seats_available` to exactly zero, the section transitions itself `OPEN` → `LOCKED` in the same operation. Re-adding an enrollment already on the section's roster is a no-op: the section is returned unchanged, with no counter movement and no `version` bump.

### 3.8. Financial Aid: Packaging, Certification, Disbursement, and Withdrawal

Financial aid begins once a `FinancialAidOfficer` opens a **FinancialAidPackage** on an enrollment, supplying the `efc_cents` — the expected family contribution. No enrollment-status gate applies: a package may be opened on an enrollment in any status. An enrollment may carry only one active package: if a package already exists in `PACKAGED`, `CERTIFIED`, or `DISBURSING`, the create is rejected with `ERR_PACKAGE_ALREADY_EXISTS` (HTTP 409). A new package starts in `PACKAGED`, records the caller's `X-User-ID` as `created_by_officer_id`, and immediately computes its `estimated_award_cents`. The estimate always assumes full-time attendance regardless of the enrollment's actual `enrollment_intensity`: the cost of attendance for `FULL_TIME` is 800,000 cents ($8,000), and the award is the smaller of the federal Pell maximum of 739,500 cents ($7,395) and the amount by which that cost of attendance exceeds `efc_cents` — never below zero. The package's `certified_award_cents` is 0 until certification, and `disbursed_cents`, `returned_cents`, `retained_cents`, and `cancelled_cents` all start at 0.

Certification is a deliberate second act, performed by a `FinancialAidOfficer` other than the one who created the package: if the certifying `X-User-ID` equals the package's `created_by_officer_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. The request must also carry `expected_enrollment_version` matching the enrollment's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412) per §2.8. Certification computes `certified_award_cents` using the same award formula as the estimate but keyed to the enrollment's actual `enrollment_intensity` — a `HALF_TIME` enrollment is priced against a 500,000-cent ($5,000) cost of attendance and a `LESS_THAN_HALF_TIME` enrollment against 200,000 cents ($2,000) — so identical inputs produce a different number whenever the intensity is not `FULL_TIME`. Certification then builds the `disbursement_schedule`, moves the package `PACKAGED` → `CERTIFIED`, and increments both the package's `version` and the parent enrollment's `version`.

The schedule always has exactly two entries, each carrying a `sequence`, a `release_date`, an `amount_cents`, and an `entry_status` of `SCHEDULED`, `DISBURSED`, `CANCELLED`, or `RETURNED`. Let the term's inclusive length in days run from `start_date` through `end_date`, counting both endpoints; the midpoint falls half that day count — rounded down to a whole number of days — after `start_date`. Entry one releases on the term's `census_date` for half of `certified_award_cents` rounded down to a whole cent; entry two releases at the midpoint for the remainder — `certified_award_cents` minus entry one's amount — so an odd cent always lands on the second entry. Release itself is lazy: whenever the package is read or mutated, entries still `SCHEDULED` whose `release_date` is on or before the current logical date transition to `DISBURSED` while the term is `IN_SESSION`, each adding its amount into `disbursed_cents`. At all times `disbursed_cents` is the gross sum of the entries in `DISBURSED` or `RETURNED`, `cancelled_cents` is the sum of the entries in `CANCELLED`, and `retained_cents` is `disbursed_cents` minus `returned_cents`; once every entry is terminal, `certified_award_cents` equals `disbursed_cents` plus `cancelled_cents` exactly.

From `CERTIFIED`, the package moves to `DISBURSING` when the term goes into session (§3.1), and from `DISBURSING` it settles to terminal `SETTLED` at term close once every schedule entry has reached a terminal entry state. The other exit from either state is a student withdrawal.

Withdrawal is a `RegistrarAdmin` operation on a `REGISTERED` or `ACTIVE` enrollment — any other status is rejected with `ERR_INVALID_STATE`. The payload may name a `withdrawal_date`; when omitted, the current logical date is used. The effective withdrawal date must fall on or before the term's `end_date`, and a later date is rejected with `ERR_WITHDRAWAL_WINDOW_CLOSED`. The cascade that follows is atomic and touches five places: the enrollment moves to terminal `WITHDRAWN`, records its `withdrawal_date`, and bumps its `version`; the applicant returns `ENROLLED` → `ADMITTED` with a `version` bump, leaving the door open to re-enrollment; every section of the term whose roster includes the enrollment decrements `enrolled_count` by 1 and increments `seats_available` by 1, reopening `LOCKED` → `OPEN` if the freed seat was in a full section, each with its own `version` bump; an aid package in `CERTIFIED` or `DISBURSING` transitions to terminal `RETURNED` with a `version` bump; and two refund figures are computed from the same withdrawal date.

The federal return, recorded as the package's `returned_cents`, is pro-rata on disbursed aid with an earned-aid cliff. The term's total length is the inclusive day count from `start_date` through `end_date`; the days completed run from `start_date` through the `withdrawal_date`, again counting both endpoints; the earned share is the exact ratio of days completed to total days. If that earned share is strictly greater than 0.60, no federal funds are returned — and note the boundary is strict, so an earned share of exactly 0.60 still triggers a return. Otherwise `returned_cents` is `disbursed_cents` multiplied by one minus the earned share, rounded half-up to whole cents. Within the same cascade, every schedule entry still `SCHEDULED` transitions to `CANCELLED` with its amount added to `cancelled_cents`, every `DISBURSED` entry transitions to `RETURNED`, and `retained_cents` is recomputed from the new `disbursed_cents` and `returned_cents`.

The institutional refund is a separate step function on `tuition_cents`, independent of how much aid has been disbursed, and it lands on the enrollment as `institutional_refund_cents`. A withdrawal on or before the term's `census_date` refunds the full `tuition_cents`; a withdrawal after census but on or before fourteen days past the `census_date` refunds half of `tuition_cents`, rounded half-up to whole cents; any later withdrawal refunds nothing. Because the two variants measure different bases — disbursed aid versus tuition — the same withdrawal date generally yields different amounts for `returned_cents` and `institutional_refund_cents`.

### 3.9. Early Alerts, Deferral, and Retention Outreach

Once a term is under way, the advising engine watches for students drifting off track. **EarlyAlert** records are injected into the system by a `SystemAdmin` against an enrollment, carrying a `trigger_type` of `GRADE_THRESHOLD` or `LATE_SUBMISSION`. A grade-based alert requires an `observed_grade_percent` strictly below 70.00; a lateness-based alert requires `days_late` of at least 3; a payload whose evidence does not meet its trigger's threshold is rejected with `ERR_ALERT_THRESHOLD_NOT_MET`. The alert's `severity` is computed rather than supplied: it is `HIGH` when the observed grade is below 60.00 or `days_late` is 7 or more, and `LOW` otherwise. A new alert opens in `OPEN` status.

Only the advisor who owns the enrollment may work the alert: every advance requires the caller's `X-User-ID` to equal the enrollment's `advisor_id`, with any other caller rejected as `ERR_FORBIDDEN`. The alert's lifecycle is `OPEN` → `ACKNOWLEDGED` → `INTERVENTION` → `RESOLVED`, with `RESOLVED` terminal; from `INTERVENTION` the advisor may instead escalate to `ESCALATED`, and an `ESCALATED` alert loops back to `INTERVENTION` when the escalation is worked down. Each advance names its `to_state` and increments the alert's `version`.

A student may also step away without withdrawing. A `RegistrarAdmin` defers a `REGISTERED` or `ACTIVE` enrollment by naming `to_state` `DEFERRED`, moving it `REGISTERED` → `DEFERRED` or `ACTIVE` → `DEFERRED` with a `version` bump. Coming back is the re-registration cycle: naming `to_state` `REGISTERED` on a `DEFERRED` enrollment passes two gates in order — the term must be `ENROLLMENT_OPEN`, otherwise `ERR_TERM_NOT_OPEN`, and the enrollment's `financial_hold` must be false, otherwise `ERR_FINANCIAL_HOLD`. The `financial_hold` flag is computed, not stored: it is true exactly when the enrollment's latest financial aid package is still in `PACKAGED` and the current logical date is later than the term's `census_date` — a student whose aid was never certified past the census snapshot cannot quietly re-register.

Between terms, advisors work retention. An `Advisor` queues a **RetentionOutreach** on a `COMPLETED` or `WITHDRAWN` enrollment — any other enrollment status is rejected with `ERR_INVALID_STATE`, and the caller must own the enrollment per the usual advisor ownership rule. On this endpoint the enrollment's existence, the ownership rule, and this status gate are all evaluated before the request body is validated, so an ineligible enrollment reports its own error even when `target_term_id` is missing or malformed. The payload names a `target_term_id`, the term the outreach aims to re-enroll the student into; the value is accepted as supplied and is not validated against existing terms. The new outreach starts in `QUEUED`, its `sent_at` is null, and its `applicant_id` is denormalized from the enrollment's application so that cadence checks can find sibling outreaches for the same person.

That cadence check runs at queue time across the applicant's history: the system finds the most recent outreach for the same `applicant_id` whose status is `SENT` or `RESPONDED` — ties broken by creation order, most recent first (equivalent to `created_at` descending when the logical clock has not regressed), never by `id` — and if that outreach's `sent_at` is less than fourteen days before the current logical instant, the new outreach is rejected with `ERR_OUTREACH_CADENCE`. The boundary is inclusive in the caller's favor: an outreach whose predecessor was sent exactly fourteen days ago is allowed, since only a gap strictly shorter than fourteen days rejects.

The outreach lifecycle is advisor-driven: `QUEUED` → `SENT` stamps `sent_at` with the current logical timestamp; `SENT` → `RESPONDED` records that the student replied; `RESPONDED` → `REENROLLED` is permitted only once a new enrollment for the same applicant exists with `term_id` equal to the outreach's `target_term_id` in `REGISTERED`, `ACTIVE`, or `DEFERRED` status — without that live target enrollment the advance is rejected with `ERR_INVALID_STATE`. Time can also run out on an outreach: a `QUEUED` or `SENT` outreach transitions to `EXPIRED` when the current logical date passes the target term's `start_date`, evaluated lazily on any advance attempt or read of the outreach; if the target term does not exist, no expiry can be evaluated and the outreach is left as-is. `REENROLLED` and `EXPIRED` are terminal, and every advance increments the outreach's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — a term, program, state authorization row, staff member, applicant, contact attempt, application, transfer-credit evaluation, enrollment, course section, financial aid package, or early alert, or a queued retention outreach — return `201 Created` with the created resource in the response envelope. Operations that read or modify an existing resource, including every state advance, decision, withdrawal, deferral, roster add, and certification, return `200 OK`. The clock-setting capability returns `200 OK`. Request payloads, gate conditions, and side effects for every operation are specified narratively in Section 3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default `2026-09-01T00:00:00Z`) | SystemAdmin |
| POST | `/api/terms` | Create a term in `SCHEDULED` | RegistrarAdmin |
| GET | `/api/terms/{id}` | Read one term | SystemAdmin, RegistrarAdmin, ComplianceOfficer, FinancialAidOfficer, Counselor, Advisor, Applicant |
| POST | `/api/terms/{id}/advance` | Advance term status; clock-gated; cascades to enrollments and aid packages | RegistrarAdmin |
| GET | `/api/terms/{id}/sections` | List sections of a term | SystemAdmin, RegistrarAdmin, ComplianceOfficer, FinancialAidOfficer, Counselor, Advisor, Applicant |
| POST | `/api/terms/{id}/sections` | Create a course section in `PLANNED` | RegistrarAdmin |
| POST | `/api/programs` | Create a degree program | RegistrarAdmin |
| GET | `/api/programs/{id}` | Read one program | SystemAdmin, RegistrarAdmin, ComplianceOfficer, FinancialAidOfficer, Counselor, Advisor, Applicant |
| GET | `/api/programs/{id}/state-authorizations` | List state authorization rows for a program | SystemAdmin, RegistrarAdmin, ComplianceOfficer, FinancialAidOfficer, Counselor, Advisor, Applicant |
| POST | `/api/programs/{id}/state-authorizations` | Append a state authorization row | ComplianceOfficer |
| POST | `/api/staff` | Create a counselor or advisor | SystemAdmin |
| GET | `/api/staff/{id}` | Read one staff member including `active_caseload_count` | SystemAdmin, RegistrarAdmin, ComplianceOfficer, FinancialAidOfficer, Counselor, Advisor, Applicant |
| GET | `/api/staff/{id}/applicants` | List applicants assigned to a counselor | SystemAdmin, RegistrarAdmin, Counselor |
| POST | `/api/applicants` | Create a prospect; counselor auto-assigned | RegistrarAdmin, Counselor |
| GET | `/api/applicants/{id}` | Read one applicant including `contact_log` | SystemAdmin, RegistrarAdmin, Counselor, Advisor, Applicant |
| POST | `/api/applicants/{id}/contact-attempts` | Log a contact attempt under the rolling cadence | Counselor |
| POST | `/api/applications` | Create an application in `SUBMITTED` | Applicant, Counselor |
| GET | `/api/applications` | List applications with filters and pagination | SystemAdmin, RegistrarAdmin, Counselor, Advisor |
| GET | `/api/applications/{id}` | Read one application | SystemAdmin, RegistrarAdmin, Counselor, Advisor, Applicant |
| POST | `/api/applications/{id}/decision` | Admit or deny an application | RegistrarAdmin |
| POST | `/api/applications/{id}/withdraw` | Withdraw a `SUBMITTED` or `ADMITTED` application | Applicant, Counselor |
| GET | `/api/applications/{id}/transfer-credit-evaluations` | List transfer credit evaluations for an application | SystemAdmin, RegistrarAdmin, Counselor, Advisor, Applicant |
| POST | `/api/applications/{id}/transfer-credit-evaluations` | Create a transfer credit evaluation in `DRAFT` | RegistrarAdmin |
| POST | `/api/transfer-credit-evaluations/{id}/advance` | Advance evaluation status | RegistrarAdmin |
| POST | `/api/enrollments` | Convert an `ADMITTED` application into an enrollment | RegistrarAdmin |
| GET | `/api/enrollments` | List enrollments with filters and pagination | SystemAdmin, RegistrarAdmin, FinancialAidOfficer, Advisor |
| GET | `/api/enrollments/{id}` | Read one enrollment | SystemAdmin, RegistrarAdmin, FinancialAidOfficer, Advisor |
| POST | `/api/enrollments/{id}/withdraw` | Withdraw an enrollment with full refund cascade | RegistrarAdmin |
| POST | `/api/enrollments/{id}/defer` | Defer or re-register an enrollment | RegistrarAdmin |
| POST | `/api/sections/{id}/advance` | Advance section staffing status | RegistrarAdmin |
| POST | `/api/sections/{id}/roster` | Add an enrollment to a section roster | RegistrarAdmin |
| POST | `/api/enrollments/{id}/financial-aid-packages` | Create an aid package in `PACKAGED` | FinancialAidOfficer |
| POST | `/api/financial-aid-packages/{id}/certify` | Certify a package and build its disbursement schedule | FinancialAidOfficer |
| GET | `/api/enrollments/{id}/financial-aid-packages` | List aid packages for an enrollment | SystemAdmin, RegistrarAdmin, FinancialAidOfficer |
| GET | `/api/enrollments/{id}/early-alerts` | List early alerts for an enrollment | SystemAdmin, RegistrarAdmin, Advisor |
| POST | `/api/enrollments/{id}/early-alerts` | Inject a system early alert | SystemAdmin |
| POST | `/api/early-alerts/{id}/advance` | Advance alert status (owning advisor only) | Advisor |
| POST | `/api/enrollments/{id}/retention-outreaches` | Queue a re-enrollment outreach | Advisor |
| GET | `/api/enrollments/{id}/retention-outreaches` | List retention outreaches for an enrollment | SystemAdmin, RegistrarAdmin, Advisor |
| POST | `/api/retention-outreaches/{id}/advance` | Advance outreach status | Advisor |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of Sections 2 and 3; this table is a lookup of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TERM_DATE_INVALID` | 422 |
| `ERR_TERM_NOT_OPEN` | 422 |
| `ERR_TERM_CLOCK_NOT_REACHED` | 422 |
| `ERR_STATE_NOT_AUTHORIZED` | 422 |
| `ERR_DISCLOSURE_REQUIRED` | 422 |
| `ERR_LICENSURE_DISCLOSURE_REQUIRED` | 422 |
| `ERR_INCENTIVE_COMP_VIOLATION` | 422 |
| `ERR_EVALUATION_INCOMPLETE` | 422 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_CASELOAD_CAP_EXCEEDED` | 422 |
| `ERR_SECTION_NOT_OPEN` | 422 |
| `ERR_SECTION_FULL` | 422 |
| `ERR_AUTHORIZATION_WINDOW_OVERLAP` | 422 |
| `ERR_CONTACT_CADENCE_EXCEEDED` | 422 |
| `ERR_OUTREACH_CADENCE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_ALERT_THRESHOLD_NOT_MET` | 422 |
| `ERR_ADD_DROP_CLOSED` | 422 |
| `ERR_WITHDRAWAL_WINDOW_CLOSED` | 422 |
| `ERR_FINANCIAL_HOLD` | 422 |
| `ERR_PACKAGE_ALREADY_EXISTS` | 409 |








