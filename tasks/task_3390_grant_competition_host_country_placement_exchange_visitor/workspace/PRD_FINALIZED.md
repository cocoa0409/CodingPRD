# Grant Exchange Compliance API — Product Requirements Document

## 1. Introduction

Every year the national exchange program runs an open grant competition in the Fulbright mold: applicants propose study, research, or teaching projects in host countries; campus committees shepherd enrolled students through a first review while independent candidates go straight to a national screening committee; host-country commissions and embassies make the final selection and negotiate placements with receiving institutions. The award itself is only the midpoint of the story. Grant terms covering stipend, travel, health benefits, and program duration are fixed per country, with separate cost-of-living bands for receiving institutions; the exchange visitor visa sponsorship carries program obligations that include the two-year home residency requirement; and the grantee owes pre-departure orientation, interim and final reporting, in-country emergency cooperation, and — long afterward — alumni engagement that decides eligibility for follow-on programs. This document specifies the API that administers that entire arc, from the moment a competition cycle is drafted to the moment an alumnus is certified eligible to apply again. All program resources are mounted under the `/exchange` path prefix.

Three design pillars hold the program's integrity together and recur throughout this specification. First, segregation of duties: six authenticated roles plus an anonymous registration lane divide the work so that no actor both scores and selects, and no applicant ever touches another's file. Second, a per-country quota ledger: every host country program owns a finite slot budget, and the API maintains strict slot conservation through selections, declines, placement failures, and the automatic promotion of alternates. Third, a server-side logical clock: every deadline, due date, and temporal gate in the system is evaluated against this clock and never against wall-clock time, which keeps the program's temporal semantics deterministic. Where figures must be quoted before all facts are known, the API computes dual variants — provisional versus final award terms, provisional versus certified engagement indices — and states explicitly which variant governs which decision.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, the response envelope, pagination, the logical clock, resource identity conventions, numeric precision, validation ordering, optimistic concurrency, and cross-entity consistency.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The declared roles are exactly seven: `PlatformAdmin`, `ProgramOfficer`, `HostCommission`, `NationalReviewer`, `CampusReviewer`, `Applicant`, and `Anonymous`. A request with missing headers, or with a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not admitted by the target endpoint — or whose role does not match the action family of the requested transition — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles divide the work as follows. A `PlatformAdmin` is the exchange program administrator: it configures competition cycles and country programs, drives every cycle phase transition, and alone may advance the logical clock. A `ProgramOfficer` is the grant administration officer: it confirms grant terms, issues visa sponsorships, activates, completes, and terminates grants, decides residency waivers, reviews reports, expires placement offers, and manages emergency incidents. A `HostCommission` operator is the host country commission or embassy reviewer: it selects grantees, parks alternates, and opens placement negotiation rounds. A `NationalReviewer` sits on the national screening committee and may score and recommend only while an application is in national screening. A `CampusReviewer` sits on a campus committee for enrolled students and may score and endorse only while an application is in campus review; the two reviewer families are deliberately segregated from one another. An `Applicant` is a registered applicant acting on their own resources. The `Anonymous` role exists solely for the applicant registration lane.

Role identity is resolved in two different ways. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant record; ownership checks on any resource that references an applicant compare that chain's terminal applicant id to `X-User-ID` — `applicant_id` on an application directly, and the applicant reached through the foreign-key chain for grants, placement rounds, reports, visa sponsorships, and residency ledgers. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `ProgramOfficer`, `HostCommission`, `NationalReviewer`, `CampusReviewer`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewer_id` on a posted review score) but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when not provided, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. Two listings accept additional filters: the application listing accepts `cycle_id`, `country_program_id`, `applicant_id`, and `status`, and the report listing accepts `report_type`.

### 2.4. The Logical Clock

The server maintains a logical clock that governs every temporal decision in the system: deadline checks, due-date computation, lateness flags, offer expiry, and the timestamps stamped onto submissions, responses, incidents, and resolutions. Before any administrator call is made, the logical clock stands at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin` advances it through an admin-only test-driving capability that sets the current instant to a supplied `to_iso8601` value; the call returns 200 OK and mutates no entity. Wherever this document says "the logical clock" — at or before a deadline, strictly past an expiry, on or after a start date — the comparison is evaluated against this clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is the same format and refreshes on every modification. The `version` field is an integer that increments by exactly one on every mutation of the resource — including mutations the server applies as cascading side effects of an operation on a related resource, such as the version bump an application receives when a placement round is opened against it or when a committee decision lands. One entity is exempt from this convention: a posted review score is immutable and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Scores, and Precision

All monetary amounts are integer cents; the API never accepts, stores, or returns fractional cents, and no floating-point arithmetic ever touches money. Derived award figures that require division are rounded half up to whole cents at exactly the computation steps the business rules in §3 pin down — rounding at a different step produces a different cent value and is a defect. Screening score averages and weighted scores — the values computed from posted scores — are decimal numbers carried to exactly 2 decimal places with round-half-up rounding; the posted screening scores themselves are integers, as §3.3's input contract defines. Grant durations are measured in whole calendar months with days ignored; residency accrual is measured in whole days; alumni engagement indices are integer points clamped to the range 0 through 100. Instants compare as ISO 8601 timestamps, and every deadline this document names "inclusive" admits a submission or response landing at the exact deadline instant.

### 2.7. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order so the error a caller receives is deterministic:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles — otherwise `ERR_UNAUTHENTICATED` (401). This applies to every endpoint.
2. **Authorization.** The role is admitted by the endpoint and matches the action family of the requested transition: SUBMIT, WITHDRAW, and DECLINE on applications and ACCEPT and DECLINE on placement offers are `Applicant` actions; DECIDE belongs to the reviewer family (`CampusReviewer`, `NationalReviewer`, `HostCommission`); EXPIRE on an offer, ACCEPT and REQUEST_REVISION on a report, and APPROVE_WAIVER and DENY_WAIVER on a residency ledger are `ProgramOfficer` actions; RESUBMIT on a report and REQUEST_WAIVER on a ledger are `Applicant` actions — violations are `ERR_UNAUTHORIZED` (403). Score posting is additionally stage-bound at this priority: a `CampusReviewer` may post only while the application is in CAMPUS_REVIEW and a `NationalReviewer` only while it is in NATIONAL_SCREENING, and a violation is likewise `ERR_UNAUTHORIZED`. For DECIDE transitions the stage-specific reviewer binding is deliberately not enforced here; it is enforced together with the state machine at priority 6, so a DECIDE from a reviewer whose stage does not match the application's current state surfaces as an invalid transition rather than an authorization failure.
3. **Path existence.** Each identifier in the path is resolved in left-to-right order: a missing cycle yields `ERR_CYCLE_NOT_FOUND`, country program `ERR_COUNTRY_PROGRAM_NOT_FOUND`, applicant `ERR_APPLICANT_NOT_FOUND`, application `ERR_APPLICATION_NOT_FOUND`, placement round `ERR_ROUND_NOT_FOUND`, grant `ERR_GRANT_NOT_FOUND`, visa sponsorship `ERR_VISA_NOT_FOUND`, residency ledger `ERR_LEDGER_NOT_FOUND`, report `ERR_REPORT_NOT_FOUND`, and incident `ERR_INCIDENT_NOT_FOUND` — all 404, and the first missing identifier wins.
4. **Optimistic concurrency.** Where an endpoint requires `expected_application_version`, the supplied value must equal the application's current `version` — otherwise `ERR_STALE_VERSION` (412); see §2.8.
5. **Applicant ownership.** For `Applicant`-role calls on application, placement-round, grant, report, and residency-ledger resources, `X-User-ID` must equal the owning applicant's id — otherwise `ERR_NOT_RESOURCE_OWNER` (403).
6. **State legality.** The target entity must be in a state from which the requested transition exists — otherwise `ERR_INVALID_STATE` (409); an `action` or `outcome` the endpoint does not know is `ERR_VALIDATION` (400) instead. Two state guards carry their own codes at this priority: a placement round must be OFFERED to be accepted, declined, or expired (`ERR_ROUND_NOT_OFFERED`, 409), and a residency ledger must be ACCRUING to record stays or to request a waiver (`ERR_RESIDENCY_NOT_ACCRUING`, 409).
7. **Orientation gate.** Grant activation requires completed pre-departure orientation — otherwise `ERR_ORIENTATION_INCOMPLETE` (409).
8. **Temporal checks.** The logical-clock comparisons scattered through §3 — the submission deadline (`ERR_DEADLINE_PASSED`), the confirmation start date (`ERR_START_DATE_IN_PAST`), the activation start (`ERR_START_DATE_NOT_REACHED`), the completion end (`ERR_END_DATE_NOT_REACHED`), offer expiry (`ERR_OFFER_EXPIRED`), the final-report window (`ERR_REPORT_WINDOW_INVALID`), and the stay accrual start (`ERR_STAY_BEFORE_ACCRUAL_START`) — all 409.
9. **Business constraints.** Structural validation (`ERR_VALIDATION`, 400): required fields present, enum members valid, scores within 0–100, `end_date` after `start_date`, a stay's end not before its start, orientation not in the future, no unknown request fields, and `country_program_id` belonging to the addressed cycle. Stage-appropriate DECIDE outcomes (`ERR_INVALID_OUTCOME`, 400). Duration bounds (`ERR_DURATION_OUT_OF_RANGE`, 422). Uniqueness and cardinality rules (`ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_SCORE`, `ERR_DUPLICATE_VISA`, `ERR_DUPLICATE_REPORT`, `ERR_ACTIVE_ROUND_EXISTS`, `ERR_ACTIVE_INCIDENT_EXISTS` — all 409). Review gates (`ERR_SCORE_QUORUM_NOT_MET`, `ERR_SCORE_BELOW_THRESHOLD`, `ERR_LANGUAGE_CRITERION_UNMET` — 409). Interval rules (`ERR_STAY_OVERLAP`, `ERR_GRANT_PERIOD_OVERLAP` — 409). Lifecycle prerequisites (`ERR_FINAL_REPORT_MISSING`, `ERR_FOLLOW_ON_INELIGIBLE`, `ERR_NO_COUNTRY_PROGRAMS`, `ERR_APPLICATIONS_PENDING` — 409).
10. **Referential phase checks.** The cycle or grant is in the phase the operation requires: `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_PHASE_FORBIDS`, `ERR_GRANT_NOT_CONFIRMED`, `ERR_PLACEMENT_NOT_SECURED`, `ERR_GRANT_NOT_ACTIVE` — all 409.
11. **Fiscal gate.** Host selection requires an open slot — otherwise `ERR_COUNTRY_QUOTA_EXHAUSTED` (409).

The ordering is observable behavior: an expired offer acted on through a nonexistent round 404s before any temporal check runs; a well-formed request from the wrong role 403s before state is examined; a stale `expected_application_version` is detected (412) before ownership is examined; and the quota gate fires only after every other check has passed.

### 2.8. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control on the application's `version`, and both name the same field. The applicant's edit of a DRAFT application's fields, and the host commission's opening of a placement negotiation round, each require `expected_application_version` in the request body, carrying the `version` of the application the client last observed. If the application's current `version` has advanced past that value — through any mutation, including cascaded ones such as the version bumps applied by submission, committee decisions, or an earlier round's creation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a state it has not observed. The field is non-optional on both operations. No other endpoint accepts a version field, and writes elsewhere proceed without an OCC check. For the round-opening operation this guard is what makes the single-open-round rule safe to reason about: a stale writer's view of the negotiation position has already been superseded by whatever newer round or state the version bump records.

### 2.9. Nested Resource Retrieval

Requests that address a resource nested beneath another are validated identifier by identifier, left to right along the path. The first identifier that does not resolve to an existing resource determines the 404 error, using that resource type's specific code from §2.7 priority 3 — a request aimed at a country program beneath a nonexistent cycle fails with `ERR_CYCLE_NOT_FOUND` before the program identifier is even consulted, and a placement-round operation under a nonexistent application fails with `ERR_APPLICATION_NOT_FOUND` before the round is examined. Existence precedes every other domain check, so cross-references are never evaluated against containers that do not exist.

### 2.10. Cross-Entity Consistency and Cascades

Single operations routinely mutate several entities as one atomic unit: selecting an application consumes a country slot and creates a provisional grant; a declined or failed placement releases the slot and may promote an alternate; activating a grant moves its visa sponsorship; completing or terminating a grant cascades into the sponsorship, the residency ledger, and a freshly created alumni profile. Every entity mutated by such a cascade — not only the one named in the request — has its `updated_at` refreshed and its `version` incremented. Two conservation invariants anchor the design. Slot conservation: for every country program, `slot_quota` always equals `slots_remaining` plus the number of that program's applications currently in slot-consuming states, so selecting and later declining the same application leaves `slots_remaining` unchanged. Award conservation: at early termination, the earned portion, the repayment portion, and the reconciliation adjustment always sum exactly to the grant's final total award.

## 3. Business Logic & Workflows

### 3.1. Competition Cycles and Host Country Program Offerings

A `PlatformAdmin` opens a season by creating a competition cycle with an `academic_year` label (for example, "2027-2028") and an inclusive `application_deadline`; the cycle's `status` is born DRAFT. While the cycle is DRAFT, the administrator registers host country program offerings beneath it: each carries the `cycle_id` of its owning cycle, a `country_code` (an ISO 3166-1 alpha-2 host country code), a `slot_quota` capping the number of grants awardable to that country in that cycle, the duration bounds `min_duration_months` and `max_duration_months` in whole calendar months, the two cost-of-living stipend figures `monthly_stipend_standard_cents` and `monthly_stipend_high_cents`, the per-dependent `dependent_allowance_monthly_cents`, the one-time `travel_allowance_cents`, the monthly `health_benefit_monthly_cents` premium, and a `language_requirement` of `NONE`, `BASIC`, or `PROFICIENT`. At creation the program's `slots_remaining` equals its `slot_quota`. While the cycle remains DRAFT the administrator may amend any of the quota, the duration bounds, the stipend and allowance figures, or the language requirement through the program edit operation; the edit recomputes `slots_remaining` and increments the program's `version` by one. Once the cycle has left DRAFT such edits are rejected with `ERR_CYCLE_PHASE_FORBIDS`.

The cycle itself walks a one-way corridor of phases, each advance driven by a `PlatformAdmin` supplying an `action` to the cycle transition capability. From DRAFT, `OPEN` opens the competition — but only if at least one country program exists for the cycle, otherwise `ERR_NO_COUNTRY_PROGRAMS`. From OPEN, `CLOSE` stops new submissions. From CLOSED, `BEGIN_SCREENING` enters SCREENING. From SCREENING, `FINALIZE_AWARDS` is allowed only when no application of the cycle remains in CAMPUS_REVIEW, NATIONAL_SCREENING, or HOST_REVIEW (`ERR_APPLICATIONS_PENDING`), and it sweeps every lingering DRAFT application of the cycle to WITHDRAWN and every ALTERNATE application to NOT_SELECTED. From AWARDS_FINALIZED, `COMPLETE` marks the cycle COMPLETED, its terminal phase.

### 3.2. Applicant Registration and Application Submission

Anyone may register — the registration lane is the system's only anonymous operation — by supplying `full_name`, `email`, `applicant_type` (either `ENROLLED_STUDENT` or `INDEPENDENT`), and `citizenship_country_code` (an ISO 3166-1 alpha-2 home country code). The `home_institution_name` is required exactly when the applicant type is ENROLLED_STUDENT and omitted otherwise (`ERR_VALIDATION`). Email addresses are unique across applicants: a duplicate registration is rejected with `ERR_DUPLICATE_EMAIL`. From then on the caller acts with the `Applicant` role, `X-User-ID` set to the new record's `id`.

While a cycle is OPEN, an applicant drafts an application naming `applicant_id` — which must be the caller's own applicant id under the ownership rule of §2.1 — plus `cycle_id`, `country_program_id`, a `project_title`, a `project_summary`, and `proposed_duration_months`; optionally the draft records `dependents_count` (defaulting to 0, and never more than two dependents are counted in any money computation) and `is_follow_on` (defaulting to false). Creation already enforces the fundamentals: the addressed country program must belong to the addressed cycle (`ERR_VALIDATION`), the cycle must be OPEN (`ERR_CYCLE_NOT_OPEN`), and the proposed duration must sit within the program's duration bounds, inclusive of both ends (`ERR_DURATION_OUT_OF_RANGE`, 422). A follow-on application — `is_follow_on` set to true — is only accepted when the applicant's most recent alumni profile by `created_at` reports `follow_on_eligible` as ELIGIBLE (`ERR_FOLLOW_ON_INELIGIBLE`). The draft is born in DRAFT status.

While the application is DRAFT the applicant may revise `project_title`, `project_summary`, `proposed_duration_months`, and `dependents_count` through the optimistic-concurrency-guarded edit described in §2.8, which increments the application's `version` by one on success.

Submission is where the pipeline forks on the applicant type. When an ENROLLED_STUDENT submits, the application moves DRAFT → CAMPUS_REVIEW; when an INDEPENDENT submits, it moves DRAFT → NATIONAL_SCREENING. Every other precondition is identical across the fork: the cycle must be OPEN (`ERR_CYCLE_NOT_OPEN`); the logical clock must be at or before the cycle's `application_deadline`, the deadline being inclusive (`ERR_DEADLINE_PASSED`); the proposed duration must be within the program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the applicant must not already hold another application in the same cycle in any of CAMPUS_REVIEW, NATIONAL_SCREENING, HOST_REVIEW, SELECTED, ALTERNATE, PLACEMENT, GRANT_PENDING, or AWARDED (`ERR_DUPLICATE_APPLICATION`); and a follow-on submission re-verifies that the latest alumni profile's `follow_on_eligible` is ELIGIBLE (`ERR_FOLLOW_ON_INELIGIBLE`). A successful submission stamps `submitted_at` with the logical clock. An applicant may withdraw from DRAFT, CAMPUS_REVIEW, NATIONAL_SCREENING, HOST_REVIEW, or ALTERNATE at any time, landing in the terminal WITHDRAWN state with no further preconditions. Applications may be listed filtered by `cycle_id`, `country_program_id`, `applicant_id`, or `status`; an `Applicant`-role listing or read is confined to the caller's own records.

### 3.3. Campus and National Review: Scores, Quorums, and Thresholds

Committee members evaluate an application by posting review scores carrying `feasibility_score`, `country_fit_score`, and `language_score` — each an integer from 0 to 100, with anything outside that range rejected as `ERR_VALIDATION`; a score value that is not an integer at all — a number with a fractional part such as 71.5, a boolean, or any non-numeric value — is likewise rejected as `ERR_VALIDATION`, while an integral-valued JSON number such as 71.0 is accepted and stored as its integer value — plus an optional free-form `comment`. Each posted score records the `application_id` it belongs to, a `stage` derived from the application's status at posting time (CAMPUS while the application is in CAMPUS_REVIEW, NATIONAL while it is in NATIONAL_SCREENING), and the posting `reviewer_id` taken from the caller's `X-User-ID`. Scores are immutable once posted. A reviewer may score a given application at a given stage only once: a second posting for the same application, stage, and reviewer is rejected with `ERR_DUPLICATE_SCORE`. Stage binding is strict — a `CampusReviewer` may post only during CAMPUS_REVIEW and a `NationalReviewer` only during NATIONAL_SCREENING, with violations rejected as `ERR_UNAUTHORIZED`.

A campus endorsement — a CampusReviewer's DECIDE with `outcome` ENDORSE — requires the cycle to be in OPEN, CLOSED, or SCREENING (`ERR_CYCLE_PHASE_FORBIDS`) and at least two CAMPUS-stage scores on the application, the campus quorum (`ERR_SCORE_QUORUM_NOT_MET`); it moves the application CAMPUS_REVIEW → NATIONAL_SCREENING. A campus DECIDE with `outcome` REJECT moves the application CAMPUS_REVIEW → NOT_SELECTED under the cycle-phase gate alone. A DECIDE carries an optional `rationale`.

National recommendation — a NationalReviewer's DECIDE with `outcome` RECOMMEND — is gated more heavily. The same cycle-phase rule applies (OPEN, CLOSED, or SCREENING; `ERR_CYCLE_PHASE_FORBIDS`), and at least two NATIONAL-stage scores must be present, the national quorum (`ERR_SCORE_QUORUM_NOT_MET`). The moment the quorum-reaching national score is posted, the system computes and stores the application's `national_weighted_score`: first the mean of the `feasibility_score` values across all of the application's NATIONAL-stage scores, rounded half up to two decimal places; then, independently, the means of the `country_fit_score` and `language_score` values on the same rounding; then the weighted sum of 0.40 times the feasibility average plus 0.35 times the country-fit average plus 0.25 times the language average, rounded half up once more to two decimal places. RECOMMEND then requires the stored weighted score to be at least 70.00, inclusive, and the feasibility average to be at least 50, inclusive (`ERR_SCORE_BELOW_THRESHOLD`). On top of that stands the country language gate keyed on the program's `language_requirement`: PROFICIENT demands a language average of at least 80, BASIC demands at least 60, and NONE imposes no language gate at all (`ERR_LANGUAGE_CRITERION_UNMET`). A successful recommendation moves the application NATIONAL_SCREENING → HOST_REVIEW and assigns its `recommend_seq`: one more than the current maximum recommendation order among applications of the same country program, starting at 1 for the first recommended application — a per-program, strictly increasing sequence that never ties. A national DECIDE with `outcome` REJECT moves the application NATIONAL_SCREENING → NOT_SELECTED under the phase gate alone.

Two outcome disciplines apply to every DECIDE. A DECIDE issued by a reviewer whose stage does not match the application's current state — say a `NationalReviewer` deciding while the application sits in CAMPUS_REVIEW — is an invalid transition and is rejected with `ERR_INVALID_STATE`, not an authorization error. And the `outcome` must belong to the current stage's vocabulary — ENDORSE or REJECT in CAMPUS_REVIEW, RECOMMEND or REJECT in NATIONAL_SCREENING, and SELECT, ALTERNATE, or REJECT in HOST_REVIEW — otherwise the request is rejected with `ERR_INVALID_OUTCOME` (400).

### 3.4. Host Country Selection and Slot Accounting

Once an application reaches HOST_REVIEW, the `HostCommission` decides its fate, but only while the cycle is CLOSED or SCREENING — host decisions during OPEN or any later phase are rejected with `ERR_CYCLE_PHASE_FORBIDS`. A DECIDE with `outcome` SELECT consumes one of the country program's quota slots: it requires `slots_remaining` to be at least 1 (`ERR_COUNTRY_QUOTA_EXHAUSTED`, the fiscal gate of §2.7), moves the application HOST_REVIEW → SELECTED, and in the same atomic step creates a Grant for the application — bound to it via `application_id` — in PROVISIONAL status with the provisional award terms of §3.6. A DECIDE with `outcome` ALTERNATE parks the application as a reserve, consuming no slot. A DECIDE with `outcome` REJECT sends it to NOT_SELECTED.

Slot accounting is a live aggregation, not a stored counter that drifts: a program's `slots_remaining` is its `slot_quota` minus the number of that program's applications currently in the slot-consuming states SELECTED, PLACEMENT, GRANT_PENDING, or AWARDED. Applications in ALTERNATE and in every negative terminal state consume nothing. The conservation invariant of §2.10 follows directly, and selecting then later declining the same application nets to zero.

Whenever a slot is released — a SELECTED or PLACEMENT application is declined by its applicant, or a placement negotiation fails outright — the freed slot is immediately re-offered through the alternate auto-promotion rule. The candidates are exactly the ALTERNATE applications of the same country program. They are ranked by `recommend_seq` ascending, the lowest first; because that sequence is unique within a program, no tie-break is ever needed — and were one ever required, the second-level fallback is `created_at` ascending, never the `id`. The single winning alternate moves ALTERNATE → SELECTED, re-consumes the slot, and spawns its own PROVISIONAL grant with provisional award terms. If no alternate is waiting, no promotion happens and the slot simply stays released. Exactly one promotion occurs per released slot.

### 3.5. Placement Negotiation and the Round Ledger

For a SELECTED application, the `HostCommission` negotiates with receiving institutions by opening a placement round, supplying the `institution_name` negotiated with, the `institution_band` that institution offers (`STANDARD` or `HIGH` — its cost-of-living band), an inclusive offer expiry `response_deadline`, and the OCC guard `expected_application_version` of §2.8. The new round's `round_number` is the application's `placement_rounds_used` plus one, and that counter increments as the round opens; the very first round moves the application SELECTED → PLACEMENT. At most one non-terminal — that is, OFFERED — round may exist per application at a time (`ERR_ACTIVE_ROUND_EXISTS`), and the negotiation is hard-capped at three rounds in total. Each round's `status` walks from OFFERED to exactly one of ACCEPTED, DECLINED, or EXPIRED.

The owning applicant responds to a live offer. Acceptance requires the round still OFFERED (`ERR_ROUND_NOT_OFFERED`) and the logical clock at or before the `response_deadline`, the deadline being inclusive (`ERR_OFFER_EXPIRED`); it stamps `responded_at` with the clock, moves the round OFFERED → ACCEPTED, and advances the application PLACEMENT → GRANT_PENDING. Declining runs under the same two gates, stamps `responded_at`, and moves the round OFFERED → DECLINED. A `ProgramOfficer` may instead expire a live offer once the clock has moved strictly past the deadline — expiring it any earlier is rejected with `ERR_INVALID_STATE` — moving the round OFFERED → EXPIRED. Either way, when the round that just died is the application's third — its `round_number` equal to the three-round cap — the negotiation is over: the application cascades PLACEMENT → PLACEMENT_FAILED, its slot is released, and the alternate auto-promotion of §3.4 runs for the freed slot.

An applicant may also walk away from the award entirely. Declining from SELECTED releases the slot and triggers auto-promotion. Declining from PLACEMENT first collapses any still-OFFERED round of the application to DECLINED, then releases the slot and triggers auto-promotion. Both land the application in the terminal DECLINED state.

### 3.6. Grant Terms: Provisional Award, Confirmation, and the Dependent Allowance Cap

The grant created at selection — whether by host decision or by alternate promotion — quotes provisional award terms, because the receiving institution's cost-of-living band is not yet known. The provisional monthly stipend is always the country program's STANDARD-band figure, stored as `provisional_monthly_stipend_cents`. The monthly dependent allowance is the program's `dependent_allowance_monthly_cents` multiplied by the number of accompanying dependents counted — the application's `dependents_count`, but never more than two. The `provisional_total_cents` is then the per-month sum of monthly stipend, monthly dependent allowance, and monthly health premium, multiplied by the application's `proposed_duration_months`, plus the one-time `travel_allowance_cents`. The provisional variant deliberately quotes the STANDARD band, uses the requested duration, and applies no percentage cap to the dependent allowance. An application's grant — at most one exists — can be read back through the application's grant listing.

Once a placement round is ACCEPTED and the application sits in GRANT_PENDING, a `ProgramOfficer` confirms the final terms by supplying `start_date` and `end_date`. Confirmation is gated: the application must be GRANT_PENDING, meaning an accepted placement exists (`ERR_PLACEMENT_NOT_SECURED`); the grant must still be PROVISIONAL (`ERR_INVALID_STATE`); the confirmed duration must fall within the country program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the `start_date` must not precede the logical clock's date (`ERR_START_DATE_IN_PAST`); and the requested period must not collide with another live grant of the same applicant (`ERR_GRANT_PERIOD_OVERLAP`). The duration itself, stored as `duration_months`, counts whole calendar months between the two dates — twelve times the difference between the end and start years, plus the difference between the end and start months, with days ignored. For the overlap rule the period is treated as running from `start_date` up to but not including `end_date`; it overlaps another grant of the same applicant in CONFIRMED, ACTIVE, or SUSPENDED status whenever the two periods share any day under that convention, while pure adjacency — a new start exactly equal to an existing end — is permitted.

Confirmation stamps the grant's `awarded_band` from the accepted round's `institution_band` and computes the final award. The final monthly stipend, stored as `final_monthly_stipend_cents`, is the program's `monthly_stipend_high_cents` when the awarded band is HIGH and its `monthly_stipend_standard_cents` otherwise. The base total is the per-month sum of that final stipend and the monthly health premium, multiplied by `duration_months`, plus the one-time travel allowance. The raw dependent allowance is the monthly per-dependent figure times the counted dependents — again at most two — times `duration_months`. The dependent allowance cap is then evaluated in a pinned order: first the base total, which deliberately excludes any dependent allowance; then the cap, which is one quarter — 25% — of that base total, rounded half up to whole cents; then the granted dependent allowance, which is the smaller of the raw allowance and the cap. The `final_total_cents` is the base total plus the granted dependent allowance. Computing the quarter against a base that already includes the dependent allowance yields a different figure and is wrong. Because the provisional variant pins the STANDARD band and skips the cap, the two variants diverge on identical application data whenever the accepted band is HIGH or the cap binds. Confirmation moves the grant PROVISIONAL → CONFIRMED and the application GRANT_PENDING → AWARDED, its terminal success state.

### 3.7. Visa Sponsorship, Orientation, and Grant Activation

With a CONFIRMED grant in hand — otherwise `ERR_GRANT_NOT_CONFIRMED` — a `ProgramOfficer` issues the exchange visitor visa sponsorship, supplying `subject_to_home_residency`, the two-year home residency determination, and `orientation_completed_at`, the pre-departure orientation completion timestamp, which must not lie in the future (`ERR_VALIDATION`). A grant carries at most one sponsorship (`ERR_DUPLICATE_VISA`), and the sponsorship's own `status` begins at ISSUED. Issuance assigns the `sponsor_program_number` — the letters "EV-" followed by a six-digit sequence — copies the orientation timestamp onto the grant's own `orientation_completed_at`, and creates the grantee's residency ledger: bound to the sponsorship via `visa_sponsorship_id`, starting in PENDING when the grantee is subject to home residency and in NOT_REQUIRED otherwise, with `required_days` set to 730 and `accrued_days` at 0. A grant's single sponsorship, and a sponsorship's single ledger, are each readable through their parent listings.

Activation — moving the grant CONFIRMED → ACTIVE — is gated twice: the grant's `orientation_completed_at` must be set, which in practice means a visa sponsorship has been issued (`ERR_ORIENTATION_INCOMPLETE`), and the logical clock must be at or past the grant's `start_date` (`ERR_START_DATE_NOT_REACHED`). Activation moves the sponsorship ISSUED → ACTIVE and schedules the grantee's reporting obligations: the `interim_report_due_date` falls four calendar months after `start_date`, and the `final_report_due_date` falls thirty days after `end_date`.

### 3.8. Incidents, Suspension, Completion, and Early Termination

While a grant is ACTIVE, a `ProgramOfficer` may declare an in-country emergency incident with a `category` of `MEDICAL`, `SECURITY`, `NATURAL_DISASTER`, or `CIVIL_UNREST` and a free-form `description`. Declaration requires the grant to be ACTIVE (`ERR_GRANT_NOT_ACTIVE`) and at most one OPEN incident per grant (`ERR_ACTIVE_INCIDENT_EXISTS`). The incident's `status` begins at OPEN, its `opened_at` is stamped from the logical clock, and the declaration suspends the grant ACTIVE → SUSPENDED in the same step.

Resolving an OPEN incident moves it to the terminal RESOLVED state, stamps `resolved_at` from the clock, and records the payload `outcome`. When the outcome is RESUME, the incident's `suspension_days` are computed as the whole calendar days between the declaration date and the resolution date; the grant's `end_date` is extended by exactly that many days, with all award amounts unchanged; those days are added into `suspension_days_total`; the `final_report_due_date` is recomputed from the shifted `end_date` as thirty days beyond it; the `interim_report_due_date` is left untouched; and the grant returns SUSPENDED → ACTIVE. When the outcome is TERMINATE, the incident's resolution runs the full early-termination cascade described below instead.

Normal completion is a `ProgramOfficer` action on an ACTIVE grant, permitted once the logical clock has reached `end_date` (`ERR_END_DATE_NOT_REACHED`) and a FINAL report for the grant exists in SUBMITTED or ACCEPTED status (`ERR_FINAL_REPORT_MISSING`). Completion moves the grant ACTIVE → COMPLETED, moves the sponsorship ACTIVE → COMPLETED, opens residency accrual — the ledger moves PENDING → ACCRUING with `accrual_start_date` set to the grant's `end_date`, but only when the grantee is subject to home residency — and creates the grantee's AlumniProfile with `terminated_early` false.

Early termination applies to an ACTIVE or SUSPENDED grant, either as a `ProgramOfficer` action — which may carry a `termination_reason` that is recorded on the grant — or forced by an incident resolved with outcome TERMINATE. It requires the logical clock to be strictly before `end_date`; at or beyond that date, completion is the correct path and termination is rejected with `ERR_INVALID_STATE`. Termination reconciles the award in a pinned rounding order. The termination date is the logical clock's date. Served months are the whole days between `start_date` and the termination date, divided by thirty and rounded down; unserved months are `duration_months` minus the served months, and always at least one because the clock precedes `end_date`. The monthly rate is computed first — `final_total_cents` divided by `duration_months`, rounded half up to whole cents — and only then multiplied: `repayment_cents` is the unserved months times that rate, and `earned_cents` is the served months times that rate. Finally, `reconciliation_adjustment_cents` is whatever remains so that earned plus repayment plus adjustment equals `final_total_cents` exactly; it absorbs the per-month rounding remainder and may be negative, zero, or positive. Summing first and rounding once would give a different cent value and is wrong. The cascade then moves the sponsorship ACTIVE → ENDED_EARLY, opens residency accrual from the termination date when the grantee is subject to home residency, creates the AlumniProfile with `terminated_early` true, and resolves any still-OPEN incident of the grant with outcome TERMINATE.

### 3.9. Reports, Home Residency, and Alumni Engagement

Grantees file reports while their grant is ACTIVE or SUSPENDED — filing against a grant in any other state is rejected with `ERR_GRANT_NOT_ACTIVE`. Each report carries a `report_type` of INTERIM or FINAL and its `content`; one report of each type may exist per grant (`ERR_DUPLICATE_REPORT`). A FINAL report is accepted only once the logical clock has reached the grant's `end_date`, or when the grant has already reached COMPLETED or TERMINATED_EARLY (`ERR_REPORT_WINDOW_INVALID`). The report is born SUBMITTED, with `submitted_at` stamped from the logical clock, and its `late` flag is set when that instant falls strictly after the applicable due date — the grant's `interim_report_due_date` for an INTERIM report, its `final_report_due_date` for a FINAL one; a submission landing exactly at the due instant is on time. A late first submission adds one to the grant's `compliance_strikes`, once; a resubmission never re-strikes, because `submitted_at` never moves. Reports of a grant may be listed with a `report_type` filter.

Review is a short loop. A `ProgramOfficer` accepts a SUBMITTED report, moving it to the terminal ACCEPTED state, or requests revision, moving it SUBMITTED → NEEDS_REVISION and storing the supplied `revision_note`. The owning grantee then resubmits, moving NEEDS_REVISION → SUBMITTED; the resubmission replaces `content` when new content is supplied and leaves `submitted_at` untouched, so lateness is fixed at first submission.

Home residency accrual runs on the ledger created at visa issuance. While the ledger is ACCRUING — recording a stay or requesting a waiver against a ledger in any other state is rejected with `ERR_RESIDENCY_NOT_ACCRUING` — the grantee records home-country stays by supplying `start_date` and `end_date`. A stay whose `start_date` precedes the ledger's `accrual_start_date` is rejected with `ERR_STAY_BEFORE_ACCRUAL_START`, and a stay whose end precedes its start is `ERR_VALIDATION`. Each stay's day count spans both endpoints inclusively — the difference between end and start in days, plus one — and the stay is appended to the ledger's `stays`, each entry keeping its `start_date`, `end_date`, and `day_count`; `accrued_days` is the running sum across all recorded stays. Stays on one ledger are closed intervals: a new stay overlaps an existing one unless it ends strictly before the existing stay begins or begins strictly after the existing stay ends, and a new stay that begins exactly on the day an existing one ends counts as overlapping, because no calendar day may be counted twice (`ERR_STAY_OVERLAP`). The moment an appended stay pushes `accrued_days` to at least 730 — the requirement, at an inclusive boundary — the ledger moves ACCRUING → FULFILLED. The waiver loop runs alongside accrual: the grantee requests a waiver with a `waiver_reason`, moving ACCRUING → WAIVER_PENDING with the reason stored; a `ProgramOfficer` then approves it (WAIVER_PENDING → WAIVED) or denies it (WAIVER_PENDING → ACCRUING).

Completion or early termination of a grant spawns the grantee's AlumniProfile, bound to the applicant via `applicant_id` and to the grant via `grant_id`, copying the grant's `terminated_early` outcome and its `compliance_strikes` at creation. Two engagement indices are recomputed on every read of the profile. The provisional index, `engagement_index_provisional` — the default surface shown to the grantee — starts from a base of 50 points, adds 10 points for every report of the grant in SUBMITTED or ACCEPTED status, subtracts 20 points per compliance strike, and is clamped so it never falls below 0 or exceeds 100. The certified index, `engagement_index_certified` — the variant that governs eligibility decisions and the program office view — applies the same arithmetic but counts only ACCEPTED reports. The two variants diverge whenever a report sits in SUBMITTED or NEEDS_REVISION. The profile's `residency_status` mirrors the linked residency ledger's state live, as of the read. The profile's `follow_on_eligible` is ELIGIBLE exactly when the grant did not terminate early, the strikes number fewer than two, and the residency status is FULFILLED, WAIVED, or NOT_REQUIRED; in every other case it is INELIGIBLE. Profiles are listed per applicant — the view an applicant consults before attempting a follow-on application — or per grant.

## 4. Endpoint Definitions

Operations that create a new resource — a cycle, a country program, an applicant, an application, a review score, a placement round, a visa sponsorship, a stay record, a report, or an incident — return `201 Created`. Operations that modify an existing resource, drive a state transition, or advance the logical clock return `200 OK`. The table below is a structural summary only; request payloads, side effects, and gating rules are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/exchange/cycles` | Create a competition cycle | PlatformAdmin |
| GET | `/exchange/cycles/{id}` | Get a competition cycle | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| POST | `/exchange/cycles/{id}/transition` | Advance cycle phase (OPEN, CLOSE, BEGIN_SCREENING, FINALIZE_AWARDS, COMPLETE) | PlatformAdmin |
| POST | `/exchange/cycles/{id}/country-programs` | Create a host-country program offering for a cycle | PlatformAdmin |
| GET | `/exchange/country-programs/{id}` | Get a country program | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| GET | `/exchange/cycles/{id}/country-programs` | List country programs of a cycle | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| PATCH | `/exchange/country-programs/{id}` | Update a country program's quota/allowances while its cycle is DRAFT | PlatformAdmin |
| POST | `/exchange/applicants` | Register an applicant | Anonymous |
| GET | `/exchange/applicants/{id}` | Get an applicant (Applicant role: own record only) | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| POST | `/exchange/applications` | Create a DRAFT application (cycle must be OPEN) | Applicant |
| GET | `/exchange/applications/{id}` | Get an application (Applicant role: own only) | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| GET | `/exchange/applications` | List applications with filters | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer, Applicant |
| PATCH | `/exchange/applications/{id}` | Update a DRAFT application's fields (OCC on the application's version) | Applicant |
| POST | `/exchange/applications/{id}/transition` | Application lifecycle action (SUBMIT, WITHDRAW, DECLINE by Applicant; DECIDE with outcome by stage reviewer role) | Applicant, CampusReviewer, NationalReviewer, HostCommission |
| POST | `/exchange/applications/{id}/scores` | Post a review score; stage derived from application status | CampusReviewer, NationalReviewer |
| GET | `/exchange/applications/{id}/scores` | List review scores of an application | PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer, CampusReviewer |
| POST | `/exchange/applications/{id}/placement-rounds` | Open a placement negotiation round with a receiving institution (OCC on the application's version) | HostCommission |
| GET | `/exchange/applications/{id}/placement-rounds` | List placement rounds of an application | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| POST | `/exchange/placement-rounds/{id}/transition` | Respond to or expire an offer (ACCEPT, DECLINE by owning Applicant; EXPIRE by ProgramOfficer) | Applicant, ProgramOfficer |
| GET | `/exchange/applications/{id}/grants` | List the grant of an application (0 or 1 entries) | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| POST | `/exchange/applications/{id}/grant-confirmation` | Confirm final grant terms after an accepted placement | ProgramOfficer |
| GET | `/exchange/grants/{id}` | Get a grant | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| POST | `/exchange/grants/{id}/transition` | Grant lifecycle action (ACTIVATE, COMPLETE, TERMINATE) | ProgramOfficer |
| POST | `/exchange/grants/{id}/visa-sponsorships` | Issue exchange visitor visa sponsorship for a CONFIRMED grant | ProgramOfficer |
| GET | `/exchange/visa-sponsorships/{id}` | Get a visa sponsorship | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| GET | `/exchange/grants/{id}/visa-sponsorships` | List visa sponsorships of a grant (0 or 1 entries) | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| GET | `/exchange/visa-sponsorships/{id}/residency-ledgers` | List the residency ledger of a sponsorship (0 or 1 entries) | PlatformAdmin, ProgramOfficer, Applicant |
| GET | `/exchange/residency-ledgers/{id}` | Get a residency ledger | PlatformAdmin, ProgramOfficer, Applicant |
| POST | `/exchange/residency-ledgers/{id}/stays` | Record a home-country stay; accrues days and may fulfill the two-year requirement | Applicant |
| POST | `/exchange/residency-ledgers/{id}/transition` | Residency waiver actions (REQUEST_WAIVER by owning Applicant; APPROVE_WAIVER, DENY_WAIVER by ProgramOfficer) | Applicant, ProgramOfficer |
| POST | `/exchange/grants/{id}/reports` | Submit an INTERIM or FINAL report for a grant | Applicant |
| GET | `/exchange/grants/{id}/reports` | List reports of a grant | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| POST | `/exchange/reports/{id}/transition` | Review a report (ACCEPT, REQUEST_REVISION by ProgramOfficer; RESUBMIT by owning Applicant) | ProgramOfficer, Applicant |
| POST | `/exchange/grants/{id}/incidents` | Declare an in-country emergency incident on an ACTIVE grant | ProgramOfficer |
| GET | `/exchange/grants/{id}/incidents` | List incidents of a grant | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| POST | `/exchange/incidents/{id}/resolve` | Resolve an OPEN incident (RESUME resumes the grant; TERMINATE runs the early-termination cascade) | ProgramOfficer |
| GET | `/exchange/applicants/{id}/alumni-profiles` | List alumni profiles of an applicant (engagement indices recomputed on read) | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |
| GET | `/exchange/grants/{id}/alumni-profiles` | List the alumni profile spawned by a grant (0 or 1 entries) | PlatformAdmin, ProgramOfficer, HostCommission, Applicant |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_COUNTRY_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_VISA_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_OUTCOME` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUND_NOT_OFFERED` | 409 Conflict |
| `ERR_RESIDENCY_NOT_ACCRUING` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_PHASE_FORBIDS` | 409 Conflict |
| `ERR_GRANT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_PLACEMENT_NOT_SECURED` | 409 Conflict |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_COUNTRY_PROGRAMS` | 409 Conflict |
| `ERR_APPLICATIONS_PENDING` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_START_DATE_IN_PAST` | 409 Conflict |
| `ERR_START_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_END_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_REPORT_WINDOW_INVALID` | 409 Conflict |
| `ERR_STAY_BEFORE_ACCRUAL_START` | 409 Conflict |
| `ERR_ORIENTATION_INCOMPLETE` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_SCORE` | 409 Conflict |
| `ERR_DUPLICATE_VISA` | 409 Conflict |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_ACTIVE_ROUND_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_INCIDENT_EXISTS` | 409 Conflict |
| `ERR_SCORE_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_LANGUAGE_CRITERION_UNMET` | 409 Conflict |
| `ERR_STAY_OVERLAP` | 409 Conflict |
| `ERR_GRANT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_FINAL_REPORT_MISSING` | 409 Conflict |
| `ERR_FOLLOW_ON_INELIGIBLE` | 409 Conflict |
| `ERR_COUNTRY_QUOTA_EXHAUSTED` | 409 Conflict |
| `ERR_DURATION_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
