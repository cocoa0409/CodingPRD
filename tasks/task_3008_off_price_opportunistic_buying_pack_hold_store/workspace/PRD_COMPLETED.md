# Off-Price Opportunistic Buying API — Product Requirements Document

## 1. Introduction

Off-price retail survives on the deal. A vendor cancels a department-store program, a factory overruns a size run, a brand quietly clears last season's goods — and the buyer who can say yes within hours, at the right price, wins margin that planned-assortment retailers never see. This document specifies the API that governs that opportunistic buying motion end to end: from the moment a closeout or cancellation offer lands on a buyer's desk, through open-to-buy adjudication against a seasonal budget, to pack-and-hold warehousing for goods destined for a later season, ticketing with compare-at price substantiation, cluster-based store allocation, in-store markdown cadence, shrink control on mixed and unticketed merchandise, and final liquidation of what does not sell.

The system exists because three disciplines collide in this business and none can be allowed to override the others. The buying desk needs speed and discretion — some vendors will only deal if their identity never appears on a ticket and junior staff never see the lot. Finance needs hard open-to-buy guardrails with liquidity deliberately sequestered for late-season packaway deals, and an accounting trail that distinguishes provisional commitments from finalized spend. Operations needs deterministic, auditable warehouse aging, store allocation by demographic cluster rather than uniform assortment, and a fixed weeks-on-floor markdown cadence that never depends on wall-clock time at the store.

A single logical clock, advanced only by planning leadership, drives every temporal rule in the system — offer expiry, warehouse aging buckets, markdown timing, and release windows all read from it. This makes the full lifecycle reproducible and testable: a season's worth of buying, holding, selling, marking down, and liquidating can be replayed deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts every endpoint obeys: authentication, response envelopes, pagination, resource identity, the logical clock, monetary precision, and optimistic concurrency.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role is checked against the endpoint's authorized role list; a role not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `Buyer`, `PlanningLead`, `AllocationManager`, `InventoryPlanner`, `PricingAnalyst`, `WarehouseClerk`, `StoreOpsLead`, and `ShrinkAuditor`.

Every role in this system is **opaque** with respect to persisted entities: for each of `Buyer`, `PlanningLead`, `AllocationManager`, `InventoryPlanner`, `PricingAnalyst`, `WarehouseClerk`, `StoreOpsLead`, and `ShrinkAuditor`, the `X-User-ID` value is an opaque operator identifier not tied to the `id` of any persisted entity, and the server never compares it against any entity's foreign key. One role carries an additional identity convention layered on top of opacity: a `Buyer` whose `X-User-ID` begins with the prefix `senior-` is treated as **SENIOR tier**; any other buyer id is **JUNIOR tier**. Buyer tier gates visibility and action on discreet vendors, as described in §2.6 and §3.2 — junior buyers may not evaluate, accept, or pass on lots from `CONFIDENTIAL` or `QUIET` vendors, and such lots are hidden from junior buyers on lot reads and listings.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, or a value outside its range, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints sort by `created_at` in ascending order unless otherwise stated; ties on identical `created_at` timestamps are broken by creation (insertion) order, so the ordering is always deterministic. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a standard system-managed field set:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that increments by exactly 1 on every mutation of the resource.

This full set applies to MerchandiseSeason, Vendor, PriceZone, Lot, LotLine, Warehouse, PackawayHold, Store, AllocationPlan, StoreSku, Receipt, ShrinkCase, and LiquidationOrder. Three resources are deliberately lighter: **Ticket**, **ReceiptLine**, and **MarkdownEvent** carry only `id` and `created_at` — both `updated_at` and `version` are absent from these entities, and no concurrency token can be taken against them. Note in particular that voiding a Ticket changes only its `status`; there is no version field to bump.

Whenever any mutation occurs on a versioned resource — including system-driven mutations such as season commitment updates, sweep-driven markdowns, or supersession — the server refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. The Logical Clock

All temporal reasoning in the system — offer expiry, warehouse aging, markdown timing, release windows, receipt and floor dates — reads from a single server-held **logical clock**, never from wall-clock time. Before the clock has ever been set, it reads exactly `2026-09-01T00:00:00Z` (the server startup default); the system must never silently fall back to wall-clock time. A `PlanningLead` advances the clock by POSTing `to_iso8601` to `/_clock/set_current_utc`, and the endpoint returns the resulting `current_utc` as an ISO 8601 UTC timestamp with three fractional digits. Advancing the clock triggers three system sweeps: the offer-expiry sweep cancels every still-`OFFERED` lot whose `offer_expires_at` has been reached (§3.2), the aging sweep recomputes every stored or under-review hold's age bucket and running accrual, and the markdown sweep applies the weeks-on-floor cadence to live store stock, recomputing `weeks_on_floor` as it goes. Date-only inputs such as season windows and release windows are interpreted as UTC midnight of the named date, and any datetime input arriving without an explicit timezone offset is likewise interpreted as UTC.

### 2.6. Vendor Discretion and Brand Protection

Sourcing discretion is a first-class constraint. Each vendor declares a `discretion_level` of `STANDARD`, `CONFIDENTIAL`, or `QUIET`. Lots supplied by `CONFIDENTIAL` or `QUIET` vendors are hidden from non-senior buyers: a junior-tier `Buyer` cannot see them on lot reads or listings — the lots are omitted from listing results, and a junior buyer's direct read of such a lot fails with `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a nonexistent lot — and any attempt by a junior buyer to evaluate, accept, or pass such a lot is rejected with `ERR_VENDOR_DISCRETION` (HTTP 403). Separately, a vendor whose `ticket_discretion_required` flag is true requires brand protection at the shelf: tickets issued for that vendor's goods omit the vendor name, recorded on the ticket as `vendor_name_on_ticket` being false. Discretion also carries a deal-quality cost at evaluation time, quantified in §3.2.

### 2.7. Monetary Values, Precision, and Price-Point Rounding

All money in the system is carried as integer cents; no floating-point money ever crosses the API. Where a computation produces a fractional cent, the result is rounded half-up to integer cents at the pinned point in the formula — per receipt line before summing, per unit basis before multiplying, per store SKU before any aggregate. The one non-integer monetary ratio, the deal quality score, is carried at 2 decimal places with round-half-up rounding. Shelf prices follow the chain's price-point convention: whenever a retail price is computed — at ticket issuance and at every markdown or clearance step — the value is first rounded half-up to integer cents and then adjusted downward to the nearest price ending in 9 cents (so 2452 becomes 2449, and 2400 becomes 2399). The warehouse billing month is fixed at 30 days for holding-cost accrual.

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent entity by carrying the parent's `version` in the request body; a mismatch rejects the write with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not take a version field.

- **Accepting a lot** requires `expected_season_version` matching the buying season's current `version`. Acceptance commits budget against the season and bumps the season's version, so a client whose view of the season predates the latest commitment holds a stale open-to-buy picture and the accept is rejected rather than committing against obsolete figures.
- **Releasing a packaway hold** requires `expected_hold_version` matching the hold's current `version`. Release finalizes accrued holding cost, and aging reviews advance the hold's version as they recompute accrual, so a client releasing against an unobserved review is rejected.
- **Creating an allocation plan** requires `expected_lot_version` matching the lot's current `version`. Under the product rule a newly approved plan legitimately supersedes the lot's prior draft plan, so a create carrying an old lot version acts on a stale lot view and is rejected.

### 2.9. Nested Resource Retrieval and Validation Order

Endpoints that address nested resources validate path identifiers strictly left-to-right: the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), before any deeper identifier or any business rule is examined. Request bodies are checked for foreign-key resolution in the same spirit. Across all endpoints, validation proceeds in a fixed priority order so that failures surface deterministically: authentication first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then resource existence (`ERR_NOT_FOUND`), then request well-formedness — required fields present, types matching, enum values in range, unknown fields rejected — as `ERR_INVALID_REQUEST` (HTTP 400), then state-machine admissibility (`ERR_INVALID_STATE`, HTTP 409), and only then the business rules of §3 in their stated priority.

### 2.10. Capacity, Uniqueness, and Structural Guards

Several structural invariants hold across the whole surface and are enforced at the moment of creation or state change. Codes are unique system-wide: `season_code`, `vendor_code`, `zone_code`, `lot_code`, `warehouse_code`, and `store_code` each reject duplicates with `ERR_DUPLICATE_CODE` (HTTP 409), as does a second `PackawayHold` for a lot that already has one — there is exactly one hold per lot. A warehouse cannot accept a hold whose `pallet_count`, added to the pallets of that warehouse's holds currently `STORED` or `AGING_REVIEW`, would exceed the warehouse's `pallet_capacity`; the overflow is rejected with `ERR_WAREHOUSE_OVER_CAPACITY`. A store placement that would push the store's on-hand past its `storage_capacity_units` is rejected with `ERR_STORE_OVER_CAPACITY`, and the same guard applies to allocations placed by plan execution. No operation may drive a store SKU's `units_on_hand` below zero: depletion beyond on-hand is rejected with `ERR_NEGATIVE_ON_HAND`, and a shrink confirmation whose `units_lost` exceeds the referenced stock's `units_on_hand` is rejected with `ERR_SHRINK_EXCEEDS_ON_HAND`. Finally, at most one season may be `OPEN` at any moment; opening a second is rejected with `ERR_SEASON_ALREADY_OPEN`.

## 3. Business Logic & Workflows

### 3.1. Season Setup, Vendors, and Price Zones

A `PlanningLead` opens the buying calendar by creating a **MerchandiseSeason** with a unique `season_code` (for example `SS2027`), a `start_date` and an `end_date` — the end strictly after the start — plus the department's open-to-buy posture: `department_otb_budget_cents` (a non-negative integer) and `packaway_reserve_ratio`, the fraction of that budget sequestered for late-season packaway deals, which must lie between 0 and 1 inclusive. A new season is `DRAFT`, and its four ledger figures — `committed_forward_cents`, `committed_packaway_cents`, `spent_forward_cents`, and `spent_packaway_cents` — all initialize to zero. The season's `status` moves `DRAFT → OPEN → CLOSED`. Opening is a `PlanningLead` action permitted only from `DRAFT` and only while no other season is `OPEN` (otherwise `ERR_SEASON_ALREADY_OPEN`); it bumps the season's `version`. Closing, also `PlanningLead`-only, is the season's terminal act and is guarded by three checks: no lot of the season may still be `OFFERED` or `EVALUATED` (`ERR_OPEN_LOTS_REMAIN`), every packaway hold bought against the season must be `RELEASED` or `LIQUIDATED` (`ERR_PACKAWAY_HOLDS_ACTIVE`), and no allocation plan of the season may still be `DRAFT` or `APPROVED` (`ERR_PLAN_NOT_EXECUTABLE`). On close, the season's version increments and every store SKU of the season still `ON_FLOOR`, `MARKED_DOWN`, or `CLEARANCE` has its `weeks_on_floor` recomputed from the logical clock without any price change.

The open-to-buy ledger on the season deserves a precise statement, because its evaluation order is pinned and must not be inverted. Caps are always computed from the budget, never from commitments: the packaway cap is the floor of `department_otb_budget_cents` times `packaway_reserve_ratio`, and the forward cap is the remainder of the budget above that floor. Availability is then each cap minus its provisional commitment — forward availability is the forward cap minus `committed_forward_cents`, and packaway availability is the packaway cap minus `committed_packaway_cents`. A candidate lot is admitted only if its landed cost is less than or equal to the relevant availability, and only after admission is the landed cost added to the corresponding commitment. The spend side finalizes at receipt completion: for each receipt line, the extended cost is the line's `received_qty` multiplied by the lot's `landed_cost_cents` divided by the lot's `unit_count`, rounded half-up to integer cents; `spent_forward_cents` is the sum of extended cost over receipt lines on `RECEIVED` receipts whose lot's disposition is `IMMEDIATE`, and `spent_packaway_cents` the same over `PACKAWAY` lots. Season reads report an over-spend alert whenever a spent figure exceeds its committed counterpart — over-spend is surfaced, never silently absorbed. Season responses carry `forward_available_cents` and `packaway_available_cents` alongside the four ledger figures; the availability read-model is initialized at season creation and refreshed on every mutation of the season's ledger, and season create, open, and close each return the same full season view that a season read returns. The season view also carries a boolean `over_spend_alert` that surfaces the over-spend condition, and an integer `projected_holding_cents` that reports the projected holding-cost reservation (§3.2) as the sum over the season's `ACCEPTED` packaway lots that already have a hold — a lot without a hold yet contributes nothing to the projection.

Vendors are registered by the `PlanningLead` with a `legal_name`, a unique `vendor_code`, the `discretion_level` and `ticket_discretion_required` flags of §2.6, a `default_zone_code` naming the price zone that governs compare-at substantiation for the vendor's lots (zones include `NE`, `MW`, `SE`, `TX`, `MT`, `WC`), and a `vendor_tier` of `A`, `B`, or `C` — a declining tier excludes the vendor from later promotions. A vendor's lots are reverse-reachable from the vendor, subject to the discretion visibility rule.

Price zones are owned by the `PricingAnalyst`. Each zone has a unique `zone_code` (one of `NE`, `MW`, `SE`, `TX`, `MT`, `WC`), a `compare_at_multiplier` strictly greater than 1 that sets the minimum legal ratio of compare-at price to our retail in that zone, a `markdown_cadence_weeks` between 1 and 8 inclusive fixing how many weeks on floor trigger each markdown step for non-clearance stores, and a `clearance_weeks` threshold — strictly greater than `markdown_cadence_weeks` and at most 52 — at which floor stock is forced to clearance.

### 3.2. The Buy: Lot Registration, Evaluation, and Open-to-Buy Adjudication

An opportunity enters the system when a `Buyer` (or `PlanningLead`) registers a **Lot** in `OFFERED` status, naming the supplying `vendor_id`, the `season_id` it is bought against, a unique `lot_code`, a `lot_type` of `CLOSEOUT`, `CANCELLATION`, or `PACKAWAY`, and a `disposition` of `IMMEDIATE` (ship to stores this season) or `PACKAWAY` (pack-and-hold for a later season). The offer carries the vendor's `asking_price_cents` (positive), the declared `unit_count` (positive), the buyer's `expected_sell_through_pct` (greater than 0 and at most 1), the buyer's `estimated_unit_retail_cents` (positive), and a hard `offer_expires_at` deadline. A lot flagged `mixed_lot` mixes departments or styles and, as §3.7 explains, forces high-value-sort merge behavior on any shrink case against it; the flag defaults to false. When the disposition is `PACKAWAY`, a `target_season_id` is required — its absence is a request well-formedness failure (`ERR_INVALID_REQUEST`, HTTP 400) — and when present it must reference an existing season, still in `DRAFT`, and different from the buying season; a violation of that target-season rule is `ERR_TARGET_SEASON_NOT_DRAFT` (HTTP 422), and the same target-season rule is rechecked at packaway hold creation. Lots and their lines may be listed and read by buyers, planners, allocators, inventory planners, pricing analysts, and warehouse clerks, subject to the discretion filter of §2.6.

A lot is fleshed out with **LotLines** while it remains `OFFERED` or `EVALUATED`; each line names a `style_code`, a `department` of `APPAREL`, `HOME`, `BEAUTY`, or `ACCESSORIES`, a positive `quantity`, a non-negative `unit_cost_cents`, the vendor-claimed `compare_at_claim_cents` (positive, to be substantiated at ticketing), and a planned `target_retail_cents` (positive, before zone rounding).

Evaluation is the `Buyer`'s exclusive call and turns `OFFERED → EVALUATED`; it may be repeated while the lot is `EVALUATED`, forming a re-evaluation loop that revises score and landed cost as negotiations move. Evaluation — and equally acceptance — must occur strictly before `offer_expires_at` on the logical clock; a lot acted on at or after expiry is rejected with `ERR_OFFER_EXPIRED` (HTTP 422), and an offer that expires while still `OFFERED` and unevaluated is cancelled by the system with `cancel_reason` `OFFER_EXPIRED` — the system performs this cancellation on every logical-clock advance, and an evaluate call that finds the lot still `OFFERED` at or past its deadline performs the same cancellation before rejecting the evaluation with `ERR_OFFER_EXPIRED`. The evaluation enforces its checks in a fixed order: state first (the lot must be in a valid from-state, else `ERR_INVALID_STATE`), then the offer-expiry clock check (`ERR_OFFER_EXPIRED`), then vendor discretion (`ERR_VENDOR_DISCRETION` for a junior buyer facing a `CONFIDENTIAL` or `QUIET` vendor). Because the lapsed-offer cancellation described above runs before the state check, an `OFFERED` lot acted on at or past its deadline surfaces `ERR_OFFER_EXPIRED` — never `ERR_INVALID_STATE`. The request may carry a `negotiated_price_cents`; either way, evaluation computes two things. First, **landed cost**: the negotiated price when supplied, otherwise the asking price, plus a flat freight surcharge of 150,000 cents per lot — recorded on the lot as `landed_cost_cents`. Second, the **deal quality score**. The margin fraction is the excess of `estimated_unit_retail_cents` over the per-unit cost basis — landed cost divided by `unit_count`, computed before any rounding — expressed as a fraction of `estimated_unit_retail_cents`, floored at zero. The sell-through term is `expected_sell_through_pct` capped at 1. The raw score is 100 times the blend of six-tenths margin fraction and four-tenths sell-through, minus a discretion penalty of 15 points for a `CONFIDENTIAL` vendor or 25 points for a `QUIET` vendor (none for `STANDARD`), plus a lot-type bonus of 10 for `CLOSEOUT`, 5 for `CANCELLATION`, or 0 for `PACKAWAY`. The result is clamped into the range 0 to 100 inclusive and recorded as `deal_quality_score`; the score is presented rounded half-up to 2 decimal places on lot responses. Both figures are null until the first evaluation. Each evaluation or re-evaluation bumps the lot's `version`.

Adjudication resolves an `EVALUATED` lot. **Acceptance** (`EVALUATED → ACCEPTED`) is where open-to-buy discipline bites, and its checks run in a pinned order after the generic gates of §2.9: the state check (`ERR_INVALID_STATE`), then the OCC check on `expected_season_version` (`ERR_STALE_VERSION`, HTTP 412), then the expiry check (`ERR_OFFER_EXPIRED`), then vendor discretion (`ERR_VENDOR_DISCRETION`), then budget admission — an `IMMEDIATE` lot whose landed cost exceeds forward availability is rejected with `ERR_OTB_FORWARD_EXCEEDED`, while a `PACKAWAY` lot exceeding packaway availability is rejected with `ERR_OTB_PACKAWAY_EXCEEDED` — and finally, for a `PACKAWAY` lot, the target-season rule (`ERR_TARGET_SEASON_NOT_DRAFT`); at acceptance that rule re-verifies only that the target season still exists and differs from the buying season, because the still-`DRAFT` requirement is rechecked at packaway hold creation rather than at acceptance. On acceptance the lot's landed cost is added to `committed_forward_cents` or `committed_packaway_cents` according to disposition, the season's `version` increments because the commitment mutates the season, and the lot's `version` increments. Accepting a packaway lot also accrues a **projected holding-cost reservation**: the estimated pallet count times the receiving warehouse's monthly rate times the number of months to target, where months to target is the days from today to the target season's `start_date`, divided by 30 and rounded up. This projection is informational on season reads and does not consume the cap. **Passing** (`EVALUATED → PASSED`) is the clean decline, subject to the same state and discretion checks — and no offer-expiry clock check, so a lot may be passed at or past its deadline — bumping the lot's version. **Cancellation** is available from both `OFFERED` and `EVALUATED`: a buyer or planning lead supplies a `cancel_reason` of `VENDOR_PULL`, `BUYER_WITHDRAW`, or `OFFER_EXPIRED`; the system fires the `OFFERED → CANCELLED` transition itself when an offer lapses unevaluated, recording `OFFER_EXPIRED`. Cancellation records the reason on the lot and bumps its version.

### 3.3. Ticketing and Compare-At Substantiation

Before a single unit reaches a sales floor, the `PricingAnalyst` issues a **Ticket** for a lot line in a specific `zone_code`, optionally attaching `substantiation_notes` as evidence for the compare-at claim (defaulting to the empty string when omitted). Issuance requires the line's lot to be `ACCEPTED` and the zone to exist; otherwise `ERR_TICKET_NOT_ISSUED` (HTTP 422). The ticket's retail, `ticket_retail_cents`, applies the zone rounding rule to the line's `target_retail_cents`: the zone retail multiplier is 1.0 for every zone in this benchmark — regional differentiation enters through the compare-at multiplier, not through retail — so the target retail is rounded half-up to integer cents and then adjusted down to the nearest price ending in 9 cents, per §2.7.

Compare-at substantiation then runs as a threshold gate with a zone-dependent variant. The gate is: the claimed compare-at must be at least the ticket retail multiplied by the zone's `compare_at_multiplier`, with the product rounded up to integer cents so the boundary is exact. In the **vendor-claim** variant — zones `MW`, `SE`, `TX`, and `MT`, which publish no zone book — the vendor's `compare_at_claim_cents` is tested directly against that gate. In the **zone-book** variant — zones `NE` and `WC`, which nominally publish a reference book — the API carries no zone-book value, so the vendor's `compare_at_claim_cents` is the candidate for those zones as well and is gated the same way; the two variants are operationally identical on this surface. A claim that passes is recorded as `compare_at_cents` with `compare_at_omitted` false; a claim that fails is **not rejected** — the ticket is printed without a compare-at price, with `compare_at_cents` null and `compare_at_omitted` true. Vendor discretion surfaces here too: `vendor_name_on_ticket` is false whenever the supplying vendor's `ticket_discretion_required` demands omission, and true otherwise. A ticket is `ACTIVE` from issuance; the `PricingAnalyst` may void it (`ACTIVE → VOIDED`) only while no store SKU in `ON_FLOOR`, `MARKED_DOWN`, or `CLEARANCE` references it — live stock protects the ticket with `ERR_TICKET_IN_USE`. Tickets are immutable ledger entries: they carry no `updated_at` and no `version` (§2.4).

### 3.4. Pack-and-Hold: Warehouse Storage, Aging, and Release

Warehouses are created by the `InventoryPlanner` with a unique `warehouse_code`, a positive `pallet_capacity`, a home `zone_code`, and a non-negative `monthly_holding_rate_per_pallet_cents` — the rate charged per stored pallet per 30-day billing month, pro-rated at day granularity as described below.

Once a `PACKAWAY` lot is `ACCEPTED`, the `InventoryPlanner` enters it into storage as a **PackawayHold** — exactly one hold per lot, enforced by `ERR_DUPLICATE_CODE`. Creation names the `lot_id`, the storing `warehouse_id`, the `pallet_count` (positive, and checked against remaining warehouse capacity per §2.10), and a release window `release_window_start` to `release_window_end`, the end strictly after the start. The hold inherits its `season_id` (the buying season) and `target_season_id` (the intended season) from the lot. On entry, `entry_date` is stamped from the logical clock, `accrued_holding_cost_cents` starts at 0, `review_count` starts at 0, `age_bucket` is `FRESH`, and the status is `STORED`.

**Holding-cost accrual** runs at creation (zero), on every logical-clock advance (the aging sweep recomputes the running accrual of every hold still `STORED` or `AGING_REVIEW`), at every aging review, and as a final computation at release or liquidation. Days held is the whole-day difference between the as-of date — today for reviews, the release date on release — and `entry_date`. Full months are the days held divided by 30, rounded down; the remainder is the days held modulo 30. Under the default **pro-rata** variant, the accrual is `pallet_count` times the warehouse monthly rate times full months, plus the floor of `pallet_count` times the monthly rate times remainder days divided by 30. Under the **month-boundary** variant — used only by warehouses whose `zone_code` is `WC`, the west-coast billing convention — any started month is billed in full: `pallet_count` times the monthly rate times full months, plus one more full month whenever the remainder days are positive. All other zones use pro-rata. The result in integer cents is written to `accrued_holding_cost_cents`.

**Aging buckets** are recomputed by the system sweep on every logical-clock advance over holds `STORED` or `AGING_REVIEW`, and inside every accrual run. A hold with fewer than 90 days since entry is `FRESH`; from 90 days up to but not including 270 days it is `AGING`; at 270 days or more it is `STALE`. The boundaries are inclusive at the low end of each band: exactly 90 days is `AGING`, exactly 270 days is `STALE`. The aging sweep recomputes both the age bucket and the running accrual but mutates the hold only when one of the recomputed values actually changed; a clock advance that changes nothing leaves `updated_at` and `version` untouched.

The hold's lifecycle is `STORED → AGING_REVIEW → (STORED | RELEASED | LIQUIDATED)`, with two direct exits from `STORED`. An **aging review** is driven by the `InventoryPlanner` (or the system sweep) with a `trigger_reason`. With `trigger_reason` `AGING_THRESHOLD`, a `STORED` hold moves to `AGING_REVIEW` — but only once its bucket has left `FRESH`, meaning at least 90 days since entry; a premature review is rejected with `ERR_AGING_REVIEW_PREMATURE` (HTTP 422). From `AGING_REVIEW`, the reviewer's decision completes the review: `DECISION_KEEP` returns the hold to `STORED`; `DECISION_RELEASE` releases it early, permitted only when today falls inside the release window inclusive on both ends (`ERR_HOLD_WINDOW_CLOSED` otherwise) — and, like the direct release, it also requires the target season to have reached its `start_date` with status `OPEN` (`ERR_TARGET_SEASON_NOT_OPEN`), the window check running first; `DECISION_LIQUIDATE` moves the hold to `LIQUIDATED`. Every aging review — threshold or decision — recomputes the accrual, increments `review_count`, and bumps the hold's `version`; a release stamps `release_date` with the final accrual computed as of that date. Liquidation, whether reached by `DECISION_LIQUIDATE` from `AGING_REVIEW` or by a **direct liquidation** from `STORED` (which requires the hold to be `STALE` — at least 270 days — else `ERR_AGING_REVIEW_PREMATURE`), computes the final accrual and creates a **LiquidationOrder** in `DRAFT` against the hold's lot with reason `PACKAWAY_STALE`, its `recovery_rate_pct` pinned to the cascade rate of 0.25, addressed to the warehouse's nearest clearance store — the store with `clearance_outlet` true in the warehouse's zone, ties broken by earliest `created_at`; if the warehouse's zone has no clearance store, the cascade order's `store_id` is null. Direct liquidation is not an aging review: it leaves `review_count` unchanged.

A **release** directly from `STORED` is the normal exit and carries the OCC gate of §2.8: the request must carry `expected_hold_version` matching the hold's current `version`, rejected with `ERR_STALE_VERSION` (412) when an unobserved aging review has advanced it. Release also requires today to fall within the release window inclusive (`ERR_HOLD_WINDOW_CLOSED`) and the target season to have reached its `start_date` with status `OPEN` (`ERR_TARGET_SEASON_NOT_OPEN`). On the direct release these checks run in a pinned order after the state check: the release-window check first, then the OCC gate, then the target-season check. The window and target-season checks guard both the direct release and the aging-review release decision. On release the final accrual is computed, `release_date` is stamped, the version increments, and the released units become eligible for allocation into the target season — an allocation plan may then be created against the lot with `season_id` equal to the hold's `target_season_id`.

### 3.5. Receiving, Variance, and Spend Finalization

When goods arrive, a `WarehouseClerk` opens a **Receipt** against an `ACCEPTED` lot at a warehouse by naming the `lot_id` and `warehouse_id`; the system stamps `receipt_date` from the logical clock and creates one **ReceiptLine** per lot line with `declared_qty` set to the lot line's `quantity`; each line is addressable by its own identifier within the receipt (the `lineId` path variable) and references its parent via `receipt_id`. While the receipt is `OPEN`, the clerk records each line's `received_qty` — which must lie between 0 and the declared quantity inclusive, else `ERR_RECEIPT_LINE_QTY_INVALID`. Completing the receipt (`OPEN → RECEIVED`) requires every line to have its `received_qty` recorded; an unrecorded line blocks completion with the same `ERR_RECEIPT_LINE_QTY_INVALID`.

Completion runs **variance valuation** in a pinned order — each line is valued first, then results are summed; never a lot-average. Per line: `variance_qty` is the declared quantity minus the received quantity; the extended cost is the received quantity times the lot's `landed_cost_cents` divided by the lot's `unit_count`, rounded half-up to integer cents, and is recorded on the line as `extended_cost_cents` (null until completion); and `variance_value_cents` is the variance quantity times the same per-unit basis, again rounded half-up. The receipt's total variance is the sum of the per-line variance values. For every line with a positive variance, the system files one **ShrinkCase** in `OPEN`: unattributed to any store (`store_id` null, `store_sku_id` null), tied to the receipt's lot, with `shrink_type` `MIXED_LOT_SHORTAGE` when the lot is `mixed_lot` and `UNSCANNED_UNIT` otherwise, `merge_mode` `HIGH_VALUE_SORT` for a mixed lot and `FIFO` otherwise, `units_lost` 0, and `units_untraceable` equal to the variance quantity. Completion also finalizes the season's spend side per §3.1 — `spent_forward_cents` and `spent_packaway_cents` are recomputed from extended costs, and the season's `version` increments — and bumps the receipt's own `version`. Receipt lines are ledger entries and, like tickets, carry neither `updated_at` nor `version`.

### 3.6. Store Allocation by Cluster

Stores are created by the `AllocationManager` with a unique `store_code`, a demographic `cluster_code` of `URBAN_PREMIUM`, `SUBURBAN_FAMILY`, or `VALUE_RURAL`, a `zone_code` referencing an existing price zone, a positive `storage_capacity_units`, and an optional `clearance_outlet` flag (default false) — clearance stores ignore the markdown cadence entirely and take clearance-priority allocations.

Allocation of an `ACCEPTED` lot begins with a **AllocationPlan** in `DRAFT`, created by the `AllocationManager` with the `lot_id`, the selling `season_id`, the `total_units` entering the plan (positive), and `cluster_weights` — a map of cluster code to a positive weight. Creation carries the lot-level OCC gate of §2.8: `expected_lot_version` must match the lot's current `version`, else `ERR_STALE_VERSION` (412); a successful create bumps the lot's `version`, because under the product rule a newly approved plan legitimately supersedes the lot's prior draft.

**Approval** (`DRAFT → APPROVED`) enforces its checks in order: the plan must be `DRAFT` (`ERR_INVALID_STATE`); then cluster coverage — every cluster named in `cluster_weights` must have at least one store, and every cluster that has at least one store must be named in `cluster_weights`, otherwise `ERR_CLUSTER_UNCOVERED`; then uniqueness of the live chain — no other plan for the same lot may be `APPROVED` or `EXECUTED` (`ERR_LOT_ALREADY_ALLOCATED`). Approving a plan supersedes every other `DRAFT` plan for the same lot: each such plan moves `DRAFT → SUPERSEDED` with `superseded_by_id` pointing at the newly approved plan and its `version` incremented. A plan may be cancelled from `DRAFT` or `APPROVED` (`→ CANCELLED`), and in all cases the acting plan's `version` increments.

**Execution** (`APPROVED → EXECUTED`) requires the plan's selling season to be `OPEN` (`ERR_SEASON_NOT_OPEN`, HTTP 422) and runs the deterministic proportional allocation. Eligible stores are those whose cluster is named in `cluster_weights` and whose `storage_capacity_units` is positive, ordered by cluster and then by store `created_at` ascending. Each cluster's quota is the floor of `total_units` times the cluster's weight divided by the sum of all weights; the leftover units are distributed one at a time to clusters by descending fractional part, ties broken by cluster code in lexicographic ascending order. Within a cluster, each store's base quota is the floor of the cluster quota divided by the number of stores in the cluster; the base is dealt first, capped at each store's remaining capacity, then the cluster remainder is dealt one unit per store in `created_at` ascending order, still capped at each store's remaining capacity — no store ever receives more than its `storage_capacity_units`. Units that could not be placed in either pass — capacity-capped base units plus any undealt remainder — then spill to the stores of the same cluster with remaining room in `created_at` order, and whatever still remains spills to other clusters by descending weight with cluster-code ties ascending. The dealing loop itself enforces capacity: when no eligible store anywhere has room for a remaining unit, execution fails with `ERR_STORE_OVER_CAPACITY`. A store that ends with zero units produces no store SKU row; an empty allocation is not an error. Clearance outlets participate in execution exactly like ordinary stores, in their cluster's `created_at` order; they are ranked first only when a liquidation sweep pulls stock out (§3.8). Execution creates one **StoreSku** per (store, lot line) pair placed: `allocation_plan_id` set to the plan, `floor_date` stamped from the logical clock, `weeks_on_floor` zero, and `current_price_cents` initialized from the ticket for the store's zone. Every placed line must have an `ACTIVE` ticket for that zone before execution, else `ERR_TICKET_NOT_ISSUED`, and no store may be pushed past capacity (`ERR_STORE_OVER_CAPACITY`).

Units may also be placed by hand: a `StoreOpsLead` or `AllocationManager` creates a StoreSku directly with `store_id`, `lot_line_id`, `ticket_id`, `season_id`, and `units_on_hand` (positive). Manual placement carries `allocation_plan_id` null, stamps `floor_date` and `weeks_on_floor` the same way, initializes `current_price_cents` from the referenced ticket, and is subject to the same ticket-presence (`ERR_TICKET_NOT_ISSUED`) and capacity (`ERR_STORE_OVER_CAPACITY`) guards. The `ticket_id` is required at placement precisely so that every sellable unit traces to a ticketed price.

### 3.7. On the Floor: Markdown Cadence, Sell-Through, and Shrink Control

A store SKU lives `ON_FLOOR → MARKED_DOWN → CLEARANCE → (SOLD_OUT | LIQUIDATED)`, with `SOLD_OUT` reachable from any live state.

The **markdown sweep** runs on every logical-clock advance over store SKUs `ON_FLOOR` or `MARKED_DOWN` whose season is `OPEN`, and the reduction is always computed per store SKU — a new price rounded per SKU — never as a bulk rate applied and then distributed. `weeks_on_floor` is the whole-day difference between today and `floor_date`, divided by 7 and rounded down. A store with `clearance_outlet` true skips the cadence entirely; nothing changes until the clearance threshold. When `weeks_on_floor` reaches the zone's `clearance_weeks`, the SKU moves to `CLEARANCE` and its price becomes 30% of the base price — the clearance floor multiplier is 0.30 applied to the ticket's `ticket_retail_cents` — rounded half-up and adjusted down to a 9-ending price, recorded as a **MarkdownEvent** of `event_type` `FORCE_CLEARANCE`; this threshold applies to clearance-outlet stores too, which skip only the cadence steps. Short of clearance, whenever `weeks_on_floor` reaches the next cadence boundary — at least `markdown_step` + 1 times the zone's `markdown_cadence_weeks` — exactly one step is applied per sweep per SKU even if several boundaries were crossed: the new price is computed by applying the 20% step rate (multiplier 0.80) to the running unadjusted price — the price before any 9-ending shelf adjustment, carried from the ticket retail through each step — then rounding half-up and adjusting down to a 9-ending price, `markdown_step` increments, and a MarkdownEvent of `event_type` `CADENCE` is created. A SKU's `markdown_step` is the count of its `CADENCE` events; `FORCE_CLEARANCE` does not count as a step. Each event records the `store_sku_id`, the `step_number`, `old_price_cents`, `new_price_cents`, the `markdown_cents` difference, the event type, and the `effective_date` from the logical clock; MarkdownEvents carry no `updated_at` or `version`. The sweep touches only SKUs whose season is `OPEN`, and only SKUs `ON_FLOOR` or `MARKED_DOWN` — a SKU already in `CLEARANCE` is untouched, and its `weeks_on_floor` is recomputed only at season close per §3.1. A sweep that changes neither `weeks_on_floor` nor the price leaves the SKU's `updated_at` and `version` untouched; the sweep bumps the SKU's `version` only when something actually changed, and a forced clearance on a SKU whose `weeks_on_floor` is already current therefore bumps the version exactly once.

Sell-through is recorded by the `StoreOpsLead` as depletion: a payload of `units_sold` (positive, and never more than `units_on_hand`, else `ERR_NEGATIVE_ON_HAND`) reduces `units_on_hand`, bumps the SKU's `version`, and moves the SKU to `SOLD_OUT` exactly when on-hand reaches zero. Depletion is admissible from `ON_FLOOR`, `MARKED_DOWN`, or `CLEARANCE` — not from terminal states.

**Shrink** on unticketed and mixed merchandise is policed by the `ShrinkAuditor`, with `StoreOpsLead` also able to file. A **ShrinkCase** names the `store_id`, a `shrink_type` of `UNSCANNED_UNIT`, `MIXED_LOT_OVERAGE`, `MIXED_LOT_SHORTAGE`, or `DAMAGE`, and two unit counts that partition the loss: `units_lost` — units written off against traced stock, which may be zero — and `units_untraceable` — units that cannot be traced to any store SKU, which may also be zero, though not both. When units are traceable the case carries the `store_sku_id` and `lot_id`; a case with zero `units_untraceable` that omits either `store_sku_id` or `lot_id` is rejected as malformed. When `units_untraceable` is positive, `store_sku_id` is null — a case filed with both untraceable units and a `store_sku_id` is rejected as malformed — while a caller-supplied `lot_id` is retained on the case, and untraceable valuation merges across that lot's lines. The `merge_mode` is `FIFO` by default but is forced to `HIGH_VALUE_SORT` whenever the underlying lot is `mixed_lot`. Confirmation (`OPEN → CONFIRMED`) by the `ShrinkAuditor` is blocked when the traced stock cannot absorb the loss — `units_lost` greater than the SKU's `units_on_hand` is `ERR_SHRINK_EXCEEDS_ON_HAND` — and runs the valuation. For traced shrink, the per-unit basis is the lot's `landed_cost_cents` divided by its `unit_count`, rounded half-up, and `shrink_value_cents` is `units_lost` times that basis; the SKU's `units_on_hand` drops by `units_lost`, and if it reaches zero the SKU transitions to `SOLD_OUT`. For untraceable shrink, the lot's lines are ordered by merge policy — `FIFO` by `created_at` ascending; `HIGH_VALUE_SORT` by `compare_at_claim_cents` descending with `created_at` ascending as the tie-break — and `shrink_value_cents` is the sum of each line's `unit_cost_cents` over the first `units_untraceable` units drawn in that order, each line contributing at most its `quantity` of units; the two policies can differ materially. The merge lot is the case's `lot_id` when carried; an untraceable case filed without a `lot_id` resolves its merge lot from the case's store — when the store's store SKUs trace to exactly one lot, that lot's lines are merged — and a case whose merge lot cannot be resolved values at zero. Confirmation bumps the case's `version`; voiding (`OPEN → VOIDED`) simply closes the case with a version bump.

### 3.8. Liquidation and Recovery

A **LiquidationOrder** pulls unsold stock out of a store for salvage. The `PlanningLead` creates one in `DRAFT` with the `store_id`, the `lot_id`, a `reason` of `CLEARANCE_WEEKS_EXCEEDED` or `PACKAWAY_STALE`, and a `recovery_rate_pct` — the expected recovery fraction, greater than 0 and at most 1. Manually created orders take the supplied rate; cascade-created orders from packaway liquidation carry the pinned rate of 0.25 (§3.4). At creation `expected_units` is stamped as the total `units_on_hand` over the affected stock, and `actual_units` and `recovery_value_cents` remain null.

The **affected stock** of an order is the live store SKUs — `ON_FLOOR`, `MARKED_DOWN`, or `CLEARANCE` — at the order's store whose lot line belongs to the order's lot. Approval (`DRAFT → APPROVED`, `PlanningLead`) computes the **provisional** recovery: `expected_units` times the affected stock's current per-unit price — the `current_price_cents` at the time of the run of the first affected store SKU in the system's deterministic ordering (creation order), or zero when the affected set is empty — times the recovery rate, rounded half-up to integer cents, written to `recovery_value_cents`. Execution (`APPROVED → EXECUTED`, `StoreOpsLead`) supplies the `actual_units` pulled, recomputes the same formula with `actual_units` in place of `expected_units` — the **actual** variant — and overwrites the provisional value. Execution moves every affected store SKU to `LIQUIDATED` with its `units_on_hand` consumed to zero; this liquidation path is how `CLEARANCE` stock exits, and packaway-stale liquidations also hit non-clearance floor stock `ON_FLOOR` or `MARKED_DOWN`. Each transition bumps the order's `version`. A `DRAFT` order may instead be cancelled (`→ CANCELLED`) by the `PlanningLead`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints share the envelope, pagination, and error contracts of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers aging and markdown sweeps | PlanningLead |
| POST | `/merchandise-seasons` | Create a season in DRAFT | PlanningLead |
| GET | `/merchandise-seasons` | List seasons | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk, StoreOpsLead, ShrinkAuditor |
| GET | `/merchandise-seasons/{id}` | Get a season with open-to-buy figures and over-spend alert | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk, StoreOpsLead, ShrinkAuditor |
| POST | `/merchandise-seasons/{id}/open` | Open a DRAFT season (only one OPEN at a time) | PlanningLead |
| POST | `/merchandise-seasons/{id}/close` | Close an OPEN season once lots adjudicated, holds closed, plans executed | PlanningLead |
| GET | `/merchandise-seasons/{id}/lots` | Lots bought against a season | Buyer, PlanningLead, AllocationManager |
| GET | `/merchandise-seasons/{id}/packaway-holds` | Holds bought in a season | InventoryPlanner, PlanningLead |
| GET | `/merchandise-seasons/{id}/allocation-plans` | Allocation plans of a season | AllocationManager, PlanningLead |
| GET | `/merchandise-seasons/{id}/store-skus` | Store SKUs of a selling season | StoreOpsLead, PlanningLead, AllocationManager |
| POST | `/vendors` | Register a vendor | PlanningLead |
| GET | `/vendors` | List vendors | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst |
| GET | `/vendors/{id}` | Get a vendor | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst |
| GET | `/vendors/{id}/lots` | Lots offered by a vendor (discretion-filtered) | Buyer, PlanningLead, PricingAnalyst |
| POST | `/price-zones` | Create a price zone | PricingAnalyst |
| GET | `/price-zones` | List price zones | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst, StoreOpsLead |
| GET | `/price-zones/{id}` | Get a price zone | PlanningLead, Buyer, AllocationManager, InventoryPlanner, PricingAnalyst, StoreOpsLead |
| POST | `/lots` | Register an opportunistic lot offer (OFFERED) | Buyer, PlanningLead |
| GET | `/lots` | List lots; junior Buyers never see CONFIDENTIAL/QUIET vendor lots | Buyer, PlanningLead, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk |
| GET | `/lots/{id}` | Get a lot (discretion-filtered) | Buyer, PlanningLead, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk |
| POST | `/lots/{id}/evaluate` | Evaluate or re-evaluate a lot; computes deal quality and landed cost | Buyer |
| POST | `/lots/{id}/accept` | Accept an evaluated lot against open-to-buy; OCC on the season | Buyer |
| POST | `/lots/{id}/pass` | Pass on an evaluated lot | Buyer |
| POST | `/lots/{id}/cancel` | Cancel an OFFERED or EVALUATED lot with a reason | Buyer, PlanningLead |
| GET | `/lots/{id}/lot-lines` | List lot lines of a lot | Buyer, PlanningLead, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk |
| GET | `/lots/{id}/packaway-holds` | Holds of a lot (0 or 1) | InventoryPlanner, PlanningLead, WarehouseClerk |
| GET | `/lots/{id}/allocation-plans` | Allocation plans of a lot | AllocationManager, PlanningLead, Buyer |
| GET | `/lots/{id}/receipts` | Receipts of a lot | WarehouseClerk, PlanningLead, InventoryPlanner |
| GET | `/lots/{id}/shrink-cases` | Shrink cases tied to a lot | ShrinkAuditor, PlanningLead |
| GET | `/lots/{id}/liquidation-orders` | Liquidation orders of a lot | PlanningLead, StoreOpsLead |
| POST | `/lots/{id}/lot-lines` | Add a lot line to an OFFERED or EVALUATED lot | Buyer, PlanningLead |
| GET | `/lot-lines/{id}` | Get a lot line | Buyer, PlanningLead, AllocationManager, InventoryPlanner, PricingAnalyst, WarehouseClerk |
| GET | `/lot-lines/{id}/tickets` | Tickets issued for a lot line | PricingAnalyst, PlanningLead, StoreOpsLead |
| GET | `/lot-lines/{id}/store-skus` | Store placements of a lot line | StoreOpsLead, AllocationManager, PlanningLead |
| GET | `/lot-lines/{id}/receipt-lines` | Receipt lines of a lot line | WarehouseClerk, PlanningLead |
| POST | `/warehouses` | Create a warehouse | InventoryPlanner |
| GET | `/warehouses` | List warehouses | InventoryPlanner, PlanningLead, WarehouseClerk |
| GET | `/warehouses/{id}` | Get a warehouse | InventoryPlanner, PlanningLead, WarehouseClerk |
| GET | `/warehouses/{id}/packaway-holds` | Holds stored at a warehouse | InventoryPlanner, PlanningLead, WarehouseClerk |
| GET | `/warehouses/{id}/receipts` | Receipts at a warehouse | WarehouseClerk, InventoryPlanner, PlanningLead |
| POST | `/packaway-holds` | Enter an ACCEPTED packaway lot into storage | InventoryPlanner |
| GET | `/packaway-holds` | List holds | InventoryPlanner, PlanningLead, WarehouseClerk |
| GET | `/packaway-holds/{id}` | Get a hold | InventoryPlanner, PlanningLead, WarehouseClerk |
| POST | `/packaway-holds/{id}/aging-review` | Run an aging review; trigger_reason AGING_THRESHOLD / DECISION_KEEP / DECISION_RELEASE / DECISION_LIQUIDATE | InventoryPlanner |
| POST | `/packaway-holds/{id}/liquidate` | Directly liquidate a STALE hold | InventoryPlanner |
| POST | `/packaway-holds/{id}/release` | Release a hold within its window; OCC on the hold | InventoryPlanner |
| POST | `/stores` | Create a store | AllocationManager |
| GET | `/stores` | List stores | AllocationManager, PlanningLead, StoreOpsLead, PricingAnalyst |
| GET | `/stores/{id}` | Get a store | AllocationManager, PlanningLead, StoreOpsLead, PricingAnalyst |
| GET | `/stores/{id}/store-skus` | SKUs on a store's floor | StoreOpsLead, AllocationManager, PlanningLead |
| GET | `/stores/{id}/shrink-cases` | Shrink cases at a store | ShrinkAuditor, PlanningLead, StoreOpsLead |
| GET | `/stores/{id}/liquidation-orders` | Liquidation orders at a store | PlanningLead, StoreOpsLead |
| POST | `/allocation-plans` | Create a DRAFT allocation plan for an ACCEPTED lot; OCC on the lot | AllocationManager |
| GET | `/allocation-plans` | List allocation plans | AllocationManager, PlanningLead, Buyer |
| GET | `/allocation-plans/{id}` | Get an allocation plan | AllocationManager, PlanningLead, Buyer |
| POST | `/allocation-plans/{id}/approve` | Approve a DRAFT plan; supersedes other DRAFT plans for the lot | AllocationManager |
| POST | `/allocation-plans/{id}/execute` | Execute an APPROVED plan; runs cluster allocation and creates StoreSkus | AllocationManager |
| POST | `/allocation-plans/{id}/cancel` | Cancel a DRAFT or APPROVED plan | AllocationManager |
| GET | `/allocation-plans/{id}/store-skus` | Store SKUs created by a plan | AllocationManager, PlanningLead, StoreOpsLead |
| POST | `/store-skus` | Manually place units of a lot line at a store (requires ACTIVE ticket) | StoreOpsLead, AllocationManager |
| GET | `/store-skus` | List store SKUs | StoreOpsLead, AllocationManager, PlanningLead, ShrinkAuditor |
| GET | `/store-skus/{id}` | Get a store SKU | StoreOpsLead, AllocationManager, PlanningLead, ShrinkAuditor |
| GET | `/store-skus/{id}/markdown-events` | Markdown events of a store SKU | StoreOpsLead, PlanningLead, PricingAnalyst |
| GET | `/store-skus/{id}/shrink-cases` | Shrink cases against a store SKU | ShrinkAuditor, PlanningLead, StoreOpsLead |
| POST | `/store-skus/{id}/deplete` | Record sell-through depletion; SOLD_OUT at zero on-hand | StoreOpsLead |
| POST | `/tickets` | Issue a ticket for a lot line in a zone (compare-at substantiation) | PricingAnalyst |
| GET | `/tickets` | List tickets | PricingAnalyst, PlanningLead, StoreOpsLead, AllocationManager |
| GET | `/tickets/{id}` | Get a ticket | PricingAnalyst, PlanningLead, StoreOpsLead, AllocationManager |
| POST | `/tickets/{id}/void` | Void an ACTIVE ticket not referenced by live stock | PricingAnalyst |
| GET | `/tickets/{id}/store-skus` | Store SKUs priced by a ticket | PricingAnalyst, StoreOpsLead, PlanningLead |
| POST | `/receipts` | Open a receipt against an ACCEPTED lot; creates lines with declared quantities | WarehouseClerk |
| GET | `/receipts` | List receipts | WarehouseClerk, InventoryPlanner, PlanningLead |
| GET | `/receipts/{id}` | Get a receipt | WarehouseClerk, InventoryPlanner, PlanningLead |
| GET | `/receipts/{id}/receipt-lines` | Lines of a receipt | WarehouseClerk, InventoryPlanner, PlanningLead |
| PATCH | `/receipts/{id}/lines/{lineId}` | Record received quantity on a receipt line while OPEN | WarehouseClerk |
| POST | `/receipts/{id}/complete` | Complete a receipt: variance valuation, shrink cases, season spend recompute | WarehouseClerk |
| POST | `/shrink-cases` | File a shrink case | ShrinkAuditor, StoreOpsLead |
| GET | `/shrink-cases` | List shrink cases | ShrinkAuditor, PlanningLead, StoreOpsLead |
| GET | `/shrink-cases/{id}` | Get a shrink case | ShrinkAuditor, PlanningLead, StoreOpsLead |
| POST | `/shrink-cases/{id}/confirm` | Confirm a shrink case: valuation and on-hand decrement | ShrinkAuditor |
| POST | `/shrink-cases/{id}/void` | Void an open shrink case | ShrinkAuditor |
| POST | `/liquidation-orders` | Create a DRAFT liquidation order for clearance stock at a store | PlanningLead |
| GET | `/liquidation-orders` | List liquidation orders | PlanningLead, StoreOpsLead |
| GET | `/liquidation-orders/{id}` | Get a liquidation order | PlanningLead, StoreOpsLead |
| POST | `/liquidation-orders/{id}/approve` | Approve a DRAFT order (provisional recovery valuation) | PlanningLead |
| POST | `/liquidation-orders/{id}/execute` | Execute an APPROVED order: pulls stock, actual recovery valuation | StoreOpsLead |
| POST | `/liquidation-orders/{id}/cancel` | Cancel a DRAFT liquidation order | PlanningLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_VENDOR_DISCRETION` | 403 |
| `ERR_OTB_FORWARD_EXCEEDED` | 422 |
| `ERR_OTB_PACKAWAY_EXCEEDED` | 422 |
| `ERR_TARGET_SEASON_NOT_DRAFT` | 422 |
| `ERR_HOLD_WINDOW_CLOSED` | 422 |
| `ERR_TARGET_SEASON_NOT_OPEN` | 422 |
| `ERR_AGING_REVIEW_PREMATURE` | 422 |
| `ERR_SEASON_NOT_OPEN` | 422 |
| `ERR_SEASON_ALREADY_OPEN` | 422 |
| `ERR_OPEN_LOTS_REMAIN` | 422 |
| `ERR_PACKAWAY_HOLDS_ACTIVE` | 422 |
| `ERR_PLAN_NOT_EXECUTABLE` | 422 |
| `ERR_LOT_ALREADY_ALLOCATED` | 422 |
| `ERR_CLUSTER_UNCOVERED` | 422 |
| `ERR_WAREHOUSE_OVER_CAPACITY` | 422 |
| `ERR_STORE_OVER_CAPACITY` | 422 |
| `ERR_TICKET_NOT_ISSUED` | 422 |
| `ERR_TICKET_IN_USE` | 422 |
| `ERR_RECEIPT_LINE_QTY_INVALID` | 422 |
| `ERR_NEGATIVE_ON_HAND` | 422 |
| `ERR_SHRINK_EXCEEDS_ON_HAND` | 422 |
