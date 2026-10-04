# Streaming Bundle Entitlement API — Product Requirements Document

## 1. Introduction

The platform operates a duo streaming bundle spanning two distinct services, referred to throughout this document as `DPLUS` and `HULU`. A subscriber pays one biller and receives entitlements provisioned independently into each service, where each service keeps its own profile, parental controls, and watchlist. Around that core sit the hard problems of a bundled subscription business: migrating a legacy standalone subscriber into a bundle with correct proration and grandfathered pricing, reconciling tier combinations across ad-supported and ad-free plans when the two sides of an account disagree, honoring the constraints that app stores and distributors impose on upgrade and cancellation paths, applying retention discounts with duration and eligibility limits, and splitting every collected dollar between the two services for revenue reporting.

This document specifies the REST API that implements those behaviors. It is written for the engineer building the service: the global contracts in §2 are precise and non-negotiable, while the business behavior in §3 is presented as narrative workflows whose rules are distributed across the subsections where they naturally arise. All resources are mounted under the `/streaming` prefix. Billing runs, cancellations scheduled against period end, and retention expirations are all driven by a controllable logical clock rather than wall-clock time, so that the full lifecycle of a subscription can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, or the role value is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles, spelled exactly as the `X-User-Role` header value must present them, are `Anonymous`, `Subscriber`, `Support`, `DistributorOps`, and `PlatformAdmin`.

When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `SubscriberAccount`; ownership checks on any resource that references a `SubscriberAccount` compare the resource's foreign-key field to `X-User-ID`. A subscriber acting on a resource owned by a different account is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403). When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity — the `Anonymous` role exists solely to register a new subscriber account. When `X-User-Role` is `Support`, `DistributorOps`, or `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `Support` is a customer-service operator who may act on any account but may not create plans or offers nor drive the clock or renewals; `DistributorOps` manages distributor-billed subscriptions and likewise cannot create plans or offers or drive the clock; `PlatformAdmin` is the full operator whose permission set is a superset of every other role.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may be at most 100. `offset` defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope. Unless a subsection states otherwise, lists are sorted by `created_at` ascending.

### 2.4. Common Resource Properties

Every resource carries an `id` that is a server-minted UUID with no type prefix. Resources with full bookkeeping — `SubscriberAccount`, `ServiceProfile`, `BillingAccount`, `Subscription`, `Entitlement`, `Migration`, `RetentionRedemption`, and `Invoice` — additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at 1 and increments by 1 on every mutation of the resource. Configuration-style resources — `Plan`, `RetentionOffer`, `WatchlistItem`, and `RevenueAllocation` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock

The system never reads wall-clock time for business decisions. Instead it consults a logical clock whose startup default is exactly 2026-09-01T00:00:00Z; before any explicit advance, every time-sensitive rule evaluates against that default. A `PlatformAdmin` advances the clock by supplying a target instant `to_iso8601`. The clock is monotonic: attempting to set it to a timestamp earlier than the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Advancing the clock fires every transition gated on time — most importantly, a subscription in `CANCEL_SCHEDULED` whose `cancel_effective_at` has been reached finalizes to `CANCELLED`.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents; there are no fractional cents anywhere in the system. Proration divides a monthly price by whole days and rounds the per-day share down to the floor. Percentage discount caps are floored to integer cents. Revenue allocation rounds the non-remainder rows half-up to integer cents and lets the last row absorb the remainder so allocations always sum exactly to the collected amount.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client views with an explicit version handshake. A plan change against a subscription must carry `expected_subscription_version`, the value of the subscription's `version` the client last observed; if another writer has advanced the subscription's version since then — by applying a retention redemption, scheduling a cancellation, or completing an earlier plan change — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any side effect executes. Confirming a migration works the same way: the request must carry `expected_migration_version` equal to the migration's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. Nested Resource Resolution and Validation Order

Path-template resources are validated left to right: an account id is resolved before the profile id nested under it, the profile before the watchlist item, and the subscription before the redemption. The first unresolved segment fails the request with `ERR_NOT_FOUND` (HTTP 404). Identifiers referenced inside a request body — a `plan_code`, an `offer_code`, a profile id, a subscription id, or a billing account id — are checked after the path resolves; a body reference that does not exist fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

When several validation rules could reject the same request, they are evaluated in a fixed priority order: authentication and role authorization first, then subscriber ownership, then path existence, then body-reference existence, then resource state, then the requirement that the owning account be `ACTIVE`, then domain business rules (parental controls, uniqueness, plan shape, temporal windows, third-party billing constraints, retention eligibility, pricing floors), then referential preconditions such as account close and profile unlink, then request-shape validation, then the optimistic-concurrency version check, and finally the remaining business gates such as duplicate subscriptions, closed-account mutation, duplicate email, and legacy-plan purchase. A request that trips several rules surfaces the error of the earliest rule in this order.

### 2.9. Account, Profile, Entitlement: the Three-Tier Consistency Model

Access to a service is never granted to an account directly. A `SubscriberAccount` owns one `ServiceProfile` per service (at most one non-`UNLINKED` profile per (account, service) pair), and each `Entitlement` binds a `Subscription` to exactly one such profile. Every state change therefore propagates along the same chain: account to subscription to entitlement to profile. When the last `ACTIVE` entitlement on a profile disappears — by suspension, revocation, or cancellation — the profile itself drops from `LINKED` to `SUSPENDED`; when any entitlement on a suspended profile returns to `ACTIVE` and no other blocking condition holds, the profile rises back to `LINKED`. These bubble-up transitions are system-only and can never be invoked directly. Every mutation that results from such a cascade updates the affected resource's `updated_at` and increments its `version` as for any other mutation.

### 2.10. Billing Periods, Grace, and Failure Budget

Each `BillingAccount` runs a half-open billing period from `period_start` to `period_end`, with the end instant excluded. Period length depends on who collects the money: exactly 30 days for a `PLATFORM` biller, exactly 31 days for `APP_STORE` and `DISTRIBUTOR` billers. A subscription is due for renewal when the logical clock reaches or passes `period_end` — the boundary is closed at `period_end`.

A failed renewal is not immediately fatal. The account has a grace window of 7 days past `period_end` during which a retry that succeeds restores everything; at exactly 7 days past `period_end` the window is closed and retry is rejected with `ERR_GRACE_WINDOW_CLOSED` (HTTP 422). Consecutive failures are counted in `consecutive_failure_count`, which resets to 0 on any success; when a further failure would push that count to 3, the billing account hard-fails and the subscription is cancelled outright.

### 2.11. Closed Accounts Are Read-Only

Closing a subscriber account is a one-way terminal act. Once `account_status` is `CLOSED`, reads of the account's resources remain permitted but every mutating operation against resources owned by that account is rejected with `ERR_ACCOUNT_CLOSED` (HTTP 409). Closing is itself only possible once every subscription of the account has reached a terminal lifecycle — an attempt with any subscription still in `PENDING_ENTITLEMENT`, `ACTIVE`, `PAST_DUE`, or `CANCEL_SCHEDULED` is rejected with `ERR_ACTIVE_SUBSCRIPTIONS_REMAIN` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Plans: the Catalog Behind Everything

A `PlatformAdmin` authors the commercial catalog as `Plan` records. Each plan is identified by a unique `plan_code` (conventional examples are `DPLUS_ADS`, `DPLUS_PREMIUM`, `HULU_ADS`, `HULU_PREMIUM`, `DUO_ADS`, and `DUO_PREMIUM`) and declares a `plan_kind` of `STANDALONE` or `BUNDLE`, a `service_scope` drawn from the two services, an `ad_tier` of `AD_SUPPORTED` or `AD_FREE`, and a `monthly_price_cents` list price. The shape constraints differ by kind. A `BUNDLE` plan must list both `DPLUS` and `HULU` in its `service_scope` and must carry `component_weights` — a per-service revenue split such as 0.45 for `DPLUS` and 0.55 for `HULU` — whose weights each sit strictly between 0 and 1 and sum to exactly 1.0 (tolerating a deviation no larger than one billionth). A `STANDALONE` plan covers exactly one service and its `component_weights` is null. A bundle's list price must be positive; there is deliberately no rule forcing the bundle to be cheaper than buying its components separately. Violations of these shape rules are rejected with `ERR_INVALID_PLAN_SHAPE` (HTTP 422). Independently, `monthly_price_cents` must be at least 100 cents — a cheaper plan is rejected with `ERR_INVALID_PRICING` (HTTP 422).

Two boolean flags per plan, `allow_app_store_billing` and `allow_distributor_billing`, govern which third-party channels may sell it, and `is_legacy` (defaulting to false) marks a plan as no longer purchasable: a legacy plan rejects new purchases and plan changes into it with `ERR_PLAN_LEGACY_ONLY` (HTTP 422), with a single exception — a subscriber whose `grandfathered_plan_code` already equals that plan code may plan-change back into it. Plans may be listed with optional `plan_kind` and `is_legacy` filters, and fetched individually by plan code, by any authenticated role including `Subscriber`.

### 3.2. Registration, Account Lifecycle, and Suspension

Anyone may register: an `Anonymous` caller supplies an `email` and `full_name` and receives a `SubscriberAccount` whose `account_status` starts `ACTIVE`. The email is globally unique across all accounts — a duplicate registration fails with `ERR_DUPLICATE_EMAIL` (HTTP 409). The account also carries three ledger fields that start empty: `grandfathered_price_cents` and `grandfathered_plan_code` are null until the first subscription activates, and `account_credit_cents` and `retention_redemption_count` start at 0. Support staff may list accounts with an optional `account_status` filter.

Suspension is a blunt instrument available to `Support` and `PlatformAdmin`. Suspending an `ACTIVE` account cascades: every subscription of the account in `ACTIVE` or `PAST_DUE` lifecycle has all of its `ACTIVE` entitlements moved to `SUSPENDED`, and each suspension that leaves a profile with zero `ACTIVE` entitlements drops that profile from `LINKED` to `SUSPENDED`. Reactivation requires the account to be `SUSPENDED` and, critically, that no subscription of the account remains in `PAST_DUE` — the money must be fixed before the account can come back. When reactivation proceeds, every `SUSPENDED` entitlement whose subscription sits in `ACTIVE` lifecycle returns to `ACTIVE`, and each reactivated entitlement lifts its profile from `SUSPENDED` back to `LINKED` when nothing else blocks it.

Closure is final and can be initiated by the subscriber themselves or by support staff. From `ACTIVE`, closure requires that no subscription remain in `PENDING_ENTITLEMENT`, `ACTIVE`, `PAST_DUE`, or `CANCEL_SCHEDULED` — everything must already be `CANCELLED` or `MIGRATED_OUT`; otherwise the close is rejected with `ERR_ACTIVE_SUBSCRIPTIONS_REMAIN`. From `SUSPENDED`, the same subscription precondition applies. On closure, every profile of the account moves to `UNLINKED`, and every retention redemption still in `ACTIVE` status on the account's subscriptions is moved to `VOIDED`.

### 3.3. Service Profiles, Parental Controls, and Watchlists

Account linking happens at the profile level. Creating a `ServiceProfile` for an account requires the account to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409) and takes a `service` of `DPLUS` or `HULU`; at most one profile per (account, service) pair may exist in any status other than `UNLINKED`, and a second attempt fails with `ERR_DUPLICATE_PROFILE` (HTTP 409). A profile starts `LINKED`. It carries parental controls: a `maturity_rating_cap` drawn from the ordered ratings `TV_Y`, `TV_G`, `TV_PG`, `TV_14`, `TV_MA` (defaulting to `TV_MA`), and a `kids_mode` flag defaulting to false. Setting `kids_mode` to true forces the cap to `TV_PG` regardless of any supplied value — this applies both at creation and on later parental-control updates, which may set `maturity_rating_cap`, `kids_mode`, or both. Profiles can be listed per account with optional `service` and `profile_status` filters.

The watchlist gate ranks maturity on a five-step ladder: `TV_Y` is rank 0, `TV_G` is rank 1, `TV_PG` is rank 2, `TV_14` is rank 3, and `TV_MA` is rank 4. When a subscriber adds a title to a profile's watchlist by supplying a `title_id` and the title's `title_maturity`, the system computes the effective cap — `TV_PG` whenever `kids_mode` is true (ignoring whatever is stored in `maturity_rating_cap`), otherwise the stored `maturity_rating_cap` — and allows the add if and only if the title's rank is at most the effective cap's rank. A title exactly at the cap is allowed; one rank above it is rejected with `ERR_MATURITY_RATING_EXCEEDED` (HTTP 422). The same `title_id` may appear only once per profile — a repeat add fails with `ERR_DUPLICATE_WATCHLIST_ITEM` (HTTP 409). Each successful add increments the profile's `watchlist_count` by 1 and each removal decrements it by 1; the watchlist may be listed with an optional `title_maturity` filter.

Unlinking a profile is permitted to the owning subscriber or support staff only when the profile carries no entitlement in `PROVISIONING` or `ACTIVE` status — attempting it otherwise fails with `ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS` (HTTP 409). Unlinking from either `LINKED` or `SUSPENDED` revokes any `SUSPENDED` entitlements still hanging on the profile and moves the profile to terminal `UNLINKED`. The profile's watchlist rows are retained as readable history, but the profile leaves all access evaluation from that point on.

### 3.4. Billing Accounts and the First Purchase

Before any subscription can be sold, the subscriber needs exactly one `BillingAccount`, created with a `biller_type` of `PLATFORM`, `APP_STORE`, or `DISTRIBUTOR` and a `biller_reference` — the literal string "platform" for platform billing, otherwise an external store receipt id or distributor account id. The `biller_type` is immutable after creation, and a subscriber attempting to create a second billing account is rejected with `ERR_DUPLICATE_BILLING_ACCOUNT` (HTTP 409). The billing account starts `CURRENT` with `consecutive_failure_count` at 0; its `period_start` and `period_end` are set when the first invoice is issued.

Purchasing a subscription takes the `subscriber_account_id`, the `billing_account_id` to charge, the `plan_code` being bought, and — so entitlements know where to land — the target profile per covered service via `dplus_service_profile_id` and `hulu_service_profile_id` as applicable. The account must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), and the account may not already hold a non-terminal subscription on the same plan code (else `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`, HTTP 409). Third-party channels constrain the sale: when the billing account's `biller_type` is `APP_STORE`, the plan's `allow_app_store_billing` must be true, and for `DISTRIBUTOR` the plan's `allow_distributor_billing` must be true; otherwise the purchase fails with `ERR_BILLER_PLAN_NOT_ALLOWED` (HTTP 422). A legacy plan refuses the sale with `ERR_PLAN_LEGACY_ONLY`.

A successful purchase does several things atomically. The subscription is created in `PENDING_ENTITLEMENT` with `billing_dimension` `PAID_UP`; one entitlement per service in the plan's scope is created against the named profiles and provisioned synchronously — each moves from `PROVISIONING` to `ACTIVE` provided its profile is `LINKED` and the entitlement's service is in the plan's scope. An entitlement whose named profile is not `LINKED` remains in `PROVISIONING` rather than failing the purchase. If the profile is `SUSPENDED`, the entitlement is then moved to `ACTIVE`, and per §2.9 the profile rises back to `LINKED`. When every spawned entitlement has reached `ACTIVE` — none remaining in `PROVISIONING` and the active count equal to the number of services in the plan's scope — the subscription bubbles up from `PENDING_ENTITLEMENT` to `ACTIVE`. The initial invoice (kind `INITIAL`) is issued and collected inline, transitioning straight from `ISSUED` to `PAID`, and revenue allocation rows are created for it. The billing account's period is initialized: `period_start` set to now and `period_end` set 30 days later for `PLATFORM` or 31 days later for third-party billers.

### 3.5. Grandfathered Pricing and the Effective Price

The first time any subscription of an account reaches `ACTIVE`, the grandfathered price lock engages — and the evaluation order is pinned, because the subscription's own price depends on the lock that the activation itself creates. First, if the account's `grandfathered_price_cents` is still null, the lock is written: `grandfathered_plan_code` becomes the activating subscription's plan code and `grandfathered_price_cents` becomes that plan's current `monthly_price_cents` list price. Only after the lock is written is the subscription's `price_cents` computed. The lock is never re-derived while any subscription of the account is in `PENDING_ENTITLEMENT`, `ACTIVE`, `PAST_DUE`, or `CANCEL_SCHEDULED`. When every prior subscription has gone terminal — all `CANCELLED` or `MIGRATED_OUT` — a subsequent new subscription reaching `ACTIVE` re-locks at its own plan's current list price, discarding the stale lock.

The effective monthly price of a subscription, exposed as `price_cents`, is then assembled from three inputs with a cap and a floor. The base is the account's `grandfathered_price_cents` whenever the account's `grandfathered_plan_code` equals the subscription's current `plan_code` and the lock is set; otherwise the base is the plan's `monthly_price_cents`. Over that base, the discounts of every `ACTIVE` retention redemption on the subscription are summed — but the total discount may not exceed 60 percent of the base, floored to whole cents, so the applied discount is the smaller of the raw sum and that cap. The price is the base minus the applied discount, recorded on the subscription as `retention_discount_cents` and `price_cents` respectively. Finally, a floor rule: the effective price may not fall below 100 cents; if it would, the price is pinned to 100 cents and the recorded discount is reduced to the base minus 100. This recomputation runs whenever a retention redemption is created, expires, or is voided, whenever the grandfathered lock changes, and on every plan change.

### 3.6. Tier Mismatch Across Linked Services

Because the two services keep distinct profiles, an account can legitimately end up in a split-tier state: a migration that upgrades the bundle to ad-free while a legacy standalone on the same account survives, or the reverse. Whenever both profiles are `LINKED` and the entitlements they carry derive from subscriptions whose plan `ad_tier` values disagree — one `AD_SUPPORTED`, one `AD_FREE` — every entitlement serving the lower-tier service is flagged: its `mismatch_flag` becomes true. A flagged entitlement still provisions and serves as `ACTIVE`; the mismatch is soft, a prompt to the subscriber rather than a denial of service. When a plan change brings the tiers back into agreement, the flag clears on all entitlements of the affected profile. Tier agreement is re-evaluated at profile-link time and again on every plan change. Two bundles of the same plan can never mismatch — one plan has one tier — so accounts holding a bundle and a standalone of the same service remain the only interesting case.

A profile may carry `ACTIVE` entitlements of both tiers at once (for example a bundle's ad-supported entitlement and an ad-free standalone entitlement for the same service). In that case each `LINKED` profile is judged by the best tier among its `ACTIVE` entitlements — `AD_FREE` outranks `AD_SUPPORTED` — and when the two services' best tiers disagree, every `ACTIVE` entitlement of the lower-tier profile is flagged.

### 3.7. Plan Changes and Pending Schedules

A subscriber (or `Support`, `PlatformAdmin`, or `DistributorOps` acting for them) changes a subscription's plan by naming a `new_plan_code` and presenting the subscription's current version as `expected_subscription_version`; the stale-version rule of §2.7 applies and a mismatch is rejected with `ERR_STALE_VERSION`. The new plan must pass the same biller-channel gate as a fresh purchase — `ERR_BILLER_PLAN_NOT_ALLOWED` when the channel forbids it — and the legacy gate of §3.1. App-store-billed subscriptions face a further structural rule: they may only move between plans of the same `plan_kind`; an app-store subscriber asking to jump from standalone to bundle or back is rejected with `ERR_BILLER_UPGRADE_PATH_BLOCKED` (HTTP 422), because cross-kind moves for that channel must be handled by the store.

On a successful change, the subscription's `version` increments by 1, `price_cents` is recomputed per §3.5 — the grandfathered price reapplies exactly when the new plan code equals the account's `grandfathered_plan_code` — and the entitlements are reconciled to the new plan's scope: services newly in scope spawn fresh entitlements that provision straight to `ACTIVE`, while services leaving the scope have their entitlements `REVOKED`. Tier mismatch is re-evaluated after the reconciliation. A subscription may also carry a `pending_plan_code` when a change is scheduled to take effect at the next renewal; it is null whenever no change is pending.

### 3.8. Cancellation: Scheduled, Immediate, and Rescinded

Cancelling a subscription from `ACTIVE` or `PAST_DUE` schedules it: the lifecycle moves to `CANCEL_SCHEDULED`. By default the cancellation takes effect at period end — `cancel_effective_at` is set to the billing account's `period_end` — but the caller may pass `immediate_effect` as true to cancel at the current logical clock instant instead. Two restrictions pin this down. A past-due subscription can cancel only at period end: `immediate_effect` must be false from `PAST_DUE`. And an app-store-billed subscription can never cancel immediately, because the store controls refund timing — such a request is rejected with `ERR_IMMEDIATE_CANCEL_NOT_ALLOWED` (HTTP 422). Distributor-billed subscriptions may cancel either way, with the biller notified.

The interdependent-component rule decides what dies with the subscription. Finalizing a `BUNDLE` subscription revokes all of its entitlements at `cancel_effective_at` — both services die together. Finalizing a `STANDALONE` subscription revokes only its own single-service entitlement; a bundle subscription on the same account is untouched, and cancelling a standalone never implicitly breaks up a bundle. When an account holds both a bundle and a standalone covering the same service, the profile for that service stays `LINKED` as long as at least one `ACTIVE` entitlement for that service survives from any source subscription.

A scheduled cancellation can be walked back: rescinding is allowed while the subscription is `CANCEL_SCHEDULED`, the current logical clock is strictly before `cancel_effective_at`, and the `billing_dimension` is not `UNPAID`. Rescinding clears `cancel_effective_at` back to null and returns the lifecycle to `ACTIVE`. Once the logical clock reaches `cancel_effective_at`, the subscription finalizes to `CANCELLED` and rescinding is no longer reachable — a late rescind hits the state gate and is rejected with `ERR_INVALID_STATE` (HTTP 409). Finalization revokes every entitlement of the subscription in `ACTIVE` or `SUSPENDED`, drops any profile left with zero active entitlements from `LINKED` to `SUSPENDED`, voids any `ACTIVE` retention redemption on the subscription, and moves the `billing_dimension` to terminal `UNPAID`. A cancel requested with `immediate_effect` at or after period end finalizes directly.

### 3.9. Migration: Standalone to Bundle with Proration

Moving a standalone subscriber into a bundle is a two-phase workflow so the subscriber sees the credit before committing. Quoting a migration names the `from_subscription_id` and a `target_plan_code`. The source must be a subscription on a `STANDALONE` plan and the target a `BUNDLE` plan — any other pairing is rejected with `ERR_MIGRATION_SHAPE` (HTTP 422); the source must be `ACTIVE` at quote time or the quote fails with `ERR_MIGRATION_SOURCE_NOT_ACTIVE` (HTTP 409); the owning account must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`); and the target plan must be sellable through the account's biller (else `ERR_BILLER_PLAN_NOT_ALLOWED`). The created `Migration` sits in `QUOTED` with `to_subscription_id` still null.

The quote computes the unused-portion credit with the chronological variant. Let `days_total` be the whole-day length of the source subscription's current billing period — 30 days for `PLATFORM`, 31 days for third-party billers — and let the monthly figure be the source subscription's effective monthly price under §3.5 (the grandfathered price when locked, else the plan list price). The elapsed days are the whole-day count from `period_start` to the quote instant; the remaining days are `days_total` minus the elapsed days; the credit is the monthly figure multiplied by the remaining days and divided by `days_total`, rounded down to whole cents. The result is stored as `proration_credit_cents` with `proration_method_used` recorded as `CHRONOLOGICAL_REMAINING`.

Confirming the migration is the committing act and carries the OCC handshake of §2.7: the request must present `expected_migration_version` equal to the migration's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. Confirming is valid only inside the quoted period — the current logical clock must be strictly before the source subscription's `period_end`; an attempt at or after that instant fails with `ERR_MIGRATION_WINDOW_CLOSED` (HTTP 422). If the source subscription has left `ACTIVE` in the meantime, the state gate rejects the confirm with `ERR_INVALID_STATE`.

At confirm, the credit is recomputed with the forward-looking variant and can shrink relative to the quote. The same day arithmetic runs against the confirm instant to produce a base credit; then every invoice of the source subscription — `ISSUED` or `PAID` — whose `period_start` is at or after the migration row's `created_at` contributes its `credit_applied_cents` to a consumed total; the confirmed credit is the base minus the consumed amount, floored at zero. `proration_credit_cents` and `proration_method_used` (now `FORWARD_LOOKING_PERIOD`) are updated. The source subscription moves from `ACTIVE` to `MIGRATED_OUT` and its entitlements are revoked. The new bundle subscription is created in `PENDING_ENTITLEMENT` with entitlements spawned per the target plan's scope and provisioned synchronously to `ACTIVE`, which bubbles the new subscription to `ACTIVE`; its `migration_id` points back to the migration, as does the source subscription's. The recomputed credit is posted to the account's `account_credit_cents`, a `MIGRATION_ADJUSTMENT` invoice with `gross_cents` of 0 and `credit_applied_cents` of 0 is issued as the audit anchor, and the migration's `version` increments by 1. Voiding a quoted migration — explicitly, or automatically when the source subscription leaves `ACTIVE` before confirm — discards the quote with no ledger movement. Both `CONFIRMED` and `VOIDED` are terminal; a migration never leaves either state.

### 3.10. Retention Offers and Redemptions

A `PlatformAdmin` defines a `RetentionOffer` with a unique `offer_code`, a `discount_cents` monthly discount of at least 1, a `duration_months` of at least 1 counting how many renewals the discount survives, a `max_redemptions_per_account` lifetime cap, and the eligibility scopes `eligible_biller_types` and `eligible_plan_kinds`. Pricing validation applies: a discount below 1 cent or a duration below 1 month is rejected with `ERR_INVALID_PRICING`. Offers default to `OPEN`; a `RETIRED` offer rejects new redemptions but never disturbs existing ones.

Redeeming an offer against a subscription is a six-clause conjunction, and any failure is `ERR_RETENTION_NOT_ELIGIBLE` (HTTP 422): the offer must be `OPEN`; the subscription's lifecycle must be `ACTIVE` — not `PAST_DUE`, not `CANCEL_SCHEDULED`; the billing account's `biller_type` must appear in `eligible_biller_types`; the plan's `plan_kind` must appear in `eligible_plan_kinds`; the count of this offer's redemptions on this account in `ACTIVE` or `EXPIRED` status must be strictly below `max_redemptions_per_account` — `VOIDED` redemptions do not count, so an account at one below the cap succeeds while one at the cap fails; and no other redemption on this same subscription may be `ACTIVE`. The account must also be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`).

A successful redemption starts `ACTIVE` with `months_remaining` initialized to the offer's `duration_months`, and the subscription's `retention_discount_cents` and `price_cents` are recomputed per §3.5. Each successful renewal of the host subscription decrements `months_remaining` by 1; when a decrement brings it to exactly 0 the redemption moves to `EXPIRED` and the subscription's discount and price are recomputed. A redemption whose host subscription is `CANCELLED` or `MIGRATED_OUT`, whose account is `CLOSED`, or whose billing account hard-fails is moved to `VOIDED`, with the same price recomputation. The account-level `retention_redemption_count` tracks the lifetime number of redemptions in `ACTIVE` or `EXPIRED` status — never `VOIDED` — and drives the eligibility cap. Redemptions may be listed per subscription, or across an account with optional `redemption_status` and `offer_code` filters.

### 3.11. Renewal Collection, Dunning, and Recovery

Renewal is driven by a test-driving capability available to `PlatformAdmin`: for a named `billing_account_id` whose period is due — `period_end` at or before the logical clock, closed at the boundary — it runs the collection with a forced `outcome`. Running it for an account whose period has not ended is rejected with `ERR_RENEWAL_NOT_DUE` (HTTP 422).

The run processes the billing account's due subscriptions — those in `ACTIVE` lifecycle with `billing_dimension` `PAID_UP` — in chronological order of each subscription's `created_at`, ascending, with no other tie-breaker. For each, the gross is the subscription's effective price per §3.5; the credit applied is the smaller of the account's `account_credit_cents` and the gross; the net is the gross minus the credit applied, and the account's credit balance is reduced by the amount consumed. A `RENEWAL` invoice (kind `INITIAL` for the first period, `RENEWAL` thereafter) records `gross_cents`, `credit_applied_cents`, and `net_cents` alongside the billed `period_start` and `period_end`. The account's `account_credit_cents` never goes negative.

On a succeeded outcome the invoice moves to `PAID`; the billing period advances — the old `period_end` becomes the new `period_start`, and the new `period_end` lands 30 days later for `PLATFORM` or 31 days later for third-party billers; and each `ACTIVE` retention redemption on the subscription loses one month of `months_remaining`, expiring exactly when that count reaches 0.

On a failed outcome the invoice moves to `FAILED` and the dunning cascade begins: the billing account drops from `CURRENT` to `PAST_DUE` with `consecutive_failure_count` incremented by 1; the subscription's `billing_dimension` moves from `PAID_UP` to `GRACE` and its lifecycle from `ACTIVE` to `PAST_DUE`; every `ACTIVE` entitlement of the subscription suspends; and each profile left with zero active entitlements drops from `LINKED` to `SUSPENDED`. Recovery can come from two directions. Retrying a failed invoice is open to the subscriber or operator within the grace window — the current logical clock must be strictly before `period_end` plus 7 days, and at exactly that instant the window is closed (`ERR_GRACE_WINDOW_CLOSED`); the billing account must also not be `HARD_FAILED`. A successful retry pays the invoice, runs revenue allocation for it, and unwinds the cascade: `consecutive_failure_count` resets to 0, the billing account returns to `CURRENT`, the subscription returns to `PAID_UP` and `ACTIVE`, suspended entitlements reactivate, and affected profiles return to `LINKED`. A succeeded renewal retry produces the same recovery.

When a renewal failure arrives while `consecutive_failure_count` already stands at 2 — so the increment would bring it to 3 — the billing account goes `HARD_FAILED`. The subscription's lifecycle moves directly from `PAST_DUE` to `CANCELLED` with `cancel_effective_at` null (the cancellation is immediate), the `billing_dimension` moves from `GRACE` to `UNPAID`, every entitlement of the subscription in `ACTIVE` or `SUSPENDED` is revoked, profiles left without active entitlements suspend, and any `ACTIVE` retention redemption on the subscription is voided. Recovery past `HARD_FAILED` is impossible — the state gate blocks retry-payment with `ERR_INVALID_STATE`.

### 3.12. Invoices, Revenue Allocation, and Reporting

Every invoice traces to one subscription for one period and carries a `invoice_kind` of `INITIAL`, `RENEWAL`, or `MIGRATION_ADJUSTMENT`. An invoice in `ISSUED` that is superseded — by a migration adjustment or by a cancellation before the period begins — is `VOIDED` without further effect. Invoices may be listed per subscription or per billing account with optional `invoice_status` and `invoice_kind` filters.

When an invoice reaches `PAID` — whether directly on issue or through a retry — the collected `net_cents` is split across services. For a standalone plan there is exactly one allocation row, crediting the entire `net_cents` to the covered service. For a bundle, services are processed in the fixed order `DPLUS` then `HULU`: the `DPLUS` row receives the net amount multiplied by the `DPLUS` component weight, rounded half-up to whole cents, and the `HULU` row receives whatever remains — the net minus the `DPLUS` allocation — so the rows always sum exactly to `net_cents`. Each row records its `service` and `allocated_cents`, and allocation rows may be listed per invoice with an optional `service` filter, visible to `Support`, `PlatformAdmin`, and `DistributorOps`.

The revenue report aggregates allocations over a closed-open window from `from_iso8601` to `to_iso8601`, optionally narrowed to one `service`. Only `PAID` invoices contribute. The report returns the `total_cents` collected in the window, a `per_service` breakdown, and the `invoice_count` of contributing invoices.

### 3.13. Reading the Graph

Every entity in the system can be traced back to its owner through the foreign keys it carries, and these identifiers are part of the API surface because list filters and payloads reference them. A `ServiceProfile` names its owner in `subscriber_account_id`; a `WatchlistItem` names its profile in `service_profile_id`. A `BillingAccount` names its owner in `subscriber_account_id`, and a `Subscription` names both its owner (`subscriber_account_id`) and the biller collecting for it (`billing_account_id`). An `Entitlement` names its source in `subscription_id` and the profile it grants in `service_profile_id`, and its `service` must equal that profile's service while also appearing in the plan's scope. A `Migration` names its owner, its consumed source in `from_subscription_id`, and — once confirmed — its produced bundle in `to_subscription_id`. A `RetentionRedemption` names its host in `subscription_id` and denormalizes the owner into `subscriber_account_id` so eligibility counting does not walk the graph. An `Invoice` names its `billing_account_id` and the billed `subscription_id`, and a `RevenueAllocation` names its `invoice_id`. Subscriptions and migrations may be listed with filters on `subscriber_account_id`, `billing_account_id`, `plan_code`, `lifecycle_status`, `migration_id`, `from_subscription_id`, `to_subscription_id`, and `migration_status`; entitlements with `service` and `entitlement_status`; and watchlist, billing, and redemption lists with their corresponding status filters.

An entitlements listing is available both from the subscription side and from the profile side, the latter aggregating entitlements granted to a profile from any subscription. The billing-run response summarizes the outcome with the resulting `invoice_id`, the invoice's `invoice_status`, and the billing account's `billing_status`; the clock endpoint answers with the new `current_utc`.

## 4. Endpoint Definitions

All endpoints live under the `/streaming` prefix. Creating a new resource returns HTTP 201 with the created resource; successful modifications, actions, and reads return HTTP 200 with the affected resource; deletions return HTTP 204 with no body. Error responses use the envelope of §2.2 with the codes of §5. Request bodies must be well-formed — a missing required field, a malformed type, a bad enum value, or a malformed ISO 8601 datetime is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /streaming/_clock/set_current_utc | Advance the logical clock to `to_iso8601`; monotonic | PlatformAdmin |
| POST | /streaming/plans | Create a standalone or bundle plan | PlatformAdmin |
| GET | /streaming/plans | List plans (`plan_kind`, `is_legacy` filters) | PlatformAdmin, Support, DistributorOps, Subscriber |
| GET | /streaming/plans/{id} | Get one plan; the id segment is the `plan_code` | PlatformAdmin, Support, DistributorOps, Subscriber |
| POST | /streaming/subscriber-accounts | Register a subscriber account | Anonymous |
| GET | /streaming/subscriber-accounts/{id} | Get a subscriber account | Subscriber, Support, PlatformAdmin |
| GET | /streaming/subscriber-accounts | List accounts (`account_status` filter) | Support, PlatformAdmin |
| POST | /streaming/subscriber-accounts/{id}/suspend | Suspend an account; cascades to entitlements and profiles | Support, PlatformAdmin |
| POST | /streaming/subscriber-accounts/{id}/reactivate | Reactivate a suspended account | Support, PlatformAdmin |
| POST | /streaming/subscriber-accounts/{id}/close | Close an account; all subscriptions must be terminal | Subscriber, Support, PlatformAdmin |
| POST | /streaming/subscriber-accounts/{id}/service-profiles | Link a service profile to the account | Subscriber, Support, PlatformAdmin |
| GET | /streaming/subscriber-accounts/{id}/service-profiles | List the account's service profiles | Subscriber, Support, PlatformAdmin |
| GET | /streaming/service-profiles/{id} | Get one service profile | Subscriber, Support, PlatformAdmin |
| POST | /streaming/service-profiles/{id}/unlink | Unlink a profile; revokes suspended entitlements | Subscriber, Support, PlatformAdmin |
| PATCH | /streaming/service-profiles/{id} | Update parental controls (`maturity_rating_cap`, `kids_mode`) | Subscriber, Support, PlatformAdmin |
| POST | /streaming/service-profiles/{id}/watchlist-items | Add a title to the profile's watchlist; maturity gate applies | Subscriber, Support, PlatformAdmin |
| GET | /streaming/service-profiles/{id}/watchlist-items | List the profile's watchlist | Subscriber, Support, PlatformAdmin |
| DELETE | /streaming/service-profiles/{id}/watchlist-items/{item_id} | Remove a watchlist item | Subscriber, Support, PlatformAdmin |
| POST | /streaming/subscriber-accounts/{id}/billing-accounts | Create the account's billing relationship (one per subscriber) | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/subscriber-accounts/{id}/billing-accounts | List the account's billing accounts | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/billing-accounts/{id} | Get one billing account | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/subscriptions | Purchase a subscription; provisions entitlements and issues the initial invoice | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/subscriptions/{id} | Get one subscription | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/subscriptions | List subscriptions with filters | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/subscriptions/{id}/plan-change | Change plan; OCC on the subscription's version | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/subscriptions/{id}/cancel | Cancel a subscription; period-end by default | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/subscriptions/{id}/rescind-cancellation | Rescind a scheduled cancellation | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/subscriptions/{id}/entitlements | List entitlements of a subscription | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/service-profiles/{id}/entitlements | List entitlements granted to a profile | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/entitlements/{id} | Get one entitlement | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/migrations | Quote a standalone-to-bundle migration | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/migrations/{id} | Get one migration | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/migrations | List migrations with filters | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/migrations/{id}/confirm | Confirm a quoted migration; OCC on the migration's version | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/migrations/{id}/void | Void a quoted migration | Subscriber, Support, PlatformAdmin, DistributorOps |
| POST | /streaming/retention-offers | Create a retention offer | PlatformAdmin |
| GET | /streaming/retention-offers | List retention offers (`offer_status` filter) | PlatformAdmin, Support |
| GET | /streaming/retention-offers/{id} | Get one offer; the id segment is the `offer_code` | PlatformAdmin, Support |
| POST | /streaming/subscriptions/{id}/retention-redemptions | Apply a retention offer to a subscription | Subscriber, Support, PlatformAdmin |
| GET | /streaming/subscriptions/{id}/retention-redemptions | List redemptions of a subscription | Subscriber, Support, PlatformAdmin |
| GET | /streaming/subscriber-accounts/{id}/retention-redemptions | List redemptions across an account | Subscriber, Support, PlatformAdmin |
| GET | /streaming/subscriptions/{id}/invoices | List invoices billed for one subscription | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/billing-accounts/{id}/invoices | List invoices of a billing account | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/invoices/{id} | Get one invoice | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/invoices/{id}/revenue-allocations | List an invoice's revenue allocation rows | Support, PlatformAdmin, DistributorOps |
| POST | /streaming/invoices/{id}/retry-payment | Retry a failed invoice within the grace window | Subscriber, Support, PlatformAdmin, DistributorOps |
| GET | /streaming/revenue-report | Aggregate revenue per service over [from_iso8601, to_iso8601) | Support, PlatformAdmin, DistributorOps |
| POST | /streaming/_billing/run_renewal | Run renewal collection for one billing account with a forced outcome | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard; this catalogue is the authoritative mapping of error id to HTTP status.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_ACCOUNT_CLOSED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_PROFILE | 409 |
| ERR_DUPLICATE_WATCHLIST_ITEM | 409 |
| ERR_DUPLICATE_ACTIVE_SUBSCRIPTION | 409 |
| ERR_DUPLICATE_BILLING_ACCOUNT | 409 |
| ERR_MATURITY_RATING_EXCEEDED | 422 |
| ERR_INVALID_PLAN_SHAPE | 422 |
| ERR_INVALID_PRICING | 422 |
| ERR_BILLER_PLAN_NOT_ALLOWED | 422 |
| ERR_BILLER_UPGRADE_PATH_BLOCKED | 422 |
| ERR_IMMEDIATE_CANCEL_NOT_ALLOWED | 422 |
| ERR_MIGRATION_SHAPE | 422 |
| ERR_MIGRATION_WINDOW_CLOSED | 422 |
| ERR_MIGRATION_SOURCE_NOT_ACTIVE | 409 |
| ERR_RETENTION_NOT_ELIGIBLE | 422 |
| ERR_GRACE_WINDOW_CLOSED | 422 |
| ERR_ACTIVE_SUBSCRIPTIONS_REMAIN | 409 |
| ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS | 409 |
| ERR_CLOCK_REGRESSION | 422 |
| ERR_RENEWAL_NOT_DUE | 422 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_PLAN_LEGACY_ONLY | 422 |
