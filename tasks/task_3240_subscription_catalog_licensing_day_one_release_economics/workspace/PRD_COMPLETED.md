# Subscription Catalog Licensing API — Product Requirements Document

## 1. Introduction

The Subscription Catalog Licensing API governs how a subscription gaming service — in the shape of a
Game Pass style catalogue — acquires third-party titles, schedules them into and out of a rotating
catalogue, and reconciles the money that flows in both directions. On one side sits the licensing
desk: publishers are onboarded, titles are registered against them, and each title is covered by a
licensing deal whose compensation structure is fixed-fee, engagement-based or hybrid. Each deal
carries a term, and the term is what decides when a title joins the catalogue, when subscribers are
told it is leaving, and when it finally disappears. On the other side sit members: they open
subscriptions against a tier, they are resolved into entitlements as catalogue entries are published,
they build engagement history that feeds both the publisher's compensation and their own score, and
they buy catalogue titles outright at a member discount that survives the title's removal for a
bounded retention window.

The commercial question the system must answer every month is whether a day-one release is worth its
cannibalised unit sales. A first-party or negotiated third-party title can be pushed into the
catalogue on its launch day, which drives subscriber acquisition and tier upgrades but suppresses
outright purchases; the platform's analysts model that tradeoff as a projection, take a decision from
a pinned decision ladder, and later reconcile the projection against the sales that actually happened.
The same catalogue that produces those projections also consumes streaming capacity, so the service
must keep a per-region fleet model that reacts to popularity, to launch spikes and to planned
maintenance windows.

Because money, entitlement and capacity figures are all derived from the same underlying events, the
system is intolerant of ambiguity: every derived number is defined by an explicit arithmetic
procedure, every state change is enumerated, and the order in which competing checks reject a request
is fixed. This document specifies the resources, the state machines, the calculations and the
validation order that together produce exactly one correct outcome for every request.

## 2. Global Specifications & System-Wide Principles

Everything in this section applies across the whole API surface: how callers authenticate, what a
response looks like, how lists are paged, how money and scores are rounded, how referenced resources
are resolved, and in what order the server rejects requests that fail more than one rule.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID`, identifying the acting principal, and
`X-User-Role`, declaring that principal's operational capacity. Requests that omit either header, or
that present an `X-User-Role` outside the four declared roles, are rejected with
`ERR_MISSING_AUTH_HEADER` and HTTP 401.

The four declared roles are `CatalogAdmin`, `CatalogAnalyst`, `Subscriber` and `Anonymous`. A
`CatalogAdmin` is the catalogue operator: they license titles, plan and publish catalogue rotation,
drive the logical clock, restore and revoke entitlements, reverse purchases, and may register
subscribers on their behalf. A `CatalogAnalyst` reads catalogue and analytics data and owns day-one
release projections, including finalising them. A `Subscriber` is a member of the service: they open
and pay for subscriptions, record engagement, resolve entitlements, buy catalogue titles and cancel.
An `Anonymous` caller is unauthenticated and may do exactly one thing — register a new subscriber
account.

The roles differ in how `X-User-ID` is interpreted, and this difference decides every ownership
check in the system:

- When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`. Ownership
  checks on any resource that carries a `subscriber_id` compare that field to `X-User-ID`; a
  `Subscriber` may only act on resources whose `subscriber_id` equals its own `X-User-ID`.
- When `X-User-Role` is `CatalogAdmin`, `CatalogAnalyst` or `Anonymous`, `X-User-ID` is an opaque
  operator identifier that is not tied to any persisted entity. The server does not compare it to
  any entity's `id`; it is recorded only for audit purposes.

A caller whose role is not permitted on the requested operation is rejected with `ERR_FORBIDDEN_ROLE`
and HTTP 403, as is a `Subscriber` who targets a resource that is not their own. Role permissions are
summarised per endpoint in §4.

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

Two server-level failures that no business rule classifies are reported in the same envelope. A request for a path the API does not serve is answered with `ERR_ENTRY_NOT_FOUND` and HTTP 404. A request that names a path the API does serve but carries a method that path does not accept is answered with `ERR_INVALID_REQUEST` and HTTP 405. Any other failure that reaches the server without a governing rule — including a request body the framework cannot decode — is reported as `ERR_INVALID_REQUEST` with HTTP 400.

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. `limit` is the maximum number of
entries to return; when it is not supplied it defaults to 10, and it must lie between 1 and 100
inclusive. `offset` is the number of matching entries to skip and defaults to 0 when omitted. The
pagination-related fields reported in `meta` are `limit`, `offset`, `total_count` and `has_more`;
`total_count` is the number of matching resources before paging and `has_more` states whether further
matches exist beyond the returned window. Unless a description in §4 says otherwise, every list
endpoint returns its resources sorted by `created_at` in ascending order, with rows sharing a
`created_at` ordered by the order in which they were persisted — the tie-break the finalized
cannibalisation accumulator in §3.9 also relies on.
### 2.4. Resource Addressability and Reference Resolution

Each of the thirteen persisted resources — `Publisher`, `Title`, `Region`, `SubscriptionTier`,
`LicensingDeal`, `CatalogEntry`, `CatalogMaintenance`, `Subscriber`, `Subscription`, `Entitlement`,
`EngagementEvent`, `Purchase` and `AvailabilityProjection` — is addressed by an identifier the server
mints. The properties that every resource carries are described in §2.5, and where a resource carries
a foreign key, that key is named explicitly in this document and is supplied by the caller on
creation rather than being invented (for example a title is registered against the `publisher_id` of
its owning studio, and a catalogue plan is filed against the `title_id` it would place).

Referenced resources are resolved before any business rule is evaluated, and the resolution order is
fixed. Path-segment identifiers are validated first, strictly left to right; only after every
path identifier has resolved are body identifiers validated, in the order in which the operation's
declared input list presents them. The first identifier that fails resolution ends the request; later
identifiers are not examined and no business rule is reached. Each failure carries its own code:

- A path or body identifier that names no `Publisher` is rejected with `ERR_PUBLISHER_NOT_FOUND`
  (404). The same 404 is raised when a `Title` identifier matches nothing, or matches a title that is
  not owned by the publisher named alongside it — `ERR_TITLE_NOT_FOUND`.
- An unknown region code is rejected with `ERR_REGION_NOT_FOUND` (404), and an unknown tier code with
  `ERR_TIER_NOT_FOUND` (404).
- A deal identifier that matches nothing, or that matches a deal not belonging to the named title, is
  rejected with `ERR_DEAL_NOT_FOUND` (404); an entry identifier that matches nothing, or an entry
  belonging to a different title than the one named, is rejected with `ERR_ENTRY_NOT_FOUND` (404); a
  subscriber identifier that matches nothing is rejected with `ERR_SUBSCRIBER_NOT_FOUND` (404); and a
  subscription identifier that matches nothing, or a subscription not owned by the named subscriber,
  is rejected with `ERR_SUBSCRIPTION_NOT_FOUND` (404).
- An unknown projection identifier is rejected with `ERR_PROJECTION_NOT_FOUND` (404).
- Three further identifiers resolve through codes that do not carry their own name.
  An `entitlement_id` that matches no `Entitlement` and a `purchase_id` that matches no `Purchase` are
  each rejected with `ERR_ENTRY_NOT_FOUND` (404); an `event_id` that matches no `EngagementEvent` is
  rejected with `ERR_SUBSCRIPTION_NOT_FOUND` (404); and a `maintenance_id` that matches no
  `CatalogMaintenance` is rejected with `ERR_REGION_NOT_FOUND` (404).

Body identifiers are the foreign keys a create or update request supplies — for example `publisher_id`,
`title_id`, `region_code`, `entry_id`, `deal_id` or `subscriber_id` — and the enforced order for a
request that carries several of them is the order in which §4 lists that operation's inputs.

### 2.5. Common Resource Properties

Eleven of the thirteen resources carry the full set of system-managed properties, and the contract is
identical for all of them:

- `**id` (string):** a unique, server-minted identifier formatted as a UUID with no type prefix or
  namespace qualifier.
- `**created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the
  resource was first persisted.
- `**updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last
  modification. Any mutation of the resource — including a mutation that only refreshes a derived
  field — advances `updated_at`.
- `**version` (integer):** a counter starting at 1 and incremented by exactly one on every mutation of
  the resource, again including mutations that only recompute a derived field. `version` is the value
  a client echoes back for optimistic concurrency control (§2.12).

Two resources are deliberately lighter. A `Region` and an `EngagementEvent` are created with only
`id` and `created_at`: neither carries `updated_at` nor `version`, and no operation may expect those
keys on a `Region` or an `EngagementEvent` response. Every other resource — `Publisher`, `Title`,
`SubscriptionTier`, `LicensingDeal`, `CatalogEntry`, `CatalogMaintenance`, `Subscriber`,
`Subscription`, `Entitlement`, `Purchase` and `AvailabilityProjection` — carries the full four-field
set.

Three resources carry one further system-managed field alongside the properties above.
`Subscription`, `Purchase` and `EngagementEvent` each expose a `created_at_dt` key, holding the same
logical-clock instant as `created_at`; it is present on the row from creation and is not dropped from
any response, and a client never supplies it.

### 2.6. Money, Scores and Rounding

Every monetary amount in the system is an integer or decimal count of cents under the key suffix
`_cents`; prices presented to a subscriber are the only values that move under a regional multiplier,
and even then the stored value remains an exact cent count. Unless a rule below states otherwise,
monetary totals, percentages and scores are held to **two decimal places, rounded half up**. Where a
calculation rounds an intermediate quantity — a regional list price, a discount amount, a share, a
utilisation percentage — the rule that governs that calculation states the precision at which the
rounding happens, and a value that has already been rounded is never re-rounded later in the same
procedure. Percentages such as `retention_pct`, `conversion_pct` and `capacity_utilization_pct` are
reported on a 0–100 scale with two decimals, not as a fraction.

Two calculations carry their own precision: an engagement event's `normalized_hours` is fixed at write
time to four decimal places, rounded half up, and is never recomputed thereafter even when the logical
clock moves; and the parity blending of a region multiplier is quantised to four decimal places. The
`engagement_score` and `weighted_engagement_score` values are scores rather than money but follow the
same two-decimal, round-half-up convention, and the `engagement_score` is additionally clamped so that
it can never exceed 100.

### 2.7. Catalogue Occupancy and Capacity Stewardship

A region declares an `availability_ceiling_titles` figure that serves two distinct purposes: it caps
how many titles the region may hold in the catalogue at once, and it sizes the region's streaming
fleet. The catalogue-occupancy side is a hard quota — an attempt to publish an entry into a region
that already holds that many entries in status `ADDED` or `REMOVING` is rejected with
`ERR_REGION_CATALOG_CEILING_REACHED` (409). The fleet side is a modelling figure rather than a quota:
the region's usable slots are the ceiling multiplied by thirty slots per ceiling unit, and the
required slots are derived from live catalogue popularity, launch spikes and a fixed per-region
overhead. The full derivation is given in §3.7.

Streaming fleets are also withdrawn for maintenance. A `CatalogMaintenance` window names the
`region_code` it applies to, an inclusive `maintenance_start`, an exclusive `maintenance_end` and a
`capacity_reduction_pct` between 0 and 1. While a window's half-open interval contains the logical
clock — the same condition on which the clock sweep marks it `ACTIVE` — the region's usable slots are
reduced by that fraction. Whether a window is currently in force is decided by the clock's position in
that interval rather than by the stored `status` string, so a window created with its interval already
covering the clock reduces the region's usable slots and blocks membership even though no sweep has yet
rewritten its `status` from `SCHEDULED`. Maintenance windows of the same region may not overlap unless the submission
explicitly marks the window as tolerating overlap: an overlapping pair is rejected with
`ERR_MAINTENANCE_WINDOW_OVERLAP` (409), and any request that would create or publish catalogue
membership while the logical clock falls inside an `ACTIVE` maintenance window of the target region is
rejected with `ERR_REGION_MAINTENANCE_WINDOW_ACTIVE` (409). A window whose `maintenance_end` is not
strictly after its `maintenance_start` is rejected with the same `ERR_MAINTENANCE_WINDOW_OVERLAP` code.

A window is born `SCHEDULED` and its status is a three-value enumeration, `SCHEDULED`, `ACTIVE` or
`COMPLETED`. The logical clock drives the progression: a `SCHEDULED` window becomes `ACTIVE` once the
clock reaches its `maintenance_start`, and an `ACTIVE` window becomes `COMPLETED` once the clock
reaches its `maintenance_end`; thereafter its reduction no longer touches the region's usable slots.
The overlap-tolerating marker is submitted per window under the key `allow_overlap` and defaults to
false when it is omitted.

Windows are not created, modified or removed through an endpoint of their own. A window comes into
existence only as one element of the `maintenance_windows` list on the region create, and there is no
standalone maintenance create, update or delete. `CatalogMaintenance` is exposed only through the two
read-only operations listed in §4 — reading one window by its identifier and listing windows with
optional region and status filters — so only the region create may carry window input.

### 2.8. Tiers, Entitlements and Access Channels

A `SubscriptionTier` is identified by its `tier_code`, one of `ESSENTIAL`, `PREMIUM` or `ULTIMATE`,
and is unique on that code. Each tier carries four independent access switches — `console_access`,
`pc_access`, `cloud_access` and `online_play_bundle` — plus its `monthly_price_cents` global default,
a base `member_discount_pct` between 0 and 0.4, a `discount_retention_days` count, and an
`annual_prepay_credit_ratio` that determines how much of an annual prepayment is credited to the first
billing month. An `Entitlement` is the per-subscriber, per-title resolution of those switches: its
`access_channels` array is derived from the subscription's tier flags and is a subset of `CONSOLE`,
`PC`, `CLOUD` and `ONLINE_PLAY`, and at most one entitlement row may exist for a given
(subscription, title, region) triple.

Regions gate tiers in one direction only. Each region declares a `catalog_tier_floor` of `ESSENTIAL`,
`PREMIUM` or `ULTIMATE`; tiers below that floor are not offered in the region. Requesting a
subscription at a tier beneath the floor is rejected with `ERR_TIER_UNSUPPORTED_IN_REGION` (409), and
filing a catalogue entry whose `tiers` array names a tier below the floor is rejected with
`ERR_TIER_BELOW_REGION_FLOOR` (409). Tiers are ordered `ESSENTIAL` below `PREMIUM` below `ULTIMATE`,
so a `PREMIUM` floor admits `PREMIUM` and `ULTIMATE` but not `ESSENTIAL`.

A subscription's entitlement dimension and its payment dimension move independently. Status `ACTIVE`
means full access; status `GRACE` means the subscription is behind on payment and cloud streaming is
suspended while every other granted channel continues to work; status `REVOKED` means no play access
remains at all. Access-channel arrays are never narrowed by a move into `GRACE` — the array is left
unchanged and the suspension is expressed by the status alone. When an entitlement resolves to
`GRACE`, it is the subscription's `lifecycle_status` — the dimension whose enumeration carries the
`GRACE` value — that governs, rather than its `billing_status`; the two dimensions nonetheless move
together on the failed-charge and settlement transitions described in §3.5.

### 2.9. Unit-Sales Ledger Conservation

Buying a catalogue title outright produces a `Purchase` row whose `list_price_cents_per_unit`,
`discount_pct_applied`, `wallet_applied_cents`, `total_charged_cents` and `unit_sales_credit_cents`
are all derived, never supplied. Wallet credit is a conserved quantity: when a purchase consumes part
of a subscriber's `wallet_credit_cents`, that amount is recorded on the row as `wallet_applied_cents`
and remains recorded there even after the purchase is reversed, so that the sum of the subscriber's
live balance and the retained `wallet_applied_cents` across reversed rows reconciles. Reversing a
purchase sets its `status` to `REFUNDED`, restores the consumed credit by increasing the subscriber's
`wallet_credit_cents` by the retained `wallet_applied_cents`, drops the row out of the sales
accumulator that feeds the reconciled cannibalisation figure, and leaves the row in place with its
`unit_sales_credit_cents` intact for audit. A purchase that is already `REFUNDED` cannot be reversed
again.

### 2.10. Optimistic Concurrency Control

Exactly one operation in this API is guarded by optimistic concurrency control: signing a licensing
deal. Signing a `LicensingDeal` requires the request body to carry `expected_title_version`, a
non-optional field holding the title's `version` as the client last observed it. If the licensing
title's `version` has advanced past that value — because another writer signed a competing deal, or
for any other reason — the request is rejected with `ERR_STALE_VERSION` and HTTP 412, and the client
must re-read the title before signing. This is the intended serialization point between two competing
signatures and it is expressed purely as a stale-observation check: the mechanism does not depend on
two requests overlapping in time, only on whether the client's observed version still matches the
title's current version. No other endpoint in the API accepts a version field; in particular, no
endpoint takes an `expected_deal_version`, `expected_entry_version` or `expected_subscription_version`.

### 2.11. Order of Rejection

When a request violates more than one rule the server reports exactly one error, decided by a fixed
precedence. Authentication and authorization are settled first (401 before 403), then request
well-formedness, then resource existence, then current-state eligibility, then the temporal window
rules, then the remaining referential and eligibility constraints, then quota and cap rules, and
finally the optimistic-concurrency check that rides on the sign operation.

Concretely, a request with a malformed or missing header is rejected before its role is examined; a
permitted-role request with a missing or undeclared body field is rejected with `ERR_INVALID_REQUEST`
(400) before any identifier is resolved; unresolved identifiers are reported before the target's state
is inspected; and a target in the wrong state is reported before any window, eligibility or quota rule
is reached. Two consequences worth stating explicitly: a body that is syntactically invalid never
produces a 404, and a resource that does not exist never produces a 409, even if the request would
also have failed the state, window or quota rules.

The state-eligibility layer collects the following codes: `ERR_DEAL_ALREADY_SIGNED`,
`ERR_ENTRY_NOT_PUBLISHABLE`, `ERR_ENTRY_ALREADY_DELISTED`, `ERR_REMOVAL_ALREADY_ANNOUNCED`,
`ERR_REMOVAL_NOT_ANNOUNCED`, `ERR_REMOVAL_REVERT_WINDOW_CLOSED`, `ERR_SUBSCRIPTION_TERMINAL`,
`ERR_NO_UNPAID_MONTHS`, `ERR_ENTITLEMENT_ALREADY_REVOKED`, `ERR_PROJECTION_ALREADY_FINALIZED` and
`ERR_PURCHASE_ALREADY_REVERSED`, each carrying HTTP 409. The temporal layer collects
`ERR_TERM_WINDOW_INVALID`, `ERR_ADD_EFFECTIVE_OUTSIDE_TERM`, `ERR_REMOVAL_DATE_NOT_AFTER_ADD`,
`ERR_INSUFFICIENT_REMOVAL_NOTICE`, `ERR_REMOVAL_REVERT_CUTOFF`, `ERR_REGION_MAINTENANCE_WINDOW_ACTIVE`
and `ERR_MAINTENANCE_WINDOW_OVERLAP`, all 409. The eligibility layer collects
`ERR_PUBLISHER_SUSPENDED`, `ERR_TIER_UNSUPPORTED_IN_REGION`, `ERR_TIER_BELOW_REGION_FLOOR`,
`ERR_PLATFORM_NOT_SUPPORTED`, `ERR_DAY_ONE_NOT_ELIGIBLE`, `ERR_ENTRY_TITLE_MISMATCH`,
`ERR_NO_BINDING_DEAL`, `ERR_DUPLICATE_DAY_ONE_PROJECTION` and `ERR_COMPENSATION_MODEL_MISMATCH`, all
409. The quota layer runs last among the 409 family and collects `ERR_REGION_CATALOG_CEILING_REACHED`,
`ERR_MEMBER_DISCOUNT_CAP_EXCEEDED` and `ERR_PREPAY_CREDIT_CAP_EXCEEDED`.

### 2.12. The Logical Clock

The service never reads wall-clock time. It runs on a logical clock that starts at
`2026-09-01T00:00:00Z` and moves only forward, and only when a `CatalogAdmin` advances it. Advancing
the clock is a test-driving capability rather than a business operation: it accepts a single input,
`current_utc`, the instant to advance to, and applies every clock-driven transition whose trigger
instant falls at or before that value, in chronological order. The transitions it drives are the licensing deal's
`SIGNED → LIVE` activation, its `LIVE → EXPIRING` removal announcement and its `EXPIRING → COMPLETED`
termination, the catalogue maintenance window's `SCHEDULED → ACTIVE → COMPLETED` progression, and the
failed monthly renewal charge on a monthly subscription. After the sweep the region capacity figures
are recomputed. Advancing the clock to an instant at or before the current logical time is not a
fallback to the host clock; the clock never moves backwards. Such a request is not rejected: it
succeeds, leaves the logical time exactly where it stood, and still drives whichever clock-driven
transitions the current logical time already triggers — a later advance to the same effective instant
and an advance that names an earlier one therefore settle the transitions identically. The response to
a successful clock advance carries an empty object as its `data`.

Because every temporal predicate in this document — the half-open playable interval, the removal
notice counts, the revert cutoff, the retention window, the maintenance window, the monthly engagement
window — is evaluated against the logical clock, the same request can succeed or fail depending only
on where the clock currently stands. Implementers must therefore compare against the logical clock
everywhere a time comparison appears, and must not substitute the host's system clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding Publishers and Registering Titles

The catalogue begins with a publisher. A `CatalogAdmin` creates a `Publisher` by supplying its `name`,
which must be non-empty and unique across all publishers, together with a `home_region_code` that
records the studio's home market for reporting. A newly registered publisher is `ACTIVE` with a
`deal_count` of zero and a `lifetime_licensing_cost_cents` of zero; the account state is a two-value
enumeration, `ACTIVE` or `SUSPENDED`, and a `SUSPENDED` publisher may not have a new licensing deal
signed against it — an attempt to sign while the counterparty is suspended is rejected with
`ERR_PUBLISHER_SUSPENDED`. Suspension does not disturb deals already signed.

Titles are registered against a publisher under a `name` that must be non-empty and unique within that
publisher, and with a `platform_set` that is a non-empty subset of `CONSOLE`, `PC` and `CLOUD`
naming the platforms on which the title ships natively. Three further inputs describe the title's
commercial posture: `day_one_eligible`, a boolean defaulting to false that declares whether the title
is even a candidate for a day-one catalogue release; `list_price_cents`, a non-negative whole-cent
global default unit sale price before any regional adjustment; and `unit_sales_30d`, an integer
defaulting to zero that records the trailing thirty-day unit-sales baseline the day-one cannibalisation
projection consumes. A new title starts in `DRAFT` status and with a `weighted_engagement_score` of
zero, and it only changes status through the catalogue workflow described in §3.3. The title's
lifecycle enumeration is `DRAFT`, `RELEASED`, `RETIRED`; the score's two-decimal, round-half-up
derivation is given in §3.7.

Regions are created by supplying a `region_code` that must be unique, an ISO 4217 `currency_code`, a
strictly positive `price_multiplier`, an `availability_ceiling_titles` of at least one, and a
`catalog_tier_floor`. A region may also be created with a `maintenance_windows` list, in which case one
`CatalogMaintenance` row is instantiated per submitted window, each starting in `SCHEDULED` status and
each carrying its `region_code`, `maintenance_start`, `maintenance_end` and `capacity_reduction_pct`.
The submitted window is not required to name a region; it carries `maintenance_start`,
`maintenance_end` and `capacity_reduction_pct`, together with an optional marker tolerating overlap,
and the enclosing region create supplies the `region_code` — the enclosing region's — to every row it
instantiates. Windows of the same region whose intervals overlap and which are not explicitly marked
as tolerating overlap are rejected with `ERR_MAINTENANCE_WINDOW_OVERLAP`. Creating or reading a region
always refreshes its derived capacity figures — `capacity_required_slots`, `capacity_usable_slots`,
`capacity_utilization_pct` and `capacity_status` — per §3.7.

Subscription tiers are created by supplying a unique `tier_code`, a non-negative `monthly_price_cents`
global default, the four access switches `console_access`, `pc_access`, `cloud_access` and
`online_play_bundle`, a `member_discount_pct` between 0 and 0.4, a non-negative
`discount_retention_days`, and a non-negative `annual_prepay_credit_ratio`. A new tier starts with
`current_subscriber_count` at zero. The `member_discount_pct` must itself lie between 0 and 0.4
inclusive; a value outside that interval is a malformed request and is rejected with
`ERR_INVALID_REQUEST` (400), so no tier is ever created whose base percentage already breaches the
forty-percent cap. The two fiscal caps that the tier's configuration feeds are enforced at the
operations where the offending amount is formed rather than at tier creation: the forty-percent
maximum is applied by clamping the effective discount on a purchase (§3.8), and the annual prepay
credit is compared against the prepayment actually collected when a subscription is opened (§3.5), the
latter surfacing as `ERR_PREPAY_CREDIT_CAP_EXCEEDED` (409). Tier creation itself applies no cap check
beyond the 0–0.4 range on `member_discount_pct`.

### 3.2. Licensing Deals and the Publisher Rollup

A licensing deal binds one publisher to one title for a bounded term. The deal records its
counterparties as `publisher_id` and `title_id`, declares a `compensation_model` of `FIXED`,
`ENGAGEMENT` or `HYBRID`, and states its term as `term_start_date` (inclusive) and `term_end_date`
(exclusive). Both instants are supplied as ISO 8601 UTC; a term whose end is not strictly after its
start is rejected with `ERR_TERM_WINDOW_INVALID`. The deal also carries an `add_effective_date`, the
planned catalogue add instant, which must fall inside the half-open term window — an instant that
lands outside it is rejected with `ERR_ADD_EFFECTIVE_OUTSIDE_TERM`.

The compensation fields are conditional on the model, and the field set must match the model exactly.
A `FIXED` deal requires `monthly_fixed_fee_cents` with a value greater than zero; an `ENGAGEMENT` deal
requires both `engagement_rate_cents_per_hour` greater than zero and `monthly_engagement_cap_cents`
greater than zero; a `HYBRID` deal requires `guaranteed_compensation_cents` greater than zero and
`monthly_engagement_cap_cents` greater than zero. A body whose supplied fields do not match its
declared model is rejected with `ERR_COMPENSATION_MODEL_MISMATCH`. The four amount fields not made
mandatory by the declared model are supplied with a zero default, but that default is not uniform
across the field set: `monthly_fixed_fee_cents`, `guaranteed_compensation_cents` and
`monthly_engagement_cap_cents` may each be omitted and are then read as zero, whereas
`engagement_rate_cents_per_hour` must still be present in the body even when the model does not
require a positive rate — omitting it outright leaves the request malformed and it is rejected with
`ERR_INVALID_REQUEST` (400). A `FIXED` or `HYBRID` create that does not engage on the hourly rate
therefore still sends `engagement_rate_cents_per_hour` explicitly, typically as zero. A new deal is
created in `DRAFT` status with
`compensation_floor_cents` computed as described below and the publisher's rollup refreshed.

Signing is the act that turns a draft into a commitment, and it is performed by a `CatalogAdmin`
against a title whose `version` the client states. The body must carry `expected_title_version`, and a
mismatch with the title's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412 as
described in §2.10. Signing a deal that is no longer `DRAFT` is rejected with `ERR_DEAL_ALREADY_SIGNED`.
Signing is otherwise permitted while the publisher is `ACTIVE` and the term is well formed; two
competing deals for the same title may both be signed, since the catalogue slot simply goes to
whichever signature the client based on current state. The `DRAFT → SIGNED` transition stamps
`signed_at` with the logical clock, recomputes `compensation_floor_cents` and
`payable_compensation_cents`, refreshes the publisher's `lifetime_licensing_cost_cents` and
`deal_count`, and increments the title's `version` by exactly one — which is precisely why a second
signature attempted against a stale observation of the title fails.

The derived floor is a straightforward function of the model and the term length in whole calendar
months. Under `FIXED`, `compensation_floor_cents` is the monthly fixed fee multiplied by the term
month count. Under `ENGAGEMENT` it is zero. Under `HYBRID` it is the guaranteed monthly compensation
multiplied by the term month count. The term month count is the number of calendar months between the
term's start and its end, counted as the difference of their year-and-month ordinals — so a term that
begins and ends within one calendar month counts as one month, and a term whose end falls one calendar
month after its start counts as one month as well. The publisher rollup counts deals by status in two
different scopes: `deal_count` counts the publisher's `LicensingDeal` rows in status `SIGNED`, `LIVE`
or `EXPIRING` only, while `lifetime_licensing_cost_cents` sums `compensation_floor_cents` across the
publisher's rows in status `SIGNED`, `LIVE`, `EXPIRING` or `COMPLETED` and rounds the sum half up to
two decimals. `DRAFT` rows are counted by neither figure, so a draft deal contributes nothing until it
is signed. Both figures are recomputed on every sign and on every clock-driven deal status change.

Once the logical clock reaches the term's start instant the deal advances from `SIGNED` to `LIVE`, and
from that point catalogue entries may be created and published against it. The clock eventually takes
the deal from `LIVE` to `EXPIRING`, which happens when the clock reaches a `removal_effective_date`
that is exactly two days before `term_end_date`, and every entry of that deal currently in status
`ADDED` is moved to `REMOVING` as a single switch. Finally, when the clock reaches `term_end_date`,
the deal advances from `EXPIRING` to `COMPLETED`, every entry of that deal still in `ADDED` or
`REMOVING` is delisted, and the entitlement cascade of §3.4 runs. `COMPLETED` is the deal's only
terminal state.

A deal that is already `EXPIRING` can be saved by a `CatalogAdmin` who extends its term. The extension
supplies a `renew_term_end_date` which must be later than the current `term_end_date`, and the
logical clock must still be before the current `term_end_date`; the operation moves the deal back from
`EXPIRING` to `LIVE`. Extending the term rewrites `term_end_date`, recomputes `removal_effective_date`
as the new end minus two days, recomputes `compensation_floor_cents` and `payable_compensation_cents`
against the longer term, refreshes the publisher's `lifetime_licensing_cost_cents`, and reverts every
entry of that deal currently in `REMOVING` back to `ADDED`. Those two window conditions are the only
ones the extension applies: it does not re-validate the `removal_date` of the deal's existing entries
against the new term window.

`payable_compensation_cents` is not confined to the read-by-id response: it is a derived field carried
on the deal record and re-exposed on every deal serialization, including the create and the list. The
`compensation_view` selector, by contrast, belongs to the read-by-id operation alone. It is a query
parameter that defaults to `LEDGER`, which renders the ledger-accurate figure; requesting it as
`STATEMENT` renders the publisher-facing forecast view instead, which differs for a hybrid deal in the
manner described in §3.6. No other deal operation accepts `compensation_view`, and those other
operations always render the `LEDGER` view. The deal's own record keeps `entry_id` and
`maintenances_in_window`, both system-derived and never client-supplied. `entry_id` names the first
catalogue entry filed against the deal: it is stamped when a catalogue entry is planned for the deal's
title while the field is still empty, and a plan filed before the title carried a binding deal leaves
it empty until the entry is published, at which point the field is filled from the then-binding `LIVE`
deal. Publication does not synthesise a new entry for the deal, so an entry that already records a
`deal_id` is not re-pointed by publishing another. `maintenances_in_window` is the count of
`CatalogMaintenance` rows whose window overlaps the deal's half-open term window.

### 3.3. Catalogue Rotation and Entry Lifecycle

A catalogue entry is created by a `CatalogAdmin` to plan a title's availability in a region. The create
supplies the `title_id`, the `region_code`, a `tiers` array that must be a non-empty subset of
`ESSENTIAL`, `PREMIUM` and `ULTIMATE`, the `announced_add_date` at which the addition is published to
subscribers, a `removal_date` marking the half-open end of the playable interval, a `release_class` of
`DAY_ONE`, `BACK_CATALOG` or `CATALOG_ADD`, a `popularity_index_cents` between 0 and 10000 expressing
the title's instantaneous popularity in centi-units, and optionally a
`popularity_index_cents_30d_avg`, the trailing thirty-day average popularity in the same centi-unit
scale, which is the input the sustained-window capacity variant uses and which defaults to zero when
it is omitted. The system resolves the entry's `deal_id` from the title's binding deal — the title's
deal in status `SIGNED` or `LIVE`, and empty when the title carries no such deal, so the field may be
null on a freshly planned entry — and computes `removal_notice_days` as a whole-day count between
`announced_add_date` and `removal_date`, truncating rather than rounding; a new entry starts in
`PLANNED` status.

Two eligibility rules guard the tiers of a planned entry. Every value in `tiers` must sit at or above
the region's `catalog_tier_floor`, or the create is rejected with `ERR_TIER_BELOW_REGION_FLOOR`. And
if the entry's `tiers` include any tier whose access flags grant cloud streaming, the title must ship
on `CLOUD` in its `platform_set`; when it does not, the create is rejected with
`ERR_PLATFORM_NOT_SUPPORTED`.

Publishing is the act that puts a planned entry into the catalogue, and it is available only to an
entry that is still `PLANNED` — attempting to publish an entry that is already `ADDED`, `REMOVING` or
`DELISTED` is rejected with `ERR_ENTRY_NOT_PUBLISHABLE`. Publishing requires that the underlying
licensing deal be in status `SIGNED` or `LIVE`, that its publisher be `ACTIVE`, and that the region
still have catalogue occupancy headroom. It also requires that the entry's tier values respect the
region floor, that a `DAY_ONE` entry's title ship on `CONSOLE` in its `platform_set` — otherwise
`ERR_PLATFORM_NOT_SUPPORTED` — and that a `DAY_ONE` entry's title actually be day-one eligible,
otherwise `ERR_DAY_ONE_NOT_ELIGIBLE`. A title with no licensing deal in `LIVE` status for the region
named cannot be published or projected at all, and the attempt is rejected with `ERR_NO_BINDING_DEAL`.
When the region already holds `availability_ceiling_titles` entries in status `ADDED` or `REMOVING`,
publication fails with `ERR_REGION_CATALOG_CEILING_REACHED`, and if the logical clock currently falls
inside an `ACTIVE` maintenance window of that region the publication fails with
`ERR_REGION_MAINTENANCE_WINDOW_ACTIVE`.

A successful publication sets the entry's `actual_add_date` to the logical clock and moves it from
`PLANNED` to `ADDED`, recomputes `removal_notice_days` and `subscriber_impact_count`, and resolves
entitlements for every subscription that is eligible for this entry — that is, every subscription
whose `tier_code` appears in the entry's `tiers` and whose owner's region matches the entry's
`region_code`. An entry that was planned while its title carried no binding deal — and so holds no
`deal_id` — has that field resolved again at the moment it is published, from the title's `LIVE` deal
if one exists and left null when the title holds only a `SIGNED` deal, even though that `SIGNED` deal is
sufficient for the publication itself to proceed and to resolve entitlements. Each such subscription receives an entitlement for the (subscription, title, region)
triple, set to `ACTIVE`; a subscription whose tier grant is suspended because its billing has failed
resolves to `GRACE` instead. Publication also promotes a `DRAFT` title to `RELEASED`, recomputes the
title's `weighted_engagement_score` whenever the title is `RELEASED`, and refreshes the region's
capacity figures. Re-publishing an already-published entry does not create a second row: the selector
policy re-runs and, if it still produces the same winning entry, the existing entitlement row is
refreshed, its `access_channels` recomputed from the subscription's current tier flags, and the
one-row-per-(subscription, title, region) invariant is preserved.

### 3.4. Leaving the Catalogue, Retention and the Delisting Cascades

An `ADDED` entry leaves the catalogue by way of an announced removal. Announcing is done by a
`CatalogAdmin` and moves the entry from `ADDED` to `REMOVING`; it requires that the entry's
`removal_date` be strictly after its `actual_add_date`, and that the computed `removal_notice_days`
meet the minimum for the entry's release class. The minimum is fourteen days for `DAY_ONE`, seven days
for `CATALOG_ADD` and zero for `BACK_CATALOG`, and the comparison is inclusive at the boundary, so a
notice count exactly equal to the minimum is accepted. The notice count is the whole number of days
between `announced_add_date` and `removal_date`, computed as the difference in seconds divided by
86,400 and truncated toward zero — which means a 13.99-day notice fails the `DAY_ONE` minimum rather
than rounding up to fourteen. An entry whose `removal_date` is not strictly after its `actual_add_date`
is rejected with `ERR_REMOVAL_DATE_NOT_AFTER_ADD`, and one whose notice falls short of its class
minimum is rejected with `ERR_INSUFFICIENT_REMOVAL_NOTICE`. Announcing against an entry that is
already `REMOVING` is rejected with `ERR_REMOVAL_ALREADY_ANNOUNCED`. The transition publishes the
removal notice to subscribers, records the announcement instant as `removal_notice_announced_at` on
the entry, and recomputes `subscriber_impact_count`.

A removal announcement is reversible for a while. A `CatalogAdmin` who withdraws the announcement
moves the entry from `REMOVING` back to `ADDED`, which is permitted only while the logical clock is
strictly before `removal_date` minus three days; the three-day cutoff is strict, so a clock sitting
exactly at the cutoff instant may no longer revert, and the attempt is rejected with
`ERR_REMOVAL_REVERT_CUTOFF`. Withdrawing against an entry that is `ADDED` — that is, one with no live
announcement — is rejected with `ERR_REMOVAL_NOT_ANNOUNCED`, and one whose window has closed is
rejected with `ERR_REMOVAL_REVERT_WINDOW_CLOSED`. Withdrawing the notice clears
`removal_notice_announced_at` and recomputes `subscriber_impact_count`. This is what makes the
rotation cyclic: `ADDED` to `REMOVING` on announcement, `REMOVING` back to `ADDED` on withdrawal.

Retiring is the abrupt exit. A `CatalogAdmin` may retire an entry from either `ADDED` or `REMOVING`,
and may also retire one that never made it out of `PLANNED`. Retiring an already `DELISTED` entry is
rejected with `ERR_ENTRY_ALREADY_DELISTED`. Retiring a `PLANNED` entry simply marks it `DELISTED`,
since no catalogue membership was ever created and therefore no entitlement side effects fire at all.
Retiring a live entry is a cascade with three hops that is best understood as a fan-out followed by a
per-entry sweep:

- **Hop one** is the retirement itself: the targeted entry moves to `DELISTED`.
- **Hop two** is the delisting fan-out. Every other `CatalogEntry` belonging to the same `Title` in
  region `NA` that is currently in status `ADDED` or `REMOVING` is also moved to `DELISTED`. Note the
  asymmetry deliberately baked in here: the fan-out is scoped to the `NA` region only, whereas the
  clock-driven deal termination cascade described in §3.2 delists every entry of the deal regardless
  of region. The title's fate is then evaluated — the title moves to `RETIRED` only when it holds no
  entry at all, in any region, in status `ADDED` or `REMOVING`.
- **Hop three** is the entitlement sweep, run for every entry that hop two delisted. For each such
  entry, every `Entitlement` whose `entry_id` points at it and whose `status` is `ACTIVE` or `GRACE`
  is revoked — with one retention clause that is evaluated before any revocation. After the sweep,
  `subscriber_impact_count` is recomputed for every delisted entry, and the title's
  `weighted_engagement_score` is recomputed.

Retirement also promotes the title to `RETIRED`, and `RETIRED` is the title's terminal state. Once
retired, the title's `weighted_engagement_score` is recomputed to zero, because no `ADDED` entry
contributes to it any longer, and the title stops participating in day-one projections.

The retention clause is the single rule that lets an entitlement survive its entry's removal, and it
has two independent arms:

- A `BACK_CATALOG` entry always retains. If the delisted entry's `release_class` is `BACK_CATALOG`,
  the entitlement is never revoked, no matter how much time has passed.
- Any other entry retains only inside a bounded window. The entitlement survives if the logical clock
  is at or before the instant formed by adding the owning tier's `discount_retention_days` to the
  entry's `removal_date` and then subtracting one second. A surviving row stays `ACTIVE` and has its
  `retained_until` set to that same instant — the entry's `removal_date` plus the tier's
  `discount_retention_days`. Once the clock passes that instant, the delayed revocation fires and the
  row becomes `REVOKED`.

An entitlement's own lifecycle is `ACTIVE`, `GRACE` or `REVOKED`, with `REVOKED` terminal apart from a
single compensating path. A `CatalogAdmin` may revoke an individual entitlement as an operator action;
the attempt against one already `REVOKED` is rejected with `ERR_ENTITLEMENT_ALREADY_REVOKED`, and a
successful revocation recomputes the related entry's `subscriber_impact_count`. The compensating
action restores a `REVOKED` entitlement to `ACTIVE`, recomputing its `access_channels` from the tier
flags and restoring `subscriber_impact_count` to its pre-revocation value, but only while two
conditions hold: the subscription's `lifecycle_status` must not be `CANCELLED`, and the entitlement's
entry must still be readable by that subscription — that is, the entry's status is `ADDED` or
`REMOVING`, or its `release_class` is `BACK_CATALOG`, or its `retained_until` instant is still in the
future. The entitlement's `entry_id` is kept after a revocation for audit purposes even though no play
access remains.

Readability is defined once and reused. An `Entitlement` resolves to an entry through its `entry_id`
field, and an entry is playable at an instant when four things hold together: the entry's status is
`ADDED` or `REMOVING`, the entry's `region_code` matches the viewer's region, the instant is at or
after the entry's `actual_add_date`, and the instant is strictly before the entry's `removal_date`.
The playable interval is therefore half-open — an entry whose `removal_date` coincides exactly with the
evaluation instant is **not** playable. Readability for a subscription at an instant is the union of
three sets of entries: entries in the subscription's own region that its tier is entitled to and that
are playable at that instant, entries whose status is `DELISTED` but whose `release_class` is
`BACK_CATALOG`, and entries for which an `ACTIVE` entitlement exists whose `retained_until` is still in
the future. The second and third sets are scoped to the subscription's own active entitlements rather
than to a region: the retained `BACK_CATALOG` entry enters the set whenever any subscription anywhere
holds an active entitlement naming it, and the third set is likewise gathered from the subscription's
own `ACTIVE` entitlement rows. In the retained case the survival test is strict — the row is retained
only while the instant is strictly before `retained_until`, so an instant equal to `retained_until`
already fails the test.

### 3.5. Subscriptions, Billing and Cancellation

A `Subscriber` account is registered by an `Anonymous` caller — or by a `CatalogAdmin` acting on the
member's behalf — with an `email` that must be unique and non-empty, a `display_name`, a
`home_region_code` naming the region the subscriber pays in and reads availability from, and an
optional `wallet_credit_cents` that starts at zero when it is not supplied. The account is `ACTIVE`,
which is the only value this surface produces, and its store credit offsets future purchases.

A subscription is opened against a tier and a billing cadence. The create supplies the `subscriber_id`,
a `tier_code` of `ESSENTIAL`, `PREMIUM` or `ULTIMATE`, a `billing_period` of `MONTHLY` or `ANNUAL`,
and, for annual billing, a `prepay_amount_cents` that defaults to zero and is zero for monthly
billing. The prepay credit is the tier's `annual_prepay_credit_ratio` multiplied by the supplied
`prepay_amount_cents` and is computed for every cadence; a credit that would exceed the amount actually
collected — the only possibility being a `ratio` above one — is rejected with
`ERR_PREPAY_CREDIT_CAP_EXCEEDED`, so a monthly subscription, whose prepayment is zero, can never
breach the cap. The tier must be offered in the subscriber's region, and a request for a tier beneath
that
region's `catalog_tier_floor` is rejected with `ERR_TIER_UNSUPPORTED_IN_REGION`. The subscription's
`monthly_bill_cents` is derived at creation by the regional pricing rule in §3.7. The `tier_code` is
frozen at the moment the subscription starts and does not follow later changes to the tier catalogue.
A new subscription starts with `billing_status` `PENDING` and `lifecycle_status` `ACTIVE`, with
`unpaid_months` initialised to one for a monthly cadence and to zero for an annual cadence, and the
tier's `current_subscriber_count` is refreshed.

Opening a subscription is the only subscription write that a `Subscriber` may apply to an account other
than its own: the create accepts either role and performs no ownership comparison against
`X-User-ID`, so a `CatalogAdmin` may open a subscription for any subscriber. Every other subscription
operation named in §4 — read, pay, cancel and engagement record — checks ownership when the caller is
a `Subscriber` and rejects a foreign target with `ERR_FORBIDDEN_ROLE` (403).

Billing and lifecycle are two parallel dimensions of the same row, and they move for different reasons.
The billing dimension runs `PENDING`, `PAID`, `FAILED`; the lifecycle dimension runs `ACTIVE`, `GRACE`,
`CANCELLED`. Settling a month is a `Subscriber` action that requires at least one outstanding month —
a subscription with `unpaid_months` of zero has nothing to settle and the attempt is rejected with
`ERR_NO_UNPAID_MONTHS`. A successful settlement decrements `unpaid_months` by one and sets
`billing_status` to `PAID`; when the count reaches zero as a result, the lifecycle dimension returns to
`ACTIVE`, and every entitlement of that subscription flips from `GRACE` back to `ACTIVE` with cloud
access restored among the granted channels. The restoration is gated on the subscriber account still
being `ACTIVE`.

Failure arrives from the clock, not from a request. When the logical clock advances to a monthly
renewal instant and the renewal charge fails, a `PAID` monthly subscription moves to `FAILED`,
`unpaid_months` is incremented by one, `lifecycle_status` flips from `ACTIVE` to `GRACE`, and every
entitlement of that subscription flips from `ACTIVE` to `GRACE`. A subscription that has never paid
behaves differently: when its first charge attempt fails — which the clock sweep applies to a
`PENDING` subscription carrying no outstanding month — `unpaid_months` is set to one rather than
incremented, and the same lifecycle and entitlement flips follow. Settling the outstanding month from
`FAILED` works exactly as it does from `PENDING`: `unpaid_months` is decremented by one, and when it
reaches zero the lifecycle dimension and the entitlements return to `ACTIVE` as described above.

Cancellation is available to the owning `Subscriber` from either `ACTIVE` or `GRACE` and moves
`lifecycle_status` to `CANCELLED`, stamping `cancellation_reason` with the single value
`USER_INITIATED`. Cancellation carries no retention clause and makes no time comparison: every
entitlement of that subscription becomes `REVOKED` immediately, all channels close including any
retained purchase access for catalogue titles, the `subscriber_impact_count` of every entry those
entitlements named is recomputed, and the tier's `current_subscriber_count` is refreshed. `CANCELLED`
is terminal — a subscription that has been cancelled accepts no further transitions, and any attempt
to pay it, cancel it again, or record engagement against it is rejected with
`ERR_SUBSCRIPTION_TERMINAL`.

### 3.6. What a Publisher Is Paid, and How Engagement Is Measured

A deal's `payable_compensation_cents` is derived when the deal enters `SIGNED` and again whenever the
logical clock crosses a term-month boundary. The procedure is defined in whole calendar months of the
term, counted as the difference between the term end's year-and-month ordinal and the term start's
year-and-month ordinal; a term that starts and ends inside the same calendar month therefore spans one
month. For each such month of the term window, the system sums the `normalized_hours` of the deal
title's engagement events whose `created_at` falls inside that calendar month — an event landing
exactly on `term_start_date` belongs to the first month, and an event landing exactly on
`term_end_date` is excluded from the term entirely, as are all events outside the half-open
`[term_start_date, term_end_date)` window. That monthly hour total is multiplied by the deal's
`engagement_rate_cents_per_hour` to form the month's raw engagement amount, and the raw amount is then
capped: the month's capped amount is the smaller of the raw amount and the deal's
`monthly_engagement_cap_cents`. The cap is applied to each month separately, before any summing. Summing
the capped monthly amounts across the term produces the deal's engagement component.

How the engagement component is used depends on the compensation model. A `FIXED` deal's total is the
fixed component alone: `monthly_fixed_fee_cents` multiplied by the term month count. An `ENGAGEMENT`
deal's total is the engagement component alone. A `HYBRID` deal's total is the larger of two figures —
the sum of the fixed component and a quarter of the engagement component, or the guaranteed floor,
which is `guaranteed_compensation_cents` multiplied by the term month count. The quarter share is
formed on the already-summed, already-capped engagement component, never on the per-month amounts. One
single rounding is applied at the very end of the whole procedure: the total is rounded half up to two
decimal places to produce `payable_compensation_cents`. The multiplication that forms the fixed
component, the multiplication that forms the floor component, and the per-month cap all happen before
that final rounding and are never rounded on their own.

The statement view of a hybrid deal differs in exactly one respect, and it is the reason the two views
can disagree. In the publisher-facing statement rendering, the quarter share is formed per month on
that month's capped engagement amount with no intermediate rounding, and the monthly shares are then
summed and the sum is rounded half up to two decimals before it is added to the fixed component and the
result compared against the guaranteed floor. The ledger view forms the same quarter share once on the
already-summed, already-capped engagement component and adds it to the fixed component with no
intermediate rounding. The cap itself is applied to the raw monthly engagement amount in both
renderings, so the two views agree on the engagement component and can differ only in the last cents,
and only when the share sum is not already an exact two-decimal value.

Deals contribute to the term total only from `SIGNED` onward: a `DRAFT` deal, and a deal that has been
terminated, contributes nothing. The events that feed the term total are the engagement events of the
deal's title, and an event carries the `subscription_id` and `title_id` it belongs to, a
`session_hours` of zero or more, a `channel` of `CONSOLE`, `PC`, `CLOUD` or `ONLINE_PLAY`, and an
`engagement_multiplier` greater than zero that weights the session — a day-one title during its launch
window might carry a higher multiplier than an older catalogue title.

The multiplier is applied exactly once, at the moment the event is recorded. A new event's
`normalized_hours` is the product of its `session_hours` and its `engagement_multiplier`, rounded half
up to four decimal places — the only place in the system where four-decimal precision appears — and
that value is frozen on the row. It is never recomputed, not when the multiplier configuration
changes and not when the logical clock advances; a stored event is immutable in this respect.

Each subscription also carries an `engagement_score` in index points, and a supporting
`monthly_engaged_hours_avg`. Both are recomputed on every new engagement event and on every monthly
rollover driven by the clock. The window is the calendar month of the logical clock: from the first
instant of the current UTC calendar month up to, but not including, the first instant of the next. The
events considered are that subscription's events with `created_at` inside the window; events from
earlier months leave the window but are never deleted. The average is the sum of the window's
`normalized_hours` divided by the number of events in the window, held exactly and without rounding;
the mean of an empty window is zero rather than an error. The `engagement_score` is that exact average
rounded half up to two decimal places and then clamped at a ceiling of 100, so no subscriber's score
can exceed one hundred index points.

The analyst export reproduces a legacy spreadsheet column and differs from the live score in one
narrow way: it first quantises the exact mean to seven decimal places using round-half-even and only
then rounds that quantised value to two decimal places using round-half-up. The two variants agree
except when the exact mean is an exact two-decimal tie — a mean of 7.345 is reported as 7.34 in the
export column and as 7.35 by the base score. The export column is a reporting artefact rather than an
API surface: no operation in §4 exposes it, so every response that carries an engagement figure —
`monthly_engaged_hours_avg` and `engagement_score` on a subscription, and the tier analytics that read
them — reports the base variant described above.

### 3.7. Derived Figures: Pricing, Capacity, Engagement Weight and Retention Index

**Regional monthly pricing.** When a subscription is opened, its `monthly_bill_cents` is derived from
the tier's `monthly_price_cents` and the subscriber's region. The region's `price_multiplier` is the
starting multiplier; if that multiplier is strictly greater than 1.50, it is replaced by the product of
the multiplier and 0.90, rounded half up to four decimal places; the resulting multiplier is then
raised to at least 0.50, and the regional monthly price is the tier's global default multiplied by that
final multiplier, rounded half up to two decimal places. Two boundary facts matter. The comparison
against 1.50 is strict, so a region sitting at exactly 1.50 uses its raw multiplier and does not take
the blend. And the tier's `monthly_price_cents` is read but never mutated by this calculation — the
global default remains the global default, and each region's price is derived freshly from it. Every
regional price in the system — the billed monthly price and the per-unit list price on a purchase —
uses this one multiplier rule; there is no alternative blend rule anywhere in the API. Region creation
declines any `price_multiplier` below 0.50 outright as an invalid request, so the floor clamp is a
defensive guard rather than a common path.

**Streaming capacity allocation.** Each region's capacity picture is recomputed whenever a capacity
view is read and whenever an entry is published or retired and whenever a maintenance window
transitions. The active entry set for a region is the entries whose `region_code` matches and for which
the logical clock is at or after `actual_add_date` and strictly before `removal_date` — the same
half-open predicate used throughout §3.4. Each active entry contributes base slots equal to its
`popularity_index_cents` multiplied by 0.5, and the base requirement is the sum of those contributions.
An entry counts as a launch entry while the clock is within fourteen days of its `actual_add_date`, and
each launch entry contributes an additional spike term of its `popularity_index_cents` multiplied by
0.5 and then by 0.40. The raw requirement is the base requirement plus the spike terms plus a fixed
overhead of 200 slots for the region. On the supply side, usable slots are the region's
`availability_ceiling_titles` multiplied by 30; if any maintenance row for that region is currently
active — that is, its `maintenance_start` is at or before the clock and its `maintenance_end` is after
it — the usable slot count is reduced by the window's `capacity_reduction_pct` and rounded half up to
two decimals. The deficit, exposed as `capacity_deficit_slots`, is the raw requirement minus the
usable slots, so a negative deficit means headroom. Utilisation is the raw requirement divided by the usable slots, multiplied by one hundred and
rounded half up to two decimals — and it is reported as 0.00 when usable slots are zero, rather than as
a division error. The region's `capacity_status` reads `OVER_CAPACITY` when the raw requirement is
strictly greater than the usable slots, and `WITHIN_CAPACITY` otherwise; a region exactly at its
capacity is therefore `WITHIN_CAPACITY`. The five figures — `capacity_required_slots`,
`capacity_usable_slots`, `capacity_deficit_slots`, `capacity_utilization_pct` and `capacity_status` —
are reported together on a region read and on the region's own create response. The live derivation
above is the only capacity variant the API performs; `popularity_index_cents_30d_avg` is accepted and
stored on a catalogue entry but no endpoint computes a capacity figure from it.

The monthly fleet-planning variant of this derivation differs in two ways: it uses each entry's
`popularity_index_cents_30d_avg` in place of its instantaneous `popularity_index_cents`, and it drops
the launch-spike term entirely. A title inside its first fourteen days therefore inflates the live
figure but not the monthly planning figure.

**Title engagement weighting.** A title's `weighted_engagement_score` is recomputed on every publish
and on every retirement, over the title's entries in status `ADDED` or `REMOVING` only; `PLANNED` and
`DELISTED` entries contribute nothing. Each contributing entry contributes its `popularity_index_cents`
divided by one hundred and then multiplied by a tier weight. The tier weight of an entry is the
**highest** weight among the tiers listed in that entry's `tiers` array, not the average of them, with
`ESSENTIAL` weighted 1.00, `PREMIUM` weighted 1.50 and `ULTIMATE` weighted 2.00; a multi-tier entry is
therefore weighted by its top tier alone. The contributions are summed and the sum is rounded half up
to two decimal places. A title that loses its last live entry has its score recomputed to 0.00, since
it then contributes no entries at all.

**Deal window occupancy.** A deal's `maintenances_in_window` counts the region's maintenance rows whose
window overlaps the deal's half-open `[term_start_date, term_end_date)` interval. It is a reporting
figure maintained with the deal and never supplied by a client. It counts every maintenance row
anywhere in the system whose interval overlaps that deal term, regardless of the region the row names,
so it is a global overlap count rather than one scoped to the deal title's own region.

### 3.8. Member Purchases, Discounts and the Unit-Sales Ledger

A member buys a catalogue title outright by naming the `subscriber_id`, the `title_id`, the `entry_id`
whose release class selects the discount treatment, the `region_code` the price is presented in, and an
optional `quantity` of at least one that defaults to one. The named entry must belong to the named
title; an entry that belongs to a different title is rejected with `ERR_ENTRY_TITLE_MISMATCH`. The
quantity scales the unit-sales credit only — it does not multiply the discount, the wallet offset or
the amount charged to the card.

The discount the buyer receives comes from a tier, and the tier is resolved from the buyer's
subscription rather than from the named entry. The system takes the buyer's earliest-created
subscription that is still in lifecycle `ACTIVE` or `GRACE`, falling back to the buyer's
earliest-created subscription of any lifecycle state when none is live, and uses that subscription's
`tier_code` to look up the tier. When the subscriber holds no subscription at all the purchase is
priced with a zero base discount and a zero retention period — no tier lookup is attempted and the
purchase still succeeds.

The price derivation proceeds in a pinned order. The regional list price per unit is the title's
`list_price_cents` multiplied by the region's `price_multiplier`, rounded half up to two decimals, and
that value is exposed as `list_price_cents_per_unit`. The tier's `member_discount_pct` — the base
discount carried by the tier the buyer subscribes to — is then augmented: a purchase naming an entry
whose `release_class` is `BACK_CATALOG` adds a retention bonus of 0.05 to the tier's base percentage,
while any other release class adds nothing. The summed percentage is clamped at a maximum of 0.40, so
no effective discount can exceed forty percent; the clamp is applied silently rather than as a
rejection, so a `BACK_CATALOG` purchase by a tier whose base percentage is already 0.40 completes at
exactly 0.40 rather than being refused, and no purchase that names an existing tier is ever rejected
for exceeding the discount cap (the error code `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED` is reserved in the
catalogue but no operation in this API raises it). The effective
percentage is recorded on the row as `discount_pct_applied`, held to two decimals with round-half-up;
under the base treatment — that is, for any entry whose release class is not `BACK_CATALOG` — the bonus
is zero and the effective discount is exactly the tier's base percentage, which may itself be zero.

The discount amount is the regional list price multiplied by the effective percentage, rounded half up
to two decimals, and it is subtracted from the regional list price to form the subtotal. Then wallet
credit is applied: the amount offset is the smaller of the buyer's current `wallet_credit_cents` and
the subtotal, so wallet credit can never exceed the discounted subtotal, and that amount is recorded as
`wallet_applied_cents`. The `total_charged_cents` is the subtotal minus the wallet offset. Finally the
`unit_sales_credit_cents` is the total charged multiplied by the purchase `quantity`. Two ordering
facts are part of the contract. The discount amount is rounded first and subtracted second, so the list
price is never re-rounded after the subtraction and the subtraction itself introduces no rounding; and
the wallet subtraction is never rounded at all. A purchase that names a `BACK_CATALOG` entry is
therefore strictly cheaper than an otherwise identical purchase of a `CATALOG_ADD` entry, by exactly
the difference between the two rounded discount amounts.

Completing a purchase consumes the offset amount from the buyer's `wallet_credit_cents`, records the
per-unit price, the applied discount, the wallet offset and the total charged on the row, sets
`unit_sales_credit_cents` per the rule above, and starts the row in `COMPLETED` status. A purchase
response is stable thereafter: reading it back re-exposes the same figures unchanged.

Reversal is the compensating action, available to a `CatalogAdmin` while the purchase is `COMPLETED`;
a second reversal of an already-`REFUNDED` row is rejected with `ERR_PURCHASE_ALREADY_REVERSED`. It
sets the row's status to `REFUNDED`, increases the subscriber's `wallet_credit_cents` by the retained
`wallet_applied_cents` — so the subscriber's live balance plus the retained offset reconciles to the
balance they held before the purchase — retains `wallet_applied_cents` and `unit_sales_credit_cents` on
the row for audit, and removes the row from the sales accumulator that the reconciled cannibalisation
figure reads. The row is never deleted. A separate `wallet_restored_cents` field records the credit
returned by a reversal and is zero for every row that is still `COMPLETED`.

The tier's `discount_retention_days` is the field that lets a member keep the discount they bought
under: as described in §3.4, a purchase's entitlement survives its title's removal for that many days
beyond the entry's `removal_date`, subject to the one-second strictness rule stated there. The tier's
`current_subscriber_count` is maintained in step with subscription state: it counts the tier's
`Subscription` rows whose lifecycle dimension is `ACTIVE` or `GRACE`, and it is recomputed whenever a
subscription is opened, cancelled, or moves between lifecycle states.

### 3.9. Day-One Release Economics

The day-one question is whether pushing a title into the catalogue on its launch day earns more in
subscription value than it loses in outright sales. A `CatalogAnalyst` — or a `CatalogAdmin` — opens a
prospective `AvailabilityProjection` for a title in a region by supplying the `title_id`, the
`region_code`, a `launch_subscriber_count` of zero or more, a `tier_step_count` of zero or more
measuring how many tier steps above the release's lowest tier the release reaches, a
`projected_unit_sales_units` of zero or more for the units expected to sell outright over the horizon,
and a `release_class` of `DAY_ONE`, `BACK_CATALOG` or `CATALOG_ADD`. The title must have a licensing deal in
`LIVE` status — otherwise the projection is refused with `ERR_NO_BINDING_DEAL`. The `region_code` is
stored on the projection but is not matched against the deal, which carries no region of its own, so
the same title's live deal backs a projection in any region; a title whose only deal is still `SIGNED`,
or whose deal has already advanced past `LIVE` into `EXPIRING` or `COMPLETED`, is refused. At most one
`FINALIZED` `DAY_ONE` projection may exist for a given (title,
region) pair; an attempt to create or finalize a second one is rejected with
`ERR_DUPLICATE_DAY_ONE_PROJECTION`, and on the create path that duplicate check is reached only after
the binding deal has resolved, so a title with no live deal reports `ERR_NO_BINDING_DEAL` ahead of any
duplicate. A new projection starts in `DRAFT` status with all four derived
figures recomputed immediately.

The projection's binding deal supplies two of the inputs: its `engagement_rate_cents_per_hour` and its
`monthly_engagement_cap_cents`, together with a term length in whole calendar months counted as the
difference between the deal's term-end month and term-start month — a term that spans a single day
therefore counts as one month. From those inputs the subscription upside is built:

- The per-subscriber hour expectation is the title's `unit_sales_30d` multiplied by 1.25 lost hours per
  unit sold.
- The theoretical gross engagement hours are that per-subscriber average multiplied by the projection's
  `launch_subscriber_count`, and the theoretical gross amount is those hours multiplied by the deal's
  engagement rate per hour.
- The capped engagement amount is the smaller of the theoretical gross amount and the deal's
  `monthly_engagement_cap_cents` multiplied by the term month count — that is, the monthly cap scaled
  to the length of the term.
- The net-new subscription value is the capped engagement amount multiplied by 0.60, rounded half up to
  two decimals.
- The tier uplift is the capped engagement amount multiplied by 0.05 and then by the projection's
  `tier_step_count`, rounded half up to two decimals, and then capped at a maximum of 250,000 cents.
  The cap applies to the tier-uplift term alone, after its own rounding.
- The `projected_subscription_value_cents` is the net-new value plus the tier uplift.

The unit-sales downside is projected in parallel. The title's regional list price per unit is its
`list_price_cents` multiplied by the region's `price_multiplier`, rounded half up to two decimals; the
gross projected sales are the projection's `projected_unit_sales_units` multiplied by that price; and
`projected_cannibalized_unit_sales_cents` is that gross multiplied by 0.30, rounded half up to two
decimals. The `projected_net_value_cents` is the projected subscription value minus the projected
cannibalised unit sales.

The release decision is read off a ladder that is evaluated strictly in the order below, and the first
rung that matches wins:

1. If the projected net value is at least zero **and** the title's `day_one_eligible` flag is true
   **and** the projection's `release_class` is `DAY_ONE`, the decision is `APPROVE_DAY_ONE`.
2. Otherwise, if the projected net value is at least negative 50,000 cents, the decision is
   `HOLD_FOR_CATALOG`.
3. Otherwise the decision is `REJECT_DAY_ONE`.

The outcome of the ladder is exposed on the projection as `decision`, whose only permitted values are
`APPROVE_DAY_ONE`, `HOLD_FOR_CATALOG` and `REJECT_DAY_ONE`.

Note that the second rung is reached only when the first rung's conjunction fails — including the case
where the net value clears zero but the title is not day-one eligible or the class is not `DAY_ONE`, in
which case a favourable projection is held for the catalogue rather than approved.

Finalizing a projection freezes it and reconciles the cannibalised figure against what actually
happened. Finalization moves the projection from `DRAFT` to `FINALIZED`; attempting it twice is
rejected with `ERR_PROJECTION_ALREADY_FINALIZED`, and attempting to finalize a second `DAY_ONE`
projection for a title-and-region pair that already has one is rejected with
`ERR_DUPLICATE_DAY_ONE_PROJECTION`. Instead of projecting cannibalisation from units and price, the
finalized view accumulates the actual purchase revenue: every `Purchase` row for the same title and
region whose status is `COMPLETED` is taken in ascending `created_at` order, and their
`total_charged_cents` are accumulated into a running total. Two rows sharing a `created_at` are
accumulated in the order they were persisted, which is stable across re-reads. `REFUNDED` rows are
excluded, so a reversed purchase drops out of the accumulator. That running total is multiplied once by
0.30 and rounded once at the end to two decimals, becoming the finalized
`projected_cannibalized_unit_sales_cents`. The `projected_net_value_cents` and the decision are then
re-derived from the new downside figure against the unchanged subscription upside, and the difference
between the finalized and the provisional cannibalised figure is exposed on the response as the
provisional-to-final delta, under the key `provisional_to_final_delta_cents` and mirrored under the
alias `cannibalization_delta_cents`, both carrying the same value. Those two keys appear only on the
finalize response; a projection read or list does not carry them. That delta equals 0.30 multiplied by
the total of the discounts and wallet
credits actually granted on the completed purchases, because the accumulator is built from amounts
charged rather than from list prices.

One variant of the day-one arithmetic belongs to the deal desk rather than to the analyst. When a desk
renegotiates an existing agreement it may ask for a rendering in which the monthly cap is applied to
the engagement **share** — the capped engagement amount multiplied by the hybrid quarter share —
rather than to the gross engagement amount, so the capped term becomes a quarter of what the standard
rendering produces and the net-new subscription value is correspondingly smaller whenever the cap
binds. This is a scenario variant rather than an API surface: no projection operation in §4 accepts a
selector for it, and every projection the API computes uses the standard rendering, which applies the
cap to the gross engagement figure as described above.

### 3.10. Tier Analytics

Reading a tier's analytics reports four numbers derived from that tier's subscription population. The
`current_subscriber_count` is the count of the tier's subscriptions whose lifecycle dimension is
`ACTIVE` or `GRACE`. The `retention_pct` is one hundred times the count of the tier's subscriptions in
lifecycle status `ACTIVE` or `GRACE`, divided by the larger of one and the tier's
`current_subscriber_count`, rounded half up to two decimals. The `conversion_pct` is one hundred times
the count of the tier's subscriptions that have at least one purchase, divided by the same
larger-of-one denominator, rounded half up to two decimals — and because the purchase predicate tests
only for the existence of a purchase row, a subscription in `GRACE` counts toward conversion exactly
as an `ACTIVE` one does, and so does a subscription whose only purchase has since been reversed. The
`normalized_engagement` figure is one hundred times the tier's average monthly engaged hours, where
that average is the population's `monthly_engaged_hours_avg` divided by 2.0 hours per index point and
then multiplied by one hundred, rounded half up to two decimals and clamped at a ceiling of 100.00.

The `conversion_retention_index` is the weighted sum of those three components: 0.60 times
`retention_pct`, plus 0.25 times `conversion_pct`, plus 0.15 times `normalized_engagement`, with the
whole sum rounded half up to two decimals. The index is a read-only aggregate. It never feeds a
selector, a ranking or a tie-break anywhere in the system — in particular it plays no part in choosing
which catalogue entry an entitlement resolves to.

A holdout-calibrated board variant of the same index moves the weights to 0.50, 0.30 and 0.20 and
substitutes the subscription's `engagement_score` — which is already clamped and already rounded, as
described in §3.6 — for the freshly computed `normalized_engagement`. Like the deal-desk day-one
variant of §3.9 this is a scenario variant without an API selector: the tier analytics endpoint
computes only the 0.60/0.25/0.15 index from the freshly computed `normalized_engagement`, and no
operation reports the board-weighted index.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a new distinct resource to a
collection, return `201 Created`. Operations that modify an existing resource — including state
transitions, compensating actions and the clock advance — return `200 OK`. Reads return `200 OK`.
Every path below is mounted under the API's `/catalog` prefix, and every request must carry the
`X-User-ID` and `X-User-Role` headers described in §2.1. One path sits outside that prefix and outside
the envelope contract: `GET /health` answers with the bare object `{"status": "ok"}` and requires no
headers.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalog/publishers` | Create a Publisher account | CatalogAdmin |
| GET | `/catalog/publishers/{publisher_id}` | Read a Publisher with its rollup figures | CatalogAdmin, CatalogAnalyst, Subscriber |
| POST | `/catalog/titles` | Create a Title owned by a Publisher | CatalogAdmin |
| GET | `/catalog/titles/{title_id}` | Read a Title | CatalogAdmin, CatalogAnalyst, Subscriber |
| GET | `/catalog/titles` | List Titles, optionally filtered by publisher | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/regions` | Create a Region, optionally with planned streaming maintenance windows | CatalogAdmin |
| GET | `/catalog/regions/{region_code}` | Read a Region including its derived capacity figures | CatalogAdmin, CatalogAnalyst, Subscriber |
| POST | `/catalog/tiers` | Create a SubscriptionTier | CatalogAdmin |
| GET | `/catalog/tiers/{tier_code}` | Read a SubscriptionTier | CatalogAdmin, CatalogAnalyst, Subscriber |
| GET | `/catalog/tiers/{tier_code}/analytics` | Computed read: conversion and retention analytics for a tier | CatalogAnalyst |
| POST | `/catalog/licensing-deals` | Create a LicensingDeal in DRAFT | CatalogAdmin |
| GET | `/catalog/licensing-deals/{deal_id}` | Read a LicensingDeal | CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/licensing-deals` | List LicensingDeals, optionally filtered by publisher, title or status | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/licensing-deals/{deal_id}/sign` | Sign a DRAFT LicensingDeal under optimistic concurrency on the licensing Title | CatalogAdmin |
| POST | `/catalog/licensing-deals/{deal_id}/renew` | Extend the term of an EXPIRING deal before its end date | CatalogAdmin |
| POST | `/catalog/catalog-entries` | Plan a catalog entry for a title in a region | CatalogAdmin |
| GET | `/catalog/catalog-entries/{entry_id}` | Read a CatalogEntry | CatalogAdmin, CatalogAnalyst, Subscriber |
| GET | `/catalog/catalog-entries` | List CatalogEntries, optionally filtered by region, title, deal or status | CatalogAdmin, CatalogAnalyst, Subscriber |
| POST | `/catalog/catalog-entries/{entry_id}/publish` | Publish a planned entry and resolve entitlements for eligible subscriptions | CatalogAdmin |
| POST | `/catalog/catalog-entries/{entry_id}/announce-removal` | Announce that an ADDED entry is leaving the catalog | CatalogAdmin |
| POST | `/catalog/catalog-entries/{entry_id}/cancel-removal` | Revert an announced removal before the revert cutoff | CatalogAdmin |
| POST | `/catalog/catalog-entries/{entry_id}/retire` | Retire an entry, cascading delisting and revoking entitlements | CatalogAdmin |
| GET | `/catalog/catalog-maintenances/{maintenance_id}` | Read a single CatalogMaintenance window | CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/catalog-maintenances` | List CatalogMaintenance windows, optionally filtered by region or status | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/subscribers` | Register a Subscriber | Anonymous, CatalogAdmin |
| GET | `/catalog/subscribers/{subscriber_id}` | Read a single Subscriber | Subscriber, CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/subscribers` | List Subscribers, optionally filtered by home region | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/subscriptions` | Open a Subscription for a Subscriber | Subscriber, CatalogAdmin |
| GET | `/catalog/subscriptions/{subscription_id}` | Read a Subscription | Subscriber, CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/subscriptions` | List Subscriptions, optionally filtered by subscriber, tier or lifecycle state | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/subscriptions/{subscription_id}/pay` | Settle one outstanding billing month | Subscriber |
| POST | `/catalog/subscriptions/{subscription_id}/cancel` | Cancel a Subscription and revoke its entitlements | Subscriber |
| POST | `/catalog/subscriptions/{subscription_id}/engagement-events` | Record an engagement event and refresh the engagement score | Subscriber |
| GET | `/catalog/engagement-events/{event_id}` | Read a single EngagementEvent | Subscriber, CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/engagement-events` | List engagement events, optionally filtered by subscription or title | CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/entitlements` | List Entitlements, optionally filtered by subscription, title, region, entry or status | Subscriber, CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/entitlements/{entitlement_id}` | Read a single Entitlement | Subscriber, CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/entitlements/{entitlement_id}/revoke` | Revoke a single entitlement as an operator action | CatalogAdmin |
| POST | `/catalog/entitlements/{entitlement_id}/restore` | Compensating action: restore an entitlement while its entry is still readable | CatalogAdmin |
| POST | `/catalog/purchases` | Buy a catalog title outright | Subscriber |
| GET | `/catalog/purchases/{purchase_id}` | Read a single Purchase | Subscriber, CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/purchases/{purchase_id}/reverse` | Compensating action: refund the charge and restore the wallet offset | CatalogAdmin |
| GET | `/catalog/purchases` | List Purchases, optionally filtered by subscriber, title, entry or region | Subscriber, CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/availability-projections` | Project the day-one release economics for a title in a region | CatalogAnalyst, CatalogAdmin |
| GET | `/catalog/availability-projections/{projection_id}` | Read an AvailabilityProjection | CatalogAdmin, CatalogAnalyst |
| GET | `/catalog/availability-projections` | List AvailabilityProjections, optionally filtered by title or region | CatalogAdmin, CatalogAnalyst |
| POST | `/catalog/availability-projections/{projection_id}/finalize` | Freeze a projection and re-derive the cannibalized figure from actual purchases | CatalogAnalyst, CatalogAdmin |
| POST | `/catalog/_clock/set_current_utc` | Test-driving clock control: advance the logical clock | CatalogAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier the API can return together with its HTTP status code.
Trigger conditions are deliberately omitted here; they are stated in the narrative sections that
govern each rule (see §2.1–§2.12 and §3.1–§3.10).

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PUBLISHER_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_NOT_FOUND` | 404 Not Found |
| `ERR_REGION_NOT_FOUND` | 404 Not Found |
| `ERR_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_DEAL_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECTION_NOT_FOUND` | 404 Not Found |
| `ERR_DEAL_ALREADY_SIGNED` | 409 Conflict |
| `ERR_ENTRY_NOT_PUBLISHABLE` | 409 Conflict |
| `ERR_ENTRY_ALREADY_DELISTED` | 409 Conflict |
| `ERR_REMOVAL_ALREADY_ANNOUNCED` | 409 Conflict |
| `ERR_REMOVAL_NOT_ANNOUNCED` | 409 Conflict |
| `ERR_REMOVAL_REVERT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SUBSCRIPTION_TERMINAL` | 409 Conflict |
| `ERR_NO_UNPAID_MONTHS` | 409 Conflict |
| `ERR_ENTITLEMENT_ALREADY_REVOKED` | 409 Conflict |
| `ERR_PROJECTION_ALREADY_FINALIZED` | 409 Conflict |
| `ERR_TERM_WINDOW_INVALID` | 409 Conflict |
| `ERR_ADD_EFFECTIVE_OUTSIDE_TERM` | 409 Conflict |
| `ERR_REMOVAL_DATE_NOT_AFTER_ADD` | 409 Conflict |
| `ERR_INSUFFICIENT_REMOVAL_NOTICE` | 409 Conflict |
| `ERR_REMOVAL_REVERT_CUTOFF` | 409 Conflict |
| `ERR_REGION_MAINTENANCE_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PUBLISHER_SUSPENDED` | 409 Conflict |
| `ERR_TIER_UNSUPPORTED_IN_REGION` | 409 Conflict |
| `ERR_TIER_BELOW_REGION_FLOOR` | 409 Conflict |
| `ERR_PLATFORM_NOT_SUPPORTED` | 409 Conflict |
| `ERR_DAY_ONE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_ENTRY_TITLE_MISMATCH` | 409 Conflict |
| `ERR_NO_BINDING_DEAL` | 409 Conflict |
| `ERR_DUPLICATE_DAY_ONE_PROJECTION` | 409 Conflict |
| `ERR_COMPENSATION_MODEL_MISMATCH` | 409 Conflict |
| `ERR_PURCHASE_ALREADY_REVERSED` | 409 Conflict |
| `ERR_REGION_CATALOG_CEILING_REACHED` | 409 Conflict |
| `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED` | 409 Conflict |
| `ERR_PREPAY_CREDIT_CAP_EXCEEDED` | 409 Conflict |
