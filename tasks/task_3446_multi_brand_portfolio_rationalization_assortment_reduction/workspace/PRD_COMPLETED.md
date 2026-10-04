# Multi-Brand Portfolio Rationalization API — Product Requirements Document

## 1. Introduction

A multi-brand consumer-products company operates dozens of brands that share manufacturing plants, distribution infrastructure, and retailer relationships. Over time the portfolio accumulates low-volume items that dilute shelf productivity, plants that run under-utilized, and non-core brands that would be worth more in someone else's hands. Acting on any of these levers is organizationally hard: cutting an item risks retailer backlash and consumer complaints, divesting a brand strands shared operations unless a transition service agreement bridges the gap, closing a plant strands production unless every item is transferred and re-qualified elsewhere, and funding innovation across many brands requires a disciplined, auditable allocation of a finite capital pool.

This document specifies the Multi-Brand Portfolio Rationalization API, the system of record for that work. It governs five interlocking pipelines — item-level rationalization cases with a scored cut recommendation, brand divestitures wrapped in transition service agreements, manufacturing-footprint consolidation through guarded product transfers and qualification runs, combined multi-brand shelf negotiations with a single retailer buyer, and capital-cycle innovation funding through a priority-ranked waterfall — all reading a single logical clock so that deadlines, service windows, and offer expirations are deterministic.

All resources are served under the `/portfolio` URL prefix, with exactly one exception: the logical-clock endpoint described in §2.4 is a platform endpoint mounted outside the prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. The system recognizes exactly six roles, spelled exactly as follows: `PortfolioManager`, `BrandManager`, `PlantDirector`, `RetailerBuyer`, `SupplyChainPlanner`, and `FinanceController`. A missing `X-User-Role` header, or a value outside these six, is rejected with `ERR_MISSING_ROLE` (HTTP 401). A missing or empty `X-User-ID` header is rejected with `ERR_MISSING_USER_ID` (HTTP 401). When the caller's role is not in the target endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity semantics differ by role and are normative. When `X-User-Role` is `BrandManager`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's foreign-key field to `X-User-ID` — concretely, a `BrandManager` may create items and innovation projects only for the brand whose `id` equals their `X-User-ID`. When `X-User-Role` is `PlantDirector`, `X-User-ID` is the `id` of the acting `Plant`; the caller may certify a qualification run only when their `X-User-ID` equals the transfer's target plant `id`. When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting `Retailer`; the caller may respond to a combined negotiation only when their `X-User-ID` equals the negotiation's retailer `id`. When `X-User-Role` is `PortfolioManager`, `SupplyChainPlanner`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proposer_user_id` on a `RationalizationCase` or `decider_user_id` on a decided case) but does not compare it to any entity's `id`. A violation of any entity-backed ownership rule is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403); the opaque roles are exempt from ownership comparison.

`PortfolioManager` is the corporate portfolio executive and exclusively owns brand, plant, retailer, rationalization-case, divestiture, footprint-closure, and combined-negotiation mutations. `SupplyChainPlanner` exclusively plans product transfers and performs inventory sell-down. `FinanceController` exclusively controls capital cycles, runs selection, and terminates transition service agreements. `PlantDirector` exclusively records qualification runs at the directed plant, and `RetailerBuyer` exclusively responds to combined negotiations for the represented retailer. Item creation and innovation-project creation are shared between `PortfolioManager` and `BrandManager` (the latter restricted to the owned brand). All six roles may call every read endpoint.

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

Failures that never reach a route handler use the same envelope: a request path matching no route is rejected with `ERR_NOT_FOUND` (HTTP 404), a matched path with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an unexpected internal failure is reported as `ERR_INVALID_REQUEST` with HTTP 500.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, and its accepted range runs from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` value that is not a base-10 integer, a `limit` outside the 1..100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; records created at the same logical instant keep their relative creation order — the tie-break is never the `id`. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. `total_count` counts every record matching the endpoint's filters, independent of the page returned, and `has_more` is true exactly when `offset` plus the number of items in the returned page is still below `total_count`.

### 2.4. The Logical Clock

The server maintains a single logical clock that every deadline, service window, expiration, and timing rule in this document reads. At startup, before any clock-setting call has been made, the logical clock reads exactly 2026-09-01T00:00:00Z; this is a fixed default and the server never falls back to wall-clock time.

Time is advanced through a platform endpoint that is **not** mounted under the `/portfolio` prefix: `POST /_clock/set_current_utc` takes a single body field `to_iso8601` and sets the logical clock to that instant, responding with the new value as `current_utc`. All six roles may advance the clock, the response carries HTTP 200, and the call mutates no entity — it only moves the clock. Every rule phrased as "the logical clock" elsewhere in this document refers to the value most recently set this way (or the fixed default if never set). Timestamps the server records against state changes — for example `terminated_at` on a transition service agreement or the approval instant that anchors a sell-through deadline — are the logical clock's value at the moment of the mutation.

### 2.5. Common Resource Properties

Every entity in this API carries an `id` that is a server-minted UUID with no type prefix, assigned at creation. Every entity also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. All entities except `QualificationRun` additionally carry `updated_at` (same timestamp format, refreshed on every mutation of the resource) and `version` (an integer that starts at 1 and increments by exactly 1 on every mutation of that resource, including mutations performed as side effects of operations on other resources). `QualificationRun` is the sole exception: it is an immutable event record carrying only `id` and `created_at`, and both `updated_at` and `version` are absent from it. Datetime-valued request fields (such as `to_iso8601`, `closure_date`, `expected_close_date`, `run_date`, and the TSA, negotiation, and cycle window bounds) are ISO 8601 strings; a trailing `Z` or a numeric UTC offset is accepted, and a value carrying no offset is read as UTC.

Foreign-key relationships are expressed as plain `id`-valued fields — `brand_id` on an `Item` names its owning `Brand`, `primary_plant_id` names the `Plant` currently producing the item, and so on. There are no nested ownership trees: all entities are peers joined by foreign keys. On nested reads and parameterized paths, path identifiers are resolved strictly left to right — the parent segment's existence is confirmed before any sub-resource segment is considered — and any unresolved path or body foreign-key identifier is rejected with `ERR_NOT_FOUND` (HTTP 404). List endpoints that accept foreign-key filters (such as `brand_id` on the item list, `item_id` on the case list, or `divestiture_id` on the TSA list) provide reverse reachability from a parent to its children. Filter values match exactly, and a filter value that matches no record yields an empty page with HTTP 200, not an error.

### 2.6. Precision, Rounding, and Integer Arithmetic

Scores and percentages in this API are carried to exactly 2 decimal places using round-half-up rounding (a fractional part of exactly one-half of the final kept digit rounds away from zero). Monetary amounts are always integer cents — no fractional cents exist anywhere in the system. Two rounding disciplines recur and must not be conflated. Per-item plant load is computed by rounding each item's quarterly commitment individually to a whole number of units (round half up) and only then summing; rounding the sum instead of the terms is forbidden. Two gates in the system — the qualification reject-rate gate and the transfer capacity gate — are pure integer comparisons with no rounding at all, and their boundary behavior is exact: a value precisely at the threshold passes, and the smallest integer step beyond it fails. Where a rule prescribes an order of operations (for example the TSA early-termination penalty's ceiling, then multiplication, then rounding), that order is part of the contract and reordering it is a defect, because different orders yield different cents.

### 2.7. Optimistic Concurrency Control

Exactly one endpoint in the API is guarded by optimistic concurrency control: selling down an item's finished-goods inventory. A sell-down request must carry `expected_item_version`, a non-optional input field holding the value of the item's `version` the client last observed. If that value does not equal the item's current `version` at the moment the write is attempted — because another writer has since sold the item down, or a divestiture cascade has touched it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated. No other endpoint takes a version field; clients must not send one elsewhere.

### 2.8. Validation Precedence

When several validation rules could reject the same request, the server evaluates them in a fixed global order, and the first failing check determines the error returned. The order is:

1. The `X-User-Role` header is present and names one of the six declared roles (`ERR_MISSING_ROLE`).
2. The `X-User-ID` header is present and non-empty (`ERR_MISSING_USER_ID`).
3. The endpoint permits the caller's role (`ERR_FORBIDDEN_ROLE`).
4. The request body is well-formed: required fields present, types correct, enum members valid, integer ranges honored — for example `private_label_share_pct` between 0 and 100 inclusive, `strategic_fit_score` between 0 and 100 inclusive, `units_produced` at least 1 — and unknown enum values rejected (`ERR_INVALID_REQUEST`).
5. Path `id` parameters resolve, checked left to right (`ERR_NOT_FOUND`).
6. Body foreign-key identifiers resolve — `brand_id`, `primary_plant_id`, `item_id`, `source_plant_id`, `target_plant_id`, `retailer_id`, `funding_cycle_id`, and each brand id inside `brand_terms` (`ERR_NOT_FOUND`).
7. Generic single-entity and cross-entity state guards (`ERR_INVALID_STATE`), with the specialized state errors of the next step layered on top where defined.
8. Transfer-creation state guards: the item must be `LISTED` (`ERR_ITEM_NOT_TRANSFERABLE`) and the target plant must be `OPERATING` (`ERR_TARGET_PLANT_NOT_OPERATING`).
9. Entity-backed ownership rules (`ERR_OWNERSHIP_MISMATCH`).
10. Segregation of duties on case decisions (`ERR_SELF_DECISION`).
11. Uniqueness and open-work singletons (`ERR_DUPLICATE`, `ERR_CASE_ALREADY_OPEN`, `ERR_DIVESTITURE_ALREADY_OPEN`, `ERR_TRANSFER_ALREADY_OPEN`, `ERR_NEGOTIATION_ALREADY_OPEN`).
12. Transfer structural checks: target differs from source (`ERR_SAME_PLANT`) and the claimed source equals the item's current primary plant (`ERR_SOURCE_PLANT_MISMATCH`).
13. Negotiation composition: `brand_terms` size and distinctness (`ERR_NOT_COMBINED`) and every referenced brand `ACTIVE` (`ERR_BRAND_NOT_NEGOTIABLE`).
14. Divestiture eligibility and signing-window checks (`ERR_BRAND_CORE`, `ERR_CLOSE_DATE_OUTSIDE_TSA`).
15. Run payload sanity: `units_rejected` no greater than `units_produced` (`ERR_INVALID_RUN`).
16. Capital-cycle window validity and non-overlap (`ERR_CYCLE_WINDOW_OVERLAP`).
17. Negotiation window validity and non-overlap (`ERR_NEGOTIATION_WINDOW_OVERLAP`).
18. Negotiation response time-to-live (`ERR_NEGOTIATION_EXPIRED`).
19. Timing gates on case finalization (`ERR_SELL_THROUGH_OPEN`) and divestiture close (`ERR_TSA_NOT_STARTED`).
20. Transfer capacity gate on the target plant (`ERR_PLANT_OVER_CAPACITY`).
21. Sell-down quantity bounds (`ERR_INSUFFICIENT_UNITS`).
22. Innovation-project size against the cycle total (`ERR_CAPITAL_REQUEST_TOO_LARGE`).
23. The optimistic-concurrency check on sell-down (`ERR_STALE_VERSION`) is evaluated last.

A consequence of this ordering worth calling out: proposing a rationalization case for an item that is `DISCONTINUED` fails at step 7 with `ERR_INVALID_STATE`, while proposing one for an item in `CUT_PROPOSED` or `SELL_THROUGH` — states that imply an open case — fails later, at step 11, with `ERR_CASE_ALREADY_OPEN`.

### 2.9. Uniqueness and Open-Work Singletons

Two families of rules keep the portfolio's bookkeeping unambiguous. First, scalar uniqueness: a brand `name` is unique across all brands, a plant `name` is unique across all plants, a retailer `name` is unique across all retailers, an item `sku_code` is unique across all items, and a capital cycle `period_code` is unique across all cycles; violating any of these is rejected with `ERR_DUPLICATE` (HTTP 409). Second, open-work singletons: an item may have at most one open rationalization case — where open means `SCORED` or `EXECUTING` — and a second proposal is rejected with `ERR_CASE_ALREADY_OPEN`; a brand may have at most one open divestiture — `PROPOSED`, `SPA_SIGNED`, or `CLOSED` — and a second proposal is rejected with `ERR_DIVESTITURE_ALREADY_OPEN`; an item may have at most one open product transfer — `PLANNED` or `QUALIFYING` — and a second plan is rejected with `ERR_TRANSFER_ALREADY_OPEN`; and a retailer may have at most one `TERMS_PROPOSED` combined negotiation per `period_code`, with a duplicate rejected as `ERR_NEGOTIATION_ALREADY_OPEN`. A rejected rationalization case releases its item's open-case slot (the item returns to `LISTED`), so a later case may be proposed again for the same item.

## 3. Business Logic & Workflows

### 3.1. Building the Portfolio: Brands, Plants, Retailers, and Items

Everything in the system hangs off four foundation entities. A `PortfolioManager` registers a **brand** by supplying its `name`, a free-form `category_name` label (a plain attribute such as `kitchen-storage`, not an entity in its own right), a `core_flag` marking whether the brand is core to the portfolio, the `private_label_share_pct` — an integer percent from 0 to 100 capturing how much of the brand's category the retailer's own private label already holds — and `annual_net_revenue_cents`, the brand-level annual net revenue in integer cents, zero or greater. A new brand starts life `ACTIVE`. The `core_flag` has a lasting consequence: a brand marked core (`core_flag` true) is never divestable, while a non-core brand is a divestiture candidate.

A `PortfolioManager` likewise registers each **plant** with a unique `name` and a `quarterly_capacity_units`, the plant's production capacity per quarter in whole units, which must be greater than zero. Plants are born `OPERATING`. Two computed readouts accompany every plant and are visible on plant reads: `committed_units_per_quarter` and `utilization_pct`, defined in §3.4.

A **retailer** is registered with a unique `name` and a `risk_rating` of `LOW`, `MEDIUM`, or `HIGH`, capturing the relationship risk the company assigns to that account.

Items are the unit of rationalization. Creating an **item** requires its `brand_id` and `primary_plant_id` (the plant currently producing it), a globally unique `sku_code`, the `annual_units` volume (zero or greater), `unit_net_revenue_cents` and `unit_cost_cents` — net revenue and fully absorbed cost per unit, both in integer cents and both zero or greater — and `units_on_hand`, the finished-goods inventory at creation. An optional `salvageable` flag, defaulting to false, records whether residual inventory has salvage value; it selects which obsolescence variant applies when the item is eventually discontinued (§3.2). A `BrandManager` may create items only under the brand they manage — the request's `brand_id` must equal their `X-User-ID`, failing which the create is rejected with `ERR_OWNERSHIP_MISMATCH` — while a `PortfolioManager` may create items for any brand. Item creation is state-guarded on both parents: the brand must be `ACTIVE` or `UNDER_REVIEW` and the named primary plant must be `OPERATING`; otherwise the create fails with `ERR_INVALID_STATE`. A new item starts `LISTED`. Two lifecycle counters accompany it from birth, both starting at zero: `units_sold_cumulative` and `units_written_off_cumulative`, plus an `obsolescence_charge_cents` accumulator that also starts at zero. Creating an item immediately changes its host plant's load: the plant's `committed_units_per_quarter` and `utilization_pct` are recomputed to include the newcomer.

### 3.2. The Rationalization Case: Scoring, Deciding, and Selling Through

When the portfolio team suspects an item no longer earns its shelf slot, a `PortfolioManager` proposes a **rationalization case** for it by supplying the `item_id`. Creation is guarded: the item must be `LISTED`. An item in `DISCONTINUED` is rejected with `ERR_INVALID_STATE`; an item already in `CUT_PROPOSED` or `SELL_THROUGH` necessarily has an open case and the proposal is rejected with `ERR_CASE_ALREADY_OPEN`. The server stamps the case with `proposer_user_id` taken from the caller's `X-User-ID` — this value anchors the segregation-of-duties rule at decision time — and the act of proposing moves the item from `LISTED` to `CUT_PROPOSED`, incrementing the item's `version`.

Scoring happens at creation, not at decision. The server computes four sub-scores from the item and its brand, each clamped to the range 0 to 100 and each rounded half-up to 2 decimal places, and stores them on the case as `volume_score`, `margin_score`, `shelf_resilience_score`, and `backlash_resilience_score`:

- The `volume_score` rewards cutting low-volume items: it is 100 minus the item's `annual_units` expressed as a percentage of a reference volume of 50,000 units per year (the constant 50000) — that is, `annual_units` divided by 50,000, multiplied by 100, subtracted from 100 — clamped into 0..100.
- The `margin_score` rewards cutting low-margin items. The item's margin percentage is its `unit_net_revenue_cents` minus its `unit_cost_cents`, divided by `unit_net_revenue_cents`; the score is then the shortfall of that margin below a reference margin of 35 percent (the constant 0.35 expressed as a fraction), expressed as a fraction of the 35-percent reference and scaled to 100 — clamped into 0..100. Edge case: when `unit_net_revenue_cents` is zero the margin percentage is undefined and the `margin_score` is set directly to 100.00.
- The `shelf_resilience_score` measures how easily the retailer's shelf absorbs the cut: the item's revenue share of its brand is `annual_units` times `unit_net_revenue_cents`, divided by the brand's `annual_net_revenue_cents`; the score is 100 minus that share expressed against a reference share of 20 percent and scaled to 100, clamped into 0..100. When the brand's `annual_net_revenue_cents` is zero, the revenue share is defined as 0.
- The `backlash_resilience_score` measures how little consumer backlash a cut provokes: it begins from 100 times one minus the brand's `annual_net_revenue_cents` divided by a reference brand scale of 10,000,000,000 cents (the constant 10000000000) — small brands score high — clamped into 0..100, and is then multiplied by a private-label damping factor equal to 0.5 plus 0.005 times the brand's `private_label_share_pct`. A brand whose category is already half private label (`private_label_share_pct` of 100) damps backlash by the full factor of 1.0; a brand with no private-label presence damps by only 0.5.

The `composite_score` is then computed **from the four already-rounded sub-scores** as a weighted blend — 0.30 times `volume_score`, plus 0.25 times `margin_score`, plus 0.20 times `shelf_resilience_score`, plus 0.25 times `backlash_resilience_score` — and the blend itself is rounded half-up to 2 decimal places. Computing the composite from unrounded sub-scores is a defect. The case's `recommendation` is derived from the composite alone: a `composite_score` of at least 65 yields a recommendation of `CUT`; anything below 65 yields `KEEP`. A worked example fixes the calibration: for a brand with `annual_net_revenue_cents` of 1,000,000,000 and `private_label_share_pct` of 40, and an item with `annual_units` 10,000, `unit_net_revenue_cents` 2,000, and `unit_cost_cents` 1,700, the four sub-scores come out to 80.00, 57.14, 90.00, and 63.00, the `composite_score` is 72.04, and the `recommendation` is `CUT`. A new case starts in `SCORED` with `decider_user_id` null.

A `SCORED` case waits for a decision by a `PortfolioManager`, who supplies a `decision` of `APPROVE` or `REJECT`. Segregation of duties is enforced: the deciding caller's `X-User-ID` must differ from the case's `proposer_user_id`, and a self-decision is rejected with `ERR_SELF_DECISION` (HTTP 403). The case must still be `SCORED` and — for an approval — the item must still be `CUT_PROPOSED`; otherwise the decide fails with `ERR_INVALID_STATE`. Either way the server records the decider's `X-User-ID` into `decider_user_id`.

An `APPROVE` decision moves the case from `SCORED` to `EXECUTING` and the item from `CUT_PROPOSED` to `SELL_THROUGH`, stamping the item's `sell_through_deadline` as the logical-clock timestamp of the decision plus exactly 90 days, with the time-of-day preserved. The 90-day sell-through window is the period during which remaining inventory is sold down through normal channels; the `sell_through_deadline` field is null at all other times in an item's life. A `REJECT` decision is a compensating revert: the case moves from `SCORED` to `REJECTED` and the item returns from `CUT_PROPOSED` to `LISTED`, which releases the open-case slot and conserves the brand's count of `LISTED` items across the propose-then-reject round trip (invariant `inv_item_unit_and_listed`). Both branches increment the case's `version` and the item's `version` by 1 each.

Finalization closes the loop. A `PortfolioManager` finalizes a case only when three conditions hold together: the case is `EXECUTING`, the item is still `SELL_THROUGH`, and the logical clock has reached the item's `sell_through_deadline` — the boundary is inclusive, so a finalize at exactly the deadline instant is allowed, and an earlier attempt is rejected with `ERR_SELL_THROUGH_OPEN` (HTTP 409). Finalizing moves the case to `EXECUTED` and the item to `DISCONTINUED`, posts the item's obsolescence charge, writes off the remaining inventory, and recomputes the host plant's load now that the item has left the committed set.

The **obsolescence charge** comes in two variants selected by the item's `salvageable` flag. Under the `STANDARD` variant (`salvageable` false), the charge is the full remaining cost: `units_on_hand` multiplied by `unit_cost_cents`, with no recovery. Under the `SALVAGE` variant (`salvageable` true), 20 percent of the cost is recovered, so the charge is 80 percent of the full cost — `units_on_hand` times `unit_cost_cents` times 0.8 — rounded half-up to integer cents; identical inputs always yield a strictly smaller charge under `SALVAGE` than under `STANDARD` (100 units at 500 cents cost: 50,000 cents standard versus 40,000 cents salvage). Posting the charge adds it into the item's `obsolescence_charge_cents` accumulator, adds the written-off `units_on_hand` into `units_written_off_cumulative`, and sets `units_on_hand` to zero. Across every sell-down, finalize, and divestiture cascade, the item's unit balance is conserved: `units_on_hand` plus `units_sold_cumulative` plus `units_written_off_cumulative` always equals the `units_on_hand` the item was created with (`inv_item_unit_and_listed`).

### 3.3. Selling Down Finished-Goods Inventory

A `SupplyChainPlanner` sells down an item's finished-goods stock by supplying `units_sold` alongside the optimistic-concurrency field `expected_item_version` described in §2.7. Sell-down is permitted only while the item is `LISTED` or `SELL_THROUGH`; any other state is rejected with `ERR_INVALID_STATE`. The quantity must be at least 1 and no greater than the item's current `units_on_hand`, otherwise the call is rejected with `ERR_INSUFFICIENT_UNITS` (HTTP 422). A successful sell-down subtracts `units_sold` from `units_on_hand`, adds it to `units_sold_cumulative`, and increments the item's `version` by 1 — which is precisely what makes a concurrently-held `expected_item_version` go stale. Sell-down never changes `item_status`; an item in `SELL_THROUGH` that sells its last unit remains `SELL_THROUGH` until its case is finalized.

### 3.4. Footprint Consolidation: Plant Load, Closures, Transfers, and Qualification

A plant's load readouts are recomputed whenever an item is created, whenever an item is discontinued (at case finalization or through a divestiture cascade), and whenever an item's `primary_plant_id` changes through transfer execution. The `committed_units_per_quarter` of a plant is the sum, over every item whose `primary_plant_id` is this plant and whose `item_status` is one of `LISTED`, `CUT_PROPOSED`, or `SELL_THROUGH`, of that item's `annual_units` divided by 4 and rounded half-up to a whole number of units — the rounding happens per item, before the sum; `DISCONTINUED` items are excluded entirely. The `utilization_pct` is that committed figure divided by the plant's `quarterly_capacity_units`, multiplied by 100, and rounded half-up to 2 decimal places.

Closing a plant is a two-step, one-way ritual performed by a `PortfolioManager`. Announcing the closure requires the plant to be `OPERATING` and supplies a `closure_date`; the plant moves to `CLOSING`, records the supplied `closure_date` (which is null while a plant is `OPERATING`), and increments its `version`. `CLOSING` is a point of no return — there is no abort transition. A `CLOSING` plant still hosts sell-down activity and qualification runs already in flight, but it can no longer be chosen as a transfer target and cannot be named as the primary plant of a newly created item. Completing the closure requires the plant to be `CLOSING` and is additionally guarded by two emptiness conditions, both checked at completion time: no item may still name the plant as its `primary_plant_id` while in `LISTED`, `CUT_PROPOSED`, or `SELL_THROUGH` (everything must have been transferred out or discontinued), and no product transfer sourced from this plant may still be `PLANNED` or `QUALIFYING`. If either guard fails the completion is rejected with `ERR_INVALID_STATE`. A completed closure moves the plant to `CLOSED` and increments its `version`.

A **product transfer** — the `ProductTransfer` entity — is how production moves between plants. A `SupplyChainPlanner` plans one by naming the `item_id`, the `source_plant_id`, and the `target_plant_id`. Creation is guarded by a battery of checks. The item must be `LISTED` — an item in any other status is rejected with `ERR_ITEM_NOT_TRANSFERABLE` (HTTP 409) — and the item must not already have an open transfer (`ERR_TRANSFER_ALREADY_OPEN`). The target plant must be `OPERATING`; a `CLOSING` or `CLOSED` target is rejected with `ERR_TARGET_PLANT_NOT_OPERATING` (HTTP 409). The `target_plant_id` must differ from the `source_plant_id` (`ERR_SAME_PLANT`, HTTP 422), and the claimed `source_plant_id` must equal the item's current `primary_plant_id` (`ERR_SOURCE_PLANT_MISMATCH`, HTTP 422). Finally, the target plant must absorb the incoming load: the **capacity gate** projects the target's load by adding the incoming item's quarterly commitment — its `annual_units` divided by 4, rounded half-up to whole units — to the target's current `committed_units_per_quarter`, and allows the transfer only if the projected figure does not exceed 110 percent of the target's `quarterly_capacity_units`. The comparison is pure integer cross-multiplication — projected times 100 must be less than or equal to capacity times 110 — with no floating-point rounding; a projected utilization of exactly 110.00 percent is allowed and 110.01 percent is rejected with `ERR_PLANT_OVER_CAPACITY` (HTTP 422). A new transfer starts `PLANNED` with `consecutive_pass_count` zero.

Production re-qualification then proceeds as a series of trial runs at the target plant, each recorded by the `PlantDirector` of that plant — the caller's `X-User-ID` must equal the transfer's `target_plant_id`, otherwise the record is rejected with `ERR_OWNERSHIP_MISMATCH`, and the recorded run's `certifier_plant_id` is set to that `X-User-ID`. Each run supplies a `run_date` (the logical date the trial ran), `units_produced` (at least 1), and `units_rejected` (zero or greater and never more than `units_produced`, else `ERR_INVALID_RUN`, HTTP 422). Every run record carries a `transfer_id` naming the transfer it qualifies — this foreign key is what the per-transfer run list reads in reverse. Runs are accepted only while the transfer is `PLANNED` or `QUALIFYING`; any other transfer state fails with `ERR_INVALID_STATE`.

Every run's `result` is computed by a hard quality gate: the run `PASS`es if and only if `units_rejected` multiplied by 10,000 is less than or equal to `units_produced` multiplied by 250 — a reject rate of at most 250 basis points, evaluated as a pure integer comparison with no rounding, where a reject rate of exactly 250 basis points passes. Any other outcome is a `FAIL`. The first accepted run moves the transfer from `PLANNED` to `QUALIFYING`; subsequent runs are a self-loop within `QUALIFYING`. Each `PASS` increments the transfer's `consecutive_pass_count` by 1; each `FAIL` resets it to 0 — there is no failure ceiling and no cancel transition, so a string of failures simply keeps the transfer in `QUALIFYING`. Recording a run always mutates the transfer — the first run's `PLANNED`-to-`QUALIFYING` transition, the `consecutive_pass_count` update, and `updated_at` — so every accepted run, `PASS` or `FAIL`, increments the transfer's `version` by exactly 1. When a `PASS` brings `consecutive_pass_count` to 2, the transfer auto-executes in the same request: `transfer_status` becomes `EXECUTED`, the item's `primary_plant_id` is rewritten to the `target_plant_id`, both the source and the target plant recompute their `committed_units_per_quarter` and `utilization_pct`, the transfer's `version` increments, and the item's `version` increments by 1 as well. Two consecutive passes are required — the threshold of 2 passes is a fixed constant of the qualification process.

### 3.5. Divesting a Brand: SPA, Transition Services, and Separation

A brand's lifecycle is driven entirely by the divestiture pipeline — brands have no direct transition endpoint of their own. The pipeline begins when a `PortfolioManager` proposes a **divestiture**, naming the `brand_id`, the `acquirer_name`, a `headline_price_cents` (integer cents, zero or greater), and an `expected_close_date`. The target brand must be non-core: proposing a divestiture for a brand whose `core_flag` is true is rejected with `ERR_BRAND_CORE` (HTTP 422). The brand must not be `EXITED` (`ERR_INVALID_STATE`) and must not already have an open divestiture in `PROPOSED`, `SPA_SIGNED`, or `CLOSED` (`ERR_DIVESTITURE_ALREADY_OPEN`). A successful proposal creates the divestiture in `PROPOSED` and, as a side effect, moves the brand from `ACTIVE` to `UNDER_REVIEW`, incrementing the brand's `version`.

Signing the sale-and-purchase agreement embeds the transition-service terms: the caller supplies `tsa_monthly_fee_cents` (the monthly service fee charged to the acquirer, integer cents, zero or greater), a `tsa_start_date`, and a `tsa_end_date`. Signing requires the divestiture to be `PROPOSED`, and the window must be coherent: `tsa_start_date` strictly before `tsa_end_date`, with the divestiture's `expected_close_date` lying within the closed interval from `tsa_start_date` to `tsa_end_date` inclusive. A violation is rejected with `ERR_CLOSE_DATE_OUTSIDE_TSA` (HTTP 422). Signing moves the divestiture from `PROPOSED` to `SPA_SIGNED`, creates exactly one `TransitionServiceAgreement` in `DRAFT` bound to the divestiture — its `divestiture_id` pointing back, its `monthly_fee_cents`, `start_date`, and `end_date` taken from the signing payload, its `early_termination_penalty_cents` initialized to 0 and its `terminated_at` null — and moves the brand from `UNDER_REVIEW` to `DIVESTING`, incrementing both the divestiture's and the brand's `version`. The TSA list endpoint, filterable by `divestiture_id` or `tsa_status`, is the only read channel for the agreement created here.

Closing the divestiture requires it to be `SPA_SIGNED` and requires that the logical clock has reached the TSA's `start_date`; closing earlier is rejected with `ERR_TSA_NOT_STARTED` (HTTP 409), with the boundary inclusive — closing exactly at `start_date` is allowed. Closing moves the divestiture from `SPA_SIGNED` to `CLOSED`, flips the TSA from `DRAFT` to `ACTIVE`, and moves the brand from `DIVESTING` to `DIVESTED`, incrementing the `version` of all three records.

Final separation requires the divestiture to be `CLOSED` and its TSA to be `TERMINATED`; if services are still running (or the TSA has not even activated) the separation is rejected with `ERR_TSA_STILL_ACTIVE` (HTTP 409). Separation moves the divestiture from `CLOSED` to `SEPARATED` and the brand from `DIVESTED` to `EXITED`, incrementing both versions. `EXITED` is the brand's terminal state.

Terminating a TSA is a `FinanceController` prerogative, available only while the TSA is `ACTIVE` (otherwise `ERR_INVALID_STATE`). Termination stamps `terminated_at` with the logical clock and posts the **early-termination penalty** into `early_termination_penalty_cents`. The penalty calculation is order-sensitive and pinned. First, the days remaining are the whole days from the termination instant to `end_date`, rounded down; if that figure is zero or negative the termination is natural and the penalty is 0. Otherwise, step one: the months remaining are the days remaining divided by 30 days per penalty month and rounded **up** to a whole number of months. Step two: that month count is multiplied by the TSA's `monthly_fee_cents` and by the penalty rate of 0.25 (25 percent). Step three: the product is rounded half-up to integer cents — and this rounding happens exactly once, on the product. The alternative order — rounding a per-month penalty first and then multiplying — is forbidden, because it yields different cents: a `monthly_fee_cents` of 120,010 with 3 months remaining produces a penalty of 90,008 cents under the pinned order, versus 90,009 under the forbidden one. A worked example anchors the arithmetic end to end: a TSA starting 2026-09-01 and ending 2027-09-01, terminated at logical time 2027-06-15, has 78 days remaining, which is 3 penalty months, and at a 120,010-cent fee the posted penalty is 90,008 cents.

Termination is also the portfolio's deepest cascade, executed within the same request. Hop 1: every item of the divested brand whose `item_status` is `LISTED`, `CUT_PROPOSED`, or `SELL_THROUGH` is moved to `DISCONTINUED`, with its obsolescence charge posted per the two-variant rule of §3.2, its `units_on_hand` folded into `units_written_off_cumulative` and zeroed, and its `version` incremented. Hop 2: every open rationalization case on those items — whether `SCORED` or `EXECUTING` — is auto-`VOIDED`, with `decider_user_id` set to the literal string `system`, and each such case's `version` incremented. Hop 3: every plant that hosted a discontinued item recomputes its `committed_units_per_quarter` and `utilization_pct`. The TSA's own `version` increments as well.

### 3.6. Combined Negotiations with a Single Retailer Buyer

One retailer buyer often covers several of the company's brands, so shelf terms are negotiated as a bundle. A `PortfolioManager` opens a **combined negotiation** (a `CombinedNegotiation` record) by naming the `retailer_id`, a `period_code` label such as `2027-H1`, the `brand_terms` array, and an effective window from `effective_from` to `effective_to`. The composition rules are strict. `brand_terms` holds between 2 and 5 entries — fewer or more is rejected with `ERR_NOT_COMBINED` (HTTP 422) — each entry pairing a `brand_id` with a `baseline_facings` and a `proposed_facings`, both integers of zero or greater; the brand ids within one negotiation must be distinct, with duplicates likewise rejected as `ERR_NOT_COMBINED`. Every referenced brand must currently be `ACTIVE`: including a brand that is `UNDER_REVIEW`, `DIVESTING`, `DIVESTED`, or `EXITED` trips the channel-conflict guard and is rejected with `ERR_BRAND_NOT_NEGOTIABLE` (HTTP 422). The window itself must be coherent — `effective_from` strictly before `effective_to`, else `ERR_INVALID_REQUEST` — and the closed interval from `effective_from` through `effective_to` must not overlap any other negotiation of the same retailer in `TERMS_PROPOSED` or `ACCEPTED`; overlap is tested inclusively, so two windows that share even a single boundary day count as overlapping, and a violation is rejected with `ERR_NEGOTIATION_WINDOW_OVERLAP` (HTTP 422). Separately, the retailer may not already hold a `TERMS_PROPOSED` negotiation for the same `period_code` (`ERR_NEGOTIATION_ALREADY_OPEN`).

At creation the server aggregates the terms: `total_baseline_facings` is the sum of `baseline_facings` across `brand_terms`, `total_proposed_facings` is the sum of `proposed_facings`, and `shelf_reduction_pct` is the difference between the two totals divided by the baseline total, multiplied by 100, and rounded half-up to 2 decimal places; when the baseline total is 0 the reduction is defined as 0.00. The negotiation is born `TERMS_PROPOSED` with an `expires_at` stamped as its `created_at` plus exactly 30 days — the offer's time-to-live.

The retailer's buyer responds with a `response` of `ACCEPT` or `REJECT`, and only the buyer whose `X-User-ID` equals the negotiation's `retailer_id` may do so (`ERR_OWNERSHIP_MISMATCH` otherwise). Responding while the negotiation is `TERMS_PROPOSED` and the logical clock is at or before `expires_at` moves it to `ACCEPTED` or `REJECTED` accordingly and increments its `version`. Once the logical clock is strictly later than `expires_at`, the respond attempt itself fails with `ERR_NEGOTIATION_EXPIRED` (HTTP 409) and the negotiation auto-transitions to `EXPIRED`, its `version` still incrementing. The boundary is precise: a clock exactly equal to `expires_at` is still a valid response instant; expiry requires a strictly later clock.

### 3.7. Innovation Capital: Cycles, Priorities, and the Allocation Waterfall

Innovation funding is rationed through **capital cycles** (`CapitalCycle` records). A `FinanceController` creates a cycle with a unique `period_code`, a `total_capital_cents` pool in integer cents (greater than zero), and a funding window from `window_start` to `window_end`. The window is half-open: it includes `window_start` and excludes `window_end`, `window_start` must be strictly before `window_end`, and it must not overlap any existing cycle's window. Overlap is tested under the half-open convention — two windows overlap when each starts before the other ends — so a new window that begins exactly when an existing window ends is adjacency, not overlap, and is allowed; a true overlap is rejected with `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 422). A cycle's `cycle_status` is born `ALLOCATING` with `allocated_cents` at 0; its `remaining_cents` is always the pool minus what has been allocated.

Brands compete for the pool through **innovation projects** (`InnovationProject` records). Creating one names the `brand_id` receiving the investment, the `funding_cycle_id` it competes in, a `title`, the `requested_capital_cents` (greater than zero and no greater than the cycle's `total_capital_cents` — an oversized request is rejected with `ERR_CAPITAL_REQUEST_TOO_LARGE`, HTTP 422), the `expected_revenue_cents_year3` (expected annual revenue in the project's third year, zero or greater), and a `strategic_fit_score` from 0 to 100 inclusive. A `BrandManager` may propose projects only for the owned brand (`ERR_OWNERSHIP_MISMATCH` otherwise); creation also requires the brand to be `ACTIVE` or `UNDER_REVIEW` and the cycle to be `ALLOCATING` (`ERR_INVALID_STATE` otherwise). The project is born `PROPOSED`.

Its `priority_score` is computed at creation and comes in two variants selected by the brand's `core_flag`. Both variants start from the same blend: a revenue score equal to `expected_revenue_cents_year3` expressed as a percentage of a year-3 reference revenue of 2,000,000,000 cents (the constant 2000000000) and capped at 100, weighted at 0.40, plus the `strategic_fit_score` weighted at 0.60; the blend is rounded half-up to 2 decimal places. Under the `STANDARD` variant (`core_flag` false), that rounded blend is the `priority_score`. Under the `CORE_BRAND` variant (`core_flag` true), a bonus of exactly 10 points is added **after** the rounding, and the result is then capped at 100. Identical project inputs therefore score strictly higher for a core brand: a project with `strategic_fit_score` 80 and `expected_revenue_cents_year3` of 1,000,000,000 scores 68.00 under `STANDARD` and 78.00 under `CORE_BRAND`.

Selection runs once per cycle, when a `FinanceController` triggers it on a cycle that is still `ALLOCATING` (otherwise `ERR_INVALID_STATE`). The selector takes every project in the cycle still `PROPOSED` — an empty set is legal and simply locks the cycle with `allocated_cents` of 0 — and ranks them by `priority_score` descending, breaking ties by `created_at` ascending — and projects still tied at the same logical instant keep their relative creation order — never by `id`. The waterfall then walks the ranked list with `remaining_cents` starting at `total_capital_cents`: a project whose `requested_capital_cents` fits within the current remainder — an exact fit counts, since the comparison is less-than-or-equal — becomes `FUNDED`, its request is added to `allocated_cents` and subtracted from the remainder; a project that does not fit becomes `DEFERRED`, and the walk **continues** down the list, so smaller later projects can still fund behind an oversized one. Every project the waterfall touches, `FUNDED` or `DEFERRED`, has its `version` incremented by 1. When the walk ends, the cycle moves to `LOCKED` (its terminal state) with its `version` incremented, and the response carries the final `allocated_cents` and `remaining_cents`. Capital is conserved throughout: after selection, `allocated_cents` plus `remaining_cents` always equals `total_capital_cents` (invariant `inv_capital_conservation`).

## 4. Endpoint Definitions

All endpoints except the platform clock are mounted under the `/portfolio` prefix. Endpoints that create a new resource respond with HTTP 201 and the created resource in `data` — recording a qualification run creates an immutable `QualificationRun` resource, so it responds 201 with the recorded run; endpoints that modify an existing resource or perform a read respond with HTTP 200. Request and response field semantics for every endpoint are those described in §2 and §3; this table is a navigational index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (unprefixed platform endpoint; startup default 2026-09-01T00:00:00Z). | All six roles |
| POST | `/portfolio/brands` | Create a brand (`ACTIVE`). | PortfolioManager |
| GET | `/portfolio/brands` | List brands, optionally filtered by `brand_status` or `category_name`. | All six roles |
| POST | `/portfolio/items` | Create an item (`LISTED`) under a brand at a primary plant; BrandManager callers must own the brand. | PortfolioManager, BrandManager |
| GET | `/portfolio/items` | List items, optionally filtered by `brand_id`, `primary_plant_id`, or `item_status`. | All six roles |
| GET | `/portfolio/items/{id}` | Get one item. | All six roles |
| POST | `/portfolio/items/{id}/sell-down` | Sell down finished-goods inventory (OCC-guarded); allowed while `LISTED` or `SELL_THROUGH`. | SupplyChainPlanner |
| POST | `/portfolio/plants` | Create a plant (`OPERATING`). | PortfolioManager |
| GET | `/portfolio/plants` | List plants, optionally filtered by `plant_status`; includes computed load readouts. | All six roles |
| POST | `/portfolio/plants/{id}/announce-closure` | Announce closure: `OPERATING` to `CLOSING`, sets `closure_date`. | PortfolioManager |
| POST | `/portfolio/plants/{id}/complete-closure` | Complete closure: `CLOSING` to `CLOSED`, guarded by empty-item and empty-transfer conditions. | PortfolioManager |
| POST | `/portfolio/retailers` | Create a retailer. | PortfolioManager |
| POST | `/portfolio/rationalization-cases` | Propose cutting an item; computes and stores the four sub-scores, `composite_score`, and `recommendation`; item becomes `CUT_PROPOSED`. | PortfolioManager |
| GET | `/portfolio/rationalization-cases` | List cases, optionally filtered by `item_id` or `case_status`. | All six roles |
| GET | `/portfolio/rationalization-cases/{id}` | Get one case. | All six roles |
| POST | `/portfolio/rationalization-cases/{id}/decide` | Decide a `SCORED` case: `APPROVE` starts sell-through, `REJECT` compensates the item back to `LISTED`; decider must differ from proposer. | PortfolioManager |
| POST | `/portfolio/rationalization-cases/{id}/finalize` | Finalize an `EXECUTING` case after the sell-through deadline: item `DISCONTINUED`, obsolescence posted, plant load recomputed. | PortfolioManager |
| POST | `/portfolio/divestitures` | Propose divesting a non-core `ACTIVE` brand; brand becomes `UNDER_REVIEW`. | PortfolioManager |
| GET | `/portfolio/divestitures` | List divestitures, optionally filtered by `brand_id` or `divestiture_status`. | All six roles |
| GET | `/portfolio/divestitures/{id}` | Get one divestiture. | All six roles |
| POST | `/portfolio/divestitures/{id}/sign-spa` | Sign the SPA with embedded TSA terms: `PROPOSED` to `SPA_SIGNED`, creates the TSA (`DRAFT`), brand becomes `DIVESTING`. | PortfolioManager |
| POST | `/portfolio/divestitures/{id}/close` | Close once the TSA window has started: `SPA_SIGNED` to `CLOSED`, TSA `DRAFT` to `ACTIVE`, brand becomes `DIVESTED`. | PortfolioManager |
| POST | `/portfolio/divestitures/{id}/separate` | Final separation: `CLOSED` to `SEPARATED`, requires TSA `TERMINATED`, brand becomes `EXITED`. | PortfolioManager |
| GET | `/portfolio/tsas` | List transition service agreements, optionally filtered by `divestiture_id` or `tsa_status`; the only read channel for the TSA created at signing. | All six roles |
| GET | `/portfolio/tsas/{id}` | Get one transition service agreement. | All six roles |
| POST | `/portfolio/tsas/{id}/terminate` | Terminate an `ACTIVE` TSA; posts the early-termination penalty and cascades discontinuation of the divested brand's live items, voiding of their open cases, and plant-load recomputation. | FinanceController |
| POST | `/portfolio/product-transfers` | Plan a transfer of a `LISTED` item to another `OPERATING` plant, subject to the 110% projected-utilization capacity gate. | SupplyChainPlanner |
| GET | `/portfolio/product-transfers` | List transfers, optionally filtered by `item_id`, `source_plant_id`, `target_plant_id`, or `transfer_status`. | All six roles |
| GET | `/portfolio/product-transfers/{id}` | Get one transfer. | All six roles |
| POST | `/portfolio/product-transfers/{id}/qualification-runs` | Record a qualification run at the target plant (caller must be that plant's director); computes `PASS`/`FAIL`, tracks consecutive passes, and auto-executes the transfer at 2 consecutive passes. | PlantDirector |
| GET | `/portfolio/product-transfers/{id}/qualification-runs` | List a transfer's qualification runs. | All six roles |
| POST | `/portfolio/combined-negotiations` | Open a combined multi-brand negotiation with one retailer; terms proposed at creation, shelf-reduction aggregates computed, 30-day TTL stamped. | PortfolioManager |
| GET | `/portfolio/combined-negotiations` | List negotiations, optionally filtered by `retailer_id` or `negotiation_status`. | All six roles |
| GET | `/portfolio/combined-negotiations/{id}` | Get one negotiation. | All six roles |
| POST | `/portfolio/combined-negotiations/{id}/respond` | The retailer's buyer accepts or rejects the combined terms; after `expires_at` the negotiation auto-marks `EXPIRED` and the call fails. | RetailerBuyer |
| POST | `/portfolio/capital-cycles` | Create a capital cycle (`ALLOCATING`) with a half-open, non-overlapping funding window. | FinanceController |
| POST | `/portfolio/capital-cycles/{id}/run-selection` | Run the priority-ranked allocation waterfall over the cycle's `PROPOSED` projects, then lock the cycle. | FinanceController |
| POST | `/portfolio/innovation-projects` | Propose an innovation project into an `ALLOCATING` cycle; `priority_score` computed at creation. | PortfolioManager, BrandManager |
| GET | `/portfolio/innovation-projects` | List projects, optionally filtered by `brand_id`, `funding_cycle_id`, or `project_status`. | All six roles |
| GET | `/portfolio/innovation-projects/{id}` | Get one innovation project. | All six roles |

## 5. Error Code Catalogue

Every error response uses the envelope of §2.2 with one of the following identifiers. Trigger conditions for each identifier are stated in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MISSING_ROLE` | 401 |
| `ERR_MISSING_USER_ID` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SELF_DECISION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_CASE_ALREADY_OPEN` | 409 |
| `ERR_DIVESTITURE_ALREADY_OPEN` | 409 |
| `ERR_TRANSFER_ALREADY_OPEN` | 409 |
| `ERR_NEGOTIATION_ALREADY_OPEN` | 409 |
| `ERR_ITEM_NOT_TRANSFERABLE` | 409 |
| `ERR_TARGET_PLANT_NOT_OPERATING` | 409 |
| `ERR_TSA_NOT_STARTED` | 409 |
| `ERR_TSA_STILL_ACTIVE` | 409 |
| `ERR_SELL_THROUGH_OPEN` | 409 |
| `ERR_NEGOTIATION_EXPIRED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SAME_PLANT` | 422 |
| `ERR_SOURCE_PLANT_MISMATCH` | 422 |
| `ERR_NOT_COMBINED` | 422 |
| `ERR_BRAND_NOT_NEGOTIABLE` | 422 |
| `ERR_BRAND_CORE` | 422 |
| `ERR_CLOSE_DATE_OUTSIDE_TSA` | 422 |
| `ERR_INVALID_RUN` | 422 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 422 |
| `ERR_NEGOTIATION_WINDOW_OVERLAP` | 422 |
| `ERR_PLANT_OVER_CAPACITY` | 422 |
| `ERR_INSUFFICIENT_UNITS` | 422 |
| `ERR_CAPITAL_REQUEST_TOO_LARGE` | 422 |
