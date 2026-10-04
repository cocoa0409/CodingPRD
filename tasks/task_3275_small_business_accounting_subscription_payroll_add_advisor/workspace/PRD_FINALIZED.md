# Small Business Accounting API — Product Requirements Document

## 1. Introduction

Small businesses expect their accounting software to grow with them: a sole proprietor begins on a cheap tier, hires staff and bolts on payroll, hands the books to an outside accountant, and eventually outgrows the entry plan. Each of those moments is a commercial negotiation as much as a software event — an upgrade prompt when a seat limit bites, a wholesale discount when an accountant's firm takes over billing, a proforma quote when billing responsibility changes hands. This document specifies the API for a small-business accounting subscription platform modelled on that commercial reality: subscription tiers that gate features, a payroll add-on with two service levels and per-employee pricing, bank feeds with rule-based categorization and statement reconciliation, and an advisor channel through which accounting firms manage client books under revocable, least-privilege access grants.

Two design commitments shape everything that follows. First, money is pinned: every price, discount, tax, and reconciliation difference is defined with an exact evaluation order and rounding rule, because a one-cent ambiguity in the spec becomes a one-cent dispute with a customer. Second, authority is delegated, never assumed: a client company owns its data, grants access to advisors explicitly, and can take billing back from a firm at any time; a firm acts on a client only while holding an active grant of the right level. Where the platform must make time-dependent judgments — trial expiry, billing anchors, consent expiry, read-only windows — the server maintains a logical clock that test tooling can advance deterministically, so that no behavior in this document depends on wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400) before any other check runs. The role names, spelled exactly, are `PlatformAdmin`, `CompanyUser`, and `AccountantUser`. A role that the endpoint's authorization does not admit is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The three roles differ fundamentally in how `X-User-ID` is interpreted:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`. Platform admins run the simulation endpoints, manage plans and firms, and onboard companies.
- When `X-User-Role` is `CompanyUser`, `X-User-ID` is the `id` of the acting `CompanyUser`; the header must resolve to a persisted `CompanyUser` row, and ownership checks on any resource that references a company compare the resource's `company_id` chain to that user's own `company_id`. A `CompanyUser` acting on a company other than their own is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403).
- When `X-User-Role` is `AccountantUser`, `X-User-ID` is the `id` of the acting `AccountantUser`; the header must resolve to a persisted `AccountantUser` row, and firm-scoped ownership checks compare against that user's `firm_id`. Mismatches are rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403).

Within a company, a `CompanyUser` carries a `permission_level` of `PRIMARY_ADMIN`, `COMPANY_ADMIN`, `STANDARD`, `REPORTS_ONLY`, or `TIME_TRACKING`. Certain operations are reserved to `PRIMARY_ADMIN` as a segregation-of-duties rule — cancelling the subscription, accepting a billing transfer on the client side, changing the plan, and downloading an export whose `scope` is `FULL_LEDGER`. A `COMPANY_ADMIN` cannot substitute; such attempts are rejected with `ERR_REQUIRES_PRIMARY_ADMIN` (HTTP 403). A full-ledger export requested by anyone other than a `PRIMARY_ADMIN` is rejected with `ERR_EXPORT_SCOPE_REQUIRES_PRIMARY_ADMIN` (HTTP 403).

An `AccountantUser` acts on a client company's data only while holding an `AccessGrant` in `ACTIVE` status at the required `access_level`: `FULL_BOOKKEEPING` for bookkeeping, reconciliation, conflict resolution, invoice payment, and export downloads; `PAYROLL_ONLY` suffices (in addition to `FULL_BOOKKEEPING`) for payroll employee create and terminate; `REPORTS_READ_ONLY` grants reads only.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response's `meta` block carries `limit`, `offset`, `total_count`, and `has_more`. All list endpoints sort by `created_at` ascending unless a more specific rule says otherwise. Individual list endpoints may additionally declare filter query parameters (for example `user_status`, `txn_status`, `invoice_status`, `recon_status`, `bank_connection_id`, `category_id`, `matched_rule_id`, `reconciled_in_id`, `rule_status`, `connection_status`, `integration_status`, `conflict_status`, `migration_status`, `transfer_status`, `grant_status`, `export_status`, `company_id`, `plan_id`, `billing_firm_id`, `subscription_id`, `payroll_addon_id`, `app_integration_id`, `accountant_user_id`, `firm_id`, `requested_by_user_id`, `primary_admin_user_id`, `employment_status`, `assign_category_id`, `initiating_firm_id`), each narrowing the result set to rows matching the given value.

### 2.4. Resource Identity and Change Tracking

Every persisted resource exposes an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same format, refreshed on every mutation) and `version`, an integer starting at 1 that increments on every mutation of that resource. Two resource kinds deliberately carry only `id` and `created_at`: a `SubscriptionPlan` and a `Category` have neither `updated_at` nor `version`; responses for these entities must not include those fields.

Nested URLs are validated left to right: each path segment's identifier must resolve to an existing resource before the next is examined, and the first unresolvable identifier determines the `ERR_NOT_FOUND` (HTTP 404) response. Body-level foreign keys (for example `plan_id`, `assign_category_id`, `accountant_user_id`, `initiating_firm_id`) are then validated in the order they appear in the endpoint's input list, again surfacing `ERR_NOT_FOUND` for the first miss. Malformed bodies, missing required fields, or type violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400), and any enum field whose value falls outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400).

### 2.5. Monetary Precision, Tax, and Rounding

All monetary values are integer cents. Wherever a computation produces a fractional cent, it is rounded half-up to the nearest whole cent at the step this document specifies — never earlier, never later, and never by summing first and rounding once at the end where a per-line rule is stated. Sales tax is computed on the post-discount subtotal: the subscription list price, minus any wholesale discount, plus the payroll base fee, plus the payroll per-employee charge, forms the tax base. The tax rate depends on the company's `home_country` / `data_region`: companies in the US are taxed at zero percent, companies in the UK at twenty percent, and companies in the EU at twenty-one percent. The resulting tax line is itself rounded half-up to whole cents, and the invoice total is the subtotal plus that tax.

### 2.6. Optimistic Concurrency Control

Three write operations are version-checked against a parent entity, and each requires its expected-version field as a non-optional input. A plan change on a subscription must carry `expected_subscription_version` matching the subscription's current `version`; if another writer has advanced the version since the caller last read the subscription — by changing the plan, or by a billing transfer completing — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A client-side acceptance of a billing transfer must likewise carry `expected_subscription_version`; accepting against a subscription whose version has moved since the transfer was created is rejected with `ERR_STALE_VERSION` (HTTP 412), because the accept recomputes pricing under the new billing owner and must not double-apply. Terminating a payroll employee must carry `expected_payroll_addon_version` matching the payroll add-on's current `version`; a mismatch — for instance, another termination having already fired or the service level having changed — is rejected with `ERR_STALE_VERSION` (HTTP 412), keeping the per-employee proration snapshot well-defined. Endpoints not named here do not take a version field.

### 2.7. Logical Clock and Simulation Drivers

The server maintains a logical clock. At boot, the current time is exactly `2026-09-01T00:00:00Z`; the server never falls back to wall-clock time. A `PlatformAdmin` may set the logical clock via a test-driving capability that accepts a `current_utc` instant; setting the clock re-evaluates every time-driven transition in the system: trial expiry, billing-transfer expiry, access-grant expiry, export-download expiry, and bank-consent expiry. A second driver simulates a payment outcome — `SUCCEEDED`, `DECLINED`, or `TIMEOUT` — against an invoice identified by `invoice_id` and `outcome`: on `SUCCEEDED` the invoice moves from `ISSUED` or `PAST_DUE` to `PAID`; on `DECLINED` it remains `ISSUED`. Settling the last unpaid invoice of a suspended subscription this way does not by itself lift the suspension — resuming from `SUSPENDED` is always the explicit operation of §3.3. A third driver performs one bank-feed sync tick for a connection identified by `bank_connection_id`, pulling pending transactions and re-evaluating the connection's `consent_expires_at`: on success `last_sync_at` is set to the current time; if consent has expired the connection drops to `STALE`.

### 2.8. Reference Data and Derived Values

Two behaviors deserve explicit statement because they underpin everything above. Every enum field accepts exactly the values named for it in this document — a role, a `permission_level`, a `service_level`, a `match_field`, a `sync_direction`, a `scope`, a state name — and any other value is rejected with `ERR_INVALID_ENUM` (HTTP 400). Every computed or derived field named in §3 (`monthly_price_cents`, `pending_upgrade_prompt`, `tax_filing_status`, `cleared_cents`, `difference_cents`, `total_cents`, `conflict_count`, `limitation_codes`, `proforma_monthly_cents`) is recomputed by the server on the triggers stated with it; clients never supply these values, and they appear on every read of the owning resource.

### 2.9. Validation Order

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic. First come the context-header check (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`) and the role check (`ERR_FORBIDDEN_FOR_ROLE`), then identity resolution for entity-backed roles (`ERR_IDENTITY_MISMATCH`). Body-shape failures (`ERR_INVALID_REQUEST` — malformed bodies, missing required fields, or type violations) are rejected as the body is read, ahead of any check that depends on the rejected field. Existence follows: path identifiers left to right, then body foreign keys in input order, each miss producing `ERR_NOT_FOUND`. State-machine legality (`ERR_INVALID_STATE_TRANSITION`) is checked next, then the subscription writability gate (`ERR_SUBSCRIPTION_NOT_WRITABLE`), then feature gating (`ERR_FEATURE_NOT_IN_TIER`), then segregation of duties (`ERR_REQUIRES_PRIMARY_ADMIN`). Business-referential checks — reconciliation window overlap (`ERR_STATEMENT_WINDOW_OVERLAP`) and the single-in-flight migration rule (`ERR_MIGRATION_ALREADY_IN_FLIGHT`) — come before uniqueness (`ERR_DUPLICATE`) and enum-domain checks (`ERR_INVALID_ENUM`). Fiscal checks follow: the seat limit (`ERR_SEAT_LIMIT_REACHED`) and billing-state blocks (`ERR_BILLING_STATE_BLOCKED`). Temporal checks — window expiry (`ERR_WINDOW_EXPIRED`) and bank consent (`ERR_CONSENT_EXPIRED`) — are next. Optimistic concurrency (`ERR_STALE_VERSION`) is evaluated last. A request failing several checks therefore always reports the earliest one in this order.

## 3. Business Logic & Workflows

### 3.1. Plans, Tiers, and the Catalog

The platform operator seeds the commercial catalog by creating `SubscriptionPlan` tiers. Each plan carries a unique `plan_code` — the conventional ladder being `SIMPLE_START`, `ESSENTIALS`, `PLUS`, and `ADVANCED` — together with a monthly `list_price_cents`, a `max_seats` allowance, four feature flags (`feature_inventory`, `feature_project_profitability`, `feature_multi_currency`, and `feature_bank_rules`), and a `plan_rank` that orders the upgrade path so that a lower rank is the cheaper tier. Attempting to register a plan whose `plan_code` already exists is rejected with `ERR_DUPLICATE` (HTTP 409).

Feature flags gate behavior, not just marketing copy. Creating a categorization rule — and rule-based auto-categorization generally — requires `feature_bank_rules` to be true on the company's current plan; a plan without it leaves customers with manual categorization only, and any rule-path attempt is rejected with `ERR_FEATURE_NOT_IN_TIER` (HTTP 400), which also sets the subscription's `pending_upgrade_prompt` flag. The same rejection guards inventory, project-profitability, and multi-currency operations against their respective flags. Plans are readable by every role, so a client weighing an upgrade can inspect exactly what the next tier buys.

### 3.2. Onboarding a Company and Its People

Onboarding begins when the platform operator creates a `ClientCompany` with its `legal_name`, `admin_email`, `home_country` (a two-letter uppercase country code that drives tax behavior), `data_region` (one of `US`, `EU`, `UK`, driving export format), and the `plan_id` of the chosen tier. Creation automatically provisions a `Subscription` for the company in `TRIAL` status: `started_at` is set to the current time and `trial_ends_at` to thirty days later. The company's `company_status` starts at `ACTIVE`.

People join as `CompanyUser` records with an `email` unique within the company, a `display_name`, and a `permission_level`. At onboarding, the platform operator may create the initial `PRIMARY_ADMIN`; every subsequent invitation is issued by an existing company user. Invitees are born `INVITED`, and the first user created becomes the company's `primary_admin_user_id`. A duplicate `email` within the same company is rejected with `ERR_DUPLICATE`. An invitation is a mutation and is subject to the `CANCELLED_READ_ONLY` writability gate of §3.3 (`ERR_SUBSCRIPTION_NOT_WRITABLE`).

Seats are rationed by the plan. The seat check counts users of the company in `INVITED` or `ACTIVE` status — `DISABLED` users do not occupy seats — and rejects the invite or acceptance when adding one more would take the occupied count strictly above `max_seats`; at exactly `max_seats` the add still succeeds. The rejection is `ERR_SEAT_LIMIT_REACHED` (HTTP 400) and, as a merchandising hook, sets `pending_upgrade_prompt` on the subscription. The same check fires twice: once when the invitation is created, and again when the invitee accepts. Acceptance is performed by the invitee themselves, moves the user from `INVITED` to `ACTIVE`, requires the subscription to be in `TRIAL`, `ACTIVE`, `PAST_DUE`, or `REACTIVATED`, and — as a kindness to a customer who just cleared space — clears `pending_upgrade_prompt` if a prior seat-limit rejection had set it.

Disabling a user is an administrative act performed by a `PRIMARY_ADMIN` or `COMPANY_ADMIN` against someone other than themselves, moving the target from `ACTIVE` to `DISABLED`. The primary admin cannot be disabled at all — the role must first be transferred to another user — because a company must never be left without someone able to cancel its subscription.

### 3.3. The Subscription Lifecycle

A subscription lives two parallel lives. Its `lifecycle_status` walks `TRIAL` → `ACTIVE` → `PAST_DUE` → `SUSPENDED`, with `CANCELLED_READ_ONLY`, `REACTIVATED`, and the terminal `CANCELLED_EXPIRED` beyond; independently, its `billing_status` walks `CURRENT` → `PAST_DUE` → `UNPAID`. The two never share a value and never block one another, and both are exposed on every read alongside `billing_owner` (`CLIENT` or `FIRM`), `billing_firm_id` (non-null exactly when the firm is billed), the `anchor_day` billing anchor, `started_at`, `trial_ends_at`, `cancelled_at`, `read_only_expires_at`, the computed `monthly_price_cents`, and the `pending_upgrade_prompt` flag.

A trial converts to `ACTIVE` when the primary admin activates it with a `payment_method_token`, or when the clock passes `trial_ends_at` with a payment method already recorded. Activation sets `anchor_day` to the day-of-month of activation (the anchor always falls between 1 and 28), initializes the billing schedule (`next_billing_at`) to the end of the first billing period, and creates the first `Invoice` — which, like every invoice, is born `DRAFT` (§3.5) — covering the period from activation through thirty days later, to be issued by the platform operator on the billing date. If the clock reaches `trial_ends_at` with no successful payment on file, the trial instead collapses to `CANCELLED_READ_ONLY`: `cancelled_at` is set to `trial_ends_at`, `read_only_expires_at` to exactly 365 days later, and the company itself drops from `ACTIVE` to `READ_ONLY`; operations attempted against the expired trial surface `ERR_TRIAL_EXPIRED` (HTTP 400).

Payment trouble degrades the subscription in stages. When an invoice remains `ISSUED` five days past its `period_end`, the subscription moves from `ACTIVE` to `PAST_DUE` and `billing_status` becomes `PAST_DUE`. When every past-due invoice is settled, the subscription recovers to `ACTIVE` and `billing_status` returns to `CURRENT`. If any invoice stays `PAST_DUE` for thirty days or longer, the subscription is suspended: `ACTIVE` or `PAST_DUE` gives way to `SUSPENDED`, the payroll add-on cascades from `ACTIVE` to `PAUSED`, every `ACTIVE` bank connection goes `STALE`, and `billing_status` drops to `UNPAID`. Suspension unwinds when all invoices are settled — or when the primary admin resumes explicitly once no invoice remains in `ISSUED` or `PAST_DUE`: the subscription returns to `ACTIVE`, the payroll add-on compensates by moving `PAUSED` back to `ACTIVE`, `billing_status` returns to `CURRENT`, but the bank connections stay `STALE` — the client must re-authorize them, because consent does not survive a suspension. Settling alone never lifts `SUSPENDED`; the resume is always explicit.

Changing plans is a primary-admin operation carrying the target `plan_id` and the OCC field `expected_subscription_version`. A successful change increments the subscription's `version`, recomputes `monthly_price_cents` under the new tier, and clears `pending_upgrade_prompt` — the prompt did its job.

Cancellation is deliberately hard and deliberately consequential. Only a `PRIMARY_ADMIN` may cancel (a `COMPANY_ADMIN` attempting it hears `ERR_REQUIRES_PRIMARY_ADMIN`), the request may carry a free-text `reason`, and cancellation is refused with `ERR_BILLING_STATE_BLOCKED` while any billing transfer for this subscription is pending client or firm acceptance, or while any reconciliation for the company sits in `DRAFT` or `IN_PROGRESS`. From any of `TRIAL`, `ACTIVE`, `PAST_DUE`, `SUSPENDED`, or `REACTIVATED`, cancellation lands in `CANCELLED_READ_ONLY` with a wide cascade: `cancelled_at` is set to now and `read_only_expires_at` to 365 days hence; the payroll add-on moves to its terminal `CANCELLED`; every `ACTIVE` access grant is revoked; every bank connection is disconnected; every app integration is disconnected with its unresolved sync conflicts left `OPEN` and its `conflict_count` preserved for audit; the company drops to `READ_ONLY`; any migration job still `QUEUED` or `CONVERTING` is cancelled; and `pending_upgrade_prompt` is cleared.

The read-only window is a grace period, not an afterlife. While in `CANCELLED_READ_ONLY`, reads and export requests remain possible but other mutations are rejected with `ERR_SUBSCRIPTION_NOT_WRITABLE` (HTTP 400) or, where the company's own status is the guard, `ERR_COMPANY_READ_ONLY` (HTTP 400). Within the window, the primary admin may reactivate with a valid `payment_method_token`; attempting it once the clock has passed `read_only_expires_at` is rejected with `ERR_REACTIVATION_WINDOW_EXPIRED` (HTTP 400). Reactivation moves the subscription to `REACTIVATED`, lifts the company back to `ACTIVE`, and clears both `cancelled_at` and `read_only_expires_at` — but it does not resurrect what cancellation killed: the payroll add-on stayed terminal and must be created anew, and the revoked access grants stay revoked until the client re-invites each advisor. The first successful invoice payment after reactivation settles the subscription into plain `ACTIVE`. When the clock finally passes `read_only_expires_at` without reactivation, the subscription reaches `CANCELLED_EXPIRED`, the company is `PURGED`, and every export request still `PENDING` or `READY` is expired.

### 3.4. Payroll: Service Levels, Employees, and Filing Health

A company on an active subscription may attach one payroll add-on by naming its `subscription_id` and choosing a `service_level`: `SELF_SERVICE`, where the customer files its own payroll taxes, or `FULL_SERVICE`, where the platform files on the customer's behalf. Activation snapshots the rate card into the add-on: a `SELF_SERVICE` add-on carries a `base_fee_cents` of 4500 and a `per_employee_fee_cents` of 600; a `FULL_SERVICE` add-on carries 8500 and 1000 respectively. The snapshot is taken once, at activation, and later rate-card changes do not reach existing add-ons. The add-on's `addon_status` walks `ACTIVE`, `PAUSED`, and the terminal `CANCELLED`. Because a subscription supports only one payroll add-on at a time, creating a second while one is `ACTIVE` or `PAUSED` is rejected with `ERR_PAYROLL_ALREADY_ACTIVE` (HTTP 409). The add-on is born `ACTIVE` with `activated_at` set, and its `tax_filing_status` is derived on every read (see below).

Employees are registered against the add-on by `payroll_addon_id`, `legal_name`, and `hire_date`, and begin life with `employment_status` `ACTIVE`. Terminating an employee is allowed to a `PRIMARY_ADMIN` or `COMPANY_ADMIN` of the company, or to an advisor holding a `FULL_BOOKKEEPING` or `PAYROLL_ONLY` grant; it requires the add-on to be `ACTIVE` and the subscription to be in `ACTIVE`, `REACTIVATED`, or `PAST_DUE`. The termination request carries `expected_payroll_addon_version` per the OCC rule in §2.6, increments the add-on's `version`, and stamps `terminated_at` with the current time — the per-employee fee at the next invoice is prorated to that day. Terminating someone already `TERMINATED` is rejected with `ERR_EMPLOYEE_ALREADY_TERMINATED` (HTTP 400), and any payroll-employee operation against a non-active add-on hears `ERR_PAYROLL_NOT_ACTIVE` (HTTP 400); because suspension of the subscription pauses the add-on, a termination attempted while the subscription is `SUSPENDED` surfaces `ERR_PAYROLL_NOT_ACTIVE` — the add-on check is the operative gate there.

The add-on itself can be paused and resumed by the primary admin, and follows the parent subscription's fortunes automatically: suspension of the subscription pauses the add-on, and resumption of the subscription reactivates it — resumption is only possible while the parent subscription is in `ACTIVE` or `REACTIVATED`. Cancelling payroll is terminal. For a `FULL_SERVICE` add-on, cancellation is refused while a tax filing is in flight — concretely, while `tax_filing_status` is `FILED_CURRENT` pending its final acknowledgment — and the refusal is `ERR_PAYROLL_CANCEL_BLOCKED_BY_FILING` (HTTP 400). Employees left behind keep their records but accrue no further per-employee fees.

The derived `tax_filing_status` summarizes payroll health as one of four values, computed in this exact order. If the add-on has no `ACTIVE` employees, the status is `NOT_READY`. Otherwise, if any bank connection of the company is `STALE` or `REVOKED`, the status is `NOT_READY`. Otherwise, if any reconciliation of the company is `IN_PROGRESS` with a `statement_period_end` more than 45 days in the past, the status is `PENALTY_RISK`. Otherwise, if all invoices of the trailing three months are `PAID`, the status is `FILED_CURRENT`. In every remaining case the status is `READY`.

### 3.5. Invoicing, Pricing, and Wholesale Arithmetic

Invoices are the system of record for what a period cost. Each `Invoice` belongs to a company and a subscription, spans a `period_start` (inclusive) to `period_end` (exclusive), and at issue time snapshots `billed_to` from the subscription's current `billing_owner` — an immutable record of who was responsible for that period. Its lines are `list_subscription_cents` (the plan's list price for the period), `wholesale_discount_cents` (zero when the client is billed), `payroll_base_cents` (the payroll base fee when the add-on was active on any day of the period, prorated per the payroll rules), `payroll_per_employee_cents` (the day-by-day computation below), `tax_cents`, and the computed `total_cents`.

The effective monthly price of a subscription — the `monthly_price_cents` quoted on reads and previews — is the plan's `list_price_cents` when the client is billed. When a firm is billed, the wholesale discount applies: the effective discount percentage is the firm's `wholesale_discount_pct` capped at the ceiling of its `proadvisor_tier` — 0.20 for `SILVER`, 0.35 for `GOLD`, 0.50 for `PLATINUM` — and the price is the list price times one minus that capped percentage, rounded half-up to whole cents. The discount percentage a firm registers must itself lie between 0 and 0.50 with two-decimal precision.

The per-employee payroll line on an invoice is computed day by day, and the rounding order is pinned because the two natural orders disagree by cents. For each day from `period_start` up to but not including `period_end`, count the employees who were `ACTIVE` on that day — an employee counts on a day when their `hire_date` is on or before it and their `terminated_at` is either unset or strictly after it. Multiply that day's count by `per_employee_fee_cents`, divide by 30 — the billing month is always thirty days regardless of calendar length — and round that day's amount half-up to whole cents. The invoice line is the sum of those per-day rounded amounts. A mid-month preview, such as the one behind `monthly_price_cents` after a plan change, uses the cheaper provisional estimate instead: the current count of `ACTIVE` employees times the per-employee fee, with no day-by-day walk; the provisional figure can differ from the final invoice line by a few cents, and the invoice line is the authoritative number.

Invoice total evaluation order is likewise pinned. The subtotal is the list subscription price minus the wholesale discount plus the payroll base plus the payroll per-employee charge; tax is the subtotal times the company's regional rate (zero percent US, twenty percent UK, twenty-one percent EU), rounded half-up to whole cents; `total_cents` is the subtotal plus that tax. Payroll enters the base before tax, never after.

An invoice is born `DRAFT`. Setting the logical clock re-evaluates billing as one of the time-driven transitions of §2.7: on each billing date of a subscription in `ACTIVE`, `PAST_DUE`, or `REACTIVATED` the system itself generates the `DRAFT` invoice covering the thirty-day period that just ended — a period already covered by a `PAID` invoice is skipped — and advances the billing schedule. Issuing it — which the platform operator does on the billing date — requires the subscription to be in `ACTIVE`, `PAST_DUE`, or `REACTIVATED`, snapshots the lines above, and, because the platform's consistency model is immediate, the payment simulation for that invoice runs within the same call: a `SUCCEEDED` outcome moves it straight to `PAID`. Issuing an invoice that is already `ISSUED` is idempotent and returns the invoice unchanged. An `ISSUED` invoice is paid by the primary admin or by a `FULL_BOOKKEEPING` advisor (or by the simulated payment succeeding), and payment lifts the subscription from `PAST_DUE` back to `ACTIVE` when no other unpaid invoice remains. Five days after `period_end` with no payment, the invoice becomes `PAST_DUE` and the bubble-up pushes the subscription from `ACTIVE` to `PAST_DUE`. The platform operator may void an invoice in `DRAFT` or `ISSUED`, moving it to the terminal `VOID`. Attempting to pay an invoice that is not `ISSUED` — or to issue one that is neither `DRAFT` nor already `ISSUED` — is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 400).

### 3.6. Bank Feeds and Transaction Categorization

A bank connection is created by a company user with the `institution_name`, the `external_account_mask` (the last four digits shown to users), and a `consent_expires_at` captured from the bank's consent flow. A company may not hold two non-terminal connections with the same institution-and-mask triple; the duplicate is rejected with `ERR_CONNECTION_ALREADY_EXISTS` (HTTP 409). A new connection is `PENDING_AUTH`. Authorizing it requires the subscription to be in `TRIAL`, `ACTIVE`, `PAST_DUE`, or `REACTIVATED` and requires `consent_expires_at` to still be in the future — an expired consent hears `ERR_CONSENT_EXPIRED` (HTTP 400) — and success moves the connection to `ACTIVE` with `last_sync_at` set. When the clock later passes `consent_expires_at`, the next sync tick drops the connection to `STALE` and halts ingestion of new transactions. Re-authorizing a `STALE` connection with a fresh `consent_expires_at` restores it to `ACTIVE`, provided the subscription is in `ACTIVE`, `REACTIVATED`, or `PAST_DUE`; the same expired-consent rejection applies. Trying to authorize a connection that is neither `PENDING_AUTH` nor `STALE` is rejected with `ERR_CONNECTION_NOT_AUTHORIZABLE` (HTTP 400). A connection in `PENDING_AUTH`, `ACTIVE`, or `STALE` may be disconnected — recoverable, but no new transactions are ingested — and a `DISCONNECTED` or `STALE` connection may be permanently revoked, after which its historical transactions are retained for audit.

Transactions arrive with a `posted_at`, a signed `amount_cents` (positive for deposits, negative for withdrawals), and the bank's raw `payee_raw` text, and each is born `UNCATEGORIZED` with both `category_id` and `matched_rule_id` null. Ingestion immediately runs the categorization-rule selector over the company's `ACTIVE` rules. A rule matches by its `match_field`: `PAYEE_CONTAINS` matches when the rule's `match_value` is a case-insensitive substring of the transaction's payee text; `AMOUNT_EQUALS` matches when the numeric value of `match_value` equals the transaction's amount in cents exactly; `AMOUNT_GREATER_THAN` matches when the transaction's amount is strictly greater than that numeric value. Among the matching rules the winner is the one with the lowest `priority`; ties are broken by the rule's `created_at`, earlier first — never by identifier. If no rule matches, the transaction stays `UNCATEGORIZED`. A winning rule with `auto_apply` true moves the transaction straight to `CATEGORIZED`, setting its `category_id` to the rule's `assign_category_id` and recording the rule in `matched_rule_id`; a winning rule with `auto_apply` false (the default for `auto_apply` is true when omitted) moves it only to `RULE_SUGGESTED`, recording `matched_rule_id` but leaving `category_id` null. Creating or resuming a rule re-evaluates the company's `UNCATEGORIZED` transactions against it, and the whole rule pathway is gated on the plan's `feature_bank_rules` flag.

From `RULE_SUGGESTED`, a user of `STANDARD` level or above — or a `FULL_BOOKKEEPING` advisor — accepts the suggestion to reach `CATEGORIZED`, or rejects it to return to `UNCATEGORIZED`, the rejection clearing both `category_id` and `matched_rule_id`. Manual categorization with an explicit `category_id` moves a transaction from `UNCATEGORIZED` to `CATEGORIZED` regardless of tier — the tier gate applies to rules, not to hand work. A `CATEGORIZED` transaction can be sent back to `UNCATEGORIZED`, clearing both fields, or excluded entirely from `UNCATEGORIZED`, `RULE_SUGGESTED`, or `CATEGORIZED`; an `EXCLUDED` transaction no longer counts toward reconciliation totals and can later be restored to `UNCATEGORIZED`. Nothing may be done to a transaction once a reconciliation has locked it — its `reconciled_in_id` set — and any such attempt is rejected with `ERR_TXN_LOCKED_BY_RECONCILIATION` (HTTP 400).

Rules themselves are managed by company users of `STANDARD` level or above and, for creation only, by `FULL_BOOKKEEPING` advisors. Each rule is created with a display `rule_name`, a `match_field`, a `match_value`, the `assign_category_id` it stamps, a `priority`, and optionally `auto_apply`; its `rule_status` walks `ACTIVE`, `PAUSED`, and terminal `DELETED`. A rule may be paused from `ACTIVE` — pausing a rule not in `ACTIVE` is rejected with `ERR_RULE_NOT_PAUSABLE` (HTTP 400) — and resumed from `PAUSED`, though resuming additionally requires the plan to still carry the bank-rules feature; a resumption attempted on a rule not in `PAUSED`, or under a plan without the feature, is rejected with `ERR_RULE_NOT_RESUMABLE` (HTTP 400). Deleting a rule moves it to terminal `DELETED`, and transactions it previously categorized keep their `matched_rule_id` for audit. Categories themselves are simple company-scoped constructs with a `name` and a `tax_line` mapping code.

### 3.7. Reconciliation: Closing the Books Against the Statement

A reconciliation pins a bank statement against the books. It is created with the `bank_connection_id` being reconciled, the `statement_period_start` and `statement_period_end` (both inclusive — the window is a closed interval), and the `statement_ending_balance_cents` from the paper statement. The `beginning_balance_cents` is pulled automatically from the ending balance of the most recent `COMPLETED` reconciliation, or treated as the opening-equity figure of zero when none exists. The reconciliation is born `DRAFT`.

Starting work on a reconciliation moves it from `DRAFT` to `IN_PROGRESS` and enforces window hygiene: the statement window must not intersect any existing `IN_PROGRESS` or `COMPLETED` reconciliation for the same bank connection. Because both ends of every window are closed, adjacency counts as overlap — a window whose start equals another window's end collides; true adjacency requires starting the day after the other's end. Violations are rejected with `ERR_STATEMENT_WINDOW_OVERLAP` (HTTP 409), and the same check runs at creation time as well.

While work proceeds, two numbers track progress. `cleared_cents` is the sum of `amount_cents` over the connection's transactions whose status is `CATEGORIZED` or `MATCHED_RECONCILED` and whose `posted_at` falls within the statement window, inclusive of both ends — `EXCLUDED` transactions never count — and it is recomputed on every transaction added, removed, categorized, or excluded. `difference_cents` is the statement's ending balance minus the sum of the beginning balance and `cleared_cents`. While the reconciliation is in `DRAFT` or `IN_PROGRESS`, the reported difference is the projected figure, which optimistically includes `RULE_SUGGESTED` transactions as if their suggestions had been accepted; once the reconciliation completes, the locked figure counts only `CATEGORIZED` and `MATCHED_RECONCILED` rows and is immutable thereafter.

Completing a reconciliation requires `difference_cents` to be exactly zero — zero and only zero; any residual is rejected with `ERR_RECON_DIFFERENCE_NOT_ZERO` (HTTP 400). On completion every `CATEGORIZED` transaction in the window cascades to `MATCHED_RECONCILED` with its `reconciled_in_id` set — locking those transactions against further modification — and `completed_at` is stamped. Work can also be abandoned, returning an `IN_PROGRESS` reconciliation to `DRAFT` and resetting its `cleared_cents` contribution to zero. When the parent subscription is cancelled, any reconciliation still in `DRAFT` or `IN_PROGRESS` moves to `LOCKED` — preserved for read-only audit, never resumable.

### 3.8. The App Ecosystem and Sync Conflicts

Third-party apps attach to a company as `AppIntegration` records carrying an `app_code` (such as `SHOPIFY`, `GUSTO`, or `SQUARE`) and a `sync_direction` of `PULL`, `PUSH`, or `BIDIRECTIONAL`. A new integration is `LINKED` and becomes `ACTIVE` when a `PRIMARY_ADMIN` or `COMPANY_ADMIN` activates it, provided the subscription is in `TRIAL`, `ACTIVE`, `REACTIVATED`, or `PAST_DUE`. Sync operations against an integration that is not `ACTIVE` are rejected with `ERR_INTEGRATION_NOT_ACTIVE` (HTTP 400).

Sync conflicts are recorded by the platform with the divergent `conflict_field`, our `local_value`, and the app's `remote_value`; each new conflict is `OPEN` and increments the integration's `conflict_count`. When the count of unresolved `OPEN` conflicts reaches three, the integration drops automatically to `CONFLICT_PAUSED`: syncing pauses, though new conflicts continue to be recorded. Resolving a conflict takes a `resolution` of `LOCAL`, `REMOTE`, or `IGNORE`: `LOCAL` keeps our value, `REMOTE` overwrites the local value with the remote one, and `IGNORE` dismisses the divergence; all three decrement `conflict_count`, and the conflict lands in `RESOLVED_LOCAL`, `RESOLVED_REMOTE`, or `IGNORED` respectively. Resolving a conflict that is not `OPEN` is rejected with `ERR_CONFLICT_NOT_OPEN` (HTTP 400). Resuming a conflict-paused integration is manual and deliberately asymmetric with the pause: even when resolution brings the count below three the integration stays paused, and resumption requires `conflict_count` to be exactly zero — attempting it earlier is rejected with `ERR_INTEGRATION_RESUME_BLOCKED` (HTTP 400). Disconnecting from `LINKED`, `ACTIVE`, or `CONFLICT_PAUSED` is terminal for the integration, leaving its unresolved conflicts `OPEN` for audit.

### 3.9. Desktop-to-Online Migration

Bringing a desktop customer online starts with a migration job naming the `source_product` (`DESKTOP_PRO`, `DESKTOP_PREMIER`, or `DESKTOP_ENTERPRISE`), the `source_file_size_bytes`, and the `target_list_entries` — the combined count of customers, vendors, items, and accounts in the source file. Only one migration job may be in flight per company: creating a second while one is `QUEUED` or `CONVERTING` is rejected with `ERR_MIGRATION_ALREADY_IN_FLIGHT` (HTTP 409).

The platform operator starts a queued job, moving it to `CONVERTING`, and completes it with an `outcome`. A `CLEAN` outcome lands in `COMPLETED_CLEAN` but is only legitimate when the combined list count is at most 750,000 and — for `DESKTOP_ENTERPRISE` sources — the target plan carries the multi-currency feature; otherwise the honest outcome is `WITH_LIMITATIONS`, landing in `COMPLETED_WITH_LIMITATIONS` with `limitation_codes` populated deterministically: `PAYROLL_NOT_MIGRATED` is always added when the company ran payroll on desktop, `MULTI_CURRENCY_NOT_MIGRATED` is added when the target plan lacks `feature_multi_currency`, and `LIST_LIMIT_EXCEEDED_PARTIAL` is added when `target_list_entries` exceeds 750,000. A `FAILED` outcome lands in `FAILED`. A job still `QUEUED` or `CONVERTING` can be cancelled — by the platform or the requesting company user, or automatically when the subscription is cancelled — and cancelling a job in any other state is rejected with `ERR_MIGRATION_NOT_CANCELLABLE` (HTTP 400).

### 3.10. The Advisor Channel: Firms, Grants, and Billing Transfers

The platform operator registers an `AccountantFirm` with its `firm_name`, its negotiated `wholesale_discount_pct` (between 0 and 0.50, two-decimal precision), and its `proadvisor_tier` of `SILVER`, `GOLD`, or `PLATINUM`, which caps the discount actually applied at 0.20, 0.35, or 0.50 respectively. Advisors join the firm as `AccountantUser` records with a `full_name`, an `email` unique within the firm (duplicates rejected with `ERR_DUPLICATE`), and an `is_firm_admin` flag (defaulting to false) marking who may manage billing transfers.

A firm's standing matters. Suspending a firm — `ACTIVE` to `SUSPENDED` — revokes every `ACTIVE` access grant issued to its advisors and flags the wholesale discount as inapplicable on the next invoice for every subscription the firm bills, until reactivation. Reactivating restores wholesale eligibility but pointedly does not restore the revoked grants; the client or the firm must re-issue each one. Closing a firm is terminal and is refused while the firm still owns billing on any non-terminal subscription (one in `TRIAL`, `ACTIVE`, `PAST_DUE`, or `SUSPENDED` with `billing_owner` `FIRM`) or while any of its grants remain in `PENDING_ACCEPT` or `ACTIVE` — the refusal surfaces as `ERR_BILLING_STATE_BLOCKED`; a firm whose `firm_status` is not `ACTIVE` also cannot accept transfers or grants, rejected as `ERR_FIRM_NOT_ACTIVE` (HTTP 400). When closure proceeds — the firm moving from `ACTIVE` or `SUSPENDED` to the terminal `CLOSED` — any billing transfers the firm initiated are cancelled.

Client access flows through `AccessGrant` records. A company user issues a grant naming the `accountant_user_id`, the `firm_id` (denormalized from the advisor's firm at creation), the `access_level` — `FULL_BOOKKEEPING`, `REPORTS_READ_ONLY`, or `PAYROLL_ONLY` — and optionally an `expires_at`. A grant is born `PENDING_ACCEPT`, and only one `ACTIVE` grant may exist for a given company-and-advisor pair; a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_GRANT` (HTTP 409). The advisor accepts their own grant, provided their firm is `ACTIVE` and the grant has not passed its `expires_at`; an acceptance against a grant no longer acceptable is rejected with `ERR_GRANT_NOT_ACCEPTABLE` (HTTP 400), and a grant whose `expires_at` the clock has passed surfaces as `ERR_WINDOW_EXPIRED` (HTTP 400). When the clock passes a grant's `expires_at` the grant transitions to `EXPIRED` on the next read or action. A `PRIMARY_ADMIN` or `COMPANY_ADMIN` of the company may revoke a grant in `PENDING_ACCEPT` or `ACTIVE` — revoking a terminal grant hears `ERR_GRANT_NOT_REVOCABLE` (HTTP 400) — and grants are also revoked automatically when the firm is suspended or the subscription is cancelled.

Billing transfers renegotiate who pays. Either a firm admin advisor or the client's primary admin initiates a transfer with the `subscription_id`, the `initiating_firm_id`, and the target `to_owner`; the record snapshots the current owner as `from_owner`, stamps `expires_at` at fourteen days out, and opens in `PENDING_CLIENT_ACCEPT`. Only one transfer may be pending for a subscription at a time; a second attempt is rejected with `ERR_TRANSFER_ALREADY_PENDING` (HTTP 409). At creation the system computes `proforma_monthly_cents`, the projected next-month price under the new owner: resolve the initiating firm, take its tier ceiling (0.20, 0.35, 0.50 for `SILVER`, `GOLD`, `PLATINUM`), cap the firm's `wholesale_discount_pct` at that ceiling when the target owner is `FIRM`, apply the discount to the plan's list price with half-up rounding to whole cents — or take the plain list price when the target is `CLIENT` — then add the payroll snapshot at the current count of `ACTIVE` employees (the add-on's `base_fee_cents` plus that count times `per_employee_fee_cents`) when an `ACTIVE` payroll add-on exists.

The client's primary admin accepts a client-pending transfer with `expected_subscription_version` per §2.6, provided the transfer has not expired and the subscription is in `ACTIVE`, `TRIAL`, or `REACTIVATED`; acceptance flips the subscription's `billing_owner` to the target, sets `billing_firm_id` to the initiating firm when the firm takes over, increments the subscription's `version`, and recomputes `monthly_price_cents` under the new arrangement. Instead of accepting, the client may counter — moving the transfer to `PENDING_FIRM_ACCEPT` to make the firm confirm the wholesale terms — and the firm admin then accepts from that state with the same completion effects, provided their firm is still `ACTIVE`. Either party may decline with a mandatory `decline_reason`, and the initiating party (the primary admin when the client initiated, the firm admin when the firm did) may cancel. A transfer left unresolved past `expires_at` expires automatically when the clock passes, and acting on an expired transfer is rejected with `ERR_TRANSFER_EXPIRED` (HTTP 400) — the expiry check fires before the pending-state check on accept, counter, and firm accept.

### 3.11. Data Export Obligations

A cancelled customer keeps the right to their data. An export request names the `requested_by_user_id`, a `format` of `CSV`, `XLSX`, or `QBO_BACKUP`, and a `scope` of `TRANSACTIONS_ONLY`, `FULL_LEDGER`, or `PAYROLL_RECORDS`; requests are accepted while the company is active and during the `CANCELLED_READ_ONLY` window alike. The `FULL_LEDGER` scope is restricted to the `PRIMARY_ADMIN` — anyone else is refused with `ERR_EXPORT_SCOPE_REQUIRES_PRIMARY_ADMIN`, and advisor downloads additionally require a `FULL_BOOKKEEPING` grant. A request is born `PENDING`, becomes `READY` when the asynchronous render completes (simulated by the platform operator), which stamps `ready_at` and sets `download_expires_at` thirty days later. Downloading before that deadline moves the request to `DOWNLOADED`; a download attempted once the clock has passed `download_expires_at` is rejected with `ERR_WINDOW_EXPIRED` (HTTP 400), and a request not in `READY` hears `ERR_EXPORT_NOT_DOWNLOADABLE` (HTTP 400). Requests still `PENDING` or `READY` expire when the clock passes the download deadline or when the subscription reaches `CANCELLED_EXPIRED`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, trigger a state transition, or read data respond with HTTP 200. Every response uses the envelope of §2.2, and list endpoints honor the pagination and sorting rules of §2.3. Request payloads and per-endpoint behaviors are defined by the workflows of §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock; re-evaluates all time-driven transitions | PlatformAdmin |
| POST | /api/_payments/simulate | Simulate a payment outcome (SUCCEEDED, DECLINED, TIMEOUT) against an invoice | PlatformAdmin |
| POST | /api/_sync/bank_feed_tick | Run one bank-feed sync tick for a connection | PlatformAdmin |
| POST | /api/plans | Create a subscription plan tier | PlatformAdmin |
| GET | /api/plans/{id} | Get a plan | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/plans | List plans | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/firms | Register an accountant firm | PlatformAdmin |
| GET | /api/firms/{id} | Get a firm | PlatformAdmin, AccountantUser |
| POST | /api/firms/{id}/suspend | Suspend a firm (cascades to grants) | PlatformAdmin |
| POST | /api/firms/{id}/reactivate | Reactivate a suspended firm | PlatformAdmin |
| POST | /api/firms/{id}/close | Close a firm (terminal) | PlatformAdmin |
| POST | /api/firms/{id}/users | Create an accountant user under a firm | PlatformAdmin |
| GET | /api/firms/{id}/users | List users of a firm | PlatformAdmin, AccountantUser |
| GET | /api/firms/{id}/users/{user_id} | Get one accountant user | PlatformAdmin, AccountantUser |
| POST | /api/companies | Create a client company; auto-creates a TRIAL subscription | PlatformAdmin |
| GET | /api/companies/{id} | Get a company | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies | List companies; filterable by primary_admin_user_id | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/users | Invite a company user (seat-limit checked) | PlatformAdmin, CompanyUser |
| GET | /api/companies/{id}/users | List users of a company | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/users/{user_id} | Get one company user | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/users/{user_id}/accept | Accept invitation; INVITED to ACTIVE | CompanyUser |
| POST | /api/companies/{id}/users/{user_id}/disable | Disable a user (not the PRIMARY_ADMIN) | CompanyUser |
| GET | /api/companies/{id}/subscription | Get the company's subscription | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/subscription/activate | Activate trial (TRIAL to ACTIVE) | CompanyUser |
| POST | /api/companies/{id}/subscription/change_plan | Upgrade or downgrade plan (OCC on subscription version) | CompanyUser |
| POST | /api/companies/{id}/subscription/cancel | Cancel the subscription (PRIMARY_ADMIN only) | CompanyUser |
| POST | /api/companies/{id}/subscription/reactivate | Reactivate from CANCELLED_READ_ONLY within the window | CompanyUser |
| POST | /api/companies/{id}/subscription/resume | Resume from SUSPENDED after settling invoices | CompanyUser |
| POST | /api/companies/{id}/payroll | Activate the payroll add-on | CompanyUser |
| GET | /api/companies/{id}/payroll | Get the payroll add-on (tax_filing_status recomputed) | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/payroll/pause | Pause payroll | CompanyUser |
| POST | /api/companies/{id}/payroll/resume | Resume payroll | CompanyUser |
| POST | /api/companies/{id}/payroll/cancel | Cancel payroll (terminal) | CompanyUser |
| POST | /api/companies/{id}/payroll/employees | Add a payroll employee | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/payroll/employees | List payroll employees | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/payroll/employees/{eid} | Get one employee | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/payroll/employees/{eid}/terminate | Terminate an employee (OCC on add-on version) | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/invoices | List invoices for a company (filterable by invoice_status, subscription_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/invoices/{iid} | Get an invoice | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/invoices/{iid}/issue | Issue a DRAFT invoice (computes lines) | PlatformAdmin |
| POST | /api/companies/{id}/invoices/{iid}/pay | Mark invoice PAID | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/invoices/{iid}/void | Void an invoice | PlatformAdmin |
| POST | /api/companies/{id}/bank_connections | Create a bank feed connection | CompanyUser |
| GET | /api/companies/{id}/bank_connections | List connections | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/bank_connections/{bid} | Get a connection | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_connections/{bid}/authorize | Authorize a PENDING_AUTH connection | CompanyUser |
| POST | /api/companies/{id}/bank_connections/{bid}/reauthorize | Re-authorize a STALE connection | CompanyUser |
| POST | /api/companies/{id}/bank_connections/{bid}/disconnect | Disconnect (recoverable) | CompanyUser |
| POST | /api/companies/{id}/bank_connections/{bid}/revoke | Revoke permanently | CompanyUser |
| POST | /api/companies/{id}/bank_connections/{bid}/transactions | Ingest a bank transaction (runs the rule selector) | PlatformAdmin, CompanyUser |
| GET | /api/companies/{id}/bank_connections/{bid}/transactions | List transactions for a connection | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/bank_transactions | List transactions across connections (filtered) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/bank_transactions/{tid} | Get a transaction | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/categorize | Manually categorize (rule-free path) | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/accept_suggestion | Accept a RULE_SUGGESTED transaction | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/reject_suggestion | Reject a suggestion; back to UNCATEGORIZED | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/uncategorize | Return a CATEGORIZED transaction to UNCATEGORIZED | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/exclude | Exclude from reconciliation totals | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/bank_transactions/{tid}/unexclude | Restore an EXCLUDED transaction | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/categories | Create a category | CompanyUser |
| GET | /api/companies/{id}/categories | List categories | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/categorization_rules | Create an auto-categorization rule (tier-gated) | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/categorization_rules | List rules | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/categorization_rules/{rid} | Get a rule | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/categorization_rules/{rid}/pause | Pause a rule | CompanyUser |
| POST | /api/companies/{id}/categorization_rules/{rid}/resume | Resume a paused rule | CompanyUser |
| DELETE | /api/companies/{id}/categorization_rules/{rid} | Soft-delete a rule | CompanyUser |
| POST | /api/companies/{id}/reconciliations | Create a reconciliation (window overlap checked) | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/reconciliations | List reconciliations | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/reconciliations/{rid} | Get a reconciliation (difference recomputed) | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/reconciliations/{rid}/start | DRAFT to IN_PROGRESS (overlap re-checked) | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/reconciliations/{rid}/complete | Complete (requires zero difference) | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/reconciliations/{rid}/abandon | Abandon back to DRAFT | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/integrations | Link an app integration | CompanyUser |
| GET | /api/companies/{id}/integrations | List integrations | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/integrations/{iid} | Get an integration | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/integrations/{iid}/activate | LINKED to ACTIVE | CompanyUser |
| POST | /api/companies/{id}/integrations/{iid}/resume | CONFLICT_PAUSED to ACTIVE (zero conflicts required) | CompanyUser |
| POST | /api/companies/{id}/integrations/{iid}/disconnect | Disconnect an integration | CompanyUser |
| POST | /api/companies/{id}/integrations/{iid}/conflicts | Record a sync conflict (may auto-pause at three) | PlatformAdmin |
| GET | /api/companies/{id}/integrations/{iid}/conflicts | List conflicts for an integration | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/integrations/{iid}/conflicts/{cid}/resolve | Resolve a conflict (LOCAL, REMOTE, or IGNORE) | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/migration_jobs | Create a desktop-to-online migration job | PlatformAdmin, CompanyUser |
| GET | /api/companies/{id}/migration_jobs | List migration jobs | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/migration_jobs/{mid} | Get a migration job | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/migration_jobs/{mid}/start | QUEUED to CONVERTING | PlatformAdmin |
| POST | /api/companies/{id}/migration_jobs/{mid}/complete | Complete with outcome CLEAN, WITH_LIMITATIONS, or FAILED | PlatformAdmin |
| POST | /api/companies/{id}/migration_jobs/{mid}/cancel | Cancel a QUEUED or CONVERTING migration | PlatformAdmin, CompanyUser |
| POST | /api/companies/{id}/billing_transfers | Initiate a billing transfer (computes proforma) | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/billing_transfers | List billing transfers for a company | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/billing_transfers/{tid} | Get a billing transfer | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/billing_transfers/{tid}/accept | Client accepts transfer (PRIMARY_ADMIN; OCC) | CompanyUser |
| POST | /api/companies/{id}/billing_transfers/{tid}/counter | Client counters; moves to PENDING_FIRM_ACCEPT | CompanyUser |
| POST | /api/companies/{id}/billing_transfers/{tid}/decline | Either party declines (decline_reason required) | CompanyUser, AccountantUser |
| POST | /api/companies/{id}/billing_transfers/{tid}/cancel | Initiating party cancels | CompanyUser, AccountantUser |
| POST | /api/firms/{id}/billing_transfers/{tid}/accept | Firm accepts from PENDING_FIRM_ACCEPT | AccountantUser |
| POST | /api/companies/{id}/access_grants | Issue an access grant to an accountant | CompanyUser |
| GET | /api/companies/{id}/access_grants | List access grants | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/access_grants/{gid} | Get a grant | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/access_grants/{gid}/revoke | Client revokes a grant | CompanyUser |
| POST | /api/firms/{id}/access_grants/{gid}/accept | Accountant accepts a grant | AccountantUser |
| POST | /api/companies/{id}/exports | Request a data export | CompanyUser, AccountantUser |
| GET | /api/companies/{id}/exports | List export requests | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/companies/{id}/exports/{eid} | Get an export request | PlatformAdmin, CompanyUser, AccountantUser |
| POST | /api/companies/{id}/exports/{eid}/mark_ready | Simulate async render completing | PlatformAdmin |
| POST | /api/companies/{id}/exports/{eid}/download | Download (PRIMARY_ADMIN or FULL_BOOKKEEPING advisor) | CompanyUser, AccountantUser |
| GET | /api/subscriptions/{id} | Get a subscription by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/subscriptions | List subscriptions (filterable by company_id, plan_id, billing_firm_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/payroll_addons/{id} | Get a payroll add-on by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/payroll_addons | List payroll add-ons (filterable by subscription_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/payroll_employees/{id} | Get a payroll employee by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/payroll_employees | List payroll employees (filterable by payroll_addon_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/invoices/{id} | Get an invoice by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/invoices | List invoices (filterable by company_id, subscription_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/bank_transactions/{id} | Get a bank transaction by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/bank_transactions | List bank transactions (filterable by bank_connection_id, category_id, matched_rule_id, reconciled_in_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/categorization_rules/{id} | Get a categorization rule by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/categorization_rules | List categorization rules (filterable by company_id, assign_category_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/reconciliations/{id} | Get a reconciliation by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/reconciliations | List reconciliations (filterable by company_id, bank_connection_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/sync_conflicts/{id} | Get a sync conflict by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/sync_conflicts | List sync conflicts (filterable by app_integration_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/billing_transfers/{id} | Get a billing transfer by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/billing_transfers | List billing transfers (filterable by company_id, subscription_id, initiating_firm_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/access_grants/{id} | Get an access grant by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/access_grants | List access grants (filterable by company_id, accountant_user_id, firm_id) | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/export_requests/{id} | Get an export request by id | PlatformAdmin, CompanyUser, AccountantUser |
| GET | /api/export_requests | List export requests (filterable by company_id, requested_by_user_id) | PlatformAdmin, CompanyUser, AccountantUser |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined where the behavior lives — in §2 and §3 — not in this table.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_IDENTITY_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_INVALID_STATE_TRANSITION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_SUBSCRIPTION_NOT_WRITABLE | 400 |
| ERR_FEATURE_NOT_IN_TIER | 400 |
| ERR_SEAT_LIMIT_REACHED | 400 |
| ERR_REQUIRES_PRIMARY_ADMIN | 403 |
| ERR_TRIAL_EXPIRED | 400 |
| ERR_REACTIVATION_WINDOW_EXPIRED | 400 |
| ERR_PAYROLL_ALREADY_ACTIVE | 409 |
| ERR_PAYROLL_NOT_ACTIVE | 400 |
| ERR_PAYROLL_CANCEL_BLOCKED_BY_FILING | 400 |
| ERR_EMPLOYEE_ALREADY_TERMINATED | 400 |
| ERR_INVOICE_NOT_PAYABLE | 400 |
| ERR_BILLING_STATE_BLOCKED | 400 |
| ERR_TRANSFER_ALREADY_PENDING | 409 |
| ERR_TRANSFER_EXPIRED | 400 |
| ERR_FIRM_NOT_ACTIVE | 400 |
| ERR_CONNECTION_NOT_AUTHORIZABLE | 400 |
| ERR_CONSENT_EXPIRED | 400 |
| ERR_CONNECTION_ALREADY_EXISTS | 409 |
| ERR_TXN_LOCKED_BY_RECONCILIATION | 400 |
| ERR_STATEMENT_WINDOW_OVERLAP | 409 |
| ERR_RECON_DIFFERENCE_NOT_ZERO | 400 |
| ERR_RULE_NOT_PAUSABLE | 400 |
| ERR_RULE_NOT_RESUMABLE | 400 |
| ERR_INTEGRATION_NOT_ACTIVE | 400 |
| ERR_INTEGRATION_RESUME_BLOCKED | 400 |
| ERR_CONFLICT_NOT_OPEN | 400 |
| ERR_MIGRATION_ALREADY_IN_FLIGHT | 409 |
| ERR_MIGRATION_NOT_CANCELLABLE | 400 |
| ERR_GRANT_NOT_ACCEPTABLE | 400 |
| ERR_GRANT_NOT_REVOCABLE | 400 |
| ERR_DUPLICATE_ACTIVE_GRANT | 409 |
| ERR_EXPORT_NOT_DOWNLOADABLE | 400 |
| ERR_EXPORT_SCOPE_REQUIRES_PRIMARY_ADMIN | 403 |
| ERR_DUPLICATE | 409 |
| ERR_WINDOW_EXPIRED | 400 |
| ERR_COMPANY_READ_ONLY | 400 |
