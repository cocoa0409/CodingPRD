# Reemployment Rights Mediation API — Product Requirements Document

## 1. Introduction

When a Guard or Reserve member returns from uniformed service to find a civilian job gone, benefits lapsed, or seniority erased, the first path to relief is usually not a courtroom but a structured informal conversation. This document specifies the Reemployment Rights Case Handling and Employer Outreach API, the system of record for that conversation: it takes in a service member's complaint, places a certified volunteer ombudsman between the member and the employer under strict neutrality obligations, drives a documented mediation exchange, performs the statutory reemployment-rights analysis — advance notice, cumulative service limits, application deadlines, escalator placement — and, only when informal resolution fails, hands the matter to a federal enforcement agency with a complete audit trail behind it.

The same platform carries the program's employer-facing mission. Coordinators onboard employers, record statements of support, nominate and vet recognition awards against a published scoring rule, schedule outreach events, and run sector trend reports so that industries with recurring problems surface early. Because the program's determinations turn on statutory clocks and certification calendars rather than on whoever happens to be watching the wall clock, every temporal rule in this API is evaluated against an explicit, test-drivable logical clock, and every mediation artifact is held to an auditable documentation standard before an informal resolution can be accepted.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API, which is mounted under the `/reemployment` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying the caller's operational capacity. The system recognizes six roles, spelled exactly as follows: `Anonymous`, `ServiceMember`, `Employer`, `Ombudsman`, `ProgramCoordinator`, and `AgencyReviewer`. A request whose `X-User-Role` header is missing or names no declared role, or whose `X-User-ID` header is missing or empty for any role other than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED`. A caller whose role is not in an endpoint's authorized list — or who violates a transition-level actor rule, such as an `AgencyReviewer` attempting a submission that belongs to a `ProgramCoordinator` — is rejected with `ERR_UNAUTHORIZED_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ServiceMember`, `X-User-ID` is the `id` of the acting `ServiceMember`; ownership checks on any resource that references a service member compare the resource's `member_id` field to `X-User-ID`. When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer`, and ownership checks compare the resource's `employer_id` field to `X-User-ID`. When `X-User-Role` is `Ombudsman`, `X-User-ID` is the `id` of the acting `Ombudsman`; case-bound ownership checks compare the case's `assigned_ombudsman_id` field to `X-User-ID`. When `X-User-Role` is `Anonymous`, the caller is an unauthenticated registrant and no `X-User-ID` is required at all. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proctor_id` on a `TrainingRecord`, as `author_id` on a `CaseNote`, or as `nominated_by_id` on a `RecognitionAward`) but never compares it to any entity's `id`. When `X-User-Role` is `AgencyReviewer`, `X-User-ID` is likewise an opaque operator identifier that the server does not persist on any entity or compare to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Program Clock, Statutory Windows, and Lazy Expiry

All time-dependent behavior in the system is evaluated against a single logical clock, never against wall-clock time. Before any coordinator has set it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `ProgramCoordinator` advances it through a test-driving capability that accepts a `to_iso8601` instant; the endpoint returns success with no resource payload, and from that moment on every deadline, expiry, and window computation in the system evaluates against the new clock value.

Four program windows recur throughout this document. A mediation proposal gives the addressed party a 14-day response window. A case that has been escalated must reach its first agency submission within a 30-day referral window. A case closed without resolution may be reopened within a 60-day reopen window. Volunteer certifications and employer pledges run in months: a certification is valid for 24 months from the day it is granted, and a statement of support's pledge term defaults to 24 months from signing.

Time-bounded statuses expire lazily, on the next read or write of the affected entity, and every expiry comparison is strictly-greater. An ombudsman's certification flips from `CERTIFIED` to `EXPIRED` only when the logical clock is strictly later than `certification_expires_on`; at the exact expiry instant the volunteer is still `CERTIFIED`. A signed statement flips from `SIGNED` to `LAPSED` only when the clock is strictly later than `expires_on`. A proposed mediation round flips from `PROPOSED` to `EXPIRED` only when the clock is strictly later than its `response_deadline` — a response recorded at exactly the deadline instant is still timely — and a round that lapses this way pulls its case from `AWAITING_RESPONSE` back to `IN_MEDIATION` as it expires.

### 2.5. Common Resource Properties and Audit Records

Primary resources — `ServiceMember`, `Employer`, `Ombudsman`, `ReemploymentCase`, `MediationRound`, `Referral`, `StatementOfSupport`, `RecognitionAward`, and `OutreachEvent` — share a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.6.

Audit-grade records — `ServicePeriod`, `CaseNote`, `EligibilityAnalysis`, `BenefitAssessment`, and `TrainingRecord` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because these records are append-only statements of fact. A `ServicePeriod` in particular is immutable once created: the service record is history, and history is corrected by analysis, not by editing.

### 2.6. Optimistic Concurrency on Case-Bound Writes

Exactly two write operations are version-guarded, and both guard on the version of the `ReemploymentCase` they act upon. The case assignment operation and the eligibility-analysis recording operation each require the client to supply `expected_case_version`, a non-optional field carrying the case `version` the client last observed. If the case's current `version` has advanced beyond that observed value — because another coordinator has assigned the case, or a prior analysis has been recorded against it — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the case rather than overwrite work it has not seen. Both operations increment the case's `version` by 1 when they succeed. No other endpoint takes a version field of any kind; requests to any other operation must not include one.

### 2.7. Validation Order and Error Precedence

Every request is validated against the following categories in a fixed order, and when several violations coincide the earliest category determines the response. First, authentication: role and identity headers as described in §2.1, failing with `ERR_UNAUTHENTICATED`. Second, role authorization, including transition-level actor rules, failing with `ERR_UNAUTHORIZED_ROLE`. Third, request shape: required fields present, enum members valid, the system-reserved `AUDIT` note category refused on input, and intervals whose end is not strictly after their start, all failing with `ERR_INVALID_REQUEST`. Shape checks deliberately precede existence checks, because a field that is absent cannot be resolved to any entity at all. Fourth, existence: path identifiers are validated left to right, and body foreign keys are validated in the endpoint's declared input order — `member_id` before `employer_id`, and so on — each miss producing the corresponding 404 error. Fifth, ownership, evaluated only for resources that exist, failing with `ERR_OWNERSHIP_VIOLATION`. Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`. Seventh, the optimistic concurrency check of §2.6, failing with `ERR_STALE_CASE_VERSION`. Eighth, the integrity screens — the neutrality conflict check and the segregation-of-duties check — failing with `ERR_CONFLICT_OF_INTEREST` or `ERR_SEGREGATION_OF_DUTIES`. Ninth, the temporal windows — response deadline, referral window, reopen window — failing with `ERR_RESPONSE_DEADLINE_PASSED`, `ERR_REFERRAL_WINDOW_PASSED`, or `ERR_REOPEN_WINDOW_PASSED`. Tenth and last, the business constraints: the caseload cap, the one-open-round rule, documentation completeness, certification requirements, award vetting gates, nomination qualification, completed-period presence, service-period overlap, and venue double-booking.

### 2.8. Ownership, Neutrality, and Segregation of Duties

Entity-backed actors touch only their own rows. For resources that exist, the server compares the acting identity against the row's owning field — `member_id` for a service member, `employer_id` for an employer, `assigned_ombudsman_id` for an ombudsman acting on a case — as applicable per endpoint, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

Neutrality is a hard precondition of mediation, not a guideline. Every volunteer may declare an `employer_affiliation_id` at signup — a nullable reference to an `Employer` — and an ombudsman whose declared affiliation equals a case's employer may never be assigned to that case; the attempt is rejected with `ERR_CONFLICT_OF_INTEREST` (HTTP 409). The conflict screen applies identically to a first assignment and to a reassignment. So that employers can see who has declared a tie to them, each employer exposes a listing of the ombudsmen whose `employer_affiliation_id` names it.

Certification authority is equally fenced. The coordinator who records a volunteer's training is stamped onto each `TrainingRecord` as its `proctor_id`, taken from the acting coordinator's `X-User-ID` at recording time. A coordinator who appears as `proctor_id` on any of a volunteer's training records may not then certify or recertify that same volunteer; the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The segregation screen is evaluated before the training-requirements checks, so a conflicted proctor is turned away even when the volunteer's hours or exam scores would also have fallen short.

### 2.9. Precision, Rounding, and the Month Convention

Benefit mathematics in this system treats one month as exactly 30.44 days. Every month-valued result — health continuation, official pension credit, alternate pension credit — is expressed as a number rounded half-up to exactly 2 decimal places. Day counts, hour differences, caseloads, and award points are exact integers or exact numeric differences between timestamps, with no rounding applied. Where a formula in §3 specifies per-step rounding, the stated rounding order is part of the rule and two rounding orders that differ are reported as two different values rather than reconciled.

### 2.10. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right, and are rejected immediately with the 404 error corresponding to the first identifier that does not resolve: a request aimed at a round of a non-existent case fails with `ERR_CASE_NOT_FOUND` before the round is ever looked for. Each resource family has its own miss error — `ERR_MEMBER_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_OMBUDSMAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, and `ERR_AWARD_NOT_FOUND` — so the response always names the kind of thing that could not be found. The same left-to-right discipline governs sub-resource reads: rounds, notes, analyses, benefit assessments, and referrals hang beneath a case; service periods are listed beneath a member or an employer; statements of support and recognition awards beneath an employer; training records beneath an ombudsman. The parent must exist before its collection is read, and body foreign keys on creation payloads resolve in the endpoint's declared input order, so a case filed with both an unknown member and an unknown employer reports `ERR_MEMBER_NOT_FOUND` first.

## 3. Business Logic & Workflows

### 3.1. Intake: Members, Employers, and the Case File

Participation begins with self-registration. An `Anonymous` caller registers a service member by supplying a `full_name`, a contact `email`, a uniformed `branch` — one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, or `SPACE_FORCE` — and a reserve `component`, one of `ARMY_RESERVE`, `NAVY_RESERVE`, `MARINE_RESERVE`, `ARMY_GUARD`, or `AIR_GUARD`. Volunteer ombudsmen likewise self-register as `Anonymous` callers, supplying `full_name`, `email`, and optionally an `employer_affiliation_id`; a new volunteer begins life in `TRAINEE` status. Employers, by contrast, are onboarded only by a `ProgramCoordinator`, who records the employer's `legal_name`, its industry `sector` — `MANUFACTURING`, `RETAIL`, `HEALTHCARE`, `LOGISTICS`, `GOVERNMENT`, `CONSTRUCTION`, `HOSPITALITY`, or `TECHNOLOGY`, the attribute trend reporting groups by — and its headcount `size_tier` of `SMALL`, `MEDIUM`, or `LARGE`. A freshly onboarded employer starts with `resolved_case_count` and `open_case_count` at zero and `recognition_tier` at `NONE`; all three are derived values maintained by the system thereafter.

A service member files an informal case in their own name: the payload's `member_id` must equal the caller's `X-User-ID`, alongside the `employer_id` complained against, a primary `issue_type` of `REEMPLOYMENT`, `BENEFITS`, `PENSION`, `DISCRIMINATION`, or `RETALIATION`, and a free-text `description` of the problem. Three optional fields shape the later statutory analysis: `application_submitted_at` records when the member applied for reemployment and stays null when the member never applied; `excuse_claimed` (default false) asserts that advance notice was impossible or unreasonable; and `excuse_category` names the claimed basis — `ORDERS_SHORT_FUSE`, `OPERATIONAL_NECESSITY`, or `CLASSIFIED_MISSION` — a distinction only the lenient analysis variant honors. A new case enters in `INTAKE` status. A `ProgramCoordinator` then moves it `INTAKE → TRIAGE` for screening. At any point while the case is in `INTAKE` or `TRIAGE` the filing member may withdraw it into `CLOSED_WITHDRAWN`, which stamps `closed_at`; because no ombudsman has been assigned at either stage, withdrawal there touches no caseload. Coordinators and ombudsmen browse the docket through a paginated case listing that can be narrowed by `member_id`, `employer_id`, `assigned_ombudsman_id`, `status`, the employer's `sector`, or `issue_type`. Reading a single case is restricted to its parties and its overseer: the filing member, the respondent employer, the assigned ombudsman, and coordinators.

### 3.2. The Service Record: Periods, Orders, and Notice

Every statutory question downstream is answered from the member's service record, so the record is built first and built immutably. A service member — or a coordinator acting on the member's behalf — records a `ServicePeriod` with the `member_id` who served, the `employer_id` the service was performed away from, a `start_date`, the `orders_type` categorizing the orders (`DRILL`, `ANNUAL_TRAINING`, `ACTIVE_DUTY`, `NATIONAL_EMERGENCY`, or `PRESIDENTIAL_CALLUP`), and optionally an `end_date` and a `notice_given_at` instant marking when the member gave the employer advance notice. Dates are recorded at day precision, normalized to midnight UTC; a null `end_date` marks an ongoing period, and a null `notice_given_at` records that no notice was given. From these the system derives `duration_days`, the whole-day count from start to end, which stays null while the period is ongoing, and `chargeable`, which is true for every orders category except `NATIONAL_EMERGENCY` and `PRESIDENTIAL_CALLUP` — service under those two categories is exempt from the five-year cumulative cap discussed in §3.5.

One member's periods may not overlap, across all employers. Each period occupies the half-open interval from its `start_date` up to but not including its `end_date`; two periods of the same member — regardless of which employer each names — whose intervals intersect are rejected with `ERR_SERVICE_PERIOD_OVERLAP` (HTTP 422). Adjacency is not overlap: one period ending on exactly the day another begins is permitted. An ongoing period, having no end, is treated as extending indefinitely, so it collides with anything that starts after it. A member's periods across all employers are listed under the member, and the periods naming a given employer are listed under that employer.

### 3.3. Assignment and the Neutrality Screen

A coordinator assigns a triaged case to a volunteer, moving it `TRIAGE → ASSIGNED`, and may later reassign an `ASSIGNED → ASSIGNED` case when coverage changes; reassignment supersedes the prior assignment rather than stacking on it. Both forms of the assignment operation run the same battery of checks, evaluated in the global precedence order of §2.7. The state gate comes first: the target ombudsman must exist and be currently `CERTIFIED` once lazy expiry has been applied, failing with `ERR_OMBUDSMAN_NOT_CERTIFIED` — a volunteer `ON_LEAVE` keeps existing assignments but fails this gate for any new one. Next, the version guard: the request's `expected_case_version` must equal the case's current `version`, failing with `ERR_STALE_CASE_VERSION`. Then the neutrality screen of §2.8 rejects an ombudsman whose `employer_affiliation_id` equals the case's employer with `ERR_CONFLICT_OF_INTEREST`. Last, the caseload cap: an ombudsman's `active_caseload` counts that volunteer's cases in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` status, and assignment to a volunteer whose caseload has reached 4 is rejected with `ERR_CASELOAD_FULL` — exactly 4 blocks.

When assignment succeeds, the case records the `assigned_ombudsman_id`, the case's `version` increments by 1, and the caseload arithmetic follows derivedly: the newly assigned volunteer's `active_caseload` rises by one, and on reassignment the previous volunteer's falls by one. Because `active_caseload` is derived at read time from the cases themselves, these shifts need no separate bookkeeping — but they are observable immediately on the ombudsman's record.

### 3.4. Mediation Rounds and the Documentation Standard

The assigned ombudsman — and only the assigned ombudsman — opens a mediation round on a case in `ASSIGNED` or `IN_MEDIATION` status, supplying the `case_id`, a `proposal_text` describing the proposed informal resolution, and the `addressed_to` party who must respond, either `EMPLOYER` or `MEMBER`. Rounds are numbered per case starting at 1, each new round's `round_number` being the count of the case's prior rounds plus one. Only one round per case may be open at a time: opening a second while a `PROPOSED` round exists is rejected with `ERR_ROUND_ALREADY_OPEN`. Each new round computes its `response_deadline` as 14 days after its creation and opens in `PROPOSED` status, and its creation moves the case into `AWAITING_RESPONSE` — the case's `open_round_count`, the count of its `PROPOSED` rounds, becoming 1 with the first round and increasing by 1 with each subsequent one.

The addressed party answers: the employer when `addressed_to` is `EMPLOYER`, the member when it is `MEMBER`, each acting on their own case. The `response` is one of `ACCEPT`, `COUNTER`, or `DECLINE`, moving the round `PROPOSED → ACCEPTED`, `PROPOSED → COUNTERED`, or `PROPOSED → DECLINED` respectively; a counter carries the party's `counter_text`, which is stored on the round, and any recorded response stamps `responded_at`. Answers are accepted only while the round is still `PROPOSED` — answering a round that has already reached any terminal status fails with `ERR_ROUND_NOT_OPEN` — and only while the logical clock has not passed the round's `response_deadline`. When the clock has passed the deadline, the round flips `PROPOSED → EXPIRED`, the case falls back from `AWAITING_RESPONSE` to `IN_MEDIATION`, and the late answer itself fails with `ERR_RESPONSE_DEADLINE_PASSED` (HTTP 422); at exactly the deadline instant an answer is still timely. A `COUNTERED` or `DECLINED` round — or one that expires, whether discovered lazily on a read of the case's rounds or on a response attempt — likewise returns the case from `AWAITING_RESPONSE` to `IN_MEDIATION`, decrementing `open_round_count` by 1, and the ombudsman may then open the next round.

Acceptance is the consequential branch, and it is gated on the documentation standard. The case's `documentation_complete` predicate, recomputed whenever the case is read, requires four things at once, with system-generated `AUDIT` notes never counting toward any category: at least one note of `note_type` `INTAKE`; at least as many `CONTACT` notes as the case has mediation rounds of any status; at least one `RESOLUTION` note; and — only when the case's `issue_type` is `BENEFITS` or `PENSION` — at least one `EMPLOYER_EDUCATION` note. If the predicate is false when an `ACCEPT` arrives, the response is rejected with `ERR_DOCUMENTATION_INCOMPLETE` and the round stays `PROPOSED` with no side effects firing. When the predicate holds, acceptance moves the round to `ACCEPTED` with `responded_at` stamped and resolves the case `AWAITING_RESPONSE → RESOLVED_INFORMAL`: the employer's `resolved_case_count` increases by 1 and its `open_case_count` decreases by 1, the assigned ombudsman's caseload drops by 1, and the case's `closed_at` is set to the logical clock.

Case notes are the raw material of that standard. An ombudsman may document only cases assigned to them; coordinators may document any case. A note carries the `case_id`, a `note_type` of `INTAKE`, `CONTACT`, `EMPLOYER_EDUCATION`, `RESOLUTION`, or `AUDIT`, and a free-text `body`; the `AUDIT` category is reserved for system-generated entries and is refused on input with `ERR_INVALID_REQUEST`. The server stamps each note with the author's `author_role` and `author_id` taken from the request headers — audit strings, not entity references. A case's notes, including the system's own audit entries, are readable by ombudsmen and coordinators, while the case's rounds are readable by all four case parties.

### 3.5. Statutory Eligibility Analysis

The assigned ombudsman or a coordinator runs a statutory eligibility analysis on a case, choosing the interpretive `variant` — `STRICT` or `LENIENT` — and presenting `expected_case_version` under the optimistic concurrency rule of §2.6, so a stale read of the case fails with `ERR_STALE_CASE_VERSION` before any analysis is stored. Each run records a new `EligibilityAnalysis` whose `case_id` is bound to the case addressed by the request rather than supplied in the payload, whose per-case `sequence_number` starts at 1 and climbs by one per run — the case's current analysis is the one with the highest `sequence_number` — and whose creation increments the case's `version` by 1. A case's analyses are listed in sequence order, the newest last, and are readable by all four case parties. Every run follows a pinned evaluation order: disputed-period selection first, then notice, then the cumulative service cap, then the deadline band; the three component booleans are always computed and stored even when an earlier one is already false.

Selection picks the disputed period from the member's completed service for this employer: periods of the member-employer pair whose `end_date` is set and falls on or before the logical clock. When no completed period exists for the pair, the analysis aborts with `ERR_NO_COMPLETED_SERVICE_PERIOD` (HTTP 422). Among the candidates the disputed period is the most recent — ordered by `end_date` latest first, ties broken by later `start_date`, then by later `created_at`, and never by identifier. Its `duration_days` becomes the analysis's `disputed_period_duration_days`.

Notice is measured in hours. `notice_hours_advance` is the signed number of hours from the disputed period's `notice_given_at` to its `start_date` — negative when notice came after service began, and null when no notice was given at all. Under the `STRICT` variant, `notice_satisfied` is true only when notice was given at least 24 hours before the start; the excuse fields are ignored entirely, so missing or short notice always fails strict review. Under the `LENIENT` variant, `notice_satisfied` is the strict result or, failing that, true when the case's `excuse_claimed` is true and its `excuse_category` is non-null — a claimed, categorized excuse cures even missing or short notice.

The cumulative cap sums the member's completed, chargeable service for this employer: `cumulative_chargeable_days` totals `duration_days` over completed periods of the pair whose orders are not `NATIONAL_EMERGENCY` or `PRESIDENTIAL_CALLUP`, ongoing periods excluded. `service_limit_ok` holds when that total is at most 1,825 days — the five-year cumulative cap — and a total of exactly 1,825 passes.

The deadline band keys on the disputed period's length: at most 30 days is `SHORT`, 31 through 180 days is `MID`, and 181 days or more is `LONG`, stored as `duration_band`. The band fixes `application_deadline_days` — 1 day for `SHORT`, 14 for `MID`, 90 for `LONG` — and `application_deadline_date` is the disputed period's `end_date` plus that many days. `deadline_satisfied` holds when the case's `application_submitted_at` is set and falls on or before the deadline date; an application on exactly the deadline date passes, and a member who never applied fails. The band also fixes the statutory remedy class: `escalator_position_class` is `SAME_POSITION` for `SHORT`, `SENIORITY_ESCALATED` for `MID`, and `ESCALATED_WITH_RETRAINING` for `LONG`. The analysis's `overall_eligible` is the conjunction of `notice_satisfied`, `service_limit_ok`, and `deadline_satisfied`.

### 3.6. Benefits Continuation and Pension Accrual

Alongside the eligibility analysis, the assigned ombudsman or a coordinator computes the case's benefit picture. A case supports at most one `BenefitAssessment`; a second attempt for the same case is rejected with `ERR_INVALID_STATE`. The assessment is requested with the `case_id` alone and draws on the same completed-period selector as the analysis — periods of the member-employer pair with an `end_date` on or before the logical clock — so a case with no completed period for the pair fails here too with `ERR_NO_COMPLETED_SERVICE_PERIOD`. Unlike the service cap, pension and health math counts every completed period, chargeable and cap-exempt alike.

Health continuation is computed in aggregate: the pair's total completed service days are divided by 30.44, the quotient is rounded half-up to 2 decimal places, and `health_continuation_months` is the lesser of that figure and 24 — the statutory cap binds only above 24, so a raw figure of exactly 24 stands uncapped. Pension credit is reported in twin values because the rounding order matters. The official figure, `pension_credit_months_official`, rounds per period first: each period's days are divided by 30.44 and rounded half-up to 2 decimal places, the per-period figures are summed, and the sum is rounded half-up to 2 decimal places. The informational comparison, `pension_credit_months_alternate`, aggregates first: all days are summed, divided by 30.44, and rounded half-up to 2 decimal places once. The two diverge whenever per-period rounding accumulates differently — periods of 10, 20, and 30 days yield an official 0.33 + 0.66 + 0.99 = 1.98 against an alternate 60 / 30.44 = 1.97.

The assessment also tracks the employer-education duty. `education_required` is true when the case's `issue_type` is `BENEFITS` or `PENSION`. `education_satisfied` is not stored but recomputed at every read: it is true when the case carries at least one `EMPLOYER_EDUCATION` note. Reading a case's assessments returns an array of zero or one element, and is open to all four case parties.

### 3.7. Escalation, Referral, Withdrawal, and Reopening

When mediation stalls, the assigned ombudsman escalates the case — from `IN_MEDIATION`, or from `AWAITING_RESPONSE` while a proposal is still out — into `ESCALATION_PENDING`. Escalation demands evidence that the informal track has been tried: at least one of the case's rounds must be `DECLINED` or `EXPIRED`, failing with `ERR_NO_EXHAUSTED_ROUND` otherwise. Escalation stamps the case's `escalated_at` with the logical clock, anchoring the referral window that follows.

The assigned ombudsman then drafts a referral, naming the `case_id` — which must be in `ESCALATION_PENDING` — the federal enforcement `agency` (`DOL_VETS`, `DOJ_CIVIL_RIGHTS`, or `OPM`), and a narrative `summary`. The draft is born in `DRAFT` status with `created_by_ombudsman_id` stamped from the drafter's `X-User-ID`, an audit string rather than an entity reference. Only a `ProgramCoordinator` submits: a `DRAFT → SUBMITTED` transition requires the case still in `ESCALATION_PENDING` and, on the first submission only, requires the logical clock to be no later than 30 days after `escalated_at` — submission at exactly the 30-day mark is inside the window, while a later first submission fails with `ERR_REFERRAL_WINDOW_PASSED` (HTTP 422). The first submission stamps `submitted_at`. Submitting cascades through the case: the case moves `ESCALATION_PENDING → REFERRED`, any of its rounds still `PROPOSED` are closed as `CLOSED_MOOT` with a system `AUDIT` note appended to the case for each round so closed, and the assigned ombudsman's caseload drops by 1.

From `SUBMITTED`, the matter belongs to the agency. An `AgencyReviewer` either acknowledges the referral into `ACKNOWLEDGED` — terminal — or returns it for more information into `RETURNED_FOR_INFO`, storing the agency's `info_request_note`. A returned referral is resubmitted by a coordinator, `RETURNED_FOR_INFO → SUBMITTED`, now requiring the case to be `REFERRED`; the 30-day window does not re-apply to resubmissions. A coordinator may also withdraw a `DRAFT` referral into `WITHDRAWN`, and the same withdrawal arrives by cascade when the case itself is withdrawn or the drafting ombudsman is decertified.

The member may abandon the case at almost any point. Withdrawal moves the case from `INTAKE`, `TRIAGE`, `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` into `CLOSED_WITHDRAWN` and always stamps `closed_at`. From `ASSIGNED` onward it also decrements the assigned ombudsman's caseload and clears the case's `assigned_ombudsman_id`; from `AWAITING_RESPONSE` it additionally closes each `PROPOSED` round as `CLOSED_MOOT` with an audit note apiece; from `ESCALATION_PENDING` it withdraws the case's `DRAFT` referrals alongside. The assigned ombudsman, giving up on a stalled matter, may instead close it from `IN_MEDIATION` or `AWAITING_RESPONSE` into `CLOSED_UNRESOLVED` — stamping `closed_at`, releasing the caseload, clearing the assignment, and mooting any open rounds with audit notes when closing from `AWAITING_RESPONSE`. All state-change requests on these lifecycles name their target in a `to_status` field, and the case and ombudsman transitions accept an optional free-text `reason`.

Closure without resolution is not necessarily the end. The member may reopen a `CLOSED_UNRESOLVED` case back into `TRIAGE` — the case re-enters triage unassigned — provided the logical clock is no later than 60 days after `closed_at`; reopening exactly 60 days after closure is inside the window, and a later attempt fails with `ERR_REOPEN_WINDOW_PASSED` (HTTP 422). A successful reopen clears `closed_at`. `RESOLVED_INFORMAL`, `REFERRED`, and `CLOSED_WITHDRAWN` are terminal: no transition leaves them.

### 3.8. The Volunteer Lifecycle: Training, Certification, Leave, and Decertification

A volunteer's road to case work runs through recorded training. A coordinator records each completed module as a `TrainingRecord` naming the `ombudsman_id`, the `module_code` — `CORE_LAW`, `MEDIATION_SKILLS`, `DOCUMENTATION`, `ETHICS_NEUTRALITY`, or `ELECTIVE` — the credit `hours`, the `exam_score` between 0 and 100, and the `completed_on` instant; the recording coordinator is stamped as `proctor_id` per §2.8. The volunteer's `total_training_hours` is derived as the sum of hours over all of their records, core and elective alike.

Certification moves a `TRAINEE` to `CERTIFIED` and demands three things. Each core module — `CORE_LAW`, `MEDIATION_SKILLS`, and `DOCUMENTATION` — must have at least one record with an `exam_score` of 80 or better; the `total_training_hours` must reach at least 20; and the segregation-of-duties screen of §2.8 must pass, evaluated before the training checks per the precedence order of §2.7. Shortfalls in the modules or hours fail with `ERR_CERTIFICATION_REQUIREMENTS_UNMET` (HTTP 422); a conflicted proctor fails with `ERR_SEGREGATION_OF_DUTIES`. Certification stamps `certified_on` with the logical clock and sets `certification_expires_on` 24 months later.

A certified volunteer may be placed `ON_LEAVE` by a coordinator and returned to `CERTIFIED` the same way; leave retains the volunteer's existing assignments but, per §3.3, fails the certification gate on new ones. The return from leave applies lazy expiry first: if the clock has already passed `certification_expires_on`, the volunteer's true status is `EXPIRED` and the return is rejected with `ERR_INVALID_STATE`. Expiry itself is lazy and strictly-greater per §2.4: `CERTIFIED` flips to `EXPIRED` on any read or write once the clock is strictly past `certification_expires_on`, and an ombudsman read surfaces that flip. Recertification moves `EXPIRED → CERTIFIED` on a lighter standard: at least one training record whose `completed_on` falls within the trailing 24 months of the logical clock, with the hours over those recent records totaling at least 8, and the segregation screen applied again. Recertification re-stamps `certified_on` and extends `certification_expires_on` a fresh 24 months.

Decertification is the program's sanction, and it cascades. A coordinator may decertify a `CERTIFIED` volunteer — or remove a mere `TRAINEE` — into the terminal `DECERTIFIED` status, supplying a `reason`. Decertifying a certified volunteer unwinds their active docket in three linked steps: every case assigned to them in `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` reverts to `TRIAGE` with its `assigned_ombudsman_id` cleared, the caseload drop following derivedly; each reverted case's `PROPOSED` rounds are closed `CLOSED_MOOT`; and a system `AUDIT` note is appended to the case for every round so closed. Any `DRAFT` referrals the decertified volunteer created on the reverted cases are withdrawn as well. A volunteer's training records are listed under the ombudsman's own record.

### 3.9. Recognition, Outreach, and Trend Reporting

The employer-facing half of the program runs on pledges, awards, and events. An employer — acting for itself, so the payload's `employer_id` must equal its `X-User-ID` — or a coordinator pledges a statement of support, naming the `signer_name` and `signer_title` and optionally a `term_months` pledge term that defaults to 24 months. The pledge rests in `PLEDGED` until the employer or a coordinator signs it, `PLEDGED → SIGNED`, which stamps `signed_on` with the logical clock and computes `expires_on` as the term length after signing. A signed statement lapses lazily into `LAPSED` once the clock is strictly past `expires_on`, and a lapsed statement may be renewed — `LAPSED → SIGNED` — which re-stamps `signed_on` and recomputes `expires_on` afresh. A coordinator may revoke a statement from `PLEDGED` or `SIGNED` into the terminal `REVOKED`. An employer's statement listing applies the lazy lapse on read.

Recognition awards begin with a nomination by an ombudsman or coordinator, carrying the `employer_id`, the nominated `tier` of `BRONZE`, `SILVER`, or `GOLD`, and a `rationale`; the server stamps `nominated_by_id` and `nominated_by_role` from the nominator's headers. An ombudsman nominator must have earned standing with that employer: at least one case assigned to that ombudsman and closed `RESOLVED_INFORMAL` for this employer, failing with `ERR_NOMINATION_NOT_QUALIFIED` otherwise. The award opens in `NOMINATED`.

Vetting, `NOMINATED → VETTED`, is where the scoring rule bites, and it runs in a pinned order at the vetting instant. The employer must hold at least one statement in `SIGNED` status — lazy lapse applied first — and its `resolved_case_count` must clear the nominated tier's gate: at least 1 for `BRONZE`, 3 for `SILVER`, 5 for `GOLD`. Then the snapshot computes: `score_base` awards 10 points per resolved case, adds 15 when a signed statement exists, and subtracts 10 per open case; `tier_qualified` is read from `score_base` alone — at least 60 qualifies `GOLD`, at least 40 qualifies `SILVER`, at least 20 qualifies `BRONZE` — and a base below 20 fails vetting outright; `score_bonus` adds 30 keyed to a `GOLD` qualification, 15 to `SILVER`, 5 to `BRONZE`; and `score_final` is the base plus the bonus. Failing the statement requirement, the resolved-case gate, or the base-score floor all surface as `ERR_AWARD_ELIGIBILITY_UNMET`. The qualified tier is never recomputed from the final score: a base of 35 qualifies `BRONZE`, the 5-point bonus lifts the final to 40, and the tier stays `BRONZE` even though 40 reaches the `SILVER` gate. Conferral, `VETTED → CONFERRED`, then recomputes the employer's `recognition_tier` as the highest tier among its `CONFERRED` awards, or `NONE` when it has none. An award may instead be declined from `NOMINATED` or `VETTED` into `DECLINED`; `CONFERRED` and `DECLINED` are terminal.

Coordinators schedule outreach events with a `title`, a `venue` identifier string, a `starts_at`, an `ends_at` strictly after the start, and a `topic` of `RIGHTS_OVERVIEW`, `BENEFITS_BRIEFING`, `EMPLOYER_RECOGNITION`, or `HIRING_FAIR`; the event opens in `PLANNED`. Venues cannot be double-booked: an event whose venue matches another event's is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 422) when their intervals overlap, where each event occupies a closed interval that includes its full running time plus a 60-minute teardown buffer after it — so unlike adjacent service periods, two events that merely touch count as overlapping — and `CANCELLED` events are excluded from the comparison set. A planned event opens from `PLANNED` into `OPEN`, and an event in `OPEN` concludes into `CONCLUDED` only once the logical clock has reached its `ends_at`; concluding earlier fails with `ERR_INVALID_STATE`. Either a planned or an open event may be cancelled into `CANCELLED`, which removes it from the venue overlap set. `CONCLUDED` and `CANCELLED` are terminal.

Finally, coordinators mine the docket for patterns. The sector-trend report takes a `sector`, a `period_start`, and a `period_end`, and considers the cases whose `created_at` falls in the half-open window from `period_start` up to but not including `period_end` and whose employer's sector matches. The report echoes the `sector`, `period_start`, and `period_end` and computes `total_cases`, the count of cases in the window; `resolved_count`, those in `RESOLVED_INFORMAL`; `repeat_employer_count`, the number of distinct employers with at least 2 cases in the window; and `top_issue_type`, the most frequent `issue_type` in the window, with ties broken in favor of the tied issue type whose earliest-created case in the window comes first. An empty window reports zero counts and a null `top_issue_type`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a member, onboarding an employer, signing up an ombudsman, recording a service period, filing a case, storing an analysis, opening a round, appending a note, computing a benefit assessment, drafting a referral, pledging a statement, nominating an award, scheduling an event, or recording training — return `201 Created` with the new resource in the response. Operations that modify an existing resource — lifecycle transitions, assignment, responses, and the clock-setting capability — return `200 OK`. Reads return `200 OK`. The clock endpoint returns `200 OK` with no resource payload.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reemployment/_clock/set_current_utc` | Set the logical clock | ProgramCoordinator |
| POST | `/reemployment/members` | Register a service member | Anonymous |
| GET | `/reemployment/members/{id}` | Read a service member | ServiceMember, ProgramCoordinator |
| POST | `/reemployment/employers` | Onboard an employer | ProgramCoordinator |
| GET | `/reemployment/employers/{id}` | Read an employer with derived counters | Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/ombudsmen` | Volunteer ombudsman signup | Anonymous |
| GET | `/reemployment/ombudsmen/{id}` | Read an ombudsman (lazy certification expiry applied) | Ombudsman, ProgramCoordinator |
| POST | `/reemployment/ombudsmen/{id}/state` | Ombudsman lifecycle: certify/recertify, leave, decertify | ProgramCoordinator |
| GET | `/reemployment/employers/{id}/affiliated-ombudsmen` | Ombudsmen declaring affiliation to this employer | Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/service-periods` | Record a period of uniformed service | ServiceMember, ProgramCoordinator |
| GET | `/reemployment/members/{id}/service-periods` | Service periods of a member | ServiceMember, Ombudsman, ProgramCoordinator |
| GET | `/reemployment/employers/{id}/service-periods` | Service periods naming an employer | Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/cases` | File an informal reemployment-rights case | ServiceMember |
| GET | `/reemployment/cases/{id}` | Read a case (parties and assigned ombudsman only) | ServiceMember, Employer, Ombudsman, ProgramCoordinator |
| GET | `/reemployment/cases` | List cases with filters and pagination | Ombudsman, ProgramCoordinator |
| POST | `/reemployment/cases/{id}/assign` | Assign or reassign an ombudsman (version-guarded) | ProgramCoordinator |
| POST | `/reemployment/cases/{id}/state` | Case lifecycle transitions and reopen | ServiceMember, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/cases/{id}/eligibility-analysis` | Run and store a statutory eligibility analysis (version-guarded) | Ombudsman, ProgramCoordinator |
| GET | `/reemployment/cases/{id}/eligibility-analyses` | All analyses of a case, newest last | ServiceMember, Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/mediation-rounds` | Open a mediation round on an assigned case | Ombudsman |
| POST | `/reemployment/mediation-rounds/{id}/respond` | Respond to a proposal (accept, counter, decline) | Employer, ServiceMember |
| GET | `/reemployment/cases/{id}/rounds` | Mediation rounds of a case (lazy round expiry applied) | ServiceMember, Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/case-notes` | Append a documentation note to a case | Ombudsman, ProgramCoordinator |
| GET | `/reemployment/cases/{id}/notes` | Documentation notes of a case, including system audit notes | Ombudsman, ProgramCoordinator |
| POST | `/reemployment/benefit-assessments` | Compute benefit continuation and pension accrual (one per case) | Ombudsman, ProgramCoordinator |
| GET | `/reemployment/cases/{id}/benefit-assessments` | Benefit assessment(s) of a case (0 or 1 element) | ServiceMember, Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/referrals` | Draft a referral to a federal enforcement agency | Ombudsman |
| POST | `/reemployment/referrals/{id}/state` | Referral lifecycle: submit, acknowledge, return for info, withdraw | ProgramCoordinator, AgencyReviewer |
| GET | `/reemployment/cases/{id}/referrals` | Referrals of a case | ServiceMember, Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/statements-of-support` | Pledge a statement of support | Employer, ProgramCoordinator |
| POST | `/reemployment/statements-of-support/{id}/state` | Statement lifecycle: sign, renew, revoke | Employer, ProgramCoordinator |
| GET | `/reemployment/employers/{id}/statements-of-support` | Statements of an employer (lazy lapse applied) | Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/recognition-awards` | Nominate an employer for recognition | Ombudsman, ProgramCoordinator |
| POST | `/reemployment/recognition-awards/{id}/state` | Award lifecycle: vet, confer, decline | ProgramCoordinator |
| GET | `/reemployment/employers/{id}/recognition-awards` | Awards of an employer | Employer, Ombudsman, ProgramCoordinator |
| POST | `/reemployment/outreach-events` | Schedule an outreach event | ProgramCoordinator |
| POST | `/reemployment/outreach-events/{id}/state` | Event lifecycle: open, conclude, cancel | ProgramCoordinator |
| POST | `/reemployment/training-records` | Record a completed training module | ProgramCoordinator |
| GET | `/reemployment/ombudsmen/{id}/training-records` | Training records of an ombudsman | Ombudsman, ProgramCoordinator |
| GET | `/reemployment/reports/sector-trends` | Sector trend report over a half-open creation window | ProgramCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_NOT_FOUND` | 404 Not Found |
| `ERR_OMBUDSMAN_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUND_NOT_OPEN` | 409 Conflict |
| `ERR_OMBUDSMAN_NOT_CERTIFIED` | 409 Conflict |
| `ERR_CONFLICT_OF_INTEREST` | 409 Conflict |
| `ERR_CASELOAD_FULL` | 409 Conflict |
| `ERR_ROUND_ALREADY_OPEN` | 409 Conflict |
| `ERR_DOCUMENTATION_INCOMPLETE` | 409 Conflict |
| `ERR_NO_EXHAUSTED_ROUND` | 409 Conflict |
| `ERR_AWARD_ELIGIBILITY_UNMET` | 409 Conflict |
| `ERR_NOMINATION_NOT_QUALIFIED` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_RESPONSE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_REFERRAL_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_REOPEN_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_SERVICE_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_VENUE_DOUBLE_BOOKED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_REQUIREMENTS_UNMET` | 422 Unprocessable Entity |
| `ERR_NO_COMPLETED_SERVICE_PERIOD` | 422 Unprocessable Entity |
