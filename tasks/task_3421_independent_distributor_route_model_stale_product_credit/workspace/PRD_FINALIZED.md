# Independent Distributor Route Model API — Product Requirements Document

## 1. Introduction

Independent bakery distribution runs on a franchise-like economic loop: the company sells exclusive territory routes to independent distributors, who buy product from the company bakery at a discount off catalog list price and resell it to retail accounts, keeping the margin as their compensation. Because fresh baked goods perish within days and demand must be forecast daily, the model lives or dies on a small set of tense trade-offs — distributors carry return risk only inside narrow stale-credit windows, the company polices shelf-level service standards through scored audits, and the territory itself is a financed asset that must be valued, repurchased, and resold as distributors come and go.

This document specifies the API that operates that loop end to end. It governs territory listing and route agreement formation, financing of the territory purchase by the company or an external lender, daily order forecasting against bakery production capacity, delivery self-reporting and company reconciliation against a running trade ledger, retail service audits with a strike-based suspension mechanism, stale product claims governed by a weekly credit cap, classification disputes over independent-contractor status, and the full exit pipeline from repurchase valuation through transfer settlement and back to territory resale. All endpoints are mounted at the service root.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the caller and `X-User-Role` naming the caller's operational capacity. Four roles exist, spelled exactly as follows: `CompanyAdmin`, `RouteOpsManager`, `CreditAnalyst`, and `Distributor`. A request missing either header, or carrying a role string other than these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not among the roles authorized for the targeted operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); this includes the segregation-of-duties boundary between route operations and the credit desk, under which a `CreditAnalyst` may not decide stale claims and a `RouteOpsManager` may not issue credits.

Identity semantics differ by role. When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting `Distributor` entity; ownership checks on any resource that references a distributor — the path distributor id, or the owning distributor of the addressed order, claim, or financing plan — compare that foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `CompanyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies individually to `RouteOpsManager` and to `CreditAnalyst`: for each of them, `X-User-ID` is an operator identifier with no entity backing and no ownership comparison.

One further role restriction is evaluated at the same stage as ownership scoping: resolving a classification-dispute suspension is reserved to `CompanyAdmin`, and a `RouteOpsManager` attempting that resolution is rejected with `ERR_REINSTATE_FORBIDDEN` (HTTP 403).

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

List endpoints accept `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server never reads wall-clock time. It maintains a logical clock that starts fixed at `2026-09-01T00:00:00Z` and never falls back to wall-clock time; every date comparison in this document — order lead times, claim windows, delinquency evaluation, valuation year counts, auto-expiry — reads this clock. A `CompanyAdmin` may move the clock through the test-driving capability that accepts a `current_utc` timestamp and echoes the accepted `current_utc` back to the caller.

### 2.5. Common Resource Properties

Every resource in the system — Bakery, Territory, Distributor, RouteAgreement, FinancingPlan, RetailAccount, ProductionDay, DailyOrder, StaleReturnClaim, and TerritoryTransfer — carries four system-managed fields:

- `id` (string): a unique, server-minted UUID rendered in its canonical hyphenated string form (for example, `550e8400-e29b-41d4-a716-446655440000`), with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at` (string): the same timestamp format, refreshed upon any change to the resource's properties.
- `version` (integer): increments by one on every mutation of the resource — including mutations performed as side effects of operations on other resources, such as a territory's `version` advancing when an agreement is created against it, or a distributor's `version` advancing when the trade ledger moves.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts are represented as integer cents. Wherever a computed amount is not already a whole number of cents, it is rounded half-up to whole cents. Rounding order is pinned wherever per-line or per-item multiplication is involved: each line-level or item-level amount is rounded to whole cents first, and only then are the rounded amounts summed; summing unrounded amounts and rounding once at the end is a different, forbidden order. Composite audit scores are likewise integers rounded half-up. Configuration-style numeric inputs such as `discount_pct` and `annual_interest_rate` are decimals preserved at input precision.

### 2.7. Optimistic Concurrency Control

Exactly two write operations carry optimistic concurrency control; endpoints not named here take no version field at all.

Creating a financing plan against a route agreement requires the request to carry `expected_agreement_version`, the client's last observed `version` of that agreement. A successful plan creation legitimately supersedes any prior draft plan and advances the agreement's `version` by one, so a creation carrying a value that no longer equals the agreement's current `version` is acting on a superseded view of the agreement and is rejected with `ERR_STALE_VERSION` (HTTP 412).

Confirming a submitted order requires the request to carry `expected_production_day_version`, the client's last observed `version` of the relevant production day. Every successful confirmation or cancellation moves the day's `allocated_units` and advances its `version`, so a confirmation carrying a value that no longer equals the day's current `version` is acting on a stale capacity view and is rejected with `ERR_STALE_VERSION` (HTTP 412).

In the request evaluation order, the version check is performed immediately after state preconditions and before any business-rule checks.

### 2.8. Validation Pipeline Ordering

When several checks could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic. First, header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`). Third, distributor ownership scoping, and with it the classification-reinstate restriction (`ERR_NOT_RESOURCE_OWNER`, `ERR_REINSTATE_FORBIDDEN`). Fourth, existence of path identifiers, validated left to right (`ERR_NOT_FOUND`). Fifth, existence of foreign keys supplied in the request body, checked in the endpoint's declared input order — for agreement creation, `territory_id` first (`ERR_TERRITORY_NOT_FOUND`), then `distributor_id` (`ERR_DISTRIBUTOR_NOT_FOUND`), then `bakery_id` (`ERR_BAKERY_NOT_FOUND`). Sixth, request shape: required fields, enum membership, and ranges (`ERR_INVALID_REQUEST`, and `ERR_AUDIT_SCORE_RANGE` for audit scores outside the inclusive 0 to 100 range). Seventh, state preconditions (`ERR_INVALID_STATE_TRANSITION`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_TERRITORY_NOT_LISTED`, `ERR_PRODUCTION_DAY_LOCKED`, `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_FINANCING_NOT_DISBURSED`, `ERR_FINANCING_PLAN_EXISTS`). Eighth, the optimistic-concurrency version check (`ERR_STALE_VERSION`). Ninth, line- and item-level referential integrity (`ERR_SKU_UNKNOWN`, `ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE`). Tenth, temporal windows (`ERR_ORDER_LEAD_TIME`, `ERR_CLAIM_NOT_STALE_YET`, `ERR_CLAIM_WINDOW_EXPIRED`). Eleventh, uniqueness, interval-overlap, and capacity constraints (`ERR_PRODUCTION_DAY_EXISTS`, `ERR_DISTRIBUTOR_AGREEMENT_OVERLAP`, `ERR_CAPACITY_EXCEEDED`). Twelfth and last, fiscal limits (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_STALE_CAP_EXHAUSTED`, `ERR_PAYMENT_BELOW_INTEREST`).

### 2.9. The Distributor Trade Ledger and Account Standing

Each distributor carries a running trade ledger, `trade_balance_cents`, which starts at zero. Exactly three events move it: recording a delivery adds the order's computed charge; reconciling a delivered order subtracts the verified shortage credit; issuing an approved stale credit subtracts the issued amount. Every ledger movement also advances the distributor's `version`, refreshes `updated_at`, and triggers recomputation of `account_standing`. Standing is derived, never written by hand: it is `PROBATION` whenever the trade balance exceeds 80% of the distributor's `credit_limit_cents`; otherwise it is `WATCH` whenever any of the distributor's financing plans is `DELINQUENT`; otherwise it is `GOOD`. Because the ledger is a running all-time balance, the weekly settlement statement described in §3.4 reconciles it against a document view rebuilt from delivery charges, shortage credits, and issued stale credits.

### 2.10. Resource Addressing and Referential Retrieval

Paths that contain several resource identifiers are validated left to right: the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` before any later identifier is examined. Foreign keys supplied in request bodies are likewise validated in the endpoint's declared input order — agreement creation checks `territory_id`, then `distributor_id`, then `bakery_id`, surfacing `ERR_TERRITORY_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`, or `ERR_BAKERY_NOT_FOUND` respectively, each at HTTP 404.

## 3. Business Logic & Workflows

### 3.1. Territories, Distributors, and the Formation of a Route Agreement

A `CompanyAdmin` registers a bakery with a display `name`, a `daily_capacity_units` default of at least 1, and a fixed `product_catalog` whose entries each name a `sku`, a `display_name`, a `shelf_life_days` of at least 1, and a `list_price_cents` of at least 1; each `sku` must be unique within that catalog. Territories are registered separately with a human-readable `area_code` — unique across all territories regardless of status — and an asking `list_price_cents` of at least 1 cent. A new territory begins `AVAILABLE`; when a `CompanyAdmin` lists it for sale, it moves `AVAILABLE → LISTED`.

Distributor onboarding is likewise an administrative act: a `CompanyAdmin` creates the distributor with a `legal_name` and a `credit_limit_cents` of at least 1. The new distributor starts in `PROSPECT` status, with `classification_status` `INDEPENDENT_CONTRACTOR`, `account_standing` `GOOD`, and a zeroed `trade_balance_cents`.

With a listed territory and a prospect in place, a `RouteOpsManager` drafts the route agreement by supplying the `territory_id`, the `distributor_id`, and the `bakery_id` whose catalog and capacity will supply the route, together with the `purchase_price_cents` (at least 1), the `financed_amount_cents` (zero for a cash purchase, and never more than the purchase price — an excess is `ERR_INVALID_REQUEST`), the distributor's `discount_pct` off catalog list price (strictly greater than 0 and strictly less than 1), and the coverage interval `start_date` to `end_date`. The interval is half-open: it covers `start_date` and runs up to but does not include `end_date`, which must be strictly after `start_date`. The territory must be `LISTED`, or creation fails with `ERR_TERRITORY_NOT_LISTED`; on success the territory flips `LISTED → UNDER_AGREEMENT` and its `version` advances by one.

One distributor may hold several agreements, but their coverage intervals may not overlap while any of them is non-terminal — that is, in `DRAFT`, `ACTIVE`, `SUSPENDED_SERVICE`, `SUSPENDED_CLASSIFICATION`, or `EXITING`. Two intervals intersect when the existing one starts before the new one ends and the new one starts before the existing one ends; adjacency, where one interval's `end_date` equals the other's `start_date`, does not intersect and is allowed. A violating overlap is rejected with `ERR_DISTRIBUTOR_AGREEMENT_OVERLAP`. The new agreement begins in `DRAFT` with `strike_count` at zero, `suspension_reason` unset, and `activated_on` and `exited_on` both null. Agreements may be listed filtered by `territory_id`, `distributor_id`, `bakery_id`, or `status`.

Activation moves the agreement `DRAFT → ACTIVE` under a `RouteOpsManager`. When `financed_amount_cents` is greater than zero, activation is gated: an `ACTIVE` financing plan must already exist for the agreement, and its absence rejects the activation with `ERR_FINANCING_NOT_DISBURSED`. Activation stamps `activated_on` from the logical clock and promotes the distributor `PROSPECT → ACTIVE` — a no-op when the distributor is already `ACTIVE` through another agreement — advancing the distributor's `version` by one.

### 3.2. Financing the Territory Purchase

When a distributor finances any portion of the purchase price, a `CreditAnalyst` creates the financing plan against the draft agreement, naming the `financier_type` — `COMPANY` or `EXTERNAL_LENDER` — together with the `principal_cents`, the `annual_interest_rate` (a decimal strictly between 0 and 1, such as 0.10), and the `term_weeks` (at least 1). A `lender_name` is required exactly when the financier is an external lender and is forbidden for company financing; violating either direction is an `ERR_INVALID_REQUEST`. The `principal_cents` must equal the agreement's `financed_amount_cents`; a mismatch is likewise `ERR_INVALID_REQUEST`. The plan's `agreement_id` is taken from the creation path, and the request must additionally carry `expected_agreement_version` per §2.7. Only one live plan may exist: creation is rejected with `ERR_FINANCING_PLAN_EXISTS` when the agreement already holds a plan in any status other than `DRAFT` or `SUPERSEDED`. When a prior plan is still in `DRAFT`, the new plan supersedes it — the older plan moves `DRAFT → SUPERSEDED` — and the agreement's `version` advances by one. An agreement's plans may be listed filtered by `status`.

A plan is born in `DRAFT`. Disbursement by a `CreditAnalyst` requires the parent agreement to still be in `DRAFT`; disbursing against an agreement that has moved on is rejected with `ERR_INVALID_STATE_TRANSITION`. Disbursement stamps `disburse_date` with the current logical date, seeds `outstanding_principal_cents` equal to `principal_cents`, and computes the level-annuity `weekly_payment_cents`: first divide `annual_interest_rate` by 52 to obtain the weekly rate; then form the discount factor by adding one to the weekly rate, raising that sum to the power of negative `term_weeks`, and subtracting the result from one; the weekly payment is `principal_cents` multiplied by the weekly rate and divided by that discount factor, rounded half-up to whole cents. The plan is then `ACTIVE`.

Payments may be recorded by the owing `Distributor` or by a `CreditAnalyst` while the plan is `ACTIVE` or `DELINQUENT`, supplying an `amount_cents`; a distributor attempting to pay against another distributor's plan is rejected with `ERR_NOT_RESOURCE_OWNER`. Each payment applies interest-first: the interest portion is the outstanding principal multiplied by the weekly rate, rounded half-up to whole cents, and a payment smaller than that interest portion is rejected with `ERR_PAYMENT_BELOW_INTEREST`. Otherwise the principal portion is the lesser of the amount remaining after interest and the outstanding principal; the outstanding principal is reduced by that portion, `total_paid_cents` accumulates the full accepted amount, and when the outstanding principal reaches zero the plan becomes `PAID_OFF` — with the distributor's `account_standing` recomputed when the plan had been delinquent.

Delinquency is evaluated by the system, not by any user action: each time a production day closes (§3.3), every plan in `ACTIVE` or `DELINQUENT` is re-examined. The number of weeks elapsed is the whole-week count between `disburse_date` and the close date — the day difference divided by 7, rounded down. The scheduled amount due is the lesser of the weeks elapsed and `term_weeks`, multiplied by `weekly_payment_cents`. The plan is delinquent when `total_paid_cents` is strictly less than the scheduled due minus one weekly payment; that subtraction builds one weekly payment of grace into the test. A delinquent result moves the plan `ACTIVE → DELINQUENT`, or keeps a delinquent plan delinquent; a passing result cures `DELINQUENT → ACTIVE`, or keeps an active plan active. Either recomputation refreshes the distributor's `account_standing` and advances the distributor's `version`.

### 3.3. Production Planning and the Daily Order Pipeline

Bakery capacity is planned one date at a time. A `CompanyAdmin` opens a production day for a bakery by supplying a `date` and, optionally, `capacity_override_units`; the day's `capacity_units` takes the override when supplied and the bakery's `daily_capacity_units` otherwise, and the day's `bakery_id` is taken from the creation path. Only one production day may exist for a given bakery and date — a point-date uniqueness, not an interval — and a duplicate is rejected with `ERR_PRODUCTION_DAY_EXISTS`. The day opens in `PLANNING`; a bakery's days may be listed filtered by `status` or `date`. Each day exposes two load figures: `allocated_units`, the units reserved by confirmed orders for that date, and `forecast_units`, the sum of `units_total` across every order whose agreement uses this bakery, whose `delivery_date` falls on this date, and whose status is `DRAFT`, `SUBMITTED`, or `CONFIRMED` — so drafts feed the forecast even before they become firm.

A distributor builds demand as a draft order under its own id — recorded as the order's `distributor_id` — supplying a `delivery_date` and a non-empty `lines` array of `sku` and `qty` pairs, each `sku` unique within the order and each `qty` at least 1. Every `sku` must exist in the catalog of the agreement's bakery, or creation fails with `ERR_SKU_UNKNOWN`. The draft's `units_total` is the sum of its line quantities, and its `submitted_on` stays null while it remains a draft. Submission converts the forecast into a firm order (`DRAFT → SUBMITTED`, stamping `submitted_on` from the logical clock), and this is where the firm gates bite: the distributor must hold an `ACTIVE` agreement (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the `delivery_date` must fall at least two days after the current logical date (`ERR_ORDER_LEAD_TIME` otherwise), and the catalog sku check re-runs (`ERR_SKU_UNKNOWN`). A distributor's orders may be listed filtered by `status` or `delivery_date`.

Confirmation is the company's act: a `RouteOpsManager` confirms a submitted order against its production day. The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`); a production day must exist for the agreement's bakery on the order's `delivery_date` (`ERR_NOT_FOUND` when absent); the day must still be `PLANNING` (`ERR_PRODUCTION_DAY_LOCKED` once it is closed); and the day must have room — the day's `allocated_units` plus the order's `units_total` may not exceed `capacity_units`, though landing exactly at capacity is allowed (`ERR_CAPACITY_EXCEEDED` otherwise). The request carries `expected_production_day_version` per §2.7, and a value that no longer matches the day's current `version` is rejected with `ERR_STALE_VERSION`. On success the order becomes `CONFIRMED`, the day's `allocated_units` grows by the order's `units_total`, and the day's `version` advances by one.

A distributor may cancel an order while it is `SUBMITTED` or `CONFIRMED`; the order lands in `CANCELLED` with `cancelled_reason` `DISTRIBUTOR_CANCELLED`, and cancelling a confirmed order releases its reservation — the production day's `allocated_units` drops by the order's `units_total` and the day's `version` advances by one. `CANCELLED` and `RECONCILED` are the order's terminal states.

Closing is the ops-run checkpoint. Once the logical date has reached the production day's `date`, a `CompanyAdmin` closes it (`PLANNING → CLOSED`); attempting to close a future production date, or to close a day that is already closed, is rejected with `ERR_INVALID_STATE_TRANSITION`. The close is a system-wide checkpoint rather than a bookkeeping formality: it runs the financing delinquency and cure evaluation of §3.2 across every `ACTIVE` or `DELINQUENT` plan, and it auto-expires unanswered stale claims as described in §3.6.

### 3.4. Delivery, Reconciliation, and the Running Trade Ledger

Once the production day for the agreement's bakery and the order's `delivery_date` is `CLOSED`, the distributor records what was actually delivered by supplying `delivered_lines` — an array of `sku` and `qty` pairs covering exactly the order's line skus, no more and no fewer (`ERR_INVALID_REQUEST` otherwise). Recording delivery against a day that is not yet closed is rejected with `ERR_PRODUCTION_DAY_LOCKED`, since production has not been finalized, and the distributor's agreement must be `ACTIVE` at this point (`ERR_AGREEMENT_NOT_ACTIVE`). The delivered charge is then computed line by line: for each delivered line, multiply the delivered quantity by the catalog `list_price_cents` for that sku and by one minus the agreement's `discount_pct`, rounding the line charge half-up to whole cents; `total_charge_cents` is the sum of those rounded line charges. The rounding order is pinned — round each line first, then sum. With catalog prices of 319 and 157 cents, a `discount_pct` of 0.20, and quantities of 3 and 3, per-line rounding then summing yields 766 + 377 = 1143 cents; summing the raw amounts before rounding would yield 1142, and is forbidden.

Before the charge posts, the credit gate runs: the distributor's `trade_balance_cents` plus the new charge may not exceed `credit_limit_cents` — landing exactly at the limit is allowed — or the delivery is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On success the order becomes `DELIVERED`, the charge is added to the trade ledger, and the distributor's `version` and `account_standing` are refreshed. An order that never reaches delivery keeps `total_charge_cents` null.

Reconciliation is the company's counterweight, performed by a `RouteOpsManager` on a `DELIVERED` order. The supplied `verified_lines` must cover exactly the delivered skus, and each verified quantity may not exceed its delivered quantity (`ERR_INVALID_REQUEST` otherwise). For every line where the verified quantity falls short of the delivered quantity, a line shortage credit is that line's charge — as computed at delivery — multiplied by the shortfall and divided by the delivered quantity, rounded half-up to whole cents; `shortage_credit_cents` is the sum of those per-line credits. The credit is subtracted from the trade ledger, the distributor's `version` advances, and the order becomes `RECONCILED`. Until reconciliation, an order's `shortage_credit_cents` is zero.

Weekly settlement is a read-only statement that any of the four roles may request for a distributor — the `Distributor` role only for its own id — optionally parameterized by an ISO week string `week` of the form `YYYY-Www`, defaulting to the ISO week of the current logical date. The statement reports `gross_charges_cents`, the sum of `total_charge_cents` over the distributor's `DELIVERED` or `RECONCILED` orders whose recorded delivery date falls inside the week; `stale_credits_issued_cents`, the credits issued on claims submitted inside the week; and `net_trade_cents`, the gross charges minus those issued stale credits. It also reports the week's stale-cap figures `stale_cap_cents` and `stale_cap_used_cents`, computed per §3.6. The statement then places two views of the all-time position side by side: `ledger_view_cents` is the running `trade_balance_cents`, while `document_view_cents` rebuilds the position from documents — every delivered or reconciled order's charge, minus every reconciled order's shortage credit, minus every issued stale credit. The `reconciles` flag is true exactly when the two views agree, and the response also carries `trade_balance_cents` itself.

### 3.5. Retail Service Standards: Accounts, Audits, and the Strike Mechanism

Distribution agreements obligate the distributor to shelf-level service — stocking, rotation, and display execution — at each retail account. Either the owning distributor or a `RouteOpsManager` registers a retail account with a `store_name` and a non-empty `delivery_weekdays` array drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, and `SUN`; the account's `distributor_id` is taken from the creation path, and creation requires the distributor's agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise). Before any audit, the account's `compliance_score` and `last_audit_on` are null and its `audit_log` is empty.

Service audits are posted by a `RouteOpsManager` and carry an `audit_date` plus three component scores — `shelf_stock_score`, `rotation_score`, and `display_score` — each an integer from 0 to 100 inclusive; a score outside that range is rejected with `ERR_AUDIT_SCORE_RANGE`. The audit is appended to the account's `audit_log` together with its computed `composite_score` and `is_violation` flag. The composite is a weighted blend — 40% of shelf stocking, 30% of rotation, and 30% of display — rounded half-up to an integer. Violation is component-level, not composite-level: the audit is a violation when any single component score is strictly below 70. A score set of 69, 70, 70 composites to 70 yet is a violation; a set of exactly 70, 70, 70 sits at the threshold and is not a violation. The account's `compliance_score` always reflects the latest audit by `audit_date`, with ties broken toward the later-created audit entry, and `last_audit_on` tracks that date.

Each posted audit also recomputes the agreement's `strike_count`: the count of violation-flagged audit entries across all of the distributor's retail accounts under the `ACTIVE` agreement whose `audit_date` lies within the trailing ninety calendar days ending on — and including — the new audit's date. When the newly posted audit is itself a violation and the recomputed count has reached three, the agreement auto-suspends: `ACTIVE → SUSPENDED_SERVICE` with `suspension_reason` `SERVICE_DEFAULT`, firing the same future-order cancellation cascade as a manual suspension (§3.7). A count of exactly three triggers the suspension; two does not.

### 3.6. Stale Product Claims and the Weekly Credit Cap

Product that outlives its shelf life on the store shelf becomes a credit question. A distributor files a stale claim under its own id — recorded as the claim's `distributor_id` — as a non-empty `items` array, each item naming a `sku`, the `delivery_date` it arrived on, the `pulled_qty` removed from the shelf (at least 1), and the `pull_date` it was removed. Filing is blocked only while the distributor's agreement is `SUSPENDED_CLASSIFICATION`, `EXITING`, or `EXITED`; in those states the attempt is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. Each item is then validated on three axes. The sku must exist in the agreement bakery's catalog and have been delivered to this distributor (`ERR_SKU_UNKNOWN`). The claimed quantity may not exceed what was delivered to this distributor for that sku on that date — summed over the distributor's `DELIVERED` and `RECONCILED` orders — minus what has already been credited for the same sku and date on claims that are `APPROVED` or `CREDIT_ISSUED` (`ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE`). And the timing windows must hold: the `pull_date` must fall on or after the delivery date plus the sku's `shelf_life_days` — an earlier pull is not yet stale (`ERR_CLAIM_NOT_STALE_YET`) — while a `pull_date` later than the delivery date plus the shelf life plus seven days, or a claim submitted more than two days after the pull, is too late (`ERR_CLAIM_WINDOW_EXPIRED`). A distributor's claims may be listed filtered by `status`.

At filing, the claim lands in `SUBMITTED` with a `provisional_credit_cents` estimate. For each item, the unit charge is the catalog `list_price_cents` multiplied by one minus the agreement's `discount_pct`, rounded half-up to whole cents; the eligible quantity is the lesser of the pulled quantity and the not-yet-credited delivered quantity for that sku and date; each item's base is the eligible quantity multiplied by the unit charge and by three quarters — a stale credit rate of 0.75 — rounded half-up to whole cents; and the provisional credit is the sum of the item bases. The provisional figure is uncapped: the weekly cap described below does not apply at filing.

Review belongs to a `RouteOpsManager` and only while the claim is `SUBMITTED`; deciding a claim in any other state is rejected with `ERR_CLAIM_NOT_REVIEWABLE`. The reviewer supplies a `decision` — and may attach an optional `decision_note` — with three possible outcomes. `APPROVE` recomputes the uncapped credit on the claim's current items and freezes it as `approved_credit_cents`, moving the claim to `APPROVED`. `DENY` moves the claim to `DENIED` with `denial_reason` `DENIED_BY_REVIEW`. `REQUEST_INFO` parks the claim in `NEEDS_INFO`, from which the distributor resubmits with a corrected `items` payload; resubmission re-runs every submission validation — the timing windows, the eligibility ceiling, and the sku check — recomputes `provisional_credit_cents`, and returns the claim to `SUBMITTED`. Claims also die of old age: when a production day closes, every claim still sitting in `SUBMITTED` or `NEEDS_INFO` that was created more than three days before the close date is denied automatically with `denial_reason` `AUTO_EXPIRED`. `DENIED` and `CREDIT_ISSUED` are the claim's terminal states.

Issuing money is deliberately segregated from deciding: only a `CreditAnalyst` may issue credit on an `APPROVED` claim — a `RouteOpsManager` attempting it is refused with `ERR_FORBIDDEN_FOR_ROLE`, and a claim not in `APPROVED` rejects the issuance with `ERR_INVALID_STATE_TRANSITION`. Issuance applies the weekly cap. The relevant week is the ISO-8601 week containing the claim's submission date — the logical-clock date at submit. The cap is 10% of the distributor's gross delivered charges whose record-delivery date falls inside that week, rounded half-up to whole cents; the used amount is the sum of credits already issued on this distributor's claims submitted inside the same week; and the remaining cap is the difference. When the remaining cap is zero, issuance is rejected with `ERR_STALE_CAP_EXHAUSTED`; otherwise the issued amount is the lesser of `approved_credit_cents` and the remaining cap, and issuing exactly the remaining cap is allowed. The claim moves to `CREDIT_ISSUED` with `issued_credit_cents` recording what was actually paid and `cap_truncated_cents` recording the approved amount minus the issued amount, so a claim approved above the cap visibly issues for less than its provisional estimate. The issued credit is subtracted from the distributor's trade ledger, advancing `version` and recomputing `account_standing`.

### 3.7. Suspension, Classification Disputes, and Reinstatement

A `RouteOpsManager` may suspend an `ACTIVE` agreement for either of two reasons, supplied as `reason`. Suspending with `SERVICE_DEFAULT` moves the agreement to `SUSPENDED_SERVICE`, stamps `suspension_reason` accordingly, and cancels forward demand: every order of this distributor under this agreement that is still `SUBMITTED` or `CONFIRMED` and whose `delivery_date` falls on or after the current logical date moves to `CANCELLED` with `cancelled_reason` `AGREEMENT_SUSPENDED`, and each confirmed order so cancelled releases its production-day reservation — the day's `allocated_units` drops by the order's `units_total` and its `version` advances by one. Suspending with `CLASSIFICATION_DISPUTE` moves the agreement to `SUSPENDED_CLASSIFICATION`, additionally flips the distributor's `classification_status` to `DISPUTED` with a `version` bump, and fires the same cancellation cascade. The strike mechanism of §3.5 produces the same `SERVICE_DEFAULT` suspension, cascade included, without any manual call.

Reinstatement depends on which suspension holds. From `SUSPENDED_SERVICE`, either a `RouteOpsManager` or a `CompanyAdmin` reinstates with the `resolution` omitted, returning the agreement to `ACTIVE` and clearing `suspension_reason` to null. From `SUSPENDED_CLASSIFICATION`, only a `CompanyAdmin` may act — a `RouteOpsManager` is refused with `ERR_REINSTATE_FORBIDDEN` — and the supplied `resolution` decides the outcome. `CONFIRMED_IC` reaffirms independent-contractor status: the agreement returns to `ACTIVE`, `suspension_reason` clears to null, and the distributor's `classification_status` returns to `INDEPENDENT_CONTRACTOR` with a `version` bump. `RECLASSIFIED` instead treats the distributor as an employee: `classification_status` becomes `RECLASSIFIED_EMPLOYEE`, and the agreement does not return to service — it moves straight to `EXITING` exactly as a for-cause exit under §3.8, stamping `exited_on`, creating a `PENDING` territory transfer in `FOR_CAUSE` mode, and pushing the territory to `EXITING`.

### 3.8. Distributor Exit and Territory Repurchase

A distributor exit begins when a `RouteOpsManager` initiates exit on an `ACTIVE` or `SUSPENDED_SERVICE` agreement, supplying a `mode` of `VOLUNTARY` or `FOR_CAUSE`. The agreement stamps `exited_on` from the logical clock, moves to `EXITING`, and pushes its territory `UNDER_AGREEMENT → EXITING`. In the same act the system creates the territory transfer — its `agreement_id` pointing at the exiting agreement — in `PENDING` status, and computes its `gross_valuation_cents` using the variant keyed on `mode`, exposing the components in `valuation_detail`.

Valuation proceeds in a pinned order. First, the full years of service: the day count between the `activated_on` date and the exit date, divided by 365 and rounded down. Second, depreciation: 2% of `purchase_price_cents` per full year of service, rounded half-up to whole cents, recorded as `depreciation_cents`. Third, compliant accounts: the count of the distributor's retail accounts with no violation audit whose `audit_date` lies in the trailing ninety days ending on the exit date — an account with no audits at all in the window counts as compliant. Fourth, the variant branch: a `VOLUNTARY` exit credits goodwill of 50,000 cents per compliant account as `goodwill_cents` with `penalty_cents` zero, while a `FOR_CAUSE` exit — including one produced by a `RECLASSIFIED` resolution — zeroes goodwill and instead assesses a `penalty_cents` of 15% of the purchase price, rounded half-up to whole cents. Fifth, the gross valuation is the purchase price minus depreciation, plus goodwill, minus penalty. The same territory, dates, and accounts therefore yield different valuations under the two modes whenever any compliant account exists or the penalty is non-zero. An agreement's transfers may be listed at any time and return at most one row.

Settlement is the credit desk's final act, performed by a `CreditAnalyst` on a `PENDING` transfer — settling a transfer in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. First the financing payoff is computed. When the agreement holds a plan in `ACTIVE` or `DELINQUENT`, interest accrues from the last accrual date — the `disburse_date` if no payment was ever made, otherwise the date of the most recent accepted payment — to the settlement date, as the outstanding principal multiplied by the `annual_interest_rate`, multiplied by the day count, and divided by 365, rounded half-up to whole cents; `financing_payoff_cents` is the outstanding principal plus that accrued interest, and the plan itself moves to `SETTLED_ON_EXIT` with its `outstanding_principal_cents` booked into the payoff and then zeroed. When no such live plan exists — none was created, or the plan is `PAID_OFF` or `SUPERSEDED` — the payoff is zero. The distributor's payout is then the gross valuation minus the payoff, recorded as `distributor_payout_cents`; the figure may be negative, representing a distributor deficiency owed back.

Settlement stamps `settled_on`, moves the transfer to `SETTLED`, moves the agreement `EXITING → EXITED`, and returns the territory `EXITING → AVAILABLE` with a `version` bump — ready to be listed and sold again, completing the cycle this model runs on. Finally, when the exiting distributor holds no other agreement in `DRAFT`, `ACTIVE`, `SUSPENDED_SERVICE`, `SUSPENDED_CLASSIFICATION`, or `EXITING`, the distributor itself moves to `EXITED`.

## 4. Endpoint Definitions

Operations that create new resources — a bakery, a territory, a distributor, a production day, an agreement, a financing plan, a retail account, an audit entry, an order, or a stale claim — return a `201 Created` status code. Operations that modify an existing resource's state, including submissions, confirmations, cancellations, deliveries, reconciliations, decisions, disbursements, payments, suspensions, reinstatements, exits, closes, settlements, and clock updates, return a `200 OK` status code. The full request and response shapes of every operation are specified by the workflows in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | CompanyAdmin |
| POST | `/bakeries` | Create a bakery with its fixed product catalog | CompanyAdmin |
| GET | `/bakeries/{id}` | Get a bakery | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/bakeries/{id}/production-days` | Create a production day for a bakery date | CompanyAdmin |
| GET | `/bakeries/{id}/production-days` | List production days of a bakery | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/production-days/{id}/close` | Close a production day (runs financing delinquency evaluation and stale-claim auto-expiry) | CompanyAdmin |
| POST | `/territories` | Create a territory | CompanyAdmin |
| GET | `/territories/{id}` | Get a territory | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/territories/{id}/list-for-sale` | List an AVAILABLE territory for sale | CompanyAdmin |
| POST | `/distributors` | Create a distributor | CompanyAdmin |
| GET | `/distributors/{id}` | Get a distributor (Distributor role restricted to its own id) | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| GET | `/distributors/{id}/settlement` | Weekly settlement statement with ledger-vs-document reconciliation | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/agreements` | Create a route agreement | RouteOpsManager |
| GET | `/agreements` | List agreements with filters | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| GET | `/agreements/{id}` | Get an agreement | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/agreements/{id}/activate` | Activate a DRAFT agreement | RouteOpsManager |
| POST | `/agreements/{id}/suspend` | Suspend an ACTIVE agreement (service default or classification dispute) | RouteOpsManager |
| POST | `/agreements/{id}/reinstate` | Reinstate a suspended agreement | RouteOpsManager, CompanyAdmin |
| POST | `/agreements/{id}/exit` | Initiate distributor exit (voluntary or for cause) | RouteOpsManager |
| POST | `/agreements/{id}/financing-plans` | Create a financing plan for a DRAFT agreement (OCC on agreement version) | CreditAnalyst |
| GET | `/agreements/{id}/financing-plans` | List financing plans of an agreement | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/financing-plans/{id}/disburse` | Disburse a DRAFT plan | CreditAnalyst |
| POST | `/financing-plans/{id}/payments` | Record a payment on an ACTIVE or DELINQUENT plan | Distributor, CreditAnalyst |
| POST | `/distributors/{id}/retail-accounts` | Create a retail account for a distributor | Distributor, RouteOpsManager |
| GET | `/distributors/{id}/retail-accounts` | List a distributor's retail accounts | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/retail-accounts/{id}/audits` | Post a service-standard audit | RouteOpsManager |
| POST | `/distributors/{id}/orders` | Create a DRAFT order (demand forecast) | Distributor |
| GET | `/distributors/{id}/orders` | List a distributor's orders | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/orders/{id}/submit` | Submit a DRAFT order as a firm order | Distributor |
| POST | `/orders/{id}/confirm` | Confirm a SUBMITTED order against its production day (OCC on day version) | RouteOpsManager |
| POST | `/orders/{id}/cancel` | Cancel a SUBMITTED or CONFIRMED order | Distributor |
| POST | `/orders/{id}/record-delivery` | Record delivered quantities for a CONFIRMED order | Distributor |
| POST | `/orders/{id}/reconcile` | Reconcile a DELIVERED order against verified quantities | RouteOpsManager |
| POST | `/distributors/{id}/stale-claims` | File a stale product claim | Distributor |
| GET | `/distributors/{id}/stale-claims` | List a distributor's stale claims | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/stale-claims/{id}/decide` | Decide a SUBMITTED claim (approve, deny, or request info) | RouteOpsManager |
| POST | `/stale-claims/{id}/resubmit` | Resubmit a NEEDS_INFO claim with corrected items | Distributor |
| POST | `/stale-claims/{id}/issue-credit` | Issue credit on an APPROVED claim | CreditAnalyst |
| GET | `/agreements/{id}/transfers` | List territory transfers of an agreement | CompanyAdmin, RouteOpsManager, CreditAnalyst, Distributor |
| POST | `/transfers/{id}/settle` | Settle a PENDING transfer | CreditAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is a routing summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_REINSTATE_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_TERRITORY_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTOR_NOT_FOUND` | 404 Not Found |
| `ERR_BAKERY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AUDIT_SCORE_RANGE` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_TERRITORY_NOT_LISTED` | 409 Conflict |
| `ERR_DISTRIBUTOR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_PRODUCTION_DAY_EXISTS` | 409 Conflict |
| `ERR_PRODUCTION_DAY_LOCKED` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ORDER_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_SKU_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_STALE_YET` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_STALE_CAP_EXHAUSTED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PAYMENT_BELOW_INTEREST` | 409 Conflict |
| `ERR_FINANCING_NOT_DISBURSED` | 409 Conflict |
| `ERR_FINANCING_PLAN_EXISTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
