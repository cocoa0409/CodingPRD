# Campus Recruiting Marketplace API — Product Requirements Document

## 1. Introduction

Campus recruiting runs on federated trust. Employers want a single storefront through which they can reach students at many universities; universities want sovereign control over which employers and which postings may reach their own students; students want a fair, well-lit path from roster record to first destination after graduation. This document specifies the API for that marketplace. It covers university partnership onboarding and student roster provisioning, employer self-registration with domain verification and platform fraud screening, per-university employer approval decisions made by career centers, job and internship postings with eligibility filters, career fairs built from scheduled sessions with student sign-ups and waitlists, applications routed under document requirements with interview scheduling, proactive employer outreach bounded by daily messaging limits, and outcome reporting on the first destination of each graduating cohort.

Three structural choices shape everything that follows. First, trust decisions are federated: the platform screens employers for fraud, but each university's career center independently approves, blocks, or revokes an employer's access to its own students, and can additionally clear or block individual postings. Second, several parties act on the same records — a career center may block an employer while a student of that university holds an outstanding offer — so the specification leans on explicit state machines, on optimistic concurrency for trust-sensitive writes, and on cascaded side effects that keep dependent records consistent. Third, every deadline in the system is evaluated against a logical clock, never against wall-clock time: application deadlines, sign-up windows, session and interview scheduling, and daily messaging buckets all read one server-held clock whose startup value and advancement rules are defined below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract shapes, and evaluation orderings that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `Anonymous`, `PlatformAdmin`, `CareerCenterAdmin`, `EmployerRecruiter`, and `Student`.

When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller label not tied to any persisted entity; anonymous callers may do exactly one thing, employer self-registration. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the platform operator owns university onboarding and lifecycle, employer fraud screening, posting publication, and the logical clock, and the server does not compare its identifier to any entity's `id`.

The remaining three roles are entity-backed, and their `X-User-ID` values participate directly in ownership checks. When `X-User-Role` is `CareerCenterAdmin`, `X-User-ID` is the `id` of the `University` the administrator manages; ownership checks on any resource that references a university — a student roster row, an employer approval, a career event, a clearance action — compare the resource's university foreign key to `X-User-ID`. When `X-User-Role` is `EmployerRecruiter`, `X-User-ID` is the `id` of the `Employer` being operated; ownership checks compare the target's `employer_id` (or the owning employer of a posting or an application) to `X-User-ID`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks compare the target's `student_id` to `X-User-ID`. An entity-backed caller acting outside its owned scope is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

Role permission is evaluated per endpoint and per operation target, not merely per endpoint. A caller whose role is not permitted for the endpoint — or not permitted for the specific target it named, such as a `Student` sending `to` as `PUBLISHED` on a posting transition, or a `Student` writing `status` or outcome fields on the student self-update — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.5 — it is not one of the §2.4 wall-clock properties.
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

Requests that hit an undeclared route or an unsupported method on a declared route fail at the routing layer with the same error envelope, carrying `error_id` `ERR_INVALID_REQUEST` at the routing status (404 or 405) rather than its catalogued 400.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is a shape error, `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system — University, Student, Employer, EmployerApproval, JobPosting, CareerEvent, EventSession, EventSignup, Application, Interview, and OutreachMessage — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix. It serves identity only and is never an input to any business decision.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation and stamped from the server's real wall clock (UTC), not from the logical clock of §2.5.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation and likewise stamped from the server's real wall clock (UTC), not from the logical clock of §2.5.
- `version` (integer): starts at 1 at creation and increments by 1 on every mutation of the resource — including mutations caused by cascaded side effects originating elsewhere, such as a posting whose block list grows because a career center blocked an employer, or an event whose version advances because a session was accepted onto it.

Fields described as computed readouts or recomputed counters — the university's `enrolled_student_count` and `approved_employer_count` (§3.1), a posting's `active_application_count` (§3.4), a session's `occupied_seats` (§3.6), and an application's `documents_status` (§3.7) — are derived at read time from the rows they aggregate; movement in those underlying rows does not itself mutate the carrying resource and does not advance its `version`. Because cascades count as mutations, a client holding a previously read `version` of a resource can detect that something downstream touched it; this is the foundation of the optimistic concurrency rules in §2.8.

### 2.5. The Logical Clock

All temporal evaluation in the system reads a single logical clock. The sole exceptions are the system-managed `created_at` and `updated_at` properties of §2.4, which are stamped from the server's real wall clock (UTC) and never read this clock. Before any explicit clock-set call, the clock reads exactly `2026-09-01T00:00:00Z`; an unset clock never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Setting the clock is side-effect-free apart from the clock itself: in particular, posting expiry is a read-time projection (§2.10), not a background sweep that rewrites rows.

Every timestamp the server stamps for business reasons — application submission, decision times, sign-up registration, outcome recording, the logical-day bucket of an outreach message — is taken from this clock, as are all deadline and window comparisons described in §3.

### 2.6. Numeric Precision and Rounding Conventions

Different quantities follow different, deliberately pinned arithmetic conventions:

- Fraud risk scores, screen counters, seat and application counts, and enrollment/approval counters are pure integer arithmetic with no rounding.
- The daily messaging allowance uses integer floor division of the base-cap-times-multiplier product before taking a minimum against the university ceiling (§3.8).
- Outcome report rates are expressed to exactly 4 decimal places using round-half-up, applied at exactly two pinned points — each per-major rate first, then the final weighted mean — as specified in §3.9. Reordering those rounding points changes the fourth decimal and is non-conformant.
- Deadline and window comparisons are plain instant comparisons against the logical clock; where a bound is inclusive or exclusive, §3 says so explicitly.

### 2.7. Nested Resource Retrieval and Existence Order

Requests that reference resources by identifier are validated for existence in a fixed order. Identifiers embedded in the URL path are validated left to right: on a path such as a session collection under an event, a nonexistent event id is rejected with `ERR_CAREER_EVENT_NOT_FOUND` (HTTP 404) before the session-level checks are even considered. After path identifiers, foreign keys in the request body are validated in the endpoint's declared input order — for example, on application creation `student_id` is resolved before `job_posting_id`, so a request in which both are bad surfaces `ERR_STUDENT_NOT_FOUND`; on sign-up creation `event_session_id` precedes `student_id`; on an approval request `employer_id` precedes `university_id`; on outreach `employer_id` precedes `student_id`.

Each resource type has its own not-found error: `ERR_UNIVERSITY_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_EMPLOYER_APPROVAL_NOT_FOUND`, `ERR_JOB_POSTING_NOT_FOUND`, `ERR_CAREER_EVENT_NOT_FOUND`, `ERR_EVENT_SESSION_NOT_FOUND`, `ERR_EVENT_SIGNUP_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, and `ERR_OUTREACH_MESSAGE_NOT_FOUND` — all HTTP 404.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to present the version of a parent entity it last observed, and both treat a mismatch as a stale-view rejection:

- The career-center trust decision on an employer approval requires a non-optional `expected_employer_version` field equal to the target Employer's current `version`. A decision pins the employer's trust posture as the career center last observed it; if the Employer's `version` has advanced since — for example because a re-screen recomputed its fraud posture — the deciding view is stale and the request is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412).
- Session creation on a career event requires a non-optional `expected_career_event_version` field equal to the target CareerEvent's current `version`. A session is validated against the event window and room plan as last observed; if the CareerEvent's `version` has advanced since — for example because another session was just accepted onto it — the client's view is stale and the create is rejected with `ERR_STALE_CAREER_EVENT_VERSION` (HTTP 412).

No endpoint other than these two accepts a version field.

### 2.9. Order of Evaluation for Rejections

When a request would fail more than one check, the first failure in the following fixed order wins; later checks are not evaluated once an earlier one has failed:

1. Context headers present and role declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role permitted for this endpoint and this operation target — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
3. Entity-backed ownership of the target scope — otherwise `ERR_FORBIDDEN_OWNERSHIP` (403).
4. Existence of referenced resources, path identifiers left to right, then body foreign keys in declared input order — otherwise the resource-specific 404 of the first missing reference.
5. State legality of the target and of related entities (a university that must be `ACTIVE`, a student who must be `ENROLLED`, a posting that must be `PUBLISHED`, an event that must be open enough for the operation, and so on) — otherwise the corresponding state error from §5, all 409.
6. Optimistic concurrency on the two version-gated writes — otherwise `ERR_STALE_EMPLOYER_VERSION` or `ERR_STALE_CAREER_EVENT_VERSION` (412).
7. Trust and privacy safety gates: domain-verification token match, fraud-tier ceiling on screening clearance, per-university employer approval and posting block status, profile visibility, and cross-university sign-up — otherwise `ERR_DOMAIN_VERIFICATION_FAILED`, `ERR_FRAUD_RISK_TOO_HIGH` (409), `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY`, `ERR_POSTING_BLOCKED_FOR_UNIVERSITY`, `ERR_PROFILE_NOT_VISIBLE`, or `ERR_CROSS_UNIVERSITY_ACCESS` (the five latter at 403).
8. Time-window rules under the logical clock: the inclusive application deadline, the exclusive sign-up deadline, session containment inside the event window, and start-before-end shape — otherwise `ERR_APPLICATION_DEADLINE_PASSED` (409), `ERR_SIGNUP_WINDOW_CLOSED` (409), `ERR_SESSION_OUTSIDE_EVENT_WINDOW` (422), or `ERR_TIME_RANGE_INVALID` (400).
9. Constraint checks: posting eligibility in its own pinned sub-order (major, then graduation year, then work authorization, then documents), duplicate guards, and room or interviewer overlap — otherwise one of the four 422 eligibility errors, or a 409 duplicate/conflict error.
10. The daily messaging allowance — otherwise `ERR_MESSAGE_LIMIT_REACHED` (429).
11. Malformed-body residual: a missing required field, a wrong-typed value, an out-of-enum member, a `min_graduation_year` greater than `max_graduation_year`, a `capacity` below 1, an in-person session without a room, or a virtual session carrying one — otherwise `ERR_INVALID_REQUEST` (400).

The residual bucket sits last because every domain rule above pins its own dedicated error; `ERR_INVALID_REQUEST` fires only for undeclared-shape failures that no earlier rule claimed.

### 2.10. Read-Time Expiry Projection for Job Postings

A posting whose stored status is `PUBLISHED` is reported as `EXPIRED` on every read — single read or list — once the logical clock has moved strictly past its `application_deadline`. The comparison is strict and the deadline is inclusive: at the exact instant the clock equals the deadline, the posting still reports `PUBLISHED` and still accepts applications. The stored status is never rewritten by this projection; `EXPIRED` exists only in read output. An apply attempt against a projected-`EXPIRED` posting is rejected as a temporal violation with `ERR_APPLICATION_DEADLINE_PASSED`, never as a state-machine error.

## 3. Business Logic & Workflows

### 3.1. University Onboarding and Student Roster Provisioning

A `PlatformAdmin` opens a university partnership by supplying the university's `name`, its `primary_domain` (the primary email and web domain, such as a state-school domain), and optionally an `employer_daily_message_cap`. The cap is a non-negative integer defaulting to 10 when omitted — a negative cap is a shape error, `ERR_INVALID_REQUEST`; it bounds how many outreach messages any single employer may send to students of this university per logical day (§3.8). A freshly onboarded university lands in `ONBOARDING`.

From there the university lifecycle is platform-driven: `ONBOARDING` moves to `ACTIVE`; `ACTIVE` can be suspended to `SUSPENDED`; `SUSPENDED` can be reactivated to `ACTIVE`; and either `ACTIVE` or `SUSPENDED` can be offboarded to `OFFBOARDED`, which is terminal. Each transition increments the university's `version` by 1, and a request naming any other source-target pair — including anything out of `OFFBOARDED` — is rejected with `ERR_INVALID_UNIVERSITY_TRANSITION` (HTTP 409). Offboarding mutates no student rows. Suspension, however, changes what the university's members and partners may do: while a university is not `ACTIVE`, employer-approval decisions, career-event creation and event transitions of any kind, session creation, event sign-up creation, application creation, and outreach sends at that university are all rejected with `ERR_UNIVERSITY_NOT_ACTIVE` (HTTP 409), and the suspension itself mutates no existing rows.

Two counters live on the university as computed readouts of these workflows: `enrolled_student_count`, the number of its students currently in `ENROLLED` status, and `approved_employer_count`, the number of its employer approvals currently in `APPROVED` status (§3.3 maintains the latter).

Roster provisioning belongs to the `CareerCenterAdmin`. The administrator creates a student with `university_id`, `email`, `full_name`, `major`, `graduation_year`, `work_authorization`, and optionally `profile_visibility`. The `university_id` must be the caller's own university — anything else is `ERR_FORBIDDEN_OWNERSHIP` — and the university must be in `ONBOARDING` or `ACTIVE`; provisioning into any other status fails with `ERR_UNIVERSITY_NOT_PROVISIONABLE` (HTTP 409). The `major` is a code later matched case-sensitively against posting eligibility lists, `graduation_year` is a four-digit year whose eligibility bounds are inclusive, `work_authorization` is one of `US_CITIZEN`, `PERMANENT_RESIDENT`, `VISA_OPT_CPT`, or `SPONSORSHIP_REQUIRED`, and `profile_visibility` is one of `PUBLIC_TO_APPROVED_EMPLOYERS`, `UNIVERSITY_ONLY`, or `HIDDEN`, defaulting to `UNIVERSITY_ONLY` when omitted. A new student starts with `status` `ENROLLED` and `outcome_status` `UNREPORTED`, and the university's `enrolled_student_count` rises by 1.

Profile maintenance splits by role. A `Student` may update only their own `profile_visibility` through the student self-update; a student who sends `status`, `outcome_status`, or `outcome_employer_name` is rejected with `ERR_UNAUTHORIZED_ROLE`. A `CareerCenterAdmin` of the owning university may likewise update `profile_visibility` and drives the academic lifecycle: `ENROLLED` to `ALUMNUS` at graduation, or `ENROLLED` to `WITHDRAWN` when a student leaves. Any other status change — including anything out of `WITHDRAWN`, which is terminal — is rejected with `ERR_INVALID_STUDENT_TRANSITION` (HTTP 409). The outcome-write legality of the next paragraph is evaluated against the student's status before the update, so a single request that both graduates a student and writes outcome fields is rejected with `ERR_OUTCOME_NOT_RECORDABLE`. A self-update that changes no declared field returns the unchanged record and does not increment `version`.

Withdrawal is the destructive branch and cascades in two hops. In the first hop, every application of the withdrawing student in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` moves to `WITHDRAWN`, and each such transition decrements its posting's `active_application_count` by 1; in the second hop, every interview still `SCHEDULED` on one of those just-withdrawn applications moves to `CANCELLED`. A parallel first-hop branch cancels the student's event commitments: every sign-up of the student in `REGISTERED` or `WAITLISTED` moves to `CANCELLED`, and each `REGISTERED` cancellation fires the waitlist-promotion rule of §3.6 on its session. The student's own `version` increments by 1 across the operation.

Graduation opens the outcome-collection window. While — and only while — a student is `ALUMNUS`, the career center may write `outcome_status` (any enum member is accepted, including `UNREPORTED` itself; the meaningful writes are `EMPLOYED`, `GRAD_SCHOOL`, `SEEKING`, or `OTHER`, moving it away from `UNREPORTED`) and the free-text `outcome_employer_name`, which names the first-destination employer or institution and is null until supplied. Attempting these writes on a student who is not `ALUMNUS` fails with `ERR_OUTCOME_NOT_RECORDABLE` (HTTP 409). This is a self-transition on `ALUMNUS` — a field update, not a status change: the first write that leaves `UNREPORTED` stamps `outcome_recorded_at` from the logical clock, later writes leave that stamp untouched, and each write increments the student's `version` by 1.

Student listings respect visibility. A `CareerCenterAdmin` listing students is automatically scoped to their own university; a `PlatformAdmin` listing is unscoped; an `EmployerRecruiter` sees only students whose `profile_visibility` is `PUBLIC_TO_APPROVED_EMPLOYERS` and whose university holds an `APPROVED` employer approval for the caller's employer. The list accepts the filters `university_id`, `major`, `graduation_year`, `status`, and `visible_for_employer_id`, plus `limit` and `offset`. A recruiter reading a single student who is not visible to them is rejected with `ERR_PROFILE_NOT_VISIBLE` (HTTP 403).

### 3.2. Employer Registration, Domain Verification, and Fraud Screening

Employers onboard themselves. An `Anonymous` caller registers with `company_name`, `website_domain`, and `contact_email`; the account is created at 201 in `PENDING` status, and the server mints a `domain_verification_token` that is returned in the creation response and held for the verification step.

Domain verification is the recruiter's next move. Until it completes, the employer's `fraud_risk_score` and `trust_tier` are null. The `EmployerRecruiter` operating that employer submits the `verification_token`; verification is legal only from `PENDING` — a state check that runs before the token check (§2.9), so verifying an employer in any other status is rejected with `ERR_INVALID_EMPLOYER_TRANSITION` (HTTP 409) — and a token that does not equal the stored `domain_verification_token` is rejected with `ERR_DOMAIN_VERIFICATION_FAILED` (HTTP 403). On a match, the employer moves from `PENDING` to `DOMAIN_VERIFIED`, and the automatic screening variant computes its initial `fraud_risk_score` from the registration fields alone. The computation starts at a base of 50 points. If the `contact_email` ends with the at-sign followed by the `website_domain`, 25 points are subtracted — the recruiter demonstrably controls the domain. If the `website_domain` ends with the `.edu` or `.gov` suffix, 15 points are subtracted for an established top-level domain. If the `website_domain` contains a hyphen, 10 points are added. If the `company_name` is shorter than four characters, 10 points are added. The result is clamped into the inclusive range from 0 to 100, higher meaning riskier, all in integer arithmetic.

From the score, the `trust_tier` is re-derived after every score change, on fixed boundaries: a score of 20 or less is `LOW_RISK`; 50 or less is `STANDARD`; 79 or less is `ELEVATED`; anything above that is `HIGH_RISK`.

Thereafter the platform screens the employer. A `PlatformAdmin` issues a screening `decision` of `CLEAR`, `FLAG`, or `REJECT`, optionally accompanied by an `analyst_signal_adjustment` — an integer defaulting to 0 whose absolute value may not exceed 40, an out-of-range adjustment being a shape error, `ERR_INVALID_REQUEST`. Every `CLEAR` or `FLAG` call, before it applies the decision's state change, recomputes the score with the analyst variant: the computation starts from the currently stored `fraud_risk_score`, adds the `analyst_signal_adjustment`, and, when the decision is `FLAG`, adds a further 10 points as the flag penalty; the result is clamped to the inclusive 0-to-100 range and the `trust_tier` is re-derived. `REJECT` does not recompute: it leaves the stored `fraud_risk_score` and `trust_tier` untouched, both remaining null when `REJECT` issues from `PENDING`. Because the analyst variant starts from the stored score and folds in analyst input, identical registration data can yield a different score here than the automatic variant produced. Every screening call also increments `screen_count` by 1 and the employer's `version` by 1, regardless of which decision was issued — `screen_count` therefore counts how many screening calls the employer has absorbed.

The state change each decision drives depends on the employer's current status. `CLEAR` moves an employer from `DOMAIN_VERIFIED` or from `UNDER_REVIEW` to `APPROVED`, but only when the resulting `trust_tier` is not `HIGH_RISK`; a clearance that would leave the employer `HIGH_RISK` is rejected with `ERR_FRAUD_RISK_TOO_HIGH` (HTTP 409). `FLAG` moves an employer from `DOMAIN_VERIFIED` or `APPROVED` to `UNDER_REVIEW`. `REJECT` moves an employer from `PENDING`, `DOMAIN_VERIFIED`, or `UNDER_REVIEW` to `REJECTED` — the platform may reject outright without domain verification. `REJECTED` is terminal: any further screening decision against it, and any decision whose source state is not in the lists above, is rejected with `ERR_INVALID_EMPLOYER_TRANSITION` (HTTP 409). One asymmetry is deliberate: `CLEAR` and `FLAG` require a domain-verified employer, so issuing either against an employer still `PENDING` fails with `ERR_EMPLOYER_NOT_DOMAIN_VERIFIED` (HTTP 409), while `REJECT` from `PENDING` stands.

Employer reads expose the full trust picture — `status`, the `domain_verification_token`, the computed `fraud_risk_score`, the derived `trust_tier`, the `screen_count`, and `last_trust_decision_at`, which stays null until the first career-center decision touches the employer (§3.3). An `EmployerRecruiter` may read only their own employer; a `CareerCenterAdmin` or `PlatformAdmin` may read any employer.

### 3.3. Per-University Trust Decisions: Employer Approvals

Platform approval is not enough to reach a campus. An `EmployerRecruiter` must additionally request approval at each target university, submitting the `employer_id` of their own employer and the `university_id` of the target. The employer must be `APPROVED` at request time, or the request fails with `ERR_EMPLOYER_NOT_APPROVED` (HTTP 409). If an approval row for the same employer-university pair already exists in `PENDING` or `APPROVED`, the request is a duplicate and fails with `ERR_DUPLICATE_APPROVAL_REQUEST` (HTTP 409). If instead the pair's latest row sits in `BLOCKED` or `REVOKED`, the request succeeds and supersedes it: the old row moves to `SUPERSEDED`, and the new row is created in `PENDING` with its `supersedes_approval_id` pointing at the row it replaced; in every other case `supersedes_approval_id` is null. While an approval is `PENDING`, its `decision_reason`, `decided_at`, and `trust_tier_at_decision` are all null.

The decision belongs to the `CareerCenterAdmin` of the approval's university — the caller's university must equal the approval's `university_id` — and the university must be `ACTIVE` at decision time, a check evaluated before transition legality: a non-`ACTIVE` university fails with `ERR_UNIVERSITY_NOT_ACTIVE` even when the requested decision would otherwise be illegal. From `PENDING`, the administrator may decide `APPROVE` or `BLOCK`; from `APPROVED`, the administrator may decide `REVOKE`. Any other combination — deciding `REVOKE` from `PENDING`, deciding anything on a terminal `BLOCKED`, `REVOKED`, or `SUPERSEDED` row — is rejected with `ERR_INVALID_APPROVAL_TRANSITION` (HTTP 409). The optional `decision_reason` text is recorded on the row; the field is overwritten on every decision, so an omitted reason stores null.

Every decision is version-gated against the employer, per §2.8: the request must carry `expected_employer_version` equal to the employer's current `version`, and a mismatch is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412). This is the serialization point between platform fraud screening and university trust decisions: a re-screen that advanced the employer's version forces the career center to re-observe the employer before deciding.

Every accepted decision, whatever its direction, stamps `decided_at` from the logical clock, pins `trust_tier_at_decision` from the employer's current `trust_tier` as of the decision, stamps the employer's `last_trust_decision_at`, and increments the employer's `version` by 1. An `APPROVE` decision then increments the university's `approved_employer_count` by 1; a `REVOKE` decision decrements it by 1.

`BLOCK` and `REVOKE` additionally fire the same three-hop cascade across the employer's footprint at this university. Hop one: for every posting of the employer whose stored status is `PUBLISHED`, this university's id is appended to the posting's `blocked_university_ids`, and each touched posting's `version` increments by 1. Hop two: every application from a student whose `university_id` is this university to one of those just-blocked postings, while in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, moves to `AUTO_WITHDRAWN`, and each such transition decrements its posting's `active_application_count` by 1. Hop three: every interview still `SCHEDULED` on an application that just became `AUTO_WITHDRAWN` moves to `CANCELLED`. The cascade is deliberately conditional: applications already at `OFFER_EXTENDED` are not touched — an outstanding offer survives an employer block.

Approval listings are scoped by caller: a `CareerCenterAdmin` sees their own university's rows, an `EmployerRecruiter` their own employer's rows, and the list accepts the filters `employer_id`, `university_id`, `status`, and `supersedes_approval_id`.

### 3.4. Job Postings: Eligibility Filters, Publication, and University Clearance

An `EmployerRecruiter` creates a posting for their own employer — the `employer_id` in the payload must be the caller's employer — and the employer must be `APPROVED`, failing which the create is rejected with `ERR_EMPLOYER_NOT_APPROVED`. The posting carries a `title`; a `position_type` of `FULL_TIME`, `INTERNSHIP`, or `COOP`; and the eligibility filter set: `required_majors` (an array defaulting to empty, where empty means every major is eligible and a non-empty list requires the student's `major` to be a member), `min_graduation_year` and `max_graduation_year` (both required fields; inclusive lower and upper bounds on the student's `graduation_year`; a `min_graduation_year` greater than `max_graduation_year` is a shape error, `ERR_INVALID_REQUEST`), `accepted_work_authorizations` (an array defaulting to empty, where empty means every authorization is accepted and a non-empty list requires membership), `required_documents` (an array defaulting to empty, whose members are drawn from `RESUME`, `COVER_LETTER`, `TRANSCRIPT`, and `PORTFOLIO`), and the inclusive `application_deadline`. New postings are created in `DRAFT` with `active_application_count` at 0 and `blocked_university_ids` empty.

Publication is a two-key door. The owning recruiter submits a `DRAFT` posting by moving it to `SUBMITTED`. From `SUBMITTED`, only a `PlatformAdmin` may move it to `PUBLISHED` — the platform publication gate — and only while the employer is still `APPROVED`, otherwise `ERR_EMPLOYER_NOT_APPROVED`; a recruiter (or anyone else without the platform role) requesting that target is rejected with `ERR_UNAUTHORIZED_ROLE`. Once live, the owning recruiter may pause a posting from `PUBLISHED` to `PAUSED` and resume it from `PAUSED` back to `PUBLISHED`, resumption again requiring the employer to be `APPROVED`. Publication is the platform's only move: a `PlatformAdmin` requesting any target other than `PUBLISHED` is rejected with `ERR_UNAUTHORIZED_ROLE`, and resumption from `PAUSED` belongs to the owning recruiter alone — a `PlatformAdmin` requesting `PUBLISHED` on a `PAUSED` posting is likewise rejected with `ERR_UNAUTHORIZED_ROLE`. The owning recruiter may close a posting from any of `DRAFT`, `SUBMITTED`, `PUBLISHED`, or `PAUSED` into `CLOSED`, which is terminal: any transition out of `CLOSED` is rejected with `ERR_POSTING_TERMINAL` (HTTP 409), and any other illegal source-target pair with `ERR_INVALID_POSTING_TRANSITION` (HTTP 409). `EXPIRED` is a read-time projection, never a transition target: naming it as `to` is rejected with `ERR_INVALID_POSTING_TRANSITION` (or `ERR_POSTING_TERMINAL` out of `CLOSED`). Each accepted transition increments the posting's `version` by 1.

Independently of stored status, every read of a posting applies the expiry projection of §2.10: a stored-`PUBLISHED` posting reports `EXPIRED` once the logical clock is strictly past its `application_deadline`, while remaining `PUBLISHED` — and open to applications — at the exact deadline instant.

Students see a restricted view of the marketplace. A `Student` listing postings sees only those visible to their own university: postings whose reported status is `PUBLISHED` — so a posting projecting `EXPIRED` under §2.10 drops out — whose `blocked_university_ids` does not contain that university, whose employer is `APPROVED` and holds an `APPROVED` employer approval at that university, at a university that is itself `ACTIVE`. An `EmployerRecruiter` listing postings is scoped to their own employer's rows; a `CareerCenterAdmin` or `PlatformAdmin` listing is unscoped. The posting list accepts the filters `employer_id`, `status`, and `university_id`: `status` matches the reported (post-projection) status, and `university_id` keeps only postings visible to that university under the same rule above. A single-posting read is not visibility-gated: a `Student`, `CareerCenterAdmin`, or `PlatformAdmin` may read any posting, while an `EmployerRecruiter` may read only their own employer's postings (`ERR_FORBIDDEN_OWNERSHIP`).

A career center can also act on a single posting directly. The clearance operation lets a `CareerCenterAdmin` block or unblock a posting at their own university by supplying `university_id` — which must be the caller's own university — and a `decision` of `BLOCK` or `CLEAR`; the posting must be in `PUBLISHED` or `PAUSED` stored status, a clearance against a `CLOSED` posting failing with `ERR_POSTING_TERMINAL` and against a `DRAFT` or `SUBMITTED` posting with `ERR_INVALID_POSTING_TRANSITION`. `BLOCK` appends the university to the posting's `blocked_university_ids` and fires the same application-level cascade as an employer block: applications from students of that university to this posting, while in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, move to `AUTO_WITHDRAWN` with their `SCHEDULED` interviews moving to `CANCELLED` and each transition decrementing the posting's `active_application_count`, while applications at `OFFER_EXTENDED` survive. `CLEAR` removes the university from the list. Either decision increments the posting's `version` by 1.

The `active_application_count` itself is a conserved quantity over the four active statuses — `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, and `OFFER_EXTENDED`. It is recomputed on every application creation and on every application terminal transition, and the bookkeeping is compensating: an application creation followed by that same application's withdrawal returns the count to exactly its prior value.

### 3.5. Career Events and Session Scheduling

Career fairs belong to universities. A `CareerCenterAdmin` creates an event for their own university with `university_id`, `title`, `starts_at`, and `ends_at`; the university must be `ACTIVE`, and `ends_at` must be strictly after `starts_at`, a start-before-end violation being rejected with `ERR_TIME_RANGE_INVALID` (HTTP 400). Events are created in `DRAFT`. Event listings are scoped for a `CareerCenterAdmin` to their own university and accept the filters `university_id` and `status`; other permitted roles list unscoped. Single-event reads and session listings restrict a `CareerCenterAdmin` to their own university's events (`ERR_FORBIDDEN_OWNERSHIP`) and are otherwise ungated.

The event lifecycle then runs `DRAFT` to `OPEN` — which again requires the university to be `ACTIVE` at that moment — `OPEN` to `LOCKED`, and `LOCKED` to `COMPLETED`, with each transition incrementing the event's `version` by 1. The §3.1 suspension gate applies to every event transition and is evaluated before transition legality: at a non-`ACTIVE` university any transition request fails with `ERR_UNIVERSITY_NOT_ACTIVE`. Locking freezes the session catalog: once an event is `LOCKED`, further session creation against it fails with `ERR_EVENT_NOT_OPEN` (HTTP 409). Completion is what makes attendance marking on the event's sign-ups legal (§3.6). Cancellation is available from `DRAFT` or `OPEN` only; any other transition request — including cancelling a `LOCKED` event — is rejected with `ERR_INVALID_EVENT_TRANSITION` (HTTP 409). Cancelling an event cascades downward: every session of the event still `SCHEDULED` moves to `CANCELLED`, and then every sign-up belonging to one of those just-cancelled sessions, while in `REGISTERED` or `WAITLISTED`, moves to `CANCELLED`. No waitlist promotion fires for these freed seats, because the session itself is gone.

Sessions are added to an event while it is in `DRAFT` or `OPEN`. The career center supplies `title`, `mode`, `room_id`, `starts_at`, `ends_at`, `signup_deadline`, `capacity`, and the version-gate field `expected_career_event_version`; the event's identity comes from the request path and is stored on the session as `career_event_id`. The `mode` is `VIRTUAL` or `IN_PERSON`: an in-person session requires a `room_id`, and a virtual session must carry none — either shape violation is `ERR_INVALID_REQUEST`. The `capacity` is the maximum number of `REGISTERED` sign-ups and must be at least 1.

Checks on session creation run in the §2.9 order. First the university-`ACTIVE` gate of §3.1 (`ERR_UNIVERSITY_NOT_ACTIVE`), then the event state gate (`DRAFT` or `OPEN`, else `ERR_EVENT_NOT_OPEN`), then the optimistic-concurrency gate — a stale `expected_career_event_version` is rejected with `ERR_STALE_CAREER_EVENT_VERSION` (HTTP 412), because the session was validated against an event window and room plan that a newer accepted session may already have changed. Temporal checks follow: the session's `starts_at` must be strictly before its `ends_at` (`ERR_TIME_RANGE_INVALID`), and the session must lie inside the event window — the event's `starts_at` at or before the session's `starts_at`, and the session's `ends_at` at or before the event's `ends_at` — with `signup_deadline` at or before the session's `starts_at`; window or deadline violations are rejected with `ERR_SESSION_OUTSIDE_EVENT_WINDOW` (HTTP 422). Only after those pass does the room check run.

Room conflict detection uses half-open interval semantics over the event's existing sessions. A new in-person session conflicts when there exists another session of the same event that is not `CANCELLED`, is itself `IN_PERSON`, carries the same `room_id`, and whose interval overlaps: the new session's `starts_at` strictly before the existing session's `ends_at`, and the existing session's `starts_at` strictly before the new session's `ends_at`. Back-to-back adjacency — the new start exactly equal to an existing end, or vice versa — is not a conflict, and `VIRTUAL` sessions never conflict because they hold no room. A conflict is rejected with `ERR_SESSION_ROOM_CONFLICT` (HTTP 409).

An accepted session starts in `SCHEDULED` with `occupied_seats` at 0. The acceptance also stamps the parent event's `last_session_added_at` and increments the event's `version` by 1 — which is exactly what invalidates any other career-center client still holding the pre-add version for a subsequent session create. Sessions leave `SCHEDULED` in only one way: the parent event's cancellation cascade moves them to `CANCELLED`, their terminal state.

### 3.6. Event Sign-Ups, Waitlists, and Attendance

A `Student` signs up for a session by submitting `event_session_id` and `student_id`, where the `student_id` must be the caller's own student record. The sign-up gates run in §2.9 order. The student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`, 409) at a university that is `ACTIVE` (`ERR_UNIVERSITY_NOT_ACTIVE`). The session's parent event must be in `OPEN` or `LOCKED` and the session itself still `SCHEDULED`; otherwise the attempt fails with `ERR_EVENT_NOT_SIGNABLE` (HTTP 409) — note that a `LOCKED` event still accepts sign-ups; locking froze the session catalog, not registration. The session must belong to an event of the student's own university; a cross-university attempt is rejected with `ERR_CROSS_UNIVERSITY_ACCESS` (HTTP 403). The sign-up window must still be open: the logical clock must read strictly before the session's `signup_deadline`, an exclusive deadline, or the attempt fails with `ERR_SIGNUP_WINDOW_CLOSED` (HTTP 409). And the pair must be fresh: an existing `REGISTERED` or `WAITLISTED` sign-up for the same student and session triggers `ERR_DUPLICATE_SIGNUP` (HTTP 409).

Admission is decided at creation time by the session's seat count. When `occupied_seats` is strictly below `capacity`, the new sign-up lands in `REGISTERED` and its `registered_at` is stamped from the logical clock. When the session is full, the sign-up lands in `WAITLISTED` instead, with `registered_at` null and `promoted_from_waitlist` false. The `occupied_seats` counter itself counts exactly the session's sign-ups in `REGISTERED` and is recomputed on every sign-up creation, cancellation, and promotion.

Cancellation splits by starting state. A student may cancel their own sign-up from `REGISTERED` or `WAITLISTED` into `CANCELLED`. Cancelling a `WAITLISTED` sign-up frees no seat and promotes nobody. Cancelling a `REGISTERED` sign-up, while the session is still `SCHEDULED`, fires waitlist promotion: among the session's `WAITLISTED` sign-ups, exactly one is promoted — the one with the earliest `created_at`, ties broken by the student's `email` in ascending order, never by identifier. The promoted sign-up moves to `REGISTERED`, has its `registered_at` stamped from the logical clock, and is marked `promoted_from_waitlist` true. Because the cancellation removes one occupied seat and the promotion fills one, `occupied_seats` is unchanged by the cancel-promote pair; when the waitlist is empty, the cancellation simply decrements the count by 1. Sign-ups also reach `CANCELLED` through cascades — student withdrawal (§3.1) and event cancellation (§3.5) — and a sign-up in `CANCELLED`, `ATTENDED`, or `NO_SHOW` accepts no further transitions: cancellation from any state other than `REGISTERED` or `WAITLISTED` is rejected with `ERR_INVALID_SIGNUP_TRANSITION` (HTTP 409).

Attendance is marked after the fact. Once the parent event has reached `COMPLETED`, a `CareerCenterAdmin` of the university that owns the event may move a `REGISTERED` sign-up to `ATTENDED` or to `NO_SHOW`. Attempting either marking before the event is `COMPLETED`, or on a sign-up that is not `REGISTERED`, fails with `ERR_INVALID_SIGNUP_TRANSITION`. The transition endpoint partitions its roles by target: a `Student` may request only `CANCELLED` and a `CareerCenterAdmin` only `ATTENDED` or `NO_SHOW`, any other role-target pairing being rejected with `ERR_UNAUTHORIZED_ROLE`.

Sign-up listings are scoped for a `Student` caller to their own rows, for a `CareerCenterAdmin` to the sign-ups belonging to their own university's events, and unscoped for `PlatformAdmin`; they accept the filters `event_session_id`, `student_id`, and `status`.

### 3.7. Applications and Interview Scheduling

A `Student` applies to a posting with `student_id` — necessarily their own — `job_posting_id`, and `submitted_documents`, an array whose entries each name a `doc_type` drawn from `RESUME`, `COVER_LETTER`, `TRANSCRIPT`, or `PORTFOLIO` alongside a `file_uri`. The application walks the full gate chain in §2.9 order, and each gate names its own rejection.

The state gates come first: the applicant must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`), the applicant's university must be `ACTIVE` (`ERR_UNIVERSITY_NOT_ACTIVE`), and the posting's stored status must be `PUBLISHED` — a posting in `DRAFT`, `SUBMITTED`, or `PAUSED` fails with `ERR_POSTING_NOT_PUBLISHED` (HTTP 409). A posting that merely projects `EXPIRED` at read time does not fail here; its rejection arrives at the temporal gate instead. The safety gates follow: an `APPROVED` employer approval must exist for the pairing of the posting's employer and the student's university, otherwise `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY` (HTTP 403); and the posting's `blocked_university_ids` must not contain the student's university, otherwise `ERR_POSTING_BLOCKED_FOR_UNIVERSITY` (HTTP 403). Then the temporal gate: the logical clock must read at or before the posting's `application_deadline` — the deadline is inclusive — and a clock past it is rejected with `ERR_APPLICATION_DEADLINE_PASSED` (HTTP 409).

Eligibility is evaluated last and in a pinned internal order, first failure winning. The major check: the posting's `required_majors` is empty or the student's `major` is a member, else `ERR_MAJOR_NOT_ELIGIBLE` (HTTP 422). The graduation-year check: the student's `graduation_year` is at least `min_graduation_year` and at most `max_graduation_year`, both bounds inclusive, else `ERR_GRAD_YEAR_NOT_ELIGIBLE` (HTTP 422). The work-authorization check: `accepted_work_authorizations` is empty or the student's `work_authorization` is a member, else `ERR_WORK_AUTHORIZATION_NOT_ELIGIBLE` (HTTP 422). The documents check: every document type in the posting's `required_documents` appears among the `submitted_documents`, else `ERR_DOCUMENT_REQUIREMENTS_NOT_MET` (HTTP 422). The duplicate check: no existing application for the same student-posting pair may sit in any of the four active statuses, else `ERR_DUPLICATE_APPLICATION` (HTTP 409).

A created application lands in `SUBMITTED` with `submitted_at` stamped from the logical clock, and the posting's `active_application_count` rises by 1. Its `documents_status` is computed as `COMPLETE` when every document type the posting requires was submitted and `INCOMPLETE` otherwise — a readout of the same membership test the documents gate enforces.

From there, the pipeline belongs to the owning employer's recruiter: `SUBMITTED` to `UNDER_REVIEW`, `UNDER_REVIEW` to `INTERVIEWING`, and `INTERVIEWING` to `OFFER_EXTENDED`, strictly in sequence — a jump that skips a stage, such as `SUBMITTED` directly to `OFFER_EXTENDED`, is rejected with `ERR_INVALID_APPLICATION_TRANSITION` (HTTP 409). The recruiter may also reject from any of the four active states, moving the application to `REJECTED`. The student's own moves are different: the applicant may withdraw from any of the four active states into `WITHDRAWN`, and may answer an offer — `ACCEPTED` or `DECLINED` — only from `OFFER_EXTENDED`. The role partition is enforced by target: a recruiter requesting `WITHDRAWN`, `ACCEPTED`, or `DECLINED`, or a student requesting `UNDER_REVIEW`, `INTERVIEWING`, `OFFER_EXTENDED`, or `REJECTED`, is rejected with `ERR_UNAUTHORIZED_ROLE`. Once an application reaches any terminal state (`ACCEPTED`, `DECLINED`, `REJECTED`, `WITHDRAWN`, or `AUTO_WITHDRAWN`), further transitions fail with `ERR_APPLICATION_TERMINAL` (HTTP 409).

Every terminal transition, in whichever direction, carries the same three side effects: each interview of the application still `SCHEDULED` moves to `CANCELLED`; the posting's `active_application_count` falls by 1; and `decided_at` is stamped from the logical clock. Through every non-terminal state — including `OFFER_EXTENDED` — `decided_at` remains null. The `AUTO_WITHDRAWN` terminal state is never reachable by a direct request: it arrives only through cascades — an employer-approval `BLOCK` or `REVOKE`, a posting clearance `BLOCK` — and only from `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, since `OFFER_EXTENDED` applications survive employer-side blocks.

Interviews are scheduled by the owning posting's recruiter while the application is `INTERVIEWING`; an attempt against an application in any other status is rejected with `ERR_APPLICATION_NOT_INTERVIEWING` (HTTP 409). The request names `interviewer_email`, `mode` (`VIRTUAL` or `IN_PERSON`), `starts_at`, and `ends_at`, with the `application_id` taken from the request path; a start not strictly before the end is `ERR_TIME_RANGE_INVALID`. Conflict detection runs per interviewer across the whole marketplace — every `SCHEDULED` interview bearing the same `interviewer_email`, on any application of any employer, participates — and it is buffered rather than half-open: the new interview conflicts when its `starts_at` is strictly before an existing interview's `ends_at` plus fifteen minutes, and that existing interview's `starts_at` is strictly before the new interview's `ends_at` plus fifteen minutes. Unlike the room rule, exact adjacency is still a conflict: a gap of strictly less than fifteen minutes fails, while a gap of exactly fifteen minutes passes. A conflicting schedule is rejected with `ERR_INTERVIEW_SCHEDULE_CONFLICT` (HTTP 409). A created interview starts in `SCHEDULED` and leaves it only through cascades — its application reaching any terminal state, a student withdrawal, or an employer-side block — landing in `CANCELLED`.

Application listings are scoped by role: a `Student` sees their own, an `EmployerRecruiter` the applications to their own employer's postings, and a `CareerCenterAdmin` the applications of their own university's students; the list accepts the filters `student_id`, `job_posting_id`, and `status`.

### 3.8. Proactive Employer Outreach and the Daily Messaging Allowance

An `EmployerRecruiter` may message a student directly, sending `employer_id` (their own employer), `student_id`, and the message `body`. Outreach is the most heavily gated write in the system. The employer must be `APPROVED` (`ERR_EMPLOYER_NOT_APPROVED`); an `APPROVED` employer approval must exist for the pairing of this employer and the student's university (`ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY`); the student must be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`) at an `ACTIVE` university (`ERR_UNIVERSITY_NOT_ACTIVE`); and the student's `profile_visibility` must be `PUBLIC_TO_APPROVED_EMPLOYERS`, any other setting failing with `ERR_PROFILE_NOT_VISIBLE`.

Only after all trust gates pass does the allowance check run — it sits at priority ten, deliberately after every cheaper rejection. The employer's `trust_tier` sets a tier cap by scaling a base of 5 messages: the tier multiplier is 200 percent for `LOW_RISK`, 100 percent for `STANDARD`, 40 percent for `ELEVATED`, and 0 percent for `HIGH_RISK`, and the tier cap is the integer floor of five times the multiplier percent divided by one hundred — that is, 10 messages per logical day for a `LOW_RISK` employer, 5 for `STANDARD`, 2 for `ELEVATED`, and none at all for `HIGH_RISK`. The effective cap is the minimum of that tier cap and the recipient university's `employer_daily_message_cap`, so a university can tighten — never widen — what an employer's tier would allow. The send is allowed only while the count of messages already sent by this employer to students of this university on the current logical day is strictly below the effective cap; when the count has reached the cap, the send is rejected with `ERR_MESSAGE_LIMIT_REACHED` (HTTP 429).

On an accepted send, the message's `university_id` is denormalized from the student's roster home at send time — that denormalization is what scopes the daily count — and `sent_day` records the logical-day bucket, the calendar date of the logical clock in year-month-day form, against which the count is tallied. Outreach listings are scoped by role — a recruiter sees their own employer's messages, a student their own, a career center their own university's — and accept the filters `employer_id`, `student_id`, and `university_id`.

### 3.9. First-Destination Outcomes and the University Outcome Report

The outcome data collected through the `ALUMNUS`-scoped writes of §3.1 feeds a computed report for each university, available to the `CareerCenterAdmin` who owns that university and to `PlatformAdmin`. The report aggregates over the university's `ALUMNUS` students only — `ENROLLED` and `WITHDRAWN` students are excluded — and returns `alumni_count`, `respondents_count`, `placed_count`, `placement_rate_cohort`, `placement_rate_respondent`, and the per-major breakdown `per_major`.

Three populations define the report. The alumni are the university's students in `ALUMNUS` status. The respondents are those alumni whose `outcome_status` is no longer `UNREPORTED`. The placed are the respondents whose `outcome_status` is `EMPLOYED` or `GRAD_SCHOOL` — the `SEEKING` and `OTHER` outcomes count as reported but not placed.

The two headline rates differ by denominator, and one of them has a pinned, nested rounding order that must not be re-associated. `placement_rate_cohort` is the total placed divided by the total alumni — including alumni who never reported — rounded half-up to 4 decimal places. `placement_rate_respondent` is built from the per-major rates: first, for each distinct `major` among the respondents (the `per_major` entries are sorted by major in ascending order, and a major with zero respondents contributes no entry), compute that major's placed count divided by its respondent count and round the result half-up to 4 decimal places; then take the respondent-weighted mean of those already-rounded per-major rates — weighting each rounded rate by its major's respondent count, dividing by the total respondents — and round that final result half-up to 4 decimal places. Computing the respondent rate from raw totals and rounding only once is the rejected alternative: it yields a different fourth decimal. Because its denominator includes non-respondents while sharing the same numerator, the cohort rate is lower than or equal to the respondent rate on identical data.

Each `per_major` entry carries `major`, `respondents_count`, `placed_count`, and `placement_rate` — the last being that major's already-rounded rate. The empty case is defined rather than exceptional: a university with no alumni at all reports an `alumni_count` of 0, both rates null, and an empty `per_major` array. A university with alumni but zero respondents reports `placement_rate_cohort` computed normally (0.0 when nothing is placed), a null `placement_rate_respondent`, and an empty `per_major` array.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a university, provisioning a student, registering an employer, requesting an approval, creating a posting, event, session, sign-up, application, interview, or outreach message — return `201 Created`. Operations that read, transition, decide, screen, verify, update, or otherwise act on an existing resource return `200 OK`. Request payloads, response fields, and side effects for each endpoint are specified by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/universities` | Onboard a university partnership | PlatformAdmin |
| POST | `/universities/{id}/transition` | University lifecycle transition | PlatformAdmin |
| POST | `/students` | Provision a roster student | CareerCenterAdmin |
| GET | `/students` | List students (role-scoped, visibility-filtered) | CareerCenterAdmin, EmployerRecruiter, PlatformAdmin |
| GET | `/students/{id}` | Read one student | CareerCenterAdmin, Student, EmployerRecruiter, PlatformAdmin |
| PATCH | `/students/{id}` | Update profile visibility, academic status, or outcome data | Student, CareerCenterAdmin |
| POST | `/employers` | Employer self-registration | Anonymous |
| GET | `/employers/{id}` | Read one employer | PlatformAdmin, EmployerRecruiter, CareerCenterAdmin |
| POST | `/employers/{id}/verify-domain` | Submit the domain verification token | EmployerRecruiter |
| POST | `/employers/{id}/screen` | Platform fraud-screening decision | PlatformAdmin |
| POST | `/employer-approvals` | Request employer approval at a university | EmployerRecruiter |
| GET | `/employer-approvals` | List employer approvals (role-scoped) | CareerCenterAdmin, EmployerRecruiter, PlatformAdmin |
| GET | `/employer-approvals/{id}` | Read one employer approval | CareerCenterAdmin, EmployerRecruiter, PlatformAdmin |
| POST | `/employer-approvals/{id}/decide` | Career-center trust decision on an approval | CareerCenterAdmin |
| POST | `/job-postings` | Create a job posting | EmployerRecruiter |
| GET | `/job-postings` | List postings (read-time expiry projection; role-scoped) | Student, EmployerRecruiter, CareerCenterAdmin, PlatformAdmin |
| GET | `/job-postings/{id}` | Read one posting (read-time expiry projection) | Student, EmployerRecruiter, CareerCenterAdmin, PlatformAdmin |
| POST | `/job-postings/{id}/transition` | Posting lifecycle transition | EmployerRecruiter, PlatformAdmin |
| POST | `/job-postings/{id}/clearance` | Block or unblock a posting at the caller's university | CareerCenterAdmin |
| POST | `/career-events` | Create a career event | CareerCenterAdmin |
| GET | `/career-events` | List career events | CareerCenterAdmin, Student, EmployerRecruiter, PlatformAdmin |
| GET | `/career-events/{id}` | Read one career event | CareerCenterAdmin, Student, EmployerRecruiter, PlatformAdmin |
| POST | `/career-events/{id}/transition` | Event lifecycle transition | CareerCenterAdmin |
| POST | `/career-events/{id}/sessions` | Add a session to an event | CareerCenterAdmin |
| GET | `/career-events/{id}/sessions` | List sessions of an event | CareerCenterAdmin, Student, EmployerRecruiter, PlatformAdmin |
| POST | `/event-signups` | Sign a student up for a session | Student |
| GET | `/event-signups` | List event sign-ups (role-scoped) | Student, CareerCenterAdmin, PlatformAdmin |
| GET | `/event-signups/{id}` | Read one event sign-up | Student, CareerCenterAdmin, PlatformAdmin |
| POST | `/event-signups/{id}/transition` | Cancel a sign-up or mark attendance | Student, CareerCenterAdmin |
| POST | `/applications` | Apply to a posting | Student |
| GET | `/applications` | List applications (role-scoped) | Student, EmployerRecruiter, CareerCenterAdmin, PlatformAdmin |
| GET | `/applications/{id}` | Read one application | Student, EmployerRecruiter, CareerCenterAdmin, PlatformAdmin |
| POST | `/applications/{id}/transition` | Advance or terminate an application | EmployerRecruiter, Student |
| POST | `/applications/{id}/interviews` | Schedule an interview on an application | EmployerRecruiter |
| GET | `/applications/{id}/interviews` | List interviews of an application | EmployerRecruiter, Student, CareerCenterAdmin, PlatformAdmin |
| POST | `/outreach-messages` | Send a proactive outreach message to a student | EmployerRecruiter |
| GET | `/outreach-messages` | List outreach messages (role-scoped) | EmployerRecruiter, Student, CareerCenterAdmin, PlatformAdmin |
| GET | `/outreach-messages/{id}` | Read one outreach message | EmployerRecruiter, Student, CareerCenterAdmin, PlatformAdmin |
| GET | `/universities/{id}/outcome-report` | Computed first-destination outcome report | CareerCenterAdmin, PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below fixes the identifier-to-status mapping. The trigger condition for each error is specified where its workflow lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_UNIVERSITY_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_POSTING_NOT_FOUND` | 404 Not Found |
| `ERR_CAREER_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_SIGNUP_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_OUTREACH_MESSAGE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_UNIVERSITY_TRANSITION` | 409 Conflict |
| `ERR_UNIVERSITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_UNIVERSITY_NOT_PROVISIONABLE` | 409 Conflict |
| `ERR_INVALID_STUDENT_TRANSITION` | 409 Conflict |
| `ERR_STUDENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_OUTCOME_NOT_RECORDABLE` | 409 Conflict |
| `ERR_INVALID_EMPLOYER_TRANSITION` | 409 Conflict |
| `ERR_EMPLOYER_NOT_DOMAIN_VERIFIED` | 409 Conflict |
| `ERR_EMPLOYER_NOT_APPROVED` | 409 Conflict |
| `ERR_INVALID_APPROVAL_TRANSITION` | 409 Conflict |
| `ERR_INVALID_POSTING_TRANSITION` | 409 Conflict |
| `ERR_POSTING_TERMINAL` | 409 Conflict |
| `ERR_POSTING_NOT_PUBLISHED` | 409 Conflict |
| `ERR_INVALID_EVENT_TRANSITION` | 409 Conflict |
| `ERR_EVENT_NOT_OPEN` | 409 Conflict |
| `ERR_EVENT_NOT_SIGNABLE` | 409 Conflict |
| `ERR_INVALID_SIGNUP_TRANSITION` | 409 Conflict |
| `ERR_INVALID_APPLICATION_TRANSITION` | 409 Conflict |
| `ERR_APPLICATION_TERMINAL` | 409 Conflict |
| `ERR_APPLICATION_NOT_INTERVIEWING` | 409 Conflict |
| `ERR_STALE_EMPLOYER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CAREER_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_FRAUD_RISK_TOO_HIGH` | 409 Conflict |
| `ERR_DOMAIN_VERIFICATION_FAILED` | 403 Forbidden |
| `ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY` | 403 Forbidden |
| `ERR_POSTING_BLOCKED_FOR_UNIVERSITY` | 403 Forbidden |
| `ERR_PROFILE_NOT_VISIBLE` | 403 Forbidden |
| `ERR_CROSS_UNIVERSITY_ACCESS` | 403 Forbidden |
| `ERR_APPLICATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_SIGNUP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SESSION_OUTSIDE_EVENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_TIME_RANGE_INVALID` | 400 Bad Request |
| `ERR_MAJOR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_GRAD_YEAR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_WORK_AUTHORIZATION_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DOCUMENT_REQUIREMENTS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_APPROVAL_REQUEST` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_SESSION_ROOM_CONFLICT` | 409 Conflict |
| `ERR_INTERVIEW_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_MESSAGE_LIMIT_REACHED` | 429 Too Many Requests |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
