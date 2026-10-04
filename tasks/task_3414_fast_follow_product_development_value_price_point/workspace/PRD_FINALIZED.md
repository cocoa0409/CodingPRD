# Fast-Follow Beauty API — Product Requirements Document

## 1. Introduction

Trend-driven beauty retail lives and dies by speed: a look that catches fire on social platforms or in a prestige launch has a commercial half-life measured in weeks, and the value segment wins by shipping a credible fast-follow before the moment passes. This document specifies the API for a Fast-Follow Product Development & Value Price Point Sourcing platform — the system of record that carries a spotted trend through concept selection, compressed formula development with contract manufacturers, ingredient and claim compliance with cruelty-free certification, packaging sourcing that reuses existing tooling wherever possible, retail line reviews and shelf-space allocation under a strictly limited planogram footprint, launch quantity decisions that trade stockout risk against markdown exposure, community and creator sampling, and finally discontinuation and refresh cadence.

The platform is built around three structural facts of the business. First, every cost decision is anchored to a small set of fixed retail price points, so cost targets are derived — not negotiated — and every quote is judged against them. Second, the scarce resources are finite pools: contract manufacturers offer a fixed number of production slots per calendar quarter, and each retail partner's shelf is a fixed map of category facings; both pools are reserved, committed, released, and reconciled by the rules in this document. Third, time is a first-class input: the system runs on a server-side logical clock that governs submission windows, quote validity, certification expiry, markdown depth, and launch timing, so that every deadline rule in the following pages reads one authoritative clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request missing either header, or carrying a role name that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other check runs. Once authenticated, a request whose role is not authorized for the endpoint — or for the particular field group it attempts to write — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles, spelled exactly as the API expects them in `X-User-Role`, are:

- `PlatformAdmin` — the operational superuser. It alone drives the logical clock and otherwise reads everything.
- `TrendScout` — spots trends on social platforms and prestige launches, registers trend signals, drives the trend lifecycle, and pitches, selects, and kills concepts.
- `ProductManager` — commercializes concepts into products, drives the product lifecycle, owns launch plans and their quantity, approval, execution, and reconciliation decisions, and proposes product discontinuations.
- `SourcingLead` — onboards, suspends, and reactivates contract manufacturers, opens formula projects, drives the formula review lifecycle, and evaluates, accepts, rejects, and settles cost quotes.
- `ComplianceOfficer` — opens compliance dossiers and records every ingredient, claim, certification, and registration review outcome.
- `RetailPlanner` — onboards retail partners and maintains their shelf capacities, schedules and drives line reviews, proposes and commits planogram slots, and approves or rejects discontinuation reviews.
- `MarketingLead` — owns the community and creator sampling program on launch plans: the sampling lifecycle and every sample-distribution event.
- `ManufacturerRep` — the portal identity of a contract manufacturer: submits and withdraws that manufacturer's own cost quotes and submits that manufacturer's formula samples.

Role identity is resolved as follows. When `X-User-Role` is `PlatformAdmin`, `TrendScout`, `ProductManager`, `SourcingLead`, `ComplianceOfficer`, `RetailPlanner`, or `MarketingLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, a discontinuation proposal stores it as `proposed_by_user_id` — but never compares it against an entity's `id`. When `X-User-Role` is `ManufacturerRep`, `X-User-ID` is the `id` of the acting `ContractManufacturer`; any resource that references a contract manufacturer — such as a quote's or formula project's `contract_manufacturer_id` — is compared against `X-User-ID` for ownership checks, and a `ManufacturerRep` touching another manufacturer's resource is rejected with `ERR_FORBIDDEN_ROLE`.

Authorization is field-sensitive on three endpoints. A product-plan update carrying `status` or `variant` requires `ProductManager`, while one carrying `sampling_status` or `sample_budget_cents` requires `MarketingLead`; mixing the two field groups in a single call is rejected with `ERR_FORBIDDEN_ROLE`. On the quote lifecycle, a withdrawal requires `ManufacturerRep` acting for its own manufacturer, while every other status target requires `SourcingLead`. On the formula lifecycle, a submission for sample review may be performed by either `SourcingLead` or the `ManufacturerRep` of that project's manufacturer, while every other status target requires `SourcingLead`.

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

List endpoints accept two query parameters: `limit`, the page size, defaulting to 10 with a minimum of 1 and a maximum of 100; and `offset`, the number of records to skip, defaulting to 0. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. Unless a filter narrows the result, list endpoints return resources sorted by `created_at` ascending.

### 2.4. The Logical Clock

All temporal rules in this document — submission windows, review dates, quote validity, certification expiry, occupancy intervals, markdown depth, launch timing — read a single server-side logical clock, never wall-clock time. Before the clock has been set by any call, it reads exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time. A `PlatformAdmin` advances the logical clock by supplying a `current_utc` instant through an admin-only test-driving capability, which returns the clock's new reading rendered exactly as the clock reads — the same `2026-09-01T00:00:00Z` form, at seconds precision with no fractional digits. Two lazy state changes hang off this clock: a quote whose `valid_until` has passed transitions to `EXPIRED` the next time it is read or written, and a dossier whose certification has passed its `cert_expires_at` transitions its certification dimension to `LAPSED` on the next read or write of that dossier.

### 2.5. Common Resource Properties

Every persisted resource carries a server-minted `id` as a UUID with no type prefix, plus `created_at` and `updated_at` timestamps rendered as ISO 8601 UTC with three fractional digits, and an integer `version` that increments by one on every mutation of that resource — including mutations caused by cascades. Timestamps described as "stamped" throughout this document (such as `selected_at`, `submitted_at`, `accepted_at`, `committed_at`, `launched_at`, `evaluated_at`) are logical-clock instants, not wall-clock ones. Every other datetime field a resource carries besides `created_at` and `updated_at` — the stamped instants just named, computed deadlines such as `due_at` and `cert_expires_at`, and client-supplied instants echoed back such as `valid_until`, the submission-window bounds, `review_date`, and the occupancy bounds — is rendered in the same form the logical clock reads: ISO 8601 UTC at seconds precision, with no fractional digits (for example, `2026-09-01T00:00:00Z`).

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Where a calculation produces a fractional cent, the rounding rule is stated with the calculation; the platform's default is round half up, applied per component before summation — components are rounded individually and then added, never added and then rounded. Amortization divisions round up to the next whole cent. The momentum score is the exception to integer precision: it is reported rounded half up to one decimal place, and the markdown risk ratio is reported to two decimal places.

### 2.7. Optimistic Concurrency Control

Two creation endpoints carry optimistic concurrency control on a parent entity, and no other endpoint takes a version field. A quote creation request must carry `expected_product_version` equal to the `version` of the target product as the client last observed it; a slot creation request must carry `expected_line_review_version` equal to the `version` of the target line review as the client last observed it. If the parent's current `version` has advanced since that observation — for example because another writer created a quote for the same product, or another slot was added to the same review — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never writes against a view of the parent it has not observed. Both creations advance the parent's `version` by one as part of their side effects, which is exactly what makes a second creation carrying an older observed version stale.

### 2.8. Validation Order and Error Precedence

When a single request violates several rules, the reported error is the one whose rule has the lowest priority number; the checks are evaluated in this fixed order. First, authentication: presence and validity of the identity headers (else `ERR_UNAUTHENTICATED`). Second, role authorization, including the field-level splits described in §2.1 (else `ERR_FORBIDDEN_ROLE`). Third, request shape: required fields present, types valid, enum members valid, conditionally required fields supplied, and review outcomes belonging to the requested dimension's outcome set (else `ERR_INVALID_REQUEST`). Fourth, path identifiers resolve, checked left to right (else the entity-specific not-found error, such as `ERR_PRODUCT_NOT_FOUND` or `ERR_LINE_REVIEW_NOT_FOUND`). Fifth, body foreign-key identifiers resolve, in the endpoint's declared input order (same family of not-found errors). Sixth, optimistic concurrency: the expected-version field matches the parent's current `version` (else `ERR_STALE_VERSION`). Seventh, state-machine from-state validity, including terminal-state lockdown, the from-state rules of the parallel packaging and sampling dimensions, and cross-entity state preconditions that have no more specific error (else `ERR_INVALID_STATE`). Eighth, the compliance gates (else `ERR_COMPLIANCE_GATE_FAILED`).

The remaining business rules follow in this order: a concept's parent trend must be `SELECTED` (else `ERR_TREND_NOT_SELECTED`; at this same step a category mismatch between concept and trend reports `ERR_INVALID_REQUEST` instead); a product's parent concept must be `SELECTED` (else `ERR_CONCEPT_NOT_SELECTED`); product advancement requires an approved formula and, later, an accepted quote (else `ERR_FORMULA_NOT_APPROVED` or `ERR_QUOTE_NOT_ACCEPTED` respectively); quote acceptance requires the product to be in `SOURCING` with an approved formula (else `ERR_PRODUCT_NOT_SOURCING`, or `ERR_FORMULA_NOT_APPROVED` when the formula is the missing piece); slot creation requires a `LAUNCH_READY` product (else `ERR_PRODUCT_NOT_LAUNCH_READY`) and plan approval requires a committed slot (else `ERR_SLOT_NOT_COMMITTED`); a discontinuation successor, when present, must be a `LAUNCH_READY` product different from the retired one (else `ERR_SUCCESSOR_INVALID`). Temporal gates come next: the line-review clock gates (else `ERR_SUBMISSION_WINDOW_CLOSED`), then quote validity (else `ERR_QUOTE_EXPIRED`), then the launch window (else `ERR_LAUNCH_WINDOW_NOT_OPEN`). Constraint rules follow: uniqueness of concept names and the one-dossier-per-product rule (else `ERR_DUPLICATE_CONCEPT_NAME` or `ERR_DOSSIER_ALREADY_EXISTS`), fixed price-point membership (else `ERR_INVALID_PRICE_POINT`), interval validity (else `ERR_INVALID_DATE_RANGE`), non-overlap of a partner's submission windows (else `ERR_WINDOW_OVERLAP`), occupancy conflicts on a shelf position (else `ERR_OCCUPANCY_CONFLICT`), category membership in the partner's capacity map (else `ERR_UNKNOWN_CATEGORY`), manufacturer availability (else `ERR_CM_SUSPENDED`), minimum-order floors (else `ERR_BELOW_MOQ`), and the capacity rules for shelf facings, quarterly production slots, and planogram lock (else `ERR_CAPACITY_EXCEEDED`, or `ERR_UNRESOLVED_SLOTS` for the planogram-lock case). Fiscal rules follow: the cost-target check (else `ERR_COST_TARGET_EXCEEDED`), the budget checks (else `ERR_BUDGET_EXCEEDED`), and the sampling caps (else `ERR_SAMPLE_OVERDRAW`). Last among business rules — deliberately placed after state and safety errors so those surface first — the segregation-of-duties check on discontinuation decisions (else `ERR_SEGREGATION_OF_DUTIES`).

### 2.9. Finite Pools: Production Slots and Shelf Facings

Two scarce pools are allocated and reconciled by the platform. Each contract manufacturer offers a fixed number of production slots per calendar quarter, recorded as `capacity_slots_per_quarter`; accepting a quote consumes one slot for the quarter named by the quote's `production_quarter`, and the consumption count for a manufacturer-quarter pair is the number of that manufacturer's quotes in `ACCEPTED` status bearing that quarter label. Acceptance order determines which quotes hold slots: quotes consume in `accepted_at` ascending order, with `created_at` ascending as the tie-break when two acceptances share a timestamp — never by identifier. A slot is released back to the pool only when an accepted quote is later invalidated by the reformulation cascade.

Each retail partner's shelf is a fixed map, `category_capacities`, from category code to total facing capacity. For each category, `committed_facings` is the sum of `facings` over that partner's planogram slots in `COMMITTED` or `ACTIVE` status — slots in `PROPOSED`, `WITHDRAWN`, `RELEASED`, or `VACATED` never count — and `available_facings` is the capacity minus the committed amount, never negative. Footprint conservation is an invariant: for every category, committed plus available always equals the configured capacity, so committing a slot and vacating or releasing one are compensating actions that leave the sum unchanged. These figures are recomputed on every commit, release, vacate, capacity change, and discontinuation cascade.

### 2.10. Primary Lifecycles and Parallel Dimensions

Most entities carry a single primary `status` lifecycle; terminal states are locked — no transition out of a terminal state is valid, and any such attempt is rejected with `ERR_INVALID_STATE`. Three entities carry additional parallel dimensions that evolve independently of the primary lifecycle: a product's `packaging_status` moves from `PACK_SOURCING` to `PACK_READY` and never back; a launch plan's `sampling_status` moves `NONE` to `PLANNED` to `ACTIVE` to `CLOSED`; and a compliance dossier carries four independent dimensions — `ingredient_status`, `claim_status`, `cert_status`, and `registration_status` — each advanced by its own review outcomes. Two lifecycles are deliberately cyclic: a product in `SOURCING` or `COMPLIANCE_GATE` can return to `FORMULATION`, and a formula project loops between `IN_DEVELOPMENT` and `SAMPLE_REVIEW` until its round budget is spent.

## 3. Business Logic & Workflows

### 3.1. Trend Discovery and Momentum Evaluation

A trend enters the platform when a `TrendScout` registers a trend signal, naming its `source` — exactly one of `SOCIAL_PLATFORM` or `PRESTIGE_LAUNCH` — along with the originating `platform` label, the `category` code the trend belongs to, the average daily mention volume over the trailing seven days as `mention_velocity_7d`, and week-over-week engagement growth as `engagement_growth_pct`, a ratio in which 1.5 means plus one hundred and fifty percent. One further input depends on the source: a signal whose `source` is `PRESTIGE_LAUNCH` must supply `prestige_similarity`, a similarity score between 0 and 1 against the prestige reference product, and a signal whose `source` is `SOCIAL_PLATFORM` must supply `cross_platform_spread`, a spread score between 0 and 1; supplying the wrong one for the source, or omitting the required one, is rejected with `ERR_INVALID_REQUEST`. A new signal starts in `DISCOVERED`, with `momentum_score` null and `evaluated_at` unset. The trend listing supports filtering by `status`, `source`, and `category`.

When a scout moves a signal from `DISCOVERED` into `EVALUATING`, the platform computes its momentum score and stamps `evaluated_at` with the logical-clock instant; the same recompute-and-stamp happens whenever a `PARKED` signal re-enters `EVALUATING`, so the score always reflects the field values at the most recent evaluation. The score normalizes each raw input against a cap: the velocity component is `mention_velocity_7d` divided by five thousand mentions per day, capped at one; the growth component is `engagement_growth_pct` divided by two, capped at one; and the signal component is `prestige_similarity` taken as-is for a prestige-sourced trend or `cross_platform_spread` taken as-is for a social one. The momentum score is then the sum of the velocity component weighted one half, the growth component weighted three tenths, and the signal component weighted one fifth, each scaled by one hundred, rounded half up to one decimal place. Selection is gated on this score: a scout may move an `EVALUATING` signal to `SELECTED` only when its `momentum_score` is at least seventy, and an attempt below that threshold is rejected with `ERR_TREND_SCORE_BELOW_THRESHOLD`. A scout may instead park an evaluating signal, moving it to `PARKED`, and may archive a signal from any of `DISCOVERED`, `EVALUATING`, or `PARKED`; `SELECTED` and `ARCHIVED` are terminal.

### 3.2. Concept Pitching and the Fixed Price-Point Cost Target

Concepts fast-follow selected trends. To pitch one, a `TrendScout` supplies the `trend_signal_id` of the parent trend, a `name`, a `category`, and a `target_price_point_cents`. Two referential rules guard creation: the parent trend must be in `SELECTED` status — pitching against a trend in any other state is rejected with `ERR_TREND_NOT_SELECTED` — and the concept's `category` must equal the parent trend's category, with a mismatch reported as `ERR_INVALID_REQUEST`. The price point is not free: `target_price_point_cents` must be one of exactly five values — 300, 600, 1000, 1500, or 2000 cents — and any other value is rejected with `ERR_INVALID_PRICE_POINT`. A concept's `name` must be unique across all concepts not in `KILLED` status; reusing a live name is rejected with `ERR_DUPLICATE_CONCEPT_NAME`. Concepts can be listed filtered by `trend_signal_id`, `status`, or `category`.

A concept begins as `PITCHED`. When the scout selects it, the platform derives the concept's cost ceiling from its fixed price point and stamps `selected_at`. The derivation applies a ratio that steps down as the price point rises: twenty-eight percent of the price point for a price point of 600 cents or less, twenty-six percent for one of 1000 cents or less, twenty-four percent for one of 1500 cents or less, and twenty-two percent for one of 2000 cents or less; the result is rounded down to a whole cent and stored as `target_unit_cost_cents`. The five price points therefore yield cost targets of 84, 168, 260, 360, and 440 cents respectively. A `PITCHED` or `SELECTED` concept may be moved to `KILLED` by the scout; once a product is commercializing the concept, the concept's further movement is driven by the product's lifecycle — the product's creation moves the concept from `SELECTED` to `IN_DEVELOPMENT`, a product reaching launch moves it to `COMMERCIALIZED`, and a killed product returns it to `SELECTED` so the concept can be commercialized again by a fresh product.

### 3.3. Product Commercialization, Tooling Reuse, and the Reformulation Loop

A `ProductManager` commercializes a selected concept by creating a product with the `concept_id`, an `sku_name`, and optionally a `tooling_code` identifying the packaging tooling. The concept must be in `SELECTED` status, else the creation is rejected with `ERR_CONCEPT_NOT_SELECTED`; a successful creation moves the concept into `IN_DEVELOPMENT`. The new product starts in `FORMULATION` with `packaging_status` `PACK_SOURCING`. Packaging lead time is computed once at creation: the platform detects `tooling_reuse` — true exactly when a `tooling_code` was supplied and another product exists with the same `tooling_code`, a strictly earlier `created_at`, and a status other than `KILLED` — and sets `packaging_lead_weeks` to five weeks when tooling is reused and fourteen weeks when new tooling must be cut. Products can be listed filtered by `concept_id`, `successor_product_id`, `status`, or `tooling_code`; the `successor_product_id` field itself stays null until the discontinuation cascade writes it.

The product lifecycle advances through gates. Moving a product from `FORMULATION` to `SOURCING` requires that at least one formula project for the product is in `APPROVED` status, else the advance is rejected with `ERR_FORMULA_NOT_APPROVED`. Moving from `SOURCING` to `COMPLIANCE_GATE` requires at least one quote for the product in `ACCEPTED` status, else `ERR_QUOTE_NOT_ACCEPTED`. Moving from `COMPLIANCE_GATE` to `LAUNCH_READY` requires two things together: the product's dossier must be fully compliant, else `ERR_COMPLIANCE_GATE_FAILED`, and the packaging dimension must have reached `PACK_READY` — a separate update the manager makes by setting `packaging_status` — else `ERR_INVALID_STATE`. A product does not reach `LAUNCHED` by direct update; it is advanced by the launch machinery described in §3.8, which also stamps `launched_at`, and `DISCONTINUED` is likewise cascade-only.

Reformulation is the deliberate loop back. A manager may return a product from `SOURCING` or `COMPLIANCE_GATE` to `FORMULATION` at any time, and the compliance cascades of §3.6 can force the same reversion. Either way, the reversion has two side effects executed atomically with it: every `ACCEPTED` quote for the product transitions to `INVALIDATED`, which releases the quarterly production slot that quote was consuming, and every `APPROVED` formula project for the product reopens to `IN_DEVELOPMENT` with its `round_count` incremented by one. A manager may also kill a product from any of `FORMULATION`, `SOURCING`, or `COMPLIANCE_GATE`; killing moves the linked concept back to `SELECTED` for a later revision and moves every non-terminal quote for the product — those in `SUBMITTED`, `UNDER_EVALUATION`, or `ACCEPTED` — to `SUPERSEDED`.

### 3.4. Contract Manufacturers and Compressed Formula Development

A `SourcingLead` onboards a contract manufacturer by registering its `name`, the `capabilities` array listing the category codes it can produce, its `base_lead_time_weeks` (at least one), its per-order `moq_units` minimum (at least one), its `quality_tier` of `STANDARD` or `PREMIUM`, and the `capacity_slots_per_quarter` it offers. A manufacturer starts `ACTIVE`. Suspending one — a `SourcingLead` decision moving it to `SUSPENDED` — blocks the creation of new formula projects and new quotes against it, and blocks acceptance of its pending quotes; any of these against a suspended manufacturer is rejected with `ERR_CM_SUSPENDED`. Reactivation returns it to `ACTIVE`. The manufacturer record's `capacity_slots_per_quarter` can also be revised by the sourcing lead.

Formula development runs on a compressed clock. A `SourcingLead` opens a formula project against a product and a manufacturer, supplying `product_id`, `contract_manufacturer_id`, and the formula `brief`; creation is rejected with `ERR_CM_SUSPENDED` when the manufacturer is suspended. The project starts in `IN_DEVELOPMENT` at `round_count` one, with its deadline `due_at` fixed at six weeks after creation — the compressed formula timeline. Projects may be listed filtered by `product_id`, `contract_manufacturer_id`, or `status`. Either the sourcing lead or the manufacturer's own `ManufacturerRep` may submit the project for review, moving it to `SAMPLE_REVIEW`; for a `ManufacturerRep`, `X-User-ID` must equal the project's `contract_manufacturer_id`, else `ERR_FORBIDDEN_ROLE`. Submission stamps `submitted_at` and computes `is_late`, which is true exactly when the submission instant is later than `due_at`.

Review outcomes belong to the `SourcingLead`. Approving a sample moves the project to `APPROVED` and sets `formula_version` to the current `round_count`, so the approved formula's version number is the round that produced it. Rejecting a sample returns the project to `IN_DEVELOPMENT` and increments `round_count` by one — unless the project is already at its third round, the maximum, in which case the rejection instead auto-transitions the project to `ABANDONED`, and the project can no longer supply an approvable formula. A sourcing lead may also abandon a project outright from `IN_DEVELOPMENT`. A later product reformulation reopens an approved project into `IN_DEVELOPMENT` with its round count incremented, as described in §3.3; the project's round budget does not reset.

### 3.5. Cost Quoting and Landed Cost

Quotes are submitted by the manufacturer's portal user. A quote creation names the `product_id` and the `contract_manufacturer_id` — which must equal the caller's `X-User-ID` when the caller is a `ManufacturerRep`, else `ERR_FORBIDDEN_ROLE` — and carries the commercial terms: `unit_cost_cents`, an optional `tooling_fee_cents` defaulting to zero, `freight_total_cents` for the whole shipment, `unit_weight_grams`, the total `shipment_weight_grams` (which must be at least the unit weight), the import `duty_rate` as a ratio in which 0.10 means ten percent, the `initial_order_qty`, the quote's `valid_until` deadline on the logical clock, and the `production_quarter` label the production slot will be consumed from. Creation also carries `expected_product_version` under the optimistic concurrency rule of §2.7. Creation is rejected with `ERR_CM_SUSPENDED` when the manufacturer is suspended. A new quote starts in `SUBMITTED` with its provisional landed cost computed (below); creating it supersedes the same manufacturer's prior `SUBMITTED` quote for the same product, moving that older quote to `SUPERSEDED`, and increments the product's `version` by one. Quotes can be listed filtered by `product_id`, `contract_manufacturer_id`, or `status`.

Landed cost has two pinned variants, both built from the same components in the same order. The freight component is the shipment's `freight_total_cents` scaled by the ratio of `unit_weight_grams` to `shipment_weight_grams`, rounded half up to a whole cent. The duty component is the duty rate applied to the sum of `unit_cost_cents` and the already-rounded freight component, again rounded half up to a whole cent — duty is computed from the rounded freight figure, and using the unrounded quotient yields a different, forbidden result. The provisional variant, computed at creation and stored as `landed_provisional_cents`, amortizes tooling by dividing `tooling_fee_cents` by `initial_order_qty` and rounding up to a whole cent, then sums unit cost, tooling amortization, freight, and duty. The settled variant is computed when a quote is settled with actuals: the actual freight component uses `actual_freight_total_cents` in place of the quoted total, the actual duty component derives from it the same way, tooling amortizes over `actual_qty` with the same round-up division, and the sum is stored as `landed_settled_cents` — null until settlement.

The sourcing lead drives evaluation. A `SUBMITTED` quote moves to `UNDER_EVALUATION`, and from there may be moved to `REJECTED`. Acceptance — moving an `UNDER_EVALUATION` quote to `ACCEPTED` — is the most heavily gated transition in the platform, and its checks are: the product must be in `SOURCING`, else `ERR_PRODUCT_NOT_SOURCING`; an approved formula project for the product must exist, else `ERR_FORMULA_NOT_APPROVED`; the quote's `landed_provisional_cents` must not exceed the parent concept's `target_unit_cost_cents`, with equality allowed, else `ERR_COST_TARGET_EXCEEDED`; the `initial_order_qty` must meet the manufacturer's `moq_units`, else `ERR_BELOW_MOQ`; the manufacturer must be `ACTIVE`, else `ERR_CM_SUSPENDED`; the logical clock must not have passed `valid_until`, else `ERR_QUOTE_EXPIRED` with the quote lazily moved to `EXPIRED`; and the manufacturer's quarterly pool must have room — the count of that manufacturer's `ACCEPTED` quotes sharing the same `production_quarter` must be strictly below `capacity_slots_per_quarter`, else `ERR_CAPACITY_EXCEEDED`. Acceptance stamps `accepted_at`, pins `pinned_formula_version` to the approved project's `formula_version`, consumes one quarterly production slot, and supersedes every other quote for the same product still in `SUBMITTED` or `UNDER_EVALUATION`.

From `SUBMITTED` or `UNDER_EVALUATION`, the manufacturer's own `ManufacturerRep` may withdraw the quote, moving it to `WITHDRAWN`. Once the product has launched — and only then — a sourcing lead may settle an accepted quote, moving it from `ACCEPTED` to `SETTLED` and supplying the actuals `actual_qty` and `actual_freight_total_cents`; attempting settlement while the product is anywhere short of `LAUNCHED` is rejected with `ERR_INVALID_STATE`. Settlement computes `landed_settled_cents` per the settled variant above. Reformulation moves an accepted quote to `INVALIDATED` and releases its production slot, and any read or attempted transition after `valid_until` lazily moves a still-pending quote to `EXPIRED`.

### 3.6. The Compliance Dossier: Ingredients, Claims, Certification, Registration

A `ComplianceOfficer` opens at most one dossier per product; opening a second is rejected with `ERR_DOSSIER_ALREADY_EXISTS`. The dossier carries four independent status dimensions, each advanced one step per review call, in which the officer supplies the `dimension`, the `outcome`, optionally `blocked_items`, and optionally `notes`. An outcome that is not a member of the requested dimension's outcome set is rejected with `ERR_INVALID_REQUEST`. Dossiers can be listed filtered by `product_id` or `cert_status`.

The ingredient dimension, `ingredient_status`, starts at `PENDING`. A review with outcome `CLEARED` moves it to `CLEARED` and empties `blocked_ingredients`; an outcome of `BLOCKED` from either `PENDING` or `BLOCKED` moves it to `BLOCKED` and records the supplied blocked ingredient names in `blocked_ingredients`; after reformulation, a `BLOCKED` dimension can be re-reviewed to `CLEARED`, clearing the list again. The claim dimension, `claim_status`, moves from `PENDING` to `SUBSTANTIATED`, from `PENDING` or `BLOCKED` to `BLOCKED`, and from `BLOCKED` back to `SUBSTANTIATED` on re-review.

The cruelty-free certification dimension, `cert_status`, walks a longer path: from `NOT_APPLIED` to `APPLIED`, from `APPLIED` to `AUDITING`, and from `AUDITING` to either `CERTIFIED` or `DENIED`. Certification stamps `cert_expires_at` at exactly three hundred and sixty-five days after the review instant. Thereafter the certification lapses lazily: any read or write of the dossier once the logical clock has passed `cert_expires_at` moves the dimension to `LAPSED`. Both denial and lapse fire the product-reversion cascade: if the product is in `COMPLIANCE_GATE` or `LAUNCH_READY`, it reverts directly to `FORMULATION` — with no intermediate state — and that reversion in turn invalidates every accepted quote and reopens every approved formula project exactly as the manual reformulation of §3.3 does. If the product has already reached `LAUNCHED` when the lapse is discovered, the product stays `LAUNCHED`, but the dossier is no longer compliant and further launch-plan approvals are blocked. The registration dimension, `registration_status`, moves from `UNFILED` to `FILED`, from `FILED` to either `REGISTERED` or `REJECTED`, and from `REJECTED` back to `REGISTERED`.

Compliance is a derived verdict: `compliant` is true exactly when `ingredient_status` is `CLEARED`, `claim_status` is `SUBSTANTIATED`, `cert_status` is `CERTIFIED` and has not lazily lapsed, and `registration_status` is `REGISTERED`. This verdict gates two transitions elsewhere in the platform — the product's move to `LAUNCH_READY` and the launch plan's move to `APPROVED` — each rejected with `ERR_COMPLIANCE_GATE_FAILED` when the verdict is false.

### 3.7. Retail Partners, Line Reviews, and Shelf-Space Allocation

A `RetailPlanner` onboards a retail partner with its `name`, an informational `banner_code`, and the `category_capacities` map from category code to total facings — the limited shelf footprint the partner can offer. From then on the partner's `committed_facings` and `available_facings` are maintained by the reconciliation rule of §2.9. A planner may revise `category_capacities`; when a revision reduces a category below its currently committed facings, the platform evicts to fit: it walks that category's `COMMITTED` slots — never `ACTIVE` ones — from most recently committed to least, ordered by `committed_at` descending with `created_at` descending as the tie-break, moving each evicted slot to `RELEASED` and reverting its quantity-locked or approved launch plan to `DRAFT`, until committed facings fit the new capacity. If `ACTIVE` slots alone still exceed the new capacity after every `COMMITTED` slot has been evicted, the whole capacity revision is rejected with `ERR_CAPACITY_EXCEEDED` and nothing is evicted — the reduction is atomic.

Line reviews are how products win shelf space. A `RetailPlanner` schedules one by naming the `retail_partner_id`, a `season` label, and three instants on the logical clock: `submission_window_start`, `submission_window_end`, and `review_date`. The window is a half-open interval — it includes the start instant and excludes the end instant — and the dates must be internally valid: the window end must be later than the start, and the review date must fall on or after the window end, else creation is rejected with `ERR_INVALID_DATE_RANGE`. Across one partner's reviews, the submission windows of all reviews not in `CANCELLED` must not overlap, though adjacency — one window's start equal to another's end — is allowed; an overlapping schedule is rejected with `ERR_WINDOW_OVERLAP`. Reviews can be listed filtered by `retail_partner_id` or `status`.

The review lifecycle is clock-gated. A review starts `SCHEDULED`; the planner opens submissions, moving it to `SUBMISSION_OPEN`, only when the logical clock reads at or after `submission_window_start` and strictly before `submission_window_end`, else `ERR_SUBMISSION_WINDOW_CLOSED`. Moving from `SUBMISSION_OPEN` to `REVIEWING` requires the clock to have reached `submission_window_end`, and moving from `REVIEWING` to `DECIDED` requires the clock to have reached `review_date`; both violations report `ERR_SUBMISSION_WINDOW_CLOSED`. Locking the planogram — `DECIDED` to `PLANOGRAM_LOCKED` — requires that no slot of the review remains in `PROPOSED`, else `ERR_UNRESOLVED_SLOTS`. A review in any of `SCHEDULED`, `SUBMISSION_OPEN`, `REVIEWING`, or `DECIDED` may instead be cancelled; cancellation moves the review's `PROPOSED` slots to `WITHDRAWN` and its `COMMITTED` slots to `RELEASED`, freeing their facings, and each released slot reverts its quantity-locked or approved launch plan to `DRAFT` with its locked quantity cleared.

Within an open window, the planner proposes planogram slots. Creation names the `line_review_id`, the `product_id` — which must be `LAUNCH_READY`, else `ERR_PRODUCT_NOT_LAUNCH_READY` — a `category` that must be a key of the partner's `category_capacities` map, else `ERR_UNKNOWN_CATEGORY`, a `position_code` identifying the shelf position, the number of `facings` requested (at least one), and an occupancy interval from `occupancy_start` to `occupancy_end`. The review must be in `SUBMISSION_OPEN` — a state precondition reported as `ERR_INVALID_STATE` — and the logical clock must be inside the submission window, else `ERR_SUBMISSION_WINDOW_CLOSED`. The occupancy interval is closed — it includes both its start and its end — and the end must not precede the start, else `ERR_INVALID_DATE_RANGE`. Two slots colliding on the same position are detected per partner, category, and `position_code`: among slots in `PROPOSED`, `COMMITTED`, or `ACTIVE`, a new occupancy must begin strictly more than fourteen days after the existing occupancy's end, or end strictly more than fourteen days before the existing occupancy's start; a reset gap of exactly fourteen days is allowed. A collision is rejected with `ERR_OCCUPANCY_CONFLICT`. Creation carries `expected_line_review_version` under the optimistic concurrency rule of §2.7, and a successful creation increments the review's `version` by one. Slots can be listed filtered by `line_review_id`, `product_id`, `status`, or `category`.

A slot starts `PROPOSED`. Once its review has reached `DECIDED` — else the commit is rejected with `ERR_INVALID_STATE` — the planner may commit it, moving it to `COMMITTED`. Committing is capacity-checked: the category's currently committed facings plus the slot's `facings` must not exceed the partner's configured capacity for that category, with equality allowed, else `ERR_CAPACITY_EXCEEDED`. A successful commit stamps `committed_at` — the eviction ordering key of §3.7's capacity revision rule — and recomputes the partner's facing availability. A `PROPOSED` slot may instead be withdrawn by the planner, and is withdrawn automatically when its review is cancelled. A committed slot becomes `ACTIVE` only through the launch execution of §3.8, and reaches `RELEASED` only through review cancellation or capacity eviction — each release reverting its launch plan to `DRAFT` with `qty_locked_units` and `landed_locked_cents` cleared — and reaches `VACATED` only through product discontinuation.

### 3.8. Launch Planning, Quantity Locking, Sampling, and Reconciliation

A launch plan ties a product to a shelf position for its launch window. A `ProductManager` creates one by naming the `product_id` and `planogram_slot_id` and supplying `demand_forecast_units`, `marketing_budget_cents`, `cogs_budget_cents`, and optionally `sample_budget_cents` defaulting to zero. Two computed quantities are fixed at creation. First, `capacity_units` — the most the shelf can sell through: the slot's `facings` multiplied by twelve units of weekly sell-through per facing, multiplied by the eight-week launch window. Second, `markdown_risk_pct` — the decay risk of a trend item: the number of whole weeks between the parent trend's `created_at` and the plan's `created_at`, multiplied by five percent per week, capped at forty percent, reported to two decimal places; the trend is reached through the plan's product, its concept, and that concept's `trend_signal_id`. From these, both quantity variants are computed and stored at creation: the demand-projection variant `qty_demand_variant_units` is the smaller of `demand_forecast_units` and `capacity_units`, and the risk-adjusted variant `qty_risk_variant_units` is the smaller of the floor of `demand_forecast_units` reduced by `markdown_risk_pct` and `capacity_units`. Plans can be listed filtered by `product_id`, `planogram_slot_id`, or `status`.

Locking the quantity — moving a `DRAFT` plan to `QUANTITY_LOCKED` — requires the manager to choose a `variant` of `DEMAND` or `RISK_ADJUSTED`; any other value is rejected with `ERR_INVALID_REQUEST`. An `ACCEPTED` quote for the product must exist, else `ERR_QUOTE_NOT_ACCEPTED`. The lock then resolves in a single pass, with no iteration, because landed cost depends on quantity through tooling amortization while quantity is clamped by a budget that itself contains landed cost. The candidate quantity is the chosen variant's stored figure. Landed unit cost at a quantity is the accepted quote's `unit_cost_cents` plus its `tooling_fee_cents` divided by that quantity and rounded up to a whole cent, plus the freight and duty per-unit components exactly as computed at acceptance. If the candidate quantity times its landed cost stays within `cogs_budget_cents`, the candidate becomes `qty_locked_units`. Otherwise the clamp applies once: the landed cost is evaluated a single time at the manufacturer's minimum order quantity, the budget is divided by that figure and floored to a whole unit count, and if that floored count falls below the minimum order quantity the lock is rejected with `ERR_BUDGET_EXCEEDED`; otherwise the floored count becomes `qty_locked_units`. In either branch, a locked quantity below the manufacturer's minimum is rejected with `ERR_BELOW_MOQ`. The lock records `locked_variant` and stores `landed_locked_cents`, the landed unit cost at the locked quantity.

Approval — `QUANTITY_LOCKED` to `APPROVED` — rechecks the world: the slot must be `COMMITTED`, else `ERR_SLOT_NOT_COMMITTED`; the product's dossier must be fully compliant with a certification that has not lapsed, else `ERR_COMPLIANCE_GATE_FAILED`; and `sample_budget_cents` must not exceed `marketing_budget_cents`, else `ERR_BUDGET_EXCEEDED`. Execution — `APPROVED` to `EXECUTED` — waits for the shelf: the logical clock must have reached the slot's `occupancy_start`, else `ERR_LAUNCH_WINDOW_NOT_OPEN`. Execution fans out atomically: the product moves from `LAUNCH_READY` to `LAUNCHED` with `launched_at` stamped, the slot moves from `COMMITTED` to `ACTIVE`, and the product's concept moves from `IN_DEVELOPMENT` to `COMMERCIALIZED`.

Reconciliation closes the loop. A manager may reconcile an `EXECUTED` plan only when its sampling program is quiet — `sampling_status` must be `NONE` or `CLOSED`, else `ERR_INVALID_STATE` — and discontinuation reconciles it automatically. Reconciliation moves every unsold unit to markdown: `markdown_units` is set to `retail_units_available`, and `markdown_exposure_cents` is computed from the markdown depth tier for the product's age. The depth depends on whole weeks since `launched_at`: zero percent when four weeks or fewer have elapsed, thirty percent through eight weeks, fifty percent through twelve weeks, and seventy percent beyond that; the exposure is `markdown_units` times `landed_locked_cents` times the depth, in integer cents. Throughout the plan's life, `retail_units_available` is always the locked quantity minus `samples_committed`, minus `samples_distributed`, minus `markdown_units`.

The sampling program is the `MarketingLead`'s parallel track on the plan. The marketing lead may move `sampling_status` from `NONE` to `PLANNED` while the plan is in `QUANTITY_LOCKED`, `APPROVED`, or `EXECUTED` — any other plan state is rejected with `ERR_INVALID_STATE` — from `PLANNED` to `ACTIVE` only while the plan is `EXECUTED`, and from `ACTIVE` to `CLOSED`; once closed, no further distribution events are accepted, and any attempted one is rejected with `ERR_INVALID_STATE`. The `sample_budget_cents` field itself is writable only by the marketing lead. Sample movements are recorded as append-only distribution events, each carrying an `event_type`, a count of `units`, and optionally a `channel` label, and are processed in creation order. Three event types exist. A `COMMIT` event reserves units for sampling: the running total of `samples_committed` plus `samples_distributed` plus the new units must stay within the sampling cap — the floor of ten percent of `qty_locked_units` — else the event is rejected with `ERR_SAMPLE_OVERDRAW`; the units must also fit within `retail_units_available`; a committed event adds its units to `samples_committed`. A `DISTRIBUTE` event fulfills committed units: the count must not exceed `samples_committed`, the program must be `ACTIVE`, and the event charges the sampling budget by adding the units times `landed_locked_cents` to `sample_spend_cents`, which must never exceed `sample_budget_cents`, else `ERR_SAMPLE_OVERDRAW`; the units move from `samples_committed` to `samples_distributed`. A `RELEASE` event is the compensating action: its count must not exceed `samples_committed`, and it returns the units to retail availability by decrementing `samples_committed`; a commit followed by a release of the same size leaves every bucket unchanged. Launch inventory is conserved at all times after the quantity lock: `qty_locked_units` always equals `retail_units_available` plus `samples_committed` plus `samples_distributed` plus `markdown_units`.

### 3.9. Discontinuation and Refresh Cadence

Discontinuation is proposed and approved by different hands. A `ProductManager` proposes by creating a discontinuation review naming the `product_id`, a `reason` of `TREND_DECAY`, `REFRESH_CADENCE`, or `PERFORMANCE`, and optionally a `successor_product_id` for the refresh successor. The retired product must be `LAUNCHED` — a state precondition reported as `ERR_INVALID_STATE` — and the successor, when present, must be a `LAUNCH_READY` product different from the retired one, else `ERR_SUCCESSOR_INVALID`. The proposal records the proposer's `X-User-ID` as `proposed_by_user_id`, and the review starts `PROPOSED`. Reviews can be listed filtered by `product_id`, `successor_product_id`, or `status`.

A `RetailPlanner` decides. Both approval and rejection enforce segregation of duties: the decider's `X-User-ID` must differ from `proposed_by_user_id`, else the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Rejection simply closes the review as `REJECTED`. Approval fires the discontinuation cascade, atomically and four entities deep: the product moves from `LAUNCHED` to `DISCONTINUED` with its `successor_product_id` set from the review — which may be null; every `COMMITTED` or `ACTIVE` planogram slot for the product moves to `VACATED`, freeing its facings; each vacancy forces recomputation of the partner's `committed_facings` and `available_facings`; and the product's `EXECUTED` launch plan moves to `RECONCILED` with `markdown_units` set to `retail_units_available` and `markdown_exposure_cents` computed from the depth tiers of §3.8. The freed shelf and the reconciled plan are what make room — and budget — for the refresh successor.

## 4. Endpoint Definitions

All endpoints live under a single flat URL hierarchy. Successful creation of a new resource returns HTTP 201 with the created resource; successful modifications, reads, and lifecycle transitions return HTTP 200. Every list endpoint accepts the pagination parameters of §2.3 and returns the paginated envelope of §2.2. Request bodies, response payloads, and side effects are specified by the narratives of §2 and §3; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Advance the server's logical clock to a supplied `current_utc` instant | `PlatformAdmin` |
| POST | `/trend-signals` | Register a trend signal from a social platform or prestige launch | `TrendScout` |
| GET | `/trend-signals` | List trend signals with filters | All roles |
| PATCH | `/trend-signals/{id}` | Drive the trend lifecycle: evaluate (computes momentum), park, select (score-gated), archive | `TrendScout` |
| POST | `/concepts` | Pitch a concept fast-following a `SELECTED` trend | `TrendScout` |
| GET | `/concepts` | List concepts with filters | All roles |
| GET | `/concepts/{id}` | Read one concept | All roles |
| PATCH | `/concepts/{id}` | Concept lifecycle: select (computes cost target) or kill | `TrendScout` |
| POST | `/products` | Commercialize a `SELECTED` concept into a product (computes tooling reuse and packaging lead time) | `ProductManager` |
| GET | `/products` | List products with filters | All roles |
| GET | `/products/{id}` | Read one product | All roles |
| PATCH | `/products/{id}` | Product lifecycle: advance gates, reformulate, kill; packaging readiness | `ProductManager` |
| POST | `/manufacturers` | Onboard a contract manufacturer | `SourcingLead` |
| GET | `/manufacturers/{id}` | Read one contract manufacturer | All roles |
| PATCH | `/manufacturers/{id}` | Suspend or reactivate a manufacturer; revise quarterly capacity | `SourcingLead` |
| POST | `/formula-projects` | Open a compressed-timeline formula project with a manufacturer | `SourcingLead` |
| GET | `/formula-projects` | List formula projects with filters | All roles |
| GET | `/formula-projects/{id}` | Read one formula project | All roles |
| PATCH | `/formula-projects/{id}` | Formula lifecycle: submit sample, approve, reject (auto-abandon at the round cap), abandon | `SourcingLead`, `ManufacturerRep` (sample submission, own manufacturer only) |
| POST | `/cost-quotes` | Submit a cost quote (optimistic concurrency on the product); computes provisional landed cost and supersedes the same manufacturer's prior pending quote | `ManufacturerRep` |
| GET | `/cost-quotes` | List cost quotes with filters | All roles |
| GET | `/cost-quotes/{id}` | Read one cost quote | All roles |
| PATCH | `/cost-quotes/{id}` | Quote lifecycle: evaluate, accept, reject, settle with actuals, or withdraw (own manufacturer only) | `SourcingLead`, `ManufacturerRep` (withdrawal only) |
| POST | `/compliance-dossiers` | Open the compliance dossier for a product (at most one per product) | `ComplianceOfficer` |
| GET | `/compliance-dossiers` | List compliance dossiers with filters | All roles |
| GET | `/compliance-dossiers/{id}` | Read one dossier (applies lazy certification lapse) | All roles |
| POST | `/compliance-dossiers/{id}/reviews` | Advance exactly one compliance dimension with a review outcome | `ComplianceOfficer` |
| POST | `/retail-partners` | Onboard a retail partner with per-category shelf facing capacities | `RetailPlanner` |
| GET | `/retail-partners/{id}` | Read one retail partner including computed facing availability | All roles |
| PATCH | `/retail-partners/{id}` | Revise category capacities; a reduction below committed facings triggers the capacity-eviction cascade | `RetailPlanner` |
| POST | `/line-reviews` | Schedule a line review with a half-open, non-overlapping submission window | `RetailPlanner` |
| GET | `/line-reviews` | List line reviews with filters | All roles |
| GET | `/line-reviews/{id}` | Read one line review | All roles |
| PATCH | `/line-reviews/{id}` | Line review lifecycle: open submissions, review, decide, lock planogram, or cancel (clock-gated) | `RetailPlanner` |
| POST | `/planogram-slots` | Propose a planogram slot during an open submission window (optimistic concurrency on the review) | `RetailPlanner` |
| GET | `/planogram-slots` | List planogram slots with filters | All roles |
| GET | `/planogram-slots/{id}` | Read one planogram slot | All roles |
| PATCH | `/planogram-slots/{id}` | Slot lifecycle: commit (capacity-checked) or withdraw | `RetailPlanner` |
| POST | `/launch-plans` | Create a launch plan; computes both quantity variants and markdown risk at creation | `ProductManager` |
| GET | `/launch-plans` | List launch plans with filters | All roles |
| GET | `/launch-plans/{id}` | Read one launch plan including the sampling rollup | All roles |
| PATCH | `/launch-plans/{id}` | Plan lifecycle: lock quantity (with variant), approve, execute, reconcile; sampling lifecycle on the parallel dimension | `ProductManager` (status/variant fields), `MarketingLead` (sampling fields) |
| POST | `/launch-plans/{id}/sample-distributions` | Record a sampling event: commit, distribute, or release units | `MarketingLead` |
| POST | `/discontinuation-reviews` | Propose discontinuing a `LAUNCHED` product, optionally naming a refresh successor | `ProductManager` |
| GET | `/discontinuation-reviews` | List discontinuation reviews with filters | All roles |
| GET | `/discontinuation-reviews/{id}` | Read one discontinuation review | All roles |
| PATCH | `/discontinuation-reviews/{id}` | Approve (fires the discontinuation cascade) or reject, under segregation of duties | `RetailPlanner` |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TREND_SIGNAL_NOT_FOUND` | 404 |
| `ERR_CONCEPT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_MANUFACTURER_NOT_FOUND` | 404 |
| `ERR_FORMULA_PROJECT_NOT_FOUND` | 404 |
| `ERR_COST_QUOTE_NOT_FOUND` | 404 |
| `ERR_DOSSIER_NOT_FOUND` | 404 |
| `ERR_RETAIL_PARTNER_NOT_FOUND` | 404 |
| `ERR_LINE_REVIEW_NOT_FOUND` | 404 |
| `ERR_PLANOGRAM_SLOT_NOT_FOUND` | 404 |
| `ERR_LAUNCH_PLAN_NOT_FOUND` | 404 |
| `ERR_DISCONTINUATION_REVIEW_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TREND_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_TREND_NOT_SELECTED` | 422 |
| `ERR_DUPLICATE_CONCEPT_NAME` | 409 |
| `ERR_INVALID_PRICE_POINT` | 422 |
| `ERR_CONCEPT_NOT_SELECTED` | 422 |
| `ERR_FORMULA_NOT_APPROVED` | 422 |
| `ERR_QUOTE_NOT_ACCEPTED` | 422 |
| `ERR_PRODUCT_NOT_SOURCING` | 422 |
| `ERR_PRODUCT_NOT_LAUNCH_READY` | 422 |
| `ERR_CM_SUSPENDED` | 422 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_BELOW_MOQ` | 422 |
| `ERR_COST_TARGET_EXCEEDED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_DOSSIER_ALREADY_EXISTS` | 409 |
| `ERR_COMPLIANCE_GATE_FAILED` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 |
| `ERR_OCCUPANCY_CONFLICT` | 409 |
| `ERR_UNRESOLVED_SLOTS` | 422 |
| `ERR_SLOT_NOT_COMMITTED` | 422 |
| `ERR_LAUNCH_WINDOW_NOT_OPEN` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_SAMPLE_OVERDRAW` | 422 |
| `ERR_SUCCESSOR_INVALID` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_DATE_RANGE` | 422 |
