# Managing Partner Equity API — Product Requirements Document

## 1. Introduction

Texas Roadhouse's managing partner program ties a partner's personal capital directly to the performance of a single restaurant: the partner posts a capital buy-in into escrow, operates the restaurant over a multi-year contract term, and earns a tiered share of restaurant-level profit that is computed from posted statement line items under explicit inclusion and exclusion rules. Above the single-restaurant layer, market partners oversee a group of restaurants and earn an override percentage on group profit. In-house meat cutting, partner conference invitations, and stock awards all feed back into the same profit math, and every number a partner sees is disputable within a fixed window.

This document specifies the Managing Partner Equity API, the system of record for that program. It governs the partner recruiting pipeline (candidacy, training tenure, certification, placement), the managing partner contract lifecycle (drafting, funding, activation, renewal, departure, buy-out, and transfer), restaurant profit accounting in two variants (provisional and final) over the same posted data, per-cut yield standards with waste accountability, award programs funded by performance, and the dispute process that lets a managing partner challenge a finalized profit figure before it is locked.

Because money moves on nearly every transition, the system is strict about who may do what and when: funding deadlines are enforced by a logical clock, departure valuation follows a pinned waterfall, rounding is pinned to per-tier and per-batch half-up rules, and three write paths carry optimistic concurrency tokens so that a stale reader cannot overwrite a contract or period it has not observed. All temporal behavior — funding lapse, contract expiry, agreement expiry, grant vesting, training extension, and dispute escalation — is driven by an explicitly set logical clock rather than wall-clock time, so the entire program is reproducible in test.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across the entire API, independent of any single workflow.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are present, the role is checked against the endpoint's authorized set; a role not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes six roles, spelled exactly as follows:

- `PlatformAdmin` — corporate platform operator; owns the logical clock, market groups, and restaurants.
- `HRRecruiter` — owns the partner recruiting pipeline and training tenure.
- `CorporateController` — corporate finance and legal; owns contracts, buyouts, market partner agreements, period finalization and locking, yield standards, waivers, award programs and grants, and dispute resolution.
- `ManagingPartner` — a partner running one restaurant; funds the buy-in, accepts renewals, initiates departure, and files and manages their own disputes.
- `MarketPartner` — a partner overseeing a market group; read access to group performance, agreements, and awards.
- `OperationsAuditor` — operational finance auditor; opens profit periods, posts and finalizes line items, runs compute, and records and audits meat cut batches.

Two of the roles are entity-backed. When `X-User-Role` is `ManagingPartner`, `X-User-ID` is the `id` of the acting `Partner`; ownership checks on any resource that references a `Partner` (a contract's `partner_id`, a dispute's `filed_by_partner_id`) compare that foreign-key field to `X-User-ID`. The same holds when `X-User-Role` is `MarketPartner`: `X-User-ID` is the `id` of the acting `Partner`, and any ownership comparison uses the resource's partner foreign key against `X-User-ID`. The remaining four roles — `PlatformAdmin`, `HRRecruiter`, `CorporateController`, and `OperationsAuditor` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it against any entity's `id`.

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

Endpoints returning collections accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer starting at 1 on creation and incremented by exactly 1 on every mutation of the resource, including mutations performed as side effects of state transitions and cascades. All fourteen entities in this API — partners, market groups, restaurants, contracts, buy-in payments, market partner agreements, profit periods, statement line items, yield standards, meat cut batches, award programs, award grants, dispute cases, and buyout orders — carry this full common set.

Time inside the system is governed by a **logical clock**, not wall-clock time. Before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `current_utc` instant; the response echoes `current_utc` and reports `sweeps_applied`, the count of scheduled sweeps the advancement fired. Setting the clock fires every time-based sweep in the system: contract funding lapse, contract expiry at term end, market partner agreement expiry, grant vesting, partner training extension, and dispute escalation. All timestamps the system writes — `submitted_at`, `training_started_at`, `certified_at`, `filed_at`, `finalized_at` — read the logical clock, never the wall clock.

### 2.5. Validation Ordering

When a request violates several rules at once, the error the caller receives is determined by a fixed priority order, evaluated from first to last:

1. **Authentication context** — presence of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization** — the role's permission for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Path existence** — each identifier in the URL path must resolve, validated left to right; the first unresolvable identifier yields its specific not-found error (for example `ERR_PARTNER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_RESTAURANT_NOT_FOUND`, `ERR_MARKET_GROUP_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_YIELD_STANDARD_NOT_FOUND`, `ERR_BUYOUT_NOT_FOUND`).
4. **Body reference existence** — foreign keys supplied in the request body (`partner_id`, `restaurant_id`, `market_group_id`, `source_period_id`, `profit_period_id`, `cut_code`) must resolve to existing resources (`ERR_REFERENCE_NOT_FOUND`).
5. **State** — the target resource must be in a from-state that permits the requested transition (`ERR_INVALID_STATE`), and the more specific state-gate errors such as `ERR_CONTRACT_NOT_FUNDABLE`, `ERR_CONTRACT_NOT_IN_BUYOUT`, `ERR_PERIOD_NOT_OPEN`, `ERR_DISPUTE_NOT_OWNED`, and `ERR_CONTRACT_PARTNER_MISMATCH`. The optimistic concurrency check (`ERR_STALE_VERSION`, HTTP 412) is part of this layer and is evaluated **after** from-state validity — a request that fails the from-state gate never reaches the version check.
6. **Temporal rules** — interval and clock rules such as the period entry cutoff, the dispute window, the funding window, and training tenure (`ERR_PERIOD_CLOSED_FOR_ENTRIES`, `ERR_DISPUTE_WINDOW_CLOSED`, `ERR_FUNDING_WINDOW_LAPSED`, `ERR_TRAINING_TENURE_INSUFFICIENT`). Temporal checks run **before** aggregate and capacity checks; in particular, when a dispute filing is both late and duplicative, `ERR_DISPUTE_WINDOW_CLOSED` is returned rather than `ERR_DUPLICATE_OPEN_DISPUTE`.
7. **Cross-entity referential rules** — rules that join one aggregate to another, such as the restaurant being open, a live contract existing on the restaurant, market group activation, coverage overlap, batch-period restaurant matching, award source period eligibility, and successor eligibility (`ERR_RESTAURANT_NOT_ACTIVE`, `ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT`, `ERR_MARKET_GROUP_NOT_ACTIVE`, `ERR_OVERRIDE_COVERAGE_OVERLAP`, `ERR_BATCH_PERIOD_RESTAURANT_MISMATCH`, `ERR_AWARD_SOURCE_PERIOD_INELIGIBLE`, `ERR_SUCCESSOR_NOT_ELIGIBLE`, `ERR_NOT_MANAGING_PARTNER`, `ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT`, `ERR_DUPLICATE_OPEN_DISPUTE`).
8. **Structural constraints** — malformed fields, bad enums, inverted date intervals, non-positive amounts, out-of-range percentages (`ERR_INVALID_REQUEST`).
9. **Aggregate and capacity checks** — fiscal and pool checks that depend on totals: buy-in completeness, unfinalized line items, award pool capacity, award eligibility, offset size, and adjustment presence (`ERR_BUY_IN_INCOMPLETE`, `ERR_UNFINALIZED_LINE_ITEMS`, `ERR_AWARD_POOL_EXHAUSTED`, `ERR_AWARD_NOT_ELIGIBLE`, `ERR_OFFSET_EXCEEDS_PAYOUT`, `ERR_ADJUSTMENT_REQUIRED`).

### 2.6. Monetary Representation, Precision, and Rounding Discipline

All monetary values are integer cents — there are no decimal-dollar fields anywhere in the API. Monetary aggregation (the profit computation itself) involves no rounding: cents sum exactly. Rounding is applied only at three pinned points, always using the round-half-up method: (a) per-category subtotals in the profit computation are rounded to integer cents **before** the subtotals are summed — sum-then-round is forbidden; (b) each tier of the managing partner share is rounded to integer cents **before** the tiers are summed — again, sum-then-round is forbidden; and (c) each meat batch's waste charge is rounded per batch to integer cents, never across a consolidated set of batches. Weights are recorded at three decimal places. The award eligibility score is the one non-monetary number with a rounding rule: it is rounded half-up to two decimal places. Percentages such as `override_pct` and the yield standard percentages are numbers preserving input precision.

### 2.7. Optimistic Concurrency Control

Three write endpoints in the system require the caller to prove it has observed the current state of the parent entity it is writing against. Each takes a non-optional version field in the request body, and a mismatch with the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Posting a statement line item to a profit period requires `expected_profit_period_version`, matching the period's current `version`. If another writer has advanced the period's version since the client last read it — for example by posting a line item of their own — the posting client's computed subtotal context is stale and the create is rejected.
- Running a profit computation on a period requires `expected_profit_period_version` under the same rule: two writers who both observed version N may both legitimately request a compute, but the first compute advances the version, so the second request arrives stale and is rejected.
- Creating a buyout order against a contract requires `expected_contract_version`, matching the contract's current `version`. A departure, renewal, or any other contract mutation that has advanced the version since the writer priced the buyout causes the create to be rejected, preventing the writer from pricing against a contract state it has not observed.

Endpoints not named above do not take a version field. The OCC check is a state-layer check: it runs only after the request has passed the from-state gate for the transition being requested.

### 2.8. Hierarchical Consistency, Cascades, and Cross-Aggregate Propagation

The system's entities are peers joined by foreign keys rather than nested URL hierarchies, but mutations still propagate across aggregate boundaries, and every propagation is explicit and immediate. When a paid buyout settles a contract, the contract moves to `SETTLED`, the partner is withdrawn, and the withdrawal in turn forfeits every not-yet-vested award grant the partner holds, crediting each grant's reserved units back to its program's pool — a cascade three levels deep that fires as a single chain. When a dispute is resolved with an adjustment, the finalized period beneath it reopens and a new adjustment line item appears on that period. When a funding window lapses, the escrow unwinds payment by payment and the candidate partner is withdrawn. In every case, each mutated entity's own `updated_at` refreshes and its own `version` increments by 1; cascades never silently reuse a parent's version bump.

State alignment also flows upward and outward: activating a fully funded contract places the partner; expiring or transferring a contract returns the partner to the certified pool; closing out the last obligation on a period locks it terminally. Conversely, dependent operations are blocked while their prerequisites are unmet — a restaurant cannot close while an open contract references it, a period cannot lock while a dispute on it is open, and a renewal or departure cannot proceed while any dispute on the restaurant's periods is unresolved.

### 2.9. Profit Accounting: Two Variants over the Same Posted Data

Restaurant profit is computed in two variants that share one aggregation shape and differ on exactly two axes. The **provisional variant**, run by the compute action, includes line items in either `PROVISIONAL` or `FINALIZED` entry status and reads each item's `amount_cents`. The **final variant**, run by the finalize action, includes only `FINALIZED` line items and reads each item's `actual_amount_cents`. Both variants sum the partner-basis revenue and adjustment items, subtract the partner-basis expense items (cost of goods, labor, the corporate marketing fee, and any meat waste charge line items), and then subtract the consolidated meat waste charge computed from the period's audited batches.

The partner-basis concept is the system's answer to the question "which corporate charges does the partner actually bear?". Every line item carries a computed `partner_basis` flag: `CORPORATE_ADMIN_FEE` items are the excluded corporate charge — their basis is `EXCLUDED` and they are skipped entirely in both variants, in both the revenue side and the expense side. Every other category is `INCLUDED`. Because the waste charge enters the final profit as a separate consolidated deduction computed from batch rows — never as a line item on the statement — the waste charge never feeds back into its own base, pinning what would otherwise be a circular dependency.

### 2.10. Program-Wide Constants

The following constants govern temporal windows, training tenure, and financial tiers throughout the system:

- The funding window for a submitted contract is 14 days from `submitted_at`.
- An accepted renewal extends the contract term by 2 years.
- Certification requires at least 52 full weeks of accrued training; a partner still in training beyond 78 accrued weeks is flagged with an extended status.
- A finalized period may be disputed within 30 days of finalization.
- An evidence request left unanswered for more than 45 days after filing escalates the dispute.
- A stock grant vests 365 days after the grant's creation date.
- The managing partner share tiers split the final profit at $50,000.00 and $100,000.00 (5,000,000 and 10,000,000 cents), at rates of 8%, 10%, and 12%.
- Award scoring is measured against a sales target of $200,000.00 (20,000,000 cents), a profit margin target of 10%, and a waste allowance of $5,000.00 (500,000 cents), with stock tiers at scores of 80 and 90.

## 3. Business Logic & Workflows

### 3.1. The Partner Pipeline: Recruiting, Training Tenure, and Certification

Every partner enters the system when an `HRRecruiter` registers a candidate with a `full_name`, a unique contact `email`, and a `role_in_program` of either `MANAGING_PARTNER` or `MARKET_PARTNER`. The role choice is immutable after creation. A new partner begins in `CANDIDATE` status.

An `HRRecruiter` begins training tenure by starting training on a candidate, which moves the partner to `IN_TRAINING` and stamps `training_started_at` with the logical clock. From that moment the partner's `training_weeks_accrued` is a computed figure: the number of full seven-day weeks elapsed between `training_started_at` and the logical clock, using floor division with no rounding up — six days and twenty-three hours of training is zero weeks. The figure is recomputed on every read of the partner; when `training_started_at` has never been set, the accrued weeks are zero.

Certification is the tenure gate. An `HRRecruiter` certifies a partner in `IN_TRAINING` or `TRAINING_EXTENDED`, but only once `training_weeks_accrued` has reached at least 52 weeks; certifying earlier is rejected with `ERR_TRAINING_TENURE_INSUFFICIENT`. A successful certification stamps `certified_at` with the logical clock and moves the partner to `CERTIFIED`. Training is not allowed to drift silently: when a partner still in `IN_TRAINING` passes 78 accrued weeks, the clock sweep moves them to `TRAINING_EXTENDED`. The extension is informational only — certification from `TRAINING_EXTENDED` remains permitted under the same 52-week rule.

Placement is not a direct action. When a managing partner contract activates (see §3.3), the system moves the partner from `CERTIFIED` to `PLACED` and sets `placed_restaurant_id` to the contract's restaurant. The reverse also flows from contract events: when a contract expires at term end, or when the contract is transferred to a successor, the partner returns from `PLACED` to `CERTIFIED` and `placed_restaurant_id` is cleared, putting the partner back into the certified pool.

An `HRRecruiter` may withdraw a partner from any of `CANDIDATE`, `IN_TRAINING`, `TRAINING_EXTENDED`, or `CERTIFIED`, moving the partner to the terminal `WITHDRAWN` state. A partner who is `PLACED` cannot be withdrawn directly; they leave the system through contract events — a paid buyout that settles the contract, or a lapsed funding window — which move them from `PLACED` to `WITHDRAWN` automatically. Either path to `WITHDRAWN` fires the award forfeiture cascade described in §3.7.

### 3.2. Market Groups, Restaurants, and Market Partner Oversight

A `PlatformAdmin` creates a market group with a `name`; it begins in `FORMING`. A restaurant is created with a `name`, `city`, two-letter `state_code`, and an optional `market_group_id` assigning it to a group at creation; it begins in `PRE_OPENING`. The `PlatformAdmin` opens a restaurant by moving it from `PRE_OPENING` to `ACTIVE`, and activates a market group from `FORMING` to `ACTIVE` — group activation requires at least one `ACTIVE` restaurant assigned to the group. Closing a restaurant moves it from `ACTIVE` to `CLOSED`, but the close is blocked with `ERR_RESTAURANT_HAS_OPEN_CONTRACTS` while any contract on the restaurant sits in `PENDING_FUNDING`, `ACTIVE`, `RENEWAL_OFFERED`, or `BUYOUT_PENDING`.

A `CorporateController` drafts a market partner agreement naming a `partner_id` (which must reference a partner whose `role_in_program` is `MARKET_PARTNER`), a `market_group_id`, a coverage window from `coverage_start_date` to `coverage_end_date`, an `override_pct`, and a `basis`. The coverage window is a **closed** interval — inclusive at both ends — and `coverage_end_date` must be on or after `coverage_start_date`. The override percentage must be greater than 0 and at most 10. The `basis` selects the override variant: `NET_GROUP_BASIS` or `PER_RESTAURANT_POSITIVE`. A new agreement begins in `DRAFT`.

Activating an agreement is guarded by two rules. First, the market group must be `ACTIVE`, or the activation is rejected with `ERR_MARKET_GROUP_NOT_ACTIVE`. Second, coverage must be unique: no other agreement in `DRAFT` or `ACTIVE` for the same market group may have a coverage interval that intersects this agreement's interval — intersection is evaluated with both intervals treated as closed, inclusive at both ends — or the activation is rejected with `ERR_OVERRIDE_COVERAGE_OVERLAP`. Activation moves the agreement from `DRAFT` to `ACTIVE`.

Agreements end in two ways. The clock sweep moves an `ACTIVE` agreement to `EXPIRED` once the logical clock's date passes the `coverage_end_date`. A `CorporateController` may also terminate an agreement from either `DRAFT` or `ACTIVE`, moving it to `TERMINATED`. Both end states are terminal.

### 3.3. The Managing Partner Contract: Drafting, Funding, and Activation

A `CorporateController` creates a managing partner contract by naming a `partner_id` and a `restaurant_id` — both immutable after creation — together with the `term_start_date`, the `term_end_date`, and the `buy_in_required_cents`. The term is a **half-open** interval: it begins on `term_start_date` and ends just before `term_end_date`, so `term_end_date` is exclusive and must be strictly after `term_start_date`. The required buy-in must be greater than zero. A new contract begins in `DRAFT` with `buy_in_escrow_cents` at 0, `capital_account_cents` at 0, `renewed_count` at 0, and `submitted_at` and `departure_date` unset. Contracts are immutable once created — there is no edit transition; a changed term requires a new contract.

Submitting a contract moves it from `DRAFT` to `PENDING_FUNDING` and stamps `submitted_at` with the logical clock. Submission is guarded, and the guards have an order within the referential layer: the contract's partner must have `role_in_program` of `MANAGING_PARTNER` (otherwise `ERR_NOT_MANAGING_PARTNER`), no other contract for the same restaurant may already exist in `PENDING_FUNDING`, `ACTIVE`, `RENEWAL_OFFERED`, or `BUYOUT_PENDING` (otherwise `ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT`), and the restaurant must be `ACTIVE` (otherwise `ERR_RESTAURANT_NOT_ACTIVE`).

Once a contract is pending funding, the managing partner funds the buy-in escrow by posting payments, each carrying an `amount_cents` greater than zero. The funding partner must be the contract's own partner — the request is rejected with `ERR_CONTRACT_PARTNER_MISMATCH` when `X-User-ID` does not equal the contract's `partner_id`. Each posted payment is bound to its contract through a `contract_id` taken from the path, begins in `POSTED` status, and adds its amount to the contract's `buy_in_escrow_cents`. Overpayment is rejected: a payment that would push the escrow above `buy_in_required_cents` fails with `ERR_BUY_IN_OVERPAYMENT`, so the escrow never exceeds the requirement.

Activation is the moment the escrow becomes restaurant capital. A `CorporateController` activates a fully funded contract, but two gates apply in sequence. The state gate fires first: if `buy_in_escrow_cents` is zero, activation is rejected with `ERR_CONTRACT_NOT_FUNDABLE`. The fiscal check follows: if the escrow is greater than zero but still below `buy_in_required_cents`, activation is rejected with `ERR_BUY_IN_INCOMPLETE`. Timing matters as well — activation after the funding window has run out is rejected with `ERR_FUNDING_WINDOW_LAPSED`; the funding window is 14 days from `submitted_at`. When activation succeeds, the escrow balance moves wholesale: `capital_account_cents` takes the full escrow amount, `buy_in_escrow_cents` resets to 0, the partner's `placed_restaurant_id` is set to the contract's restaurant, and the partner moves from `CERTIFIED` to `PLACED`. The contract is now `ACTIVE`.

If the funding window lapses before activation, the clock sweep moves the contract from `PENDING_FUNDING` to `LAPSED` and unwinds the escrow: every `POSTED` buy-in payment on the contract flips to `REFUNDED`, `buy_in_escrow_cents` resets to 0, and the partner moves to `WITHDRAWN` — which in turn forfeits their unvested award grants per §3.7.

### 3.4. Renewal, Expiry, Departure, Buy-Out, and Transfer

A contract in `ACTIVE` may be offered a renewal by a `CorporateController`, moving it to `RENEWAL_OFFERED`. The offer is blocked while any dispute on any profit period of the contract's restaurant sits in `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `ESCALATED`; the rejection is `ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE`. Acceptance belongs to the partner: the managing partner accepts the renewal, and the request is rejected with `ERR_CONTRACT_PARTNER_MISMATCH` if the caller is not the contract's partner. Acceptance moves the contract back to `ACTIVE`, extends `term_end_date` by 2 years, and increments `renewed_count` by 1. This loop is cyclic and unbounded — renewal may be offered and accepted repeatedly, and `renewed_count` grows without limit.

Expiry is the clock's doing. Whether a contract is `ACTIVE` or `RENEWAL_OFFERED`, once the logical clock's date reaches the `term_end_date`, the sweep moves the contract to `EXPIRED` and returns the partner from `PLACED` to `CERTIFIED`, clearing their placement.

Departure begins with the partner. A managing partner initiates departure on their own `ACTIVE` contract — again guarded by `ERR_CONTRACT_PARTNER_MISMATCH` on the partner identity — which records `departure_date` as the logical clock's date and moves the contract to `BUYOUT_PENDING`. Like renewal, departure is blocked while any open dispute exists on the restaurant's periods, with `ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE`.

From `BUYOUT_PENDING` there are exactly two exits, and they are mutually exclusive. The **buy-out** path starts when a `CorporateController` prices and creates a buyout order against the contract, supplying an `offset_cents` for outstanding debits (zero or more) and the `expected_contract_version` OCC token (§2.7). Order creation is only valid while the contract is in `BUYOUT_PENDING`; otherwise it is rejected with `ERR_CONTRACT_NOT_IN_BUYOUT`. The valuation runs at creation and its evaluation order is pinned. First, `capital_return_cents` is the straight-line depreciated buy-in: the elapsed term fraction is the number of days from `term_start_date` to `departure_date` — clamped so it never falls below zero days and never exceeds the total term length in days — divided by the total days from `term_start_date` to `term_end_date`; the returned capital is the `buy_in_required_cents` multiplied by the remaining (un-elapsed) fraction, rounded half-up to integer cents. A departure on the very first day returns the full buy-in; a departure on or after the term end returns zero, never a negative amount. Second, `accrued_share_cents` is the sum of `partner_share_cents` over the contract's restaurant's profit periods that are `FINALIZED` or `LOCKED`, have `partner_share_paid` false, and have a `period_end_date` on or before the `departure_date`. Third, `total_payout_cents` is the capital return plus the accrued share minus the offset. The offset may not exceed the sum of the capital return and the accrued share; an offset that does is rejected with `ERR_OFFSET_EXCEEDS_PAYOUT`, which guarantees the total payout is never negative. The conservation invariant holds by construction: capital return plus accrued share always equals total payout plus offset.

Approval moves a buyout order from `DRAFT` to `APPROVED`, guarded by the contract being in `BUYOUT_PENDING` (`ERR_CONTRACT_NOT_IN_BUYOUT`). Payment moves it from `APPROVED` to `PAID` and fires the depth-3 cascade: the contract moves from `BUYOUT_PENDING` to `SETTLED`, its `capital_account_cents` returns to 0, the partner moves from `PLACED` to `WITHDRAWN` — cascading award forfeiture per §3.7 — and every profit period whose accrued share was swept into the order has its `partner_share_paid` set to true, so a period's share can never be paid out twice.

The **transfer** path is chosen instead when a successor waits. A `CorporateController` transfers the contract by naming a `successor_partner_id`. The successor must exist with `role_in_program` of `MANAGING_PARTNER` and status `CERTIFIED` — otherwise `ERR_SUCCESSOR_NOT_ELIGIBLE` — and no buyout order may already exist on the contract in `DRAFT` or `APPROVED`, or the transfer is rejected with `ERR_BUYOUT_ALREADY_OPEN`. On transfer, the old partner moves from `PLACED` back to `CERTIFIED` with `placed_restaurant_id` cleared; the successor moves from `CERTIFIED` to `PLACED` with `placed_restaurant_id` set to the restaurant; and a brand-new contract row is created in `DRAFT` for the successor on the same restaurant with a fresh term starting at the logical clock's date. The old contract row closes terminally as `TRANSFERRED`. Transfer settles nothing: there is no capital return — the successor's new contract carries its own buy-in.

### 3.5. Profit Periods and Statement Line Items

An `OperationsAuditor` opens a profit period for a restaurant by supplying a `restaurant_id`, a `period_start_date` (inclusive), and a `period_end_date` (exclusive, and strictly after the start). The period begins in `OPEN`. Periods of one restaurant may not overlap: a new period whose half-open interval intersects any existing non-`LOCKED` period of the same restaurant is rejected with `ERR_PERIOD_OVERLAP`; half-open adjacency — one period's start equal to another's end — is allowed.

While a period is `OPEN`, the `OperationsAuditor` posts statement line items to it. Each line item carries a `category` — one of `REVENUE`, `COST_OF_GOODS`, `LABOR`, `CORPORATE_ADMIN_FEE`, `CORPORATE_MARKETING_FEE`, `MEAT_WASTE_CHARGE`, or `ADJUSTMENT` — an `amount_cents`, an `entry_status` of `PROVISIONAL` or `FINALIZED`, and the `expected_profit_period_version` OCC token (§2.7). The signing convention is uniform: `REVENUE` and `ADJUSTMENT` amounts are positive contributions, while expense categories carry their positive magnitude and are subtracted by the computation. Posting is rejected once the logical clock's date has passed the `period_end_date`, with `ERR_PERIOD_CLOSED_FOR_ENTRIES`; posting also requires the period to be `OPEN`. Every posted line item is a mutation of its parent period, advancing the period's `version` — which is exactly what makes a second poster's OCC token stale.

A line item posted as `PROVISIONAL` carries its estimate in `amount_cents`, and its `actual_amount_cents` equals `amount_cents` until it is finalized. The `OperationsAuditor` finalizes a provisional line item by recording its `actual_amount_cents`, which moves the item's `entry_status` from `PROVISIONAL` to `FINALIZED`. Final profit accounting reads only these actualized figures.

Every line item also carries a computed `partner_basis` per §2.9: `EXCLUDED` for `CORPORATE_ADMIN_FEE` — the excluded corporate charge that partners never bear — and `INCLUDED` for every other category.

### 3.6. Computing, Finalizing, Reopening, and Locking a Period

The provisional computation is run by an `OperationsAuditor` against an `OPEN` or `REOPENED` period, carrying the `expected_profit_period_version` token. Two referential gates apply: the restaurant must be `ACTIVE` (`ERR_RESTAURANT_NOT_ACTIVE`), and a contract for the restaurant must exist in `ACTIVE`, `RENEWAL_OFFERED`, or `BUYOUT_PENDING` (`ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT`). The computation aggregates per §2.9's provisional variant — provisional and finalized items, reading `amount_cents` — and writes the result to `provisional_profit_cents`, moving the period to `COMPUTED`.

Finalization belongs to the `CorporateController` and is the heaviest single transition in the system. It requires that no line item on the period remains `PROVISIONAL` — any unfinalized item blocks with `ERR_UNFINALIZED_LINE_ITEMS` — and again that an active-family contract exists on the restaurant (`ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT`). On success, four figures are written in one step:

1. `final_distributable_profit_cents` — the final variant of the profit computation: only `FINALIZED` line items, reading `actual_amount_cents`, minus the consolidated meat waste charge — the sum of `waste_charge_cents` over the period's batches in `AUDITED_CONFORMING` or `VARIANCE_CONFIRMED` status (waived batches contribute nothing because their charge was zeroed and their status no longer qualifies).
2. `partner_share_cents` — the tiered managing partner share. The tiers are marginal, not average-rate: 8% of the first 5,000,000 cents of final profit, 10% of the next band up to 10,000,000 cents, and 12% of everything above 10,000,000 cents. Each tier's marginal amount is rounded half-up to integer cents **before** the tiers are summed. When the final profit is zero or negative, the partner share is zero.
3. `market_override_cents` — the market partner override attributable to this period's restaurant (see §3.8); zero when no `ACTIVE` agreement covers the restaurant's group at period end.
4. `corporate_retained_cents` — the remainder bucket: the final distributable profit minus the partner share minus the market override. This allocation conservation invariant always holds.

Finalization also stamps `finalized_at` with the logical clock and computes `dispute_deadline` as exactly 30 days after `finalized_at`; disputes are accepted while the logical clock is on or before the deadline. The period is now `FINALIZED`.

A finalized period can reopen — but only through the dispute process. When a dispute on the period resolves as `RESOLVED_ADJUSTED` (§3.9), the period moves from `FINALIZED` to `REOPENED` and a new line item appears on it automatically: category `ADJUSTMENT`, `amount_cents` equal to the dispute's `adjustment_cents`, and `entry_status` already `FINALIZED`. From `REOPENED`, the `OperationsAuditor` re-runs the provisional computation, which now includes the adjustment line, and the period returns to `COMPUTED` — ready for a fresh finalization. The loop finalize → dispute → reopen → recompute → re-finalize is cyclic by design.

Locking is terminal. A `CorporateController` locks a `FINALIZED` period, but only while no dispute on the period sits in `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `ESCALATED` — otherwise the lock is rejected with `ERR_OPEN_DISPUTE_BLOCKS_LOCK`. A `LOCKED` period may not be disputed or reopened; locked periods are excluded from buyout accrual unless their share was already swept by a paid buyout.

### 3.7. Yield Standards, Meat Cutting, and Waste Accountability

In-house meat cutting is governed by yield standards. A `CorporateController` creates a standard with a `cut_code` (for example `SIRLOIN_8OZ`), an `expected_yield_pct` (the expected sellable fraction of sub-primal weight, greater than 0 and less than 100), a `waste_tolerance_pct` (a buffer over expected waste, zero or more), and a `standard_cost_per_lb_cents` (the cost basis per excess-waste pound, greater than 0). A new standard is `active` by default. The cut code must be unique among active standards — creating a duplicate active cut code is rejected with `ERR_DUPLICATE_CUT_CODE`. Deactivating a standard sets `active` to false.

An `OperationsAuditor` records a meat cut batch with a `restaurant_id`, a `profit_period_id`, a `cut_code`, and a `sub_primal_weight_lbs` given at three decimal places and greater than zero. The period referenced must belong to the same restaurant — a mismatch is rejected with `ERR_BATCH_PERIOD_RESTAURANT_MISMATCH` — the period must be in `OPEN`, `COMPUTED`, or `REOPENED` (otherwise `ERR_PERIOD_NOT_OPEN`), and the cut code must match an active yield standard (otherwise `ERR_UNKNOWN_CUT_CODE`). A new batch begins in `RECORDED`, with `actual_yield_lbs` unset.

The audit is where waste accountability bites. An `OperationsAuditor` audits a `RECORDED` batch by recording the `actual_yield_lbs`; the same period-state gate applies (`ERR_PERIOD_NOT_OPEN`). The waste math then runs against the batch's active yield standard, in this order: the expected yield in pounds is the sub-primal weight multiplied by the expected yield percentage divided by 100; the expected waste is the sub-primal weight minus that expected yield; the allowed waste is the expected waste multiplied by one plus the tolerance percentage divided by 100; the batch's `actual_waste_lbs` is the sub-primal weight minus the recorded actual yield; and the `excess_waste_lbs` is the amount by which the actual waste exceeds the allowed waste, never below zero. The boundary is inclusive on the conforming side: when actual waste equals allowed waste exactly, the excess is zero.

Two outcomes branch off the excess. When the excess is zero, the batch becomes `AUDITED_CONFORMING` and its `waste_charge_cents` is 0. When the excess is greater than zero, the batch becomes `VARIANCE_CONFIRMED` and its `waste_charge_cents` is the excess waste in pounds multiplied by the standard's `standard_cost_per_lb_cents`, rounded half-up to integer cents for this batch alone — per-batch rounding, pinned, never consolidated before rounding.

A confirmed variance can be forgiven. A `CorporateController` waives a `VARIANCE_CONFIRMED` batch — again subject to the period-state gate — moving it to `VARIANCE_WAIVED` and resetting its `waste_charge_cents` to 0. Waiving is compensation: the charge is removed from the consolidated waste deduction at period finalize, and the batch remains terminally `VARIANCE_WAIVED`. All three audit outcomes are terminal states for the batch.

### 3.8. The Market Partner Override

When a period finalizes, the system determines the market partner override attributable to that period's restaurant. The candidate agreement is the one `ACTIVE` market partner agreement whose `market_group_id` equals the restaurant's `market_group_id` and whose closed coverage interval — inclusive at both `coverage_start_date` and `coverage_end_date` — covers the period's `period_end_date`. Uniqueness is guaranteed by the overlap validation enforced at activation. When no such agreement exists, `market_override_cents` is 0.

The agreement's `basis` selects between two variants. Under `NET_GROUP_BASIS`, the restaurant's attributable share of group profit is the period's `final_distributable_profit_cents` divided by the group restaurant count — the number of restaurants in the group whose status is `ACTIVE` at finalize time — and the override is the agreement's `override_pct` percentage of that attributable share, rounded half-up to integer cents and floored at zero: a negative restaurant profit contributes a negative share, which floors the override at 0. Under `PER_RESTAURANT_POSITIVE`, the override is the `override_pct` percentage of this restaurant's own positive profit — the final distributable profit floored at zero — rounded half-up. The two variants diverge whenever the group has more than one active restaurant or the restaurant's profit is negative.

### 3.9. Disputes: Filing, Evidence Rounds, Escalation, and Resolution

A managing partner who disputes a finalized profit figure files a dispute case with a `period_id` and a `claim_text`. The period must be `FINALIZED`. The filer must be the partner of the restaurant's active-family contract — a mismatch is rejected with `ERR_CONTRACT_PARTNER_MISMATCH` — and the filing partner's identity is recorded from `X-User-ID` into `filed_by_partner_id`, with `filed_at` stamped from the logical clock. Filing is closed once the logical clock passes the period's `dispute_deadline` — 30 days after `finalized_at` — with `ERR_DISPUTE_WINDOW_CLOSED`; and a period may host only one open dispute at a time, so a filing while another dispute on the period sits in `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `ESCALATED` is rejected with `ERR_DUPLICATE_OPEN_DISPUTE`. When both violations apply, the window error wins (§2.5). A new dispute lands in `SUBMITTED` and immediately, automatically, moves to `UNDER_REVIEW`.

Review is a dialogue. A `CorporateController` may request evidence, moving the dispute from `UNDER_REVIEW` to `EVIDENCE_REQUESTED`. The filing partner answers by submitting evidence — a request carrying `evidence_text`, permitted only when `X-User-ID` matches the dispute's `filed_by_partner_id` (otherwise `ERR_DISPUTE_NOT_OWNED`) — which returns the dispute to `UNDER_REVIEW`. This evidence loop is cyclic: multiple rounds of request and submission are allowed. If an evidence request goes unanswered until the logical clock passes 45 days after `filed_at` while the dispute still sits in `EVIDENCE_REQUESTED`, the clock sweep escalates the dispute to `ESCALATED`. Escalation is not terminal — resolution remains available from `ESCALATED` exactly as from `UNDER_REVIEW`.

Resolution belongs to the `CorporateController` and takes an `outcome` of `UPHELD` or `ADJUSTED`. Resolving as `UPHELD` moves the dispute to `RESOLVED_UPHELD` and leaves the profit period untouched — the original computation stands. Resolving as `ADJUSTED` requires a positive `adjustment_cents` — omitting it or supplying a non-positive value is rejected with `ERR_ADJUSTMENT_REQUIRED` — and moves the dispute to `RESOLVED_ADJUSTED`: the adjustment is recorded on the dispute, and the cascade of §3.6 fires, reopening the period from `FINALIZED` to `REOPENED` and creating the finalized `ADJUSTMENT` line item carrying the adjustment amount. Both resolutions are terminal for the dispute. Alternatively, the filing partner may withdraw a dispute while it is in `SUBMITTED`, `UNDER_REVIEW`, or `EVIDENCE_REQUESTED` — guarded by the same ownership check (`ERR_DISPUTE_NOT_OWNED`) — moving it to `WITHDRAWN`.

Disputes hold the rest of the program still: an open dispute on any of a restaurant's periods blocks renewal offers (`ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE`) and departures (`ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE`) on the restaurant's contract, and an open dispute on a period blocks that period's lock (`ERR_OPEN_DISPUTE_BLOCKS_LOCK`).

### 3.10. Award Programs, Eligibility Scoring, and Grant Vesting

A `CorporateController` creates an award program with a `name`, a `program_type` of `CONFERENCE` or `STOCK_GRANT`, and an inclusive performance window from `performance_period_start_date` to `performance_period_end_date` bounding the source periods eligible for the program. The `eligibility_threshold_score` is the minimum passing score, inclusive, and defaults to 80 when omitted. For a `STOCK_GRANT` program, `stock_units_pool` is required and must be greater than zero; for a `CONFERENCE` program it is ignored. A program begins `OPEN` with `units_reserved` at 0, and a `CorporateController` may close it, moving it to `CLOSED` to stop new grants.

Granting an award pairs a `partner_id` with a `source_period_id` under the program identified by the path, recorded on the grant as its `program_id`. The source period must be `FINALIZED` or `LOCKED`, and its own period interval must lie entirely within the program's inclusive performance window — a period failing either condition is rejected with `ERR_AWARD_SOURCE_PERIOD_INELIGIBLE`. Grant creation runs the eligibility scoring, a weighted composite of three components measured against the source period. The sales component contributes up to 50 points: 50 times the ratio of the period's revenue to the 20,000,000-cent sales target, capped at the full 50 when revenue meets or exceeds the target — where the period's revenue is the sum of `actual_amount_cents` over its `FINALIZED` `REVENUE` line items. The profit margin component contributes up to 30 points: 30 times the ratio of the period's profit margin to the 10% margin target, again capped at full marks; the margin itself is the final distributable profit, floored at zero, divided by the period's revenue, with a revenue of zero treated as 1 to avoid division failure, and a negative profit floors the margin contribution at zero. The waste component contributes up to 20 points: 20 times one minus the ratio of the period's total waste charges to the 500,000-cent waste allowance, with the ratio capped at 1 — so waste at or beyond the allowance contributes nothing; the total waste charges are the sum of `waste_charge_cents` over the period's batches in `AUDITED_CONFORMING` or `VARIANCE_CONFIRMED` status. The `eligibility_score` is the sum of the three components, rounded half-up to two decimal places.

Eligibility is inclusive: a score equal to the program's `eligibility_threshold_score` passes; below it, the grant is rejected with `ERR_AWARD_NOT_ELIGIBLE`. What a passing partner receives depends on the program type. A `CONFERENCE` grant awards zero units — `units_awarded` is 0 — the award is the invitation itself. A `STOCK_GRANT` awards by tier: a score of at least 90 earns 200 units; a score of at least 80 earns 100 units. Stock draws against the pool: if the program's `units_reserved` plus the tier's units would exceed the `stock_units_pool`, the grant is rejected with `ERR_AWARD_POOL_EXHAUSTED`; otherwise the units are added to `units_reserved`. A new grant begins in `EARNED`.

A `CorporateController` moves a grant from `EARNED` to `VESTING`. From there the clock does the rest: once the logical clock's date reaches the grant's `created_at` date plus 365 days, the sweep moves the grant to `VESTED`. Grants die with their partner's standing: when a partner moves to `WITHDRAWN` — by recruiter withdrawal, by a settled buyout, or by a lapsed funding window — every grant that partner holds in `EARNED` or `VESTING` moves to `FORFEITED`, and each forfeiture credits the grant's `units_awarded` back to its program's `units_reserved`. `VESTED` grants survive withdrawal untouched.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new stand-alone resource — including child resources added to a collection, such as a line item on a period, a buy-in payment on a contract, or a grant under a program — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and fire all scheduled sweeps | PlatformAdmin |
| POST | `/api/partners` | Register a partner candidate | HRRecruiter |
| GET | `/api/partners` | List partners | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/partners/{id}` | Get a partner | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/partners/{id}/start-training` | Begin training tenure | HRRecruiter |
| POST | `/api/partners/{id}/certify` | Certify a partner after sufficient training tenure | HRRecruiter |
| POST | `/api/partners/{id}/withdraw` | Withdraw a candidate, trainee, or certified partner | HRRecruiter |
| POST | `/api/market-groups` | Create a market group | PlatformAdmin |
| GET | `/api/market-groups` | List market groups | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/market-groups/{id}` | Get a market group | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/market-groups/{id}/activate` | Activate a market group | PlatformAdmin |
| POST | `/api/restaurants` | Create a restaurant | PlatformAdmin |
| GET | `/api/restaurants` | List restaurants | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/restaurants/{id}` | Get a restaurant | PlatformAdmin, HRRecruiter, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/restaurants/{id}/activate` | Open the restaurant | PlatformAdmin |
| POST | `/api/restaurants/{id}/close` | Close the restaurant | PlatformAdmin |
| POST | `/api/managing-partner-contracts` | Create a managing partner contract in draft | CorporateController |
| GET | `/api/managing-partner-contracts` | List contracts | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner |
| GET | `/api/managing-partner-contracts/{id}` | Get a contract | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner |
| POST | `/api/managing-partner-contracts/{id}/submit` | Submit a draft contract for funding | CorporateController |
| POST | `/api/managing-partner-contracts/{id}/buy-in-payments` | Fund the buy-in escrow | ManagingPartner |
| GET | `/api/managing-partner-contracts/{id}/buy-in-payments` | List buy-in payments for a contract | PlatformAdmin, CorporateController, ManagingPartner |
| POST | `/api/managing-partner-contracts/{id}/activate` | Activate a fully funded contract | CorporateController |
| POST | `/api/managing-partner-contracts/{id}/offer-renewal` | Offer a renewal term | CorporateController |
| POST | `/api/managing-partner-contracts/{id}/accept-renewal` | Partner accepts a renewal; term extends | ManagingPartner |
| POST | `/api/managing-partner-contracts/{id}/depart` | Managing partner initiates departure | ManagingPartner |
| POST | `/api/managing-partner-contracts/{id}/transfer` | Transfer the contract to a certified successor | CorporateController |
| POST | `/api/managing-partner-contracts/{id}/buyout-orders` | Price and create a buyout order | CorporateController |
| GET | `/api/buyout-orders` | List buyout orders | PlatformAdmin, CorporateController |
| GET | `/api/buyout-orders/{id}` | Get a buyout order | PlatformAdmin, CorporateController, ManagingPartner |
| POST | `/api/buyout-orders/{id}/approve` | Approve a priced buyout | CorporateController |
| POST | `/api/buyout-orders/{id}/pay` | Pay an approved buyout; settles the contract | CorporateController |
| POST | `/api/market-partner-agreements` | Create a market partner agreement in draft | CorporateController |
| GET | `/api/market-partner-agreements` | List market partner agreements | PlatformAdmin, CorporateController, OperationsAuditor, MarketPartner |
| GET | `/api/market-partner-agreements/{id}` | Get a market partner agreement | PlatformAdmin, CorporateController, OperationsAuditor, MarketPartner |
| POST | `/api/market-partner-agreements/{id}/activate` | Activate an agreement | CorporateController |
| POST | `/api/market-partner-agreements/{id}/terminate` | Terminate an agreement | CorporateController |
| POST | `/api/profit-periods` | Open a profit accounting period for a restaurant | OperationsAuditor |
| GET | `/api/profit-periods` | List profit periods | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/profit-periods/{id}` | Get a profit period | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/profit-periods/{id}/line-items` | Post a statement line item to an open period | OperationsAuditor |
| GET | `/api/profit-periods/{id}/line-items` | List line items of a period | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner |
| POST | `/api/line-items/{id}/finalize` | Finalize a provisional line item with its actual amount | OperationsAuditor |
| POST | `/api/profit-periods/{id}/compute` | Compute provisional restaurant profit | OperationsAuditor |
| POST | `/api/profit-periods/{id}/finalize` | Finalize a computed period: profit, share, override, retained | CorporateController |
| POST | `/api/profit-periods/{id}/lock` | Lock a finalized period | CorporateController |
| POST | `/api/yield-standards` | Create a yield standard | CorporateController |
| GET | `/api/yield-standards` | List yield standards | PlatformAdmin, CorporateController, OperationsAuditor |
| GET | `/api/yield-standards/{id}` | Get a yield standard | PlatformAdmin, CorporateController, OperationsAuditor |
| POST | `/api/yield-standards/{id}/deactivate` | Deactivate a yield standard | CorporateController |
| POST | `/api/meat-cut-batches` | Record an in-house meat cutting batch | OperationsAuditor |
| GET | `/api/meat-cut-batches` | List meat cut batches | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner |
| GET | `/api/meat-cut-batches/{id}` | Get a meat cut batch | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner |
| POST | `/api/meat-cut-batches/{id}/audit` | Audit a batch: record actual yield, compute waste charge | OperationsAuditor |
| POST | `/api/meat-cut-batches/{id}/waive` | Waive a confirmed variance charge | CorporateController |
| POST | `/api/award-programs` | Create a conference or stock award program | CorporateController |
| GET | `/api/award-programs` | List award programs | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/award-programs/{id}` | Get an award program | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/award-programs/{id}/close` | Close a program to new grants | CorporateController |
| POST | `/api/award-programs/{id}/grants` | Grant an award from a source profit period | CorporateController |
| GET | `/api/award-grants` | List award grants | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| GET | `/api/award-grants/{id}` | Get an award grant | PlatformAdmin, CorporateController, OperationsAuditor, ManagingPartner, MarketPartner |
| POST | `/api/award-grants/{id}/vest` | Move a grant into vesting | CorporateController |
| POST | `/api/dispute-cases` | File a profit dispute on a finalized period | ManagingPartner |
| GET | `/api/dispute-cases` | List dispute cases | PlatformAdmin, CorporateController, ManagingPartner |
| GET | `/api/dispute-cases/{id}` | Get a dispute case | PlatformAdmin, CorporateController, ManagingPartner |
| POST | `/api/dispute-cases/{id}/request-evidence` | Request evidence from the filing partner | CorporateController |
| POST | `/api/dispute-cases/{id}/submit-evidence` | Filing partner submits evidence | ManagingPartner |
| POST | `/api/dispute-cases/{id}/resolve` | Resolve a dispute as upheld or adjusted | CorporateController |
| POST | `/api/dispute-cases/{id}/withdraw` | Filing partner withdraws an open dispute | ManagingPartner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_RESTAURANT_NOT_FOUND` | 404 Not Found |
| `ERR_MARKET_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_YIELD_STANDARD_NOT_FOUND` | 404 Not Found |
| `ERR_BUYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_NOT_FUNDABLE` | 409 Conflict |
| `ERR_BUY_IN_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_BUY_IN_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_FUNDING_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_RESTAURANT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RESTAURANT_ALREADY_HAS_ACTIVE_CONTRACT` | 422 Unprocessable Entity |
| `ERR_RESTAURANT_HAS_OPEN_CONTRACTS` | 422 Unprocessable Entity |
| `ERR_NOT_MANAGING_PARTNER` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT` | 422 Unprocessable Entity |
| `ERR_RENEWAL_BLOCKED_BY_OPEN_DISPUTE` | 422 Unprocessable Entity |
| `ERR_DEPARTURE_BLOCKED_BY_OPEN_DISPUTE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_PARTNER_MISMATCH` | 403 Forbidden |
| `ERR_SUCCESSOR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_BUYOUT_ALREADY_OPEN` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_IN_BUYOUT` | 409 Conflict |
| `ERR_OFFSET_EXCEEDS_PAYOUT` | 422 Unprocessable Entity |
| `ERR_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_PERIOD_CLOSED_FOR_ENTRIES` | 422 Unprocessable Entity |
| `ERR_UNFINALIZED_LINE_ITEMS` | 422 Unprocessable Entity |
| `ERR_BATCH_PERIOD_RESTAURANT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CUT_CODE` | 422 Unprocessable Entity |
| `ERR_UNKNOWN_CUT_CODE` | 422 Unprocessable Entity |
| `ERR_TRAINING_TENURE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_MARKET_GROUP_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_OVERRIDE_COVERAGE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_AWARD_SOURCE_PERIOD_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_AWARD_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_AWARD_POOL_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_OPEN_DISPUTE` | 422 Unprocessable Entity |
| `ERR_DISPUTE_NOT_OWNED` | 403 Forbidden |
| `ERR_ADJUSTMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_OPEN_DISPUTE_BLOCKS_LOCK` | 422 Unprocessable Entity |
