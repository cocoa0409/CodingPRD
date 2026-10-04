# Capacity Market Auction API — Product Requirements Document

## 1. Introduction

Regional transmission organizations run forward capacity auctions to make sure enough megawatts are committed to serve load three years ahead of the delivery year. Running such an auction is not a single clearing computation: it is a long, staged process that starts with a weather-normalized peak load forecast and an installed reserve margin, rolls the resulting reliability requirement down into zones with import constraints, accredits each participating resource into unforced capacity terms, collects and mitigates seller offers, clears the stack against zonal requirements, and then — for the entire delivery year — holds every committed resource accountable during emergency events, charging non-performance and redistributing the proceeds to the resources that did perform.

This document specifies the Capacity Market Auction API, mounted under `/capacity-market`, which operationalizes that full lifecycle. The API serves the grid operator's market staff (who administer delivery years, forecasts, auctions, mitigation, and emergency assessment), market participants (who register resources, submit offers, and manage their obligations, including bilateral replacement capacity transactions when a committed resource cannot perform), and the settlement function (which closes out delivery years and posts the final redistribution of non-performance charges). The design goals are auditability of every state change, exact reproducibility of every dollar figure, and deterministic behavior under concurrent access to commitments and auction runs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. Three roles are recognized, spelled exactly as follows: `MarketAdmin`, `ResourceOwner`, and `SettlementOps`. A request missing either header, presenting an empty `X-User-ID`, or naming a role outside this set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity semantics of `X-User-ID` differ by role. When `X-User-Role` is `ResourceOwner`, `X-User-ID` is the `id` of the acting `ResourceOwnerEntity`; ownership checks on any resource that references a `ResourceOwnerEntity` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `MarketAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `SettlementOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

`MarketAdmin` is the grid operator's staff role: it alone performs delivery-year setup, forecast submission and locking, zone definition, owner registration and suspension, accreditation review, the auction-run lifecycle, mitigation resolution, emergency-event declaration and assessment, measurement-report review, commitment default declaration, replacement review, and logical-clock control. `ResourceOwner` is the market-participant role: it registers and retires its own resources, and submits accreditations, offers, withdrawals, replacement transactions, and measurement reports for resources it owns. `SettlementOps` settles and closes delivery years and otherwise reads. All three roles may invoke every read (GET) endpoint.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. All list endpoints sort by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`. Several list endpoints also accept a `status` query parameter that filters results to resources in the named state, alongside the entity-specific filters enumerated in §4.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` formatted as a bare UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (ISO 8601 UTC, refreshed on every mutation) and `version` (an integer starting at its initial value that increments on every mutation of that resource). Two ledger-style resources are the exception: a PerformanceAssessment and a SettlementEntry carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because they are append-only records.

Any mutation that cascades into a parent or sibling resource — for example, a forecast lock that advances the delivery year, or an accreditation approval that updates the resource — independently refreshes that resource's `updated_at` and increments its `version`.

### 2.5. Precision, Rounding, and Monetary Conventions

All calculations use decimal arithmetic; floating-point artifacts must never leak into stored or returned values. Megawatt quantities are rounded to 3 decimal places, round half up. Dollar amounts and per-MW-day prices are rounded to 2 decimal places, round half up. Accreditation factors and performance ratios are rounded to 4 decimal places, round half up. Where a rounding step is specified as occurring *before* a downstream decision (as in auction clearing, where MW quantities are rounded before the marginal offer is determined), that ordering is normative. Monetary and MW values are returned as JSON numbers, never strings.

### 2.6. Validation Cascade and Gate Ordering

When a request is rejected, *which* error it is rejected with is part of the contract. Every endpoint evaluates its gates in a fixed priority order, and the first failing gate determines the response:

1. **Authentication** — headers present and role recognized; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization** — role permitted on this endpoint; failure yields `ERR_FORBIDDEN`.
3. **Path existence** — every path-templated resource id is resolved left to right; the first id that does not resolve yields `ERR_NOT_FOUND`, and no later segment is examined.
4. **Body foreign-key existence** — every body-supplied reference (such as `resource_id`, `zone_id`, `delivery_year_id`, `owner_id`, `offer_id`, `commitment_id`, `replacement_resource_id`, or `revision_of_id`) resolves to an existing row; failure yields `ERR_NOT_FOUND`.
5. **Optimistic concurrency** — where an endpoint declares an expected-version field, a stale value yields `ERR_STALE_VERSION`. This check runs *before* the target resource's own state gate, so a stale parent view surfaces as HTTP 412 rather than as a state conflict.
6. **State legality** — the requested transition must exist from the target resource's current state; failure yields `ERR_INVALID_STATE`.
7. **Ownership** — for owner-scoped mutations, the acting `ResourceOwner` must own the resource, offer, or commitment being mutated; failure yields `ERR_OWNERSHIP_VIOLATION`.
8. **Owner standing** — a `SUSPENDED` owner may not submit offers, replacements, or measurement reports; failure yields `ERR_OWNER_SUSPENDED`.
9. **Temporal and business rules** — domain-specific temporal, constraint, and fiscal checks (event overlap, measurement-window overlap, time-range sanity, forecast share sums, offer headroom, replacement deliverability, mitigation gating, accreditation uniqueness, replacement bounds, default thresholds, measurement applicability); each carries its own error id from §5. One ordering exception applies: on accreditation approval, the `EFFECTIVE`-uniqueness check (`ERR_ACCREDITATION_CONFLICT`) is evaluated before the resource-state and delivery-year-state checks of item 6, per §3.2.
10. **Request shape** — missing required fields, enum violations, and numeric range violations (for example `reserve_margin_pct` outside the open interval between 0 and 1, or `credit_score` outside the closed interval from 0 to 1000) yield `ERR_INVALID_REQUEST`.

### 2.7. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency contract, and only these two. First, creating a replacement transaction against a commitment requires the request to carry `expected_commitment_version`, the commitment `version` the submitter last observed. If the commitment's current `version` has advanced since then — for instance because an earlier replacement against the same commitment was approved, or a prior pending replacement already moved the commitment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never acts on a commitment state it has not observed. Second, withdrawing an offer requires `expected_auction_run_version`, the last-observed `version` of the parent auction run. Because sealing a run advances its version and freezes every offer's price terms, a withdrawal carrying a pre-seal version is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than as a plain state error. Endpoints not named here accept no version field.

### 2.8. Hierarchy and Nested Retrieval

Resources form a containment hierarchy: a delivery year owns zones, forecasts, auction runs, emergency events, and settlement entries; an owner owns resources; a resource owns accreditations, offers, commitments, and measurement reports; a commitment owns replacement transactions; an event owns assessments. For any request whose path nests one resource under another, identifiers are validated left to right and the first unresolvable id determines the `ERR_NOT_FOUND` response. Body-supplied references are validated the same way before any business rule runs, per the cascade in §2.6.

### 2.9. The Logical Clock

The server maintains a logical clock that governs every server-assigned timestamp. Before any explicit adjustment, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. All timestamps written by the server — `sealed_at`, `cleared_at`, `resolved_at`, `created_at`, `updated_at` — are taken from this clock.

## 3. Business Logic & Workflows

### 3.1. Delivery Year Setup: Zones, Forecasts, and the Reliability Requirement

A `MarketAdmin` opens a planning cycle by creating a **DeliveryYear** with a human-readable `delivery_year_label` (unique across all delivery years, conventionally of the form "2029/2030"), a `planning_period_start` (June 1 at 00:00 UTC of the first year), and a `planning_period_end` (May 31 at 23:59:59 UTC of the following year). The end must be strictly after the start; an inverted range is rejected with `ERR_INVALID_TIME_RANGE`. A new delivery year begins in `DRAFT` status, with `reliability_requirement_mw` at 0 and `forecast_version` at 0.

Within the delivery year, the admin defines **Zones**. Each zone carries a short `zone_code` (unique within its delivery year) and an optional `parent_zone_id`, which enables locational deliverability area (LDA) nesting: a zone with a null `parent_zone_id` is the RTO-wide root, and any nested zone must reference a parent in the same delivery year. A zone's `import_limit_mw` — the capacity import limit into the zone from its parent — is null for the unconstrained RTO-wide root and, when present, must be greater than zero. Until the forecast is locked, `zonal_requirement_mw` and `cleared_mw` sit at 0 and `clearing_price_per_mw_day` is null.

The admin then submits one or more **LoadForecast** revisions. A forecast carries `rto_peak_load_mw` (the coincident weather-normalized summer peak), `reserve_margin_pct` (the installed reserve margin as a fraction, strictly between 0 and 1 — anything outside that open interval is an `ERR_INVALID_REQUEST`), `pool_wide_avg_eford` (the pool-wide average forced outage rate on demand, a fraction at least 0 and below 1), and `zonal_peak_shares`, a map from top-level zone code to the zone's fraction of the RTO peak. The map's keys must cover every top-level zone of the delivery year, and the fractions — each rounded to 3 decimal places round half up — must sum to exactly 1.000; otherwise submission fails with `ERR_FORECAST_SHARES_INVALID`. The server assigns each forecast a `revision`, a monotonically increasing integer per delivery year starting at 1, so a higher revision supersedes a lower one; every new revision enters in `DRAFT` status.

Locking the forecast is the pivotal act of setup. It is permitted only while the delivery year is in `DRAFT`, requires exactly one `DRAFT` forecast (the highest revision) for that delivery year, and requires at least one zone to exist, including the RTO-wide root zone. Because re-locking is gated on `DRAFT`, adopting a newer forecast revision is impossible once the year has advanced to `AUCTION_OPEN`. On lock, the system computes the reliability requirement in four steps. First, the installed capacity basis is the RTO peak load multiplied by one plus the reserve margin. Second, that basis is converted to unforced capacity terms by multiplying by one minus the pool-wide average forced outage rate. Third, the requirement rolls down zonally: each top-level zone's `zonal_requirement_mw` is the RTO unforced requirement multiplied by its share from `zonal_peak_shares`, rounded to 3 decimals round half up; a nested LDA's requirement is its parent's zonal requirement multiplied by an LDA share taken from `zonal_peak_shares` when the LDA's code appears there, otherwise 1.0 when the LDA is its parent's only child, and failing that the lock is rejected with `ERR_FORECAST_SHARES_INVALID`. Fourth, the delivery year's `reliability_requirement_mw` is set to the RTO unforced requirement rounded to 3 decimals round half up. The same lock writes the locked revision into `forecast_version`, moves that forecast from `DRAFT` to `LOCKED`, flips any previously `LOCKED` forecast for the delivery year to `SUPERSEDED` (a transition that itself is only reachable while the delivery year is in `DRAFT`), advances the delivery year from `DRAFT` to `FORECAST_LOCKED`, and bumps the delivery year's `version`.

### 3.2. Participants, Resources, and Accreditation

Before any resource can participate, a `MarketAdmin` registers a **ResourceOwnerEntity** with a unique `legal_name`, a `contact_email` that must contain an at-sign, and a `credit_score` between 0 and 1000 inclusive. Owners begin `ACTIVE`; the admin may suspend one, moving it to `SUSPENDED` and incrementing its `version`. A `SUSPENDED` owner is blocked — with `ERR_OWNER_SUSPENDED` — from submitting offers, replacement transactions, and measurement reports, though nothing else in its existing portfolio changes.

A `ResourceOwner` registers a **CapacityResource** under its own `owner_id` in an interconnection `zone_id`, declaring a `resource_type` of `GEN` (thermal, hydro, or nuclear generation), `DR` (demand response), or `EE` (energy efficiency), plus a strictly positive `nameplate_mw` installed capability. New resources enter as `REGISTERED`, with `accredited_ucap_mw` at 0 and `must_offer` false. Ownership is enforced on every owner-scoped mutation: the acting owner's identity must equal the owning entity of the resource, offer, or commitment being mutated, on pain of `ERR_OWNERSHIP_VIOLATION`.

Accreditation converts nameplate capability into unforced capacity. The owner submits an **Accreditation** naming the `resource_id` and `delivery_year_id`, a `method` of `CLASS_AVG` or `UNIT_SPECIFIC`, a `forced_outage_rate` (the unit's own forced outage rate, a fraction at least 0 and below 1), and `scarcity_hours_sampled` (at least 1). When the method is `CLASS_AVG`, a `class_avg_factor` in the open-closed interval above 0 and at most 1 is required and `unit_elcc_factor` is ignored; when the method is `UNIT_SPECIFIC`, a `unit_elcc_factor` in the same interval is required and `class_avg_factor` is ignored. Submitted accreditations enter `PENDING_REVIEW`.

Approval by a `MarketAdmin` moves the accreditation to `EFFECTIVE` and runs the unforced-capacity calculation, but only when the resource is still `REGISTERED`, the accreditation's delivery year is in `DRAFT` or `FORECAST_LOCKED`, and no other `EFFECTIVE` accreditation exists for the same resource-and-delivery-year pair — a second effective accreditation is refused with `ERR_ACCREDITATION_CONFLICT`. The uniqueness check is evaluated before the resource-state and delivery-year-state checks: because a first approval cascades the resource from `REGISTERED` to `ACCREDITED`, evaluating resource state first would make the named conflict error unreachable, so a second approval attempt on a resource-and-delivery-year pair that already holds an `EFFECTIVE` accreditation fails with `ERR_ACCREDITATION_CONFLICT` even though the resource is no longer `REGISTERED`. The effective `accreditation_factor` depends on the variant. Under the class-average variant, the factor is simply the `class_avg_factor`; the outage rate and sample size play no role. Under the unit-specific variant, the unit's marginal ELCC is derated twice: the `unit_elcc_factor` is multiplied by an outage derate equal to one minus the unit's `forced_outage_rate`, divided by one minus the pool-wide average forced outage rate from the `LOCKED` forecast of that delivery year (or, while the year is still `DRAFT`, from its highest-revision `DRAFT` forecast), and then multiplied by a sample confidence equal to the lesser of 1.0 and the scarcity hours sampled divided by 100 — a full sample being 100 hours. Either way, the factor is capped at 1.0 and rounded to 4 decimal places round half up, and the accredited `ucap_mw` is the nameplate megawatts times the factor, rounded to 3 decimal places round half up. Approval cascades: the resource moves `REGISTERED` → `ACCREDITED`, its `accredited_ucap_mw` takes the computed `ucap_mw`, and its `must_offer` flag is recomputed — true exactly when the resource is a `GEN` resource holding a capacity commitment in the immediately prior delivery year. Rejection instead moves the accreditation `PENDING_REVIEW` → `REJECTED` with no further effect.

An accredited resource may later be retired by its owner, moving `ACCREDITED` → `RETIRED`, provided no commitment for the resource is in `ACTIVE` or `REPLACEMENT_PENDING`. Retirement sweeps any of the resource's still-`SUBMITTED` offers into `WITHDRAWN` and bumps the resource's `version`.

### 3.3. Auction Runs, Offers, and Seller Offer Caps

With the forecast locked, a `MarketAdmin` creates an **AuctionRun** for the delivery year, identified by a `run_label` such as "BRA" or "IRA-1" that is unique within the delivery year. Runs are created in `DRAFT`. Opening a run — `DRAFT` → `OPEN` — requires the delivery year to be `FORECAST_LOCKED` and no other run of the same delivery year to be in `OPEN` or `SEALED`; the open transition itself flips the delivery year to `AUCTION_OPEN` and increments the run's `version`. The run's `sealed_at` and `cleared_at` remain null until the corresponding transitions occur.

While a run is `OPEN`, a `ResourceOwner` submits an **AuctionOffer** for one of its `ACCREDITED` resources — offering from a resource in any other state is an `ERR_INVALID_STATE` — by naming the `resource_id` and `auction_run_id` and declaring `offer_mw` and an `offer_price_per_mw_day` floor of at least zero dollars per MW-day. The offered quantity must be greater than zero and must fit within the resource's remaining headroom: `offer_mw` may not exceed the resource's `accredited_ucap_mw` minus the megawatts this same resource has already offered into the same run in `SUBMITTED` or `SEALED` status, or the submission is rejected with `ERR_OFFER_EXCEEDS_UCAP`. New offers enter `SUBMITTED` with `cleared_mw` at 0 and `mitigation_status` `UNREVIEWED`.

An owner may withdraw a `SUBMITTED` offer while its run is still `OPEN`. Withdrawal is one of the two optimistic-concurrency operations in the system (§2.7): the request must carry `expected_auction_run_version`, and a mismatch against the run's current `version` is rejected with `ERR_STALE_VERSION` — in particular, because sealing advances the run's version, a withdrawal issued against a pre-seal view is refused as stale rather than as an ordinary state error. A successful withdrawal moves the offer to `WITHDRAWN` and increments the run's `version`.

### 3.4. Sealing, Mitigation Review, and Clearing

Sealing the run closes the offer window. It requires the run to be `OPEN` with at least one `SUBMITTED` offer, and it is rejected from any other state with `ERR_INVALID_STATE`. On seal, every `SUBMITTED` offer is first re-validated against the resource's current `accredited_ucap_mw`: an offer whose `offer_mw` no longer fits moves directly to `REJECTED`; the rest move to `SEALED`, with `offer_mw` and the price terms frozen. For each sealed offer the system computes the seller-specific offer cap and records it as `mitigated_cap_per_mw_day`. The cap is the greater of two screens — one tenth of the net cost of new entry, and the owner's avoidable cost rate, defined as 60.00 dollars per MW-day plus 0.10 dollars for every point the owner's `credit_score` falls below 1000 — and the result is then capped at the net cost of new entry itself, 390.00 dollars per MW-day, with the final cap rounded to 2 decimal places round half up. Sealing also auto-creates the per-offer **MitigationReview**: when the owner passes the three-pivotal-supplier screen for the offer's LDA (so `pivotal_supplier_flag` would be false) and the `offer_price_per_mw_day` is at or under the cap, the review is created already resolved as `EXEMPT` and the offer's `mitigation_status` becomes `EXEMPT`; otherwise the review is created `PENDING` with `pivotal_supplier_flag` set from the screen. The run records `sealed_at` from the logical clock and bumps its `version`.

The market monitor resolves each `PENDING` review by naming an `outcome` of `PASS` or `MITIGATE`, optionally with a `reviewer_note`; `resolved_at` is stamped when the review leaves `PENDING`. A `PASS` outcome marks the offer `PASSED` and keeps the `effective_price_per_mw_day` equal to the submitted `offer_price_per_mw_day`. A `MITIGATE` outcome is only legitimate when `pivotal_supplier_flag` is true; it marks the offer `MITIGATED` and reprices `effective_price_per_mw_day` to the lesser of the submitted price and the `mitigated_cap_per_mw_day`. The `EXEMPT` outcome is reachable only by the automatic screen at seal time.

Clearing requires the run to be `SEALED` and the delivery year `AUCTION_OPEN`, and it is gated on mitigation completeness: while any review for any offer in the run remains `PENDING`, the clear is rejected with `ERR_MITIGATION_PENDING`. Clearing proceeds in four steps. First, all resolved offers (those `PASSED`, `MITIGATED`, or `EXEMPT`) are stacked in merit order by `effective_price_per_mw_day` ascending, tie-broken by `sealed_at` and then by the offer's `created_at`, both ascending. Second, zones clear innermost-LDA-first, then parents, then the RTO: for each nested LDA, internal supply is the summed `offer_mw` of remaining offers in that zone; the import need is the amount by which the `zonal_requirement_mw` exceeds internal supply (never below zero); the importable quantity is the lesser of that need and the zone's `import_limit_mw`; internal offers clear cheapest-first, then imports up to the importable quantity; the zone's clearing price is the `effective_price_per_mw_day` of the marginal offer cleared for it, and if the requirement is not fully met the zone prices at the administrative shortage price of 390.00 dollars per MW-day. For the RTO-wide zone the requirement is the `reliability_requirement_mw` less the megawatts already counted toward nested-LDA requirements, and its price is the marginal offer's effective price — the administrative shortage price is never applied to the RTO-wide zone, even when its requirement is not fully met (it is left at the marginal offer's effective price, or null when no offer was cleared for it). Third, price separation runs upward only: a nested LDA's `clearing_price_per_mw_day` is the greater of its own marginal price and its parent zone's marginal price, so child-zone resources receive the child price and parent-zone resources the parent price. Fourth, commitments are assigned in merit order: each offer's `cleared_mw` is the lesser of its `offer_mw` and the remaining requirement of its zone, with every megawatt figure rounded to 3 decimals round half up *before* price assignment and the marginal offer determined on those rounded quantities. An offer cleared in full becomes `CLEARED`, one cleared in part becomes `PARTIALLY_CLEARED`, and one cleared not at all becomes `REJECTED`. For every offer with a positive `cleared_mw`, a **CapacityCommitment** is created in `ACTIVE` status with `committed_mw` equal to the cleared quantity and `clearing_price_per_mw_day` taken from the resource's zone. The run stamps `cleared_at`, moves `SEALED` → `CLEARED`, and the delivery year advances `AUCTION_OPEN` → `CLEARED`, each with its `version` increment.

### 3.5. Commitments, Replacements, and Default

A commitment is the resource owner's obligation to deliver. Its `daily_revenue_dollars` is the `committed_mw` times its locked `clearing_price_per_mw_day`, rounded to 2 decimal places round half up, and is recomputed whenever `committed_mw` changes. Its `cumulative_performance_score` begins at 0.

When a committed resource cannot perform, the owner of the original commitment submits a **ReplacementTransaction**, naming the `commitment_id`, a `replacement_resource_id`, the `replacement_mw` to release, and a bilateral `price_per_mw_day` that is purely informational and never alters the original commitment's clearing price. This creation is the second optimistic-concurrency operation: it must carry `expected_commitment_version` equal to the commitment's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` before any state gate is consulted — this is the serialization point that protects a submitter from acting on a commitment whose obligated megawatts have already been reduced by an earlier approved replacement or that a prior pending replacement has already moved. The commitment must be `ACTIVE`. The quantity must be greater than zero and no more than the commitment's current `committed_mw`, or the request fails with `ERR_REPLACEMENT_EXCEEDS_COMMITMENT`. Deliverability is then enforced: the replacement resource must be `ACCREDITED` for the commitment's delivery year, must have remaining accredited headroom — its `accredited_ucap_mw` less its `ACTIVE` committed megawatts in the same delivery year — of at least `replacement_mw`, must not be the commitment's own resource, and must sit in the commitment's zone or in an ancestor or descendant LDA of it; any of these failures is an `ERR_REPLACEMENT_NOT_DELIVERABLE`. The replacement owner may be any `ACTIVE` owner, the same or different. A valid submission creates the transaction in `PENDING`, moves the commitment `ACTIVE` → `REPLACEMENT_PENDING`, and increments the commitment's `version`.

Review of a `PENDING` transaction has two outcomes. Rejection moves the transaction to `REJECTED` and reverts the commitment `REPLACEMENT_PENDING` → `ACTIVE` with `committed_mw` unchanged. Approval moves the transaction to `APPROVED`, returns the commitment to `ACTIVE` with `committed_mw` reduced by `replacement_mw`, recomputes its `daily_revenue_dollars`, and creates a new `ACTIVE` commitment for the replacement resource: its `committed_mw` is the replaced quantity, its `clearing_price_per_mw_day` is copied from the original commitment, it belongs to the same delivery year, and its `offer_id` is copied from the original commitment.

A chronically non-performing commitment may be declared `DEFAULTED` by a `MarketAdmin`, but only from `ACTIVE` and only when its `cumulative_performance_score` is below 0.40 and at least two `FINALIZED` performance assessments exist for it; otherwise the attempt fails with `ERR_DEFAULT_THRESHOLD_NOT_MET`. Default sets the resource's `must_offer` to false; the resource remains `ACCREDITED` but cannot offer in the next run for the same delivery year, and the commitment's `version` increments.

### 3.6. Emergency Events and Performance Assessment

During the delivery year, a `MarketAdmin` declares an **EmergencyEvent** — a performance assessment interval — with a `delivery_year_id`, an `event_start`, an `event_end` strictly after it, and an `event_type` of `EMERGENCY_ACTION` (assessing every commitment) or `DR_TEST` (assessing demand-response commitments only). Both endpoints of the window must fall within the delivery year's planning period; violations are rejected with `ERR_INVALID_TIME_RANGE`. The event enters `DECLARED`.

Beginning assessment moves the event `DECLARED` → `ASSESSING` and requires the delivery year to be `CLEARED`. Events may be *declared* with overlapping windows so reviews can be staged, but only non-overlapping events may enter assessment: no other event of the same delivery year in `DECLARED`, `ASSESSING`, or `ASSESSED` may have a half-open interval that overlaps this event's interval — adjacent events, where one ends exactly when the other begins, are allowed — and a violation is rejected with `ERR_EVENT_OVERLAP`. On entry to `ASSESSING`, the system creates a `DRAFT` **PerformanceAssessment** for every commitment of the delivery year in `ACTIVE` or `SETTLED` status whose resource type matches the event scope. Assessments are append-only records: they carry `id` and `created_at` but no `updated_at` or `version`.

The admin then records each assessment's `expected_mw` and `actual_mw`, each at least zero. The `expected_mw` is conventionally no more than the commitment's `committed_mw` at assessment time, but this is a descriptive convention only: no validation gate rejects an `expected_mw` above the commitment's `committed_mw`, and the value is recorded as given. When every assessment of the event has its `actual_mw` recorded, finalization moves the event `ASSESSING` → `ASSESSED` and flips each assessment `DRAFT` → `FINALIZED`. Finalization computes each assessment's `performance_ratio`: 1.0000 when `expected_mw` is zero (no obligation during the interval), otherwise the lesser of the delivered-over-expected quotient and 1.5000 — the over-performance bonus cap — rounded to 4 decimal places round half up. It also computes the signed `charge_or_credit_dollars`. Let the interval duration in hours, possibly fractional, be H; the daily base rate is the commitment's clearing price divided by the 24 hours of a day. The shortfall is the amount by which `expected_mw` exceeds `actual_mw` (never below zero); the over-delivery is the converse. When the unrounded ratio of actual to expected is at least 0.60, the non-performance charge is the shortfall times the base rate times H times 1.0; when the ratio is at least 0.30 but below 0.60 the multiplier is 1.5; below 0.30 it is 2.0 — with the tier chosen on the unrounded quotient. A bonus is earned only when there is no shortfall and `expected_mw` is positive: the lesser of the over-delivery and half of `expected_mw`, times the base rate times H times 1.0. The settlement amount is the bonus minus the charge, rounded to 2 decimal places round half up — negative means the owner owes the pool, positive means a credit — and is exactly 0.00 when `expected_mw` is zero. Finalization posts a `CHARGE` or `BONUS` **SettlementEntry** for each assessment, stamps each assessment's `assessed_mwh` as its `expected_mw` times H, and recomputes each affected commitment's `cumulative_performance_score` as the weighted average of `performance_ratio` across all of that commitment's `FINALIZED` assessments, weighted by `assessed_mwh` and rounded to 4 decimal places round half up.

### 3.7. Measurement and Verification for Demand Response and Energy Efficiency

Demand-response and energy-efficiency resources prove their capability through **MeasurementReport** submissions by their owner; generation resources may not submit, and an attempt yields `ERR_MEASUREMENT_NOT_APPLICABLE`. A report names the `resource_id` and `delivery_year_id`, a measurement window from `reporting_period_start` (inclusive) to `reporting_period_end` (exclusive) that must end after it begins on pain of `ERR_INVALID_TIME_RANGE`, a `metered_mwh` of at least zero, and a strictly positive `baseline_mwh` from the approved baseline methodology. A report enters `SUBMITTED`.

Review moves the report `SUBMITTED` → `UNDER_REVIEW`. Verification moves it to `VERIFIED` and enforces the window-exclusion rule: a `VERIFIED` report's half-open window blocks any later report for the same resource with an overlapping window from entering `VERIFIED`, rejected with `ERR_MEASUREMENT_WINDOW_OVERLAP`. Verification computes `verified_ucap_mw`: the delivered energy is the lesser of `metered_mwh` and `baseline_mwh`; divided by the window length in hours it yields an average megawatt figure, which is then scaled by the resource's `EFFECTIVE` accreditation factor for the report's delivery year — or by 1.0 when no effective accreditation exists, so unaccredited DR and EE resources are still measured at face value — and rounded to 3 decimal places round half up. When the resource holds an `ACTIVE` commitment in that delivery year and the verified value falls short of `committed_mw`, the commitment itself is left `ACTIVE` and no replacement is created automatically; instead the shortfall — `committed_mw` minus `verified_ucap_mw`, at 3-decimal precision — is recorded by setting the resource's `must_offer` flag true for the next delivery year. Rejection instead moves the report to `REJECTED`. A rejected report is never edited in place: the owner submits a revision whose `revision_of_id` points at the `REJECTED` report, the new report enters `SUBMITTED` provided its window overlaps no `VERIFIED` report for the resource, and the prior report remains untouched — an append-only revision history.

### 3.8. Settlement, Redistribution, and Year Close-Out

When the delivery year's obligations have all been assessed, a `SettlementOps` operator settles the year, moving it `CLEARED` → `SETTLED`. Settlement is permitted only when every emergency event of the year is in `ASSESSED` or `SETTLED`, every performance assessment is `FINALIZED`, and no replacement transaction for the year's commitments remains `PENDING`. Settlement first redistributes each `ASSESSED` event's non-performance pool. The pool for an event is the sum of the charges collected — the negated amounts of its `FINALIZED` assessments with negative `charge_or_credit_dollars` — minus the sum of the bonus credits already paid out. If the pool is zero or negative, no redistribution occurs for that event. Otherwise the pool is distributed pro-rata among the full performers — the `FINALIZED` assessments whose `performance_ratio` is at least 1.0000 — weighted by `assessed_mwh`: each performer's share is the pool times its assessed megawatt-hours divided by the total assessed megawatt-hours of all performers. Shares are rounded to 2 decimal places round half up in ascending order of assessment `created_at`, and the last performer in that order receives the pool minus the sum of all prior rounded shares, so the rounding remainder is absorbed rather than lost or double-paid. One `REDISTRIBUTION` **SettlementEntry** is posted per performer commitment, and each `ASSESSED` event then moves to `SETTLED`. Settlement also moves the year's `ACTIVE` commitments to `SETTLED`, carries the cleared auction run from `CLEARED` to `SETTLED`, and increments the delivery year's `version`. A final close action by `SettlementOps` moves the year `SETTLED` → `CLOSED`, the terminal state.

The **SettlementEntry** ledger records every dollar movement with an `entry_type` of `CHARGE`, `BONUS`, or `REDISTRIBUTION`, a signed `amount_dollars` at 2-decimal precision where negative is owed to the pool and positive is paid to the owner, a `commitment_id`, a `delivery_year_id`, and an `emergency_event_id` that is null for daily capacity revenue accrual entries. Entries are append-only and, like assessments, carry `id` and `created_at` but neither `updated_at` nor `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The complete request and response semantics of each endpoint are defined by the workflows in §3 and the global rules in §2; this table is an index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/capacity-market/delivery-years` | Create a delivery year in DRAFT | MarketAdmin |
| GET | `/capacity-market/delivery-years` | List delivery years (paginated) | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/delivery-years/{id}` | Fetch one delivery year | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/delivery-years/{id}/lock-forecast` | Lock the highest-revision DRAFT forecast and compute the reliability requirement | MarketAdmin |
| POST | `/capacity-market/delivery-years/{id}/settle` | Settle the delivery year; post redistribution entries | SettlementOps |
| POST | `/capacity-market/delivery-years/{id}/close` | Close a settled delivery year | SettlementOps |
| POST | `/capacity-market/delivery-years/{id}/zones` | Create a zone in a delivery year | MarketAdmin |
| GET | `/capacity-market/delivery-years/{id}/zones` | List zones of a delivery year | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/zones` | List zones across delivery years | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/zones/{id}` | Fetch one zone | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/delivery-years/{id}/forecasts` | Submit a new LoadForecast revision | MarketAdmin |
| GET | `/capacity-market/delivery-years/{id}/forecasts` | List forecast revisions of a delivery year | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/owners` | Register a market participant | MarketAdmin |
| GET | `/capacity-market/owners/{id}` | Fetch one owner | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/owners/{id}/suspend` | Suspend an owner | MarketAdmin |
| POST | `/capacity-market/resources` | Register a capacity resource under an owner and zone | ResourceOwner |
| GET | `/capacity-market/resources` | List resources; filter by owner, zone, type, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/resources/{id}` | Fetch one resource | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/resources/{id}/retire` | Retire an accredited resource with no live commitments | ResourceOwner |
| POST | `/capacity-market/accreditations` | Submit an accreditation for a resource and delivery year | ResourceOwner |
| GET | `/capacity-market/accreditations` | List accreditations; filter by resource, delivery year, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/accreditations/{id}` | Fetch one accreditation | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/accreditations/{id}/approve` | Approve an accreditation; compute UCAP and accredit the resource | MarketAdmin |
| POST | `/capacity-market/accreditations/{id}/reject` | Reject an accreditation | MarketAdmin |
| POST | `/capacity-market/auction-runs` | Create an auction run (DRAFT) for a delivery year | MarketAdmin |
| GET | `/capacity-market/auction-runs` | List auction runs; filter by delivery year, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/auction-runs/{id}` | Fetch one auction run | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/auction-runs/{id}/open` | Open the run for offers | MarketAdmin |
| POST | `/capacity-market/auction-runs/{id}/seal` | Seal the offer window; freeze offers, compute caps, open mitigation reviews | MarketAdmin |
| POST | `/capacity-market/auction-runs/{id}/clear` | Clear the auction; publish zonal prices and create commitments | MarketAdmin |
| POST | `/capacity-market/offers` | Submit an offer into an OPEN run for an ACCREDITED resource | ResourceOwner |
| GET | `/capacity-market/offers` | List offers; filter by resource, run, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/offers/{id}` | Fetch one offer | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/offers/{id}/withdraw` | Withdraw a SUBMITTED offer while the run is OPEN | ResourceOwner |
| GET | `/capacity-market/mitigation-reviews` | List mitigation reviews; filter by offer, outcome | MarketAdmin, SettlementOps |
| GET | `/capacity-market/offers/{id}/mitigation-review` | Fetch the (0-or-1) review for an offer | MarketAdmin, SettlementOps |
| POST | `/capacity-market/mitigation-reviews/{id}/resolve` | Resolve a PENDING review to PASS or MITIGATE | MarketAdmin |
| GET | `/capacity-market/commitments` | List commitments; filter by resource, delivery year, offer, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/commitments/{id}` | Fetch one commitment | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/commitments/{id}/default` | Declare a commitment defaulted for sustained non-performance | MarketAdmin |
| POST | `/capacity-market/replacement-transactions` | Submit a bilateral replacement against an ACTIVE commitment | ResourceOwner |
| GET | `/capacity-market/replacement-transactions` | List replacements; filter by commitment, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/replacement-transactions/{id}` | Fetch one replacement transaction | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/replacement-transactions/{id}/approve` | Approve a PENDING replacement | MarketAdmin |
| POST | `/capacity-market/replacement-transactions/{id}/reject` | Reject a PENDING replacement | MarketAdmin |
| POST | `/capacity-market/emergency-events` | Declare an emergency event in a delivery year | MarketAdmin |
| GET | `/capacity-market/emergency-events` | List emergency events; filter by delivery year, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/emergency-events/{id}` | Fetch one emergency event | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/emergency-events/{id}/begin-assessment` | Move event to ASSESSING; spawn DRAFT assessments for in-scope commitments | MarketAdmin |
| GET | `/capacity-market/emergency-events/{id}/assessments` | List assessments of an event | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/assessments` | List performance assessments; filter by commitment, event, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/assessments/{id}` | Fetch one performance assessment | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/assessments/{id}/record-actual` | Record expected and actual megawatts on a DRAFT assessment | MarketAdmin |
| POST | `/capacity-market/emergency-events/{id}/finalize-assessments` | Finalize all DRAFT assessments; post charges and bonuses | MarketAdmin |
| POST | `/capacity-market/measurement-reports` | Submit an M&V report (or a revision of a REJECTED report) | ResourceOwner |
| GET | `/capacity-market/measurement-reports` | List measurement reports; filter by resource, delivery year, status | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/measurement-reports/{id}` | Fetch one measurement report | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/measurement-reports/{id}/start-review` | Move a SUBMITTED report to UNDER_REVIEW | MarketAdmin |
| POST | `/capacity-market/measurement-reports/{id}/verify` | Verify an UNDER_REVIEW report; compute verified UCAP | MarketAdmin |
| POST | `/capacity-market/measurement-reports/{id}/reject` | Reject an UNDER_REVIEW report | MarketAdmin |
| GET | `/capacity-market/settlement-entries` | List settlement ledger entries; filter by delivery year, commitment, event, type | MarketAdmin, ResourceOwner, SettlementOps |
| GET | `/capacity-market/settlement-entries/{id}` | Fetch one settlement ledger entry | MarketAdmin, ResourceOwner, SettlementOps |
| POST | `/capacity-market/_clock/set_current_utc` | Advance the server's logical clock (test-driving) | MarketAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_OWNER_SUSPENDED` | 422 |
| `ERR_EVENT_OVERLAP` | 409 |
| `ERR_MEASUREMENT_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_FORECAST_SHARES_INVALID` | 422 |
| `ERR_OFFER_EXCEEDS_UCAP` | 422 |
| `ERR_REPLACEMENT_NOT_DELIVERABLE` | 422 |
| `ERR_MITIGATION_PENDING` | 409 |
| `ERR_ACCREDITATION_CONFLICT` | 409 |
| `ERR_REPLACEMENT_EXCEEDS_COMMITMENT` | 422 |
| `ERR_DEFAULT_THRESHOLD_NOT_MET` | 422 |
| `ERR_MEASUREMENT_NOT_APPLICABLE` | 422 |
