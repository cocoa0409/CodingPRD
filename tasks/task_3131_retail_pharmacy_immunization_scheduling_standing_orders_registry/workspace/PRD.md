# Retail Pharmacy Immunization API — Product Requirements Document

## 1. Introduction

Community pharmacies now deliver a substantial share of adult vaccinations in the United States, and the operational surface behind each administered dose is wider than it looks from the counter: appointment scheduling with age and product eligibility screening, walk-in accommodation, pharmacist authority that varies state by state (standing orders, protocols, and prescription-only vaccines), a prescreening questionnaire with pharmacist contraindication review, lot-level vaccine inventory with continuous refrigerator temperature monitoring, insurance adjudication split across the pharmacy and medical benefit channels with a cash fallback, and timely reporting to the jurisdictional immunization registry in one of three message formats. Off-site and employer-sponsored clinic events add a mobile-inventory dimension on top of all of that.

This document specifies a single REST API, mounted under `/immunization`, that models that entire surface. The system enforces segregation of duties across the clinical pipeline (the staff member who checks a patient in may not also review their consent, and the pharmacist who reviews consent may not also administer the dose), tracks every dose from receipt into a store refrigerator through administration and registry acknowledgement, and maintains a compliance audit trail strong enough to answer "which lots were exposed to a temperature excursion, how severe was it, and what happened to the doses drawn from them."

A logical clock drives all time-dependent behavior — check-in windows, no-show sweeps, registry lateness, clinic-event activation — so the system is deterministic and testable. All side effects of a state transition (lot decrement, registry queueing, observation session creation, dose-counter increments) commit atomically in the same request as the transition that triggers them.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role value the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. These two checks run first, in that order, before any resource-existence or business-rule evaluation.

The system recognizes seven roles, spelled exactly: `StoreManager`, `Pharmacist`, `PharmacyTechnician`, `Immunizer`, `ObservationMonitor`, `ComplianceOfficer`, and `Patient`.

For six of the seven roles — `StoreManager`, `Pharmacist`, `PharmacyTechnician`, `Immunizer`, `ObservationMonitor`, and `ComplianceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow captures an actor (for example as `reviewed_by_pharmacist_id` on a questionnaire, `administered_by` on an immunization record, or `observer_id` on an observation session), but it never compares such an identifier to any entity's `id`.

When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` record; ownership checks on any resource that references a `Patient` compare the resource's foreign-key field to `X-User-ID`. A patient may book only for themselves — a booking payload whose `patient_id` does not equal the caller's `X-User-ID` is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and may view or cancel only their own appointments and view their own price quote.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` envelope on list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven System Transitions

The system never consults wall-clock time for business logic. A server-maintained logical clock, initialized to exactly 2026-09-01T00:00:00Z at startup, is the sole source of "now" for eligibility checks, check-in windows, due-date computation, lateness evaluation, and sweep transitions. Before any explicit set call the clock reads exactly that startup instant and never falls back to wall-clock time.

An operator with the `StoreManager` or `ComplianceOfficer` role may advance the logical clock to a supplied instant via the clock's test-driving capability, supplying the target instant as `to_iso8601`. Each such advance triggers the system's time-driven sweeps in the same request: non-walk-in appointments whose check-in window has lapsed transition to `NO_SHOW`, walk-in appointments never checked in by end of their calendar day transition to `EXPIRED`, overdue registry submissions still awaiting transmission transition to `LATE_UNRESOLVED`, and clinic events whose window has been entered transition from `PLANNED` to `ACTIVE`. These sweeps are described fully in §3 alongside the workflows they guard.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is a system-managed integer that increments by one on every modification to the resource and underpins the optimistic concurrency controls described in §2.7.

One entity is an exception: a `TemperatureReading` is an immutable fact about a refrigerator at an instant. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and no endpoint mutates a reading after it is posted.

### 2.6. Nested Resource Retrieval and Validation Ordering

When an endpoint path contains multiple resource identifiers — for example a store id followed by a lot id, or an appointment id followed by a questionnaire — the system validates the existence of each identifier sequentially, left to right. The request is rejected immediately with `ERR_NOT_FOUND` for the first identifier in the path that does not correspond to an existing resource, before any later segment is resolved and before any state or business rule is evaluated.

Across the whole request lifecycle, checks are evaluated in a fixed priority order. Authentication context comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then left-to-right path existence (`ERR_NOT_FOUND`), then — on the two endpoints that declare an optimistic-concurrency field — the stale-version check, which runs before any business-rule validation. Only after those four layers pass does the system evaluate whether the target resource is in a state that permits the requested transition (`ERR_INVALID_STATE` and the more specific state errors), and finally the business-rule layer: safety checks (contraindications, pharmacist authority and minimum age, segregation of duties, daily dose caps), then constraint checks (series completion and minimum intervals, slot overlap, reservation capacity), then temporal checks (check-in windows, observation windows, event timing), then referential checks on lot administerability. When a single request would violate several rules, the error surfaced is the one belonging to the earliest failing layer in this order.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry a mandatory optimistic-concurrency field; no other endpoint accepts a version field.

Administering a dose requires the request to carry `expected_lot_version`, set to the `version` of the target `VaccineLot` as the client last observed it. If another writer has advanced the lot's version since that observation — by administering a dose from the same lot, by an auto-quarantine triggered by a temperature excursion, by a manual quarantine, release, or retirement — the administer request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). This prevents a client from drawing from a lot whose availability or status it has not observed.

Completing pharmacist contraindication review requires the request to carry `expected_appointment_version`, set to the `version` of the `ImmunizationAppointment` as the pharmacist last loaded it. If the appointment's version has advanced since — for example because the appointment was re-screened or otherwise mutated — the review is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412), so a pharmacist never clears a screening snapshot they have not seen. Both version fields are non-optional on their respective endpoints; on both, the version check runs before business-rule validation, so a stale request fails with the 412 even if it would also have failed a later check.

### 2.8. Monetary Values, Precision, and Rounding

All monetary values are integer cents — `cash_price_cents`, `copay_cents`, `deductible_remaining_cents`, and the computed `charge_cents` are whole numbers of cents, never fractional. The single rounding step in the adjudication waterfall is a floor applied to the coinsurance multiplication, taken after the full remainder is multiplied by the coinsurance percentage; the percentage itself is never pre-rounded.

Temperature deltas used in excursion grading are computed to exactly 2 decimal places using round-half-up, and the rounding is applied before any severity-tier comparison — never after. Severity tiers and registry deadlines are otherwise integer or second-precision quantities as described in §3.

### 2.9. Segregation of Duties

The clinical pipeline deliberately separates its actors. On any single appointment, the operator who performed check-in may not be the pharmacist who completes contraindication review, and the pharmacist who completed review may not be the immunizer who administers the dose. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. The comparison is by `X-User-ID`; because operator identities are opaque, two operators who happen to be the same human under different role headers are still distinguished by their identifier.

### 2.10. Hierarchical Consistency and Cascading Side Effects

State changes on a parent resource propagate to dependent resources atomically within the same request. Suspending a store cancels every `SCHEDULED` appointment booked at it. Retiring a vaccine lot writes off its remaining doses and auto-cancels any `PLANNED` clinic event that checked the lot out as mobile inventory. Voiding an immunization record restores the dose to its lot, removes the record's registry submission from the reporting queue, closes any still-open observation session, and decrements the hosting clinic event's administered count. Conversely, child events roll up: an excursion reading quarantines its lot, an administration decrements its lot and increments its event, and a clinic close reconciles its mobile lot. Each such mutation refreshes the mutated resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Stores, Protocols, Products, Plans, and Patients

A `StoreManager` onboards a pharmacy location by registering it with its `store_number` (a unique human-readable identifier), the two-letter `state_code` of the state where the store is licensed, and its `address_line`. A store's `status` begins as `ACTIVE`; a `StoreManager` may update a store's `address_line` or flip its `status` between `ACTIVE` and `SUSPENDED`. A `SUSPENDED` store cannot accept bookings, check-ins, or administrations — attempts against one fail with `ERR_STORE_SUSPENDED` — and the act of suspending a store cancels every appointment still `SCHEDULED` at that store with reason `STORE_SUSPENDED`. The store's `state_code` is what determines which state protocol governs immunizations performed there; a patient's residence state is informational only.

Pharmacist authority is modeled per state and per product. A `ComplianceOfficer` creates a `StateProtocol` row for a (`state_code`, `vaccine_product_id`) pair — unique per pair — declaring the `authority_type` (one of `STANDING_ORDER`, `PROTOCOL`, or `PRESCRIPTION_REQUIRED`), the `min_patient_age_years` a pharmacist may immunize under that authority, the jurisdiction's `registry_format` (one of `HL7_VXU`, `FLAT_FILE_CSV`, or `STATE_API_JSON`), and the `registry_deadline_hours` within which an administration must be acknowledged by the registry. The `max_doses_per_patient_per_day` field caps how many distinct vaccine administrations one patient may receive in a single calendar day at a store and defaults to 2 when omitted. A protocol's `status` starts `ACTIVE`; a `ComplianceOfficer` may update a protocol's `min_patient_age_years`, `registry_deadline_hours`, or `status`, and a `RETIRED` protocol authorizes nothing new — review against a retired protocol fails with `ERR_PROTOCOL_NOT_ACTIVE`. An `authority_type` of `PRESCRIPTION_REQUIRED` additionally forbids walk-in and standing-order administration entirely.

The vaccine catalog is maintained by a `ComplianceOfficer`. Each `VaccineProduct` is registered with its CDC `cvx_code`, a display `name`, the manufacturer's `min_patient_age_years`, the `doses_per_series` (1 for a flu shot, 2 for shingles), the `cash_price_cents` charged per dose when no benefit applies, and the acceptable refrigerator band `fridge_temp_min_c` to `fridge_temp_max_c` in Celsius. `min_interval_days` — the minimum gap between successive doses of the product — defaults to 0, and `observation_minutes`, the standard post-vaccination observation window, defaults to 15.

Insurance coverage is similarly reference data. A `ComplianceOfficer` registers an `InsurancePlan` with its `plan_name`, the `benefit_type` channel that covers immunizations (`PHARMACY`, `MEDICAL`, or `BOTH`), the `copay_cents` owed under the pharmacy channel, and the `covered_cvx_codes` list naming every CVX code the plan covers at all. `coinsurance_pct` — the patient percentage under the medical channel, between 0 and 100 — and `deductible_remaining_cents` — the medical deductible still to be consumed — both default to 0. Plans drift over time as external claims consume the deductible or coverage changes, and a `ComplianceOfficer` may update `copay_cents`, `coinsurance_pct`, `deductible_remaining_cents`, `covered_cvx_codes`, or `benefit_type` on an existing plan; adjudication always re-reads the plan row at the moment of administration.

A `PharmacyTechnician` or `Pharmacist` registers a `Patient` with `full_name`, `date_of_birth` (an ISO 8601 date), and residence `state_code`. Optional at registration are `allergy_flags` — a list of known allergen codes that contraindication review matches against vaccine excipient lists, defaulting to empty — `high_risk_flag`, which when true mandates a 30-minute observation window instead of the standard one and defaults to false, and `insurance_plan_id`, which may be omitted at registration but is required before any non-cash checkout.

### 3.2. Cold Chain: Lots, Temperature Monitoring, and Excursions

Inventory lives in lots. A `StoreManager` receives a `VaccineLot` into a store by supplying the `vaccine_product_id`, the manufacturer `lot_number` (unique per store), the `expiration_date` on or after which doses may not be administered, and the `doses_received` count. Receipt initializes `doses_available` equal to `doses_received` and sets the lot's `status` to `RELEASED`. Thereafter `doses_available` is computed — it equals `doses_received` minus doses administered, minus doses wasted, minus doses under unresolved quarantine or event reservation — and it never goes negative. The lot's `store_id` is recorded from the receiving store.

Refrigerator surveillance is continuous. A `StoreManager` or `PharmacyTechnician` posts a `TemperatureReading` against a lot with the `recorded_at` timestamp and the `temperature_c` value. The system computes `is_excursion` as true whenever the reading falls outside the product's band — strictly below `fridge_temp_min_c` or strictly above `fridge_temp_max_c`. A reading inside the band is accepted with no side effects and an `excursion_severity_tier` of `NONE`.

Any excursion at all — however slight — auto-quarantines the lot: the lot's `status` moves from `RELEASED` to `QUARANTINED` with `quarantine_reason` set to `EXCURSION`, and the severity of the excursion is graded and stored. Grading uses the peak-delta rule. The raw delta is the number of degrees outside the acceptable band, taking the worse of the two sides: how far above the maximum the reading sits, or how far below the minimum, whichever is larger, and never less than zero. That raw delta is first rounded half-up to 2 decimal places, and only the rounded value is compared against the tier boundaries — the order is pinned because the two orders genuinely diverge (a raw delta of 2.004 rounds to 2.00 and tiers `MINOR`, whereas comparing the unrounded value would tier it `MODERATE`). On the rounded value: exactly zero means no excursion; greater than zero and at most 2.0 degrees is `MINOR`; greater than 2.0 and at most 5.0 degrees is `MODERATE`; greater than 5.0 degrees is `SEVERE`. The boundary is exclusive at the top of `MINOR` — a rounded delta of exactly 2.00 is `MINOR`, while 2.01 is `MODERATE`. The graded tier is recorded on the reading as `excursion_severity_tier` and reflected on the lot as `last_excursion_severity_tier`.

A `StoreManager` may also quarantine a lot by hand; manual quarantine requires the lot to be `RELEASED` (otherwise `ERR_LOT_NOT_RELEASED`) and records `quarantine_reason` as `MANUAL`. Either way, while a lot is `QUARANTINED` it cannot be administered. Appointments at the store whose only eligible lot was the quarantined lot remain valid only if another `RELEASED` lot of the same product exists.

Resolution of a quarantine is a deliberate act by a `StoreManager`, who releases the lot by supplying an `excursion_disposition`. The disposition must be one of `RELEASE_OK` or `RELEASE_OK_CUMULATIVE`; a release attempted on a lot that is not `QUARANTINED` fails with `ERR_LOT_NOT_QUARANTINED`, and a release missing a valid disposition fails with `ERR_EXCURSION_DISPOSITION_REQUIRED`. Under `RELEASE_OK`, the lot returns to `RELEASED` keeping its peak-delta severity tier. Under `RELEASE_OK_CUMULATIVE` — used in jurisdictions that grade severity by total time outside the band rather than peak deviation — the lot's `last_excursion_severity_tier` is recomputed by the cumulative variant: sum, over each run of consecutive out-of-band readings, the elapsed minutes between each reading and the next, and tier the total as at most 30 minutes `MINOR`, greater than 30 and at most 120 minutes `MODERATE`, and greater than 120 minutes `SEVERE`. For identical temperature data this can produce a different tier than the peak-delta base variant whenever a shallow-but-long excursion occurs. Either release clears `quarantine_reason` and increments the lot's `version`.

Retirement is terminal. A `StoreManager` may retire a lot from either `RELEASED` or `QUARANTINED`; retiring an already `RETIRED` lot fails with `ERR_LOT_NOT_RETIRABLE`. Retirement permanently writes off the remaining doses — `doses_available` becomes zero — and if the retired lot was checked out as the mobile lot of a `PLANNED` clinic event, that event auto-cancels.

### 3.3. Booking: Eligibility Screening, Series Rules, and Slot Management

Booking an appointment is open to a `PharmacyTechnician`, a `Pharmacist`, or the `Patient` themselves (self-booking only — the payload's `patient_id` must equal the caller's `X-User-ID`). The request names the `store_id`, the `patient_id`, the `vaccine_product_id`, and the desired `slot_start` instant; `is_walk_in` may be set true to indicate a walk-in, in which case `slot_start` is set equal to the creation time and slot-availability checks are bypassed — but eligibility and inventory checks are not.

At booking, the system resolves the governing protocol: the appointment's `state_protocol_id` is computed from the store's `state_code` and the requested product, and the store must be `ACTIVE` (`ERR_STORE_SUSPENDED` otherwise). The patient's age in whole years is computed from `date_of_birth` against the logical-clock date — a patient turns N on their birthday, so a date earlier in the calendar year than the birthday subtracts one from the naive year difference — and, critically, eligibility is evaluated at the administration date (the calendar day of `slot_start`), not the booking date, so a patient may book while underage and become eligible by the slot day. Eligibility requires the age at the slot date to be at least the greater of the protocol's `min_patient_age_years` and the product's `min_patient_age_years`; the comparison is inclusive, so a patient exactly at the minimum age on their birthday is eligible. Falling short is rejected with `ERR_PATIENT_UNDER_MIN_AGE`.

Series position is computed at booking as well. The appointment's `dose_number` is one plus the count of the patient's `COMPLETED` immunization records for the same product (records drawn from a lot of that product; `VOIDED` records are excluded), ordered by `administered_at` ascending with ties broken by `created_at` ascending. If that computed `dose_number` exceeds the product's `doses_per_series`, the series is already complete and booking is rejected with `ERR_SERIES_ALREADY_COMPLETE`. For a second or later dose, the most recent prior `COMPLETED` record's `administered_at` must be at least `min_interval_days` before `slot_start`; a gap of exactly the minimum interval is allowed, and a shorter gap is rejected with `ERR_MIN_INTERVAL_NOT_MET`.

For non-walk-in appointments, slot overlap is enforced per store: the new appointment's interval — half-open, from `slot_start` through the fifteen minutes following it — must not overlap the corresponding interval of any existing `SCHEDULED` or `CHECKED_IN` appointment at the same store. Because the intervals are half-open, back-to-back adjacency is allowed: a 10:15 slot may follow a 10:00 slot. An overlap is rejected with `ERR_SLOT_CONFLICT`.

A booked appointment begins in `SCHEDULED`. From there the system maintains `scheduled_dose_count_today`, the count of the patient's administrations at this store on the appointment's calendar day, which later gates the daily dose cap. Cancellation is available to a `PharmacyTechnician`, a `Pharmacist`, or the owning `Patient` while the appointment is `SCHEDULED` or `CHECKED_IN`; a cancellation attempt in any later or terminal state fails with `ERR_APPOINTMENT_NOT_CANCELLABLE`. Two sweeps reap abandoned appointments without any client action: when the logical clock passes sixty minutes past `slot_start` with no check-in, a non-walk-in appointment moves from `SCHEDULED` to `NO_SHOW`; when the logical clock passes the end of the slot's calendar day, a walk-in appointment never checked in moves from `SCHEDULED` to `EXPIRED`.

Before administration, anyone at the counter — or the patient — may request a provisional price quote for the appointment. The quote runs the full adjudication waterfall of §3.6 with one difference: it does not consume the deductible, treating `deductible_remaining_cents` as read-only. The quote returns `quoted_charge_cents` and the `billing_channel` that produced it. It is an estimate only: the administered charge re-reads the plan row at administration time, so a plan whose deductible changed between quote and administration produces a different charge than quoted.

### 3.4. The Counter Pipeline: Check-in, Screening, and Pharmacist Review

On the day of the appointment, a `PharmacyTechnician` or `Pharmacist` checks the patient in, moving the appointment from `SCHEDULED` to `CHECKED_IN` and incrementing the appointment's `version`. Check-in requires the appointment to actually be `SCHEDULED` — any other state yields `ERR_APPOINTMENT_NOT_SCHEDULED` — and the store to be `ACTIVE`. Timing is enforced for scheduled appointments: the logical clock must fall within the window from thirty minutes before `slot_start` through sixty minutes after it, inclusive; a missed window is rejected with `ERR_CHECKIN_WINDOW_MISSED`. Walk-ins are exempt from the window check.

Once checked in, a `PharmacyTechnician` administers the prescreening questionnaire, submitting the `answers` map keyed by question code (codes such as `FEVER_TODAY`, `PREGNANT`, `IMMUNOCOMPROMISED`, and `PRIOR_ANAPHYLAXIS`). Exactly one questionnaire exists per appointment; a second submission fails with `ERR_QUESTIONNAIRE_ALREADY_EXISTS`, and submission against an appointment that is not `CHECKED_IN` fails with `ERR_APPOINTMENT_NOT_CHECKED_IN`. On submission the system computes `contraindication_detected` — true when any answer, or any entry in the patient's `allergy_flags`, is a hard contraindication for the appointment's vaccine — creates the `PrescreeningQuestionnaire` with its `appointment_id` back-reference, and advances the appointment to `SCREENED`.

The pharmacist's contraindication review is the clinical gate. A `Pharmacist` completes review by supplying `expected_appointment_version` (see §2.7 — a stale snapshot is rejected with `ERR_STALE_APPOINTMENT_VERSION` before any business rule runs) and an `outcome`. With `outcome` of `CLEAR`, the system evaluates, in order: the appointment must be `SCREENED` (`ERR_APPOINTMENT_NOT_SCREENED`); the questionnaire's `contraindication_detected` must be false (`ERR_CONTRAINDICATION_DETECTED`); the governing protocol must be `ACTIVE` — and for a walk-in, must not be `PRESCRIPTION_REQUIRED` authority — (`ERR_PROTOCOL_NOT_ACTIVE`); the patient's age at the administration date must be at least the greater of the protocol and product minimum ages (`ERR_PATIENT_UNDER_MIN_AGE`); the patient's `scheduled_dose_count_today` must be below the protocol's `max_doses_per_patient_per_day` (`ERR_DAILY_DOSE_LIMIT_REACHED`); there must exist at least one `RELEASED`, unexpired lot of the product at the store with `doses_available` above zero, or the appointment must be attached to an `ACTIVE` clinic event with reserved doses remaining (`ERR_NO_ELIGIBLE_LOT`); and the reviewing pharmacist's `X-User-ID` must differ from the operator who performed check-in (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). A successful CLEAR sets the questionnaire's `review_outcome` to `CLEARED`, records the reviewing pharmacist's opaque identifier in `reviewed_by_pharmacist_id`, advances the appointment to `CONSENTED`, and increments the appointment's `version`.

The same review endpoint carries the sibling branch: with `outcome` of `REFER_OUT`, the only precondition is that the appointment be `SCREENED` (`ERR_APPOINTMENT_NOT_SCREENED`). The questionnaire's `review_outcome` is set to `REFERRED_OUT`, the appointment moves from `SCREENED` to `CANCELLED`, and if a lot had been soft-held for the appointment, the hold is released and the doses restored to availability. Refer-out is the system's answer to a genuine contraindication or any other clinical concern: the patient is directed to a prescriber rather than vaccinated at the counter.

### 3.5. Administration and Its Atomic Fan-Out

Administration is the exclusive act of the `Immunizer`. The request names the `lot_id` the dose is drawn from, carries `expected_lot_version` for the OCC check of §2.7 (a stale view of the lot fails with `ERR_STALE_LOT_VERSION`), and may carry a `clinic_event_id` when the dose is administered under an off-site event. The appointment must be `CONSENTED` (`ERR_APPOINTMENT_NOT_CONSENTED`). The target lot must be `RELEASED` and unexpired — a quarantined, retired, expired, or otherwise unfit lot is rejected with `ERR_LOT_NOT_ADMINISTERABLE` — must have `doses_available` above zero (`ERR_LOT_DEPLETED`), and must be a lot of the appointment's product (`ERR_LOT_PRODUCT_MISMATCH`). Segregation of duties applies again: the immunizer's `X-User-ID` must differ from the reviewing pharmacist's, or the request fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

A successful administration commits five effects atomically in one request. First, an `ImmunizationRecord` is created in `COMPLETED` status: its `appointment_id` ties it to the appointment, `patient_id` is copied from the appointment, `lot_id` records the source lot, `administered_by` captures the immunizer's opaque identifier, `administered_at` is stamped from the logical clock, `dose_number` is copied from the appointment, and `charge_cents` with its `billing_channel` is computed by the adjudication waterfall of §3.6. Second, the lot's `doses_available` decrements by one and the lot's `version` bumps. Third, a `RegistrySubmission` springs into existence in `PENDING` status with its payload rendered per the governing protocol's format and its deadline computed from the administration instant. Fourth, an `ObservationSession` is created in `IN_PROGRESS` status. Fifth, the counters roll up: if the appointment is attached to a clinic event, the event's `doses_administered` increments by one, and the patient's `scheduled_dose_count_today` for the day increments. The appointment itself lands in `VACCINATED`, a terminal state.

Rescission is possible but narrow. A `Pharmacist` may void an administration by supplying a `reason`, but only while the record is `COMPLETED` (otherwise `ERR_RECORD_ALREADY_VOIDED`) and only while its registry submission is still `PENDING` or `REJECTED` — a submission already transmitted or acknowledged cannot be voided back, and the attempt fails with `ERR_SUBMISSION_ALREADY_TRANSMITTED`. A void compensates on every front at once: the record moves to `VOIDED`; the source lot's `doses_available` increments by one with its `version` bumped; the record's registry submission is removed from the reporting queue outright (the row is deleted while the record keeps its history); the parent observation session, if still `IN_PROGRESS`, transitions to `COMPLETED` with `ended_at` stamped from the logical clock — observation is moot once the dose is voided, and this system transition bypasses the minimum-duration floor that manual completion enforces; and if the dose was administered under a clinic event, the event's `doses_administered` decrements by one.

### 3.6. Benefit Adjudication: The Charge Waterfall

Every administration computes the patient's `charge_cents` by a strict waterfall over the benefit channels, evaluating channels in pinned order — pharmacy benefit first, then medical benefit, then cash — with the first applicable channel winning. Let the price be the product's `cash_price_cents` in integer cents, and let the plan be the patient's `insurance_plan_id` resolved to its `InsurancePlan` row, which may be absent.

The pharmacy benefit channel applies when a plan exists, its `benefit_type` is `PHARMACY` or `BOTH`, and the product's `cvx_code` appears in the plan's `covered_cvx_codes`. The charge is then the lesser of the plan's `copay_cents` and the price. The medical benefit channel applies when the pharmacy channel does not, a plan exists, its `benefit_type` is `MEDICAL` or `BOTH`, and the CVX is covered. Under the medical channel, the deductible applied is the lesser of `deductible_remaining_cents` and the price; the remainder is the price minus that deductible; the coinsurance is the remainder multiplied by `coinsurance_pct` and divided by 100, floored to whole cents after the full multiplication — the percentage is never rounded first; and the charge is the deductible applied plus the floored coinsurance. The cash channel applies when no plan exists, when the CVX is not covered, or when both benefit channels are otherwise inapplicable, and the charge is simply the full price with no discount.

Two consequences of the pinned order deserve emphasis. A plan with `benefit_type` of `BOTH` always resolves to the `PHARMACY_BENEFIT` channel when the CVX is covered, even if the medical channel would yield a lower charge. And the resulting `billing_channel` — `PHARMACY_BENEFIT`, `MEDICAL_BENEFIT`, or `CASH` — is recorded on the record alongside `charge_cents`, so auditors can always see which channel produced the number. All arithmetic is integer cents; the only rounding in the waterfall is the floor at the coinsurance step.

### 3.7. Observation and Adverse-Event Response

Every administration opens an observation window staffed by an `ObservationMonitor`, whose opaque identifier is recorded as the session's `observer_id`. The session's `required_minutes` is 30 when the patient's `high_risk_flag` is true, and otherwise the product's `observation_minutes`; `started_at` is stamped from the logical clock at creation and the session begins `IN_PROGRESS`.

Normal completion belongs to the assigned observer alone: completing a session requires the session to be `IN_PROGRESS` (`ERR_SESSION_NOT_IN_PROGRESS`), requires the logical clock to have reached `started_at` plus `required_minutes` — completion at exactly that instant is allowed, and earlier attempts fail with `ERR_OBSERVATION_TOO_EARLY` — requires `adverse_reaction` to be false (a session with a recorded reaction may not be completed normally and must be escalated instead, `ERR_REACTION_MUST_ESCALATE`), and requires the caller's `X-User-ID` to equal the session's `observer_id` (`ERR_NOT_ASSIGNED_OBSERVER`). Completion stamps `ended_at` from the logical clock.

Escalation is shared between the `ObservationMonitor` and a `Pharmacist`. It requires the session to be `IN_PROGRESS` and requires `adverse_reaction` true together with non-empty `reaction_notes`; escalation with a reaction but no notes is rejected with `ERR_REACTION_NOTES_REQUIRED`. Escalation records the reaction on the session, moves it to `ESCALATED`, and writes an adverse-event audit flag onto the parent immunization record — the record itself stays `COMPLETED` and its registry submission is unaffected.

### 3.8. Registry Reporting: Formats, Deadlines, and the Correction Cycle

The moment a dose is administered, the compliance clock starts. The `RegistrySubmission` created at administration copies its `payload_format` from the governing protocol's `registry_format` — `HL7_VXU`, `FLAT_FILE_CSV`, or `STATE_API_JSON` — renders its `payload` as the jurisdiction-specific message body, and computes its `due_at` as the record's `administered_at` plus the protocol's `registry_deadline_hours`, with exact hour arithmetic. The submission's `immunization_record_id` ties it to its record, with at most one active submission per record.

Transmission and acknowledgement belong to the `ComplianceOfficer`. Submitting a `PENDING` submission stamps `submitted_at` from the logical clock and moves it to `SUBMITTED`; submitting is allowed only from `PENDING` or `REJECTED` (and, as below, from `LATE_UNRESOLVED`), and only while the parent record is `COMPLETED` rather than `VOIDED` (`ERR_RECORD_VOIDED`). A submission may be rejected by the registry, moving from `SUBMITTED` to `REJECTED`; resubmission of a `REJECTED` entry requires a `corrected_payload` — omitting it fails with `ERR_CORRECTED_PAYLOAD_REQUIRED` — and on resubmission the `payload` is replaced with the corrected body and `submitted_at` is restamped. Either submission attempt from an ineligible state fails with `ERR_SUBMISSION_NOT_SUBMITTABLE`. Acknowledgement and rejection both require the submission to be `SUBMITTED` (`ERR_SUBMISSION_NOT_SUBMITTED`); acknowledgement stamps `acknowledged_at` and computes `is_late` as true when the acknowledgement time is strictly after `due_at` — an acknowledgement landing exactly at the deadline is on time. `ACKNOWLEDGED` is the only terminal state of the reporting lifecycle.

The lateness sweep runs whenever the logical clock advances: a submission still `PENDING` or `REJECTED` whose `due_at` has passed transitions to `LATE_UNRESOLVED`. Late is not hopeless — a `LATE_UNRESOLVED` submission may still be submitted and acknowledged — but it is permanent: `is_late`, once true, never flips back to false, and submissions resolved from `LATE_UNRESOLVED` carry the flag forever. Compliance audits list submissions filtered by `status`, `is_late`, or `payload_format` to find exactly these stragglers.

### 3.9. Off-Site Clinic Events and Mobile Inventory

Employer and venue clinics extend the store's reach. A `StoreManager` plans a `ClinicEvent` by naming the sponsoring `store_id`, the `employer_name`, the `event_start` and `event_end` instants, the `mobile_lot_id` to check out, and the `doses_reserved` count. The event window must be well-formed: `event_end` strictly after `event_start` and within the same calendar day — a malformed window fails with `ERR_EVENT_STILL_RUNNING` (and malformed or missing fields generally surface as `ERR_INVALID_REQUEST`). The mobile lot must be `RELEASED` and non-expired.

Capacity is checked in two layers at creation, raw capacity first and overlap second. Raw capacity: `doses_reserved` may not exceed the mobile lot's current `doses_available`, or the creation fails with `ERR_INSUFFICIENT_DOSES`. Overlap: for the same mobile lot, consider every other `PLANNED` or `ACTIVE` event whose window overlaps the new event's window — intervals being closed at the start and open at the end, so two events that merely touch endpoints do not overlap — and sum their `doses_reserved`; the new event's `doses_reserved` must fit within the lot's `doses_available` minus that overlapping reserved sum, or creation fails with `ERR_MOBILE_LOT_OVER_RESERVED`. The overlap check runs only after raw capacity passes.

A planned event begins in `PLANNED`. When the logical clock enters the event window — at or after `event_start` and strictly before `event_end` — the event activates automatically, and activation checks out the mobile inventory: the lot's `doses_available` decrements by `doses_reserved`. A `StoreManager` may cancel a `PLANNED` event (any other state fails with `ERR_EVENT_NOT_CANCELLABLE`), and an event whose mobile lot is retired before its start auto-cancels, as §3.2 describes. During the window, administrations attached to the event via `clinic_event_id` draw against it, each incrementing `doses_administered` from its initial zero.

Closing an event is a `StoreManager` act requiring the event to be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`) and the logical clock to be at or past `event_end` (`ERR_EVENT_STILL_RUNNING`). Close reconciles the mobile inventory: the unadministered remainder — `doses_reserved` minus `doses_administered` — returns to the lot's `doses_available`, and the event lands in `CLOSED`. The reconciliation invariant is compensating and exact: activation's checkout, the per-administration decrements, and close's return must net to precisely the number of doses actually administered, no more and no less. A close whose `doses_administered` exceeds `doses_reserved` is arithmetically impossible to reconcile and is rejected with `ERR_RECONCILIATION_OVERFLOW`.

## 4. Endpoint Definitions

Operations that create new resources — registering a store, protocol, product, plan, patient, or lot; booking an appointment; posting a temperature reading or questionnaire; administering a dose (which creates the immunization record); planning a clinic event — return `201 Created`. Operations that modify an existing resource or drive a state transition — check-in, review, cancel, quarantine, release, retire, void, submit, acknowledge, reject, complete, escalate, close, and all updates — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/immunization/_clock/set_current_utc` | Set the logical clock (test-driving; triggers time-driven sweeps) | StoreManager, ComplianceOfficer |
| POST | `/immunization/stores` | Register a pharmacy store | StoreManager |
| GET | `/immunization/stores` | List stores | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer, ObservationMonitor |
| GET | `/immunization/stores/{storeId}` | Get one store | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer, ObservationMonitor |
| PUT | `/immunization/stores/{storeId}` | Update a store (including ACTIVE ↔ SUSPENDED) | StoreManager |
| POST | `/immunization/state-protocols` | Create a state pharmacist-authority protocol row | ComplianceOfficer |
| GET | `/immunization/state-protocols` | List protocols | StoreManager, Pharmacist, ComplianceOfficer |
| GET | `/immunization/state-protocols/{protocolId}` | Get one protocol | StoreManager, Pharmacist, ComplianceOfficer |
| PUT | `/immunization/state-protocols/{protocolId}` | Update a protocol (e.g., retire) | ComplianceOfficer |
| POST | `/immunization/vaccine-products` | Register a vaccine product | ComplianceOfficer |
| GET | `/immunization/vaccine-products` | List vaccine products | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer, ObservationMonitor |
| GET | `/immunization/vaccine-products/{productId}` | Get one vaccine product | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer, ObservationMonitor |
| POST | `/immunization/insurance-plans` | Register an insurance plan | ComplianceOfficer |
| GET | `/immunization/insurance-plans/{planId}` | Get one insurance plan | StoreManager, Pharmacist, PharmacyTechnician, ComplianceOfficer |
| PUT | `/immunization/insurance-plans/{planId}` | Update an insurance plan (deductible consumption, coverage changes) | ComplianceOfficer |
| POST | `/immunization/patients` | Register a patient | PharmacyTechnician, Pharmacist |
| GET | `/immunization/patients/{patientId}` | Get one patient | PharmacyTechnician, Pharmacist, Immunizer, ComplianceOfficer |
| GET | `/immunization/patients` | List patients | PharmacyTechnician, Pharmacist, ComplianceOfficer |
| POST | `/immunization/stores/{storeId}/lots` | Receive a vaccine lot into a store | StoreManager |
| GET | `/immunization/stores/{storeId}/lots` | List lots at a store | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer |
| GET | `/immunization/lots/{lotId}` | Get one lot | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer |
| GET | `/immunization/lots` | List lots across stores (filtered) | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer |
| POST | `/immunization/lots/{lotId}/temperature-readings` | Post a refrigerator temperature reading for a lot | StoreManager, PharmacyTechnician |
| GET | `/immunization/lots/{lotId}/temperature-readings` | List temperature readings for a lot | StoreManager, Pharmacist, ComplianceOfficer |
| POST | `/immunization/lots/{lotId}/quarantine` | Manually quarantine a lot | StoreManager |
| POST | `/immunization/lots/{lotId}/release` | Release a quarantined lot after excursion review | StoreManager |
| POST | `/immunization/lots/{lotId}/retire` | Retire a lot (write off remaining doses) | StoreManager |
| POST | `/immunization/appointments` | Book an appointment (scheduled or walk-in) | PharmacyTechnician, Pharmacist, Patient |
| GET | `/immunization/appointments` | List appointments | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer |
| GET | `/immunization/appointments/{appointmentId}` | Get one appointment | StoreManager, Pharmacist, PharmacyTechnician, Immunizer, ComplianceOfficer, Patient |
| GET | `/immunization/appointments/{appointmentId}/price-quote` | Provisional price quote (no deductible consumption) | PharmacyTechnician, Pharmacist, Patient |
| POST | `/immunization/appointments/{appointmentId}/check-in` | Check the patient in at the counter | PharmacyTechnician, Pharmacist |
| POST | `/immunization/appointments/{appointmentId}/questionnaire` | Submit the prescreening questionnaire | PharmacyTechnician |
| GET | `/immunization/appointments/{appointmentId}/questionnaire` | Get the questionnaire for an appointment (0 or 1) | Pharmacist, PharmacyTechnician, ComplianceOfficer |
| POST | `/immunization/appointments/{appointmentId}/review-consent` | Pharmacist contraindication review and consent capture | Pharmacist |
| POST | `/immunization/appointments/{appointmentId}/administer` | Administer the vaccine from a specific lot | Immunizer |
| POST | `/immunization/appointments/{appointmentId}/cancel` | Cancel a SCHEDULED or CHECKED_IN appointment | PharmacyTechnician, Pharmacist, Patient |
| GET | `/immunization/immunization-records/{recordId}` | Get one immunization record | Pharmacist, Immunizer, ComplianceOfficer, PharmacyTechnician |
| GET | `/immunization/immunization-records` | List immunization records (filtered) | Pharmacist, Immunizer, ComplianceOfficer, PharmacyTechnician |
| POST | `/immunization/immunization-records/{recordId}/void` | Void an administration before registry transmission | Pharmacist |
| GET | `/immunization/appointments/{appointmentId}/immunization-records` | List immunization records for an appointment (0 or 1) | Pharmacist, Immunizer, ComplianceOfficer, PharmacyTechnician |
| GET | `/immunization/immunization-records/{recordId}/registry-submissions` | List registry submissions for a record | ComplianceOfficer, Pharmacist |
| GET | `/immunization/registry-submissions/{submissionId}` | Get one registry submission | ComplianceOfficer |
| GET | `/immunization/registry-submissions` | List registry submissions (compliance audit) | ComplianceOfficer |
| POST | `/immunization/registry-submissions/{submissionId}/submit` | Transmit a submission to the state registry | ComplianceOfficer |
| POST | `/immunization/registry-submissions/{submissionId}/acknowledge` | Record registry acknowledgement | ComplianceOfficer |
| POST | `/immunization/registry-submissions/{submissionId}/reject` | Record registry rejection | ComplianceOfficer |
| GET | `/immunization/immunization-records/{recordId}/observation-sessions` | List observation sessions for a record (0 or 1) | ObservationMonitor, Pharmacist, ComplianceOfficer |
| POST | `/immunization/observation-sessions/{sessionId}/complete` | Complete an observation session (no reaction) | ObservationMonitor |
| POST | `/immunization/observation-sessions/{sessionId}/escalate` | Escalate an observation session for an adverse reaction | ObservationMonitor, Pharmacist |
| POST | `/immunization/clinic-events` | Plan an off-site / employer clinic event with mobile inventory checkout | StoreManager |
| GET | `/immunization/stores/{storeId}/clinic-events` | List clinic events for a store | StoreManager, Pharmacist, ComplianceOfficer |
| GET | `/immunization/clinic-events/{eventId}` | Get one clinic event | StoreManager, Pharmacist, ComplianceOfficer |
| GET | `/immunization/clinic-events` | List clinic events (filtered) | StoreManager, Pharmacist, ComplianceOfficer |
| POST | `/immunization/clinic-events/{eventId}/cancel` | Cancel a PLANNED clinic event | StoreManager |
| POST | `/immunization/clinic-events/{eventId}/close` | Close an ACTIVE clinic event and reconcile mobile inventory | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_APPOINTMENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STORE_SUSPENDED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_SCREENED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CONSENTED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_MISSED` | 409 Conflict |
| `ERR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_QUESTIONNAIRE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CONTRAINDICATION_DETECTED` | 422 Unprocessable Entity |
| `ERR_PROTOCOL_NOT_ACTIVE` | 409 Conflict |
| `ERR_PATIENT_UNDER_MIN_AGE` | 422 Unprocessable Entity |
| `ERR_DAILY_DOSE_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_SERIES_ALREADY_COMPLETE` | 422 Unprocessable Entity |
| `ERR_MIN_INTERVAL_NOT_MET` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_LOT` | 409 Conflict |
| `ERR_LOT_NOT_ADMINISTERABLE` | 409 Conflict |
| `ERR_LOT_DEPLETED` | 409 Conflict |
| `ERR_LOT_PRODUCT_MISMATCH` | 409 Conflict |
| `ERR_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_LOT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_LOT_NOT_RETIRABLE` | 409 Conflict |
| `ERR_EXCURSION_DISPOSITION_REQUIRED` | 400 Bad Request |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 409 Conflict |
| `ERR_OBSERVATION_TOO_EARLY` | 409 Conflict |
| `ERR_REACTION_MUST_ESCALATE` | 409 Conflict |
| `ERR_REACTION_NOTES_REQUIRED` | 400 Bad Request |
| `ERR_NOT_ASSIGNED_OBSERVER` | 403 Forbidden |
| `ERR_SESSION_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_SUBMISSION_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SUBMISSION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CORRECTED_PAYLOAD_REQUIRED` | 400 Bad Request |
| `ERR_RECORD_VOIDED` | 409 Conflict |
| `ERR_RECORD_ALREADY_VOIDED` | 409 Conflict |
| `ERR_SUBMISSION_ALREADY_TRANSMITTED` | 409 Conflict |
| `ERR_EVENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_EVENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_EVENT_STILL_RUNNING` | 409 Conflict |
| `ERR_INSUFFICIENT_DOSES` | 422 Unprocessable Entity |
| `ERR_RECONCILIATION_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_MOBILE_LOT_OVER_RESERVED` | 422 Unprocessable Entity |
