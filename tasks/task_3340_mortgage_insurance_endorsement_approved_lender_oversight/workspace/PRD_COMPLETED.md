# FHA MI Endorsement & Approved Lender Oversight API — Product Requirements Document

## 1. Introduction

This document specifies the Mortgage Insurance Endorsement and Approved Lender Oversight platform operated on behalf of the Federal Housing Administration single-family mortgage insurance program. The platform governs the full oversight arc of an approved lender: admission to the program through a desk and field review backed by audited financials, endorsement of individual loan cases against program handbook requirements including appraisal and minimum property standards, collection of upfront and annual mortgage insurance premiums with vintage-dependent cancellation rules, post-endorsement quality control reviews that apply a weighted defect taxonomy and can trigger indemnification, and the default-servicing pipeline in which a servicer must exhaust a six-tier loss mitigation waterfall before filing an insurance claim — either conveying the property or claiming without conveyance.

Two properties of this domain shape the design. First, oversight is adversarial: agency reviewers, approving officials, lender officers, servicer officers, and claims examiners act on the same records with strictly segregated duties, and the system must record who did what so that conflicts of interest (an approver who also advanced the application, a post-endorsement reviewer who originally endorsed the case) are detected and rejected rather than trusted. Second, money is unforgiving: net worth floors, premium calculations, claim payments, and indemnification recoveries are all integer-cent computations with pinned rounding orders, and several derived figures (a lender's endorsed volume, a case's retained premiums) are compensating ledgers that must reconcile exactly when a decision is voided or reversed. All API resources are mounted under the `/mi` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the caller, and `X-User-Role` naming the caller's role. A request missing either header, or carrying a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the endpoint — or, on the lender lifecycle endpoint, not permitted for the requested action — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `PlatformAdmin` — agency platform operator; onboards lender applications and drives the logical clock.
- `LenderOfficer` — operations officer of an approved lender; files audited financials, originates and submits loan cases, delivers and transfers appraisals, opens repair escrows, executes indemnification agreements, and resubmits returned applications.
- `ServicerOfficer` — servicing arm of the approved lender; declares defaults, disburses escrows, bills and cancels annual MIP, works the loss mitigation waterfall, and files claims.
- `FhaReviewer` — agency reviewer; advances or returns lender applications, decides financial filings and appraisals, runs endorsement reviews, opens post-endorsement reviews, records defects, and closes reviews.
- `FhaApprover` — agency approving official; approves, suspends, reinstates, and terminates lenders, voids endorsements, confirms or dismisses defects, and drafts indemnification agreements.
- `ClaimsExaminer` — agency claims examiner; decides claims and records indemnification recoveries.

Identity semantics differ by role. When `X-User-Role` is `LenderOfficer` or `ServicerOfficer`, `X-User-ID` is the `id` of the acting `Lender`; ownership checks on any resource that references a lender — directly, or through a loan case's `lender_id`, or through the parent chain of filings, appraisals, escrows, reviews, and claims — compare that lender id to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `FhaReviewer`, `FhaApprover`, or `ClaimsExaminer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `advanced_by_user_id` or `approved_by_user_id` on a `Lender`, `decided_by_user_id` on a `FinancialFiling` or `InsuranceClaim`, `reviewer_user_id` on a `PostEndorsementReview`, or `created_by_user_id` / `confirmed_by_user_id` on a `Defect`) but does not compare it to any entity's `id`. Read endpoints (every GET operation) perform no ownership check: any authenticated role may read any resource, and the ownership comparison is enforced only on mutating operations.

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
- Requests to an unknown path, or to a known path with an unsupported method, are rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 and is clamped to a minimum of 1 and a maximum of 100; `offset` defaults to 0 and is clamped to a minimum of 0; a non-integer value for either falls back to its default rather than an error. Results are sorted by `created_at` ascending, with ties broken by creation order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` + `limit` is below `total_count`.

### 2.4. The Logical Clock and Common Resource Properties

The platform runs on a logical clock, not wall-clock time. At startup, before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` advances it by supplying a target instant `to_iso8601` through an admin-only test-driving capability: any parseable ISO 8601 instant is accepted as supplied (no monotonicity check), a missing or malformed value is rejected with `ERR_VALIDATION`, and the response is HTTP 200 with a `data` object echoing the resulting instant as `current_utc`. Setting the clock fires two time-based sweeps: every `ACCEPTED` appraisal whose `expiry_date` is at or before the new logical date becomes `EXPIRED`, and every `OPEN` repair escrow whose `end_date` is strictly before the new logical date becomes `EXPIRED`. Several timestamps elsewhere in the system — `endorsement_date`, `default_date`, `closed_at`, `evaluated_at` — are stamped from this same logical clock at the moment the triggering action completes.

Every entity in the platform carries the common resource properties: `id`, a server-minted UUID with no type prefix, rendered in the canonical hyphenated string form (five hexadecimal groups of 8, 4, 4, 4, and 12 digits joined by hyphens); `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped from the server's wall clock rather than the logical clock; `updated_at`, refreshed on every mutation in the same format from the same wall-clock source; and `version`, an integer that starts at 1 and increments by 1 on every mutation of that entity. The lender is the exception to that blanket rule: a lender's `version` increments by exactly 1 only where a workflow rule says so — on every status-change action (§3.1) and on the submission and the decision of a financial filing — while the computed-field reconciliations that endorsement, endorsement-voiding, and filing acceptance perform on the lender (`endorsed_volume_cents`, `net_worth_variant`, `required_net_worth_cents`, `last_accepted_filing_id`) never by themselves increment it. Mutating any other entity increments that entity's own `version`, with one further computed-field exception: refreshing a case's `mip_retained_cents` when an annual premium is billed (§3.3) does not increment the case's `version`.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent lender's `version`. Both require the non-optional input field `expected_lender_version` carrying the client's last observed `version` of the parent `Lender`, and both reject with `ERR_STALE_VERSION` (HTTP 412) when that value does not match the lender's current `version`.

The first guard covers submitting an audited financial filing: because accepting a new filing for the same fiscal year legitimately supersedes the prior one, a writer holding a stale lender version must re-read the lender before filing. The second guard covers a reviewer's accept-or-reject decision on a filing: because accept-with-supersede mutates the lender's filing set, a stale decision must not silently supersede a filing the reviewer never saw. No other endpoint takes a version field.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents. Every division, rate application, or percentage computation that produces a fractional cent is rounded half-up to whole cents, and every basis-point result is rounded half-up to an integer. Where a computation has several stages, the stage-by-stage rounding order stated in the relevant workflow is part of the contract — in particular, claim expense lines are each rounded to whole cents before being summed, and the loan-modification restructure follows its pinned eight-step order. Derived balances maintained by the system (a lender's `endorsed_volume_cents`, a case's `mip_retained_cents`, an agreement's `recovered_total_cents`) are exact integer reconciliations with no rounding at all.

### 2.7. Validation Priority Order

When a request violates more than one rule, the platform reports the violation whose category ranks earliest in the following priority order, so a caller always sees the most fundamental problem first:

1. Authentication: both headers present and the role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted for the endpoint — and, on the lender status-change endpoint, for the requested action, per the role-to-action matrix (`ERR_UNAUTHORIZED_ROLE`).
3. Ownership: for entity-backed callers, the caller owns the lender of the target resource (`ERR_FORBIDDEN_OWNERSHIP`). Where the lender must be dereferenced through a path-scoped resource, that resource's existence is established first, so an unknown path id draws `ERR_NOT_FOUND` before any ownership comparison can run.
4. Existence: every id in the path and body references an existing resource (`ERR_NOT_FOUND`).
5. Payload shape: required fields present, enums valid, dates well-formed, amounts within their floors — positive (minimum 1) for loan-case amounts and term, appraisal values, escrow and disbursement amounts, the coverage cap, recovery amounts, and a claim's unpaid principal balance, and non-negative (zero allowed) for filing asset and liability figures, a MIP event's `current_balance_cents`, claim expense-line amounts and percentages, `months_late`, and `escrow_advances_cents` — `start_date` not after `end_date`, `deficiency_codes` non-empty on a flag-deficient decision (`ERR_VALIDATION`).
6. Optimistic concurrency: `expected_lender_version` matches the lender's current `version` (`ERR_STALE_VERSION`).
7. State legality: the target resource is in a state that permits the transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`). Within this category, a request against a resource sitting in a terminal state for its lifecycle — `TERMINATED` lender; `ACCEPTED`, `REJECTED`, or `SUPERSEDED` filing; `VOIDED` or `CLAIM_PAID` case; `REJECTED`, `EXPIRED`, or `TRANSFERRED` appraisal; `DISBURSED` or `FORFEITED` escrow; `CLOSED` review; `REMEDIATED` or `DISMISSED` defect; an already-evaluated action; `PAID` or `DENIED` claim; `SATISFIED` agreement — is rejected with `ERR_ALREADY_TERMINAL`, while a non-terminal state that merely does not permit the transition draws `ERR_INVALID_STATE` (or `ERR_CASE_BLOCKED` for a case blocked by a lender suspension).
8. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, `ERR_REVIEWER_CONFLICT`).
9. Linked-entity state gates (`ERR_LENDER_NOT_APPROVED`, `ERR_APPRAISAL_NOT_ACCEPTED`, `ERR_REVIEW_ALREADY_OPEN`, `ERR_CASE_ALREADY_HAS_APPRAISAL`, `ERR_INDEMNIFICATION_BLOCKS_PAYMENT`, `ERR_DEFECTS_OPEN`, `ERR_LENDER_HAS_ACTIVE_CASES`).
10. Temporal windows (`ERR_APPRAISAL_EXPIRED`, `ERR_TRANSFER_WINDOW_CLOSED`, `ERR_FILING_STALE`, `ERR_REVIEW_WINDOW_PASSED`, `ERR_CLAIM_DEADLINE_PASSED`, `ERR_ESCROW_EXPIRED`).
11. Domain constraints (`ERR_ESCROW_WINDOW_OVERLAP`, `ERR_ESCROW_FROZEN`, `ERR_WATERFALL_ORDER_VIOLATION`, `ERR_WATERFALL_NOT_EXHAUSTED`, `ERR_MODIFICATION_INSUFFICIENT_REDUCTION`, `ERR_VINTAGE_LIFE_OF_LOAN`).
12. Financial sufficiency (`ERR_NET_WORTH_DEFICIENT`, `ERR_LIQUIDITY_DEFICIENT`, `ERR_QC_PLAN_MISSING`, `ERR_MIP_CANCELLATION_INELIGIBLE`).
## 3. Business Logic & Workflows

### 3.1. Lender Admission: Applications, Audited Filings, and the Net Worth Floor

A `PlatformAdmin` onboards a lender application by supplying the applicant's `legal_name`, its `institution_type` — one of `MORTGAGEE_SUPERVISED`, `MORTGAGEE_NONSUPERVISED`, or `MORTGAGEE_INVESTING` — its two-letter `home_state`, and the `qc_plan_on_file` attestation flag recording whether a quality control plan was presented at application. The new `Lender` lands in `DESK_REVIEW` with `endorsed_volume_cents` at 0 and its `required_net_worth_cents` immediately computed per the variant rule below. A single status-change operation drives the entire lender lifecycle: the caller supplies an `action` naming the transition and may attach an optional `note`. The action vocabulary is `ADVANCE_TO_FIELD_REVIEW`, `RETURN`, `RESUBMIT`, `APPROVE`, `SUSPEND`, `REINSTATE`, and `TERMINATE`, and the role-to-action matrix gates each: `RESUBMIT` belongs to the owning `LenderOfficer`, `ADVANCE_TO_FIELD_REVIEW` and `RETURN` belong to an `FhaReviewer`, and `APPROVE`, `SUSPEND`, `REINSTATE`, and `TERMINATE` belong to an `FhaApprover`; a caller attempting an action outside their role is rejected with `ERR_UNAUTHORIZED_ROLE`. The application moves through a review cycle: an `FhaReviewer` may advance an application sitting in `DESK_REVIEW` to `FIELD_REVIEW`, which records the reviewer's identifier in `advanced_by_user_id`, or return an application sitting in either `DESK_REVIEW` or `FIELD_REVIEW` to `RETURNED`. Requesting an advance against an application that is no longer in `DESK_REVIEW` is rejected with `ERR_INVALID_STATE`. A returned application may be resubmitted by the owning `LenderOfficer`, which moves it from `RETURNED` back to `DESK_REVIEW`; the resubmission cycle `RETURNED` → `DESK_REVIEW` → `FIELD_REVIEW` may repeat any number of times. Resubmission by anyone other than the lender that owns the application is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Every status change increments the lender's `version` by 1.

Approval is the gateway to everything else, and it is deliberately hard. An `FhaApprover` approves an application in `FIELD_REVIEW` only when five conditions hold. First, the approver's identity must differ from the `advanced_by_user_id` recorded when the application was advanced — the same person who moved the file forward may not approve it — or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, the lender's `last_accepted_filing_id` must reference an accepted audited filing whose `fiscal_year_end` falls on or after the date exactly 15 months before the current logical date; otherwise the approval fails with `ERR_FILING_STALE`. Third, that filing's `adjusted_net_worth_cents` must be at least the lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`). Fourth, the filing's `liquid_assets_cents` multiplied by five must be at least `required_net_worth_cents` — a twenty-percent liquidity test (`ERR_LIQUIDITY_DEFICIENT`). Fifth, `qc_plan_on_file` must be true (`ERR_QC_PLAN_MISSING`). On approval the approver's identifier is recorded in `approved_by_user_id`, the net worth requirement and variant are recomputed, and the lender's `version` increments by 1.

Which net worth floor applies depends on the lender's `net_worth_variant`. A lender whose `institution_type` is `MORTGAGEE_NONSUPERVISED` and whose `endorsed_volume_cents` is below 5,000,000,000 cents is a `SMALL_LENDER`, and its `required_net_worth_cents` is a flat 50,000,000 cents regardless of volume. Every other lender is `STANDARD`, and its requirement is the greater of 100,000,000 cents and one percent of its `endorsed_volume_cents` rounded half-up to whole cents — so two non-supervised lenders with identical financials can face different floors once one crosses the volume cap. The requirement and variant are recomputed whenever an audited filing is accepted, whenever a loan case is endorsed or its endorsement is voided, and at approval time itself.

Audited financials arrive as `FinancialFiling` records submitted by the owning `LenderOfficer`, carrying the `fiscal_year_end` date, audited `total_assets_cents`, `total_liabilities_cents`, and `liquid_assets_cents`. The system derives `adjusted_net_worth_cents` as total assets minus total liabilities. A new filing lands in `SUBMITTED`. A filing may be submitted whatever the lender's current status, and submission itself increments the lender's `version` by 1 even though it changes no lender field. An `FhaReviewer` then decides it, supplying a `decision` of `ACCEPT` or `REJECT` along with an optional `note`. Accepting a filing records the reviewer in `decided_by_user_id`, supersedes any previously accepted filing of the same lender with the same `fiscal_year_end` (that older filing moves from `ACCEPTED` to `SUPERSEDED`, an accept-with-supersede rule driven by the system), updates the lender's `last_accepted_filing_id`, recomputes the lender's net worth requirement and variant, and increments the lender's `version` by 1; rejecting a filing records the reviewer and likewise increments the lender's `version` by 1. Both submission and decision are optimistic-concurrency guarded per §2.5: each must carry `expected_lender_version` matching the lender's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Because accepting a filing mutates the lender's filing set and increments its version, a reviewer who read the lender before a colleague's filing was accepted holds a stale version and must re-read before deciding. `ACCEPTED`, `REJECTED`, and `SUPERSEDED` are all terminal for a filing.

### 3.2. Loan Origination, Appraisal, and Endorsement Review

With the lender `APPROVED`, a `LenderOfficer` opens a mortgage insurance case by supplying the `lender_id`, a `borrower_reference`, the `base_loan_amount_cents` before any upfront premium financing, the `appraised_value_cents` used for the loan-to-value computation, the `term_months`, the `note_rate_bps`, and the `current_monthly_payment_cents` at origination. Opening a case against a lender that is not `APPROVED` is rejected with `ERR_LENDER_NOT_APPROVED`. When the new case refinances a prior one, the officer supplies `refinance_of_case_id`, which must reference an `ENDORSED` case of the same lender — an unknown id is rejected with `ERR_NOT_FOUND`, and an existing case that belongs to another lender or sits in any other status is rejected with `ERR_VALIDATION`; otherwise it is omitted. The new case starts in `CASE_NUMBER_ASSIGNED` with `endorsement_integrity` set to `SOUND`. Cases can be listed filtered by `lender_id` or by `refinance_of_case_id`.

Submitting the underwriting package moves a case from `CASE_NUMBER_ASSIGNED` to `UNDERWRITE_SUBMITTED`, and the same submission also cures a deficiency, moving a case from `DEFICIENT` back to `UNDERWRITE_SUBMITTED` — the deficiency cure cycle may repeat. Both require the lender to be `APPROVED` (`ERR_LENDER_NOT_APPROVED`).

The endorsement review itself belongs to an `FhaReviewer`, whose request carries a `decision` of `ENDORSE` or `FLAG_DEFICIENT`; both decisions require the case to sit in `UNDERWRITE_SUBMITTED`, and any other non-terminal state is rejected with `ERR_INVALID_STATE`. Endorsing a case requires the lender to be `APPROVED` and requires an appraisal attached to the case in `ACCEPTED` status; without one the decision is rejected with `ERR_APPRAISAL_NOT_ACCEPTED`. When several attached appraisals are `ACCEPTED`, the most recently delivered one governs the endorsement. The appraisal must also be inside its validity window: endorsement is rejected with `ERR_APPRAISAL_EXPIRED` when the current logical date has reached the appraisal's `expiry_date`, because the window is the half-open interval from `effective_date` up to but not including `expiry_date`. A case that has been driven into `BLOCKED` by a lender suspension cannot be endorsed at all — the review is rejected with `ERR_CASE_BLOCKED`. On a successful endorsement the system stamps `endorsement_date` from the logical clock, records the reviewer in `endorsement_reviewer_id`, computes `ltv_bps` as the base loan amount divided by the appraised value and multiplied by ten thousand, rounded half-up to an integer, derives `mip_vintage` as `PRE_CUTOFF` when the endorsement date is before `2024-01-01T00:00:00Z` and `POST_CUTOFF` otherwise, bills the upfront premium described in §3.3, adds the `base_loan_amount_cents` to the lender's `endorsed_volume_cents`, and recomputes the lender's net worth requirement. Alternatively, the reviewer flags the case deficient: the request must carry a non-empty `deficiency_codes` list (an empty list is rejected with `ERR_VALIDATION`), the codes are recorded on the case, and the case moves to `DEFICIENT`.

An `FhaApprover` may later void an endorsement, supplying a `reason`. Voiding moves the case from `ENDORSED` to `VOIDED`, subtracts the `base_loan_amount_cents` from the lender's `endorsed_volume_cents`, recomputes the net worth requirement, and cancels every premium ledger entry of the case of type `ANNUAL` still in `BILLED` status, after which `mip_retained_cents` is recomputed. The compensating invariant is exact for volume and annual premiums: endorsing and then voiding returns the lender's endorsed volume to its pre-endorsement total, and any billed annual premiums are cancelled in full; the upfront premium row is never cancelled, so the case's `mip_retained_cents` settles at the billed upfront amount rather than returning to zero. A lender's `endorsed_volume_cents` is defined as the sum of `base_loan_amount_cents` over its cases in `ENDORSED`, `IN_DEFAULT`, or `CLAIM_FILED` status.

Appraisals are delivered by a `LenderOfficer` against a specific case, carrying the appraiser's `appraised_value_cents`, the `effective_date`, and optionally a list of `mps_deficiency_codes` documenting minimum property standards deficiencies — the list defaults to empty for a compliant property. Delivery is permitted against a case in any status; no case-state gate applies. The system computes `expiry_date` as exactly 120 days after `effective_date`, and the appraisal lands in `DELIVERED`. An `FhaReviewer` reviews the property standards findings and accepts or rejects the appraisal — again via a `decision` of `ACCEPT` or `REJECT` with an optional `note` — moving it to `ACCEPTED` or `REJECTED`. An accepted appraisal ages out through the clock sweep described in §2.4: once the logical date reaches `expiry_date` the appraisal becomes `EXPIRED` and can no longer support an endorsement.

A `LenderOfficer` may also transfer an accepted appraisal to another case by naming `to_loan_case_id`, subject to four checks. The transfer must occur strictly before `expiry_date` — at or after expiry it is rejected with `ERR_TRANSFER_WINDOW_CLOSED`. The target case must belong to the same lender (`ERR_FORBIDDEN_OWNERSHIP`). The target case must be in `CASE_NUMBER_ASSIGNED` (`ERR_INVALID_STATE`). And the target case must not already hold an appraisal in `DELIVERED` or `ACCEPTED` status (`ERR_CASE_ALREADY_HAS_APPRAISAL`). A successful transfer records the original case in `transferred_from_case_id`, moves the `loan_case_id` attachment to the target, and marks the appraisal `TRANSFERRED`.

### 3.3. Mortgage Insurance Premiums: Upfront, Annual, and Vintage Cancellation

Premiums are tracked as `MipLedgerEntry` rows on the case. Each row has an `entry_type` of `UPFRONT`, `ANNUAL`, or `REFUND`; a `period_index` that is 0 for upfront rows and a 1-based annual period number for annual and refund rows; a signed `amount_cents` (positive for billed premiums, negative for refunds); a `credit_cents` field that defaults to 0; the `rate_bps` applied; and a `status` that starts at `BILLED` and can reach `CANCELLED`. The case's `mip_retained_cents` is at all times the sum of `amount_cents` over the case's ledger rows whose status is not `CANCELLED`; refund rows, carrying negative amounts, reduce the retained total through this same summation.

Endorsement bills the upfront premium. The gross upfront amount is the `base_loan_amount_cents` multiplied by 175 basis points — that is, by 175 and divided by ten thousand — rounded half-up to whole cents. When the case refinances a prior case, a refund credit applies: let the number of complete calendar months between the prior case's endorsement date (date part) and this endorsement be the elapsed months. If that count is at least 1 and at most 36, the refund percentage is the greater of 1,000 basis points and 8,000 basis points reduced by 200 basis points for each month beyond the first; the credit is the prior case's gross upfront premium — the `amount_cents` plus the `credit_cents` of the prior case's `UPFRONT` row, that is, the gross before any credit was taken — multiplied by that percentage and divided by ten thousand, rounded half-up to whole cents. Outside the 36-month window the credit is zero. The new case's `UPFRONT` row then carries an `amount_cents` equal to its gross premium minus the credit, with the credit recorded in `credit_cents` and the rate of 175 in `rate_bps`.

Annual premiums are serviced through MIP events raised by a `ServicerOfficer`, which supply an `event_type` and the `current_balance_cents`. MIP events are accepted only while the case is `ENDORSED`, `IN_DEFAULT`, or `CLAIM_FILED` — against any other non-terminal state the request is rejected with `ERR_INVALID_STATE`, as is any further event once the case's `mip_cancelled` flag is set. An `ANNUAL_BILL` event bills the next annual premium on the current balance; the billed row's `period_index` is one greater than the highest annual period index already on the case (1 for the first bill), and billing appends the ledger row and refreshes `mip_retained_cents` without incrementing the case's `version`. MIP event responses return HTTP 200 with the appended ledger row as `data`. For a `PRE_CUTOFF` case the annual amount is the current balance multiplied by 55 basis points and divided by ten thousand, rounded half-up. For a `POST_CUTOFF` case the rate depends on the case's original `ltv_bps`: 50 basis points when the LTV is at most 9,000 basis points, 55 basis points when it is above 9,000 and at most 9,500, and 80 basis points above 9,500; the billed amount is again the current balance times the rate over ten thousand, rounded half-up.

A `CANCEL` event evaluates vintage-specific eligibility before doing anything else. For a `PRE_CUTOFF` case, cancellation is permitted only when the `current_balance_cents` is at most 78 percent of the original `appraised_value_cents` — computed as the appraised value multiplied by 7,800 and divided by ten thousand, rounded half-up — and the endorsement is at least 60 complete calendar months old; otherwise the request is rejected with `ERR_MIP_CANCELLATION_INELIGIBLE`. For a `POST_CUTOFF` case whose original LTV exceeded 9,000 basis points, the premium runs for the life of the loan and cancellation is always rejected with `ERR_VINTAGE_LIFE_OF_LOAN`; otherwise cancellation requires an endorsement age of at least 132 complete calendar months, failing which the request is rejected with `ERR_MIP_CANCELLATION_INELIGIBLE`. Endorsement age is measured in complete calendar months between `endorsement_date` and the current logical date, counted on the full timestamps (an anniversary reached only later in the day does not yet count).

Once cancellation passes, the system posts a pro-rated refund. The current annual period index is the endorsement age in months divided by 12, rounded down, plus 1; the months already consumed in that period are the age in months minus 12 times one less than the period index; and the unused months are 12 minus the consumed count. The refund is the `amount_cents` of the case's `ANNUAL` row for that period in `BILLED` status, multiplied by the unused months and divided by 12, rounded half-up to whole cents; if no such `BILLED` annual row exists for that period, the refund is zero. A `REFUND` row carrying the negated refund amount (with `rate_bps` copied from that annual row, or 0 when there is none) is created for that period, and the case's `mip_cancelled` flag is set to true, reducing `mip_retained_cents` per the summation invariant above.

### 3.4. Repair Escrows: Windows, Disbursement, Freezes, and Forfeiture

A `LenderOfficer` opens a repair escrow on a case by supplying the `amount_cents`, a `start_date`, and an `end_date`. The escrow window is a closed interval from `start_date` through `end_date` inclusive, and the platform rejects any new escrow whose closed window intersects another `OPEN` or `FROZEN` escrow of the same case — intersection includes merely touching endpoints, so a new escrow whose `start_date` equals an existing escrow's `end_date` overlaps — with `ERR_ESCROW_WINDOW_OVERLAP`. A `start_date` after `end_date` is malformed and rejected with `ERR_VALIDATION`. The new escrow opens in `OPEN` status with `remaining_amount_cents` equal to the full `amount_cents` and `disbursed_amount_cents` at 0. Escrows may be opened against a case in any status, and — alone among creations — opening an escrow returns HTTP 200 rather than 201.

When repairs complete, a `ServicerOfficer` disburses the escrow by supplying the `disbursed_amount_cents`. Disbursement requires the current logical date to be on or before the escrow's `end_date` — afterwards the request is rejected with `ERR_ESCROW_EXPIRED` — and the amount must not exceed the escrow's `amount_cents` (`ERR_VALIDATION`). Attempting to disburse an escrow that has been frozen is rejected with `ERR_ESCROW_FROZEN`. On success the escrow moves to `DISBURSED`, the released amount is recorded in `disbursed_amount_cents`, and `remaining_amount_cents` becomes the original amount minus the disbursed amount.

Escrows also move without direct action. The clock sweep moves an `OPEN` escrow to `EXPIRED` once the logical date passes its `end_date`. Two separate cascades can freeze an escrow — a lender suspension and an endorsement-integrity impairment — and each stamps the escrow's `freeze_origin` with `SUSPENSION` or `IMPAIRMENT` respectively so that the matching reversal later unfreezes exactly the escrows that cascade froze; on reversal the escrow returns from `FROZEN` to `OPEN` and `freeze_origin` is cleared. Finally, filing a claim without conveyance forfeits the case's escrows: every escrow of the case in `OPEN` or `EXPIRED` status moves to `FORFEITED`, and the sum of their `remaining_amount_cents` is recorded on the case as `forfeited_escrow_total_cents`, which later offsets the claim payment.
### 3.5. Post-Endorsement Reviews and the Defect Taxonomy

An `FhaReviewer` opens a post-endorsement review on an endorsed case — one in `ENDORSED`, `IN_DEFAULT`, or `CLAIM_FILED` status — by supplying the review's `scope_codes` as a list. Three gates apply: the reviewer must differ from the case's `endorsement_reviewer_id` — the person who endorsed the case may not review their own endorsement, and the attempt is rejected with `ERR_REVIEWER_CONFLICT`; the review must be opened on or before the instant exactly 24 months after the `endorsement_date`, or it is rejected with `ERR_REVIEW_WINDOW_PASSED`; and the case must not already have a review in `INITIATED`, `FINDINGS_RECORDED`, or `CLOSURE_PENDING`, or the attempt is rejected with `ERR_REVIEW_ALREADY_OPEN`. The new review lands in `INITIATED` with the reviewer recorded in `reviewer_user_id`.

Recording a defect in the review moves it from `INITIATED` to `FINDINGS_RECORDED`, and each additional finding keeps it there; defects may be recorded only while the review is in one of those two states. A defect is recorded against the review through its `review_id` and carries a `defect_code` — one of `INCOME_MISCALC`, `APPRAISAL_INFLATED`, `ASSET_VERIFICATION_MISSING`, `QC_PLAN_VIOLATION`, or `ELIGIBILITY_CRITERIA_UNMET` — and an optional free-text `detail`, with the recording reviewer stored in `created_by_user_id`. Every new defect is scored immediately. Each defect code carries a base weight: `INCOME_MISCALC` weighs 40, `APPRAISAL_INFLATED` weighs 35, `ASSET_VERIFICATION_MISSING` weighs 20, `QC_PLAN_VIOLATION` weighs 15, and `ELIGIBILITY_CRITERIA_UNMET` weighs 25. The pattern multiplier is one and a half when the same defect code already appears in at least two other reviews of the same lender — regardless of whether those reviews are still open or already closed — whose `created_at` falls within the trailing 12 months before the current logical instant — a review created exactly twelve months earlier counts — and one otherwise. The default multiplier is one and a quarter when the case is `IN_DEFAULT` at the moment the defect is created, and one otherwise. The `severity_score` is the base weight multiplied by both multipliers, rounded half-up to an integer, with the multipliers applied before rounding. The score determines the defect's `severity_tier`: a score of at least 50 lands the defect in `TIER_1`; a score of at least 25 but below 50 lands it in `TIER_2`; anything below 25 is `TIER_3`.

An `FhaApprover` disposes of each defect through a `decision` of `CONFIRM`, `DISMISS`, or `MARK_REMEDIATED`: confirming it moves it from `OPEN` to `CONFIRMED`, dismissing moves it from `OPEN` to `DISMISSED`, and marking remediation moves a `CONFIRMED` defect to `REMEDIATED`; in all three the approver's identifier is recorded in `confirmed_by_user_id`. Confirming a `TIER_1` defect fires cascade A in three hops: the defect's review moves from `FINDINGS_RECORDED` to `CLOSURE_PENDING`; the case's `endorsement_integrity` flips to `IMPAIRED`; and every `OPEN` repair escrow of the case is frozen with `freeze_origin` set to `IMPAIRMENT`.

Closing the review requires the review to be in `FINDINGS_RECORDED` or `CLOSURE_PENDING` — closing an `INITIATED` review is rejected with `ERR_INVALID_STATE` — and requires every defect of the review to have reached a terminal disposition — `CONFIRMED`, `REMEDIATED`, or `DISMISSED` — and is rejected with `ERR_DEFECTS_OPEN` while any defect remains `OPEN`. Closure stamps `closed_at` from the logical clock. If any `CONFIRMED` `TIER_1` defect remains unremediated at close, the system auto-creates an `IndemnificationAgreement` in `DRAFT` status whose `coverage_cap_cents` equals the sum of the `severity_score` values of those unremediated `CONFIRMED` `TIER_1` defects, and whose `created_by_user_id` is the literal value `system`. If no `CONFIRMED` `TIER_1` defect remains, the case's `endorsement_integrity` restores to `SOUND` and every escrow frozen with `freeze_origin` `IMPAIRMENT` returns to `OPEN`. `CLOSED` is terminal for a review; `REMEDIATED` and `DISMISSED` are terminal for a defect.

### 3.6. Lender Suspension, Reinstatement, and Termination

Suspending a lender is the second cascade in the platform. An `FhaApprover` moves a lender from `APPROVED` to `SUSPENDED`, and the suspension cascades in two hops: every loan case of the lender sitting in `UNDERWRITE_SUBMITTED` moves to `BLOCKED`, and — caused by the first hop — every `OPEN` repair escrow of each newly blocked case is frozen with `freeze_origin` set to `SUSPENSION`. Reinstating reverses the same cascade: the lender moves from `SUSPENDED` back to `APPROVED`, every `BLOCKED` case of the lender returns to `UNDERWRITE_SUBMITTED`, and every escrow frozen with `freeze_origin` `SUSPENSION` on those cases returns to `OPEN` with its `freeze_origin` cleared. Because both impairment and suspension freezes record their origin, a reinstatement never accidentally unfreezes an escrow frozen by an unremediated `TIER_1` defect, and a review close never unfreezes an escrow frozen by a suspension.

An `FhaApprover` terminates a lender from either `APPROVED` or `SUSPENDED`, but only when no loan case of the lender sits in a non-terminal state — `CASE_NUMBER_ASSIGNED`, `UNDERWRITE_SUBMITTED`, `DEFICIENT`, `BLOCKED`, `ENDORSED`, `IN_DEFAULT`, or `CLAIM_FILED`. A termination attempt with any such case outstanding is rejected with `ERR_LENDER_HAS_ACTIVE_CASES`. `TERMINATED` is the lender's terminal state.

### 3.7. Indemnification Agreements and Claim Denial

When a case carries an unremediated `CONFIRMED` `TIER_1` defect, an `FhaApprover` may draft an indemnification agreement by supplying the `coverage_cap_cents` — the maximum recovery — or the system drafts one automatically at review close as described in §3.5; drafting against a case with no unremediated `CONFIRMED` `TIER_1` defect is rejected with `ERR_INVALID_STATE`. A drafted agreement starts in `DRAFT` with `recovered_total_cents` at 0 and the drafter recorded in `created_by_user_id`.

Execution belongs to the `LenderOfficer` of the lender that owns the case; an officer of any other lender is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Execution moves the agreement from `DRAFT` to `EXECUTED` and fires the claim-denial cascade: every claim of the case still `UNDER_REVIEW` is denied with `denial_reason` set to `INDEMNIFIED_DEFECT` and `decided_by_user_id` set to `system`, and the case returns from `CLAIM_FILED` to `IN_DEFAULT`. Thereafter a claims examiner cannot pay any claim on that case while an `EXECUTED` or `SATISFIED` agreement covers it — the payment decision is rejected with `ERR_INDEMNIFICATION_BLOCKS_PAYMENT`.

Recoveries are recorded by a `ClaimsExaminer` against an executed agreement, each carrying a `recovery_amount_cents`. The amount is added to `recovered_total_cents`, and the moment the cumulative recovered total reaches or exceeds the `coverage_cap_cents` the agreement moves from `EXECUTED` to `SATISFIED`, its terminal state.

### 3.8. Default, the Loss Mitigation Waterfall, Claims, and Payment

A `ServicerOfficer` declares an endorsed case in default, moving it from `ENDORSED` to `IN_DEFAULT` and stamping `default_date` from the logical clock.

Before any insurance claim may be filed, the servicer must work a six-tier loss mitigation waterfall, one `LossMitigationAction` at a time; actions may be opened only while the case is `IN_DEFAULT`, and against any other non-terminal state the attempt is rejected with `ERR_INVALID_STATE`. The tiers in order are: `REPAYMENT_PLAN` (tier 1), `SPECIAL_FORBEARANCE` (tier 2), `LOAN_MODIFICATION` (tier 3), `PARTIAL_CLAIM` (tier 4), `PRE_FORECLOSURE_SALE` (tier 5), and `DEED_IN_LIEU` (tier 6); each created action has its `tier` derived from its `action_type` and lands in `PENDING`. Creation is strictly ordered: the only action type that may be created is the one whose tier is the lowest tier holding no existing action of the case, and any attempt to create an action out of that order — including any attempt once every tier already holds an action — is rejected with `ERR_WATERFALL_ORDER_VIOLATION`. While any action of the case is still `PENDING`, all further creation is likewise rejected with `ERR_WATERFALL_ORDER_VIOLATION`. An action evaluated `INFEASIBLE` or `FAILED` opens the next tier; an action evaluated `APPROVED` permanently blocks claims because the waterfall is then not exhausted.

Evaluating a pending action is also a `ServicerOfficer` duty and always stamps `evaluated_at` from the logical clock. A `FAIL` decision moves the action to `FAILED` and an `INFEASIBLE` decision to `INFEASIBLE`, with no further computation. An `APPROVE` decision on a `LOAN_MODIFICATION` runs the modification restructure in a pinned eight-step order, supplied with the number of `months_late` (a required non-negative integer) and any `escrow_advances_cents` (optional, defaulting to 0). First, the old payment is frozen at the case's `current_monthly_payment_cents`. Second, late fees are the old payment multiplied by 400 basis points — that is, multiplied by 400 and divided by ten thousand, rounded half-up to whole cents — and then multiplied by the months late. Third, arrears are the months late multiplied by the old payment, plus the late fees, plus the escrow advances. Fourth, the restructured unpaid principal `new_upb_cents` is the case's `base_loan_amount_cents` plus the arrears. Fifth, the modified rate is the case's `note_rate_bps` reduced by 200 basis points, floored at 300 basis points. Sixth, the restructured monthly payment `new_payment_cents` is the new balance multiplied by the modified rate and divided by 120,000, rounded half-up to whole cents. Seventh, the `reduction_bps` is the old payment minus the new payment, divided by the old payment and multiplied by ten thousand, rounded half-up to an integer. Eighth, the approval is allowed only when that reduction is at least 1,000 basis points — a ten percent payment reduction — and is otherwise rejected with `ERR_MODIFICATION_INSUFFICIENT_REDUCTION`. On an allowed approval the three computed values are stored on the action and it moves to `APPROVED`.

With the waterfall exhausted — every tier 1 through 6 holding an action in `INFEASIBLE` or `FAILED` status — the servicer files a claim, and filing before exhaustion is rejected with `ERR_WATERFALL_NOT_EXHAUSTED`. The claim supplies the `claim_type` (`CONVEYANCE` or `WITHOUT_CONVEYANCE`), the `unpaid_principal_balance_cents` at claim time, and an array of `expense_items`, each line carrying an `amount_cents` and an `allowable_pct_bps`. The claim must be filed on or before the 180th day after `default_date`, inclusive; afterwards the filing is rejected with `ERR_CLAIM_DEADLINE_PASSED`. Filing moves the case from `IN_DEFAULT` to `CLAIM_FILED`, and for a `WITHOUT_CONVEYANCE` claim it also triggers the escrow forfeiture described in §3.4.

The claim payment is computed at filing with a pinned rounding order: each expense line is rounded to whole cents first, and only then are the lines summed. The `principal_component_cents` for a `CONVEYANCE` claim is the unpaid principal balance multiplied by 8,500 basis points — that is, by 8,500 and divided by ten thousand, rounded half-up — an 85 percent coverage of principal. For a `WITHOUT_CONVEYANCE` claim, that same 85 percent figure is itself multiplied by 9,000 basis points and divided by ten thousand, rounded half-up — a 90 percent damage factor applied after coverage. The `expense_component_cents` is the sum over the expense items of each line's `amount_cents` multiplied by its `allowable_pct_bps` and divided by ten thousand, each line rounded half-up to whole cents before summation. The `forfeited_escrow_offset_cents` is zero for a conveyance claim and equals the case's `forfeited_escrow_total_cents` for a claim without conveyance. The `total_claim_cents` is the principal component plus the expense component minus the forfeited escrow offset.

A new claim lands in `UNDER_REVIEW`. A `ClaimsExaminer` decides it with a `decision` of `PAY` or `DENY`: paying moves the claim to `PAID` and the case from `CLAIM_FILED` to `CLAIM_PAID`, while denying records `denial_reason` as `EXAMINER_DENIAL`, moves the claim to `DENIED`, and returns the case from `CLAIM_FILED` to `IN_DEFAULT` — the denial loop may repeat, and the servicer may refile while the 180-day deadline from `default_date` still holds. Payment is blocked outright while an `EXECUTED` or `SATISFIED` indemnification agreement covers the case (`ERR_INDEMNIFICATION_BLOCKS_PAYMENT`), and executing such an agreement while a claim sits under review denies that claim with `denial_reason` `INDEMNIFIED_DEFECT` per §3.7. `PAID` and `DENIED` are terminal for a claim.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201 — with one exception: opening a repair escrow returns HTTP 200 — while operations that modify an existing resource, drive a state transition, or read data return HTTP 200. The complete request and response payloads for each operation are defined by the workflows in §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; fires appraisal and escrow expiry sweeps | PlatformAdmin |
| POST | /mi/lenders | Onboard a lender application (lands in DESK_REVIEW) | PlatformAdmin |
| GET | /mi/lenders/{lenderId} | Get a lender | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/lenders/{lenderId}/status-change | Drive the lender lifecycle: RESUBMIT, ADVANCE_TO_FIELD_REVIEW, RETURN, APPROVE, SUSPEND, REINSTATE, TERMINATE | LenderOfficer, FhaReviewer, FhaApprover |
| POST | /mi/lenders/{lenderId}/financial-filings | Submit an audited financial filing (OCC-guarded) | LenderOfficer |
| GET | /mi/lenders/{lenderId}/financial-filings | List a lender's filings | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/financial-filings/{filingId}/decide | Accept (with supersede) or reject a filing (OCC-guarded) | FhaReviewer |
| POST | /mi/loan-cases | Open a mortgage insurance case | LenderOfficer |
| GET | /mi/loan-cases | List loan cases; filterable by `lender_id` and `refinance_of_case_id` | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| GET | /mi/loan-cases/{loanCaseId} | Get a loan case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/loan-cases/{loanCaseId}/submit-underwriting | Submit (or resubmit after deficiency) the underwriting package | LenderOfficer |
| POST | /mi/loan-cases/{loanCaseId}/endorsement-review | Endorse the case or flag it deficient | FhaReviewer |
| POST | /mi/loan-cases/{loanCaseId}/void-endorsement | Void an endorsement; compensates volume and cancels billed annual MIP | FhaApprover |
| POST | /mi/loan-cases/{loanCaseId}/declare-default | Declare the case in default | ServicerOfficer |
| POST | /mi/loan-cases/{loanCaseId}/appraisals | Deliver an appraisal for the case | LenderOfficer |
| GET | /mi/loan-cases/{loanCaseId}/appraisals | List appraisals attached to the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/appraisals/{appraisalId}/decide | Accept or reject a delivered appraisal | FhaReviewer |
| POST | /mi/appraisals/{appraisalId}/transfer | Transfer an accepted appraisal to another case of the same lender | LenderOfficer |
| POST | /mi/loan-cases/{loanCaseId}/repair-escrows | Open a repair escrow with a non-overlapping closed window | LenderOfficer |
| GET | /mi/loan-cases/{loanCaseId}/repair-escrows | List repair escrows of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/repair-escrows/{escrowId}/disburse | Disburse escrowed funds on completed repairs | ServicerOfficer |
| GET | /mi/loan-cases/{loanCaseId}/mip-ledger-entries | List MIP ledger entries of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/loan-cases/{loanCaseId}/mip-events | Bill the annual premium or cancel MIP per vintage rules | ServicerOfficer |
| POST | /mi/loan-cases/{loanCaseId}/post-endorsement-reviews | Open a post-endorsement review (segregation, 24-month window, one open per case) | FhaReviewer |
| GET | /mi/loan-cases/{loanCaseId}/post-endorsement-reviews | List post-endorsement reviews of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/post-endorsement-reviews/{reviewId}/defects | Record a defect finding with weighted severity scoring | FhaReviewer |
| GET | /mi/post-endorsement-reviews/{reviewId}/defects | List defects recorded in the review | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/post-endorsement-reviews/{reviewId}/close | Close the review; unremediated TIER_1 defects auto-draft indemnification | FhaReviewer |
| POST | /mi/defects/{defectId}/confirm | Confirm, dismiss, or mark a defect remediated | FhaApprover |
| POST | /mi/loan-cases/{loanCaseId}/indemnification-agreements | Draft an indemnification agreement | FhaApprover |
| GET | /mi/loan-cases/{loanCaseId}/indemnification-agreements | List indemnification agreements of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/indemnification-agreements/{agreementId}/execute | Execute the agreement; cascade-denies under-review claims | LenderOfficer |
| POST | /mi/indemnification-agreements/{agreementId}/record-recovery | Record a recovery payment; satisfies at the coverage cap | ClaimsExaminer |
| POST | /mi/loan-cases/{loanCaseId}/loss-mitigation-actions | Open the next loss-mitigation option in waterfall order | ServicerOfficer |
| GET | /mi/loan-cases/{loanCaseId}/loss-mitigation-actions | List loss-mitigation actions of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/loss-mitigation-actions/{actionId}/evaluate | Evaluate a pending action (approve, fail, or mark infeasible) | ServicerOfficer |
| POST | /mi/loan-cases/{loanCaseId}/claims | File an insurance claim (conveyance or without conveyance) | ServicerOfficer |
| GET | /mi/loan-cases/{loanCaseId}/claims | List claims of the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |
| POST | /mi/claims/{claimId}/decide | Pay or deny a claim under review | ClaimsExaminer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_CASE_BLOCKED | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_REVIEWER_CONFLICT | 422 |
| ERR_LENDER_NOT_APPROVED | 409 |
| ERR_APPRAISAL_NOT_ACCEPTED | 409 |
| ERR_REVIEW_ALREADY_OPEN | 409 |
| ERR_CASE_ALREADY_HAS_APPRAISAL | 409 |
| ERR_INDEMNIFICATION_BLOCKS_PAYMENT | 409 |
| ERR_DEFECTS_OPEN | 409 |
| ERR_LENDER_HAS_ACTIVE_CASES | 409 |
| ERR_APPRAISAL_EXPIRED | 409 |
| ERR_TRANSFER_WINDOW_CLOSED | 409 |
| ERR_FILING_STALE | 422 |
| ERR_REVIEW_WINDOW_PASSED | 422 |
| ERR_CLAIM_DEADLINE_PASSED | 422 |
| ERR_ESCROW_EXPIRED | 409 |
| ERR_ESCROW_WINDOW_OVERLAP | 409 |
| ERR_ESCROW_FROZEN | 409 |
| ERR_WATERFALL_ORDER_VIOLATION | 409 |
| ERR_WATERFALL_NOT_EXHAUSTED | 409 |
| ERR_MODIFICATION_INSUFFICIENT_REDUCTION | 422 |
| ERR_VINTAGE_LIFE_OF_LOAN | 422 |
| ERR_MIP_CANCELLATION_INELIGIBLE | 422 |
| ERR_NET_WORTH_DEFICIENT | 422 |
| ERR_LIQUIDITY_DEFICIENT | 422 |
| ERR_QC_PLAN_MISSING | 422 |
