# Real Estate Rent Franchise API — Product Requirements Document

## 1. Introduction

This document specifies the Real Estate Rent Franchise API, the system of record for a franchisor whose economics are built on owning the dirt under its restaurants. The franchisor acquires parcels outright or holds them under long-term ground leases from third-party landowners, then subleases each developed location to a franchised operator. Occupancy income is computed under a greater-of rule — the operator owes whichever is larger: an escalating annual base rent, or a percentage of the year's sales — while royalties and national advertising fund contributions are layered on top of the sales base, split from it under a fixed allocation fraction.

Beyond rent, the API governs the whole operator lifecycle: financial capacity review before approval, portfolio caps derived from the resulting grade, initial franchise fees, renewal rewriting of terms tied to remodel reinvestment obligations, sublease default with an escrow-funded cure waterfall, and repossession with a full unwind cascade. National and local co-op advertising funds carry their own governance, assessment, and disbursement rules with segregated duties between the franchisor's administrative staff, its finance officers, the operators themselves, and local co-op managers.

Every monetary figure is tracked in whole cents and every mutation is versioned, so that billing, reconciliation, and enforcement decisions can be audited against the exact state of the system at the moment they were made.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API, which is mounted under the `/franchise-system` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request in which either header is missing or blank is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles, spelled as follows: `FranchisorAdmin`, `FranchiseFinance`, `Operator`, and `CoopManager`. Any attempt to perform an operation outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The relationship between `X-User-ID` and persisted resources differs by role. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` entity; ownership checks on any resource that references an `Operator` compare the resource's operator foreign-key field to `X-User-ID`, and an `Operator` caller acting on a resource owned by a different operator is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `FranchisorAdmin`, `FranchiseFinance`, or `CoopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. List responses are sorted by the resources' creation timestamps in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset + limit` is less than `total_count`. Out-of-range pagination parameters are clamped rather than rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0; a non-integer `limit` or `offset` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

### 2.4. Common Resource Properties

Every entity in the system — `Site`, `Operator`, `Store`, `FranchiseAgreement`, `Sublease`, `SalesReport`, `RentCharge`, `FundAssessment`, `ReinvestmentObligation`, `DefaultEvent`, `AdvertisingFund`, `CoopAssessment`, and `CapacityReview` — carries a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same style of timestamp refreshed on every modification. `version` is an integer starting at 1 that increments by exactly 1 on every mutation of the resource, including mutations driven by cascades originating on other entities.

### 2.5. The Logical Clock and Temporal Semantics

The system does not consult wall-clock time. A logical clock governs every time-dependent rule — sublease expiry, agreement expiry, reinvestment deadlines, renewal windows. At server startup the logical clock reads exactly 2026-09-01T00:00:00Z, and before any explicit adjustment it never falls back to wall-clock time. A `FranchisorAdmin` may advance the clock by supplying a `current_utc` instant through a test-driving capability; all deadline and expiry evaluations thereafter read this logical clock.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values are integers in whole cents — for example `fy_net_worth_cents`, `base_rent_cents`, and `balance_cents` — and all derived monetary amounts are rounded to whole cents using the round-half-up method. Where a calculation chains several rounding steps, the rounding order is pinned by the business rules in §3; in particular the escalated base rent applies a single composite rounding rather than iterative per-year rounding, and the monthly royalty split rounds the occupancy share first. Rates such as `royalty_rate`, `ad_fund_rate`, `pct_rent_rate`, `escalation_rate`, `occupancy_allocation_pct`, and `admin_fee_rate` are decimal fractions strictly between 0 and 1 where the rule requires a genuine fraction (and greater than or equal to 0 — but still strictly below 1 — for `escalation_rate` and `admin_fee_rate`), and they preserve input precision.

### 2.7. Nested Resource and Foreign-Key Resolution

When an endpoint path contains resource identifiers, the system validates their existence left to right, rejecting with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. The same error applies when a request body references a foreign key that does not exist — `site_id`, `operator_id`, `store_id`, `renewal_of_id`, `fund_id`, or `sublease_id` on creation payloads must all point to live resources before any business rule is evaluated.

### 2.8. Validation Ordering

Incoming requests are checked against a fixed validation cascade, evaluated in the following order so that earlier failures mask later ones. First, the presence and non-emptiness of the `X-User-ID` and `X-User-Role` headers (failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, that the caller's role is permitted on the endpoint (failure yields `ERR_INSUFFICIENT_PERMISSIONS`). Third, that path identifiers resolve to existing resources, validated left to right (failure yields `ERR_RESOURCE_NOT_FOUND`). Fourth, that foreign-key identifiers in the request body resolve (also `ERR_RESOURCE_NOT_FOUND`). Fifth, that the target resource is in the state required by the operation (failure yields `ERR_INVALID_STATE`, HTTP 409, unless the operation names a more specific state error such as `ERR_AGREEMENT_NOT_ACTIVE`). Sixth, ownership for `Operator`-role callers on their own resources (failure yields `ERR_NOT_RESOURCE_OWNER`). Seventh and beyond, the domain business rules — portfolio limits, temporal bounds on subleases and billing periods, singularity of active agreements and subleases, renewal windows, fiscal sufficiency checks — and finally the optimistic-concurrency version match, each with the specific error identifier defined in §3 and §5.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic-concurrency protection, and only these two take a version field. Creating a store accepts the request-body field `expected_operator_version`, holding the client-observed `version` of the `Operator` the store will be attached to; when the field is supplied and the operator's current `version` has advanced since that observation — for example because a capacity review submission changed `max_stores`, or another store was just created — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), while omitting the field skips the version check entirely. Posting an annual rent charge accepts `expected_sublease_version`, holding the client-observed `version` of the `Sublease` the charge will be computed against; a supplied value that mismatches the sublease's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and omission again skips the check. No other endpoint accepts or requires a version field.

### 2.10. Hierarchical Consistency and Cascade Discipline

State changes propagate across entity boundaries automatically, without a client request on the affected resource. When a store completes repossession, its agreement, sublease, open charges, open assessments, and pending obligations are all resolved in one cascade, and its operator is terminated; each affected entity has its own `updated_at` refreshed and its own `version` incremented. Recomputed aggregate fields on the `Operator` — `stores_operated_count` and `delinquency_balance_cents` — are refreshed whenever an underlying store status or charge status changes, and these recomputations are immediate: the system's consistency model is synchronous, never deferred. When a recomputation leaves both aggregates unchanged, the operator's `version` and `updated_at` are not bumped by the recomputation alone. Clock-driven transitions (agreement expiry, sublease expiry, automatic obligation breach) are applied lazily: the logical clock is consulted and due transitions are applied at the start of every request, so state advances are observed no later than the first request after the clock passes the relevant date.

## 3. Business Logic & Workflows

### 3.1. Real Estate Holdings: Sites and Their Commitment Lifecycle

The franchisor's property book begins with the **Site**. A `FranchisorAdmin` registers a site by supplying a human-readable `site_code` (which need not be unique; no uniqueness check is applied), the parcel's street `address`, and an `acquisition_type` of either `FEE_SIMPLE` (the franchisor buys the land outright) or `GROUND_LEASE` (the franchisor holds a long-term ground lease from a third-party landowner). For a `GROUND_LEASE` site, `ground_lease_expiry` — the expiry of the third-party ground lease — is required; for a `FEE_SIMPLE` site it is forbidden. A newly registered site carries `holding_status` `HELD`, meaning no store sits on it and it is available for development.

When a store referencing a site is created, the system automatically transitions the site `HELD → COMMITTED`, bumping its `version`; a `COMMITTED` site hosts exactly one store, which may be `OPEN` or `SUSPENDED`. Only after that store has been repossessed may a `FranchisorAdmin` divest the site, moving it `COMMITTED → DIVESTED`; divesting while the site's store is in any state other than `REPOSSESSED` is rejected with `ERR_SITE_STORE_NOT_REPOSSESSED`. `DIVESTED` is terminal. The sites collection can be listed with a `holding_status` filter, and the stores sitting on a given site are reachable through the site's own sub-resource listing.

### 3.2. Operators: Registration, Capacity Review, and Portfolio Limits

A prospective franchisee enters the system as an **Operator** registered by a `FranchisorAdmin` with a `legal_name`, the most recent fiscal-year net worth `fy_net_worth_cents` in whole cents (zero or greater), and the most recent fiscal-year operating income `fy_operating_income_cents` in whole cents (which may be negative). A new operator starts in `CANDIDATE` status, with `capacity_score` and `capacity_grade` both null until a review is submitted, `stores_operated_count` and `delinquency_balance_cents` at 0, and `escrow_balance_cents` — the reserve held against future default cures — at 0. A `FranchiseFinance` officer may later update the fiscal pair through the operator's fiscal-snapshot capability, supplying fresh `fy_net_worth_cents` (zero or greater) and `fy_operating_income_cents` values that feed subsequent reviews, and may credit the escrow reserve by posting escrow deposits carrying a positive `amount_cents` (at least 1 cent), each deposit adding to `escrow_balance_cents`.

Approval is gated on a **CapacityReview**. A `FranchiseFinance` officer opens a review for an operator with a `review_period` identifying the fiscal year under review (format YYYY); the review starts in `DRAFT`. The operator's status is not checked at review-open time, and multiple `DRAFT` reviews may coexist for one operator. Submitting the review freezes the computed scores and pushes them onto the operator. At submission the system first refreshes the operator's aggregates, then counts the `DefaultEvent` records in `DECLARED` status across all of the operator's stores into `active_defaults_count`, counts the `ReinvestmentObligation` records in `PENDING` or `BREACHED` status across all of the operator's stores into `pending_reinvestment_count`, and computes a `composite_score` from four weighted components. The net-worth component is 100 times the lesser of 1.0 and the ratio of `fy_net_worth_cents` to two hundred million cents — full credit at two million dollars of net worth. The operating-margin component is 100 times the lesser of 1.0 and the ratio of (the greater of 0.0 and the ratio of `fy_operating_income_cents` to `fy_net_worth_cents`) to 0.25 — full credit at a twenty-five percent operating margin, with negative margins floored at zero credit. The portfolio component is 100 times the lesser of 1.0 and the ratio of `stores_operated_count` to ten — full credit at ten open stores. The compliance component starts at 100 and subtracts 30 points per active default, 20 points per pending-or-breached reinvestment obligation, and 20 points scaled by the lesser of 1.0 and the ratio of `delinquency_balance_cents` to fifty thousand dollars (5,000,000 cents). The `composite_score` is the round-half-up of the weighted sum: 0.35 times the net-worth component, plus 0.25 times the operating-margin component, plus 0.20 times the portfolio component, plus 0.20 times the compliance component, clamped into the inclusive range 0 to 100 and thereby yielding an integer from 0 to 100. The review's `grade` bands from the score with the low edge of each band inclusive: at least 80 is `STRONG`, 60 through 79 is `ADEQUATE`, 40 through 59 is `WEAK`, and below 40 is `FAILING`. Submission transitions the review `DRAFT → SUBMITTED`, writes `capacity_score`, `capacity_grade`, and `max_stores` onto the operator, and increments both the review's and the operator's `version`.

The `capacity_grade` determines `max_stores`: `STRONG` permits 12 stores, `ADEQUATE` permits 6, `WEAK` permits 2, `FAILING` permits 0, and an operator with no submitted review at all has `max_stores` 0. The headroom check at store creation subtracts the operator's `stores_operated_count` — which counts only the operator's stores whose `status` is `OPEN`, excluding `SETUP`, `SUSPENDED`, and `REPOSSESSED` — from `max_stores`; creation requires headroom strictly greater than zero, and at the exact boundary where headroom is zero the creation is rejected with `ERR_PORTFOLIO_LIMIT_REACHED`.

Operator status moves under administrative control and under cascade. A `FranchisorAdmin` approves a `CANDIDATE` operator only when a `SUBMITTED` capacity review exists for that operator whose grade is `STRONG` or `ADEQUATE`; otherwise approval is rejected with `ERR_CAPACITY_REVIEW_REQUIRED`. Approval recomputes `max_stores` from the grade and moves the operator `CANDIDATE → APPROVED`. An `APPROVED` operator may be suspended (`APPROVED → SUSPENDED`) unconditionally. Reinstatement from `SUSPENDED` back to `APPROVED` requires that `capacity_grade` is not `FAILING` (else `ERR_CAPACITY_GRADE_FAILING`) and that `delinquency_balance_cents` is exactly 0 (else `ERR_OUTSTANDING_DELINQUENCY`). Finally, whenever any of the operator's stores completes repossession, the operator is automatically terminated — `APPROVED → TERMINATED` or `SUSPENDED → TERMINATED`, with `TERMINATED` terminal.

### 3.3. Bringing a Store to Life: Creation, Agreements, Subleases, and Opening

A `FranchisorAdmin` creates a **Store** by supplying a human-readable `store_code`, the `site_id` of the site it will occupy, and the `operator_id` of its operator, plus the optimistic-concurrency field `expected_operator_version` described in §2.9. The `store_code` need not be unique; no uniqueness check is applied to it. Creation requires that the site be `HELD`, that the operator be `APPROVED`, and that the portfolio headroom rule of §3.2 passes; all three violations are rejected with `ERR_PORTFOLIO_LIMIT_REACHED` (an un-held site and a non-`APPROVED` operator share that error with the headroom failure). A new store starts in `SETUP` status — no active sublease yet — and its creation flips the site `HELD → COMMITTED` and increments the operator's `version`.

The **FranchiseAgreement** captures the economic terms. Drafting one takes the `store_id`, the `operator_id` (which must equal the store's operator, else the drafting is rejected as a malformed request with HTTP 400), a positive `initial_fee_cents`, a `royalty_rate` and an `ad_fund_rate` (both decimals strictly between 0 and 1) applied to the royalty-allocated share of sales, an `occupancy_allocation_pct` (also strictly between 0 and 1) fixing what fraction of monthly sales is deemed occupancy-allocated with the remainder royalty-allocated, a `term_years` of at least 1 whole year, and a `term_start_date`. The system computes `term_end_date` as `term_start_date` plus `term_years`, landing on the same calendar day minus one day; when the resulting anniversary would fall on February 29 of a non-leap year, the anniversary is taken as February 28 before the one-day subtraction. A renewal agreement additionally carries `renewal_of_id` referencing the agreement it rewrites; original agreements leave it null. A store may have at most one non-terminal agreement — drafting while another agreement for the store exists in `DRAFT`, `FEE_PENDING`, or `ACTIVE` status is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`.

A drafted agreement moves `DRAFT → FEE_PENDING` when a `FranchisorAdmin` submits it for fee invoicing. For renewals, submission is additionally gated, with the gates evaluated in this order: the referenced agreement must be `ACTIVE` (a referenced agreement in any other state is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`), then it must carry a `ReinvestmentObligation` in `SATISFIED` status (else `ERR_RENEWAL_REINVESTMENT_UNMET`), and finally its term must end within 180 days of the logical clock — the window is inclusive of both boundaries, covering term-end dates from the logical-clock date itself through exactly 180 days out (else `ERR_RENEWAL_WINDOW_NOT_OPEN`). Recording the initial fee payment is a segregated duty performed by a `FranchiseFinance` officer, whose `amount_cents` must be at least the agreement's `initial_fee_cents` — a shortfall is rejected with `ERR_INSUFFICIENT_FEE_PAYMENT` (HTTP 402). Payment moves the agreement `FEE_PENDING → ACTIVE`, and if the agreement is a renewal, the referenced agreement simultaneously moves `ACTIVE → SUPERSEDED`, its terms rewritten by the new agreement. An `ACTIVE` agreement whose `term_end_date` passes with no renewal submitted moves automatically to `EXPIRED`; repossession of the store moves it to `TERMINATED`. `EXPIRED`, `SUPERSEDED`, and `TERMINATED` are all terminal.

The **Sublease** sets the occupancy terms. Drafting one takes the `store_id` and `operator_id` (again matching the store's operator, else the drafting is rejected as a malformed request with HTTP 400), a positive annual `base_rent_cents` on a year-1 basis, a `pct_rent_rate` strictly between 0 and 1, an `escalation_rate` of 0 or more (and strictly below 1, per §2.6), the `escalation_month` (1–12) and `escalation_day` (1–28) fixing the annual escalation anniversary, and a `start_date` with an `end_date` strictly after it — an `end_date` at or before `start_date` is rejected with `ERR_SUBLEASE_BEYOND_GROUND_LEASE` (HTTP 422). For stores on `GROUND_LEASE` sites the `end_date` must not extend beyond the site's `ground_lease_expiry`; a sublease reaching past it is rejected with `ERR_SUBLEASE_BEYOND_GROUND_LEASE` (HTTP 422), both at drafting and again at activation. A store may have at most one non-terminal sublease at a time — drafting while another sublease for the store exists in `PENDING`, `ACTIVE`, `DEFAULTED`, or `CURED` status is rejected with `ERR_ACTIVE_SUBLEASE_EXISTS`. A new sublease starts `PENDING`.

Activation by a `FranchisorAdmin` moves the sublease `PENDING → ACTIVE` and requires that the store's agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and that the store has no other sublease in `ACTIVE`, `DEFAULTED`, or `CURED` status (else `ERR_ACTIVE_SUBLEASE_EXISTS`). Once the logical clock passes the `end_date`, an `ACTIVE` sublease expires automatically to `EXPIRED`. The sublease's `active_default_id` is null normally and points at the outstanding `DefaultEvent` while a curable default is in flight.

Opening the store is the final step: a `FranchisorAdmin` opens a `SETUP` store only when the store has a `FranchiseAgreement` in `ACTIVE` status (else `ERR_AGREEMENT_NOT_ACTIVE`), a `Sublease` in `ACTIVE` status (else `ERR_SUBLEASE_NOT_ACTIVE`), and an operator in `APPROVED` status (else `ERR_OPERATOR_NOT_APPROVED`). Opening stamps `opened_at` with the current logical clock, moves the store `SETUP → OPEN`, and recomputes the operator's `stores_operated_count`.

### 3.4. Sales Reporting, Billing Runs, and the Occupancy/Royalty Split

Each month, the operating **Operator** files a **SalesReport** for a store, supplying the `store_id`, the `period_month` in YYYY-MM format, and `gross_sales_cents` in whole cents (zero or greater); there is one report per store per month. Filing a report is itself owner-only: the `X-User-ID` must equal the operator that owns the store (else `ERR_NOT_RESOURCE_OWNER`); the store's status is not checked at filing time. A new report starts in `DRAFT`. Submitting the report is likewise an owner-only action: the `X-User-ID` must equal the operator that owns the report's store (else `ERR_NOT_RESOURCE_OWNER`), and the store must be `OPEN` (else `ERR_STORE_NOT_OPEN`). Submission moves the report `DRAFT → SUBMITTED`.

A `FranchiseFinance` officer then posts a monthly **billing run** for a store and `period_month`. The billing run consumes the month's `SUBMITTED` report — when no `SUBMITTED` report exists for that store and month, the posting is rejected with `ERR_INVALID_STATE` (HTTP 409) — locking it `SUBMITTED → LOCKED` so it can feed rent calculations, and emits a **FundAssessment** recording the month's royalty and advertising split. The split follows a pinned rounding order. First, the `occupancy_share_cents` is computed as `gross_sales_cents` multiplied by the agreement's `occupancy_allocation_pct`, rounded half-up to whole cents — this rounding happens first. Second, the `royalty_sales_cents` is the remainder, `gross_sales_cents` minus `occupancy_share_cents`, and is never independently rounded. Third, `royalty_cents` is the round-half-up of `royalty_sales_cents` times `royalty_rate`, and `ad_fund_cents` is the round-half-up of `royalty_sales_cents` times `ad_fund_rate` — each rounding per line from the un-rounded remainder. The assessment also records a forward-looking `provisional_royalty_cents`, equal to 12 times that month's `royalty_cents`, annualizing the single month and ignoring the rest of the year's actuals; `final_royalty_cents` remains null until annual reconciliation. The assessment is created in `OPEN` status and carries the `store_id`, the `agreement_id` of the store's active agreement, and the `period_month`.

Annual royalty reconciliation, invoked by a `FranchiseFinance` officer for a store and a `fiscal_year` (in YYYY format), replays the year's actual locked reports: when the store has no `LOCKED` reports for that fiscal year the run is rejected with `ERR_INVALID_STATE` (HTTP 409), and the store's agreement must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`). The year's summed royalty-allocated sales are computed by rounding each month's occupancy share half-up first and subtracting it from that month's gross sales — the same per-month split as the billing run — then summing those remainders; `final_royalty_cents` is populated on the year's assessments as the round-half-up of that sum times the `royalty_rate`, and the delta against the provisional figures is surfaced. The response carries the last of the year's assessments with the populated figure. Because the provisional variant annualizes one month while the final variant replays actuals, identical underlying data produces different totals whenever monthly sales are not uniform.

Paying an open assessment — performed by a `FranchiseFinance` officer — requires the assessment to be `OPEN` (else `ERR_ASSESSMENT_NOT_OPEN`) and moves it `OPEN → PAID`, crediting the national advertising fund's `balance_cents` by the `ad_fund_cents` amount, less the administration fee withheld per the fund's configuration.

### 3.5. Annual Rent: Escalation, the Greater-Of Rule, and Payment

Rent is billed annually. A `FranchiseFinance` officer posts a **RentCharge** for a store by supplying the `store_id`, the `billing_period` in YYYY format (one charge per store per billing year), the inclusive `period_start` and `period_end` dates bounding the billing year, and the optimistic-concurrency field `expected_sublease_version` described in §2.9. The billing period must lie entirely inside the sublease's term — `period_start` and `period_end` within `start_date` and `end_date`, with `period_end` at or after `period_start` — otherwise the posting is rejected with `ERR_CHARGE_PERIOD_OUT_OF_TERM` (HTTP 422). The store must have a sublease in `ACTIVE` status at posting time (else `ERR_SUBLEASE_NOT_ACTIVE`), and the charge binds the `sublease_id` of that active sublease; a `sublease_id` supplied in the request body must resolve if present but does not override this binding.

The escalated base rent is computed from the sublease terms. The `escalation_count` counts how many escalation anniversaries — dates constructed from each year in the billing span combined with the sublease's `escalation_month` and `escalation_day` — fall within the inclusive bounds of the billing period, scanning every year from the year of `period_start` through the year of `period_end`. The `effective_base_rent_cents` is then the round-half-up of `base_rent_cents` multiplied by the compound factor: one plus the `escalation_rate`, raised to the power of `escalation_count`. The composite factor is rounded exactly once; iterative rounding year by year is forbidden.

The percentage alternative uses the year's locked sales. The `annual_sales_cents` is the sum of `gross_sales_cents` over the store's SalesReports whose status is `LOCKED` and whose `period_month`'s first day falls inside the inclusive billing period bounds; `DRAFT` and `SUBMITTED` reports are excluded. The `percentage_rent_cents` is the round-half-up of `annual_sales_cents` times the sublease's `pct_rent_rate`. The billed `selected_rent_cents` follows the greater-of rule: when `effective_base_rent_cents` is greater than or equal to `percentage_rent_cents`, the escalated base binds and the percentage component is reported but not billed; when `percentage_rent_cents` exceeds `effective_base_rent_cents`, the percentage-of-sales figure binds and the escalated base is reported but not billed.

A new charge is created in `OPEN` status with `amount_paid_cents` at zero, and its creation increments the bound sublease's `version` and recomputes the operator's `delinquency_balance_cents`. Payments arrive through a `FranchiseFinance` officer against a charge that must be `OPEN` (else `ERR_CHARGE_NOT_OPEN`); each payment's `amount_cents` (which must be positive, at least 1 cent) adds to `amount_paid_cents`, and when the cumulative payments reach or exceed the selected rent the charge moves `OPEN → PAID` — an overpayment is accepted, the full amount is recorded in `amount_paid_cents`, and nothing is refunded — again recomputing `delinquency_balance_cents`. The `delinquency_balance_cents` on the operator is the sum of the unpaid amount over all of the operator's stores' `OPEN` rent charges — each charge's unpaid amount being `selected_rent_cents` minus `amount_paid_cents` — plus the full `royalty_cents` plus `ad_fund_cents` of each of their `OPEN` fund assessments.

### 3.6. Reinvestment Obligations at Renewal

Remodel commitments ride on specific agreements. A `FranchisorAdmin` attaches a **ReinvestmentObligation** by supplying the `store_id`, the `agreement_id` of the agreement or renewal it rides on, a positive committed `required_budget_cents`, and a `deadline_date` by which spend must be submitted. The system computes `min_spend_cents` as the round-half-up of `required_budget_cents` times 0.70 — seventy percent minimum coverage — and the obligation starts in `PENDING` with `verified_spend_cents` at zero.

The owning operator submits remodel spend with an `amount_cents`; submission is owner-only (a mismatched `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`) and must arrive on or before `deadline_date` (a later submission is rejected with `ERR_REINVESTMENT_DEADLINE_PASSED`). Submission adds the amount to `verified_spend_cents` pending verification and moves the obligation `PENDING → SUBMITTED`. A `FranchiseFinance` officer then either verifies or rejects the submission. Verification succeeds only when the post-addition `verified_spend_cents` is at least `min_spend_cents` — the boundary is inclusive — moving the obligation `SUBMITTED → SATISFIED`; an underfunded verification is rejected with `ERR_REINVESTMENT_UNDERFUNDED`. Rejection moves the obligation `SUBMITTED → BREACHED`. Independently, if the logical clock passes `deadline_date` while the obligation is still `PENDING`, it breaches automatically (`PENDING → BREACHED`). Both `SATISFIED` and `BREACHED` are terminal. As §3.3 describes, a `SATISFIED` obligation on the referenced agreement is a precondition for submitting a renewal.

### 3.7. Default, Cure, and the Escrow Waterfall

When an operator falls behind, a `FranchisorAdmin` declares default on the store's `ACTIVE` sublease, supplying a free-text `reason` (for example RENT_NONPAYMENT) and a non-negative administrative `cure_fee_cents`. Declaration creates a **DefaultEvent** in `DECLARED` status (returned with HTTP 200 rather than 201) whose `shortfall_cents` captures the store's delinquency at the moment of declaration — the unpaid amounts of the store's `OPEN` rent charges plus the full `royalty_cents` plus `ad_fund_cents` of its `OPEN` fund assessments — and whose `store_id` is copied from the sublease; the sublease moves `ACTIVE → DEFAULTED` and records the new event in `active_default_id`, while the store moves `OPEN → SUSPENDED`, which recomputes the operator's `stores_operated_count` (the store no longer counts as open) and `delinquency_balance_cents`.

Curing the default is a `FranchiseFinance` duty gated on the event being `DECLARED` (else `ERR_DEFAULT_NOT_DECLARED`) and follows an all-or-nothing escrow waterfall. The required amount is the event's `shortfall_cents` plus its `cure_fee_cents`. If the operator's `escrow_balance_cents` is below the required amount, the cure is rejected with `ERR_INSUFFICIENT_CURE_FUNDS` (HTTP 402) and no state changes — a partial cure is never persisted. Otherwise the escrow is debited by the full required amount, the shortfall is applied to the store's `OPEN` rent charges oldest first in `created_at` ascending order — each charge absorbing the lesser of the remaining shortfall and its own unpaid amount, and being marked `PAID` as soon as its cumulative payments reach or exceed its selected rent — the event moves `DECLARED → CURED`, the sublease's `active_default_id` clears to null and the sublease moves `DEFAULTED → CURED`, and the store moves `SUSPENDED → OPEN` with the operator counters recomputed again. A `CURED` sublease returns to normal standing when a `FranchisorAdmin` reinstates it, `CURED → ACTIVE`.

### 3.8. Repossession and the Unwind Cascade

When a default cannot be cured, a `FranchisorAdmin` repossesses the store behind the `DECLARED` event (an event in any other state is rejected with `ERR_DEFAULT_NOT_DECLARED`). Repossession moves the event `DECLARED → REPOSSESSED`, the sublease `DEFAULTED → REPOSSESSED` with its `active_default_id` cleared to null, and the store `SUSPENDED → REPOSSESSED`, where the store transition fans out into the full unwind cascade: the store's `ACTIVE` franchise agreement moves to `TERMINATED`; every one of the store's `OPEN` rent charges moves to `WAIVED`, every `OPEN` fund assessment moves to `WAIVED`, and every `ASSESSED` co-op assessment moves to `WAIVED`; every `PENDING` or `SUBMITTED` reinvestment obligation moves to `BREACHED`; and the operator moves to `TERMINATED` with `delinquency_balance_cents` recomputed — waived charges drop out of the delinquency sum. Each entity touched by the cascade has its own `version` incremented. `REPOSSESSED` is terminal for the store, the sublease, and the event. Only after this point may the site's divestment proceed, as described in §3.1.

### 3.9. Advertising Funds: National Governance and Local Co-ops

The **AdvertisingFund** entity represents both the national brand fund and regional local co-ops. A `FranchisorAdmin` creates a fund with a `name`, a `fund_type` of `NATIONAL` or `LOCAL_COOP`, and a non-negative `admin_fee_rate` (below 1, per §2.6) withheld from assessments; a `region_code` identifies the region and is required for `LOCAL_COOP` funds, while for `NATIONAL` funds it must be null — supplying one is rejected as a malformed request with HTTP 400. A new fund starts with `governance_status` `ACTIVE` and `balance_cents` zero.

The fund's `balance_cents` rolls up as the sum of assessment credits minus the sum of disbursements minus the sum of administration fees, where the administration fee on each credit is the round-half-up of that credit times the `admin_fee_rate`, withheld per credit at posting time and rounded per credit. Paying a national `FundAssessment` (§3.4) credits the national fund by its `ad_fund_cents` — when more than one `NATIONAL` fund exists, the credit lands on the earliest-created one; when none exists, no fund is credited — while paying a `CoopAssessment` credits the local co-op fund named by the assessment's `fund_id`.

A `FranchiseFinance` officer pays an `ASSESSED` co-op assessment — an assessment in any other state is rejected with `ERR_ASSESSMENT_NOT_OPEN` — moving it `ASSESSED → PAID` and crediting the fund. **CoopAssessment** records themselves are raised by a `CoopManager`, who assesses a member store into a local co-op fund by supplying the `fund_id` (local co-op funds only — naming a `NATIONAL` fund is rejected with `ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403), the `store_id`, and a positive `amount_cents`; the assessment starts in `ASSESSED` status. Both fund assessments and co-op assessments that are still open when a store is repossessed are waived by the §3.8 cascade.

Disbursements are governance-gated. Either a `FranchisorAdmin` or a `CoopManager` may disburse from a fund by supplying an `amount_cents` and a `purpose`, but a `CoopManager` is restricted to `LOCAL_COOP` funds — attempting to disburse from a `NATIONAL` fund is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Disbursement requires the fund's `governance_status` to be `ACTIVE`; a disbursement against a `FROZEN` fund is rejected with `ERR_FUND_FROZEN`. It also requires sufficient balance: an `amount_cents` exceeding the fund's `balance_cents` is rejected with `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 402); an amount exactly equal to the balance is permitted and drains the fund to zero. A successful disbursement debits `balance_cents` by the amount. A `FranchisorAdmin` freezes a fund (`ACTIVE → FROZEN`) to halt disbursements and unfreezes it (`FROZEN → ACTIVE`) to resume; freezing has no effect on assessment credits.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Two exceptions: declaring a default (§3.7) returns `200 OK` even though it creates a DefaultEvent, and setting the logical clock (§2.5) returns `200 OK` with an empty data object. The request payloads, preconditions, and side effects of each operation are defined by the narratives in §3; this table is an index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/franchise-system/_clock/set_current_utc` | Set the logical clock | FranchisorAdmin |
| POST | `/franchise-system/sites` | Register a site (fee-simple purchase or ground lease) | FranchisorAdmin |
| GET | `/franchise-system/sites` | List sites | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| GET | `/franchise-system/sites/{siteId}` | Get one site | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| POST | `/franchise-system/sites/{siteId}/divest` | Divest a COMMITTED site whose store was repossessed | FranchisorAdmin |
| GET | `/franchise-system/sites/{siteId}/stores` | List stores on a site | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| POST | `/franchise-system/operators` | Register an operator candidate | FranchisorAdmin |
| GET | `/franchise-system/operators` | List operators | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| GET | `/franchise-system/operators/{operatorId}` | Get one operator | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| POST | `/franchise-system/operators/{operatorId}/approve` | Approve a CANDIDATE operator | FranchisorAdmin |
| POST | `/franchise-system/operators/{operatorId}/suspend` | Suspend an APPROVED operator | FranchisorAdmin |
| POST | `/franchise-system/operators/{operatorId}/reinstate` | Reinstate a SUSPENDED operator | FranchisorAdmin |
| PUT | `/franchise-system/operators/{operatorId}/fiscal-snapshot` | Update fiscal-year net worth and operating income | FranchiseFinance |
| POST | `/franchise-system/operators/{operatorId}/escrow-deposits` | Deposit escrow reserve against future default cure | FranchiseFinance |
| POST | `/franchise-system/capacity-reviews` | Open a capacity review for an operator | FranchiseFinance |
| GET | `/franchise-system/capacity-reviews` | List capacity reviews | FranchisorAdmin, FranchiseFinance |
| GET | `/franchise-system/capacity-reviews/{reviewId}` | Get one capacity review | FranchisorAdmin, FranchiseFinance |
| POST | `/franchise-system/capacity-reviews/{reviewId}/submit` | Submit a review; freeze score and push grade to the operator | FranchiseFinance |
| POST | `/franchise-system/stores` | Create a store on a held site for an approved operator | FranchisorAdmin |
| GET | `/franchise-system/stores` | List stores | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| GET | `/franchise-system/stores/{storeId}` | Get one store | FranchisorAdmin, FranchiseFinance, Operator, CoopManager |
| POST | `/franchise-system/stores/{storeId}/open` | Open a SETUP store once agreement and sublease are ACTIVE | FranchisorAdmin |
| POST | `/franchise-system/agreements` | Draft a franchise agreement (original or renewal) | FranchisorAdmin |
| GET | `/franchise-system/agreements` | List agreements | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/agreements/{agreementId}` | Get one agreement | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/agreements/{agreementId}/submit` | Submit a DRAFT agreement for fee invoicing | FranchisorAdmin |
| POST | `/franchise-system/agreements/{agreementId}/record-fee-payment` | Record the initial franchise fee payment | FranchiseFinance |
| POST | `/franchise-system/subleases` | Draft a sublease for a store | FranchisorAdmin |
| GET | `/franchise-system/subleases` | List subleases | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/subleases/{subleaseId}` | Get one sublease | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/subleases/{subleaseId}/activate` | Activate a PENDING sublease | FranchisorAdmin |
| POST | `/franchise-system/subleases/{subleaseId}/declare-default` | Declare default on an ACTIVE sublease | FranchisorAdmin |
| POST | `/franchise-system/subleases/{subleaseId}/reinstate` | Reinstate a CURED sublease to ACTIVE | FranchisorAdmin |
| GET | `/franchise-system/default-events` | List default events | FranchisorAdmin, FranchiseFinance |
| GET | `/franchise-system/default-events/{defaultId}` | Get one default event | FranchisorAdmin, FranchiseFinance |
| POST | `/franchise-system/default-events/{defaultId}/cure` | Cure a DECLARED default via the escrow waterfall | FranchiseFinance |
| POST | `/franchise-system/default-events/{defaultId}/repossess` | Repossess the store behind a DECLARED default | FranchisorAdmin |
| POST | `/franchise-system/sales-reports` | Create a monthly sales report | Operator |
| GET | `/franchise-system/sales-reports` | List sales reports | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/sales-reports/{reportId}` | Get one sales report | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/sales-reports/{reportId}/submit` | Submit a DRAFT report (owner-operator only) | Operator |
| POST | `/franchise-system/rent-charges` | Post an annual rent charge | FranchiseFinance |
| GET | `/franchise-system/rent-charges` | List rent charges | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/rent-charges/{chargeId}` | Get one rent charge | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/rent-charges/{chargeId}/pay` | Pay an OPEN rent charge | FranchiseFinance |
| POST | `/franchise-system/billing-runs` | Post a monthly billing run; lock the report and emit a FundAssessment | FranchiseFinance |
| GET | `/franchise-system/fund-assessments` | List fund assessments | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/fund-assessments/{assessmentId}` | Get one fund assessment | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/fund-assessments/{assessmentId}/pay` | Pay an OPEN fund assessment | FranchiseFinance |
| POST | `/franchise-system/stores/{storeId}/annual-reconciliation` | Run annual royalty reconciliation for a store-year | FranchiseFinance |
| POST | `/franchise-system/reinvestment-obligations` | Attach a remodel obligation to an agreement | FranchisorAdmin |
| GET | `/franchise-system/reinvestment-obligations` | List reinvestment obligations | FranchisorAdmin, FranchiseFinance, Operator |
| GET | `/franchise-system/reinvestment-obligations/{obligationId}` | Get one obligation | FranchisorAdmin, FranchiseFinance, Operator |
| POST | `/franchise-system/reinvestment-obligations/{obligationId}/submit-spend` | Operator submits remodel spend (owner only) | Operator |
| POST | `/franchise-system/reinvestment-obligations/{obligationId}/verify-spend` | Finance verifies submitted spend | FranchiseFinance |
| POST | `/franchise-system/reinvestment-obligations/{obligationId}/reject-spend` | Finance rejects submitted spend | FranchiseFinance |
| POST | `/franchise-system/advertising-funds` | Create the national fund or a local co-op fund | FranchisorAdmin |
| GET | `/franchise-system/advertising-funds` | List funds | FranchisorAdmin, FranchiseFinance, CoopManager |
| GET | `/franchise-system/advertising-funds/{fundId}` | Get one fund | FranchisorAdmin, FranchiseFinance, CoopManager |
| POST | `/franchise-system/advertising-funds/{fundId}/freeze` | Freeze a fund (halts disbursements) | FranchisorAdmin |
| POST | `/franchise-system/advertising-funds/{fundId}/unfreeze` | Unfreeze a fund | FranchisorAdmin |
| POST | `/franchise-system/advertising-funds/{fundId}/disburse` | Disburse from a fund (governance-gated) | FranchisorAdmin, CoopManager |
| POST | `/franchise-system/coop-assessments` | Assess a store into a local co-op fund | CoopManager |
| GET | `/franchise-system/coop-assessments` | List co-op assessments | FranchisorAdmin, FranchiseFinance, CoopManager, Operator |
| GET | `/franchise-system/coop-assessments/{assessmentId}` | Get one co-op assessment | FranchisorAdmin, FranchiseFinance, CoopManager, Operator |
| POST | `/franchise-system/coop-assessments/{assessmentId}/pay` | Pay an ASSESSED co-op assessment | FranchiseFinance |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SITE_STORE_NOT_REPOSSESSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUBLEASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPERATOR_NOT_APPROVED` | 409 Conflict |
| `ERR_CAPACITY_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_CAPACITY_GRADE_FAILING` | 409 Conflict |
| `ERR_OUTSTANDING_DELINQUENCY` | 409 Conflict |
| `ERR_PORTFOLIO_LIMIT_REACHED` | 409 Conflict |
| `ERR_ACTIVE_AGREEMENT_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_SUBLEASE_EXISTS` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_RENEWAL_REINVESTMENT_UNMET` | 409 Conflict |
| `ERR_INSUFFICIENT_FEE_PAYMENT` | 402 Payment Required |
| `ERR_SUBLEASE_BEYOND_GROUND_LEASE` | 422 Unprocessable Entity |
| `ERR_CHARGE_PERIOD_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_CHARGE_NOT_OPEN` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_OPEN` | 409 Conflict |
| `ERR_STORE_NOT_OPEN` | 409 Conflict |
| `ERR_DEFAULT_NOT_DECLARED` | 409 Conflict |
| `ERR_INSUFFICIENT_CURE_FUNDS` | 402 Payment Required |
| `ERR_REINVESTMENT_DEADLINE_PASSED` | 409 Conflict |
| `ERR_REINVESTMENT_UNDERFUNDED` | 409 Conflict |
| `ERR_FUND_FROZEN` | 409 Conflict |
| `ERR_INSUFFICIENT_FUND_BALANCE` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
