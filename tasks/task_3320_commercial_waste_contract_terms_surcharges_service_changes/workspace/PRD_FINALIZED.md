# Commercial Waste Contracts API — Product Requirements Document

## 1. Introduction

Commercial waste hauling runs on long-lived service agreements whose economics shift constantly beneath the signatures: fuel indexes move, environmental and administrative surcharges are repriced, customers resize containers and re-tune pickup frequencies, and competitors periodically try to poach the account with a better monthly number. This document specifies the Commercial Waste Contracts API, a system that administers the full commercial lifecycle of those agreements — multi-year terms with automatic renewal, cancellation notice windows and liquidated damages on early exit, percentage-based surcharge schedules, contamination and overweight fees captured at the curb with photo evidence and a formal dispute channel, a contractual right-of-first-refusal mechanism that lets the incumbent match a competing offer, service-failure credits for missed pickups, and separately priced roll-off and temporary container orders that sit outside any ongoing contract.

The API serves four constituencies. A platform operations team maintains the customer book and the surcharge schedule. Waste-management operations managers own contracts, rate adjustment notices, service-change approvals, dispute resolution, match decisions, cancellations, and roll-off fulfillment. Commercial customers initiate service changes, competing offers, cancellations, service credits, disputes, and roll-off orders against their own accounts. Hauler field agents record the outcome of every collection attempt. Because so many rules are time-dependent — renewal, rate-notice application, termination finalization, dispute and credit filing windows — the system is driven by a single logical clock rather than wall-clock time, and every temporal rule in this document is evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `PlatformAdmin`, `OpsManager`, `Customer`, and `HaulerAgent`. A request missing either header, or presenting an `X-User-Role` value that is not one of these four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `OpsManager`, or `HaulerAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

The `PlatformAdmin` role is the platform operator: it manages customers and surcharge configurations, drives the logical clock, and has read access to every resource. The `OpsManager` role runs waste-management operations: it creates and activates contracts, adds service lines, files and cancels rate notices, approves/rejects/applies service changes, matches or declines competing offers, approves/denies cancellations and waives liquidated damages, resolves disputes, and marks roll-off orders delivered or completed; it also has read access to every resource. The `Customer` role files service-change requests, competing offers, cancellation requests, service credits, and pickup disputes, withdraws its own pending requests, creates and cancels roll-off orders, and may read any resource. The `HaulerAgent` role records collection events and may list and read pickup events.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

All temporal rules in this system — renewal, notice application, termination finalization, filing windows, effective-date gates — are evaluated against a single server-side logical clock, never against wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the logical clock to it.

Every clock advance runs three sweeps, in this exact order. First, the auto-renewal sweep: every contract in `ACTIVE` status whose `end_date` is on or before the new clock time renews (see §3.2). Second, the rate-notice application sweep: every rate adjustment notice still `SCHEDULED` whose `effective_date` is on or before the new clock time is applied (see §3.3). Third, the termination-finalization sweep: every contract in `TERMINATION_PENDING` whose approved cancellation's `requested_end_date` is on or before the new clock time moves to `TERMINATED` (see §3.8).

### 2.5. Common Resource Properties

Every primary resource — customers, contracts, service lines, pickup events, surcharge configurations, rate adjustment notices, service change requests, competing offers, cancellation requests, service credits, and roll-off orders — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the logical-clock time at which the resource was created (per §2.4, never the wall clock).
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed to the current logical-clock time on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every modification to the resource.

Ledger entries are the exception: a `LedgerEntry` is immutable once written and carries only `id` and `created_at`; it has no `updated_at` and no `version`.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integers of cents. Wherever a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent. Rounding order is pinned wherever multi-component totals are involved: each component is rounded individually before any summation, and summing unrounded values and rounding once at the end is forbidden. Two calculations deliberately use a different rounding rule and say so explicitly where they are defined: the liquidated-damages month count rounds any partial month up to a full month, the roll-off overage tonnage rounds any fractional excess ton up to a whole ton, and the service-credit amount takes the floor of its product.

### 2.7. The Customer Credit Ledger

Each customer carries a server-maintained ledger balance, `credit_balance_cents`, which starts at 0 when the customer is created and is never accepted from client input — any input value for it is ignored. The balance is a derived figure with immediate consistency, recomputed on every mutation of its sources: it equals the sum of `credit_cents` over every service credit in `ACTIVE` status whose service line belongs to a contract of this customer, minus the sum of `ld_total_cents` over every cancellation request with `ld_status` equal to `ASSESSED` on contracts of this customer. The balance may go negative, which represents net liquidated-damages exposure exceeding accrued service credits. Filing a service credit raises the balance by that credit's amount; approving an untimely cancellation lowers it by the assessed damages; waiving assessed damages raises it back by the waived amount; and a dispute resolved in the customer's favor raises it by cancelling the associated credit (see §3.6 and §3.7).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent contract: matching a competing offer, and applying an approved service change. Each of these requests must carry `expected_contract_version`, a non-optional input field holding the `version` of the contract as the client last observed it. If that value does not match the contract's current `version` — because a prior match, a rate-notice application, a service-change application, an activation, a renewal, or any other contract mutation has advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-observe the contract's pricing before re-pricing it. No other endpoint accepts a version field; on all other writes the server applies the mutation without an OCC check.

### 2.9. Surcharge Configuration and Active-Window Resolution

Surcharge behavior is governed by `SurchargeConfig` resources, each carrying an `effective_from` timestamp that opens its active window. The active configuration at any moment T is the one with the latest `effective_from` that is on or before T. No two surcharge configurations may share the same `effective_from`; an attempt to create one with a colliding timestamp is rejected with `ERR_DUPLICATE_PENDING` (HTTP 409). The configuration active at the relevant moment supplies the fuel, environmental, and administrative surcharge percentages used in monthly invoicing, the flat contamination and overweight fees stamped onto pickup events, and the credit percentage of base used when a service credit is computed. Each configuration declares a `fuel_mode` of either `FIXED` or `INDEXED`; a `FIXED` configuration must supply `fuel_fixed_pct`, and an `INDEXED` configuration must supply both `fuel_index_base` and `fuel_index_current`, while `environmental_pct`, `admin_pct`, `contamination_fee_cents`, and `overweight_fee_cents` are required on every configuration. `credit_pct_of_base` — the credit percentage of base used when a service credit is computed (see §3.6) — is optional; when omitted it is stored and serialized as null.

### 2.10. Nested Resource Retrieval and Validation Ordering

When an endpoint path or payload references multiple resources — a contract id plus a service-line foreign key, a service-line id plus a pickup-event id — the server validates the existence of every referenced resource in left-to-right order, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Validations on any request are evaluated in a fixed priority order so that failures surface deterministically: first authentication (missing or malformed headers, `ERR_UNAUTHENTICATED`); second role authorization (`ERR_FORBIDDEN`); third resource existence (`ERR_NOT_FOUND`); fourth request shape — required fields present, well-typed values, enums within their declared sets, numeric ranges respected (`ERR_INVALID_REQUEST`, HTTP 400); fifth state admissibility of the target resource (`ERR_INVALID_STATE`, HTTP 409); sixth the optimistic-concurrency version match on the two OCC-guarded writes (`ERR_STALE_VERSION`); seventh business time-window rules (`ERR_WINDOW_EXPIRED`, HTTP 422); eighth uniqueness and pending-duplicate rules (`ERR_DUPLICATE_PENDING`); ninth business referential rules such as the right-of-first-refusal gate (`ERR_ROFR_NOT_ENABLED`, HTTP 422); and tenth fiscal sanity of amounts (`ERR_INVALID_AMOUNT`, HTTP 422). A request that violates more than one rule is rejected with the error belonging to the earliest applicable priority in this ordering.

## 3. Business Logic & Workflows

### 3.1. Customers and the Book of Business

A `PlatformAdmin` onboards a commercial account by creating a customer with its `legal_name` and `billing_email`; both are required. The new customer's `credit_balance_cents` is initialized to 0 by the server. From that point on the balance moves only through the ledger cascade described in §2.7 — clients never write it directly.

### 3.2. Contract Lifecycle: Drafting, Activation, Renewal, Reinstatement

An `OpsManager` drafts a contract against a customer by supplying the `customer_id`, a `start_date` (ISO 8601 UTC, required), and a `term_months` length in whole months (required, and it must be at least 1). Four optional terms carry explicit defaults: `renewal_term_months` defaults to 12 and controls how many months each automatic renewal adds; `cancellation_notice_days` defaults to 60 and defines the notice window used in liquidated-damages evaluation; `rofr_enabled` defaults to false and switches the right-of-first-refusal clause on or off; and `rofr_window_days` defaults to 15 and sets how long the incumbent has to exercise that right after a competing offer lands. A new contract is born in `DRAFT` status with `current_term_index` equal to 1. Its `end_date` is computed by the server as the `start_date` plus `term_months` whole months on the same day-of-month; any client-supplied `end_date` is ignored. The contract's `base_monthly_total_cents` is a computed figure, always equal to the sum of `base_rate_cents` across all of the contract's service lines; it starts at 0, is recomputed on every line creation, every rate-notice application, every service-change application, and every right-of-first-refusal match, and any client-supplied value for it is ignored.

Service lines are attached to a contract while it is `DRAFT` or `ACTIVE`. Each line declares a `container_size` — one of `CY_2`, `CY_4`, `CY_6`, or `CY_8` cubic yards — a `frequency_per_week` of scheduled pickups per week (an integer from 1 to 6 inclusive; any value outside that range is rejected with `ERR_INVALID_REQUEST`), and a monthly `base_rate_cents` charge in cents (required, at least 0). Adding a line recomputes the contract's `base_monthly_total_cents` and increments the contract's `version` by 1.

Activation moves a contract from `DRAFT` to `ACTIVE`. An `OpsManager` may activate only when two preconditions both hold: the contract has at least one service line, and its `start_date` is on or before the logical clock. A contract without lines, or one whose start date still lies in the future, is rejected with `ERR_INVALID_STATE`. Activation increments the contract's `version` by 1.

Once active, a contract renews automatically: on every advance of the logical clock, any contract in `ACTIVE` whose `end_date` is on or before the new clock time extends its `end_date` by `renewal_term_months` months, increments `current_term_index` by 1, and increments its `version` by 1. A contract may also be reinstated: reinstatement moves a contract from `TERMINATED` back to `ACTIVE` and is permitted only while the logical clock is strictly before the contract's `end_date`; it increments the contract's `version` by 1.

### 3.3. Rate Adjustment Notices

An `OpsManager` files a rate adjustment notice against a contract with a `reason` — one of `CPI`, `FUEL_INDEX`, or `COST_RECOVERY` — a fractional `pct_increase` (for example 0.05 means a 5 percent increase; it must be strictly greater than 0, and a non-positive value is rejected with `ERR_INVALID_AMOUNT`), and an `effective_date`. The `effective_date` must lie strictly after the logical clock at filing time; a date at or before now is rejected with `ERR_WINDOW_EXPIRED`. A new notice is born `SCHEDULED`.

On every clock advance, each notice still `SCHEDULED` whose `effective_date` is on or before the new clock time is applied: for every service line on the contract, the line's `base_rate_cents` is replaced by its previous value multiplied by one plus the `pct_increase`, rounded half-up to a whole cent. The contract's `base_monthly_total_cents` is then recomputed as the sum of the new line rates, a `LedgerEntry` with `source` equal to `RATE_NOTICE` is written capturing the change, and the contract's `version` increments by 1. Application moves the notice from `SCHEDULED` to `APPLIED`. If the contract happens to have a pending service change request whose quote was computed at the old base, that quote is deliberately not re-quoted when the notice applies — the stored `quoted_new_rate_cents` stays as originally quoted, and the final price is instead repriced from the new base when the change is applied (see §3.4).

A scheduled notice may be cancelled while the logical clock is still strictly before its `effective_date`; cancellation at or after the effective date is rejected with `ERR_WINDOW_EXPIRED`. Cancellation moves the notice from `SCHEDULED` to `CANCELLED`. Notices are also cancelled by cascade: approving a contract termination cancels every `SCHEDULED` notice on that contract (see §3.8). Both `APPLIED` and `CANCELLED` are terminal.

### 3.4. Service Change Requests: Quoting, Approval, Repricing at Application

A `Customer` requests a container or frequency change against one of its service lines by supplying the `service_line_id`, a `new_container_size` (one of `CY_2`, `CY_4`, `CY_6`, `CY_8`; it may equal the current size when only the frequency changes), a `new_frequency_per_week` (an integer from 1 to 6 inclusive; it may equal the current frequency when only the size changes), and an `effective_date` that must lie strictly after the logical clock, with an at-or-before-now date rejected with `ERR_WINDOW_EXPIRED`. The request is born `PENDING`. At creation the server captures the line's current `base_rate_cents` into the request's `old_rate_cents` and computes a `quoted_new_rate_cents` using the quoting rule below against the line's current values.

The quoting rule works per-pickup. Divide the line's `base_rate_cents` by its current `frequency_per_week` to obtain a per-pickup weekly unit (kept as an unrounded intermediate). When the `new_frequency_per_week` is greater than the current frequency — an upgrade — multiply the unit by the `new_frequency_per_week` and then by a premium multiplier of 1.10, rounding half-up to a whole cent. When the `new_frequency_per_week` is less than or equal to the current frequency — a downgrade or frequency-neutral change — multiply the unit by the `new_frequency_per_week` and then by a discount multiplier of 0.95, rounding half-up to a whole cent. Container size alone never changes the price; only the frequency ratio and the direction of the change matter, and the apparently circular dependency between base rate and new price is resolved by the pinned order of computing the per-pickup unit first and then scaling it.

An `OpsManager` approves a `PENDING` request only when the owning contract is `ACTIVE` and no other request on the same service line is already `APPROVED`; a second approved change on one line is rejected with `ERR_DUPLICATE_PENDING`, and approval against a non-active contract is rejected with `ERR_INVALID_STATE`. Approval moves the request from `PENDING` to `APPROVED`. An `OpsManager` may instead reject a `PENDING` request, moving it to `REJECTED`. The filing `Customer` may withdraw a `PENDING` request, moving it to `CANCELLED`.

Application is the money step and is guarded by optimistic concurrency. An `OpsManager` applies an `APPROVED` request once the logical clock is on or after the request's `effective_date`; attempting application while the clock is still strictly before that date violates the transition's precondition and is rejected with `ERR_INVALID_STATE`. The request must carry `expected_contract_version` matching the contract's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.8, because a rate-notice application or a right-of-first-refusal match in between changes the base rate the final price is computed from, so the price must be re-observed before applying. On application the final price is recomputed with the same quoting rule, but reading the line's `base_rate_cents` as it stands at apply time — an intervening rate notice changes the result — and stored in `final_applied_rate_cents` (which is null until the request is applied). The line's `base_rate_cents` is set to that final rate, its `container_size` becomes the `new_container_size`, and its `frequency_per_week` becomes the `new_frequency_per_week`. The contract's `base_monthly_total_cents` is recomputed, a `LedgerEntry` with `source` equal to `SERVICE_CHANGE` is written, and the contract's `version` increments by 1. The request moves from `APPROVED` to `APPLIED`. Termination of the contract cancels every `PENDING` or `APPROVED` request on its lines by cascade, moving each to `CANCELLED`; `APPLIED`, `REJECTED`, and `CANCELLED` are all terminal.

### 3.5. Collection Events: Fees at the Curb and the Dispute Channel

A `HaulerAgent` records each collection attempt as a pickup event carrying the `service_line_id`, the `occurred_date` of the attempt as a calendar date in `YYYY-MM-DD` form (required), an `outcome`, and a `photo_evidence_url`. The `outcome` is one of `COMPLETED`, `MISSED`, `CONTAMINATED`, `OVERWEIGHT`, or `CONTAMINATED_OVERWEIGHT`. Photo evidence is mandatory whenever the outcome involves contamination or overweight — that is, for `CONTAMINATED`, `OVERWEIGHT`, and `CONTAMINATED_OVERWEIGHT` — and omitting `photo_evidence_url` on those outcomes is rejected with `ERR_INVALID_REQUEST`; for `COMPLETED` and `MISSED` the photo field is optional.

Fees are stamped onto the event at recording time from the surcharge configuration active at the `occurred_date` (per the active-window rule in §2.9). When the outcome includes contamination, the event's `contamination_fee_cents` equals the active configuration's `contamination_fee_cents`; otherwise it is 0. When the outcome includes overweight, the event's `overweight_fee_cents` equals the active configuration's `overweight_fee_cents`; otherwise it is 0. Every event is born with `dispute_status` equal to `NONE` and `appeal_count` equal to 0.

A `Customer` may dispute an event whose outcome is `CONTAMINATED`, `OVERWEIGHT`, or `CONTAMINATED_OVERWEIGHT`, moving its `dispute_status` from `NONE` to `DISPUTED`. Disputing a `COMPLETED` or `MISSED` event is rejected with `ERR_INVALID_STATE`. The dispute must be filed while the logical clock is on or before the `occurred_date` plus 30 days; filing after that 30-day window is rejected with `ERR_WINDOW_EXPIRED`. An `OpsManager` then resolves the dispute by supplying a `resolution` of either `UPHELD` or `CREDITED`. A resolution of `UPHELD` moves the event from `DISPUTED` to `RESOLVED_UPHELD` and keeps the fees in place. The customer gets exactly one appeal: from `RESOLVED_UPHELD` the customer may dispute again, but only while `appeal_count` is still 0; that re-dispute returns the event to `DISPUTED` and sets `appeal_count` to 1, after which no further disputes of that event are possible (a further attempt is rejected with `ERR_INVALID_STATE`). A resolution of `CREDITED` moves the event from `DISPUTED` to `RESOLVED_CREDITED`, which is terminal, and triggers the credit cascade: any service credit in `ACTIVE` status whose `pickup_event_id` is this event is cancelled — its `status` becomes `CANCELLED` — and the customer's `credit_balance_cents` is recomputed accordingly, rising by that credit's `credit_cents` because the event's fees have been refunded.

### 3.6. Missed-Pickup Service Credits

When a collection is missed, the affected `Customer` files a service credit supplying the `service_line_id` and the `pickup_event_id` of the missed event. The referenced event must have outcome `MISSED` and must belong to the same service line named in the filing; a credit filed against a non-missed event or a mismatched line is rejected with `ERR_INVALID_STATE`. At most one credit may exist per pickup event; a second filing against the same event is rejected with `ERR_DUPLICATE_PENDING`. Timing is enforced through the credit filing window: the server stamps `filed_at` with the logical-clock time of filing, and the filing is accepted only while `filed_at` is on or before the event's `occurred_date` plus 14 days; filing after that 14-day window is rejected with `ERR_WINDOW_EXPIRED`.

The credit amount is server-computed and any client-supplied value is ignored: `credit_cents` equals the floor of the line's `base_rate_cents` multiplied by the credit percentage of base, `credit_pct_of_base`, in effect under the surcharge configuration active at filing; if no configuration is active at filing, or the active configuration carries no `credit_pct_of_base`, `credit_cents` is 0. A new credit is born `ACTIVE`, and its creation immediately raises the customer's `credit_balance_cents` by `credit_cents` per §2.7. A credit moves to `CANCELLED` only by the dispute cascade described in §3.5 — when the source event's dispute resolves `RESOLVED_CREDITED` — and `CANCELLED` is terminal.

### 3.7. The Monthly Invoice Breakdown

A computed read returns a contract's current monthly invoice breakdown with seven integer-cent components: `base_cents`, `fuel_cents`, `env_cents`, `admin_cents`, `fees_cents`, `credits_cents`, and `total_cents`. The `base_cents` is the contract's `base_monthly_total_cents`. The fuel surcharge depends on the active configuration's `fuel_mode`: when the mode is `FIXED`, the fuel percentage is simply the configuration's `fuel_fixed_pct` regardless of any index values; when the mode is `INDEXED`, the fuel percentage is the amount by which `fuel_index_current` exceeds `fuel_index_base`, floored at zero, divided by `fuel_index_base` — a current index at or below the base yields a zero fuel surcharge and the percentage is never negative. The `fuel_cents` is the base multiplied by that fuel percentage, rounded half-up to a whole cent. The `env_cents` is the base multiplied by the active configuration's `environmental_pct`, rounded half-up to a whole cent. The `admin_cents` is the base multiplied by the active configuration's `admin_pct`, rounded half-up to a whole cent. The `fees_cents` is the sum of `contamination_fee_cents` plus `overweight_fee_cents` over every pickup event on the contract's lines whose `occurred_date` falls inside the trailing 30-day window from 30 days before the logical clock up to and including the clock time. The `credits_cents` is the sum of `credit_cents` over every `ACTIVE` service credit on the contract's lines. The `total_cents` is the base plus fuel plus environmental plus administrative plus fees, minus credits. Per §2.6, each surcharge component is rounded individually before the summation; summing unrounded components and rounding the total is forbidden.

### 3.8. Cancellation, Liquidated Damages, and Termination

A `Customer` files a cancellation request against a contract with the `contract_id` and a `requested_end_date`; the requested date must lie strictly after the logical clock, and a date at or before now is rejected with `ERR_INVALID_REQUEST`. The request is born `PENDING`. At filing, the server computes two derived fields. The `timely` flag is true exactly when the `requested_end_date` is on or before the contract's `end_date` minus `cancellation_notice_days` days; a requested date later than that threshold is untimely. The `months_remaining` is 0 when the filing is timely; otherwise it is the number of calendar months from the `requested_end_date` to the contract's `end_date` with any partial month rounded up to a full month — both dates are day-aligned, so for example a span from 2027-07-04 to 2027-09-01 is one whole month plus 28 days and counts as 2. The month count must never be derived from a prorated daily fraction.

An `OpsManager` may deny a `PENDING` request, moving it to `DENIED`, and the filing `Customer` may withdraw a `PENDING` request while the logical clock is on or before the `requested_end_date`, moving it to `WITHDRAWN`; withdrawal after the requested end date violates the time gate and is rejected. Approval is the consequential path and is permitted only while the owning contract is `ACTIVE` and the request is `PENDING`; approving against a contract in any other status, or against a request already decided, is rejected with `ERR_INVALID_STATE`.

Approval forks on the `timely` flag, and both branches run the same shutdown cascade on the contract: every `SCHEDULED` rate adjustment notice on the contract moves to `CANCELLED`, every `PENDING` or `APPROVED` service change request on the contract's lines moves to `CANCELLED`, and every `SUBMITTED` competing offer on the contract moves to `VOID`.

On the timely branch — where `timely` is true and therefore `ld_total_cents` is 0 — the contract moves directly from `ACTIVE` to `TERMINATED` and no damages are assessed.

On the untimely branch the contract moves from `ACTIVE` to `TERMINATION_PENDING`, and liquidated damages are assessed. The `ld_base_cents` is the contract's `base_monthly_total_cents` as it stands at approval time. The `ld_total_cents` is the `ld_base_cents` multiplied by `months_remaining` multiplied by one half (0.5), rounded half-up to a whole cent; when the filing is timely the total is 0. The evaluation order is pinned: timeliness first, then months remaining, then the damage total. Assessing damages sets the request's `ld_status` from its initial `NONE` to `ASSESSED` and immediately debits the customer's `credit_balance_cents` by `ld_total_cents` per §2.7. Thereafter, on every clock advance, a contract in `TERMINATION_PENDING` whose approved cancellation's `requested_end_date` is on or before the new clock time moves to `TERMINATED`, incrementing the contract's `version` by 1; `TERMINATED` is terminal for the contract (short of reinstatement per §3.2).

Assessed damages may later be forgiven: an `OpsManager` waiving the damages moves `ld_status` from `ASSESSED` to `WAIVED` and immediately credits the customer's `credit_balance_cents` back by the waived `ld_total_cents`.

### 3.9. Competing Offers and the Right of First Refusal

When a contract carries the right-of-first-refusal clause (`rofr_enabled` true), a `Customer` may submit a competing offer against it with the `contract_id`, a `competitor_monthly_cents` total monthly offer in cents (required, and strictly greater than 0; a non-positive value is rejected with `ERR_INVALID_AMOUNT`), and an `evidence_doc_url` referencing the competing offer document (required). Submitting against a contract whose `rofr_enabled` is false is rejected with `ERR_ROFR_NOT_ENABLED`. At most one offer may be `SUBMITTED` on a contract at a time; a second submission while one is still pending is rejected with `ERR_DUPLICATE_PENDING`. A new offer is born `SUBMITTED`.

An `OpsManager` exercises the incumbent's right by matching a `SUBMITTED` offer. Matching requires three preconditions: the logical clock must be on or before the offer's `created_at` plus the contract's `rofr_window_days` days; no other offer on the same contract may be `SUBMITTED`; and the contract must be `ACTIVE`. Matching is also guarded by optimistic concurrency: the request must carry `expected_contract_version` matching the contract's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.8, because a prior match, rate-notice application, or service-change application has legitimately re-priced the contract and the writer's view of `base_monthly_total_cents` is stale.

The match price is the competitor's total minus an undercut of 500 cents, floored at zero: the matched rate is the greater of 0 and `competitor_monthly_cents` minus 500. The matched rate is then allocated across the contract's lines proportionally. Each line's new `base_rate_cents` is its current `base_rate_cents` multiplied by the matched rate and divided by the contract's pre-match `base_monthly_total_cents`, rounded half-up to a whole cent. Lines are processed in order of `base_rate_cents` descending with ties broken by `created_at` ascending, and any rounding remainder — the matched rate minus the sum of the per-line results — is added to the first line in that order, so the new line rates sum to the matched rate exactly. The contract's `base_monthly_total_cents` is then set to the matched rate, a `LedgerEntry` with `source` equal to `ROFR_MATCH` is written, the contract's `version` increments by 1, and the offer moves from `SUBMITTED` to `MATCHED`.

Declining a `SUBMITTED` offer moves it to `NOT_MATCHED`, leaving the contract's pricing untouched. Termination of the contract voids every `SUBMITTED` offer by cascade, moving each to `VOID`. `MATCHED`, `NOT_MATCHED`, and `VOID` are all terminal.

### 3.10. Roll-Off and Temporary Orders

Roll-off and temporary service is priced entirely independently of any contract. A `Customer` places an order with its `customer_id`, a roll-off `container_size` — one of `YD_10`, `YD_20`, `YD_30`, or `YD_40` — a requested `delivery_date`, a `rental_days` length in days (an integer from 1 to 30 inclusive; values outside that range are rejected with `ERR_INVALID_REQUEST`), an optional `included_tons` tonnage allowance that defaults to 2.0 when omitted, and three required price components: a flat `delivery_fee_cents`, a per-day `daily_rental_cents`, and an `overage_ton_cents` rate charged per ton (or part thereof) above the included allowance. A new order is born `RESERVED` with `total_cents` equal to 0 until completion.

An `OpsManager` marks the container delivered once the logical clock is on or after the `delivery_date`, moving the order from `RESERVED` to `DELIVERED`; a delivery attempt before the delivery date is rejected with `ERR_INVALID_STATE`. Completion requires the recorded `actual_tons`; completing without it is rejected with `ERR_INVALID_REQUEST`. On completion the order's `total_cents` is computed: the rental charge is `daily_rental_cents` multiplied by `rental_days`; the billable overage is the greater of 0 and the difference `actual_tons` minus `included_tons` rounded up to a whole ton — an `actual_tons` exactly equal to `included_tons` yields zero overage, overage is charged strictly above the included allowance, and any fractional excess rounds up via ceiling rather than half-up rounding; the overage charge is those billable tons multiplied by `overage_ton_cents`; and the total is the `delivery_fee_cents` plus the rental charge plus the overage charge. Completion moves the order from `DELIVERED` to `COMPLETED`. The placing `Customer` may cancel a `RESERVED` order while the logical clock is strictly before the `delivery_date`, moving it to `CANCELLED`; cancelling at or after the delivery date is rejected. `COMPLETED` and `CANCELLED` are terminal.

### 3.11. The Contract Ledger

Every repricing of a contract leaves an audit trail. A `LedgerEntry` records the `contract_id`, the `effective_date` on which the rate change takes effect, the `old_base_monthly_cents` (the contract's `base_monthly_total_cents` before the change), the `new_base_monthly_cents` (the same figure after the change), and a `source` naming the cause — one of `RATE_NOTICE`, `SERVICE_CHANGE`, or `ROFR_MATCH`. Entries are written by exactly the three events those sources name: a rate-notice application, a service-change application, and a right-of-first-refusal match. Ledger entries are immutable once written (§2.5) and are listed in `created_at` ascending order, either for one contract or across contracts with an optional `contract_id` filter.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new resource — a customer, contract, service line, pickup event, surcharge configuration, rate notice, service change request, competing offer, cancellation request, service credit, or roll-off order — return `201 Created`. Operations that modify an existing resource, perform a state transition, or perform a computed read return `200 OK`. List endpoints accept `limit` and `offset` per §2.3; several also accept the optional filters noted in §3 (`customer_id`, `status`, `service_line_id`, `outcome`, `contract_id`, `pickup_event_id`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; runs the renewal, rate-notice, and termination sweeps in that order | PlatformAdmin |
| POST | `/api/customers` | Create a customer | PlatformAdmin |
| GET | `/api/customers` | List customers with pagination | PlatformAdmin, OpsManager |
| GET | `/api/customers/{id}` | Get one customer including computed `credit_balance_cents` | PlatformAdmin, OpsManager |
| POST | `/api/contracts` | Create a contract in `DRAFT` status | OpsManager |
| GET | `/api/contracts` | List contracts, optionally filtered by `customer_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/contracts/{id}` | Get one contract | PlatformAdmin, OpsManager, Customer |
| POST | `/api/contracts/{id}/activate` | Activate a `DRAFT` contract (requires at least one service line and `start_date` on or before now) | OpsManager |
| POST | `/api/contracts/{id}/reinstate` | Reinstate a `TERMINATED` contract while now is before `end_date` | OpsManager |
| POST | `/api/contracts/{id}/service-lines` | Add a service line to a `DRAFT` or `ACTIVE` contract | OpsManager |
| GET | `/api/contracts/{id}/service-lines` | List service lines of a contract | PlatformAdmin, OpsManager, Customer |
| GET | `/api/service-lines/{id}` | Get one service line | PlatformAdmin, OpsManager, Customer |
| GET | `/api/contracts/{id}/monthly-invoice` | Computed monthly invoice breakdown per §3.7 | PlatformAdmin, OpsManager, Customer |
| GET | `/api/contracts/{id}/ledger-entries` | List ledger entries of a contract, `created_at` ascending | PlatformAdmin, OpsManager, Customer |
| GET | `/api/ledger-entries` | List ledger entries, optionally filtered by `contract_id` | PlatformAdmin, OpsManager, Customer |
| POST | `/api/pickup-events` | Record a collection event; stamps contamination/overweight fees from the active configuration | HaulerAgent |
| GET | `/api/pickup-events` | List pickup events, optionally filtered by `service_line_id` or `outcome` | PlatformAdmin, OpsManager, Customer, HaulerAgent |
| GET | `/api/pickup-events/{id}` | Get one pickup event | PlatformAdmin, OpsManager, Customer, HaulerAgent |
| POST | `/api/pickup-events/{id}/dispute` | Dispute a contaminated/overweight event within 30 days; one re-dispute allowed from `RESOLVED_UPHELD` | Customer |
| POST | `/api/pickup-events/{id}/resolve-dispute` | Resolve a dispute as `UPHELD` or `CREDITED` (crediting cancels the event's active credit) | OpsManager |
| POST | `/api/surcharge-configs` | Create a surcharge configuration; `effective_from` must be unique | PlatformAdmin |
| GET | `/api/surcharge-configs` | List surcharge configurations ordered by `effective_from` ascending | PlatformAdmin, OpsManager |
| POST | `/api/rate-notices` | File a rate adjustment notice; `effective_date` must be strictly after now | OpsManager |
| GET | `/api/rate-notices` | List rate notices, optionally filtered by `contract_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/rate-notices/{id}` | Get one rate adjustment notice | PlatformAdmin, OpsManager, Customer |
| POST | `/api/rate-notices/{id}/cancel` | Cancel a `SCHEDULED` notice before its `effective_date` | OpsManager |
| POST | `/api/service-change-requests` | Request a container/frequency change; server computes `quoted_new_rate_cents` | Customer |
| GET | `/api/service-change-requests` | List service change requests, optionally filtered by `service_line_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/service-change-requests/{id}` | Get one service change request | PlatformAdmin, OpsManager, Customer |
| POST | `/api/service-changes/{id}/approve` | Approve a `PENDING` request; at most one `APPROVED` per line; contract must be `ACTIVE` | OpsManager |
| POST | `/api/service-changes/{id}/reject` | Reject a `PENDING` request | OpsManager |
| POST | `/api/service-changes/{id}/apply` | Apply an `APPROVED` request at/after `effective_date`; reprices from the line's current rate (OCC-guarded) | OpsManager |
| POST | `/api/service-changes/{id}/withdraw` | Withdraw a `PENDING` request | Customer |
| POST | `/api/competing-offers` | Submit a competing offer against a `rofr_enabled` contract; at most one `SUBMITTED` per contract | Customer |
| GET | `/api/competing-offers` | List competing offers, optionally filtered by `contract_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/competing-offers/{id}` | Get one competing offer | PlatformAdmin, OpsManager, Customer |
| POST | `/api/competing-offers/{id}/match` | Match within `rofr_window_days` of offer creation; reprices all lines per §3.9 (OCC-guarded) | OpsManager |
| POST | `/api/competing-offers/{id}/decline-match` | Decline to match a `SUBMITTED` offer | OpsManager |
| POST | `/api/cancellation-requests` | File a cancellation request; server computes `timely` and `months_remaining` | Customer |
| GET | `/api/cancellation-requests` | List cancellation requests, optionally filtered by `contract_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/cancellation-requests/{id}` | Get one cancellation request | PlatformAdmin, OpsManager, Customer |
| POST | `/api/cancellation-requests/{id}/approve` | Approve a `PENDING` cancellation; untimely path assesses liquidated damages and cascades, timely path terminates immediately | OpsManager |
| POST | `/api/cancellation-requests/{id}/deny` | Deny a `PENDING` cancellation request | OpsManager |
| POST | `/api/cancellation-requests/{id}/withdraw` | Withdraw a `PENDING` cancellation at/before `requested_end_date` | Customer |
| POST | `/api/cancellation-requests/{id}/waive-ld` | Waive assessed liquidated damages (`ASSESSED` to `WAIVED`); customer balance credited back | OpsManager |
| POST | `/api/service-credits` | File a missed-pickup credit; event must be `MISSED` on the same line, filed within 14 days; one credit per event | Customer |
| GET | `/api/service-credits` | List service credits, optionally filtered by `service_line_id`, `pickup_event_id`, or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/service-credits/{id}` | Get one service credit | PlatformAdmin, OpsManager, Customer |
| POST | `/api/rolloff-orders` | Create a roll-off/temporary order, priced independently of any contract | Customer |
| GET | `/api/rolloff-orders` | List roll-off orders, optionally filtered by `customer_id` or `status` | PlatformAdmin, OpsManager, Customer |
| GET | `/api/rolloff-orders/{id}` | Get one roll-off order | PlatformAdmin, OpsManager, Customer |
| POST | `/api/rolloff-orders/{id}/deliver` | Mark delivery at/after `delivery_date` | OpsManager |
| POST | `/api/rolloff-orders/{id}/complete` | Complete the rental with `actual_tons`; computes `total_cents` per §3.10 | OpsManager |
| POST | `/api/rolloff-orders/{id}/cancel` | Cancel a `RESERVED` order before `delivery_date` | Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_WINDOW_EXPIRED` | 422 |
| `ERR_DUPLICATE_PENDING` | 409 |
| `ERR_ROFR_NOT_ENABLED` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
