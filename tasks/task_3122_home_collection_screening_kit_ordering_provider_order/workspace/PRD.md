# Home Collection Screening API — Product Requirements Document

## 1. Introduction

Health plans and health systems increasingly run colorectal cancer screening programs in which a member can complete a screening at home by returning a self-collection kit through the mail, rather than presenting for a colonoscopy as a first-line test. Operating such a program is an orchestration problem: a patient must be screened for eligibility (age band, risk category, and contraindications that would push them toward a different test modality), a valid provider order must be captured from either the patient's own physician or a telehealth network, the kit must be shipped with collection instructions and stabilization requirements, and the returned specimen must reach laboratory processing before its stabilization window closes. Uncollected kits require a structured reminder cadence and abandonment tracking; inadequate specimens require a bounded recollection loop; positive results require follow-up colonoscopy navigation within a defined window.

This document specifies the Home Collection Screening API, mounted under `/screening`, which supports that full lifecycle. The platform serves five operator communities — program administrators working on behalf of payers and health systems, ordering and telehealth providers, kit fulfillment staff, laboratory technicians, and care navigators — and gives each a clearly bounded slice of the workflow. Programs may operate in a push mode (the plan drives outreach to a defined member population) or a self-serve mode (patients initiate), and the system tracks quality-measure attribution and adherence so that plans can report screening rates against a measure year.

A deliberate design choice underpins the whole API: the server maintains a logical clock rather than consulting wall-clock time, because reminder schedules, abandonment deadlines, stabilization expiry, navigation windows, and adherence windows are all date-driven. Test harnesses and operations teams advance time explicitly, and every time-based auto-transition is evaluated when the clock moves.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which that operator acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. Once the headers are present, the role is matched against the endpoint's authorization list; a role that is not permitted on that endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `ProgramAdmin` — the payer/health-system program operator. This role manages programs, member cohorts, outreach dispatch, exclusions, eligibility determinations (confirm and reject), reminder dispatch, provider registration, patient opt-out, quality-measure reporting, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- `Provider` — the ordering physician or telehealth-network provider. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity; ownership checks on any resource that references a `Provider` compare the resource's foreign-key field to `X-User-ID`. A `Provider` may register patients, capture orders, cancel orders, and read broadly.
- `FulfillmentAgent` — the kit logistics operator. This role creates kits against eligible orders, ships kits, and records returns. When `X-User-Role` is `FulfillmentAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `LabTechnician` — the laboratory operator responsible for accessioning, processing, adequacy determinations, and resulting. When `X-User-Role` is `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Navigator` — the care navigator who schedules and completes colonoscopy navigation for positive results. When `X-User-Role` is `Navigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses order results by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records and `has_more` indicates whether further records exist beyond the returned window.

### 2.4. Common Resource Properties and Server-Minted Identifiers

Most resources carry four system-managed properties: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `updated_at` is refreshed on every mutation of the owning resource. The `version` is an integer that increments by exactly 1 on every mutation of that resource.

Two resource families deliberately carry a lighter footprint. An `OutreachEvent` carries only `id` and `created_at` — both `updated_at` and `version` are absent, because an outreach dispatch is an immutable fact. The same lighter footprint applies to `Reminder` rows and to `ScreeningResult` rows: each carries `id` and `created_at` and carries neither `updated_at` nor `version`. All other entities in this document — `HealthPlanProgram`, `Patient`, `Provider`, `MemberCohort`, `ScreeningOrder`, `ScreeningKit`, `LabSpecimen`, and `QualityMeasureReport` — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

Kit serial numbers are server-minted as well: every `ScreeningKit` receives a unique `kit_serial` at creation, and clients never supply it.

### 2.5. The Logical Clock and Time-Driven Transitions

The server never consults wall-clock time. At startup the logical clock reads 2026-09-01T00:00:00Z, and it advances only when a `ProgramAdmin` operator invokes the clock-setting capability with a `to_iso8601` timestamp, after which the server reports the supplied instant as `current_utc`. Advancing the clock is not a bookkeeping no-op: it is the single trigger that evaluates every time-based auto-transition in the system. When the clock moves, the server sweeps for orders whose abandonment deadline has arrived or passed, for recollection requests that have been waiting beyond their allowance, and for pending or scheduled colonoscopy navigations whose due date has passed, applying each transition described in §3. Implementations must treat clock advancement as the only entry point into those transitions.

### 2.6. Hierarchical Path Resolution

Several resources are addressed through nested paths — a cohort lives under its program, an outreach event under its cohort, a kit under its order, a specimen under its kit. Path parameters are validated left to right: the server confirms that the leftmost identifier exists before examining the next, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). A nested resource whose identifier exists but whose parent chain does not match the path (for example, a cohort that belongs to a different program than the one named in the path) is likewise reported as not found rather than as a mismatch.

### 2.7. Optimistic Concurrency on Kit Creation

Exactly one write operation in this API is guarded by optimistic concurrency control: kit creation against a screening order. A kit-creation request must carry `expected_order_version`, a non-optional field holding the `version` of the `ScreeningOrder` as the client last observed it. If another writer has advanced the order's version since that observation — for example, by creating a replacement kit that legitimately consumed the order's single outstanding-kit slot — the client's view is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check runs after the order's state precondition has been satisfied and before any other business rule on that operation. No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.8. Precision, Rounding, and Calendar Conventions

Integer quantities throughout the system — ages, day counts, sequence ordinals, risk scores, counters — are whole numbers with no fractional part. Rates are the exception: the adherence rate on a quality measure report is rounded to four decimal places using round-half-up, and a rate computed against an empty denominator is reported as exactly 0.0000 rather than being rejected. Day arithmetic is calendar-date arithmetic: adding N days to a timestamp means adding N to its date component, and an interval described as "days inclusive" counts both endpoints. Windows expressed in hours (the stabilization window) are exact timestamp arithmetic.

### 2.9. Validation Ordering

When several validation rules could reject the same request, the server evaluates them in a fixed order and returns the first failure. The order is: authentication context first (missing or empty headers, then role authorization), then resource existence along the path left to right, then request-body well-formedness (required fields present, types correct, enum values known — any failure here is `ERR_VALIDATION`), then state-machine preconditions on the addressed resource, then the optimistic-concurrency version check where one applies, and finally the business rules (patient status, age band, risk category, contraindications, provider and cohort referential checks, in-flight order exclusivity, temporal windows, recollection limits, adequacy, program activity and outreach mode, navigation applicability, and duplicate registration). An operator debugging a rejection can therefore rely on the returned `error_id` naming the earliest failing rule in this ordering, not an arbitrary one.

## 3. Business Logic & Workflows

### 3.1. Program Setup and Member Enrollment

A payer or health system begins by creating a program. A `ProgramAdmin` supplies a unique `program_code`, a human-readable `program_name`, the `measure_year` the program reports against, and the `outreach_mode`, which is either `PUSH` (the program pushes outreach to members) or `SELF_SERVE` (patients initiate on their own). The `is_active` flag defaults to true and governs whether the program may continue enrolling cohorts and dispatching outreach. Newly created programs start with `population_size`, `attributed_count`, and `adherent_count` all at zero; these are system-maintained and never supplied by the client.

Enrollment creates a `MemberCohort` row linking a `patient_id` to the program. The server stamps `enrolled_at` with the logical clock's current date, sets `adherence_window_start` to that same date (inclusive), and sets `adherence_window_end` to the date 364 days after it, so the adherence window spans 365 days inclusive from enrollment. The cohort begins in `ELIGIBLE` status with `attributed` set to true. Enrollment increments the program's `population_size` by one and recomputes the program's attribution counters. Cohort rows may be listed within their program (optionally filtered by `status`), listed across programs with optional `program_id` and `patient_id` filters, or fetched individually by identifier.

Push-mode outreach is dispatched per member. A `ProgramAdmin` initiating outreach supplies a `channel` — one of `MAIL`, `SMS`, or `PHONE` — and a `template_code` identifying the outreach template. Three conditions must hold, in this order: the cohort must currently be in `ELIGIBLE` status, else the request fails with `ERR_COHORT_INVALID_STATE`; the program's `is_active` must be true, else `ERR_PROGRAM_INACTIVE`; and the program's `outreach_mode` must be `PUSH`, else `ERR_PROGRAM_MODE_VIOLATION`. On success the server creates an `OutreachEvent` recording the `cohort_id`, the `channel`, the `template_code`, and a `sent_at` timestamp from the logical clock, and the cohort's status advances `ELIGIBLE → OUTREACH_SENT`. Outreach events are listed per cohort or across the system with an optional `cohort_id` filter.

Exclusion removes a member from the measure. A `ProgramAdmin` may exclude a cohort while it is in either `ELIGIBLE` or `OUTREACH_SENT` status; any other status is rejected with `ERR_COHORT_INVALID_STATE`. Exclusion sets the cohort's `attributed` flag to false and moves the cohort to the terminal `EXCLUDED` status, then recomputes the program's counters. A patient-level opt-out is broader: when a `ProgramAdmin` marks a patient `OPTED_OUT`, every cohort row for that patient currently in `ELIGIBLE` or `OUTREACH_SENT` is moved to `EXCLUDED` and the affected program counters are recomputed.

### 3.2. Patient Registration and Risk Screening

Patients are registered by a `ProgramAdmin` or a `Provider`. Registration captures an `external_ref` (the client-facing reference, such as an MRN or an email surrogate, which must be unique across patients), a `date_of_birth` as an ISO 8601 date, and a `risk_category` of `AVERAGE`, `ELEVATED`, or `HIGH`. Three advisory flags may accompany registration — `recent_symptoms`, `comorbidity`, and `family_history` — each a boolean defaulting to false, plus `contraindication_flags`, a list of contraindication codes defaulting to empty. A new patient's `status` starts at `ACTIVE` and may later become `DECEASED` or `OPTED_OUT`. Attempting to register a patient whose `external_ref` duplicates an existing patient is rejected with `ERR_DUPLICATE_PATIENT` (HTTP 409). Patients may be listed (with an optional `external_ref` filter) or fetched individually.

Alongside registration, the system offers a computed advisory: a weighted risk screen score for a patient. The score adds 5 points if `recent_symptoms` is true, 3 points if `comorbidity` is true, and 2 points if `family_history` is true — each flag contributing its weight when set and zero otherwise, producing a whole-number `score` between 0 and 10. When the score is 6 or higher, the response's `recommended_channel` is `CLINIC`, an advisory that a home kit is not the recommended modality; a score of 5 or lower yields `HOME_KIT_OK`. This score is advisory only — actual order eligibility is governed strictly by the eligibility rules of §3.3, never by this score.

### 3.3. Provider Order Capture and Eligibility Determination

Providers themselves are registered by a `ProgramAdmin`, who supplies the provider's `npi` (National Provider Identifier, unique), a `display_name`, and a `channel` of `ORDERING` (the patient's own physician) or `TELEHEALTH` (a network provider). The provider's `is_active` flag defaults to true; an inactive provider may not issue new orders.

Order capture is performed by a `Provider` or a `ProgramAdmin`, supplying the `patient_id`, the `provider_id`, and optionally a `program_id` and a `cohort_id` linking the order into a program's member cohort. Two referential checks guard creation. First, the referenced provider must be active; an order against a provider whose `is_active` is false is rejected with `ERR_PROVIDER_INACTIVE` (HTTP 422). Second, `program_id` and `cohort_id` must be consistent: either both are supplied or neither is, and when both are supplied the cohort must belong to the named program — any other combination is `ERR_COHORT_PROGRAM_MISMATCH` (HTTP 422). A pure self-serve order, one with no program attachment, leaves both fields unset. On success the order starts in `PENDING_ELIGIBILITY` status, and its `order_channel` is copied from the ordering provider's `channel` at that moment, freezing the channel attribution even if the provider's channel later changes. The order's `recollection_round` starts at 0, its `quality_outcome` starts at `UNRESOLVED`, and `eligible_at`, `shipped_at`, `returned_at`, `abandonment_due_at`, and `active_kit_id` all begin unset.

Eligibility determination is a `ProgramAdmin` decision with two outcomes. Confirmation is guarded by five checks, evaluated in this order: the order must still be in `PENDING_ELIGIBILITY` (otherwise `ERR_ORDER_INVALID_STATE`); the patient must be `ACTIVE` — a patient who is `DECEASED` or `OPTED_OUT` fails with `ERR_PATIENT_NOT_ACTIVE`; the patient's age at the order's creation date must fall within 45 to 75 years inclusive on both ends, failing with `ERR_AGE_OUT_OF_RANGE` otherwise; the patient's `risk_category` must not be `HIGH` — high-risk patients require a different test modality and fail with `ERR_RISK_CATEGORY_EXCLUDED`; and the patient's `contraindication_flags` must be empty, failing with `ERR_CONTRAINDICATION_PRESENT` when any code is present. On confirmation the order transitions `PENDING_ELIGIBILITY → ELIGIBLE`, `eligible_at` is stamped with the logical clock's current instant, and the order's `version` increments. Rejection is simpler: from `PENDING_ELIGIBILITY` (again enforced with `ERR_ORDER_INVALID_STATE`), the order transitions to `REJECTED_INELIGIBLE` and its `version` increments. Rejecting an order never consumes the cohort: if the rejected order carried a `cohort_id`, that cohort remains in `ELIGIBLE` and a later order may pick it up.

Cancellation is available to a `Provider` or `ProgramAdmin` while the order sits in `PENDING_ELIGIBILITY` or `ELIGIBLE`. From either state the order moves to `CANCELLED` with a `version` increment; a cancel attempted from any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409).

### 3.4. Kit Fulfillment, Shipment, and Reminder Cadence

Once an order is `ELIGIBLE`, a `FulfillmentAgent` creates its kit. The request carries `expected_order_version` per the optimistic-concurrency rule of §2.7, and the order's state must be `ELIGIBLE` (else `ERR_ORDER_INVALID_STATE`). A further exclusivity rule applies: no other `ScreeningOrder` for the same patient may currently sit in any of `ELIGIBLE`, `KIT_ORDERED`, `KIT_SHIPPED`, `KIT_RETURNED`, `IN_LAB`, or `RECOLLECTION_REQUESTED` — if one does, creation is rejected with `ERR_ACTIVE_ORDER_EXISTS` (HTTP 409). On success the server creates a `ScreeningKit` in `ORDERED` status with a fresh `kit_serial`, sets the order's `active_kit_id` to the new kit, advances the order `ELIGIBLE → KIT_ORDERED`, and — when the order carries a `cohort_id` — cascades that cohort into `ORDERED` status, whether the cohort was sitting in `ELIGIBLE` or `OUTREACH_SENT`. The order's `version` increments. Kits may be listed (filterable by `order_id` or `status`), listed within their order, or fetched individually.

Shipping is recorded by a `FulfillmentAgent` against the kit. The kit must be in `ORDERED` status (else `ERR_KIT_INVALID_STATE`) and its parent order must be in `KIT_ORDERED` (else `ERR_ORDER_INVALID_STATE`). Shipping stamps `shipped_at` on both kit and order with the logical clock's current instant, moves the kit `ORDERED → SHIPPED` and the order `KIT_ORDERED → KIT_SHIPPED`, computes the order's `abandonment_due_at` as the date 45 days after the ship date, and creates the reminder cadence: exactly three `Reminder` rows with `sequence_no` 1, 2, and 3, whose `scheduled_for` dates are 7, 14, and 28 days respectively after the ship date. All three reminders begin in `SCHEDULED` status with `sent_at` unset. The order's `version` increments.

Reminders are dispatched in batch by a `ProgramAdmin`. Dispatch requires the order to be in `KIT_SHIPPED` (else `ERR_ORDER_INVALID_STATE`) and releases every reminder for that order whose `scheduled_for` date has been reached by the current logical date; each released reminder is stamped with `sent_at` and moves `SCHEDULED → SENT`. Because the cadence offsets are strictly increasing, dispatch is naturally chronological by scheduled date and then by `sequence_no`, and ties are impossible. A reminder still in `SCHEDULED` when its kit is returned, or when its order is abandoned, is moved to `SKIPPED` instead. Reminder rows may be listed per order, listed across orders with optional `order_id` and `status` filters, or fetched individually.

Return is recorded by a `FulfillmentAgent` when the completed kit arrives at the lab dock. The kit must be `SHIPPED` (else `ERR_KIT_INVALID_STATE`) and the order must be `KIT_SHIPPED` (else `ERR_ORDER_INVALID_STATE`). The kit's `returned_at` is stamped, its `stabilization_expires_at` is computed as exactly 72 hours after `returned_at`, and the kit moves `SHIPPED → RETURNED`. The order moves `KIT_SHIPPED → KIT_RETURNED` with its own `returned_at` stamped, every still-`SCHEDULED` reminder on the order flips to `SKIPPED`, and the order's `version` increments.

For operational monitoring, each order exposes a computed turnaround figure in two variants, returned together as `provisional_days` and `return_logistics_days`. Both measure whole days from the ship date. When the order's `returned_at` is set, both variants agree: each is the number of days from the ship date to the return date. When the kit has not been returned, the provisional variant counts days from the ship date to the current logical date, while the return-logistics variant — the one used for adherence reporting — counts the full 45-day abandonment allowance regardless of how much time has actually elapsed. The two variants diverge precisely on unreturned kits, and readers must pick the variant appropriate to their purpose.

### 3.5. Specimen Intake, Stabilization, and Laboratory Processing

A returned kit is accessioned by a `LabTechnician`, which creates a `LabSpecimen` for the kit named by the order's `active_kit_id`. The order must be in `KIT_RETURNED` (else `ERR_ORDER_INVALID_STATE`). The new specimen records its `kit_id` and — denormalized at intake — the `order_id` of the order that owns the kit; it is stamped with `accessioned_at`, starts in `ACCESSIONED` status with `adequacy` set to `PENDING`, and the order advances `KIT_RETURNED → IN_LAB` with a `version` increment. Specimens may be listed (filterable by `kit_id` or `status`), listed for one kit, or fetched individually.

Processing may begin only inside the stabilization window. A `LabTechnician` starting processing on a specimen requires the specimen to be in `ACCESSIONED` status (else `ERR_SPECIMEN_INVALID_STATE`) and requires the logical clock's current instant to be strictly before the kit's `stabilization_expires_at` — a start exactly at the expiry instant is too late and is rejected, along with any later start, with `ERR_STABILIZATION_EXPIRED` (HTTP 422). On success the specimen moves `ACCESSIONED → PROCESSING` with `processing_started_at` stamped, and the kit moves `RETURNED → IN_PROCESSING`.

Adequacy is then determined by a `LabTechnician` supplying an `adequacy` value. An `ADEQUATE` determination records the determination — stamping `adequacy_checked_at` — while leaving a `PROCESSING` specimen in `PROCESSING` so that resulting may follow; the specimen's `adequacy` field becomes `ADEQUATE`. An `INADEQUATE` determination is heavier. The specimen must be in `ACCESSIONED` or `PROCESSING` (else `ERR_SPECIMEN_INVALID_STATE`), and the order's `recollection_round` must be below the maximum of 2 completed recollection cycles — at the limit the request fails with `ERR_RECOLLECTION_LIMIT_REACHED` (HTTP 422) and nothing else changes. Otherwise the specimen's `adequacy` becomes `INADEQUATE` with `adequacy_checked_at` stamped, the specimen moves to `INADEQUATE`, the kit is consumed — moving to `CONSUMED`, with the order's `active_kit_id` cleared — the order's `recollection_round` increments by one, the order transitions `IN_LAB → RECOLLECTION_REQUESTED`, and the order's `version` increments.

A recollection order waits for a replacement kit. A `FulfillmentAgent` creates the replacement exactly as a first kit is created: the order must be in `RECOLLECTION_REQUESTED` (else `ERR_ORDER_INVALID_STATE`), the request carries `expected_order_version` per §2.7, and on success a fresh `ScreeningKit` is created in `ORDERED`, the order's `active_kit_id` is set to it, any `abandonment_due_at` left over from the prior shipment is cleared (it is recomputed when the replacement ships), the order moves `RECOLLECTION_REQUESTED → KIT_ORDERED`, and its `version` increments. The in-flight-order exclusivity rule does not re-apply here because the order's own `RECOLLECTION_REQUESTED` status is the expected starting point.

### 3.6. Result Delivery and Positive-Result Navigation

Resulting finalizes the laboratory work. A `LabTechnician` supplies an `outcome` of `NEGATIVE` or `POSITIVE`. The specimen must be in `PROCESSING` (else `ERR_SPECIMEN_INVALID_STATE`) and its `adequacy` must be `ADEQUATE` — resulting on a specimen whose adequacy is anything else is rejected with `ERR_SPECIMEN_NOT_ADEQUATE` (HTTP 422). On success, a cascade runs: the specimen moves `PROCESSING → RESULTED`; the kit moves to `CONSUMED` and the order's `active_kit_id` is cleared; a `ScreeningResult` is created recording the `order_id`, the producing `specimen_id`, the `outcome`, a `resulted_at` timestamp, and a `delivered_to_provider_at` timestamp — both stamped from the logical clock, since finalization and delivery to the ordering provider happen in the same instant; and the order transitions `IN_LAB → RESULTED` with a `version` increment. Results may be listed (filterable by `order_id` or `specimen_id`), listed for one order, or fetched individually.

The `navigation_status` of the new result depends on its outcome. A `NEGATIVE` result needs no follow-up and starts at `NOT_REQUIRED`. A `POSITIVE` result starts at `PENDING`, and its `navigation_due_at` is computed as the date 90 days after the delivery date — the colonoscopy navigation window. From `PENDING`, a `Navigator` may schedule the follow-up, moving `PENDING → SCHEDULED`; scheduling is only meaningful for `POSITIVE` results, and an attempt against a `NEGATIVE` result fails with `ERR_NAVIGATION_NOT_REQUIRED` (HTTP 422), while an attempt from any `navigation_status` other than `PENDING` fails with `ERR_NAVIGATION_INVALID_STATE` (HTTP 409). Completion, also by a `Navigator`, requires `SCHEDULED` (else `ERR_NAVIGATION_INVALID_STATE`), stamps `navigation_completed_at`, and moves `SCHEDULED → COMPLETED`. A completion is on-time when the completion date falls on or before `navigation_due_at` — the boundary day itself counts as on-time.

Navigation can also lapse without any operator action. When the logical clock advances past `navigation_due_at` while a result's `navigation_status` is still `PENDING` or `SCHEDULED`, the result's navigation moves to `LAPSED`, the owning order's `quality_outcome` becomes `POSITIVE_NAVIGATION_LAPSED`, and the order's `version` increments by one.

### 3.7. Abandonment and Order Termination

Two system-driven transitions close out stalled orders when the logical clock advances. An order sitting in `KIT_SHIPPED` whose `abandonment_due_at` date has been reached or passed transitions `KIT_SHIPPED → ABANDONED`: the outstanding kit moves to `EXPIRED_STABILIZATION`, every still-`SCHEDULED` reminder moves to `SKIPPED`, and the order's `version` increments. An order sitting in `RECOLLECTION_REQUESTED` abandons when the current logical date reaches or passes 30 days after the date on which the order entered `RECOLLECTION_REQUESTED` — that entry date is recoverable from the order's `updated_at` at the moment of that transition — moving `RECOLLECTION_REQUESTED → ABANDONED` with a `version` increment.

An order therefore terminates in one of four states: `RESULTED` after successful laboratory completion, `CANCELLED` by operator action while still early, `ABANDONED` by clock advancement, or `REJECTED_INELIGIBLE` at the eligibility gate. A kit terminates as `CONSUMED` (processed or discarded after an inadequate determination), `EXPIRED_STABILIZATION` (stranded by abandonment), or `CANCELLED`. A specimen terminates as `RESULTED` or `INADEQUATE`.

### 3.8. Quality Measure Attribution and Reporting

Quality measurement rides on the cohort and order machinery already described and is recomputed on every relevant event: an order resulting, a cohort exclusion, a patient status change, or a report snapshot. Each `ScreeningOrder` carries a computed `quality_outcome`. An order that resulted with `outcome` `NEGATIVE` is `ADHERENT_NEGATIVE`. An order that resulted `POSITIVE` and whose navigation completed on or before its `navigation_due_at` is `ADHERENT_POSITIVE_NAVIGATED`. A `POSITIVE` result whose navigation is still `PENDING` or `SCHEDULED` leaves the order `POSITIVE_NAVIGATION_PENDING`; once navigation lapses, the order becomes `POSITIVE_NAVIGATION_LAPSED`. An order that has not resulted at all — including one still in flight and one rejected, cancelled, or abandoned — remains `UNRESOLVED`.

Program counters aggregate over cohort rows. A program's `attributed_count` is the number of its `MemberCohort` rows whose `attributed` flag is true and whose status is not `EXCLUDED`; its `adherent_count` is the number of those attributed cohorts linked to a `ScreeningOrder` whose `quality_outcome` is `ADHERENT_NEGATIVE` or `ADHERENT_POSITIVE_NAVIGATED`. Note that a cohort that was excluded — whether directly or through patient opt-out — drops out of the denominator entirely. These counters are recomputed whenever a contributing event occurs, including when an order carrying the cohort results (which also cascades the cohort `ORDERED → SCREENED`).

A `ProgramAdmin` may snapshot the measure at any time, producing a `QualityMeasureReport` for a program. The snapshot copies the program's `measure_year`, records `numerator` as the program's `adherent_count` at snapshot time and `denominator` as its `attributed_count` at snapshot time, computes `adherence_rate` as the numerator divided by the denominator rounded to four decimal places round-half-up — exactly 0.0000 when the denominator is zero — and stamps `snapshot_at` from the logical clock. Reports may be listed for their program, listed across programs with an optional `program_id` filter, or fetched individually.

## 4. Endpoint Definitions

All endpoints are mounted under the `/screening` prefix. Status codes follow a simple convention: operations that create a new resource return 201, operations that modify an existing resource or perform a read return 200, and every rejection uses the HTTP status paired with its `error_id` in §5. The table below is a summary only; request payloads, response shapes, preconditions, and side effects are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /screening/_clock/set_current_utc | Set the server's logical clock and evaluate time-based auto-transitions | ProgramAdmin |
| POST | /screening/programs | Create a health plan / health system program | ProgramAdmin |
| GET | /screening/programs | List programs | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent, Navigator |
| GET | /screening/programs/{programId} | Get one program, including computed counters | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent, Navigator |
| GET | /screening/programs/{programId}/cohorts | List member cohort rows of a program | ProgramAdmin |
| POST | /screening/programs/{programId}/cohorts | Enroll a patient into the program's member cohort | ProgramAdmin |
| GET | /screening/programs/{programId}/cohorts/{cohortId} | Get one cohort row | ProgramAdmin |
| POST | /screening/programs/{programId}/cohorts/{cohortId}/outreach | Dispatch PUSH outreach to one member | ProgramAdmin |
| POST | /screening/programs/{programId}/cohorts/{cohortId}/exclude | Exclude a member from the measure | ProgramAdmin |
| GET | /screening/programs/{programId}/cohorts/{cohortId}/outreach-events | List outreach events for one cohort member | ProgramAdmin |
| GET | /screening/cohorts | Filtered list of cohort rows across programs | ProgramAdmin |
| GET | /screening/cohorts/{cohortId} | Get one cohort row by id | ProgramAdmin |
| GET | /screening/outreach-events | Filtered list of outreach events | ProgramAdmin |
| GET | /screening/outreach-events/{eventId} | Get one outreach event by id | ProgramAdmin |
| GET | /screening/reminders | Filtered list of reminder rows | ProgramAdmin, FulfillmentAgent |
| GET | /screening/reminders/{reminderId} | Get one reminder by id | ProgramAdmin, FulfillmentAgent |
| GET | /screening/quality-measure-reports/{reportId} | Get one quality measure report snapshot by id | ProgramAdmin |
| GET | /screening/quality-measure-reports | Filtered list of report snapshots across programs | ProgramAdmin |
| GET | /screening/kits | Filtered list of kits | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent |
| GET | /screening/specimens | Filtered list of lab specimens | ProgramAdmin, LabTechnician |
| GET | /screening/results | Filtered list of screening results | ProgramAdmin, Provider, LabTechnician, Navigator |
| POST | /screening/programs/{programId}/quality-measure-report | Generate a snapshot quality measure report | ProgramAdmin |
| GET | /screening/programs/{programId}/quality-measure-reports | List report snapshots for the program | ProgramAdmin |
| POST | /screening/patients | Register a patient | ProgramAdmin, Provider |
| GET | /screening/patients | List patients | ProgramAdmin, Provider |
| GET | /screening/patients/{patientId} | Get one patient | ProgramAdmin, Provider |
| POST | /screening/patients/{patientId}/opt-out | Mark patient OPTED_OUT | ProgramAdmin |
| GET | /screening/patients/{patientId}/risk-score | Computed weighted risk screen score (advisory) | ProgramAdmin, Provider |
| POST | /screening/providers | Register a provider | ProgramAdmin |
| GET | /screening/providers/{providerId} | Get one provider | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent, Navigator |
| POST | /screening/orders | Capture a provider order for a home collection kit | Provider, ProgramAdmin |
| GET | /screening/orders | List orders | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent, Navigator |
| GET | /screening/orders/{orderId} | Get one order | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent, Navigator |
| POST | /screening/orders/{orderId}/eligibility/confirm | Confirm eligibility screening passed | ProgramAdmin |
| POST | /screening/orders/{orderId}/eligibility/reject | Reject order as ineligible | ProgramAdmin |
| POST | /screening/orders/{orderId}/cancel | Cancel a pending/eligible order | Provider, ProgramAdmin |
| POST | /screening/orders/{orderId}/kit | Create (or re-create after inadequate specimen) the screening kit for the order | FulfillmentAgent |
| GET | /screening/orders/{orderId}/kits | List kits of an order | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent |
| GET | /screening/orders/{orderId}/reminders | List reminder cadence rows for an order | ProgramAdmin, FulfillmentAgent |
| POST | /screening/orders/{orderId}/reminders/dispatch | Dispatch all due reminders for the order | ProgramAdmin |
| GET | /screening/orders/{orderId}/sla | Computed SLA days (both provisional and return-logistics variants) | ProgramAdmin, Provider, FulfillmentAgent |
| GET | /screening/orders/{orderId}/results | List results for an order | ProgramAdmin, Provider, LabTechnician, Navigator |
| GET | /screening/kits/{kitId} | Get one kit | ProgramAdmin, Provider, LabTechnician, FulfillmentAgent |
| POST | /screening/kits/{kitId}/ship | Mark kit shipped with collection instructions and stabilization requirements | FulfillmentAgent |
| POST | /screening/kits/{kitId}/return | Record return of the completed kit at the lab dock | FulfillmentAgent |
| POST | /screening/orders/{orderId}/specimens | Accession a specimen from the returned kit | LabTechnician |
| GET | /screening/specimens/{specimenId} | Get one specimen | ProgramAdmin, LabTechnician |
| GET | /screening/kits/{kitId}/specimens | List specimens accessioned from one kit | ProgramAdmin, LabTechnician |
| POST | /screening/specimens/{specimenId}/process | Begin laboratory processing (stabilization window enforced) | LabTechnician |
| POST | /screening/specimens/{specimenId}/adequacy | Record specimen adequacy determination | LabTechnician |
| POST | /screening/specimens/{specimenId}/result | Finalize the screening result and deliver to the ordering provider | LabTechnician |
| GET | /screening/results/{resultId} | Get one result | ProgramAdmin, Provider, LabTechnician, Navigator |
| POST | /screening/results/{resultId}/navigation/schedule | Schedule follow-up colonoscopy navigation | Navigator |
| POST | /screening/results/{resultId}/navigation/complete | Mark colonoscopy navigation completed | Navigator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives where the guarded workflow lives; this table is only an index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_DUPLICATE_PATIENT | 409 |
| ERR_PATIENT_NOT_ACTIVE | 422 |
| ERR_AGE_OUT_OF_RANGE | 422 |
| ERR_RISK_CATEGORY_EXCLUDED | 422 |
| ERR_CONTRAINDICATION_PRESENT | 422 |
| ERR_PROVIDER_INACTIVE | 422 |
| ERR_COHORT_PROGRAM_MISMATCH | 422 |
| ERR_ORDER_INVALID_STATE | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_KIT_INVALID_STATE | 409 |
| ERR_SPECIMEN_INVALID_STATE | 409 |
| ERR_SPECIMEN_NOT_ADEQUATE | 422 |
| ERR_STABILIZATION_EXPIRED | 422 |
| ERR_RECOLLECTION_LIMIT_REACHED | 422 |
| ERR_ACTIVE_ORDER_EXISTS | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PROGRAM_INACTIVE | 422 |
| ERR_PROGRAM_MODE_VIOLATION | 422 |
| ERR_COHORT_INVALID_STATE | 409 |
| ERR_NAVIGATION_NOT_REQUIRED | 422 |
| ERR_NAVIGATION_INVALID_STATE | 409 |
