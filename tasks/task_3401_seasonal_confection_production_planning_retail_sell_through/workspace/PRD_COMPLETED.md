# Seasonal Confection Planning API — Product Requirements Document

## 1. Introduction

Seasonal confection is a business of hard deadlines and irreversible decisions. Four times a year the company runs a distinct seasonal program — Valentine's, Easter, Halloween, and Christmas — each built around molded shapes and themed packaging that cannot legally or commercially be sold outside its season. Production must be scheduled months ahead of the retail window, on shared manufacturing lines that also carry the everyday portfolio, so every seasonal run competes for line time and forces a changeover whenever a line switches between seasonal and everyday product. Ingredients are procured against a fixed retail price, which means cocoa and sugar contracts are booked per program-year and frequently hedged, and the landed cost of that procurement has to be known both provisionally (at booking) and finally (at settlement). Once the season ends, unsold seasonal stock is a liability: it must be marked down, diverted to a secondary channel, or destroyed, and brand-protected molded shapes may never leak into the secondary channel.

This document specifies the API that coordinates that entire lifecycle. The system collects retailer commitments during a bounded collection window, allocates the finite produced supply across confirmed commitments by retailer tier when production is known, ships through retailer-specific ship windows inside the program ship window, tracks weekly sell-through against each retailer's everyday baseline so that seasonal displays are not silently eating the core shelf, settles heat-damage claims for summer transit, and drives end-of-season disposition under segregation of duties. A single mid-season reorder per commitment is the only remedy for forecast error once allocation has run. Warehouse capacity is finite and temperature-controlled space is scarce; the system therefore tracks warehouse load as a first-class posture that can refuse inbound seasonal stock. Because the whole domain is window-driven, the server maintains a logical clock that every window and deadline rule reads, and test-driving clients may set it explicitly.

All endpoints are mounted under the `/confection` prefix. This document is the sole specification an implementer should need: structural contracts live in Section 2, business workflows in Section 3, the endpoint table in Section 4, and the error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the user acts. If either header is missing, or if the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but is not among the roles authorized for the target endpoint (see Section 4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system declares exactly six roles, spelled exactly as follows:

- `PlatformAdmin` — owns reference data and the program lifecycle: seasonal programs, products, warehouses, retailer accounts, commodity contracts and their settlement, program state advances, and the logical clock.
- `ProductionPlanner` — schedules production runs on lines and drives them through start, completion, and cancellation.
- `Retailer` — an entity-backed retail customer that creates and manages its own commitments, exercises the single mid-season reorder, files weekly sell-through reports, and files and supplements heat claims.
- `CategoryManager` — confirms submitted commitments, runs manual QA quarantine on lots, and proposes disposition orders; approval of a disposition order must be performed by a different `CategoryManager` user than the one who proposed it.
- `LogisticsCoordinator` — creates and delivers shipments and executes approved disposition orders.
- `ClaimsAdjuster` — decides heat claims and never files them, keeping claim adjudication segregated from claim filing.

Role identity is resolved as follows. When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `RetailerAccount`; ownership checks on any resource that references a `RetailerAccount` compare the resource's `retailer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This ownership rule guards commitment submission, revision, reorder, and cancellation, the provision of additional heat-claim evidence, and sell-through report creation, and it applies equally at commitment creation, where the request's `retailer_id` must equal `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `ProductionPlanner`, `CategoryManager`, `LogisticsCoordinator`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a disposition order records its proposing and approving `CategoryManager` operator identifiers in `proposed_by_user_id` and `approved_by_user_id` — but it does not compare the identifier to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the server's logical clock (Section 2.5), never from wall-clock time.
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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0. A negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List results are always sorted by `created_at` ascending. Ties on `created_at` break by creation order, earliest created first. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of resources matching the filters and `has_more` indicates whether resources remain beyond the returned page. List endpoints additionally accept the resource-specific filter parameters named in Section 3 and Section 4; an omitted filter parameter matches every value of that attribute.

### 2.4. Common Resource Properties

Every resource in the system — `SeasonalProgram`, `Product`, `ProductionRun`, `RetailerAccount`, `RetailerCommitment`, `Shipment`, `HeatClaim`, `Warehouse`, `InventoryLot`, `DispositionOrder`, `CommodityContract`, and `SellThroughReport` — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records the creation instant as an ISO 8601 UTC timestamp with three fractional digits. The `updated_at` timestamp is an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource. The `version` is an integer starting at 1 on creation and incremented by exactly 1 on every mutation, including system-driven mutations such as state advances, allocation, cascades, and computed-field updates that accompany a transition; reads never change `version`. All twelve entity kinds carry this full common set — no entity omits `updated_at` or `version`. Both `created_at` and `updated_at` are rendered from the logical clock (Section 2.5), never from wall-clock time. Each discrete write a workflow performs on an entity is its own mutation: an entity touched by several links of one cascade — for example a lot quarantined by the pull cascade's first link and then restored to by its third — increments `version` once per link. Client-supplied instant fields (program window dates, run schedules, commitment ship windows, `ship_on`, `week_of_on`) are stored and echoed in responses exactly as supplied.

### 2.5. The Logical Clock and the Seasonal Window Architecture

The server does not consult wall-clock time for any business rule. Instead it maintains a **logical clock** that every window, deadline, and schedule gate reads. On startup, before any client has set it, the logical clock is exactly `2026-09-01T00:00:00Z`; the clock must never silently fall back to wall-clock time. A `PlatformAdmin` may advance the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant — any valid instant is accepted, including one behind the current value — and responds with the resulting `current_utc`, rendered without fractional digits when the instant falls on a whole second and with three fractional digits otherwise; every rule phrased in this document as "the clock has reached" or "the clock is before" reads this logical clock.

A seasonal program is defined by an ordered chain of window instants, all supplied at creation: `commitment_open_on` (retailer commitment collection opens), `commitment_close_on` (collection closes), `production_deadline_on` (the latest allowed `scheduled_end_on` for seasonal production runs of the program), `ship_window_open_on` (the earliest `ship_on` for any shipment of the program), `ship_window_close_on` (the latest `ship_on`, inclusive), `on_shelf_on` (the retail on-shelf date at which sell-through reporting opens), `pull_on` (the mandatory pull date), and `destroy_by_on` (the instant after which only destruction dispositions may execute). The chain is strictly ordered as follows, and a program whose dates violate it is rejected at creation: `commitment_open_on` is earlier than `commitment_close_on`; `commitment_close_on` is no later than `production_deadline_on`; `production_deadline_on` is no later than `ship_window_open_on`; `ship_window_open_on` is earlier than `ship_window_close_on`; `ship_window_close_on` is no later than `on_shelf_on`; `on_shelf_on` is earlier than `pull_on`; and `pull_on` is earlier than `destroy_by_on`. Commitment submissions are accepted on the half-open interval from `commitment_open_on` inclusive up to but not including `commitment_close_on`.

A program also fixes the commercial terms of its season: `retail_price_cents` is the fixed retail price per unit charged for every product of the program and must be greater than zero, and `forecast_units` is the forecasted seasonal demand in units and must be greater than zero. The `season_code` is one of exactly `VALENTINES`, `EASTER`, `HALLOWEEN`, or `CHRISTMAS`, and `season_year` is the retail season year, which must be at least 2026. The pair of `season_code` and `season_year` is unique across programs; a second program for the same season and year is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409).

### 2.6. Monetary Precision, Rounding, and Ratio Conventions

All money in the system is integer cents. Fields such as `retail_price_cents`, `credit_balance_cents`, `credit_cents`, `recovered_value_cents`, `provisional_spend_cents`, and `effective_spend_cents` are whole-cent integers; wherever a computation would otherwise produce a fractional cent, the result is rounded half-up to a whole cent at the step the relevant Section 3 rule names. Unit counts (`committed_units`, `allocated_units`, `planned_units`, `produced_units`, `units`, `claimed_units`, and similar) are exact integers. Ratio scores — the two cannibalization variants on a sell-through report — are carried to exactly 4 decimal places, rounded half-up. Schedule instants are compared at second precision.

Two rounding disciplines are worth stating once because Section 3 relies on them everywhere. First, **round half-up** means a fraction of exactly one half rounds away from zero. Second, markdown recovery rounds **per unit first, then multiplies**: the per-unit price after markdown is rounded to whole cents before it is multiplied by the number of units, never the other way around, because the two orders yield different cents.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and no other endpoint accepts a version field.

The program-advance operation requires the request to carry `expected_program_version`, holding the `version` of the target `SeasonalProgram` as the caller last observed it. If another writer has advanced the program's `version` since the caller last read it, the advance is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from re-driving a transition — such as consuming the single reopen budget or re-running allocation — against a snapshot it has not observed. The transition's guard set (window clocks, allocation side effects, the reopen budget) is always evaluated against a single observed snapshot.

The commitment-revision operation requires the request to carry `expected_commitment_version`, holding the `version` of the target `RetailerCommitment` as the caller last observed it. Revision legitimately supersedes the current `SUBMITTED` revision with a new one; if the commitment's `version` has advanced since the caller last read it — for example because a prior revision already superseded it — the revise is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than forking a second successor.

Every other endpoint — including run completion, shipment creation, disposition execution, and contract settlement — performs no version negotiation and takes no expected-version input.

### 2.8. Validation Priority Order

A request that violates several rules at once receives exactly one error, and the winner is determined by a fixed priority order; a lower priority number wins. Syntactic request validation comes before all numbered priorities: a request with a missing required field, a wrong-typed value, an out-of-enum value, or a violated field constraint (for example an end instant not after its start instant, or a unit count of zero or less where a positive count is required) is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The numbered priorities then run in this order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the declared role is listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED`).
3. **Path existence** — identifiers in the URL path resolve to existing resources, validated left to right (so a program identifier is validated before a run identifier before a lot identifier). The first miss produces that entity's not-found error, one of `ERR_PROGRAM_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DISPOSITION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`, each at HTTP 404.
4. **Ownership** — for `Retailer`-scoped mutation endpoints, the acting retailer's `X-User-ID` equals the target resource's `retailer_id` (`ERR_OWNERSHIP_MISMATCH`).
5. **Body foreign keys** — identifiers carried in the request body resolve to existing resources, checked in the endpoint's declared input order (the matching `ERR_PRODUCT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, or `ERR_PROGRAM_NOT_FOUND`).
6. **Optimistic concurrency** — the expected-version field matches the entity's current `version` (`ERR_STALE_VERSION`).
7. **State-machine preconditions** — the target resource is in a state from which the requested transition is defined, plus the cross-entity state gates named in Section 3 (`ERR_INVALID_STATE`, `ERR_PROGRAM_NOT_OPEN`, `ERR_PROGRAM_REOPEN_EXHAUSTED`, `ERR_NO_PRODUCTION_SCHEDULED`, `ERR_UNDISPOSED_STOCK_REMAINS`); within this priority, the target resource's own transition validity is evaluated before any cross-entity state gate.
8. **Business safety** — brand protection, the auto-approved-claim rejection ban, and segregation of duties (`ERR_BRAND_PROTECTION`, `ERR_CLAIM_AUTO_APPROVED`, `ERR_SEGREGATION_OF_DUTIES`).
9. **Temporal windows** — advance clock gates, the commitment window, ship windows, report weeks, the production deadline, the destroy-by gate, and line scheduling (`ERR_PROGRAM_ADVANCE_TOO_EARLY`, `ERR_COMMITMENT_WINDOW_CLOSED`, `ERR_SHIP_WINDOW_VIOLATION`, `ERR_REPORT_WEEK_OUT_OF_WINDOW`, `ERR_PRODUCTION_DEADLINE_VIOLATION`, `ERR_DISPOSITION_WINDOW_CLOSED`, `ERR_LINE_SCHEDULE_OVERLAP`, `ERR_CHANGEOVER_VIOLATION`).
10. **Structural constraints** — uniqueness, product/program coherence, reorder eligibility, markdown range, claim and shipment aggregate caps, the cannibalization floor, hedge bounds, the retailer shelf cap, and quarantined-stock bounds (`ERR_DUPLICATE_RESOURCE`, `ERR_PRODUCT_PROGRAM_MISMATCH`, `ERR_REORDER_NOT_ALLOWED`, `ERR_MARKDOWN_OUT_OF_RANGE`, `ERR_CLAIM_EXCEEDS_SHIPMENT`, `ERR_SHIPMENT_EXCEEDS_ALLOCATION`, `ERR_CANNIBALIZATION_GUARD`, `ERR_HEDGE_EXCEEDS_QUANTITY`, `ERR_SHELF_CAP_EXCEEDED`, `ERR_DISPOSITION_EXCEEDS_QUARANTINE`).
11. **Capacity and pool gates, evaluated last** — warehouse fullness, the congested-warehouse seasonal block, shipment stock sufficiency, and reorder pool exhaustion (`ERR_WAREHOUSE_FULL`, `ERR_WAREHOUSE_CONGESTED_SEASONAL`, `ERR_INSUFFICIENT_STOCK`, `ERR_SUPPLY_POOL_EXHAUSTED`).

Because capacity and pool gates rank last, a request that is both malformed in business terms and impossible on capacity grounds always surfaces the business error first.

### 2.9. Warehouse Load and Posture

Every warehouse has a `capacity_units` (greater than zero) and a derived `posture` recomputed whenever lots are created, consumed, restored, quarantined, or released, and whenever a shipment draws stock. The load figures are: `in_use_units`, the sum of `units_on_hand` over the warehouse's lots in `AVAILABLE` or `QUARANTINED` status (lots in `DISPOSITIONED` or `DEPLETED` are excluded), and `quarantined_units`, the sum of `units_on_hand` over the warehouse's `QUARANTINED` lots only. Posture derives from `in_use_units` with inclusive boundaries: if `in_use_units` is at least `capacity_units`, posture is `FULL`; otherwise, if `in_use_units` is at least the floor of 85% of `capacity_units` (the congestion threshold is the constant 0.85, applied with a floor before comparison), posture is `CONGESTED`; otherwise posture is `OPEN`. Sitting exactly at the 85% floor is `CONGESTED`, not `OPEN`; sitting exactly at capacity is `FULL`, not `CONGESTED`. A warehouse is created with a `name`, a `temp_controlled` flag, and its `capacity_units`, starting with `in_use_units` 0, `quarantined_units` 0, and posture `OPEN`.

Posture is enforced, not merely reported. Completing a production run into a warehouse is rejected with `ERR_WAREHOUSE_FULL` (HTTP 409) when the warehouse's `in_use_units` plus the run's produced units would exceed `capacity_units`, or when the warehouse is already in `FULL` posture. A warehouse in `CONGESTED` posture refuses additional **seasonal** inbound lots — completing a seasonal run into it is rejected with `ERR_WAREHOUSE_CONGESTED_SEASONAL` (HTTP 409) — while everyday lots are still accepted, because the everyday business must keep flowing even when a warehouse is nearly full.

### 2.10. Production Line Scheduling Discipline

Production runs are scheduled against a free-form `line_code`, and every new run is checked against the other non-`CANCELLED` runs sharing that line; a cancelled run no longer participates in either check. Two checks run, **overlap first, then changeover**.

The overlap check treats each run's schedule as a half-open interval: a new run overlaps an existing run on the same line only when the existing run's `scheduled_start_on` is earlier than the new run's `scheduled_end_on` and, at the same time, the new run's `scheduled_start_on` is earlier than the existing run's `scheduled_end_on`. Any such intersection is rejected with `ERR_LINE_SCHEDULE_OVERLAP` (HTTP 409). Back-to-back scheduling — one run ending at exactly the instant the next begins — is not an overlap and is allowed.

The changeover check finds the **prior run**: the non-cancelled run on the same line whose `scheduled_end_on` is the greatest value not after the new run's `scheduled_start_on`. If a prior run exists and its product's kind differs from the new run's product's kind — a seasonal/everyday switch in either direction — the new run must start at least 8 hours after the prior run's `scheduled_end_on`; a changeover buffer shorter than that is rejected with `ERR_CHANGEOVER_VIOLATION` (HTTP 422). The 8-hour buffer is inclusive: a gap of exactly 8 hours passes. A same-kind succession requires no gap at all.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Season: Programs, Products, and Retailer Accounts

A season begins when a `PlatformAdmin` creates a `SeasonalProgram` carrying the full window chain described in Section 2.5 — `commitment_open_on`, `commitment_close_on`, `production_deadline_on`, `ship_window_open_on`, `ship_window_close_on`, `on_shelf_on`, `pull_on`, and `destroy_by_on` — together with `season_code`, `season_year`, `retail_price_cents`, and `forecast_units`. The program is born in `PLANNING` status with `reopen_count` 0, all computed totals (`produced_units_total`, `committed_units_total`, `shipped_units_total`, `disposed_units_total`) at 0, and `version` 1. From `PLANNING`, a `PlatformAdmin` advances the program to `OPEN_FOR_COMMITMENTS` once the window design is settled; the advance is a guarded write under the optimistic-concurrency rule of Section 2.7, so the request carries `expected_program_version`, and each successful advance increments the program's `version` by 1. A program may also be abandoned early: advancing from `PLANNING` to `CANCELLED`, or from `OPEN_FOR_COMMITMENTS` to `CANCELLED`, cancels every commitment of the program still in `DRAFT`, `SUBMITTED`, or `CONFIRMED` status as a cascade, and increments the program's `version` by 1. `CLOSED` and `CANCELLED` are the terminal program states; any advance attempted from a state where the requested target is not defined — including any transition out of a terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Products come in two kinds, declared at creation in the `kind` field as exactly `SEASONAL` or `EVERYDAY`. A `SEASONAL` product must name the `program_id` of the program it belongs to; an `EVERYDAY` product must carry a null `program_id`. Every product has a globally unique `sku_code` — a duplicate is rejected with `ERR_DUPLICATE_RESOURCE` — a free-form `molded_shape` name (a pumpkin, a heart, an egg, or the everyday standard bar), a positive `units_per_case`, and two flags that matter later: `brand_protected`, marking a branded molded shape that may never be diverted to the secondary channel, and `requires_temp_control`, marking heat-sensitive product whose summer shipments receive special claim treatment. Both flags are required booleans at creation. A `PlatformAdmin` creates products; anyone may read them, and the product list can be filtered by `program_id` and `kind`.

Retailer accounts are onboarded by a `PlatformAdmin` with a `name`, a sales `region`, an allocation `tier` of exactly `GOLD`, `SILVER`, or `BRONZE`, and two everyday-business protection numbers: `max_seasonal_units`, a positive cap on the retailer's total seasonal committed units across all programs, and `everyday_baseline_weekly_units`, a positive baseline weekly everyday-shelf velocity that later anchors the cannibalization index. Every account carries a `credit_balance_cents` ledger, starting at 0, onto which shortfall credits and approved heat-claim credits are posted.

### 3.2. Production Scheduling and Run Completion

A `ProductionPlanner` schedules a `ProductionRun` by naming a `product_id`, a `line_code`, a positive `planned_units`, and the half-open schedule interval from `scheduled_start_on` to `scheduled_end_on`; the end must be later than the start or the request is `ERR_INVALID_REQUEST`. A run for a seasonal product must name the `program_id` of that product's program, and a run for an everyday product must carry a null `program_id`; a mismatch is rejected with `ERR_PRODUCT_PROGRAM_MISMATCH` (HTTP 422). For the body-foreign-key resolution of Section 2.8 priority 5, run creation checks `program_id` first (when supplied) and then `product_id`. A seasonal run's `scheduled_end_on` must not fall after the program's `production_deadline_on`, or the create is rejected with `ERR_PRODUCTION_DEADLINE_VIOLATION` (HTTP 422). The line-discipline checks of Section 2.10 then run against the other non-`CANCELLED` runs on the same `line_code`, overlap before changeover. A created run is `SCHEDULED` with `produced_units` 0 and `version` 1. Runs can be listed with filters on `line_code`, `product_id`, `program_id`, `status`, and `completed_warehouse_id`.

Starting a run moves it from `SCHEDULED` to `IN_PROGRESS` and increments its `version` by 1. For a seasonal product, the program must be in `LOCKED` or `IN_PRODUCTION` status — production cannot begin while commitments are still being collected — or the start is rejected with `ERR_INVALID_STATE`. A `SCHEDULED` run may instead be cancelled, moving it to `CANCELLED` with a `version` increment; cancellation has no preconditions, and a cancelled run drops out of all future overlap and changeover checks.

Completing an `IN_PROGRESS` run is the moment supply enters the system. The planner reports the actual `produced_units` — a non-negative count; zero is accepted — and the `warehouse_id` that receives the lot. The named warehouse must exist (`ERR_WAREHOUSE_NOT_FOUND`), and the two capacity gates of Section 2.9 apply: overflow is `ERR_WAREHOUSE_FULL`, and completing a seasonal run into a `CONGESTED` warehouse is `ERR_WAREHOUSE_CONGESTED_SEASONAL`. On success the run becomes `COMPLETE`, `produced_units` is frozen — it is immutable afterwards — `completed_warehouse_id` is recorded, and the run's `version` increments. Completion cascades: it creates exactly one `InventoryLot` for the run, stamped with the run's `product_id`, the receiving `warehouse_id`, and the run's id as `production_run_id`, with `units_on_hand` equal to `produced_units` and status `AVAILABLE`; the lot's `lot_code` is assigned as `LOT-` followed by a six-digit zero-padded monotone sequence starting at `LOT-000001`, which also serves as the deterministic tie-break after `created_at` in every draw order. Completion then recomputes the warehouse's `in_use_units` and posture per Section 2.9, and — for seasonal runs only — refreshes the program's `produced_units_total`, the sum of `produced_units` over the program's `COMPLETE` runs.

A program leaves `LOCKED` for `IN_PRODUCTION` only when at least one non-`CANCELLED` production run exists for it; advancing otherwise is rejected with `ERR_NO_PRODUCTION_SCHEDULED` (HTTP 422). Like every advance, it carries `expected_program_version` and increments the program's `version` by 1.

### 3.3. Cocoa and Sugar Procurement with Hedging

Procurement is booked per program-year. A `PlatformAdmin` creates a `CommodityContract` naming the `program_id`, the `commodity` — exactly `COCOA` or `SUGAR` — a positive `quantity_units`, and a positive `contract_price_cents_per_unit`. A hedge is optional: `hedged_quantity_units` defaults to 0, may not exceed `quantity_units`, and whenever it is greater than zero a `hedge_price_cents_per_unit` strike must be supplied; a contract whose hedged quantity exceeds its contracted quantity, or that hedges without a strike price, is rejected with `ERR_HEDGE_EXCEEDS_QUANTITY` (HTTP 422). A negative `hedged_quantity_units`, a non-positive `hedge_price_cents_per_unit` supplied at booking, and a non-positive `spot_price_cents_per_unit` supplied at settlement are field-constraint violations rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The contract prices itself twice over its life, and the two variants price the identical contract against different reference prices. At creation — and on any read while the contract remains `OPEN` — the **provisional** landed cost `provisional_spend_cents` is the contracted quantity times the contract price, reduced by the hedged quantity times the amount by which the contract price exceeds the hedge strike, with that excess counted as zero when the strike is at or above the contract price. All operands are integers, so this figure is exact in cents. Settlement happens once: a `PlatformAdmin` settles an `OPEN` contract by supplying the market `spot_price_cents_per_unit`, moving it to `SETTLED` and computing the **final** landed cost `effective_spend_cents` as the contracted quantity times the spot price, reduced by the hedged quantity times the amount by which the spot price exceeds the hedge strike, again with a zero floor. The hedge therefore pays off only when the reference price exceeds the strike, and the provisional and final figures diverge exactly when the spot price differs from the contract price. Settlement increments the contract's `version` by 1. Contracts can be listed with filters on `program_id`, `commodity`, and `status`.

### 3.4. The Commitment Collection Window

While a program is `OPEN_FOR_COMMITMENTS`, a `Retailer` files commitments against it. Creating a `RetailerCommitment` names the `program_id`, the retailer's own `retailer_id` — which must equal the acting `X-User-ID` (`ERR_OWNERSHIP_MISMATCH`) — a `product_id` that must be a `SEASONAL` product belonging to that program (`ERR_PRODUCT_PROGRAM_MISMATCH`), a positive `committed_units`, and a retailer-specific ship window: `ship_window_open_on` no earlier than the program's `ship_window_open_on`, and `ship_window_close_on` no later than the program's `ship_window_close_on`, with violations rejected as `ERR_INVALID_REQUEST`; these program-relative bounds are evaluated once the named program has resolved (after the body foreign keys), ahead of the program-state gate. The program must be `OPEN_FOR_COMMITMENTS` at creation or the request fails with `ERR_PROGRAM_NOT_OPEN` (HTTP 409). A new commitment is a `DRAFT` with `allocated_units` 0, `reorder_units` 0, `reorder_used` false, `revision` 1, a null `supersedes_commitment_id`, and `version` 1. Commitments can be listed with filters on `program_id`, `retailer_id`, `product_id`, `status`, and `supersedes_commitment_id`.

Submitting moves a `DRAFT` commitment to `SUBMITTED` and increments its `version`. Submission is guarded three ways, in the priority order of Section 2.8: the acting retailer must own the commitment (`ERR_OWNERSHIP_MISMATCH`); the program must be `OPEN_FOR_COMMITMENTS` (`ERR_PROGRAM_NOT_OPEN`); and the logical clock must sit inside the half-open collection interval — at or after `commitment_open_on` and strictly before `commitment_close_on` — or the submit is rejected with `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422).

Confirmation is the house's move: a `CategoryManager` confirms a `SUBMITTED` commitment, moving it to `CONFIRMED`, recomputing the program's `committed_units_total` (the sum of `committed_units` over the program's commitments in `CONFIRMED`, `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status), and incrementing the commitment's `version`. Confirmation enforces the everyday-shelf cap: the sum of `committed_units` over all of the retailer's commitments in `SUBMITTED`, `CONFIRMED`, `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status — this commitment included — must not exceed the account's `max_seasonal_units`, or the confirm is rejected with `ERR_SHELF_CAP_EXCEEDED` (HTTP 422). Confirmation carries no program-state or clock gate; the `SUBMITTED` precondition and this shelf cap are its only guards.

A retailer that needs to change a live commitment uses revision, a create-with-supersede: the old `SUBMITTED` commitment becomes `SUPERSEDED` and its `version` increments, and a brand-new commitment is created in the same breath — same program, retailer, and product, the new `committed_units`, new ship-window bounds when supplied, `revision` one higher than the old row, `supersedes_commitment_id` pointing at the old commitment, status `SUBMITTED`, and `version` 1; because a new resource is created, revision returns the successor with HTTP 201. Revision is the second OCC-guarded write of Section 2.7: the request must carry `expected_commitment_version` matching the old commitment's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). Beyond ownership (`ERR_OWNERSHIP_MISMATCH`) and the OCC check, revision also requires the program to be `OPEN_FOR_COMMITMENTS` (`ERR_PROGRAM_NOT_OPEN`) and the logical clock to be strictly before `commitment_close_on` (`ERR_COMMITMENT_WINDOW_CLOSED`). The successor's effective ship window — supplied sides replacing, omitted sides carried over from the superseded row — is then re-validated against the same program-relative bounds as at creation, with violations rejected as `ERR_INVALID_REQUEST`.

Cancellation is the retailer's exit before allocation: a commitment in `DRAFT`, `SUBMITTED`, or `CONFIRMED` may be cancelled by its owning retailer, moving it to `CANCELLED` and incrementing its `version`; cancelling a `CONFIRMED` commitment additionally recomputes the program's `committed_units_total`. Once the collection window is over, a `PlatformAdmin` advances the program from `OPEN_FOR_COMMITMENTS` to `LOCKED`; this advance requires the logical clock to have reached `commitment_close_on`, and an early attempt is rejected with `ERR_PROGRAM_ADVANCE_TOO_EARLY` (HTTP 422). The lock is not quite irreversible: the program supports a single sanctioned reopen from `LOCKED` back to `OPEN_FOR_COMMITMENTS`, usable at most once — the reopen budget `MAX_REOPEN` is 1. The reopen increments `reopen_count` by 1 and the program's `version` by 1, and a second attempt, finding `reopen_count` already at the budget, is rejected with `ERR_PROGRAM_REOPEN_EXHAUSTED` (HTTP 422).

### 3.5. Allocation Day: The Supply Waterfall

Once production is real, a `PlatformAdmin` advances the program from `IN_PRODUCTION` to `SHIPPING`; the advance requires the logical clock to have reached `ship_window_open_on`, and an early attempt is rejected with `ERR_PROGRAM_ADVANCE_TOO_EARLY`. This advance is the system's allocation day: the moment it lands, the **supply waterfall** runs per seasonal product of the program, and it is a system cascade, not a per-committee decision.

For each `SEASONAL` product of the program, the pool is the sum of `produced_units` over that product's `COMPLETE` production runs. The eligible claimants are exactly that product's commitments in `CONFIRMED` status — commitments still in `DRAFT`, `SUBMITTED`, `SUPERSEDED`, or `CANCELLED` are excluded and receive nothing. Eligible commitments are sorted by retailer tier first, using the fixed rank order `GOLD` (rank 0), then `SILVER` (rank 1), then `BRONZE` (rank 2), and ties within a tier break by the commitment's `created_at`, earliest first. Walking that pinned order, each commitment is granted the smaller of its `committed_units` and the pool remaining at its turn, and the grant is written to its `allocated_units` as the pool drains. Commitments created at the same logical-clock instant are ordered by creation sequence, earliest created first. Per-product pools are independent, and within a product the tier-major, `created_at`-minor order is the only evaluation order.

A commitment granted its full `committed_units` becomes `ALLOCATED`. A commitment granted strictly less — including a grant of zero, which is a legal outcome — becomes `SHORTED`, and the house owes it a shortfall credit: the unmet units times the program's `retail_price_cents`, times the shortfall-credit rate of 0.10 (ten percent), rounded half-up to whole cents, posted onto the retailer account's `credit_balance_cents`. Both outcomes increment the commitment's `version` by 1, and when the waterfall finishes, the program's `committed_units_total` is recomputed and the program's `version` increments by 1 as the advance completes.

### 3.6. Shipping, Delivery, and the Mid-Season Reorder

With allocations fixed, a `LogisticsCoordinator` creates shipments against them. A shipment names a `commitment_id`, the `warehouse_id` whose stock it draws, a positive `units`, the `ship_on` instant, whether transport is `temp_controlled`, and — optionally — `temp_control_declined_by_retailer`, defaulting to false, which records that the retailer explicitly declined refrigerated transport and halves any later heat-claim payout. The `ship_on` must lie inside **both** the commitment's own ship window and the program's ship window — no earlier than either open date and no later than either close date, with close dates inclusive — or the create is rejected with `ERR_SHIP_WINDOW_VIOLATION` (HTTP 422). The cumulative `units` over the commitment's shipments in `PLANNED` or `DELIVERED` status, plus the new shipment's `units`, must not exceed the commitment's `allocated_units`, or the create is rejected with `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 422); a commitment with no allocation therefore cannot absorb any shipment at all.

Stock leaves the shelf first-expiring-first-out, realized here as lot age: the draw walks the warehouse's `AVAILABLE` lots of the shipment's product in `created_at` ascending order, breaking ties by `lot_code` ascending, decrementing each lot's `units_on_hand` until the shipment is covered. If the warehouse's available stock of the product falls short of the request, the create is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). A lot whose `units_on_hand` reaches zero through a draw becomes `DEPLETED`, and the warehouse's load and posture are recomputed. A new shipment is `PLANNED` with a null `delivered_on`; the very first shipment created against an `ALLOCATED` or `SHORTED` commitment moves that commitment to `FULFILLING` with a `version` increment, and each creation recomputes the program's `shipped_units_total` — the sum of `units` over shipments in `PLANNED` or `DELIVERED` status for the program's commitments. Shipments can be listed with filters on `commitment_id`, `warehouse_id`, and `status`.

Delivery is a single act by a `LogisticsCoordinator`: a `PLANNED` shipment becomes `DELIVERED`, `delivered_on` is set from the logical clock, and the shipment's `version` increments. `delivered_on` renders the delivery instant without fractional digits when it falls on a whole second and with three fractional digits otherwise. When the delivered units push the sum of `DELIVERED` units over the commitment's shipments to at least the commitment's `allocated_units`, the commitment becomes `FULFILLED` with its own `version` increment.

Forecast error has exactly one remedy. Each commitment holds a single mid-season **reorder**, exercised by its owning retailer with a `units` request. The reorder is granted only when the requested `units` is at least 1 and no more than the product's remaining supply pool, the commitment's `reorder_used` is still false, and the program is in `SHIPPING` or `ON_SHELF` status. The remaining pool for a product is the sum of `produced_units` over the product's `COMPLETE` runs minus the sum of `allocated_units` over that product's commitments in `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status. A request against a commitment that already consumed its reorder, or while the program is in the wrong state, is rejected with `ERR_REORDER_NOT_ALLOWED` (HTTP 422); a request whose units exceed the remaining pool — including any request when the pool is zero, which is a rejection, not a zero-grant — is rejected with `ERR_SUPPLY_POOL_EXHAUSTED` (HTTP 422). The reorder is defined only for commitments in `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status; a request against a commitment in any other status is rejected with `ERR_REORDER_NOT_ALLOWED` (HTTP 422). A granted reorder adds `units` to the commitment's `allocated_units`, records the grant in `reorder_units`, flips `reorder_used` to true, and increments the commitment's `version`; if the commitment was `FULFILLED` and its delivered units now fall short of the enlarged allocation, it reopens to `FULFILLING` — the one cycle that lets a fulfilled commitment take more stock.

### 3.7. Weekly Sell-Through Reporting and the Cannibalization Index

When the logical clock reaches `on_shelf_on`, a `PlatformAdmin` advances the program from `SHIPPING` to `ON_SHELF` — an early attempt is `ERR_PROGRAM_ADVANCE_TOO_EARLY` — and weekly sell-through reporting opens. Each week, a `Retailer` files one `SellThroughReport` per program, naming its own `retailer_id` (which must equal `X-User-ID`, `ERR_OWNERSHIP_MISMATCH`), the `program_id`, and `week_of_on`, the Monday of the reported week, which must lie inside the inclusive interval from the program's `on_shelf_on` to its `pull_on`; a week outside that interval is rejected with `ERR_REPORT_WEEK_OUT_OF_WINDOW` (HTTP 422). That window is the only filing gate; the program's current status is not consulted. The report carries three non-negative counters: `seasonal_units_sold`, `seasonal_units_on_hand`, and `everyday_units_sold` — the last being the core-shelf velocity that feeds the cannibalization index. The triple of retailer, program, and week is unique: a second report for the same triple is rejected with `ERR_DUPLICATE_RESOURCE`. Reports can be listed with filters on `retailer_id` and `program_id`.

Every report computes two cannibalization variants at creation, both rounded half-up to 4 decimal places. The **raw** variant, `cannibalization_raw`, is the week's `everyday_units_sold` divided by the retailer account's `everyday_baseline_weekly_units` — a reading of how the everyday shelf actually performed against its own baseline. The **seasonally adjusted** variant, `cannibalization_adjusted`, divides the same `everyday_units_sold` by the baseline scaled up by the season's expected everyday lift: the lift constant is 1.10 for a `VALENTINES` program, 1.15 for `EASTER`, 1.25 for `HALLOWEEN`, and 1.20 for `CHRISTMAS`. Because every season's lift is greater than 1, identical report data always yields an adjusted value below the raw value. The two variants have distinct jobs: the raw index is the enforcement input — it drives the markdown approval guard of Section 3.9 — while the adjusted index is the planning view, correcting for the lift the everyday shelf was expected to feel from the season itself.

### 3.8. Summer Heat Claims and Settlement

Chocolate travels badly in the heat, so summer shipments carry a claims protocol. A `Retailer` files a `HeatClaim` against a shipment that has been `DELIVERED` — filing against a shipment in any other status is rejected with `ERR_INVALID_STATE` — naming the `shipment_id`, the `claimed_units`, a `reason` of exactly `MELT`, `BLOOM`, or `PACKAGING_COMPROMISE`, and a free-text `evidence_note`. The `claimed_units` must be at least 1, and the sum of `claimed_units` over all of the shipment's claims that are not `REJECTED` must not exceed the shipment's `units`, or the filing is rejected with `ERR_CLAIM_EXCEEDS_SHIPMENT` (HTTP 422). A claim is born `FILED` and immediately advanced to `UNDER_REVIEW` by the system within the same request, so the persisted claim reads `UNDER_REVIEW` at `version` 1. At filing the system also computes the claim's `auto_approve` flag: it is true exactly when the product is heat-sensitive (`requires_temp_control`), the shipment was not `temp_controlled`, the retailer did not decline temp control, and the shipment's `ship_on` falls in a summer month — June, July, or August (months 6, 7, and 8).

Adjudication belongs to a `ClaimsAdjuster`, never to the filing retailer. The adjudication request carries a `decision` field, and its value is one of three. `APPROVE` moves the claim to `APPROVED`, computes `credit_cents` by the settlement rule below, and posts that credit onto the `credit_balance_cents` of the retailer account behind the shipment's commitment. `REJECT` moves the claim to `REJECTED` — but a claim whose `auto_approve` condition holds may not be rejected at all, and the attempt is refused with `ERR_CLAIM_AUTO_APPROVED` (HTTP 422), because a summer shipment of heat-sensitive product sent without refrigeration was a known house risk. `REQUEST_MORE_INFO` moves the claim to `MORE_INFO`, from which the owning retailer supplies fresh evidence through a provide-info step carrying a new `evidence_note`; that step replaces the claim's `evidence_note`, returns the claim to `UNDER_REVIEW`, and is repeatable — the review cycle `UNDER_REVIEW` to `MORE_INFO` and back may run as many times as needed. Every decide and provide-info increments the claim's `version` by 1. Claims can be listed with filters on `shipment_id` and `status`. The `credit_cents` field stays null until an approval sets it.

The settlement amount on approval is the `claimed_units` times the program's `retail_price_cents` times a payout fraction, rounded half-up to whole cents. The fraction is chosen by the first matching branch in this pinned top-to-bottom order: if the shipment was `temp_controlled`, the payout is 100% (a fraction of 1.00) — the house carried the cold chain and owns the failure; otherwise, if the retailer explicitly declined temp control (`temp_control_declined_by_retailer`), the payout is 50% (0.50) — the risk was shared; otherwise, if the product is heat-sensitive and the `ship_on` falls in a summer month — the auto-approve condition — the payout is 100% (1.00); otherwise the payout is a 25% (0.25) goodwill fraction.

### 3.9. Pull Date, Quarantine, and Disposition

Every season ends at `pull_on`. When the logical clock has reached it, a `PlatformAdmin` advances the program from `ON_SHELF` to `DISPOSITION` — an early attempt is `ERR_PROGRAM_ADVANCE_TOO_EARLY` — and the advance fires a three-link cascade. First, every `AVAILABLE` `InventoryLot` whose product is a `SEASONAL` product of this program becomes `QUARANTINED`; everyday lots and other programs' lots are untouched. Second, every `PLANNED` shipment whose commitment belongs to this program becomes `CANCELLED`, because a shipment of quarantined stock cannot ship. Third, each cancelled shipment's units are restored to the exact lots they were drawn from — each source lot's `units_on_hand` grows back by the units it contributed, in the reverse of the original draw order. The cascade then recomputes `in_use_units`, `quarantined_units`, and posture for the affected warehouses, recomputes the program's `shipped_units_total`, and increments the program's `version` by 1. A source lot that is not already `QUARANTINED` (for example one drawn to `DEPLETED`) becomes `QUARANTINED` as its units are restored.

Quarantine also exists outside the pull. A `CategoryManager` may place a manual QA hold on any `AVAILABLE` lot, moving it to `QUARANTINED`, and may later release a `QUARANTINED` lot back to `AVAILABLE` — but only pre-pull: both operations require the program of the lot's product to be outside `DISPOSITION`, `CLOSED`, and `CANCELLED`, and a violation is rejected with `ERR_INVALID_STATE`. Post-pull quarantine is permanent; the only way out for a quarantined lot then is disposition. A lot of an `EVERYDAY` product has no program and is never blocked by this gate. Both operations recompute the warehouse's `quarantined_units` and posture (quarantine also recomputes `in_use_units`) and increment the lot's `version` by 1. Lots can be listed with filters on `product_id`, `warehouse_id`, `production_run_id`, and `status`.

Disposition converts quarantined stock into recovered value under segregation of duties. A `CategoryManager` proposes a `DispositionOrder` naming the `program_id` — the program must be in `DISPOSITION` status, or the proposal is rejected with `ERR_INVALID_STATE` — a `product_id` that must be a `SEASONAL` product of that program (`ERR_PRODUCT_PROGRAM_MISMATCH`), the `warehouse_id` whose quarantined stock it consumes, the `units` to dispose, and a `channel` of exactly `MARKDOWN`, `SECONDARY`, or `DESTRUCTION`. The `units` must be at least 1 and no more than the quarantined `units_on_hand` of that product at that warehouse, or the proposal is rejected with `ERR_DISPOSITION_EXCEEDS_QUARANTINE` (HTTP 422). A `MARKDOWN` order must carry a `markdown_pct` — a fraction no lower than 0.10 and no higher than 0.70 — and a missing or out-of-band value is rejected with `ERR_MARKDOWN_OUT_OF_RANGE` (HTTP 422). Brand protection is absolute: a `SECONDARY`-channel order for a `brand_protected` product is rejected with `ERR_BRAND_PROTECTION` (HTTP 422). The proposal is born `PROPOSED` with `proposed_by_user_id` recording the proposer's `X-User-ID` and `version` 1. Orders can be listed with filters on `program_id`, `product_id`, `warehouse_id`, and `status`.

Approval belongs to a **different** `CategoryManager`: the approver's `X-User-ID` must differ from `proposed_by_user_id`, and a self-approval — whether the decision is `APPROVE` or `REJECT` — is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The approval request's `decision` field takes `APPROVE`, moving the order to `APPROVED`, or `REJECT`, moving it to `REJECTED`; either way `approved_by_user_id` records the approver and the order's `version` increments. Approval of a `MARKDOWN` order carries one more guard, the everyday-business protection made concrete: if at least one sell-through report exists for the program, the average of `cannibalization_raw` over those reports must be at least 0.85 — the cannibalization floor — or the approval is rejected with `ERR_CANNIBALIZATION_GUARD` (HTTP 422), because marking seasonal stock down while it is measurably eating the core shelf only makes the damage cheaper to repeat. When no sell-through report exists yet for the program, the guard does not apply.

Execution is the warehouse's act, performed by a `LogisticsCoordinator` on an `APPROVED` order. Timing matters: a `MARKDOWN` or `SECONDARY` order may execute only while the logical clock has not passed the program's `destroy_by_on`; after that instant only `DESTRUCTION` may execute, and an out-of-window attempt is rejected with `ERR_DISPOSITION_WINDOW_CLOSED` (HTTP 422). Execution also re-verifies that the quarantined `units_on_hand` of the order's product at its warehouse still cover the order's `units`; a shortfall found at execution time is rejected with `ERR_DISPOSITION_EXCEEDS_QUARANTINE` (HTTP 422). Execution consumes the warehouse's `QUARANTINED` lots of the product in `created_at` ascending, `lot_code` ascending order, and a lot whose `units_on_hand` reaches zero becomes `DISPOSITIONED`. The order's `recovered_value_cents` is settled by channel. For `MARKDOWN`, the per-unit price after markdown is computed first — the program's `retail_price_cents` scaled by one minus the `markdown_pct`, rounded half-up to whole cents — and only then multiplied by the disposed `units`; this per-unit-first order is pinned, and the alternative of multiplying first and rounding once is forbidden because it yields different cents (at a 499-cent price, a 0.15 markdown, and 10 units, the pinned result is 424 cents times 10, i.e. 4240 cents — not the 4242 cents the alternative would produce). For `SECONDARY`, the recovered value is the disposed `units` times the program's `retail_price_cents` times the secondary-channel recovery fraction, a system constant fixed at 0.25 (25%), rounded half-up to whole cents. For `DESTRUCTION`, the recovered value is 0. Execution then recomputes the warehouse's load figures and posture, refreshes the program's `disposed_units_total` (the sum of `units` over the program's `EXECUTED` disposition orders), and increments the order's `version` by 1.

Only when the quarantine is empty may the season be filed away: advancing the program from `DISPOSITION` to `CLOSED` requires that no `QUARANTINED` lot with `units_on_hand` greater than zero remain for any product of the program, and an attempt with undisposed stock outstanding is rejected with `ERR_UNDISPOSED_STOCK_REMAINS` (HTTP 422).

A program's aggregate position is readable at any moment through its supply summary, a computed read returning `program_id`, `produced_units_total`, `committed_units_total`, `allocated_units_total` (the sum of `allocated_units` over the program's commitments in `ALLOCATED`, `SHORTED`, `FULFILLING`, or `FULFILLED` status), `shipped_units_total`, `disposed_units_total`, and `remaining_supply_pool_units` — the sum, across the program's seasonal products, of each product's remaining reorder pool as defined in Section 3.6.

## 4. Endpoint Definitions

All endpoints live under the `/confection` prefix. Creation of a new resource returns HTTP 201; operations that modify an existing resource return HTTP 200. The commitment revision operation returns HTTP 201 because it creates the successor commitment, even though it also supersedes the old one. Request and response payloads are not restated here — Sections 2 and 3 define them; the table below is the routing and authorization contract only. Request fields beyond the inputs an endpoint declares are ignored; in particular, client-supplied values for system-managed properties (`id`, `created_at`, `updated_at`, `version`, computed totals, and workflow-owned fields such as `allocated_units`) never take effect. "All roles" in the authorized-roles column means every declared role: `PlatformAdmin`, `ProductionPlanner`, `Retailer`, `CategoryManager`, `LogisticsCoordinator`, and `ClaimsAdjuster`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /confection/seasonal-programs | Create a seasonal program (fixed retail price, all window dates) | PlatformAdmin |
| GET | /confection/seasonal-programs/{id} | Read a program including computed totals | All roles |
| GET | /confection/seasonal-programs/{id}/supply-summary | Computed read: production, commitment, allocation, shipment, and disposition totals plus the remaining reorder pool | All roles |
| POST | /confection/seasonal-programs/{id}/advance | Drive the program state machine to `to_state` under OCC (`expected_program_version`) | PlatformAdmin |
| POST | /confection/products | Create a product (SEASONAL requires `program_id`; EVERYDAY requires it null) | PlatformAdmin |
| GET | /confection/products/{id} | Read a product | All roles |
| GET | /confection/products | List products with filters (`program_id`, `kind`) | All roles |
| POST | /confection/production-runs | Schedule a production run (overlap and changeover checks on `line_code`) | ProductionPlanner |
| GET | /confection/production-runs/{id} | Read a production run | All roles |
| GET | /confection/production-runs | List production runs with filters (`line_code`, `product_id`, `program_id`, `status`, `completed_warehouse_id`) | All roles |
| POST | /confection/production-runs/{id}/start | Start a scheduled run (seasonal runs require program LOCKED or IN_PRODUCTION) | ProductionPlanner |
| POST | /confection/production-runs/{id}/complete | Complete an in-progress run; creates its inventory lot at the given warehouse and recomputes posture | ProductionPlanner |
| POST | /confection/production-runs/{id}/cancel | Cancel a SCHEDULED run (removes it from overlap/changeover checks) | ProductionPlanner |
| POST | /confection/retailer-accounts | Onboard a retailer account (tier, shelf cap, everyday baseline) | PlatformAdmin |
| GET | /confection/retailer-accounts/{id} | Read a retailer account including the credit ledger balance | All roles |
| POST | /confection/retailer-commitments | Create a DRAFT commitment (retailer-scoped; seasonal product of the program) | Retailer |
| GET | /confection/retailer-commitments/{id} | Read a commitment | All roles |
| GET | /confection/retailer-commitments | List commitments with filters (`program_id`, `retailer_id`, `product_id`, `status`, `supersedes_commitment_id`) | All roles |
| POST | /confection/retailer-commitments/{id}/submit | Submit a DRAFT commitment during the collection window | Retailer |
| POST | /confection/retailer-commitments/{id}/confirm | Confirm a SUBMITTED commitment (shelf-cap check) | CategoryManager |
| POST | /confection/retailer-commitments/{id}/revise | Create-with-supersede: replace this SUBMITTED commitment with revision+1 under OCC (`expected_commitment_version`) | Retailer |
| POST | /confection/retailer-commitments/{id}/reorder | The single mid-season reorder: draw extra units from the remaining program supply pool | Retailer |
| POST | /confection/retailer-commitments/{id}/cancel | Cancel a DRAFT, SUBMITTED, or CONFIRMED commitment | Retailer |
| POST | /confection/shipments | Create a PLANNED shipment; draws stock lot-age-first from the warehouse's AVAILABLE lots | LogisticsCoordinator |
| GET | /confection/shipments/{id} | Read a shipment | All roles |
| GET | /confection/shipments | List shipments with filters (`commitment_id`, `warehouse_id`, `status`) | All roles |
| POST | /confection/shipments/{id}/deliver | Mark a PLANNED shipment DELIVERED (`delivered_on` set from the logical clock) | LogisticsCoordinator |
| POST | /confection/heat-claims | File a heat-damage claim against a DELIVERED shipment | Retailer |
| GET | /confection/heat-claims/{id} | Read a heat claim | All roles |
| GET | /confection/heat-claims | List heat claims with filters (`shipment_id`, `status`) | All roles |
| POST | /confection/heat-claims/{id}/decide | Adjudicate a claim: APPROVE, REJECT, or REQUEST_MORE_INFO | ClaimsAdjuster |
| POST | /confection/heat-claims/{id}/provide-info | Retailer supplies more evidence; MORE_INFO returns to UNDER_REVIEW | Retailer |
| POST | /confection/warehouses | Create a warehouse | PlatformAdmin |
| GET | /confection/warehouses/{id} | Read a warehouse including computed load and posture | All roles |
| GET | /confection/inventory-lots/{id} | Read a lot | All roles |
| GET | /confection/inventory-lots | List lots with filters (`product_id`, `warehouse_id`, `production_run_id`, `status`) | All roles |
| POST | /confection/inventory-lots/{id}/quarantine | Manual QA quarantine of an AVAILABLE lot (pre-pull only) | CategoryManager |
| POST | /confection/inventory-lots/{id}/release-quarantine | Release a QUARANTINED lot back to AVAILABLE (forbidden once the program is in DISPOSITION or later) | CategoryManager |
| POST | /confection/disposition-orders | Propose disposition of quarantined seasonal stock (MARKDOWN, SECONDARY, or DESTRUCTION) | CategoryManager |
| GET | /confection/disposition-orders/{id} | Read a disposition order | All roles |
| GET | /confection/disposition-orders | List disposition orders with filters (`program_id`, `product_id`, `warehouse_id`, `status`) | All roles |
| POST | /confection/disposition-orders/{id}/approve | Approve or reject a PROPOSED disposition (approver must differ from proposer; cannibalization guard for MARKDOWN) | CategoryManager |
| POST | /confection/disposition-orders/{id}/execute | Execute an APPROVED disposition; consumes quarantined lots and settles recovered value | LogisticsCoordinator |
| POST | /confection/commodity-contracts | Book a cocoa or sugar contract for a program-year, optionally hedged | PlatformAdmin |
| GET | /confection/commodity-contracts/{id} | Read a contract | All roles |
| GET | /confection/commodity-contracts | List contracts with filters (`program_id`, `commodity`, `status`) | All roles |
| POST | /confection/commodity-contracts/{id}/settle | Settle an OPEN contract at the given spot price (final landed cost) | PlatformAdmin |
| POST | /confection/sell-through-reports | File the weekly sell-through report; computes both cannibalization variants | Retailer |
| GET | /confection/sell-through-reports/{id} | Read a sell-through report | All roles |
| GET | /confection/sell-through-reports | List sell-through reports with filters (`retailer_id`, `program_id`) | All roles |
| POST | /confection/_clock/set_current_utc | Set the server's logical clock (startup default exactly 2026-09-01T00:00:00Z; never falls back to wall-clock time) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below is the complete set of machine-readable error identifiers and their HTTP statuses. Trigger conditions are intentionally not repeated here; each error's conditions are defined in the narrative of Sections 2 and 3 where the guarded workflow lives. A request that matches no declared route fails with the framework-level `ERR_NOT_FOUND` (HTTP 404), and a declared path called with an unsupported method fails with `ERR_METHOD_NOT_ALLOWED` (HTTP 405); neither is attached to any workflow.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_RUN_NOT_FOUND | 404 |
| ERR_RETAILER_NOT_FOUND | 404 |
| ERR_COMMITMENT_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_WAREHOUSE_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_DISPOSITION_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_PROGRAM_NOT_OPEN | 409 |
| ERR_PROGRAM_REOPEN_EXHAUSTED | 422 |
| ERR_NO_PRODUCTION_SCHEDULED | 422 |
| ERR_UNDISPOSED_STOCK_REMAINS | 422 |
| ERR_BRAND_PROTECTION | 422 |
| ERR_CLAIM_AUTO_APPROVED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PROGRAM_ADVANCE_TOO_EARLY | 422 |
| ERR_COMMITMENT_WINDOW_CLOSED | 422 |
| ERR_SHIP_WINDOW_VIOLATION | 422 |
| ERR_REPORT_WEEK_OUT_OF_WINDOW | 422 |
| ERR_PRODUCTION_DEADLINE_VIOLATION | 422 |
| ERR_DISPOSITION_WINDOW_CLOSED | 422 |
| ERR_LINE_SCHEDULE_OVERLAP | 409 |
| ERR_CHANGEOVER_VIOLATION | 422 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_PRODUCT_PROGRAM_MISMATCH | 422 |
| ERR_REORDER_NOT_ALLOWED | 422 |
| ERR_MARKDOWN_OUT_OF_RANGE | 422 |
| ERR_CLAIM_EXCEEDS_SHIPMENT | 422 |
| ERR_SHIPMENT_EXCEEDS_ALLOCATION | 422 |
| ERR_CANNIBALIZATION_GUARD | 422 |
| ERR_HEDGE_EXCEEDS_QUANTITY | 422 |
| ERR_SHELF_CAP_EXCEEDED | 422 |
| ERR_DISPOSITION_EXCEEDS_QUARANTINE | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_WAREHOUSE_FULL | 409 |
| ERR_WAREHOUSE_CONGESTED_SEASONAL | 409 |
| ERR_SUPPLY_POOL_EXHAUSTED | 422 |
