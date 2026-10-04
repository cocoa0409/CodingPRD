# Closeout Deal Stores API — Product Requirements Document

## 1. Introduction

Closeout retail lives and dies on the buy. A closeout chain acquires irregular inventory — manufacturer overruns, package-change lots, insurance-salvage recoveries — at deep discounts, then prices, allocates, and sells those finite lots across a store fleet before the deal goes stale. This document specifies the product requirements for the Closeout Deal Stores API, the operational backbone for that model: a system in which every lot of goods is bought once, screened for safety, priced against a substantiated comparison price under jurisdictional advertising rules, allocated to stores by performance tier, and sold under deal-driven aisle layouts with quantity-limited signage and loyalty-club member pricing.

The domain imposes unusual pressures that a naive inventory API cannot absorb. Salvage and distressed goods require safety screening — recall checks, expiration checks, condition verification — with strict segregation of duties between the buyer who sourced a lot and the officer who screens it. Advertising a "was" price is regulated: some jurisdictions demand a substantiation window, some anchor the comparison to a vendor-declared MSRP, and some prohibit comparison advertising outright. Lots are finite, so allocation across the fleet is a waterfall ordered by store performance tier, and unsold goods cycle through markdown, secondary liquidation, or scrap. Because the assortment changes with every buy, store layouts are deal-dependent: a lot occupies an aisle only while a time-windowed aisle assignment says so, and each new buy supersedes the last occupant.

Timing matters as much as money. The system maintains a logical clock, driven by an administrative capability, which governs early-access event windows, sell-through pacing evaluation, refund windows, and the timestamps recorded on every transition. Operators across seven roles — from the sourcing buyer to the anonymous guest at the register — interact with the same lot at different stages of its life, and the API enforces the boundaries between them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that apply to every resource and every request.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which specifies their operational capacity. The system recognizes eight roles, spelled exactly as follows: `Admin`, `SourcingBuyer`, `SafetyOfficer`, `PricingLead`, `AllocationManager`, `StoreManager`, `ClubMember`, and `Anonymous`.

A request missing `X-User-Role`, carrying a role value outside this set, or missing `X-User-ID` for any role other than `Anonymous` is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`. Two further authorization refinements apply to purchases: when a `ClubMember` places a purchase carrying a `member_id`, the `X-User-ID` header must equal that `member_id` — a member may not transact under another member's identity — and an `Anonymous` caller must not supply a `member_id` at all.

The identity of `X-User-ID` differs by role. When `X-User-Role` is `ClubMember`, `X-User-ID` is the `id` of the acting `LoyaltyMember`; ownership checks on any resource that references a `LoyaltyMember` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Admin`, `SourcingBuyer`, `SafetyOfficer`, `PricingLead`, `AllocationManager`, `StoreManager`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `created_by_user_id` on a BuyLot or `screener_user_id` on a SafetyScreening where a workflow writes it — but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Vendor, JurisdictionRule, Store, BuyLot, SafetyScreening, Allocation, AisleAssignment, LoyaltyMember, EarlyAccessEvent, Purchase, and Disposition — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-09-01T00:00:00.000Z`) recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer starting at 1 on creation and incremented by 1 on every modification. Recomputing derived quantities on a resource — for example refreshing a lot's `landed_unit_cost_cents` after a passed screening — is a mutation and therefore bumps `updated_at` and `version` just as a direct edit would.

Lifecycle-bearing resources additionally expose a `status` field (or, on a lot, the paired `commercial_status` and `safety_status` fields) whose exact enumeration values are spelled out where each workflow is described in §3.

### 2.5. The Logical Clock

All time-dependent behavior in the system — event windows, pacing evaluation, refund eligibility, supersede timestamps — reads a single server-maintained logical clock, never wall-clock time. Before any administrative adjustment, the logical clock starts at exactly `2026-09-01T00:00:00Z`. An `Admin`-only test-driving capability advances the logical clock to a supplied instant expressed by the `to_iso8601` field; the clock never falls back to wall-clock time on its own. Advancing the clock is itself an event with side effects: early-access events whose windows now cover the current instant move from `SCHEDULED` to `ACTIVE`, events whose end has passed move from `ACTIVE` to `ENDED`, and the sell-through pacing evaluation described in §3.7 runs across the fleet.

### 2.6. Validation Order and Nested Resource Retrieval

Every request passes through a fixed, ordered validation cascade, and the order is observable: when several checks would fail, the earliest one wins. Authentication of the headers comes first (missing or malformed identity produces `ERR_UNAUTHENTICATED`, a role mismatch or identity violation produces `ERR_UNAUTHORIZED`). Existence checks come next: path identifiers are validated left-to-right, and body foreign-key references such as `vendor_id`, `home_jurisdiction_id`, `jurisdiction_id`, `store_id`, `lot_id`, `member_id`, and `home_store_id` must resolve to existing resources, with any failure reported as `ERR_NOT_FOUND`. Lifecycle-state checks (`ERR_INVALID_STATE`) follow, then domain business rules — safety gating, store status, layout presence, segregation of duties, reconciliation, window geometry, advertising law, temporal windows, and fiscal sufficiency — each paired with its own error identifier and detailed in §3. Request-shape validation (required fields, types, enum membership, quantity floors, no unknown fields, and the presence of required optimistic-concurrency fields) is enforced as `ERR_INVALID_REQUEST`, and the optimistic-concurrency check itself (`ERR_STALE_VERSION`) is evaluated after authentication and existence, as its own distinct step. For nested paths such as a screening completion under a lot, a nonexistent lot is reported before a nonexistent screening beneath it.

### 2.7. Monetary Values and Precision

All money in the system is integer cents. Prices, costs, and recoveries — `total_cost_cents`, `comparison_price_cents`, `vendor_msrp_cents`, `retail_price_cents`, `recovery_cents`, `unit_price_cents`, `line_total_cents`, `landed_unit_cost_cents` — are whole-cent integers; where a division produces a fractional cent, the result is rounded half-up to zero decimal places. Discount percentages are integers between 0 and 100 inclusive, except the advertised-discount computation described in §3.5, which is carried to two decimal places rounded half-up before comparison against the jurisdictional cap. Per-unit rounding is pinned at the unit level for purchases (see §3.6); line totals are never rounded a second time.

### 2.8. Optimistic Concurrency Control

Two write operations in the system legitimately supersede prior state, and both are protected by optimistic concurrency control. Creating an aisle assignment on a store must carry `expected_store_version`, the client's last observed `version` of that store; if the store's current `version` no longer matches — because another writer has advanced it since the client last read the store — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a supersede built on an outdated view of the layout. Creating a disposition on a lot must likewise carry `expected_lot_version` matching the lot's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's picture of the lot's pricing and allocation state is out of date. These two OCC fields are non-optional on their respective endpoints and are part of request shape. Endpoints not named here take no version field.

### 2.9. Unit Conservation Across the Lot Ledger

A BuyLot is a closed ledger of physical units. At every moment, the lot's `quantity_total` equals the sum of five buckets: `qty_pool` (unallocated warehouse units), `qty_allocated_outstanding` (units committed to or sitting at stores), `qty_sold` (units sold and not refunded), `qty_liquidated` (units sent to secondary liquidation), and `qty_scrapped` (units destroyed). The outstanding bucket itself is the sum of `qty_granted` across allocations in `CONFIRMED` or `SHIPPED` status, plus the `store_on_hand_qty` across allocations in `RECEIVED` status. Releasing an allocation is the compensating action that returns units to the pool, and the conservation sum must be identical before and after every allocation or purchase mutation. A computed lot snapshot exposes these conservation fields alongside cost and pacing data so operators can audit the invariant directly.

### 2.10. Safety Gate as a Cross-Cutting Precondition

A lot's `safety_status` is independent of its `commercial_status` and acts as a cross-cutting gate. Three operations — selling units of a lot at a store, assigning a lot to an aisle, and proposing a warehouse allocation from a lot — all require the lot's `safety_status` to be `CLEARED`. A lot that is `BLOCKED`, or one that has never passed a screening, is rejected from all three with `ERR_LOT_SAFETY_BLOCKED`. This gate sits ahead of layout, membership, pricing, and fiscal checks in the validation order.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Vendors, Jurisdictions, Stores, and Members

Before any lot can be sourced, the reference data must exist. A `SourcingBuyer` or `Admin` registers a **Vendor** with a display `name` and a `vendor_code` that is unique across all vendors. A `PricingLead` or `Admin` authors a **JurisdictionRule**, identified by a unique `jurisdiction_code` (for example a state or territory code), which fixes the advertising regime for stores and lots under its authority: a `comparison_rule` of `WAS_NOW_WINDOW`, `MSRP_REFERENCE`, or `COMPARISON_PROHIBITED`; a `max_advertised_discount_pct` between 0 and 100 bounding how deep an advertised discount versus the comparison price may run; and a `member_discount_cap_pct`, also between 0 and 100, capping the combined member discount off retail in that jurisdiction. Rules of the `WAS_NOW_WINDOW` kind additionally carry `window_days`, the substantiation lookback window in days, and `required_offer_days`, the number of days the comparison price must have been offered inside that window; both are required for that rule and absent otherwise.

An `Admin` registers a **Store** with a `name`, a fleet-unique `store_code`, the `jurisdiction_id` of its governing advertising rule, and a `performance_tier` of `TIER_1`, `TIER_2`, or `TIER_3` that drives allocation priority — `TIER_1` is served first. A store is born `ACTIVE` and may later be suspended or reactivated by an `Admin`, who may also retune its `performance_tier` through the same store update; each such update increments the store's `version`. A `SUSPENDED` store refuses new business: allocation proposals naming it, aisle assignments created on it, and purchases attempted at it are all rejected with `ERR_STORE_SUSPENDED`.

Loyalty membership is open enrollment: an `Anonymous` caller or an `Admin` registers a **LoyaltyMember** with a fleet-unique `member_code`, a `tier` of `BRONZE`, `SILVER`, or `GOLD`, and a `home_store_id` anchoring the member to a store. Members are created `ACTIVE`; an `Admin` may suspend or reactivate a member or change their `tier`, incrementing the member's `version` with each update. A purchase that names a `SUSPENDED` member is rejected with `ERR_MEMBER_SUSPENDED`.

### 3.2. Sourcing a Buy Lot

A deal begins when a `SourcingBuyer` (or `Admin`) acquires a **BuyLot**. The acquisition payload carries the sourcing `vendor_id`, the `home_jurisdiction_id` whose rules will govern lot-level price substantiation, a human-readable `title`, the `source_type` of the buy — `MFR_OVERRUN`, `PACKAGE_CHANGE`, or `INSURANCE_SALVAGE` — and the buyer-declared `condition_grade` of `A`, `B`, `C`, or `MIXED`. The commercial terms are `quantity_total` (total sellable units acquired), `total_cost_cents` (the all-in acquisition cost), and `est_sellable_qty` (the buyer's estimate of sellable units, used as the provisional cost basis). Pricing substance is captured up front in `comparison_price_cents` (the substantiated comparison or "was" unit price) and `vendor_msrp_cents` (the vendor-declared MSRP used by the MSRP-reference regime). Sell-through expectations are set via `pace_target_units_per_week`, the target units per trailing seven-day window.

The lot is created directly in `commercial_status` `SOURCED` with `safety_status` `PENDING_SCREEN`; its `retail_price_cents` is unset, `advertises_comparison` defaults to false, `sellable_qty_confirmed` is null until a screening passes, `markdown_rounds` is 0, `on_sale_since` is null until first sale, `qty_liquidated` and `qty_scrapped` are 0, and the entire `quantity_total` sits in `qty_pool`. The server stamps `created_by_user_id` from the caller's `X-User-ID` — this becomes the segregation-of-duties anchor for screening — and the lot's `landed_unit_cost_cents` is computed immediately using the provisional variant described in §3.5. A read-only summary view of the lot reports `qty_pool`, `qty_allocated_outstanding`, `qty_sold`, `qty_liquidated`, `qty_scrapped`, `landed_unit_cost_cents`, `markdown_rounds`, `commercial_status`, `safety_status`, and `pace_window_units_sold` (the units sold within the current trailing pacing window). Lots may be listed with optional `commercial_status`, `vendor_id`, and `source_type` filters alongside the standard pagination parameters.

### 3.3. Safety Screening and the Regrade Loop

Salvage and distressed goods cannot be sold until screened. A `SafetyOfficer` opens a **SafetyScreening** round on a lot; the screening is created `PENDING` with a `round_number` equal to one more than the count of prior screenings for that lot, and `screener_user_id` stamped from the caller. Segregation of duties is enforced at the moment of opening: the screening officer's identity must differ from the lot's `created_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Opening a screening against a lot in `SOURCED` advances the lot to `SCREENING`. Screenings may also be opened against lots in `ON_SALE` or `DISPOSITION_REVIEW` — this is the post-market recall re-screen path, and it does not change the lot's commercial status at open time.

Completing a screening requires the officer to record the `recall_check` (`PASS` or `FAIL`), the `expiration_check` (`PASS`, `FAIL`, or `NA`), whether the observed condition matched the declared grade via `condition_verified`, and the observed grade counts `qty_grade_a`, `qty_grade_b`, and `qty_grade_c`, with optional `notes`. Only a `PENDING` screening can be completed — attempting otherwise is `ERR_INVALID_STATE` — and the three grade counts must reconcile exactly to the lot's `quantity_total`, or the completion is rejected with `ERR_GRADE_SUM_MISMATCH`. On completion the screening's `result` is derived in a fixed order: a failed recall check yields `FAILED_RECALL`; otherwise a failed expiration check yields `FAILED_EXPIRATION`; otherwise a condition mismatch yields `FAILED_CONDITION`; otherwise the screening is `PASSED`. The screening then sits terminally in `COMPLETED` with `completed_at` stamped from the logical clock — a completed screening is never edited.

The lot's fate follows the result. A `PASSED` screening moves the lot from `SCREENING` to `CLEARED`, sets `safety_status` to `CLEARED`, records `sellable_qty_confirmed` as the sum of the three observed grade counts, and recomputes `landed_unit_cost_cents` using the final variant of §3.5. A `FAILED_RECALL` or `FAILED_EXPIRATION` result sets `safety_status` to `BLOCKED` and drives the lot to `BLOCKED` — whether it was in `SCREENING`, `ON_SALE`, or `DISPOSITION_REVIEW` — and triggers a two-link cascade. First, every allocation of the lot in `PROPOSED` or `CONFIRMED` status is cancelled, and each cancelled `CONFIRMED` allocation returns its `qty_granted` to the lot's `qty_pool`. Second, for every store whose allocation was cancelled in the first link, that store's `ACTIVE` aisle assignments referencing the lot are superseded with `valid_to` set to the block timestamp. A `FAILED_CONDITION` result leaves the lot in `SCREENING` and opens the regrade loop: a `SourcingBuyer` may submit a revised `condition_grade` for the lot, which updates the declared grade, resets `safety_status` to `PENDING_SCREEN`, returns the lot to `SOURCED`, and bumps the lot's `version` — ready for a fresh screening round.

### 3.4. Retail Pricing Under Advertising Law

Once a lot is `CLEARED` in both commercial and safety status, a `PricingLead` sets its retail price. The pricing payload carries `retail_price_cents` and the `advertises_comparison` flag declaring whether signage will advertise the comparison price. Both are recorded on the lot — `advertises_comparison` is fixed at pricing — and the lot moves from `CLEARED` to `PRICED`, with `version` incremented. Pricing is gated by the advertising-law engine of §3.5 evaluated against the lot's home jurisdiction; a lot priced in violation never leaves `CLEARED`.

### 3.5. Deal Mathematics: Unit Cost and Advertised Price Legality

Two calculations underpin the economics of every lot, and their precision rules are part of the contract.

**Landed unit cost** comes in two variants. Before any screening has passed, the provisional variant divides the lot's `total_cost_cents` by `est_sellable_qty` and rounds half-up to a whole cent. After the first `PASSED` screening, the final variant divides `total_cost_cents` by a grade-weighted effective quantity — each observed grade-A unit counts in full, each grade-B unit counts as eight-tenths of a unit, and each grade-C unit counts as six-tenths — again rounding half-up to a whole cent. The two variants deliberately produce different values for identical cost data whenever the observed grade mix deviates from the buyer's estimate.

**Advertised price legality** is evaluated at pricing time against the lot's home jurisdiction, and the prohibited-comparison branch is re-checked at aisle-assignment time against the store's jurisdiction. The engine branches on the jurisdiction's `comparison_rule`:

- Under `COMPARISON_PROHIBITED`, `advertises_comparison` must be false; pricing a lot to advertise a comparison price in such a jurisdiction, or creating an aisle assignment at a store in such a jurisdiction for a lot whose `advertises_comparison` is true, is rejected with `ERR_COMPARISON_ADVERTISING_PROHIBITED`.
- Under `WAS_NOW_WINDOW`, the `comparison_price_cents` must be at least the retail price marked up by twenty percent — that is, at least the retail price multiplied by 1.20, with the anchor computed in whole cents rounded half-up, and the comparison boundary inclusive — otherwise `ERR_ANCHOR_PREMIUM_INSUFFICIENT`. The advertised discount percent is then computed as the difference between the comparison price and the retail price, expressed in hundredths of a percent of the comparison price with the final figure rounded half-up to two decimal places; if that figure exceeds the jurisdiction's `max_advertised_discount_pct`, the pricing is rejected with `ERR_ADVERTISED_DISCOUNT_TOO_DEEP`, with the cap boundary inclusive.
- Under `MSRP_REFERENCE`, the `comparison_price_cents` must equal the lot's `vendor_msrp_cents` exactly, else `ERR_COMPARISON_NOT_MSRP`, and the `retail_price_cents` must not exceed the comparison price — a retail above the comparison is rejected as `ERR_ADVERTISED_DISCOUNT_TOO_DEEP`.

### 3.6. Selling at the Register: Members, Events, Signage, and Stock

A sale is recorded by creating a **Purchase** at a store — the caller is a `ClubMember` buying for themselves or an `Anonymous` guest. The payload carries the `lot_id`, the `qty` purchased, and optionally the `member_id` (absent for guests). The purchase endpoint runs the strictest validation cascade in the system, evaluated in this order. First, the lot must be in a sellable lifecycle state: `ON_SALE`, `DISPOSITION_REVIEW`, or `BLOCKED` all pass the state check — a `BLOCKED` lot deliberately passes through so the safety gate, not the state gate, owns the rejection — and any other commercial status yields `ERR_INVALID_STATE`. Second, the lot's `safety_status` must be `CLEARED`, else `ERR_LOT_SAFETY_BLOCKED`. Third, the store must be `ACTIVE`, else `ERR_STORE_SUSPENDED`. Fourth, the deal-dependent layout gate: an `ACTIVE` aisle assignment covering the current instant must exist for the store and lot — `valid_from` at or before now, and either no `valid_to` or `valid_to` at or after now — else `ERR_NO_ACTIVE_ASSIGNMENT`. Fifth, a supplied `member_id` must reference an `ACTIVE` member, else `ERR_MEMBER_SUSPENDED`. Sixth, while any early-access event of the lot is `ACTIVE` at the current instant, a `member_id` is mandatory — member-only early access — and a guest attempt is rejected with `ERR_EARLY_ACCESS_MEMBER_ONLY`. Seventh, during such an event the member's `tier` must rank at or above the event's `min_tier` (bronze below silver below gold), else `ERR_MEMBER_TIER_TOO_LOW`. Eighth, the combined member discount must respect the jurisdictional cap described below, else `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED`. Ninth, the quantity-limited signage rule: the units already purchased for this store and lot on the current UTC day by this member — or by the shared guest bucket when no member is involved — plus the requested `qty` must not exceed the covering assignment's `daily_unit_limit`, else `ERR_SIGNAGE_LIMIT_EXCEEDED`. Tenth, the store's shelf must hold the goods: `qty` must not exceed the `store_on_hand_qty` of the store's received allocation for the lot, else `ERR_INSUFFICIENT_STORE_STOCK`.

Pricing then follows a pinned evaluation order — rounding order matters, and rounding never happens at line level. The discount percent is determined first: guests (no `member_id`) pay full freight with a percent of zero and `pricing_variant` `GUEST`; a member purchase with no `ACTIVE` event covering the instant takes the tier discount — five percent for `BRONZE`, ten for `SILVER`, fifteen for `GOLD` — with `pricing_variant` `STANDARD`; a member purchase during an `ACTIVE` event whose tier qualifies takes the tier discount plus the event's `extra_discount_pct`, with `pricing_variant` `EVENT`. The cap gate is applied before charging: if the combined percent exceeds the selling store's jurisdiction `member_discount_cap_pct` the sale is rejected — a combined percent exactly equal to the cap is allowed. The per-unit price is the lot's current `retail_price_cents` reduced by that percent, rounded half-up to a whole cent and recorded as `unit_price_cents`; the `line_total_cents` is exactly the per-unit price multiplied by `qty` with no further rounding. The purchase is recorded in `COMPLETED` status, its `discount_pct_applied` and `pricing_variant` preserved for audit. Completion decrements the received allocation's `store_on_hand_qty` by `qty` and refreshes the lot's `qty_sold`. If the sale empties the pipeline — `qty_pool`, `qty_allocated_outstanding`, `qty_liquidated`, and `qty_scrapped` all zero — the lot closes automatically to `CLOSED_SOLD_OUT`.

A `StoreManager` may refund a `COMPLETED` purchase within fourteen days of its creation — the boundary is inclusive, so a refund at exactly fourteen days is allowed; beyond it the attempt fails with `ERR_REFUND_WINDOW_EXPIRED`. Refunds are also refused once the lot has been terminally liquidated or scrapped (`CLOSED_LIQUIDATED` or `CLOSED_SCRAPPED`), surfacing `ERR_INVALID_STATE`. A successful refund flips the purchase to `REFUNDED`, stamps `refunded_at` from the logical clock, credits the `qty` back to the stocking allocation's `store_on_hand_qty`, and recomputes the lot's `qty_sold` downward. Because `qty_sold` derives only from `COMPLETED` purchases, a purchase-then-refund pair leaves the lot's sold count, the allocation's on-hand units, and the sum of line totals across the lot's completed purchases exactly as they were before the sale. And if the lot sat in `CLOSED_SOLD_OUT`, the returning units reopen it to `ON_SALE` at its current retail price.

### 3.7. Sell-Through Pacing and the Markdown–Disposition Cycle

Every advance of the logical clock triggers a fleet-wide pacing evaluation. A lot is eligible only while `ON_SALE` and only after at least three full selling days have elapsed since `on_sale_since` — selling days are counted as whole days between then and now. For each eligible lot, the system totals the units sold within the trailing seven-day window: purchases of the lot in `COMPLETED` status whose creation falls in the half-open window from seven days before now up to now (refunded purchases are excluded because their status is `REFUNDED`). If twice that trailing total is strictly less than the lot's `pace_target_units_per_week` — that is, the pace has fallen strictly below half of target, with an exact fifty-percent pace not triggering — the lot moves from `ON_SALE` to `DISPOSITION_REVIEW`.

A lot under review is resolved through **Disposition** records created by a `SourcingBuyer`. Creating a disposition requires `expected_lot_version` per §2.8 and an `action` of `MARKDOWN`, `LIQUIDATE`, or `SCRAP`; a `MARKDOWN` additionally requires a `markdown_pct` between 1 and 50 inclusive, and a `LIQUIDATE` requires a `liquidator_ref` and a non-negative `recovery_cents`. A disposition is born `PENDING`, and creating a new one supersedes the lot's prior `PENDING` disposition, moving it to `SUPERSEDED`. Markdown and liquidation dispositions may only be created while the lot is `ON_SALE` or `DISPOSITION_REVIEW`; scrap dispositions require the lot to be `BLOCKED` or `DISPOSITION_REVIEW` — a mismatch is `ERR_INVALID_STATE`.

Applying a `PENDING` disposition executes the chosen exit. Applying a `MARKDOWN` reduces the lot's `retail_price_cents` by the stated percent — the new price is the current price multiplied by the complement of the markdown percent, rounded half-up to a whole cent — increments `markdown_rounds`, marks the disposition `APPLIED` with `applied_at` stamped, and loops the lot back from `DISPOSITION_REVIEW` to `ON_SALE`, where pacing resumes against the same `on_sale_since`. Applying a `LIQUIDATE` requires that no allocation of the lot remain in `PROPOSED`, `CONFIRMED`, `SHIPPED`, or `RECEIVED` — the outstanding bucket must be empty — then moves all units in `qty_pool` into `qty_liquidated`, empties the pool, marks the disposition `APPLIED`, and closes the lot as `CLOSED_LIQUIDATED`; the closure cascades, superseding every `ACTIVE` aisle assignment referencing the lot with `valid_to` set to the close timestamp and cancelling every `SCHEDULED` or `ACTIVE` early-access event of the lot. Applying a `SCRAP` — permitted from `DISPOSITION_REVIEW` or from `BLOCKED` — likewise requires an empty outstanding bucket, moves the pool into `qty_scrapped`, marks the disposition `APPLIED`, and closes the lot as `CLOSED_SCRAPPED`. The three closed states are terminal.

### 3.8. Fleet Allocation: The Tier-Ordered Waterfall

Units move from the warehouse pool to stores through **Allocation** records managed by an `AllocationManager`. Proposing an allocation names the destination `store_id` and a `qty_requested`; the requested quantity must not exceed the lot's unallocated `qty_pool` at proposal time, else `ERR_INSUFFICIENT_LOT_QUANTITY`, and the lot's safety and the store's standing are gated per §2.10 and §3.1. The allocation is created `PROPOSED` with `qty_granted` at zero — a proposal holds no pool units.

Committing runs the waterfall over every `PROPOSED` allocation of the lot. Candidates are ordered by destination store's `performance_tier` — `TIER_1` before `TIER_2` before `TIER_3` — with ties broken by allocation creation time, earliest first; the allocation identifier is never consulted. Each allocation in turn is granted the smaller of its `qty_requested` and the remaining pool; a grant greater than zero moves the allocation to `CONFIRMED` and draws the pool down, while a zero grant leaves the allocation `PROPOSED` and the waterfall continues to the next candidate. The commit reports how many allocations were granted and the total units granted. When a commit on a `PRICED` lot grants any units at all, the lot moves to `ON_SALE` and `on_sale_since` is stamped from the logical clock — the deal is live.

From `CONFIRMED`, an allocation's lifecycle is operational: shipping moves it to `SHIPPED`; a shipment recall returns it from `SHIPPED` to `CONFIRMED` with no pool movement, the units staying committed to the store; receiving at the store moves it to `RECEIVED` and sets `store_on_hand_qty` equal to the granted quantity. Release is the compensating exit: releasing a `CONFIRMED` allocation returns its full `qty_granted` to the lot's pool, while releasing a `RECEIVED` allocation returns whatever `store_on_hand_qty` remains and zeroes that field — units already sold stay counted in the lot's `qty_sold`. A `PROPOSED` allocation may simply be cancelled; since it holds no pool units, cancellation is a pure status change. `RELEASED` and `CANCELLED` are terminal. Any lifecycle action on an allocation in the wrong state is `ERR_INVALID_STATE`.

### 3.9. Deal-Driven Layouts: Aisle Assignments and Early Access

Because the assortment changes with every buy, shelf placement is data. A `StoreManager` assigns a lot to an aisle by creating an **AisleAssignment** naming the `lot_id`, an `aisle_code`, and a `daily_unit_limit` — the quantity-limited signage cap on units per member (or per shared guest bucket) per UTC day at that store. The assignment window runs from `valid_from` (inclusive, defaulting to the current logical-clock instant) to `valid_to` (inclusive, or open-ended when null), and the assignment is created `ACTIVE`. Creation carries the `expected_store_version` OCC field per §2.8 and bumps the store's `version`.

Aisle windows on the same store and `aisle_code` follow closed-interval semantics: touching endpoints conflict. A new assignment that overlaps an existing `ACTIVE` assignment on the same aisle is rejected with `ERR_AISLE_WINDOW_CONFLICT` unless the caller passes `supersede` as true, in which case the prior assignment is superseded — its `valid_to` rewritten to one second before the new assignment's `valid_from` — and the new deal takes the aisle. Aisle assignments are also superseded by cascade when their lot is blocked or liquidated, per §3.3 and §3.7. The advertising-law gate of §3.5 applies here too: creating an assignment at a store whose jurisdiction prohibits comparison advertising, for a lot that advertises its comparison price, is rejected with `ERR_COMPARISON_ADVERTISING_PROHIBITED`.

A `PricingLead` sweetens a deal by scheduling an **EarlyAccessEvent** on a lot that is `PRICED` or `ON_SALE`. The event carries `starts_at` and `ends_at` defining a half-open window — the start instant is included, the end instant excluded — plus a `min_tier` admitting only members at or above that tier, and an `extra_discount_pct` between 0 and 100 stacked onto the member's tier discount during the event. The window must be strictly positive — an end at or before the start is `ERR_INVALID_EVENT_WINDOW` — and must not overlap any `SCHEDULED` or `ACTIVE` event on the same lot under half-open semantics, where one event ending exactly when another begins is allowed; a true overlap is `ERR_EVENT_WINDOW_OVERLAP`. Events are created `SCHEDULED`, activate and end automatically as the logical clock crosses their boundaries, and may be cancelled while `SCHEDULED` or `ACTIVE`; `ENDED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource in place — pricing a lot, applying a disposition, advancing an allocation's lifecycle, updating a store or member, completing a screening, refunding a purchase — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vendors` | Register a closeout vendor | SourcingBuyer, Admin |
| GET | `/vendors/{id}` | Get a vendor | Any role |
| GET | `/vendors/{id}/lots` | List lots sourced from a vendor | Any role |
| POST | `/jurisdiction-rules` | Create a jurisdictional advertising rule | PricingLead, Admin |
| GET | `/jurisdiction-rules/{id}` | Get a jurisdiction rule | Any role |
| GET | `/jurisdiction-rules/{id}/stores` | List stores governed by a jurisdiction | Any role |
| GET | `/jurisdiction-rules/{id}/lots` | List lots priced under a home jurisdiction | Any role |
| POST | `/stores` | Register a store in the fleet | Admin |
| GET | `/stores/{id}` | Get a store | Any role |
| PATCH | `/stores/{id}` | Suspend/reactivate a store or change its performance tier | Admin |
| GET | `/stores/{id}/allocations` | List allocations destined for a store | Any role |
| GET | `/stores/{id}/aisle-assignments` | List aisle assignments of a store | Any role |
| GET | `/stores/{id}/members` | List loyalty members whose home store this is | Any role |
| GET | `/stores/{id}/purchases` | List purchases at a store | Any role |
| POST | `/lots` | Acquire a closeout lot | SourcingBuyer, Admin |
| GET | `/lots/{id}` | Get a lot | Any role |
| GET | `/lots` | List lots with filters and pagination | Any role |
| GET | `/lots/{id}/summary` | Computed lot snapshot: conservation, cost, pacing | Any role |
| POST | `/lots/{lot_id}/regrade` | Re-grade a lot after a condition-only screening failure | SourcingBuyer |
| POST | `/lots/{id}/screenings` | Open a safety screening round (also post-market re-screen) | SafetyOfficer |
| GET | `/lots/{id}/screenings` | List screening rounds of a lot | Any role |
| POST | `/lots/{lot_id}/screenings/{id}/complete` | Complete a PENDING screening with check results | SafetyOfficer |
| POST | `/lots/{lot_id}/price` | Set the retail price against the substantiated comparison price | PricingLead |
| POST | `/lots/{lot_id}/allocations` | Propose a warehouse allocation of lot units to a store | AllocationManager |
| GET | `/lots/{id}/allocations` | List allocations of a lot | Any role |
| GET | `/lots/{lot_id}/allocations/{id}` | Get a single allocation of a lot | Any role |
| POST | `/lots/{lot_id}/allocations/commit` | Run the tier-ordered waterfall over PROPOSED allocations | AllocationManager |
| POST | `/lots/{lot_id}/allocations/{id}/ship` | Ship a CONFIRMED allocation | AllocationManager |
| POST | `/lots/{lot_id}/allocations/{id}/receive` | Receive a SHIPPED allocation at the store | AllocationManager |
| POST | `/lots/{lot_id}/allocations/{id}/recall` | Recall a SHIPPED allocation back to CONFIRMED | AllocationManager |
| POST | `/lots/{lot_id}/allocations/{id}/release` | Release a CONFIRMED or RECEIVED allocation back to the pool | AllocationManager |
| POST | `/lots/{lot_id}/allocations/{id}/cancel` | Cancel a PROPOSED allocation | AllocationManager |
| POST | `/stores/{store_id}/aisle-assignments` | Assign a deal lot to an aisle with quantity-limited signage | StoreManager |
| GET | `/lots/{id}/aisle-assignments` | List aisle assignments referencing a lot | Any role |
| POST | `/members` | Register a loyalty club member | Anonymous, Admin |
| GET | `/members/{id}` | Get a member | Any role |
| PATCH | `/members/{id}` | Suspend/reactivate a member or change tier | Admin |
| GET | `/members/{id}/purchases` | List purchases of a member | Any role |
| POST | `/lots/{id}/early-access-events` | Schedule a member early-access event window on a lot | PricingLead |
| GET | `/lots/{id}/early-access-events` | List early-access events of a lot | Any role |
| POST | `/lots/{lot_id}/early-access-events/{id}/cancel` | Cancel a SCHEDULED or ACTIVE event | PricingLead |
| POST | `/stores/{store_id}/purchases` | Sell units of a lot at a store (member or guest) | ClubMember, Anonymous |
| GET | `/purchases/{id}` | Get a purchase | Any role |
| POST | `/purchases/{id}/refund` | Refund a COMPLETED purchase within 14 days | StoreManager |
| GET | `/lots/{id}/purchases` | List purchases of a lot across the fleet | Any role |
| POST | `/lots/{id}/dispositions` | Create a disposition; supersedes the prior PENDING one | SourcingBuyer |
| GET | `/lots/{id}/dispositions` | List dispositions of a lot | Any role |
| POST | `/lots/{lot_id}/dispositions/{id}/apply` | Apply a PENDING disposition | SourcingBuyer |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_LOT_SAFETY_BLOCKED` | 409 Conflict |
| `ERR_STORE_SUSPENDED` | 409 Conflict |
| `ERR_NO_ACTIVE_ASSIGNMENT` | 409 Conflict |
| `ERR_MEMBER_SUSPENDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_GRADE_SUM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AISLE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EARLY_ACCESS_MEMBER_ONLY` | 403 Forbidden |
| `ERR_MEMBER_TIER_TOO_LOW` | 403 Forbidden |
| `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SIGNAGE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_COMPARISON_ADVERTISING_PROHIBITED` | 422 Unprocessable Entity |
| `ERR_COMPARISON_NOT_MSRP` | 422 Unprocessable Entity |
| `ERR_ANCHOR_PREMIUM_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_ADVERTISED_DISCOUNT_TOO_DEEP` | 422 Unprocessable Entity |
| `ERR_INVALID_EVENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_REFUND_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 409 Conflict |
| `ERR_INSUFFICIENT_STORE_STOCK` | 409 Conflict |
