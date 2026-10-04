# Spectrum License Auction API — Product Requirements Document

## 1. Introduction

Spectrum is a finite public resource, and allocating it fairly demands a process that is at once competitive, auditable, and unforgiving of manipulation. This document specifies the Spectrum License Auction API: a system that administers clock-style spectrum auctions in the manner of a national telecommunications regulator, from the first stroke of band planning through the grant of licenses and the years of obligations that follow. The platform covers the full arc of the auction lifecycle — defining license areas and spectrum blocks, qualifying applicants and their bidding credits, running the round-by-round clock auction with its activity rules and tiered price increments, assigning specific frequency blocks to winners, collecting settlement payments, and then policing the buildout milestones, secondary-market transfers, leases, and renewals that determine whether the spectrum actually reaches the public. Incumbent occupants of the band are first-class participants as well: they are notified, relocated on coordinated schedules, and cleared before new licensees may activate, with their relocation costs shared across the new licensees of the affected area.

Two commitments shape every corner of the design. First, all time-dependent behavior — payment deadlines, milestone due dates, lease windows, renewal windows, relocation schedules — is governed by a single server-side logical clock that administrators can advance deterministically, so a process spanning ten-year license terms can be exercised end to end without waiting for the calendar. Second, duties are segregated: the officials who run the auction are not the officials who adjudicate transfers and renewals, and anti-collusion rules freeze applicant disclosures for the entire bidding period. Every cent that changes hands is an integer number of cents, and every megahertz-pop of bidding eligibility traces back to an explicit, deterministic rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting disciplines that apply to the entire API. All business endpoints are mounted under the `/spectrum-auctions` prefix; the single test-driving clock endpoint is deliberately mounted outside it (§2.4).

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming one of four roles — `AuctionAdmin`, `Bidder`, `IncumbentOperator`, and `TransferReviewer`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not on the endpoint's authorization list is rejected with `ERR_UNAUTHORIZED_ROLE` (403).

Role identity works differently per role. When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant compare the resource's foreign-key field — for example `holder_applicant_id` on a license, the license-holder chain on a buildout milestone, or `transferor_applicant_id` on a transfer application — against `X-User-ID`, and a mismatch is `ERR_FORBIDDEN_OWNERSHIP` (403). The bidder identity is bootstrapped by self-registration: the caller registers with role `Bidder`, and the returned applicant `id` becomes that caller's `X-User-ID` for every subsequent `Bidder` call. When `X-User-Role` is `IncumbentOperator`, `X-User-ID` is the `id` of the acting `Incumbent`, an identity established when an `AuctionAdmin` registers the incumbent record. When `X-User-Role` is `AuctionAdmin` or `TransferReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`.

The two administrative roles are deliberately disjoint. The `AuctionAdmin` runs band planning, the auction lifecycle, clock rounds, qualification review, milestone review, and incumbent registration and relocation scheduling; the `TransferReviewer` alone adjudicates secondary-market transfer applications and renewal applications. Endpoints that multiplex several operations behind a single `action` field additionally restrict which role may supply which action value: on the transfer adjudication driver, a `Bidder` may perform only `PROVIDE_INFO`; on the incumbent transition driver, an `IncumbentOperator` may not perform `BEGIN_RELOCATION`, and an `AuctionAdmin` may not perform `SUBMIT_PLAN`, `DISPUTE`, `RESUBMIT_PLAN`, or `CONFIRM_CLEARED`. A caller whose role is permitted on the endpoint but not on the requested action value is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (400); an out-of-range value is clamped to the bounds rather than rejected — a `limit` below 1 is served as 1, above 100 as 100, and a negative `offset` as 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, ties broken by creation order (never by id). List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Its Maintenance Sweeps

Every time-dependent rule in this system reads a single server-side logical clock; wall-clock time is never consulted. Before the clock has ever been set, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time.

The clock is driven through a test-driving endpoint that intentionally lives outside the `/spectrum-auctions` prefix: `POST /_clock/set_current_utc`, restricted to `AuctionAdmin`. The request body carries a single field, `to_iso8601`, holding the ISO 8601 UTC instant to set; any parseable instant is accepted — the endpoint enforces no monotonicity, so a setting earlier than the current reading is accepted, and the sweeps below simply evaluate against whatever instant is set. A successful call returns 200 and echoes the new logical time as `current_utc`, rendered in the domain family of §2.5 (exactly as the clock reads).

Advancing the clock runs three maintenance sweeps. First, the payment-deadline sweep: every license still `PENDING_PAYMENT` whose `payment_deadline` is earlier than the new logical instant becomes `CANCELLED`, with the forfeiture and supply-restoration cascade described in §3.7. Second, the milestone sweep: every buildout milestone in `PENDING`, `FILED`, or `REJECTED` whose `due_date` is earlier than the new instant becomes `MISSED`, with the consequences described in §3.8 — a missed `INTERIM` milestone accelerates its sibling `FINAL` milestone's due date by 365 days, and a missed `FINAL` milestone terminates the license with its own cascade. Third, lease reconciliation: each license's lease fields are reconciled against its approved lease windows, so an approved window that contains the new instant becomes active — `active_lease_start`, `active_lease_end`, and `leased_to_applicant_id` are set — and a currently active window whose `active_lease_end` is at or before the new instant is cleared. Within each sweep class, records are processed in `created_at` ascending order, never in id order.

### 2.5. Resource Identity, Common Fields, and Timestamp Rendering

Every resource in the system — band plans, license areas, license blocks, auctions, applicants, clock rounds, bids, assignment bids, licenses, buildout milestones, transfer applications, incumbents, and renewal applications — carries the same four system-managed fields. The `id` is a server-minted UUID rendered in its standard dashed string form, used purely for identity; ids carry no type prefix of any kind. The `created_at` field records the creation instant and `updated_at` the latest mutation instant. The `version` field is an integer that starts at 1 and increments by exactly one on every mutation of the resource, including mutations performed as cascaded side effects of an operation on another resource.

Timestamp rendering distinguishes two families, and they must not be normalized into one serializer. The envelope field `api_request_timestamp` and the housekeeping fields `created_at` and `updated_at` always render as ISO 8601 UTC with exactly three fractional digits (millisecond precision). All domain datetimes — `application_deadline`, `grant_date`, `term_end`, `payment_deadline`, `due_date`, `lease_start`, `lease_end`, `active_lease_start`, `active_lease_end`, `transition_window_start`, and `transition_window_end` — render exactly as the logical clock reads: the ISO 8601 UTC instant that was set through the clock endpoint, with no added fractional-digit normalization.

### 2.6. Money, Spectrum Units, and Arithmetic Discipline

All monetary values are integer cents; no fractional cents ever exist. The system's only rounding mode is round half up, and it is applied exactly where each rule in §3 says it is applied. All bidding-eligibility and activity quantities are integer megahertz-pop units, computed from block bandwidths and area populations by exact integer multiplication. Ratio comparisons — the price-increment tiers, the activity requirement, the buildout coverage threshold — are evaluated by integer cross-multiplication rather than floating-point division, so two implementations doing exact integer arithmetic always agree. Day arithmetic is defined on the logical clock: a day is a 24-hour multiple, calendar-naive, and window boundaries are inclusive exactly where §3 says they are.

### 2.7. Validation Order and Error Precedence

When a request could fail several checks, the server evaluates them in a fixed priority order and reports only the first failure; later checks are never consulted once an earlier one has fired. The tiers, from first to last:

1. **Authentication** — the header and role-value check of §2.1 (`ERR_UNAUTHENTICATED`, 401).
2. **Role authorization** — the caller's role must appear in the endpoint's authorization list and, on action-multiplexed endpoints, must be permitted for the specific `action` value (`ERR_UNAUTHORIZED_ROLE`, 403).
3. **Existence** — path identifiers are resolved strictly left to right, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (404); a `transferee_applicant_id` supplied in a request body must likewise resolve to an existing applicant. For bid and assignment-bid bodies, once every path identifier has resolved, the referenced product — the (`area_code`, `category`) pair — must exist in the auction's band plan, or the request fails with `ERR_PRODUCT_NOT_FOUND` (still 404).
4. **Ownership** — entity-backed callers must own the target resource per §2.1 (`ERR_FORBIDDEN_OWNERSHIP`, 403).
5. **State gates** — the target entity must be in a from-state of the requested transition, surfaced through the machine-specific error id: `ERR_AUCTION_INVALID_STATE`, `ERR_APPLICANT_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, `ERR_LICENSE_INVALID_STATE`, `ERR_MILESTONE_INVALID_STATE`, `ERR_TRANSFER_INVALID_STATE`, `ERR_INCUMBENT_INVALID_STATE`, `ERR_RENEWAL_INVALID_STATE`, `ERR_BAND_PLAN_NOT_DRAFT`, or `ERR_PRODUCT_CLOSED` (all 409).
6. **Anti-collusion and qualification compliance** — the quiet-period freeze (`ERR_QUIET_PERIOD_VIOLATION`, 409) and, at qualification, the ownership-total and credit-claim gates (`ERR_OWNERSHIP_TOTAL_INVALID` and `ERR_CREDIT_CLAIM_CONFLICT`, both 422, the ownership total checked first).
7. **Structural constraints** — uniqueness, supply caps, lease-window shape and overlap, relocation-window conflicts, assignment-bid completeness, and plan completeness: `ERR_DUPLICATE_AREA_CODE`, `ERR_DUPLICATE_BLOCK_CATEGORY`, `ERR_DUPLICATE_BID`, `ERR_DUPLICATE_ASSIGNMENT_BID`, `ERR_LEASE_WINDOW_OVERLAP`, `ERR_TRANSITION_WINDOW_CONFLICT`, and `ERR_ASSIGNMENT_BIDS_INCOMPLETE` (all 409), plus `ERR_SUPPLY_EXCEEDED`, `ERR_LEASE_DATES_INVALID`, and `ERR_BAND_PLAN_INCOMPLETE` (all 422).
8. **Temporal windows** — windowed operations must fall inside their windows: `ERR_APPLICATION_DEADLINE_NOT_PASSED`, `ERR_UPFRONT_WINDOW_CLOSED`, `ERR_WITHDRAWAL_WINDOW_CLOSED`, and `ERR_RENEWAL_WINDOW_CLOSED` (all 409).
9. **Membership and derivation** — the winner check on assignment bids (`ERR_NOT_A_WINNER`, 403).
10. **Fiscal gates, always last** — money and quota checks: `ERR_BID_EXCEEDS_ELIGIBILITY`, `ERR_OVERPAYMENT`, `ERR_INSUFFICIENT_UPFRONT`, `ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED`, and `ERR_COVERAGE_BELOW_REQUIREMENT` (all 422).

Independently of this ordering, a request body that is malformed — a missing required field, a mistyped or out-of-range value, or an unknown enum member — is rejected with `ERR_INVALID_REQUEST` (400). Separately, the three optimistic-concurrency endpoints of §2.8 reject a stale edit base with `ERR_STALE_VERSION` (412) before any mutation is applied.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its own version field. Updating an applicant's disclosure (`PATCH /spectrum-auctions/applicants/{id}/disclosure`) requires the request to carry `expected_applicant_version`, holding the applicant's `version` as the client last observed it; if the record has been mutated since — for example by an earlier disclosure update or by a resubmission — the versions disagree and the update is rejected with `ERR_STALE_VERSION` (412), because the client's edit base is stale. Resubmitting a corrected application (`POST /spectrum-auctions/applicants/{id}/resubmit`, §3.3) likewise carries `expected_applicant_version` and rejects a stale base with `ERR_STALE_VERSION` (412). Filing a buildout coverage notice (`POST /spectrum-auctions/buildout-milestones/{id}/file-notice`) likewise requires `expected_milestone_version` matching the milestone's current `version`; because each filing supersedes the previous filing's content, any intervening mutation — an earlier filing, a review decision, or a due-date acceleration — invalidates a stale base, and the filing is rejected with `ERR_STALE_VERSION` (412). On each guarded endpoint the version check is evaluated after ownership and the guarded resource's own state gate, and before the endpoint's remaining gates — on the applicant endpoints it precedes the quiet-period freeze, and on the milestone endpoint it precedes the license-state check. All three fields are non-optional on their respective endpoints. Endpoints not named here do not accept a version field.

### 2.9. Flat Topology, Nested Retrieval, and Listing Filters

All thirteen resources are top-level: none is nested inside another at creation, and they reference each other through foreign-key fields such as `band_plan_id`, `auction_id`, `round_id`, `license_id`, and `area_id`. Where a request path chains more than one identifier, the identifiers are validated in strict left-to-right order, and the request fails with `ERR_NOT_FOUND` at the first identifier that does not resolve, before any later identifier or business rule is examined.

List endpoints double as reverse-reach views over those foreign keys, and several accept filters: the applicant roster of an auction can be filtered by `status`; the bids of a round by `bidder_applicant_id`; the bids of an applicant by `round_id`; the license registry by `auction_id`, `area_id`, `holder_applicant_id`, or `status`; and the incumbent registry by `band_plan_id`, `area_id`, or `status`. All of them accept the `limit` and `offset` parameters of §2.3.

## 3. Business Logic & Workflows

### 3.1. Band Planning, License Areas, Blocks, and Incumbent Registration

An `AuctionAdmin` begins by authoring a band plan, supplying a human-readable `band_name`, the band edges `frequency_start_mhz` and `frequency_end_mhz` — both numbers, and a lower edge not strictly below the upper edge is rejected with `ERR_INVALID_REQUEST` (400) — and an optional free-text `technical_rules` summary of power limits and out-of-band emission masks, which defaults to an empty string when omitted. A new band plan is `DRAFT`.

While the plan remains `DRAFT`, the administrator adds license areas and license blocks to it. A license area carries the plan's `band_plan_id`, a short `area_code` such as PEA001, a display `name`, and a `population` of at least 1 — the population drives both bidding-unit arithmetic and buildout coverage math later. A license block carries the plan's `band_plan_id`, a `category` of `CATEGORY_A`, `CATEGORY_B`, `CATEGORY_C`, or `CATEGORY_D`, an integer `mhz_size` of at least 1, a `supply_per_area` of at least 1 (the number of licenses of this category that will exist in every license area), and a `price_per_mhz_pop_cents` opening-price coefficient of at least 0. Two structural rules guard the plan's integrity: an `area_code` may appear only once within a band plan (`ERR_DUPLICATE_AREA_CODE`), and a `category` may appear only once within a band plan (`ERR_DUPLICATE_BLOCK_CATEGORY`). Once the plan has left `DRAFT`, any further attempt to add an area or a block to it is rejected with `ERR_BAND_PLAN_NOT_DRAFT`.

Publishing moves the plan `DRAFT → PUBLISHED` and requires at least one license area and at least one license block; publishing an empty plan fails with `ERR_BAND_PLAN_INCOMPLETE` (422), and attempting to publish a plan that is no longer `DRAFT` fails with `ERR_BAND_PLAN_NOT_DRAFT`. `PUBLISHED` is terminal: from that moment the plan's structure — its areas, its blocks, and their parameters — is frozen, which is what lets auctions treat the product inventory as fixed.

Band planning also records who already occupies the spectrum. An `AuctionAdmin` registers an incumbent by supplying the plan's `band_plan_id`, the `area_id` of the license area the incumbent occupies — registration validates that the named plan and the named area both exist, and does not otherwise require the area to belong to the named plan — a station `callsign`, and an estimated `relocation_cost_cents` of at least 0. A new incumbent starts in `NOTIFIED` status; the relocation workflow of §3.7 later moves it through plan submission, dispute, relocation, and clearing, and its `transition_window_start`, `transition_window_end`, `shares_proportional`, and `shares_equal` fields stay unset — each rendering as null — until that workflow fills them in.

### 3.2. Auction Setup, Self-Registration, and the Upfront Ledger

Against a `PUBLISHED` plan, an `AuctionAdmin` creates an auction — a plan in any other status is rejected with `ERR_INVALID_REQUEST` (400) — supplying the plan's `band_plan_id`, a display `name`, and an `application_deadline` — the ISO 8601 UTC instant before which the quiet period cannot begin. A new auction is `DRAFT`, with `current_round_number` 0, `total_proceeds_cents` 0, and `forfeited_deposits_cents` 0. The auction's phase machine is driven by the administrator through an `action` field, and every phase transition requires the auction to be in exactly its from-state — any other phase fails with `ERR_AUCTION_INVALID_STATE`. Opening applications (`action` `OPEN_APPLICATIONS`) moves the auction `DRAFT → APPLICATION_OPEN`.

While an auction is `APPLICATION_OPEN`, a prospective bidder self-registers with role `Bidder`, supplying the `auction_id`, a `legal_name`, the booleans `claims_small_business` and `claims_rural_credit`, the applicant's `own_annual_revenue_cents` (at least 0), the `service_population` of its intended rural service area (a non-negative integer), and an `ownership_interests` array whose entries each carry a `holder_name` (a non-empty string), a `stake_pct` (a non-negative number; fractional percentages are admitted), and a `holder_annual_revenue_cents` (a non-negative integer) — malformed entries are rejected with `ERR_INVALID_REQUEST` (400). Registration against an auction in any other phase is rejected with `ERR_AUCTION_INVALID_STATE`. The new applicant starts `SUBMITTED` with a zeroed ledger — `upfront_paid_cents`, `upfront_held_cents`, `upfront_refunded_cents`, `upfront_forfeited_cents`, `eligibility_units`, `initial_eligibility_units`, and `credit_pct` all begin at 0 — and the returned applicant `id` becomes the caller's `X-User-ID` for everything that follows. `attributable_revenue_cents` is no part of that zeroed ledger: it renders as null from registration until a successful qualification computes it (§3.3), and nothing else ever writes it. Whenever the ownership array is supplied — at registration, in a later disclosure update, or when it is re-examined at qualification — its `stake_pct` values must sum to exactly 100 — for fractional stakes the comparison tolerates floating-point representation error, passing whenever the sum is within 1e-9 of 100 — or the request fails with `ERR_OWNERSHIP_TOTAL_INVALID` (422). Registration itself is permissive about the two credit claims: an applicant may register with both flags set, and the mutual-exclusion rule bites only at qualification.

While the applicant is `SUBMITTED` or `NEEDS_CORRECTION` and the auction is still `APPLICATION_OPEN`, the bidder may update its disclosure — any of `legal_name`, `claims_small_business`, `claims_rural_credit`, `own_annual_revenue_cents`, `service_population`, and `ownership_interests` — and the ownership array, when supplied, replaces the previous array wholesale and must again sum to exactly 100. The update is OCC-guarded per §2.8: `expected_applicant_version` is mandatory, a stale base is rejected with `ERR_STALE_VERSION`, and a successful update increments the applicant's `version` by 1. An update attempted while the applicant is in any other status is rejected with `ERR_APPLICANT_INVALID_STATE`, and from the quiet period onward the anti-collusion freeze of §3.4 rejects it with `ERR_QUIET_PERIOD_VIOLATION` regardless of the applicant's status.

Bidding eligibility is bought with money up front. While the auction is `APPLICATION_OPEN` or `QUIET_PERIOD`, the bidder may add an `amount_cents` payment to the deposit — the amount must be a positive integer, a non-positive amount failing with `ERR_INVALID_REQUEST` (400); payments attempted after the auction has left those phases fail with `ERR_UPFRONT_WINDOW_CLOSED`. Each payment increases `upfront_paid_cents` and `upfront_held_cents` by the amount paid and immediately recomputes `eligibility_units` as the held balance divided by 2500, rounded down to a whole unit — one eligibility unit of bidding power per 2500 cents held. The held figure is the basis, not the paid figure: later refunds and forfeitures move cents out of `upfront_held_cents` and therefore reduce live eligibility. The ledger is conservative at every step, so `upfront_paid_cents` always equals the sum of `upfront_held_cents`, `upfront_refunded_cents`, and `upfront_forfeited_cents`.

### 3.3. Qualification Review, Corrections, and Bidding Credits

An `AuctionAdmin` drives qualification through the review driver's `action` field. Starting review (`START_REVIEW`) moves an applicant `SUBMITTED → UNDER_REVIEW`. Requesting a correction (`REQUEST_CORRECTION`) moves it `UNDER_REVIEW → NEEDS_CORRECTION`, from which the owning bidder resubmits: the resubmission carries `expected_applicant_version` (§2.8), requires the auction to still be `APPLICATION_OPEN` — once the quiet period has begun, the freeze rejects resubmission with `ERR_QUIET_PERIOD_VIOLATION` — and returns the applicant to `UNDER_REVIEW` with its `version` incremented by 1.

Qualification (`QUALIFY`, moving the applicant `UNDER_REVIEW → QUALIFIED`) applies four checks in a fixed order. First the state gate: the applicant must be `UNDER_REVIEW`, else `ERR_APPLICANT_INVALID_STATE`. Then the compliance gates: the `ownership_interests` stakes must sum to exactly 100, else `ERR_OWNERSHIP_TOTAL_INVALID`, and `claims_small_business` and `claims_rural_credit` must not both be true, else `ERR_CREDIT_CLAIM_CONFLICT` (422). Last, the fiscal gate: the applicant must hold at least one eligibility unit, else `ERR_INSUFFICIENT_UPFRONT` (422). The ordering matters — a qualification attempt that would fail both the ownership total and the insufficient-upfront check reports the ownership failure.

A successful qualification computes two derived fields. The `attributable_revenue_cents` is the applicant's `own_annual_revenue_cents` plus the `holder_annual_revenue_cents` of every ownership interest whose `stake_pct` is strictly greater than 25 — a holder with exactly 25 percent is not attributable. The `credit_pct` is then assigned by tier. A small-business claimant receives 35 percent when its attributable revenue is at most 400000000 cents, otherwise 25 percent when at most 2000000000 cents, otherwise 15 percent when at most 5500000000 cents, and 0 above the largest tier; tier boundaries are inclusive, so revenue exactly at a boundary qualifies for that boundary's percentage. A rural claimant instead receives 15 percent when its `service_population` is at most 250000, and 0 above that cap. An applicant with neither claim receives 0. The two credits are mutually exclusive — that is what the conflict check enforces — and `credit_pct` is only ever written by qualification: client-supplied values are ignored everywhere.

Rejection (`REJECT`) moves an applicant `UNDER_REVIEW → REJECTED` and refunds the deposit in full: the entire `upfront_held_cents` moves into `upfront_refunded_cents`, leaving the held balance at 0 and preserving the conservation invariant. Withdrawal is the bidder's own exit and requires ownership of the applicant record; it is available from `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_CORRECTION`, or `QUALIFIED` alike, but only while the auction is `APPLICATION_OPEN` — from the quiet period onward the window has closed and the attempt fails with `ERR_WITHDRAWAL_WINDOW_CLOSED`. Withdrawal moves the applicant to `WITHDRAWN` and refunds the held deposit exactly as rejection does. Both `REJECTED` and `WITHDRAWN` are terminal.

Disqualification (`DISQUALIFY`) is the anti-collusion enforcement instrument. It moves an applicant `QUALIFIED → DISQUALIFIED` and is available only while the auction is `QUIET_PERIOD`, `CLOCK_ACTIVE`, or `CLOCK_PAUSED`; at any other auction phase the attempt fails with `ERR_APPLICANT_INVALID_STATE`. Disqualification cascades in two hops: first, every `SUBMITTED` bid the applicant holds in the currently open clock round becomes `VOIDED`; second, each voiding itself triggers live recomputation of that round's `aggregate_demand` with the voided quantities removed. The applicant's entire held deposit is then forfeit — `upfront_held_cents` moves into `upfront_forfeited_cents` — and the auction's `forfeited_deposits_cents` grows by the forfeited amount.

### 3.4. The Quiet Period and the Start of the Clock

Once the logical clock has reached the auction's `application_deadline`, an `AuctionAdmin` may begin the quiet period (`action` `BEGIN_QUIET_PERIOD`, moving the auction `APPLICATION_OPEN → QUIET_PERIOD`); attempting it before the deadline has passed fails with `ERR_APPLICATION_DEADLINE_NOT_PASSED`. The quiet period starts the anti-collusion freeze: from that moment until the auction reaches `CLOSED`, disclosure updates and correction resubmissions are rejected with `ERR_QUIET_PERIOD_VIOLATION`. If conditions change, the administrator may postpone (`action` `POSTPONE`, moving `QUIET_PERIOD → APPLICATION_OPEN`), which lifts the freeze; the auction may later re-enter the quiet period, subject again to the deadline check.

Starting the clock (`action` `START_CLOCK`, moving `QUIET_PERIOD → CLOCK_ACTIVE`) requires at least one `QUALIFIED` applicant of the auction, failing which the attempt is rejected with `ERR_NO_QUALIFIED_BIDDERS` (422). The transition performs four side effects atomically. It creates clock round 1 in `OPEN` status with opening prices: for every product — every (area, block) pair of the auction's band plan — the posted `price_cents` is the block's `mhz_size` multiplied by the area's `population`, multiplied by the block's `price_per_mhz_pop_cents`, an exact integer with no rounding step. It initializes the auction's `available_supply`, an array of (`area_code`, `category`, `available`) entries in which every product's `available` starts at the block's `supply_per_area`. It snapshots every `QUALIFIED` applicant's `initial_eligibility_units` from that applicant's current `eligibility_units`. And it sets the auction's `current_round_number` to 1. The same product arithmetic defines the product's bidding units — `mhz_size` multiplied by `population` — which remains the unit of account for eligibility and activity for the rest of the auction.

The administrator may pause the clock (`action` `PAUSE_CLOCK`, moving `CLOCK_ACTIVE → CLOCK_PAUSED`) and later resume it (`action` `RESUME_CLOCK`, moving `CLOCK_PAUSED → CLOCK_ACTIVE`). While the auction is paused, bid placement is rejected with `ERR_AUCTION_INVALID_STATE`, and rounds can neither be opened nor closed, since both require `CLOCK_ACTIVE`.

### 3.5. Clock Rounds: Prices, Bids, Demand, and Activity

Each clock round is `OPEN` or `CLOSED`, carries a 1-based `round_number`, and is stamped with a `stage` — 1 for every round before round 4, and 2 from round 4 onward. A round's `prices` array lists every product still open for bidding as an (`area_code`, `category`, `price_cents`) entry, and its `aggregate_demand` array lists, per product, the running `demand_quantity`. While a round is `OPEN`, demand is maintained live: each new bid adds its quantity into the round's `aggregate_demand`, and each voided bid's quantity is removed, so the open round always reflects current `SUBMITTED` bids. When the auction is `CLOCK_ACTIVE` and the previous round has been `CLOSED`, the administrator opens the next round — an attempt while the auction is not `CLOCK_ACTIVE`, or while its current round is not yet `CLOSED`, fails with `ERR_AUCTION_INVALID_STATE`; the auction's `current_round_number` advances by 1, and the new round's prices are computed from the last closed round by the tiered increment rule below — a product that closed in any earlier round is absent from `prices` and never returns.

Price formation between rounds follows a tiered increment rule, evaluated independently for each product present in the last closed round's `prices` array. Take the product's finalized demand — its `demand_quantity` in that round's `aggregate_demand` — and its supply, the block's `supply_per_area`. The comparisons use integer cross-multiplication so no floating-point division ever occurs: the product takes a 15 percent increment when twice the demand is at least three times the supply; failing that, a 10 percent increment when five times the demand is at least six times the supply; failing that, a 5 percent increment when the demand is at least the supply. Boundaries are inclusive on the lower side — demand of exactly three-halves of supply earns 15 percent, exactly six-fifths earns 10 percent, and demand exactly equal to supply earns 5 percent. The new posted price is the product's last price increased by the selected percentage and rounded half up to a whole cent, applied once per product per round. A product whose demand falls short of supply closes: it is excluded from the new round's `prices` array, is no longer biddable, and can never re-enter. Because the decision is computed independently per product, one product may jump 15 percent in the same round in which another closes.

A `Bidder` places a clock bid against an open round by supplying `area_code`, `category`, and a whole-number `quantity` between 1 and the block's `supply_per_area`; a non-positive or otherwise malformed quantity is rejected with `ERR_INVALID_REQUEST`, while one exceeding supply fails with `ERR_SUPPLY_EXCEEDED` (422). The caller's `X-User-ID` must equal the applicant `id` the bid is placed for (`ERR_FORBIDDEN_OWNERSHIP`), and the bid's `bidder_applicant_id` is always that caller — bidding on another applicant's behalf is impossible. A caller whose `X-User-ID` does not resolve to an applicant of the bid's auction at all is rejected with `ERR_APPLICANT_INVALID_STATE`, a resolution evaluated once the referenced product has been found and before the round-open check. The round must be `OPEN` (`ERR_ROUND_NOT_OPEN`), the auction must be `CLOCK_ACTIVE` — a bid while paused fails with `ERR_AUCTION_INVALID_STATE` — the bidder must be `QUALIFIED` (bids by applicants in any other status land on `ERR_APPLICANT_INVALID_STATE`), and the product must both exist in the auction's band plan (`ERR_PRODUCT_NOT_FOUND`, checked only after every path identifier has resolved) and still be open in this round (`ERR_PRODUCT_CLOSED`). One bid per round, bidder, and product is allowed: a second `SUBMITTED` bid for the same triple is `ERR_DUPLICATE_BID`. Per the global ordering of §2.7, the fiscal gate fires last: the bidder's cumulative activity in this round — the sum of `units_snapshot` over the bidder's bids in the round, the new bid included — must not exceed the bidder's current `eligibility_units`, or the bid is rejected with `ERR_BID_EXCEEDS_ELIGIBILITY` (422). A created bid is `SUBMITTED`, with its `units_snapshot` frozen at bid time as the `quantity` multiplied by the product's bidding units, so later changes elsewhere can never rewrite a bid's contribution.

Closing a round requires the round to be `OPEN` (`ERR_ROUND_NOT_OPEN`) and the auction to be `CLOCK_ACTIVE` (`ERR_AUCTION_INVALID_STATE`). Closing finalizes `aggregate_demand` from the round's `SUBMITTED` bids, which become `PROCESSED`, and then applies the activity requirement. For every applicant whose status is `QUALIFIED` at close time — applicants in `DISQUALIFIED`, `REJECTED`, or `WITHDRAWN` are excluded from both sides of the comparison — the applicant's activity for the round is the sum of `units_snapshot` over that round's `PROCESSED` bids placed by the applicant. The requirement is set by the round's `stage`: 800 milli-units (80 percent) in stage 1 and 950 milli-units (95 percent) in stage 2. If the applicant's activity multiplied by 1000 is at least the stage requirement multiplied by the applicant's current `eligibility_units`, eligibility is unchanged — the boundary is inclusive. Otherwise `eligibility_units` is reduced to the applicant's activity multiplied by 1000 and divided by the stage requirement, rounded down to a whole unit. The evaluation order is pinned to break any appearance of circularity: bids were validated against the eligibility in force during the round; activity is measured at close for that same round; and any reduction applies to subsequent rounds only, never retroactively.

When the round being closed shows demand at or below supply for every product still open for bidding, closing it also advances the auction `CLOCK_ACTIVE → ASSIGNMENT_PHASE` and fixes the winners: the final round's `PROCESSED` bids with `quantity` greater than 0 become the winning (applicant, `area_code`, `category`, `quantity`) tuples, and each unit of a winning tuple will become one license when the assignment completes.

### 3.6. The Assignment Phase and Settlement Pricing

During the assignment phase, each winner files one sealed assignment bid per product won, supplying `area_code`, `category`, and an `amount_cents` of at least 0 — a negative amount is rejected with `ERR_INVALID_REQUEST`. The amount applies per license won: a winner of three units on a product will see the full amount folded into each of the three licenses. Filing is phase-gated — it is accepted only while the auction is in `ASSIGNMENT_PHASE`, and at any other phase the attempt fails with `ERR_AUCTION_INVALID_STATE` — and the caller must be a recorded winner of that product in the final clock round, else `ERR_NOT_A_WINNER` (403). Only one assignment bid may exist per bidder and product (`ERR_DUPLICATE_ASSIGNMENT_BID`). A new assignment bid is `SUBMITTED`.

Completing the assignment (`action` `COMPLETE_ASSIGNMENT`, moving the auction `ASSIGNMENT_PHASE → CLOSED`) requires every winning tuple to have a `SUBMITTED` assignment bid from its applicant; there is no zero-amount default fallback, and a missing bid blocks completion with `ERR_ASSIGNMENT_BIDS_INCOMPLETE`. Within each product, the winners' assignment bids are ranked by `amount_cents` descending, with ties broken by the assignment bid's `created_at` ascending — never by id. Walking that ranking, each winner's won quantity takes the next consecutive `frequency_block_index` values, starting at 0, within the product.

Completion mints one license per won unit, in `PENDING_PAYMENT` status. Each license records the `auction_id`, the `area_id` of its license area, the denormalized `area_code` for display and joining convenience — a copy, not a foreign key — the `category`, its assigned `frequency_block_index`, and the winning applicant as `holder_applicant_id`. The `credit_pct` is copied from the winning applicant at creation and never changes thereafter, whatever happens to the applicant later. The `gross_clock_price_cents` is the final clock round's posted price for the product, and `assignment_bid_cents` is that winner's assignment bid amount.

Each license's money fields are then computed in two variants that share one credit basis. The `gross_final_price_cents` is `gross_clock_price_cents` plus `assignment_bid_cents`. The provisional variant, `provisional_net_price_cents`, is `gross_clock_price_cents` scaled by (100 minus `credit_pct`) percent and rounded half up to a whole cent; because it excludes the assignment bid it is invariant to the assignment phase, and identical clock data yields a different provisional and final figure whenever any assignment bid exceeds 0. The final variant, `net_price_cents`, applies the same scaling to `gross_final_price_cents` and is the settlement amount actually due. The `credit_amount_cents` — the dollar value of the bidding credit, and the basis for unjust-enrichment repayment at transfer time — is `gross_final_price_cents` minus `net_price_cents`. Each license's `payment_deadline` is set to the logical instant of its creation plus 30 days; `paid_cents` starts at 0; `grant_date` and `term_end` remain null until grant; the lease fields `active_lease_start`, `active_lease_end`, and `leased_to_applicant_id` are null while no lease is active; and `relocation_share_owed_cents` starts at 0.

Rounding order is pinned: each license's `net_price_cents` is rounded to cents first, and the auction's `total_proceeds_cents` is then the sum of those per-license figures — summing unrounded values and rounding once at the end is a different, non-conformant answer. Completion also marks every winner's assignment bid `SUBMITTED → APPLIED` — `APPLIED` is terminal for the assignment bid — decrements each product's `available_supply` entry by the number of licenses created in it, and moves the auction to `CLOSED`, its terminal state.

### 3.7. Settlement, Incumbent Clearing, and License Grant

A winner pays down a `PENDING_PAYMENT` license through settlement payments of `amount_cents`, made by the license holder — the caller's `X-User-ID` must equal the license's `holder_applicant_id` (`ERR_FORBIDDEN_OWNERSHIP`). The license must be `PENDING_PAYMENT`, else `ERR_LICENSE_INVALID_STATE`, and each payment must be positive and must not exceed the remaining balance — `net_price_cents` minus `paid_cents` — with either violation rejected as `ERR_OVERPAYMENT` (422). Payments accumulate into `paid_cents` and may be made in any number of installments.

The payment that would complete settlement — the one bringing `paid_cents` up to `net_price_cents` — carries one extra precondition: every incumbent registered in the license's area must be `RELOCATING` or `CLEARED`. An incumbent still `NOTIFIED`, `PLAN_SUBMITTED`, or `DISPUTED` in that area blocks the completing payment with `ERR_INCUMBENTS_NOT_CLEARED` (409). On completion the license becomes `ACTIVE`: `grant_date` is stamped with the current logical instant, `term_end` is computed as the grant date plus 3650 days, and two buildout milestones are created in `PENDING` status, each stamped with its `milestone_type` — an `INTERIM` milestone due 1095 days after grant with `required_coverage_pct` 40, and a `FINAL` milestone due 2190 days after grant with `required_coverage_pct` 70, the constants copied onto the milestone records at creation. In milestone listings the pair created by a single grant reads in `created_at` ascending order, `INTERIM` before `FINAL`.

If the logical clock advances past a license's `payment_deadline` while it is still `PENDING_PAYMENT`, the deadline sweep cancels it, and the cancellation cascades in two hops: first, the holder's remaining held deposit is forfeit — the holder applicant's `upfront_held_cents` moves into its `upfront_forfeited_cents`; second, that forfeiture itself adds the forfeited amount to the auction's `forfeited_deposits_cents`. The product's `available_supply` entry then increases by 1, returning the spectrum to inventory. `CANCELLED` is terminal.

The incumbent workflow that feeds the settlement gate is driven through an `action` field split between the two roles of §2.1. The owning `IncumbentOperator` submits a relocation plan (`SUBMIT_PLAN`, moving `NOTIFIED → PLAN_SUBMITTED`), disputes a plan (`DISPUTE`, moving `PLAN_SUBMITTED → DISPUTED`), and resubmits after a dispute (`RESUBMIT_PLAN`, moving `DISPUTED → PLAN_SUBMITTED`); every one of these requires the caller's `X-User-ID` to equal the incumbent's `id` (`ERR_FORBIDDEN_OWNERSHIP`) and the matching from-state (`ERR_INCUMBENT_INVALID_STATE`). An `AuctionAdmin` then begins relocation (`BEGIN_RELOCATION`, moving `PLAN_SUBMITTED → RELOCATING`), recording `transition_window_start` and `transition_window_end`; the end must be strictly after the start (`ERR_INVALID_REQUEST`), and the new window must keep a buffer against every other `RELOCATING` incumbent in the same area — the windows are closed intervals, so the new window must start at least 30 days after the existing window's end or end at least 30 days before the existing window's start, and any tighter fit fails with `ERR_TRANSITION_WINDOW_CONFLICT`. Finally the owner confirms clearing (`CONFIRM_CLEARED`, moving `RELOCATING → CLEARED`), which is allowed only once the logical clock has reached `transition_window_end`; an earlier attempt fails with `ERR_INCUMBENT_INVALID_STATE`. `CLEARED` is terminal.

Confirming cleared also settles relocation costs across the area's new licensees, and this is the one place the incumbent record's share arrays are filled. Let the cost be the incumbent's `relocation_cost_cents`, and consider every `ACTIVE` license whose `area_id` matches the incumbent's area; each license's weight is its bidding units — its category's `mhz_size` multiplied by its area's `population`. Two schedules are computed and stored on the incumbent. The binding schedule, `shares_proportional`, gives each license a base amount of the cost multiplied by the license's units and divided by the total units across those licenses, rounded down; the leftover cents are then distributed one cent at a time to licenses ordered by units descending, ties broken by the license's `created_at` ascending — never by id — until the remainder is exhausted. The dispute-reference schedule, `shares_equal`, gives each license an equal base of the cost divided by the number of licenses, rounded down, with the same remainder rule. Each entry in either array names a `license_id` and an `amount_cents`. The proportional amounts are posted onto each license's `relocation_share_owed_cents`, syncing the license ledger; if no `ACTIVE` licenses exist in the area, both arrays are empty and nothing is posted. Identical inputs produce different amounts under the two schedules whenever the licenses' units differ, which is exactly why both are stored.

### 3.8. Buildout Milestones and Performance Enforcement

A licensee files a coverage notice against a milestone by supplying `covered_population` — a non-negative integer, the population it certifies as covered, a field that is null until the first filing — together with `expected_milestone_version` (§2.8; a stale base fails with `ERR_STALE_VERSION`). Filing is allowed only from `PENDING` or `REJECTED` — filing against a milestone in any other status, `FILED`, `ACCEPTED`, or `MISSED` alike, fails with `ERR_MILESTONE_INVALID_STATE` — only while the license is `ACTIVE` or `RENEWAL_REVIEW` (`ERR_LICENSE_INVALID_STATE` otherwise), and only by the license holder (`ERR_FORBIDDEN_OWNERSHIP`). Filing moves the milestone to `FILED`, records the certified figure — overwriting any earlier filing — and increments the milestone's `version` by 1, which is precisely what invalidates stale concurrency bases.

An `AuctionAdmin` reviews a `FILED` milestone with a `decision` of `ACCEPT` or `REJECT`; reviewing a milestone that is not `FILED` fails with `ERR_MILESTONE_INVALID_STATE`. Acceptance requires the coverage cross-multiplication to hold: the certified `covered_population` multiplied by 100 must be at least the milestone's `required_coverage_pct` multiplied by the license area's `population` — an exact integer comparison with an inclusive boundary, so coverage of exactly 40.000 percent passes an `INTERIM` milestone — and any shortfall fails with `ERR_COVERAGE_BELOW_REQUIREMENT` (422). Rejection moves the milestone to `REJECTED`, from which the licensee may re-file under the same rules as an initial filing.

The logical clock enforces the deadlines whether or not anyone has filed. When the clock advances past a milestone's `due_date` while the milestone is `PENDING`, `FILED`, or `REJECTED`, the milestone becomes `MISSED` — an unreviewed filing does not satisfy the milestone, regardless of the coverage figure filed, and neither does a rejected one. A missed `INTERIM` milestone accelerates its sibling: while the `FINAL` milestone is still `PENDING`, `FILED`, or `REJECTED`, its `due_date` moves 365 days earlier and its `version` increments as part of that mutation; an already-terminal `FINAL` (`ACCEPTED` or `MISSED`) is left untouched. A missed `FINAL` milestone terminates the license: the license moves `ACTIVE → TERMINATED`, every transfer application of that license still `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is moved to `DENIED`, and the product's `available_supply` entry increases by 1. `ACCEPTED` and `MISSED` are the milestone's terminal states, and `TERMINATED` is one of the license's two terminal states.

### 3.9. Transfers, Leases, Renewal, and Termination

The holder of an `ACTIVE` license may file a secondary-market application, supplying a `transfer_type` of `FULL_ASSIGNMENT` or `LEASE` and a `transferee_applicant_id`, which must resolve to an existing applicant — of any auction, not necessarily this one, and not excluding the holder itself — or the filing fails with `ERR_NOT_FOUND`. Filing against a license in any other status, including `RENEWAL_REVIEW`, fails with `ERR_LICENSE_INVALID_STATE`, and the filer must be the license holder (`ERR_FORBIDDEN_OWNERSHIP`). A lease additionally requires `lease_start` and `lease_end` with the end strictly after the start (`ERR_LEASE_DATES_INVALID`, 422), and its window — half-open, containing every instant from `lease_start` up to but not including `lease_end` — must not intersect any already-approved lease window on the same license; the overlap scan covers all approved windows of the license, not only the currently active one, while merely touching endpoints is allowed (`ERR_LEASE_WINDOW_OVERLAP`, 409). `lease_start` and `lease_end` are meaningful only for a `LEASE`; supplied on a `FULL_ASSIGNMENT` they are ignored, and the stored fields remain null. The new application is `FILED`, and its `unjust_enrichment_cents` is computed at filing time from the logical clock.

Unjust enrichment protects the bidding-credit program on early or down-qualifying transfers. When the license's `credit_amount_cents` is 0, the repayment is 0. Otherwise, measure the holding period in whole 365-day years elapsed between `grant_date` and the filing instant. If the transferee's `credit_pct` is lower than the license's `credit_pct`, the schedule percentage is 100 — a less credit-eligible buyer repays the credit in full regardless of holding period. Otherwise the schedule steps down over five 365-day years: 100 percent during year 0, then 80, 60, 40, and 20 percent during years 1 through 4 respectively, and 0 percent at five or more years — so a transfer filed exactly 1825 days after grant owes nothing, while one filed on day 1824 still owes 20 percent. The repayment is the license's `credit_amount_cents` multiplied by the schedule percentage, divided by 100, and rounded half up to a whole cent.

A `TransferReviewer` adjudicates the application through the review driver's `action` field. Beginning review (`BEGIN_REVIEW`) moves it `FILED → UNDER_REVIEW`; requesting information (`REQUEST_INFO`) moves it `UNDER_REVIEW → INFO_REQUESTED`; and the transferor — and only the transferor, as a `Bidder` — supplies the information (`PROVIDE_INFO`), moving it `INFO_REQUESTED → UNDER_REVIEW`. The transferor may withdraw from `FILED` or `INFO_REQUESTED`, moving the application to `WITHDRAWN`. Any of these attempted from a state without that edge fails with `ERR_TRANSFER_INVALID_STATE`, and any caller other than the transferor on the transferor's actions fails with `ERR_FORBIDDEN_OWNERSHIP`. Approval (`APPROVE`) and denial (`DENY`) both proceed from `UNDER_REVIEW`. Approval requires the license to be `ACTIVE` or `RENEWAL_REVIEW` (`ERR_LICENSE_INVALID_STATE` otherwise) and, when the application's `unjust_enrichment_cents` exceeds 0, requires the request to carry `confirm_unjust_enrichment_repayment` set to true, else `ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED` (422).

Approval lands differently per transfer type. An approved `FULL_ASSIGNMENT` rewrites the license's `holder_applicant_id` to the transferee. An approved `LEASE` whose window already contains the current logical instant activates immediately — `active_lease_start`, `active_lease_end`, and `leased_to_applicant_id` are set on the spot — while a future window is activated later by the clock's lease sweep when the logical instant enters the window, and the same sweep clears the fields once `active_lease_end` has been reached. `APPROVED`, `DENIED`, and `WITHDRAWN` are all terminal for the application.

A license is renewable inside a window at the end of its term: from 365 days before `term_end` through `term_end` itself, inclusive at both ends. The holder files for renewal inside that window — outside it the filing fails with `ERR_RENEWAL_WINDOW_CLOSED` — the license must be `ACTIVE` (`ERR_LICENSE_INVALID_STATE` otherwise), and no other renewal application of the same license may be `FILED` or `UNDER_REVIEW` (`ERR_RENEWAL_INVALID_STATE`). Filing moves the license `ACTIVE → RENEWAL_REVIEW` and creates the renewal application, which passes through `FILED` and into `UNDER_REVIEW` within the same request — filing and review-open are one operation. A `TransferReviewer` then decides with a `decision` of `GRANT` or `DENY`; deciding an application that is not `UNDER_REVIEW` fails with `ERR_RENEWAL_INVALID_STATE`. A grant moves the application to `GRANTED`, returns the license to `ACTIVE`, and extends `term_end` by 3650 days, so the renewal cycle may repeat when the new window arrives. A denial moves the application to `DENIED` and the license `RENEWAL_REVIEW → TERMINATED`, and cascades: every transfer application of the license still `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is denied, and the product's `available_supply` entry increases by 1. Both `GRANTED` and `DENIED` are terminal for the application.

## 4. Endpoint Definitions

Operations that create a new resource — a band plan, license area, license block, auction, applicant, clock round, bid, assignment bid, transfer application, incumbent, or renewal application — return `201 Created`. Operations that read a resource, modify one, or drive a state transition on an existing one — including the clock endpoint — return `200 OK`. Rows marked "Any" are readable by all four roles. Request and response shapes are not repeated here; they are reconstructed from the narratives of §2 and §3 together with each row's description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the time-driven sweeps | AuctionAdmin |
| POST | `/spectrum-auctions/band-plans` | Create a band plan in DRAFT | AuctionAdmin |
| GET | `/spectrum-auctions/band-plans/{id}` | Read one band plan | Any |
| POST | `/spectrum-auctions/band-plans/{id}/publish` | Publish a DRAFT plan, freezing its structure | AuctionAdmin |
| POST | `/spectrum-auctions/license-areas` | Add a license area to a DRAFT plan | AuctionAdmin |
| GET | `/spectrum-auctions/band-plans/{id}/license-areas` | List the license areas of a plan | Any |
| POST | `/spectrum-auctions/license-blocks` | Add a license block category to a DRAFT plan | AuctionAdmin |
| GET | `/spectrum-auctions/band-plans/{id}/license-blocks` | List the license blocks of a plan | Any |
| POST | `/spectrum-auctions/auctions` | Create an auction against a PUBLISHED plan | AuctionAdmin |
| GET | `/spectrum-auctions/auctions/{id}` | Read one auction (status, round number, totals, supply) | Any |
| GET | `/spectrum-auctions/band-plans/{id}/auctions` | List the auctions of a plan | Any |
| POST | `/spectrum-auctions/auctions/{id}/phase` | Drive the auction phase machine | AuctionAdmin |
| POST | `/spectrum-auctions/applicants` | Self-register as an applicant for an open auction | Bidder |
| GET | `/spectrum-auctions/applicants/{id}` | Read one applicant (credit, eligibility, ledger, status) | Any |
| GET | `/spectrum-auctions/auctions/{id}/applicants` | List the applicants of an auction | Any |
| PATCH | `/spectrum-auctions/applicants/{id}/disclosure` | Update disclosure fields (OCC-guarded) | Bidder |
| POST | `/spectrum-auctions/applicants/{id}/upfront-payments` | Add to the upfront deposit | Bidder |
| POST | `/spectrum-auctions/applicants/{id}/review` | Drive applicant review (start, qualify, correct, reject, disqualify) | AuctionAdmin |
| POST | `/spectrum-auctions/applicants/{id}/resubmit` | Resubmit a corrected application (OCC-guarded) | Bidder |
| POST | `/spectrum-auctions/applicants/{id}/withdraw` | Withdraw an application | Bidder |
| POST | `/spectrum-auctions/auctions/{id}/rounds` | Open the next clock round | AuctionAdmin |
| GET | `/spectrum-auctions/auctions/{id}/rounds` | List the rounds of an auction | Any |
| GET | `/spectrum-auctions/rounds/{id}` | Read one clock round (prices, demand, stage, status) | Any |
| POST | `/spectrum-auctions/rounds/{id}/close` | Close an open round | AuctionAdmin |
| POST | `/spectrum-auctions/rounds/{id}/bids` | Place a clock bid | Bidder |
| GET | `/spectrum-auctions/rounds/{id}/bids` | List the bids of a round | Any |
| GET | `/spectrum-auctions/applicants/{id}/bids` | List the bids placed by an applicant | Any |
| POST | `/spectrum-auctions/auctions/{id}/assignment-bids` | File a sealed assignment bid | Bidder |
| GET | `/spectrum-auctions/auctions/{id}/assignment-bids` | List the assignment bids of an auction | Any |
| GET | `/spectrum-auctions/applicants/{id}/assignment-bids` | List the assignment bids filed by an applicant | Any |
| GET | `/spectrum-auctions/licenses` | List/search licenses | Any |
| GET | `/spectrum-auctions/licenses/{id}` | Read one license (prices, credit, payments, term, lease, status) | Any |
| POST | `/spectrum-auctions/licenses/{id}/settlement-payments` | Pay toward the settlement balance | Bidder |
| GET | `/spectrum-auctions/licenses/{id}/buildout-milestones` | List the buildout milestones of a license | Any |
| POST | `/spectrum-auctions/buildout-milestones/{id}/file-notice` | File a coverage notice (OCC-guarded) | Bidder |
| POST | `/spectrum-auctions/buildout-milestones/{id}/review` | Review a filed milestone | AuctionAdmin |
| POST | `/spectrum-auctions/licenses/{id}/transfer-applications` | File a transfer or lease application | Bidder |
| GET | `/spectrum-auctions/licenses/{id}/transfer-applications` | List the transfer applications of a license | Any |
| GET | `/spectrum-auctions/applicants/{id}/transfer-applications` | List the transfer applications involving an applicant | Any |
| GET | `/spectrum-auctions/transfer-applications/{id}` | Read one transfer application | Any |
| POST | `/spectrum-auctions/transfer-applications/{id}/review` | Adjudicate a transfer application | TransferReviewer, Bidder |
| POST | `/spectrum-auctions/transfer-applications/{id}/withdraw` | Withdraw a transfer application | Bidder |
| POST | `/spectrum-auctions/incumbents` | Register an incumbent in a license area | AuctionAdmin |
| GET | `/spectrum-auctions/incumbents` | List/search incumbents | Any |
| GET | `/spectrum-auctions/incumbents/{id}` | Read one incumbent (windows, shares, status) | Any |
| POST | `/spectrum-auctions/incumbents/{id}/transition` | Drive the incumbent relocation machine | IncumbentOperator, AuctionAdmin |
| POST | `/spectrum-auctions/licenses/{id}/renewal-applications` | File for license renewal | Bidder |
| GET | `/spectrum-auctions/licenses/{id}/renewal-applications` | List the renewal applications of a license | Any |
| POST | `/spectrum-auctions/renewal-applications/{id}/decide` | Grant or deny a renewal | TransferReviewer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_CLOSED` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BAND_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_BAND_PLAN_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_AREA_CODE` | 409 Conflict |
| `ERR_DUPLICATE_BLOCK_CATEGORY` | 409 Conflict |
| `ERR_AUCTION_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_DEADLINE_NOT_PASSED` | 409 Conflict |
| `ERR_NO_QUALIFIED_BIDDERS` | 422 Unprocessable Entity |
| `ERR_APPLICANT_INVALID_STATE` | 409 Conflict |
| `ERR_OWNERSHIP_TOTAL_INVALID` | 422 Unprocessable Entity |
| `ERR_CREDIT_CLAIM_CONFLICT` | 422 Unprocessable Entity |
| `ERR_QUIET_PERIOD_VIOLATION` | 409 Conflict |
| `ERR_UPFRONT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_WITHDRAWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ROUND_NOT_OPEN` | 409 Conflict |
| `ERR_BID_EXCEEDS_ELIGIBILITY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BID` | 409 Conflict |
| `ERR_SUPPLY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NOT_A_WINNER` | 403 Forbidden |
| `ERR_DUPLICATE_ASSIGNMENT_BID` | 409 Conflict |
| `ERR_ASSIGNMENT_BIDS_INCOMPLETE` | 409 Conflict |
| `ERR_LICENSE_INVALID_STATE` | 409 Conflict |
| `ERR_INCUMBENTS_NOT_CLEARED` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_COVERAGE_BELOW_REQUIREMENT` | 422 Unprocessable Entity |
| `ERR_MILESTONE_INVALID_STATE` | 409 Conflict |
| `ERR_LEASE_DATES_INVALID` | 422 Unprocessable Entity |
| `ERR_LEASE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TRANSFER_INVALID_STATE` | 409 Conflict |
| `ERR_TRANSITION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INCUMBENT_INVALID_STATE` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RENEWAL_INVALID_STATE` | 409 Conflict |
| `ERR_INSUFFICIENT_UPFRONT` | 422 Unprocessable Entity |
