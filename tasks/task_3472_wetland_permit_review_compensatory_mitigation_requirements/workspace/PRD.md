# Wetland Permit Review API — Product Requirements Document

## 1. Introduction

Regulators reviewing work in jurisdictional wetlands and waters carry a heavy evidentiary burden: before any fill is authorized, the reviewing district must establish whether the waters are even regulated, weigh whether the applicant has avoided and minimized impacts, open the proposal to public and agency scrutiny, and — only after all of that — decide how much compensatory mitigation is owed and whether it has actually been secured. When work proceeds without authorization, the same office must open an enforcement case, accrue civil penalties, and drive the matter to either verified restoration or an after-the-fact permit. Today these steps live in disconnected spreadsheets and correspondence files, which makes it impossible to guarantee that a permit was never issued over an unresolved objection, that a mitigation bank's credit inventory was never oversold, or that a monitoring report more than sixty days late always escalated into enforcement.

This document specifies a single REST API for that entire lifecycle. It covers jurisdictional determinations with delineation review and appeal rights; permit pathway selection between streamlined general permits and individual permits with public notice; alternatives analysis gated on demonstrated avoidance and minimization; a weighted public interest review balancing environmental, economic, and navigation considerations against agency comments; compensatory mitigation through bank credit purchase, in-lieu fee payment, or permittee-responsible plans with ratios that vary by resource type, service location, and timing lag; permit issuance with pinned special conditions; a five-year monitoring and long-term stewardship regime; and enforcement of unauthorized fill with restoration orders, penalty accrual, and after-the-fact permits.

All resources are mounted under the `/wetland-permits` prefix, with one platform-level test-driving capability for the logical clock mounted outside that prefix. The API is deliberately strict about ordering — avoidance before compensation, comment closure before decision, secured credits before issuance — because each of those orderings is a legal requirement of the program, not an implementation preference.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting principal, and `X-User-Role` naming the principal's role. If either header is missing, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401). If the role is valid but does not appear in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles, spelled exactly as the API expects them, are:

- `SystemAdmin` — the platform operator; provisions applicants, waters sites, and mitigation banks, and is the only role permitted to drive the logical clock.
- `Applicant` — a permit seeker; owns sites, applications, alternatives analyses, mitigation plans, credit transactions, appeals, monitoring submissions, and work commencement.
- `Reviewer` — a Corps project manager; drafts jurisdictional determinations, screens applications, reviews alternatives analyses and mitigation plans, resolves agency comments, and reviews monitoring reports.
- `DistrictEngineer` — the decision authority; issues determinations, decides appeals, approves and suspends banks, renders permit decisions, reinstates and closes permits, and grants restoration extensions.
- `AgencyReviewer` — a cooperating agency reviewer (EPA, FWS, NMFS, state water quality, or tribal authority); files agency comments during open comment periods.
- `EnforcementOfficer` — a compliance and enforcement officer; opens and confirms enforcement cases (never both on the same case), sets resolution tracks, and verifies restoration.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an `Applicant` compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `SystemAdmin`, `Reviewer`, `DistrictEngineer`, `AgencyReviewer`, or `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `screening_reviewer_id` on a permit application when screening begins, or as `opened_by_officer_id` on an enforcement case at creation — but it never compares such an identifier to any entity's `id` for ownership. Two segregation-of-duties gates do compare these recorded operator identifiers against the caller's `X-User-ID` (decision rendering and violation confirmation); they are specified in §2.9 and rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every list endpoint accepts two optional query parameters: `limit`, which defaults to 10 and must be at least 1 and at most 100, and `offset`, which defaults to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Unless an endpoint's description pins a different key, list results are sorted by `created_at` ascending. The monitoring report list is the one pinned exception: its results are sorted by `period_index` ascending.
### 2.4. Resource Identity, Timestamps, and Versioning

All thirteen resource types — `Applicant`, `WatersSite`, `JurisdictionalDetermination`, `Appeal`, `PermitApplication`, `AlternativesAnalysis`, `AgencyComment`, `MitigationPlan`, `MitigationBank`, `CreditTransaction`, `Permit`, `MonitoringReport`, and `EnforcementCase` — share the same common properties. Every resource carries an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp; an `updated_at` timestamp; and a `version` integer. Both timestamps are ISO 8601 UTC values rendered with three fractional digits. The `version` starts as a small integer at creation and is incremented by exactly 1 on every mutation of the resource, with `updated_at` refreshed to the mutation's logical-clock value at the same time. Single-resource reads address the resource by its `id` in the final path segment.

### 2.5. The Logical Clock and Time-Driven Transitions

The system runs on a logical clock, never on wall-clock time. Before any operator sets it, the logical clock's startup default is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `SystemAdmin` advances the clock through an admin-only test-driving capability mounted outside the `/wetland-permits` prefix, supplying a `to_iso8601` instant; the capability responds with the new `current_utc`. The new instant must be strictly greater than the current logical clock value — a request to move the clock backward, or to the identical instant, is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422).

Advancing the clock is the trigger for every time-based transition in the system, and the evaluation order is pinned so that outcomes do not depend on implementation scheduling. On each clock set, the system evaluates, in exactly this order:

1. Published notices whose comment window has fully elapsed — that is, the new clock is strictly greater than `notice_published_date` plus `comment_period_days` days — move `notice_status` from `PUBLISHED` to `COMMENT_PERIOD_CLOSED`. A clock value exactly equal to the publication instant plus the comment period leaves the window `PUBLISHED`; the comparison is strictly-greater.
2. Permits in `ISSUED` or `ACTIVE` whose `expiration_date` is now in the past (new clock strictly greater) transition to `EXPIRED`, and each such permit's linked mitigation plan in `ACTIVE` transitions to `DEFAULTED`.
3. Monitoring reports in `DUE` whose `due_date` is now in the past transition to `OVERDUE` — but only for permits still in `ACTIVE` after step 2.
4. Breach escalation: any report in `OVERDUE` whose `due_date` is more than 60 days in the past (new clock strictly greater than `due_date` plus 60 days) on a permit still `ACTIVE` suspends that permit (`ACTIVE` to `SUSPENDED`) and auto-creates an enforcement case of `case_source` `MONITORING_BREACH`.
5. Enforcement cases on the `RESTORATION` track in `RESOLUTION_PENDING` whose `restoration_deadline` is now in the past transition to `DEFAULTED`.

Jurisdictional determination expiry is deliberately lazy: there is no `EXPIRED` status value for a determination. An `ISSUED` determination whose `expiration_date` is before the current clock is simply treated as expired at validation time — it fails a submission check with `ERR_JD_EXPIRED`, and it no longer blocks issuance of a new determination for the same site.

### 2.6. Numeric Precision and Rounding

All credit quantities and dollar amounts are carried at two decimal places, and every rounding performed by the system is round-half-up. Three rounding orders are pinned because different orders yield different cents. For the in-lieu fee, each per-resource-type line is rounded half-up to cents first, and the fee total is the exact sum of those rounded lines — summing unrounded products and rounding once at the end is forbidden. For bank credit pricing, the per-credit unit price is rounded half-up to two decimal places first, then multiplied by the number of credits and rounded half-up to two decimal places again. For the public interest review score, the environmental, economic, and navigation components are carried unrounded until the final weighted sum, which alone is rounded half-up to two decimal places. Mitigation credit requirements are rounded half-up to two decimal places per resource-type line and stored per type. The enforcement penalty accrues exactly (no rounding during accrual); rounding half-up to two decimal places happens only when the penalty is fixed at case closure.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint takes a version field. Editing a permit application requires the request to carry `expected_application_version`, holding the application `version` the client last observed; if that value no longer equals the application's current `version` — because a prior edit has already advanced it since the client's last read, so the client's edits are based on a stale record — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Editing a mitigation plan likewise requires `expected_plan_version` equal to the plan's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. This second guard matters even though a successful edit on a draft plan leaves the plan in `DRAFT`: no state precondition catches a second edit carrying an earlier observed version, so only the version check rejects it. The same holds for application edits, which are permitted while the application is in `DRAFT` or `RETURNED_TO_APPLICANT` and do not change status.

### 2.8. The Validation Pipeline: First Failure Wins

Every request is checked against an ordered validation pipeline, and the first failing check wins — its error is the one returned, and no later check masks an earlier failure. The pipeline runs in this order:

1. Header presence and role membership: `X-User-ID` and `X-User-Role` present and the role one of the six declared roles, else `ERR_MISSING_AUTH`.
2. Role authorization: the role appears in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`.
3. Path existence: every `{id}` segment of the URL must reference an existing entity, validated left-to-right, else the per-resource 404 — `ERR_APPLICANT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_JD_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_AA_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_BANK_NOT_FOUND`, `ERR_CREDIT_TXN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`, chosen by resource type.
4. Applicant ownership (applicant-scoped writes): the `Applicant` caller must own the target resource, else `ERR_NOT_RESOURCE_OWNER`.
5. Body foreign-key existence: identifier fields in the payload — `site_id`, `jd_id`, `new_jd_id`, `application_id`, `bank_id`, `plan_id`, `enforcement_case_id`, `atf_application_id` — must reference existing entities, else the corresponding 404 (`ERR_SITE_NOT_FOUND`, `ERR_JD_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_BANK_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, or `ERR_CASE_NOT_FOUND`).
6. Request shape: required fields present, enumerations valid, numbers in range, the `impacts` array non-empty with each line's resource type among the site's present types and a positive acreage, after-the-fact pathways carrying an `enforcement_case_id` whose case names the same responsible applicant, general pathways carrying a `general_permit_code`, `comment_period_days` within its allowed window, and `stewardship_entity_name` present where the mechanism demands it — any failure is `ERR_INVALID_REQUEST` (HTTP 400).
7. State preconditions: the target entity must be in a state from which the invoked transition is defined, else the per-entity 409 — `ERR_JD_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_AA_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_CREDIT_TXN_INVALID_STATE`, `ERR_PERMIT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, or `ERR_BANK_NOT_OPERATIONAL`. This tier also covers three cross-entity state reads: at application submission the referenced determination must be `ISSUED`; at credit-transaction creation the linked plan must be `APPROVED`; and a bank must be `OPERATIONAL` before it accepts reservations.
8. Optimistic concurrency: `expected_application_version` or `expected_plan_version` must equal the entity's current `version`, else `ERR_STALE_VERSION`.

Only after all eight general tiers pass do the domain rules run, again in a pinned relative order: appeal rights limited to `APPROVED` determinations (`ERR_JD_NOT_APPEALABLE`); the sixty-day appeal window (`ERR_APPEAL_WINDOW_CLOSED`); the referenced determination unexpired at submission (`ERR_JD_EXPIRED`); agency comments only while the notice is published (`ERR_COMMENT_PERIOD_CLOSED`); decision advance only after the comment period closes (`ERR_NOTICE_PERIOD_STILL_OPEN`); the two segregation-of-duties gates (`ERR_SEGREGATION_OF_DUTIES`); general-permit eligibility (`ERR_GENERAL_PERMIT_INELIGIBLE`); the LEDPA gate (`ERR_LEDPA_NOT_DEMONSTRATED`); a favorable public interest outcome for issuance on individual pathways (`ERR_PUBLIC_INTEREST_UNFAVORABLE`); the referenced determination being jurisdictional (`ERR_JD_NOT_JURISDICTIONAL`); avoidance-and-minimization-before-compensation sequencing (`ERR_AA_NOT_ACCEPTED`); zero unresolved substantive objections (`ERR_UNRESOLVED_AGENCY_OBJECTIONS`); after-the-fact linkage integrity (`ERR_CASE_INVALID_STATE`); one live determination per site (`ERR_ACTIVE_JD_EXISTS`); one appeal per determination (`ERR_APPEAL_ALREADY_FILED`); the singleton rules for analyses, notices, and active plans (`ERR_AA_ALREADY_EXISTS`, `ERR_NOTICE_ALREADY_PUBLISHED`, `ERR_ACTIVE_PLAN_EXISTS`); in-state bank service (`ERR_OUT_OF_SERVICE_AREA`); monitoring coverage contiguity (`ERR_COVERAGE_INTERVAL_CONFLICT`); sufficient bank inventory (`ERR_INSUFFICIENT_CREDIT_INVENTORY`); credit-securing sufficiency (`ERR_CREDITS_NOT_SECURED`, `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE`); exact in-lieu fee payment (`ERR_PAYMENT_AMOUNT_MISMATCH`); the decision and permit-lifecycle prerequisites (`ERR_MITIGATION_NOT_SECURED`, `ERR_REPORTS_OVERDUE_EXIST`, `ERR_MONITORING_INCOMPLETE`); and finally clock monotonicity (`ERR_CLOCK_REGRESSION`). Because ordering is observable, note the sequence for a determination referenced at submission: a determination that is not `ISSUED` fails at the state tier with `ERR_JD_INVALID_STATE` before expiry is considered, an expired one then fails with `ERR_JD_EXPIRED`, and only then can a non-jurisdictional one fail with `ERR_JD_NOT_JURISDICTIONAL`.

### 2.9. Applicant Ownership Scoping and Segregation of Duties

Ownership scoping applies whenever `X-User-Role` is `Applicant`. For an application, the caller's `X-User-ID` must equal the application's `applicant_id`. For an appeal, it must equal the `applicant_id` of the site whose determination is being appealed. For an alternatives analysis, a mitigation plan, a credit transaction, a monitoring report, or a permit, it must equal the `applicant_id` of the parent application the resource belongs to. A violation is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The applicant-scoped writes are: filing an appeal; creating, editing, submitting, and withdrawing applications; creating and revising alternatives analyses; creating, editing, submitting, securing, and paying mitigation plans; creating, purchasing, and releasing credit transactions; commencing work on a permit; and submitting monitoring reports. When an `Applicant` reads a single applicant record, the requested `id` must be the caller's own.

Two operations are additionally protected by segregation of duties, because the same person must never both prepare and decide. Rendering a permit decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the caller's `X-User-ID` equals the application's recorded `screening_reviewer_id`. Confirming a violation is rejected with the same error when the caller's `X-User-ID` equals the case's recorded `opened_by_officer_id` — the officer who opens a case may never be the one who confirms it.
## 3. Business Logic & Workflows

### 3.1. Establishing the Record: Applicants, Sites, and Jurisdictional Determinations

Before any permit activity exists, a `SystemAdmin` registers the parties and the land. Registering an applicant captures the `legal_name`, an `organization_type` of exactly one of `INDIVIDUAL`, `CORPORATION`, `GOVERNMENT`, or `NONPROFIT`, and a `contact_email`. The new applicant's `prior_violation_count` is initialized to 0; thereafter it is a computed value, counting the enforcement cases that name this applicant as `responsible_applicant_id` and whose `case_status` is anything other than `OPENED` — that is, cases that have matured past mere opening.

Registering a waters site ties the land to its owner: the payload names the owning `applicant_id`, a `site_name`, the two-letter `state_code` where the site sits, an eight-digit hydrologic unit `watershed_code`, the `total_acres` of the site (which must be greater than zero), and `resource_types_present`, a non-empty subset drawn from `EMERGENT_MARSH`, `FORESTED_WETLAND`, `OPEN_WATER`, and `STREAM`. The site roster can be listed with an optional `applicant_id` filter, and both sites and applicants are readable by every role.

A jurisdictional determination records whether the site's waters are regulated. A `Reviewer` drafts one by supplying the `site_id`, a `jd_type` of `PRELIMINARY` or `APPROVED`, a `determination` of `JURISDICTIONAL` or `NON_JURISDICTIONAL`, and the delineation review `rationale`. A new determination sits in `DRAFT`, and while it does both `issued_date` and `expiration_date` are null. Issuance is the `DistrictEngineer`'s act and is guarded by the one-live-determination rule: no other determination for the same site may already be `ISSUED` with an `expiration_date` still at or beyond the current clock, otherwise the issuance is rejected with `ERR_ACTIVE_JD_EXISTS` (HTTP 409). On issuance the determination moves `DRAFT` to `ISSUED`, `issued_date` is set to the current logical clock, and `expiration_date` is fixed at the issuance instant plus 1825 days — five years of validity. Expiry itself is lazy, as §2.5 describes: an expired determination never changes state on its own, it simply stops satisfying submission checks and stops blocking a successor. The determination's terminal state is `REVERSED`, reachable only through the appeal machinery of §3.2. Determinations can be listed with optional `site_id`, `jd_type`, and `status` filters. Operating on a determination in the wrong state — issuing one that is not `DRAFT`, or appealing or submitting against one that is not `ISSUED` — is rejected with `ERR_JD_INVALID_STATE` (HTTP 409).

### 3.2. Appeal Rights and the Suspension Cascade

Only an `APPROVED` determination carries appeal rights; attempting to appeal a `PRELIMINARY` one is rejected with `ERR_JD_NOT_APPEALABLE` (HTTP 422). An `Applicant` files an appeal by naming the `jd_id` and stating the `grounds_text`, and three further guards apply at filing time: the determination must currently be `ISSUED`; the filing must fall inside the appeal window, meaning the gap between the filing clock and the determination's `issued_date` is at most 60 days — exactly 60 days is allowed, one day more is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422); and each determination carries at most one appeal, so a second filing against the same determination is rejected with `ERR_APPEAL_ALREADY_FILED` (HTTP 409). The filer must own the site's applicant record per the ownership rule, and at filing the system stamps `appellant_applicant_id` from the caller's `X-User-ID`, sets `filed_date` to the logical clock, and opens the appeal in `FILED` with `decided_date` and `decision_rationale` still null.

A `DistrictEngineer` decides a `FILED` appeal by supplying an `outcome` and a `decision_rationale`. Either way, `decided_date` is set to the clock and the rationale is copied onto the appeal. A decision of `DENIED` ends the matter — `FILED` to `DENIED` — with no further effect. A decision of `SUSTAINED` is far more consequential: the appeal moves `FILED` to `SUSTAINED`, and the referenced determination reverses from `ISSUED` to `REVERSED`, firing the suspension cascade. Every permit application that references the reversed determination and sits in `SUBMITTED`, `SCREENING`, `RETURNED_TO_APPLICANT`, `ALTERNATIVES_REVIEW`, `PUBLIC_NOTICE_OPEN`, or `DECISION_PENDING` transitions to `SUSPENDED_PENDING_JD`; and for each such application, every credit transaction of the application's mitigation plans still in `RESERVED` transitions to `RELEASED`, restoring the bank's inventory. Appeals in any state other than `FILED` refuse a decision with `ERR_APPEAL_INVALID_STATE` (HTTP 409). Appeals can be listed with optional `jd_id`, `appellant_applicant_id`, and `status` filters.

A suspended application is not dead. The applicant may resubmit it by naming a `new_jd_id` that references a determination for the same site — one that is `ISSUED`, carries a `JURISDICTIONAL` determination, and is unexpired at the current clock. A missing reference yields `ERR_JD_NOT_FOUND`; the wrong state, wrong determination, or expiry yield `ERR_JD_INVALID_STATE`, `ERR_JD_NOT_JURISDICTIONAL`, or `ERR_JD_EXPIRED` respectively. On a successful resubmission the application's `jd_id` is replaced with the new determination, `submitted_date` is restamped to the clock, and the application returns to `SUBMITTED`.

### 3.3. Pathways, Submission, and Screening

An `Applicant` opens a permit application in `DRAFT` by supplying the `site_id`, the `jd_id` of the determination it relies on, a `pathway` of `GENERAL`, `INDIVIDUAL`, `ATF_GENERAL`, or `ATF_INDIVIDUAL`, a non-empty `impacts` array whose lines each pair a `resource_type` with a strictly positive `impact_acres`, a `project_purpose` statement, and an `estimated_cost_dollars` of zero or more. Every impact line's resource type must appear among the site's `resource_types_present`. The `applicant_id` is set from the caller's `X-User-ID`, never from the payload. Two conditional fields attach at creation: `general_permit_code` is required exactly when the pathway is `GENERAL` or `ATF_GENERAL` and must be `NWP-29` or `NWP-39`, and `enforcement_case_id` is required exactly when the pathway is after-the-fact, naming an existing case whose `responsible_applicant_id` equals the creating applicant — shape failures of any of these rules are `ERR_INVALID_REQUEST` (HTTP 400). At creation the system computes `total_impact_acres` as the sum of the impact lines' acreages, derives `is_after_the_fact` as true exactly for the two after-the-fact pathways, and derives `compensatory_mitigation_required` as true exactly when `total_impact_acres` is strictly greater than 0.10 acres. The independent notice dimension `notice_status` starts at `NONE`, and `submitted_date`, `pir_score`, and `pir_outcome` stay null for now.

The general-permit pathways are deliberately narrow, and their eligibility rule is enforced both when the application is created and again when it is submitted: the `general_permit_code` must be `NWP-29` or `NWP-39`, the `total_impact_acres` must not exceed 0.50 acres (exactly 0.50 remains eligible), and every impact line's resource type must be `EMERGENT_MARSH` or `STREAM`. Any breach is `ERR_GENERAL_PERMIT_INELIGIBLE` (HTTP 422). The after-the-fact pathways carry their own gate, also checked at creation and again at submission: the linked enforcement case must exist with a `case_status` of `VIOLATION_CONFIRMED` or `RESOLUTION_PENDING`, else `ERR_CASE_INVALID_STATE` (HTTP 409).

While an application is in `DRAFT` or `RETURNED_TO_APPLICANT`, the applicant may edit it — the `site_id`, `jd_id`, `pathway`, `impacts`, `project_purpose`, `estimated_cost_dollars`, and the two conditional fields are all editable — carrying the `expected_application_version` guard of §2.7. The edit leaves the status untouched, recomputes the derived fields, and bumps the application's `version` by 1.

Submission moves an application from `DRAFT` or `RETURNED_TO_APPLICANT` to `SUBMITTED`, and it is the first real regulatory checkpoint. The referenced determination must be `ISSUED` (else `ERR_JD_INVALID_STATE` at the state tier), must be unexpired — the current clock no later than its `expiration_date`, with expiry exactly at the clock still acceptable, else `ERR_JD_EXPIRED` (HTTP 409) — and must carry a `JURISDICTIONAL` determination, else `ERR_JD_NOT_JURISDICTIONAL` (HTTP 422); a `NON_JURISDICTIONAL` site needs no permit at all. The general-permit and after-the-fact gates re-run as described above. A successful submission stamps `submitted_date` with the logical clock.

Screening is the `Reviewer`'s three-way fork, driven by an `action` in the payload. Beginning screening moves `SUBMITTED` to `SCREENING` and captures `screening_reviewer_id` from the invoking reviewer's `X-User-ID` — the value the segregation-of-duties gate will compare against at decision time. Returning the package moves `SCREENING` to `RETURNED_TO_APPLICANT`, optionally carrying a `return_reason`, and the applicant may edit and resubmit from there. Approving from `SCREENING` splits by pathway: an `INDIVIDUAL` or `ATF_INDIVIDUAL` application advances to `ALTERNATIVES_REVIEW`, while a `GENERAL` or `ATF_GENERAL` application jumps straight to `DECISION_PENDING` — the streamlined path skips alternatives review, public notice, and the public interest review entirely, which is why the general pathways never carry a `pir_score` or `pir_outcome`.

The applicant may withdraw from any non-terminal pre-decision state — `DRAFT`, `SUBMITTED`, `SCREENING`, `RETURNED_TO_APPLICANT`, `ALTERNATIVES_REVIEW`, `PUBLIC_NOTICE_OPEN`, `DECISION_PENDING`, or `SUSPENDED_PENDING_JD` — moving the application to `WITHDRAWN`. Withdrawal runs the same credit compensation cascade and plan cancellation as a denial, specified in §3.7, with one nuance: a withdrawal from `SUSPENDED_PENDING_JD` finds no reserved credit transactions left (they were released at suspension), so only the plan cancellation applies. Every other state-targeted application action attempted from a state where it is not defined is rejected with `ERR_APPLICATION_INVALID_STATE` (HTTP 409). The full status vocabulary is `DRAFT`, `SUBMITTED`, `SCREENING`, `RETURNED_TO_APPLICANT`, `ALTERNATIVES_REVIEW`, `PUBLIC_NOTICE_OPEN`, `DECISION_PENDING`, `ISSUED`, `DENIED`, `WITHDRAWN`, and `SUSPENDED_PENDING_JD`, of which `ISSUED`, `DENIED`, and `WITHDRAWN` are terminal. Applications can be listed with optional `applicant_id`, `site_id`, `jd_id`, `status`, and `enforcement_case_id` filters.
### 3.4. Alternatives Analysis and the LEDPA Gate

Individual-pathway review begins from the sequencing principle that compensation is the last resort: avoidance and minimization must be demonstrated before any compensatory mitigation is even considered. Once an application reaches `ALTERNATIVES_REVIEW`, the applicant files exactly one alternatives analysis for it — a second analysis for the same application is rejected with `ERR_AA_ALREADY_EXISTS` (HTTP 409), and filing while the application is anywhere else is rejected with `ERR_AA_INVALID_STATE` (HTTP 409). The filing payload carries the `application_id`, an `avoidance_demonstrated` flag, an `avoidance_narrative`, a `minimization_steps` array of step descriptions, a `ledpa_conclusion` of `PROPOSED_IS_LEDPA`, `ALTERNATIVE_IS_LEDPA`, or `UNDETERMINED`, and an `offsite_alternatives_considered` count of zero or more. The analysis opens in `SUBMITTED` with `revision_count` at 0.

A `Reviewer` then renders a `verdict`. Requesting revision moves the analysis `SUBMITTED` to `REVISION_REQUESTED` and may carry `revision_notes`; outright rejection moves it to `REJECTED`, a terminal state. Accepting the analysis is gated on the LEDPA demonstration — the least environmentally damaging practicable alternative: acceptance requires `avoidance_demonstrated` to be true, at least two entries in `minimization_steps`, and a `ledpa_conclusion` of `PROPOSED_IS_LEDPA`, all three together, else the acceptance is rejected with `ERR_LEDPA_NOT_DEMONSTRATED` (HTTP 422). A successful accept moves the analysis `SUBMITTED` to `ACCEPTED`, also terminal. The applicant revises a `REVISION_REQUESTED` analysis by editing any of `avoidance_demonstrated`, `avoidance_narrative`, `minimization_steps`, `ledpa_conclusion`, or `offsite_alternatives_considered`; the edit returns the analysis to `SUBMITTED` and increments `revision_count` by 1. Reviewing an analysis that is not `SUBMITTED`, or revising one that is not `REVISION_REQUESTED`, is `ERR_AA_INVALID_STATE`. Analyses can be listed with optional `application_id` and `status` filters.

The sequencing principle binds two later steps: creating a mitigation plan for an `INDIVIDUAL` or `ATF_INDIVIDUAL` application requires the analysis to already be `ACCEPTED`, and publishing the public notice requires the same — both fail with `ERR_AA_NOT_ACCEPTED` (HTTP 422) otherwise. The general pathways, having skipped alternatives review, instead require the application to sit in `DECISION_PENDING` before a plan can be created; a violation there surfaces at the state tier.

### 3.5. Public Notice, Agency Comments, and the Public Interest Review

With an accepted analysis in hand, a `Reviewer` publishes the public notice, which requires the application in `ALTERNATIVES_REVIEW`, the analysis `ACCEPTED` (else `ERR_AA_NOT_ACCEPTED`), and the notice dimension still at `NONE` — a notice already published cannot be published again, `ERR_NOTICE_ALREADY_PUBLISHED` (HTTP 409). Publication moves the application to `PUBLIC_NOTICE_OPEN`, sets `notice_status` to `PUBLISHED`, stamps `notice_published_date` with the clock, and fixes `comment_period_days` to the payload value if supplied, defaulting to 30 days; any supplied value must lie between 15 and 60 days inclusive, else `ERR_INVALID_REQUEST`. Thereafter the notice dimension evolves orthogonally to the main status: when the clock advances strictly past `notice_published_date` plus `comment_period_days` days, `notice_status` moves `PUBLISHED` to `COMMENT_PERIOD_CLOSED`. A clock landing exactly on the boundary leaves the window open — the comparison is strictly greater.

While `notice_status` is `PUBLISHED`, an `AgencyReviewer` files agency comments against the application, each carrying the `application_id`, an `agency` of `EPA`, `FWS`, `NMFS`, `STATE_WATER_QUALITY`, or `TRIBAL_AUTHORITY`, a `comment_type` of `ADVISORY`, `SUBSTANTIVE_OBJECTION`, or `CONCURRENCE`, and the `comment_text`. Filing stamps `filed_date` and opens the comment in `FILED`. Once the window is anything other than `PUBLISHED`, filing is rejected with `ERR_COMMENT_PERIOD_CLOSED` (HTTP 422). A `Reviewer` resolves a `FILED` comment by supplying `resolution_text`, which is copied onto the comment as it moves to `RESOLVED`. Comments can be listed with optional `application_id`, `comment_type`, `status`, and `agency` filters.

Advancing the application from `PUBLIC_NOTICE_OPEN` to `DECISION_PENDING` is the `Reviewer`'s act and carries two preconditions: the notice dimension must have reached `COMMENT_PERIOD_CLOSED`, else `ERR_NOTICE_PERIOD_STILL_OPEN` (HTTP 422), and no agency comment of this application may remain with `comment_type` `SUBSTANTIVE_OBJECTION` and `status` `FILED`, else `ERR_UNRESOLVED_AGENCY_OBJECTIONS` (HTTP 422). At that moment the system computes and stores the public interest review — a weighted score over three components, with the components carried unrounded until the final weighted sum is rounded half-up to two decimal places.

The environmental component starts from a per-acre harm term: negative 10.0 points per impacted acre of `total_impact_acres` on the standard variant, or — for an after-the-fact application — negative 15.0 points per impacted acre plus a flat negative 10.0 deterrence adjustment, so identical application data always scores strictly lower on the after-the-fact variant. To the harm term the component adds 5.0 points for every entry in `minimization_steps` of the application's `ACCEPTED` analysis, adds a `secured_bonus` of 20.0 points when the application's mitigation plan stands in `CREDITS_SECURED`, `ACTIVE`, or `COMPLETED` (zero otherwise), subtracts 15.0 points for every agency comment of this application that is `ADVISORY` and still `FILED`, and adds 5.0 points for every `CONCURRENCE` comment of this application regardless of that comment's status.

The economic component measures the project's cost against a neutral point: take `estimated_cost_dollars`, subtract 250000.0 dollars, divide by 10000.0 dollars, and clamp the result so it never falls below negative 100.0 or above positive 100.0. The navigation component is negative 10.0 points when any impact line touches `OPEN_WATER` or `STREAM`, and positive 15.0 points when none does.

The `pir_score` is the weighted sum — 0.40 times the environmental component, 0.35 times the economic component, and 0.25 times the navigation component — rounded half-up to two decimal places. The `pir_outcome` is `FAVORABLE` when the score is at least 0.0 and `UNFAVORABLE` below that. Both are stored on the application at advance-to-decision time; on the general pathways, which never run this review, both stay null.

### 3.6. Compensatory Mitigation: Plans, Banks, and Credit Transactions

When `compensatory_mitigation_required` is true, the applicant must secure mitigation before any permit can issue. The applicant creates a mitigation plan naming the `application_id` and a `mechanism` of `BANK_CREDITS`, `IN_LIEU_FEE`, `PERMITTEE_RESPONSIBLE`, or `COMBINATION`, with three optional inputs: `financial_assurance_dollars` (defaulting to 0, never negative), `stewardship_entity_name`, and `long_term_stewardship_secured` (defaulting to false). A `stewardship_entity_name` is required for the `PERMITTEE_RESPONSIBLE` and `COMBINATION` mechanisms, its absence being `ERR_INVALID_REQUEST`. Each application carries at most one plan outside the terminal statuses — a second plan while one stands in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `CREDITS_SECURED`, or `ACTIVE` is rejected with `ERR_ACTIVE_PLAN_EXISTS` (HTTP 409). Creation sequencing follows §3.4: individual pathways need the analysis `ACCEPTED` first (`ERR_AA_NOT_ACCEPTED`), general pathways need the application in `DECISION_PENDING`.

At creation the system computes the provisional credit requirement. For each impact line of the application, keyed by resource type, the base ratio is 2.0 credits per acre for `EMERGENT_MARSH`, 3.0 for `FORESTED_WETLAND`, 1.5 for `OPEN_WATER`, and 1.0 for `STREAM`. The provisional requirement multiplies the line's `impact_acres` by its base ratio, then by a location multiplier and a lag multiplier both fixed at 1.0 at creation — no bank has been chosen and no lag has elapsed — and finally by the after-the-fact multiplier, 1.5 when `is_after_the_fact` is true and 1.0 otherwise; each per-type result is rounded half-up to two decimal places and stored in `required_credits_by_type`. Two more creation-time computations attach by mechanism. For `IN_LIEU_FEE` and `COMBINATION`, `ilf_fee_due_dollars` is the sum over resource types of each type's provisional credits multiplied by that type's per-credit rate — 40000 dollars for `EMERGENT_MARSH`, 55000 for `FORESTED_WETLAND`, 30000 for `OPEN_WATER`, and 25000 for `STREAM` — with each per-type line rounded half-up to cents first and the total taken as the exact sum of the rounded lines; for the other mechanisms it stays null. For `PERMITTEE_RESPONSIBLE` and `COMBINATION`, `assurance_required_dollars` is computed and stored; for the other mechanisms it is null. The plan opens in `DRAFT` with `final_credits_required_by_type` null, `ilf_fee_paid_dollars` at 0, and `secured_date` null.

A draft plan may be edited — `mechanism`, `financial_assurance_dollars`, `stewardship_entity_name`, and `long_term_stewardship_secured` — under the `expected_plan_version` guard of §2.7; an edit on a `DRAFT` plan leaves it in `DRAFT`, recomputes the computed fields, and bumps `version`. The applicant submits the plan (`DRAFT` to `SUBMITTED`), and a `Reviewer` renders a `verdict` with optional `revision_notes`: `APPROVE` moves it to `APPROVED`, while `REQUEST_REVISION` moves it to `REVISION_REQUESTED`, from which the applicant's edit returns it to `SUBMITTED` with the computed fields recomputed. Wrong-state submits and reviews surface `ERR_PLAN_INVALID_STATE` (HTTP 409).

Mitigation banks are the supply side. A `SystemAdmin` registers a bank with its `bank_name`, `sponsor_name`, the two-letter `state_code` it operates in, a non-empty `service_area_watersheds` array of eight-digit hydrologic unit codes, a `credit_capacity` map of approved capacity per resource type (resource types absent from the map have capacity zero; values are never negative), and a `base_price_per_credit` map of dollar prices per credit per resource type (strictly positive for any type with capacity). The bank's computed inventory maps start clean: `credits_reserved_by_type` and `credits_purchased_by_type` at zero, `available_credits_by_type` equal to capacity, and `revenue_dollars` at 0. A `DistrictEngineer` approves a `PENDING_APPROVAL` bank to `OPERATIONAL`, may suspend an `OPERATIONAL` bank to `SUSPENDED`, and may approve a `SUSPENDED` bank back to `OPERATIONAL`; an out-of-state-order approve or suspend is `ERR_BANK_NOT_OPERATIONAL`. Banks can be listed with optional `status` and `watershed_code` filters, the latter matching banks whose `service_area_watersheds` contains the given code.

An applicant reserves credits by creating a credit transaction naming the `bank_id`, the `plan_id`, a `resource_type`, and the `credits` to reserve (strictly positive). The resource type must be a key of the plan's `required_credits_by_type`. The plan must be `APPROVED` and the bank `OPERATIONAL` — violations surface at the state tier as `ERR_PLAN_INVALID_STATE` and `ERR_BANK_NOT_OPERATIONAL` respectively. Two business guards follow: the bank's `state_code` must equal the state code of the site on the plan's application, else `ERR_OUT_OF_SERVICE_AREA` (HTTP 422); and the bank's `available_credits_by_type` for the resource type must be at least the requested credits, with exact equality allowed, else `ERR_INSUFFICIENT_CREDIT_INVENTORY` (HTTP 422). A successful reservation opens in `RESERVED` — `price_per_credit_dollars` and `total_price_dollars` still null — and immediately holds inventory: the bank's `credits_reserved_by_type` rises and `available_credits_by_type` falls.

Purchasing a `RESERVED` transaction stamps its price. The price tier is read from the bank's depletion before this purchase: take the bank's `credits_purchased_by_type` for the resource type — only `PURCHASED` transactions count; reservations hold inventory but do not move the tier — divide by the type's `credit_capacity` (treated as fraction zero when capacity is zero), and apply a multiplier of 1.0 when that sold fraction is less than 0.5, 1.15 when it is at least 0.5 but less than 0.8, and 1.30 when it is at least 0.8. The `price_per_credit_dollars` is the type's `base_price_per_credit` multiplied by the tier multiplier, rounded half-up to two decimal places; the `total_price_dollars` is that unit price multiplied by the `credits`, again rounded half-up to two decimal places. The evaluation order is pinned: the tier comes from the pre-transaction fraction, and a purchase never moves its own tier — pricing from the post-transaction fraction is forbidden. The transaction moves `RESERVED` to `PURCHASED`, and the bank's purchased and available maps and `revenue_dollars` are recomputed.

Releasing a `RESERVED` transaction — at the applicant's request, or automatically when an application is withdrawn, denied, or suspended — moves it to `RELEASED` and returns the held credits to `available_credits_by_type`. Refunding happens only system-side, when an application is withdrawn or denied: each `PURCHASED` transaction moves to `REFUNDED`, restoring both inventory and revenue. Purchasing or releasing a transaction no longer `RESERVED` is `ERR_CREDIT_TXN_INVALID_STATE` (HTTP 409). Throughout, the bank's books obey a conservation invariant: for every bank and resource type, `credit_capacity` always equals `available_credits_by_type` plus `credits_reserved_by_type` plus `credits_purchased_by_type`, so a reserve-then-release pair and a purchase-then-refund pair each leave availability unchanged; `revenue_dollars` is always the sum of `total_price_dollars` over `PURCHASED` transactions minus the sum over `REFUNDED` ones. Transactions can be listed with optional `bank_id`, `plan_id`, `resource_type`, and `status` filters; plans with optional `application_id`, `mechanism`, and `status` filters.

Securing an `APPROVED` plan is the final financial gate, and it is where the provisional requirement becomes final. At secure-credits time the system recomputes each resource type's requirement with the true multipliers and stores it in `final_credits_required_by_type`: the multiplier application order is pinned — base ratio first, then location, then lag, then the after-the-fact multiplier — with the per-type result rounded half-up to two decimal places. The location multiplier is 1.0 when every `PURCHASED` credit transaction of the plan draws on a bank whose `service_area_watersheds` contains the site's `watershed_code`, and 1.25 otherwise — buying out-of-basin costs a quarter more mitigation; for a `PERMITTEE_RESPONSIBLE` plan the location multiplier is simply 1.0. The lag multiplier prices delay: take the whole days elapsed from the application's `submitted_date` to the current clock, and apply 1.0 when that lag is at most 365 days, 1.10 when it is between 366 and 730 days inclusive, and 1.20 once it exceeds 730 days. The after-the-fact multiplier remains 1.5 or 1.0 as at creation. Identical plan data therefore yields a strictly larger final requirement whenever the lag has passed one year or an out-of-basin bank was used. The in-lieu fee is the exception: for `IN_LIEU_FEE` the fee was fixed at creation from the provisional credits and is never recomputed.

What securing demands depends on the mechanism, and each failure carries its own error. For `BANK_CREDITS`, the sum of `PURCHASED` transaction credits must meet the final requirement for every resource type, else `ERR_CREDITS_NOT_SECURED` (HTTP 422); arriving at secure-credits with the `IN_LIEU_FEE` mechanism is rejected as a state error, `ERR_PLAN_INVALID_STATE`. For `PERMITTEE_RESPONSIBLE`, `financial_assurance_dollars` must be at least the recomputed `assurance_required_dollars` and `long_term_stewardship_secured` must be true, else `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE` (HTTP 422). For `COMBINATION`, both halves must hold at half weight: per resource type the `PURCHASED` credits must reach at least half the final requirement, that half rounded half-up to two decimal places; `financial_assurance_dollars` must reach at least half of `assurance_required_dollars`, likewise rounded; and `long_term_stewardship_secured` must be true — a credits shortfall is `ERR_CREDITS_NOT_SECURED`, an assurance or stewardship shortfall `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE`. For `IN_LIEU_FEE`, securing instead happens by paying the fee: the supplied `amount_dollars` must equal `ilf_fee_due_dollars` exactly, else `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), whereupon `ilf_fee_paid_dollars` records the amount paid. Either route moves the plan `APPROVED` to `CREDITS_SECURED` and stamps `secured_date` with the clock.
### 3.7. Decision, Issuance, and the Compensation Cascade

From `DECISION_PENDING`, the decision belongs to the `DistrictEngineer`, who supplies an `outcome` and an optional `decision_rationale`. Four gates stand in front of an issuance. First, segregation of duties: the deciding engineer's `X-User-ID` must differ from the application's `screening_reviewer_id`, else `ERR_SEGREGATION_OF_DUTIES`. Second, on the `INDIVIDUAL` and `ATF_INDIVIDUAL` pathways the stored `pir_outcome` must be `FAVORABLE`, else `ERR_PUBLIC_INTEREST_UNFAVORABLE` (HTTP 422). Third, for an after-the-fact application the linked enforcement case must stand with `resolution_track` `AFTER_THE_FACT_PERMIT` and its `atf_application_id` pointing back at this very application, else `ERR_CASE_INVALID_STATE`. Fourth, when `compensatory_mitigation_required` is true, one of the application's mitigation plans must stand in `CREDITS_SECURED`, else `ERR_MITIGATION_NOT_SECURED` (HTTP 422).

An `ISSUE` outcome moves the application to `ISSUED` and creates the `Permit`. The permit records the `application_id`; is stamped with a `permit_number` formed as `WP-` followed by a four-digit zero-padded sequential count of issued permits starting at 1 — the first permit is `WP-0001`, and the number is count-based, never derived from any identifier; takes `issue_date` from the logical clock; fixes `expiration_date` at the issue instant plus 1825 days; and opens in `ISSUED`. Its `special_conditions` are pinned by pathway and never vary: general-pathway permits carry exactly "SC-GP-01: Erosion and sediment controls must be maintained for the duration of the authorized work" and "SC-GP-02: Work must be completed within the general permit activity limits", while individual-pathway permits carry exactly "SC-IP-01: Five years of mitigation monitoring reports are required", "SC-IP-02: Long-term stewardship must be maintained by the designated stewardship entity", and "SC-IP-03: Compensatory mitigation must remain secured for the life of the project". Issuance also activates the mitigation: the application's `CREDITS_SECURED` plan transitions to `ACTIVE`, and when the application has such a plan, exactly five monitoring reports are generated for the new permit and plan — `period_index` running 1 through 5, each report's `due_date` set at the permit's `issue_date` plus 365 days times its period index, each opening in `DUE`. Finally, for an after-the-fact application, issuance closes the enforcement loop: the linked case moves `RESOLUTION_PENDING` to `CLOSED`, and `penalty_final_dollars` is fixed at the full `penalty_accrued_dollars` evaluated at this clock — the after-the-fact track carries no good-faith offset.

A `DENY` outcome moves the application to `DENIED` and unwinds the money. Every credit transaction of the application's plans still in `RESERVED` transitions to `RELEASED`, and every one in `PURCHASED` transitions to `REFUNDED`, restoring the banks' inventory and revenue; and every mitigation plan of the application not yet terminal — anything in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, or `CREDITS_SECURED` — transitions to `CANCELLED`. Withdrawal by the applicant runs this identical cascade, with the single §3.3 nuance for withdrawal from `SUSPENDED_PENDING_JD`. The permit status vocabulary is `ISSUED`, `ACTIVE`, `SUSPENDED`, `CLOSED`, and `EXPIRED`, with `CLOSED` and `EXPIRED` terminal; permits can be listed with optional `application_id` and `status` filters.

### 3.8. Monitoring, Permit Lifecycle, and Compliance Breach

The applicant commences work to move a permit `ISSUED` to `ACTIVE`; invoking that transition on a permit in any other state is `ERR_PERMIT_INVALID_STATE` (HTTP 409).

Monitoring then runs on the five-report schedule created at issuance. Submitting a report — allowed from `DUE`, from `OVERDUE`, and from `DEFICIENT`, always landing in `SUBMITTED` — supplies the `coverage_start`, the `coverage_end`, and the `findings_text`, and restamps `submitted_date`. The coverage interval must be internally sane, with `coverage_start` strictly before `coverage_end`, else `ERR_INVALID_REQUEST`; and it must dovetail perfectly with its siblings: the first report's `coverage_start` must equal the permit's `issue_date`, and each later report's `coverage_start` must equal the `coverage_end` most recently submitted — in `SUBMITTED` or `ACCEPTED` status — for the preceding period index. No gaps and no overlaps are tolerated between sibling reports; a break in that zero-gap chain is `ERR_COVERAGE_INTERVAL_CONFLICT` (HTTP 409). Submitting from a state other than those three is `ERR_REPORT_INVALID_STATE`.

A `Reviewer` reviews a `SUBMITTED` report by supplying an `outcome`. Marking it `DEFICIENT` requires `deficiency_notes` in the payload, else `ERR_INVALID_REQUEST`; the notes are copied onto the report as its `outcome` records `DEFICIENT`, and the applicant may correct and resubmit from there. Accepting records the `outcome` `ACCEPTED` — the report's terminal state — and when that acceptance lands on the fifth and final report of the plan, so that all five stand `ACCEPTED`, the linked mitigation plan transitions from `ACTIVE` to `COMPLETED`. Until its first review a report's `outcome` is null, and `deficiency_notes` stays null unless a deficiency has been recorded. Reports can be listed with optional `permit_id`, `plan_id`, and `status` filters, and the list is sorted by `period_index` ascending.

The clock drives the rest of the lifecycle, in the pinned order of §2.5. A report still `DUE` once the clock passes its `due_date` flips to `OVERDUE`. A report that stays `OVERDUE` more than 60 days past its `due_date` while its permit is `ACTIVE` is a compliance breach: the permit transitions `ACTIVE` to `SUSPENDED`, and the system auto-opens an enforcement case with `case_source` `MONITORING_BREACH`, pulling `site_id` and `responsible_applicant_id` from the permit's application, recording `unauthorized_fill_acres` as 0 — the one situation in which zero fill acres appear on a case — and `opened_by_officer_id` as `SYSTEM`, opening in `OPENED`. A `DistrictEngineer` reinstates a `SUSPENDED` permit to `ACTIVE` only once none of its reports remains `OVERDUE`, else `ERR_REPORTS_OVERDUE_EXIST` (HTTP 422); and closes an `ACTIVE` permit to `CLOSED` only when all five of its monitoring reports stand `ACCEPTED` and the mitigation plan has reached `COMPLETED`, else `ERR_MONITORING_INCOMPLETE` (HTTP 422). Whatever its state — `ISSUED` or `ACTIVE` — a permit whose `expiration_date` falls behind the clock transitions to `EXPIRED`, and its linked plan in `ACTIVE` transitions to `DEFAULTED`.

### 3.9. Enforcement and After-the-Fact Resolution

An `EnforcementOfficer` opens a case for unauthorized fill by naming the `site_id`, the `responsible_applicant_id`, the `unauthorized_fill_acres` (zero or more), and a `description`. The new case records `case_source` `MANUAL`, stamps `opened_by_officer_id` from the caller's `X-User-ID` and `opened_date` from the clock, and opens with `case_status` `OPENED` and `resolution_track` `NONE`; `confirmed_date`, `penalty_final_dollars`, `restoration_deadline`, and `atf_application_id` are all null, and `extension_used` is false. Cases can be listed with optional `site_id`, `responsible_applicant_id`, `atf_application_id`, and `case_status` filters.

Confirmation is a second officer's act: confirming the violation is rejected with `ERR_SEGREGATION_OF_DUTIES` when the caller's `X-User-ID` equals the case's `opened_by_officer_id`. Confirmation moves the case `OPENED` to `VIOLATION_CONFIRMED`, stamps `confirmed_date`, and starts the penalty clock. From that instant, `penalty_accrued_dollars` accrues at 250.0 dollars per unauthorized acre per day — the whole days elapsed from `confirmed_date` to the current logical clock, computed as the floor of the difference in seconds divided by 86400 — capped at 500000.0 dollars, so the accrual is the smaller of the running product and the cap. While a case is unconfirmed its accrual reads 0. The accrual is evaluated against the current clock whenever read, and is fixed — with rounding half-up to two decimal places only at fixation — into `penalty_final_dollars` when the case closes.

Setting the resolution moves a `VIOLATION_CONFIRMED` case to `RESOLUTION_PENDING` along one of two tracks named by the payload's `track`. On the `RESTORATION` track there is no further requirement, and the system sets `restoration_deadline` to the current clock plus 90 days. On the `AFTER_THE_FACT_PERMIT` track, the payload must carry an `atf_application_id` referencing an existing application — a dangling reference is `ERR_APPLICATION_NOT_FOUND` — and that application's `enforcement_case_id` must name this case, completing the two-way linkage, else `ERR_CASE_INVALID_STATE`; the reference is then stored. Either way `resolution_track` records the chosen track, and on the after-the-fact track the deadline stays null.

Closure splits by track. On the restoration track, an `EnforcementOfficer` verifies the restoration — an act defined only while the case is `RESOLUTION_PENDING` with `resolution_track` `RESTORATION`, else `ERR_CASE_INVALID_STATE` — and timely restoration earns the good-faith offset: the case closes and `penalty_final_dollars` is fixed at half of the accrued penalty, rounded half-up to two decimal places. On the after-the-fact track the case closes system-side, without any offset, at the moment the linked application is issued (§3.7). Should the clock pass a restoration deadline while the case still pends, the case transitions `RESOLUTION_PENDING` to `DEFAULTED`; a `DistrictEngineer` may then grant a one-time extension, returning the case to `RESOLUTION_PENDING` with `restoration_deadline` reset to the current clock plus 60 days and `extension_used` set true — a second extension attempt is rejected with `ERR_EXTENSION_ALREADY_USED` (HTTP 409). Every other out-of-state case operation is `ERR_CASE_INVALID_STATE`. The case vocabulary is `OPENED`, `VIOLATION_CONFIRMED`, `RESOLUTION_PENDING`, `DEFAULTED`, and `CLOSED`, with `CLOSED` terminal; recall from §3.1 that every case no longer `OPENED` raises its responsible applicant's `prior_violation_count`.
## 4. Endpoint Definitions

All endpoints are mounted under `/wetland-permits` except the platform clock capability. Creating a new resource returns HTTP 201; every other successful operation — reads, edits, and state-transition actions — returns HTTP 200. Request payloads, preconditions, and side effects for each endpoint are specified in §2 and §3; this table is a locator, not a contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /wetland-permits/applicants | Register an applicant | SystemAdmin |
| GET | /wetland-permits/applicants/{id} | Get one applicant (Applicant role may only read its own id) | SystemAdmin, Applicant |
| POST | /wetland-permits/sites | Register a waters site for an applicant | SystemAdmin |
| GET | /wetland-permits/sites | List sites, optionally filtered by applicant_id | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/sites/{id} | Get one site | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/jurisdictional-determinations | Create a jurisdictional determination in DRAFT | Reviewer |
| GET | /wetland-permits/jurisdictional-determinations | List jurisdictional determinations, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/jurisdictional-determinations/{id} | Get one jurisdictional determination | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/jurisdictional-determinations/{id}/issue | Issue a DRAFT determination (sets issued_date/expiration_date; enforces one live determination per site) | DistrictEngineer |
| POST | /wetland-permits/appeals | File an appeal of an ISSUED APPROVED determination within 60 days of issuance; appellant is X-User-ID and must own the site's applicant | Applicant |
| GET | /wetland-permits/appeals | List appeals, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/appeals/{id} | Get one appeal | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/appeals/{id}/decide | Decide a FILED appeal; outcome SUSTAINED reverses the determination and fires the suspension cascade | DistrictEngineer |
| POST | /wetland-permits/applications | Create a permit application in DRAFT; applicant_id is set from X-User-ID | Applicant |
| GET | /wetland-permits/applications | List applications, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/applications/{id} | Get one application | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| PATCH | /wetland-permits/applications/{id} | Edit a DRAFT or RETURNED_TO_APPLICANT application; OCC-guarded; status unchanged | Applicant |
| POST | /wetland-permits/applications/{id}/submit | Submit from DRAFT or RETURNED_TO_APPLICANT; from SUSPENDED_PENDING_JD requires new_jd_id | Applicant |
| POST | /wetland-permits/applications/{id}/screening | Reviewer screening action: BEGIN, RETURN, or APPROVE (pathway-dependent target state) | Reviewer |
| POST | /wetland-permits/applications/{id}/publish-notice | Publish the public notice (individual pathways; requires the analysis ACCEPTED); moves the application to PUBLIC_NOTICE_OPEN | Reviewer |
| POST | /wetland-permits/applications/{id}/advance-to-decision | Close review and compute the public interest review score; requires the comment period closed and no unresolved substantive objections | Reviewer |
| POST | /wetland-permits/applications/{id}/render-decision | District engineer decision: ISSUE creates the permit and activates the secured plan; DENY releases/refunds plan credits and cancels the plan | DistrictEngineer |
| POST | /wetland-permits/applications/{id}/withdraw | Applicant withdraws from any non-terminal pre-decision state (including SUSPENDED_PENDING_JD) | Applicant |
| POST | /wetland-permits/alternatives-analyses | Submit an alternatives analysis for an application in ALTERNATIVES_REVIEW; one per application | Applicant |
| GET | /wetland-permits/alternatives-analyses | List alternatives analyses, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/alternatives-analyses/{id} | Get one alternatives analysis | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| PATCH | /wetland-permits/alternatives-analyses/{id} | Revise a REVISION_REQUESTED analysis; returns it to SUBMITTED and increments revision_count | Applicant |
| POST | /wetland-permits/alternatives-analyses/{id}/review | Reviewer verdict on a SUBMITTED analysis: ACCEPT (LEDPA gate), REQUEST_REVISION, or REJECT | Reviewer |
| POST | /wetland-permits/agency-comments | File an agency comment while the application's notice is PUBLISHED | AgencyReviewer |
| GET | /wetland-permits/agency-comments | List agency comments, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/agency-comments/{id} | Get one agency comment | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/agency-comments/{id}/resolve | Resolve a FILED comment with a resolution narrative | Reviewer |
| POST | /wetland-permits/mitigation-plans | Create a mitigation plan in DRAFT; individual pathways require the analysis ACCEPTED first; general pathways require the application in DECISION_PENDING | Applicant |
| GET | /wetland-permits/mitigation-plans | List mitigation plans, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/mitigation-plans/{id} | Get one mitigation plan | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| PATCH | /wetland-permits/mitigation-plans/{id} | Edit a DRAFT plan (stays DRAFT) or revise a REVISION_REQUESTED plan (returns to SUBMITTED); OCC-guarded | Applicant |
| POST | /wetland-permits/mitigation-plans/{id}/submit | Submit a DRAFT plan for review | Applicant |
| POST | /wetland-permits/mitigation-plans/{id}/review | Reviewer verdict on a SUBMITTED plan: APPROVE or REQUEST_REVISION | Reviewer |
| POST | /wetland-permits/mitigation-plans/{id}/secure-credits | Secure an APPROVED BANK_CREDITS, PERMITTEE_RESPONSIBLE, or COMBINATION plan; recomputes the final credit requirement | Applicant |
| POST | /wetland-permits/mitigation-plans/{id}/pay-in-lieu-fee | Pay the in-lieu fee for an APPROVED IN_LIEU_FEE plan; amount must equal ilf_fee_due_dollars exactly | Applicant |
| POST | /wetland-permits/mitigation-banks | Register a mitigation bank in PENDING_APPROVAL | SystemAdmin |
| GET | /wetland-permits/mitigation-banks | List banks; the watershed_code filter matches banks whose service_area_watersheds contains the code | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/mitigation-banks/{id} | Get one bank | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/mitigation-banks/{id}/approve | Approve a PENDING_APPROVAL bank or reinstate a SUSPENDED bank to OPERATIONAL | DistrictEngineer |
| POST | /wetland-permits/mitigation-banks/{id}/suspend | Suspend an OPERATIONAL bank (new reservations rejected) | DistrictEngineer |
| POST | /wetland-permits/credit-transactions | Reserve bank credits for an APPROVED plan; holds inventory immediately | Applicant |
| GET | /wetland-permits/credit-transactions | List credit transactions, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/credit-transactions/{id} | Get one credit transaction | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/credit-transactions/{id}/purchase | Purchase a RESERVED transaction; stamps the tier-adjusted price from the pre-transaction depletion fraction | Applicant |
| POST | /wetland-permits/credit-transactions/{id}/release | Release a RESERVED transaction back to the bank's available inventory | Applicant |
| GET | /wetland-permits/permits | List permits, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/permits/{id} | Get one permit | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/permits/{id}/commence-work | Mark an ISSUED permit as commenced | Applicant |
| POST | /wetland-permits/permits/{id}/reinstate | Reinstate a SUSPENDED permit once no OVERDUE reports remain | DistrictEngineer |
| POST | /wetland-permits/permits/{id}/close | Close an ACTIVE permit after all monitoring is accepted and the plan is COMPLETED | DistrictEngineer |
| GET | /wetland-permits/monitoring-reports | List monitoring reports sorted by period_index ascending, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/monitoring-reports/{id} | Get one monitoring report | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/monitoring-reports/{id}/submit | Submit a DUE, OVERDUE, or DEFICIENT report with its coverage interval (zero-gap contiguity enforced) | Applicant |
| POST | /wetland-permits/monitoring-reports/{id}/review | Reviewer accepts or marks a SUBMITTED report deficient (deficiency_notes required for DEFICIENT); the fifth ACCEPTED report completes the plan | Reviewer |
| POST | /wetland-permits/enforcement-cases | Open an enforcement case for unauthorized fill; the opener is recorded for the segregation-of-duties gate | EnforcementOfficer |
| GET | /wetland-permits/enforcement-cases | List enforcement cases, optionally filtered | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| GET | /wetland-permits/enforcement-cases/{id} | Get one enforcement case | SystemAdmin, Applicant, Reviewer, DistrictEngineer, AgencyReviewer, EnforcementOfficer |
| POST | /wetland-permits/enforcement-cases/{id}/confirm-violation | Confirm the violation; must be a different officer than the opener; starts penalty accrual | EnforcementOfficer |
| POST | /wetland-permits/enforcement-cases/{id}/set-resolution | Set the resolution track: RESTORATION (deadline 90 days out) or AFTER_THE_FACT_PERMIT (requires a linked application) | EnforcementOfficer |
| POST | /wetland-permits/enforcement-cases/{id}/verify-restoration | Verify restoration on a RESTORATION-track case in RESOLUTION_PENDING; closes with the good-faith 50 percent penalty offset | EnforcementOfficer |
| POST | /wetland-permits/enforcement-cases/{id}/grant-extension | Grant a one-time 60-day extension on a DEFAULTED case | DistrictEngineer |
| POST | /_clock/set_current_utc | Advance the logical clock (strictly monotonic); fires every time-based transition in the pinned evaluation order | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_APPLICANT_NOT_FOUND | 404 |
| ERR_SITE_NOT_FOUND | 404 |
| ERR_JD_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_AA_NOT_FOUND | 404 |
| ERR_COMMENT_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_BANK_NOT_FOUND | 404 |
| ERR_CREDIT_TXN_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_JD_INVALID_STATE | 409 |
| ERR_APPEAL_INVALID_STATE | 409 |
| ERR_APPLICATION_INVALID_STATE | 409 |
| ERR_AA_INVALID_STATE | 409 |
| ERR_PLAN_INVALID_STATE | 409 |
| ERR_CREDIT_TXN_INVALID_STATE | 409 |
| ERR_PERMIT_INVALID_STATE | 409 |
| ERR_REPORT_INVALID_STATE | 409 |
| ERR_CASE_INVALID_STATE | 409 |
| ERR_BANK_NOT_OPERATIONAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CLOCK_REGRESSION | 422 |
| ERR_JD_NOT_APPEALABLE | 422 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_JD_EXPIRED | 409 |
| ERR_COMMENT_PERIOD_CLOSED | 422 |
| ERR_NOTICE_PERIOD_STILL_OPEN | 422 |
| ERR_GENERAL_PERMIT_INELIGIBLE | 422 |
| ERR_LEDPA_NOT_DEMONSTRATED | 422 |
| ERR_PUBLIC_INTEREST_UNFAVORABLE | 422 |
| ERR_JD_NOT_JURISDICTIONAL | 422 |
| ERR_AA_NOT_ACCEPTED | 422 |
| ERR_UNRESOLVED_AGENCY_OBJECTIONS | 422 |
| ERR_ACTIVE_JD_EXISTS | 409 |
| ERR_APPEAL_ALREADY_FILED | 409 |
| ERR_AA_ALREADY_EXISTS | 409 |
| ERR_NOTICE_ALREADY_PUBLISHED | 409 |
| ERR_ACTIVE_PLAN_EXISTS | 409 |
| ERR_OUT_OF_SERVICE_AREA | 422 |
| ERR_COVERAGE_INTERVAL_CONFLICT | 409 |
| ERR_EXTENSION_ALREADY_USED | 409 |
| ERR_INSUFFICIENT_CREDIT_INVENTORY | 422 |
| ERR_CREDITS_NOT_SECURED | 422 |
| ERR_INSUFFICIENT_FINANCIAL_ASSURANCE | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_MITIGATION_NOT_SECURED | 422 |
| ERR_REPORTS_OVERDUE_EXIST | 422 |
| ERR_MONITORING_INCOMPLETE | 422 |
