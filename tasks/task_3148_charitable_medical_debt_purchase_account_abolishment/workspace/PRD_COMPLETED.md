# Charitable Medical Debt Abolishment API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Charitable Medical Debt Abolishment API, the operational backbone of a nonprofit program that purchases bundled medical debt portfolios from hospitals, physician groups, and debt buyers — and then permanently abolishes the underlying accounts rather than collecting on them. Every account in a purchased portfolio is screened against income-based and insolvency-based eligibility criteria; qualifying accounts are bought for a small fraction of face value, forgiven outright, and their owners are notified by letter without ever having applied for relief. Where an account was previously reported to a credit bureau, the system drives a deletion-request lifecycle with the bureau; where relief could constitute taxable cancellation-of-debt income, the system tracks assessment and filing outcomes for each relieved amount.

The platform coordinates several distinct operational constituencies under one audit trail. Portfolio analysts source and import account-level data files. Eligibility officers define screening policies and resolve accounts that automated scoring cannot decide. Contract managers draft and execute purchase contracts carrying hard charitable covenants, while finance officers — deliberately separated from contract execution by a segregation-of-duties rule — settle purchases, receive donor funds, and commit abolishment batches whose funding is drawn from donor campaigns through a deterministic earmark-aware waterfall. Donor-relations staff run campaigns, manage hospital partnerships that pair abolishment with financial-assistance-policy improvement milestones, and shepherd notification letters through a bounded bounce-and-requeue cycle. Compliance auditors own the credit-bureau deletion lifecycle and the tax-relief assessment pipeline, and platform administrators operate the source-organization registry, the logical clock, and impact reporting.

Two design commitments shape the entire API. First, every money movement is auditable and reversible only through explicit compensating actions: donation refunds, batch uncommit, batch reversal, and contract termination each undo a prior commitment without deleting history. Second, household relief is measured twice — once per account and once per distinct household — so impact reporting can speak honestly to both the volume of debt abolished and the number of families touched. All amounts throughout the system are integer cents; all timestamps come from a server-side logical clock rather than wall-clock time, so that due dates, reporting periods, and policy windows are reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or presenting a role name the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly eight roles:

- `PlatformAdmin` — platform operator; owns the source-organization registry, the logical clock, and (jointly with the compliance function) impact reports.
- `PortfolioAnalyst` — sources portfolios and imports account-level data files.
- `EligibilityOfficer` — owns eligibility policies, screening runs, and resolution of accounts awaiting manual review.
- `ContractManager` — drafts and executes purchase contracts; is barred from settling them.
- `FinanceOfficer` — moves money: settles contracts, receives and refunds donations, and commits, uncommits, finalizes, and reverses abolishment batches.
- `DonorRelationsOfficer` — runs donor campaigns, hospital partnerships, partnership milestones, and beneficiary notification letters.
- `ComplianceAuditor` — owns the credit-bureau deletion lifecycle and tax-relief assessment and filing.
- `HospitalPartner` — a partner hospital's contact, permitted to mark its own partnership's milestones met.

For every role except `HospitalPartner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `executed_by` on a `PurchaseContract` when a `ContractManager` executes, or as `settled_by` when a `FinanceOfficer` settles — but never compares it to any entity's `id`. When `X-User-Role` is `HospitalPartner`, `X-User-ID` is the `id` of the acting `SourceOrganization`; ownership checks on any resource that references a `SourceOrganization` — concretely, the milestone mark-met operation — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). List endpoints also accept the filter parameters named against them in §4 narratives — most commonly a `status` filter matching the resource's lifecycle or state field, alongside resource-specific filters such as `portfolio_id`, `policy_id`, `account_id`, `batch_id`, `source_org_id`, `campaign_id`, `partnership_id`, `eligibility_status`, `lifecycle_status`, `bureau_status`, `abolished_batch_id`, `org_type`, `state_code`, `earmark_type`, `earmark_source_org_id`, `scope`, and `scope_source_org_id`. Concretely, each list endpoint supports exactly: source organizations — `org_type`, `state_code`, `status`; policies — `state_code`, `status`; portfolios — `source_org_id`, `status`; accounts — `portfolio_id`, `eligibility_status`, `lifecycle_status`, `bureau_status`, `abolished_batch_id`; screening runs — `portfolio_id`, `policy_id`, `status`; contracts — `portfolio_id`, `status`; campaigns — `earmark_type`, `earmark_source_org_id`, `status`; donations — `campaign_id`, `status`; batches — `portfolio_id`, `status`; letters — `account_id`, `batch_id`, `status`; deletion requests — `account_id`, `batch_id`, `status`; tax records — `account_id`, `status`; partnerships — `source_org_id`, `status`; milestones — `partnership_id`, `status`; reports — `scope`, `scope_source_org_id`, `status`. Every filter is an exact-match equality on the named field. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order (earliest created first). Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. The Logical Clock

The server maintains a logical clock that stamps every system-generated timestamp in the domain — `executed_at` on a screening run, `abolished_at` on an account, `sent_at` on a letter, and the due-date comparison for partnership milestones. At server startup, before any call, the logical clock reads exactly `2026-09-01T00:00:00.000Z`; it must never fall back to wall-clock time. A `PlatformAdmin` may set the clock to a supplied instant via an admin-only test-driving capability that accepts a `to_iso8601` value — any ISO 8601 timestamp string, with or without fractional seconds, and with any numeric UTC offset in place of `Z` (the value is normalized to UTC) — and returns the resulting `current_utc`; the supplied instant is not constrained to the future. Every subsequent server-stamped timestamp uses the new clock reading.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` — an integer starting at 1 that increments on every mutation of the resource.

Every entity in this domain — `SourceOrganization`, `EligibilityPolicy`, `Portfolio`, `DebtAccount`, `ScreeningRun`, `PurchaseContract`, `DonorCampaign`, `Donation`, `AbolishmentBatch`, `NotificationLetter`, `CreditDeletionRequest`, `TaxReliefRecord`, `HospitalPartnership`, `PartnershipMilestone`, and `ImpactReport` — carries the full set. Any cascade that mutates a resource, including automatic recomputation of derived totals, refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Monetary Precision and Rounding

All money in the system is represented as integer cents. Wherever a calculation introduces a fractional result — the eligibility income cap, the tiered portfolio quote, and the per-donation processing fee — the value is rounded half-up to the nearest cent at exactly the point the governing calculation specifies, and no earlier. The financial-assistance-policy score is the one non-monetary rounded value: it is an integer between 0 and 100, also rounded half-up. Counts (accounts, households, attempts) are plain integers.

### 2.7. Validation Order and Nested Resource Resolution

Every request passes through a fixed validation pipeline, and the order is part of the contract:

1. **Request shape** — the body is well-formed, all required fields are present and correctly typed, and enum values are valid (`ERR_INVALID_REQUEST`, 400).
2. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is recognized (`ERR_UNAUTHENTICATED`, 401).
3. **Authorization** — the role is permitted for this endpoint; for milestone mark-met, a `HospitalPartner`'s `X-User-ID` must equal the partnership's `source_org_id` (`ERR_FORBIDDEN`, 403).
4. **Path existence** — path-segment entities exist, validated left-to-right; the first missing segment fails the request (`ERR_NOT_FOUND`, 404).
5. **Body-referenced existence** — entities referenced by body fields exist (`ERR_SOURCE_ORG_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, or `ERR_ACCOUNT_NOT_FOUND`, all 404).
6. **Source-state legality** — the target entity is in a legal source state for the transition (`ERR_INVALID_STATE` or `ERR_CAMPAIGN_CLOSED`, 409).
7. **Cross-entity state gates** — batch create/commit requires the portfolio to be `SETTLED` or `ABOLISHING` (`ERR_PORTFOLIO_NOT_SETTLED`); letter send requires a `FINALIZED` batch; credit-deletion submission requires an `ABOLISHED` account whose bureau status is `REPORTED` (`ERR_ACCOUNT_NOT_ABOLISHED`, `ERR_BUREAU_NOT_REPORTED`); screening execution requires an `ACTIVE` policy and a portfolio in `SCREENING` (`ERR_POLICY_NOT_ACTIVE`); portfolio submission requires an `ACTIVE` source organization (`ERR_SOURCE_ORG_SUSPENDED`); price-quote requires screening completeness (`ERR_SCREENING_INCOMPLETE`). All are 409.
8. **Charitable-compliance covenants** — contract execution requires both covenants true (`ERR_COLLECTION_COVENANT_MISSING`, 422); a hospital-earmarked campaign may not target a suspended organization (`ERR_EARMARK_TARGET_SUSPENDED`, 409).
9. **Temporal windows** — policy activation windows may not overlap within a jurisdiction (`ERR_POLICY_WINDOW_OVERLAP`, 409); published report periods may not overlap within a scope key (`ERR_REPORT_PERIOD_OVERLAP`, 409).
10. **Referential fit** — earmark and partnership targets must be hospitals and batch accounts must belong to the path portfolio (`ERR_EARMARK_TARGET_NOT_HOSPITAL` or `ERR_PARTNERSHIP_NOT_HOSPITAL`, 422; `ERR_BATCH_ACCOUNT_FOREIGN`, 409).
11. **Domain constraints** — price drift, segregation of duties, household-size sanity, non-empty batches, letter attempt limits, credit-deletion resubmission limits, milestone code uniqueness, partnership completion gates, and batch reversibility (409; `ERR_BATCH_EMPTY` is 422).
12. **Money checks, last** — donation and exclusion amounts (`ERR_INVALID_AMOUNT`, 422) and waterfall coverage (`ERR_INSUFFICIENT_FUNDING`, 402).
13. **Optimistic concurrency** — `expected_portfolio_version` must match the portfolio's current `version` (`ERR_STALE_VERSION`, 412).

When several checks could fail on one request, the earliest tier's error is returned — so, for example, a malformed body surfaces as `ERR_INVALID_REQUEST` even if the caller is also unauthorized, and a state conflict surfaces before any money check on the same call.

### 2.8. Optimistic Concurrency Control

Two write endpoints — both child creations against a `Portfolio` — are protected by optimistic concurrency control, and no other endpoint takes a version field.

- Creating a purchase contract against a portfolio requires the request to carry `expected_portfolio_version`, set to the portfolio's `version` as the client last observed it. If the portfolio's current `version` no longer matches — for instance because a re-price recomputed the quote since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412): the client would otherwise pin a contract to a quote it never saw.
- Creating an abolishment batch against a portfolio likewise requires `expected_portfolio_version`. A mismatch with the portfolio's current `version` — for instance because another batch's finalize changed the abolished totals — is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the portfolio before composing the batch.

Endpoints not named here do not accept any version field.

### 2.9. Derived Totals, Version Bumps, and Cascading Consistency

The `Portfolio` is the aggregate whose derived fields — `eligible_face_value_cents`, `eligible_account_count`, `quoted_price_cents`, `purchased_price_cents`, and `abolished_face_value_cents` — are maintained by the workflows in §3, never written directly. Every operation that advances a portfolio's lifecycle (submit, screening-run creation, screening execution, price-quote, contract creation, execution, settlement, termination, cancellation, and batch creation, commit, finalization, and reversal) increments the portfolio's `version` by exactly one and refreshes its `updated_at`; batch uncommit does not touch the portfolio. Two invariants hold at all times: a campaign's `raised_cents` always equals the sum of `net_cents` over its `RECEIVED` donations, and a portfolio's `abolished_face_value_cents` always equals the sum of `total_abolished_cents` over its `FINALIZED` batches. When a screening execution or a manual review changes which accounts count as eligible, the portfolio's eligible totals are recomputed immediately from the full result set; when a batch finalizes or reverses, the abolished totals and every drawn campaign's balances move together in the same atomic step.

## 3. Business Logic & Workflows

### 3.1. Sourcing: Seller Organizations and Portfolio Intake

A `PlatformAdmin` onboards each seller by registering a `SourceOrganization` with its legal `name`, an `org_type` of `HOSPITAL`, `PHYSICIAN_GROUP`, or `DEBT_BUYER`, the two-letter `state_code` of its principal office, and a `contact_email`. The organization is born `ACTIVE`, and its `org_type` is immutable once set. When a seller relationship sours, the administrator may suspend the organization — a transition allowed only from `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise. Suspension has two immediate consequences: any attempt to submit one of that seller's portfolios is rejected with `ERR_SOURCE_ORG_SUSPENDED`, and any attempt to create a donor campaign earmarked to that seller as a hospital is rejected with `ERR_EARMARK_TARGET_SUSPENDED`. Reactivation returns a `SUSPENDED` organization to `ACTIVE` and restores normal operations.

With a seller registered, a `PortfolioAnalyst` creates a `Portfolio` by naming the selling organization in `source_org_id` — a reference that must resolve to an existing organization or the create fails with `ERR_SOURCE_ORG_NOT_FOUND` — together with a human-readable `label`, the declared total `face_value_cents` of the bundled accounts, and the seller's `asking_price_cents`. The portfolio is born `DRAFT` with all computed totals at zero and `quoted_price_cents` unset.

Accounts enter the portfolio through a bulk import of the seller's account-level data file, performed by the analyst while the portfolio is still in `DRAFT`; the request body carries a single `accounts` array whose elements are the per-account records. Each imported item carries the seller's `external_ref`, a `debtor_household_key` shared by every account of the same household, the debtor's `debtor_zip` and `debtor_state`, an optional `household_size` and `annual_income_cents`, an `is_insolvent` flag attesting that debts exceed assets, the outstanding `balance_cents` at file cut, any post-cut `accrued_adjustment_cents` (residual interest or reversals; negative values allowed, defaulting to zero when absent), and the optional `mailing_address` later used for notification letters. Accounts whose seller reported them to a credit bureau carry `reported_to_bureau` true and must name a `bureau_name` of `EQUIFAX`, `EXPERIAN`, or `TRANSUNION`; when `reported_to_bureau` is false, `bureau_name` must be absent, and presenting a bureau flag without a bureau name is rejected as `ERR_INVALID_REQUEST`. A `household_size` that is present but less than 1 fails the item as `ERR_INVALID_HOUSEHOLD_DATA`. The import is atomic: any invalid item rejects the entire file, and the response array preserves request order; a successful import returns `201` with `response_type` `array` and, unlike list endpoints, no pagination fields in `meta`. Every imported account begins with `eligibility_status` `UNSCREENED`, `lifecycle_status` `AVAILABLE`, and a `bureau_status` initialized from the reported flag — `REPORTED` when reported, `NOT_REPORTED` otherwise. The account's `portfolio_id` is bound by the import path and never changes.

Submitting the portfolio — allowed only from `DRAFT` — requires at least one imported account (`ERR_BATCH_EMPTY` when the file is empty) and an `ACTIVE` seller (`ERR_SOURCE_ORG_SUSPENDED`). A successful submission moves the portfolio to `SUBMITTED`. A portfolio that should not proceed may instead be cancelled from `DRAFT`, `SUBMITTED`, `SCREENING`, or `PRICED`, landing in the terminal `CANCELLED` state; cancelling from `PRICED` additionally requires that no purchase contract for the portfolio is sitting in `DRAFT` or `EXECUTED`, otherwise the cancellation is rejected with `ERR_INVALID_STATE`.

### 3.2. Eligibility: Policies, Screening Runs, and Manual Review

Eligibility rules live in `EligibilityPolicy` resources, created by an `EligibilityOfficer` or a `PlatformAdmin` with a `name`, a jurisdiction `state_code`, an `fpl_multiplier` that scales the federal poverty level base table and must be greater than zero, an `insolvency_qualifies` flag deciding whether insolvent debtors qualify above the income cap, and a half-open effectiveness window from `effective_from` up to but not including `effective_to` (both `YYYY-MM-DD`; the end must fall after the start). A policy is born `DRAFT`.

Activation, performed by an `EligibilityOfficer` and only from `DRAFT`, enforces window exclusivity: no two `ACTIVE` policies in the same `state_code` may have overlapping half-open windows, and a violation is rejected with `ERR_POLICY_WINDOW_OVERLAP`. Adjacency is not overlap — when one policy's `effective_to` equals another's `effective_from`, both may be active. An `ACTIVE` policy becomes selectable for screening runs; an `EligibilityOfficer` may later retire it, moving it from `ACTIVE` to terminal `RETIRED`, after which screening runs naming it fail with `ERR_POLICY_NOT_ACTIVE`.

Screening begins when an `EligibilityOfficer` opens a `ScreeningRun` against a portfolio, supplying the `policy_id` to apply — a reference that must exist (`ERR_POLICY_NOT_FOUND`) and be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`). The portfolio must be in `SUBMITTED`, `SCREENING`, or `PRICED`; creating the run moves it to `SCREENING`, which is why a re-screen from `PRICED` acts as a deliberate back-edge that invalidates the pricing context — the previous quote remains on `quoted_price_cents` until the next price-quote, but it no longer reflects the freshest eligibility picture. The run is born `PENDING` with `eligible_count`, `ineligible_count`, and `needs_review_count` all zero and `executed_at` unset.

Executing the run — allowed only while it is `PENDING` and only while the portfolio is still in `SCREENING`, with both violations surfacing as `ERR_INVALID_STATE`, and only while the named policy is still `ACTIVE` at execution time (`ERR_POLICY_NOT_ACTIVE` if it was retired after the run was created) — re-derives every account of the portfolio from scratch, regardless of each account's current `eligibility_status`; a re-screen resets prior results, so an account previously found `ELIGIBLE` may flip to `INELIGIBLE` or `NEEDS_REVIEW`, and vice versa. The per-account rule is a threshold test. For each account, the system computes an income cap: take the federal poverty level base of 15,650.00 dollars for a household of one, add 5,560.00 dollars for each additional household member, multiply by the policy's `fpl_multiplier`, and round the result half-up to whole cents. Then:

- If `household_size` is absent or less than 1, the account cannot be scored and lands in `NEEDS_REVIEW`.
- Otherwise, if `annual_income_cents` is absent, the account is `ELIGIBLE` only when `is_insolvent` is true and the policy's `insolvency_qualifies` is true; failing either, it lands in `NEEDS_REVIEW`.
- Otherwise, if `annual_income_cents` is at most the cap — equality qualifies — the account is `ELIGIBLE`, and insolvency is never consulted.
- Otherwise, above the cap, the account is `ELIGIBLE` only when `is_insolvent` is true and the policy's `insolvency_qualifies` is true — the insolvency override; failing either, it is `INELIGIBLE`. A policy whose `insolvency_qualifies` is false flips the identical over-cap account to `INELIGIBLE`, and the identical income-missing account to `NEEDS_REVIEW`.

Execution completes the run to terminal `COMPLETED`, recording `eligible_count`, `ineligible_count`, and `needs_review_count` from the result set, stamping `executed_at` from the logical clock, and recomputing the portfolio's `eligible_face_value_cents` — the sum of `balance_cents` over accounts now `ELIGIBLE` — and `eligible_account_count` accordingly.

Accounts stuck in `NEEDS_REVIEW` are resolved by an `EligibilityOfficer` through a manual review carrying a `decision` of `ELIGIBLE` or `INELIGIBLE`. Review is allowed only from `NEEDS_REVIEW` (`ERR_INVALID_STATE` otherwise); a decision of `ELIGIBLE` moves the account there and triggers the same recomputation of the portfolio's eligible totals, while a decision of `INELIGIBLE` simply marks the account ineligible.

### 3.3. Pricing: The Tiered Purchase Quote

Once screening is complete, a `PortfolioAnalyst` requests a price quote. Quoting requires the portfolio to be in `SCREENING` (or already `PRICED`, for a re-price) and demands screening completeness: at least one `COMPLETED` screening run must exist for the portfolio and zero accounts may remain in `UNSCREENED` or `NEEDS_REVIEW`; otherwise the request fails with `ERR_SCREENING_INCOMPLETE`.

The quote prices only eligible debt. Starting from the portfolio's `eligible_face_value_cents`, the system applies a three-tier schedule. The first tier covers the eligible face value up to one million dollars (100,000,000 cents) at a rate of 2.5 cents per dollar of face (0.025). The second tier covers the next four million dollars (400,000,000 cents) of face at 1.5 cents per dollar (0.015). Any remaining face beyond five million dollars prices at 0.8 cents per dollar (0.008). The three tier amounts are summed, and the sum is then multiplied by a factor reflecting the seller's `org_type`: 1.0 for a `HOSPITAL`, 0.9 for a `PHYSICIAN_GROUP`, and 0.75 for a `DEBT_BUYER`. The final quoted price is this product rounded half-up to whole cents — exactly one rounding, at the very end, never per tier. The evaluation order is pinned: tiers are computed on the face value first, the org factor is applied to the tiered sum, and rounding happens once.

The result is stored as `quoted_price_cents` and the portfolio moves to `PRICED`. Re-quoting a `PRICED` portfolio recomputes under the same screening-completeness preconditions and overwrites the quote; any `DRAFT` contract keeps the snapshot it pinned, with the divergence surfaced later at execution as a price-drift failure.

Two valuations of an account coexist throughout the pipeline. The provisional relief value is `balance_cents` alone; it drives screening totals, the price quote, and pre-purchase reporting. The final relief value is `balance_cents` plus `accrued_adjustment_cents` — residual interest added or reversed after the data cut — and it is the value recorded at abolishment. For an account with a non-zero adjustment, the two values deliberately differ.

### 3.4. The Purchase: Contracts, Covenants, and Settlement

A `ContractManager` drafts a `PurchaseContract` against a `PRICED` portfolio by attesting to the two charitable covenants — `collection_prohibition`, the buyer's promise never to attempt collection, and `no_resale`, the promise that accounts may never be resold — and by presenting `expected_portfolio_version` per the optimistic-concurrency rule of §2.8. Creation snapshots the portfolio's current `quoted_price_cents` into `contract_price_cents`, version-pinned, and the contract is born `DRAFT`.

Execution, also by a `ContractManager`, enforces four checks, evaluated in order: the request shape first, then authorization, then the contract's own state and the cross-entity gates, then the business rules. The contract must be `DRAFT` and the portfolio must be `PRICED` (`ERR_INVALID_STATE`). Both covenants must be true; a missing covenant is rejected with `ERR_COLLECTION_COVENANT_MISSING`, and this covenant check precedes the price comparison. The portfolio's current `quoted_price_cents` must still equal the pinned `contract_price_cents`; if a re-quote has drifted the price, execution is rejected with `ERR_PRICE_DRIFT`. On success, the contract becomes `EXECUTED`, records `executed_by` from the caller's `X-User-ID`, and the portfolio advances to `CONTRACTED`.

Settlement belongs to a `FinanceOfficer` — and segregation of duties is enforced: the settler's `X-User-ID` must differ from `executed_by`, or the settle is rejected with `ERR_SEGREGATION_OF_DUTIES`. The contract must be `EXECUTED`. Settlement stamps `settled_by`, copies the pinned `contract_price_cents` into the portfolio's `purchased_price_cents`, moves the portfolio to `SETTLED`, and partitions the accounts: every account whose `eligibility_status` is `ELIGIBLE` at settlement moves from `AVAILABLE` to `PURCHASED` and becomes valid input for abolishment batches, while every other account — `INELIGIBLE`, `NEEDS_REVIEW`, or still `UNSCREENED` — moves from `AVAILABLE` to terminal `EXCLUDED`.

A contract that should not settle may be terminated by a `ContractManager` from `EXECUTED`, supplying a `reason` that is recorded as `terminated_reason`; the contract lands in terminal `TERMINATED` and the portfolio falls back from `CONTRACTED` to `PRICED`, freeing it to be re-contracted or cancelled.

### 3.5. Donor Funding: Campaigns, Donations, and the Earmark Waterfall

A `DonorRelationsOfficer` raises money through `DonorCampaign` resources. Each campaign has a `name`, an `earmark_type` of `GEOGRAPHY`, `HOSPITAL`, or `GENERAL`, and a funding `goal_cents`. A geography earmark requires an `earmark_state_code` and forbids an `earmark_source_org_id`; a hospital earmark requires an `earmark_source_org_id` — which must resolve to an existing organization (`ERR_SOURCE_ORG_NOT_FOUND`) whose status is not `SUSPENDED` (`ERR_EARMARK_TARGET_SUSPENDED`, checked first) and whose `org_type` is `HOSPITAL` (`ERR_EARMARK_TARGET_NOT_HOSPITAL`) — and forbids an `earmark_state_code`; a general campaign carries neither earmark field. Violations of these earmark field-shape rules — a missing required field or a forbidden field present — are request-shape failures rejected with `ERR_INVALID_REQUEST` (400). Campaigns are born `OPEN` with `raised_cents`, `committed_cents`, and `spent_cents` all at zero.

Donations are recorded against a campaign by the officer, supplying `donor_name`, `donor_email`, and a `gross_cents` that must be greater than zero (`ERR_INVALID_AMOUNT`). The campaign must not be `CLOSED` (`ERR_CAMPAIGN_CLOSED`). Each donation is born `PLEDGED` against the campaign named by its path-bound `campaign_id`, and its economics are computed per donation: the processing `fee_cents` is the gift multiplied by a fee rate of 2.9 percent (0.029), rounded half-up to whole cents, and `net_cents` is the gross minus the fee. The rounding order is pinned: the fee is rounded per donation, and only then are nets summed into campaign totals. The alternative — summing grosses and rounding once — is forbidden because it yields different cents: two gifts of 3,333 cents net 3,236 each for a campaign total of 6,472, whereas sum-then-round would produce 6,473.

A `FinanceOfficer` marks a pledge received, which moves the donation from `PLEDGED` to `RECEIVED` and adds its `net_cents` to the campaign's `raised_cents`. If the campaign was `OPEN` and its `raised_cents` now meets or exceeds `goal_cents` — equality counts as funded — the campaign automatically flips to `FUNDED`; a funded campaign remains open to further donations and to funding draws. Refund is the compensating action: a `FinanceOfficer` may refund a `RECEIVED` donation, subtracting its `net_cents` from `raised_cents`, and if a `FUNDED` campaign thereby drops below its goal it flips back to `OPEN`. Refunded donations land in terminal `REFUNDED`. A campaign's `raised_cents` is always exactly the sum of `net_cents` over its `RECEIVED` donations. The officer may close a campaign from either `OPEN` or `FUNDED`; closure is terminal, blocks new donations with `ERR_CAMPAIGN_CLOSED`, and removes the campaign from the funding waterfall. Receiving or refunding a donation remains possible after its campaign is `CLOSED` and still adjusts `raised_cents`, but the automatic threshold flip never changes a `CLOSED` campaign's status.

The waterfall runs when a `FinanceOfficer` commits a staged abolishment batch, and it allocates the batch's funding need across campaigns in a strict draw order. Candidates are campaigns in `OPEN` or `FUNDED` — `CLOSED` campaigns never participate — sorted into three classes: first, hospital-earmarked campaigns whose `earmark_source_org_id` equals the portfolio's seller; second, geography-earmarked campaigns whose `earmark_state_code` equals the seller organization's `state_code`; third, general campaigns. Within each class, campaigns draw in chronological `created_at` order, earliest first, with ties broken by creation order; `id` is never a tiebreaker. From each candidate the waterfall draws the smaller of the batch's remaining need and the campaign's uncommitted balance — its `raised_cents` minus its `committed_cents` — skipping any candidate whose uncommitted balance is not positive. Drawing stops as soon as the remaining need reaches zero. If every candidate is exhausted with need outstanding, the entire commit is rejected with `ERR_INSUFFICIENT_FUNDING` — the reservation is atomic and no campaign is partially drawn on failure. On success the batch records its `funding_allocations` as the list of campaign-and-amount pairs in draw order, each an object with `campaign_id` and `amount_cents`, and each drawn campaign's `committed_cents` increases by its allocation.

### 3.6. Abolishment: Batches, Finalization, and Reversal

Abolishment executes in batches. A `FinanceOfficer` stages an `AbolishmentBatch` against a settled portfolio by listing the `account_ids` to abolish and presenting `expected_portfolio_version` per §2.8. For this endpoint the checks run in a pinned order that overrides the general tier ordering of §2.7: the list must be non-empty (`ERR_BATCH_EMPTY`), every entry must resolve to an existing account (`ERR_ACCOUNT_NOT_FOUND`), the portfolio itself must be `SETTLED` or `ABOLISHING` (`ERR_PORTFOLIO_NOT_SETTLED`), every account must belong to the portfolio named in the path (`ERR_BATCH_ACCOUNT_FOREIGN`), every account must be in `PURCHASED` lifecycle (`ERR_ACCOUNT_NOT_PURCHASED`), and only then is `expected_portfolio_version` compared. The batch is born `STAGING` with `account_count` set to the length of the list, `funding_allocations` empty, `reversed_reason` unset, and `total_abolished_cents` computed as the sum, over the listed accounts, of each account's final relief value — its `balance_cents` plus `accrued_adjustment_cents`.

Committing the batch runs the earmark waterfall of §3.5 against `total_abolished_cents`. A successful commit moves the batch to `COMMITTED` and, on the first commit against a `SETTLED` portfolio, advances the portfolio to `ABOLISHING`. Uncommitting is the compensating action: it returns a `COMMITTED` batch to `STAGING`, releases every drawn campaign's reservation by subtracting each allocation from that campaign's `committed_cents`, and clears the batch's `funding_allocations`.

Finalization is the moment of abolishment. From `COMMITTED`, the batch moves to terminal `FINALIZED` and a three-link cascade fires for every account in the batch. First, the account moves from `PURCHASED` to terminal `ABOLISHED`: its `abolished_amount_cents` is stamped with the final relief value, its `abolished_at` is stamped from the logical clock, and its `abolished_batch_id` records the batch. Second, three artifacts are created per account: a `NotificationLetter` in `QUEUED` status carrying a snapshot of the account's mailing address, a `TaxReliefRecord` in `PENDING` status whose `relief_amount_cents` snapshots the abolished amount, and — only for accounts whose `bureau_status` is `REPORTED` — a `CreditDeletionRequest` that skips the draft stage and is born already `SUBMITTED` with the batch recorded on its `batch_id` and the account's `bureau_name` recorded as its `bureau`. Third, that auto-submitted deletion request flips the account's `bureau_status` from `REPORTED` to `DELETION_REQUESTED`. Meanwhile each drawn campaign converts its reservation into spend — `committed_cents` decreases by the allocation and `spent_cents` increases by the same — and the portfolio's `abolished_face_value_cents` increases by the batch's `total_abolished_cents`. When a finalize leaves no `PURCHASED` accounts remaining and no batch in `STAGING` or `COMMITTED` — that is, every account's lifecycle is `ABOLISHED` or `EXCLUDED` — the portfolio automatically closes: it moves from `ABOLISHING` to terminal `CLOSED`, after which no further batches, screenings, or contracts are possible.

Reversal is the compensating action for a finalized batch, and it is gated on irreversibility. A `FinanceOfficer` may reverse a `FINALIZED` batch, supplying a `reason` recorded as `reversed_reason`, only while none of the batch's artifacts has crossed an outer wall: no letter may be `SENT`, `DELIVERED`, or `UNDELIVERABLE`; no credit-deletion request may be `ACKNOWLEDGED`; and no tax record may be `FILED` or `EXEMPT`. Any such artifact makes the batch irreversible and the reversal is rejected with `ERR_BATCH_IRREVERSIBLE`. A successful reversal moves the batch to terminal `REVERSED`; returns every account from `ABOLISHED` to `PURCHASED`, clearing `abolished_amount_cents`, `abolished_at`, and `abolished_batch_id`; cancels every letter still in `QUEUED` or `BOUNCED`; cancels every credit-deletion request in `DRAFT`, `SUBMITTED`, or `REJECTED` and returns the corresponding accounts' `bureau_status` from `DELETION_REQUESTED` back to `REPORTED`; cancels every tax record in `PENDING` or `ASSESSED`; returns each drawn campaign's allocation by subtracting it from `spent_cents` so the funds reappear as raised but unspent; and subtracts the batch's `total_abolished_cents` from the portfolio's `abolished_face_value_cents`, restoring the invariant that the portfolio total equals the sum over `FINALIZED` batches.

### 3.7. Notification Letters: The Bounded Bounce Cycle

Beneficiaries never applied for relief, so the letter is how they learn their debt is gone. Each letter is created at batch finalization in `QUEUED` status, carrying the `account_id`, the `batch_id`, a `channel` of `MAIL` (the cascade always creates letters on the `MAIL` channel), a `mailing_address` snapshotted from the account (which may be absent if the account was imported without one), an `attempt_count` of zero, and no `sent_at`.

A `DonorRelationsOfficer` sends a `QUEUED` letter — but only once its parent batch is `FINALIZED`; sending earlier fails with `ERR_INVALID_STATE`. Sending moves the letter to `SENT` and stamps `sent_at` from the logical clock. From `SENT` the letter either lands — the officer marks it `DELIVERED`, a terminal state — or it bounces. Marking a bounce increments `attempt_count` and consults the attempt ceiling, which is three attempts: if the incremented count is still below three, the letter falls back to `BOUNCED`, but if the incremented count reaches three the letter becomes terminally `UNDELIVERABLE` instead.

A `BOUNCED` letter may be requeued by the officer, optionally supplying a `corrected_address`; when one is provided, the letter's `mailing_address` is replaced with it. Requeueing returns the letter to `QUEUED` for another send, but only while `attempt_count` remains below the three-attempt ceiling — requeueing a letter that has exhausted its attempts is rejected with `ERR_DELIVERY_ATTEMPTS_EXHAUSTED`. Letters may also reach `CANCELLED`, but only through batch reversal, never directly.

### 3.8. Credit Bureau Deletion and Tax Relief

For accounts the seller reported to a bureau, abolishment must be followed by tradeline deletion. The automatic path creates a `SUBMITTED` `CreditDeletionRequest` at batch finalization, as described in §3.6. A `ComplianceAuditor` may also create a request manually against an account, supplying the `bureau` (`EQUIFAX`, `EXPERIAN`, or `TRANSUNION`); manual creation is permitted only for an account whose lifecycle is `ABOLISHED` (`ERR_ACCOUNT_NOT_ABOLISHED`) and whose `bureau_status` is `REPORTED` (`ERR_BUREAU_NOT_REPORTED`), and it produces a `DRAFT` request with no `batch_id`.

Submitting a `DRAFT` request — by a `ComplianceAuditor`, under the same account-level gates of `ABOLISHED` lifecycle and `REPORTED` bureau status — moves it to `SUBMITTED` and flips the account's `bureau_status` from `REPORTED` to `DELETION_REQUESTED`. The bureau's answer arrives through the auditor. Acknowledgement moves a `SUBMITTED` request to terminal `ACKNOWLEDGED` and the account's `bureau_status` to terminal `DELETED`. Rejection records the supplied `rejection_reason` and depends on how many times the request has already been resubmitted, with the ceiling set at two resubmissions: while `resubmission_count` is below two, the request falls back to `REJECTED` and the account's `bureau_status` returns from `DELETION_REQUESTED` to `REPORTED`, opening another cycle; when the count already equals two, rejection instead moves the request to terminal `FAILED` and the account's `bureau_status` to terminal `DELETION_FAILED`. A `REJECTED` request may be resubmitted by the auditor while `resubmission_count` is below two — at the ceiling, resubmission is rejected with `ERR_RESUBMISSION_LIMIT` — which increments the count, returns the request to `SUBMITTED`, and flips the account's `bureau_status` from `REPORTED` back to `DELETION_REQUESTED`. Requests may also reach `CANCELLED` through batch reversal.

Every abolished account also carries a `TaxReliefRecord`, created `PENDING` at finalization with `relief_amount_cents` snapshotting the abolished amount and both `insolvency_exclusion_cents` and `reportable_amount_cents` unset until assessment. A `ComplianceAuditor` assesses the record by declaring an `insolvency_exclusion_cents` — the amount excluded from income under the insolvency rules — which must be at least zero and at most the full `relief_amount_cents`, with any out-of-range value rejected as `ERR_INVALID_AMOUNT`. Assessment sets `reportable_amount_cents` to the relief amount minus the exclusion and branches on the result: when the exclusion is smaller than the relief amount, a positive reportable remainder remains and the record moves to `ASSESSED`; when the exclusion equals the relief amount in full, the reportable remainder is zero, no filing is required, and the record moves to terminal `EXEMPT`. An `ASSESSED` record is completed when the auditor files it, moving it to terminal `FILED`. Records in `PENDING` or `ASSESSED` may be `CANCELLED` through batch reversal.

### 3.9. Hospital Partnerships and FAP Milestones

Abolishment pairs with policy change through `HospitalPartnership` resources. A `DonorRelationsOfficer` proposes a partnership by naming a `source_org_id` that must resolve (`ERR_SOURCE_ORG_NOT_FOUND`) to an organization whose `org_type` is `HOSPITAL` (`ERR_PARTNERSHIP_NOT_HOSPITAL`), and by recording a `fap_baseline_score` — the hospital's financial-assistance-policy score, an integer from 0 to 100, at partnership start — and a `fap_target_score`, also 0 to 100, that must exceed the baseline. The partnership is born `PROPOSED` with `fap_current_score` initialized to the baseline.

The officer activates a `PROPOSED` partnership to `ACTIVE`, may suspend an `ACTIVE` one to `SUSPENDED`, and may resume a `SUSPENDED` one back to `ACTIVE`; each step requires exactly the named source state (`ERR_INVALID_STATE`). While a partnership is `SUSPENDED`, all milestone transitions are blocked with `ERR_INVALID_STATE`.

Each milestone is created under its owning partnership — the parent is path-bound and recorded on the milestone as `partnership_id` — by the officer or by the hospital's own `HospitalPartner` contact acting with an `X-User-ID` equal to the partnership's `source_org_id` (`ERR_FORBIDDEN` otherwise), with a `code` unique within the partnership across all milestones regardless of their status (a repeat is rejected with `ERR_DUPLICATE_MILESTONE_CODE`), a `description` of the FAP improvement, a strictly positive integer `weight`, and a `due_date`. Milestones are born `PENDING`. Milestone creation is permitted in any partnership status — the suspension block applies only to the mark-met, mark-missed, and waive transitions — and creating a milestone immediately recomputes the partnership's `fap_current_score` (the new `PENDING` milestone enlarges the denominator) and refreshes the partnership's `updated_at` and `version`. From there, marking a milestone met — available to the officer, and to a `HospitalPartner` only when the caller's `X-User-ID` equals the partnership's `source_org_id` (`ERR_FORBIDDEN` otherwise) — moves it from `PENDING` or `MISSED` to terminal `MET`, so a missed milestone can still be completed late. The officer may mark a `PENDING` milestone `MISSED`, but only once the logical clock's date has passed the milestone's `due_date`; attempting it earlier fails with `ERR_INVALID_STATE`. The officer may instead waive a milestone from `PENDING` or `MISSED`, moving it to terminal `WAIVED`.

Every transition to `MET` or `WAIVED` recomputes the partnership's `fap_current_score` as a weighted attainment ratio: sum the `weight` of milestones in `MET`, divide by the sum of `weight` over all milestones not in `WAIVED`, multiply by one hundred, and round half-up to an integer. Waived milestones are excluded from both the numerator and the denominator. When every milestone is waived — the denominator is zero — the score falls back to the `fap_baseline_score`.

Completion requires two gates, both enforced when the officer completes an `ACTIVE` partnership: every milestone must sit in a terminal state — `MET`, `MISSED`, or `WAIVED` — otherwise the completion is rejected with `ERR_MILESTONE_NOT_TERMINAL`; and the `fap_current_score` must be at least the `fap_target_score`, with equality satisfying the gate, otherwise the completion is rejected with `ERR_FAP_TARGET_NOT_MET`. A completed partnership is terminal in `COMPLETED`.

### 3.10. Impact Reporting

Impact reports measure relief for donors and regulators. A `PlatformAdmin` or `ComplianceAuditor` creates an `ImpactReport` by naming a `scope` of `GLOBAL`, `GEOGRAPHY`, or `HOSPITAL`; a `period_start` and `period_end` bounding a closed, inclusive date interval (the end must not precede the start); and a `counting_variant` of `PER_ACCOUNT` or `DEDUPED_HOUSEHOLD`. A geography scope requires `scope_state_code`, matched against accounts' `debtor_state`; a hospital scope requires `scope_source_org_id`, which must resolve to an existing organization (`ERR_SOURCE_ORG_NOT_FOUND`) and is matched against the seller of each abolished account's portfolio. Scope-key fields not required by the named scope must be absent, and presenting one is `ERR_INVALID_REQUEST`.

The metrics are computed at creation, and the report is born `DRAFT` with them populated. The in-scope set is every account whose lifecycle is `ABOLISHED` and whose `abolished_at` date falls within the closed period — both boundary dates included — and which satisfies the scope predicate: unrestricted for `GLOBAL`, matching debtor state for `GEOGRAPHY`, and matching portfolio seller for `HOSPITAL`. The report's `dollars_abolished_cents` is the sum of `abolished_amount_cents` over that set, identical under both counting variants. The `households_relieved` figure depends on the variant: under `PER_ACCOUNT` it is simply the count of in-scope accounts, so three abolished accounts belonging to two households report 3; under `DEDUPED_HOUSEHOLD` it is the count of distinct `debtor_household_key` values over the set, so the same three accounts report 2.

Publishing a `DRAFT` report — by a `PlatformAdmin` or `ComplianceAuditor` — enforces period exclusivity within a scope key: no two `PUBLISHED` reports sharing the same scope and scope key may have overlapping closed periods, and because the intervals are inclusive, even sharing a single boundary date counts as overlap. A violation is rejected with `ERR_REPORT_PERIOD_OVERLAP`. A published report is terminal in `PUBLISHED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The logical-clock endpoint returns `200 OK`. All endpoints are mounted under `/api`, except the test-driving clock which is mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | PlatformAdmin |
| POST | `/api/source-organizations` | Register a seller organization (hospital, physician group, or debt buyer) | PlatformAdmin |
| GET | `/api/source-organizations/{id}` | Get one source organization | Any authenticated role |
| GET | `/api/source-organizations` | List source organizations with filters and pagination | Any authenticated role |
| POST | `/api/source-organizations/{id}/suspend` | Suspend an organization; blocks portfolio submit and hospital earmark targeting | PlatformAdmin |
| POST | `/api/source-organizations/{id}/reactivate` | Reactivate a suspended organization | PlatformAdmin |
| POST | `/api/eligibility-policies` | Create an eligibility policy (FPL-multiplier income cap plus insolvency rule) | EligibilityOfficer, PlatformAdmin |
| GET | `/api/eligibility-policies/{id}` | Get one policy | Any authenticated role |
| GET | `/api/eligibility-policies` | List policies | Any authenticated role |
| POST | `/api/eligibility-policies/{id}/activate` | Activate a policy; half-open window overlap within a state is rejected | EligibilityOfficer |
| POST | `/api/eligibility-policies/{id}/retire` | Retire an active policy | EligibilityOfficer |
| POST | `/api/portfolios` | Create a debt portfolio offered by a source organization | PortfolioAnalyst |
| GET | `/api/portfolios/{id}` | Get one portfolio | Any authenticated role |
| GET | `/api/portfolios` | List portfolios | Any authenticated role |
| POST | `/api/portfolios/{id}/submit` | Submit a draft portfolio (requires at least one account and an active seller) | PortfolioAnalyst |
| POST | `/api/portfolios/{id}/cancel` | Cancel a pre-contract portfolio | PortfolioAnalyst |
| POST | `/api/portfolios/{id}/price-quote` | Compute or recompute the tiered purchase quote | PortfolioAnalyst |
| POST | `/api/portfolios/{id}/accounts` | Bulk-import the account-level data file into a draft portfolio (atomic) | PortfolioAnalyst |
| GET | `/api/accounts/{id}` | Get one account | Any authenticated role |
| GET | `/api/accounts` | List accounts with filters | Any authenticated role |
| POST | `/api/accounts/{id}/review` | Resolve a needs-review account to eligible or ineligible | EligibilityOfficer |
| POST | `/api/portfolios/{id}/screening-runs` | Create a screening run against a policy | EligibilityOfficer |
| GET | `/api/screening-runs/{id}` | Get one screening run | Any authenticated role |
| GET | `/api/screening-runs` | List screening runs | Any authenticated role |
| POST | `/api/screening-runs/{id}/execute` | Execute the run, re-deriving every account's eligibility | EligibilityOfficer |
| POST | `/api/portfolios/{id}/contracts` | Create a purchase contract pinning the current quote (OCC on portfolio version) | ContractManager |
| GET | `/api/contracts/{id}` | Get one contract | Any authenticated role |
| GET | `/api/contracts` | List contracts | Any authenticated role |
| POST | `/api/contracts/{id}/execute` | Execute a draft contract: covenant and price-drift checks | ContractManager |
| POST | `/api/contracts/{id}/settle` | Settle an executed contract (settler must differ from executor) | FinanceOfficer |
| POST | `/api/contracts/{id}/terminate` | Terminate an executed contract; portfolio returns to priced | ContractManager |
| POST | `/api/donor-campaigns` | Create a donor campaign with optional geography or hospital earmark | DonorRelationsOfficer |
| GET | `/api/donor-campaigns/{id}` | Get one campaign | Any authenticated role |
| GET | `/api/donor-campaigns` | List campaigns | Any authenticated role |
| POST | `/api/donor-campaigns/{id}/close` | Close a campaign to new donations and waterfall draws | DonorRelationsOfficer |
| POST | `/api/donor-campaigns/{id}/donations` | Record a pledged donation; fee and net computed per donation | DonorRelationsOfficer |
| GET | `/api/donations/{id}` | Get one donation | Any authenticated role |
| GET | `/api/donations` | List donations | Any authenticated role |
| POST | `/api/donations/{id}/receive` | Mark a pledge received; campaign raised total and threshold update | FinanceOfficer |
| POST | `/api/donations/{id}/refund` | Refund a received donation (compensating action) | FinanceOfficer |
| POST | `/api/portfolios/{id}/abolishment-batches` | Stage an abolishment batch over purchased accounts (OCC on portfolio version) | FinanceOfficer |
| GET | `/api/abolishment-batches/{id}` | Get one batch | Any authenticated role |
| GET | `/api/abolishment-batches` | List batches | Any authenticated role |
| POST | `/api/abolishment-batches/{id}/commit` | Commit a staged batch; runs the funding waterfall atomically | FinanceOfficer |
| POST | `/api/abolishment-batches/{id}/uncommit` | Uncommit a batch, releasing campaign reservations | FinanceOfficer |
| POST | `/api/abolishment-batches/{id}/finalize` | Finalize: abolish accounts and cascade letters, deletion requests, tax records | FinanceOfficer |
| POST | `/api/abolishment-batches/{id}/reverse` | Reverse a finalized batch when no irreversible artifacts exist | FinanceOfficer |
| GET | `/api/notification-letters/{id}` | Get one letter | Any authenticated role |
| GET | `/api/notification-letters` | List letters | Any authenticated role |
| POST | `/api/notification-letters/{id}/send` | Send a queued letter (batch must be finalized) | DonorRelationsOfficer |
| POST | `/api/notification-letters/{id}/mark-bounced` | Record a bounce; the third bounce marks the letter undeliverable | DonorRelationsOfficer |
| POST | `/api/notification-letters/{id}/requeue` | Requeue a bounced letter, optionally with a corrected address | DonorRelationsOfficer |
| POST | `/api/notification-letters/{id}/mark-delivered` | Mark a sent letter delivered | DonorRelationsOfficer |
| POST | `/api/accounts/{id}/credit-deletion-requests` | Manually create a draft deletion request for an abolished, reported account | ComplianceAuditor |
| GET | `/api/credit-deletion-requests/{id}` | Get one deletion request | Any authenticated role |
| GET | `/api/credit-deletion-requests` | List deletion requests | Any authenticated role |
| POST | `/api/credit-deletion-requests/{id}/submit` | Submit a draft deletion request to the bureau | ComplianceAuditor |
| POST | `/api/credit-deletion-requests/{id}/acknowledge` | Record bureau acknowledgement of deletion | ComplianceAuditor |
| POST | `/api/credit-deletion-requests/{id}/reject` | Record bureau rejection; at the resubmission ceiling the request fails terminally | ComplianceAuditor |
| POST | `/api/credit-deletion-requests/{id}/resubmit` | Resubmit a rejected deletion request (bounded cycle) | ComplianceAuditor |
| GET | `/api/tax-relief-records/{id}` | Get one tax relief record | Any authenticated role |
| GET | `/api/tax-relief-records` | List tax relief records | Any authenticated role |
| POST | `/api/tax-relief-records/{id}/assess` | Assess tax treatment; full insolvency exclusion routes to exempt | ComplianceAuditor |
| POST | `/api/tax-relief-records/{id}/file` | File the cancellation-of-debt report for an assessed record | ComplianceAuditor |
| POST | `/api/hospital-partnerships` | Create a partnership with a hospital combining abolishment with FAP improvements | DonorRelationsOfficer |
| GET | `/api/hospital-partnerships/{id}` | Get one partnership | Any authenticated role |
| GET | `/api/hospital-partnerships` | List partnerships | Any authenticated role |
| POST | `/api/hospital-partnerships/{id}/activate` | Activate a proposed partnership | DonorRelationsOfficer |
| POST | `/api/hospital-partnerships/{id}/suspend` | Suspend an active partnership (blocks milestone transitions) | DonorRelationsOfficer |
| POST | `/api/hospital-partnerships/{id}/resume` | Resume a suspended partnership | DonorRelationsOfficer |
| POST | `/api/hospital-partnerships/{id}/complete` | Complete when all milestones are terminal and the FAP target is met | DonorRelationsOfficer |
| POST | `/api/hospital-partnerships/{id}/milestones` | Add a FAP improvement milestone; code unique within the partnership | DonorRelationsOfficer, HospitalPartner |
| GET | `/api/partnership-milestones/{id}` | Get one milestone | Any authenticated role |
| GET | `/api/partnership-milestones` | List milestones | Any authenticated role |
| POST | `/api/partnership-milestones/{id}/mark-met` | Mark a milestone met (including late completion from missed) | HospitalPartner, DonorRelationsOfficer |
| POST | `/api/partnership-milestones/{id}/mark-missed` | Mark a pending milestone missed once its due date has passed | DonorRelationsOfficer |
| POST | `/api/partnership-milestones/{id}/waive` | Waive a milestone, excluding it from the FAP score | DonorRelationsOfficer |
| POST | `/api/impact-reports` | Create an impact report; metrics computed at creation per counting variant | PlatformAdmin, ComplianceAuditor |
| GET | `/api/impact-reports/{id}` | Get one impact report | Any authenticated role |
| GET | `/api/impact-reports` | List impact reports | Any authenticated role |
| POST | `/api/impact-reports/{id}/publish` | Publish a report; closed-period overlap within a scope key is rejected | PlatformAdmin, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_SOURCE_ORG_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOURCE_ORG_SUSPENDED` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 |
| `ERR_SCREENING_INCOMPLETE` | 409 |
| `ERR_PORTFOLIO_NOT_SETTLED` | 409 |
| `ERR_ACCOUNT_NOT_PURCHASED` | 409 |
| `ERR_ACCOUNT_NOT_ABOLISHED` | 409 |
| `ERR_BATCH_EMPTY` | 422 |
| `ERR_BATCH_ACCOUNT_FOREIGN` | 409 |
| `ERR_BATCH_IRREVERSIBLE` | 409 |
| `ERR_INSUFFICIENT_FUNDING` | 402 |
| `ERR_COLLECTION_COVENANT_MISSING` | 422 |
| `ERR_PRICE_DRIFT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CAMPAIGN_CLOSED` | 409 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_EARMARK_TARGET_NOT_HOSPITAL` | 422 |
| `ERR_EARMARK_TARGET_SUSPENDED` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_INVALID_HOUSEHOLD_DATA` | 422 |
| `ERR_DELIVERY_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_RESUBMISSION_LIMIT` | 409 |
| `ERR_BUREAU_NOT_REPORTED` | 409 |
| `ERR_DUPLICATE_MILESTONE_CODE` | 409 |
| `ERR_PARTNERSHIP_NOT_HOSPITAL` | 422 |
| `ERR_MILESTONE_NOT_TERMINAL` | 409 |
| `ERR_FAP_TARGET_NOT_MET` | 409 |
