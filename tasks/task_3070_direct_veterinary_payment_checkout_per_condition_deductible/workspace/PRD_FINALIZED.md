# Direct Vet Payment API — Product Requirements Document

## 1. Introduction

Pet insurance has historically forced owners to pay the full veterinary invoice at the counter and then wait weeks for reimbursement — a delay that drives owners to decline recommended care, and leaves hospitals in the awkward position of advocating treatment the client cannot immediately afford. This product eliminates that gap: software installed inside veterinary hospitals adjudicates a claim **during the visit** and pays the hospital directly for the insurer's share, so the owner only ever pays their member responsibility at the counter.

Two design decisions distinguish this system from conventional pet insurance. First, deductibles are tracked **per condition over the pet's lifetime** rather than per policy year: once the deductible for a given condition is consumed, every subsequent treatment of that same condition is reimbursed without further deductible. Second, reimbursement is computed from the actual invoice cost with **no payout caps** — there is no annual or lifetime maximum, and benefit-schedule disputes are replaced by deterministic line categorization (covered treatment versus excluded exam fees, taxes, and other excluded charges).

The system also owns the regulatory and financial plumbing this model requires: territory-based rate filings that must pass through a state insurance filing lifecycle before they can price a policy, age-band premium recalculation as pets grow older, waiting-period enforcement separating injury coverage from illness coverage, medical-record-driven pre-existing condition determination, a claim appeal process with medical-record requests and segregation-of-duties resolution, and dual-variant ledger reconciliation that lets a hospital verify that every direct payment — and every clawback — is accounted for. All temporal behavior (waiting periods, filing effectiveness, settlement delays, premium sweeps) is driven by a controllable logical clock so that the full lifecycle can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. A request whose role is not permitted for the operation — or whose entity-backed identity check fails (wrong hospital, wrong owner) — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly five roles, spelled exactly as follows: `PlatformAdmin`, `RateFilingAdmin`, `HospitalStaff`, `ClaimsAdjuster`, and `PetOwner`.

- A `PlatformAdmin` is the insurer's platform operator: it onboards hospitals, marks policies lapsed for non-payment, forces premium recalculation, generates and acknowledges reconciliation reports, and controls the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `RateFilingAdmin` is the regulatory rate-filing specialist who creates and files `TerritoryRateFiling` resources. When `X-User-Role` is `RateFilingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `ClaimsAdjuster` adjudicates and denies claims and manages appeals, subject to the segregation-of-duties rule at appeal resolution. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — but it is recorded on an appeal as the appeal's `original_adjuster_id` when that appeal is opened, so the later resolution can compare against it.
- `HospitalStaff` identity is entity-backed: when `X-User-Role` is `HospitalStaff`, `X-User-ID` is the `id` of the acting `Hospital`, and any operation restricted to "staff of this hospital" compares the request's hospital path or body reference to `X-User-ID`. Staff submit claims, receive direct payment, upload medical records, submit appeal records, and dispute reconciliation reports.
- `PetOwner` identity is entity-backed: when `X-User-Role` is `PetOwner`, `X-User-ID` is the `id` of the owner's `Policy` (the policyId-bound owner id), and ownership checks on any resource that references a `Policy` compare the resource's policy foreign key to `X-User-ID`. An owner enrolls and cancels their policy and opens appeals on its claims.

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and must not exceed 100. `offset` defaults to 0. List results are always sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter (not just the returned page) and `has_more` indicates whether further records exist beyond the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry the common fields: `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that starts at its creation value and is incremented by exactly 1 on every mutation of that resource). Every lazy or sweep-driven transition a resource undergoes is itself such a mutation, so a single request that triggers sweep transitions (clock advance, lazy evaluation on read, or an operation that first runs lazy evaluation on its target) in addition to its own state change advances the version once per transition — the version after such a request is strictly higher than before it, but the exact delta is determined by how many intermediate transitions fired. The `TerritoryRateFiling`, `Hospital`, `Policy`, `PolicyCondition`, `Claim`, `Payment`, and `ClaimAppeal` resources all carry the full common-field set.

Two resources deliberately carry only `id` and `created_at`: `MedicalRecord` and `ReconciliationReport` have **no** `updated_at` and **no** `version` field, because a medical record is an immutable clinical artifact and a reconciliation report transitions only its `status` without versioned mutation.

All time in the system is governed by a **logical clock**, never the wall clock. Before any clock operation is performed, the logical clock stands at exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` may advance it through the clock-setting capability, which takes a `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock fires four system sweeps: the policy waiting-period transitions, the rate-filing effectiveness transition, the claim settlement-delay transition, and the age-band premium recalculation sweep. The same lazy evaluations also run when a `Policy` or a `Claim` is read, so a client never observes a stale enrollment or settlement status after the clock has crossed a threshold. They likewise run when a `TerritoryRateFiling` is read or otherwise handled: a filed filing whose effective date has been reached may already be observed as `EFFECTIVE` in the response of the very request that handled it (including the filing request's own response).

Every timestamp the server emits — including system-derived business timestamps such as `injury_waiting_end`, `illness_waiting_end`, and `records_due_at`, not just the common `created_at` and `updated_at` fields — is rendered as an ISO 8601 UTC timestamp with exactly three fractional digits (millisecond precision, `Z` suffix). Two timestamp strings that render differently but denote the same UTC instant are equivalent for the purposes of this document; the instants pinned throughout this document are exact, while the string rendering of any server-produced timestamp always follows this millisecond format.

### 2.5. Optimistic Concurrency Control

Two write endpoints enforce optimistic concurrency control, and only those two take a version field.

An adjudication request on a claim must carry `expected_claim_version`, equal to the claim's `version` the client last observed. If the claim's current `version` has advanced since then — for example because another adjuster already flagged, cleared, adjudicated, or denied it — the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), and no mutation occurs.

A hospital approval request must carry `expected_hospital_version`, equal to the hospital's `version` the client last observed. If the hospital's current `version` does not match, the request is rejected with `ERR_STALE_HOSPITAL_VERSION` (HTTP 412). An administrator acting on a stale snapshot must re-read the hospital before retrying.

No other endpoint accepts or requires an expected-version field.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Every premium multiplication and every per-line reimbursement multiplication is rounded **half-up to whole cents at the per-line (or per-premium) multiplication step only**; claim-level totals are then formed by **summing the already-rounded per-line values**. Sum-then-round is forbidden. No other rounding occurs anywhere else in the system; deductible accounting, eligibility, ledger balances, and reconciliation amounts are pure integer-cent arithmetic with no rounding step.

### 2.7. Validation Order and Resource Resolution

When a request fails several checks at once, the error the client receives is determined by a fixed priority order, evaluated in this sequence:

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the operation (`ERR_UNAUTHORIZED`).
3. Existence of path identifiers, validated **left to right** as they appear in the URL — `hospitalId` before `policyId` before `claimId` before `appealId` before `filingId` before `reportId` — each missing identifier yielding its specific not-found error (`ERR_HOSPITAL_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`).
4. Existence of body-referenced identifiers — a `policy_id`, a `hospital_id`, every element of `medical_record_ids`, and the target of an expected-version field — yielding `ERR_POLICY_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, or `ERR_RECORD_NOT_FOUND` as applicable.
5. State admissibility — the target resource must be in a state from which the requested transition exists, otherwise `ERR_INVALID_STATE` (expressed through its state-specific aliases `ERR_HOSPITAL_NOT_APPROVABLE`, `ERR_FILING_NOT_FILABLE`, `ERR_CLAIM_NOT_ADJUDICATABLE`, `ERR_CLAIM_NOT_PAYABLE`, `ERR_APPEAL_NOT_OPENABLE`, `ERR_APPEAL_NOT_RESOLVABLE`). A transition that has no dedicated alias — training completion, hospital suspension and reinstatement, policy cancel, mark-lapsed, and premium recalculation state gates, claim flag/clear review and deny, appeal record request and submission, and reconciliation report acknowledge/dispute — surfaces the bare error id `ERR_INVALID_STATE` itself (HTTP 409).
6. Business temporal checks — the waiting-period gate (`ERR_WAITING_PERIOD_ACTIVE`).
7. Business safety checks — the pre-existing condition gate (`ERR_PREEXISTING_CONDITION`).
8. Business referential checks on appeal record submission (`ERR_RECORD_NOT_FOUND`, `ERR_RECORD_ALREADY_ATTACHED`, `ERR_APPEAL_WINDOW_EXPIRED`).
9. Segregation-of-duties and ownership constraints (`ERR_SELF_RESOLUTION_FORBIDDEN`, `ERR_UNAUTHORIZED`).
10. Hospital-active and policy-active gates (`ERR_HOSPITAL_NOT_ACTIVE`, `ERR_POLICY_NOT_ACTIVE`).
11. Fiscal and syntactic business rules (`ERR_RATE_NOT_FILED`, `ERR_FILING_RETROACTIVE`, `ERR_INVALID_REQUEST`, `ERR_CONDITION_CODE_REQUIRED`).

Malformed payloads — a missing required field, a wrong type, a non-positive invoice line amount, an enum violation, or a treatment line missing its condition code at intake — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Rating Territories and the Regulatory Filing Lifecycle

Every premium in the system traces back to a `TerritoryRateFiling` — the artifact a `RateFilingAdmin` creates to register prices with a state regulator. A filing is created with its `territory_code` (the postal prefix that defines the rating territory, for example 941), its `state_code` (the two-letter regulator state code), the `species` it prices (`DOG` or `CAT`), the `base_monthly_premium_cents` that applies to a pet of age band 0, an `age_band_multipliers` map from integer age band — the floor of the pet's age in whole years — to a decimal multiplier (for example a band of "0" at 1.0 and a band of "1" at 1.05), the `filing_effective_date` on or after which the rates may be applied, and the `regulator_reference` carrying the state department-of-insurance filing number. Creation is a 201 and the filing begins life in `DRAFT` status.

Filing with the regulator transitions a filing from `DRAFT` to `FILED`, stamps `filed_at` with the current logical clock, and increments the filing's `version`. The filing date matters: if the `filing_effective_date` is before the current logical date at the moment of filing, the attempt is rejected as retroactive with `ERR_FILING_RETROACTIVE` (HTTP 422). Filing anything that is not in `DRAFT` status is rejected with `ERR_FILING_NOT_FILABLE` (HTTP 409).

A filed filing becomes `EFFECTIVE` automatically — evaluated lazily on read and eagerly by the clock sweep — once the current logical date reaches the `filing_effective_date` at 00:00:00Z; at that moment `effective_at` is stamped and the `version` increments. The effectiveness transition carries a supersession cascade: **any other** `EFFECTIVE` filing for the same pair of `territory_code` and `species` is immediately moved to `SUPERSEDED`, so at most one filing per territory-and-species pair is ever effective at a time. `SUPERSEDED` is terminal.

Filings may be listed with optional `territory_code`, `species`, and `status` filters, and retrieved individually; listing and retrieval are shared by `PlatformAdmin`, `RateFilingAdmin`, and `ClaimsAdjuster`.

### 3.2. Hospital Onboarding, Training, and the Suspension Cascade

A hospital enters the network when a `PlatformAdmin` registers it with its `legal_name`, its `territory_code`, the opaque `bank_account_ref` used for direct-pay disbursement, and the installed `checkout_software_version`. The hospital begins in `APPLIED` status with a `running_ledger_balance_cents` of zero.

Approval by a `PlatformAdmin` moves the hospital from `APPLIED` to `APPROVED`; this is the OCC-guarded operation described in §2.5, so the approval payload carries `expected_hospital_version`. Approving a hospital that is not in `APPLIED` status is rejected with `ERR_HOSPITAL_NOT_APPROVABLE` (HTTP 409). Approval alone does not enable claims: the hospital must also complete onboarding training. Training completion is performed by `HospitalStaff` **of that hospital only** — the `X-User-ID` must equal the hospital's `id`, otherwise the request fails authorization with `ERR_UNAUTHORIZED` — and transitions the hospital from `APPROVED` to `ACTIVE`, stamping `training_completed_at` with the current logical clock. Both transitions increment the hospital's `version`.

Suspension is the most consequential administrative act in the system. When a `PlatformAdmin` suspends an `ACTIVE` hospital, three levels of cascade fire:

1. Every claim at that hospital whose status is `SUBMITTED`, `PREEXISTING_REVIEW`, `ADJUDICATED`, or `REOPENED` is moved to `DENIED` with `denial_reason` set to `HOSPITAL_SUSPENDED`. Each such claim's line-level computed fields are zeroed and its claim totals recomputed accordingly.
2. Each claim thus denied releases its `PolicyCondition` mappings: the deductible contributions its lines had consumed are reversed, and each affected condition's `deductible_accumulated_cents` is recomputed.
3. The hospital's own `version` increments.

Reinstatement by a `PlatformAdmin` moves a `SUSPENDED` hospital back to `ACTIVE` and increments its `version`, but it deliberately does **not** reopen the claims the suspension denied — those claims remain `DENIED` and must find their remedy, if any, through the appeal process.

### 3.3. Policy Enrollment, Waiting Periods, and Premium Aging

A policy is enrolled by a `PetOwner` or a `PlatformAdmin` with the `owner_name`, `pet_name`, `species` (`DOG` or `CAT`), `breed`, `pet_date_of_birth`, the policy's `territory_code`, the `coverage_start` date, the `per_condition_deductible_cents` lifetime deductible that will apply to each condition, and the `reimbursement_rate` — a decimal strictly greater than 0 and at most 1, for example 0.90.

Enrollment is gated on rate availability: there must exist an `EFFECTIVE` filing for the policy's pair of `territory_code` and `species` whose `filing_effective_date` is on or before the `coverage_start`. When several qualify, the newest is chosen — the one with the latest `filing_effective_date`, breaking ties by the latest `effective_at` and then the latest `created_at`. If no such filing exists, enrollment is rejected with `ERR_RATE_NOT_FILED` (HTTP 422). The chosen filing becomes the policy's `applied_filing_id`; its `base_monthly_premium_cents` is locked into the policy's `filed_base_cents` as a historical record, and the initial `current_monthly_premium_cents` is computed from it.

A policy lives on **two parallel status dimensions**. The enrollment dimension runs `INJURY_WAITING` → `ILLNESS_WAITING` → `FULLY_ACTIVE`; the lifecycle dimension runs `ACTIVE` → `CANCELLED` or `LAPSED` (both terminal). At creation the policy is `INJURY_WAITING` and `ACTIVE`, its waiting windows are computed — `injury_waiting_end` at `coverage_start` 00:00:00Z plus the injury waiting day count `INJURY_WAITING_DAYS`, which is 5 days, and `illness_waiting_end` at `coverage_start` 00:00:00Z plus the illness waiting day count `ILLNESS_WAITING_DAYS`, which is 14 days — and its `next_birthday` is computed for the premium sweep. The `next_birthday` is the earliest DOB-anniversary date that falls on or after `coverage_start` — so a pet whose birthday falls exactly on `coverage_start` already counts as its next birthday (that anniversary), and the age band at enrollment and at recalculation likewise treats a pet as having reached a new whole year on its birthday itself. Enrollment returns 201.

The enrollment dimension advances only by the logical clock: once the current logical clock is at or past `injury_waiting_end`, the policy moves to `ILLNESS_WAITING`; once it is at or past `illness_waiting_end`, the policy moves to `FULLY_ACTIVE`. Each transition increments the policy's `version`, and each is evaluated lazily on any policy read as well as by the clock sweep.

The lifecycle dimension moves by explicit act. An owner cancels their own `ACTIVE` policy — the `X-User-ID` must equal the policy's `id`-bound owner identity, otherwise `ERR_UNAUTHORIZED` — moving it to `CANCELLED`. A `PlatformAdmin` marks an `ACTIVE` policy `LAPSED` for premium non-payment. Both transitions increment the `version`.

**Premium aging.** The monthly premium is recomputed whenever the pet crosses into a new age band, either because the clock sweep crosses the policy's `next_birthday` or because a `PlatformAdmin` forces recalculation. Recalculation requires the policy's `lifecycle_status` to be `ACTIVE` and the current logical date to be at or past `next_birthday`. The age band is the floor of the pet's age in whole years at the current logical date. The applied filing is re-selected as the newest `EFFECTIVE` filing for the policy's territory and species whose `filing_effective_date` is on or before the **current logical date** — note the contrast with enrollment, which selects relative to `coverage_start` — with the same tie-break (latest `effective_at`, then latest `created_at`). The multiplier is the filing's `age_band_multipliers` entry for the computed band if present; otherwise the multiplier of the greatest declared band at or below the computed band; otherwise 1.0 if no declared band is at or below it. The new `current_monthly_premium_cents` is the filing's `base_monthly_premium_cents` times that multiplier, rounded half-up to whole cents. The `filed_base_cents` captured at enrollment is never rewritten — it remains the historical record — while `current_monthly_premium_cents`, `applied_filing_id`, and `next_birthday` (advanced by one year) all update, and the policy's `version` increments.

Policies can be listed with `territory_code`, `species`, `lifecycle_status`, `enrollment_status`, and `applied_filing_id` filters.

### 3.4. Medical Records and Pre-Existing Condition Determination

Hospitals upload clinical history against a policy as `MedicalRecord` resources, each carrying the producing `hospital_id`, a `record_type` of `EXAM`, `LAB`, `IMAGING`, `PROCEDURE`, or `PRESCRIPTION`, the `recorded_at` timestamp of the clinical event (logical past dates are allowed — historical records are the norm), a `diagnosis_code` such as K21.9, and free-text `notes`. Upload returns 201 and is a `HospitalStaff` capability. A record's `appeal_id` is null at upload; it is set only when the record is later attached to an appeal.

These records feed the pre-existing condition determination. When a condition is first minted during claim adjudication (and again when an appeal re-reviews), the system examines every medical record of the policy whose `diagnosis_code` equals the condition code and whose `record_type` is one of `EXAM`, `PROCEDURE`, or `LAB`. The condition is pre-existing if **any** such record has a `recorded_at` strictly before `coverage_start` at 00:00:00Z. The boundary is sharp: a record dated exactly on the coverage start date — at or after that midnight — does **not** count as pre-existing. Records attached to an appeal participate in this determination once attached.

Medical records are reachable from several directions: per policy (optionally filtered by `condition_code`), per hospital, per appeal, individually by `recordId`, and through the global filtered list supporting `policy_id`, `hospital_id`, and `appeal_id` filters.

### 3.5. Claim Submission and Checkout Adjudication

At the counter, `HospitalStaff` submit a claim with the `policy_id`, the treating `hospital_id`, the `visit_date`, the `claim_type` (`INJURY` or `ILLNESS`), and the invoice `lines`. Each line carries a `description`, a positive integer `amount_cents` (a non-positive amount is `ERR_INVALID_REQUEST`), a `category` of `TREATMENT`, `EXAM_FEE`, `TAX`, or `OTHER_EXCLUDED`, and — mandatory exactly when the category is `TREATMENT` — a `condition_code` naming the condition the line treats. A treatment line submitted without its condition code is rejected with `ERR_CONDITION_CODE_REQUIRED` (HTTP 400). Submission creates the claim in `SUBMITTED` status with all totals zeroed until adjudication, mints the lines as `ClaimLine` resources numbered by `seq` from 1 upward in submission order, and returns 201. Two gates apply at submission: the hospital must be `ACTIVE` (else `ERR_HOSPITAL_NOT_ACTIVE`, HTTP 409) and the policy's `lifecycle_status` must be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`, HTTP 409).

Adjudication is the `ClaimsAdjuster`'s core act and is OCC-guarded: the request carries `expected_claim_version` and a stale snapshot is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). Adjudication is admissible only from `SUBMITTED` or `PREEXISTING_REVIEW`; from anywhere else it fails with `ERR_CLAIM_NOT_ADJUDICATABLE` (HTTP 409). The hospital-active and policy-active gates apply here exactly as at submission. The waiting-period gate follows: an `INJURY` claim requires the current logical clock to be at or past the policy's `injury_waiting_end`, and an `ILLNESS` claim requires it to be at or past `illness_waiting_end`; the boundary is inclusive — a claim adjudicated at exactly the waiting end passes — and a violation is `ERR_WAITING_PERIOD_ACTIVE` (HTTP 409). Per the priority order of §2.7, the temporal waiting-period check is evaluated before the pre-existing safety check, so a claim that violates both surfaces the waiting-period error first.

Successful adjudication runs two calculations back to back and then stamps `adjudicated_at`:

**Line categorization and eligibility** walks the lines in ascending `seq` order. For a `TREATMENT` line, the system finds the policy's `PolicyCondition` with the same `condition_code`; if none exists it is minted on the spot — its `condition_code` copied from this first accepted line and immutable thereafter, its `preexisting` flag computed by the medical-record rule of §3.4, its `deductible_target_cents` copied from the policy's `per_condition_deductible_cents` at first use, and its `deductible_accumulated_cents` starting at 0. If the condition — whether found or freshly minted — is pre-existing, the entire claim is rejected with `ERR_PREEXISTING_CONDITION` (HTTP 422). Otherwise the line's `eligible_amount_cents` is set to its full `amount_cents` and its `policy_condition_id` to the mapped condition. A line of any other category — `EXAM_FEE`, `TAX`, or `OTHER_EXCLUDED` — gets an `eligible_amount_cents` of 0 and a null `policy_condition_id`: exam fees and taxes are never covered.

**The per-condition deductible waterfall** then processes the eligible lines — again strictly in ascending `seq` order, which is unique per claim so no tie-break is needed. For each line, the condition's remaining deductible is its `deductible_target_cents` minus its `deductible_accumulated_cents` so far; the line's `deductible_applied_cents` is the smaller of that remaining amount and the line's `eligible_amount_cents`, and that consumption is added to the condition's `deductible_accumulated_cents` immediately, so later lines of the same condition within the same claim see the updated accumulation. The line's reimbursement base is its `eligible_amount_cents` minus its `deductible_applied_cents`, and its `reimbursement_cents` is that base multiplied by the policy's `reimbursement_rate`, **rounded half-up to whole cents at this per-line step**. A condition's `deductible_accumulated_cents` never exceeds its `deductible_target_cents`, by construction of the minimum. Claim totals then fall out: `eligible_cents` is the sum of the lines' `eligible_amount_cents`, `deductible_applied_cents` the sum of the lines' `deductible_applied_cents`, `reimbursement_cents` the sum of the per-line rounded `reimbursement_cents`, `total_invoice_cents` the sum of all lines' `amount_cents` (excluded lines included), and `member_responsibility_cents` the `total_invoice_cents` minus the `reimbursement_cents`. There is **no payout cap**: `reimbursement_cents` is unbounded by any annual or lifetime maximum. Adjudication moves the claim to `ADJUDICATED` and increments its `version`.

An adjuster may instead route a claim into pre-existing review: flagging moves `SUBMITTED` → `PREEXISTING_REVIEW`, and clearing moves `PREEXISTING_REVIEW` → `SUBMITTED`, each incrementing the `version`. This cycle exists so a review can bounce a claim back for re-adjudication without losing it. Separately, an adjuster may deny a claim outright from `SUBMITTED` or `PREEXISTING_REVIEW`, supplying a `denial_reason`, which moves it to `DENIED` and increments the `version`.

Claims can be listed with `policy_id`, `hospital_id`, `status`, `claim_type`, and `payment_id` filters; a claim's lines are listed in `seq` order; individual lines are retrievable by `lineId`; a global line list supports `claim_id` and `policy_condition_id` filters for reverse reachability; and conditions are likewise reachable per policy, individually by `conditionId`, and through the global condition list with `policy_id` and `condition_code` filters.

### 3.6. Direct Payment at Checkout, Idempotency, and Settlement

Payment is where the product promise lands: `HospitalStaff` of the treating hospital — `X-User-ID` must equal the claim's `hospital_id` — trigger checkout payment on an `ADJUDICATED` claim, supplying an `idempotency_key`. A claim in any other state is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 409). A claim whose `reimbursement_cents` is zero is still payable: a payment of 0 is created normally.

The idempotency rule is key-scoped per claim: if the supplied `idempotency_key` was already used for another `Payment` of this claim, the endpoint returns the existing payment and creates no new one. Otherwise a `Payment` of `kind` `DIRECT_PAY` is created with `amount_cents` equal to the claim's `reimbursement_cents`, linked through the claim's `payment_id`.

On success the payment is born with `status` `SETTLED` and `ledger_status` `POSTED`; the claim moves `ADJUDICATED` → `PAID`; each mapped condition's `lifetime_reimbursed_cents` is incremented by its lines' reimbursement amounts — again uncapped; and the hospital's `running_ledger_balance_cents` increases by the payment amount. Both the claim's and the hospital's `version` increment.

The payment rail can fail, and the system models this deterministically: a checkout-pay request carrying `simulate_outcome` of `FAILED` injects a rail failure. In that case the payment is created with `status` `FAILED`, `ledger_status` `PENDING_POST`, and its amount is **not** added to the hospital ledger; the claim moves `ADJUDICATED` → `PAYMENT_FAILED` and its `version` increments. A failed payment is not terminal: retrying checkout-pay on a `PAYMENT_FAILED` claim whose prior payment is `FAILED` marks the prior payment's `ledger_status` as `EXCLUDED`, creates a fresh payment (settled and posted on success), points the claim's `payment_id` at the new payment, and returns the claim to `ADJUDICATED` → `PAID`. This retry loop can cycle until success.

Settlement is a delayed system transition: once the current logical clock reaches the payment time plus the settlement delay of `SETTLE_DELAY_DAYS` days, which is 3 days, a `PAID` claim moves to `SETTLED`, its `version` incrementing. Like the waiting-period transitions this is evaluated lazily on claim read and eagerly by the clock sweep. `SETTLED` is the claim's only terminal state under normal flow — but see the appeal remedy below, which can reopen even a settled claim.

Payments are queryable per hospital (with `status`, `ledger_status`, and `reverses_payment_id` filters), per claim, individually by `paymentId`, and through the global list supporting `claim_id`, `hospital_id`, `status`, `ledger_status`, and `reverses_payment_id` filters.

### 3.7. Appeals, Record Requests, and the Overturn Cascade

A `PetOwner` may open a `ClaimAppeal` on a claim that is `DENIED` or `SETTLED` — an appeal on a claim in any other status is rejected with `ERR_APPEAL_NOT_OPENABLE` (HTTP 409) — supplying a `reason_code` of `PREEXISTING_DISPUTE`, `CONDITION_DEFINITION`, `COVERAGE_DENIAL`, or `LINE_CATEGORIZATION`. The appeal is created in `OPEN` status with `opened_by` recorded as `PET_OWNER`, and — critically for segregation of duties — the system records as `original_adjuster_id` the `X-User-ID` of the adjuster who last adjudicated or denied the underlying claim.

An adjuster may request medical records, moving the appeal `OPEN` → `RECORDS_REQUESTED` and setting `records_due_at` to the current logical clock plus the records window of `RECORDS_WINDOW_DAYS` days, which is 14 days. `HospitalStaff` then submit records for the appeal by supplying `medical_record_ids`; submission is valid only while the appeal is in `RECORDS_REQUESTED`, only while the current logical clock is at or before `records_due_at` — after the deadline the attempt fails with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 409) — and every referenced record must exist, belong to the claim's policy (a record that does not exist or belongs to another policy yields `ERR_RECORD_NOT_FOUND`, HTTP 404), and not already be attached to another appeal (else `ERR_RECORD_ALREADY_ATTACHED`, HTTP 409). Successful submission stamps each record's `appeal_id` with this appeal's `id` and moves the appeal to `UNDER_REVIEW`.

Resolution is the segregation-of-duties checkpoint. A `ClaimsAdjuster` resolves an appeal that is `OPEN` or `UNDER_REVIEW` — from any other status the attempt fails with `ERR_APPEAL_NOT_RESOLVABLE` (HTTP 409) — by supplying an `outcome` and a `resolution_note`. An `outcome` of `UPHELD` simply closes the appeal as `UPHELD`. An `outcome` of `OVERTURNED` additionally requires that the resolving adjuster's `X-User-ID` **differ** from the appeal's `original_adjuster_id`; the same adjuster resolving their own decision is rejected with `ERR_SELF_RESOLUTION_FORBIDDEN` (HTTP 403). Both resolution paths increment the appeal's `version`, and both `UPHELD` and `OVERTURNED` are terminal.

An overturn fires the deepest cascade in the system, three levels:

1. The underlying claim — whether `DENIED` or `SETTLED` — transitions to `REOPENED`.
2. The claim's original `DIRECT_PAY` payment, if one exists, is moved to `REVERSED` while its `ledger_status` stays `POSTED`, and a compensating `CLAWBACK` payment is created: negative `amount_cents`, `status` settled into the ledger, `ledger_status` `POSTED`, its `reverses_payment_id` pointing at the reversed payment. The hospital's `running_ledger_balance_cents` decreases by the clawed amount.
3. Every affected `PolicyCondition` has its `lifetime_reimbursed_cents` and `deductible_accumulated_cents` recomputed by replaying the remaining non-reversed claim lines.

The claim's and the hospital's `version` both increment through this cascade. A `REOPENED` claim sits back in the adjudicable flow — note that a subsequent hospital suspension treats `REOPENED` claims as open and denies them with `HOSPITAL_SUSPENDED`.

Appeals are listable per claim and through the global appeal list (with `claim_id` and `status` filters), retrievable individually, and their attached medical records are listable per appeal.

### 3.8. Ledger Integrity and Dual-Variant Reconciliation

The hospital ledger is maintained incrementally: `running_ledger_balance_cents` is the sum of `amount_cents` over the hospital's payments whose `ledger_status` is `POSTED`, minus clawed-back amounts from reversed payments, minus the clawback payments themselves (which carry negative amounts). Failed payments — `PENDING_POST` — and `EXCLUDED` payments never contribute.

A `PlatformAdmin` generates a `ReconciliationReport` for a hospital over a half-open window: `period_start` inclusive, `period_end` exclusive. The report computes two ledger variants that must agree when every reversal has been handled correctly:

- `expected_cents` — the **expected ledger** variant: the sum of `amount_cents` over the hospital's payments with `ledger_status` `POSTED` whose `created_at` falls inside the half-open window.
- `actual_cents` — the **actual ledger** variant: the hospital's `running_ledger_balance_cents` position for the identical window, reconstructed by replaying the same posted payments in ascending `created_at` order (timestamps are unique per mutation, so no tie-break is needed) and summing the signed amounts.

The `discrepancy_cents` is `expected_cents` minus `actual_cents`. The two variants agree only if every reversal created a matching negative clawback payment — this is precisely the property the report exists to audit. A generated report is born in `GENERATED` status (201), may be acknowledged by a `PlatformAdmin` (moving it to `ACKNOWLEDGED`), and may be disputed by `HospitalStaff` (moving it to `DISPUTED`). Reports are listed per hospital and globally (with `hospital_id` and `status` filters) and retrievable individually by `reportId`.

## 4. Endpoint Definitions

All endpoints are mounted under `/vetpay`. Resource creation endpoints return 201; action endpoints that modify an existing resource, and all reads, return 200. Errors carry the envelope and codes of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /vetpay/_clock/set_current_utc | Set the logical clock; fires waiting-period, filing-effectiveness, settlement, and premium sweeps | PlatformAdmin |
| POST | /vetpay/rate-filings | Create a TerritoryRateFiling in DRAFT | RateFilingAdmin |
| GET | /vetpay/rate-filings | List rate filings | PlatformAdmin, RateFilingAdmin, ClaimsAdjuster |
| GET | /vetpay/rate-filings/{filingId} | Get one filing | PlatformAdmin, RateFilingAdmin, ClaimsAdjuster |
| POST | /vetpay/rate-filings/{filingId}/file | File a DRAFT filing with the regulator | RateFilingAdmin |
| POST | /vetpay/hospitals | Register a hospital (status APPLIED) | PlatformAdmin |
| GET | /vetpay/hospitals | List hospitals | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/hospitals/{hospitalId} | Get one hospital (includes running ledger balance) | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| POST | /vetpay/hospitals/{hospitalId}/approve | Approve an APPLIED hospital (OCC on Hospital version) | PlatformAdmin |
| POST | /vetpay/hospitals/{hospitalId}/training-complete | Mark onboarding training complete (staff of this hospital only) | HospitalStaff |
| POST | /vetpay/hospitals/{hospitalId}/suspend | Suspend an ACTIVE hospital; denies open claims (cascade) | PlatformAdmin |
| POST | /vetpay/hospitals/{hospitalId}/reinstate | Reinstate a SUSPENDED hospital | PlatformAdmin |
| GET | /vetpay/hospitals/{hospitalId}/payments | List payments for a hospital | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| POST | /vetpay/hospitals/{hospitalId}/reconciliation-reports | Generate a reconciliation report for a period | PlatformAdmin |
| GET | /vetpay/hospitals/{hospitalId}/reconciliation-reports | List reconciliation reports for a hospital | PlatformAdmin, ClaimsAdjuster |
| GET | /vetpay/reconciliation-reports/{reportId} | Get one reconciliation report | PlatformAdmin, ClaimsAdjuster |
| POST | /vetpay/reconciliation-reports/{reportId}/acknowledge | Acknowledge a GENERATED report | PlatformAdmin |
| POST | /vetpay/reconciliation-reports/{reportId}/dispute | Dispute a GENERATED report | HospitalStaff |
| GET | /vetpay/reconciliation-reports | List reconciliation reports (filtered list form) | PlatformAdmin, ClaimsAdjuster |
| POST | /vetpay/policies | Enroll a policy (requires an EFFECTIVE filing for territory/species) | PetOwner, PlatformAdmin |
| GET | /vetpay/policies | List policies | PlatformAdmin, ClaimsAdjuster, PetOwner |
| GET | /vetpay/policies/{policyId} | Get one policy (lazy waiting-period evaluation) | PlatformAdmin, ClaimsAdjuster, PetOwner, HospitalStaff |
| POST | /vetpay/policies/{policyId}/cancel | Owner cancels an ACTIVE policy | PetOwner |
| POST | /vetpay/policies/{policyId}/mark-lapsed | Mark an ACTIVE policy lapsed for non-payment | PlatformAdmin |
| POST | /vetpay/policies/{policyId}/recalculate-premium | Force age-band premium recalculation | PlatformAdmin |
| GET | /vetpay/policies/{policyId}/conditions | List PolicyConditions of a policy | PlatformAdmin, ClaimsAdjuster, PetOwner |
| GET | /vetpay/policy-conditions/{conditionId} | Get one PolicyCondition | PlatformAdmin, ClaimsAdjuster, PetOwner |
| GET | /vetpay/policy-conditions | List PolicyConditions (filtered list form) | PlatformAdmin, ClaimsAdjuster, PetOwner |
| GET | /vetpay/claim-lines/{lineId} | Get one ClaimLine | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| GET | /vetpay/claim-lines | List ClaimLines (filtered list form) | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| GET | /vetpay/payments/{paymentId} | Get one Payment | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/payments | List payments (filtered list form) | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/claims/{claimId}/payments | List payments for a claim | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| GET | /vetpay/policies/{policyId}/medical-records | List medical records of a policy | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| POST | /vetpay/policies/{policyId}/medical-records | Upload a medical record | HospitalStaff |
| GET | /vetpay/medical-records/{recordId} | Get one medical record | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/medical-records | List medical records (filtered list form) | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/hospitals/{hospitalId}/medical-records | List medical records produced by a hospital | PlatformAdmin, ClaimsAdjuster, HospitalStaff |
| GET | /vetpay/appeals/{appealId}/medical-records | List medical records attached to an appeal | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| POST | /vetpay/claims | Submit a claim at checkout with invoice lines | HospitalStaff |
| GET | /vetpay/claims | List claims | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| GET | /vetpay/claims/{claimId} | Get one claim (lazy PAID-to-SETTLED evaluation) | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| GET | /vetpay/claims/{claimId}/lines | List claim lines | PlatformAdmin, ClaimsAdjuster, HospitalStaff, PetOwner |
| POST | /vetpay/claims/{claimId}/flag-preexisting-review | Move a SUBMITTED claim into PREEXISTING_REVIEW | ClaimsAdjuster |
| POST | /vetpay/claims/{claimId}/clear-preexisting-review | Return a PREEXISTING_REVIEW claim to SUBMITTED | ClaimsAdjuster |
| POST | /vetpay/claims/{claimId}/adjudicate | Run checkout adjudication (OCC on Claim version) | ClaimsAdjuster |
| POST | /vetpay/claims/{claimId}/deny | Deny a SUBMITTED/PREEXISTING_REVIEW claim | ClaimsAdjuster |
| POST | /vetpay/claims/{claimId}/checkout-pay | Pay the hospital directly at checkout; idempotent; supports failure injection | HospitalStaff |
| POST | /vetpay/claims/{claimId}/appeals | Open an appeal on a DENIED or SETTLED claim | PetOwner |
| GET | /vetpay/claims/{claimId}/appeals | List appeals for a claim | PlatformAdmin, ClaimsAdjuster, PetOwner, HospitalStaff |
| GET | /vetpay/appeals | List appeals (filtered list form) | PlatformAdmin, ClaimsAdjuster, PetOwner, HospitalStaff |
| GET | /vetpay/appeals/{appealId} | Get one appeal | PlatformAdmin, ClaimsAdjuster, PetOwner, HospitalStaff |
| POST | /vetpay/appeals/{appealId}/request-records | Request medical records; sets records due time | ClaimsAdjuster |
| POST | /vetpay/appeals/{appealId}/submit-records | Hospital submits records for the appeal | HospitalStaff |
| POST | /vetpay/appeals/{appealId}/resolve | Resolve an appeal UPHELD or OVERTURNED (segregation of duties enforced) | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_HOSPITAL_NOT_FOUND | 404 |
| ERR_POLICY_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_RECORD_NOT_FOUND | 404 |
| ERR_HOSPITAL_NOT_APPROVABLE | 409 |
| ERR_HOSPITAL_NOT_ACTIVE | 409 |
| ERR_POLICY_NOT_ACTIVE | 409 |
| ERR_RATE_NOT_FILED | 422 |
| ERR_FILING_RETROACTIVE | 422 |
| ERR_FILING_NOT_FILABLE | 409 |
| ERR_WAITING_PERIOD_ACTIVE | 409 |
| ERR_PREEXISTING_CONDITION | 422 |
| ERR_CLAIM_NOT_ADJUDICATABLE | 409 |
| ERR_CLAIM_NOT_PAYABLE | 409 |
| ERR_APPEAL_NOT_OPENABLE | 409 |
| ERR_APPEAL_NOT_RESOLVABLE | 409 |
| ERR_APPEAL_WINDOW_EXPIRED | 409 |
| ERR_RECORD_ALREADY_ATTACHED | 409 |
| ERR_SELF_RESOLUTION_FORBIDDEN | 403 |
| ERR_STALE_CLAIM_VERSION | 412 |
| ERR_STALE_HOSPITAL_VERSION | 412 |
| ERR_CONDITION_CODE_REQUIRED | 400 |
