# GSE Loan Delivery API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the GSE Loan Delivery API, a platform that governs the end-to-end relationship between a government-sponsored enterprise and the lending counterparties that sell and service mortgage loans into its programs. The system covers counterparty onboarding with financial and quality-control eligibility thresholds, automated underwriting backed by third-party data-validation services for income, assets, and employment, risk-attribute-based pricing at loan delivery, securitization pool management, post-purchase quality control with repurchase and appeal mechanics, representation and warranty relief earned through payment performance or independent data validation, and servicing transfer governance with segregation of duties and oversight scoring.

The business problem is one of coordinated risk: a seller that is thinly capitalized or producing defective loans cannot be allowed to keep delivering; a loan whose income, asset, and employment data has been independently validated at origination should earn relief from later repurchase exposure; a servicer accumulating unresolved repurchase demands should lose eligibility to receive transferred servicing. Each of these judgments depends on state scattered across many entities, so the API exposes explicit, auditable state machines, deterministic pricing derived from a single active loan-level price adjustment grid, and optimistic concurrency controls on the three operations most exposed to stale reads: underwriting case finalization, pool issuance, and servicing transfer approval.

The system is mounted under the `/gse` URL prefix. It is designed to be driven both by human operators (seller officers, servicer officers, underwriters, quality-control auditors, GSE administrators) and by an automated underwriting engine operator that finalizes underwriting cases once their data-validation package is complete.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When a caller attempts an operation outside the permissions of their declared role, or fails an ownership check tied to their identity, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `GseAdmin`, `SellerOfficer`, `Underwriter`, `GseUnderwritingEngine`, `QcAuditor`, and `ServicerOfficer`.

- A `GseAdmin` is the GSE operational administrator responsible for counterparty approval, suspension, and termination; master agreement lifecycle; loan-level price adjustment grid management; repurchase demand issuance and appeal resolution; servicing transfer adjudication; subservicer oversight records; and control of the logical clock.
- A `SellerOfficer` acts for a selling lender: registering loans, submitting underwriting cases, delivering loans into pools, managing the pool lifecycle, appealing and settling repurchase demands, and maintaining the seller's pipeline tracker.
- An `Underwriter` records data-validation reports against underwriting cases and completes them with outcomes.
- A `GseUnderwritingEngine` operator finalizes validated underwriting cases, producing the recommendation and eligibility outcome.
- A `QcAuditor` opens post-purchase quality control audits, records findings, issues findings, and closes audits.
- A `ServicerOfficer` records monthly payment events and requests or cancels servicing transfers.

Two roles are entity-backed. When `X-User-Role` is `SellerOfficer`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` compare the resource's seller foreign key to `X-User-ID`. When `X-User-Role` is `ServicerOfficer`, `X-User-ID` is the `id` of the acting `Servicer`; ownership checks on any resource that references a `Servicer` compare the resource's servicer foreign key to `X-User-ID`. The remaining four roles — `GseAdmin`, `Underwriter`, `GseUnderwritingEngine`, and `QcAuditor` — are opaque: for each of them, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier (for example, as `requester_id` on a `ServicingTransfer`, where the transfer workflow requires it) but does not compare it to any entity's `id` for those roles. All roles may call every read endpoint; write permissions per endpoint are given in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Counterparty Eligibility Thresholds

Admission of counterparties is gated on two financial and quality thresholds applied at approval time. Both a seller and a servicer must report a `net_worth_cents` of at least 2,500,000 cents (that is, 25,000.00 in dollar terms); approval of an under-capitalized counterparty is rejected with `ERR_NET_WORTH_BELOW_MINIMUM`. A seller must additionally present a `qc_defect_rate_bps` — its post-purchase quality-control defect rate expressed in basis points — of at most 150 basis points; exceeding that ceiling yields `ERR_QC_DEFECT_RATE_EXCEEDED`. A servicer must instead present a `qc_rating` of `SATISFACTORY`; the ratings `NEEDS_IMPROVEMENT` and `UNSATISFACTORY` are both insufficient and produce `ERR_SERVICER_QC_RATING_INSUFFICIENT`. These thresholds are re-checked on re-approval of a suspended seller, not only on initial approval.

### 2.5. Monetary Representation, Rates, and Precision

All monetary values in the system are integer cents — `net_worth_cents`, `unpaid_principal_balance_cents`, `appraised_value_cents`, `target_balance_cents`, `current_balance_cents`, `delivery_price_cents`, `amount_cents`, `projected_value_cents`, `projected_value_before_cents`, `projected_value_after_cents`, and `delta_cents` are all whole-cent integers. Rates and ratios are integer basis points where applicable — `qc_defect_rate_bps`, `ltv_bp`, `applied_llpa_bps`, and each pricing row's `llpa_bps`, `ltv_min_bp`, and `ltv_max_bp`. Two derived quantities are computed with round-half-up rounding: the loan-to-value ratio, which is an integer number of basis points, and any dollar adjustment derived by multiplying a cent amount by a basis-point rate, which is rounded half-up to a whole cent.

### 2.6. The Logical Clock and Time-Gated Behavior

The system maintains a logical clock rather than relying on wall-clock time. At startup, before any operator action, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never silently falls back to wall-clock time. A `GseAdmin` may advance the clock by supplying a `current_utc` instant in ISO 8601 UTC. Advancing the clock re-evaluates the time-dependent transitions in the system: a master agreement whose `expiration_date` has been reached moves from `ACTIVE` to `EXPIRED`, and an approved servicing transfer whose `effective_date` has been reached completes (or cancels, per §3.8). Several workflows gate on the logical clock: a servicing transfer's requested `effective_date` must lie strictly after the current logical time, a pool's `issue_date` must lie strictly after the current logical time at creation, a master agreement may only be activated while the logical time is within its effective window, an appeal must be lodged on or before the demand's `appeal_deadline`, and an oversight record may only close once its period has ended.

### 2.7. Common Resource Properties and Mutation Semantics

Most resources carry a standard set of system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (refreshed on every mutation), and `version` (an integer that increments on every mutation). The entities `Seller`, `Servicer`, `MasterAgreement`, `LlpaMatrix`, `Loan`, `UnderwritingCase`, `Pool`, `QcAudit`, `QcFinding`, `RepurchaseDemand`, `ServicingTransfer`, `SubservicerOversight`, and `Pipeline` all carry this full set. Two resources are deliberately lighter: a `ValidationReport` and a `PaymentEvent` carry only `id` and `created_at` — both `updated_at` and `version` are absent on them — and an `LlpaUpdateEvent` likewise carries only `id` and `created_at`. Any side effect described in §3 that mutates a resource — a status transition, a recomputed derived field, an incremented counter — also refreshes that resource's `updated_at` and increments its `version`.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names a distinct required input field. Finalizing an underwriting case requires the request to carry `expected_case_version`, equal to the case's current `version` as last observed by the caller; if another writer has advanced the case's version since that read — for example through a prior finalize or a cascaded mutation — the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the case is out of date. Issuing a pool requires `expected_pool_version` matching the pool's current `version`; deliveries, cancellations, or a prior issue attempt may have changed the pool contents the caller priced against, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Approving a servicing transfer requires `expected_loan_version` matching the current `version` of the loan whose servicing is moving; a loan-level mutation such as a repurchase, a re-underwriting, or a prior transfer completion may have invalidated the arrangement the approval was based on, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No endpoint other than these three accepts a version field.

### 2.9. Validation Order and Nested Resource Retrieval

When several checks could reject the same request, the server applies them in a fixed priority order. First come the header checks (§2.1), then the role-permission check. Next, every identifier referenced in the path and the body must exist — `ERR_NOT_FOUND` (HTTP 404) otherwise — with path identifiers validated strictly left to right, so a missing parent is reported before any child lookup is attempted. Identity-based ownership checks (`ERR_FORBIDDEN_FOR_ROLE`, HTTP 403) — for example the checks that restrict a `SellerOfficer` to their own seller or a `ServicerOfficer` to a servicing transfer they requested — are applied only after the existence of every body-referenced identifier has been confirmed, so a request naming a nonexistent body-referenced resource is reported as `ERR_NOT_FOUND` even when the caller would also fail the ownership check. After existence and ownership, the target resource must be in a state that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP 409). Only then do the business gates run, in this order: temporal gates (appeal window, transfer date, oversight period end, agreement effectiveness, pool issue date), referential gates (pool-to-loan seller and agreement matching, finding-loan-to-audit-seller matching), compliance gates (relief-tier bars, segregation of duties, oversight-score floor), fiscal gates (pool capacity, seller funds), and finally constraint gates (appeal rounds, pool non-empty, approval thresholds, loan eligibility). Within a gate family, the checks named in that family run in the order named — for example, on a demand appeal the appeal-window check precedes the appeal-rounds check, so an appeal that is both late and over budget is rejected with `ERR_APPEAL_WINDOW_CLOSED`. This ordering matters operationally: for example, on transfer approval the oversight-deficiency rejection is evaluated before the stale-version rejection, so a caller receives `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT` rather than `ERR_STALE_VERSION` when both would apply.

### 2.10. Pricing Authority: a Single Active Grid

Loan-level price adjustments are governed by `LlpaMatrix` grids. Each grid is defined by an `effective_from` instant (inclusive) and an `effective_until` instant (exclusive, and strictly after `effective_from`), plus a list of pricing `rows`. Each row is a structure carrying `occupancy`, `product_type`, `llpa_bps`, `ltv_max_bp`, `ltv_min_bp`, `credit_min`, and `credit_max`. At most one grid is `ACTIVE` at a time: creating a newer grid supersedes the prior `ACTIVE` grid, moving it to `SUPERSEDED`, and the new grid becomes the single pricing authority. All provisional pricing (pipeline projections) uses whichever grid is currently `ACTIVE`; final pricing at delivery pins the grid active at the delivery instant onto the loan and is immune to later grid swaps.

### 2.11. Conserved Quantities

Three quantities must always reconcile. For every pool, `current_balance_cents` equals the sum of `unpaid_principal_balance_cents` over its loans currently in `DELIVERED` status, and `loan_count` equals the count of those loans; delivering a loan into a pool and later cancelling that pool form a forward/compensate pair after which every affected loan returns to `DRAFT` and the pool balance returns to its pre-delivery value. For every loan, `consecutive_on_time_payments` equals the length of the longest trailing run of consecutive `ON_TIME` payment events ordered by due date — a `LATE` event breaks the run — and `relief_tier` equals the tier computed from that counter together with the independent-validation flag and the seller's probation flag. For every seller pipeline, `projected_value_cents` equals the sum of provisionally priced values over the seller's loans in `DRAFT` or `UNDERWRITTEN` status under the currently `ACTIVE` grid; across a grid swap, each recorded update event's `delta_cents` equals its `projected_value_after_cents` minus its `projected_value_before_cents` exactly.

## 3. Business Logic & Workflows

### 3.1. Onboarding Sellers and Servicers

A `GseAdmin` begins the counterparty relationship by registering a seller with its `legal_name`, an externally assigned `seller_number` unique across all sellers, its reported `net_worth_cents`, and its `qc_defect_rate_bps`. A new seller starts in `PENDING_APPROVAL` with `approval_cycle` at 1 and `probation_relief_enabled` set to false. Registering a servicer is parallel: `legal_name`, a unique `servicer_number`, `net_worth_cents`, and a `qc_rating` drawn from `SATISFACTORY`, `NEEDS_IMPROVEMENT`, or `UNSATISFACTORY`; a new servicer also starts in `PENDING_APPROVAL`, with its `oversight_score` initialized to 100. Any reuse of an already-registered `seller_number`, `servicer_number`, `pool_number`, or `loan_number` is rejected with `ERR_DUPLICATE_IDENTIFIER`.

Approval applies the thresholds of §2.4. A seller in `PENDING_APPROVAL` meeting both the net-worth floor and the defect-rate ceiling moves to `APPROVED`; a servicer meeting the net-worth floor and holding a `SATISFACTORY` rating moves to `APPROVED`. Either party may later be moved `APPROVED → SUSPENDED` by an administrator without further preconditions. Suspending a seller does not cascade: its master agreements are not automatically terminated, and an administrator who wants them ended must terminate each one individually.

Re-approval is where seller history accumulates. When a `SUSPENDED` seller is approved again — again subject to the net-worth and defect-rate gates, with `ERR_NET_WORTH_BELOW_MINIMUM` or `ERR_QC_DEFECT_RATE_EXCEEDED` on failure — its `approval_cycle` increments by one. The moment `approval_cycle` reaches 2, the system sets `probation_relief_enabled` to true on the seller. That flag caps the representation-and-warranty relief tier of every loan that seller ever delivers at `PAYMENT_HISTORY_36`, regardless of how strong the loan's independent validation package is (§3.6).

Termination is the final step and is guarded differently for the two counterparty types. A seller may move `APPROVED → TERMINATED` only if none of its loans is in `DELIVERED` status — an open delivery obligation blocks termination with `ERR_SELLER_HAS_ACTIVE_LOANS`. A servicer may move `APPROVED → TERMINATED` only if no loan for which it is the servicer of record is in `DELIVERED` or `PURCHASED` status, failing with `ERR_SERVICER_HAS_ACTIVE_LOANS`. Both `TERMINATED` states are terminal.

### 3.2. Master Agreements and Their Effective Windows

A master agreement binds one seller and one servicer as counterparties. An administrator creates one by supplying the `seller_id`, the `servicer_id`, an `effective_date`, and an `expiration_date`; the expiration must be strictly after the effective date, and a payload violating that ordering is rejected with `ERR_INVALID_REQUEST`. A new agreement begins in `DRAFT`.

Activation — `DRAFT → ACTIVE` — is allowed only when three conditions hold together: the seller is `APPROVED` (else `ERR_SELLER_NOT_APPROVED`), the servicer is `APPROVED` (else `ERR_SERVICER_NOT_APPROVED`), and the current logical time is on or after `effective_date` and strictly before `expiration_date` (else `ERR_AGREEMENT_NOT_EFFECTIVE`). From `ACTIVE`, an agreement expires automatically — moving to `EXPIRED` — once the logical clock passes its `expiration_date`; an administrator may also terminate an `ACTIVE` agreement outright, moving it to `TERMINATED`, which is terminal. Agreements may be listed with optional `seller_id`, `servicer_id`, and `status` filters alongside `limit` and `offset`.

### 3.3. Registering Loans and the Loan-to-Value Computation

A `SellerOfficer` registers a loan application by providing the `seller_id` of the selling lender, the `servicer_id` of the servicer of record, the `agreement_id` under which the loan will be delivered, a seller-assigned `loan_number` unique across all loans, the primary `borrower_name`, the `unpaid_principal_balance_cents`, the `appraised_value_cents` at origination, the representative `credit_score` (an integer from 300 to 850), the `occupancy` (one of `PRIMARY_RESIDENCE`, `SECOND_HOME`, `INVESTMENT`), and the `product_type` (one of `FIXED_30`, `FIXED_15`, `ARM_5_1`).

At creation the system computes `ltv_bp`, the loan-to-value ratio in basis points: ten thousand times `unpaid_principal_balance_cents`, divided by `appraised_value_cents`, rounded half-up to an integer. A loan with a 400,000.00 balance against a 500,000.00 appraisal therefore carries an `ltv_bp` of 8000, meaning 80.00 percent. New loans begin in `DRAFT` status with `au_status` of `NOT_SUBMITTED`, `consecutive_on_time_payments` at 0, `independent_validation_complete` false, `relief_tier` of `NONE`, `pool_id` null, and no `delivered_at`. Registering a loan triggers a revaluation of its seller's pipeline (§3.7). Loans may be listed with optional `seller_id`, `servicer_id`, `agreement_id`, `pool_id`, and `status` filters.

### 3.4. Automated Underwriting: Cases, Validation Rounds, and Finalization

Submitting a loan for automated underwriting creates an `UnderwritingCase` from a payload carrying the `loan_id`. The loan must be in `DRAFT` status, and no case that has not yet reached `FINALIZED` may already exist for it; violating either condition yields `ERR_LOAN_NOT_UNDERWRITABLE`. A new case starts with `case_status` of `SUBMITTED`, `submission_round` at 1, `recommendation` of `PENDING`, and `final_outcome` of `PENDING`; the `seller_id` is denormalized onto the case from the loan at submission as a join key. Cases may be listed filtered by `loan_id` or `case_status`.

An `Underwriter` then feeds the case data-validation reports, one per service. Each report is created with a `service_type` of `INCOME`, `ASSET`, or `EMPLOYMENT` and an external `provider_reference` code. Recording the first report moves the case `SUBMITTED → VALIDATING`; reports recorded against a case already in `VALIDATING` leave it there. Each new report belongs to the case's current `submission_round`, recorded on the report as `round`, and starts with `result` of `PENDING`. Reports may be listed filtered by `case_id` or `service_type`. The underwriter completes a pending report by supplying a `result` of `VALIDATED` or `NOT_VALIDATED`.

The case reacts automatically as outcomes land. When all three service types — `INCOME`, `ASSET`, and `EMPLOYMENT` — hold a report with `result` `VALIDATED` for the current round, the case moves `VALIDATING → VALIDATED`. If any report for the current round completes as `NOT_VALIDATED`, the case instead moves `VALIDATING → FAILED` and its `submission_round` increments by one. A failed case is not dead: the underwriter may resubmit by recording further reports, which moves it `FAILED → VALIDATING` with new reports stamped at the incremented round.

Finalization is reserved for the `GseUnderwritingEngine` and is OCC-guarded per §2.8: the request carries `expected_case_version`, and a case whose version has advanced since the caller's last read is rejected with `ERR_STALE_VERSION`. On success the case moves `VALIDATED → FINALIZED`, its `version` increments, and the engine computes the eligibility outcome.

Eligibility is all-or-nothing across four tests. The loan is eligible only when its `ltv_bp` is at most 9500 (the maximum loan-to-value of 95.00 percent — a loan at exactly 9500 is eligible, one at 9501 is not), its `credit_score` is at least 620 (exactly 620 is eligible, 619 is not), its `occupancy` is one of the three enumerated values, and its `product_type` is one of the three enumerated values. An ineligible loan yields `final_outcome` of `FAIL`, with `recommendation` left unset from the eligible vocabulary. For an eligible loan, `final_outcome` is `PASS`, and the `recommendation` is `REFER_WITH_CAUTION` when the `credit_score` is below 680 or the `ltv_bp` is above 9000 — that is, a credit score from 620 through 679, or a loan-to-value strictly above 9000 and at most 9500, places the loan in the refer band — and `APPROVE_ELIGIBLE` otherwise.

The finalized outcome cascades onto the loan. A `PASS` with recommendation `APPROVE_ELIGIBLE` moves the loan `DRAFT → UNDERWRITTEN` and sets its `au_status` to `RECOMMEND_APPROVE`. A `PASS` with `REFER_WITH_CAUTION` leaves the loan in `DRAFT` — a cautionary recommendation does not advance the loan — while setting its `au_status` to `RECOMMEND_REFER`. A `FAIL` moves the loan `DRAFT → REJECTED` and sets its `au_status` to `INELIGIBLE`. When `final_outcome` is `PASS`, the system also marks the loan's `independent_validation_complete` true — the completed Day-1 validation package for income, assets, and employment is what earned the pass — and re-evaluates the loan's relief tier per §3.6. Every one of these cascades triggers a revaluation of the seller's pipeline (§3.7).

### 3.5. Delivery into Pools and Pool Lifecycle

Pools are the securitization containers into which underwritten loans are delivered. A `SellerOfficer` creates a pool with the `seller_id` securitizing into it, the governing `agreement_id`, an externally assigned `pool_number` unique across all pools, an `issue_date`, and a `target_balance_cents` — the maximum total unpaid principal balance the pool accepts. The `issue_date` must lie strictly after the current logical time, failing with `ERR_INVALID_REQUEST` otherwise. A new pool is `OPEN` with `current_balance_cents` and `loan_count` both 0. Pools may be listed filtered by `seller_id`, `agreement_id`, or `status`.

Delivering a loan is the central commercial act and is guarded by five preconditions, all enforced at delivery time. The loan's `au_status` must be `RECOMMEND_APPROVE`, else `ERR_LOAN_NOT_ELIGIBLE`. The seller must be `APPROVED`, else `ERR_SELLER_NOT_APPROVED`. The agreement must be `ACTIVE`, else `ERR_AGREEMENT_NOT_EFFECTIVE`. The target pool named by the `pool_id` in the delivery payload must exist, be `OPEN`, and match the loan on both seller and agreement — its seller must be the loan's seller and its agreement the loan's agreement — else `ERR_POOL_NOT_OPEN`. Finally, capacity: the pool's `current_balance_cents` plus the incoming loan's `unpaid_principal_balance_cents` must not exceed the pool's `target_balance_cents`; a sum exactly equal to the target is allowed, and exceeding it by any amount yields `ERR_POOL_CAPACITY_EXCEEDED`.

A successful delivery moves the loan `UNDERWRITTEN → DELIVERED`, stamps its `pool_id` with the pool's id and its `delivered_at` with the current logical time, and adds the loan's unpaid principal balance to the pool's `current_balance_cents` while incrementing the pool's `loan_count`. Delivery is also the moment of final pricing. The system selects the pricing row of the `ACTIVE` grid at the delivery instant by matching the loan's `occupancy` and `product_type` exactly, requiring the loan's `ltv_bp` to be strictly above the row's `ltv_min_bp` and at most its `ltv_max_bp`, and requiring the loan's `credit_score` to be at least the row's `credit_min` and at most its `credit_max`; exactly one row must match for a loan to be priced. The dollar adjustment is the unpaid principal balance multiplied by the row's `llpa_bps` and divided by ten thousand, rounded half-up to a whole cent, and the `delivery_price_cents` is the unpaid principal balance minus that adjustment. The row's `llpa_bps` is pinned onto the loan as `applied_llpa_bps`, and these two pinned values never change afterward — later grid swaps do not touch delivered or purchased loans. The delivery closes with a pipeline revaluation for the seller.

From `OPEN`, a pool may be locked — but only when it holds at least one delivered loan, failing with `ERR_POOL_EMPTY` otherwise — moving `OPEN → LOCKED`. A `LOCKED` pool may be unlocked back to `OPEN` without preconditions, or issued. Issuance is OCC-guarded: the request carries `expected_pool_version`, and a pool whose version has advanced since the caller's last read is rejected with `ERR_STALE_VERSION`. On success the pool moves `LOCKED → ISSUED`, its `version` increments, and every loan in the pool that is `DELIVERED` moves to `PURCHASED`; the seller's pipeline is revalued. `ISSUED` is terminal.

Cancelling an `OPEN` pool moves it to `CANCELLED` (also terminal) and unwinds its contents: every `DELIVERED` loan in the pool returns to `DRAFT`, its `pool_id` and `delivered_at` are cleared, the pool's `current_balance_cents` decreases by each such loan's unpaid principal balance and its `loan_count` decreases accordingly, and the seller's pipeline is revalued. The loan's previously computed `delivery_price_cents` and `applied_llpa_bps` are retained as historical values on the loan but no longer count toward pipeline projected value while the loan is back in `DRAFT` — the pipeline re-prices provisionally under the currently active grid instead.

### 3.6. Payment Performance and Representation & Warranty Relief

Once a loan is `PURCHASED`, a `ServicerOfficer` records monthly payment events against it; a payment event on a loan in any other status is rejected with `ERR_LOAN_NOT_PURCHASED`. Each event carries the `loan_id`, a `due_date`, a `paid_on_time` boolean, and an `amount_cents` that must be a positive number of cents — a zero or negative amount fails with `ERR_INVALID_REQUEST`. At most one event may exist per loan per due date; a second event for the same loan and `due_date` is rejected with `ERR_DUPLICATE_PAYMENT_PERIOD`. The system derives the event's `outcome`: `ON_TIME` when `paid_on_time` is true, `LATE` otherwise. Events may be listed filtered by `loan_id` or `outcome`.

Every recorded event moves the loan's relief machinery. An `ON_TIME` event increments `consecutive_on_time_payments`; a `LATE` event resets that counter to 0. The relief tier is then re-evaluated. The raw tier is `INDEPENDENT_VALIDATION` when the loan's `independent_validation_complete` flag is true; otherwise `PAYMENT_HISTORY_36` when the counter has reached at least 36 — exactly 36 consecutive on-time payments qualifies, 35 does not — and `NONE` below that. There is then a probation cap: when the loan's seller has `probation_relief_enabled` true, a raw tier of `INDEPENDENT_VALIDATION` is capped down to `PAYMENT_HISTORY_36`; any other raw tier passes through unchanged. The resulting tier is stored as the loan's `relief_tier`. The two paths to relief are genuinely independent: the payment-history path requires the 36-payment streak and is destroyed by any late payment, while the independent-validation path requires all three validation services (`INCOME`, `ASSET`, `EMPLOYMENT`) validated in the latest submission round and is indifferent to payment count.

### 3.7. Pipelines and Grid-Swap Impact Events

Each seller has a pipeline tracker projecting the value of its undelivered book. A `SellerOfficer` creates it by supplying the `seller_id`; there is exactly one pipeline per seller, and a second create call for the same seller returns the existing pipeline rather than making a duplicate. The pipeline's `projected_value_cents` is the sum, over the seller's loans in `DRAFT` or `UNDERWRITTEN` status, of each loan's provisional price under the currently `ACTIVE` grid — computed with the same row-matching rules as final pricing (§3.5) but using whichever grid is active at revaluation time and never persisted on the loan. A loan matching no pricing row in the active grid contributes 0 to the sum. Pipelines may be listed filtered by `seller_id`.

Revaluation is triggered by any event that changes the inputs: creating or updating a loan in `DRAFT` or `UNDERWRITTEN`, a case finalization that moves a loan to `UNDERWRITTEN` or `REJECTED`, a delivery, a pool cancellation, a pool issuance, and — most dramatically — a grid swap. When an administrator creates a new `LlpaMatrix`, the prior `ACTIVE` grid becomes `SUPERSEDED`, the new grid becomes `ACTIVE`, and every pipeline is revalued against it. For each impacted pipeline the system appends an `LlpaUpdateEvent` recording the `pipeline_id`, the `old_matrix_id` of the superseded grid, the `new_matrix_id` of the newly active grid, the `projected_value_before_cents` immediately before the swap, the `projected_value_after_cents` immediately after, the `delta_cents` (after minus before), and the `impacted_loan_count` — the number of that pipeline's loans whose recomputed price changed. These events may be listed filtered by `pipeline_id`.

### 3.8. Servicing Transfers and Subservicer Oversight

A `ServicerOfficer` may request that servicing of a `PURCHASED` loan move to a different servicer by supplying the `loan_id`, the `to_servicer_id` of the proposed receiver, and a requested `effective_date`. The loan must be `PURCHASED`, else `ERR_LOAN_NOT_PURCHASED`; the `effective_date` must be strictly after the current logical time, else `ERR_TRANSFER_DATE_PAST`. The request records the loan's current servicer as `from_servicer_id` (denormalized at request time) and captures the requesting officer's identity as `requester_id` — the `X-User-ID` of the `ServicerOfficer` who created the request — which later drives the segregation-of-duties and cancel-ownership checks. The transfer begins in `REQUESTED`. Transfers may be listed filtered by `loan_id`, `from_servicer_id`, `to_servicer_id`, or `status`.

Adjudication belongs to a `GseAdmin`, but not to just any operator. Segregation of duties requires that the acting administrator's `X-User-ID` differ from the `requester_id` recorded on the transfer; an administrator who is the same principal as the requesting officer is rejected with `ERR_SEGREGATION_OF_DUTIES` on both approval and rejection. Approval adds three further gates, evaluated per the priority order of §2.9 — so the compliance gates surface before the concurrency gate. The receiving servicer must be `APPROVED`, else `ERR_SERVICER_NOT_APPROVED`. Its `oversight_score` must be at least 60 — exactly 60 passes — else `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT`. And the request must carry `expected_loan_version` matching the loan's current `version`, with a mismatch rejected as `ERR_STALE_VERSION`; a loan mutated since the caller's read (by repurchase, re-underwriting, or a prior transfer completion) invalidates the basis of the approval. A passing approval moves the transfer `REQUESTED → APPROVED`; rejection moves it `REQUESTED → REJECTED`, which is terminal.

Completion is automatic. When the logical clock reaches an approved transfer's `effective_date`, the transfer moves `APPROVED → COMPLETED` and the loan's `servicer_id` is rewritten to `to_servicer_id` — unless the loan is in `REPURCHASED` status at that moment, in which case the transfer instead auto-transitions to `CANCELLED`. A pending transfer may also be withdrawn: the requesting officer — and only that officer, matched by comparing the caller's `X-User-ID` to the transfer's `requester_id`, failing with `ERR_FORBIDDEN_FOR_ROLE` otherwise — may cancel a `REQUESTED` transfer, moving it to `CANCELLED`.

Oversight of subservicers feeds the transfer gate. An administrator opens a `SubservicerOversight` record with the `servicer_id` of the master servicer doing the overseeing, the `subservicer_id` being overseen, an `oversight_period_start`, an `oversight_period_end` strictly after the start, and an optional `findings_count` defaulting to 0. The record opens in `OPEN` status; opening one immediately recomputes the master servicer's oversight score. A record may close only once its `oversight_period_end` has been reached by the logical clock — earlier closure fails with `ERR_OVERSIGHT_PERIOD_NOT_ENDED` — moving it to `CLOSED` and again recomputing the master servicer's score. Records may be listed filtered by `servicer_id`, `subservicer_id`, or `status`.

The `oversight_score` itself starts at 100 and loses 5 points for every pending issue and 2 points for every oversight finding. Pending issues are repurchase demands in `ISSUED` or `APPEALED` status on loans whose servicer of record is this servicer. Oversight findings are the summed `findings_count` across this servicer's `OPEN` oversight records where it acts as master. The score is clamped so it never falls below 0 nor rises above 100. The score is recomputed whenever its inputs change: when a demand is issued or withdrawn on a serviced loan, when a quality-control finding is created on a serviced loan, when an oversight record is opened or closed, and it is consulted at every transfer approval.

### 3.9. Post-Purchase Quality Control, Repurchase Demands, and Appeals

After loans are purchased, a `QcAuditor` may open a post-purchase quality control audit of a seller by supplying the `seller_id` and a `sampling_method` of `RANDOM`, `TARGETED`, or `DISCRETIONARY`. The audit begins in `OPEN` status. Audits may be listed filtered by `seller_id` or `status`.

Findings cite individual loans. Recording a finding against an audit takes the `loan_id`, a `defect_category` of `INCOME_MISREP`, `ASSET_MISREP`, `EMPLOYMENT_MISREP`, `COLLATERAL`, `ELIGIBILITY`, or `OTHER`, and a `severity` of `SIGNIFICANT`, `MODERATE`, or `MINOR`. The cited loan must be `PURCHASED`, else `ERR_LOAN_NOT_PURCHASED`, and it must belong to the seller under audit — the loan's seller must equal the audit's seller — else the same referential failure surfaces. The first finding moves the audit `OPEN → IN_REVIEW`, the finding itself begins in `IDENTIFIED`, and the servicer oversight score is recomputed for the loan's servicer. Findings may be listed filtered by `audit_id`, `loan_id`, or `status`. When the auditor is ready, issuing the findings moves the audit `IN_REVIEW → FINDINGS_ISSUED`.

Repurchase demands are issued by a `GseAdmin` against an identified finding, but two gates stand in front. The audit must already be in `FINDINGS_ISSUED` status, else `ERR_AUDIT_NOT_ISSUED`. And the loan's relief tier may bar the demand outright: when the loan's `relief_tier` is `INDEPENDENT_VALIDATION` and the `defect_category` is one of `INCOME_MISREP`, `ASSET_MISREP`, or `EMPLOYMENT_MISREP`, or when the tier is `PAYMENT_HISTORY_36` and the defect category is one of those same three misrepresentation categories, the demand is rejected with `ERR_RELIEF_TIER_BLOCKS_DEMAND` — earned relief insulates precisely the defects the validation or payment history covered, while collateral, eligibility, and other defects remain actionable at any tier. A successful issuance moves the finding `IDENTIFIED → REPURCHASE_ISSUED` and creates a `RepurchaseDemand` in `ISSUED` status whose `amount_cents` equals the loan's `unpaid_principal_balance_cents` at the moment of issuance, whose `loan_id` is denormalized from the finding, whose `appeal_deadline` is set 30 days after issuance, and whose `appeal_rounds_used` starts at 0. The servicer oversight score is recomputed, since a new pending issue now counts against the servicer. Demands may be listed filtered by `finding_id`, `loan_id`, or `status`.

The seller may appeal a demand that is `ISSUED` or `UPHELD` — appealing from any other status fails with `ERR_INVALID_STATE`. The appeal must arrive on or before the `appeal_deadline`; later appeals fail with `ERR_APPEAL_WINDOW_CLOSED`. Note the window runs from issuance and is not extended by an early upheld ruling, so an appeal of an `UPHELD` demand is still measured against the original deadline. Each demand affords at most two appeals in total; a third attempt fails with `ERR_APPEAL_ROUNDS_EXHAUSTED`. The appeal payload carries an `appeal_reason`. A successful appeal moves the demand to `APPEALED`, increments `appeal_rounds_used`, and moves the finding to `APPEALED`.

Appeals are resolved by a `GseAdmin` supplying an `outcome`. The demand must be `APPEALED`, else `ERR_INVALID_STATE`. An `outcome` of `UPHELD` moves the demand to `UPHELD` and the finding to `UPHELD`. An `outcome` of `OVERTURNED` moves the demand to `WITHDRAWN` (terminal) and the finding to `OVERTURNED` (terminal), and the servicer oversight score is recomputed because a pending issue has left the books. An `UPHELD` finding may be appealed again, subject to the same window and the same two-appeal budget.

Settlement closes the loop. A `SellerOfficer` settles a demand only when it is `UPHELD`, else `ERR_DEMAND_NOT_UPHELD`. Before anything changes, the system runs the seller financial check: the sum of `amount_cents` across all of this seller's demands currently in `UPHELD` status — a sum that includes the demand being settled — must not exceed the seller's `net_worth_cents`. Equality is allowed; exceeding the net worth by even one cent rejects the settlement with `ERR_INSUFFICIENT_SELLER_FUNDS` and leaves all state untouched. A passing settlement moves the demand to `SETTLED` (terminal), the finding to `REMEDIATED` (terminal), and the loan `PURCHASED → REPURCHASED` (terminal for the loan).

An audit may close once everything it surfaced has resolved. Moving `FINDINGS_ISSUED → CLOSED` requires every finding of the audit to be in a terminal finding state — `UPHELD` with its demand settled or withdrawn, `OVERTURNED`, or `REMEDIATED` — and any lingering non-terminal finding blocks closure with `ERR_AUDIT_HAS_OPEN_FINDINGS`. `CLOSED` is terminal.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource return `200 OK`. Error responses use the status codes listed in §5 and the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/gse/_clock/set_current_utc` | Set the logical clock; re-evaluates time-dependent transitions | GseAdmin |
| POST | `/gse/sellers` | Register a seller (PENDING_APPROVAL) | GseAdmin |
| GET | `/gse/sellers/{sellerId}` | Get a seller | Any |
| POST | `/gse/sellers/{sellerId}/approve` | Approve a seller (initial or re-approval from SUSPENDED) | GseAdmin |
| POST | `/gse/sellers/{sellerId}/suspend` | Suspend a seller | GseAdmin |
| POST | `/gse/sellers/{sellerId}/terminate` | Terminate a seller | GseAdmin |
| POST | `/gse/servicers` | Register a servicer (PENDING_APPROVAL) | GseAdmin |
| GET | `/gse/servicers/{servicerId}` | Get a servicer | Any |
| POST | `/gse/servicers/{servicerId}/approve` | Approve a servicer | GseAdmin |
| POST | `/gse/servicers/{servicerId}/suspend` | Suspend a servicer | GseAdmin |
| POST | `/gse/servicers/{servicerId}/terminate` | Terminate a servicer | GseAdmin |
| POST | `/gse/master-agreements` | Create a master agreement (DRAFT) | GseAdmin |
| GET | `/gse/master-agreements/{agreementId}` | Get a master agreement | Any |
| GET | `/gse/master-agreements` | List master agreements, filterable | Any |
| POST | `/gse/master-agreements/{agreementId}/activate` | Activate a master agreement | GseAdmin |
| POST | `/gse/master-agreements/{agreementId}/terminate` | Terminate a master agreement | GseAdmin |
| POST | `/gse/llpa-matrices` | Create an LLPA grid; supersedes the prior ACTIVE grid and revalues all pipelines | GseAdmin |
| GET | `/gse/llpa-matrices/{matrixId}` | Get an LLPA grid | Any |
| GET | `/gse/llpa-matrices` | List LLPA grids | Any |
| POST | `/gse/loans` | Register a loan application (DRAFT); ltv_bp computed at creation | SellerOfficer |
| GET | `/gse/loans/{loanId}` | Get a loan | Any |
| GET | `/gse/loans` | List loans, filterable | Any |
| POST | `/gse/loans/{loanId}/deliver` | Deliver an UNDERWRITTEN loan into an OPEN pool; pins final LLPA pricing | SellerOfficer |
| POST | `/gse/underwriting-cases` | Submit a loan for automated underwriting (SUBMITTED) | SellerOfficer |
| GET | `/gse/underwriting-cases/{caseId}` | Get an underwriting case | Any |
| GET | `/gse/underwriting-cases` | List underwriting cases, filterable by loan | Any |
| POST | `/gse/underwriting-cases/{caseId}/reports` | Record a data-validation report for the current submission round | Underwriter |
| GET | `/gse/validation-reports` | List validation reports, filterable by case | Any |
| POST | `/gse/validation-reports/{reportId}/complete` | Complete a pending validation report with an outcome | Underwriter |
| POST | `/gse/underwriting-cases/{caseId}/finalize` | Finalize a VALIDATED case (OCC-guarded on case version) | GseUnderwritingEngine |
| POST | `/gse/pools` | Create a pool (OPEN) | SellerOfficer |
| GET | `/gse/pools/{poolId}` | Get a pool | Any |
| GET | `/gse/pools` | List pools, filterable | Any |
| POST | `/gse/pools/{poolId}/lock` | Lock a pool for issuance | SellerOfficer |
| POST | `/gse/pools/{poolId}/unlock` | Unlock a pool back to OPEN | SellerOfficer |
| POST | `/gse/pools/{poolId}/issue` | Issue a LOCKED pool (OCC-guarded on pool version) | SellerOfficer |
| POST | `/gse/pools/{poolId}/cancel` | Cancel an OPEN pool; returns its DELIVERED loans to DRAFT | SellerOfficer |
| POST | `/gse/payment-events` | Record a monthly payment for a loan | ServicerOfficer |
| GET | `/gse/payment-events` | List payment events, filterable by loan | Any |
| POST | `/gse/qc-audits` | Open a post-purchase QC audit for a seller | QcAuditor |
| GET | `/gse/qc-audits/{auditId}` | Get a QC audit | Any |
| GET | `/gse/qc-audits` | List QC audits, filterable by seller | Any |
| POST | `/gse/qc-audits/{auditId}/findings` | Add a finding citing a PURCHASED loan | QcAuditor |
| GET | `/gse/qc-findings` | List QC findings, filterable | Any |
| GET | `/gse/qc-findings/{findingId}` | Get a QC finding | Any |
| POST | `/gse/qc-audits/{auditId}/issue-findings` | Move audit to FINDINGS_ISSUED | QcAuditor |
| POST | `/gse/qc-audits/{auditId}/close` | Close an audit once all findings are terminal | QcAuditor |
| POST | `/gse/qc-findings/{findingId}/issue-demand` | Issue a repurchase demand for a finding | GseAdmin |
| GET | `/gse/repurchase-demands/{demandId}` | Get a repurchase demand | Any |
| GET | `/gse/repurchase-demands` | List repurchase demands, filterable | Any |
| POST | `/gse/repurchase-demands/{demandId}/appeal` | Appeal an ISSUED or UPHELD demand | SellerOfficer |
| POST | `/gse/repurchase-demands/{demandId}/resolve-appeal` | Resolve an appealed demand (UPHELD or OVERTURNED) | GseAdmin |
| POST | `/gse/repurchase-demands/{demandId}/settle` | Seller settles an UPHELD demand; loan becomes REPURCHASED | SellerOfficer |
| POST | `/gse/servicing-transfers` | Request a servicing transfer for a PURCHASED loan | ServicerOfficer |
| GET | `/gse/servicing-transfers/{transferId}` | Get a servicing transfer | Any |
| GET | `/gse/servicing-transfers` | List servicing transfers, filterable | Any |
| POST | `/gse/servicing-transfers/{transferId}/approve` | Approve a transfer (segregation of duties, oversight score, OCC on loan version) | GseAdmin |
| POST | `/gse/servicing-transfers/{transferId}/reject` | Reject a transfer (segregation of duties) | GseAdmin |
| POST | `/gse/servicing-transfers/{transferId}/cancel` | Requesting officer cancels a pending transfer | ServicerOfficer |
| POST | `/gse/subservicer-oversight` | Open a subservicer oversight record | GseAdmin |
| GET | `/gse/subservicer-oversight/{recordId}` | Get an oversight record | Any |
| GET | `/gse/subservicer-oversight` | List oversight records, filterable | Any |
| POST | `/gse/subservicer-oversight/{recordId}/close` | Close an oversight record after its period has ended | GseAdmin |
| POST | `/gse/pipelines` | Create (or return) the pipeline tracker for a seller | SellerOfficer |
| GET | `/gse/pipelines/{pipelineId}` | Get a pipeline with current projected value | Any |
| GET | `/gse/pipelines` | List pipelines, filterable by seller | Any |
| GET | `/gse/llpa-update-events` | List LLPA grid-swap impact events, filterable by pipeline | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NET_WORTH_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_QC_DEFECT_RATE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SERVICER_QC_RATING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SELLER_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_SERVICER_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_SELLER_HAS_ACTIVE_LOANS` | 409 Conflict |
| `ERR_SERVICER_HAS_ACTIVE_LOANS` | 409 Conflict |
| `ERR_LOAN_NOT_UNDERWRITABLE` | 409 Conflict |
| `ERR_LOAN_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_POOL_NOT_OPEN` | 409 Conflict |
| `ERR_POOL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_POOL_EMPTY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PAYMENT_PERIOD` | 409 Conflict |
| `ERR_DUPLICATE_IDENTIFIER` | 409 Conflict |
| `ERR_LOAN_NOT_PURCHASED` | 409 Conflict |
| `ERR_AUDIT_NOT_ISSUED` | 409 Conflict |
| `ERR_AUDIT_HAS_OPEN_FINDINGS` | 409 Conflict |
| `ERR_RELIEF_TIER_BLOCKS_DEMAND` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_DEMAND_NOT_UPHELD` | 409 Conflict |
| `ERR_INSUFFICIENT_SELLER_FUNDS` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SUBSERVICER_OVERSIGHT_DEFICIENT` | 422 Unprocessable Entity |
| `ERR_TRANSFER_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_OVERSIGHT_PERIOD_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
