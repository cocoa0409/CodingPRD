# Similarity Detection Repository API — Product Requirements Document

## 1. Introduction

Academic integrity offices face a tension: instructors need fast, defensible similarity feedback on student work, while students retain rights over where their writing lives and how it is reused. A campus may be perfectly comfortable letting its papers be compared against an internet corpus and its own historical submissions, yet deeply uncomfortable shipping those papers into a shared cross-institution repository. A second institution, by contrast, may see repository participation as the whole point. The Similarity Detection Repository API exists to let both postures coexist on one platform, with data residency, repository participation, and consent handled as first-class, auditable state rather than as configuration footnotes.

This document describes a multi-tenant integrity service rooted at `/integrity`. An `Institution` registers; a Platform operator provisions an `LmsIntegration` that receives submissions from a learning management system; an `Instructor` configures assignments with exclusion settings (quotes, bibliography, small matches) and a repository option; a `Student` submits work, optionally superseding an earlier attempt. Processing a submission compares its text against internet, publication, and student-repository corpora and produces a `SimilarityReport` with both a raw and a filtered similarity score. An optional AI writing indicator produces a point estimate and a deliberately more conservative bound, because institutional policy guidance treats the conservative bound as the only actionable number. Retention policies purge submissions across half-open time windows; consent withdrawal and repository opt-out quarantine stored deposits; grade entries remain provisional until the similarity report is finalized and revert to provisional whenever a report is invalidated.

The API is built around a logical clock (never wall-clock time) so that due-date auto-close, retention expiry, and timestamped consent records are deterministic and testable. Optimistic concurrency control guards the three writes that are most dangerous to apply blindly: assignment settings edits, consent records, and institutional policy changes. Cascades — suspension closing open assignments, retraction staling reports, supersession withdrawing deposits, finalization releasing grades — are spelled out in full so that an implementer reading only this document can reproduce the exact behavior of every endpoint.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifies the acting user and `X-User-Role` names the role that user is acting in. If either header is missing, or the supplied role is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the endpoint, or an ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly four roles, spelled exactly as follows:

- `PlatformAdmin` — a cross-tenant operator. This role alone may create institutions, update institutional policy, drive the test-injection endpoint, and set the logical clock. It shares all read endpoints and most administrative writes with other roles.
- `InstitutionalAdmin` — a tenant-scoped administrator for one institution. Manages LMS integrations, instructors, students, sources, deposits, and retention policies within its own institution, and may record consent on a student's behalf.
- `Instructor` — a faculty member. Creates and edits own assignments, runs the comparison pipeline, interprets and finalizes similarity reports, and records grade entries.
- `Student` — the author of submissions. Submits and resubmits own work, records own consent, and reads own reports only once the assignment has released them.

Identity semantics differ across roles and govern how `X-User-ID` is interpreted. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an `Instructor` (notably `Assignment.instructor_id`) compare that foreign-key field to `X-User-ID`, so an instructor may only write against assignments whose `instructor_id` equals their own `X-User-ID`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; the same ownership rule applies, so intake requires the payload's `student_id` to equal the caller's `X-User-ID`, consent writes must target the caller's own student record, and a student may read only their own submissions and only those reports whose assignment has released visibility. When `X-User-Role` is `PlatformAdmin` or `InstitutionalAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and it is recorded only for audit purposes.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is drawn from the host wall clock, not the logical clock of §2.4 — it is the sole timestamp the server writes that is not logical-clock-sourced.
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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0; a negative or non-integer `offset` (like an out-of-range or non-integer `limit`) is rejected with `ERR_VALIDATION` (HTTP 400). Responses are sorted by `created_at` ascending unless a resource-specific rule says otherwise; ties on `created_at` are left in creation (insertion) order via a stable sort. Every list response populates `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the full unpaginated count and `has_more` reports whether further results exist past the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Unless otherwise stated, entities also carry `updated_at` (same format, refreshed on every mutation) and `version` (an integer starting at 1 on creation and incremented by exactly 1 on every mutation). The sole exception is `MatchFragment`, which carries only `id` and `created_at` — `updated_at` and `version` are absent from it entirely.

All timestamps the server writes — `submitted_at`, `consent_recorded_at`, `stored_at`, `finalized_at`, lazy auto-close and auto-expiry decisions, and grace-window comparisons — are taken from a single logical clock, never from the host's wall clock. At server startup the logical clock reads `2026-09-01T00:00:00Z`. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (§4 lists its exact path). Time-based lazy transitions (assignment auto-close at `due_at`, retention-policy expiry at `retention_end`) are evaluated against this logical clock, at millisecond precision.

### 2.5. Nested Resource Resolution and Existence Checking

Resources form a hierarchy: an `Institution` owns `LmsIntegration`s, `Instructor`s, `Student`s, `SourceDocument`s, `DataRetentionPolicy`s, and `RepositoryDeposit`s; an `LmsIntegration` owns `Assignment`s; an `Assignment` owns `Submission`s; a `Submission` owns `MatchFragment`s, one `SimilarityReport`, one `AiWritingAssessment`, `RepositoryDeposit`s, and `GradeEntry`s. Whenever a URL contains nested path identifiers, every segment is resolved left-to-right: the outermost identifier is looked up first, and only after it exists is the next identifier resolved. The first identifier that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404); identifiers carried in the request body are validated after all path identifiers have resolved. Required-field presence, enum membership, and basic type well-formedness of the request body are then checked with `ERR_VALIDATION` (HTTP 400) before any state- or business-level rule runs.

### 2.6. Optimistic Concurrency Control

Three writes are OCC-guarded because applying them blindly would silently overwrite a newer observed state:

- Updating an assignment's settings (an `Instructor`-only write) requires `expected_assignment_version` in the payload, carrying the `Assignment.version` the client last observed. A mismatch with the assignment's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Note that the lazy due-date auto-close itself bumps the assignment's `version`, so a client holding a pre-auto-close view will be rejected.
- Recording or withdrawing consent requires `expected_student_version` matching the target `Student`'s current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating institutional policy (`repository_participation`, residency, or the detection flag) requires `expected_institution_version` matching the `Institution`'s current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here take no version field at all. The OCC stale-version check is evaluated last in the validation order — after every state and business rule below — so a request that fails both a business rule and the version check surfaces the business rule's error.

When several checks could reject the same request, they are evaluated in this fixed order: first authentication (headers present, role known), then authorization (role permitted and ownership), then resource existence (path identifiers left-to-right, then body identifiers), then request-body well-formedness, then state preconditions of the target resources, then business-safety rules (consent, residency), then business constraints (content, thresholds, quotas), then referential rules (supersede targets, report prerequisites), then temporal rules (retention windows), and finally the OCC stale-version check. Within §3, each workflow names the checks that apply to it in their relative order.

### 2.7. Precision, Rounding, and Weighting Constants

All similarity and AI-confidence scores are integers in basis points, ranging from 0 to 10000 inclusive, and every conversion from a fractional intermediate to basis points rounds half up. Fragment weighting uses four category multipliers: a `DIRECT_QUOTE` fragment is weighted at its full matched word count (multiplier 1.0), a `PARAPHRASE` at eight tenths (0.8), a `BIBLIOGRAPHY_ENTRY` at its full count (1.0), and a `BOILERPLATE` fragment at half (0.5). Critically, weighting rounds per fragment before any summation: each fragment's `weighted_words` is the half-up-rounded integer of its `matched_word_count` times its category multiplier, computed at injection time, and score aggregation sums those integers. Summing raw matched-word counts first and rounding once at the end is a different, forbidden computation — three one-word `PARAPHRASE` fragments contribute 3 weighted words under per-fragment rounding (each rounds to 1), versus 2 under sum-then-round. The AI confidence blend weights `ai_burstiness` at 0.5, `ai_perplexity` at 0.3, and `ai_stylometry` at 0.2.

### 2.8. Repository Participation, Residency, and Consent as Cross-Cutting Policy

Three institution-level policies cut across nearly every workflow, and are summarized here once. First, `repository_participation` takes one of `GLOBAL_SHARED`, `INSTITUTION_ONLY`, or `OPT_OUT` and determines both the `scope` of new deposits (`GLOBAL_SHARED` only when participation is `GLOBAL_SHARED`, otherwise `INSTITUTION_ONLY`) and their initial `deposit_state` (`QUARANTINED` under `OPT_OUT`, otherwise `STORED`); changing participation to `OPT_OUT` quarantines the institution's stored deposits, and reversing that change restores exactly those deposits. Second, `residency_region` (`EU`, `US`, or `APAC`) constrains student intake when `data_residency_locked` is true, constrains retention-policy creation, and becomes immutable once locked. Third, cross-institution comparison is off unless both sides opt in: a `STUDENT_REPOSITORY` source is visible to another institution's submissions only when the deposit behind it is `STORED` with `GLOBAL_SHARED` scope and both institutions have `cross_institution_comparison_enabled` true. A student's `consent_status` (`NOT_GIVEN`, `GRANTED`, `WITHDRAWN`) gates intake according to the integration's `consent_enforcement` mode and, on withdrawal, quarantines that student's stored deposits.

### 2.9. Cascading Invalidation: Retraction, Supersession, and Staleness

Several state changes deliberately propagate across aggregate boundaries, and the direction of every cascade is fixed. Retracting a `SourceDocument` marks every `MatchFragment` referencing it as excluded, and every similarity report whose submission holds one of those fragments goes `STALE` — which in turn flips any `RELEASED` grade entries on those submissions back to `PROVISIONAL`. Changing any exclusion setting on an assignment likewise stales that assignment's reports (and releases revert). A student resubmitting flips the prior submission to `SUPERSEDED` and withdraws its stored deposit. Withdrawing a deposit (or quarantining it via consent withdrawal or participation opt-out) recomputes the institution's `comparable_submission_count`, and a full withdraw (explicit withdrawal per §3.10) additionally retracts the deposit's auto-created `STUDENT_REPOSITORY` source — pulling its fragments out of every other submission's report as a second-order cascade; supersession-driven withdrawal (§3.4) and purge-driven withdrawal (§3.9) do not retract the source. The net invariant: a grade is visible as `RELEASED` only while its report is `FINALIZED` and nothing the report depends on has been invalidated.

## 3. Business Logic & Workflows

### 3.1. Institution Onboarding and Integration Lifecycle

Onboarding begins when a `PlatformAdmin` creates an institution with a display `name` and a `residency_region` drawn from `EU`, `US`, or `APAC`. At creation the operator may also set the repository posture: `repository_participation` (defaulting to `INSTITUTION_ONLY` when omitted), `cross_institution_comparison_enabled` (default false), the `ai_detection_enabled` policy flag (default true), and `data_residency_locked` (default false). An institution starts with `comparable_submission_count` at zero; the count is maintained automatically thereafter as deposits are created, quarantined, restored, and withdrawn. Later institutional policy edits are the exclusive province of `PlatformAdmin`, are OCC-guarded (see §2.6), are partial — any of `repository_participation`, `residency_region`, `cross_institution_comparison_enabled`, or `ai_detection_enabled` may be omitted from the patch body, in which case it is left unchanged; `data_residency_locked` is never mutable via the patch — and carry the live consequences described in §2.8: flipping `repository_participation` to `OPT_OUT` quarantines every one of the institution's `STORED` deposits and recomputes `comparable_submission_count`, while restoring participation to `GLOBAL_SHARED` or `INSTITUTION_ONLY` returns exactly the deposits that participation-quarantine cascade had quarantined to `STORED` — deposits quarantined because a student withdrew consent remain `QUARANTINED` regardless. Once `data_residency_locked` is true, any edit attempting to change `residency_region` is rejected with `ERR_RESIDENCY_LOCKED` (HTTP 409).

Under an institution, integrations, instructors, and students are provisioned by a `PlatformAdmin` or `InstitutionalAdmin`. An `LmsIntegration` is created with a `provider` (one of `CANVAS`, `BLACKBOARD`, `MOODLE`, or `CUSTOM_API`) and an opaque `external_key`, and starts life with its lifecycle `status` in `PENDING`. Its `consent_enforcement` mode — `STRICT` unless the creator chooses `LENIENT` — controls the intake consent gate described in §3.4. Activation moves an integration from `PENDING` to `ACTIVE`, and the same activation also revives a `SUSPENDED` integration back to `ACTIVE`; invoking activation on an integration in any other state is rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409). Suspension is the dramatic direction: moving an integration from `ACTIVE` to `SUSPENDED` conditionally cascades downward, flipping every assignment of that integration whose `accepting_state` is `OPEN` to `CLOSED`; assignments already `CLOSED` are untouched, and invoking suspension on an integration that is not `ACTIVE` is rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409). Each activation and suspension increments the integration's `version`. Only an `ACTIVE` integration may receive new assignments — creating an assignment under a `PENDING` or `SUSPENDED` integration is rejected with `ERR_INTEGRATION_NOT_ACTIVE` (HTTP 409).

Instructors are created with an `email` and `full_name`. Students are created with an `external_lms_id` (their identifier inside the LMS), an `email`, a `full_name`, and a `home_region` from the same `EU`/`US`/`APAC` enumeration. A freshly created student has `consent_status` `NOT_GIVEN` and a null `consent_recorded_at`.

### 3.2. Student Consent

Consent is a small state machine with outsized downstream effects. A student (or an `InstitutionalAdmin` acting on the student's record) records consent by submitting a `consent_action` of `GRANT` or `WITHDRAW` together with the OCC field `expected_student_version`. From `NOT_GIVEN`, a `GRANT` moves the student to `GRANTED`; from `WITHDRAWN`, a `GRANT` likewise returns the student to `GRANTED`. From `GRANTED`, a `WITHDRAW` moves the student to `WITHDRAWN` — and only from `GRANTED`: withdrawing when consent was never given, or granting when consent is already granted, does not match any transition and is rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409). Every successful consent write stamps `consent_recorded_at` with the current logical-clock instant and increments the student's `version` by one.

The withdrawal cascade is the reason consent is not merely cosmetic: when a student moves to `WITHDRAWN`, every `RepositoryDeposit` belonging to that student's submissions that is currently `STORED` flips to `QUARANTINED`, and each such quarantine recomputes the owning institution's `comparable_submission_count`. This is the intended serialization point with institutional policy — consent-quarantined deposits do not come back when participation settings later change, and they are re-stored only if the student grants consent again through the normal transition rules (a re-grant moves consent state, but quarantined deposits stay quarantined unless separately restored by the participation-reversal cascade, which they are not eligible for).

### 3.3. Assignment Configuration

An `Instructor` creates an assignment under a specific integration, supplying the delivering integration in the path and a payload containing `instructor_id`, `title`, and `due_at`. The `instructor_id` must equal the caller's `X-User-ID` — an instructor cannot create assignments on a colleague's behalf, and a mismatch is `ERR_FORBIDDEN`. Optional configuration at creation time includes `repository_option` (`STORE_AND_COMPARE` or `COMPARE_ONLY`, default `COMPARE_ONLY`), the three exclusion switches `exclude_quotes`, `exclude_bibliography`, and `exclude_small_matches` (each default false), `small_match_threshold_words` (default 8, and when provided must lie within 1 to 32 inclusive — anything outside that range is rejected with `ERR_THRESHOLD_OUT_OF_RANGE`, HTTP 422), `max_submissions_per_student` (default 3, and when provided must lie within 1 to 10 inclusive — anything outside that range is rejected with `ERR_VALIDATION`, HTTP 400), and `report_visibility` (which nonetheless starts at `HIDDEN`).

An assignment carries two parallel, independent state dimensions. The first, `accepting_state`, starts `OPEN` and ends `CLOSED`. There is no manual close: the transition fires lazily, whenever the assignment is read or a submission intake is attempted, if the logical clock has reached or passed `due_at`. The lazy evaluation itself mutates the record — it bumps the assignment's `version` and refreshes `updated_at` — which is why §2.6 warns that a client holding a pre-auto-close version will fail the OCC check on its next settings edit. The second dimension, `report_visibility`, starts `HIDDEN` and may be moved to `RELEASED` by the owning instructor via an OCC-guarded settings update; it evolves independently of whether the assignment still accepts submissions.

Editing an assignment after creation is an `Instructor`-only, OCC-guarded write; the patch is partial — any editable field omitted from the body is left unchanged — and `title` and `due_at` are never editable after creation. Editing is permitted even after the assignment has auto-closed: `accepting_state` does not gate the settings write. The write may touch `exclude_quotes`, `exclude_bibliography`, `exclude_small_matches`, `small_match_threshold_words` (same 1-to-32 range enforced, same `ERR_THRESHOLD_OUT_OF_RANGE` on violation), `report_visibility`, and `repository_option`. The exclusion settings are live configuration, not just intake-time decoration: changing any of the three exclusion switches or the threshold invalidates existing scoring, so every similarity report of the assignment's submissions that is currently `DRAFT` or `FINALIZED` flips to `STALE` (incrementing each report's `version`), and — as the compensation cascade — every grade entry on those submissions that had been `RELEASED` flips back to `PROVISIONAL` with its own `version` bump. The assignment's own `version` increments once for the edit itself. An instructor reading an assignment always observes it after lazy auto-close has been applied; a student may read an assignment too, since the read is open to all four roles.

### 3.4. Submission Intake and Resubmission

Intake is the busiest gate in the system. A `Student` submits to an assignment with a payload naming the parent assignment in the path (stored on the new record as `assignment_id`) and carrying `student_id`, `content_text`, and optionally `supersedes_submission_id` plus the three AI signal fields `ai_burstiness`, `ai_perplexity`, and `ai_stylometry`. The checks run in a fixed order, and the order matters because it determines which error surfaces when several conditions are violated at once:

1. Authentication, authorization, and ownership — the caller's role must be `Student` and the payload's `student_id` must equal the caller's `X-User-ID`, otherwise `ERR_UNAUTHENTICATED` or `ERR_FORBIDDEN`.
2. Existence — the assignment in the path, then the student in the body, each yielding `ERR_NOT_FOUND` when absent.
3. Body well-formedness — required fields present, enum and types sound, else `ERR_VALIDATION`.
4. The assignment's gate state — after lazy auto-close has been applied, intake against a `CLOSED` assignment is rejected with `ERR_ASSIGNMENT_CLOSED` (HTTP 409).
5. The consent gate — when the integration's `consent_enforcement` is `STRICT`, the student's `consent_status` must be `GRANTED`; when it is `LENIENT`, `NOT_GIVEN` is tolerated but `WITHDRAWN` is not. Failure is `ERR_CONSENT_MISSING` (HTTP 422).
6. Data residency — when the institution's `data_residency_locked` is true, the student's `home_region` must equal the institution's `residency_region`, else `ERR_RESIDENCY_VIOLATION` (HTTP 422).
7. Content — `content_text` must be non-empty and must tokenize to at least one whitespace-separated word; empty or all-whitespace content is `ERR_CONTENT_INVALID` (HTTP 422).
8. Quota — the count of this student's submissions on this assignment whose `pipeline_state` is anything other than `SUPERSEDED` must be below `max_submissions_per_student`, else `ERR_SUBMISSION_LIMIT_REACHED` (HTTP 422).
9. Supersede target — when `supersedes_submission_id` is present, it must reference a submission of the same student on the same assignment whose `pipeline_state` is `REPORT_READY` or `FAILED`; a missing target, another student's submission, a submission of a different assignment, or a target in any other state is `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422).

A fresh submission is stamped `submitted_at` from the logical clock, its `word_count` is computed as the count of whitespace-separated tokens in `content_text`, and it enters the pipeline at `RECEIVED` with `revision_number` 1. A resubmission — one carrying `supersedes_submission_id` — gets `revision_number` equal to the prior revision's number plus one, and the prior submission is transitioned to `SUPERSEDED` (its `version` increments) as part of the same intake. Supersession also cascades into the repository: any `RepositoryDeposit` of the superseded submission that is currently `STORED` flips to `WITHDRAWN`, and the institution's `comparable_submission_count` is recomputed. Unlike an explicit deposit withdrawal (§3.10), supersession does not retract the deposit's auto-created `STUDENT_REPOSITORY` source — the source stays `ACTIVE` and any fragments referencing it remain in place. Either way, the assignment's `submission_count` is recomputed after intake; that counter always equals the number of the assignment's submissions whose `pipeline_state` is not `SUPERSEDED`, so a resubmission leaves the count unchanged (one enters `RECEIVED`, one leaves to `SUPERSEDED`).

The three AI signals are upstream text-analysis measurements supplied per submission, each in the interval from 0 to 1 — a supplied value outside that interval (or not a number) is rejected with `ERR_VALIDATION` (HTTP 400). They are required for AI scoring later — §3.6 explains what happens when they are absent — but they are optional at intake and default to null. Intake returns the new submission with HTTP 201.

### 3.5. Corpora, Source Documents, and Fragment Injection

Comparison runs against three corpora, unified under `SourceDocument`: `INTERNET` pages, `PUBLICATION` articles, and `STUDENT_REPOSITORY` entries that mirror stored deposits. Platform operators and institutional administrators register `INTERNET` and `PUBLICATION` sources directly, supplying `source_type`, a `uri`, a residency `region`, and an optional `publication_date` (nullable, default null); the registering institution is recorded on the source as its `origin_institution_id`. Manually creating a source of type `STUDENT_REPOSITORY` is forbidden — such rows are auto-created by the processing pipeline, one per deposit — and an attempt to do so is rejected with `ERR_VALIDATION` (HTTP 400). A source starts `ACTIVE` and is comparable while `ACTIVE`; retracting it (available to `PlatformAdmin` and `InstitutionalAdmin`, requiring the source still be `ACTIVE`) moves it to `RETRACTED` and triggers the full invalidation cascade of §2.9: every fragment referencing the source is marked excluded, every report holding one of those fragments goes `STALE`, and released grades revert to provisional.

Deterministic fragments enter the system through a `PlatformAdmin`-only test-driving injection capability. The injector supplies `submission_id`, `source_document_id`, `matched_word_count` (at least 1), `match_category` (one of `DIRECT_QUOTE`, `PARAPHRASE`, `BIBLIOGRAPHY_ENTRY`, `BOILERPLATE`), and `offset_start` (at least 0, the word offset where the match begins inside the submission). Two state checks guard injection, and both must hold: the source must still be `ACTIVE` (a `RETRACTED` source yields `ERR_SOURCE_RETRACTED`, HTTP 409), and the comparison must respect residency and visibility boundaries — the injected fragment is rejected with `ERR_CROSS_REGION_COMPARISON` (HTTP 422) unless either the source's `region` equals the residency region of the submission's institution, or the source is a `STUDENT_REPOSITORY` source backed by a `STORED` deposit with `GLOBAL_SHARED` scope and both institutions involved have `cross_institution_comparison_enabled` set. The submission's own `pipeline_state` does not gate injection — fragments may be injected against a submission in any state. On success the fragment's `weighted_words` is computed immediately as the half-up-rounded product of `matched_word_count` and its category multiplier (§2.7) and the fragment is persisted with `excluded` false. Fragments are readable both from the submission side (the report's source breakdown) and from the source side (every fragment referencing a given source).

### 3.6. The Processing Pipeline: Comparison, AI Assessment, and Deposit

Processing is the heart of the product and is driven by an `Instructor` or `PlatformAdmin` against a single submission. The submission must be in `RECEIVED`, `FAILED`, or `REPORT_READY`; invoking the pipeline against a `SUPERSEDED` submission is rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409). Within the request, `PROCESSING` is transient: the submission advances `RECEIVED` → `PROCESSING` (bumping `version`) and the same call completes the transition to either `REPORT_READY` or `FAILED`. A retry from `FAILED` and a re-run from `REPORT_READY` both pass through `PROCESSING` the same way, each bumping `version` once more.

**Failure branch.** When the content tokenizes to zero words — reachable only for all-whitespace content, since intake rejects empty content outright — the pipeline completes in `FAILED` and creates nothing: no report, no assessment, no deposit.

**Success branch: similarity scoring.** When at least one word is present, the submission lands in `REPORT_READY` and a `SimilarityReport` is created (or regenerated) in `DRAFT` state. The report carries two scores in basis points, both derived from the submission's non-excluded fragments through the same three-step aggregation. Step one, deduplication: fragments whose word intervals — each interval starting at `offset_start` and extending `matched_word_count` words — overlap transitively are clustered together, and within each cluster only the fragment with the largest `weighted_words` survives, ties broken toward the earliest `created_at`; fragments marked `excluded` never participate. Step two, summation: the matched total is the sum of `weighted_words` over the surviving fragments. Step three, scoring: the score is ten thousand times the ratio of the matched total to the submission's `word_count`, capped so the ratio never exceeds one, and rounded half up to an integer in the 0-to-10000 range. The **raw** variant applies this to all non-excluded fragments and is stored as `raw_score_bps`. The **filtered** variant first removes fragments per the assignment's exclusion settings — `DIRECT_QUOTE` fragments when `exclude_quotes` is on, `BIBLIOGRAPHY_ENTRY` fragments when `exclude_bibliography` is on, and fragments whose `matched_word_count` falls strictly below `small_match_threshold_words` when `exclude_small_matches` is on (a fragment exactly at the threshold is kept) — then runs the identical aggregation, and is stored as `filtered_score_bps`. Because exclusion settings can change after a report is generated, the report freezes a copy of the four settings — `exclude_quotes`, `exclude_bibliography`, `exclude_small_matches`, and `small_match_threshold_words` — into its `exclusion_snapshot` at generation time, and a later regeneration refreshes that snapshot from the assignment's current values.

**Success branch: AI writing assessment.** The same processing call upserts the submission's `AiWritingAssessment`. The assessment's lifecycle is tracked in `assessment_state`: it is created in `PENDING`, and when the institution's `ai_detection_enabled` is false, or the submission's `word_count` is below 250, it lands in `SUPPRESSED` — a terminal state — with `ai_score_bps`, `confidence_band`, and `conservative_score_bps` all null. Otherwise, provided all three signal fields `ai_burstiness`, `ai_perplexity`, and `ai_stylometry` are present on the submission, the assessment moves to `COMPLETE` and is scored. The blend is a weighted sum: half of `ai_burstiness` plus three tenths of `ai_perplexity` plus one fifth of `ai_stylometry`; the **point estimate** `ai_score_bps` is ten thousand times that blend, rounded half up. The spread between the largest and smallest of the three signals determines `confidence_band`: a spread of at most 0.15 is `HIGH`, otherwise at most 0.30 is `MEDIUM`, otherwise `LOW`. The **conservative bound** `conservative_score_bps` subtracts a band-dependent margin from the point estimate — 500 basis points for `HIGH`, 1500 for `MEDIUM`, 2500 for `LOW` — floored at zero. Institutional policy guidance treats the conservative bound, not the point estimate, as the only actionable AI-writing indicator; neither score is evidence of misconduct by itself. If scoring is required but one or more signals are absent, the assessment cannot complete under the `COMPLETE` preconditions; it remains in `PENDING` with `ai_score_bps`, `confidence_band`, and `conservative_score_bps` all null, and the processing call itself still succeeds with the submission landing in `REPORT_READY`.

**Success branch: repository deposit.** When the assignment's `repository_option` is `STORE_AND_COMPARE`, processing also creates a `RepositoryDeposit` for the submission. The deposit's `institution_id` is taken from the submission's assignment's integration's owning institution. Its `scope` is `GLOBAL_SHARED` exactly when the institution's `repository_participation` is `GLOBAL_SHARED`, and `INSTITUTION_ONLY` otherwise. Its initial `deposit_state` is `QUARANTINED` when participation is `OPT_OUT` and `STORED` otherwise, and `stored_at` is stamped from the logical clock. Alongside the deposit, the pipeline auto-creates a `SourceDocument` of `source_type` `STUDENT_REPOSITORY` mirroring it — this is the only way such sources come into existence. Finally, the institution's `comparable_submission_count` is recomputed: it always equals the number of the institution's deposits that are simultaneously in `deposit_state` `STORED` and `scope` `GLOBAL_SHARED`. When `repository_option` is `COMPARE_ONLY`, no deposit and no auto source are created — the submission is compared against the corpora but never joins them. In all success cases the assignment's `submission_count` rollup is also recomputed.

A re-run from `REPORT_READY` (for instance after the report went `STALE`) regenerates everything: the report returns to `DRAFT` with a refreshed `exclusion_snapshot` and recomputed scores, the assessment is re-evaluated against the current signals and flags, and the deposit rules apply as above — under `STORE_AND_COMPARE` each re-run creates a fresh `RepositoryDeposit` (and its auto-created source); no prior deposit of the submission is retracted, withdrawn, or deduplicated as part of a re-run. Reports and assessments are one-to-one with their submission: reading a submission's similarity report or AI assessment returns an array of at most one element (empty when processing has not yet produced one).

### 3.7. Report Interpretation and Finalization

The report's lifecycle is tracked in its `report_state`, which starts at `DRAFT` on creation; a `DRAFT` report is an interpretation aid, not a verdict. Finalization is performed by the instructor who owns the submission's assignment (the assignment's `instructor_id` must equal the caller's `X-User-ID`), supplying an `instructor_interpretation` of `NOT_MISCONDUCT`, `POSSIBLE_MISCONDUCT`, or `NEEDS_REVIEW` — the platform's standing guidance is that similarity is not misconduct, and the interpretation field exists precisely so a human records the judgment the score cannot make. The report must be `DRAFT` and the interpretation must be present; finalizing a report in any other state is `ERR_INVALID_SUBMISSION_STATE` (HTTP 409), while finalizing a `STALE` report is specifically `ERR_REPORT_STALE` (HTTP 409) — a stale report must first be regenerated by re-running the pipeline. Successful finalization stamps `finalized_at` from the logical clock, bumps the report's `version`, and releases grades: every grade entry of the submission in `PROVISIONAL` flips to `RELEASED` with its own `version` increment.

Reports go `STALE` through two cascades, never directly: an exclusion-settings edit on the assignment (§3.3), or the retraction of a source referenced by one of the submission's fragments (§3.5), including the retraction that a deposit withdrawal triggers indirectly. Both `DRAFT` → `STALE` and `FINALIZED` → `STALE` increment the report's `version` and flip the submission's `RELEASED` grade entries back to `PROVISIONAL`. The only way out of `STALE` is a pipeline re-run on the owning submission (which must be `REPORT_READY`), returning the report to `DRAFT` with refreshed snapshot and scores.

Students see reports only after release: a `Student` may read a submission's report solely when the assignment's `report_visibility` is `RELEASED` and the submission is their own; otherwise the read is `ERR_FORBIDDEN`. Staff roles read reports regardless of visibility.

### 3.8. Grading Workflow

Grading deliberately trails the integrity pipeline. An `Instructor` records a grade entry against a submission with a numeric `score_points` (zero or greater) and an optional `feedback_text` (default empty string); unlike assignment edits and report finalization, grade-entry creation carries no assignment-ownership check — any `Instructor` may record a grade entry against any submission. Creation requires the submission to already have a similarity report in `DRAFT` or `FINALIZED`; grading against a submission with no report — or only a `STALE` one — is rejected with `ERR_GRADE_REQUIRES_REPORT` (HTTP 409). At creation the entry captures `pinned_report_version`, the report's current `version` at that moment, so later staleness can be correlated against the version the grader observed.

A grade entry starts with `grade_state` `PROVISIONAL` and is released only by report finalization (§3.7), never directly. The reverse path is equally automatic: whenever the underlying report goes `STALE`, every `RELEASED` entry on the submission returns to `PROVISIONAL`. Both directions increment the entry's `version`. The grade lifecycle therefore mirrors report trust — provisional while the evidence is draft or invalidated, released only while a finalized report stands behind it.

### 3.9. Data Retention and Purge

Retention is policy-driven, region-scoped, and deliberately conservative. A `PlatformAdmin` or `InstitutionalAdmin` creates a `DataRetentionPolicy` for an institution with a `region`, an `applies_to` class (`SUBMISSIONS`, `REPORTS`, or `BOTH`), and a half-open window running from `retention_start` (inclusive) to `retention_end` (exclusive). The window must be non-empty — `retention_start` strictly before `retention_end` — and the policy's `region` must equal the institution's `residency_region`; violations are `ERR_INVALID_RETENTION_WINDOW` (HTTP 422). Windows also may not collide: a new policy is rejected with `ERR_RETENTION_WINDOW_OVERLAP` (HTTP 409) if its half-open interval overlaps any existing `ACTIVE` policy of the same institution whose `applies_to` collides — `BOTH` collides with everything, including itself — where adjacency does not count as overlap (one window ending exactly where another begins is allowed). A policy's lifecycle is tracked in `policy_state`: it starts `ACTIVE` and transitions to `EXPIRED` lazily, on read or at purge time, once the logical clock reaches `retention_end`, incrementing its `version`.

Executing a purge against a policy first applies that lazy expiry — running a purge on an `EXPIRED` policy is `ERR_POLICY_EXPIRED` (HTTP 409). The candidate set is then the institution's submissions whose `submitted_at` falls inside the half-open window and whose `pipeline_state` is not `SUPERSEDED`, restricted to policies whose `applies_to` is `SUBMISSIONS` or `BOTH`, ordered by `submitted_at` ascending with `created_at` ascending as tie-break. Before anything is deleted, one aggregate safety check runs over the whole candidate set: if any candidate owns a deposit in `deposit_state` `STORED` whose `stored_at` lies inside the closed grace interval beginning seven days before `retention_start` and ending at `retention_end` — both endpoints included — the entire run is rejected with `ERR_PURGE_GRACE_CONFLICT` (HTTP 409) and nothing is purged. The boundary asymmetry is intentional: a submission timestamped exactly at `retention_end` is not a candidate (the window is half-open), but a deposit stored exactly at `retention_end` is a conflict (the grace interval is closed). When no conflict exists, the purge processes candidates in that ordering; for each candidate it first flips that submission's deposits in `STORED` or `QUARANTINED` to `WITHDRAWN` with the institution's `comparable_submission_count` recomputed — without retracting any auto-created `STUDENT_REPOSITORY` source (unlike an explicit deposit withdrawal), so no fragment-exclusion or report-staling cascade fires — and then deletes the submission together with its match fragments and similarity reports. The response reports `purged_count` and the list of `purged_submission_ids`.

### 3.10. Repository Deposit Administration

Beyond the automatic transitions, a `PlatformAdmin` or `InstitutionalAdmin` may explicitly withdraw any deposit in `STORED` or `QUARANTINED`; withdrawing a deposit already `WITHDRAWN` is rejected with `ERR_INVALID_SUBMISSION_STATE` (HTTP 409). Withdrawal moves the deposit to terminal `WITHDRAWN`, recomputes the institution's `comparable_submission_count`, increments the deposit's `version`, and — because the deposit's auto-created `STUDENT_REPOSITORY` source is retracted as part of withdrawal — excludes that source's fragments everywhere and stales every dependent report (with the grade-reversion compensation following behind). Deposits of a submission and deposits of an institution are both listable; the institution-level view is how an administrator audits what the tenant currently holds.

## 4. Endpoint Definitions

All endpoints are mounted under the API's top-level prefix. Endpoints that create a new resource respond with HTTP 201; all other successful operations — reads, updates, state transitions, and action invocations — respond with HTTP 200. Failures use the HTTP status declared per error in §5. Request payloads, OCC fields, side effects, and per-endpoint preconditions are specified in §2 and §3; the table below is a navigation index, not a complete contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /integrity/institutions | Create institution | PlatformAdmin |
| GET | /integrity/institutions/{id} | Read institution | PlatformAdmin, InstitutionalAdmin, Instructor, Student |
| PATCH | /integrity/institutions/{id} | Update repository participation / residency / flags (OCC-guarded) | PlatformAdmin |
| POST | /integrity/institutions/{id}/lms-integrations | Create LMS integration | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/institutions/{id}/lms-integrations | List integrations of an institution | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/lms-integrations/{id}/activate | Activate integration (from PENDING or SUSPENDED) | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/lms-integrations/{id}/suspend | Suspend integration; cascades OPEN assignments to CLOSED | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/institutions/{id}/instructors | Create instructor | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/institutions/{id}/instructors | List instructors of an institution | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/institutions/{id}/students | Create student | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/institutions/{id}/students | List students of an institution | PlatformAdmin, InstitutionalAdmin, Instructor |
| POST | /integrity/students/{id}/consents | Record or withdraw repository consent (OCC-guarded) | Student, InstitutionalAdmin |
| POST | /integrity/lms-integrations/{id}/assignments | Create assignment under an ACTIVE integration | Instructor |
| GET | /integrity/lms-integrations/{id}/assignments | List assignments of an integration | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/assignments/{id} | Read assignment (applies lazy due-date auto-close) | PlatformAdmin, InstitutionalAdmin, Instructor, Student |
| GET | /integrity/assignments | List assignments with optional `instructor_id` / `lms_integration_id` filters | PlatformAdmin, InstitutionalAdmin, Instructor |
| PATCH | /integrity/assignments/{id} | Update exclusion settings / report visibility (OCC-guarded) | Instructor |
| POST | /integrity/assignments/{id}/submissions | Submission intake; with `supersedes_submission_id` performs a resubmission | Student |
| GET | /integrity/assignments/{id}/submissions | List submissions of an assignment | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/submissions/{id} | Read submission; Student may read only own submissions | PlatformAdmin, InstitutionalAdmin, Instructor, Student |
| GET | /integrity/submissions | List submissions with optional `student_id` / `supersedes_submission_id` filters | PlatformAdmin, InstitutionalAdmin, Instructor |
| POST | /integrity/submissions/{id}/process | Run comparison pipeline: build/refresh report, AI assessment, repository deposit | Instructor, PlatformAdmin |
| POST | /integrity/institutions/{id}/source-documents | Register an INTERNET or PUBLICATION source | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/institutions/{id}/source-documents | List sources registered by an institution | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/source-documents/{id} | Read source document | PlatformAdmin, InstitutionalAdmin, Instructor |
| POST | /integrity/source-documents/{id}/retract | Retract a source; excludes its fragments and stales dependent reports | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/submissions/{id}/match-fragments | List match fragments of a submission (source breakdown) | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/source-documents/{id}/match-fragments | List fragments referencing a source | PlatformAdmin, InstitutionalAdmin, Instructor |
| POST | /integrity/_matches/inject | Test-driving endpoint: inject a deterministic MatchFragment | PlatformAdmin |
| GET | /integrity/submissions/{id}/similarity-reports | Read the submission's similarity report (array of 0..1); Student access gated on release | PlatformAdmin, InstitutionalAdmin, Instructor, Student |
| POST | /integrity/similarity-reports/{id}/finalize | Instructor finalizes report with interpretation; releases grade entries | Instructor |
| GET | /integrity/submissions/{id}/ai-writing-assessments | Read the submission's AI writing assessment (array of 0..1) | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/submissions/{id}/repository-deposits | List repository deposits of a submission | PlatformAdmin, InstitutionalAdmin, Instructor |
| GET | /integrity/institutions/{id}/repository-deposits | List repository deposits of an institution | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/repository-deposits/{id}/withdraw | Withdraw a deposit from the repository | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/institutions/{id}/retention-policies | Create an ACTIVE retention purge window | PlatformAdmin, InstitutionalAdmin |
| GET | /integrity/institutions/{id}/retention-policies | List retention policies of an institution (applies lazy expiry) | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/retention-policies/{id}/run-purge | Execute purge over the policy window | PlatformAdmin, InstitutionalAdmin |
| POST | /integrity/submissions/{id}/grade-entries | Create a grade entry pinned to the current report version | Instructor |
| GET | /integrity/submissions/{id}/grade-entries | List grade entries of a submission | PlatformAdmin, InstitutionalAdmin, Instructor |
| POST | /integrity/_clock/set_current_utc | Test-driving endpoint: set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below lists every machine-readable error identifier and its HTTP status. Trigger conditions for each error are specified in the narrative of §2 and §3 alongside the workflows that raise them.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INTEGRATION_NOT_ACTIVE | 409 |
| ERR_ASSIGNMENT_CLOSED | 409 |
| ERR_INVALID_SUBMISSION_STATE | 409 |
| ERR_REPORT_STALE | 409 |
| ERR_CONSENT_MISSING | 422 |
| ERR_RESIDENCY_VIOLATION | 422 |
| ERR_RESIDENCY_LOCKED | 409 |
| ERR_CROSS_REGION_COMPARISON | 422 |
| ERR_CONTENT_INVALID | 422 |
| ERR_THRESHOLD_OUT_OF_RANGE | 422 |
| ERR_SUBMISSION_LIMIT_REACHED | 422 |
| ERR_INVALID_SUPERSEDE_TARGET | 422 |
| ERR_GRADE_REQUIRES_REPORT | 409 |
| ERR_INVALID_RETENTION_WINDOW | 422 |
| ERR_RETENTION_WINDOW_OVERLAP | 409 |
| ERR_PURGE_GRACE_CONFLICT | 409 |
| ERR_POLICY_EXPIRED | 409 |
| ERR_SOURCE_RETRACTED | 409 |
| ERR_STALE_VERSION | 412 |

