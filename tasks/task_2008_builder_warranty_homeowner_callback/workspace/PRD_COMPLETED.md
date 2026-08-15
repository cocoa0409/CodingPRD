# Builder Warranty API — Product Requirements Document

## 1. Introduction

Production home builders run their warranty departments on an industry-standard term structure — one year of workmanship coverage, two years on the major systems, ten years on the structure itself — and every homeowner callback inside those windows is a cost event that must be triaged, dispatched, verified, and accounted for. This document specifies the Builder Warranty API, the system of record for that operation: it registers homeowners and warranted homes, intakes service requests, dispatches trade partners, recovers callback costs from responsible subcontractors through a chargeback workflow, files structural claims with a third-party warranty administrator where the program cedes that risk, and maintains a per-home warranty reserve that accrues monthly against expected lifetime warranty spend.

The department's pain points are specific. Coverage decisions must be defensible — the same category-to-tier map and the same half-open term windows applied every time, homeowner education shipped on every denial, and a formal dispute path when the homeowner pushes back. Response and completion service levels differ by severity, are tracked to the second, and escalate automatically when breached. Cash recovery runs on two rails — subcontractor chargebacks and administrator claims — while finance needs the reserve ledger to be append-only and self-evidently conserved, with trend alerts when a home's warranty fund runs thin. Six roles interact with the API, each confined to its own lane.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Section 3 develops the business workflows in narrative form; where a rule has both a global shape and a workflow-specific trigger, the trigger is described with the workflow.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity. The declared role must be one of six: `Homeowner`, `WarrantyRep`, `TradePartner`, `WarrantyManager`, `FinanceAdmin`, or `WarrantyAdministrator`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting homeowner record, and ownership checks compare the relevant resource's `homeowner_id` — directly on a service request, or through the home for a work order — against `X-User-ID`. When `X-User-Role` is `TradePartner`, `X-User-ID` is the `id` of the acting trade partner; a partner may complete only its own dispatched work orders and contest only chargebacks issued against it. An entity-backed caller acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining four roles — `WarrantyRep`, `WarrantyManager`, `FinanceAdmin`, and `WarrantyAdministrator` — are opaque: for each of them `X-User-ID` is an operator identifier not tied to any persisted entity, and the server performs no ownership comparison against any entity `id`. Duties are segregated across the opaque roles: representatives run triage, dispatch, follow-up, chargeback issuance, and claim filing; the manager holds master data, dispute resolution, chargeback approval and resolution, the operations checkpoint, and the clock; finance posts reserve adjustments and applies chargeback cash; the external administrator decides structural claims. The roles that issue a chargeback, approve or resolve it, and apply its payments are three different roles.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.4), never the wall clock.
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

A request to an undeclared path is rejected with `ERR_INVALID_REQUEST` at HTTP 404, a declared path with an unsupported method with `ERR_INVALID_REQUEST` at HTTP 405, and any unexpected internal failure with `ERR_INVALID_REQUEST` at HTTP 400.

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside its range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list responses are sorted by `created_at` in ascending order, with ties broken by creation order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server runs on a logical clock, never the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z; it advances only when a `WarrantyManager` sets it through the clock endpoint (`POST /_clock/set_current_utc`) with a `to_iso8601` payload, and the response echoes the new reading as `current_utc`. The payload value must be a valid ISO 8601 datetime, else `ERR_INVALID_REQUEST`; any valid instant is accepted, earlier or later than the current reading. Every timestamp the system stamps — intake times, deadlines, issuance times, decision times — and every deadline evaluation derives from this logical reading. Time comparisons are made at second precision; ISO 8601 datetimes supplied to the API are interpreted at second precision — fractional seconds are truncated — and a value without a timezone offset is read as UTC. Each deadline rule in Section 3 states whether its boundary is inclusive (an event exactly at the deadline instant is accepted) or exclusive (the evaluation instant must be strictly past the deadline); where a coverage window is described as half-open, its end instant is excluded from coverage.

### 2.5. Common Resource Properties

All primary resources — homeowners, homes, service requests, work orders, trade partners, chargebacks, warranty reserves, and administrator claims — share four system-managed properties:

- `id`: a server-minted UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation; at creation it equals `created_at`.
- `version`: an integer that starts at 1 at creation and increments by one on every mutation.

Recomputation of a derived field — a request's rolled-up cost, a reserve's balance or alert status, a partner's counters — is a mutation of the owning resource and therefore refreshes `updated_at` and increments `version`, even when no client wrote to that resource directly. A resource field that has no value yet is serialized with a JSON `null` rather than omitted from the response.

Ledger lines are the exception. A reserve entry is immutable once appended and carries only `id` and `created_at`; `updated_at` and `version` are absent.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents: sale prices, cost estimates, invoiced costs, chargeback amounts, reserve balances, claim amounts. Rates are decimal fractions — the accrual rate, the administration fee rate — applied by multiplication against cent amounts. Rounding is always round-half-up to whole cents, applied at the pinned points stated with each calculation in Section 3: the expected lifetime accrual is rounded once when computed; each monthly accrual is rounded individually; the chargeback administration fee is rounded immediately after the percentage multiplication and before its cap is applied; the trend-alert threshold is rounded when evaluated. Deadline and coverage comparisons use instants at second precision, never calendar dates alone.

### 2.7. Validation Order and Error Precedence

When a request violates several rules at once, exactly one error is returned: the first failure in the fixed precedence below.

1. Authentication: `X-User-ID` and `X-User-Role` are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. Authorization: the role is permitted on this endpoint, else `ERR_FORBIDDEN`.
3. Ownership: on the five ownership-scoped operations — service-request intake, dispute filing, work-order completion, work-order verification, and chargeback contest — an entity-backed caller must own the target, else `ERR_NOT_RESOURCE_OWNER`.
4. Identifier resolution: path and body identifiers resolve in a fixed left-to-right order — home, then service request, then work order, then trade partner, then chargeback, then warranty reserve, then administrator claim, and finally homeowner references (the `homeowner_id` on a home-creation payload, or the homeowner path id on a homeowner fetch). The first unresolvable identifier produces its own 404: `ERR_HOME_NOT_FOUND`, `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_TRADE_PARTNER_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND`, `ERR_RESERVE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_HOMEOWNER_NOT_FOUND`. Resolution is attempted only for identifiers present as non-empty strings; an absent, empty, or non-string identifier is not a 404 but a request-shape failure under item 5.
5. Request shape: required fields present, enum values in domain, numeric constraints honored — a strictly positive sale price, non-negative cost figures, a strictly positive claimed amount, a satisfaction score between one and five — and a visit window that ends strictly after it begins, else `ERR_INVALID_REQUEST`. A required string field must be a non-empty string, whitespace-only counting as missing; an explicit JSON `null` supplied for an optional field is treated as the field being omitted; and no format validation beyond non-emptiness is applied to email addresses.
6. State legality: the two state rejections partition by terminality. If the target sits in a terminal state for its lifecycle — a `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a `PAID`, `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the rejection is `ERR_ALREADY_TERMINAL`. If the state is non-terminal but the requested transition is not defined from it, the rejection is `ERR_INVALID_STATE`.
7. Stale-version guard on reserve writes: `ERR_STALE_VERSION` (see §2.9).
8. Business rules, in the endpoint-specific orders given in Section 3.

### 2.8. The Warranty Reserve Ledger

Every warranted home owns exactly one warranty reserve, created together with the home, and the reserve's truth is its ledger: an append-only sequence of reserve entries in five kinds — `ACCRUAL`, `TRUE_UP`, `MANUAL_ADJUSTMENT`, `DRAW`, and `RECOVERY`. Entries are never edited or deleted; corrections are new entries. Entry amounts are signed cents: accruals, true-ups, and recoveries post positive; draws post negative; manual adjustments may carry either sign. The reserve's `balance_cents` is the signed sum of every entry ever posted — the ledger's conservation invariant — and its derived totals decompose by kind: `accrued_to_date_cents` sums accrual and true-up amounts, `drawn_to_date_cents` sums the absolute values of draws, and `recovered_to_date_cents` sums recoveries. Because a home's reserve is one-to-one, filtering the reserve collection by `home_id` yields an array of length zero or one, never more.

Each entry records its `reserve_id`, its `kind`, its signed `amount_cents`, and all five provenance fields — `month_index` (set for accruals), `work_order_ref` (set for draws), `chargeback_ref` or `claim_ref` (set for recoveries), and a free-text `note` (set for manual entries) — each serialized as `null` when not relevant. Every entry insertion re-evaluates the owning reserve's trend alert (§3.7). Entries are read back in chronological order.

### 2.9. Optimistic Concurrency Control

Exactly one endpoint is guarded by optimistic concurrency: posting a reserve adjustment or true-up. The request must carry `expected_reserve_version`, set to the reserve's `version` as the client last observed it; the field is non-optional. If the reserve's version has advanced since that observation — because the sweep posted accruals, a work-order completion posted a draw, or another adjustment landed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the reserve and resubmit with the fresh version. A successful adjustment itself increments the reserve's `version` by one. No other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Book of Business

A `WarrantyManager` registers each homeowner with a `full_name` and an `email`; `phone` is optional and stays unset when not provided. Registering a home takes the owning `homeowner_id` — an unknown homeowner is refused with `ERR_HOMEOWNER_NOT_FOUND` — the `lot_number` and `community_name` locating the property within its subdivision, a strictly positive `sale_price_cents`, the `closing_date` on which title transferred, and the `warranty_program`: either `STANDARD`, meaning the builder self-administers, or `THIRD_PARTY_ADMINISTERED`, meaning structural risk is ceded to an external administrator. Homes may be listed with `homeowner_id` or `community_name` filters.

The closing date anchors all three coverage tiers, and the server computes the tier end dates at creation: `workmanship_end_date` twelve months after closing, `systems_end_date` twenty-four months after, and `structural_end_date` one hundred twenty months — ten years — after. Each window is half-open: coverage runs from the closing instant — 00:00:00Z at the start of the closing date — up to but not including the tier end instant — 00:00:00Z at the start of the tier end date — so a defect reported exactly at an end date is already out of term. Creating the home also creates its warranty reserve — version 1, zero balance, `last_accrual_month_index` 0, expected lifetime accrual computed from the sale price as described in §3.7 — and until the first accrual lands the reserve's alert reads `ELEVATED`, because a zero balance sits below the alert threshold whenever the expected accrual is positive.

Trade partners are registered with a `company_name`, a `trade` drawn from `PLUMBING`, `ELECTRICAL`, `HVAC`, `DRYWALL`, `FLOORING`, or `GENERAL`, and a `contact_email`. A partner's `daily_capacity_minutes` defaults to 480 — one eight-hour crew day — and must be positive when supplied. Two counters track each partner's exposure: `open_work_order_count`, the number of its visits currently `SCHEDULED`, and `outstanding_chargeback_cents`, its unpaid chargeback balance (§3.6).

### 3.2. Intake and Coverage Triage

A callback begins when a `Homeowner` files a service request against their own home, supplying `home_id`, the `item_category`, a `severity`, and a free-text `description`. The reporter's `homeowner_id` is copied from `X-User-ID`; a homeowner may not file against someone else's home (`ERR_NOT_RESOURCE_OWNER`). The category vocabulary is ten values: `DRYWALL_PAINT`, `FLOORING`, `PLUMBING`, `ELECTRICAL`, `HVAC`, `FOUNDATION`, `FRAMING`, `LANDSCAPING`, `APPLIANCE`, and `ROUTINE_MAINTENANCE`. Severity is `EMERGENCY`, `URGENT`, or `STANDARD`. The server stamps `reported_at` from the logical clock — coverage is judged on this instant, and only this instant — sets the status to `RECEIVED`, and anchors the response service level: `response_due_at` is `reported_at` plus four hours for `EMERGENCY`, twenty-four hours for `URGENT`, or seventy-two hours for `STANDARD`. A new request carries `response_breached` and `completion_breached` false, `escalation_level` 0, `reopened_count` 0, and its decision fields — `determined_tier`, `approved_at`, `denied_at`, `dispute_outcome`, and the rest — unset. Requests may be listed with `home_id`, `homeowner_id`, `status`, or `severity` filters.

Triage is the `WarrantyRep`'s assess action, allowed only from `RECEIVED` or `REOPENED`; any other non-terminal state draws `ERR_INVALID_STATE`, and a `CLOSED` request draws `ERR_ALREADY_TERMINAL`. The representative submits `warrantable`, true or false; an `assess_notes` field may be supplied but is not persisted on the request. The two branches are checked against different rule sets, and within the warrantable branch the checks run in a fixed order.

A warrantable assessment first confronts the category map. Three categories — `LANDSCAPING`, `APPLIANCE`, and `ROUTINE_MAINTENANCE` — are excluded from coverage entirely: they map to no tier and no term window, so assessing one of them warrantable is rejected with `ERR_ITEM_NOT_COVERED` before any date arithmetic is considered. The remaining seven categories map to tiers: `DRYWALL_PAINT` and `FLOORING` to `WORKMANSHIP`; `PLUMBING`, `ELECTRICAL`, and `HVAC` to `SYSTEMS`; `FOUNDATION` and `FRAMING` to `STRUCTURAL`. Only after the category check passes does the temporal check run: `reported_at` must fall inside the tier's half-open window — on or after the `closing_date` and strictly before that tier's end date — or the assessment is rejected with `ERR_OUT_OF_WARRANTY`. Approving an out-of-term or excluded item is therefore impossible: it is an error, never a silent denial. For a reopened request, these same coverage checks are evaluated against the original `reported_at`, never a new intake time. On success the server records `determined_tier` from the category map, stamps `approved_at`, anchors the completion service level — `completion_due_at` is `approved_at` plus three days for `EMERGENCY`, seven days for `URGENT`, or thirty days for `STANDARD` — and moves the request to `APPROVED`. Fields recorded by an earlier denial — `denied_at`, `denial_reason_code`, `education_packet_code`, `dispute_deadline_at` — and any recorded `dispute_outcome` are retained, not wiped.

A non-warrantable assessment must be complete to be recorded. The `denial_reason_code` — one of `OUT_OF_TERM`, `EXCLUDED_CATEGORY`, `HOMEOWNER_CAUSED`, or `NORMAL_MAINTENANCE` — is part of the request's shape, so its absence is an `ERR_INVALID_REQUEST`. With a reason code present but no `education_packet_code`, the denial is refused with `ERR_EDUCATION_PACKET_REQUIRED`: every non-warrantable determination ships homeowner education, without exception. A recorded denial stamps `denied_at`, sets the dispute window `dispute_deadline_at` thirty days later, and moves the request to `DENIED`.

Both assess branches also evaluate the response service level at the assessment instant. An assessment is late only when that instant is strictly later than `response_due_at` — assessing exactly at the deadline is on time. A late assessment sets `response_breached` true and raises `escalation_level` to at least 1.

### 3.3. Dispatching the Trades

From `APPROVED`, a `WarrantyRep` dispatches a subcontractor by creating a work order naming the `service_request_id` and the `trade_partner_id` — unknown identifiers resolve to `ERR_SERVICE_REQUEST_NOT_FOUND` or `ERR_TRADE_PARTNER_NOT_FOUND` — a visit window from `window_start` to `window_end`, a non-negative `estimated_cost_cents`, and the triage attribution `defect_responsibility`: `SUBCONTRACTOR`, `BUILDER`, or `HOMEOWNER`. The visit's `duration_minutes` is derived as the whole minutes between window end and window start.

Three scheduling guards run in order, after shape and state checks. First, the window must not begin in the past: a `window_start` strictly before the current clock is `ERR_INVALID_WINDOW`, while a window opening exactly now is acceptable. Second, trade capacity: the sum of `duration_minutes` over the partner's `SCHEDULED` work orders whose window start falls on the same UTC calendar date as the new window start, plus the new visit's duration, must not exceed `daily_capacity_minutes` — a day filled to exactly capacity is allowed, and one minute over draws `ERR_TRADE_CAPACITY_EXCEEDED`. Third, home visit overlap: the new window conflicts with an existing `SCHEDULED` visit at the same home when the new start falls before the existing visit's end and the existing visit's start falls before the new end; back-to-back windows that merely touch are permitted, and a genuine overlap draws `ERR_HOME_VISIT_OVERLAP`.

A created work order starts `SCHEDULED`, bumps the partner's `open_work_order_count` by one, and — when it is the request's first dispatch — automatically moves the parent request from `APPROVED` to `IN_SERVICE`. Work orders may be listed with `service_request_id`, `trade_partner_id`, or `status` filters.

### 3.4. Completion, Verification, and the Rework Loop

Completion belongs to the dispatched partner and only that partner (`ERR_NOT_RESOURCE_OWNER`), and only from `SCHEDULED`. The partner reports the final invoiced `actual_cost_cents`, which may not be negative; the server stamps `completed_at` and fires a three-level cascade. The parent request's `actual_cost_cents` is recomputed as the sum of invoiced costs over its work orders in `COMPLETED` or `ACCEPTED`. The home's reserve posts a `DRAW` entry of negative the invoiced cost with `work_order_ref` set — a zero invoiced cost still posts a zero-amount `DRAW` — recomputing `balance_cents` and `drawn_to_date_cents` and re-evaluating the trend alert. And a linked chargeback still provisional and sitting in `ISSUED` or `CONTESTED` is refinalized against the invoiced cost: `final_amount_cents` is recomputed by the chargeback formula of §3.6, and `amount_basis` moves to `FINAL` — or, when the recomputed final amount is zero, the chargeback voids itself automatically. A chargeback already approved is not refinalized; its payable amount remains the provisional figure.

Verification belongs to the homeowner whose home was serviced, and only from `COMPLETED`. An `outcome` of `ACCEPT` moves the work order to `ACCEPTED`; an `outcome` of `REJECT` requires a `rejection_reason` and moves the work order to `REJECTED`, opening the workmanship rework loop. Acceptance also bubbles upward: when every work order of the parent request sits in `ACCEPTED` or `CANCELLED` and at least one is `ACCEPTED`, the request advances itself from `IN_SERVICE` to `PENDING_FOLLOWUP`, stamping `followup_entered_at` — and if that instant is strictly later than `completion_due_at`, `completion_breached` is set and `escalation_level` rises to 2. Entry exactly at the completion deadline is on time.

A rejected work order is rescheduled, not abandoned. Rescheduling — from `REJECTED` or directly from `SCHEDULED` — replaces `window_start` and `window_end` and re-runs the full battery: window shape, not-in-past, capacity, and overlap, with the work order being rescheduled itself excluded from the capacity sum and the overlap scan. Returning from `REJECTED` to `SCHEDULED` also bumps `open_work_order_count` by one and clears `completed_at`; the recorded `rejection_reason` is retained, and the retained `actual_cost_cents` stays on the record for audit but drops out of the parent request's rolled-up cost until the visit completes again, because the roll-up counts only `COMPLETED` and `ACCEPTED` work orders. The earlier reserve draw is not reversed — ledger entries are append-only — so the re-completion posts a second `DRAW` for the new cost. A reschedule within `SCHEDULED` leaves the partner's count unchanged. Cancelling a `SCHEDULED` work order moves it to `CANCELLED` — a `cancel_reason` may be supplied but is not persisted — decrements the partner's count by one, and voids a linked provisional chargeback still in `ISSUED`.

### 3.5. Follow-Up, Closure, and the Dispute Cycle

Closure comes two ways. The representative's follow-up call, allowed only from `PENDING_FOLLOWUP`, records a `satisfaction_score` from one to five — optional `notes` are accepted but not persisted — stamps `closed_at`, and lands the request in its terminal `CLOSED` state. Alternatively, a request left waiting in `PENDING_FOLLOWUP` is closed by the operations sweep once the clock reaches `followup_entered_at` plus fourteen days, stamping `closed_at` without a score.

A denied homeowner has recourse. Within thirty days of denial — the `dispute_deadline_at` boundary is inclusive, so a dispute filed exactly at the deadline is accepted and one instant later is `ERR_DISPUTE_DEADLINE_PASSED` — the owning homeowner files a dispute with their `dispute_reason`, moving the request from `DENIED` to `DISPUTED`. Disputes are arbitration intake; resolution belongs to the `WarrantyManager`, acting only on a `DISPUTED` request and submitting both an `outcome` and `resolution_notes` — the notes are required but not persisted on the request — with each outcome a different fork. `HOMEOWNER_PREVAILS` reopens the request: `dispute_outcome` is recorded, `reopened_count` increments, the response deadline re-anchors to the reopen instant plus the severity's response hours with `response_breached` cleared and `escalation_level` raised to at least 1, and the coverage fields — `completion_due_at`, `approved_at`, and `determined_tier` — are wiped, because coverage must be re-assessed from scratch against the original `reported_at`. `BUILDER_UPHELD` re-denies: `denied_at` re-stamps to the resolution instant and the thirty-day dispute window re-arms from the new denial, so the homeowner may dispute again. `SETTLED` closes the request outright with `closed_at` stamped. This is the arbitration cycle: `DENIED` to `DISPUTED` to `REOPENED`, assess again, and the loop continues until a closure sticks — and a re-assessment that denies from `REOPENED` clears any recorded `dispute_outcome` while re-arming the window.

### 3.6. Subcontractor Chargebacks

When the triage attribution is `SUBCONTRACTOR`, the representative may issue a chargeback against the work order — but only while the work order is still `SCHEDULED`, and only if no non-`VOID` chargeback already exists for it. The uniqueness check fires first, as `ERR_DUPLICATE_CHARGEBACK`; only then does eligibility bite, with `ERR_NOT_CHARGEBACKABLE` for a wrong attribution or a work order that has already left `SCHEDULED`. Issuance after completion is refused precisely so the provisional-to-final progression stays observable. Issuance denormalizes the partner onto the chargeback as its `trade_partner_id`, stamps `issued_at`, sets the ten-day contest window `contest_deadline_at` — inclusive, like the dispute window — and records a `provisional_amount_cents` computed from the work order's `estimated_cost_cents`, with `amount_basis` `PROVISIONAL` and nothing yet collected. Chargebacks may be listed with `work_order_id`, `trade_partner_id`, or `status` filters.

The chargeback formula is the department's recovery schedule, applied identically to estimates and invoices. From the cost basis, subtract the 25,000-cent deductible — two hundred fifty dollars — flooring the result at zero; cap the recoverable portion at 500,000 cents; then add an administration fee of ten percent of the capped amount, rounded half-up to whole cents immediately after the multiplication and itself capped at 15,000 cents. The payable amount is the capped portion plus the fee. When the formula yields zero — a cost at or under the deductible — the chargeback voids itself rather than stand for nothing.

The chargeback's books are straightforward. `payable_amount_cents` is the final amount once `amount_basis` is `FINAL`, and the provisional amount while the basis is still `PROVISIONAL`. `outstanding_cents` is payable minus `collected_cents`, recomputed whenever the payable amount recomputes — including while the chargeback still sits in `ISSUED` or `CONTESTED` — and forced to zero on waiver or voiding. The partner's `outstanding_chargeback_cents` aggregates outstanding across its chargebacks in `ISSUED`, `APPROVED`, `CONTESTED`, `UPHELD`, or `REDUCED`, and is recomputed on every change.

From `ISSUED`, the workflow forks. The charged partner — and only that partner — may contest within the window, filing a `contest_reason` that moves the chargeback to `CONTESTED`; after the deadline the attempt is `ERR_CONTEST_WINDOW_CLOSED`. Or the chargeback is approved, moving to `APPROVED`: manually by the `WarrantyManager`, optionally with `approve_notes` (accepted but not persisted) — the only route for amounts above the auto-approval cap — or automatically by the operations sweep, which walks `ISSUED` chargebacks from earliest `issued_at` first, breaking ties by creation order, and approves each whose contest deadline has strictly passed and whose payable amount is at most 100,000 cents; a payable exactly at the one-thousand-dollar cap is approved.

A contest lands on the `WarrantyManager`'s desk, and resolution — allowed only from `CONTESTED` — is a three-way fork with divergent books, each leg carrying the manager's `resolution_notes`. `UPHELD` keeps the full amount. `REDUCED` requires a `reduced_amount_cents` that is positive and strictly below the current payable amount — a failing amount is rejected with `ERR_INVALID_REQUEST`, a check evaluated only after the resolve's state legality has passed; it overwrites `final_amount_cents` with the reduced figure, moves the basis to `FINAL`, and recomputes the outstanding balance and the partner's aggregate. `WAIVED` zeroes the outstanding balance and recomputes the partner's aggregate — and posts nothing to the reserve, because a chargeback was never drawn against the reserve in the first place; waiver is pure compensation to the partner and leaves no ledger footprint.

Collection is the `FinanceAdmin`'s lane. A payment against an `APPROVED`, `UPHELD`, or `REDUCED` chargeback records `amount_cents` — optionally with a `payment_reference`, which is accepted but not persisted — and the amount must be positive and no more than the outstanding balance; any violation is `ERR_OVERPAYMENT`. A partial payment adds to `collected_cents`, recomputes the outstanding balance, and leaves the status untouched. The payment that exactly settles the outstanding balance moves the chargeback to `PAID` and credits the home's reserve with a `RECOVERY` entry for the amount, `chargeback_ref` attached, recomputing `balance_cents` and `recovered_to_date_cents` and re-evaluating the trend alert.

Two automatic voidings complete the machine: a provisional chargeback whose final amount recomputes to zero at completion voids from `ISSUED` or `CONTESTED`, and a provisional chargeback in `ISSUED` voids when its work order is cancelled. Either way the outstanding balance zeroes and the partner's aggregate recomputes. `PAID`, `WAIVED`, and `VOID` are terminal.

### 3.7. Reserve Accounting and the Operations Sweep

The reserve funds warranty work before it happens. At home creation the expected lifetime accrual is set: `expected_lifetime_accrual_cents` is the `sale_price_cents` multiplied by the accrual rate of one-half of one percent — 0.005 — rounded half-up to whole cents. Funding then follows a straight-line schedule over one hundred twenty monthly anniversaries of the closing date. Each of the first one hundred nineteen months posts the expected accrual divided by 120, each month rounded half-up to whole cents individually; the final month posts the remainder — the expected accrual minus the sum of the one hundred nineteen rounded postings — so the schedule always sums exactly to the expected accrual. This rounding order is pinned: month-by-month, never sum-then-round, because the two orders disagree by cents.

The operations sweep, a `WarrantyManager` capability, is what posts due accruals. Elapsed months are counted as anniversaries of the closing date already reached by the current clock date — an anniversary counts when the clock date is on or after it, and an anniversary that would fall on a day missing from a shorter month lands on that month's last day — capped at 120. The sweep posts one `ACCRUAL` entry per fully elapsed, not-yet-posted month, numbered from `last_accrual_month_index` plus one through the elapsed count, then advances `last_accrual_month_index` to the elapsed count when the count is ahead — the index never moves backward, so a clock set behind already-accrued months posts nothing; a month already posted is never posted twice, so re-running the sweep is safe. Each posting re-evaluates the reserve's trend alert.

Finance may correct the schedule. Posting to a reserve carries the stale-version guard of §2.9 — the request's `expected_reserve_version` must match the reserve's current `version` — along with a `kind` and an optional `note`. A `MANUAL_ADJUSTMENT` carries a signed, non-zero `amount_cents`; a zero adjustment is `ERR_INVALID_ADJUSTMENT`. A `TRUE_UP` carries a `revised_accrual_rate`, which must be positive — a non-positive rate is likewise `ERR_INVALID_ADJUSTMENT`, while omitting the field the kind requires is a shape error, `ERR_INVALID_REQUEST`. The true-up re-rates the home: the expected lifetime accrual is recomputed as the sale price times the revised rate, rounded half-up, and a single `TRUE_UP` entry posts for the difference between what the new schedule would have accrued for the months already elapsed — the elapsed count times the new monthly amount, the new expected divided by 120 and rounded half-up — and the `accrued_to_date_cents` standing to date; the entry carries that signed difference, which may be zero or negative, and posts regardless. Future months then accrue at the new monthly amount, and the true-up advances `last_accrual_month_index` to the elapsed month count when that count is ahead, so the sweep never re-accrues the months the true-up covered. Identical homes at identical elapsed months therefore hold different accruals once one is re-rated. Either posting recomputes the reserve's accrual and balance and re-evaluates the alert, and a successful adjustment is itself a mutation that increments the reserve's `version` by one. The response carries the created ledger entry.

The trend alert classifies each reserve after every entry. A balance below zero is `DEPLETED`. Otherwise, a balance below the alert threshold — one fifth of the expected lifetime accrual, rounded half-up to whole cents — is `ELEVATED`. Anything at or above the threshold is `NORMAL`. Both comparisons are strictly-below triggers: a balance exactly equal to the threshold is `NORMAL`, and — because the threshold is positive whenever the expected accrual is positive — a balance of exactly zero is `ELEVATED`. Reserves may be listed with `home_id` or `alert_status` filters, and a reserve's ledger may be read with a `kind` filter.

The sweep is also the metronome for everything time-based. Beyond accruals, each run raises the breach flags: requests still in `RECEIVED` whose response deadline is strictly past are marked `response_breached` with escalation level 1, and requests still in `APPROVED` or `IN_SERVICE` whose completion deadline is strictly past are marked `completion_breached` with escalation level 2. It auto-approves the eligible chargebacks described in §3.6 and auto-closes the stale follow-ups described in §3.5. The sweep reports its work as counts: `accrual_entries_posted`, `chargebacks_auto_approved`, `requests_marked_response_breached`, `requests_marked_completion_breached`, and `requests_auto_closed`.

### 3.8. Third-Party Administrator Claims

Homes on the `THIRD_PARTY_ADMINISTERED` program cede their structural risk. When a structural request is approved on such a home, the representative files a claim with the administrator, naming the `service_request_id` and a strictly positive `claimed_amount_cents`, optionally recording the administrator's `external_reference`; the claim's `home_id` is denormalized from the request at filing, and the claim is born `SUBMITTED`. Three gates guard filing, in order: one claim per service request, else `ERR_DUPLICATE_CLAIM`; the home's `warranty_program` must be `THIRD_PARTY_ADMINISTERED`, else `ERR_PROGRAM_MISMATCH`; and the request must be `APPROVED` with `determined_tier` `STRUCTURAL`, else `ERR_CLAIM_TIER_INELIGIBLE`. Claims may be listed with `service_request_id`, `home_id`, or `status` filters.

Decision belongs to the `WarrantyAdministrator`, acting only on a `SUBMITTED` claim. An `outcome` of `ACCEPT` carries `approved_amount_cents`, positive and no more than the claimed amount — an acceptance without a conforming amount fails request validation — stamps `decided_at`, moves the claim to `PAID`, and posts a `RECOVERY` entry for the approved amount to the home's reserve, `claim_ref` attached, recomputing the balance and recovered totals and re-evaluating the alert. An `outcome` of `DENY` requires the administrator's `denial_reason`, stamps `decided_at`, and moves the claim to `DENIED`, posting nothing. Both outcomes are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — a homeowner, a home, a service request, a work order, a trade partner, a chargeback, a reserve ledger entry, or an administrator claim — return `201 Created`. Operations that act on an existing resource without creating a new one — assessments, follow-ups, disputes, resolutions, completions, verifications, reschedules, cancellations, approvals, contests, payments, decisions, the sweep, and the clock — return `200 OK`. Request payloads, response bodies, and side effects are defined by the workflows in Section 3; this table is only the HTTP contract and the role gate.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/homeowners` | Register a homeowner | WarrantyManager |
| GET | `/homeowners/{id}` | Fetch a homeowner | WarrantyManager, WarrantyRep, Homeowner |
| POST | `/homes` | Create a warranted home; auto-creates its warranty reserve and computes the three tier end dates | WarrantyManager |
| GET | `/homes/{id}` | Fetch a home | WarrantyManager, WarrantyRep, FinanceAdmin, Homeowner |
| GET | `/homes` | List homes with filters | WarrantyManager, WarrantyRep, FinanceAdmin |
| POST | `/service-requests` | Homeowner intake of a warranty service request; stamps the logical-clock intake time and anchors the response SLA | Homeowner |
| GET | `/service-requests/{id}` | Fetch a service request | WarrantyManager, WarrantyRep, FinanceAdmin, Homeowner |
| GET | `/service-requests` | List service requests with filters | WarrantyManager, WarrantyRep, FinanceAdmin, Homeowner |
| POST | `/service-requests/{id}/assess` | Triage: warrantable assessments approve with tier and SLA anchors; non-warrantable assessments deny with reason and mandatory education packet | WarrantyRep |
| POST | `/service-requests/{id}/follow-up` | Record customer follow-up and close the request | WarrantyRep |
| POST | `/service-requests/{id}/dispute` | Homeowner disputes a denial (arbitration intake) within the 30-day window | Homeowner |
| POST | `/service-requests/{id}/resolve-dispute` | Record the dispute outcome: homeowner prevails reopens, builder upheld re-denies, settled closes | WarrantyManager |
| POST | `/work-orders` | Dispatch a trade partner to an approved service request with a visit window | WarrantyRep |
| GET | `/work-orders/{id}` | Fetch a work order | WarrantyManager, WarrantyRep, TradePartner, Homeowner |
| GET | `/work-orders` | List work orders with filters | WarrantyManager, WarrantyRep, TradePartner, Homeowner |
| POST | `/work-orders/{id}/complete` | Trade partner marks the visit complete with the invoiced cost; fires the cost cascade | TradePartner |
| POST | `/work-orders/{id}/verify` | Homeowner accepts or rejects completed work | Homeowner |
| POST | `/work-orders/{id}/reschedule` | Move a scheduled or rejected work order to a new visit window | WarrantyRep |
| POST | `/work-orders/{id}/cancel` | Cancel a scheduled work order | WarrantyRep |
| POST | `/trade-partners` | Register a subcontractor | WarrantyManager |
| GET | `/trade-partners/{id}` | Fetch a trade partner | WarrantyManager, WarrantyRep, TradePartner, FinanceAdmin |
| POST | `/chargebacks` | Issue a subcontractor chargeback on a scheduled, subcontractor-responsible work order | WarrantyRep |
| GET | `/chargebacks/{id}` | Fetch a chargeback | WarrantyManager, WarrantyRep, TradePartner, FinanceAdmin |
| GET | `/chargebacks` | List chargebacks with filters | WarrantyManager, WarrantyRep, TradePartner, FinanceAdmin |
| POST | `/chargebacks/{id}/approve` | Manager approval of an issued chargeback (required above the auto-approval cap) | WarrantyManager |
| POST | `/chargebacks/{id}/contest` | Trade partner contests the chargeback within the 10-day window | TradePartner |
| POST | `/chargebacks/{id}/resolve` | Manager resolves a contested chargeback: upheld, reduced, or waived | WarrantyManager |
| POST | `/chargebacks/{id}/payments` | Record a subcontractor payment; full settlement pays the chargeback and credits the reserve | FinanceAdmin |
| GET | `/warranty-reserves/{id}` | Fetch a warranty reserve | WarrantyManager, FinanceAdmin, WarrantyRep |
| GET | `/warranty-reserves` | List reserves; the home filter finds a home's one-to-one reserve as an array of length 0 or 1 | WarrantyManager, FinanceAdmin, WarrantyRep |
| GET | `/warranty-reserves/{id}/entries` | Ledger entries of a reserve, chronological | WarrantyManager, FinanceAdmin, WarrantyRep |
| POST | `/warranty-reserves/{id}/adjustments` | Post a manual adjustment or true-up entry; OCC-guarded | FinanceAdmin |
| POST | `/administrator-claims` | File a structural claim with the third-party warranty administrator, created already submitted | WarrantyRep |
| GET | `/administrator-claims/{id}` | Fetch an administrator claim | WarrantyManager, WarrantyRep, WarrantyAdministrator, FinanceAdmin |
| GET | `/administrator-claims` | List administrator claims with filters | WarrantyManager, WarrantyRep, WarrantyAdministrator, FinanceAdmin |
| POST | `/administrator-claims/{id}/decide` | Administrator accepts (with approved amount; reserve recovery posted) or denies | WarrantyAdministrator |
| POST | `/ops/run-sweep` | Operations checkpoint: post due monthly accruals, raise SLA breach flags, auto-approve eligible chargebacks, auto-close stale follow-ups | WarrantyManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | WarrantyManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described with the workflows that raise them in Sections 2 and 3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_HOME_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TRADE_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGEBACK_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_HOMEOWNER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OUT_OF_WARRANTY` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_EDUCATION_PACKET_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_TRADE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_HOME_VISIT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_CHARGEBACK` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_NOT_CHARGEBACKABLE` | 422 Unprocessable Entity |
| `ERR_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_TIER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CONTEST_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_INVALID_ADJUSTMENT` | 422 Unprocessable Entity |
