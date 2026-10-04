# Federal Payment Offset API — Product Requirements Document

## 1. Introduction

This document specifies the Federal Payment Disbursement and Treasury Offset Program API, operated in the spirit of the Bureau of the Fiscal Service's collection mandate. The system receives payment files from federal agencies, verifies each payee, determines the disbursement method, and — before any money moves — screens every payment against a database of delinquent debts referred by federal and state creditors. When a payee owes, the payment is offset: funds are diverted to creditors in a strict statutory priority order, net of a remittance fee, and only the remainder is released to the payee.

The program is compliance-heavy by design. Pre-offset due process — notice and an opportunity to dispute — is attested by the referring creditor and enforced by the platform before a debt becomes offset-eligible. Exemption policies protect certain payment types through protected minimums and percentage caps. Administrative wage garnishment and cross-servicing extend collection beyond the payment stream, reciprocal agreements let states offset their own outgoing payments against federal debts, and a do-not-pay screen blocks disbursement to deceased or excluded payees. Refund claims with independent review, segregation of duties between the operator who executed an offset and the officer who judges it, and full-fidelity reversal cascades keep the creditor ledgers auditable when an offset is later found improper.

All temporal behavior — notice windows, hearing windows, appeal deadlines, claim windows, agreement coverage, do-not-pay intervals, request expiry, and settlement — is governed by a controllable logical clock rather than wall-clock time, so every rule in this document is deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).

Seven roles are declared: `TreasurySupervisor`, `TreasuryOperator`, `PaymentAgencyAnalyst`, `CreditorAnalyst`, `StateCoordinator`, `RefundOfficer`, and `Auditor`. An eighth actor, `System`, is the automation identity behind clock sweeps and cascade recomputation; it is never callable — no request may present `System` in `X-User-Role`. Every endpoint restricts which roles may invoke it (see §4); a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (403). The `Auditor` is read-only: it may call any retrieval endpoint and nothing else.

Identity semantics differ by role. When `X-User-Role` is `CreditorAnalyst`, `X-User-ID` is the `id` of the acting `CreditorAgency`; ownership checks on any resource that references a creditor compare the resource's `creditor_agency_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `TreasurySupervisor`, `TreasuryOperator`, `PaymentAgencyAnalyst`, `StateCoordinator`, `RefundOfficer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `executed_by_user_id` on a payment or `decided_by_user_id` on a refund claim — but never compares it to any entity's `id`. One cross-role rule depends on those recorded identifiers: the `RefundOfficer` deciding a refund claim must not be the same `X-User-ID` that executed the claimed offset's payment, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It reads server wall-clock time; the logical clock of §2.4 governs resource timestamps and every temporal rule instead.
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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Out-of-range values clamp to the nearest bound rather than failing — a `limit` below 1 reads as 1, above 100 as 100, and a negative `offset` as 0 — while a non-integer `limit` or `offset` is `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` — common under the logical clock — broken by creation (insertion) order.

The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

A single logical clock governs every temporal rule in the system: notice windows, hearing windows, appeal and claim deadlines, agreement coverage windows, do-not-pay intervals, request expiry, settlement, and the creditor ledgers' calendar-year boundaries all read this clock and never wall-clock time. Before it is ever set, the clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own.

A `TreasurySupervisor`-only test-driving capability moves the clock by supplying a `current_utc` instant — any instant is accepted, including one earlier than the current reading — (`POST /_clock/set_current_utc`, which sits outside the business surface); it responds `200 OK` with an object carrying the new `current_utc`. Setting the clock also runs the settlement sweep: every `EXECUTED` payment whose parent file's `settlement_date` falls on or before the clock's UTC date transitions to `SETTLED`. The same clock read seeds the lazy calendar-year reset of the remittance ledgers (§2.9), the half-open coverage tests of reciprocal agreements (§2.10), the closed-interval do-not-pay matches (§2.11), and the lazy expiry of reverse-offset requests (§3.8). Datetime request fields throughout the API accept ISO 8601 date-only strings (read as midnight UTC) as well as full datetimes with a trailing `Z` or an explicit offset; every stored instant serializes back as an ISO 8601 UTC datetime with three fractional digits.

### 2.5. Common Resource Properties

Every resource in the system — creditor agencies, payees, exemption policies, debts, payment files, payments, offsets, refund claims, collection agencies, collection actions, reverse-offset requests, reciprocal agreements, and do-not-pay records — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.4) and fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp read from the same logical clock, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 and increments with every mutation of the resource, including system-driven transitions and cascaded side effects; it is the basis for optimistic concurrency control (§2.7).

### 2.6. Monetary Representation, Precision, and Rounding

All monetary amounts in the system are integer cents — on the wire, in storage, and inside every calculation. Wherever a percentage enters a computation (the offset-pool percentage cap, the remittance fee, the garnishment dip), the percentage term is rounded half up to whole cents.

Aggregation order is pinned at the file level: each payment's offset pool is computed and rounded to whole cents first, and the file totals are the plain sums of those per-payment rounded integers. Summing unrounded pools and rounding once at the file level is forbidden — it yields a different cent total.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two:

- Offset evaluation (`POST /payments/{paymentId}/evaluate-offsets`) requires the non-optional request field `expected_payment_version`, carrying the client's last observed `version` of the target payment. If it does not equal the payment's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Re-evaluation legitimately supersedes the prior proposed offset set — old proposals are dropped and a fresh match is computed — so a client whose view of the payment predates the most recent evaluation holds a stale basis for its match and is refused. The check is purely version-based: a strictly sequential second evaluation carrying the pre-supersede version fails.
- Recording a collection (`POST /collection-actions/{collectionActionId}/collect`) requires the non-optional request field `expected_debt_version`, carrying the client's last observed `version` of the debt under collection. A mismatch with the debt's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Each collection mutates the debt's balance — and caps a garnishment dip at the remaining balance — so a client holding a pre-collection version would compute against a balance the debt no longer has; here too the check is purely version-based and a strictly sequential retry with the old version fails.

Endpoints not listed above do not take a version field at all.

### 2.8. Validation Order and Error Precedence

Every request is validated against an ordered cascade of eleven tiers, and the first failing tier produces the response, masking anything later. In order:

1. **Header presence.** `X-User-ID` and `X-User-Role` are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Authorization.** The caller's role is listed for the endpoint; a `CreditorAnalyst` must additionally be acting on its own creditor's debt, whether referring a new one or transitioning an existing one — otherwise `ERR_FORBIDDEN_FOR_ROLE` (403).
3. **Segregation of duties.** On refund decisions, the decider differs from the operator recorded as having executed the claimed offset's payment — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
4. **Request schema.** Required fields present, no unknown fields, enum membership, positive amounts, ordered effective windows, and the conditional-field rules (state code, policy-class fields, garnishment-versus-cross-servicing fields) — otherwise `ERR_INVALID_REQUEST` or `ERR_STATE_CODE_REQUIRED` (400). A conditional-field rule whose discriminator lives on a path-loaded resource — the collect payload's garnishment-versus-cross-servicing fields, discriminated by the loaded action's `action_type` — is evaluated immediately after that resource loads, still ahead of the state tier.
5. **Path existence.** Identifiers in the path exist, validated left to right, failing on the first missing one — otherwise `ERR_NOT_FOUND` (404).
6. **Body foreign keys.** Referenced resources exist, validated in the endpoint's declared input order: `payee_id` surfaces `ERR_PAYEE_NOT_FOUND`, `creditor_agency_id` surfaces `ERR_CREDITOR_NOT_FOUND`, and `offset_id` surfaces `ERR_OFFSET_NOT_FOUND` (all 404).
7. **State preconditions.** The attempted transition is defined for the resource's current state — terminal states included — and OCC version equality holds where §2.7 applies — otherwise `ERR_INVALID_STATE`, `ERR_PAYMENT_NOT_EXECUTABLE`, `ERR_OFFSET_NOT_APPLIED`, or `ERR_APPEAL_LIMIT_REACHED` (409), or `ERR_STALE_VERSION` (412). Within this tier, the state precondition is evaluated before the OCC version equality check.
8. **Compliance gates.** Due-process attestation, the pre-offset notice window, the garnishment hearing window, and payment integrity — otherwise `ERR_DUE_PROCESS_NOT_COMPLETED`, `ERR_NOTICE_WINDOW_NOT_ELAPSED`, `ERR_AWG_HEARING_WINDOW_OPEN`, or `ERR_DNP_FLAGGED_PAYMENT` (409).
9. **Temporal windows.** Claim, appeal, request-expiry, and window-overlap rules — otherwise `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_REQUEST_EXPIRED`, `ERR_AGREEMENT_OVERLAP`, or `ERR_DNP_WINDOW_OVERLAP` (409).
10. **Referential consistency and selector gates.** Uniqueness of `tin`, `creditor_code`, and `agency_code`; payee-TIN equality; active-policy presence; agreement coverage; collection-agency availability — otherwise `ERR_DUPLICATE_TIN`, `ERR_DUPLICATE_CREDITOR_CODE`, or `ERR_DUPLICATE_AGENCY_CODE` (409); `ERR_PAYEE_TIN_MISMATCH` (422); or `ERR_NO_ACTIVE_POLICY`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_NO_RECIPROCAL_AGREEMENT`, or `ERR_NO_COLLECTION_AGENCY_AVAILABLE` (409).
11. **Amount bounds.** Claim and remittance ceilings — otherwise `ERR_REFUND_EXCEEDS_OFFSET`, `ERR_COLLECT_EXCEEDS_BALANCE`, or `ERR_COLLECT_AMOUNT_ZERO` (422).

The ordering is observable behavior: a request failing an earlier tier never surfaces a later tier's error, so, for example, a malformed body on a request with missing headers reports the header failure, and a claim against a nonexistent offset reports the existence failure rather than any state or amount rule.

### 2.9. Creditor Remittance Ledgers

Each creditor agency carries a ledger maintained entirely by the system. `remitted_gross_ytd_cents` accumulates gross (pre-fee) collections remitted in the current logical-clock calendar year; `remitted_ytd_year` records which calendar year that accumulation belongs to; and `remitted_net_total_cents` is the all-time net (post-fee) ledger, credited on collections and debited on refund clawbacks and payment reversals. A fourth value, `outstanding_receivable_cents`, is never stored: it is derived on every read as the sum of `current_balance_cents` over the creditor's debts in `ACTIVE` or `IN_COLLECTION` status. A freshly registered creditor starts with `remitted_gross_ytd_cents` and `remitted_net_total_cents` at 0 and `remitted_ytd_year` null.

Every collection event — an offset applied at execution, a garnishment or agency collection, a reverse-offset confirmation — assesses a remittance fee against the creditor of the debt being collected, in a pinned order:

1. Lazy year reset: if the logical clock's calendar year differs from `remitted_ytd_year`, `remitted_gross_ytd_cents` resets to 0 and `remitted_ytd_year` adopts the clock's year.
2. The pre-event gross year-to-date figure is read.
3. The fee percentage is three percent when that pre-event gross is below 60,000 cents (six hundred dollars), and two percent when it is at or above that threshold. The current event never counts toward its own tier.
4. The fee is the gross collected amount multiplied by that percentage, rounded half up to whole cents; the net remittance is the gross minus the fee.
5. Only then are the counters credited: `remitted_gross_ytd_cents` increases by the gross amount and `remitted_net_total_cents` by the net amount.

Unwinding is symmetric where the semantics demand it. A payment reversal decrements both counters by the original gross and net amounts of each reversed offset; a refund clawback decrements `remitted_net_total_cents` by the clawed-back amount only, leaving the gross year-to-date figure untouched.

### 2.10. Reciprocal Agreement Coverage

Agreements with states are time-boxed and direction-scoped. `direction` is one of `FED_TO_STATE` (state debts may be offset from federal payments), `STATE_TO_FED` (federal debts may be offset from state payments), or `BIDIRECTIONAL` (counts as both scopes). The coverage window is half-open: `effective_from` is inclusive, `effective_until` is exclusive, and `effective_until` must be strictly after `effective_from` — an inverted window is `ERR_INVALID_REQUEST`.

An agreement is created `DRAFT` and becomes `ACTIVE` only through activation; `ACTIVE` is absorbing — there is no terminate operation, and coverage simply ends when the logical clock reaches `effective_until`. Two gates elsewhere in the system read this coverage: a state creditor's debt can become offset-eligible only while a `FED_TO_STATE` or `BIDIRECTIONAL` agreement covers the creditor's state at the current clock (§3.3), and a state can request a reverse offset only while a `STATE_TO_FED` or `BIDIRECTIONAL` agreement covers it (§3.8).

No two `ACTIVE` agreements for the same `state_code` may have half-open-overlapping windows with conflicting direction scopes. `BIDIRECTIONAL` conflicts with every scope, `FED_TO_STATE` conflicts with `FED_TO_STATE` and `BIDIRECTIONAL`, and `STATE_TO_FED` conflicts with `STATE_TO_FED` and `BIDIRECTIONAL`. A creation or activation that would produce such an overlap is rejected with `ERR_AGREEMENT_OVERLAP` (409).

### 2.11. The Do-Not-Pay Screen

Payment integrity is enforced through do-not-pay records. Each record lists a `tin` on one `list_source` — `DEATH_MASTER_FILE`, `SAM_EXCLUSION`, or `DEBARMENT_LIST` — over a closed interval: both `effective_from` and `effective_until` are inclusive, and `effective_until` must be on or after `effective_from`. Two `ACTIVE` records for the same `tin` and `list_source` may not have overlapping intervals — a `REMOVED` record's interval no longer participates in the conflict test — and intervals that merely touch count as overlapping; a conflicting creation is rejected with `ERR_DNP_WINDOW_OVERLAP` (409).

The match evaluation asks one question: does an `ACTIVE` record exist whose `tin` equals the payee's TIN and whose closed interval contains the current logical clock? A hit sets a payment's `integrity_status` to `FLAGGED`; otherwise it is `CLEAR`. The evaluation runs at three moments — payment intake, record creation, and record removal — and drives the hold and release cascades described in §3.9. A `FLAGGED` payment cannot be executed (§3.5).

## 3. Business Logic & Workflows

### 3.1. Registry Onboarding: Creditors, Payees, and Collection Agencies

A `TreasurySupervisor` registers each creditor agency with a unique `creditor_code` — duplicates are rejected with `ERR_DUPLICATE_CREDITOR_CODE` — a `legal_name`, and a `creditor_type` of `FEDERAL` or `STATE`. The `state_code` field is conditional: a `STATE` creditor must supply its two-letter code, and a missing code is `ERR_STATE_CODE_REQUIRED`; a `FEDERAL` creditor must omit it entirely, and a supplied code is `ERR_INVALID_REQUEST`. Registration initializes the creditor's remittance ledger exactly as §2.9 describes, with both counters at 0 and the year marker null.

Payees are registered by a `TreasurySupervisor` or a `TreasuryOperator`. Each payee declares a `tin` — unique across all payees, with duplicates rejected as `ERR_DUPLICATE_TIN` — a `tin_type` of `SSN` or `EIN`, and a `legal_name`. The optional `routing_number` and `account_last4` describe the disbursement account and default to null. The `routing_number` is load-bearing beyond identification: when it is non-null, every payment to this payee disburses by `EFT`; when it is null, payments disburse by `CHECK`.

Private collection agencies are registered by a `TreasurySupervisor` as well, each with a unique `agency_code` — duplicates rejected with `ERR_DUPLICATE_AGENCY_CODE` — a display `name`, and a `capacity_max_active`: a non-negative integer capping how many concurrently open (`INITIATED` or `ACTIVE`) cross-servicing actions the agency will accept.

### 3.2. Exemption Policy Administration

Exemption policies codify, per `payment_type` — one of `VENDOR`, `SALARY`, `BENEFIT_RETIREMENT`, `BENEFIT_DISABILITY`, `TAX_REFUND`, or `GRANT` — how much of a payment is exposed to offset. A `TreasurySupervisor` drafts a policy by choosing an `exemption_class` of `EXEMPT`, `PARTIAL`, or `FULL`, and the class disciplines the remaining fields. A `PARTIAL` policy must carry both a `protected_minimum_cents` floor of zero or more and a `max_offset_pct` fraction greater than zero and at most one. An `EXEMPT` or `FULL` policy must leave both fields absent or null. Violating either conditional rule is `ERR_INVALID_REQUEST`.

A policy begins `DRAFT` and becomes `ACTIVE` through activation by a `TreasurySupervisor`; activating from any state other than `DRAFT` is `ERR_INVALID_STATE`. Drafting is unconstrained: any number of `DRAFT` policies for the same `payment_type` may coexist. Activation supersedes: the incumbent `ACTIVE` policy for the same `payment_type`, if one exists, is immediately `RETIRED`, and `RETIRED` is terminal. Because payment intake requires an `ACTIVE` policy for the payment's type (§3.4), this supersede chain is the mechanism by which offset exposure for a payment type changes over time.

The three classes behave as follows when the offset pool is sized (§3.4 carries the full computation): an `EXEMPT` payment is never offset, a `FULL` payment is exposed up to its entire amount, and a `PARTIAL` payment protects its floor first and caps the eligible fraction second.

### 3.3. Debt Referral, Notice, and Activation

A creditor brings delinquent debt into the program through its own `CreditorAnalyst`: the analyst's `X-User-ID` must equal the `creditor_agency_id` the debt is referred under, so a creditor can only ever refer and manage its own debts — a mismatch is `ERR_FORBIDDEN_FOR_ROLE`, and an unknown creditor id is `ERR_CREDITOR_NOT_FOUND`. The referral carries the `debtor_tin` and `debtor_name` as referred, a `debt_type` of `CHILD_SUPPORT`, `FEDERAL_TAX`, `FEDERAL_NONTAX`, `STATE_TAX`, or `STATE_OTHER`, an `original_amount_cents` strictly greater than zero, and the `delinquent_since` date on which the debt became delinquent. Two optional fields — `notice_sent_at` and `due_process_completed` — may be supplied at referral when the creditor has already run its pre-offset notice; an omitted `due_process_completed` defaults to `false`.

Two bookkeeping values are derived at intake. `current_balance_cents` initializes to the referred `original_amount_cents` and thereafter moves only with collections, restorations, and refund outcomes. `priority_rank` maps from the debt type — `CHILD_SUPPORT` ranks 10, `FEDERAL_TAX` ranks 20, `FEDERAL_NONTAX` ranks 30, `STATE_TAX` ranks 40, and `STATE_OTHER` ranks 50 — and lower ranks offset first in the waterfall (§3.4), with `delinquent_since` as the first tie-break. A third counter, `returned_count`, starts at 0 and records how many times the debt has been pushed back to `RETURNED` by approved refunds (§3.6).

A debt referred with a `notice_sent_at` starts directly in `NOTICED`; without one it starts in `REFERRED`. Recording the notice later — the transition from `REFERRED` to `NOTICED`, performed by the owning creditor's analyst — writes the request's `notice_sent_at` and `due_process_completed` onto the debt and starts the debtor's notice window. The same recording also takes a `RETURNED` debt back to `NOTICED`: re-referral always requires a fresh notice window, so both transitions write fresh values from the request rather than preserving anything old. Attempting to record a notice on a debt in any other state is `ERR_INVALID_STATE`.

Activation turns a `NOTICED` debt offset-eligible (`NOTICED` → `ACTIVE`) and enforces the program's due-process core in one gate. The creditor must have attested `due_process_completed` — otherwise `ERR_DUE_PROCESS_NOT_COMPLETED`. The logical clock must have reached at least thirty days after `notice_sent_at`, with equality activating — an earlier attempt is `ERR_NOTICE_WINDOW_NOT_ELAPSED`. And a `STATE` creditor's debt activates only while an `ACTIVE` reciprocal agreement covers the creditor's `state_code` in the `FED_TO_STATE` or `BIDIRECTIONAL` scope at the current clock — otherwise `ERR_AGREEMENT_NOT_ACTIVE`. A debt in any state other than `NOTICED` cannot be activated at all (`ERR_INVALID_STATE`).

The debt lifecycle is deliberately cyclic. Collection activity moves an `ACTIVE` debt to `IN_COLLECTION` and back (§3.7). A balance driven to exactly zero — by offset application, garnishment collection, or reverse-offset confirmation — moves the debt to `PAID_IN_FULL` from either `ACTIVE` or `IN_COLLECTION`, and when the final collection lands on an open collection action, that action completes alongside. A payment reversal restores balance and reopens a `PAID_IN_FULL` debt to `ACTIVE` (§3.5), while an approved refund instead sends the debt — whatever its status, `ACTIVE`, `IN_COLLECTION`, or `PAID_IN_FULL` — to `RETURNED` without restoring its balance, forcing the creditor to re-validate and re-notice before the debt can offset again (§3.6). `RETURNED` is terminal except for the re-notice path back to `NOTICED`.

For oversight and reconciliation, debts can be listed with optional `creditor_agency_id`, `debtor_tin`, and `status` filters alongside the standard pagination parameters.

### 3.4. Payment Intake and Offset Evaluation

A submitting agency — a `PaymentAgencyAnalyst` — opens a payment file with its free-form, registry-less `agency_code` and the `settlement_date` on which the file's executed payments should settle. The file is born `RECEIVED`; the first payment added to it flips it to `PROCESSING`; and it becomes `COMPLETED` once it holds at least one payment and every payment in it has reached `SETTLED` or `REVERSED`, re-evaluated after any payment transition.

Adding a payment to a file runs a multi-part intake. The payload names the `payee_id` — an unknown payee is `ERR_PAYEE_NOT_FOUND` — and declares a `payee_tin` that must equal the registered payee's own `tin`, with a mismatch rejected as `ERR_PAYEE_TIN_MISMATCH` (422). The `amount_cents` must be strictly greater than zero, and the `payment_type` must have an `ACTIVE` exemption policy, otherwise `ERR_NO_ACTIVE_POLICY`. The parent file must still be `RECEIVED` or `PROCESSING` (`ERR_INVALID_STATE` otherwise), and the payment's `payment_file_id` is taken from the request path rather than the payload. Each accepted payment increments the file's `payment_count`, and the first one drives the file into `PROCESSING` as noted above.

Intake then derives the new payment's character. Its `payment_method` is `EFT` when the payee's `routing_number` is non-null and `CHECK` otherwise. A worst-case projection, `projected_offset_cents`, estimates the offset pool for the submitting agency: under this intake estimate an `EXEMPT` policy projects zero, a `FULL` policy projects the entire amount, and a `PARTIAL` policy projects the amount minus its `protected_minimum_cents`, floored at zero — with neither the percentage cap nor the child-support branch applied, because no match set exists yet. Finally, the do-not-pay scan runs against the payee's TIN: a hit initializes the payment with `integrity_status` `FLAGGED` and `processing_status` `HELD`, while a miss initializes it `CLEAR` and `VERIFIED`. These two axes — `processing_status` (`VERIFIED`, `HELD`, `EVALUATED`, `EXECUTED`, `SETTLED`, `REVERSED`) and `integrity_status` (`CLEAR`, `FLAGGED`) — evolve independently, with exactly two couplings: a do-not-pay hit on a `VERIFIED` payment forces it to `HELD`, and execution is gated on `CLEAR`.

Offset evaluation by a `TreasuryOperator` advances a payment from `VERIFIED` to `EVALUATED`; attempting it from any processing state other than `VERIFIED` or `EVALUATED` is `ERR_INVALID_STATE`. The request must carry the OCC token described in §2.7, and evaluation is repeatable: re-evaluating an `EVALUATED` payment supersedes the prior run — every existing `PROPOSED` offset of the payment drops to `DROPPED`, a fresh match is computed, and the payment's `version` increments with each evaluation.

Matching selects the eligible debts: those `ACTIVE` at the evaluation clock whose `debtor_tin` equals the payment's `payee_tin`, where a state creditor's debt additionally requires an `ACTIVE` covering reciprocal agreement — `FED_TO_STATE` or `BIDIRECTIONAL`, in window at the evaluation clock — while federal debts are eligible outright. The final pool then sizes the exposure precisely: zero for `EXEMPT`; the full payment amount for `FULL`; and, for `PARTIAL`, the lesser of the amount minus the protected minimum (floored at zero) and the amount multiplied by the applicable percentage with the product rounded half up to whole cents — where the applicable percentage is 65 percent whenever any eligible matched debt is of type `CHILD_SUPPORT`, and the policy's own `max_offset_pct` otherwise. This execution-final figure diverges from the intake projection whenever the percentage cap binds below the floor-adjusted base.

Allocation walks the eligible debts ordered by `priority_rank` ascending, then `delinquent_since` ascending, then `created_at` ascending — never the server-minted `id` — with any remaining `created_at` ties broken by creation (insertion) order. Each debt in turn takes the lesser of the remaining pool and its own `current_balance_cents`; every positive take creates a `PROPOSED` offset carrying the `payment_id`, the `debt_id`, a snapshot of the debt's `priority_rank` at proposal time, and the `offset_amount_cents` taken. At proposal the offset's `fee_cents`, `net_remittance_cents`, and `applied_at` remain null — they are fixed only at application. Whatever pool remains after the walk stays with the payee at execution time.

File-level totals follow the pinned rounding order of §2.6: `total_offset_cents` and `total_disbursed_cents` are the plain sums of the per-payment rounded values across the file, and `payment_count` counts the file's payments; all three recompute whenever a payment state change alters them. Payments can be read back individually and listed with optional `payment_file_id`, `payee_id`, `processing_status`, and `integrity_status` filters; offsets are likewise readable individually and listable with optional `payment_id`, `debt_id`, and `status` filters.

### 3.5. Execution, Settlement, and Reversal

Execution by a `TreasuryOperator` turns proposals into money movement (`EVALUATED` → `EXECUTED`). Two gates guard it: the payment must be `EVALUATED` — otherwise `ERR_PAYMENT_NOT_EXECUTABLE` — and its `integrity_status` must be `CLEAR`, otherwise `ERR_DNP_FLAGGED_PAYMENT`. On success, every `PROPOSED` offset of the payment becomes `APPLIED` with `applied_at` stamped to the logical clock; each affected debt's `current_balance_cents` falls by its `offset_amount_cents`, reaching `PAID_IN_FULL` at exactly zero; and each offset's `fee_cents` and `net_remittance_cents` are fixed by the remittance-fee assessment of §2.9, crediting the creditor's ledger net of fee. The payment records its own outcome: `total_offset_cents` sums the applied offsets, `disbursed_cents` is the remainder of `amount_cents` released to the payee, `executed_by_user_id` captures the operator's `X-User-ID` for later segregation-of-duties checks, and `executed_at` stamps the clock. The parent file's totals recompute within the same request.

Settlement is clock-driven rather than request-driven: the sweep of §2.4 moves each `EXECUTED` payment to `SETTLED` once its parent file's `settlement_date` is on or before the clock's UTC date, and a file whose payments have all settled or reversed bubbles up to `COMPLETED`.

When an executed payment is later found improper, a `TreasuryOperator` reverses it (`EXECUTED` → `REVERSED`; attempting the reversal from any other state is `ERR_INVALID_STATE`). Reversal unwinds in three cascaded steps inside one atomic request. First, every `APPLIED` offset of the payment becomes `REVERSED`, each affected debt's `current_balance_cents` is restored by the offset amount, and any debt the offsets had driven to `PAID_IN_FULL` reopens to `ACTIVE`. Second, each affected creditor's ledger is debited symmetrically to §2.9: `remitted_net_total_cents` falls by the offset's `net_remittance_cents` and `remitted_gross_ytd_cents` falls by its `offset_amount_cents`. Third, each affected creditor's `outstanding_receivable_cents` re-derives from the new debt statuses on the next read. On the payment itself, `total_offset_cents` and `disbursed_cents` reset to 0 — the improper disbursement is clawed back from the payee channel outside this API's scope. Reversal is the only path that restores debt balances; the refund path of §3.6 deliberately does not.

### 3.6. Refund Claims and Restitution

A payee who believes an offset was improper gets relief through a refund claim, filed by a `TreasuryOperator` against a specific applied offset. The payload names the `offset_id` — an unknown id is `ERR_OFFSET_NOT_FOUND`, and an offset not in `APPLIED` status is `ERR_OFFSET_NOT_APPLIED` — a `claimed_amount_cents` strictly greater than zero and no more than the offset's `offset_amount_cents`, with any excess rejected as `ERR_REFUND_EXCEEDS_OFFSET` (422), and a `reason` of `DEBT_NOT_OWED`, `AMOUNT_INCORRECT`, `PAYMENT_DUPLICATED`, or `DEBTOR_MISIDENTIFIED`. Timeliness is enforced at filing: the claim must be filed within 180 days of the offset's `applied_at`, and a later filing is `ERR_CLAIM_WINDOW_EXPIRED`. A claim is born `FILED`, and claims can be listed with optional `offset_id` and `status` filters.

Review belongs to an independent `RefundOfficer`. Reviewing moves a claim from `FILED` to `UNDER_REVIEW` — and, on the appeal loop described below, from `APPEALED` back to `UNDER_REVIEW`; any other state is `ERR_INVALID_STATE`. Deciding takes a `decision` of `approve` or `deny` — the uppercase spellings `APPROVE` and `DENY` are accepted identically — and is allowed only from `UNDER_REVIEW`. Segregation of duties is hard: the deciding officer's `X-User-ID` must differ from the `executed_by_user_id` recorded on the payment behind the claimed offset, otherwise `ERR_SEGREGATION_OF_DUTIES` — the officer who decides a claim must never be the operator who executed the offset.

An approval pays the claim (`UNDER_REVIEW` → `PAID`) and runs the restitution cascade. The claimed offset becomes `REFUNDED`. `refund_amount_cents` equals the `claimed_amount_cents` returned to the payee channel. `clawback_cents` — the lesser of the claimed amount and the offset's `net_remittance_cents` — is debited from the creditor's `remitted_net_total_cents`. `treasury_absorbed_cents` is the remainder, the withheld fee that Treasury absorbs, so the refund always conserves: the refunded amount is exactly the clawback plus the absorbed portion. The debt behind the offset moves to `RETURNED` from whatever status it holds — `ACTIVE`, `IN_COLLECTION`, or `PAID_IN_FULL`; an already-`RETURNED` debt simply stays — its `returned_count` increments, and its balance is deliberately not restored: the offset was improper, so the creditor must re-validate the debt and run a fresh notice window before it can offset again. A denial (`UNDER_REVIEW` → `DENIED`) records only the decision. Either way, `decided_by_user_id` and `decided_at` capture who decided and when. One further consequence of a debt's return: any still-`PROPOSED` offsets naming that debt drop to `DROPPED`, since the debt has left offset eligibility. An open collection action on the returned debt is unaffected by the refund and continues under its own lifecycle (§3.7).

A denied claimant gets exactly one appeal, filed by a `TreasuryOperator` (`DENIED` → `APPEALED`): the claim's `appeal_count` must still be 0 — a second appeal is `ERR_APPEAL_LIMIT_REACHED` — and the logical clock must be within thirty days of `decided_at`, with a later appeal rejected as `ERR_APPEAL_WINDOW_EXPIRED`. Appealing increments `appeal_count`, and a fresh review returns the claim to `UNDER_REVIEW` for a second decision under the same segregation-of-duties rule. `PAID` is terminal, and a `DENIED` claim whose single appeal is exhausted or whose window has lapsed is terminal as well.

### 3.7. Collections: Wage Garnishment and Cross-Servicing

Debts that outlive the payment stream go into collection. A `TreasuryOperator` opens a collection action on an `ACTIVE` debt — a debt in any other state is `ERR_INVALID_STATE` — choosing an `action_type` of `AWG` (administrative wage garnishment) or `CROSS_SERVICING` (referral to a private collection agency). Creation flips the debt from `ACTIVE` to `IN_COLLECTION`, which is also why at most one open action exists per debt: the first creation changes the very state every later creation would check. Each action tracks a `collected_total_cents` counter that starts at 0, and actions can be listed with optional `debt_id`, `collection_agency_id`, and `status` filters.

The two action types carry disjoint payloads. `AWG` requires a `notice_sent_at` — the start of the debtor's hearing window — and a `disposable_pay_estimate_cents` of zero or more (a negative value is `ERR_INVALID_REQUEST`); `CROSS_SERVICING` forbids both fields, and mixing them up is `ERR_INVALID_REQUEST`. For `AWG`, creation computes a provisional `projected_per_period_cents`: fifteen percent of the estimated disposable pay, rounded half up to whole cents, with the statutory floor deliberately not applied at projection time. For `CROSS_SERVICING` the projection stays null, and instead the selector assigns the new action's `collection_agency_id` from the ranked eligible pool — the agencies that can still accept another open action under their declared `capacity_max_active`, ranked by registration order (`created_at` ascending, creation order breaking ties), with the first agency in that order receiving the action. An empty pool fails the referral outright with `ERR_NO_COLLECTION_AGENCY_AVAILABLE` and leaves the debt unchanged. An `AWG` action's `collection_agency_id` is always null.

Activation (`INITIATED` → `ACTIVE`) treats the two types asymmetrically. A `CROSS_SERVICING` action activates with no waiting period. An `AWG` action activates only once the logical clock has reached at least fifteen days after its `notice_sent_at` — equality activates, and an earlier attempt is `ERR_AWG_HEARING_WINDOW_OPEN`. Activating from any state other than `INITIATED` is `ERR_INVALID_STATE`.

Collecting on an `ACTIVE` action records a collection event — a self-transition that keeps the action `ACTIVE` — and is OCC-guarded on the debt's version per §2.7; attempting it on an action that is not `ACTIVE` is `ERR_INVALID_STATE`. For `AWG`, the operator supplies the period's actual `disposable_pay_cents` (zero or more; a negative value is `ERR_INVALID_REQUEST`), and the statutory garnishment is the lesser of fifteen percent of that disposable pay (rounded half up to whole cents) and the disposable pay minus a protected weekly floor of 21,750 cents — thirty hours at the $7.25 federal minimum wage — with that subtraction floored at zero. A garnishment that computes to zero is rejected with `ERR_COLLECT_AMOUNT_ZERO`. The collected amount is then the lesser of the garnishment and the debt's `current_balance_cents`. For `CROSS_SERVICING`, the operator instead supplies the agency's `remitted_amount_cents`, which must be greater than zero and no more than the debt's current balance — an excess is `ERR_COLLECT_EXCEEDS_BALANCE` (422) — and that amount is collected as reported.

Every collection mutates three records in one request: the debt's `current_balance_cents` falls by the collected amount and its `version` increments; the creditor's ledger is credited net of the §2.9 remittance fee, tiered on the pre-event year-to-date figure; and the action's `collected_total_cents` grows by the collected amount. A collection that drives the balance to exactly zero completes the loop in the same event — the debt becomes `PAID_IN_FULL` and the action `COMPLETED`. Termination is the manual exit: terminating an `INITIATED` or `ACTIVE` action moves it to `TERMINATED` and, since the terminated action was the only open one, returns the debt to `ACTIVE` — provided the debt is still `IN_COLLECTION`; a debt an approved refund has meanwhile sent to `RETURNED` (§3.6) keeps that status, since `RETURNED` exits only through the re-notice path. Terminating an already-closed action is `ERR_INVALID_STATE`.

### 3.8. State Reciprocity and Reverse Offsets

Reciprocity lets the offset relationship run in both directions. A `TreasurySupervisor` drafts a reciprocal agreement with a `state_code`, a `direction`, and the half-open window described in §2.10. Overlap with an `ACTIVE` agreement of the same state and a conflicting direction scope is rejected at creation with `ERR_AGREEMENT_OVERLAP`, and activation — a `DRAFT`-only transition, otherwise `ERR_INVALID_STATE` — re-checks the same rule so a stale draft cannot slip into conflict. Once `ACTIVE`, coverage runs until the logical clock reaches `effective_until`; there is no terminate operation, and beyond the window the agreement simply covers nothing, so state-debt activations and reverse-offset requests start failing their coverage gates.

The reverse direction starts when a `StateCoordinator` exposes an outgoing state payment, supplying the paying `state_code`, the `payee_tin` about to be paid, and a `requested_amount_cents` strictly greater than zero. The request is honored only while an `ACTIVE` agreement covers that state in the `STATE_TO_FED` or `BIDIRECTIONAL` scope at the current clock — otherwise `ERR_NO_RECIPROCAL_AGREEMENT`. Matching then runs the mirror-image waterfall on the federal side: `ACTIVE` debts of `FEDERAL` creditors whose `debtor_tin` equals the request's `payee_tin`, walked in the same `priority_rank`-then-`delinquent_since`-then-`created_at` order as §3.4, each taking the lesser of the remaining requested amount and its own `current_balance_cents`. The result is a `matches` array pairing each matched `debt_id` with its `matched_amount_cents`, plus the `matched_total_cents` sum. A non-empty result starts the request `MATCHED`; an empty one starts it `NO_MATCH` with a zero total, and `NO_MATCH` is terminal.

A matched request lives ten days: `expires_at` is fixed at creation as exactly ten days after `created_at`. Confirming — the state certifying that it offset its own payment — moves `MATCHED` to `CONFIRMED`, but only while the logical clock is on or before `expires_at`; a late confirm flips the request to `EXPIRED` and fails with `ERR_REQUEST_EXPIRED`. Confirmation applies each match fresh: every matched amount is re-capped to the lesser of its `matched_amount_cents` and the debt's balance at confirmation time, the re-capped amount reduces that balance (reaching `PAID_IN_FULL` at zero), and the federal creditor's ledger is credited net of the §2.9 fee. The request records what actually happened: `applied_total_cents` sums the applied amounts and `confirmed_at` stamps the clock. Confirming a request in any state other than `MATCHED` is `ERR_INVALID_STATE`.

### 3.9. Do-Not-Pay List Administration

A `TreasuryOperator` lists a TIN by creating a do-not-pay record with its `tin`, `list_source`, and the closed interval described in §2.11; interval conflicts on the same `tin` and `list_source` — touching intervals included — are `ERR_DNP_WINDOW_OVERLAP`, and an inverted interval is `ERR_INVALID_REQUEST`. The record is born `ACTIVE`, and creation immediately cascades across the payment population: every not-yet-executed payment whose payee TIN the record now matches is flagged — a `VERIFIED` payment is forced to `HELD` with `integrity_status` `FLAGGED`, while an `EVALUATED` payment is flagged but stays `EVALUATED`, free to be re-evaluated yet barred from execution until cleared.

Removal is the `TreasurySupervisor`'s corrective lever: an `ACTIVE` record becomes `REMOVED` — attempting removal in any other state is `ERR_INVALID_STATE` — and the release cascade runs. Every `HELD` payment whose payee TIN no longer matches any remaining `ACTIVE` record at the current clock returns to `VERIFIED` with `integrity_status` restored to `CLEAR`, and an `EVALUATED` payment that the creation cascade flagged is likewise restored to `CLEAR` in place, remaining `EVALUATED`; a payment that still matches another active record stays held (or flagged), and payments already past execution are untouched by either cascade.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, sweeps, and cascades — return `200 OK`. The API is mounted at the service root with no versioned path prefix; the paths below are complete as written. Request bodies, response payloads, and side effects are defined by the narratives of §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps EXECUTED payments whose file settlement date has arrived into SETTLED | TreasurySupervisor |
| POST | `/creditor-agencies` | Register a creditor agency (federal or state) | TreasurySupervisor |
| GET | `/creditor-agencies/{creditorAgencyId}` | Get a creditor agency including derived ledger fields | All roles |
| POST | `/payees` | Register a payee (unique TIN) | TreasurySupervisor, TreasuryOperator |
| POST | `/exemption-policies` | Create a DRAFT exemption policy for a payment type | TreasurySupervisor |
| POST | `/exemption-policies/{exemptionPolicyId}/activate` | Activate a DRAFT policy, retiring the incumbent ACTIVE policy for the same payment type | TreasurySupervisor |
| POST | `/debts` | Refer a delinquent debt; starts NOTICED when a notice timestamp is supplied, REFERRED otherwise | CreditorAnalyst |
| GET | `/debts/{debtId}` | Get a debt | All roles |
| GET | `/debts` | List debts with filters | All roles |
| POST | `/debts/{debtId}/notice` | Record the creditor's pre-offset notice and due-process attestation (REFERRED or RETURNED to NOTICED) | CreditorAnalyst |
| POST | `/debts/{debtId}/activate` | Make a NOTICED debt offset-eligible after the due-process, notice-window, and reciprocal-agreement gates | CreditorAnalyst |
| POST | `/payment-files` | Submit a payment file (RECEIVED) | PaymentAgencyAnalyst |
| GET | `/payment-files/{paymentFileId}` | Get a payment file including derived totals | All roles |
| POST | `/payment-files/{paymentFileId}/payments` | Add a payment record; payee verification, payment-method determination, do-not-pay scan, and intake projection run at intake | PaymentAgencyAnalyst |
| GET | `/payments/{paymentId}` | Get a payment | All roles |
| GET | `/payments` | List payments with filters | All roles |
| POST | `/payments/{paymentId}/evaluate-offsets` | Run matching and create PROPOSED offsets via the waterfall; re-evaluation supersedes prior proposals; OCC-guarded | TreasuryOperator |
| POST | `/payments/{paymentId}/execute` | Apply PROPOSED offsets, assess remittance fees, disburse the remainder | TreasuryOperator |
| POST | `/payments/{paymentId}/reverse` | Reverse an EXECUTED payment; depth-3 cascade restores offsets, debts, and creditor ledgers | TreasuryOperator |
| GET | `/offsets/{offsetId}` | Get an offset | All roles |
| GET | `/offsets` | List offsets with filters | All roles |
| POST | `/refund-claims` | File a claim that an applied offset was improper; must be within 180 days of the offset's application | TreasuryOperator |
| GET | `/refund-claims/{refundClaimId}` | Get a refund claim | All roles |
| GET | `/refund-claims` | List refund claims with filters | All roles |
| POST | `/refund-claims/{refundClaimId}/review` | Move a FILED or APPEALED claim to UNDER_REVIEW | RefundOfficer |
| POST | `/refund-claims/{refundClaimId}/decide` | Approve (PAID plus clawback cascade) or deny (DENIED) an UNDER_REVIEW claim; segregation of duties enforced | RefundOfficer |
| POST | `/refund-claims/{refundClaimId}/appeal` | Appeal a DENIED claim within 30 days of the decision; at most one appeal | TreasuryOperator |
| POST | `/collection-agencies` | Register a private collection agency | TreasurySupervisor |
| POST | `/debts/{debtId}/collection-actions` | Open an AWG or cross-servicing action on an ACTIVE debt; cross-servicing runs the agency selector; the debt flips to IN_COLLECTION | TreasuryOperator |
| GET | `/collection-actions/{collectionActionId}` | Get a collection action | All roles |
| GET | `/collection-actions` | List collection actions with filters | All roles |
| POST | `/collection-actions/{collectionActionId}/activate` | Activate an INITIATED action; AWG requires the 15-day hearing window to have elapsed | TreasuryOperator |
| POST | `/collection-actions/{collectionActionId}/collect` | Record a collection event (AWG computes the statutory dip; cross-servicing records the agency remittance); OCC-guarded on the debt's version | TreasuryOperator |
| POST | `/collection-actions/{collectionActionId}/terminate` | Terminate an open action; the debt returns to ACTIVE | TreasuryOperator |
| POST | `/reverse-offset-requests` | State requests matching of its outgoing payment against federal debts; requires a covering ACTIVE reciprocal agreement | StateCoordinator |
| POST | `/reverse-offset-requests/{reverseOffsetRequestId}/confirm` | Confirm the state offset; matched amounts are re-capped to current balances and applied to the federal debts | StateCoordinator |
| POST | `/reciprocal-agreements` | Create a reciprocal agreement (DRAFT); half-open window overlap with an ACTIVE agreement of conflicting scope is rejected | TreasurySupervisor |
| POST | `/reciprocal-agreements/{reciprocalAgreementId}/activate` | Activate a DRAFT agreement; the overlap rule is re-checked | TreasurySupervisor |
| POST | `/do-not-pay-records` | List a TIN on a do-not-pay source over a closed interval; touching intervals on the same TIN and source conflict | TreasuryOperator |
| POST | `/do-not-pay-records/{doNotPayRecordId}/remove` | Remove a record; HELD payments with no remaining matching ACTIVE record are released | TreasurySupervisor |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PAYEE_NOT_FOUND` | 404 Not Found |
| `ERR_CREDITOR_NOT_FOUND` | 404 Not Found |
| `ERR_OFFSET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STATE_CODE_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PAYMENT_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_OFFSET_NOT_APPLIED` | 409 Conflict |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUE_PROCESS_NOT_COMPLETED` | 409 Conflict |
| `ERR_NOTICE_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_AWG_HEARING_WINDOW_OPEN` | 409 Conflict |
| `ERR_DNP_FLAGGED_PAYMENT` | 409 Conflict |
| `ERR_CLAIM_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REQUEST_EXPIRED` | 409 Conflict |
| `ERR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_DNP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_TIN` | 409 Conflict |
| `ERR_DUPLICATE_CREDITOR_CODE` | 409 Conflict |
| `ERR_DUPLICATE_AGENCY_CODE` | 409 Conflict |
| `ERR_PAYEE_TIN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_RECIPROCAL_AGREEMENT` | 409 Conflict |
| `ERR_NO_COLLECTION_AGENCY_AVAILABLE` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_OFFSET` | 422 Unprocessable Entity |
| `ERR_COLLECT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_COLLECT_AMOUNT_ZERO` | 422 Unprocessable Entity |
