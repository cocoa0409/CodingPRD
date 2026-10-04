# Commitment Contracts Savings Plans API — Product Requirements Document

## 1. Introduction

Enterprise cloud customers rarely pay list price. They negotiate multi-year agreements that commit a fixed amount of eligible spend over a term in exchange for tiered discount rates, they pre-purchase hourly commitment plans (savings plans and reserved capacity) that discount covered usage, and they receive promotional or concessionary credits that offset what is finally owed. When these instruments stack — a private pricing amendment on a service family, a savings plan covering compute, a negotiated tier schedule on the same agreement, and a credit grant about to expire — the order in which discounts are applied determines real money. Consolidated billing across an organization's linked accounts makes the problem harder still, because commitments and credits are shared at the payer level while consumption happens per account.

This document specifies a billing administration API that models that world end to end. It covers the lifecycle of enterprise discount agreements from negotiation through activation, suspension, expiry, and termination; the purchase and early termination of commitment plans with org-wide fiscal ceilings and capacity quotas; usage ingestion from linked accounts; a pinned four-stage discount waterfall that turns a period's raw usage into a draft invoice; credit grant issuance, consumption, forfeiture, and revocation under a strict conservation invariant; term-end true-up billing for commitment shortfalls and early termination penalties; and renewal forecasting from closed-period history. All monetary values are integer cents; all time is governed by a logical clock, not the wall clock.

The audience is the engineering team implementing the service. The API is mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal acts. A request missing either header, or presenting a role value that is not one of the declared roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `PlatformBillingOperator` — the cloud platform operator. It manages the logical clock, creates billing organizations, runs period closes, issues and revokes credit grants, and may ingest usage records on behalf of any account. When `X-User-Role` is `PlatformBillingOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `OrgAdmin` — the customer-side organization administrator. It manages linked accounts (create, suspend, reactivate), enterprise agreements (create and all lifecycle transitions), discount tiers, commitment plans (purchase and terminate), invoices (generate, finalize, dispute, resolve-dispute, settle, void), and true-up charges (assess and bill). Its `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- `FinanceAnalyst` — the customer-side finance analyst. It owns private pricing amendments, renewal review (open and close), true-up waivers, and renewal forecasts. It is deliberately segregated from `OrgAdmin` on true-up: the analyst may waive a charge but may never assess or bill one. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `LinkedAccountManager` — the manager of exactly one linked account. When `X-User-Role` is `LinkedAccountManager`, `X-User-ID` is the `id` of the acting `LinkedAccount`; ownership checks on any resource that references a `LinkedAccount` compare the resource's foreign-key field to `X-User-ID`. A `LinkedAccountManager` may ingest usage only for its own account — that is, only when the payload's `linked_account_id` equals `X-User-ID` — and any attempt to ingest for another account is rejected with `ERR_FORBIDDEN` (HTTP 403).

All four roles may read resources through the GET endpoints enumerated in §4, subject to the per-endpoint role lists there.

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

List endpoints accept optional query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are sorted by `created_at` ascending unless stated otherwise. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional results exist beyond the returned window.

### 2.4. Common Resource Properties, Timestamps, and the Logical Clock

Every persistent resource carries an `id` that is a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at its initial value and increments by exactly 1 on every mutation of that resource. Stateful entities — linked accounts, agreements, plans, usage records, credit grants, invoices, and true-up charges — also expose a `status` field (or, on agreements, the `lifecycle_status` and `renewal_status` pair) carrying the exact state strings used throughout §3. Three resource kinds are lighter-weight and carry only `id` and `created_at` — neither `updated_at` nor `version` is present on them: usage records, invoice lines, and renewal forecasts.

Time in this system is logical, not wall-clock. The platform operator sets the logical clock through an admin-only capability that supplies a `to_iso8601` instant; at startup the clock reads exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time. Every temporal rule in this document — term windows, amendment windows, credit expiry, coverage replay, remaining-hours computations — evaluates against this logical clock.

### 2.5. Monetary Precision and Rounding

All money amounts are integer cents. Unless a rule says otherwise, intermediate computation keeps full precision and rounding happens exactly once per invoice line: the line's `net_due_cents` is rounded half-up to integer cents at line finalization, and invoice totals are sums of those already-rounded line values — the sum-of-unrounded-then-round pattern is never used. Per-stage discount fields on a line are each stored as integer cents rounded half-up, with the final stage absorbing any residual one-cent difference so that every line satisfies the identity `list_cents` minus `amendment_discount_cents` minus `plan_discount_cents` minus `tier_discount_cents` minus `credit_applied_cents` equals `net_due_cents`. One exception exists upstream of invoicing: the marketplace contribution inside the true-up shortfall computation truncates each record's weighted value down to integer cents (floor) before summation.

### 2.6. Validation Order and Error Precedence

When several checks apply to one request, they are evaluated in a fixed priority order, and the first failure determines the rejection. Authentication (missing or unknown headers, `ERR_UNAUTHENTICATED`, 401) comes first, then authorization (`ERR_FORBIDDEN`, 403), then existence of every referenced id — validated left-to-right across path and body identifiers such as `org_id`, `linked_account_id`, `agreement_id`, `plan_id`, `invoice_id`, `grant_id`, and `trueup_id` (`ERR_NOT_FOUND`, 404). Only after those three gates does the server examine whether the target resource's current state permits the transition (`ERR_INVALID_STATE_TRANSITION`, 409), then cross-entity state gates such as suspended accounts and non-active agreements (409), then temporal-window checks (422), then referential coverage of service families (422), then structural constraints such as tier ordering, duplicate usage, and capacity quotas (422), and only then fiscal checks such as commitment ceilings and settlement amounts (422). Term-end gates — true-up assessment before expiry (`ERR_TERM_NOT_ENDED`, 409) and insufficient forecast windows (`ERR_FORECAST_WINDOW_INSUFFICIENT`, 409) — are evaluated last. This ordering is observable: a request that violates both a state gate and a fiscal ceiling must surface the state-gate error.

### 2.7. Optimistic Concurrency Control

One write endpoint participates in optimistic concurrency control: creating a private pricing amendment. The request must carry `expected_agreement_version`, holding the value of the target agreement's `version` as last observed by the caller. If the agreement's `version` has since advanced — because another writer suspended, resumed, or terminated the agreement, added a tier, or created a prior amendment — the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), preventing the caller from writing pricing terms against an agreement it has not observed. No other endpoint takes a version field.

### 2.8. Consolidated Billing and Org-Wide Sharing

A `BillingOrganization` is the payer root; `LinkedAccount` resources belong to it through `org_id`, and usage flows upward. Commitments and credits are shared at the organization level: plan coverage within a single hour pools the post-amendment usage of the plan's family across all of the org's linked accounts, credit grants debit against any invoice of the org regardless of which account consumed the usage, and the fiscal ceilings on plans (`max_hourly_commitment_cents`, `capacity_quota_units`) are org-wide aggregates. The organization also tracks `current_period_index`, a logical billing-period counter that starts at 0 and advances by 1 each time a period close runs; usage records capture `period_index` at ingest, and invoices are generated for a specific period.

### 2.9. Derived Balances and Invariants

Two quantities are always recomputed from their sources rather than stored independently. On the organization, `unapplied_credit_cents` is the sum of `remaining_cents` over all of the org's credit grants whose status is either `ISSUED` or `DEPLETING`; it is recomputed whenever a grant is issued, debited, exhausted, expired, or revoked. On the agreement, `accrued_trueup_cents` is the sum of `amount_cents` over all true-up charges of the agreement whose status is anything other than `WAIVED`; it is recomputed whenever a charge is created, billed, or waived. Credit grants obey a strict conservation invariant at all times: for every grant, `amount_cents` equals `consumed_cents` plus `remaining_cents` plus `forfeited_cents`, so `remaining_cents` is always the original amount less what has been consumed less what has been forfeited.

### 2.10. Status Codes

Creation of a new resource returns 201; modifications of an existing resource return 200. One endpoint behaves dual-mode: assessing a term-end shortfall returns 201 with the created charge when the shortfall is positive, but 200 with `data` null when the shortfall is exactly zero (including the boundary where consumed spend equals the commitment) — no zero-amount charge is ever created.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Payer: Organizations and Linked Accounts

A `PlatformBillingOperator` begins by creating a billing organization, supplying its display `name`, an ISO `currency` code that defaults to `USD` when omitted, and two org-wide guardrails: `max_hourly_commitment_cents`, a ceiling on the combined hourly commitment across all of the org's currently `ACTIVE` plans, and `capacity_quota_units`, a per-instance-family cap on reserved units that may overlap at any instant. The organization is born with `current_period_index` at 0 and `unapplied_credit_cents` at 0.

Under the organization, an `OrgAdmin` registers linked accounts with a `name` and an `external_ref`. Each account starts `ACTIVE`. Suspension moves an account from `ACTIVE` to `SUSPENDED`, blocking further usage ingest for that account with `ERR_ACCOUNT_SUSPENDED` (HTTP 409); reactivation returns it from `SUSPENDED` to `ACTIVE`. Both transitions increment the account's `version` by 1 and refresh `updated_at`.

### 3.2. Negotiating and Activating an Enterprise Agreement

An `OrgAdmin` drafts an `EnterpriseAgreement` with `committed_spend_cents` — the total eligible spend the customer commits over the whole term — and a half-open term window from `term_start` (inclusive) to `term_end` (exclusive), where `term_end` must be strictly later than `term_start`. A new agreement has `lifecycle_status` `NEGOTIATION`, `renewal_status` `NONE`, `consumed_commitment_cents` 0, and `accrued_trueup_cents` 0.

The agreement carries two parallel state dimensions. Lifecycle runs `NEGOTIATION → ACTIVE → SUSPENDED → ACTIVE → …` and ends at `EXPIRED` or `TERMINATED`. Renewal runs independently — `NONE → RENEWAL_REVIEW → RENEWED` or `NONE → RENEWAL_REVIEW → ABANDONED` — and every renewal transition requires the lifecycle to be `ACTIVE`, otherwise the call fails with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). Lifecycle transitions never touch the renewal axis, with a single exception: terminating an agreement that sits in `RENEWAL_REVIEW` forces its renewal status back to `NONE`.

Activation — moving `NEGOTIATION` to `ACTIVE` — is guarded by three checks. The logical clock must fall within the term (at or after `term_start` and before `term_end`), else `ERR_AMENDMENT_OUT_OF_TERM` (HTTP 422). At least one discount tier must exist for the agreement, else `ERR_SERVICE_FAMILY_NOT_COVERED` (HTTP 422). And no other agreement of the same organization may already be `ACTIVE`, else `ERR_ORG_HAS_ACTIVE_AGREEMENT` (HTTP 409). Suspending moves `ACTIVE` to `SUSPENDED` with no preconditions; resuming moves `SUSPENDED` back to `ACTIVE` but repeats the no-other-active-agreement check with the same error. Every lifecycle transition increments the agreement's `version` by 1.

### 3.3. Tiered Discount Schedules and Private Pricing Amendments

Discount tiers attach marginal discount rates to brackets of cumulative commitment consumption. Each tier row names an `agreement_id`, a `service_family` (for example COMPUTE, STORAGE, or DATABASE), a `threshold_cents` at which the bracket begins — inclusive, so consumption exactly equal to the threshold already qualifies for the higher bracket — and a `rate`, a marginal discount rate of at least 0 and strictly less than 1 applied inside that bracket. Within one agreement and one service family, thresholds must be strictly increasing: adding a tier whose `threshold_cents` is not strictly greater than every existing threshold for that family on that agreement is rejected with `ERR_TIER_THRESHOLD_NOT_INCREASING` (HTTP 422). Adding a tier bumps the agreement's `version` by 1.

A `FinanceAnalyst` layers private pricing onto specific service families by creating a `PricingAmendment` with a `discount_rate` (at least 0, strictly less than 1) and a half-open effective window `effective_from` (inclusive) to `effective_to` (exclusive). Amendments are allowed while the agreement is `ACTIVE` or `SUSPENDED`. The window must lie entirely within the agreement's term — an amendment whose window falls outside it is rejected with `ERR_AMENDMENT_OUT_OF_TERM`. Two amendments on the same agreement and the same service family may not overlap under half-open semantics; adjacency, where one amendment's `effective_to` equals the other's `effective_from`, is explicitly not an overlap. A violating create is rejected with `ERR_AMENDMENT_WINDOW_OVERLAP` (HTTP 422). The amendment's service family must also be covered by at least one discount tier of the agreement, else `ERR_SERVICE_FAMILY_NOT_COVERED`. Because amendments reshape pricing terms, the create is OCC-guarded as described in §2.7 via `expected_agreement_version`, and a successful create increments the agreement's `version` by 1 — which in turn invalidates any other writer's captured version.

### 3.4. Purchasing and Terminating Commitment Plans

Commitment plans come in two `type` variants: `SAVINGS_PLAN` and `RESERVED_CAPACITY`. A purchase names the `org_id`, the `agreement_id` it is scoped to, an `instance_family`, a `units` count, an `hourly_commitment_cents` of at least 1, a `plan_discount_rate` of at least 0 and strictly less than 1, and a half-open term window whose `term_end` must be strictly later than `term_start`. The units discipline differs by type: a savings plan must carry `units` exactly 0, while a reserved capacity plan requires `units` of at least 1; mixing these up fails with `ERR_INVALID_REQUEST` (HTTP 400).

Purchase is gated by a chain of checks evaluated in the global priority order. The scoped agreement's lifecycle gates first: if the agreement is `SUSPENDED` the purchase fails with `ERR_AGREEMENT_SUSPENDED` (HTTP 409), and if it is in any other non-`ACTIVE` state (`NEGOTIATION`, `EXPIRED`, or `TERMINATED`) it fails with `ERR_AGREEMENT_NOT_ACTIVE`. This state check precedes the fiscal checks. For reserved capacity plans, the structural quota applies: the sum of `units` over the org's `ACTIVE` reserved-capacity plans of the same `instance_family` whose term windows intersect the new plan's window, plus the new plan's `units`, must not exceed the org's `capacity_quota_units`, else `ERR_CAPACITY_QUOTA_EXCEEDED` (HTTP 422). Finally, the fiscal ceiling: the sum of `hourly_commitment_cents` over the org's `ACTIVE` plans plus the new plan's commitment must not exceed `max_hourly_commitment_cents`, else `ERR_COMMITMENT_CEILING_EXCEEDED` (HTTP 422). A plan is created `ACTIVE`.

A plan leaves `ACTIVE` in three ways. When the logical clock reaches its `term_end`, a period close moves it to `EXPIRED`. An `OrgAdmin` may terminate it early, but only while the org has no invoice in `DRAFT` — terminating against an open draft is rejected with `ERR_INVOICE_DRAFT_BLOCKS_TERMINATION` (HTTP 409). And when the scoped agreement is terminated, every `ACTIVE` plan of that agreement is cascade-terminated. Both early-termination paths — manual and cascade — spawn an `EARLY_TERMINATION` true-up charge in `ASSESSED` status with the charge's `plan_id` pointing at the terminated plan, and then recompute the scoped agreement's `accrued_trueup_cents`. The penalty amount is half of the remaining hourly commitment over the remaining hours: take the whole hours between the logical clock and the plan's `term_end` (zero if the clock has already passed `term_end`), multiply by `hourly_commitment_cents`, multiply by one half, and round half-up to integer cents. Each termination increments the plan's `version` by 1.

A plan's coverage can be inspected as a computed read over a window. Two modes exist. The `ACTUAL` mode replays real usage chronologically hour by hour, ordered by `usage_hour_start` ascending with ties broken by account creation order; within each hour the plan's remaining budget is exactly `hourly_commitment_cents`, and post-amendment usage of the plan's `instance_family` across all of the org's linked accounts is covered in account `created_at` ascending order until the hourly budget is exhausted, so the covered amount is the sum over hours of the smaller of that hour's family usage and the hourly commitment. The `PROJECTED` mode is a purchase-time what-if that assumes full utilization: the covered amount is simply `hourly_commitment_cents` multiplied by the number of hours in the window. The two diverge precisely when any hour is under-utilized. The read accepts optional `mode`, `window_start`, and `window_end` parameters and reports `covered_cents`, the `mode` used, and `window_hours`.

### 3.5. Usage Ingestion

Usage arrives one hour at a time. An ingest call carries `linked_account_id`, `service_family`, `usage_hour_start`, `list_price_cents` of at least 0, and an optional `is_marketplace` flag defaulting to false, marking marketplace purchases that count toward commitment under negotiated weighting. The `usage_hour_start` must be aligned to the hour — minute and second both zero — otherwise the record is rejected with `ERR_INVALID_REQUEST`. The target account must be `ACTIVE`; ingesting against a `SUSPENDED` account fails with `ERR_ACCOUNT_SUSPENDED`. At most one record may exist per account, service family, and hour; a second record for the same triple is rejected with `ERR_DUPLICATE_USAGE_RECORD` (HTTP 422). A `LinkedAccountManager` may ingest only for its own account as described in §2.1.

On ingest the record is stamped with the org's identity — `org_id` is denormalized from the linked account — and the org's `current_period_index` at that moment becomes the record's `period_index`. The record starts `INGESTED` with `invoice_id` null. Whether the usage is eligible to consume commitment depends on coverage: usage counts toward the agreement's commitment only if its service family is covered by at least one discount tier of the org's agreement; ineligible usage is still ingested normally, it simply never accrues toward the commitment.

### 3.6. Invoice Generation and the Four-Stage Discount Waterfall

Invoice generation bills one organization for one period. The caller supplies `org_id` and `period_index`; a period that is already covered by a non-`VOIDED` invoice of the org is rejected with `ERR_INVOICE_PERIOD_ALREADY_BILLED` (HTTP 422). Generation selects the org's unique `ACTIVE` agreement at that moment and records it on the invoice as `agreement_id`, or null if the org has none. Every `INGESTED` usage record of the org whose `period_index` matches the invoice's period is swept in, and one invoice line is produced per linked-account-by-service-family combination present in that usage. Each swept record transitions from `INGESTED` to `BILLED` with its `invoice_id` set to the new invoice. The invoice is born `DRAFT`.

Each line is priced by a pinned, non-commutative four-stage waterfall.

Stage 1 — private pricing. If the invoice has an agreement and a `PricingAmendment` of that agreement covers the record's `service_family` with the record's `usage_hour_start` inside the amendment's half-open window, the line base is the list price reduced by the amendment's `discount_rate`; otherwise the list price carries through untouched. The line's `list_cents` records the pre-discount value and `amendment_discount_cents` the stage-1 discount.

Stage 2 — plan coverage. The `ACTUAL` chronological coverage of §3.4 determines how much of the post-amendment amount is covered by the org's `ACTIVE` plans whose term windows cover the usage hour; the covered portion is discounted at the plan's `plan_discount_rate`. The line records `plan_covered_cents` and `plan_discount_cents`.

Stage 3 — tiered agreement discount. For invoices with a non-null `agreement_id`, the post-stage-2 remainder earns the marginal tier discount of §3.3, computed per service family against the agreement's cumulative `consumed_commitment_cents`. Lines are processed in a fixed order — the linked account's `created_at` ascending, then `service_family` ascending — and the running cumulative consumption at the start of each line defines which brackets the line's amount flows through. The discount is the sum over brackets of the bracket's `rate` times the overlap between the line's consumption span and the bracket's half-open span from its `threshold_cents` up to the next tier's threshold, where the highest tier's bracket extends without bound. If the agreement has no tier for the line's family, the stage contributes zero. The line records `tier_discount_cents`.

Stage 4 — credits. The post-stage-3 remainders of all lines form a credit pool, allocated against the org's usable grants as described in §3.7; the line records `credit_applied_cents` as computed at generation, though the grants are only actually debited at finalize.

Rounding follows §2.5: full precision through the stages, each stage's stored cent field rounded half-up with the final stage absorbing any residual, and the line's `net_due_cents` rounded half-up once. The invoice aggregates its lines into `total_list_cents`, `total_amendment_discount_cents`, `total_plan_discount_cents`, `total_tier_discount_cents`, `total_credit_applied_cents`, and `total_due_cents`, each the sum of the corresponding line field — with `total_due_cents` summing the already-rounded line values. Generation also advances the agreement's `consumed_commitment_cents` by the period's eligible spend, using the pass-1 marketplace weighting of §3.8.

### 3.7. Credit Grants: Issuance, Consumption, Forfeiture

A `PlatformBillingOperator` issues a `CreditGrant` to an organization with an `amount_cents` of at least 1 and an `expires_at` instant (exclusive). New grants start `ISSUED` with `consumed_cents` and `forfeited_cents` at 0, and issuance immediately recomputes the org's `unapplied_credit_cents`.

The candidate pool for invoice stage 4 is the org's grants in `ISSUED` or `DEPLETING` status whose `expires_at` is strictly after the logical clock. Grants are walked in `expires_at` ascending order with ties broken by `created_at` ascending, each debited by the smaller of its `remaining_cents` and the outstanding pool, until the pool is exhausted. The debit happens at finalize, not at generation: when a `DRAFT` invoice is finalized, the cascade debits each grant in that order; a grant debited down to exactly zero remaining moves to `EXHAUSTED` (whether from `ISSUED` or `DEPLETING`), a partially debited `ISSUED` grant moves to `DEPLETING`, and every such transition recomputes `unapplied_credit_cents`. Finalization has one cross-entity gate: if the invoice's `agreement_id` is non-null, that agreement's lifecycle must be `ACTIVE` or `EXPIRED`; finalizing against an agreement in any other lifecycle state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`.

Grants die three ways, all forfeiting whatever remains. A period close that finds the clock at or past `expires_at` moves an `ISSUED` or `DEPLETING` grant to `EXPIRED`, setting `forfeited_cents` to the entire `remaining_cents` and leaving `consumed_cents` untouched, so `remaining_cents` recomputes to zero. A `PlatformBillingOperator` may revoke an `ISSUED` or `DEPLETING` grant, with the same forfeiture bookkeeping and a `version` bump. And consumption itself can drive a grant to `EXHAUSTED`. Once a grant reaches any terminal state — `EXHAUSTED`, `EXPIRED`, or `REVOKED` — any further revoke or consume attempt against it is rejected with `ERR_CREDIT_NOT_USABLE` (HTTP 409).

### 3.8. Term End: Period Close, Expiry, and True-Up

A period close is the system's batch heartbeat. When the operator runs it for an organization, `current_period_index` advances by exactly 1, and three expiry sweeps fire against the logical clock: every credit grant in `ISSUED` or `DEPLETING` whose `expires_at` has been reached moves to `EXPIRED` under the forfeiture bookkeeping of §3.7; every `ACTIVE` commitment plan whose `term_end` has been reached moves to `EXPIRED`; and every agreement whose lifecycle is `ACTIVE` and whose `term_end` has been reached moves to `EXPIRED`. The org's `unapplied_credit_cents` is then recomputed.

Only an `EXPIRED` agreement may be assessed for a shortfall; assessing earlier fails with `ERR_TERM_NOT_ENDED` (HTTP 409). The shortfall computation is a two-pass weighting of marketplace purchases, and its evaluation order is pinned. Pass 1 computes consumed spend as the sum of `list_price_cents` over eligible non-marketplace usage in the agreement's covered families across the term, plus half of the marketplace `list_price_cents` — the base marketplace weight is one half, and each marketplace record's weighted contribution is truncated down to integer cents before summation. Tier selection then finds the highest discount tier anywhere on the agreement whose `threshold_cents` is at or below the pass-1 consumed value, again with the inclusive boundary. Pass 2 re-weights marketplace: if the selected tier is the agreement's highest-threshold tier, marketplace usage counts at full weight; otherwise it stays at the base half weight. The shortfall is the amount by which `committed_spend_cents` exceeds the pass-2 consumed value, floored at zero. When the shortfall is zero — including the boundary where pass-2 consumption exactly equals the commitment — no charge is created at all and the assess call answers 200 with null data; a positive shortfall yields a `SHORTFALL` charge in `ASSESSED` status with null `plan_id`, returned with 201, and the agreement's `accrued_trueup_cents` is recomputed.

True-up charges have their own small lifecycle under a segregation-of-duties split. An `ASSESSED` charge may be billed by an `OrgAdmin`, moving it to `BILLED`, or waived by a `FinanceAnalyst` — who supplies a `reason` — moving it to `WAIVED`; both transitions recompute `accrued_trueup_cents`, and waived charges drop out of that sum. When an invoice of the org's agreement is settled, every `BILLED` charge of that agreement moves to `SETTLED`. Waived and settled are terminal.

### 3.9. Invoice Settlement, Disputes, and Voiding

After finalize, an invoice may be disputed and resolved — `FINALIZED` to `DISPUTED` with a `reason`, then back to `FINALIZED` — a cycle that may repeat and increments the invoice's `version` each time. Settlement moves `FINALIZED` to `SETTLED` and is exact-amount: the request's `amount_cents` must equal the invoice's `total_due_cents` to the cent, otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH` (HTTP 422). A successful settle cascades to the agreement's `BILLED` true-up charges as described in §3.8. A `DRAFT` invoice may instead be voided, moving it to `VOIDED`; voiding releases every usage record billed into it back to `INGESTED` with `invoice_id` cleared to null, which makes the period billable again.

### 3.10. Renewal Review and Forecasting

Renewal is a negotiation aid, not a lifecycle event. A `FinanceAnalyst` opens a renewal review on an `ACTIVE` agreement, moving the renewal axis from `NONE` to `RENEWAL_REVIEW`, and later closes it with an `outcome` of either `RENEWED` or `ABANDONED`. All three renewal transitions require lifecycle `ACTIVE` and fail otherwise with `ERR_AGREEMENT_NOT_ACTIVE`; `RENEWED` and `ABANDONED` are terminal for the renewal axis.

Forecasts quantify next-term eligible spend from closed-period history. A forecast names an `agreement_id`, a `variant` of `LINEAR` or `COHORT_WEIGHTED`, and an optional `window_periods` defaulting to 3 and required to be at least 3. Let U be the org's total eligible list spend per closed period — a period counts as closed when its index is below the org's `current_period_index` and it contains usage — taking the most recent window of W periods with U of index 1 the most recent. The `LINEAR` variant extrapolates average period-over-period growth from the window's endpoints: the forecast is the most recent period's spend plus the mean of the consecutive deltas, which equals the most recent spend plus the difference between the most recent and the oldest period in the window divided by one less than the window size. The `COHORT_WEIGHTED` variant pins the window to 3 periods and ignores trend in favor of recency-weighted level: half of the most recent period's spend, plus three tenths of the period before it, plus one fifth of the period before that. Both variants round half-up to integer cents. If fewer closed periods with usage exist than the requested window requires, generation is rejected with `ERR_FORECAST_WINDOW_INSUFFICIENT` (HTTP 409). The resulting `RenewalForecast` records the computed `forecast_cents` and the `generated_period_index` — the org's `current_period_index` at generation time.

### 3.11. Termination of an Agreement and Its Cascade

Terminating an agreement — allowed from either `ACTIVE` or `SUSPENDED` — is the most far-reaching write in the system and proceeds in a fixed cascade order. First, every commitment plan scoped to the agreement that is still `ACTIVE` moves to `TERMINATED`. Second, each plan terminated in the first step spawns an `EARLY_TERMINATION` true-up charge in `ASSESSED` status, with `plan_id` set and the penalty amount computed per the early-termination rule of §3.4. Third, the agreement's `accrued_trueup_cents` is recomputed over the now-larger set of non-waived charges. If the agreement was sitting in `RENEWAL_REVIEW`, its renewal status is forced back to `NONE`. The agreement's own `version` increments by 1, as does each terminated plan's. Agreement termination is terminal: an agreement in `EXPIRED` or `TERMINATED` accepts no further lifecycle transitions, and any attempted transition from a terminal state — here or on any other entity — is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), as are repeated non-idempotent actions such as suspending an already-suspended account.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creating a new resource returns 201; modifying an existing resource returns 200; reads return 200. The shortfall-assess endpoint is dual-mode as described in §3.8: 201 with the created charge when the shortfall is positive, 200 with null data when it is zero.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock to a supplied instant | PlatformBillingOperator |
| POST | /api/billing-orgs | Create a billing organization | PlatformBillingOperator |
| GET | /api/billing-orgs/{id} | Fetch one billing organization | PlatformBillingOperator, OrgAdmin, FinanceAnalyst |
| GET | /api/billing-orgs | List billing organizations | PlatformBillingOperator, OrgAdmin, FinanceAnalyst |
| POST | /api/billing-orgs/{id}/run-period-close | Advance the period counter and run expiry sweeps | PlatformBillingOperator |
| POST | /api/linked-accounts | Create a linked account | OrgAdmin |
| GET | /api/linked-accounts/{id} | Fetch one linked account | OrgAdmin, FinanceAnalyst, LinkedAccountManager, PlatformBillingOperator |
| GET | /api/linked-accounts | List linked accounts, optionally by org | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/linked-accounts/{id}/suspend | Suspend a linked account | OrgAdmin |
| POST | /api/linked-accounts/{id}/reactivate | Reactivate a suspended account | OrgAdmin |
| POST | /api/enterprise-agreements | Create an agreement in NEGOTIATION | OrgAdmin |
| GET | /api/enterprise-agreements/{id} | Fetch one agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/enterprise-agreements | List agreements, optionally by org | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/enterprise-agreements/{id}/activate | Activate an agreement | OrgAdmin |
| POST | /api/enterprise-agreements/{id}/suspend | Suspend an active agreement | OrgAdmin |
| POST | /api/enterprise-agreements/{id}/resume | Resume a suspended agreement | OrgAdmin |
| POST | /api/enterprise-agreements/{id}/terminate | Terminate an agreement and cascade to plans | OrgAdmin |
| POST | /api/enterprise-agreements/{id}/open-renewal-review | Open renewal review | FinanceAnalyst |
| POST | /api/enterprise-agreements/{id}/close-renewal-review | Close renewal review with an outcome | FinanceAnalyst |
| POST | /api/discount-tiers | Add a tier row to an agreement | OrgAdmin |
| GET | /api/discount-tiers/{id} | Fetch one discount tier | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/discount-tiers | List tiers, optionally by agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/pricing-amendments | Create a private pricing amendment (OCC-guarded) | FinanceAnalyst |
| GET | /api/pricing-amendments/{id} | Fetch one amendment | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/pricing-amendments | List amendments, optionally by agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/commitment-plans | Purchase a savings plan or reserved capacity | OrgAdmin |
| GET | /api/commitment-plans/{id} | Fetch one plan | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/commitment-plans | List plans, optionally by org or agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/commitment-plans/{id}/terminate | Terminate a plan early | OrgAdmin |
| GET | /api/commitment-plans/{id}/coverage | Computed plan coverage over a window | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/usage-records | Ingest one hour of usage | LinkedAccountManager, PlatformBillingOperator |
| GET | /api/usage-records/{id} | Fetch one usage record | OrgAdmin, FinanceAnalyst, LinkedAccountManager, PlatformBillingOperator |
| GET | /api/usage-records | List usage records, optionally filtered | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/credit-grants | Issue a credit grant | PlatformBillingOperator |
| GET | /api/credit-grants/{id} | Fetch one credit grant | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/credit-grants | List credit grants, optionally by org | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/credit-grants/{id}/revoke | Revoke a grant and forfeit its remainder | PlatformBillingOperator |
| POST | /api/invoices/generate | Generate a draft invoice for an org and period | OrgAdmin |
| GET | /api/invoices/{id} | Fetch one invoice | OrgAdmin, FinanceAnalyst, LinkedAccountManager, PlatformBillingOperator |
| GET | /api/invoices | List invoices, optionally by org or agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/invoices/{id}/lines | List the computed lines of an invoice | OrgAdmin, FinanceAnalyst, LinkedAccountManager, PlatformBillingOperator |
| GET | /api/invoice-lines/{id} | Fetch one invoice line | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/invoice-lines | List invoice lines, optionally filtered | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/invoices/{id}/finalize | Finalize a draft invoice and debit credits | OrgAdmin |
| POST | /api/invoices/{id}/dispute | Dispute a finalized invoice | OrgAdmin |
| POST | /api/invoices/{id}/resolve-dispute | Resolve a dispute back to finalized | OrgAdmin |
| POST | /api/invoices/{id}/settle | Settle a finalized invoice for its exact total | OrgAdmin |
| POST | /api/invoices/{id}/void | Void a draft invoice and release its usage | OrgAdmin |
| POST | /api/true-up-charges/assess | Assess the term-end shortfall for an expired agreement | OrgAdmin |
| GET | /api/true-up-charges/{id} | Fetch one true-up charge | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/true-up-charges | List true-up charges, optionally by agreement or plan | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| POST | /api/true-up-charges/{id}/bill | Bill an assessed true-up charge | OrgAdmin |
| POST | /api/true-up-charges/{id}/waive | Waive an assessed true-up charge | FinanceAnalyst |
| POST | /api/renewal-forecasts | Generate a renewal forecast | FinanceAnalyst |
| GET | /api/renewal-forecasts/{id} | Fetch one renewal forecast | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |
| GET | /api/renewal-forecasts | List renewal forecasts, optionally by agreement | OrgAdmin, FinanceAnalyst, PlatformBillingOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_AGREEMENT_SUSPENDED | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_ORG_HAS_ACTIVE_AGREEMENT | 409 |
| ERR_AMENDMENT_OUT_OF_TERM | 422 |
| ERR_AMENDMENT_WINDOW_OVERLAP | 422 |
| ERR_SERVICE_FAMILY_NOT_COVERED | 422 |
| ERR_TIER_THRESHOLD_NOT_INCREASING | 422 |
| ERR_DUPLICATE_USAGE_RECORD | 422 |
| ERR_CAPACITY_QUOTA_EXCEEDED | 422 |
| ERR_INVOICE_PERIOD_ALREADY_BILLED | 422 |
| ERR_INVOICE_DRAFT_BLOCKS_TERMINATION | 409 |
| ERR_COMMITMENT_CEILING_EXCEEDED | 422 |
| ERR_SETTLEMENT_AMOUNT_MISMATCH | 422 |
| ERR_TERM_NOT_ENDED | 409 |
| ERR_FORECAST_WINDOW_INSUFFICIENT | 409 |
| ERR_STALE_AGREEMENT_VERSION | 412 |
| ERR_CREDIT_NOT_USABLE | 409 |
