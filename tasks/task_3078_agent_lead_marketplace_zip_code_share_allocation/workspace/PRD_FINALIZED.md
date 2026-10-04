# Agent Lead Marketplace API — Product Requirements Document

## 1. Introduction

The Agent Lead Marketplace is a two-sided platform in which licensed real-estate agents purchase impression share within individual zip codes, and consumers inquiring on listings inside those zips are routed to advertising agents in proportion to the share each agent has bought. Pricing per lead is not flat: as more share sells inside a market, the demand tier rises, and the per-lead unit price climbs. Advertisers post an activation deposit when they buy share and are charged against their order as finalized leads are delivered, with a refund path for invalid or duplicate leads adjudicated by marketplace operations.

The platform must also govern team accounts — groups of licensed agents operating under a team lead who buys share on the team's behalf — and distribute team-routed leads across members in proportion to configured weights. Live connection bridging lets a consumer be transferred by phone to the assigned agent, with both-party consent captured and the call recording retained for a fixed window before purge. Agent performance on response time, conversion, and consumer ratings feeds a scoring engine whose output drives future routing rank and tier classification.

Beyond the lead flow itself, the marketplace ingests listings from multiple feeds (MLS or broker-direct) whose display rules vary with each market's participation agreement, and it exposes a dispute channel for brokerages to contest listing display or lead attribution. This document specifies the API surface, the business rules that bind these flows together, and the cross-cutting invariants — capacity, licensing, OCC, and the logical clock — that an implementation must respect.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry the headers `X-User-ID` and `X-User-Role`. A request missing either header, or with a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes four roles:

- `Agent` — a licensed real-estate agent advertiser. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` record; ownership checks on any resource that references an `Agent` (for example `ShareOrder.buyer_agent_id`, `Lead.accepted_agent_id`, `TeamAccount.lead_agent_id`, or `TeamMembership.agent_id`) compare the resource's foreign-key field to `X-User-ID`. An `Agent` buys zip share, accepts lead offers, bridges live connections, files credit claims, manages team accounts they lead, and may deactivate themselves.
- `BrokerageUser` — a staff member acting on behalf of a brokerage. When `X-User-Role` is `BrokerageUser`, `X-User-ID` is the `id` of the acting `Brokerage` record; ownership checks on any resource that references a `Brokerage` (for example `Dispute.brokerage_id` or `Listing.brokerage_id`) compare the resource's foreign-key field to `X-User-ID`. A `BrokerageUser` ingests listings and files disputes.
- `MarketplaceOps` — an opaque operator identifier. When `X-User-Role` is `MarketplaceOps`, `X-User-ID` is not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. MarketplaceOps runs sweeps, moderates markets, agents, and listings, resolves claims and disputes, and drives the logical clock.
- `PlatformAdmin` — an opaque superuser. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque identifier not tied to any persisted entity. PlatformAdmin has access to every endpoint.

When an action targets a resource the caller does not own (for example an `Agent` attempting to accept a lead offer routed to a different agent's order), the request is rejected with `ERR_UNAUTHORIZED`. When an action requires the acting agent to be the team lead and the caller is not the team's `lead_agent_id`, the request is rejected with `ERR_NOT_TEAM_LEAD`. A request whose body is malformed, missing a required field, or violates a field-level constraint (an enum outside its allowed set, a range violation, or a format violation) is rejected with `ERR_VALIDATION` (HTTP 400).

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order. The `meta` object of the response envelope for a list endpoint always includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

The platform runs on a logical clock. At server startup the clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time. An operator with the `MarketplaceOps` or `PlatformAdmin` role may advance the clock by submitting a `current_utc` value to the clock-setting capability; the server's notion of "now" is whatever the clock last read.

Time-driven work — expiring unanswered offers, sweeping orders whose campaign window has ended, purging recordings past their retention horizon, and snapshotting agent performance — is not performed by a background thread. It is performed only when an operator explicitly invokes the ops-run capability, which executes a fixed sequence of sweep steps and returns an `OpsRun` record. Each `OpsRun` carries a monotonically increasing `seq` starting at 1, the `run_at` instant from the logical clock, and a `sweep_counts` object reporting how many entities of each kind were touched: expired offers, rerouted leads, unassigned leads, expired orders, credited orders, purged recordings, and snapshotted agents. `OpsRun` records carry only `id` and `created_at`; they do not carry `updated_at` or `version`.

### 2.5. Share Capacity and Pricing Discipline

Every market has a fixed share capacity of 10000 basis points. A `Market` carries two derived counters: `allocated_bps`, the sum of `share_bps` over that market's orders whose `order_status` is `ACTIVE`, and `available_bps`, which is 10000 minus `allocated_bps`. When an order transitions into `ACTIVE`, its `share_bps` is added to `allocated_bps`; when an order leaves `ACTIVE` (pause, completion, or expiry-cancel), its `share_bps` is subtracted. Each such mutation recomputes the market's `current_unit_price_cents` and increments the market's `version`.

A buy request whose `share_bps` would push the aggregate over 10000 at the activation or resume instant is rejected with `ERR_SHARE_CAPACITY_EXCEEDED` (HTTP 422). Note that share capacity is checked at activation, not at order-creation: an order can be created in `PENDING_PAYMENT` while the market is full, and only fails if capacity is still insufficient when payment is captured. The same re-check applies on resume.

### 2.6. Licensing and Geographic Eligibility

Real-estate licensure is state-bound. An `Agent` carries a `license_state`, and a `Market` carries a `state_code`. To buy share in a market, to be eligible as a routing candidate in that market, or to be manually assigned a lead in that market, the agent's `license_state` must equal the market's `state_code`. A mismatch is rejected with `ERR_LICENSE_STATE_MISMATCH` (HTTP 422) on share purchase, on offer acceptance, and on manual assignment. License state does not constrain which listings a brokerage may submit, but it does constrain which agents the routing selector may consider.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control on a parent entity's `version`:

- Capturing a payment against a share order requires the request body to carry `expected_market_version` matching the current `version` of the order's parent `Market`. If the market's version has advanced since the client last observed it — for example because another writer activated, paused, or resumed an order in the same market and so mutated `allocated_bps`, or an ops run swept expirations — the capture is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412). The client's view of available capacity is stale and must not be allowed to drive an activation.
- Accepting a lead assignment requires the request body to carry `expected_lead_version` matching the current `version` of the lead the assignment is for. If the lead's version has advanced — for example because an ops sweep expired the offer and rerouted the lead, or another candidate accepted first — the accept is rejected with `ERR_STALE_LEAD_VERSION` (HTTP 412).

Endpoints not listed above do not take a version field; submissions that include one on a non-OCC endpoint ignore it.

### 2.8. Validation Ordering

Every endpoint applies its checks in a fixed priority order so that when multiple conditions fail, the surfaced error is deterministic:

1. Authentication — `X-User-Role` and `X-User-ID` present and well-formed (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted for the endpoint (`ERR_UNAUTHORIZED`).
3. Existence — every path `id` resolves to a resource of the expected type, checked left-to-right (`ERR_NOT_FOUND` variants; see §2.9).
4. State — target resource in a state permitting this operation (`ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_AGENT_SUSPENDED`, `ERR_TEAM_DISSOLVED`, `ERR_MARKET_SUSPENDED`).
5. License-state compatibility (`ERR_LICENSE_STATE_MISMATCH`) on share purchase, offer acceptance, and manual assignment.
6. Listing display-rule compatibility (`ERR_LISTING_DISPLAY_VIOLATION`) on listing ingestion and listing review.
7. Share capacity (`ERR_SHARE_CAPACITY_EXCEEDED`) on share purchase, payment capture, and resume.
8. Offer TTL (`ERR_OFFER_EXPIRED`) on offer acceptance.
9. Duplicate-lead guard (`ERR_DUPLICATE_LEAD`) on lead intake and live-connection request.
10. Team membership integrity (`ERR_TEAM_MEMBERSHIP_INVALID`) on membership creation, team share purchase, and manual assignment.
11. Payment amount exactness (`ERR_PAYMENT_AMOUNT_MISMATCH`) on payment capture.
12. Credit-claim eligibility (`ERR_CREDIT_CLAIM_INVALID`) on claim submission.
13. Candidate pool exhaustion (`ERR_CANDIDATE_POOL_EXHAUSTED`) on reroute paths during lead intake and the ops sweep.
14. Stale market version (`ERR_STALE_MARKET_VERSION`) on payment capture.
15. Stale lead version (`ERR_STALE_LEAD_VERSION`) on offer acceptance.

A request that would fail at a higher-priority step surfaces that error, even if it would also fail at a lower-priority step.

### 2.9. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers, the system validates them sequentially, left-to-right. The request is rejected with the `404 Not Found` error corresponding to the first identifier that does not resolve to an existing resource of the expected type. Per-entity not-found errors are: `ERR_MARKET_NOT_FOUND`, `ERR_BROKERAGE_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_TEAM_MEMBERSHIP_NOT_FOUND`, `ERR_SHARE_ORDER_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_LIVE_CONNECTION_NOT_FOUND`, `ERR_CREDIT_CLAIM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, and `ERR_DISPUTE_NOT_FOUND`.

### 2.10. Common Resource Properties

Most primary resources — `Market`, `Brokerage`, `Agent`, `TeamAccount`, `TeamMembership`, `ShareOrder`, `Lead`, `LeadAssignment`, `LiveConnection`, `CreditClaim`, `Listing`, and `Dispute` — carry a standard set of system-managed fields:

- `id` (string): a server-generated UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification. Any mutation to the resource refreshes this field.
- `version` (integer): a system-managed counter that increments on every mutation, used by optimistic concurrency control.

The remaining resources — `Payment`, `CallRecording`, `Rating`, `PerformanceSnapshot`, and `OpsRun` — are append-only and carry only `id` and `created_at`. They do not have `updated_at` or `version` fields.

### 2.11. Monetary Precision and Scoring

All monetary values are stored and transmitted as integer cents. Internally, all monetary computation uses integer arithmetic: per-lead prices use floor division when a percentage adjustment is applied, and credits computed as half of a charge round down to the nearest cent. There are no decimal-money representations in any API body.

Performance scores are integer values in the range 0 to 100, rounded half-up from a weighted sum of components (see §3.7). Both the rolling and the windowed variants share this precision contract.

### 2.12. Cascade and Counter Discipline

Several operations have cascading side effects on entities beyond the one being directly mutated. Pausing or completing a share order decrements its market's `allocated_bps`; capturing a payment increments it. Expiring an unanswered offer increments each candidate agent's `offers_expired` and recomputes their `rolling_score`. Cancelling a routed lead credits the charged order and reverses the per-agent allocation that the team charge split had previously awarded. Recording a live-connection outcome either creates a stored `CallRecording` or increments the agent's `connections_missed`. Approving a credit claim mutates the order's `credits_cents` and `leads_credited` and propagates a per-agent credit. Every such cascade is described alongside the workflow that triggers it in §3; none are optional.

## 3. Business Logic & Workflows

### 3.1. Markets, Brokerages, and Listing Ingestion

A `MarketplaceOps` operator establishes the platform's geography by creating `Market` records, one per zip code. Each market is identified by a `zip_code` (exactly five digits, unique across all markets), a `state_code` (two uppercase letters governing license eligibility), a `participation_agreement` (one of `IDX_FULL`, `IDX_LIMITED`, or `NON_PARTICIPATING`, defaulting to `IDX_FULL` when not supplied), and a `base_lead_price_cents` (the per-lead price in cents at demand tier 1, strictly positive). A market's `market_status` begins at `OPEN`. An operator may suspend a market — while `SUSPENDED`, the market accepts no new share orders, no new leads, no new team accounts, and no new listings (any such attempt is rejected with `ERR_MARKET_SUSPENDED`, HTTP 409) — and may later reopen it. Payment capture against an existing order in a suspended market is not blocked by the suspension. The market's derived `allocated_bps`, `available_bps`, and `current_unit_price_cents` (the unit price that would be quoted for a hypothetical 100-basis-point purchase against the current allocation) are recomputed whenever allocation changes.

Brokerages are onboarded separately: an operator creates a `Brokerage` with a `legal_name` and a `primary_state` (two-letter home state). The brokerage's `brokerage_status` begins at `ACTIVE`. The `primary_state` matters for the display-rule check described below: a market operating under `IDX_LIMITED` admits broker-direct listings only when the listing brokerage's `primary_state` equals the market's `state_code`.

Listing ingestion is performed by a `BrokerageUser` (or by an operator on the brokerage's behalf). The submitter provides an `external_ref` (the source-system reference, unique within the combination of the target `market_id` and the `source_feed`), a `source_feed` of either `MLS` or `BROKER_DIRECT`, the `brokerage_id` of the listing brokerage, and the `listing_agent_id` of the listing-side agent. The new listing lands in `PENDING_REVIEW` and is not routable for lead intake until approved.

Review is a moderation act by `MarketplaceOps`. The reviewer supplies an `outcome` of `APPROVE` or `REJECT` and an optional `compliance_note`. Approval requires the listing's `listing_status` to be `PENDING_REVIEW` and is gated by the market's display-rule check: if the market's `participation_agreement` is `IDX_FULL`, any feed is allowed; if it is `IDX_LIMITED`, the listing is allowed only when its `source_feed` is `MLS` or when the listing brokerage's `primary_state` matches the market's `state_code`; if it is `NON_PARTICIPATING`, no listings are allowed at all and the review must reject. An approval attempt that violates the display rule is rejected with `ERR_LISTING_DISPLAY_VIOLATION` (HTTP 422); the same check applies at ingestion time as a defensive gate. Rejection moves the listing to `REJECTED` and records the `compliance_note`. An `ACTIVE` listing may later be withdrawn by an operator (or by a dispute resolution of `REMOVE`); withdrawal moves it to `WITHDRAWN`, records the `compliance_note`, and rejects any future lead intake that references the listing, while existing leads are unaffected. Every lead intake references a listing: the referenced listing must exist and must be in `ACTIVE` status — intake against a listing in any other status (`PENDING_REVIEW`, `REJECTED`, or `WITHDRAWN`) is rejected.

### 3.2. Agents, Teams, and Memberships

Agent onboarding is an operator act. The operator registers an `Agent` with a `full_name`, a login `email` (unique across all agents), a `license_number` (also unique), the `license_state` in which the license is issued, and the `brokerage_id` of the employing brokerage. New agents start in `ACTIVE` status with `performance_tier` of `UNRATED` and an `official_score` of zero. Their counters — `offers_received`, `offers_accepted`, `offers_expired`, `response_seconds_sum`, `leads_converted`, `leads_closed_lost`, `connections_missed`, `rating_sum`, `rating_count` — all start at zero, and their `rolling_score` is recomputed on every scoring event from these all-time counters.

An agent's lifecycle has three states. `ACTIVE` is the working state. An operator may suspend an agent — moving them to `SUSPENDED` — which excludes them from selector pools and prevents them from accepting any outstanding offers, though the offers themselves remain in place. Suspension is also applied automatically when the agent accumulates three consecutive `NO_ANSWER` connection outcomes. An operator may later unsuspend, returning the agent to `ACTIVE`. An agent may also deactivate themselves, which is terminal: the move to `DEACTIVATED` requires that the agent hold no `ACTIVE` or `PAUSED` share orders and no `ACTIVE` team memberships, and once deactivated the agent is permanently excluded. Attempting to act as a suspended or deactivated agent is rejected with `ERR_AGENT_SUSPENDED` (HTTP 409).

Team accounts let a team lead buy share on behalf of a group. An `Agent` creates a `TeamAccount` by supplying a `team_name`, their own id as `lead_agent_id` (the caller must be the named lead), and the `market_id` the team is scoped to — teams are bound to exactly one market. An optional `distribution_mode` of `WEIGHTED_DEFICIT` or `MANUAL` controls how team-routed leads pick a member; when not supplied it defaults to `WEIGHTED_DEFICIT`. The team's `team_status` begins at `ACTIVE`.

The team lead adds members by creating `TeamMembership` records that name the `team_id`, the `agent_id`, and an `allocation_weight` (a positive integer of at least 1). At most one membership with `membership_status` of `ACTIVE` may exist for a given combination of team and agent; the memberships of a dissolved team are invalid; and the membership must be consistent with the team's market scope — violations are rejected with `ERR_TEAM_MEMBERSHIP_INVALID` (HTTP 422). Each membership carries two counters: `leads_assigned`, the number of team leads routed to this member, and `allocated_charge_cents`, this member's cumulative share of finalized team-order charges under the waterfall split described in §3.6. The team lead may remove a member, which transitions that membership to `REMOVED`. Dissolving a team requires that the team hold no `ACTIVE` or `PAUSED` share orders, and the act transitions every membership to `REMOVED` and the team's `team_status` to `DISSOLVED`. Any subsequent attempt to operate against a dissolved team is rejected with `ERR_TEAM_DISSOLVED` (HTTP 409).

### 3.3. Share Purchase: Quote, Deposit, Activation

An `Agent` buys share by creating a `ShareOrder` against a `market_id`, naming themselves (or, for a team order, the team's lead) as `buyer_agent_id`, specifying the requested `share_bps` (between 1 and 10000), and a `duration_days` campaign length (between 1 and 90). For team orders the buyer also supplies `team_id`; for solo orders `team_id` is null. The new order lands in `PENDING_PAYMENT`. Purchase enforces the license check — the buyer's `license_state` must match the market's `state_code` — and a team purchase additionally enforces the team-membership integrity check.

At purchase time the platform quotes a price using the demand-tier calculation. The quote evaluates the market's current `allocated_bps` against the total capacity of 10000 basis points: if the allocated share is less than 50 percent of capacity the demand `tier` is 1, otherwise if it is less than 80 percent the `tier` is 2, otherwise the `tier` is 3. The quote then applies a volume discount based on the requested `share_bps`: no discount below 2500 basis points, a 5 percent discount when the request is at least 2500 but less than 5000 basis points, and a 10 percent discount at 5000 basis points or more. The `unit_price_cents` is the market's `base_lead_price_cents` multiplied by one plus 25 percent per tier step above tier 1, then multiplied by one minus the volume discount, with the final value floored to integer cents. The `deposit_cents` required at activation is the `tier` multiplied by 100, multiplied by the `unit_price_cents`. All three derived values — `tier`, `unit_price_cents`, `deposit_cents` — are written onto the order at creation. The same calculation backs the price-quote capability: a caller may ask what `tier`, `unit_price_cents`, and `deposit_cents` would apply for a hypothetical `share_bps` against the market's current allocation, and the response contains exactly those three integers.

Crucially, the quote is demand-sensitive: if another buyer activates a large order between quote and payment, the tier that applies at activation may differ from what was quoted. The locked values on the order reflect the purchase instant; subsequent market changes do not reopen them. The market's `current_unit_price_cents` field exposes what the unit price would be for a fresh 100-basis-point purchase right now, and moves as allocation changes.

Activation is a payment capture. The buyer posts a payment against the order with `amount_cents` exactly equal to the order's `deposit_cents` and an `outcome` of either `SUCCEEDED` or `DECLINED`. The recorded `Payment` carries the `share_order_id`, the captured `amount_cents`, the echoed `outcome`, and a `payment_status` that mirrors the outcome and is immutable once recorded. The capture is guarded by OCC on the parent market: the body must carry `expected_market_version` matching the market's current `version`, and a mismatch is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412). A `DECLINED` outcome transitions the order to `PAYMENT_FAILED` and leaves the market's counters untouched. A `SUCCEEDED` outcome activates the order, subject to a re-check that the market's `available_bps` at that instant is at least the order's `share_bps` — otherwise the capture is rejected with `ERR_SHARE_CAPACITY_EXCEEDED`. The amount must equal the deposit exactly, and the order must not already have a `SUCCEEDED` payment on file; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). On a successful activation the order's `paid_cents` becomes the deposit, `activated_at` is set to now, and `ends_at` is computed as `activated_at` plus `duration_days`; the market's `allocated_bps` increases by `share_bps`, its `available_bps` and `current_unit_price_cents` are recomputed, and its `version` increments.

Once `ACTIVE`, an order accrues `leads_received` as leads are routed to it, `leads_charged` as those leads finalize, and `charged_cents` as the corresponding charge is posted. `credits_cents` accumulates any credits granted via claims or operator cancels. The buyer may pause an `ACTIVE` order, which releases its share back to the market — `allocated_bps` decreases, `current_unit_price_cents` is recomputed, and the market's `version` increments — and may later resume a `PAUSED` order, which re-checks capacity against the market's `available_bps` at the resume instant. A paused order may be cancelled outright, moving it to `CANCELLED` with no further market-counter change (the share was already released at pause).

While an order is `ACTIVE`, the buyer may also post settlement payments against any outstanding balance: the required `amount_cents` for settlement is the order's `charged_cents` minus its `paid_cents`, and must be positive. Settlement does not change the order's status — it only advances `paid_cents`. An order that reaches the end of its campaign window is swept by the ops run: if `ends_at` has been reached and the order is settled (its `paid_cents` is at least `charged_cents` minus `credits_cents`), it transitions to `COMPLETED` and its `completed_at` is set; if instead there is a balance due at expiry, the order transitions to `CANCELLED`. Either way its share is released from the market.

### 3.4. Lead Intake and Routing

Lead intake is initiated either by an `Agent` (for example a listing agent entering a consumer inquiry) or by an operator. The submitter provides the `market_id`, the `listing_id` of the listing the consumer inquired about, the `consumer_key` (a normalized consumer identity such as an email hash), and the `listing_agent_id` of the listing-side agent recorded at intake. The new lead's `lead_status` begins at `NEW`.

Before routing, two duplicate guards fire. The window guard rejects the intake when the same `consumer_key` already has a lead in this market within the last 30 days (counting only anchor leads that are not themselves `REJECTED_DUPLICATE`). The same-agent guard rejects the intake when a lead with the same `consumer_key` and the same `listing_agent_id` already exists; the same-agent guard has no time window and applies regardless of how old the anchor lead is. A rejection on either ground moves the new lead to `REJECTED_DUPLICATE` with `duplicate_of_lead_id` set to the anchor lead, and the intake is rejected with `ERR_DUPLICATE_LEAD` (HTTP 422).

When no duplicate fires, routing selects a winning share order from the market's `ACTIVE` orders using a deterministic share-proportional walk. The eligible orders are sorted by `share_bps` descending, breaking ties by `activated_at` ascending. A routing key is derived by hashing the lead's `consumer_key` modulo the total `share_bps` of the eligible orders. Walking the sorted list and accumulating each order's `share_bps`, the first order whose cumulative total reaches or exceeds the routing key wins. The lead's `share_order_id` is set to the winning order, its `team_id` is set to the winning order's `team_id` (or null for a solo order), the winning order's `leads_received` counter is incremented, the lead's `routing_attempts` becomes 1, and the lead moves to `ROUTED`.

A `LeadAssignment` is then created with `assignment_status` of `OFFERED`, carrying the `lead_id`, the winning `share_order_id` copied from the lead, and a `candidate_agent_ids` array of exactly three agent ids drawn from the candidate selector. The selector considers only agents whose `agent_status` is `ACTIVE`, whose `performance_tier` is not `INELIGIBLE`, whose `license_state` matches the market's `state_code`, and who are covered by the winning order — for a solo order, the candidate must be the order's `buyer_agent_id`; for a team order, the candidate must hold an `ACTIVE` `TeamMembership` in the order's team. Candidates are ranked by `performance_tier` (HIGH above STANDARD above LOW above UNRATED), then by `rolling_score` descending, then by `created_at` ascending, and the top three are taken. The assignment's `offered_at` is now and its `expires_at` is `offered_at` plus 300 seconds.

If the eligible candidate pool is empty — no order in the market can be charged for a lead nobody can receive — the lead moves directly to `UNASSIGNED` with a `routing_note` of "pool empty"; no share order's counters are touched and no charge is posted.

### 3.5. Offer Acceptance, Expiry, and Manual Assignment

An offer is accepted when one of the candidates accepts it. Acceptance is guarded by OCC on the lead: the body carries `expected_lead_version` matching the lead's current `version`, and a mismatch is rejected with `ERR_STALE_LEAD_VERSION` (HTTP 412). The acting agent must be one of the assignment's `candidate_agent_ids` — otherwise `ERR_NOT_A_CANDIDATE` (HTTP 422) — and the assignment's `assignment_status` must still be `OFFERED` with `now` strictly less than its `expires_at` — otherwise `ERR_OFFER_EXPIRED` (HTTP 422). The acting agent's license state must also match the market. On a successful accept, the assignment moves to `ACCEPTED` with `accepted_by_agent_id` and `accepted_at` recorded; the lead moves to `ASSIGNED` with `accepted_agent_id` set to the acceptor and `assigned_at` set to now; the accepting agent's `offers_accepted` increments by one; their `response_seconds_sum` increases by the number of seconds between `offered_at` and `accepted_at`; and their `rolling_score` is recomputed. If the winning order was a team order, the team-member selector picks the specific member whose `leads_assigned` counter increments: among the team's `ACTIVE` memberships, each member's deficit is computed as their `leads_assigned` divided by their `allocation_weight`, the memberships are sorted by deficit ascending (lower deficit means the member is more owed), breaking ties by `allocation_weight` descending and then `created_at` ascending, and the first member wins.

Offers do not sit forever. When the ops sweep encounters an assignment that is still `OFFERED` with `expires_at` at or before now, the assignment moves to `EXPIRED` and each of its prior candidates has their `offers_expired` incremented and their `rolling_score` recomputed. The sweep then attempts to reroute the lead: the reroute pool excludes all prior candidates across every earlier attempt, and if the pool is non-empty a fresh `LeadAssignment` is created in `OFFERED` with a new `candidate_agent_ids` triple, the lead's `routing_attempts` increments by one, and the new offer's `expires_at` is now plus 300 seconds. No candidate may repeat across reroute attempts; if the reroute pool is empty the lead moves to `UNASSIGNED` with `routing_note` of "pool exhausted", and the previously charged amount is credited back to the share order — the order's `credits_cents` increases by the charged amount for this lead and each affected agent's allocated share is reversed. Attempting to construct an offer with no remaining candidates surfaces `ERR_CANDIDATE_POOL_EXHAUSTED` (HTTP 422).

Two operator-side overrides exist. An operator may cancel a `ROUTED` lead outright, which moves the open assignment to `CANCELLED`, the lead to `UNASSIGNED`, and applies the same credit settlement as the sweep path — the charged order's `credits_cents` increases by the charged amount and per-agent debits reverse. An operator may also manually assign a lead: a lead in `ROUTED` or `UNASSIGNED` status may be moved to `ASSIGNED` by specifying an `accepted_agent_id` directly. The assignee must be eligible per the same selector criteria (license state matches the market, agent is `ACTIVE`, tier is not `INELIGIBLE`) and must be covered by an `ACTIVE` share order in this market, either their own or a team order they belong to; if no covering order exists the assignment is rejected with `ERR_NO_ELIGIBLE_CANDIDATES` (HTTP 422). A successful manual assignment sets `assigned_at`, applies the same counter increments as an acceptance (including the team-member selection when the covering order is a team order), and recomputes `rolling_score`.

### 3.6. Charge Finalization and Team Splits

When a routed lead reaches a finalized, chargeable state the platform posts a charge against the order that won the routing. The order's `charged_cents` accumulates the posted amount and its `leads_charged` counter increments by one. For solo orders the full charge attaches to the buyer agent's account. For team orders the charge is distributed across the team's `ACTIVE` memberships in proportion to their `allocation_weight` using a waterfall allocation: the platform computes the total of the active members' `allocation_weight` values, then computes each member's raw share as the floor of the charge multiplied by their `allocation_weight` divided by the total weight, then reconciles the remainder one cent at a time to members in order of `allocation_weight` descending, breaking ties by `created_at` ascending. Each member's `allocated_charge_cents` accumulates their awarded share. The split sums exactly to the charge.

### 3.7. Performance Scoring

Every scoring event — an offer received, an offer acceptance, an offer expiry, a close, a no-answer, a consumer rating — recomputes two variants of the agent's performance score. The rolling variant uses all-time counters; the official variant is computed only at ops-run time and considers events inside the window from the previous run's `run_at` (exclusive) up to and including this run's `run_at`. The official variant drives the agent's `performance_tier`: the tier changes only when an ops run recomputes the official score, and a scoring event that recomputes the rolling score leaves the tier untouched. The rolling variant is the live value used for selector tie-breaks and tier display.

The score formula combines five components with fixed weights. The acceptance component is the ratio of `offers_accepted` to `offers_received`, expressed as a percentage and weighted at 25 percent. The conversion component is the ratio of `leads_converted` to the total of `leads_converted` plus `leads_closed_lost` (treating a zero denominator as one to avoid division by zero), expressed as a percentage and weighted at 20 percent. The response component starts from 100 and subtracts the agent's average response seconds — `response_seconds_sum` divided by `offers_accepted`, again treating a zero denominator as one — divided by 30, floored at zero; this component is weighted at 20 percent and yields 100 for an instant response and 0 at an average of 50 minutes or slower. The connection component is 100 multiplied by one minus the ratio of `connections_missed` to `offers_accepted` (zero denominator treated as one), weighted at 20 percent. The rating component is the agent's average consumer rating — `rating_sum` divided by `rating_count` (zero denominator treated as one) — multiplied by 20 to put it on a 0-to-100 scale, weighted at 15 percent. The weighted sum is rounded half-up to an integer in the range 0 to 100.

When an agent has received no offers at all (`offers_received` is zero) the score is reported as 0 and the agent's `performance_tier` is `UNRATED`. Otherwise the tier classification derives from the official score: an official score of 80 or above is `HIGH`, 60 to 79 is `STANDARD`, 40 to 59 is `LOW`, and below 40 is `INELIGIBLE` — the floor below which an agent is excluded from routing eligibility.

At every ops run the sweep snapshots every `ACTIVE` agent into a `PerformanceSnapshot` record carrying the `agent_id`, the `ops_run_seq` of the producing run, the `window_start_at` (the previous run's `run_at`, exclusive lower bound), the `window_end_at` (this run's `run_at`, inclusive upper bound), and the `windowed_score` — the official variant computed against events in that window. `PerformanceSnapshot` records are immutable once written and exist only in the `FINAL` state.

### 3.8. Live Connections and Call Recording

Once a lead is `ASSIGNED`, the assigned agent may request a live transfer of the consumer. The caller supplies the `lead_id`, the `consumer_key` (which must match the lead's recorded consumer key), and the `listing_agent_id` of the listing-side agent (used by the duplicate-attribution guard). The new `LiveConnection` begins in `REQUESTED`. The duplicate guards from lead intake apply here as well — including the same-agent guard, which has no time window: if the same consumer already has a lead in this market within the 30-day window, or already has a lead with the same `listing_agent_id`, the connection moves to `REJECTED_DUPLICATE` with `duplicate_of_lead_id` set to the anchor lead. Otherwise the connection moves to `BRIDGING`, its `agent_id` is set to the lead's `accepted_agent_id`, and its `share_order_id` is set to the lead's `share_order_id`. The caller must be the lead's accepted agent and the lead must be `ASSIGNED`; otherwise the request is rejected.

The bridge outcome is recorded by the agent with a `duration_seconds` and a `consent_given` flag. Recording requires the connection's `connection_status` to be `BRIDGING`; an attempt against any other `connection_status` is rejected with `ERR_CONNECTION_NOT_BRIDGING` (HTTP 409). When `consent_given` is true and `duration_seconds` is at least 1, the bridge succeeds: a `CallRecording` is created in `STORED` status attached to the connection via `live_connection_id`, the connection's `recording_retention_expires_at` is set to now plus 90 days, the connection moves to `COMPLETED`, and the lead moves to `LIVE_CONNECTED`. When `duration_seconds` is zero the bridge reports no answer: the connection moves to `NO_ANSWER`, no recording is created, the agent's `connections_missed` increments by one, and their `rolling_score` is recomputed. When `consent_given` is false, the bridge cannot legally store a recording: the connection moves to `DROPPED`, no recording is created, and the lead remains in `ASSIGNED` so the agent may retry with a fresh connection. `DROPPED` is terminal for the connection attempt but not for the lead.

Recordings are purged by the ops sweep: any recording whose `recording_status` is still `STORED` and whose `recording_retention_expires_at` is in the past moves to `PURGED`. Purging deletes the audio data but retains the recording's metadata for audit.

### 3.9. Closes, Ratings, and Credit Claims

The assigned agent closes a lead by reporting an `outcome` of `CONVERTED` or `LOST`. Closing is permitted from either `ASSIGNED` or `LIVE_CONNECTED` status, and only by the lead's `accepted_agent_id`. A `CONVERTED` outcome moves the lead to `CLOSED_CONVERTED` and increments the agent's `leads_converted`; a `LOST` outcome moves the lead to `CLOSED_LOST` and increments `leads_closed_lost`. Either way the agent's `rolling_score` is recomputed.

Consumers rate their interactions through an operator-mediated submission that names the `lead_id`, a `score` between 1 and 5, and an optional free-text `comment`. A score outside the 1-to-5 range is rejected with `ERR_RATING_OUT_OF_RANGE` (HTTP 422). Ratings may be submitted for leads in `ASSIGNED`, `LIVE_CONNECTED`, `CLOSED_CONVERTED`, or `CLOSED_LOST` status. Each accepted rating increments the agent's `rating_sum` by the score and `rating_count` by one, then recomputes `rolling_score`.

An agent who believes a charged lead was invalid or a duplicate may file a `CreditClaim`. The claimant supplies the `lead_id`, a `claim_type` of `INVALID` or `DUPLICATE`, and a free-text `reason`. The claim is valid only when the referenced lead is in a finalized chargeable status, has not already been credited by another approved claim, and the claimant is the lead's `accepted_agent_id` — violations are rejected with `ERR_CREDIT_CLAIM_INVALID` (HTTP 422). The claim's `claimant_agent_id` is set from the acting user. The new claim lands with `claim_status` of `SUBMITTED`.

An operator resolves the claim by approving or rejecting it; the claim's `claim_status` must still be `SUBMITTED`. An approve resolution moves the claim to `APPROVED` and computes `credit_cents`: when the `claim_type` is `INVALID` the credit equals the lead's finalized charge; when the `claim_type` is `DUPLICATE` the credit is half of the finalized charge, floored to integer cents. The order's `credits_cents` increases by the credit, its `leads_credited` increments by one, and the per-agent allocation awarded at finalize time is reversed: for team orders each affected agent's share is credited, for solo orders the full credit attaches to the claimant agent. A reject resolution moves the claim to `REJECTED`, sets `credit_cents` to zero, and leaves the ledgers untouched. Either resolution is terminal for the claim.

### 3.10. Disputes

A `BrokerageUser` may file a `Dispute` when their brokerage disagrees with how the marketplace is treating their listings or their agents' attribution. The filer supplies a `dispute_type` of `LISTING_DISPLAY` or `LEAD_ATTRIBUTION`, the `brokerage_id` (which must equal the acting user's brokerage), and free-text `evidence`. For a `LISTING_DISPLAY` dispute the filer must also supply a `listing_id`; for a `LEAD_ATTRIBUTION` dispute the filer must supply both a `lead_id` and a `requested_agent_id` naming the agent attribution should move to. A submission missing the required reference for its type is rejected with `ERR_DISPUTE_TYPE_MISMATCH` (HTTP 422). New disputes land with `dispute_status` of `OPEN`.

An operator resolves a dispute by naming a `resolution`. For `LISTING_DISPLAY` the valid resolutions are `KEEP` and `REMOVE`; for `LEAD_ATTRIBUTION` they are `REASSIGN` and `KEEP`. A `REMOVE` resolution on a listing-display dispute withdraws the listing (transitioning it to `WITHDRAWN` and recording a `compliance_note`). A `REASSIGN` resolution on a lead-attribution dispute updates the lead's `listing_agent_id` to the `requested_agent_id`. The dispute moves to `RESOLVED` with `resolved_at` set to now. An operator may also reject the dispute outright, which moves it to `REJECTED` with `resolution` of `REJECTED_DISPUTE` and leaves the underlying listing or lead untouched. A resolution value invalid for the dispute's type is rejected with `ERR_DISPUTE_TYPE_MISMATCH`.

### 3.11. The Ops Sweep

The ops-run capability is the platform's only scheduled-action surface. When invoked it performs the following steps in order, recording per-step counts into the run's `sweep_counts`:

1. Expire every `LeadAssignment` still in `OFFERED` whose `expires_at` is at or before now, moving each to `EXPIRED` and incrementing each of its prior candidates' `offers_expired` (recomputing their `rolling_score`).
2. For each newly expired assignment, attempt to reroute the lead: build the reroute pool excluding every prior candidate, and either issue a fresh offer (new `LeadAssignment` in `OFFERED`, `routing_attempts` incremented, `expires_at` of now plus 300 seconds) or, when the pool is empty, move the lead to `UNASSIGNED` with `routing_note` of "pool exhausted" and credit the previously charged amount back to the share order.
3. Expire every `ShareOrder` in `ACTIVE` whose `ends_at` has been reached: orders that are settled (their `paid_cents` is at least `charged_cents` minus `credits_cents`) move to `COMPLETED` with `completed_at` set; orders with a balance due move to `CANCELLED`. Either way the order's `share_bps` is released from the market and the market's `current_unit_price_cents` and `version` are updated.
4. Purge every `CallRecording` still `STORED` whose `recording_retention_expires_at` is in the past, moving each to `PURGED`.
5. Snapshot every `ACTIVE` agent into a `PerformanceSnapshot` with the official-variant score for the window between the previous run's `run_at` and this run's `run_at`.

The run itself is persisted as an `OpsRun` record carrying the run's `seq` (a monotonically increasing sequence number starting at 1), the `run_at` instant from the logical clock, and the `sweep_counts` object.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, or that simply read one, return `200 OK`. The table below summarizes the surface; readers should refer back to §3 narratives for the full request and response semantics of each call.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | MarketplaceOps, PlatformAdmin |
| POST | `/ops-runs` | Execute the ops sweep | MarketplaceOps, PlatformAdmin |
| POST | `/markets` | Create a zip-code market | MarketplaceOps, PlatformAdmin |
| GET | `/markets` | List markets with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}` | Get market detail | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}/price-quote` | Quote tier, unit price, and deposit for a hypothetical share | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/markets/{id}/suspend` | Suspend market | MarketplaceOps, PlatformAdmin |
| POST | `/markets/{id}/reopen` | Reopen suspended market | MarketplaceOps, PlatformAdmin |
| POST | `/brokerages` | Create brokerage | MarketplaceOps, PlatformAdmin |
| GET | `/brokerages/{id}` | Get brokerage | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/agents` | Register agent | MarketplaceOps, PlatformAdmin |
| GET | `/agents` | List agents with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}` | Get agent profile | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/agents/{id}/suspend` | Suspend agent | MarketplaceOps, PlatformAdmin |
| POST | `/agents/{id}/unsuspend` | Unsuspend agent | MarketplaceOps, PlatformAdmin |
| POST | `/agents/{id}/deactivate` | Deactivate self (terminal) | Agent |
| POST | `/team-accounts` | Create team account in a market | Agent |
| GET | `/team-accounts/{id}` | Get team account | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/team-accounts/{id}/dissolve` | Dissolve team | Agent |
| GET | `/team-accounts/{id}/memberships` | List memberships of team | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/team-memberships` | Add member to team | Agent |
| GET | `/team-memberships` | List memberships filtered by team or agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/team-memberships/{id}/remove` | Remove member from team | Agent |
| POST | `/share-orders` | Create share order and quote deposit | Agent |
| GET | `/share-orders` | List share orders with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/share-orders/{id}` | Get share order | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/share-orders/{id}/payments` | Capture activation deposit or settle outstanding balance | Agent |
| POST | `/share-orders/{id}/pause` | Pause active order | Agent |
| POST | `/share-orders/{id}/resume` | Resume paused order | Agent |
| POST | `/share-orders/{id}/cancel` | Cancel paused order | Agent |
| GET | `/share-orders/{id}/payments` | List payments for order | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/leads` | Ingest lead and route | Agent, MarketplaceOps, PlatformAdmin |
| GET | `/leads` | List leads with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}` | Get lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/leads/{id}/assign` | Manual assignment override | MarketplaceOps, PlatformAdmin |
| POST | `/leads/{id}/close` | Close assigned or live-connected lead | Agent |
| POST | `/leads/{id}/cancel` | Operator-cancel a routed lead | MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/assignments` | List assignments for lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/ratings` | List ratings for lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/live-connections` | List live connections for lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/credit-claims` | List credit claims for lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/lead-assignments/{id}` | Get assignment | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/lead-assignments/{id}/accept` | Accept offered lead | Agent |
| POST | `/live-connections` | Request live transfer of consumer | Agent |
| GET | `/live-connections/{id}` | Get connection | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/live-connections/{id}/record` | Record bridge outcome | Agent |
| GET | `/live-connections/{id}/recordings` | List call recordings for connection | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/ratings` | Submit consumer rating | MarketplaceOps, PlatformAdmin |
| POST | `/credit-claims` | Submit refund or credit claim | Agent |
| GET | `/credit-claims/{id}` | Get credit claim | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/credit-claims/{id}/resolve` | Approve or reject claim | MarketplaceOps, PlatformAdmin |
| POST | `/listings` | Ingest listing from MLS or broker-direct feed | BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/listings` | List listings with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/listings/{id}` | Get listing | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/listings/{id}/review` | Approve or reject a pending listing | MarketplaceOps, PlatformAdmin |
| POST | `/listings/{id}/withdraw` | Withdraw an active listing | MarketplaceOps, PlatformAdmin |
| POST | `/disputes` | File listing-display or lead-attribution dispute | BrokerageUser |
| GET | `/disputes` | List disputes with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/disputes/{id}` | Get dispute | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| POST | `/disputes/{id}/resolve` | Resolve dispute | MarketplaceOps, PlatformAdmin |
| GET | `/performance-snapshots` | List performance snapshots with filters and pagination | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/team-accounts` | List team accounts led by this agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/team-memberships` | List memberships of this agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/share-orders` | List share orders bought by this agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/performance-snapshots` | List performance snapshots of this agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/listings` | List listings where this agent is the listing agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/agents/{id}/credit-claims` | List credit claims filed by this agent | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/team-accounts/{id}/share-orders` | List share orders of this team | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/share-orders/{id}/leads` | List leads routed to this order | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/share-orders/{id}/live-connections` | List live connections attributed to this order | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/listings/{id}/leads` | List leads inquiring on this listing | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/listings/{id}/disputes` | List disputes referencing this listing | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/disputes` | List disputes referencing this lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/duplicates` | List leads marked duplicate of this lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/leads/{id}/duplicate-connections` | List live connections rejected as duplicate of this lead | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/brokerages/{id}/agents` | List agents employed by this brokerage | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/brokerages/{id}/listings` | List listings of this brokerage | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/brokerages/{id}/disputes` | List disputes filed by this brokerage | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}/share-orders` | List share orders in this market | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}/team-accounts` | List team accounts in this market | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}/leads` | List leads in this market | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/markets/{id}/listings` | List listings in this market | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/lead-assignments` | List lead assignments with filters | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |
| GET | `/live-connections` | List live connections with filters | Agent, BrokerageUser, MarketplaceOps, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MARKET_NOT_FOUND` | 404 |
| `ERR_BROKERAGE_NOT_FOUND` | 404 |
| `ERR_AGENT_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_TEAM_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_SHARE_ORDER_NOT_FOUND` | 404 |
| `ERR_LEAD_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_LIVE_CONNECTION_NOT_FOUND` | 404 |
| `ERR_CREDIT_CLAIM_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_MARKET_SUSPENDED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_AGENT_SUSPENDED` | 409 |
| `ERR_TEAM_DISSOLVED` | 409 |
| `ERR_STALE_MARKET_VERSION` | 412 |
| `ERR_STALE_LEAD_VERSION` | 412 |
| `ERR_LICENSE_STATE_MISMATCH` | 422 |
| `ERR_LISTING_DISPLAY_VIOLATION` | 422 |
| `ERR_SHARE_CAPACITY_EXCEEDED` | 422 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_NOT_A_CANDIDATE` | 422 |
| `ERR_DUPLICATE_LEAD` | 422 |
| `ERR_TEAM_MEMBERSHIP_INVALID` | 422 |
| `ERR_NOT_TEAM_LEAD` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_CREDIT_CLAIM_INVALID` | 422 |
| `ERR_NO_ELIGIBLE_CANDIDATES` | 422 |
| `ERR_RATING_OUT_OF_RANGE` | 422 |
| `ERR_CONNECTION_NOT_BRIDGING` | 409 |
| `ERR_DISPUTE_TYPE_MISMATCH` | 422 |
