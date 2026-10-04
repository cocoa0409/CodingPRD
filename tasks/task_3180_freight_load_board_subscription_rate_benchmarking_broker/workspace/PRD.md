# Freight Load Board API — Product Requirements Document

## 1. Introduction

Freight brokers and motor carriers live and die by information asymmetry: who has a truck, who has a load, what a lane is actually paying, and whether the counterparty on the other end of the deal pays its invoices and holds valid operating authority. This product is a subscription-based freight load board — a marketplace API in the style of DAT Freight & Analytics — on which broker organizations post loads, carrier organizations post available trucks, and the two sides find each other through lane, equipment, and date search. Around that core marketplace, the platform layers three trust-and-intelligence services: subscription tiering that meters posting volume, daily search access, and analytics depth; rate benchmarking computed from transacted spot and contract freight data, expressed as lane-level percentiles with a fuel-price adjustment; and broker credit scoring built from carrier-reported payment experiences, complete with days-to-pay statistics, a dispute workflow, and automatic escalation when a broker's score collapses.

Trust is enforced, not assumed. Every acting organization must maintain an authority verification record whose insurance policy windows are checked for gaps and for coverage of the current moment before the org may post or book; fraud analysts can open alerts for double brokering, identity spoofing, and cargo theft schemes, and a confirmed alert suspends the target organization and cascades through its posts, bookings, subscriptions, and contributed rate data. Data contribution is part of the social contract: organizations that report enough of their own transacted rates earn access to the deepest analytics, while free-riders are limited to spot-only lane views.

This document specifies the API contract, the system-wide principles, and the business workflows that an implementation must honor. All time in the system is governed by a controllable logical clock; monetary amounts are integer cents; and every state transition, calculation, and error condition described here is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which the user acts. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are accepted, the role is checked against the endpoint's permission set; a role that is not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `PlatformAdmin` — the platform operator; manages organizations, subscription plans, subscriptions, and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any organization's `id`.
- `BrokerAdmin` — acts on behalf of a broker organization. When `X-User-Role` is `BrokerAdmin`, `X-User-ID` is the `id` of the acting `BrokerOrg`; ownership checks on any resource that references a broker organization compare the resource's `broker_org_id` field to `X-User-ID`.
- `CarrierAdmin` — acts on behalf of a carrier organization. When `X-User-Role` is `CarrierAdmin`, `X-User-ID` is the `id` of the acting `CarrierOrg`; ownership checks on any resource that references a carrier organization compare the resource's `carrier_org_id` field to `X-User-ID`.
- `ComplianceAnalyst` — adjudicates fraud alerts and credit disputes and decides authority verifications. When `X-User-Role` is `ComplianceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `DataOps` — performs data stewardship, in particular excluding bad rate transactions from benchmarks. When `X-User-Role` is `DataOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Write endpoints are partitioned among the roles. Only a `PlatformAdmin` may create or administer broker orgs, carrier orgs, subscription plans, and subscriptions, and may set the logical clock. Only a `BrokerAdmin` may post loads, withdraw loads, file credit disputes, and submit rebuttals. Only a `CarrierAdmin` may post trucks, withdraw trucks, create bookings, complete bookings, and report credit events. Booking cancellation is shared: a `CarrierAdmin` cancels a booking on its own truck side, a `BrokerAdmin` cancels on its own load side. Contributing rate transactions and submitting authority verifications are shared between `BrokerAdmin` and `CarrierAdmin` (each for its own org). Only a `ComplianceAnalyst` may open, confirm, or dismiss fraud alerts, drive credit-dispute review and resolution, and verify or revoke authority records. Only `DataOps` may exclude a rate transaction. Read endpoints are available to all five roles except where §4 states otherwise. Ownership-scoped operations add a further check: when the acting entity-backed org does not own the target resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Results are always sorted by `created_at` ascending unless stated otherwise. The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All temporal behavior in the system — billing periods, posting expiry, insurance coverage, contribution windows, dispute deadlines, benchmark sampling windows — is evaluated against a single logical clock, never against wall-clock time. At server startup the clock reads exactly 2026-09-01T00:00:00Z, and it changes only when a `PlatformAdmin` explicitly sets it to a supplied `to_iso8601` instant, the server answering with the resulting `current_utc`. Setting the clock eagerly applies every time-driven transition whose threshold has been crossed: open loads whose pickup window has closed become `EXPIRED`, available trucks whose availability window has closed become `EXPIRED`, authority verifications whose merged coverage has run out become `EXPIRED`, and past-due subscriptions whose grace period has elapsed are suspended. The same transitions are also applied lazily whenever an affected record is read, so a record never presents a stale status simply because the clock moved while nobody was watching.

### 2.5. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp of the same format refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on every mutation of the resource. All entities in this domain — broker orgs, carrier orgs, plans, subscriptions, load posts, truck posts, bookings, rate transactions, credit report events, credit disputes, fraud alerts, and authority verifications — carry the full common set. New resources are returned with HTTP 201; modifications and state-transition actions return HTTP 200.

### 2.6. Monetary Amounts, Precision, and Rounding

All money is represented as integer cents: `rate_offer_cents`, `agreed_rate_cents`, `rate_cents`, `fuel_price_cents`, `invoice_amount_cents`, the subscription `period_price_cents`, and every benchmark output field. No rounding is required for pure integer-cent arithmetic. Where a calculation produces a fractional intermediate — the fuel surcharge percentage (carried to 4 decimal places), the blended-variant contract haircut, per-transaction surcharge cents, the fuel-adjusted median, days-to-pay averages (4 decimal places), and the broker credit score — the final value at each pinned step is rounded half-up: a fraction of exactly one-half rounds away from zero. Days-to-pay averages are reported to 4 decimal places; the credit score itself is an integer after half-up rounding and clamping.

### 2.7. Validation Order

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. First, the presence and well-formedness of `X-User-ID` and `X-User-Role` (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role permission for the endpoint (priority 2, `ERR_UNAUTHORIZED_ROLE`). Third, existence of every path id and body foreign-key id, validated left-to-right in the order declared by the endpoint's input list, yielding the appropriate 404 (`ERR_ORG_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_LOAD_POST_NOT_FOUND`, `ERR_TRUCK_POST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_RATE_TRANSACTION_NOT_FOUND`, `ERR_CREDIT_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_FRAUD_ALERT_NOT_FOUND`, or `ERR_AUTHORITY_VERIFICATION_NOT_FOUND`). Fourth, state admissibility: the org must be `ACTIVE`, the subscription must be `ACTIVE`, and the target entity must be in a state that permits the transition, yielding the state-specific 409 codes such as `ERR_ORG_NOT_ACTIVE`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_LOAD_POST_NOT_OPEN`, `ERR_TRUCK_POST_NOT_AVAILABLE`, `ERR_BOOKING_NOT_ACTIVE`, `ERR_CREDIT_EVENT_NOT_PUBLISHED`, and `ERR_DISPUTE_INVALID_STATE`. Fifth, business safety for posting and booking operations: the acting org must hold a `VERIFIED` authority record with `insurance_ok` true, and no `CONFIRMED` fraud alert may target it (`ERR_AUTHORITY_NOT_VERIFIED`, `ERR_INSURANCE_NOT_VERIFIED`, `ERR_ORG_HAS_CONFIRMED_FRAUD`). Sixth, ownership (`ERR_NOT_RESOURCE_OWNER`). Seventh, temporal rules: truck availability window overlap, pickup window ordering, and the 90-day dispute filing window (`ERR_TRUCK_WINDOW_OVERLAP`, `ERR_INVALID_REQUEST`, `ERR_DISPUTE_WINDOW_EXPIRED`). Eighth, constraint checks: enum membership, uniqueness of `mc_number` and `dot_number`, the exactly-one-org rule, positive amounts, the rebuttal cap, and optimistic-concurrency version match (`ERR_INVALID_REQUEST`, `ERR_DUPLICATE_MC_NUMBER`, `ERR_DUPLICATE_DOT_NUMBER`, `ERR_REBUTTAL_LIMIT_EXCEEDED`, `ERR_STALE_VERSION`). Ninth and last, fiscal limits: the posting hard cap and the daily search limit (`ERR_POSTING_QUOTA_EXCEEDED`, `ERR_SEARCH_LIMIT_EXCEEDED`).

### 2.8. Optimistic Concurrency Control

Plan changes on a subscription are guarded by optimistic concurrency control. A request to change a subscription's plan must carry `expected_subscription_version`, the `version` of the `Subscription` the client last observed. If any intervening mutation — a mark-past-due, a record-payment, an earlier plan change, or a cascade-driven update — has advanced the subscription's `version` beyond what the client presents, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied. A successful plan change increments `Subscription.version` by 1 and recomputes the period price against the new plan. No other endpoint in the system takes an expected-version field.

### 2.9. Resource Existence and Nested Retrieval

Every path identifier and every foreign-key identifier supplied in a request body must resolve to an existing record before any state or business rule is evaluated. Identifiers are validated left-to-right in the order the endpoint declares them, and the first missing identifier produces the corresponding 404 error from §5. Where a list endpoint is nested beneath a parent resource — the authority verifications of a broker org or of a carrier org — the parent id is validated first; only then are child rows returned.

### 2.10. Status Codes

Resource creation returns 201; all other successful operations, including state-transition actions and reads, return 200. Client errors use 400 for malformed requests and missing context headers, 403 for role and ownership failures and for analytics-depth or data-contribution denials, 404 for missing resources, 409 for state and safety conflicts, 412 for stale optimistic-concurrency versions, 402 for fiscal limit breaches (posting quota and daily search limit), and 422 for well-formed requests that fail domain validation such as insufficient benchmark data, insurance coverage gaps, or an expired dispute window.

## 3. Business Logic & Workflows

### 3.1. Onboarding Organizations and Their Operating Authority

A marketplace begins with the `PlatformAdmin` registering organizations. A broker organization is created with its `legal_name` and `mc_number`, the FMCSA motor-carrier docket number, which must be unique across all broker orgs — a duplicate submission is rejected with `ERR_DUPLICATE_MC_NUMBER` (HTTP 409). A fresh broker org starts in `ACTIVE` status with a `credit_score` of 70 and a `credit_badge` of `STANDARD`, reflecting the absence of payment history rather than proven trustworthiness. A carrier organization is created with its `legal_name` and `dot_number`, the USDOT number, likewise unique across carrier orgs, with duplicates rejected as `ERR_DUPLICATE_DOT_NUMBER`. Both org types carry a `data_contribution_flag`, described in §3.6, that gates the deepest analytics.

Registration alone does not grant marketplace privileges. Before an org can post or book, it must hold an authority verification that a `ComplianceAnalyst` has marked `VERIFIED`. Submission is performed by the org's own admin — a `BrokerAdmin` supplying `broker_org_id` or a `CarrierAdmin` supplying `carrier_org_id`, with exactly one of the two present, otherwise `ERR_INVALID_REQUEST` — together with an `authority_reference` docket string and an `insurance_windows` array of half-open policy windows, each an `effective_from` and an `effective_to`. On submission the record is `PENDING`, and the platform computes three derived values: the windows are sorted by `effective_from` ascending with ties broken by `effective_to` ascending, then merged with half-open semantics where a window extends coverage only when its `effective_from` is at or before the running `covered_until` (adjacency counts as contiguous). `covered_until` becomes the maximum `effective_to` over the merged contiguous prefix — null when there are no windows at all. `coverage_gap_detected` is true when some window's `effective_from` falls strictly after the running `covered_until` at its turn. `insurance_ok` holds only when no gap was detected, `covered_until` is not null, and the first window's `effective_from` is at or before the current logical clock while the clock is strictly before `covered_until`.

Verification is a judgment call by a `ComplianceAnalyst`: it requires a non-empty `authority_reference` and insurance coverage satisfied against the current clock; if the windows contain a gap or do not cover the present moment, the verify attempt is rejected with `ERR_INSURANCE_WINDOW_GAP` (HTTP 422). A `VERIFIED` record transitions automatically to `EXPIRED` once the logical clock reaches `covered_until` — applied eagerly on clock set and lazily on read — and may be returned to `VERIFIED` after the org updates its `insurance_windows` to restore coverage and the analyst verifies again. From `PENDING`, `VERIFIED`, or `EXPIRED`, an analyst may instead revoke the record, landing it in the terminal `REVOKED` state. Posting and booking operations consult this machinery through two distinct failures: an org with no `VERIFIED` verification is rejected with `ERR_AUTHORITY_NOT_VERIFIED`, and an org whose verification exists but computes `insurance_ok` as false is rejected with `ERR_INSURANCE_NOT_VERIFIED`.

### 3.2. Plans, Subscriptions, and Period Pricing

The commercial shape of the marketplace is defined by subscription plans, created by the `PlatformAdmin`. Each plan carries a unique `code` from the set `BASIC`, `PRO`, `ENTERPRISE`; a `monthly_posting_allowance` of posts included in the base fee; an `overage_tier1_limit`, the number of overage posts billed at the cheaper tier-1 rate before the tier-2 rate applies; an `overage_hard_cap`, the maximum overage posts above the allowance, beyond which further posts are rejected outright; a `search_daily_limit` bounding load-board searches per logical-clock day; an `analytics_depth` of `NONE`, `LANE_LEVEL`, or `FULL`; and a `requires_data_contribution` boolean marking plans whose `FULL` analytics is conditional on the caller org's contribution flag.

A subscription binds exactly one org to one plan: creation requires a `plan_id` and exactly one of `broker_org_id` or `carrier_org_id`, with both supplied or neither supplied yielding `ERR_INVALID_REQUEST`. The subscription's `period_start` is the logical clock at creation and its `period_end` is exactly 30 days later; it opens in `ACTIVE` status. Two counters track consumption: `posts_used`, the number of posts created in the current period net of within-24-hour withdrawal refunds, and `searches_used_today`, the searches performed by this subscription's org on the current logical-clock day.

The `period_price_cents` is recomputed whenever the subscription is read and whenever `posts_used` or the plan changes. The base fee depends on the plan's `code`: 9900 cents for `BASIC`, 24900 cents for `PRO`, and 49900 cents for `ENTERPRISE`. Overage is the amount by which `posts_used` exceeds the plan's `monthly_posting_allowance`, floored at zero. Of those overage posts, the first ones up to the plan's `overage_tier1_limit` are billed at 150 cents each; any remainder beyond the tier-1 limit is billed at 300 cents each. An analytics add-on is then added: 0 cents for `NONE`, 2000 cents for `LANE_LEVEL`, and 5000 cents for `FULL`. The period price is the base plus both overage charges plus the add-on, all in integer cents.

The subscription lifecycle runs `ACTIVE` → `PAST_DUE` when a `PlatformAdmin` marks it past due, and `PAST_DUE` → `ACTIVE` when payment is recorded. If the logical clock reaches seven days past `period_end` while the subscription is still `PAST_DUE`, the system suspends it (`PAST_DUE` → `SUSPENDED`); recording payment on a `SUSPENDED` subscription returns it to `ACTIVE`. From `ACTIVE`, `PAST_DUE`, or `SUSPENDED`, cancellation lands the subscription in the terminal `CANCELLED` state. Each of mark-past-due, record-payment, and cancel increments `Subscription.version` by 1. Any operation that requires an active subscription — posting, booking, benchmark access — rejects a `PAST_DUE`, `SUSPENDED`, or `CANCELLED` subscription with `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409), and an org with no subscription where one is required yields `ERR_SUBSCRIPTION_NOT_FOUND`.

### 3.3. Posting Loads and Trucks

Posting is the heartbeat of the marketplace, and it is metered. Before any post is created, the acting org must be `ACTIVE`, hold an `ACTIVE` subscription, pass the authority and insurance checks of §3.1, and not be the target of any `CONFIRMED` fraud alert (such an org is rejected with `ERR_ORG_HAS_CONFIRMED_FRAUD`). The fiscal gate is a hard cap: a post may be created only while the subscription's `posts_used` is strictly less than the plan's `monthly_posting_allowance` plus its `overage_hard_cap`; when `posts_used` equals that sum, the create is rejected with `ERR_POSTING_QUOTA_EXCEEDED` (HTTP 402). A successful create increments `posts_used` by 1 on the acting org's active subscription.

A `BrokerAdmin` posts a load by supplying `origin` and `destination` market codes, an `equipment_type` of `DRY_VAN`, `REEFER`, or `FLATBED`, a pickup window `pickup_window_start` to `pickup_window_end`, and a `rate_offer_cents`. The pickup window is half-open — the start is inclusive, the end exclusive — and the start must be strictly before the end, otherwise `ERR_INVALID_REQUEST`. The load's `broker_org_id` is set from the acting admin's identity. New loads open with `status` `OPEN` and `visibility` `LISTED`. Status and visibility are independent parallel dimensions: a load is found in search only while `LISTED`, but its lifecycle (open, booked, completed, withdrawn, expired) advances regardless.

A `CarrierAdmin` posts a truck with `origin`, `destination`, `equipment_type`, and an availability window `available_from` to `available_until`, also half-open. A carrier may not hold two simultaneously available trucks whose windows overlap: a new truck is rejected with `ERR_TRUCK_WINDOW_OVERLAP` (HTTP 409) when any existing `AVAILABLE` truck of the same carrier has `available_from` strictly before the new `available_until` and `available_until` strictly after the new `available_from`. Adjacency is not overlap — a new truck whose `available_from` equals an existing truck's `available_until`, or whose `available_until` equals an existing `available_from`, is allowed. New trucks open in `AVAILABLE` status.

Time retires posts on its own. An `OPEN` load whose `pickup_window_end` has been reached becomes `EXPIRED`; an `AVAILABLE` truck whose `available_until` has been reached becomes `EXPIRED`. Both transitions fire eagerly when the clock is set and lazily when the record is read. Owners can also exit early: a `BrokerAdmin` may withdraw an `OPEN` load it owns, and a `CarrierAdmin` may withdraw an `AVAILABLE` truck it owns, in each case landing the post in `WITHDRAWN`. Withdrawing a load not in `OPEN` is rejected with `ERR_LOAD_POST_NOT_OPEN`; withdrawing a truck not in `AVAILABLE` is rejected with `ERR_TRUCK_POST_NOT_AVAILABLE`. An early exit is partially rewarded: when the logical clock at withdrawal is no more than 24 hours after the post's `created_at`, the owning subscription's `posts_used` is decremented by 1, refunding the post.

Search is metered separately from posting. Querying the load board accepts optional filters `origin`, `destination`, `equipment_type`, `pickup_on`, `status`, and `broker_org_id`. Every search performed by a `CarrierAdmin` caller increments `searches_used_today` on that carrier's subscription, and once the counter equals the plan's `search_daily_limit`, further searches that day are rejected with `ERR_SEARCH_LIMIT_EXCEEDED` (HTTP 402). Each returned load row is enriched with two trust signals from the posting broker: `broker_credit_badge`, the broker's current credit badge, and `broker_authority_status`, the broker's current authority verification status — so a carrier sees creditworthiness and authority inline, before committing a truck. Truck posts can likewise be listed with filters `carrier_org_id`, `origin`, `destination`, `equipment_type`, and `status`; truck listing does not consume search quota.

### 3.4. Booking and Completion

A booking marries one load to one truck. A `CarrierAdmin` creates it by supplying `load_post_id`, `truck_post_id`, and the negotiated `agreed_rate_cents`. The referenced load must be `OPEN` and currently `LISTED`, the referenced truck must be `AVAILABLE`, and both the carrier org and the posting broker org must pass the safety gate of §3.1 — a load whose broker sits under a `CONFIRMED` alert, or whose authority lapsed, cannot be booked. On creation the booking is `BOOKED`, and both sides move with it: the load transitions `OPEN` → `BOOKED` and the truck transitions `AVAILABLE` → `BOOKED`.

Completion belongs to the carrier side. When the acting `CarrierAdmin` owns the truck on a `BOOKED` booking, completing it moves the booking to `COMPLETED`, moves both posts to `COMPLETED`, and — critically — mints the system's most trusted rate data point: a `RateTransaction` with `source` `BOOKING`, `rate_kind` `SPOT`, the booking carrier as `reporter_carrier_org_id`, `rate_cents` equal to the booking's `agreed_rate_cents`, and `transaction_date` equal to the logical clock at completion. The booking's `rate_transaction_id` is set to point at this new record. A booking not in `BOOKED` rejects completion or cancellation with `ERR_BOOKING_NOT_ACTIVE`.

Cancellation is available to either party while the booking is `BOOKED`: the `CarrierAdmin` owning the truck side, or the `BrokerAdmin` owning the load side — an admin on neither side is rejected with `ERR_NOT_RESOURCE_OWNER`. Cancellation returns both posts to the market: the load goes back to `OPEN` with `visibility` restored to `LISTED`, and the truck goes back to `AVAILABLE`.

### 3.5. Rate Transactions and Lane Benchmarks

Beyond booking-derived transactions, both `BrokerAdmin` and `CarrierAdmin` may contribute transacted rates directly, each acting as the reporter for its own org: exactly one of `reporter_broker_org_id` or `reporter_carrier_org_id` is set, from the caller's identity. A contributed transaction carries `origin`, `destination`, `equipment_type`, a `rate_kind` of `SPOT` or `CONTRACT`, the all-in `rate_cents`, the `fuel_price_cents` (diesel price per gallon in cents on the transaction date), and the `transaction_date`. A transaction's `source` is either `BOOKING` (minted by booking completion) or `CONTRIBUTED` (reported directly); all transactions begin in `ACCEPTED` status. `DataOps` may exclude a transaction — moving it to `EXCLUDED` — when it is judged bad data; excluding an already-`EXCLUDED` transaction is rejected with `ERR_RATE_TRANSACTION_IMMUTABLE` (HTTP 409). Excluded transactions never feed benchmarks or contribution counts.

The lane rate benchmark is the platform's flagship analytic. A caller requests it with `origin`, `destination`, `equipment_type`, and a `variant`. Two variants exist, gated by the caller's plan. `SPOT_ONLY` requires at least `LANE_LEVEL` analytics depth and considers only `SPOT` transactions. `BLENDED` requires `FULL` depth, includes `CONTRACT` transactions at a discounted effective rate, and — when the caller's plan has `requires_data_contribution` — additionally requires the caller org's `data_contribution_flag` to be true, otherwise the request is rejected with `ERR_DATA_CONTRIBUTION_REQUIRED` (HTTP 403). Asking for a variant beyond the plan's `analytics_depth` — for example `BLENDED` on a `LANE_LEVEL` plan, or any benchmark on a `NONE` plan — is rejected with `ERR_ANALYTICS_DEPTH_FORBIDDEN` (HTTP 403).

Candidate transactions are those matching the requested `origin`, `destination`, and `equipment_type`, in `ACCEPTED` status, with `transaction_date` within the inclusive window from 30 days before the logical clock through the clock itself. In the `BLENDED` variant, each `CONTRACT` row's effective rate is its `rate_cents` multiplied by 0.95, rounded half-up; `SPOT` rows keep their `rate_cents` as the effective rate. If fewer than 5 candidates remain, the request is rejected with `ERR_INSUFFICIENT_BENCHMARK_DATA` (HTTP 422).

The computation proceeds in a pinned order that must not be rearranged. First, for each transaction, a fuel surcharge percentage is derived from its `fuel_price_cents`: starting from a base diesel price of 300 cents per gallon, each full 25-cent step above the base adds one percentage point of surcharge — steps below the base count as zero — and the percentage is capped at 20 percent. The surcharge portion of that transaction's effective rate is the effective rate multiplied by this percentage, rounded half-up to integer cents; the remainder is the transaction's linehaul. Second, the linehaul values are sorted ascending and percentiles are taken by nearest rank: the k-th percentile is the element at the 1-indexed position given by rounding up k percent of the sample size. Third, the fuel-adjusted median is produced by taking the median fuel price of the sample set — the element at the position obtained by rounding up half the sample size, of the fuel prices sorted ascending — computing the surcharge percentage for that median fuel price, and adding to the 50th-percentile linehaul a surcharge equal to the 50th-percentile linehaul multiplied by that percentage, rounded half-up to integer cents. The response reports the `lane_key`, the `sample_count`, the `p25_linehaul_cents`, `p50_linehaul_cents`, and `p75_linehaul_cents`, the `fuel_adjusted_p50_cents`, and the `variant` that was computed.

### 3.6. Data Contribution as a Membership Obligation

The `data_contribution_flag` on each broker and carrier org answers a simple question: has this org given back enough data to deserve the deepest analytics? The flag is recomputed on every rate-transaction create or exclude, and whenever the org is read. An org qualifies when the number of `ACCEPTED` rate transactions it reported — booking-derived or contributed — with `transaction_date` inside the inclusive trailing 30-day window ending at the logical clock is at least 10. Exactly 10 qualifies; 9 does not. `EXCLUDED` transactions never count, so a `DataOps` exclusion can flip an org's flag from true to false, cutting off `BLENDED` benchmark access on contribution-gated plans at the next request.

### 3.7. Broker Credit: Reporting, Scoring, and Disputes

Carriers experience broker payment behavior first-hand, and the platform turns those experiences into a credit file. A `CarrierAdmin` reports a payment experience on a broker by supplying the `broker_org_id` being reported on, the `invoice_amount_cents`, and the `days_to_pay` — the days from invoice to payment. The reporting carrier is recorded as the event's `carrier_org_id` from the acting admin's identity, and `reported_at` captures the logical clock at creation. New events are `PUBLISHED`. Filing an event recomputes the broker's credit fields, but — importantly — creation alone never suspends a broker, no matter how bad the numbers look.

The broker credit score is rebuilt from included events only: those `PUBLISHED` events whose `reported_at` falls within the inclusive trailing 365-day window ending at the logical clock. `UNDER_DISPUTE` and `REMOVED` events are excluded. Two averages are maintained: `days_to_pay_simple`, the unweighted mean of `days_to_pay` over included events, and `days_to_pay_weighted`, the invoice-amount-weighted mean — the sum over included events of each `days_to_pay` multiplied by its `invoice_amount_cents`, divided by the sum of `invoice_amount_cents`. Both averages are carried to 4 decimal places with half-up rounding, and are null when no events are included. The broker record also tracks `credit_event_count` (events in `PUBLISHED` or `UNDER_DISPUTE` status), and three ledger sums: `included_amount_cents` over `PUBLISHED` events, `under_dispute_amount_cents` over `UNDER_DISPUTE` events, and `removed_amount_cents` over `REMOVED` events.

Variant selection is by sample size: with 5 or more included events the weighted average governs; with fewer than 5 the simple average governs — so an identical event list can produce different scores depending on whether invoice amounts differ. With zero included events the broker sits at the starting position of `credit_score` 70 and `credit_badge` `STANDARD`. Otherwise, the raw score starts at 100 and loses 2 points for every day the selected average exceeds 30, never gaining points for faster payment. Confidence scales with evidence: it is the included-event count divided by 10, capped at 1. The final score is 70 plus the gap between the raw score and 70 multiplied by confidence, rounded half-up, then clamped into the 0-to-100 range. The badge bands are: `GOLD` at 80 or above, `STANDARD` at 60 or above, `WATCH` at 40 or above, and `CRITICAL` below 40. Crossing below 40 matters enormously — but the auto-suspension that it triggers is evaluated only on dispute-resolution recomputes and on fraud-alert confirmation, never on event creation.

A broker that disputes a reported event acts within 90 days of the event's `reported_at`; filing later is rejected with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422). Filing requires the event to be `PUBLISHED` — disputing an event in any other status is rejected with `ERR_CREDIT_EVENT_NOT_PUBLISHED` — and the acting `BrokerAdmin` must be the broker named on the event, else `ERR_NOT_RESOURCE_OWNER`. The filing supplies a `reason` and lands the dispute in `FILED`; the event simultaneously moves to `UNDER_DISPUTE`, and the broker's credit fields are recomputed with that event excluded — with no auto-suspension attached to this recompute.

The dispute then alternates between the analyst and the broker. A `ComplianceAnalyst` starts review, moving `FILED` → `UNDER_REVIEW`. The broker may rebut — `UNDER_REVIEW` → `REBUTTED` — supplying a `rebuttal_note`, but at most twice per dispute: a third attempt is rejected with `ERR_REBUTTAL_LIMIT_EXCEEDED`, and each accepted rebuttal increments `rebuttal_count` by 1. The analyst may return a `REBUTTED` dispute to `UNDER_REVIEW` for another look. From `FILED`, `UNDER_REVIEW`, or `REBUTTED`, the analyst resolves the dispute in one of two directions, supplying an `outcome`. A `SUSTAIN` outcome lands the dispute in `RESOLVED_SUSTAIN` and returns the event to `PUBLISHED`, recomputing the broker's credit fields with the event included again. A `REMOVE` outcome lands the dispute in `RESOLVED_REMOVE` and moves the event permanently to `REMOVED`, recomputing the broker's fields with the event excluded for good — and this is the moment the floor falls out: if the recomputed `credit_score` is below 40, the broker org is suspended and the full suspension cascade of §3.8 fires. Attempting any dispute transition the current status does not permit is rejected with `ERR_DISPUTE_INVALID_STATE`.

### 3.8. Fraud Alerts and the Suspension Cascades

Fraud monitoring covers three schemes, spelled exactly: `DOUBLE_BROKERING`, `IDENTITY_SPOOFING`, and `CARGO_THEFT`. A `ComplianceAnalyst` opens an alert by supplying the `alert_type`, at least one of `target_broker_org_id` or `target_carrier_org_id` (an alert with neither target is rejected with `ERR_INVALID_REQUEST`), and an `evidence_note` summarizing the analyst's grounds. New alerts are `OPEN`. Dismissing an alert lands it in `DISMISSED` with no further effect. Confirming an alert lands it in `CONFIRMED` and suspends every targeted org, firing the full cascade described below. An org that is the target of a `CONFIRMED` alert is thereafter barred from posting and booking with `ERR_ORG_HAS_CONFIRMED_FRAUD`, and cannot be reinstated while any `CONFIRMED` alert still targets it.

Administrative suspension by a `PlatformAdmin` is the gentler instrument. Suspending a broker withdraws every one of its `OPEN` loads (status to `WITHDRAWN`) and delists every one of its `BOOKED` loads (visibility to `DELISTED`, lifecycle status unchanged, bookings untouched), and moves its `ACTIVE` subscription to `SUSPENDED`. Suspending a carrier withdraws every one of its `AVAILABLE` trucks and likewise suspends its `ACTIVE` subscription. In each case, the org itself becomes `SUSPENDED` and any operation requiring an active org is rejected with `ERR_ORG_NOT_ACTIVE`.

The fraud cascade — triggered when a `CONFIRMED` alert suspends an org — goes further. For a targeted broker, everything the administrative cascade does happens, plus: every `BOOKED` booking on one of the broker's loads is cancelled, and each such booking's truck (if itself `BOOKED`) is released back to `AVAILABLE`; additionally, every `ACCEPTED` rate transaction reported by that broker is moved to `EXCLUDED`. For a targeted carrier, the administrative cascade applies, plus: every `BOOKED` booking on one of the carrier's trucks is cancelled, and each such booking's load (if `BOOKED`) returns to `OPEN` with `visibility` restored to `LISTED`; and every `ACCEPTED` rate transaction the carrier reported is `EXCLUDED`. The credit-driven cascade — a broker suspended because a dispute-resolution recompute pushed its score below 40 — mirrors the fraud cascade's booking cancellations exactly, but deliberately does not exclude the broker's reported rate transactions: bad credit is not bad data.

Reinstatement is possible only while no `CONFIRMED` fraud alert targets the org. Reinstating a broker re-lists its loads that were delisted while `BOOKED` (visibility `DELISTED` → `LISTED`) and returns its `SUSPENDED` subscription to `ACTIVE`; reinstating a carrier returns its `SUSPENDED` subscription to `ACTIVE`. Withdrawn posts are not resurrected. Deactivation, from either `ACTIVE` or `SUSPENDED`, lands an org in the terminal `DEACTIVATED` state: it can no longer post, search, or be reinstated.

### 3.9. Inspecting the Record

Every aggregate is auditable through its constituent records. Rate transactions can be listed and filtered by `booking_id`, `reporter_broker_org_id`, `reporter_carrier_org_id`, `origin`, `destination`, `equipment_type`, `rate_kind`, or `status` — so a `DataOps` steward can, for instance, isolate every transaction minted by a particular booking. Credit report events can be listed by `broker_org_id`, `carrier_org_id`, or `status`; disputes can be listed by `credit_report_event_id` or `status`; bookings by `load_post_id`, `truck_post_id`, `rate_transaction_id`, or `status`; fraud alerts by `target_broker_org_id`, `target_carrier_org_id`, or `status`; and subscriptions by `plan_id`, `broker_org_id`, `carrier_org_id`, or `status`. Broker orgs and carrier orgs can be listed with an optional `status` filter. Reading a broker org always reflects a lazily recomputed view of its credit fields; reading a load post, truck post, or authority verification applies any pending lazy expiry before responding.

## 4. Endpoint Definitions

The table below is a navigational index only. Request payloads, response shapes, side effects, and preconditions are defined by the narratives in §2 and §3. Newly created resources are returned with HTTP 201; all other successful operations — reads, actions, state transitions — return HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; applies eager time-driven transitions | PlatformAdmin |
| POST | /broker-orgs | Create broker org | PlatformAdmin |
| GET | /broker-orgs | List broker orgs | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /broker-orgs/{id} | Get broker org (lazy credit recompute) | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /broker-orgs/{id}/suspend | Suspend broker org (administrative cascade) | PlatformAdmin |
| POST | /broker-orgs/{id}/reinstate | Reinstate broker org | PlatformAdmin |
| POST | /broker-orgs/{id}/deactivate | Deactivate broker org (terminal) | PlatformAdmin |
| POST | /carrier-orgs | Create carrier org | PlatformAdmin |
| GET | /carrier-orgs | List carrier orgs | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /carrier-orgs/{id} | Get carrier org | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /carrier-orgs/{id}/suspend | Suspend carrier org (administrative cascade) | PlatformAdmin |
| POST | /carrier-orgs/{id}/reinstate | Reinstate carrier org | PlatformAdmin |
| POST | /subscription-plans | Create subscription plan | PlatformAdmin |
| GET | /subscription-plans | List subscription plans | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /subscriptions | Create subscription for exactly one org | PlatformAdmin |
| GET | /subscriptions | List/filter subscriptions | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /subscriptions/{id} | Get subscription (period price recomputed) | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /subscriptions/{id}/change-plan | Change plan under optimistic concurrency | PlatformAdmin |
| POST | /subscriptions/{id}/mark-past-due | Move ACTIVE subscription to PAST_DUE | PlatformAdmin |
| POST | /subscriptions/{id}/record-payment | Move PAST_DUE or SUSPENDED subscription to ACTIVE | PlatformAdmin |
| POST | /subscriptions/{id}/cancel | Cancel subscription (terminal) | PlatformAdmin |
| POST | /load-posts | Post a load (consumes posting quota) | BrokerAdmin |
| GET | /load-posts | Search loads; CarrierAdmin searches consume daily limit | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /load-posts/{id} | Get load post (lazy expiry check) | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /load-posts/{id}/withdraw | Withdraw an OPEN load (owner broker; 24h refund rule) | BrokerAdmin |
| POST | /truck-posts | Post a truck (quota; window-overlap checked) | CarrierAdmin |
| GET | /truck-posts | List/filter truck posts | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /truck-posts/{id} | Get truck post (lazy expiry check) | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /truck-posts/{id}/withdraw | Withdraw an AVAILABLE truck (owner carrier; 24h refund rule) | CarrierAdmin |
| POST | /bookings | Carrier books a load | CarrierAdmin |
| GET | /bookings | List/filter bookings | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /bookings/{id} | Get booking | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /bookings/{id}/complete | Complete booking; emits a BOOKING rate transaction | CarrierAdmin |
| POST | /bookings/{id}/cancel | Cancel booking (either owning party) | CarrierAdmin, BrokerAdmin |
| POST | /rate-transactions | Contribute a transacted rate | BrokerAdmin, CarrierAdmin |
| GET | /rate-transactions | List/filter rate transactions | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /rate-transactions/{id} | Get rate transaction | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /rate-transactions/{id}/exclude | Exclude a transaction from benchmarks | DataOps |
| GET | /lane-rate-benchmarks | Computed lane benchmark (SPOT_ONLY or BLENDED) | BrokerAdmin, CarrierAdmin |
| POST | /credit-report-events | Carrier reports a payment experience on a broker | CarrierAdmin |
| GET | /credit-report-events | List/filter credit report events | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /credit-report-events/{id} | Get credit report event | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /credit-report-events/{id}/disputes | Broker disputes a credit report event | BrokerAdmin |
| GET | /credit-disputes | List/filter credit disputes | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /credit-disputes/{id} | Get credit dispute | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /credit-disputes/{id}/start-review | Move FILED or REBUTTED dispute to UNDER_REVIEW | ComplianceAnalyst |
| POST | /credit-disputes/{id}/rebut | Broker rebuttal (at most two per dispute) | BrokerAdmin |
| POST | /credit-disputes/{id}/resolve | Resolve dispute SUSTAIN or REMOVE | ComplianceAnalyst |
| POST | /authority-verifications | Submit authority and insurance windows for an org | BrokerAdmin, CarrierAdmin |
| GET | /authority-verifications/{id} | Get authority verification (lazy expiry check) | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /broker-orgs/{id}/authority-verifications | Authority verifications for a broker | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| GET | /carrier-orgs/{id}/authority-verifications | Authority verifications for a carrier | PlatformAdmin, ComplianceAnalyst, DataOps, BrokerAdmin, CarrierAdmin |
| POST | /authority-verifications/{id}/verify | Verify authority (PENDING or EXPIRED to VERIFIED) | ComplianceAnalyst |
| POST | /authority-verifications/{id}/revoke | Revoke authority (terminal) | ComplianceAnalyst |
| POST | /fraud-alerts | Open a fraud alert against a broker and/or carrier | ComplianceAnalyst |
| GET | /fraud-alerts | List/filter fraud alerts | PlatformAdmin, ComplianceAnalyst, DataOps |
| GET | /fraud-alerts/{id} | Get fraud alert | PlatformAdmin, ComplianceAnalyst, DataOps |
| POST | /fraud-alerts/{id}/confirm | Confirm alert; full suspension cascade on targets | ComplianceAnalyst |
| POST | /fraud-alerts/{id}/dismiss | Dismiss alert | ComplianceAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the canonical list of identifiers and statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_DATA_CONTRIBUTION_REQUIRED | 403 |
| ERR_ANALYTICS_DEPTH_FORBIDDEN | 403 |
| ERR_ORG_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_LOAD_POST_NOT_FOUND | 404 |
| ERR_TRUCK_POST_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_RATE_TRANSACTION_NOT_FOUND | 404 |
| ERR_CREDIT_EVENT_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_FRAUD_ALERT_NOT_FOUND | 404 |
| ERR_AUTHORITY_VERIFICATION_NOT_FOUND | 404 |
| ERR_ORG_NOT_ACTIVE | 409 |
| ERR_ORG_HAS_CONFIRMED_FRAUD | 409 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 409 |
| ERR_LOAD_POST_NOT_OPEN | 409 |
| ERR_TRUCK_POST_NOT_AVAILABLE | 409 |
| ERR_BOOKING_NOT_ACTIVE | 409 |
| ERR_CREDIT_EVENT_NOT_PUBLISHED | 409 |
| ERR_DISPUTE_INVALID_STATE | 409 |
| ERR_REBUTTAL_LIMIT_EXCEEDED | 409 |
| ERR_TRUCK_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_MC_NUMBER | 409 |
| ERR_DUPLICATE_DOT_NUMBER | 409 |
| ERR_AUTHORITY_NOT_VERIFIED | 409 |
| ERR_INSURANCE_NOT_VERIFIED | 409 |
| ERR_RATE_TRANSACTION_IMMUTABLE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_POSTING_QUOTA_EXCEEDED | 402 |
| ERR_SEARCH_LIMIT_EXCEEDED | 402 |
| ERR_INSUFFICIENT_BENCHMARK_DATA | 422 |
| ERR_INSURANCE_WINDOW_GAP | 422 |
| ERR_DISPUTE_WINDOW_EXPIRED | 422 |
