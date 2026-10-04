# Agent Desk Fee Model & Commission Retention Administration API — Product Requirements Document

## 1. Introduction

Franchise real-estate networks that operate on the desk-fee model invert the usual brokerage economics: rather than the office taking a percentage of every deal, each agent pays a predictable monthly management fee plus an overhead share, and in exchange keeps the vast majority of every commission they earn. Office profitability then depends on agent count rather than transaction share, which makes agent recruitment, retention, and orderly departure every bit as important as deal flow. This document describes the API that administers that model end-to-end — onboarding agents under a fee schedule, billing them monthly for desk and technology costs, holding commissions in escrow, splitting them at closing, advancing cash ahead of closing, supervising agents through a disbursement-authorization ladder, settling their affairs when they leave, and compensating other offices across the referral network when an out-of-market client lands.

The system is built around a small set of interacting state machines. Franchise offices open, suspend, and close; agents move from pending onboarding through active service and out via a fourteen-day notice window; offers negotiate through a bounded counter cycle before producing transactions that walk a strict closing path guarded by a three-rung compliance ladder; monthly invoices march from issuance through overdue, collections, and either payment or write-off; and a ledger of commission entries carries every escrow movement through to reconciliation. A logical clock — not wall-clock time — governs every temporal gate, from the seventy-two-hour offer TTL to the ninety-day write-off floor, so that tests, audits, and demos can step time forward deterministically. Supervision obligations (the disbursement ladder, the rung-by-rung role assignments, and the post-departure audit of open balances) persist regardless of how the agent's compensation is structured, because regulators hold the broker responsible for every disbursement that leaves trust.

This document is the sole specification the implementation team needs: it covers the role model, the wire envelope, every state transition and its preconditions and side effects, every calculation (closing statements, departure proration, monthly invoice totals, advance-recovery waterfalls, trust-balance arithmetic, retention reporting, referral fees, and offer expiry), every error code, and the complete endpoint surface.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting operator and `X-User-Role` names their operational role. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorization list; an authenticated caller whose role is not permitted for the operation is rejected with `ERR_FORBIDDEN` (HTTP 403). The seven declared roles are `FranchiseeOwner`, `BrokerOfRecord`, `ManagingBroker`, `Agent`, `TrustAccountant`, `ComplianceAuditor`, and `PlatformAdmin`.

Only one role is entity-backed. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` record, and ownership checks on any resource that references an `Agent` compare the resource's foreign-key field (for example `agent_id` on an `Invoice` or `FeeAssignment`) to `X-User-ID`. An agent attempting to pay another agent's invoice, accept another agent's fee assignment, terminate another agent, or return an advance on another agent's balance is rejected with `ERR_FORBIDDEN`.

For `FranchiseeOwner`, `BrokerOfRecord`, `ManagingBroker`, `TrustAccountant`, `ComplianceAuditor`, and `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a transition names an actor (for example as `authorizing_broker_id` on a `CommissionDisbursementAuthorization`) but does not compare it to any entity's `id`. Role-name spellings are exact — the strings above are the only values the role header may carry.

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

List endpoints paginate via the `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending. List responses carry four pagination fields in `meta`: `limit`, `offset`, `total_count`, and `has_more`. The filter parameters available on each list endpoint are enumerated in §4 and named in the workflow narratives of §3.

### 2.4. The Logical Clock

All time-dependent behavior — offer expiry, invoice overdue and collections escalations, fee-schedule window activation, the fourteen-day termination notice, the ninety-day write-off floor, retention-report month boundaries, and ledger-month attribution — is driven by a single logical clock, never by wall-clock time. The logical clock starts at exactly `2026-09-01T00:00:00Z` at server startup; before any explicit advance, every time-dependent rule reads this default. A `PlatformAdmin` advances the clock by submitting a `current_utc` timestamp to the clock endpoint, after which the server re-evaluates every time-gated state: offers sitting in `OFFERED` past their TTL are moved to `EXPIRED`, unpaid invoices are escalated from `ISSUED` or `PARTIALLY_PAID` to `OVERDUE` and from `OVERDUE` to `COLLECTIONS`, and fee schedules whose effective window now contains the clock are flipped to `ACTIVE`. The same re-evaluation runs lazily on reads — fetching an offer or an invoice may cause its status to advance before the response is rendered.

### 2.5. Common Resource Properties

Every top-level resource in this API — `Office`, `FeeSchedule`, `Agent`, `FeeAssignment`, `Offer`, `Transaction`, `CommissionDisbursementAuthorization`, `ClosingStatementLine`, `Invoice`, `InvoiceLine`, `CommissionEntry`, `ReferralAgreement`, and `AgentRetentionReport` — carries a uniform set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 and increments by 1 on every mutation, including mutations cascaded from a parent or a related entity.

Cascades are first-class mutations. When a transition's side effects touch another entity — for example, closing a transaction that flips a referral agreement to `FULFILLED`, or terminating an agent that tightens their supervision cadence — each affected entity's `updated_at` is refreshed and its `version` incremented exactly once per originating request.

### 2.6. Money, Basis Points, and Rounding

Every monetary value in the system is an integer number of cents. There are no floats, no decimal dollars, and no sub-cent fractions anywhere in request bodies, response payloads, or ledger rows. Percentages are expressed as basis points, where 100 basis points equal one percent and the basis-point denominator is 10000. When a rate is applied to a money amount, the resulting line is rounded half-up to whole cents, and the rounding happens at the line where the rate is applied — never earlier, never later, and never deferred to a sum. Where multiple lines make up one total (monthly invoices, departure invoices, closing statements), each line is rounded independently first and only then summed; the alternative order (sum unrounded fractions, round the total) is forbidden because it produces different cents.

### 2.7. Optimistic Concurrency Control on Fee Assignment Creation

Proposing a fee assignment mutates the parent agent in two ways: any prior `PROPOSED` assignment for that agent is flipped to `SUPERSEDED`, and the agent's `version` advances. Because the client may have based its decision on an older view of the agent's fee posture, the proposal endpoint requires a non-optional `expected_agent_version` field in the request body, carrying the `version` of the `Agent` the client last observed. If that number does not match the agent's current `version`, the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412). This OCC rule applies only to fee-assignment creation; no other endpoint in the API takes an expected-version field.

### 2.8. Trust Accounting, Escrow, and the Commission Ledger

The office's trust is the financial spine of the system, and its balance is a derived figure, never a stored counter. An office's `trust_balance_cents` is the sum of two components: the `amount_cents` of every `CommissionEntry` belonging to the office whose status is `ESCROW_HELD`, `OFFICE_FEE_ACCRUED`, or `DEPARTURE_HOLD`, plus the unpaid remainder — `amount_due_cents` minus `amount_paid_cents` — of every `Invoice` belonging to the office whose status is `ISSUED`, `PARTIALLY_PAID`, or `COLLECTIONS`. Invoices that are `OVERDUE` remain in the trust base because the obligation is still owed; invoices that reach `PAID` or `WRITTEN_OFF` drop out. Every commission entry records an `entry_month`, the calendar month in `YYYY-MM` form derived from the logical clock at posting time, which drives monthly aggregation for retention analysis.

The ledger is append-only in spirit: cash moves through the trust by posting new entries and advancing their statuses rather than by editing history. When a transaction closes, gross commission income arrives as a `GCI_RECEIPT` entry held in escrow, then splits into per-agent `AGENT_DISBURSEMENT` entries, an `OFFICE_FEE_ACCRUAL` entry, and — when a referral agreement covers the deal — a `REFERRAL_PAYOUT` entry. Reconciliation by a `TrustAccountant` settles the payable and accrued entries, decrementing the trust by the amounts that leave escrow. Departures introduce two further kinds, `DEPARTURE_HOLD` and `DEPARTURE_RELEASE`, which quarantine the departing agent's open balances until the departure invoice is settled. A managing broker may also advance cash to an agent ahead of closing (`ADVANCE`), and the agent may return it (`ADVANCE_RETURN`); both move the agent's `unearned_advance_balance_cents`.

### 2.9. Supervision Persists Regardless of Compensation Model

The desk-fee model shifts transaction economics toward the agent, but it does not shift regulatory accountability. The supervising broker remains responsible for every disbursement, which is why no transaction can move from `UNDER_CONTRACT` to `PENDING_CLOSE` without a fully approved `CommissionDisbursementAuthorization`, and why the CDA's review ladder always walks compliance, trust, and broker sign-off in that fixed order. Supervision continues during departure as well: when an agent initiates termination, their `supervision_cadence_days` tightens from 30 to 7, reflecting the intensified review owed to an agent whose account is being wound down, and the office's ledger quarantines their open receivables. These duties attach to the office and the broker roles, not to any particular fee schedule, so a change of plan never alters them.

### 2.10. Nested Resource Retrieval and Path Validation

Endpoints whose paths nest resource identifiers — for example an agent under an office, or a closing-statement line under a transaction — validate path segments left to right. The server first confirms the leftmost identifier exists, then the next, and so on; the first segment that fails produces a `ERR_NOT_FOUND` (HTTP 404) response and no further segment is examined. Body-supplied foreign keys are validated after the path, in the endpoint's declared input order, and a body reference that does not resolve to a live entity compatible with the operation is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Opening, Suspending, and Closing an Office

A `FranchiseeOwner` opens a franchise office by supplying its `office_name` (the legal name), a `market_code` such as `DEN` or `PHX` (the market identifier that groups offices for the referral network), and a `recruiting_target_agents` headcount goal that must be at least 1 — recruitment economics in the desk-fee model scale with agent count, not with transaction share. The new office is born with `status` set to `ACTIVE`, `active_agent_count` equal to 0, and `trust_balance_cents` equal to 0; `closed_at` is null. Reading an office returns these fields plus the standard resource properties, and the list of offices can be filtered by `market_code`, `status`, or `office_id`.

Suspension is automatic. The moment any invoice belonging to the office escalates into `COLLECTIONS`, the office's `status` flips to `SUSPENDED`. While an office is suspended (or closed), new agent onboarding into it is rejected with `ERR_OFFICE_SUSPENDED` (HTTP 409); existing agents, transactions, and ledgers continue to operate. Reinstatement is equally automatic: when a payment or a write-off leaves the office with zero invoices in `COLLECTIONS`, the office returns to `ACTIVE`.

A `FranchiseeOwner` closes an office by invoking the close operation. The close is permitted only when the office has zero agents in `ACTIVE` status; attempting it with active agents fails with `ERR_OFFICE_NOT_EMPTY`. On close, `closed_at` is set to the logical clock, every agent still in `TERMINATION_PENDING` is advanced to `TERMINATED` with `terminated_at` set (a conditional cascade), every invoice in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` is escalated to `COLLECTIONS` (a cascade down), and the office's `version` is incremented. The office's `active_agent_count` is recomputed on every agent activation, every agent termination, and on the office close itself.

### 3.2. Fee Schedules and Effective Windows

The fee schedule is the contract economics of the desk-fee plan. A `BrokerOfRecord` authors one with a human-readable `schedule_name` (for example, "95/5 Desk Plan"), a monthly `desk_fee_cents` management fee that must be at least 0, an `overhead_share_bps` office-overhead rate applied against net GCI at statement time (between 0 and 10000 inclusive), a `retention_bps` agent-retention rate (between 0 and 10000 inclusive, with the office keeping the complement out of 10000), a cross-office `referral_fee_bps` (between 0 and 5000 inclusive), and the two monthly fixed costs disclosed to the agent upfront at onboarding: `tech_subscription_monthly_cents` and `marketing_monthly_cents`, both at least 0. Every schedule carries an effective window `[effective_from, effective_to)`, half-open: `effective_from` is inclusive and `effective_to` is exclusive. An open-ended schedule uses the sentinel `effective_to` of `9999-12-31T00:00:00Z`.

Schedule windows must tile the calendar without overlap. A new schedule's window may not intersect any sibling schedule's window, and when a predecessor exists, the new window must start exactly at the predecessor's `effective_to` — adjacent with zero gap. A violation of either rule is rejected with `ERR_SCHEDULE_WINDOW_VIOLATION` (HTTP 409). A schedule's `status` is derived from its window against the logical clock: `DRAFT` before its window opens, `ACTIVE` while the clock sits inside the window, and `ARCHIVED` once superseded or once its window has passed. The list of fee schedules may be filtered by `status` or `fee_schedule_id`. Schedules are listed and fetched by every role.

### 3.3. Onboarding an Agent and Binding a Fee Schedule

A `ManagingBroker` onboards an agent into an office by supplying the agent's `full_name`, contact `email`, and state-issued `license_number`. License numbers are unique across the entire system; attempting to register a duplicate fails with `ERR_DUPLICATE_LICENSE` (HTTP 409). The new agent is born in `PENDING_ONBOARDING`, with `supervision_cadence_days` at its default of 30 and `unearned_advance_balance_cents` at 0; `onboarded_at`, `termination_requested_at`, and `terminated_at` are all null. Onboarding is permitted only while the office is `ACTIVE` — a suspended or closed office rejects the request with `ERR_OFFICE_SUSPENDED`.

The agent activates only when their first fee assignment is accepted. A `ManagingBroker` proposes the assignment by naming the `fee_schedule_id`, the assignment window `[effective_from, effective_to)` with `effective_to` strictly greater than `effective_from`, and — because this is the OCC-guarded write — `expected_agent_version` carrying the `version` of the agent the broker last observed (see §2.7). The proposal lands in `PROPOSED`. If another `PROPOSED` assignment already exists for the same agent, that earlier one is automatically moved to `SUPERSEDED`. Two window rules are checked at proposal time: the assignment's window must not intersect any other non-terminal assignment window for the same agent — touching endpoints where one window's `effective_to` equals the other's `effective_from` are adjacent, not overlapping — and any intersection is rejected with `ERR_ASSIGNMENT_OVERLAP`; and the schedule referenced by `fee_schedule_id` must be a live schedule whose own window covers the assignment, otherwise the request is rejected with `ERR_REFERENTIAL_INTEGRITY`.

The agent then decides. Acceptance is performed by the agent themselves — the caller's `X-User-ID` must equal the assignment's `agent_id` — and is gated on the schedule's window covering both the assignment's `effective_from` and the current logical clock; a violation is rejected with `ERR_SCHEDULE_WINDOW_VIOLATION`. On acceptance the assignment moves from `PROPOSED` to `ACCEPTED`. If this is the agent's first accepted assignment, the agent's `status` advances from `PENDING_ONBOARDING` to `ACTIVE`, `onboarded_at` is set to the logical clock, and the office's `active_agent_count` is incremented. Rejection moves the assignment to `REJECTED`; a `ManagingBroker` may also cancel a still-`PROPOSED` assignment, moving it to `CANCELLED`. The parent agent's `version` advances on acceptance (because the agent's status may change) and on creation of a sibling proposal that supersedes this one, but not on rejection or cancellation of the assignment record alone. The agent's assignments can be listed per agent or across agents, with `status`, `agent_id`, and `fee_schedule_id` filters.

### 3.4. Monthly Billing, Invoices, Payments, and Write-Offs

Each month the office bills every active agent for the fixed costs of their plan. A `ManagingBroker` triggers the billing run by submitting a `billing_month` in `YYYY-MM` form. For each agent in `ACTIVE` status whose `ACCEPTED` fee-assignment window covers the billing month, the system generates exactly one `Invoice` of `origin` `AUTO_RUN`, born directly in `ISSUED` status. The run is idempotent per (agent, billing month): re-running it for the same month returns the already-existing invoices without duplicating them. The invoice's `amount_due_cents` is the sum of its `InvoiceLine` amounts, and its `due_date` is the first day of the billing month plus seven days. The invoice carries three monthly lines, each rounded half-up to whole cents before the sum (line-rounding order is pinned): a `DESK_FEE` line at the schedule's `desk_fee_cents`, a `TECH_SUBSCRIPTION` line at `tech_subscription_monthly_cents`, and a `MARKETING` line at `marketing_monthly_cents`. Each line carries a `period_label` such as "2026-09 desk fee" naming the billed period. Overhead share is deliberately not a monthly line — it is deducted at closing through the closing-statement calculation, so only fixed monthly costs appear here.

A `ManagingBroker` may also create a manual invoice by supplying `office_id`, `agent_id`, `billing_month`, and an explicit `lines` array. Manual invoices land in `DRAFT` and must be issued by a subsequent issue action, which moves them to `ISSUED`. A manual invoice's `due_date` is seven days after its `created_at`. A `DRAFT` invoice may be cancelled by a `ManagingBroker`, moving it to `CANCELLED`.

Payment is the agent's own act — the caller's `X-User-ID` must equal the invoice's `agent_id`. A payment carries `amount_cents`, which must be strictly greater than zero and no greater than the remaining balance (`amount_due_cents` minus `amount_paid_cents`); anything larger is rejected with `ERR_OVERPAYMENT` (HTTP 422). A partial payment moves the invoice from `ISSUED` to `PARTIALLY_PAID` and increments `amount_paid_cents` accordingly; a payment equal to the remaining balance moves the invoice to `PAID`. An invoice already in `PARTIALLY_PAID` accepts further payments on the same terms. The office's `trust_balance_cents` does not change when the agent pays — the payment sits in the office's escrow trust until a `TrustAccountant` reconciles.

Time is the invoice's other adversary. When the logical clock passes `due_date` with any balance remaining, an `ISSUED` or `PARTIALLY_PAID` invoice advances to `OVERDUE`. When the clock passes `due_date` plus thirty days, an `OVERDUE` invoice advances to `COLLECTIONS`, and at that moment the office's `status` flips to `SUSPENDED` (the cascade up). Payments continue to be accepted in `OVERDUE` and `COLLECTIONS`: a partial payment moves `OVERDUE` to `PARTIALLY_PAID`; a full payment moves `OVERDUE` to `PAID` and — if this was the office's last invoice in `COLLECTIONS` — restores the office from `SUSPENDED` to `ACTIVE`; a full payment on a `COLLECTIONS` invoice moves it directly to `PAID` with the same suspension-lift side effect.

Bad debt is recognized by write-off. A `BrokerOfRecord` may write off a `COLLECTIONS` invoice, but only once the invoice is at least ninety days past its `due_date`; attempting it earlier is rejected with `ERR_WRITE_OFF_TOO_EARLY` (HTTP 409). Write-off moves the invoice to `WRITTEN_OFF`, reduces the office's `trust_balance_cents` by the unpaid balance (bad-debt recognition), and — if this was the office's last `COLLECTIONS` invoice — lifts the suspension back to `ACTIVE`. Individual invoice lines are reachable by id, and the lines of a given invoice are listed via the invoice's lines collection; the cross-invoice line list supports `invoice_id` and `line_kind` filters. Line kinds are `DESK_FEE`, `OVERHEAD_SHARE`, `TECH_SUBSCRIPTION`, `MARKETING`, `PRORATED_DESK_FEE`, and `ADVANCE_RECOVERY`. Every line also tracks `applied_at_closing_cents`, the portion of the line already satisfied by closing-statement offsets (see §3.9).

### 3.5. Offers, Negotiation Rounds, and the Deal They Seed

A buyer's offer is registered against a listing office by an `Agent` or a `ManagingBroker`, supplying the external `listing_reference`, the `buyer_name`, and an `offer_price_cents` that must be strictly greater than zero. The offer is born in `OFFERED` with `offer_round` set to 1.

Negotiation is a bounded cycle. The listing office's agent counters the offer, moving it from `OFFERED` to `COUNTERED`. The buyer, through their agent, re-offers — moving the offer from `COUNTERED` back to `OFFERED` and incrementing `offer_round`. The cycle is capped: a re-offer attempted when `offer_round` is already 4 (so that the next round would begin round 5) is rejected with `ERR_NEGOTIATION_EXHAUSTED` (HTTP 409). An offer can be rejected from either `OFFERED` or `COUNTERED` (moving to `REJECTED`), and withdrawn from `COUNTERED` (moving to `WITHDRAWN`). An offer left in `OFFERED` expires automatically when the logical clock reaches seventy-two hours after its last status change — a boundary-inclusive TTL: an offer whose last status change was exactly seventy-two hours ago is expired, while one second under is still alive. The expiry check runs on any read of the offer and on any attempt to accept it; an accept attempted after the TTL has elapsed is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). Every status change refreshes `updated_at` and increments `version`, so the seventy-two-hour window is always measured from the most recent transition.

Acceptance is the offer's terminal fork. When an offer in `OFFERED` is accepted by the agent, two things happen in the same request: the offer moves to `ACCEPTED`, and a `Transaction` is created against the same office, born directly in `UNDER_CONTRACT` status with `sale_price_cents` snapshotted from the accepted offer's price and `gross_commission_cents` taken from the acceptance-time input. The transaction's `offer_id` references the accepted offer.

A transaction may also be created directly — without going through offer acceptance — by a `ManagingBroker` who supplies `listing_agent_id`, `selling_agent_id` (which may equal the listing agent when the same agent represents both sides), an `offer_id` referencing an existing offer, a `sale_price_cents` strictly greater than zero, and a `gross_commission_cents` strictly greater than zero. A directly-created transaction lands in `LISTED` and must be advanced separately. The referenced offer and both agents must resolve to live entities; a dangling reference is rejected with `ERR_REFERENTIAL_INTEGRITY`.

The transaction's lifecycle has a re-list loop. From `UNDER_CONTRACT`, the agent may mark the deal as fallen through (`FELL_THROUGH`); from `FELL_THROUGH`, the agent may re-list it (`RELISTED`); from `RELISTED`, the agent may put it back under contract (`UNDER_CONTRACT`). The same fall-through is available from `PENDING_CLOSE`. A fall-through does not disturb the offer that seeded the transaction — that offer is already `ACCEPTED` — but it does supersede any `IN_REVIEW` CDA attached to the deal (see §3.6). Transactions are listed with `office_id`, `status`, `selling_agent_id`, `listing_agent_id`, and `offer_id` filters.

### 3.6. The Commission Disbursement Authorization Ladder

Before money can move at closing, a three-rung review must approve the disbursement. A `ManagingBroker` opens a `CommissionDisbursementAuthorization` (CDA) on a transaction by supplying the `review_ladder`, an ordered list of reviewer role names that must be exactly `COMPLIANCE_REVIEW`, then `TRUST_REVIEW`, then `BROKER_SIGNOFF`. Creation is permitted only while the transaction is `UNDER_CONTRACT` or `PENDING_CLOSE`; attempting it on a transaction in any other state is rejected with `ERR_INVALID_STATE`. Only one live CDA may exist per transaction: if a CDA in `DRAFT`, `IN_REVIEW`, or `APPROVED` already exists for the transaction, the create is rejected with `ERR_CDA_EXISTS` (HTTP 409). A successfully created CDA is born directly in `IN_REVIEW` with `current_rung` set to 0 (the `COMPLIANCE_REVIEW` rung), and the CDA records the `authorizing_broker_id` of the opening broker.

Reviews proceed one rung at a time, and each rung is owned by exactly one role: rung 0 belongs to `ComplianceAuditor`, rung 1 to `TrustAccountant`, and rung 2 to `ManagingBroker`. A review submitted by a role that does not own the current rung is rejected with `ERR_REVIEW_RUNG_MISMATCH` (HTTP 409). The reviewer submits a `verdict`. An `APPROVE` at rung 0 or rung 1 advances `current_rung` by 1 while the CDA remains in `IN_REVIEW`. An `APPROVE` at rung 2 completes the ladder: the CDA's `status` becomes `APPROVED`, and from that moment the parent transaction may advance to `PENDING_CLOSE`. A `REJECT` at any rung resets `current_rung` to 0 — the ladder cycles back to compliance review rather than terminating, and the CDA stays in `IN_REVIEW`. If the parent transaction is marked fallen through while the CDA is `IN_REVIEW`, the CDA is automatically moved to `SUPERSEDED`.

The CDA is the gate on closing. A request to advance a transaction from `UNDER_CONTRACT` to `PENDING_CLOSE` is rejected with `ERR_CDA_NOT_APPROVED` (HTTP 409) when no `APPROVED` CDA exists for the deal. The same transition also requires the listing agent to be in `ACTIVE` status; if the listing agent has entered `TERMINATION_PENDING` (or any other non-active state), the request is rejected with `ERR_AGENT_NOT_ACTIVE` (HTTP 409) — a cross-entity dependency from the transaction to the listing agent.

### 3.7. Closing Statements and the Split of Gross Commission

When the CDA has approved the disbursement and the listing agent is active, the agent on the deal requests the close, advancing the transaction from `UNDER_CONTRACT` to `PENDING_CLOSE`. A `ManagingBroker` then executes the close itself, advancing the transaction from `PENDING_CLOSE` to `CLOSED`. The close is permitted on or after the transaction's request-close timestamp — a same-day close is allowed. On close, `closed_at` is set to the logical clock, the closing-statement calculation runs, and a cascade of ledger entries is posted (§3.8).

The closing-statement calculation is pinned in evaluation order because the overhead share keys off net GCI rather than gross: the overhead line can only be computed once the referral tier has been removed. The steps are:

1. **Referral tier.** Identify the fee schedule in force — the `ACCEPTED` fee assignment covering the transaction's `selling_agent_id` whose window contains `closed_at`, together with its `FeeSchedule`. If an `ACTIVE` `ReferralAgreement` covers the deal (its `agent_id` equals the transaction's `selling_agent_id` and its `receiving_office_id` equals the transaction's `office_id`), the agreement's `referral_fee_bps` wins; otherwise the schedule's own `referral_fee_bps` applies. The referral fee is the gross commission multiplied by the applicable referral basis points and divided by 10000, rounded half-up to whole cents. The fee is zero exactly when the applicable `referral_fee_bps` is zero. Because referral agreements cannot activate with a fee above 5000 basis points, the referral tier is bounded by that ceiling by construction.
2. **Net GCI.** Subtract the referral fee from `gross_commission_cents` to obtain `net_gci_cents`.
3. **Agent retention.** Multiply the net GCI by the schedule's `retention_bps`, divide by 10000, and round half-up to whole cents to obtain `agent_retention_cents`.
4. **Overhead share.** Multiply the net GCI by the schedule's `overhead_share_bps`, divide by 10000, and round half-up to whole cents to obtain `overhead_share_cents`.
5. **Office split.** The office's remainder is the net GCI minus the agent retention minus the overhead share.
6. **Advance recovery offset.** The amount of the retention diverted to recover outstanding advances is the smaller of `agent_retention_cents` and the agent's `unearned_advance_balance_cents`; the agent's take-home disbursement is the retention minus that offset (§3.9).

The calculation emits `ClosingStatementLine` rows on the transaction: a `GCI` line for the gross, a `REFERRAL_FEE` line for the referral tier, an `AGENT_RETENTION` line, an `OFFICE_SPLIT` line, an `OVERHEAD_SHARE` line, and an `ADVANCE_RECOVERY` line for the offset. Each line is signed so that the sum over all lines of a closed statement equals zero, under this fixed sign convention: the `GCI` line is negative (its `amount_cents` is the negated gross commission), while every other line — `REFERRAL_FEE`, `AGENT_RETENTION`, `OVERHEAD_SHARE`, `OFFICE_SPLIT`, and `ADVANCE_RECOVERY` — is positive, carrying the magnitude computed by the steps above. Lines on the office side — `REFERRAL_FEE` and `OFFICE_SPLIT` — carry a null `agent_id`; agent-side lines name the agent. Each line records the `variant` of the calculation that produced it and an `applied_invoice_line_id` when the line satisfies, partially or wholly, an outstanding invoice line.

Two variants of the closing statement exist, and the choice between them is automatic. The `STANDARD` variant applies when the selling agent is `ACTIVE` at close: the full formula above runs and the disbursement entries are posted as agent-payable. The `FORMER_AGENT` variant applies when the selling agent is in `TERMINATION_PENDING` or `TERMINATED` at close: the retention figure is computed identically, but it is routed into departure-hold ledger entries rather than agent-payable ones, and the overhead share is waived entirely — departing agents do not carry overhead share, so the `OVERHEAD_SHARE` line is zero. In both variants the closing statement lines are born `PROVISIONAL` and finalize atomically with the close, ending in `FINAL`. A `FINAL` line may later move to `VOIDED` if the close is unwound by a subsequent re-contract failure — a path reserved in the state machine but not reachable in current flows — in which case a paired reversing `CommissionEntry` is posted.

### 3.8. The Closing Cascade and Trust Reconciliation

The close fans out through the commission ledger in three hops. The first hop posts a `GCI_RECEIPT` entry in `ESCROW_HELD` status for the gross commission income arriving into trust. The second hop splits the receipt: an `AGENT_DISBURSEMENT` entry per agent in `AGENT_PAYABLE` status for the agent's disbursement, and an `OFFICE_FEE_ACCRUAL` entry in `OFFICE_FEE_ACCRUED` status for the office's split and fee accrual. The third hop fires only when an `ACTIVE` referral agreement covers the deal: a `REFERRAL_PAYOUT` entry in `REFERRAL_PAYABLE` status for the cross-office fee, and the covering referral agreement is advanced to `FULFILLED` with `fulfilled_transaction_id` set to the closing transaction (see §3.11). Within the same close, the advance-recovery waterfall (§3.9) is applied against the agent's open balances, and the transaction's `version` is incremented.

Reconciliation is the trust accountant's settlement run. A `TrustAccountant` invokes reconciliation on an office, and the run settles every outstanding payable and accrual: every `AGENT_PAYABLE` entry advances to `DISBURSED` with the office's `trust_balance_cents` reduced by the entry's amount as cash leaves escrow; every `REFERRAL_PAYABLE` entry advances to `DISBURSED` and the referring office receives the payout; every `OFFICE_FEE_ACCRUED` entry advances to `RECONCILED`, recognized as office revenue with the trust balance reduced accordingly. The office's `version` is incremented by the run. Entries in `ESCROW_HELD` and `DEPARTURE_HOLD` are not touched by reconciliation; departure holds settle only through the departure flow (§3.10). A reversal path from `AGENT_PAYABLE` to `REVERSED` exists in the machine for unwinding closes, returning the amount to the `ESCROW_HELD` parent, but it is not reachable in current flows. The ledger can be read entry-by-entry or listed per office, with `office_id`, `transaction_id`, `status`, `entry_kind`, and `entry_month` filters; `entry_month` is the `YYYY-MM` ledger month derived from the logical clock at posting time. Entry kinds are `GCI_RECEIPT`, `AGENT_DISBURSEMENT`, `OFFICE_FEE_ACCRUAL`, `REFERRAL_PAYOUT`, `ADVANCE`, `ADVANCE_RETURN`, `MANUAL_ADJUSTMENT` (the only kind whose `transaction_id` is null), `DEPARTURE_HOLD`, and `DEPARTURE_RELEASE`.

### 3.9. Advances and Their Recovery

A `ManagingBroker` may advance cash to an agent ahead of closing by submitting an `amount_cents`. The advance posts a `CommissionEntry` of kind `ADVANCE` in `DISBURSED` status (cash has left the trust), and the agent's `unearned_advance_balance_cents` is increased by the amount. The agent may later return an advance themselves by submitting an `amount_cents`; the return posts an `ADVANCE_RETURN` entry and decreases `unearned_advance_balance_cents` by the amount, with a return larger than the outstanding balance rejected as `ERR_OVERPAYMENT`.

Whatever remains outstanding at close is recovered through the advance-recovery waterfall, which runs inside the closing-statement calculation once the agent's retention figure is known. The total offset is the smaller of `agent_retention_cents` and `unearned_advance_balance_cents`, and it is allocated across the agent's open invoice lines in a fixed priority order with overflow rolling to the next bucket. The first bucket, walked oldest-first by each line's `created_at` ascending — never by id — covers the agent's outstanding `ADVANCE_RECOVERY`, `PRORATED_DESK_FEE`, and `DESK_FEE` lines on invoices in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE`. The second bucket, also walked oldest-first, covers the agent's `TECH_SUBSCRIPTION` lines and then their `MARKETING` lines. Each touched line's `applied_at_closing_cents` is increased by its applied portion, and the agent's `unearned_advance_balance_cents` is reduced by the total offset. The rounding remainder — should one arise — stays in the last bucket touched; since both bounds are integer cents, no fractional remainders occur.

### 3.10. Agent Departure: Notice, Proration, and Settlement

Departure is agent-initiated. The agent themselves — the caller's `X-User-ID` must equal the agent's `id` — requests termination, moving the agent from `ACTIVE` to `TERMINATION_PENDING`. Three things happen in that request: `termination_requested_at` is set to the logical clock; the agent's `supervision_cadence_days` tightens from 30 to 7, because supervision persists regardless of the compensation model and intensifies during wind-down; and every `InvoiceLine` belonging to the agent whose `applied_at_closing_cents` is below its `amount_cents` on an invoice in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` spawns a `CommissionEntry` of kind `DEPARTURE_HOLD` in `DEPARTURE_HOLD` status, with an amount equal to that line's remaining balance — quarantining the agent's open receivables inside the trust.

A `ManagingBroker` completes the departure once the fourteen-day notice window has passed: the logical clock must be at or past `termination_requested_at` plus fourteen days, and an attempt before that boundary is rejected with `ERR_TERMINATION_WINDOW_OPEN` (HTTP 409). Completion moves the agent to `TERMINATED`, sets `terminated_at`, and decrements the office's `active_agent_count`. In the same request, a departure invoice is generated with `origin` `DEPARTURE` and a `due_date` fourteen days after `terminated_at`, carrying a `PRORATED_DESK_FEE` line and an `ADVANCE_RECOVERY` line computed by the departure-proration calculation, and every `DEPARTURE_HOLD` entry for the agent is resolved: if the departure invoice nets to zero or less, each hold advances through `DEPARTURE_RELEASE` to `DISBURSED`; otherwise the holds stay held against the invoice until it is paid.

Departure proration uses a fixed 30-day month, and both variants pin the same day-count convention so the totals cannot drift. Let `D` be the day-of-month of `termination_requested_at`, counting from 1. The owed variant — used when the departure invoice charges the partial month — computes the prorated desk fee as `desk_fee_cents` multiplied by `D` and divided by 30, rounded half-up to whole cents; that figure becomes the `PRORATED_DESK_FEE` line's `amount_cents`, covering days 1 through `D`. The refund variant — used when the full month's desk fee was already invoiced and paid before termination was requested — computes the credit as `desk_fee_cents` multiplied by `30 - D` and divided by 30, rounded half-up to whole cents, returning days `D+1` through 30; that credit is netted against the departure invoice. The two variants never appear on the same departure invoice, and because both round independently under the same convention, the owed amount plus the refund amount equals the full `desk_fee_cents` exactly. The departure invoice's `ADVANCE_RECOVERY` line carries the agent's full `unearned_advance_balance_cents`, settling the advance balance at exit.

### 3.11. The Cross-Market Referral Network

Offices cooperate across markets through referral agreements: when an office in one market sends a client to an office in another market, the receiving office pays the referring office a negotiated slice of the gross commission. A `ManagingBroker` proposes a `ReferralAgreement` by naming the `referring_office_id`, the `receiving_office_id`, the `agent_id` of the receiving office's agent who will handle the referred client, the negotiated `referral_fee_bps` (between 0 and 5000 inclusive, deducted from gross commission before the agent/office split), and optionally a `replaces_agreement_id` referencing an existing agreement this one supersedes. The new agreement is born `PROPOSED`.

The receiving office's `ManagingBroker` accepts or declines. Acceptance is checked three ways: the caller must belong to the receiving office; the referring office's `market_code` must differ from the receiving office's `market_code` — referral fees apply only across markets, and a same-market pair is rejected with `ERR_SAME_MARKET_REFERRAL` (HTTP 422); and when `replaces_agreement_id` is set, the referenced agreement must exist and be `ACTIVE`, otherwise the request is rejected with `ERR_REPLACED_NOT_ACTIVE` (HTTP 409). On acceptance the agreement moves from `PROPOSED` to `ACTIVE`, and the replaced agreement, when present, is moved to `WITHDRAWN` in the same request — a self-referential cascade. Declining moves the proposal to `DECLINED`.

Either office's `ManagingBroker` may withdraw an `ACTIVE` agreement, but only while it remains unfulfilled: if `fulfilled_transaction_id` is already set, the withdraw is rejected with `ERR_AGREEMENT_LOCKED` (HTTP 409). Fulfillment itself is automatic: when a transaction for the agreement's `agent_id` closes with this agreement applied, the agreement advances from `ACTIVE` to `FULFILLED`, its `fulfilled_transaction_id` is set to that transaction, and the `REFERRAL_PAYOUT` entry has already been posted by the closing cascade (§3.8). Agreements can be listed with `referring_office_id`, `receiving_office_id`, `agent_id`, `status`, `replaces_agreement_id`, and `fulfilled_transaction_id` filters.

### 3.12. Retention Reporting

Because desk-fee economics ride on agent count, franchisees watch retention month over month. A `FranchiseeOwner` or `BrokerOfRecord` computes the retention index for an office by supplying a `period_month` in `YYYY-MM` form and, optionally, a `report_variant` — `CHURN` (the default) or `COHORT`. The resulting `AgentRetentionReport` is born `COMPUTED`; when a newer report is computed for the same office and `period_month`, the prior `COMPUTED` report is moved to `ARCHIVED`.

The `CHURN` variant measures the whole-office headcount across the month, with both window boundaries half-open. The `headcount_start` counts agents of the office whose `onboarded_at` is strictly before the first instant of `period_month` and whose `terminated_at` is either null or at or after that instant. The `headcount_end` applies the same predicate against the first instant of the following month. The report's `retention_bps` is `headcount_end` multiplied by 10000 and divided by `headcount_start`, rounded half-up to integer basis points; the `churned_agent_count` is `headcount_start` minus `headcount_end`. When `headcount_start` is zero there is no baseline to divide by, and the computation is rejected with `ERR_NO_RETENTION_BASELINE` (HTTP 422).

The `COHORT` variant narrows the lens to the agents onboarded within `period_month` itself: `headcount_start` counts only that month's onboarding cohort, and `headcount_end` counts the members of that same cohort still unterminated at the start of the following month. The same formula and the same rounding apply, and an empty cohort is likewise rejected with `ERR_NO_RETENTION_BASELINE`. Reports can be listed per office or across offices, with `office_id`, `period_month`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — an office, a fee schedule, an agent, a fee assignment, an offer, a transaction, a CDA, a manual invoice, an advance, a referral agreement, or a retention report — return `201 Created`. Operations that modify an existing resource (state transitions, payments, reconciliations, the clock set, the monthly billing run) return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock and re-evaluate time-gated states | PlatformAdmin |
| POST | `/offices` | Create a franchise office | FranchiseeOwner |
| GET | `/offices/{officeId}` | Get an office | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/offices` | List offices (filters: `market_code`, `status`, `office_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/close` | Close an office (requires zero ACTIVE agents) | FranchiseeOwner |
| POST | `/fee-schedules` | Create a fee schedule (window must tile, no overlap, adjacency required) | BrokerOfRecord |
| GET | `/fee-schedules/{scheduleId}` | Get a fee schedule | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/fee-schedules` | List fee schedules (filters: `status`, `fee_schedule_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/agents` | Onboard an agent into an office | ManagingBroker |
| GET | `/agents/{agentId}` | Get an agent | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/agents` | List agents (filters: `office_id`, `agent_id`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/agents/{agentId}/terminate` | Agent initiates departure | Agent |
| POST | `/agents/{agentId}/complete-termination` | Finalize departure after the notice window | ManagingBroker |
| POST | `/agents/{agentId}/advance-commission` | Advance commission to an agent | ManagingBroker |
| POST | `/agents/{agentId}/return-advance` | Agent returns an advance | Agent |
| POST | `/agents/{agentId}/fee-assignments` | Propose a fee assignment (OCC on Agent.version) | ManagingBroker |
| GET | `/fee-assignments/{assignmentId}` | Get a fee assignment | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/agents/{agentId}/fee-assignments` | List an agent's fee assignments (filters: `status`, `agent_id`, `fee_schedule_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/fee-assignments/{assignmentId}/accept` | Agent accepts the proposed fee assignment | Agent |
| POST | `/fee-assignments/{assignmentId}/reject` | Agent rejects the proposed fee assignment | Agent |
| POST | `/fee-assignments/{assignmentId}/cancel` | Broker cancels a proposed fee assignment | ManagingBroker |
| GET | `/fee-assignments` | List fee assignments across agents (filters: `agent_id`, `fee_schedule_id`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/offers` | Register a buyer offer on a listing | Agent, ManagingBroker |
| GET | `/offers/{offerId}` | Get an offer (expiry re-checked on read) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offers/{offerId}/counter` | Counter the offer | Agent |
| POST | `/offers/{offerId}/reoffer` | Buyer re-offers after a counter (round increments) | Agent |
| POST | `/offers/{offerId}/accept` | Accept the offer and open a transaction | Agent |
| POST | `/offers/{offerId}/reject` | Reject the offer | Agent |
| POST | `/offers/{offerId}/withdraw` | Withdraw a countered offer | Agent |
| GET | `/offers` | List offers (filters: `office_id`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/transactions` | Create a transaction directly (lands LISTED) | ManagingBroker |
| GET | `/transactions/{transactionId}` | Get a transaction | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/transactions` | List transactions (filters: `office_id`, `status`, `selling_agent_id`, `listing_agent_id`, `offer_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/transactions/{transactionId}/request-close` | Request closing (requires APPROVED CDA and ACTIVE listing agent) | Agent |
| POST | `/transactions/{transactionId}/close` | Close the transaction: run the closing statement, post escrow entries, apply advance offsets, fulfill referrals | ManagingBroker |
| POST | `/transactions/{transactionId}/mark-fell-through` | Mark a deal fallen through | Agent |
| POST | `/transactions/{transactionId}/relist` | Re-list a fallen-through deal | Agent |
| POST | `/transactions/{transactionId}/recontract` | Put a re-listed deal back under contract | Agent |
| POST | `/transactions/{transactionId}/cdas` | Open a Commission Disbursement Authorization review ladder | ManagingBroker |
| GET | `/cdas/{cdaId}` | Get a CDA | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/transactions/{transactionId}/cdas` | List CDAs for a transaction | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/cdas` | List CDAs across transactions (filters: `transaction_id`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/cdas/{cdaId}/review` | Review the current rung of the ladder (APPROVE advances, REJECT cycles back to rung 0) | ComplianceAuditor, TrustAccountant, ManagingBroker |
| GET | `/closing-statement-lines/{lineId}` | Get a single closing statement line | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/closing-statement-lines` | List closing statement lines across transactions (filters: `transaction_id`, `agent_id`, `applied_invoice_line_id`, `variant`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/transactions/{transactionId}/closing-statement-lines` | List the closing statement lines for a transaction (filters: `variant`, `status`, `transaction_id`, `agent_id`, `applied_invoice_line_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/invoice-lines` | List invoice lines across invoices (filters: `invoice_id`, `line_kind`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/generate-invoices` | Monthly billing run: one AUTO_RUN invoice per ACTIVE agent with an in-force ACCEPTED assignment | ManagingBroker |
| POST | `/invoices` | Create a manual invoice (lands DRAFT) | ManagingBroker |
| GET | `/invoices/{invoiceId}` | Get an invoice (overdue/collections re-evaluated on read) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/invoices` | List invoices (filters: `office_id`, `agent_id`, `invoice_id`, `status`, `billing_month`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/invoices/{invoiceId}/issue` | Issue a DRAFT manual invoice | ManagingBroker |
| POST | `/invoices/{invoiceId}/pay` | Agent pays an invoice (full or partial) | Agent |
| POST | `/invoices/{invoiceId}/cancel` | Cancel a DRAFT invoice | ManagingBroker |
| POST | `/invoices/{invoiceId}/write-off` | Write off a COLLECTIONS invoice at least 90 days past due | BrokerOfRecord |
| GET | `/invoice-lines/{lineId}` | Get a single invoice line | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/invoices/{invoiceId}/lines` | List an invoice's lines | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/commission-entries/{entryId}` | Get a single commission entry | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/commission-entries` | List commission entries (filters: `office_id`, `transaction_id`, `status`, `entry_kind`, `entry_month`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/offices/{officeId}/reconcile` | Trust reconciliation run: settles payable and accrued entries | TrustAccountant |
| GET | `/retention-reports/{reportId}` | Get a single retention report | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/retention-reports` | List retention reports across offices (filters: `office_id`, `period_month`, `status`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/referral-agreements` | Propose a cross-market referral agreement | ManagingBroker |
| GET | `/referral-agreements/{agreementId}` | Get a referral agreement | FranchiseeOwner, BrokerOfRecord, ManagingBroker, Agent, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| GET | `/referral-agreements` | List referral agreements (filters: `referring_office_id`, `receiving_office_id`, `agent_id`, `status`, `replaces_agreement_id`, `fulfilled_transaction_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |
| POST | `/referral-agreements/{agreementId}/accept` | Receiving office accepts the referral (cross-market only) | ManagingBroker |
| POST | `/referral-agreements/{agreementId}/decline` | Receiving office declines the referral | ManagingBroker |
| POST | `/referral-agreements/{agreementId}/withdraw` | Either office withdraws an unfulfilled ACTIVE agreement | ManagingBroker |
| POST | `/offices/{officeId}/retention-reports/compute` | Compute the agent retention index for a period month | FranchiseeOwner, BrokerOfRecord |
| GET | `/offices/{officeId}/retention-reports` | List retention reports for an office (filters: `period_month`, `status`, `office_id`) | FranchiseeOwner, BrokerOfRecord, ManagingBroker, TrustAccountant, ComplianceAuditor, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_LICENSE` | 409 Conflict |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_OFFICE_SUSPENDED` | 409 Conflict |
| `ERR_OFFICE_NOT_EMPTY` | 409 Conflict |
| `ERR_CDA_EXISTS` | 409 Conflict |
| `ERR_CDA_NOT_APPROVED` | 409 Conflict |
| `ERR_REVIEW_RUNG_MISMATCH` | 409 Conflict |
| `ERR_AGENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_NEGOTIATION_EXHAUSTED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_SAME_MARKET_REFERRAL` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_LOCKED` | 409 Conflict |
| `ERR_REPLACED_NOT_ACTIVE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_TERMINATION_WINDOW_OPEN` | 409 Conflict |
| `ERR_WRITE_OFF_TOO_EARLY` | 409 Conflict |
| `ERR_NO_RETENTION_BASELINE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
