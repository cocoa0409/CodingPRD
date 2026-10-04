# Storefront Revenue Share Refund Key API — Product Requirements Document

## 1. Introduction

Running a digital games storefront means balancing three constituencies whose interests routinely collide: developers who want predictable onboarding, fair revenue share, and the freedom to distribute their own activation keys through third-party retailers; players who want a trustworthy refund policy and honest review scores; and the platform itself, which must keep gray-market key reselling, refund abuse, and review bombing from quietly hollowing out the catalog. This document specifies the API surface of that storefront, mounted under `/storefront`, covering developer onboarding with title registration, store-page review, and release scheduling; a tiered revenue-share engine in which a title's platform cut improves as its lifetime recognized revenue crosses fixed thresholds; a refund policy bounded by playtime and purchase age with cross-account abuse scoring; product key generation with free-key allowances and redemption velocity controls; regional pricing recommendations with currency conversion and deviation guards; early-access disclosure requirements; and a user review system with weighted scoring and review-bomb windowing, plus a community workshop with creator revenue sharing.

The system is built around an immediate-consistency model: every mutation that changes money, review scores, or abuse posture recomputes its derived values before the response returns, and several write paths are guarded by optimistic concurrency so that a client acting on a stale snapshot of a title is turned away rather than allowed to overwrite work it never saw. A logical clock governs all temporal reasoning — release scheduling, refund windows, abuse-score windows, review-bomb detection — so that behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist. `PlatformOps` is platform operations staff — onboarding, key-batch approval, logical clock control, and revenue adjustments. `Developer` is a game developer operating its own account and titles. `StoreReviewer` approves or rejects store-page submissions. `TrustSafety` handles refunds, moderation, and abuse control. `User` is a player account that purchases, refunds, reviews, redeems keys, and participates in the workshop. `Anonymous` is an unauthenticated caller with no permitted operations.

Role identity is bound to stored entities for exactly two roles. When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `DeveloperAccount`; ownership checks on any resource that chains back to a developer (titles, regional price overrides, key batches) compare the resource's `developer_account_id` lineage to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `User`, `X-User-ID` is the `id` of the acting `UserAccount`; ownership checks compare the resource's `user_account_id` or `creator_account_id` field to `X-User-ID`. When `X-User-Role` is `PlatformOps`, `StoreReviewer`, `TrustSafety`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

All list endpoints accept two optional query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Results are always sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether further results exist beyond the returned window.

### 2.4. The Logical Clock and Scheduled Releases

All temporal reasoning in the storefront — refund windows, abuse-score windows, review-bomb detection windows, release scheduling — is evaluated against a server-side logical clock, never against wall-clock time. Before any explicit clock call, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformOps`-only capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `now_iso8601`. Setting the clock has a sweeping side effect: every title in `RELEASE_SCHEDULED` whose `scheduled_release_at` is at or before the new logical time transitions to `RELEASED`, with `released_at` recorded as the scheduled instant rather than the sweep instant. The same sweep re-evaluates which review-bomb windows actively cover the new "now". This auto-release is also lazy: any read of, or action on, a `RELEASE_SCHEDULED` title whose scheduled instant has been reached releases it on the spot, so callers never observe an overdue title still holding `RELEASE_SCHEDULED`.

### 2.5. Common Resource Properties

Every persisted resource carries `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer starting at its initial value that increments by one on every mutation of that resource). No entity in this system is exempt from the common-fields set. Resources are related to one another only through identifier fields carried in payloads and URLs — for example a title declares its owning developer via `developer_account_id`, and a purchase declares its buyer via `user_account_id` — never through nested embedding.

### 2.6. Optimistic Concurrency Control

Three write paths require the caller to prove it has seen the current state of the parent title. Recording a manual revenue adjustment requires the non-optional field `expected_title_version` carrying the caller's last observed `version` of the title; if the title's current `version` has advanced — because a refund cascade, a purchase, or an earlier adjustment moved its recognized revenue — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Posting a review likewise requires `expected_title_version` matching the title's current `version`, so that a caller whose snapshot of the title's `review_bomb_flag` and off-topic posture predates an intervening removal, window creation, or score recompute is turned away with `ERR_STALE_VERSION` (HTTP 412). Creating a regional price override requires `expected_title_version` as well, since the recommendation its deviation is checked against derives from title state that may have moved; a mismatch yields `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here accept no version field at all.

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic. First comes authentication (missing or malformed headers yield `ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN`). Next, every identifier referenced in the path and body is resolved left-to-right in path order, and the first missing resource yields `ERR_NOT_FOUND`. Ownership for entity-backed callers is checked fourth (`ERR_NOT_OWNER`), state-transition validity fifth (a transition that does not exist from the resource's current state yields `ERR_INVALID_STATE`, HTTP 409), and optimistic concurrency sixth (`ERR_STALE_VERSION`). Field-level request validity comes seventh — missing required fields, bad types, out-of-range enums, empty strings, and numeric bounds all yield `ERR_INVALID_REQUEST` (HTTP 400). Only after all of those do the business gates fire, in their own relative order: developer-account activity (`ERR_DEVELOPER_NOT_ACTIVE`), user-account activity (`ERR_ACCOUNT_RESTRICTED`), temporal schedule rules (`ERR_INVALID_SCHEDULE`), early-access disclosure (`ERR_MISSING_DISCLOSURE`), the one-open-review rule (`ERR_REVIEW_ALREADY_OPEN`), regional price deviation (`ERR_PRICE_DEVIATION`), override uniqueness (`ERR_OVERRIDE_EXISTS`), free-key allowance (`ERR_FREE_KEY_ALLOWANCE_EXCEEDED`), gray-market risk (`ERR_GRAY_MARKET_RISK`), redemption velocity (`ERR_REDEEM_VELOCITY`), refund window expiry (`ERR_REFUND_WINDOW_EXPIRED`), playtime limits (`ERR_PLAYTIME_EXCEEDED`), refund-abuse restriction (`ERR_REFUND_ABUSE`), refund amount bounds (`ERR_REFUND_AMOUNT`), the one-pending-refund rule (`ERR_REFUND_ALREADY_PENDING`), review ownership (`ERR_REVIEW_NOT_OWNED`), the recognized-revenue floor (`ERR_NEGATIVE_REVENUE`), workshop item purchasability (`ERR_ITEM_NOT_PURCHASABLE`), and finally uniqueness conflicts (`ERR_DUPLICATE`). One deliberate exception: the auto-decision refund policy is not an error path at all — a refund request whose policy evaluation fails is still created successfully and simply remains in `REQUESTED` awaiting manual review, returning HTTP 201.

### 2.8. Monetary Precision, Rounding, and Units

All money is stored and computed as integer minor units — cents for USD, EUR, GBP, and BRL; JPY has zero decimal places by convention but lives in the same integer field. Wherever a computation produces a fractional minor unit, the result is rounded half-up to the nearest integer unless a rule explicitly says otherwise; the workshop creator split is the one place a floor is used instead, and the revenue-share fee rounding order is pinned as described in §3.4. Review scores are integers in basis points between 0 and 10000, also rounded half-up. Datetimes are compared at second precision, and playtime is tracked as integer minutes.

## 3. Business Logic & Workflows

### 3.1. Developer Onboarding and Account Lifecycle

A developer enters the platform when a `PlatformOps` operator registers a developer account with a `company_name` and a `contact_email`. The contact email must be unique across all developer accounts; a duplicate is rejected with `ERR_DUPLICATE` (HTTP 409). The new account starts in `PENDING` status with `onboarding_fee_paid` and `bank_details_submitted` both false.

Before the account can go live, the developer itself records its onboarding progress through the payment-info capability, which accepts the optional flags `pay_fee` and `submit_bank_details` and sets `onboarding_fee_paid` and `bank_details_submitted` accordingly, incrementing the account's `version`. Activation is then performed by `PlatformOps`: moving an account from `PENDING` to `ACTIVE` requires both `onboarding_fee_paid` and `bank_details_submitted` to be true. Throughout this document, whenever a named state transition exists from the resource's current state but one of that transition's preconditions is not met — activation with an unpaid fee being the canonical example — the request is rejected with `ERR_INVALID_STATE` (HTTP 409), the same code used when the transition does not exist from the current state at all. A successful activation increments the account's `version`.

An `ACTIVE` developer account can be moved to `SUSPENDED` by `PlatformOps`. Suspension is deliberately blunt: every title of that developer currently in `RELEASED` or `RELEASE_SCHEDULED` cascades to `DELISTED`, and new purchases and key requests for all of the developer's titles are blocked while the suspension holds. Unsuspension returns the account from `SUSPENDED` to `ACTIVE`, but titles delisted by the suspension are not auto-restored — the developer must resubmit each affected title for store-page review and walk it back through the pipeline. Termination is the terminal act: from `PENDING`, `ACTIVE`, or `SUSPENDED` an account moves to `TERMINATED`, every non-`DELISTED` title of the developer cascades to `DELISTED`, and every `UNUSED` key in every batch the developer owns cascades to `REVOKED`. Each of these lifecycle operations increments the account's `version`.

### 3.2. Title Registration, Store-Page Review, and Release Scheduling

A developer registers a title by supplying its `developer_account_id` — which must be the caller's own account, or the request fails ownership with `ERR_NOT_OWNER` — together with a `title_name`, a `base_price_usd_cents` that must be greater than zero, and optionally `early_access` and `early_access_disclosure_text`. The title name must be unique among that developer's own titles; a clash is `ERR_DUPLICATE` (HTTP 409). New titles are born in `DRAFT` with `early_access_disclosure_text` defaulting to null. While a title remains in `DRAFT`, its developer may patch `title_name`, `base_price_usd_cents`, `early_access`, and `early_access_disclosure_text`; each successful patch increments the title's `version`. A patch attempted against a title that has left `DRAFT` is rejected with `ERR_INVALID_STATE`.

Submitting a title for review moves it from `DRAFT` to `PENDING_REVIEW` and is allowed only when the owning developer account is `ACTIVE` — otherwise `ERR_DEVELOPER_NOT_ACTIVE` (HTTP 409) — and when no other store-page review for the same title is currently `SUBMITTED`, since only one open review per title may exist; a second open review is rejected with `ERR_REVIEW_ALREADY_OPEN` (HTTP 409). The submission creates a `StorePageReview` whose `title_id` points at the title, whose `status` is `SUBMITTED`, whose `submitted_at` is the submission instant, and whose `submission_seq` is a per-title monotonically increasing sequence starting at 1, each new submission taking the prior count plus one.

A `StoreReviewer` then decides the open review. Approval requires the referenced review to still be `SUBMITTED`; it moves the review to `APPROVED` and the title from `PENDING_REVIEW` to `APPROVED`, incrementing both resources' `version`. Rejection likewise requires a `SUBMITTED` review, moves the review to `REJECTED`, and sends the title back to `DRAFT`, copying the payload's `review_notes` onto the title so the developer can see why it failed. Both paths increment the title's `version` as well as the review's.

From `APPROVED`, a title has three roads. Scheduling a release takes a `release_at` that must lie strictly after the current logical time — a `release_at` at or before now is rejected with `ERR_INVALID_SCHEDULE` (HTTP 422) — and moves the title to `RELEASE_SCHEDULED` with `scheduled_release_at` recorded. Cancelling a scheduled release returns the title from `RELEASE_SCHEDULED` to `APPROVED` and clears `scheduled_release_at`. Releasing immediately moves the title straight from `APPROVED` to `RELEASED` with `released_at` set to the current logical instant. When the logical clock reaches a scheduled title's `scheduled_release_at`, the title auto-releases — either lazily, the next time anyone reads or acts on the title, or eagerly during a clock-set sweep — and in that case `released_at` is recorded as the scheduled instant, not the sweep instant. Early access adds one gate on both release roads: a title whose `early_access` flag is true may not be scheduled or released while its `early_access_disclosure_text` is still null, and the attempt is rejected with `ERR_MISSING_DISCLOSURE` (HTTP 422).

Delisting is the developer's own takedown: from `APPROVED`, `RELEASE_SCHEDULED`, or `RELEASED` a title moves to the terminal `DELISTED`, new purchases and key requests for it are blocked, and every `UNUSED` key of the title cascades to `REVOKED`. A `RELEASED` title can also reach `DELISTED` without any developer action, through the suspension and termination cascades described in §3.1.

Beyond the lifecycle, a title carries a block of computed fields that are resolved on read: `current_tier`, `lifetime_recognized_revenue_usd_cents`, `lifetime_refund_events`, `refund_abuse_flag`, `review_score_bps`, `recent_review_summary`, and `review_bomb_flag`. Their derivations are spread across §3.4, §3.5, and §3.7. Separately, `PlatformOps` may record a manual revenue adjustment against a title by supplying a signed `delta_usd_cents`, a free-text `reason`, and the OCC field `expected_title_version` (see §2.6). The delta is added to the title's recognized revenue, but the adjustment is rejected with `ERR_NEGATIVE_REVENUE` (HTTP 422) whenever it would drive the title's recognized revenue below zero, and the title's tier is re-evaluated after the adjustment lands.

### 3.3. Pricing Resolution, Regional Overrides, and the Purchase Path

Every title declares a single USD list price, `base_price_usd_cents`. Prices in the other four supported storefront currencies — `EUR`, `GBP`, `JPY`, and `BRL` — are derived, not declared. The recommended price for a currency is the base USD price multiplied by that currency's FX rate and then by its purchasing-power multiplier, rounded half-up to integer minor units. The FX table converts one US dollar into the local currency: 0.92 for `EUR`, 0.79 for `GBP`, 149.50 for `JPY`, and 5.05 for `BRL`. The purchasing-power multipliers are 0.90 for `EUR`, 0.95 for `GBP`, 0.70 for `JPY`, and 0.50 for `BRL`. A pricing-recommendation read answers, for a requested `currency` (or all four currencies when the parameter is omitted), the `recommended_cents`, the `effective_cents` a buyer would actually be charged, the `currency` itself, and the `usd_recognized_per_unit` — the USD value each unit sold in that currency contributes to the title's recognized revenue.

A developer who disagrees with a recommendation may set a regional price override by supplying `title_id`, `currency`, the override `price_cents` (which must be greater than zero), and the OCC field `expected_title_version` (§2.6). The override's `deviation_bps` is computed as the signed difference between the override price and the current recommendation, scaled to basis points of the recommendation and rounded half-up. As a gray-market control, an override whose absolute deviation exceeds 2500 basis points — twenty-five percent — is rejected with `ERR_PRICE_DEVIATION` (HTTP 422). Only one override per title and currency may be `ACTIVE` at a time; attempting a second yields `ERR_OVERRIDE_EXISTS` (HTTP 409). The owning developer account must be `ACTIVE` (`ERR_DEVELOPER_NOT_ACTIVE`), and a successful creation increments the title's `version`. An override is born `ACTIVE` and can later be withdrawn by its developer, moving it to `WITHDRAWN`, provided the owning title has not been delisted — withdrawal is permitted while the title is in `DRAFT`, `PENDING_REVIEW`, `APPROVED`, `RELEASE_SCHEDULED`, or `RELEASED`.

Effective price resolution is pinned. For a purchase in USD, the charged price is always exactly `base_price_usd_cents` — no FX, no overrides. For a purchase in another currency, an `ACTIVE` override for that title and currency wins; otherwise the recommended price is charged.

A player buys a title by supplying `user_account_id`, `title_id`, and `currency` (one of `USD`, `EUR`, `GBP`, `JPY`, `BRL`). The buyer's account must be `ACTIVE` — a `RESTRICTED` or `BANNED` account is rejected with `ERR_ACCOUNT_RESTRICTED` (HTTP 409) — and the title must be `RELEASED`; buying a title in any other state is rejected with `ERR_INVALID_STATE`. The purchase is created in `COMPLETED` status with `purchased_at` set to the current logical instant, `playtime_minutes` starting at 0, `refunded_cents` at 0, and `refunded_amount_usd_cents` at 0. Its `gross_price_cents` is the resolved price in the purchase currency's minor units, and its split into `platform_fee_cents` and `developer_share_cents` follows the tiered rule in §3.4. The purchase's `usd_recognized_cents` snapshot is the gross itself when the currency is USD, and otherwise the gross divided by the purchase-time FX rate, rounded half-up; that USD value is immediately added to the title's `lifetime_recognized_revenue_usd_cents`, the title's `current_tier` is re-evaluated, and the title's `version` increments. The buyer's `refund_abuse_score` is decremented by 1 on each completed purchase, floored at 0 (see §3.5). Owners record play by posting `minutes` against their own purchase — acting on someone else's purchase fails ownership with `ERR_NOT_OWNER` — and the minutes accumulate into `playtime_minutes`, incrementing the purchase's `version`.

### 3.4. Revenue Share Tiers and the Recognized-Revenue Ledger

The platform's cut of each sale shrinks as a title proves itself. A title's `current_tier` is re-derived from its `lifetime_recognized_revenue_usd_cents` after every mutation of that figure — purchase completion, refund cascade, or manual adjustment — by a descending threshold scan in which the first match wins. When the recognized revenue is at least fifty million dollars, the title sits in tier 3 and the platform rate is twenty percent. Below that, when the recognized revenue is at least ten million dollars, the title sits in tier 2 at a twenty-five percent rate. Otherwise the title sits in tier 1 at a thirty percent rate. The thresholds are inclusive: recognized revenue of exactly ten million dollars earns tier 2. There is no hysteresis — the tier is fully re-derived each time, so a refund that drags recognized revenue back below a threshold degrades the tier, and a title that climbs to tier 3 can fall back to tier 2.

Each purchase is split between platform and developer using the tier rate in force at purchase time. The pinned split mode is developer-first: the platform fee is the gross price multiplied by the current tier rate, rounded half-up to integer minor units, and the developer's share is the gross minus that rounded fee. (An alternative platform-first mode exists — fee rounded first, developer taking the remainder — which differs by exactly one cent from the developer-first split whenever the unrounded fee has a fractional part; it is not the configured mode.) So `platform_fee_cents` plus `developer_share_cents` always reconstructs `gross_price_cents` exactly.

The title's revenue ledger distinguishes two metrics that deliberately diverge. Recognized revenue — the figure that drives tier evaluation — rises by a purchase's `usd_recognized_cents` at completion, falls by the USD value of each approved refund (partial refunds subtract only the refunded part, so the retained part keeps counting), and moves by the signed `delta_usd_cents` of manual adjustments, subject to the floor that recognized revenue may never go below zero (`ERR_NEGATIVE_REVENUE`). The gross-export view used for payout reporting is instead the sum of all completed purchase gross and is never decremented by refunds; after any refund the two metrics disagree by exactly the cumulative refunded USD.

A title's `refund_abuse_flag` turns true when its `lifetime_refund_events` is greater than zero and that count exceeds thirty percent of the title's lifetime completed sales (purchases in `COMPLETED` or `PARTIALLY_REFUNDED` status). The flag is recomputed whenever either side of the comparison changes, and it gates key-batch approval as described in §3.6.

### 3.5. Refund Policy and Abuse Scoring

A player requests a refund against one of their own purchases by supplying the `purchase_id`, a free-text `reason`, and optionally an `amount_cents`; an omitted or zero amount is treated as a request for the full remaining gross. The refund request records the `user_account_id` denormalized from the purchase. Several gates apply at creation. The buyer's account must be `ACTIVE`, or the request is rejected with `ERR_ACCOUNT_RESTRICTED`. An account whose `refund_restricted` flag is set is rejected with `ERR_REFUND_ABUSE` (HTTP 422). The requested amount must not exceed the purchase's `gross_price_cents` minus its already `refunded_cents`, and the purchase must be in `COMPLETED` or `PARTIALLY_REFUNDED` — a violation of either is `ERR_REFUND_AMOUNT` (HTTP 422). At most one refund request per purchase may be open: if another request for the same purchase is still `REQUESTED`, the new one is rejected with `ERR_REFUND_ALREADY_PENDING` (HTTP 409).

Every refund request then passes through the auto-decision policy. The policy approves when all of the following hold: the purchase is in `COMPLETED` or `PARTIALLY_REFUNDED`; the purchase's `playtime_minutes` is strictly below 120 — 119 minutes qualifies, 120 does not; the purchase is no older than fourteen days, with exactly fourteen days still qualifying; the requested amount is at least zero and no more than the remaining gross; the account's `refund_restricted` is false; and no other request for the purchase is open. When the whole policy passes, the new request is immediately `APPROVED`: its `approved_amount_cents` is set — a zero-amount request approving for the full remaining gross — its `decided_at` is stamped, and the purchase cascades as described below. When any policy clause fails, the request is still created and returned successfully (HTTP 201) but remains in `REQUESTED` for manual review; a failed auto-decision is never an error.

`TrustSafety` staff work the manual queue. (Player accounts themselves are registered by `PlatformOps` with a unique `email`; a duplicate email is rejected with `ERR_DUPLICATE`, and new accounts start `ACTIVE`.) Manually approving a request re-checks the same gates as hard errors: a request whose purchase is older than fourteen days is rejected with `ERR_REFUND_WINDOW_EXPIRED` (HTTP 422), and a request whose purchase has `playtime_minutes` of 120 or more is rejected with `ERR_PLAYTIME_EXCEEDED` (HTTP 422) — although `TrustSafety` may still deny such requests, and denial of an over-age purchase remains available, while the same `ERR_REFUND_WINDOW_EXPIRED` gate applies to denying a request on an over-age purchase. The account's `refund_restricted` flag and the amount bounds are likewise re-checked, surfacing `ERR_REFUND_ABUSE` and `ERR_REFUND_AMOUNT` respectively. Denial takes a `decision_reason` from the payload and moves the request to `DENIED`.

An approved refund cascades into the purchase and beyond. If the approved amount brings the purchase's cumulative `refunded_cents` to exactly its `gross_price_cents`, the purchase moves to the terminal `REFUNDED`; otherwise it moves to `PARTIALLY_REFUNDED` with `refunded_cents` increased by the approved amount. The USD value of the refunded portion — computed with the purchase-time FX rate, proportionally to `approved_amount_cents`, and accumulated into `refunded_amount_usd_cents` — is subtracted from the title's `lifetime_recognized_revenue_usd_cents`, and the title's `current_tier` is re-evaluated and may degrade. The title's `lifetime_refund_events` increments by one and its `refund_abuse_flag` is recomputed. On the buyer's side, the refund adds to the account's `refund_abuse_score`: one point per approved refund event, plus three further points when the refunded purchase's `playtime_minutes` is at least 120 — the over-limit case arises only through manual `TrustSafety` approval, since the auto policy would have declined it, and it is deliberately more expensive.

That score is a rolling figure over the trailing sixty days of the account's refund decisions and purchases: one point per approved refund, three extra per over-limit approved refund, minus one per completed purchase, floored at zero. Whenever the score rises above 3, the account automatically moves to `RESTRICTED` and its `refund_restricted` flag is set. `TrustSafety` may also restrict an account directly, with the same effect. Unrestricting an account clears `refund_restricted`, recomputes the score from the trailing window (floored at zero), and returns the account to `ACTIVE`. Banning moves an account from `ACTIVE` or `RESTRICTED` to the terminal `BANNED` and cascades every `PUBLISHED` review the account has authored to `REMOVED`, triggering the score recomputes of §3.7 for each affected title.

### 3.6. Activation Keys: Batches, Allowances, and Redemption

Developers distribute product keys through third-party retailers, and those sales carry no platform revenue share. A developer requests a key batch by supplying `title_id`, a `requested_quantity` between 1 and 10000, and a `free_keys_in_batch` count between 0 and the requested quantity; out-of-range values are `ERR_INVALID_REQUEST`. The owning developer account must be `ACTIVE` (`ERR_DEVELOPER_NOT_ACTIVE`). The batch is created in `REQUESTED`, and at that moment the server snapshots `free_key_allowance_at_request` as the larger of 5000 and the title's lifetime completed sale count — purchases in `COMPLETED` or `PARTIALLY_REFUNDED`, with `REFUNDED` purchases no longer counting. Later sales do not retroactively enlarge an old batch's snapshot.

`PlatformOps` approves or rejects the batch. Approval enforces four preconditions: the title must be `RELEASED`; the title's `refund_abuse_flag` must be false — a gray-market control whose violation is rejected with `ERR_GRAY_MARKET_RISK` (HTTP 422); the free keys granted so far across the title's already-`APPROVED` batches plus this batch's `free_keys_in_batch` must not exceed the batch's snapshotted allowance — a violation is `ERR_FREE_KEY_ALLOWANCE_EXCEEDED` (HTTP 422); and the owning developer account must still be `ACTIVE`. On approval the server mints exactly `requested_quantity` keys, marks the first `free_keys_in_batch` of them (ordered by `created_at`) with `is_free` true, and records the minted count as the batch's `allocated_keys`. Each key carries its `batch_id`, a unique server-minted `key_code`, and starts life `UNUSED`. Rejection simply moves the batch to `REJECTED`.

A player redeems a key by presenting its `key_code`. Redemption requires the key to be `UNUSED`, the key's title to be `RELEASED`, the key's owning developer account to be `ACTIVE`, and the redeeming account to be `ACTIVE`; failures of these are rejected with `ERR_KEY_NOT_REDEEMABLE` (HTTP 409), except the account check, which surfaces `ERR_ACCOUNT_RESTRICTED`. A velocity guard then applies as gray-market protection: within the trailing sixty minutes the redeeming account must have fewer than 3 successful redemptions, and across all accounts the trailing sixty minutes must show fewer than 50 successful redemptions — either breach is rejected with `ERR_REDEEM_VELOCITY` (HTTP 422). A successful redemption moves the key to `REDEEMED`, stamps `redeemed_by_account_id` and `redeemed_at`, and records ownership so the account may now review the title. Keys also move from `UNUSED` to `REVOKED` without any user action when their title is delisted or their developer is terminated (§3.1, §3.2).

### 3.7. Reviews, Scoring, and Review-Bomb Windows

A player reviews a title by posting `title_id`, `user_account_id`, an `is_positive` flag, a `body` of 1 to 8000 characters, and the OCC field `expected_title_version` (§2.6). The author must be `ACTIVE` (`ERR_ACCOUNT_RESTRICTED`), must own the review as their own (`ERR_NOT_OWNER`), and must hold a stake in the title — either a purchase in `COMPLETED` or `PARTIALLY_REFUNDED`, or a `REDEEMED` activation key; a review from an account with neither is rejected with `ERR_REVIEW_NOT_OWNED` (HTTP 422). Each account may publish at most one review per title; a repeat is `ERR_DUPLICATE` (HTTP 409). At posting, the author's current playtime is snapshotted into `author_playtime_minutes`, and the review is born `PUBLISHED`. If the review's `created_at` falls inside any active review-bomb window for the title, it is immediately marked `off_topic` — it still publishes, but never scores.

A title's `review_score_bps` aggregates its included reviews — those `PUBLISHED` and not `off_topic` — using playtime-weighted scoring, the pinned mode. Each review's weight is the floor of the square root of the author's snapshotted playtime minutes, with a minimum weight of 1 (so a zero-playtime review still counts once). The score is ten thousand times the total weight of positive reviews divided by the total weight of all included reviews, rounded half-up to an integer number of basis points. When no review qualifies, the score is null. (An unweighted mode, in which every review counts once regardless of playtime, exists but is not configured.) Alongside the score, `recent_review_summary` classifies the trailing thirty days — inclusive of now, exclusive of the instant thirty days earlier — over the same included set: the summary is `MOSTLY_POSITIVE` when the positive share is at least seventy percent, `MIXED` when it is at least forty percent but below seventy, and `MOSTLY_NEGATIVE` below that; an empty window yields null. Both figures are recomputed on every review publish, review removal, and bomb-window open or close.

Review-bomb detection runs on every review creation. Looking back over the trailing twenty-four hours inclusive of now, the system counts the title's `PUBLISHED` reviews created in that window and the subset with `is_positive` false. When at least 10 negative reviews have accumulated and the negative share reaches at least eighty percent — evaluated exactly, with the comparison holding whenever five times the negative count is at least four times the total — a review-bomb window opens. The new window's `start_at` is the `created_at` of the oldest negative review in the detection window (earliest first on ties), its `end_at` is seven days from now, it records the triggering negative count in `trigger_review_count`, and it is born `ACTIVE`. Window creation retro-marks every pre-existing review whose `created_at` falls inside the covered interval as `off_topic`, and the triggering review itself is marked too. While any `ACTIVE` window covers the present, the title's `review_bomb_flag` is true. Only one window per title may be `ACTIVE` at a time: a second trigger while one is open instead extends the existing window's `end_at` to seven days from now.

`TrustSafety` moderates. Removing a review moves it from `PUBLISHED` to `REMOVED` and recomputes the title's score and recent summary, incrementing both the review's and the title's `version`; banning an author cascades the same transition across all of their published reviews. Closing a window moves it from `ACTIVE` to `CLOSED`: if no other active window still covers the present, the title's `review_bomb_flag` clears, and the score and recent summary are recomputed — while the `off_topic` marks placed on reviews created inside the window are lifted, restoring them to scoring eligibility.

### 3.8. Workshop Items and Creator Revenue Sharing

Players create workshop content for released titles. Creating an item takes `title_id`, `creator_account_id`, an `item_name`, a `price_cents` in USD cents that must be greater than zero, and a `creator_share_bps` between 1 and 5000 — the creator's cut in basis points, at most fifty percent, with the platform taking the remainder. The creator must be the caller (ownership, `ERR_NOT_OWNER`) and `ACTIVE` (`ERR_ACCOUNT_RESTRICTED`). The item is born `PENDING`.

The creator alone may publish the item, and only while the host title is `RELEASED`; publishing by anyone else fails ownership, and publishing against a non-released title is rejected with `ERR_INVALID_STATE`. Removal moves an item from `PENDING` or `PUBLISHED` to `REMOVED` and is available to the creator themselves or to `TrustSafety` for any item.

A player buys a published workshop item by supplying `workshop_item_id` and `buyer_account_id`. The item must be `PUBLISHED` and its host title `RELEASED`; otherwise the sale is rejected with `ERR_ITEM_NOT_PURCHASABLE` (HTTP 422). The buyer's account must be `ACTIVE` (`ERR_ACCOUNT_RESTRICTED`). The sale's `gross_cents` is the item's price at sale time. The split rounds in a pinned order: the creator's share is computed first as the floor of the gross multiplied by the creator's basis points and divided by ten thousand, and the platform's share is whatever remains — so on a 999-cent item at 3333 basis points the creator receives 332 cents and the platform 667, never the other way around. These land in `creator_share_cents` and `platform_share_cents`, with `sold_at` stamped at the logical now. Each workshop sale, like each title purchase, decrements the buyer's `refund_abuse_score` by 1, floored at zero.

## 4. Endpoint Definitions

All endpoints live under `/storefront`. Endpoints that create a new resource respond with HTTP 201; endpoints that modify, transition, or read an existing resource respond with HTTP 200. Error responses follow §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /storefront/_clock/set_current_utc | Set the logical clock; sweeps due scheduled releases and re-evaluates bomb-window coverage | PlatformOps |
| POST | /storefront/developer-accounts | Register a developer account (PENDING) | PlatformOps |
| GET | /storefront/developer-accounts/{id} | Read a developer account | PlatformOps, Developer, StoreReviewer, TrustSafety |
| GET | /storefront/developer-accounts | List developer accounts (filterable by `status`) | PlatformOps, StoreReviewer, TrustSafety |
| POST | /storefront/developer-accounts/{id}/payment-info | Record onboarding fee payment and/or bank details | Developer |
| POST | /storefront/developer-accounts/{id}/activate | Activate a developer (fee paid and bank details required) | PlatformOps |
| POST | /storefront/developer-accounts/{id}/suspend | Suspend a developer; delists its released and scheduled titles | PlatformOps |
| POST | /storefront/developer-accounts/{id}/unsuspend | Unsuspend a developer (titles not auto-restored) | PlatformOps |
| POST | /storefront/developer-accounts/{id}/terminate | Terminate a developer; delists titles and revokes unused keys | PlatformOps |
| POST | /storefront/titles | Register a title (DRAFT) | Developer |
| GET | /storefront/titles/{id} | Read a title (computed fields resolved on read; lazy auto-release) | PlatformOps, Developer, StoreReviewer, TrustSafety, User |
| GET | /storefront/titles | List titles (filterable by `developer_account_id`, `status`) | PlatformOps, Developer, StoreReviewer, TrustSafety, User |
| PATCH | /storefront/titles/{id} | Update DRAFT title fields | Developer |
| POST | /storefront/titles/{id}/submit-review | Submit a title for store-page review | Developer |
| POST | /storefront/titles/{id}/schedule-release | Schedule a release (APPROVED to RELEASE_SCHEDULED) | Developer |
| POST | /storefront/titles/{id}/cancel-release | Cancel a scheduled release | Developer |
| POST | /storefront/titles/{id}/release-now | Release immediately | Developer |
| POST | /storefront/titles/{id}/delist | Delist a title; revokes its unused keys | Developer |
| POST | /storefront/titles/{id}/adjustments | Record a manual recognized-revenue adjustment (OCC) | PlatformOps |
| GET | /storefront/titles/{id}/pricing-recommendation | Recommended and effective price per currency | PlatformOps, Developer, StoreReviewer, TrustSafety |
| GET | /storefront/titles/{id}/reviews | List a title's reviews (filterable by `status`, `off_topic`) | PlatformOps, Developer, StoreReviewer, TrustSafety, User |
| GET | /storefront/titles/{id}/key-batches | List a title's key batches | PlatformOps, Developer |
| GET | /storefront/titles/{id}/workshop-items | List a title's workshop items | PlatformOps, Developer, TrustSafety, User |
| GET | /storefront/titles/{id}/review-bomb-windows | List a title's review-bomb windows | PlatformOps, Developer, TrustSafety |
| GET | /storefront/titles/{id}/regional-prices | List a title's regional price overrides | PlatformOps, Developer, StoreReviewer |
| GET | /storefront/titles/{id}/store-page-reviews | List a title's store-page reviews | PlatformOps, Developer, StoreReviewer |
| GET | /storefront/store-page-reviews | List store-page reviews (filterable by `title_id`, `status`) | PlatformOps, StoreReviewer |
| GET | /storefront/store-page-reviews/{id} | Read a store-page review | PlatformOps, StoreReviewer, Developer |
| POST | /storefront/store-page-reviews/{id}/approve | Approve a store page (title becomes APPROVED) | StoreReviewer |
| POST | /storefront/store-page-reviews/{id}/reject | Reject a store page (title returns to DRAFT with notes) | StoreReviewer |
| POST | /storefront/regional-prices | Create a regional price override (deviation guard; OCC) | Developer |
| GET | /storefront/regional-prices/{id} | Read a regional price override | PlatformOps, Developer, StoreReviewer |
| POST | /storefront/regional-prices/{id}/withdraw | Withdraw an override | Developer |
| POST | /storefront/key-batches | Request an activation key batch (allowance snapshotted) | Developer |
| GET | /storefront/key-batches/{id} | Read a key batch | PlatformOps, Developer |
| GET | /storefront/key-batches | List key batches (filterable by `title_id`, `status`) | PlatformOps |
| GET | /storefront/key-batches/{id}/keys | List keys minted in a batch | PlatformOps, Developer |
| GET | /storefront/keys/{id} | Read a single key | PlatformOps, Developer |
| GET | /storefront/keys | List keys (filterable by `batch_id`, `status`) | PlatformOps, Developer |
| GET | /storefront/user-accounts/{id}/keys | List keys redeemed by a user | PlatformOps, TrustSafety, User |
| POST | /storefront/key-batches/{id}/approve | Approve a batch; mints keys (gray-market and allowance guards) | PlatformOps |
| POST | /storefront/key-batches/{id}/reject | Reject a batch | PlatformOps |
| POST | /storefront/keys/redeem | Redeem a key by code (velocity guard) | User |
| POST | /storefront/user-accounts | Register a user account (ACTIVE) | PlatformOps |
| GET | /storefront/user-accounts/{id} | Read a user account | PlatformOps, TrustSafety, User |
| GET | /storefront/user-accounts | List user accounts (filterable by `status`) | PlatformOps, TrustSafety |
| POST | /storefront/user-accounts/{id}/restrict | Restrict an account (refunds blocked) | TrustSafety |
| POST | /storefront/user-accounts/{id}/unrestrict | Unrestrict an account | TrustSafety |
| POST | /storefront/user-accounts/{id}/ban | Ban an account; removes its published reviews | TrustSafety |
| GET | /storefront/user-accounts/{id}/purchases | List a user's purchases | PlatformOps, TrustSafety, User |
| GET | /storefront/user-accounts/{id}/reviews | List reviews authored by a user | PlatformOps, TrustSafety, User |
| POST | /storefront/purchases | Buy a title in a currency (pricing resolution, tiered split, ledger credit) | User |
| GET | /storefront/purchases/{id} | Read a purchase | PlatformOps, TrustSafety, User |
| GET | /storefront/purchases | List purchases (filterable by `title_id`, `user_account_id`, `status`) | PlatformOps, TrustSafety |
| POST | /storefront/purchases/{id}/playtime | Record play minutes (owner only) | User |
| POST | /storefront/refund-requests | Request a refund; auto-approved when the full policy passes | User |
| GET | /storefront/refund-requests/{id} | Read a refund request | PlatformOps, TrustSafety, User |
| GET | /storefront/refund-requests | List refund requests (filterable by `purchase_id`, `user_account_id`, `status`) | PlatformOps, TrustSafety |
| POST | /storefront/refund-requests/{id}/approve | Manually approve a refund (re-checks purchase state and remaining amount) | TrustSafety |
| POST | /storefront/refund-requests/{id}/deny | Manually deny a refund with a reason | TrustSafety |
| POST | /storefront/reviews | Post a review (ownership and OCC; triggers bomb detection) | User |
| GET | /storefront/reviews/{id} | Read a review | PlatformOps, Developer, TrustSafety, User |
| POST | /storefront/reviews/{id}/remove | Remove a review | TrustSafety |
| GET | /storefront/review-bomb-windows/{id} | Read a review-bomb window | PlatformOps, Developer, TrustSafety |
| GET | /storefront/review-bomb-windows | List review-bomb windows (filterable by `title_id`, `status`) | PlatformOps, TrustSafety |
| POST | /storefront/review-bomb-windows/{id}/close | Close a window; clears the bomb flag if it was the last | TrustSafety |
| POST | /storefront/workshop-items | Create a workshop item (PENDING) | User |
| GET | /storefront/workshop-items/{id} | Read a workshop item | PlatformOps, Developer, TrustSafety, User |
| GET | /storefront/workshop-items | List workshop items (filterable by `title_id`, `creator_account_id`, `status`) | PlatformOps, TrustSafety |
| POST | /storefront/workshop-items/{id}/publish | Publish an item (creator only; host title must be released) | User |
| POST | /storefront/workshop-items/{id}/remove | Remove an item (creator or TrustSafety) | User, TrustSafety |
| POST | /storefront/workshop-sales | Buy a workshop item (creator share floored first) | User |
| GET | /storefront/workshop-sales/{id} | Read a workshop sale | PlatformOps, TrustSafety, User |
| GET | /storefront/workshop-sales | List workshop sales (filterable by `workshop_item_id`, `buyer_account_id`) | PlatformOps, TrustSafety |
| GET | /storefront/user-accounts/{id}/workshop-sales | List workshop sales made by a buyer | PlatformOps, TrustSafety, User |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_NOT_OWNER | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DEVELOPER_NOT_ACTIVE | 409 |
| ERR_ACCOUNT_RESTRICTED | 409 |
| ERR_INVALID_SCHEDULE | 422 |
| ERR_MISSING_DISCLOSURE | 422 |
| ERR_REVIEW_ALREADY_OPEN | 409 |
| ERR_PRICE_DEVIATION | 422 |
| ERR_OVERRIDE_EXISTS | 409 |
| ERR_FREE_KEY_ALLOWANCE_EXCEEDED | 422 |
| ERR_GRAY_MARKET_RISK | 422 |
| ERR_REDEEM_VELOCITY | 422 |
| ERR_KEY_NOT_REDEEMABLE | 409 |
| ERR_REFUND_WINDOW_EXPIRED | 422 |
| ERR_PLAYTIME_EXCEEDED | 422 |
| ERR_REFUND_ABUSE | 422 |
| ERR_REFUND_AMOUNT | 422 |
| ERR_REFUND_ALREADY_PENDING | 409 |
| ERR_REVIEW_NOT_OWNED | 422 |
| ERR_NEGATIVE_REVENUE | 422 |
| ERR_ITEM_NOT_PURCHASABLE | 422 |
| ERR_DUPLICATE | 409 |
