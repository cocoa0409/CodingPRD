# Therapist Network Credentialing Payouts API — Product Requirements Document

## 1. Introduction

A behavioral-health network sits between three parties that never coordinate directly: the licensed therapist who delivers care, the insurance payer who reimburses it, and the patient who consumes it. Every one of those relationships carries a rule of its own — a license that must be verified before it counts, a malpractice policy that must be live before a session can be billed, a payer enrollment whose effective window silently decides whether a given Tuesday session is payable at all, and a rate schedule keyed simultaneously by payer, license type, geography and service code. This document specifies the API surface that models those relationships and the financial machinery that flows out of them.

The network's central promise to its clinicians is predictability of cash. Clinicians are paid on a fixed cadence that is deliberately decoupled from when, or whether, payers actually remit: a session that has been delivered and documented earns its place in a payout line even while the claim behind it is still in flight, and a later denial arrives as a signed adjustment against a line that has already been paid rather than as a retroactive erasure of the work. Holding that promise requires the network to maintain a credentialing ledger, a benefit-verification ledger, a claim ledger and a payout ledger that stay consistent with one another through suspension, offboarding, payer termination and license expiry.

The system is operated by a network back office. Six acting capacities are defined — `OpsAdmin`, `ComplianceOfficer`, `Clinician`, `Patient`, `PayrollService` and `Anonymous` — and the separation between credentialing review and fiscal authority is deliberate and enforced in both directions. This specification is written for the engineer who must build it: it fixes the response envelope, the pagination mechanics, the concurrency contract, the state machines, the arithmetic and the error identities, and it expects the result to behave identically for identical inputs.

## 2. Global Specifications & System-Wide Principles

This section holds the rules that apply regardless of which workflow a caller is exercising: identity and authorization, the response envelope, pagination, the credentialing gate that governs every billable operation, monetary precision, resource identity conventions, optimistic concurrency, path-scoped lookups, the ordering of validation failures, and the logical clock the whole system runs on.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the capacity in which that user is acting. A request that omits either header, supplies an empty `X-User-ID`, or names a role outside the declared set is rejected with `ERR_UNAUTHENTICATED`. A request whose declared role is not permitted on the addressed endpoint is rejected with `ERR_UNAUTHORIZED`.

The system recognises exactly six roles: `OpsAdmin`, `ComplianceOfficer`, `Clinician`, `Patient`, `PayrollService` and `Anonymous`. The interpretation of `X-User-ID` depends on the role:

- `OpsAdmin`, `ComplianceOfficer`, `PayrollService` and `Anonymous` are opaque identities. When `X-User-Role` is one of these, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record it — for example as `created_by_user_id` on `PayoutBatch`, as `verified_by_user_id` on `License`, or as `signer_clinician_id` on `SessionNote` — but it never compares it to any entity's `id`.
- When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician`; ownership checks on any resource that references a clinician compare the resource's clinician foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `PatientClient`; ownership checks on any resource that references a patient compare the resource's patient foreign-key field to `X-User-ID`.

For any entity-backed role, a request whose `X-User-ID` does not resolve to an existing instance of that role's entity is rejected with `ERR_UNAUTHORIZED`.

Authority is split as follows. `OpsAdmin` is the network operator: it onboards clinicians, records licenses and malpractice policies, publishes payers and rate schedules, opens and administers payer enrollments, registers patients, records benefit verifications, requests sessions, submits and adjudicates claims on clinicians' behalf, administers payout batches, opens and reassigns continuity plans, drives the logical clock and injects synthetic claim outcomes. `OpsAdmin` may not verify a license. `ComplianceOfficer` is the credentialing reviewer and may only advance a clinician into credentialing and verify, re-verify or reset a license; it is excluded from every fiscal operation so that the reviewer and the payer of record are never the same role. A `Clinician` acts on their own schedule and documentation: creating and signing session notes and accepting or declining a continuity plan are theirs alone, while scheduling, completing, cancelling and rescheduling sessions are shared with `OpsAdmin`. `Patient` holds read-only access to their own sessions, cost-share quotes and clinician records. `PayrollService` is the downstream disbursement integration: it may execute the disbursement run on a payout batch and read batches and lines, but it cannot open, lock, reconcile or supersede a batch. `Anonymous` may reach only endpoints that exist to prove header handling. Where a role is not listed as authorised for an endpoint, the attempt fails with `ERR_UNAUTHORIZED`.

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

All list-returning endpoints accept two query parameters. `limit` caps the number of items returned; if it is omitted it defaults to 10, must be at least 1 and must not exceed 100. `offset` names how many items to skip and defaults to 0. Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Unless a specific endpoint states otherwise, list results are sorted by creation timestamp in ascending order.

### 2.4. The Credentialing Gate: Billing Posture

The single most consequential derived value in the system is a clinician's `billing_posture`, which is one of `BILLABLE`, `GATED` or `FROZEN`. It is never supplied by a client; it is derived from the clinician's child rows and from `Clinician.status`, and it is consulted by every billable session operation, by claim submission and resubmission, by session completion, and by continuity-plan acceptance.

The derivation is a fixed precedence: `FROZEN` overrides `GATED`, and `GATED` overrides `BILLABLE`. The evaluation walks the three tests in that order and stops at the first that matches. A clinician reads `FROZEN` when `status` is `SUSPENDED` or `OFFBOARDED`, or when `enrolled_payer_count` is 0. Failing that, the clinician reads `GATED` when no `License` row for that clinician reads `verification_status` of `VERIFIED`, or when no `MalpracticePolicy` row for that clinician reads `policy_status` of `ACTIVE`. Otherwise the clinician reads `BILLABLE`.

Only `PayerEnrollment` rows in `EFFECTIVE` status count toward `enrolled_payer_count`; `PENDING`, `SUSPENDED` and `TERMINATED` rows do not. A clinician with no `EFFECTIVE` enrollment therefore has an enrolled payer count of zero and is `FROZEN` regardless of licensure, which means the minimum viable billable clinician has at least one `EFFECTIVE` enrollment, at least one license reading `VERIFIED`, and at least one malpractice policy reading `ACTIVE`. The derivation re-runs on every write to a license, a malpractice policy, a payer enrollment or the clinician itself, and it re-runs when the logical clock advances far enough to expire a credential.

### 2.5. Monetary Precision and Integer Cents

Every monetary quantity in this system — rates, coverage limits, deductibles, coinsurance results, allowed amounts, patient responsibility, payer remittances, gross, adjustment, net and balance figures — is an integer number of cents. There are no fractional-cent values anywhere in a request or a response.

Three rounding behaviours appear and must be applied exactly where stated. Multiplying by the payer-allowed ratio or by the patient's coinsurance rate rounds half up to the nearest whole cent. The new-clinician and geography differentials in rate resolution, and the payer-paid clamp, round toward negative infinity. Deriving `open_slot_count` from availability blocks uses whole-minute arithmetic and a ceiling: a partial hour of availability left over is not rounded away. No step is re-rounded after it has been applied, and no sum is re-rounded at all — per-session integers are summed as integers, per-line values are stored, and totals are the sums of the stored line values.

### 2.6. Common Resource Properties

Every entity in this system — `Clinician`, `License`, `MalpracticePolicy`, `Payer`, `PayerRate`, `PayerEnrollment`, `PatientClient`, `BenefitVerification`, `Session`, `SessionNote`, `Claim`, `PayoutBatch`, `PayoutLine` and `ContinuityPlan` — carries a common set of system-managed fields:

- `id`, a server-minted UUID string with no type prefix and no entity name embedded in it.
- `created_at`, an ISO 8601 UTC timestamp with three fractional digits.
- `updated_at`, an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version`, an integer that starts at 1 and increments by 1 on every mutation.

A derived field is a mutation: re-deriving `open_slot_count`, `billing_posture`, `benefit_status` or a provider's aggregate counters refreshes `updated_at` and increments `version`. Every state transition described in this document increments the `version` of the row it lands on. All fourteen entities carry the full set of common fields; none omits `updated_at` and none omits `version`.

### 2.7. Optimistic Concurrency Control

Three write operations require the client to present its last observed version of the resource that owns the write, and reject the request rather than overwrite a change the client has not seen. In each case the version is supplied as a required, non-optional body field; omitting it is a malformed request (`ERR_INVALID_REQUEST`) rather than an unchecked write.

- Superseding an open payout batch requires `expected_open_batch_version`, carrying the client's last observed `version` of that `PayoutBatch`. If the batch's current `version` differs from the supplied value the request is rejected with `ERR_STALE_VERSION` and HTTP status 412.
- Adding a session note requires `expected_session_version`, carrying the client's last observed `version` of the `Session` the note is being attached to. If the session's current `version` differs from the supplied value the request is rejected with `ERR_STALE_VERSION` and HTTP status 412.
- Reassigning a continuity plan's successor clinician requires `expected_plan_version`, carrying the client's last observed `version` of that `ContinuityPlan`. If the plan's current `version` differs from the supplied value the request is rejected with `ERR_STALE_VERSION` and HTTP status 412.

No other endpoint enforces an optimistic-concurrency rejection. In particular, updating a clinician's own profile fields, scheduling, completing, cancelling and rescheduling a session, adjudicating and resubmitting a claim, activating, suspending, reinstating and terminating an enrollment, and adjusting, cancelling and completing a continuity plan all proceed without an optimistic-concurrency check, and a version-shaped field supplied to one of them — such as the `expected_clinician_version` that the clinician update accepts — does not by itself cause a rejection.

### 2.8. Nested Resource Retrieval and Existence Precedence

Requests that address a resource through a nested path validate the identifiers left to right. The system confirms the existence of the leftmost resource first, then the next, and only then any body-supplied identifiers, which are themselves checked in the declared input order of the endpoint. The first identifier that does not resolve ends the request: a note addressed under a session that does not exist fails as a missing session (`ERR_SESSION_NOT_FOUND`) before the system ever looks for the note, and a license addressed under a clinician that does not exist fails as a missing clinician (`ERR_CLINICIAN_NOT_FOUND`) before the license is considered. The not-found identities are `ERR_CLINICIAN_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_NOTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND` and `ERR_CONTINUITY_PLAN_NOT_FOUND`, all reported with HTTP status 404.

### 2.9. Validation Sequencing and Error Precedence

When a request can fail for several reasons, the reasons are evaluated in a fixed order and the first failure is the one reported. This ordering is normative, not incidental: a caller who has both a stale credential and a bad payload must receive the credential error, and a test that exercises a valid payload against a stale credential must not be satisfied by a payload error.

The sequence is: authentication first, so a missing header surfaces as `ERR_UNAUTHENTICATED` rather than being masked by any later check. Authorisation second, so a role that may not touch the endpoint surfaces as `ERR_UNAUTHORIZED` before the endpoint's own rules are consulted. Existence third, in the left-to-right and path-before-body order given in §2.8. Declared-state fourth: a resource that is not in a state from which the requested transition is declared is rejected with `ERR_INVALID_STATE`, and a resource already sitting in a terminal state that admits no further transition is rejected with `ERR_ALREADY_TERMINAL`. The clinical safety gate is fifth: the session's clinician must read `billing_posture` of `BILLABLE` at the moment of completion, claim submission or claim resubmission, and a `GATED` or `FROZEN` posture blocks the operation with `ERR_CLINICIAN_NOT_BILLABLE`. Referential billing eligibility is sixth: the payer must be `ACTIVE` for the session's service date, the session's `cpt_code` must appear in the payer's `allowed_cpt_codes`, and an enrollment in `EFFECTIVE` status must cover the service date for that clinician-and-payer pair, failing which the request is rejected with `ERR_SERVICE_NOT_ENROLLED`. Temporal conflicts are seventh, and within that group the clinician's availability is checked first, then the patient's own bookings, then the length of an enrollment window; the first conflict encountered produces its own identity, so a slot that is both unavailable to the clinician and double-booked for the patient reports the clinician conflict (`ERR_CLINICIAN_SLOT_CONFLICT`) and never the patient conflict (`ERR_PATIENT_DOUBLE_BOOKED`), and an enrollment whose window is zero-length reports `ERR_ENROLLMENT_WINDOW_INVALID`. Fiscal gates come last: batch lockability, batch payability, write-off eligibility and caseload acceptance capacity are evaluated after all of the above and produce `ERR_BATCH_NOT_LOCKABLE`, `ERR_BATCH_NOT_PAYABLE`, `ERR_WRITE_OFF_NOT_ALLOWED` and `ERR_CASELOAD_FULL` respectively.

A request that is structurally malformed — a required body field absent, a value outside its declared enumeration, a number outside its permitted range, or a field the endpoint does not recognise — is rejected with `ERR_INVALID_REQUEST` at HTTP status 400. Payers whose status is `SUSPENDED_AT_PAYER` or `TERMINATED` block any operation that requires an `ACTIVE` payer, and that rejection carries `ERR_PAYER_SUSPENDED`.

### 2.10. The Logical Clock

The system's notion of "now" is a settable logical clock. Before any call it reads `2026-09-01T00:00:00Z`, and it never falls back to real wall-clock time, so every temporal rule in this document is evaluated against the clock the operator has set rather than against the host's system time. The clock is advanced by an `OpsAdmin` supplying the target instant as `current_utc`, and the response reports the resulting `current_utc` value. Advancing the clock reconciles the world: it re-derives license verification status, malpractice policy status and patient benefit status on their next read, fires any continuity-plan escalations that have come due, and re-evaluates clinician billing posture.

## 3. Business Logic & Workflows

### 3.1. Clinician Onboarding, Licensure and Malpractice Coverage

A therapist joins the network when an `OpsAdmin` onboards them with a `full_name`, a `license_type` drawn from `LCSW`, `LMFT`, `LPC`, `LMHC`, `PSY_D` or `PHD`, a `primary_state` two-letter geography anchor, a set of `specialty_tags`, a `weekly_caseload_target`, and optional `availability_blocks`. The `weekly_caseload_target` must be at least 1. Each availability block is written against the UTC week as a `weekday` numbered 0 through 6 with 0 meaning Sunday through 6 meaning Saturday, a `start_minute` and an `end_minute`; half-open in the same way an enrollment window is, the start bounds the interval inclusively and the end bounds it exclusively, `start_minute` runs 0 to 1439 and `end_minute` runs 1 to 1440. Onboarding stamps `onboarded_at` from the logical clock and sets the clinician's `status` to `ONBOARDING`, its `billing_posture` to `GATED`, `active_patient_count` to 0, and an `open_slot_count` derived from the availability blocks that were supplied — full minutes divided by 60, rounding up, so an availability of 90 minutes counts as 2 whole hours.

Two child records make the clinician credentialable. A license is recorded with `license_number`, its own `license_type`, the `issuing_state`, the `expires_on` instant and a `telehealth_eligible` flag; it starts at `verification_status` of `UNVERIFIED` with `verification_attempts` of 0, `verified_at` null and `verified_by_user_id` null. A malpractice policy is recorded with the `carrier_name`, a `coverage_cents` per-occurrence limit, `effective_on`, `expires_on` and a `tail_coverage` flag; its `policy_status` is never stored as a fixed value but derived on every read from the logical clock against those two instants — `PENDING` before `effective_on`, `ACTIVE` from `effective_on` up to but not including `expires_on`, and `LAPSED` from `expires_on` onward. The boundary is inclusive at the start and at the end: a policy with `expires_on` exactly equal to the logical clock reads `LAPSED`, not `ACTIVE`. `tail_coverage` is a reporting-endorsement flag; it does not keep a clinician billable, and it suppresses the posture downgrade only for sessions that have already reached `COMPLETED`.

Once both a license and a malpractice policy are on file, a `ComplianceOfficer` may submit the clinician for credentialing, moving `status` from `ONBOARDING` to `CREDENTIALING`. The same transition is declared again from `ONBOARDING` or from `CREDENTIALING` when the same officer re-verifies a license, so credentialing review is repeatable without re-opening onboarding. License verification itself is a `ComplianceOfficer` act with two outcomes decided by one comparison. If the license's `expires_on` is strictly after the logical clock, the license becomes `VERIFIED` and the call records `verified_at` from the clock and `verified_by_user_id` from the acting header. If `expires_on` is at or before the logical clock, the attempt fails and the license becomes `FAILED` instead. Either way `verification_attempts` grows by 1. A `FAILED` license can be returned to `UNVERIFIED` by a reset, which leaves `verification_attempts` untouched and clears `verified_at` to null, so the same license can be attempted again after the underlying data is corrected. An `EXPIRED` license is revived by re-verification, which accepts a `replacement_expires_on` and requires that the replacement expiry be strictly after the logical clock; the stored `expires_on` is replaced, the license returns to `VERIFIED`, `verified_at` is stamped from the clock, `verified_by_user_id` is recorded, and `verification_attempts` grows by 1.

The effective status of a license is derived, not frozen, and four cases are checked in order with the first match winning. A license reads `FAILED` when the most recent verify attempt was made against an `expires_on` at or before the clock and no reset has happened since. Failing that, it reads `EXPIRED` once the logical clock reaches `expires_on`. Failing that, it reads `VERIFIED` when a successful verification exists and the clock is still strictly before `expires_on`. Otherwise it reads `UNVERIFIED`. A license whose expiry coincides exactly with the clock instant reads `EXPIRED`, never `VERIFIED`. Whenever a license expires this way the owning clinician's posture is re-derived — dropping to `GATED` if no other license still reads `VERIFIED` — and every enrollment of that clinician with a payer that requires that license type is re-evaluated.

The clinician becomes `ACTIVE` and begins accepting patients the moment `billing_posture` reaches `BILLABLE`, which is to say once one license reads `VERIFIED`, one malpractice policy reads `ACTIVE` and `enrolled_payer_count` is at least 1. From `ACTIVE`, an `OpsAdmin` can suspend the clinician, which sets `status` to `SUSPENDED`, forces `billing_posture` to `FROZEN`, and cancels every session of that clinician still sitting in `REQUESTED` or `SCHEDULED`. From `SUSPENDED`, reinstating sets `status` back to `ACTIVE` — permitted only when at least one license reads `VERIFIED` and `enrolled_payer_count` is at least 1 — and re-derives posture back to `BILLABLE` when a malpractice policy reads `ACTIVE`, or to `GATED` otherwise. A clinician whose posture reaches `FROZEN` for any reason has every open session cancelled and each cancelled session's `slot_consumed` set back to false; sessions already `COMPLETED` keep their `billing_state` untouched, though any later claim submission for them is refused because the clinician is no longer billable.

### 3.2. Payer Contracts, Rate Schedules and Enrollment Windows

A payer is created with a `payer_name`, a `payer_code` unique across all payers, a `delegated_credentialing` flag recording whether the payer delegates group credentialing to the network, a `min_malpractice_coverage_cents` floor, a `timely_filing_days` window that must be at least 1, a `credentialing_sla_days` expectation, and the `allowed_cpt_codes` the payer reimburses. A new payer starts at `status` of `ACTIVE`.

A rate schedule is published per payer as `PayerRate` rows. Each row names the payer, a `rate_set_version`, a `license_type`, a `geography` two-letter state, a `cpt_code`, a `rate_cents` figure, and an `effective_from` and optional `effective_to`. Two rows may not share the same combination of payer, rate-set version, license type, geography, CPT code and `effective_from`; a duplicate is rejected with `ERR_DUPLICATE_RATE` at HTTP 409. Publishing a rate never repriced the past: a session that has already been scheduled or completed keeps the rate that resolved against its own `scheduled_start`, and a rate revision walks forward only. The validity window is half-open — `effective_from` inclusive, `effective_to` exclusive — and an open-ended row has `effective_to` null.

Bringing a clinician onto a payer begins with an enrollment carrying the `clinician_id`, the `payer_id`, a `delegated` flag, an `effective_from` and an optional `effective_to`, starting at `status` of `PENDING` with `rate_set_version_pinned` null. A zero-length or inverted window is refused at 422 with `ERR_ENROLLMENT_WINDOW_INVALID`: the window is half-open, so a window that closes exactly where it opens is invalid rather than empty, and `effective_to` must be strictly after `effective_from` whenever it is supplied at all. The derived `effective_window_days` is the whole number of days between the two instants while `effective_to` is set, and null while the enrollment is open-ended.

Activation is the point at which all the credentialing work has to hold simultaneously. An `OpsAdmin` may move an enrollment from `PENDING` to `EFFECTIVE` only when its `effective_from` is at or before the logical clock, the owning clinician holds at least one license reading `VERIFIED` whose `issuing_state` equals the clinician's `primary_state`, the payer's `status` is `ACTIVE`, and the clinician holds at least one malpractice policy whose `coverage_cents` is at least the payer's `min_malpractice_coverage_cents` and whose `policy_status` reads `ACTIVE`. A payer whose status is `SUSPENDED_AT_PAYER` or `TERMINATED` blocks activation with `ERR_PAYER_SUSPENDED`. On activation the system pins `rate_set_version_pinned` to the highest `rate_set_version` among the payer's rate rows for the clinician's license type and primary state whose window covers `effective_from`, or leaves it null when no such row is effective at that instant, derives `effective_window_days`, and recomputes the clinician's `enrolled_payer_count` and posture. An enrollment may instead be rejected outright from `PENDING`, landing terminally in `REJECTED` with no change to the clinician's aggregates, and it may be terminated from any of `PENDING`, `EFFECTIVE` or `SUSPENDED`, landing terminally in `TERMINATED`.

The remaining enrollment transitions move it in and out of service. An `EFFECTIVE` enrollment may be suspended — either explicitly, or automatically when its payer becomes `SUSPENDED_AT_PAYER` or `TERMINATED` — which decrements the clinician's `enrolled_payer_count` and re-derives posture, while leaving sessions already `COMPLETED` untouched. A suspended enrollment may be reinstated back to `EFFECTIVE`, permitted only while the payer reads `ACTIVE`, `effective_from` is at or before the clock, and `effective_to` is either null or strictly after the clock; reinstating increments `enrolled_payer_count` and re-derives posture.

Two consequences of these rules deserve separate emphasis, because they are the ways enrollment bookkeeping propagates. When `enrolled_payer_count` drops to zero — whether because the last enrollment was terminated, suspended, or lost to a payer suspension — the clinician's posture becomes `FROZEN` under §2.4 even if every license and policy is in order, and the frozen-posture cascade cancels the clinician's open sessions. And because only `EFFECTIVE` enrollments count, an enrollment that is merely `PENDING` confers no billability at all: the credentialing decision, not the credentialing application, is what makes a clinician able to work.

### 3.3. Patient Benefits and the Cost-Share Estimate

A patient is registered with a `full_name`, a `member_id` unique within their payer, the `payer_id` that insures them, a `plan_code`, a `state_code` residence geography, a `deductible_cents`, a `coinsurance_rate` expressed as a fraction between 0.0 and 1.0 inclusive, and an `oop_max_cents` annual out-of-pocket maximum. Registration sets `benefit_status` to `UNVERIFIED`, `oop_met_cents` to 0, `visit_count_year` to 0, `matched_clinician_id` to null and `swap_requested` to false.

A patient is verified when an `OpsAdmin` records a benefit verification snapshot carrying `deductible_remaining_cents`, a `coinsurance_rate` confirmed by the payer, a `copay_cents` and `oop_remaining_cents`. The snapshot inherits the patient's `payer_id` at verification time, is stamped `verified_at` from the logical clock, and starts at `status` of `VERIFIED`. A patient's `benefit_status` is derived from the newest snapshot: `UNVERIFIED` when none exists, `VERIFIED` while the newest snapshot reads `VERIFIED`, and `STALE` once that snapshot ages out. A patient whose `benefit_status` is not `VERIFIED` cannot have a session scheduled; the attempt is refused with `ERR_BENEFIT_UNVERIFIED`.

Each verification snapshot also carries a `quoted_cost_share_cents`, a provisional per-session estimate computed from the snapshot itself. The estimator shares one body across both of its variants: it takes the allowed amount `S` for the session — zero when no rate row resolved — sets `d` to the smaller of `S` and the remaining deductible floor-ed at zero, subtracts that from `S` to obtain the after-deductible remainder, multiplies the remainder by the coinsurance rate and rounds half up to whole cents, adds the deductible portion, the rounded coinsurance and the copay together, applies a copay offset of 500 cents only when the variant carries the offset and only when the coinsurance component is at least 500 cents, and finally clamps the result between zero and the out-of-pocket room by taking the larger of zero and the smaller of the pre-clamp figure and the room. The copay offset is applied at most once per session, is never applied when the coinsurance component is below 500 cents, and rounding toward negative infinity appears only in that final clamp.

The two variants diverge in which deductible and out-of-pocket bases they read, and in whether the offset applies at all. The provisional quote used at booking — and recomputed whenever a cancelled session is moved to a new interval — reads all four of its parameters from the snapshot in force at that moment: the remaining deductible, the out-of-pocket room, the coinsurance rate and the copay all come from that same `BenefitVerification` row, and this variant always carries the copay offset. The final adjudicated variant applies at adjudication and reads its bases from live accumulators instead. Its remaining deductible is the patient's `deductible_cents` reduced by the sum of `patient_resp_cents` across that patient's claims in `PAID` status during the current plan year, taken in ascending `submitted_on` order and floored at zero; its out-of-pocket room is the patient's `oop_max_cents` less the live `oop_met_cents`, floored at zero. Its coinsurance rate and copay come from the newest verified snapshot, and this variant never carries the copay offset — the 500-cent step is skipped entirely. Three independent differences therefore separate the two figures: the deductible basis, the out-of-pocket-room basis, and the presence or absence of the offset. A patient with no snapshot reading `VERIFIED` cannot reach the estimator at all, because both booking and adjudication gate on exactly that.

### 3.4. Scheduling, Delivery and Clinical Documentation

A session is requested by an `OpsAdmin` with a `clinician_id`, a `patient_id`, a `scheduled_start`, a `scheduled_end`, a `cpt_code` and a `modality` of `VIDEO`, `PHONE` or `IN_PERSON`. It starts at `status` of `REQUESTED` with `billing_state` of `UNBILLED`, `slot_consumed` false and `quoted_cost_share_cents` null. Requesting does not commit resources; scheduling does.

Scheduling a requested session is open to the treating `Clinician` or an `OpsAdmin`, and four conditions must hold at once. The clinician's `billing_posture` must be `BILLABLE` or `GATED`; a `FROZEN` clinician cannot have sessions scheduled. The patient's `benefit_status` must read `VERIFIED` at the booked instant. The clinician must have a free availability block covering the requested interval. And neither the clinician nor the patient may hold an overlapping non-terminal session, where the clinician's own sessions additionally observe a 15-minute buffer — a session beginning exactly 15 minutes after another ends is accepted, while one beginning exactly 14 minutes after is rejected with `ERR_CLINICIAN_SLOT_CONFLICT`. Overlap on the patient alone is reported as `ERR_PATIENT_DOUBLE_BOOKED`. On success `slot_consumed` becomes true, `quoted_cost_share_cents` is filled from the patient's newest verified snapshot under the provisional variant described in §3.3, and the clinician's `open_slot_count` and the patient's `visit_count_year` are re-derived. When a requested session is booked onto an interval that collides with an existing non-terminal session for the same patient at the same `scheduled_start`, the newcomer is the one that loses: the earlier request is transitioned to `CANCELLED` without a client call.

Delivery is recorded by the treating `Clinician` or an `OpsAdmin` marking a scheduled session delivered, which is permitted only when the patient is attached, at least one note on the session is `SIGNED`, the scheduled start is not later than the logical clock, and the owning clinician is not `OFFBOARDED`. The note that authorises delivery must be the *newest* note on the session: if an older note is signed but a newer row is still `DRAFT`, the delivery is refused with `ERR_NOTE_SUPERSEDED` rather than being treated as undocumented. Every note on the session, not merely the newest, must have a `duration_minutes` equal to the session's scheduled length in minutes; a mismatch is `ERR_DURATION_MISMATCH`, and a session with no signed note at all is `ERR_DOCUMENTATION_MISSING`. Completion sets `slot_consumed` back to false, re-derives the clinician's `open_slot_count` and increments the patient's `visit_count_year`, and it makes the session claim-eligible without creating a claim by itself. It also feeds the continuity machinery of §3.7: when the owning clinician's `status` is `OFFBOARDING` or `OFFBOARDED` at the moment of completion, the pending continuity plan for that clinician-and-patient pair escalates.

A completed session may be returned to `SCHEDULED` by an `OpsAdmin` so that its documentation can be corrected, but only while its `billing_state` is still `UNBILLED` and no claim exists for it; the reopen re-occupies the slot and re-derives both counters. Notes are left in place by a reopen, and because the newest signed note still blocks a second delivery until it is superseded, re-opening a session is only useful in combination with recording a fresh note. A requested or scheduled session may be cancelled by the treating `Clinician` or an `OpsAdmin`; a manual cancellation is permitted only while `scheduled_start` is strictly after the logical clock, whereas a system-driven cancellation — triggered by a clinician whose posture reached `FROZEN` — carries no such precondition. Cancellation frees the slot, re-derives `open_slot_count`, and leaves `billing_state` at `UNBILLED`. A cancelled session can be rescheduled to a new interval by supplying a fresh `scheduled_start` and `scheduled_end`, which must satisfy the same availability and overlap rules the original booking did, and which re-quotes `quoted_cost_share_cents` from the patient's newest verified snapshot.

Documentation itself is the `Clinician`'s alone. A note is created with a `diagnosis_code`, a `duration_minutes`, the billed `cpt_code` and a `narrative`, and starts at `status` of `DRAFT` with `note_version` set to one more than the highest `note_version` already recorded for that session. Signing is permitted only for the clinician the session belongs to — the acting header must equal the session's `clinician_id` — and only when the `diagnosis_code` is present, the `narrative` is non-empty, and `duration_minutes` falls between 45 and 120 minutes inclusive. Signing stamps `signed_at` from the clock and `signer_clinician_id` from the acting header, and it locks any earlier signed note on the same session by moving it to `LOCKED`. The superseded note is not deleted and is not edited; it is simply no longer the note of record, and a transition that needs the newest note to be signed will not accept a locked one.

### 3.5. Claim Submission, Adjudication and Recovery

Billing a delivered session is an `OpsAdmin` act. A claim is submitted against a session that has reached `COMPLETED`; the clinician's `billing_posture` must read `BILLABLE` at that instant, and the session must carry exactly one note reading `SIGNED` which is also the newest note for the session. The precedence between the two documentation failures matters: a session whose newest note is a `DRAFT` sitting on top of an older `SIGNED` note fails as `ERR_NOTE_SUPERSEDED`, not as missing documentation, whereas a session with no signed note at all fails as `ERR_DOCUMENTATION_MISSING`. Eligibility is also checked against the payer: the payer must read `ACTIVE` for the session's service date, the session's `cpt_code` must be among the payer's `allowed_cpt_codes`, and an `EFFECTIVE` enrollment must cover the service date for the clinician-and-payer pair — a service falling before `effective_from` or at or after `effective_to` of the only covering enrollment is refused with `ERR_OUTSIDE_ENROLLMENT_WINDOW`, and any of the other eligibility failures is `ERR_SERVICE_NOT_ENROLLED`.

A successful submission creates the claim, stamps `submitted_on` from the logical clock, inherits the patient's payer and the session's clinician onto the claim, moves the claim through its initial `DRAFT` state to `SUBMITTED`, and at the same time advances the session's parallel billing axis to `CLAIM_SUBMITTED` and records the claim's identifier as the session's `claim_id`. The arithmetic is pinned, and each step stores its result on the claim. The claim's `billed_cents` is the resolved session rate described in §3.6. The claim's `allowed_cents` is that billed amount multiplied by 0.80 and rounded half up. The claim's `patient_resp_cents` is the adjudicated-variant cost share from §3.3, computed over the allowed amount. The claim's `payer_paid_cents` is the allowed amount less the patient responsibility, floored at zero. From submission until adjudication the patient response and payer-paid amounts read as zero on the claim, and they are filled in at adjudication; the billed and allowed amounts are fixed at submission. The ratio and the differentials mean the allowed amount cannot be recomputed from the rate row's `rate_cents` directly; it is derived from the billed amount that the differentials actually produced.

After those three figures are fixed, one saturation rule applies, and its boundary is exact. The claim being adjudicated is clamped only when the patient's `oop_met_cents` plus this claim's `patient_resp_cents` is strictly greater than `oop_max_cents`. In that case the claim's `patient_resp_cents` is rewritten to the larger of zero and the amount of room left under the out-of-pocket maximum, and the claim's `payer_paid_cents` is recomputed as `allowed_cents` less the rewritten responsibility, floored at zero, so the payer absorbs the remainder that the patient is no longer liable for. When the sum equals the maximum exactly, no clamp occurs; the equality case is the boundary between clamping and not clamping.

Adjudication records the payer's answer, supplied as an `outcome` of `PAID` or `DENIED`, optionally accompanied by a `denial_code` when the outcome is a denial. An outcome of `PAID` is permitted only when the claim's `allowed_cents` is at least zero; it moves the claim to `PAID`, advances the session's billing axis to `PAYER_PAID`, fixes `patient_resp_cents` and `payer_paid_cents` on the claim under the saturation rule above, increases the patient's `oop_met_cents` by the claim's `patient_resp_cents` capped at `oop_max_cents`, and commits the claim's earning to the clinician's newest payout line. An outcome of `DENIED` requires a `denial_code`, which is one of `TIMELY_FILING`, `NOT_COVERED`, `MISSING_DOCUMENTATION`, `AUTHORIZATION_REQUIRED` or `DUPLICATE`; it moves the claim to `DENIED`, moves the session's billing axis to `DENIED`, and sets `recovery_deadline` to `submitted_on` plus the payer's `timely_filing_days`. A claim that is already `PAID` can also be taken back: an adjudication of `DENIED` against a paid claim records the take-back reason as the `denial_code`, refreshes the recovery deadline the same way, moves the session's billing axis to `DENIED`, and — critically — does not un-pay anything. The earning already sits on a payout line, and the reversal is expressed as a negative adjustment against that line under §3.6; a line that was already paid keeps its `gross_cents` and shows the reversal in `adjustment_cents` rather than having its gross rewritten.

Recovery from a denial is bounded by two independent limits. Resubmitting a denied claim is permitted only while the logical clock is strictly before `recovery_deadline` and only while `resubmission_count` is at most 1, and it additionally requires the clinician's `billing_posture` to read `BILLABLE` at the resubmission instant. At the deadline instant itself resubmission is refused with `ERR_TIMELY_FILING_EXPIRED`; a claim that has already used both attempts is refused with `ERR_RESUBMISSION_LIMIT_REACHED`. An accepted resubmission clears the `denial_code` to null, increments `resubmission_count` by 1, and passes the claim through an intermediate `REPROCESSING` state before it returns to `SUBMITTED` — the intermediate state is observable and the counter is incremented at the moment resubmission is accepted, not when the reprocessing outcome is decided. Settling the reprocessing outcome is a separate act: an accepted outcome returns the claim to `SUBMITTED` with the session's billing axis back at `CLAIM_SUBMITTED` and a refreshed `submitted_on`, while a rejected outcome returns it to `DENIED` with `denial_code` of `DUPLICATE` and a refreshed recovery deadline. Writing a claim off, finally, is permitted when the logical clock is at or after `recovery_deadline` or when `resubmission_count` has reached 2 regardless of the clock; writing off while the clock is still strictly before the deadline and fewer than two resubmissions have occurred is refused with `ERR_WRITE_OFF_NOT_ALLOWED`. A write-off moves the claim to `WRITTEN_OFF` and the session's billing axis to `WRITTEN_OFF`, and records a negative adjustment against the clinician's newest payout line. The deadline boundary therefore carries opposite senses in its two readings: at exactly `recovery_deadline`, resubmission is rejected and write-off is permitted.

### 3.6. Payout Batches, Line Construction and Disbursement

#### Rate resolution

Every session's earning begins as a resolved contract rate in whole cents. Resolution proceeds in a pinned order. First, the candidate rate rows are selected: those whose payer matches the patient's payer, whose license type matches the clinician's license type, whose geography matches the clinician's `primary_state`, whose CPT code matches the session's `cpt_code`, and whose window covers the session's `scheduled_start` under the half-open rule — `effective_from` at or before the start, and `effective_to` null or strictly after the start. Second, the winner is the candidate with the highest `rate_set_version`; when two candidates share the highest version, the winner is the one with the largest `created_at`, and a tie on both keys cannot arise because the duplicate-rate rule forbids two rows sharing payer, rate-set version, license type, geography, CPT code and start instant, so the winner is always unique without falling back to any identifier. Third, when the first pass found nothing, the same selection is repeated with the geography anchored to the patient's `state_code` instead of the clinician's `primary_state`. Fourth, when that also finds nothing, the rate is zero. Fifth, when the session's modality is `VIDEO` and the clinician's license for eligible practice does not permit telehealth into the primary state, the rate is zero and the following two steps are skipped entirely. Sixth, while the session's `scheduled_start` is strictly before the clinician's `onboarded_at` plus 90 days, the rate is multiplied by 0.90 and rounded toward negative infinity; at and after that instant the step is skipped and the rate is left untouched. Seventh, once the activation instant `2026-07-01T00:00:00Z` has been reached, and only then, and only when the chosen rate row's geography differs from the patient's `state_code`, a branching differential is applied to the value the sixth step produced: if that value is at least 10,000 cents the rate becomes that value less 1,000 cents, and otherwise the rate becomes that value multiplied by 0.90 and rounded toward negative infinity.

The ordering of the last two steps is fixed and they are never applied in reverse. The branch test in the seventh step reads the value the sixth step produced, not the original rate, so swapping the two steps yields a different number for the same inputs. Rounding toward negative infinity means toward negative infinity, and there is no re-rounding after the seventh step. The seventh step's activation instant is `2026-07-01T00:00:00Z`: a session whose `scheduled_start` falls strictly before that instant takes the value the sixth step produced with no geography differential applied, and a session whose `scheduled_start` falls at or after it is subject to the differential. The differential's own effective-from is declared elsewhere in the specification's constant set as `2026-01-01T00:00:00Z`, which is earlier than the instants any session can carry in this domain; where the two instants disagree, the seventh step's `2026-07-01T00:00:00Z` test is the one that decides whether the differential fires.

#### Cost-share estimate reference

The estimator that produces patient cost share was specified in §3.3 and is reused here unchanged: booking reads the booking snapshot and carries the copay offset, adjudication reads the live accumulators and never carries it.

#### Payout lines and their amounts

A payout batch is opened by an `OpsAdmin` for a `period_start`, a `period_end` and a `schedule` of `WEEKLY`, `BIWEEKLY` or `SEMIMONTHLY`. A new batch starts at `status` of `OPEN` with `line_count` of 0 — lines are not materialised at opening but at lock time — and records `created_by_user_id` from the acting header. Opening a batch whose period overlaps an already-open batch on the same schedule retires the older one: the older batch, which must have a strictly earlier `created_at` and a period that overlaps the newcomer's, transitions to `SKIPPED`, each of its non-voided lines becomes `VOIDED`, and the newcomer records that batch's identifier as its `supersedes_batch_id`. A batch may also be retired explicitly before it is locked by an `OpsAdmin` whose observed `version` of that open batch still matches, which moves it to `SKIPPED` and voids its non-voided lines; the same endpoint requires `expected_open_batch_version` as described in §2.7 and rejects a stale observation with `ERR_STALE_VERSION` at HTTP 412.

Locking is permitted only when `period_end` is at or before the logical clock and at least one non-voided line exists on the batch; locking before the period closes, from a status other than `OPEN`, or with no non-voided lines is refused with `ERR_BATCH_NOT_LOCKABLE`. At lock time the system materialises one line per clinician who has at least one eligible session in the window, and each line is bound to the batch through `payout_batch_id` and carries that clinician's `session_ids`, `claim_ids`, `gross_cents`, `adjustment_cents` and `net_cents` under whichever payout variant is active for that clinician.

The variant is selected by two rules that point the same way. A clinician is paid on the scheduled basis when the batch's `schedule` is `WEEKLY` or `BIWEEKLY` and the clinician does not carry `cash_basis_opt_in`; those clinicians earn on every `COMPLETED` session in the window that has a signed note, regardless of whether the payer has paid anything, so `gross_cents` counts unpaid and denied sessions and the denials are picked up later as clawback adjustments. A clinician is paid on the cash basis when they carry `cash_basis_opt_in` set to true or when the batch's `schedule` is `SEMICONTHLY`; those clinicians earn only on sessions whose newest claim reads `PAID`, so `gross_cents` is strictly lower whenever any session in the window is unpaid or denied, and `adjustment_cents` carries no denial clawbacks at all because denied sessions were never included. Both variants read the same window and resolve rates identically, so the divergence is caused solely by the inclusion filter. The line records which variant produced it in its `basis` field. Note carefully what the scheduled basis includes: sessions with `status` of `COMPLETED` whose `scheduled_end` falls in the half-open window from `period_start` inclusive to `period_end` exclusive, for the line's clinician, whatever the state of the claim behind them.

The amounts are built by summing already-rounded integers, never by rounding a sum. The gross amount of a line is the sum, over its included sessions, of each session's resolved rate as described above — each session contributes its already-rounded integer rate, the sum itself is never re-rounded, and a batch total is the sum of line grosses. Applying the geography differential once to a sum of raw rate rows, or scaling a batch total, produces a different number by up to one cent per affected line and is wrong. The adjustment amount is the signed sum of the denial clawback adjustments carried by the line's claims, plus any residual carried in from the clinician's prior batch, and the net amount is the gross plus the adjustment. The line records `rate_set_version_used` as the rate-set version resolved for the newest session it includes.

#### Clawbacks and residuals

A denial becomes money only through the line that carries the claim. A claim is associated with the line that carries its earnings through the claim's own `assigned_payout_line_id`, which is null until a line has taken the claim on. Adding a clawback against a claim whose session sits on no payout line produces no adjustment at all. Against a session on a `PENDING` line, the adjustment is the negative of the resolved session rate, and if applying it would drive the line's net below zero the net is floored at zero and the shortfall — a positive magnitude — is carried on the clinician as `pending_clawback_residual_cents` for the next batch. Against a session on a `PAID` line, the adjustment is likewise the negative of the resolved session rate but the net is allowed to go negative with no floor, and that negative value is meant to be seen. The asymmetry is deliberate: the floor protects an unpaid line from showing a negative payable, while a line that has already been disbursed shows the reversal in full.

A line's status follows from its own history rather than from the sign of its adjustment alone. A line whose adjustment falls below zero becomes `CLAWED_BACK` only if it was already `PAID`; a line that is still `PENDING` keeps its `PENDING` status and simply has its net floored at zero. That distinction is what makes the two variants' books reconcile: the same denial produces different line-level outcomes depending on whether the money has left the building.

#### Batch totals, payment and reconciliation

Locking freezes the batch's `total_gross_cents`, `total_adjustment_cents`, `total_net_cents` and `line_count` as a snapshot taken over its non-voided lines: the total gross is the sum of the included lines' `gross_cents`, the total adjustment is the signed sum of their `adjustment_cents`, the total net is the sum of their `net_cents`, and the line count is the number of included lines. Voided lines are excluded entirely — a batch all of whose lines were voided by supersession has a line count of zero and all totals of zero. The rounding order is again pinned: per-line values are computed and stored first and only then summed.

Paying a locked batch is permitted only when every non-voided line on it is `PENDING` or already `PAID`; a batch in any status other than `LOCKED`, or one carrying a line in some other status, is refused with `ERR_BATCH_NOT_PAYABLE`. Paying sets the batch to `PAID`, moves every `PENDING` line to `PAID`, and increments each paid clinician's `payout_balance_cents` by that line's net. Payment is decoupled from payer remittance: a batch is paid on its schedule whether or not the payers behind its claims have remitted, and a line already sitting in `CLAWED_BACK` is left alone by the payment run rather than being re-paid or re-floored.

Reconciling is permitted only when every non-voided line on a paid batch is `PAID` or `CLAWED_BACK`, and it closes the batch: any denial adjustment that landed after payment is applied as an additional clawback and the batch lands terminally in `RECONCILED`.

A clinician's balance reflects only settled and reversed money, and the classification of each line decides how much of it contributes. Lines in `PAID` contribute their `net_cents`; lines in `PENDING` contribute zero; lines in `CLAWED_BACK` contribute their `adjustment_cents`, which is to say the negative reversal rather than the original gross. Voided lines contribute nothing at all, not even their adjustment. Because a `PAID` line's net may go negative when a clawback exceeds its gross and the floor applies only to pending lines, that negative value flows into the balance unchanged. This is the mechanism by which a therapist who has been paid for work later denied by the payer ends up with the reversal carried against a future payout rather than with a demand for a refund.

### 3.7. Caseload Balance, Patient Matching and Continuity of Care

Matching a patient to a clinician is an `OpsAdmin` act that chooses from a filtered and ranked candidate set, and the rank is computed once, from a single consistent read of the candidate rows taken before any match is written, so an earlier assignment in the same request never shifts a later candidate's ranking. A candidate must satisfy all six eligibility conditions together: the clinician's `status` is `ACTIVE`; the clinician's `billing_posture` is `BILLABLE`; the patient's payer appears among the payer identifiers of that clinician's `EFFECTIVE` enrollments; the intersection of the clinician's `specialty_tags` with the requested `specialty_tags` is non-empty; the clinician's `primary_state` equals the patient's `state_code`, or some license of that clinician has an `issuing_state` equal to the patient's `state_code` and is `telehealth_eligible`; and the clinician's `active_patient_count` is strictly less than their `weekly_caseload_target`.

Surviving candidates are ranked by three keys applied in order: the descending count of matched specialty tags, then the ascending `active_patient_count`, then the ascending `created_at`. The tie-breaking ends at the third key — if two candidates remain tied on `created_at` the request is rejected with `ERR_MATCH_TIE_UNRESOLVABLE`, and the server never falls back to `id` or any other value. An empty candidate set is rejected with `ERR_NO_ELIGIBLE_CLINICIAN` at HTTP 422 and no match is written.

Caseload arithmetic uses two predicates that deliberately disagree at the boundary. Utilization is the floor of one hundred times the clinician's `active_patient_count` divided by the `weekly_caseload_target`. Acceptance of a new patient is allowed only while `active_patient_count` is strictly less than the target. Waitlist eligibility begins once utilization reaches 90 hundredths or more, inclusively. The senses are opposite on the same numbers: at a patient count exactly equal to the target, acceptance is not allowed while waitlist eligibility is true. Attempting to push a clinician to or past their target through continuity acceptance or through a match is refused with `ERR_CASELOAD_FULL` at HTTP 409.

Continuity planning is what protects a patient when their therapist leaves. An `OpsAdmin` may open a continuity plan explicitly with the departing `clinician_id`, the `patient_id`, a `reason` of `OFFBOARDING`, `CASELOAD_REBALANCE` or `CLINICAL_CONFLICT`, and an optional `successor_clinician_id`; it starts at `PENDING`, and its `reassignment_deadline` is the departure instant plus the 30-day continuity grace window, computed on the logical clock — or, when no offboarding instant is recorded on the clinician, the clock at the moment the plan is opened. Requesting offboarding for a clinician opens one plan per matched patient automatically: an `OpsAdmin` may move an `ACTIVE` clinician into `OFFBOARDING` only when the clinician's `open_slot_count` is 0 and they carry at least one active patient, and doing so stamps `offboarding_requested_on` from the clock, drops `billing_posture` to `GATED`, and creates one plan per `PatientClient` whose `matched_clinician_id` is that clinician, each at `PENDING` with `reason` of `OFFBOARDING` and `successor_clinician_id` null.

A proposed successor accepts or declines. Acceptance is a `Clinician` act permitted only when the acting header equals the proposed `successor_clinician_id`, that clinician's `billing_posture` is `BILLABLE`, and that clinician's `active_patient_count` is strictly less than their `weekly_caseload_target`. Accepting moves the plan to `ACCEPTED`, transfers the patient's `matched_clinician_id` to the successor, decrements the prior clinician's `active_patient_count` and increments the successor's, and clears the patient's `swap_requested` flag. Declining moves the plan to `DECLINED` and does nothing else. An `OpsAdmin` may assign or replace the successor on a plan, which returns a `DECLINED` or `ESCALATED` plan to `PENDING` and clears `swap_requested`; this is permitted while the logical clock is strictly before `reassignment_deadline` from `DECLINED`, and while the clock is strictly before `reassignment_deadline` plus 7 days from `ESCALATED`, and it requires a non-null `successor_clinician_id` in the `ESCALATED` case. Requested at or after the extended deadline for a declined or escalated plan, the attempt is refused with `ERR_CONTINUITY_DEADLINE_PASSED`. The same endpoint requires `expected_plan_version` as described in §2.7 and rejects a stale observation with `ERR_STALE_VERSION` at HTTP 412.

Escalation is the system's way of saying that a plan is no longer comfortably reassignable, and it has two independent triggers, either of which suffices. The first is a session for the patient completing while the owning clinician's `status` is `OFFBOARDING` or `OFFBOARDED`. The second is the logical clock reaching `reassignment_deadline` while the plan is still `PENDING` or `DECLINED`. Delivery is deliberately not blocked by the offboarding completeness gate, so escalation can reach a plan while it is still reassignable. Whenever a plan escalates, the patient's `swap_requested` flag is set to true, and the flag is cleared only when the plan returns to `PENDING` or when a successor accepts it. A plan moves from `ACCEPTED` to `COMPLETED` only once the patient's `matched_clinician_id` actually equals the `successor_clinician_id`, which decrements the departing clinician's `continuity_plan_count`.

A departing clinician reaches `OFFBOARDED` when their `active_patient_count` reaches 0 — either automatically, or by an explicit completion by an `OpsAdmin` that requires exactly that — and completing offboarding forces `billing_posture` to `FROZEN`, escalates every still-`PENDING` continuity plan of that clinician, sets `swap_requested` on each of those patients, and cancels every one of the clinician's sessions still in `REQUESTED` or `SCHEDULED`. Escalation of a pending plan at offboarding completion exists precisely so that a half-reassigned caseload cannot be left in limbo when the clinician finally leaves. An `OpsAdmin` can also reverse an in-progress departure: while every continuity plan for the clinician is in `PENDING` or `COMPLETED`, the `OFFBOARDING` status can be reverted to `ACTIVE`, which clears `offboarding_requested_on`, recomputes `continuity_plan_count`, and re-derives posture to `BILLABLE` when a malpractice policy reads `ACTIVE` and `enrolled_payer_count` is at least 1, or to `GATED` otherwise. The clinician status machine is therefore cyclic rather than one-way: `ACTIVE` to `OFFBOARDING` and back, with `OFFBOARDED` the only state that admits no return.

### 3.8 Network-Wide Cascades: Payer Suspension and Termination

The most far-reaching operations in the system are ordinary `OpsAdmin` edits to a payer's status, because a payer sits underneath every enrollment, every session that depends on one, and every claim already in flight. Each of the three target statuses has a different blast radius.

Moving a payer to `SUSPENDED_AT_PAYER` cascades in three hops. First, every enrollment with that payer in `EFFECTIVE` status moves to `SUSPENDED`. Second, each enrollment that was suspended re-derives its clinician's `enrolled_payer_count` and posture, and a clinician whose `enrolled_payer_count` reaches zero becomes `FROZEN` — which is the route by which a payer-side problem can freeze a clinician even though every license and policy remains in order. Third, each clinician frozen in that hop has every session still in `REQUESTED` or `SCHEDULED` cancelled and each cancelled session's `slot_consumed` set back to false. Returning the payer to `ACTIVE` does not run the cascade in reverse: enrollments are not auto-restored, and each one stays `SUSPENDED` until an `OpsAdmin` reinstates it individually.

Moving a payer to `TERMINATED`, from either `ACTIVE` or `SUSPENDED_AT_PAYER`, is more destructive and reaches money. Every enrollment with that payer in `PENDING`, `EFFECTIVE` or `SUSPENDED` status moves to `TERMINATED`. Every claim with that payer that is still `SUBMITTED` is denied with a `denial_code` of `NOT_COVERED`. And every claim denied in that sweep appends a clawback adjustment to its clinician's newest payout line: a clinician with no line in `PENDING` or `PAID` status gets a new `PENDING` line with a `gross_cents` of 0 so that the clawback has somewhere to live, a line that is still `PENDING` keeps its status with its net floored at zero, and a line that has already been paid becomes `CLAWED_BACK`. A clinician may therefore learn that a payer exited the network only by watching their balance move.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a distinct new resource to a collection, respond with `201 Created`. Operations that modify an existing resource — including transitions on a resource and writes that only refresh derived fields — respond with `200 OK`. All responses use the envelope in §2.2, and all list responses obey the pagination contract in §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/network/clinicians` | Onboard a clinician; status `ONBOARDING`, posture `GATED`, `onboarded_at` stamped from the logical clock | OpsAdmin |
| GET | `/network/clinicians` | List clinicians; filter by `status`, `billing_posture`, `primary_state`, `license_type` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/clinicians/{id}` | Fetch one clinician with derived posture, counts and balance | OpsAdmin, ComplianceOfficer, Clinician, Patient |
| PUT | `/network/clinicians/{id}` | Update caseload target, availability blocks, specialty tags or primary state; re-derive slots and posture | OpsAdmin |
| POST | `/network/clinicians/{id}/submit-credentials` | Move a clinician from `ONBOARDING` to `CREDENTIALING` | ComplianceOfficer |
| POST | `/network/clinicians/{id}/suspend` | Suspend an active clinician; freeze posture and cancel open sessions | OpsAdmin |
| POST | `/network/clinicians/{id}/reinstate` | Reinstate a suspended clinician when licenses and enrollments permit | OpsAdmin |
| POST | `/network/clinicians/{id}/request-offboarding` | Begin offboarding; open one continuity plan per matched patient | OpsAdmin |
| POST | `/network/clinicians/{id}/cancel-offboarding` | Revert `OFFBOARDING` to `ACTIVE` | OpsAdmin |
| POST | `/network/clinicians/{id}/complete-offboarding` | Finalize offboarding and escalate any remaining pending plans | OpsAdmin |
| POST | `/network/clinicians/{id}/licenses` | Record a state license for a clinician | OpsAdmin |
| GET | `/network/clinicians/{id}/licenses` | List licenses; filter by `license_type`, `issuing_state`, `verification_status` | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/clinicians/{clinician_id}/licenses/{id}/verify` | Verify a license; `VERIFIED` or `FAILED` by comparison with the logical clock | ComplianceOfficer |
| POST | `/network/clinicians/{clinician_id}/licenses/{id}/reverify` | Re-verify an expired license with a replacement expiry | ComplianceOfficer |
| POST | `/network/clinicians/{clinician_id}/licenses/{id}/reset-verification` | Return a failed license to `UNVERIFIED` | ComplianceOfficer |
| POST | `/network/clinicians/{id}/malpractice-policies` | Record a malpractice policy; policy status derived on read | OpsAdmin |
| GET | `/network/clinicians/{id}/malpractice-policies` | List malpractice policies; filter by `policy_status` | OpsAdmin, ComplianceOfficer |
| POST | `/network/payers` | Create a payer with delegated-credentialing posture and billing constraints | OpsAdmin |
| GET | `/network/payers` | List payers; filter by `status`, `delegated_credentialing` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/payers/{id}` | Fetch one payer | OpsAdmin, ComplianceOfficer, Clinician |
| PATCH | `/network/payers/{id}` | Change payer status; suspension and termination cascade through enrollments, sessions and claims | OpsAdmin |
| POST | `/network/payers/{id}/rates` | Publish a rate row keyed by license type, geography and CPT code | OpsAdmin |
| GET | `/network/payers/{id}/rates` | List rate rows; filter by `license_type`, `geography`, `cpt_code`, `rate_set_version` | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/payer-enrollments` | Submit a clinician for credentialing with a payer; starts `PENDING` | OpsAdmin |
| GET | `/network/payer-enrollments` | List enrollments; filter by `clinician_id`, `payer_id`, `status` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/payer-enrollments/{id}` | Fetch one enrollment | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/payer-enrollments/{id}/activate` | Move an enrollment to `EFFECTIVE` when the credentialing floors hold | OpsAdmin |
| POST | `/network/payer-enrollments/{id}/reject` | Reject a pending enrollment terminally | OpsAdmin |
| POST | `/network/payer-enrollments/{id}/suspend` | Suspend an effective enrollment | OpsAdmin |
| POST | `/network/payer-enrollments/{id}/reinstate` | Return a suspended enrollment to `EFFECTIVE` | OpsAdmin |
| POST | `/network/payer-enrollments/{id}/terminate` | Terminate an enrollment terminally | OpsAdmin |
| POST | `/network/patients` | Register a patient with plan parameters and insurance identifiers | OpsAdmin |
| GET | `/network/patients` | List patients; filter by `payer_id`, `state_code`, `benefit_status`, `matched_clinician_id` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/patients/{id}` | Fetch one patient with derived benefit status and accumulators | OpsAdmin, ComplianceOfficer, Clinician, Patient |
| POST | `/network/patients/{id}/match` | Select the best eligible clinician and assign the match | OpsAdmin |
| POST | `/network/patients/{id}/verification` | Record a benefit verification snapshot and quote the provisional cost share | OpsAdmin |
| GET | `/network/patients/{id}/verification` | List benefit verifications; filter by `status` | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/sessions` | Request a session; starts `REQUESTED` with billing state `UNBILLED` | OpsAdmin |
| GET | `/network/sessions` | List sessions; filter by `clinician_id`, `patient_id`, `status`, `billing_state` | OpsAdmin, ComplianceOfficer, Clinician, Patient |
| GET | `/network/sessions/{id}` | Fetch one session | OpsAdmin, ComplianceOfficer, Clinician, Patient |
| POST | `/network/sessions/{id}/schedule` | Confirm a requested session against availability and overlap rules | Clinician, OpsAdmin |
| POST | `/network/sessions/{id}/complete` | Mark a scheduled session delivered against its signed note | Clinician, OpsAdmin |
| POST | `/network/sessions/{id}/reopen` | Return a completed but unbilled session to `SCHEDULED` | OpsAdmin |
| POST | `/network/sessions/{id}/cancel` | Cancel a requested or scheduled session | Clinician, OpsAdmin |
| POST | `/network/sessions/{id}/reschedule` | Move a cancelled session to a new interval | Clinician, OpsAdmin |
| POST | `/network/sessions/{id}/notes` | Attach a documentation note; supersedes any earlier note under the OCC rule | Clinician |
| GET | `/network/sessions/{id}/notes` | List notes for a session; filter by `status` | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/sessions/{session_id}/notes/{id}/sign` | Sign a draft note and lock the prior signed note | Clinician |
| POST | `/network/claims` | Submit a claim on a completed session for billing on the clinician's behalf | OpsAdmin |
| GET | `/network/claims` | List claims; filter by `session_id`, `claim_status`, `payer_id` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/claims/{id}` | Fetch one claim with its derived deadline and resubmission counter | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/claims/{id}/adjudicate` | Record remittance advice; move the claim to `PAID` or `DENIED` | OpsAdmin |
| POST | `/network/claims/{id}/resubmit` | Reprocess a denied claim before the deadline and at most twice | OpsAdmin |
| POST | `/network/claims/{id}/decide-reprocessing` | Settle the reprocessing outcome | OpsAdmin |
| POST | `/network/claims/{id}/write-off` | Write a denied claim off as uncollectible | OpsAdmin |
| POST | `/network/payout-batches` | Open a payout batch for a period and schedule | OpsAdmin |
| GET | `/network/payout-batches` | List payout batches; filter by `status`, `schedule` | OpsAdmin, Clinician |
| GET | `/network/payout-batches/{id}` | Fetch one payout batch with frozen totals when locked | OpsAdmin, Clinician |
| POST | `/network/payout-batches/{id}/lock` | Freeze a batch's totals over its non-voided lines | OpsAdmin |
| POST | `/network/payout-batches/{id}/pay` | Pay a locked batch independent of payer remittance | OpsAdmin, PayrollService |
| POST | `/network/payout-batches/{id}/reconcile` | Close a paid batch after post-payment denials | OpsAdmin |
| POST | `/network/payout-batches/{id}/supersede` | Retire an open batch under the OCC contract | OpsAdmin |
| GET | `/network/payout-batches/{id}/lines` | List the payout lines on a batch; filter by `line_status` | OpsAdmin, Clinician, PayrollService |
| GET | `/network/clinicians/{id}/payout-lines` | List payout lines for a clinician across batches; filter by `line_status` | OpsAdmin, Clinician |
| POST | `/network/continuity-plans` | Open a continuity plan for a patient of a departing clinician | OpsAdmin |
| GET | `/network/continuity-plans` | List continuity plans; filter by `clinician_id`, `patient_id`, `status` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/continuity-plans/{id}` | Fetch one continuity plan | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/continuity-plans/{id}/successor` | Assign or replace the successor clinician | OpsAdmin |
| POST | `/network/continuity-plans/{id}/accept` | Successor accepts a plan and the patient match transfers | Clinician |
| POST | `/network/continuity-plans/{id}/decline` | Proposed successor declines the plan | Clinician |
| POST | `/network/continuity-plans/{id}/complete` | Close a plan once the patient is confirmed with the successor | OpsAdmin |
| GET | `/network/claims/{id}/payout-line` | Fetch the payout line carrying this claim's earnings | OpsAdmin, Clinician, ComplianceOfficer |
| GET | `/network/patients/{id}/sessions` | List sessions booked for a patient; filter by `status`, `billing_state` | OpsAdmin, ComplianceOfficer, Clinician, Patient |
| GET | `/network/clinicians/{id}/continuity-plans` | List continuity plans owned by a departing clinician; filter by `status` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/patients/{id}/continuity-plans` | List continuity plans opened for a patient; filter by `status` | OpsAdmin, ComplianceOfficer, Clinician |
| GET | `/network/payers/{id}/payer-enrollments` | List the clinician enrollments filed with a payer; filter by `status` | OpsAdmin, ComplianceOfficer, Clinician |
| POST | `/network/_clock/set_current_utc` | Set the logical clock; default `2026-09-01T00:00:00Z` before any call | OpsAdmin |
| POST | `/network/_inject/claim-outcome` | Deliver a synthetic remittance advice so adjudication paths are reachable deterministically | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CLINICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_NOTE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_CONTINUITY_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CASELOAD_FULL` | 409 Conflict |
| `ERR_CLINICIAN_SLOT_CONFLICT` | 409 Conflict |
| `ERR_PATIENT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BATCH_NOT_LOCKABLE` | 409 Conflict |
| `ERR_BATCH_NOT_PAYABLE` | 409 Conflict |
| `ERR_WRITE_OFF_NOT_ALLOWED` | 409 Conflict |
| `ERR_PAYER_SUSPENDED` | 409 Conflict |
| `ERR_CONTINUITY_DEADLINE_PASSED` | 409 Conflict |
| `ERR_DUPLICATE_RATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLINICIAN_NOT_BILLABLE` | 422 Unprocessable Entity |
| `ERR_SERVICE_NOT_ENROLLED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_ENROLLMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_TIMELY_FILING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RESUBMISSION_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_DOCUMENTATION_MISSING` | 422 Unprocessable Entity |
| `ERR_DURATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOTE_SUPERSEDED` | 422 Unprocessable Entity |
| `ERR_BENEFIT_UNVERIFIED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_CLINICIAN` | 422 Unprocessable Entity |
| `ERR_MATCH_TIE_UNRESOLVABLE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_WINDOW_INVALID` | 422 Unprocessable Entity |