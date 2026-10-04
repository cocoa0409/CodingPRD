# Institutional Accreditation API — Product Requirements Document

## 1. Introduction

This document specifies the Institutional Accreditation API, the commission's system of record for the full accreditation lifecycle of member institutions: eligibility and candidacy for new members, the comprehensive self-study and peer-review visit, decision-panel adjudication, public action outcomes, sanction management, substantive-change review, and ongoing indicator monitoring between comprehensive reviews. The process follows the Higher Learning Commission style: an institution enters as a prospect, earns candidacy along a multi-year pathway, and must demonstrate — through a written assurance argument, verifiable evidence, and an on-site or virtual peer visit — that it satisfies the criteria for accreditation spanning mission, integrity, teaching and learning, and resources and planning.

The API exists because the process is adversarial as well as collaborative. Four constituencies — commission administrators, commission staff, institutional liaison officers, and peer reviewers — act on shared records under different authorities, and several integrity mechanisms (segregation of duties, conflict-of-interest screening, quorum and tally rules, mandatory public disclosure of every action) exist precisely because no single actor may control an outcome. Financial and non-financial indicator reports keep institutions under surveillance between comprehensive reviews, and a sanctions ladder with cure and escalation mechanics handles institutions whose standing deteriorates. Deterministic calculations — a dual-variant Composite Financial Index, readiness scores, a points-based recommended-action determination, tiered annual dues, and a threshold-based cure determination — keep every consequential number reproducible by any reader.

All resources are mounted under the `/accreditation` path prefix. Every time-dependent rule in this document — candidacy expiry, visit windows, report eligibility, disclosure and effectuation stamps, evaluation timestamps, and cure deadlines — is evaluated against a server-side logical clock (§2.4), never against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `CommissionAdmin`, `CommissionStaff`, `InstitutionLiaison`, and `PeerReviewer`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint, or that fails the entity-backed ownership binding described below, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Authentication is always evaluated before role authorization, and role authorization before any resource lookup (§2.8).

When `X-User-Role` is `CommissionAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds when `X-User-Role` is `CommissionStaff`: `X-User-ID` is opaque and binds to no stored resource. When `X-User-Role` is `InstitutionLiaison`, `X-User-ID` is the `id` of the `Institution` the liaison represents; ownership checks on any resource that belongs to an institution — directly, or through the resource's parent chain of eligibility application, review cycle, assurance argument, evidence item, substantive-change request, or indicator report — compare the institution's `id` at the root of that chain to `X-User-ID`, so a liaison acting on another institution's resources is rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is `PeerReviewer`, `X-User-ID` is the `id` of the acting `Reviewer`; every endpoint that binds a specific reviewer (responding to an assignment, scheduling or filing a visit as chair, verifying evidence, casting a panel vote) compares that binding to `X-User-ID` and rejects mismatches.

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

Endpoints that return collections accept two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless a listing states otherwise, every list endpoint returns resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, several directories expose filter parameters that the workflow narratives rely on: the institution directory filters on `accreditation_status`, `sanction_status`, and `legal_status`; the review-cycle, substantive-change, and indicator-report listings filter on `status`; an argument's evidence listing filters on `criterion_code`; a team's assignment listing filters on `reviewer_id`; and the reviewer directory filters on `affiliation_institution_id`, `specialty`, and `is_active`.

### 2.4. The Logical Clock

The server maintains a logical clock, and every rule in this document that refers to "now" reads that clock: filing stamps, candidacy start and expiry, visit-window arithmetic, the earliest moment a visit report may be filed, disclosure and effectuation stamps, indicator evaluation timestamps, and sanction cure deadlines all take their time from it. At server startup, before any administrative call, the logical clock reads exactly 2026-09-01T00:00:00Z. The server never falls back to wall-clock time.

A `CommissionAdmin` moves the clock through the administrative capability `POST /accreditation/_clock/set_current_utc`, passing the target instant in the `to_iso8601` field. A successful call returns the clock's new value in the `current_utc` field of the response. This capability is the sole means of advancing time in the system; nothing else — not the passage of real time, not any workflow step — moves it.

### 2.5. Common Resource Properties

All twelve resources of the domain — Institution, EligibilityApplication, ReviewCycle, AssuranceArgument, EvidenceItem, Reviewer, ReviewTeam, TeamAssignment, DecisionPanel, ActionOutcome, SubstantiveChangeRequest, and IndicatorReport — share one set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- **`version` (integer):** a system-managed integer that increments by one with every modification, exposed so clients can participate in optimistic concurrency control (§2.7).

Reads never mutate these fields. Any write that changes a resource's stored state — including writes driven by a cascade rather than by a direct client call on that resource — refreshes `updated_at` and advances `version`.

### 2.6. Numeric Precision and Rounding Conventions

Financial and indicator arithmetic follows fixed precision rules so that every client recomputes the same numbers the server computes. The Composite Financial Index, the Enrollment Momentum Index, and both assurance readiness scores are stored at exactly two decimal places using round-half-up; inside the CFI, each ratio is first scaled by multiplying it by twenty, and that scaled value is itself rounded half-up to two decimal places and clamped before any weighting is applied (§3.9). Annual dues are assessed in whole cents: each per-level line is rounded half-up to zero decimal places before the lines are summed, and the resulting total is an integer number of cents (§3.1). Cohort default rates are compared at one decimal place against their stored percent values (§3.3). A reviewer's `quality_rating` is recorded at two decimal places within the range 0.00 to 5.00. The point totals behind the recommended-action determination, the panel tally, and the sanction cure determination are integers and are never rounded.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and for each of them the version field is a non-optional input. The institution profile update endpoint, `PATCH /accreditation/institutions/{id}`, requires `expected_institution_version`, carrying the `version` of the institution the client last observed. The team assembly endpoint, `POST /accreditation/review-cycles/{id}/review-teams`, likewise requires `expected_review_cycle_version`, carrying the `version` of the cycle the client last observed — the cycle's version advances on every cycle mutation, including advance steps, federal-compliance recording, and earlier team assemblies. In both cases, if the supplied value does not equal the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the client holds a stale view and must re-read the resource before writing, which prevents it from overwriting changes it has not observed. Endpoints not named in this section do not accept any version field.

### 2.8. Validation Order, Existence Checks, and Nested Path Resolution

A request that would fail several checks receives the error of the first check in the evaluation order — the first failure wins. The global order is: (1) authentication of the two headers, failing as `ERR_UNAUTHENTICATED`; (2) role permission and entity-backed ownership, failing as `ERR_UNAUTHORIZED_ROLE`; (3) existence of every identifier in the path, validated left to right, where the first unresolved identifier produces the not-found code belonging to its own path root — one of `ERR_INSTITUTION_NOT_FOUND`, `ERR_ELIGIBILITY_APPLICATION_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`, `ERR_ASSURANCE_ARGUMENT_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_REVIEW_TEAM_NOT_FOUND`, `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_DECISION_PANEL_NOT_FOUND`, `ERR_ACTION_OUTCOME_NOT_FOUND`, `ERR_SUBSTANTIVE_CHANGE_NOT_FOUND`, or `ERR_INDICATOR_REPORT_NOT_FOUND`, each an HTTP 404; (4) state-machine checks — whether the target resource stands in a state that permits the requested transition, failing as `ERR_INVALID_STATE` — together with the creation guards on review cycles (`ERR_CYCLE_ALREADY_OPEN`) and substantive-change requests (`ERR_INSTITUTION_NOT_ACCREDITED`); and finally (5) the business rules of the endpoint — safety, constraint, temporal, referential, and fiscal checks — each named where it applies in §3.

Payloads that are structurally malformed — a missing required field, a value of the wrong type, an invalid enum member, or a missing type-specific detail field such as `requested_program_level` on a `PROGRAM_LEVEL` change — are rejected with `ERR_VALIDATION` (HTTP 400). Two multi-gate endpoints pin their internal order explicitly. Closing a decision panel evaluates the federal-compliance gate first, so a `DEFICIENT` cycle surfaces `ERR_FEDERAL_COMPLIANCE_DEFICIENT` rather than being masked by vote arithmetic, then the quorum gate, then the action-type consistency gate (§3.7). Submitting a substantive-change request evaluates the sanction gate before the dues gate (§3.9).

### 2.9. Two Independent Dimensions of Institutional Standing

An institution's standing is tracked on two parallel dimensions that evolve independently of one another. The first dimension, `accreditation_status`, begins at `PROSPECTIVE` and runs through `CANDIDATE` to `ACCREDITED`, with `DENIED_ENTRY` and `WITHDRAWN` as its terminal states. The second dimension, `sanction_status`, begins at `NONE` and runs through the escalating sanctions `NOTICE`, `PROBATION`, and `SHOW_CAUSE` to its own terminal state `MEMBERSHIP_REMOVED`. An institution can be `ACCREDITED` while simultaneously under `PROBATION`; a sanction does not rewrite accreditation history, and a reaffirmation does not erase a sanction. The dimensions intersect only at defined points: the membership-removal sanction also withdraws accreditation (§3.8), and the team's computed recommendation reads the sanction dimension as a severity floor (§3.6).

### 2.10. Segregation of Duties and Conflict-of-Interest Screening

The commission separates the people who evaluate an institution from the people who decide its fate, and both from the institution itself. A reviewer who holds any `TeamAssignment` on a review cycle may not sit on that cycle's decision panel: convening a panel with such a member, or a vote cast by such a reviewer, is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Evidence verification during the visit is reserved for accepted members of the visiting team, and the liaison of the institution under review may never verify evidence — a verification attempt that breaches this segregation is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`, while a reviewer holding no `ACCEPTED` assignment on the cycle's team is rejected with `ERR_REVIEWER_NOT_ASSIGNED`. Conflict screening applies wherever reviewers meet institutions: at team assembly and at panel seating, a candidate whose `affiliation_institution_id` equals the institution under review, or whose `declared_conflict_institution_ids` contains it, is ineligible, and seating or voting by such a reviewer is rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST` (HTTP 409). Screening is continuous rather than one-shot: when staff update a reviewer's profile and the change introduces an affiliation or a declared conflict matching the institution of a cycle on which the reviewer holds an active assignment, each affected assignment's `conflict_status` flips from `CLEARED` to `CONFLICTED` (§3.5).

### 2.11. Cascades and Cross-Entity Consistency

Several operations deliberately mutate more than one resource in a single transaction, and this document names every cascade at the workflow that triggers it. Three cascades structure the domain. Imposing a sanction freezes the institution's in-flight substantive-change requests: every such request in `SUBMITTED` status moves to `DEFERRED` with its `decision_notes` set to the literal text "frozen by sanction", while requests still in `DRAFT` are left untouched (§3.8, §3.9). Closing a decision panel drafts the action outcome, moves the cycle to `DECIDED`, disbands the visiting team, closes its assignments, decrements the affected reviewers' loads, and accepts the locked assurance argument unless the prevailing action is a denial (§3.7). Evaluating an indicator report into the `PANEL` band creates an already-effective sanction outcome without any panel involvement (§3.9). Cascades obey the same field discipline as direct writes: every mutated resource has its `updated_at` refreshed and its `version` advanced, per §2.5.

## 3. Business Logic & Workflows

### 3.1. Institutional Onboarding, Profile Maintenance, and Annual Dues

A `CommissionAdmin` onboards a new institution by supplying its `legal_name`, its `legal_status`, its two-letter `state_code` of incorporation, its current `fte_enrollment` as a non-negative integer, and its `degree_levels_offered` as a non-empty subset of `ASSOCIATE`, `BACCALAUREATE`, `MASTERS`, and `DOCTORAL`. The `legal_status` is one of `PUBLIC`, `PRIVATE_NONPROFIT`, or `PRIVATE_FORPROFIT`, and it matters beyond record-keeping: it selects which variant of the Composite Financial Index is computed on every future indicator submission (§3.9). A new institution begins with `accreditation_status` `PROSPECTIVE` and `sanction_status` `NONE`, with `distance_delivery_approved` false, `locations_count` at 1, no candidacy pathway or timestamps — `candidacy_pathway`, `candidacy_started_at`, and `candidacy_expires_at` all null — no `accredited_since` or `last_reaffirmed_at`, and no CFI history, so `latest_cfi_value` and `latest_cfi_band` are null until the first indicator evaluation.

Onboarding immediately assesses annual dues. The assessment is a fixed base of 250,000 cents plus one line item per offered degree level, where each line is the institution's `fte_enrollment` multiplied by that level's per-FTE rate in cents — 33 for `ASSOCIATE`, 45 for `BACCALAUREATE`, 61 for `MASTERS`, 83 for `DOCTORAL` — and by that level's multiplier — 1.00 for `ASSOCIATE`, 1.00 for `BACCALAUREATE`, 1.15 for `MASTERS`, 1.35 for `DOCTORAL`. The rounding order is pinned: each line is rounded half-up to whole cents first, then the rounded lines are summed, and only then is the base added; summing the raw unrounded lines first produces a different total and is not the contract. The result is stored as `current_annual_dues_cents`. At creation the system also initializes `dues_paid_cents` equal to `current_annual_dues_cents`, so a freshly onboarded institution starts with zero arrears. The institution's arrears are carried on `outstanding_dues_cents`, defined as the amount by which `current_annual_dues_cents` exceeds `dues_paid_cents`, floored at zero; any positive arrears block substantive-change submission (§3.9).

Thereafter, `CommissionStaff` maintain the profile through the versioned institution update, which accepts changes to `legal_name`, `legal_status`, `state_code`, `fte_enrollment`, `degree_levels_offered`, and `dues_paid_cents` alongside the mandatory `expected_institution_version` (§2.7). Staff record dues payments by raising `dues_paid_cents`. Whenever an update touches `fte_enrollment` or `degree_levels_offered`, the dues assessment is recomputed from the new values; a change of `legal_status` flips the CFI variant used by future indicator submissions without recomputing past reports. Two events elsewhere in the lifecycle trigger the same recomputation: an indicator submission refreshes the institution's FTE and recomputes dues (§3.9), and an approved `PROGRAM_LEVEL` substantive change appends a degree level and recomputes dues (§3.9).

### 3.2. Eligibility Filings and the Candidacy Clock

An institution enters the pipeline when its `InstitutionLiaison` drafts an `EligibilityApplication` naming the requested `pathway` — `STANDARD`, a four-year candidacy, or `ACCELERATED`, a two-year candidacy — together with a free-text `statement_of_intent`. Drafting is possible only while the institution is `PROSPECTIVE`; once the institution has moved on, the request is rejected with `ERR_INVALID_STATE`. The application records the institution it belongs to on its `institution_id`, taken from the creation path, and is born in `DRAFT`.

Filing moves the application from `DRAFT` to `FILED` and stamps `filed_at` with the logical clock. Staff then adjudicate a `FILED` application by passing a `decision` of `APPROVE`, `DENY`, or `REQUEST_COMPLETION`, optionally accompanied by `adjudication_notes`; every adjudication stamps `adjudicated_at`. Denial moves the application to the terminal `DENIED`. A completion request moves it to `DEFICIENT`, from which the liaison may re-file — the deficiency loop returns the application to `FILED` with a fresh `filed_at` and may repeat.

Approval is the consequential branch. It is permitted only while the institution is still `PROSPECTIVE` — adjudicating approval against an institution in any other standing is rejected with `ERR_INVALID_STATE` — and it moves the application itself to the terminal `APPROVED` while promoting the institution from `PROSPECTIVE` to `CANDIDATE`: the approved application's `pathway` is copied onto `candidacy_pathway`, `candidacy_started_at` is stamped with the logical clock, and `candidacy_expires_at` is computed as the candidacy start plus the pathway length, four years for `STANDARD` and two years for `ACCELERATED`. The candidacy clock is a hard gate later in the pipeline: effectuating a `GRANT_INITIAL` outcome when the logical clock has passed `candidacy_expires_at` is rejected with `ERR_CANDIDACY_EXPIRED` (§3.8).

### 3.3. The Comprehensive Review Cycle and Federal Compliance

`CommissionStaff` open a comprehensive review cycle for an institution by naming a `cycle_type`. An `INITIAL_ACCREDITATION` cycle requires the institution to be a `CANDIDATE`; a `REAFFIRMATION` cycle requires it to be `ACCREDITED`; a mismatch between the requested cycle type and the institution's standing is rejected with `ERR_INVALID_STATE`. At most one cycle per institution may be open at a time — creating a cycle while another cycle of the same institution holds any `status` other than `CLOSED` is rejected with `ERR_CYCLE_ALREADY_OPEN` (HTTP 409). A new cycle is `SCHEDULED`, with `federal_compliance_status` `PENDING`, empty `federal_components` and `cohort_default_rates`, and no `decided_at`; it records its institution on `institution_id` from the creation path.

The cycle walks a one-directional ladder: `SCHEDULED` → `MATERIALS_OPEN` → `EVALUATION_ACTIVE` → `VISIT_COMPLETE` → `PANEL_REVIEW` → `DECIDED` → `CLOSED`. Staff advance the cycle one deterministic step at a time, and each successful advance increments the cycle's `version`. Three steps are gated on sub-resources, and each gate failure surfaces `ERR_CYCLE_PREREQUISITE_NOT_MET` (HTTP 409): moving from `MATERIALS_OPEN` to `EVALUATION_ACTIVE` requires an assurance argument of this cycle in `SUBMITTED` or `REVIEW_LOCKED`; moving from `EVALUATION_ACTIVE` to `VISIT_COMPLETE` requires a review team of this cycle in `REPORT_FILED`; and moving from `VISIT_COMPLETE` to `PANEL_REVIEW` requires a decision panel of this cycle in `CONVENED`. The step from `PANEL_REVIEW` to `DECIDED` is never taken through the advance capability — it happens only as a cascade of closing the decision panel, which also stamps `decided_at` (§3.7). The final step from `DECIDED` into `CLOSED` requires the action outcome created by the deciding panel to have reached `EFFECTIVE`, again failing with `ERR_CYCLE_PREREQUISITE_NOT_MET` otherwise. `CLOSED` is the cycle's terminal state.

Federal compliance is recorded on the cycle itself, because it protects student-aid eligibility. Staff submit the `federal_components` — a list of records, each pairing a `component_code` with a `result` of `PASS` or `FAIL` — together with `cohort_default_rates`, up to three most-recent annual cohort default rates in percent, ordered oldest first. The assessment reads the rates chronologically: the cycle is `DEFICIENT` if any single rate is 40.0 or greater, or if three rates were provided and all three are 30.0 or greater — both boundaries are inclusive, so exactly 40.0 triggers the single-year rule and exactly 30.0 counts toward the three-year rule. Independently of the rates, any federal component with a `FAIL` result also yields `DEFICIENT`. Only when every recorded component is `PASS` and neither default-rate rule fires is the cycle marked `COMPLIANT`. The verdict is stored on `federal_compliance_status`, which remains `PENDING` until recorded, and recording it increments the cycle's `version`. A `DEFICIENT` finding has teeth downstream: it floors the team's computed recommendation at sanction severity (§3.6) and blocks the decision panel from closing at all (§3.7).

### 3.4. The Assurance Argument and Its Evidence Base

Once a cycle opens its materials phase, the liaison drafts the institution's self-study as an `AssuranceArgument` with its `narrative_text`; drafting is possible only while the cycle is `MATERIALS_OPEN`, and later attempts are rejected with `ERR_INVALID_STATE`. The argument records its cycle on `review_cycle_id` from the creation path and is born in `DRAFT` with a `revision_count` of zero. Against the argument the liaison attaches evidence items, each recording its argument on `assurance_argument_id` and naming a `criterion_code` — one of `CRIT_MISSION`, `CRIT_INTEGRITY`, `CRIT_TEACHING_QUALITY`, `CRIT_TEACHING_EVALUATION`, or `CRIT_RESOURCES_PLANNING` — an `evidence_type` of `INSTITUTIONAL_DATA`, `ASSESSMENT_RESULT`, `FINANCIAL_INDICATOR`, or `POLICY_DOCUMENT`, plus a `title` and a `document_uri`. Evidence may be attached only while the argument is `DRAFT` or `REVISION_REQUESTED`; attempts against an argument in any other state are rejected with `ERR_INVALID_STATE`. An evidence item is born with `verified` false and `verified_by_reviewer_id` null.

Submitting the argument is gated on coverage. From `DRAFT`, submission additionally requires the parent cycle to be `MATERIALS_OPEN`, failing as `ERR_INVALID_STATE`; both the first submission and every resubmission out of `REVISION_REQUESTED` require every criterion to hold at least 3 evidence items and the argument to hold at least 15 evidence items in total, failing which the submission is rejected with `ERR_INSUFFICIENT_EVIDENCE_COVERAGE` (HTTP 422). A successful submission moves the argument to `SUBMITTED`, stamps `submitted_at`, and computes the self-reported readiness score onto `readiness_self_reported`.

Readiness is a weighted coverage score across the five criteria. For each criterion, the coverage fraction is the number of qualifying evidence items divided by the per-criterion requirement of 3, capped at 1.0; the readiness score is one hundred times the weighted sum of the five coverage fractions — weighted 0.15 for mission, 0.25 for integrity, 0.25 for teaching quality, 0.15 for teaching evaluation, and 0.20 for resources and planning — rounded half-up to two decimal places. The two variants differ only in what counts as qualifying: the `SELF_REPORTED` variant, computed at every submission, counts every attached item regardless of verification, while the `TEAM_VERIFIED` variant counts only items whose `verified` flag is true, so the identical evidence set scores lower until the visiting team verifies it.

Staff who find a submitted argument wanting may request a revision, which increments `revision_count` and returns the argument to `REVISION_REQUESTED` — the cyclic loop back to submission. The loop is bounded: requesting a revision when `revision_count` has already reached the maximum of 2 fails the call with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 409), and within that same rejected request the argument transitions to the terminal `REJECTED_AS_INSUFFICIENT`. When the cycle has reached `EVALUATION_ACTIVE`, staff lock the submitted argument for the visit — locking while the cycle is in any other state is rejected with `ERR_INVALID_STATE` — which stamps `locked_at`, moves the argument to `REVIEW_LOCKED`, and initializes `readiness_team_verified` from the verified-evidence variant.

During the visit, accepted team members toggle verification on individual evidence items by passing `verified`; the call records the acting reviewer on `verified_by_reviewer_id`, resets that field to null whenever `verified` is set false, and recomputes the team-verified readiness on every toggle. Verification is restricted to an `ACCEPTED` member of the cycle's own team acting while the argument is `REVIEW_LOCKED` — a reviewer without that binding is rejected with `ERR_REVIEWER_NOT_ASSIGNED`, and the liaison of the institution under review is additionally barred by segregation of duties with `ERR_SEGREGATION_OF_DUTIES` (§2.10). When the cycle is ultimately decided with any prevailing action other than a denial, the locked argument cascades to the terminal `ACCEPTED` state (§3.7).

### 3.5. The Peer Reviewer Registry and Deterministic Team Assembly

`CommissionStaff` register peer reviewers with a `full_name`, the `specialty_criteria` they cover as a subset of the five criterion codes, and a `quality_rating` between 0.00 and 5.00 at two decimal places; optional attributes are the reviewer's home `affiliation_institution_id` (null for the unaffiliated), a `declared_conflict_institution_ids` list, a `prior_chair_count` of completed prior chair assignments (default 0), and an `is_active` flag (default true). The system continuously tracks each reviewer's `current_assignment_count`: the number of their assignments whose `response` is `PENDING` or `ACCEPTED`, whose own status is `ACTIVE`, and whose team has not been `DISBANDED`. A reviewer may carry at most 3 such concurrent assignments. Staff may later update the mutable attributes; such an update increments the reviewer's `version` and re-screens every `ACTIVE` assignment the reviewer holds — if the update introduces an affiliation or a declared conflict matching the institution under review on one of those assignments' cycles, that assignment's `conflict_status` flips from `CLEARED` to `CONFLICTED`.

Team assembly is deterministic and is performed by the system, never by hand. Staff request a team for a cycle by naming the `visit_modality` — `ON_SITE` or `VIRTUAL` — and presenting the mandatory `expected_review_cycle_version` (§2.7). A cycle may hold at most one team that is not `DISBANDED`, so assembling a second live team is rejected with `ERR_INVALID_STATE`. The selector first filters the registry to eligible candidates: a candidate must be active, must have an `affiliation_institution_id` that is null or different from the cycle's institution, must not list the cycle's institution among `declared_conflict_institution_ids`, must have a `current_assignment_count` below 3, and must not already hold an `ACTIVE` assignment on any team of this cycle. From the eligible pool, the chair is chosen among candidates whose `prior_chair_count` is at least 2, ranked by `quality_rating` descending, then `prior_chair_count` descending, then `created_at` ascending; if no eligible candidate meets the chair bar, assembly fails with `ERR_NO_ELIGIBLE_CHAIR` (HTTP 422). The three member seats go to the highest-ranked remaining candidates, ranked by the number of `specialty_criteria` covered descending, then `quality_rating` descending, then `created_at` ascending; if fewer than three members are available, assembly fails with `ERR_INSUFFICIENT_REVIEWER_POOL` (HTTP 422). A successful assembly creates four `TeamAssignment` records on the new team — one with `role_on_team` `CHAIR` and three with `MEMBER`, each recording its team on `review_team_id` and its reviewer on `reviewer_id`, each with `response` `PENDING`, status `ACTIVE`, and `conflict_status` `CLEARED`, because conflicted candidates are never assigned in the first place. The assembly records its pick on the team's `chair_reviewer_id`, increments the cycle's `version`, and raises each selected reviewer's `current_assignment_count` accordingly.

Each invited reviewer answers their own assignment with a `response` of `ACCEPT` or `DECLINE`; answering another reviewer's assignment is rejected with `ERR_REVIEWER_NOT_ASSIGNED`. Acceptance is refused with `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409) when it would push the reviewer past the ceiling of 3 concurrent assignments. Declining moves the assignment's `response` to the terminal `DECLINED` and closes the assignment — its status becomes `CLOSED` — while it decrements the reviewer's load and immediately triggers the selector to offer the seat to the next-ranked eligible candidate not already assigned to this team, keeping the same `role_on_team`; if no eligible candidate remains, no replacement is created, the seat stays open, and the team simply cannot be confirmed. Staff confirm a `PROPOSED` team only when every `ACTIVE` assignment has `response` `ACCEPTED` and none carries a `conflict_status` of `CONFLICTED` — a late-declared conflict must first be resolved by a decline and its replacement — and any shortfall fails confirmation with `ERR_TEAM_INCOMPLETE` (HTTP 409). A confirmed team stands ready for the visit phase.

### 3.6. The Site Visit and the Team Report

Once the cycle is evaluating and the argument is locked, the chair schedules the visit by proposing `visit_start_at` and `visit_end_at`. Only the team's chair may schedule — any other reviewer is rejected with `ERR_REVIEWER_NOT_ASSIGNED` — the cycle must be `EVALUATION_ACTIVE` (else `ERR_INVALID_STATE`), and the cycle's assurance argument must be `REVIEW_LOCKED` (else `ERR_CYCLE_PREREQUISITE_NOT_MET`). Scheduling also runs a window-conflict check across every accepted member of the team: no accepted member may already hold an effective visit window that intersects the proposed one. Each visit's effective window is a half-open interval; for an `ON_SITE` modality it runs from one day before the visit's start to one day after its end — a one-day travel buffer on each side — while a `VIRTUAL` visit carries no buffer and its effective window is the visit's own half-open interval. Because the intervals are half-open, a window that ends exactly where another begins does not conflict. A detected conflict is rejected with `ERR_REVIEWER_WINDOW_CONFLICT` (HTTP 409). A successful scheduling stores the window on the team, which becomes `VISIT_SCHEDULED`. Staff may cancel a scheduled visit, which returns the team to `CONFIRMED` and releases the window — the cancellation-and-rescheduling loop may repeat.

After the visit, the chair files the team report. Filing before the logical clock has reached `visit_end_at` is rejected with `ERR_INVALID_STATE`, and only the chair may file, under the same `ERR_REVIEWER_NOT_ASSIGNED` binding. The report payload carries `criterion_ratings` — exactly one rating per criterion, each `MET`, `MET_WITH_CONCERNS`, or `NOT_MET`, and all five criteria must be covered or the filing is rejected with `ERR_VALIDATION` — together with the team's advisory `report_recommendation`, one of `REAFFIRM`, `GRANT`, `NOTICE`, `PROBATION`, `SHOW_CAUSE`, or `DENY`, and a free-text `report_summary`. Filing stores the three payload fields, stamps `report_filed_at`, moves the team to `REPORT_FILED`, and computes `recommended_action_computed`, the system's own deterministic recommendation.

The computed recommendation starts from the ratings: `MET` earns 4 points, `MET_WITH_CONCERNS` earns 2, and `NOT_MET` earns 0, so the total across the five criteria ranges from 0 to 20. The base severity is read off the total: 18 or more points maps to severity 1, reaffirmation; 12 through 17 points maps to severity 2, notice; 8 through 11 points maps to severity 3, probation; and 7 or fewer points maps to severity 4, show-cause — on the severity scale reaffirm 1, notice 2, probation 3, show-cause 4, higher numbers being more severe. Three floors then apply in a fixed order, each able only to raise the severity, never lower it: first, if the institution's `sanction_status` is `PROBATION` or `SHOW_CAUSE`, the severity is raised to at least 2; second, if the cycle's `federal_compliance_status` is `DEFICIENT`, the severity is raised to at least 2, while `PENDING` or `COMPLIANT` imposes no floor; third, if the institution's `latest_cfi_band` is `PANEL`, the severity is raised to at least 3. The resulting severity is then mapped through the cycle type: on a `REAFFIRMATION` cycle, severities 1 through 4 produce `REAFFIRMATION`, `NOTICE`, `PROBATION`, and `SHOW_CAUSE` respectively, while on an `INITIAL_ACCREDITATION` cycle severity 1 produces `GRANT_INITIAL`, severity 2 produces `NOTICE`, and severity 3 or 4 produces `DENIAL`. A filed report also unlocks the cycle's advance to `VISIT_COMPLETE` (§3.3), and the team remains `REPORT_FILED` until the panel's decision disbands it.

### 3.7. The Decision Panel, Voting, and the Panel-Close Cascade

With the visit report filed, `CommissionStaff` convene the decision panel by seating exactly 7 reviewers, named in `member_reviewer_ids`. Seating enforces the integrity rules of §2.10 at creation time: any nominee holding a `TeamAssignment` on the same cycle is rejected with `ERR_SEGREGATION_OF_DUTIES`, and any nominee affiliated with, or conflict-declared against, the institution under review is rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`. The panel records its cycle on `review_cycle_id` and is born `CONVENED`, with an empty `votes` list and `prevailing_action` null.

Seated members then cast their votes, one ballot per member. The vote payload is a `choice` of `REAFFIRM`, `GRANT`, `NOTICE`, `PROBATION`, `SHOW_CAUSE`, `DENY`, or `WITHDRAW`, and each cast appends an entry recording the `reviewer_id`, the `choice`, and the `cast_at` timestamp to the panel's append-only `votes` list. A member who already has a vote recorded on this panel is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409), and the segregation and conflict screens are re-applied at vote time, failing as `ERR_SEGREGATION_OF_DUTIES` or `ERR_REVIEWER_CONFLICT_OF_INTEREST` respectively. Because each cast adds a new vote entry to the panel, a successful vote returns 201.

Closing the panel is the decisive act, and its gates are evaluated in a pinned order. First, the cycle's `federal_compliance_status` must not be `DEFICIENT` — this gate is checked before any vote arithmetic, and its failure is `ERR_FEDERAL_COMPLIANCE_DEFICIENT` (HTTP 422). Second, at least 5 of the 7 seats must have cast votes — the quorum — failing which the close is rejected with `ERR_PANEL_QUORUM_NOT_MET` (HTTP 422). Third, the prevailing choice must be type-consistent with the cycle: `GRANT` and `DENY` may prevail only on an `INITIAL_ACCREDITATION` cycle, `REAFFIRM` and `WITHDRAW` only on a `REAFFIRMATION` cycle, while the sanction choices may prevail on either; an inconsistent prevailing choice is rejected with `ERR_ACTION_TYPE_MISMATCH` (HTTP 422). The tally itself takes the choice with the highest vote count among the cast votes; ties break toward the more severe action under the order `WITHDRAW` most severe, then `SHOW_CAUSE`, then `PROBATION`, then `NOTICE`, then `DENY`, then `REAFFIRM`, with `GRANT` least severe. The winning choice becomes `prevailing_action` and is mapped to the outcome vocabulary: `GRANT` maps to `GRANT_INITIAL`, `DENY` to `DENIAL`, `WITHDRAW` to `WITHDRAWAL`, `REAFFIRM` to `REAFFIRMATION`, and each sanction choice maps to the sanction of the same name.

A successful close stamps `closed_at`, moves the panel to the terminal `CLOSED`, and fires the panel-close cascade. An `ActionOutcome` is created with `origin` `PANEL`, the mapped `action_type`, and status `DRAFTED` (§3.8). The cycle moves from `PANEL_REVIEW` to `DECIDED`, stamping `decided_at`. The cycle's `REPORT_FILED` review team moves to `DISBANDED`, each of its `ACTIVE` assignments moves to `CLOSED`, and each affected reviewer's `current_assignment_count` drops accordingly. Finally, the cycle's `REVIEW_LOCKED` assurance argument cascades to `ACCEPTED` — unless the prevailing action is a denial, in which case the argument is not accepted and remains locked.

### 3.8. Action Outcomes, Public Disclosure, and the Sanction Ladder

Every commission action is born as an `ActionOutcome` in `DRAFTED` status and walks a fixed publication ladder — `DRAFTED` → `DISCLOSED` → `EFFECTIVE` — one step per advance by `CommissionStaff`, with `EFFECTIVE` terminal for the ladder itself. Disclosure is mandatory for every action, reaffirmation and denial included: the step into `DISCLOSED` stamps the generated public notice onto `public_disclosure_text` and records `disclosed_at` on the logical clock. The step into `EFFECTIVE` stamps `effective_at` and applies the action to the institution. Outcomes carry an `origin` — `PANEL` for panel-decided actions, `INDICATOR_MONITOR` for the indicator cascade of §3.9 — and while a panel outcome references its `review_cycle_id`, an indicator-monitor outcome leaves that reference null and instead records the affected institution on `indicator_origin_institution_id`, which is why the institution-level outcome listing exists alongside the cycle-level one.

Effectuation applies each action type's own institution mutation. A `REAFFIRMATION` stamps `last_reaffirmed_at` and leaves the institution `ACCREDITED`. A `GRANT_INITIAL` is gated on the candidacy clock — if the logical clock has passed `candidacy_expires_at`, the advance is rejected with `ERR_CANDIDACY_EXPIRED` (HTTP 409) — and otherwise promotes the institution from `CANDIDATE` to `ACCREDITED`, stamping `accredited_since`. A `DENIAL` moves a `CANDIDATE` institution to the terminal `DENIED_ENTRY`. A `WITHDRAWAL` moves an `ACCREDITED` institution to the terminal `WITHDRAWN` and simultaneously sets the sanction dimension to `MEMBERSHIP_REMOVED`. The three sanction actions — `NOTICE`, `PROBATION`, and `SHOW_CAUSE` — copy the action type onto the outcome's `sanction_level`, set `cure_deadline_at` to the effectuation instant plus the level's cure window (twelve months for `NOTICE`, twenty-four months for `PROBATION`, twelve months for `SHOW_CAUSE`), move the institution's `sanction_status` to the imposed level, and freeze the institution's in-flight substantive-change requests per §2.11. Sanction imposition may skip rungs: a clean institution can be placed directly on `PROBATION` when findings are severe, exactly as `NOTICE` or `SHOW_CAUSE` can be imposed where the ladder's intermediate rungs were never occupied; only the escalation mechanic below is constrained to single steps.

An `EFFECTIVE` sanction outcome then lives through a cure sub-lifecycle, driven by staff sanction transitions naming an `action` of `OPEN_CURE_REVIEW`, `CURE`, or `ESCALATE`. These transitions exist only on outcomes whose `action_type` is one of the three sanctions; targeting any other outcome is rejected with `ERR_INVALID_STATE`. Opening a cure review requires the outcome's `cure_status` to be `NONE` — opening twice is `ERR_INVALID_STATE` — and it sets `cure_status` to `UNDER_CURE_REVIEW`, stamps `cure_review_opened_at`, and freezes `cure_threshold_snapshot` at a base of 60 plus the offset of the sanction level in force at that instant: 0 for `NOTICE`, 15 for `PROBATION`, 30 for `SHOW_CAUSE`. The snapshot is deliberate: the cure bar must not move while the institution works toward it, and a later escalation replaces it with a fresh snapshot.

Curing requires the review to be open, and the evidence must clear the frozen bar. The cure evidence score awards 25 points for each of the institution's indicator reports that reached `CLEARED` with an `evaluated_at` strictly later than `cure_review_opened_at`, capped at 100. The cure succeeds only when that score is at least `cure_threshold_snapshot`; a cure attempted without an open review, or with a score below the snapshot, is rejected with `ERR_CURE_THRESHOLD_NOT_MET` (HTTP 422). A successful cure sets `cure_status` to `CURED` and lifts the institution's `sanction_status` back to `NONE`.

Escalation is single-step along the ladder. At `NOTICE` or `PROBATION` it moves the outcome's `sanction_level` and the institution's `sanction_status` to the next rung, resets `cure_deadline_at` to the escalation instant plus the new level's cure window, and resets the cure sub-lifecycle — `cure_status` returns to `NONE` and `cure_threshold_snapshot` is cleared to null. At `SHOW_CAUSE` the ladder ends in removal: escalation sets the institution's `sanction_status` to the terminal `MEMBERSHIP_REMOVED` and its `accreditation_status` to the terminal `WITHDRAWN`, while the outcome itself remains `EFFECTIVE` with `sanction_level` `SHOW_CAUSE`.

### 3.9. Substantive Change and Interim Indicator Monitoring

Between comprehensive reviews, two instruments keep an accredited institution honest: substantive-change review and indicator monitoring. A liaison drafts a `SubstantiveChangeRequest` by naming a `change_type` — `NEW_LOCATION`, `PROGRAM_LEVEL`, `OWNERSHIP_CHANGE`, or `DISTANCE_DELIVERY` — and the draft must carry the type's detail field: `requested_program_level`, one of the four degree levels, is required exactly when the type is `PROGRAM_LEVEL`; `new_location_state`, a two-letter state code, exactly when the type is `NEW_LOCATION`; and free-text `ownership_details` exactly when the type is `OWNERSHIP_CHANGE`. A missing type-specific detail is rejected with `ERR_VALIDATION`. Drafting is restricted to institutions whose `accreditation_status` is `ACCREDITED` — drafting against any other standing is rejected with `ERR_INSTITUTION_NOT_ACCREDITED` (HTTP 409) — and the request records its institution on `institution_id` and is born in `DRAFT`.

Submission is gated twice, in a pinned order: first the institution's `sanction_status` must be `NONE` or `NOTICE` — a request submitted while the institution sits at `PROBATION` or `SHOW_CAUSE` is rejected with `ERR_SANCTION_BLOCKS_CHANGE` — and then `outstanding_dues_cents` must be zero, arrears being rejected with `ERR_DUES_ARREARS` (HTTP 402). The same two gates, in the same order, guard both the first submission from `DRAFT` and every resubmission from `DEFERRED`. The sanction gate is also re-checked at decision time: staff decide a `SUBMITTED` request with a `decision` of `APPROVE`, `DENY`, or `DEFER` plus optional `decision_notes`, and an approval attempted after the institution's sanctions have deepened fails with `ERR_SANCTION_BLOCKS_CHANGE`. Approval applies the type's mutation: a `NEW_LOCATION` increments the institution's `locations_count` by one; a `PROGRAM_LEVEL` appends the `requested_program_level` to `degree_levels_offered` and recomputes the annual dues assessment of §3.1; a `DISTANCE_DELIVERY` sets `distance_delivery_approved` to true; and an `OWNERSHIP_CHANGE` mutates no institutional field beyond status, because the CFI variant follows `legal_status`, which staff maintain through the versioned profile update. Denial is terminal. Deferral moves the request to `DEFERRED`, from which the deferral-resubmission loop runs — and the sanction freeze of §2.11 pushes in-flight `SUBMITTED` requests to `DEFERRED` as well.

Indicator monitoring runs on tiled annual periods. Staff open a report for an institution by naming an inclusive `period_start` and `period_end` as ISO calendar dates; the end must fall strictly after the start, and malformed periods are rejected with `ERR_VALIDATION`. Periods must tile the institution's reporting history contiguously: the closed interval from `period_start` through `period_end` may not intersect any existing report period of the institution — an overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409) — and unless it is the institution's first report, the new `period_start` must be exactly one day after the latest existing `period_end`, any gap being rejected with `ERR_REPORT_PERIOD_GAP` (HTTP 422). The report records its institution on `institution_id` and opens in `DUE`.

The liaison then submits the period's metrics: the financial ratios `primary_reserve_ratio`, `viability_ratio`, and `net_operating_ratio`; the `state_appropriation_ratio`, which feeds only the public variant; the non-financial metrics `enrollment_change_pct`, `completion_rate` as a percentage from 0 to 100, and `retention_rate` likewise; and the verified `fte_enrollment` for the period. Submission is permitted only while the report is `DUE` — resubmitting is rejected with `ERR_INVALID_STATE` — and it performs three computations. First, the Composite Financial Index lands on `cfi_value`: each ratio is scaled by multiplying by twenty, rounding half-up to two decimal places, and clamping the result to a floor of -4.00 and a ceiling of 10.00; for a private institution (`PRIVATE_NONPROFIT` or `PRIVATE_FORPROFIT`) the index is the scaled primary reserve ratio weighted at 0.40, plus the scaled viability ratio weighted at 0.35, plus the scaled net operating ratio weighted at 0.25, summed and rounded half-up to two decimal places, with no appropriation bonus; for a `PUBLIC` institution the net operating ratio plays no part — the index is the scaled primary reserve ratio weighted at 0.50, plus the scaled viability ratio weighted at 0.50, plus an appropriation bonus of 0.50 when the `state_appropriation_ratio` is at least 0.20 and 0.00 otherwise, again rounded half-up to two decimal places, so identical ratios yield different indices under the two variants. The variant in force, `PUBLIC` or `PRIVATE`, is chosen from the institution's `legal_status` at submit time and frozen onto `cfi_variant_used`. Second, the Enrollment Momentum Index lands on `emi_value`: half of `enrollment_change_pct`, plus three tenths of the amount by which `completion_rate` exceeds its neutral value of 50.0, plus one fifth of the amount by which `retention_rate` exceeds its neutral value of 70.0, rounded half-up to two decimal places; an index strictly below -5.00 flags the report, while exactly -5.00 does not flag. Third, submission overwrites the institution's `fte_enrollment` with the reported figure and forces a recomputation of the annual dues assessment (§3.1).

Staff then evaluate a `SUBMITTED` report — evaluating from any other status is rejected with `ERR_INVALID_STATE`. Every evaluation stamps `evaluated_at` and copies the computed index and its band onto the institution's `latest_cfi_value` and `latest_cfi_band`. The band boundaries are pinned: a CFI strictly above 1.10 is the `CLEAR` band; a CFI at or below 1.10 but strictly above -0.90 is the `REVIEW` band; and a CFI at or below -0.90 is the `PANEL` band. A report whose CFI falls in the `CLEAR` band and whose EMI is at least -5.00 is marked `CLEARED`. A report whose CFI falls in the `REVIEW` band — or whose EMI is below -5.00 while its CFI stands in the `CLEAR` band — is marked `FLAGGED_REVIEW`. A report whose CFI falls in the `PANEL` band is marked `FLAGGED_PANEL`, and that verdict fires the indicator cascade: the system creates an `ActionOutcome` with `origin` `INDICATOR_MONITOR`, `action_type` `NOTICE`, status already `EFFECTIVE`, `sanction_level` `NOTICE`, a `cure_deadline_at` twelve months after the evaluation, and `indicator_origin_institution_id` pointing at the reporting institution; the institution's `sanction_status` moves from `NONE` to `NOTICE`, or stays where it is if a sanction is already in force; and the substantive-change freeze of §2.11 applies to the institution's in-flight requests. All three verdicts — `CLEARED`, `FLAGGED_REVIEW`, and `FLAGGED_PANEL` — are terminal for the report.

## 4. Endpoint Definitions

Operations that create a new resource — including a new vote entry appended to a panel's ballot list — return a `201 Created` status code. Operations that modify an existing resource or advance it along its lifecycle return `200 OK`. The table below is a navigational summary only; request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/accreditation/institutions` | Onboard an institution; computes the annual dues assessment and starts it with zero arrears | CommissionAdmin |
| GET    | `/accreditation/institutions` | Paginated institution directory with standing filters | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/institutions/{id}` | Read a single institution | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| PATCH  | `/accreditation/institutions/{id}` | Update an institution profile under optimistic concurrency control | CommissionStaff |
| POST   | `/accreditation/institutions/{id}/eligibility-applications` | Draft an eligibility application for a prospective institution | InstitutionLiaison |
| GET    | `/accreditation/institutions/{id}/eligibility-applications` | List an institution's eligibility applications | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/eligibility-applications/{id}/file` | File, or re-file after a deficiency, an application | InstitutionLiaison |
| POST   | `/accreditation/eligibility-applications/{id}/adjudicate` | Adjudicate a filed application: approve, deny, or request completion | CommissionStaff |
| POST   | `/accreditation/institutions/{id}/review-cycles` | Open a comprehensive review cycle | CommissionStaff |
| GET    | `/accreditation/institutions/{id}/review-cycles` | List an institution's review cycles | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/review-cycles/{id}` | Read a single review cycle | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/review-cycles/{id}/advance` | Advance the cycle one deterministic step | CommissionStaff |
| POST   | `/accreditation/review-cycles/{id}/record-federal-compliance` | Record federal compliance components and cohort default rates | CommissionStaff |
| POST   | `/accreditation/review-cycles/{id}/assurance-arguments` | Draft the cycle's assurance argument | InstitutionLiaison |
| GET    | `/accreditation/review-cycles/{id}/assurance-arguments` | List a cycle's assurance arguments | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/assurance-arguments/{id}` | Read a single assurance argument, including readiness scores | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/assurance-arguments/{id}/submit` | Submit or resubmit the argument under the evidence-coverage gate | InstitutionLiaison |
| POST   | `/accreditation/assurance-arguments/{id}/request-revision` | Send the argument back for revision; rejects the argument at the revision cap | CommissionStaff |
| POST   | `/accreditation/assurance-arguments/{id}/lock` | Lock the submitted argument for the visit | CommissionStaff |
| POST   | `/accreditation/assurance-arguments/{id}/evidence-items` | Attach an evidence item to the argument | InstitutionLiaison |
| GET    | `/accreditation/assurance-arguments/{id}/evidence-items` | List an argument's evidence items | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/evidence-items/{id}/verify` | Toggle an evidence item's verification during the visit | PeerReviewer |
| POST   | `/accreditation/reviewers` | Register a peer reviewer | CommissionStaff |
| GET    | `/accreditation/reviewers` | Reviewer directory with filters | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/reviewers/{id}` | Read a single reviewer | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| PATCH  | `/accreditation/reviewers/{id}` | Update reviewer attributes and re-screen active assignments | CommissionStaff |
| POST   | `/accreditation/review-cycles/{id}/review-teams` | Auto-assemble a conflict-screened team of one chair and three members | CommissionStaff |
| GET    | `/accreditation/review-cycles/{id}/review-teams` | List a cycle's review teams | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/review-teams/{id}` | Read a single review team, including visit window and filed report | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/review-teams/{id}/assignments` | List a team's assignments | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/reviewers/{id}/assignments` | List a reviewer's assignments | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/team-assignments/{id}/respond` | Accept or decline a team assignment | PeerReviewer |
| POST   | `/accreditation/review-teams/{id}/confirm` | Confirm a fully accepted, conflict-cleared team | CommissionStaff |
| POST   | `/accreditation/review-teams/{id}/schedule-visit` | Chair schedules the visit window | PeerReviewer |
| POST   | `/accreditation/review-teams/{id}/file-report` | Chair files the visit report with per-criterion ratings | PeerReviewer |
| POST   | `/accreditation/review-teams/{id}/cancel-visit` | Cancel a scheduled visit and release its window | CommissionStaff |
| POST   | `/accreditation/review-cycles/{id}/decision-panels` | Convene the seven-member decision panel | CommissionStaff |
| GET    | `/accreditation/review-cycles/{id}/decision-panels` | List a cycle's decision panels | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/decision-panels/{id}/cast-vote` | Cast one panel vote | PeerReviewer |
| POST   | `/accreditation/decision-panels/{id}/close` | Close the panel and fire the decision cascade | CommissionStaff |
| GET    | `/accreditation/review-cycles/{id}/action-outcomes` | List a cycle's action outcomes | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| GET    | `/accreditation/institutions/{id}/action-outcomes` | List outcomes targeting an institution, including indicator-monitor outcomes | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/action-outcomes/{id}/advance` | Advance an outcome through disclosure to effectuation | CommissionStaff |
| POST   | `/accreditation/action-outcomes/{id}/sanction-transition` | Run the sanction cure and escalation sub-lifecycle | CommissionStaff |
| POST   | `/accreditation/institutions/{id}/substantive-change-requests` | Draft a substantive-change request | InstitutionLiaison |
| GET    | `/accreditation/institutions/{id}/substantive-change-requests` | List an institution's substantive-change requests | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/substantive-change-requests/{id}/submit` | Submit or resubmit a change request under the sanction and dues gates | InstitutionLiaison |
| POST   | `/accreditation/substantive-change-requests/{id}/decide` | Decide a submitted change request: approve, deny, or defer | CommissionStaff |
| POST   | `/accreditation/institutions/{id}/indicator-reports` | Open an indicator report for a contiguous period | CommissionStaff |
| GET    | `/accreditation/institutions/{id}/indicator-reports` | List an institution's indicator reports | CommissionAdmin, CommissionStaff, InstitutionLiaison, PeerReviewer |
| POST   | `/accreditation/indicator-reports/{id}/submit` | Submit period metrics; computes the CFI and EMI and refreshes institutional FTE and dues | InstitutionLiaison |
| POST   | `/accreditation/indicator-reports/{id}/evaluate` | Evaluate a submitted report into its band verdict | CommissionStaff |
| POST   | `/accreditation/_clock/set_current_utc` | Set the logical clock | CommissionAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are intentionally omitted here; each error's conditions are defined in the workflow narratives of §2 and §3 where the error is raised.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_ELIGIBILITY_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSURANCE_ARGUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVIDENCE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEWER_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DECISION_PANEL_NOT_FOUND` | 404 Not Found |
| `ERR_ACTION_OUTCOME_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTANTIVE_CHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_INDICATOR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_ALREADY_OPEN` | 409 Conflict |
| `ERR_CYCLE_PREREQUISITE_NOT_MET` | 409 Conflict |
| `ERR_INSTITUTION_NOT_ACCREDITED` | 409 Conflict |
| `ERR_FEDERAL_COMPLIANCE_DEFICIENT` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_REVIEWER_CONFLICT_OF_INTEREST` | 409 Conflict |
| `ERR_INSUFFICIENT_EVIDENCE_COVERAGE` | 422 Unprocessable Entity |
| `ERR_MAX_REVISIONS_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_REVIEWER_POOL` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_CHAIR` | 422 Unprocessable Entity |
| `ERR_TEAM_INCOMPLETE` | 409 Conflict |
| `ERR_PANEL_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ACTION_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_REVIEWER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_GAP` | 422 Unprocessable Entity |
| `ERR_CANDIDACY_EXPIRED` | 409 Conflict |
| `ERR_SANCTION_BLOCKS_CHANGE` | 409 Conflict |
| `ERR_REVIEWER_NOT_ASSIGNED` | 409 Conflict |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUES_ARREARS` | 402 Payment Required |
| `ERR_CURE_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
