# NIH Peer Review API — Product Requirements Document

## 1. Introduction

Research funding at the National Institutes of Health turns on a disciplined, multi-party pipeline: an investigator drafts an application against a funding opportunity announcement, referral staff place it with a study section and a funding institute, a recruited panel scores it, a percentile ranking normalizes the score across review groups, an advisory council weighs program priorities and portfolio balance, and grants management converts a funding decision into a budgeted award whose post-award life — progress reports, carryover authority, no-cost extensions, terminations, and change-of-institution transfers — is administered against a finite institute appropriation. Each stage is owned by a different office, and the integrity of the whole depends on those duties remaining segregated.

This document specifies the Peer Review API, the system of record for that pipeline. It governs announcement configuration with page limits, budget bounds, and institutional certification requirements; referral with applicant assignment requests; reviewer recruitment with conflict-of-interest screening; criterion scoring, overall impact computation, and dual (raw and cross-panel normalized) percentile ranking; payline publication under commitment authority and select-pay discretion; just-in-time information collection; award issuance with per-year budget construction; and post-award fiscal administration. The API's business surface is mounted under `/grants`; a separate operator capability for driving the logical clock lives outside that prefix and is described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying an empty value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to each operation is further restricted by role: a caller whose role is not listed for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

Seven roles are recognized, segregating program, referral, review, council, and grants-management duties across disjoint offices:

- **ProgramOfficer** — program official; configures funding opportunities, institutes, institutions, and applicant registrations; publishes paylines; operates the logical clock.
- **ReferralOfficer** — assigns submitted applications to study sections and funding institutes.
- **ScientificReviewOfficer** — runs study sections, recruits reviewers, creates assignments, convenes meetings, and releases scores.
- **Reviewer** — panel reviewer; responds to recruitment, declares conflicts, responds to assignments, and submits critiques.
- **CouncilMember** — advisory council member; records second-level reviews.
- **GrantsOfficer** — grants management officer; exercises select pay, adjudicates just-in-time packages, issues awards, accepts progress reports, adjudicates modifications, and drives transfers.
- **Applicant** — principal investigator; drafts, submits, and withdraws own applications, answers just-in-time requests, files progress reports, requests carryovers and no-cost extensions, and proposes change-of-institution transfers.

Identity binding differs by role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant; ownership checks on any resource that references an Applicant compare the resource's foreign-key field to `X-User-ID` — an application's `applicant_id` directly, and, for award-scoped operations, the `applicant_id` of the application that the award funds. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting Reviewer; ownership checks compare the target reviewer's `id`, or an assignment's `reviewer_id`, to `X-User-ID`. An entity-backed caller acting on a resource owned by a different entity is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ProgramOfficer`, `ReferralOfficer`, `ScientificReviewOfficer`, `CouncilMember`, or `GrantsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `recorded_by` on a council review — but never compares it to any entity's `id`.

Within the shared post-award modification capability, the two entity-adjacent roles split by modification type: an `Applicant` may request only `CARRYOVER` or `NO_COST_EXTENSION` modifications, while a `GrantsOfficer` may create only `TERMINATION` modifications; crossing that line is rejected with `ERR_MODIFICATION_TYPE_ROLE_MISMATCH`.

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

Endpoints that return lists of resources paginate through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Domain Timestamps

Every deadline, window, and expiry rule in the system reads a **logical clock** rather than wall-clock time. Before any clock operation is performed, the logical clock starts at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `ProgramOfficer` may advance the clock through an admin-only, test-driving capability mounted outside the business surface at `/_clock/set_current_utc`, supplying `to_iso8601`, which must be a valid ISO 8601 UTC timestamp and must not be earlier than the current logical time: the clock is monotonic non-decreasing, and a malformed or regressive value is rejected with `ERR_INVALID_CLOCK_VALUE`. A successful call reports the resulting `current_utc`.

Time-gated rules evaluate lazily against the logical clock — nothing is swept by a background timer. A just-in-time request, for instance, expires when a JIT operation is attempted while the clock is past the request's `due_date`, and every evaluation observes the most recently set clock on the next call.

System-managed timestamps — `created_at`, `updated_at`, and the envelope's `api_request_timestamp` — are rendered as ISO 8601 UTC with exactly three fractional digits. Domain datetime fields, whether supplied by clients (`open_date`, `receipt_deadline`, `meeting_date`, `start_date`, `effective_date`, `new_end_date`, `human_subjects_certification_expiry`, `animal_welfare_assurance_expiry`) or computed by the system (`due_date`, `end_date`), are ISO 8601 UTC instants rendered as supplied or as the logical clock reads.

### 2.5. Common Resource Properties and Numeric Precision

Every resource in the system carries a standard set of system-managed fields: an `id`, which is a unique server-minted UUID with no type prefix; a `created_at` timestamp recording when the resource was first created; an `updated_at` timestamp refreshed on every modification; and a `version`, an integer that increments by one on every mutation of the resource — including automatic transitions the server performs on it, such as quorum-driven flips, score release outcomes, funding decisions, and expiry cascades.

All money is represented as integer cents; no fractional-cent amount ever appears in the API. Where a computation yields a fraction of a cent — an indirect-cost product, a transfer proration, a carryover auto-approval limit, a select-pay cap — the result is rounded half up to a whole cent. Percentile values are rendered with exactly one decimal place, and criterion means with exactly two decimal places, both rounded half up. Fractional configuration values supplied by callers (`indirect_cost_rate`, `select_pay_cap_pct`, `select_pay_extension_percentile`, `budget_cut_pct`) are used at the precision supplied.

### 2.6. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and no other endpoint accepts a version field.

The referral operation — including a re-referral that legitimately supersedes a prior referral — requires the request to carry `expected_application_version`, the caller's last observed `version` of the application. When the supplied value no longer matches the application's current `version`, the referral is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412): the caller is acting on a stale view of the application's referral state.

Publishing a payline decision requires the request to carry `expected_institute_version`, the caller's last observed `version` of the institute. A payline decision supersedes the institute's previously published payline, so a request whose `expected_institute_version` no longer matches the institute's current `version` is rejected as stale with `ERR_STALE_INSTITUTE_VERSION` (HTTP 412).

### 2.7. The Ordered Validation Pipeline

Every request is validated against a fixed, priority-ordered pipeline. When several checks could reject the same request, the earliest stage in this ordering wins, so the error a caller observes is always the highest-priority failure:

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty on every endpoint (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Role authorization.** The supplied role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. **Path existence, left to right.** Every resource id in the URL path must exist, validated in left-to-right order; the request is rejected with the not-found error (HTTP 404) of the *first* missing id, and a nested path under a missing parent never evaluates the child. The not-found family is: `ERR_FOA_NOT_FOUND`, `ERR_INSTITUTE_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_STUDY_SECTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_JIT_REQUEST_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`.
4. **Body foreign keys.** Ids referenced in the request body — `foa_id`, `institution_id`, `requested_study_section_id`, `requested_institute_id`, `reviewer_id`, `application_id`, `to_institution_id` — must exist, rejecting with the same 404 family. The `excluded_reviewer_ids` list is exempt from existence checking at application creation; it is enforced later, at assignment time.
5. **Entity-backed ownership.** For owner-scoped operations — submission, withdrawal, JIT item submission, progress-report creation, modification creation, transfer proposal, reviewer respond, conflict declaration, assignment respond, and critique submission — the caller's `X-User-ID` must match the owning entity as described in §2.1 (`ERR_NOT_RESOURCE_OWNER`, HTTP 403).
6. **Lifecycle state gates.** The target resource's current state must permit the operation: application submittable, referrable, withdrawable, scored, fundable, or JIT-complete; announcement open; section recruiting, convenable, in-meeting, or releasable; reviewer invited or active; assignment respondable or accepted; JIT open or submitted; award active; report submitted; modification pending; transfer proposed or relinquished. Violations reject with the 409 state-gate family: `ERR_APPLICATION_NOT_SUBMITTABLE`, `ERR_APPLICATION_NOT_REFERRABLE`, `ERR_APPLICATION_NOT_WITHDRAWABLE`, `ERR_APPLICATION_NOT_SCORED`, `ERR_APPLICATION_NOT_FUNDABLE`, `ERR_APPLICATION_NOT_JIT_COMPLETE`, `ERR_FOA_NOT_OPEN`, `ERR_SECTION_NOT_RECRUITING`, `ERR_SECTION_NOT_CONVENABLE`, `ERR_SECTION_NOT_IN_MEETING`, `ERR_SECTION_NOT_RELEASABLE`, `ERR_REVIEWER_INVALID_STATE`, `ERR_REVIEWER_NOT_ACTIVE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_JIT_INVALID_STATE`, `ERR_AWARD_NOT_ACTIVE`, `ERR_REPORT_INVALID_STATE`, `ERR_MODIFICATION_NOT_PENDING`, `ERR_TRANSFER_INVALID_STATE`.
7. **Optimistic concurrency.** The stale-version checks of §2.6 (`ERR_STALE_APPLICATION_VERSION`, `ERR_STALE_INSTITUTE_VERSION`, HTTP 412).
8. **Institutional certifications.** An application flagging human-subjects or vertebrate-animal work requires the institution's corresponding certification or assurance to be present (`ERR_CERTIFICATION_MISSING`, HTTP 422) and unexpired relative to the governing date (`ERR_CERTIFICATION_EXPIRED`, HTTP 422). This stage guards submission and, with the transfer's `effective_date` as the governing date, transfer proposals.
9. **Conflict-of-interest screening.** Assignment creation rejects an institutional match (`ERR_COI_INSTITUTION_MATCH`, HTTP 409), an applicant-requested exclusion (`ERR_REVIEWER_EXCLUDED`, HTTP 409), or a reviewer self-declared conflict (`ERR_REVIEWER_SELF_DECLARED_CONFLICT`, HTTP 409).
10. **Page limit.** The research strategy must fit the announcement's page limit (`ERR_PAGE_LIMIT_EXCEEDED`, HTTP 422).
11. **Budget structure and caps.** Structural defects (`ERR_INVALID_BUDGET_STRUCTURE`, HTTP 400) are distinguished from per-year over-cap amounts (`ERR_BUDGET_CAP_EXCEEDED`, HTTP 422).
12. **Uniqueness.** `ERR_DUPLICATE_PA_NUMBER`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_ASSIGNMENT`, `ERR_PRIMARY_ALREADY_ASSIGNED`, `ERR_ASSIGNMENT_LIMIT_REACHED` (all HTTP 409).
13. **Quotas.** `ERR_SECTION_QUOTA_EXCEEDED` at referral and `ERR_REVIEWER_CAPACITY_EXCEEDED` at assignment (both HTTP 409).
14. **Assignment-request honor rule.** Overriding a satisfiable applicant request without the override flag (`ERR_ASSIGNMENT_REQUEST_IGNORED`, HTTP 409), and re-referral while live assignments exist (`ERR_LIVE_ASSIGNMENTS_EXIST`, HTTP 409).
15. **Select-pay band and JIT completeness.** `ERR_NO_PAYLINE_PUBLISHED` (HTTP 409), `ERR_SELECT_PAY_BAND_EXCEEDED` (HTTP 422), `ERR_JIT_ITEM_MISSING` (HTTP 422).
16. **Receipt deadline.** `ERR_RECEIPT_DEADLINE_PASSED` (HTTP 409).
17. **Reviewer meeting proximity.** `ERR_MEETING_PROXIMITY_CONFLICT` (HTTP 409).
18. **Window checks.** `ERR_JIT_EXPIRED`, `ERR_REPORT_PERIOD_MISMATCH`, `ERR_REPORT_WINDOW_CLOSED`, `ERR_CARRYOVER_PERIOD_MISMATCH`, `ERR_NCE_TOO_LATE`, `ERR_NCE_LIMIT_EXCEEDED` (all HTTP 409).
19. **Carryover sufficiency.** `ERR_CARRYOVER_EXCEEDS_UNOBLIGATED` (HTTP 422).
20. **Select-pay fiscal gates.** Commitment authority is checked before the select-pay cap: `ERR_INSUFFICIENT_COMMITMENT_AUTHORITY` first, then `ERR_SELECT_PAY_CAP_EXCEEDED` (both HTTP 402).

Separately from this pipeline, malformed payloads — a missing required field, a wrong type, an enum value outside its declared set, a criterion score outside 1 through 9, a `budget_cut_pct` outside zero to 0.30, a `new_end_date` that is not after the award's current `end_date`, or a `start_date`/`effective_date` earlier than the logical clock — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.8. The Institute Ledger and Commitment Authority

Each Institute maintains a fiscal ledger that is the single source of truth for funding decisions. Its configuration fields are the `appropriation_cents` (the total fiscal appropriation available for awards), the `reserve_cents` (an untouchable reserve withheld from every commitment walk), the `indirect_cost_rate` (the facilities-and-administration rate applied to direct costs), the `select_pay_cap_pct` (the fraction of the appropriation spendable through select pay), and the `select_pay_extension_percentile` (the percentile points beyond the published payline reachable by select pay). Its computed ledger fields all start at zero: `committed_cents`, the outstanding obligations across non-terminal awards; `disbursed_cents`, the cumulative outlays from accepted progress reports; and `select_pay_spent_cents`, the cumulative projected cost committed through select-pay decisions. The `current_payline_percentile` records the most recently published base payline and is null until the first payline decision.

The commitment authority available to any funding decision is the appropriation reduced by outstanding commitments, cumulative disbursements, and the reserve. Issuing an award adds the award's `total_awarded_cents` to `committed_cents`. Accepting a progress report converts commitment into outlay: the institute's `committed_cents` falls and its `disbursed_cents` rises by the disbursed amount. Terminating an award returns its undisbursed commitment to the ledger. Completing a transfer reduces the commitment by the relinquished and retained portions of the original award and re-commits the relinquished portion against the successor award. Each select-pay decision adds the selected application's projected cost to `select_pay_spent_cents`. Every mutation of the institute refreshes its `updated_at` and increments its `version`, which is what makes the payline OCC check of §2.6 meaningful.

## 3. Business Logic & Workflows

### 3.1. Announcements, Registrations, and the Draft Application

A funding cycle begins when a `ProgramOfficer` publishes a **FundingOpportunity** announcement. The announcement carries a `pa_number` that must be unique across all funding opportunities — a duplicate is rejected with `ERR_DUPLICATE_PA_NUMBER` — along with a `title`, an `activity_code` naming the grant mechanism (`R01`, `R21`, or `R03`), a `research_strategy_page_limit` of at least one page, the per-year budget bounds `min_direct_cents_per_year` (zero or more) and `max_direct_cents_per_year` (at least the minimum), a `max_years` project-period cap between one and five, and the `open_date` and `receipt_deadline` instants that bracket submissions. A new announcement starts `OPEN`. When the program office closes it, its status moves from `OPEN` to `CLOSED` and no further submissions against it are accepted; closing an already-`CLOSED` announcement is rejected with `ERR_FOA_NOT_OPEN`.

The program office also maintains the registries the pipeline depends on. An **Institution** is registered with a `name` and two nullable compliance dates: `human_subjects_certification_expiry` (null means the institution holds no human-subjects certification) and `animal_welfare_assurance_expiry` (null means no animal-welfare assurance). An **Applicant** — a principal investigator — is registered with a `full_name`, a contact `email`, and a `career_stage` of `NEW_INVESTIGATOR`, `EARLY_STAGE_INVESTIGATOR`, or `ESTABLISHED_INVESTIGATOR`.

Against an announcement, an `Applicant` drafts an **Application** by supplying the target `foa_id`, the applicant institution's `institution_id`, a project `title`, the `research_strategy_page_count` (at least one page), the requested budget as `direct_cents_per_year` — an array of integer cents, one entry per project year — and the `requested_years` project period (one to five years). The array length must equal `requested_years` at creation, or the draft is rejected with `ERR_INVALID_BUDGET_STRUCTURE`. The drafting applicant's identity comes from the request context: `applicant_id` is taken from `X-User-ID`, never from the request body. Two boolean flags, `human_subjects_involved` and `vertebrate_animals_involved`, default to false and drive both certification gates and later just-in-time requirements. The applicant may also express referral preferences through `requested_study_section_id` and `requested_institute_id` (both optional and advisory), and may name reviewers to avoid in `excluded_reviewer_ids` (defaulting to an empty list, with no existence check at creation). An applicant may hold only one non-terminal application per announcement: a second draft against the same `foa_id` while an earlier application of the same applicant is not yet `AWARDED`, `NOT_FUNDED`, `UNSCORED`, or `WITHDRAWN` is rejected with `ERR_DUPLICATE_APPLICATION`.

A draft starts in `DRAFT` status with `study_section_id` and `institute_id` unset, `live_assignment_count` at zero, and `impact_score`, `approach_mean`, `significance_mean`, `innovation_mean`, `percentile_raw`, and `percentile_normalized` all null until scoring. The applications collection can be filtered by `foa_id`, `applicant_id`, `institution_id`, `requested_study_section_id`, `requested_institute_id`, `study_section_id`, `institute_id`, or `status`.

### 3.2. Submission, Withdrawal, and the Receipt Window

Submission by the owning `Applicant` runs the announcement's full gate chain against a `DRAFT` application — submitting from any other status is rejected with `ERR_APPLICATION_NOT_SUBMITTABLE`. Following the pipeline order of §2.7, the announcement must still be `OPEN` (`ERR_FOA_NOT_OPEN`); then the applicant institution's compliance record is checked against the application's flags — when `human_subjects_involved` is set, the institution's `human_subjects_certification_expiry` must be present (`ERR_CERTIFICATION_MISSING`) and must not expire before the announcement's `receipt_deadline` (`ERR_CERTIFICATION_EXPIRED`), and when `vertebrate_animals_involved` is set, the `animal_welfare_assurance_expiry` is held to the same two checks; then the `research_strategy_page_count` must not exceed the announcement's `research_strategy_page_limit` (`ERR_PAGE_LIMIT_EXCEEDED`); then the budget is re-validated against announcement bounds — `requested_years` no greater than `max_years`, the `direct_cents_per_year` length equal to `requested_years`, and every year's direct cost at least `min_direct_cents_per_year`, each defect rejecting with `ERR_INVALID_BUDGET_STRUCTURE`, while any year's direct cost above `max_direct_cents_per_year` rejects with `ERR_BUDGET_CAP_EXCEEDED`; and finally the logical clock must not be past the `receipt_deadline` (`ERR_RECEIPT_DEADLINE_PASSED`). A successful submission moves the application from `DRAFT` to `SUBMITTED` and increments its `version` by one.

The owning applicant may withdraw an application while it is `DRAFT`, `SUBMITTED`, `REFERRED`, or `UNDER_REVIEW`; from any other status the attempt is rejected with `ERR_APPLICATION_NOT_WITHDRAWABLE`. Withdrawal lands the application in the terminal `WITHDRAWN` state and increments its `version`. The cascade scales with how far the application had progressed: withdrawing from `DRAFT` or `SUBMITTED` touches nothing else; withdrawing from `REFERRED` additionally decrements the study section's `assigned_application_count`; and withdrawing from `UNDER_REVIEW` first cancels every live assignment — each assignment in `ASSIGNED`, `ACCEPTED`, or `CRITIQUE_SUBMITTED` status moves to `CANCELLED` — then decrements each cancelled assignment's reviewer `active_assignment_count` (only for assignments that were `ASSIGNED` or `ACCEPTED`, since a submitted critique has already freed the reviewer's active slot), and finally decrements the section's `assigned_application_count`.

### 3.3. Referral and the Assignment-Request Honor Rule

Once an application is `SUBMITTED`, a `ReferralOfficer` places it with a review group and a funding institute by supplying the target `study_section_id` and `institute_id`. The application must be `SUBMITTED` or `REFERRED` — referral from any other status is rejected with `ERR_APPLICATION_NOT_REFERRABLE`. The referral carries the OCC expectation described in §2.6: `expected_application_version` must match the application's current `version`, or the request is rejected with `ERR_STALE_APPLICATION_VERSION`. The target study section must exist (`ERR_STUDY_SECTION_NOT_FOUND`) and still be `RECRUITING` (`ERR_SECTION_NOT_RECRUITING`), its `assigned_application_count` must be below its `application_quota` (`ERR_SECTION_QUOTA_EXCEEDED`), and the target institute must exist (`ERR_INSTITUTE_NOT_FOUND`).

Referral honors the applicant's stated preferences. When the application named a `requested_study_section_id` that differs from the referral's target, and the requested section is satisfiable — it exists, is still `RECRUITING`, and has quota capacity remaining — the referral is rejected with `ERR_ASSIGNMENT_REQUEST_IGNORED` unless the officer sets `override_assignment_request` to true. The same rule governs `requested_institute_id`: overriding an existing, requested institute without the override flag is rejected the same way. A request that names a section or institute matching the target, or one that is no longer satisfiable, never triggers the rule.

A successful referral sets the application's `study_section_id` and `institute_id`, moves it to `REFERRED`, increments the section's `assigned_application_count` by one, and increments the application's `version`. Re-referral is a first-class operation: referring an already-`REFERRED` application supersedes the prior placement under a `REFERRED` to `REFERRED` transition, subject to the same target-state checks, the same OCC expectation, and one additional guard — the application's `live_assignment_count` must be zero, because reviewers have not yet been assigned (`ERR_LIVE_ASSIGNMENTS_EXIST` otherwise). When the re-referral changes the section, the old section's `assigned_application_count` decrements and the new section's increments; the application's `version` increments again.

### 3.4. Panel Recruitment, Conflict Screening, and Review Assignments

The `ScientificReviewOfficer` operates the review side of the pipeline, starting with the **StudySection** itself: a review group is created with a `name`, a `meeting_date`, and an `application_quota` of at least one, starting in `RECRUITING` status with `assigned_application_count` at zero.

Reviewer recruitment follows. The SRO places a **Reviewer** on the roster with a `full_name`, an `institution_id` affiliation (which drives institutional conflict screening), and a list of `expertise_keywords`; the reviewer starts `INVITED` with an empty `declared_conflicts` list and an `active_assignment_count` of zero. The reviewer collection can be filtered by `institution_id` or `status`. The invited reviewer then answers for themselves — the roster respond action is owner-scoped — with a `decision` of `ACCEPT` moving them to `ACTIVE`, or `DECLINE` moving them to the terminal `DECLINED` state; responding from any status other than `INVITED` is rejected with `ERR_REVIEWER_INVALID_STATE`. An active reviewer may also self-declare a conflict with a specific application, which appends the `application_id` to their `declared_conflicts` (never duplicating an entry).

With a panel recruited, the SRO creates an **Assignment** by naming the `application_id`, the `reviewer_id`, and a `role` of `PRIMARY` or `SECONDARY`. The reviewer must be `ACTIVE` (`ERR_REVIEWER_NOT_ACTIVE`), and the application's study section must still be `RECRUITING` (`ERR_SECTION_NOT_RECRUITING`). Conflict-of-interest screening then rejects three pairings: the reviewer's `institution_id` matching the application's `institution_id` (`ERR_COI_INSTITUTION_MATCH`); the reviewer appearing in the application's `excluded_reviewer_ids` (`ERR_REVIEWER_EXCLUDED`); and the application appearing in the reviewer's `declared_conflicts` (`ERR_REVIEWER_SELF_DECLARED_CONFLICT`). Uniqueness rules protect the panel's composition: a second live assignment for the same (application, reviewer) pair is rejected with `ERR_DUPLICATE_ASSIGNMENT`; a second live `PRIMARY` assignment for the same application is rejected with `ERR_PRIMARY_ALREADY_ASSIGNED`; and an application may hold at most three live assignments — live meaning `ASSIGNED`, `ACCEPTED`, or `CRITIQUE_SUBMITTED` — beyond which creation is rejected with `ERR_ASSIGNMENT_LIMIT_REACHED`.

Two capacity constraints complete the gate. A reviewer may hold at most four active assignments — assignments in `ASSIGNED` or `ACCEPTED` status; when the reviewer already holds four, creation is rejected with `ERR_REVIEWER_CAPACITY_EXCEEDED`, so the boundary is inclusive at the limit: the fourth active assignment is allowed and the fifth is refused. And a reviewer may not serve two panels that meet too close together: for each of the reviewer's live assignments to an application of a *different* study section, if the absolute difference between the two sections' `meeting_date` values is within seven days — inclusive, so exactly seven days apart is a conflict while seven days and one second is not — creation is rejected with `ERR_MEETING_PROXIMITY_CONFLICT`. Co-review within the same section is normal panel service and is exempt from this check. The assignments collection can be filtered by `application_id`, `reviewer_id`, or `status`.

A created assignment starts in `ASSIGNED` status; the reviewer's `active_assignment_count` and the application's `live_assignment_count` each increment by one. Creating an assignment while the application is `REFERRED` flips it automatically from `REFERRED` to `UNDER_REVIEW` and increments the application's `version` — the first assignment is what puts an application under review.

The assigned reviewer answers with a `decision`: from `ASSIGNED`, `ACCEPT` moves the assignment to `ACCEPTED`, while `DECLINE` from either `ASSIGNED` or `ACCEPTED` moves it to the terminal `DECLINED` state; any other respond attempt is rejected with `ERR_ASSIGNMENT_INVALID_STATE`. A decline decrements the reviewer's `active_assignment_count` by one and the application's `live_assignment_count` by one — and the quorum rule bites here: an application must hold at least two live assignments to remain under review, so when a decline drops an `UNDER_REVIEW` application below two live assignments, the application automatically falls back from `UNDER_REVIEW` to `REFERRED`, increments its `version`, and must attract new assignments before it can be scored.

### 3.5. The Review Meeting: Critiques, Impact Scores, and Percentile Ranking

When at least one application assigned to a `RECRUITING` section has reached `UNDER_REVIEW`, the SRO convenes the review meeting, moving the section from `RECRUITING` to `MEETING_HELD`; convening a section without an under-review application is rejected with `ERR_SECTION_NOT_CONVENABLE`.

With the meeting held, each assigned reviewer submits a critique on their own `ACCEPTED` assignment — submitting from any other assignment state is rejected with `ERR_ASSIGNMENT_INVALID_STATE`, and submitting while the application's section is not `MEETING_HELD` is rejected with `ERR_SECTION_NOT_IN_MEETING`. The critique supplies six integer scores, each from 1 to 9 (`ERR_VALIDATION` otherwise): `significance_score`, `innovation_score`, `approach_score`, `investigator_score`, `environment_score`, and `overall_impact_score`. These fields stay null on the assignment until the critique is submitted. A successful submission moves the assignment from `ACCEPTED` to the terminal `CRITIQUE_SUBMITTED` state and decrements the reviewer's `active_assignment_count` by one — a completed critique frees the active slot — while the application's `live_assignment_count` is unchanged, since a submitted critique still counts as live.

Releasing scores moves the section from `MEETING_HELD` to the terminal `SCORES_RELEASED` state; releasing from any other state is rejected with `ERR_SECTION_NOT_RELEASABLE`. Release runs the scoring computation for every `UNDER_REVIEW` application of the section. Only assignments in `CRITIQUE_SUBMITTED` status enter it — `ASSIGNED`, `ACCEPTED`, `DECLINED`, and `CANCELLED` assignments are excluded. An application with fewer than two submitted critiques becomes `UNSCORED` (a terminal state): its `impact_score`, criterion means, and both percentiles remain null. Otherwise each submitted critique's `overall_impact_score` is weighted — a weight of two for a `PRIMARY` assignment, one for a `SECONDARY` assignment — and the weighted mean is the sum of each score multiplied by its weight, divided by the sum of the weights. The application's `impact_score` is that weighted mean multiplied by ten and rounded half up to a whole number, yielding an integer from 10 to 90. The `approach_mean`, `significance_mean`, and `innovation_mean` are the unweighted means of the corresponding criterion scores across the submitted critiques, each rounded half up to two decimal places. The application moves to `SCORED`, and either way its `version` increments by one.

Release then ranks the section's newly scored applications within the section — the **raw** percentile. The pool is every application of this study section in `SCORED` status, sorted by `impact_score` from lowest to highest; ties break by `approach_mean` lowest first, then `significance_mean` lowest first, then `innovation_mean` lowest first, and finally `created_at` earliest first — the resource `id` is never a tie-break. Each application takes a 1-based rank in this ordering, and its `percentile_raw` is one hundred multiplied by the rank minus one-half, divided by the pool size, rounded half up to one decimal place. Lower is better, and the raw percentile is the metric that select-pay band checks use.

Finally, release re-runs the **normalized** percentile across panels. The pool is every `SCORED` application — in any study section — whose announcement shares the same `activity_code` as the application being ranked. For each section represented in the pool, a section mean is the mean of `impact_score` over that section's `SCORED` applications, rounded half up to one decimal place; a pool mean is computed identically over the whole pool. Each application's adjusted score is its own `impact_score` minus the section mean of its own section plus the pool mean. The pool sorts by adjusted score lowest first, with ties broken by `impact_score` lowest first and then `created_at` earliest first, and each application takes a 1-based rank. The `percentile_normalized` follows the same rank formula — one hundred multiplied by the rank minus one-half, divided by the pool size, rounded half up to one decimal place. Because the normalized variant re-runs over the entire activity-code pool on every release, a later-releasing section rewrites the `percentile_normalized` values of applications scored by earlier sections; the two variants share inputs but rank differently whenever section means differ, and the normalized percentile is the metric that payline decisions use.

### 3.6. Advisory Council Review

Second-level review is performed by a `CouncilMember`, who records a **CouncilReview** for an application in `SCORED` or `DEFERRED` status — recording against any other status is rejected with `ERR_APPLICATION_NOT_SCORED`. The review names the `application_id` and a `recommendation` of `FUND`, `DEFER`, or `NOT_FUND`. A `priority_alignment_score` from 1 to 5 captures program-priority alignment and is required exactly when the recommendation is `FUND` (omitting it there, or supplying a value outside 1 through 5, is rejected with `ERR_VALIDATION`); a `portfolio_balance_note` may optionally record the portfolio rationale. The server stamps the review with `recorded_by`, the council member's opaque `X-User-ID`. All of an application's council reviews can be listed under the application.

The recommendation drives the application's next state, and each recording increments the application's `version` by one. `FUND` moves a `SCORED` or `DEFERRED` application to `COUNCIL_REVIEWED`. `DEFER` moves a `SCORED` application to `DEFERRED`, and recording another `DEFER` on an already-`DEFERRED` application is a legitimate re-deferral that leaves it `DEFERRED`. `NOT_FUND` moves a `SCORED` or `DEFERRED` application to the terminal `NOT_FUNDED` state.

### 3.7. Payline Publication and Select-Pay Decisions

An institute turns council-reviewed applications into funding selections through two mechanisms: a published payline, and discretionary select pay.

Payline publication is a `ProgramOfficer` act on the institute, carrying the requested `base_payline_percentile` and the OCC field `expected_institute_version` (§2.6; a stale expectation is rejected with `ERR_STALE_INSTITUTE_VERSION`). Publication runs a budget walk. The institute's committable authority is its `appropriation_cents` reduced by `committed_cents`, by `disbursed_cents`, and by the untouchable `reserve_cents`. The candidates are the institute's applications in `COUNCIL_REVIEWED` status. Each candidate's effective percentile is its `percentile_normalized` reduced by an early-stage bonus — five percentile points when the applicant's `career_stage` is `EARLY_STAGE_INVESTIGATOR`, zero otherwise — but never below one-tenth of a percentile point. Candidates whose effective percentile does not exceed the requested `base_payline_percentile` are eligible; they are ordered by effective percentile lowest first, with ties broken by `percentile_raw` lowest first, then `impact_score` lowest first, then `created_at` earliest first. Each candidate's projected cost is the sum over its requested years of, per year, the lesser of that year's requested direct cost and the announcement's `max_direct_cents_per_year`, plus that capped amount multiplied by the institute's `indirect_cost_rate` rounded half up to a whole cent; the just-in-time budget cut is not applied in this estimate. The walk then proceeds in order, funding a candidate while the running total of projected costs plus the candidate's own projected cost stays within committable authority, and it stops at the first candidate that would exceed that authority — later, cheaper candidates are never skipped ahead, and the published percentile is never re-derived from the walk's outcome. The institute's `current_payline_percentile` records exactly the requested `base_payline_percentile`, superseding any previously published payline, and the institute's `version` increments by one. Every funded application moves from `COUNCIL_REVIEWED` to `JIT_PENDING`, a just-in-time request is automatically created for it in `ISSUED` status with its `due_date` thirty days after the current logical clock, and the application's `version` increments.

Select pay is the discretionary sibling path, exercised by a `GrantsOfficer` on an application in `COUNCIL_REVIEWED` status — from any other status the attempt is rejected with `ERR_APPLICATION_NOT_FUNDABLE` — with an optional `rationale`. The institute must have a published payline: when `current_payline_percentile` is still null, selection is rejected with `ERR_NO_PAYLINE_PUBLISHED`. The band check then uses the *raw* percentile, not the normalized one: the application's `percentile_raw` must not exceed the institute's `current_payline_percentile` plus its `select_pay_extension_percentile`, or the selection is rejected with `ERR_SELECT_PAY_BAND_EXCEEDED`. Two fiscal gates follow, in this order: first, commitment authority — the selection's projected cost (computed exactly as in the payline walk) must fit, meaning `committed_cents` plus `disbursed_cents` plus the projected cost must not exceed `appropriation_cents` minus `reserve_cents`, or the selection is rejected with `ERR_INSUFFICIENT_COMMITMENT_AUTHORITY`; second, the select-pay cap — `select_pay_spent_cents` plus the projected cost must not exceed the appropriation multiplied by `select_pay_cap_pct`, rounded half up to a whole cent, or the selection is rejected with `ERR_SELECT_PAY_CAP_EXCEEDED`. On success the application moves from `COUNCIL_REVIEWED` to `JIT_PENDING` with the same automatically created `ISSUED` just-in-time request due thirty days out, the institute's `select_pay_spent_cents` grows by the projected cost, and the application's `version` increments.

### 3.8. Just-In-Time Information and Award Issuance

A **JitRequest** is never created directly; it materializes in `ISSUED` status the moment an application is funded by a payline walk or chosen by select pay. Its `application_id` names the funding-selected application. Its `required_items` are derived from the application's flags: `OTHER_SUPPORT` and `BUDGET_JUSTIFICATION` always, plus `IRB_APPROVAL` exactly when `human_subjects_involved` is set, plus `IACUC_APPROVAL` exactly when `vertebrate_animals_involved` is set. The `due_date` falls thirty days after the request's creation as read on the logical clock, `submitted_items` starts empty, and `budget_cut_pct` starts at zero. An application's just-in-time requests can be listed under the application.

The owning `Applicant` answers the request from `ISSUED` or `RETURNED` status — any other state rejects with `ERR_JIT_INVALID_STATE` — by supplying `items_submitted`, which must cover every element of `required_items`; an incomplete package is rejected with `ERR_JIT_ITEM_MISSING`. A successful submission records `submitted_items` as exactly the supplied `items_submitted` and moves the request to `SUBMITTED`. A `GrantsOfficer` then adjudicates a `SUBMITTED` package (otherwise `ERR_JIT_INVALID_STATE`) with a `decision`: `RETURN` moves the request to `RETURNED` — optionally carrying a `return_reason` — so the applicant can revise and resubmit the full item set, while `ACCEPT` moves it to the terminal `ACCEPTED` state, records the supplied `budget_cut_pct` (defaulting to zero, and never above 0.30 — a value outside that range is rejected with `ERR_VALIDATION`) as a uniform direct-cost cut, and advances the application from `JIT_PENDING` to `JIT_COMPLETE`, incrementing the application's `version`.

The thirty-day window is enforced lazily: any JIT operation attempted while the logical clock is past the `due_date` — whether the request stands at `ISSUED`, `SUBMITTED`, or `RETURNED` — moves the request to the terminal `EXPIRED` state, rejects the operation with `ERR_JIT_EXPIRED`, and moves the application from `JIT_PENDING` to the terminal `NOT_FUNDED` state with a version increment.

Award issuance is the `GrantsOfficer`'s act on a `JIT_COMPLETE` application — from any other status it is rejected with `ERR_APPLICATION_NOT_JIT_COMPLETE` — supplying a `start_date` that must not be earlier than the current logical clock (`ERR_VALIDATION`). The award's per-year budget is built from the application's request, the announcement's cap, the institute's rate, and the accepted request's cut. For each requested year: the funded direct cost starts from the lesser of that year's `direct_cents_per_year` entry and the announcement's `max_direct_cents_per_year`; that capped amount is multiplied by one minus the `budget_cut_pct` and rounded half up to a whole cent; the year's indirect cost is that reduced direct amount multiplied by the institute's `indirect_cost_rate`, rounded half up to a whole cent; and the year's entry in `period_total_cents` is the sum of the two rounded components. The evaluation order is pinned: each component is rounded per year *before* any summation — summing first and rounding once is a different, rejected order. The award's `total_awarded_cents` is the sum of the per-year totals, and its `end_date` falls exactly `requested_years` times 365 days after the `start_date`.

The created **Award** records the `application_id`, the funding `institute_id`, and the application's institution as its `institution_id`; it starts `ACTIVE` with `current_period` at 1, `disbursed_cents` at zero, `disbursed_per_period_cents` and `carried_out_per_period_cents` as zeroed per-period arrays, and `originating_transfer_id` null. Its `terms_and_conditions` always contain `STANDARD_TERMS_V1`, and gain `RESTRICTED_DRAW_DOWN` exactly when the accepted `budget_cut_pct` is greater than zero. Issuance adds the `total_awarded_cents` to the institute's `committed_cents` and moves the application from `JIT_COMPLETE` to the terminal `AWARDED` state, incrementing its `version`. The awards collection can be filtered by `application_id`, `institute_id`, `institution_id`, `originating_transfer_id`, or `status`.

### 3.9. Post-Award Administration: Reports, Modifications, and Transfers

Progress reporting keeps the award's ledger honest. The owning `Applicant` files a **ProgressReport** against an `ACTIVE` award — reports against a non-active award are rejected with `ERR_AWARD_NOT_ACTIVE` — naming the `period_year` being reported, the `actual_expenditure_cents` for the period (zero or more), and the `publications_count` arising in the period (zero or more). The `period_year` must equal the award's `current_period` (`ERR_REPORT_PERIOD_MISMATCH`). Each budget period spans 365 days from the award's `start_date`, and the filing window closes ninety days after the current period's end: filing past that close is rejected with `ERR_REPORT_WINDOW_CLOSED`, while filing after the period's end but within the grace window succeeds and records `submitted_late` as true. A new report starts `SUBMITTED`; an award's reports can be listed under the award.

A `GrantsOfficer` accepts a `SUBMITTED` report — acceptance from any other state is rejected with `ERR_REPORT_INVALID_STATE`. Acceptance disburses the period: the disbursed amount is the lesser of the report's `actual_expenditure_cents` and the award's `period_total_cents` entry for the current period. The award's `disbursed_cents` grows by that amount, its `disbursed_per_period_cents` entry for the current period is set to it, the institute's `committed_cents` falls by it, the institute's `disbursed_cents` rises by it, and the award's `current_period` advances by one.

Post-award changes are requested as an **AwardModification** on an `ACTIVE` award, with a `type` of `CARRYOVER`, `NO_COST_EXTENSION`, or `TERMINATION` and an optional `reason`. The role split of §2.1 applies (`ERR_MODIFICATION_TYPE_ROLE_MISMATCH`). Which other fields are required depends on the type: a carryover requires `amount_cents` and `from_period`; a no-cost extension requires `new_end_date`; a missing required-for-type field is rejected with `ERR_VALIDATION`. Each modification records an `auto_approved` flag that is true when the type-specific auto-approval rule fires at creation, and an award's modifications can be listed under the award.

For a carryover, the `from_period` must be the period immediately before the award's `current_period` — `ERR_CARRYOVER_PERIOD_MISMATCH` otherwise; because `current_period` advances only on report acceptance, the source period's report is always already accepted. The source period's unobligated balance is its `period_total_cents` entry minus its `disbursed_per_period_cents` entry; `carried_out_per_period_cents` is an audit trail only and is never subtracted again, because prior carryovers have already reduced `period_total_cents`. The `amount_cents` must not exceed that unobligated balance (`ERR_CARRYOVER_EXCEEDS_UNOBLIGATED`). When the amount is at most one quarter of the unobligated balance — the quarter computed with half-up rounding to a whole cent — the modification lands directly in the terminal `AUTO_APPROVED` state and its effects apply immediately; otherwise it waits in `PENDING_APPROVAL`. The effects, immediate or upon later approval: the source period's `period_total_cents` entry is reduced by the amount, the source period's `carried_out_per_period_cents` grows by it, and the current period's `period_total_cents` entry grows by the same amount, so the award's total budget is conserved.

For a no-cost extension, the request must arrive while the logical clock is not past the award's `end_date` (`ERR_NCE_TOO_LATE`); the `new_end_date` must fall after the current `end_date` (`ERR_VALIDATION`); and the requested extension must not exceed 365 days beyond the current `end_date` (`ERR_NCE_LIMIT_EXCEEDED`). The first approved extension of up to 365 days auto-approves at creation into `AUTO_APPROVED`; when the award already has an approved extension, the request waits in `PENDING_APPROVAL`. Approval sets the award's `end_date` to the `new_end_date`, the extension adjoining the prior end date with no gap and no overlap.

A termination always auto-approves at creation: the modification lands in `AUTO_APPROVED`, the award moves from `ACTIVE` to the terminal `TERMINATED` state, and the institute's `committed_cents` is reduced by the award's undisbursed balance — its `total_awarded_cents` minus its `disbursed_cents`.

Modifications waiting in `PENDING_APPROVAL` are adjudicated by a `GrantsOfficer` with a `decision` — adjudicating from any other state is rejected with `ERR_MODIFICATION_NOT_PENDING`. `APPROVE` moves the modification to the terminal `APPROVED` state and applies the type-specific budget or end-date effects described above; `DENY` moves it to the terminal `DENIED` state with an optional `denial_reason` and no fiscal effect.

A change of institution runs as a three-step transfer. The owning `Applicant` proposes a **TransferRequest** on an `ACTIVE` award by naming the `to_institution_id` and an `effective_date` that must not be earlier than the logical clock (`ERR_VALIDATION`); the transfer-requests collection can be filtered by `award_id`, `to_institution_id`, or `status`. Only one transfer may be in flight per award: proposing while another transfer for the same award is still `PROPOSED` or `RELINQUISHED` is rejected with `ERR_TRANSFER_ALREADY_PENDING`. The receiving institution's compliance record is re-checked against the application's flags as of the `effective_date`: a required certification or assurance that is absent rejects with `ERR_CERTIFICATION_MISSING`, and one that expires before the `effective_date` rejects with `ERR_CERTIFICATION_EXPIRED`. The request starts `PROPOSED` with `proration_variant` and `relinquished_amount_cents` null.

Relinquishment by a `GrantsOfficer` — which requires the `PROPOSED` state, rejecting otherwise with `ERR_TRANSFER_INVALID_STATE` — computes what moves. When at least one progress report has been accepted on the award, so its `disbursed_cents` is greater than zero, the `LEDGER_ACTUALS` variant applies: the entire undisbursed balance moves, and `relinquished_amount_cents` is the `total_awarded_cents` minus the `disbursed_cents`. When no report has been accepted, the `TIME_PRORATED` variant applies a straight-line calendar proration: the relinquished amount is the award's `total_awarded_cents` multiplied by the fraction of the award remaining — the whole days from the `effective_date` to the `end_date` (never below zero) divided by the whole days from the `start_date` to the `end_date` — rounded half up to a whole cent. Either way, the retained amount is whatever neither moved nor was spent — the total minus the disbursed minus the relinquished — and the three parts always re-sum to the award's `total_awarded_cents`. The request records the chosen `proration_variant` and the computed `relinquished_amount_cents` and moves to `RELINQUISHED`.

The final decision by a `GrantsOfficer` requires the `RELINQUISHED` state (`ERR_TRANSFER_INVALID_STATE`). A `decision` of `DECLINE` moves the request to the terminal `DECLINED` state with an optional `decline_reason` and no fiscal movement. A `decision` of `ACCEPT` fires a three-level cascade: first, the original award moves from `ACTIVE` to the terminal `TRANSFERRED` state, and the institute's `committed_cents` is reduced by the relinquished amount plus the retained amount; second, a successor award is created for the same application and institute, with `institution_id` set to the `to_institution_id`, `total_awarded_cents` equal to the relinquished amount, `start_date` equal to the `effective_date`, `end_date` equal to the original award's `end_date`, a single-element `period_total_cents` holding exactly the relinquished amount, `current_period` at 1, `terms_and_conditions` gaining `TRANSFERRED_AWARD` alongside `STANDARD_TERMS_V1`, and `originating_transfer_id` set to the transfer request's `id`; third, the institute's `committed_cents` grows back by the `relinquished_amount_cents`. The transfer request lands in the terminal `ACCEPTED` state.

## 4. Endpoint Definitions

Operations that create a new resource — announcements, institutes, institutions, applicants, applications, study sections, reviewers, assignments, council reviews, awards, progress reports, modifications, and transfer requests — return a `201 Created` status code. Operations that act on an existing resource, including all state-transition and adjudication actions and the clock operation, return a `200 OK` status code. The table below is a summary only; request payloads, response payloads, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (monotonic non-decreasing) | ProgramOfficer |
| POST | `/grants/funding-opportunities` | Create a funding opportunity announcement; starts OPEN | ProgramOfficer |
| GET | `/grants/funding-opportunities/{id}` | Get a funding opportunity | Any authenticated role |
| POST | `/grants/funding-opportunities/{id}/close` | Close an open announcement to further submissions | ProgramOfficer |
| POST | `/grants/institutes` | Create a funding institute with its appropriation ledger configuration | ProgramOfficer |
| GET | `/grants/institutes/{id}` | Get an institute, ledger fields included | Any authenticated role |
| POST | `/grants/institutes/{id}/payline-decisions` | Publish a base payline percentile; funds eligible council-reviewed applications by budget walk (OCC on institute version) | ProgramOfficer |
| POST | `/grants/institutions` | Register an institution with its certifications | ProgramOfficer |
| GET | `/grants/institutions/{id}` | Get an institution | Any authenticated role |
| POST | `/grants/applicants` | Register a principal investigator | ProgramOfficer |
| GET | `/grants/applicants/{id}` | Get an applicant | Any authenticated role |
| POST | `/grants/applications` | Create a draft application against an announcement; applicant identity taken from the request context | Applicant |
| GET | `/grants/applications` | List applications with filters | Any authenticated role |
| GET | `/grants/applications/{id}` | Get an application (scores, percentiles, status) | Any authenticated role |
| POST | `/grants/applications/{id}/submit` | Submit a draft application; runs the full submission validation chain | Applicant |
| POST | `/grants/applications/{id}/withdraw` | Withdraw a non-terminal application before scoring; cascades to assignments and reviewer capacity | Applicant |
| POST | `/grants/applications/{id}/referral` | Refer a submitted application to a study section and institute; re-referral supersedes (OCC on application version) | ReferralOfficer |
| POST | `/grants/applications/{id}/select-pay` | Select a council-reviewed application for pay under institute discretion | GrantsOfficer |
| GET | `/grants/applications/{id}/council-reviews` | List council reviews recorded for an application | Any authenticated role |
| GET | `/grants/applications/{id}/jit-requests` | List just-in-time requests for an application | Any authenticated role |
| POST | `/grants/study-sections` | Create a study section (review group); starts RECRUITING | ScientificReviewOfficer |
| GET | `/grants/study-sections/{id}` | Get a study section | Any authenticated role |
| POST | `/grants/study-sections/{id}/convene` | Convene the review meeting | ScientificReviewOfficer |
| POST | `/grants/study-sections/{id}/release-scores` | Release scores; computes impact scores and both percentile variants | ScientificReviewOfficer |
| POST | `/grants/reviewers` | Recruit a reviewer onto the roster; starts INVITED | ScientificReviewOfficer |
| GET | `/grants/reviewers` | List reviewers with filters | Any authenticated role |
| GET | `/grants/reviewers/{id}` | Get a reviewer | Any authenticated role |
| POST | `/grants/reviewers/{id}/respond` | Reviewer responds to the recruitment invitation | Reviewer |
| POST | `/grants/reviewers/{id}/declare-conflict` | Reviewer self-declares a conflict of interest with an application | Reviewer |
| POST | `/grants/assignments` | Assign a reviewer to an application with a scoring role | ScientificReviewOfficer |
| GET | `/grants/assignments` | List assignments with filters | Any authenticated role |
| GET | `/grants/assignments/{id}` | Get an assignment (scores included once submitted) | Any authenticated role |
| POST | `/grants/assignments/{id}/respond` | Reviewer accepts or declines an assignment | Reviewer |
| POST | `/grants/assignments/{id}/submit-critique` | Reviewer submits criterion scores and overall impact | Reviewer |
| POST | `/grants/council-reviews` | Record an advisory-council second-level review for a scored application | CouncilMember |
| GET | `/grants/jit-requests/{id}` | Get a just-in-time request | Any authenticated role |
| POST | `/grants/jit-requests/{id}/submit-items` | Applicant submits the full set of outstanding JIT items | Applicant |
| POST | `/grants/jit-requests/{id}/adjudicate` | Grants officer accepts (with optional uniform budget cut) or returns a submitted JIT package | GrantsOfficer |
| POST | `/grants/applications/{id}/award` | Issue the award for a JIT-complete application; computes the per-year budget | GrantsOfficer |
| GET | `/grants/awards` | List awards with filters | Any authenticated role |
| GET | `/grants/awards/{id}` | Get an award (budget arrays, disbursal, status) | Any authenticated role |
| POST | `/grants/awards/{id}/progress-reports` | Submit the progress report for the award's current budget period | Applicant |
| GET | `/grants/awards/{id}/progress-reports` | List progress reports for an award | Any authenticated role |
| POST | `/grants/progress-reports/{id}/accept` | Accept a submitted progress report; disburses the period and advances the current period | GrantsOfficer |
| POST | `/grants/awards/{id}/modifications` | Request a post-award modification (carryover, no-cost extension, or termination) | Applicant, GrantsOfficer |
| GET | `/grants/awards/{id}/modifications` | List modifications for an award | Any authenticated role |
| POST | `/grants/award-modifications/{id}/adjudicate` | Approve or deny a pending modification | GrantsOfficer |
| POST | `/grants/awards/{id}/transfer-requests` | Propose a change-of-institution transfer for an active award | Applicant |
| GET | `/grants/transfer-requests` | List transfer requests with filters | Any authenticated role |
| GET | `/grants/transfer-requests/{id}` | Get a transfer request | Any authenticated role |
| POST | `/grants/transfer-requests/{id}/relinquish` | Relinquish the award from the current institution; computes the relinquished amount | GrantsOfficer |
| POST | `/grants/transfer-requests/{id}/decide` | Accept (successor-award cascade) or decline a relinquished transfer | GrantsOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_MODIFICATION_TYPE_ROLE_MISMATCH` | 403 Forbidden |
| `ERR_FOA_NOT_FOUND` | 404 Not Found |
| `ERR_INSTITUTE_NOT_FOUND` | 404 Not Found |
| `ERR_INSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEWER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_JIT_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRESS_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_MODIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_BUDGET_STRUCTURE` | 400 Bad Request |
| `ERR_INVALID_CLOCK_VALUE` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_FOA_NOT_OPEN` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_REFERRABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_SCORED` | 409 Conflict |
| `ERR_APPLICATION_NOT_FUNDABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_JIT_COMPLETE` | 409 Conflict |
| `ERR_SECTION_NOT_RECRUITING` | 409 Conflict |
| `ERR_SECTION_NOT_CONVENABLE` | 409 Conflict |
| `ERR_SECTION_NOT_IN_MEETING` | 409 Conflict |
| `ERR_SECTION_NOT_RELEASABLE` | 409 Conflict |
| `ERR_REVIEWER_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEWER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_JIT_INVALID_STATE` | 409 Conflict |
| `ERR_JIT_EXPIRED` | 409 Conflict |
| `ERR_AWARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_MODIFICATION_NOT_PENDING` | 409 Conflict |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 Conflict |
| `ERR_TRANSFER_INVALID_STATE` | 409 Conflict |
| `ERR_NO_PAYLINE_PUBLISHED` | 409 Conflict |
| `ERR_DUPLICATE_PA_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_PRIMARY_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_ASSIGNMENT_LIMIT_REACHED` | 409 Conflict |
| `ERR_SECTION_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_LIVE_ASSIGNMENTS_EXIST` | 409 Conflict |
| `ERR_CERTIFICATION_MISSING` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_COI_INSTITUTION_MATCH` | 409 Conflict |
| `ERR_REVIEWER_EXCLUDED` | 409 Conflict |
| `ERR_REVIEWER_SELF_DECLARED_CONFLICT` | 409 Conflict |
| `ERR_ASSIGNMENT_REQUEST_IGNORED` | 409 Conflict |
| `ERR_RECEIPT_DEADLINE_PASSED` | 409 Conflict |
| `ERR_MEETING_PROXIMITY_CONFLICT` | 409 Conflict |
| `ERR_REPORT_PERIOD_MISMATCH` | 409 Conflict |
| `ERR_REPORT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CARRYOVER_PERIOD_MISMATCH` | 409 Conflict |
| `ERR_NCE_TOO_LATE` | 409 Conflict |
| `ERR_NCE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PAGE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BUDGET_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CARRYOVER_EXCEEDS_UNOBLIGATED` | 422 Unprocessable Entity |
| `ERR_JIT_ITEM_MISSING` | 422 Unprocessable Entity |
| `ERR_SELECT_PAY_BAND_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_COMMITMENT_AUTHORITY` | 402 Payment Required |
| `ERR_SELECT_PAY_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INSTITUTE_VERSION` | 412 Precondition Failed |
