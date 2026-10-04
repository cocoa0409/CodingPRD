# Tool Fleet Subscription API — Product Requirements Document

## 1. Introduction

Contractors increasingly prefer to operate their power-tool fleets as a subscribed service rather than as owned capital: for a monthly per-unit rate they receive tools, repairs with turnaround commitments, loaner units so work is never interrupted, theft coverage with defined replacement terms, and the freedom to grow or shrink the fleet as project volume changes. This document specifies the API for a tool fleet management subscription and jobsite service platform that administers those fleet agreements end to end — from rate-card definition and agreement activation, through jobsite deployment, usage tracking, repair logistics, and theft claims, to consumable supply, on-site engineering support, and end-of-term settlement.

The platform serves two organizations at once. On the provider side, operations administrators, service coordinators, claims adjusters, and field engineers run the fleet, the repair pipeline, and the claims desk. On the contractor side, account managers and jobsite supervisors size the fleet, move assets between jobsites, record usage, report thefts, order consumables, and request engineering visits. Because a single agreement can be repriced mid-cycle while a theft claim, a repair ticket, and an end-of-term election are all in flight, the system pins down precise billing formulas, state machines, optimistic-concurrency rules, and segregation-of-duties checks; this document is the authoritative source for all of them.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `FleetAdmin` — provider-side operations administrator: accounts, rate cards, catalog, agreement lifecycle, theft verification, consumable approval, the loaner registry, and the logical clock.
- `ContractorManager` — contractor-side account manager.
- `JobsiteSupervisor` — contractor-side field supervisor.
- `ServiceCoordinator` — provider-side repair dispatcher who advances repair tickets and dispatches loaners.
- `ClaimsAdjuster` — provider-side claims adjudicator who decides verified theft claims.
- `FieldEngineer` — provider-side field engineer who reviews and documents anchor-design and firestop support cases.

Identity semantics differ by role. When `X-User-Role` is `ContractorManager`, `X-User-ID` is the `id` of the `ContractorAccount` the manager acts for; ownership checks on any resource that references a `ContractorAccount` compare the resource's foreign-key field to `X-User-ID`. The same rule applies when `X-User-Role` is `JobsiteSupervisor`: `X-User-ID` is the `id` of the `ContractorAccount` whose jobsites the supervisor runs, and ownership checks compare resource account references to that value. When `X-User-Role` is `FleetAdmin`, `ServiceCoordinator`, `ClaimsAdjuster`, or `FieldEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `verified_by` on a `TheftClaim` or as `approved_by_engineer_id` on a `SupportCase`) but does not compare it to any entity's `id` — except where a business rule explicitly demands it, such as the theft-claim segregation-of-duties check in §3.7.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending unless a more specific ordering is stated for a particular report. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through any collection.

### 2.4. Resource Identity and Common Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Unless an entity is explicitly exempted below, it also carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version` integer that starts at its initial value on creation and increments by exactly 1 on every mutation of that resource. Two entity kinds are exempt: `UsageEvent` and `EndOfTermSettlement` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Certain identifiers are minted by the server rather than supplied by the caller: an agreement's `agreement_number`, an asset's `serial_number` (unique within its tool model) and `tag_code` (an RFID tag code).

### 2.5. The Logical Clock and the Calendar Month

All time-dependent behavior in the platform — billing cycles, service-level windows, election windows, expiry sweeps, utilization reporting — reads from a single logical clock, never from wall-clock time. At startup the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `FleetAdmin` advances the clock through an admin-only test-driving capability that sets the current instant to a supplied `to_iso8601` value; the capability answers with the resulting `current_utc`.

Advancing the clock fires two sweeps. First, the theft-claim expiry sweep: any claim still in `REPORTED` whose 48-hour police-report window has passed moves to `EXPIRED`. Second, the month-boundary sweep: when the clock crosses into a new calendar month, full monthly billing runs for every agreement in `ACTIVE`, and every asset's `utilization_minutes_current_month` resets to 0. "The current calendar month" is always defined by the logical clock, and several rules below — usage-event acceptance, utilization reporting — depend on it.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Where a percentage is applied (theft depreciation, deductibles, buyout pricing), the result is rounded half-up to whole cents at the step where the percentage is applied. Where a utilization percentage is reported, it is rounded half-up to two decimal places. Where proration applies, a single floor to whole cents is taken after proration and nowhere else. Each calculation in §3 states its own rounding order explicitly; the order is part of the contract.

### 2.7. Optimistic Concurrency Control on Fleet Agreements

Two agreement write operations are guarded by optimistic concurrency: adjusting the fleet, and electing an end-of-term option. Each of these requests must carry `expected_agreement_version`, a non-optional field holding the agreement `version` the client last observed. If the submitted value does not match the agreement's current `version` — because another writer has advanced the agreement since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). For adjust-fleet this prevents repricing against a superseded fleet composition; for end-of-term election it prevents a provisional settlement being frozen from a fleet snapshot the client never saw. Endpoints not named here do not take a version field.

### 2.8. Validation Order

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then request-body shape (`ERR_VALIDATION`), then path existence and parentage (`ERR_NOT_FOUND`), then optimistic-concurrency staleness (`ERR_STALE_VERSION`), then state-machine legality (`ERR_INVALID_STATE`), then segregation of duties (`ERR_DUTY_SEGREGATION`), then time windows (`ERR_WINDOW_EXPIRED`), then structural and capacity constraints (`ERR_CAPACITY_EXCEEDED`, `ERR_WINDOW_OVERLAP`, `ERR_LOANER_POOL_EMPTY`, `ERR_AGREEMENT_HAS_OPEN_CLAIMS`, `ERR_RETURN_INCOMPLETE`), then the application-approval gate (`ERR_APPLICATION_APPROVAL_REQUIRED`), then credit checks (`ERR_CREDIT_LIMIT_EXCEEDED`), and finally uniqueness (`ERR_DUPLICATE`). A request failing an earlier check never reports a later one.

### 2.9. Nested Paths and Cross-Account Scoping

Endpoints that address a resource nested under an account or an agreement validate path identifiers from left to right: each id must exist, and each child must belong to the embedding parent named to its left. A violation anywhere in the chain is reported as `ERR_NOT_FOUND` (HTTP 404). References that cross account boundaries are deliberately hidden the same way — for example, deploying an asset to a jobsite owned by a different account yields `ERR_NOT_FOUND`, not an authorization error, so the existence of other tenants' resources is never disclosed.

## 3. Business Logic & Workflows

### 3.1. Contractor Accounts and the Credit Ledger

A `FleetAdmin` onboards a contractor by creating an account with the legal `company_name`, the US employer identifier `tax_id` (unique across all accounts), and an approved `credit_limit_cents`. New accounts are born `ACTIVE` with `outstanding_balance_cents` at 0; a duplicate `tax_id` is rejected with `ERR_DUPLICATE`. The outstanding balance is a running ledger: monthly fleet billings, approved consumable order totals, and theft deductibles add to it, while payments and SLA breach credits reduce it, and it is never allowed to go below 0.

Credit discipline is enforced at three points. A `FleetAdmin` may suspend an account only while its `outstanding_balance_cents` exceeds its `credit_limit_cents`; the attempt is otherwise rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. Suspension cascades: every agreement of the account that is `ACTIVE` moves to `SUSPENDED`, and each cascaded agreement's `version` increments by 1. While an agreement is `SUSPENDED`, repair tickets on its assets that sit in `OPENED`, `PICKUP_SCHEDULED`, `IN_SHOP`, `LOANER_DISPATCHED`, or `QUALITY_CHECK` cannot advance. Reinstatement is the mirror image: a `FleetAdmin` may reinstate a `SUSPENDED` account only once `outstanding_balance_cents` is at most `credit_limit_cents` (again `ERR_CREDIT_LIMIT_EXCEEDED` otherwise), and reinstatement cascades every `SUSPENDED` agreement of the account back to `ACTIVE`, incrementing each such agreement's `version` by 1.

The contractor pays down the ledger through payments: a `ContractorManager` records a payment by supplying `amount_cents`, which is subtracted from `outstanding_balance_cents` with the result floored at 0.

### 3.2. Rate Cards and the Tool Catalog

Pricing is governed by rate cards. A `FleetAdmin` creates a rate card with a unique `code`, the `tool_category` it governs (one of `DRILL`, `SAW`, `BREAKER`, `MEASURING`, `ANCHORING`), and a three-tier price schedule: `base_monthly_rate_cents` applies per unit below the tier-2 threshold, `tier2_threshold` is the unit count at which tier 2 begins (inclusive), `tier2_monthly_rate_cents` is the per-unit rate for tier-2 units, `tier3_threshold` and `tier3_monthly_rate_cents` play the same role for tier 3, and `min_monthly_fee_cents` is the per-category minimum monthly fee. Each card is valid over a closed interval from `effective_from` through `effective_to`, both bounds included; `effective_to` must be strictly later than `effective_from` (else `ERR_VALIDATION`). A new card whose closed interval overlaps the closed interval of an existing `ACTIVE` card of the same `tool_category` is rejected with `ERR_WINDOW_OVERLAP` — this guarantee is what makes rate-card selection during billing unambiguous. A rate card's `status` is `ACTIVE` on creation.

The catalog is a set of tool models. A `FleetAdmin` registers each model with a unique `model_code`, a `category` from the same five-value enumeration, the `replacement_value_cents` used for theft and buyout pricing, and a `weight_class` of `LIGHT` or `HEAVY` that drives repair turnaround commitments and breach credits. Duplicate codes — a repeated rate-card `code`, `model_code`, loaner `serial_number`, or consumable `sku` — are all rejected with `ERR_DUPLICATE`.

### 3.3. Fleet Agreements: Setup, Activation, and Monthly Billing

A `FleetAdmin` drafts an agreement for an account by supplying `term_months` (the term length in whole months), a `start_date`, and an initial `end_of_term_option` of `BUYOUT`, `RENEWAL`, or `RETURN`. The server mints the `agreement_number`, links the agreement to its owning account through `account_id`, computes `end_date` as `start_date` plus `term_months` months, and opens the agreement in `DRAFT`. The agreement also maintains three derived figures: `fleet_size_target`, the count of its assets in `REGISTERED`, `DEPLOYED`, `IN_TRANSIT`, or `IN_REPAIR`; `billed_this_month_cents`, the most recently committed monthly billing (0 before the first billing); and `theft_claim_count`, the number of theft claims on its assets in `REPORTED`, `POLICE_VERIFIED`, or `APPROVED`.

Activation moves a `DRAFT` agreement to `ACTIVE` and is performed by a `FleetAdmin`. Three preconditions apply: the owning account must be `ACTIVE`; at least one asset must have been added (so `fleet_size_target` is at least 1); and `start_date` must not be earlier than the logical clock's current date. Activation runs the first monthly billing in its prorated variant, commits the result to `billed_this_month_cents`, adds the billed amount to the account's `outstanding_balance_cents`, and increments the agreement's `version` by 1.

Monthly fleet billing runs on three triggers: activation, every successful fleet adjustment, and the month-boundary sweep. The billable input set is the agreement's assets in `REGISTERED`, `DEPLOYED`, `IN_TRANSIT`, or `IN_REPAIR` — assets that are `LOST` or `RETIRED` are excluded. For each tool category present among those assets, the billing date selects the rate card whose `status` is `ACTIVE` and whose closed effective interval contains that date; the overlap-prevention rule of §3.2 guarantees at most one such card. With `n` the billable unit count in the category, the tier split is: tier-1 units are the smaller of `n` and one less than the card's `tier2_threshold`; tier-2 units exist only when `n` has reached the `tier2_threshold`, and then number the smaller of (`n` minus `tier2_threshold` plus one) and the width of the tier-2 band (`tier3_threshold` minus `tier2_threshold`); tier-3 units exist only when `n` has reached the `tier3_threshold`, and then number `n` minus `tier3_threshold` plus one. The category charge is tier-1 units at the base rate plus tier-2 units at the tier-2 rate plus tier-3 units at the tier-3 rate, raised to at least the card's `min_monthly_fee_cents`. The subtotal is the sum of category charges across categories. On activation and fleet adjustment only — never on the sweep — the subtotal is prorated: the proration factor is the count of calendar days from the logical-clock date through month end, both endpoints included, divided by the number of days in the month; the prorated subtotal is floored once to whole cents. The evaluation order is pinned: tier split, then per-category minimum fee, then summation, then proration, then the single floor. The result becomes `billed_this_month_cents` and is added to the account's `outstanding_balance_cents`. The sweep variant uses a proration factor of exactly 1 — the full month is billed — and additionally resets every asset's `utilization_minutes_current_month` to 0.

### 3.4. Sizing the Fleet: Additions and Returns

A `ContractorManager` resizes an agreement by adjusting its fleet, an operation allowed while the agreement is in `DRAFT` or `ACTIVE`. The call carries `expected_agreement_version` for optimistic concurrency (§2.7), plus `add_tool_model_ids` — a list of catalog model ids in which duplicates are allowed, each entry creating one new asset — and `return_asset_ids`, a list of existing assets to hand back. Each added model id produces a new asset in `REGISTERED` with a server-minted `serial_number` and `tag_code`, linked to the chosen `tool_model_id`. Each returned asset must currently be `REGISTERED`; attempting to return an asset that is `DEPLOYED`, `IN_TRANSIT`, or `IN_REPAIR` is rejected with `ERR_INVALID_STATE`. Accepted returns move the asset from `REGISTERED` to `RETIRED`. When the agreement is `ACTIVE`, a successful adjustment reprices it under the prorated billing variant of §3.3 and adds the billed amount to the account's `outstanding_balance_cents`. Every successful adjustment increments the agreement's `version` by 1.

### 3.5. Jobsites, Deployment, Transfers, and Usage

A `ContractorManager` registers each jobsite under the account with a `name`, a street `address`, a `capacity_assets` ceiling on simultaneously deployed assets, and a `geofence_radius_m` used for location reporting. A new jobsite's `deployed_asset_count` starts at 0 and is maintained by the platform as the count of its assets in `DEPLOYED`.

Field movement is driven by a `JobsiteSupervisor`. Deploying a `REGISTERED` asset to a jobsite requires the owning agreement to be `ACTIVE` (otherwise `ERR_INVALID_STATE`), the target jobsite — named by the submitted `jobsite_id` — to belong to the same account as the agreement (cross-account targets are hidden as `ERR_NOT_FOUND`), and the target's `deployed_asset_count` to be below its `capacity_assets` — a full jobsite rejects the deploy with `ERR_CAPACITY_EXCEEDED`. A successful deploy moves the asset to `DEPLOYED`, records the jobsite in `current_jobsite_id`, stamps `commissioned_on` if the asset has never been deployed before (this first-deployment timestamp later anchors theft depreciation), and raises the jobsite's `deployed_asset_count` by 1.

Moving an asset between jobsites is a two-step transfer with a compensating path. Initiating a transfer on a `DEPLOYED` asset requires the same agreement-`ACTIVE`, same-account, and target-capacity preconditions as a deploy (with `ERR_CAPACITY_EXCEEDED` when the target is full); it moves the asset to `IN_TRANSIT`, decrements the origin jobsite's `deployed_asset_count` by 1, clears `current_jobsite_id`, and records the destination in `pending_jobsite_id` by way of the submitted `target_jobsite_id`. Confirming arrival moves the asset back to `DEPLOYED` at the pending site: `current_jobsite_id` takes the value of `pending_jobsite_id`, `pending_jobsite_id` is cleared, and the target jobsite's `deployed_asset_count` rises by 1. Cancelling the transfer instead returns the asset to `DEPLOYED` at its origin: `current_jobsite_id` is restored to the origin, `pending_jobsite_id` is cleared, and the origin jobsite's `deployed_asset_count` rises by 1, compensating the earlier decrement. A supervisor can also check a `DEPLOYED` asset back into the depot, returning it to `REGISTERED`: `current_jobsite_id` is cleared and the jobsite's `deployed_asset_count` falls by 1.

While an asset is `DEPLOYED`, the supervisor records usage by submitting `started_at` and `ended_at`; `ended_at` must be strictly after `started_at` (else `ERR_VALIDATION`), and both timestamps must lie within the logical clock's current calendar month. The recorded `minutes` are the whole-minute floor of the elapsed time, and the asset's `utilization_minutes_current_month` accumulates them until the month-boundary sweep resets it to 0. Usage events, like settlements, carry no `updated_at` or `version`.

Utilization is reported per agreement. The elapsed-days basis is the day-of-month of the logical-clock date (16 on the 16th). Each billable asset's utilization is its `utilization_minutes_current_month` divided by the product of elapsed days and a 480-minute workday, expressed as a percentage and clamped to the range 0 through 100; the report value is the arithmetic mean over the agreement's billable assets (the same status filter as billing), rounded half-up to two decimal places, with `asset_count` reporting how many billable assets contributed. An agreement with no billable assets reports a `utilization_pct` of 0.00. The report takes an optional `mode` query parameter: omitted or `ACTUAL` uses recorded minutes only, while `PROJECTED` scales the actual figure by the ratio of days in the month to elapsed days, extrapolating to month end — the clamp is applied after scaling, so identical inputs yield a higher percentage mid-month. The response carries `utilization_pct`, the echoed `mode`, and `asset_count`.

### 3.6. Repair Service and the Loaner Pool

Opening a repair ticket is a `JobsiteSupervisor` action on a `DEPLOYED` asset, with `loaner_requested` declaring whether a loaner is wanted. The asset moves from `DEPLOYED` to `IN_REPAIR`, the ticket is created in `OPENED` with `opened_at` stamped from the logical clock, the origin jobsite's `deployed_asset_count` falls by 1, and the asset retains its `current_jobsite_id` so it can go home after repair. The ticket's `promised_return_by` is computed from the model's `weight_class`: `opened_at` plus 3 days for `LIGHT`, plus 5 days for `HEAVY`.

From there a `ServiceCoordinator` advances the ticket, and every advancement requires the asset's agreement to be `ACTIVE` (a `SUSPENDED` agreement freezes its tickets in place with `ERR_INVALID_STATE`). Scheduling pickup moves `OPENED` to `PICKUP_SCHEDULED`; receiving the unit moves `PICKUP_SCHEDULED` to `IN_SHOP`. From `IN_SHOP` the coordinator may dispatch a loaner — permitted only when `loaner_requested` is true (else `ERR_INVALID_STATE`) — which allocates from the loaner pool: eligible units are those in `AVAILABLE` whose `tool_model_id` equals the model of the asset under repair, ranked oldest first by `created_at` (creation timestamps are unique per row, so no further tie-break applies). An empty eligible pool is rejected with `ERR_LOANER_POOL_EMPTY` (HTTP 409) and the ticket remains `IN_SHOP`. A successful dispatch moves the ticket to `LOANER_DISPATCHED`, moves the chosen unit from `AVAILABLE` to `DISPATCHED`, and cross-links the two: the unit's `assigned_ticket_id` and the ticket's `loaner_unit_id` are both set. Completing the repair moves the ticket from `IN_SHOP` — or from `LOANER_DISPATCHED` — to `QUALITY_CHECK`.

Closing the ticket (from `QUALITY_CHECK` to `CLOSED`) is the settlement point of the repair pipeline, and several things happen in one call. `closed_at` is stamped from the logical clock. The SLA breach credit is computed: the raw lateness is the time from `promised_return_by` to `closed_at`; a breach exists only when the ticket closed strictly after the promised instant, and then the breach length in hours is rounded up to whole breach days; the credit is the breach days multiplied by the daily credit — 2500 cents per day for `LIGHT`, 9000 cents per day for `HEAVY` — capped at 50000 cents, with the ceiling applied last (round-up to whole days first, then multiply, then cap). The result is stored in `sla_breach_credit_cents`, which is immutable once set, and any positive credit reduces the account's `outstanding_balance_cents`, floored at 0. If a loaner was dispatched, the unit cascades through two hops within the same call — `DISPATCHED` to `RETURNED` and then immediately `RETURNED` to `AVAILABLE` — with `assigned_ticket_id` and the ticket's `loaner_unit_id` both cleared. The repaired asset returns from `IN_REPAIR` to `DEPLOYED` at the jobsite recorded in its `current_jobsite_id`, and that jobsite's `deployed_asset_count` rises by 1.

A supervisor who is unsatisfied with a repair may reopen a closed ticket, subject to two gates: the logical clock must be no later than 14 days after `closed_at` (the boundary is inclusive; a later attempt is rejected with `ERR_WINDOW_EXPIRED`), and the ticket's `reopen_count` must still be below the hard cap of 2 (a ticket already reopened twice rejects with `ERR_CAPACITY_EXCEEDED`). Reopening moves the ticket to `REOPENED`, moves the asset from `DEPLOYED` back to `IN_REPAIR` with its jobsite's `deployed_asset_count` falling by 1, and raises `reopen_count` by 1; the previously granted `sla_breach_credit_cents` is left untouched. When the reopened unit is received again, the `REOPENED` leg into `IN_SHOP` recomputes `promised_return_by` from that receive timestamp, opening a fresh SLA window. The loaner fleet itself is administered by a `FleetAdmin`, who registers units with a `tool_model_id` and a unique `serial_number` (born `AVAILABLE`) and may decommission an `AVAILABLE` unit, moving it to `DECOMMISSIONED`.

### 3.7. Theft Claims: Reporting, Verification, and Adjudication

When a deployed tool disappears, a `JobsiteSupervisor` reports the theft on the asset. The claim is created in `REPORTED`, linked to the affected unit through `asset_id`, with `reported_at` stamped from the logical clock, and the agreement's `theft_claim_count` rises by 1. The asset itself remains `DEPLOYED` while the claim is investigated.

Verification is a `FleetAdmin` duty: the administrator records the `police_report_number` and the `police_report_filed_at` timestamp, which must fall no later than 48 hours after `reported_at` — the boundary is inclusive, and a report filed after that window is rejected with `ERR_WINDOW_EXPIRED`. Successful verification moves the claim to `POLICE_VERIFIED` and records the acting administrator's identifier in `verified_by`. A claim that is still `REPORTED` when the logical clock passes the 48-hour mark is swept to `EXPIRED`, the asset remains `DEPLOYED`, and the agreement's `theft_claim_count` is decremented.

Adjudication belongs to a `ClaimsAdjuster`, under a segregation-of-duties rule: the deciding adjuster's `X-User-ID` must differ from the claim's `verified_by`; the verifier deciding their own claim is rejected with `ERR_DUTY_SEGREGATION`. The adjuster submits a `decision` of `APPROVE` or `DENY`. A denial moves the claim to `DENIED`, leaves the asset `DEPLOYED`, and decrements the agreement's `theft_claim_count`. An approval moves the claim to `APPROVED` and prices the loss in a pinned order. First, the asset's age in whole months is the floor of the days between its `commissioned_on` and the claim's `reported_at`, divided by 30. Second, the depreciated value is the model's `replacement_value_cents` scaled by the age band — 100 percent when the asset is at most 12 months old, 70 percent from month 13 through month 36, 40 percent beyond 36 months — rounded half-up to whole cents. Third, the `deductible_cents` is 10 percent of the depreciated value, rounded half-up to whole cents, then clamped: raised to at least 50000 cents and lowered to at most 250000 cents. Fourth, the `approved_replacement_value_cents` is the depreciated value minus the deductible, further limited so that the running total of approved replacement values on the same agreement — summed over already-`APPROVED` claims in chronological order by `reported_at`, ties broken by `created_at` — never exceeds the 1000000-cent coverage cap; the result is floored at 0. Approval also cascades to the asset, which moves from `DEPLOYED` to `LOST`: its jobsite's `deployed_asset_count` falls by 1 and its `current_jobsite_id` is cleared. The deductible is added to the account's `outstanding_balance_cents`.

An open claim blocks the end of the agreement: electing an end-of-term option is rejected with `ERR_AGREEMENT_HAS_OPEN_CLAIMS` while any claim on the agreement's assets is in `REPORTED` or `POLICE_VERIFIED`.

### 3.8. Consumables, Application Approval, and On-Site Engineering

The catalog extends beyond tools to consumables. A `FleetAdmin` creates each consumable product with a unique `sku`, a `name`, a `unit_price_cents` list price, a `pack_size` (units per pack), and a `requires_application_approval` flag that is true for anchors and fasteners whose use demands a documented anchor-design review.

A `ContractorManager` drafts a consumable order as a set of `lines`, each line pairing a `product_id` with a `quantity_units`. Order totals are computed per line and then summed: each line's pack count is its `quantity_units` divided by the product's `pack_size` rounded up to a whole pack, the line total is that pack count times `pack_size` times `unit_price_cents` in integer arithmetic, and `total_cents` is the sum of the line totals. Merging quantities across lines of the same product and rounding once is forbidden, because two under-filled lines of one product would round to fewer packs together than apart. The total is computed when the order is created and recomputed when it is submitted.

Submitting a draft order is a `ContractorManager` action with three preconditions: the `lines` must be non-empty (else `ERR_VALIDATION`); the account must be `ACTIVE` (else `ERR_INVALID_STATE`); and every line whose product carries `requires_application_approval` must be covered by a `DOCUMENTED` support case of kind `ANCHOR_DESIGN` on the same account — a missing coverage is rejected with `ERR_APPLICATION_APPROVAL_REQUIRED` (HTTP 422). A successful submit moves the order to `SUBMITTED` and stamps `submitted_at` from the logical clock. A `FleetAdmin` then decides the order: approval moves it to `APPROVED` but only while the order's `total_cents` plus the account's `outstanding_balance_cents` does not exceed the account's `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`), and on approval the total is added to the outstanding balance; rejection moves it to `REJECTED`. An approved order is finally moved to `FULFILLED` by a `FleetAdmin`.

Engineering support cases open the door to application approval. A `ContractorManager` opens a case with a `kind` of `ANCHOR_DESIGN` or `FIRESTOP`, the `jobsite_id` to be visited, and a `scheduled_for` start time; the case occupies the half-open two-hour window beginning at `scheduled_for` at that jobsite, and a new case whose window overlaps the window of another non-`REJECTED` case at the same jobsite is rejected with `ERR_WINDOW_OVERLAP`. New cases are `OPEN`. A `FieldEngineer` reviews the case with a `decision`: approval moves it to `DOCUMENTED` and requires a stamped `documentation_url` (absent, the approval fails with `ERR_VALIDATION`), recording the reviewing engineer's `X-User-ID` in `approved_by_engineer_id` alongside the documentation link; rejection moves it to `REJECTED`.

### 3.9. End of Term: Election, Settlement, and Close-Out

Within the final stretch of an agreement, a `ContractorManager` elects how the term ends. The election call carries `expected_agreement_version` for optimistic concurrency (§2.7) and the chosen `end_of_term_option` — `BUYOUT`, `RENEWAL`, or `RETURN`. Two further gates apply: the logical clock must have reached at least 30 days before `end_date` (an election attempted earlier is rejected with `ERR_WINDOW_EXPIRED`), and no theft claim on any of the agreement's assets may be in `REPORTED` or `POLICE_VERIFIED` (otherwise `ERR_AGREEMENT_HAS_OPEN_CLAIMS`). A valid election moves the agreement from `ACTIVE` to `ENDING`, re-pins `end_of_term_option` to the elected value, increments the agreement's `version` by 1, and creates the agreement's settlement — at most one settlement exists per agreement, linked by its `agreement_id`, with its `option` echoing the elected value — with `provisional_amount_cents` computed from the fleet as it stands at election time.

The settlement amount depends on the elected option and is computed over the agreement's billable assets at computation time, using the same status filter as monthly billing. For `BUYOUT`, each billable asset is charged 20 percent of its model's `replacement_value_cents`, rounded half-up to whole cents per asset, and the amount is the sum across assets. For `RETURN`, the amount is the `assessed_damage_cents` supplied at finalization — the provisional snapshot has no inspection input yet and is 0. For `RENEWAL`, the amount is 0.

Finalization is a `FleetAdmin` action carrying `assessed_damage_cents`, and its effect forks on the elected option. In all cases the final amount is recomputed from the billable fleet as of the finalization call — before any retirements the call itself performs — so the provisional and final figures diverge whenever the fleet changed in between, for example when an asset went `LOST` after the election; the result is committed to `final_amount_cents` and `finalized` becomes true. For `RETURN`, finalization additionally requires every asset of the agreement to be in `REGISTERED` or `RETIRED`; any asset still `DEPLOYED`, `IN_TRANSIT`, `IN_REPAIR`, or `LOST` blocks the close with `ERR_RETURN_INCOMPLETE`. For `BUYOUT` and `RETURN`, finalization closes the agreement (`ENDING` to `CLOSED`); under `BUYOUT`, every asset that is neither `LOST` nor `RETIRED` moves to `RETIRED` after the final amount is computed. Under `RENEWAL`, the agreement returns from `ENDING` to `ACTIVE` instead: `term_months` grows by 12, `end_date` is recomputed, the settlement is finalized with a `final_amount_cents` of 0, and subsequent billing uses the rate card effective at the renewal date. Each finalization increments the agreement's `version` by 1.

## 4. Endpoint Definitions

All endpoints are mounted under `/fleet`. Creating a new resource returns HTTP 201; operations that modify an existing resource, query single resources, or run reports return HTTP 200. Every request requires the `X-User-ID` and `X-User-Role` headers described in §2.1, and list endpoints follow the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /fleet/_clock/set_current_utc | Advance the logical clock; fires theft-claim expiry and month-boundary sweeps | FleetAdmin |
| POST | /fleet/accounts | Create a contractor account | FleetAdmin |
| GET | /fleet/accounts/{id} | Get an account | FleetAdmin, ContractorManager, JobsiteSupervisor, ServiceCoordinator, ClaimsAdjuster, FieldEngineer |
| POST | /fleet/accounts/{id}/suspend | Suspend an account whose outstanding balance exceeds its credit limit | FleetAdmin |
| POST | /fleet/accounts/{id}/reinstate | Reinstate a suspended account once the balance is within limit | FleetAdmin |
| POST | /fleet/accounts/{id}/payments | Record a payment against the account's outstanding balance | ContractorManager |
| POST | /fleet/rate-cards | Create a rate card; closed-interval overlap within a category is rejected | FleetAdmin |
| POST | /fleet/tool-models | Create a catalog tool model | FleetAdmin |
| POST | /fleet/accounts/{account_id}/agreements | Create a fleet agreement in DRAFT | FleetAdmin |
| GET | /fleet/accounts/{id}/agreements | List agreements of an account | FleetAdmin, ContractorManager |
| GET | /fleet/agreements/{id} | Get an agreement | FleetAdmin, ContractorManager, JobsiteSupervisor |
| POST | /fleet/accounts/{account_id}/agreements/{id}/activate | Activate a DRAFT agreement; runs the prorated first billing | FleetAdmin |
| POST | /fleet/accounts/{account_id}/agreements/{id}/adjust-fleet | Add assets by tool model and/or return REGISTERED assets; reprices mid-cycle; OCC-guarded | ContractorManager |
| POST | /fleet/accounts/{account_id}/agreements/{id}/elect-end-of-term | Elect BUYOUT/RENEWAL/RETURN within the election window; creates the provisional settlement; OCC-guarded | ContractorManager |
| POST | /fleet/accounts/{account_id}/agreements/{id}/finalize-settlement | Finalize the settlement; BUYOUT/RETURN close the agreement, RENEWAL extends it by 12 months | FleetAdmin |
| GET | /fleet/agreements/{id}/utilization | Utilization report over billable assets; optional query mode=ACTUAL (default) or PROJECTED | FleetAdmin, ContractorManager |
| GET | /fleet/agreements/{id}/settlement | Read the end-of-term settlement for an agreement (array of length 0 or 1) | FleetAdmin, ContractorManager |
| POST | /fleet/accounts/{account_id}/jobsites | Create a jobsite | ContractorManager |
| GET | /fleet/accounts/{id}/jobsites | List jobsites of an account | FleetAdmin, ContractorManager, JobsiteSupervisor |
| GET | /fleet/jobsites/{id} | Get a jobsite | FleetAdmin, ContractorManager, JobsiteSupervisor |
| GET | /fleet/assets | List assets with optional filters agreement_id, tool_model_id, current_jobsite_id, pending_jobsite_id, status | FleetAdmin, ContractorManager, JobsiteSupervisor, ServiceCoordinator, ClaimsAdjuster |
| GET | /fleet/assets/{id} | Get an asset | FleetAdmin, ContractorManager, JobsiteSupervisor, ServiceCoordinator, ClaimsAdjuster |
| POST | /fleet/assets/{id}/deploy | Deploy a REGISTERED asset to a same-account jobsite with free capacity | JobsiteSupervisor |
| POST | /fleet/assets/{id}/transfer | Move a DEPLOYED asset to another jobsite via IN_TRANSIT | JobsiteSupervisor |
| POST | /fleet/assets/{id}/confirm-arrival | Confirm arrival of an IN_TRANSIT asset at its pending target jobsite | JobsiteSupervisor |
| POST | /fleet/assets/{id}/cancel-transfer | Return an IN_TRANSIT asset to its origin jobsite | JobsiteSupervisor |
| POST | /fleet/assets/{id}/check-in | Return a DEPLOYED asset to the depot | JobsiteSupervisor |
| POST | /fleet/assets/{id}/usage-events | Record a usage event for a DEPLOYED asset; both timestamps must fall in the current calendar month | JobsiteSupervisor |
| GET | /fleet/assets/{id}/usage-events | List usage events for an asset | FleetAdmin, ContractorManager, JobsiteSupervisor |
| POST | /fleet/assets/{asset_id}/repair-tickets | Open a repair ticket on a DEPLOYED asset | JobsiteSupervisor |
| GET | /fleet/assets/{id}/repair-tickets | List repair tickets for an asset | FleetAdmin, ContractorManager, JobsiteSupervisor, ServiceCoordinator |
| GET | /fleet/repair-tickets/{id} | Get a repair ticket | FleetAdmin, ContractorManager, JobsiteSupervisor, ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/schedule-pickup | Advance an OPENED ticket to PICKUP_SCHEDULED | ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/receive | Receive a PICKUP_SCHEDULED or REOPENED unit into IN_SHOP; recomputes the SLA window on the REOPENED leg | ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/dispatch-loaner | Dispatch the oldest AVAILABLE loaner of the same tool model | ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/complete-repair | Advance an IN_SHOP or LOANER_DISPATCHED ticket to QUALITY_CHECK | ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/close | Close a QUALITY_CHECK ticket; computes SLA credit, returns the loaner, redeploys the asset | ServiceCoordinator |
| POST | /fleet/repair-tickets/{id}/reopen | Reopen a CLOSED ticket within 14 days, at most twice | JobsiteSupervisor |
| POST | /fleet/loaner-units | Register a loaner unit | FleetAdmin |
| GET | /fleet/loaner-units | List loaner units with optional filters tool_model_id, assigned_ticket_id, status | FleetAdmin, ServiceCoordinator |
| GET | /fleet/loaner-units/{id} | Get a loaner unit | FleetAdmin, ServiceCoordinator |
| POST | /fleet/loaner-units/{id}/decommission | Decommission an AVAILABLE loaner unit | FleetAdmin |
| POST | /fleet/assets/{asset_id}/theft-claims | Report a theft on a DEPLOYED asset | JobsiteSupervisor |
| GET | /fleet/assets/{id}/theft-claims | List theft claims for an asset | FleetAdmin, ClaimsAdjuster |
| POST | /fleet/theft-claims/{id}/verify-police-report | Verify the police report within the 48-hour window | FleetAdmin |
| POST | /fleet/theft-claims/{id}/decide | Approve or deny a POLICE_VERIFIED claim; decider must differ from verifier | ClaimsAdjuster |
| POST | /fleet/consumable-products | Create a consumable product | FleetAdmin |
| POST | /fleet/accounts/{account_id}/consumable-orders | Create a DRAFT consumable order | ContractorManager |
| GET | /fleet/accounts/{id}/consumable-orders | List consumable orders of an account | FleetAdmin, ContractorManager |
| GET | /fleet/consumable-orders/{id} | Get a consumable order | FleetAdmin, ContractorManager |
| POST | /fleet/accounts/{account_id}/consumable-orders/{id}/submit | Submit a DRAFT order; enforces the application-approval gate and recomputes the total | ContractorManager |
| POST | /fleet/accounts/{account_id}/consumable-orders/{id}/decide | Approve (credit-gated) or reject a SUBMITTED order | FleetAdmin |
| POST | /fleet/accounts/{account_id}/consumable-orders/{id}/fulfill | Fulfill an APPROVED order | FleetAdmin |
| POST | /fleet/accounts/{account_id}/support-cases | Open an on-site support case; overlapping 2-hour windows at one jobsite are rejected | ContractorManager |
| GET | /fleet/support-cases | List support cases with optional filters account_id, jobsite_id, status, kind | FleetAdmin, ContractorManager, FieldEngineer |
| GET | /fleet/support-cases/{id} | Get a support case | FleetAdmin, ContractorManager, FieldEngineer |
| POST | /fleet/accounts/{account_id}/support-cases/{id}/review | Document (requires documentation_url) or reject an OPEN case | FieldEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_DUTY_SEGREGATION | 409 |
| ERR_WINDOW_EXPIRED | 409 |
| ERR_CAPACITY_EXCEEDED | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_LOANER_POOL_EMPTY | 409 |
| ERR_AGREEMENT_HAS_OPEN_CLAIMS | 409 |
| ERR_RETURN_INCOMPLETE | 409 |
| ERR_APPLICATION_APPROVAL_REQUIRED | 422 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_DUPLICATE | 409 |
