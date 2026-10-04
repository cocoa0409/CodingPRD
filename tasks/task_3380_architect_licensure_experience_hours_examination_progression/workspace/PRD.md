# Architect Licensure Experience Examination API — Product Requirements Document

## 1. Introduction

Architect licensure is earned at the intersection of three evidentiary tracks — education, supervised experience, and examination — and then defended through continuing education and good standing for the rest of a career. This service is the national council's system of record for that lifecycle. It registers licensure candidates, evaluates their education against accredited-degree requirements or a credit-based alternative path, collects experience reports across six practice areas with mandatory supervisor verification, administers the six-division examination under a rolling validity clock, layers jurisdiction-specific requirements (including supplemental examinations) on top of the national standard, and issues the national certificate on which state boards rely for reciprocal licensure. Certificates are living documents: they occupy twenty-four-month continuing-education periods, lapse when a period closes unrenewed, can be reinstated within a bounded window, and can be revoked outright when a disciplinary sanction lands.

Two commitments shape every endpoint in this document. First, time is a first-class input: the service runs on an explicit logical clock, and every deadline in the domain — credit tiering of experience hours, retake waiting periods, attempt windows, rolling examination validity, renewal and reinstatement windows — is evaluated against that clock and nothing else. Second, authority is deliberately fragmented so that no single actor can carry a file from registration to licensure alone: candidates report their own work but cannot verify it, supervisors verify experience but cannot score examinations, state boards authorize testing and decide transmittals but cannot resolve the disciplinary reports they file, and national council staff operate the clock, the review pipeline, and the certificate press. All resources are served under the `/licensure` mount.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string outside the declared role set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role must appear in the endpoint's authorized-role list and the ownership rules of §2.6 must hold; either failure is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `Anonymous` — the unauthenticated registrant; may only register a new candidate record.
- `Candidate` — a licensure candidate acting on their own record.
- `Supervisor` — a licensed architect verifying experience reports assigned to them.
- `BoardAdministrator` — state or jurisdiction board staff; grants examination authorizations, reports supplemental-exam results, decides transmittals, and files disciplinary reports.
- `NcarbAdministrator` — national council staff; operates the logical clock and the expiry sweep, administers the jurisdiction and supervisor registries, reviews education evaluations, reports examination scores, issues certificates, and resolves disciplinary reports.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting Candidate; ownership checks on any resource that references a candidate compare the resource's `candidate_id` field (or the candidate identifier in the request path) to `X-User-ID`. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting Supervisor; verification and return of an experience report compare the report's `supervisor_id` to `X-User-ID`. When `X-User-Role` is `Anonymous`, `BoardAdministrator`, or `NcarbAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — most notably as `filed_by_user_id` on a disciplinary report filed by a `BoardAdministrator` — but never compares it to any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100; the `offset` parameter defaults to 0. List responses are sorted by `created_at` ascending unless a more specific ordering is stated for that resource. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of matching records before pagination and `has_more` indicates whether further records exist beyond the returned window.

### 2.4. The Logical Clock and Calendar Arithmetic

Every date- and deadline-sensitive rule in this service reads a single logical clock; the server never falls back to wall-clock time. At server startup, before any administrative clock action, the logical clock reads exactly 2026-09-01T00:00:00Z. An `NcarbAdministrator` moves the clock through a test-driving capability that accepts a target instant in the `to_iso8601` field and answers with the new value in `current_utc`; setting the clock mutates no entity. A separate ops-run checkpoint capability, the expiry sweep, applies time-based transitions at the current logical date — passing examination divisions whose validity has run out become expired, and active certificates whose period has closed become lapsed — and answers with the counts of affected rows in `expired_divisions` and `lapsed_certificates`.

All deadline arithmetic in this document uses calendar-month and calendar-day addition on ISO calendar dates: adding sixty calendar months to a date yields the same day-of-month sixty months later. Every deadline comparison operates at day granularity — the time-of-day component never participates in a deadline decision. Each rule in §3 states explicitly whether its boundary day is included or excluded, and those inclusivity decisions are part of the contract.

### 2.5. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in this service carries an `id` minted by the server as a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp — both ISO 8601 UTC with three fractional digits — and an integer `version`. The `version` of a resource increments by one on every accepted mutation of that resource, including mutations caused by cascade side effects originating elsewhere; `updated_at` refreshes on the same occasions. Client-supplied `id`, `created_at`, or `version` values sent at registration time are ignored. When a request touches a nested path, path identifiers are resolved from left to right, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404).

Two write endpoints are guarded by optimistic concurrency control, and only these two. Updating a jurisdiction's requirement flags requires the request to carry `expected_jurisdiction_version` holding the caller's last-observed `version` of that jurisdiction; when the value does not match the jurisdiction's currently stored `version` — because another writer has modified the jurisdiction since the caller last read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), so the stale caller cannot silently discard the intervening change. Updating a supervisor's license data works identically with `expected_supervisor_version` against the supervisor's stored `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective endpoints, and a successful guarded update increments the stored `version` by one. No endpoint other than these two accepts a version field.

### 2.6. Validation Order and Error Precedence

When several checks could reject the same request, the first failure in a fixed evaluation order wins, and only that failure's error is returned. The tiers, evaluated in this order, are:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is one of the five declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and ownership.** The caller's role is in the endpoint's authorized-role list, and `Candidate` callers act only on their own resources — `X-User-ID` equals the candidate identifier in the path or the target resource's `candidate_id`; otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. **Existence and jurisdiction resolution.** Path parameters resolve to existing resources from left to right, and body references such as `supervisor_id`, `candidate_id`, and `new_supervisor_id` resolve to existing records; failures yield `ERR_NOT_FOUND` (HTTP 404). A `jurisdiction_code` or `home_jurisdiction_code` value that matches no registered jurisdiction's `code` is rejected at this same tier with `ERR_JURISDICTION_UNKNOWN` (HTTP 422).
4. **State legality.** The target resource's current state must permit the attempted transition; any trigger attempted from a state that does not list it is rejected with the generic `ERR_INVALID_STATE` (HTTP 409). Dedicated state rejections at this tier include `ERR_DIVISION_ALREADY_PASSED`, `ERR_DIVISION_ALREADY_SCHEDULED`, `ERR_CERTIFICATE_EXISTS`, `ERR_EVALUATION_ALREADY_OPEN`, and `ERR_CERTIFICATE_NOT_ACTIVE` (all HTTP 409), as well as the optimistic-concurrency rejection `ERR_STALE_VERSION` (HTTP 412).
5. **Business safety.** Disciplinary and eligibility gates: `ERR_OPEN_DISCIPLINARY_BLOCK` (HTTP 409), `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and `ERR_ELIGIBILITY_NOT_MET` (HTTP 409).
6. **Business referential integrity.** Assignment-level checks: `ERR_SUPERVISOR_NOT_ACTIVE` (HTTP 422), `ERR_SUPERVISOR_MISMATCH` (HTTP 403), and `ERR_SUPPLEMENTAL_NOT_REQUIRED` (HTTP 422).
7. **Temporal rules.** Every deadline and window rule of §3: `ERR_EXPERIENCE_TOO_OLD`, `ERR_RETAKE_WAIT_NOT_ELAPSED`, `ERR_ATTEMPT_LIMIT_EXCEEDED`, `ERR_SCHEDULE_DATE_PAST`, `ERR_REASSIGN_WINDOW_NOT_OPEN`, `ERR_SUPPLEMENTAL_RETAKE_WAIT`, `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_REINSTATEMENT_WINDOW_CLOSED`, and `ERR_CE_ENTRY_INVALID` (all HTTP 422).
8. **Request shape and business constraints.** Required fields, enum membership, numeric ranges, and conditional-field presence are swept last as `ERR_INVALID_REQUEST` (HTTP 400), alongside the dedicated constraint codes `ERR_WORK_PERIOD_INVALID` (HTTP 422), `ERR_HOURS_OUT_OF_RANGE` (HTTP 422), `ERR_WORK_PERIOD_OVERLAP` (HTTP 409), `ERR_EXAM_DAY_CONFLICT` (HTTP 409), `ERR_JURISDICTION_CODE_EXISTS` (HTTP 409), `ERR_TRANSMITTAL_DUPLICATE` (HTTP 409), and `ERR_CE_HOURS_INSUFFICIENT` (HTTP 422).

One nuance lives inside this ordering: a caller whose role is `Supervisor` but whose `X-User-ID` does not match the assigned report's `supervisor_id` is rejected at tier 6 with `ERR_SUPERVISOR_MISMATCH`, not at tier 2 — the tier-2 ownership sweep governs candidate-scoped resources.

### 2.7. Precision, Rounding, and Half-Open Periods

All hour figures in this domain are integers. Wherever a crediting calculation produces a fraction, the result is rounded half-up to the nearest whole hour — a value of 3.5 becomes 4 — and the rounding is applied per individual experience report first; area totals and candidate totals then sum the already-rounded integers, never the unrounded products. Calendar periods are half-open intervals: a work period covers the span from `work_period_start` up to but not including `work_period_end`, and a continuing-education period covers `period_start` up to but not including `period_end`. Two periods that merely touch at a boundary day therefore do not overlap.

### 2.8. Examination Content Confidentiality

Examination outcomes are exposed only as a `result` of `PASS` or `FAIL` plus a `scaled_score` integer between 0 and 100 inclusive. Item-level examination content — questions, answers, subscores, and any finer breakdown — is confidential and is never returned by any read endpoint.

## 3. Business Logic & Workflows

### 3.1. The Registries: Candidates, Jurisdictions, and Supervisors

Everything begins with three registries. An `Anonymous` caller opens a candidate record by supplying `email`, `full_name`, `password`, and a `home_jurisdiction_code` naming the board where initial licensure is sought. The `email` must be unique across all candidates, and the `password` is stored but never returned in any response. The `home_jurisdiction_code` must resolve to an existing jurisdiction's `code`, or registration fails with `ERR_JURISDICTION_UNKNOWN`. A fresh candidate carries four guarded sub-statuses — `education_status` starting at `NONE`, `experience_status` at `NOT_STARTED`, `exam_status` at `NOT_AUTHORIZED`, and `record_standing` at `CLEAR` — plus a persisted `certificate_eligible` flag that starts at false and is recomputed after every event that could change it. Anyone reading a candidate sees those sub-statuses; a candidate, a board, or council staff may also pull a computed progress summary whose contents are detailed in §3.3 and §3.6.

Before any candidate can register, council staff seed the jurisdiction registry. Creating a jurisdiction takes a unique `code` (a duplicate is rejected with `ERR_JURISDICTION_CODE_EXISTS`) and a `name`, plus four optional overrides of the national standard: `requires_supplemental_exam` (default false), `min_total_experience_hours` (default 3740), `ce_hours_required` (default 24, the total continuing-education hours required per renewal period), `ce_hsw_hours_required` (default 12, the Health-Safety-Welfare subset of that total), and `ce_carry_over_allowed` (default false, governing whether surplus hours from the previous period may roll forward). These flags are read live where §3.6 and §3.7 require it — most consequentially, the `ce_carry_over_allowed` flag in force at the moment of each renewal decides which compliance variant applies. Jurisdiction updates are concurrency-guarded per §2.5.

The supervisor registry holds licensed architects who may verify experience. Registration records `full_name`, a unique `license_number`, and a `jurisdiction_code` that must resolve to an existing jurisdiction. A supervisor's `license_status` starts at `ACTIVE` and may be flipped to `INACTIVE` (and back) by council staff through the concurrency-guarded supervisor update; only `ACTIVE` supervisors can participate in submission or verification, as §3.3 details.

### 3.2. Education Evaluation and the Review Loop

A candidate demonstrates the education track by submitting an evaluation naming a `path_type` of either `ACCREDITED_DEGREE` or `ALTERNATIVE_PATH`, together with `institution_name` and `semester_credit_hours`. The alternative path carries a hard floor: an `ALTERNATIVE_PATH` evaluation must declare at least 64 semester credit hours, and a lower figure is rejected with `ERR_ALTERNATIVE_CREDITS_INSUFFICIENT` (HTTP 422). A new evaluation lands in `SUBMITTED` status with `review_count` at 0 and `deficiency_notes` null. Only one evaluation per candidate may be open at a time: submitting a second while an earlier one is still `SUBMITTED` fails with `ERR_EVALUATION_ALREADY_OPEN`.

An `NcarbAdministrator` adjudicates each open evaluation through the review action, which takes a `decision` of `SATISFIED` or `DEFICIENT`. A `SATISFIED` decision moves the evaluation to `SATISFIED` — its terminal state — increments `review_count` by one, flips the owning candidate's `education_status` from `NONE` to `SATISFIED`, and triggers a recompute of `certificate_eligible`. A `DEFICIENT` decision requires a non-empty `deficiency_notes` (its absence is an `ERR_INVALID_REQUEST`); it moves the evaluation to `DEFICIENT`, records the notes, and likewise increments `review_count` by one. Attempting to review an evaluation that is no longer `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

`DEFICIENT` is a loop, not a dead end. The owning candidate — and only that candidate — may resubmit the evaluation, which returns it to `SUBMITTED`, clears `deficiency_notes` back to null, and replaces any of `path_type`, `institution_name`, or `semester_credit_hours` for which the resubmission supplies new values. A candidate's evaluations may be listed with an optional `status` filter plus the standard `limit` and `offset` pagination.

### 3.3. Experience Reporting: Credit Tiering, Verification, and Reassignment

Experience accrues through reports a candidate drafts against a named supervisor. Creating a report records `candidate_id`, `supervisor_id`, a `practice_area` drawn from exactly six values — `PRACTICE_MANAGEMENT`, `PROJECT_MANAGEMENT`, `PROGRAMMING_ANALYSIS`, `PROJECT_PLANNING_DESIGN`, `PROJECT_DEVELOPMENT_DOCUMENTATION`, `CONSTRUCTION_EVALUATION` — plus `hours`, `work_period_start`, `work_period_end`, and an optional `work_setting` that defaults to `ARCHITECTURAL_FIRM` and may instead be `GOVERNMENT` or `OTHER`. A single report must carry at least 1 hour and at most 2000 hours; anything outside that range is rejected with `ERR_HOURS_OUT_OF_RANGE`. The `work_period_end` must fall strictly after `work_period_start`, failing which the create is rejected with `ERR_WORK_PERIOD_INVALID`. New reports are `DRAFT`, with `submitted_at` null, `credit_pct` 0, `credited_hours` 0, and `return_reason` null. Two checks are deliberately deferred from creation to submission: work-period overlap and supervisor fitness.

Submission is where a report earns its credit tier. When the owning candidate submits a `DRAFT` report, the service requires the assigned supervisor to exist and to hold `license_status` `ACTIVE`, else `ERR_SUPERVISOR_NOT_ACTIVE`; it requires the half-open work period to avoid overlapping any `SUBMITTED` or `VERIFIED` report of the same candidate — mere adjacency, where one period's end equals another's start, is allowed — with overlaps rejected as `ERR_WORK_PERIOD_OVERLAP`; and it requires the submission date to fall no later than sixty calendar months after the report's `work_period_end`, else the report is too old to count and submission fails with `ERR_EXPERIENCE_TOO_OLD`. A successful submission moves the report to `SUBMITTED`, stamps `submitted_at` with the current logical-clock instant, and locks the credit percentage into `credit_pct` according to how quickly the hours were reported: a report submitted on or before the day eight calendar months after its `work_period_end` locks 100 percent credit, while one submitted later but on or before the day sixty calendar months after `work_period_end` locks 50 percent. That locked tier is permanent — a report submitted inside the eight-month full-credit window keeps 100 percent forever, even if it is verified years later.

A returned report is a second chance, not a new report. Resubmitting a `RETURNED` report re-applies every submission check, restamps `submitted_at` to the current instant, re-locks `credit_pct` against the new submission date, and clears `return_reason`.

Verification belongs to the assigned supervisor alone. The caller's `X-User-ID` must equal the report's `supervisor_id`, failing which the rejection is `ERR_SUPERVISOR_MISMATCH`, and the supervisor must still hold `license_status` `ACTIVE` at verify time, failing which the rejection is `ERR_SUPERVISOR_NOT_ACTIVE`; verifying a report that is not `SUBMITTED` is an `ERR_INVALID_STATE`. A successful verification moves the report to its terminal `VERIFIED` state and stamps `credited_hours`: the report's `hours` are multiplied by the locked `credit_pct` percentage and the product is rounded half-up to a whole hour, per report, before any aggregation. Verification also fires a two-link cascade on the candidate. Link one: if this is the candidate's first `VERIFIED` report, `experience_status` moves from `NOT_STARTED` to `IN_PROGRESS` (refreshing the candidate's `updated_at`); then the completion gate below is re-evaluated, and if it now holds, `experience_status` advances to `COMPLETE`. Link two: `certificate_eligible` is recomputed. A supervisor may instead return a `SUBMITTED` report with a `return_reason`; the report moves to `RETURNED`, the reason is recorded, and candidate totals are unaffected because `SUBMITTED` reports contribute nothing.

When a supervisor goes silent, the candidate may reassign an unanswered `SUBMITTED` report to a new supervisor, but only after a waiting period: the current date must be on or after the day forty-five days after the report's submitted date. The `new_supervisor_id` must resolve to an existing supervisor (else `ERR_NOT_FOUND`) that differs from the current one and holds `license_status` `ACTIVE`; attempting the reassignment before the forty-five-day window has opened, or naming the same or an inactive supervisor, is rejected with `ERR_REASSIGN_WINDOW_NOT_OPEN`. Reassignment replaces `supervisor_id` but preserves both `submitted_at` and the locked `credit_pct` — the credit tier survives the handoff untouched.

Credited hours aggregate per practice area. Only `VERIFIED` reports contribute; `DRAFT`, `SUBMITTED`, and `RETURNED` reports each contribute exactly zero. The completion gate that drives `experience_status` to `COMPLETE` has two conjuncts, both evaluated on inclusive boundaries: every one of the six areas must meet its minimum credited hours — at least 160 in `PRACTICE_MANAGEMENT`, at least 360 in `PROJECT_MANAGEMENT`, at least 260 in `PROGRAMMING_ANALYSIS`, at least 1360 in `PROJECT_PLANNING_DESIGN`, at least 1520 in `PROJECT_DEVELOPMENT_DOCUMENTATION`, and at least 80 in `CONSTRUCTION_EVALUATION` — and the total credited across all areas must reach the greater of the national floor of 3740 hours or the home jurisdiction's `min_total_experience_hours` override. The six area minima sum to exactly 3740 hours, so a jurisdiction that never overrides the national total asks for precisely a full-credit profile; an area sitting exactly at its minimum counts.

A candidate-facing progress summary reports both official and what-if figures. Its official fields — `total_credited_hours`, `locked_credited_hours`, and the per-area `area_progress` map — always use the tiers locked at submission time. Its `projected_credited_hours` field answers a different question: what the candidate would hold if every `DRAFT` and `SUBMITTED` report were submitted today and verified today, re-tiering each such report against the current date and adding the `VERIFIED` rows' stamped `credited_hours`. Projected and locked figures diverge exactly when the logical clock has crossed a tier boundary since a report was (or has not been) submitted. The summary also carries `candidate_id`, the four sub-statuses `education_status`, `experience_status`, `exam_status`, and `record_standing`, the persisted `certificate_eligible` flag, the `certificate_status` of the candidate's certificate if one exists, and `open_disciplinary_count`. Experience reports may be listed with `candidate_id`, `supervisor_id`, `status`, and `practice_area` filters alongside `limit` and `offset`.

### 3.4. Examination: Authorization, Scheduling, Scoring, and the Rolling Clock

Testing begins when a `BoardAdministrator` grants an examination authorization for a candidate, naming the authorizing board's `jurisdiction_code` (which must resolve, else `ERR_JURISDICTION_UNKNOWN`). The grant moves the candidate's `exam_status` from `NOT_AUTHORIZED` to `AUTHORIZED` and creates one progress row for each of the six divisions — `PCM`, `PJM`, `PA`, `PPD`, `PDD`, and `CE` — every row `ELIGIBLE` with `attempt_count` 0, an empty `attempt_dates` history, and `scheduled_date`, `last_failed_at`, `passed_at`, `expires_at`, `result`, and `scaled_score` all null. Each row records the `authorization_id` of the grant that created it, and the authorization record itself is `ACTIVE`. The candidate's progress rows are discoverable through the candidate's exam-progress list — no reverse lookup on the authorization is required — and that list is ordered by `division_code` ascending, which produces the sequence CE, PA, PCM, PDD, PJM, PPD; the list accepts `division_code` and `status` filters.

Scheduling a sitting is the candidate's action on a progress row they own, supplying a `scheduled_date`. From `ELIGIBLE`, the requested date must fall on or after the current date (earlier dates are rejected with `ERR_SCHEDULE_DATE_PAST`); the attempt window must have room, meaning fewer than three prior scored attempts on that division bear dates strictly more recent than the day three hundred sixty-five days before the requested sitting — an attempt exactly 365 days earlier no longer counts against the window, and a third recent attempt makes the request fail with `ERR_ATTEMPT_LIMIT_EXCEEDED`; and no other `SCHEDULED` division nor any `REGISTERED` supplemental exam of the same candidate may already occupy that calendar day, which is rejected as `ERR_EXAM_DAY_CONFLICT`. From `FAILED`, all of those checks apply plus the retake waiting period: the new sitting must fall at least sixty days after `last_failed_at`, with a sitting exactly sixty days later permitted; earlier requests are rejected with `ERR_RETAKE_WAIT_NOT_ELAPSED`. From `EXPIRED`, scheduling follows the same rules as from `ELIGIBLE` — prior attempts still count toward the 365-day window, and an expired pass confers no credit — while the row's `passed_at`, `expires_at`, `result`, and `scaled_score` are retained as history until the next score is reported. Attempting to schedule a division already `PASSED` is rejected with `ERR_DIVISION_ALREADY_PASSED`, and one already `SCHEDULED` with `ERR_DIVISION_ALREADY_SCHEDULED`.

Score reporting belongs to `NcarbAdministrator` staff and applies to a `SCHEDULED` division whose sitting date has arrived — the current date must be on or after the `scheduled_date`. The report carries a `result` of `PASS` or `FAIL` and a `scaled_score` integer from 0 to 100 inclusive. A `PASS` increments `attempt_count` by one, appends the sitting date to `attempt_dates`, records the sitting date as `passed_at`, sets `expires_at` to the day sixty calendar months after the pass, stores the result and score, and clears `scheduled_date` to null. A `FAIL` likewise increments `attempt_count` by one and appends the sitting date, records the sitting date as `last_failed_at`, stores the result and score, and clears `scheduled_date`. When a pass completes the set of six, the candidate's `exam_status` advances from `AUTHORIZED` to `ALL_PASSED` and `certificate_eligible` is recomputed.

Passed divisions live on a rolling clock, not a fixed deadline. Each pass remains valid until the current date reaches its own `expires_at`, sixty calendar months after that pass's date; on the boundary day itself the pass is already expired, because expiry triggers when the current date is on or after `expires_at`. The expiry sweep moves every such `PASSED` row to `EXPIRED`. Because validity is judged per division against its own pass date, the earliest pass anchors the effective window: once the oldest pass crosses its sixty-month boundary, that division lapses even though later passes remain valid until their own anniversaries. When a lapse leaves the candidate with fewer than six valid passes, `exam_status` falls back from `ALL_PASSED` to `AUTHORIZED` and `certificate_eligible` is recomputed — a lapse can undo a completed examination set. An `EXPIRED` division is not a dead end: it may be scheduled again exactly as an `ELIGIBLE` one can.

### 3.5. Supplemental Examinations

Some boards layer a jurisdiction-specific examination on top of the national divisions. A candidate may register for a board's supplemental exam only when that jurisdiction's `requires_supplemental_exam` flag is true; registering against a board that requires none is rejected with `ERR_SUPPLEMENTAL_NOT_REQUIRED`. Registration supplies `jurisdiction_code` and an `exam_date` that must fall on or after the current date, failing which `ERR_SCHEDULE_DATE_PAST` applies, and the same calendar-day conflict rule as division scheduling applies — a `REGISTERED` supplemental exam blocks, and is blocked by, any same-day `SCHEDULED` division of the candidate, with `ERR_EXAM_DAY_CONFLICT`. A new registration sits in `REGISTERED` status with `result` null.

After a failure, retakes observe their own waiting period: a new registration's `exam_date` must fall at least ninety days after the previous `FAILED` sitting, and an earlier date is rejected with `ERR_SUPPLEMENTAL_RETAKE_WAIT`. The board reports the outcome once the sitting date has arrived — the current date must be on or after the `exam_date` — moving the registration to its terminal `PASSED` or `FAILED` state. A `PASSED` result satisfies the supplemental requirement for that jurisdiction and triggers a recompute of `certificate_eligible`. A candidate's registrations may be listed with an optional `status` filter.

### 3.6. Certificate Eligibility and Issuance

The persisted `certificate_eligible` flag on a candidate is the conjunction of five conditions, recomputed after every event that touches one of its inputs — an education review, a report verification, a score report, a supplemental-exam result, an expiry sweep, or a disciplinary sanction. The flag is true exactly when the candidate's `education_status` is `SATISFIED`, the candidate's `experience_status` is `COMPLETE`, all six examination divisions are `PASSED`, the home jurisdiction either does not require a supplemental exam or the candidate holds a `PASSED` supplemental exam for that home jurisdiction, and the candidate's `record_standing` is `CLEAR`.

Issuance is an `NcarbAdministrator` action and is gated three ways beyond eligibility. Issuing while `certificate_eligible` is false fails with `ERR_ELIGIBILITY_NOT_MET`; issuing while any `OPEN` disciplinary report exists against the candidate fails with `ERR_OPEN_DISCIPLINARY_BLOCK`; and issuing while the candidate already holds a certificate that is not `REVOKED` fails with `ERR_CERTIFICATE_EXISTS`. A successful issuance creates a certificate in `ACTIVE` status with a server-minted `serial_number`, an `issued_at` taken from the logical clock, a `home_jurisdiction_code` snapshot of the candidate's home board, `ce_hours_required` and `ce_hsw_hours_required` snapshots copied from that board's flags at issuance time (so later board edits do not retroactively change the certificate's obligations), `renewal_count` at 0, and the first continuing-education period running from `period_start` equal to the issuance date (inclusive) to `period_end` exactly twenty-four calendar months later (exclusive). Reading a candidate's certificate history returns an array that holds at most one certificate while that certificate is not `REVOKED`; reading a certificate directly includes its computed period totals.

### 3.7. Continuing Education, Renewal, Lapse, and Reinstatement

Certificate maintenance runs on continuing-education entries logged against the certificate while it is `ACTIVE` or `LAPSED`. Each entry records `certificate_id`, an integer `hours` of at least 1 and at most 24, an `hsw` flag marking Health-Safety-Welfare content, a `completed_date` that must fall on or before the current date, and a `provider` name; an entry violating those bounds is rejected with `ERR_CE_ENTRY_INVALID`. Three computed totals track the certificate: `ce_hours_current_period` sums the hours of non-voided entries whose `completed_date` falls inside the current half-open period, `ce_hsw_current_period` sums the same restricted to `hsw` entries, and `lifetime_ce_hours` sums every non-voided entry across all periods and is never reset by renewal, lapse, or reinstatement. An erroneous entry may be voided by the certificate's owner; voiding sets `voided` to true and the entry counts toward nothing from then on. Entries may be listed with an optional `voided` filter plus `limit` and `offset`.

Renewal is dual-mode, and the mode is chosen by the certificate's state at request time. While `ACTIVE`, renewal is open during a sixty-day window: the current date must fall on or after the day sixty days before `period_end` and strictly before `period_end`; outside that window the request is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. Compliance is then judged against the certificate's snapshotted requirements using the home jurisdiction's `ce_carry_over_allowed` flag read live at renewal time. Under the strict variant — flag false — the current period's hours alone must meet `ce_hours_required` and its Health-Safety-Welfare subset must meet `ce_hsw_hours_required`. Under the carry-over variant — flag true — the current-period total is augmented by a carry of up to 12 hours: the excess of the immediately preceding period's total over `ce_hours_required`, floored at zero and capped at 12, counts toward the current period's total requirement, while the Health-Safety-Welfare subset receives no carry and must stand on current-period entries alone; the preceding period is treated as zero for the first period and after any reinstatement. Identical entry history can therefore pass in one jurisdiction and fail in another, and insufficient totals are rejected with `ERR_CE_HOURS_INSUFFICIENT`. A successful renewal advances the period: `period_start` becomes the old `period_end`, `period_end` extends twenty-four calendar months beyond it, `renewal_count` increments by one, and the carry available to the new period is booked as the just-ended period's excess over `ce_hours_required`, floored at zero and capped at 12.

Lapse is unconditional. When the expiry sweep finds an `ACTIVE` certificate whose `period_end` has been reached — the current date on or after `period_end` — the certificate becomes `LAPSED` regardless of how many continuing-education hours it holds; CE sufficiency only matters at renewal time.

Reinstatement is the `LAPSED` mode of renewal. It remains available until the day twelve calendar months after `period_end`; a request on or before that day is admissible, and after it the door is shut with `ERR_REINSTATEMENT_WINDOW_CLOSED`. Reinstatement always uses strict accounting — carry-over never applies — and raises the Health-Safety-Welfare bar by a penalty of 4 hours: non-voided entries completed within the closed period must total at least `ce_hours_required`, and their `hsw` subset must reach `ce_hsw_hours_required` plus 4. A successful reinstatement returns the certificate to `ACTIVE`, starts a fresh period at the current date with `period_end` twenty-four calendar months later, increments `renewal_count` by one, and resets the carry bookkeeping to zero.

### 3.8. Reciprocal Transmittal and Disciplinary Action

A certificate earns its keep through transmittal: the holder asks that it be sent to a destination board for reciprocal licensure. The request names a `jurisdiction_code` that must resolve to an existing jurisdiction, requires the certificate to be `ACTIVE` at request time (otherwise `ERR_CERTIFICATE_NOT_ACTIVE`), and is refused while any `OPEN` disciplinary report stands against the candidate with `ERR_OPEN_DISCIPLINARY_BLOCK`. Only one unanswered transmittal per destination may exist: a second request to the same jurisdiction while one is still `REQUESTED` is rejected with `ERR_TRANSMITTAL_DUPLICATE`. A new transmittal is `REQUESTED` with `denial_reason` null.

The destination board decides by supplying an `outcome` of `GRANT` or `DENY`. A `GRANT` — permitted only while the certificate is still `ACTIVE` at decision time — moves the transmittal to `LICENSE_GRANTED` and records reciprocal licensure for the certificate's candidate in that jurisdiction. A `DENY` requires a non-empty `denial_reason` (its absence is an `ERR_INVALID_REQUEST`), moves the transmittal to `LICENSE_DENIED` with the reason recorded, and leaves the candidate free to request a fresh transmittal to the same jurisdiction afterwards. Both outcomes are terminal. A certificate's transmittals may be listed with an optional `status` filter.

Disciplinary action runs in the opposite direction. A `BoardAdministrator` files a report against a candidate with a `candidate_id`, the reporting board's `jurisdiction_code`, and a non-empty `allegation`; the filer's `X-User-ID` is recorded as `filed_by_user_id`, and the report opens as `OPEN` with `resolution_notes` null. Resolution belongs to `NcarbAdministrator` staff under a segregation-of-duties rule: the resolver's `X-User-ID` must differ from the report's `filed_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The resolver supplies an `outcome` and optional `resolution_notes`. A `CLEAR` outcome moves the report to `RESOLVED_CLEAR` and changes nothing about standing or certificates. A `SANCTION` outcome moves the report to `RESOLVED_SANCTION` and fires a three-link cascade: link one sets the candidate's `record_standing` to `FLAGGED`, which is terminal; link two, caused by link one, moves the candidate's non-`REVOKED` certificate — if one exists, whether `ACTIVE` or `LAPSED` — to `REVOKED`; link three, caused by link two, moves every `REQUESTED` transmittal of that certificate to `CANCELLED`, leaving already-terminal `LICENSE_GRANTED` and `LICENSE_DENIED` transmittals untouched. The cascade finishes with a recompute of `certificate_eligible`, which the flag's `CLEAR`-standing conjunct forces to false. A candidate's disciplinary reports may be listed with an optional `status` filter.

## 4. Endpoint Definitions

All endpoints live under the `/licensure` mount. Endpoints that create a new resource respond with HTTP 201; all other successful operations — reads, updates, and state-transition actions — respond with HTTP 200. Request bodies, response payloads, and side effects are defined by the narratives of §2 and §3; this table is only an index of method, path, purpose, and authorization.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /licensure/_clock/set_current_utc | Set the logical clock used by every date/deadline rule | NcarbAdministrator |
| POST | /licensure/_maintenance/run_expiry_sweep | Apply time-based transitions: expire passed divisions, lapse active certificates | NcarbAdministrator |
| POST | /licensure/candidates | Register a candidate record | Anonymous |
| GET | /licensure/candidates/{id} | Read one candidate including sub-statuses | Candidate, NcarbAdministrator, BoardAdministrator |
| GET | /licensure/candidates/{id}/summary | Computed progress read: sub-statuses, area sums, locked vs projected hours, eligibility | Candidate, NcarbAdministrator, BoardAdministrator |
| POST | /licensure/jurisdictions | Create a jurisdiction board with national-standard overrides | NcarbAdministrator |
| PATCH | /licensure/jurisdictions/{id} | Update jurisdiction flags/overrides (OCC-guarded) | NcarbAdministrator |
| POST | /licensure/supervisors | Register a supervising architect | NcarbAdministrator |
| PATCH | /licensure/supervisors/{id} | Update supervisor license data (OCC-guarded) | NcarbAdministrator |
| POST | /licensure/candidates/{id}/education-evaluations | Submit an education evaluation (one open per candidate) | Candidate |
| GET | /licensure/candidates/{id}/education-evaluations | List a candidate's education evaluations | Candidate, NcarbAdministrator |
| POST | /licensure/education-evaluations/{id}/review | Adjudicate an evaluation as SATISFIED or DEFICIENT | NcarbAdministrator |
| POST | /licensure/education-evaluations/{id}/resubmit | Resubmit a DEFICIENT evaluation after remediation | Candidate |
| POST | /licensure/experience-reports | Create a DRAFT experience report | Candidate |
| GET | /licensure/experience-reports/{id} | Read one experience report including stamped credit fields | Candidate, Supervisor, NcarbAdministrator |
| GET | /licensure/experience-reports | Filtered list of experience reports | Candidate, Supervisor, NcarbAdministrator |
| POST | /licensure/experience-reports/{id}/submit | Submit a DRAFT or RETURNED report; stamps submitted_at and locks credit_pct | Candidate |
| POST | /licensure/experience-reports/{id}/verify | Assigned supervisor verifies a SUBMITTED report; stamps credited_hours | Supervisor |
| POST | /licensure/experience-reports/{id}/return | Assigned supervisor returns a SUBMITTED report for correction | Supervisor |
| POST | /licensure/experience-reports/{id}/reassign | Reassign an unanswered SUBMITTED report after the 45-day window | Candidate |
| POST | /licensure/candidates/{id}/exam-authorizations | Grant authorization to test; creates six division progress rows | BoardAdministrator |
| GET | /licensure/candidates/{id}/exam-progress | List division progress rows, ordered by division_code ascending | Candidate, BoardAdministrator, NcarbAdministrator |
| POST | /licensure/exam-progress/{id}/schedule | Schedule a sitting from ELIGIBLE, FAILED, or EXPIRED | Candidate |
| POST | /licensure/exam-progress/{id}/report-score | Report a PASS/FAIL result with scaled_score for a sitting whose date arrived | NcarbAdministrator |
| POST | /licensure/candidates/{id}/supplemental-exams | Register for a jurisdiction's supplemental exam | Candidate |
| GET | /licensure/candidates/{id}/supplemental-exams | List a candidate's supplemental exam registrations | Candidate, BoardAdministrator, NcarbAdministrator |
| POST | /licensure/supplemental-exams/{id}/report-result | Board reports PASS/FAIL for a registered supplemental exam | BoardAdministrator |
| POST | /licensure/candidates/{id}/certificate | Issue the national certificate | NcarbAdministrator |
| GET | /licensure/candidates/{id}/certificate | Read the candidate's certificate history | Candidate, NcarbAdministrator, BoardAdministrator |
| GET | /licensure/certificates/{id} | Read one certificate including computed CE period totals | Candidate, NcarbAdministrator, BoardAdministrator |
| POST | /licensure/certificates/{id}/renew | Renew an ACTIVE certificate in its window, or reinstate a LAPSED one | Candidate |
| POST | /licensure/certificates/{id}/ce-entries | Log a continuing-education entry | Candidate |
| GET | /licensure/certificates/{id}/ce-entries | List CE entries of a certificate | Candidate, NcarbAdministrator |
| POST | /licensure/ce-entries/{id}/void | Void an erroneous CE entry | Candidate |
| POST | /licensure/certificates/{id}/transmittals | Request transmittal of an ACTIVE certificate to a jurisdiction board | Candidate |
| GET | /licensure/certificates/{id}/transmittals | List transmittals of a certificate | Candidate, BoardAdministrator, NcarbAdministrator |
| POST | /licensure/transmittals/{id}/decide | Destination board grants or denies reciprocal licensure | BoardAdministrator |
| POST | /licensure/disciplinary-reports | File a disciplinary report against a candidate | BoardAdministrator |
| POST | /licensure/disciplinary-reports/{id}/resolve | Resolve a report; SANCTION fires the revocation cascade | NcarbAdministrator |
| GET | /licensure/candidates/{id}/disciplinary-reports | List disciplinary reports filed against a candidate | Candidate, BoardAdministrator, NcarbAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is only the index of identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_JURISDICTION_UNKNOWN | 422 |
| ERR_JURISDICTION_CODE_EXISTS | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_EVALUATION_ALREADY_OPEN | 409 |
| ERR_ALTERNATIVE_CREDITS_INSUFFICIENT | 422 |
| ERR_WORK_PERIOD_INVALID | 422 |
| ERR_HOURS_OUT_OF_RANGE | 422 |
| ERR_WORK_PERIOD_OVERLAP | 409 |
| ERR_EXPERIENCE_TOO_OLD | 422 |
| ERR_SUPERVISOR_NOT_ACTIVE | 422 |
| ERR_SUPERVISOR_MISMATCH | 403 |
| ERR_REASSIGN_WINDOW_NOT_OPEN | 422 |
| ERR_DIVISION_ALREADY_PASSED | 409 |
| ERR_DIVISION_ALREADY_SCHEDULED | 409 |
| ERR_RETAKE_WAIT_NOT_ELAPSED | 422 |
| ERR_ATTEMPT_LIMIT_EXCEEDED | 422 |
| ERR_SCHEDULE_DATE_PAST | 422 |
| ERR_EXAM_DAY_CONFLICT | 409 |
| ERR_SUPPLEMENTAL_NOT_REQUIRED | 422 |
| ERR_SUPPLEMENTAL_RETAKE_WAIT | 422 |
| ERR_ELIGIBILITY_NOT_MET | 409 |
| ERR_CERTIFICATE_EXISTS | 409 |
| ERR_CERTIFICATE_NOT_ACTIVE | 409 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 422 |
| ERR_REINSTATEMENT_WINDOW_CLOSED | 422 |
| ERR_CE_HOURS_INSUFFICIENT | 422 |
| ERR_CE_ENTRY_INVALID | 422 |
| ERR_OPEN_DISCIPLINARY_BLOCK | 409 |
| ERR_TRANSMITTAL_DUPLICATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
