# Creator Monetization Claims API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Creator Monetization Claims API, the platform surface that decides which channels may earn money, which uploads may carry advertising, who owns the revenue a video generates, and when that revenue may actually leave the platform. The domain is adversarial by nature: creators want to publish and get paid, rights holders want their assets accounted for, advertisers want their brands kept away from unfriendly content, and regulators want withholding, tax documentation and strike policy applied consistently across every country the platform operates in. The API must reconcile those four interests on a single, auditable ledger.

The business problem the system solves is the gap between *earning* money and *being entitled to it*. A channel may accumulate thousands of dollars of advertising revenue while a single reference-file match is under dispute, and the platform cannot simply hand that money over and claw it back later. Monetization eligibility is therefore not a one-time gate but a continuously re-evaluated posture that can close a channel's earning capability the moment its strike count crosses a policy line — and reopen it automatically once those strikes expire. Revenue is routed into clearly labelled buckets that track whether the money currently belongs to the creator, is being held pending a rights decision, or has already been paid out and may need to be retroactively reclassified.

Three engineering constraints dominate the design. First, every monetary figure is an integer count of cents computed with a pinned rounding order, because a per-record split and a batch-total split of the same revenue produce different totals. Second, the system runs on an explicit logical clock rather than wall-clock time, so that the thirty-day dispute window, the ninety-day strike lifetime and the fourteen-day appeal lockout are all testable and deterministic. Third, every figure the system reports — a channel's `monetization_posture`, an item's `ad_suitability`, a claim's `lock_reason`, a payout batch's `adjusted_net_cents` — is derived, never stored as an independently editable input, so that it can always be recomputed from the facts that produced it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which that principal is acting. A request that omits `X-User-Role`, or supplies a value that is not one of the roles named below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not permitted to perform the requested operation, or whose principal is acting on a resource it does not own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognises eight role names, spelled exactly as follows: `Anonymous`, `Creator`, `MonetizationReviewer`, `Reviewer`, `RightsHolder`, `Moderator`, `PlatformAdmin`, and `Any`.

Two of these roles are entity-backed, meaning the identifier in `X-User-ID` is the `id` of a persisted row and is compared against foreign-key fields on the resources being touched. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Channel`; every ownership check on a resource that references a `Channel` — a `ContentItem` through its `channel_id`, a `PayoutBatch`, a `ChannelStrike`, a `MembershipSchedule`, a `ChannelMembership`, a `RevenueEvent` — compares that resource's channel foreign key to `X-User-ID`, and a creator may act only on its own channel and the content, claims and schedules beneath it. When `X-User-Role` is `RightsHolder`, `X-User-ID` is the `id` of the acting `ReferenceFile`; ownership checks on a `Claim` compare the claim's `reference_file_id` to `X-User-ID`, and a rights holder may only appeal, resolve or take down claims originating from its own registered reference.

The remaining roles are opaque: when `X-User-Role` is `Anonymous`, `MonetizationReviewer`, `Reviewer`, `Moderator`, `PlatformAdmin` or `Any`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a rule calls for an issuing principal, but it does not compare it to any entity's `id`.

`Anonymous` callers may create a channel and read public listings; that is the entire unauthenticated surface. `Any` is a convenience umbrella for the read-only surface — every authenticated role may read listings and single resources. The operations reserved to each role are enumerated in §4.

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

List endpoints accept a `limit` and an `offset` query parameter. `limit` caps the number of rows returned, defaults to 10 when omitted, and must be at least 1 and at most 100. `offset` states how many rows to skip from the front of the ordering and defaults to 0. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object. Unless a rule in §3 says otherwise, list endpoints return rows ordered by `created_at` ascending.

Two list surfaces also accept filters. The cross-channel content-item listing accepts a `channel_id` filter. The claim listing accepts a `content_item_id` filter, a `reference_file_id` filter and a `status` filter, each narrowing the result set to rows matching the supplied value. The reviewer queue and the read-listings of claims, channels, reference files and payout batches each accept the standard `limit` and `offset` pair and nothing else.

### 2.4. Channel Posture: The Master Monetization Gate

Every revenue-generating and monetization-related operation on a channel is gated by that channel's `monetization_posture`, a derived field with exactly three values: `OPEN`, `RESTRICTED`, and `FROZEN`. Posture is never supplied by a client; it is recomputed from the channel's own facts whenever `monetization_status`, `policy_strike_count` or `copyright_strike_count` changes, and it is recomputed by the strike sweeper as well. The four branches are evaluated top to bottom and the first one that matches wins:

- If `monetization_status` is `MONETIZATION_REVOKED`, posture is `FROZEN`.
- Otherwise, if `policy_strike_count` is greater than zero, posture is `RESTRICTED`.
- Otherwise, if `copyright_strike_count` is at least 2, posture is `RESTRICTED`.
- Otherwise, posture is `OPEN`.

The consequence of `FROZEN` is that every operation which routes or pays out revenue is refused with `ERR_POSTURE_FROZEN` (HTTP 409). This covers four operations precisely: filing a dispute, requesting review of an upload (which drives an item into classification), and both the lock and the release stages of payout. A frozen channel is additionally barred from requesting a classification review of one of its uploads and from being escalated to takedown. A `RESTRICTED` posture is narrower still: it refuses new monetization applications and re-applications, dispute filings, classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (HTTP 409), while leaving the read surface and the majority of the earnings workflow intact.

The two strike counters that feed posture are themselves derived. `policy_strike_count` is the number of `ChannelStrike` rows of kind `COMMUNITY` whose status is `ACTIVE`, plus any count supplied directly at channel creation. `copyright_strike_count` is the number of `CopyrightStrike` rows whose status is `ACTIVE`. Expired strikes are excluded from both counters entirely.

### 2.5. Common Resource Properties and Change Accounting

Resources declared with the common field set — `Channel`, `ContentItem`, `ReferenceFile`, `Claim`, `CopyrightStrike`, `ChannelStrike`, `MembershipSchedule`, `ChannelMembership` and `PayoutBatch` — carry four system-managed properties in addition to their own attributes:

- `id` (string): a server-minted UUID with no type prefix and no embedded entity name.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a counter starting at 1 that increments by exactly 1 on every mutation, including mutations performed by background cascades rather than by a client request.

The sub-resources declared without the common field set — `AdReview`, `ClaimDispute`, `ClaimAppeal`, `RevenueRouting` and `RevenueEvent` — expose an `id` and their own creation timestamp, and carry neither `updated_at` nor `version`. No version guard applies to them, and a `ClaimDispute` and a `ClaimAppeal` are immutable in substance after they are written: each is set once to the status it carries and is never otherwise touched.

Cascades matter for version accounting. When one client action mutates several resources, each mutated parent increments its own `version` by 1 and refreshes its own `updated_at`; a client that holds an older copy of that parent will find its version stale, which is exactly the signal that §2.6 turns into a rejection.

### 2.6. Optimistic Concurrency on Version-Bearing Writes

Three write operations are guarded against a stale client view. In each case the client must supply a version field naming the last version it observed for the parent resource, the field is mandatory rather than optional, and a mismatch between the supplied value and the parent's current `version` rejects the request with `ERR_STALE_VERSION` (HTTP 412). The guard is a staleness check, not a scheduling mechanism: the request is rejected because the caller's observation of the parent no longer matches the parent's stored state, and no claim regarding request interleaving is implied.

- Routing revenue for a content item requires `expected_content_item_version`, naming the observed `version` of that `ContentItem`. A stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Releasing a locked payout batch requires `expected_payout_batch_version`, naming the observed `version` of that `PayoutBatch`. A stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Filing a dispute against a claim requires `expected_claim_version`, naming the observed `version` of that `Claim`. A stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints that do not appear in this list do not perform a version-mismatch rejection.

### 2.7. Nested Resources and Left-to-Right Existence Resolution

Many operations address a resource through its ancestors: a content item is reached through its channel via a `channelId` segment and an `itemId` segment, a claim suspension or appeal is reached through a `claimId` segment and, for appeal decisions, an `appealId` segment, and a payout batch is reached through a `channelId` segment and a `batchId` segment. Before any business rule is evaluated, the server resolves these identifiers strictly left to right along the path and rejects the request at the first identifier that does not name an existing resource.

Each failure maps to a specific identifier: an unknown channel yields `ERR_CHANNEL_NOT_FOUND`, an unknown content item — or one that does not belong to the channel named earlier in the same path — yields `ERR_CONTENT_ITEM_NOT_FOUND`, an unknown claim yields `ERR_CLAIM_NOT_FOUND`, an unknown reference file yields `ERR_REFERENCE_FILE_NOT_FOUND`, an unknown or cross-channel payout batch yields `ERR_PAYOUT_BATCH_NOT_FOUND`, an unknown appeal for the named claim yields `ERR_APPEAL_NOT_FOUND`, and an unknown membership for the named channel yields `ERR_MEMBERSHIP_NOT_FOUND`. All of these are HTTP 404 responses. Only after every path identifier resolves does the server apply the state and business rules described in §3 — so a request naming a non-existent channel and a non-existent item reports the channel failure, never the item failure.

### 2.8. Money, Cents Precision and Split Conservation

Every monetary quantity in this system is an integer number of cents. There are no fractional cents anywhere in any stored field or any API response. Rates — the per-stream creator rates, the withholding rates, the network fee rate, the splitter share rate — are decimal fractions, and each is documented with its precision at the point where it is used.

Rounding is always half-up, applied to the nearest whole cent, and it is applied to exactly the step named in the rule that performs it. The system never rounds a running total in place of a component, never derives one component by subtracting a rounded figure from another rounded figure, and never re-rounds an already-rounded value. Two consequences follow immediately and are load-bearing for this domain. First, a revenue split is always computed per routing record: the creator share is the half-up rounding of the record's gross amount multiplied by the stream rate, and the partner share is whatever remains of that record's gross amount after the creator share is taken, so the two shares always sum exactly to the record's gross. Summing several records first and rounding the sum gives a different cent total and is not permitted. Second, when a computation produces a negative payout after deductions, the result is floored at zero rather than passed through as a negative amount.

### 2.9. The Logical Clock and Deferred Strike Expiry

The system does not read wall-clock time. It maintains a logical clock whose startup value is fixed at `2026-09-01T00:00:00Z`, and the server must never fall back to real wall-clock time before the clock has been explicitly advanced. The clock is advanced only by a `PlatformAdmin`-only test-driving capability, which accepts a `to_iso8601` instant and moves the logical clock to that value.

Advancing the clock is not a passive act: it runs the strike expiry sweep. Every `ChannelStrike` and every `CopyrightStrike` whose status is `ACTIVE` and whose `expires_at` is at or before the new clock instant is moved to `EXPIRED`; the comparison is inclusive at the boundary, so a strike whose `expires_at` equals the newly set clock instant expires. Strikes already in `EXPIRED` are never revisited. After the sweep the system recomputes `policy_strike_count`, `copyright_strike_count` and `monetization_posture` for every affected channel, and, when a channel is in `MONETIZATION_REVOKED` and both of its strike counters have reached zero, moves that channel's `monetization_status` to `MONETIZATION_PENDING`.

The logical clock also supplies the timestamps that make the temporal rules testable: a `RevenueEvent`'s `occurred_at` defaults to the clock instant at creation, a released payout batch's `paid_at` is set to the clock instant, and the thirty-day dispute window, the ninety-day strike lifetime and the fourteen-day appeal lockout are all measured against it.

### 2.10. Validation Order and Error Precedence

When more than one rule could reject a request, the server reports only the highest-priority failure, evaluated in the following fixed order.

1. **Authentication** — the `X-User-Role` header must be present and must name a declared role; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the caller's role must permit the operation, and an entity-backed caller may act only on its own channel, claim or content item; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence** — path and body resources must exist, resolved left to right as described in §2.7, yielding the 404 family of errors.
4. **State admissibility** — the target resource must be in a state that admits the operation; publishing a membership schedule additionally requires the owning channel to be in `MONETIZATION_APPROVED`. A failure is `ERR_INVALID_STATE` (HTTP 409).
5. **Posture gates** — a `FROZEN` posture rejects every revenue-generating or monetization write with `ERR_POSTURE_FROZEN`, and a `RESTRICTED` posture rejects new monetization applications, dispute filings, classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (both HTTP 409).
6. **Temporal business rules** — a claim may be disputed only while its age is within the thirty-day window, otherwise `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409).
7. **Appeal ladder limits** — at most two appeals per claim, a second appeal only after a decided first appeal; otherwise `ERR_APPEAL_LIMIT_REACHED` (HTTP 409).
8. **Appeal lockout** — a reinstated claim may be re-appealed only after the fourteen-day lockout, otherwise `ERR_APPEAL_LOCKOUT` (HTTP 409).
9. **Appeal referential constraints** — at most one pending appeal per claim, and a claim already taken down can never be appealed again; violations yield `ERR_APPEAL_ALREADY_PENDING` or `ERR_CLAIM_TERMINAL` (both HTTP 409).
10. **Reference fingerprint uniqueness** — a re-used `reference_fingerprint` is rejected with `ERR_DUPLICATE_REFERENCE_FINGERPRINT` (HTTP 409).
11. **Payment threshold** — a payout batch whose `adjusted_net_cents` is below the channel's `payment_threshold_cents` may not be released; the rejection is `ERR_BELOW_PAYMENT_THRESHOLD` (HTTP 409).
12. **Member eligibility** — a member payout run against a channel with no `ACTIVE` `ChannelMembership` row is rejected with `ERR_NO_ELIGIBLE_MEMBERS` (HTTP 409) rather than silently paying nobody.
13. **Match-confidence range** — a manual claim's `match_confidence` must lie within the inclusive range from 0.500 to 1.000; a value of 0.499 is rejected and 0.500 is accepted, with `ERR_INVALID_MATCH_CONFIDENCE` (HTTP 400).

Two further code-level checks sit alongside this ladder: a classification pass that supplies a category outside the recognised vocabulary is rejected with `ERR_INVALID_CATEGORY_CODE` (HTTP 400), and a stream type outside the four recognised streams is rejected with `ERR_UNSUPPORTED_STREAM_TYPE` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Channel Onboarding and the Monetization Application Loop

A channel is the root of every commercial relationship in this system. It is created with a `channel_name`, a `country_code` that names the ISO-3166 alpha-2 jurisdiction selecting the withholding regime applied to its earnings, a `lifetime_watch_hours` figure measured over the trailing 365 days, and a `subscriber_count`. Four further attributes are accepted optionally at creation: `membership_offered`, which controls whether the channel may sell memberships and defaults to false; `tax_tin_status`, which defaults to `TIN_MISSING` and takes the value `TIN_PROVIDED` once documentation is on file; `tax_treaty`, a boolean defaulting to false that records whether a reduced-rate treaty applies for a non-US `country_code`; `payment_threshold_cents`, the adjusted-net balance a payout batch must reach before it may be issued and which defaults to 10000; and `policy_strike_count`, which defaults to 0 and which may be supplied directly when a channel is brought onto the platform with historical policy actions already on record. A newly created channel starts with `monetization_status` set to `MONETIZATION_NOT_APPLIED`, `monetization_posture` set to `OPEN`, `copyright_strike_count` at 0 and `last_copyright_strike_activated_at` null.

Channel configuration is mutable by its owner or by a platform operator. The updatable surface is exactly `channel_name`, `country_code`, `tax_tin_status`, `tax_treaty`, `payment_threshold_cents` and `policy_strike_count` — notably the watch-hour and subscriber counters are not client-editable, because they are the figures the eligibility gate reads. Any such change increments the channel's `version` by 1 and triggers a recomputation of `monetization_posture`, since raising `policy_strike_count` above zero immediately narrows the channel to `RESTRICTED`.

Applying for monetization moves a channel from `MONETIZATION_NOT_APPLIED` to `MONETIZATION_PENDING`, and the same operation is the path back from `MONETIZATION_REJECTED` to `MONETIZATION_PENDING`, forming a re-application loop in which the eligibility thresholds are re-checked against the channel's current counters on every attempt. Three preconditions guard the transition: the channel must have at least 4000 `lifetime_watch_hours`, at least 1000 `subscriber_count`, and a `policy_strike_count` of exactly zero. The first two are checked together and a shortfall in either — below 4000 watch hours or below 1000 subscribers — is reported as `ERR_MONETIZATION_INELIGIBLE` (HTTP 409); a non-zero policy strike count is reported separately as `ERR_MONETIZATION_BLOCKED_BY_STRIKE` (HTTP 409), so the caller can distinguish an unearned audience from a punitive hold. A channel whose posture is `RESTRICTED` cannot file an application at all and is turned away with `ERR_POSTURE_RESTRICTED`. On success the channel's `monetization_status` becomes `MONETIZATION_PENDING`, its `version` increments by 1, and posture is recomputed — which, at this point, remains `OPEN`, because only a revocation or a non-zero policy strike count can push a channel out of the open posture.

Reviewers do not work from an unordered inbox. The review queue returns only channels whose `monetization_status` is `MONETIZATION_PENDING`, ranked by a composite health score: the channel's `lifetime_watch_hours` divided by the `WATCH_HOURS_DIVISOR` of 1000, plus its `subscriber_count` divided by the `SUBSCRIBER_DIVISOR` of 500, minus the `STRIKE_PENALTY` of 10 multiplied by its `copyright_strike_count`. Candidates are ordered by that score descending, with ties broken by `created_at` ascending — never by `id` — and the score is compared at six decimal places before the tie-break is applied. When no channel is pending, the queue is simply an empty array and no error is raised. Channels in `MONETIZATION_APPROVED`, `MONETIZATION_REJECTED`, `MONETIZATION_REVOKED` or `MONETIZATION_NOT_APPLIED` are excluded from the candidate set regardless of how strong their score would be.

### 3.2. The Reviewer Decision and Its Settlement Cascade

A `MonetizationReviewer` resolves a pending application by supplying a `decision` of `APPROVE` or `REJECT` and an optional free-text `note`. Only a channel currently in `MONETIZATION_PENDING` may be reviewed; anything else is refused as `ERR_INVALID_STATE` (HTTP 409). An `APPROVE` decision moves the channel from `MONETIZATION_PENDING` to `MONETIZATION_APPROVED`, and a `REJECT` decision moves it from `MONETIZATION_PENDING` to `MONETIZATION_REJECTED`.

The `APPROVE` branch is guarded by one additional precondition beyond the pending status: every content item of the channel that has already reached `CLASSIFIED` or `CLAIM_SCAN_COMPLETE` must have an `ad_suitability` other than `NO_ADS`. A single item carrying `NO_ADS` blocks the approval and produces `ERR_CLASSIFICATION_BLOCKS_MONETIZATION` (HTTP 409). This is the deliberate choke point between the classification workflow and the monetization workflow: a channel cannot be admitted to the earning programme while one of its uploads is judged wholly unsuitable for advertising.

When the approval is accepted, four consequences execute in a fixed order, and understanding the order matters because each hop reads what the previous hop wrote.

1. The channel's `monetization_status` becomes `MONETIZATION_APPROVED`, and every content item of that channel whose `upload_status` is `CLASSIFIED` is settled forward to `CLAIM_SCAN_COMPLETE`.
2. That settlement materialises claims: for each content item, one claim is created against every reference file whose rights-scan match reaches a `match_confidence` of at least 0.500. If, and only if, the reviewed channel's `monetization_posture` is `OPEN`, each such claim starts in status `ACTIVE` with its `lock_reason` set to `PENDING_RETRO`.
3. Each claim that is now `ACTIVE` fires the claim-revenue-lock cascade. Every revenue routing row belonging to that content item whose status is `PAID_CREATOR` is moved to `RETROACTIVE_OWED`, its `creator_share_cents` is zeroed and its `partner_share_cents` is raised to the full `gross_revenue_cents` of the row, and the content item's `routed_revenue_cents` is recomputed to zero.
4. The same cascade recomputes the content item's `holds_revenue` to true. This is the value the review response reports, so a reviewer sees immediately that the item's money is now parked rather than paid.

The `REJECT` branch is deliberately thinner. The channel's `monetization_status` becomes `MONETIZATION_REJECTED` and its posture is recomputed, but no content item is settled, no claim is materialised and no revenue is locked. The settlement cascade belongs to the approval branch alone. A rejected channel may re-apply once it meets the eligibility thresholds again, which returns it to `MONETIZATION_PENDING` and puts it back into the review queue.

### 3.3. Upload Classification and Advertiser-Friendliness

A content item is uploaded with a `title`, a `duration_seconds` runtime, a `category_code` used by the advertiser classification rules, and an optional `self_declared_mature` marking that defaults to false. It enters the system in `UPLOADED` status with `ad_suitability` null, `gross_revenue_cents` and `routed_revenue_cents` both at zero, and `holds_revenue` and `takedown_flag` both false. Nothing is classified at upload time.

A creator requests review to move the item from `UPLOADED` to `CLASSIFYING`. The one precondition is that the owning channel's `monetization_posture` is not `FROZEN`; anything else is `ERR_POSTURE_FROZEN` (HTTP 409). At this instant no `AdReview` row exists yet and `ad_suitability` remains null — the item is queued, not decided.

The rights scan resolves an item in `CLASSIFYING` down one of two paths. When the scan finishes with no reference match at or above 0.500, the item moves from `CLASSIFYING` to `CLASSIFIED`. When the scan finishes with at least one reference match at or above 0.500, the item moves from `CLASSIFYING` to `CLAIM_SCAN_COMPLETE`, and one claim is created for each matching reference file, with `source` set to `REFERENCE_AUTO` and `match_confidence` set to the scan score; if the channel's posture is `OPEN`, each of those claims is `ACTIVE` with `lock_reason` set to `PENDING_RETRO`. Both paths create a single `AdReview` row carrying the classification output, and both paths copy that row's `outcome` onto the item as `ad_suitability` and `limited_ads_reasons`.

Classification itself is a threshold rule over the categories submitted for the pass. The recognisable advertiser categories are `GAMBLING`, `ALCOHOL`, `POLITICS`, `NEWS`, `TRAGEDY` and `MILDLANGUAGE`; these are the only categories whose presence can limit advertising. One engagement exception exists, and it applies to exactly one category: when `MILDLANGUAGE` is among the matched categories and the sum of the `AdReview` row's `like_count` and `comment_count` reaches the `MILDLANGUAGE_SUPPRESSION_ENGAGEMENT_THRESHOLD` of 1000 or more, `MILDLANGUAGE` is removed from the matched set before the outcome is decided. The boundary is inclusive — 1000 suppresses and 999 does not — and the threshold is measured against the combined like and comment figure, not against either counter alone. After that suppression, the outcome follows from the remaining count: no matched categories yields `AD_FRIENDLY`, exactly one matched category yields `LIMITED_ADS`, and two or more matched categories yield `NO_ADS`. The item's `limited_ads_reasons` and the `AdReview` row's `reason_codes` both carry the sorted list of matched categories that produced a non-friendly outcome, and both are empty when the outcome is `AD_FRIENDLY`. The `AdReview` row additionally records the sorted `matched_categories` actually matched by the item, alongside the `like_count` and `comment_count` that were supplied and its own `created_at` timestamp marking the reviewer pass.

Two boundary points are worth stating plainly because they carry the most commercial weight. First, one matched limited-eligible category is a limited-ads outcome while two matched categories on an identical revenue profile is a no-ads outcome — the same video with an extra offending category loses advertising entirely. Second, the engagement exception can flip a single-category determination back to fully friendly, so a mild-language video with a large enough like and comment volume is treated as advertiser friendly.

A creator who disagrees with a `LIMITED_ADS` or `NO_ADS` classification may seek a review, which a `MonetizationReviewer` performs by supplying a `grounds_code`. Two preconditions apply: the item must be in `CLASSIFIED`, and its `ad_suitability` must be either `LIMITED_ADS` or `NO_ADS` — an `AD_FRIENDLY` item has nothing to appeal and a `CLAIM_SCAN_COMPLETE` item has a different appeals path. The transition is a self-loop on the item: it does not move off `CLASSIFIED`, and the item remains `CLASSIFIED` with its `ad_suitability` and `limited_ads_reasons` unchanged. The `AdReview` row's `appeal_outcome` becomes `UPHELD`, meaning the original determination stands rather than being reversed. The item's `version` increments by 1. A channel whose posture is `RESTRICTED` may not pursue this appeal and receives `ERR_POSTURE_RESTRICTED`.

Re-classification is a separate, reviewer-driven pass that supplies a replacement `category_codes` set together with the current `like_count` and `comment_count`, and runs the same classification rule over the new category set. It is available from either of the item's two settled resting states — from `CLASSIFIED` and from `CLAIM_SCAN_COMPLETE` alike — and in both cases it holds the item at its current status while rewriting `ad_suitability` and `limited_ads_reasons`: a re-classification from `CLASSIFIED` leaves the item `CLASSIFIED`, and one from `CLAIM_SCAN_COMPLETE` leaves it `CLAIM_SCAN_COMPLETE`. This is where the heaviest cascade in the domain can begin: when a re-classification resolves to `NO_ADS`, the item's advertising is not merely limited — every claim on that item is taken down, a copyright strike is raised for each, and the channel's strike posture is re-evaluated. That cascade is developed in §3.7. A re-classification whose `category_codes` contains a value outside the recognised vocabulary is rejected with `ERR_INVALID_CATEGORY_CODE` (HTTP 400).

### 3.4. Reference Files and Automatic Claim Matching

A `RightsHolder` registers a reference asset by supplying a `rights_holder_name`, an `asset_kind` of `AUDIO`, `VIDEO` or `VISUAL`, a `reference_fingerprint`, a `policy_mode` of `MONETIZE`, `TRACK` or `BLOCK`, a `claimed_segment_seconds` length describing the matched segment whenever the reference fires, and an optional `is_active` flag defaulting to true. The `reference_fingerprint` is a globally unique key across the entire platform: a registration that reuses an existing fingerprint is rejected outright with `ERR_DUPLICATE_REFERENCE_FINGERPRINT` (HTTP 409), and no two reference files may share one.

Registration is not merely an insert, because a new reference can retroactively capture content that was already classified. Only for a content item that is currently sitting in `CLASSIFIED`, whose owning channel's posture is `OPEN`, and whose fingerprint matches the newly registered reference at or above 0.500, is the item moved to `CLAIM_SCAN_COMPLETE` and a new claim created against it with `source` set to `REFERENCE_AUTO`, that claim `ACTIVE` with `lock_reason` set to `PENDING_RETRO`; the claim-revenue-lock cascade then runs against the item immediately. An item whose owning channel's posture is not `OPEN` is not captured by the registration at all, and neither is an item that has already left `CLASSIFIED`. The registered file's own `version` also increments by 1. This is the retroactive-capture path: a rights holder can register an asset today and cause claims to appear on videos uploaded months earlier.

Claims can also be filed manually by a rights holder or a platform operator, in which case the payload carries the `content_item_id` being claimed, the `reference_file_id` being invoked, a `match_confidence` and an optional `claim_level` defaulting to `STANDARD`. A manually filed claim records `source` as `MANUAL`. Its `match_confidence` must lie inside the inclusive range from 0.500 to 1.000: a supplied value of 0.499 is rejected and 0.500 is accepted, with the rejection reported as `ERR_INVALID_MATCH_CONFIDENCE` (HTTP 400). The `claim_level` may be raised to `HIGH`, which is the level that distinguishes a deliberately escalated dispute from a routine one. When the owning channel's posture is `OPEN`, a manual claim starts `ACTIVE` with `lock_reason` set to `PENDING_RETRO`, and it runs the same claim-revenue-lock cascade as an automatic claim.

Every claim carries the derived bookkeeping that downstream workflows read. Its `match_confidence` is recorded to three decimal places, floored rather than rounded, in the range from 0.000 to 1.000. Its `status` moves through `ACTIVE`, `DISPUTED`, `APPEALED`, `REINSTATED`, `RELEASED` and `TAKEN_DOWN`. Its `revenue_locked` flag is true exactly while its `lock_reason` is something other than `NONE`, and `lock_reason` itself takes the values `NONE`, `PENDING_RETRO` and `RETROACTIVE_OWED`. Its `taken_down_at` timestamp stays null until the claim reaches `TAKEN_DOWN`. Its `dispute_deadline_at` is null until the claim first becomes `DISPUTED`, at which point it is set to thirty days after the claim's `created_at`. Its `appeal_attempts` counter records how many appeal attempts have been lodged against it, and its `appeal_count` records how many of its appeals are currently `PENDING`. Its `copyright_counter_notified` flag defaults to false and is the standing prerequisite for releasing a taken-down claim.

### 3.5. Disputing a Claim and the Revenue Lock

A claim raised by the rights scan begins its life `ACTIVE`. The creator's remedy against it is a dispute, filed with a `reason_code` drawn from `FAIR_USE`, `LICENSED`, `PUBLIC_DOMAIN`, `MISMATCH` and `OWNERSHIP`, an optional free-text `narrative` of at most 2000 characters, and the mandatory `expected_claim_version` described in §2.6. Three preconditions guard the filing. The claim must be `ACTIVE` — an `ERR_INVALID_STATE` (HTTP 409) otherwise. The claim must be at most thirty days old, meaning its `created_at` is no earlier than thirty days before the current logical clock instant; once that window has lapsed the filing is refused with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409). And the owning channel's `monetization_posture` must not be `FROZEN`, or the filing is refused with `ERR_POSTURE_FROZEN`.

Two further refusals cover the claim's own history rather than its state: a claim already sitting in `DISPUTED` cannot be disputed a second time and yields `ERR_CLAIM_ALREADY_DISPUTED` (HTTP 409), and a claim that has already been taken down can take no further dispute, appeal or takedown and yields `ERR_CLAIM_TERMINAL` (HTTP 409). A `RESTRICTED` channel is also barred from filing disputes, with `ERR_POSTURE_RESTRICTED`, which is how a channel under a strike restriction loses its principal defensive remedy.

Accepting a dispute writes a `ClaimDispute` row in status `FILED` carrying the `reason_code` and the `narrative`; sets the claim's `dispute_deadline_at` to thirty days after the claim's `created_at`; and moves the claim's status to `DISPUTED`. The financial consequence is immediate and is the reason this workflow is central to the domain. Every revenue routing row belonging to the claimed content item whose status is `PAID_CREATOR` is converted to `RETROACTIVE_OWED`, with its `creator_share_cents` zeroed and its `partner_share_cents` raised to the full `gross_revenue_cents` of that row. The content item's `routed_revenue_cents` is then recomputed to zero, and its `holds_revenue` flag is recomputed to true. Money that had already been credited to the creator is thus reclassified as owed rather than paid, and the item is marked as holding revenue.

The dispute window closes itself if the creator never acts. When the logical clock reaches or passes the claim's `created_at` plus thirty days and no dispute has been filed, the claim moves from `ACTIVE` to `RELEASED` automatically, its `lock_reason` returns to `NONE`, and the content item's `holds_revenue` is recomputed. A claim released this way is terminal; nothing returns it to `ACTIVE`.

The rights holder answers a dispute through a resolution carrying a `resolution` value of `RELEASE`. From the `DISPUTED` state that resolution closes the open `ClaimDispute` row to `RELEASED`, moves the claim to `RELEASED`, returns its `lock_reason` to `NONE`, and releases the content item's parked revenue: like the appeal's upholding in §3.6, it moves every routing row of the claimed content item that sits in `RETROACTIVE_OWED` to `RELEASED_TO_CREATOR`, restoring that row's `creator_share_cents` and `partner_share_cents` to the values the applicable stream split produces for its recorded `gross_revenue_cents`, and then recomputes the content item's `holds_revenue` and its `routed_revenue_cents` to the restored figure. From the `TAKEN_DOWN` state the same resolution is available but carries an extra precondition: the creator must already have filed a counter-notification — a creator-side filing carrying a free-text `statement` that sets the claim's `copyright_counter_notified` flag to true — and acceptance moves the claim from `TAKEN_DOWN` to `RELEASED`, returning its `lock_reason` to `NONE` and releasing the item's parked revenue the same way. The resulting claim is released permanently — it is never returned to `ACTIVE`, and no further takedown may be issued against it — and the owning content item's `takedown_flag` is recomputed to false, since no claim on it remains taken down. A resolution aimed at a taken-down claim before any counter-notification exists is refused with `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN` (HTTP 409), and so is a takedown-scoped resolution against a claim that is not currently `TAKEN_DOWN`.

### 3.6. The Appeal Ladder

The appeal ladder belongs to the rights holder, not the creator, and it can run twice against a single claim. Filing an appeal requires a `grounds_code` drawn from `REVIEW_ERROR`, `NEW_EVIDENCE` and `MISIDENTIFIED`.

The first rung opens while the claim is `DISPUTED`, provided `appeal_count` is zero and the referenced content item is not currently taken down. The system creates a `ClaimAppeal` row with `appeal_level` set to `FIRST` and `status` set to `PENDING`, moves the claim to `APPEALED`, sets the claim's `lock_reason` to `RETROACTIVE_OWED`, and recomputes both `appeal_attempts` and `appeal_count`. Only one appeal may be pending at a time: a filing against a claim that already has a `PENDING` appeal is refused with `ERR_APPEAL_ALREADY_PENDING` (HTTP 409). A claim that has reached `TAKEN_DOWN` can never be appealed again and yields `ERR_CLAIM_TERMINAL` (HTTP 409).

A `RightsHolder` decides a pending first-level appeal by supplying a `decision` of `UPHOLD` or `DENY`. Upholding reverses the claim: the `ClaimAppeal` row's status becomes `UPHELD`, the claim moves to `REINSTATED`, its `lock_reason` returns to `NONE`, and every revenue routing row of the claimed content item that sits in `RETROACTIVE_OWED` is moved to `RELEASED_TO_CREATOR` with its `creator_share_cents` and `partner_share_cents` restored to the values the applicable stream split would produce for that row's recorded `gross_revenue_cents`. The content item's `routed_revenue_cents` is then recomputed and its `holds_revenue` recomputed to false. Denying is the softer outcome: the `ClaimAppeal` row becomes `DENIED`, the claim returns to `DISPUTED` — moving from `APPEALED` back to `DISPUTED` — and the claim's `lock_reason` stays `RETROACTIVE_OWED`, so the money remains parked. Returning the claim to `DISPUTED` on denial is deliberate, because it is what makes the second rung reachable.

The second rung opens from `DISPUTED` once `appeal_attempts` has reached exactly 1 and the most recently filed appeal has been decided — that is, it carries status `DENIED` or `UPHELD` at level `FIRST`. The filing creates a `ClaimAppeal` row with `appeal_level` set to `SECOND` and `status` set to `PENDING`, returns the claim to `APPEALED`, sets `lock_reason` to `RETROACTIVE_OWED`, and recomputes `appeal_attempts` and `appeal_count` once more. Attempting a third appeal, or attempting a second-level appeal before any first-level appeal has been decided, is refused with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409). At most two attempts are recorded against any claim.

A reinstated claim is not permanently closed. It may be appealed again once fourteen days have elapsed since the reinstatement, measured from the `created_at` timestamp of the `UPHELD` `ClaimAppeal` row that produced the reinstatement: the filing requires the claim to be in `REINSTATED` and the logical clock to be at or past that appeal's `created_at` plus fourteen days. It creates a fresh `ClaimAppeal` row at `FIRST` level with status `PENDING`, moves the claim from `REINSTATED` back to `APPEALED`, and sets `lock_reason` to `RETROACTIVE_OWED`. A re-appeal attempted before the lockout lapses is refused with `ERR_APPEAL_LOCKOUT` (HTTP 409). This is the cycle that keeps a contested claim alive across multiple review rounds while the money continues to be held.

### 3.7. Takedown, Copyright Strikes and Channel-Level Consequences

Escalation to takedown is available only from `APPEALED`, and only when the pending appeal has reached the `SECOND` level; a claim that is not `APPEALED`, or whose pending appeal is still at `FIRST`, is refused with `ERR_INVALID_STATE` (HTTP 409). A `FROZEN` channel is barred from the operation with `ERR_POSTURE_FROZEN`, and a claim already taken down is refused with `ERR_CLAIM_TERMINAL`. The takedown then executes a four-hop cascade, and each hop depends on the one before it.

1. The claim's `status` becomes `TAKEN_DOWN` and its `taken_down_at` is stamped with the current logical clock instant. One `CopyrightStrike` row is created in status `ACTIVE`, with its `expires_at` set to ninety days after its own creation.
2. The owning channel's `copyright_strike_count` is recomputed as the number of its `ACTIVE` `CopyrightStrike` rows, and its `last_copyright_strike_activated_at` is recomputed to the `created_at` of the most recent `CopyrightStrike` in `ACTIVE` or `EXPIRED` status.
3. The channel's strike thresholds are applied. If `copyright_strike_count` has reached 3 or more, the channel's `monetization_status` becomes `MONETIZATION_REVOKED`, its `monetization_posture` becomes `FROZEN`, and every payout batch of that channel currently in status `LOCKED` is moved to `FAILED`. Otherwise, if `copyright_strike_count` is exactly 2, the channel's `monetization_posture` becomes `RESTRICTED`. The two boundaries are inclusive at the terminating side and exact at the restricting side: the `COPYRIGHT_TERMINATION_THRESHOLD` of 3 revokes the channel and freezes it, the `COPYRIGHT_RESTRICTION_THRESHOLD` of 2 narrows it, and one strike leaves posture `OPEN`.
4. The content item's `ad_suitability` is forced to `NO_ADS`, its `takedown_flag` becomes true, and the `AdReview` row for the item has its `is_visible` flag set to false so the item drops out of the visible review surface.

Each takedown advances the claim, the content item and the channel, so all three increment their `version` by 1 — which is the stale-version signal a client holding an older copy of any of them will hit. A `CopyrightStrike` records the `strike_sequence`, a one-based ordinal of the strike within its channel ordered by `created_at` ascending, together with the `channel_id`, the `content_item_id` of the taken-down upload and the `claim_id` of the claim that escalated. Its `acknowledged` flag defaults to false and records whether the creator has confirmed receipt of the notice; acknowledging a strike is a creator-side bookkeeping act and does not alter any status.

Community policy strikes are issued independently of the copyright machinery. A `Moderator` or `PlatformAdmin` supplies a `kind` of `COMMUNITY` and a `reason_code` of `SEXUAL_CONTENT`, `VIOLENT_CONTENT` or `HATE_SPEECH`, and the system creates a `ChannelStrike` in status `ACTIVE` whose `issued_at` is the current logical clock instant and whose `expires_at` is ninety days later. The channel's `policy_strike_count` is recomputed as the number of its `ACTIVE` `COMMUNITY` strikes and the channel's `monetization_posture` is recomputed. When the third `ACTIVE` `COMMUNITY` strike lands on a channel, the channel's `monetization_status` becomes `MONETIZATION_REVOKED` and every payout batch of that channel in status `LOCKED` is moved to `FAILED`; the constant is the `POLICY_TERMINATION_THRESHOLD` of 3, so a channel on its first or second community strike continues to operate, narrowing to `RESTRICTED` at that point only if it has also accumulated two or more active copyright strikes.

The `NO_ADS` re-classification cascade is the second route into copyright strikes, and it mirrors the takedown cascade while originating from classification rather than from a rights-holder escalation. When a re-classification pass resolves an item to `NO_ADS` — from either the `CLASSIFIED` or the `CLAIM_SCAN_COMPLETE` resting state, the two behaving identically — the item's `ad_suitability` is set to `NO_ADS`, every claim on the item is moved to `TAKEN_DOWN`, one `CopyrightStrike` is created `ACTIVE` per claim with `expires_at` ninety days out, and the channel thresholds are applied exactly as in the takedown cascade: three or more active copyright strikes revoke the channel, exactly two restrict it. The content item's `takedown_flag` becomes true and the `AdReview` row's `is_visible` becomes false. A re-classification therefore punishes a video's own discovery of unsuitable content with the same strike machinery that a rights-holder escalation would trigger.

Strikes expire on a `STRIKE_LIFETIME_DAYS` clock of ninety days and the expiry is swept only when the logical clock advances. When a `CopyrightStrike` crosses its `expires_at` it moves to `EXPIRED`, the channel's `copyright_strike_count` is recomputed against `ACTIVE` rows only, the channel's `monetization_posture` is recomputed, and — when the channel is `MONETIZATION_REVOKED` and `copyright_strike_count` has reached zero — the channel's `monetization_status` returns to `MONETIZATION_PENDING`, putting it back into the reviewer queue. When a `ChannelStrike` crosses its `expires_at` it moves to `EXPIRED`, the channel's `policy_strike_count` is recomputed against `ACTIVE` `COMMUNITY` rows only, and the channel's `monetization_posture` is recomputed. A revoked channel is restored to `MONETIZATION_PENDING` with posture `OPEN` only once the sweeper has left every one of its `ChannelStrike` and `CopyrightStrike` rows expired, so both counters must read zero simultaneously; a channel still carrying a live community strike stays revoked even after its copyright strikes have lapsed.

Posture recomputation follows the ordered branches of §2.4 on every one of these events, which is why a channel can move between `OPEN`, `RESTRICTED` and `FROZEN` many times across its life without any client ever setting the field.

### 3.8. Revenue Streams, Splits and the Routing Ledger

Money enters the platform as revenue events. A `PlatformAdmin` records one by supplying a `stream_type` of `AD`, `MEMBERSHIP`, `SUPER_CHAT` or `SHOPPING`, an `amount_cents` gross figure, and — for item-scoped streams only — a `content_item_id` naming the earning upload; the field is null for a channel-wide stream event, such as a membership month, that is not attributable to a single video. A stream type outside those four values is rejected with `ERR_UNSUPPORTED_STREAM_TYPE` (HTTP 400). The event is created with `routed` false and its `occurred_at` stamped with the current logical clock instant, and it stays unrouted until a routing row is minted from it.

Revenue is routed into `RevenueRouting` rows, each of which records the `content_item_id` whose revenue is being routed, the `claim_id` that captured the segment or null when no claim applies, the `stream_type` and `gross_revenue_cents` being routed, and the mandatory `expected_content_item_version` naming the observed version of the owning content item. Omitting that field, or supplying a version older than the item's current `version`, is refused with `ERR_STALE_VERSION` (HTTP 412) — the guard exists because a claim's arrival mutates the item and therefore advances its version, so a writer whose picture of the item predates the claim is exactly the writer who must not be allowed to route against it. A channel whose posture is `FROZEN` cannot route at all and is refused with `ERR_POSTURE_FROZEN`.

The split itself is fixed per stream and is applied to each routing record in isolation. The creator receives the half-up rounding of the record's gross amount multiplied by the stream's rate: 0.55 for `AD`, 0.70 for `MEMBERSHIP`, 0.70 for `SUPER_CHAT`, and 0.60 for `SHOPPING`. The claimant receives everything that remains of that record's gross after the creator share is taken — the partner share is never computed by applying a complementary rate and rounding it, it is computed by subtraction, which is what makes the two shares always sum to the record's gross with no drift. The corresponding named rates are the `AD_CREATOR_RATE` of 0.55, the `MEMBERSHIP_CREATOR_RATE` of 0.70, the `SUPER_CHAT_CREATOR_RATE` of 0.70 and the `SHOPPING_CREATOR_RATE` of 0.60 — which is why the split is referred to internally as the royalty share split.

The order of the rounding step is the single most consequential detail in this calculation and it is not negotiable. Rounding happens once per routing record, never against a batch total. Concretely, three `AD` routing records of 1001 cents each produce creator shares of 551, 551 and 551 — a total of 1653 cents — because each record rounds independently; rounding the 3003-cent sum once instead produces 1652 cents. The system must therefore never sum first and round afterwards.

A routing record's status depends on the item's routing ledger. When no routing row of the item already sits in `ESCROW` or `RETROACTIVE_OWED` the new record is created as `PAID_CREATOR`. When at least one of the item's routing rows is already in `ESCROW` or `RETROACTIVE_OWED` — which is the reading of the item's `holds_revenue` flag that this rule is stated in terms of — the new record is created as `ESCROW` and its creator share is parked rather than paid. Both cases populate the full set of split fields, including the `matched_segment_seconds` the record consumed, which is zero for a full-item routing. After the routing row is written, the content item's `routed_revenue_cents` is recomputed as the sum of the creator shares of every routing row recorded against it, and the item's `version` increments by 1.

The routing ledger has a second, system-driven mode of operation. A cascade capability locks or unlocks an item's routed revenue as claims are created and resolved, and it is driven by a `locked` boolean and a `reason_code`. When `locked` is true, every routing row of the item currently sitting in `PAID_CREATOR` is converted to `RETROACTIVE_OWED`, its `creator_share_cents` is zeroed and its `partner_share_cents` is raised to the row's full `gross_revenue_cents`. The item's `routed_revenue_cents` is then recomputed — to zero when everything has been converted — and the item's `holds_revenue` flag is recomputed. The item's `version` increments by 1. This is the mechanism the approval settlement, the dispute filing, the claim suspension and the automatic claim creation all invoke when they need to park money.

### 3.9. Settlement Waterfall Across Claims and the Channel

Settling an item distributes its `gross_revenue_cents` across the parties who have a claim on it, in a fixed priority order, and then leaves the remainder with the channel. The buckets are the item's `Claim` rows ordered by `match_confidence` descending and, where two claims share a confidence, by `created_at` ascending; a bucket representing the absence of any claim follows the claims; and a final channel bucket absorbs whatever is left. Ties on `match_confidence` always break on the earlier `created_at`, never on an identifier.

The waterfall processes every bucket except the last in that order. For each, the holder's amount is the remaining balance minus the half-up rounding of the remaining balance multiplied by the `SPLITTER_SHARE_RATE` of 0.55, which is equivalently the remaining balance multiplied by the `HOLDER_KEEP_RATE` of 0.45 — the holder of each claim keeps 45 per cent of what remains at the point it is reached, and the balance shrinks by that amount before the next bucket is processed. The final channel bucket takes whatever balance is left after every claim bucket has been served, which is what guarantees that the bucket amounts always sum exactly to the item's `gross_revenue_cents` with no rounding remainder stranded. Buckets are consumed highest-confidence first; processing them lowest-confidence first would not change the conserved total but would change every bucket's individual subtotal. The item's `version` increments by 1 when the settlement completes.

### 3.10. Memberships and Member Payouts

Membership revenue is priced by a schedule rather than by a routing row. A creator publishes a schedule with a `tier_name`, a `monthly_fee_cents` gross monthly price and an optional `perks` list defaulting to empty. Publishing is available only while the owning channel's `monetization_status` is `MONETIZATION_APPROVED`; a channel in any other monetization status is refused with `ERR_INVALID_STATE` (HTTP 409), which is the second place in this specification where monetization approval is a hard precondition rather than a posture gate. On success the channel's `membership_offered` flag is set to true.

The schedule's four derived figures — `creator_share_cents`, `platform_share_cents`, `network_fee_cents` and `member_charge_cents` — are each rounded independently to the nearest whole cent, half-up, and none of them is derived by subtracting another rounded figure. The `creator_share_cents` is the half-up rounding of the monthly fee multiplied by 0.70, the `MEMBERSHIP_CREATOR_RATE`. The `platform_share_cents` is the half-up rounding of the monthly fee multiplied by the remaining 0.30. The `network_fee_cents` is the half-up rounding of the monthly fee multiplied by 0.03, the `NETWORK_FEE_RATE`, and it is added on top of the fee rather than carved out of it, because it is paid by the member. The `member_charge_cents` is the monthly fee plus the `network_fee_cents`, unrounded beyond the fee's own whole-cent precision. Deriving the platform share by subtracting a rounded creator share from a rounded member charge would produce different cents and is explicitly not the sanctioned method — the components are rounded independently, and that ordering is the only sanctioned one.

Individual membership enrolment records a `member_name`, a `monthly_fee_cents` and an optional `joined_at` membership start instant, which defaults to the current logical clock instant when omitted and which serves as the primary tie-break in the member payout ranking below. An enrolled `ChannelMembership` starts with `status` `ACTIVE`, `paid_member_months` at 0 and `payout_cents` at 0.

Member payouts are distributed by a ranked waterfall rather than by an even division. The candidate set is the channel's `ChannelMembership` rows whose `status` is `ACTIVE`, and an empty candidate set is a hard rejection with `ERR_NO_ELIGIBLE_MEMBERS` (HTTP 409) rather than a silent no-op. The run takes a `total_payout_cents` pool and the channel's `expected_channel_version` as its observed version input. Candidates are ranked by `paid_member_months` descending first, then by `joined_at` ascending, then by `created_at` ascending — never by `id` — so two members with the same count of paid months are separated by whichever joined earlier. Each member in rank order is granted the half-up rounding of that member's `paid_member_months` multiplied by the per-month unit of 25 cents — the `MEMBER_REVENUE_UNIT_CENTS` constant — and that grant is clamped to whatever remains in the pool: if the computed grant would exceed the remaining balance, the member receives exactly the remainder and the pool is exhausted. Each member's `payout_cents` is set to the granted amount and the remaining pool is reduced by that grant before the next member is served, which means the members at the bottom of the ranking may receive nothing once the pool runs dry. The run increments the channel's `version` by 1, and it is identified by `SELECTOR_VERSION` 1 so that a future change to the ranking or the per-month unit can be distinguished in the audit trail.

### 3.11. Payout Batches, Withholding and the Payment Threshold

Payout is a two-stage process, and the two stages are deliberately separate rows. Locking assembles a batch for a period from a `period_start_at` inclusive lower bound and a `period_end_at` exclusive upper bound on routing-record creation, together with the channel's `expected_channel_version` as its observed version input. The batch created by the lock carries its `stage` set to `ROUTE` and its `status` set to `LOCKED`, and its aggregate fields — `gross_cents`, `creator_share_cents`, `partner_share_cents` and `held_cents` — are summed over the routed set.

The routed set is pinned precisely: it contains the routing rows recorded against content items owned by the channel, whose status is one of `RELEASED_TO_CREATOR`, `PAID_CREATOR` or `ESCROW`, and whose creation timestamp falls in the half-open window from `period_start_at` inclusive to `period_end_at` exclusive. `gross_cents` sums those rows' gross amounts, `creator_share_cents` sums their creator shares, and `held_cents` sums the creator shares of the `ESCROW` subset only — money that is parked rather than payable. A batch is always born `LOCKED`; the payment threshold is enforced at release time and never at lock time, so a batch that is too small to pay can still be assembled and inspected.

The lock-stage figures are a provisional estimate and are labelled as such. Against the same routed set the estimate reports the gross total minus the held subtotal minus the withholding, without the residual adjustment the release step applies, so it can differ from the amount later committed. This is intentional: the estimate is a forecast and the release is the settlement.

Releasing a batch is a `PlatformAdmin` operation that takes the mandatory `expected_payout_batch_version`, naming the observed version of the batch. A version older than the batch's current `version` — which advances legitimately whenever a lock-stage assembly or a tax-status change touches the batch — is refused with `ERR_STALE_VERSION` (HTTP 412). Before any amount is paid, the release applies the payment threshold: the batch's `adjusted_net_cents` must have reached the channel's `payment_threshold_cents`, which defaults to 10000 cents and which a creator or operator can raise or lower through the channel update surface. A batch falling short is refused with `ERR_BELOW_PAYMENT_THRESHOLD` (HTTP 409).

The withholding applied at release depends on the channel's tax documentation first and its jurisdiction second. If the channel's `tax_tin_status` is `TIN_MISSING`, the rate is 0.30 regardless of country and regardless of any treaty flag — the `TIN_MISSING_PENALTY_RATE` outranks the entire country table, and for a country whose documented non-treaty rate is 0.24 it produces a penalty delta of 0.06. Only when the status is `TIN_PROVIDED` does the country table apply: a `country_code` of `US` yields the `US_RATE` of 0.00; otherwise a channel with a treaty in force (`tax_treaty` true and a non-US country) collapses to the `TREATY_RATE` of 0.15 for every country it applies to, overriding the country table entirely and, for example, dropping a German channel from 0.26 to 0.15; and otherwise the country's own rate applies, with `GB` at the `GB_RATE` of 0.20, `DE` at the `DE_RATE` of 0.26, `IN` at the `IN_RATE` of 0.24 and `BR` at the `BR_RATE` of 0.24, and any other non-US country taking the `DEFAULT_NON_TREATY_RATE` of 0.24. The corresponding constants are `TIN_MISSING_PENALTY_RATE`, `US_RATE`, `TREATY_RATE`, `GB_RATE`, `DE_RATE`, `IN_RATE`, `BR_RATE` and `DEFAULT_NON_TREATY_RATE`. The selected rate is recorded on the batch as `withholding_rate_pct`, a three-decimal fraction, so the applied regime is auditable after the fact.

The net figure — the `adjusted_net_cents` balance — is then computed in a fixed step order. The payer base is the batch's `creator_share_cents` minus its `held_cents`, which excludes the parked escrow money from the payable amount. The `tax_withheld_cents` is the half-up rounding of that payer base multiplied by the withholding rate, and it is the only rounding step in this calculation. The raw net is the payer base minus the withheld amount, and the `adjusted_net_cents` balance is that figure, floored at zero — a computed negative falls to zero rather than being carried as a debt. The channel's `payment_threshold_cents` defaults to the `PAYMENT_THRESHOLD_DEFAULT_CENTS` value of 10000 and may be raised or lowered through the channel update surface.

A successful release writes a second `PayoutBatch` row at stage `PAYOUT`, linked back to the `ROUTE` row through its `route_batch_id`, with status `RELEASED` and `paid_at` stamped with the current logical clock instant; the original `ROUTE` row is also moved to `RELEASED` with the same `paid_at`. The batch's `version` increments by 1. The `ROUTE` and `PAYOUT` rows are separate resources precisely so that the settled amount can be compared against the estimate, and the two figures diverge whenever the routed set gains a row minted after the lock — a newly created `PAID_CREATOR` routing, or a `RELEASED_TO_CREATOR` row minted by a claim release — which is the intended audit signal that a payout was settled against facts the lock did not see. A `PAYOUT`-stage batch can be traversed back to its `ROUTE` predecessor for exactly this comparison: the route batch of a payout batch is the `ROUTE` row it links to, and the lookup returns an array containing that row.

### 3.12. Read Surfaces and Reverse Reachability

Beyond the lifecycle writes, the API exposes a read surface that lets an operator reconstruct how a number was arrived at. Listing endpoints exist for channels, for a channel's content items, for content items across channels filtered by channel, for reference files, for claims filtered by content item, reference file or status, and for a channel's payout batches. Single-resource reads exist for a channel, a content item, a reference file, a claim and a payout batch addressed by its own identifier.

Several reads exist specifically to traverse a relationship backwards from the child to the parent context. A content item's classification reviews can be listed, which is how the sequence of `AdReview` rows recorded against an upload is inspected. The disputes filed against a claim can be listed, and likewise the appeals filed against a claim. A content item's routing records can be listed, as can the routing records attributable to a claim and every routing record of a channel. The revenue events attributed to a content item can be listed, as can a channel's revenue events. Copyright strikes can be listed by channel, by content item and by claim, so that a strike can be traced to the upload and the claim that produced it; community strikes can be listed by channel; membership schedules and enrolled members can be listed by channel. The payout batch route-batch lookup described in §3.10 is part of this same family. All of these reads are available to any authenticated role.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection, return `201 Created`. Operations that modify an existing resource return `200 OK`. Reads return `200 OK`. The base path for every route is `/api`. Authorized roles are named exactly as enumerated in §2.1; `Any` denotes the read-only umbrella available to every authenticated role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock to a supplied instant and run the strike expiry sweep | PlatformAdmin |
| POST | `/api/channels` | Create a channel | Anonymous, PlatformAdmin |
| GET | `/api/channels` | List channels | Any |
| GET | `/api/channels/{id}` | Get one channel | Any |
| PATCH | `/api/channels/{id}` | Update mutable channel configuration | Creator, PlatformAdmin |
| POST | `/api/channels/{id}/monetization-applications` | Apply for monetization, or re-apply after a rejection | Creator |
| POST | `/api/channels/{id}/monetization-review` | Reviewer decision on a pending monetization application | MonetizationReviewer |
| GET | `/api/review-queue` | Reviewer queue of pending channels, ranked by channel health score | MonetizationReviewer |
| POST | `/api/channels/{id}/content-items` | Upload a content item | Creator, PlatformAdmin |
| GET | `/api/channels/{id}/content-items` | List content items of a channel | Any |
| GET | `/api/content-items` | List content items across channels | Any |
| GET | `/api/content-items/{id}` | Get one content item | Any |
| POST | `/api/channels/{id}/content-items/{id}/requests-review` | Drive an item into classification; the rights scan then resolves it | Creator |
| POST | `/api/channels/{id}/content-items/{id}/classification-appeals` | Creator appeal against a limited-ads or no-ads classification | MonetizationReviewer |
| POST | `/api/content-items/{id}/classifications` | Re-classify an item; a no-ads resolution drives the takedown cascade | Reviewer, MonetizationReviewer |
| POST | `/api/content-items/{id}/settle` | Run the settlement waterfall over the item's claims and channel | PlatformAdmin |
| PATCH | `/api/content-items/{id}/revenue-lock` | System cascade: lock or unlock the item's routed revenue | PlatformAdmin |
| POST | `/api/reference-files` | Register a rights-holder reference file and match it against classified items | RightsHolder, PlatformAdmin |
| GET | `/api/reference-files` | List reference files | Any |
| GET | `/api/reference-files/{id}` | Get one reference file | Any |
| GET | `/api/content-items/{id}/ad-reviews` | List the classification reviews of an item | Any |
| GET | `/api/content-items/{id}/revenue-events` | List revenue events attributed to an item | Any |
| POST | `/api/claims` | File a manual claim against a content item | RightsHolder, PlatformAdmin |
| GET | `/api/claims` | List claims filtered by content item, reference file or status | Any |
| GET | `/api/claims/{id}` | Get one claim | Any |
| POST | `/api/claims/{id}/dispute` | File a creator dispute inside the thirty-day window | Creator |
| GET | `/api/claims/{id}/disputes` | List the disputes filed against a claim | Any |
| POST | `/api/claims/{id}/dispute/resolve` | Release or uphold a disputed or taken-down claim | RightsHolder |
| POST | `/api/claims/{id}/appeals` | File a claim appeal at first level, second level, or after reinstatement | RightsHolder |
| GET | `/api/claims/{id}/appeals` | List the appeals filed against a claim | Any |
| POST | `/api/claims/{id}/appeals/{id}/decide` | Decide a pending claim appeal | RightsHolder |
| POST | `/api/claims/{id}/counter-notifications` | File a creator counter-notification against a taken-down claim | Creator |
| POST | `/api/claims/{id}/takedown` | Escalate an appealed claim to takedown and issue a copyright strike | RightsHolder |
| GET | `/api/channels/{id}/copyright-strikes` | List copyright strikes of a channel | Any |
| GET | `/api/content-items/{id}/copyright-strikes` | List copyright strikes raised on a content item | Any |
| GET | `/api/claims/{id}/copyright-strikes` | List copyright strikes caused by a claim | Any |
| POST | `/api/channels/{id}/strikes` | Issue a community policy strike on a channel | Moderator, PlatformAdmin |
| GET | `/api/channels/{id}/strikes` | List strikes of a channel | Any |
| POST | `/api/channels/{id}/revenue-events` | Record a gross revenue event on a stream | PlatformAdmin |
| GET | `/api/channels/{id}/revenue-events` | List revenue events of a channel | Any |
| POST | `/api/revenue-routings` | Route an item's gross revenue into a routing record | PlatformAdmin |
| GET | `/api/content-items/{id}/revenue-routings` | List routing records of an item | Any |
| GET | `/api/claims/{id}/revenue-routings` | List routing records attributable to a claim | Any |
| GET | `/api/channels/{id}/revenue-routings` | List every routing record of a channel | Any |
| POST | `/api/channels/{id}/membership-schedules` | Publish a membership pricing schedule | Creator |
| GET | `/api/channels/{id}/membership-schedules` | List membership schedules of a channel | Any |
| POST | `/api/channels/{id}/memberships` | Enrol a member on the channel | Creator, PlatformAdmin |
| GET | `/api/channels/{id}/memberships` | List members of a channel | Any |
| POST | `/api/channels/{id}/member-payout-runs` | Run the member payout waterfall over the channel's active members | PlatformAdmin |
| POST | `/api/channels/{id}/payouts/lock` | Assemble and lock a payout batch for a period | PlatformAdmin |
| POST | `/api/channels/{id}/payouts/{id}/release` | Release a locked payout batch, applying withholding | PlatformAdmin |
| GET | `/api/payouts/{id}` | Get one payout batch by its own id | Any |
| GET | `/api/payouts/{id}/route-batch` | Get the route-stage batch linked from a payout-stage batch | Any |
| GET | `/api/channels/{id}/payouts` | List payout batches of a channel | Any |
| GET | `/api/channels/{id}/payouts/{id}` | Get one payout batch | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CHANNEL_NOT_FOUND` | 404 |
| `ERR_CONTENT_ITEM_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_REFERENCE_FILE_NOT_FOUND` | 404 |
| `ERR_PAYOUT_BATCH_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CLAIM_ALREADY_DISPUTED` | 409 |
| `ERR_CLAIM_TERMINAL` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_APPEAL_ALREADY_PENDING` | 409 |
| `ERR_APPEAL_LOCKOUT` | 409 |
| `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN` | 409 |
| `ERR_POSTURE_FROZEN` | 409 |
| `ERR_POSTURE_RESTRICTED` | 409 |
| `ERR_MONETIZATION_INELIGIBLE` | 409 |
| `ERR_MONETIZATION_BLOCKED_BY_STRIKE` | 409 |
| `ERR_CLASSIFICATION_BLOCKS_MONETIZATION` | 409 |
| `ERR_INVALID_CATEGORY_CODE` | 400 |
| `ERR_DUPLICATE_REFERENCE_FINGERPRINT` | 409 |
| `ERR_INVALID_MATCH_CONFIDENCE` | 400 |
| `ERR_BELOW_PAYMENT_THRESHOLD` | 409 |
| `ERR_NO_ELIGIBLE_MEMBERS` | 409 |
| `ERR_UNSUPPORTED_STREAM_TYPE` | 400 |
