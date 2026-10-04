# Provider Appointment Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the Provider Appointment Marketplace API, a Zocdoc-style platform that connects patients with bookable provider availability across a network of independent practices. The system centers on a hard commercial promise: a patient who searches by insurance plan must only ever see providers who actually accept that plan, and a provider who publishes a slot must never be double-booked. Those two promises force the platform to model attestation of insurance acceptance as a first-class, auditable lifecycle — not a static checkbox — and to treat calendar write-back from practice scheduling systems as an atomic, concurrency-guarded operation rather than a best-effort sync.

Around that core, the platform layers monetization and trust. Practices may be billed per attributed booking or on a flat monthly subscription; because per-booking billing is where disputes arise, the system computes attribution deterministically from a 90-day pre-existing-contact window and supports a full dispute and refund flow on invoices. Patient reliability is scored from no-show and late-cancellation strikes within a rolling epoch window, with recovery credit for completed visits; reviews are admitted only against verified completed visits; and an operations audit capability sweeps provider directories for stale availability and stale insurance attestations, escalating repeat insurance mismatches into automatic provider suspension.

The API is mounted under `/marketplace`. All time in the system is governed by a logical clock, never the wall clock; §2.6 defines how operators drive it.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply to every endpoint: identity and roles, the response envelope, pagination, resource conventions, monetary precision, the logical clock, concurrency control, validation ordering, and the error model.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. The declared roles are `Anonymous`, `Patient`, `Provider`, `PracticeStaff`, and `OpsAdmin`. A pseudo-role `Any` is used in endpoint definitions to indicate a public read endpoint callable by any declared role, including `Anonymous`; even on `Any` endpoints the two headers are still required. A request missing either header, or carrying an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not listed among the roles authorized for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity binding of `X-User-ID` differs by role:

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a patient (a booking, a review, a complaint, the patient's own record) compare the resource's `patient_id` to `X-User-ID`.
- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on provider-scoped resources compare the relevant `provider_id` to `X-User-ID`.
- When `X-User-Role` is `PracticeStaff`, `X-User-ID` is the `id` of the `Practice` the staff member operates; ownership checks on practice-scoped resources compare the relevant `practice_id` to `X-User-ID`.
- When `X-User-Role` is `OpsAdmin` or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, an attestation's `verified_by` captures the `X-User-ID` of the verifying `OpsAdmin` — but it is never compared to any entity's `id`.

Acting outside this ownership scope is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. All list endpoints sort by `created_at` ascending unless otherwise specified. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources carry a standard set of system-managed fields. `id` is a server-minted UUID string with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at creation and increments by 1 on every mutation of the resource. The entities `Practice`, `Provider`, `Slot`, `AppointmentType`, `InsurancePlan`, `Attestation`, `Patient`, `Booking`, `Charge`, `Invoice`, `Complaint`, `Review`, and `AuditCase` all carry the full set. Three entities — `ContactEvent`, `LedgerEntry`, and `VisitRecord` — are append-only records: they carry `id` and `created_at` only, and both `updated_at` and `version` are absent from them entirely.

### 2.5. Monetary Values, Rounding, and Integer Arithmetic

All monetary values are integer cents. Where a percentage is applied, each component is rounded independently using round half up before any subtraction takes place; the system never computes a raw total and rounds once at the end. This pinned rounding order applies to per-charge fee splitting (§3.6) and to invoice-level tier discounts (§3.7). Reliability scores and all counters are plain integers.

### 2.6. The Logical Clock

The marketplace never consults wall-clock time. All temporal comparisons — slot lead times, cancellation windows, attestation windows, audit staleness, strike aging — read a server-side logical clock. Before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z` and it never falls back to wall-clock time. An `OpsAdmin` may advance the clock by calling the clock-setting capability with a `to_iso8601` timestamp; the response echoes the resulting `current_utc`. This design makes every temporal rule in §3 deterministic and testable.

### 2.7. Nested Resource Retrieval and Existence Checking

For any request that references resources by identifier — in the URL path or in the request body — the system validates existence left to right: path identifiers first, in path order, then identifiers referenced from the request body. The path-parameter identifiers used across the API are `practice_id`, `provider_id`, `slot_id`, `type_id`, `plan_id`, `attestation_id`, `patient_id`, `event_id`, `booking_id`, `charge_id`, `invoice_id`, `entry_id`, `complaint_id`, `review_id`, `record_id`, and `case_id`. The first identifier that does not resolve to an existing resource short-circuits the request with the corresponding 404 error (`ERR_PRACTICE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_TYPE_NOT_FOUND`). No later check runs once an existence check has failed.

### 2.8. Validation Priority Ordering

When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order so the reported error is deterministic:

1. **Request context.** The `X-User-ID` / `X-User-Role` header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) runs before everything else.
2. **Role authorization.** The endpoint's role list (`ERR_FORBIDDEN`).
3. **Request schema.** Required fields present, types correct, enum members valid, `rating` within its 1-to-5 range, `end_at` strictly after `start_at`, and attestation `effective_to` strictly after `effective_from` (`ERR_INVALID_REQUEST`).
4. **Ownership scope** (`ERR_OWNERSHIP_MISMATCH`).
5. **Existence**, left to right per §2.7 (the `ERR_*_NOT_FOUND` family).
6. **State-machine admissibility.** The target entity must be in a state from which the requested transition exists — this includes a slot being `OPEN` for booking (`ERR_SLOT_NOT_OPEN`), a booking being `CONFIRMED` for cancellation (`ERR_BOOKING_NOT_CANCELLABLE`), an invoice being `ISSUED` for dispute (`ERR_INVOICE_NOT_DISPUTABLE`) or for payment with a positive balance (`ERR_INVOICE_NOT_PAYABLE`), a complaint being `OPEN` for a response or `UNDER_REVIEW` for resolution (`ERR_COMPLAINT_NOT_OPEN`), and the generic `ERR_INVALID_STATE` for all other illegal transitions.
7. **Temporal rules.** Slot start in the future at publication (`ERR_SLOT_IN_PAST`), lead-time satisfaction at booking (`ERR_LEAD_TIME_VIOLATION`), the two-hour cancellation floor (`ERR_CANCELLATION_TOO_LATE`), and no-show marking only at or after the appointment start (`ERR_NO_SHOW_TOO_EARLY`).
8. **Constraint rules.** Insurance plan acceptance (`ERR_PLAN_NOT_ACCEPTED`), appointment-type mapping (`ERR_TYPE_MAPPING_MISSING`), the new-patient type gate (`ERR_NEW_PATIENT_TYPE_BLOCKED`), the reliability gate (`ERR_RELIABILITY_GATE`, HTTP 403 despite sitting in this band), slot overlap (`ERR_SLOT_OVERLAP`), duplicate attestation (`ERR_DUPLICATE_ATTESTATION`), one review per booking (`ERR_DUPLICATE_REVIEW`), verified-visit requirement (`ERR_VISIT_NOT_VERIFIED`), and stale optimistic-concurrency versions (`ERR_STALE_VERSION`, HTTP 412 despite sitting in this band).
9. **Fiscal rules.** Billing-mode switch with pending charges (`ERR_PENDING_CHARGES`), charge-level operations against a subscription practice (`ERR_BILLING_MODE_MISMATCH`, HTTP 402), and practice/provider activity requirements for slot publication (`ERR_PRACTICE_NOT_ACTIVE` and `ERR_PROVIDER_NOT_BOOKABLE`, both HTTP 409 despite sitting in the fiscal band). On slot creation specifically, the provider-status check (`ERR_PROVIDER_NOT_BOOKABLE`) precedes the practice-status check (`ERR_PRACTICE_NOT_ACTIVE`); on invoice dispute against an invoice belonging to a `SUBSCRIPTION`-mode practice, `ERR_BILLING_MODE_MISMATCH` is raised after the existence and state checks.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

- The bulk schedule publish on a provider requires a non-optional `expected_provider_version` field in the request, carrying the provider `version` the client last observed. If the provider's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because a bulk publish legitimately supersedes the provider's future `OPEN` slot set — closing slots absent from the new payload — so a stale view would silently destroy slots created by a newer publish.
- The patient plan update requires a non-optional `expected_patient_version` field carrying the patient `version` the client last observed. A mismatch with the patient's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Plan updates are idempotent by value but not by intent: a newer writer's plan choice must not be silently overwritten by a writer holding an older view.

## 3. Business Logic & Workflows

### 3.1. Onboarding Practices, Providers, and the Bookability Derivation

An `OpsAdmin` onboards a practice by creating it with a `name`, an IANA `timezone`, and optional commercial and scheduling configuration. The practice's `billing_mode` is `PER_BOOKING` unless the operator passes `SUBSCRIPTION` at creation; `subscription_fee_cents` carries a default of 30000 (a flat monthly fee of 300.00 in the subscription currency unit) and is only meaningful in `SUBSCRIPTION` mode. Two scheduling thresholds default on the practice: `new_patient_lead_time_hours` defaults to 24 hours and `existing_patient_lead_time_hours` defaults to 4 hours. A new practice starts in `DRAFT` status.

A practice's back office then registers its providers. A `PracticeStaff` caller creates a provider with a `practice_id` that must equal the caller's own `X-User-ID`, plus a `display_name`, a `specialty` code such as `DERM`, and optionally a `lead_time_override_hours` that, when set, replaces both practice-level lead times for this provider; when null, the provider inherits from the practice. A new provider starts in `PENDING` status, with `insurance_mismatch_count` at 0.

Only an `OpsAdmin` may move a practice from `DRAFT` to `ACTIVE` via the activate transition, or a provider from `PENDING` to `ACTIVE`. Provider activation additionally requires the owning practice to be `ACTIVE`; otherwise the request is rejected with `ERR_PRACTICE_NOT_ACTIVE`. Both provider and practice support a suspension cycle: `ACTIVE` to `SUSPENDED`, and `SUSPENDED` back to `ACTIVE` via reinstatement — which for a provider again requires the owning practice to be `ACTIVE`. Suspension and delisting of a practice are operator actions; delisting is permitted from either `ACTIVE` or `SUSPENDED` and moves the practice to terminal `DELISTED`.

The derived field `bookable_in_directory` on a provider is true exactly when the provider's own `status` is `ACTIVE` and the owning practice's `status` is `ACTIVE`. It is recomputed on every provider status change and on every practice status change, which is why practice activation, suspension, and reinstatement each re-evaluate every provider of the practice.

Delisting is the destructive cascade. When a practice is delisted, every provider of that practice in `ACTIVE` or `SUSPENDED` status moves to `DELISTED`, and every future `OPEN` slot of those providers — those whose `start_at` is after the current logical time — moves to `CLOSED` with `close_reason` set to `PROVIDER_SUSPENDED`. When an individual provider is delisted (from `ACTIVE` or `SUSPENDED`) or suspended, the same slot cascade applies to that provider alone: every future `OPEN` slot is closed with `close_reason` `PROVIDER_SUSPENDED`, and `bookable_in_directory` becomes false. The system-driven cascade of a practice delist into its providers bypasses the per-provider state precondition — a provider in `ACTIVE` or `SUSPENDED` is delisted even though the operator-facing delist endpoint itself would reject a provider in any other state with `ERR_INVALID_STATE`.

A practice's commercial model can be renegotiated after onboarding. Switching `billing_mode` between `PER_BOOKING` and `SUBSCRIPTION` is an `OpsAdmin` action, but it is blocked while the practice has any charge still in `BILLABLE` status, rejected with `ERR_PENDING_CHARGES` — unswept per-booking revenue must first be invoiced before the practice's billing basis can change.

### 3.2. Publishing Availability: Slots, Overlap, and Bulk Calendar Sync

Availability enters the marketplace through calendar write-back. A provider account, or the `PracticeStaff` of the owning practice, publishes an individual slot by supplying `start_at` and `end_at` in ISO 8601 UTC; `end_at` must be strictly after `start_at`, and `start_at` must be strictly after the current logical time, otherwise the publish is rejected with `ERR_SLOT_IN_PAST`. Publication requires the provider to be bookable — the provider `ACTIVE` (`ERR_PROVIDER_NOT_BOOKABLE` when not) and the owning practice `ACTIVE` (`ERR_PRACTICE_NOT_ACTIVE` when not), with the provider check evaluated before the practice check. The slot's `provider_id` is taken from the URL path, not the payload.

Slots of one provider are half-open intervals — a slot occupies the span from its `start_at` up to but not including its `end_at`. Two intervals overlap when the first starts before the second ends and the second starts before the first ends. A new slot that overlaps any existing slot of the same provider whose status is `OPEN` or `BOOKED` is rejected with `ERR_SLOT_OVERLAP`; adjacency — one slot's `end_at` exactly equal to another's `start_at` — does not count as overlap, and `CLOSED` slots never block anything.

A slot is born `OPEN`. Booking flips it to `BOOKED` and sets `current_booking_id` to the occupying booking's id; a cancellation of that booking releases it back to `OPEN` and clears `current_booking_id` to null. A `BOOKED` slot moves to `CLOSED` when its occupying booking reaches `COMPLETED` (in which case `close_reason` becomes `PROVIDER_CLOSED`) or `NO_SHOW` (in which case `close_reason` becomes `PROVIDER_SUSPENDED`). An `OPEN` slot can be closed explicitly by the provider or the practice, which sets `close_reason` to `PROVIDER_CLOSED`; the audit sweep can close it with `close_reason` `AUDIT_SWEEP`; and provider suspension or delisting closes it with `close_reason` `PROVIDER_SUSPENDED`. Attempting the close endpoint on a slot that is not `OPEN` is rejected with `ERR_INVALID_STATE`; the system-driven cascades, by contrast, only ever touch `OPEN` slots. Closing is terminal.

Practice scheduling systems typically push whole calendars rather than single slots. The bulk publish accepts a `slots` array alongside the OCC field `expected_provider_version` (§2.9), and applies supersede semantics atomically: every slot in the payload is created — each one overlap-checked against the provider's existing `OPEN` and `BOOKED` slots exactly as a single publish would be — and every future `OPEN` slot of the provider that is not present in the payload is closed with `close_reason` `PROVIDER_CLOSED`. The response reports `created_count` and `closed_count`. A successful publish — single or bulk — increments the provider's `version` by 1; a booking, notably, does not touch the provider's version (only the slot's own `version` increments).

### 3.3. Appointment Types and Insurance Attestation

Before a provider can be booked, the marketplace needs to know what a booking means. A provider or the owning practice's staff maps a practice scheduling template into a marketplace-facing appointment type by supplying the template `code` (for example `NEW30`), a `display_name`, a `duration_minutes` length, and a `booked_copay_cents` amount that will be pinned onto each booking and its charge. The optional `accepts_new_patients` flag defaults to true and governs the new-patient gate described in §3.4. A type is born `ACTIVE`; either the provider or the practice may retire it, moving it to terminal `RETIRED`. Retirement never rewrites history — existing bookings keep the `booked_copay_cents` they pinned at booking time.

Insurance acceptance is modeled as a time-boxed claim, not a profile attribute. A provider or the practice's staff creates an attestation naming a `provider_id` and a `plan_id` together with an acceptance window: `effective_from` (inclusive) and `effective_to` (exclusive), where `effective_to` must be strictly after `effective_from`. The insurance plan catalog itself is operator-maintained: an `OpsAdmin` creates plans with a `carrier`, a `plan_name`, and a `plan_code` that must be unique across all plans; a plan is born `ACTIVE` and may be retired to terminal `RETIRED`, after which it no longer matches directory `plan_id` filters.

An attestation is born `ATTESTED`. An `OpsAdmin` reviews it through the verification action, which takes a `decision`: `VERIFY` moves the attestation to `VERIFIED` and records the operator's identity in `verified_by`, while `REJECT` moves it to terminal `REJECTED`. Verification requires the referenced plan to be `ACTIVE`; verifying against a retired plan is rejected with `ERR_PLAN_NOT_ACTIVE`. Two system-driven exits also exist: a `VERIFIED` attestation becomes `REVOKED` when an insurance-mismatch complaint is upheld against it (§3.5), and becomes `EXPIRED` when the epoch run or an audit sweep observes that its `effective_to` is at or before the current logical time. Submitting an attestation while another attestation for the same provider-and-plan pair is already `ATTESTED` or `VERIFIED` is rejected with `ERR_DUPLICATE_ATTESTATION`.

Only a `VERIFIED` attestation whose window contains the current logical time — `effective_from` at or before now, and now strictly before `effective_to` — counts as actual acceptance, and that single fact drives both directory filtering and booking validation.

### 3.4. Booking a Slot: The Full Validation Chain

Patient registration is open: an `Anonymous` caller creates a patient with a `full_name` and an `email` that must be unique across all patients, plus an optional self-declared `plan_id` — null means self-pay. New patients start with both `reliability_score` and `provisional_score` at 100 and an empty `strikes` array. A patient may later update their declared plan through a self-service update carrying the optional new `plan_id` and the mandatory `expected_patient_version` OCC field (§2.9); a successful update increments the patient's `version`.

Booking is the densest operation in the system. A `Patient` books an `OPEN` slot by posting the patient's own `patient_id` (which must equal `X-User-ID`), an `appointment_type_id`, and optionally an `insurance_plan_id` (null means self-pay). The booking's `provider_id` is copied from the slot, its `practice_id` is copied from the provider, and its `start_at` and `end_at` are copied from the slot. The checks run in the priority order of §2.8; the business-level gauntlet, in order, is:

- The slot must be `OPEN`, otherwise `ERR_SLOT_NOT_OPEN`.
- Lead time. The applicable lead time is the provider's `lead_time_override_hours` when set; otherwise the practice's `new_patient_lead_time_hours` if the patient is new to the practice, or its `existing_patient_lead_time_hours` otherwise. A patient is new — the booking's computed `is_new_patient` flag is true — exactly when they have no `COMPLETED` booking with this practice at booking time. The gap between the slot's `start_at` and now must be at least the applicable number of hours; exactly the lead time passes, one second less fails with `ERR_LEAD_TIME_VIOLATION`.
- Insurance acceptance. When `insurance_plan_id` is provided, the slot's provider must hold a `VERIFIED` attestation for that plan whose window contains now; otherwise the booking is rejected with `ERR_PLAN_NOT_ACCEPTED`.
- Type mapping. The appointment type must belong to the slot's provider and be `ACTIVE`; a type of another provider or a `RETIRED` type is rejected with `ERR_TYPE_MAPPING_MISSING`.
- New-patient gate. If the type's `accepts_new_patients` is false and the patient has no `COMPLETED` booking at this practice, the booking is rejected with `ERR_NEW_PATIENT_TYPE_BLOCKED`.
- Reliability gate. The patient's `reliability_score` must be at least 50 — exactly 50 passes, 49 fails with `ERR_RELIABILITY_GATE` (HTTP 403).

A successful booking is created in `CONFIRMED` status, pins `booked_copay_cents` from the appointment type, flips the slot from `OPEN` to `BOOKED`, and sets the slot's `current_booking_id`.

Attribution is computed at booking time and determines whether the marketplace may bill the practice. The system looks back over a window that opens exactly 90 days before the booking's `created_at` (inclusive) and ends at `created_at` itself (exclusive). If at least one `ContactEvent` exists for this patient whose `practice_id` equals the booking's practice or whose `provider_id` equals the booking's provider, and whose `contacted_at` falls inside that window, the booking's `attribution_status` is `ORGANIC` — a pre-existing relationship, never billed. Otherwise it is `ATTRIBUTED` — marketplace-acquired and billable. A contact exactly 90 days before `created_at` is inside the window (organic); one second earlier is outside (attributed). Practices record those pre-existing touches through a CRM write-back: a `PracticeStaff` caller logs a `ContactEvent` with a `patient_id`, an optional specific `provider_id`, the `contacted_at` timestamp, and a `channel` of `PHONE`, `EMAIL`, `PORTAL`, or `WALKIN`; the event's `practice_id` is taken from the acting staff member's `X-User-ID`.

A `Charge` is created at booking time only when the booking is `ATTRIBUTED` and the practice's `billing_mode` is `PER_BOOKING`. Two variants suppress the charge entirely: a subscription practice is billed its flat monthly fee instead of per booking, and an organic booking is never billed regardless of billing mode.

### 3.5. The Visit Lifecycle: Check-in, Completion, No-Show, and Cancellation

A booking's visit flow is operated by the practice. On the day of the appointment, `PracticeStaff` check the patient in — `CONFIRMED` to `CHECKED_IN` — and after the visit, complete the booking — `CHECKED_IN` to `COMPLETED`. Completion creates a `VisitRecord` for the booking whose `verification` is always `VERIFIED` (records are created only by this transition), whose `booking_id`, `provider_id`, and `patient_id` are copied from the booking, and whose `completed_at` is the logical-clock timestamp of completion. There is at most one visit record per booking. Completion also rewards reliability: the patient's `recovery_count` increases by 1, the reliability scores are recomputed (§3.8), and the occupied slot moves from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_CLOSED`.

If the patient never arrives, `PracticeStaff` mark the booking as a no-show — but only once the appointment time has actually been reached; marking before the booking's `start_at` is rejected with `ERR_NO_SHOW_TOO_EARLY`. A no-show appends a strike of kind `NO_SHOW` with magnitude 25 to the patient's `strikes`, stamped with the current epoch, recomputes reliability, and closes the slot from `BOOKED` to `CLOSED` with `close_reason` `PROVIDER_SUSPENDED`. The marketplace fee is not refunded on a no-show — any charge remains `BILLABLE`.

Cancellation follows a graded policy based on the hours between now and the booking's `start_at`, computed to second precision. Either the patient or the practice's staff may cancel a `CONFIRMED` booking — anything else is rejected with `ERR_BOOKING_NOT_CANCELLABLE`. Cancelling with 24 or more hours to go is free: `late_cancel` stays false and no strike is issued. Cancelling with at least 2 hours but strictly less than 24 hours to go is allowed but penalized: `late_cancel` is set true and a strike of kind `LATE_CANCEL` with magnitude 15 is appended, then reliability is recomputed. Cancelling with less than 2 hours to go is rejected outright with `ERR_CANCELLATION_TOO_LATE` — at exactly 2 hours the cancellation is allowed and penalized; at one second under 2 hours it is rejected. The booking's `cancel_reason` records who cancelled: `PATIENT` for a patient actor, `PRACTICE` for a `PracticeStaff` actor, and `RELIABILITY_GATE` when the system cancels. Every cancellation releases the slot from `BOOKED` back to `OPEN`.

The reliability gate cascade is the system's self-defending edge. Whenever a strike — no-show or late-cancel — causes the patient's recomputed `reliability_score` to fall below 50, every other `CONFIRMED` booking of that patient whose `start_at` is in the future is cancelled by the system with `cancel_reason` `RELIABILITY_GATE`, and each such booking's slot is released from `BOOKED` back to `OPEN`. The cascade only touches `CONFIRMED` bookings.

### 3.6. Per-Booking Monetization: The Fee Split

When a charge is created (per §3.4's attribution and billing-mode rules), its economics are computed in a pinned order from the booking's pinned `booked_copay_cents`, which becomes the charge's `gross_cents`. First, `marketplace_fee_cents` is the gross multiplied by fifteen percent, rounded half up to integer cents. Second, `processing_cents` is the gross multiplied by two point nine percent, rounded half up to integer cents, plus a flat 30 cents. Third, `net_to_practice_cents` is the gross minus the marketplace fee minus the processing amount. Each component is rounded independently before the subtraction; the system never rounds once at the end. As a worked example, a gross of 9999 cents yields a marketplace fee of 1500 cents, processing of 320 cents, and a net to the practice of 8179 cents. A new charge starts in `BILLABLE` status with `invoice_id` null; its `booking_id` and `practice_id` are copied from the booking.

### 3.7. Monthly Invoicing: Sweep, Tier Discount, Ledger, and Reconciliation

An `OpsAdmin` runs billing for a practice and a `period` — a year-month string in `YYYY-MM` format. The sweep collects every charge of that practice still in `BILLABLE` status whose booking's `created_at` falls within the period — from the first instant of the first day of the month up to but not including the first day of the following month — and moves each into `INVOICED` with `invoice_id` pointing at the new invoice. The new invoice is created in `ISSUED` status and stamped with a set of aggregates computed in a pinned order.

For a `PER_BOOKING` practice: `charge_count` is the number of swept charges; `fee_total_cents` is the sum of the swept charges' individual `marketplace_fee_cents` values — the per-charge rounded values, never re-derived from gross and never re-adjusted per charge after the discount is known; `discount_tier` is 0.20 when `charge_count` is at least 21, 0.10 when it is at least 11, and 0.00 otherwise; and `discount_cents` is `fee_total_cents` multiplied by `discount_tier`, rounded half up, computed once after `fee_total_cents` is final. As a worked example, eleven charges each carrying a fee of 1500 cents produce a `fee_total_cents` of 16500, a tier of 0.10, a `discount_cents` of 1650, and an `amount_due_cents` of 14850.

Every mutation of an invoice's money flows through its ledger. The sweep appends one `CHARGE_FEE` `LedgerEntry` per swept charge with `amount_cents` equal to that charge's positive `marketplace_fee_cents`, and — when `discount_cents` is greater than zero — one `TIER_DISCOUNT` entry with a negative amount equal to `discount_cents`. Ledger amounts are signed: fees are positive; discounts, credits, and payments are negative. For a `SUBSCRIPTION` practice the sweep skips charges entirely: a single `SUBSCRIPTION_FEE` entry is posted for the practice's `subscription_fee_cents`, `charge_count` stays 0, and per-booking charges are never swept. The invoice's `amount_due_cents` always equals the sum of the `amount_cents` values of its ledger entries and is recomputed on every ledger mutation. `LedgerEntry` rows carry the `invoice_id`, an optional `charge_id` (null for `TIER_DISCOUNT`, `SUBSCRIPTION_FEE`, `PAYMENT`, and `WRITE_OFF` entries), an `entry_type` from `CHARGE_FEE`, `TIER_DISCOUNT`, `DISPUTE_CREDIT`, `SUBSCRIPTION_FEE`, `PAYMENT`, `WRITE_OFF`, and an optional free-text `note`.

Two payout views are stamped at sweep time. `payout_provisional_cents` is the sum of the swept charges' `net_to_practice_cents` — the per-charge view that does not credit the tier discount back. `payout_final_cents` is the sum of the swept charges' `gross_cents`, minus the invoice's `amount_due_cents` billing part, minus the sum of the swept charges' `processing_cents` — the invoice-level view that does credit the discount back. The two always reconcile: `payout_final_cents` equals `payout_provisional_cents` plus `discount_cents`. As a worked example, eleven charges with a gross of 10000 cents each produce a provisional payout of 89980 cents, a final payout of 91630 cents, and a delta of 1650 cents that equals the discount.

Disputes let a practice contest specific attributed charges — the classic case being "this patient already knew us." A `PracticeStaff` caller disputes an `ISSUED` invoice — anything else is `ERR_INVOICE_NOT_DISPUTABLE` — by naming the contested `charge_ids` and a free-text `reason`. Every named charge must exist (`ERR_CHARGE_NOT_FOUND`), must belong to this invoice (`ERR_CHARGE_NOT_IN_INVOICE`), and must be `INVOICED` (otherwise `ERR_INVALID_STATE`). Disputing against an invoice belonging to a `SUBSCRIPTION`-mode practice is rejected with `ERR_BILLING_MODE_MISMATCH` after the existence and state checks. A valid dispute moves the invoice from `ISSUED` to `DISPUTED` and each named charge from `INVOICED` to `DISPUTED`.

An `OpsAdmin` resolves the dispute by supplying `resolutions` — an array of entries each naming a `charge_id` and an `action` of `KEEP` or `REMOVE`. Every `DISPUTED` charge of the invoice must appear in `resolutions` exactly once, otherwise the request is rejected with `ERR_INVALID_REQUEST`. A `KEEP` returns the charge from `DISPUTED` to `INVOICED`. A `REMOVE` moves the charge from `DISPUTED` to terminal `REFUNDED` and appends a `DISPUTE_CREDIT` ledger entry whose amount is the negative of that charge's `marketplace_fee_cents`. After resolution the invoice returns to `ISSUED` and `amount_due_cents` is recomputed from the ledger.

Settlement closes the loop. A `PracticeStaff` caller pays an `ISSUED` invoice whose `amount_due_cents` is greater than zero — otherwise `ERR_INVOICE_NOT_PAYABLE` — which appends a `PAYMENT` ledger entry equal to the negative of `amount_due_cents`, zeroes `amount_due_cents`, moves the invoice to `PAID`, and settles every `INVOICED` charge of the invoice into terminal `SETTLED`. Alternatively, an `OpsAdmin` may write off an `ISSUED` invoice, appending a `WRITE_OFF` entry equal to the negative of `amount_due_cents`, zeroing `amount_due_cents`, and moving the invoice to terminal `WRITTEN_OFF`.

### 3.8. Patient Reliability: Strikes, Recovery, and the Epoch

Patient reliability is a decaying ledger of misbehavior offset by a recovery credit. A patient's `strikes` is an array of entries each carrying an `epoch`, a `magnitude`, and a `kind` of `NO_SHOW` or `LATE_CANCEL`. The current epoch starts at 1, and a strike is active while its `epoch` is greater than or equal to the current epoch minus 3 — a four-epoch window counting the current epoch. Nothing is ever deleted from `strikes`; entries simply age out of the window as the epoch advances.

Two scores are derived. `provisional_score` is the pure windowed view: 100 minus the sum of the magnitudes of the active strikes, clamped to the range 0 to 100, ignoring recoveries entirely. `reliability_score` — the score the booking gate (§3.4) reads — adds a recovery credit of 10 points per `recovery_count` to the same windowed base, again clamped to 0 to 100. Identical strike data therefore yields a higher effective score whenever the patient has completed visits: one active no-show strike plus one completed-visit recovery gives a provisional score of 75 and an effective score of 85.

An `OpsAdmin` advances time's erosion through the epoch run capability, which increments the current epoch by 1, recomputes both scores for every patient that has at least one strike (strikes whose `epoch` falls below the window's edge simply stop counting), and expires every `VERIFIED` attestation whose `effective_to` is at or before now. The response reports the new `epoch`, the number of `decayed_strikes`, and the count of `patients_updated`.

### 3.9. Complaints, Insurance Mismatches, and Provider Auto-Suspension

A patient may file a complaint on any of their own bookings that is not `CANCELLED`, supplying the `booking_id`, a `complaint_type` of `INSURANCE_MISMATCH`, `DIRECTORY_INACCURACY`, or `OTHER`, and an optional free-text `description`. The complaint's `patient_id` and `provider_id` are copied from the booking. A complaint is born `OPEN`.

The practice gets the first word: a `PracticeStaff` response moves the complaint from `OPEN` to `UNDER_REVIEW` and stores the supplied `response` text; responding to a complaint that is not `OPEN` is rejected with `ERR_COMPLAINT_NOT_OPEN`. An `OpsAdmin` then resolves a complaint from `UNDER_REVIEW` — again `ERR_COMPLAINT_NOT_OPEN` otherwise — by supplying an `outcome` of `UPHOLD` or `DISMISS` and an optional `resolution_note`.

A dismissal simply records `outcome` as `DISMISS` and moves the complaint to terminal `RESOLVED_DISMISSED`. An upholding is where the insurance-integrity machinery engages. The complaint moves to terminal `RESOLVED_UPHELD` with `outcome` `UPHOLD`. When the complaint is an `INSURANCE_MISMATCH`, resolution additionally requires that an attestation selected by the booking's `provider_id` and `insurance_plan_id` with status `VERIFIED` — ties broken by earliest `created_at` — exists; without one the resolution is rejected with `ERR_INVALID_STATE`. That selected attestation is then moved from `VERIFIED` to `REVOKED`, and the provider's `insurance_mismatch_count` increases by 1.

The counter is a tripwire. When a provider's `insurance_mismatch_count` reaches 3, the system suspends the provider — `ACTIVE` to `SUSPENDED` — with the full suspension cascade: every future `OPEN` slot closes with `close_reason` `PROVIDER_SUSPENDED`, and `bookable_in_directory` is recomputed to false. This system-driven suspension mirrors exactly what an operator's manual suspension does.

### 3.10. Reviews: Verified Visits Only, with Moderation

A patient may review a visit, but only a real one. Creating a review supplies the `booking_id`, an integer `rating` from 1 to 5 inclusive, and optional `text`; the review's `patient_id` and `provider_id` are copied from the booking. The booking must have a `VERIFIED` `VisitRecord` — which, since visit records are created only by the completion transition, means the visit actually happened; a booking without one is rejected with `ERR_VISIT_NOT_VERIFIED`. At most one review exists per booking; a second attempt is rejected with `ERR_DUPLICATE_REVIEW`. A review is born `PUBLISHED`.

The practice side can flag a review — a `PracticeStaff` member of the owning practice or the reviewed provider itself — supplying a `reason`, which moves the review from `PUBLISHED` to `FLAGGED` and records the supplied text in `flag_reason`; flagging a non-`PUBLISHED` review is `ERR_INVALID_STATE`. Moderation is operator-only: an `OpsAdmin` moderates with an `action`. `RESTORE` on a `FLAGGED` review returns it to `PUBLISHED` and clears `flag_reason` to null. `REMOVE` on a review in either `PUBLISHED` or `FLAGGED` moves it to terminal `REMOVED`. Any other combination is `ERR_INVALID_STATE`.

### 3.11. Directory Accuracy Audits

The audit capability gives operations a deterministic instrument for directory hygiene. An `OpsAdmin` opens an audit case against a provider by supplying the `provider_id` and a `scope` of `AVAILABILITY`, `INSURANCE`, or `FULL`; the case starts `OPEN`.

Running the case inspects a deterministic sample. For `AVAILABILITY` scope the inspected items are the provider's slots; for `INSURANCE` scope, the provider's attestations; for `FULL` scope, slots first then attestations, combined. Items are ordered by `created_at` ascending — slots first for `FULL` — and at most 20 items are inspected. Within the sample, a slot is a mismatch of type `TIME_TRAVEL_SLOT` when it is `OPEN` but its `start_at` is before now; an attestation is a mismatch of type `INSURANCE_STALE` when it is `VERIFIED` but its `effective_to` is at or before now. The run stamps `sampled_count` with the number of inspected items, `mismatch_count` with the number matching a predicate, and `mismatch_rate` with `mismatch_count` divided by the larger of 1 and `sampled_count`. Severity follows with strict thresholds: `severity` is `CRITICAL` when the mismatch rate is strictly greater than 0.20, `WARN` when strictly greater than 0.05, and `CLEAN` otherwise. With a full sample of 20 items, one mismatch is a rate of 0.05 and `CLEAN`; two is 0.10 and `WARN`; four is 0.20 and still `WARN`; five is 0.25 and `CRITICAL`.

The run is also a remediation sweep. Every slot flagged as a `TIME_TRAVEL_SLOT` finding is moved from `OPEN` to `CLOSED` with `close_reason` `AUDIT_SWEEP`, and every attestation flagged as an `INSURANCE_STALE` finding is moved from `VERIFIED` to `EXPIRED`. The `findings` array is populated with one entry per mismatch, each carrying a `finding_index`, a `finding_type` of `TIME_TRAVEL_SLOT` or `INSURANCE_STALE`, the `ref_id` of the offending slot or attestation, and a `resolved` flag initialized to false. When the run finds zero mismatches the case moves directly from `OPEN` to terminal `CLOSED_CLEAN`; otherwise it moves from `OPEN` to `FINDINGS_OPEN`.

From `FINDINGS_OPEN`, an operator works the findings: the resolve-finding action takes a `finding_index` and a `resolution_note` and flips that finding's `resolved` flag to true. Only when every finding is resolved may the operator close the case — `FINDINGS_OPEN` to terminal `CLOSED`; closing with any unresolved finding is rejected with `ERR_UNRESOLVED_FINDINGS`. Any run or close attempted from the wrong state is `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, sweeps, moderation actions — return `200 OK`. Read endpoints return `200 OK`. The clock-setting capability returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marketplace/_clock/set_current_utc` | Set the logical clock | OpsAdmin |
| POST | `/marketplace/ops/run-epoch` | Advance the reliability epoch and expire stale attestations | OpsAdmin |
| POST | `/marketplace/practices` | Create a practice | OpsAdmin |
| GET | `/marketplace/practices` | List practices | Any |
| GET | `/marketplace/practices/{practice_id}` | Get a practice | Any |
| POST | `/marketplace/practices/{practice_id}/activate` | Activate a DRAFT practice | OpsAdmin |
| POST | `/marketplace/practices/{practice_id}/suspend` | Suspend an ACTIVE practice | OpsAdmin |
| POST | `/marketplace/practices/{practice_id}/reinstate` | Reinstate a SUSPENDED practice | OpsAdmin |
| POST | `/marketplace/practices/{practice_id}/delist` | Delist a practice; cascades to providers and future OPEN slots | OpsAdmin |
| POST | `/marketplace/practices/{practice_id}/billing-mode` | Switch the practice's billing mode | OpsAdmin |
| POST | `/marketplace/providers` | Create a provider under the acting practice | PracticeStaff |
| GET | `/marketplace/providers` | Directory search with `specialty`, `plan_id`, `bookable_only`, `practice_id` filters | Any |
| GET | `/marketplace/providers/{provider_id}` | Get a provider | Any |
| POST | `/marketplace/providers/{provider_id}/activate` | Activate a PENDING provider | OpsAdmin |
| POST | `/marketplace/providers/{provider_id}/suspend` | Suspend an ACTIVE provider; closes future OPEN slots | OpsAdmin |
| POST | `/marketplace/providers/{provider_id}/reinstate` | Reinstate a SUSPENDED provider | OpsAdmin |
| POST | `/marketplace/providers/{provider_id}/delist` | Delist a provider; closes future OPEN slots | OpsAdmin |
| POST | `/marketplace/providers/{provider_id}/slots` | Publish a single slot | Provider, PracticeStaff |
| POST | `/marketplace/providers/{provider_id}/slots/bulk-publish` | Atomic calendar sync push with supersede semantics (OCC-guarded) | Provider, PracticeStaff |
| GET | `/marketplace/slots` | Search slots with `provider_id`, `status`, `from`, `to` filters | Any |
| GET | `/marketplace/slots/{slot_id}` | Get a slot | Any |
| POST | `/marketplace/slots/{slot_id}/close` | Close an OPEN slot | Provider, PracticeStaff |
| POST | `/marketplace/providers/{provider_id}/appointment-types` | Map a marketplace appointment type to a scheduling template | Provider, PracticeStaff |
| GET | `/marketplace/appointment-types` | List appointment types with `provider_id`, `status` filters | Any |
| GET | `/marketplace/appointment-types/{type_id}` | Get an appointment type | Any |
| POST | `/marketplace/appointment-types/{type_id}/retire` | Retire an appointment type | Provider, PracticeStaff |
| POST | `/marketplace/insurance-plans` | Create an insurance plan | OpsAdmin |
| GET | `/marketplace/insurance-plans` | List insurance plans with `carrier`, `status` filters | Any |
| GET | `/marketplace/insurance-plans/{plan_id}` | Get an insurance plan | Any |
| POST | `/marketplace/insurance-plans/{plan_id}/retire` | Retire an insurance plan | OpsAdmin |
| POST | `/marketplace/attestations` | Attest acceptance of a plan over a window | Provider, PracticeStaff |
| GET | `/marketplace/attestations` | List attestations with `provider_id`, `plan_id`, `status` filters | OpsAdmin, Provider, PracticeStaff |
| GET | `/marketplace/attestations/{attestation_id}` | Get an attestation | OpsAdmin, Provider, PracticeStaff |
| POST | `/marketplace/attestations/{attestation_id}/verify` | Verify or reject an attestation | OpsAdmin |
| POST | `/marketplace/patients` | Register a patient | Anonymous |
| GET | `/marketplace/patients` | List patients with `plan_id` filter | OpsAdmin |
| GET | `/marketplace/patients/{patient_id}` | Get a patient (self or operator) | Patient, OpsAdmin |
| PATCH | `/marketplace/patients/{patient_id}` | Update the patient's insurance plan (OCC-guarded) | Patient |
| POST | `/marketplace/contact-events` | Record a pre-existing patient contact | PracticeStaff |
| GET | `/marketplace/contact-events` | List contact events with `patient_id`, `practice_id`, `provider_id` filters | PracticeStaff, OpsAdmin |
| GET | `/marketplace/contact-events/{event_id}` | Get a contact event | PracticeStaff, OpsAdmin |
| POST | `/marketplace/slots/{slot_id}/bookings` | Book an OPEN slot | Patient |
| GET | `/marketplace/bookings` | List bookings with patient, provider, slot, practice, type, plan, and status filters | Patient, PracticeStaff, OpsAdmin |
| GET | `/marketplace/bookings/{booking_id}` | Get a booking | Patient, PracticeStaff, OpsAdmin |
| POST | `/marketplace/bookings/{booking_id}/cancel` | Cancel a CONFIRMED booking | Patient, PracticeStaff |
| POST | `/marketplace/bookings/{booking_id}/check-in` | Check in a CONFIRMED booking | PracticeStaff |
| POST | `/marketplace/bookings/{booking_id}/complete` | Complete a CHECKED_IN booking; creates the verified visit record | PracticeStaff |
| POST | `/marketplace/bookings/{booking_id}/mark-no-show` | Mark a CONFIRMED booking as no-show | PracticeStaff |
| GET | `/marketplace/charges` | List charges with `booking_id`, `practice_id`, `invoice_id`, `status` filters | OpsAdmin, PracticeStaff |
| GET | `/marketplace/charges/{charge_id}` | Get a charge | OpsAdmin, PracticeStaff |
| POST | `/marketplace/billing/generate-invoices` | Sweep a practice's billable charges for a period into an invoice | OpsAdmin |
| GET | `/marketplace/invoices` | List invoices with `practice_id`, `status` filters | OpsAdmin, PracticeStaff |
| GET | `/marketplace/invoices/{invoice_id}` | Get an invoice | OpsAdmin, PracticeStaff |
| POST | `/marketplace/invoices/{invoice_id}/dispute` | Dispute named charges on an ISSUED invoice | PracticeStaff |
| POST | `/marketplace/invoices/{invoice_id}/resolve-dispute` | Resolve a dispute with per-charge KEEP/REMOVE actions | OpsAdmin |
| POST | `/marketplace/invoices/{invoice_id}/pay` | Pay an ISSUED invoice | PracticeStaff |
| POST | `/marketplace/invoices/{invoice_id}/write-off` | Write off an ISSUED invoice | OpsAdmin |
| GET | `/marketplace/ledger-entries` | List ledger entries with `invoice_id`, `charge_id`, `entry_type` filters | OpsAdmin, PracticeStaff |
| GET | `/marketplace/ledger-entries/{entry_id}` | Get a ledger entry | OpsAdmin, PracticeStaff |
| POST | `/marketplace/complaints` | File a complaint on an own booking | Patient |
| GET | `/marketplace/complaints` | List complaints with `booking_id`, `provider_id`, `patient_id`, `status` filters | OpsAdmin, PracticeStaff, Patient |
| GET | `/marketplace/complaints/{complaint_id}` | Get a complaint | OpsAdmin, PracticeStaff, Patient |
| POST | `/marketplace/complaints/{complaint_id}/respond` | Respond to an OPEN complaint | PracticeStaff |
| POST | `/marketplace/complaints/{complaint_id}/resolve` | Resolve an UNDER_REVIEW complaint | OpsAdmin |
| POST | `/marketplace/reviews` | Create a review of a verified visit | Patient |
| GET | `/marketplace/reviews` | List reviews with `provider_id`, `booking_id`, `patient_id`, `status` filters | Any |
| GET | `/marketplace/reviews/{review_id}` | Get a review | Any |
| POST | `/marketplace/reviews/{review_id}/flag` | Flag a PUBLISHED review | PracticeStaff, Provider |
| POST | `/marketplace/reviews/{review_id}/moderate` | Moderate a review (restore or remove) | OpsAdmin |
| GET | `/marketplace/visit-records` | List visit records with `booking_id`, `provider_id`, `patient_id` filters | PracticeStaff, OpsAdmin, Patient |
| GET | `/marketplace/visit-records/{record_id}` | Get a visit record | PracticeStaff, OpsAdmin, Patient |
| GET | `/marketplace/bookings/{booking_id}/visit-records` | List the visit records for a booking (zero or one) | PracticeStaff, OpsAdmin, Patient |
| POST | `/marketplace/audit-cases` | Open a directory-accuracy audit case | OpsAdmin |
| GET | `/marketplace/audit-cases` | List audit cases with `provider_id`, `status` filters | OpsAdmin |
| GET | `/marketplace/audit-cases/{case_id}` | Get an audit case | OpsAdmin |
| POST | `/marketplace/audit-cases/{case_id}/run` | Execute the audit sweep | OpsAdmin |
| POST | `/marketplace/audit-cases/{case_id}/resolve-finding` | Mark one finding resolved | OpsAdmin |
| POST | `/marketplace/audit-cases/{case_id}/close` | Close a case once all findings are resolved | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PRACTICE_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_ATTESTATION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_TYPE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRACTICE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROVIDER_NOT_BOOKABLE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_SLOT_NOT_OPEN` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_COMPLAINT_NOT_OPEN` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_UNRESOLVED_FINDINGS` | 409 Conflict |
| `ERR_SLOT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CANCELLATION_TOO_LATE` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_TYPE_MAPPING_MISSING` | 422 Unprocessable Entity |
| `ERR_NEW_PATIENT_TYPE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_RELIABILITY_GATE` | 403 Forbidden |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ATTESTATION` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |
| `ERR_VISIT_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PENDING_CHARGES` | 409 Conflict |
| `ERR_BILLING_MODE_MISMATCH` | 402 Payment Required |
