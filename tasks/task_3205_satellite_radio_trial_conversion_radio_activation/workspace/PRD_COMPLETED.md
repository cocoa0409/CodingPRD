# Satellite Radio Trial Conversion & Radio Activation API — Product Requirements Document

## 1. Introduction

This document specifies a subscription-management platform for a satellite radio service provider in the mold of SiriusXM: a business in which the first subscription a vehicle ever hears is almost always a free trial, delivered at the dealership, and nearly every commercial decision afterwards is an exercise in converting that trial into a paid relationship without running afoul of automatic-renewal disclosure law. The system models the full loop — automaker data feeds that identify eligible radios at the point of vehicle sale, activation and deactivation commands dispatched over satellite and cellular bearer paths with bounded retry, trial-to-paid conversion marketing organized into sequenced offer campaigns, package tiering with channel entitlements and family multi-radio discounts, and the used-vehicle dealer programs that wake a dormant radio back up when a car changes hands.

Two regulatory and operational pressures shape the design more than any feature list does. First, automatic-renewal regulation: a paid subscription that will renew itself may not be charged, and in some flows may not even be cancelled, until the customer has been sent (and in some flows acknowledged) a renewal disclosure with sufficient lead time. The platform therefore treats disclosure as a first-class, dated, per-subscription artifact rather than a marketing email. Second, the physical radio: every entitlement decision ultimately has to materialize as a radio-frequency command the hardware can actually receive, on hardware generations that differ in whether they can hear a cellular path at all. Signals can fail, retry, exhaust, and be superseded, and the subscription state machine is deliberately coupled to signal acknowledgment rather than to API-call success.

A product manager reading this document should come away able to answer, for any subscription, four questions: what is the customer paying this term and why, what state is the radio in and how did it get there, what is the subscription allowed to do next, and what does the law require us to have told the customer before we bill them again. Engineers should treat the whole API as mounted under the `/api/v1` prefix and read §2 for the cross-cutting contracts before §3's workflow narratives.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two HTTP headers: `X-User-ID` and `X-User-Role`. The declared roles, spelled exactly as the server expects them, are `PlatformAdmin`, `AutomakerPartner`, `DealerPartner`, `Customer`, `RetentionAgent`, `SystemOperator`, and `Anonymous`. A request whose `X-User-Role` is missing or is not one of these values, or whose `X-User-ID` is missing for a role whose identity is entity-backed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The single exception to header enforcement is self-service customer registration, which is performed as `Anonymous` and requires no prior identity.

Identity semantics differ by role, and the difference is load-bearing for ownership checks:

- When `X-User-Role` is `AutomakerPartner`, `X-User-ID` is the `id` of the acting `Automaker`; the partner may only submit data feeds for its own automaker record.
- When `X-User-Role` is `DealerPartner`, `X-User-ID` is the `id` of the acting `Dealer`; used-vehicle reactivations are attributed to that dealer record.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` — most importantly `Subscription.customer_id` — compare the resource's foreign-key field to `X-User-ID`. A customer-scoped action (cancel, suspend, resume, save-offer acceptance, disclosure acknowledgment, or listing one's own subscriptions) performed against a subscription whose `customer_id` does not equal the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403).
- When `X-User-Role` is `PlatformAdmin`, `RetentionAgent`, or `SystemOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; these roles act across customers.
- When `X-User-Role` is `Anonymous`, no `X-User-ID` is required; the role exists solely to admit self-service customer registration.

`PlatformAdmin` configures all reference data (automakers, dealers, package tiers, subscription plans, offer campaigns) and drives dealer program enrollment. `AutomakerPartner` submits eligibility data feeds and registers vehicles and radios — a feed submitted against an automaker record other than the caller's own is rejected with `ERR_FORBIDDEN_OWNER`. `DealerPartner` runs the used-vehicle reactivation program. `Customer` manages its own subscriptions, disclosures, and save offers. `RetentionAgent` is the call-center role: it may cancel, suspend, resume, accept save offers, send disclosures, and re-enqueue replacement signals for any customer. `SystemOperator` runs the billing batch, dispatches signals, and acknowledges or fails them.

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

All list endpoints paginate through two query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100; `offset` defaults to 0 and counts records skipped from the start of the result set. Every list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`, where `total_count` is the size of the unpaginated result set and `has_more` indicates whether further records exist beyond the current page. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties among records created in the same logical instant broken by record `id`; several list endpoints additionally accept a `status` query parameter restricting results to that status, and the campaign-redemption list accepts a `customer_id` filter and the offer-step list accepts `plan_id` and `campaign_id` filters.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix — never a value supplied by the client, and never a compound or human-readable identifier. Most resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 at creation and increments by one on every mutation of that resource. `created_at` is fixed at creation and never changes; `updated_at` is refreshed on every mutation. The three-fractional-digit ISO 8601 UTC format (with a `Z` suffix) applies uniformly to every timestamp field the API serializes — `start_at`, `end_at`, `sent_at`, `due_before`, `acknowledged_at`, `next_retry_at`, `last_signal_at`, `redeemed_at`, `effective_at`, `cancel_requested_at`, `used_program_enrolled_at`, and the `api_request_timestamp` of §2.2 among them — and a nullable timestamp that has not been set serializes as null.

Three entity families are deliberately lighter-weight and carry only `id` and `created_at` — no `updated_at`, no `version`: `OfferRedemption`, `BillingLedgerEntry`, and `DisclosureRecord`. These are append-only records (a redemption, a ledger posting, a disclosure event), so there is nothing to mutate after creation and therefore nothing to version.

Certain string fields are unique across their entity type and a duplicate submission is rejected with `ERR_DUPLICATE` (HTTP 409): an automaker's `oem_code`, a dealer's `dealer_code`, a customer's `email`, a vehicle's `vin`, a radio's `esn`, a package tier's `code`, a subscription plan's `code`, an offer campaign's `code`, and the client-supplied `idempotency_key` on both `SignalCommand` and `BillingLedgerEntry`. For the two idempotency-scoped resources the rule is stronger than a plain conflict: when a create carries an `idempotency_key` that has already been used, the server does not fail — it returns the original command or entry that the key first produced, with the same 201 status the original creation returned. The `SignalCommand` idempotency surface is the retention requeue endpoint of §3.4 — internally enqueued commands carry no key — while ledger idempotency applies to internal postings, so two postings under the same key collapse to the first entry.

### 2.5. Monetary Precision and Rounding

All money in the system is integer cents. Every price field (`price_cents` on a plan, `current_term_price_cents` on a subscription, `redeemed_price_cents` on a redemption, `amount_cents` on a ledger entry, `flat_discount_cents` on an offer step) is a whole number of cents with no fractional component. Percentage discounts are expressed in basis points (`discount_pct_bps`, ranging from 0 to 10000, so 2500 basis points means a 25 percent discount).

Two rounding directions are pinned and must never be swapped. A percentage-discount step rounds **down** — the discount amount is the floor of the product of the base price and the basis-point rate divided by ten thousand. The family multi-radio discount, by contrast, rounds **up** — its amount is the ceiling of one quarter of the post-offer-discount price. Proration calculations (cancellation refunds and transfer credits) floor both of their divisions. The business rationale for the asymmetry is deliberate: promotional percentage discounts round in the platform's favor per cent, while the structural family discount rounds in the customer's favor per cent.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and they are the only two that take an expected-version field. Every other endpoint in the API accepts no version field at all.

Provisioning a trial subscription against a radio requires the request to carry `expected_radio_version`, the value of that radio's `version` as the client last observed it. If another writer has since advanced the radio's version — because a prior provisioning or a transfer-driven reassignment legitimately superseded the caller's view of which subscription anchors the radio — the request is rejected with `ERR_STALE_VERSION` (HTTP 412); a missing or non-integer `expected_radio_version` is likewise rejected with `ERR_STALE_VERSION`, and the client must re-read the radio before retrying.

Transferring a vehicle's ownership requires the request to carry `expected_vehicle_version`, the value of the vehicle's `version` as the client last observed it. A mismatch with the vehicle's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), as is a missing or non-integer `expected_vehicle_version`: a prior transfer or a feed-driven owner change has already reassigned subscriptions off the radio, and the stale transfer would double-reassign.

### 2.7. The Logical Clock and System-Driven Transitions

The platform runs on a logical clock, not wall-clock time. Before any operator call, the logical clock stands at exactly 2026-09-01T00:00:00Z and must never fall back to the host's wall clock. An administrative capability — restricted to `PlatformAdmin` and `SystemOperator` — sets the clock to a supplied `to_iso8601` instant and returns the resulting `now_iso8601`; a missing or malformed `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Advancing the clock is not a bookkeeping convenience; it re-evaluates every system transition whose precondition depends on the current time: subscriptions reach their `end_at` and expire or finalize, campaign windows open and close, and signal retry deadlines come due. Setting the clock therefore runs the same system-driven pass the billing batch performs (expiries, renewals through the disclosure gate, and cancel finalizations), though its response carries only `now_iso8601` and not the batch counts. Tests and operators drive time forward exclusively through this capability.

### 2.8. Signal Transport Discipline

Every entitlement change that must reach a physical radio is materialized as a `SignalCommand` with a `command_type` of `ACTIVATE`, `DEACTIVATE`, `SUSPEND`, or `RESUME`. The command's delivery `path` is computed at enqueue time from the radio's hardware generation: radios of generation `GEN2` or `GEN3` can be reached over `CELLULAR`, while `GEN1` radios can only be reached over `SATELLITE`. Dispatching a command whose path is `CELLULAR` to a `GEN1` radio is not permitted.

Retry behavior differs by bearer. A `CELLULAR` command retries with a base interval of 15 minutes; a `SATELLITE` command retries with a base interval of 60 minutes, because satellite transmission windows are scarce. In both cases the backoff is linear: after a failure, `next_retry_at` is set to the time of the last attempt plus the current `attempt_count` multiplied by the path's base interval. The attempt cap is 3 on both paths — `attempt_count` may range from 0 to 3 and never beyond.

Signals are dispatched per radio in strict first-in-first-out order: among non-terminal commands for the same radio, the one with the earliest `created_at` must be dispatched first, and a command may not be dispatched while an earlier-created command for the same radio is still in `QUEUED` or `SENT`. Because the logical clock can stand still across several enqueues, commands that share the same `created_at` instant are ordered by their enqueue sequence — the order in which the server accepted them — and that same enqueue order decides which command is "newer" for supersession. Coherence is preserved by supersession: when a newer command for the same radio arrives whose `command_type` contradicts a still-pending command — a `DEACTIVATE` enqueued after an `ACTIVATE`, for instance — the older pending command transitions to `SUPERSEDED` and only the newest survives — and "contradicts" here simply means a different `command_type`: a pending `ACTIVATE` is never superseded by a newer `ACTIVATE`, only by a newer command of another type.

### 2.9. Validation Order

When a request violates several rules at once, the checks are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication comes first: a missing or unknown role header or a missing identity for an entity-backed role yields `ERR_UNAUTHENTICATED` before anything else is examined; role permission for the endpoint is checked second (`ERR_UNAUTHORIZED`). Existence follows: every path-template identifier is resolved left to right (`ERR_NOT_FOUND`), then foreign keys supplied in the request body such as `plan_id`, `package_tier_id`, `vehicle_id`, `automaker_id`, and `offer_step_id` (`ERR_REFERENCE_NOT_FOUND`). State-legality is next (`ERR_INVALID_STATE` for a transition not declared from the current state), then ownership (`ERR_FORBIDDEN_OWNER`).

Only after those structural checks do the business rules fire, in this order: the regulatory renewal-disclosure gate (`ERR_RENEWAL_DISCLOSURE_REQUIRED`); the exhausted-signal block (`ERR_SIGNAL_EXHAUSTED_BLOCK`); uniqueness (`ERR_DUPLICATE`); trial eligibility (`ERR_RADIO_INELIGIBLE`); used-program enrollment (`ERR_DEALER_NOT_ENROLLED`); the trial-plan gate (`ERR_TRIAL_PLAN_REQUIRED`); the paid-plan gate (`ERR_PAID_PLAN_REQUIRED`); hardware compatibility (`ERR_HARDWARE_INCOMPATIBLE`); the campaign window (`ERR_CAMPAIGN_WINDOW`); campaign phase-window occupancy (`ERR_CAMPAIGN_OVERLAP`); offer step-up sequencing (`ERR_OFFER_SEQUENCE_VIOLATION`); offer eligibility and per-customer caps (`ERR_OFFER_INELIGIBLE`); the save-offer cap (`ERR_SAVE_CAP_REACHED`); optimistic-concurrency staleness (`ERR_STALE_VERSION`); and finally field-level format sanity — a `vin` of exactly 17 characters, a non-empty `esn`, a positive `term_length_days`, `discount_pct_bps` between 0 and 10000, `household_size` at least 1, and `model_year` at least 1990 — reported as `ERR_INVALID_REQUEST`. A campaign creation whose `window_end_at` is not strictly later than its `window_start_at` is also reported as `ERR_CAMPAIGN_WINDOW`. Campaign-activation preconditions — a `DRAFT` campaign with no `OfferStep`, a `PAUSED` campaign whose window has since closed, or an archive attempted while the window is still open and redemptions exist — are declared transitions of the campaign machine and are therefore reported as `ERR_INVALID_STATE`, not `ERR_CAMPAIGN_WINDOW`.

### 2.10. Common Lifecycle Semantics

When any mutating operation succeeds on a versioned resource, that resource's `version` increments by exactly one and its `updated_at` refreshes to the current logical time. Cascades propagate the same discipline: when a hold-like event changes a parent (a radio provisioned, a vehicle transferred, a subscription terminated), the parent's `version` and `updated_at` move even though the client never wrote to the parent directly. Enumerations throughout the API are case-sensitive and must be transmitted exactly as spelled in this document — status strings such as `ACTIVE`, `SUSPENDED`, `PENDING_ACTIVATION`, hardware generations `GEN1`, `GEN2`, `GEN3`, service modes `IN_VEHICLE`, `STREAMING_ONLY`, `BUNDLED`, term kinds `TRIAL`, `MONTHLY`, `ANNUAL`, and so on.

New resources are returned with HTTP 201; modifications to existing resources and all action endpoints return HTTP 200.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Automakers, Dealers, Tiers, and Plans

Everything in the platform hangs off four registries maintained by `PlatformAdmin`. An automaker is registered with a unique `oem_code`, a display `name`, and a `feed_contact_email` used for data-feed operations; its `status` begins as `ACTIVE` and may later move to `SUSPENDED`. A dealer is registered with a unique `dealer_code` and a display `name`, and likewise carries a `status` of `ACTIVE` or `SUSPENDED`. Whether a dealer participates in the used-vehicle reactivation program is captured by the boolean `used_program_enrolled`, which defaults to false; when enrollment happens — either at registration or through the dedicated enrollment action — the server stamps `used_program_enrolled_at` with the enrollment timestamp, and the enrollment action increments the dealer's `version` by one. A dealer that has never enrolled has `used_program_enrolled_at` null.

A package tier defines what a subscriber is entitled to hear. It has a unique `code`, a display `name`, a list `channel_entitlements` of entitled channel codes, a boolean `includes_streaming` (default false) declaring whether streaming access is bundled with the in-vehicle service, and a `min_hardware_generation` (default `GEN1`) naming the oldest radio hardware — ordered `GEN1` before `GEN2` before `GEN3` — that can carry the tier.

A subscription plan prices a tier. It carries a unique `code`, a `name`, the `package_tier_id` of the tier it sells, a `service_mode` of `IN_VEHICLE`, `STREAMING_ONLY`, or `BUNDLED`, a `term_kind` of `TRIAL`, `MONTHLY`, or `ANNUAL`, a positive `term_length_days`, a non-negative `price_cents` giving the gross term price before any discount, and an `auto_renew_default` (default true) that decides whether new paid subscriptions on the plan renew automatically unless the customer opts out. A plan flagged `is_trial` (default false) is special: trial plans have `term_kind` `TRIAL` and `price_cents` zero. The plan-kind gates are strict and symmetric — the trial-provisioning endpoints (direct trial provisioning, automaker data feeds, and used-dealer reactivations) each require a plan whose `is_trial` is true, rejecting a paid plan with `ERR_TRIAL_PLAN_REQUIRED` (HTTP 422), while direct purchase and offer redemption each require a plan whose `is_trial` is false, rejecting a trial plan with `ERR_PAID_PLAN_REQUIRED` (HTTP 422).

Customers self-register with an `email` unique across customers and a `full_name`; they may declare a `household_size`, which defaults to 1, must be at least 1, and later drives family-discount eligibility. A customer's `status` begins `ACTIVE` and may become `DEACTIVATED`.

### 3.2. Vehicles, Radios, and Trial Provisioning

A vehicle is registered by `PlatformAdmin`, `AutomakerPartner`, or `DealerPartner` with a 17-character `vin` unique across vehicles, the `automaker_id` of its manufacturer, a `model_year` no earlier than 1990, the `owner_customer_id` of the currently registered owner, and a `condition` of `NEW` or `USED`. A radio is registered against a vehicle with a unique, non-empty `esn` (its electronic serial number), the `vehicle_id` of the vehicle it is installed in, and a `hardware_generation` of `GEN1`, `GEN2`, or `GEN3`. That generation gates two things everywhere else in the system: whether the cellular signal path is available at all, and which package tiers the radio may carry. A radio's `activation_status` begins `UNREGISTERED`, and its `last_signal_at` stays null until the first signal acknowledgment.

Trial eligibility is a precise threshold rule, evaluated identically wherever a trial is provisioned. A radio is trial-eligible only when its `activation_status` is `UNREGISTERED` or `DEACTIVATED` **and** the count of non-terminal subscriptions attached to that radio is exactly zero — a single `PENDING_ACTIVATION` subscription is enough to block. Beyond the radio, the actor matters by vehicle condition: for a `NEW` vehicle the trial flows through the automaker feed, while for a `USED` vehicle the used-dealer trial requires an enrolled dealer as the actor — that door additionally requires the radio's `activation_status` to be `DEACTIVATED`, which the general trial-eligibility rule already enforces. Any trial provisioning against an ineligible radio is rejected with `ERR_RADIO_INELIGIBLE` (HTTP 422).

There are three doors into a trial. An `AutomakerPartner` submits a data feed against its automaker: a bulk request carrying `items`, where each eligible item yields a created trial subscription plus an enqueued `ACTIVATE` signal (and the radio's `version` increments by one per provisioned item), and each ineligible item is recorded in `results` with its rejection reason; the response summarizes `provisioned_count` and `rejected_count` rather than failing the batch wholesale. A direct provisioning against a specific radio carries `plan_id`, `customer_id`, and the OCC field `expected_radio_version` (see §2.6); on success it creates the trial subscription and increments the radio's `version` by one. A `DealerPartner` reactivates a `DEACTIVATED` radio at resale by supplying `radio_id`, `customer_id`, and `plan_id` — this door additionally requires `used_program_enrolled` to be true on the acting dealer, and an unenrolled dealer is rejected with `ERR_DEALER_NOT_ENROLLED` (HTTP 422). Only the dealer's own record may be used: a `DealerPartner` whose `X-User-ID` does not match the path dealer's `id` is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403). The hardware gate of §3.7 applies to all three trial doors: a trial plan whose tier's `min_hardware_generation` is newer than the radio's `hardware_generation` is rejected with `ERR_HARDWARE_INCOMPATIBLE` (HTTP 422).

Whichever door is used, the created subscription looks the same in outline: `kind` `TRIAL`, `status` `PENDING_ACTIVATION`, and an `origin` that records how it arrived — `OEM_FEED` for the automaker feed, `USED_DEALER` for dealer reactivation, or `WEB_SIGNUP` for customer-initiated direct provisioning (and likewise for any direct trial provisioned by `PlatformAdmin`, which takes no partner origin). An `ACTIVATE` `SignalCommand` is enqueued for the radio with its `path` computed per §2.8. The full origin vocabulary — `OEM_FEED`, `USED_DEALER`, `WEB_SIGNUP`, `CALL_CENTER`, `SAVE_ACCEPT`, and `TRANSFER_IN` — spans the other creation flows described below.

### 3.3. Direct Purchase and the Term Pricing Engine

A paid subscription is born when a `Customer` (or a `RetentionAgent` or `PlatformAdmin` acting for one) purchases a plan, supplying `customer_id`, `plan_id`, an optional `radio_id`, and an optional `auto_renew` override that defaults from the plan's `auto_renew_default`. The subscription's `kind` is derived by the system — `TRIAL` for trial plans, `PAID` for ordinary paid plans, `SAVE_OFFER` for subscriptions repriced through the retention save flow — and its `origin` on direct purchase is `WEB_SIGNUP` for a self-service customer, `CALL_CENTER` when a retention agent drives the purchase, and likewise `WEB_SIGNUP` when `PlatformAdmin` purchases on a customer's behalf. Its `start_at` is stamped at creation, with `end_at` computed as `start_at` plus the plan's `term_length_days` converted to seconds. Streaming-only subscriptions are the solitary exception to signal-mediated activation: a `STREAMING_ONLY` plan has no radio (`radio_id` stays null), no `SignalCommand` exists for it, and the subscription moves from `PENDING_ACTIVATION` to `ACTIVE` immediately upon creation when `start_at` is not in the future. In-vehicle and bundled plans instead wait for their `ACTIVATE` signal to be acknowledged, as §3.4 describes.

A paid creation on a `STREAMING_ONLY` plan ignores any supplied `radio_id` (the subscription is created with `radio_id` null), while a paid creation on an `IN_VEHICLE` or `BUNDLED` plan without a `radio_id` is rejected with `ERR_INVALID_REQUEST`. Every paid creation runs the term pricing engine, which is also re-run on save-offer acceptance for the next term, on every family-anchor recompute, and on renewal. The evaluation order is pinned to break the apparent circularity between the family anchor (which depends on price) and the price (which depends on the family discount):

1. The base is the plan's raw `price_cents`, before any discount.
2. The offer discount applies **first**: it is the floor of the base multiplied by the redeeming step's `discount_pct_bps` divided by ten thousand, followed by subtraction of the step's `flat_discount_cents`, with the total offer discount capped at the base and the result floored at zero.
3. The family discount applies **second**: when the subscription is not the customer's primary anchor, the customer's `household_size` is at least 2, and the primary anchor subscription is an `ACTIVE` or `SUSPENDED` paid subscription, the family discount is the ceiling of one quarter — 2500 basis points — of the base price after the offer discount, i.e. the ceiling of the post-offer price multiplied by 2500 and divided by ten thousand. Otherwise the family discount is zero.
4. The term price is the base minus the offer discount minus the family discount, floored at zero, and is stored as the subscription's `current_term_price_cents`.

The two rounding directions — floor on the percentage step, ceiling on the family step — are pinned and must not be swapped. When no offer redemption applies and the subscription is not family-eligible, the list-price variant holds: the term price is the plan's `price_cents` verbatim.

The family anchor itself is recomputed whenever any paid subscription of the customer is created, cancelled, expired, transferred, suspended, or resumed. The candidate set is the customer's subscriptions of `kind` `PAID` or `SAVE_OFFER` whose `status` is `ACTIVE`, `SUSPENDED`, or `CANCEL_SCHEDULED`. The anchor is the candidate whose plan has the highest base `price_cents`, with ties broken by the earliest `created_at`; the anchor's `is_primary_for_discount` becomes true and every other candidate's becomes false. Non-anchor candidates receive the 25 percent family discount when `household_size` is at least 2. When the anchor itself is cancelled, transferred, or expired, the next-highest subscription becomes the anchor and **loses** its discount — its price rises at next renewal — so an anchor change recomputes `current_term_price_cents` for every surviving paid subscription of that customer — with one deliberate carve-out: a `SAVE_OFFER` subscription's price is fixed at save-acceptance time for the term and is not re-derived by the family recompute, though its `is_primary_for_discount` flag still tracks the anchor.

A successful purchase posts a `CHARGE` entry to the subscription's billing ledger equal to the freshly computed `current_term_price_cents`, enqueues an `ACTIVATE` signal for in-vehicle and bundled plans, triggers the family recompute above, and — when the subscription is paid and `auto_renew` is true — moves `disclosure_state` from `NONE` to `REQUIRED`, because an auto-renewing paid subscription needs a renewal disclosure on file before it may be charged again.

### 3.4. The Signal Pipeline: Dispatch, Acknowledgment, Failure, and Exhaustion

A `SignalCommand` is created `QUEUED`, carrying the `radio_id` it targets, the `subscription_id` whose state it materializes, its `command_type`, the computed `path`, an `attempt_count` starting at 0, a `next_retry_at` that stays null until the first failure, and a client-supplied `idempotency_key`. Re-submitting a create with an `idempotency_key` already in use returns the original command rather than a duplicate.

A `SystemOperator` runs the batch dispatch, which dispatches every `QUEUED` command whose `next_retry_at` is null or already due (a `next_retry_at` exactly equal to now is due), honoring per-radio FIFO order by ascending `created_at` (with enqueue sequence breaking ties among commands created in the same logical instant, per §2.8), and reports `dispatched_count` and `superseded_count`; supersession itself happens at enqueue time, so the batch's `superseded_count` is always 0. A single command may also be force-sent directly, bypassing the FIFO queue order. Dispatch moves a command `QUEUED → SENT` and increments `attempt_count` by one. A command whose computed `path` is `CELLULAR` may not be dispatched for a `GEN1` radio. While a command for a radio sits in `QUEUED` or `SENT`, no later-created command for the same radio may jump the queue.

From `SENT` a command is either acknowledged or failed by the operator. Acknowledgment moves it `SENT → ACKED`, applies the command's effect to the radio per the radio lifecycle (an `ACTIVATE` registration sets `last_signal_at` to the acknowledgment time), and — when the command is an `ACTIVATE` for a subscription still `PENDING_ACTIVATION` — flips that subscription to `ACTIVE`, provided its `start_at` is not in the future. A `DEACTIVATE` acknowledgment moves the radio to `DEACTIVATED` when no *other* subscription in `ACTIVE` or `SUSPENDED` still references it; a `PENDING_ACTIVATION` subscription does not yet hold live service and therefore does not block deactivation — this is what lets the §3.10 `DEACTIVATED → REGISTERED` cycle run across owners even when a fresh trial is already waiting. Failure moves it `SENT → FAILED` and forks on the attempt budget: while `attempt_count` is below 3 the command is automatically requeued to `QUEUED` with `next_retry_at` set to the failure time plus `attempt_count` times the path's base interval; the moment `attempt_count` reaches 3 the command instead becomes terminal `EXHAUSTED`. `ACKED`, `EXHAUSTED`, and `SUPERSEDED` are the terminal states.

Exhaustion has a business consequence beyond the signal itself. A subscription with an `EXHAUSTED` command cannot be suspended and cannot be immediately cancelled — both actions are rejected with `ERR_SIGNAL_EXHAUSTED_BLOCK` (HTTP 409) — until a `RetentionAgent` re-enqueues a replacement signal, supplying a fresh `command_type` and `idempotency_key`; a requeue on a streaming-only subscription — which has no radio — is rejected with `ERR_INVALID_REQUEST`. The replacement is a brand-new `QUEUED` command; the exhausted one remains terminal history. The re-enqueue lifts the block left by prior `EXHAUSTED` commands of the same `command_type` on that subscription; an `EXHAUSTED` command of a different `command_type` keeps blocking until it is itself replaced by a matching re-enqueue. Supersession rounds out the machine: when a newer command for the same radio arrives with a contradictory `command_type`, any still-pending (`QUEUED` or `SENT`) older command moves to `SUPERSEDED`, so only the newest contradictory command survives.

### 3.5. The Subscription Lifecycle: Activation, Suspension, and Resumption

A subscription's `status` walks a wider vocabulary than the radio's: it begins `PENDING_ACTIVATION`, may become `ACTIVE`, `SUSPENDED`, or `CANCEL_SCHEDULED`, and ends in one of the terminal states `CANCELLED`, `EXPIRED`, or `TRANSFERRED_AWAY`. Any attempt to drive a transition that is not declared from the current state is rejected with `ERR_INVALID_STATE` (HTTP 409).

Activation is signal-mediated, as §3.4 covers: the linked `ACTIVATE` command reaching `ACKED` moves the subscription `PENDING_ACTIVATION → ACTIVE`, provided `start_at` has been reached. Two things happen on that activation worth restating here. The radio's `activation_status` becomes `REGISTERED` (from `UNREGISTERED` or `DEACTIVATED`) and its `last_signal_at` is set to the acknowledgment time. If the subscription is `PAID` with `auto_renew` true, `disclosure_state` becomes `REQUIRED`. And because a new paid subscription may be the customer's most expensive plan, the family anchor for the customer's other non-terminal paid subscriptions is recomputed at activation — the anchor may change.

Suspension moves `ACTIVE → SUSPENDED` at the request of the owning customer or a `RetentionAgent`. The request is rejected with `ERR_FORBIDDEN_OWNER` when a customer asks about someone else's subscription, and with `ERR_SIGNAL_EXHAUSTED_BLOCK` when any `EXHAUSTED` signal exists for the subscription. A successful suspension enqueues a `SUSPEND` signal and recomputes the customer's family discount. Only when that signal is acknowledged does the radio follow: its `activation_status` becomes `SUSPENDED`, but only if no other `ACTIVE` or `PENDING_ACTIVATION` subscription still references the radio.

Resumption moves `SUSPENDED → ACTIVE` under the same ownership rule, with one temporal precondition: the current time must still be earlier than `end_at` — a subscription at or past its term must expire, not resume, and a resume attempted at exactly `end_at` is rejected with `ERR_INVALID_STATE`. Resumption enqueues a `RESUME` signal, whose acknowledgment returns the radio's `activation_status` to `REGISTERED` and refreshes `last_signal_at`.

### 3.6. Cancellation, Refunds, and the Save-Offer Loop

Cancellation comes in two flavors, selected by the request's `effective_mode`, and both flavors are available from both `ACTIVE` and `SUSPENDED` (with one asymmetry: `PENDING_ACTIVATION` supports only the immediate flavor — an `END_OF_TERM` cancel from `PENDING_ACTIVATION` is rejected with `ERR_INVALID_STATE`, and any cancel from a terminal or `CANCEL_SCHEDULED` state is likewise `ERR_INVALID_STATE`).

An immediate cancellation (`effective_mode` `IMMEDIATE`) moves the subscription directly to `CANCELLED`. From `PENDING_ACTIVATION` it simply posts the refund computed by the cancellation rule — which is zero for a never-activated trial — and enqueues the `DEACTIVATE` signal whose acknowledgment deactivates the radio under the reference rule of §3.4; no ledger entry is posted for the zero-amount trial refund. From `SUSPENDED`, two extra guards apply: the exhausted-signal block of §3.4, and, for a `PAID` subscription with `auto_renew` true, a regulatory gate — the subscription's `disclosure_state` must already be `SENT` or `ACKNOWLEDGED`, and a missing disclosure is rejected with `ERR_RENEWAL_DISCLOSURE_REQUIRED` (HTTP 422). From `ACTIVE`, the same disclosure gate applies and the same error fires; the law does not permit silently immediate-cancelling an auto-renewing paid subscription whose renewal disclosure was never sent — the retention flow must disclose first. Successful immediate cancellation from `ACTIVE` or `SUSPENDED` posts a `PRORATION_CREDIT` ledger entry, enqueues a `DEACTIVATE` signal whose acknowledgment moves the radio to `DEACTIVATED` under the same §3.4 reference rule, and recomputes the family discount for the customer's surviving paid subscriptions.

An end-of-term cancellation (`effective_mode` `END_OF_TERM`) moves `ACTIVE` or `SUSPENDED` to `CANCEL_SCHEDULED`. It stamps `cancel_requested_at` with the request time, forces `auto_renew` to false, and posts no refund — service continues until `end_at`. Finalization is system-driven: once the logical clock reaches `end_at`, the billing batch (or a clock advance) moves `CANCEL_SCHEDULED → CANCELLED`, enqueues the `DEACTIVATE` signal with the same radio side effect, and recomputes the family discount.

The cancellation refund rule is pinned to floor arithmetic, and an alternative ceiling-based reading is explicitly not the API's behavior. The unused time is the whole number of days between the cancellation time and `end_at` — the difference in seconds divided by 86400, floored. The refund is the subscription's `current_term_price_cents` multiplied by those unused days and divided by the plan's `term_length_days`, floored; a cancellation exactly at or after `end_at` refunds zero. Trials, at price zero, refund zero. The refund posts as a negative `PRORATION_CREDIT`, and only for `PAID` or `SAVE_OFFER` subscriptions.

The save-offer loop is the retention counter-move, and it is the platform's only cyclic subscription edge: accepting a save offer moves `CANCEL_SCHEDULED → ACTIVE`. The acceptance names an `offer_step_id` drawn from a campaign whose `lifecycle_phase` is `SAVE` and whose `state` is `ACTIVE`, and the requesting customer must own the subscription (or be a `RetentionAgent`). Two hard caps apply. The subscription's `save_offers_used_in_term` — counting accepted save offers in the current term, bounded from 0 to 2 — must still be below 2; a third acceptance in the same term is rejected with `ERR_SAVE_CAP_REACHED` (HTTP 422). And the step itself must pass the offer machinery of §3.7. On acceptance, `cancel_requested_at` is cleared back to null, `auto_renew` is restored to true, `kind` becomes `SAVE_OFFER` (the subscription's `origin` is recorded as `SAVE_ACCEPT`), and `save_offers_used_in_term` increments by one. The save price is prospective: `current_term_price_cents` is recomputed at the save offer's rate — the base plan price minus the step's offer discount (percentage floor then flat, per §3.3's step 2), with no family discount applied to the stored save price — for the **next** term while the current term's price is unchanged, an informational `SAVE_CREDIT` ledger entry records the next-term discount amount (base minus next-term price) as a negative amount, an `OfferRedemption` row is created recording the save-priced amount as its `redeemed_price_cents`, and — because the subscription now auto-renews on new terms — `disclosure_state` returns to `REQUIRED`, demanding fresh disclosure.

### 3.7. Offer Campaigns: Sequencing, Eligibility, and Redemption

Conversion marketing is organized into campaigns. A `PlatformAdmin` creates an `OfferCampaign` with a unique `code`, a `name`, a `lifecycle_phase` of `IN_TRIAL`, `POST_TRIAL`, `WINBACK`, or `SAVE`, and an inclusive window from `window_start_at` to `window_end_at` (both timestamps inclusive at redemption time); Creation itself requires the end to be strictly after the start, else `ERR_CAMPAIGN_WINDOW`; an unparseable or missing window timestamp is `ERR_INVALID_REQUEST`. A campaign begins in `DRAFT` and moves to `ACTIVE` through activation, which enforces three checks: the campaign must have at least one `OfferStep` (this has-steps requirement applies only to activation from `DRAFT` — reactivating a `PAUSED` campaign never re-checks step count); its `window_end_at` must still be strictly in the future (an `end_at` exactly equal to now blocks activation); and no other campaign in the same `lifecycle_phase` may already occupy the window. Occupancy uses half-open interval semantics — the candidate's `window_start_at` must be strictly before the incumbent's `window_end_at`, and the incumbent's `window_start_at` strictly before the candidate's `window_end_at`; windows that merely touch at a boundary do not overlap. Crucially, the occupancy set includes both `ACTIVE` **and** `PAUSED` campaigns — pausing a campaign does not free its phase-window — and a conflicting activation is rejected with `ERR_CAMPAIGN_OVERLAP` (HTTP 409). An `ACTIVE` campaign may move to `PAUSED` (while paused, redemptions against it are rejected), a `PAUSED` campaign may return to `ACTIVE` provided its window has not closed, and either `ACTIVE` or `PAUSED` may move to terminal `ARCHIVED` once the window has passed (current time strictly later than `window_end_at`) or the campaign still has zero redemptions; an archive attempted while the window is still open and the campaign has redemptions is rejected with `ERR_INVALID_STATE`.

Steps give a campaign its content. A step is added to a `DRAFT` or `PAUSED` campaign with a `step_index` (non-negative and unique within the campaign — on redemption the lowest eligible `step_index` wins), the `plan_id` it grants, a `step_up_rank` (default 0) that drives price step-up ordering, an optional `discount_pct_bps` between 0 and 10000 (default 0), an optional `flat_discount_cents` (default 0) applied after the percentage discount, an `eligibility_expr` predicate (default null when omitted), and a `max_redemptions_per_customer` cap (default 1). The eligibility predicate may declare a `min_household_size`, a `requires_streaming` flag, and `required_prior_offer_step_indexes` — an array of `step_index` values the same customer must already have redeemed within the same campaign. The `requires_streaming` flag holds when the customer has any non-terminal subscription whose plan's `service_mode` is `STREAMING_ONLY` or `BUNDLED`, or whose plan's tier sets `includes_streaming`. A step of `step_up_rank` 0 (the default) is always sequence-unconstrained, regardless of other ranks in the campaign.

Redemption is where a customer (or a `RetentionAgent` on the phone) converts, supplying `offer_step_id`, `customer_id`, and optionally `radio_id`; a `Customer` may redeem only for themselves. The guards fire in the order of §2.9: the campaign must be `ACTIVE` with the current time inside its inclusive window — a non-`ACTIVE` campaign (including `PAUSED`) or a time outside the window is `ERR_CAMPAIGN_WINDOW`; the step-up sequence must be respected — a step of `step_up_rank` R is redeemable only if every other step in the campaign with rank below R has already been redeemed by this customer (matched by its `step_index`) or fails its own eligibility expression (`ERR_OFFER_SEQUENCE_VIOLATION`, HTTP 422); and the step's own `eligibility_expr` must hold with its per-customer redemption cap not yet reached (`ERR_OFFER_INELIGIBLE`, HTTP 422). A successful redemption prices the step in isolation — floor of the plan's `price_cents` times `discount_pct_bps` over ten thousand, then minus `flat_discount_cents`, floored at zero, rounded per step and never summed-then-rounded — then feeds that discounted price into the term engine of §3.3, where any family discount applies on top. The result is persisted as an `OfferRedemption` recording the `campaign_id`, `offer_step_id`, `customer_id`, the `subscription_id` it created or repriced, the `redeemed_price_cents`, and an immutable `redeemed_at`. The recorded `redeemed_price_cents` is the created subscription's final `current_term_price_cents` after the family-anchor recompute the redemption triggers — the post-recompute term price with any family discount applied, not a pre-recompute intermediate. The redemption creates a `PAID` subscription on the supplied radio — or a streaming-only subscription when no radio is involved — with `origin` `WEB_SIGNUP` for a self-service customer or `CALL_CENTER` when a retention agent drove it, posts the `CHARGE` ledger entry, and recomputes the family discount. Because redemption creates a radio-backed subscription, the hardware gate applies: the plan's tier `min_hardware_generation` must be no newer than the radio's `hardware_generation`, else `ERR_HARDWARE_INCOMPATIBLE` (HTTP 422); `STREAMING_ONLY` plans are exempt because they touch no radio.

### 3.8. Renewal, Expiry, and the Disclosure Gate

The billing batch — run by a `SystemOperator` — processes everything due as of the current logical time and reports `expired_count`, `renewed_count`, `disclosure_blocked_count`, and `cancel_finalized_count`. Three kinds of work happen in one pass.

Subscriptions reach their end in one of two ways. An `ACTIVE` subscription whose time has come — `end_at` at or before now — expires — moving `ACTIVE → EXPIRED` — when it is a trial or has `auto_renew` false; expiry enqueues a `DEACTIVATE` signal (whose acknowledgment deactivates the radio under the §3.4 reference rule) and recomputes the family discount for the customer's surviving paid subscriptions. A `CANCEL_SCHEDULED` subscription finalizes to `CANCELLED` on the same clock condition — `end_at` at or before now — with the same side effects, as §3.6 describes.

An auto-renewing `PAID` or `SAVE_OFFER` subscription past its `end_at` does not expire — it renews in place, but only through the disclosure gate. The gate is a hard regulatory rule: renewal is forbidden unless a `DisclosureRecord` of type `RENEWAL_NOTICE` (or `SAVE_RENEWAL_NOTICE` for a `SAVE_OFFER` subscription) exists whose `sent_at` is no later than 15 days before the subscription's `end_at`. When the timely disclosure is missing, the subscription is neither renewed nor expired: it is left `ACTIVE` past its `end_at` in a regulatory limbo, with `disclosure_state` set to `REQUIRED`, until the disclosure is sent and a later billing run picks it up. The limbo exit is deliberately forgiving: once the current time is *strictly* later than `end_at`, a billing run treats any existing disclosure of the needed type as satisfying the gate — even one sent inside the 15-day lead window or during the limbo itself — while a subscription examined exactly at its `end_at` is still held to the timely-disclosure rule. Automatic renewal may not charge without timely disclosure. While a blocked subscription waits in limbo its `disclosure_state` stays (or is set back to) `REQUIRED`, even if a late disclosure was since sent; the state advances only through the ordinary send/acknowledge flow.

When the gate is satisfied, renewal recomputes the term price forward from current state: the offer discounts of the expiring term do **not** carry — promotions are one-term — while the family discount **does** carry, being structural. The new price becomes `current_term_price_cents`; `start_at` slides to the old `end_at` and `end_at` extends by another `term_length_days`; a `CHARGE` entry posts to the ledger; `save_offers_used_in_term` resets to 0 for the new term; and `kind` remains `PAID` or `SAVE_OFFER` as it was.

### 3.9. Disclosure Records and Acknowledgment

A disclosure is a dated compliance artifact on a subscription. Sending one — done by `RetentionAgent`, `PlatformAdmin`, or `SystemOperator` — names a `disclosure_type` of `RENEWAL_NOTICE`, `SAVE_RENEWAL_NOTICE`, or `TRIAL_END_NOTICE` and a `channel` of `EMAIL` or `POSTAL`. The record stamps `sent_at` at send time and computes `due_before` as the subscription's current `end_at` at send time; `acknowledged_at` stays null until the customer acknowledges. When the sent type matches the disclosure the subscription currently requires, the subscription's `disclosure_state` moves from `REQUIRED` to `SENT`. A `DisclosureRecord` is effectively a two-state record — created already sent, then acknowledged — rather than a machine with stored status enums.

Acknowledgment belongs to the customer alone: the owning customer acknowledges a specific disclosure on their subscription, the record's `acknowledged_at` is set to the acknowledgment time (acknowledging an already-acknowledged record is idempotent — `acknowledged_at` keeps its first value), and when every required disclosure for the subscription has been acknowledged, the subscription's `disclosure_state` advances to `ACKNOWLEDGED`. The full `disclosure_state` vocabulary is `NONE`, `REQUIRED`, `SENT`, and `ACKNOWLEDGED`, computed from the records rather than stored freehand.

### 3.10. Ownership Transfer and the Used-Vehicle Loop

When a vehicle changes hands, the platform treats the radio's entitlements as belonging to the seller, not the metal. A transfer request names the `new_owner_customer_id`, carries the OCC field `expected_vehicle_version` (see §2.6), and may optionally name a `used_dealer_id` and a `trial_plan_id`. A `Customer` may transfer only their own vehicle; `DealerPartner` and `PlatformAdmin` may also drive transfers — and may do so for any vehicle, not only ones tied to their own records. A supplied `trial_plan_id` must resolve to a plan whose `is_trial` is true, else `ERR_TRIAL_PLAN_REQUIRED`.

The transfer rewrites `owner_customer_id` to the new owner and increments the vehicle's `version` by one. Every `ACTIVE` or `CANCEL_SCHEDULED` subscription on the vehicle's radios moves `ACTIVE → TRANSFERRED_AWAY` (or from `CANCEL_SCHEDULED` to the same terminal state): a `DEACTIVATE` signal is enqueued revoking the old entitlement, and the old owner is credited for unused whole days — the same floor-based proration as cancellation, posting a negative `TRANSFER_ADJUSTMENT` entry per paid subscription (trials, at price zero, post no entry at all), with trials crediting zero. The old owner's family anchor is then recomputed, since a departing subscription may have been the anchor.

In the same request, each radio may immediately begin its next life: when `trial_plan_id` is supplied, a fresh `PENDING_ACTIVATION` trial is created per radio for the new owner and an `ACTIVATE` signal is enqueued. The fresh trial's `origin` is `USED_DEALER` when a `used_dealer_id` accompanied the transfer and `TRANSFER_IN` otherwise, and the new owner's family discount is recomputed as well. This is the loop that makes the used-vehicle program work: the radio's `activation_status` may cycle `DEACTIVATED → REGISTERED` again and again across owners — a `DEACTIVATED` radio is reactivatable by design — while each owner's subscriptions terminate cleanly rather than following the car. Each subscription also carries a `supersession_seq`, a monotone counter (starting at 0 for the first subscription on a `(radio_id, customer_id)` pairing) equal to the number of pre-existing subscriptions on the same pairing, used as a transfer tie-break after `created_at`; streaming subscriptions with no radio always carry 0.

### 3.11. The Billing Ledger

Every monetary event lands in an append-only `BillingLedgerEntry`: the `subscription_id` it belongs to, an `entry_type` of `CHARGE`, `PRORATION_CREDIT`, `REFUND`, `SAVE_CREDIT`, or `TRANSFER_ADJUSTMENT`, a signed `amount_cents` — charges positive, credits and refunds negative — an `effective_at` stamped at posting, a client-supplied `idempotency_key` unique across the ledger (a duplicate key returns the original entry), and a free-text `note`. The ledger is the system of record for the flows above: purchase and renewal `CHARGE` entries, immediate-cancel `PRORATION_CREDIT` entries, transfer `TRANSFER_ADJUSTMENT` credits, save-accept `SAVE_CREDIT` annotations, and refunds.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api/v1` prefix. Resource creation endpoints return HTTP 201 with the created resource; modifications, actions, and all reads return HTTP 200. Request and response bodies are not repeated here — the narrative of §2 and §3 defines them; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/v1/_clock/set_current_utc | Set the logical clock; re-evaluates all now-dependent system transitions | PlatformAdmin, SystemOperator |
| POST | /api/v1/_billing/run_renewals | Billing batch: expiries, auto-renewals with the disclosure gate, and cancel finalizations due as of now | SystemOperator |
| POST | /api/v1/_signals/dispatch | Dispatch all due QUEUED signal commands in per-radio FIFO order | SystemOperator |
| POST | /api/v1/_signals/{id}/force_send | Dispatch one signal command directly | SystemOperator |
| POST | /api/v1/automakers | Register an automaker | PlatformAdmin |
| GET | /api/v1/automakers/{id} | Get automaker | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/automakers/{id}/vehicles | List vehicles of an automaker | PlatformAdmin, AutomakerPartner, RetentionAgent, SystemOperator |
| POST | /api/v1/automakers/{id}/data-feeds | Automaker data feed: bulk-identify eligible radios and provision trials with per-item results | AutomakerPartner |
| POST | /api/v1/dealers | Register a dealer | PlatformAdmin |
| GET | /api/v1/dealers/{id} | Get dealer | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| POST | /api/v1/dealers/{id}/enroll-used-program | Enroll dealer in the used-vehicle reactivation program | PlatformAdmin |
| POST | /api/v1/dealers/{id}/used-reactivations | Reactivate a DEACTIVATED radio with a fresh trial for the resale buyer | DealerPartner |
| POST | /api/v1/customers | Register a customer (self-service; no auth) | Anonymous |
| GET | /api/v1/customers/{id} | Get customer | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/customers/{id}/api/v1/subscriptions | List subscriptions of a customer | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/customers/{id}/vehicles | List vehicles owned by a customer | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/customers/{id}/redemptions | List offer redemptions of a customer | PlatformAdmin, Customer, RetentionAgent |
| POST | /api/v1/package-tiers | Create a package tier | PlatformAdmin |
| GET | /api/v1/package-tiers/{id} | Get package tier | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/package-tiers/{id}/subscription-plans | List plans on a package tier | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| POST | /api/v1/subscription-plans | Create a subscription plan | PlatformAdmin |
| GET | /api/v1/subscription-plans/{id} | Get plan | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/subscription-plans/{id}/subscriptions | List subscriptions on a plan | PlatformAdmin, RetentionAgent, SystemOperator |
| POST | /api/v1/vehicles | Register a vehicle (VIN) for an owner customer | PlatformAdmin, AutomakerPartner, DealerPartner |
| GET | /api/v1/vehicles/{id} | Get vehicle | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/vehicles/{id}/api/v1/radios | List radios installed in a vehicle | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| POST | /api/v1/vehicles/{id}/transfer_ownership | Transfer vehicle ownership to another customer; reassigns radios' subscriptions (OCC-guarded) | PlatformAdmin, DealerPartner, Customer |
| POST | /api/v1/radios | Register a radio (ESN) installed in a vehicle | PlatformAdmin, AutomakerPartner |
| GET | /api/v1/radios/{id} | Get radio | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/radios/{id}/api/v1/subscriptions | List subscriptions tied to a radio | PlatformAdmin, AutomakerPartner, DealerPartner, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/radios/{id}/api/v1/signal-commands | List signal commands for a radio | PlatformAdmin, SystemOperator, RetentionAgent |
| POST | /api/v1/radios/{id}/trials | Provision a trial subscription on a radio (OCC-guarded on the radio's version) | PlatformAdmin, AutomakerPartner, DealerPartner, Customer |
| POST | /api/v1/subscriptions | Direct purchase of a paid or streaming-only subscription | Customer, RetentionAgent, PlatformAdmin |
| GET | /api/v1/subscriptions/{id} | Get subscription | PlatformAdmin, Customer, RetentionAgent, SystemOperator, DealerPartner, AutomakerPartner |
| GET | /api/v1/subscriptions/{id}/ledger | List billing ledger entries of a subscription | PlatformAdmin, Customer, RetentionAgent, SystemOperator |
| GET | /api/v1/subscriptions/{id}/disclosures | List disclosure records of a subscription | PlatformAdmin, Customer, RetentionAgent |
| POST | /api/v1/subscriptions/{id}/suspend | Suspend an active subscription | Customer, RetentionAgent |
| POST | /api/v1/subscriptions/{id}/resume | Resume a suspended subscription | Customer, RetentionAgent |
| POST | /api/v1/subscriptions/{id}/cancel | Cancel a subscription; IMMEDIATE refunds per proration, END_OF_TERM schedules at end_at | Customer, RetentionAgent |
| POST | /api/v1/subscriptions/{id}/save-offers/accept | Accept a SAVE-phase offer, reverting a scheduled cancel at a save rate for the next term | Customer, RetentionAgent |
| POST | /api/v1/subscriptions/{id}/disclosures/send | Send a renewal/save/trial-end disclosure to the customer | RetentionAgent, PlatformAdmin, SystemOperator |
| POST | /api/v1/subscriptions/{id}/disclosures/{disclosureId}/acknowledge | Customer acknowledges a disclosure | Customer |
| POST | /api/v1/subscriptions/{id}/signals/requeue | Retention re-enqueues a replacement signal after EXHAUSTED (clears the block) | RetentionAgent |
| POST | /api/v1/signal-commands/{id}/ack | Mark a SENT signal acknowledged by the radio | SystemOperator |
| POST | /api/v1/signal-commands/{id}/fail | Mark a SENT signal failed; requeues or exhausts per attempt_count | SystemOperator |
| GET | /api/v1/signal-commands/{id} | Get a signal command | PlatformAdmin, SystemOperator, RetentionAgent |
| GET | /api/v1/subscriptions/{id}/signal-commands | List signal commands for a subscription | PlatformAdmin, SystemOperator, RetentionAgent |
| GET | /api/v1/subscriptions/{id}/redemptions | List offer redemptions attached to a subscription (0..1) | PlatformAdmin, Customer, RetentionAgent |
| POST | /api/v1/offer-campaigns | Create a campaign (DRAFT) | PlatformAdmin |
| GET | /api/v1/offer-campaigns/{id} | Get campaign | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/offer-campaigns/{id}/steps | List steps of a campaign | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/offer-campaigns/{id}/redemptions | List redemptions of a campaign | PlatformAdmin, RetentionAgent |
| POST | /api/v1/offer-campaigns/{id}/steps | Add an offer step to a DRAFT or PAUSED campaign | PlatformAdmin |
| POST | /api/v1/offer-campaigns/{id}/activate | Activate a DRAFT or PAUSED campaign (overlap-checked) | PlatformAdmin |
| POST | /api/v1/offer-campaigns/{id}/pause | Pause an ACTIVE campaign | PlatformAdmin |
| POST | /api/v1/offer-campaigns/{id}/archive | Archive a campaign | PlatformAdmin |
| POST | /api/v1/offer-campaigns/{id}/redeem | Redeem a campaign offer for a customer: provisions the step's plan as a paid subscription (or converts the trial's radio) | Customer, RetentionAgent |
| GET | /api/v1/offer-steps/{id} | Get an offer step | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/offer-steps | List offer steps, filterable by plan | PlatformAdmin, Customer, RetentionAgent |
| GET | /api/v1/offer-steps/{id}/redemptions | List redemptions of an offer step | PlatformAdmin, RetentionAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_FORBIDDEN_OWNER | 403 |
| ERR_DUPLICATE | 409 |
| ERR_RADIO_INELIGIBLE | 422 |
| ERR_HARDWARE_INCOMPATIBLE | 422 |
| ERR_CAMPAIGN_WINDOW | 422 |
| ERR_CAMPAIGN_OVERLAP | 409 |
| ERR_OFFER_SEQUENCE_VIOLATION | 422 |
| ERR_OFFER_INELIGIBLE | 422 |
| ERR_SAVE_CAP_REACHED | 422 |
| ERR_RENEWAL_DISCLOSURE_REQUIRED | 422 |
| ERR_SIGNAL_EXHAUSTED_BLOCK | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DEALER_NOT_ENROLLED | 422 |
| ERR_TRIAL_PLAN_REQUIRED | 422 |
| ERR_PAID_PLAN_REQUIRED | 422 |
