# Residential Workforce Training Center API — Product Requirements Document

## 1. Introduction

Residential workforce training centers take young adults out of poverty-level households and turn them into credentialed, employed graduates — but only if the pipeline holds together end to end. An applicant must first clear an eligibility determination on age, household income, and documented barriers; an eligible applicant must be matched to a center that actually teaches the desired trade, has a free seat, and has a free bed when the student boards; the enrollee must satisfy credential prerequisites, live under conduct standards with zero-tolerance rules, accumulate supervised work-based learning hours, and finally leave with a job, housing, and transportation plan. After separation, the center's operating company is paid against measured outcomes — graduation rate, placement rate, and starting wages — so every number the system reports has contractual money attached to it.

This document specifies the REST API that runs that pipeline. It covers front-door intake by admissions counselors, independent eligibility adjudication, center assignment through a weighted ranking selector, enrollment into trade programs with remediation support, dormitory and conduct management with a depth-3 separation cascade, credential attainment tracking, employer-agreement-governed work placements, post-separation transition services, and operator-contract performance review with period close-out. All resources are served under the `/jc` URL prefix, with a single test-driving clock endpoint mounted outside it. Every date- and age-sensitive rule in this document is evaluated against a logical clock (§2.4), never against wall-clock time, so that behavior is fully deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or whose `X-User-Role` value does not name one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Seven roles exist, spelled exactly as follows: `AdmissionsCounselor`, `EligibilityReviewer`, `EnrollmentManager`, `ResidentialAdvisor`, `CareerInstructor`, `TransitionSpecialist`, and `OperatorAdmin`.

All seven roles use opaque operator identities, and each role is named individually here so the ownership semantics are unambiguous. When `X-User-Role` is `AdmissionsCounselor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `intake_counselor_id` on the `Application` the counselor creates, but does not compare it to any entity's `id`. The same holds for `EligibilityReviewer` — the server records the reviewer's opaque identifier as `reviewer_id` on the `Application` when review begins. For `EnrollmentManager`, `ResidentialAdvisor`, `CareerInstructor`, `TransitionSpecialist`, and `OperatorAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`; a `TransitionSpecialist` may additionally supply an opaque staff identifier as `supervisor_id` when proposing a placement, which is stored on the placement but is not the caller's identity.

One segregation-of-duties rule cuts across these roles: the admissions counselor who intakes an eligibility case may not adjudicate it. The review actions — beginning review, requesting information, and issuing a determination — are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the acting `X-User-ID` equals the application's stored `intake_counselor_id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must be at most 100. The `offset` parameter defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, so a client can page deterministically through a collection. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order; the per-applicant eligibility-case listing is the documented exception and returns its cases newest first.

### 2.4. The Logical Clock

A single logical clock governs every date- and time-sensitive rule in the system: applicant age at determination, agreement effective windows, bed-occupancy intervals, the rolling conduct window, enrollment exit dates, transition-plan expiry, and review-period boundaries. Before any clock-setting call has been made, the clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time.

An `OperatorAdmin` may advance the clock through the test-driving capability mounted at the clock endpoint, supplying a `to_iso8601` instant; the response echoes the new clock reading as `current_utc`. Advancing the clock persists nothing by itself — instead, clock-derived statuses (the employer agreement's `ACTIVE`/`EXPIRED` posture and the transition plan's `ACTIVE`/`COMPLETED`/`EXPIRED` posture) are re-derived on the next read. Business dates elsewhere in this document are calendar dates in `YYYY-MM-DD` form taken from the logical clock's date, while clock timestamps recorded on resources are full ISO 8601 instants.

### 2.5. Resource Identity and Common Fields

Every persisted resource carries an `id` that is a server-minted UUID rendered in the canonical dashed 8-4-4-4-12 string form (36 characters, hyphens included, e.g. `550e8400-e29b-41d4-a716-446655440000`), with no type prefix; the `id` is identity-only and never participates in ranking, tie-break, or allocation decisions — `created_at` ascending is the only sanctioned common-field fallback wherever a deterministic order is needed. Resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts low at creation and increments by exactly 1 on every mutation of that resource.

One entity deviates from this shape: the performance snapshot carries only `id` and `created_at`. Both `updated_at` and `version` are absent from snapshots, because a persisted snapshot is an immutable historical record that is never modified after the period close that created it.

When several resources mutate as a side effect of one operation — an enrollment going terminal while its dormitory assignments terminate and its trade program's seat count changes — each mutated resource has its own `updated_at` refreshed and its own `version` advanced independently.

### 2.6. Optimistic Concurrency on the Applicant

Two write endpoints take an optimistic-concurrency token, and no other endpoint takes one. Opening an eligibility case for an applicant, and running center assignment for an applicant, both require the request to carry `expected_applicant_version` holding the `version` of the `Applicant` as the client last observed it. If the applicant's current `version` has advanced beyond that observed value — because, for instance, another counselor filed a case or ran an assignment in the meantime — the write is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard is what makes a re-assignment or a re-application a deliberate supersede rather than an accidental overwrite of a view the writer never saw. Endpoints not named here do not accept any version field.

### 2.7. Validation Pipeline and Priority

When several checks could fail on one request, the server reports exactly one error: the first failing rule in a fixed priority order. Authentication comes first — missing or malformed identity headers produce `ERR_UNAUTHENTICATED`, and an authenticated role outside the endpoint's authorization list produces `ERR_FORBIDDEN_ROLE`. Next, for the three review actions on an eligibility case, the segregation-of-duties check produces `ERR_SEGREGATION_OF_DUTIES`. Then path-templated identifiers are resolved left to right, and the first id that does not resolve produces `ERR_NOT_FOUND`. A structurally malformed body — a missing required field, an undeclared field, an invalid enum member, or a field-domain violation such as an out-of-range household size, a bed label outside the center's valid label range, sanction points outside their allowed band, or out-of-range daily hours — produces `ERR_INVALID_REQUEST`. Only after the body is well-formed does the optimistic-concurrency check produce `ERR_STALE_VERSION`.

State checks follow. On every transition endpoint, a target entity that already sits in a terminal state of its own state machine — an `ELIGIBLE` application, a `REVOKED` credential, an incident in `DISMISSED`, `SANCTIONED`, `EXONERATED`, or `SEPARATION_ORDERED`, a placement in `COMPLETED` or `TERMINATED`, a `TERMINATED` contract, or an assignment in `CHECKED_OUT` or `TERMINATED` — is reported as `ERR_ALREADY_TERMINAL` before any other state analysis; terminal lockdown is reported first. If the target is not terminal but the requested action is undefined from its current state, the request fails with `ERR_INVALID_STATE`; the same `ERR_INVALID_STATE` also covers create endpoints whose referenced entities violate a state precondition — cross-entity state preconditions on creates are never reported as `ERR_ALREADY_TERMINAL`. Business rules run last: conduct-hold gating, zero-tolerance routing, duplicate-application detection, prerequisite checks, hours-entry rules, selector emptiness, bed overlap and availability, agreement activity, capacity ceilings, wage floors, and period closability, each with the specific error named in §3 and §5.

One endpoint inverts part of this ordering on purpose. Recording a transition-service outcome checks the plan's service window before the generic state check: a plan whose expiry has passed is rejected with `ERR_TRANSITION_WINDOW_EXPIRED` even though the generic non-terminal-state rule would otherwise fire first, while a plan already completed (all tracks resolved) still surfaces through the generic state rule as `ERR_INVALID_STATE`.

### 2.8. Money, Rates, and Rounding

All money amounts are integer cents; the API never carries fractional cents. Income limits, wage floors, stipends, allowances, and contract payments are therefore compared and stored exactly, with no rounding at comparison time. Center-assignment scores are rounded half-up to two decimal places. Performance rates — the graduation rate and the placement rate — are rounded half-up to four decimal places, and the average starting wage is rounded half-up to whole cents. Where a rounding order is pinned by a calculation (the operator payment rounds each graduate's award to whole cents first and sums second), §3 states the order explicitly, because rounding once after summation yields a different, non-conforming result.

### 2.9. Derived State and Recomputed Fields

Several fields are never written directly; they are derived from other state and recomputed whenever their inputs change. A center's `beds_in_use` counts its `ACTIVE` dormitory assignments and its `beds_available` is the remainder of `total_beds`, with the invariant that the two sum to `total_beds` after every mutation. A trade program's `enrolled_count` counts its enrollments in `REMEDIATION` or `TRAINING`, its `open_seats` is the remainder of `capacity`, and its `status` flips itself between `OPEN` and `FULL` as seats cross zero, while `CLOSED` is reachable only by an explicit administrative update. An enrollment's `conduct_hold` is recomputed from its incidents after every incident transition and on any read. An employer agreement's `status` is derived from the logical clock on every read. A transition plan's `status` is computed on read from its three service tracks and its expiry date. Performance snapshots, by contrast, are frozen at close: their rates, counts, and payment are computed once and never recomputed.

## 3. Business Logic & Workflows

### 3.1. Front-Door Intake and the Eligibility Case

An `AdmissionsCounselor` opens the pipeline by creating an applicant with `full_name`, `date_of_birth` (a `YYYY-MM-DD` date), `home_region_code`, and `desired_trade_code`. The new applicant starts with `assignment_status` set to `NONE` and `assigned_center_id` unset; both are managed by the system from then on. Applicants can be listed with optional `assigned_center_id` and `assignment_status` filters, and fetched individually — the single-applicant view always includes the current `assignment_status` and `version`.

Against an applicant, the counselor opens an eligibility case carrying `applicant_id`, `household_size`, `annual_income_cents`, and `barrier_flags`. Household size must lie between 1 and 12 inclusive, income is a non-negative integer of cents, and each barrier flag must be one of `FOSTER_CARE`, `HOMELESS`, `SINGLE_PARENT`, `DISABILITY`, `OFFENDER`, or `LOW_BASIC_SKILLS`. The create captures the caller's header identity into `intake_counselor_id`, starts the case in `SUBMITTED`, and advances the applicant's `version` by 1 — so the optimistic-concurrency rule of §2.6 applies on this endpoint, and a writer holding an old applicant `version` is rejected with `ERR_STALE_VERSION`. An applicant may hold only one open case at a time: while any case sits in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`, a further create fails with `ERR_DUPLICATE_APPLICATION`. Once a case has reached `ELIGIBLE` or `INELIGIBLE`, a fresh case supersedes it — this is the legitimate re-application path.

Review is driven by an `EligibilityReviewer` through case actions. Beginning review moves `SUBMITTED` to `UNDER_REVIEW` and stamps `reviewer_id` with the reviewer's opaque identifier; requesting information moves `UNDER_REVIEW` to `INFO_REQUESTED` and accepts an optional `info_request_note`. Both actions, and determination itself, are subject to segregation of duties: when the acting `X-User-ID` equals the case's `intake_counselor_id`, the action is rejected with `ERR_SEGREGATION_OF_DUTIES`. The counselor answers an information request with a provide-info action that returns the case to `UNDER_REVIEW`; any of `annual_income_cents`, `household_size`, or `barrier_flags` supplied on that call overwrite the stored snapshot. The request-info/provide-info cycle may repeat without bound. An `INELIGIBLE` case is likewise reopened by the counselor's appeal action, which returns it to `UNDER_REVIEW` with the same overwrite semantics for the three snapshot fields, after which determination runs again on the updated snapshot.

Determination itself is a server-side computation over the case's stored snapshot and the applicant's `date_of_birth` at determination time; it is never a client-supplied verdict. Age is measured in whole years between the birth date and the logical clock date, subtracting one year when the birthday has not yet occurred in the current year. The income limit in cents is a 1500000-cent base plus 500000 cents for each household member beyond the first. The determination accumulates reasons in a fixed order: `AGE_OUT_OF_RANGE` when the applicant is younger than 16 or older than 24 (both bounds inclusive, so exactly 16 and exactly 24 pass); `INCOME_EXCEEDS_LIMIT` when `annual_income_cents` is strictly greater than the computed limit (income exactly equal to the limit passes); and `NO_BARRIER_DOCUMENTED` when fewer than 1 barrier flag is recorded — that is, when `barrier_flags` is empty. An empty reason list lands the case in `ELIGIBLE` with `determination_reasons` stored empty; any reason lands it in `INELIGIBLE` with the reasons stored in the order just given. Either way `determined_at` records the logical-clock timestamp of the latest determination. `ELIGIBLE` is terminal — a further case action on it fails with `ERR_ALREADY_TERMINAL` — while `INELIGIBLE` remains reopenable through appeal.

### 3.2. The Supply Side: Centers, Trade Programs, and the Assignment Selector

Before any applicant can be placed, an `OperatorAdmin` builds the supply side. A center is created with a `name`, a `region_code` matched later against applicant home regions, and a `total_beds` count of at least 1; the center starts with `beds_in_use` at 0 and `beds_available` equal to `total_beds`. A trade program is created against a `center_id` with a `trade_code` (values such as WELDING, CARPENTRY, or CULINARY), a `capacity` of at least 1, an optional `required_credential_types` list whose members come from `HSE`, `INDUSTRY_CERT`, and `DRIVER_LICENSE` (empty means no prerequisites), and an optional `supports_remediation` flag defaulting to false. The program begins with `enrolled_count` at 0, `open_seats` equal to `capacity`, and `status` set to `OPEN`. Thereafter the program's seat bookkeeping is automatic: it flips from `OPEN` to `FULL` when `open_seats` reaches 0 and back to `OPEN` when a seat frees, while `CLOSED` is reachable only through an administrative update. That update may touch only `capacity` and `status`; lowering `capacity` below the current `enrolled_count` is rejected with `ERR_INVALID_REQUEST`, `open_seats` is recomputed when capacity changes, and the update advances the program's `version` by 1.

With supply in place, an `AdmissionsCounselor` runs center assignment for an applicant, passing `residential_track` (whether the student will board) alongside the concurrency token described in §2.6. Assignment is gated on eligibility: without an `ELIGIBLE` case on file, the request fails with `ERR_APPLICANT_NOT_ELIGIBLE`. The selector then builds its candidate pool. A center qualifies only when it operates at least one trade program whose `trade_code` equals the applicant's `desired_trade_code`, whose `status` is `OPEN`, and whose `open_seats` is at least 1 — and, when `residential_track` is true, whose center's `beds_available` is at least 1. An empty pool is rejected with `ERR_NO_ELIGIBLE_CENTER`.

Each candidate is scored. The trade component takes the largest `open_seats` among the center's qualifying programs, capped at 10; the capacity component takes the center's `beds_available`, also capped at 10; the geographic component contributes 10 points when the center's `region_code` equals the applicant's `home_region_code` and nothing otherwise. The score is the trade component weighted by 0.5, plus the capacity component weighted by 0.3, plus the geographic component weighted by 0.2 — that is, one-half of the trade component, three-tenths of the capacity component, and one-fifth of the geographic component summed together — rounded half-up to two decimal places. Candidates are ranked by score descending; ties fall to `beds_available` descending; remaining ties fall to the center's `created_at` ascending — never to the center's `id`. The rank-1 center wins.

A successful run writes the winner into the applicant's `assigned_center_id`, moves `assignment_status` from `NONE` to `ASSIGNED`, advances the applicant's `version` by 1, and returns the updated `assignment_status`, the `assigned_center_id`, the winning `assigned_center_score`, and the full `ranked_candidates` list. Running assignment again while the applicant is `ASSIGNED` is a legitimate supersede — the new winner overwrites the old and the version advances again, with the stale-view guard of §2.6 as the only protection. A former enrollee whose `assignment_status` has become `RELEASED` may likewise be re-armed to `ASSIGNED` by a fresh assignment run. From `ENROLLED`, however, assignment is undefined and is rejected with `ERR_INVALID_STATE`; an actively enrolled student is not reassigned.

### 3.3. Enrollment, Seats, and the Two State Axes

An `EnrollmentManager` turns an assigned applicant into a student by creating an enrollment with `applicant_id`, `trade_program_id`, and `residential_track`. Three gates guard the create, in the pipeline order of §2.7. The applicant must currently hold `assignment_status` equal to `ASSIGNED`, else `ERR_APPLICANT_NOT_ELIGIBLE`. The chosen program's center must be the applicant's `assigned_center_id`, else `ERR_CENTER_MISMATCH`. And the program's `status` must be `OPEN` — a `FULL` or `CLOSED` program rejects the create with `ERR_PROGRAM_NOT_OPEN`.

Prerequisites decide where the new enrollment lands on the training axis. When the program's `required_credential_types` is empty, or every listed type is already held `VERIFIED` for this applicant, the enrollment opens in `TRAINING`. A credential counts toward this gate when it belongs to an enrollment of the same applicant and its own status is `VERIFIED`; a first-time applicant therefore holds none. When some required type is missing and the program's `supports_remediation` is true, the enrollment opens in `REMEDIATION` instead; when the program does not support remediation, the create is rejected with `ERR_PREREQUISITE_NOT_MET`.

Either way, creation consumes a seat: `enrolled_count` rises by 1, `open_seats` falls by 1, and a program whose `open_seats` reaches 0 flips from `OPEN` to `FULL`. The applicant's `assignment_status` becomes `ENROLLED`. The enrollment carries two state dimensions that evolve independently: `training_status` on the training axis and `residential_status` on the residential axis. On the residential axis, a `residential_track` enrollment opens in `AWAITING_BED`, while a non-residential one stays `NONRESIDENTIAL`. Enrollments can be listed with `applicant_id`, `trade_program_id`, `center_id`, and `training_status` filters, and fetched individually with both state dimensions and the current `conduct_hold` visible.

From `REMEDIATION`, the begin-training action advances the enrollment to `TRAINING` once every required credential type is held `VERIFIED` on credentials of this enrollment — at this gate the prerequisite is evaluated against the enrollment's own credential records, not merely the applicant's historical ones. The same advance happens automatically the moment a verification completes the set (§3.5). When the set is incomplete, begin-training fails with `ERR_PREREQUISITE_NOT_MET`.

Completion moves `TRAINING` to `COMPLETED` and carries two gates: the enrollment's `conduct_hold` must be false (a live hold rejects with `ERR_CONDUCT_HOLD`), and every required credential type must be held `VERIFIED` for this enrollment (else `ERR_PREREQUISITE_NOT_MET`). A completion stamps `exit_date` with the logical-clock date, releases the seat (enrolled count down by one, a `FULL` program flipping back to `OPEN`), terminates the enrollment's `ACTIVE` dormitory rows with the clock date as their move-out, flips the applicant's `assignment_status` to `RELEASED` with `assigned_center_id` kept for audit, and auto-creates the student's transition plan (§3.7) — when a completed work placement flagged `converted_to_hire` exists for the enrollment, the plan's job track initializes already `COMPLETED` with `job_starting_wage_cents` taken from the placement's `hire_wage_cents`, and otherwise all three tracks start `PENDING`.

Two other terminal exits exist from either `REMEDIATION` or `TRAINING`. Unenrolling with a `reason` lands the enrollment in `UNENROLLED`: it stamps `exit_date` and `exit_reason`, releases the seat with the same `FULL`-to-`OPEN` flip, terminates active dormitory rows the same way, flips the applicant to `RELEASED` — and creates no transition plan. Separating with a `reason` lands the enrollment in `SEPARATED` with identical seat, dormitory, and applicant effects, but it does auto-create the transition plan under the same hire-inheritance rule as completion. Once an enrollment is in `COMPLETED`, `UNENROLLED`, or `SEPARATED`, its training axis is terminal and any further training-axis action fails with `ERR_ALREADY_TERMINAL`; the residential axis settles to `RELEASED` at the same moment from whichever of `AWAITING_BED`, `RESIDENT`, or `NONRESIDENTIAL` it occupied.

### 3.4. Beds, Conduct, and the Separation Cascade

Residential life begins when a `ResidentialAdvisor` assigns a bed to an enrollment that is waiting for one. The create carries `enrollment_id`, a `move_in_date`, and optionally a `bed_label`. Valid bed labels run from `B-01` up to `B-NN`, zero-padded to two digits, where NN is the center's `total_beds`; a label outside that range is a shape-level `ERR_INVALID_REQUEST`. When `bed_label` is omitted, the server auto-selects the lowest-numbered free bed label in ascending label order, and if every bed of the center is occupied the create fails with `ERR_NO_BED_AVAILABLE`. An explicit `bed_label` instead triggers an overlap check: occupancy intervals are half-open, running from `move_in_date` up to but not including `move_out_date`, so an existing `ACTIVE` assignment on the same center and bed conflicts exactly when its `move_out_date` is null (open-ended) or the new `move_in_date` falls before that existing move-out — while a new move-in exactly equal to the existing move-out is adjacency and is allowed. A colliding request is rejected with `ERR_BED_OVERLAP`. A live `conduct_hold` on the enrollment blocks the create outright with `ERR_CONDUCT_HOLD`. A successful assignment starts `ACTIVE` with `move_out_date` null, moves the enrollment's residential axis from `AWAITING_BED` to `RESIDENT`, and recomputes the center's `beds_in_use`, keeping the invariant that `beds_in_use` plus `beds_available` equals `total_beds`.

Checkout is the compensating action for an assignment: the advisor supplies a `move_out_date` that must not fall before the `move_in_date`, the assignment settles to `CHECKED_OUT`, the freed bed returns to the pool as `beds_available` rises by one, and the enrollment's residential axis moves from `RESIDENT` to `RELEASED`. Separately, whenever an enrollment reaches a terminal training state, each of its still-`ACTIVE` assignments is terminated by the system with `move_out_date` set to the clock date and `status` set to `TERMINATED`, the bed pool is recomputed again, and the residential axis settles to `RELEASED`; rows already `CHECKED_OUT` are untouched by this cascade. Both `CHECKED_OUT` and `TERMINATED` are terminal.

Conduct runs in parallel. An advisor reports an incident with `enrollment_id`, an `infraction_code` drawn from `CURFEW_VIOLATION`, `THEFT`, `VIOLENCE`, `DRUGS`, `WEAPONS`, and `OTHER`, the `occurred_at` date, and an optional `note`. The system derives `zero_tolerance` at report time: it is true exactly for `VIOLENCE`, `DRUGS`, and `WEAPONS`. The incident opens `REPORTED`, and beginning the investigation moves it to `INVESTIGATING`. From there an advisor may dismiss it (optionally with a `note`), landing in `DISMISSED`; sanction it with `sanction_points` between 1 and 5 inclusive, landing in `SANCTIONED`; or refer it to the conduct board, landing in `BOARD_REVIEW`. A zero-tolerance incident may not be sanctioned directly — the sanction action on it is rejected with `ERR_ZERO_TOLERANCE_BOARD_REQUIRED`, and only the board path may proceed. From `BOARD_REVIEW` the board either exonerates the student (`EXONERATED`) or orders separation (`SEPARATION_ORDERED`). All four of `DISMISSED`, `SANCTIONED`, `EXONERATED`, and `SEPARATION_ORDERED` are terminal.

The enrollment's `conduct_hold` is recomputed after every incident transition and on any read. A rolling window opens 90 days before the logical clock date; the enrollment's rolling points are the sum of `sanction_points` over its own incidents in `SANCTIONED` whose `occurred_at` falls inside the window, with the window inclusive at both ends as a date comparison. The hold is on whenever any incident of the enrollment sits in `BOARD_REVIEW`, or whenever the rolling points reach at least 10 — exactly 10 points activates the hold. While the hold is on, four kinds of writes are gated with `ERR_CONDUCT_HOLD`: recording a credential, proposing or activating a work placement, creating a dormitory assignment, and completing training.

A board-ordered separation fires the deepest cascade in the system. First the owning enrollment's training axis moves to `SEPARATED`, with `exit_date` set to the clock date and `exit_reason` set to `CONDUCT_BOARD`. That enrollment mutation releases the program seat — enrolled count down by one, with the `FULL`-to-`OPEN` flip when the program had been full — and terminates the enrollment's `ACTIVE` dormitory assignments with the clock date as move-out, which in turn recomputes the center's `beds_in_use` and `beds_available`. The same mutation auto-creates the student's transition plan with all three service tracks `PENDING`.

### 3.5. Credential Attainment and Remediation

A `CareerInstructor` records attainment by creating a credential with `enrollment_id`, a `credential_type` of `HSE`, `INDUSTRY_CERT`, or `DRIVER_LICENSE`, and a `subject_area` that is required when the type is `INDUSTRY_CERT` and optional otherwise. A live `conduct_hold` on the enrollment blocks the create with `ERR_CONDUCT_HOLD`. The credential opens `EARNED` with `earned_at` stamped from the logical-clock date.

Verification moves a credential from `EARNED` to `VERIFIED` and stamps `verified_at` with the clock date. Verification is also the trigger for remediation graduation: when the credential's owning enrollment sits in `REMEDIATION` and this verification completes the set — every entry of the program's `required_credential_types` now held `VERIFIED` on this enrollment's own credentials — the enrollment auto-advances from `REMEDIATION` to `TRAINING` without a separate manager action. Revocation moves a `VERIFIED` credential to `REVOKED`, which is terminal; revocation deliberately does not demote an enrollment already in `TRAINING`, because prerequisites are evaluated only at the gates that demand them — enrollment creation, begin-training, and completion.

### 3.6. Work-Based Learning Placements

Work-based learning runs under employer agreements that an `OperatorAdmin` establishes with `employer_name`, a covered `trade_code`, an operating `region_code`, a `slot_count` of at least 1 capping concurrent active placements, an `hourly_wage_floor_cents` greater than 0, and an inclusive effective window from `effective_start` to `effective_end`. The agreement's `status` is never stored; it reads `ACTIVE` while the logical clock date lies inside that inclusive window and `EXPIRED` once the clock passes `effective_end`, and it is re-derived on every read.

A `TransitionSpecialist` proposes a placement with `enrollment_id`, `employer_agreement_id`, `supervisor_id`, and `hourly_wage_cents`; the placement opens `PROPOSED`. Two business guards run at proposal: the offered wage must not fall below the agreement's `hourly_wage_floor_cents` (a lower offer is rejected with `ERR_WAGE_BELOW_FLOOR`), and a live `conduct_hold` blocks the proposal with `ERR_CONDUCT_HOLD`. The agreement must also read `ACTIVE`, both at proposal and again at activation; an expired agreement rejects either step with `ERR_AGREEMENT_INACTIVE`.

Activation moves `PROPOSED` to `ACTIVE` under three concurrency-sensitive ceilings: the count of concurrent `ACTIVE` placements under the same agreement must remain below its `slot_count` (else `ERR_WBL_SLOT_EXCEEDED`), the count of concurrent `ACTIVE` placements sharing the placement's `supervisor_id` must remain below 3 (else `ERR_SUPERVISION_OVERLOAD`), and the enrollment's `conduct_hold` must be false. A successful activation stamps `start_date` with the clock date.

While `ACTIVE`, the specialist records hours against the placement. Each entry carries a `work_date`, an `hours` total between 1 and 10 inclusive, and an optional `verified` flag. The work date must not fall before the placement's `start_date`, must not lie after the logical clock date, and must be unique within the placement — a second entry for the same date is rejected. All three violations surface as `ERR_INVALID_REQUEST`. Entries are processed in ascending `work_date` order and feed two running totals: `verified_hours_total`, the sum over entries flagged verified, and `provisional_hours_total`, the sum over all entries regardless of flag. These are the ACTUAL and PROVISIONAL variants of the same credit calculation — identical inputs always yield a provisional total at least as large as the actual total — and the actual total is the one that feeds the completion gate and the performance inputs of §3.8.

Completion moves `ACTIVE` to `COMPLETED` and demands at least 120 hours in `verified_hours_total`. The action accepts `converted_to_hire` and `hire_wage_cents`; the hire wage is required whenever conversion to hire is claimed, and both are stored on the placement. Completion frees one agreement slot and one supervision slot, and — as described in §3.3 — a completed placement with `converted_to_hire` set is what later initializes the job track of the student's auto-created transition plan. Termination moves either `PROPOSED` or `ACTIVE` to `TERMINATED`, accepts an optional `termination_reason`, and frees one agreement slot and one supervision slot when the placement had been active; the system applies the same termination to `ACTIVE` placements when the owning enrollment reaches a terminal training state. Both `COMPLETED` and `TERMINATED` are terminal.

### 3.7. Transition Plans and Post-Separation Services

Every student who completes or separates leaves with a transition plan, created automatically by the terminal enrollment transition and linked one-to-one to that enrollment through its `enrollment_id`; unenrollment creates none. The plan records the `separation_date` as the logical-clock date the enrollment went terminal and sets `expires_at` twelve months after that date, which is when the service window closes. Fetching a student's plan returns an array of zero or one entries — zero while the enrollment is still active or exited via unenrollment.

The plan carries three independent service tracks, `job_placement_status`, `housing_status`, and `transportation_status`, each moving from `PENDING` to either `COMPLETED` or `WAIVED`. The hire-inheritance rule of §3.3 may initialize the job track already `COMPLETED` with `job_starting_wage_cents` populated from the placement's `hire_wage_cents`; every other track starts `PENDING`. The plan's overall `status` is computed on read, never stored: `COMPLETED` once all three tracks sit in `COMPLETED` or `WAIVED`; otherwise `EXPIRED` once the logical clock date passes `expires_at` while any track is still `PENDING`; otherwise `ACTIVE`. When both readings would apply, `COMPLETED` wins over `EXPIRED`, and the status is re-evaluated on every track mutation.

A `TransitionSpecialist` records service outcomes against the plan by naming a `service_type` of `JOB_PLACEMENT`, `HOUSING`, or `TRANSPORTATION` and an `outcome` of `COMPLETED` or `WAIVED`. A completed job placement stores the verified wage, supplied as `starting_wage_cents`, into `job_starting_wage_cents`. A completed housing track entitles the plan to a flat 50000-cent stipend: `housing_stipend_cents` reads 50000 once the track is `COMPLETED` and 0 before. A completed transportation track entitles the plan to a tiered allowance from the supplied `distance_miles`: no more than 25 miles pays 2500 cents, more than 25 but no more than 100 miles pays 7500 cents, and anything beyond 100 miles pays 15000 cents — the boundaries belong to the lower tier, so exactly 25 miles pays 2500 and exactly 100 miles pays 7500. The result surfaces as `transport_allowance_cents` once the track is `COMPLETED`, and 0 before. Recording any outcome after the window has closed — the clock date past `expires_at`, so the plan reads `EXPIRED` — is rejected with `ERR_TRANSITION_WINDOW_EXPIRED`, and on this endpoint that window check outranks the generic state check; recording against a plan already fully resolved surfaces instead as `ERR_INVALID_STATE`.

### 3.8. Operator Contracts and Performance Review

Centers are run by operating companies under contract. An `OperatorAdmin` creates a contract with `center_id`, `operator_name`, and a `contract_code` that is unique across all contracts; the contract opens `ACTIVE`, stamps `current_period_start` with the logical-clock date, and starts `period_sequence` at 1. Contract governance moves between three states: probating moves `ACTIVE` to `PROBATION`, reinstating moves `PROBATION` back to `ACTIVE` — a cycle that may repeat across review periods — and terminating from either state lands in `TERMINATED`, which is terminal.

Performance is measured over review periods. The open period runs from `current_period_start` through the logical clock date at evaluation, both ends inclusive. The cohort is the set of enrollments at the contract's center whose `exit_date` falls inside that window. Within the cohort, graduates are enrollments that reached `COMPLETED`, leavers are those that reached `SEPARATED` or `UNENROLLED`, and placed graduates are graduates whose transition plan's `job_placement_status` is `COMPLETED`.

Two variants of the same computation exist. The FINAL variant — the one persisted at period close — computes `graduation_rate` as graduates divided by the sum of graduates and leavers, rounded half-up to four decimal places, reading 0.0 when that denominator is zero. The PROVISIONAL variant — computed on demand by the preview and never persisted — additionally counts the center's still-active enrollments (those in `REMEDIATION` or `TRAINING`) as projected graduates in both the numerator and the denominator, so identical underlying data yields a different, forward-looking rate; the preview surfaces this count as `projected_actives_count`. Both variants compute `placement_rate` as placed graduates divided by graduates, rounded half-up to four decimal places, reading 0.0 when there are no graduates, and `avg_starting_wage_cents` as the mean of the placed graduates' `job_starting_wage_cents` rounded half-up to whole cents, reading 0 when none are placed.

The operator payment rides on the placed-graduate set of the evaluated cohort, and its rounding order is pinned. For each placed graduate, the wage ratio is the graduate's `job_starting_wage_cents` divided by 150000, capped at 2.0; the graduate's award is 200000 cents multiplied by that ratio, rounded half-up to whole cents immediately. The contract's `payment_cents` is then the sum of those per-graduate awards. Rounding each award first and summing second is the conforming order — two placed graduates at 149999 cents each pay 399998 cents under the pinned order but 399997 cents if the raw products were summed before a single rounding, and only the former is correct.

Closing a period is allowed only when the logical clock date is strictly later than `current_period_start` and the contract is `ACTIVE` or `PROBATION`; otherwise the close is rejected with `ERR_PERIOD_NOT_CLOSABLE`. A successful close persists a performance snapshot — always with `variant` set to `FINAL` — carrying `contract_id`, `period_start`, `period_end`, `graduates_count`, `leavers_count`, `graduation_rate`, `placement_rate`, `avg_starting_wage_cents`, and `payment_cents` for the window just closed. The close then advances `current_period_start` to the day after `period_end`, increments `period_sequence` by 1, and applies the automatic governance transitions: a persisted snapshot whose `graduation_rate` falls below 0.6, or whose cohort produced at least one graduate while its `placement_rate` falls below 0.7, moves the contract to `PROBATION`, while a snapshot meeting both floors returns a probated contract to `ACTIVE`. Persisted snapshots are listed per contract and, per §2.5, are immutable records without `updated_at` or `version`.

## 4. Endpoint Definitions

Requests that create a new resource return HTTP 201; requests that modify an existing resource, drive a state transition, run a computation, or set the clock return HTTP 200 — with one exception: closing a review period returns 201 because it persists a new performance snapshot. Request payloads, response fields, and side effects are specified in the narratives of §2 and §3; this table is only the HTTP-level index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | OperatorAdmin |
| POST | `/jc/applicants` | Create an applicant at intake | AdmissionsCounselor |
| GET | `/jc/applicants` | List applicants with optional filters | AdmissionsCounselor, EligibilityReviewer, EnrollmentManager, OperatorAdmin |
| GET | `/jc/applicants/{id}` | Fetch one applicant with assignment posture and version | AdmissionsCounselor, EligibilityReviewer, EnrollmentManager, ResidentialAdvisor, CareerInstructor, TransitionSpecialist, OperatorAdmin |
| POST | `/jc/applications` | Open an eligibility case for an applicant | AdmissionsCounselor |
| GET | `/jc/applicants/{id}/applications` | List an applicant's eligibility cases, newest first | AdmissionsCounselor, EligibilityReviewer, OperatorAdmin |
| POST | `/jc/applications/{id}/transition` | Drive the case: begin_review, request_info, provide_info, determine, appeal | AdmissionsCounselor, EligibilityReviewer |
| POST | `/jc/applicants/{id}/center-assignment` | Run the ranking selector and assign the rank-1 center | AdmissionsCounselor |
| POST | `/jc/centers` | Create a training center with its bed pool | OperatorAdmin |
| GET | `/jc/centers/{id}` | Fetch one center with computed bed fields | OperatorAdmin, AdmissionsCounselor, EnrollmentManager, ResidentialAdvisor |
| GET | `/jc/centers/{id}/operator-contracts` | List operator contracts for a center | OperatorAdmin |
| POST | `/jc/trade-programs` | Create a trade program at a center | OperatorAdmin |
| GET | `/jc/centers/{id}/trade-programs` | List a center's trade programs | OperatorAdmin, AdmissionsCounselor, EnrollmentManager |
| PATCH | `/jc/trade-programs/{id}` | Update capacity and/or status of a program | OperatorAdmin |
| POST | `/jc/enrollments` | Enroll an assigned applicant into a trade program | EnrollmentManager |
| GET | `/jc/enrollments` | List enrollments with optional filters | EnrollmentManager, OperatorAdmin, TransitionSpecialist |
| GET | `/jc/enrollments/{id}` | Fetch one enrollment with both state axes and conduct hold | AdmissionsCounselor, EligibilityReviewer, EnrollmentManager, ResidentialAdvisor, CareerInstructor, TransitionSpecialist, OperatorAdmin |
| POST | `/jc/enrollments/{id}/transition` | Training-axis actions: begin_training, complete, unenroll, separate | EnrollmentManager |
| POST | `/jc/dormitory-assignments` | Assign a dormitory bed to a resident enrollment | ResidentialAdvisor |
| GET | `/jc/enrollments/{id}/dormitory-assignments` | List dormitory assignments of an enrollment | ResidentialAdvisor, EnrollmentManager |
| POST | `/jc/dormitory-assignments/{id}/checkout` | Early release of a bed | ResidentialAdvisor |
| POST | `/jc/conduct-incidents` | Report a conduct incident against an enrollment | ResidentialAdvisor |
| GET | `/jc/enrollments/{id}/conduct-incidents` | List conduct incidents of an enrollment | ResidentialAdvisor, EnrollmentManager |
| POST | `/jc/conduct-incidents/{id}/transition` | Adjudication actions: begin_investigation, dismiss, sanction, refer_board, exonerate, separate | ResidentialAdvisor |
| POST | `/jc/credentials` | Record an earned credential for an enrollment | CareerInstructor |
| GET | `/jc/enrollments/{id}/credentials` | List credentials of an enrollment | CareerInstructor, EnrollmentManager |
| POST | `/jc/credentials/{id}/transition` | Verify or revoke a credential | CareerInstructor |
| POST | `/jc/employer-agreements` | Create an employer agreement | OperatorAdmin |
| GET | `/jc/employer-agreements/{id}` | Fetch one agreement with its clock-derived status | OperatorAdmin, TransitionSpecialist |
| GET | `/jc/employer-agreements/{id}/wbl-placements` | List placements under an agreement | OperatorAdmin, TransitionSpecialist |
| POST | `/jc/wbl-placements` | Propose a work-based learning placement | TransitionSpecialist |
| GET | `/jc/enrollments/{id}/wbl-placements` | List placements of an enrollment | TransitionSpecialist, EnrollmentManager |
| POST | `/jc/wbl-placements/{id}/transition` | Placement actions: activate, record_hours, complete, terminate | TransitionSpecialist |
| GET | `/jc/enrollments/{id}/transition-plan` | Fetch the transition plan of an enrollment (array of 0 or 1) | TransitionSpecialist, EnrollmentManager |
| POST | `/jc/transition-plans/{id}/services` | Record a transition-service outcome | TransitionSpecialist |
| POST | `/jc/operator-contracts` | Create an operator contract for a center | OperatorAdmin |
| GET | `/jc/operator-contracts/{id}` | Fetch one contract | OperatorAdmin |
| POST | `/jc/operator-contracts/{id}/transition` | Contract actions: probate, reinstate, terminate | OperatorAdmin |
| GET | `/jc/operator-contracts/{id}/performance-preview` | On-demand PROVISIONAL performance computation over the open period | OperatorAdmin |
| POST | `/jc/operator-contracts/{id}/close-period` | Close the current review period and persist the FINAL snapshot | OperatorAdmin |
| GET | `/jc/operator-contracts/{id}/performance-snapshots` | List persisted FINAL snapshots of a contract | OperatorAdmin |

## 5. Error Code Catalogue

Every error response carries one of the following identifiers in the `error_id` field of the error envelope. Trigger conditions are specified where each error naturally arises in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_CONDUCT_HOLD` | 409 |
| `ERR_ZERO_TOLERANCE_BOARD_REQUIRED` | 422 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_PREREQUISITE_NOT_MET` | 422 |
| `ERR_NO_ELIGIBLE_CENTER` | 422 |
| `ERR_BED_OVERLAP` | 409 |
| `ERR_TRANSITION_WINDOW_EXPIRED` | 422 |
| `ERR_APPLICANT_NOT_ELIGIBLE` | 409 |
| `ERR_CENTER_MISMATCH` | 422 |
| `ERR_PROGRAM_NOT_OPEN` | 409 |
| `ERR_AGREEMENT_INACTIVE` | 409 |
| `ERR_NO_BED_AVAILABLE` | 422 |
| `ERR_WBL_SLOT_EXCEEDED` | 422 |
| `ERR_SUPERVISION_OVERLOAD` | 422 |
| `ERR_WAGE_BELOW_FLOOR` | 422 |
| `ERR_PERIOD_NOT_CLOSABLE` | 409 |
