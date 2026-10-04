# US Mint Coinage API — Product Requirements Document

## 1. Introduction

The United States Mint runs two economically distinct businesses on shared production infrastructure. On the circulating side, the Mint strikes coinage against Federal Reserve orders: it procures metal tonnage, converts delivered metal into blanks, schedules press lines, and tracks the difference between a coin's face value and its production cost — the seigniorage that accrues to the Treasury. On the numismatic side, the Mint develops congressionally authorized commemorative programs carrying statutory surcharges owed to named beneficiaries, sells limited-mintage collector products under household order limits, enrolls collectors in subscription programs with recurring billing, and operates a bullion channel in which authorized purchaser firms confirm priced allocations against live spot prices. Quality control closes the loop: error coins are quarantined, counted against each denomination's recent error rate, and destroyed under dual certification.

This document specifies the API backing those operations. Fourteen resources share one response envelope, one pagination scheme, one optimistic-concurrency convention, and one logical clock. Because striking schedules, statutory sales windows, billing due dates, and bullion offer expirations all turn on time, the platform never reads wall-clock time: a single administrative operation sets the logical clock and the current commodity spot prices, and every time-based rule in the system evaluates against that clock. All business resources are mounted under the `/mint` prefix; the clock operation is platform-level and deliberately sits outside that prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1 User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or whose `X-User-Role` value is not one of the twelve declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not listed among the roles authorized for the invoked endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The twelve roles, spelled exactly as the API expects them: `Anonymous`, `PlatformAdmin`, `FedLiaison`, `ProcurementOfficer`, `ProductionPlanner`, `QualityInspector`, `DestructionCertifier`, `ProgramManager`, `MintDirector`, `FinanceOfficer`, `Collector`, and `BullionDealer`.

Two roles are entity-backed. When `X-User-Role` is `Collector`, `X-User-ID` is the `id` of the acting `Collector`; ownership checks on orders, subscriptions, and invoices compare the resource's `collector_id` (or its parent subscription's `collector_id`) against `X-User-ID`, and a Collector calling a list endpoint with a `collector_id` filter must pass their own id. When `X-User-Role` is `BullionDealer`, `X-User-ID` is the `id` of the acting `AuthorizedPurchaser`; the dealer may confirm only those allocations whose `authorized_purchaser_id` equals `X-User-ID`. A violation of either ownership rule is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The remaining ten roles — `Anonymous`, `PlatformAdmin`, `FedLiaison`, `ProcurementOfficer`, `ProductionPlanner`, `QualityInspector`, `DestructionCertifier`, `ProgramManager`, `MintDirector`, and `FinanceOfficer` — are opaque: for each of them `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it where a workflow captures an actor (for example `created_by_user_id` on a program, `offered_by_user_id` on an allocation, or `reported_by_user_id` on an error-coin case) but never compares it to an entity `id` for ownership. `Anonymous` is itself a declared role value rather than an absence of authentication: unauthenticated public callers send `X-User-Role: Anonymous` with an arbitrary `X-User-ID`, and may invoke only collector registration.

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

### 2.3 Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a `limit` outside that inclusive range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). `offset` defaults to 0. List responses are sorted by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4 The Logical Clock and Market Spot Prices

The platform keeps a logical clock that never reads wall-clock time. At server boot the logical clock reads exactly 2026-09-01T00:00:00Z and no spot prices are established for any commodity or metal. A `PlatformAdmin` moves the clock through the platform-level endpoint `POST /_clock/set_current_utc`, which is intentionally mounted outside the `/mint` prefix. The request body carries `to_iso8601` (required) and optionally `spot_prices`, a map from commodity or metal name to an integer price in cents per unit — per troy ounce for `GOLD`, `SILVER`, and `PLATINUM`, and per metric tonne for `COPPER`, `NICKEL`, and `ZINC`. Each key present in `spot_prices` replaces the current price for that commodity or metal; keys not present in the map are left unchanged. The operation responds 200 OK with `current_utc` and the full current `spot_prices` map.

The clock is monotonic: any attempt to set it to an instant earlier than its current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Setting the clock also sweeps every time-based rule in the system: commemorative programs open and close their statutory sales windows, scheduled numismatic products release for sale, and open bullion allocation offers expire. Section 3 details each sweep. Any rule that asks what time it is — a billing cycle's due date, a vault's same-day received tonnage, an offer's expiry instant — reads this logical clock and nothing else.

### 2.5 Resource Identity, Timestamps, and Versioning

All fourteen resources share a common property set. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps maintained by the server. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including system-driven auto-transitions.

Timestamps render in two families, and the distinction is contractual. The system family — `created_at`, `updated_at`, and the envelope's `api_request_timestamp` — always renders as ISO 8601 UTC with exactly three fractional digits (for example `2026-09-01T00:00:00.000Z`). The domain family — `planned_start`, `planned_end`, `release_datetime`, `sales_window_start`, `sales_window_end`, `offer_expires_at`, and the clock's own `current_utc` — renders as the logical clock reads, or exactly as the value was supplied at input, with no millisecond normalization applied. Date-typed fields (`due_date`, `planned_delivery_date`, `next_billing_date`) render as ISO 8601 calendar dates.

Nullable computed fields stay null until the event that fixes them: an order's `realized_seigniorage_cents` until the order is fulfilled, a lot's `realized_cost_cents` until the lot is delivered, an allocation's `total_price_cents` until the allocation is confirmed, and a case's `destroyed_by_user_ids` until destruction is certified.

### 2.6 Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control; no other endpoint accepts a version field of any kind.

Creating a bullion allocation requires the request to carry `expected_bullion_issue_version`, holding the `version` of the parent `BullionIssue` as the client last observed it. If the issue's current `version` has advanced since that observation — because another offer was accepted against the issue or an expiry restored units to its pool — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never sizes and prices an offer against a stale view of the remaining pool.

Running a subscription billing cycle requires the request to carry `expected_subscription_version`, holding the `version` of the `Subscription` as the client last observed it. A mismatch with the subscription's current `version` — advanced by an intervening billing cycle or a dunning transition — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a billing run against a schedule the client has not observed.

### 2.7 Validation Order and Error Precedence

Validations are evaluated as a fixed ladder; the earliest rung that fails produces the response, and later rungs are never consulted. The rungs, in evaluation order, are:

1. Authentication presence — both headers are present and `X-User-Role` names a declared role (`ERR_UNAUTHENTICATED`, 401).
2. Role authorization — the role appears in the endpoint's authorized list (`ERR_UNAUTHORIZED_ROLE`, 403).
3. Entity-backed ownership — Collectors read and act only on orders, subscriptions, and invoices whose `collector_id` equals their `X-User-ID`, a Collector list filter must name the caller's own `collector_id`, and a BullionDealer confirms only allocations whose `authorized_purchaser_id` equals their `X-User-ID` (`ERR_FORBIDDEN_OWNERSHIP`, 403).
4. Path existence — every id in the URL path resolves to an existing resource, validated left to right along the path (`ERR_NOT_FOUND`, 404).
5. State-machine preconditions — the invoked transition exists from the resource's current state, including any transition-specific state preconditions, and the OCC version check on the two concurrency-guarded endpoints. Transitions carrying a dedicated domain error raise it (for example `ERR_RUN_NOT_STARTABLE`, `ERR_ORDER_NOT_PAYABLE`, `ERR_LOT_NOT_RECEIVABLE`); any other invalid from-state falls back to `ERR_INVALID_STATE_TRANSITION` (422); an OCC mismatch raises `ERR_STALE_VERSION` (412). Two product-state gates also live at this rung: order placement requires the product to be in `ON_SALE` or `SOLD_OUT`, and subscription enrollment requires the product to be `ON_SALE`, both rejected otherwise as `ERR_PRODUCT_NOT_ORDERABLE` (422).
6. Referential integrity — body references resolve: `denomination_code` to an existing denomination (`ERR_UNKNOWN_DENOMINATION`, 422), a supplied `program_id` to an existing program (`ERR_UNKNOWN_PROGRAM`, 422), `product_id` to an existing product (`ERR_UNKNOWN_PRODUCT`, 422), a current spot price established for the commodity or metal (`ERR_SPOT_PRICE_MISSING`, 422), and the authorized purchaser existing in `APPROVED` status (`ERR_AP_NOT_APPROVED`, 422). A production run inherits its denomination from its parent Federal Reserve order; an unresolvable denomination through that chain is likewise `ERR_UNKNOWN_DENOMINATION`.
7. Safety gates — segregation-of-duties separations (`ERR_SEGREGATION_OF_DUTIES`, 422) and the denomination quality gate (`ERR_QUALITY_THRESHOLD_BREACH`, 422).
8. Temporal rules — press-window overlap (`ERR_PRESS_WINDOW_OVERLAP`, 409), release-family gap (`ERR_RELEASE_GAP_VIOLATION`, 409), billing due date (`ERR_BILLING_NOT_DUE`, 422), and clock monotonicity (`ERR_CLOCK_REGRESSION`, 422).
9. Request and constraint checks — payload shape, required fields, types, enum membership, datetime parsing, and rejection of undeclared or read-only fields (`ERR_INVALID_REQUEST`, 400); strictly positive quantities (`ERR_QUANTITY_INVALID`, 400); uniqueness of `code`, `product_code`, and `email` (`ERR_DENOMINATION_EXISTS`, `ERR_PRODUCT_CODE_EXISTS`, and `ERR_EMAIL_EXISTS` respectively, all 409); duplicate live subscriptions (`ERR_DUPLICATE_SUBSCRIPTION`, 409); subscription product eligibility (`ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT`, 422); vault daily capacity (`ERR_VAULT_CAPACITY_EXCEEDED`, 422); the program mintage ceiling (`ERR_PROGRAM_MINTAGE_EXCEEDED`, 422); error-coin quantity against the run's scrapped pieces (`ERR_ERRORCOIN_QUANTITY_EXCEEDS`, 422); exact payment amounts (`ERR_PAYMENT_AMOUNT_MISMATCH`, 422); and withdrawal blocked by live subscriptions (`ERR_PRODUCT_NOT_WITHDRAWABLE`, 422).
10. Fiscal limits — household order limits (`ERR_HOUSEHOLD_LIMIT_EXCEEDED`, 422), bullion pool sufficiency (`ERR_POOL_INSUFFICIENT`, 422), and blank stock sufficiency (`ERR_BLANKS_INSUFFICIENT`, 422).

The ladder has practical consequences. On order placement, a product-state failure at rung five surfaces before a malformed payload at rung nine, and the household limit at rung ten is the last check standing between a valid request and a created order. Where a request body references another resource, that reference is resolved at rung six; the state gates at rung five evaluate against the resolved resource.

### 2.8 Monetary Precision and Rounding

All monetary amounts are integer cents. Where a per-unit cost must carry fractions — the budgeted or realized unit margin behind seigniorage — it is kept to 2 decimal places with round-half-up rounding. Round half up means a value exactly halfway between two representable results rounds away from zero to the next representable result, and it is the only rounding mode the platform uses. Several formulas pin the rounding order: the per-unit figure is rounded first and only then multiplied by quantity; §3 pins each such site explicitly. Ratios such as the denomination error rate are compared exactly as rational numbers over integers, never through a rounded decimal approximation. Integer-unit rules (pieces, units, tonnes) use exact integer arithmetic with the inclusivity each rule states.

### 2.9 Seigniorage Accounting, Blank-Stock Reconciliation, and Computed Reports

Two seigniorage variants coexist for every denomination. The budgeted variant uses the denomination's configured `blank_budget_cost_cents` and is snapshotted into each Federal Reserve order at creation. The realized variant replaces the budgeted blank cost with a delivered-cost average over the denomination's `DELIVERED` lots only and is finalized when an order reaches `FULFILLED`. Sections 3.1 and 3.3 carry both formulas.

Blank stock is reconciled as an invariant on every blank-affecting transition — lot receipt, run start, inspection resolution, and run cancellation. For each denomination, the pieces on hand (`blank_stock_pieces`), plus the pieces reserved by runs currently in `STRIKING` or `INSPECTION`, plus all pieces produced across its runs, plus all pieces scrapped across its runs, must equal the total pieces delivered by its `DELIVERED` lots. The invariant holds regardless of the age of the lots and runs involved.

Computed reports are read through a single parameterized endpoint whose `report_type` path variable selects the report. The seigniorage report carries one row per denomination with `budgeted_seigniorage_cents` summed over non-cancelled orders' creation-time snapshots, `realized_seigniorage_cents` summed over `FULFILLED` orders, and the reconciliation figures `blanks_on_hand_pieces`, `blanks_reserved_pieces`, `blanks_produced_pieces`, `blanks_scrapped_pieces`, and `blanks_delivered_pieces`; optional `fiscal_year` and `denomination_code` query parameters narrow the rows. The metal-exposure report carries one row per commodity with an integer-cents `exposure_cents` under a `variant` parameter — `mark_to_market` by default or `budget_variance` — and an optional `commodity` filter; §3.2 defines both variants.

### 2.10 Segregation of Duties

Three operations separate the actor from an earlier participant, and all three reject a violation with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Surcharge disbursement must be performed by a `FinanceOfficer` whose `X-User-ID` differs from the program's recorded `created_by_user_id`. Allocation settlement must be performed by a `FinanceOfficer` whose `X-User-ID` differs from the allocation's recorded `offered_by_user_id`. Error-coin destruction requires two certifiers — `primary_certifier_user_id` and `secondary_certifier_user_id` — whose ids differ from each other, and neither may equal the case's `reported_by_user_id`.

## 3. Business Logic & Workflows

### 3.1 Denomination Configuration and Federal Reserve Order Intake

Before any coin can be planned, a `PlatformAdmin` configures a denomination: its `code` (unique across denominations — a duplicate is rejected with `ERR_DENOMINATION_EXISTS`, 409), `face_value_cents` of at least 1, the `blank_budget_cost_cents` budgeted per planchet, the `striking_cost_cents` of labor and overhead per piece, and `blanks_per_tonne`, the number of blank pieces one metric tonne of delivered metal yields for that denomination. From those inputs the platform derives `budgeted_unit_seigniorage_cents` — the face value minus the budgeted blank cost minus the striking cost — and initializes `blank_stock_pieces` to 0.

A `FedLiaison` then submits the government's coin orders. Each order carries its `fiscal_year`, a `denomination_code` that must match an existing denomination (`ERR_UNKNOWN_DENOMINATION`, 422, otherwise), a `quantity_ordered_pieces` strictly greater than zero (`ERR_QUANTITY_INVALID`, 400), and a required `due_date`. Newly submitted orders sit in `SUBMITTED`, and at creation the platform snapshots `budgeted_seigniorage_cents` as `quantity_ordered_pieces` multiplied by the denomination's current `budgeted_unit_seigniorage_cents`.

An order's lifecycle is system-driven except for cancellation. Creating the first production run against an order moves it `SUBMITTED → SCHEDULED`; the first linked run to begin striking moves it `SCHEDULED → FULFILLING`. Each transition increments the order's `version`. As runs complete, the order's `quantity_fulfilled_pieces` accumulates the `produced_pieces` of its `COMPLETED` linked runs. When a completing run pushes the fulfilled count to at least the ordered quantity, the order auto-transitions `FULFILLING → FULFILLED` and finalizes its `realized_seigniorage_cents`: the platform computes the denomination's realized unit blank cost by dividing the summed `realized_cost_cents` of that denomination's `DELIVERED` lots by the summed `blanks_produced` of those same lots, rounding the quotient half-up to 2 decimal places; it then subtracts that unit cost and the denomination's `striking_cost_cents` from `face_value_cents`, rounds the resulting unit margin half-up to 2 decimal places, and only then multiplies by `quantity_ordered_pieces`. Rounding the unit margin before multiplying is pinned; rounding after multiplication is a rejected order of operations. Lots still in `ORDERED` never enter the average. If instead every linked run of a `SCHEDULED` or `FULFILLING` order has reached a terminal state — `COMPLETED` or `CANCELLED`, with at least one linked run existing — and the fulfilled count still falls short of the ordered quantity, the order auto-transitions to `SHORTFALL_RECORDED`, again incrementing `version`.

Cancellation is the one manual branch. A `FedLiaison` may cancel an order in `SUBMITTED` or `SCHEDULED`; cancelling a `SCHEDULED` order cascades, moving every linked run still in `PLANNED` or `REWORK` to `CANCELLED` and incrementing each such run's own `version`. Because blank reservation happens only when a run starts striking, runs in those two states hold no reserved blanks, so no pieces return to the denomination's stock on a cascade cancel. An order in `FULFILLING`, `FULFILLED`, `SHORTFALL_RECORDED`, or `CANCELLED` cannot be cancelled; the attempt is rejected with `ERR_FEDORDER_NOT_CANCELLABLE` (422). `FULFILLED`, `SHORTFALL_RECORDED`, and `CANCELLED` are the order's terminal states.

### 3.2 Metal Procurement, Hedging, and Vault Receipt

A `ProcurementOfficer` buys metal by creating a procurement lot: a `commodity` of `COPPER`, `NICKEL`, `ZINC`, `GOLD`, `SILVER`, or `PLATINUM`; a `denomination_code` naming the denomination these blanks will feed (`ERR_UNKNOWN_DENOMINATION`, 422, if it matches nothing); a strictly positive `quantity_tonnes`; a `budget_price_cents_per_tonne` budget reference; optionally a `locked_unit_price_cents_per_tonne` for a hedged lot — its absence means the lot rides the spot market; a destination `vault` of `WEST_POINT`, `FORT_KNOX`, or `DENVER_VAULT`; and a `planned_delivery_date` that is metadata only and drives no transition. Creating a lot requires a current spot price for the commodity established through the clock operation; without one the create is rejected with `ERR_SPOT_PRICE_MISSING` (422), hedged lots included, because the platform records `order_spot_cents_per_tonne` from the spot price at creation time regardless of any lock. The lot's `blanks_produced` is computed immediately as `quantity_tonnes` multiplied by the denomination's `blanks_per_tonne`, and the lot sits in `ORDERED`.

Receipt is recorded per lot and is the lot's only transition. Receiving moves the lot `ORDERED → DELIVERED` (receiving a lot not in `ORDERED` is rejected with `ERR_LOT_NOT_RECEIVABLE`, 422), fixes `realized_cost_cents` as `quantity_tonnes` multiplied by the locked unit price when one is present or by the commodity's current spot price per tonne at delivery time when the lot is unhedged, and credits the denomination's `blank_stock_pieces` by the lot's `blanks_produced`, incrementing the denomination's `version`. Vaults impose a daily receiving cap: the sum of `quantity_tonnes` over lots delivered at the same vault on the same UTC date — per the logical clock — plus the arriving lot's tonnage must not exceed 50 tonnes, and a receipt that would break the cap is rejected with `ERR_VAULT_CAPACITY_EXCEEDED` (422).

Commodity exposure is reported only for unhedged lots — those whose `locked_unit_price_cents_per_tonne` is absent — in either `ORDERED` or `DELIVERED` status, grouped by `commodity`. The metal-exposure report supports two variants. The default variant, `mark_to_market`, measures drift since each order was placed: for every exposed lot, its `quantity_tonnes` multiplied by the difference between the commodity's current spot price and the lot's `order_spot_cents_per_tonne`, summed per commodity into an integer-cents `exposure_cents`. The `budget_variance` variant measures drift against the budget reference: the same tonnage multiplied by the difference between the current spot price and the lot's `budget_price_cents_per_tonne`. Because tonnage and per-tonne prices are integers, both variants are exact integer-cent figures, and they differ whenever a lot's order-time spot differs from its budget price. Hedged lots are excluded from both variants.

### 3.3 Striking Operations: Scheduling, Press Windows, Inspection, and Rework

A `ProductionPlanner` schedules a production run by naming its parent order through `fed_order_id`, choosing a `facility` of `PHILADELPHIA` or `DENVER`, naming a `press_line` within the facility, fixing a `planned_start` and `planned_end` window, and committing a strictly positive `planned_quantity`. The press line is a real resource: no two runs in non-terminal states on the same facility and press line may occupy overlapping windows, where overlap is judged on half-open intervals — an existing run's `planned_start` falling before the new run's `planned_end` while the new run's `planned_start` falls before the existing run's `planned_end`. Runs that merely touch, one ending exactly when the other begins, do not overlap and both are accepted. A window whose `planned_end` is not after its `planned_start`, or any genuine overlap with a non-terminal run, is rejected with `ERR_PRESS_WINDOW_OVERLAP` (409). Runs inherit their denomination from their parent order rather than naming one themselves; a run whose order's denomination cannot be resolved is rejected with `ERR_UNKNOWN_DENOMINATION` (422). New runs sit in `PLANNED`, and the first run created against a `SUBMITTED` order moves the order to `SCHEDULED` as described in §3.1. Planners, inspectors, liaisons, and directors browse runs through a list that accepts optional `fed_order_id`, `facility`, `status`, and `denomination_code` filters.

Starting a run — from `PLANNED`, or from `REWORK` after a failed inspection — is a `ProductionPlanner` action gated by three preconditions. The linked order must be in `SCHEDULED` or `FULFILLING`; starting a run that is not in `PLANNED` or `REWORK`, or whose order sits in any other state, is rejected with `ERR_RUN_NOT_STARTABLE` (422). The denomination's `blank_stock_pieces` must be at least the run's `planned_quantity` (`ERR_BLANKS_INSUFFICIENT`, 422). And the denomination's trailing quality record must be clean: over the window from 30 days before the current logical-clock instant up to that instant, the platform sums the `error_pieces` of every error-coin case raised against runs of this denomination whose case was created inside the window, and sums the `produced_pieces` plus `scrapped_pieces` of every run of this denomination whose inspection completed inside the window; if any pieces were struck at all and the ratio of error pieces to struck pieces is at least 0.02 — exactly 0.02 breaches the gate, while anything strictly below it passes — the start is rejected with `ERR_QUALITY_THRESHOLD_BREACH` (422). A successful start debits `blank_stock_pieces` by `planned_quantity`, sets the run's `reserved_blanks` to `planned_quantity`, increments both the run's and the denomination's `version`, and — when the linked order is still `SCHEDULED` — moves the order to `FULFILLING`. A reworked start consumes a fresh, full reservation from stock; pieces already scrapped stay scrapped.

Inspection resolves a striking run inside a single `QualityInspector` action carrying an `outcome`; `INSPECTION` is entered and left within that call and is never persisted as a resting state, and inspecting a run that is not in `STRIKING` is rejected with `ERR_RUN_NOT_INSPECTABLE` (422). On `outcome=PASS` the inspector supplies `good_pieces` between 0 and the run's `reserved_blanks` inclusive — any other value is rejected with `ERR_INVALID_REQUEST` (400) — and the run's `produced_pieces` becomes `good_pieces`, its `scrapped_pieces` becomes the reserved count minus the good pieces, `reserved_blanks` zeroes out, and the run lands in `COMPLETED`. The linked order then absorbs the produced pieces into `quantity_fulfilled_pieces` and, as §3.1 describes, auto-transitions to `FULFILLED` with realized seigniorage finalized when the order is fully satisfied, or to `SHORTFALL_RECORDED` when every linked run is terminal and the fulfilled count remains short. On `outcome=FAIL` the entire reservation is lost: `scrapped_pieces` grows by the reserved count, `reserved_blanks` zeroes out, `rework_count` increments by one, and the run returns to `REWORK`, from which a planner may start it again with a fresh reservation once stock and quality gates permit.

A planner may cancel a run in `PLANNED` or `REWORK`; cancelling one in `STRIKING`, `COMPLETED`, or `CANCELLED` is rejected with `ERR_RUN_NOT_CANCELLABLE` (422). Runs in `PLANNED` or `REWORK` hold no reserved blanks, so cancellation returns nothing to stock. If a cancellation leaves the linked order with all of its runs terminal and a fulfilled count below the ordered quantity, the order auto-transitions to `SHORTFALL_RECORDED`. `COMPLETED` and `CANCELLED` are the run's terminal states.

### 3.4 Error Coin Quarantine and Certified Destruction

When striking output reveals mint errors, a `QualityInspector` opens an error-coin case against the offending production run, supplying the `production_run_id`, an `error_pieces` count that is strictly positive and no greater than that run's `scrapped_pieces` at the moment of creation — a larger count is rejected with `ERR_ERRORCOIN_QUANTITY_EXCEEDS` (422) — and an optional `description` such as an off-center strike or a doubled die. The platform records `reported_by_user_id` from the reporting inspector's `X-User-ID`, and the case sits in `QUARANTINED`. Open cases are the numerator of the denomination error-rate gate described in §3.3, and a run's cases can be listed with an optional `status` filter.

Destruction is a certified, two-person act. A `DestructionCertifier` destroys a quarantined case by supplying a `primary_certifier_user_id` and a `secondary_certifier_user_id`; the two ids must differ from each other, and neither may equal the case's `reported_by_user_id` — any overlap is rejected with `ERR_SEGREGATION_OF_DUTIES` (422). A successful destruction records both ids in `destroyed_by_user_ids` and moves the case to its terminal `DESTROYED` state. Attempting destruction on a case already in `DESTROYED` is rejected with `ERR_CASE_ALREADY_DESTROYED` (422).

### 3.5 Commemorative Programs: From Statute to Surcharge Disbursement

A `ProgramManager` opens a commemorative program — always backed by legislation — with a `name`, the authorizing `statute_reference` citation, the statutory `max_mintage_legal` ceiling across all of the program's products (strictly positive), a `surcharge_cents_per_unit` owed to the beneficiary on each unit sold (zero or more), the `beneficiary_name` organization, a statutory `beneficiary_cap_cents` bounding total surcharge disbursement (zero or more), the program's `direct_costs_cents` (zero or more), and the statutory sales window from `sales_window_start` to `sales_window_end`, which must end after it begins — a malformed window is rejected with `ERR_INVALID_REQUEST` (400). The creating user's id is recorded as `created_by_user_id`, and the program enters `DESIGN_REVIEW` with `design_revision_count` at zero.

Design authority rests with the `MintDirector`, whose `decision` either approves the design — moving the program `DESIGN_REVIEW → APPROVED_FOR_SALE` — or requests revisions, a deliberate self-loop that keeps the program in `DESIGN_REVIEW` while incrementing `design_revision_count` for legislation-driven redesign cycles. Either decision increments the program's `version`, and invoking the decision on a program no longer in `DESIGN_REVIEW` falls back to `ERR_INVALID_STATE_TRANSITION` (422).

From there the logical clock drives the sales window. When a clock-set sweep finds the clock at or past `sales_window_start`, an `APPROVED_FOR_SALE` program moves to `ON_SALE` and, in the same sweep, each of the program's products still in `SCHEDULED` whose `release_datetime` has been reached also moves to `ON_SALE`. When a sweep finds the clock at or past `sales_window_end`, an `ON_SALE` program moves to `SALES_CLOSED`. Both sweeps increment the program's `version`.

While the program sells, three computed fields track its finances. `gross_receipts_cents` sums, over all `PAID` orders of products belonging to the program, each order's quantity multiplied by its product's `price_cents`. `surcharge_accrued_cents` multiplies the total paid units across those products by `surcharge_cents_per_unit`; it is computed separately and is not net of the administrative fee. `net_proceeds_cents` follows a pinned evaluation order: first the base is `gross_receipts_cents` minus `direct_costs_cents`; then the administrative fee is that base multiplied by five percent, rounded half-up to whole cents; then net proceeds are the base minus the fee.

After the window closes, a `FinanceOfficer` disburses the surcharge. Disbursement requires the program to be in `SALES_CLOSED` — any other state is rejected with `ERR_PROGRAM_NOT_DISBURSABLE` (422) — and the officer's `X-User-ID` must differ from the program's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 422, per §2.10). The disbursed amount is the smaller of `beneficiary_cap_cents` and `surcharge_accrued_cents` — when the two are equal, the cap is paid exactly — and is recorded in `disbursed_cents` as the program moves to its terminal `SURCHARGE_DISBURSED` state, incrementing `version` one last time.

### 3.6 The Product Catalog, Release Calendar, and Collector Order Flow

A `ProgramManager` builds the numismatic catalog. Each product carries a unique `product_code` (a collision is rejected with `ERR_PRODUCT_CODE_EXISTS`, 409), an optional `program_id` that must resolve to a real program when supplied (`ERR_UNKNOWN_PROGRAM`, 422) and stays null for non-commemorative products, a `product_family` grouping releases on the calendar, a `product_type` of `PROOF_SET`, `COMMEMORATIVE`, `UNCIRCULATED`, or `SUBSCRIPTION_SERIES`, a strictly positive `price_cents`, a strictly positive `mintage_limit` bounding sellable units, a strictly positive `household_order_limit` bounding per-household accumulation, a scheduled `release_datetime`, and a `subscription_eligible` flag defaulting to false when omitted. Two creation-time rules protect the calendar and the statute. Releases within a family must stand at least 24 hours apart: a new `release_datetime` less than 24 hours away from any non-`WITHDRAWN` product in the same `product_family` is rejected with `ERR_RELEASE_GAP_VIOLATION` (409), while a gap of exactly 24 hours passes. And when the product belongs to a program, the sum of `mintage_limit` over the program's products must stay at or below `max_mintage_legal`; exceeding it is rejected with `ERR_PROGRAM_MINTAGE_EXCEEDED` (422). Products are created in `SCHEDULED`, and the catalog list accepts optional `program_id`, `status`, and `product_family` filters.

Release itself is clockwork. When a clock-set sweep finds the logical clock at or past a `SCHEDULED` product's `release_datetime`, the product moves to `ON_SALE` — unless it belongs to a program that is not yet `ON_SALE`, in which case it waits in `SCHEDULED` until the program opens. Thereafter allocation drives the lifecycle: when `allocated_units` reaches `mintage_limit` exactly, whether through a new allocation or a waitlist promotion, the product auto-transitions `ON_SALE → SOLD_OUT`; when a cancellation pulls `allocated_units` back below the limit, the product returns `SOLD_OUT → ON_SALE`. `SOLD_OUT` is therefore a reversible state, and `remaining_units` is always the limit minus the allocated count. A `ProgramManager` may withdraw a product from `SCHEDULED`, `ON_SALE`, or `SOLD_OUT` — but never while any subscription in `ACTIVE` or `DUNNING` references it, and never once it is `WITHDRAWN`; both violations are rejected with `ERR_PRODUCT_NOT_WITHDRAWABLE` (422). Withdrawal cascades through the order book: every order of the product in `ALLOCATED` or `WAITLISTED` flips to `RELEASED`, which makes its derived status `CANCELLED`, and each such order already `PAID` is refunded to `REFUNDED`. Withdrawal runs no waitlist promotion, because the product is finished selling; `WITHDRAWN` is the product's only terminal state.

Collectors enter through open registration — the one operation `Anonymous` callers may invoke — supplying a `full_name`, an `email` unique across collectors (`ERR_EMAIL_EXISTS`, 409, on collision), and a `household_id` shared by every collector in the same household, the key over which household order limits aggregate.

Placing an order is a `Collector` action, and the platform sets the order's `collector_id` from the caller's `X-User-ID` rather than trusting the payload. The `product_id` must resolve to an existing product (`ERR_UNKNOWN_PRODUCT`, 422) that is in `ON_SALE` or `SOLD_OUT`; orders against `SCHEDULED` or `WITHDRAWN` products are rejected with `ERR_PRODUCT_NOT_ORDERABLE` (422). A sold-out product still accepts orders — they join its waitlist. The `quantity` must be at least 1 (`ERR_QUANTITY_INVALID`, 400). The household limit then aggregates: the platform sums the quantities of every non-`CANCELLED` order for this product placed by any collector sharing the caller's `household_id`, adds the new quantity, and accepts only while the total stays at or below the product's `household_order_limit` — reaching exactly the limit succeeds, while one unit beyond it fails with `ERR_HOUSEHOLD_LIMIT_EXCEEDED` (422). Finally the allocation waterfall runs against the product's current `allocated_units`: if the allocated count plus the order's quantity stays at or below `mintage_limit`, the whole order becomes `ALLOCATED` and `allocated_units` grows by the quantity — flipping the product to `SOLD_OUT` when the limit is met exactly — and otherwise the whole order becomes `WAITLISTED`, because partial fills are never performed. The order's `total_cents` is its `quantity` multiplied by the product's `price_cents`, its `payment_status` begins `UNPAID`, and the order list accepts optional `collector_id`, `product_id`, `allocation_status`, and `payment_status` filters.

Payment is exact-change only. Paying an order requires it to be `UNPAID` and `ALLOCATED` — a `WAITLISTED` or `RELEASED` order, or one whose payment was already made or refunded, is rejected with `ERR_ORDER_NOT_PAYABLE` (422) — and the tendered `amount_cents` must equal the order's `total_cents` to the cent (`ERR_PAYMENT_AMOUNT_MISMATCH`, 422). A successful payment moves `payment_status` to `PAID` and the derived status to `COMPLETED`.

Cancellation releases the order's claim. A collector may cancel an order that is `ALLOCATED` or `WAITLISTED`; cancelling one already `RELEASED` is rejected with `ERR_ORDER_NOT_CANCELLABLE` (422). Cancellation flips `allocation_status` to `RELEASED` — and therefore the derived status to `CANCELLED` — refunds a `PAID` order to `REFUNDED`, and, for an order that held allocated units, returns its quantity to the product's `remaining_units`, reopening a `SOLD_OUT` product to `ON_SALE` when the count dips below the limit. Released units immediately trigger waitlist promotion: the platform scans the product's `WAITLISTED` orders oldest first by `created_at`, ties broken by server receipt order, under strict head-of-line blocking — the earliest waiting order is promoted to `ALLOCATED` if its `quantity` fits the remaining units, growing `allocated_units` and possibly closing the product at `SOLD_OUT` again, and the scan repeats with the new earliest; the moment the earliest waiting order does not fit, promotion stops and no later order is considered, even one that would fit.

An order's `status` is never stored directly. It is derived from the two parallel dimensions the order actually carries: `CANCELLED` exactly when `allocation_status` is `RELEASED`; `COMPLETED` exactly when `payment_status` is `PAID` and `allocation_status` is `ALLOCATED`; and `ACTIVE` in every other combination.

### 3.7 Subscription Enrollment, Billing Cycles, and Dunning

Collectors enroll in recurring deliveries for products that allow it. Enrollment requires the `product_id` to resolve (`ERR_UNKNOWN_PRODUCT`, 422), the product to be in `ON_SALE` — any other state, `SOLD_OUT` included, is rejected with `ERR_PRODUCT_NOT_ORDERABLE` (422) — and `subscription_eligible` to be true (`ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT`, 422). One live subscription per pairing: if the collector already holds an `ACTIVE` or `DUNNING` subscription for the same product, enrollment is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (409). The request's `units_per_cycle` must be at least 1 (`ERR_QUANTITY_INVALID`, 400), and `frequency` is either `MONTHLY` or `QUARTERLY`. The platform sets the subscription's `collector_id` from the caller's `X-User-ID`, creates it `ACTIVE` with `cycles_billed` at zero, and initializes `next_billing_date` to the current logical-clock date. The subscription list accepts optional `collector_id`, `product_id`, and `status` filters, and a Collector reading a single subscription, or listing its invoices through the optional `status` filter, must own it.

Billing is driven by a `PlatformAdmin` running a billing cycle against a subscription. The request carries `expected_subscription_version` for optimistic concurrency (§2.6) and is gated twice: the subscription must be `ACTIVE` — running a cycle against a `DUNNING`, `CANCELLED`, or `CANCELLED_NONPAYMENT` subscription is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE` (422) — and the logical clock's date must have reached `next_billing_date`, with an early run rejected as `ERR_BILLING_NOT_DUE` (422). A successful run creates a new invoice in `PENDING` whose `subscription_id` ties it to the billed subscription, whose `period_index` is `cycles_billed` plus one, and whose `amount_cents` prices the cycle: the product's `price_cents` is discounted by the ten-percent subscriber discount and rounded half-up to whole cents per unit first, that per-unit net is then multiplied by `units_per_cycle`, and finally a shipping tier is added — 495 cents when the cycle ships at most 3 units, 895 cents when it ships 4 to 10 units, and free shipping at 11 units or more. The rounding order is pinned: the discount is applied and rounded per unit before multiplication, and rounding after multiplication is a rejected order of operations. The cycle then advances `next_billing_date` by one month for `MONTHLY` or three months for `QUARTERLY`, increments `cycles_billed` by one, increments the subscription's `version`, and returns the created invoice.

Invoice payment attempts come from the subscribing collector — the caller's `X-User-ID` must equal the subscription's `collector_id` (`ERR_FORBIDDEN_OWNERSHIP`, 403) — and carry an `outcome`. Every attempt, success or failure, increments the invoice's `attempts` by one. On a `PENDING` invoice, `SUCCEEDED` moves it to `PAID`; `FAILED` moves it to `FAILED`, and that first failed attempt drops the subscription from `ACTIVE` into `DUNNING`. On a `FAILED` invoice the same two outcomes apply so long as `attempts` is still below 3: `SUCCEEDED` pays the invoice and lifts the subscription back to `ACTIVE`, while `FAILED` leaves the invoice `FAILED` — a second failure while the subscription is already in `DUNNING` leaves it in `DUNNING` — and when the failed attempt being recorded is the third, the invoice is written off to `WRITTEN_OFF` and the subscription moves to `CANCELLED_NONPAYMENT`. A subscription in `DUNNING` whose failed invoice is subsequently paid returns to `ACTIVE`. Paying a `PAID` or `WRITTEN_OFF` invoice, or attempting payment on a `FAILED` invoice already at 3 attempts, is rejected with `ERR_INVOICE_NOT_PAYABLE` (422).

Collectors may cancel an `ACTIVE` or `DUNNING` subscription at any time, moving it to `CANCELLED`. Both `CANCELLED` and `CANCELLED_NONPAYMENT` are terminal; cancelling a subscription already in a terminal state falls back to `ERR_INVALID_STATE_TRANSITION` (422).

### 3.8 Bullion Issues, Authorized Purchasers, and Allocation Settlement

The bullion program sells metal at spot-plus-premium to a closed network. A `ProgramManager` creates an issue with a `name`, a `metal` of `GOLD`, `SILVER`, or `PLATINUM`, a strictly positive `unit_weight_oz` in troy ounces, a strictly positive `total_pool_units`, and a strictly positive `offer_window_hours` bounding how long an offer stays open. Issues begin `ACTIVE` with `remaining_pool_units` equal to the full pool, and the remaining pool excludes every unit held in an `OFFERED`, `CONFIRMED`, or `SETTLED` allocation. When the remaining pool reaches zero and no allocation of the issue is still `OFFERED`, the issue auto-transitions `ACTIVE → SOLD_OUT`; when a later expiry restores units to the pool, the issue returns `SOLD_OUT → ACTIVE`. Both transitions increment the issue's `version`, and neither state is absorbing — the pool cycles with offers, settlements, and expiries.

A `PlatformAdmin` registers each authorized purchaser with a firm `name` and a `tier` of `T1`, `T2`, or `T3` that drives the premium schedule; purchasers begin `APPROVED`. A `MintDirector` manages standing through set-status transitions carrying a `to_status`: `APPROVED ↔ SUSPENDED` in both directions, and `APPROVED` or `SUSPENDED` to `TERMINATED`, which is terminal. Any requested transition outside that declared set falls back to `ERR_INVALID_STATE_TRANSITION` (422).

Offering an allocation is a `ProgramManager` action against a specific issue, whose `id` the allocation records as its `bullion_issue_id`. The request names an `authorized_purchaser_id` — the firm must exist and be in `APPROVED`, otherwise `ERR_AP_NOT_APPROVED` (422) — a `quantity_units` of at least 1 (`ERR_QUANTITY_INVALID`, 400) that does not exceed the issue's `remaining_pool_units` (`ERR_POOL_INSUFFICIENT`, 422), and the OCC field `expected_bullion_issue_version` described in §2.6. Because a `SOLD_OUT` issue's remaining pool is zero, offers against it fail the pool check directly. A created offer decrements the issue's `remaining_pool_units` by the offered quantity, increments the issue's `version`, records `offered_by_user_id` from the manager's `X-User-ID`, fixes `offer_expires_at` as the current logical-clock instant plus the issue's `offer_window_hours`, and sits in `OFFERED` with `total_price_cents` still null. The allocation list accepts optional `bullion_issue_id`, `authorized_purchaser_id`, and `status` filters.

Confirmation belongs to the offered firm. A `BullionDealer` confirms an allocation still in `OFFERED` — anything else is rejected with `ERR_ALLOCATION_NOT_CONFIRMABLE` (422) — with the caller's `X-User-ID` equal to the allocation's `authorized_purchaser_id` (`ERR_FORBIDDEN_OWNERSHIP`, 403), with the firm still `APPROVED` (`ERR_AP_NOT_APPROVED`, 422), and before `offer_expires_at`; because the clock sweep expires offers eagerly, a lapsed offer is already `EXPIRED` and fails the state check. Confirmation prices the allocation at spot plus premium. The total weight is `quantity_units` multiplied by the issue's `unit_weight_oz`. The premium in basis points combines a tier component — 300 basis points for `T1`, 450 for `T2`, and 625 for `T3` — with a size bracket: 200 basis points when the total weight is under 100 troy ounces, 100 basis points from 100 up to but not including 500 troy ounces, and zero at 500 troy ounces or more. The `total_price_cents` is then the total weight multiplied by the metal's current spot price in cents per troy ounce, multiplied by one plus the premium fraction (the premium basis points divided by ten thousand), with a single round-half-up to whole cents at the very end. Confirming while no current spot price exists for the metal is rejected with `ERR_SPOT_PRICE_MISSING` (422).

Settlement is the finance counterparty's step. A `FinanceOfficer` settles a `CONFIRMED` allocation — any other state is rejected with `ERR_ALLOCATION_NOT_SETTLABLE` (422) — and segregation of duties forbids the settler's `X-User-ID` from matching the allocation's `offered_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, 422). Settlement lands the allocation in its terminal `SETTLED` state and, when the remaining pool is zero with no `OFFERED` allocations left, flips the issue to `SOLD_OUT`.

Offers that lapse are reclaimed by the clock. When a clock-set sweep finds the logical clock at or past an `OFFERED` allocation's `offer_expires_at`, the allocation becomes `EXPIRED` — terminal — its `quantity_units` return to the issue's `remaining_pool_units`, an issue that had sold out returns to `ACTIVE`, and the issue's `version` increments.

## 4. Endpoint Definitions

Resource-creating operations — denominations, Federal Reserve orders, procurement lots, production runs, commemorative programs, products, collectors, numismatic orders, subscriptions, billing cycles (each of which creates an invoice), bullion issues, authorized purchasers, bullion allocations, and error-coin cases — respond 201 on success and return the created resource. All other successful operations, whether reads or state-changing actions (cancel, receive, start, inspect, decide-design, disburse-surcharges, withdraw, pay, confirm, settle, destroy, set-status, and the clock set), respond 200 and return the affected resource. Request payloads, computed fields, and cascades are specified in §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock and optionally replace spot prices; sweeps all time-based auto-transitions | PlatformAdmin |
| POST | /mint/denominations | Create a denomination configuration | PlatformAdmin |
| POST | /mint/federal-reserve-orders | Submit a Federal Reserve coin order (created in SUBMITTED) | FedLiaison |
| GET | /mint/federal-reserve-orders/{id} | Read a Federal Reserve order | FedLiaison, ProductionPlanner, MintDirector, FinanceOfficer, PlatformAdmin |
| POST | /mint/federal-reserve-orders/{id}/cancel | Cancel an order in SUBMITTED or SCHEDULED; cascades cancellation to linked non-terminal runs | FedLiaison |
| POST | /mint/metal-procurement-lots | Create a metal procurement lot (created in ORDERED); requires a current spot price for the commodity | ProcurementOfficer |
| GET | /mint/metal-procurement-lots/{id} | Read a metal procurement lot | ProcurementOfficer, ProductionPlanner, FinanceOfficer, MintDirector, PlatformAdmin |
| POST | /mint/metal-procurement-lots/{id}/receive | Record delivery of a lot at its vault; enforces vault daily capacity and credits denomination blank stock | ProcurementOfficer |
| POST | /mint/production-runs | Schedule a production run (created PLANNED); enforces the press-window half-open overlap rule | ProductionPlanner |
| GET | /mint/production-runs | List production runs with optional filters | ProductionPlanner, QualityInspector, FedLiaison, MintDirector, PlatformAdmin |
| GET | /mint/production-runs/{id} | Read a production run | ProductionPlanner, QualityInspector, FedLiaison, MintDirector, PlatformAdmin |
| POST | /mint/production-runs/{id}/start | Start striking from PLANNED or REWORK; reserves blanks from denomination stock | ProductionPlanner |
| POST | /mint/production-runs/{id}/inspect | Inspect a STRIKING run; PASS completes it, FAIL returns it to REWORK | QualityInspector |
| POST | /mint/production-runs/{id}/cancel | Cancel a run in PLANNED or REWORK | ProductionPlanner |
| POST | /mint/commemorative-programs | Create a commemorative program authorized by legislation (created in DESIGN_REVIEW) | ProgramManager |
| GET | /mint/commemorative-programs/{id} | Read a program including its computed financial fields | ProgramManager, MintDirector, FinanceOfficer, PlatformAdmin |
| POST | /mint/commemorative-programs/{id}/decide-design | Record a design decision: APPROVED advances, REVISION_REQUESTED loops in review | MintDirector |
| POST | /mint/commemorative-programs/{id}/disburse-surcharges | Disburse accrued surcharges to the statutory beneficiary | FinanceOfficer |
| POST | /mint/products | Create a numismatic product (created in SCHEDULED); enforces the family release gap and program mintage ceiling | ProgramManager |
| GET | /mint/products | List products (catalog browse) with optional filters | Collector, ProgramManager, MintDirector, FinanceOfficer, PlatformAdmin |
| GET | /mint/products/{id} | Read a product | Collector, ProgramManager, MintDirector, FinanceOfficer, PlatformAdmin |
| POST | /mint/products/{id}/withdraw | Withdraw a product; cascades cancellation and refunds to its non-released orders | ProgramManager |
| POST | /mint/collectors | Register a collector | Anonymous |
| POST | /mint/orders | Place a numismatic order; household limit enforced; whole order allocates or waitlists | Collector |
| GET | /mint/orders | List orders with optional filters; Collector callers must pass their own collector_id | Collector, ProgramManager, MintDirector, PlatformAdmin |
| GET | /mint/orders/{id} | Read an order (Collector callers: own orders only) | Collector, ProgramManager, MintDirector, PlatformAdmin |
| POST | /mint/orders/{id}/pay | Pay an order (UNPAID and ALLOCATED only); amount must equal total_cents exactly | Collector |
| POST | /mint/orders/{id}/cancel | Cancel an order (ALLOCATED or WAITLISTED); releases units, refunds if PAID, runs waitlist promotion | Collector |
| POST | /mint/subscriptions | Enroll in a subscription for a subscription-eligible ON_SALE product | Collector |
| GET | /mint/subscriptions | List subscriptions with optional filters; Collector callers must pass their own collector_id | Collector, ProgramManager, PlatformAdmin |
| GET | /mint/subscriptions/{id} | Read a subscription (Collector callers: own only) | Collector, ProgramManager, PlatformAdmin |
| POST | /mint/subscriptions/{id}/cancel | Cancel an ACTIVE or DUNNING subscription | Collector |
| POST | /mint/subscriptions/{id}/billing-cycle | Run the billing cycle when due; creates the PENDING invoice and advances next_billing_date; OCC-guarded | PlatformAdmin |
| GET | /mint/subscriptions/{id}/invoices | List invoices of a subscription with optional status filter (Collector callers: own only) | Collector, ProgramManager, PlatformAdmin |
| POST | /mint/subscription-invoices/{id}/pay | Attempt payment of an invoice (PENDING, or FAILED with attempts below 3) | Collector |
| POST | /mint/bullion-issues | Create a bullion issue with a total unit pool (created ACTIVE) | ProgramManager |
| GET | /mint/bullion-issues/{id} | Read a bullion issue | ProgramManager, BullionDealer, FinanceOfficer, MintDirector, PlatformAdmin |
| POST | /mint/authorized-purchasers | Register an authorized purchaser (created APPROVED) | PlatformAdmin |
| POST | /mint/authorized-purchasers/{id}/set-status | Transition an authorized purchaser between APPROVED, SUSPENDED, and TERMINATED | MintDirector |
| POST | /mint/bullion-issues/{id}/allocations | Offer an allocation to an APPROVED authorized purchaser; decrements the pool; OCC-guarded | ProgramManager |
| GET | /mint/allocations | List bullion allocations with optional filters | ProgramManager, BullionDealer, FinanceOfficer, MintDirector, PlatformAdmin |
| GET | /mint/allocations/{id} | Read a bullion allocation | ProgramManager, BullionDealer, FinanceOfficer, MintDirector, PlatformAdmin |
| POST | /mint/allocations/{id}/confirm | Authorized purchaser confirms an OFFERED allocation before expiry; computes the settlement price | BullionDealer |
| POST | /mint/allocations/{id}/settle | Settle a CONFIRMED allocation; settler must differ from the offering manager | FinanceOfficer |
| POST | /mint/error-coin-cases | Report an error-coin case against a production run (created QUARANTINED) | QualityInspector |
| GET | /mint/production-runs/{id}/error-coin-cases | List error-coin cases of a production run with optional status filter | QualityInspector, DestructionCertifier, ProductionPlanner, MintDirector, PlatformAdmin |
| POST | /mint/error-coin-cases/{id}/destroy | Certify destruction of a quarantined case with two distinct certifier ids | DestructionCertifier |
| GET | /mint/reports/{report_type} | Computed report: seigniorage per denomination, or metal-exposure per commodity under a variant | FinanceOfficer, ProductionPlanner, ProgramManager, MintDirector, PlatformAdmin, ProcurementOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API emits. Trigger conditions are specified in §2.7 and throughout §3, next to the workflows each error guards.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 422 |
| ERR_QUANTITY_INVALID | 400 |
| ERR_UNKNOWN_DENOMINATION | 422 |
| ERR_UNKNOWN_PROGRAM | 422 |
| ERR_UNKNOWN_PRODUCT | 422 |
| ERR_SPOT_PRICE_MISSING | 422 |
| ERR_AP_NOT_APPROVED | 422 |
| ERR_PRODUCT_NOT_ORDERABLE | 422 |
| ERR_ORDER_NOT_PAYABLE | 422 |
| ERR_ORDER_NOT_CANCELLABLE | 422 |
| ERR_RUN_NOT_STARTABLE | 422 |
| ERR_RUN_NOT_INSPECTABLE | 422 |
| ERR_RUN_NOT_CANCELLABLE | 422 |
| ERR_FEDORDER_NOT_CANCELLABLE | 422 |
| ERR_PROGRAM_NOT_DISBURSABLE | 422 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 422 |
| ERR_BILLING_NOT_DUE | 422 |
| ERR_INVOICE_NOT_PAYABLE | 422 |
| ERR_ALLOCATION_NOT_CONFIRMABLE | 422 |
| ERR_ALLOCATION_NOT_SETTLABLE | 422 |
| ERR_CASE_ALREADY_DESTROYED | 422 |
| ERR_LOT_NOT_RECEIVABLE | 422 |
| ERR_PRODUCT_NOT_WITHDRAWABLE | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_PRESS_WINDOW_OVERLAP | 409 |
| ERR_RELEASE_GAP_VIOLATION | 409 |
| ERR_VAULT_CAPACITY_EXCEEDED | 422 |
| ERR_CLOCK_REGRESSION | 422 |
| ERR_DENOMINATION_EXISTS | 409 |
| ERR_PRODUCT_CODE_EXISTS | 409 |
| ERR_EMAIL_EXISTS | 409 |
| ERR_DUPLICATE_SUBSCRIPTION | 409 |
| ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT | 422 |
| ERR_HOUSEHOLD_LIMIT_EXCEEDED | 422 |
| ERR_POOL_INSUFFICIENT | 422 |
| ERR_BLANKS_INSUFFICIENT | 422 |
| ERR_PROGRAM_MINTAGE_EXCEEDED | 422 |
| ERR_QUALITY_THRESHOLD_BREACH | 422 |
| ERR_ERRORCOIN_QUANTITY_EXCEEDS | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
