# Health Plan Accreditation API — Product Requirements Document

## 1. Introduction

Accrediting a health plan against a national quality framework is a slow, evidence-heavy audit. A plan arrives with a specific product line (commercial, Medicare, Medicaid, or marketplace), a declared geography, and a review period of historical case work. The accrediting body assembles a standards edition whose elements span utilization management, credentialing, member rights and responsibilities, and quality improvement; the plan files evidence against those elements; surveyors test the plan's actual files against timeliness rules; scored elements and measure results feed a composite that decides whether the plan is accredited, accredited subject to corrective action, provisionally accredited, or denied. Where gaps surface, corrective action plans open and a focused resurvey follows. Between survey cycles, plans attest annually and their accreditation status is displayed publicly for a bounded window.

This document describes the Accreditation API, the system the accrediting body operates to run that entire lifecycle end-to-end: edition authoring and publication, plan and scope registration, application submission and evidence assembly, file review sampling with required-turnaround evaluation, survey scheduling across virtual and on-site sessions with per-surveyor overlap protection, surveyor question adjudication, element scoring with must-pass gating, decision publication with public-display rules, corrective action and resurvey, annual reporting, and the logical clock that anchors all date-sensitive determinations. The audience is the engineering team implementing the server.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two authentication headers: `X-User-ID`, which identifies the acting party, and `X-User-Role`, which names the operational capacity in which they act. Five roles exist. A `PlatformAdmin` administers reference data on behalf of the accrediting body — standards editions, standard elements, health plans, surveyors, and the logical clock. A `PlanCoordinator` is a health-plan accreditation coordinator who acts on behalf of exactly one health plan; when `X-User-Role` is `PlanCoordinator`, `X-User-ID` is the `id` of the acting `HealthPlan`, and ownership checks on any resource that references a `HealthPlan` compare the resource's foreign-key field (for example, the `health_plan_id` on an application or the `id` of the owning plan behind a scope) to `X-User-ID`. An `AccreditationOfficer` is an accrediting-body review officer who drives review, survey, scoring, decision, CAP verification and annual report review; when `X-User-Role` is `AccreditationOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. A `Surveyor` is a field surveyor who completes their own sessions and logs questions; when `X-User-Role` is `Surveyor`, `X-User-ID` is the `id` of the acting `Surveyor`, and ownership checks on a session-completion or question-logging request compare the session's `surveyor_id` to `X-User-ID`. A `PublicViewer` is an unauthenticated-equivalent role used for the public accreditation status display; `X-User-ID` for a `PublicViewer` is opaque and not tied to any entity.

A request missing either header, or carrying a role value outside the five declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among the roles authorized for the targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Where ownership scope applies, a `PlanCoordinator` whose `X-User-ID` does not equal the owning health plan's `id` of the targeted resource, or a `Surveyor` whose `X-User-ID` does not equal the target session's `surveyor_id` on session complete or question log, is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). The auth checks run before any existence, request-shape, or business checks; a request lacking a proper user context never reaches the deeper validation stack.

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

List endpoints accept two query parameters controlling pagination. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum accepted value of 0. A `limit` or `offset` that is not an integer, a `limit` outside the accepted range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order (equivalently, by creation sequence), unless otherwise specified. List responses carry the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` is refreshed on every mutation of the resource. Entity `created_at` and `updated_at` values are produced from the server's wall clock at the moment of creation or mutation; they do not read from the logical clock (§2.7), which governs only the date-sensitive determinations enumerated there. The `version` field is an integer that increments by exactly 1 on every mutation, including mutations driven by cascading side effects. Each `EvidenceItem` carries an `application_id` linking it back to the application it supports, a `standard_element_id` naming the element the evidence speaks to, and a `title`. Each `FileReviewSample` carries an `application_id` for its owning application. Each `FileReviewCase` carries a `file_review_sample_id` naming the sample it was filed under, along with its `case_reference`, `service_date`, `decision_date`, `resolution_date`, and `required_turnaround_days`. Each `Survey` and each `CorrectiveActionPlan` carries an `application_id` for its owning application. Each `SurveySession` carries a `survey_id` for the survey it sits under, and each `SurveyorQuestion` carries a `survey_session_id` for the session it was logged on. The `ElementScore` and `AccreditationOutcome` likewise carry an `application_id`; each `QualityMeasureResult` and `ConsumerSurveyScore` carries a `product_line_scope_id`; each `ProductLineScope` carries a `health_plan_id`; each `StandardElement` carries a `standards_edition_id`. All entities in this domain follow this convention, including derived-field recomputations: when a survey's minute totals are recomputed because a session changed, or an application's `total_awarded_points` is recomputed because a score was finalized, the affected entity's `updated_at` advances and its `version` increments.

### 2.5. Validation Order

Every request is checked against the following ordered list of concerns; the first failure encountered terminates evaluation and produces the response.

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the five declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Role authorization** — the role must be authorized for the targeted endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403).
3. **Ownership scope** — for plan-scoped `PlanCoordinator` operations the header `X-User-ID` must equal the owning `HealthPlan` id; for `Surveyor` session-completion and question-logging operations the header `X-User-ID` must equal the session's `surveyor_id` (`ERR_OWNERSHIP_MISMATCH`, HTTP 403).
4. **Path existence** — every path identifier must exist, validated left-to-right with the entity-specific 404 (`ERR_HEALTH_PLAN_NOT_FOUND`, `ERR_PRODUCT_LINE_SCOPE_NOT_FOUND`, `ERR_STANDARDS_EDITION_NOT_FOUND`, `ERR_STANDARD_ELEMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_FILE_REVIEW_SAMPLE_NOT_FOUND`, `ERR_FILE_REVIEW_CASE_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_SURVEY_SESSION_NOT_FOUND`, `ERR_SURVEYOR_NOT_FOUND`, `ERR_SURVEYOR_QUESTION_NOT_FOUND`, `ERR_ELEMENT_SCORE_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND`, `ERR_ACCREDITATION_OUTCOME_NOT_FOUND`, `ERR_ANNUAL_REPORT_NOT_FOUND`, `ERR_QUALITY_MEASURE_RESULT_NOT_FOUND`; HTTP 404).
5. **Request shape** — required fields present, types correct, enum values in the declared set, string lengths and numeric ranges within declared constraints (`ERR_INVALID_REQUEST`, HTTP 400). Request bodies must be JSON objects; a request body that is not valid JSON, or that is not an object, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Requests to an unknown route, or a method not supported on a known route, return the standard error envelope with `ERR_INVALID_REQUEST` (HTTP 404 and HTTP 405 respectively).
6. **Optimistic concurrency** — where the endpoint declares an `expected_application_version` input, the supplied value must equal the application's current `version` (`ERR_STALE_VERSION`, HTTP 412).
7. **State-machine preconditions** — the targeted resource's current status must permit the requested transition (`ERR_APPLICATION_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_EDITION_NOT_PUBLISHED`, `ERR_EDITION_NOT_SUPERSEDABLE`, `ERR_EDITION_HAS_NO_ELEMENTS`, `ERR_EVIDENCE_NOT_REVIEWABLE`, `ERR_EVIDENCE_NOT_RESUBMITTABLE`, `ERR_SAMPLE_NOT_OPEN`, `ERR_SAMPLE_NOT_SUBMITTED`, `ERR_SURVEY_INVALID_STATE`, `ERR_SESSION_INVALID_STATE`, `ERR_SCORE_NOT_PROVISIONAL`, `ERR_CAP_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_QUESTION_ALREADY_ADJUDICATED`; HTTP 409).
8. **Resurvey safety gates** — confirming a resurvey is blocked when any of the application's corrective action plans is awaiting officer review (`ERR_CAP_REVIEW_PENDING`, HTTP 422) or when any non-verified corrective action plan is past its due date (`ERR_CAP_OVERDUE`, HTTP 422).
9. **Cross-entity referential integrity** — a referenced scope must belong to the path's health plan (`ERR_SCOPE_PLAN_MISMATCH`, HTTP 422); a referenced standard element must belong to the application's standards edition (`ERR_ELEMENT_EDITION_MISMATCH`, HTTP 422).
10. **Temporal windows and overlaps** — review periods, survey windows, session placement inside a survey window, case service dates inside a review period, per-surveyor half-open session overlap, closed date-range survey overlap, and the one-on-site-session-per-date rule (`ERR_REVIEW_PERIOD_INVALID`, `ERR_SURVEY_WINDOW_INVALID`, `ERR_SESSION_OUTSIDE_SURVEY_WINDOW`, `ERR_CASE_OUTSIDE_REVIEW_PERIOD` at HTTP 422; `ERR_SURVEYOR_SESSION_OVERLAP`, `ERR_SURVEY_DATE_OVERLAP`, `ERR_ONSITE_SAME_DATE_CONFLICT` at HTTP 409).
11. **Uniqueness, cardinality, and aggregate completeness** — duplicate identifiers and broken aggregate preconditions (`ERR_PLAN_CODE_DUPLICATE`, `ERR_EDITION_YEAR_DUPLICATE`, `ERR_PRODUCT_LINE_DUPLICATE`, `ERR_ELEMENT_CODE_DUPLICATE`, `ERR_DUPLICATE_ACTIVE_APPLICATION`, `ERR_ELEMENT_SCORE_EXISTS`, `ERR_CAP_EXISTS`, `ERR_OUTCOME_ALREADY_EXISTS`, `ERR_MEASURE_RESULT_DUPLICATE`, `ERR_ANNUAL_REPORT_DUPLICATE`, `ERR_NO_SCHEDULED_SESSIONS`, `ERR_SESSIONS_NOT_FINISHED`, `ERR_ACTIVE_APPLICATIONS_EXIST` at HTTP 409; `ERR_INVALID_TURNAROUND_DAYS`, `ERR_EVIDENCE_COMPLETENESS_UNMET`, `ERR_ELEMENT_SCORES_INCOMPLETE`, `ERR_OPEN_GAP_QUESTIONS_REMAIN`, `ERR_SAMPLE_INCOMPLETE` at HTTP 422).
12. **Sample size floor** — a file review sample's `required_size` must be at least the edition's `min_file_sample_per_category` (`ERR_SAMPLE_SIZE_BELOW_MINIMUM`, HTTP 422).

### 2.6. Optimistic Concurrency Control

Three write operations require the caller to present the version of the `AccreditationApplication` they last observed, carried in the request body field `expected_application_version`. The three guarded operations are: submitting a draft application, adding an evidence item to an application, and creating a survey on an application. If the supplied value does not match the application's current `version` — because some other writer has advanced it since the client last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not take a version field.

For the evidence-item creation case, the rule is strictly necessary even though the operation does not itself change application status: adding an evidence item increments the application's `version` by 1 as a side effect, and the OCC check is what prevents a client with a superseded view of the application from layering evidence on top of a state it has not observed. The same reasoning applies to survey creation: creating a survey leaves the application's status untouched (the application only moves at confirm time) but still advances the application's `version`, and a stale `expected_application_version` is rejected. For application submission, the optimistic concurrency check is one of four preconditions and runs after existence and request-shape validation but before the state-machine and referential checks (see §2.5).

### 2.7. The Logical Clock

All date-sensitive determinations in the system — overdue evaluation for corrective action plans, lateness evaluation for annual reports, public-display window evaluation, and decision timestamps — read from a server-side logical clock, never from wall-clock time. Before any client call sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`, the server startup default; the server MUST NOT fall back to wall-clock time if no explicit set has occurred. A `PlatformAdmin` advances the clock by invoking the test-driving capability that sets the logical clock to a supplied `to_iso8601` instant. Advancing the clock triggers two recomputations across the dataset: `is_overdue` is recomputed on every corrective action plan not yet in `VERIFIED` status, and `is_publicly_displayed` is recomputed on every published outcome. The clock endpoint returns an object carrying `current_utc`, the logical clock's new value rendered as an ISO 8601 UTC timestamp.

### 2.8. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers, the server validates each identifier's existence in left-to-right order along the path, returning the entity-specific 404 error for the first segment that does not resolve. A request to list or create sessions under a survey that does not exist returns `ERR_SURVEY_NOT_FOUND` before any session-level check runs; a request to fetch a file review case under a sample that does not exist returns `ERR_FILE_REVIEW_SAMPLE_NOT_FOUND`. Once every path segment resolves, the request proceeds to request-shape, state, and business validation in the order given in §2.5.

### 2.9. Precision and Rounding

Quantitative values in the system observe three precision regimes. Rates derived from file review samples and CAP closure — `timeliness_rate` on a sample and `frozen_cap_closure_rate` on a resurvey — are stored to 4 decimal places using round-half-up. Monetary-style point values — `awarded_points`, `forfeited_points`, per-category component values inside the composite, `quality_component`, `consumer_component`, `measure_bonus`, and `composite_score` — are stored to 2 decimal places using round-half-up. Component rounding inside both the element-score formula and the composite-score formula is pinned: each component is rounded individually to its declared precision before components are combined, never after summation. Whole-day and whole-minute quantities (`days_to_basis`, `required_turnaround_days`, `duration_minutes`, `scheduled_minutes`, `completed_minutes`, `cancelled_minutes`, `active_minutes`) are integers with no rounding. The `percentile` on a quality measure result is an integer from 0 to 100; the `composite_score` on a consumer survey score accepts values from 0 to 100 inclusive with 2 decimal places — out-of-range values are rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and is stored as supplied without server-side re-rounding.

### 2.10. Common Enumerations

Several enumerations recur across the domain. A `ProductLineScope` declares a `product_line` of `COMMERCIAL`, `MEDICARE`, `MEDICAID`, or `MARKETPLACE`. A `StandardElement` declares a `category` of `UM` (utilization management), `CR` (credentialing), `MRR` (member rights and responsibilities), or `QI` (quality improvement). A `FileReviewSample` declares a `sample_type` of `DENIAL`, `APPEAL`, or `CREDENTIALING`, and a `timeliness_basis` of `DECISION_DATE` or `RESOLUTION_DATE`. A `Survey` declares a `survey_type` of `FULL` or `RESURVEY` and a `mode` of `VIRTUAL`, `ONSITE`, or `HYBRID`. A `Surveyor` declares a `credential_level` of `LEAD` or `STAFF`.

## 3. Business Logic & Workflows

### 3.1. Standards Editions and the Catalogue of Elements

A `PlatformAdmin` authors a standards cycle by creating a `StandardsEdition`, supplying an `edition_year` (unique across all editions; duplicates are rejected with `ERR_EDITION_YEAR_DUPLICATE`), an `effective_from` timestamp marking the start of the edition's effective window (inclusive), an `effective_until` timestamp marking the end of the window (inclusive and strictly after `effective_from`; violations are rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `min_file_sample_per_category` integer of at least 1 (the floor that every file review sample created under applications on this edition must respect; a value below 1 is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and a `timeliness_threshold` strictly greater than 0 and at most 1 (the pass threshold a sample's `timeliness_rate` must reach; out-of-range values are rejected with `ERR_INVALID_REQUEST`, HTTP 400). New editions begin in `DRAFT` status.

Elements join the edition while it remains `DRAFT`. Each `StandardElement` is added with an `element_code` unique within its edition (violations return `ERR_ELEMENT_CODE_DUPLICATE`), a `category`, a `max_points` integer of at least 1, an `is_must_pass` flag, and an `evidence_required_count` of 0 or more. Publishing moves the edition from `DRAFT` to `PUBLISHED` and is rejected with `ERR_EDITION_HAS_NO_ELEMENTS` when the edition still has zero elements; publishing from any state other than `DRAFT` is rejected with `ERR_EDITION_NOT_PUBLISHED`. Once `PUBLISHED`, an edition is immutable and becomes the target that applications submit against.

When a newer edition takes over, a `PlatformAdmin` supersedes the older one by naming a `superseded_by_edition_id`. The named edition must be different from the path edition (a request that points at itself is `ERR_INVALID_REQUEST`, HTTP 400), the path edition must be `PUBLISHED` (otherwise `ERR_EDITION_NOT_SUPERSEDABLE`), and the named replacement must exist and itself be a `PUBLISHED` edition — a name that is unknown or not `PUBLISHED` is rejected with `ERR_EDITION_NOT_PUBLISHED`. Superseding moves the path edition to `SUPERSEDED`, increments its `version`, and cascades: every `AccreditationApplication` whose `standards_edition_id` equals this edition and whose status is still `DRAFT` is withdrawn by the system (status becomes `WITHDRAWN`, the application's `version` increments), and the withdrawal in turn voids every `SUBMITTED` evidence item on those applications (status becomes `VOIDED`).

### 3.2. Health Plans, Scopes, and Reference Data

The accrediting body onboards a health plan by creating a `HealthPlan` with a `name` and a `plan_code`; the code must be unique across all health plans, with duplicates rejected as `ERR_PLAN_CODE_DUPLICATE`. New plans begin `ACTIVE`. A plan retires exactly once, when a `PlatformAdmin` invokes retire; the plan must currently be `ACTIVE` (retiring a `RETIRED` plan returns `ERR_PLAN_NOT_ACTIVE`), and no `AccreditationApplication` of the plan may be in a non-terminal status — that is, every application must be either `WITHDRAWN` or `CLOSED` — otherwise the retire is rejected with `ERR_ACTIVE_APPLICATIONS_EXIST`. Retire moves the plan to `RETIRED` and increments its `version`. Child creation against a `RETIRED` plan is likewise rejected with `ERR_PLAN_NOT_ACTIVE`.

Each plan defines the scopes under which it operates. A `PlanCoordinator` of the plan creates a `ProductLineScope` with a `product_line`, a non-empty `state_codes` array of 2-letter US state codes (each code must be exactly two uppercase ASCII letters `A`–`Z`; an empty array or any other code form is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and a `member_count` of at least 1 (a value below 1 is rejected with `ERR_INVALID_REQUEST`, HTTP 400). A plan may not register the same product line twice — a second scope for the same (plan, product line) pair is rejected with `ERR_PRODUCT_LINE_DUPLICATE`. The scope is the unit on which quality measures and consumer survey results accumulate, and the unit against which applications are submitted and outcomes are publicly displayed.

Surveyors are reference data owned by the accrediting body. A `PlatformAdmin` registers a `Surveyor` with a `name` and a `credential_level`. The `active` flag on a surveyor is always `true` and retained for roster display purposes; it never transitions.

### 3.3. Opening an Application and Filing Evidence

An application ties together the plan, a scope, an edition, and a lookback window. A `PlanCoordinator` creates an `AccreditationApplication` under their plan with a `product_line_scope_id`, a `standards_edition_id`, and the `review_period_start` and `review_period_end` datetimes that bound the file review lookback window (both bounds inclusive; `review_period_end` must be strictly after `review_period_start`, otherwise `ERR_REVIEW_PERIOD_INVALID`). The scope named must belong to the path's health plan; otherwise `ERR_SCOPE_PLAN_MISMATCH`. New applications begin in `DRAFT` with `total_awarded_points` and `total_forfeited_points` both 0.

Submission moves the application from `DRAFT` to `SUBMITTED`. Submitting is one of the three OCC-guarded writes (see §2.6) and enforces four preconditions, evaluated in this order: the application must be in `DRAFT` (otherwise `ERR_APPLICATION_INVALID_STATE`); the `expected_application_version` must match the application's current `version` (otherwise `ERR_STALE_VERSION`); the referenced standards edition must be `PUBLISHED` (otherwise `ERR_EDITION_NOT_PUBLISHED`); and no other application may already exist for the same (`product_line_scope_id`, `standards_edition_id`) pair in a non-terminal status, meaning a status other than `WITHDRAWN` or `CLOSED` (otherwise `ERR_DUPLICATE_ACTIVE_APPLICATION`). A successful submission increments the application's `version` by 1. On all three OCC-guarded endpoints (§2.6) the `expected_application_version` field is required in the request body — omitting it is `ERR_INVALID_REQUEST` (HTTP 400) — and when present it must be an integer (a non-integer value is likewise `ERR_INVALID_REQUEST`, HTTP 400).

Evidence assembly begins when an `AccreditationOfficer` begins evidence review, moving the application from `SUBMITTED` to `EVIDENCE_REVIEW` (wrong-state invocations return `ERR_APPLICATION_INVALID_STATE`). While the application is in `SUBMITTED` or `EVIDENCE_REVIEW`, the plan's coordinator files `EvidenceItem` records against elements of the application's edition, supplying a `standard_element_id` and a `title`, along with the OCC field `expected_application_version`. The named element must belong to the application's standards edition (otherwise `ERR_ELEMENT_EDITION_MISMATCH`). Each creation starts the item in `SUBMITTED` with `review_note` null and `revision_count` 0, and increments the application's `version` by 1 — which is exactly why the OCC check exists on this write (§2.6).

The `AccreditationOfficer` reviews each `SUBMITTED` item, either accepting or rejecting it and recording a `review_note`. On accept the note is optional in the payload; on reject it is required. Accept or reject on an item not in `SUBMITTED` is rejected with `ERR_EVIDENCE_NOT_REVIEWABLE`, and either action requires the owning application to be in `EVIDENCE_REVIEW` (otherwise `ERR_APPLICATION_INVALID_STATE`). A rejected item can be resubmitted by the plan's coordinator; resubmission requires the item to be `REJECTED` (otherwise `ERR_EVIDENCE_NOT_RESUBMITTABLE`) and the application to remain in `EVIDENCE_REVIEW`. Resubmitting moves the item back to `SUBMITTED`, increments `revision_count` by 1, resets `review_note` to null, and accepts an optional new `title`. When an application is withdrawn from `DRAFT` or `SUBMITTED`, every evidence item still in `SUBMITTED` is voided automatically by the system (status becomes `VOIDED`).

Advancement to survey scheduling is gated on evidence completeness. An `AccreditationOfficer` advances the application from `EVIDENCE_REVIEW` to `SURVEY_SCHEDULING` only when, for every standard element of the application's edition whose `evidence_required_count` is greater than 0, the application holds at least that many evidence items in `ACCEPTED` status; otherwise the request is rejected with `ERR_EVIDENCE_COMPLETENESS_UNMET` (HTTP 422). Successful advancement increments the application's `version` by 1.

### 3.4. File Review Samples and Timeliness Scoring

File review is how the survey tests the plan's actual case work. An `AccreditationOfficer` creates a `FileReviewSample` under an application while that application is in `EVIDENCE_REVIEW` or `SURVEY_SCHEDULING`, supplying a `sample_type`, a `required_size`, and a `timeliness_basis`. The `required_size` must be at least the owning edition's `min_file_sample_per_category`; a smaller value is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` (HTTP 422). The sample's `category` is derived from its type at creation: a `DENIAL` sample belongs to `UM`, an `APPEAL` sample belongs to `UM`, and a `CREDENTIALING` sample belongs to `CR`. New samples begin `OPEN` with `timely_case_count` 0, `timeliness_rate` null, and `must_pass_threshold_breached` false.

Cases join an `OPEN` sample through the plan's coordinator. Each `FileReviewCase` carries a `case_reference`, a `service_date`, a `decision_date`, a `resolution_date`, and a `required_turnaround_days` integer of at least 1 (a value below 1 is rejected with `ERR_INVALID_TURNAROUND_DAYS`, HTTP 422). The `service_date` must lie within the application's review period, with both endpoints inclusive; a case outside that window is rejected with `ERR_CASE_OUTSIDE_REVIEW_PERIOD` (HTTP 422), and this temporal-window check runs before the `required_turnaround_days` floor check (per the §2.5 ordering, which places temporal windows ahead of uniqueness, cardinality, and aggregate constraints). Case creation requires the sample to be `OPEN` and the owning application to be in `EVIDENCE_REVIEW` or `SURVEY_SCHEDULING`. Cases list in creation order, ascending.

Once the sample holds at least as many cases as its `required_size`, the plan's coordinator submits it; submission from any state other than `OPEN` is rejected with `ERR_SAMPLE_NOT_OPEN`, and submission while the case count is still short is rejected with `ERR_SAMPLE_INCOMPLETE` (HTTP 422). The sample moves to `SUBMITTED`.

Scoring is the officer's final act on the sample, and it requires the sample to be `SUBMITTED` (otherwise `ERR_SAMPLE_NOT_SUBMITTED`). At score time the system recomputes, for every case of the sample regardless of its current values and in case creation order for determinism, the case's `days_to_basis` and `is_timely`. The basis date is the case's `decision_date` when the sample's `timeliness_basis` is `DECISION_DATE`, or the case's `resolution_date` when the basis is `RESOLUTION_DATE`; `days_to_basis` is the whole calendar days between `service_date` and the basis date, taken as the floor of the elapsed time (when the basis date precedes the `service_date`, the floor is toward negative infinity, so `days_to_basis` may be negative — and such a case is timely, since a negative value is less than or equal to any `required_turnaround_days` of at least 1). A case is timely when `days_to_basis` is less than or equal to the case's `required_turnaround_days` — the boundary case where `days_to_basis` equals `required_turnaround_days` exactly counts as timely. The same case can therefore be timely under the decision-date basis but not timely under the resolution-date basis, when the decision was prompt but final resolution lagged. The sample's `timely_case_count` is the count of timely cases. The sample's `timeliness_rate` is the timely count divided by the total case count (every case counts, with no status filter), rounded to 4 decimal places using round-half-up. The sample's `must_pass_threshold_breached` becomes true when the `timeliness_rate` is strictly less than the edition's `timeliness_threshold` and the edition contains at least one element in the sample's category whose `is_must_pass` is true; a rate equal to or above the threshold does not breach. Scoring sets all three fields and moves the sample to `SCORED`.

### 3.5. Surveys and Sessions

A survey is the on-the-ground examination. An `AccreditationOfficer` creates a `Survey` under an application — one of the three OCC-guarded writes (§2.6) — supplying a `survey_type`, a `mode`, a `start_date` and `end_date` in `YYYY-MM-DD` form (both inclusive; `end_date` before `start_date` is rejected with `ERR_SURVEY_WINDOW_INVALID`), a `budgeted_surveyor_hours` of at least 1 (a value below 1 is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and `expected_application_version`. For a `FULL` survey the application must be in `SURVEY_SCHEDULING`; for a `RESURVEY` survey the application must be in `CORRECTIVE_ACTION`; the wrong application state returns `ERR_APPLICATION_INVALID_STATE`. Creating the survey increments the application's `version` by 1 and starts the survey in `PLANNED` with `frozen_cap_closure_rate` null and the four minute counters (`scheduled_minutes`, `completed_minutes`, `cancelled_minutes`, `active_minutes`) all at 0.

Sessions are the atomic units of surveyor time. An `AccreditationOfficer` schedules a `SurveySession` under a survey in `PLANNED` or `CONFIRMED` status, naming a `surveyor_id` (which must reference an existing `Surveyor`; an unknown id is rejected with `ERR_SURVEYOR_NOT_FOUND`, HTTP 404), a `session_date` in `YYYY-MM-DD` form, a `start_minute` between 0 and 1439 inclusive, an `end_minute` between 1 and 1440 inclusive and strictly greater than `start_minute` (violations of either minute bound are `ERR_INVALID_REQUEST`, HTTP 400), and an `is_onsite` flag. The `session_date` must fall within the survey's `[start_date, end_date]` window inclusive (otherwise `ERR_SESSION_OUTSIDE_SURVEY_WINDOW`). The new session's half-open `[start_minute, end_minute)` interval must not overlap any other `SCHEDULED` or `COMPLETED` session of the same surveyor on the same calendar date; two sessions where one ends exactly when the other begins are treated as adjacent, not overlapping (violations return `ERR_SURVEYOR_SESSION_OVERLAP`, HTTP 409). At most one on-site session per calendar date per survey: if `is_onsite` is true and another non-`CANCELLED` on-site session of the same survey already exists on that date, the request is rejected with `ERR_ONSITE_SAME_DATE_CONFLICT` (HTTP 409). A new session starts in `SCHEDULED` with `duration_minutes` computed as `end_minute` minus `start_minute`.

The survey's four minute counters reconcile on every session create, complete, cancel, or reschedule. `scheduled_minutes` is the sum of `duration_minutes` over sessions in `SCHEDULED`; `completed_minutes` is the same sum over `COMPLETED` sessions; `cancelled_minutes` is the same sum over `CANCELLED` sessions; and `active_minutes` is `scheduled_minutes` plus `completed_minutes`. Cancelling a session and scheduling a replacement of equal duration therefore leaves `active_minutes` unchanged — this is the conserved quantity of the reconciliation.

Rescheduling is a self-loop on a `SCHEDULED` session: the session remains `SCHEDULED`, but its `session_date`, `start_minute`, and `end_minute` are replaced (the request carries exactly these three fields; `is_onsite` is not reschedulable and the session's existing value is retained) and its `duration_minutes` recomputed. A session may be rescheduled any number of times while `SCHEDULED`. The rescheduling request must observe the same constraints as initial scheduling: the session must currently be `SCHEDULED` (otherwise `ERR_SESSION_INVALID_STATE`), the owning survey must be `PLANNED` or `CONFIRMED` (otherwise `ERR_SURVEY_INVALID_STATE`), the new `session_date` must lie within the survey window (otherwise `ERR_SESSION_OUTSIDE_SURVEY_WINDOW`), the new half-open interval must not overlap another `SCHEDULED` or `COMPLETED` session of the same surveyor on the same date with adjacency allowed (otherwise `ERR_SURVEYOR_SESSION_OVERLAP`), and if `is_onsite` is true no other non-`CANCELLED` on-site session of the same survey may exist on the new date (otherwise `ERR_ONSITE_SAME_DATE_CONFLICT`).

A session completes when its assigned `Surveyor` marks it complete; completion requires the session to be `SCHEDULED` (otherwise `ERR_SESSION_INVALID_STATE`), the owning survey to be `CONFIRMED` (otherwise `ERR_SURVEY_INVALID_STATE`), and the caller's `X-User-ID` to equal the session's `surveyor_id` (otherwise `ERR_OWNERSHIP_MISMATCH`). Cancelling a session is the officer's prerogative and requires only that the session is `SCHEDULED`. Cancelling a whole survey — allowed while the survey is `PLANNED` or `CONFIRMED` — also cancels every `SCHEDULED` session under it.

Confirming a survey is the point of no return and enforces eight checks: the survey must be `PLANNED` (otherwise `ERR_SURVEY_INVALID_STATE`); at least one of its sessions must be `SCHEDULED` (otherwise `ERR_NO_SCHEDULED_SESSIONS`); every `SCHEDULED` session must lie within the survey window (otherwise `ERR_SESSION_OUTSIDE_SURVEY_WINDOW`); for a `FULL` survey the application must be in `SURVEY_SCHEDULING` and for a `RESURVEY` survey the application must be in `CORRECTIVE_ACTION` (otherwise `ERR_APPLICATION_INVALID_STATE`); for a `RESURVEY` survey no corrective action plan of the application may be in `EVIDENCE_SUBMITTED` status awaiting officer review (otherwise `ERR_CAP_REVIEW_PENDING`, HTTP 422); for a `RESURVEY` survey no corrective action plan of the application may be overdue, meaning `is_overdue` is true — equivalently, its `due_date` falls before the logical clock's current date while its status is not `VERIFIED` (otherwise `ERR_CAP_OVERDUE`, HTTP 422); and no other survey of the same application in `PLANNED` or `CONFIRMED` status may have a closed `[start_date, end_date]` date range intersecting this survey's `[start_date, end_date]` range, with touching boundary dates counting as overlap (otherwise `ERR_SURVEY_DATE_OVERLAP`, HTTP 409).

Confirmation has type-specific side effects. For a `FULL` survey, the application moves from `SURVEY_SCHEDULING` to `SURVEY_IN_PROGRESS` and its `version` increments. For a `RESURVEY` survey, the application moves from `CORRECTIVE_ACTION` to `RESURVEY_IN_PROGRESS`, its `version` increments, and the survey freezes its `frozen_cap_closure_rate` at this instant as the count of the application's `VERIFIED` corrective action plans divided by the total corrective action plans of the application (or 0 when the application has no corrective action plans), rounded to 4 decimal places using round-half-up. At the same moment, the system snapshots, per element with an existing corrective action plan, the then-`FINAL` element score's `awarded_points` and `forfeited_points` as the freeze values used later by the resurvey recovery rule (should several `FINAL` scores exist for the element, the most recently created is snapshotted; an element whose corrective action plan has no `FINAL` score at freeze time contributes no snapshot and is later scored by the ordinary formula). CAP verifications completed after confirm do not change the frozen rate.

A confirmed survey completes when the officer marks it complete and every session under it is finished — meaning every session is in `COMPLETED` or `CANCELLED`; a survey with any session still `SCHEDULED` is rejected with `ERR_SESSIONS_NOT_FINISHED`. Completion requires the survey to be `CONFIRMED` (otherwise `ERR_SURVEY_INVALID_STATE`). For a `FULL` survey, completing moves the application from `SURVEY_IN_PROGRESS` to `SCORING` and increments its `version`. For a `RESURVEY` survey, completing moves the application from `RESURVEY_IN_PROGRESS` to `SCORING`, increments its `version`, and voids every `FINAL` element score of the application whose `standard_element_id` matches an existing corrective action plan's `standard_element_id` (those scores move `FINAL` to `VOIDED`).

### 3.6. Surveyor Questions and Gap Adjudication

During a confirmed survey, the assigned `Surveyor` logs questions against the elements they probe. Each `SurveyorQuestion` is logged on a session of a `CONFIRMED` survey with a `standard_element_id` (which must belong to the application's edition, otherwise `ERR_ELEMENT_EDITION_MISMATCH`), a `question_text`, and a `raises_gap` flag set true when the surveyor suspects an element-level gap. The caller's `X-User-ID` must equal the session's `surveyor_id` (otherwise `ERR_OWNERSHIP_MISMATCH`). New questions begin `LOGGED` with `gap_confirmed` null.

Adjudication is the officer's determination, per question, of whether the flagged gap is real. Adjudicating requires the question to be `LOGGED`; invoking it on an already-adjudicated question returns `ERR_QUESTION_ALREADY_ADJUDICATED`. The payload carries a `gap_confirmed` boolean; adjudication writes that value onto the question and moves it to `ADJUDICATED`. The adjudicated count of confirmed gaps feeds element scoring at finalization, and any unadjudicated gap-flagged question blocks finalization for the element it references (see §3.7).

### 3.7. Element Scores: Provisional, Final, and Resurvey Recovery

Element scoring begins with an `AccreditationOfficer` creating a provisional `ElementScore` for an element of the application's edition. Creation is allowed while the application is in `EVIDENCE_REVIEW`, `SURVEY_SCHEDULING`, `SURVEY_IN_PROGRESS`, `SCORING`, or `RESURVEY_IN_PROGRESS`; at most one non-`VOIDED` score may exist per (application, element) pair, and a duplicate is rejected with `ERR_ELEMENT_SCORE_EXISTS`. The element named must belong to the application's edition (otherwise `ERR_ELEMENT_EDITION_MISMATCH`). The new score carries a `scoring_basis` of `FILE_REVIEW` when the application has never completed a `RESURVEY` survey, or `RESURVEY` otherwise — "completed" means a `COMPLETED` resurvey exists, and when several do the most recently created one supplies the frozen values.

For a `FILE_REVIEW`-basis provisional score, the awarded points follow the element-score formula. The formula picks a category-matched sample rate when possible: among the application's `SCORED` file review samples whose `category` equals the element's `category`, the lowest `timeliness_rate` is selected as the sample rate (the minimum is deterministic and needs no tie-break), and `sample_rate_used` records the value applied; when the category has no `SCORED` sample, the sample rate is null and `sample_rate_used` is null. The evidence side counts the application's `ACCEPTED` evidence items for this element into `evidence_count_used`. The formula then combines three components. The file component contributes 60 percent of `max_points` in full when no `SCORED` sample exists for the category, or 60 percent of `max_points` multiplied by the selected sample rate when one does, rounded to 2 decimals round-half-up. The evidence component contributes 40 percent of `max_points` in full when the element's `evidence_required_count` is 0; otherwise it contributes 40 percent of `max_points` multiplied by the ratio of accepted evidence count to `evidence_required_count`, with that ratio capped at 1, rounded to 2 decimals round-half-up. The gap deduction subtracts 10 percent of `max_points` per confirmed gap, rounded to 2 decimals round-half-up. The provisional variant treats the confirmed gap count as 0 (survey gaps have not been adjudicated yet), so `gap_count_used` is 0 while the score is `PROVISIONAL`. The raw total is file component plus evidence component minus gap deduction; `awarded_points` is that raw value clamped from below at 0 and from above at `max_points`. `forfeited_points` is `max_points` minus `awarded_points`, so the two always sum to the element's `max_points`. When the element's `is_must_pass` is true and at least one of the application's `SCORED` samples in the element's category breached its threshold, the awarded points collapse to 0 regardless of the other components.

Finalization turns the provisional score into a `FINAL` one. Finalizing requires the score to be `PROVISIONAL` (otherwise `ERR_SCORE_NOT_PROVISIONAL`), the owning application to be in `SCORING` (otherwise `ERR_APPLICATION_INVALID_STATE`), and two further gates. First, if any file review sample exists for the element's category on this application, at least one such sample must be `SCORED`; otherwise the request is rejected with `ERR_SAMPLE_NOT_SCORED` (HTTP 409). Second, no surveyor question with `raises_gap` true and status `LOGGED` may reference this element within this application's surveys; an unadjudicated gap-flagged question blocks finalization with `ERR_OPEN_GAP_QUESTIONS_REMAIN` (HTTP 422). Finalization recomputes `awarded_points` using the final variant of the formula: the confirmed gap count now counts every question on this application's surveys whose `standard_element_id` equals the element, whose `raises_gap` is true, whose status is `ADJUDICATED`, and whose `gap_confirmed` is true; that count lands in `gap_count_used`, the deduction applies, and `forfeited_points` is recomputed to preserve the invariant. A score created with `scoring_basis` `RESURVEY` is exempt from the final-variant recompute: finalization re-applies the resurvey recovery rule against the frozen snapshot (recomputing `awarded_points` and `forfeited_points` from the freeze values), refreshes `sample_rate_used` and `evidence_count_used` from current data, and leaves `gap_count_used` unchanged from creation. Otherwise, whenever at least one gap is confirmed, the final awarded points are strictly lower than what the same file and evidence data would have produced provisionally. Finalization also recomputes the application's `total_awarded_points` (the sum of `awarded_points` over the application's `FINAL`, non-`VOIDED` element scores, or 0 when there are none) and `total_forfeited_points` (the analogous sum of `forfeited_points`).

A provisional score can instead be voided; voiding requires the score to be `PROVISIONAL` (otherwise `ERR_SCORE_NOT_PROVISIONAL`) and moves it to `VOIDED` without further effect.

When the application has completed a resurvey, scoring switches to the resurvey recovery rule for elements that have a corrective action plan and a frozen snapshot. The recovery amount is the survey's `frozen_cap_closure_rate` multiplied by the snapshot's forfeited-at-freeze value, rounded to 2 decimal places round-half-up. The provisional `awarded_points` is the snapshot's awarded-at-freeze value plus the recovery amount, clamped at the element's `max_points`. Elements without a corrective action plan use the ordinary element-score formula unchanged. The frozen closure rate and snapshots were captured at resurvey-confirm time (§3.5), and later verifications of corrective action plans do not move them.

### 3.8. Decision, Public Display, and Post-Decision Cascade

The decision is the accreditation outcome. An `AccreditationOfficer` decides an application in `SCORING`; the decision requires every element of the application's edition to have a `FINAL`, non-`VOIDED` element score (otherwise `ERR_ELEMENT_SCORES_INCOMPLETE`, HTTP 422), and every file review sample of the application to be `SCORED` (otherwise `ERR_SAMPLE_NOT_SCORED`, HTTP 409). Exactly one `AccreditationOutcome` exists per application: a second decision call on the same application is rejected with `ERR_OUTCOME_ALREADY_EXISTS`, and re-decision after a resurvey uses the revise operation instead.

Deciding computes three derived quantities and the outcome status. The composite score first groups the application's `FINAL`, non-`VOIDED` element scores by element category. For each of the four categories, the awarded-sum is the sum of `awarded_points` over the scores in that category and the max-sum is the sum of the corresponding elements' `max_points`; the category ratio is the awarded-sum divided by the max-sum, rounded to 4 decimal places round-half-up (max-sum is positive because the decide gate guarantees every edition element is scored). Each rounded ratio is then multiplied by its category weight — 0.30 for `UM`, 0.30 for `CR`, 0.20 for `MRR`, 0.20 for `QI` — without intermediate rounding, and the four weighted values sum to the base. The measure bonus is built from the application's product line scope for the measurement year matching the calendar year of the application's `review_period_end`: among the scope's `QualityMeasureResult` rows with `is_reportable` true and `measurement_year` equal to that year, the mean of `percentile` (0 when the set is empty, no rounding on the mean) is divided by 100 and multiplied by 2.0 to give the quality component, which is then rounded to 2 decimal places round-half-up; symmetrically, the mean of `composite_score` over the scope's `ConsumerSurveyScore` rows with `survey_year` equal to that year (0 when empty, unrounded mean) is divided by 100 and multiplied by 2.0 and rounded to 2 decimal places round-half-up to give the consumer component. `measure_bonus` is the exact sum of the two rounded components — the per-component rounding is pinned, and summing unrounded components and rounding once at the end is a forbidden reordering. The outcome's `composite_score` is the base multiplied by 100 plus `measure_bonus`, rounded to 2 decimal places round-half-up, with no cap. The outcome's `must_pass_failure_count` counts the application's `FINAL`, non-`VOIDED` element scores whose element has `is_must_pass` true and whose `awarded_points` is strictly less than half of the element's `max_points`; a score exactly at half of `max_points` is not a failure.

The outcome status is determined by a pinned evaluation order — the must-pass gate runs before the points thresholds. When the `composite_score` is below 60.00 or the `must_pass_failure_count` is at least 2, the status is `DENIED`. Otherwise, when the `must_pass_failure_count` is at least 1, the status is `ACCREDITED_WITH_CAP` — the gate-first rule means a high-scoring application with even one must-pass failure can never be `ACCREDITED`. Otherwise, when the `composite_score` is at least 90.00, the status is `ACCREDITED`. Otherwise, when the `composite_score` is at least 75.00, the status is `ACCREDITED_WITH_CAP`. Otherwise — `composite_score` at least 60.00 and below 75.00 with zero must-pass failures — the status is `PROVISIONAL`. The threshold boundaries are inclusive: a composite of exactly 90.00 qualifies for `ACCREDITED`, exactly 75.00 qualifies for `ACCREDITED_WITH_CAP`, and exactly 60.00 escapes `DENIED`.

Deciding also cascades. The application moves from `SCORING` to `DECIDED`. For every element of the edition whose `FINAL` awarded points are less than its `max_points` and which either is must-pass or was awarded 0 points, an `OPEN` corrective action plan is created automatically with `origin` `AUTO` and a `due_date` 90 days after the decision date — unless a non-`VOIDED` corrective action plan already exists for that (application, element) pair. Immediately after this auto-creation, the application is re-evaluated: if at least one corrective action plan of the application is in `OPEN` or `EVIDENCE_SUBMITTED` status, the application moves from `DECIDED` to `CORRECTIVE_ACTION`; otherwise it moves from `DECIDED` to `CLOSED`. Either way the application's `version` increments. The outcome records a `decision_sequence` starting at 1, a `published` flag starting false, a `public_display_until` starting null, an `is_publicly_displayed` flag starting false, and a `decided_at` set to the logical clock at decision time. Outcome responses render `is_publicly_displayed` recomputed live at read time (see the publishing rules below), even though the stored flag is refreshed on logical-clock advancement.

Re-decision after a resurvey uses the revise operation on the existing outcome. Revising requires the application to be back in `SCORING` (which the resurvey-completion cascade has just arranged), recomputes `composite_score`, `measure_bonus`, `must_pass_failure_count`, and `status` against the new score set, refreshes `decided_at` to the current logical clock, and increments `decision_sequence` by 1. The same post-decision cascade runs: `AUTO` corrective action plans are created for newly qualifying elements, and the application is re-evaluated into `CORRECTIVE_ACTION` or `CLOSED`.

Publishing an outcome is the accrediting body's public statement. Publishing sets `published` to true, computes `public_display_until` as the `decided_at` timestamp plus 36 months (same day-of-month and same time-of-day, with month-end dates clamping to the last day of the resulting month), and supersedes display for any other published outcome linked — via its application — to the same `product_line_scope_id`: each such previously published outcome's `is_publicly_displayed` becomes false. Publishing is idempotent: publishing an already-published outcome returns 200 and recomputes the same fields. Thereafter, `is_publicly_displayed` is recomputed on every read as the conjunction of three conditions: `published` is true, the logical clock is at or before `public_display_until`, and no other published outcome exists for the same product line scope with a later `decided_at` (or, on a tie in `decided_at`, with a higher `decision_sequence`). The public display view for a plan reports, per scope, the currently publicly displayed accreditation status. The view responds with an object carrying `plan_id`, `plan_name`, and a `scopes` array listing every product line scope of the plan in creation order; each scope entry carries `product_line_scope_id`, `product_line`, `accreditation_status` (the `status` of the scope's currently publicly displayed outcome, or null when no outcome of the scope is currently publicly displayed), and `outcome_id` (that outcome's id, or null likewise).

### 3.9. Corrective Action and Resurvey

A corrective action plan tracks remediation of one element-level gap. Beyond the `AUTO` corrective action plans the decision cascade creates, an `AccreditationOfficer` may create one manually while the application is in `DECIDED` or `CORRECTIVE_ACTION`, supplying a `standard_element_id` (which must belong to the application's edition, otherwise `ERR_ELEMENT_EDITION_MISMATCH`), a `gap_description`, and a `due_date` in `YYYY-MM-DD` form; manual creation sets `origin` to `MANUAL`. At most one corrective action plan per (application, element) exists at all — any existing corrective action plan for the pair blocks creation, regardless of status; duplicates are rejected with `ERR_CAP_EXISTS`. A new plan begins `OPEN`. Its `is_overdue` flag is recomputed whenever the logical clock advances: it is true when the plan's `due_date` is before the logical clock's current date and the plan's status is not `VERIFIED`.

The plan's coordinator submits remediation evidence, moving the corrective action plan from `OPEN` to `EVIDENCE_SUBMITTED` with an `evidence_summary` payload (the field is accepted when supplied but is not required and is not persisted on the corrective action plan); the plan must be `OPEN` (otherwise `ERR_CAP_INVALID_STATE`) and the application must be in `CORRECTIVE_ACTION` (otherwise `ERR_APPLICATION_INVALID_STATE`). The officer then verifies: a verification with `approved` true moves the plan to `VERIFIED`, its terminal state; a verification with `approved` false returns it to `OPEN` and the cycle may repeat — the plan can loop from `OPEN` to `EVIDENCE_SUBMITTED` and back to `OPEN` any number of times. Verification requires the plan to be `EVIDENCE_SUBMITTED` (otherwise `ERR_CAP_INVALID_STATE`).

While any corrective action plan is open or awaiting verification, the application sits in `CORRECTIVE_ACTION`. The resurvey path out of it is described in §3.5: creating a `RESURVEY` survey, confirming it (which freezes the closure rate), completing it (which voids the `FINAL` scores for elements with corrective action plans and returns the application to `SCORING`), re-scoring those elements under the resurvey recovery rule (§3.7), and revising the outcome (§3.8).

### 3.10. Annual Reporting Between Survey Cycles

Accreditation is not a one-time grant; the plan attests annually between survey cycles. A `PlanCoordinator` creates an `AnnualReport` under an application once that application is `CLOSED` or in `CORRECTIVE_ACTION` with a decided outcome whose status is `ACCREDITED` or `ACCREDITED_WITH_CAP`. Creation takes a `reporting_year` and an `attestation` text of at least 20 characters; at most one report may exist per (application, `reporting_year`), with duplicates rejected as `ERR_ANNUAL_REPORT_DUPLICATE`. The report's `due_date` is computed at creation as March 31 of the year after the `reporting_year`, at 23:59:59 UTC, and is stored and rendered as an ISO 8601 UTC timestamp (per §2.4's timestamp rendering). New reports begin in `DRAFT` with `is_late` false.

Submission moves the report out of `DRAFT`. When the logical clock at submission time is at or before the `due_date`, the report becomes `SUBMITTED` with `is_late` false; when the logical clock is strictly after the `due_date`, the report becomes `LATE` with `is_late` true — submitting exactly at the due instant is on time. Submission from any state other than `DRAFT` is rejected with `ERR_REPORT_INVALID_STATE`.

Officer review closes the loop. Reviewing with `accepted` true moves a `SUBMITTED` or `LATE` report to `ACCEPTED`, its terminal state; reviewing with `accepted` false moves it to `RETURNED`. Review requires the report to be `SUBMITTED` or `LATE` (otherwise `ERR_REPORT_INVALID_STATE`). Review leaves `is_late` untouched — a `LATE` report that is accepted keeps `is_late` true. A returned report can be reopened by the plan's coordinator: reopening requires the report to be `RETURNED` (otherwise `ERR_REPORT_INVALID_STATE`), moves it back to `DRAFT`, and resets `is_late` to false. A reopened report re-enters the submission cycle, and its lateness is re-evaluated at each submission against the same fixed `due_date` — a report reopened after its due date will be `LATE` again on its next submission.

### 3.11. Quality Measures and Consumer Survey Scores

The measure bonus in the accreditation composite draws on two scope-level inputs, both filed by the plan's coordinator. A `QualityMeasureResult` records a `measure_code`, a `measurement_year`, a `percentile` from 0 to 100 inclusive, and an `is_reportable` flag; at most one result may exist per (scope, `measure_code`, `measurement_year`) triple, and duplicates are rejected with `ERR_MEASURE_RESULT_DUPLICATE`. Only reportable results feed the composite. A `ConsumerSurveyScore` records a `survey_year`, a `composite_score` from 0 to 100 with 2 decimal places, and a `response_count` of at least 1 (a value below 1 is rejected with `ERR_INVALID_REQUEST`, HTTP 400). Consumer survey scores carry no uniqueness constraint: multiple rows for the same (scope, `survey_year`) pair are permitted and all rows of the matching year enter the mean. Both data sets are read at decision time for the year matching the calendar year of the application's `review_period_end`, as described in §3.8.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, reviews, adjudications, and publication — return `200 OK`. All endpoints are mounted under `/accreditation`. `GET /accreditation/applications/{applicationId}/outcome` is the one single-path exception to the object convention: it returns the standard list envelope (an array of length 0 or 1) rather than a bare object.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/accreditation/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/accreditation/standards-editions` | Create a standards edition (DRAFT) | PlatformAdmin |
| GET | `/accreditation/standards-editions` | List standards editions (paginated) | Any |
| GET | `/accreditation/standards-editions/{editionId}` | Get a standards edition | Any |
| POST | `/accreditation/standards-editions/{editionId}/publish` | Publish a DRAFT edition (requires at least one element) | PlatformAdmin |
| POST | `/accreditation/standards-editions/{editionId}/supersede` | Supersede a PUBLISHED edition by another PUBLISHED edition | PlatformAdmin |
| POST | `/accreditation/standards-editions/{editionId}/standard-elements` | Add a standard element to an edition | PlatformAdmin |
| GET | `/accreditation/standards-editions/{editionId}/standard-elements` | List elements of an edition | Any |
| GET | `/accreditation/standard-elements` | List standard elements with optional edition filter | Any |
| GET | `/accreditation/standard-elements/{elementId}` | Get a standard element | Any |
| POST | `/accreditation/health-plans` | Create a health plan (ACTIVE) | PlatformAdmin |
| GET | `/accreditation/health-plans` | List health plans (paginated) | Any |
| GET | `/accreditation/health-plans/{planId}` | Get a health plan | Any |
| POST | `/accreditation/health-plans/{planId}/retire` | Retire a plan; blocked while any application is non-terminal | PlatformAdmin |
| POST | `/accreditation/health-plans/{planId}/product-line-scopes` | Create a product line scope for a plan | PlanCoordinator |
| GET | `/accreditation/health-plans/{planId}/product-line-scopes` | List scopes of a plan | Any |
| GET | `/accreditation/product-line-scopes` | List product line scopes with optional plan filter | Any |
| GET | `/accreditation/product-line-scopes/{scopeId}` | Get a product line scope | Any |
| POST | `/accreditation/surveyors` | Register a surveyor | PlatformAdmin |
| GET | `/accreditation/surveyors` | List surveyors (paginated) | Any |
| GET | `/accreditation/surveyors/{surveyorId}` | Get a surveyor | Any |
| GET | `/accreditation/surveyors/{surveyorId}/sessions` | List all sessions assigned to a surveyor | Any |
| POST | `/accreditation/health-plans/{planId}/applications` | Create an accreditation application (DRAFT) | PlanCoordinator |
| GET | `/accreditation/health-plans/{planId}/applications` | List applications of a plan | Any |
| GET | `/accreditation/applications` | List applications with optional filters | Any |
| GET | `/accreditation/applications/{applicationId}` | Get an application | Any |
| POST | `/accreditation/applications/{applicationId}/submit` | Submit a DRAFT application (OCC-guarded) | PlanCoordinator |
| POST | `/accreditation/applications/{applicationId}/begin-evidence-review` | Move a SUBMITTED application into evidence review | AccreditationOfficer |
| POST | `/accreditation/applications/{applicationId}/advance-to-survey-scheduling` | Move to survey scheduling once evidence completeness holds | AccreditationOfficer |
| POST | `/accreditation/applications/{applicationId}/withdraw` | Withdraw a DRAFT or SUBMITTED application | PlanCoordinator |
| POST | `/accreditation/applications/{applicationId}/evidence-items` | Add an evidence item (OCC-guarded) | PlanCoordinator |
| GET | `/accreditation/applications/{applicationId}/evidence-items` | List evidence items of an application | Any |
| GET | `/accreditation/evidence-items` | List evidence items with optional element filter | Any |
| GET | `/accreditation/evidence-items/{evidenceItemId}` | Get an evidence item | Any |
| POST | `/accreditation/evidence-items/{evidenceItemId}/accept` | Accept a SUBMITTED evidence item | AccreditationOfficer |
| POST | `/accreditation/evidence-items/{evidenceItemId}/reject` | Reject a SUBMITTED evidence item | AccreditationOfficer |
| POST | `/accreditation/evidence-items/{evidenceItemId}/resubmit` | Resubmit a REJECTED evidence item | PlanCoordinator |
| POST | `/accreditation/applications/{applicationId}/file-review-samples` | Create a file review sample | AccreditationOfficer |
| GET | `/accreditation/applications/{applicationId}/file-review-samples` | List file review samples of an application | Any |
| GET | `/accreditation/file-review-samples` | List file review samples with optional application filter | Any |
| GET | `/accreditation/file-review-samples/{sampleId}` | Get a file review sample | Any |
| POST | `/accreditation/file-review-samples/{sampleId}/cases` | Add a case to an OPEN sample | PlanCoordinator |
| GET | `/accreditation/file-review-samples/{sampleId}/cases` | List cases of a sample (ordered by created_at ASC) | Any |
| GET | `/accreditation/file-review-cases` | List file review cases with optional sample filter | Any |
| GET | `/accreditation/file-review-cases/{caseId}` | Get a file review case | Any |
| POST | `/accreditation/file-review-samples/{sampleId}/submit` | Submit an OPEN sample whose case count meets required size | PlanCoordinator |
| POST | `/accreditation/file-review-samples/{sampleId}/score` | Score a SUBMITTED sample; computes timeliness fields | AccreditationOfficer |
| POST | `/accreditation/applications/{applicationId}/surveys` | Create a survey (PLANNED; OCC-guarded) | AccreditationOfficer |
| GET | `/accreditation/applications/{applicationId}/surveys` | List surveys of an application | Any |
| GET | `/accreditation/surveys` | List surveys with optional application filter | Any |
| GET | `/accreditation/surveys/{surveyId}` | Get a survey | Any |
| POST | `/accreditation/surveys/{surveyId}/confirm` | Confirm a PLANNED survey; freezes CAP closure rate for RESURVEY | AccreditationOfficer |
| POST | `/accreditation/surveys/{surveyId}/complete` | Complete a CONFIRMED survey once all sessions are finished | AccreditationOfficer |
| POST | `/accreditation/surveys/{surveyId}/cancel` | Cancel a PLANNED or CONFIRMED survey | AccreditationOfficer |
| POST | `/accreditation/surveys/{surveyId}/sessions` | Schedule a session on a PLANNED or CONFIRMED survey | AccreditationOfficer |
| GET | `/accreditation/surveys/{surveyId}/sessions` | List sessions of a survey | Any |
| GET | `/accreditation/survey-sessions` | List survey sessions with optional surveyor or survey filter | Any |
| GET | `/accreditation/survey-sessions/{sessionId}` | Get a survey session | Any |
| POST | `/accreditation/survey-sessions/{sessionId}/complete` | Surveyor completes their own session | Surveyor |
| POST | `/accreditation/survey-sessions/{sessionId}/cancel` | Cancel a SCHEDULED session | AccreditationOfficer |
| POST | `/accreditation/survey-sessions/{sessionId}/reschedule` | Reschedule a SCHEDULED session (self-loop) | AccreditationOfficer |
| POST | `/accreditation/survey-sessions/{sessionId}/questions` | Log a surveyor question on a session of a CONFIRMED survey | Surveyor |
| GET | `/accreditation/survey-sessions/{sessionId}/questions` | List questions of a session | Any |
| GET | `/accreditation/surveyor-questions` | List questions with optional element or session filter | Any |
| GET | `/accreditation/surveyor-questions/{questionId}` | Get a surveyor question | Any |
| POST | `/accreditation/surveyor-questions/{questionId}/adjudicate` | Adjudicate a LOGGED question | AccreditationOfficer |
| POST | `/accreditation/applications/{applicationId}/element-scores` | Create a PROVISIONAL element score | AccreditationOfficer |
| GET | `/accreditation/applications/{applicationId}/element-scores` | List element scores of an application | Any |
| GET | `/accreditation/element-scores` | List element scores with optional element filter | Any |
| GET | `/accreditation/element-scores/{scoreId}` | Get an element score | Any |
| POST | `/accreditation/element-scores/{scoreId}/finalize` | Finalize a PROVISIONAL score | AccreditationOfficer |
| POST | `/accreditation/element-scores/{scoreId}/void` | Void a PROVISIONAL score | AccreditationOfficer |
| POST | `/accreditation/product-line-scopes/{scopeId}/quality-measure-results` | Record a quality measure result for a scope | PlanCoordinator |
| GET | `/accreditation/product-line-scopes/{scopeId}/quality-measure-results` | List quality measure results of a scope | Any |
| GET | `/accreditation/quality-measure-results` | List quality measure results with optional scope filter | Any |
| GET | `/accreditation/quality-measure-results/{resultId}` | Get a quality measure result | Any |
| POST | `/accreditation/product-line-scopes/{scopeId}/consumer-survey-scores` | Record a consumer survey composite score for a scope | PlanCoordinator |
| GET | `/accreditation/product-line-scopes/{scopeId}/consumer-survey-scores` | List consumer survey scores of a scope | Any |
| GET | `/accreditation/consumer-survey-scores` | List consumer survey scores with optional scope filter | Any |
| GET | `/accreditation/consumer-survey-scores/{consumerSurveyScoreId}` | Get a consumer survey score | Any |
| POST | `/accreditation/applications/{applicationId}/corrective-action-plans` | Manually create a corrective action plan | AccreditationOfficer |
| GET | `/accreditation/applications/{applicationId}/corrective-action-plans` | List corrective action plans of an application | Any |
| GET | `/accreditation/corrective-action-plans` | List corrective action plans with optional element filter | Any |
| GET | `/accreditation/corrective-action-plans/{capId}` | Get a corrective action plan | Any |
| POST | `/accreditation/corrective-action-plans/{capId}/submit-evidence` | Plan submits CAP remediation evidence | PlanCoordinator |
| POST | `/accreditation/corrective-action-plans/{capId}/verify` | Officer verifies or rejects CAP evidence | AccreditationOfficer |
| POST | `/accreditation/applications/{applicationId}/outcome` | Decide the accreditation outcome | AccreditationOfficer |
| GET | `/accreditation/applications/{applicationId}/outcome` | Get the application's outcome (array of length 0 or 1) | Any |
| GET | `/accreditation/outcomes` | List outcomes with optional application filter | Any |
| GET | `/accreditation/outcomes/{outcomeId}` | Get an outcome | Any |
| POST | `/accreditation/outcomes/{outcomeId}/revise` | Re-decide after resurvey | AccreditationOfficer |
| POST | `/accreditation/outcomes/{outcomeId}/publish` | Publish the outcome for public display | AccreditationOfficer |
| GET | `/accreditation/public/plans/{planId}/accreditation-status` | Public display view of per-scope accreditation status | Any |
| POST | `/accreditation/applications/{applicationId}/annual-reports` | Create an annual report | PlanCoordinator |
| GET | `/accreditation/applications/{applicationId}/annual-reports` | List annual reports of an application | Any |
| GET | `/accreditation/annual-reports` | List annual reports with optional application filter | Any |
| GET | `/accreditation/annual-reports/{reportId}` | Get an annual report | Any |
| POST | `/accreditation/annual-reports/{reportId}/submit` | Submit a DRAFT report | PlanCoordinator |
| POST | `/accreditation/annual-reports/{reportId}/review` | Officer accepts or returns a SUBMITTED/LATE report | AccreditationOfficer |
| POST | `/accreditation/annual-reports/{reportId}/reopen` | Reopen a RETURNED report into DRAFT | PlanCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_HEALTH_PLAN_NOT_FOUND | 404 |
| ERR_PRODUCT_LINE_SCOPE_NOT_FOUND | 404 |
| ERR_STANDARDS_EDITION_NOT_FOUND | 404 |
| ERR_STANDARD_ELEMENT_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_EVIDENCE_ITEM_NOT_FOUND | 404 |
| ERR_FILE_REVIEW_SAMPLE_NOT_FOUND | 404 |
| ERR_FILE_REVIEW_CASE_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_SURVEY_SESSION_NOT_FOUND | 404 |
| ERR_SURVEYOR_NOT_FOUND | 404 |
| ERR_SURVEYOR_QUESTION_NOT_FOUND | 404 |
| ERR_ELEMENT_SCORE_NOT_FOUND | 404 |
| ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND | 404 |
| ERR_ACCREDITATION_OUTCOME_NOT_FOUND | 404 |
| ERR_ANNUAL_REPORT_NOT_FOUND | 404 |
| ERR_QUALITY_MEASURE_RESULT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_APPLICATION_INVALID_STATE | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_EDITION_NOT_PUBLISHED | 409 |
| ERR_EDITION_NOT_SUPERSEDABLE | 409 |
| ERR_EDITION_HAS_NO_ELEMENTS | 409 |
| ERR_EVIDENCE_NOT_REVIEWABLE | 409 |
| ERR_EVIDENCE_NOT_RESUBMITTABLE | 409 |
| ERR_SAMPLE_NOT_OPEN | 409 |
| ERR_SAMPLE_NOT_SUBMITTED | 409 |
| ERR_SAMPLE_NOT_SCORED | 409 |
| ERR_SURVEY_INVALID_STATE | 409 |
| ERR_SESSION_INVALID_STATE | 409 |
| ERR_SCORE_NOT_PROVISIONAL | 409 |
| ERR_CAP_INVALID_STATE | 409 |
| ERR_REPORT_INVALID_STATE | 409 |
| ERR_QUESTION_ALREADY_ADJUDICATED | 409 |
| ERR_CAP_REVIEW_PENDING | 422 |
| ERR_CAP_OVERDUE | 422 |
| ERR_SCOPE_PLAN_MISMATCH | 422 |
| ERR_ELEMENT_EDITION_MISMATCH | 422 |
| ERR_REVIEW_PERIOD_INVALID | 422 |
| ERR_SURVEY_WINDOW_INVALID | 422 |
| ERR_SESSION_OUTSIDE_SURVEY_WINDOW | 422 |
| ERR_CASE_OUTSIDE_REVIEW_PERIOD | 422 |
| ERR_SURVEYOR_SESSION_OVERLAP | 409 |
| ERR_SURVEY_DATE_OVERLAP | 409 |
| ERR_ONSITE_SAME_DATE_CONFLICT | 409 |
| ERR_PLAN_CODE_DUPLICATE | 409 |
| ERR_EDITION_YEAR_DUPLICATE | 409 |
| ERR_PRODUCT_LINE_DUPLICATE | 409 |
| ERR_ELEMENT_CODE_DUPLICATE | 409 |
| ERR_DUPLICATE_ACTIVE_APPLICATION | 409 |
| ERR_ELEMENT_SCORE_EXISTS | 409 |
| ERR_CAP_EXISTS | 409 |
| ERR_OUTCOME_ALREADY_EXISTS | 409 |
| ERR_MEASURE_RESULT_DUPLICATE | 409 |
| ERR_ANNUAL_REPORT_DUPLICATE | 409 |
| ERR_INVALID_TURNAROUND_DAYS | 422 |
| ERR_NO_SCHEDULED_SESSIONS | 409 |
| ERR_EVIDENCE_COMPLETENESS_UNMET | 422 |
| ERR_ELEMENT_SCORES_INCOMPLETE | 422 |
| ERR_OPEN_GAP_QUESTIONS_REMAIN | 422 |
| ERR_SESSIONS_NOT_FINISHED | 409 |
| ERR_SAMPLE_INCOMPLETE | 422 |
| ERR_ACTIVE_APPLICATIONS_EXIST | 409 |
| ERR_SAMPLE_SIZE_BELOW_MINIMUM | 422 |

A consumer survey score has no dedicated 404 error id; an unknown `ConsumerSurveyScore` id on its GET endpoint returns `ERR_ACCREDITATION_OUTCOME_NOT_FOUND` (HTTP 404).
