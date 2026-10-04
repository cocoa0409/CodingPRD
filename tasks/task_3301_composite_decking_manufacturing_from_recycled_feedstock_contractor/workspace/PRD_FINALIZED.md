# Composite Decking Manufacturing API — Product Requirements Document

## 1. Introduction

This document specifies the Composite Decking Manufacturing API, the operational backbone for a single-plant manufacturer that extrudes composite deck boards from recycled polyethylene film and wood flour. The business runs against a strongly seasonal building calendar: inventory is built ahead of the season inside a pre-season window, sold through a two-step distribution network of dealers who carry stocking commitments by territory, and supported for years after sale through a contractor certification program and a warranty claim pipeline that adjudicates fading, staining, and structural defects against physical board samples.

The API must hold together several concerns that pull in different directions. Feedstock quality gates decide whether an inbound lot of post-consumer film or wood flour may enter production, and recycled content decays in storage, so material accounting is time-sensitive. Extrusion scheduling is slot-based with changeover penalties that depend on the previous run's color, profile, emboss, and capstock. Commercially, the system must price shipments from pinned price books with dealer-tier discounts, enforce credit limits, and penalize dealers who miss seasonal stocking commitments. On the aftermarket side, contractor tiers unlock longer enhanced warranties, and claim outcomes — credit, replacement, or repair — interact with inventory because replacement boards come from a deliberately maintained support stock that ordinary sales may not touch.

Every rule in this document is normative. The API is mounted under `/decking` and is exercised against a logical clock that begins at exactly `2026-09-01T00:00:00Z` before any request is made; the clock never falls back to wall-clock time and only advances when explicitly set.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes ten roles, spelled exactly as follows: `OpsManager`, `QualityEngineer`, `ProcessEngineer`, `ProductManager`, `ChannelManager`, `DealerSalesRep`, `Dealer`, `ProgramAdmin`, `Contractor`, and `ClaimsAdjuster`. A request missing either header, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` — for example a shipment order's `dealer_id` or a lead referral's `submitted_by_dealer_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on any resource that references a `Contractor` — such as an install registration's `contractor_id` or a lead referral's `assigned_contractor_id` — compare the resource's foreign-key field to `X-User-ID`. A contractor acting on another contractor's registration is rejected with `ERR_NOT_OWNER` (HTTP 403), and a lead decline attempted by anyone other than the current assignee is rejected with `ERR_NOT_ASSIGNEE` (HTTP 403).

The remaining eight roles — `OpsManager`, `QualityEngineer`, `ProcessEngineer`, `ProductManager`, `ChannelManager`, `DealerSalesRep`, `ProgramAdmin`, and `ClaimsAdjuster` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — plants, suppliers, collection programs, feedstock lots, formulations, product lines, dealers, shipment orders, stocking commitments, allocation commitments, production runs, board lots, contractors, training modules, training records, lead referrals, install registrations, warranty claims, claim samples, sample kits, color chip requests, and price books — carries a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating the last modification; refreshed on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including system-driven side effects that touch it.

Because side effects count as mutations, operations that update derived aggregates — for example releasing a feedstock lot, which adds its mass to the plant's feedstock store, or completing a production run, which adds finished goods — refresh `updated_at` and increment `version` on both the resource being acted upon and any other resource the side effect mutates.

### 2.5. Validation Ordering and Failure Semantics

Every request passes through a fixed validation cascade, evaluated in a strict order so that the first failing check determines the error returned. Authentication comes first: missing or unknown `X-User-Role` or missing `X-User-ID` yields `ERR_UNAUTHENTICATED`. Authorization comes second: a well-authenticated caller whose role is not permitted for the endpoint yields `ERR_UNAUTHORIZED`. Existence comes third: path parameters are validated left-to-right against existing resources, and the first missing path segment yields `ERR_NOT_FOUND`. Fourth, every foreign key supplied in a request body must reference an existing resource; a required body reference field that is absent is rejected with `ERR_INVALID_REQUEST`, and a dangling body reference — one that is present but resolves to no resource — yields `ERR_REFERENCED_NOT_FOUND`. Fifth, the target resource must be in a state that permits the requested transition, otherwise the request fails with `ERR_INVALID_STATE`. Only after these generic gates do business-specific checks run — feedstock lab limits, capacity, resin sufficiency, formulation balance, dealer credit, finished-goods availability, temporal windows, idempotence guards, product-line sellability, certification gates, ownership, and lab verdict gates — each mapped to its own error identifier and described in the workflow narratives of §3. A malformed payload or a missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Nested Resource Retrieval

Some resources are addressed through their parent in the URL hierarchy — production runs live under a plant, addressed by the plant's `id` followed by the run's `runId`. For any such nested path, the server validates identifiers strictly left-to-right: the parent identifier is resolved first, and if it does not exist the request is rejected with `ERR_NOT_FOUND` before the child identifier is even considered. A run addressed under a non-existent plant therefore fails on the plant's `id`, not on the `runId`. Foreign keys supplied in request bodies are a separate concern from path parameters: body references that do not resolve produce `ERR_REFERENCED_NOT_FOUND` rather than `ERR_NOT_FOUND`, and this applies to `supplier_id`, `dealer_id`, `product_line_id`, `formulation_id`, `module_id`, `contractor_id`, `install_registration_id`, `warranty_claim_id`, `price_book_id`, and `reservation_id` wherever they appear.

### 2.7. The Logical Clock and the Plant Capacity Review

Time inside the system is governed by a logical clock, not the wall clock. Before any request is processed the clock reads exactly `2026-09-01T00:00:00Z`. An admin-only, test-driving capability available to `OpsManager` advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock changes nothing else by itself: season posture, material decay, stale quarantine lots, reservation expiry, lead expiry, and contractor lapse are all recomputed only when the plant's periodic capacity review runs.

The capacity review is the plant's operations checkpoint, performed by an `OpsManager`. A single review performs all of the following against the addressed plant: it recomputes the plant's season posture from the logical clock date against the plant's pre-season window; it decays the post-consumer film mass held in the feedstock store; it sweeps feedstock lots that have sat in quarantine too long; it expires stale finished-goods reservations; it expires stale lead assignments; and it lapses idle contractors. Every day-granularity age computation the review performs — quarantine age, reservation age, lead age, and the contractor-lapse span — is measured against the logical clock, using each resource's logical-clock creation or transition date (never the wall-clock `created_at`). Each review increments the plant's `version` by one and refreshes its `updated_at`. Details of each sweep live with the corresponding workflow in §3.

### 2.8. Integer Arithmetic, Truncation, and Monetary Precision

This system deliberately avoids floating-point money and floating-point masses. All monetary amounts are integer cents. All feedstock masses are integer pounds, and all finished-goods quantities are integer linear feet. Percentages that must survive exact arithmetic are expressed in basis points, so ten thousand basis points equals one hundred percent.

Where a calculation would produce a fraction, the rounding rule is fixed per calculation in §3, and two disciplines recur. First, truncation (rounding down toward zero) is the default for masses, minutes-derived quantities, reliability scores, fill rates, credits, and invoice amounts. Second, per-day truncation is not interchangeable with one-shot truncation: when a decay is applied over several days, the floor is applied after each individual day in chronological order, never once on the compounded total. Unless a calculation states otherwise, monetary values are computed with a single truncation applied once at the end of the formula — intermediate ratios are never pre-rounded.

### 2.9. Optimistic Concurrency Control on Plant-Mutating Writes

Two write operations mutate plant-level aggregates whose correctness depends on the client having observed the plant's current state: reserving finished goods through an allocation commitment, and scheduling a production run. Both are exposed as plant-scoped creation endpoints, and both require a non-optional request field `expected_plant_version` carrying the plant `version` the client last observed.

If the supplied `expected_plant_version` does not match the plant's current `version` at the moment the request is processed, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule is framed purely in stale-version terms: a writer holding an outdated view of the plant's reservation or scheduling state must re-read the plant before writing, because reservation creation mutates the reserved finished-goods ledger and run scheduling assigns extrusion slots and consumes daily capacity. No other endpoint takes an `expected_plant_version` field, and no other resource participates in optimistic concurrency control; endpoints not listed here accept no version field at all.

### 2.10. Feedstock Accounting and Support-Stock Segregation

The plant tracks on-hand feedstock in a composite attribute `resin_store` with exactly four keys — `VIRGIN_PE`, `REPRO_PE`, `PCR_FILM`, and `WOOD_FLOUR` — each holding an integer number of pounds and each starting at zero when the plant is created. Finished goods are tracked separately in two parallel ledgers keyed by product line: `fg_store`, the sellable finished-goods position in linear feet, and `reserved_fg_store`, the portion of finished goods reserved by open allocation commitments. The reserved ledger is additive-only and independent of `fg_store`; it is incremented when a reservation is created and decremented when the reservation is consumed, released, or expired. Every key of both ledgers starts at zero at plant creation.

Feedstock enters the plant through quarantined lots and is only added to `resin_store` at release. Each release carries a disposition of `PRODUCTION` or `SUPPORT_STOCK`. Both dispositions add mass to `resin_store` identically, but the disposition matters downstream: a capped product line — one whose `capped` flag is true because the board carries a co-extruded polymer capstock — may not start a production run if the plant's post-consumer film stock originated exclusively from lots released as `SUPPORT_STOCK`. The rejection code for that situation is `ERR_SUPPORT_STOCK_BARRED`.

### 2.11. Season Posture

Each plant defines a pre-season inventory build window through `pre_season_window_start` and `pre_season_window_end`, both calendar dates in MM-DD form (for example, `01-01`), and the start must precede the end within the same calendar year. The plant's `season_posture` is either `PRE_SEASON` or `SELLING`, derived from the logical clock: when the clock's month-and-day falls within the window, inclusive of both endpoints, the posture is `PRE_SEASON`; otherwise it is `SELLING`. The boundary is inclusive at the end — a date exactly equal to `pre_season_window_end` is still `PRE_SEASON`, and the following day is `SELLING`. The posture is computed at plant creation and recomputed at every capacity review.

## 3. Business Logic & Workflows

### 3.1. Plants, Suppliers, and Collection Programs

An `OpsManager` onboards a plant by supplying its `name`, nominal extrusion capacity `daily_capacity_lf` in linear feet per calendar day (at least 1), the number of parallel extrusion `lines` (at least 1), and the pre-season window bounds `pre_season_window_start` and `pre_season_window_end`. At creation the feedstock store and both finished-goods ledgers are zeroed and the season posture is computed from the logical clock.

Feedstock originates from suppliers, registered by a `QualityEngineer` with a `name` and a `kind` of either `COLLECTION_PROGRAM` or `BROKER`; a supplier may in practice operate both a collection program and brokered sales, and `kind` records the registration classification rather than restricting the other activity. Every supplier begins with `quality_tier` `STANDARD` and a `reliability_score_bp` of 10000 basis points. Reliability is reportage only: it is recomputed whenever one of the supplier's lots is rejected, as ten thousand minus the ratio of rejected lot count to total lot count expressed in basis points, computed with integer truncation.

A `ChannelManager` formalizes recycled-film sourcing by creating a collection program against a supplier, providing the `supplier_id`, a `region` label, and a non-negative `rebate_per_lb_cents`. A program starts `ACTIVE`. Suspending a program moves it `ACTIVE → SUSPENDED`; reactivating moves it `SUSPENDED → ACTIVE`; termination moves it to `TERMINATED` from either `ACTIVE` or `SUSPENDED`. The supplier's `quality_tier` tracks program state: it is `PREFERRED` only while at least one `ACTIVE` collection program exists for that supplier, and it is recomputed on program creation, activation, suspension, and termination — so suspending a supplier's only active program drops the tier back to `STANDARD`, while reactivation restores `PREFERRED`. Each program maintains an `accrued_rebate_cents` ledger, starting at zero, that accumulates rebate cents earned on released post-consumer film lots while the program is `ACTIVE`; the program's read view exposes the running accrual.

### 3.2. Feedstock Intake, Lab Limits, and Lot Disposition

Inbound material arrives as a feedstock lot, registered by a `QualityEngineer` with the `supplier_id`, the `material` (one of `PCR_FILM`, `WOOD_FLOUR`, `REPRO_PE`, or `VIRGIN_PE`), a `weight_lbs` of at least 1, the `received_date` the lot physically arrived, a lab-measured `moisture_pct` carried to one decimal place, a lab-measured `contamination_ppm`, and a chain-of-custody `certificate_ref`. Polymer lots — `PCR_FILM`, `REPRO_PE`, and `VIRGIN_PE` — must also carry a `melt_flow_index`; the field is required for polymer lots and its absence on a polymer lot is itself a lab-limit breach. Every lot enters `QUARANTINE`.

A `QualityEngineer` releases a quarantined lot by providing a `release_disposition` of `PRODUCTION` or `SUPPORT_STOCK`. Release enforces material-specific lab limits, and a breach of any applicable limit is rejected with `ERR_LOT_LIMIT_EXCEEDED` (HTTP 422):

- `PCR_FILM`: `contamination_ppm` must be at most 2000, and `melt_flow_index` must lie in the inclusive range 0.3 to 1.2.
- `WOOD_FLOUR`: `moisture_pct` must be at most 8.0, and `contamination_ppm` must be at most 500.
- `REPRO_PE`: `contamination_ppm` must be at most 1500.
- `VIRGIN_PE`: `melt_flow_index` must lie in the inclusive range 0.4 to 1.0.

On a successful release the lot's mass is added to the corresponding key of the plant's `resin_store`. When the released lot is `PCR_FILM` and its supplier has an `ACTIVE` collection program, a rebate accrual equal to the lot's `weight_lbs` multiplied by the program's `rebate_per_lb_cents` is added to the program's `accrued_rebate_cents`. Release increments the lot's `version` and the plant's `version` by one. Lots released as `SUPPORT_STOCK` contribute to `resin_store` like any other lot but are barred from runs of capped product lines, per §2.10.

Alternatively, a `QualityEngineer` may reject a quarantined lot, moving it `QUARANTINE → REJECTED`; rejection triggers recomputation of the supplier's `reliability_score_bp` and increments the lot's `version`. `REJECTED` is terminal. `RELEASED` lots have no outgoing API transition — they are consumed by production runs, which decrement the plant's store. Stale quarantine is handled by the capacity review: any lot still `QUARANTINE` whose `received_date` is more than 14 days before the review date auto-transitions to `REJECTED`, with the same supplier reliability recomputation that an explicit rejection performs.

### 3.3. Formulations and Product Lines

A `ProcessEngineer` authors a formulation with a `name` and a set of formulation `lines`, each line pairing a `material` (`VIRGIN_PE`, `REPRO_PE`, `PCR_FILM`, or `WOOD_FLOUR`) with an integer `weight_fraction_bp`. A new formulation starts in `DRAFT`. Activation, performed by a `ProcessEngineer`, requires the weight fractions across all lines to sum to exactly 10000 basis points; an unbalanced formulation is rejected with `ERR_FORMULA_UNBALANCED` (HTTP 422). On activation the formulation stamps `current_revision_hash` — a content hash of the active revision's line set — and sets `active_revision` to 1, moving `DRAFT → ACTIVE`.

An active formulation may be revised in place by submitting a new line set. The new set must again sum to exactly 10000 basis points, and its content hash must differ from every prior revision hash of the same formulation — a duplicate content hash is rejected with `ERR_REVISION_COLLISION` (HTTP 422). A successful revision increments `active_revision` by one, updates `current_revision_hash`, and bumps the formulation's `version`. Production runs already planned keep the revision they pinned at their own creation; revision-in-place never rewrites history. Retirement moves the formulation `ACTIVE → RETIRED` and is blocked while any product line in `ACTIVE` status still references it (`ERR_FORMULATION_IN_USE`, HTTP 409). Discontinued and repair-supported lines keep referencing a retired formulation so that repair support runs remain possible.

A `ProductManager` defines a product line with a `name`, a `color`, a `capped` flag, a `profile` of `GROOVED`, `SQUARE`, or `FASCIA`, an `emboss` of `WOODGRAIN` or `SMOOTH`, a `board_length_ft` of at least 1, a `formulation_id` pinning the recipe, and an optional `repair_support_only` flag defaulting to false. New lines are `ACTIVE`. The lifecycle then runs `ACTIVE → DISCONTINUED → REPAIRED_SUPPORTED → SUNSET`. Discontinuation is blocked while any shipment order in `REQUESTED` or `CONFIRMED` references the line (`ERR_LINE_HAS_OPEN_ORDERS`); open stocking commitments for the line deliberately remain `OPEN` and may still be fulfilled from existing finished goods. Moving a discontinued line into repair support requires the `repair_support_only` flag to be true, either set previously or supplied in the same request; once in `REPAIRED_SUPPORTED`, new production for the line is allowed only with `run_kind` `SUPPORT_STOCK` or `NULL_SLOT`, and sellable runs against it are rejected with `ERR_LINE_SUPPORT_ONLY` (HTTP 409). Sunsetting requires both that no warranty claim in `FILED`, `SAMPLE_REQUESTED`, or `UNDER_REVIEW` references an install registration of the line (`ERR_LINE_HAS_OPEN_CLAIMS`) and that the line's finished-goods balance is zero (`ERR_LINE_STOCK_REMAINS`). A `SUNSET` line forbids all production runs and all orders, rejected with `ERR_LINE_SUNSET`.

### 3.4. Production Scheduling: Slots, Changeovers, and Capacity

An `OpsManager` schedules a production run against a plant by providing the `product_line_id`, the `planned_lf` (at least 1), the `production_date`, and the OCC field `expected_plant_version` described in §2.9. Two optional fields refine the run: `run_kind`, defaulting to `SELLABLE` and alternatively `SUPPORT_STOCK` or `NULL_SLOT`, and `reservation_id`, which ties the run's output to an open allocation commitment. When reservations exist for the product line, a `SELLABLE` run must carry a `reservation_id`; the field is otherwise nullable. `NULL_SLOT` runs carry `line_slot` equal to null and are exempt from the line-status sellability rule described in §3.3; `SUPPORT_STOCK` runs additionally require `repair_support_only` to be true on the product line, while `SELLABLE` runs require the line to be `ACTIVE`. Sellability violations surface as `ERR_LINE_SUPPORT_ONLY` or `ERR_LINE_SUNSET`.

Scheduling assigns the run a `line_slot`: the lowest free extrusion-line index for that plant and production date, where line indices are 1-based — the lowest free index in the range 1 through the plant's `lines`. The slot is unique per plant per `production_date`. At creation the run pins `formulation_revision` from the formulation's current `active_revision` — immutable thereafter — records the `plant_id` from the addressed plant, computes its `changeover_minutes` penalty, and increments the plant's `version`.

The `changeover_minutes` penalty compares the run against the previous run on the same line slot — for a `NULL_SLOT` run, which holds no slot, against the previous run across the whole plant regardless of slot —: the run in `PLANNED`, `RUNNING`, or `COMPLETED` status with the greatest `production_date` strictly before this run's `production_date`, with ties broken by the later `created_at`. With no predecessor, the changeover is 60 minutes of initial setup. With a predecessor, the changeover starts at a 15-minute base and accrues additive penalties for each physical difference between the two runs' product lines: 45 minutes when the `color` differs, 60 minutes when the `profile` differs, 30 minutes when the `emboss` differs, and 25 minutes when the `capped` flag differs. The run's working time, `total_minutes`, is the sum of this changeover and the run's own run-minutes, where run-minutes is the planned footage divided by the per-line daily capacity (the plant's `daily_capacity_lf` divided by its `lines`), scaled to a full day of 24 hours times 60 minutes, and rounded up to the next whole minute, computed in exact integer arithmetic so that an exact quotient is never inflated by binary floating-point representation. A production date is feasible only when the sum of `total_minutes` across all of that date's runs, over all slots, does not exceed the plant's `lines` multiplied by 1440 minutes; a schedule that would breach this is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409).

A scheduled run begins `PLANNED` and may be cancelled from `PLANNED` with no inventory consequence — the reservation, if any, is untouched and the slot is freed.

### 3.5. Run Execution: Start, Draw, and Completion

Starting a run — transitioning `PLANNED → RUNNING` — is guarded by four checks. The run's `production_date` must equal the logical clock date (`ERR_RUN_NOT_TODAY`). No other run on the same plant may be `RUNNING` on the same `line_slot` on the same `production_date` (`ERR_LINE_OCCUPIED`). The plant's `resin_store` must hold sufficient mass for the recipe draw (`ERR_RESIN_SHORTFALL`, HTTP 409). And the support-stock segregation rule of §2.10 must hold for capped lines (`ERR_SUPPORT_STOCK_BARRED`).

The recipe draw converts footage to mass uniformly across product lines at 2.0 pounds per linear foot, rounded up to the next whole pound: the run's total mass is the ceiling of `planned_lf` multiplied by 2.0. Each formulation line other than `WOOD_FLOUR` draws its `weight_fraction_bp` share of that total, truncated down to a whole pound per material; `WOOD_FLOUR` absorbs the remainder, so the wood draw equals the total mass minus the sum of the other draws. Starting the run decrements each material's draw from `resin_store`. If any material's on-hand balance is below its draw, the start is rejected with `ERR_RESIN_SHORTFALL`.

Completing a run — transitioning `RUNNING → COMPLETED` — requires the `actual_lf` produced, which must be at least 1 and at most 110 percent of `planned_lf`; an overage beyond that ceiling is rejected with `ERR_OVERAGE_LIMIT` (HTTP 409). Completion creates exactly one board lot with `lf` equal to `actual_lf`, `produced_at` stamped with the completion datetime, and `support_tagged` true whenever the run's `run_kind` is anything other than `SELLABLE`; the lot's id is recorded on the run as `board_lot_id`, and the lot carries the run's `product_line_id`, pinned `formulation_revision`, and `plant_id`. A new lot's `disposition` is `AVAILABLE`; the full disposition lifecycle runs `AVAILABLE → ALLOCATED → SHIPPED`, with `CONSUMED_BY_CLAIM` and `SCRAPPED` as the claim-consumption and scrap terminals. For `SELLABLE` runs the actual footage is added to the plant's `fg_store` under the product line, and when the run carried a `reservation_id` the plant's `reserved_fg_store` for that line is reduced by the consumed share — the lesser of `actual_lf` and the reservation's remaining reserved balance — and the reservation is re-evaluated, transitioning `OPEN → CONSUMED` when fully drawn, at which point its remaining share is removed from the reserved ledger. Lots from `SUPPORT_STOCK` and `NULL_SLOT` runs never enter `fg_store`; support stock is tracked only on the lot itself. Completion increments both the run's and the plant's `version`. Cancelling a `RUNNING` run scraps the resin already drawn at start — it is not returned — and creates no board lot.

### 3.6. Dealers, Price Books, and the Shipment Order Pipeline

A `ChannelManager` registers a dealer with a `name`, a `territory_code` identifying the geographic territory the dealer covers, and a non-negative `credit_limit_cents`. Dealers begin `ACTIVE` with `outstanding_cents` of zero; the outstanding balance is recomputed at invoicing and at claim credit issuance as the sum of `invoiced_cents` across the dealer's shipment orders that have been invoiced, minus credited amounts.

Pricing is governed by price books, published by a `ChannelManager` with a `name`, an `effective_from` date, a `base_prices` map of integer cents per linear foot keyed by product line id, and a `tier_discounts_bp` map of basis-point discounts keyed by dealer tier with keys `STANDARD` and `PREFERRED`. Exactly one price book is active per date: the one with the latest `effective_from` on or before that date. Publishing a new book supersedes the previously active book — any earlier book becomes `SUPERSEDED` once the new book's `effective_from` is reached.

A `Dealer` or a `DealerSalesRep` places a ship-later order with the `dealer_id`, `product_line_id`, the ordered footage `lf` (at least 1), and `ship_week_start`, the ISO date of the Monday of the requested ship week. The product line must be `ACTIVE` (`ERR_LINE_SUPPORT_ONLY` / `ERR_LINE_SUNSET` otherwise). New orders are `REQUESTED`.

Confirmation, performed by a `DealerSalesRep`, runs three gates in this order. First, the dealer must be `ACTIVE` (`ERR_DEALER_SUSPENDED`, HTTP 409). Second, credit headroom: the dealer's `outstanding_cents` plus the projected invoice for this order must be strictly less than `credit_limit_cents` — equality with the limit is a rejection, not an acceptance — with breaches reported as `ERR_CREDIT_LIMIT` (HTTP 409). The projection uses the provisional invoicing variant: it is computed exactly like the final invoice described below but is never persisted, because the dealer's tier can change between confirmation and shipment. Third, finished-goods availability: the line's `fg_store` minus the sum of footage over confirmed-but-unshipped orders for that line must be at least the order's `lf`; the boundary is inclusive, so a net position exactly equal to the order size is confirmable, and anything short is rejected with `ERR_FG_SHORTFALL` (HTTP 409). On confirmation the order pins its `price_book_id`: when an open allocation commitment exists for the dealer and product line, the commitment's price book is pinned; otherwise the price book active on the confirm date is pinned.

Shipping, performed by a `DealerSalesRep`, requires the logical clock date to fall within the confirmed ship week — the seven days from `ship_week_start` through six days after it, inclusive — and otherwise fails with `ERR_OUTSIDE_SHIP_WEEK` (HTTP 409). Shipping decrements the line's `fg_store` by the order footage, computes the final invoice, and consumes board lots for the line in first-in-first-out order — oldest `produced_at` first, with `created_at` as the tie-break — moving each consumed lot from `AVAILABLE` to `SHIPPED`. The final invoice is computed from the pinned price book: the base amount is the order footage multiplied by the book's base price per linear foot for the line. The dealer's tier is `PREFERRED` when the dealer has at least one stocking commitment that closed `MET` with a `season_year` equal to the year of the ship date minus one, and `STANDARD` otherwise. The invoice equals the base amount multiplied by the complement of the tier's discount in basis points — that is, ten thousand minus the discount, over ten thousand — truncated down to whole cents. The result is persisted to `invoiced_cents`, the `actual_ship_date` is stamped, and the amount is added to the dealer's `outstanding_cents`. Because tier derives from prior-season performance, a commitment closing `MET` between confirmation and shipment legitimately makes the provisional and final figures disagree for identical order data.

Delivery, performed by the `Dealer` whose `X-User-ID` equals the order's `dealer_id`, advances the matching open stocking commitment — the one for the same dealer, product line, and the season year of the ship date — by adding the order's footage to `fulfilled_lf`; when `fulfilled_lf` reaches or exceeds `committed_lf` the commitment transitions `OPEN → MET`. A confirmed order may instead be cancelled by a `DealerSalesRep`; cancellation moves no inventory, because nothing was decremented at confirmation.

### 3.7. Stocking Commitments, Season Close, and Pre-Season Reservations

A `ChannelManager` creates a stocking commitment with the `dealer_id`, a `territory_code` that must equal the dealer's own `territory_code` at creation, a `product_line_id`, the `committed_lf` (at least 1), and the `season_year`. At most one open stocking commitment may exist per dealer-and-territory pair; a second open commitment for the same pair is rejected with `ERR_DUPLICATE_COMMITMENT` (HTTP 409). Commitments track `fulfilled_lf`, starting at zero and advanced at delivery as described in §3.6.

After the season ends, a `ChannelManager` closes a commitment. Closing is only possible once the logical clock date is after December 31 of the `season_year` — the earliest close date is January 1 of the following year. Closing with `waive` set true moves the commitment `OPEN → WAIVED` with no financial consequence. Closing without a waiver, when delivered footage fell short of the commitment, moves it `OPEN → SHORTFALL_PENALIZED` and debits a penalty to the dealer's `outstanding_cents`. The penalty is banded by fill rate, where the fill rate in basis points is the delivered footage over the committed footage expressed in ten-thousandths, truncated down: a fill rate of at least 9000 basis points lands in the grace band and incurs a zero-cent penalty — the status is still `SHORTFALL_PENALIZED`, and the 9000-point boundary itself belongs to the grace band; a fill rate of at least 7000 but below 9000 basis points incurs 50 cents per unfulfilled linear foot; a fill rate below 7000 basis points incurs 150 cents per unfulfilled linear foot.

Ahead of the season, a `DealerSalesRep` reserves finished goods for a dealer by creating an allocation commitment against a plant, supplying the `dealer_id`, `product_line_id`, `reserved_lf` (at least 1), a `price_book_id` that later confirmed orders will pin, and the OCC field `expected_plant_version` from §2.9. Creation adds `reserved_lf` to the plant's `reserved_fg_store` for the line and increments the plant's `version`. A reservation is `OPEN` until it is consumed by production and order activity, explicitly released by a `DealerSalesRep` (`OPEN → RELEASED`, which subtracts the remaining reserved footage from the reserved ledger), or swept to `EXPIRED` by the capacity review when it has been open for more than 90 days — expiry likewise releases its remaining contribution to `reserved_fg_store`.

### 3.8. Contractor Onboarding, Training, and Certification

A `ProgramAdmin` admits a contractor to the certification program with a `name` and a unique `email`; the applicant starts `APPLIED`. The first training enrolment — by the contractor or a `ProgramAdmin`, supplying `contractor_id` and `module_id` — moves the contractor `APPLIED → IN_TRAINING` and creates a training record in `ENROLLED`. A `ProgramAdmin` then records the outcome: passing requires the module to be `ACTIVE` (a pass attempt on a retired module is rejected with `ERR_MODULE_RETIRED`) and stamps the record's `passed_module_version` with the module's `version_no` at the moment of passing along with `passed_at`; failing simply closes the record as `FAILED`.

Training modules are created by a `ProgramAdmin` with a `title`, an integer `version_no` of at least 1, a `duration_hours` greater than zero, and the `required_for_tier` they gate — `SILVER`, `GOLD`, or `PLATINUM`. Modules are `ACTIVE` until retired; retirement makes the module no longer required for certification and blocks further pass records. Re-versioning a module increments its `version_no` (the request carries the updated `duration_hours`) and invalidates passes recorded against older versions for certification purposes.

Certification moves a contractor `IN_TRAINING → CERTIFIED` and enforces two gates. First, the contractor's training records must show `PASSED` for every active training module whose `required_for_tier` is `SILVER` that the certifying contractor has a training record for — only modules this contractor enrolled in gate certification, so modules created later or enrolled in only by other contractors never block it; a missing pass is rejected with `ERR_MODULES_INCOMPLETE` (HTTP 409). Second, when any module was re-versioned after the contractor passed it, at least one pass must have been recorded against the module's current `version_no`; stale passes are rejected with `ERR_STALE_TRAINING` (HTTP 409), so re-versioned modules must be re-passed. On certification the contractor's `certified_at` is stamped and the `tier` is computed from trailing-twelve-month activity against the logical clock: the score is the contractor's `completed_project_count` multiplied by 100 plus the `enhanced_warranty_count` multiplied by 250. A score of at least 3000 earns `PLATINUM`, a score of at least 1000 earns `GOLD`, and anything below earns `SILVER`; the boundaries are inclusive, so a score of exactly 3000 is `PLATINUM` and exactly 1000 is `GOLD`. The tier carries warranty weight: `SILVER` grants ten warranty years, `GOLD` grants fifteen, and `PLATINUM` grants twenty-five.

A `ProgramAdmin` may suspend a certified contractor (`CERTIFIED → SUSPENDED`), which makes the contractor ineligible for new lead assignment and for enhanced warranty activation, and may later reinstate (`SUSPENDED → CERTIFIED`), which recomputes the tier. The capacity review lapses idle contractors automatically: a certified contractor whose `certified_at` is more than 24 months before the review date and whose `completed_project_count` is zero transitions to `LAPSED`, and a contractor suspended for more than 24 months also transitions to `LAPSED`, which is terminal.

### 3.9. Lead Referrals and Install Registrations

A homeowner lead is submitted by a `Dealer` — whose `X-User-ID` must equal the `submitted_by_dealer_id` — or by a `ProgramAdmin`, carrying the `homeowner_name`, `zip_code`, and `submitted_by_dealer_id`. A new lead is `OPEN`. Assignment, performed by a `ProgramAdmin`, runs the lead selector: the candidate pool is all contractors in `CERTIFIED` status, ranked first by tier (`PLATINUM` above `GOLD` above `SILVER`), then by fewest currently-`ASSIGNED` leads in the trailing 90 days, then by earliest `certified_at`, and finally by earliest contractor `created_at`. The winner is recorded as `assigned_contractor_id` and the lead moves `OPEN → ASSIGNED`; an empty pool is rejected with `ERR_NO_ELIGIBLE_CONTRACTOR` (HTTP 409). The assignee — and only the assignee — may decline the lead (`ASSIGNED → DECLINED`), after which a `ProgramAdmin` may reassign it (`DECLINED → ASSIGNED`) with the declining contractor excluded from the candidate pool. A lead that sits `ASSIGNED` for more than 30 days is expired by the capacity review (`ASSIGNED → EXPIRED`).

After a job, a contractor registers the installation with the `contractor_id`, the selling `dealer_id`, the installed `product_line_id`, the `install_date`, and the `board_lot_id` of the lot that produced the installed boards. The registration starts `PENDING` with `registered_at` stamped from the logical clock. Creation also accepts an optional `registered_date` (an ISO calendar date) recording the business date of the registration; when supplied, it — rather than the `registered_at` date — is the registration date used by the 60-day enhanced-warranty window check described below. Marking the project installed (`PENDING → INSTALLED`) is an owner-only action — `X-User-ID` must equal the registration's `contractor_id`, otherwise `ERR_NOT_OWNER` — and stamps `completion_date` and recomputes the contractor's `completed_project_count`, which counts registrations marked `INSTALLED` whose `completion_date` falls inside the trailing 12 months. A pending registration may instead be cancelled by its owner (`PENDING → CANCELLED`).

Activating the enhanced warranty on an installed registration enforces three checks: the contractor must be `CERTIFIED` (`ERR_CONTRACTOR_NOT_CERTIFIED`, HTTP 409); the registration's registration date — its `registered_date` when one was supplied at creation, otherwise the `registered_at` date — must fall within 60 days of the `install_date` (`ERR_REGISTRATION_WINDOW`, HTTP 409); and the `enhanced_warranty` flag must still be false — a repeat activation is rejected with `ERR_ALREADY_ENHANCED` (HTTP 409). Activation sets `enhanced_warranty` true, fixes `warranty_years` from the contractor's tier — 25 for `PLATINUM`, 15 for `GOLD`, 10 for `SILVER` — and recomputes the contractor's `enhanced_warranty_count`, which counts registrations of that contractor whose enhanced warranty was activated within the trailing 12 months. Without activation a registration carries a five-year baseline warranty.

### 3.10. Warranty Claims, Samples, and Adjudication

A `Contractor` or a `ClaimsAdjuster` files a warranty claim against an install registration with the `install_registration_id` and a `category` of `FADING`, `STAINING`, or `STRUCTURAL`; the claim starts `FILED` with `filed_at` stamped from the logical clock. Creation also accepts an optional `filed_date` (an ISO calendar date) recording the business date on which the claim was filed; everywhere this section refers to the claim's `filed_at` date — in the warranty-window and category-specific gates of the sample request and in the credit proration of adjudication — the claim's `filed_date` is used instead when one was supplied.

A `ClaimsAdjuster` moves a claim `FILED → SAMPLE_REQUESTED` by requesting a physical board sample, which creates a claim sample in `AWAITING`. The request passes through two eligibility gates. The warranty-window gate: the number of whole days between the registration's `install_date` and the claim's `filed_at` must not exceed the registration's `warranty_years` multiplied by 365, otherwise `ERR_CLAIM_OUT_OF_WARRANTY` (HTTP 409). Category-specific gates: for `FADING` claims, when the installed boards were produced on a legacy formulation revision — the lot's pinned `formulation_revision` is older than the formulation's current `active_revision` — the claim must be at least 180 days old, measured from install, before a sample may be requested, otherwise `ERR_FADE_COOLDOWN` (HTTP 409); for `STAINING` claims, coverage is capped at 5 years from install regardless of the `warranty_years` on the registration, so an install older than five years is out of warranty for staining.

Sample logistics are handled on the sample itself: a `ClaimsAdjuster` logs receipt (`AWAITING → RECEIVED`, stamping `received_at`), then records the lab verdict (`RECEIVED → REVIEWED`) by supplying a `lab_verdict` of `CONFIRMS_DEFECT`, `CONTRADICTS_CLAIM`, or `INCONCLUSIVE`. Recording the verdict moves the parent claim `SAMPLE_REQUESTED → UNDER_REVIEW`.

Adjudication is the terminal step, moving the claim `UNDER_REVIEW → APPROVED` or `UNDER_REVIEW → DENIED`. Denial records the `denial_reason` and closes the claim. Approval requires the lab verdict to be `CONFIRMS_DEFECT` — any other verdict blocks approval with `ERR_VERDICT_BLOCKS_APPROVAL` (HTTP 409) — and takes an `adjudication` of `REPLACEMENT`, `CREDIT`, or `REPAIR` via the adjudication `decision`. Approval with `CREDIT` computes `credit_amount_cents` as a linear proration over remaining whole warranty years: the elapsed time from `install_date` to the claim's `filed_at` date, converted to whole years by dividing by 365 and truncating, is subtracted from the registration's `warranty_years` to give the remaining years (floored at zero); the original value is the `invoiced_cents` of the shipped order whose board-lot lineage contains the registration's `board_lot_id` — matching on the exact lot, and if the lot shipped on multiple orders, using the order with the earliest `actual_ship_date` (tie-broken by `created_at`). With zero remaining years the credit is zero — the claim may still be approved as `REPAIR` — and otherwise the credit is the original value multiplied by the ratio of remaining years to total warranty years, with a single truncation to whole cents applied once at the very end; the ratio itself is never pre-rounded. The credit is debited against the selling dealer's `outstanding_cents`. Approval with `REPLACEMENT` consumes support stock: the `AVAILABLE` support-tagged board lot of the claim's product line with the earliest `produced_at` (tie-break `created_at`) moves to `CONSUMED_BY_CLAIM`, and when no such lot exists the approval is rejected with `ERR_NO_SUPPORT_STOCK` (HTTP 409) until a `SUPPORT_STOCK` production run has been scheduled and completed.

### 3.11. Merchandising: Sample Kits and Color Chips

A `DealerSalesRep` orders a merchandising sample kit for a dealer with the `dealer_id`, the showcased `product_line_id`, and a `kit_type` of `DISPLAY_BOARD` or `CHIP_SET`. Kits move `ORDERED → DELIVERED → RETIRED`; retirement is allowed only when the kit's product line is `DISCONTINUED` or later in its lifecycle, or when a newer kit supersedes this one for the same line — otherwise the retirement is rejected with `ERR_KIT_STILL_CURRENT` (HTTP 409).

Color chip requests are raised by a `Dealer` or `DealerSalesRep` with the `dealer_id`, `product_line_id`, and a `quantity` of at least 1. Fulfilment, performed by an `OpsManager`, draws on support stock: a completed `SUPPORT_STOCK` production run for the request's product line must exist with `actual_lf` of at least two linear feet per chip requested — each chip consumes 2 linear feet — otherwise the fulfilment is rejected with `ERR_CHIP_STOCK_SHORT` (HTTP 409). On fulfilment (`REQUESTED → FULFILLED`) the producing run is recorded as the request's `chip_run_id` and the support lot is decremented; a request may instead be cancelled by a `DealerSalesRep` (`REQUESTED → CANCELLED`).

### 3.12. The Capacity Review in Detail

The plant capacity review, introduced in §2.7, is the single checkpoint where time-dependent bookkeeping catches up with the logical clock. Each review performs, against the addressed plant:

1. **Posture recompute.** `season_posture` is re-derived from the clock date against the pre-season window, per §2.11.
2. **Recycled-film decay.** The `PCR_FILM` balance in `resin_store` decays at half a percent per elapsed calendar day since the previous review — or since plant creation for the first review. The decay is applied day by day in chronological order, truncating each day's result down to a whole pound before the next day is computed; equivalently, each day retains 99.5 percent of the prior day's balance, floored daily rather than once on the compounded total. The daily iteration starts from the balance held at the anchor — for the first review, the live balance at plant creation, so mass released before the first review decays over the full elapsed span — and mass released since the anchor is then added to the decayed result undecayed; the anchor then advances to this review.
3. **Stale quarantine sweep.** Feedstock lots still `QUARANTINE` whose `received_date` is more than 14 days before the review date auto-transition to `REJECTED`, with supplier reliability recomputed per §3.2.
4. **Reservation expiry.** Allocation commitments still `OPEN` whose creation date is more than 90 days before the review date transition to `EXPIRED`, releasing their remaining `reserved_fg_store` contribution.
5. **Lead expiry.** Lead referrals `ASSIGNED` for more than 30 days transition to `EXPIRED`.
6. **Contractor lapse.** Certified contractors idle for more than 24 months with zero completed projects, and contractors suspended for more than 24 months, transition to `LAPSED`, per §3.8.

The review returns the updated plant and increments its `version` by one.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code. All endpoints are mounted under `/decking`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/decking/_clock/set_current_utc` | Set the logical clock (test-driving) | OpsManager |
| POST | `/decking/plants` | Create a plant | OpsManager |
| GET | `/decking/plants/{id}` | Get a plant | OpsManager, QualityEngineer, ProcessEngineer, ProductManager, DealerSalesRep, ChannelManager, ClaimsAdjuster, ProgramAdmin |
| POST | `/decking/plants/{id}/run-capacity-review` | Run the plant ops checkpoint | OpsManager |
| POST | `/decking/suppliers` | Register a supplier | QualityEngineer |
| GET | `/decking/suppliers/{id}` | Get a supplier | QualityEngineer, OpsManager, ChannelManager |
| GET | `/decking/suppliers/{id}/collection-programs` | List a supplier's collection programs | QualityEngineer, ChannelManager |
| GET | `/decking/suppliers/{id}/feedstock-lots` | List a supplier's feedstock lots | QualityEngineer, OpsManager |
| POST | `/decking/collection-programs` | Create a collection program (starts ACTIVE) | ChannelManager |
| GET | `/decking/collection-programs/{id}` | Get a collection program (includes accrued rebate) | ChannelManager, QualityEngineer |
| POST | `/decking/collection-programs/{id}/suspend` | Suspend a collection program | ChannelManager |
| POST | `/decking/collection-programs/{id}/reactivate` | Reactivate a suspended program | ChannelManager |
| POST | `/decking/collection-programs/{id}/terminate` | Terminate a program | ChannelManager |
| POST | `/decking/feedstock-lots` | Register an inbound feedstock lot (enters QUARANTINE) | QualityEngineer |
| GET | `/decking/feedstock-lots/{id}` | Get a feedstock lot | QualityEngineer, OpsManager |
| POST | `/decking/feedstock-lots/{id}/release` | Release a quarantined lot to production or support stock | QualityEngineer |
| POST | `/decking/feedstock-lots/{id}/reject` | Reject a quarantined lot | QualityEngineer |
| POST | `/decking/formulations` | Create a formulation (DRAFT) | ProcessEngineer |
| GET | `/decking/formulations/{id}` | Get a formulation | ProcessEngineer, OpsManager, ProductManager |
| POST | `/decking/formulations/{id}/activate` | Activate a formulation | ProcessEngineer |
| POST | `/decking/formulations/{id}/revisions` | Revise an ACTIVE formulation in place | ProcessEngineer |
| POST | `/decking/formulations/{id}/retire` | Retire a formulation | ProcessEngineer |
| GET | `/decking/formulations/{id}/product-lines` | List product lines using this formulation | ProcessEngineer, ProductManager |
| POST | `/decking/product-lines` | Create a product line (ACTIVE) | ProductManager |
| GET | `/decking/product-lines/{id}` | Get a product line | ProductManager, OpsManager, DealerSalesRep, ChannelManager, ClaimsAdjuster |
| POST | `/decking/product-lines/{id}/discontinue` | Discontinue a color/line | ProductManager |
| POST | `/decking/product-lines/{id}/set-repair-support` | Move a discontinued line into repair support | ProductManager |
| POST | `/decking/product-lines/{id}/sunset` | Sunset a repair-supported line | ProductManager |
| POST | `/decking/plants/{id}/production-runs` | Schedule a production run (assigns line slot, computes changeover) | OpsManager |
| GET | `/decking/plants/{id}/production-runs/{runId}` | Get a production run | OpsManager, ProcessEngineer, QualityEngineer |
| GET | `/decking/plants/{id}/production-runs` | List runs of a plant (optional `production_date`, `status` filters) | OpsManager, ProcessEngineer |
| POST | `/decking/plants/{id}/production-runs/{runId}/start` | Start a run (consumes resin) | OpsManager |
| POST | `/decking/plants/{id}/production-runs/{runId}/complete` | Complete a run (creates board lot, updates finished goods) | OpsManager |
| POST | `/decking/plants/{id}/production-runs/{runId}/cancel` | Cancel a planned or running run | OpsManager |
| GET | `/decking/production-runs/{runId}/board-lots` | List board lots produced by a run | OpsManager, QualityEngineer, ClaimsAdjuster |
| GET | `/decking/production-runs/{id}` | Get a production run by id (top-level alias) | OpsManager, ProcessEngineer, QualityEngineer |
| GET | `/decking/production-runs` | List production runs (optional `product_line_id`, `reservation_id`, `status` filters) | OpsManager, ProcessEngineer, QualityEngineer |
| GET | `/decking/board-lots/{id}` | Get a board lot | OpsManager, QualityEngineer, ClaimsAdjuster |
| GET | `/decking/board-lots` | List board lots (optional `product_line_id`, `disposition`, `support_tagged`, `production_run_id` filters) | OpsManager, ClaimsAdjuster |
| GET | `/decking/plants/{id}/board-lots` | List a plant's board lots (optional `disposition`, `support_tagged` filters) | OpsManager, QualityEngineer, ClaimsAdjuster |
| POST | `/decking/dealers` | Register a dealer | ChannelManager |
| GET | `/decking/dealers/{id}` | Get a dealer | ChannelManager, DealerSalesRep, Dealer, ClaimsAdjuster |
| GET | `/decking/dealers/{id}/shipment-orders` | List a dealer's orders (optional `status` filter) | DealerSalesRep, Dealer, ChannelManager |
| GET | `/decking/dealers/{id}/stocking-commitments` | List a dealer's stocking commitments (optional `status` filter) | DealerSalesRep, Dealer, ChannelManager |
| POST | `/decking/shipment-orders` | Place a ship-later order | Dealer, DealerSalesRep |
| GET | `/decking/shipment-orders/{id}` | Get an order | DealerSalesRep, Dealer, ChannelManager, ClaimsAdjuster |
| GET | `/decking/shipment-orders` | List shipment orders (optional `product_line_id`, `price_book_id`, `dealer_id`, `status` filters) | DealerSalesRep, Dealer, ChannelManager |
| POST | `/decking/shipment-orders/{id}/confirm` | Confirm an order (credit and finished-goods checks; pins price book) | DealerSalesRep |
| POST | `/decking/shipment-orders/{id}/ship` | Ship a confirmed order (final invoicing) | DealerSalesRep |
| POST | `/decking/shipment-orders/{id}/deliver` | Mark delivered; advances stocking commitment fulfilment | Dealer |
| POST | `/decking/shipment-orders/{id}/cancel` | Cancel a confirmed order | DealerSalesRep |
| POST | `/decking/stocking-commitments` | Create a stocking commitment | ChannelManager |
| GET | `/decking/stocking-commitments/{id}` | Get a stocking commitment | ChannelManager, DealerSalesRep, Dealer |
| GET | `/decking/stocking-commitments` | List stocking commitments (optional `product_line_id`, `dealer_id`, `status` filters) | ChannelManager, DealerSalesRep, Dealer |
| POST | `/decking/stocking-commitments/{id}/close-season` | Close a commitment post-season (penalty or waive) | ChannelManager |
| POST | `/decking/plants/{id}/allocation-commitments` | Reserve finished goods for a dealer (pre-season allocation) | DealerSalesRep |
| GET | `/decking/allocation-commitments/{id}` | Get an allocation commitment | DealerSalesRep, ChannelManager, OpsManager |
| GET | `/decking/plants/{id}/allocation-commitments` | List a plant's allocation commitments (optional `status` filter) | DealerSalesRep, ChannelManager, OpsManager |
| GET | `/decking/allocation-commitments` | List allocation commitments (optional `dealer_id`, `product_line_id`, `price_book_id`, `status` filters) | DealerSalesRep, ChannelManager, OpsManager |
| POST | `/decking/allocation-commitments/{id}/release` | Release a reservation | DealerSalesRep |
| POST | `/decking/contractors` | Apply to the contractor program | ProgramAdmin |
| GET | `/decking/contractors/{id}` | Get a contractor | ProgramAdmin, Contractor, ClaimsAdjuster |
| POST | `/decking/contractors/{id}/certify` | Certify a trained contractor | ProgramAdmin |
| POST | `/decking/contractors/{id}/suspend` | Suspend a contractor | ProgramAdmin |
| POST | `/decking/contractors/{id}/reinstate` | Reinstate a suspended contractor | ProgramAdmin |
| GET | `/decking/contractors/{id}/training-records` | List a contractor's training records | ProgramAdmin, Contractor |
| GET | `/decking/contractors/{id}/install-registrations` | List a contractor's registrations | ProgramAdmin, Contractor, ClaimsAdjuster |
| POST | `/decking/training-modules` | Create a training module | ProgramAdmin |
| GET | `/decking/training-modules/{id}` | Get a module | ProgramAdmin, Contractor |
| POST | `/decking/training-modules/{id}/re-version` | Publish a new version of a module | ProgramAdmin |
| POST | `/decking/training-modules/{id}/retire` | Retire a module | ProgramAdmin |
| POST | `/decking/training-records` | Enrol a contractor in a module | Contractor, ProgramAdmin |
| GET | `/decking/training-records/{id}` | Get a training record | ProgramAdmin, Contractor |
| GET | `/decking/training-records` | List training records (optional `contractor_id`, `module_id`, `status` filters) | ProgramAdmin, Contractor |
| POST | `/decking/training-records/{id}/pass` | Record a pass | ProgramAdmin |
| POST | `/decking/training-records/{id}/fail` | Record a fail | ProgramAdmin |
| POST | `/decking/lead-referrals` | Submit a homeowner lead | Dealer, ProgramAdmin |
| GET | `/decking/lead-referrals/{id}` | Get a lead | ProgramAdmin, Dealer, Contractor |
| GET | `/decking/lead-referrals` | List lead referrals (optional `submitted_by_dealer_id`, `assigned_contractor_id`, `status` filters) | ProgramAdmin, Dealer, Contractor |
| POST | `/decking/lead-referrals/{id}/assign` | Assign (or reassign) a lead via the selector | ProgramAdmin |
| POST | `/decking/lead-referrals/{id}/decline` | Assignee declines the lead | Contractor |
| POST | `/decking/install-registrations` | Register an installation | Contractor |
| GET | `/decking/install-registrations/{id}` | Get a registration | Contractor, ProgramAdmin, ClaimsAdjuster, Dealer |
| GET | `/decking/install-registrations` | List install registrations (optional `dealer_id`, `product_line_id`, `board_lot_id`, `contractor_id` filters) | Contractor, ProgramAdmin, ClaimsAdjuster |
| POST | `/decking/install-registrations/{id}/mark-installed` | Mark the project installed | Contractor |
| POST | `/decking/install-registrations/{id}/activate-warranty` | Activate the enhanced warranty | Contractor |
| POST | `/decking/install-registrations/{id}/cancel` | Cancel a pending registration | Contractor |
| GET | `/decking/install-registrations/{id}/warranty-claims` | List claims on a registration | ClaimsAdjuster, Contractor |
| POST | `/decking/warranty-claims` | File a warranty claim | Contractor, ClaimsAdjuster |
| GET | `/decking/warranty-claims/{id}` | Get a claim | ClaimsAdjuster, Contractor, ProgramAdmin |
| POST | `/decking/warranty-claims/{id}/request-sample` | Request a physical board sample | ClaimsAdjuster |
| POST | `/decking/warranty-claims/{id}/adjudicate` | Adjudicate a claim (approve with adjudication, or deny) | ClaimsAdjuster |
| GET | `/decking/warranty-claims/{id}/samples` | List samples on a claim | ClaimsAdjuster |
| GET | `/decking/claim-samples/{id}` | Get a claim sample | ClaimsAdjuster |
| POST | `/decking/claim-samples/{id}/receive` | Log sample receipt | ClaimsAdjuster |
| POST | `/decking/claim-samples/{id}/review` | Record lab verdict; moves claim to UNDER_REVIEW | ClaimsAdjuster |
| POST | `/decking/sample-kits` | Order a merchandising sample kit | DealerSalesRep |
| GET | `/decking/sample-kits/{id}` | Get a sample kit | DealerSalesRep, ChannelManager |
| GET | `/decking/sample-kits` | List sample kits (optional `product_line_id`, `dealer_id`, `status` filters) | DealerSalesRep, ChannelManager, Dealer |
| GET | `/decking/dealers/{id}/sample-kits` | List a dealer's sample kits | DealerSalesRep, ChannelManager, Dealer |
| POST | `/decking/sample-kits/{id}/deliver` | Mark a kit delivered | DealerSalesRep |
| POST | `/decking/sample-kits/{id}/retire` | Retire a kit | DealerSalesRep |
| POST | `/decking/color-chip-requests` | Request color chips | Dealer, DealerSalesRep |
| GET | `/decking/color-chip-requests/{id}` | Get a chip request | Dealer, DealerSalesRep, OpsManager |
| GET | `/decking/color-chip-requests` | List chip requests (optional `product_line_id`, `dealer_id`, `chip_run_id`, `status` filters) | Dealer, DealerSalesRep, OpsManager |
| GET | `/decking/dealers/{id}/color-chip-requests` | List a dealer's chip requests | Dealer, DealerSalesRep |
| POST | `/decking/color-chip-requests/{id}/fulfill` | Fulfil chips from support stock | OpsManager |
| POST | `/decking/color-chip-requests/{id}/cancel` | Cancel a chip request | DealerSalesRep |
| POST | `/decking/price-books` | Publish a price book | ChannelManager |
| GET | `/decking/price-books/{id}` | Get a price book | ChannelManager, DealerSalesRep, Dealer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LOT_LIMIT_EXCEEDED` | 422 |
| `ERR_SUPPORT_STOCK_BARRED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_LINE_OCCUPIED` | 409 |
| `ERR_RESIN_SHORTFALL` | 409 |
| `ERR_FORMULA_UNBALANCED` | 422 |
| `ERR_REVISION_COLLISION` | 422 |
| `ERR_FORMULATION_IN_USE` | 409 |
| `ERR_LINE_HAS_OPEN_ORDERS` | 409 |
| `ERR_LINE_HAS_OPEN_CLAIMS` | 409 |
| `ERR_LINE_STOCK_REMAINS` | 409 |
| `ERR_LINE_SUPPORT_ONLY` | 409 |
| `ERR_LINE_SUNSET` | 409 |
| `ERR_DEALER_SUSPENDED` | 409 |
| `ERR_CREDIT_LIMIT` | 409 |
| `ERR_FG_SHORTFALL` | 409 |
| `ERR_OUTSIDE_SHIP_WEEK` | 409 |
| `ERR_RUN_NOT_TODAY` | 409 |
| `ERR_OVERAGE_LIMIT` | 409 |
| `ERR_MODULES_INCOMPLETE` | 409 |
| `ERR_STALE_TRAINING` | 409 |
| `ERR_MODULE_RETIRED` | 409 |
| `ERR_CONTRACTOR_NOT_CERTIFIED` | 409 |
| `ERR_REGISTRATION_WINDOW` | 409 |
| `ERR_ALREADY_ENHANCED` | 409 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_ASSIGNEE` | 403 |
| `ERR_NO_ELIGIBLE_CONTRACTOR` | 409 |
| `ERR_CLAIM_OUT_OF_WARRANTY` | 409 |
| `ERR_FADE_COOLDOWN` | 409 |
| `ERR_VERDICT_BLOCKS_APPROVAL` | 409 |
| `ERR_NO_SUPPORT_STOCK` | 409 |
| `ERR_KIT_STILL_CURRENT` | 409 |
| `ERR_CHIP_STOCK_SHORT` | 409 |
| `ERR_DUPLICATE_COMMITMENT` | 409 |
