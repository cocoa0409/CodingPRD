# Card Settlement Holdback Financing API — Product Requirements Document

## 1. Introduction

This platform extends fixed-fee commercial financing to merchants who process card payments on the platform, in the style of Square Loans. Rather than fixed monthly installments, each advance is repaid automatically as a percentage holdback of the merchant's daily card settlement, which aligns repayment pace with the merchant's actual revenue. Eligibility is computed from processing history, seasonality, and account tenure; offers are pre-approved for specific amounts, carry an expiry, and can be re-underwritten when they lapse.

Because the product touches regulated commercial credit, the system embeds compliance machinery end to end: disclosure statements with state-mandated content and cooling-off periods, personal guarantees with a formal enforcement pipeline, delinquency tracking against a minimum-repayment rule, and segregation of duties when loans are sold to funding partner banks. A merchant who begins migrating volume to a rival processor is detected from settlement telemetry and suspended from new offers. Origination is performed through partner banks, with loan sales executed under a reserve-withholding waterfall while the platform retains servicing.

This document is the authoritative requirements specification for the API. Section 2 defines global contracts every endpoint obeys; Section 3 describes business workflows in narrative form; Sections 4 and 5 provide the endpoint and error-code summary tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the caller's role is not among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Both checks run before any resource lookup.

The roles, spelled exactly as the server recognizes them, are:

- `PlatformAdmin` — platform superuser: merchant onboarding, activation, and reinstatement, batch recording, the funding-bank registry, charge-offs, and logical-clock control.
- `Underwriter` — generates, issues, renews, and withdraws loan offers; may not service loans or post sweeps.
- `ServicerAgent` — services loans: finalizes batches, posts and reverses sweeps, settles catch-up payments, activates loans, delivers disclosures, runs period evaluation, and manages enforcement actions and migration signals.
- `MerchantOwner` — the borrowing merchant: accepts its own offers, acknowledges its own disclosures, and initiates catch-up payments on its own loans.
- `GuarantorPrincipal` — the personal guarantor: acknowledges the guarantee.
- `BankOfficer` — funding partner bank officer: quotes, commits, settles, fails, and requotes loan sales.
- `Auditor` — read-only oversight; every role, including `Auditor`, may call any GET endpoint.

Identity semantics differ by role. When `X-User-Role` is `MerchantOwner`, `X-User-ID` is the `id` of the acting `Merchant`; ownership checks on any resource that references a merchant compare the resource's merchant foreign-key field to `X-User-ID`, so a merchant owner can only accept offers addressed to their own merchant, acknowledge disclosures on their own loans, and initiate catch-up payments on their own loans. When `X-User-Role` is `GuarantorPrincipal`, `X-User-ID` is the `id` of the acting `Guarantor`; acknowledgment of a guarantee requires `X-User-ID` to equal that guarantor's `id`. When `X-User-Role` is `PlatformAdmin`, `Underwriter`, `ServicerAgent`, `BankOfficer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `generated_by` on an offer, or as `committed_by_user_id` and `settled_by_user_id` on a loan sale — but does not compare it to any entity's `id`, except where segregation-of-duties rules explicitly compare two recorded operator identifiers (see §3.8).

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

List endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are always sorted by `created_at` ascending. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`, alongside `api_request_id` and `api_request_timestamp`. Most list endpoints additionally accept an optional `status` query parameter that filters results to the named status value, and the cross-entity list endpoints for loans, sweeps, enforcement actions, and sales also accept the foreign-key filters `merchant_id`, `offer_id`, `loan_id`, `batch_id`, `guarantor_id`, and `bank_id` as shown in §4.

Nested URLs identify resources through path parameters named `merchantId`, `batchId`, `offerId`, `loanId`, `guarantorId`, `disclosureId`, `sweepId`, `paymentId`, `actionId`, `signalId`, `bankId`, and `saleId`. When a path nests one resource beneath another, the path parameters are validated left to right — the parent is resolved first, and the first parameter that names a nonexistent resource yields `ERR_NOT_FOUND`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in this API carries a server-minted `id` (a UUID, with no type prefix), a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format refreshed on every mutation, and an integer `version` that starts at 1 and increments by 1 on every mutation of that entity.

All time-gated rules in this document — offer expiry, repayment-period windows, the enforcement demand window, the 24-hour disclosure cooling period, trailing aggregate windows — evaluate against a single logical clock, never against wall-clock time. Before any clock-setting call, the logical clock starts at exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` may advance it by posting a `to_iso8601` instant; once set, the clock remains at the supplied instant until set again, and it never falls back to wall-clock time. Lazy evaluations such as offer expiry, and every clock-gated rule, evaluate against the current logical clock.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents; the server never emits fractional cents. Wherever a computation produces a fractional cent value — the loan fee, a per-day holdback, a sale purchase price, a reserve withholding — it is rounded half-up to whole cents. Ratios and rates (`seasonality_index`, `trailing_30d_chargeback_ratio`, `drop_ratio`, `apr_scheduled`, `apr_projected`) are carried at four decimal places, rounded half-up. Flooring operations — pre-approval rounding to the nearest $500 step and the per-period minimum — round down to a whole multiple or whole cents as specified in §3. Boundary comparisons are pinned per rule: the repayment-period minimum is met when paid is greater than or equal to the minimum (inclusive), the migration volume-drop threshold is inclusive, and the chargeback-spike threshold is strict (strictly greater than).

### 2.6. Optimistic Concurrency Control

Two write endpoints require the caller to prove they observed the current state of a parent entity before writing:

- Accepting an offer requires `expected_merchant_version` in the request body, carrying the caller's last-observed `version` of the target merchant. If the merchant's current `version` does not match — because, for example, another writer accepted an offer in the meantime, setting `active_loan_id` and superseding the caller's view — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Posting a settlement sweep against a loan requires `expected_loan_version` in the request body, carrying the caller's last-observed `version` of that loan. Because a sweep mutates `remaining_balance_cents`, a caller holding a stale balance view must re-read the loan before posting the next sweep; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.7. Validation Order

When a request violates several rules at once, the checks run in a fixed priority order so the surfaced error is deterministic. First, authentication: the presence and shape of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Second, existence: path-referenced resources are resolved left to right — merchant, then offer, loan, batch, sale, signal, disclosure, guarantor, action, bank, sweep, payment — and the first missing one yields `ERR_NOT_FOUND`. Third, optimistic-concurrency checks (`ERR_STALE_VERSION`). Fourth, state-permission checks — whether the target resource's state allows the operation, including offer expiry against the clock, merchant eligibility and suspension gates, batch-already-swept, bank-inactive, loan active/terminal gates, and the single-active-loan gate. Fifth, regulatory disclosure gates on activation and acknowledgment. Sixth, uniqueness, overlap, and segregation-of-duties constraints. Seventh, cross-entity referential state (guarantor active before activation; batch finalized before sweeping). Eighth, fiscal limits (principal within pre-approval, catch-up within outstanding balance, volume minimums). Ninth, time-based gates (period fully elapsed, tenure minimum). Tenth and last, request-body shape — required fields present, enum values valid, cents non-negative integers, `state_code` two uppercase letters — reported as `ERR_INVALID_REQUEST`.

### 2.8. Ledger Principles and Compensating Reversals

Every loan maintains a double-entry-style ledger view: `remaining_balance_cents` starts at the loan's total repayment obligation and falls as value is applied; `paid_to_date_cents` starts at zero and rises by the same amounts. The two always move together — the sum of applied sweeps, applied catch-up payments, and enforcement draws equals `paid_to_date_cents`, and `total_repayment_cents` minus that same sum equals `remaining_balance_cents`. Reversals are compensating, never deletions: reversing a sweep or a catch-up payment restores the loan's balances by exactly the reversed amount and leaves the original record in place with terminal status. A loan's `version` increments whenever a sweep posts, a catch-up settles, a draw lands, or a reversal restores balances.

## 3. Business Logic & Workflows

### 3.1. Merchant Onboarding, Processing History, and Eligibility

A `PlatformAdmin` onboards a merchant by supplying `legal_name`, the two-letter uppercase US state code of the principal place of business as `state_code` (this drives the disclosure mandate described in §3.3), the primary owner's full name as `owner_name`, and `processing_started_at`, the UTC timestamp of the merchant's first card payment on the platform, which anchors tenure. A new merchant enters `ONBOARDING` status with all aggregates zeroed: `lifetime_net_cents`, `trailing_12m_months_recorded`, `trailing_30d_net_cents`, and `prior_30d_net_cents` are zero, `seasonality_index` and `trailing_30d_chargeback_ratio` are zero, `loans_repaid_count` is 0, and `active_loan_id` is null.

Day-to-day card volume enters the system as daily settlement batches. A `PlatformAdmin` or `ServicerAgent` records a batch for a merchant with `processing_date` (a calendar date, unique per merchant — a second batch for the same merchant and date is rejected with `ERR_DUPLICATE_PROCESSING_DATE`), `gross_cents`, and optionally `refunds_cents` and `chargebacks_cents`, which both default to 0. At creation the batch is `OPEN` and its `net_settled_cents` is computed as gross minus refunds minus chargebacks.

An `OPEN` batch becomes `FINALIZED` when a `ServicerAgent` finalizes it. Finalization is the moment a batch begins to count: the merchant's aggregates are recomputed from the full set of the merchant's batches in `FINALIZED` or `SWEPT` status, and the merchant's `version` increments. The aggregate definitions are pinned as follows, all windows anchored at the logical clock: `lifetime_net_cents` is the sum of `net_settled_cents` over every included batch. The trailing-12-month set is included batches whose `processing_date` falls within the closed window from 365 days before the clock through the clock; grouping that set by calendar month of `processing_date` yields one monthly net figure per month, `trailing_12m_months_recorded` counts the distinct months present, and the average monthly net is the sum of monthly nets divided by that count, kept exact until used. `seasonality_index` is the difference between the largest and smallest monthly net, divided by the average monthly net, carried at four decimal places rounded half-up — and defined as 0 when no trailing-12-month months are recorded. `trailing_30d_net_cents` sums included batches whose `processing_date` falls in the half-open window from 30 days before the clock up to but not including the clock; `prior_30d_net_cents` does the same for the half-open window from 60 days before the clock up to but not including 30 days before the clock. `trailing_30d_chargeback_ratio` is the sum of `chargebacks_cents` over the trailing 30-day window divided by `trailing_30d_net_cents`, at four decimal places rounded half-up, and 0 when that net sum is 0.

A merchant in `ONBOARDING` is activated by a `PlatformAdmin`, moving it to `ELIGIBLE`, only when two minimums both hold at that moment: the merchant has at least 365 days of tenure — the clock minus `processing_started_at` is no less than 365 days, otherwise `ERR_MERCHANT_TENURE_INSUFFICIENT` — and `lifetime_net_cents` is at least 10000000 cents ($100,000 of lifetime net settled volume), otherwise `ERR_MERCHANT_VOLUME_INSUFFICIENT`. Activation recomputes the merchant's aggregates from the `FINALIZED` and `SWEPT` batch set as part of the same operation.

Suspension is the inverse state and arrives only through cascades: confirming a processor-migration signal (§3.7) or a loan reaching delinquency or default (§3.5) moves an `ELIGIBLE` merchant to `SUSPENDED`. While a merchant is `SUSPENDED`, new offer generation for that merchant is blocked with `ERR_MERCHANT_SUSPENDED`; existing loans are unaffected. Reinstatement is always an explicit `PlatformAdmin` action that returns the merchant from `SUSPENDED` to `ELIGIBLE` — clearing a migration signal does not reinstate the merchant by itself.

### 3.2. Offer Underwriting, Issuance, Renewal, and Acceptance

An `Underwriter` generates a pre-approved offer for a merchant. Generation is gated: the merchant must be `ELIGIBLE` — an `ONBOARDING` merchant yields `ERR_MERCHANT_NOT_ELIGIBLE`, a `SUSPENDED` one yields `ERR_MERCHANT_SUSPENDED` — and the merchant must have recorded processing in all twelve trailing months: `trailing_12m_months_recorded` must be at least 12, otherwise `ERR_MERCHANT_VOLUME_INSUFFICIENT`. The offer is born in `DRAFT` status with `renewal_count` 0 and `generated_by` recording the underwriter's `X-User-ID`.

Generation computes two pre-approval variants from the merchant's current aggregates, snapshots them onto the offer, and selects one. First the average monthly net over the trailing twelve months is taken exactly, then truncated to whole cents, and multiplied by 1.25 to form the base amount. The STANDARD variant applies no haircut: `preapproved_standard_cents` is the base amount floored down to the nearest whole multiple of 50000 cents (a $500 step). The CONSERVATIVE variant applies a 0.70 haircut before the same flooring: `preapproved_conservative_cents` is the base multiplied by 0.70, floored to the same $500 step. The selected `preapproved_cents` is the CONSERVATIVE amount when `seasonality_index` — the four-decimal rounded value — exceeds 0.75, and the STANDARD amount otherwise; identical processing history therefore yields a lower pre-approval for a seasonal merchant. The offer also snapshots `trailing_12m_avg_net_cents` (the average monthly net at generation time) and `seasonality_index_at_generation` (the merchant's seasonality index at that moment).

An offer in `DRAFT` — or, after a renewal cycle, in `REUNDERWRITING` — is issued by an `Underwriter`, moving it to `OFFERED`. Issuance stamps `issued_at` with the clock and sets `expires_at` to exactly 30 days later; the acceptance window is the half-open interval starting at `issued_at` and ending just before `expires_at`. Issuance is refused with `ERR_OFFER_OVERLAP_ACTIVE` when any other offer for the same merchant is currently `OFFERED` — validity windows being half-open, an offer whose expiry has not yet arrived still blocks. Note that generation is permitted while another offer is `OFFERED`; the overlap constraint bites at issue time.

Expiry is lazy: there is no background job. Whenever an `OFFERED` offer is read, renewed, or accepted and the clock has reached `expires_at`, the offer transitions to `EXPIRED` at that moment. Acceptance attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`.

An `EXPIRED` offer may be re-underwritten by an `Underwriter`, moving it to `REUNDERWRITING`; an offer still in `OFFERED` whose clock has passed `expires_at` may be renewed directly, treated as passing through `EXPIRED`. Re-underwriting recomputes `trailing_12m_avg_net_cents`, `seasonality_index_at_generation`, `preapproved_standard_cents`, `preapproved_conservative_cents`, and the selected `preapproved_cents` from the merchant's current aggregates — the same computation as generation — and increments `renewal_count` by 1. A renewed offer can then be issued again, carrying refreshed amounts and a fresh 30-day window. An `Underwriter` may also withdraw an offer from any non-terminal pre-acceptance state — `DRAFT`, `OFFERED`, `EXPIRED`, or `REUNDERWRITING` — moving it to `WITHDRAWN`. `ACCEPTED` and `WITHDRAWN` are terminal.

Acceptance is performed by the `MerchantOwner` of the merchant the offer addresses. The acceptance payload carries `selected_principal_cents`, `accepted_holdback_pct`, `guarantor_full_name`, `guarantor_email`, `guarantee_cap_cents`, and the OCC field `expected_merchant_version` described in §2.6. Acceptance enforces five checks, all rejected with HTTP 409 except the OCC check: the offer must be within its half-open window (`ERR_OFFER_EXPIRED` at or after `expires_at`); `expected_merchant_version` must match the merchant's current `version` (`ERR_STALE_VERSION`, HTTP 412); the merchant must not already carry a non-terminal loan — `active_loan_id` must be null, else `ERR_MERCHANT_HAS_ACTIVE_LOAN`; the chosen `accepted_holdback_pct` must be one of the offered holdback options 0.08, 0.10, or 0.14, else `ERR_HOLDBACK_PCT_NOT_OFFERED`; and `selected_principal_cents` must not exceed the offer's selected `preapproved_cents`, else `ERR_OFFER_AMOUNT_EXCEEDS_PREAPPROVED`.

A successful acceptance moves the offer to `ACCEPTED` and stamps `accepted_principal_cents`, `accepted_holdback_pct`, and `accepted_loan_id`. Three records are created in the same operation: a `Loan` (its initial status is `PENDING_DISCLOSURE` when the merchant's `state_code` at this moment is CA, NY, UT, or VA, otherwise `PENDING_ACK`), a `Guarantor` in `LINKED` status, and a `DisclosureStatement` in `GENERATED` status carrying both APR variants. The merchant's `active_loan_id` is set to the new loan and the merchant's `version` increments by 1.

### 3.3. Loan Activation: Guarantees and Disclosure Gates

The loan created at acceptance records `merchant_id` and `offer_id` as its origins, `principal_cents` equal to the accepted principal, and `holdback_pct` equal to the accepted holdback fraction of daily net settlement. Its fee and repayment schedule are computed in a pinned evaluation order — principal first, then fee rate, then fee, then total, then the per-period minimum — so that the apparently circular dependency is made explicit. The tiered `fee_rate` is 0.11 when `principal_cents` is at most 2500000 cents, 0.13 when it is at most 10000000 cents, and 0.15 above that. `fee_cents` is the principal multiplied by the fee rate, rounded half-up to whole cents. `total_repayment_cents` is principal plus fee. `per_period_minimum_cents` — the minimum due per 60-day repayment period — is `total_repayment_cents` divided by 18, floored to whole cents. `remaining_balance_cents` initializes to `total_repayment_cents`, `paid_to_date_cents` to 0, `repayment_period_index` to 0, `consecutive_missed_periods` to 0, `carried_surplus_cents` to 0, `cumulative_shortfall_cents` to 0, and `servicing_retained` to true. The loan's `disclosure_required` flag is true when the merchant's `state_code` at acceptance is one of CA, NY, UT, or VA. `activated_at` stays null until activation.

Two gates must clear before a `ServicerAgent` can activate the loan, and they differ by mandate. The guarantee gate is identical for both paths: the loan's guarantor must be `ACTIVE`, otherwise activation is rejected with `ERR_GUARANTOR_NOT_ACTIVE`. The disclosure gate depends on `disclosure_required`. For a mandate-state loan (`PENDING_DISCLOSURE`), the disclosure statement must be `ACKNOWLEDGED`, otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`. For a non-mandate loan (`PENDING_ACK`), the disclosure statement must be at least `DELIVERED` — `DELIVERED` or `ACKNOWLEDGED` both pass — otherwise `ERR_DISCLOSURE_NOT_DELIVERED`. Activation stamps `activated_at` with the clock, sets `repayment_period_index` to 0, and moves the loan to `ACTIVE`. Repayment period p covers the half-open window from `activated_at` plus 60p days up to `activated_at` plus 60 times (p+1) days.

The guarantor record created at acceptance carries `loan_id`, the supplied `full_name`, `email`, and `guarantee_cap_cents` — the maximum amount enforceable under the personal guarantee. It begins `LINKED` with `acknowledged_at` null. The guarantee becomes enforceable when the `GuarantorPrincipal` acknowledges it: the caller's `X-User-ID` must equal the guarantor's `id`, and acknowledgment stamps `acknowledged_at` and moves the guarantor to `ACTIVE`.

The disclosure statement is generated at acceptance with both APR variants computed, regardless of mandate. `apr_scheduled` is the loan's `fee_rate` multiplied by 365 over a scheduled term of 1080 days, at four decimal places rounded half-up. `apr_projected` projects the term from the merchant's recent pace: the daily pace is the sum of `net_settled_cents` over the merchant's `FINALIZED` and `SWEPT` batches whose `processing_date` falls in the closed 90-day window ending on the acceptance day, divided by 90, then multiplied by `holdback_pct`. When that daily pace is zero or negative, the projected term is the scheduled 1080 days; otherwise `estimated_term_days` under projection is the total repayment divided by the daily pace, rounded up to a whole number of days, and `apr_projected` is `fee_rate` multiplied by 365 over that projected term, at four decimal places rounded half-up. Because a faster pace shortens the projected term, a mandate-state disclosure shows a higher APR-equivalent for identical loan terms than the scheduled variant would. `disclosed_apr_basis` is `PROJECTED` when the loan's `disclosure_required` is true (mandate states CA, NY, UT, VA) and `SCHEDULED` otherwise, and `estimated_term_days` is the projected term in mandate states and 1080 days otherwise. The statement's `mandate_state` mirrors the loan's `disclosure_required`, and `cooling_required` is true exactly when `mandate_state` is true.

A `ServicerAgent` delivers the statement, moving it from `GENERATED` to `DELIVERED` and stamping `delivered_at`. The `MerchantOwner` of the loan's merchant then acknowledges it — `X-User-ID` must equal the loan's `merchant_id` — moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`. When `cooling_required` is true, acknowledgment is only allowed at or after 24 hours past `delivered_at`; an earlier attempt is rejected with `ERR_DISCLOSURE_COOLING_NOT_ELAPSED`. In non-mandate states no cooling applies, and activation does not require acknowledgment at all — delivery suffices.

### 3.4. Daily Holdback Sweeps and the Loan Balance Ledger

Repayment flows through the daily settlement stream. When a `ServicerAgent` posts a sweep against a loan, the request names a `batch_id` and carries `expected_loan_version` per §2.6. The referenced batch must belong to the loan's merchant and be in `FINALIZED` status — a batch still `OPEN` or otherwise not finalized is rejected with `ERR_BATCH_NOT_FINALIZED`, and a batch already swept by a non-reversed sweep is rejected with `ERR_BATCH_ALREADY_SWEPT`. The loan must be `ACTIVE` or `DELINQUENT`; a sweep against a loan still in a pending state is rejected with `ERR_LOAN_NOT_ACTIVE`, and against a terminal loan with `ERR_LOAN_ALREADY_TERMINAL`.

The holdback amount follows a pinned rounding order: round per day, then accumulate. The raw holdback is the batch's `net_settled_cents` multiplied by the loan's `holdback_pct`; that product is rounded half-up to whole cents for that day — never aggregated over a week and then rounded, which would yield different cents. The posted `holdback_cents` is then the smaller of that daily figure and the loan's current `remaining_balance_cents`; when the raw daily figure exceeded the remaining balance, the sweep's `clipped` flag is true. The sweep records `loan_id`, `batch_id`, and `swept_date` — the `processing_date` of the swept batch, which determines which repayment period the payment is attributed to. The new sweep is born `APPLIED` with `reversed_at` null; the batch cascades from `FINALIZED` to `SWEPT`; the loan's `remaining_balance_cents` falls and `paid_to_date_cents` rises by `holdback_cents`; and the loan's `version` increments by 1. If the remaining balance reaches zero, the repayment cascade of §3.5 fires.

Reversing an `APPLIED` sweep is a `ServicerAgent` operation permitted only while the loan is `ACTIVE` or `DELINQUENT` — on a terminal loan it is rejected with `ERR_LOAN_ALREADY_TERMINAL`. Reversal is compensating: the sweep moves to `REVERSED` with `reversed_at` stamped, the loan's `remaining_balance_cents` rises and `paid_to_date_cents` falls by exactly the sweep's `holdback_cents`, and the batch returns from `SWEPT` to `FINALIZED`.

### 3.5. Repayment Periods, Minimums, Catch-Ups, Delinquency, and Default

Although repayment is continuous, the loan is evaluated against a minimum-payment rule every 60 days. A `ServicerAgent` closes the current period by requesting period evaluation. Evaluation requires the period to have fully elapsed: the clock must have reached `activated_at` plus 60 times the current `repayment_period_index` plus one days — otherwise `ERR_PERIOD_NOT_ELAPSED`.

The evaluation sums what was paid in the closing period: the `holdback_cents` of `APPLIED` sweeps whose `swept_date` falls inside the period's half-open window, plus the portions of `APPLIED` catch-up payments whose `period_index_credited` equals the current period index that exceed shortfall reduction (see the application order below). Adding any `carried_surplus_cents` from the prior period yields the effective paid figure. When effective paid is greater than or equal to `per_period_minimum_cents` — the boundary is inclusive — the period is MET: the excess over the minimum becomes the new `carried_surplus_cents`, and `consecutive_missed_periods` resets to 0. When effective paid falls short, `consecutive_missed_periods` increments by 1, the shortfall (minimum minus effective paid) is added to `cumulative_shortfall_cents`, and `carried_surplus_cents` resets to 0. Either way, `repayment_period_index` then increments by 1.

Misses cascade. When `consecutive_missed_periods` reaches 2, the loan moves from `ACTIVE` to `DELINQUENT` and the merchant cascades to `SUSPENDED`, blocking new offer creation. When it reaches 4, the loan moves to `DEFAULTED` and an `EnforcementAction` is created in `DRAFT` referencing the loan and its guarantor; the merchant remains `SUSPENDED`. Curing works in reverse: when a `DELINQUENT` loan evaluates a period as MET and `cumulative_shortfall_cents` is 0, the loan returns to `ACTIVE` and `consecutive_missed_periods` resets — but the merchant stays `SUSPENDED` until a `PlatformAdmin` explicitly reinstates it.

A merchant can also pay down the loan out of band. The `MerchantOwner` initiates a catch-up payment with an `amount_cents`, creating it in `INITIATED` status. A `ServicerAgent` settles it — permitted while the loan is `ACTIVE`, `DELINQUENT`, or `DEFAULTED`, else `ERR_LOAN_ALREADY_TERMINAL` — provided the amount does not exceed the loan's `remaining_balance_cents`, else `ERR_CATCHUP_EXCEEDS_OUTSTANDING`. Settlement moves the payment to `APPLIED`, stamps `period_index_credited` with the loan's current `repayment_period_index`, reduces `remaining_balance_cents` and increases `paid_to_date_cents` by `amount_cents`, and applies the amount shortfall-first: it reduces `cumulative_shortfall_cents` before any excess counts toward the current period's minimum evaluation. A `ServicerAgent` may instead mark an `INITIATED` payment `FAILED`. Reversing an `APPLIED` payment is compensating — the payment moves to `REVERSED`, balances are restored by the reversed amount, and the shortfall and period attribution are unwound — and is blocked on a `REPAID` or `CHARGED_OFF` loan with `ERR_LOAN_ALREADY_TERMINAL`.

A loan reaches `REPAID` automatically the moment `remaining_balance_cents` reaches zero, from any of `ACTIVE`, `DELINQUENT`, or `DEFAULTED` — via a sweep, a catch-up, or an enforcement draw. The repayment cascade clears the merchant's `active_loan_id`, increments `loans_repaid_count` by 1, and increments the merchant's `version`; and when the merchant's status is `ELIGIBLE` at that moment, a renewal offer is auto-created in `DRAFT` with freshly recomputed pre-approval amounts. For a `DEFAULTED` loan, the cascade additionally releases any open enforcement action for the loan. A `DEFAULTED` loan that will not recover may instead be charged off by a `PlatformAdmin`, moving it to `CHARGED_OFF`; charge-off clears the merchant's `active_loan_id` and releases any open enforcement action for the loan. `REPAID` and `CHARGED_OFF` are the loan's terminal states.

### 3.6. Personal Guarantee Enforcement

Enforcement against a defaulted loan's guarantor proceeds through a formal pipeline on the `EnforcementAction`, which references the loan via `loan_id` and the guarantor via `guarantor_id`. The action is created in `DRAFT` by the default cascade of §3.5.

A `ServicerAgent` issues a demand, moving the action from `DRAFT` to `DEMANDED` and stamping `demanded_at`; `window_end` is set to exactly 30 days after the demand. Demands are mutually exclusive per guarantor identity across loans: a demand is rejected with `ERR_ENFORCEMENT_WINDOW_OPEN` when any other action exists whose guarantor has the same `email`, in `DEMANDED` or `ESCALATED` status, whose closed window from its `demanded_at` through its `window_end` contains the current clock. After the window closes — the clock has reached `window_end` — the action may be escalated from `DEMANDED` to `ESCALATED`; an early escalation is rejected with `ERR_INVALID_STATE_TRANSITION`.

Drawing on the guarantee is permitted only from `ESCALATED` and only while the loan is `DEFAULTED`, else `ERR_INVALID_STATE_TRANSITION`. The draw amount `draw_amount_cents` is the smaller of the loan's `remaining_balance_cents` and the guarantor's `guarantee_cap_cents` at draw time; it is applied to the loan exactly like a catch-up settlement — `remaining_balance_cents` falls and `paid_to_date_cents` rises by the drawn amount — and the guarantor cascades from `ACTIVE` to `ENFORCED`. If the draw brings the remaining balance to zero, the repayment cascade fires: the loan becomes `REPAID` and the merchant side effects of §3.5 follow.

Release is the pipeline's exit. A `ServicerAgent` may release an action from `DRAFT`, `DEMANDED`, `ESCALATED`, or `DRAWN` once the loan is `REPAID` or `CHARGED_OFF` — otherwise `ERR_INVALID_STATE_TRANSITION`. When no other non-terminal enforcement action references the same guarantor, release cascades the guarantor to `RELEASED` — from `ACTIVE` when the action is released without a draw and the loan is terminal, or from `ENFORCED` after a draw once the loan is terminal. `DRAWN` and `RELEASED` are the action's terminal states; `RELEASED` is likewise the guarantor's terminal state.

### 3.7. Processor-Migration Risk Monitoring

A borrower quietly moving card volume to another processor starves the holdback, so the platform evaluates migration risk on demand. A `ServicerAgent` requests an evaluation for a merchant; the merchant must be `ELIGIBLE`, otherwise `ERR_MERCHANT_NOT_ELIGIBLE`, and evaluation is refused with `ERR_MIGRATION_SIGNAL_OPEN` while any signal for the merchant is in `DETECTED` or `CONFIRMED` status.

The evaluation computes a `drop_ratio`: one minus the ratio of `trailing_30d_net_cents` to `prior_30d_net_cents`, at four decimal places rounded half-up, and 0 when the prior window's net is 0. Two variant verdicts are computed. The VOLUME_ONLY diagnostic variant — reported on the signal as `volume_only_would_trigger` — is true when the drop ratio is at least 0.60 (inclusive) and the trailing 30-day net is strictly above 0. The active VOLUME_AND_CHARGEBACK variant — reported as `triggered` — is true when the volume-only condition holds or the `trailing_30d_chargeback_ratio` is strictly above 0.03, so a chargeback spike alone triggers even when the volume drop is below threshold. A `MigrationSignal` row is created in `DETECTED` status — with `merchant_id` attached and `evaluated_at` stamped — only when `triggered` is true; when it is false, no row is created, the response reports `triggered` as false inline, and listing the merchant's migration signals returns an empty array for that evaluation.

A `DETECTED` signal can be confirmed or dismissed by a `ServicerAgent`. Confirmation moves it to `CONFIRMED` and cascades the merchant to `SUSPENDED`, blocking new offer creation while leaving existing loans untouched. Dismissal moves it to `DISMISSED`. A confirmed signal is later cleared — `CONFIRMED` to `CLEARED` — but clearing does not reinstate the merchant; reinstatement is the separate explicit `PlatformAdmin` action of §3.1. `CLEARED` and `DISMISSED` are terminal.

### 3.8. Bank Funding, Loan Sales, and Servicing Retention

Origination runs through funding partner banks. A `PlatformAdmin` registers a bank with its `legal_name` and `purchase_discount_pct` — the discount off remaining balance the bank takes when purchasing a loan; the bank starts `ACTIVE` with `committed_exposure_cents` 0. Suspending a bank moves it to `SUSPENDED`, after which any new sale quote, commit, settle, or requote against it is rejected with `ERR_BANK_INACTIVE`.

The sale lifecycle is driven by `BankOfficer` operators. Quoting a sale of a loan to a bank takes a `bank_id` and creates a `LoanSale` in `QUOTED` status with `purchase_price_cents` computed as the loan's current `remaining_balance_cents` multiplied by one minus the bank's `purchase_discount_pct`, rounded half-up to whole cents. Committing the quote — permitted only while the bank is `ACTIVE`, else `ERR_BANK_INACTIVE` — moves the sale to `COMMITTED`, records the committing operator's `X-User-ID` as `committed_by_user_id`, and adds `purchase_price_cents` to the bank's `committed_exposure_cents`.

Settlement enforces segregation of duties: the settling operator's `X-User-ID` must differ from `committed_by_user_id`, otherwise `ERR_SOD_SAME_USER`. Settlement additionally requires the loan to be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`) and the bank to be `ACTIVE` (`ERR_BANK_INACTIVE`). Settlement applies a two-bucket waterfall over the purchase price, reserve first: `reserve_withheld_cents` is the purchase price multiplied by 0.05, rounded half-up, and `bank_remittance_cents` is the remainder — purchase price minus reserve — so reserve and remittance always sum exactly to the purchase price. Settlement moves the sale to `SETTLED`, records the settling operator as `settled_by_user_id`, releases the bank's committed exposure by subtracting `purchase_price_cents` from `committed_exposure_cents`, and leaves the loan's `servicing_retained` flag true — the platform continues to service the loan even after a settled sale.

A committed sale that cannot close is failed, moving to `FAILED` and compensating the bank's `committed_exposure_cents` by subtracting `purchase_price_cents`. A failed sale may be requoted — bank must be `ACTIVE`, else `ERR_BANK_INACTIVE` — returning it to `QUOTED` with `purchase_price_cents` recomputed from the loan's current remaining balance, which may have moved since the original quote. `SETTLED` and `FAILED` are the sale's terminal states.

## 4. Endpoint Definitions

New resources are returned with HTTP 201 on creation; modifications to existing resources return HTTP 200. The API is mounted under the `/lending` prefix, with the clock control endpoint mounted separately.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-09-01T00:00:00Z; never falls back to wall clock) | PlatformAdmin |
| POST | `/lending/merchants` | Onboard a merchant | PlatformAdmin |
| GET | `/lending/merchants/{merchantId}` | Get a merchant | All roles |
| GET | `/lending/merchants` | List merchants with pagination | All roles |
| POST | `/lending/merchants/{merchantId}/activate` | Activate a merchant after tenure and volume minimums | PlatformAdmin |
| POST | `/lending/merchants/{merchantId}/reinstate` | Reinstate a suspended merchant | PlatformAdmin |
| POST | `/lending/merchants/{merchantId}/processing_batches` | Record a daily card settlement batch (unique per merchant and date) | PlatformAdmin, ServicerAgent |
| POST | `/lending/processing_batches/{batchId}/finalize` | Finalize a batch; recompute merchant aggregates | ServicerAgent |
| GET | `/lending/processing_batches/{batchId}` | Get a batch | All roles |
| GET | `/lending/merchants/{id}/processing_batches` | List a merchant's batches | All roles |
| POST | `/lending/merchants/{merchantId}/offers` | Generate a pre-approved offer (computes STANDARD and CONSERVATIVE variants) | Underwriter |
| POST | `/lending/offers/{offerId}/issue` | Issue an offer, starting the 30-day window | Underwriter |
| POST | `/lending/offers/{offerId}/withdraw` | Withdraw an offer | Underwriter |
| POST | `/lending/offers/{offerId}/renew` | Re-underwrite an expired offer | Underwriter |
| POST | `/lending/offers/{offerId}/accept` | Merchant accepts an offer; creates loan, guarantor, disclosure | MerchantOwner |
| GET | `/lending/offers/{offerId}` | Get an offer | All roles |
| GET | `/lending/merchants/{id}/offers` | List a merchant's offers | All roles |
| GET | `/lending/loans/{loanId}` | Get a loan | All roles |
| GET | `/lending/loans` | List loans (filtered) | All roles |
| GET | `/lending/merchants/{id}/loans` | List a merchant's loans | All roles |
| POST | `/lending/loans/{loanId}/activate` | Activate a loan after disclosure and guarantee gates | ServicerAgent |
| POST | `/lending/loans/{loanId}/charge_off` | Charge off a defaulted loan | PlatformAdmin |
| POST | `/lending/loans/{loanId}/evaluate_period` | Close the current 60-day repayment period and apply minimum-payment rules | ServicerAgent |
| GET | `/lending/guarantors/{guarantorId}` | Get a guarantor | All roles |
| GET | `/lending/loans/{id}/guarantors` | List a loan's guarantors (0 or 1) | All roles |
| POST | `/lending/guarantors/{guarantorId}/acknowledge` | Guarantor acknowledges the personal guarantee | GuarantorPrincipal |
| GET | `/lending/disclosures/{disclosureId}` | Get a disclosure statement | All roles |
| GET | `/lending/loans/{id}/disclosures` | List a loan's disclosure statements | All roles |
| POST | `/lending/disclosures/{disclosureId}/deliver` | Deliver a disclosure to the merchant | ServicerAgent |
| POST | `/lending/disclosures/{disclosureId}/acknowledge` | Merchant acknowledges a disclosure (24h cooling in mandate states) | MerchantOwner |
| POST | `/lending/loans/{loanId}/sweeps` | Post the holdback sweep for a finalized batch against a loan | ServicerAgent |
| GET | `/lending/sweeps/{sweepId}` | Get a sweep | All roles |
| GET | `/lending/loans/{id}/sweeps` | List a loan's sweeps | All roles |
| GET | `/lending/sweeps` | List sweeps (filtered) | All roles |
| POST | `/lending/sweeps/{sweepId}/reverse` | Reverse an applied sweep (compensating) | ServicerAgent |
| POST | `/lending/loans/{loanId}/catch_up_payments` | Merchant initiates an out-of-band catch-up payment | MerchantOwner |
| POST | `/lending/catch_up_payments/{paymentId}/settle` | Settle and apply a catch-up payment | ServicerAgent |
| POST | `/lending/catch_up_payments/{paymentId}/fail` | Mark a catch-up payment failed | ServicerAgent |
| POST | `/lending/catch_up_payments/{paymentId}/reverse` | Reverse an applied catch-up payment | ServicerAgent |
| GET | `/lending/catch_up_payments/{paymentId}` | Get a catch-up payment | All roles |
| GET | `/lending/loans/{id}/catch_up_payments` | List a loan's catch-up payments | All roles |
| POST | `/lending/enforcement_actions/{actionId}/demand` | Issue a demand on the personal guarantee | ServicerAgent |
| POST | `/lending/enforcement_actions/{actionId}/escalate` | Escalate an unpaid demand after its 30-day window | ServicerAgent |
| POST | `/lending/enforcement_actions/{actionId}/draw` | Draw on the personal guarantee | ServicerAgent |
| POST | `/lending/enforcement_actions/{actionId}/release` | Release an enforcement action once the loan is terminal | ServicerAgent |
| GET | `/lending/enforcement_actions/{actionId}` | Get an enforcement action | All roles |
| GET | `/lending/loans/{id}/enforcement_actions` | List a loan's enforcement actions | All roles |
| GET | `/lending/enforcement_actions` | List enforcement actions (filtered) | All roles |
| POST | `/lending/merchants/{merchantId}/migration_signals/evaluate` | Evaluate processor-migration risk from recent batches | ServicerAgent |
| POST | `/lending/migration_signals/{signalId}/confirm` | Confirm a migration signal; suspends the merchant | ServicerAgent |
| POST | `/lending/migration_signals/{signalId}/dismiss` | Dismiss a migration signal | ServicerAgent |
| POST | `/lending/migration_signals/{signalId}/clear` | Clear a confirmed migration signal | ServicerAgent |
| GET | `/lending/migration_signals/{signalId}` | Get a migration signal | All roles |
| GET | `/lending/merchants/{id}/migration_signals` | List a merchant's migration signals | All roles |
| POST | `/lending/funding_banks` | Register a funding partner bank | PlatformAdmin |
| POST | `/lending/funding_banks/{bankId}/suspend` | Suspend a funding partner bank | PlatformAdmin |
| GET | `/lending/funding_banks/{bankId}` | Get a funding partner bank | All roles |
| POST | `/lending/loans/{loanId}/sales/quote` | Quote a loan sale to a partner bank | BankOfficer |
| POST | `/lending/sales/{saleId}/commit` | Commit to a quoted sale | BankOfficer |
| POST | `/lending/sales/{saleId}/settle` | Settle a committed sale (different officer than committer) | BankOfficer |
| POST | `/lending/sales/{saleId}/fail` | Fail a committed sale (compensating) | BankOfficer |
| POST | `/lending/sales/{saleId}/requote` | Requote a failed sale at the loan's current remaining balance | BankOfficer |
| GET | `/lending/sales/{saleId}` | Get a loan sale | All roles |
| GET | `/lending/loans/{id}/sales` | List a loan's sales | All roles |
| GET | `/lending/sales` | List loan sales (filtered) | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MERCHANT_TENURE_INSUFFICIENT` | 409 |
| `ERR_MERCHANT_VOLUME_INSUFFICIENT` | 409 |
| `ERR_MERCHANT_NOT_ELIGIBLE` | 409 |
| `ERR_MERCHANT_SUSPENDED` | 409 |
| `ERR_MERCHANT_HAS_ACTIVE_LOAN` | 409 |
| `ERR_DUPLICATE_PROCESSING_DATE` | 409 |
| `ERR_BATCH_NOT_FINALIZED` | 409 |
| `ERR_BATCH_ALREADY_SWEPT` | 409 |
| `ERR_OFFER_OVERLAP_ACTIVE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_AMOUNT_EXCEEDS_PREAPPROVED` | 409 |
| `ERR_HOLDBACK_PCT_NOT_OFFERED` | 409 |
| `ERR_GUARANTOR_NOT_ACTIVE` | 409 |
| `ERR_DISCLOSURE_NOT_DELIVERED` | 409 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 409 |
| `ERR_DISCLOSURE_COOLING_NOT_ELAPSED` | 409 |
| `ERR_LOAN_NOT_ACTIVE` | 409 |
| `ERR_LOAN_ALREADY_TERMINAL` | 409 |
| `ERR_CATCHUP_EXCEEDS_OUTSTANDING` | 409 |
| `ERR_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_ENFORCEMENT_WINDOW_OPEN` | 409 |
| `ERR_MIGRATION_SIGNAL_OPEN` | 409 |
| `ERR_BANK_INACTIVE` | 409 |
| `ERR_SOD_SAME_USER` | 409 |
