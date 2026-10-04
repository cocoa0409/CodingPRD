# Volunteer Placement & Clearance API — Product Requirements Document

## 1. Introduction

Every year, an international volunteer agency moves thousands of candidates through a pipeline that begins with a written application and ends, some twenty-seven months later, with a sworn-in volunteer completing a term of service abroad. Between those two points sit country program configuration, skill-based matching against concrete assignment openings, structured interviews, formal invitations bound to specific departure dates, medical and dental clearance weighed against the medical infrastructure actually available in the destination country, background and suitability review under a strict segregation of duties, pre-service training with language, technical, and cultural assessment, site placement under host-community agreements and housing standards, in-service medical and safety support, and — at the close of service — a readjustment allowance together with non-competitive eligibility benefits.

This document specifies the API that orchestrates that pipeline, and its design answers four pressures. Decisions made early must survive later change, so every invitation pins the country program, its medical support tier, and the departure date at issuance, and no later administrative edit rewrites those facts. Several officers touch the same opening, so the invitation-issuing write is guarded by optimistic concurrency control. Time itself is a test input: the system runs on a deterministic logical clock whose every advance triggers a fixed-order sweep that expires invitations, closes openings, and starts and concludes training cohorts. And denial or withdrawal is never a local event — each one fires a precise cascade that releases seats, voids in-flight clearances, and returns applications to the matching pool. All resources are mounted under the `/volunteer-portal` prefix, with the logical clock exposed separately under `/_clock`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, the response envelope, pagination, the logical clock, resource boilerplate, concurrency control, validation precedence, and numeric precision.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request with either header missing or malformed, or whose role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly seven roles: `SystemAdmin`, `Applicant`, `PlacementOfficer`, `MedicalOfficer`, `LegalReviewer`, `TrainingDirector`, and `CountryDirector`. Each operation is restricted to a named subset of these roles, and an authenticated caller whose role is outside the operation's allowed set is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant compare the resource's foreign-key field to `X-User-ID`. Seven applicant-scoped operations enforce this ownership check and reject a mismatched caller with `ERR_NOT_OWNER` (HTTP 403): submitting an application, withdrawing an application, accepting an invitation, declining an invitation, creating a medical clearance, resubmitting a medical clearance, and reading the match list of an application. Creating an application likewise requires `X-User-ID` to equal the payload's `applicant_id`.

For the other six roles — `SystemAdmin`, `PlacementOfficer`, `MedicalOfficer`, `LegalReviewer`, `TrainingDirector`, and `CountryDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `issued_by` on an Invitation, as `reviewed_by` on a MedicalClearance, or as `background_adjudicated_by` and `suitability_decided_by` on a LegalClearance) but does not compare it to any entity's `id`.

A `SystemAdmin` onboards applicants, configures country programs, assignment openings, and training cohorts, cancels openings, and drives the logical clock. An `Applicant` owns exactly the applications whose `applicant_id` equals their `X-User-ID`, and submits, withdraws, answers invitations, and files medical forms. A `PlacementOfficer` reviews applications, schedules and scores interviews, issues invitations, and enrolls cleared applicants into training cohorts. A `MedicalOfficer` renders medical clearance determinations and may log medical-care events during service. A `LegalReviewer` adjudicates background checks and determines suitability — never both on the same clearance. A `TrainingDirector` records trainee assessments, orders remediation, and swears in passed trainees. A `CountryDirector` proposes and reviews site placements, logs safety and security events, suspends and returns volunteers, and completes or early-terminates service. Every role may call every read (GET) endpoint.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order; the service-event log is the documented exception, listed chronologically by `occurred_at` with `created_at` ascending as the tie-break (§3.8). The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Deterministic Sweep

The system does not consult the wall clock. All deadline reasoning runs on a logical clock that, at server startup and before any administrative intervention, reads exactly 2026-09-01T00:00:00Z. A `SystemAdmin`-only test-driving capability advances the clock to a supplied instant: the request carries the target as `to_iso8601`, the response reports the resulting reading as `current_utc`, and the clock must never move backwards.

Every advance of the logical clock runs a sweep in a pinned order, each step completing before the next begins:

1. **Invitation expiry.** Every invitation still `ISSUED` whose `acceptance_deadline` is strictly earlier than the new reading becomes `EXPIRED`; its opening's `seats_provisional` is decremented, and its application moves from `INVITED` back to `UNDER_REVIEW`.
2. **Opening closure.** Every assignment opening still `OPEN` whose `invitation_issue_deadline` is strictly earlier than the new reading becomes `CLOSED`.
3. **Cohort session start.** Every training cohort in `SCHEDULED` whose `start_date` has been reached or passed becomes `IN_SESSION`, and each of its enrollments in `ENROLLED` or `REMEDIATION` moves its application from `CLEARED_TO_DEPART` to `IN_TRAINING`.
4. **Cohort conclusion.** Every training cohort in `IN_SESSION` whose `end_date` has been reached or passed becomes `CONCLUDED`.

Two practical consequences follow. An invitation that remains `ISSUED` is never past its acceptance deadline, and an opening that remains `OPEN` is never past its issue deadline — the sweep-induced state is what clients observe, so the acceptance and issuance paths carry no separate deadline errors. And because the sweep runs on every clock set in exactly this order, downstream state (an application entering `IN_TRAINING`, say) always derives from the same deterministic sequence regardless of how large the clock step was.

### 2.5. Common Resource Properties

Every persisted resource carries a system-minted `id` formatted as a bare UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. With one exception, every resource also carries `updated_at` — refreshed on any change to the resource — and `version`, an integer that increments on every mutation, including mutations performed by system cascades rather than by a direct client write on that resource.

The exception is the ServiceEvent. Service events form an append-only log: each entry receives an `id` and a `created_at`, and neither `updated_at` nor `version` exists on the resource. A logged event is immutable.

### 2.6. Immutable Issuance Snapshots

When an invitation is issued, three facts are snapshotted onto it and never change again: `pinned_country_program_id` identifies the program hosting the assignment, `pinned_country_medical_tier` records the program's medical support tier at issuance, and `pinned_departure_date` records the opening's planned departure date. The invitation also stamps `issued_at` from the logical clock, records the issuing officer in `issued_by`, and sets its `acceptance_deadline` exactly ten days after `issued_at`.

Later administrative edits to the country program — suspending it, closing it, changing its medical support tier, training capacity, or language threshold — never rewrite these pinned values. Every downstream consumer evaluates against the snapshot: medical clearance reviews measure declared conditions against the `pinned_country_medical_tier` even if the live program tier has since changed, and training enrollment requires the cohort to belong to the `pinned_country_program_id` rather than to whatever program the opening might later be associated with.

### 2.7. Seat Accounting and Opening Churn

An assignment opening's `seats_total` is its fixed capacity, and two computed counters track its consumption. `seats_provisional` counts the opening's invitations currently in `ISSUED` — seats held but not yet accepted — and `seats_committed` counts those in `ACCEPTED`. Both counters start at zero, and issuance is only possible while the sum of held and committed seats remains strictly below `seats_total`.

Acceptance converts a hold into a commitment: `seats_provisional` is decremented and `seats_committed` incremented, and when the committed count reaches `seats_total` the opening becomes `FILLED`. The machine is cyclic — a rescission that drops the committed count of a `FILLED` opening back below `seats_total` reopens it to `OPEN`. Declines, expiries, and rescissions of still-`ISSUED` invitations simply release the hold by decrementing `seats_provisional`. Every change to either counter is a mutation of the opening and increments its `version`.

### 2.8. Optimistic Concurrency Control at Issuance

Exactly one write in the system participates in optimistic concurrency control: the issuance of an invitation. The request must carry `expected_assignment_opening_version`, holding the `version` of the target assignment opening as the issuing officer last observed it. If that value does not match the opening's current `version`, the issuance is rejected with `ERR_STALE_OPENING_VERSION` (HTTP 412).

The rationale is that an issuance decision rests on a read of the opening — its seats, dates, and status. Any mutation since that read, whether another officer's issuance holding a seat, an acceptance committing one, or an administrative edit or cancellation, advances the opening's `version` and invalidates the basis of the decision; the officer must re-read the opening and retry with the fresh version. No other endpoint accepts a version field, and no other resource participates in optimistic concurrency control.

### 2.9. Validation Discipline and Error Precedence

A single request can violate several rules at once, so the system evaluates checks in a fixed priority order and reports only the first failure: authentication (missing or malformed headers, `ERR_UNAUTHENTICATED`); role authorization (`ERR_FORBIDDEN`); applicant ownership (`ERR_NOT_OWNER`); resource existence; optimistic concurrency (`ERR_STALE_OPENING_VERSION`); state-machine guards; compliance gates; business-constraint gates; the temporal gate on service completion; and finally field-shape validation (`ERR_VALIDATION`). A request that fails an earlier check never surfaces a later one — a caller without ownership of an application sees `ERR_NOT_OWNER` even when the payload is also malformed.

Existence checks resolve identifiers left to right: path-template identifiers first, in the order they appear in the URL, then foreign keys supplied in the request body. Each missing resource has its own error: `ERR_APPLICANT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND` (also raised for an unknown program id inside `country_preference_ids`), `ERR_OPENING_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_INTERVIEW_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`, `ERR_MEDICAL_CLEARANCE_NOT_FOUND`, `ERR_LEGAL_CLEARANCE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, and `ERR_PLACEMENT_NOT_FOUND`.

State-machine guards run sixth, each with its dedicated error where one exists — `ERR_INVALID_APPLICATION_STATE` for application transitions attempted from a state that does not offer them, `ERR_OPENING_NOT_OPEN` for issuance against a non-`OPEN` opening or cancellation of a `CLOSED` or `CANCELLED` one, `ERR_INVITATION_NOT_ACTIONABLE` for answering an invitation no longer `ISSUED`, `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` for determining a clearance no longer `SUBMITTED`, `ERR_ENROLLMENT_NOT_ASSESSABLE` for assessment, remediation, or swearing-in attempted from the wrong enrollment state, and `ERR_SERVICE_NOT_ACTIVE` for service-scoped actions against a service that is not `ACTIVE`. Every other machine guard falls to `ERR_INVALID_STATE`: completing or cancelling a non-`SCHEDULED` interview, scheduling an interview for an application not `UNDER_REVIEW`, legal-clearance dimension guards including a suitability determination attempted before the background is adjudicated or against a `VOID` lifecycle, and assessing while the cohort is not `IN_SESSION`.

Compliance gates run seventh — `ERR_CLEARANCES_NOT_CLEARED`, `ERR_SUITABILITY_SELF_APPROVAL`, `ERR_ACCOMMODATION_DETERMINATION_INVALID`, and `ERR_DENTAL_TREATMENT_PENDING`, all HTTP 422 — followed by business-constraint gates eighth and the temporal gate on service completion (`ERR_SERVICE_TERM_NOT_REACHED`) ninth. Field-shape validation runs last and covers missing required fields, unknown enum members, out-of-range numbers, and a window whose end is not strictly after its start, all reported as `ERR_VALIDATION` (HTTP 400). Among the business-constraint errors the status codes differ: `ERR_VALIDATION` on the submit path is a 400; the quota and conflict errors — `ERR_OPENING_NOT_OPEN` on opening creation, `ERR_INTERVIEW_OVERLAP`, `ERR_NO_SEATS_AVAILABLE`, `ERR_DUPLICATE_ACTIVE_CLEARANCE`, `ERR_COHORT_CAPACITY_EXCEEDED`, and `ERR_TRAINING_CAPACITY_EXCEEDED` — carry HTTP 409; and the remaining constraint errors carry 422. The full status mapping appears in §5.

### 2.10. Precision, Rounding, and Time Units

Scores that the system computes — the weighted match score and the interview overall score — are rounded half-up to exactly two decimal places, and any rule that compares such a score compares the rounded value. Money is integer arithmetic: the readjustment ledger works in whole cents, and the penalized allowance rounds each month's amount half-up to a whole cent before any multiplication. Service time counts in whole days and whole months, with months derived from days by the half-month round-up rule of §3.9. Medical support tiers and condition severities are integers. Timestamps are compared at second precision, and deadline checks distinguish strict precedence — an invitation expires only once its acceptance deadline is strictly earlier than the clock — from at-or-before precedence, under which a cohort starts once its `start_date` has been reached or passed.

### 2.11. Cascades and Cross-Aggregate Consistency

Many client actions mutate more than one aggregate, and the system performs every step of a cascade atomically with the triggering request — there is no asynchronous settlement. Five cascade families recur throughout §3: the rescission of an invitation, which releases its seat and returns the application to the matching pool; the withdrawal of an application, which tears down whatever stage the application had reached; a medical or legal denial, which rescinds the accepted invitation and voids the sibling clearance; a training separation, which closes the application and releases the seat; and the close of a service, which writes the completion record and ends every live site placement. Each resource a cascade touches is genuinely mutated — its `updated_at` refreshes and its `version` increments — so a client holding a stale `version` of an opening discovers the drift at the next guarded write.

## 3. Business Logic & Workflows

### 3.1. Setting the Stage: Applicants, Country Programs, and Assignment Openings

A `SystemAdmin` onboards each candidate by registering an applicant profile: `full_name`, a unique `email` (no two applicants may share one), `date_of_birth`, `citizenship_country`, and a `skills` list drawn from the ten-code skill catalog — `TEACHING_ENGLISH`, `MATH_SCIENCE`, `PRIMARY_HEALTH`, `NURSING`, `AGRONOMY`, `FORESTRY`, `SMALL_BUSINESS`, `IT`, `WATER_SANITATION`, and `YOUTH_DEVELOPMENT`. The skills list may be empty, and an optional `languages` list captures free-form languages spoken, defaulting to empty.

Country programs come first in the placement topology. A `SystemAdmin` creates each program with a unique `country_code`, a display `name`, a `medical_support_tier` from 1 (limited in-country medical support) through 2 (moderate) to 3 (full), the `required_language` trainees must demonstrate in pre-service training, a `language_threshold_score` between 1.0 and 5.0 that trainees must reach to swear in, and a `training_capacity` of at least 1 limiting how many overlapping cohort seats the program can host at once. A program is born `OPEN`. The administrator may later patch its `status` along with the `medical_support_tier`, `training_capacity`, and `language_threshold_score`: `OPEN` and `SUSPENDED` alternate freely, and either may move to `CLOSED`, which is terminal. Suspension blocks the creation of new assignment openings while leaving every existing opening and invitation untouched; closure ends the program outright. Every such edit increments the program's `version`, and per §2.6 no edit ever rewrites a pinned invitation snapshot.

Against an `OPEN` program — and only an `OPEN` one, or the attempt fails with `ERR_OPENING_NOT_OPEN` — a `SystemAdmin` publishes an assignment opening: the hosting `country_program_id`, a `sector` from `EDUCATION`, `HEALTH`, `AGRICULTURE`, `ENVIRONMENT`, `YOUTH`, or `COMMUNITY_DEVELOPMENT`, a `title`, the `required_skills` an invitee must fully hold (itself possibly empty), optional `preferred_skills` that never gate eligibility and default to empty, a `seats_total` of at least 1, the planned `departure_date`, and the `invitation_issue_deadline` after which no invitations may be issued. The opening starts `OPEN` with both seat counters at zero, and the openings list can be filtered by `country_program_id`, `status`, or `sector`.

Cancelling an opening is the heaviest administrative action in the system. Available from `OPEN` or `FILLED` — attempting it on a `CLOSED` or `CANCELLED` opening is rejected with `ERR_OPENING_NOT_OPEN` — cancellation moves the opening to `CANCELLED` and fires the full rescission cascade. Every invitation still `ISSUED` becomes `RESCINDED`, releasing its held seat and returning its application from `INVITED` to `UNDER_REVIEW`. Every `ACCEPTED` invitation becomes `RESCINDED`, releasing its committed seat, returning its application from `ACCEPTED` to `UNDER_REVIEW`, voiding that application's in-flight medical clearance (one in `SUBMITTED` or `DEFERRED` becomes `VOID`), and setting that application's legal clearance lifecycle to `VOID`.

### 3.2. The Application: Drafting, Submission, Withdrawal, and Rejection

An applicant journey begins when an `Applicant` creates an application, with `X-User-ID` equal to the payload's `applicant_id`. The draft captures an optional ranked `country_preference_ids` list — rank 1 first, no duplicates, every entry an existing program id or the request fails with `ERR_PROGRAM_NOT_FOUND`, and an empty list meaning the candidate is willing to serve anywhere — an optional `sector_preferences` list drawn from the sector enum, and an optional free-text `statement`, the latter two defaulting to empty. The application is born `DRAFT`; over its life its `status` walks through `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, `EVALUATED`, `INVITED`, `ACCEPTED`, `CLEARED_TO_DEPART`, and `IN_TRAINING` before the terminal `SWORN_IN`, with three other terminal exits along the way: `NOT_SELECTED`, `WITHDRAWN`, and `SEPARATED`.

Submission is the applicant's own act and requires at least one sector preference — submitting a draft whose `sector_preferences` list is empty fails with `ERR_VALIDATION`. Once `SUBMITTED`, a `PlacementOfficer` begins review, moving the application to `UNDER_REVIEW`, and may reject an application from `UNDER_REVIEW` or `EVALUATED`, ending it as `NOT_SELECTED`. State guards reject transitions from the wrong source state: submitting an already-`SUBMITTED` application, or beginning review of a `DRAFT`, fails with `ERR_INVALID_APPLICATION_STATE`. The applications list can be filtered by `applicant_id` or `status`.

Withdrawal is always the applicant's prerogative, but its blast radius grows with the pipeline stage, and only non-terminal states offer it. From `DRAFT`, `SUBMITTED`, or `EVALUATED` it is clean. From `UNDER_REVIEW` or `INTERVIEWING`, any `SCHEDULED` interview of the application is cancelled. From `INVITED`, the outstanding invitation becomes `DECLINED` and its held seat is released. From `ACCEPTED`, the accepted invitation becomes `RESCINDED`, its committed seat is released — reopening the opening from `FILLED` to `OPEN` if the committed count has fallen below `seats_total` — the in-flight medical clearance in `SUBMITTED` or `DEFERRED` becomes `VOID`, and the legal clearance's lifecycle becomes `VOID`. From `CLEARED_TO_DEPART` or `IN_TRAINING`, the invitation is rescinded with the same seat release, and the applicant's training enrollment in `ENROLLED`, `REMEDIATION`, or `FAILED` becomes `SEPARATED`, decrementing the cohort's `enrolled_count`. Every withdrawal ends the application as `WITHDRAWN`.

### 3.3. Interviews: Scheduling, Scoring, and the Evaluation Loop

With an application `UNDER_REVIEW` — scheduling against any other application state fails with `ERR_INVALID_STATE` — a `PlacementOfficer` books an interview by naming the `interviewer_id`, an opaque identifier of the interviewing officer, and a half-open window from `scheduled_start` to `scheduled_end`, where the end must be strictly after the start. Scheduling moves the application from `UNDER_REVIEW` to `INTERVIEWING`, and the new interview is born `SCHEDULED`. One officer's calendar may not double-book: for the same `interviewer_id`, the new window must not overlap any existing `SCHEDULED` interview, where two half-open windows overlap exactly when the new one starts before the existing one ends and the existing one starts before the new one ends. Adjacency is allowed — a window beginning precisely when another ends does not overlap, and neither does one ending precisely when another begins — and a genuine overlap is rejected with `ERR_INTERVIEW_OVERLAP` (HTTP 409). Completed or cancelled interviews no longer constrain the calendar. Note the deliberate contrast with the cohort capacity rule of §3.7: interviews forbid any overlap outright, while cohorts permit overlap up to a summed capacity cap.

Completion is where evaluation happens. Against a `SCHEDULED` interview — completing or cancelling a non-`SCHEDULED` one fails with `ERR_INVALID_STATE` — the officer records four dimension scores, `motivation_score`, `adaptability_score`, `skill_competency_score`, and `cross_cultural_score`, each between 1.0 and 5.0 or the request fails with `ERR_VALIDATION`. The system then computes the interview's `overall_score` as thirty per cent of the motivation score, plus twenty-five per cent each of the adaptability and skill-competency scores, plus twenty per cent of the cross-cultural score, rounding the weighted sum half-up to two decimal places. The `recommendation` is derived in a fixed order: round first, then apply the minimum-dimension cap, then tier. If the lowest of the four dimension scores falls below 2.0, the recommendation is `NOT_RECOMMENDED` regardless of the weighted sum. Otherwise an `overall_score` of at least 4.0 earns `STRONGLY_RECOMMEND`, at least 3.0 earns `RECOMMEND`, at least 2.5 earns `NEUTRAL`, and anything below that earns `NOT_RECOMMENDED`. Completing the interview moves the application from `INTERVIEWING` to `EVALUATED`.

Cancellation closes the loop. Cancelling a `SCHEDULED` interview moves it to `CANCELLED`, and if no other `SCHEDULED` interview remains for the application, the application reverts from `INTERVIEWING` to `UNDER_REVIEW`, free to be interviewed again. `COMPLETED` and `CANCELLED` are both terminal for the interview itself.

### 3.4. Matching, Invitation Issuance, and the Applicant's Answer

Once an application has left `DRAFT`, its match list becomes readable by a `PlacementOfficer` or by the owning applicant (ownership per §2.1). The list is a selector over every assignment opening in the system: an opening is a candidate when it is `OPEN`, its `invitation_issue_deadline` has not passed — which the sweep of §2.4 guarantees for every `OPEN` opening — its held plus committed seats remain strictly below `seats_total`, the applicant's strict skill coverage of it is exactly 1.0, and the applicant's country preferences are either empty or contain the opening's program. An empty candidate set is not an error: the response is a 200 whose `matches` array is simply empty.

Each element of `matches` carries `assignment_opening_id`, `country_program_id`, `sector`, `departure_date`, the `strict_score`, and the `weighted_score`. Strict coverage is the fraction of the opening's `required_skills` that the applicant's `skills` list covers — the number of skills appearing in both lists divided by the number of required skills, with an empty requirements list defined as exactly 1.0. The weighted score blends in preference signals: seven-tenths of the strict coverage, plus two-tenths of a sector bonus that is 1.0 when the opening's `sector` appears among the application's `sector_preferences` and 0.0 otherwise, plus one-tenth of a country bonus, the sum rounded half-up to two decimal places. The country bonus rewards ranked preference: an empty preference list earns one-half, reflecting willingness to serve anywhere; a program ranked first earns 1.0, and each step down the ranking deducts one-quarter — 0.75 for the second choice, 0.5 for the third, 0.25 for the fourth — and a program absent from a non-empty list earns nothing. Candidates are ranked by `weighted_score` descending, then by `departure_date` ascending, then by the opening's `created_at` ascending.

Issuance is the `PlacementOfficer`'s binding offer, and the request names the `application_id`, the `assignment_opening_id`, and — per §2.8 — the `expected_assignment_opening_version`. The application must be `EVALUATED`, failing with `ERR_INVALID_APPLICATION_STATE` from any other state, and five business gates then apply: the opening must be `OPEN` (`ERR_OPENING_NOT_OPEN`); the applicant's strict coverage of its required skills must be exactly 1.0 (`ERR_SKILL_REQUIREMENTS_NOT_MET`); the application's latest completed interview must carry a `RECOMMEND` or `STRONGLY_RECOMMEND` recommendation (`ERR_RECOMMENDATION_INSUFFICIENT`); the opening's program must be compatible with the applicant's country preferences — automatic when the list is empty, otherwise the program must appear in it (`ERR_PREFERENCE_MISMATCH`); and a seat must remain (`ERR_NO_SEATS_AVAILABLE`). A successful issuance creates the invitation in `ISSUED` with `issued_at` read from the logical clock, the `acceptance_deadline` set ten days later, the pinned snapshots of §2.6 recorded, and `issued_by` set to the issuing officer's `X-User-ID`; the opening's `seats_provisional` increments, advancing its `version`; and the application moves from `EVALUATED` to `INVITED`. The invitations list can be filtered by `application_id`, `assignment_opening_id`, or `status`.

The applicant answers. Acceptance — possible only while the invitation is `ISSUED`, and otherwise rejected with `ERR_INVITATION_NOT_ACTIONABLE` — moves it to `ACCEPTED`, converts the held seat into a committed one (decrementing `seats_provisional`, incrementing `seats_committed`, and marking the opening `FILLED` when the committed count reaches `seats_total`), moves the application from `INVITED` to `ACCEPTED`, and auto-creates the application's legal clearance with both dimensions `PENDING` and lifecycle `ACTIVE`. Decline moves the invitation to `DECLINED`, releases the held seat, and returns the application from `INVITED` to `UNDER_REVIEW` — the re-matching loop, in which the application may be interviewed again or invited to another opening. Expiry (§2.4) and rescission of an `ISSUED` invitation (§3.1) have the same shape: the invitation becomes `EXPIRED` or `RESCINDED`, the hold is released, and the application returns to `UNDER_REVIEW`. A rescission of an `ACCEPTED` invitation — fired by medical denial, legal denial, opening cancellation, or withdrawal — instead decrements `seats_committed`, reopens a `FILLED` opening whose committed count has fallen below `seats_total`, and returns the application from `ACCEPTED` to `UNDER_REVIEW`. `ACCEPTED`, `DECLINED`, `EXPIRED`, and `RESCINDED` are all terminal for the invitation.

### 3.5. Medical Clearance: Declared Conditions Against a Pinned Tier

Once an application is `ACCEPTED`, the applicant files medical and dental forms. Creation requires the application to be `ACCEPTED` — otherwise `ERR_INVALID_APPLICATION_STATE` — and forbids a second active clearance: if a medical clearance in `SUBMITTED` or `DEFERRED` already exists for the application, the attempt fails with `ERR_DUPLICATE_ACTIVE_CLEARANCE` (HTTP 409). The filing carries the `application_id`, a `conditions` list in which each entry names a `condition_code`, a `severity` from 1 to 3, and a `required_support_tier` from 1 to 3 — an empty list declaring no conditions — and a `dental_status` of `CLEAR` or `NEEDS_TREATMENT`. The clearance is born `SUBMITTED`, with `deferral_count` at zero and `reviewed_by` null until the first determination. An application's clearances are listed per application.

Every clearance is measured against the pinned tier, never the live one: the clearance's `max_tier_gap` is the largest amount by which any declared condition's `required_support_tier` exceeds the `pinned_country_medical_tier` of the application's accepted invitation, or zero when no conditions are declared or none exceeds the pinned tier. The gap is computed at creation and recomputed at every resubmission, and it constrains which determinations a `MedicalOfficer` may reach — even if the country program's live `medical_support_tier` has changed since issuance, the review never consults it.

Determination acts only on a `SUBMITTED` clearance — anything else fails with `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` — and records the acting officer's `X-User-ID` in `reviewed_by`. The request names a `determination` and may carry `accommodation_granted`. Admissibility is a function of the gap. With no positive gap, the officer may reach `CLEARED`, `DENIED`, or `DEFERRED`. With a gap of exactly one, the admissible outcomes are `CLEARED_WITH_ACCOMMODATION` — which additionally requires `accommodation_granted` to be true in the request — `DENIED`, or `DEFERRED`. With a gap of two or more, only `DENIED` or `DEFERRED` remain. Any inadmissible pairing is rejected with `ERR_ACCOMMODATION_DETERMINATION_INVALID` (HTTP 422): an accommodation outcome without a gap of exactly one, an accommodation outcome without the grant flag, or a cleared outcome the gap forbids. Independently, a `dental_status` of `NEEDS_TREATMENT` forbids both cleared outcomes and surfaces `ERR_DENTAL_TREATMENT_PENDING` (HTTP 422). Deferral is rationed as well: a `DEFERRED` determination requires the clearance's `deferral_count` to still be below two, otherwise `ERR_MAX_DEFERRALS_REACHED` (HTTP 422).

A `DENIED` determination fires the full denial cascade: the application's accepted invitation becomes `RESCINDED`; that rescission returns the application from `ACCEPTED` to `UNDER_REVIEW` and releases the committed seat, reopening the opening from `FILLED` to `OPEN` if the committed count has fallen below `seats_total`; and the application's legal clearance lifecycle becomes `VOID`. A deferral, by contrast, keeps the file alive: the applicant may resubmit a `DEFERRED` clearance — resubmitting from any other clearance state violates the state guard (HTTP 409), and the application must remain `ACCEPTED` or the request fails with `ERR_INVALID_APPLICATION_STATE` — supplying fresh `conditions` and `dental_status`, which replace the previous filing wholesale. Resubmission increments `deferral_count`, recomputes `max_tier_gap`, and returns the clearance to `SUBMITTED`. Withdrawal or opening cancellation voids any clearance still in `SUBMITTED` or `DEFERRED`, and `CLEARED`, `CLEARED_WITH_ACCOMMODATION`, `DENIED`, and `VOID` are all terminal.

### 3.6. Legal Clearance: Two Dimensions, Two Reviewers

Acceptance of an invitation auto-creates the application's legal clearance, discoverable through the application's legal-clearances listing. The clearance carries two independent dimensions that evolve in parallel: `background_check_status` — `PENDING`, `CLEAR`, or `ADVERSE`, with `background_adjudicated_by` null while pending — and `suitability_status` — `PENDING`, `FAVORABLE`, or `UNFAVORABLE`, with `suitability_decided_by` recording its decider. A derived `overall_status` summarizes the pair: `VOID` when the clearance's `lifecycle` is `VOID`; otherwise `DENIED` when the background is `ADVERSE` or the suitability `UNFAVORABLE`; otherwise `CLEARED` when the background is `CLEAR` and the suitability `FAVORABLE`; otherwise still `PENDING`.

A `LegalReviewer` adjudicates the background check by supplying an `outcome`. The act requires the background dimension still `PENDING` and the lifecycle still `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise, and records the reviewer's `X-User-ID` as `background_adjudicated_by`. An outcome of `CLEAR` simply marks the dimension. An outcome of `ADVERSE` fires the same denial cascade a medical denial fires: the accepted invitation is rescinded, the application returns from `ACCEPTED` to `UNDER_REVIEW`, the committed seat is released with a `FILLED` opening reopening below `seats_total`, and — additionally — the application's in-flight medical clearance, if one sits in `SUBMITTED` or `DEFERRED`, becomes `VOID`.

Suitability comes second and under different hands. The determination, again keyed by an `outcome`, requires the suitability dimension still `PENDING`, the lifecycle still `ACTIVE`, and the background already adjudicated — determining suitability while the background is still `PENDING` fails with `ERR_INVALID_STATE`. Segregation of duties forbids the same officer from holding both pens: when the caller's `X-User-ID` equals the clearance's `background_adjudicated_by`, the attempt is rejected with `ERR_SUITABILITY_SELF_APPROVAL` (HTTP 422). A `FAVORABLE` outcome with a `CLEAR` background completes the clearance, `overall_status` becoming `CLEARED`, while an `UNFAVORABLE` outcome denies it and fires the identical denial cascade, voiding any in-flight medical clearance on the way out. The lifecycle itself becomes `VOID` whenever the parent application leaves the clearance pipeline — withdrawal, a rescission cascade, or a denial — freezing both dimensions where they stand.

### 3.7. Pre-Service Training: Cohorts, Enrollment, and Assessment

A `SystemAdmin` stands up a pre-service training cohort with its `country_program_id`, a `name`, a half-open training window from `start_date` to `end_date` — the end strictly after the start — and a `capacity` of at least 1. The cohort is born `SCHEDULED` with `enrolled_count` at zero. Cohorts of the same program may overlap in time, but only up to a budget: the new cohort's `capacity` plus the summed capacities of all overlapping cohorts of that program in `SCHEDULED` or `IN_SESSION` must not exceed the program's `training_capacity`, or creation fails with `ERR_TRAINING_CAPACITY_EXCEEDED` (HTTP 409). Two half-open windows overlap exactly when each starts before the other ends, so cohorts that merely touch — one ending the instant another begins — do not count against each other. This aggregate-capacity rule is the deliberate counterpart of the interview rule in §3.3: interviews exclude one another absolutely, while cohorts share a budget. The cohorts list can be filtered by `country_program_id` or `status`.

The clock sweep of §2.4 advances cohorts without any client action: a `SCHEDULED` cohort becomes `IN_SESSION` once its `start_date` is reached, moving each enrolled trainee's application from `CLEARED_TO_DEPART` to `IN_TRAINING`, and an `IN_SESSION` cohort becomes `CONCLUDED` once its `end_date` is reached.

Enrollment is the gate into training, performed by a `PlacementOfficer` naming the `application_id` and the `training_cohort_id`. The application must be `ACCEPTED` (`ERR_INVALID_APPLICATION_STATE` otherwise) and fully cleared — its medical clearance `CLEARED` or `CLEARED_WITH_ACCOMMODATION` and its legal clearance's `overall_status` `CLEARED`, otherwise `ERR_CLEARANCES_NOT_CLEARED` (HTTP 422). The cohort must belong to the invitation's `pinned_country_program_id` (`ERR_COHORT_PROGRAM_MISMATCH`, HTTP 422), must have `enrolled_count` still strictly below `capacity` (`ERR_COHORT_CAPACITY_EXCEEDED`, HTTP 409), and must still be `SCHEDULED`. Success creates the enrollment in `ENROLLED` with `assessment_attempts` at zero and all three component scores unset, increments the cohort's `enrolled_count`, and moves the application from `ACCEPTED` to `CLEARED_TO_DEPART`. The enrollments list can be filtered by `application_id`, `training_cohort_id`, or `status`.

Assessment belongs to the `TrainingDirector` and to a live classroom: it requires the cohort `IN_SESSION` (`ERR_INVALID_STATE` otherwise) and the enrollment `ENROLLED` or `REMEDIATION` (`ERR_ENROLLMENT_NOT_ASSESSABLE` otherwise). Each assessment records `language_score`, `technical_score`, and `cultural_score` — each between 1.0 and 5.0 — and increments `assessment_attempts`. Passing requires the language score to meet or exceed the cohort program's `language_threshold_score` and both the technical and cultural scores to reach at least 2.5; any component short of its threshold fails the attempt. From `ENROLLED`, a pass promotes the enrollment to `PASSED` and a fail drops it to `FAILED`. A `FAILED` enrollment may be moved into `REMEDIATION` — remediation from any other state fails with `ERR_ENROLLMENT_NOT_ASSESSABLE` — which grants a second and final attempt: a pass from `REMEDIATION` promotes to `PASSED`, while a second consecutive failed assessment separates the trainee. Separation moves the enrollment to `SEPARATED` and the application to `SEPARATED` (terminal), rescinds the accepted invitation with the usual seat release and `FILLED`-to-`OPEN` reopening, and decrements the cohort's `enrolled_count`.

Swearing in is the terminal triumph. A `TrainingDirector` swears in a `PASSED` enrollment — any other state fails with `ERR_ENROLLMENT_NOT_ASSESSABLE` — which creates the volunteer's service record: `service_start_date` read from the logical clock, `expected_completion_date` exactly 810 days later, status `ACTIVE`, and `application_id`, `assignment_opening_id`, and `country_program_id` copied from the accepted invitation and its pinned program. The same act advances the application from `IN_TRAINING` to `SWORN_IN`, its terminal state.

### 3.8. In-Country Service: Placements, Events, and the Close of Service

With the volunteer sworn in, a `CountryDirector` proposes a site placement for the `ACTIVE` service — a service in any other state rejects the proposal with `ERR_SERVICE_NOT_ACTIVE` — naming the `host_community_name` and the `counterpart_org_name`. The placement's `volunteer_service_id` binds it to the service it serves. It is born `PROPOSED`, with `counterpart_agreement_signed`, `has_running_water`, `structurally_sound`, and `secure_locks` all false and `inspection_passed` — the conjunction of the three housing flags — likewise false.

Review is a loop, not a gate: from `PROPOSED` or from `REJECTED`, the director records the four flags and a `decision`, while reviewing a placement that has reached `CONFIRMED` or `ENDED` fails with `ERR_INVALID_STATE`. The service must still be `ACTIVE` (`ERR_SERVICE_NOT_ACTIVE`). A `CONFIRM` decision additionally requires `counterpart_agreement_signed` to be true (`ERR_AGREEMENT_NOT_SIGNED`, HTTP 422) and all three housing standards — running water, structural soundness, and secure locks — to be true (`ERR_HOUSING_STANDARDS_NOT_MET`, HTTP 422), and lands the placement in `CONFIRMED`; a `REJECT` decision lands it in `REJECTED`, from which a later review may still confirm it. Every review records the flag values afresh and recomputes `inspection_passed`. When the service eventually closes, every placement in `PROPOSED`, `CONFIRMED`, or `REJECTED` becomes `ENDED`.

Life in country is narrated through the service-event log. A `CountryDirector` may log any event; a `MedicalOfficer` may log only `MEDICAL_CARE` events, any other event type from that role lying outside its grant and rejected with `ERR_FORBIDDEN`. Each entry's `volunteer_service_id` ties it to its service, and it carries an `event_type` of `MEDICAL_CARE`, `SAFETY_INCIDENT`, `SECURITY_ALERT`, `ALL_CLEAR`, or `COMMENDATION`, a `severity` of `ROUTINE`, `URGENT`, or `CRITICAL`, a free-text `description`, and the `occurred_at` instant. Entries are immutable once written (§2.5), and the log lists chronologically by `occurred_at` with `created_at` ascending as the tie-break. Two event types move the service itself: a `SECURITY_ALERT` at `CRITICAL` severity suspends an `ACTIVE` service into `SUSPENDED` under the evacuation protocol, and an `ALL_CLEAR` returns a `SUSPENDED` service to `ACTIVE`. The services list can be filtered by `application_id`, `assignment_opening_id`, `country_program_id`, or `status`.

Closing a service is the `CountryDirector`'s final act, and it comes in two shapes. Completion is available only while the service is `ACTIVE` (`ERR_SERVICE_NOT_ACTIVE`) and only once the logical clock has reached the `expected_completion_date` — earlier attempts fail with `ERR_SERVICE_TERM_NOT_REACHED` (HTTP 422). Early termination is available from `ACTIVE` or `SUSPENDED` — from any other state, `ERR_SERVICE_NOT_ACTIVE` — and names a `reason` of `MEDICAL`, `FAMILY`, `SECURITY`, or `ADMINISTRATIVE`. Both paths stamp `actual_end_date` from the logical clock, compute `days_served` as the whole days between `service_start_date` and that end, derive `months_served`, end every live site placement, and write exactly one completion record for the service: `completion_type` `FULL` with `et_reason` null on completion, or `EARLY` with `et_reason` taken from the request's `reason`. Every completion record points back to its service through `volunteer_service_id`, exactly one record exists per service, and the completion-record read returns an array of zero or one entries. `COMPLETED` and `EARLY_TERMINATED` are terminal for the service.

### 3.9. Readjustment Allowance and Non-Competitive Eligibility

The completion record is also the volunteer's settlement statement, and its arithmetic is fixed. Service converts to months by a half-month round-up: `months_served` is the whole days served plus fifteen, divided by thirty, rounded down — so the forty-fourth day of service still counts as one month while the forty-fifth counts as two. The record copies this `months_served` from the service at close. Gross accrual is months times the standard monthly rate of 47,500 cents: `gross_accrued_cents` equals `months_served` multiplied by 47,500, regardless of how the service ended.

What is actually paid depends on the variant. A `FULL` completion pays the standard accrual in full. An `EARLY` termination with at least 18 months served also pays in full — length of service, not the label, earns the standard treatment. An `EARLY` termination with fewer than 18 months is penalized: each served month pays two-thirds of the standard rate, with that per-month amount rounded half-up to a whole cent before being multiplied by the number of months. The rounding order is pinned — round the month first, then multiply — so the penalized month is exactly 31,667 cents, and three penalized months pay 95,001 cents rather than the 95,000 that rounding the total instead would produce. The withheld third is the `allowance_forfeited_cents`, which always equals `gross_accrued_cents` minus `allowance_paid_cents`, so paid plus forfeited conserves the gross.

Non-competitive eligibility for federal employment rides on the same record. `nce_eligible` is true exactly when at least 12 months were served and either the completion is `FULL` or the early-termination reason is `MEDICAL`; `nce_duration_months` is 12 when eligible and 0 otherwise.

## 4. Endpoint Definitions

Operations that create a new resource — an applicant, a program, an opening, an application, an interview, an invitation, a medical clearance, a cohort, an enrollment, a service event, or a site placement — return `201 Created`. Operations that modify an existing resource, including all state transitions, reviews, determinations, and clock advances, return `200 OK`. Request payloads, side effects, and cascades are defined by the workflows of §3; this table is a locator, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/volunteer-portal/applicants` | Register an applicant | SystemAdmin |
| POST | `/volunteer-portal/country-programs` | Create a country program | SystemAdmin |
| GET | `/volunteer-portal/country-programs/{id}` | Get a country program | All roles |
| PATCH | `/volunteer-portal/country-programs/{id}` | Update a program's status, medical tier, capacity, or language threshold | SystemAdmin |
| POST | `/volunteer-portal/assignment-openings` | Create an assignment opening | SystemAdmin |
| GET | `/volunteer-portal/assignment-openings/{id}` | Get an assignment opening | All roles |
| GET | `/volunteer-portal/assignment-openings` | List assignment openings with optional filters | All roles |
| POST | `/volunteer-portal/assignment-openings/{id}/cancel` | Cancel an opening and fire the rescission cascade | SystemAdmin |
| POST | `/volunteer-portal/applications` | Create an application in DRAFT | Applicant |
| GET | `/volunteer-portal/applications/{id}` | Get an application | All roles |
| GET | `/volunteer-portal/applications` | List applications with optional filters | All roles |
| POST | `/volunteer-portal/applications/{id}/submit` | Submit a draft application | Applicant |
| POST | `/volunteer-portal/applications/{id}/withdraw` | Withdraw a non-terminal application | Applicant |
| POST | `/volunteer-portal/applications/{id}/begin-review` | Move a submitted application into review | PlacementOfficer |
| POST | `/volunteer-portal/applications/{id}/reject` | Reject an application as not selected | PlacementOfficer |
| GET | `/volunteer-portal/applications/{id}/matches` | List eligible openings ranked for the application | PlacementOfficer, Applicant |
| POST | `/volunteer-portal/applications/{id}/interviews` | Schedule an interview | PlacementOfficer |
| GET | `/volunteer-portal/applications/{id}/interviews` | List interviews of an application | All roles |
| POST | `/volunteer-portal/interviews/{id}/complete` | Record dimension scores and complete an interview | PlacementOfficer |
| POST | `/volunteer-portal/interviews/{id}/cancel` | Cancel a scheduled interview | PlacementOfficer |
| POST | `/volunteer-portal/invitations` | Issue an invitation against an opening | PlacementOfficer |
| GET | `/volunteer-portal/invitations/{id}` | Get an invitation | All roles |
| GET | `/volunteer-portal/invitations` | List invitations with optional filters | All roles |
| POST | `/volunteer-portal/invitations/{id}/accept` | Accept an issued invitation | Applicant |
| POST | `/volunteer-portal/invitations/{id}/decline` | Decline an issued invitation | Applicant |
| POST | `/volunteer-portal/medical-clearances` | Submit medical and dental forms | Applicant |
| GET | `/volunteer-portal/applications/{id}/medical-clearances` | List medical clearances of an application | All roles |
| POST | `/volunteer-portal/medical-clearances/{id}/determine` | Render a medical determination | MedicalOfficer |
| POST | `/volunteer-portal/medical-clearances/{id}/resubmit` | Resubmit a deferred clearance | Applicant |
| GET | `/volunteer-portal/applications/{id}/legal-clearances` | List legal clearances of an application | All roles |
| POST | `/volunteer-portal/legal-clearances/{id}/adjudicate-background` | Adjudicate the background check | LegalReviewer |
| POST | `/volunteer-portal/legal-clearances/{id}/determine-suitability` | Determine suitability | LegalReviewer |
| POST | `/volunteer-portal/training-cohorts` | Create a training cohort | SystemAdmin |
| GET | `/volunteer-portal/training-cohorts/{id}` | Get a training cohort | All roles |
| GET | `/volunteer-portal/training-cohorts` | List training cohorts with optional filters | All roles |
| POST | `/volunteer-portal/training-enrollments` | Enroll a cleared application into a cohort | PlacementOfficer |
| GET | `/volunteer-portal/training-enrollments/{id}` | Get a training enrollment | All roles |
| GET | `/volunteer-portal/training-enrollments` | List training enrollments with optional filters | All roles |
| POST | `/volunteer-portal/training-enrollments/{id}/assess` | Record a training assessment | TrainingDirector |
| POST | `/volunteer-portal/training-enrollments/{id}/remediate` | Move a failed enrollment into remediation | TrainingDirector |
| POST | `/volunteer-portal/training-enrollments/{id}/swear-in` | Swear in a passed trainee | TrainingDirector |
| GET | `/volunteer-portal/volunteer-services/{id}` | Get a volunteer service record | All roles |
| GET | `/volunteer-portal/volunteer-services` | List volunteer services with optional filters | All roles |
| POST | `/volunteer-portal/volunteer-services/{id}/events` | Append a service event | CountryDirector, MedicalOfficer |
| GET | `/volunteer-portal/volunteer-services/{id}/events` | List service events of a service | All roles |
| POST | `/volunteer-portal/volunteer-services/{id}/early-terminate` | Early-terminate a service | CountryDirector |
| POST | `/volunteer-portal/volunteer-services/{id}/complete` | Complete a service at term | CountryDirector |
| GET | `/volunteer-portal/volunteer-services/{id}/completion-record` | Get the completion record of a service | All roles |
| POST | `/volunteer-portal/volunteer-services/{id}/site-placements` | Propose a site placement | CountryDirector |
| GET | `/volunteer-portal/volunteer-services/{id}/site-placements` | List site placements of a service | All roles |
| POST | `/volunteer-portal/site-placements/{id}/review` | Review a site placement | CountryDirector |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the sweep | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_OPENING_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INTERVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVITATION_NOT_FOUND` | 404 Not Found |
| `ERR_MEDICAL_CLEARANCE_NOT_FOUND` | 404 Not Found |
| `ERR_LEGAL_CLEARANCE_NOT_FOUND` | 404 Not Found |
| `ERR_COHORT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_NOT_FOUND` | 404 Not Found |
| `ERR_PLACEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_OPENING_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_APPLICATION_STATE` | 409 Conflict |
| `ERR_OPENING_NOT_OPEN` | 409 Conflict |
| `ERR_INVITATION_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MEDICAL_CLEARANCE_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ASSESSABLE` | 409 Conflict |
| `ERR_SERVICE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLEARANCES_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_SUITABILITY_SELF_APPROVAL` | 422 Unprocessable Entity |
| `ERR_ACCOMMODATION_DETERMINATION_INVALID` | 422 Unprocessable Entity |
| `ERR_DENTAL_TREATMENT_PENDING` | 422 Unprocessable Entity |
| `ERR_NO_SEATS_AVAILABLE` | 409 Conflict |
| `ERR_SKILL_REQUIREMENTS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_RECOMMENDATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PREFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INTERVIEW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CLEARANCE` | 409 Conflict |
| `ERR_MAX_DEFERRALS_REACHED` | 422 Unprocessable Entity |
| `ERR_COHORT_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COHORT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_TRAINING_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SIGNED` | 422 Unprocessable Entity |
| `ERR_HOUSING_STANDARDS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SERVICE_TERM_NOT_REACHED` | 422 Unprocessable Entity |
