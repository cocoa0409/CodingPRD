# Celebrity Video Marketplace API — Product Requirements Document

## 1. Introduction

Fans increasingly expect direct, personal contact with the public figures they follow, and celebrities increasingly expect a reliable way to monetize that attention without middlemen. This document specifies a marketplace API in which creators — referred to as **talent** — sell short personalized videos to individual buyers and to business customers who need content for commercial campaigns. The platform handles identity verification, pricing, content screening, fulfillment deadlines, moderation, licensing, payouts, and dispute handling end to end.

The marketplace operates under a strict financial and compliance posture. Every paid order generates auditable earnings records for the talent; commercial use of a video requires an explicit license grant priced by usage window, channels, and territory; payouts to talent are batched weekly and gated on verified tax documentation; and any video that fails content policy review is routed back to the talent before a buyer ever sees it. Both buyers and the platform itself bear clearly defined slices of every refund, so that a "bad delivery" never leaves money unaccounted for.

Timing is first-class: the platform runs on a logical clock rather than wall-clock time, so acceptance windows, delivery deadlines, auto-confirmation, licensing expiry, and payout periods are all evaluated against an operator-controlled timestamp. This document is the sole product-side contract for the implementing team.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply to every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `Talent`, `Buyer`, `Moderator`, and `PlatformAdmin`. A request arriving with missing or malformed headers — or with a role string outside that set — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint per the authorization matrix in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity is bound to entities differently depending on the role. When `X-User-Role` is `Talent`, `X-User-ID` is the `id` of the acting `Talent` record; ownership checks on any resource that references a talent (for example, an order's `talent_id`) compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer` record; ownership checks on any resource that references a buyer (for example, an order's `buyer_id`) compare that foreign-key field to `X-User-ID` under the same rejection rule. When `X-User-Role` is `Moderator` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Admin-scoped actions (activation, suspension, tax review, dispute resolution, sweeps, payout lifecycle, logical-clock control, forced pricing-suggestion refresh) are reserved for `PlatformAdmin`; video moderation may additionally be performed by a `Moderator`.

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

List endpoints accept two pagination query parameters. `limit` specifies the maximum number of items to return; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Transitions

The marketplace does not consult wall-clock time. All temporal reasoning — acceptance windows, delivery deadlines, auto-confirmation, license expiry, identity auto-rejection, payout windows, trailing-window aggregations — is evaluated against a server-maintained **logical clock**. Before any operator sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it must never fall back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the clock is monotonic, and an attempt to move it backward is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Three operator-run checkpoints consume the logical clock. The **deadline sweep** accepts a `to_iso8601` instant and, treating that instant as "now", drives every time-based automatic transition up to it: acceptance-window expiry, delivery-deadline cancellation, auto-confirmation of delivered orders, and license expiry. The **verification sweep** auto-rejects stale identity submissions (see §3.1). The **payout sweep** batches unsettled earnings into payout runs (see §3.7). Each sweep reports counts of the entities it touched; the deadline sweep reports `expired_count`, `cancelled_count`, `auto_confirmed_count`, and `licenses_expired_count`, and the verification sweep reports `auto_rejected_count`.

### 2.5. Common Resource Properties

Every primary resource — Talent, Buyer, Order, Video, ReRecordRequest, LicenseGrant, PayoutLine, Payout, TaxDocument, Dispute — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Any state transition, balance recompute, or cascade described in §3 that mutates a resource also updates that resource's `updated_at` and increments its `version` by 1.

### 2.6. Monetary Values and Precision

All monetary amounts in the system are integer cents — never floats, never decimal strings. Rates, fees, refunds, balances, and payout totals are all expressed as whole-cent integers. Where a calculation produces a fractional intermediate value (commission computation, licensing fee computation, partial-refund splits, pricing suggestions), the final amount is rounded to the nearest whole cent using **round half up**: a remainder of exactly half a cent rounds upward. Percentages and multipliers used internally (commission rates, channel factors, territory multipliers, scoring weights) are applied exactly as specified in §3; intermediate scores are not rounded until the final scaling step that produces a cent amount.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and each names its guard field explicitly. Opening a dispute on an order requires the request to carry `expected_order_version` holding the buyer's last-observed `version` of that order. If the order's current `version` no longer matches — for example because the video snapshot or the auto-confirm clock has advanced since the buyer last read the order — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Setting or changing a talent's rates requires the request to carry `expected_talent_version` holding the caller's last-observed `version` of the talent record; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so a rate write never silently overwrites a tier recompute or a suggestion refresh that landed in between. Endpoints not listed here do not accept a version field.

### 2.8. Validation Order and Nested Resource Retrieval

Every request passes through a single ordered validation pipeline, and failures surface in that order. First, authentication headers are checked (`ERR_UNAUTHENTICATED`). Second, role permission is checked (`ERR_UNAUTHORIZED`). Third, every identifier referenced in the request path is validated for existence in strict left-to-right order — the talent before the order, the order before the child resource — and the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404). Fourth, request-body shape is validated: required fields present, enum values within their declared sets, datetimes in ISO 8601, integers within declared ranges; violations yield `ERR_INVALID_REQUEST` (HTTP 400). Fifth, the target resource's current state is checked against the transition being attempted (`ERR_INVALID_STATE`, HTTP 409). Sixth, on the two OCC-guarded writes, the expected-version check runs (`ERR_STALE_VERSION`). Only then do business rules — content policy, moderation gates, ownership, temporal windows, uniqueness, rate bounds, fiscal gates — execute, each surfacing its own error code as described in §3. Because earlier checks mask later ones, a request that fails both authentication and a business rule always reports the authentication failure.

### 2.9. Wallet Refunds and Balance Conservation

The buyer's `wallet_credit_cents` is the single destination for every refund issued by the platform: screening declines, talent declines, acceptance expiries, delivery-deadline cancellations, suspension cascades, and dispute resolutions all credit the buyer's wallet rather than any external instrument. The wallet only grows through refunds; it starts at zero.

On the talent side, two balances are maintained and their sum is conserved across the payout lifecycle. `pending_balance_cents` accumulates unsettled net earnings (video earnings and license fee credits) and is debited by clawbacks and by payout completion; `paid_out_balance_cents` accumulates lifetime net earnings actually transferred via paid payouts. When a payout completes, the amount that leaves `pending_balance_cents` is exactly the amount that enters `paid_out_balance_cents`. Clawbacks are never allowed to drive `pending_balance_cents` negative; a resolution that would do so is rejected with `ERR_PENDING_BALANCE_INSUFFICIENT` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Talent Onboarding: Registration, Identity, Tax Documentation, and Activation

A creator joins the marketplace by registering a talent account with a `stage_name`, a `legal_name`, an `email`, and an `identity_document_ref`. The `stage_name` is the public display name and must be between 1 and 80 characters, unique across all talent records case-insensitively; the `email` is likewise unique across talent records case-insensitively. A registration that collides with an existing `stage_name` or `email` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409). The `legal_name` is used for tax documentation and payout payee records. A newly registered talent begins in `PENDING_VERIFICATION` status with `availability` set to `BOOKABLE`, all balances at zero, and `commission_tier` at `STANDARD`.

Identity verification is self-serve at the point of submission: a talent acting on its own record submits an `identity_document_ref`, which moves the talent from `PENDING_VERIFICATION` to `ID_VERIFIED` and stamps `identity_submitted_at` with the current logical time. The submission requires the acting user's `X-User-ID` to equal the talent's own `id`; acting on someone else's record is rejected with `ERR_NOT_RESOURCE_OWNER`. A talent whose submission grows stale without an admin decision is caught by the verification sweep: when the logical timestamp supplied to that sweep is at least 72 hours past the talent's `identity_submitted_at` while the talent is still in `PENDING_VERIFICATION`, the submission is auto-rejected — `identity_document_ref` and `identity_submitted_at` are cleared, the talent remains in `PENDING_VERIFICATION`, and the talent may resubmit afterward. A `PlatformAdmin` may also reject a submitted identity explicitly, moving an `ID_VERIFIED` talent back to `PENDING_VERIFICATION` and clearing the same two identity fields.

Tax documentation runs in parallel. A talent submits a `TaxDocument` by supplying a `doc_type` — either `W9` for US persons or `W8BEN` for non-US persons — together with `tax_id_last4`, which must be exactly four alphanumeric characters. Each submission is stamped with `submitted_at` at the current logical time and begins in `SUBMITTED` status. A `PlatformAdmin` reviews the document with a `decision` of `VERIFY` or `REJECT`, moving it to `VERIFIED` or `REJECTED` respectively. A rejected document is immutable, but the talent may simply submit a new one; a talent's document history is readable as a list filterable by `status`.

Activation is the admin's gate. Moving a talent from `ID_VERIFIED` to `ACTIVE` requires three things to hold simultaneously: the talent must currently be `ID_VERIFIED`; the talent must hold at least one `VERIFIED` tax document; and all three rates — `personal_rate_cents`, `business_rate_cents`, and `advertising_rate_cents` — must be set and must satisfy the rate floors and ordering described in §3.2. An activation attempted while the rate set is incomplete or out of bounds is rejected with `ERR_RATE_OUT_OF_BOUNDS` (HTTP 422); an activation attempted from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Rates, Availability, and Demand-Based Pricing

Once onboard, a talent controls three price points and one delivery commitment. `personal_rate_cents` prices `PERSONAL` requests, `business_rate_cents` prices `BUSINESS_USE` requests, and `advertising_rate_cents` prices `ADVERTISING_USE` requests. `turnaround_hours` is the talent's committed delivery turnaround, between 1 and 336 hours — at most two weeks — and it directly drives the delivery deadline on every accepted order. Rate writes are OCC-guarded: the request must carry `expected_talent_version` matching the talent's current `version`, or the write is refused with `ERR_STALE_VERSION` as described in §2.7.

The rate schedule obeys floors and a fixed ordering. The personal rate must be at least 100 cents and at most 10000000 cents. The business rate must be at least four times the personal-rate floor — that is, at least 400 cents — and at least the personal rate itself. The advertising rate must be at least eight times the personal-rate floor — at least 800 cents — and at least the business rate. Any violation is rejected with `ERR_RATE_OUT_OF_BOUNDS`. When a demand-based pricing suggestion exists for the talent, an additional bound applies: the personal rate may only be set within a band running from half of the suggested rate rounded down to twice the suggested rate rounded up.

The suggestion itself is computed from the talent's recent book of business. Demand is the number of the talent's orders that reached `CONFIRMED` within the trailing 30 days — the half-open window beginning 30 days before the current logical time and ending at it. Utilization is the number of the talent's orders currently open in `ACCEPTED` or `RE_RECORD_REQUESTED`. Each signal saturates: demand is divided by 20 and capped at 1.0, and utilization is divided by 5 and capped at 1.0. The composite score weighs demand at 0.6 and utilization at 0.4. The raw suggestion scales the talent's current `personal_rate_cents` by one plus half the score, and the published `suggested_personal_rate_cents` is that raw value rounded to the nearest 500 cents, half-up. The suggestion is stamped with `suggestion_seed_at` at the logical time it was computed, and it remains null until the first computation. Reading the suggestion returns the persisted value and recomputes it only when the stored `suggestion_seed_at` is more than 24 hours stale relative to the logical clock; a fresh read has no side effects. A `PlatformAdmin` may force a refresh at any time.

Availability is a separate axis from lifecycle status. An `ACTIVE` talent may pause itself, moving to `PAUSED` and flipping `availability` to `PAUSED_AVAILABILITY`; pausing increments `availability_pause_count_30d`, the count of pauses started within the trailing 30 days. A pause that would be the fourth within that window is rejected with `ERR_PAUSE_RATE_LIMIT` (HTTP 429) — the third pause is the last one allowed. A paused talent may resume, returning to `ACTIVE` with `availability` restored to `BOOKABLE`. In-flight orders are unaffected by pausing; the pause only closes the talent to new bookings.

Suspension is the admin's terminal lever and triggers the marketplace's widest cascade. When a `PlatformAdmin` suspends a talent in `ACTIVE` or `PAUSED`, every one of that talent's orders still in `AWAITING_ACCEPTANCE` transitions to `EXPIRED` with a full refund of its gross amount to the buyer's wallet; every order in `ACCEPTED` or `RE_RECORD_REQUESTED` transitions to `CANCELLED`, again with a full wallet refund, and any `OPEN` re-record request on those orders transitions to `CLOSED`. The talent's `pending_balance_cents` is recomputed but is unchanged by these refunds, because only confirmed orders ever contributed to it. `SUSPENDED` is terminal.

### 3.3. Booking an Order: Intake, Screening, and Acceptance

A buyer places a request by naming the `talent_id` being booked and the `buyer_id` placing it, choosing a `use_type` of `PERSONAL`, `BUSINESS_USE`, or `ADVERTISING_USE`, and supplying an `occasion`, `script_instructions` of 1 to 2000 characters, and a `recipient_name`. Two gates guard creation. First, the talent must be bookable — `ACTIVE` in status with `availability` equal to `BOOKABLE` — otherwise the request is rejected with `ERR_TALENT_NOT_BOOKABLE` (HTTP 409). Second, commercial requests require a commercial account: `BUSINESS_USE` and `ADVERTISING_USE` orders may only be placed by a buyer whose `is_business_account` flag is true, otherwise the request is rejected with `ERR_BUSINESS_ACCOUNT_REQUIRED` (HTTP 403). Buyers register with an `email` — unique across buyer records case-insensitively, with collisions rejected as `ERR_DUPLICATE_UNIQUE_FIELD` — a `display_name` shown to talent, and an optional `is_business_account` defaulting to false; new buyers start `ACTIVE` with `wallet_credit_cents` at zero. A buyer whose status has become `BLOCKED` cannot place new requests, though it may continue to act on its existing orders.

Creation freezes the price: `gross_amount_cents` is captured from the talent's rate for the chosen `use_type` at the moment of creation — the personal rate for `PERSONAL`, the business rate for `BUSINESS_USE`, the advertising rate for `ADVERTISING_USE` — and never moves afterward, even if the talent changes its rates mid-flight. The order enters `SCREENING`, and the server runs content policy screening over the request text. The screening rule is deterministic: when `script_instructions` contains the marker substring `FLAGGED_POLICY_VIOLATION`, the server raises a `POLICY_VIOLATION` flag; otherwise `screening_flags` is the empty array. The server also mints an opaque `screening_token` on the order.

To leave screening, the buyer echoes the `screening_token` back as an attestation that the screening result is clear. The attestation is only meaningful on a clean order: if `screening_flags` is non-empty, the attestation is rejected with `ERR_CONTENT_POLICY_FLAGGED` (HTTP 422), and a token that does not match the order's stored token is rejected as an invalid request. A successful attestation moves the order from `SCREENING` to `AWAITING_ACCEPTANCE` and sets `acceptance_deadline` to the current logical time plus 48 hours. Alternatively, the buyer may decline during screening, moving the order to `DECLINED` with `refund_amount_cents` set to the full gross amount and the same amount credited to the buyer's wallet.

Acceptance belongs to the talent. Accepting moves the order from `AWAITING_ACCEPTANCE` to `ACCEPTED`, requires the acting user to be the booked talent and the talent to currently be `ACTIVE`, and requires the current logical time to be strictly before `acceptance_deadline`; an acceptance at or after the deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409). Acceptance sets `delivery_deadline` to the current logical time plus the talent's `turnaround_hours`. The talent may instead decline, which moves the order to `DECLINED` with a full wallet refund, exactly as a screening decline does. If neither happens before the deadline, the deadline sweep expires the order: an order still in `AWAITING_ACCEPTANCE` when the sweep's `to_iso8601` reaches its `acceptance_deadline` transitions to `EXPIRED` with a full wallet refund.

### 3.4. Delivery, Moderation, and Re-Recording

Fulfilment is a video upload against the order. The talent supplies a `content_url` and a `duration_seconds` between 5 and 600 seconds. Uploading is permitted from either `ACCEPTED` or `RE_RECORD_REQUESTED`, but only while the current logical time is strictly before `delivery_deadline`; an upload at or after the deadline is rejected with `ERR_DELIVERY_DEADLINE_PASSED` (HTTP 409). Each upload creates a new `Video` whose `moderation_status` begins at `PENDING_REVIEW`, stamped with a monotonic per-order `version_no` — 1 for the first delivery and one higher than the previous video on each subsequent delivery. The upload also moves the order to `DELIVERED`, stamps `delivered_at`, sets (or resets) `auto_confirm_at` to the current logical time plus 72 hours, and closes any `OPEN` re-record request on the order. An order's videos are listable as a sub-resource of the order.

Missed delivery is the sweep's job: when the deadline sweep's `to_iso8601` reaches the `delivery_deadline` of an order still in `ACCEPTED` or `RE_RECORD_REQUESTED`, the order transitions to `CANCELLED` with a full wallet refund; for the re-record case, the open re-record request closes with it.

Moderation runs on every upload before the buyer can act on it. A `PlatformAdmin` or `Moderator` reviews a `PENDING_REVIEW` video with a `decision` of `CLEAR` or `FLAG`. Clearing moves the video to `CLEARED`. Flagging requires a `flagged_reason` and moves the video to `FLAGGED`; when the flagged video's order is currently `DELIVERED`, the flag forks the order back into a re-record loop — the order transitions to `RE_RECORD_REQUESTED`, an `OPEN` re-record request is created whose `notes` are the `flagged_reason`, and the order's `re_record_count` is incremented. This moderation-driven increment does not count against the buyer's own request budget beyond the increment itself: it never triggers the buyer-facing cap rejection described below. The moderation gate is enforced on every buyer-facing consumption of a video — confirmation, buyer-initiated re-record requests, and license creation all require the latest video on the order to be `CLEARED`, and any of the three attempted against an uncleared latest video is rejected with `ERR_VIDEO_NOT_CLEARED` (HTTP 409).

A buyer who is unsatisfied with a cleared delivery may request a re-record while the order is `DELIVERED`, supplying `notes` of 1 to 1000 characters describing what should change. The request requires the logical time to be strictly before `auto_confirm_at` (otherwise `ERR_BUYER_WINDOW_CLOSED`, HTTP 409), requires that no dispute is open on the order, and requires `re_record_count` to be below the hard cap of 2 — a third buyer-initiated request is rejected with `ERR_RERECORD_LIMIT_REACHED` (HTTP 409). A successful request creates a `ReRecordRequest` in `OPEN` status, increments `re_record_count`, and moves the order from `DELIVERED` to `RE_RECORD_REQUESTED`; the original `delivery_deadline` is not extended. The request closes automatically when the talent's next delivery lands, or when the order reaches a terminal state.

### 3.5. Confirmation, Commission, and Commission Tiers

Confirmation is the moment money starts moving. A buyer confirms a `DELIVERED` order while the logical time is strictly before `auto_confirm_at` — later attempts are rejected with `ERR_BUYER_WINDOW_CLOSED` — with no open dispute on the order and with the latest video `CLEARED`. If the buyer simply waits, the deadline sweep auto-confirms on the same preconditions: a `DELIVERED` order whose `auto_confirm_at` has been reached, whose latest video is `CLEARED`, and with no open dispute transitions to `CONFIRMED` identically to a manual confirmation. Confirmation is also reachable from dispute resolution, as described in §3.6.

The `CONFIRMED` transition runs payout computation once, freezing the split at that instant. The commission rate is read from the talent's `commission_tier` at the exact moment of the transition: a `STANDARD` talent pays 25% commission, `SILVER` pays 20%, and `GOLD` pays 15%. The commission is the order's `gross_amount_cents` multiplied by that rate, rounded half-up to whole cents, and is recorded as `platform_commission_cents`; the remainder is recorded as `talent_net_cents`. Tier changes that happen after confirmation never retroactively alter a confirmed order. Confirmation then creates a `PayoutLine` of kind `VIDEO_EARNING` carrying the `talent_id` and `order_id` from the order, a positive `amount_cents` equal to `talent_net_cents`, and `settlement_status` `UNSETTLED`, and credits the talent's `pending_balance_cents` by the same amount.

Confirmation also feeds the talent's tier. The order's `gross_amount_cents` is added to the talent's `trailing_gmv_cents`, which is the sum of gross amounts over the talent's orders whose `CONFIRMED` transition occurred within the trailing 365-day window — inclusive of the window start, exclusive of the window end — minus gross amounts refunded by full-refund dispute resolutions and minus buyer-refund amounts from partial-refund resolutions. Platform-absorbed refunds do not subtract. The window rolls with the logical clock, so old confirmations age out as time advances and a tier can drop without any refund at all. The tier is recomputed immediately on every change to `trailing_gmv_cents`: at least 2000000 cents of trailing GMV yields `GOLD`, at least 500000 cents yields `SILVER`, and anything below yields `STANDARD`; both thresholds are inclusive.

While an order is still `DELIVERED`, reading the order returns a provisional commission preview: an estimate computed from the talent's `commission_tier` at read time, using the same rate table. The preview is not persisted and may differ from the final `platform_commission_cents` if the tier changes before confirmation.

### 3.6. Disputes and Refund Resolution

When a delivered video does not match the request, the buyer opens a dispute with a `reason` of 1 to 1000 characters. From `DELIVERED`, the open requires the logical time to be strictly before `auto_confirm_at`; from `CONFIRMED` a dispute may still be opened — video mismatch remains actionable after confirmation — and no buyer-window deadline applies there. Either way the order transitions to `REFUND_PENDING`, and the request is OCC-guarded by `expected_order_version` as described in §2.7. An order may have at most one dispute ever; a second attempt is rejected with `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409). An order's disputes are listable as a sub-resource, returning zero or one element.

Resolution belongs to `PlatformAdmin`, who supplies an `outcome` and optional `resolution_notes`. Four outcomes exist, and they differ in exactly who bears the refund. All four require the dispute to be `OPEN` and the order to be `REFUND_PENDING`.

Under `FULL_REFUND`, the dispute resolves to `RESOLVED_REFUND` with `refund_to_buyer_cents` set to the order's full gross amount. The order transitions to `REFUNDED` with `refund_amount_cents` equal to the gross, the buyer's wallet is credited in full, and the talent's share is clawed back: a `PayoutLine` of kind `CLAWBACK` is created with `amount_cents` equal to the negative of the order's `talent_net_cents`, the order's `clawback_cents` records the clawed amount, and the talent's `pending_balance_cents` is debited by the same. The order's gross is subtracted from `trailing_gmv_cents` and the tier is recomputed.

Under `PARTIAL_REFUND`, the dispute resolves to `RESOLVED_PARTIAL` with the refund split computed on the order's gross: the buyer receives the gross multiplied by one half, rounded half-up — so for an odd gross the buyer receives the larger half — and the talent retains the remainder. The platform's commission is not clawed back on a partial. The order transitions to `REFUNDED` with `refund_amount_cents` equal to the buyer's half; the buyer's wallet is credited by that amount; a `CLAWBACK` payout line of negative that amount is created and the talent's pending balance is debited by it; and the buyer-refund amount — not the full gross — is subtracted from `trailing_gmv_cents` before the tier recompute.

Under `NO_REFUND`, the dispute resolves to `RESOLVED_NO_REFUND` with `refund_to_buyer_cents` zero. The order returns from `REFUND_PENDING` to `CONFIRMED`, and payout computation runs exactly as on a normal confirmation — the `VIDEO_EARNING` line, the pending-balance credit, and the GMV-and-tier recompute all happen at this point, keyed to the tier in force at resolution.

Under `BUYER_MISMATCH_PLATFORM_ABSORB`, the dispute resolves to `RESOLVED_BUYER_MISMATCH`: the buyer is still made whole with a full-gross wallet credit, but the platform absorbs the cost. The order transitions to `REFUNDED` with `refund_amount_cents` equal to the gross, `platform_absorbed_cents` equal to the gross, and `clawback_cents` zero. No `CLAWBACK` line is created, the talent's `pending_balance_cents` is untouched, and `trailing_gmv_cents` is unchanged — the sale still counts toward the talent's tier.

For both refund-bearing clawback outcomes — `FULL_REFUND` and `PARTIAL_REFUND` — solvency is checked before anything is written: if the talent's `pending_balance_cents` is below the clawback amount, the resolution is rejected outright with `ERR_PENDING_BALANCE_INSUFFICIENT` and nothing mutates.

### 3.7. Licensing Commercial Usage

Commercial use of a delivered video beyond the initial request requires an explicit license grant, created by the buyer against a `CONFIRMED` order whose latest video is `CLEARED`. The grant carries a `license_type` of `BUSINESS` or `ADVERTISING`, a `territory` of `DOMESTIC` or `GLOBAL`, a non-empty `channels` list drawn from `SOCIAL`, `WEB`, `TV`, and `OOH`, and a usage window from `starts_at` (inclusive) to `ends_at` (exclusive). Compatibility is enforced between the license type and the order's `use_type`: a `BUSINESS` license requires the order to be `BUSINESS_USE` or `ADVERTISING_USE`, and an `ADVERTISING` license requires `ADVERTISING_USE`; violations are rejected with `ERR_LICENSE_TYPE_INCOMPATIBLE` (HTTP 422).

The window must be well-formed and non-overlapping. A window whose `starts_at` is not strictly before `ends_at` — zero-length or inverted — is rejected with `ERR_INVALID_LICENSE_WINDOW` (HTTP 422). Overlap is checked per license type on the same order: a new `BUSINESS` grant must not overlap, under half-open interval intersection, any `ACTIVE` `BUSINESS` grant on that order, and likewise for `ADVERTISING`; cross-type overlaps are allowed. A violating overlap is rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409). Grants expire through the deadline sweep: an `ACTIVE` grant whose `ends_at` is at or before the sweep's `to_iso8601` flips to `EXPIRED` and no longer participates in overlap checks.

The licensing fee is computed at creation. The usage duration in days is the window length rounded up to whole days, with a minimum of one day. The base fee depends on the license type: 50000 cents for `BUSINESS` and 150000 cents for `ADVERTISING`. The base is multiplied by the sum of per-channel factors — 1.0 for `SOCIAL`, 1.2 for `WEB`, 2.0 for `TV`, 1.5 for `OOH` — and by a territory multiplier of 1.0 for `DOMESTIC` and 1.5 for `GLOBAL`. The duration applies with a marginal tier discount: windows of at most 90 days are charged at the full day count; windows strictly longer than 90 days are charged as 90 full-rate days plus the days beyond 90 at nine tenths of the rate. The resulting raw fee is rounded half-up to whole cents and stored as `fee_cents`. The discount is strictly marginal — a whole-window discount on long windows is explicitly not used.

License fees flow entirely to the talent. Creating the grant also creates a `PayoutLine` of kind `LICENSE_FEE_CREDIT` in `UNSETTLED` status for the full `fee_cents`, and credits the talent's `pending_balance_cents` by the same amount. An order's grants are listable, filterable by `license_type` and `status`.

### 3.8. Payouts: Weekly Sweep, Initiation, and Completion

Earnings settle through a weekly batch. The payout sweep takes a `period_start` and `period_end` defining the sweep window and considers every talent whose status is `ACTIVE` or `PAUSED`, processing them in ascending order of the talent's own `created_at`. For each such talent, the sweep collects that talent's `UNSETTLED` payout lines whose `created_at` is strictly before `period_end` and sums their signed amounts — earnings positive, clawbacks negative. When a talent's net total is at least 2500 cents, the sweep creates a `Payout` in `SCHEDULED` status carrying that `total_cents` and the window's `period_start` and `period_end`, and attaches every swept line to it by setting each line's `payout_id`; each line's `kind` distinguishes a `VIDEO_EARNING` from a `LICENSE_FEE_CREDIT` and a `CLAWBACK` within the sum. Talents whose swept total falls below the 2500-cent minimum are skipped entirely — no payout is created for them. If the sweep as a whole yields no qualifying talent at all, it is rejected with `ERR_PAYOUT_BELOW_MINIMUM` (HTTP 422); when at least one talent qualifies, the sweep succeeds and returns the created payouts as a paginated list.

A scheduled payout cannot move until tax compliance is proven: initiation — which moves the payout from `SCHEDULED` to `PROCESSING` — requires the payout's talent to hold at least one `VERIFIED` tax document, and is otherwise rejected with `ERR_TAX_DOC_MISSING` (HTTP 422). Completion moves a `PROCESSING` payout to `PAID`, stamps `paid_at` with the current logical time, transitions every attached payout line from `UNSETTLED` to `SETTLED`, and performs the conserved balance shift: the talent's `pending_balance_cents` is debited by `total_cents` and `paid_out_balance_cents` is credited by exactly the same amount, so the sum of the two balances is invariant across the transition.

Payouts and their lines are inspectable from several angles. A talent's payouts are listable and filterable by `status`; a single payout is fetchable, as are the lines swept into it. A talent's payout lines are listable and filterable by `settlement_status`, and a `PlatformAdmin` may list payout lines across the marketplace filtered by `payout_id`, `order_id`, `talent_id`, or `settlement_status`. A single payout line is fetchable by its `id`.

## 4. Endpoint Definitions

Operations that create a new resource — a talent account, a buyer account, an order, a video upload, a tax document, a dispute, a license grant — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints are mounted under the `/marketplace` prefix. Request and response shapes for each endpoint are defined by the workflows in §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marketplace/talents` | Register a new talent account (starts in `PENDING_VERIFICATION`) | Talent |
| GET | `/marketplace/talents` | List talents, filterable by `status` and `availability` | Talent, Buyer, PlatformAdmin, Moderator |
| GET | `/marketplace/talents/{id}` | Fetch a talent by id | Talent, Buyer, PlatformAdmin, Moderator |
| POST | `/marketplace/talents/{id}/identity/submit` | Talent submits identity document (`PENDING_VERIFICATION` → `ID_VERIFIED`) | Talent |
| POST | `/marketplace/talents/{id}/rates` | Set or change talent rates and turnaround (OCC-guarded) | Talent |
| POST | `/marketplace/talents/{id}/pause` | Talent pauses availability (`ACTIVE` → `PAUSED`) | Talent |
| POST | `/marketplace/talents/{id}/resume` | Talent resumes availability (`PAUSED` → `ACTIVE`) | Talent |
| GET | `/marketplace/talents/{id}/pricing-suggestion` | Return the persisted pricing suggestion; recompute only when more than 24h stale | Talent, PlatformAdmin |
| POST | `/marketplace/talents/{id}/tax-documents` | Talent submits a tax document | Talent |
| GET | `/marketplace/talents/{id}/tax-documents` | List a talent's tax documents, filterable by `status` | Talent, PlatformAdmin |
| GET | `/marketplace/talents/{id}/payouts` | List a talent's payouts, filterable by `status` | Talent, PlatformAdmin |
| GET | `/marketplace/talents/{id}/payout-lines` | List a talent's payout lines, filterable by `settlement_status` | Talent, PlatformAdmin |
| POST | `/marketplace/buyers` | Register a buyer account | Buyer |
| GET | `/marketplace/buyers/{id}` | Fetch a buyer by id | Buyer, PlatformAdmin |
| GET | `/marketplace/buyers` | List buyers, filterable by `status` | PlatformAdmin |
| POST | `/marketplace/orders` | Buyer creates a video request; screening runs and gross is frozen | Buyer |
| GET | `/marketplace/orders` | List orders, filterable by `talent_id`, `buyer_id`, `status` | Buyer, Talent, PlatformAdmin, Moderator |
| GET | `/marketplace/orders/{id}` | Fetch an order; includes provisional commission preview while `DELIVERED` | Buyer, Talent, PlatformAdmin, Moderator |
| POST | `/marketplace/orders/{id}/screening-attest` | Buyer attests a clear screening result (`SCREENING` → `AWAITING_ACCEPTANCE`) | Buyer |
| POST | `/marketplace/orders/{id}/screening-decline` | Buyer declines during screening (`SCREENING` → `DECLINED`, wallet refund) | Buyer |
| POST | `/marketplace/orders/{id}/accept` | Talent accepts the request (`AWAITING_ACCEPTANCE` → `ACCEPTED`) | Talent |
| POST | `/marketplace/orders/{id}/decline` | Talent declines the request (`AWAITING_ACCEPTANCE` → `DECLINED`, wallet refund) | Talent |
| POST | `/marketplace/orders/{id}/videos` | Talent uploads a video; order moves to `DELIVERED` | Talent |
| GET | `/marketplace/orders/{id}/videos` | List videos for an order | Buyer, Talent, PlatformAdmin, Moderator |
| POST | `/marketplace/orders/{id}/re-record-requests` | Buyer requests a re-record (`DELIVERED` → `RE_RECORD_REQUESTED`) | Buyer |
| GET | `/marketplace/orders/{id}/re-record-requests` | List re-record requests for an order | Buyer, Talent, PlatformAdmin |
| POST | `/marketplace/orders/{id}/confirm` | Buyer confirms delivery (`DELIVERED` → `CONFIRMED`, payout computation runs) | Buyer |
| POST | `/marketplace/orders/{id}/disputes` | Buyer opens a dispute (order → `REFUND_PENDING`; OCC-guarded) | Buyer |
| GET | `/marketplace/orders/{id}/disputes` | List disputes for an order (zero or one element) | Buyer, Talent, PlatformAdmin |
| POST | `/marketplace/orders/{id}/license-grants` | Create a license grant for a `CONFIRMED` order; fee computed and credited to talent | Buyer |
| GET | `/marketplace/orders/{id}/license-grants` | List license grants for an order, filterable by `license_type` and `status` | Buyer, Talent, PlatformAdmin |
| GET | `/marketplace/payouts/{id}` | Fetch a payout | Talent, PlatformAdmin |
| GET | `/marketplace/payouts/{id}/payout-lines` | List the payout lines swept into a payout | Talent, PlatformAdmin |
| GET | `/marketplace/payout-lines/{id}` | Fetch a single payout line by id | Talent, PlatformAdmin |
| GET | `/marketplace/payout-lines` | List payout lines filtered by `payout_id`, `order_id`, `talent_id`, `settlement_status` | PlatformAdmin |
| POST | `/marketplace/admin/talents/{id}/activate` | Activate an `ID_VERIFIED` talent (requires verified tax doc and valid rates) | PlatformAdmin |
| POST | `/marketplace/admin/talents/{id}/reject-identity` | Reject a submitted identity (`ID_VERIFIED` → `PENDING_VERIFICATION`) | PlatformAdmin |
| POST | `/marketplace/admin/talents/{id}/suspend` | Suspend a talent; cascades refunds on in-flight orders | PlatformAdmin |
| POST | `/marketplace/admin/talents/{id}/pricing-suggestion` | Force a pricing-suggestion refresh for a talent | PlatformAdmin |
| POST | `/marketplace/admin/videos/{id}/moderate` | Clear or flag an uploaded video | PlatformAdmin, Moderator |
| POST | `/marketplace/admin/tax-documents/{id}/review` | Verify or reject a submitted tax document | PlatformAdmin |
| POST | `/marketplace/admin/disputes/{id}/resolve` | Resolve an open dispute (`FULL_REFUND` / `PARTIAL_REFUND` / `NO_REFUND` / `BUYER_MISMATCH_PLATFORM_ABSORB`) | PlatformAdmin |
| POST | `/marketplace/admin/deadline-sweep` | Advance all time-based transitions (expiry, cancellation, auto-confirm, license expiry) up to `to_iso8601` | PlatformAdmin |
| POST | `/marketplace/admin/verification-sweep` | Auto-reject identity submissions older than 72 hours at `to_iso8601` | PlatformAdmin |
| POST | `/marketplace/admin/payout-sweep` | Weekly payout batch; creates `SCHEDULED` payouts for qualifying talents | PlatformAdmin |
| POST | `/marketplace/admin/payouts/{id}/initiate` | Start processing a `SCHEDULED` payout (requires verified tax doc) | PlatformAdmin |
| POST | `/marketplace/admin/payouts/{id}/complete` | Complete a `PROCESSING` payout; lines settle, balances shift | PlatformAdmin |
| POST | `/marketplace/_clock/set_current_utc` | Set the server's logical clock (monotonic) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONTENT_POLICY_FLAGGED` | 422 |
| `ERR_VIDEO_NOT_CLEARED` | 409 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_ACCEPTANCE_WINDOW_CLOSED` | 409 |
| `ERR_DELIVERY_DEADLINE_PASSED` | 409 |
| `ERR_BUYER_WINDOW_CLOSED` | 409 |
| `ERR_INVALID_LICENSE_WINDOW` | 422 |
| `ERR_LICENSE_WINDOW_OVERLAP` | 409 |
| `ERR_TALENT_NOT_BOOKABLE` | 409 |
| `ERR_BUSINESS_ACCOUNT_REQUIRED` | 403 |
| `ERR_LICENSE_TYPE_INCOMPATIBLE` | 422 |
| `ERR_RERECORD_LIMIT_REACHED` | 409 |
| `ERR_DISPUTE_ALREADY_EXISTS` | 409 |
| `ERR_DUPLICATE_UNIQUE_FIELD` | 409 |
| `ERR_RATE_OUT_OF_BOUNDS` | 422 |
| `ERR_PAUSE_RATE_LIMIT` | 429 |
| `ERR_PAYOUT_BELOW_MINIMUM` | 422 |
| `ERR_TAX_DOC_MISSING` | 422 |
| `ERR_PENDING_BALANCE_INSUFFICIENT` | 422 |
