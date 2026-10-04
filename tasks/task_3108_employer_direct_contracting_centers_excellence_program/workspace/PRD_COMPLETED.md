# COE Bundles API — Product Requirements Document

## 1. Introduction

Self-funded employers increasingly contract directly with centers of excellence rather than paying fee-for-service claims through a carrier. Under such an arrangement, the clinic quotes a single bundled case rate for an entire surgical episode — the procedure itself, the related care surrounding it, and a warranty window during which qualifying readmissions are absorbed by the provider — and the employer's members gain access to eligibility screening, mandatory second-opinion review, and travel and lodging benefits for the patient and, where negotiated, one companion.

This document specifies the Employer Direct Contracting Centers of Excellence platform API, mounted under `/coe`. The platform administers the full lifecycle of that arrangement: program configuration (employers, baseline rate books, bundle templates), negotiated case-rate contracts with capacity limits and a governed repricing process, patient intake with idempotent episode creation, screening and second-opinion review that may conclude surgery is unnecessary, scheduling with urgency-based priority, pre- and post-operative care coordination with local providers, warranty-window accountability with cost absorption, multi-entity claim submission and adjudication against the bundle, and monthly employer reporting on avoided procedures and outcomes.

Because a single episode spans weeks of coordination and touches clinical, financial, and administrative actors simultaneously, the API leans on a logical episode day counter, optimistic concurrency tokens on every episode mutation, and a deterministic waterfall for claim adjudication. The sections that follow define the system-wide contracts first, then walk the business workflows in narrative form, and finally tabulate the endpoints and error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A header that is present but blank or whitespace-only counts as missing, and the system label is never a valid `X-User-Role` value — it exists only to attribute automatic transitions in this document, so sending it is rejected as an undeclared role. The platform recognizes exactly six roles: `ProgramAdmin`, `EmployerRep`, `CareCoordinator`, `PhysicianReviewer`, `ClaimsAdmin`, and — as a non-actor actor label used in this document for automatic transitions — the system itself. A caller whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The roles divide into three identity models. When `X-User-Role` is `EmployerRep`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's employer foreign-key field to `X-User-ID`, and acting on a resource chain owned by a different employer — including generating a report for another employer — is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403). When `X-User-Role` is `ProgramAdmin`, `CareCoordinator`, `PhysicianReviewer`, or `ClaimsAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the clinic-side roles are not employer-scoped, and `ProgramAdmin` is global. The server may record an opaque identifier where a workflow calls for it — notably, a recorded second-opinion review captures the acting reviewer's user id in its `reviewer_id` field — but it never compares such an identifier to an entity's `id`.

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

A request to a path the API does not define is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

List endpoints paginate through the `limit` and `offset` query parameters. When `limit` is not supplied it defaults to 10; the minimum accepted value is 1 and the maximum is 100. `offset` defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Because every resource created under the same logical-clock instant shares a `created_at`, ties on `created_at` are broken by creation order so the sort is stable.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that starts at 1 at creation and increments on every mutation of the resource. Any mutation — including system-driven side effects such as a cascade cancellation — refreshes `updated_at` and increments `version` on each resource it touches.

Two record types are exceptions. A `Screening` and a `SecondOpinionReview` are append-only log entries: each carries only `id` and `created_at` from the common set, and both `updated_at` and `version` are absent. They are immutable once created, and no update endpoint exists for them. A `Readmission` does carry the full common field set, but its computed fields are fixed at recording and never change thereafter.

### 2.5. Monetary Values and Precision

All monetary quantities are integer cents. There is no floating-point money anywhere in the platform. The single division that appears in a financial computation — the outlier share applied to billed excess — truncates to whole cents rather than rounding. Percentages and day averages surfaced on employer reports are the only non-integer outputs in the system; they are expressed at exactly 2 decimal places using round-half-up and are serialized as JSON numbers (for example 33.33, or 0.0 for an empty cohort).

### 2.6. Optimistic Concurrency Control

The episode aggregate and the contract reprice path are protected by optimistic concurrency control, expressed purely in stale-version terms — never in terms of requests overlapping in time.

Every episode mutation — recording a second-opinion review, scheduling or rescheduling the surgery day, marking surgery complete, discharging the patient, submitting a claim, and administering a travel or lodging benefit — must carry `expected_episode_version` equal to the episode's current `version` as the client last observed it. (Within the episode model this client-supplied token is referred to as the episode's `expected_system_version` input.) When the episode's `version` has advanced since that observation — for example because a screening auto-transition bumped the version between the client's read and this write — the mutation is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than applied against an out-of-date episode. Two coordinator-internal steps are exempt and carry no version token: advancing the episode day counter, and recording a readmission. Endpoints not named here do not take a version field.

A reprice amendment against a contract must likewise carry `expected_contract_version` equal to the contract's current `version`. When the contract's version has advanced since the client last read it — for example because a prior accepted amendment already changed the price schedule — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client cannot reprice against a superseded price schedule.

### 2.7. The Logical Clock and the Episode Day Counter

The platform runs on a logical clock, never on wall-clock time. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z, and it moves only when a `ProgramAdmin` sets it to a supplied `to_iso8601` instant through the test-driving capability described in §4. The logical clock drives contract coverage-window checks and calendar-month bucketing for capacity gates and employer reports. The 30-day reprice prior-notice rule is measured purely on the episode day counter and the amendment day stamps (§3.2, §3.4), not on the clock.

Each episode maintains `screen_seq`, a monotonic per-episode day counter that starts at 0 at intake and increments by exactly one on every screening document, every recorded review, every scheduling action, every surgery completion, every discharge, every recorded readmission, and every day-counter advance — including the automatic transitions the system performs between intake and review, and the cascade cancellation of §2.8. Care plan item creation, completion, and waiver are not day-counter events and never increment `screen_seq`. Advancing the day counter is accepted on any non-terminal episode: outside `POST_OP_TRACKING` the advance simply increments `screen_seq` and the episode's `version`, and the warranty-horizon closure check of §3.6 runs only while the episode is in `POST_OP_TRACKING`; an advance on a terminal episode is rejected with `ERR_INVALID_STATE`. The clock-setting capability responds with the new clock value in a `current_utc` field. Sequence stamps derived from it (`scheduled_start_seq`, `surgery_done_seq`, `discharge_seq`, `warranty_end_seq`, `warranty_close_seq`, and the per-record `screen_seq` stamped onto screenings and reviews) order everything that happens on the episode and define the warranty window and closure horizon. An episode's `screen_seq` of 0 on `scheduled_start_seq`, `surgery_done_seq`, `discharge_seq`, `warranty_end_seq`, or `warranty_close_seq` means "not yet reached": the scheduled day starts at 0 until something is scheduled, the surgery and discharge stamps stay 0 until those events occur, and the warranty stamps stay 0 until discharge.

### 2.8. Hierarchical Consistency and Cascades

Every record subordinate to an episode — screenings, reviews, claims, readmissions, benefits, and care plan items — carries an `episode_id` identifying the episode it belongs to, and every cascade acts through that linkage. Termination flows downhill and never leaves dependents dangling. Terminating an employer terminates every one of its contracts still in `DRAFT` or `ACTIVE`, and each contract termination in turn cancels every episode on that contract that has not yet been approved — episodes in `INTAKE_PENDING`, `SCREENING`, `SOR_PENDING`, or `SOR_REVIEW` move to `CANCELLED` — while every `OPEN` care plan item on a cancelled episode is set to `WAIVED`. Each cancelled episode has its `screen_seq` incremented and its `version` bumped by the cancellation. Benefits already administered on episodes that remain open are untouched by the cascade; they are released later, when the episode reaches any terminal state, per the closure rules in §3. Episode status never regresses: activity recorded during post-operative tracking re-asserts `POST_OP_TRACKING` after any side-effect evaluation rather than moving the episode backwards.

### 2.9. Nested Resource Retrieval

Endpoints whose paths contain multiple identifiers — for example a screening listed under an episode — validate path identifiers sequentially from left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, before any later identifier or any business rule is examined.

### 2.10. Validation Order

When several checks could reject the same request, the platform evaluates them in a fixed priority order, and the first failure determines the error returned. The order is:

1. Authentication — both headers present and the role declared (`ERR_UNAUTHENTICATED`).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Employer scope for `EmployerRep` callers (`ERR_FORBIDDEN_SCOPE`).
4. Path existence, resolved left to right (`ERR_NOT_FOUND`).
5. Request body well-formedness — required fields present, enums valid, types correct (`ERR_INVALID_REQUEST`). An absent or empty request body is treated as an empty JSON object, a body that parses to a non-object is rejected at this layer, and a required string field rejects empty or whitespace-only values. A malformed `period_month` that is not in YYYY-MM form is rejected at this layer with `ERR_MONTH_FORMAT_INVALID` (HTTP 400), and an unrecognized `view` query value with `ERR_VIEW_UNKNOWN` (HTTP 400).
6. Current-state legality of the transition or action (`ERR_INVALID_STATE`, HTTP 409) — for example a screening submitted on an already-approved episode, a review on an episode still in `SCREENING`, or adjudication of a claim already `PAID`.
7. Optimistic concurrency tokens (`ERR_STALE_VERSION`, HTTP 412).
8. Business-temporal checks — coverage window at approval and strictly-future scheduling (`ERR_OUTSIDE_COVERAGE_WINDOW`, HTTP 422).
9. Structural and aggregate business rules (HTTP 409): contract window overlap (`ERR_CONTRACT_WINDOW_OVERLAP`), component sum (`ERR_COMPONENT_SUM_MISMATCH`), implant cap (`ERR_IMPLANT_CAP_EXCEEDED`), scheduling priority (`ERR_PRIORITY_BLOCKED`), duplicate bundle-case claim (`ERR_DUPLICATE_CASE_CLAIM`), intake idempotency conflict (`ERR_DUPLICATE_INTAKE_REQUEST`), and one active episode per patient per family (`ERR_ACTIVE_EPISODE_EXISTS`).
10. Fiscal and capacity rules (HTTP 422): the monthly and concurrent capacity gates (`ERR_CAPACITY_EXCEEDED`) and the benefit pool (`ERR_BENEFIT_POOL_EXCEEDED`).
11. Clinical safety and closure gates (HTTP 422): required care items outstanding (`ERR_REQUIRED_CARE_INCOMPLETE`) and unresolved claims at closure (`ERR_PENDING_CLAIMS`).
12. Referential usability of foreign-key targets (HTTP 422): patient-to-employer mismatch (`ERR_PATIENT_EMPLOYER_MISMATCH`), a retired template at contract creation (`ERR_TEMPLATE_RETIRED`), and a terminated employer at activation or intake (`ERR_EMPLOYER_TERMINATED`).

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Employers, Rate Books, and Bundle Templates

A `ProgramAdmin` onboards a self-funded employer by registering its `legal_name`, its `ein` (intended unique across employers, though registration does not reject a duplicate), and the `baseline_rate_book` it will be measured against — stored as supplied, without validating that the referenced rate book exists. A rate book carries a `book_code` such as "MSDRG-2026" (intended unique, though creation does not reject a duplicate) and a `rates` map from procedure family to the baseline rate in cents for the underlying procedure, whose values must be integers — a non-integer rate value is rejected with `ERR_INVALID_REQUEST`; these baseline rates anchor both the avoided-cost estimate on employer reports and the employer-scoped view of an episode's estimated total. A new employer starts `ACTIVE`. An employer can later be terminated — termination requires the employer to still be `ACTIVE`, so terminating an already-terminated employer fails with `ERR_INVALID_STATE` — which ends its participation and triggers the cascade described in §2.8; a terminated employer blocks both new contract activations and new episode intakes with `ERR_EMPLOYER_TERMINATED`. Employers can be listed with optional `status` and `baseline_rate_book` filters alongside the standard `limit` and `offset` pagination parameters.

Bundle templates describe what a negotiated episode covers. Each template names a `procedure_family` — one of `CARDIAC`, `ORTHO_JOINT`, `BARIATRIC`, or `SPINE` — a human-readable `label` such as "Primary Total Knee (OP)", a `warranty_days` length of at least 1 defining the related-care warranty window, an `implant_component_cap_cents` ceiling (zero or greater) on the implant carve-out inside the bundle price, and a `readmit_policy` of either `RELATED_ONLY` or `ALL_CAUSE` scoping which readmissions the warranty absorbs. Templates start `ACTIVE`; a `ProgramAdmin` may retire one, moving it to `RETIRED`, after which it cannot seed new contracts — attempting to create a contract against a retired template fails with `ERR_TEMPLATE_RETIRED` — while contracts already created against it are unaffected. Retiring requires the template to still be `ACTIVE`; retiring an already-retired template fails with `ERR_INVALID_STATE`.

### 3.2. Contracts: Negotiation, Activation, Repricing, Termination

A contract binds an employer to a template for a coverage window. At creation the `ProgramAdmin` supplies the `employer_id` and `template_id`, the window bounds `effective_from` (inclusive) and `effective_to` (exclusive, and strictly later than the start), the negotiated `bundle_price_cents` (greater than zero), a `rate_components` map breaking the price into facility, professional, implant, and anesthesia components in cents, an `outlier_threshold_cents` level (greater than zero) at which provider billing triggers outlier sharing, the employer's `outlier_share_pct` of the excess (an integer percent from 0 to 100), the `episode_cap_per_month` and `concurrent_capacity` limits (each zero or greater), the per-episode `travel_benefit_cents` and `lodging_benefit_cents` pools, and whether `companion_allowed` extends travel and lodging coverage to one companion. Naming an employer or template that does not exist fails with `ERR_NOT_FOUND`. The component keys themselves are not constrained — any non-empty map of integer-valued components is accepted — but structural checks guard the price itself: an empty components map fails with `ERR_COMPONENT_SUM_MISMATCH`, the component values must sum exactly to the bundle price, otherwise creation fails with `ERR_COMPONENT_SUM_MISMATCH`; and the implant component, when an `implant` key is present, must not exceed the template's cap, otherwise `ERR_IMPLANT_CAP_EXCEEDED`. The creation-time price and components are retained internally as the pre-amendment schedule that the LOCKED resolution of §3.4 falls back to. A new contract starts `DRAFT`, pins the template's current version into `template_version` at creation, and opens with an empty `change_history` and a `reprice_count` of zero.

Activation moves a contract from `DRAFT` to `ACTIVE` and is allowed only while the employer is still `ACTIVE` and no other `ACTIVE` contract exists for the same employer and the same template procedure family whose half-open coverage window overlaps this one. Windows that merely share an endpoint — one ending exactly when the other begins — do not overlap and both may activate. A genuine overlap is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`.

While `ACTIVE`, a contract's price can be amended through repricing. The amendment carries `expected_contract_version` (per §2.6), a `new_bundle_price_cents` greater than zero, and `new_rate_components` whose values must again sum exactly to the new price with the implant component inside the template cap — the same `ERR_COMPONENT_SUM_MISMATCH` and `ERR_IMPLANT_CAP_EXCEEDED` guards as creation. An accepted amendment appends an entry recording the new price, the new components, the `effective_from_seq` at which it took effect, and the `amended_at` logical-clock timestamp of acceptance to the contract's `change_history`, increments `reprice_count` by one, updates `bundle_price_cents` and `rate_components` to the new values, and bumps the contract's `version`. The `effective_from_seq` is stamped from a platform-wide amendment day counter that lives on the same logical-day axis as each episode's `screen_seq` and is shared by all contracts: it starts at 0 at server startup and increments by exactly one each time an amendment is accepted on any contract, so the first accepted amendment anywhere carries `effective_from_seq` 1, the second 2, and so on, independent of how many episode days any episode has burned. The contract's `status` stays `ACTIVE` through repricing. Termination from either `DRAFT` or `ACTIVE` moves the contract to `TERMINATED` and fires the episode cascade of §2.8; terminating an already-terminated contract fails with `ERR_INVALID_STATE`. Contracts can be listed with optional `employer_id`, `template_id`, and `status` filters.

### 3.3. Patient Registration and Episode Intake

Patients are registered under an employer by a `CareCoordinator` or `ProgramAdmin` with a `full_name`, a `dob` (conventionally YYYY-MM-DD, though the shape is not validated and any non-empty string is accepted), and a `member_id` (intended unique within that employer's health plan, though registration does not reject a duplicate); the patient record keeps the owning `employer_id`, and naming an employer that does not exist fails with `ERR_NOT_FOUND`. Patients can be listed globally with an optional `employer_id` filter, or per employer.

A `CareCoordinator` opens an episode by naming the `patient_id`, the `contract_id`, an `intake_request_id`, and optionally a `triage_rank` — 0 for elective (the default) or 1 for urgent. Intake is idempotent per employer on the `intake_request_id`: a duplicate submission with the identical payload replays the original 201 response, while the same key carrying a different payload is a conflict rejected with `ERR_DUPLICATE_INTAKE_REQUEST`. Payload identity is judged on the triple of `patient_id`, `contract_id`, and `triage_rank`, and the replay returns the original episode as it currently stands, not a snapshot of its intake-time state. Naming a patient or contract that does not exist fails with `ERR_NOT_FOUND`. The patient must belong to the employer that owns the contract, else `ERR_PATIENT_EMPLOYER_MISMATCH`, and a patient may hold at most one non-terminal episode per procedure family — a second intake in a family where an episode is still live fails with `ERR_ACTIVE_EPISODE_EXISTS`. The new episode starts in `INTAKE_PENDING` with `screen_seq` at 0, and its `family` is copied from the contract's pinned template at intake so later template changes cannot reclassify an in-flight episode.

### 3.4. Screening and Second-Opinion Review

Screening is document-driven. A `CareCoordinator` submits screening documents — each with a `doc_type` of `IMAGING`, `LAB`, `NOTE`, or `CONSENT` and a `result` of `CANDIDATE` or `NOT_A_CANDIDATE` — against the episode. The first document moves the episode from `INTAKE_PENDING` to `SCREENING`; further documents while in `SCREENING` keep it there. Every submission increments the episode's `screen_seq` by one and stamps the screening record with that sequence value. Two automatic transitions follow the just-recorded document: a `CANDIDATE` result moves the episode `SCREENING → SOR_PENDING` immediately, consuming one additional sequence step for the auto-transition itself; a `NOT_A_CANDIDATE` result moves it `SCREENING → CANCELLED` immediately, likewise incrementing `screen_seq`.

Once awaiting review, a `PhysicianReviewer` records a second-opinion `conclusion` of `SURGERY_INDICATED`, `SURGERY_UNNECESSARY`, or `MORE_INFO_NEEDED`, carrying `expected_episode_version` per §2.6. The review record captures the acting reviewer's id in `reviewer_id` and snapshots the episode's status before the review in `prev_status` (`SOR_PENDING` or `SOR_REVIEW`), which is what makes the `MORE_INFO_NEEDED` branch well-defined: from `SOR_PENDING` it moves the episode to `SOR_REVIEW`, and from `SOR_REVIEW` it keeps it there, each time incrementing `screen_seq` and stamping the review. Both `SOR_PENDING → SOR_REVIEW` and the deeper `SOR_REVIEW` loop may later resolve identically.

A conclusion of `SURGERY_UNNECESSARY` — from either `SOR_PENDING` or `SOR_REVIEW` — ends the episode as `AVOIDED`: every `ADMINISTERED` travel or lodging benefit on the episode is `RELEASED`, every `OPEN` care plan item is `WAIVED`, `screen_seq` increments once more, and the resulting sequence value becomes the episode's terminal stamp that drives monthly avoided-procedure counting in employer reports.

A conclusion of `SURGERY_INDICATED` — again from either `SOR_PENDING` or `SOR_REVIEW` — is the approval gate, and it enforces four preconditions. The contract must be `ACTIVE` — an approval attempted while the contract is not `ACTIVE` fails with `ERR_INVALID_STATE`. The approval must fall inside the contract's coverage window — the clock date must be at or after `effective_from` and strictly before `effective_to` — else `ERR_OUTSIDE_COVERAGE_WINDOW`. Two distinct capacity gates then apply, and a contract can pass one and fail the other. The monthly gate counts episodes on the contract in any of `APPROVED`, `SCHEDULING`, `PRE_OP`, `SURGERY_DONE`, `POST_OP_TRACKING`, or `CLOSED` whose approval stamp's clock date falls in the current calendar month; approval proceeds only while that count is below `episode_cap_per_month`, so reaching the cap exactly is rejected with `ERR_CAPACITY_EXCEEDED` and a cap of zero forbids all approvals. The concurrent gate counts episodes in `APPROVED`, `SCHEDULING`, `PRE_OP`, `SURGERY_DONE`, or `POST_OP_TRACKING`; approval proceeds only while that count is below `concurrent_capacity`, else `ERR_CAPACITY_EXCEEDED`. Unlike the monthly gate, concurrent capacity frees up as episodes close.

Approval also locks the episode's price basis, recorded in `price_rule` as `LOCKED` or `REPRICED` together with the `applied_bundle_price_cents` and `applied_rate_components` snapshot. When the contract has never been repriced (`reprice_count` is zero), the episode locks the contract's original price and components. When amendments exist, the 30-day prior-notice rule decides: if the gap between the episode's `screen_seq` at approval and the latest amendment's `effective_from_seq` is at least 30 days — a gap of exactly 30 qualifies — the episode is `REPRICED` onto the latest amendment's price and components; if the gap is under 30 days, the episode stays `LOCKED` onto the price schedule in force before that latest amendment, which is the contract's original price when exactly one amendment exists and otherwise the previous amendment's price. The two `LOCKED` resolutions are deliberately different lookups. The approval transition increments `screen_seq`, stamps the episode's approval sequence from the post-increment value, and bumps the episode's `version`. `price_rule` and the applied price fields stay null until approval resolves them, and a review whose conclusion fails a gate is rejected before the review record is written, so no review entry persists from a failed attempt.

### 3.5. Scheduling, Pre-Operative Coordination, and Surgery

An approved episode is scheduled by a `CareCoordinator` supplying a `requested_day_seq` and `expected_episode_version`. Scheduling is strictly into the future: the requested day must be greater than the episode's `screen_seq` at the time of the call, otherwise `ERR_OUTSIDE_COVERAGE_WINDOW`. An urgency gate protects earlier-approved urgent cases: an elective episode (`triage_rank` 0) cannot be scheduled while any other episode on the same contract and family sits in `APPROVED` with `triage_rank` 1 and an earlier approval stamp — that situation is rejected with `ERR_PRIORITY_BLOCKED`. Urgent episodes are never blocked by this gate; among urgent episodes, priority is earliest approval stamp, then earliest `created_at`, never the resource id. A successful schedule moves the episode `APPROVED → SCHEDULING`, records `requested_day_seq` into `scheduled_start_seq`, increments `screen_seq`, and bumps `version`. The same action on a `SCHEDULING` episode reschedules it to a new `requested_day_seq` under the same future-day and priority rules.

Care coordination with local providers is tracked as care plan items, each carrying a `phase` of `PRE_OP` or `POST_OP`, the `local_provider_name` the item is handed to, and a `required` flag. Care items can be created only while the episode is in `SCHEDULING` or `PRE_OP`. The first `PRE_OP` item created on a `SCHEDULING` episode moves it into `PRE_OP` — a `POST_OP` item offered while the episode is still in `SCHEDULING` is rejected with `ERR_INVALID_STATE`; additional items of either phase can be added while in `PRE_OP`, each created `OPEN`. Care item creation, completion, and waiver carry no `expected_episode_version` and do not touch the episode's day counter; only the `SCHEDULING → PRE_OP` transition bumps the episode's `version`. A coordinator later marks an item `DONE` or waives it to `WAIVED`; both actions require the item to still be `OPEN`.

Marking surgery complete moves the episode `PRE_OP → SURGERY_DONE` and carries `expected_episode_version`. It is blocked while any required `PRE_OP` item is still `OPEN` (`ERR_REQUIRED_CARE_INCOMPLETE`), and surgery cannot complete before its scheduled day — the current `screen_seq` must be at least `scheduled_start_seq`. The transition stamps `surgery_done_seq` from the post-increment `screen_seq` and bumps `version`.

Discharge moves the episode `SURGERY_DONE → POST_OP_TRACKING` under the same concurrency token and opens the warranty window: `discharge_seq` is stamped from the post-increment `screen_seq`, `warranty_end_seq` is set to the discharge stamp plus the template's `warranty_days`, and `warranty_close_seq` is set seven days beyond the warranty end — a quiet-tail horizon after which an uneventful episode closes itself. The warranty window is half-open: it includes the discharge day and runs up to but does not include `warranty_end_seq`.

### 3.6. The Warranty Window: Post-Operative Tracking, Readmissions, and Closure

During `POST_OP_TRACKING` the episode's day counter is advanced one day at a time by a `CareCoordinator`; this is a coordinator-internal step and carries no concurrency token. When an advance brings `screen_seq` to or beyond `warranty_close_seq`, the episode closes — provided no required `POST_OP` care item is still `OPEN` (`ERR_REQUIRED_CARE_INCOMPLETE`) and no claim on the episode is still `PENDING` (`ERR_PENDING_CLAIMS`). The same closure fires on a later advance when the horizon had already passed but closure was previously blocked — for instance when a pending claim was resolved only after the close sequence had passed. Closure sets `closed_outcome` to `READMITTED` when any readmission on the episode was recorded inside the warranty window, otherwise `CLEAN`; releases every `ADMINISTERED` benefit to `RELEASED`; and converts every still-unpaid `APPROVED` claim to `ABSORBED`, meaning the approved amount is never remitted. `closed_outcome` is null until closure occurs.

Readmissions are recorded by a `CareCoordinator` with a `related` flag and the `provider_billed_cents` cost; like day advances, this step carries no concurrency token and does not change the episode's status — `POST_OP_TRACKING` is re-asserted after recording. The record is stamped with `recorded_seq` from the episode's counter, and two fields are computed once at recording and never change: `out_of_window` is true when the recorded sequence is at or beyond `warranty_end_seq`, and `absorbed_cents` is the provider's warranty absorption. Out of window, nothing is absorbed — the employer bears the cost. In window, an `ALL_CAUSE` template absorbs the full billed amount, while a `RELATED_ONLY` template absorbs the full billed amount only when the readmission is clinically related to the index procedure and absorbs nothing otherwise.

### 3.7. Claim Submission and Adjudication

A bundle episode spans multiple provider entities, and a `ClaimsAdmin` submits claim lines against it with a `claim_type` of `BUNDLE_CASE`, `RELATED_CARE`, `TRAVEL`, `LODGING`, or `READMISSION`; a `submitting_entity` of `HOSPITAL`, `SURGERY_CENTER`, `ANESTHESIA_GROUP`, or `TRAVEL_VENDOR`; the episode-relative `service_date_seq`; the `billed_cents` amount (zero or greater); `expected_episode_version` per §2.6; and an `is_readmit_related` flag, which may accompany any claim type — it is stored and echoed on the claim record but consulted only for `READMISSION` claims. Submission on a terminal episode is rejected with `ERR_INVALID_STATE` before the version token is examined. Submission creates the claim in `PENDING` with `adjudicated_payable_cents` and `adjudication_reason` unset and bumps the episode's `version`.

Adjudication evaluates the claim's rules as a waterfall: the first failing rule moves the claim to `DENIED` with that rule's reason code recorded in `adjudication_reason`, `adjudicated_payable_cents` set to zero; a claim that clears every rule is `APPROVED` with its payable recorded and its `adjudication_reason` recorded as `APPROVED`. Denied and approved claims are both outcomes of the same adjudication action on a `PENDING` claim; an approved claim is later paid (`APPROVED → PAID`) by a `ClaimsAdmin`, and as §3.6 describes, an approved claim left unpaid when the episode closes becomes `ABSORBED`.

For a `BUNDLE_CASE` claim, the episode's price basis must be resolved — always true after approval. Anti-fraud ordering comes next: the service day must be at or after this episode's `surgery_done_seq` — an episode with no recorded surgery fails this rule by definition — else denial with reason `SERVICE_BEFORE_SURGERY` (surfaced to the submitter as `ERR_CLAIM_BEFORE_SURGERY`); another episode's surgery stamp is never consulted, because filing against the wrong episode is caught by the foreign key itself. Only one bundle case may ever pay: if any other claim on the episode of the same type stands in `APPROVED`, `PAID`, or `ABSORBED`, the claim is denied with reason `DUPLICATE_BUNDLE_CASE` (`ERR_DUPLICATE_CASE_CLAIM`). The payable then decomposes in pinned order: the excess is the billed amount above the contract's `outlier_threshold_cents`, floored at zero; the outlier payable is that excess multiplied by `outlier_share_pct` and divided by 100, truncated to whole cents; and the payable is the episode's `applied_bundle_price_cents` plus the outlier payable. Because the applied basis comes from the approval-time price determination, a `LOCKED` episode pays against the original price snapshot while a `REPRICED` episode pays against the latest amendment, and changing the basis changes the payable for the same billed amount.

For a `RELATED_CARE` claim, the episode must be in `POST_OP_TRACKING` or `CLOSED`, and the service day must fall inside the half-open warranty window from `discharge_seq` up to but not including `warranty_end_seq`, else denial with reason `OUTSIDE_WARRANTY_WINDOW` (`ERR_CLAIM_OUTSIDE_WARRANTY`). The payable is the billed amount capped at what remains of the bundle: the episode's `applied_bundle_price_cents` minus the payables already approved or paid on this episode's `BUNDLE_CASE` and `RELATED_CARE` claims, floored at zero — so approval with a payable of zero is possible once the bundle is exhausted.

For `TRAVEL` and `LODGING` claims, the episode must have reached `APPROVED` at some point — benefits exist only under a live bundle — else `ERR_EPISODE_NOT_APPROVED`. The payable draws from the same per-episode pool ledger that benefit administration debits: the contract's pool for that kind, minus the amounts of the episode's `ADMINISTERED` benefits of that kind, minus payables already approved or paid on claims of the same type. The claim is paid the billed amount up to the remaining pool — a partial draw is allowed — and denied with reason `BENEFIT_POOL_EXHAUSTED` (`ERR_BENEFIT_POOL_EXCEEDED`) only when nothing remains.

For a `READMISSION` claim, a readmission record must exist on the episode whose `recorded_seq` falls inside the warranty window, else denial with reason `READMISSION_OUT_OF_WINDOW` (`ERR_NO_IN_WINDOW_READMISSION`, also surfaced as `ERR_CLAIM_OUTSIDE_WARRANTY` for the window dimension). The template's scope then applies: under `RELATED_ONLY`, a claim whose `is_readmit_related` is false is denied with reason `UNRELATED_READMISSION` (`ERR_READMISSION_POLICY_SCOPE`), while an `ALL_CAUSE` template ignores the flag. The matching readmission is the earliest-recorded in-window readmission on the episode. The payable is the billed amount minus that readmission's `absorbed_cents`, floored at zero — full absorption yields an approved claim that pays nothing.

### 3.8. Travel and Lodging Benefit Administration

Alongside claims, a `CareCoordinator` administers benefits directly: each benefit names a `kind` of `TRAVEL` or `LODGING`, a `traveler` of `PATIENT` or `COMPANION`, an `amount_cents` greater than zero, and `expected_episode_version` per §2.6; creation bumps the episode's `version`. A benefit may be administered in any non-terminal episode status; administering one on a terminal episode is rejected with `ERR_INVALID_STATE`. A companion benefit is only available when the contract's `companion_allowed` flag permits it, else `ERR_BENEFIT_KIND_MISMATCH`. Administration draws against the same pool ledger used at claim adjudication: the amount must fit within the remaining pool for its kind, where an amount exactly equal to the remainder succeeds and one cent over fails with `ERR_BENEFIT_POOL_EXCEEDED`. A benefit is created `ADMINISTERED` and stays outstanding until the episode reaches any terminal state — `CLOSED`, `AVOIDED`, or `CANCELLED` — at which point it is `RELEASED` and no longer counts against the pool or the estimate.

### 3.9. Episode Estimates and Employer Reporting

Reading a single episode computes `estimated_total_billed_cents` on the fly, in one of two variants selected by the `view` query parameter. Episode intake and mutation responses also carry `estimated_total_billed_cents`, computed on the default `employer` view; list responses do not carry the estimate. The default `employer` view anchors on the employer's baseline rate book: the baseline rate for the episode's `family` plus the unreleased accrual — the sum of `ADMINISTERED` benefit amounts on the episode. The `clinic` view anchors on the provider side: the episode's `applied_bundle_price_cents` (zero until approval resolves the price basis), plus an outlier projection when the episode's internal outlier flag is set — the flag and its expected-billing figure are internal bookkeeping that no endpoint sets — (the expected billing above the contract's `outlier_threshold_cents`, floored at zero, multiplied by `outlier_share_pct`, divided by 100, and truncated to cents), minus the same unreleased accrual. Any other `view` value is rejected with `ERR_VIEW_UNKNOWN`. Both variants require the employer's rate book to carry a rate for the episode's family; when it does not, the estimate — and the avoided-cost reporting that shares the lookup — fails with `ERR_RATE_FAMILY_MISSING`. That failure surfaces only where the estimate is authoritative, namely the single-episode read under either view and report generation; intake and mutation responses instead carry a null `estimated_total_billed_cents`. Episodes can be listed with optional `contract_id`, `patient_id`, and `status` filters.

Monthly employer reports are generated on demand for a `period_month` in YYYY-MM form — anything else fails with `ERR_MONTH_FORMAT_INVALID`, including a month component outside 01–12 — by a `ProgramAdmin` or by the `EmployerRep` of that employer. Both initial generation and regeneration respond with `201 Created` and the report snapshot. Generation upserts a snapshot per employer and month: regenerating the same month refreshes the computed fields in place and re-stamps `computed_seq` with the maximum `screen_seq` across the employer's episodes at computation time (0 when the employer has no episodes), so readers can reason about snapshot staleness. The report's `status` is always `GENERATED`. In-month membership is judged by the logical clock date at which each episode's terminal or scheduled stamp was recorded. The snapshot reports: `avoided_procedures_count`, the episodes of this employer that reached `AVOIDED` in the month; `avoided_cost_estimate_cents`, the sum over those episodes of the employer baseline rate for each episode's family; `readmission_rate_pct`, the count of in-month closed episodes with surgery that saw at least one in-window readmission over the count of in-month closed episodes with surgery, expressed as a percentage at 2 decimal places round-half-up, and exactly 0.00 when no such episodes exist; `warranty_absorbed_total_cents`, the sum of `absorbed_cents` over readmissions of in-month closed episodes; and `avg_days_to_schedule`, the mean gap between the approval stamp and the first scheduled day over episodes first scheduled in the month, at 2 decimal places round-half-up, and exactly 0.00 when none were scheduled.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Request bodies, response payloads, and side effects are as specified in §2 and §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coe/employers` | Register a self-funded employer | ProgramAdmin |
| GET | `/coe/employers` | List employers (paginated, filterable) | ProgramAdmin |
| GET | `/coe/employers/{id}` | Get employer | ProgramAdmin, EmployerRep, ClaimsAdmin, CareCoordinator |
| POST | `/coe/employers/{id}/terminate` | Terminate an employer; cascades to contracts and their episodes | ProgramAdmin |
| GET | `/coe/employers/{id}/contracts` | List contracts of an employer | ProgramAdmin, EmployerRep |
| GET | `/coe/employers/{id}/patients` | List patients of an employer | ProgramAdmin, EmployerRep, CareCoordinator |
| GET | `/coe/employers/{id}/reports` | List generated employer reports | ProgramAdmin, EmployerRep |
| POST | `/coe/employers/{id}/reports/generate` | Generate (or regenerate) the monthly outcomes report snapshot | ProgramAdmin, EmployerRep |
| POST | `/coe/bundle-templates` | Create a bundle template | ProgramAdmin |
| GET | `/coe/bundle-templates/{id}` | Get bundle template | ProgramAdmin, EmployerRep, ClaimsAdmin, CareCoordinator, PhysicianReviewer |
| POST | `/coe/bundle-templates/{id}/retire` | Retire a template (blocks new contracts) | ProgramAdmin |
| POST | `/coe/rate-books` | Create a baseline rate book | ProgramAdmin |
| GET | `/coe/rate-books/{id}` | Get a rate book | ProgramAdmin, EmployerRep |
| POST | `/coe/contracts` | Create a bundled case-rate contract (starts DRAFT; pins template version) | ProgramAdmin |
| GET | `/coe/contracts` | List contracts (filterable) | ProgramAdmin |
| GET | `/coe/contracts/{id}` | Get contract | ProgramAdmin, EmployerRep, ClaimsAdmin, CareCoordinator |
| POST | `/coe/contracts/{id}/activate` | Activate a DRAFT contract (overlap gate applies) | ProgramAdmin |
| POST | `/coe/contracts/{id}/reprice` | Amend bundle price/components (OCC on contract version) | ProgramAdmin |
| POST | `/coe/contracts/{id}/terminate` | Terminate a contract; cascades to pre-approval episodes | ProgramAdmin |
| POST | `/coe/patients` | Register a patient under an employer | CareCoordinator, ProgramAdmin |
| GET | `/coe/patients` | List patients (filterable) | ProgramAdmin, CareCoordinator |
| GET | `/coe/patients/{id}` | Get patient | ProgramAdmin, EmployerRep, CareCoordinator, PhysicianReviewer, ClaimsAdmin |
| POST | `/coe/episodes` | Open an episode (intake); idempotent per employer intake key | CareCoordinator |
| GET | `/coe/episodes` | List episodes (filterable) | ProgramAdmin, EmployerRep, CareCoordinator, ClaimsAdmin |
| GET | `/coe/episodes/{id}` | Get episode; computes the estimated total per `view` | ProgramAdmin, EmployerRep, CareCoordinator, PhysicianReviewer, ClaimsAdmin |
| POST | `/coe/episodes/{id}/screenings` | Submit an eligibility screening document | CareCoordinator |
| GET | `/coe/episodes/{id}/screenings` | List screening documents of an episode | ProgramAdmin, CareCoordinator, PhysicianReviewer |
| GET | `/coe/screenings/{id}` | Get a screening document | ProgramAdmin, CareCoordinator, PhysicianReviewer |
| POST | `/coe/episodes/{id}/reviews` | Record a second-opinion review conclusion | PhysicianReviewer |
| GET | `/coe/episodes/{id}/reviews` | List second-opinion reviews of an episode | ProgramAdmin, CareCoordinator, PhysicianReviewer |
| GET | `/coe/reviews/{id}` | Get a second-opinion review | ProgramAdmin, CareCoordinator, PhysicianReviewer |
| POST | `/coe/episodes/{id}/schedule` | Schedule (or reschedule) the surgery day | CareCoordinator |
| POST | `/coe/episodes/{id}/care-items` | Add a pre/post-op care coordination item | CareCoordinator |
| GET | `/coe/episodes/{id}/care-items` | List care plan items of an episode | ProgramAdmin, CareCoordinator, PhysicianReviewer |
| GET | `/coe/care-items/{id}` | Get care plan item | ProgramAdmin, CareCoordinator |
| POST | `/coe/care-items/{id}/complete` | Mark a care item done | CareCoordinator |
| POST | `/coe/care-items/{id}/waive` | Waive a care item | CareCoordinator |
| POST | `/coe/episodes/{id}/surgery-complete` | Mark the surgery performed | CareCoordinator |
| POST | `/coe/episodes/{id}/discharge` | Discharge the patient; opens the warranty window | CareCoordinator |
| POST | `/coe/episodes/{id}/advance-day` | Advance the episode day counter; auto-closes at the warranty horizon | CareCoordinator |
| POST | `/coe/episodes/{id}/readmissions` | Record a readmission inside or outside the warranty window | CareCoordinator |
| GET | `/coe/episodes/{id}/readmissions` | List readmissions of an episode | ProgramAdmin, CareCoordinator, ClaimsAdmin, EmployerRep |
| GET | `/coe/readmissions/{id}` | Get a readmission record | ProgramAdmin, CareCoordinator, ClaimsAdmin, EmployerRep |
| POST | `/coe/episodes/{id}/claims` | Submit a claim line for the bundle | ClaimsAdmin |
| GET | `/coe/episodes/{id}/claims` | List claims of an episode | ProgramAdmin, ClaimsAdmin, EmployerRep |
| GET | `/coe/claims/{id}` | Get claim | ProgramAdmin, ClaimsAdmin, EmployerRep |
| POST | `/coe/claims/{id}/adjudicate` | Adjudicate a PENDING claim | ClaimsAdmin |
| POST | `/coe/claims/{id}/pay` | Pay an APPROVED claim | ClaimsAdmin |
| POST | `/coe/episodes/{id}/benefits` | Administer a travel or lodging benefit under the bundle | CareCoordinator |
| GET | `/coe/episodes/{id}/benefits` | List benefits of an episode | ProgramAdmin, CareCoordinator, EmployerRep |
| GET | `/coe/benefits/{id}` | Get travel/lodging benefit | ProgramAdmin, CareCoordinator, EmployerRep |
| GET | `/coe/reports/{id}` | Get an employer report | ProgramAdmin, EmployerRep |
| POST | `/coe/_clock/set_current_utc` | Set the logical clock (startup default 2026-09-01T00:00:00Z) | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_SCOPE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_OUTSIDE_COVERAGE_WINDOW | 422 |
| ERR_CONTRACT_WINDOW_OVERLAP | 409 |
| ERR_COMPONENT_SUM_MISMATCH | 409 |
| ERR_IMPLANT_CAP_EXCEEDED | 409 |
| ERR_PRIORITY_BLOCKED | 409 |
| ERR_DUPLICATE_CASE_CLAIM | 409 |
| ERR_DUPLICATE_INTAKE_REQUEST | 409 |
| ERR_ACTIVE_EPISODE_EXISTS | 409 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_BENEFIT_POOL_EXCEEDED | 422 |
| ERR_REQUIRED_CARE_INCOMPLETE | 422 |
| ERR_PENDING_CLAIMS | 422 |
| ERR_PATIENT_EMPLOYER_MISMATCH | 422 |
| ERR_TEMPLATE_RETIRED | 422 |
| ERR_EMPLOYER_TERMINATED | 422 |
| ERR_CLAIM_OUTSIDE_WARRANTY | 422 |
| ERR_READMISSION_POLICY_SCOPE | 422 |
| ERR_CLAIM_BEFORE_SURGERY | 422 |
| ERR_BENEFIT_KIND_MISMATCH | 422 |
| ERR_MONTH_FORMAT_INVALID | 400 |
| ERR_EPISODE_NOT_APPROVED | 422 |
| ERR_NO_IN_WINDOW_READMISSION | 422 |
| ERR_VIEW_UNKNOWN | 400 |
| ERR_RATE_FAMILY_MISSING | 422 |
