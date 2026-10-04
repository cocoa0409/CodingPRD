# Comparative Rating Dual Channel API — Product Requirements Document

## 1. Introduction

Personal-lines carriers increasingly distribute the same products through two structurally different storefronts: a direct-to-consumer channel where shoppers quote and bind online without intermediation, and an independent-agent channel where licensed producers quote through third-party **comparative raters** — software platforms that ingest carrier rate feeds and display side-by-side premiums. Running both channels on one product catalog creates a channel-conflict problem (a direct price that undercuts the agent's quoted price poisons the agency relationship), a data-continuity problem (a consumer who starts a quote online and finishes with an agent should not have to re-key their coverage selections), and an economics problem (agent compensation — new-business commission schedules, contingent profit-sharing bonus pools, and agency-of-record commission splits on brokered placements — must be administered against a ledger the carrier controls).

This document specifies the API for a carrier-side platform that manages that dual-channel reality end to end. It governs the filing and activation of carrier products with channel-specific pricing factors, the publication of versioned rate feeds to comparative raters under strict temporal window rules, the full quote-to-bind funnel in both channels including consumer-to-agent referral with quote data reuse, snapshot telematics enrollment with a deliberately different discount realization in each channel, and the agent-economics back office: appointments, commission schedules, periodic statements with marginal-tier commission computation, mid-term cancellation clawbacks, contingent bonus pool settlement gated on loss ratio and growth, portfolio reviews with enforced segregation of duties, and bundled home placements written with unaffiliated carriers including agency-of-record transfer with commission waterfall.

A design constraint pervades the platform: time is a first-class input. Quote expiry, appointment expiry, feed coverage windows, statement periods, trailing loss-ratio windows, and policy proration are all evaluated against a server-side **logical clock**, never wall-clock time, so that every time-dependent rule is deterministic and testable. The logical clock reads exactly `2026-09-01T00:00:00Z` at server startup before any administrative adjustment, and an admin-only test-driving capability advances it to a supplied `to_iso8601` instant; advancing the clock makes lazy expirations observable on subsequent reads.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which they act. A request missing either header, carrying an empty value, or naming a role the platform does not recognize is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The declared roles are `Anonymous`, `CarrierAdmin`, `RatingManager`, `UnderwritingReviewer`, `Agent`, `Consumer`, `ComparativeRater`, and `System`.

Identity semantics differ across roles and are load-bearing for ownership checks:

- When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` record; ownership checks on any resource that references an agent compare the resource's `agent_id` to `X-User-ID`.
- When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer` record; ownership checks compare the resource's `consumer_id` to `X-User-ID`.
- When `X-User-Role` is `ComparativeRater`, `X-User-ID` is the `id` of the acting `ComparativeRater` record; the role is read-only, and ownership checks on feed-related resources compare `rater_id` to `X-User-ID`.
- When `X-User-Role` is `CarrierAdmin`, `RatingManager`, `UnderwritingReviewer`, `System`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `opened_by_user_id` or `actioned_by_user_id` on a `PortfolioReview` — but does not compare it to any entity's `id` for ownership.

Ownership enforcement: on any non-read endpoint acting on an owned resource, and on reads of owned records, an entity-backed caller whose `X-User-ID` does not match the owning foreign key on the target resource is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items before returning the page; it defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, generated at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, taken from the logical clock.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` — an integer starting at 1 at creation and incremented by exactly 1 on every state transition or mutation of the resource.

All entities in this platform — products, raters, publications, agents, appointments, schedules, consumers, quotes, policies, claims, enrollments, statements, pools, payouts, reviews, and placements — carry the full common set. Derived recomputations count as mutations: when a side effect refreshes a computed field on a resource (for example, earned premium on cancellation, or the `updated_at` refresh a scoring event performs on its policy), that resource's `version` and `updated_at` move accordingly.

### 2.5. Nested Resource Retrieval and Left-to-Right Validation

Endpoints addressed through a nested path — an appointment under an agent, a claim under a policy, a feed publication under a rater — validate path identifiers sequentially from left to right. The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) immediately, before later segments or any body content are examined. The same rule governs foreign keys referenced inside request bodies: an unresolvable `product_id`, `agent_id`, `consumer_id`, or `policy_id` is a 404. Body shape — required fields present, types valid, enum members valid, datetimes parseable — is verified as `ERR_INVALID_REQUEST` (HTTP 400); fields the server does not recognize are ignored rather than rejected.

### 2.6. Money, Ratios, and Rounding Discipline

All monetary amounts are integer cents — never floating-point dollars — and every rounding in the platform uses the round-half-up method. Two rounding placements are pinned and non-negotiable because the reverse order yields different cents. Quote premiums are rounded **per coverage line first**, then summed; the premium floor is applied only after the sum of rounded lines. Statement commissions are rounded **per policy first**, then summed across the statement. Aggregate-then-round interpretations of either rule are rejected. Ratios that surface in the API — trailing loss ratios, leakage rates — are carried to exactly 4 decimal places with round-half-up. Calendar arithmetic everywhere uses half-open intervals of the form start-inclusive, end-exclusive, and day counts are whole logical-clock calendar days.

### 2.7. Optimistic Concurrency Control

Two creation endpoints are guarded by optimistic concurrency against the parent entity's version; these are the only endpoints that accept a version field.

- Creating a commission schedule for an agent requires the request to carry `expected_agent_version`, equal to the agent's current `version` as the client last observed it. If the agent's `version` has advanced since that observation, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a successful creation supersedes the prior `ACTIVE` schedule for the same agent and line of business; a client working from a stale view of the agent's schedule set would supersede the wrong baseline, and the stale version check surfaces that before any supersede occurs.
- Creating a rate feed publication against a comparative rater requires `expected_rater_version`, equal to the rater's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Publication windows are validated against the rater's full publication set (the overlap and gap rules of §3.2); a client that computed its window from a stale publication set would validate against the wrong baseline, so the stale version is refused up front.

No other endpoint takes a version field; mutations elsewhere proceed without an OCC check.

### 2.8. Validation Priority Ordering

When a request would fail several checks, the checks are evaluated in a fixed priority order and the error of the **lowest** priority number is returned. The order is:

1. Header presence and role recognition (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. Ownership for entity-backed callers (`ERR_OWNERSHIP_MISMATCH`).
4. Request body shape (`ERR_INVALID_REQUEST`).
5. Resource existence, path segments left-to-right then body references (`ERR_NOT_FOUND`).
6. State-transition legality, including the lazy-state errors — quote expiry (`ERR_QUOTE_EXPIRED`), stale rate pin (`ERR_RATE_STALE`), product not active (`ERR_PRODUCT_NOT_ACTIVE`), feed not published (`ERR_FEED_NOT_PUBLISHED`), policy not in force (`ERR_POLICY_NOT_IN_FORCE`) — grouped under the state category whose generic member is `ERR_INVALID_STATE_TRANSITION`.
7. Compliance rules: agent appointment standing (`ERR_AGENT_TERMINATED`, `ERR_AGENT_NOT_APPOINTED_IN_STATE`), review segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), one open review per agent (`ERR_REVIEW_ALREADY_OPEN`).
8. Temporal interval rules: appointment overlap (`ERR_APPOINTMENT_WINDOW_OVERLAP`), feed strict overlap (`ERR_FEED_WINDOW_OVERLAP`) and then the feed gap rule (`ERR_FEED_WINDOW_GAP_VIOLATION`), statement period overlap (`ERR_STATEMENT_PERIOD_OVERLAP`).
9. Cross-entity referential rules: channel availability (`ERR_CHANNEL_NOT_AVAILABLE`), publishability at feed-creation time (`ERR_PRODUCT_NOT_PUBLISHABLE`), bundle eligibility (`ERR_BUNDLE_NOT_ELIGIBLE`), agent mismatch (`ERR_AGENT_MISMATCH`), duplicate rater code (`ERR_DUPLICATE_RATER_CODE`), duplicate consumer email (`ERR_DUPLICATE_CONSUMER_EMAIL`), agency-of-record transfer target (`ERR_AOR_NOT_ALLOWED`), second telematics enrollment (`ERR_TELEMATICS_ALREADY_ENROLLED`).
10. Money rules, always checked last: the direct premium cap (`ERR_PREMIUM_CAP_EXCEEDED`), paying an empty statement (`ERR_NOTHING_TO_PAY`), a claw-back that would drive a statement negative (`ERR_NEGATIVE_COMMISSION`), and terminating an agent holding active placements (`ERR_AGENT_HAS_ACTIVE_PLACEMENTS`).

The practical consequence: a request that is both unauthorized and malformed returns the authorization error; a stale rate pin masks a premium-cap breach only in the sense that the state error reports first.

### 2.9. Derived (Lazy) State Evaluation

Two states are never written by an explicit transition: they are derived on read from the logical clock. An appointment whose `effective_end` is not null and is at or before the current logical time reads as `EXPIRED`, even though nothing was ever written to it. A quote whose expiry instant has been reached likewise reads as `EXPIRED` — and a bind attempted at or past that instant fails with `ERR_QUOTE_EXPIRED`, after which the quote reads `EXPIRED` thereafter. Advancing the logical clock past these boundaries flips observed status without any write and without any version increment.

## 3. Business Logic & Workflows

### 3.1. Product Filing and Channel Differentiation

A `RatingManager` files a new product with a `product_code` unique across all products, a `line_of_business` of `AUTO` or `HOME`, the `state_code` in which the product is filed, a `channel_availability` of `DIRECT`, `AGENT`, or `BOTH` declaring which channels may quote it, and a `coverage_rates` rate table mapping each coverage code to a per-tier rate in cents. Pricing differentiation between channels is expressed as fractional factors on the product: `direct_discount_pct` (default 0; a value of 0.10 means a 10% discount) reduces direct premiums, while `agent_load_pct` (default 0; 0.15 means a 15% load) raises agent-channel premiums. When a consumer intends to bundle a home placement, `bundle_credit_pct` (default 0) is subtracted from the agent load for that quote. A `min_premium_cents` floor applies to every quoted premium after line-level rounding and summation. The anti-conflict lever is `direct_channel_max_premium_cents` (default null): when set, a direct-channel submission whose computed premium exceeds the cap is refused. `bundle_eligible` (default false) marks whether policies of this product may carry a bundled home placement.

A product is born in `DRAFT` and becomes quotable only when a `RatingManager` activates it, moving it to `ACTIVE`; activation requires `coverage_rates` to be non-empty, failing with `ERR_INVALID_REQUEST` otherwise. Withdrawal moves an `ACTIVE` product to `WITHDRAWN` — but only when no quote referencing the product sits in `QUOTED`, `REFERRED_TO_AGENT`, or `AGENT_QUOTED`; an in-flight funnel blocks withdrawal with `ERR_INVALID_STATE_TRANSITION`. Both transitions increment the product's `version`.

### 3.2. Raters and Rate Feed Publication Windows

Comparative raters are registered by a `RatingManager` with a `rater_code` (unique; a re-registration is refused with `ERR_DUPLICATE_RATER_CODE`), a `display_name`, the `feed_format_version` the rater consumes, and the `accepted_line_of_business` (`AUTO` or `HOME`). Raters carry no lifecycle status; their `version` exists primarily as the OCC anchor for publication creation under §2.7.

Feed delivery is organized as `RateFeedPublication` records linking a `rater_id` and a `product_id`, carrying an opaque `rate_table_payload` and a half-open effectiveness window from `effective_start` (inclusive) to `effective_end` (exclusive). Creating a publication is OCC-guarded on the rater's version and is subject to two temporal rules evaluated against sibling publications for the same rater-and-product pair in `DRAFT` or `PUBLISHED` status: strict overlap with an existing window is rejected with `ERR_FEED_WINDOW_OVERLAP`, and a non-overlapping window that nonetheless leaves less than a 24-hour gap to a sibling window — touching intervals count as less than 24 hours, while exactly 24 hours is allowed — is rejected with `ERR_FEED_WINDOW_GAP_VIOLATION`; between the two, the strict-overlap check is evaluated first. The product referenced must already be `ACTIVE` at creation time, failing with `ERR_PRODUCT_NOT_PUBLISHABLE` when it is still `DRAFT` or already `WITHDRAWN`. A successful creation lands in `DRAFT` and increments the rater's `version`.

Publishing is the moment a feed goes live, and it carries a two-hop cascade. The publication itself moves `DRAFT → PUBLISHED`, stamps `published_at` with the logical clock, and increments its own `version`; the product it references must be `ACTIVE` at publish time or the publish fails with `ERR_PRODUCT_NOT_ACTIVE`. The first cascade hop supersedes whatever publication was previously `PUBLISHED` for the same rater-and-product pair, moving it `PUBLISHED → SUPERSEDED` with a version increment — at most one publication per pair is ever live. The second hop flags every quote pinned to that superseded publication and still sitting in `QUOTED` or `AGENT_QUOTED`: each such quote's `rate_stale` is set to true and its `version` increments. Recall moves a publication from `DRAFT` or `PUBLISHED` to `RECALLED` with a version increment; when the recalled publication was `PUBLISHED`, the same dependent-quote staleness flag is applied to quotes pinned to it in `QUOTED` or `AGENT_QUOTED`.

Consumers enter the platform through open registration: an `Anonymous` caller registers a consumer with an `email` (unique across the platform — a duplicate registration is refused with `ERR_DUPLICATE_CONSUMER_EMAIL`), a `full_name`, a `date_of_birth` as an ISO date, and a `home_state_code`.

### 3.3. The Quote Funnel: Submit, Re-rate, Refer, Bind

Every resource's lifecycle position is exposed through its `status` field, whose exact enumeration values appear throughout §3. A quote is created in `DRAFT` against a `consumer_id` and a `product_id`, carrying a `channel` of `DIRECT` or `AGENT` and the selected `coverages` as coverage-code-and-tier pairs. Optional flags shape downstream behavior: `bundled_home_intended` (default false) engages the agent-channel bundle credit, and `telematics_opt_in` (default false) drives enrollment at bind. Channel and identity are bound at creation: an agent-channel quote must carry an `agent_id` (omitting it fails with `ERR_AGENT_MISMATCH`), an `Agent` caller may only create quotes naming themselves as `agent_id`, and a `Consumer` caller may only create `DIRECT` quotes for their own `consumer_id`. At creation `quoted_premium_cents`, `quoted_at`, and `expires_at` are null, `rate_stale` is false, and both `referral_snapshot` and `rate_feed_publication_id` are null.

Submitting a `DRAFT` quote — by the consumer for a direct quote or by the named agent for an agent quote — prices it and moves it to `QUOTED`. Pricing is the channel quote premium: a channel factor is chosen first (for `DIRECT`, one minus `direct_discount_pct`; for `AGENT`, one plus `agent_load_pct`, less `bundle_credit_pct` when `bundled_home_intended` is true); each selected coverage is priced by looking up its code and tier in the product's `coverage_rates`, multiplying by the channel factor, and rounding half-up to integer cents **per line**; the rounded lines are then summed; and finally the sum is raised to `min_premium_cents` if it falls below the floor. Preconditions gate the transition: the product must be `ACTIVE` (`ERR_PRODUCT_NOT_ACTIVE`); the product's `channel_availability` must include the quote's channel (`ERR_CHANNEL_NOT_AVAILABLE`); for an agent-channel quote the named agent must be `APPOINTED` and not terminated (`ERR_AGENT_TERMINATED`) and must hold an `ACTIVE` appointment covering the product's state and line of business (`ERR_AGENT_NOT_APPOINTED_IN_STATE`); and for an agent-channel quote a publication for the product must be `PUBLISHED` with a window covering the current logical time — the earliest-published qualifying publication wins the pin, with ties broken by the lowest `published_at` and then by publication `created_at` ascending — and its id is recorded as `rate_feed_publication_id` (absence of a covering publication fails with `ERR_FEED_NOT_PUBLISHED`). Direct quotes pin no publication: `rate_feed_publication_id` stays null. Finally, when the product carries a `direct_channel_max_premium_cents` cap, a direct-channel premium above the cap is refused with `ERR_PREMIUM_CAP_EXCEEDED`. A successful submit stamps `quoted_at` with the logical clock, sets `expires_at` to exactly 30 days after `quoted_at`, clears `rate_stale` to false, and increments the quote's `version`.

Re-rating unwinds a priced quote without destroying it. From `QUOTED` it returns to `DRAFT`; from `AGENT_QUOTED` it returns to `REFERRED_TO_AGENT` so the referral relationship survives. Either way the computed artifacts are cleared — `quoted_premium_cents`, `quoted_at`, `expires_at`, and `rate_feed_publication_id` go to null and `rate_stale` to false — while on the agent-side re-rate the `agent_id` and `referral_snapshot` are preserved. The quote's `version` increments.

Referral is the data-reuse bridge between channels. A `Consumer` holding a `DIRECT` quote in `QUOTED` may refer it to an agent by supplying an `agent_id`; the target agent must be `APPOINTED` (`ERR_AGENT_TERMINATED`) and hold an `ACTIVE` appointment for the product's state and line (`ERR_AGENT_NOT_APPOINTED_IN_STATE`), and the quote must actually be direct-channel (`ERR_INVALID_STATE_TRANSITION` otherwise). The transition moves the quote `QUOTED → REFERRED_TO_AGENT`, flips its `channel` to `AGENT`, sets the `agent_id`, and captures the `referral_snapshot` — the current `coverages` together with the direct-channel `quoted_premium_cents` — which is the payload the agent inherits.

Agent-quoting completes the referral. The acting agent must be the quote's own `agent_id` (`ERR_OWNERSHIP_MISMATCH`), must still be `APPOINTED` (`ERR_AGENT_TERMINATED`) with an `ACTIVE` appointment for the product's state and line (`ERR_AGENT_NOT_APPOINTED_IN_STATE`), and a `PUBLISHED` publication covering the current time must exist for the product (`ERR_FEED_NOT_PUBLISHED`), pinned by the same earliest-published selector used at submit. If the agent supplies new `coverages` differing from the snapshot's, the new selection is adopted; if the payload omits `coverages`, the snapshot's selections are reused verbatim. The premium is recomputed with agent-channel factors, `quoted_at` and the 30-day `expires_at` are restamped, `rate_stale` clears, and the quote moves `REFERRED_TO_AGENT → AGENT_QUOTED`.

Binding is where a quote becomes a policy, and it is guarded by two lazy-state checks on both legs: the logical clock must be before `expires_at` (`ERR_QUOTE_EXPIRED`) and `rate_stale` must be false (`ERR_RATE_STALE`). A `Consumer` binds a direct quote from `QUOTED` — the caller must be the quote's own `consumer_id` (`ERR_OWNERSHIP_MISMATCH`) and the quote must still be direct-channel (`ERR_INVALID_STATE_TRANSITION`). An `Agent` binds from `AGENT_QUOTED` — the caller must be the quote's `agent_id` (`ERR_OWNERSHIP_MISMATCH`) and must still be `APPOINTED` with an `ACTIVE` appointment for the product's state and line (`ERR_AGENT_TERMINATED` / `ERR_AGENT_NOT_APPOINTED_IN_STATE`). Either way the quote moves to `BOUND` and a `Policy` is born `IN_FORCE` with `inception_at` set to the logical clock, a `term_days` of 365, and `quote_id`, `consumer_id`, `agent_id` (null on direct policies), `product_id`, and `channel` copied from the quote. The written premium differs by channel in exactly one respect — telematics money movement at bind, described in §3.5. Quotes may also be withdrawn from `QUOTED`, `REFERRED_TO_AGENT`, or `AGENT_QUOTED` to `WITHDRAWN`; withdrawal from `QUOTED` or `REFERRED_TO_AGENT` increments the quote's `version`, while withdrawal from `AGENT_QUOTED` records no further field changes. Expiry is lazy per §2.9: once the clock reaches `expires_at`, the quote reads `EXPIRED` and bind attempts fail; referred and agent-quoted quotes expire the same way as submitted ones.

### 3.4. Policies, Claims, and Mid-Term Cancellation

A policy's premium accounting is continuous. While `IN_FORCE`, its `earned_premium_cents` equals its full `written_premium_cents` and `unearned_premium_cents` is zero. Cancellation — by the owning consumer, the policy's agent, or a `CarrierAdmin`; an entity-backed caller who does not own the policy is refused with `ERR_OWNERSHIP_MISMATCH` — moves the policy to `CANCELLED`, stamps `cancelled_at`, and prorates: the days in force are the whole calendar days in the half-open interval from `inception_at` to `cancelled_at`, the earned premium is the written premium multiplied by the days in force and divided by `term_days` (365), rounded half-up to integer cents, and the unearned premium is the written premium minus the earned. The policy's `version` increments. If the policy carries a telematics enrollment still in `ENROLLED` or `PARTICIPATING`, cancellation forces it to `OPTED_OUT`; crucially, any direct-channel up-front discount already baked into the written premium is **not** retroactively clawed back on the policy, and the enrollment's `adjustment_cents` stays null. A policy also carries `per_policy_commission_cents` (the commission a covering statement credits for it; null for direct policies) and `clawback_cents` (default 0), both written by the commission machinery of §3.6.

Claims are reported against a policy by a `CarrierAdmin` with a `claim_type` of `COLLISION`, `LIABILITY`, `HOME_DAMAGE`, or `OTHER` and a non-negative `incurred_amount_cents`; the report lands `REPORTED` with `reported_at` stamped from the logical clock, and `policy_id` links it to its policy. Closing a claim moves it `REPORTED → CLOSED` with a version increment; the incurred amount remains on the claim and continues to count toward every loss-ratio window regardless of whether the claim is open or closed.

### 3.5. Snapshot Telematics: Two Discount Realizations

When a quote with `telematics_opt_in` true is bound, a `TelematicsEnrollment` is created alongside the policy in `ENROLLED` status, linked by `policy_id`; at most one enrollment may ever exist per policy, and a second attempt is rejected with `ERR_TELEMATICS_ALREADY_ENROLLED`. The enrollment's `channel` is copied from the policy, and that channel selects the discount variant.

The scoring table is shared. A `driving_score` of 90 or above earns a 0.20 discount fraction; a score of 70 through 89 earns 0.10; below 70 earns 0.00. The boundary is inclusive at the top of each tier: a score of exactly 90 earns 0.20, a score of exactly 89 earns 0.10. At scoring, both channels converge on the same final premium — the quote's `quoted_premium_cents` multiplied by one minus the table fraction, rounded half-up to integer cents — but the path and the observable intermediate numbers differ.

In the direct variant, the 15% participation discount is taken **at bind**: the policy's `written_premium_cents` is the quoted premium minus the quoted premium times 0.15 rounded half-up, and the enrollment's `upfront_discount_cents` records exactly that discount. When the enrollment is later scored, `discount_pct_applied` records the table fraction and `adjustment_cents` records the final premium minus the written premium — negative when the earned discount exceeds the participation discount, a credit to the consumer. In the agent variant, nothing moves at bind: `written_premium_cents` equals the quoted premium and `upfront_discount_cents` is 0. At scoring, `adjustment_cents` is again the final premium minus the written premium, so the entire discount realizes as a retroactive credit.

Device activation — by the consumer or the agent — moves the enrollment `ENROLLED → PARTICIPATING` and requires the policy to be `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`). Scoring is performed exclusively by the `System` automation identity: it moves `PARTICIPATING → SCORED`, requires the policy to remain `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`), and requires `driving_score` within the inclusive range 0 to 100 (`ERR_INVALID_REQUEST` outside it). Scoring records the score, computes `discount_pct_applied` and `adjustment_cents` per the channel variant, refreshes the policy's `updated_at`, and increments the enrollment's `version`.

Opting out — by the consumer or the agent, from either `ENROLLED` or `PARTICIPATING` — moves the enrollment to `OPTED_OUT`. For a direct-channel enrollment with an `upfront_discount_cents` greater than zero, an **explicit** opt-out debits the participation discount back: `adjustment_cents` is set to positive `upfront_discount_cents`, restoring the premium. An agent-channel opt-out sets `adjustment_cents` to 0 — no money ever moved up front, so nothing reverses. Opt-out forced by policy cancellation, by contrast, never computes a debit: `adjustment_cents` stays null on that path.

### 3.6. Agent Economics: Appointments, Schedules, Statements, Clawbacks

An agent begins life as an `APPLICANT`, created by a `CarrierAdmin` with an `agency_name`, a `principal_name`, and a `resident_state_code`. Appointment to the carrier's agency force — moving `APPLICANT → APPOINTED` — is performed by an `UnderwritingReviewer` and requires the agent to already hold at least one `ACTIVE` appointment record (`ERR_AGENT_NOT_APPOINTED_IN_STATE` otherwise). Appointment records themselves are created by an `UnderwritingReviewer` with a `state_code`, a `line_of_business`, and a half-open window from `effective_start` to an optional `effective_end` (null means open-ended); a new appointment whose window intersects an existing `ACTIVE` appointment for the same agent, state, and line is rejected with `ERR_APPOINTMENT_WINDOW_OVERLAP`, while adjacency — one window's end equaling the other's start — is allowed. Appointments may be terminated directly (recording `terminated_reason`), expire lazily per §2.9, or fall with the agent.

Suspension (`APPOINTED → SUSPENDED`) and reinstatement (`SUSPENDED → APPOINTED`) are reviewer actions; reinstatement, like initial appointment, requires at least one `ACTIVE` appointment record (`ERR_AGENT_NOT_APPOINTED_IN_STATE`). Termination — direct, or via a portfolio review — carries the platform's deepest cascade, three hops. The agent moves to `TERMINATED`, records its `terminated_reason` (an optional `reason` may accompany the request), and increments its `version`. Hop one: every `ACTIVE` appointment of the agent moves to `TERMINATED` with `terminated_reason` recorded as `AGENT_TERMINATED`. Hop two: every `ACTIVE` commission schedule of the agent whose `line_of_business` is no longer covered by any remaining `ACTIVE` appointment moves to `VOIDED`. Hop three: every `DRAFT` commission statement of the agent moves to `STALE` — it must be regenerated against the surviving schedules. Termination is blocked outright while any bundle placement naming the agent sits in `PLACED` status, failing with `ERR_AGENT_HAS_ACTIVE_PLACEMENTS`.

Commission schedules are created by a `CarrierAdmin` under the OCC rule of §2.7: the request carries `line_of_business`, `effective_start`, an optional `effective_end`, the `tiers` array, `contingent_bonus_eligible`, and the mandatory `expected_agent_version`. The `tiers` are marginal brackets — each with an `up_to_cents` ceiling (null on the unbounded final tier) and a `rate_pct` — listed in ascending order of ceiling. Creation supersedes the prior `ACTIVE` schedule for the same agent and line, moving it to `SUPERSEDED`, and increments the agent's `version`.

Statement generation is where tier arithmetic meets policies. A `CarrierAdmin` requests a statement for a half-open window from `period_start` to `period_end`; the window must satisfy `period_end` after `period_start` and not in the future relative to the logical clock (`ERR_INVALID_REQUEST`), and it must not overlap any `FINALIZED`, `PAID`, or `CLAWED_BACK` statement of the same agent (`ERR_STATEMENT_PERIOD_OVERLAP`). The eligible policies are the agent's bound policies whose policy `created_at` falls within the window, processed strictly in policy `created_at` ascending order — never by id. A cumulative tier cursor tracks the agent's written premium already consumed across the statement period. For each policy in order, the policy's `written_premium_cents` is poured through the tiers: the current tier's remaining capacity is its ceiling minus the cursor (or, on the unbounded final tier, whatever remains of the policy), the slice taken is the smaller of the policy's remaining premium and that capacity (never below zero), each slice earns commission at its tier's `rate_pct`, the cursor advances by the slice, and the pour stops when the policy is exhausted. The policy's commission is rounded half-up to integer cents **per policy** and recorded as the policy's `per_policy_commission_cents`; the statement's `commission_cents` is the sum of those rounded per-policy values. The schedule applied to each policy is the agent's `ACTIVE` schedule for the policy product's line of business whose window covers the policy's `created_at`; a policy with no covering schedule is excluded from the statement entirely — not zero-rated. The statement is born `DRAFT` with its `line_items` — one line per included policy carrying `policy_id`, `premium_cents`, and `commission_cents`, ordered by policy `created_at` ascending — plus its `written_premium_cents` total and a `clawback_cents` of 0; `net_payable_cents` is `commission_cents` minus `clawback_cents`.

Finalization locks the statement: `line_items`, `written_premium_cents`, `commission_cents`, and `net_payable_cents` freeze as it moves `DRAFT → FINALIZED`. Payment moves `FINALIZED → PAID` and requires a positive `net_payable_cents` — paying a zero-net statement fails with `ERR_NOTHING_TO_PAY`. Claw-back recovers commission on a cancelled policy: the supplied `policy_id` must appear in the statement's `line_items` (`ERR_INVALID_REQUEST`), the referenced policy must be `CANCELLED` (`ERR_POLICY_NOT_IN_FORCE`), and the policy must not already carry a positive `clawback_cents` (`ERR_INVALID_STATE_TRANSITION`). The clawed amount is the policy's `per_policy_commission_cents` minus the portion earned for the days actually in force — that earned portion being the per-policy commission multiplied by the days in force and divided by `term_days`, rounded half-up — and is recorded on both the policy's `clawback_cents` and the statement's `clawback_cents`, with `net_payable_cents` recomputed as `commission_cents` minus `clawback_cents`. A claw-back that would drive the statement's net below zero is refused with `ERR_NEGATIVE_COMMISSION`. The statement moves `PAID → CLAWED_BACK`; `DRAFT → STALE` occurs only through the agent-termination cascade.

### 3.7. Contingent Bonus Pools

A `CarrierAdmin` opens a bonus pool for a `year` with a `pool_total_cents` and two eligibility gates: `loss_ratio_threshold` (default 0.70) and `growth_threshold_pct` (default 0.05). The pool sits `OPEN` until settlement.

Settlement evaluates agents in a pinned order that resolves what would otherwise look like a circular dependency — eligibility gates are computed **first**, excluding any bonus accrual. The loss gate: the agent's trailing loss ratio at settle time must be **strictly** less than `loss_ratio_threshold`; an agent exactly at the threshold fails. The growth gate: year-over-year written premium growth — the trailing twelve months' earned premium minus the prior twelve months' earned, divided by the prior twelve months' earned — must be at least `growth_threshold_pct`; when the prior twelve months' earned is zero, growth is **defined** as 1.0, so first-year agents pass. An agent enters the eligible pool only by passing both gates and having positive trailing twelve-month earned premium. Each eligible agent's `payout_cents` is the pool total multiplied by the agent's earned premium and divided by the total eligible earned premium, **floor-rounded** to integer cents; the `undistributed_cents` remainder — pool total minus the sum of payouts — is retained by the carrier and never redistributed. Settlement creates one `BonusPayout` per agent who holds a `contingent_bonus_eligible` `ACTIVE` schedule and has positive trailing earned premium, recording `earned_premium_cents`, the computed `eligible` flag, an `ineligibility_reason` of `LOSS_RATIO`, `GROWTH`, or `NONE`, and the `payout_cents` (zero when ineligible); the pool moves `OPEN → SETTLED`, stamps `settled_at`, and increments its `version`. Each payout links `pool_id` and `agent_id`.

The trailing loss ratio itself is computed over the window of the 365 days ending at the as-of instant, **both bounds inclusive**. Earned premium in the window is summed over the agent's policies — any status — whose `inception_at` falls in the window, each contributing its written premium multiplied by the days of overlap between its in-force span (inception through cancellation, or through the window end if still in force) and the window, divided by `term_days`, rounded half-up. Incurred loss is the sum of `incurred_amount_cents` over claims of those policies whose `reported_at` falls in the window, counting claims in both `REPORTED` and `CLOSED` status. When the earned total is zero the ratio is defined as 0.0000 — the empty-book rule — and otherwise it is incurred divided by earned, rounded half-up at 4 decimal places.

### 3.8. Portfolio Reviews and Segregation of Duties

An `UnderwritingReviewer` opens a portfolio review on an agent with a `reason`; the platform records the caller's `X-User-ID` as `opened_by_user_id`, computes the `trailing_loss_ratio` (4 decimal places) and `earned_premium_trailing_cents` (zero when the agent has no policies) at open, and refuses to open a second review while one is already `OPEN` for the same agent (`ERR_REVIEW_ALREADY_OPEN`). Issuing findings records the reviewer's `findings` text and moves the review `OPEN → FINDINGS_ISSUED`. Taking action moves it `FINDINGS_ISSUED → ACTION_TAKEN` under a hard segregation-of-duties rule: the actioning reviewer's `X-User-ID` must differ from `opened_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the platform records it as `actioned_by_user_id`. The `action` is one of `CONTINUE`, `SUSPEND`, or `TERMINATE`. `CONTINUE` leaves the agent untouched. `SUSPEND` moves an `APPOINTED` agent to `SUSPENDED`. `TERMINATE` runs the full agent-termination cascade of §3.6 — including its precondition that no `PLACED` bundle placements name the agent (`ERR_AGENT_HAS_ACTIVE_PLACEMENTS`). Each transition increments the review's `version`.

### 3.9. Bundled Home Placements and Agency-of-Record Transfer

A bundled home placement writes the consumer's home coverage with an **unaffiliated** carrier while the carrier's own auto or home policy anchors the relationship. An `Agent` or `CarrierAdmin` creates the placement against a policy with the `unaffiliated_carrier_name`, the `home_premium_cents` written with the outside carrier, and the `total_commission_cents` the agency earns on the placement. The policy's product must be `bundle_eligible` (`ERR_BUNDLE_NOT_ELIGIBLE`), the policy must be `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`), and the policy must carry an agent — the placement's `agent_id` becomes the policy's `agent_id` as the current agency of record, and a direct policy with no agent cannot take a placement (`ERR_AGENT_MISMATCH`). The placement is born `QUOTED`, linked by `policy_id`.

The agent of record — and only that agent (`ERR_OWNERSHIP_MISMATCH`) — marks the placement written, moving `QUOTED → PLACED` with the policy still `IN_FORCE` (`ERR_POLICY_NOT_IN_FORCE`). Decline moves a `QUOTED` placement to `DECLINED` at the hand of the agent or a `CarrierAdmin`; declining a `PLACED` placement is reserved to a `CarrierAdmin`, and in that case the unearned commission simply remains with the current agent of record — no transfer is computed. An optional `reason` may accompany the decline.

Agency-of-record transfer, performed by a `CarrierAdmin` supplying a `new_agent_id`, moves a `PLACED` placement to `AOR_TRANSFERRED`. The receiving agent must be `APPOINTED`, must differ from the current `agent_id` (`ERR_AOR_NOT_ALLOWED` otherwise — the same error covers a transfer attempted on a non-`PLACED` placement), and must hold an `ACTIVE` appointment for the policy product's state and line of business (`ERR_AGENT_NOT_APPOINTED_IN_STATE`). The commission waterfall splits the `total_commission_cents` by time: the days in force are the whole calendar days from the policy's `inception_at` to the transfer instant; the `earned_commission_cents` retained by the original agent is the total commission multiplied by those days and divided by the policy's `term_days`, rounded half-up; and the `transferred_commission_cents` moved to the receiving agent is the exact complement — total minus earned — so the two legs sum to the total exactly and nothing is created or lost. The placement's `agent_id` and `transferred_to_agent_id` both become the `new_agent_id`, and the placement's `version` increments.

### 3.10. Quote-to-Bind Leakage Analytics

A computed read answers the channel-conflict question: of the quotes that entered the funnel, how much never bound. The report is parameterized by a half-open window from `period_start` to `period_end`, a `basis` of `COUNT` or `PREMIUM_WEIGHTED`, and an optional `channel` filter. The cohort for a channel is the quotes of that channel whose `quoted_at` falls within the window — a quote must have reached `QUOTED` or `AGENT_QUOTED` at least once to count, which is exactly what a non-null `quoted_at` certifies. A cohort member has leaked when it did not reach `BOUND` with a bind before `period_end` — that is, it is `EXPIRED`, `WITHDRAWN`, or still sitting in `QUOTED`, `REFERRED_TO_AGENT`, or `AGENT_QUOTED`. On the `COUNT` basis, leakage is the leaked count divided by the cohort count, with an empty cohort defined as 0.0000. On the `PREMIUM_WEIGHTED` basis, leakage is the sum of the leaked quotes' **latest** `quoted_premium_cents` divided by the sum over the whole cohort, with a zero premium total defined as 0.0000. Both variants round half-up at 4 decimal places, and the two bases yield different leakage for the same funnel whenever the leaked quotes are not premium-average.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — state transitions, computed reads with inputs, cascading actions — return `200 OK`. All paths below are served from the API root; there is no additional mount prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock to a supplied instant | CarrierAdmin |
| POST | `/products` | Create a product in DRAFT | RatingManager |
| GET | `/products` | List products (filters: channel_availability, status, state_code) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/products/{id}` | Get a product | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/products/{id}/activate` | Activate a DRAFT product | RatingManager |
| POST | `/products/{id}/withdraw` | Withdraw an ACTIVE product | RatingManager |
| GET | `/products/{id}/rate-feed-publications` | List feed publications for a product | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/raters` | Register a comparative rater | RatingManager |
| GET | `/raters` | List comparative raters | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/raters/{id}` | Get a comparative rater | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/raters/{id}/rate-feed-publications` | Create a DRAFT feed publication (OCC-guarded on the rater) | RatingManager |
| GET | `/raters/{id}/rate-feed-publications` | List feed publications for a rater | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/rate-feed-publications/{id}` | Get a feed publication | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/rate-feed-publications/{id}/publish` | Publish a DRAFT publication; supersedes the prior live one | RatingManager |
| POST | `/rate-feed-publications/{id}/recall` | Recall a DRAFT or PUBLISHED publication | RatingManager |
| POST | `/agents` | Create an agent (APPLICANT) | CarrierAdmin |
| GET | `/agents` | List agents (filters: status, state_code) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/agents/{id}` | Get an agent | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/agents/{id}/appoint` | Appoint an APPLICANT agent | UnderwritingReviewer |
| POST | `/agents/{id}/suspend` | Suspend an APPOINTED agent | UnderwritingReviewer |
| POST | `/agents/{id}/reinstate` | Reinstate a SUSPENDED agent | UnderwritingReviewer |
| POST | `/agents/{id}/terminate` | Terminate an agent with full cascade | UnderwritingReviewer |
| POST | `/agents/{id}/appointments` | Create an ACTIVE appointment | UnderwritingReviewer |
| GET | `/agents/{id}/appointments` | List an agent's appointments | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/appointments/{id}` | Get an appointment (EXPIRED derived on read) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/appointments/{id}/terminate` | Terminate an ACTIVE appointment | UnderwritingReviewer |
| POST | `/agents/{id}/commission-schedules` | Create a commission schedule (OCC-guarded on the agent) | CarrierAdmin |
| GET | `/agents/{id}/commission-schedules` | List an agent's commission schedules | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/commission-schedules/{id}` | Get a commission schedule | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/consumers` | Register a consumer | Anonymous |
| GET | `/consumers` | List consumers (filter: home_state_code) | CarrierAdmin, RatingManager, UnderwritingReviewer, System |
| GET | `/consumers/{id}` | Get a consumer | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/quotes` | Create a DRAFT quote (DIRECT by consumer, AGENT by agent) | Consumer, Agent |
| GET | `/quotes` | List quotes (filters: consumer_id, product_id, agent_id, rate_feed_publication_id, channel, status) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/quotes/{id}` | Get a quote (lazy EXPIRED evaluation on read) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/quotes/{id}/submit` | Submit a DRAFT quote; compute premium, pin feed | Consumer, Agent |
| POST | `/quotes/{id}/re-rate` | Reset a priced quote for re-rating, preserving referrals | Consumer, Agent |
| POST | `/quotes/{id}/refer-to-agent` | Consumer hands a DIRECT QUOTED quote to an agent | Consumer |
| POST | `/quotes/{id}/agent-quote` | Agent re-quotes a referred quote, reusing snapshot coverages | Agent |
| POST | `/quotes/{id}/bind` | Bind a QUOTED (consumer) or AGENT_QUOTED (agent) quote | Consumer, Agent |
| POST | `/quotes/{id}/withdraw` | Withdraw a non-terminal, non-bound quote | Consumer, Agent |
| GET | `/policies` | List policies (filters: quote_id, consumer_id, agent_id, product_id, status) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/policies/{id}` | Get a policy | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/policies/{id}/cancel` | Cancel an IN_FORCE policy; prorate earned premium | Consumer, Agent, CarrierAdmin |
| POST | `/policies/{id}/claims` | Report a claim against a policy | CarrierAdmin |
| GET | `/policies/{id}/claims` | List claims of a policy | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/claims/{id}` | Get a claim | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/claims/{id}/close` | Close a REPORTED claim | CarrierAdmin |
| GET | `/policies/{id}/telematics-enrollments` | List enrollments of a policy (0 or 1 element) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/telematics-enrollments/{id}` | Get a telematics enrollment | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/telematics-enrollments/{id}/activate-device` | Activate the snapshot device | Consumer, Agent |
| POST | `/telematics-enrollments/{id}/score` | Record driving score; realize channel-specific discount | System |
| POST | `/telematics-enrollments/{id}/opt-out` | Opt out before scoring; DIRECT debits the up-front discount | Consumer, Agent |
| POST | `/agents/{id}/commission-statements` | Generate a DRAFT statement for a period | CarrierAdmin |
| GET | `/agents/{id}/commission-statements` | List an agent's statements | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/commission-statements/{id}` | Get a statement | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| POST | `/commission-statements/{id}/finalize` | Finalize a DRAFT statement | CarrierAdmin |
| POST | `/commission-statements/{id}/pay` | Pay a FINALIZED statement | CarrierAdmin |
| POST | `/commission-statements/{id}/claw-back` | Claw back commission for a cancelled policy | CarrierAdmin |
| POST | `/contingent-bonus-pools` | Create an OPEN bonus pool | CarrierAdmin |
| GET | `/contingent-bonus-pools` | List bonus pools (filters: year, status) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/contingent-bonus-pools/{id}` | Get a bonus pool | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| POST | `/contingent-bonus-pools/{id}/settle` | Settle an OPEN pool; create payouts, retain remainder | CarrierAdmin |
| GET | `/contingent-bonus-pools/{id}/bonus-payouts` | List payouts of a pool | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/agents/{id}/bonus-payouts` | List payouts of an agent | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/bonus-payouts/{id}` | Get a bonus payout | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| POST | `/agents/{id}/portfolio-reviews` | Open a portfolio review; compute trailing loss ratio | UnderwritingReviewer |
| GET | `/agents/{id}/portfolio-reviews` | List an agent's reviews | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/portfolio-reviews/{id}` | Get a portfolio review | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| POST | `/portfolio-reviews/{id}/issue-findings` | Issue findings on an OPEN review | UnderwritingReviewer |
| POST | `/portfolio-reviews/{id}/take-action` | Act on a FINDINGS_ISSUED review (segregation of duties) | UnderwritingReviewer |
| POST | `/policies/{id}/bundle-placements` | Create a bundled home placement on a policy | Agent, CarrierAdmin |
| GET | `/policies/{id}/bundle-placements` | List bundle placements of a policy | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| GET | `/bundle-placements` | List bundle placements (filters: agent_id, transferred_to_agent_id, status) | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, System |
| GET | `/bundle-placements/{id}` | Get a bundle placement | CarrierAdmin, RatingManager, UnderwritingReviewer, Agent, Consumer, ComparativeRater, System |
| POST | `/bundle-placements/{id}/place` | Mark a QUOTED placement as placed | Agent |
| POST | `/bundle-placements/{id}/transfer-aor` | Transfer agency of record; commission waterfall | CarrierAdmin |
| POST | `/bundle-placements/{id}/decline` | Decline a QUOTED (agent or carrier) or PLACED (carrier) placement | Agent, CarrierAdmin |
| GET | `/leakage-reports/quote-to-bind` | Quote-to-bind leakage by channel over a window, COUNT or PREMIUM_WEIGHTED | CarrierAdmin, RatingManager, UnderwritingReviewer, System |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_RATE_STALE` | 409 Conflict |
| `ERR_PRODUCT_NOT_ACTIVE` | 409 Conflict |
| `ERR_FEED_NOT_PUBLISHED` | 409 Conflict |
| `ERR_POLICY_NOT_IN_FORCE` | 409 Conflict |
| `ERR_AGENT_NOT_APPOINTED_IN_STATE` | 409 Conflict |
| `ERR_AGENT_TERMINATED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_REVIEW_ALREADY_OPEN` | 409 Conflict |
| `ERR_APPOINTMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_FEED_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_FEED_WINDOW_GAP_VIOLATION` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CHANNEL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_PRODUCT_NOT_PUBLISHABLE` | 409 Conflict |
| `ERR_AGENT_MISMATCH` | 409 Conflict |
| `ERR_BUNDLE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_AGENT_HAS_ACTIVE_PLACEMENTS` | 409 Conflict |
| `ERR_AOR_NOT_ALLOWED` | 409 Conflict |
| `ERR_TELEMATICS_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_PREMIUM_CAP_EXCEEDED` | 409 Conflict |
| `ERR_NOTHING_TO_PAY` | 409 Conflict |
| `ERR_NEGATIVE_COMMISSION` | 409 Conflict |
| `ERR_DUPLICATE_RATER_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CONSUMER_EMAIL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
