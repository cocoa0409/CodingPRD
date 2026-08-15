# Adjunct Faculty Contracts API — Product Requirements Document

## 1. Introduction

Community colleges deliver a substantial share of their instruction through adjunct faculty, and the administrative machinery behind that workforce is unforgiving. Hiring happens through departmental pools that open and close on fixed calendar windows; every hire must be backed by verified transcripts, degrees, background checks, and training clearances; each course assignment is a separate per-course contract priced against a versioned rate schedule; and a single cancelled section ripples outward through partial-pay clauses, benefits-eligibility load caps, payroll accruals, and next term's reappointment list. When any one of those threads is handled inconsistently, the college either overpays for cancelled sections or undercounts a lecturer's load and wrongly grants or denies benefits.

This document specifies the Adjunct Faculty Contracts API, the backend service that manages that full lifecycle for a multi-department college. The API is mounted under `/adjunct-hr` and serves five operator roles — central HR administration, HR credential review, department chairs, academic deans, and payroll officers — under strict segregation of duties. Every date-sensitive rule in the system reads a controllable logical clock rather than wall-clock time, so an entire academic year can be rehearsed deterministically. Section 2 defines the global contracts every endpoint obeys; Section 3 walks the business workflows in narrative form; Section 4 is the endpoint table; Section 5 is the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the acting role. A request that is missing either header, presents a malformed header, or names a role the system does not declare is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that authenticates cleanly but whose role is not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five roles exist, spelled exactly as written here:

- `HRAdmin` — the central HR administrator; owns departments, terms, and rate schedules; voids contracts; drives the logical clock.
- `HRReviewer` — the HR credential reviewer; files and processes applications and verifies credentials; cannot approve an application whose credentials they personally verified.
- `DepartmentChair` — a department chair; owns pool postings and course sections and issues per-course contracts.
- `Dean` — an academic dean; records evaluations and administers retention lists.
- `PayrollOfficer` — the payroll officer; owns payroll periods and runs payroll close.

Read access is shared: every GET endpoint accepts all five roles. Write access is segregated exactly as the role descriptions state and as the endpoint table in Section 4 enumerates.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`. When `X-User-Role` is `HRReviewer`, the server records the acting reviewer's `X-User-ID` as `verified_by_hr_id` on each credential verification or rejection, and that stamp — not any entity ownership — is what segregation-of-duties checks compare. When `X-User-Role` is `Dean`, the acting dean's `X-User-ID` is recorded as `recorded_by_dean_id` on each evaluation record. When `X-User-Role` is `HRAdmin`, `DepartmentChair`, or `PayrollOfficer`, the identifier is not persisted on any entity at all.

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

### 2.3. Pagination, Sorting, and List Filtering

List endpoints paginate with two query parameters: `limit` defaults to 10, accepts a minimum of 1 and a maximum of 100; `offset` defaults to 0. List results sort by `created_at` ascending. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept optional equality filters named after resource fields. Department listings filter by `active`. Term listings filter by `code` and `rollover_status`. Rate schedule listings filter by `department_id`, `education_tier`, and `schedule_status`. Posting listings filter by `department_id` and `posting_status`, and the per-posting application listing filters by `application_status`. Application listings filter by `posting_id`, `application_status`, `applicant_email`, and `hired_faculty_id`. Credential listings — global or scoped to one application — filter by `application_id`, `kind`, and `verification_status` as applicable. Faculty listings filter by `department_id`, `application_id`, `compliance_status`, `retention_status`, and `benefits_eligible`. Section listings filter by `department_id`, `term_code`, and `section_status`. Contract listings — global, per-faculty, or per-section — filter by `faculty_id`, `section_id`, `rate_schedule_id`, and `contract_status` as applicable. Payroll period listings filter by `period_status`. Payroll entry listings — global, per-period, or per-contract — filter by `contract_id`, `payroll_period_id`, `entry_kind`, and `reversal_of_entry_id` as applicable. Evaluation listings — global or per-faculty — filter by `faculty_id` and `term_code` as applicable. Retention entry listings filter by `faculty_id`, `department_id`, `list_term_code`, and `entry_status`.

### 2.4. The Logical Clock and Academic Calendar Dates

The server keeps its own logical clock, and every date-sensitive rule in this document reads that clock: posting open and close windows, census-tier selection at cancellation, section activation at term start, payroll window overlap, and term rollover. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set call it continues to read that default and never falls back to wall-clock time.

An `HRAdmin` moves the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and answers with the new reading as `current_utc`. Advancing the clock is not inert. Moving it past the final millisecond of a posting's close date automatically closes that posting and expires its untouched applications. Moving it to or past a term's first instructional day flips that term's scheduled sections to running and activates the contracts attached to them, subject to the compliance guard described in Section 3.5.

All calendar fields — term boundaries, census dates, schedule effective windows, posting windows, payroll period windows — are ISO 8601 dates, and timestamps such as `created_at` are ISO 8601 UTC with three fractional digits.

### 2.5. Common Resource Properties and Entity Versioning

Every entity exposed by the API carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp recording when the record was created. All entities except payroll entries and evaluation records additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that increments by one on every mutation of the record, including state transitions and partial updates. Payroll entries and evaluation records carry only `id` and `created_at`; both `updated_at` and `version` are absent from those two resources.

Nested reads validate their path identifiers left to right. When a request names a posting and asks for its applications, the posting identifier is resolved first; an unresolvable identifier anywhere in the path fails the request with `ERR_NOT_FOUND` before any query parameter or body field is examined.

### 2.6. Money, Load Units, and Rounding Discipline

All money in the system is integer cents. Rates are declared in cents (`base_rate_cents`, `longevity_step_cents`), contract amounts are cents (`gross_pay_cents`, `payable_cents`), and payroll entries carry a signed `amount_cents` that is negative on clawbacks. Wherever a calculation yields a fractional cent, the result is rounded half up; each calculation in Section 3 pins the exact point at which that rounding occurs, and rounding never happens earlier or later than stated.

Load units — the currency of the benefits-eligibility cap — are kept at two decimal places, rounded half up after summation. Evaluation component scores are accepted with two decimal places, and composite scores are produced with two decimal places. A department's `contact_hour_value` and a term's `load_cap_units` each carry at most two decimal places and must be strictly positive.

### 2.7. Optimistic Concurrency Control on the Faculty Record

Three writes carry an optimistic concurrency token against the faculty record: `POST /adjunct-hr/contracts` (contract issuance), `POST /adjunct-hr/retention-entries/{id}/reappoint` (reappointment from a retention entry), and `POST /adjunct-hr/retention-entries/{id}/mark-non-reappointed` (non-reappointment). Each of these requests must include `expected_faculty_version`, a non-optional integer carrying the `version` of the target `AdjunctFaculty` record as the client last observed it.

If the supplied token does not match the faculty record's current `version` at write time — because any earlier mutation, including a prior contract issuance or a prior reappointment decision, advanced it — the request is rejected with `ERR_STALE_FACULTY_VERSION` (HTTP 412). The client is expected to re-read the faculty record and retry with the fresh version; this prevents a writer from acting on a load or retention view it has not observed. Endpoints other than the three named above do not take a version field.

### 2.8. Validation Pipeline and Error Precedence

A request that violates several rules at once receives exactly one error: the checks below run in a fixed order and the first failing check wins. The pipeline order is:

1. `ERR_UNAUTHENTICATED` (401) — `X-User-Role` and `X-User-ID` headers are present, well-formed, and the role is one of the five declared roles. Applies to every endpoint.
2. `ERR_UNAUTHORIZED_ROLE` (403) — the acting role appears in the endpoint's authorized role list. Applies to every endpoint.
3. `ERR_NOT_FOUND` (404) — every path identifier and every `*_id` field in the request body resolves to an existing entity, validated left to right, path parameters before body fields. Applies to every endpoint.
4. `ERR_INVALID_STATE` (409) — the requested action exists as a transition from the target entity's current state. This single state error covers terminal-state lockdown and repeated-action (double-action) failures, and it applies to every action endpoint: posting publish, suspend, resume, close, and archive; application start-review, return-for-revision, resubmit, approve, reject, and withdraw; credential verify and reject; section cancel and complete; contract void; payroll period lock and close; reappoint and mark-non-reappointed; and compliance reinstatement.
5. `ERR_POSTING_NOT_OPEN` (409) — application filing window; applies to application creation only.
6. `ERR_SEGREGATION_OF_DUTIES` (403) — approval separation of duties; applies to application approval only.
7. `ERR_COMPLIANCE_INCOMPLETE` (422) — compliance gates; applies to compliance reinstatement and to reappointment.
8. `ERR_CREDENTIALS_INCOMPLETE` (422) — credential completeness at approval; applies to application approval only.
9. `ERR_DUPLICATE` (409) — uniqueness; applies to department creation, term creation, payroll period creation, section creation, and application creation.
10. `ERR_INVALID_DATE_RANGE` (422) — date coherence; applies to term creation, rate schedule creation, posting creation, and payroll period creation.
11. `ERR_SCHEDULE_OVERLAP` (409) — rate schedule publish overlap; applies to schedule publishing only.
12. `ERR_PAYROLL_PERIOD_OVERLAP` (409) — payroll period window overlap; applies to payroll period creation only.
13. `ERR_CANCELLATION_POLICY` (422) — the low-enrollment cancellation policy; applies to section cancellation only.
14. `ERR_CONTRACT_REFERENCE_INVALID` (422) — contract issuance references; applies to contract creation only.
15. `ERR_LOAD_CAP_EXCEEDED` (422) — the load-cap guard; applies to contract creation only.
16. `ERR_PAYROLL_CLOSE_ORDER` (422) — chronological payroll close order; applies to payroll period closing only.
17. `ERR_REVISION_LIMIT` (422) — the revision-loop bound; applies to return-for-revision only.
18. `ERR_REFERENCE_IN_USE` (409) — live-reference guards; applies to rate schedule retirement, posting archival, and department update when deactivating.
19. `ERR_INVALID_REQUEST` (400) — request body schema: required fields present, enum members valid, numeric ranges respected, dates well-formed. Applies to every endpoint.
20. `ERR_STALE_FACULTY_VERSION` (412) — the optimistic concurrency token check; applies to the three OCC-guarded writes named in Section 2.7.

Two consequences of this ordering are worth internalizing. First, request-schema validation sits deliberately late in the pipeline: a request that is both state-illegal and numerically malformed surfaces `ERR_INVALID_STATE`, not `ERR_INVALID_REQUEST`. Second, the concurrency check is the final gate — at contract issuance, for example, the reference checks and the load-cap guard evaluate before the stale-version check, so a request that is both over the load cap and stale is refused with `ERR_LOAD_CAP_EXCEEDED`.

### 2.9. Uniqueness, Interval Overlap, and In-Use Reference Guards

Uniqueness violations surface as `ERR_DUPLICATE` (HTTP 409). A department's `code` is unique across all departments and must be two to twelve uppercase alphanumeric characters. A term's `code` is unique. A payroll period's `period_code` is unique. A course section's natural key — the triple of `term_code`, `course_code`, and `section_code` — is unique. Within a single posting, an `applicant_email` is unique among applications currently in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED`; an email attached only to applications that have reached `REJECTED`, `WITHDRAWN`, or `EXPIRED` may be filed again.

Two interval-overlap regimes exist, and they differ in endpoint semantics. Rate schedules use half-open intervals: a schedule's effective window runs from `effective_start_date` inclusive to `effective_end_date` exclusive, so one schedule whose start equals another schedule's end touches without overlapping and is permitted. Payroll periods use closed intervals: a new period whose `start_date`-to-`end_date` span merely touches an existing non-`CLOSED` period's span — one's end date equal to the other's start date — counts as an overlap and is rejected.

Three destructive or restrictive actions are guarded by live references and fail with `ERR_REFERENCE_IN_USE` (HTTP 409): a rate schedule cannot retire while any contract in `ISSUED` or `ACTIVE` references it; a posting cannot archive while any of its applications sits in `UNDER_REVIEW` or `RETURNED_FOR_REVISION`; and a department cannot be deactivated while any `OPEN` posting or any `ISSUED` or `ACTIVE` contract references it.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Academic Year: Departments and Terms

Before any recruiting happens, an `HRAdmin` registers the college's departments. A department carries a unique `code` (two to twelve uppercase alphanumerics, such as MATH), a display `name`, a `contact_hour_value` expressing how many load units one weekly contact hour is worth in that department's load-cap arithmetic, and an `active` flag that defaults to true when omitted at creation. The `contact_hour_value` must be strictly positive with at most two decimal places; out-of-range values are refused with `ERR_INVALID_REQUEST`. Later, the administrator may patch `name`, `contact_hour_value`, or `active` — each patch bumps the department's `version` by one — but flipping `active` to false is refused with `ERR_REFERENCE_IN_USE` while any `OPEN` posting or any `ISSUED` or `ACTIVE` contract still references the department. New postings, rate schedules, and contracts all require an active department.

Terms come next. A term configuration carries a unique `code` such as 2026FA, a `start_date` marking the inclusive first instructional day, an `end_date` marking the inclusive last instructional day, two census boundaries — `early_census_date` and `late_census_date` — and a `load_cap_units` threshold, strictly positive with at most two decimal places, that drives benefits eligibility. Date coherence is enforced at creation: the `end_date` must fall after the `start_date` with a span of at least fourteen days, and the census boundaries must satisfy the ordering in which `start_date` falls on or before `early_census_date`, `early_census_date` falls strictly before `late_census_date`, and `late_census_date` falls on or before `end_date`. Violations are refused with `ERR_INVALID_DATE_RANGE`. Cancellation strictly before the early census date pays the pre-census tier, while cancellation on or after the early census date — a boundary that includes the day itself — pays the post-census tier; a cancellation on or after `late_census_date` therefore unambiguously pays the post-census tier.

A term begins life with `rollover_status` set to `SCHEDULED`. An `HRAdmin` opens the term, advancing `rollover_status` to `OPEN` — the operational signal that contract issuance into the term may begin — and the open action bumps the term's `version` by one. Issuance and posting publication remain possible until the term's rollover run advances `rollover_status` to `ROLLED_OVER`: from that moment, publishing a posting that names the term is refused with `ERR_INVALID_STATE`, and issuing a contract into the term is refused with `ERR_CONTRACT_REFERENCE_INVALID`. The rollover run itself, an `HRAdmin` checkpoint described fully in Section 3.7, completes the term's finished sections, lapses idle faculty, and recomputes load aggregates.

### 3.2. Rate Schedules: Drafting, Publishing, and Pinning

Compensation for adjunct contracts comes from rate schedules, each scoped to one department via `department_id` and one credential level via `education_tier`, whose members in ascending order are `BACHELORS`, then `MASTERS`, then `DOCTORATE`. The schedule's `rate_basis` declares whether it pays `PER_CONTACT_HOUR` or `PER_COURSE`. Its `base_rate_cents` — an integer of at least one — is the rate per contact-hour unit or per course depending on that basis. Longevity is layered on top: `longevity_step_cents` is the additional cents granted per completed prior term of service, and `longevity_step_cap` bounds how many prior terms are credited; both must be zero or greater. The schedule's effective window runs from `effective_start_date` inclusive to `effective_end_date` exclusive, and the end must fall after the start, with violations refused as `ERR_INVALID_DATE_RANGE`.

A schedule is created in `DRAFT`. Publishing is an `HRAdmin` action guarded by two conditions: the referenced department must be active, and no other `PUBLISHED` schedule may exist for the same pairing of department and education tier whose half-open effective window intersects this schedule's window — half-open adjacency, where one schedule's end date equals the other's start date, is expressly not an overlap. A violation of the overlap guard is refused with `ERR_SCHEDULE_OVERLAP`. At the moment of publish, the schedule records its own then-current `version` counter value as `published_version`, and the publish mutation then increments `version` as every mutation does; `published_version` therefore freezes the counter value the schedule carried when it went live. Contracts later pin that value, as Section 3.5 describes. Publishing advances `schedule_status` from `DRAFT` to `PUBLISHED`.

Retirement advances `schedule_status` from `PUBLISHED` to `RETIRED` and is permitted only while no contract in `ISSUED` or `ACTIVE` references the schedule; otherwise the retire is refused with `ERR_REFERENCE_IN_USE`. Retired is terminal — a schedule never returns to circulation.

### 3.3. Recruiting Pipeline: Pool Postings, Applications, and Credentials

A `DepartmentChair` opens a hiring round by creating a pool posting in `DRAFT`, supplying the `department_id` of the hiring department, the `term_code` the pool hires for, a `title`, the `min_education_tier` that applications must ultimately evidence (`BACHELORS`, `MASTERS`, or `DOCTORATE`), and the application window from `open_date` through `close_date`, both inclusive; the close date must fall on or after the open date, else creation fails with `ERR_INVALID_DATE_RANGE`. The `term_code` is free text while the posting sits in draft and is validated against the college's term configurations only at publish time.

Publishing moves the posting from `DRAFT` to `OPEN` and is allowed only when three conditions hold: the posting's department is active, the named `term_code` matches an existing term whose `rollover_status` is not `ROLLED_OVER`, and the current logical date is on or before `close_date`. A publish attempted from any other state, or with one of those conditions broken, is refused with `ERR_INVALID_STATE`. From `OPEN`, the chair may suspend the posting — `OPEN` to `SUSPENDED` — without further conditions, and later resume it — `SUSPENDED` back to `OPEN` — provided the current logical date is still on or before `close_date`. Closing moves a posting from `OPEN` or `SUSPENDED` to `CLOSED`, and it happens two ways: the chair may close it explicitly, or the system closes it automatically once the logical clock moves past the final millisecond of the close date. Either way, closing cascades: every application still sitting in `SUBMITTED` against that posting transitions to `EXPIRED`. Finally, a `CLOSED` posting may be archived into `ARCHIVED` — the terminal state — but only while none of its applications remains in `UNDER_REVIEW` or `RETURNED_FOR_REVISION`; an in-flight application blocks archival with `ERR_REFERENCE_IN_USE`. Every one of these posting transitions bumps the posting's `version` by one.

Applications are filed by an `HRReviewer` against an `OPEN` posting. Filing carries `posting_id`, the candidate's `applicant_name`, an `applicant_email`, and the candidate's `claimed_education_tier`. The filing window is strict: the posting must be in `OPEN` status and the current logical date must fall within the inclusive window from `open_date` to `close_date`, or the filing is refused with `ERR_POSTING_NOT_OPEN`. The duplicate-email rule of Section 2.9 applies per posting, with violations refused as `ERR_DUPLICATE`. A new application begins in `SUBMITTED`.

Review begins when an `HRReviewer` starts review on a `SUBMITTED` application whose posting is `OPEN`, moving it to `UNDER_REVIEW`. From there the pipeline branches. Returning the application for revision moves it to `RETURNED_FOR_REVISION`, increments its `revision_count` by one, and is bounded: the return is allowed only while `revision_count` is below three, so an application may cycle `UNDER_REVIEW` to `RETURNED_FOR_REVISION` and back at most three times, and a fourth return attempt is refused with `ERR_REVISION_LIMIT`. Resubmitting moves a `RETURNED_FOR_REVISION` application back to `UNDER_REVIEW` and is permitted while the posting is either `OPEN` or `SUSPENDED`. Rejecting moves an `UNDER_REVIEW` application to `REJECTED`. Withdrawing — from either `SUBMITTED` or `UNDER_REVIEW` — moves the application to `WITHDRAWN`. The terminal application states are `APPROVED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED`; any action attempted from a terminal state fails the state gate with `ERR_INVALID_STATE`.

Credential evidence accumulates on the application through records an `HRReviewer` registers with the application: each carries the `application_id`, a `kind` drawn from `TRANSCRIPT`, `DEGREE`, `LICENSE`, `BACKGROUND_CHECK`, or `TRAINING`, an opaque `evidence_ref` pointing at the uploaded evidence, and — where the evidence attests an education level, which is meaningful only for `TRANSCRIPT` and `DEGREE` records — an optional `verified_education_tier`. Registration is accepted while the application is `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_REVISION`, or `APPROVED`; the last of these exists so post-hire compliance paperwork can be registered after the hiring decision. Each record begins in `PENDING`.

Deciding a credential is separate from registering it. Verifying moves a record from `PENDING` to `VERIFIED`, rejecting moves it from `PENDING` to `REJECTED`, and both are allowed only while the application is `UNDER_REVIEW` or `APPROVED`. Either decision stamps the record with `verified_by_hr_id` — the acting reviewer's `X-User-ID` — and `decided_at`, the current logical timestamp. When the application is already `APPROVED` and a verify decision completes the pair of verified `BACKGROUND_CHECK` and `TRAINING` credentials, the hired faculty member's compliance status flips automatically, as Section 3.4 describes.

Approval is the pipeline's gate with the most conditions, evaluated in the pipeline order of Section 2.8 — state gate first, then segregation of duties, then credential completeness. The application must be `UNDER_REVIEW`. The acting reviewer's `X-User-ID` must differ from `verified_by_hr_id` on every `VERIFIED` credential of the application: a reviewer who personally verified any credential on a file cannot approve that file, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` — this refusal surfaces even if the credential file is also incomplete, because the segregation check evaluates first. Completeness then demands three things, any failure of which is refused with `ERR_CREDENTIALS_INCOMPLETE`: every `TRANSCRIPT` and `DEGREE` credential on the application is `VERIFIED`; at least one `VERIFIED` credential evidences a `verified_education_tier` at or above the posting's `min_education_tier`, using the tier ordering in which `BACHELORS` ranks below `MASTERS`, which ranks below `DOCTORATE`; and no credential of any kind on the application remains `PENDING`.

A successful approval moves the application to `APPROVED` and creates the faculty record: the new `AdjunctFaculty` carries the application's `application_id`, the posting's `department_id`, a `legal_name` copied from `applicant_name`, an `education_tier` set to the highest tier evidenced among the application's verified credentials, and a `hire_date` set to the current logical date. The faculty record starts with `compliance_status` `ONBOARDING` and `retention_status` `PROVISIONAL`, and the system immediately evaluates the onboarding-to-compliant automatic transition against any already-verified `BACKGROUND_CHECK` and `TRAINING` credentials on the application, so a fully cleared applicant is created directly in `COMPLIANT`. The application's `hired_faculty_id` is set to the new record, and the application's `version` increments.

### 3.4. Faculty Records and the Two Parallel Status Dimensions

The faculty record is the hub of everything downstream: contracts reference it, payroll accrues against it, and two independent status dimensions evolve in parallel on the same row. The compliance dimension — `compliance_status` — moves among `ONBOARDING`, `COMPLIANT`, and `LAPSED`, and gates whether issued contracts may activate. The retention dimension — `retention_status` — moves among `PROVISIONAL`, `RETENTION_LISTED`, and `NON_REAPPOINTED`, and gates whether new contracts may be issued at all. Neither dimension implies anything about the other.

On the compliance dimension, the move from `ONBOARDING` to `COMPLIANT` is automatic: as soon as the originating application carries both a `VERIFIED` `BACKGROUND_CHECK` credential and a `VERIFIED` `TRAINING` credential, the faculty record flips to `COMPLIANT` and its `version` increments. That evaluation happens at approval time and again whenever a post-approval verify decision completes the pair. The move from `COMPLIANT` to `LAPSED` is also automatic: during the term rollover run, any `COMPLIANT` faculty member who holds no `ACTIVE` and no `COMPLETED` contract in the term being closed lapses. Reinstatement — `LAPSED` back to `COMPLIANT` — is a manual `HRReviewer` action requiring at least one `VERIFIED` `BACKGROUND_CHECK` credential on file for the originating application; without it the reinstatement is refused with `ERR_COMPLIANCE_INCOMPLETE`. Each of these transitions bumps the faculty `version` by one.

Load tracking lives on this record too. The system maintains `current_term_load_units`, the sum of `load_units` over the faculty's contracts in the current term, and `benefits_eligible`, a boolean that is true exactly when that sum reaches or exceeds the current term's `load_cap_units` — the comparison is inclusive, so a load exactly equal to the cap qualifies. "Current term" means the term whose `start_date` falls on or before the current logical date and whose `end_date` falls on or after it; when no term contains the current logical date, the current term is the chronologically next term by `start_date`, with ties broken by the earliest `created_at` among the tied term configurations. The benefits boundary itself is a computed flag, never an error: crossing it flips `benefits_eligible` and blocks nothing.

Two load variants exist, and they answer different questions. The authoritative actual variant sums `load_units` over contracts in `ACTIVE` status only; `current_term_load_units` always stores this variant, and it is what `benefits_eligible` reads. The scheduled variant sums `load_units` over contracts in either `ISSUED` or `ACTIVE` status, making it a pre-term planning preview: for identical contract data before the term starts, the scheduled variant reports a higher number, because an issued-but-not-yet-activated contract contributes its full `load_units` to the scheduled figure and zero to the actual one. Sums are rounded half up to two decimal places after summation. A computed read of load returns the actual variant by default and the scheduled variant when the caller passes the `variant` query parameter as `scheduled`; the response carries `load_units`, the echoed `variant`, the resolved `term_code`, the term's `load_cap_units`, and the resulting `benefits_eligible`. Recomputation of both the stored sum and the flag is triggered by every contract transition into or out of `ACTIVE`, by section cancellation and completion cascades, by contract voiding, and by the non-reappointment cascade of Section 3.8.

### 3.5. Course Sections and Contract Issuance

A `DepartmentChair` builds the term's teaching plan as course sections. Creating a section requires the owning `department_id`, a `term_code` that must match an existing term configuration's code, a `course_code` such as ENG-101, a `section_code` such as 01, the `weekly_contact_hours` the section meets (strictly positive, at most two decimal places), informational `credit_hours` of zero or more, a `min_enrollment` of zero or more below which the section becomes cancellable for low enrollment, and an optional `enrollment` that defaults to zero. The natural key of `term_code`, `course_code`, and `section_code` must be unique, with conflicts refused as `ERR_DUPLICATE`. A section begins `SCHEDULED`. While it is `SCHEDULED` or `RUNNING`, the chair may patch its `enrollment` — and only its `enrollment` — with each patch bumping the section's `version`.

When the logical clock reaches the term's `start_date` at midnight UTC, every `SCHEDULED` section of that term flips to `RUNNING`, and each contract attached to the section in `ISSUED` status attempts activation. Activation is guarded: the contract moves from `ISSUED` to `ACTIVE` only when its faculty's `compliance_status` is `COMPLIANT`. A contract whose faculty is still in onboarding or has lapsed remains `ISSUED` while the section runs without it — the section flip is not blocked. Every successful activation recomputes the faculty's load aggregates per Section 3.4.

Contract issuance is the chair's central write. The issuance payload names the `faculty_id` of the instructor of record, the `section_id` of the course covered, the `rate_schedule_id` pricing the work, and the OCC token `expected_faculty_version` described in Section 2.7, which is recorded on the contract itself. Reference validity is checked before anything computes, with any failure refused as `ERR_CONTRACT_REFERENCE_INVALID`: the named rate schedule must be `PUBLISHED`; the schedule's department must match the section's department; the schedule's `education_tier` must equal the faculty's `education_tier`; the schedule's effective window must cover the section's term `start_date`; the section must not be `CANCELLED` or `COMPLETED`; the faculty's `retention_status` must not be `NON_REAPPOINTED`; and the term's `rollover_status` must not be `ROLLED_OVER`.

Next comes the load-cap guard. The faculty's prospective load for the section's term is the sum of `load_units` over that faculty's existing `ISSUED` and `ACTIVE` contracts in the term plus the new contract's `load_units`. Issuance is refused with `ERR_LOAD_CAP_EXCEEDED` only when that prospective sum is strictly greater than the term's `load_cap_units` plus an overage allowance of 1.00 load unit; a prospective load of exactly the cap plus 1.00 passes. This guard is deliberately distinct from the benefits boundary — the cap plus allowance constrains what may be signed, while the `benefits_eligible` flag merely reports what the signed load implies.

An issued contract freezes several computed snapshots. Its `load_units` is the section's `weekly_contact_hours` multiplied by the department's `contact_hour_value` at issuance, stored as a frozen snapshot immune to later schedule or section edits. Its `gross_pay_cents` is the full-term provisional gross: the server credits the faculty's longevity as the smaller of `completed_terms` and the schedule's `longevity_step_cap`, computes an effective rate of `base_rate_cents` plus that credited count times `longevity_step_cents`, and then branches on basis. Under `PER_CONTACT_HOUR`, the term's length in whole weeks is the day count between `start_date` and `end_date` divided by seven with any fractional week discarded — only whole weeks count — and the billable units are the section's `weekly_contact_hours` multiplied by that whole-week count at full precision, with the gross equal to the effective rate times those units. Under `PER_COURSE`, the gross is the effective rate applied once. Either way the result is rounded half up to whole cents exactly once, at the very end. The contract's `payable_cents` starts out equal to `gross_pay_cents` and stays there until a terminal event reprices it. Its `pinned_schedule_version` captures the schedule's `published_version` at issuance for stale-pin detection. The contract begins life in `ISSUED`, and the issuance bumps the faculty record's `version` by one — which is precisely why a second issuance against the same faculty must carry a freshly observed `expected_faculty_version`.

### 3.6. Section Endings: Cancellation Tiers, Partial Pay, and Completion

A `DepartmentChair` may cancel a section that is `SCHEDULED` or `RUNNING`, supplying a `cancellation_reason` drawn from `LOW_ENROLLMENT`, `PROGRAM_CUT`, `FACULTY_INITIATED`, or `ADMINISTRATIVE`. One policy constrains the reason: a cancellation citing `LOW_ENROLLMENT` requires the section's `enrollment` to be strictly below `min_enrollment` and the current logical date to be strictly before the term's `early_census_date` — both strict — or the cancel is refused with `ERR_CANCELLATION_POLICY`.

Cancelling a `SCHEDULED` section is always a pre-census event, because the term has not started: every attached contract in `ISSUED` or `ACTIVE` moves to `CANCELLED_PRE_CENSUS` with `cancelled_at` stamped to the current logical timestamp, and each is repriced at the pre-census tier. Cancelling a `RUNNING` section splits on the census boundary: attached contracts move to `CANCELLED_PRE_CENSUS` when the current logical date falls strictly before `early_census_date`, and to `CANCELLED_LATE` when it falls on or after that date. Both paths recompute every affected faculty member's load aggregates, bump the section's `version`, and reprice each cancelled contract; the running-section path additionally posts clawbacks for accrued excess, as Section 3.7 details.

The partial-pay clause prices a cancelled contract against the term's census calendar using the calendar date of `cancelled_at`. In the pre-census tier — cancellation date strictly before `early_census_date` — the payable amount is ten percent of `gross_pay_cents`, and that base component is rounded half up to whole cents first; only then is the fixed onboarding stipend of 5,000 cents added, the stipend being already a whole-cent figure that is never rounded. Elapsed time is irrelevant in this tier. In the late tier — cancellation date on or after `early_census_date`, the boundary day included — the clause pays the larger of two independently rounded components. The earned component counts the term's total days inclusively from `start_date` through `end_date`, counts elapsed days inclusively from `start_date` through the cancellation date, and multiplies `gross_pay_cents` by the exact ratio of elapsed to total days carried at full precision before rounding the result half up to whole cents. The floor component is twenty-five percent of `gross_pay_cents`, rounded half up on its own. The payable amount is the maximum of the two, and the onboarding stipend is not paid in the late tier. The result replaces the contract's `payable_cents`, and the contract reaches one of its terminal states: `CANCELLED_PRE_CENSUS` or `CANCELLED_LATE`.

Two other terminal outcomes exist. An `HRAdmin` may void a contract that is still `ISSUED` — never activated — moving it to `VOIDED`, zeroing its `payable_cents`, and reversing any accruals posted for it in `OPEN` payroll periods through clawback entries; the retention cascade of Section 3.8 drives the same transition. Completion is the happy ending: a `RUNNING` section moves to `COMPLETED` once the current logical date falls strictly after the term's `end_date`, either automatically during the rollover run or at the chair's explicit request. Completion moves every attached `ACTIVE` contract to `COMPLETED`, sets each such contract's `payable_cents` equal to its `gross_pay_cents` — the final variant of the pay calculation — increments the faculty's `completed_terms` by one per completed contract, and recomputes load aggregates. A section's terminal states are `CANCELLED` and `COMPLETED`; the section-level `section_status` reads `CANCELLED` or `COMPLETED` accordingly while its contracts carry their own finer-grained outcomes.

### 3.7. Payroll Periods, Accrual Splits, and Term-End Rollover

Payroll runs on explicit periods owned by the `PayrollOfficer`. A period is created with a unique `period_code` such as 2026FA-P1, an inclusive `start_date`, and an inclusive `end_date` that must fall on or after the start, else creation fails with `ERR_INVALID_DATE_RANGE`. Creation is refused with `ERR_PAYROLL_PERIOD_OVERLAP` when the new period's closed window intersects any existing period not yet `CLOSED` — and because payroll intervals are closed, a new period whose start date equals an existing open period's end date already counts as overlapping. A period begins `OPEN`, moves to `LOCKED` at the officer's lock action, and moves from `LOCKED` to `CLOSED` at the close action.

Closing is the checkpoint that materializes payroll entries, and it is chronologically disciplined: a period may close only after every period with an earlier `start_date` is already `CLOSED`, and an already-`CLOSED` period rejects any further close; violations of either rule surface as `ERR_PAYROLL_CLOSE_ORDER`. At the close of a period, the run posts an `ACCRUAL` entry for every contract in `ISSUED`, `ACTIVE`, `CANCELLED_PRE_CENSUS`, `CANCELLED_LATE`, or `COMPLETED` whose term window overlaps the period and which has not yet been accrued for that period; contracts in `VOIDED` are excluded from accrual entirely. The same close posts a `CANCELLATION_PAYOUT` entry — the contract's `payable_cents` minus its prior accruals minus its prior clawbacks — for each contract cancelled before this close. Every entry records its `contract_id`, its `payroll_period_id`, its `entry_kind` (`ACCRUAL`, `CANCELLATION_PAYOUT`, or `CLAWBACK`), a signed `amount_cents`, the `split_variant` that produced it, a `posted_at` timestamp from the close run, and — on clawbacks — a `reversal_of_entry_id` naming the accrual it reverses. No endpoint creates payroll entries directly; they exist only as the output of close runs and cancellation clawbacks.

The split schedule behind each accrual deserves precise statement, because two variants exist and they answer differently. For a given contract, the schedule is computed over all payroll periods of any status whose closed date window intersects the contract's term window, and the entry posted at a period's close is exactly that period's slice — never the whole remaining payable; periods created later change the schedule only for periods not yet `CLOSED`. The variant is pinned per contract by its rate schedule's `rate_basis`: `PER_COURSE` contracts accrue under `EQUAL_SPLIT`, and `PER_CONTACT_HOUR` contracts accrue under `DAYS_WEIGHTED`.

Under `EQUAL_SPLIT`, the contract's `payable_cents` is divided by the number of overlapping periods using integer division that discards any fractional cent, giving every period the same base amount; the remainder — the payable minus the base times the period count — is then distributed one cent each to the chronologically earliest periods, ordered by `start_date` with ties broken by the earlier period `created_at`. Under `DAYS_WEIGHTED`, each period's overlap days are counted as the calendar dates falling inside both the period's inclusive window and the term's inclusive window; walking the overlapping periods in chronological order — `start_date` ascending, ties by `created_at` ascending — every period except the last receives the payable multiplied by the ratio of its overlap days to the total overlap days, rounded half up to whole cents, and the chronologically last period receives whatever remains of `payable_cents` after the earlier slices, so rounding residue is swept into the final period and the per-contract total is always exact. When a period closes, the posted accrual is its slice minus anything already posted for that period, which is normally zero. When a cancellation reduces a contract's payable after earlier periods have closed, the excess of prior accruals over the new `payable_cents` is reversed through `CLAWBACK` entries posted into the earliest period still `OPEN` — earliest `start_date`, ties by earliest `created_at` — or, when no `OPEN` period exists, into the period currently being closed.

The term rollover run is the college's other checkpoint, invoked by an `HRAdmin` against a specific term. The run completes every `RUNNING` section of that term whose `end_date` falls strictly before the current logical date, with the full contract-completion cascade of Section 3.6; it lapses every `COMPLIANT` faculty member who holds no `ACTIVE` and no `COMPLETED` contract in the term being closed; it recomputes faculty load aggregates; and it advances the term's `rollover_status` to `ROLLED_OVER`, sealing the term against further issuance and posting publishes per Section 3.1.

### 3.8. Evaluations, Retention Lists, and Reappointment Decisions

After a term's teaching is done, a `Dean` records an evaluation for a faculty member, supplying the `faculty_id`, the `term_code` evaluated, and three component scores — `teaching_score` for teaching effectiveness, `service_score` for service and availability, and `compliance_score` for compliance timeliness — each between 0.00 and 5.00 inclusive with at most two decimal places, with out-of-range values refused as `ERR_INVALID_REQUEST`. The server stamps the record with `recorded_by_dean_id`, the acting dean's `X-User-ID`.

Each evaluation's `composite_score` is a weighted blend with pinned weights: teaching contributes sixty percent, service twenty-five percent, and compliance fifteen percent. Each component is scaled first — the score multiplied by its weight and by one hundred — and rounded half up to an integer number of hundredths, and only then are the three rounded components summed; dividing that sum by one hundred yields the two-decimal composite. Rounding is per component before summation, always in that order.

Retention entries assemble a department's reappointment list for the next hiring round. A `Dean` creates an entry naming the `faculty_id`, the `department_id` scoping the list, and the `list_term_code` of the term the list applies to; the entry begins in `LISTED`. Creation re-ranks the entire scope: the server gathers every `LISTED` entry sharing the new entry's `department_id` and `list_term_code` — gathered after inserting the new one — and orders them by a ranking score, which for each faculty is the `composite_score` of that faculty's most recent evaluation whose `term_code` precedes the list term, the latest by that record's `created_at` when several qualify. Entries sort by that composite descending; ties break by the same evaluation record's `teaching_score` descending, then by that record's `created_at` ascending. A faculty with no qualifying prior evaluation sorts last, and among themselves such entries order by the faculty record's `created_at` ascending. The server then assigns `rank_position` from one upward in that order, rewriting every row in scope; no identifier-based tie-break is used anywhere. Creation also flips the faculty's `retention_status` from `PROVISIONAL` to `RETENTION_LISTED`, bumping the faculty `version`; when the faculty is already `RETENTION_LISTED` and the new entry names a later `list_term_code`, the dimension simply refreshes in place with no version change.

Reappointment is the dean's affirmative decision on a `LISTED` entry. It requires the faculty's `compliance_status` to be `COMPLIANT` — otherwise the decision is refused with `ERR_COMPLIANCE_INCOMPLETE` — and it carries the OCC token `expected_faculty_version`, refused with `ERR_STALE_FACULTY_VERSION` when the token no longer matches per Section 2.7. A successful reappointment moves the entry from `LISTED` to `REAPPOINTED` and bumps both the entry's `version` and the faculty record's `version`, because the decision touches the faculty row.

Non-reappointment is the heavier decision. Marking an entry non-reappointed — allowed while that entry belongs to the addressed faculty and sits in `LISTED`, and guarded by the same `expected_faculty_version` OCC token — moves the entry to `NON_REAPPOINTED` and cascades across the faculty record: the faculty's `retention_status` becomes `NON_REAPPOINTED`, every `ISSUED` contract of that faculty whose section's term starts after the entry's `list_term_code` term starts moves to `VOIDED` with `payable_cents` zeroed and any `OPEN`-period accruals reversed by clawbacks, and the faculty's load aggregates are recomputed. The entry's `version` and the faculty's `version` both increment. Thereafter the issuance guard of Section 3.5 refuses any new contract for that faculty with `ERR_CONTRACT_REFERENCE_INVALID`. Both terminal entry states — `REAPPOINTED` and `NON_REAPPOINTED` — are final.

## 4. Endpoint Definitions

All endpoints are mounted under `/adjunct-hr` and require the authentication headers of Section 2.1. Endpoints that create a new resource return HTTP 201; reads, modifications, and lifecycle actions return HTTP 200. Request payloads, computed fields, and side effects are defined in the narratives of Sections 2 and 3; the table below is intentionally a routing summary.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /adjunct-hr/_clock/set_current_utc | Set the server's logical clock; returns the new reading | HRAdmin |
| POST | /adjunct-hr/departments | Create a department | HRAdmin |
| GET | /adjunct-hr/departments/{id} | Fetch one department | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/departments | List departments | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| PATCH | /adjunct-hr/departments/{id} | Update mutable department fields (name, contact_hour_value, active); deactivation is reference-guarded | HRAdmin |
| POST | /adjunct-hr/terms | Create an academic term configuration | HRAdmin |
| GET | /adjunct-hr/terms/{id} | Fetch one term | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/terms | List terms | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| POST | /adjunct-hr/terms/{id}/open | Advance a term from SCHEDULED to OPEN, signalling issuance may begin | HRAdmin |
| POST | /adjunct-hr/terms/{id}/rollover | Run the term rollover checkpoint: complete finished sections, lapse idle faculty, set ROLLED_OVER | HRAdmin |
| POST | /adjunct-hr/rate-schedules | Create a rate schedule in DRAFT | HRAdmin |
| GET | /adjunct-hr/rate-schedules/{id} | Fetch one rate schedule | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/rate-schedules | List rate schedules | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/rate-schedules/{id}/publish | Publish a schedule (overlap-guarded); stamps published_version | HRAdmin |
| POST | /adjunct-hr/rate-schedules/{id}/retire | Retire a PUBLISHED schedule not referenced by ISSUED/ACTIVE contracts | HRAdmin |
| POST | /adjunct-hr/postings | Create a pool posting in DRAFT | DepartmentChair |
| GET | /adjunct-hr/postings/{id} | Fetch one posting | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/postings | List postings | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/postings/{id}/publish | Move a posting from DRAFT to OPEN | DepartmentChair |
| POST | /adjunct-hr/postings/{id}/suspend | Move a posting from OPEN to SUSPENDED | DepartmentChair |
| POST | /adjunct-hr/postings/{id}/resume | Move a posting from SUSPENDED back to OPEN | DepartmentChair |
| POST | /adjunct-hr/postings/{id}/close | Close an OPEN or SUSPENDED posting; expires SUBMITTED applications | DepartmentChair |
| POST | /adjunct-hr/postings/{id}/archive | Archive a CLOSED posting; guarded by in-flight applications | DepartmentChair |
| GET | /adjunct-hr/postings/{id}/applications | List applications filed against this posting | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/applications | File an application into an OPEN posting | HRReviewer |
| GET | /adjunct-hr/applications/{id} | Fetch one application | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/applications | List applications | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/applications/{id}/start-review | Move an application from SUBMITTED to UNDER_REVIEW | HRReviewer |
| POST | /adjunct-hr/applications/{id}/return-for-revision | Return an UNDER_REVIEW application for revision (bounded revision loop) | HRReviewer |
| POST | /adjunct-hr/applications/{id}/resubmit | Move a RETURNED_FOR_REVISION application back to UNDER_REVIEW | HRReviewer |
| POST | /adjunct-hr/applications/{id}/approve | Approve an UNDER_REVIEW application; creates the faculty record; segregation-of-duties guarded | HRReviewer |
| POST | /adjunct-hr/applications/{id}/reject | Move an UNDER_REVIEW application to REJECTED | HRReviewer |
| POST | /adjunct-hr/applications/{id}/withdraw | Withdraw a SUBMITTED or UNDER_REVIEW application | HRReviewer |
| GET | /adjunct-hr/applications/{id}/credentials | List credential verifications for one application | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/credentials | Register a credential evidence record in PENDING | HRReviewer |
| GET | /adjunct-hr/credentials/{id} | Fetch one credential record | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/credentials | List credential records | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/credentials/{id}/verify | Move a credential from PENDING to VERIFIED; stamps the deciding reviewer | HRReviewer |
| POST | /adjunct-hr/credentials/{id}/reject | Move a credential from PENDING to REJECTED | HRReviewer |
| GET | /adjunct-hr/faculty/{id} | Fetch one faculty record including computed load and benefits flag | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/faculty | List faculty | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/faculty/{id}/load | Computed read of term load: actual variant by default, scheduled via the variant parameter | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| POST | /adjunct-hr/faculty/{id}/reinstate-compliance | Move a LAPSED faculty back to COMPLIANT (requires a verified background check) | HRReviewer |
| GET | /adjunct-hr/faculty/{id}/contracts | List contracts held by this faculty | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/faculty/{id}/evaluations | List evaluation records for this faculty | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/sections | Create a course section | DepartmentChair |
| GET | /adjunct-hr/sections/{id} | Fetch one section | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/sections | List sections | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| PATCH | /adjunct-hr/sections/{id} | Update enrollment (and only enrollment) on a SCHEDULED or RUNNING section | DepartmentChair |
| POST | /adjunct-hr/sections/{id}/cancel | Cancel a SCHEDULED or RUNNING section; cascades contract cancellations at the census-appropriate tier | DepartmentChair |
| POST | /adjunct-hr/sections/{id}/complete | Complete a RUNNING section after term end; cascades contract completion | DepartmentChair |
| GET | /adjunct-hr/sections/{id}/contracts | List contracts issued against this section | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| POST | /adjunct-hr/contracts | Issue a per-course contract (OCC-guarded on faculty version); computes load and gross pay, pins the schedule version | DepartmentChair |
| GET | /adjunct-hr/contracts/{id} | Fetch one contract | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| GET | /adjunct-hr/contracts | List contracts | HRAdmin, HRReviewer, DepartmentChair, Dean, PayrollOfficer |
| POST | /adjunct-hr/contracts/{id}/void | Void a never-activated ISSUED contract; zeroes payable and reverses OPEN-period accruals | HRAdmin |
| GET | /adjunct-hr/contracts/{id}/payroll-entries | List payroll entries posted for this contract | HRAdmin, PayrollOfficer |
| POST | /adjunct-hr/payroll-periods | Create a payroll period (closed-interval overlap with non-CLOSED periods rejected) | PayrollOfficer |
| GET | /adjunct-hr/payroll-periods/{id} | Fetch one payroll period | HRAdmin, PayrollOfficer, DepartmentChair, Dean |
| GET | /adjunct-hr/payroll-periods | List payroll periods | HRAdmin, PayrollOfficer, DepartmentChair, Dean |
| POST | /adjunct-hr/payroll-periods/{id}/lock | Move a payroll period from OPEN to LOCKED | PayrollOfficer |
| POST | /adjunct-hr/payroll-periods/{id}/close | Close a LOCKED period; posts accrual and cancellation entries; chronological close order enforced | PayrollOfficer |
| GET | /adjunct-hr/payroll-periods/{id}/payroll-entries | List payroll entries posted into this period | HRAdmin, PayrollOfficer |
| GET | /adjunct-hr/payroll-entries | List payroll entries with filters | HRAdmin, PayrollOfficer |
| GET | /adjunct-hr/payroll-entries/{id} | Fetch one payroll entry | HRAdmin, PayrollOfficer |
| POST | /adjunct-hr/evaluations | Record a term evaluation; computes the composite score | Dean |
| GET | /adjunct-hr/evaluations/{id} | Fetch one evaluation | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/evaluations | List evaluations | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/retention-entries | Add a faculty member to a department retention list; triggers a full re-rank of the list scope | Dean |
| GET | /adjunct-hr/retention-entries/{id} | Fetch one retention entry | HRAdmin, HRReviewer, DepartmentChair, Dean |
| GET | /adjunct-hr/retention-entries | List retention entries | HRAdmin, HRReviewer, DepartmentChair, Dean |
| POST | /adjunct-hr/retention-entries/{id}/reappoint | Reappoint from a LISTED entry (OCC-guarded; requires COMPLIANT) | Dean |
| POST | /adjunct-hr/retention-entries/{id}/mark-non-reappointed | Mark a LISTED entry non-reappointed (OCC-guarded); cascades faculty status and voids future ISSUED contracts | Dean |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions for each error are defined in the narratives of Sections 2 and 3, with the evaluation precedence of Section 2.8 governing which error surfaces when several conditions fail at once.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_POSTING_NOT_OPEN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CREDENTIALS_INCOMPLETE | 422 |
| ERR_COMPLIANCE_INCOMPLETE | 422 |
| ERR_DUPLICATE | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_SCHEDULE_OVERLAP | 409 |
| ERR_PAYROLL_PERIOD_OVERLAP | 409 |
| ERR_CANCELLATION_POLICY | 422 |
| ERR_CONTRACT_REFERENCE_INVALID | 422 |
| ERR_LOAD_CAP_EXCEEDED | 422 |
| ERR_PAYROLL_CLOSE_ORDER | 422 |
| ERR_STALE_FACULTY_VERSION | 412 |
| ERR_REFERENCE_IN_USE | 409 |
| ERR_REVISION_LIMIT | 422 |
