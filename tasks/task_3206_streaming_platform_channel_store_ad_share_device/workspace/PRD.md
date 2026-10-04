# Streaming Platform Channel Store, Ad Share & Device Distribution API — Product Requirements Document

## 1. Introduction

A large-scale streaming platform operates a three-sided marketplace: publishers ship channels into the platform's channel store, advertisers and publishers buy home-screen promotional placement, and the platform's own operating system runs on streaming devices and licensed televisions. Money moves in two directions at once — viewers pay for channel subscriptions through platform billing, while ad revenue from publisher inventory is split between the publisher and the platform — and every one of these flows must be reconciled monthly into a single, disputable revenue statement per publisher.

This document specifies the REST API that governs that marketplace end to end. It covers publisher onboarding and standing discipline; channel certification with a revision loop and a content-policy hold mechanism; viewer subscriptions with a payment dimension and an access dimension that evolve separately; ad inventory grants whose publisher/platform split can be recomputed as publisher standing changes; promotional campaigns with budget-capped measurement and home-screen placement bookings on half-open windows; television manufacturer licensing, device-model certification with lab-bench scheduling, and mandatory OS update compliance; device hardware sold near cost with the subsidy recovered by one of two recovery policies; and a monthly statement pipeline whose tiered fee selection, dual-variant payout arithmetic, and negative-net balance accrual form the platform's reconciliation backbone.

Every rule here exists because two parties can disagree about it later. Refunds must land in the statement period containing the refund rather than the period containing the original charge; rounding order on per-entry ad revenue is pinned so a publisher auditing a statement gets the same number the platform computed; a stale client writing against an advanced channel version is rejected rather than silently superseding a certification version it never saw. Implementations should read §2 for system-wide contracts and §3 for the business workflows those contracts serve.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly to every endpoint, entity, and workflow in the system.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting caller, and `X-User-Role`, naming the caller's operational role. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled exactly as follows: `PlatformAdmin`, `AdOps`, `Publisher`, `Viewer`, and `TvManufacturer`.

Three of these roles are entity-backed, meaning `X-User-ID` is the `id` of a persisted entity and ownership checks compare resource foreign keys to it. When `X-User-Role` is `Publisher`, `X-User-ID` is the `id` of the acting `Publisher`; ownership checks on any resource that references a publisher — a channel, a campaign, a statement, a dispute — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When `X-User-Role` is `Viewer`, `X-User-ID` is the `id` of the acting `ViewerAccount`; the same comparison applies to subscriptions, privacy records, and device units that reference a viewer. When `X-User-Role` is `TvManufacturer`, `X-User-ID` is the `id` of the acting `TvManufacturer`, and ownership of device models, lab bookings derived from those models, and manufactured units is enforced the same way.

The remaining two roles are opaque operator identities. When `X-User-Role` is `PlatformAdmin` or `AdOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and these two roles are never the subject of ownership checks — their authority comes from the role alone. `PlatformAdmin` is the platform operator: it owns publisher onboarding and standing, channel publication and removal, certification decisions, viewer account creation, refunds, ad-grant administration, manufacturer licensing, OS update administration, device sales, statement generation/finalization/settlement, dispute adjudication, and the logical clock. `AdOps` runs the advertising business: campaign start/pause/resume, impression recording, placement booking confirmation and release, ad-slot revenue recording, and device subsidy recovery entries.

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

Endpoints that return lists of resources accept two optional query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The platform's notion of "now" is a logical clock, not wall-clock time. Before any clock call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and the server must never fall back to wall-clock time. A `PlatformAdmin` advances the logical clock through an admin-only test-driving capability that sets the current instant to a supplied `to_iso8601` timestamp; the call returns the new clock reading as `current_utc` and mutates no entity. Every time-sensitive rule in the system — subscription period attribution, refund attribution, campaign flight windows, placement booking windows, lab windows, OS update deadlines, appeal windows, pacing projection — reads this logical clock and only this clock.

### 2.5. Common Resource Properties

Every primary resource in the system — publishers, channels, channel versions, viewer accounts, subscriptions, ad slot grants, ad campaigns, placement bookings, manufacturers, device models, lab bookings, OS updates, device units, revenue statements, and disputes — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): starts at creation and increments by exactly 1 on every mutation of the resource. This field backs optimistic concurrency control (§2.7).

Cascading mutations follow the same discipline: when one operation mutates several entities (a channel suspension pausing campaigns and releasing bookings, a statement finalization updating the publisher's tier and balance), each mutated entity has its own `updated_at` refreshed and its own `version` incremented.

### 2.6. Monetary Precision and Rounding

All money in the system is integer cents; all percentages are integer basis points where 10000 basis points is the whole. Final amounts that require rounding — per-entry ad revenue shares, subscription payouts, impression costs, pacing projections, monetization-based subsidy recovery — use round-half-up to the nearest integer cent. Signed round-half-up rounds away from zero on an exact half for negative inputs, which matters because statement nets and subscription bases can be negative. Slot-count splits and straight-line subsidy recovery use integer floor instead, as specified in §3. No floating-point arithmetic is permitted anywhere a monetary value is computed or compared.

### 2.7. Optimistic Concurrency Control

Two write operations carry a mandatory optimistic-concurrency guard, and only these two.

First, submitting a new channel version for certification requires the request to carry `expected_channel_version`, the version of the parent channel the client last observed. If the channel's current `version` has advanced beyond that observed value, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because superseding a `SUBMITTED` version is legitimate product behavior: a client holding a stale channel version would otherwise silently supersede a certification version it never saw.

Second, re-splitting an ad slot grant requires the request to carry `expected_grant_version`, the version of the grant the client last observed. A grant in `OPEN` status may be re-split repeatedly as publisher standing changes, so only this check distinguishes a write based on a stale split from one based on a fresh one; a mismatch with the grant's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field.

### 2.8. Validation Order

Every request is validated against an ordered cascade, and the first failure short-circuits the rest:

1. Authentication headers are present and non-empty — else `ERR_UNAUTHENTICATED`.
2. The caller's role is permitted on the endpoint — else `ERR_FORBIDDEN_ROLE`.
3. Entity-backed ownership: a `Publisher` caller owns the channel, campaign, dispute, or statement being acted on; a `Viewer` owns the subscription, privacy record, or device unit; a `TvManufacturer` owns the model or unit — else `ERR_FORBIDDEN_ROLE`.
4. Existence of path identifiers and body foreign-key references, validated left-to-right — else `ERR_NOT_FOUND`.
5. Request shape: required fields present, types valid, enum membership, amounts positive where required, window ordering (`window_start` strictly before `window_end` for placements, `window_start` before or equal to `window_end` for lab benches), and period format `YYYY-MM` — else `ERR_INVALID_REQUEST`.
6. The target resource's own state machine permits the transition from its current state (a grant must be `OPEN`, a statement `OPEN` or `FINALIZED` as appropriate, a dispute in the right stage, a campaign `ACTIVE` for impression recording, a channel non-terminal) — else `ERR_INVALID_STATE`.
7. Cross-entity state gates: the channel is `PUBLISHED` for subscriptions and campaign schedule/start/resume, the campaign is `ACTIVE` for impression recording and placement booking, and version/channel review pairing holds — else `ERR_CHANNEL_NOT_PUBLISHED` or `ERR_CAMPAIGN_NOT_ACTIVE`.
8. Content-policy safety: the channel's `policy_hold` is false for placement bookings and campaign scheduling, and the channel is not `REMOVED` for any new commercial activity — else `ERR_CONTENT_POLICY_BLOCK`.
9. Temporal rules: slot and bench overlap, booking windows not entirely in the past, the logical clock inside the campaign flight for start/resume, the appeal inside its window — else the corresponding temporal error.
10. Publisher standing gate: version submission, channel publication, and channel reinstatement require the publisher's `standing` to be `GOOD` or `PROBATION` — else `ERR_PUBLISHER_SUSPENDED`.
11. Uniqueness and capacity constraints: lab capacity, unique device serial numbers, unique grant periods per channel, no second review while one is in progress, unique viewer emails, unique model codes per manufacturer, unique OS version tags — else the corresponding duplicate/capacity error.
12. Device referential-state rules, evaluated in this pinned sub-order: (1) the device model is `CERTIFIED` — else `ERR_MODEL_NOT_CERTIFIED`; (2) the model's `update_compliance` is not `OVERDUE` — else `ERR_UPDATE_OVERDUE`; (3) the manufacturer's `license_status` is `LICENSED` — else `ERR_MANUFACTURER_NOT_LICENSED`; (4) the OS update is `ROLLING` — else `ERR_UPDATE_NOT_APPLICABLE`; (5) the recovery endpoint matches the model's `recovery_policy` — else `ERR_RECOVERY_POLICY_MISMATCH`.
13. Fiscal gates: the publisher's outstanding balance is within the campaign credit limit for scheduling, and impression spend fits within budget — else `ERR_OUTSTANDING_BALANCE` or `ERR_BUDGET_EXHAUSTED`.
14. Privacy: personalized measurement requires the measured viewer's consent — else `ERR_PRIVACY_OPTED_OUT`.
15. Optimistic concurrency on the two guarded writes — else `ERR_STALE_VERSION`.

This ordering is normative. When a request would fail multiple checks, the error returned is the one belonging to the earliest failing tier.

### 2.9. Cascades and Their Boundaries

Several single operations mutate multiple entities, and the cascade boundaries are part of the contract. A channel suspension pauses the channel's `ACTIVE` and `PAUSED` campaigns, and each such pause — not the suspension directly — releases that campaign's `HELD` and `CONFIRMED` placement bookings. A channel removal fires the same campaign/booking cascade and additionally cancels the channel's `ACTIVE` subscriptions, revoking their entitlements. Publisher termination removes every channel of the publisher that is not already `REMOVED`, each firing its own removal cascade. Critically, cascades do not run in reverse: reinstating a suspended channel does not resume its campaigns and does not re-hold bookings that were released — released bookings stay `RELEASED`, and the publisher must re-book inventory explicitly. Refunds are never auto-issued by any cascade.

### 2.10. Nested and Filtered Retrieval

Several list endpoints are scoped to a parent resource or filtered by foreign keys. When a path contains nested identifiers, the system validates existence left-to-right and returns `ERR_NOT_FOUND` for the first identifier that does not resolve. The channel list accepts an `active_version_id` filter, which provides reverse reachability from a certification version to the channel that adopted it. Parent-scoped listings exist for a publisher's channels, campaigns, and statements; a channel's versions, subscriptions, ad slot grants, and campaigns; a viewer's subscriptions and device units; a manufacturer's device models and lab bookings; a device model's lab bookings and device units; and a campaign's placement bookings. Unscoped lists accept foreign-key filters as documented per endpoint in §4.

## 3. Business Logic & Workflows

### 3.1. Publisher Onboarding and Standing Discipline

A `PlatformAdmin` onboards a publisher by supplying its `legal_name`, a negotiated `default_ad_share_bps` — the publisher's share of revenue from its own ad slots, expressed in basis points between 0 and 10000 inclusive, where 7000 means the publisher keeps seventy percent — and a `billing_model` of either `GROSS_SHARE` or `NET_OF_FEES`, which selects which subscription payout variant applies to this publisher's statements (§3.7). A new publisher begins with `standing` of `GOOD`, `revenue_tier` of `STANDARD`, and an `outstanding_balance_cents` of zero.

Standing is a disciplinary dial operated by the platform: a standing transition supplies a target `to_standing` and a `reason`. From `GOOD`, a publisher may be moved to `PROBATION`; from `PROBATION` it may be restored to `GOOD`. From either `GOOD` or `PROBATION` it may be suspended: the transition to `SUSPENDED` carries an economic consequence beyond the access gates — a publisher in `SUSPENDED` standing at statement finalization time pays a platform fee five hundred basis points above its tier rate, and any ad-grant resplit computed while the publisher is suspended applies the same five-hundred-basis-point penalty to the publisher's share (§3.4). From `SUSPENDED` the only way back is to `PROBATION`. Every standing change records a `reason`. From any of `GOOD`, `PROBATION`, or `SUSPENDED` the platform may terminate the publisher; termination to `TERMINATED` is final and fires the cascade described in §2.9 — every channel of the publisher not already `REMOVED` is removed (each recording its own removal rationale and firing its own removal side effects), each channel's `ACTIVE` subscriptions are cancelled with entitlements revoked, and no refunds are issued automatically. A terminated publisher's future statements simply record zero new activity.

The publisher's `outstanding_balance_cents` is the running total of what the publisher owes the platform: it is the sum, over this publisher's statements in `FINALIZED` status (settled statements no longer count), of the positive part of the negated net payout — statements whose net was negative. It can never fall below zero.

### 3.2. Channels and the Certification Loop

A `Publisher` creates a channel by naming the owning publisher via `publisher_id`, choosing a display `name`, a `category` — one of `VIDEO`, `AUDIO`, `GAME`, `NEWS`, or `KIDS` — and a `content_rating` of `G`, `PG`, or `R18`. New channels begin in `DRAFT`.

Certification is version-based. The publisher submits a certification version by supplying a `version_label` (a publisher-assigned label such as `1.4.2`) and a `technical_checklist` declaring the platform's technical requirements — deep linking, DRM, trick play — together with the OCC field described in §2.7. The first submission moves the channel from `DRAFT` to `SUBMITTED` and creates a channel version whose `review_status` is `SUBMITTED`; the channel's `version` increments by 1. Version submission, like publication and reinstatement, is gated on the publisher's `standing` being `GOOD` or `PROBATION`, failing with `ERR_PUBLISHER_SUSPENDED` otherwise. If the publisher submits again while the channel is `SUBMITTED`, the submission self-loops: the prior version still in `SUBMITTED` is set to `SUPERSEDED`, a fresh version is created in `SUBMITTED`, and the channel's `version` increments again — this is the legitimate supersession the OCC guard protects. If a version of the channel is already being reviewed (the channel is in `IN_REVIEW`), a new submission passes the state gate but is rejected at the business-constraint tier with `ERR_REVIEW_IN_PROGRESS`: a second review may not begin while one is in flight. After a failed review the channel sits in `CHANGES_REQUESTED`, and resubmission from there likewise supersedes any lingering `SUBMITTED` version, creates a new one, and returns the channel to `SUBMITTED`. Submissions against channels in `CERTIFIED`, `PUBLISHED`, `SUSPENDED`, or `REMOVED` fail the state gate with `ERR_INVALID_STATE`.

Review itself belongs to the platform. A `PlatformAdmin` picks up a `SUBMITTED` version for review, which moves the version to `IN_REVIEW` and, in lockstep, moves the parent channel from `SUBMITTED` to `IN_REVIEW`. The decision then lands in one of two ways. A passing decision (an `outcome` of `PASS`) moves the version to `PASSED`, moves the channel from `IN_REVIEW` to `CERTIFIED`, and sets the channel's `active_version_id` to the passed version — until a version passes, `active_version_id` is null. A failing decision (an `outcome` of `FAIL`) requires a non-empty `failure_codes` list, which is recorded on the version as its `review_status` becomes `FAILED`; the channel drops back to `CHANGES_REQUESTED`, opening the revision loop. Version `review_status` values are exactly `SUBMITTED`, `IN_REVIEW`, `PASSED`, `FAILED`, and `SUPERSEDED`, with the last three terminal.

### 3.3. Channel Lifecycle After Certification: Publication, Holds, Suspension, Removal

A `CERTIFIED` channel is made commercially live when a `PlatformAdmin` publishes it, moving it to `PUBLISHED`. Publication requires the publisher's `standing` to be `GOOD` or `PROBATION` and the channel's `policy_hold` to be false.

The channel carries a `policy_hold` boolean that is independent of its `status` field. Suspension accepts a `reason`, and when that reason is `POLICY`, the suspension sets `policy_hold` to true in addition to moving the channel to `SUSPENDED`. The platform can also set or clear a content-policy hold directly on a `PUBLISHED` channel by supplying a `held` flag — the channel stays `PUBLISHED`, only `policy_hold` changes, and each such change increments the channel's `version`. While a channel's `policy_hold` is true, placement bookings and campaign scheduling against that channel are rejected with `ERR_CONTENT_POLICY_BLOCK`, and the same code guards any new commercial activity against a `REMOVED` channel.

Suspension by a `PlatformAdmin` moves a `PUBLISHED` channel to `SUSPENDED` and fires the cascade of §2.9: every campaign of this channel in `ACTIVE` or `PAUSED` becomes `PAUSED`, and each campaign so paused releases its own `HELD` and `CONFIRMED` placement bookings to `RELEASED`. The channel's `removed_reason` is untouched by suspension. Reinstatement moves a `SUSPENDED` channel back to `PUBLISHED`, requires the publisher to be in `GOOD` or `PROBATION`, clears `policy_hold` to false — and deliberately does nothing else: campaigns stay paused, bookings stay released.

Removal is terminal. A `PlatformAdmin` removing a channel — whether directly from `PUBLISHED` or `SUSPENDED`, via the publisher-termination cascade, or as the confirmation of an upheld channel-removal dispute — records the supplied `reason` into `removed_reason` and moves the channel to `REMOVED`. From `PUBLISHED`, removal fires the full suspension cascade plus subscription termination: every subscription of the channel with `billing_status` of `ACTIVE` is cancelled and its entitlement revoked. From `SUSPENDED`, removal records the rationale and cancels the channel's active subscriptions the same way (the campaign/booking cascade has already run at suspension time).

### 3.4. Ad Inventory Grants, Splits, and Revenue Recording

Each calendar month, the platform grants a channel a block of advertising inventory and splits it between publisher and platform. A `PlatformAdmin` creates the grant by supplying the `channel_id`, the `period` as a `YYYY-MM` string, and the `total_slots` — at least one. Only one grant per channel per period may be live: if an `OPEN` grant already exists for the same channel and period, creation is rejected with `ERR_GRANT_PERIOD_DUPLICATE`. Grants begin in `OPEN` status.

At creation, the grant snapshots the owning publisher's current `default_ad_share_bps` into `publisher_share_bps`, and the split is computed: `publisher_slots` is the floor of `total_slots` multiplied by the effective share in basis points and divided by 10000, and `platform_slots` — the platform-retained share of publisher inventory — is `total_slots` minus `publisher_slots`. The invariant `publisher_slots + platform_slots == total_slots` holds at creation and after every resplit.

A grant may be re-split while `OPEN`, a `PlatformAdmin` operation guarded by the grant OCC field of §2.7. At resplit the effective share is recomputed from the publisher's current `default_ad_share_bps`, minus five hundred basis points if the publisher's `standing` is currently `SUSPENDED`, floored at zero; the same floor-division split then recomputes `publisher_slots` and `platform_slots`, conserving the invariant, and the grant's `version` increments by 1. Resplitting a grant that is no longer `OPEN` fails the state gate.

Revenue against the publisher's slots is recorded by `AdOps` as a batch of `slot_revenue_entries` against an `OPEN` grant. The rounding order is pinned and audit-critical: for each entry, processed in array order, the publisher's payout from that entry is computed first — the entry amount multiplied by `publisher_share_bps`, divided by 10000, rounded half-up to the nearest cent — and only then are the per-entry payouts summed into the grant's `publisher_payout_cents`. The grant's `ad_gross_cents` accumulates the raw sum of the entries. Sum-then-round is never acceptable: with entries of one cent, one cent, and one cent at 3333 basis points, the pinned per-entry-then-sum answer is a publisher payout of zero, where the counterfactual sum-then-round would yield one cent. Closing a grant — a terminal move to `CLOSED` — ends both resplitting and revenue recording for that period.

### 3.5. Promotional Campaigns, Measurement, and Home-Screen Placement

A `Publisher` creates a promotional campaign by supplying the `publisher_id`, the promoted `channel_id`, a `flight_start` (inclusive) and `flight_end` (exclusive, strictly later than `flight_start`), a positive `budget_cents` cap, and a `targeting_mode` of `CONTEXTUAL` or `PERSONALIZED` — the latter uses viewer data and is gated by viewer consent at measurement time. Campaigns begin in `DRAFT` with `spent_cents` and `impressions_delivered` at zero.

Scheduling a `DRAFT` campaign is the publisher's declaration that the flight should go live, and it passes three tiers of gate. The campaign must belong to the calling publisher; the channel must be `PUBLISHED` (`ERR_CHANNEL_NOT_PUBLISHED` otherwise) and free of any content-policy hold (`ERR_CONTENT_POLICY_BLOCK`); and the publisher's `outstanding_balance_cents` must not exceed the campaign credit limit of 100000 cents — a publisher already owing the platform more than that is rejected with `ERR_OUTSTANDING_BALANCE`. Scheduling moves the campaign to `SCHEDULED`.

`AdOps` starts a `SCHEDULED` campaign, moving it to `ACTIVE`, but only while the logical clock reads within the flight window — at or after `flight_start` and strictly before `flight_end` — and only while the channel remains `PUBLISHED`; starting outside the flight is rejected with `ERR_CAMPAIGN_OUTSIDE_FLIGHT`. Pausing an `ACTIVE` campaign moves it to `PAUSED` and releases its `HELD` and `CONFIRMED` bookings; resuming a `PAUSED` campaign re-applies both the in-flight clock check and the published-channel check before returning it to `ACTIVE`. A publisher may cancel a campaign in `DRAFT`, `SCHEDULED`, or `PAUSED`, moving it to `CANCELLED` and releasing its bookings the same way. An `ACTIVE` campaign completes itself: the moment a measurement entry brings `spent_cents` to exactly `budget_cents`, the campaign moves to `COMPLETED`. `COMPLETED` and `CANCELLED` are terminal.

Measurement is recorded by `AdOps` in impression batches carrying an `impression_count`, a `cpm_cents` rate, and optionally the `viewer_id` of the measured viewer. The batch cost is the impression count multiplied by the CPM in cents, divided by 1000, rounded half-up to the nearest cent. Before anything is applied, the guard checks that the current `spent_cents` plus this batch cost does not exceed `budget_cents` — spending to exactly the budget is allowed and completes the campaign; one cent over is rejected with `ERR_BUDGET_EXHAUSTED`. Applied batches increment `spent_cents` by the cost and `impressions_delivered` by the count. When a batch carries a `viewer_id` and the campaign's `targeting_mode` is `PERSONALIZED`, that viewer's `ad_consent` must be `PERSONALIZED`; a viewer who is `NON_PERSONALIZED` or `OPTED_OUT` rejects the personalized measurement with `ERR_PRIVACY_OPTED_OUT`. Impression recording against a campaign that is not `ACTIVE` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`.

Every campaign read exposes a live pacing projection. The total flight length is the difference between `flight_end` and `flight_start` in whole hours (at least one); elapsed time is the difference between the logical clock now and `flight_start` in whole hours, clamped to lie between zero and the total. The `expected_spend_cents` is the budget multiplied by elapsed hours, divided by total hours, rounded half-up; `pacing_delta_cents` is `spent_cents` minus that expectation — positive when the campaign is running hot.

Home-screen placement is booked against an `ACTIVE` campaign: the publisher supplies the `campaign_id`, a `slot_code` identifying the home-screen slot resource (for example `HOME_ROW_1`), and a half-open booking window from `window_start` (inclusive) to `window_end` (exclusive, strictly later). Booking creation is subject to the channel's policy-hold safety gate as well. Booking windows use half-open interval semantics: a conflict exists exactly when another booking on the same `slot_code` in `HELD` or `CONFIRMED` status satisfies both that the new start is strictly before the existing end and the new end is strictly after the existing start — and pure adjacency, where the new start equals an existing end or the new end equals an existing start, does not conflict. A conflicting booking is rejected with `ERR_SLOT_OVERLAP`. Zero-length windows fail earlier as shape errors, and a window whose end is not after the logical clock now is rejected with `ERR_BOOKING_WINDOW_PAST`. `RELEASED` and `EXPIRED` bookings never block anything. Bookings begin `HELD`; `AdOps` confirms a `HELD` booking to `CONFIRMED` provided the logical clock still reads strictly before `window_end`, or releases it explicitly to `RELEASED`, freeing the window for future bookings. A booking still `HELD` when the logical clock passes its `window_end` becomes `EXPIRED`, a transition the system applies when any subsequent booking write touches the same `slot_code`.

### 3.6. Viewers, Subscriptions, and the Two Dimensions of Access

Viewer accounts are created by the platform with a unique `email` — a duplicate address is rejected with `ERR_DUPLICATE_EMAIL` — and two privacy controls: `ad_consent`, one of `PERSONALIZED`, `NON_PERSONALIZED`, or `OPTED_OUT` (defaulting to `NON_PERSONALIZED`), and `data_retention_opt_out`, a boolean defaulting to false. Accounts begin `ACTIVE`. The owning `Viewer` — and only the owner — may update either privacy field through the privacy controls of their account.

A `Viewer` subscribes to a channel through platform billing by supplying the `channel_id` and a positive `price_cents` period price; the channel must be `PUBLISHED` at that moment. The new subscription records the calling viewer's identity as its `viewer_id`, stamps `period_start` from the logical clock, and begins with `billing_status` of `ACTIVE` and `entitlement_status` of `ENTITLED`.

A subscription carries two independent dimensions. The billing dimension moves from `ACTIVE` to `CANCELLED` when the owning viewer cancels, or to `REFUNDED` when a `PlatformAdmin` issues a refund; both are terminal. The access dimension moves from `ENTITLED` to `REVOKED` in lockstep with either billing transition — cancellation revokes access immediately, and so does a refund. A refund also stamps `refunded_at` from the logical clock, and this timestamp governs statement attribution: the refund counts against the statement period containing `refunded_at`, regardless of when the original charge occurred (§3.7). Cascading channel removal cancels active subscriptions without issuing refunds — the refund decision always belongs to a human operator.

### 3.7. Monthly Revenue Statements: Generation, Tiering, and the Payout Ledger

The statement pipeline is the platform's reconciliation backbone, run per publisher per calendar month. A `PlatformAdmin` triggers statement generation for a `period`, which creates or refreshes an `OPEN` statement for every publisher — except that a publisher who already has a statement for that period in `FINALIZED`, `DISPUTED`, or `SETTLED` is skipped, because only `OPEN` statements are recomputed. The call reports how many statements were generated as `generated_count`. An `OPEN` statement's amounts are provisional: generation computes from live data, and late-arriving refunds are captured because finalization recomputes from live data again.

A statement accumulates four amount streams from the period's activity on the publisher's channels. `subscription_gross_cents` is the sum of `price_cents` over subscriptions created within the period, and `charge_count` is their count — including subscriptions later refunded. `refund_cents` is the sum of `price_cents` over subscriptions refunded within the period (their `refunded_at` falls in the period), regardless of when they were created. `ad_gross_cents` and `ad_payout_cents` are swept from the publisher's channels' ad slot grants whose period equals the statement's period — the grants' accumulated gross and their per-entry-rounded publisher payouts (§3.4) — and `platform_ad_fee_cents` is the exact difference between them. `placement_spend_cents` is the sum of `spent_cents` over the publisher's campaigns whose `flight_start` falls within the period.

Finalization locks the numbers and answers the question every downstream amount depends on: which fee tier applies. The tier evaluation looks backward only, breaking the apparent circularity between tier, fee, and net. For a statement of a given period, consider the three calendar periods immediately before it — for 2026-09, those are 2026-08, 2026-07, and 2026-06. Sum the `net_payout_cents` of this publisher's statements in those three periods that are in `FINALIZED`, `SETTLED`, or `DISPUTED` status; periods with no qualifying statement contribute zero, and `OPEN` statements never count. If that trailing sum is at least the premier threshold of 10000000 cents — equality qualifies — the publisher earns `PREMIER` for this statement; otherwise `STANDARD`. Only then is the fee rate chosen: `PREMIER_FEE_BPS` of 1500 basis points for a premier statement, `STANDARD_FEE_BPS` of 2000 for a standard one, plus a standing penalty of 500 basis points if the publisher's `standing` is `SUSPENDED` at finalization time. These are recorded on the statement as `applied_tier` and `applied_fee_bps` — both null until finalization — and the publisher's `revenue_tier` is updated to the applied tier at that moment.

With the fee rate fixed, the subscription payout is computed per the publisher's `billing_model`. The subscription base is `subscription_gross_cents` minus `refund_cents`, and it may be negative. Under the `GROSS_SHARE` variant, the publisher's `sub_payout_cents` is the base multiplied by the publisher's share — 10000 minus the applied fee basis points — divided by 10000, rounded half-up; the processing fee is invisible to the payout. Under the `NET_OF_FEES` variant, a processing fee of 55 cents per charge is deducted first — 55 multiplied by `charge_count` — and the share is applied to what remains, again rounded half-up; given the same data, this variant yields a strictly smaller payout whenever there is at least one charge and the fee rate is below the whole. Either way, `platform_sub_fee_cents` is the base minus the payout — exact, with any rounding remainder belonging to the platform. The statement's `net_payout_cents` is then the subscription payout plus the ad payout minus the placement spend, and it too may be negative.

Finalization moves the statement from `OPEN` to `FINALIZED` and locks every amount. If the locked net is negative, the publisher owes the platform: `outstanding_balance_cents` increases by the negated net. Settlement — moving a `FINALIZED` statement to `SETTLED` — is the platform's acknowledgment that the obligation is discharged; if the net was negative, `outstanding_balance_cents` decreases by the negated net, floored at zero.

A publisher who disagrees with a finalized statement may raise a dispute against it (the statement dispute capability described in §3.9), which moves the statement from `FINALIZED` to `DISPUTED`, increments the statement's `version` by 1, and freezes settlement until the dispute is resolved; when the dispute is closed, the statement returns to `FINALIZED`.

### 3.8. Device Hardware: Manufacturers, Models, Lab Certification, and OS Compliance

The device business begins with television manufacturers. A `PlatformAdmin` licenses a manufacturer by recording its `legal_name` and a `royalty_per_device_cents` — the OS licensing royalty owed per activated device, zero or more. Manufacturers begin with `license_status` of `LICENSED`. The platform may suspend a license, recording a `reason`, and reinstate a `SUSPENDED` license — but reinstatement requires that none of the manufacturer's device models is currently `OVERDUE` on a mandatory OS update.

A `TvManufacturer` submits a device model by supplying its own `manufacturer_id`, a `model_code` unique within that manufacturer (a duplicate is rejected with `ERR_DUPLICATE_MODEL_CODE`), and a `recovery_policy` of `STRAIGHT_LINE` or `MONETIZATION`, which selects how device subsidies are recovered (§3.10). Models begin with `cert_status` of `SUBMITTED` and `update_compliance` of `COMPLIANT`; these are two parallel dimensions that evolve independently.

Certification requires lab time. The manufacturer books a certification lab bench for the model by supplying a `bench_code` (for example `LAB_BENCH_1`) and a closed window from `window_start` to `window_end`, where the end may equal the start. Lab windows use closed-interval semantics — unlike placement bookings, both endpoints are inclusive, so a new window whose start exactly equals another's end does conflict — and for conflict purposes every window is buffered by 24 hours on each side: the effective window runs from 24 hours before `window_start` to 24 hours after `window_end`. A new booking whose buffered window intersects any `BOOKED` booking's buffered window on the same `bench_code` is rejected with `ERR_BENCH_OVERLAP`. Overlap is checked before capacity: independent of any overlap, a manufacturer may have at most 3 models in `LAB_TESTING` at once — booking the bench for a fourth is rejected with `ERR_LAB_CAPACITY_EXCEEDED`. Booking requires the manufacturer's license to be `LICENSED` and creates a `LabBooking` in `BOOKED` status, derived from the model under test and stamped with the owning manufacturer; the model moves from `SUBMITTED` to `LAB_TESTING`.

A `PlatformAdmin` certifies a model in `LAB_TESTING` once its lab work has finished — a `BOOKED` lab booking must exist for the model whose `window_end` is strictly before the logical clock now — at which point the model becomes `CERTIFIED` and that booking becomes `COMPLETED`. Rejection records a `reason`, moves the model to `REJECTED`, and cancels its `BOOKED` lab bookings. Rejection is not the end: the manufacturer may resubmit a `REJECTED` model (license still required), returning it to `SUBMITTED` for another loop. A `CERTIFIED` model may later be decertified, a terminal move to `DECERTIFIED` that blocks creation of new units for the model while leaving existing units unchanged.

OS updates are announced by the platform with a unique `version_tag` (a duplicate is rejected with `ERR_DUPLICATE_VERSION_TAG`), a `mandatory` flag, a `rollout_start`, and a `compliance_deadline`. Updates are created directly in `ROLLING` status — the `ANNOUNCED` value of the update `status` enumeration is reserved for pre-rollout staging — and may be withdrawn to `WITHDRAWN`, after which they impose no compliance obligations. Mandatory updates impose the deadline on every activated device, and the platform re-derives each model's `update_compliance` on demand. A model moves from `COMPLIANT` to `GRACE` when a mandatory `ROLLING` update exists whose deadline is at most seven days ahead but has not yet passed — the logical clock now is strictly after the deadline minus seven days and at or before the deadline itself — while at least one `ACTIVATED` unit of the model has not yet applied it. A model in `COMPLIANT` or `GRACE` moves to `OVERDUE` when a mandatory `ROLLING` update's deadline has strictly passed — applying the update at exactly the deadline is compliant, the boundary is inclusive — and at least one `ACTIVATED` unit still lacks it. Entering `OVERDUE` cascades: the manufacturer's `license_status` becomes `SUSPENDED`, blocking new device-unit creation and lab bookings until cured. A model in `GRACE` or `OVERDUE` returns to `COMPLIANT` once every mandatory `ROLLING` update whose deadline has passed is present on every `ACTIVATED` unit of the model. Curing compliance does not automatically restore the manufacturer's license — reinstatement is the separate manual step described above.

### 3.9. Disputes: Channel Removals, Statements, and the Appeal Window

Disputes give publishers a formal challenge path. A publisher raises a dispute by supplying the `publisher_id`, a `subject_type` of `CHANNEL_REMOVAL` or `STATEMENT`, a `reason`, and — when the subject is a channel removal — the `channel_id` of a `REMOVED` channel; for statement subjects the statement linkage is recorded as `statement_id` when the dispute is raised through the statement's own dispute capability (§3.7), and `channel_id` is null for statement subjects. Every dispute begins in `FILED`.

The platform moves a `FILED` dispute to `TRIAGE`, then to `EVIDENCE` by requesting evidence. From `EVIDENCE`, a `PlatformAdmin` decides the dispute with a `decision` of `UPHELD` or `OVERTURNED`, stamping `decided_at` from the logical clock. Decision consequences depend on the subject. For a channel-removal dispute decided `OVERTURNED`, the removal is compensated: the channel moves from `REMOVED` back to `PUBLISHED` with `policy_hold` cleared to false. For a channel-removal dispute decided `UPHELD`, the channel stays `REMOVED`. The publisher may appeal a `DECIDED` dispute — but only within seven days of `decided_at`, with the boundary inclusive: an appeal at exactly seven days after the decision succeeds, one later than that is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. Appeal moves the dispute to `APPEALED`, from which the platform requests evidence again, returning it to `EVIDENCE` for another decision loop. Closing a `DECIDED` dispute moves it to terminal `CLOSED`; when the subject is a statement, closing also returns the linked statement from `DISPUTED` to `FINALIZED`, unfreezing its settlement path.

### 3.10. Device Units: Subsidy Accounting and Recovery

Hardware is sold near cost and the platform recovers the difference through monetization. A `TvManufacturer` manufactures a unit by supplying the `device_model_id` — the model must be `CERTIFIED` and the manufacturer `LICENSED`, evaluated in the pinned referential order of §2.8 — a globally unique `serial_number` (a duplicate is rejected with `ERR_DUPLICATE_SERIAL`), the `hardware_cost_cents` (positive), and the near-cost `sale_price_cents` (zero or more). The unit begins `MANUFACTURED` with `os_version_tag` of `BASE` and no `viewer_id`. At creation the platform's subsidy is computed: `subsidy_cents` is the positive part of `hardware_cost_cents` minus `sale_price_cents`, or zero when the sale price meets or exceeds cost.

The platform sells a `MANUFACTURED` unit, moving it to `SOLD`. The buyer — a `Viewer` whose account is `ACTIVE` — activates a `SOLD` unit, which records the caller as the unit's `viewer_id` and moves it to `ACTIVATED`. Activation is a posture gate across three cross-entity dimensions, evaluated in the pinned order of §2.8: the model must be `CERTIFIED` (`ERR_MODEL_NOT_CERTIFIED`), the model's `update_compliance` must not be `OVERDUE` (`ERR_UPDATE_OVERDUE`), and the manufacturer's license must be `LICENSED` (`ERR_MANUFACTURER_NOT_LICENSED`). The owning viewer may apply a `ROLLING` OS update to an activated unit by naming the `os_update_id`; the unit's `os_version_tag` becomes the update's `version_tag`. Applying an update that is not `ROLLING`, or one the unit already runs, is rejected with `ERR_UPDATE_NOT_APPLICABLE`. The owner may also deactivate an `ACTIVATED` unit, moving it to terminal `DEACTIVATED`.

The subsidy ledger obeys a conservation invariant at all times: `subsidy_cents` equals `subsidy_recovered_cents` plus `subsidy_written_off_cents` plus `subsidy_outstanding_cents`. Recovery proceeds per the model's `recovery_policy`, and the two variants are mutually exclusive — recording ad revenue against a `STRAIGHT_LINE` model's unit, or accruing straight-line recovery against a `MONETIZATION` model's unit, is rejected with `ERR_RECOVERY_POLICY_MISMATCH`. Under `STRAIGHT_LINE`, `AdOps` accrues one month of recovery at a time: the monthly amount is the floor of `subsidy_cents` divided by 24 — twenty-four monthly installments — and each accrual recovers the smaller of that monthly amount and the subsidy still outstanding (the subsidy minus what is already recovered and written off). Under `MONETIZATION`, `AdOps` records attributed ad `revenue_cents` against the unit, and the recovery is 3500 basis points of that revenue — thirty-five percent — rounded half-up to the nearest cent, then capped at the subsidy still outstanding. Each recovery adds to `subsidy_recovered_cents` and recomputes `subsidy_outstanding_cents` as the subsidy minus recovered minus written off. Deactivation writes off whatever subsidy remains outstanding: `subsidy_written_off_cents` grows by the outstanding amount, `subsidy_outstanding_cents` becomes zero, and the invariant is conserved.

## 4. Endpoint Definitions

All endpoints are mounted under the API root `/`. Operations that create new resources return `201 Created`; operations that modify or act upon existing resources return `200 OK`. All list endpoints accept the optional `limit` and `offset` pagination parameters described in §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/publishers` | Onboard a publisher | PlatformAdmin |
| GET | `/publishers` | List publishers | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| GET | `/publishers/{id}` | Get a publisher | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| POST | `/publishers/{id}/standing` | Transition publisher standing | PlatformAdmin |
| GET | `/publishers/{id}/channels` | List a publisher's channels | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| GET | `/publishers/{id}/campaigns` | List a publisher's campaigns | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| GET | `/publishers/{id}/statements` | List a publisher's revenue statements | PlatformAdmin, AdOps, Publisher |
| POST | `/channels` | Create a channel in DRAFT | Publisher |
| GET | `/channels` | List channels | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| GET | `/channels/{id}` | Get a channel | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| POST | `/channels/{id}/publish` | Publish a CERTIFIED channel | PlatformAdmin |
| POST | `/channels/{id}/suspend` | Suspend a PUBLISHED channel (reason OPS or POLICY) | PlatformAdmin |
| POST | `/channels/{id}/reinstate` | Reinstate a SUSPENDED channel to PUBLISHED | PlatformAdmin |
| POST | `/channels/{id}/remove` | Remove a channel (terminal) | PlatformAdmin |
| POST | `/channels/{id}/policy-hold` | Set or clear a content-policy hold on a PUBLISHED channel | PlatformAdmin |
| GET | `/channels/{id}/versions` | List a channel's versions | PlatformAdmin, AdOps, Publisher |
| GET | `/channels/{id}/subscriptions` | List a channel's subscriptions | PlatformAdmin, AdOps, Publisher |
| GET | `/channels/{id}/ad-slot-grants` | List a channel's ad slot grants | PlatformAdmin, AdOps, Publisher |
| GET | `/channels/{id}/campaigns` | List a channel's campaigns | PlatformAdmin, AdOps, Publisher |
| POST | `/channels/{id}/versions` | Submit a channel version for certification | Publisher |
| GET | `/channel-versions/{id}` | Get a channel version | PlatformAdmin, AdOps, Publisher |
| POST | `/channel-versions/{id}/review` | Begin review of a SUBMITTED version | PlatformAdmin |
| POST | `/channel-versions/{id}/decide` | PASS or FAIL an IN_REVIEW version | PlatformAdmin |
| POST | `/viewer-accounts` | Create a viewer account | PlatformAdmin |
| GET | `/viewer-accounts/{id}` | Get a viewer account | PlatformAdmin, AdOps, Viewer |
| PATCH | `/viewer-accounts/{id}/privacy` | Update viewer privacy controls (owner only) | Viewer |
| GET | `/viewer-accounts/{id}/subscriptions` | List a viewer's subscriptions | PlatformAdmin, AdOps, Viewer |
| GET | `/viewer-accounts/{id}/device-units` | List a viewer's device units | PlatformAdmin, AdOps, Viewer |
| POST | `/subscriptions` | Subscribe the calling viewer to a channel | Viewer |
| GET | `/subscriptions` | List subscriptions | PlatformAdmin, AdOps, Publisher, Viewer |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, AdOps, Publisher, Viewer |
| POST | `/subscriptions/{id}/cancel` | Cancel own subscription | Viewer |
| POST | `/subscriptions/{id}/refund` | Refund a subscription | PlatformAdmin |
| POST | `/ad-slot-grants` | Grant and split a channel's ad inventory for a period | PlatformAdmin |
| GET | `/ad-slot-grants` | List ad slot grants | PlatformAdmin, AdOps, Publisher |
| GET | `/ad-slot-grants/{id}` | Get an ad slot grant | PlatformAdmin, AdOps, Publisher |
| POST | `/ad-slot-grants/{id}/record-revenue` | Record publisher-slot revenue entries | AdOps |
| POST | `/ad-slot-grants/{id}/resplit` | Re-split an OPEN grant against current publisher standing | PlatformAdmin |
| POST | `/ad-slot-grants/{id}/close` | Close an OPEN grant (terminal) | PlatformAdmin |
| POST | `/campaigns` | Create a promotional campaign in DRAFT | Publisher |
| GET | `/campaigns` | List campaigns | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| GET | `/campaigns/{id}` | Get a campaign including pacing projection fields | PlatformAdmin, AdOps, Publisher, Viewer, TvManufacturer |
| POST | `/campaigns/{id}/schedule` | Schedule a DRAFT campaign | Publisher |
| POST | `/campaigns/{id}/start` | Start a SCHEDULED campaign | AdOps |
| POST | `/campaigns/{id}/pause` | Pause an ACTIVE campaign | AdOps |
| POST | `/campaigns/{id}/resume` | Resume a PAUSED campaign | AdOps |
| POST | `/campaigns/{id}/cancel` | Cancel a DRAFT/SCHEDULED/PAUSED campaign | Publisher |
| POST | `/campaigns/{id}/impressions` | Record measured impressions with cost | AdOps |
| GET | `/campaigns/{id}/placement-bookings` | List a campaign's placement bookings | PlatformAdmin, AdOps, Publisher |
| POST | `/placement-bookings` | Book a home-screen placement window | Publisher |
| GET | `/placement-bookings` | List placement bookings | PlatformAdmin, AdOps, Publisher |
| GET | `/placement-bookings/{id}` | Get a placement booking | PlatformAdmin, AdOps, Publisher |
| POST | `/placement-bookings/{id}/confirm` | Confirm a HELD booking | AdOps |
| POST | `/placement-bookings/{id}/release` | Release a HELD/CONFIRMED booking | AdOps |
| POST | `/manufacturers` | License a television manufacturer | PlatformAdmin |
| GET | `/manufacturers/{id}` | Get a manufacturer | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/manufacturers/{id}/suspend` | Suspend a manufacturer's OS license | PlatformAdmin |
| POST | `/manufacturers/{id}/reinstate` | Reinstate a SUSPENDED license | PlatformAdmin |
| GET | `/manufacturers/{id}/device-models` | List a manufacturer's device models | PlatformAdmin, AdOps, TvManufacturer |
| GET | `/manufacturers/{id}/lab-bookings` | List a manufacturer's lab bookings | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/device-models` | Submit a device model for certification | TvManufacturer |
| GET | `/device-models/{id}` | Get a device model | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/device-models/{id}/lab-bookings` | Book a certification lab bench | TvManufacturer |
| GET | `/device-models/{id}/lab-bookings` | List a model's lab bookings | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/device-models/{id}/certify` | Certify a model whose lab window has finished | PlatformAdmin |
| POST | `/device-models/{id}/reject` | Reject a model in LAB_TESTING | PlatformAdmin |
| POST | `/device-models/{id}/resubmit` | Resubmit a REJECTED model | TvManufacturer |
| POST | `/device-models/{id}/decertify` | Decertify a CERTIFIED model (terminal) | PlatformAdmin |
| POST | `/device-models/{id}/refresh-compliance` | Re-evaluate a model's update compliance | PlatformAdmin |
| GET | `/device-models/{id}/device-units` | List a model's device units | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/os-updates` | Announce a platform OS update | PlatformAdmin |
| GET | `/os-updates` | List OS updates | PlatformAdmin, AdOps, TvManufacturer |
| GET | `/os-updates/{id}` | Get an OS update | PlatformAdmin, AdOps, TvManufacturer |
| POST | `/os-updates/{id}/withdraw` | Withdraw an OS update | PlatformAdmin |
| POST | `/device-units` | Manufacture a device unit | TvManufacturer |
| GET | `/device-units` | List device units | PlatformAdmin, AdOps, TvManufacturer, Viewer |
| GET | `/device-units/{id}` | Get a device unit | PlatformAdmin, AdOps, TvManufacturer, Viewer |
| POST | `/device-units/{id}/sell` | Sell a unit at its near-cost price | PlatformAdmin |
| POST | `/device-units/{id}/activate` | Activate a sold unit for the calling viewer | Viewer |
| POST | `/device-units/{id}/deactivate` | Deactivate own unit; writes off outstanding subsidy | Viewer |
| POST | `/device-units/{id}/apply-os-update` | Apply a ROLLING OS update to own activated unit | Viewer |
| POST | `/device-units/{id}/record-ad-revenue` | Record attributed ad revenue (MONETIZATION models) | AdOps |
| POST | `/device-units/{id}/accrue-straight-line` | Accrue one month of straight-line subsidy recovery | AdOps |
| POST | `/statements/generate` | Generate or refresh OPEN statements for a period | PlatformAdmin |
| GET | `/statements` | List revenue statements | PlatformAdmin, AdOps, Publisher |
| GET | `/statements/{id}` | Get a revenue statement | PlatformAdmin, AdOps, Publisher |
| POST | `/statements/{id}/finalize` | Finalize an OPEN statement | PlatformAdmin |
| POST | `/statements/{id}/settle` | Settle a FINALIZED statement | PlatformAdmin |
| POST | `/statements/{id}/disputes` | Raise a statement dispute | Publisher |
| POST | `/disputes` | Raise a channel-removal dispute | Publisher |
| GET | `/disputes` | List disputes | PlatformAdmin, AdOps, Publisher |
| GET | `/disputes/{id}` | Get a dispute | PlatformAdmin, AdOps, Publisher |
| POST | `/disputes/{id}/triage` | Triage a FILED dispute | PlatformAdmin |
| POST | `/disputes/{id}/request-evidence` | Move a TRIAGE or APPEALED dispute to evidence gathering | PlatformAdmin |
| POST | `/disputes/{id}/decide` | Decide an EVIDENCE dispute | PlatformAdmin |
| POST | `/disputes/{id}/appeal` | Appeal a DECIDED dispute within its window | Publisher |
| POST | `/disputes/{id}/close` | Close a DECIDED dispute | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CHANNEL_NOT_PUBLISHED` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_CAMPAIGN_OUTSIDE_FLIGHT` | 409 |
| `ERR_CONTENT_POLICY_BLOCK` | 422 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_BENCH_OVERLAP` | 409 |
| `ERR_BOOKING_WINDOW_PAST` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_MODEL_CODE` | 409 |
| `ERR_DUPLICATE_VERSION_TAG` | 409 |
| `ERR_GRANT_PERIOD_DUPLICATE` | 409 |
| `ERR_PUBLISHER_SUSPENDED` | 409 |
| `ERR_REVIEW_IN_PROGRESS` | 409 |
| `ERR_MODEL_NOT_CERTIFIED` | 409 |
| `ERR_MANUFACTURER_NOT_LICENSED` | 409 |
| `ERR_UPDATE_OVERDUE` | 409 |
| `ERR_UPDATE_NOT_APPLICABLE` | 409 |
| `ERR_RECOVERY_POLICY_MISMATCH` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 422 |
| `ERR_BUDGET_EXHAUSTED` | 422 |
| `ERR_PRIVACY_OPTED_OUT` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 |
