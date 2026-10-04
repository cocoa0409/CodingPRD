# Dental Benefit Administration API — Product Requirements Document

## 1. Introduction

Dental carriers operate under a peculiar burden: the clinical work happens in a dentist's chair, but the financial promises are made by the plan. A crown quoted at one allowed amount in January can reprice in March when a fee schedule rolls over; a member with dual coverage expects the secondary plan to pick up exactly what the primary left behind, no more; a teenager's third bitewing series this year must be refused without anyone at the carrier manually noticing. This document specifies the Dental Benefit Administration API, a carrier-side system that administers dental benefit plans end to end — from plan configuration and network fee schedules, through predetermination of benefits with clinical review, to claim adjudication with frequency, age, missing-tooth and waiting-period limitations, alternate benefit provisions, and coordination of benefits.

The system serves six constituencies with sharply segregated duties. Plan administrators define benefit plans, enroll subscribers, and configure the limitation rules that govern cleanings, radiographs, sealants, and major replacements. Network managers onboard dental providers into one of three participation tiers and file the fee schedules that determine what the plan recognizes as an allowed amount. Clinical reviewers — licensed dental consultants — self-assign predetermination requests, estimate what the plan would pay, and approve or deny them with the schedule pinned at approval so the member's quote survives later schedule updates. Claims examiners shepherd claims through coordination-of-benefits review, payment, and void. Members and providers file predeterminations and claims against their own identities only.

Two design commitments run through everything that follows. First, every financial figure is an integer number of cents — the system never rounds except where explicitly stated, and coinsurance floors rather than rounds so the plan never overpays a fractional cent. Second, benefit usage is tracked per patient and per plan year in a dedicated accumulator, and every adjudication and void adjusts that accumulator transactionally so a member's remaining annual maximum is always reconstructible from their paid history.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API: authentication, response envelopes, pagination, resource identity, monetary precision, concurrency control, and the cross-cutting benefit principles (plan years, logical clock, tiered pricing) that individual workflows in §3 rely on.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming their operational capacity. A request missing either header, or presenting an `X-User-Role` value outside the declared role set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role is checked against the endpoint's authorized role list; a role that is recognized but not permitted on the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles: `PlanAdmin`, `NetworkManager`, `ClinicalReviewer`, `ClaimsExaminer`, `Member`, and `Provider`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource that references a `Subscriber` compare the resource's `subscriber_id` foreign key to `X-User-ID`, and actions on a dependent are authorized when the dependent's owning subscriber matches `X-User-ID`.
- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on claims, predeterminations, and attachments compare the resource's `provider_id` foreign key to `X-User-ID`.
- When `X-User-Role` is `PlanAdmin`, `NetworkManager`, `ClinicalReviewer`, or `ClaimsExaminer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — notably, a `ClinicalReviewer`'s `X-User-ID` is stored as `clinical_reviewer_id` on a `Predetermination` when they self-assign — but the server does not compare it to any entity's `id` except where a segregation-of-duties rule explicitly requires it.

Ownership violations by `Member` or `Provider` callers — for example, a member acting on another member's subscriber, or a provider filing a claim under a different provider's identity — are rejected with `ERR_UNAUTHORIZED` (HTTP 403), the same code used for role-based rejection.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. List responses are always sorted by `created_at` in ascending order unless otherwise specified. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — plans, providers, fee schedules and their entries, subscribers, dependents, limitation rules, predeterminations, claims, claim lines, and benefit accumulators — carries a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. `created_at` records the creation instant as an ISO 8601 UTC timestamp with three fractional digits. `updated_at` is refreshed on every mutation. `version` is an integer starting at 1 that increments on every mutation and underpins optimistic concurrency control. Every lifecycle-bearing resource also exposes a `status` field whose exact enumeration is given alongside the workflow that drives it in §3 — plans run `DRAFT`, `ACTIVE`, `SUSPENDED`, `RETIRED`; providers and subscribers and dependents run `ACTIVE` to `TERMINATED`; fee schedules run `PENDING`, `ACTIVE`, `SUPERSEDED`, `RETIRED`; predeterminations run `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, `WITHDRAWN`, `EXPIRED`; claims run `RECEIVED`, `PENDED_ATTACHMENTS`, `PENDED_REVIEW`, `ADJUDICATED`, `PAID`, `DENIED`, `VOID`; claim lines run `PENDING`, `PRICED`, `PAYABLE`, `DENIED`; and limitation rules run `ACTIVE` to `RETIRED`.

One resource deviates from this convention: `ClaimAttachment` records only `id` and `created_at` — it has no `updated_at` and no `version`, because attachments are immutable once uploaded; the server stamps the upload instant on the attachment itself as `transmitted_on`.

### 2.5. Monetary Representation and Calculation Precision

All monetary quantities — plan caps, deductibles, allowed amounts, submitted charges, plan payments, patient responsibilities — are represented as integer cents. No monetary field ever carries a fractional value, and no monetary calculation rounds except in exactly one place: when computing the plan's coinsurance share of a line, the product of the post-deductible allowed amount and the plan's coinsurance percentage is floored to a whole cent (floor, not round-half-up). Everything else — allowed amounts, deductibles, caps, COB allocations, accumulator totals — is exact integer arithmetic.

Plan configuration is bounded: `preventive_coinsurance_pct`, `basic_coinsurance_pct`, and `major_coinsurance_pct` must each be at least 0 and at most 100, and `annual_maximum_cents` and `deductible_cents` must be non-negative. A plan creation request violating these bounds is rejected with `ERR_INVALID_PLAN_CONFIG` (HTTP 422).

### 2.6. The Logical Clock

The system runs on a logical clock, not wall-clock time. Before any administrative action is taken, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlanAdmin` may advance it by calling the clock-setting capability with a `to_iso8601` timestamp; the endpoint responds with the new time in a `now` field. The logical clock never falls back to wall-clock. Three behaviors anchor to it: predetermination expiry (an `APPROVED` predetermination becomes `EXPIRED` once the clock passes its `expires_on`), the retroactivity ban on new predeterminations, and the thirty-day void window on paid claims.

### 2.7. Plan Years and Per-Patient Accumulation

Deductibles and annual maximums are tracked per patient — subscriber and each dependent accumulate independently — and per plan year. A plan declares its renewal month as `plan_year_start_month` (an integer from 1 to 12). The plan-year bucket for a service date is derived as follows: if the service date's month is on or after the plan's anchor month, the plan-year starts in the service date's calendar year; otherwise it started in the prior calendar year. The bucket key `plan_year_key` is the two years joined by a hyphen — for example, a plan renewing in July treats a March 2027 service as belonging to plan year `2026-2027`, while a September 2027 service belongs to `2027-2028`.

Each (subscriber, dependent-or-null, plan-year) combination has at most one `BenefitAccumulator`, created lazily on the first adjudication that touches it with `deductible_met_cents` and `annual_max_used_cents` at zero and `version` at 1. After every transition the invariant holds that `deductible_met_cents` lies between zero and the plan's `deductible_cents` inclusive, and `annual_max_used_cents` lies between zero and the plan's `annual_maximum_cents` inclusive.

### 2.8. Network Tiers and Fee Schedule Versioning

Every provider participates in exactly one network tier — `PREMIER`, `PPO`, or `OUT_OF_NETWORK` — recorded as the provider's `tier`, and that tier determines which fee schedule prices their work. Fee schedules are versioned per tier: each schedule declares `effective_from` and an optional `effective_to` (null meaning open-ended), and a schedule applies to work whose anchor date falls on or after `effective_from` and strictly before `effective_to`.

Only one schedule per tier should govern any instant. When a `NetworkManager` activates a new schedule, any existing `ACTIVE` schedule for the same tier whose `effective_from` is on or before the new schedule's `effective_from` has its `effective_to` set to the new schedule's `effective_from` — its window is truncated but its status remains `ACTIVE`. The mirror-image case is forbidden: activating a schedule that would overlap an existing `ACTIVE` same-tier schedule whose `effective_from` is strictly later than the new one's (a retroactive insertion) is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409). Schedules leave `ACTIVE` only via retirement, which moves them to `SUPERSEDED` — window truncation by a successor never changes a schedule's status.

### 2.9. Optimistic Concurrency Control

Two write operations require the caller to prove they have observed the resource's current state, and both reject stale views with `ERR_STALE_VERSION` (HTTP 412):

- Approving a predetermination requires `expected_predetermination_version` in the request body, carrying the `version` of the predetermination as the approving reviewer last observed it. If the predetermination's current `version` has advanced — for instance because a reassignment recomputed the estimate — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so a reviewer never approves an estimate they have not seen.
- Voiding a claim requires `expected_claim_version`, carrying the `version` of the claim as the examiner last observed it. If the claim's `version` has advanced since — for instance because another examiner has just paid it — the void is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; requests to any other operation are processed without an OCC check.

### 2.10. Validation Order and Nested Path Resolution

Every request passes through validation layers in a fixed order, and the first failing layer determines the error returned. Authentication (header presence and known role, `ERR_UNAUTHENTICATED`) runs first, followed by role authorization and ownership checks (`ERR_UNAUTHORIZED`). Next, path-parameter identifiers are resolved left to right — each entity type surfaces its own dedicated 404 code: `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path is rejected at the first identifier that does not resolve, before deeper segments are examined. Foreign-key references in request bodies (`plan_id`, `subscriber_id`, `dependent_id`, `provider_id`, `predetermination_id`, `claim_line_id`) resolve next, failing with the generic `ERR_NOT_FOUND` (HTTP 404). Only then are required-field presence, types, and enum membership validated, failing with `ERR_INVALID_REQUEST` (HTTP 400), followed by state-transition legality (`ERR_INVALID_STATE`, HTTP 409) and finally the business rules described in §3.

### 2.11. Hierarchical Consistency and Cascade Discipline

State changes propagate down the entity hierarchy so the system never holds a contradiction: terminating a subscriber terminates all of their dependents and withdraws their open predeterminations; activating a fee schedule recomputes every in-flight predetermination priced against the same tier; voiding a claim reverses the accumulator exactly. Each cascade-induced mutation refreshes the affected resource's `updated_at` and increments its `version`, and each cascade is described beside the workflow that triggers it in §3.

## 3. Business Logic & Workflows

### 3.1. Setting Up a Plan and Its Limitation Rules

A `PlanAdmin` authors a benefit plan by supplying its `plan_code` — a globally unique human-readable identifier such as DD-PRIME-100 — together with the financial skeleton: `annual_maximum_cents` (the per-member per-plan-year benefit cap; zero is not permitted as a way of expressing "uncapped"), `deductible_cents`, the `deductible_applies_preventive` flag governing whether preventive-category lines draw down the deductible, and the three coinsurance percentages `preventive_coinsurance_pct`, `basic_coinsurance_pct`, and `major_coinsurance_pct` naming the share of the allowed amount the plan pays in each category. Waiting periods are configured as `basic_waiting_months` and `major_waiting_months`, counted from each subscriber's effective date. Two clinical-policy switches complete the configuration: `missing_tooth_clause_active`, which when true denies replacement of teeth lost before coverage began, and `abp_enabled`, which when true arms the alternate benefit provision described in §3.6.

A plan is born in `DRAFT`. Activation by a `PlanAdmin` moves it `DRAFT → ACTIVE`, which requires all monetary and coinsurance fields to be present and non-negative and that no other `ACTIVE` plan carries the same `plan_code`; only an `ACTIVE` plan is referenceable when enrolling subscribers. An active plan may be suspended (`ACTIVE → SUSPENDED`), which blocks new subscriber enrollment and new claim submission against it with `ERR_PLAN_NOT_ACTIVE` (HTTP 409) while leaving already-adjudicated-but-unpaid claims payable; suspension is reversed by activating again (`SUSPENDED → ACTIVE`). Retirement (`ACTIVE → RETIRED`) is permitted only when no `ACTIVE` subscriber remains on the plan, after which the plan is read-only and its surviving claims can still run to `PAID` or `VOID`.

Limitation rules attach to a plan and encode the clinical frequency and age policies. A `PlanAdmin` creates each rule with the `cdt_code` it governs — which may be an exact code or a category wildcard such as `D1*` covering a radiograph series — plus a `rule_kind` of `FREQUENCY`, `AGE_MAX`, `AGE_MIN`, `REPLACEMENT_INTERVAL`, or `MISSING_TOOTH`. Frequency and replacement rules use `window_months` (a rolling window in months) and `max_occurrences`; age rules use `age_years_min` or `age_years_max`, expressed in whole years. A rule field that its `rule_kind` does not use carries zero. Rules are themselves listable by `rule_kind` or `cdt_code`, and a rule may be retired (`ACTIVE → RETIRED`) when the plan's policy changes. How each rule kind fires at adjudication time is specified in §3.7.

### 3.2. Building the Provider Network and Filing Fee Schedules

A `NetworkManager` onboards a dental practice by registering its `npi` (the ten-digit National Provider Identifier), `legal_name`, `license_state`, participation `tier`, and `contracted_on` date from which the tier is honored. A provider is `ACTIVE` from creation and remains so until terminated.

Fee schedules are filed per tier. A `NetworkManager` creates a schedule with its `tier`, an `effective_from` instant, an optional `effective_to`, and an `entries` array; each element of `entries` becomes a `FeeScheduleEntry` carrying the procedure's `cdt_code`, the `allowed_cents` the plan recognizes for that code under this schedule, the service `category` (`PREVENTIVE`, `BASIC`, or `MAJOR` — this drives both the coinsurance bucket and the waiting-period gate), a `requires_attachment` flag marking codes whose claim lines demand supporting documentation, and an `abp_alternative_cdt` naming a lower-cost alternate procedure code when one exists (empty when none does), with each entry bound to its owning schedule through its `fee_schedule_id`. A new schedule is `PENDING` until a `NetworkManager` activates it; activation applies the overlap and truncation rules of §2.8 and triggers the predetermination recomputation cascade described in §3.4. Retirement moves a schedule `PENDING → RETIRED` unconditionally, or `ACTIVE → SUPERSEDED`, or `ACTIVE → RETIRED`; retiring directly from `ACTIVE` to `RETIRED` is refused while any claim in `PENDED_ATTACHMENTS` or `PENDED_REVIEW` was priced against that schedule. A superseded schedule stops pricing new claims, but predeterminations approved against it keep their pinned pricing — the pin survives supersession.

Terminating a provider (`ACTIVE → TERMINATED`) is blocked while the provider has any predetermination in `UNDER_REVIEW` or any claim in `PENDED_REVIEW`; the attempt fails with `ERR_PROVIDER_BUSY` (HTTP 409). Once terminated, any future claim or predetermination naming that `provider_id` is rejected with `ERR_PROVIDER_TERMINATED` (HTTP 409).

### 3.3. Enrollment: Subscribers, Dependents, and Coordination of Benefits Declarations

Enrollment is a `PlanAdmin` function. Creating a subscriber requires the target `plan_id`, the external `member_id`, the subscriber's `full_name`, `date_of_birth`, and `effective_date` — the anchor from which waiting periods, the missing-tooth clause, and coordination-of-benefits primacy are all measured. The subscriber declares their position in any dual-coverage arrangement via `cob_priority`: `PRIMARY`, `SECONDARY`, or `NONE`. When `cob_priority` is `SECONDARY`, the enrollment must name the other carrier in `other_plan_external_id`; when it is `PRIMARY` or `NONE`, that field must be empty. Violating this pairing is rejected with `ERR_COB_CONFIG_INVALID` (HTTP 422). Enrollment against a plan that is not `ACTIVE` fails with `ERR_PLAN_NOT_ACTIVE`. A subscriber begins life `ACTIVE`, and enrollment lays down a placeholder for the benefit accumulator, which materializes lazily on first adjudication.

Dependents are added under a subscriber with a `full_name`, `date_of_birth` (which drives age limitation for sealants and fluoride), and a `relationship` of `SPOUSE`, `CHILD`, or `DOMESTIC_PARTNER`. Dependents are `ACTIVE` from creation and may be terminated individually by a `PlanAdmin` (`ACTIVE → TERMINATED`).

Terminating a subscriber is a cascading event. It is refused while the subscriber has any claim in `RECEIVED`, `PENDED_ATTACHMENTS`, `PENDED_REVIEW`, or `ADJUDICATED` — such claims must first reach `PAID`, `DENIED`, or `VOID`. When termination proceeds, every dependent of the subscriber transitions `ACTIVE → TERMINATED`, and every predetermination of the subscriber still in `SUBMITTED` or `UNDER_REVIEW` transitions to `WITHDRAWN`.

### 3.4. Predetermination of Benefits: Clinical Review with a Pricing Pin

Before a member commits to major treatment, either the member or the rendering provider may request a predetermination of benefits. The submission names the `subscriber_id` and, when the patient is a dependent, the `dependent_id` (which must belong to that subscriber, else `ERR_CROSS_REFERENCE_MISMATCH`); it also names the `provider_id`, the `cdt_code` under review, the provider's billed `submitted_amount_cents`, and the `planned_service_date`. A `Provider` caller may submit only for themselves — the payload's `provider_id` must equal their `X-User-ID` — and a `Member` caller may submit only for themselves or their own dependents; either ownership violation draws `ERR_UNAUTHORIZED`. Predeterminations are forward-looking by definition: a `planned_service_date` earlier than the logical clock is rejected with `ERR_RETROACTIVE_PREDETERMINATION` (HTTP 422). The request is born in `SUBMITTED` with `clinical_reviewer_id` empty.

Review is self-assigned under strict segregation of duties. A `ClinicalReviewer` takes ownership by submitting a `clinical_reviewer_id` in the assign payload that must equal their own `X-User-ID` — a reviewer cannot be assigned by anyone else, and any mismatch is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Assignment moves the predetermination `SUBMITTED → UNDER_REVIEW`, records the reviewer, and computes the estimate: the system resolves the fee schedule `ACTIVE` for the rendering provider's tier at the `planned_service_date`, and sets `estimated_allowed_cents`, `estimated_plan_pay_cents`, and `estimated_patient_pay_cents` exactly as the claim adjudication pipeline would — same allowed-amount resolution, same ABP handling (with `abp_applied` reflecting whether the provision re-priced the estimate), same waiting-period and limitation checks evaluated against the planned date and current paid history, same coinsurance, deductible, and annual-maximum arithmetic — with one crucial difference: the accumulator is read-only during estimation. The estimate is what the plan would pay given the accumulator as it stands at this moment; nothing is drawn down. If no `ACTIVE` schedule covers the provider's tier at the planned date, or the schedule lacks an entry for the code, assignment fails with `ERR_NO_FEE_SCHEDULE` (HTTP 422).

While a predetermination is `UNDER_REVIEW`, three things can happen. A different reviewer may take it over: reassignment requires the payload's `clinical_reviewer_id` to equal the requesting reviewer's `X-User-ID` and to differ from the currently recorded reviewer — reassigning to oneself is a segregation-of-duties violation — and it recomputes the estimate against the schedule currently in force, without pinning anything. The assigned reviewer may deny, moving the predetermination `UNDER_REVIEW → DENIED`; denial is permitted only to the reviewer of record, so `X-User-ID` must equal the stored `clinical_reviewer_id`. Or the assigned reviewer may approve.

Approval is the load-bearing transition. The reviewer of record approves with `expected_predetermination_version` matching the predetermination's current `version` per §2.9. The approval re-runs the estimate against current state, then freezes it: `version_pin_fee_schedule_id` is locked to the fee schedule used for the final estimate, the `estimated_*` fields are locked, and `expires_on` is set to the logical clock plus ninety days — the predetermination validity window. One fiscal guard applies at approval: if the freshly computed `estimated_plan_pay_cents` would exceed the plan's remaining annual maximum for the patient — the plan's `annual_maximum_cents` minus the accumulator's current `annual_max_used_cents` — the approval is refused with `ERR_ANNUAL_MAX_EXCEEDED` (HTTP 422), so a clinician can never promise payment the plan cannot deliver.

Approval is not the only way out. A member may withdraw their own predetermination from either `SUBMITTED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`; the caller's `X-User-ID` must be the subscriber who owns it. And an approved predetermination does not live forever: once the logical clock passes `expires_on`, the predetermination lazily transitions `APPROVED → EXPIRED` on read or when a claim references it, releasing the pricing pin so that claims thereafter resolve the schedule by service date normally.

Because fee schedule activation recomputes every `UNDER_REVIEW` predetermination whose rendering provider's tier matches the schedule's tier — refreshing the `estimated_*` fields against the schedule now governing the planned service date and incrementing each recomputed predetermination's `version` — a reviewer approving after a schedule roll must re-read the estimate; the OCC check on approval exists precisely to catch a reviewer acting on a pre-recomputation view.

### 3.5. Claim Intake: Timely Filing, Attachments, and Routing

A claim arrives from the rendering `Provider` — whose `X-User-ID` must equal the payload's `provider_id` — or from a `ClaimsExaminer` filing on the provider's behalf. The payload names the `subscriber_id` and optional `dependent_id` (which must belong to that subscriber, on pain of `ERR_CROSS_REFERENCE_MISMATCH`), the `provider_id`, an optional `predetermination_id` referencing an approved predetermination whose pin should price the claim, the `service_date`, the `received_date`, an optional `cob_other_plan_paid_cents` amount (defaulting to zero) recording what the primary carrier already paid when this plan is secondary, an optional `tooth_missing_prior_to_coverage` map attesting per tooth number whether the tooth was missing before the member's `effective_date`, and a `lines` array. Each element of `lines` becomes a `ClaimLine` — stamped with the `claim_id` of its owning claim — carrying a one-based `line_number` unique within the claim, the `cdt_code` billed, a `tooth_number` when the code is tooth-specific (empty for non-tooth codes), and the provider's `submitted_amount_cents` for that line.

Two intake gates run before anything is priced. The timely-filing rule rejects a claim whose `received_date` falls more than three hundred sixty-five days after the `service_date` — a claim received on the three-hundred-sixty-fifth day itself is timely, one received later is refused with `ERR_TIMELY_FILING` (HTTP 422). The schedule gate verifies that an `ACTIVE` fee schedule covers the rendering provider's tier at the service date and contains an entry for every `cdt_code` on the claim; failure is `ERR_NO_FEE_SCHEDULE`.

Once past intake, the claim's routing is automatic. If any line's fee schedule entry is flagged `requires_attachment` and no matching attachment exists yet, the claim moves `RECEIVED → PENDED_ATTACHMENTS` and the attachment-requiring lines stay in `PENDING`. Otherwise, if the subscriber's `cob_priority` is `SECONDARY`, the claim moves `RECEIVED → PENDED_REVIEW` to await examiner confirmation of the primary carrier's payment. Otherwise the claim moves directly `RECEIVED → ADJUDICATED` and the adjudication pipeline of §3.7 runs immediately.

Providers supply missing documentation by uploading attachments: each attachment names the `claim_line_id` it supports — which must belong to the same claim, else `ERR_CROSS_REFERENCE_MISMATCH` — an `attachment_kind` of `RADIOGRAPH`, `NARRATIVE`, `PERIO_CHART`, or `PHOTO`, and an opaque `blob_ref` storage reference. A submission missing `blob_ref` or `attachment_kind`, or presenting a kind outside the declared set, fails with `ERR_INVALID_ATTACHMENT` (HTTP 400). When an upload completes the last missing attachment on a `PENDED_ATTACHMENTS` claim, the claim re-evaluates its routing: a secondary-coverage claim proceeds `PENDED_ATTACHMENTS → PENDED_REVIEW`, while a primary or single-coverage claim proceeds `PENDED_ATTACHMENTS → ADJUDICATED` and adjudicates immediately.

For claims waiting on coordination of benefits, a `ClaimsExaminer` confirms the primary carrier's payment by supplying `cob_other_plan_paid_cents` (zero or more), moving the claim `PENDED_REVIEW → ADJUDICATED` and running the full pipeline including the COB waterfall of §3.8.

### 3.6. Pricing a Line: Allowed Amounts and the Alternate Benefit Provision

The first step of adjudication prices every line, moving each from `PENDING` through the transient `PRICED` state within the same adjudication pass. Pricing resolves the fee schedule as §2.8 describes: the schedule whose tier matches the rendering provider's `tier` at the moment of pricing, whose window contains the claim's `service_date`. One override applies: when the claim's `predetermination_id` references an `APPROVED` predetermination that has not expired, the schedule named by that predetermination's `version_pin_fee_schedule_id` governs instead — regardless of which schedule is currently `ACTIVE` — so a member treated under an approved quote pays exactly what they were quoted even if schedules have since rolled. A claim referencing an expired or never-approved predetermination ignores the pin and prices by service date.

With the schedule resolved, the line's base allowed amount is the lesser of the provider's `submitted_amount_cents` and the schedule entry's `allowed_cents`; the entry's `category` is copied onto the line at this moment. Then the alternate benefit provision may fire: when the plan's `abp_enabled` is true and the entry names a non-empty `abp_alternative_cdt`, the system prices the alternate code the same way — the lesser of the submitted amount and the alternate entry's allowed amount — and if that alternate allowance is lower than the base allowance, the plan pays against the cheaper treatment. In that case the line's `abp_applied` becomes true, its `allowed_cents` drops to the alternate allowance, and the gap between the base allowance and the alternate allowance is recorded as `abp_patient_difference_cents` — a sum the patient owes in addition to their normal cost share, because the member chose the more expensive procedure. When the plan disables ABP, that difference is zero by definition.

### 3.7. Adjudication: Limitations, Waiting Periods, Deductibles, and the Annual Maximum

After pricing, each line faces the clinical and temporal gates, evaluated per line. The waiting-period gate reads the plan's waiting configuration: preventive lines are never gated, basic lines wait `basic_waiting_months` calendar months from the subscriber's `effective_date`, and major lines wait `major_waiting_months`. A service rendered before the earliest eligible date is denied with `denial_code` `WAITING_PERIOD`; a service rendered exactly on the eligible date is eligible — the boundary is inclusive.

The limitation rules of §3.1 then fire. A `FREQUENCY` rule counts the patient's prior claim lines with the same `cdt_code` that sit on `PAID` claims in `PAYABLE` status and whose service dates fall within the rolling window — from `window_months` before this service date through this service date, inclusive on both ends; if adding this line would push the count past `max_occurrences`, the line is denied `FREQUENCY`. An `AGE_MAX` rule denies with `AGE_LIMIT` when the patient's age in whole years at the service date exceeds `age_years_max`; an `AGE_MIN` rule denies `AGE_LIMIT` when that age falls short of `age_years_min` — ages are whole years, so a member is seventeen until their eighteenth birthday. A `REPLACEMENT_INTERVAL` rule looks back at the patient's most recent paid line for the same `tooth_number` with a code in the same major category (ties broken by earliest `created_at`), and denies `FREQUENCY` when fewer than `window_months` calendar months have elapsed since that prior service. A `MISSING_TOOTH` rule fires only when the plan's `missing_tooth_clause_active` is true and the line names a `tooth_number`: if the claim's `tooth_missing_prior_to_coverage` map attests that tooth was missing before coverage began, the line is denied `MISSING_TOOTH`. When several rules match one line, the rule declared earliest on the plan — by `created_at` ascending — wins and sets the `denial_code`.

A denied line's `plan_pay_cents` is zero and its `patient_pay_cents` equals its `submitted_amount_cents`; the full denial vocabulary also includes `TIMELY_FILING`, `ATTACHMENT_MISSING`, and `NO_COVERAGE`, and a clean line carries `NULL`. Surviving lines then draw down the patient's accumulator in `line_number` ascending order — order matters because the deductible and the annual maximum deplete sequentially, and later lines on the same claim observe earlier lines' draws. For each line, the deductible step charges nothing when the line is preventive-category and the plan's `deductible_applies_preventive` is false; otherwise it charges the lesser of the line's `allowed_cents` and the patient's remaining deductible — the plan's `deductible_cents` minus the accumulator's `deductible_met_cents`, floored at zero — recording it as `deductible_applied_cents`. The coinsurance step then computes the plan's share of the remainder: the allowed amount minus the line deductible, multiplied by the category's percentage — `preventive_coinsurance_pct`, `basic_coinsurance_pct`, or `major_coinsurance_pct` as the line's `category` dictates — divided by one hundred and floored to a whole cent, stored as `coinsurance_plan_cents`. The annual-maximum step caps that share at the patient's remaining maximum — `annual_maximum_cents` minus `annual_max_used_cents`, floored at zero. What survives becomes the line's `plan_pay_cents` (subject to the COB adjustment of §3.8), and the patient's responsibility `patient_pay_cents` is the allowed amount minus the plan payment plus any `abp_patient_difference_cents`. As each line completes, the accumulator absorbs its draws: `deductible_met_cents` grows by the line's `deductible_applied_cents` and `annual_max_used_cents` by its `plan_pay_cents`.

Adjudication finalizes the claim's rollups: `total_submitted_cents`, `total_allowed_cents`, `total_plan_pay_cents`, and `total_patient_pay_cents` are the per-line sums across the claim. When every line denies, the claim itself transitions `ADJUDICATED → DENIED` automatically and no accumulator changes attach to it.

### 3.8. Coordination of Benefits: The Secondary-Carrier Waterfall

When the subscriber's `cob_priority` is `SECONDARY`, this plan pays last. The COB waterfall first computes what this plan would have paid as primary — the full patient-cost-share arithmetic of §3.7 run as if the coverage were primary. The secondary payment is then bounded by what the primary carrier left behind: the line's allowed amount minus the claim's `cob_other_plan_paid_cents`. The plan's payment is the lesser of the hypothetical primary payment and that remaining responsibility, floored at zero, and is recorded on the claim as `cob_secondary_payment_cents`. Two boundaries fall out naturally: if the primary carrier paid more than this plan's allowed amount, the secondary payment is zero; if the primary paid nothing, the secondary payment equals the hypothetical primary payment. When coverage is `PRIMARY` or `NONE`, `cob_secondary_payment_cents` is zero and the COB step changes nothing.

### 3.9. Payment, Void, and Accumulator Reversal

An adjudicated claim becomes payable when a `ClaimsExaminer` marks it paid, moving `ADJUDICATED → PAID`. Payment requires every line to be resolved — none still `PENDING` — and at least one line in `PAYABLE`; at that moment the claim totals become immutable and the accumulator update is finalized.

Voiding is the compensation path. A `ClaimsExaminer` may void an `ADJUDICATED` claim unconditionally, and may void a `PAID` claim only while the logical clock remains within thirty days of the claim's `updated_at` — the void window. Every void carries `expected_claim_version` per §2.9. Voiding reverses the accumulator exactly: the voided claim's payable lines have their `deductible_applied_cents` sums subtracted from `deductible_met_cents` and their `plan_pay_cents` sums subtracted from `annual_max_used_cents`, and the accumulator's `version` increments. After reversal, the invariant of §2.7 holds again — the patient's remaining deductible and maximum are as if the claim had never adjudicated.

## 4. Endpoint Definitions

Operations that create a new resource — a plan, provider, fee schedule, limitation rule, subscriber, dependent, predetermination, claim, or attachment — return `201 Created`. Operations that modify an existing resource's state — activations, suspensions, retirements, terminations, assignment, approval, denial, withdrawal, COB confirmation, payment, void, and the clock setter — return `200 OK`. All endpoints are mounted under the `/dental` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dental/_clock/set_current_utc` | Advance the logical clock | PlanAdmin |
| POST | `/dental/plans` | Create a plan in DRAFT | PlanAdmin |
| GET | `/dental/plans` | List plans | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/plans/{id}` | Get one plan | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| POST | `/dental/plans/{id}/activate` | Activate or un-suspend a plan | PlanAdmin |
| POST | `/dental/plans/{id}/suspend` | Suspend a plan | PlanAdmin |
| POST | `/dental/plans/{id}/retire` | Retire a plan | PlanAdmin |
| POST | `/dental/providers` | Create a provider | NetworkManager |
| GET | `/dental/providers` | List providers | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/providers/{id}` | Get one provider | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| POST | `/dental/providers/{id}/terminate` | Terminate a provider | NetworkManager |
| POST | `/dental/fee-schedules` | Create a fee schedule in PENDING with entries | NetworkManager |
| GET | `/dental/fee-schedules` | List fee schedules | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer |
| GET | `/dental/fee-schedules/{id}` | Get one fee schedule | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer |
| GET | `/dental/fee-schedules/{id}/entries` | List entries of one fee schedule | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer |
| POST | `/dental/fee-schedules/{id}/activate` | Activate a fee schedule (truncates overlapping same-tier ACTIVE) | NetworkManager |
| POST | `/dental/fee-schedules/{id}/retire` | Retire a schedule | NetworkManager |
| POST | `/dental/plans/{id}/limitation-rules` | Attach a limitation rule to a plan | PlanAdmin |
| GET | `/dental/plans/{id}/limitation-rules` | List a plan's limitation rules | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer |
| GET | `/dental/limitation-rules/{id}` | Get one limitation rule | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer |
| POST | `/dental/subscribers` | Enroll a subscriber on an ACTIVE plan | PlanAdmin |
| GET | `/dental/subscribers` | List subscribers | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member |
| GET | `/dental/subscribers/{id}` | Get one subscriber | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member |
| POST | `/dental/subscribers/{id}/terminate` | Terminate a subscriber; cascades to dependents and open predeterminations | PlanAdmin |
| POST | `/dental/subscribers/{id}/dependents` | Add a dependent | PlanAdmin |
| GET | `/dental/subscribers/{id}/dependents` | List a subscriber's dependents | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member |
| GET | `/dental/dependents/{id}` | Get one dependent | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member |
| POST | `/dental/dependents/{id}/terminate` | Terminate one dependent | PlanAdmin |
| GET | `/dental/subscribers/{id}/accumulators` | List a subscriber's benefit accumulators | PlanAdmin, ClaimsExaminer, ClinicalReviewer, Member |
| GET | `/dental/dependents/{id}/accumulators` | List a dependent's benefit accumulators | PlanAdmin, ClaimsExaminer, ClinicalReviewer, Member |
| POST | `/dental/predeterminations` | Submit a predetermination | Member, Provider |
| GET | `/dental/predeterminations` | List predeterminations | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/predeterminations/{id}` | Get one predetermination (lazy EXPIRED transition may apply) | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| POST | `/dental/predeterminations/{id}/assign` | ClinicalReviewer self-assigns and computes the estimate | ClinicalReviewer |
| POST | `/dental/predeterminations/{id}/reassign` | Reassign to a different reviewer; recomputes estimate | ClinicalReviewer |
| POST | `/dental/predeterminations/{id}/approve` | Approve with pinned schedule and validity window | ClinicalReviewer |
| POST | `/dental/predeterminations/{id}/deny` | Deny the predetermination | ClinicalReviewer |
| POST | `/dental/predeterminations/{id}/withdraw` | Member withdraws an open predetermination | Member |
| POST | `/dental/claims` | Submit a claim with lines; auto-adjudicates or pends | Provider, ClaimsExaminer |
| GET | `/dental/claims` | List claims | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/claims/{id}` | Get one claim | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/claims/{id}/lines` | List claim lines | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/claim-lines/{id}` | Get one claim line | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| GET | `/dental/claim-lines/{id}/attachments` | List attachments linked to one claim line | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| POST | `/dental/claims/{id}/attachments` | Upload an attachment for a claim line | Provider |
| GET | `/dental/claims/{id}/attachments` | List attachments for a claim | PlanAdmin, NetworkManager, ClaimsExaminer, ClinicalReviewer, Member, Provider |
| POST | `/dental/claims/{id}/cob-confirm` | Examiner confirms COB inputs and triggers adjudication | ClaimsExaminer |
| POST | `/dental/claims/{id}/pay` | Mark an adjudicated claim as PAID | ClaimsExaminer |
| POST | `/dental/claims/{id}/void` | Void an ADJUDICATED or PAID claim; reverses the accumulator | ClaimsExaminer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 |
| `ERR_DEPENDENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PREDETERMINATION_NOT_FOUND` | 404 |
| `ERR_FEE_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PROVIDER_TERMINATED` | 409 |
| `ERR_PROVIDER_BUSY` | 409 |
| `ERR_SCHEDULE_OVERLAP` | 409 |
| `ERR_TIMELY_FILING` | 422 |
| `ERR_RETROACTIVE_PREDETERMINATION` | 422 |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 |
| `ERR_COB_CONFIG_INVALID` | 422 |
| `ERR_INVALID_PLAN_CONFIG` | 422 |
| `ERR_ANNUAL_MAX_EXCEEDED` | 422 |
| `ERR_INVALID_ATTACHMENT` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NO_FEE_SCHEDULE` | 422 |
| `ERR_STALE_VERSION` | 412 |
