# Charity Pediatric Admission API — Product Requirements Document

## 1. Introduction

A network of charity specialty pediatric hospitals operates on a principle most healthcare systems abandoned long ago: no family ever receives a bill. This document specifies the API that runs that network — a Shriners-style system covering patient intake from community physicians, outreach clinics, and international partners; committee-based admission review conducted without any regard to a family's ability to pay; insurance billing used only to offset costs where third-party coverage genuinely exists; travel and lodging support for distant families; multi-year staged care for orthopedic and burn patients; remote outreach clinic scheduling with follow-up conversion; and the philanthropic funding that makes all of it possible.

Two commitments sit underneath every endpoint in this document, and implementers should treat them as constitutional rather than incidental. First, **acceptance is blind to means**: a family's financial capacity is recorded for statistical purposes only and must never influence, gate, or accelerate an acceptance decision. Second, **the family balance is always zero**: wherever the arithmetic of charges, insurance remittances, and write-offs would otherwise leave a residual owed by the family, the system absorbs the difference into charity write-off instead. These two principles are enforced structurally — by validation rules, by computed-field invariants, and by the settlement sweep — not by policy prose alone.

All endpoints are mounted under the `/charity-care` prefix. The system runs on a logical clock rather than wall-clock time; several workflows (clinic activation, screening expiry, annual admission counters) are driven by advancing that clock, which makes the whole API reproducible for testing and audit.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once headers are validated, the role is checked against the endpoint's authorization list; an authenticated caller whose role is not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). The header check always runs before the role check, so a caller missing headers never receives a permissions error.

The system recognizes eight roles, spelled exactly as follows: `NetworkAdmin`, `IntakeCoordinator`, `ReferringPhysician`, `ReviewCommitteeMember`, `BillingSpecialist`, `CareCoordinator`, `OutreachPlanner`, and `PhilanthropyOfficer`.

The identity semantics of `X-User-ID` differ by role, and the difference matters for ownership checks:

- When `X-User-Role` is `ReferringPhysician`, `X-User-ID` is the `id` of the acting `ReferralSource`; ownership checks on any resource that references a `ReferralSource` compare the resource's foreign-key field to `X-User-ID`. In particular, a `ReferringPhysician` submitting a patient application must supply a `referral_source_id` equal to the caller's own `X-User-ID`.
- When `X-User-Role` is `NetworkAdmin`, `IntakeCoordinator`, `ReviewCommitteeMember`, `BillingSpecialist`, `CareCoordinator`, `OutreachPlanner`, or `PhilanthropyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `info_requested_by` on a `PatientApplication` where an info-request transition writes it, or as `reviewer_user_id` on an `ApplicationReview` event — but does not compare it to any entity's `id`.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system never consults wall-clock time for business decisions. Instead, a logical clock governs every time-sensitive rule in this document: patient age computations, stage scheduling windows, clinic activation, screening expiry, and the annual admission counters. At startup, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must not fall back to wall-clock time before the first explicit clock-setting call.

A `NetworkAdmin` may advance the logical clock by supplying a `current_utc` instant. Setting the clock is not a passive read of a variable: it runs a clock-touch cascade across the network. Any outreach clinic in `CONFIRMED` status whose `start_date` has been reached transitions to `IN_PROGRESS`. Any screening in `COMPLETED` status whose parent clinic's `conversion_deadline` has passed transitions to `EXPIRED`. And when the clock crosses a calendar-year boundary (the first clock touch at or after January 1 00:00:00Z of a new year), every hospital's `admissions_ytd` is recomputed from the accepted-application set for the new current year — a true recomputation rather than a blind zeroing, so the counter stays consistent if acceptances are later inspected.

### 2.5. Common Resource Properties

All primary resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` field is an integer that increments with every modification and underpins optimistic concurrency control.

One deliberate exception: the `ApplicationReview` event log is append-only and carries only `id` and `created_at` — both `updated_at` and `version` are absent from review events, because an event, once written, never changes. Any operation that mutates a parent resource as a cascade (for example, a claim adjudication bumping its billing account) updates the parent's `updated_at` and increments its `version` as part of the same effect.

### 2.6. Monetary Values and Precision

All monetary amounts in this system are stored and transmitted as integers of whole cents — `total_charged_cents`, `insurance_paid_cents`, `charity_writeoff_cents`, `family_balance_cents`, `open_claim_cents`, `submitted_amount_cents`, `estimated_allowed_cents`, `adjudicated_amount_cents`, `amount_cents`, `allocated_cents`, `available_cents`, `total_committed_cents`, `estimated_cost_cents`, `nightly_lodging_stipend_cents`, `travel_allowance_cents`, and per-line `charge_cents` are all integer cent values. No monetary field ever carries fractional cents.

Where a calculation produces a fractional result — claim allowed amounts, road distances, allocation weights — rounding is always the round-half-up method. Distances are rounded to one decimal place; the `allocation_weight` factor is rounded to four decimal places; claim allowed amounts are rounded to whole cents. The exact placement of the rounding step matters and differs between the provisional and final variants of several calculations; those placements are pinned in §3 where each calculation is introduced.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only those two. The application-decision operation requires a non-optional `expected_application_version` field in the request body, carrying the `version` of the `PatientApplication` the committee member last observed. If the application's current `version` has advanced since then — because a vote, a resubmission, or another state-changing operation legitimately moved it — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412). The allocation-commit operation likewise requires a non-optional `expected_fund_version` matching the parent `PhilanthropicFund`'s current `version`; a mismatch — for instance because another commit or release has legitimately moved the fund's `allocated_cents` and `available_cents` — is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field at all.

### 2.8. Nested Resource Retrieval and Validation Ordering

Requests that target nested resources validate path-segment identifiers in strict left-to-right order, and the request is rejected with a 404 the moment the first nonexistent identifier is encountered. A request aimed at a screening under a nonexistent clinic therefore fails with `ERR_CLINIC_NOT_FOUND` before the screening id is ever examined. Body-supplied foreign keys are validated after path identifiers, in the endpoint's declared input order — on application creation, `referral_source_id` is checked before `program_id`, which is checked before `screening_id`. Existence failures surface as the entity-specific 404 error (`ERR_HOSPITAL_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CLINIC_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_BILLING_ACCOUNT_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_REFERRAL_SOURCE_NOT_FOUND`, or `ERR_POLICY_NOT_FOUND`).

More broadly, every request passes through a fixed validation ladder. Authentication context comes first, then role authorization, then path-segment existence, then body foreign-key existence, then state-machine legality (a transition attempted from a state that does not define it is `ERR_INVALID_STATE`, HTTP 409), then the OCC stale-version check where the endpoint declares one, and only then the business rules — condition scope, age eligibility, international routing, segregation of duties, quorum, program/hospital operational status, temporal windows, fiscal constraints, and referential integrity — each named in §3 next to the workflow it guards. Malformed request bodies (a missing required field, a type mismatch, or an out-of-enum value) fail with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Hierarchical Consistency and Cascading Effects

State changes on a parent resource propagate to its children, and the propagation is immediate — the system's consistency model is immediate, not eventual. Suspending a hospital suspends all of its `ACTIVE` programs in the same operation and cancels every `PROPOSED` outreach clinic the hospital sponsors, which in turn expires each of those clinics' `BOOKED` screenings. Reopening a hospital deliberately does not restore its programs — each program must be reactivated individually. Discharging a care plan from `ACTIVE_TREATMENT` cancels every `PLANNED` stage. Completing an outreach clinic converts its remaining `BOOKED` screenings to `NO_SHOW`. Each such cascade mutation refreshes `updated_at` and increments `version` on the affected resources.

### 2.10. The No-Means-Test and No-Family-Billing Principles

Two invariants are enforced structurally and apply across every workflow. First, the `family_ability_to_pay` field on a patient application is recorded for statistical purposes only and must never be consulted by any acceptance logic; it defaults to `DECLINED_TO_STATE` when the caller does not supply it. Second, `family_balance_cents` on every `BillingAccount` is always zero — computed as `total_charged_cents` minus `insurance_paid_cents` minus `charity_writeoff_cents` minus `open_claim_cents` — and any operation that would leave a nonzero family balance is rejected with `ERR_NO_FAMILY_BILLING_VIOLATION` (HTTP 422) and the residue swept into `charity_writeoff_cents` instead. These are not policy statements; they are validation and computation rules described where they bite in §3.

## 3. Business Logic & Workflows

### 3.1. Building the Hospital Network and Its Programs

The `NetworkAdmin` builds out the network one `SpecialtyHospital` at a time. Each hospital is registered with a unique `hospital_code` (for example, `SHC-PDX`), a `name`, a `city`, and a `state_code` that holds either a two-letter US state code or a two-letter ISO country code for international sites. Because distance-based benefits and clinic conflict detection both depend on geography, each hospital also records its `latitude` (between −90 and 90 decimal degrees) and `longitude` (between −180 and 180 decimal degrees). Every hospital declares an `annual_capacity` — the maximum number of new admissions it will accept in a calendar year, at least 1 — and begins life with `admissions_ytd` at 0 and `status` set to `OPEN`.

Within a hospital, the `NetworkAdmin` creates `SpecialtyProgram` resources. A program's `category` is one of `ORTHOPEDIC`, `BURN`, `CLEFT_CRANIOFACIAL`, `SPINAL_CORD`, or `NEUROMUSCULAR`, and this category later governs which patient conditions the program may admit. Programs declare an age window: `min_age_months` (at least 0) is the youngest patient, in whole months at application submission, the program will consider, and `max_age_months` is an exclusive upper bound — the patient must be strictly younger than `max_age_months`, and `max_age_months` must be greater than `min_age_months`. The `accepts_international` flag (default false) records whether the program takes international referrals, and `staged_care_required` (default false) marks programs — typically `ORTHOPEDIC` and `BURN` — whose accepted patients need a multi-stage care plan. New programs start `ACTIVE`.

Hospitals and programs each have an operational lifecycle. Suspending a hospital (only valid from `OPEN`) moves it to `SUSPENDED`, cascades all its `ACTIVE` programs to `SUSPENDED`, and cancels every `PROPOSED` outreach clinic it sponsors — expiring those clinics' `BOOKED` screenings along the way. A `SUSPENDED` hospital may be reopened back to `OPEN`, but its programs stay `SUSPENDED` and must be reactivated one at a time; a program reactivation is only accepted while the parent hospital is `OPEN`, otherwise it is rejected with `ERR_HOSPITAL_NOT_OPEN`. A program may also be suspended directly. Closing a hospital is terminal: it is permitted from either `OPEN` or `SUSPENDED`, but only when no `PatientApplication` in a non-terminal state (`SUBMITTED`, `PENDING_REVIEW`, or `INFO_REQUESTED`) references any of the hospital's programs; a close attempt against open applications fails with `ERR_HOSPITAL_HAS_OPEN_APPLICATIONS`. Closing from `OPEN` first suspends all `ACTIVE` programs; closing from `SUSPENDED` leaves the already-suspended programs in place so their rows remain queryable.

### 3.2. Referral Intake and the Patient Application

Patients arrive through three kinds of referral source, each registered as a `ReferralSource` by a `NetworkAdmin` or `IntakeCoordinator`: a `COMMUNITY_PHYSICIAN`, an `OUTREACH_CLINIC`, or an `INTERNATIONAL_PARTNER`. Registration captures the `source_type`, a `display_name` (physician, clinic, or partner organization name), a `contact_email`, and a two-letter `country_code`; new sources start `ACTIVE`.

An `IntakeCoordinator` — or a `ReferringPhysician` acting under their own referral-source identity — submits a `PatientApplication` carrying the `patient_full_name`, the `patient_date_of_birth` (a date at 00:00:00Z), the `condition_category`, the `referral_source_id`, the `program_id` of the program applied to, and the family's `home_latitude` and `home_longitude`. The optional `screening_id` links the application to an outreach screening when one is being converted (see §3.8), and the optional `family_ability_to_pay` records one of `UNABLE`, `PARTIAL`, `ABLE`, or `DECLINED_TO_STATE` — purely statistical, never consulted by acceptance. Two fields are derived at creation and never change afterward: `is_international`, which is true exactly when the referral source's `country_code` is not `US`, and `age_at_submission_months`, the floor of the span between the patient's date of birth and the submission date in whole months, computed against the logical clock. New applications start in `SUBMITTED` with `review_round` at 1.

Intake enforces a ladder of business checks, applied in this order after the general validation ladder of §2.8. First, condition scope: the application's `condition_category` must equal the applied program's `category`, and a `condition_category` of `OTHER` is never in scope for any program — violations are rejected with `ERR_CONDITION_OUT_OF_SCOPE` (HTTP 422). Second, age eligibility: the patient's `age_at_submission_months` must be at least the program's `min_age_months` and strictly less than its `max_age_months`, otherwise `ERR_AGE_INELIGIBLE` (HTTP 422). Third, international routing: an application whose `is_international` is true may only target a program with `accepts_international` true, otherwise `ERR_INTERNATIONAL_NOT_ACCEPTED` (HTTP 422). Finally, screening linkage integrity: when `screening_id` is supplied, it must reference a screening in `COMPLETED` status belonging to a clinic sponsored by the same hospital as the applied program, and the screening's `suspected_condition_category` must equal the application's `condition_category` — a mismatch on any of those three points is `ERR_SCREENING_MISMATCH` (HTTP 422).

### 3.3. Committee Review: Rounds, Votes, and the Decision

Committee review is a `ReviewCommitteeMember`-driven lifecycle with a deliberate cycle. Opening review moves an application from `SUBMITTED` to `PENDING_REVIEW` and appends an `ApplicationReview` event with `action` `OPEN_ROUND` and `round_number` 1. While in `PENDING_REVIEW`, any committee member may request more information, moving the application to `INFO_REQUESTED`; the acting member's `X-User-ID` is recorded on the application as `info_requested_by`, and a `REQUEST_INFO` event is appended. An `IntakeCoordinator` then supplies the requested information, returning the application to `PENDING_REVIEW`, incrementing `review_round` by 1, and appending a `RESUBMIT_INFO` event stamped with the new round number. At any point before a decision — from `SUBMITTED`, from `PENDING_REVIEW`, or from `INFO_REQUESTED` — an `IntakeCoordinator` may withdraw the application, moving it to the terminal `WITHDRAWN` state.

While the application sits in `PENDING_REVIEW`, committee members cast non-deciding votes. Each vote appends an `ApplicationReview` event whose `action` is `CAST_VOTE_ACCEPT` or `CAST_VOTE_DENY`, carrying the voter's `reviewer_user_id`, the current `round_number`, and a `vote_weight` — 1 for a regular member and 2 for the committee chair, defaulting to 1 when not supplied. Votes are scoped to the round: only votes cast under the application's current `review_round` count toward quorum.

The decision itself is rendered by a committee member supplying a `decision`, a free-text `decision_reason`, and the OCC guard `expected_application_version` described in §2.7. Decision-time checks are evaluated in a fixed order: the segregation-of-duties check first, then the quorum check, then hospital capacity, then program status. Segregation of duties bars the member who most recently requested information on the current round from casting the deciding vote — if the acting member's `X-User-ID` equals the application's `info_requested_by`, the decision is rejected with `ERR_REVIEWER_CONFLICT` (HTTP 403). Quorum is weighted and direction-locked: an `ACCEPT` decision requires the sum of `vote_weight` over this round's `CAST_VOTE_ACCEPT` events to be at least 3 with this round's deny weight at exactly 0, while a `DENY` decision requires this round's deny weight to be at least 2 with this round's accept weight at exactly 0; failing either yields `ERR_QUORUM_NOT_MET` (HTTP 409). An `ACCEPT` additionally requires the hospital's `admissions_ytd` to be strictly below its `annual_capacity` — evaluated on the pre-increment value — otherwise `ERR_HOSPITAL_CAPACITY_REACHED` (HTTP 409), and requires the applied program to be `ACTIVE`, otherwise `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409). A successful `ACCEPT` appends the deciding `CAST_VOTE_ACCEPT` event, increments the hospital's `admissions_ytd` by 1, records the `decision_reason`, auto-creates the application's `BillingAccount`, auto-creates a `CarePlan` when the program has `staged_care_required`, and converts the linked screening if `screening_id` is set. A successful `DENY` appends the deciding `CAST_VOTE_DENY` event and records the `decision_reason`. Both outcomes are terminal.

The full review history of an application — every `OPEN_ROUND`, `REQUEST_INFO`, `RESUBMIT_INFO`, `CAST_VOTE_ACCEPT`, and `CAST_VOTE_DENY` event — remains queryable, filterable by `round_number`, as an append-only log.

### 3.4. Insurance Policies and the Billing Account

An `IntakeCoordinator` or `BillingSpecialist` may attach an `InsurancePolicy` to an application at any time, supplying the `payer_name`, the `policy_number`, and a `coverage_exists` flag. A policy starts `VERIFIED` and may later lapse to `LAPSED`; when `coverage_exists` is false, the policy is informational only — it records that the family reported no third-party coverage — and no claims may be filed against it. Attaching a policy never gates, delays, or influences acceptance.

The `BillingAccount` springs into existence automatically the moment an application is accepted — exactly one account per accepted application, created with `status` `OPEN` and all four balances (`total_charged_cents`, `insurance_paid_cents`, `charity_writeoff_cents`, `open_claim_cents`) at 0. If the application has an `InsurancePolicy` with `coverage_exists` true, that policy's id is linked as the account's `insurance_policy_id`; otherwise the field is null and the account belongs to an uninsured patient. The account's `family_balance_cents` is a derived invariant: it always equals the total charged minus insurance paid minus charity write-offs minus open claims, which the system's write-off rules keep pinned at 0.

### 3.5. Claims: Provisional Estimates, Final Adjudication, and Write-Offs

A `BillingSpecialist` files a `Claim` against a billing account — the claim records the account's id as its `billing_account_id` — by supplying the `service_date` and a non-empty `lines` array, each line pairing a `cpt_code` with a `charge_cents` of at least 1. Claim submission requires the account's `insurance_policy_id` to reference a policy with `coverage_exists` true and status `VERIFIED`; without billable coverage the submission is rejected with `ERR_NO_BILLABLE_COVERAGE` (HTTP 409). On creation, the claim's `submitted_amount_cents` is the plain integer sum of its lines' `charge_cents`, and its `estimated_allowed_cents` is computed by the **provisional variant**: each line's charge is multiplied by the estimated rate of 0.62, each per-line product is rounded half-up to whole cents, and the rounded per-line amounts are then summed. Submission also adds the `submitted_amount_cents` to the account's `open_claim_cents` and bumps the account's `version`.

Adjudication applies the **final variant** and is where the two variants deliberately diverge. When a `BillingSpecialist` adjudicates a `SUBMITTED` claim — again requiring the account's linked policy to exist with `coverage_exists` true and status `VERIFIED`, else `ERR_NO_BILLABLE_COVERAGE` — the system sums all line charges first, multiplies the summed total once by the contract rate of 0.60, and rounds the result half-up to whole cents exactly once, storing it as `adjudicated_amount_cents`, and the claim moves to the terminal `ADJUDICATED` state. Because the provisional variant rounds per line and the final variant rounds once at the end, the two integers disagree whenever the claim carries two or more lines whose charges do not divide evenly against the two rates. Adjudication then settles the account: `open_claim_cents` decreases by `submitted_amount_cents`, `insurance_paid_cents` increases by `adjudicated_amount_cents`, and the uncompensated remainder — `submitted_amount_cents` minus `adjudicated_amount_cents` — is always added to `charity_writeoff_cents`, keeping `family_balance_cents` at 0.

A claim may instead be denied outright, moving it from `SUBMITTED` to the terminal `DENIED_CLAIM` state. Denial removes the full `submitted_amount_cents` from `open_claim_cents` and adds that entire amount to `charity_writeoff_cents` — a denied claim is fully absorbed by charity. Either way, once no `SUBMITTED` claims remain, the account's `open_claim_cents` reads 0 and a `BillingSpecialist` may settle the account. Settlement is blocked while any claim is still open (`ERR_OPEN_CLAIMS_EXIST`, HTTP 409); when it proceeds, the settle recomputes `family_balance_cents`, sweeps any nonzero residue into `charity_writeoff_cents` before storing — the no-balance-billing invariant's final enforcement — and moves the account to the terminal `SETTLED` state.

### 3.6. Care Continuity: Care Plans and Staged Procedures

Acceptance into a program with `staged_care_required` creates a `CarePlan` for the application — exactly one per such application — holding a `diagnosis_summary` and tracking two independent status dimensions carried on the fields `clinical_status` and `funding_status`. The clinical dimension moves `PLANNING` → `ACTIVE_TREATMENT` → `SURVEILLANCE` → `DISCHARGED`; the funding dimension moves among `UNFUNDED`, `PARTIALLY_FUNDED`, and `FULLY_FUNDED` as philanthropic designations land (see §3.9). The plan records a `planned_stage_count` (at least 1) and a computed `completed_stage_count` starting at 0.

A `CareCoordinator` populates the plan with `StagedProcedure` resources, each carrying a 1-based `stage_index` unique within the plan and no greater than `planned_stage_count`, an age window (`min_age_months` inclusive, `max_age_months` exclusive, with the maximum greater than the minimum), a `scheduled_date`, and an `estimated_cost_cents` of at least 1. Adding a stage recomputes the plan's funding position because the remaining-need figure has changed. New stages are `PLANNED`.

Scheduling a stage is the gated step. A `PLANNED` stage may move to `SCHEDULED` only while the plan's clinical status is `PLANNING` or `ACTIVE_TREATMENT`; only when the patient's age at the `scheduled_date` — derived from the parent application's `patient_date_of_birth` — falls within the stage's window (at least `min_age_months`, strictly less than `max_age_months`), else `ERR_AGE_WINDOW_VIOLATION` (HTTP 422); only when the `scheduled_date` is not before the logical clock's current date, else `ERR_STAGE_IN_PAST` (HTTP 422); and only when no other stage of the same plan is already `SCHEDULED` — one stage in flight at a time — else `ERR_STAGE_ALREADY_IN_FLIGHT` (HTTP 409). Scheduling the plan's very first stage moves the plan from `PLANNING` to `ACTIVE_TREATMENT` automatically.

Once the logical clock reaches the `scheduled_date`, a `CareCoordinator` may complete the stage (completing early fails with `ERR_STAGE_NOT_DUE`, HTTP 409), incrementing `completed_stage_count`; when the completed count reaches `planned_stage_count`, the plan advances automatically from `ACTIVE_TREATMENT` to `SURVEILLANCE`. A scheduled stage may instead be deferred to `DEFERRED`, and a deferred stage may be replanned back to `PLANNED` by supplying a `new_scheduled_date` — which re-checks the same age window against the new date (failing again with `ERR_AGE_WINDOW_VIOLATION`) and rewrites `scheduled_date`. A `PLANNED` stage may also be cancelled outright to `CANCELLED_STAGE`; cancellation contracts the plan by decrementing `planned_stage_count`, and if the completed count now equals the reduced planned count while the plan is in `ACTIVE_TREATMENT`, the plan advances to `SURVEILLANCE` at that moment.

Discharge is a `CareCoordinator` action with two entry points. From `SURVEILLANCE`, the plan may be discharged provided its funding dimension is not `PARTIALLY_FUNDED` — a plan holding a partial designation cannot close until its allocations resolve to `COMMITTED` or are withdrawn, else `ERR_PLAN_FUNDING_UNRESOLVED` (HTTP 409). From `ACTIVE_TREATMENT`, discharge additionally requires that no stage is currently `SCHEDULED` (`ERR_STAGES_IN_FLIGHT`, HTTP 409), and it cascades: every remaining `PLANNED` stage moves to `CANCELLED_STAGE`. `DISCHARGED` is the clinical dimension's terminal state; the funding dimension has no terminal.

### 3.7. Travel and Lodging Support

For an `ACCEPTED` application, a `CareCoordinator` may create a `TravelSupportGrant` by naming a `grant_type` of `TRAVEL`, `LODGING`, or `TRAVEL_AND_LODGING`. Grant creation runs a two-variant distance computation. The provisional reading, `straight_line_distance_miles`, is the haversine distance between the family's `home_latitude`/`home_longitude` and the hospital of the applied program, using an earth radius of 3958.8 miles and rounded to one decimal half-up — it is used for display and preliminary screening only, never for eligibility. The final reading, `road_distance_miles`, multiplies the straight-line distance by a road circuity factor of 1.3 and rounds to one decimal half-up. The two variants genuinely disagree for families whose straight-line distance falls between 76.9 miles inclusive and 100.0 miles exclusive: ineligible on the provisional reading, eligible on the final.

Eligibility is decided on the road distance alone: `distance_eligible` is true exactly when `road_distance_miles` is at least 100.0 miles — the boundary is inclusive, so a family at exactly 100.0 road miles qualifies. When a grant is not distance-eligible, both money fields are 0. Otherwise the benefit splits by grant type. The `nightly_lodging_stipend_cents` applies only to `LODGING` and `TRAVEL_AND_LODGING` grants: 15000 cents per night when the road distance is at least 100.0 and strictly below 300.0 miles, and 22500 cents per night when the road distance is at least 300.0 miles. The `travel_allowance_cents` applies only to `TRAVEL` and `TRAVEL_AND_LODGING` grants: 58 cents per road mile, with the road distance rounded to the nearest whole mile first, and the product capped at 100000 cents. Grants begin `ACTIVE` and may later be `EXHAUSTED` or `REVOKED`.

### 3.8. Outreach Clinics and Screening Conversion

An `OutreachPlanner` proposes an `OutreachClinic` under a sponsoring hospital, supplying a `location_name`, the clinic's `latitude` and `longitude`, a `start_date` and `end_date` (the clinic occupies the closed interval from start through end, and `end_date` must not precede `start_date`), and a `screening_capacity` of at least 1 — the maximum number of screenings bookable across the whole clinic. Creation fixes the clinic's `conversion_deadline` at 90 days after `end_date`, initializes `booked_screening_count` to 0, and sets status `PROPOSED`.

Confirming a clinic runs a network-wide conflict check: no other clinic of any hospital, itself in `CONFIRMED` or `IN_PROGRESS` status, may sit within 25.0 miles (haversine) of this clinic's coordinates with an overlapping padded interval — two clinics conflict unless one's `end_date` plus a 7-day buffer falls strictly before the other's `start_date`, so intervals padded by 7 days on the end side must not interleave, and a violation is rejected with `ERR_CLINIC_LOCATION_CONFLICT` (HTTP 409). Clinics still `PROPOSED` or already terminal never conflict. Confirming also requires the sponsoring hospital to be `OPEN`, else `ERR_HOSPITAL_NOT_OPEN`. A confirmed clinic transitions automatically to `IN_PROGRESS` when the logical clock reaches its `start_date`. After the clock passes the clinic's `end_date`, the planner may complete it (completing while the clock is still on or before `end_date` fails with `ERR_CLINIC_STILL_RUNNING`, HTTP 409), which moves every remaining `BOOKED` screening to `NO_SHOW`. A clinic may be cancelled from `PROPOSED` or `CONFIRMED` to the terminal `CANCELLED_CLINIC` state, moving its `BOOKED` screenings to `EXPIRED`.

Screenings are booked against a clinic with the screened patient's `patient_full_name`, `patient_date_of_birth`, `suspected_condition_category`, and a `screening_date` that must fall inside the clinic's closed interval — a date outside the interval is rejected with `ERR_SCREENING_DATE_OUTSIDE_CLINIC` (HTTP 409). Booking also requires the clinic's sponsoring hospital to be `OPEN`; booking against a suspended or closed hospital's clinic is rejected with `ERR_HOSPITAL_NOT_OPEN`. Booking consumes capacity: if the clinic's `booked_screening_count` already equals its `screening_capacity`, the booking fails with `ERR_CLINIC_CAPACITY_REACHED` (HTTP 409). Each booking increments `booked_screening_count` and starts the screening in `BOOKED`. Once the clinic is `IN_PROGRESS`, the planner records the outcome, moving a `BOOKED` screening to `COMPLETED` (recording an outcome before the clinic is in progress fails with `ERR_CLINIC_NOT_IN_PROGRESS`). A `BOOKED` screening may instead be marked `NO_SHOW`, which releases its capacity slot by decrementing `booked_screening_count`. A `NO_SHOW` screening may be rebooked back to `BOOKED` with a `new_screening_date` inside the clinic interval, provided the parent clinic is `CONFIRMED` or `IN_PROGRESS` and the capacity check passes again — another booking may have taken the released slot, in which case rebooking fails with `ERR_CLINIC_CAPACITY_REACHED`.

Conversion is the payoff. When a `PatientApplication` carrying a `screening_id` is accepted, the linked screening — which must be in `COMPLETED` status — transitions automatically to `CONVERTED` and records the new application's id as `converted_application_id`, provided the logical clock has not passed the parent clinic's `conversion_deadline`; conversion at exactly the deadline succeeds, while a conversion attempt past the deadline fails with `ERR_CONVERSION_WINDOW_CLOSED` (HTTP 409). Separately, on any clock touch where the logical clock has passed a clinic's `conversion_deadline`, every still-`COMPLETED` screening of that clinic expires to `EXPIRED`.

### 3.9. Philanthropic Funds and Allocation Waterfall

The money behind all of this is administered by `PhilanthropyOfficer` users. A `PhilanthropicFund` is created with a `fund_name`, a `fiscal_year`, and a `total_committed_cents` of at least 0; it starts `OPEN` with `allocated_cents` at 0 and `available_cents` equal to `total_committed_cents`. At all times the invariant `allocated_cents` plus `available_cents` equals `total_committed_cents` holds. A fund may be locked — no new commits while `LOCKED` — and unlocked again; a locked fund may be closed, but only when no allocation is still `PLEDGED` (`ERR_PLEDGED_ALLOCATIONS_EXIST`, HTTP 409), at which point `COMMITTED` allocations stay on the books as historical records and the fund becomes read-only.

Allocations begin as pledges. An officer pledges a `FundAllocation` against a fund by naming the receiving `hospital_id` and an `amount_cents` of at least 1, optionally restricting the gift with a `program_id`, or designating it to a specific patient's course of care with a `care_plan_id` (both optional and null by default; a null `program_id` means hospital-general). Pledging changes no fund balances. Committing the pledge is the consequential step, guarded by the `expected_fund_version` OCC rule of §2.7. A commit requires the allocation to be `PLEDGED` and the parent fund to be `OPEN` (`ERR_FUND_NOT_OPEN`, HTTP 409), and requires the fund's `available_cents` to be at least the allocation's `amount_cents` — equality commits cleanly and leaves `available_cents` at exactly 0, while a shortfall is rejected with `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 402).

At commit time the system computes and stores the allocation's `allocation_weight`, rounded to four decimal places half-up, following a pinned evaluation order: first snapshot the receiving hospital's `admissions_ytd` and `annual_capacity` before this commit touches anything, then compute the weight from that snapshot, then apply the balance mutation. The weight starts from a base of 1.0, is multiplied by 1.5 when a `program_id` is present, multiplied by 2.0 when a `care_plan_id` is present, and multiplied by 1.25 when the receiving hospital's `admissions_ytd` is less than half of its `annual_capacity` (the capacity-strain factor, measured from the pre-commit snapshot). The commit then adds `amount_cents` to the fund's `allocated_cents`, subtracts it from `available_cents`, and bumps the fund's `version`.

A pledged allocation may instead be withdrawn to the terminal `WITHDRAWN` state with no fund impact. A committed allocation may be released back to the fund — the compensating action, moving the allocation to the terminal `RELEASED` state — provided that, when it designates a care plan, that plan is not in `ACTIVE_TREATMENT` with a `SCHEDULED` stage (releasing mid-flight would strand a patient, so the release fails with `ERR_PLAN_HAS_STAGE_IN_FLIGHT`, HTTP 409). Release subtracts `amount_cents` from `allocated_cents`, adds it back to `available_cents`, and bumps the fund's `version`.

Whenever an allocation naming a `care_plan_id` is committed or released, the designated plan's funding dimension is recomputed. Let the designated amount be the sum of `amount_cents` over `COMMITTED` allocations naming the plan, and let the remaining need be the sum of `estimated_cost_cents` over the plan's stages in `PLANNED`, `SCHEDULED`, or `DEFERRED` status. The plan is `UNFUNDED` when the designated amount is 0; `FULLY_FUNDED` when the designated amount is at least the remaining need and the remaining need is above 0 — and also when the remaining need has fallen to 0 (all stages terminal) while designated funds remain; and `PARTIALLY_FUNDED` when the designated amount is above 0 but below the remaining need. Stage additions, completions, and cancellations change the remaining-need figure and likewise trigger the recompute, so a plan can drift from `FULLY_FUNDED` back to `PARTIALLY_FUNDED` when a release lands or the stage list grows.

## 4. Endpoint Definitions

Operations that create a new resource (a hospital, program, referral source, application, insurance policy, claim, staged procedure, travel grant, clinic, screening, fund, or allocation) return `201 Created`. Operations that modify an existing resource — every lifecycle action, vote, decision, adjudication, settlement, and the clock-setting call — return `200 OK`. All endpoints are mounted under the `/charity-care` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/charity-care/_clock/set_current_utc` | Set the logical clock; runs clock-touch side effects | NetworkAdmin |
| POST | `/charity-care/hospitals` | Create a specialty hospital | NetworkAdmin |
| GET | `/charity-care/hospitals` | List hospitals (filterable by `status`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| GET | `/charity-care/hospitals/{hospitalId}` | Get one hospital | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| POST | `/charity-care/hospitals/{hospitalId}/suspend` | Suspend a hospital (cascades to programs and proposed clinics) | NetworkAdmin |
| POST | `/charity-care/hospitals/{hospitalId}/reopen` | Reopen a suspended hospital (programs stay suspended) | NetworkAdmin |
| POST | `/charity-care/hospitals/{hospitalId}/close` | Close a hospital (terminal; blocked by open applications) | NetworkAdmin |
| POST | `/charity-care/hospitals/{id}/programs` | Create a specialty program within a hospital | NetworkAdmin |
| GET | `/charity-care/hospitals/{id}/programs` | List programs of a hospital (filterable by `category`, `status`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| GET | `/charity-care/programs/{programId}` | Get one program | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| POST | `/charity-care/programs/{programId}/suspend` | Suspend a program | NetworkAdmin |
| POST | `/charity-care/programs/{programId}/reactivate` | Reactivate a program (requires hospital OPEN) | NetworkAdmin |
| POST | `/charity-care/referral-sources` | Register a referral source | NetworkAdmin, IntakeCoordinator |
| GET | `/charity-care/referral-sources` | List referral sources (filterable by `source_type`, `country_code`, `status`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| GET | `/charity-care/referral-sources/{sourceId}` | Get one referral source | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer, ReferringPhysician |
| POST | `/charity-care/applications` | Submit a patient application | IntakeCoordinator, ReferringPhysician |
| GET | `/charity-care/applications` | List applications (filterable by `program_id`, `referral_source_id`, `screening_id`, `status`, `condition_category`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer |
| GET | `/charity-care/applications/{applicationId}` | Get one application | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator, OutreachPlanner, PhilanthropyOfficer |
| POST | `/charity-care/applications/{applicationId}/open-review` | Open committee review round 1 | ReviewCommitteeMember |
| POST | `/charity-care/applications/{applicationId}/request-info` | Request more information (cycles out of review) | ReviewCommitteeMember |
| POST | `/charity-care/applications/{applicationId}/resubmit-info` | Supply requested info; round increments | IntakeCoordinator |
| POST | `/charity-care/applications/{applicationId}/vote` | Cast a non-deciding committee vote on the current round | ReviewCommitteeMember |
| POST | `/charity-care/applications/{applicationId}/decide` | Render the acceptance decision (OCC-guarded) | ReviewCommitteeMember |
| POST | `/charity-care/applications/{applicationId}/withdraw` | Withdraw a non-terminal application | IntakeCoordinator |
| GET | `/charity-care/applications/{id}/reviews` | List the append-only review events of an application (filterable by `round_number`) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember |
| POST | `/charity-care/applications/{id}/insurance-policies` | Attach an insurance policy to an application | IntakeCoordinator, BillingSpecialist |
| GET | `/charity-care/applications/{id}/insurance-policies` | List insurance policies of an application | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, BillingSpecialist, CareCoordinator |
| GET | `/charity-care/insurance-policies/{policyId}` | Get one insurance policy | NetworkAdmin, IntakeCoordinator, BillingSpecialist, CareCoordinator |
| GET | `/charity-care/applications/{id}/billing-account` | Get the billing account of an application (array of 0 or 1) | NetworkAdmin, BillingSpecialist, CareCoordinator |
| GET | `/charity-care/billing-accounts` | List billing accounts (filterable by `application_id`, `insurance_policy_id`, `status`) | NetworkAdmin, BillingSpecialist, CareCoordinator |
| GET | `/charity-care/billing-accounts/{accountId}` | Get one billing account | NetworkAdmin, BillingSpecialist, CareCoordinator |
| POST | `/charity-care/billing-accounts/{id}/claims` | Submit a claim with charge lines | BillingSpecialist |
| GET | `/charity-care/billing-accounts/{id}/claims` | List claims of a billing account (filterable by `status`) | NetworkAdmin, BillingSpecialist, CareCoordinator |
| GET | `/charity-care/claims/{claimId}` | Get one claim | NetworkAdmin, BillingSpecialist, CareCoordinator |
| POST | `/charity-care/claims/{claimId}/adjudicate` | Adjudicate a claim at the payer contract rate | BillingSpecialist |
| POST | `/charity-care/claims/{claimId}/deny` | Deny a claim; full amount absorbed by charity | BillingSpecialist |
| POST | `/charity-care/billing-accounts/{accountId}/settle` | Settle the account; residue swept to charity write-off | BillingSpecialist |
| GET | `/charity-care/applications/{id}/care-plan` | Get the care plan of an application (array of 0 or 1) | NetworkAdmin, IntakeCoordinator, ReviewCommitteeMember, CareCoordinator, PhilanthropyOfficer |
| GET | `/charity-care/care-plans/{carePlanId}` | Get one care plan | NetworkAdmin, CareCoordinator, PhilanthropyOfficer, BillingSpecialist |
| POST | `/charity-care/care-plans/{carePlanId}/discharge` | Discharge a care plan | CareCoordinator |
| POST | `/charity-care/care-plans/{id}/staged-procedures` | Add a planned stage to a care plan | CareCoordinator |
| GET | `/charity-care/care-plans/{id}/staged-procedures` | List stages of a care plan (filterable by `status`) | NetworkAdmin, CareCoordinator, PhilanthropyOfficer, BillingSpecialist |
| GET | `/charity-care/staged-procedures/{stageId}` | Get one staged procedure | NetworkAdmin, CareCoordinator, PhilanthropyOfficer, BillingSpecialist |
| POST | `/charity-care/staged-procedures/{stageId}/schedule` | Schedule a planned stage | CareCoordinator |
| POST | `/charity-care/staged-procedures/{stageId}/complete` | Mark a scheduled stage completed | CareCoordinator |
| POST | `/charity-care/staged-procedures/{stageId}/defer` | Defer a scheduled stage | CareCoordinator |
| POST | `/charity-care/staged-procedures/{stageId}/replan` | Replan a deferred stage to a new date | CareCoordinator |
| POST | `/charity-care/staged-procedures/{stageId}/cancel-stage` | Cancel a planned stage (plan contracts) | CareCoordinator |
| POST | `/charity-care/applications/{id}/travel-support-grants` | Create a travel/lodging grant for an accepted application | CareCoordinator |
| GET | `/charity-care/applications/{id}/travel-support-grants` | List travel grants of an application | NetworkAdmin, CareCoordinator, PhilanthropyOfficer |
| GET | `/charity-care/travel-support-grants/{grantId}` | Get one travel grant | NetworkAdmin, CareCoordinator, PhilanthropyOfficer |
| POST | `/charity-care/hospitals/{id}/outreach-clinics` | Propose an outreach clinic at a remote location | OutreachPlanner |
| GET | `/charity-care/hospitals/{id}/outreach-clinics` | List clinics of a hospital (filterable by `status`) | NetworkAdmin, IntakeCoordinator, OutreachPlanner, CareCoordinator |
| GET | `/charity-care/outreach-clinics/{clinicId}` | Get one clinic | NetworkAdmin, IntakeCoordinator, OutreachPlanner, CareCoordinator |
| POST | `/charity-care/outreach-clinics/{clinicId}/confirm` | Confirm a proposed clinic (conflict check) | OutreachPlanner |
| POST | `/charity-care/outreach-clinics/{clinicId}/complete` | Complete an in-progress clinic after its end date | OutreachPlanner |
| POST | `/charity-care/outreach-clinics/{clinicId}/cancel` | Cancel a proposed or confirmed clinic | OutreachPlanner |
| POST | `/charity-care/outreach-clinics/{id}/screenings` | Book a screening slot at a clinic | OutreachPlanner |
| GET | `/charity-care/outreach-clinics/{id}/screenings` | List screenings of a clinic (filterable by `status`) | NetworkAdmin, IntakeCoordinator, OutreachPlanner, CareCoordinator |
| GET | `/charity-care/outreach-screenings` | List screenings across clinics (filterable by `clinic_id`, `converted_application_id`, `status`) | NetworkAdmin, IntakeCoordinator, OutreachPlanner, CareCoordinator |
| GET | `/charity-care/outreach-screenings/{screeningId}` | Get one screening | NetworkAdmin, IntakeCoordinator, OutreachPlanner, CareCoordinator |
| POST | `/charity-care/outreach-screenings/{screeningId}/record-outcome` | Record that a booked screening happened | OutreachPlanner |
| POST | `/charity-care/outreach-screenings/{screeningId}/mark-no-show` | Mark a booked screening as no-show | OutreachPlanner |
| POST | `/charity-care/outreach-screenings/{screeningId}/rebook` | Rebook a no-show screening to a new date | OutreachPlanner |
| POST | `/charity-care/philanthropic-funds` | Create a philanthropic fund for a fiscal year | PhilanthropyOfficer |
| GET | `/charity-care/philanthropic-funds` | List funds (filterable by `fiscal_year`, `status`) | NetworkAdmin, PhilanthropyOfficer, CareCoordinator |
| GET | `/charity-care/philanthropic-funds/{fundId}` | Get one fund | NetworkAdmin, PhilanthropyOfficer, CareCoordinator |
| POST | `/charity-care/philanthropic-funds/{fundId}/lock` | Lock a fund (no new commits while locked) | PhilanthropyOfficer |
| POST | `/charity-care/philanthropic-funds/{fundId}/unlock` | Unlock a fund | PhilanthropyOfficer |
| POST | `/charity-care/philanthropic-funds/{fundId}/close` | Close a locked fund (terminal) | PhilanthropyOfficer |
| POST | `/charity-care/philanthropic-funds/{id}/allocations` | Pledge an allocation from a fund | PhilanthropyOfficer |
| GET | `/charity-care/philanthropic-funds/{id}/allocations` | List allocations of a fund (filterable by `status`, `hospital_id`) | NetworkAdmin, PhilanthropyOfficer, CareCoordinator |
| GET | `/charity-care/fund-allocations` | List allocations across funds (filterable by `fund_id`, `hospital_id`, `program_id`, `care_plan_id`, `status`) | NetworkAdmin, PhilanthropyOfficer, CareCoordinator |
| GET | `/charity-care/fund-allocations/{allocationId}` | Get one allocation | NetworkAdmin, PhilanthropyOfficer, CareCoordinator |
| POST | `/charity-care/fund-allocations/{allocationId}/commit` | Commit a pledged allocation (OCC-guarded) | PhilanthropyOfficer |
| POST | `/charity-care/fund-allocations/{allocationId}/withdraw` | Withdraw a pledged allocation | PhilanthropyOfficer |
| POST | `/charity-care/fund-allocations/{allocationId}/release` | Release a committed allocation back to the fund | PhilanthropyOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_HOSPITAL_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_BILLING_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_CARE_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_STAGE_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONDITION_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_AGE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INTERNATIONAL_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_REVIEWER_CONFLICT` | 403 Forbidden |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_HOSPITAL_NOT_OPEN` | 409 Conflict |
| `ERR_HOSPITAL_HAS_OPEN_APPLICATIONS` | 409 Conflict |
| `ERR_HOSPITAL_CAPACITY_REACHED` | 409 Conflict |
| `ERR_AGE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_STAGE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_STAGE_ALREADY_IN_FLIGHT` | 409 Conflict |
| `ERR_STAGE_NOT_DUE` | 409 Conflict |
| `ERR_STAGES_IN_FLIGHT` | 409 Conflict |
| `ERR_PLAN_FUNDING_UNRESOLVED` | 409 Conflict |
| `ERR_PLAN_HAS_STAGE_IN_FLIGHT` | 409 Conflict |
| `ERR_SCREENING_DATE_OUTSIDE_CLINIC` | 409 Conflict |
| `ERR_CLINIC_LOCATION_CONFLICT` | 409 Conflict |
| `ERR_CLINIC_CAPACITY_REACHED` | 409 Conflict |
| `ERR_CLINIC_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CLINIC_STILL_RUNNING` | 409 Conflict |
| `ERR_CONVERSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SCREENING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FUND_NOT_OPEN` | 409 Conflict |
| `ERR_INSUFFICIENT_FUND_BALANCE` | 402 Payment Required |
| `ERR_PLEDGED_ALLOCATIONS_EXIST` | 409 Conflict |
| `ERR_NO_BILLABLE_COVERAGE` | 409 Conflict |
| `ERR_OPEN_CLAIMS_EXIST` | 409 Conflict |
| `ERR_NO_FAMILY_BILLING_VIOLATION` | 422 Unprocessable Entity |
