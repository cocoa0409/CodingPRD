# Military Transition Internship API — Product Requirements Document

## 1. Introduction

Every year, thousands of service members approach the end of their service contracts holding skills the civilian labor market urgently wants but no structured way to demonstrate. The months immediately preceding separation are the single best window for a supervised civilian internship — and the easiest window to lose to paperwork, unclear approval chains, and employers who confuse a training program with free labor. This document specifies the Military Transition Internship API, the backend for a SkillBridge-style transition program: eligible members, still on active duty and still paid by the service, are matched into employer-hosted internships during a tightly bounded eligibility window before their scheduled separation date.

The API governs the full program surface. Installations publish command-level approval policies that legitimately vary from command to command. Members progress through the Transition Assistance Program and submit program applications that unit commanders approve or deny, with a bounded appeal cycle adjudicated under segregation of duties. Employers are authorized as program providers, reviewed on a fixed cadence, and lapsed automatically when review deadlines slip. Internship matches pair an approved application with an employer opening under skills, location, schedule, and capacity constraints, and carry a parallel training-plan dimension that the installation must approve before the match can be approved. During execution, weekly supervision reports advance learning objectives and a wage-record ledger enforces the cardinal rule of the program — the employer never pays the intern. Compliance audits score employer conduct and can revoke an employer outright, cascading through every opening and match the employer operates. After separation, conversion records capture which internships turned into jobs, feeding a dual-variant hiring-rate measure.

All endpoints are mounted under the `/skillbridge` prefix. The system does not use wall-clock time; all temporal rules evaluate against a server-held logical clock described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly six roles: `ProgramOffice`, `TransitionCounselor`, `ServiceMember`, `UnitCommander`, `InstallationAuthority`, and `EmployerRep`. A request missing either header, or carrying a role name outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

How `X-User-ID` binds to stored data differs by role:

- When `X-User-Role` is `ProgramOffice`, `TransitionCounselor`, `UnitCommander`, or `InstallationAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by_user_id` on an InternshipApplication, as `installation_decision_by` on an InternshipMatch, or as the operator behind a review or audit action — but it does not compare the value to any entity's `id`.
- When `X-User-Role` is `ServiceMember`, `X-User-ID` is the `id` of the acting ServiceMember; ownership checks on any resource that references a ServiceMember compare the resource's foreign-key field (such as `service_member_id` on an application) to `X-User-ID`.
- When `X-User-Role` is `EmployerRep`, `X-User-ID` is the `id` of the acting Employer; ownership checks on any resource that references an Employer compare the resource's foreign-key field (such as `employer_id` on an opening or a match) to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept optional equality filters drawn from the resource's foreign keys and status fields. The service-member list filters by `home_installation_id` and `service_status`; the application list filters by `service_member_id`, `installation_id`, and `status`; the opening list filters by `employer_id` and `status`; the match list filters by `internship_application_id`, `employer_opening_id`, `service_member_id`, `employer_id`, `installation_id`, and `match_status`.

### 2.4. The Logical Clock and Scheduled Sweeps

Every temporal rule in this document — eligibility windows, appeal deadlines, review horizons, match start and end bounds — evaluates against a server-held **logical clock**, never against wall-clock time. Before any clock-setting call has been made, the logical clock starts at exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock. A ProgramOffice-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` together with three sweep counters: `employers_lapsed`, `members_separated`, and `matches_activated`.

Setting the clock triggers three side-effect sweeps in a pinned order: first, the employer review-lapse sweep moves employers whose review horizon has passed to `AUTHORIZATION_LAPSED`; second, the member separation sweep moves members whose `separation_date` has been reached to `SEPARATED`, cascading voids and early terminations through their matches; third, the match auto-start sweep activates approved matches whose `start_date` has been reached. The pinned order matters: a member whose separation fires in the same clock-set call as a pending match activation voids that match instead of activating it, because separation runs before auto-start. Within each sweep, affected entities are processed in `created_at` ascending order, never by `id`. Every entity mutated by a sweep has its `updated_at` refreshed and its `version` incremented.

### 2.5. Common Resource Properties

The seven principal resources — Installation, ServiceMember, InternshipApplication, Employer, EmployerOpening, InternshipMatch, and ComplianceAudit — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by 1 with every modification to the resource, including modifications driven by sweeps and cascades.

Three ledger-style resources — SupervisionReport, WageRecord, and ConversionRecord — are immutable once filed. They carry only `id` and `created_at`; both `updated_at` and `version` are absent on these resources.

### 2.6. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control, and both require their version field as a non-optional input:

- Updating a service member's record requires `expected_service_member_version`, carrying the client's last observed `version` of that ServiceMember. If another writer has advanced the member's version since the client last read it, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because a `separation_date` edit in particular re-validates every non-terminal match of the member and must never apply on top of a record the caller has not re-read.
- Proposing an internship match requires `expected_employer_opening_version`, carrying the client's last observed `version` of the target EmployerOpening. A mismatch with the opening's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); the client's view of remaining capacity is stale, and it must re-read the opening and retry with the fresh version.

On both endpoints the OCC check runs immediately after the existence check of the versioned parent resource, and before any ownership, state, or business rule is evaluated. Endpoints not listed in this subsection do not take a version field.

### 2.7. Validation Priority Order

When several checks could reject the same request, the server evaluates them in a single pinned order and surfaces the first failure. The full ladder, from first to last:

1. **User context.** `X-User-ID` and `X-User-Role` are present, and the role is one of the six declared names — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Applies to all endpoints.
2. **Request schema.** Required fields are present, types are correct, enum values are in range, and conditional requirements hold: a `decision` of DENY requires a `reason`; `location_type` of `ON_SITE` requires a `region_code`; `offer_accepted` of true requires `offer_made` of true; `learning_objectives` must be non-empty with unique objective codes and positive `weight_hours`; a `variant` of COHORT requires both cohort dates; `objectives_achieved` and `objectives_excused` must be disjoint; a wage record's `period_start_date` must not fall after its `period_end_date`. Any failure is `ERR_VALIDATION` (HTTP 400). Applies to every endpoint with a request body.
3. **Role permission.** The role is permitted to call this endpoint per §4 — otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
4. **Path existence.** Resource ids in the URL path exist, validated strictly left to right; the first missing id yields its resource-specific 404: `ERR_INSTALLATION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_OPENING_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, or `ERR_AUDIT_NOT_FOUND`.
5. **Body foreign-key existence.** Ids supplied in the request body exist, validated in the body's declared input order — on a match proposal, `internship_application_id` first, then `employer_opening_id` — with the same resource-specific 404 family.
6. **Optimistic concurrency.** `ERR_STALE_VERSION` (HTTP 412) on the two OCC endpoints of §2.6.
7. **Entity-backed ownership.** `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403): the member's `X-User-ID` must equal the application's `service_member_id` on application submission and appeal; the employer representative's `X-User-ID` must equal the owning employer of the opening or match being touched on opening creation, opening close, match proposal, plan submission, employer-side termination, supervision report filing, wage record posting, and conversion recording.
8. **Active duty.** `ERR_MEMBER_NOT_ON_ACTIVE_DUTY` (HTTP 409) — the member must be `ACTIVE_DUTY` on application submission, on TAP advancement, on match proposal (the applicant), and on installation approval of a match.
9. **Application state.** `ERR_APPLICATION_NOT_SUBMITTED` for commander decisions, `ERR_APPLICATION_NOT_DENIED` for appeals, `ERR_NO_PENDING_APPEAL` for appeal adjudication (all HTTP 409).
10. **Segregation of duties.** `ERR_APPEAL_ADJUDICATOR_CONFLICT` (HTTP 403) on appeal adjudication; this check sits immediately after the `UNDER_APPEAL` state check, because it needs the application's `decided_by_user_id` loaded.
11. **Employer and audit state.** `ERR_EMPLOYER_NOT_AUTHORIZED`, `ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION`, or `ERR_AUDIT_ALREADY_CLOSED` (HTTP 409), guarding opening creation, match proposal, installation decision, employer authorization, periodic review, and audit close.
12. **Opening, match, and plan state.** The 409 family: `ERR_OPENING_NOT_OPEN` (match proposal and opening close), `ERR_APPLICATION_NOT_APPROVED` (match proposal), `ERR_MATCH_NOT_PROPOSED` (plan submission and installation decision), `ERR_MATCH_NOT_ACTIVE` (supervision reports and completion), `ERR_MATCH_NOT_TERMINABLE` (termination), `ERR_WAGE_RECORD_NOT_ALLOWED` (wage records accepted only while the match is `ACTIVE`), `ERR_PLAN_NOT_SUBMITTED` (plan review), `ERR_PLAN_NOT_APPROVED` (installation approval), and `ERR_MATCH_NOT_COMPLETED` (conversion recording).
13. **One live application.** `ERR_ACTIVE_APPLICATION_EXISTS` (HTTP 409) on submission.
14. **Pay-grade exclusion.** `ERR_PAY_GRADE_EXCLUDED` (HTTP 409) on submission.
15. **Eligibility window.** `ERR_OUTSIDE_ELIGIBILITY_WINDOW` (HTTP 409) on submission.
16. **Appeal budget.** On an appeal, the window check precedes the count check: `ERR_APPEAL_WINDOW_EXPIRED` first, then `ERR_MAX_APPEALS_REACHED` (both HTTP 409).
17. **TAP gates.** `ERR_TAP_INCOMPLETE` at commander decision; `ERR_TAP_SEQUENCE_VIOLATION` at TAP advancement (both HTTP 409).
18. **Match date gates**, in pinned order: `ERR_START_DATE_IN_PAST`, then `ERR_DURATION_BELOW_MINIMUM`, then `ERR_DURATION_EXCEEDS_POLICY` (all HTTP 409, match proposal only).
19. **Skills coverage.** `ERR_SKILLS_MISMATCH` (HTTP 409, match proposal).
20. **Duty location.** `ERR_LOCATION_CONSTRAINT_VIOLATION` (HTTP 409, match proposal).
21. **Member schedule overlap.** `ERR_MEMBER_SCHEDULE_OVERLAP` (HTTP 409, match proposal).
22. **Opening capacity.** `ERR_OPENING_AT_CAPACITY` (HTTP 409, match proposal). Quota-style checks run last among the match-creation gates.
23. **Child-record windows.** Supervision week anchors and wage period dates must lie inside the match's date window — failures are `ERR_VALIDATION` (HTTP 400) on supervision reports and wage records.
24. **One report per week.** `ERR_DUPLICATE_WEEK_REPORT` (HTTP 409) on supervision reports.
25. **Plan revision budget.** `ERR_MAX_PLAN_REVISIONS_REACHED` (HTTP 409) on plan resubmission.
26. **Completion timing.** `ERR_COMPLETION_DATE_NOT_REACHED` (HTTP 409) on completion.
27. **Completion content gates**, in pinned order: `ERR_OBJECTIVES_INCOMPLETE`, then `ERR_INSUFFICIENT_SUPERVISION`, then `ERR_MASTERY_BELOW_THRESHOLD` (all HTTP 409).
28. **Separation-date conflict.** `ERR_SEPARATION_DATE_CONFLICT` (HTTP 409) on member record updates.
29. **Conversion window.** `ERR_CONVERSION_WINDOW_EXPIRED` (HTTP 409) on conversion recording.
30. **Conversion uniqueness.** `ERR_CONVERSION_ALREADY_RECORDED` (HTTP 409) on conversion recording.

### 2.8. Command-Policy Variation Across Installations

Approval policy is deliberately not uniform across the program: each Installation carries the policy of its owning command, identified by `command_code` (for example NAVSW or ACC), alongside its display `name` and its geographic `region_code`. Four policy knobs vary per installation. `max_internship_duration_days` (an integer of at least 1) caps the duration of any internship governed by that command. `appeal_window_days` (an integer of at least 1) fixes how many days after a denial an appeal may be filed. `requires_tap_complete` (a boolean) determines whether commander approval is gated on the member having finished the full Transition Assistance Program. `excluded_pay_grades` (a list of pay-grade strings such as `E1` or `E2`, defaulting to empty) bars listed grades from the program at that installation. Every member is governed by the installation referenced as their `home_installation_id`; every application snapshots that governing installation at submission; every match inherits it for the duration cap. Region codes additionally drive the on-site duty constraint described in §3.4.

### 2.9. Numeric Precision and Rounding

All computed ratios, scores, and percentages exposed by the API — `resolution_ratio`, `mastery_ratio`, `compliance_score`, `last_compliance_score`, and `hiring_rate_pct` — are rounded half-up to exactly 2 decimal places and returned as numbers, not strings. The compliance score pins its rounding order: each finding's deduction is rounded half-up to 2 decimal places individually, and only then are the deductions summed; rounding merely the final sum is a rejected implementation. Durations, day counts, and window comparisons are whole days evaluated at date precision against the logical clock. Employer-paid amounts are integer cents carried in `amount_cents`; no fractional-cent arithmetic exists anywhere in the system.

### 2.10. Slot Ledgers and Cascading State Consistency

Two computed counters keep the program's capacity picture honest. An opening's `filled_count` and a member's `active_match_count` each count that entity's InternshipMatches whose `match_status` is one of the three non-terminal statuses — `PROPOSED`, `INSTALLATION_APPROVED`, or `ACTIVE`; matches in `INSTALLATION_DENIED`, `COMPLETED`, `TERMINATED_EARLY`, or `MATCH_VOIDED` never count. Both ledgers are recomputed on every match creation, termination, void, denial, and completion affecting the entity, and the term "non-terminal match" is used throughout this document in exactly this sense.

State changes propagate along three cascade chains, and every mutation plus all of its cascades commits atomically within the triggering request or clock-set call. Revoking an employer closes its openings and voids or terminates its matches. Separating a member voids or terminates that member's matches — after which the member's `active_match_count` necessarily reads 0, since every match that fed it has just become terminal. Closing an opening voids its not-yet-active matches. Each cascade recomputes `filled_count` and `active_match_count` on every affected opening and member, and each mutated entity's `updated_at` and `version` advance accordingly.

## 3. Business Logic & Workflows

### 3.1. Installation Policy Setup and Member Intake

A `ProgramOffice` administrator onboards each participating installation with its command-level policy bundle: `name`, `command_code`, `region_code`, `max_internship_duration_days`, `appeal_window_days`, `requires_tap_complete`, and optionally `excluded_pay_grades`. These policies, summarized in §2.8, govern every member, application, and match that flows through the installation.

A `TransitionCounselor` registers each transitioning member with the member's `full_name`, `service_branch` (exactly one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `SPACE_FORCE`, or `COAST_GUARD`), `pay_grade` (a string such as `E5` or `O3`), scheduled `separation_date`, the list of skill codes the member holds in `skills`, and a `home_installation_id` referencing the governing installation — an unknown installation id is rejected with `ERR_INSTALLATION_NOT_FOUND`. A freshly registered member starts with `service_status` set to `ACTIVE_DUTY`, `tap_stage` set to `TAP_NOT_STARTED`, and `active_match_count` at 0. Each member record also exposes `days_until_separation`, computed as the whole days from the logical clock date to `separation_date` at date precision; the value turns negative once the member has separated.

Member records are maintained under optimistic concurrency. A counselor patching a member supplies `expected_service_member_version` per §2.6 and may change `separation_date`, `skills`, or `pay_grade`. A `separation_date` change re-validates every non-terminal match the member holds: each such match's `end_date` must still fall on or before the new separation date minus a 7-day buffer, or the update is rejected with `ERR_SEPARATION_DATE_CONFLICT` and nothing is written. A successful patch increments the member's `version` by 1 and recomputes `days_until_separation`.

Transition Assistance Program progression is one-directional. A counselor advances `tap_stage` by submitting a `target_stage`, and the target must be exactly the next stage in the fixed order — `TAP_NOT_STARTED` to `PRESEPARATION_COUNSELING_DONE`, then `CORE_CURRICULUM_DONE`, then `CAPSTONE_DONE`. Skipping ahead or naming any other target is rejected with `ERR_TAP_SEQUENCE_VIOLATION`; there is no regression transition. Advancement requires the member to still be `ACTIVE_DUTY`, otherwise `ERR_MEMBER_NOT_ON_ACTIVE_DUTY`, and each successful advance increments the member's `version` by 1.

Separation itself is system-driven. When a clock-set call moves the logical clock date to or past a member's `separation_date`, the separation sweep flips `service_status` from `ACTIVE_DUTY` to `SEPARATED`. Every match of that member in `PROPOSED` or `INSTALLATION_APPROVED` moves to `MATCH_VOIDED`; every match in `ACTIVE` moves to `TERMINATED_EARLY` with `termination_reason` set to `SEPARATION`. The affected openings' `filled_count` values are recomputed, and the member's `active_match_count` is recomputed to 0.

### 3.2. The Program Application: Submission, Commander Decision, and the Appeal Cycle

A member enters the program by submitting an application carrying their own `service_member_id`; because the ServiceMember role is entity-backed, the caller's `X-User-ID` must equal that `service_member_id`, or the submission is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Submission is gated by four checks beyond the schema rules of §2.7. The member must still be `ACTIVE_DUTY` — `ERR_MEMBER_NOT_ON_ACTIVE_DUTY`. The member may hold at most one live application at a time, where every status in `SUBMITTED`, `UNDER_APPEAL`, `APPROVED`, and `DENIED` counts as live; a second submission while one is live fails with `ERR_ACTIVE_APPLICATION_EXISTS`. The member's `pay_grade` must not appear in the home installation's `excluded_pay_grades`, else `ERR_PAY_GRADE_EXCLUDED`. Finally, the eligibility window (`ELIGIBILITY_WINDOW_MIN_DAYS` 30 to `ELIGIBILITY_WINDOW_MAX_DAYS` 180 days) requires `days_until_separation` at submission to be at least 30 and at most 180, both bounds inclusive — exactly 30 days and exactly 180 days are eligible, while 29 or 181 days are rejected with `ERR_OUTSIDE_ELIGIBILITY_WINDOW`.

A created application starts in `SUBMITTED` with `submitted_at` stamped from the logical clock, a `days_until_separation_at_submission` snapshot preserved for the audit trail, `installation_id` copied from the member's `home_installation_id` so the governing policy survives later member edits, `appeal_count` at 0, and `appeal_deadline` still null. The full status vocabulary is `SUBMITTED`, `APPROVED`, `DENIED`, and `UNDER_APPEAL`; `APPROVED` is the only formally terminal state, though a `DENIED` application whose appeal budget is exhausted is de facto terminal.

A `UnitCommander` decides a submitted application by sending a `decision` of APPROVE or DENY with an optional `reason`. The application must currently be `SUBMITTED`, otherwise `ERR_APPLICATION_NOT_SUBMITTED`. A conditional TAP gate applies identically to both outcomes: when the governing installation's `requires_tap_complete` is true, the member's `tap_stage` must already be `CAPSTONE_DONE`, or the decision is rejected with `ERR_TAP_INCOMPLETE`. On DENY the `reason` is mandatory and its absence is `ERR_VALIDATION`. Either decision stamps `decided_by_user_id` with the commander's `X-User-ID`, `decided_at` with the logical clock, and `decision_reason` with the supplied reason, and increments the application's `version` by 1. APPROVE moves the application to `APPROVED`; DENY moves it to `DENIED` and computes `appeal_deadline` as `decided_at` plus the installation's `appeal_window_days` days.

The member — and only the member, under the same ownership rule — may appeal a `DENIED` application, optionally attaching an `appeal_reason`. Appealing requires the application to be `DENIED` (`ERR_APPLICATION_NOT_DENIED`), the logical clock to be on or before `appeal_deadline` (`ERR_APPEAL_WINDOW_EXPIRED`), and `appeal_count` to still be below the appeal budget of `MAX_APPEALS_PER_APPLICATION`, which is 2 (`ERR_MAX_APPEALS_REACHED`); the window check precedes the count check. A successful appeal moves the application to `UNDER_APPEAL`, increments `appeal_count` by 1, and increments `version`.

Adjudication belongs to an `InstallationAuthority`, who resolves a pending appeal with an `outcome` of OVERTURNED or UPHELD and an optional `reason`. The application must be `UNDER_APPEAL`, otherwise `ERR_NO_PENDING_APPEAL`, and segregation of duties forbids the adjudicator's `X-User-ID` from equaling the application's current `decided_by_user_id` — a commander never judges their own denial — else `ERR_APPEAL_ADJUDICATOR_CONFLICT`. OVERTURNED moves the application to `APPROVED`; UPHELD returns it to `DENIED` and recomputes `appeal_deadline` from the new `decided_at` plus `appeal_window_days`. Both outcomes restamp `decided_by_user_id`, `decided_at`, and `decision_reason`. The cycle edge from `DENIED` through `UNDER_APPEAL` back to `DENIED` may repeat while appeals remain; once `appeal_count` reaches 2, the appeal path itself refuses further filings and the denial stands.

### 3.3. Employer Authorization, Periodic Review, and Lapse

A `ProgramOffice` administrator registers a candidate program provider with its `legal_name` and `industry_code`. A new employer starts with `authorization_status` set to `PENDING_AUTHORIZATION` and `pending_violations` at 0, and progresses through the `authorization_status` vocabulary `PENDING_AUTHORIZATION`, `AUTHORIZED`, `SUSPENDED`, `AUTHORIZATION_LAPSED`, and `REVOKED`; `REVOKED` is the terminal state.

Authorization is a deliberate act: the ProgramOffice authorizes an employer currently in `PENDING_AUTHORIZATION` — any other status yields `ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION` — which moves the employer to `AUTHORIZED`, stamps `authorized_at` from the logical clock, and sets `next_review_due_date` to the logical clock date plus the 180-day review interval (`REVIEW_INTERVAL_DAYS`).

Periodic review keeps the authorization alive. A review carries an `outcome` of PASS or FAIL with optional `notes`. PASS is accepted while the employer is `AUTHORIZED`, `SUSPENDED`, or `AUTHORIZATION_LAPSED`; it (re-)moves the employer to `AUTHORIZED`, restamps `authorized_at`, and refreshes `next_review_due_date` to the clock date plus 180 days. A passed review on an already-`AUTHORIZED` employer is a self-loop that simply renews the horizon, and a passed review on a `SUSPENDED` employer is the remediation edge that restores good standing — but a passed review never resets `pending_violations`; only a cleared compliance audit does that (§3.8). FAIL is accepted while the employer is `AUTHORIZED` or `AUTHORIZATION_LAPSED` and moves it to `SUSPENDED`. Calling review on a `PENDING_AUTHORIZATION` or `REVOKED` employer is rejected with `ERR_EMPLOYER_NOT_AUTHORIZED`. Every successful review increments the employer's `version` by 1.

Lapse is automatic. When a clock-set sweep finds an `AUTHORIZED` employer whose `next_review_due_date` is not null and whose date is strictly earlier than the logical clock date, the employer moves to `AUTHORIZATION_LAPSED`. The boundary is exact: a clock date exactly equal to `next_review_due_date` keeps the employer `AUTHORIZED`, because the comparison is strictly-greater. Each employer record also carries `last_cleared_audit_at`, the logical-clock timestamp of its most recent cleared audit, and `last_compliance_score`, the score that audit computed — both null until the first cleared close, and both maintained by the audit workflow of §3.8.

### 3.4. Openings and Match Proposal

An `EmployerRep` posts an internship opening for their own employer, supplying `employer_id` (which must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`), a `title`, the `required_skills` a member must fully hold, a `location_type` of `ON_SITE` or `REMOTE`, a `capacity` of at least 1 bounding concurrently-overlapping non-terminal matches, and a `region_code` that is required when `location_type` is `ON_SITE` (its absence there is `ERR_VALIDATION`) and meaningless-but-tolerated for `REMOTE`. The owning employer must be `AUTHORIZED` at posting time, otherwise `ERR_EMPLOYER_NOT_AUTHORIZED`. A new opening starts with `status` set to `OPEN` and `filled_count` at 0; the full status vocabulary is `OPEN` and `CLOSED`.

An employer representative may also withdraw an opening they own. Closing requires the opening to be `OPEN` — a double-close is rejected with `ERR_OPENING_NOT_OPEN` — and requires `X-User-ID` to equal the opening's `employer_id`, else `ERR_FORBIDDEN_OWNERSHIP`. Closing moves the opening to `CLOSED`, voids every match on it still in `PROPOSED` or `INSTALLATION_APPROVED` (each becomes `MATCH_VOIDED`), leaves `ACTIVE` matches untouched because they are already in flight, and recomputes `filled_count` plus the `active_match_count` of every affected member.

Match proposal is the program's combinatorial core. An `EmployerRep` proposes a match with a payload containing `internship_application_id`, `employer_opening_id`, `start_date`, `end_date`, and the OCC field `expected_employer_opening_version` of §2.6. Beyond the universal checks, the gates fire in this pinned order: body foreign keys exist in declared input order — the application first (`ERR_APPLICATION_NOT_FOUND`), then the opening (`ERR_OPENING_NOT_FOUND`); the opening's version matches (`ERR_STALE_VERSION`); the caller owns the opening's employer (`ERR_FORBIDDEN_OWNERSHIP`); the application is `APPROVED` (`ERR_APPLICATION_NOT_APPROVED`); the opening is `OPEN` (`ERR_OPENING_NOT_OPEN`); the employer is `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`); the applicant member is `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`).

Then the date and duration gates run in their own pinned order. A `start_date` earlier than the logical clock date is rejected with `ERR_START_DATE_IN_PAST`. The duration in whole days — `end_date` minus `start_date`, with `end_date` treated as an exclusive bound — must be at least the 30-day minimum (`MIN_INTERNSHIP_DURATION_DAYS`), else `ERR_DURATION_BELOW_MINIMUM`. Finally the duration must not exceed the effective maximum, which is the smaller of two numbers: the governing installation's `max_internship_duration_days`, and the separation headroom — the whole days from `start_date` to the member's `separation_date` minus the 7-day `SEPARATION_BUFFER_DAYS` buffer. Exceeding that nested-min cap is `ERR_DURATION_EXCEEDS_POLICY`; a duration exactly equal to the cap passes, because both bounds of the duration gate are inclusive.

With dates settled, three constraint checks follow. The member's `skills` must be a superset of the opening's `required_skills`, else `ERR_SKILLS_MISMATCH`. For an `ON_SITE` opening, the opening's `region_code` must equal the member's home installation `region_code`, else `ERR_LOCATION_CONSTRAINT_VIOLATION`; `REMOTE` openings impose no region constraint. The member's schedule must stay free of overlaps under half-open interval semantics: the proposal is rejected with `ERR_MEMBER_SCHEDULE_OVERLAP` if any other non-terminal match of the member fails to satisfy either disjunct of the separation test — the proposal's `end_date` on or before the existing match's `start_date`, or the proposal's `start_date` on or after the existing match's `end_date` — which means back-to-back adjacency, where the new match starts exactly when an existing one ends, is allowed. Last of all, per the standard priority grouping that runs quota checks last, capacity is enforced: the number of non-terminal matches on the opening whose half-open intervals overlap the proposed interval must remain strictly below `capacity`, else `ERR_OPENING_AT_CAPACITY`.

A created match starts with `match_status` set to `PROPOSED` and `plan_status` set to `PLAN_DRAFT` — two parallel dimensions on one row. The full `match_status` vocabulary is `PROPOSED`, `INSTALLATION_APPROVED`, `INSTALLATION_DENIED`, `ACTIVE`, `COMPLETED`, `TERMINATED_EARLY`, and `MATCH_VOIDED`; the full `plan_status` vocabulary is `PLAN_DRAFT`, `PLAN_SUBMITTED`, `PLAN_APPROVED`, and `PLAN_RETURNED`. Creation denormalizes `service_member_id` from the application, `employer_id` from the opening, and `installation_id` from the member's home installation — the last of these is what binds the match to the command's duration cap. Creating a match increments the opening's `version` by 1 and recomputes both `filled_count` and the member's `active_match_count`.

### 3.5. Training Plans and the Installation Decision

Before an installation will approve a match, the employer must write its training plan. An `EmployerRep` owning the match submits a plan with `learning_objectives` — a non-empty array whose entries each carry an `objective_code` unique within the plan, a `description`, a positive integer `weight_hours`, and a `status` drawn from `PENDING`, `ACHIEVED`, and `EXCUSED` — together with the named `supervisor_name` and a `weekly_hours` of at least 1; any violation of these payload rules is `ERR_VALIDATION`, and a caller other than the owning employer is `ERR_FORBIDDEN_OWNERSHIP`. The match must still be `PROPOSED`, else `ERR_MATCH_NOT_PROPOSED`: the plan locks once the installation decides. Submission overwrites `learning_objectives`, `supervisor_name`, and `weekly_hours` wholesale, resets every objective's `status` to `PENDING`, moves `plan_status` from `PLAN_DRAFT` (or, on a resubmission, from `PLAN_RETURNED`) to `PLAN_SUBMITTED`, and increments the match's `version`.

Review belongs to the `InstallationAuthority`, who acts with an `outcome` of APPROVE or RETURN and optional `feedback`. The plan must be `PLAN_SUBMITTED`, otherwise `ERR_PLAN_NOT_SUBMITTED`. APPROVE moves the plan to `PLAN_APPROVED`. RETURN moves it to `PLAN_RETURNED` and increments `plan_revision_count` by 1. Resubmission out of `PLAN_RETURNED` repeats the full submission validation and is allowed only while `plan_revision_count` remains below the revision budget of `MAX_PLAN_REVISIONS`, which is 3; a fourth attempt is rejected with `ERR_MAX_PLAN_REVISIONS_REACHED`. The cycle from `PLAN_SUBMITTED` to `PLAN_RETURNED` and back may therefore repeat up to three returns.

The installation decision converts a proposal into an approved internship — or ends it. An `InstallationAuthority` sends a `decision` of APPROVE or DENY with a `reason`. Approval requires the match to be `PROPOSED` (`ERR_MATCH_NOT_PROPOSED`), the plan to be `PLAN_APPROVED` (`ERR_PLAN_NOT_APPROVED`) — a cross-dimension gate on the same row, tying the two parallel state machines together — the employer to be `AUTHORIZED` (`ERR_EMPLOYER_NOT_AUTHORIZED`), and the member to still be `ACTIVE_DUTY` (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`). Approval moves `match_status` to `INSTALLATION_APPROVED` and stamps `installation_decision_by` with the authority's `X-User-ID` and `installation_decision_reason` with the reason. Denial requires only `PROPOSED` and an `AUTHORIZED` employer — an installation may deny a training-free proposal, so `PLAN_APPROVED` is not required — but the `reason` is mandatory on DENY, its absence yielding `ERR_VALIDATION`. Denial moves the match to `INSTALLATION_DENIED`, stamps the same two decision fields, and releases the slot by recomputing the opening's `filled_count` and the member's `active_match_count`. Either decision increments the match's `version`.

Activation is then automatic: the match auto-start sweep of §2.4 moves an `INSTALLATION_APPROVED` match to `ACTIVE` once the logical clock date has reached or passed its `start_date`, provided the member is still `ACTIVE_DUTY`. A member whose separation fires in the same clock-set call voids the match instead, because the separation sweep runs before the auto-start sweep.

### 3.6. Internship Execution: Supervision, Wage Attestation, and Early Termination

While a match is `ACTIVE`, the employer files weekly supervision reports. The filing `EmployerRep` must own the match's employer (`ERR_FORBIDDEN_OWNERSHIP`) and the match must be `ACTIVE` (`ERR_MATCH_NOT_ACTIVE`). Each report carries `internship_match_id`, a `week_start_date` anchoring the supervised week, `hours_supervised` of at least 0, the attesting `supervisor_name`, free-text `attestation_text`, and optionally `objectives_achieved` and `objectives_excused`. The `week_start_date` must lie within the match's `start_date`-to-`end_date` window, every objective code referenced must exist in the match's approved plan, and the two objective lists must be disjoint; violations are `ERR_VALIDATION`. One report is allowed per match per week: a second report for the same `week_start_date` on the same match is rejected with `ERR_DUPLICATE_WEEK_REPORT`. Filing marks the listed objectives `ACHIEVED` or `EXCUSED`, recomputes both progress ratios, and increments the match's `version` by 1.

Two progress measures ride on the plan and are recomputed on every supervision report that marks objectives. The `resolution_ratio` is the count of objectives whose status is `ACHIEVED` or `EXCUSED` divided by the total number of objectives — an unweighted structural-completeness measure. The `mastery_ratio` is the sum of `weight_hours` over `ACHIEVED` objectives only, divided by the sum of `weight_hours` over all objectives — a weighted quality floor. Both ratios read exactly 1.0 when the plan holds no objectives, and both are rounded half-up to 2 decimal places. The two measures legitimately diverge: an excused objective resolves the plan but contributes no mastery hours, so a heavily-excused plan can be fully resolved yet below the mastery floor.

The program's cardinal fiscal rule is that the employer never pays the intern — the service continues member pay throughout. Employers attest to this through wage records: an owning `EmployerRep` posts `internship_match_id`, `period_start_date`, `period_end_date`, `amount_cents` as an integer of at least 0, and an optional `memo`. Wage records are accepted only while the match is `ACTIVE`; posting against a match in any other status is rejected with the dedicated `ERR_WAGE_RECORD_NOT_ALLOWED`. The period must lie within the match's date window with `period_start_date` not after `period_end_date`, else `ERR_VALIDATION`. An `amount_cents` of exactly 0 is the normal no-wage attestation. Any positive amount sets the record's computed `is_violation` to true and fires the wage-violation cascade: the match's `flagged_wage_violation` becomes true, the employer's `pending_violations` ledger increments by 1, and if that raises `pending_violations` to at least the suspension threshold of 2 (`WAGE_VIOLATION_SUSPEND_THRESHOLD`) while the employer is `AUTHORIZED` or `AUTHORIZATION_LAPSED`, the employer moves to `SUSPENDED`. A violating record increments both the match's and the employer's `version` by 1. The ledger counts only violations recorded after the employer's `last_cleared_audit_at`; a cleared audit resets it (§3.8).

Either the owning `EmployerRep` or an `InstallationAuthority` may end a match early by terminating it with a `reason`. The match must be `PROPOSED`, `INSTALLATION_APPROVED`, or `ACTIVE`; terminating an already-terminal match — `INSTALLATION_DENIED`, `COMPLETED`, `TERMINATED_EARLY`, or `MATCH_VOIDED` — is rejected with `ERR_MATCH_NOT_TERMINABLE`. The caller-supplied reason must be one of `VOLUNTARY`, `MEDICAL`, `EMPLOYER_REQUEST`, or `CONDUCT` and is recorded as `termination_reason`; the remaining two enum values, `SEPARATION` and `EMPLOYER_REVOKED`, are written only by the system sweeps and cascades. The employer-side caller must own the match's employer (`ERR_FORBIDDEN_OWNERSHIP`); the installation authority is exempt from that ownership check. Termination moves the match to `TERMINATED_EARLY`, recomputes `filled_count` and `active_match_count`, and increments the match's `version`.

### 3.7. Completion, Conversion, and the Hiring Rate

When an internship has run its course, an `InstallationAuthority` completes the match. Completion requires the match to be `ACTIVE` (`ERR_MATCH_NOT_ACTIVE`) and the logical clock date to have reached or passed the match's `end_date` (`ERR_COMPLETION_DATE_NOT_REACHED`). Three content gates then run in pinned order. First, every learning objective must be resolved — status `ACHIEVED` or `EXCUSED`, equivalently a `resolution_ratio` of exactly 1.00 — else `ERR_OBJECTIVES_INCOMPLETE`. Second, supervision coverage must be met: the number of SupervisionReports filed for the match must be at least the duration in whole days divided by the 7-day supervision cadence (`SUPERVISION_CADENCE_DAYS`), rounded down to an integer — a 34-day internship requires 4 reports, a 35-day internship requires 5 — and one report too few is `ERR_INSUFFICIENT_SUPERVISION`. Third, `mastery_ratio` must be at least the `MIN_MASTERY_RATIO` floor of 0.75, else `ERR_MASTERY_BELOW_THRESHOLD`. Completion moves the match to `COMPLETED`, stamps `completed_at` from the logical clock, releases the slot by recomputing `filled_count` and `active_match_count`, and increments the match's `version`.

After separation, an internship may convert into employment. An owning `EmployerRep` records a conversion with `internship_match_id`, `conversion_date`, `offer_made`, and `offer_accepted`. The match must be `COMPLETED` (`ERR_MATCH_NOT_COMPLETED`). The `conversion_date` must fall on or after the member's `separation_date` and no later than `separation_date` plus the 90-day conversion window (`CONVERSION_WINDOW_DAYS`), both bounds inclusive, else `ERR_CONVERSION_WINDOW_EXPIRED`. At most one conversion record exists per match; a second filing is `ERR_CONVERSION_ALREADY_RECORDED`. An `offer_accepted` of true requires `offer_made` of true, else `ERR_VALIDATION`. The record's computed `hired` flag is true exactly when both `offer_made` and `offer_accepted` are true, and only hired records count as conversions in the hiring rate.

The employer hiring rate is a computed read over the employer's `COMPLETED` matches, joined to conversion records on `internship_match_id`, and comes in two variants selected by the query parameter `variant`. Under `COHORT`, the caller must supply `cohort_start_date` and `cohort_end_date` — omitting either is `ERR_VALIDATION` — and completions are bucketed by the member's `separation_date` falling within that caller-supplied window, both bounds inclusive. Under `ROLLING`, the default when `variant` is omitted, completions are bucketed by the match's `completed_at` date falling within the trailing 90-day window (`ROLLING_HIRING_WINDOW_DAYS`) ending at the logical clock date, both bounds inclusive. The two variants legitimately diverge on identical underlying data because they bucket the same completions on different dates over different windows. In either variant, `completed_count` is the number of in-window completions and `converted_count` is the number of those completions having a conversion record with `hired` true; `hiring_rate_pct` is 100 times `converted_count` divided by `completed_count`, rounded half-up to 2 decimal places, and an empty denominator yields exactly 0.00. The response also reports the resolved `window_start_date` and `window_end_date` alongside `employer_id` and `variant`.

### 3.8. Compliance Audits and the Sanction Cascade

The program office polices employers — above all against use of interns as unpaid labor — through compliance audits. A `ProgramOffice` administrator opens an audit on any employer by supplying `employer_id`; employers in any authorization state may be audited. A new audit starts in `OPEN` with `opened_at` stamped from the logical clock. The audit status vocabulary is `OPEN`, `CLOSED_CLEARED`, and `CLOSED_SANCTIONED`, the latter two being terminal.

Closing an audit supplies its `findings`: an array whose entries each carry a `finding_code` of `WAGE_PAYMENT_DETECTED`, `SUPERVISION_MISSING`, `OBJECTIVE_MISMATCH`, or `TRAINING_PLAN_ABSENT`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `note`. Only an `OPEN` audit can be closed; a second close is rejected with `ERR_AUDIT_ALREADY_CLOSED`. The close computes a `compliance_score` starting from the base score of 100 (`AUDIT_BASE_SCORE`). Findings are processed in array order. Each finding's deduction is its severity base — 5.00 for `MINOR`, 20.00 for `MAJOR`, 45.00 for `CRITICAL` — multiplied by one plus the `REPEAT_MULTIPLIER` of 0.5 times the number of earlier findings in the same audit carrying the same `finding_code`; every deduction is rounded half-up to 2 decimal places individually, and only then are the rounded deductions summed. The total deduction is capped at the base score of 100, and the score is the base minus that capped total. An audit closed with no findings scores exactly 100.00.

The outcome is decided by the sanction threshold `SANCTION_SCORE_THRESHOLD` of 70. A score of at least 70 closes the audit as `CLOSED_CLEARED`: `closed_at` is stamped, the employer's `pending_violations` ledger resets to 0, `last_cleared_audit_at` is set to the logical clock, and `last_compliance_score` records the computed score. A score below 70 closes the audit as `CLOSED_SANCTIONED`: `closed_at` and the employer's `last_compliance_score` are stamped, and the employer — provided it is not already `REVOKED` — moves to `REVOKED` from `AUTHORIZED`, `SUSPENDED`, or `AUTHORIZATION_LAPSED` alike. Revocation cascades in full: every `OPEN` opening of the employer moves to `CLOSED`; every match of the employer in `PROPOSED` or `INSTALLATION_APPROVED` moves to `MATCH_VOIDED`; every such match in `ACTIVE` moves to `TERMINATED_EARLY` with `termination_reason` set to `EMPLOYER_REVOKED`; and `filled_count` plus `active_match_count` are recomputed for every affected opening and member. The close increments the versions of both the audit and the employer.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, decisions, reviews, and sweeps — return a `200 OK` status code. Request payloads, validation gates, and side effects for each endpoint are defined by the workflows of §3; the table below is an index, not a complete contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/skillbridge/_clock/set_current_utc` | Advance the logical clock and run the three sweeps | ProgramOffice |
| POST | `/skillbridge/installations` | Create an installation with its command policy | ProgramOffice |
| POST | `/skillbridge/service-members` | Register a transitioning service member | TransitionCounselor |
| GET | `/skillbridge/service-members` | List service members; filterable | All roles |
| GET | `/skillbridge/service-members/{id}` | Get one service member | All roles |
| PATCH | `/skillbridge/service-members/{id}` | Update separation date, skills, or pay grade under OCC | TransitionCounselor |
| POST | `/skillbridge/service-members/{id}/tap-advance` | Advance the member's TAP stage by one step | TransitionCounselor |
| POST | `/skillbridge/internship-applications` | Submit a program application | ServiceMember |
| GET | `/skillbridge/internship-applications` | List applications; filterable | All roles |
| GET | `/skillbridge/internship-applications/{id}` | Get one application | All roles |
| POST | `/skillbridge/internship-applications/{id}/commander-decision` | Commander approves or denies the application | UnitCommander |
| POST | `/skillbridge/internship-applications/{id}/appeal` | Member appeals a denied application | ServiceMember |
| POST | `/skillbridge/internship-applications/{id}/adjudicate-appeal` | Installation authority adjudicates a pending appeal | InstallationAuthority |
| POST | `/skillbridge/employers` | Register an employer as a candidate provider | ProgramOffice |
| GET | `/skillbridge/employers/{id}` | Get one employer | All roles |
| POST | `/skillbridge/employers/{id}/authorize` | Authorize a pending employer | ProgramOffice |
| POST | `/skillbridge/employers/{id}/periodic-review` | Periodic review: PASS renews, FAIL suspends | ProgramOffice |
| GET | `/skillbridge/employers/{id}/compliance-audits` | List an employer's compliance audits | All roles |
| GET | `/skillbridge/employers/{id}/hiring-rate` | Computed hiring rate, cohort or rolling variant | ProgramOffice, EmployerRep, InstallationAuthority |
| POST | `/skillbridge/employer-openings` | Post an internship opening | EmployerRep |
| GET | `/skillbridge/employer-openings` | List openings; filterable | All roles |
| GET | `/skillbridge/employer-openings/{id}` | Get one opening | All roles |
| POST | `/skillbridge/employer-openings/{id}/close` | Employer withdraws an open opening | EmployerRep |
| POST | `/skillbridge/internship-matches` | Propose a match under OCC on the opening | EmployerRep |
| GET | `/skillbridge/internship-matches` | List matches; filterable on every foreign key | All roles |
| GET | `/skillbridge/internship-matches/{id}` | Get one match | All roles |
| POST | `/skillbridge/internship-matches/{id}/installation-decision` | Installation approves or denies the proposed match | InstallationAuthority |
| POST | `/skillbridge/internship-matches/{id}/submit-plan` | Employer submits or resubmits the training plan | EmployerRep |
| POST | `/skillbridge/internship-matches/{id}/review-plan` | Installation approves or returns the plan | InstallationAuthority |
| POST | `/skillbridge/internship-matches/{id}/terminate` | Terminate a non-terminal match early | EmployerRep, InstallationAuthority |
| POST | `/skillbridge/internship-matches/{id}/complete` | Complete an active match at or past its end date | InstallationAuthority |
| GET | `/skillbridge/internship-matches/{id}/supervision-reports` | List a match's supervision reports | All roles |
| GET | `/skillbridge/internship-matches/{id}/wage-records` | List a match's wage records | All roles |
| GET | `/skillbridge/internship-matches/{id}/conversion-records` | List a match's conversion records | All roles |
| POST | `/skillbridge/supervision-reports` | File a weekly supervision report | EmployerRep |
| POST | `/skillbridge/wage-records` | Record a payment-period wage attestation | EmployerRep |
| POST | `/skillbridge/compliance-audits` | Open a compliance audit on an employer | ProgramOffice |
| POST | `/skillbridge/compliance-audits/{id}/close` | Close an audit with findings and apply the outcome | ProgramOffice |
| POST | `/skillbridge/conversion-records` | Record a post-separation employment conversion | EmployerRep |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows of §2 and §3; this table is the canonical id-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_APPEAL_ADJUDICATOR_CONFLICT` | 403 Forbidden |
| `ERR_INSTALLATION_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_NOT_FOUND` | 404 Not Found |
| `ERR_OPENING_NOT_FOUND` | 404 Not Found |
| `ERR_MATCH_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_NOT_ON_ACTIVE_DUTY` | 409 Conflict |
| `ERR_OUTSIDE_ELIGIBILITY_WINDOW` | 409 Conflict |
| `ERR_PAY_GRADE_EXCLUDED` | 409 Conflict |
| `ERR_ACTIVE_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_DENIED` | 409 Conflict |
| `ERR_NO_PENDING_APPEAL` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_MAX_APPEALS_REACHED` | 409 Conflict |
| `ERR_TAP_INCOMPLETE` | 409 Conflict |
| `ERR_TAP_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_SEPARATION_DATE_CONFLICT` | 409 Conflict |
| `ERR_EMPLOYER_NOT_PENDING_AUTHORIZATION` | 409 Conflict |
| `ERR_EMPLOYER_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_OPENING_NOT_OPEN` | 409 Conflict |
| `ERR_APPLICATION_NOT_APPROVED` | 409 Conflict |
| `ERR_SKILLS_MISMATCH` | 409 Conflict |
| `ERR_LOCATION_CONSTRAINT_VIOLATION` | 409 Conflict |
| `ERR_DURATION_BELOW_MINIMUM` | 409 Conflict |
| `ERR_DURATION_EXCEEDS_POLICY` | 409 Conflict |
| `ERR_START_DATE_IN_PAST` | 409 Conflict |
| `ERR_MEMBER_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_OPENING_AT_CAPACITY` | 409 Conflict |
| `ERR_MATCH_NOT_PROPOSED` | 409 Conflict |
| `ERR_MATCH_NOT_ACTIVE` | 409 Conflict |
| `ERR_MATCH_NOT_TERMINABLE` | 409 Conflict |
| `ERR_PLAN_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_MAX_PLAN_REVISIONS_REACHED` | 409 Conflict |
| `ERR_COMPLETION_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_OBJECTIVES_INCOMPLETE` | 409 Conflict |
| `ERR_INSUFFICIENT_SUPERVISION` | 409 Conflict |
| `ERR_MASTERY_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_DUPLICATE_WEEK_REPORT` | 409 Conflict |
| `ERR_WAGE_RECORD_NOT_ALLOWED` | 409 Conflict |
| `ERR_MATCH_NOT_COMPLETED` | 409 Conflict |
| `ERR_CONVERSION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_CONVERSION_ALREADY_RECORDED` | 409 Conflict |
| `ERR_AUDIT_ALREADY_CLOSED` | 409 Conflict |

