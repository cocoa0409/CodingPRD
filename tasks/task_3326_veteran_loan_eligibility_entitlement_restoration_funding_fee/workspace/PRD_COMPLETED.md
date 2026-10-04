# Veteran Loan Eligibility API — Product Requirements Document

## 1. Introduction

Military service earns a benefit that is unusually easy to mismanage: a government-backed home loan guaranty that depends on the character of a veteran's discharge, the length and recency of qualifying service, the history of entitlement already charged against earlier loans, and a statutory funding fee whose rate varies by service category, down payment tier, and first-versus-subsequent use. When any of these inputs are mishandled — a COE issued to an ineligible borrower, entitlement double-charged across loans, a funding fee assessed against a disabled veteran who is exempt — the program absorbs the loss and the veteran loses trust in it.

This document specifies the Veteran Loan Eligibility API, mounted under `/va-loans`, a program-operations backend that administers the full lifecycle of that benefit. It covers eligibility determination from service history with certificate of eligibility issuance, denial, and bounded reconsideration; entitlement accounting including remaining entitlement in both its basic and bonus variants and restoration on sale, refinance payoff, or a one-time retained-property restoration; funding fee assessment with disability exemption and retroactive refund; appraisal ordering through a regional assignment pool with minimum property requirement repairs; occupancy certification with a deployment exception; residual-income and debt-ratio underwriting that deliberately diverges from conventional guidelines; assumption of an existing loan by a qualified buyer with entitlement substitution; and refinance seasoning and net-tangible-benefit evaluation.

Two principles shape every workflow below. First, decisions are auditable: every mutating operation appends an audit event recording the acting role and user, and adjudication powers (COE issuance, repair waivers, fee refunds, restoration grants) are segregated from origination powers. Second, money and entitlement are accounted in integer cents with deterministic rounding, so that two clients reading the same account always reconstruct the same remaining entitlement.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles: `Veteran`, `LoanOfficer`, `Underwriter`, `Appraiser`, and `ProgramAdmin`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the target endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of the roles are entity-backed. When `X-User-Role` is `Veteran`, `X-User-ID` is the `id` of the acting `Veteran`; ownership checks on any resource that references a `Veteran` compare the resource's foreign-key field to `X-User-ID`, and a `Veteran` acting anywhere outside the subtree of the veteran whose `id` equals `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `Appraiser`, `X-User-ID` is the `id` of the acting `Appraiser`; report submission and repair verification compare the appraisal's assigned `appraiser_id` to `X-User-ID`.

The remaining three roles are opaque operator identities. When `X-User-Role` is `LoanOfficer`, `Underwriter`, or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `originator_user_id` on a `Loan` at creation, or `decided_by_user_id` on an `UnderwritingDecision`) but does not compare it to any entity's `id`.

Segregation of duties binds these identities together. An underwriting decision is rejected with `ERR_UNDERWRITER_IS_ORIGINATOR` (HTTP 403) whenever the deciding underwriter's `X-User-ID` equals the loan's `originator_user_id` — the officer who originated a loan may never decide it. The same separation-of-powers spirit bars a `LoanOfficer` from waiving repairs, submitting appraisal reports, or adjudicating COEs; those belong to `Appraiser` and `ProgramAdmin`.

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

List endpoints accept two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A non-integer `limit` or `offset` falls back to its default; out-of-range values are clamped — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. The singleton list endpoints — a veteran's entitlement account, a loan's funding fee assessments, and a loan's occupancy certificates (§2.4) — return their zero-or-one-element array without pagination fields in `meta` and ignore `limit` and `offset`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at its initial value on creation and increments by one on every mutation of that resource — including mutations caused by cascades originating elsewhere.

One resource departs from this convention. `AuditEvent` is an append-only record carrying only `id` and `created_at`; both `updated_at` and `version` are absent on audit events, because an audit record, once written, is never mutated.

Several resources are singletons created automatically alongside their parent and are therefore read back as arrays of length zero or one: a veteran's entitlement account, a loan's funding fee assessment, and a loan's occupancy certificate. Their list endpoints always return an array envelope even though at most one element can exist.

### 2.5. The Logical Clock

Time inside this system is logical, not wall-clock. A single logical clock governs issuance timestamps, seasoning measurement, deployment windows, and occupancy deadlines. At startup the clock reads 2026-09-01T00:00:00Z, and it must never silently fall back to wall-clock time. An admin-only test-driving capability — restricted to `ProgramAdmin` — advances the logical clock to a supplied `to_iso8601` instant; it echoes the supplied value back as `{"current_utc": "<to_iso8601>"}` and sets the clock regardless of direction — moving the clock backward is permitted. Computations described in §3 as happening "at evaluate time" or "at grant time" read this clock. Envelope `api_request_timestamp` values and the `created_at`/`updated_at` system fields of §2.4 are wall-clock server timestamps; only the domain timestamps named above — `issued_at`, seasoning measurement, deployment window containment, and occupancy deadlines — read the logical clock.

### 2.6. Entitlement Accounting: The Two Remaining-Entitlement Variants

Every veteran owns exactly one `EntitlementAccount`, created automatically when the veteran is registered. The account holds two system-fixed constants: `basic_entitlement_cents` of 3,600,000 cents (the fixed basic entitlement of $36,000.00) and `county_limit_cents` of 76,655,000 cents (the conforming county loan limit of $766,550.00 used to derive bonus entitlement). Two running totals accumulate over the account's life: `total_charged_cents`, the sum of entitlement charges posted at loan closings, which is never decremented by repayment or passage of time; and `total_restored_cents`, the sum of entitlement returned by granted restoration requests or by an entitlement-substituting assumption.

From these, the account exposes two remaining-entitlement readings. Define the entitlement in use as `total_charged_cents` minus `total_restored_cents`. The base-only variant, `remaining_base_cents`, is the greater of zero and the basic entitlement minus the entitlement in use — this reading caps guaranty capacity at $36,000.00, so identical inputs yield a remaining base of zero once a $300,000 loan has charged $75,000, while the bonus reading still shows $116,637.50. The with-bonus variant, `remaining_with_bonus_cents`, is the greater of zero and one quarter of the county limit minus the entitlement in use — guaranty capacity under this variant is 25% of the county limit, $191,637.50, so the same charge history leaves a strictly larger remaining entitlement. Both readings are recomputed on every loan close, every restoration grant, and every entitlement-substituting assumption approval. The with-bonus variant — never the base-only variant — is the one consulted for close-time feasibility in §3.4.

### 2.7. Monetary Precision and Rounding Discipline

All monetary amounts in this API are integer cents. Where a calculation must round, the rounding method is round half up unless the specific rule says otherwise, and the precision is stated with each rule in §3: debt-to-income percentages round half up to two decimal places, down-payment percentages round half up to four decimal places, amortized payments round half up to whole cents, and the funding fee is truncated down to whole dollars (never rounded). Interest rates are carried as percentages with three decimal places, so a note rate of six and a half percent is written 6.500. No computed monetary value may be approximated: a reader implementing the formulas in §3 with these rounding rules must reproduce the system's outputs exactly.

### 2.8. Nested Resource Retrieval

The API enforces strict left-to-right validation of hierarchical paths. When a path contains multiple resource identifiers — a veteran followed by a loan, a loan followed by an appraisal — the system resolves each identifier in order and rejects the request immediately with the not-found error corresponding to the first segment that does not resolve: `ERR_VETERAN_NOT_FOUND` for an unresolvable veteran id, `ERR_COE_NOT_FOUND` for a certificate of eligibility, `ERR_LOAN_NOT_FOUND` for a loan, `ERR_APPRAISAL_NOT_FOUND` for an appraisal, `ERR_REPAIR_NOT_FOUND` for a repair requirement, `ERR_OCCUPANCY_CERT_NOT_FOUND` for an occupancy certificate, `ERR_ASSUMPTION_NOT_FOUND` for an assumption request, `ERR_REFINANCE_NOT_FOUND` for a refinance request, `ERR_FEE_ASSESSMENT_NOT_FOUND` for a funding fee assessment, or `ERR_RESTORATION_NOT_FOUND` for a restoration request. A request naming a loan under a veteran who does not exist surfaces the veteran error before the loan is ever consulted.

### 2.9. Optimistic Concurrency Control

Exactly one endpoint in this API participates in optimistic concurrency control: creating a refinance request against a loan. That request must carry `expected_loan_version`, a non-optional field holding the `version` of the `Loan` as the client last observed it. If another writer has advanced the loan's version since that observation — for example by closing the loan, recording a payoff, or creating an earlier refinance request that the client never saw — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rationale is specific to this workflow: creating a new refinance request legitimately supersedes a prior `SUBMITTED` one, so a client holding a stale loan view would silently supersede a request it never observed. Endpoints other than refinance-request creation take no version field at all.

### 2.10. Audit Trail

Every mutating operation in the system appends an `AuditEvent`. Each audit event records the `entity_type` and `entity_id` of the mutated resource, the `action` (the endpoint action name, such as issue, deny, close, or refund), the `actor_role` taken from the caller's `X-User-Role` header, the `actor_user_id` taken from `X-User-ID`, and a short machine-generated `detail` summarizing the mutation. Audit events are readable only by `ProgramAdmin`, and the audit list may be filtered by `entity_type`, `entity_id`, or `action`.

### 2.11. Validation Ordering

When several checks could reject the same request, the system evaluates them in a fixed order so that the error a caller receives is deterministic. Authentication and role checks come first (`ERR_UNAUTHENTICATED`, then `ERR_FORBIDDEN_ROLE`, including the veteran-subtree restriction and the segregation-of-duties check on underwriting decisions). Path-existence checks follow, resolving identifiers left to right. Request-shape validation is next — a missing required field, a mistyped value, or an `ssn_last4` that is not exactly four digits yields `ERR_VALIDATION`, while an enum field carrying a value outside its declared membership yields `ERR_INVALID_ENUM`. A single field that is both missing and required reports `ERR_VALIDATION`, never `ERR_INVALID_ENUM`; enum membership is checked only for present, correctly typed values, and where a payload carries several malformed fields the error reflects the first field in the endpoint's declared payload order. Generic state checks come after shape validation: an action attempted on a resource in a state that does not permit it is rejected with `ERR_INVALID_STATE`. Only then do the domain-specific business rules run, in the orders given in §3 — for COE issuance, the discharge gate before the service-length gate before the service-period ownership check; for refinance evaluation, the seasoning gate before the net-tangible-benefit determination.

## 3. Business Logic & Workflows

### 3.1. Registering Veterans and Proving Service

A `LoanOfficer` or `ProgramAdmin` registers a veteran by providing the `full_name`, the `ssn_last4` (exactly the last four digits of the Social Security number), the `service_category` — one of `REGULAR_MILITARY` or `RESERVES_NATIONAL_GUARD`, which drives funding-fee table selection — the overall `character_of_discharge` (one of `HONORABLE`, `GENERAL`, `OTHER_THAN_HONORABLE`, `BAD_CONDUCT`, or `DISHONORABLE`), and the flag `receives_disability_compensation`, which when true exempts the veteran from the funding fee. An optional `is_surviving_spouse` flag, defaulting to false, marks an eligible surviving spouse applying in place of the veteran; it confers funding-fee exemption and a waiver of the §3.2 service-length gate, but the discharge gate is not waived — the recorded `character_of_discharge` must still be `HONORABLE` or `GENERAL` for issuance to succeed. Registration cascade-creates the veteran's 1:1 `EntitlementAccount` with the fixed constants described in §2.6, and appends an audit event.

Service history is built up period by period. A `LoanOfficer` adds a `ServicePeriod` to a veteran by supplying the `branch` (one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, or `SPACE_FORCE`), the `start_date`, the `end_date`, and the `discharge_character` for that period, drawn from the same five-value discharge enumeration. Each period's dates form a closed interval — both the start and the end day count. A period's `qualifying_days` is computed at creation: when the period's `discharge_character` is `HONORABLE` or `GENERAL`, it is the number of days from `start_date` through `end_date` inclusive (the difference in days plus one); for any other discharge character it is zero. The veteran's `total_qualifying_service_days` is the sum of `qualifying_days` across all of the veteran's service periods, recomputed whenever a period is added.

Periods of the same veteran may not overlap. Because intervals are closed, a new period is rejected with `ERR_SERVICE_PERIOD_OVERLAP` (HTTP 409) whenever it fails to end strictly before an existing period's start or begin strictly after that period's end — which means a new period whose `start_date` equals an existing period's `end_date` collides, because both intervals claim that day.

### 3.2. The Certificate of Eligibility

With service history on file, a `LoanOfficer` requests a `CertificateOfEligibility` for the veteran, asserting an `entitlement_code` of `ERA_WWII`, `ERA_KOREA`, `ERA_VIETNAM`, `ERA_PEACETIME`, `ERA_GULF`, `RESTORED`, or `UNREIMBURSED_SURVIVING_SPOUSE`. The certificate begins life in `REQUESTED` status, with `reconsideration_count` at zero, `denial_reason` null, and `issued_at` null.

Adjudication belongs to `ProgramAdmin`. Issuing a certificate — from either `REQUESTED` or `RECONSIDERATION` — applies three gates, evaluated in this order. First, the discharge gate: the veteran's `character_of_discharge` must be `HONORABLE` or `GENERAL`, else the request is rejected with `ERR_DISCHARGE_INELIGIBLE` (HTTP 422). Second, the service-length gate: the veteran's `total_qualifying_service_days` must reach at least 90 days when the `service_category` is `REGULAR_MILITARY` and at least 180 days when it is `RESERVES_NATIONAL_GUARD`, else the request is rejected with `ERR_INSUFFICIENT_SERVICE` (HTTP 422); this gate is waived entirely when the veteran `is_surviving_spouse`. Third, the referential gate: the issuance payload may carry `service_period_ids`, and every id in it must exist and belong to this veteran, else the request is rejected with `ERR_SERVICE_PERIOD_MISMATCH` (HTTP 422). On success the certificate becomes `ISSUED` — its terminal state — `issued_at` is stamped from the logical clock, and the veteran's `has_issued_coe` flag is recomputed true; `has_issued_coe` is true exactly when the veteran holds a certificate in `ISSUED` status.

Denial moves a certificate from `REQUESTED` (or, on re-adjudication, from `RECONSIDERATION`) to `DENIED`, setting `denial_reason` from the failing gate — `DISCHARGE_INELIGIBLE` or `INSUFFICIENT_SERVICE` — and leaving it null whenever the certificate is not denied. The deny action re-evaluates only the discharge gate to choose the reason: when the veteran's `character_of_discharge` is not `HONORABLE` or `GENERAL` the reason is `DISCHARGE_INELIGIBLE`; in every other case it is `INSUFFICIENT_SERVICE`, regardless of the veteran's measured service. Denial is not contained to the certificate. Every loan of the same veteran whose `underwriting_status` is still `SUBMITTED` becomes `DENIED`. In turn, every appraisal of each such newly denied loan that is sitting in `REQUESTED` or `ASSIGNED` becomes `CANCELLED`. Each appraiser who held one of those cancelled `ASSIGNED` appraisals has their `open_assignment_count` decremented accordingly. And each freed appraiser slot triggers queue promotion: the earliest-created appraisal still waiting in `REQUESTED` in that appraiser's region becomes `ASSIGNED` to that appraiser, whose `open_assignment_count` increments. A loan officer may send a `DENIED` certificate back to `RECONSIDERATION`, which increments `reconsideration_count`; the cap is two reconsiderations, and a third attempt is rejected with `ERR_RECONSIDERATION_EXHAUSTED` (HTTP 409). Reconsidered certificates face the same issuance and denial gates as fresh ones, and a denial from `RECONSIDERATION` fires the same four-link cascade as a denial from `REQUESTED`, with `denial_reason` refreshed.

### 3.3. Loan Origination and the Funding Fee

A `LoanOfficer` creates a loan for a veteran with a payload naming the `coe_id`, the `purpose` (`PURCHASE`, `IRRRL`, or `CASH_OUT_REFINANCE`), the `property_region` (`NORTHEAST`, `MIDWEST`, `SOUTH`, or `WEST` — which drives both appraisal assignment and the residual-income table), the `purchase_price_cents` (for refinances, the payoff balance of the prior loan), the `down_payment_cents` (zero is allowed), the `interest_rate_percent`, the `rate_type` (`FIXED` or `ARM`), and optionally `term_months`, which defaults to 360. A `coe_id` that resolves to no certificate at all is rejected with `ERR_COE_NOT_FOUND` (HTTP 404). The cited certificate must belong to the path veteran — a mismatch is rejected with `ERR_SERVICE_PERIOD_MISMATCH` — and must be `ISSUED`, else creation fails with `ERR_COE_NOT_ISSUED` (HTTP 409). The down payment must be at least zero and no greater than the purchase price, else `ERR_INVALID_DOWN_PAYMENT` (HTTP 422).

Creation stamps the loan's `originator_user_id` from the caller's `X-User-ID` — the segregation-of-duties marker consulted at underwriting time — and computes several fields. The `loan_amount_cents` is the purchase price minus the down payment. The `down_payment_pct` is the down payment divided by the purchase price, expressed as a percentage rounded half up to four decimal places. The `loan_use` is `FIRST_USE` when the borrower's `charged_loan_count` is zero at creation and `SUBSEQUENT_USE` otherwise; `charged_loan_count` counts the veteran's loans that carry a positive `entitlement_charged_cents`, sit in `closing_status` `CLOSED` or `PAID_IN_FULL`, and have not had the charge fully restored. A new loan's two parallel state dimensions both start at their initial values: `underwriting_status` `SUBMITTED` and `closing_status` `NOT_CLOSED`, with `entitlement_charged_cents` zero, `closing_date` and `first_payment_due_date` null, and `payoff_type` null.

Loan creation also creates the loan's `FundingFeeAssessment` in `ASSESSED` status, and the fee math runs immediately. When the veteran `receives_disability_compensation` or `is_surviving_spouse` at assessment time, the assessment's `exempt` flag is true, the `fee_rate` is 0, and the `assessed_fee_cents` is 0 — exemption overrides every tier. Otherwise the rate depends on purpose and use. An `IRRRL` loan always pays a rate of 0.50. A `CASH_OUT_REFINANCE` pays 2.15 on first use and 3.30 on subsequent use, with the down payment not considered. A `PURCHASE` loan tiers by the down-payment percentage: on first use, 2.15 when the percentage is below 5.0000, 1.50 when it is at least 5.0000 but below 10.0000, and 1.25 at 10.0000 or more; on subsequent use the lowest tier jumps to 3.30 while the two upper tiers remain 1.50 and 1.25. The assessed fee is the loan amount multiplied by the rate, expressed as a percent, and then truncated down to the nearest whole dollar — fractional dollars are discarded, never rounded. Both `collected_cents` and `refunded_cents` start at zero.

### 3.4. Underwriting, Closing, and the Cost of Money

Underwriting uses the VA method, which differs deliberately from conventional guidelines. An `Underwriter` records a decision on a `SUBMITTED` loan by supplying the borrower's stable `gross_monthly_income_cents`, the proposed `new_housing_payment_cents`, an array `other_obligations_annual_cents` of annual recurring obligation amounts, the `family_size` (household size for the residual-income table; values above five add per-member rows), and the `region` for the table lookup. The deciding underwriter's identity must differ from the loan's `originator_user_id`; a violation is `ERR_UNDERWRITER_IS_ORIGINATOR`.

Monthly obligations are computed with a pinned rounding order: each annual obligation in `other_obligations_annual_cents` is first converted to a monthly figure by dividing by twelve and rounding that item half up to whole cents, and only then are the per-item monthly figures summed into `other_obligations_monthly_cents`. Summing the annual items first and dividing once yields a different total and is not the rule. The `dti_percent` is then the sum of `new_housing_payment_cents` and `other_obligations_monthly_cents`, divided by `gross_monthly_income_cents`, expressed as a percentage and rounded half up to two decimal places; a `gross_monthly_income_cents` of zero yields a `dti_percent` of 0.00 rather than an error. The conventional-style benchmark, `dti_only_pass`, is true when `dti_percent` is at most 41.00 — 41.00 exactly passes and 41.01 fails — with no residual-income gate; it is exposed for comparison but is not the decision gate, and identical income data can yield `dti_only_pass` true while the VA outcome is `DENIED`.

The VA gate runs on residual income. The `residual_income_cents` is the gross monthly income minus the new housing payment minus the monthly obligations. The `residual_required_cents` comes from a table keyed by region and family size. For a family of one through five, the monthly requirement in cents is: in the `NORTHEAST`, 45,000 / 75,500 / 90,900 / 102,500 / 106,200; in the `MIDWEST`, 44,100 / 73,800 / 88,900 / 100,300 / 103,900; in the `SOUTH`, the same five values as the Midwest; in the `WEST`, 49,100 / 82,300 / 99,000 / 111,700 / 115,800. Families larger than five use the five-member row plus 8,000 cents for each member beyond the fifth; a `family_size` below one falls back to the one-member row. The decision `outcome` is `APPROVED` when the residual income is at least the requirement — equality passes — and additionally either the `dti_percent` is at most 41.00 or the residual income reaches at least 120 percent of the requirement (the requirement multiplied by 1.2, rounded half up to whole cents); otherwise the outcome is `DENIED`. That compensating factor is the only way a loan whose debt ratio exceeds 41.00 survives. Recording the decision persists the `UnderwritingDecision` with all computed fields, moves the loan's `underwriting_status` to the outcome, and increments the loan's `version`. A `DENIED` outcome also cascades exactly like a COE denial at the loan level: the loan's appraisals in `REQUESTED` or `ASSIGNED` become `CANCELLED`, affected appraisers' open counts decrement, and queue promotion runs for each freed appraiser.

Closing is the fiscal heart of the system, performed by a `LoanOfficer` on a loan whose `underwriting_status` is `APPROVED` — closing from any other underwriting state is rejected with `ERR_LOAN_NOT_CLOSABLE` (HTTP 409). Three further preconditions guard the close. Some appraisal of the loan must have reached `VALUE_ISSUED` with an `appraised_value_cents` at least equal to the loan's `purchase_price_cents`; when no such appraisal exists, the close is rejected with `ERR_LOAN_NOT_CLOSABLE` (HTTP 409), the same error as the underwriting-state gate. No repair requirement flagged `required_for_clearance` on any of the loan's appraisals may still sit in `OPEN` or `COMPLETED` — such repairs must be `VERIFIED` or `WAIVED` before close, else `ERR_REPAIRS_OUTSTANDING` (HTTP 409). And entitlement feasibility must hold: when the `loan_amount_cents` is no more than four times the account's `remaining_with_bonus_cents`, no additional down payment is required; otherwise the shortfall — the loan amount minus four times the remaining with-bonus entitlement, multiplied by 0.25 and rounded half up to whole cents — must be covered by the loan's `down_payment_cents`, else the close is rejected with `ERR_INSUFFICIENT_ENTITLEMENT` (HTTP 422). Closing is only possible once: a loan whose `closing_status` is no longer `NOT_CLOSED` is rejected with `ERR_INVALID_STATE` (HTTP 409). The precondition checks run in a fixed order — underwriting-status gate, already-closed state gate, repair clearance, appraisal coverage, entitlement feasibility — so a loan failing several checks deterministically reports the earliest one.

A successful close fires a four-link cascade. The loan's `closing_status` becomes `CLOSED`, `closing_date` and `first_payment_due_date` are set from the close payload, and the loan's `version` increments. The entitlement charge posts: `entitlement_charged_cents` becomes the smaller of one quarter of the loan amount (rounded half up to whole cents) and the account's `remaining_with_bonus_cents`, and the funding fee assessment moves from `ASSESSED` to `COLLECTED` with `collected_cents` set to the `assessed_fee_cents`. The entitlement account then absorbs the charge — `total_charged_cents` increases by the charged amount and both remaining-entitlement variants recompute — and the veteran's `charged_loan_count` recomputes. Finally, an `OccupancyCertificate` springs into existence for the loan in `CERTIFIED` status.

Later, when the loan is paid off, a `LoanOfficer` records the payoff with a `payoff_type` of `SALE` or `REFINANCE_PAYOFF`; recording payoff on anything other than a `CLOSED` loan is `ERR_INVALID_STATE` (HTTP 409). The `closing_status` becomes the terminal `PAID_IN_FULL` and the loan's `version` increments. A loan is terminally resolved either as `DENIED` and never closed, or as `APPROVED` carried through to `PAID_IN_FULL`.

A collected fee can still be returned. When a retroactive disability determination arrives, a `ProgramAdmin` refunds the assessment by presenting `disability_evidence` set to true; presenting `disability_evidence` as false on a `COLLECTED` assessment is a validation failure (`ERR_VALIDATION`). Refunding requires the assessment to be in `COLLECTED` — any other status, including an already-refunded assessment, is rejected with `ERR_FEE_NOT_REFUNDABLE` (HTTP 409). The refund sets `refunded_cents` to the `collected_cents`, moves the assessment to its terminal `REFUNDED` status, and recomputes `exempt` true; the underlying veteran record is not modified.

### 3.5. Appraisal Assignment, Minimum Property Requirements, and Repairs

The appraisal pool is administered by `ProgramAdmin`, who registers each `Appraiser` with a `name`, a coverage `region` drawn from the same four-region enumeration as loan properties, an optional `max_open_assignments` capacity ceiling (defaulting to 3), and an optional `active` flag (defaulting true; inactive appraisers are excluded from assignment). An appraiser's `open_assignment_count` tracks how many of their appraisals currently sit in `ASSIGNED` or `REPAIRS_REQUIRED`.

A `LoanOfficer` orders an appraisal on a loan — in any underwriting or closing state — and the request begins in `REQUESTED` with `appraiser_id` null, `appraised_value_cents` unset, and `report_round` at zero. Assignment is a system-run selector policy, attempted immediately at creation and again whenever a slot frees. The candidate set is the active appraisers whose region equals the loan's `property_region` and whose `open_assignment_count` is below their `max_open_assignments`. Within the candidate set, the policy ranks by `open_assignment_count` ascending and breaks ties by appraiser `created_at` ascending; the chosen appraiser's `open_assignment_count` increments. When the candidate set is empty, the appraisal simply stays `REQUESTED` — queued, unassigned — and this is not an error.

Only the assigned appraiser may report. When the acting `Appraiser` submits the report, their identity must equal the appraisal's `appraiser_id` and the appraisal must be in `ASSIGNED` or `REPAIRS_REQUIRED`; a report from anyone else, or on an appraisal in any other state, is rejected with `ERR_APPRAISAL_NOT_ASSIGNED` (HTTP 409). The report's `outcome` selects the transition. An outcome of `VALUE_ISSUED` requires that no clearance-flagged repair of the appraisal remains `OPEN` or `COMPLETED` (the same `ERR_REPAIRS_OUTSTANDING` guard as at close); it moves the appraisal to its terminal `VALUE_ISSUED` state, sets `appraised_value_cents` from the payload, increments `report_round`, decrements the appraiser's `open_assignment_count`, and runs queue promotion for that appraiser. An outcome of `REPAIRS_REQUIRED` carries a non-empty `repairs` array — an absent or empty array is `ERR_VALIDATION` — and creates one `RepairRequirement` per entry, each in `OPEN` status with the entry's `description` (a required string) and its `required_for_clearance` flag (a boolean defaulting to true; a non-boolean value is `ERR_VALIDATION`); the appraisal moves to `REPAIRS_REQUIRED` and `report_round` increments. From `REPAIRS_REQUIRED`, a further `REPAIRS_REQUIRED` report is a self-loop re-inspection round — new repair requirements are appended in `OPEN`, prior repairs are unchanged, and `report_round` increments again — while a `VALUE_ISSUED` report completes the appraisal as above, decrementing the appraiser's open count and promoting the queue.

The `RepairRequirement` is created by the system, not directly: each one springs from a `REPAIRS_REQUIRED` report and is bound to its parent appraisal via the system-set `appraisal_id`. Repairs themselves have their own small lifecycle, with duties deliberately split. A `LoanOfficer` marks an `OPEN` repair `COMPLETED` once the builder-side work is done, but only while the parent appraisal remains in `REPAIRS_REQUIRED`; completing a repair on an appraisal in any other status, or on a repair not `OPEN`, is `ERR_INVALID_STATE` (HTTP 409). The assigned appraiser — and only that appraiser — then moves a `COMPLETED` repair to the terminal `VERIFIED` state; verification by anyone else, including an unassigned appraiser of the same region, is rejected with `ERR_APPRAISAL_NOT_ASSIGNED` (HTTP 409). Waiving is reserved for `ProgramAdmin`: an `OPEN` repair may be moved to the terminal `WAIVED` state, and a `LoanOfficer` may not waive. Both `VERIFIED` and `WAIVED` satisfy the clearance gate; `OPEN` and `COMPLETED` do not.

### 3.6. Occupancy and the Deployment Exception

Closing a loan certifies occupancy intent. The `OccupancyCertificate` created at close starts `CERTIFIED`, with its `certification_date` equal to the loan's `closing_date` and its `move_in_deadline` sixty days after the closing date, the deadline day itself included. Its `exception_type` begins as `NONE`.

Verification is a `LoanOfficer` action carrying a `move_in_date`. When the move-in date is on or before the deadline, the certificate becomes `SATISFIED`. When it falls after the deadline, the outcome depends on deployment. If a `DeploymentException` of the loan's veteran exists whose half-open window — running from `deployment_start` up to but not including `deployment_end` — contains the `move_in_deadline`, the certificate becomes `EXCEPTED` with `exception_type` set to `DEPLOYMENT`. With no covering deployment window, a late move-in leaves the certificate `VIOLATED`, and an audit event records the violation. All three of `SATISFIED`, `EXCEPTED`, and `VIOLATED` are terminal.

Deployment windows are recorded on the veteran — by the veteran themselves or by a `LoanOfficer` — with a `deployment_start`, a `deployment_end`, and an `orders_reference` pointing at the deployment orders document. Windows are half-open, so two windows of the same veteran overlap only when one starts strictly before the other ends; a window whose `deployment_end` equals another window's `deployment_start` does not overlap, and anything tighter is rejected with `ERR_DEPLOYMENT_WINDOW_OVERLAP` (HTTP 409).

### 3.7. Entitlement Restoration and Assumption

Paying off a loan does not by itself return entitlement; restoration is a separate adjudicated step. A `LoanOfficer` files an `EntitlementRestorationRequest` on the veteran, citing the `loan_id` whose charge is to be restored and a `restoration_type` of `SALE_PAYOFF` (the property was sold and the loan paid), `REFINANCE_PAYOFF` (the loan was paid off by a refinance), or `ONE_TIME_RESTORATION` (the loan is paid in full but the property was retained — usable once per veteran). The request starts `SUBMITTED`.

Granting belongs to `ProgramAdmin` and is gated on fact, not discretion. Granting a request that is no longer `SUBMITTED` — including an already-granted one — is `ERR_INVALID_STATE` (HTTP 409). The cited loan must be `PAID_IN_FULL`, else `ERR_LOAN_NOT_PAID_OFF` (HTTP 409). The restoration type must match the loan's recorded payoff: `SALE_PAYOFF` requires the loan's `payoff_type` to be `SALE`, and `REFINANCE_PAYOFF` requires `REFINANCE_PAYOFF`; a mismatched type is rejected with `ERR_INVALID_STATE` (HTTP 409), as is a `ONE_TIME_RESTORATION` when the veteran already holds a prior granted one-time restoration. On grant, the request's `restored_amount_cents` is set to the loan's `entitlement_charged_cents`, the status becomes the terminal `GRANTED`, the account's `total_restored_cents` increases by the restored amount, both remaining-entitlement variants recompute, and the veteran's `charged_loan_count` recomputes.

An existing closed loan may instead pass to a new borrower. A `LoanOfficer` submits an `AssumptionRequest` on the loan with the `buyer_name`, a `buyer_is_veteran` flag, a `buyer_veteran_id` (required when the buyer is a veteran and omitted otherwise — a veteran reference that does not resolve is `ERR_SERVICE_PERIOD_MISMATCH`), a `substitute_entitlement` flag, and a `release_of_liability` flag recording whether release of the original borrower's liability is requested. The request starts `SUBMITTED`. Approval is an `Underwriter` action on a request still in `SUBMITTED` — approving one already resolved is `ERR_INVALID_STATE` (HTTP 409) — with three preconditions: the loan must be `CLOSED` rather than `PAID_IN_FULL`; when `substitute_entitlement` is set the buyer must be a veteran with a resolvable `buyer_veteran_id`; and the buyer's entitlement account must hold `remaining_with_bonus_cents` at least equal to the loan's `entitlement_charged_cents`. Any failure is `ERR_ASSUMPTION_INELIGIBLE` (HTTP 422). Approval moves the request to its terminal `APPROVED` state; when entitlement is substituted, the buyer's account absorbs the charge (`total_charged_cents` increases by the loan's charged amount), the seller's account is relieved (`total_restored_cents` increases by the same amount), both accounts recompute their remaining variants, and both veterans' `charged_loan_count` recompute. The seller-side relief counts toward the fully-restored test of the §3.3 `charged_loan_count` definition, so a substitution-approved loan drops out of the seller's `charged_loan_count`.

### 3.8. Refinance Seasoning and Net Tangible Benefit

A refinance begins when a `LoanOfficer` files a `RefinanceRequest` against a loan, supplying the `refinance_type` (`IRRRL` for a streamline refinance or `CASH_OUT`), the proposed `new_rate_percent`, the `new_rate_type` (`FIXED` or `ARM`), and the `flat_costs_cents` of allowable closing costs other than the funding fee. The request must also carry `expected_loan_version` per §2.9; a value that no longer matches the loan's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A refinance request may be filed against a loan in any closing state, including one that has never closed. Filing a new request on a loan that already has a `SUBMITTED` request supersedes the older one — it becomes `SUPERSEDED` at the moment the new request is created — and creating the request increments the loan's `version` by one. The four evaluation-output fields — `seasoning_days`, `ntb_rate_satisfied`, `recoupment_months`, and `ntb_satisfied` — are null until evaluation.

Evaluation is an `Underwriter` action on a request still in `SUBMITTED` — evaluating a request in any other status is `ERR_INVALID_STATE` (HTTP 409) — that applies the seasoning gate first and the net-tangible-benefit determination second, in that order. A request whose loan has never closed carries no `closing_date` or `first_payment_due_date` and cannot be evaluated: the attempt is `ERR_INVALID_STATE` (HTTP 409). The `seasoning_days` measured at evaluation time is the smaller of two intervals: the days from the loan's `closing_date` to the current logical clock reading, and the days from the loan's `first_payment_due_date` to the clock. Seasoning of at least 210 days is required — 210 exactly passes — and a shortfall is rejected with `ERR_SEASONING_NOT_MET` (HTTP 422); the measured `seasoning_days` is stamped onto the request even when the seasoning gate fails, while the three NTB fields stay null. Only when seasoning passes does the NTB determination run, and its outcome is a state transition, never an error: a request whose NTB fails becomes `REJECTED` (persisted), while one whose NTB holds becomes `APPROVED`.

The NTB computation follows a pinned evaluation order, because the funding fee depends on the new base, the costs include the fee, and the new payment depends on the costs. The new base is the existing loan's `loan_amount_cents` — the payoff balance carried over. The fee is one half of one percent of that base for an `IRRRL`, truncated down to whole dollars; for a `CASH_OUT` the fee uses the funding-fee rate of §3.3 — 2.15 on the loan's recorded `FIRST_USE`, 3.30 on `SUBSEQUENT_USE`, and 0 when the veteran `receives_disability_compensation` or `is_surviving_spouse` — truncated down to whole dollars, with the down payment not considered. The allowable costs are the fee plus the request's `flat_costs_cents`, and the new principal is the new base plus the allowable costs. Both the old and new monthly payments are then amortized over a 360-month term at their respective note rates — the existing loan's `interest_rate_percent` for the old payment on the existing loan amount, and the `new_rate_percent` for the new payment on the new principal — using the standard level-payment annuity formula with the monthly rate taken as the annual percentage divided by twelve hundred, each payment rounded half up to whole cents; a zero percent note rate amortizes as simple principal divided by the term. The `monthly_savings_cents` is the old payment minus the new payment. For an `IRRRL`, the `recoupment_months` is the allowable costs divided by the monthly savings, rounded up to the next whole month; when the monthly savings is not positive, recoupment is treated as 999999 months.

Two legs then decide the NTB. The rate leg compares the note rates by rate-type pair: refinancing `FIXED` into `FIXED` requires a rate reduction of at least 0.50 percentage points; `FIXED` into `ARM` requires at least 2.00; `ARM` into `FIXED` is always satisfied regardless of the rate change; and `ARM` into `ARM` requires at least 0.50. The request's `ntb_rate_satisfied` records this leg. For an `IRRRL`, `ntb_satisfied` requires the rate leg and a recoupment of no more than 36 months; for a `CASH_OUT`, the rate leg alone decides. Evaluation stamps all four computed fields — `seasoning_days`, `ntb_rate_satisfied`, `recoupment_months`, and `ntb_satisfied` — onto the request.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Successful creation and modification responses return the affected resource in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/va-loans/veterans` | Create a veteran; cascade-creates the 1:1 entitlement account | LoanOfficer, ProgramAdmin |
| GET | `/va-loans/veterans/{id}` | Read a veteran | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/veterans/{id}/service-periods` | Add a service period (closed-interval overlap rejected) | LoanOfficer |
| GET | `/va-loans/veterans/{id}/service-periods` | List a veteran's service periods | Veteran, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/veterans/{id}/coe-requests` | Request a Certificate of Eligibility | LoanOfficer |
| GET | `/va-loans/veterans/{id}/coe-requests` | List a veteran's COE requests | Veteran, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/coe-requests/{id}/issue` | Issue a COE after discharge and service review | ProgramAdmin |
| POST | `/va-loans/coe-requests/{id}/deny` | Deny a COE; cascades to loans and appraisals | ProgramAdmin |
| POST | `/va-loans/coe-requests/{id}/reconsider` | Move a DENIED COE back into RECONSIDERATION (max 2) | LoanOfficer, ProgramAdmin |
| GET | `/va-loans/veterans/{id}/entitlement-account` | Read the veteran's 1:1 entitlement account (array of 0-1) | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/veterans/{id}/loans` | Create a loan; computes loan_use and creates the funding fee assessment | LoanOfficer |
| GET | `/va-loans/veterans/{id}/loans` | List a veteran's loans | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| GET | `/va-loans/loans/{id}` | Read a loan | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| GET | `/va-loans/loans` | Filtered list of loans, e.g. by `coe_id` or `veteran_id` | LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/loans/{id}/underwriting-decisions` | Record an underwriting decision; loan underwriting_status follows outcome | Underwriter |
| GET | `/va-loans/loans/{id}/underwriting-decisions` | List decisions on a loan | LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/loans/{id}/close` | Close an approved loan; charges entitlement, collects the fee, creates the occupancy certificate | LoanOfficer |
| POST | `/va-loans/loans/{id}/record-payoff` | Record payoff of a closed loan (sale or refinance) | LoanOfficer |
| GET | `/va-loans/loans/{id}/funding-fee-assessments` | List funding fee assessments for a loan (array of 0-1) | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/funding-fee-assessments/{id}/refund` | Refund a collected fee on retroactive disability exemption | ProgramAdmin |
| POST | `/va-loans/appraisers` | Register an appraiser in the assignment pool | ProgramAdmin |
| GET | `/va-loans/appraisal-requests` | Filtered list of appraisals, e.g. by `appraiser_id`, `loan_id`, or `status` | Appraiser, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/loans/{id}/appraisal-requests` | Order an appraisal; system assigns via selector policy or queues | LoanOfficer |
| GET | `/va-loans/loans/{id}/appraisal-requests` | List appraisals of a loan | Veteran, LoanOfficer, Appraiser, ProgramAdmin |
| GET | `/va-loans/appraisal-requests/{id}` | Read an appraisal | Veteran, LoanOfficer, Appraiser, ProgramAdmin |
| POST | `/va-loans/appraisal-requests/{id}/submit-report` | Assigned appraiser submits the report: VALUE_ISSUED or REPAIRS_REQUIRED | Appraiser |
| GET | `/va-loans/appraisal-requests/{id}/repair-requirements` | List MPR repairs of an appraisal | Veteran, LoanOfficer, Appraiser, ProgramAdmin |
| POST | `/va-loans/repair-requirements/{id}/complete` | Mark a repair completed by the builder side | LoanOfficer |
| POST | `/va-loans/repair-requirements/{id}/verify` | Assigned appraiser verifies a completed repair | Appraiser |
| POST | `/va-loans/repair-requirements/{id}/waive` | Waive an open repair (LoanOfficer may not) | ProgramAdmin |
| GET | `/va-loans/loans/{id}/occupancy-certificates` | List occupancy certificates of a loan (array of 0-1) | Veteran, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/occupancy-certificates/{id}/verify-occupancy` | Verify move-in against the 60-day deadline | LoanOfficer |
| POST | `/va-loans/veterans/{id}/deployment-exceptions` | Record a deployment window (half-open overlap rejected) | Veteran, LoanOfficer |
| GET | `/va-loans/veterans/{id}/deployment-exceptions` | List a veteran's deployment exceptions | Veteran, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/loans/{id}/assumption-requests` | Submit an assumption of the existing loan by a qualified buyer | LoanOfficer |
| GET | `/va-loans/loans/{id}/assumption-requests` | List assumption requests of a loan | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| GET | `/va-loans/veterans/{id}/assumption-requests` | List assumption requests where this veteran is the buyer | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/assumption-requests/{id}/approve` | Approve an assumption; entitlement substitution moves the charge | Underwriter |
| POST | `/va-loans/loans/{id}/refinance-requests` | Create a refinance request; supersedes a prior SUBMITTED one; OCC applies | LoanOfficer |
| GET | `/va-loans/loans/{id}/refinance-requests` | List refinance requests of a loan | Veteran, LoanOfficer, Underwriter, ProgramAdmin |
| POST | `/va-loans/refinance-requests/{id}/evaluate` | Evaluate seasoning then NTB; APPROVED or REJECTED | Underwriter |
| POST | `/va-loans/veterans/{id}/entitlement-restoration-requests` | Request entitlement restoration after payoff | LoanOfficer |
| GET | `/va-loans/veterans/{id}/entitlement-restoration-requests` | List a veteran's restoration requests | Veteran, LoanOfficer, ProgramAdmin |
| GET | `/va-loans/loans/{id}/entitlement-restoration-requests` | List restoration requests citing this loan | Veteran, LoanOfficer, ProgramAdmin |
| POST | `/va-loans/entitlement-restoration-requests/{id}/grant` | Grant restoration; restores the loan's charged entitlement | ProgramAdmin |
| GET | `/va-loans/audit-events` | Filtered list of audit events | ProgramAdmin |
| POST | `/va-loans/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_UNDERWRITER_IS_ORIGINATOR` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_VETERAN_NOT_FOUND` | 404 |
| `ERR_COE_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_APPRAISAL_NOT_FOUND` | 404 |
| `ERR_REPAIR_NOT_FOUND` | 404 |
| `ERR_OCCUPANCY_CERT_NOT_FOUND` | 404 |
| `ERR_ASSUMPTION_NOT_FOUND` | 404 |
| `ERR_REFINANCE_NOT_FOUND` | 404 |
| `ERR_FEE_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_RESTORATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COE_NOT_ISSUED` | 409 |
| `ERR_LOAN_NOT_CLOSABLE` | 409 |
| `ERR_LOAN_NOT_PAID_OFF` | 409 |
| `ERR_FEE_NOT_REFUNDABLE` | 409 |
| `ERR_RECONSIDERATION_EXHAUSTED` | 409 |
| `ERR_APPRAISAL_NOT_ASSIGNED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DISCHARGE_INELIGIBLE` | 422 |
| `ERR_INSUFFICIENT_SERVICE` | 422 |
| `ERR_SERVICE_PERIOD_MISMATCH` | 422 |
| `ERR_SERVICE_PERIOD_OVERLAP` | 409 |
| `ERR_DEPLOYMENT_WINDOW_OVERLAP` | 409 |
| `ERR_SEASONING_NOT_MET` | 422 |
| `ERR_REPAIRS_OUTSTANDING` | 409 |
| `ERR_ASSUMPTION_INELIGIBLE` | 422 |
| `ERR_INVALID_DOWN_PAYMENT` | 422 |
| `ERR_INSUFFICIENT_ENTITLEMENT` | 422 |
