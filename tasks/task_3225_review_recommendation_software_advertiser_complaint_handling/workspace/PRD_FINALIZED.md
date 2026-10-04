# Review Recommendation Complaints API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a Yelp-style review and recommendation platform: the backend service that ingests consumer reviews, decides which reviews to surface or filter via automated recommendation software, and adjudicates the disputes that arise when business owners disagree with that outcome. The platform treats advertising and content moderation as strictly separate concerns — paid placement must never alter a review's recommendation state — while still offering a full advertiser stack (sponsored placement, call tracking, attribution reporting) on top of claimed business pages.

Around that central workflow, the system must support a broader set of operational responsibilities: business page claiming and ownership transfers, duplicate-listing merges, consumer alerts that flag manipulation evidence on a page, strikes and force-flagging cascades against reviewers implicated in solicitation, and a tightly controlled pipeline for handling media, subpoena, and law-enforcement requests for reviewer identity. Each of these workflows is governed by its own state machine, its own segregation-of-duties rules, and a deterministic logical clock that the operations team can advance for testing and scheduled work.

The audience for this document is the engineering team implementing the service. Every section below is normative: where the prose defines a state, an error code, a formula, or a cascade, implementations are expected to follow it exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting party and `X-User-Role` declares their operational capacity. The platform recognizes nine roles, spelled exactly as follows: `PlatformOps`, `Reviewer`, `BusinessOwner`, `Advertiser`, `ContentModerator`, `TrustInvestigator`, `SupportAdmin`, `LegalOps`, and `Reporter`. A request missing either header, or presenting a role string outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `X-User-ID` header carries different semantics depending on the role:

- When `X-User-Role` is `Reviewer`, `BusinessOwner`, `Advertiser`, or `Reporter`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` (for example a review's `author_user_id`, a page's `claimed_by_user_id`, an ad account's `owner_user_id`, or a case's `reporter_user_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `PlatformOps`, `ContentModerator`, `TrustInvestigator`, `SupportAdmin`, or `LegalOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `decided_by_admin_id` on a `Complaint`, `PageClaim`, or `MergeRequest`, or as `lifted_by_admin_id` on a `ConsumerAlert`) but does not compare it to any entity's `id`.

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

Endpoints returning collections accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` indicates how many items to skip before returning the page; it defaults to 0. Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope.

### 2.4. The Logical Clock

The platform runs on a deterministic logical clock rather than wall-clock time. At server startup, the logical "now" is exactly `2026-09-01T00:00:00Z`, and the server must not silently fall back to wall-clock time. A `PlatformOps` operator may advance the clock by posting a target instant (`to_iso8601`); advancing applies lazy time-based effects throughout the system: a `PageClaim` left in `SUBMITTED` past its seven-day verification window becomes `EXPIRED`, an `AdCampaign` whose `ends_on` date is in the past transitions to `COMPLETED`, and an `AdAccount`'s `spent_today_cents` resets to zero when the UTC calendar day rolls over (the reset is applied lazily on the next charge or read against the account).

### 2.5. Common Resource Properties

Every first-class resource carries a server-minted `id` (a UUID, with no type prefix), a `created_at` timestamp, and an `updated_at` timestamp — both ISO 8601 UTC with three fractional digits — plus a monotonically incrementing integer `version` that bumps on every mutation. The three event-like resources in the advertising stack — `AdImpressionEvent`, `CallTrackEvent`, and `AttributionReport` — are append-only records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent on them. Whenever any other entity is mutated, `updated_at` is refreshed and `version` is incremented, including when the mutation is a side effect of an operation against a related resource (for example, when a complaint resolution re-points a review, the affected page's `version` and `updated_at` move forward).

### 2.6. Hierarchical Consistency and Cascading Side Effects

Several operations in this domain mutate more than one entity. When that happens, every cascaded mutation is applied atomically alongside the primary change, and each mutated entity has its `updated_at` refreshed and `version` bumped. Notable cascades specified later in §3 include: closing a business page (which suspends its ad account and pauses its active campaigns); approving a `TRANSFER` claim (which reassigns and suspends the attached ad account and rejects the prior owner's open complaints); executing a merge (which re-points reviews, recomputes survivor aggregates, closes the duplicate's ad account, lifts its alerts, expires its pending claims, and rejects any other pending merge touching either page); and confirming a solicitation case (which removes the targeted reviews, increments author strikes, force-flags authors who have accumulated at least two strikes, and auto-places a consumer alert). All of these are described in detail in their workflow subsections.

### 2.7. Nested Resource Retrieval and Validation Order

When an endpoint path embeds multiple identifiers (for example, a review nested under a business page), the server validates path identifiers from left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same left-to-right rule governs foreign keys carried in request bodies: any referenced `page_id`, `campaign_id`, `review_id`, `case_id`, `subject_user_id`, `duplicate_page_id`, or `survivor_page_id` must exist before business-rule checks fire, and a missing reference likewise returns `ERR_NOT_FOUND`. Across the entire surface, validation proceeds in this strict order: authentication of the headers first, then role authorization, then path and body reference existence, then structural payload checks (missing fields, wrong types, enum violations, minimum-length violations, out-of-range values, and reversed date ranges — all surfaced as `ERR_INVALID_REQUEST`), then state-machine admissibility of the operation (`ERR_INVALID_STATE`), and only then domain-specific business rules.

### 2.8. Precision, Scoring, and Rounding

Monetary amounts (budgets, bids, spend, event costs) are stored as integer cents with no rounding. The recommendation software's score is stored as integer per-mille (a value between 0 and 1000) and likewise involves no rounding. The displayed rating average on a business page is stored as an integer equal to one hundred times the true average — when a page's `displayed_review_count` is zero, the average is exactly zero; otherwise it is the sum of `rating` over the displayed reviews, divided by the displayed count, multiplied by 100, and rounded half-up at the final division only (sum first, then divide, then round; never round per-review). Trust scores are integers clamped to the inclusive range 0 to 100.

### 2.9. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency against a parent entity's `version`. In each case the request body must include the named OCC field carrying the parent's `version` as the client last observed it; if the value does not match the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Approving a verified page claim requires `expected_page_version` matching the `BusinessPage`'s current `version`. A mismatch — for example because another admin has just approved a different claim, or a merge re-pointed the page — is rejected with `ERR_STALE_VERSION` (HTTP 412).
- An owner submitting a page info update must include `expected_page_version` matching the page's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), and the owner must re-read the page and retry.
- Executing a merge request requires `expected_duplicate_page_version` matching the duplicate `BusinessPage`'s current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field.

## 3. Business Logic & Workflows

### 3.1. Reviewer Onboarding, Trust, and Sanctions

A `PlatformOps` operator registers a new user by supplying an `email` (unique across all users), a `display_name`, and a `home_region` (a region code such as `US-CA`). A freshly registered `User` starts with `status` = `ACTIVE`, a `trust_score` of 50, and a `strike_count` of 0. The `trust_score` is an integer clamped to the inclusive range 0 to 100 and feeds directly into the recommendation scoring described in §3.3; the `strike_count` records how many times this user has been the author of a review that a `CONFIRMED` solicitation case implicated.

PlatformOps can move a user out of `ACTIVE` at any time. Suspending a user transitions their `status` to `SUSPENDED`; on the next recommendation evaluation, any of their currently `DISPLAYED` reviews will be re-scored with the suspension penalty applied, which typically pushes them to `FILTERED`. Purging a user is stronger: their `status` becomes `PURGED` and every review they have authored that is not already `REMOVED` is forced into `REMOVED`, with each affected page's `displayed_review_count` decremented and `displayed_rating_avg_x100` recomputed. PlatformOps may also directly set a user's `trust_score` to an exact integer (the input is clamped to the inclusive range 0 to 100) via the trust-adjustment capability.

### 3.2. Business Pages, Ownership, and Owner Info Updates

`PlatformOps` creates a `BusinessPage` with a `name`, an `address_line`, a `city`, a `category`, and a `website`. The new page starts in `ACTIVE` status with `claimed_by_user_id` null (unclaimed), `merged_into_id` null, `ad_account_id` null, `displayed_review_count` equal to 0, and `displayed_rating_avg_x100` equal to 0. The address and city are used downstream by duplicate-detection workflows.

Once a page is claimed (see §3.4), the claiming `BusinessOwner` may update the page's mutable info — any subset of `name`, `website`, `category`, `address_line`, or `city` — by submitting the new values along with `expected_page_version`. The version field is non-optional: if it does not match the page's current `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412); otherwise the update is applied and the page's `version` is incremented by 1.

A `SupportAdmin` may close a page, transitioning it from `ACTIVE` to `CLOSED`. Closure cascades: if the page has an attached ad account, that account transitions to `SUSPENDED` and all of its `ACTIVE` campaigns transition to `PAUSED`; any `PageClaim` on the page in `SUBMITTED` or `VERIFIED` transitions to `EXPIRED`. Existing reviews on a closed page remain queryable, but new review submissions are rejected with `ERR_PAGE_NOT_ACTIVE` (HTTP 409).

### 3.3. Review Submission and the Recommendation Software

A `Reviewer` submits a review to a specific page by providing a `rating` (an integer between 1 and 5, inclusive) and a `text` body of at least 20 characters. The system records `page_id`, stamps `author_user_id` from `X-User-ID`, captures `submitted_at` from the logical clock, and initializes `edited_flag` to false and `evidence_confirmed` to false. The review's `recommendation_state` starts at `PENDING`, and the recommendation software is immediately evaluated against it in its at-submission variant — which simply means the age-decay term contributes nothing because `submitted_at` equals the current logical time. This at-submission evaluation applies the threshold rule: the review leaves `PENDING` in the same request and is created directly in `DISPLAYED` (score at least 700) or `FILTERED` (score below 700); when it is created in `DISPLAYED`, the page's `displayed_review_count` and `displayed_rating_avg_x100` reflect it immediately. `PENDING` is therefore a transient initial value — no freshly submitted review remains observable in `PENDING`.

Submission is gated by a strict priority of checks. After the generic auth, existence, and payload checks, the page-side rules fire in this order: the page must be in `ACTIVE` status and must not currently host an `ACTIVE` `ConsumerAlert` whose `review_cooldown_until` is later than the current logical time — any violation is `ERR_PAGE_NOT_ACTIVE` (HTTP 409). Next, the author's own `status` must be `ACTIVE`; otherwise the submission is rejected with `ERR_USER_NOT_ACTIVE` (HTTP 409). Finally, the solicitation prohibition applies: the author must not be the page's claimed owner, and the author must not have an `OPEN` or `INVESTIGATING` `SolicitationCase` targeting their prior reviews on this same page — violations are rejected with `ERR_SOLICITATION_SUSPECT` (HTTP 422).

The recommendation software computes a per-mille score from a small set of signals. Start from a base of 300 plus 4 times the author's `trust_score` (clamped into 0..100 before multiplication), giving a base in the range 300 to 700. If the author's `status` is `SUSPENDED`, subtract 200. If the review's `edited_flag` is true, subtract 50. Then compute the review's age in days as the integer floor of (current logical time minus `submitted_at`) divided by 86400 seconds, cap that age at 100 days, and subtract 2 per capped day. Clamp the result into the inclusive range 0 to 1000 — that integer is the review's `recommendation_score_x1000`. A score of at least 700 transitions the review toward `DISPLAYED`; anything below 700 transitions it toward `FILTERED`. The presence or absence of any advertising relationship — whether the page has an `AdAccount`, whether any `AdCampaign` is running — must not enter the score in any way.

The author of a still-`PENDING` review may edit it — replacing `rating` and `text` — provided they do so within 72 hours of `submitted_at`; a review in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Because at-submission evaluation (above) moves every review out of `PENDING` in the submission request itself, a review is editable only if it is in `PENDING` at the time of the edit attempt. Editing requires that `X-User-ID` equal the review's `author_user_id`; an attempt by anyone else is a forbidden action, and an attempt later than the 72-hour window is rejected with `ERR_EDIT_WINDOW_EXPIRED` (HTTP 410). A successful edit sets `edited_flag` to true and re-queues the review: it stays in `PENDING` until the next evaluation pass.

`PlatformOps` may run the recommendation software over a specific review at any time. This re-evaluation variant applies both the age-decay term and the edit penalty, then applies the threshold rule: from `PENDING` the review moves to `DISPLAYED` when the score is at least 700 (and `evidence_confirmed` is false), or to `FILTERED` otherwise. From `DISPLAYED`, the review drops to `FILTERED` whenever the re-computed score is below 700 — for example because the author's `trust_score` decayed or the author was suspended. From `FILTERED`, the review is promoted back to `DISPLAYED` when the score reaches 700 and `evidence_confirmed` is false. Every transition into `DISPLAYED` increments the parent page's `displayed_review_count` and recomputes its `displayed_rating_avg_x100`; every transition out of `DISPLAYED` decrements the count and recomputes the average. Any transition that would place an evidence-confirmed review into `DISPLAYED` — whether via re-evaluation or via complaint resolution — is rejected with `ERR_REVIEW_EVIDENCE_LOCKED` (HTTP 409). A review in `REMOVED` is terminal and never re-enters scoring.

### 3.4. Page Claims and Ownership Transfer

A `BusinessOwner` initiates a claim on a page by submitting a `kind` (`CLAIM` or `TRANSFER`) and a free-text `evidence_text`. The server records the `claimant_user_id` from `X-User-ID`, mints an 8-character `verification_code`, returns it in the response, and sets the claim's `status` to `SUBMITTED` with `decided_by_admin_id` null. Submission enforces kind-aware admissibility: a `CLAIM` requires the page's `claimed_by_user_id` to be null; a `TRANSFER` requires the page to be currently claimed by someone other than the claimant; in both cases the page must be `ACTIVE` and no other claim in `SUBMITTED` or `VERIFIED` may already exist on the page — any violation is rejected with `ERR_CLAIM_CONFLICT` (HTTP 409).

The claimant must then verify the claim by resubmitting the `verification_code` within 7 days of the claim's `created_at`. The verification must be performed by the claimant themselves (`X-User-ID` equal to the claim's `claimant_user_id`); a successful match moves the claim from `SUBMITTED` to `VERIFIED`. A verification attempted after the seven-day window — or with a code that does not match — is rejected with `ERR_VERIFICATION_EXPIRED` (HTTP 410). If the window elapses without verification, the system marks the claim `EXPIRED` the next time the logical clock advances past it.

A `SupportAdmin` decides a `VERIFIED` claim. Approval requires the request to carry `expected_page_version` matching the page's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Approval also re-checks the kind-aware admissibility against current state — a `CLAIM` still requires an unclaimed page, a `TRANSFER` still requires the page to be claimed by someone other than the claimant, and the page must still be `ACTIVE`. On approval the claim moves to `APPROVED`, the page's `claimed_by_user_id` is set to the claimant, the page's `version` is incremented by 1, and the admin's id is recorded in `decided_by_admin_id`. A `TRANSFER` approval additionally cascades: if the page has an attached ad account, the account's `owner_user_id` is reassigned to the claimant and its `status` is forced to `SUSPENDED` (the new owner must reactivate it explicitly); and every `OPEN` or `UNDER_REVIEW` complaint previously filed by the prior owner on this page is transitioned to `REJECTED` — a prior owner's pending complaints do not survive a transfer. Rejecting a `VERIFIED` claim simply moves it to `REJECTED`.

### 3.5. Advertising Accounts, Campaigns, and Charging

A claimed page's owner may attach a single `AdAccount` by supplying a `daily_budget_cents` (an integer cents value, greater than or equal to 0). The account is created with `status` = `ACTIVE`, `spent_today_cents` = 0, `owner_user_id` equal to the caller's `X-User-ID`, and the page's `ad_account_id` set to point at it. Creation is rejected with `ERR_AD_ACCOUNT_CONFLICT` (HTTP 409) if the page is unclaimed, if the caller is not the claimed owner, or if the page already has an ad account. Only one ad account may ever be attached to a page.

The owner — operating under the `Advertiser` role — creates campaigns against their account by supplying a `kind` (`SPONSORED_PLACEMENT` or `CALL_TRACKING`), a `bid_cents` of at least 1 cent, an inclusive `starts_on` and `ends_on` (both ISO dates in `YYYY-MM-DD` form; `ends_on` must not precede `starts_on`), and a `call_tracking_enabled` flag. The flag's value must agree with `kind`: `CALL_TRACKING` campaigns require `call_tracking_enabled` true; `SPONSORED_PLACEMENT` campaigns require it false. A mismatch is rejected with `ERR_CAMPAIGN_CONFIG` (HTTP 422). A new campaign starts in `DRAFT`.

An `Advertiser` activates a `DRAFT` campaign, provided the parent ad account is `ACTIVE`, the caller is the account's owner, and the current logical date falls within the campaign's `[starts_on, ends_on]` window — activating outside the window is rejected with `ERR_CAMPAIGN_OUT_OF_WINDOW` (HTTP 409). Activation moves the campaign from `DRAFT` to `ACTIVE`. The same transition is used to resume a `PAUSED` campaign; on resume the account must still be `ACTIVE` and the logical date must not be later than `ends_on`. An `ACTIVE` campaign may be paused by its owner, moving it to `PAUSED`; this pause/resume cycle is repeatable. From any of `DRAFT`, `ACTIVE`, or `PAUSED`, the owner may cancel the campaign, moving it to terminal `CANCELLED`. When the logical date advances past a campaign's `ends_on`, the system moves the campaign from `ACTIVE` or `PAUSED` to terminal `COMPLETED`.

The ad account itself has its own lifecycle. A `SupportAdmin` may suspend an `ACTIVE` account — the account moves to `SUSPENDED` and all of its `ACTIVE` campaigns move to `PAUSED`. The same transition happens automatically when the underlying page is closed or when a `TRANSFER` claim is approved. The owner may reactivate a `SUSPENDED` account, returning it to `ACTIVE`, provided the page is still `ACTIVE` — campaigns are not implicitly resumed, and each paused campaign must be re-activated individually. The owner may close an account from `ACTIVE` or `SUSPENDED`; closure moves the account to terminal `CLOSED` and moves every campaign in `DRAFT`, `ACTIVE`, or `PAUSED` to `CANCELLED`.

Charging follows a single rule applied in a pinned order. For a candidate charge — an impression served against a `SPONSORED_PLACEMENT` campaign, or a qualified call against a `CALL_TRACKING` campaign — the candidate cost is the campaign's `bid_cents`. The account admits the charge only if the sum of `spent_today_cents` and the candidate cost does not strictly exceed `daily_budget_cents`; equality is allowed, so spend may land exactly on the cap. If the sum would exceed the cap, the charge is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422). Otherwise `spent_today_cents` is incremented by the candidate cost. The accumulator resets to zero on UTC logical-day rollover, applied lazily on the next charge or read against the account.

### 3.6. Impressions, Call Tracking, and Attribution Reporting

An `Advertiser` (or `PlatformOps` acting on their behalf) records a served impression by providing a `campaign_id` and an `idempotency_key`. The server creates an `AdImpressionEvent` whose `cost_cents` equals the campaign's `bid_cents` and whose `served_on` is the current logical date, then charges the budget per §3.5. The `idempotency_key` is unique within the account: replaying the same key against the same `campaign_id` returns the original event without charging again; replaying the same key against a different `campaign_id` on the same account is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

A tracked call is recorded against a campaign by supplying a `campaign_id`, a `caller_number` in E.164 form, a `called_at` logical timestamp, and a `duration_seconds` of at least 0. The target campaign must be of kind `CALL_TRACKING` and must be in `ACTIVE` status — otherwise the call is rejected with `ERR_CAMPAIGN_NOT_CALL_TRACKING` (HTTP 422). The calendar date of `called_at` must fall within the campaign's `[starts_on, ends_on]` window (inclusive on both ends); a call outside that window is rejected with `ERR_ATTRIBUTION_WINDOW` (HTTP 422). A call whose `duration_seconds` is at least 30 seconds is marked `qualified` = true; shorter calls record `qualified` = false and `cost_cents` = 0 and never touch the budget. A qualified call's `cost_cents` equals the campaign's `bid_cents` and is charged to the budget per §3.5. Each call event also carries an `attribution_window_days` field, fixed at the constant 30, which the reporting variant below consumes.

An `AttributionReport` is generated on demand by supplying a `campaign_id`, an inclusive `period_start` and `period_end` (`period_end` must not precede `period_start`), and a `variant` of `STRICT` or `EXTENDED`. The report computes three numbers. `impressions` counts the `AdImpressionEvent` records for the campaign whose `served_on` date falls in the period. `qualified_calls` counts the campaign's qualified `CallTrackEvent` records, with the window chosen by the variant: under `STRICT` the window is `[period_start, period_end]`; under `EXTENDED` the window is `[period_start − 30 days, period_end]`, so the extended count is always a superset of strict, and the two diverge exactly when qualified calls happened in the 30-day lookback band before `period_start`. `spend_cents` is the sum of the `cost_cents` of the in-window impressions plus the `cost_cents` of the in-window qualified calls. All dates are compared at calendar-day granularity against the logical clock. When several campaigns could in principle claim a caller, attribution is pinned by the `campaign_id` on the request — there is no selector ambiguity.

### 3.7. Owner Complaints and Content Moderation

The claimed owner of a page files a `Complaint` against a review by supplying the `review_id`, a `kind` (`FILTERED_DISPUTE`, `NEGATIVE_DISPUTE`, or `SOLICITATION_REPORT`), and a `body` of at least 10 characters. The new complaint's `status` is `OPEN`, `filer_user_id` is taken from `X-User-ID`, `escalated` is false, and `decided_by_admin_id` is null. Filing is rejected with `ERR_COMPLAINT_CONFLICT` (HTTP 409) when any of: the caller is not the page's claimed owner; the review's `page_id` does not match the page the complaint is filed on; the `kind` is `FILTERED_DISPUTE` but the review is not currently in `FILTERED`; or another complaint on the same review is already in `OPEN`, `UNDER_REVIEW`, or `ESCALATED`.

A `ContentModerator` picks up an `OPEN` complaint by starting review, transitioning it to `UNDER_REVIEW`. Segregation of duties applies: the moderator's `X-User-ID` must not equal the complaint's `filer_user_id`; a self-action is rejected with `ERR_SELF_ACTION` (HTTP 403). From `UNDER_REVIEW` the moderator may escalate, moving the complaint to `ESCALATED` and setting `escalated` to true. Both `UNDER_REVIEW` and `ESCALATED` are decidable states: the moderator may reject the complaint outright (transitioning it to terminal `REJECTED`) or resolve it with one of three actions supplied in the `action` field.

Resolution with `action` = `UPHOLD_FILTER` asserts that the current state is correct and ends the complaint in terminal `RESOLVED_UPHELD`. For a complaint of kind `FILTERED_DISPUTE`, this action additionally requires the subject review to still be in `FILTERED` at resolve time; if the review has since moved (for example because a re-evaluation promoted it), the resolution is rejected with `ERR_REVIEW_STATE_CHANGED` (HTTP 409). Resolution with `action` = `RESTORE_REVIEW` requires the review to be in `FILTERED` and its `evidence_confirmed` to be false; the `evidence_confirmed` check fires first, so an evidence-confirmed review is rejected with `ERR_REVIEW_EVIDENCE_LOCKED` (HTTP 409) regardless of its current `recommendation_state`, and only a review that passes it is then checked for `FILTERED` (a non-`FILTERED` review is rejected with `ERR_INVALID_STATE`, HTTP 409); on success the review's `recommendation_state` moves to `DISPLAYED`, the page's `displayed_review_count` is incremented, the displayed average is recomputed, and the complaint ends in `RESOLVED_ACTIONED`. Resolution with `action` = `REMOVE_REVIEW` requires only that the review not already be `REMOVED`; on success the review transitions to `REMOVED`, the page's displayed aggregates are recomputed (decrementing `displayed_review_count` if the review had been `DISPLAYED`), the author's `trust_score` is reduced by 5 (clamped to the 0..100 floor) with no change to `strike_count`, and the complaint ends in `RESOLVED_ACTIONED`. In all resolution paths the moderator's id is recorded in `decided_by_admin_id`. A complaint in any terminal state (`RESOLVED_UPHELD`, `RESOLVED_ACTIONED`, `REJECTED`) accepts no further moderation action; attempts are rejected with `ERR_INVALID_STATE` (HTTP 409). Complaints filed by a prior owner are also force-transitioned from `OPEN` (or `UNDER_REVIEW`) to `REJECTED` by the system when a `TRANSFER` claim is approved on the page.

### 3.8. Solicitation Cases, Strikes, and Force-Flagging

A `Reporter` files a `SolicitationCase` on a page by supplying `target_review_ids` — an array of 1 to 10 distinct review ids, each on the named page and none already `REMOVED` — plus an `evidence_text` of at least 20 characters. Violations of the target shape (empty list, more than 10 entries, duplicates, reviews on a different page, already-removed reviews) are rejected with `ERR_CASE_TARGETS_INVALID` (HTTP 422). On acceptance the case starts in `OPEN` with `reporter_user_id` taken from `X-User-ID` and `confirmed_review_count` equal to 0.

A `TrustInvestigator` opens an investigation, moving the case from `OPEN` to `INVESTIGATING`. From there the investigator may dismiss the case (terminal `DISMISSED`) or confirm it. Confirmation requires segregation of duties: the investigator must not be the case's reporter — a self-confirm is rejected with `ERR_SELF_ACTION` (HTTP 403). Confirming fires a three-hop cascade.

In the first hop, every target review is marked `evidence_confirmed` = true and moved to `REMOVED`: a `DISPLAYED` review decrements its page's `displayed_review_count` and recomputes the average; a `FILTERED` or `PENDING` review simply transitions without touching aggregates. The case's `confirmed_review_count` is set to the number of target reviews so marked. In the second hop, each distinct author of a confirmed review has their `strike_count` incremented by 1 and their `trust_score` reduced by 15 (clamped to a 0..100 floor); any author whose `strike_count` reaches at least 2 then has all of their other reviews across all pages force-flagged — each such review transitions to `FILTERED` unless it is already `REMOVED`, and any that were `DISPLAYED` decrement their pages' `displayed_review_count` and trigger a recompute of the displayed average. In the third hop, unless an `ACTIVE` consumer alert of kind `SOLICITATION_EVIDENCE` already exists on the case's page, the system auto-places one whose `case_id` references this case, whose `status` is `ACTIVE`, and whose `review_cooldown_until` is the current logical time plus 30 days.

### 3.9. Consumer Alerts

A `SupportAdmin` places a `ConsumerAlert` on a page by supplying a `kind` — one of `SOLICITATION_EVIDENCE`, `SUSPICIOUS_ACTIVITY`, or `MEDIA_ATTENTION` — together with a public `evidence_text` and, when the kind is `SOLICITATION_EVIDENCE`, a `case_id` referencing a `CONFIRMED` solicitation case on the same page. Placement is rejected with `ERR_ALERT_CONFLICT` (HTTP 409) when the kind is `SOLICITATION_EVIDENCE` but the referenced case is missing or not `CONFIRMED`, or when an `ACTIVE` alert of the same kind already exists on the page. On placement the alert's `status` is `ACTIVE`, `lifted_by_admin_id` is null, and `review_cooldown_until` is set to the current logical time plus 30 days. While an `ACTIVE` alert's `review_cooldown_until` is later than the current logical time, new review submissions on the page are rejected with `ERR_PAGE_NOT_ACTIVE` (HTTP 409).

A `SupportAdmin` lifts an `ACTIVE` alert, moving it to terminal `LIFTED` and recording their id in `lifted_by_admin_id`. For a case-linked alert (one whose `case_id` is set), the referenced case must be in `DISMISSED` before the lift is permitted — otherwise the lift is rejected with `ERR_ALERT_CASE_ACTIVE` (HTTP 409). Lifting ends enforcement of the review cooldown immediately.

### 3.10. Identity Requests: Media, Subpoena, and Law Enforcement

`LegalOps` intakes an `IdentityRequest` naming a `subject_user_id`, a free-text `requester_label`, and a `channel` of `MEDIA`, `LEGAL_SUBPOENA`, or `LAW_ENFORCEMENT`, plus a `legal_process_ref` carrying a docket or subpoena reference. The intake policy is asymmetric by design. A request with `channel` = `MEDIA` is refused at intake — the platform's standing policy is that media requests never disclose reviewer identity — and is rejected with `ERR_MEDIA_REQUEST_REFUSED` (HTTP 422). The same rejection fires when `legal_process_ref` is missing for a `LEGAL_SUBPOENA` or `LAW_ENFORCEMENT` request, or is supplied on a `MEDIA` request. An accepted request starts in `RECEIVED` with `notice_sent_at` and `notice_deadline` both null.

From `RECEIVED`, `LegalOps` may move the request to `UNDER_REVIEW` (recall that only `LEGAL_SUBPOENA` and `LAW_ENFORCEMENT` requests reach this point, since `MEDIA` is refused upstream). From `UNDER_REVIEW`, the workflow splits by channel. For a `LEGAL_SUBPOENA` request, `LegalOps` sends notice to the subject user, moving the request to `NOTICE_SENT` and stamping `notice_sent_at` with the current logical time and `notice_deadline` with `notice_sent_at` plus 14 days. Release from `NOTICE_SENT` is blocked until the logical clock reaches `notice_deadline`; an early release attempt is rejected with `ERR_NOTICE_PERIOD_ACTIVE` (HTTP 409), and once the deadline has passed a successful release moves the request to terminal `RELEASED`. For a `LAW_ENFORCEMENT` request, no notice step is required: `LegalOps` releases directly from `UNDER_REVIEW` to terminal `RELEASED`. From any of `RECEIVED`, `UNDER_REVIEW`, or `NOTICE_SENT`, `LegalOps` may decline the request — moving it to terminal `DECLINED` — which is how a subpoena that is quashed during the notice period is recorded. From `RECEIVED` or `UNDER_REVIEW` the request may also be withdrawn, ending in terminal `WITHDRAWN`.

### 3.11. Duplicate Listings and Merges

A `SupportAdmin` files a `MergeRequest` naming a `duplicate_page_id` (the page that will be retired), a `survivor_page_id` (the page that will absorb the duplicate's content), and a `reason` of at least 10 characters. Filing is rejected with `ERR_MERGE_CONFLICT` (HTTP 409) when the two ids are equal, when either page is not in `ACTIVE` status, or when another `PENDING` merge request already references either page. On acceptance the merge request starts in `PENDING` with `decided_by_admin_id` null.

Execution is OCC-guarded: the executing admin must supply `expected_duplicate_page_version` matching the duplicate page's current `version`, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412). Execution also re-verifies that no other `PENDING` merge references either page, that the duplicate and survivor are distinct, and that both are still `ACTIVE`. On success the merge request transitions to `EXECUTED`, the admin's id is recorded in `decided_by_admin_id`, and the duplicate page transitions from `ACTIVE` to `MERGED` with its `merged_into_id` set to the survivor's id and its `version` incremented by 1. The merge cascade then runs.

The first hop re-points every review whose `page_id` equals the duplicate's id to the survivor, preserving each review's `recommendation_state` and `evidence_confirmed` flag — reviews that were `REMOVED` stay `REMOVED`. The survivor's `displayed_review_count` is recomputed as the count of `DISPLAYED` reviews over the union of both pages' reviews, and its `displayed_rating_avg_x100` is recomputed over the same union (sum the ratings of the displayed reviews, divide by the count, multiply by 100, round half-up at the final division; zero when the count is zero). The duplicate's `displayed_review_count` and `displayed_rating_avg_x100` are both zeroed. Reviews on the survivor authored by the survivor's owner remain governed by the solicitation rules unchanged. The second hop closes the duplicate's ad account (if any): the account transitions to `CLOSED` and every campaign on it in `DRAFT`, `ACTIVE`, or `PAUSED` moves to `CANCELLED`. The third hop resolves the duplicate's loose ends: every `ACTIVE` `ConsumerAlert` on the duplicate transitions to `LIFTED`; every `PageClaim` on the duplicate in `SUBMITTED` or `VERIFIED` transitions to `EXPIRED`; and every other `PENDING` `MergeRequest` that references either the duplicate or the survivor transitions to `REJECTED`.

A `SupportAdmin` may also reject a `PENDING` merge request outright, moving it to terminal `REJECTED` with no cascade.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, owner info updates, clock advancement, and cascading actions — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/platform/_clock/set_current_utc` | Advance the logical clock; applies lazy time-based transitions | PlatformOps |
| POST   | `/platform/users` | Register a user | PlatformOps |
| GET    | `/platform/users` | List users | PlatformOps, ContentModerator, TrustInvestigator, SupportAdmin, LegalOps |
| GET    | `/platform/users/{userId}` | Get a user | Any declared role |
| GET    | `/platform/users/{userId}/reviews` | List reviews authored by a user | Any declared role |
| GET    | `/platform/users/{userId}/identity-requests` | List identity requests about a subject user | PlatformOps, LegalOps |
| POST   | `/platform/users/{userId}/suspend` | Suspend a user | PlatformOps |
| POST   | `/platform/users/{userId}/purge` | Purge a user and cascade their reviews to REMOVED | PlatformOps |
| POST   | `/platform/users/{userId}/trust-adjustments` | Set a user's trust_score to an exact value | PlatformOps |
| POST   | `/platform/business-pages` | Create a business page | PlatformOps |
| GET    | `/platform/business-pages` | List business pages with optional filters | Any declared role |
| GET    | `/platform/business-pages/{pageId}` | Get a business page | Any declared role |
| PATCH  | `/platform/business-pages/{pageId}` | Owner updates page info (OCC-guarded) | BusinessOwner |
| POST   | `/platform/business-pages/{pageId}/close` | Close a business page | SupportAdmin |
| GET    | `/platform/business-pages/{pageId}/reviews` | List reviews on a page | Any declared role |
| GET    | `/platform/business-pages/{pageId}/claims` | List claims on a page | PlatformOps, SupportAdmin, BusinessOwner |
| GET    | `/platform/business-pages/{pageId}/complaints` | List complaints on a page | PlatformOps, ContentModerator, SupportAdmin, BusinessOwner |
| GET    | `/platform/business-pages/{pageId}/solicitation-cases` | List solicitation cases on a page | PlatformOps, TrustInvestigator, SupportAdmin |
| GET    | `/platform/business-pages/{pageId}/consumer-alerts` | List consumer alerts on a page | Any declared role |
| POST   | `/platform/business-pages/{pageId}/reviews` | Submit a review | Reviewer |
| GET    | `/platform/reviews` | List reviews with optional filters | Any declared role |
| GET    | `/platform/reviews/{reviewId}` | Get a review | Any declared role |
| PATCH  | `/platform/reviews/{reviewId}` | Author edits a PENDING review within 72h | Reviewer |
| POST   | `/platform/reviews/{reviewId}/evaluate` | Run recommendation software re-evaluation | PlatformOps |
| POST   | `/platform/business-pages/{pageId}/claims` | Submit a CLAIM or TRANSFER request | BusinessOwner |
| GET    | `/platform/page-claims` | List page claims with optional filters | PlatformOps, SupportAdmin, BusinessOwner |
| GET    | `/platform/page-claims/{claimId}` | Get a PageClaim | PlatformOps, SupportAdmin, BusinessOwner |
| POST   | `/platform/page-claims/{claimId}/verify` | Verify a claim with the minted code | BusinessOwner |
| POST   | `/platform/page-claims/{claimId}/approve` | Approve a VERIFIED claim (OCC-guarded) | SupportAdmin |
| POST   | `/platform/page-claims/{claimId}/reject` | Reject a VERIFIED claim | SupportAdmin |
| POST   | `/platform/business-pages/{pageId}/ad-account` | Create the page's ad account | BusinessOwner |
| GET    | `/platform/ad-accounts` | List ad accounts with optional filters | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/ad-accounts/{accountId}` | Get an ad account | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/suspend` | Suspend an ad account | SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/reactivate` | Owner reactivates a suspended account | Advertiser |
| POST   | `/platform/ad-accounts/{accountId}/close` | Owner closes an ad account | Advertiser |
| GET    | `/platform/ad-accounts/{accountId}/campaigns` | List campaigns of an account | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/campaigns` | Create a campaign | Advertiser |
| GET    | `/platform/ad-campaigns` | List campaigns with optional filter | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/ad-campaigns/{campaignId}` | Get a campaign | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-campaigns/{campaignId}/activate` | Activate or resume a campaign | Advertiser |
| POST   | `/platform/ad-campaigns/{campaignId}/pause` | Pause an ACTIVE campaign | Advertiser |
| POST   | `/platform/ad-campaigns/{campaignId}/cancel` | Cancel a DRAFT/ACTIVE/PAUSED campaign | Advertiser |
| GET    | `/platform/ad-accounts/{accountId}/impressions` | List impression events of an account | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/impressions` | Serve and charge a sponsored-placement impression | Advertiser, PlatformOps |
| GET    | `/platform/ad-impression-events` | List impression events with optional filters | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/ad-impression-events/{eventId}` | Get a single impression event | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/ad-accounts/{accountId}/call-events` | List call track events of an account | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/call-events` | Record a tracked call | Advertiser, PlatformOps |
| GET    | `/platform/call-track-events` | List call track events with optional filters | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/call-track-events/{eventId}` | Get a single call track event | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/ad-accounts/{accountId}/attribution-reports` | List attribution reports of an account | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/ad-accounts/{accountId}/attribution-reports` | Generate an attribution report | Advertiser, PlatformOps |
| GET    | `/platform/attribution-reports` | List attribution reports with optional filters | PlatformOps, Advertiser, SupportAdmin |
| GET    | `/platform/attribution-reports/{reportId}` | Get a single attribution report | PlatformOps, Advertiser, SupportAdmin |
| POST   | `/platform/business-pages/{pageId}/complaints` | File a complaint over a review | BusinessOwner |
| GET    | `/platform/complaints` | List complaints with optional filters | PlatformOps, ContentModerator, SupportAdmin, BusinessOwner |
| GET    | `/platform/complaints/{complaintId}` | Get a complaint | PlatformOps, ContentModerator, SupportAdmin, BusinessOwner |
| POST   | `/platform/complaints/{complaintId}/start-review` | Moderator picks up an OPEN complaint | ContentModerator |
| POST   | `/platform/complaints/{complaintId}/escalate` | Escalate an UNDER_REVIEW complaint | ContentModerator |
| POST   | `/platform/complaints/{complaintId}/resolve` | Resolve with UPHOLD_FILTER / RESTORE_REVIEW / REMOVE_REVIEW | ContentModerator |
| POST   | `/platform/complaints/{complaintId}/reject` | Reject an UNDER_REVIEW or ESCALATED complaint | ContentModerator |
| POST   | `/platform/business-pages/{pageId}/solicitation-cases` | File a solicitation case | Reporter |
| GET    | `/platform/solicitation-cases` | List solicitation cases with optional filters | PlatformOps, TrustInvestigator, SupportAdmin |
| GET    | `/platform/solicitation-cases/{caseId}` | Get a solicitation case | PlatformOps, TrustInvestigator, SupportAdmin |
| POST   | `/platform/solicitation-cases/{caseId}/investigate` | Open an investigation | TrustInvestigator |
| POST   | `/platform/solicitation-cases/{caseId}/confirm` | Confirm a case and fire the cascade | TrustInvestigator |
| POST   | `/platform/solicitation-cases/{caseId}/dismiss` | Dismiss a case under investigation | TrustInvestigator |
| POST   | `/platform/business-pages/{pageId}/consumer-alerts` | Place a consumer alert | SupportAdmin |
| GET    | `/platform/consumer-alerts` | List consumer alerts with optional filters | Any declared role |
| GET    | `/platform/consumer-alerts/{alertId}` | Get a consumer alert | Any declared role |
| POST   | `/platform/consumer-alerts/{alertId}/lift` | Lift an ACTIVE alert | SupportAdmin |
| POST   | `/platform/identity-requests` | Intake an identity request | LegalOps |
| GET    | `/platform/identity-requests` | List identity requests with optional filter | PlatformOps, LegalOps |
| GET    | `/platform/identity-requests/{requestId}` | Get an identity request | PlatformOps, LegalOps |
| POST   | `/platform/identity-requests/{requestId}/start-review` | Move an identity request to UNDER_REVIEW | LegalOps |
| POST   | `/platform/identity-requests/{requestId}/send-notice` | Notify the subject user (LEGAL_SUBPOENA only) | LegalOps |
| POST   | `/platform/identity-requests/{requestId}/release` | Release reviewer identity | LegalOps |
| POST   | `/platform/identity-requests/{requestId}/decline` | Decline an identity request | LegalOps |
| POST   | `/platform/identity-requests/{requestId}/withdraw` | Withdraw an identity request | LegalOps |
| POST   | `/platform/merge-requests` | File a duplicate-listing merge request | SupportAdmin |
| GET    | `/platform/merge-requests` | List merge requests with optional filters | PlatformOps, SupportAdmin |
| GET    | `/platform/merge-requests/{mergeRequestId}` | Get a merge request | PlatformOps, SupportAdmin |
| POST   | `/platform/merge-requests/{mergeRequestId}/execute` | Execute the merge (OCC-guarded) | SupportAdmin |
| POST   | `/platform/merge-requests/{mergeRequestId}/reject` | Reject a PENDING merge request | SupportAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PAGE_NOT_ACTIVE` | 409 |
| `ERR_USER_NOT_ACTIVE` | 409 |
| `ERR_SOLICITATION_SUSPECT` | 422 |
| `ERR_REVIEW_EVIDENCE_LOCKED` | 409 |
| `ERR_EDIT_WINDOW_EXPIRED` | 410 |
| `ERR_CLAIM_CONFLICT` | 409 |
| `ERR_VERIFICATION_EXPIRED` | 410 |
| `ERR_AD_ACCOUNT_CONFLICT` | 409 |
| `ERR_CAMPAIGN_CONFIG` | 422 |
| `ERR_CAMPAIGN_OUT_OF_WINDOW` | 409 |
| `ERR_CAMPAIGN_NOT_CALL_TRACKING` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_ATTRIBUTION_WINDOW` | 422 |
| `ERR_COMPLAINT_CONFLICT` | 409 |
| `ERR_REVIEW_STATE_CHANGED` | 409 |
| `ERR_SELF_ACTION` | 403 |
| `ERR_CASE_TARGETS_INVALID` | 422 |
| `ERR_ALERT_CONFLICT` | 409 |
| `ERR_ALERT_CASE_ACTIVE` | 409 |
| `ERR_MEDIA_REQUEST_REFUSED` | 422 |
| `ERR_NOTICE_PERIOD_ACTIVE` | 409 |
| `ERR_MERGE_CONFLICT` | 409 |
