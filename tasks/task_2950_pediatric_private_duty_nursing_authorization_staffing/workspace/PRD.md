# Pediatric PDN Authorization Staffing API — Product Requirements Document

## 1. Introduction

Pediatric private-duty nursing sits at the intersection of two systems that rarely agree with each other. On one side a payer writes a finite weekly hour grant against a physician's plan of care; on the other side a staffing office must convert that grant into concrete overnight and daytime shifts, filled by nurses whose licences, competencies and contractual weekly ceilings all constrain who may walk into a medically fragile child's bedroom. The gap between "authorized" and "actually staffed" is where families are failed: an unfilled trach shift at 22:00 is not a scheduling inconvenience, it is a clinical event, and an hour billed without electronic visit verification is a compliance exposure that surfaces months later as a denied claim.

This document specifies the API that Aveanna Healthcare's authorization and staffing platform exposes to close that gap. The API owns the complete chain — payer enrolment, patient enrolment with acuity flags, plan-of-care drafting and submission, payer authorization with hours-per-week approval, renewal and supersession, hour-reduction notices and the appeals that contest them, nurse competency attestation and revocation, shift publication, manual and automatic staffing with continuity preference, escalation and parent-backup fallbacks, supervisory-visit cadence enforcement, incident and hospitalization reporting with case hold, and finally timesheet capture with electronic visit verification (EVV) and payer billing edits. Every quantity that a human would argue about — how many hours are committed this week, which nurse the selector picks, how many billable units a 250-minute visit yields under a strict billing ruleset — is defined here as a deterministic computation.

Two design commitments run through the whole specification and should be read as non-negotiable. First, **time is a server-controlled logical clock**, not the wall clock: every window, expiry, cadence and escalation reads the same injectable instant so that the platform's behaviour is reproducible. Second, **authorized hours are a quota that is never silently overspent** — the system would rather reject a staffing request, cancel a future shift, or refuse a renewal than let committed minutes drift past the grant a payer signed.

## 2. Global Specifications & System-Wide Principles

Everything in this section applies across the API surface. Where a rule below conflicts with a narrative reading of Section 3, this section wins; where Section 3 supplies a number or an ordering that this section only gestures at, Section 3 is the detail.

The entire API is mounted under the `/pdn` path prefix.

### 2.1. User and Role-Based Access Control

Every request — including reads — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent or empty, the request fails with `ERR_MISSING_AUTH_HEADER` (HTTP 401); this check precedes every other check in the system. If the supplied role is not one of the six recognised roles, or is a recognised role that the target operation does not permit, the request fails with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The six roles are `AgencyAdmin`, `PayerReviewer`, `CaseManager`, `Scheduler`, `ClinicalSupervisor`, and `Nurse`.

- An `AgencyAdmin` is the agency's operations administrator. They maintain payers, the nurse roster and the nurse-status controls, and they alone drive the logical clock and the daily checkpoint.
- A `PayerReviewer` is a payer-side utilization reviewer: they issue authorizations against submitted plans of care, activate, reduce, renew and supersede them, return plans of care for revision, take disputes under review and decide them, and rule on timesheet billing.
- A `CaseManager` is the agency's case manager: they enrol patients, draft and submit plans of care, open, activate and close cases, and file authorization disputes.
- A `Scheduler` is the staffing coordinator: they publish shifts, assign and cancel nurses, escalate unfilled shifts, arrange parent backup, and submit or void timesheets.
- A `ClinicalSupervisor` is a registered-nurse supervisor: they attest and revoke nurse competencies, record supervisory visits, file and close incident reports, and hold or resume cases.
- A `Nurse` is a field nurse: they perform EVV clock-in and clock-out and correct their own timesheet.

Two of the six roles are **entity-backed**, meaning `X-User-ID` is the identifier of a persisted row and ownership is checked against it:

- When `X-User-Role` is `PayerReviewer`, `X-User-ID` is the `id` of the acting `Payer`. Ownership checks compare the `payer_id` of the `Authorization` in scope against `X-User-ID`, reaching that authorization directly for authorization operations or through the dispute, or through the timesheet's shift, its case and that case's authorization, for billing and plan-of-care operations. A mismatch is rejected with `ERR_PAYER_SCOPE_VIOLATION` (HTTP 403). This scope check guards nine operations: creating an authorization, activating one, noticing a reduction, applying a noticed reduction, renewing, taking a dispute under review, deciding a dispute, recording a billing decision on a timesheet, and returning a plan of care. The reviewer's identifier is also recorded as `reviewer_user_id` when a dispute moves under review.
- When `X-User-Role` is `Nurse`, `X-User-ID` is the `id` of the acting `Nurse` row. Ownership checks compare it against the `nurse_id` of the shift's `ACTIVE` `ShiftAssignment`; a nurse who clocks in, clocks out or corrects a timesheet that is not theirs is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The remaining four roles — `AgencyAdmin`, `CaseManager`, `Scheduler`, and `ClinicalSupervisor` — have **opaque** identity: `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared against any row's `id`. The server does record these identifiers where a workflow calls for an audit trail: a `ClinicalSupervisor`'s identifier is stored as `validated_by_user_id` on an attested competency, as `supervisor_user_id` on a recorded supervisory visit, as `reported_by_user_id` on a filed incident report, and is supplied by a `CaseManager` as `assigned_supervisor_user_id` when a case is opened; a `CaseManager`'s identifier is stored as `filed_by_user_id` on a dispute; a `Scheduler`'s identifier is stored as `submitted_by_user_id` on a submitted timesheet. Nothing is recorded for an `AgencyAdmin`.

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

List endpoints are paginated through two query-string arguments. `limit` caps the number of rows returned; when it is omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows to skip and defaults to 0; its minimum accepted value is 0. A `limit` outside the range from 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order.

Both paginated and unpaginated list responses expose `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope described in Section 2.2.

### 2.4. Common Resource Properties, Versions and Audit Fields

Every persisted resource in this system carries a server-minted `id` formatted as a UUID with no type prefix — no `case_`, `shift_` or similar decoration — and a `created_at` timestamp rendered as an ISO 8601 UTC instant with exactly three fractional digits, for example `2026-08-01T00:00:00.000Z`.

Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row. Resources with `updated_at` and `version` are: `Payer`, `Patient`, `PlanOfCare`, `Authorization`, `Nurse`, `NurseCompetency`, `Case`, `Shift`, `ShiftAssignment`, `Timesheet`, `IncidentReport`, and `AuthorizationDispute`.

`SupervisoryVisit` is the single exception. A supervisory visit is an immutable clinical record: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a supervisory visit's representation entirely.

Recomputation of a derived field counts as a mutation of the row that owns it. When a staffing action changes a case's `fill_rate`, or an accepted billing decision changes a case's `billed_units_to_date`, the case's `updated_at` is refreshed and its `version` increments. Where a cascade touches several rows, each touched row independently gets its own `updated_at` refresh and `version` increment.

### 2.5. The Logical Clock and Temporal Semantics

Nothing in this system reads the wall clock. All temporal reasoning — authorization effective windows, licence and competency expiry, supervisory cadence, escalation timestamps, EVV tolerances, the trim of over-cap shifts, and every weekly aggregation window — reads a single server-held **logical clock**. Before any client moves it, the logical clock reads `2026-08-01T00:00:00Z`. An `AgencyAdmin` may reposition it to any instant by supplying `to_iso8601`; the response reports the new value as `current_utc`. Repositioning the clock mutates no business entity — only the clock moves. The clock may be moved backwards as freely as forwards.

Two interval conventions are used consistently and should be assumed everywhere unless a rule explicitly says otherwise:

- A shift occupies the **half-open** interval from `start_at` inclusive to `end_at` exclusive. An authorization's grant likewise runs from `effective_start` inclusive to `effective_end` exclusive.
- An **ISO week window** is the seven-day half-open interval that begins at Monday 00:00:00.000Z of the ISO-8601 week containing a reference instant and ends seven days later. "The current week" always means the ISO week window containing the current value of the logical clock. Weekly aggregates are keyed on a shift's `start_at` falling inside such a window — never on a timesheet's `clock_in_at`.

Dates supplied as date-only values — `date_of_birth`, `start_date`, `end_date`, `license_expires_on`, `validated_on`, `expires_on` — are `YYYY-MM-DD` strings, and when they are compared against the logical clock or against a shift boundary the comparison is made against the date part of that instant.

### 2.6. Optimistic Concurrency Control

Two write operations in this API are guarded by optimistic concurrency against a *parent* row's `version`. In both cases the concurrency field is a required, non-optional element of the request body, and in both cases the operation is a legitimate product action that cannot be blocked on state alone — which is precisely why the version guard exists.

**Creating an authorization** requires `expected_plan_of_care_version` carrying the client's last observed `version` of the target `PlanOfCare`. Writing a second authorization against the same plan of care is a legitimate operation — it supersedes the earlier `PENDING` grant and drives the plan through `UNDER_REVIEW` again — so state alone cannot distinguish a deliberate re-issue from a reviewer whose view of the approval history is out of date. If `expected_plan_of_care_version` does not equal the plan of care's current `version`, the create is rejected with `ERR_STALE_PLAN_OF_CARE_VERSION` (HTTP 412) and nothing is written.

**Creating a shift assignment**, whether by naming a nurse explicitly or by invoking the automatic selector, requires `expected_shift_version` carrying the client's last observed `version` of the target `Shift`. Assigning a nurse to an already `ASSIGNED` shift is a legitimate continuity swap — the incumbent assignment is cancelled with `cancel_reason` `REPLACED` — so, again, shift state cannot identify the stale writer. If `expected_shift_version` does not equal the shift's current `version`, the request is rejected with `ERR_STALE_SHIFT_VERSION` (HTTP 412), and no assignment row, no version bump and no side effect of any kind is produced. Since escalation, parent-backup, clock-in and clock-out all increment `Shift.version`, a scheduler who has not seen those events will be caught here.

No other endpoint in this API accepts a version field. In particular, holding a case, resuming it, closing it, reducing an authorization, deciding a dispute, submitting a timesheet and clocking in or out take no expected-version input at all.

### 2.7. Path Resolution and Not-Found Semantics

Several read paths are nested — a nurse's competency list, a case's supervisory visits, a case's incident reports, and an assignment's timesheets. Wherever a path carries more than one identifier, the identifiers are resolved **strictly left to right**, and the first identifier that does not resolve determines the response. A request for the supervisory visits of a case that does not exist yields `ERR_CASE_NOT_FOUND` (HTTP 404); the server does not look further right. This same left-to-right discipline applies to a single-identifier path.

Each entity has its own not-found code: `ERR_PAYER_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PLAN_OF_CARE_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_NURSE_NOT_FOUND`, `ERR_COMPETENCY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, and `ERR_DISPUTE_NOT_FOUND`, all with HTTP 404.

Foreign keys supplied in a request body are resolved the same way and with the same code set. A create that names a `patient_id`, `authorization_id`, `plan_of_care_id`, `payer_id`, `nurse_id`, `case_id` or `shift_id` that does not exist is a 404 against the missing entity, not a 422.

Every mutation in this API addresses its own top-level collection and carries its foreign keys in the body; there are no nested write paths other than recording a competency for a named nurse and recording a supervisory visit on a named case.

### 2.8. Validation Precedence

When a single request could fail several checks, the outcome is fully determined: checks are evaluated in **ascending priority order** and the **first** failing check produces the response. This ordering is part of the contract, not an implementation detail — a request that violates both a payer scope rule and a weekly hour cap must report the scope violation.

The complete order is as follows.

1. `X-User-Role` and `X-User-ID` are both present and non-empty, on every endpoint — otherwise `ERR_MISSING_AUTH_HEADER` (401).
2. The `X-User-Role` value is one of the six roles of Section 2.1 and is permitted on the endpoint, on every endpoint — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
3. Entity-backed ownership for a `Nurse`: on shift clock-in, shift clock-out and timesheet correction, `X-User-ID` equals the `nurse_id` of the shift's `ACTIVE` `ShiftAssignment` — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
4. Payer scope for a `PayerReviewer`, on the nine operations enumerated in Section 2.1 — otherwise `ERR_PAYER_SCOPE_VIOLATION` (403).
5. Every identifier in the URL path exists, resolved left to right, on every endpoint with path parameters — otherwise the matching 404 code.
6. Every foreign-key identifier in the request body exists, on every create that carries foreign keys — otherwise the matching 404 code.
7. Request shape: required fields present, enum members legal, numbers strictly positive, `end_at` strictly after `start_at`, `effective_end` strictly after `effective_start`, `end_date` strictly after `start_date`, `expires_on` strictly after `validated_on`, `required_skills` non-empty with distinct members, `ordering_physician_npi` exactly ten digits, `limit` between 1 and 100 inclusive, and `offset` at least 0 — on every create, every correction and every paginated list — otherwise `ERR_INVALID_REQUEST` (400).
8. Optimistic concurrency: `expected_plan_of_care_version` equals the plan of care's `version` on authorization creation; `expected_shift_version` equals the shift's `version` on manual assignment and on automatic staffing — otherwise `ERR_STALE_PLAN_OF_CARE_VERSION` or `ERR_STALE_SHIFT_VERSION` (412).
9. The target resource currently sits in a state from which the requested transition is declared in Section 3, on every transition endpoint — otherwise `ERR_INVALID_STATE` (409). One carve-out exists: this rule does **not** apply to filing an authorization dispute. A filing against an authorization already `UNDER_APPEAL` is reported by check 28 as `ERR_DISPUTE_ALREADY_OPEN`, and a filing against an authorization whose status is outside `ACTIVE`, `REDUCTION_NOTICED` and `UNDER_APPEAL` is reported by check 11 as `ERR_AUTHORIZATION_NOT_ACTIVE`.
10. The governing case is neither `ON_HOLD` nor `CLOSED`, on six operations — publishing a shift, manual assignment, automatic staffing, escalation, parent-backup arrangement, and clock-in — otherwise `ERR_CASE_ON_HOLD` (409).
11. The governing authorization's `status` is one of `ACTIVE`, `REDUCTION_NOTICED`, `UNDER_APPEAL`, `REDUCED`, on six operations — opening a case, activating a case, publishing a shift, manual assignment, automatic staffing, and filing a dispute — otherwise `ERR_AUTHORIZATION_NOT_ACTIVE` (409).
12. The patient's `status` is not `HOSPITALIZED`, on three operations — activating a case, resuming a case, and publishing a shift — otherwise `ERR_PATIENT_HOSPITALIZED` (409).
13. Segregation of duties on case resume, as specified in Section 2.11 — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
14. On opening a case, the patient's `payer_id` equals the authorization's `payer_id` — otherwise `ERR_PAYER_MISMATCH` (422).
15. On manual assignment, the nurse does not appear in the case's `excluded_nurse_ids` — otherwise `ERR_NURSE_EXCLUDED_FROM_CASE` (422).
16. On manual assignment, the nurse's `status` is `ACTIVE` — otherwise `ERR_NURSE_NOT_ACTIVE` (422).
17. On manual assignment, the nurse's `license_expires_on` date is strictly after the date of the shift's `end_at` — otherwise `ERR_NURSE_LICENSE_EXPIRED` (422).
18. On manual assignment, the nurse holds a competency row — in any status — for every skill in the shift's `required_skills`; a skill with no row at all is a mismatch rather than an expiry — otherwise `ERR_NURSE_SKILL_MISMATCH` (422).
19. On manual assignment, every one of those matched competency rows has `status` `VALID` and an `expires_on` strictly after the date of the shift's `start_at`; a competency expiring exactly on the shift's start date fails — otherwise `ERR_COMPETENCY_EXPIRED` (422).
20. On manual assignment and on automatic staffing, the case's `supervisory_status` is `CURRENT`, meaning the logical clock is strictly before `next_supervisory_visit_due_at` — otherwise `ERR_SUPERVISORY_VISIT_OVERDUE` (409).
21. On recording a parent-backup arrangement, the patient's `parent_backup_available` is true — otherwise `ERR_NO_PARENT_BACKUP` (422).
22. On publishing a shift, `start_at` is at or after the authorization's `effective_start` and `end_at` is at or before its `effective_end` — otherwise `ERR_SHIFT_OUTSIDE_AUTH_WINDOW` (422).
23. On manual assignment, the nurse-as-resource overlap check with its sixty-minute rest buffer, as specified in Section 3.5 — otherwise `ERR_NURSE_SHIFT_OVERLAP` (409).
24. On manual assignment, the patient-as-resource aggregate capacity check, as specified in Section 3.5 — otherwise `ERR_PATIENT_CONCURRENCY_EXCEEDED` (409).
25. On clock-in, the logical clock is at or after fifteen minutes before the shift's `start_at` — otherwise `ERR_CLOCK_IN_TOO_EARLY` (422).
26. On filing a dispute of type `REDUCTION_APPEAL`, the logical clock is strictly before the authorization's `reduction_effective_at` — otherwise `ERR_DISPUTE_WINDOW_CLOSED` (422).
27. On applying a noticed reduction, the logical clock is at or after the authorization's `reduction_effective_at` — otherwise `ERR_REDUCTION_NOT_EFFECTIVE` (409).
28. On filing a dispute, no dispute of that authorization is currently `FILED` or `UNDER_REVIEW` — otherwise `ERR_DISPUTE_ALREADY_OPEN` (409).
29. On deciding a dispute, `decided_hours_per_week` is present for outcome `PARTIALLY_GRANTED` and falls strictly inside the band declared in Section 3.9 — otherwise `ERR_DECIDED_HOURS_OUT_OF_RANGE` (422).
30. On registering a nurse, `license_number` is not already held by another nurse — otherwise `ERR_LICENSE_NUMBER_TAKEN` (409).
31. On recording a competency, no competency for the same nurse and the same `skill` exists whose `status` is anything other than `REVOKED` — otherwise `ERR_COMPETENCY_DUPLICATE` (409).
32. On manual assignment, the nurse's weekly ceiling, as specified in Section 3.5 — otherwise `ERR_NURSE_WEEKLY_LIMIT_EXCEEDED` (422).
33. On automatic staffing, the candidate pool is non-empty — otherwise `ERR_NO_ELIGIBLE_NURSE` (422).
34. On issuing an authorization and on renewing one, `approved_hours_per_week` is at most the payer's `weekly_hour_cap` — otherwise `ERR_PAYER_HOUR_CAP_EXCEEDED` (422).
35. On issuing an authorization and on renewing one, `approved_hours_per_week` is at most the plan of care's `requested_hours_per_week` — otherwise `ERR_APPROVED_EXCEEDS_REQUESTED` (422).
36. On manual assignment and on automatic staffing, the weekly authorized-hours cap, as specified in Section 3.5 — otherwise `ERR_WEEKLY_HOURS_EXCEEDED` (422).
37. On renewing an authorization, the utilization gate of Section 3.9 — otherwise `ERR_RENEWAL_UTILIZATION_TOO_LOW` (422).
38. On submitting a timesheet for billing, the shift's `evv_status` is `VERIFIED` — otherwise `ERR_EVV_NOT_VERIFIED` (409).
39. On correcting a timesheet, submitting one, and recording a billing decision, the timesheet has not already reached `BILL_ACCEPTED` or `VOIDED` — otherwise `ERR_TIMESHEET_ALREADY_BILLED` (409).

A practical consequence worth internalising: because the nurse-eligibility gauntlet is ordered 15 through 19 and then 23, 24, 32 and 36, a nurse who is simultaneously excluded from the case, suspended, and over their weekly ceiling produces `ERR_NURSE_EXCLUDED_FROM_CASE`, and a nurse who fails both the rest-buffer overlap and the authorized weekly cap produces `ERR_NURSE_SHIFT_OVERLAP`.

### 2.9. Units, Precision and Rounding

Three units of measure circulate through this system and confusing them is the most common source of arithmetic error.

- **Whole minutes** are the internal currency of scheduling. A shift's `scheduled_minutes` is the number of whole minutes between its `start_at` and its `end_at`. A nurse's `scheduled_minutes_this_week` is an integer count of minutes. Weekly caps expressed in hours are converted to minutes by multiplying by 60 before any comparison, and every comparison in the scheduling domain is an exact integer comparison with no rounding whatsoever.
- **Hours** are the unit in which a payer writes a grant. Any hour figure the API exposes — `approved_hours_per_week`, `noticed_hours_per_week`, `requested_hours_per_week`, `decided_hours_per_week`, `hours_committed_this_week`, `hours_remaining_this_week`, and `hours_remaining` on a utilization read — is a number rounded to exactly two decimal places using the round-half-up convention.
- **Billing units** are quarter-hours. One billable unit represents 15 minutes of care. All unit figures — `gross_billable_units`, `edit_deduction_units`, `net_billable_units`, `settled_gross_units`, `settled_net_units`, and `billed_units_to_date` — are integers.

Ratios are reported to four decimal places, round half up: this covers `utilization_ratio` on a utilization read, a case's `fill_rate`, and the renewal utilization ratio. Match scores and continuity scores are integer point totals with no rounding at all. Cadences are whole days, and where a cadence is halved the result is rounded **up** to the next whole day.

All numeric values in response bodies are JSON numbers, never strings.

### 2.10. Cascade Discipline and Hierarchical Consistency

This system's hardest behaviour is not any single computation but the way suspensions propagate. Five events cascade: filing a qualifying incident report, placing a case on hold, applying or upholding an hour reduction, an authorization expiring at the daily checkpoint, and revoking a nurse competency. A sixth, closing a case, cancels future work without a hold.

Two invariants govern all of them.

**Only the future is disturbed.** A cascade may cancel a shift only when its `start_at` is at or after the current logical clock. A shift already in progress, a shift already `COMPLETED`, and a shift already covered by a `PARENT_BACKUP` arrangement are never cancelled by any cascade. Already-worked hours are never clawed back.

**The chain runs to its end.** When a cascade cancels a shift, it also cancels that shift's `ACTIVE` `ShiftAssignment` with a matching `cancel_reason`, and then re-derives every aggregate the cancellation invalidated: the nurse's `scheduled_minutes_this_week`, the authorization's `hours_committed_this_week` and `hours_remaining_this_week`, and the case's `unfilled_shift_count` and `fill_rate`. Each row touched along the way independently refreshes `updated_at` and increments `version`. A cascade that stops after the first hop is a defect.

The `cancel_reason` recorded on a cancelled shift is the audit trail that tells the two hops apart, and its value depends on the cascade's origin: `CASE_HOLD` for a hold (whether manual or cascaded from an incident), `AUTH_REDUCTION` for a reduction trim, `AUTH_EXPIRY` for authorization expiry, `COMPETENCY_REVOKED` for a competency revocation, and `SCHEDULER` for a case closure or a scheduler-driven cancellation. `NONE` is the default on a shift that has never been cancelled. Assignment `cancel_reason` uses the same vocabulary plus `REPLACED`, which marks the incumbent when a continuity swap displaces it.

Resuming a held case never resurrects cancelled shifts. The scheduler must publish replacement shifts by hand. This is deliberate: a family whose Tuesday overnight was cancelled during a hospitalization needs a new staffing decision, not a silently restored one.

### 2.11. Segregation of Duties

Two duties in this system are deliberately split so that no single operator can both create and clear a clinical risk.

The first split is on **case resume**. When a case was put on hold by a cascade from an incident report, the case records `hold_incident_report_id` pointing at that report. Resuming such a case requires that the acting `ClinicalSupervisor`'s `X-User-ID` differs from the `reported_by_user_id` recorded on that incident report; if they are the same person, the resume is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). When `hold_incident_report_id` is null — the hold was placed manually — no such comparison is made and any `ClinicalSupervisor` may resume.

The second split is on **timesheet billing**. A `Nurse` captures and may correct their own timesheet, but a `Nurse` can never advance it toward payment: submission belongs exclusively to a `Scheduler`, and the accept-or-reject decision belongs exclusively to a `PayerReviewer` scoped to the paying payer. Three different actors therefore touch every billed visit.

### 2.12. Conserved Quantities and Compensating Actions

Two quantities in this system are conserved, which means every forward action that moves them has an exact compensating action that returns them to their prior value with zero drift.

The first is **committed scheduled minutes**. At all times, an authorization's `hours_committed_this_week` equals the sum of `scheduled_minutes` over shifts of that authorization's cases whose `staffing_status` is `ASSIGNED` or `COMPLETED` and whose `start_at` falls in the ISO week window containing the current logical clock, divided by 60 and rounded half up to two decimal places. Likewise, a nurse's `scheduled_minutes_this_week` equals the sum of `scheduled_minutes` over the shifts of that nurse's assignments whose `status` is `ACTIVE` or `COMPLETED` and whose shift `start_at` falls in that same week window. Creating an assignment grows both quantities by exactly the shift's `scheduled_minutes` — expressed as hours for the authorization figure and as minutes for the nurse figure — and cancelling that assignment shrinks both by exactly the same amount, so a create followed by a cancel is a perfect no-op.

The second is **accepted billable units**. At all times, a case's `billed_units_to_date` equals the sum of `net_billable_units` over the timesheets of that case whose `status` is `BILL_ACCEPTED`; voided rows contribute nothing. Accepting a timesheet for billing adds exactly that timesheet's `net_billable_units`; voiding it subtracts exactly the same figure, and the timesheet simultaneously leaves the settled utilization input set, so a settled-basis utilization read returns to its pre-acceptance value exactly.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Payers, Patients and the Nursing Roster

Nothing can be authorized or staffed until three registries exist. An `AgencyAdmin` seeds the payer registry: each payer carries a `name` between 1 and 120 non-blank characters, a `plan_type` that is one of `MEDICAID_WAIVER`, `MEDICAID_MCO` or `COMMERCIAL`, and a `weekly_hour_cap` between 1 and 168 that is the hard ceiling on any weekly grant this payer will ever write. Four further attributes are optional at registration and shape downstream behaviour. `evv_required` records whether electronic visit verification is mandatory for this payer's billing and defaults to true. `billing_edit_ruleset` selects which deduction-percentage table the billing-edit computation of Section 3.7 uses; it is one of `STANDARD_15MIN` or `STRICT_15MIN` and defaults to `STANDARD_15MIN`. `appeal_window_days` is the notice window published to families, between 1 and 90 days, defaulting to 30 — it is informational and gates nothing on its own. `reduction_notice_days`, between 1 and 60 and defaulting to 10, is the operative one: it is the number of days added to the logical clock to compute a reduction's effective instant.

Pediatric patients are enrolled by a `CaseManager` under exactly one payer, named through `payer_id`. Each patient carries a `full_name` of 1 to 120 non-blank characters, a date-only `date_of_birth`, and a free-text `primary_diagnosis`. Four boolean flags describe the child's acuity and the family's capacity, and each defaults to false: `requires_trach` when tracheostomy care is needed at every visit, `requires_vent` when ventilator management is needed at every visit, `requires_feeding_tube` when enteral feeding-tube management is needed at every visit, and `parent_backup_available` when the family has a trained parent caregiver who can absorb an unfilled shift. A patient's `status` is system-managed and begins at `ACTIVE`; it becomes `HOSPITALIZED` when a hospitalization incident is filed, returns to `ACTIVE` when that report is closed with the child home, and becomes `DISCHARGED` once every case of the patient is `CLOSED`. Patients may be listed with an optional `payer_id` or `status` filter.

The nurse roster is likewise the `AgencyAdmin`'s responsibility. A nurse row records a `full_name` of 1 to 120 non-blank characters, a `license_type` of either `RN` or `LPN`, a `license_number` of 1 to 32 characters that must be unique across the entire roster, a date-only `license_expires_on`, and a `max_weekly_hours` contractual ceiling between 1 and 80 that defaults to 40. A duplicate licence number is rejected with `ERR_LICENSE_NUMBER_TAKEN`. A nurse's `status` starts at `ACTIVE` and may be moved by an `AgencyAdmin` to `SUSPENDED` or `INACTIVE` and back; only an `ACTIVE` nurse is staffable. Reading a nurse also exposes two derived quantities: `scheduled_minutes_this_week`, the integer minute total defined in Section 2.12, and `verified_skills`, the list of skills for which the nurse holds a competency whose `status` is `VALID` and whose `expires_on` is strictly after the current logical clock date, sorted ascending by skill name. Nurses may be listed with an optional `status` filter or an optional single-`skill` filter.

Moving a nurse out of `ACTIVE` is not a bookkeeping change. Every `ACTIVE` assignment of that nurse on a shift whose `evv_status` is still `NOT_STARTED` is cancelled with `cancel_reason` `SCHEDULER`, and each such shift returns to `OPEN` rather than being cancelled — the work still needs covering. The authorization's `hours_committed_this_week` and the nurse's `scheduled_minutes_this_week` are then recomputed. Visits already under way, where the nurse has clocked in, are left alone.

### 3.2. Competency Attestation, Expiry and Revocation

Skill is tracked per nurse per skill, and only a `ClinicalSupervisor` may attest it. Each competency row names one `skill` from `TRACH`, `VENT`, `FEEDING_TUBE`, `SEIZURE_RESCUE`, a date-only `validated_on`, and a date-only `expires_on` that must be strictly after `validated_on`. The attesting supervisor's identifier is captured as `validated_by_user_id`. A nurse may hold at most one non-revoked row per skill: attempting to add a second row for a skill the nurse already holds in any status other than `REVOKED` is rejected with `ERR_COMPETENCY_DUPLICATE`. Recording a competency re-derives the nurse's `verified_skills`. A nurse's competency rows may be listed with an optional `status` filter.

A competency's `status` begins at `VALID`. It becomes `EXPIRED` when the daily checkpoint observes that its `expires_on` is at or before the current logical clock date, and it becomes `REVOKED` when a `ClinicalSupervisor` revokes it after a failed validation, supplying a `revoked_reason` that is stored on the row. `revoked_reason` is null on every row that has not been revoked.

**Revocation cascades into the schedule.** Because a revoked skill invalidates the nurse for work that depends on it, revoking a competency cancels every shift whose `start_at` is at or after the current logical clock, whose `required_skills` contain the revoked skill, and whose `ACTIVE` assignment belongs to this nurse. Each such shift becomes `CANCELLED` with `cancel_reason` `COMPETENCY_REVOKED`, and that assignment becomes `CANCELLED` with the same reason. The authorization's `hours_committed_this_week` and the nurse's `scheduled_minutes_this_week` are then recomputed, and the nurse's `verified_skills` is re-derived. Shifts requiring skills the nurse still holds are untouched, as are shifts already begun or in the past.

### 3.3. From Physician Order to Approved Hours

A plan of care is the physician's order, transcribed by a `CaseManager`. It names the child through `patient_id`, states the `requested_hours_per_week` the ordering physician asked for as an integer between 1 and 168, delimits coverage with a date-only `start_date` and a date-only `end_date` that must be strictly after `start_date`, and records the ordering physician's `ordering_physician_npi` as exactly ten digits. It is created in `DRAFT` with `revision_round` at 0. Plans of care may be listed with an optional `patient_id` or `status` filter.

Submission by the plan's `CaseManager` moves `DRAFT → SUBMITTED` and is permitted only while the plan is still `DRAFT` and the patient's `status` is anything other than `DISCHARGED`; the plan's `version` increments. A submitted plan is what a payer can act on.

A `PayerReviewer` answers a submitted plan by issuing an authorization against it. The request names the plan through `plan_of_care_id` and the paying organisation through `payer_id`, states the `approved_hours_per_week` being granted, delimits the grant with `effective_start` and `effective_end` as ISO 8601 UTC instants where `effective_end` must be strictly after `effective_start`, and carries `expected_plan_of_care_version` as described in Section 2.6. Optionally it carries `supersedes_authorization_id`, the renewal-chain pointer, which is null for the first authorization of a plan of care. The `payer_id` recorded on an authorization must be the payer that the plan's patient is enrolled under; the case-opening check of Section 3.4 enforces that alignment again at the point where the two aggregates meet. `approved_hours_per_week` is a positive number with two decimal places, and it must not exceed either the payer's `weekly_hour_cap` — otherwise `ERR_PAYER_HOUR_CAP_EXCEEDED` — or the plan's `requested_hours_per_week` — otherwise `ERR_APPROVED_EXCEEDS_REQUESTED`. Issuing the authorization is only possible while the plan sits in `SUBMITTED`; it creates the authorization in `PENDING` with `renewal_chain_depth` 0, moves the plan `SUBMITTED → UNDER_REVIEW`, and increments the plan's `version`. A partial approval — an `approved_hours_per_week` strictly below the plan's `requested_hours_per_week` — is legitimate and is exactly what a denial appeal later contests.

Activation is the reviewer's second act and the moment the grant becomes real. It requires the authorization to be `PENDING` and the logical clock to be strictly before the authorization's `effective_end`. On success the authorization moves `PENDING → ACTIVE`, the plan of care moves `UNDER_REVIEW → AUTHORIZED` — its terminal state — and the plan's `version` increments. When the activating authorization carries a non-null `supersedes_authorization_id`, activation additionally runs the renewal handover described in Section 3.9.

Not every plan survives review. A `PayerReviewer` may instead return the plan for revision, supplying a `return_reason`. A return is permitted while the plan is `SUBMITTED` or `UNDER_REVIEW`, and only when no authorization of that plan currently sits in `ACTIVE`, `REDUCTION_NOTICED`, `UNDER_APPEAL` or `REDUCED` — a plan whose grant is already live cannot be pulled back. The return moves the plan to `RETURNED`, increases `revision_round` by 1, takes every `PENDING` authorization of that plan out of consideration by moving it to `EXPIRED`, and increments the plan's `version`. The `CaseManager` then resubmits, moving `RETURNED → SUBMITTED` and incrementing `version` again. The loop `RETURNED → SUBMITTED → UNDER_REVIEW → RETURNED` may repeat any number of times, with `revision_round` counting the rounds.

An authorization's `status` ranges over `PENDING`, `ACTIVE`, `REDUCTION_NOTICED`, `UNDER_APPEAL`, `REDUCED`, `EXPIRED` and `SUPERSEDED`, of which `EXPIRED` and `SUPERSEDED` are terminal. Authorizations may be listed with optional `plan_of_care_id`, `payer_id`, `supersedes_authorization_id` or `status` filters.

**Weekly utilization, in two bases.** Any read of an authorization exposes `hours_committed_this_week` and `hours_remaining_this_week`; a dedicated utilization read exposes the full picture and accepts an optional `basis` of either `PROJECTED` or `SETTLED` and an optional `week_of` instant. When `week_of` is omitted the current logical clock is used; when `basis` is omitted the `PROJECTED` variant applies. The reference week is the ISO week window containing that instant, and the cases in scope are **every** case whose `authorization_id` is this authorization — with no status filter at all, so `ON_HOLD` and `CLOSED` cases are included.

Under the `PROJECTED` variant, `committed_minutes` is the sum of `scheduled_minutes` over the shifts of those in-scope cases whose `staffing_status` is `ASSIGNED` or `COMPLETED` and whose `start_at` falls inside the week window. Shifts that are `OPEN`, `ESCALATED`, `PARENT_BACKUP` or `CANCELLED` contribute nothing. This is the scheduled view: a visit the nurse under-worked still consumes its full scheduled duration, and an unverified visit still counts.

Under the `SETTLED` variant, the input set is the timesheets reachable from those same in-scope cases through assignment and shift, restricted to shifts whose `start_at` falls inside the week window and to timesheets whose `status` is `SUBMITTED` or `BILL_ACCEPTED`; `CAPTURED`, `EDITED`, `BILL_REJECTED` and `VOIDED` timesheets are excluded. Over that set, `settled_gross_units` is the sum of `gross_billable_units` and `settled_net_units` is the sum of `net_billable_units`, and `settled_minutes` is `settled_net_units` multiplied by 15. Because grace capping, quarter-hour rounding, billing-edit deductions and un-submitted visits all bite here, the settled figure diverges from the projected figure for identical shift data. Note that both bases key on the **shift's** `start_at`, never on a timesheet's `clock_in_at`.

From whichever basis applies, three figures follow. The weekly ceiling in minutes is `approved_hours_per_week` multiplied by 60. `utilization_ratio` is the basis minutes divided by that ceiling, rounded half up to four decimal places. `hours_remaining` is the greater of zero and the ceiling minus the basis minutes, divided by 60 and rounded half up to two decimal places. The utilization read returns `authorization_id`, the `basis` applied, the `week_start` and `week_end` instants bounding the window, `committed_minutes`, `settled_gross_units`, `settled_net_units`, `settled_minutes`, `approved_hours_per_week`, `hours_remaining` and `utilization_ratio`. The two fields carried on the authorization row itself are the same computation pinned to the current week on the projected basis: `hours_committed_this_week` is `committed_minutes` divided by 60 rounded half up to two decimal places, and `hours_remaining_this_week` is `approved_hours_per_week` minus `hours_committed_this_week`, floored at 0.00 and carried to two decimal places.

### 3.4. Opening a Case, Supervisory Oversight and Fill Metrics

A case is the operational bridge between a payer's grant and a family's calendar, and only a `CaseManager` may open one. The request binds the child through `patient_id` to a grant through `authorization_id` and names the accountable supervisor through `assigned_supervisor_user_id`. Three optional inputs shape staffing policy for the life of the case: `continuity_nurse_id`, the family's preferred continuity nurse, which is null when no preference is recorded; `concurrent_nurse_limit`, an integer between 1 and 3 defaulting to 1, being the maximum number of overlapping staffed shifts allowed for this patient at any instant; and `excluded_nurse_ids`, an array of nurse identifiers barred from this case, defaulting to an empty array. Opening the case requires the named authorization to sit in `ACTIVE`, `REDUCTION_NOTICED`, `UNDER_APPEAL` or `REDUCED`, and requires the patient's `payer_id` to equal the authorization's `payer_id` — a cross-aggregate alignment whose violation is `ERR_PAYER_MISMATCH`. The case is created in `PENDING_STAFFING`, and `next_supervisory_visit_due_at` is initialised immediately from the patient's acuity cadence.

Activation moves the case `PENDING_STAFFING → ACTIVE` and opens it to shift publication and staffing. It requires the case to still be `PENDING_STAFFING`, the governing authorization to be in one of the four staffable statuses above, and the patient to be `ACTIVE` — a `HOSPITALIZED` patient blocks activation with `ERR_PATIENT_HOSPITALIZED`. On success `next_supervisory_visit_due_at` and `supervisory_status` are re-derived. Cases may be listed with optional `patient_id`, `authorization_id`, `continuity_nurse_id`, `hold_incident_report_id` or `status` filters.

**The supervisory cadence is a staffing gate, not a reminder.** Every case carries a computed `supervisory_status` of either `CURRENT` or `OVERDUE`, and while it reads `OVERDUE` no nurse may be assigned to any of its shifts — the attempt is rejected with `ERR_SUPERVISORY_VISIT_OVERDUE`. The cadence itself is driven by the child's acuity. The base cadence is 14 days when the patient's `requires_vent` is true; otherwise 30 days when `requires_trach` is true; otherwise 60 days. The latest supervisory visit of the case is the one with the greatest `visit_at`, breaking a tie by the greatest `created_at` and never by identifier. When the case has no supervisory visit at all, or when the latest visit's `outcome` is `PASS`, the cadence applied is the base cadence; when the latest visit's `outcome` is `DEFICIENT`, the cadence applied is the base cadence halved and rounded up to the next whole day. The anchor from which the cadence is measured is the case's own `created_at` when there is no visit yet, and otherwise the latest visit's `visit_at`. `next_supervisory_visit_due_at` is the anchor plus the applied cadence in days, and `supervisory_status` reads `OVERDUE` when the logical clock is at or after that instant and `CURRENT` otherwise — a clock sitting exactly on the due instant is already `OVERDUE`.

A `ClinicalSupervisor` resets the cadence by recording a visit against the case. The record carries a `visit_at` instant that must not be after the current logical clock, an `outcome` of either `PASS` or `DEFICIENT`, and a narrative in `notes`; the acting supervisor's identifier is captured as `supervisor_user_id`. The visit stores the cadence the rule selected for it in `cadence_days_applied` and its own `next_due_at`, which is `visit_at` plus `cadence_days_applied` days, and the case's `next_supervisory_visit_due_at` is set to that same instant with `supervisory_status` re-derived. A ventilator-dependent child whose most recent visit came back `DEFICIENT` is therefore due again seven days later, while a non-trach non-vent child with a passing visit has two months of runway.

**Fill metrics.** Two computed figures let a scheduler see coverage at a glance, and both look strictly forward from the current logical clock to the governing authorization's `effective_end`, a half-open window. Over the shifts of this case whose `start_at` falls in that window and whose `staffing_status` is anything other than `CANCELLED`, the denominator is their count and the numerator is the count of those whose `staffing_status` is `ASSIGNED`, `COMPLETED` or `PARENT_BACKUP`. `fill_rate` is the numerator divided by the denominator, rounded half up to four decimal places; when the denominator is zero, `fill_rate` is exactly 1.0000. Separately, `unfilled_shift_count` is the number of shifts of the case whose `staffing_status` is `OPEN` or `ESCALATED` and whose `start_at` is at or after the current logical clock. Cancelled shifts are excluded from both the numerator and the denominator of the fill rate. A case read also exposes `billed_units_to_date`, the conserved unit total of Section 2.12.

Closing a case is the `CaseManager`'s final act and takes a `close_reason`. A close is accepted from `PENDING_STAFFING`, `ACTIVE` or `ON_HOLD`, but only when no timesheet of the case is still in flight — that is, no timesheet of the case has `status` `CAPTURED`, `EDITED`, `SUBMITTED` or `BILL_REJECTED`; an in-flight timesheet makes the close an `ERR_INVALID_STATE`. On close, every shift of the case whose `staffing_status` is `OPEN`, `ASSIGNED` or `ESCALATED` and whose `start_at` is at or after the current logical clock becomes `CANCELLED` with `cancel_reason` `SCHEDULER`, and each such shift's `ACTIVE` assignment becomes `CANCELLED`. Once every case of the patient has reached `CLOSED`, the patient's `status` becomes `DISCHARGED`.

### 3.5. Publishing Shifts and Filling Them

A `Scheduler` publishes each shift against a case through `case_id`, bounding it with `start_at` and `end_at` — the latter strictly after the former — and declaring `required_skills`, a non-empty array of between one and four distinct values drawn from `TRACH`, `VENT`, `FEEDING_TUBE` and `SEIZURE_RESCUE`. The server derives `scheduled_minutes` as the whole minutes between the two instants. Publication requires the governing case to be neither `ON_HOLD` nor `CLOSED`, the governing authorization to be in one of the four staffable statuses, and the patient not to be `HOSPITALIZED`; it further requires the shift to sit inside the grant, meaning `start_at` at or after the authorization's `effective_start` and `end_at` at or before its `effective_end`, failing which the publication is rejected with `ERR_SHIFT_OUTSIDE_AUTH_WINDOW`. A new shift begins with `staffing_status` `OPEN`, `evv_status` `NOT_STARTED`, `escalation_tier` `NONE`, `escalated_at` null and `cancel_reason` `NONE`, and the case's `unfilled_shift_count` and `fill_rate` are immediately re-derived. Shifts may be listed with optional `case_id`, `staffing_status`, `evv_status` or `start_after` filters, the last selecting shifts starting after a supplied instant.

A shift carries **two independent state axes**, and confusing them is the single most consequential modelling error an implementer can make. `staffing_status` — ranging over `OPEN`, `ASSIGNED`, `ESCALATED`, `PARENT_BACKUP`, `COMPLETED` and `CANCELLED`, of which the last three are terminal — describes who is going to work the shift. `evv_status` — ranging over `NOT_STARTED`, `CLOCKED_IN`, `VERIFIED` and `EXCEPTION` — describes what electronic visit verification observed. A clock-in advances only the second axis and leaves the first untouched. A case hold cancels only shifts on the first axis and never rewrites the second.

Filling a shift by hand names the target through `shift_id` and the nurse through `nurse_id` and carries `expected_shift_version`. The transition is accepted while the shift's `staffing_status` is `OPEN`, `ESCALATED` or `ASSIGNED` — the third case being a deliberate continuity swap in which the new assignment replaces the incumbent — provided the shift's `start_at` is at or after the current logical clock, the case is `ACTIVE`, the authorization is in one of the four staffable statuses, and the case's `supervisory_status` reads `CURRENT`. On success the shift lands in `ASSIGNED` on its staffing axis and its `version` increments by 1.

Between those state checks and the assignment row sits the eligibility gauntlet, evaluated in the precedence order of Section 2.8. The nurse must not appear in the case's `excluded_nurse_ids` (`ERR_NURSE_EXCLUDED_FROM_CASE`). The nurse's `status` must be `ACTIVE` (`ERR_NURSE_NOT_ACTIVE`). The nurse's `license_expires_on` must be strictly after the date of the shift's `end_at`, so a licence lapsing on the shift's end date is a failure (`ERR_NURSE_LICENSE_EXPIRED`). For every skill in `required_skills` the nurse must have a competency row — in any status whatsoever — otherwise the request is a skill mismatch (`ERR_NURSE_SKILL_MISMATCH`), which is deliberately distinguished from the next check: every one of those matched rows must have `status` `VALID` and an `expires_on` strictly after the date of the shift's `start_at`, so an `EXPIRED` row, a `REVOKED` row, or a row expiring exactly on the shift's start date is a competency failure (`ERR_COMPETENCY_EXPIRED`).

Three capacity rules close the gauntlet, and each uses a different overlap convention.

- **The nurse rest buffer.** A nurse may hold no `ACTIVE` assignment on any other shift whose window, widened by sixty minutes on both sides, meets the target: the conflict exists when the target's `start_at` is earlier than the other shift's `end_at` plus sixty minutes **and** the other shift's `start_at` is earlier than the target's `end_at` plus sixty minutes. Any such conflict is `ERR_NURSE_SHIFT_OVERLAP`. Back-to-back shifts are therefore not permitted; an hour of rest must separate them.
- **The patient's home capacity.** Counted over the shifts of the patient's cases whose `staffing_status` is `ASSIGNED` or `COMPLETED`, the number that **strictly** overlap the target shift — the target's `start_at` earlier than the other's `end_at` and the other's `start_at` earlier than the target's `end_at`, so exact adjacency is allowed and no buffer applies — must remain below the case's `concurrent_nurse_limit`. Exceeding it is `ERR_PATIENT_CONCURRENCY_EXCEEDED`. With the default limit of 1, a second nurse may not overlap the first by even a minute, but may start at the exact instant the first ends.
- **The nurse's contractual ceiling.** Take the nurse's scheduled minutes in the ISO week window containing the shift's `start_at`, excluding any minutes this very shift already contributes, add the shift's `scheduled_minutes`, and require the total to be at most `max_weekly_hours` multiplied by 60. Exceeding it is `ERR_NURSE_WEEKLY_LIMIT_EXCEEDED`. A nurse whose ceiling is 40 hours therefore has 2,400 weekly minutes to spend.

Last comes the payer's quota. Take the projected committed minutes for the ISO week window containing the shift's `start_at`, excluding the target shift's own contribution, add the shift's `scheduled_minutes`, and require the total to be at most `approved_hours_per_week` multiplied by 60. Equality is allowed — a week filled exactly to the grant is legal — and anything above it is `ERR_WEEKLY_HOURS_EXCEEDED`.

A successful assignment creates a `ShiftAssignment` in `ACTIVE` referencing `shift_id` and `nurse_id`, with `cancel_reason` `NONE`. Two computed values are attached at birth: `continuity_match`, true exactly when `nurse_id` equals the case's `continuity_nurse_id`, and `match_score_at_assignment`, the match score evaluated for this nurse against this shift at creation time and **frozen** thereafter — a later change in the nurse's workload never rewrites it, and manual assignments store it just as automatic ones do. When the shift had an incumbent, that incumbent assignment becomes `CANCELLED` with `cancel_reason` `REPLACED` and the incumbent nurse's `scheduled_minutes_this_week` is recomputed. When the shift had been escalated, `escalation_tier` returns to `NONE` and `escalated_at` returns to null. Finally the aggregates of Section 2.12 are refreshed together with the case's `unfilled_shift_count` and `fill_rate`. Assignments may be listed with optional `shift_id`, `nurse_id` or `status` filters, `status` ranging over `ACTIVE`, `CANCELLED` and `COMPLETED`.

Releasing a nurse is the exact compensating move. A `Scheduler` cancels an `ACTIVE` assignment with a `cancel_note`, permitted only while the shift's `staffing_status` is `ASSIGNED` and its `evv_status` is still `NOT_STARTED` — once a nurse has clocked in, the assignment cannot be cancelled. The assignment becomes `CANCELLED` with `cancel_reason` `SCHEDULER`, the shift moves `ASSIGNED → OPEN` with its `version` incremented, and both conserved minute quantities fall by exactly the shift's `scheduled_minutes`, returning to their pre-assignment values with no drift.

### 3.6. Choosing the Nurse — and What Happens When No Nurse Exists

Continuity is the currency families care about most, so the platform quantifies it. A continuity score may be read for one nurse against one case, naming the case through `case_id` and selecting an optional `basis` of either `STRICT` or `BROAD`; when `basis` is omitted, `STRICT` applies. The read returns `nurse_id`, `case_id`, the `basis` applied, `matched_assignment_count`, and `continuity_score`.

Under the `STRICT` basis, the matched count is the number of that nurse's assignments whose `status` is `COMPLETED`, whose shift belongs to **this** case, and whose shift `start_at` is at or after the current logical clock minus 28 days. Under the `BROAD` basis, the matched count is the number of that nurse's assignments whose `status` is `COMPLETED` or `CANCELLED` and whose shift belongs to any case of the **same patient** — including closed cases and cases governed by a superseded authorization — with no time window at all. In both bases the score is 15 points per match, counting at most 5 matches, so the score ranges from 0 to 75. Because the broad basis widens the entity scope, admits cancelled contact and drops the window, identical history yields a strictly larger broad score than strict score whenever the nurse has any cancelled or cross-case history with that child.

**The match score** is what ranks candidates, and it combines three signals that interact non-linearly. Continuity points are 40 when the nurse is the case's `continuity_nurse_id`; for any other nurse they are the lesser of 30 and that nurse's strict-basis continuity score for the case. Skill points count the distinct skills in the shift's `required_skills` for which the nurse holds a competency with that skill, `status` `VALID`, and an `expires_on` strictly after the date of the shift's `start_at`; that matched count is capped at 3 and multiplied by 10 points, and a further 10 points are added when the nurse's `license_type` is `RN` and `VENT` is among the shift's `required_skills`. Availability points start at 30 and lose 5 points for every complete four-hour block the nurse already has scheduled this week — formally, 5 points are deducted for each whole multiple of 240 minutes in the nurse's `scheduled_minutes_this_week`, and the result is floored at 0. The match score is the sum of the three components, an integer between 0 and 110.

**The automatic selector** offers a `Scheduler` the same outcome as a manual assignment without naming a nurse; the request carries only `expected_shift_version`. It first builds an eligible pool from the entire nurse roster — no pagination, every row considered — admitting a nurse only when all of the following hold: the nurse's `status` is `ACTIVE`; the nurse's `license_expires_on` date is strictly after the date of the shift's `end_at`; the nurse does not appear in the case's `excluded_nurse_ids`; for every skill in `required_skills` the nurse holds a competency with that skill whose `status` is `VALID` and whose `expires_on` is strictly after the date of the shift's `start_at`; the nurse holds no `ACTIVE` assignment on another shift that conflicts under the sixty-minute rest buffer described in Section 3.5; and the nurse's scheduled minutes in the ISO week window containing the shift's `start_at`, plus the shift's `scheduled_minutes`, are at most `max_weekly_hours` multiplied by 60.

The pool is then ordered by match score descending. Ties are broken first by the nurse's scheduled minutes in that same week window ascending — the least loaded nurse wins — and then by the nurse's `created_at` ascending. No tie-break in this system ever consults an identifier. The first row of the ordered list is the selected nurse, and the assignment that results is identical in every respect to a manual one: the shift moves `OPEN → ASSIGNED`, committed minutes grow, `match_score_at_assignment` is frozen and `continuity_match` is computed, and the case's fill metrics are re-derived. A `Scheduler` can inspect the selector's reasoning before committing to it: a candidates read returns `shift_id`, `candidate_count`, `ranked_nurse_ids` in the selector's order, `selected_nurse_id`, and `top_match_score`.

When the eligible pool is empty, the selector rejects the request with `ERR_NO_ELIGIBLE_NURSE` and mutates absolutely nothing — no assignment row, no version bump, and, crucially, **no automatic escalation**. Escalation is a deliberate act the scheduler must take.

**Escalation walks a three-tier ladder.** Escalating an unfilled shift, with an `escalation_reason` supplied, is permitted while its `staffing_status` is `OPEN` or `ESCALATED`, its `start_at` is at or after the current logical clock, and its case is `ACTIVE`. The first escalation moves the shift `OPEN → ESCALATED`, sets `escalation_tier` to `TIER1_AGENCY_POOL`, stamps `escalated_at` with the current logical clock, and increments the shift's `version`. A second escalation on an already `ESCALATED` shift is where the two branches part company. When the patient's `parent_backup_available` is false, the second escalation advances `escalation_tier` to `TIER3_PAYER_NOTIFICATION`, leaving `escalated_at` at its original value and incrementing `version`. When the patient's `parent_backup_available` is true, the second escalation is refused with `ERR_INVALID_STATE`: tier two is reachable only by actually arranging the parent backup, never by escalating again.

Arranging that backup is the `Scheduler`'s tier-two move, recorded with an `arrangement_note`. It requires the shift's `staffing_status` to be exactly `ESCALATED`, the shift's `start_at` to be at or after the current logical clock, and the patient's `parent_backup_available` to be true — otherwise `ERR_NO_PARENT_BACKUP`. The shift moves `ESCALATED → PARENT_BACKUP`, `escalation_tier` becomes `TIER2_PARENT_BACKUP`, and the shift's `version` increments. A parent-covered shift consumes **no authorized hours**: it is excluded from every committed-minutes sum, projected or settled. It does, however, count as covered for the purposes of the case's `fill_rate`, and it drops out of `unfilled_shift_count`, both of which are re-derived. `PARENT_BACKUP` is terminal on the staffing axis — the shift cannot later be assigned to a nurse.

### 3.7. The Visit: Electronic Visit Verification, Timesheets and Billing

The visit begins when the assigned `Nurse` clocks in, declaring an `evv_method` of `GPS`, `IVR` or `MANUAL` and optionally a `geo_verified` flag recording whether the device geofence matched the patient's address, which defaults to false. Clock-in is permitted only while the shift's `evv_status` is `NOT_STARTED` and its `staffing_status` is `ASSIGNED`, only by the nurse named on the shift's `ACTIVE` assignment, only while the case is neither `ON_HOLD` nor `CLOSED`, and no earlier than fifteen minutes before the shift's `start_at` — an attempt made more than fifteen minutes early is refused with `ERR_CLOCK_IN_TOO_EARLY`. Clocking in advances the shift `NOT_STARTED → CLOCKED_IN` on its verification axis, leaves the staffing axis at `ASSIGNED`, creates a timesheet in `CAPTURED` referencing the assignment through `shift_assignment_id` with `clock_in_at` set to the current logical clock and `clock_out_at` null, stores the method and geofence flag for later verification, and increments the shift's `version`.

Clocking out is the busiest single operation in the API. It requires the shift's `staffing_status` to be `ASSIGNED`, its `evv_status` to be `CLOCKED_IN`, and the acting nurse to be the one on the `ACTIVE` assignment. It then moves both axes at once and computes the money. On the staffing axis the shift moves `ASSIGNED → COMPLETED` and the assignment moves `ACTIVE → COMPLETED`. On the verification axis the shift moves from `CLOCKED_IN` to either `VERIFIED` or `EXCEPTION`. The timesheet's `clock_out_at` is set to the current logical clock, and the whole billing-edit computation runs. The shift's `version` increments.

**The verification outcome** is a strict three-part conjunction. The visit verifies only when the timesheet's `evv_method` is `GPS` or `IVR`, **and** `geo_verified` is true, **and** `clock_in_at` is at or before the shift's `start_at` plus sixty minutes. If all three hold, the shift moves `CLOCKED_IN → VERIFIED` and no exception code is recorded. If any one fails — a `MANUAL` method, a false geofence, or a clock-in later than sixty minutes past the shift start — the shift moves `CLOCKED_IN → EXCEPTION` and `EVV_EXCEPTION` is appended to the timesheet's `edit_codes`. The boundary is inclusive: a clock-in exactly sixty minutes after `start_at` still verifies, while sixty-one minutes late is an exception. A shift left in `EXCEPTION` keeps its timesheet blocked from billing: submission is refused with `ERR_EVV_NOT_VERIFIED` for as long as `evv_status` reads `EXCEPTION`.

**The billing-edit computation runs in four steps, and the order is pinned.** It must execute step one, then two, then three, then four, on exactly one timesheet at a time together with its shift's `scheduled_minutes`, `start_at` and `evv_status`, and the `billing_edit_ruleset` of the payer behind the case.

*Step one — clamp the worked interval.* The raw worked figure is the whole minutes from `clock_in_at` to `clock_out_at`, which must be greater than zero. The capped figure is the lesser of that raw figure and the shift's `scheduled_minutes` plus a fifteen-minute grace allowance. A nurse who stays two hours late is paid for fifteen extra minutes, not two hours.

*Step two — convert to units exactly once.* `gross_billable_units` is the capped minutes divided by 15, rounded half up to a whole number. This rounding happens once, per timesheet, and never on summed minutes.

*Step three — deduct.* A deduction applies when the timesheet's `evv_method` is `MANUAL` **or** the shift's `evv_status` is `EXCEPTION`; otherwise the base percentage is zero. When a deduction applies, the base percentage is selected from `gross_billable_units`: 5 percent when `gross_billable_units` is at most 8, 10 percent when it is between 9 and 16 inclusive, and 15 percent when it is 17 or more. That tier is chosen **from the gross figure and is never re-selected from the net result**, even when the net value would fall into a lower band. When the payer's `billing_edit_ruleset` is `STRICT_15MIN` and a deduction applies, a further 5 percentage points are added to the selected percentage; under `STANDARD_15MIN` nothing is added, and when no deduction applies the strict surcharge is not added either. The percentage deduction in units is `gross_billable_units` multiplied by that percentage, rounded **up** to the next whole unit. Separately, one further unit is deducted when `clock_in_at` is more than seven minutes after the shift's `start_at`, and zero otherwise. `edit_deduction_units` is the sum of the percentage deduction and that late-start unit.

*Step four — net out.* `net_billable_units` is `gross_billable_units` minus `edit_deduction_units`, floored at 0.

Alongside the numbers, `edit_codes` is assembled as an ascending-sorted set drawn from four members: `MANUAL_ENTRY` when `evv_method` is `MANUAL`; `EVV_EXCEPTION` when the shift's `evv_status` is `EXCEPTION`; `LATE_START` when the late-start unit was deducted; and `POST_EDIT` when at least one correction has been applied to this timesheet.

One aggregation rule follows from step two and must be respected wherever weekly settled units are needed: the weekly total is the **sum of per-timesheet** `net_billable_units`. Summing capped minutes across timesheets and rounding the total is forbidden and produces a different answer — two 250-minute visits yield 17 units each for 34 units in total, whereas rounding 500 minutes divided by 15 would give 33.

A `Nurse` may correct their own timesheet, supplying an `edit_reason` and optionally new `clock_in_at` and `clock_out_at` instants; `edit_reason` is null before any correction has been made. A correction is accepted while the timesheet is `CAPTURED` or `BILL_REJECTED`, only by the nurse on the assignment, and only if `clock_out_at` is non-null once the patch has been applied. The supplied instants overwrite the stored ones, `POST_EDIT` is appended to `edit_codes`, and `gross_billable_units`, `edit_deduction_units` and `net_billable_units` are recomputed from scratch. The timesheet lands in `EDITED` whether it arrived from `CAPTURED` or from `BILL_REJECTED`. A timesheet that has already reached `BILL_ACCEPTED` or `VOIDED` cannot be corrected: the attempt is `ERR_TIMESHEET_ALREADY_BILLED`.

Submission belongs to a `Scheduler`, never to the nurse who captured the visit. A timesheet may be submitted from `CAPTURED` or from `EDITED`, and only when the shift's `staffing_status` is `COMPLETED` and its `evv_status` is `VERIFIED`. Submission records `submitted_by_user_id` — null on every timesheet not yet submitted — and moves the row to `SUBMITTED`.

The payer's `PayerReviewer` then rules on it with a `decision` of either `ACCEPT` or `REJECT`, optionally supplying a `rejection_reason`. `ACCEPT` moves the timesheet `SUBMITTED → BILL_ACCEPTED` and adds its `net_billable_units` to the case's `billed_units_to_date`; the timesheet joins the settled utilization input set. `REJECT` moves it `SUBMITTED → BILL_REJECTED`, stores the supplied text in `rejection_reason` — null on any timesheet not rejected — and leaves `billed_units_to_date` untouched. A rejected timesheet can be reworked without limit: `BILL_REJECTED → EDITED → SUBMITTED → BILL_REJECTED` is a genuine cycle.

Finally, a `Scheduler` may void a timesheet with a `void_reason`. A void is accepted from `SUBMITTED`, `BILL_ACCEPTED` or `BILL_REJECTED` and moves the row to `VOIDED`, which is terminal alongside `BILL_ACCEPTED`. When the voided row had been accepted, exactly its `net_billable_units` are subtracted from the case's `billed_units_to_date` and its minutes leave the settled utilization total, returning both figures to their pre-acceptance values exactly.

### 3.8. Incidents, Hospitalization and the Hold Cycle

A `ClinicalSupervisor` files an incident against a case through `case_id`, classifying it with a `category` of `HOSPITALIZATION`, `MEDICATION_ERROR`, `EQUIPMENT_FAILURE`, `FALL` or `MISSED_VISIT`, a `severity` of `LOW`, `MODERATE` or `HIGH`, an `occurred_at` instant that must not be after the current logical clock, and a `narrative`. The filing supervisor's identifier is captured as `reported_by_user_id`, the report opens in `OPEN`, and filing is accepted while the case is `PENDING_STAFFING`, `ACTIVE` or `ON_HOLD`. Each report also records `triggered_case_hold`, which is true exactly when the `category` is `HOSPITALIZATION` or the `severity` is `HIGH`. A case's incident reports may be listed with an optional `status` filter.

Whether filing disturbs the schedule depends entirely on those two fields, and the branches are not symmetric.

- **A `HOSPITALIZATION` report of any severity** first sets the patient's `status` to `HOSPITALIZED`. Because the patient became `HOSPITALIZED`, the case moves `ACTIVE → ON_HOLD` with `hold_reason` `HOSPITALIZATION` and `hold_incident_report_id` set to this report. Because the case entered `ON_HOLD`, every shift of the case whose `staffing_status` is `OPEN`, `ASSIGNED` or `ESCALATED` and whose `start_at` is at or after the current logical clock becomes `CANCELLED` with `cancel_reason` `CASE_HOLD`, and each such shift's `ACTIVE` assignment becomes `CANCELLED` with the same reason. Because those assignments were cancelled, the affected nurses' `scheduled_minutes_this_week`, the authorization's `hours_committed_this_week` and the case's `unfilled_shift_count` and `fill_rate` are all recomputed.
- **A non-hospitalization report whose `severity` is `HIGH`** cascades the identical case hold and identical shift and assignment cancellations and identical recomputation, but with `hold_reason` `INCIDENT_REVIEW`, and the patient-status hop is skipped entirely — the child is not marked `HOSPITALIZED`.
- **A non-hospitalization report whose `severity` is `LOW` or `MODERATE`** cascades nothing at all. `triggered_case_hold` is false, the case stays `ACTIVE`, and no shift is touched.

Closing a report takes a `resolution` narrative and a `patient_returned_home` boolean, which defaults to false; both are stored on the report, and `resolution` is null on any report still `OPEN`. The report moves `OPEN → CLOSED`, its terminal state. When `patient_returned_home` is true and the patient's `status` is currently `HOSPITALIZED`, closing returns the patient's `status` to `ACTIVE`. What closing does **not** do is release the case: the case remains `ON_HOLD` until a supervisor explicitly resumes it.

A `ClinicalSupervisor` may also place a hold by hand, supplying a `hold_reason` of `HOSPITALIZATION`, `INCIDENT_REVIEW`, `AUTHORIZATION_EXPIRED` or `FAMILY_REQUEST`. A manual hold is accepted only from `ACTIVE`, records the supplied reason, leaves `hold_incident_report_id` null, and runs exactly the same shift and assignment cancellation cascade and the same recomputation described above. Whether cascaded or manual, `hold_reason` reads null on any case that is not `ON_HOLD`.

Resuming moves the case `ON_HOLD → ACTIVE` and is gated on four conditions. The case must be `ON_HOLD`. The patient must not be `HOSPITALIZED`, failing which the resume is `ERR_PATIENT_HOSPITALIZED`. When `hold_incident_report_id` is non-null, the referenced report's `status` must be `CLOSED`, failing which the resume is `ERR_INVALID_STATE`; and, as Section 2.11 specifies, the acting supervisor's `X-User-ID` must differ from that report's `reported_by_user_id`, failing which the resume is `ERR_SEGREGATION_OF_DUTIES`. The governing authorization must also be in one of the four staffable statuses. On success `hold_reason` and `hold_incident_report_id` are both cleared to null. Shifts cancelled during the hold are **not** restored — the `Scheduler` must publish replacements. Because `ACTIVE → ON_HOLD → ACTIVE` is a genuine cycle, a case may be held and resumed any number of times over its life.

### 3.9. Hour Reductions, Appeals, Renewal and Expiry

Payers do not always leave a grant alone. A `PayerReviewer` may notice a prospective reduction on an `ACTIVE` authorization, supplying `noticed_hours_per_week` — which must be strictly greater than zero and strictly less than the current `approved_hours_per_week` — together with a `reduction_reason`. The authorization moves `ACTIVE → REDUCTION_NOTICED`, the proposed figure is stored in `noticed_hours_per_week`, and `reduction_effective_at` is set to the current logical clock plus the payer's `reduction_notice_days` in days. Nothing else happens: no shift is touched and `approved_hours_per_week` is unchanged throughout the notice period. `noticed_hours_per_week` is null unless the authorization is `REDUCTION_NOTICED` or `UNDER_APPEAL`, and `reduction_effective_at` is null in the same circumstances.

The notice period is the family's window to fight back. A `CaseManager` files a dispute naming the grant through `authorization_id`, choosing a `dispute_type`, stating the `requested_hours_per_week` they ask the payer to restore or grant as a positive number with two decimal places, and supplying a `reason`. The filer's identifier is captured as `filed_by_user_id` and `filed_at` records the current logical clock; the dispute opens in `FILED` with `decided_hours_per_week`, `decided_at` and `reviewer_user_id` all null. Disputes may be listed with an optional `authorization_id` or `status` filter.

The two dispute types have different entry conditions and both drive the authorization to `UNDER_APPEAL`.

- A `REDUCTION_APPEAL` contests a noticed reduction. It requires the authorization to be `REDUCTION_NOTICED` and the current logical clock to be strictly before `reduction_effective_at`; a filing made on or after that instant, or against an authorization with no live notice, is refused with `ERR_DISPUTE_WINDOW_CLOSED`. On success the authorization moves `REDUCTION_NOTICED → UNDER_APPEAL` and the pending reduction is suspended.
- A `DENIAL_APPEAL` contests a partial approval. It requires the authorization to be `ACTIVE` and its `approved_hours_per_week` to be strictly less than the plan of care's `requested_hours_per_week` — there is nothing to appeal against a fully granted order. On success the authorization moves `ACTIVE → UNDER_APPEAL`.

Both types additionally require that no dispute of that authorization is currently `FILED` or `UNDER_REVIEW`, otherwise `ERR_DISPUTE_ALREADY_OPEN`; and both require the authorization's status to be one of `ACTIVE`, `REDUCTION_NOTICED` or `UNDER_APPEAL`, otherwise `ERR_AUTHORIZATION_NOT_ACTIVE`. As Section 2.8 notes, filing is deliberately exempt from the generic transition-state check so that these two specific codes surface instead.

A `PayerReviewer` takes a `FILED` dispute under review, moving it `FILED → UNDER_REVIEW` and recording `reviewer_user_id`. Deciding it requires the dispute to be `UNDER_REVIEW` and takes an `outcome` of `UPHELD`, `OVERTURNED` or `PARTIALLY_GRANTED`, an optional `decision_note`, and — for `PARTIALLY_GRANTED` only — a mandatory `decided_hours_per_week`. Every outcome stamps `decided_at` with the current logical clock; `decided_hours_per_week` stays null for `UPHELD` and `OVERTURNED`. All three outcomes are terminal for the dispute.

On a `REDUCTION_APPEAL`, the three outcomes diverge sharply:

- `UPHELD` sets `approved_hours_per_week` to the stored `noticed_hours_per_week`, clears both `noticed_hours_per_week` and `reduction_effective_at` to null, moves the authorization `UNDER_APPEAL → REDUCED`, and runs the trim cascade below.
- `PARTIALLY_GRANTED` requires `decided_hours_per_week` to sit strictly between the stored `noticed_hours_per_week` and the current `approved_hours_per_week` — strictly greater than the noticed figure and strictly less than the approved figure — otherwise the decision is refused with `ERR_DECIDED_HOURS_OUT_OF_RANGE`. It then sets `approved_hours_per_week` to `decided_hours_per_week`, clears the two notice fields, moves the authorization `UNDER_APPEAL → REDUCED`, and runs the same trim cascade.
- `OVERTURNED` leaves `approved_hours_per_week` unchanged, clears the two notice fields, and moves the authorization `UNDER_APPEAL → ACTIVE`. Zero shifts are cancelled.

On a `DENIAL_APPEAL`, every outcome returns the authorization `UNDER_APPEAL → ACTIVE` and no shift is ever trimmed, but the granted hours differ:

- `UPHELD` leaves `approved_hours_per_week` unchanged.
- `OVERTURNED` raises `approved_hours_per_week` to the smallest of three figures: the dispute's `requested_hours_per_week`, the payer's `weekly_hour_cap`, and the plan of care's `requested_hours_per_week`.
- `PARTIALLY_GRANTED` requires `decided_hours_per_week` to be strictly greater than the current `approved_hours_per_week` and at most that same smallest-of-three figure, otherwise `ERR_DECIDED_HOURS_OUT_OF_RANGE`; it then sets `approved_hours_per_week` to `decided_hours_per_week`.

In every case `hours_remaining_this_week` is recomputed against the new grant.

Where no dispute intervenes, the payer simply applies the notice once its instant arrives. Applying requires the authorization to be `REDUCTION_NOTICED`, the current logical clock to be at or after `reduction_effective_at` — an early attempt is `ERR_REDUCTION_NOT_EFFECTIVE` — and no dispute of that authorization to be `FILED` or `UNDER_REVIEW`. It sets `approved_hours_per_week` to `noticed_hours_per_week`, clears both notice fields, moves the authorization `REDUCTION_NOTICED → REDUCED`, and runs the same trim cascade as an upheld reduction appeal.

**The trim cascade.** Whenever `approved_hours_per_week` falls, some weeks may now be over-committed, and the surplus is removed deterministically. The new target in minutes is the new `approved_hours_per_week` multiplied by 60. The weeks considered are every ISO week whose week-start Monday falls in the half-open span from the week-start of the current logical clock up to the authorization's `effective_end`, processed in ascending week-start order. Within each week the following loop repeats. First, compute that week's committed minutes as the sum of `scheduled_minutes` over the shifts of the authorization's in-scope cases whose `staffing_status` is `ASSIGNED` or `COMPLETED` and whose `start_at` falls in that week's window; if the figure is at or below the target, stop and move to the next week. Otherwise gather the candidates: shifts of those in-scope cases whose `staffing_status` is `ASSIGNED`, whose `start_at` is at or after the current logical clock, and whose `start_at` falls in that week's window. If there are no candidates, stop and move on — already-worked hours are never clawed back, and `COMPLETED` shifts continue to count toward the week's committed minutes while remaining immune from cancellation. Otherwise the victim is the candidate with the greatest `start_at`, breaking a tie by the greatest `created_at` so that the most recently created shift loses first, and never consulting an identifier. That victim's `staffing_status` becomes `CANCELLED` with `cancel_reason` `AUTH_REDUCTION`, its `ACTIVE` assignment becomes `CANCELLED` with `cancel_reason` `AUTH_REDUCTION`, and the loop re-evaluates the week's committed minutes before deciding whether to cancel again. Shifts that are `OPEN`, `ESCALATED` or `PARENT_BACKUP` are neither counted toward the week nor eligible to be cancelled. After the cascade completes, the affected nurses' `scheduled_minutes_this_week` and the affected cases' `unfilled_shift_count` and `fill_rate` are recomputed.

**Renewal** extends coverage by issuing a successor rather than editing the incumbent. A `PayerReviewer` supplies the successor's `effective_end` and optionally a new `approved_hours_per_week`; when that figure is omitted the predecessor's grant carries over, and the successor's `effective_start` is the predecessor's `effective_end`, so the two windows abut without a gap. Both fiscal ceilings still apply — the new figure must not exceed the payer's `weekly_hour_cap` (`ERR_PAYER_HOUR_CAP_EXCEEDED`) nor the plan of care's `requested_hours_per_week` (`ERR_APPROVED_EXCEEDS_REQUESTED`). Renewal is additionally gated on demonstrated use. Take the **last completed** ISO week — the seven days from one week before the week-start of the current logical clock up to that week-start — and compute the settled minutes for the authorization over that week, using the settled basis of Section 3.3 with its `SUBMITTED`-or-`BILL_ACCEPTED` timesheet filter. Divide those minutes by `approved_hours_per_week` multiplied by 60 and round half up to four decimal places. That ratio must be at least 0.5000; a ratio of exactly 0.5000 passes, and anything below is refused with `ERR_RENEWAL_UTILIZATION_TOO_LOW`. The current, incomplete week is excluded from this gate entirely. On success a new authorization is created in `PENDING` with `supersedes_authorization_id` pointing at the predecessor and `renewal_chain_depth` set to the predecessor's `renewal_chain_depth` plus 1; the first authorization of a plan of care has `renewal_chain_depth` 0. The predecessor stays `ACTIVE` until the successor is activated.

**The handover** happens on the successor's activation and is a three-hop cascade. The successor moves `PENDING → ACTIVE`. Because its `supersedes_authorization_id` is non-null, the predecessor — which must be `ACTIVE` or `REDUCED` — moves to `SUPERSEDED`. Because the predecessor became `SUPERSEDED`, every case whose `authorization_id` pointed at the predecessor is repointed to the successor. Because those `authorization_id` values changed, each affected case's `fill_rate` and the successor's `hours_committed_this_week` and `hours_remaining_this_week` are recomputed against the successor's `approved_hours_per_week`.

**Expiry** is the checkpoint's job, and it too cascades. An authorization whose `status` is `ACTIVE`, `REDUCTION_NOTICED` or `REDUCED` and whose `effective_end` is at or before the current logical clock becomes `EXPIRED`; `PENDING` authorizations are left untouched by expiry. Because the authorization expired, every case whose `authorization_id` is that authorization and whose `status` is `PENDING_STAFFING` or `ACTIVE` becomes `ON_HOLD` with `hold_reason` `AUTHORIZATION_EXPIRED`. Because those cases entered `ON_HOLD`, their shifts whose `staffing_status` is `OPEN`, `ASSIGNED` or `ESCALATED` and whose `start_at` is at or after the current logical clock become `CANCELLED` with `cancel_reason` `AUTH_EXPIRY`. Because those shifts were cancelled, their `ACTIVE` assignments become `CANCELLED` with `cancel_reason` `AUTH_EXPIRY` and the affected nurses' `scheduled_minutes_this_week` are recomputed.

The checkpoint itself is an `AgencyAdmin` capability that takes no input and advances every clock-driven derivation to the current logical clock in one pass. It expires authorizations past their `effective_end` as just described, moves competency rows whose `expires_on` is at or before the current clock date from `VALID` to `EXPIRED`, re-derives `supervisory_status` to `OVERDUE` on every case whose `next_supervisory_visit_due_at` has been reached or passed, and cancels shifts that were never staffed and whose `start_at` now lies in the past, moving them from `OPEN` or `ESCALATED` to `CANCELLED`. It reports what it did as four counts: `expired_authorization_count`, `expired_competency_count`, `overdue_case_count`, and `cancelled_shift_count`.

## 4. Endpoint Definitions

Every path below is absolute. Status codes follow one rule: an operation that brings a new resource into existence answers with **201 Created**, and every other successful operation answers with **200 OK**. Concretely, 201 is returned by payer registration, nurse registration, competency attestation, patient enrolment, plan-of-care drafting, authorization issuance, authorization renewal, dispute filing, case opening, supervisory-visit recording, incident filing, shift publication, automatic staffing, manual assignment, and EVV clock-in — the last three because each of them creates an assignment or a timesheet row. Reads, transitions, corrections and the two operational controls all answer 200. The table below is intentionally minimal: request bodies, response bodies and side effects are specified in Sections 2 and 3, not here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/pdn/_clock/set_current_utc` | Set the deterministic logical clock used by every temporal rule. | `AgencyAdmin` |
| POST | `/pdn/_ops/run-daily-checkpoint` | Advance all clock-driven derivations: authorization expiry, competency expiry, supervisory overdue marking, and cancellation of unstaffed past shifts. | `AgencyAdmin` |
| POST | `/pdn/payers` | Register a payer with its weekly hour cap, appeal window and billing edit ruleset. | `AgencyAdmin` |
| GET | `/pdn/payers/{id}` | Read one payer. | `AgencyAdmin`, `PayerReviewer`, `CaseManager` |
| POST | `/pdn/nurses` | Register a nurse with licence type, licence number, licence expiry and weekly ceiling. | `AgencyAdmin` |
| GET | `/pdn/nurses/{id}` | Read one nurse including derived verified skills and weekly scheduled minutes. | `AgencyAdmin`, `Scheduler`, `ClinicalSupervisor`, `Nurse` |
| GET | `/pdn/nurses` | List nurses, optionally filtered by status or by a single required skill. | `AgencyAdmin`, `Scheduler` |
| POST | `/pdn/nurses/{id}/status` | Move a nurse between `ACTIVE`, `SUSPENDED` and `INACTIVE`. | `AgencyAdmin` |
| POST | `/pdn/nurses/{id}/competencies` | Record a validated competency for one skill with a validity window. | `ClinicalSupervisor` |
| GET | `/pdn/nurses/{id}/competencies` | List the competency rows of one nurse. | `AgencyAdmin`, `Scheduler`, `ClinicalSupervisor` |
| POST | `/pdn/nurse-competencies/{id}/revoke` | Revoke a competency after a failed supervisory validation. | `ClinicalSupervisor` |
| GET | `/pdn/nurses/{id}/continuity-score` | Read the continuity score of one nurse against one case under either basis. | `Scheduler`, `ClinicalSupervisor` |
| POST | `/pdn/patients` | Enrol a pediatric patient under a payer with clinical requirement flags. | `CaseManager` |
| GET | `/pdn/patients/{id}` | Read one patient. | `CaseManager`, `Scheduler`, `ClinicalSupervisor`, `PayerReviewer` |
| GET | `/pdn/patients` | List patients, optionally filtered by payer or status. | `CaseManager`, `PayerReviewer` |
| POST | `/pdn/plans-of-care` | Draft a plan of care requesting a weekly nursing-hour volume for a date range. | `CaseManager` |
| GET | `/pdn/plans-of-care/{id}` | Read one plan of care. | `CaseManager`, `PayerReviewer` |
| GET | `/pdn/plans-of-care` | List plans of care, optionally filtered by patient or status. | `CaseManager`, `PayerReviewer` |
| POST | `/pdn/plans-of-care/{id}/submit` | Submit a drafted or returned plan of care to the payer for authorization. | `CaseManager` |
| POST | `/pdn/plans-of-care/{id}/return` | Return a submitted plan of care to the agency for correction. | `PayerReviewer` |
| POST | `/pdn/authorizations` | Issue an authorization against a submitted plan of care. Guarded by optimistic concurrency on the plan of care. | `PayerReviewer` |
| GET | `/pdn/authorizations/{id}` | Read one authorization. | `PayerReviewer`, `CaseManager`, `Scheduler` |
| GET | `/pdn/authorizations` | List authorizations, optionally filtered by plan of care, payer, predecessor or status. | `PayerReviewer`, `CaseManager` |
| POST | `/pdn/authorizations/{id}/activate` | Activate an issued authorization so cases and shifts may be created against it. | `PayerReviewer` |
| GET | `/pdn/authorizations/{id}/utilization` | Read weekly utilization under the projected or the settled basis. | `PayerReviewer`, `CaseManager`, `Scheduler` |
| POST | `/pdn/authorizations/{id}/reduce` | Notice a prospective reduction of the approved weekly hours. | `PayerReviewer` |
| POST | `/pdn/authorizations/{id}/apply-reduction` | Apply a noticed reduction once its effective instant has arrived, trimming over-cap shifts. | `PayerReviewer` |
| POST | `/pdn/authorizations/{id}/renew` | Renew an authorization by issuing a successor, gated on last completed week's utilization. | `PayerReviewer` |
| POST | `/pdn/authorization-disputes` | File an appeal or hour-reduction dispute against an authorization. | `CaseManager` |
| GET | `/pdn/authorization-disputes/{id}` | Read one dispute. | `CaseManager`, `PayerReviewer` |
| GET | `/pdn/authorization-disputes` | List disputes, optionally filtered by authorization or status. | `CaseManager`, `PayerReviewer` |
| POST | `/pdn/authorization-disputes/{id}/review` | Take a filed dispute under review. | `PayerReviewer` |
| POST | `/pdn/authorization-disputes/{id}/decide` | Decide a dispute as `UPHELD`, `OVERTURNED` or `PARTIALLY_GRANTED`. | `PayerReviewer` |
| POST | `/pdn/cases` | Open a staffing case binding a patient to an active authorization under a supervisor. | `CaseManager` |
| GET | `/pdn/cases/{id}` | Read one case including derived fill metrics and supervisory status. | `CaseManager`, `Scheduler`, `ClinicalSupervisor`, `PayerReviewer` |
| GET | `/pdn/cases` | List cases, optionally filtered by patient, authorization, continuity nurse, holding incident or status. | `CaseManager`, `Scheduler`, `ClinicalSupervisor` |
| POST | `/pdn/cases/{id}/activate` | Activate a case so shifts can be published and staffed. | `CaseManager` |
| POST | `/pdn/cases/{id}/hold` | Place a case on hold, suspending all staffing activity. | `ClinicalSupervisor` |
| POST | `/pdn/cases/{id}/resume` | Resume a held case once the holding incident is closed and the patient is home. | `ClinicalSupervisor` |
| POST | `/pdn/cases/{id}/close` | Close a case permanently. | `CaseManager` |
| POST | `/pdn/cases/{id}/supervisory-visits` | Record a supervisory visit, resetting the cadence clock for the case. | `ClinicalSupervisor` |
| GET | `/pdn/cases/{id}/supervisory-visits` | List the supervisory visits of one case. | `ClinicalSupervisor`, `CaseManager`, `PayerReviewer` |
| POST | `/pdn/incident-reports` | File an incident or hospitalization report against a case. | `ClinicalSupervisor` |
| GET | `/pdn/incident-reports/{id}` | Read one incident report. | `ClinicalSupervisor`, `CaseManager`, `PayerReviewer` |
| GET | `/pdn/cases/{id}/incident-reports` | List the incident reports of one case. | `ClinicalSupervisor`, `CaseManager`, `PayerReviewer` |
| POST | `/pdn/incident-reports/{id}/close` | Close an incident report and, when the patient returned home, clear the patient hold. | `ClinicalSupervisor` |
| POST | `/pdn/shifts` | Publish an authorized shift on an active case with its required skill set. | `Scheduler` |
| GET | `/pdn/shifts/{id}` | Read one shift including its staffing, escalation and EVV dimensions. | `Scheduler`, `ClinicalSupervisor`, `CaseManager`, `Nurse` |
| GET | `/pdn/shifts` | List shifts, optionally filtered by case, staffing status, EVV status or start instant. | `Scheduler`, `ClinicalSupervisor`, `CaseManager` |
| GET | `/pdn/shifts/{id}/staffing-candidates` | Read the ranked eligible-nurse pool for a shift and the nurse the selector would choose. | `Scheduler` |
| POST | `/pdn/shifts/{id}/auto-staff` | Assign the shift to the nurse chosen by the selector. Guarded by optimistic concurrency on the shift. | `Scheduler` |
| POST | `/pdn/shifts/{id}/escalate` | Escalate an unfilled shift up the escalation tier ladder. | `Scheduler` |
| POST | `/pdn/shifts/{id}/parent-backup` | Record a parent backup arrangement covering an unfilled shift. | `Scheduler` |
| POST | `/pdn/shifts/{id}/clock-in` | EVV clock-in by the assigned nurse; opens the timesheet. | `Nurse` |
| POST | `/pdn/shifts/{id}/clock-out` | EVV clock-out; closes the timesheet and evaluates the verification outcome. | `Nurse` |
| POST | `/pdn/shift-assignments` | Manually assign a nurse to a shift. Guarded by optimistic concurrency on the shift. | `Scheduler` |
| GET | `/pdn/shift-assignments/{id}` | Read one shift assignment. | `Scheduler`, `ClinicalSupervisor`, `Nurse` |
| GET | `/pdn/shift-assignments` | List shift assignments, optionally filtered by shift, nurse or status. | `Scheduler`, `ClinicalSupervisor`, `Nurse` |
| POST | `/pdn/shift-assignments/{id}/cancel` | Cancel an active assignment, returning the shift to the open pool. | `Scheduler` |
| GET | `/pdn/shift-assignments/{id}/timesheets` | List the timesheets produced under one assignment. | `Scheduler`, `PayerReviewer`, `Nurse` |
| GET | `/pdn/timesheets/{id}` | Read one timesheet including worked minutes, gross units, billing edits and net units. | `Scheduler`, `PayerReviewer`, `Nurse` |
| PATCH | `/pdn/timesheets/{id}` | Correct the clock instants of a timesheet, recomputing every derived unit figure. | `Nurse` |
| POST | `/pdn/timesheets/{id}/submit` | Submit a verified timesheet for payer billing. | `Scheduler` |
| POST | `/pdn/timesheets/{id}/billing-decision` | Accept or reject a submitted timesheet for billing. | `PayerReviewer` |
| POST | `/pdn/timesheets/{id}/void` | Void a timesheet, reversing any billed units it contributed. | `Scheduler` |

## 5. Error Code Catalogue

Every failure response carries exactly one `error_id` from this catalogue, together with the HTTP status shown here. The conditions that trigger each identifier, and the order in which competing conditions are resolved, are specified in Section 2.8 and Section 3.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_PAYER_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PAYER_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PLAN_OF_CARE_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_NURSE_NOT_FOUND` | 404 |
| `ERR_COMPETENCY_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_TIMESHEET_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STALE_PLAN_OF_CARE_VERSION` | 412 |
| `ERR_STALE_SHIFT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CASE_ON_HOLD` | 409 |
| `ERR_AUTHORIZATION_NOT_ACTIVE` | 409 |
| `ERR_PATIENT_HOSPITALIZED` | 409 |
| `ERR_EVV_NOT_VERIFIED` | 409 |
| `ERR_TIMESHEET_ALREADY_BILLED` | 409 |
| `ERR_REDUCTION_NOT_EFFECTIVE` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_SUPERVISORY_VISIT_OVERDUE` | 409 |
| `ERR_NURSE_SHIFT_OVERLAP` | 409 |
| `ERR_PATIENT_CONCURRENCY_EXCEEDED` | 409 |
| `ERR_LICENSE_NUMBER_TAKEN` | 409 |
| `ERR_COMPETENCY_DUPLICATE` | 409 |
| `ERR_NURSE_SKILL_MISMATCH` | 422 |
| `ERR_COMPETENCY_EXPIRED` | 422 |
| `ERR_NURSE_LICENSE_EXPIRED` | 422 |
| `ERR_NURSE_NOT_ACTIVE` | 422 |
| `ERR_NURSE_EXCLUDED_FROM_CASE` | 422 |
| `ERR_NO_PARENT_BACKUP` | 422 |
| `ERR_SHIFT_OUTSIDE_AUTH_WINDOW` | 422 |
| `ERR_CLOCK_IN_TOO_EARLY` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 |
| `ERR_WEEKLY_HOURS_EXCEEDED` | 422 |
| `ERR_NURSE_WEEKLY_LIMIT_EXCEEDED` | 422 |
| `ERR_PAYER_HOUR_CAP_EXCEEDED` | 422 |
| `ERR_APPROVED_EXCEEDS_REQUESTED` | 422 |
| `ERR_RENEWAL_UTILIZATION_TOO_LOW` | 422 |
| `ERR_DECIDED_HOURS_OUT_OF_RANGE` | 422 |
| `ERR_NO_ELIGIBLE_NURSE` | 422 |
| `ERR_PAYER_MISMATCH` | 422 |
