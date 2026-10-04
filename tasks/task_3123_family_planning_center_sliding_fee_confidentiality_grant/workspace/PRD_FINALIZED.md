# Family Planning Center API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Family Planning Center API, a system supporting the operational, clinical, and financial workflows of a federally funded family planning network modeled on Planned Parenthood affiliates. The platform must reconcile three regulatory commitments that often pull in opposite directions: a sliding-fee pricing engine that guarantees access regardless of ability to pay, confidentiality guarantees for minors and for insured patients who wish to keep services off a policyholder's explanation-of-benefits, and federal grant compliance obligations that demand auditable reporting on encounter volume, demographic composition, and contraceptive inventory valuation.

Each **Affiliate** in the network operates under its own state law and fee schedule, publishes a service catalog that may differ from its neighbors, and manages its own contraceptive stock, providers, and grant reports. Patients are assessed against a federal poverty level schedule to determine a fee tier; encounters consume that assessment; claims against third-party payers must respect confidentiality suppressions that override ordinary billing logic; and grant reports must capture low-income service quotas and device valuations under one of two pinned inventory-valuation variants.

The API is the system of record. Every fee decision, every privacy hold, every claim submission, and every grant report is mediated through it, and its validation pipeline is ordered so that privacy protections always take precedence over state-machine errors when both would apply.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and contracts that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting operator and `X-User-Role` declaring that operator's capacity. A request missing either header, or carrying a role string the server does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers parse, the server verifies that the named role is permitted to invoke the operation; a violation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `GrantAdministrator`, `FrontDeskStaff`, `Clinician`, `BillingSpecialist`, `CareCoordinator`, `SupplyCoordinator`, and `PrivacyOfficer`.

All seven roles use **opaque** operator identifiers. For every role above, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as an entry in `authorized_staff_ids` on a `PrivacyHold` where the `PrivacyOfficer` whitelists specific operators) but never compares it to the `id` of any entity in the data model. There is no `entity_backed` role in this system; ownership checks always consult the explicit allowlists and role matrix rather than foreign-key equality against `X-User-ID`.

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

All list endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10, accepts a minimum of 1 and a maximum of 100; `offset` defaults to 0 and accepts any non-negative integer. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending. The `meta` block of any paginated response contains `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that increments on every mutation of the resource and is the currency of optimistic concurrency. All entities in this system — `Affiliate`, `ServiceCatalogEntry`, `FeeScheduleTier`, `Patient`, `HouseholdAssessment`, `Provider`, `ProviderLicense`, `Encounter`, `Claim`, `ContraceptiveStockLot`, `DeviceReservation`, `ReferralOrder`, `GrantReport`, and `PrivacyHold` — carry the full set of `id`, `created_at`, `updated_at`, and `version`; no entity in this system uses the reduced `common_fields: false` shape.

### 2.5. The Logical Clock

The system runs on a logical clock rather than wall-clock time. At server startup the logical clock reads `2026-09-01T00:00:00Z`; it MUST NOT silently fall back to wall-clock time before the first explicit clock-set call. A `GrantAdministrator` advances the clock by submitting a `to_iso8601` timestamp to a test-driving endpoint, which returns the new `current_utc`. Setting the clock re-derives two families of derived state: `ProviderLicense` rows whose `valid_until` now precedes the new logical time transition to `EXPIRED`, and every `Patient`'s `is_minor` flag is recomputed against the new current date. All "current time" comparisons anywhere in this document — fee tier effective windows, privacy hold coverage, report finalization windows, telehealth license containment, lot expiry — are evaluated against this logical clock.

### 2.6. Monetary Values, Percentages, and Precision

All monetary values are carried as integer cents — never as floats, never as decimal dollars. This applies to `full_fee_cents`, `nominal_copay_cents`, `annual_income_cents`, `patient_charge_cents`, `billed_cents`, `paid_cents`, `recouped_cents`, `net_receivable_cents`, `unit_cost_cents`, and `device_value_cents`.

Where a calculation produces a percentage, that percentage is an **integer percent** computed by truncation toward zero (floor), not by rounding. Where a calculation produces a discounted amount, the discount itself is floored to integer cents **before** being subtracted from the gross amount — round-then-subtract, never sum-then-round. The per-line rounding rule for sliding-fee charges is covered in §3.4.

### 2.7. Hierarchical Consistency and Cascading State

The entity hierarchy is rooted at the `Affiliate`. `ServiceCatalogEntry`, `FeeScheduleTier`, `Patient`, `Provider`, `ContraceptiveStockLot`, and `GrantReport` are direct children of an affiliate; `HouseholdAssessment` and `PrivacyHold` hang off `Patient`; `ProviderLicense` hangs off `Provider`; `Encounter` hangs off `Patient`; and `Claim`, `DeviceReservation`, and `ReferralOrder` hang off `Encounter`.

When an affiliate's lifecycle state changes, the cascade is immediate and automatic. Suspending an affiliate transitions every `ACTIVE` catalog entry of that affiliate to `SUSPENDED`; reinstating an affiliate transitions every `SUSPENDED` entry back to `ACTIVE`. A catalog entry that is `SUSPENDED` blocks creation of new encounters for that `service_code`, with the rejection surfacing as `ERR_SERVICE_OUT_OF_SCOPE` — the gate is enforced at validation time rather than by mutating existing encounters. Every cascade that mutates a parent resource refreshes its `updated_at` and increments its `version`.

### 2.8. Nested Resource Retrieval

The API validates nested path identifiers left-to-right. A request to a child of a non-existent parent fails at the parent's 404 before the server even attempts to resolve the child. The not-found error identifiers follow the per-entity pattern: `ERR_AFFILIATE_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_HOLD_NOT_FOUND`. Each carries HTTP 404.

### 2.9. Optimistic Concurrency Control

Two write endpoints in this system carry a mandatory optimistic-concurrency check on a parent resource; no other endpoint takes a version field.

When a client creates a `HouseholdAssessment` for a patient, the request must carry `expected_patient_version` matching the patient's current `version`. If another writer has advanced the patient's `version` since the client last read it — most commonly because a prior assessment superseded the one the client is about to displace — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the writer to re-read the patient before superseding someone else's assessment.

When a client creates a `GrantReport` for an affiliate — whether an initial report or an amendment — the request must carry `expected_affiliate_version` matching the affiliate's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a writer whose view of the affiliate's reporting lineage is stale from silently forking the amendment chain.

### 2.10. Validation Pipeline Order

Validation failures on a single request are reported in a fixed priority order, not in arbitrary order. The order is: (1) header presence and shape, surfaced as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) RBAC permission, surfaced as `ERR_INSUFFICIENT_PERMISSIONS`; (3) path-parameter existence, surfaced as the appropriate `ERR_*_NOT_FOUND`; (4) parent-affiliate-active checks for child creation, surfaced as `ERR_AFFILIATE_NOT_ACTIVE`; (4.5) privacy-hold authorization, surfaced as `ERR_PRIVACY_HOLD_BLOCKS_ACCESS`; (5) state-machine validity, surfaced as `ERR_INVALID_STATE`; (5.5) the current-assessment precondition for encounter creation, surfaced as `ERR_NO_CURRENT_ASSESSMENT`; (6) the confidential-suppression gate for claim submission, surfaced as `ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL`; (7) service-catalog scope checks, surfaced as `ERR_SERVICE_OUT_OF_SCOPE`; (8) telehealth licensure containment, surfaced as `ERR_TELEHEALTH_LICENSE_GAP`; (9) temporal well-formedness, surfaced as `ERR_INVALID_INTERVAL`; (10) privacy-hold overlap, surfaced as `ERR_PRIVACY_HOLD_OVERLAP`; (11) device reservation safety, surfaced as one of `ERR_INVALID_STATE`, `ERR_STOCK_UNAVAILABLE`, `ERR_LOT_EXPIRED`, or `ERR_REINSERTION_WINDOW_EXCEEDED`; (12) fiscal caps on payments and recoupments, surfaced as `ERR_OVERPAYMENT` or `ERR_RECOUPMENT_EXCEEDS_PAID`; and (13) grant-report period checks, surfaced as `ERR_REPORT_PERIOD_OPEN` or `ERR_REPORT_PERIOD_OVERLAP`.

Three conflict pairs deserve explicit statement because the orderings are otherwise ambiguous. First, the privacy-hold gate (priority 4.5) runs **before** state checks on patient-scoped requests: a state-invalid action against a held patient returns `ERR_PRIVACY_HOLD_BLOCKS_ACCESS`, never the state error. Second, an encounter creation that is simultaneously out-of-scope and license-gapped returns `ERR_SERVICE_OUT_OF_SCOPE` (priority 7) before `ERR_TELEHEALTH_LICENSE_GAP` (priority 8). Third, a claim submission that would both violate the confidential-suppression gate and exceed a fiscal cap returns `ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL` (priority 6) before any fiscal error, because the safety gate runs ahead of payment arithmetic.

## 3. Business Logic & Workflows

### 3.1. Affiliate Onboarding and Lifecycle

A `GrantAdministrator` opens a new affiliate by submitting an `affiliate_code` (a unique string such as "PP-SW-07"), the two-letter `state_code` the affiliate operates in, and a `low_income_priority_quota` integer between 0 and 100 expressing the minimum percentage of grant-cycle encounters that must serve patients below the federal poverty line. A newly registered affiliate enters `ACTIVE` status with `grant_cycle_open` set to `true` and `version` initialized to 1.

The affiliate's lifecycle has three states: `ACTIVE`, `SUSPENDED`, and `CLOSED`. Suspension and reinstatement are paired operations. A `GrantAdministrator` may suspend an `ACTIVE` affiliate, which flips the affiliate to `SUSPENDED` and cascades every `ACTIVE` `ServiceCatalogEntry` under it to `SUSPENDED`. While suspended, attempts to create new encounters against any of that affiliate's catalog entries are rejected with `ERR_SERVICE_OUT_OF_SCOPE`. Reinstatement reverses the cascade, flipping `SUSPENDED` catalog entries back to `ACTIVE`. Either transition increments the affiliate's `version` by 1 and refreshes `updated_at`.

Closure is terminal. A `GrantAdministrator` may close an affiliate from either `ACTIVE` or `SUSPENDED`, but only when the affiliate has no encounter in `SCHEDULED` or `IN_PROGRESS` — otherwise the closure is rejected with `ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS` (HTTP 409). Closure also increments `version`.

Throughout the affiliate's life, any creation of a child resource — patient, provider, catalog entry, fee tier, stock lot, or grant report — requires the parent affiliate to be `ACTIVE`; otherwise the create is rejected with `ERR_AFFILIATE_NOT_ACTIVE` (HTTP 409).

### 3.2. Catalog, Fee Schedule, and Provider Configuration

Once an affiliate exists, a `GrantAdministrator` builds its service catalog and fee schedule. A catalog entry is created with a `service_code` (for example `CONTRACEPTIVE_COUNSELING`, `LARC_INSERTION`, or `STI_SCREEN`), a boolean `in_scope` declaring whether the affiliate and its state law allow in-house delivery, an optional `telehealth_eligible` flag defaulting to `false`, and the undiscounted `full_fee_cents` list price. Catalog entries enter `ACTIVE` status and may be flipped to `SUSPENDED` only through the affiliate-level cascade — there is no per-entry suspension endpoint.

Fee tiers are configured per affiliate as a set of half-open bands over the federal-poverty-level percentage. Each tier carries a `tier_code` label (`A`, `B`, `C`, `D`, or `E`), a `fpl_pct_min_inclusive` lower bound, a `fpl_pct_max_exclusive` upper bound (the band is `[min, max)`), a `discount_pct` integer between 0 and 100, an optional `nominal_copay_cents` floor defaulting to 0 that the patient owes even at full discount, and a `requires_documentation` boolean that gates the tier away from self-declared income.

Providers are registered with a `display_name` and a `provider_type` enum of `PHYSICIAN`, `NP`, `RN`, or `COUNSELOR`. Provider suspension is out of scope for this system: a `Provider` is always `ACTIVE`. A provider's authority to practice across state lines is captured through `ProviderLicense` rows, each recording the `state_code` it authorizes, an inclusive `valid_from` timestamp, and an **exclusive** `valid_until` timestamp. The license status enum is `ACTIVE` or `EXPIRED`, with `EXPIRED` derived automatically whenever the logical clock passes `valid_until`; there is no explicit suspend path.

### 3.3. Patient Registration and the Sliding-Fee Assessment

A `FrontDeskStaff` operator registers a patient under an affiliate, supplying an `external_ref` (an opaque client-facing reference — never the patient `id`), a `date_of_birth`, an optional `confidentiality_flag` defaulting to `false`, and an optional `insurance_policy_id` defaulting to null. The patient's `is_minor` flag is computed by the server: it is `true` exactly when the logical-clock current date minus `date_of_birth` is less than 18 years. Patients are never deleted or archived; `status` is always `ACTIVE`.

Before any encounter can be scheduled, the patient must hold a **current** household assessment. A `FrontDeskStaff` operator creates one by submitting `household_size` (an integer count of household members, at least 1), `annual_income_cents` (declared or documented annual income in cents, at least 0), an `income_basis` enum of `DOCUMENTED` or `SELF_DECLARED`, and the OCC field `expected_patient_version` described in §2.9. The server computes the assessment's `fpl_pct` and `assigned_tier_code`, sets `effective_from` to the logical-clock timestamp, marks the new assessment `CURRENT`, and supersedes the patient's prior `CURRENT` assessment if one existed. Creation increments the patient's `version` by 1.

The **FPL percentage** is computed against a fixed table of annual-cents bases indexed by household size: size 1 → 1506000, size 2 → 2044200, size 3 → 2582400, size 4 → 3120600, size 5 → 3658800, size 6 → 4197000, size 7 → 4735200, size 8 → 5273400. Households larger than 8 use the size-8 base plus 538200 cents for each member beyond the eighth. The `fpl_pct` is then the integer floor of `annual_income_cents` multiplied by 100 and divided by the applicable base — truncated toward zero. Income exactly equal to the base yields exactly 100, not 99.

The **tier assignment** runs immediately after the FPL computation, against the affiliate's `FeeScheduleTier` rows. Candidate tiers are those whose half-open band contains `fpl_pct` — that is, `fpl_pct_min_inclusive` is less than or equal to `fpl_pct` and `fpl_pct` is strictly less than `fpl_pct_max_exclusive`. The candidate set is then filtered by the assessment's `income_basis`. A `DOCUMENTED` assessment is eligible for every candidate. A `SELF_DECLARED` assessment is eligible only for candidates whose `requires_documentation` is `false` **and** whose `discount_pct` does not exceed 80 — the self-declaration ceiling — regardless of any tier configuration to the contrary. If the filtered eligible set is empty, the assessment creation fails with `ERR_NO_ELIGIBLE_TIER` (HTTP 422). If multiple candidates remain (overlapping misconfiguration), the server deterministically selects the one with the highest `discount_pct`, breaking ties first by the lowest `fpl_pct_min_inclusive` and then by the tier's `created_at` ascending.

The dual variant between `DOCUMENTED` and `SELF_DECLARED` is intentional: identical income and household size can yield different `assigned_tier_code` values depending on which basis the assessment was recorded under.

### 3.4. Encounter Scheduling and the Sliding-Fee Charge

A `FrontDeskStaff` operator schedules an encounter for a patient by supplying the `service_code`, the delivering `provider_id`, a `channel` enum of `IN_PERSON` or `TELEHEALTH`, an optional `patient_location_state` (the two-letter state the patient is physically in — required for telehealth), a `scheduled_start`, and a `scheduled_end` strictly greater than `scheduled_start`. The new encounter pins the patient's `CURRENT` household assessment into its `assessment_id` field at scheduling time; if no current assessment exists, creation is rejected with `ERR_NO_CURRENT_ASSESSMENT` (HTTP 422). The encounter's `affiliate_id` is denormalized from the patient. New encounters enter clinical status `SCHEDULED` and billing status `UNBILLED`.

The encounter's `patient_charge_cents` is computed from the catalog entry for `service_code` and the pinned assessment's tier. The discount in cents is the floor of `full_fee_cents` multiplied by the tier's `discount_pct` and divided by 100; the patient charge is then `full_fee_cents` minus that floored discount, with the further constraint that the charge never falls below the tier's `nominal_copay_cents` floor. The evaluation order is pinned: each per-service discount is rounded down **before** any subtraction, and a multi-service visit sums the per-service rounded charges — round-per-line-then-sum; the alternative sum-then-round ordering is forbidden. All arithmetic is integer cents.

The **temporal well-formedness** check runs on every encounter creation: `scheduled_end` must be strictly greater than `scheduled_start`, and the affiliate's `grant_cycle_open` must be `true` at creation time — a closed grant cycle rejects the encounter with `ERR_INVALID_INTERVAL` (HTTP 400), as does a malformed interval.

The **scope check** requires the encounter's `service_code` to resolve to an `ACTIVE` catalog entry of the affiliate whose `in_scope` is `true`. A `service_code` that is missing from the catalog, present but with `in_scope` false, or present but `SUSPENDED` (whether directly or through an affiliate-level suspension cascade) rejects the encounter with `ERR_SERVICE_OUT_OF_SCOPE` (HTTP 422); in those cases a `ReferralOrder` is the correct artifact, not an encounter.

The **telehealth licensure check** applies whenever `channel` is `TELEHEALTH`. The delivering provider must hold a `ProviderLicense` whose `state_code` equals the encounter's `patient_location_state`, whose status is `ACTIVE`, whose `valid_from` is less than or equal to the encounter's `scheduled_start`, and whose `valid_until` is greater than or equal to the encounter's `scheduled_end`. The containment is over the **whole** encounter interval: a license valid at the start instant but expiring mid-encounter fails the check, and point-in-time checks are forbidden — the entire half-open encounter interval `[scheduled_start, scheduled_end)` must be contained in the half-open license interval `[valid_from, valid_until)`. Failure is rejected with `ERR_TELEHEALTH_LICENSE_GAP` (HTTP 422). When both the scope check and the licensure check would fail on the same encounter creation, the scope error wins, as described in §2.10.

### 3.5. Encounter Execution, Cancellation, and Device Fulfillment

Once scheduled, an encounter's clinical dimension moves through `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, while its billing dimension moves through `UNBILLED`, `CLAIMED`, `SETTLED`, or `WAIVED`. The two dimensions evolve in parallel, and the terminal shapes are constrained: a `CANCELLED` encounter's billing is always `UNBILLED` or `WAIVED`, and a `COMPLETED` encounter's billing ends at `SETTLED` or `WAIVED`.

A `Clinician` starts a scheduled encounter, transitioning clinical status from `SCHEDULED` to `IN_PROGRESS`. The start is permitted only when the logical clock has reached `scheduled_start`; attempting to start early is rejected with `ERR_INVALID_STATE`.

A `Clinician` completes an `IN_PROGRESS` encounter, transitioning clinical status to `COMPLETED`. Completion is the trigger that fulfills every `RESERVED` device reservation attached to the encounter: each reservation moves to `FULFILLED`, and the parent stock lot loses the unit from both pools — `on_hand` is decremented by 1 **and** `reserved_out` is decremented by 1, so the physical unit leaves stock while the reservation placeholder is released. Completion also makes the affiliate's grant-cycle aggregates eligible for recompute at the next `GrantReport` generation.

A `FrontDeskStaff` operator cancels a `SCHEDULED` encounter, transitioning clinical status to `CANCELLED`. Cancellation releases reservations rather than fulfilling them: each attached reservation in `RESERVED` moves to `RELEASED`, and the lot's `reserved_out` is decremented by 1 while `on_hand` is unchanged — the compensating invariant restores the reserved pool without removing any physical unit.

### 3.6. Contraceptive Stock and Device Reservations

A `SupplyCoordinator` receives contraceptive inventory into an affiliate by registering a stock lot with a `device_code` (one of `IUD_COPPER`, `IUD_HORMONAL`, or `IMPLANT`), the manufacturer `lot_number`, the `unit_cost_cents` acquisition cost per unit, the initial `on_hand` count, and an `expires_on` ISO date beyond which the lot must not be dispensed. The lot's `reserved_out` counter is initialized to 0.

To stage a long-acting device for an insertion encounter, a `SupplyCoordinator` creates a device reservation against the encounter, identifying the `lot_id` and optionally flagging `is_rapid_reinsertion` (defaulting to `false`) with an accompanying `expulsion_recorded_at` timestamp (defaulting to null). Creation succeeds only against an encounter whose clinical status is `SCHEDULED` — reservations against started or completed encounters are rejected with `ERR_INVALID_STATE`. The lot must have `on_hand` minus `reserved_out` greater than or equal to 1; otherwise the create is rejected with `ERR_STOCK_UNAVAILABLE` (HTTP 422). On success, the lot's `reserved_out` increments by 1 and `on_hand` is unchanged — the unit is earmarked but still on the shelf.

The expiry rule distinguishes normal and rapid-reinsertion reservations. A normal reservation may not use a lot whose `expires_on` precedes the encounter date at all; such a create is rejected with `ERR_LOT_EXPIRED` (HTTP 422). A reservation flagged as rapid reinsertion is eligible only when the gap between the encounter's `scheduled_start` and the supplied `expulsion_recorded_at` is at most 30 days, evaluated with second precision; the comparison is inclusive, so exactly 30 days is eligible and 30 days plus one second is not, with violations rejected as `ERR_REINSERTION_WINDOW_EXCEEDED` (HTTP 422). An eligible rapid reinsertion may draw from a lot whose `expires_on` falls within a 7-day grace window around the encounter date — a tolerance that does not apply to normal reservations.

Reservations terminate in one of two ways. Fulfillment happens automatically on encounter completion as described in §3.5. Release happens either automatically on encounter cancellation or manually when a `SupplyCoordinator` releases a specific reservation; in both cases the lot's `reserved_out` decrements by 1 and `on_hand` is unchanged. The reservation status enum is `RESERVED`, `FULFILLED`, or `RELEASED`.

### 3.7. Billing, Claims, and the Confidential-Suppression Gate

When a completed encounter remains in billing status `UNBILLED`, a `BillingSpecialist` may open a `Claim` against it. Claim creation copies the patient's `insurance_policy_id` into the claim's `policy_id` and computes two flags. The `confidential_suppression` flag is set to `true` whenever the patient was a minor at the time of the encounter **or** the patient's `confidentiality_flag` is `true`; confidential services bypass third-party billing entirely. The `billed_cents` amount is then derived: when `confidential_suppression` is `true`, `billed_cents` is 0 (the claim exists for records only and nothing is billed to a payer); otherwise `billed_cents` is the catalog `full_fee_cents` minus the encounter's `patient_charge_cents`. The claim's `paid_cents` and `recouped_cents` both start at 0, its `net_receivable_cents` is computed as `billed_cents` minus `paid_cents` plus `recouped_cents`, its `submission_round` starts at 1, and its initial status is `DRAFT`. Claim creation does **not** itself flip the encounter's billing status — that flip happens at submission.

The claim lifecycle walks `DRAFT` → `SUBMITTED` → `PAID`/`DENIED`/`RETURNED` → (resubmit loop) → terminal. A `BillingSpecialist` submits a `DRAFT` claim; the preconditions are that the parent encounter's clinical status is `COMPLETED` and the claim's `confidential_suppression` is `false` — a suppressed claim may never reach a payer, and submitting one is rejected with `ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL` (HTTP 422). Successful submission flips the encounter's `billing_status` from `UNBILLED` to `CLAIMED`.

A payer may return a submitted claim for correction; a `BillingSpecialist` records that transition as `SUBMITTED` → `RETURNED`. A returned claim may be resubmitted, flipping back to `SUBMITTED` and incrementing `submission_round` by 1, but only while `submission_round` is strictly less than 3 — a resubmit attempted at round 3 is rejected with `ERR_CLAIM_RESUBMISSION_EXHAUSTED` (HTTP 409).

Adjudication and denial are terminal. A `BillingSpecialist` adjudicates a `SUBMITTED` claim by supplying an `amount_cents` payment; the transition is `SUBMITTED` → `PAID`, the `paid_cents` counter accumulates the payment, and `net_receivable_cents` is recomputed. The payment is capped: an amount exceeding the current `net_receivable_cents` is rejected with `ERR_OVERPAYMENT` (HTTP 422). Denial moves `SUBMITTED` → `DENIED` without further arithmetic. Void is available only on `DRAFT` claims: it moves the claim to `VOID`, and if an earlier submission had flipped the encounter's billing to `CLAIMED`, the void reverses that flip back to `UNBILLED` — otherwise the encounter's billing is unchanged.

A `BillingSpecialist` may post a recoupment against a `PAID` claim by supplying an `amount_cents`. The recoupment is capped at `paid_cents` minus `recouped_cents`; a larger amount is rejected with `ERR_RECOUPMENT_EXCEEDS_PAID` (HTTP 422). A successful recoupment adds to `recouped_cents` and recomputes `net_receivable_cents` — the compensating invariant that conserves `paid_cents` minus `recouped_cents` against `billed_cents`. The claim remains in `PAID` status through recoupment posting.

The encounter's billing dimension closes in one of two ways. Settlement is available when the encounter is `COMPLETED` and `CLAIMED` and the open claim has reached `PAID` with `net_receivable_cents` equal to 0, or has reached `DENIED` (the denial implying a patient write-off). Settlement flips the encounter from `CLAIMED` to `SETTLED`; settling under any other claim configuration is rejected with `ERR_CLAIM_NOT_SETTLEABLE` (HTTP 409). Waiver is the alternative path: a `BillingSpecialist` may waive billing on a `COMPLETED`/`UNBILLED` encounter whenever the patient is confidential — that is, the patient's `confidentiality_flag` is `true` or the patient was a minor at encounter time — flipping billing from `UNBILLED` to `WAIVED`. Confidential services bypass third-party billing entirely.

### 3.8. The Assessment-Supersede Cascade

Creating a new `HouseholdAssessment` for a patient who already holds a `CURRENT` assessment triggers a four-link cascade. The chain runs synchronously inside the create.

**Link 1** — the prior `CURRENT` assessment moves to `SUPERSEDED`, and the new assessment becomes the patient's only `CURRENT` one. The patient's `version` increments and `updated_at` refreshes.

**Link 2** — every encounter of the patient whose billing status is `UNBILLED` or `CLAIMED` re-pins its `assessment_id` to the new current assessment and recomputes `patient_charge_cents` under the new tier. Encounters in `SETTLED` or `WAIVED` are never re-priced. Each re-priced encounter's `version` increments and `updated_at` refreshes.

**Link 3** — for every re-priced encounter whose billing status is `CLAIMED`, the open `Claim`'s `billed_cents` is recomputed under the new charge (and `net_receivable_cents` recomputes accordingly), and the claim's `updated_at` refreshes.

**Link 4** — any `DRAFT` `GrantReport` of the affiliate whose half-open `[period_start, period_end)` window covers a re-priced encounter's `scheduled_start` refreshes its aggregate fields. The `encounter_count` is unchanged (the encounter was already counted), but `low_income_encounter_count` and `device_value_cents` are re-derived under the new assessments.

### 3.9. Referral Pathways

When a clinician encounters a service need that is out of scope — whether because state law forbids it, the affiliate does not offer it, or capacity is exhausted — the system captures the handoff as a `ReferralOrder` rather than as an encounter. Either a `Clinician` or a `CareCoordinator` may originate a referral by supplying the `requested_service_code`, the `receiving_org` external organization name, and a `reason_code` enum of `OUT_OF_SCOPE_STATE_LAW`, `OUT_OF_SCOPE_AFFILIATE`, or `CAPACITY`. New referrals enter `OPEN`.

A `CareCoordinator` owns the referral lifecycle from there. An `OPEN` referral may be acknowledged (`OPEN` → `ACKNOWLEDGED`) or withdrawn (`OPEN` → `WITHDRAWN`). An `ACKNOWLEDGED` referral may be completed (`ACKNOWLEDGED` → `COMPLETED`) or withdrawn (`ACKNOWLEDGED` → `WITHDRAWN`). `COMPLETED` and `WITHDRAWN` are terminal.

### 3.10. Grant Reporting and Amendment

A `GrantAdministrator` generates a `GrantReport` against an affiliate by supplying a `period_start` (inclusive), a `period_end` (exclusive — the reporting window is half-open), a `valuation_variant` enum of `FIFO` or `WEIGHTED_AVERAGE` pinning which device-valuation rule the report will use, an optional `amendment_of` reference when the new report amends a prior `FINALIZED` report, and the OCC field `expected_affiliate_version` described in §2.9. The new report enters `DRAFT` with its aggregates computed from the encounter history, and the affiliate's `version` increments by 1.

The aggregates are computed as follows. `encounter_count` is the count of `COMPLETED` encounters of the affiliate whose `scheduled_start` falls in `[period_start, period_end)`. `low_income_encounter_count` is the count of those encounters whose pinned assessment has `fpl_pct` strictly less than 100 — a patient at exactly 100% FPL does **not** count toward the quota. `minor_encounter_count` is the count of those encounters whose patient was `is_minor` at the encounter's `scheduled_start`. `low_income_quota_met` is `true` when `low_income_encounter_count` multiplied by 100 is greater than or equal to `encounter_count` multiplied by the affiliate's `low_income_priority_quota`; exact equality counts as met, and a period with zero encounters reports `true`. The arithmetic is integer-only — no float division is permitted anywhere in the comparison.

The `device_value_cents` aggregate depends on the pinned `valuation_variant`. The input set in both variants is the `FULFILLED` device reservations whose encounter's `scheduled_start` falls in `[period_start, period_end)`, joined to their stock lots. Under `FIFO`, fulfilled units are valued in order of each unit's lot `created_at` ascending and then the reservation's `created_at` ascending, with each unit valued at its own lot's `unit_cost_cents`. Under `WEIGHTED_AVERAGE`, the server computes a per-`device_code` average cost as the floor of (sum of `unit_cost_cents` multiplied by units fulfilled from each lot) divided by (total units fulfilled of that device code), then multiplies that average by the units of that code and sums across codes. The two variants produce different `device_value_cents` whenever lots of the same `device_code` carry different `unit_cost_cents` — this is the second intentional dual-variant pair in the system, alongside the documented/self-declared pair from §3.3.

Two period-shape constraints govern reporting. Finalization requires the period to have closed: a finalize attempted before the logical clock has reached `period_end` is rejected with `ERR_REPORT_PERIOD_OPEN` (HTTP 409). And no two `DRAFT` reports on the same affiliate may have overlapping half-open periods; creation of a second overlapping draft is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409).

Finalization transitions the report from `DRAFT` to `FINALIZED`. Amendment is the only path past `FINALIZED`: when a new report is created with `amendment_of` pointing at a `FINALIZED` report, the amended report transitions to `SUPERSEDED`, and the amending report captures the amended report's aggregates as its baseline. The amendment chain depth is unrestricted. `SUPERSEDED` is the terminal state.

### 3.11. Privacy Holds and Confidential Access

A `PrivacyOfficer` may place a privacy hold on a patient by supplying `hold_start` (inclusive), `hold_end` (exclusive — half-open), a `scope` enum of `RECORD_VIEW`, `BILLING_CORRESPONDENCE`, or `ALL`, and an `authorized_staff_ids` array of opaque staff identifiers permitted through the hold (an empty array means no one). The hold enters `ACTIVE`. The same officer may release an `ACTIVE` hold, transitioning it to `RELEASED`.

Overlap rules are strict: a same-patient, same-scope `ACTIVE` hold may not overlap the requested half-open interval. Two half-open intervals overlap exactly when the existing hold's `hold_start` is strictly before the new hold's `hold_end` **and** the new hold's `hold_start` is strictly before the existing hold's `hold_end`. Adjacent intervals — where the new hold's `hold_start` equals the existing hold's `hold_end` — do **not** overlap and do **not** merge; they remain distinct holds. Overlapping same-scope holds are rejected with `ERR_PRIVACY_HOLD_OVERLAP` (HTTP 409); the system never silently merges. Holds of different scopes may overlap freely.

The hold's enforcement is described in §2.10. In effect, any caller whose `X-User-ID` is not on the `authorized_staff_ids` of any `ACTIVE` hold covering the logical-clock now (at scope `RECORD_VIEW` or `ALL`) may not read or mutate the patient record or any descendant resource — encounters, claims, household assessments, device reservations, or referral orders of that patient. The rejection is `ERR_PRIVACY_HOLD_BLOCKS_ACCESS` (HTTP 403). The privacy-hold management endpoints themselves — creating, listing, reading, and releasing holds — are never blocked by a hold; otherwise the officer would be unable to release the very hold that locks the record.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — lifecycle transitions, submissions, adjudications, releases, waivers, finalize — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/family-planning/_clock/set_current_utc` | Set the logical clock | GrantAdministrator |
| POST | `/family-planning/affiliates` | Register an affiliate | GrantAdministrator |
| GET | `/family-planning/affiliates` | List affiliates | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/affiliates/{affiliateId}` | Get one affiliate | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/affiliates/{affiliateId}/suspend` | Suspend affiliate; cascades catalog entries to SUSPENDED | GrantAdministrator |
| POST | `/family-planning/affiliates/{affiliateId}/reinstate` | Reinstate affiliate; cascades catalog entries back to ACTIVE | GrantAdministrator |
| POST | `/family-planning/affiliates/{affiliateId}/close` | Close affiliate (no open encounters) | GrantAdministrator |
| POST | `/family-planning/affiliates/{id}/service-catalog` | Add a service to the affiliate catalog | GrantAdministrator |
| GET | `/family-planning/affiliates/{id}/service-catalog` | List catalog entries of an affiliate | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/service-catalog/{entryId}` | Get one service catalog entry | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/affiliates/{id}/fee-tiers` | Add a sliding-fee tier band | GrantAdministrator |
| GET | `/family-planning/affiliates/{id}/fee-tiers` | List fee tiers of an affiliate | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/fee-tiers/{tierId}` | Get one fee schedule tier | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, SupplyCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/affiliates/{id}/patients` | Register a patient | FrontDeskStaff |
| GET | `/family-planning/affiliates/{id}/patients` | List patients of an affiliate | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/patients/{patientId}` | Get one patient | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/patients/{id}/household-assessments` | Create an assessment; supersedes prior CURRENT | FrontDeskStaff |
| GET | `/family-planning/patients/{id}/household-assessments` | List assessments of a patient | GrantAdministrator, PrivacyOfficer, BillingSpecialist, FrontDeskStaff |
| GET | `/family-planning/household-assessments/{assessmentId}` | Get one household assessment | GrantAdministrator, PrivacyOfficer, BillingSpecialist, FrontDeskStaff |
| GET | `/family-planning/household-assessments/{id}/encounters` | List encounters currently pinned to an assessment | GrantAdministrator, PrivacyOfficer, BillingSpecialist, FrontDeskStaff |
| POST | `/family-planning/affiliates/{id}/providers` | Register a provider | GrantAdministrator |
| GET | `/family-planning/affiliates/{id}/providers` | List providers | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/providers/{providerId}` | Get one provider | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/providers/{id}/licenses` | Add a state license to a provider | GrantAdministrator |
| GET | `/family-planning/providers/{id}/licenses` | List licenses of a provider | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/licenses/{licenseId}` | Get one provider license | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/patients/{id}/encounters` | Schedule an encounter | FrontDeskStaff |
| GET | `/family-planning/patients/{id}/encounters` | List encounters of a patient | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/affiliates/{id}/encounters` | List encounters delivered by an affiliate | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/providers/{id}/encounters` | List encounters delivered by a provider | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician, FrontDeskStaff |
| GET | `/family-planning/encounters/{encounterId}` | Get one encounter | GrantAdministrator, PrivacyOfficer, BillingSpecialist, CareCoordinator, Clinician, FrontDeskStaff |
| POST | `/family-planning/encounters/{encounterId}/start` | Start an encounter | Clinician |
| POST | `/family-planning/encounters/{encounterId}/complete` | Complete an encounter; fulfills device reservations | Clinician |
| POST | `/family-planning/encounters/{encounterId}/cancel` | Cancel a scheduled encounter; releases reservations | FrontDeskStaff |
| POST | `/family-planning/encounters/{encounterId}/waive-billing` | Waive third-party billing for a confidential completed encounter | BillingSpecialist |
| POST | `/family-planning/encounters/{id}/claims` | Create a DRAFT claim for a completed unbilled encounter | BillingSpecialist |
| GET | `/family-planning/encounters/{id}/claims` | List claims of an encounter | GrantAdministrator, PrivacyOfficer, BillingSpecialist |
| GET | `/family-planning/claims/{claimId}` | Get one claim | GrantAdministrator, PrivacyOfficer, BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/submit` | Submit a DRAFT claim | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/return` | Payer returns a submitted claim for correction | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/resubmit` | Resubmit a returned claim | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/adjudicate` | Apply a payer payment | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/deny` | Deny a submitted claim | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/void` | Void a DRAFT claim | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/recoup` | Payer recoups funds from a PAID claim | BillingSpecialist |
| POST | `/family-planning/claims/{claimId}/settle` | Settle encounter billing once claim is PAID (net 0) or DENIED | BillingSpecialist |
| POST | `/family-planning/affiliates/{id}/stock-lots` | Receive a contraceptive stock lot | SupplyCoordinator |
| GET | `/family-planning/affiliates/{id}/stock-lots` | List stock lots | GrantAdministrator, SupplyCoordinator, Clinician |
| GET | `/family-planning/stock-lots/{lotId}` | Get one stock lot | GrantAdministrator, SupplyCoordinator, Clinician |
| GET | `/family-planning/stock-lots/{id}/device-reservations` | List reservations against a lot | GrantAdministrator, SupplyCoordinator, Clinician |
| POST | `/family-planning/encounters/{id}/device-reservations` | Reserve a device unit for an insertion encounter | SupplyCoordinator |
| GET | `/family-planning/encounters/{id}/device-reservations` | List reservations of an encounter | GrantAdministrator, SupplyCoordinator, Clinician |
| GET | `/family-planning/device-reservations/{reservationId}` | Get one device reservation | GrantAdministrator, SupplyCoordinator, Clinician |
| POST | `/family-planning/device-reservations/{reservationId}/release` | Manually release a reservation | SupplyCoordinator |
| POST | `/family-planning/encounters/{id}/referral-orders` | Create a referral for an out-of-scope need | Clinician, CareCoordinator |
| GET | `/family-planning/encounters/{id}/referral-orders` | List referrals of an encounter | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician |
| GET | `/family-planning/referral-orders/{referralId}` | Get one referral order | GrantAdministrator, PrivacyOfficer, CareCoordinator, Clinician |
| POST | `/family-planning/referral-orders/{referralId}/acknowledge` | Acknowledge a referral | CareCoordinator |
| POST | `/family-planning/referral-orders/{referralId}/complete` | Complete an acknowledged referral | CareCoordinator |
| POST | `/family-planning/referral-orders/{referralId}/withdraw` | Withdraw an open or acknowledged referral | CareCoordinator |
| POST | `/family-planning/affiliates/{id}/grant-reports` | Generate a DRAFT grant report (initial or amendment) | GrantAdministrator |
| GET | `/family-planning/affiliates/{id}/grant-reports` | List grant reports of an affiliate | GrantAdministrator, PrivacyOfficer |
| GET | `/family-planning/grant-reports/{reportId}` | Get one grant report | GrantAdministrator, PrivacyOfficer |
| GET | `/family-planning/grant-reports/{id}/amendments` | List amendment reports of a given report | GrantAdministrator, PrivacyOfficer |
| POST | `/family-planning/grant-reports/{reportId}/finalize` | Finalize a DRAFT report whose period has closed | GrantAdministrator |
| POST | `/family-planning/patients/{id}/privacy-holds` | Place a privacy hold | PrivacyOfficer |
| GET | `/family-planning/patients/{id}/privacy-holds` | List privacy holds of a patient | GrantAdministrator, PrivacyOfficer |
| GET | `/family-planning/privacy-holds/{holdId}` | Get one privacy hold | GrantAdministrator, PrivacyOfficer |
| POST | `/family-planning/privacy-holds/{holdId}/release` | Release an active hold | PrivacyOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_AFFILIATE_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_ENCOUNTER_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AFFILIATE_NOT_ACTIVE` | 409 Conflict |
| `ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 400 Bad Request |
| `ERR_NO_CURRENT_ASSESSMENT` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_TIER` | 422 Unprocessable Entity |
| `ERR_SERVICE_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_TELEHEALTH_LICENSE_GAP` | 422 Unprocessable Entity |
| `ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL` | 422 Unprocessable Entity |
| `ERR_CLAIM_RESUBMISSION_EXHAUSTED` | 409 Conflict |
| `ERR_CLAIM_NOT_SETTLEABLE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_RECOUPMENT_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_STOCK_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_LOT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REINSERTION_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRIVACY_HOLD_BLOCKS_ACCESS` | 403 Forbidden |
| `ERR_PRIVACY_HOLD_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_OPEN` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
