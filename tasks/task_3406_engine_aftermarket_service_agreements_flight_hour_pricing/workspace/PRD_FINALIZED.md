# Engine Aftermarket Service Agreements API — Product Requirements Document

## 1. Introduction

Long-term engine service agreements are the commercial backbone of the aircraft-engine aftermarket: an airline pays the maintenance provider a price per engine flight hour, and in exchange the provider assumes the cost and planning burden of shop visits, life-limited parts, engineering directives, and spare coverage for years at a time. Getting these contracts right is a forecasting problem as much as an operational one. The price written into the agreement rests on utilization assumptions — how many hours and cycles each enrolled engine will accumulate — while the provider's exposure rests on predictions of when each engine will next need to come off wing, how severe the operating environment will make each visit, and which airworthiness mandates will fall due before the next planned removal. When reality drifts from those assumptions, the contract must absorb the change: billing trues up against verified utilization, visit forecasts move as cycle consumption is reported, and commercial terms occasionally have to be renegotiated mid-term.

This document specifies the Engine Aftermarket Service Agreements API, the system of record for that entire lifecycle. It governs the registration of operators, engines, and the spare-engine pool; the drafting, activation, enrollment, renegotiation, and expiry of flight-hour service agreements; the monthly submission and finance verification of flight-hour reports; the issuance and settlement of billing statements under an escalating, utilization-banded rate card; the scheduling, forecasting, induction, and completion of shop visits; the iterative drafting and operator approval of visit workscopes under a post-visit life-restoration floor and a per-visit cost cap; parts sourcing across new, repaired, and used serviceable material constrained by contract terms and lead times; spare-engine leasing for aircraft-on-ground coverage; and contract accounting snapshots that recognize revenue on both forward-looking and chronological-actual bases. Every date-sensitive rule in the system is evaluated against a controllable logical clock so that long-horizon contract behavior can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `PlatformAdmin`, `ContractManager`, `Operator`, `ShopPlanner`, and `FinanceController`. A request that arrives without these headers, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is additionally restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN`.

Role identity semantics differ by role and are part of the contract:

- When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` entity; ownership checks on any resource traceable to an operator compare the resource's owning operator to `X-User-ID`. The ownership chain runs through the engine: for engines, and for flight-hour reports and shop visits belonging to an engine, the owning operator is the one referenced by the engine's `operator_id`; for workscopes and spare-engine leases, the owning operator is the operator of the engine that the parent shop visit belongs to. An `Operator` caller whose `X-User-ID` does not match the resolved owning operator is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `PlatformAdmin`, `ContractManager`, `ShopPlanner`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

The `PlatformAdmin` is the MRO provider's platform administrator and alone may register master data (operators, engines, spare engines), issue airworthiness directives, and drive the logical clock. The `ContractManager` owns the commercial contract lifecycle: drafting, activating, renegotiating, amending agreements, enrolling engines, and resolving sourcing escalations with an override. The `Operator` is the airline customer: it submits utilization reports, schedules shop visits, approves or rejects workscopes, and reserves, activates, and returns spare-engine leases. The `ShopPlanner` runs the shop floor: inducting and completing visits, drafting workscope versions, demanding parts, and running the sourcing selector. The `FinanceController` verifies utilization reports, issues and settles billing statements, and appends contract-accounting snapshots. All read endpoints are available to every authenticated role.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every date-sensitive rule in the system — escalation anniversaries, period eligibility, forecast dates, lease windows, directive deadlines, agreement expiry — is evaluated against a single server-side **logical clock**, never against wall-clock time. Before any client advances it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; all downstream date rules then evaluate against the new reading.

Advancing the clock has a system-wide side effect: any agreement still `ACTIVE` whose `end_date` has been reached — that is, whose `end_date` is at or before the new clock reading — transitions automatically from `ACTIVE` to `EXPIRED`, and each such transition increments the agreement's `version` by 1. `EXPIRED` is terminal.

Monthly periods throughout the API (flight-hour reports, billing statements) are expressed as calendar-month strings in `YYYY-MM` format. A report or statement whose `period` is after the current logical-clock month is rejected with `ERR_FUTURE_PERIOD`.

### 2.5. Common Resource Properties

All primary resources (Operators, Engines, Service Agreements, Flight-Hour Reports, Billing Statements, Shop Visits, Workscopes, Part Requisitions, Spare Engines, and Spare Engine Leases) carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-09-01T00:00:00.000Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed on every mutation.
- **`version` (integer):** A system-managed integer that increments by 1 with every modification to the resource, including mutations applied as cascaded side effects of operations on other resources.

Two entity types are immutable, append-only records and carry **only** `id` and `created_at`: the `Directive` and the `RecognitionSnapshot`. Neither has an `updated_at` field nor a `version` field; a directive is never modified after issuance, and a recognition snapshot is a permanent point-in-time computation in an append-only history.

### 2.6. Monetary Precision and Rounding

All monetary values within the system must be handled with specific precision to ensure financial accuracy and prevent floating-point drift.

- **Internal calculations** involving money use decimal arithmetic.
- **Final monetary values** stored on resources — billing line amounts, statement totals, workscope totals, unit costs, lease costs, projected costs, recognized revenue, and loss accruals — are rounded to exactly 2 decimal places using the round-half-up method.
- **Billing statements pin a rounding order:** each line's `line_amount_usd` is rounded to 2 decimal places first, and the statement total is then the exact sum of those rounded lines, with no further rounding applied to the total.
- **Per-flight-hour rates** are carried at 4 decimal places, round half up: the `effective_rate_per_fh_usd` on a billing line has exactly 4 decimal places.
- **Percentage fields** (`recognition_pct` on a recognition snapshot) are carried at 4 decimal places, round half up.
- **API representation:** monetary values in response bodies are standard numbers (not strings) with a maximum of 2 decimal places, and rates/percentages with a maximum of 4. Configuration and price inputs supplied by clients (such as `base_rate_per_fh_usd`, `daily_lease_rate_usd`, `list_price_usd`, and `estimated_cost_usd`) preserve the precision they were submitted with.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and **only** those two; endpoints not listed here do not accept a version field.

- **Amending an agreement** requires the request to carry `expected_agreement_version`, the caller's last observed `version` of the agreement. If another writer has advanced the agreement's `version` since the client last read it — for example, a prior amend or an open-renegotiation has already bumped it — the amend is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's amended terms were drafted against a stale contract baseline.
- **Creating a new workscope version** for a shop visit requires the request to carry `expected_shop_visit_version`, the caller's last observed `version` of the visit. A prior workscope creation legitimately supersedes the previous version and bumps the visit's `version`, so if the visit's current `version` does not match `expected_shop_visit_version` the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

In both cases the rejection is purely a stale-version check on the parent entity's current `version`; the request does not proceed and no state changes.

### 2.8. Validation Order and Error Precedence

When several checks could fail on the same request, the system evaluates them in a fixed priority order and surfaces the **first** failing check's error; later checks are not evaluated. The order, from first to last, is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** The caller's role is permitted on the endpoint and, for `Operator` callers, the ownership chain described in §2.1 resolves to the caller, else `ERR_FORBIDDEN` (HTTP 403).
3. **Existence.** Every identifier in the request path resolves to an existing resource, validated left to right, else the resource-specific `404` error (see §2.9).
4. **Request shape.** Required fields are present (a required string field must not be the empty string), types are valid, enum values are in range, numeric bounds are respected (such as strictly positive quantities, rates, and prices, and non-negative hour and cycle counts), a lease window's `end_date` is strictly after its `start_date`, a report or statement `period` is not after the current logical-clock month, and a directive declares at least one of `compliance_cycles` or `compliance_date`. Generic violations surface as `ERR_INVALID_REQUEST` (HTTP 400); lease-window violations surface as `ERR_INVALID_WINDOW` (HTTP 422); future-period violations surface as `ERR_FUTURE_PERIOD` (HTTP 422).
5. **Uniqueness.** Unique business keys do not collide — `iata_code`, `esn`, `contract_ref`, `spare_serial`, and `directive_ref` are each globally unique; a flight-hour report is unique per engine and `period`; a billing statement is unique per agreement and `period`. Collisions surface as `ERR_DUPLICATE_RESOURCE` (HTTP 409), with report and statement duplicates surfacing as `ERR_DUPLICATE_REPORT` and `ERR_DUPLICATE_STATEMENT` respectively.
6. **State preconditions.** The targeted transition's from-state and related entity-state requirements hold: the agreement is in the required status (`ERR_AGREEMENT_NOT_ACTIVE`, `ERR_AGREEMENT_NOT_IN_RENEGOTIATION`), the engine's enrollment and shop status permit the operation (`ERR_ENGINE_NOT_ENROLLED`, `ERR_ENGINE_ALREADY_ENROLLED`, `ERR_ENGINE_IN_SHOP`), and the visit, workscope, requisition, report, statement, or lease is in a from-state of the requested transition (`ERR_VISIT_NOT_INDUCTED`, `ERR_NO_APPROVED_WORKSCOPE`, `ERR_WORKSCOPE_NOT_SUBMITTED`, `ERR_WORKSCOPE_NOT_APPROVED`, `ERR_ACTIVE_WORKSCOPE_EXISTS`, and the generic `ERR_INVALID_STATE` for transition precondition failures not covered by a more specific error — such as operating on a terminal-state resource, verifying an already-`VERIFIED` report, settling an already-`SETTLED` statement, or activating a lease that is not `RESERVED`). The optimistic-concurrency version match also lives at this tier: a mismatched expected version is rejected with `ERR_STALE_VERSION` (HTTP 412). All other state-tier rejections carry HTTP 409.
7. **Airworthiness compliance gate.** Visit completion enforces a two-step gate evaluated in a pinned order: first, every due mandatory directive applicable to the engine's model must be incorporated into an `APPROVED` workscope of the visit, else `ERR_MANDATORY_DIRECTIVE_OPEN`; only then is the existence of an `APPROVED` workscope checked, else `ERR_NO_APPROVED_WORKSCOPE`.
8. **Temporal resource rules.** A new lease window must not overlap another `RESERVED` or `ACTIVE` lease of the same spare engine under half-open window semantics (`ERR_LEASE_WINDOW_OVERLAP`); lease activation is only permitted while the logical clock is inside the lease window (`ERR_LEASE_NOT_IN_WINDOW`); and the daily induction count must be below the shop's daily induction capacity (`ERR_SHOP_CAPACITY_EXCEEDED`).
9. **Cross-entity referential rules.** An engine cannot be enrolled twice (`ERR_ENGINE_ALREADY_ENROLLED`); visit completion is blocked by requisitions still open (`ERR_OPEN_REQUISITIONS`); a spare engine's model must match the covered visit's engine model (`ERR_MODEL_MISMATCH`, HTTP 422); and sourcing requires at least one eligible class (`ERR_NO_ELIGIBLE_SOURCING_CLASS`).
10. **Fiscal gates.** Workscope approval requires the workscope's `total_cost_usd` to be at or below the agreement's `max_workscope_cost_usd` (`ERR_WORKSCOPE_COST_CAP_EXCEEDED`, HTTP 422), and workscope creation requires the post-visit life restoration to meet the minimum post-visit interval (`ERR_INSUFFICIENT_LIFE_RESTORATION`, HTTP 422).

### 2.9. Nested Resource Resolution

For every request whose path contains resource identifiers, the system validates the existence of each identifier in a strict left-to-right order and rejects immediately with the `404 Not Found` error corresponding to the **first** identifier that does not resolve. Each resource type has its own not-found error: `ERR_OPERATOR_NOT_FOUND`, `ERR_ENGINE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_SHOP_VISIT_NOT_FOUND`, `ERR_WORKSCOPE_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_SPARE_ENGINE_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`. A request that references a missing engine therefore fails with `ERR_ENGINE_NOT_FOUND` before any check on a report, visit, or workscope beneath it is attempted, and only after every identifier resolves do the business rules of §2.8's later tiers run.

### 2.10. The Utilization Band Pricing Model

Flight-hour pricing in this system is built from three multiplicative components, and the same architecture feeds both monthly billing and contract-accounting projections:

- **Base rate.** Each agreement carries a `base_rate_per_fh_usd`, the price per engine flight hour in USD before escalation and utilization adjustment.
- **Escalation.** The agreement's `escalation_pct` (for example, 0.03 for three percent) compounds once per full 12-month period elapsed since the `escalation_anchor_date`. The number of compounding steps for a given statement period is the count of integers k, with k at least 1, such that the date exactly k times 12 months after `escalation_anchor_date` is on or before the last day of that statement period. The escalation factor is one plus `escalation_pct`, raised to the power of that anniversary count; a period that has not yet reached the first anniversary compounds zero times and applies a factor of exactly 1.
- **Utilization band.** Each engine's recent actual utilization is compared against its `assumed_annual_hours` to form a utilization ratio (defined fully in §3.4). A ratio strictly below 0.90 prices the period at a band factor of 0.95; a ratio from 0.90 up to and including 1.10 prices at a band factor of 1.00; a ratio strictly above 1.10 prices at a band factor of 1.08. When an engine has no verified utilization history in the look-back window, the ratio defaults to exactly 1.00 and the standard band applies.

The effective per-flight-hour rate for an engine in a period is the base rate multiplied by the escalation factor multiplied by the band factor, rounded half-up to 4 decimal places.

Separately from the rate card, the system prices shop-visit exposure through **severity-adjusted visit costs**: a base visit cost of 1,200,000 USD is multiplied by a severity factor drawn from the engine's `base_severity_tier` — 1.00 for `BENIGN`, 1.15 for `MODERATE`, and 1.30 for `HARSH`. This same severity-adjusted figure drives both the per-visit `projected_cost_usd` and the lifetime cost projection used in contract accounting.

## 3. Business Logic & Workflows

### 3.1. Registering Operators, Engines, and the Spare Pool

Before any commercial activity, a `PlatformAdmin` registers the master data. An **Operator** record captures the airline's legal `name`, its two-letter `iata_code` (two uppercase letters, unique across all operators), and a `credit_rating` of `A`, `B`, or `C`. The credit grade has one concrete financial consequence: an operator rated `A` has the spare-engine lease deposit waived entirely, while `B` and `C` operators pay it in full (§3.8).

An **Engine** is registered against its owning operator via a payload carrying the `operator_id`, the engine serial number `esn` (unique across all engines), the `engine_model` designation such as CFM56-7B, the `base_severity_tier` of the engine's home operation (`BENIGN`, `MODERATE`, or `HARSH`), and the current `llp_remaining_cycles` — the minimum remaining cycles across the engine's life-limited parts, a non-negative integer. The referenced operator must exist: an `operator_id` that resolves to no registered operator is rejected with `ERR_OPERATOR_NOT_FOUND`. A freshly registered engine starts with `cumulative_flight_hours` and `cumulative_cycles` both at 0, `status` of `IN_SERVICE`, `agreement_id` unset, `enrolled_at` unset, and `projected_next_removal_date` unset, because the removal projection cannot be computed until enrollment supplies the utilization assumptions. The engine model string matters beyond display: directive applicability is an exact string match against it, and a spare engine may only substitute for an engine of the same model.

A **SpareEngine** joins the lease pool with a unique `spare_serial`, the `engine_model` it can substitute for, and a strictly positive `daily_lease_rate_usd`. It begins life `AVAILABLE`.

The `PlatformAdmin` also issues **Directives** — airworthiness directives, service bulletins, and engineering directives — as immutable records. Each directive carries a unique authority reference `directive_ref` (for example AD-2026-0113), a `directive_type` of `AD`, `SB`, or `ED`, the `applicability_model` it applies to, a `mandatory` flag, and the strictly positive `estimated_cost_usd` of incorporating it into a workscope. A directive is bound by cycles, by date, or by both: `compliance_cycles` is a positive-integer cumulative-cycle threshold or null, `compliance_date` is a deadline instant or null, and a directive that leaves both null is rejected with `ERR_INVALID_REQUEST`. Mandatory directives are the ones that cascade into open workscopes and gate visit completion (§3.6).

Registering any of these records colliding with an existing unique key — `iata_code`, `esn`, `spare_serial`, or `directive_ref` — is rejected with `ERR_DUPLICATE_RESOURCE`.

### 3.2. Service Agreements: Drafting, Activation, Enrollment, and Renegotiation

A `ContractManager` drafts a **ServiceAgreement** by supplying the customer-facing `contract_ref` (unique across agreements), the `base_rate_per_fh_usd` (strictly positive), the `escalation_pct` (zero or positive), the `escalation_anchor_date` from which escalation anniversaries are counted, the contract term's `start_date` and `end_date`, the `allowed_sourcing_classes` the contract permits (a non-empty subset of `NEW`, `REPAIRED`, and `USM`), and the per-visit `max_workscope_cost_usd` cap (strictly positive). A new agreement is created in `DRAFT` status with `billed_to_date_usd` at zero and `enrolled_engine_count` at zero.

Activation moves the agreement from `DRAFT` to `ACTIVE` and is permitted only while the logical clock sits inside the contract term — on or after `start_date` and strictly before `end_date` — and only from `DRAFT`; an activation attempt outside the term window or from any other status is rejected with `ERR_INVALID_STATE`. Each activation increments the agreement's `version`.

Enrollment is how engines enter the contract, and it is also the mechanism for fleet mix changes mid-term. A `ContractManager` enrolls an engine into an `ACTIVE` agreement by naming the `engine_id` and capturing the utilization assumptions `assumed_annual_hours` (strictly positive) and `assumed_cycles_per_month` (a positive integer). The agreement must be `ACTIVE` — enrolling against a `DRAFT`, `RENEGOTIATION`, or `EXPIRED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The engine must currently be `IN_SERVICE` and must not already belong to an agreement: an engine whose `agreement_id` is already set is rejected with `ERR_ENGINE_ALREADY_ENROLLED`, and an engine mid-visit in the shop is rejected with `ERR_ENGINE_IN_SHOP`. A successful enrollment stamps the engine's `agreement_id` (permanent thereafter), records both assumptions, sets `enrolled_at` to the logical clock, computes the engine's `projected_next_removal_date` for the first time, and increments the engine's `version`. The agreement's `enrolled_engine_count` always reflects the number of engines whose `agreement_id` points at it.

Renegotiation is a two-step cycle. Opening a renegotiation moves an `ACTIVE` agreement to `RENEGOTIATION` and increments its `version`; while the agreement is in `RENEGOTIATION`, billing issuance and shop-visit induction are blocked — both require an `ACTIVE` agreement and fail with `ERR_AGREEMENT_NOT_ACTIVE`. Closing the round is done by amending: the `ContractManager` supplies `expected_agreement_version` (the OCC guard of §2.7; a mismatch is rejected with `ERR_STALE_VERSION`) plus any subset of the amendable commercial terms — `base_rate_per_fh_usd`, `escalation_pct`, `escalation_anchor_date`, `end_date`, `allowed_sourcing_classes`, and `max_workscope_cost_usd` — which are applied on success. Amending is only possible from `RENEGOTIATION`; an amend attempt against an agreement in any other status is rejected with `ERR_AGREEMENT_NOT_IN_RENEGOTIATION`. A successful amend returns the agreement to `ACTIVE` and increments its `version` again.

The terminal transition is system-driven: when the logical clock reaches or passes an `ACTIVE` agreement's `end_date`, the agreement becomes `EXPIRED` (§2.4). No client operation can expire an agreement, and no transition leaves `EXPIRED`. Throughout the lifecycle, `billed_to_date_usd` keeps a running commercial picture: it is the sum of `provisional_total_usd` over the agreement's `ISSUED` statements plus `final_total_usd` over its `SETTLED` statements, recomputed whenever a statement is issued or settled.

### 3.3. Flight-Hour Reporting and the Verification Cascade

Each calendar month, the `Operator` submits a **FlightHourReport** for an enrolled engine, carrying the `period` in `YYYY-MM` form, the `flight_hours` accumulated in the period (zero or more), the `cycles` accumulated (a non-negative integer), and the `observed_severity` of the dominant route environment (`BENIGN`, `MODERATE`, or `HARSH`). Submission is only meaningful for an engine under contract and on wing: reporting for an engine with no `agreement_id` is rejected with `ERR_ENGINE_NOT_ENROLLED`, and reporting while the engine is `IN_SHOP` is rejected with `ERR_ENGINE_IN_SHOP`. One report exists per engine per period — a second submission for the same `(engine_id, period)` pair is rejected with `ERR_DUPLICATE_REPORT` — and the `period` must not be a future month relative to the logical clock, else `ERR_FUTURE_PERIOD`. A new report is created `SUBMITTED` with `verified_at` unset.

Verification is the finance function that turns raw operator submissions into contractual fact. A `FinanceController` verifies a `SUBMITTED` report, moving it to `VERIFIED` — a terminal state; verifying an already-`VERIFIED` report is rejected with `ERR_INVALID_STATE`. Verification stamps `verified_at` with the logical clock and then fires a broad cascade in a single coherent update:

- The engine's lifetime counters absorb the period: `flight_hours` are added to `cumulative_flight_hours`, and `cycles` are added to `cumulative_cycles`.
- Life-limited-part consumption is debited: `llp_remaining_cycles` is reduced by the report's `cycles`, floored at zero so it can never go negative.
- The engine's `projected_next_removal_date` is recomputed from the new remaining life (the cycle-based projection of §3.5).
- Every `SCHEDULED` shop visit of the engine has its `forecast_induction_date` recomputed. If the new forecast falls **earlier** than the visit's `planned_induction_date`, the planned date is auto-advanced to the forecast date, and every `RESERVED` spare-engine lease of that visit whose half-open window does not contain the new planned induction date is automatically cancelled — the lease transitions from `RESERVED` to `CANCELLED` and its `version` increments by 1.
- The engine's `version` increments by 1 and the report's `version` increments by 1.

Verified reports are the only ones that count toward utilization ratios, final billing, and life consumption; submitted-but-unverified reports still influence provisional billing, as the next subsection describes.

### 3.4. Monthly Billing: Provisional Issuance and Final Settlement

Billing runs per agreement per calendar month. A `FinanceController` issues a **BillingStatement** for an agreement by naming the billing `period` (`YYYY-MM`). The agreement must be `ACTIVE` — issuance against a `DRAFT`, `RENEGOTIATION`, or `EXPIRED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. One statement exists per agreement per period (`ERR_DUPLICATE_STATEMENT` on collision), and the period must not be a future month (`ERR_FUTURE_PERIOD`).

Issuance computes the **PROVISIONAL variant** of the billing calculation. The system considers every engine whose `agreement_id` equals the agreement at the time of the call, iterated in `enrolled_at` ascending order with `created_at` ascending as the tie-break. For each engine it looks up that engine's flight-hour report for the statement period in the provisional input set — reports in either `SUBMITTED` or `VERIFIED` status — so unverified hours are billed at issuance. An engine with no such report contributes no line. Otherwise a line item is produced containing the `engine_id`, the reported `hours`, the `effective_rate_per_fh_usd`, and the `line_amount_usd`, which is the reported flight hours multiplied by the effective rate and rounded half-up to 2 decimal places. The statement's `line_items` array holds these per-engine lines. The statement's `provisional_total_usd` is then the exact sum of those rounded line amounts, with no further rounding of the total, and is fixed at issuance. The statement is created in `ISSUED` status with `final_total_usd` and `adjustment_usd` both unset, and the agreement's `billed_to_date_usd` is recomputed.

The effective rate on each line follows §2.10's model. The utilization ratio for an engine and period is computed over a look-back window: the twelve calendar months ending at the statement period, inclusive of the statement month — formally, every calendar month that is on or before the statement period and strictly after the month twelve months before it. The engine's `VERIFIED` reports whose `period` falls in that window are summed; if there are none, the ratio defaults to exactly 1.00 and the standard band applies. Otherwise the summed hours are annualized by multiplying by 12 and dividing by the number of distinct periods present, and the ratio is that annualized figure divided by the engine's `assumed_annual_hours`. The band factor is then selected: strictly below 0.90 yields 0.95; from 0.90 through 1.10 inclusive yields 1.00; strictly above 1.10 yields 1.08. The line's `effective_rate_per_fh_usd` is `base_rate_per_fh_usd` multiplied by the escalation factor for the period (§2.10) multiplied by the band factor, rounded half-up to 4 decimal places.

Settlement trues the month up. A `FinanceController` settles an `ISSUED` statement — attempting to settle one already `SETTLED` is rejected with `ERR_INVALID_STATE` — which recomputes the line items under the **FINAL variant**: the input set is now `VERIFIED` reports only, so hours that were never verified drop out of the bill. The settlement sets `final_total_usd` to the recomputed total and `adjustment_usd` to the difference between `final_total_usd` and `provisional_total_usd`, transitions the statement to `SETTLED` (terminal), increments the statement's `version` by 1, and recomputes the agreement's `billed_to_date_usd`, which from then on counts this statement by its final rather than provisional total.

### 3.5. Shop Visits: Scheduling, Forecasting, Induction, and Completion

When an engine's life consumption says a removal is coming, the `Operator` schedules a **ShopVisit** for it by supplying a `planned_induction_date`. Scheduling requires the engine to be enrolled in an agreement — otherwise the request is rejected with `ERR_ENGINE_NOT_ENROLLED`. At creation the server immediately computes the visit's forecast. Two independent forecast variants race each other:

- The **cycle-based** forecast derives the date from remaining life: it takes the engine's `llp_remaining_cycles`, divides by the `assumed_cycles_per_month` captured at enrollment, converts months to days at 30 days per month with any fractional day discarded down to a whole day, and adds that many days to the current logical clock.
- The **calendar-based** forecast is insensitive to utilization: it takes the `completion_date` of the engine's most recent `COMPLETED` shop visit — or the engine's `created_at` if the engine has never completed a visit — and adds a fixed interval of 72 months.

The visit's `forecast_induction_date` is the earlier of the two dates, and `forecast_method` records which variant produced it: `CYCLE_BASED` when the cycle-based date is earlier or the two coincide exactly (ties always go to the cycle-based view), otherwise `CALENDAR_BASED`. The same cycle-based formula, evaluated against the logical clock, is what maintains the engine-level `projected_next_removal_date` on enrollment, on every report verification, and on visit completion. The server also sets the visit's `projected_cost_usd` at creation: the 1,200,000 USD base visit cost multiplied by the severity factor for the engine's `base_severity_tier` — 1.00 for `BENIGN`, 1.15 for `MODERATE`, 1.30 for `HARSH`. The visit starts in `SCHEDULED` status with `actual_induction_date` and `completion_date` unset, and it stays forecast-maintained: every report verification for the engine recomputes the forecast and may pull `planned_induction_date` earlier, cancelling out-of-window leases as described in §3.3.

Induction pulls the engine into the shop. A `ShopPlanner` inducts a `SCHEDULED` visit; the engine must be `IN_SERVICE` (inducting while `IN_SHOP` is rejected with `ERR_ENGINE_IN_SHOP`) and its enrolled agreement must be `ACTIVE` — induction is one of the operations blocked during `RENEGOTIATION`, failing with `ERR_AGREEMENT_NOT_ACTIVE`. The shop also enforces an aggregate daily capacity across all visits regardless of agreement or operator: if the number of visits already in `INDUCTED` status whose `actual_induction_date` equals the current logical-clock date has reached 2, the induction is rejected with `ERR_SHOP_CAPACITY_EXCEEDED` — at most 2 engines can be inducted on a single logical-clock day. A successful induction stamps `actual_induction_date` with the logical clock, moves the visit to `INDUCTED`, moves the engine from `IN_SERVICE` to `IN_SHOP`, and increments both the visit's and the engine's `version` by 1.

Completion returns the engine to service and is the most heavily gated transition in the system. A `ShopPlanner` completes an `INDUCTED` visit; completing from any other status fails the state tier with `ERR_INVALID_STATE`. Then the airworthiness compliance gate runs in its pinned order: first, every due mandatory directive applicable to the engine's model must be incorporated into an `APPROVED` workscope of this visit — if any due mandatory directive is missing, completion is rejected with `ERR_MANDATORY_DIRECTIVE_OPEN`; second, an `APPROVED` workscope must exist for the visit at all, else `ERR_NO_APPROVED_WORKSCOPE`. After the gate, the parts check runs: no part requisition belonging to any non-`SUPERSEDED` workscope of the visit may still be open — any requisition still `REQUESTED` or `ESCALATED` blocks completion with `ERR_OPEN_REQUISITIONS`. On success the visit's `completion_date` is stamped with the logical clock, the visit moves to `COMPLETED` (terminal), the engine returns from `IN_SHOP` to `IN_SERVICE`, and life restoration is applied: when an `APPROVED` workscope exists, the engine's `llp_remaining_cycles` becomes the larger of its current value and that workscope's `restores_llp_cycles`, after which `projected_next_removal_date` is recomputed. Completion increments the visit's `version` by 1 and the engine's `version` by 1.

### 3.6. Workscope Determination, Directives, and the Life-Restoration Floor

The **Workscope** is the negotiated content of a shop visit, versioned per visit: each version carries a `scope_version` counter that starts at 1 and increments with every new workscope created for the same visit. A `ShopPlanner` drafts the next version for an `INDUCTED` visit — drafting against a visit in any other status is rejected with `ERR_VISIT_NOT_INDUCTED` — and the request must carry `expected_shop_visit_version` per the OCC rule of §2.7; a stale value is rejected with `ERR_STALE_VERSION`. If the visit's latest workscope version is still `SUBMITTED` (drafted but undecided), a new version may not be layered on top: the attempt is rejected with `ERR_ACTIVE_WORKSCOPE_EXISTS`. A new version is therefore only created when there is no prior version or the prior version is `REJECTED`, `REOPENED`, or `APPROVED`, and creating it supersedes that prior version (below).

The proposer supplies an optional list of `items`, each a work item with an `item_code`, an `item_type` of `MANDATORY_DIRECTIVE`, `LLP_REPLACEMENT`, `MODULE_OVERHAUL`, or `INSPECTION`, an `estimated_cost_usd`, a `restores_cycles` count (a non-negative integer expressing how much life-limited-part life the item restores), and a `directive_ref` that must be null unless the item is a `MANDATORY_DIRECTIVE`. The server then assembles the final item list itself, in a pinned evaluation order that exists because remaining life and mandatory items depend on each other — due directives must be judged against the engine as it arrived, before any restoration is credited:

1. **Due-directive evaluation against pre-visit state.** A directive is due for this visit when it is `mandatory`, its `applicability_model` matches the engine's `engine_model` exactly, and at least one of its bounds is triggered: its `compliance_cycles`, when non-null, is at most the engine's `llp_remaining_cycles` plus a buffer of 18 months' worth of assumed cycles (that is, 18 multiplied by `assumed_cycles_per_month`); or its `compliance_date`, when non-null, is on or before the logical clock plus 18 months.
2. **Mandatory item append.** For every due directive, the server appends one `MANDATORY_DIRECTIVE` item to the proposer-supplied list: the `item_code` and `directive_ref` are set to the directive's `directive_ref`, the `estimated_cost_usd` is taken from the directive, and `restores_cycles` is 0. Appended items are de-duplicated by `directive_ref`, so a directive already proposed by the planner is not doubled.
3. **Post-visit life floor.** Let the restored life be the maximum `restores_cycles` over all items (0 when no item restores anything). The post-visit life in cycles is the larger of that restored value and the engine's current `llp_remaining_cycles`; divided by `assumed_cycles_per_month`, it gives the post-visit interval in months. If that interval is strictly less than 18 months, the workscope creation is rejected with `ERR_INSUFFICIENT_LIFE_RESTORATION` — the visit would not buy enough life to reach the next planned removal window.
4. **Pricing.** The workscope's `total_cost_usd` is the sum of `estimated_cost_usd` over all items, rounded half-up to 2 decimal places, and it is recomputed whenever the item list changes. The `restores_llp_cycles` field carries the maximum-`restores_cycles` figure (0 when none) for use at visit completion.

A fresh workscope is `SUBMITTED` with `decided_at` unset. The `Operator` then decides it. Approval requires the workscope to be `SUBMITTED` (otherwise `ERR_WORKSCOPE_NOT_SUBMITTED`), the visit to be `INDUCTED` (otherwise `ERR_VISIT_NOT_INDUCTED`), and the fiscal cap: `total_cost_usd` must be at or below the agreement's `max_workscope_cost_usd`, else the approval is rejected with `ERR_WORKSCOPE_COST_CAP_EXCEEDED`. Approval stamps `decided_at` with the logical clock, moves the workscope to `APPROVED`, and increments its `version`. Rejection likewise requires `SUBMITTED` (otherwise `ERR_WORKSCOPE_NOT_SUBMITTED`) and moves the workscope to `REJECTED` with `decided_at` stamped and `version` incremented.

Workscopes are living documents in the face of new airworthiness mandates. When a `PlatformAdmin` issues a `mandatory` directive whose `applicability_model` matches the `engine_model` of an engine whose visit is currently `INDUCTED`, and the directive evaluates as due for that visit under step 1 above at issuance, two cascades fire. On a still-`SUBMITTED` workscope of such a visit, the server appends the due `MANDATORY_DIRECTIVE` item (same construction as above) and recomputes `total_cost_usd`, so the undecided draft absorbs the new mandate. On an `APPROVED` workscope of such a visit, the approved baseline is instead protected: the workscope transitions from `APPROVED` to `REOPENED` with its items left untouched, every requisition of that workscope still `REQUESTED` or `ESCALATED` is set to `CANCELLED` (each incrementing its own `version`), and the workscope's `version` increments. The planner is expected to draft a new version that incorporates the mandate.

Version succession is the cleanup mechanism. Creating a newer workscope version for the visit moves the previous version — whether `REJECTED`, `REOPENED`, or `APPROVED` — to the terminal `SUPERSEDED` state, increments its `version`, and cancels every one of its requisitions in `REQUESTED`, `ESCALATED`, or `SOURCED` status. Cancelling a `SOURCED` requisition releases committed money: the visit's `committed_parts_cost_usd` decreases by that requisition's `quantity` multiplied by its `unit_cost_usd`. The creation itself also increments the shop visit's `version` by 1, which is exactly what the OCC guard on the next drafting round observes.

### 3.7. Parts Sourcing and Committed Parts Cost

Once a workscope is `APPROVED`, the `ShopPlanner` demands the parts it calls for. A **PartRequisition** is created against the workscope — recorded on the requisition as its `workscope_id` — with a `part_number`, a strictly positive integer `quantity`, a strictly positive catalog `list_price_usd` per unit, a `requested_class` of `NEW`, `REPAIRED`, or `USM` expressing the operator's sourcing preference, and a `required_by_date` giving the latest acceptable delivery date. Demanding a part on a workscope that is not `APPROVED` is rejected with `ERR_WORKSCOPE_NOT_APPROVED`. A new requisition is `REQUESTED`, with `sourced_class` and `unit_cost_usd` unset until sourcing succeeds.

Sourcing is a deterministic selector run on demand — the `ShopPlanner` runs it in the normal case, and a `ContractManager` runs it when an override is needed. Each sourcing class carries a cost factor applied to the catalog price and a procurement lead time: `NEW` prices at 1.00 of list with a 7-day lead, `REPAIRED` at 0.70 with a 21-day lead, and `USM` at 0.45 with a 3-day lead; the candidate unit cost for a class is the requisition's `list_price_usd` multiplied by the class factor, rounded half-up to 2 decimal places. A class is **eligible** when two conditions both hold: the class appears in the agreement's `allowed_sourcing_classes`, and either an override is being applied or the lead time fits — the `required_by_date` is on or after the logical clock plus that class's lead days. The selector then chooses in a pinned order:

1. If the request carries `override` set to true — permitted only to a `ContractManager` — the selector chooses the cheapest class in `allowed_sourcing_classes` by unit cost, bypassing the lead-time check entirely; the allowed-class list itself is never bypassed.
2. Otherwise, if the `requested_class` is eligible, it is chosen.
3. Otherwise, if any class is eligible, the eligible class with the lowest unit cost is chosen; ties on equal unit cost break by a fixed class priority of `NEW`, then `REPAIRED`, then `USM`.
4. Otherwise no class can serve the demand: the requisition transitions from `REQUESTED` to `ESCALATED`, its `version` increments, and the request is rejected with `ERR_NO_ELIGIBLE_SOURCING_CLASS`.

A successful sourcing — whether from `REQUESTED` or, under override, from `ESCALATED` — sets the requisition's `sourced_class` and `unit_cost_usd`, moves it to `SOURCED`, and increments its `version`. Sourced money becomes committed: the visit's `committed_parts_cost_usd` is the sum of `quantity` multiplied by `unit_cost_usd` over all `SOURCED` requisitions belonging to any non-`SUPERSEDED` workscope of the visit, so it rises as requisitions source and falls back when a supersede cascade releases them (§3.6). Requisitions are never cancelled directly by clients: `CANCELLED` is a terminal state reached only through the workscope cascades — a reopen cancels `REQUESTED` and `ESCALATED` requisitions, while a supersede cancels those plus `SOURCED` ones with the corresponding release of committed cost.

### 3.8. Spare Engine Leasing

A shop visit strands an aircraft without its engine, so the `Operator` can reserve a spare from the pool to cover the aircraft-on-ground window. Reserving a **SpareEngineLease** names the `spare_engine_id`, the `shop_visit_id` whose window it covers, and the lease window: `start_date` inclusive and `end_date` exclusive. The `end_date` must be strictly after the `start_date`, else `ERR_INVALID_WINDOW`. The spare's `engine_model` must match the model of the engine under the covered visit, else `ERR_MODEL_MISMATCH`. And one spare cannot be promised twice for the same time: the new window must not overlap any other `RESERVED` or `ACTIVE` lease of the same spare engine under half-open semantics — two windows that merely touch, one's `end_date` equal to the other's `start_date`, do not overlap — otherwise `ERR_LEASE_WINDOW_OVERLAP`.

Pricing is fixed at reservation. The `lease_cost_usd` is the number of whole calendar days inside the half-open window multiplied by the spare's `daily_lease_rate_usd`, rounded half-up to 2 decimal places. The `deposit_usd` depends on the covered operator's creditworthiness: it is 0 when the operator's `credit_rating` is `A`, and a flat 50,000 USD otherwise. The lease is created `RESERVED`.

Activation and return are operator actions timed by the logical clock. Activating a lease requires it to be `RESERVED` (activation from any other status is rejected with `ERR_INVALID_STATE`), requires the logical clock to sit inside the window — on or after `start_date` and strictly before `end_date`, otherwise `ERR_LEASE_NOT_IN_WINDOW` — requires the covered visit to be `SCHEDULED` or `INDUCTED`, and requires the spare to be `AVAILABLE`. Activation moves the lease to `ACTIVE`, moves the spare engine from `AVAILABLE` to `LEASED`, and increments both resources' `version` by 1. Returning an `ACTIVE` lease moves it to `RETURNED` (terminal), returns the spare from `LEASED` to `AVAILABLE`, and again increments both versions. The fourth lease state, `CANCELLED`, is terminal and is reached only by the forecast cascade of §3.3: when a report verification pulls the visit's `planned_induction_date` earlier and the new date falls outside a `RESERVED` lease's half-open window, that lease is cancelled automatically with its `version` incremented.

### 3.9. Contract Accounting and Revenue Recognition

Long-term agreements are accounted against lifetime projections, and the system lets finance capture that position at any moment: a `FinanceController` appends a **RecognitionSnapshot** to an agreement, and the server recomputes every figure at the logical clock of the call. Snapshots are immutable, append-only records (they carry only `id` and `created_at`, per §2.5), so the list of snapshots over an agreement forms a permanent accounting history.

Each snapshot carries seven computed figures. Two projection horizons are computed first. The **remaining term** is measured in whole calendar months from the clock to the agreement's `end_date` — computed as the difference of the year-and-month indices, floored at zero once the term has passed. The **projected monthly revenue** is the sum over every engine currently enrolled in the agreement of one twelfth of the engine's `assumed_annual_hours` multiplied by the engine's effective per-flight-hour rate computed for the current period under §2.10's model (escalation and utilization band included). The snapshot's `lifetime_revenue_projection_usd` is then the agreement's `billed_to_date_usd` plus the remaining term in months multiplied by that projected monthly revenue.

On the cost side, the snapshot separates actuals from forecasts. `cost_to_date_usd` is the sum of `total_cost_usd` over all `APPROVED` workscopes of `COMPLETED` visits of the agreement's enrolled engines, plus the `lease_cost_usd` of all `RETURNED` leases on those visits — money demonstrably spent. The forward-looking piece forecasts each enrolled engine's future visits: the remaining term in months is multiplied by the engine's `assumed_cycles_per_month` and divided by 8,000 — the life-limited-part reset interval in cycles that each full visit restores — with the quotient rounded up to a whole number of visits. Each forecast visit is priced at the severity-adjusted projection, the 1,200,000 USD base multiplied by the factor for the engine's `base_severity_tier` (1.00 `BENIGN`, 1.15 `MODERATE`, 1.30 `HARSH`). The `lifetime_cost_projection_usd` is `cost_to_date_usd` plus the sum over enrolled engines of their forecast visit counts multiplied by those per-visit projections.

Recognition itself is computed on two bases. The **PROJECTED variant** recognizes revenue in proportion to progress against the lifetime projection: `recognition_pct` is the ratio of `cost_to_date_usd` to `lifetime_cost_projection_usd`, capped at 1, carried at 4 decimal places rounded half-up, and defined as exactly 0 when the cost projection is 0; `recognized_revenue_projected_usd` is that percentage applied to `lifetime_revenue_projection_usd`, rounded half-up to 2 decimal places. The **ACTUAL variant** ignores all forecast state and recognizes only chronological actuals: `recognized_revenue_actual_usd` is the sum of `final_total_usd` over the agreement's `SETTLED` statements, deflated by the fixed target margin of 0.15 — that is, multiplied by 0.85 — and rounded half-up to 2 decimal places.

Finally, the snapshot flags onerous contracts. The projected margin is the difference between `lifetime_revenue_projection_usd` and `lifetime_cost_projection_usd` divided by `lifetime_revenue_projection_usd`, taken as 0 when the revenue projection is 0. When that margin falls strictly below the margin floor of 0.05, the contract is onerous and `onerous_loss_accrual_usd` is the full projected shortfall — `lifetime_cost_projection_usd` minus `lifetime_revenue_projection_usd`, rounded half-up to 2 decimal places; otherwise the accrual is 0.

## 4. Endpoint Definitions

Operations that create a new resource — registering an operator, engine, spare engine, or directive; submitting a report; scheduling a visit; drafting an agreement; issuing a statement; appending a snapshot; drafting a workscope version; demanding a part; reserving a lease — return `201 Created`. Operations that act on an existing resource without creating a new one — clock advancement, activation, renegotiation open, amend, enrollment, verification, settlement, induction, completion, approve, reject, sourcing, lease activation and return — return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; auto-expires agreements whose term has passed | PlatformAdmin |
| POST | `/api/operators` | Register an airline operator | PlatformAdmin |
| POST | `/api/engines` | Register an engine asset for an operator | PlatformAdmin |
| POST | `/api/engines/{id}/flight-hour-reports` | Submit the monthly flight-hour/cycle report for an engine | Operator |
| POST | `/api/engines/{id}/shop-visits` | Schedule a shop visit; server computes the forecast and projected cost | Operator |
| POST | `/api/agreements` | Draft a long-term flight-hour service agreement | ContractManager |
| POST | `/api/agreements/{id}/activate` | Activate a DRAFT agreement | ContractManager |
| POST | `/api/agreements/{id}/open-renegotiation` | Open a renegotiation round; blocks billing and induction until amended | ContractManager |
| POST | `/api/agreements/{id}/amend` | Close a renegotiation by applying amended terms; OCC-guarded | ContractManager |
| POST | `/api/agreements/{id}/enroll` | Enroll an unenrolled in-service engine with utilization assumptions | ContractManager |
| POST | `/api/agreements/{id}/billing-statements` | Issue the PROVISIONAL monthly statement (SUBMITTED + VERIFIED reports) | FinanceController |
| POST | `/api/agreements/{id}/recognition-snapshots` | Append a contract-accounting snapshot (PROJECTED and ACTUAL variants) | FinanceController |
| POST | `/api/flight-hour-reports/{id}/verify` | Verify a submitted report; consumes LLP life and drives the forecast/lease cascade | FinanceController |
| POST | `/api/billing-statements/{id}/settle` | Settle an ISSUED statement with the FINAL variant and record the adjustment | FinanceController |
| POST | `/api/shop-visits/{id}/induct` | Induct a SCHEDULED visit, subject to daily induction capacity | ShopPlanner |
| POST | `/api/shop-visits/{id}/complete` | Complete an INDUCTED visit after the compliance and parts gates | ShopPlanner |
| POST | `/api/shop-visits/{id}/workscopes` | Create the next workscope version; OCC-guarded; supersedes the previous version | ShopPlanner |
| POST | `/api/workscopes/{id}/approve` | Operator approves a SUBMITTED workscope within the cost cap | Operator |
| POST | `/api/workscopes/{id}/reject` | Operator rejects a SUBMITTED workscope | Operator |
| POST | `/api/workscopes/{id}/part-requisitions` | Demand a part for an APPROVED workscope | ShopPlanner |
| POST | `/api/part-requisitions/{id}/source` | Run the sourcing selector; ContractManager may override lead time | ShopPlanner, ContractManager |
| POST | `/api/spare-engines` | Register a spare engine in the lease pool | PlatformAdmin |
| POST | `/api/spare-engine-leases` | Reserve a spare engine for a visit's aircraft-on-ground window | Operator |
| POST | `/api/spare-engine-leases/{id}/activate` | Activate a RESERVED lease inside its window | Operator |
| POST | `/api/spare-engine-leases/{id}/return` | Return an ACTIVE lease; the spare becomes AVAILABLE again | Operator |
| POST | `/api/directives` | Issue an engineering directive; mandatory ones cascade into open workscopes | PlatformAdmin |
| GET | `/api/engines/{id}` | Read one engine, including `projected_next_removal_date` | Any |
| GET | `/api/engines` | List engines; optional filters `operator_id` and `agreement_id` | Any |
| GET | `/api/engines/{id}/shop-visits` | List shop visits of an engine | Any |
| GET | `/api/engines/{id}/flight-hour-reports` | List flight-hour reports of an engine | Any |
| GET | `/api/agreements/{id}` | Read one agreement, including `billed_to_date_usd` and `enrolled_engine_count` | Any |
| GET | `/api/agreements/{id}/billing-statements` | List billing statements of an agreement | Any |
| GET | `/api/agreements/{id}/recognition-snapshots` | List recognition snapshots of an agreement (append-only history) | Any |
| GET | `/api/shop-visits/{id}` | Read one shop visit, including forecast and committed parts cost | Any |
| GET | `/api/shop-visits/{id}/workscopes` | List workscope versions of a visit | Any |
| GET | `/api/shop-visits/{id}/leases` | List spare engine leases covering a visit | Any |
| GET | `/api/workscopes/{id}` | Read one workscope version, including `total_cost_usd` and `restores_llp_cycles` | Any |
| GET | `/api/workscopes/{id}/part-requisitions` | List part requisitions of a workscope | Any |
| GET | `/api/spare-engines/{id}` | Read one spare engine | Any |
| GET | `/api/spare-engines/{id}/leases` | List leases of a spare engine | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this table is the canonical identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OPERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_ENGINE_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SHOP_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_WORKSCOPE_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_SPARE_ENGINE_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_FUTURE_PERIOD` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_DUPLICATE_STATEMENT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_RENEGOTIATION` | 409 Conflict |
| `ERR_ENGINE_NOT_ENROLLED` | 409 Conflict |
| `ERR_ENGINE_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_ENGINE_IN_SHOP` | 409 Conflict |
| `ERR_VISIT_NOT_INDUCTED` | 409 Conflict |
| `ERR_NO_APPROVED_WORKSCOPE` | 409 Conflict |
| `ERR_WORKSCOPE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_WORKSCOPE_NOT_APPROVED` | 409 Conflict |
| `ERR_ACTIVE_WORKSCOPE_EXISTS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MANDATORY_DIRECTIVE_OPEN` | 409 Conflict |
| `ERR_LEASE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_LEASE_NOT_IN_WINDOW` | 409 Conflict |
| `ERR_SHOP_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_OPEN_REQUISITIONS` | 409 Conflict |
| `ERR_MODEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_SOURCING_CLASS` | 409 Conflict |
| `ERR_WORKSCOPE_COST_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LIFE_RESTORATION` | 422 Unprocessable Entity |
