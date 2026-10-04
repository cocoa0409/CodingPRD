# MBS Pooling & Issuer Approval API — Product Requirements Document

## 1. Introduction

This document specifies the Mortgage-Backed Security Pooling & Issuer Approval API, a system that models the lifecycle through which a mortgage originator becomes an approved issuer of government-insured mortgage-backed securities, pools loans into securities, and services the resulting monthly pass-through obligations. The business context is a Ginnie-Mae-style guarantee program: the agency does not buy loans, it guarantees securities backed by government-insured mortgages, and therefore its central risks are issuer solvency, custodial fund integrity, and the unbroken flow of scheduled payments to investors even when borrowers stop paying.

The API is built around three persistent tensions. First, an applicant must clear tiered net-worth, liquidity, and origination-experience gates before it may issue, and a segregation-of-duties rule prevents any officer from adjudicating their own submission. Second, once approved, an issuer must maintain custodial accounts that rigidly separate principal-and-interest funds from tax-and-insurance escrow, must report to investors monthly, and must honor the full scheduled pass-through payment regardless of borrower delinquency — funding any shortfall out of its own liquidity as a repayable advance. Third, the agency continuously monitors issuer liquidity and pool delinquency; breaches trigger watch, suspension, default, and ultimately extinguishment of the issuer's portfolio with transfer to a successor.

All resources are addressed at flat top-level collections; relationships are expressed through foreign-key fields in request payloads rather than nested URL paths. A test-driving endpoint lets the platform administrator set the server's logical clock, which governs engagement-window coverage checks and monthly reporting periods.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role value the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

The system recognizes five roles, spelled exactly as follows: `ApplicantOfficer`, `AgencyReviewer`, `IssuerOfficer`, `DocumentCustodian`, and `PlatformAdmin`.

Role identity is bound to resources in two distinct ways. When `X-User-Role` is `IssuerOfficer`, `X-User-ID` is the `id` of the acting `Issuer`; ownership checks on any resource that references an `Issuer` — a pool's `issuer_id`, an engagement's `issuer_id`, an advance's `issuer_id`, a custodial account's `issuer_id`, or the issuer that owns a loan's, report's, payment's, or plan's pool — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `DocumentCustodian`, `X-User-ID` is the `id` of the acting `DocumentCustodian`, used to attribute certifications to the certifying custodian. When `X-User-Role` is `ApplicantOfficer`, `AgencyReviewer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands attribution (for example, to enforce segregation of duties at application approval) but does not compare it to any entity's `id`.

`ApplicantOfficer` authors, edits, and submits issuer applications. `AgencyReviewer` adjudicates applications, investor reports, corrective action plans, and portfolio transfers; closes delinquency breaches; and declares issuer default. `IssuerOfficer` performs all issuer-scoped operational work: engagements, pooling, loans, custodial accounts and their transactions, investor reporting, payment settlement, advance reimbursement, corrective plans, and financial updates. `DocumentCustodian` certifies pool loan files. `PlatformAdmin` registers document custodians and drives the logical clock. Read access is broad: issuers, custodians, pools, loans, engagements, and applications are listable by most roles, while custodial accounts, transactions, reports, payments, advances, breaches, plans, and transfers are readable by `IssuerOfficer`, `AgencyReviewer`, and `PlatformAdmin`.

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

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Both are validated as part of request-shape checking; a malformed value is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that starts at its initial value on creation and increments by exactly one on every modification, including modifications caused by system cascades rather than direct client writes. Every stateful resource additionally carries a `status` field whose value is drawn from that resource's state enumeration (§3). Every stateful resource additionally carries a `status` field whose value is drawn from that resource's state enumeration (§3).

One exception applies: `AccountTransaction` entries are an append-only ledger and carry only `id` and `created_at` — both `updated_at` and `version` are absent on transaction rows, since a posted entry is never mutated.

Any mutation that a state transition, threshold evaluation, or cascade applies to a resource — including recomputation of derived fields such as a pool's `aggregate_principal_cents` or an issuer's `advance_obligation_cents` when it is performed as part of a named transition on that resource — counts as a modification for `updated_at` and `version` purposes where the transition's side effects say so.

### 2.5. Monetary Values, Rates, and Precision

All monetary amounts are integers denominated in cents — there is no floating-point money anywhere in the system. All interest rates, delinquency rates, and liquidity ratios are integers denominated in basis points, where 10000 basis points equal one hundred percent.

Two rounding disciplines coexist and must not be confused. Delinquency rates are rounded half-up to the nearest integer basis point. Liquidity ratios, per-loan scheduled interest, the actual-collected payment variant, escrow tax splits, and the volume-tier net-worth requirement are floored — truncated toward zero — to integer cents or integer basis points. Wherever a calculation divides, the PRD states which discipline applies; a reader must be able to reconstruct each formula step for step from the prose in §2 and §3.

### 2.6. The Logical Clock

The server maintains a logical clock that is the sole source of "now" for all date-sensitive behavior: engagement-window coverage checks, monthly reporting periods, and engagement-end adjustments. Before any clock-setting call, the clock reads exactly `2026-09-01T00:00:00Z` as a fixed startup default and must never fall back to wall-clock time. A `PlatformAdmin` may advance the clock by supplying a `current_utc` timestamp; the capability exists for test-driving and operational simulation and returns the newly set `current_utc`.

### 2.7. Validation Ordering

When a request violates several rules, the server reports the earliest failing check in a fixed priority order, so that a caller always sees the most fundamental problem first. The order is: (1) authentication — presence and recognizability of the identity headers; (2) role authorization for the endpoint; (3) existence of every resource identifier, validated left to right — a dangling application id yields `ERR_APPLICATION_NOT_FOUND`, an issuer id `ERR_ISSUER_NOT_FOUND`, a custodian id `ERR_CUSTODIAN_NOT_FOUND`, an engagement id `ERR_ENGAGEMENT_NOT_FOUND`, a pool id `ERR_POOL_NOT_FOUND`, a loan id `ERR_LOAN_NOT_FOUND`, an account id `ERR_ACCOUNT_NOT_FOUND`, a report id `ERR_REPORT_NOT_FOUND`, a payment id `ERR_PAYMENT_NOT_FOUND`, an advance id `ERR_ADVANCE_NOT_FOUND`, a breach id `ERR_BREACH_NOT_FOUND`, a plan id `ERR_PLAN_NOT_FOUND`, and a transfer id `ERR_TRANSFER_NOT_FOUND`; (4) ownership, for `IssuerOfficer` write operations; (5) state-machine legality of the requested transition, where each resource family reports its own invalid-state error (for example `ERR_POOL_INVALID_STATE` for pools, `ERR_ACCOUNT_INVALID_STATE` for custodial accounts, and `ERR_REPORT_INVALID_STATE` for reports); (6) optimistic-concurrency version matching on guarded writes; (7) request shape — required fields present, enums valid, integers in range, dates parseable; (8) referential business rules such as insurer eligibility, note-rate bands, account-type uniqueness, report-period uniqueness, engagement-window disjointness, and engagement coverage; (9) safety and compliance gates such as application thresholds, segregation of duties, successor capitalization, and pool composition; and (10) funds and capacity checks such as custodial balances and frozen-account or non-active-issuer blocks. Thus, for example, a pool assemble attempted by the wrong issuer on a non-existent pool surfaces the not-found error before the ownership error, and a stale-version rejection surfaces before any request-shape error on the same write.

### 2.8. Optimistic Concurrency Control

Five write operations are guarded by optimistic concurrency control against a parent entity's `version`. Each guarded request must carry a non-optional expected-version field naming the client's last observed `version` of the parent; if another writer has advanced that version since the client read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot act on a parent state it has not observed. The guarded writes are: creating a pool, which requires `expected_issuer_version` matching the issuing issuer's current `version`; creating an investor report, which requires `expected_pool_version` matching the reported pool's current `version`; initiating a portfolio transfer, which requires `expected_defaulted_issuer_version` matching the defaulted issuer's current `version`; updating an issuer's financials, which requires `expected_issuer_version` matching that issuer's current `version`; and patching an issuer application, which requires `expected_application_version` matching the application's current `version`. Endpoints not named here take no version field at all.

### 2.9. Hierarchical Consistency and Cascades

The system maintains alignment between issuers and everything they own through automatic cascades. When an issuer leaves good standing, its custodial accounts freeze; when it recovers, they thaw; when it is extinguished, they close, its open advances are written off, and its pending pools are terminated. When an issuer defaults with live pools, those pools park in a transfer-pending posture until the transfer resolves. Conversely, child-level events roll upward: a loan's delinquency change recomputes its pool's delinquency rate, and a sufficiently severe rate opens a breach and moves the issuer to watch. These cascades run immediately within the triggering request — the consistency model is immediate, not eventual. For any request that names resources through payload foreign keys rather than nested paths, the server still validates the existence of each referenced resource, and a dangling reference yields the corresponding not-found error.

### 2.10. Ledger Invariants

Two invariants hold across every accepted posting. First, custodial reconciliation: for each custodial account, the `balance_cents` always equals the sum of deposit amounts minus the sum of disbursement amounts over all of the account's transactions, and always equals the sum of the account's two component balances — `principal_balance_cents` plus `interest_balance_cents` for a principal-and-interest account, `tax_balance_cents` plus `insurance_balance_cents` for a tax-and-insurance account. Any posting that would drive a component negative is rejected, so the invariant holds after every accepted transaction. Second, advance conservation: the sum of `amount_cents` over all advances in `OPEN` status across all issuers changes only through sanctioned pairs — a settle-as-advance raises it and the matching reimbursement lowers it by the same amount, a transfer acceptance moves open advances from the defaulted issuer to the successor with zero change to the global total, and extinguishment write-off is the only sanctioned reduction, always paired with the issuer reaching `EXTINGUISHED`.

## 3. Business Logic & Workflows

### 3.1. Becoming an Issuer: The Application Lifecycle

An `ApplicantOfficer` begins by creating an issuer application in `DRAFT` status, declaring the applicant's `legal_name`, `net_worth_cents`, `liquid_assets_cents`, `origination_experience_months`, `branch_count` (at least one operating branch), and `annual_origination_volume_cents` covering the prior twelve months; `unused_credit_lines_cents` may be supplied and defaults to zero when omitted. On creation the server computes and exposes a read-only `net_worth_requirement_cents`: the tiered minimum net worth the applicant must meet. The requirement is the larger of two components — a branch component of two hundred fifty million cents (two and a half million dollars) plus twenty-five million cents (two hundred fifty thousand dollars) for each branch beyond the first, and a volume component equal to the applicant's prior-year origination volume multiplied by ten basis points (one tenth of one percent) and floored to integer cents. When the branch component dominates, the requirement is the base plus the per-branch add-on; when the volume component dominates, the requirement is the floored volume share — floor, not round.

While the application is in `DRAFT`, the officer may patch its financial fields; every patch must carry `expected_application_version` matching the application's current `version`, and each accepted patch recomputes `net_worth_requirement_cents` and increments the application's `version`.

Submission moves the application from `DRAFT` to `SUBMITTED` and is gated by three threshold checks, enforced at submit time and re-checked on every revision patch through the recomputed requirement: the declared `net_worth_cents` must meet or exceed `net_worth_requirement_cents` (else `ERR_NET_WORTH_DEFICIENT`); `liquid_assets_cents` must not exceed `net_worth_cents`, since liquid assets are a subset of net worth (else `ERR_LIQUIDITY_EXCEEDS_NET_WORTH`); and `origination_experience_months` must be at least 24 (else `ERR_INSUFFICIENT_EXPERIENCE`). An application not in `DRAFT` cannot be submitted — the attempt fails with `ERR_APPLICATION_INVALID_STATE`.

An `AgencyReviewer` then opens review, moving `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the reviewer has three dispositions. Approval moves the application to `APPROVED` and, in the same action, creates an `Issuer` in `ACTIVE` status whose `application_id` points back to the application and whose `legal_name`, `net_worth_cents`, `liquid_assets_cents`, and `unused_credit_lines_cents` are copied from the approved application as a snapshot; the application's read-only `approved_issuer_id`, null until this moment, is set to the new issuer's id. Denial moves the application to the terminal `DENIED` state. A request for revision moves it to `REVISION_REQUESTED`, from which the applicant's next patch returns it to `DRAFT` — the application may loop through draft, review, and revision repeatedly. Approval and denial share a segregation-of-duties rule: the acting reviewer's user id must differ from the id of the officer who submitted the application, and a same-user adjudication is rejected with `ERR_SEGREGATION_OF_DUTIES`. Any disposition attempted on an application not in `UNDER_REVIEW` fails with `ERR_APPLICATION_INVALID_STATE`.

### 3.2. Custodians and Engagement Windows

Before any pool can be created or certified, the issuer must have a document custodian under engagement. A `PlatformAdmin` registers each custodian firm by its `firm_name`. An `IssuerOfficer` then engages a custodian by creating a custodian engagement naming the `custodian_id` and the engaging `issuer_id` together with a `window_start` and `window_end`, both dates in year-month-day form. The window is half-open: it covers every date from `window_start` inclusive up to but not including `window_end`. Engagement creation requires the engaging issuer to be `ACTIVE`; an issuer that is `SUSPENDED`, `DEFAULTED`, or `EXTINGUISHED` cannot open new engagements and the attempt is rejected with `ERR_ISSUER_NOT_ACTIVE`.

Engagements are born `ACTIVE`. Two active engagements on the same custodian-and-issuer pair must have disjoint windows: windows that merely touch, where one engagement's `window_end` equals the other's `window_start`, are allowed, but any positive overlap is rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP`. Coverage is checked twice downstream — at pool creation and at certification — each time against the server's logical clock date: the check requires an active engagement for the pool's custodian-and-issuer pair whose window contains the request date, and a gap is rejected with `ERR_CUSTODIAN_ENGAGEMENT_GAP`.

An `IssuerOfficer` ends an engagement by an explicit end action, moving it from `ACTIVE` to the terminal `ENDED` state; ending an already-ended engagement fails with `ERR_ENGAGEMENT_INVALID_STATE`, and ending an engagement owned by another issuer fails with `ERR_NOT_RESOURCE_OWNER`. If the recorded `window_end` lies after the request date, the end action adjusts `window_end` down to the request date, preserving the half-open semantics.

### 3.3. Pool Assembly, Loan Composition, and Certification

An `IssuerOfficer` creates a pool in `DRAFT` status by naming the `issuer_id` of the issuing issuer, the `custodian_id` responsible for its loan files, a `pool_type`, a `term_months`, and the security's `note_rate_bps`. The create must carry `expected_issuer_version` matching the issuer's current `version`; a stale read is rejected with `ERR_STALE_VERSION` because issuer-level mutations may have changed pooling eligibility since the client computed it. The custodian-engagement coverage check runs at creation against the current clock date. Creating the pool increments the issuing issuer's `version` by one.

The pool type constrains the term. A `SINGLE_FAMILY` pool runs 360 or 180 months; a `MANUFACTURED_HOME` pool runs exactly 240 months; a `MULTIFAMILY` pool runs exactly 360 months. Any other combination is rejected with `ERR_POOL_TERM_INVALID`.

Loans join a pool while it is in `DRAFT`. Each loan is created with a payload containing the `pool_id`, its `principal_balance_cents`, its mortgage `note_rate_bps`, its `government_insurance` program — one of `FHA`, `VA`, `USDA`, or `PIH` — and the `escrow_monthly_cents` collected with each payment for taxes and insurance. Two referential gates apply at loan creation. The insurance program must be allowed for the pool type: a `MULTIFAMILY` pool accepts only `FHA` loans, and any other program there is rejected with `ERR_INSURER_NOT_ALLOWED`. The loan's note rate must sit within a band above the security's note rate — at least 50 basis points above the pool's `note_rate_bps` and at most 150 basis points above it, both bounds inclusive; a loan outside the band is rejected with `ERR_LOAN_NOTE_RATE_OUT_OF_RANGE`. Each accepted loan starts in `CURRENT` status and triggers recomputation of the pool's read-only `aggregate_principal_cents` and `delinquency_rate_bps`.

Assembly moves a pool from `DRAFT` to `ASSEMBLED`. The assemble request is evaluated against a sequence of gates: the pool must be in `DRAFT` (else `ERR_POOL_INVALID_STATE`); the acting officer must own the pool's issuer (else `ERR_NOT_RESOURCE_OWNER`); the issuer must be `ACTIVE` (else `ERR_ISSUER_NOT_ACTIVE`); the pool must contain at least one loan (else `ERR_POOL_EMPTY`); the loan count must not exceed the per-type cap — three loans for `SINGLE_FAMILY`, three for `MANUFACTURED_HOME`, and two for `MULTIFAMILY` (else `ERR_POOL_LOAN_COUNT_EXCEEDED`); and the pool's `aggregate_principal_cents` must be at least one hundred million cents — exactly 100000000 cents, a one-million-dollar minimum pool balance (else `ERR_POOL_BELOW_MINIMUM_PRINCIPAL`).

Certification is performed by the `DocumentCustodian` and is the pool's gateway out of `ASSEMBLED`. The custodian records a loan-file certification carrying a `decision` and, when the decision flags exceptions, a non-empty `exception_loan_ids` array of the flagged loan ids; for a clean certification the array is empty. A certification attempt on a pool not in `ASSEMBLED` fails with `ERR_POOL_INVALID_STATE`, and the custodian-engagement coverage check runs again at the certification date — a lapsed window yields `ERR_CUSTODIAN_ENGAGEMENT_GAP`. When the `decision` is `CERTIFIED` with an empty `exception_loan_ids`, the certification is recorded with the pool's `pool_id` and the certifying `custodian_id`, and the pool advances `ASSEMBLED` to `CERTIFIED`. When the `decision` is `EXCEPTION`, the certification is recorded, the flagged loans are stored, and the pool stays in `ASSEMBLED` — a retry loop in which the custodian re-certifies until a clean certification lands.

Activation moves a pool from `CERTIFIED` to `LIVE`; an attempt from any other state fails with `ERR_POOL_INVALID_STATE` — attempting to activate a pool that was never certified is the case reported as `ERR_CERTIFICATION_REQUIRED` — and the issuer must still be `ACTIVE` (else `ERR_ISSUER_NOT_ACTIVE`). Activation has a notable side effect: it creates the pool's first investor report, a `DRAFT` report for the current clock month with a full-collection assumption (a collection rate of ten thousand basis points), with its scheduled, actual, and advance figures computed at creation exactly as any monthly report's would be.

A live pool terminates only when it is fully wound down: termination requires the pool in `LIVE` (else `ERR_POOL_INVALID_STATE`), every loan paid off so that `aggregate_principal_cents` is exactly zero (else `ERR_POOL_NOT_FULLY_PAID`), and no investor report for the pool sitting in `DRAFT` or `SUBMITTED` (else `ERR_UNRESOLVED_RECORDS_EXIST`). Termination lands the pool in the terminal `TERMINATED` state.

### 3.4. Custodial Accounts and the Escrow Split

Every issuer maintains custodial accounts that strictly separate principal-and-interest funds from tax-and-insurance escrow. An `IssuerOfficer` opens an account by naming the owning `issuer_id` and an `account_type` of either `P_AND_I` or `T_AND_I`. At most one account of each type may exist per issuer; a duplicate type is rejected with `ERR_ACCOUNT_TYPE_DUPLICATE`. Accounts are born `ACTIVE`.

Each account exposes four read-only component balances and a total. A `P_AND_I` account carries `principal_balance_cents` and `interest_balance_cents`; a `T_AND_I` account carries `tax_balance_cents` and `insurance_balance_cents`; in both cases `balance_cents` is the sum of the account's two components. These are never written directly — they move only through posted transactions and system settlements.

An `IssuerOfficer` posts a transaction to an account by supplying a `component`, an `amount_cents` strictly greater than zero, and optionally a `loan_id` as an informational reference to the loan the funds were collected from. The `component` is one of `PRINCIPAL`, `INTEREST`, `TAX`, `INSURANCE`, or `ESCROW`. The account must be `ACTIVE`: a posting to a `FROZEN` or `CLOSED` account is rejected with `ERR_ACCOUNT_FROZEN`. Each accepted posting is recorded as an `AccountTransaction` with its `account_id`, a `direction` of `DEPOSIT` or `DISBURSEMENT`, the posted `component`, and the `amount_cents`; the transaction updates the corresponding component balance, and the custodial reconciliation invariant of §2.10 holds after every posting.

The `ESCROW` component has special semantics and is valid for deposits to a `T_AND_I` account: the deposit is split automatically into its tax and insurance shares. The tax share is the posted amount multiplied by six thousand basis points — sixty percent — floored to integer cents, and the insurance share is the remainder of the amount after the tax share, so any rounding remainder lands on insurance, never the reverse. The split is exposed on the transaction as the read-only `tax_split_cents` and `insurance_split_cents`, both null for non-escrow postings.

A raw disbursement that exceeds the targeted component's balance is rejected with `ERR_INSUFFICIENT_CUSTODIAL_FUNDS`, so no component can go negative. This error fires only on raw disbursement postings — never on payment settlement, which routes around shortfalls by design as described in §3.6.

### 3.5. Monthly Reporting and the Pass-Through Obligation

For each calendar month, the issuer reports to investors on each of its pools. An `IssuerOfficer` creates a monthly investor report by naming the `pool_id` and the `period_month` in year-month form, together with the `collection_rate_bps` observed for the month and an `expected_pool_version` matching the pool's current `version`; a stale pool read is rejected with `ERR_STALE_VERSION` because pool membership or certification changes alter the payment computation basis.

At report creation the server pins three read-only figures. The `scheduled_payment_cents` is the scheduled variant of the pass-through payment: for every loan of the pool not yet `PAID_OFF`, the loan's scheduled monthly interest is computed as its `principal_balance_cents` multiplied by the pool's `note_rate_bps`, divided by ten thousand, divided by twelve months, and floored to integer cents — and these per-loan floored amounts are then summed. The evaluation order is pinned: each loan's interest is rounded first, then summed; summing first and rounding once is a different, wrong algorithm. Because the security's note rate is the pass-through rate, the scheduled figure is what investors are owed, and it assumes full collection. The `actual_collected_cents` is the actual variant: the unrounded aggregate ratio — the sum over the same loans of each principal balance multiplied by the pool note rate, divided by ten thousand and by twelve — is scaled by the month's `collection_rate_bps` out of ten thousand and floored exactly once. The actual variant therefore differs from the scheduled variant by both the collection rate and the rounding order; it is not a per-loan rounding of actuals. The `advance_required_cents` is the difference between the scheduled and actual figures. These values are pinned at creation and never recomputed later.

A `DRAFT` report is submitted by the issuer's officer, moving it to `SUBMITTED`. Submission requires that the report's pool is in `CERTIFIED` or `LIVE` and belongs to the acting issuer (else `ERR_NOT_RESOURCE_OWNER`), that the report is in `DRAFT` (else `ERR_REPORT_INVALID_STATE`), and that no other report already exists for the same pool and `period_month` (else `ERR_DUPLICATE_REPORT_PERIOD`). An `AgencyReviewer` then accepts or rejects the submission from `SUBMITTED` (any other state fails with `ERR_REPORT_INVALID_STATE`). Rejection lands the report in terminal `REJECTED`. Acceptance lands it in terminal `ACCEPTED` and creates the month's pass-through payment: a payment whose `report_id` points to the accepted report, whose `amount_cents` equals the report's `scheduled_payment_cents` — the full scheduled amount, owed regardless of borrower delinquency — whose `funding_source` is null until settled, and whose status begins at `DUE`.

### 3.6. Settlement, Advances, and Issuer Liquidity

Settlement of a `DUE` payment is the issuer's monthly moment of truth, and it has two paths chosen by the state of the issuer's principal-and-interest account rather than by the caller. If the issuer's `P_AND_I` account is `ACTIVE` and its combined principal plus interest balances cover the payment's `amount_cents`, the settle succeeds through the custodial path: the payment moves `DUE` to `PAID`, its `funding_source` is recorded as `CUSTODIAL`, and a disbursement transaction for the full amount is posted against the `P_AND_I` account. That disbursement draws from the interest bucket first — up to the full `interest_balance_cents` — and only then from the principal bucket for whatever remains; the interest-before-principal order is pinned. If after both buckets the amount cannot be covered, the settle does not debit partially — it routes to the advance path instead.

The advance path applies whenever the custodial path is unavailable: the account not `ACTIVE`, or the combined balances short of the amount. There the payment moves `DUE` to `ADVANCED`, its `funding_source` is recorded as `ADVANCE`, and a liquidity advance is created for the pool's issuer in `OPEN` status with an `amount_cents` equal to the payment amount and a `payment_id` pointing at the payment it funded. Settling a payment not in `DUE` fails with `ERR_PAYMENT_INVALID_STATE` on either path.

Every advance movement re-prices the issuer's liquidity posture. An issuer's read-only `advance_obligation_cents` is the sum of `amount_cents` over its `OPEN` advances. Two ratios are computed against that obligation, both floored to integer basis points and both null whenever the obligation is zero. The `liquidity_ratio_excluding_credit_bps` divides the issuer's `liquid_assets_cents` alone by the obligation, scaled to basis points. The `liquidity_ratio_including_credit_bps` adds the issuer's `unused_credit_lines_cents` to the numerator against the same denominator. Each ratio is floored independently from its own numerator; the including ratio is not obtained by adding a floored credit-line contribution to the excluding ratio, so the exact difference of the two floored ratios is not pinned — only that the including ratio is never less than the excluding ratio. The excluding ratio is the issuer's self-monitoring and hard-floor measure; the including ratio gates successor eligibility at transfer acceptance.

Immediately after every ratio recomputation — on advance creation, on reimbursement, on an issuer financial patch, and on transfer acceptance — the liquidity threshold evaluation runs. If the excluding ratio is not null and falls strictly below three hundred basis points — a three-percent hard floor — an issuer in `ACTIVE` or `WATCH` moves to `SUSPENDED`, and its custodial accounts freeze `ACTIVE` to `FROZEN`. A ratio of exactly three hundred does not suspend. Recovery works in reverse: when a reimbursement or financial update restores the excluding ratio to at least three hundred, a suspended issuer with no open or mitigating breach returns to `ACTIVE` and its accounts thaw `FROZEN` to `ACTIVE`; if a breach still stands, it returns to `WATCH` instead, accounts thawing either way. While `SUSPENDED`, pool assembly and activation, engagement creation, and custodial deposits and disbursements are blocked, but pass-through settlement continues — necessarily down the advance path, since the accounts are frozen. Separately, a soft monitoring threshold of five hundred basis points — five percent — on the including ratio gates successor capitalization in §3.8.

An `IssuerOfficer` updates the issuer's `liquid_assets_cents` and `unused_credit_lines_cents` through a financial patch that must carry `expected_issuer_version` matching the issuer's current `version`; staleness is rejected with `ERR_STALE_VERSION`, and the patch recomputes the ratios and runs the threshold evaluation. An open advance is reimbursed by the issuer's officer — reimbursement of a non-`OPEN` advance fails with `ERR_ADVANCE_INVALID_STATE`, and another issuer's advance fails with `ERR_NOT_RESOURCE_OWNER` — moving it to terminal `REIMBURSED` and again recomputing the obligation and ratios, potentially lifting a suspension as described above.

### 3.7. Delinquency, Breaches, and Corrective Action

A loan marches down a delinquency ladder driven by the issuer's officer, who moves it by naming a `to_status`. From `CURRENT` a loan becomes `DELINQ_30`; from `DELINQ_30` it becomes `DELINQ_60`; from `DELINQ_60` it becomes `DELINQ_90_PLUS`; from `DELINQ_90_PLUS` it becomes `FORECLOSURE`. Cures move directly back: `DELINQ_30`, `DELINQ_60`, or `DELINQ_90_PLUS` may each return to `CURRENT`. From any non-terminal status a loan may move to `PAID_OFF`. Any other pairing — a skipped rung, a move out of `FORECLOSURE`, or any move out of `PAID_OFF` — is rejected with `ERR_LOAN_INVALID_STATE`, and acting on a loan owned by another issuer fails with `ERR_NOT_RESOURCE_OWNER`.

Every delinquency change and every payoff recomputes the pool's read-only `delinquency_rate_bps`. The numerator is the total `principal_balance_cents` of the pool's loans in `DELINQ_60`, `DELINQ_90_PLUS`, or `FORECLOSURE`; the denominator is the pool's `aggregate_principal_cents`, the total over loans not `PAID_OFF`. `DELINQ_30` is never counted in the delinquent set, and a paid-off loan leaves both numerator and denominator. The rate is the numerator scaled to basis points against the denominator and rounded half-up; when the denominator is zero the rate is zero.

Immediately after every recompute, the pool threshold evaluation runs. When the recomputed rate is at least five hundred basis points — five percent of aggregate principal, with exactly five hundred breaching — and no breach for the pool is currently `OPEN` or `MITIGATING`, the system creates a delinquency breach in `OPEN` status recording the owning `issuer_id`, the `pool_id`, and the current rate as `delinquency_rate_bps_at_breach`; if the issuer is `ACTIVE` it simultaneously moves to `WATCH`, remaining fully operational — pool transitions continue while on watch. Closing a breach is never automatic: even when the rate later falls back below threshold, the breach stays open until an `AgencyReviewer` closes it, and the issuer stays at `WATCH` until closure.

The issuer answers a breach with a corrective action plan, created against a `breach_id` with a free-text `plan_summary` and a `target_cure_month` in year-month form committing to a cure date. Plans are born `SUBMITTED`. An `AgencyReviewer` accepts or rejects from `SUBMITTED` — anything else fails with `ERR_PLAN_INVALID_STATE`. Acceptance moves the plan to `ACCEPTED` and the breach from `OPEN` to `MITIGATING`, and re-evaluates the issuer: when this was the only blocking breach and liquidity is not below the hard floor, the issuer returns from `WATCH` to `ACTIVE`. Rejection moves only the plan to `REJECTED`.

Breach closure is an agency action available from `OPEN` or `MITIGATING` — closing from any other state fails with `ERR_BREACH_INVALID_STATE` — and requires the breaching pool's current `delinquency_rate_bps` to be back below the five-hundred-basis-point threshold (else `ERR_BREACH_STILL_BREACHING`). Closure lands the breach in terminal `CLOSED` and re-evaluates the issuer exactly as plan acceptance does.

### 3.8. Default, Portfolio Transfer, and Extinguishment

Default is an agency declaration. An `AgencyReviewer` declares an issuer defaulted from `ACTIVE`, `WATCH`, or `SUSPENDED` — from any other state the attempt fails with `ERR_ISSUER_INVALID_STATE` — moving it to `DEFAULTED` and freezing its custodial accounts (accounts already frozen stay frozen).

With a defaulted issuer on the books, the agency initiates a portfolio transfer by naming the `defaulted_issuer_id`, the `successor_issuer_id`, and an `expected_defaulted_issuer_version` matching the defaulted issuer's current `version`; a stale read is rejected with `ERR_STALE_VERSION` because a new pool or advance may have entered the extinguishment set since the client looked. Initiation increments the defaulted issuer's `version` and parks every one of its `LIVE` pools into `TRANSFER_PENDING`, suspending their custodial exposure pending the successor's answer.

The transfer resolves in one of two terminal ways, both agency actions requiring the transfer still in `INITIATED` (else `ERR_TRANSFER_INVALID_STATE`). Acceptance is gated on the successor: the successor issuer must be `ACTIVE` (else `ERR_SUCCESSOR_NOT_ACTIVE`), and after assuming the defaulted issuer's advance obligations its `liquidity_ratio_including_credit_bps` — liquid assets plus unused credit lines against the combined obligation — must remain at least five hundred basis points, the monitoring threshold (else `ERR_SUCCESSOR_UNDERCAPITALIZED`). An accepted transfer moves to `COMPLETED` and executes the full cascade: every `TRANSFER_PENDING` pool returns to `LIVE` with its `issuer_id` reassigned to the successor; every `OPEN` advance of the defaulted issuer is reassigned to the successor with no change to the global open-advance total; the defaulted issuer moves to `EXTINGUISHED` and its frozen custodial accounts close `FROZEN` to `CLOSED`; and the successor's obligation and ratios are recomputed with the liquidity threshold evaluation run on the successor. Rejection moves the transfer to `REJECTED` and executes the extinguishment cascade instead: every `TRANSFER_PENDING` pool terminates; the defaulted issuer moves to `EXTINGUISHED`; its accounts close; and every `OPEN` advance is written off to the terminal `WRITTEN_OFF` status — the advance's obligation removed from the issuer and the only sanctioned reduction of the global open-advance total, always paired with the issuer's extinguishment.

Account status tracks these issuer cascades throughout: an account freezes when its issuer suspends, defaults, or is extinguished; thaws when the issuer recovers to active or when a successor acceptance re-activates a transferred portfolio; and closes only on extinguishment. Posting to a frozen or closed account remains blocked with `ERR_ACCOUNT_FROZEN` at every stage.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Error responses follow §2.2's error envelope with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/issuer-applications` | Create issuer application in DRAFT | ApplicantOfficer |
| GET | `/issuer-applications` | List issuer applications | ApplicantOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/issuer-applications/{id}` | Get an issuer application | ApplicantOfficer, AgencyReviewer, PlatformAdmin |
| PATCH | `/issuer-applications/{id}` | Edit application fields; from REVISION_REQUESTED also returns to DRAFT | ApplicantOfficer |
| POST | `/issuer-applications/{id}/submit` | Submit application for review (runs threshold gates) | ApplicantOfficer |
| POST | `/issuer-applications/{id}/review` | Open review | AgencyReviewer |
| POST | `/issuer-applications/{id}/request-revision` | Send application back for revision | AgencyReviewer |
| POST | `/issuer-applications/{id}/approve` | Approve application; creates Issuer | AgencyReviewer |
| POST | `/issuer-applications/{id}/deny` | Deny application | AgencyReviewer |
| GET | `/issuers` | List issuers (filterable by application) | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| GET | `/issuers/{id}` | Get issuer incl. computed advance obligations and liquidity ratios | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| PATCH | `/issuers/{id}/financials` | Update issuer liquid assets / unused credit lines (OCC-guarded) | IssuerOfficer |
| POST | `/issuers/{id}/default` | Declare issuer default (agency action) | AgencyReviewer |
| POST | `/document-custodians` | Register a document custodian | PlatformAdmin |
| GET | `/document-custodians` | List custodians | PlatformAdmin, AgencyReviewer, IssuerOfficer, DocumentCustodian |
| GET | `/document-custodians/{id}` | Get a custodian | PlatformAdmin, AgencyReviewer, IssuerOfficer, DocumentCustodian |
| POST | `/custodian-engagements` | Create custodian engagement with half-open window | IssuerOfficer |
| GET | `/custodian-engagements` | List engagements (filterable by custodian, issuer) | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| GET | `/custodian-engagements/{id}` | Get an engagement | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| POST | `/custodian-engagements/{id}/end` | End an engagement | IssuerOfficer |
| POST | `/pools` | Create pool in DRAFT (OCC-guarded on issuer version) | IssuerOfficer |
| GET | `/pools` | List pools (filterable by issuer, custodian) | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| GET | `/pools/{id}` | Get pool incl. computed aggregate principal and delinquency rate | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| POST | `/pools/{id}/assemble` | Assemble pool (composition gates) | IssuerOfficer |
| POST | `/pools/{id}/certifications` | Custodian certifies loan files (CERTIFIED or EXCEPTION) | DocumentCustodian |
| GET | `/pools/{id}/certifications` | List certifications for a pool | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| POST | `/pools/{id}/activate` | Activate certified pool; creates first monthly report in DRAFT | IssuerOfficer |
| POST | `/pools/{id}/terminate` | Terminate a fully-paid pool with no open reports | IssuerOfficer |
| POST | `/loans` | Add a loan to a DRAFT pool | IssuerOfficer |
| GET | `/loans` | List loans (filterable by pool) | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| GET | `/loans/{id}` | Get a loan | IssuerOfficer, AgencyReviewer, PlatformAdmin, DocumentCustodian |
| POST | `/loans/{id}/delinquency-status` | Move a loan along the delinquency ladder or to PAID_OFF | IssuerOfficer |
| POST | `/custodial-accounts` | Open a custodial account (P_AND_I or T_AND_I) for an issuer | IssuerOfficer |
| GET | `/custodial-accounts` | List custodial accounts (filterable by issuer) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/custodial-accounts/{id}` | Get account incl. component balances | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/custodial-accounts/{id}/transactions` | Post a deposit or disbursement; ESCROW deposits split per escrow share | IssuerOfficer |
| GET | `/custodial-accounts/{id}/transactions` | List transactions for an account | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/investor-reports` | Create monthly investor report (OCC-guarded on pool version) | IssuerOfficer |
| GET | `/investor-reports` | List investor reports (filterable by pool) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/investor-reports/{id}` | Get an investor report | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/investor-reports/{id}/submit` | Submit report | IssuerOfficer |
| POST | `/investor-reports/{id}/accept` | Accept report; generates the month's payment DUE | AgencyReviewer |
| POST | `/investor-reports/{id}/reject` | Reject report | AgencyReviewer |
| GET | `/pass-through-payments` | List pass-through payments (filterable by report) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/pass-through-payments/{id}` | Get a payment | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/pass-through-payments/{id}/settle` | Settle from the P_AND_I account, or fund by advance when custodial funds insufficient | IssuerOfficer |
| GET | `/liquidity-advances` | List advances (filterable by issuer, payment) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/liquidity-advances/{id}` | Get an advance | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/liquidity-advances/{id}/reimburse` | Reimburse an open advance | IssuerOfficer |
| GET | `/delinquency-breaches` | List breaches (filterable by issuer, pool) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/delinquency-breaches/{id}` | Get a breach | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/delinquency-breaches/{id}/close` | Close a breach whose pool is back under threshold (agency action) | AgencyReviewer |
| POST | `/corrective-action-plans` | Submit a corrective action plan against a breach | IssuerOfficer |
| GET | `/corrective-action-plans` | List plans (filterable by breach) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/corrective-action-plans/{id}` | Get a plan | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/corrective-action-plans/{id}/accept` | Accept plan; breach moves to MITIGATING; issuer re-evaluated | AgencyReviewer |
| POST | `/corrective-action-plans/{id}/reject` | Reject plan | AgencyReviewer |
| POST | `/portfolio-transfers` | Initiate defaulted-issuer portfolio transfer (OCC-guarded); cascades live pools to TRANSFER_PENDING | AgencyReviewer |
| GET | `/portfolio-transfers` | List transfers (filterable by defaulted or successor issuer) | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| GET | `/portfolio-transfers/{id}` | Get a transfer | IssuerOfficer, AgencyReviewer, PlatformAdmin |
| POST | `/portfolio-transfers/{id}/accept` | Successor accepts; pools and advances move; defaulted issuer extinguished; terminal COMPLETED | AgencyReviewer |
| POST | `/portfolio-transfers/{id}/reject` | Successor rejects; portfolio extinguished, pools terminated, advances written off; terminal REJECTED | AgencyReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_ISSUER_NOT_FOUND` | 404 |
| `ERR_CUSTODIAN_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_POOL_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_ADVANCE_NOT_FOUND` | 404 |
| `ERR_BREACH_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_APPLICATION_INVALID_STATE` | 409 |
| `ERR_ISSUER_INVALID_STATE` | 409 |
| `ERR_POOL_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_INVALID_STATE` | 409 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_PAYMENT_INVALID_STATE` | 409 |
| `ERR_ADVANCE_INVALID_STATE` | 409 |
| `ERR_BREACH_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_TRANSFER_INVALID_STATE` | 409 |
| `ERR_ENGAGEMENT_INVALID_STATE` | 409 |
| `ERR_NET_WORTH_DEFICIENT` | 422 |
| `ERR_LIQUIDITY_EXCEEDS_NET_WORTH` | 422 |
| `ERR_INSUFFICIENT_EXPERIENCE` | 422 |
| `ERR_POOL_TERM_INVALID` | 422 |
| `ERR_INSURER_NOT_ALLOWED` | 422 |
| `ERR_LOAN_NOTE_RATE_OUT_OF_RANGE` | 422 |
| `ERR_ACCOUNT_TYPE_DUPLICATE` | 422 |
| `ERR_DUPLICATE_REPORT_PERIOD` | 422 |
| `ERR_ENGAGEMENT_WINDOW_OVERLAP` | 422 |
| `ERR_CUSTODIAN_ENGAGEMENT_GAP` | 422 |
| `ERR_POOL_EMPTY` | 422 |
| `ERR_POOL_LOAN_COUNT_EXCEEDED` | 422 |
| `ERR_POOL_BELOW_MINIMUM_PRINCIPAL` | 422 |
| `ERR_POOL_NOT_FULLY_PAID` | 422 |
| `ERR_CERTIFICATION_REQUIRED` | 422 |
| `ERR_UNRESOLVED_RECORDS_EXIST` | 422 |
| `ERR_ACCOUNT_FROZEN` | 422 |
| `ERR_INSUFFICIENT_CUSTODIAL_FUNDS` | 422 |
| `ERR_ISSUER_NOT_ACTIVE` | 422 |
| `ERR_SUCCESSOR_NOT_ACTIVE` | 422 |
| `ERR_SUCCESSOR_UNDERCAPITALIZED` | 422 |
| `ERR_BREACH_STILL_BREACHING` | 422 |
