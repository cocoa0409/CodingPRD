# Uge Economy Payouts Age API — Product Requirements Document

## 1. Introduction

The platform described here is a user-generated experience economy: creators publish interactive experiences and marketplace items, players spend a virtual currency called Robux, and a share of every transaction flows back to the creators who built the content. Because the audience includes children, every commercial surface is entangled with safety obligations — age ratings on experiences, parental controls on child accounts, chat filtering, and a moderation pipeline that blends automated classification with human review. This document specifies the API that ties those surfaces together: creator publishing with automated and human moderation of experiences, assets, and text; a virtual-currency economy in which purchases fund creator earnings through tiered exchange rates; a developer exchange program that converts earned Robux into USD subject to identity verification, minimum balances, and tax documentation; experience age guidelines enforced against each viewer's computed age band; marketplace item creation with resale and limited-item scarcity mechanics; moderation appeals with strict segregation of duties; and account termination with a defined earnings-disposition pipeline.

Two cross-cutting concerns dominate the design. First, money: every Robux movement is computed by a pinned formula — tiered, progressive, or waterfall — with explicit rounding rules, and the platform treats Robux balances, lifetime earnings, and payout eligibility as derived values that must reconcile against the underlying orders at all times. Second, safety: the viewer's `age_band`, the child's parental-control settings, and the sender's chat filter level are computed system fields that gate purchases, joins, chat, and even the publication of mature content, and these gates are evaluated before any fiscal check so that a child blocked by a spend limit never sees a generic "insufficient funds" error first.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes seven roles, spelled exactly: `Anonymous`, `Creator`, `Moderator`, `AppealsReviewer`, `SafetyAgent`, `FinanceOfficer`, and `PlatformAdmin`. When a caller attempts an operation their role does not permit, the request is rejected with `ERR_UNAUTHORIZED_ROLE`.

Identity is handled in two distinct ways depending on the role. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` — an experience's `creator_user_id`, a resale listing's `seller_user_id`, a DevEx request's `user_id`, an appeal's `appellant_user_id`, a termination's target `user_id`, and so on — compare the resource's foreign-key field to `X-User-ID`. The same convention holds when a `Creator` acts as the parent on a child account: the parent is the acting `User` and the child is referenced by `child_user_id`. When `X-User-Role` is any of `Anonymous`, `Moderator`, `AppealsReviewer`, `SafetyAgent`, `FinanceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reviewer_user_id` on a `ModerationSubmission` or `ModerationAppeal`, as `triaged_by_user_id` on a `Report`, as `initiated_by_user_id` on an `AccountTermination`, or as `actor_user_id` on an `AuditLog` — but does not compare it to any entity's `id` for ownership. Segregation-of-duties checks that involve two operator identifiers (approver versus payer, original reviewer versus appeals reviewer, initiator versus termination target) compare the recorded `X-User-ID` values directly.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter controls how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource in the system — `User`, `IdentityVerification`, `TaxDocument`, `ParentalControls`, `Experience`, `ExperienceAgeRating`, `ModerationSubmission`, `ModerationAppeal`, `CurrencyPurchaseOrder`, `PurchaseOrder`, `DevExchangeRequest`, `MarketplaceItem`, `ResaleListing`, `ChatMessage`, `Report`, and `AccountTermination` — carries four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation of the resource, including mutations driven by cascades or derived-field recomputation. The `version` is a system-managed integer that increments with every mutation and serves as the basis for optimistic concurrency control. Two resources deviate from this convention: `EngagementSnapshot` and `AuditLog` carry only `id` and `created_at` — both `updated_at` and `version` are absent on them, because snapshot and audit rows are append-only and never mutated after creation.

Cascading transitions respect the same bookkeeping. When a parent entity's transition forces a child into a new state — for instance when a user suspension pushes that user's published experiences into `SUSPENDED` — each affected child's `updated_at` is refreshed and its `version` incremented, exactly as if the child had been mutated directly.

### 2.5. Validation Order and Nested-Path Resolution

Incoming requests are validated in a fixed priority order, and the first failing check determines the returned error. Authentication of the request context comes first: the presence and well-formedness of `X-User-ID` and `X-User-Role`, yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second comes role authorization against the operation, yielding `ERR_UNAUTHORIZED_ROLE`. Third, path-segment identifiers are resolved: every id appearing in a nested URL is checked for existence in strict left-to-right order, and the first missing segment produces the corresponding 404 — `ERR_USER_NOT_FOUND`, `ERR_EXPERIENCE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, or `ERR_TERMINATION_NOT_FOUND` — before any later segment is even consulted. Fourth, the target entity's current state is checked against the requested transition, yielding `ERR_INVALID_STATE`. Fifth come the safety checks — age-band sufficiency, parental spend limits, chat restrictions, and creator-age-for-rating gates — which yield `ERR_AGE_BAND_INSUFFICIENT`, `ERR_PARENTAL_SPEND_LIMIT`, `ERR_PARENTAL_CHAT_RESTRICTED`, or `ERR_CREATOR_AGE_INSUFFICIENT_FOR_RATING`. Safety checks deliberately precede all other business checks, so a minor who is simultaneously over their spend limit and short of funds sees the safety error, not the fiscal one. Sixth come structural business constraints such as the resale price floor, limited-supply exhaustion, segregation of duties, and idempotency conflicts, surfacing `ERR_RESALE_FLOOR_VIOLATION`, `ERR_LIMITED_SUPPLY_EXHAUSTED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_DUPLICATE_IDEMPOTENCY_KEY`, or `ERR_INVALID_REQUEST`. Seventh come cross-entity state gates — an experience must be `PUBLISHED` to join or to sell a gamepass against (`ERR_EXPERIENCE_NOT_PUBLISHED`), an item must be `ON_SALE` to purchase (`ERR_ITEM_NOT_ON_SALE`), and a submission must be `REJECTED` before it can be appealed (`ERR_SUBMISSION_NOT_REJECTED`). Fiscal checks come last of all: insufficient balance (`ERR_INSUFFICIENT_ROBUX`), DevEx eligibility and minimums (`ERR_DEVEX_NOT_ELIGIBLE`, `ERR_DEVEX_MINIMUM_NOT_MET`), and stale optimistic-concurrency versions (`ERR_STALE_VERSION`). A request violating both a safety rule and a fiscal rule always reports the safety error.

### 2.6. Optimistic Concurrency Control

Two write operations in the system carry a mandatory optimistic-concurrency field, and no other endpoint accepts a version field. Submitting a DevEx request requires the client to pass `expected_user_version`, the `version` of the target `User` the client last observed; because marketplace sales, engagement payouts, and parental-control edits all advance the user's `version`, a client whose snapshot of `earned_robux_lifetime` is stale would otherwise lock Robux against an out-of-date eligibility decision. If the supplied value does not match the user's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). The same mechanism guards resale listings: creating a `ResaleListing` requires `expected_item_version`, the `version` of the underlying `MarketplaceItem` last observed by the seller. A price edit, a take-off-sale and put-on-sale cycle, or a moderation-driven state change each advance the item's `version`, and the listing's ask-price floor is computed from that observed price — a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Separately, the same `expected_item_version` is re-validated at the moment a resale purchase is confirmed, per the resale state machine described in §3. The parental-controls write carries an `expected_user_version` of its own, checked against the acting parent user's `version`, also failing with `ERR_STALE_VERSION` on mismatch.

### 2.7. Monetary Precision and Rounding

Robux amounts are integers everywhere: balances, prices, fees, credits, locks, and payouts are stored and returned as whole numbers of Robux. Whenever a calculation produces a fractional Robux value, the final aggregate of that calculation is rounded half-up to zero decimal places — and rounding is applied once, at the end of the calculation, never per tier or per bracket. USD amounts are handled as integer cents (`fiat_amount_cents`, `usd_payout_cents`, `withholding_tax_cents`, `net_payout_cents`, `disposed_usd_cents`) and likewise rounded half-up at the end of their computation. Percentages and rates that appear in formulas — the marketplace fee of 30%, the resale floor of one half, the promotional bonus of ten percent, the per-bracket DevEx ladder rates, and the withholding brackets — are exact constants of the calculation, not inputs.

### 2.8. The Platform Clock and Derived Temporal Fields

The platform maintains a logical clock whose current instant, `current_utc`, is the reference for every age computation, monthly window, and expiry check in the system. The clock starts at 2026-09-01T00:00:00Z at server startup, before any clock-setting call. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant through the clock-setting capability; crossing a user's birthday in the course of that advance triggers recomputation of that user's `age_band` and every field derived from it, exactly as if the recomputation had happened on the user's creation date. Each `User` also carries `account_age_days`, the whole number of days between `created_at` and `current_utc` (any partial day is discarded); this value gates DevEx eligibility at thirty days and limited-item resale at seven days. Calendar-month windows used by the parental spend check and the engagement settlement are defined on UTC month boundaries.

### 2.9. Audit Trail and Idempotent Money Movement

Every state-changing operation in the system writes an `AuditLog` row capturing `actor_user_id` (which may be the system user `00000000-0000-0000-0000-000000000000` when the system itself acts), a dot-notation `action` key such as experience.publish or devex.approve, the `subject_type` and `subject_id` of the entity acted upon, a `payload` holding the before-and-after snapshot fields relevant to the action, and the server timestamp `at`. Audit rows are immutable once written. Both order types — `CurrencyPurchaseOrder` and `PurchaseOrder` — accept a client-supplied `idempotency_key`. A repeated submission under a key already seen returns the original order rather than creating a new charge; a key reused with a different payload is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY`.

## 3. Business Logic & Workflows

### 3.1. Accounts, Age Bands, and Parental Control

A new account is registered by an `Anonymous` caller supplying a `username` (a unique handle of three to twenty characters drawn from letters, digits, and underscore), an `email` used for identity-verification correspondence, a `date_of_birth` in ISO 8601 date form, and an optional `parent_user_id`. Registration produces a `User` in `ACTIVE` status and immediately computes the account's `age_band`: a user younger than thirteen years is `CHILD`, a user at least thirteen but younger than eighteen is `TEEN`, and a user eighteen or older is `ADULT`. Age in years is the whole-year count between `date_of_birth` and the current platform instant, computed against an average year length so that the boundary lands on the birthday itself — a user whose thirteenth birthday is exactly today is already `TEEN`, because "at least thirteen" includes the birthday. Parent linkage is constrained: `parent_user_id` may be null, but when supplied it must reference an existing `User` whose computed `age_band` is `ADULT` and whose own `parent_user_id` is null — a child cannot be parented to another child, nor to a user who is themselves parent-linked. Registration also computes the account's initial `chat_filter_level` and writes an audit entry.

A `User`'s `status` moves from `ACTIVE` to `SUSPENDED` when a `PlatformAdmin` or `SafetyAgent` suspends the account (or when the safety-triage path escalates), supplying a `reason` that is recorded as `suspension_reason`. Suspension is deliberately loud: every `ACTIVE` resale listing owned by the user transitions to `CANCELLED`, every `PUBLISHED` experience owned by the user cascades to `SUSPENDED`, and every `SUBMITTED` DevEx request for the user transitions to `CANCELLED` with its `locked_robux` released. Reinstatement, performed by a `PlatformAdmin`, returns the account from `SUSPENDED` to `ACTIVE` and clears `suspension_reason` — but it does not undo the cascade: experiences suspended by it stay `SUSPENDED`, and the creator must re-publish each one individually. The terminal transition from `ACTIVE` or `SUSPENDED` to `TERMINATED` is system-driven once the account-termination pipeline completes its earnings disposition; it stamps `terminated_at` (immutable thereafter), forces `is_devex_eligible` to false, and pushes all child entities to their terminal states. Both suspension and reinstatement increment the user's `version`.

A parent manages a child's account through the parental-controls capability, creating or replacing the child's `ParentalControls` row. The parent — an authenticated `Creator` acting as the linked parent — supplies `child_user_id` and a `pin_hash` (a bcrypt-style hash of a four-digit PIN, required to authorize later changes to these settings), and may supply `monthly_spend_limit_robux`, `chat_mode`, and `allowed_age_ratings`. A null `monthly_spend_limit_robux` — the default — means no cap; when set, it is a hard cap on the total of the child's completed purchase debits per calendar month. `chat_mode` defaults to `FILTERED` and may be `RESTRICTED` (no free-text chat at all), `FILTERED` (server-side lexical filtering), or `OPEN` (no restriction beyond the child's `age_band`). `allowed_age_ratings` is a whitelist of experience rating levels the child may join — a subset of `ALL`, `NINE_PLUS`, `THIRTEEN_PLUS`, and `SEVENTEEN_PLUS` — and defaults to an empty array, which means the child simply inherits the defaults implied by their `age_band`. The write requires `expected_user_version` matching the parent user's current `version`, rejected with `ERR_STALE_VERSION` when it has advanced, and it bumps the `version` of both the parent and the child, because the child's `chat_filter_level` is recomputed from the new settings. Each row records `last_changed_at`, the timestamp of its most recent mutation. Parents and admins can read the controls for a child back through the same surface.

The `chat_filter_level` itself is a computed field with three values: `SAFE` when the user's `age_band` is `CHILD` or when parental controls set `chat_mode` to `RESTRICTED`; `STANDARD` for a `TEEN`; and `ADULT` for an `ADULT` with no parental override. It is recomputed whenever `age_band` changes or the parental controls are edited, so a child who turns thirteen — or whose parent relaxes the controls — sees their filter level move without any direct write to the user record.

### 3.2. Identity, Tax, and DevEx Eligibility

A creator seeking payouts must clear two paperwork tracks. The identity track begins when the creator submits an `IdentityVerification` with a `document_type` of `PASSPORT`, `DRIVERS_LICENSE`, or `NATIONAL_ID`, a `document_country` in ISO 3166-1 alpha-2 form, and the document's `expiry_date`. The submission lands in `PENDING` with `submitted_at` stamped. A `PlatformAdmin` then verifies it — moving it to `VERIFIED` and stamping `reviewed_at` — or rejects it with a `rejection_reason`, which is mandatory whenever the status becomes `REJECTED`. Independently of review, a verification transitions to `EXPIRED` the moment the platform clock passes `expiry_date`; `reviewed_at` is stamped whenever the status leaves `PENDING`, by whichever path.

The tax track begins when the creator submits a `TaxDocument` with a `form_type` of `W9`, `W8BEN`, or `W8BENE`, the `tin_last4` (the last four digits of the taxpayer identification number), the `legal_name` on the tax record, and the `country_of_residence` in ISO 3166-1 alpha-2 form. The document lands in `SUBMITTED`, transitions automatically to `UNDER_REVIEW` with `submitted_at` stamped, and a `PlatformAdmin` accepts it — status `ACCEPTED`, `reviewed_at` stamped — or rejects it with a mandatory `rejection_reason`. `reviewed_at` is stamped on any transition out of `UNDER_REVIEW`.

The two tracks converge in `is_devex_eligible`, a derived flag recomputed whenever the user is read, whenever a DevEx request is submitted, and again at approval. Six clauses must all hold: the user's `status` is `ACTIVE`; the `age_band` is `ADULT`; the identity verification's `status` is `VERIFIED`; the tax document's `status` is `ACCEPTED`; `account_age_days` is at least thirty; and `earned_robux_lifetime` is at least 30,000 Robux. The first failing clause short-circuits the evaluation and determines the specific eligibility failure. A submission against a user failing any clause is rejected with `ERR_DEVEX_NOT_ELIGIBLE`, and the approval step re-derives the flag at the moment of approval rather than trusting the submit-time value.

### 3.3. Buying Robux: The Tiered Exchange

A creator converts fiat into Robux by creating a `CurrencyPurchaseOrder` with a `fiat_amount_cents` (the USD cents to charge), an opaque `payment_method_token`, and an `idempotency_key`. The order is born `PENDING_PAYMENT`. Confirming the payment — by the buyer or by the payment webhook — transitions it to `COMPLETED`, but only if the `idempotency_key` has not previously been completed; the confirmation computes `credited_robux` from the tiered exchange-rate table and adds it to the buyer's `robux_balance`, stamping `completed_at`. A payment that does not go through is marked `FAILED` by the webhook, with no balance effect.

The exchange rate is deliberately not linear: larger purchases buy Robux at a better marginal rate, and the tiers apply marginally to the cents of this single order. The first 999 cents (from zero) convert at 0.80 Robux per cent; cents from 1,000 through 4,999 convert at 0.90 per cent; cents from 5,000 through 19,999 convert at 1.00 per cent; and every cent from 20,000 upward converts at 1.10 per cent. The Robux contributed by each tier are summed, and only the final aggregate is rounded — half-up to a whole number of Robux; per-tier rounding is forbidden because it drifts the total. When an order carries an active promotion code, a flat ten-percent bonus applies: the already-rounded tiered sum is multiplied by one and one tenth and rounded half-up again — the bonus is computed on the rounded tiered total, not on the raw pre-round value.

Refunds are constrained by solvency. A `PlatformAdmin` may refund a `COMPLETED` currency order only while the buyer's `robux_balance` still covers the order's `credited_robux`; if the buyer has already spent part of the credited Robux such that the refund would drive the balance negative, the refund is rejected with `ERR_REFUND_EXCEEDS_BALANCE`. A successful refund transitions the order to `REFUNDED` and subtracts `credited_robux` from the buyer's `robux_balance`, restoring the compensating invariant that the balance is unchanged net of the original purchase.

### 3.4. Publishing Experiences and the Moderation Pipeline

A `Creator` builds an experience by creating it with a `title` of three to sixty characters and a free-text `description`; the experience is born `DRAFT` under that creator's ownership, recorded as `creator_user_id`. When the draft is ready, the creator submits it for review — permitted only while the creator's own status is `ACTIVE` — which moves the experience to `PENDING_REVIEW` and spawns a `ModerationSubmission` whose `subject_type` is `EXPERIENCE`, whose `subject_id` is the experience, and whose `status` is `QUEUED`.

Every moderation submission — whether spawned by an experience submission, by an asset submission, or filed manually by a `Creator` or `SafetyAgent` against an `EXPERIENCE`, an `ASSET`, or a `TEXT` subject (the polymorphic `subject_id` resolving to an experience, a marketplace item, or a chat message respectively, and `submitted_by_user_id` recording the filer) — passes through the same automated gate. The classifier computes an `automated_score` between 0.0 and 1.0 and routes on asymmetric thresholds: a score of 0.85 or higher is auto-rejected to `REJECTED` with no human involvement; a score of 0.10 or lower is auto-approved to `APPROVED`; anything strictly between goes to `HUMAN_REVIEW`. The boundaries are pinned deliberately — exactly 0.85 rejects, exactly 0.10 approves. The intermediate `AUTO_REVIEWED` state is transient: the system re-dispatches immediately to one of the three outcomes. For test-driving, a `PlatformAdmin` may pin the `automated_score` of a `QUEUED` submission by supplying `submission_id` and `score` to the score-injection capability, which applies the same thresholds synchronously.

A human decision is rendered by a `Moderator` supplying a `decision` of `APPROVE`, `REJECT`, or `ESCALATE` against a submission in `HUMAN_REVIEW`. Segregation of duties forbids the reviewer from deciding their own filing: the acting `reviewer_user_id` must differ from `submitted_by_user_id`, and the decision stamps `decided_at` as the status leaves `HUMAN_REVIEW`. Approval cascades by subject type: an experience subject transitions from `PENDING_REVIEW` to `PUBLISHED` and receives its assigned rating (an `ExperienceAgeRating` row built from the submission's descriptor set (mirrored onto the experience as its `content_descriptors`), with `assigned_by` of `AUTOMATED` or `HUMAN`, and the experience's `age_rating` updated to match); an asset subject moves its marketplace item to `ON_SALE`; a text subject leaves the chat message's `was_reported` true with no further action. Rejection also cascades by subject type: an experience subject returns from `PENDING_REVIEW` to `DRAFT` so the creator can edit and resubmit, while an already-`PUBLISHED` experience whose update is rejected drops to `SUSPENDED`; an asset subject moves its item to `MODERATION_REJECTED`. Escalation moves the submission to `ESCALATED` and immediately returns it to `QUEUED` with a higher-priority flag, to be picked up by a different `Moderator` — the second `reviewer_user_id` must differ from the first, another segregation-of-duties check enforced as `ERR_SEGREGATION_OF_DUTIES`.

The rating cascade has one hard safety gate. When the assigned rating is `SEVENTEEN_PLUS` and the creator's `age_band` is `CHILD`, the publish transition is blocked outright: the experience stays `PENDING_REVIEW` and the operation is rejected with `ERR_CREATOR_AGE_INSUFFICIENT_FOR_RATING`. Each rating row carries `rating` (one of `ALL`, `NINE_PLUS`, `THIRTEEN_PLUS`, `SEVENTEEN_PLUS`), the final `descriptors` set (descriptor codes such as VIOLENCE_MILD, GAMBLING_SIMULATED, ALCOHOL_REFERENCE, which drive the rating computation), `assigned_by`, `assigned_at`, a `supersedes_id` pointing at the row it replaces (null for the first rating), and a computed `is_current` flag that is true only for the row with the maximum `assigned_at` for that experience — the row the access-control layer consults. The full rating history of an experience is listable, and the rating's `id` is addressable directly.

Once live, an experience accumulates `visit_count_lifetime` — the total count of join events — and the rolling engagement counters described in §3.8. A published experience can be suspended by a `PlatformAdmin` or `SafetyAgent` supplying a `reason` (recorded as `suspended_reason`), or automatically when its creator is suspended or when moderation rejects an update; suspension tombstones every in-flight chat message in the experience, replacing each `body_filtered` with `[removed]`, while resale listings of marketplace items associated with the experience are unaffected because they belong to a different aggregate. A suspended experience whose creator is back in `ACTIVE` status can be re-published by that creator, returning it to `PUBLISHED`. Finally, a creator may archive an experience they own from `DRAFT`, `PUBLISHED`, or `SUSPENDED`; archiving moves it to `ARCHIVED`, stamps `archived_at`, is terminal, stops snapshot accumulation, and runs a final engagement sweep that settles `engagement_payout_pending_robux` to zero by crediting the creator immediately — the pending payout is never lost to archival.

### 3.5. Appeals: Second-Look Moderation

A creator who disagrees with a rejection may file a `ModerationAppeal` against it, supplying the `submission_id` and a free-text `reason` of ten to two thousand characters. The appeal is only admissible while the target submission is `REJECTED`; filing against a submission in any other state is rejected with `ERR_SUBMISSION_NOT_REJECTED`. The appeal is born `FILED` under the filer's identity, recorded as `appellant_user_id`.

An `AppealsReviewer` starts the review, moving the appeal to `UNDER_REVIEW` — with a hard segregation rule: the appeals reviewer's `reviewer_user_id` must differ from the original submission's `reviewer_user_id`, so no one reviews their own decision. From `UNDER_REVIEW`, the reviewer decides by supplying an `outcome`. An `UPHELD` outcome leaves the original submission `REJECTED` and stamps `decided_at`. An `OVERTURNED` outcome retroactively flips the original `ModerationSubmission` to `APPROVED` and replays the approval cascade as if the submission had been approved in the first place: the experience or marketplace item transitions as it would have on original approval, and when the subject is an experience, a new `ExperienceAgeRating` row with `assigned_by` of `APPEAL_DECISION` supersedes the prior rating. The appellant may also withdraw their own appeal while it is still `FILED` — withdrawal requires `appellant_user_id` to match the acting `X-User-ID` — moving it to `WITHDRAWN`. `UPHELD`, `OVERTURNED`, and `WITHDRAWN` are all terminal.

### 3.6. Marketplace: Items, Limiteds, and Resale

A creator lists goods by creating a `MarketplaceItem` with a `title` of three to sixty characters, an `item_kind` of `HAT`, `SHIRT`, `PANTS`, `GEAR`, `LIMITED_HAT`, or `LIMITED_GEAR`, a `price_robux`, and — for the two `LIMITED_` kinds only — a `total_supply` fixing the mint count and a `royalty_pct` between 0 and 50 directing a percentage of each future resale back to the original creator. For non-limited kinds, `total_supply` must be null and `royalty_pct` must be 0; violating either structural rule is an `ERR_INVALID_REQUEST`. The item's `is_limited` flag is derived from the kind. Items are born `DRAFT`, and for limited kinds the `price_robux` is the initial sale price only — subsequent sales run through the resale pipeline.

Submitting an item moves it from `DRAFT` to `PENDING_MODERATION`, spawning a `ModerationSubmission` with `subject_type` of `ASSET` and recording it as `moderation_submission_id` on the item; only the owning creator whose status is `ACTIVE` may submit. The moderation decision then drives the item: approval moves it to `ON_SALE`, rejection to the terminal `MODERATION_REJECTED`. The creator can take an `ON_SALE` item off sale — moving it to `OFF_SALE` — and later put it back on sale, returning it from `OFF_SALE` to `ON_SALE`; taking an item off sale leaves existing active resale listings untouched (they are an independent aggregate) but blocks the creation of new listings for that item. Sales accumulate into `copies_sold`, the count of completed primary purchases, and a primary purchase that would push `copies_sold` past a limited item's `total_supply` is rejected with `ERR_LIMITED_SUPPLY_EXHAUSTED`.

Resale is gated three ways. A `Creator` lists a limited item they own by supplying the `item_id`, an `ask_price_robux`, and `expected_item_version` — the item `version` they last observed, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412) because the floor depends on the observed price. The ask must be at least one half of the item's current `price_robux`, rounded down to a whole Robux, and the boundary is inclusive: an ask equal to that floor is accepted, one Robux below it is rejected with `ERR_RESALE_FLOOR_VIOLATION`. (Concretely, an item priced at 101 Robux has a floor of 50: ask 50 passes, ask 49 fails.) The listing is born `ACTIVE` with `listed_at` stamped. Cancellation by the seller — requiring `seller_user_id` to match the acting user — moves it to `CANCELLED`.

When a resale purchase confirms, the listing transitions from `ACTIVE` to `SOLD`, but only if the seller's `account_age_days` is at least seven — the resale account-age gate — and the `expected_item_version` captured on the listing still matches the item's current `version` at the moment of sale. On sale, `sold_at` and `buyer_user_id` are stamped, item ownership transfers to the buyer, and the proceeds split by the waterfall in §3.7: the seller's `robux_balance` grows by their post-fee, post-royalty share, and the original creator's `earned_robux_lifetime` grows by the royalty share.

### 3.7. Purchases and the Marketplace Split

All spending flows through the `PurchaseOrder`. A `Creator` creates one with an `item_type` of `MARKETPLACE_ITEM`, `EXPERIENCE_GAMEPASS`, or `LIMITED_ITEM_RESALE`; an `item_id` resolving polymorphically to a marketplace item, an experience (for a gamepass), or a resale listing; the `price_robux` to charge; and an `idempotency_key`. The order is born `PENDING`; the safety and fiscal checks all fire at confirmation time, not at creation.

Confirming a purchase runs the gauntlet in the validation order of §2.5. The buyer's `robux_balance` must cover `price_robux`, else `ERR_INSUFFICIENT_ROBUX`. If the buyer has parental controls with a `monthly_spend_limit_robux` set, the sum of this purchase's `price_robux` plus every `COMPLETED` purchase's `price_robux` in the current UTC calendar month (from the first instant of the month through now) must stay strictly below the limit: reaching the limit exactly is rejected, because the comparison includes equality — a purchase that would bring the month's total to precisely the cap fails with `ERR_PARENTAL_SPEND_LIMIT`, the opposite of the usual "at the cap is fine" convention, and this strictness is deliberate. For a gamepass on an experience, the experience must be `PUBLISHED` (`ERR_EXPERIENCE_NOT_PUBLISHED` otherwise) and the buyer's `age_band` must satisfy the experience's `age_rating` per the access rules of §3.9, else `ERR_AGE_BAND_INSUFFICIENT`. For a marketplace item, the item must be `ON_SALE`, else `ERR_ITEM_NOT_ON_SALE`. For a resale, the listing must still be `ACTIVE` and its pinned item version must still match.

A confirmed order computes the money split. The platform fee is always 30% of `price_robux`, rounded half-up to a whole Robux, and recorded as `platform_fee_robux`. For a non-limited item or a gamepass, the remainder — `price_robux` minus the fee — is the `creator_credit_robux` paid to the seller. For a limited resale the split is a waterfall, and the order of operations is pinned: the platform fee comes off first, the gross seller share is what remains, the royalty is computed as the gross seller share multiplied by the item's `royalty_pct` percent and rounded half-up, the reseller's credit is the gross seller share minus the royalty, and the original creator's credit is exactly the royalty. Computing the royalty on the gross price instead of the post-fee share yields different Robux and is forbidden — the fee-first, royalty-second order is part of the contract. On completion the buyer's `robux_balance` drops by `price_robux`, the seller's `earned_robux_lifetime` rises by their credit, a resale additionally pays the original creator's royalty into that creator's lifetime earnings, `completed_at` is stamped, and a resale listing flips to `SOLD`.

Refunds and clawbacks close the loop. A `PlatformAdmin` may refund a `COMPLETED` purchase; for a resale this is permitted only while the buyer still owns the item. Refunding returns `price_robux` to the buyer's `robux_balance` and subtracts `creator_credit_robux` from the seller's `earned_robux_lifetime` — the compensating invariant is that the seller's lifetime-earned figure returns to its pre-purchase value. Separately, when a seller's account is terminated with earnings forfeited to the platform within thirty days of a purchase's `completed_at`, the system transitions that purchase to `REVERSED`: the `creator_credit_robux` is clawed back while the `platform_fee_robux` stays with the platform.

The buyer-side `robux_balance` itself is a derived ledger position: it equals the sum of `credited_robux` across completed currency purchases, minus the sum of `price_robux` debited across completed purchases, minus the seller-side debits of completed resales at their post-fee value, minus the `debited_robux` of paid DevEx requests. It may never go negative — any debit that would drive it below zero is rejected with `ERR_INSUFFICIENT_ROBUX`.

### 3.8. Engagement Payouts and the Monthly Settlement

Player attention pays creators directly. A daily engagement sweep — driven by a `PlatformAdmin` posting an `EngagementSnapshot` with a `snapshot_date` and the day's `minutes_engaged` — computes that day's `payout_robux` for the experience and adds it to the experience's `engagement_payout_pending_robux`. The payout rate depends on the experience's `age_rating`: the minutes are converted to whole hours (any partial hour discarded) and multiplied by the per-hour rate for the rating — 2 Robux per hour for `ALL`, 3 for `NINE_PLUS`, 4 for `THIRTEEN_PLUS`, and 5 for `SEVENTEEN_PLUS`. The experience's `engagement_minutes_30d` is a rolling thirty-day sum of session minutes, recomputed daily by the same sweep, and is what the dashboard reads.

The pending amount becomes real at the month boundary. The monthly settlement — run by a `PlatformAdmin` through the settlement capability — walks every `PUBLISHED` experience, credits its `engagement_payout_pending_robux` into the creator's `earned_robux_lifetime`, resets the pending counter to zero, and reports how many experiences settled and the total Robux credited. A mid-month creator-dashboard view may show a provisional estimate — whole hours of the minutes so far times the rating's rate — but that estimate commits nothing; only the settlement moves money. Recall from §3.4 that archiving an experience triggers the same settlement immediately for that experience alone, so pending payout survives archival.

### 3.9. Age Ratings and Access Control

Access to rated content is decided by comparing bands, not birthdays. Each rating demands a minimum band: `ALL` admits a `CHILD`; `NINE_PLUS` admits a `CHILD` only when the viewer is at least nine years old, and is forbidden to a younger child; `THIRTEEN_PLUS` requires `TEEN`; and `SEVENTEEN_PLUS` requires `ADULT`. Bands order as `CHILD` below `TEEN` below `ADULT`, and access is granted exactly when the viewer's band is at least the required band. The comparison is against the band ordering, never against raw age — so a seventeen-year-old, being `TEEN`, is denied a `SEVENTEEN_PLUS` experience, full stop. These checks fire on experience joins, on gamepass purchases (as the `ERR_AGE_BAND_INSUFFICIENT` gate in §3.7), and on chat reads, and a parental `allowed_age_ratings` whitelist narrows — never widens — what a child account may join.

### 3.10. Chat, Filtering, and Reports

Chat lives inside experiences. A `Creator` sends a message into an experience by supplying `body_raw`; the message records `sender_user_id` and `experience_id` and stamps `sent_at`. If the sender's parental controls set `chat_mode` to `RESTRICTED`, the send is rejected outright with `ERR_PARENTAL_CHAT_RESTRICTED` — no message is created at all. Otherwise the server computes `body_filtered` by applying the stricter of the sender's own `chat_filter_level` and the strictest viewer's level for the context, and records the level actually used as `filter_applied`. At the `SAFE` level all digits and most punctuation are stripped; at `STANDARD` a server-side lexical blocklist applies; at `ADULT` the filtered body equals `body_raw` unchanged. Experience descriptions shown to `CHILD`-band viewers pass through the same filter discipline.

Any `Creator` or `SafetyAgent` may report a message by filing a report against its `message_id` with a `reason_code` of `HARASSMENT`, `SCAM`, `INAPPROPRIATE_CONTENT`, `PERSONAL_INFO`, or `OTHER`; the report records the filer as `reporter_user_id` and filing sets the message's `was_reported` to true. The report is born `OPEN`. A `SafetyAgent` triages it to `TRIAGED`, stamping `triaged_at` and recording themselves as `triaged_by_user_id`, then either dismisses it to `DISMISSED` or actions it by supplying an `action_taken` of `WARNING`, `SUSPEND_SENDER`, or `TERMINATE_SENDER` — actioning with the value `NONE` is not a valid terminal action. Actioning moves the report to `ACTIONED`; a `WARNING` leaves the sender untouched, `SUSPEND_SENDER` cascades the message's sender into `SUSPENDED` (with the full user-suspension cascade of §3.1), and `TERMINATE_SENDER` creates an `AccountTermination` row with `reason_code` of `SAFETY_VIOLATION`, feeding the termination pipeline of §3.11.

### 3.11. Account Termination and Earnings Disposition

Termination is a two-step pipeline with mandatory segregation of duties. A `PlatformAdmin` or `SafetyAgent` initiates an `AccountTermination` by supplying the target `user_id`, a `reason_code` of `FRAUD`, `SAFETY_VIOLATION`, `LEGAL_REQUEST`, `PARENT_REQUEST`, or `SELF_REQUEST`, and an `earnings_disposition`. The initiator may not terminate their own account — `initiated_by_user_id` must differ from `user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The row is born `PENDING_DISPOSITION`. The disposition choices are constrained by the reason: `FORFEIT_TO_PLATFORM` and `DONATE_TO_CHARITY` are admissible only for `FRAUD`, `SAFETY_VIOLATION`, and `LEGAL_REQUEST`; `PAYOUT_TO_VERIFIED_USER` is admissible only for `SELF_REQUEST`; and a disposition must always be chosen — it is required whenever the reason is anything other than a plain self-request, and in practice the initiating call always carries one consistent with the reason.

A `PlatformAdmin` then executes the disposition, moving the row to `EARNINGS_DISPOSED`. At that instant the system records `disposed_robux` as the user's entire `robux_balance`, computes `disposed_usd_cents` by applying the DevEx ladder's marginal rates (§3.12) to that Robux amount, and zeroes the user's `robux_balance` — while `earned_robux_lifetime` is deliberately not reduced, preserving the historical record of what the account earned. When the disposition is `PAYOUT_TO_VERIFIED_USER`, the target user must satisfy `is_devex_eligible` at that moment, and the system creates a synthetic DevEx request in `PAID` state against them to carry the funds. Once the disposition's side effects settle, the system moves the termination to `COMPLETE`, which cascades the `User` to `TERMINATED` per §3.1 — stamping `terminated_at` and pushing every child entity to its terminal state.

### 3.12. DevEx: Converting Earnings to USD

The developer exchange is the economy's exit ramp. A `Creator` submits a `DevExchangeRequest` with a `requested_robux` amount and the mandatory `expected_user_version` described in §2.6. The amount must be at least 30,000 Robux — anything less is rejected with `ERR_DEVEX_MINIMUM_NOT_MET` — and may not exceed the user's `earned_robux_lifetime` net of the Robux already locked by other in-flight requests. Eligibility is evaluated at submission against the six clauses of §3.2, failing with `ERR_DEVEX_NOT_ELIGIBLE`. A valid submission is born `SUBMITTED` with `submitted_at` stamped and `locked_robux` equal to `requested_robux`: the funds are reserved immediately so concurrent requests cannot over-commit the same earnings.

A `FinanceOfficer` approves a `SUBMITTED` request. Approval re-derives `is_devex_eligible` at the moment of approval — not at submission — and requires it true; it also re-checks `expected_user_version` against the user's current `version`, rejecting a mismatch with `ERR_STALE_VERSION` (HTTP 412). Approval computes the money. The `usd_payout_cents` comes from the progressive DevEx ladder applied marginally to `requested_robux`: the first 30,000 Robux convert at 0.35 cents per Robux, Robux from 30,001 through 100,000 at 0.38, Robux from 100,001 through 1,000,000 at 0.40, and every Robux from 1,000,001 upward at 0.42; the bracket sums are aggregated and rounded half-up only at the end. The `withholding_tax_cents` is then computed from `usd_payout_cents` — never from the net — using brackets keyed on the user's tax `form_type`. For a `W9` filer the withholding is progressive in cents: nothing on the first 10,000 cents, ten percent on cents from 10,001 through 50,000, twenty-four percent on cents from 50,001 through 200,000, and thirty percent on every cent from 200,001 upward. For `W8BEN` and `W8BENE` filers the withholding is a flat thirty percent of the full `usd_payout_cents`, with no brackets. The withholding aggregate rounds half-up at the end, and `net_payout_cents` is `usd_payout_cents` minus `withholding_tax_cents`. The evaluation order is pinned: the ladder prices the gross Robux before any withholding exists, and the net is derived after — the withholding never feeds back into bracket selection. Approval stamps `approved_at`.

Payment is a separate act by a separate officer. A `FinanceOfficer` marks an `APPROVED` request `PAID`, but the marking officer's identifier must differ from the approving officer's — the same person cannot approve and pay, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Marking paid converts the lock into a real debit: the user's `robux_balance` drops by `requested_robux`, and `paid_at` is stamped. A `SUBMITTED` request can also die two quieter ways: a `FinanceOfficer` rejects it with a `reason`, or the owning creator cancels it (requiring `user_id` to match the acting `X-User-ID`); both paths transition to `REJECTED` or `CANCELLED` respectively and release the `locked_robux` back to the user's available earnings.

## 4. Endpoint Definitions

All resources are mounted under the `/ugc` prefix. Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Request and response payloads for each operation are governed by the workflow narratives in §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ugc/_clock/set_current_utc` | Set the platform logical clock | PlatformAdmin |
| POST | `/ugc/users` | Register a new user | Anonymous |
| GET | `/ugc/users/{id}` | Get user | Anonymous, Creator, PlatformAdmin, SafetyAgent, Moderator, AppealsReviewer, FinanceOfficer |
| GET | `/ugc/users` | List users | PlatformAdmin, SafetyAgent, Moderator, AppealsReviewer, FinanceOfficer |
| POST | `/ugc/users/{id}/suspend` | Suspend user (cascades to experiences, resale listings, devex) | PlatformAdmin, SafetyAgent |
| POST | `/ugc/users/{id}/reinstate` | Reinstate suspended user | PlatformAdmin |
| POST | `/ugc/users/{id}/parental-controls` | Create or replace parental controls for a child account | Creator |
| GET | `/ugc/users/{id}/parental-controls` | Get parental controls for a child | Creator, PlatformAdmin |
| POST | `/ugc/users/{id}/identity-verifications` | Submit identity verification | Creator |
| GET | `/ugc/users/{id}/identity-verifications` | List identity verifications for user | Creator, PlatformAdmin |
| POST | `/ugc/identity-verifications/{id}/verify` | Approve identity verification | PlatformAdmin |
| POST | `/ugc/identity-verifications/{id}/reject` | Reject identity verification | PlatformAdmin |
| POST | `/ugc/users/{id}/tax-documents` | Submit tax form | Creator |
| GET | `/ugc/users/{id}/tax-documents` | List tax documents | Creator, PlatformAdmin, FinanceOfficer |
| POST | `/ugc/tax-documents/{id}/accept` | Accept tax document | PlatformAdmin |
| POST | `/ugc/tax-documents/{id}/reject` | Reject tax document | PlatformAdmin |
| POST | `/ugc/experiences` | Create experience (DRAFT) | Creator |
| GET | `/ugc/experiences/{id}` | Get experience | Anonymous, Creator, PlatformAdmin, Moderator, SafetyAgent, AppealsReviewer, FinanceOfficer |
| GET | `/ugc/experiences` | List experiences | Anonymous, Creator, PlatformAdmin, Moderator, SafetyAgent, AppealsReviewer, FinanceOfficer |
| POST | `/ugc/experiences/{id}/submit-for-review` | Submit experience for moderation | Creator |
| POST | `/ugc/experiences/{id}/suspend` | Suspend experience | PlatformAdmin, SafetyAgent |
| POST | `/ugc/experiences/{id}/republish` | Re-publish suspended experience | Creator |
| POST | `/ugc/experiences/{id}/archive` | Archive experience (terminal) | Creator |
| GET | `/ugc/experiences/{id}/age-ratings` | List age-rating history for an experience | Anonymous, Creator, PlatformAdmin, Moderator, AppealsReviewer |
| GET | `/ugc/experiences/{id}/chat-messages` | List chat messages in an experience | Creator, PlatformAdmin, SafetyAgent, Moderator |
| POST | `/ugc/moderation-submissions` | Create moderation submission (manual report path) | Creator, SafetyAgent |
| GET | `/ugc/moderation-submissions/{id}` | Get submission | Creator, PlatformAdmin, Moderator, AppealsReviewer, SafetyAgent |
| GET | `/ugc/moderation-submissions` | List submissions | PlatformAdmin, Moderator, AppealsReviewer, SafetyAgent |
| POST | `/ugc/moderation-submissions/{id}/decide` | Human decision on a submission | Moderator |
| POST | `/ugc/_moderation/inject_score` | Test-driving: pin automated score and force dispatch | PlatformAdmin |
| POST | `/ugc/moderation-appeals` | File appeal against a REJECTED submission | Creator |
| GET | `/ugc/moderation-appeals/{id}` | Get appeal | Creator, PlatformAdmin, AppealsReviewer |
| GET | `/ugc/moderation-appeals` | List appeals | PlatformAdmin, AppealsReviewer, Moderator |
| POST | `/ugc/moderation-appeals/{id}/start-review` | Start appeals review | AppealsReviewer |
| POST | `/ugc/moderation-appeals/{id}/decide` | Decide appeal | AppealsReviewer |
| POST | `/ugc/moderation-appeals/{id}/withdraw` | Withdraw appeal | Creator |
| POST | `/ugc/currency-purchase-orders` | Create a fiat to Robux purchase | Creator |
| GET | `/ugc/currency-purchase-orders/{id}` | Get currency order | Creator, PlatformAdmin, FinanceOfficer |
| GET | `/ugc/currency-purchase-orders` | List currency purchase orders | Creator, PlatformAdmin, FinanceOfficer |
| POST | `/ugc/currency-purchase-orders/{id}/confirm-payment` | Confirm payment; credits Robux via tiered exchange | Creator |
| POST | `/ugc/currency-purchase-orders/{id}/fail-payment` | Mark payment failed | PlatformAdmin |
| POST | `/ugc/currency-purchase-orders/{id}/refund` | Refund completed currency purchase | PlatformAdmin |
| POST | `/ugc/marketplace-items` | Create marketplace item | Creator |
| GET | `/ugc/marketplace-items/{id}` | Get item | Anonymous, Creator, PlatformAdmin, Moderator, SafetyAgent, AppealsReviewer, FinanceOfficer |
| GET | `/ugc/marketplace-items` | List items | Anonymous, Creator, PlatformAdmin, Moderator, SafetyAgent, AppealsReviewer, FinanceOfficer |
| POST | `/ugc/marketplace-items/{id}/submit` | Submit item for moderation | Creator |
| POST | `/ugc/marketplace-items/{id}/take-off-sale` | Take item off sale | Creator |
| POST | `/ugc/marketplace-items/{id}/put-on-sale` | Put item back on sale | Creator |
| POST | `/ugc/resale-listings` | List a limited item for resale | Creator |
| GET | `/ugc/resale-listings/{id}` | Get listing | Anonymous, Creator, PlatformAdmin, SafetyAgent |
| GET | `/ugc/resale-listings` | List resale listings | Anonymous, Creator, PlatformAdmin, SafetyAgent |
| POST | `/ugc/resale-listings/{id}/cancel` | Cancel listing | Creator |
| POST | `/ugc/purchase-orders` | Buy a marketplace item, gamepass, or resale | Creator |
| GET | `/ugc/purchase-orders/{id}` | Get purchase order | Creator, PlatformAdmin, FinanceOfficer |
| GET | `/ugc/purchase-orders` | List purchase orders | Creator, PlatformAdmin, FinanceOfficer |
| POST | `/ugc/purchase-orders/{id}/confirm` | Confirm and settle a purchase | Creator |
| POST | `/ugc/purchase-orders/{id}/refund` | Refund a completed purchase | PlatformAdmin |
| POST | `/ugc/devex-requests` | Submit a developer exchange request | Creator |
| GET | `/ugc/devex-requests/{id}` | Get DevEx request | Creator, PlatformAdmin, FinanceOfficer |
| GET | `/ugc/devex-requests` | List DevEx requests | PlatformAdmin, FinanceOfficer |
| POST | `/ugc/devex-requests/{id}/approve` | Approve DevEx request | FinanceOfficer |
| POST | `/ugc/devex-requests/{id}/reject` | Reject DevEx request | FinanceOfficer |
| POST | `/ugc/devex-requests/{id}/mark-paid` | Mark approved request as paid (different officer than approver) | FinanceOfficer |
| POST | `/ugc/devex-requests/{id}/cancel` | Creator cancels own pending request | Creator |
| POST | `/ugc/experiences/{id}/chat-messages` | Send a chat message into an experience | Creator |
| POST | `/ugc/chat-messages/{id}/reports` | Report a chat message | Creator, SafetyAgent |
| GET | `/ugc/reports/{id}` | Get report | SafetyAgent, PlatformAdmin, Moderator |
| GET | `/ugc/reports` | List reports | SafetyAgent, PlatformAdmin, Moderator |
| POST | `/ugc/reports/{id}/triage` | Triage a report | SafetyAgent |
| POST | `/ugc/reports/{id}/action` | Take action on a triaged report | SafetyAgent |
| POST | `/ugc/reports/{id}/dismiss` | Dismiss a triaged report | SafetyAgent |
| POST | `/ugc/account-terminations` | Initiate an account termination | PlatformAdmin, SafetyAgent |
| GET | `/ugc/account-terminations/{id}` | Get termination | PlatformAdmin, SafetyAgent, FinanceOfficer |
| GET | `/ugc/account-terminations` | List account terminations | PlatformAdmin, SafetyAgent, FinanceOfficer |
| POST | `/ugc/account-terminations/{id}/dispose-earnings` | Dispose of the terminated user's earned Robux | PlatformAdmin |
| POST | `/ugc/experiences/{id}/engagement-snapshots` | Post a daily engagement snapshot | PlatformAdmin |
| GET | `/ugc/experiences/{id}/engagement-snapshots` | List snapshots | Creator, PlatformAdmin, FinanceOfficer |
| POST | `/ugc/_engagement/settle_monthly` | Test-driving: run monthly engagement settlement | PlatformAdmin |
| GET | `/ugc/experience-age-ratings/{id}` | Get a single experience age rating | Anonymous, Creator, PlatformAdmin, Moderator, AppealsReviewer |
| GET | `/ugc/experience-age-ratings` | List experience age ratings | Anonymous, Creator, PlatformAdmin, Moderator, AppealsReviewer |
| GET | `/ugc/chat-messages/{id}` | Get a single chat message | Creator, PlatformAdmin, SafetyAgent, Moderator |
| GET | `/ugc/chat-messages` | List chat messages | Creator, PlatformAdmin, SafetyAgent, Moderator |
| GET | `/ugc/audit-logs/{id}` | Get a single audit log entry | PlatformAdmin |
| GET | `/ugc/audit-logs` | List audit log entries | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_USER_NOT_FOUND` | 404 Not Found |
| `ERR_EXPERIENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_TERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AGE_BAND_INSUFFICIENT` | 403 Forbidden |
| `ERR_PARENTAL_SPEND_LIMIT` | 403 Forbidden |
| `ERR_PARENTAL_CHAT_RESTRICTED` | 403 Forbidden |
| `ERR_CREATOR_AGE_INSUFFICIENT_FOR_RATING` | 403 Forbidden |
| `ERR_RESALE_FLOOR_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LIMITED_SUPPLY_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 Conflict |
| `ERR_EXPERIENCE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_ITEM_NOT_ON_SALE` | 409 Conflict |
| `ERR_SUBMISSION_NOT_REJECTED` | 409 Conflict |
| `ERR_INSUFFICIENT_ROBUX` | 402 Payment Required |
| `ERR_DEVEX_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_DEVEX_MINIMUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REFUND_EXCEEDS_BALANCE` | 409 Conflict |
