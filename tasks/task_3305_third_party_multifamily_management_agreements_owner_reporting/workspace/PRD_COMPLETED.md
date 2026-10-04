# Multifamily Management Agreements API — Product Requirements Document

## 1. Introduction

Third-party multifamily property management is, at its core, a fiduciary business. A manager such as Greystar runs day-to-day operations of apartment communities on behalf of institutional owners — collecting rents, paying vendors and staff, proposing budgets and rents, absorbing or allocating risk — and then reports the results back to the owner, month after month, in a package the owner's lenders and asset managers rely on. Every dollar that flows through the property is governed by a negotiated management agreement: the base fee is a percentage of collected revenue subject to a minimum, incentives kick in above thresholds, tail fees follow the manager after a termination for convenience, and indemnification for resident incidents and employment claims is split by contract.

This document specifies the Multifamily Management Agreements API, mounted under `/mgmt`. The API models the full arc of the manager-owner relationship: agreement authoring and activation, onboarding a property from a prior manager (resident data, ledger balances, vendor contract transition), the monthly operating cycle (ledger postings, statement close with fee and payroll computation, owner distribution, lender reporting), budget and reforecast approval under segregation of duties, revenue-management pricing with owner override rights, claims and settlements within the agreement's risk allocation, and finally disposition or termination with its fee-tail and transition obligations.

Because owners, lenders, and managers may each dispute the books, the system maintains a single logical clock, immediate consistency, and optimistic concurrency on the handful of writes where a stale read would be financially material. Every computed figure — the management fee, the incentive fee, the payroll allocation, the owner distribution, the termination tail, the claim settlement split — is a deterministic function of posted ledger entries and agreement terms, recomputed in a pinned evaluation order and always rounded to whole cents.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` identifies their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing. The system recognizes five roles, spelled exactly as follows: `PortfolioManager`, `PropertyAccountant`, `OwnerRep`, `RevenueAnalyst`, and `RiskOfficer`. An attempt to perform an operation outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

`PortfolioManager` is the manager-side executive: it owns owners, properties, agreements and their lifecycle actions, onboarding activation and abort, staffing, and control of the logical clock and monthly epoch. `PropertyAccountant` is the manager-side operator: it runs onboarding data, ledger, and vendor steps; authors and submits budgets; posts ledger entries; opens, closes, and restates statements; and builds, generates, and delivers report packages. `OwnerRep` is the owner-side representative: it approves or rejects budgets, overrides published pricing, initiates agreement termination, and drives property disposition. `RevenueAnalyst` is the manager-side revenue-management function: it proposes, publishes, and withdraws pricing recommendations. `RiskOfficer` is the manager-side risk function: it files, reviews, settles, and closes claims. All five roles may call any GET endpoint.

Role identity works as follows. When `X-User-Role` is `OwnerRep`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that references an `Owner` compare the resource's `owner_id` foreign key to `X-User-ID`. When `X-User-Role` is `PortfolioManager`, `PropertyAccountant`, `RevenueAnalyst`, or `RiskOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `decided_by` on a `Budget` when an owner-side decision is captured, or as the submitting user compared against during segregation-of-duties checks — but does not compare it to any entity's `id`.

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

Endpoints that return lists are paginated through query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending, with `id` ascending as the tie-break for equal timestamps. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. The Logical Clock and the Monthly Epoch

All time-dependent rules in this system — statement close eligibility, pricing window liveness, distribution grace windows, agreement expiry, lender-report overdue checks, and the annual NOI incentive settlement — are evaluated against a single server-side **logical clock**, never against real wall-clock time. Before any client sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`; the server must not silently fall back to wall-clock time at any point.

A `PortfolioManager` may set the logical clock to a supplied `to_iso8601` instant; a missing or malformed `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and a successful set returns `current_utc`, the new logical-clock time, in the response data. Setting the clock moves time but performs no automatic month roll. Separately, a `PortfolioManager` may advance the global operating epoch by one month. Month advance always moves the logical clock to the first day of the next calendar month (00:00:00Z), and a successful advance returns the new epoch month as `epoch_month` in `YYYY-MM` format in the response data; the month that just ended is the **closing period** of the advance. Month advance is the batch boundary at which three classes of deferred work run, in this order: agreements whose `term_end_date` has been reached expire (see §3.7), the annual NOI incentive is settled when the closing period is December (see §3.6), and any `LENDER` report package on a disposition-listed property that was not delivered by month-end raises `ERR_LENDER_REPORT_OVERDUE` (see §3.8) — a `LENDER` package counts as undelivered when its `status` is not `DELIVERED` and its `period_month` is strictly earlier than the new epoch month, and when any such package exists the advance is rejected with `ERR_LENDER_REPORT_OVERDUE` and does not return a new epoch month. The steps run in the pinned order above and the clock move happens first, so a rejected advance still leaves the logical clock at the new month and keeps the expiry and annual-incentive effects that already ran.

### 2.5. Common Resource Properties

Every primary resource — `Owner`, `ManagementAgreement`, `Property`, `OnboardingTransition`, `Resident`, `VendorContract`, `Budget`, `PricingRecommendation`, `StaffPosition`, `MonthlyStatement`, `LedgerEntry`, `OwnerReportPackage`, and `Claim` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation.
- `version` (integer): a system-managed integer that increments with every modification to the resource; it is the basis of optimistic concurrency control.

`ClaimSettlement` is the single exception: it is created once, at the moment a claim settles, and never mutated thereafter. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right: the owner first, then the property or agreement, then the child resource. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in the path that does not correspond to an existing resource, and no later identifier is examined. This ordering applies uniformly to reads, creations, and action calls under nested paths. The path parameter names used throughout the API are `ownerId`, `propertyId`, `agreementId`, `onboardingId`, `residentId`, `vendorContractId`, `budgetId`, `pricingId`, `staffPositionId`, `statementId`, `ledgerEntryId`, `reportId`, `claimId`, and `claimSettlementId`.

### 2.7. Monetary Values and Precision

All monetary amounts are integer cents. Every calculation in the system produces whole-cent results — zero decimal places — using the round-half-up method. Where a calculation is defined in multiple steps (the staffing allocation, the annual NOI incentive, the fee tail), the intermediate rounding points named in §3 are normative: rounding at a different point, or deferring rounding to the end, produces different cents and is non-compliant. Percentages themselves are never rounded; rounding applies only after a percentage has been multiplied by an amount.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and only these three take a version field in their request bodies:

- Activating a draft agreement requires `expected_agreement_version`, carrying the `version` of the `ManagementAgreement` the client last read. If another writer has advanced the agreement's version since that read — terms amended, state changed — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), so activation never proceeds on outdated terms.
- Creating a reforecast budget is guarded by `expected_base_budget_version`, carrying the `version` of the APPROVED base `Budget` the client last read and named in `supersedes_budget_id`. When the field is supplied, a stale value means the base was amended or already superseded by another reforecast, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412); when it is supplied and matches, or when it is omitted, the create proceeds.
- Settling a claim requires `expected_claim_version`, carrying the `version` of the `Claim` the client last read. Settlement terms depend on the claim's current reserve and indemnification fields; if those changed after the client's read, the settle is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed above do not take a version field. The stale-version check is purely a comparison between the supplied value and the entity's current `version`; it does not depend on requests overlapping in time.

### 2.9. The Property Ledger and Cash Position

Each property carries a ledger of `LedgerEntry` rows and a derived **cash available** position. Cash available is the running balance of property cash on hand: ledger collections increase it and system payouts decrease it, through the guarded cash-moving transitions listed below; the balance itself is carried on the property rather than re-derived from the ledger on every read. Ledger entries are signed: charges are positive, credits negative. Six kinds of entry exist — `RENT`, `FEE`, `RECOVERY`, `CONCESSION`, `EXPENSE`, and `PAYROLL` — and only `RENT`, `FEE`, and `RECOVERY` count toward revenue, with `CONCESSION` entries reducing `RENT` revenue; `EXPENSE` and `PAYROLL` never enter revenue. Two month keys sit on every entry: `accrual_month`, the month the charge was earned or incurred, and `collected_month`, the month cash was actually collected (absent until cash arrives). These two keys drive the dual cash/accrual reporting basis described in §3.5. Entries begin in `POSTED` status and may move to `VOID`.

Three guarded transitions reduce cash available without any ledger ambiguity: statement close pays the manager its fees and payroll charge; report delivery posts the owner distribution as an `EXPENSE` entry; and claim review holds, then claim settlement releases, the claim's reserve.

### 2.10. Validation Order

When several validation rules apply to a single request, the server evaluates them in a fixed priority order and surfaces the first failure. Authentication header presence and well-formedness is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission (`ERR_FORBIDDEN_FOR_ROLE`), then left-to-right path existence (`ERR_NOT_FOUND`), then state-machine legality (`ERR_INVALID_STATE_TRANSITION`), then the business rules in their domain order: risk-allocation safety (incident-term and reserve rules), business referential guards (vendor contracts pending, open claims blocking exit), temporal windows (pricing overlap, statement period, distribution window, vendor contract window), constraint rules (override band, segregation of duties), and finally the fiscal guards (reforecast base, reserve floor, tail invoicing) with books-locked last. A caller debugging a rejection can therefore rely on the reported error being the highest-priority unmet rule, not an arbitrary one.

## 3. Business Logic & Workflows

### 3.1. Owners and Properties

The `Owner` is the owning entity on whose behalf properties are managed. A `PortfolioManager` creates an owner with a `legal_name`; the owner begins with `status` `ACTIVE` (its other states are `SUSPENDED` and `EXITED`). Each owner carries a `distribution_day_of_month` — the contractual target day of each month for owner distributions, defaulting to 10 when the field is omitted or null and constrained to the range 1 through 28 (a value outside the range is rejected with `ERR_INVALID_REQUEST`) — which governs the delivery grace window in §3.8.

A `PortfolioManager` registers a `Property` under an owner with a `name` and a `unit_count` (`unit_count` must be a non-negative integer, else `ERR_INVALID_REQUEST`). The property begins with `status` `OPEN` (its terminal state is `CLOSED`) and a `management_posture` of `UNMANAGED`. The posture field tracks where the property sits in its relationship with the manager across five values — `UNMANAGED`, `ONBOARDING`, `MANAGED`, `TRANSITIONING_OUT`, and `DISPOSED` — and is always derived by the system from the surrounding workflows rather than set directly. A property that has been listed for sale records the moment in `disposition_listed_at`, which remains absent otherwise. Properties can be listed filtered by `owner_id` and `management_posture`; residents, vendor contracts, onboarding transitions, pricing, staff, statements, ledger entries, report packages, and claims are all reachable both as nested lists under the property and as top-level filtered lists taking `property_id`.

### 3.2. The Management Agreement

The `ManagementAgreement` is the contract between owner and manager and the source of every fee parameter. A `PortfolioManager` drafts one under an owner by supplying the `property_id` it will govern, the `effective_date` and `term_end_date`, and the economic terms: `base_fee_pct` (the fraction of collected revenue charged as the base management fee), `minimum_monthly_fee_cents` (the monthly floor on that base fee), `incentive_threshold_egi_cents` (the monthly effective gross income threshold above which the first incentive tier applies), and `incentive_tier1_rate` (the fraction of EGI above the threshold paid to the manager as incentive). The referenced `property_id` must exist, `term_end_date` must be strictly after `effective_date`, and `minimum_monthly_fee_cents` and `incentive_threshold_egi_cents` must be non-negative; violations are rejected with `ERR_INVALID_REQUEST`. Three further terms carry defaults: `noi_hurdle_pct` defaults to 0.08 (the annual NOI outperformance hurdle for the annual incentive), `incentive_noi_share_pct` defaults to 0.20 (the manager's share of NOI above the hurdle), `tail_months` defaults to 3 and `tail_rate_pct` defaults to 0.50 (the tail owed when the agreement ends for convenience or disposition). The agreement begins in `DRAFT`, and its full state vocabulary is `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATION_PENDING`, `TERMINATED`, and `EXPIRED`, with `TERMINATED` and `EXPIRED` terminal.

Activation moves a `DRAFT` agreement to `ACTIVE` and is performed by a `PortfolioManager`. Two preconditions guard it, evaluated within the validation order of §2.10: the owner must be in `ACTIVE` status, else `ERR_OWNER_NOT_ACTIVE`; and the request must carry `expected_agreement_version` matching the agreement's current `version`, else `ERR_STALE_VERSION` as described in §2.8. Successful activation increments the agreement's `version` by one. Agreements are listed filtered by `owner_id`, `property_id`, and `status`.

Suspension and resumption are manager-side acts. A `PortfolioManager` may suspend an `ACTIVE` agreement — but only when no `Budget` for the property is sitting in `SUBMITTED` awaiting the owner's decision; if one is, the suspension is rejected with `ERR_PENDING_OWNER_DECISION`. Suspension moves the agreement to `SUSPENDED`, increments its `version`, and cascades down to staffing: every `StaffPosition` row for the property currently in `ACTIVE` flips to `INACTIVE`. Resuming a `SUSPENDED` agreement returns it to `ACTIVE`, increments `version` again, and performs the compensation cascade — exactly the positions that suspension pushed to `INACTIVE` return to `ACTIVE`; positions made `INACTIVE` any other way are untouched.

### 3.3. Onboarding a Property from a Prior Manager

When a property changes managers, the incoming manager must take over resident data, ledger balances, and vendor contracts in an orderly pipeline. Either a `PortfolioManager` or a `PropertyAccountant` starts an `OnboardingTransition` under the property, naming the `prior_manager_name` and the `takeover_date` — the effective handover date, which is also the cutoff for the ledger import. The transition begins in `INTAKE`, and starting it sets the property's `management_posture` to `ONBOARDING` (the normal path starts from `UNMANAGED`; starting an onboarding places no precondition on the prior posture). The onboarding state vocabulary is `INTAKE`, `DATA_VERIFIED`, `LEDGER_IMPORTED`, `VENDOR_REVIEW`, `READY`, `ACTIVATED`, and `ABORTED`, with the last two terminal. Optional opening balances — `deposits_received_cents`, `prepaid_rent_cents`, and `delinquency_cents` — may be supplied at start; each defaults to 0 and must be non-negative (a negative value is rejected with `ERR_INVALID_REQUEST`). `net_position_cents` is absent until the ledger import computes it. Onboardings are listed per property, and a top-level filtered list takes `property_id` and `status`.

Resident data comes first. A `PropertyAccountant` imports residents into the property: each `Resident` carries a `unit_label`, a `full_name`, and a `lease_end_date`, and begins with `lease_status` `ACTIVE` (its other values are `NOTICE` and `VACATED`). Once at least one resident row exists for the property, the accountant may mark resident data verified, moving the onboarding from `INTAKE` to `DATA_VERIFIED`; with no residents at all the step is rejected with `ERR_NO_RESIDENT_DATA`. Residents are listed per property filtered by `lease_status`, or top-level by `property_id`.

Ledger import comes second. From `DATA_VERIFIED`, a `PropertyAccountant` imports the prior manager's closing balances, supplying `deposits_received_cents`, `prepaid_rent_cents`, and `delinquency_cents` — each must be set and non-negative. Import computes the **onboarding net position**: `net_position_cents` is deposits received plus prepaid rent minus delinquency, in whole cents. A positive net position means the prior manager owes the property funds; a negative position means the property inherited net liabilities. Imported rows are ordered by their original posting date as of `takeover_date`, and rows posted after `takeover_date` are excluded — they belong to the new manager's books. As a side effect the import creates balancing `LedgerEntry` rows effective as of `takeover_date`: deposits and prepaid rent import as credits, delinquency as charges. Concretely, the import posts a `RECOVERY` credit of `deposits_received_cents`, a `RECOVERY` credit of `prepaid_rent_cents`, and a `RENT` charge of `delinquency_cents` (skipping any zero amount), each with `accrual_month` and `collected_month` set to the calendar month of `takeover_date`, and cash available moves by the net position — increasing by deposits plus prepaid rent and decreasing by delinquency. The onboarding advances to `LEDGER_IMPORTED`.

Vendor transition comes third, and it is a guarded aggregate step. Beginning vendor review moves the onboarding from `LEDGER_IMPORTED` to `VENDOR_REVIEW`. During review, each `VendorContract` registered against the property — created by a `PropertyAccountant` with `vendor_name`, `service_type`, `monthly_cost_cents`, `start_date`, and `end_date`, where the window must be valid (a start on or after the end is rejected with `ERR_INVALID_REQUEST`) and `monthly_cost_cents` must be non-negative — begins with `assignment_status` `PENDING` and must be resolved by a `PropertyAccountant` into exactly one of `ASSUMED` (the owner assumes the contract), `ASSIGNED_TO_MANAGER` (the manager takes it over), or `TERMINATED`, via the `resolution` input on the resolve action. Completing vendor review is blocked while any contract for the property remains `PENDING` — the attempt is rejected with `ERR_VENDOR_CONTRACTS_PENDING` — and otherwise moves the onboarding to `READY`. Vendor contracts are listed per property filtered by `assignment_status`, or top-level by `property_id`.

Activation is the final step. From `READY`, a `PortfolioManager` activates the onboarding, which requires the property's `ManagementAgreement` to be `ACTIVE` — otherwise `ERR_AGREEMENT_NOT_ACTIVE` — and on success moves the onboarding to `ACTIVATED` and the property's `management_posture` to `MANAGED`; the property is now in service and its first monthly statement may be opened. Only from `INTAKE` may a `PortfolioManager` instead abort the onboarding — an abort attempted from any later state is rejected with `ERR_INVALID_STATE_TRANSITION` — moving it to `ABORTED` and returning the property's posture to `UNMANAGED`.

### 3.4. Budgets, Reforecasts, and Owner Approval

Each fiscal year, the manager proposes a budget and the owner decides it. A `PropertyAccountant` creates a `Budget` with the `property_id`, `fiscal_year`, `kind` (`ANNUAL` or `REFORECAST`, defaulting to `ANNUAL` when omitted), and the three budgeted amounts: `operating_revenue_cents`, `operating_expense_cents`, and `capex_total_cents`. A new budget begins in `DRAFT`; its full vocabulary is `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, and `SUPERSEDED`, with the last three terminal. Budgets are listed filtered by `property_id`, `fiscal_year`, `kind`, `status`, and `supersedes_budget_id`.

A reforecast is a create-with-supersede: its `supersedes_budget_id` must reference an `APPROVED` budget for the same property and fiscal year (a missing reference, or one that fails these checks, is rejected with `ERR_REFORECAST_REQUIRES_APPROVED_BASE`), and its create may carry `expected_base_budget_version` matching that base budget's current `version`, per the OCC rule in §2.8. The supersede is legitimate — a newer reforecast replaces the prior one — but when the client supplies the expected version it must be the version it actually read; a stale supplied version is rejected with `ERR_STALE_VERSION`, while an omitted one skips the check.

Submission is the accountant's act and approval is the owner's, and the two must never be the same hand. From `DRAFT`, a `PropertyAccountant` submits the budget, which requires the property's `management_posture` to be `MANAGED` (otherwise `ERR_INVALID_STATE_TRANSITION`) and, for a reforecast, that `supersedes_budget_id` reference an `APPROVED` budget for the same property and fiscal year (otherwise `ERR_REFORECAST_REQUIRES_APPROVED_BASE`). The budget moves to `SUBMITTED`, and the submitting user's id is recorded on the budget as `_submitted_by`. An `OwnerRep` then decides it. Approval moves the budget to `APPROVED`, increments its `version`, and records the deciding user in `decided_by`; when the approved budget is a reforecast, the base budget named in `supersedes_budget_id` flips to `SUPERSEDED` in the same request. Rejection moves the budget to `REJECTED` and likewise records `decided_by`. Both decisions enforce segregation of duties by comparing the acting user's `X-User-ID` against `_submitted_by` directly: if the two strings are equal the decision is rejected with `ERR_SOD_VIOLATION`. A budget sitting in `SUBMITTED` has one further systemic effect: it blocks suspension of the property's agreement (§3.2), surfacing as `ERR_PENDING_OWNER_DECISION`.

### 3.5. Revenue Management and Owner Override

Pricing flows from the manager's revenue-management model to the owner for oversight. A `RevenueAnalyst` creates a `PricingRecommendation` under a property, naming the `unit_label` it applies to, the `recommended_rent_cents`, and a half-open effective window from `effective_start_date` to `effective_end_date` (the end exclusive). The recommendation begins in `PROPOSED`; its vocabulary is `PROPOSED`, `PUBLISHED`, `OWNER_OVERRIDDEN`, and `WITHDRAWN`, with the last three terminal. Its `final_rent_cents` — the rent that actually takes effect — is a computed field, absent of meaning until publication (it is null until then, as is `override_rent_cents`). `recommended_rent_cents` must be non-negative. Recommendations are listed per property filtered by `unit_label` and `status`, or top-level by `property_id`.

Publishing is the analyst's act and is checked against the unit's existing price windows. From `PROPOSED`, publication requires the window to be well-formed — the start strictly before the end, otherwise `ERR_INVALID_REQUEST` — and that no other `PUBLISHED` recommendation for the same property and `unit_label` has an overlapping window; windows are half-open, so a window that abuts another exactly is not an overlap, but any true overlap is rejected with `ERR_PRICING_WINDOW_OVERLAP`. On publish, `final_rent_cents` is set equal to `recommended_rent_cents` and the recommendation becomes `PUBLISHED`.

The owner retains override rights over any published price. An `OwnerRep` may override a `PUBLISHED` recommendation by supplying `override_rent_cents`, which must be non-negative; the override must stay within a band of plus or minus ten percent of `recommended_rent_cents` (the constant `MAX_OVERRIDE_BAND_PCT` is 0.10), inclusive at the boundary — a deviation of exactly ten percent is permitted, one cent beyond is rejected with `ERR_OVERRIDE_BAND_EXCEEDED`. A successful override moves the recommendation to `OWNER_OVERRIDDEN` and sets `final_rent_cents` to the override value. Withdrawal is the analyst's escape: a `PROPOSED` recommendation may always be withdrawn, and a `PUBLISHED` one may be withdrawn only while the logical clock is still before `effective_start_date` — a live price window cannot be withdrawn, and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. Withdrawal lands in `WITHDRAWN` from either origin state.

### 3.6. The Monthly Cycle: Ledger, Statement Close, and Fee Computation

Operations accumulate in the property ledger. A `PropertyAccountant` posts a `LedgerEntry` under the property with a `kind` (`RENT`, `FEE`, `RECOVERY`, `CONCESSION`, `EXPENSE`, or `PAYROLL`), a signed `amount_cents` (charges positive, credits negative; malformed bodies such as negative amounts on charge kinds, missing required fields, or invalid enum values are rejected with `ERR_INVALID_REQUEST` — the charge kinds for this rule are `RENT`, `FEE`, `RECOVERY`, `EXPENSE`, and `PAYROLL`, whose amounts must be non-negative, while `CONCESSION` entries may carry either sign), an `accrual_month` in `YYYY-MM` format, and optionally a `collected_month` and a `resident_id` for resident-linked entries (absent for non-resident entries; when supplied, `resident_id` must reference a `Resident` of the same property, else `ERR_INVALID_REQUEST`). Posting creates the entry in `POSTED` status and updates cash available immediately: `RENT`, `FEE`, `RECOVERY`, and `CONCESSION` entries adjust cash by their signed `amount_cents` when `collected_month` is set, and `EXPENSE` and `PAYROLL` entries always reduce cash by `amount_cents` at posting, with or without a `collected_month`. Entries are listed per property or top-level, filterable by `resident_id`, `kind`, `status`, `accrual_month`, and `collected_month`.

Once the property is managed, a `PropertyAccountant` opens a `MonthlyStatement` for a `period_month` (format `YYYY-MM`), declaring the `basis` — `CASH` or `ACCRUAL` — that the statement's fee math will use. Opening requires the property's `management_posture` to be `MANAGED` or `TRANSITIONING_OUT` (otherwise `ERR_INVALID_STATE_TRANSITION`); the API does not enforce uniqueness of `period_month` per property. The statement begins `OPEN`; its vocabulary is `OPEN`, `CLOSED`, and `RESTATED`, with `CLOSED` terminal for normal purposes (restatement revisits it, below). While a statement is open, reading it previews the computations that close will freeze, recomputed live from current ledger and staffing state on each read.

Closing is the month's fiscal boundary. A `PropertyAccountant` may close an `OPEN` statement only when the property's `management_posture` is `MANAGED` or `TRANSITIONING_OUT` (otherwise `ERR_INVALID_STATE_TRANSITION`) and only once the logical clock has reached the first day of the month following `period_month` — a statement may never close before its month has ended, and an early close is rejected with `ERR_STATEMENT_PERIOD_OPEN`. Close runs three computations in sequence and freezes the results on the statement.

First, revenue and the base fee. `collected_revenue_cents` is the sum of `POSTED` ledger amounts of kinds `RENT`, `FEE`, and `RECOVERY` for the month, with `CONCESSION` entries reducing `RENT` revenue and `EXPENSE` and `PAYROLL` excluded — and the month an entry counts in depends on the basis. On the `CASH` basis, a row counts when its `collected_month` equals `period_month`: revenue is counted in the month cash is collected, so a charge accrued in month M but collected in month M+1 counts in M+1 only. On the `ACCRUAL` basis, a row counts when its `accrual_month` equals `period_month` regardless of collection. The identical ledger therefore produces a different fee whenever collection lags accrual. The base fee is then `base_fee_cents`, the greater of the agreement's `minimum_monthly_fee_cents` and the agreement's `base_fee_pct` multiplied by that revenue, the multiplication rounded half-up to whole cents exactly once (the percentage itself is never rounded). Wherever the fee math references "the agreement", it uses the most recently created `ManagementAgreement` for the property regardless of its status; when the property has no agreement at all, the base fee and the incentive fee are both zero.

Second, the incentive fee. Using the same basis revenue as effective gross income, when EGI is strictly greater than the agreement's `incentive_threshold_egi_cents`, `incentive_fee_cents` is the agreement's `incentive_tier1_rate` multiplied by the excess of EGI over the threshold, rounded half-up to whole cents; otherwise the incentive is zero. The boundary is exact: EGI equal to the threshold yields zero — strictly greater triggers the tier, greater-than-or-equal does not.

Third, the staffing payroll charge, computed by the **staffing cost allocation**. For each `StaffPosition` of the property in `ACTIVE` status — positions are created by a `PortfolioManager` with a `role_title`, a fully burdened `hourly_cost_cents`, `scheduled_hours_per_week`, and a `shared_region_code`, beginning `ACTIVE` with `INACTIVE` as the other state — the direct cost is its scheduled weekly hours multiplied by 4 weeks per month multiplied by its hourly cost; `hourly_cost_cents` and `scheduled_hours_per_week` must be non-negative integers. The property's `direct_total` is the sum over its own active positions; when the property has no active positions (or a zero direct total), the payroll charge is zero. A regional pool is then formed: the direct costs of every `ACTIVE` position across all properties sharing the same `shared_region_code` are summed — when the property's active positions carry several region codes, the pool covers every position whose code is any of them — the pool is charged a regional overhead of 20 percent, and the property's share of that overhead is the pool times 0.20 times the ratio of the property's direct total to the region's direct total, rounded half-up to whole cents — this regional allocation is rounded first, and that rounding point is normative. A load of 32 percent is then applied to the sum of the property's direct total and its regional share, and that loaded amount is rounded half-up to whole cents as a second, separately pinned rounding. The statement's `payroll_charge_cents` is the property's direct total plus its regional share plus the loaded amount. `INACTIVE` positions are excluded from both the direct and the regional pool. Summing everything and rounding once at the end produces different cents and is non-compliant.

The statement's `management_fee_total_cents` is its `base_fee_cents` plus its `incentive_fee_cents`. On close, the computed fields freeze, and two cascades fire: first the property's cash available is reduced by the management fee total plus the payroll charge (the manager is paid), and then any `DRAFT` `OwnerReportPackage` for the same property and period becomes `GENERATED` with its distribution computed from the already-reduced cash as described in §3.8.

Restatement handles corrections after the fact. From `CLOSED`, a `PropertyAccountant` may restate a statement only while the period's books are not owner-locked: once any `OwnerReportPackage` for the same property and period has been `DELIVERED`, restatement is rejected with `ERR_BOOKS_LOCKED`. A permitted restatement leaves the statement in `CLOSED` but recomputes every computed field from the current ledger state — prior computed values are superseded — and increments the statement's `version` by one. Restatement recomputes the statement only: it fires no cash cascade and does not re-run generation — report packages, including any already `GENERATED`, keep the `distribution_amount_cents` computed when they were generated. Statements are listed per property filtered by `period_month` and `status`, or top-level by `property_id`.

One annual settlement rides on the monthly cycle. When the epoch advance (§2.4) closes a December period — that is, the advance whose new epoch month is January, so the month that just ended is December — the **annual NOI incentive** runs for every property: budget NOI is the `APPROVED` `ANNUAL` budget's `operating_revenue_cents` minus its `operating_expense_cents` (only the currently approved budget counts; superseded bases are excluded, and when several qualify the most recently created one is used), and actual NOI is the sum of `collected_revenue_cents` across the fiscal year's twelve `CLOSED` statements for the property minus the year's `POSTED` `EXPENSE` ledger amounts, keyed by `accrual_month` within the fiscal year — aggregating cash-basis or accrual-basis revenue according to whichever basis the majority of the year's statements used (summing only the majority-basis statements' revenue; a six-six tie counts as `CASH`), so identical ledgers yield a different annual incentive whenever the basis mix differs. When the property has no agreement, when fewer than twelve `CLOSED` statements exist for the fiscal year, or when no `APPROVED` `ANNUAL` budget exists for that year, the annual incentive is zero. The hurdle base — budget NOI multiplied by one plus the agreement's `noi_hurdle_pct` — is computed and rounded half-up to whole cents first; if actual NOI exceeds that rounded hurdle, the annual incentive is the agreement's `incentive_noi_share_pct` applied to the excess of actual NOI over the rounded hurdle, rounded half-up to whole cents; otherwise it is zero. The evaluation order — round the hurdle base, then subtract, then apply the share and round — is normative; sharing-then-subtracting produces different cents and is non-compliant. When the computed annual incentive is greater than zero it is paid to the manager out of property cash on that advance: the property's cash available is reduced by the incentive amount and a `POSTED` `LedgerEntry` of kind `EXPENSE` in exactly that amount is recorded against the property, with `accrual_month` set to the December period that closed, `collected_month` set to the new epoch month, and no `resident_id`; the amount is observable through the property's cash position and this ledger entry, not on the advance response.

### 3.7. Termination, Disposition, and the Fee Tail

Endings are owner-initiated and manager-completed, and the contract's tail provisions follow the manager out the door. An `OwnerRep` initiates termination of an `ACTIVE` agreement by supplying a `terminated_reason` — one of `CONVENIENCE`, `CAUSE`, `DISPOSITION`, or `EXPIRY`; a missing reason is rejected with `ERR_INVALID_REQUEST`. Initiation requires the property's `management_posture` to be `MANAGED` (otherwise `ERR_INVALID_STATE_TRANSITION`) and moves the agreement to `TERMINATION_PENDING` while the property's posture becomes `TRANSITIONING_OUT`. When the reason is `CONVENIENCE` or `DISPOSITION`, the **fee tail** is computed at this moment and stored in `termination_fee_tail_cents`: the system looks back over the six most recent `CLOSED` monthly statements for the property ordered by `period_month` descending (averaging over however many exist when fewer than six are available, and producing a tail of zero when none exist), takes the mean of their `base_fee_cents` rounded half-up to whole cents, and multiplies that average by the agreement's `tail_rate_pct` and its `tail_months`, rounding half-up to whole cents. On `CAUSE` or `EXPIRY` the tail is zero regardless of the formula.

Completing the termination is the manager's final act, gated on every loose end. A `PortfolioManager` may complete termination of a `TERMINATION_PENDING` agreement only when three conditions hold: every `OnboardingTransition` obligation for the property is in a terminal state (`ACTIVATED` or `ABORTED`) — a non-terminal onboarding blocks completion with `ERR_INVALID_STATE_TRANSITION`; no `Claim` for the property is in `OPEN` or `UNDER_REVIEW` — open claims block the exit with `ERR_OPEN_CLAIMS_BLOCK_EXIT`; and the tail has been invoiced — either `termination_fee_tail_cents` is zero, or a `POSTED` ledger entry of kind `EXPENSE` in exactly that amount exists for the property. On completion the agreement becomes `TERMINATED`, every `VendorContract` in `ASSIGNED_TO_MANAGER` for the property cascades to `TERMINATED`, and the property's posture settles to `UNMANAGED` — or to `DISPOSED` when the reason was `DISPOSITION` and the disposition itself has completed (the property already `CLOSED`).

Expiry is the clock-driven ending: when the logical clock reaches an `ACTIVE` agreement's `term_end_date` during month advance — that is, the post-advance clock is on or after `term_end_date` — the agreement moves to `EXPIRED`, the property's posture returns to `UNMANAGED`, and no fee tail accrues.

Disposition is the sale path, and it interlocks with termination. An `OwnerRep` lists a property for disposition only while its posture is `MANAGED` (otherwise `ERR_INVALID_STATE_TRANSITION`); listing stamps `disposition_listed_at` with the current logical clock time and makes `LENDER` report packages due monthly until the sale completes (§3.8). Completing the disposition requires `disposition_listed_at` to be set and the property's agreement to be sitting in `TERMINATION_PENDING` with `terminated_reason` `DISPOSITION` — both failures surface as `ERR_INVALID_STATE_TRANSITION`. Completion closes the property (`status` `CLOSED`, posture `DISPOSED`) and immediately moves the agreement from `TERMINATION_PENDING` to `TERMINATED` — a shortcut past the normal completion gates, though the tail is still invoiced when the computed fee tail is greater than zero — and cascades every `ASSIGNED_TO_MANAGER` vendor contract for the property to `TERMINATED`, as on normal completion.

### 3.8. Owner Reporting, Distributions, and Lender Packages

Reporting is the owner's window into the books. A `PropertyAccountant` creates an `OwnerReportPackage` shell under a property for a `period_month` with a `package_type` of `MONTHLY_OWNER` or `LENDER`; the shell begins in `DRAFT`, and the package vocabulary is `DRAFT`, `GENERATED`, and the terminal `DELIVERED`. Packages are listed per property filtered by `period_month`, `package_type`, and `status`, or top-level by `property_id`.

Generation ties the package to its closed statement. A package becomes `GENERATED` either as a cascade when the statement for the same property and period closes (§3.6) or explicitly by a `PropertyAccountant`, and in both cases the precondition is that the statement is `CLOSED` (otherwise `ERR_INVALID_STATE_TRANSITION`). Generation computes `distribution_amount_cents` for `MONTHLY_OWNER` packages via the **owner distribution** waterfall; for `LENDER` packages the distribution is zero.

The distribution waterfall fills four buckets in a pinned order, and the owner receives the remainder. First the reserve floor: 20000000 cents must remain in property cash. Second the lender holdback: when any `LENDER` package exists for the period — in any status — a further 15000000 cents is held back, and zero otherwise. Third, claim holds: the sum of `reserved_amount_cents` over the property's claims in `OPEN` or `UNDER_REVIEW`. The distribution is then cash available minus the floor, minus the holdback, minus the claim holds — never less than zero, so the floor can never be breached by a distribution. Cash available itself is the running balance defined in §2.9; the reserve floor, the lender holdback, and the claim holds below each subtract exactly once from that balance, so a standing claim hold reduces the distribution by exactly `reserved_amount_cents`.

Delivery is timed by contract. A `PropertyAccountant` delivers a `GENERATED` package; for `MONTHLY_OWNER` packages, the logical clock's day of month must be no later than the owner's `distribution_day_of_month` plus a five-day grace — the check compares only the day-of-month component — delivery inside the grace window is permitted, delivery past it is rejected with `ERR_DISTRIBUTION_WINDOW_MISSED`. Delivering a `MONTHLY_OWNER` package posts the distribution: the property's cash available is reduced by `distribution_amount_cents` and an owner-distribution `LedgerEntry` of kind `EXPENSE` is recorded with `accrual_month` and `collected_month` both set to the package's `period_month` and no `resident_id`; when the distribution is zero no entry is posted and cash is unchanged. For `LENDER` packages on a property with `disposition_listed_at` set, delivery is mandatory by month-end; the obligation is validated at month advance, and an undelivered lender package at that boundary raises `ERR_LENDER_REPORT_OVERDUE`. Delivery also locks the books: once any package for a property and period is `DELIVERED`, restatement of that period's statement is blocked (§3.6).

### 3.9. Claims, Risk Allocation, and Settlement

Resident incidents and employment claims are filed against the property and worked under the agreement's risk allocation. A `RiskOfficer` files a `Claim` with a `claim_type` (`RESIDENT_INCIDENT` or `EMPLOYMENT`), a `reserved_amount_cents` loss reserve held against property funds, an `indemnified_by` allocation (`OWNER`, `MANAGER`, or `SHARED`), and an `incident_date`. The claim begins `OPEN`; its vocabulary is `OPEN`, `UNDER_REVIEW`, `SETTLED`, and the terminal `CLOSED`. `reserved_amount_cents` must be non-negative. Claims are listed per property filtered by `claim_type` and `status`, or top-level by `property_id`.

Beginning review moves the claim from `OPEN` to `UNDER_REVIEW` and places a contingent hold: the property's cash available is reduced by `reserved_amount_cents` for as long as the reserve stands. Settlement is the risk officer's OCC-guarded act on a claim in `UNDER_REVIEW` (a settle attempted from any other state is rejected with `ERR_INVALID_STATE_TRANSITION`): the settle request carries the total `amount_cents` — which must be non-negative — and the `expected_claim_version` of §2.8, and two preconditions apply — when `indemnified_by` is `MANAGER`, the `incident_date` must fall within the agreement's term, from `effective_date` through `term_end_date` inclusive (the manager indemnifies only incidents inside the term; an out-of-term incident — or a property with no agreement at all — is rejected with `ERR_INCIDENT_OUTSIDE_TERM`), and the expected version must match the claim's current `version` (else `ERR_STALE_VERSION`). Settlement moves the claim to `SETTLED`, increments its `version`, creates the claim's single `ClaimSettlement` row, releases the reserve hold, and deducts the owner's share from property cash.

The settlement split follows the indemnification field, and the two shares always sum to the settlement amount exactly — the owner absorbs any rounding remainder, so there is never drift. When `indemnified_by` is `MANAGER`, the manager's share is the settlement amount capped at 100000000 cents (the manager indemnity cap): the lesser of `amount_cents` and the cap. When it is `OWNER`, the manager's share is zero. When it is `SHARED`, the manager's share is the settlement amount multiplied by 0.25, rounded half-up to whole cents. In all three branches, `owner_share_cents` is the amount minus `manager_share_cents`. The settlement row — carrying `claim_id`, `amount_cents`, `manager_share_cents`, and `owner_share_cents` — is reachable as a list under the claim (zero or one rows) and through top-level get and filtered list by `claim_id`.

Closing finishes the lifecycle. A `SETTLED` claim may be closed unconditionally. An `OPEN` claim may be closed directly only when no reserve is outstanding — `reserved_amount_cents` must be zero, otherwise the close is rejected with `ERR_RESERVE_OUTSTANDING`. An `UNDER_REVIEW` claim cannot be closed at all — the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`; the reserve it holds must first be released through settlement. Because open claims block termination completion (§3.7), the risk and exit workflows interlock: a property cannot leave management while any claim still sits `OPEN` or `UNDER_REVIEW`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions — return `200 OK`. Request and response bodies for each operation are defined by the workflows in §3; the table below is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mgmt/_clock/set_current_utc` | Set the logical clock (default 2026-09-01T00:00:00Z; no automatic month roll) | PortfolioManager |
| POST | `/mgmt/advance_month` | Advance the operating epoch by one month (expiry, annual NOI incentive, lender overdue check) | PortfolioManager |
| POST | `/mgmt/owners` | Create an Owner | PortfolioManager |
| GET | `/mgmt/owners/{ownerId}` | Get an Owner | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| GET | `/mgmt/owners` | List Owners (filterable by status) | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| POST | `/mgmt/owners/{ownerId}/properties` | Create a Property under an Owner | PortfolioManager |
| GET | `/mgmt/properties/{propertyId}` | Get a Property | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| GET | `/mgmt/properties` | List Properties (filterable by owner_id, management_posture) | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| POST | `/mgmt/properties/{propertyId}/list_for_disposition` | Mark a managed property listed for sale | OwnerRep |
| POST | `/mgmt/properties/{propertyId}/complete_disposition` | Complete a property disposition (sale closes) | OwnerRep |
| POST | `/mgmt/owners/{ownerId}/agreements` | Create a ManagementAgreement (DRAFT) | PortfolioManager |
| GET | `/mgmt/agreements/{agreementId}` | Get a ManagementAgreement | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| GET | `/mgmt/agreements` | List ManagementAgreements (filterable by owner_id, property_id, status) | PortfolioManager, PropertyAccountant, OwnerRep, RevenueAnalyst, RiskOfficer |
| POST | `/mgmt/agreements/{agreementId}/activate` | Activate a DRAFT agreement (OCC-guarded) | PortfolioManager |
| POST | `/mgmt/agreements/{agreementId}/suspend` | Suspend an ACTIVE agreement | PortfolioManager |
| POST | `/mgmt/agreements/{agreementId}/resume` | Resume a SUSPENDED agreement | PortfolioManager |
| POST | `/mgmt/agreements/{agreementId}/terminate` | Owner initiates termination (reason required) | OwnerRep |
| POST | `/mgmt/agreements/{agreementId}/complete_termination` | Complete termination after obligations and tail invoice settle | PortfolioManager |
| POST | `/mgmt/properties/{propertyId}/onboardings` | Start onboarding a property from a prior manager | PortfolioManager, PropertyAccountant |
| GET | `/mgmt/onboardings/{onboardingId}` | Get an OnboardingTransition | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/properties/{propertyId}/onboardings` | List onboarding transitions for a property | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/onboardings` | List OnboardingTransitions (filterable by property_id, status) | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| POST | `/mgmt/onboardings/{onboardingId}/verify_resident_data` | Mark resident data verified | PropertyAccountant |
| POST | `/mgmt/onboardings/{onboardingId}/import_ledger` | Import prior-manager ledger balances | PropertyAccountant |
| POST | `/mgmt/onboardings/{onboardingId}/begin_vendor_review` | Begin vendor contract transition review | PropertyAccountant |
| POST | `/mgmt/onboardings/{onboardingId}/complete_vendor_review` | Complete vendor review (all contracts resolved) | PropertyAccountant |
| POST | `/mgmt/onboardings/{onboardingId}/activate` | Activate onboarding — property enters management | PortfolioManager |
| POST | `/mgmt/onboardings/{onboardingId}/abort` | Abort onboarding | PortfolioManager |
| POST | `/mgmt/properties/{propertyId}/residents` | Create/import a Resident | PropertyAccountant |
| GET | `/mgmt/residents/{residentId}` | Get a Resident | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/properties/{propertyId}/residents` | List residents of a property | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/residents` | List Residents (filterable by property_id, lease_status) | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| POST | `/mgmt/properties/{propertyId}/vendor-contracts` | Register a vendor contract (inherited or new) | PropertyAccountant |
| GET | `/mgmt/vendor-contracts/{vendorContractId}` | Get a VendorContract | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/properties/{propertyId}/vendor-contracts` | List vendor contracts for a property | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/vendor-contracts` | List VendorContracts (filterable by property_id, assignment_status) | PortfolioManager, PropertyAccountant, OwnerRep |
| POST | `/mgmt/vendor-contracts/{vendorContractId}/resolve` | Resolve a PENDING contract: assume, assign to manager, or terminate | PropertyAccountant |
| POST | `/mgmt/budgets` | Create a Budget (ANNUAL or REFORECAST; reforecast is OCC-guarded create-with-supersede) | PropertyAccountant |
| GET | `/mgmt/budgets/{budgetId}` | Get a Budget | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/budgets` | List Budgets (filterable by property_id, fiscal_year, kind, status, supersedes_budget_id) | PortfolioManager, PropertyAccountant, OwnerRep |
| POST | `/mgmt/budgets/{budgetId}/submit` | Submit a DRAFT budget for owner approval | PropertyAccountant |
| POST | `/mgmt/budgets/{budgetId}/approve` | Owner approves a SUBMITTED budget (SoD enforced) | OwnerRep |
| POST | `/mgmt/budgets/{budgetId}/reject` | Owner rejects a SUBMITTED budget (SoD enforced) | OwnerRep |
| POST | `/mgmt/properties/{propertyId}/pricing` | Create a pricing recommendation | RevenueAnalyst |
| GET | `/mgmt/pricing/{pricingId}` | Get a PricingRecommendation | PortfolioManager, RevenueAnalyst, OwnerRep, PropertyAccountant |
| GET | `/mgmt/properties/{propertyId}/pricing` | List pricing recommendations for a property | PortfolioManager, RevenueAnalyst, OwnerRep, PropertyAccountant |
| GET | `/mgmt/pricing` | List PricingRecommendations (filterable by property_id, unit_label, status) | PortfolioManager, RevenueAnalyst, OwnerRep, PropertyAccountant |
| POST | `/mgmt/pricing/{pricingId}/publish` | Publish a recommendation (overlap check per property+unit) | RevenueAnalyst |
| POST | `/mgmt/pricing/{pricingId}/override` | Owner overrides a published recommendation within band | OwnerRep |
| POST | `/mgmt/pricing/{pricingId}/withdraw` | Withdraw a recommendation (live windows cannot be withdrawn) | RevenueAnalyst |
| POST | `/mgmt/properties/{propertyId}/staff` | Add a staff position charged to the property | PortfolioManager |
| GET | `/mgmt/staff/{staffPositionId}` | Get a StaffPosition | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/properties/{propertyId}/staff` | List staff positions for a property | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/staff` | List StaffPositions (filterable by property_id, status) | PortfolioManager, PropertyAccountant, OwnerRep |
| POST | `/mgmt/properties/{propertyId}/ledger-entries` | Post a ledger entry (charge/credit/expense) | PropertyAccountant |
| GET | `/mgmt/ledger-entries/{ledgerEntryId}` | Get a LedgerEntry | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/properties/{propertyId}/ledger-entries` | List ledger entries for a property (filterable) | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| GET | `/mgmt/ledger-entries` | List LedgerEntries (filterable by property_id, resident_id, kind, status, accrual_month, collected_month) | PortfolioManager, PropertyAccountant, OwnerRep, RiskOfficer |
| POST | `/mgmt/properties/{propertyId}/statements` | Open a monthly statement for a managed property | PropertyAccountant |
| GET | `/mgmt/statements/{statementId}` | Get a MonthlyStatement (preview computations while OPEN) | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/properties/{propertyId}/statements` | List statements for a property | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/statements` | List MonthlyStatements (filterable by property_id, period_month, status) | PortfolioManager, PropertyAccountant, OwnerRep |
| POST | `/mgmt/statements/{statementId}/close` | Close a statement: freeze fees, payroll charge, cascade to reports | PropertyAccountant |
| POST | `/mgmt/statements/{statementId}/restate` | Restate a CLOSED statement (blocked once reports delivered) | PropertyAccountant |
| POST | `/mgmt/properties/{propertyId}/reports` | Create a report package shell (DRAFT) | PropertyAccountant |
| GET | `/mgmt/reports/{reportId}` | Get an OwnerReportPackage | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/properties/{propertyId}/reports` | List report packages for a property | PortfolioManager, PropertyAccountant, OwnerRep |
| GET | `/mgmt/reports` | List OwnerReportPackages (filterable by property_id, period_month, package_type, status) | PortfolioManager, PropertyAccountant, OwnerRep |
| POST | `/mgmt/reports/{reportId}/generate` | Generate a report from its closed statement | PropertyAccountant |
| POST | `/mgmt/reports/{reportId}/deliver` | Deliver a generated report (distribution timing enforced) | PropertyAccountant |
| POST | `/mgmt/properties/{propertyId}/claims` | File a claim (resident incident or employment) | RiskOfficer |
| GET | `/mgmt/claims/{claimId}` | Get a Claim | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |
| GET | `/mgmt/properties/{propertyId}/claims` | List claims for a property | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |
| GET | `/mgmt/claims` | List Claims (filterable by property_id, claim_type, status) | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |
| POST | `/mgmt/claims/{claimId}/begin_review` | Begin claim review (reserve held) | RiskOfficer |
| POST | `/mgmt/claims/{claimId}/settle` | Settle a claim (OCC-guarded; risk allocation computed) | RiskOfficer |
| POST | `/mgmt/claims/{claimId}/close` | Close a settled (or zero-reserve open) claim | RiskOfficer |
| GET | `/mgmt/claims/{claimId}/settlements` | List settlement rows for a claim (0 or 1) | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |
| GET | `/mgmt/claim-settlements/{claimSettlementId}` | Get a ClaimSettlement by id | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |
| GET | `/mgmt/claim-settlements` | List ClaimSettlements (filterable by claim_id) | PortfolioManager, RiskOfficer, OwnerRep, PropertyAccountant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OWNER_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PENDING_OWNER_DECISION` | 409 |
| `ERR_NO_RESIDENT_DATA` | 409 |
| `ERR_VENDOR_CONTRACTS_PENDING` | 409 |
| `ERR_OPEN_CLAIMS_BLOCK_EXIT` | 409 |
| `ERR_REFORECAST_REQUIRES_APPROVED_BASE` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_PRICING_WINDOW_OVERLAP` | 409 |
| `ERR_OVERRIDE_BAND_EXCEEDED` | 409 |
| `ERR_STATEMENT_PERIOD_OPEN` | 409 |
| `ERR_BOOKS_LOCKED` | 409 |
| `ERR_DISTRIBUTION_WINDOW_MISSED` | 409 |
| `ERR_LENDER_REPORT_OVERDUE` | 409 |
| `ERR_INCIDENT_OUTSIDE_TERM` | 409 |
| `ERR_RESERVE_OUTSTANDING` | 409 |
