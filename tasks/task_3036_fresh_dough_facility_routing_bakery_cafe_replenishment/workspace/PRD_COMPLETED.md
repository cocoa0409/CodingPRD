# Dough Facility Replenishment API — Product Requirements Document

## 1. Introduction

Regional bakery-cafe chains live and die by a single unforgiving fact: fresh dough has a shelf life measured in hours, not days. Every evening, hundreds of cafes must commit to tomorrow's bread before tonight's cutoff; every night, a handful of dough facilities must convert those commitments into a production plan that fits inside real oven-line capacity; every early morning, trucks must thread overnight routes that land at each cafe inside a narrow receiving window; and every day, cafe bakers must proof and bake that dough before it expires. A mistake anywhere in the chain — an over-committed facility, a late truck, a batch proofed too long — turns directly into discarded product or empty shelves.

This document specifies the Dough Facility Replenishment API, the system of record for that chain. It covers next-day cafe ordering with per-dough-type cutoffs and a strict no-substitution policy, weather- and event-driven demand adjustments that rescale orders after they are placed, facility production planning with effective-unit capacity accounting, overnight route dispatch with per-stop delivery windows, cafe bake-day scheduling with proofing and shelf-life gates, a day-end donation program that converts unsold goods into account credits, and a periodic settlement process that allocates facility overhead across company and franchise cafes on different burden terms.

All cafe-local times in this deployment are UTC. A single logical clock — initialized to exactly `2026-09-01T00:00:00Z` before any call is made, and never falling back to wall-clock time — is the only time source for cutoff evaluation, delivery-window resolution, proofing timers, shelf-life checks, and schedule open/close decisions. An operator-facing capability advances this clock to a supplied `to_iso8601` instant and returns the resulting `now_iso8601`; it is available to every role.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every resource and every request in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. The system recognizes exactly five roles: `FacilityPlanner`, `RouteDispatcher`, `CafeManager`, `DonationCoordinator`, and `FinanceAdmin`. A request with a missing, empty, or unrecognized `X-User-Role`, or a missing or empty `X-User-ID` (both headers are required on every endpoint), is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity works as follows. When `X-User-Role` is `CafeManager`, `X-User-ID` is the `id` of the acting `Cafe`; ownership checks on any resource that references a cafe compare the resource's cafe foreign key to `X-User-ID`, so a cafe manager may only create, submit, amend, or cancel orders, manage schedules and bake entries, for their own cafe. A CafeManager acting on another cafe's resource is rejected with `ERR_FORBIDDEN_ROLE` even when the resource exists. When `X-User-Role` is `FacilityPlanner`, `RouteDispatcher`, `DonationCoordinator`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it against any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, or one outside these bounds, is rejected with `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource and underpins the optimistic concurrency rules in §2.9.

All entities in this API — `DoughFacility`, `DoughType`, `Cafe`, `DemandAdjustment`, `CafeOrder`, `ProductionPlan`, `DeliveryRoute`, `RouteStop`, `CafeSchedule`, `BakeEntry`, `DonationPickup`, `BillingPeriod`, and `SettlementLine` — carry the full set. A resource's `version` starts at 1 at creation. Note that a mutation triggered as a side effect counts too: when an order write touches its parent cafe aggregate (for example, submit, amend, cancel, payment posting, plan close invoicing, or donation confirm), the cafe's `version` increments and its `updated_at` refreshes. The same holds for a production plan's owning facility when a plan is created, locked, released, or closed. If a single request would mutate the same resource several times (for example, an order write that also touches the cafe), the resource's `version` advances by exactly 1 for that request as a whole.

### 2.5. The Logical Clock and Cafe-Local Time

The logical clock is the system's only temporal authority. Before any call is made it reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. Because cafe-local time is UTC in this deployment, no timezone conversion is ever applied: a cutoff expressed as an `HH:MM` string, a delivery window bound, or a proofing deadline is evaluated directly against the logical clock. Order cutoffs, stop window resolution, proofing and baking gates, shelf-life expiry, and schedule opening all read this clock and no other.

### 2.6. Nested Resource Retrieval

Endpoints that address nested resources — a route stop beneath a route beneath a facility, a bake entry beneath a schedule beneath a cafe — validate path identifiers strictly left to right. The request is rejected immediately with `ERR_NOT_FOUND` at the first path identifier that does not correspond to an existing resource, before any later identifier or any business rule is evaluated. The same code applies when a body-supplied foreign key — such as a `cafe_id`, `dough_type_id`, `schedule_id`, or `cafe_order_id` — does not resolve, or resolves to a resource that belongs to a different parent than the path implies. A CafeManager ownership denial (`ERR_FORBIDDEN_ROLE`, per §2.1) is interposed between the two: it fires after the addressed path resources resolve but before any remaining body foreign keys are resolved.

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication comes first (missing or unknown headers yield `ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then path existence from left to right (`ERR_NOT_FOUND`), then body foreign-key resolution (also `ERR_NOT_FOUND`), then whether the target resource's current state permits the requested transition (`ERR_INVALID_STATE`). Only after those come the business rules: the locked-order and locked-plan guards (`ERR_ORDER_LOCKED`, `ERR_PLAN_LOCKED`), then the order-cutoff check (`ERR_ORDER_CUTOFF_PASSED`), then the safety rules — the no-substitution guard (`ERR_SUBSTITUTION_FORBIDDEN`) and the shelf-life gate (`ERR_SHELF_LIFE_EXCEEDED`) — then the stop-window rules (`ERR_STOP_WINDOW_VIOLATION`), then the credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`), then the capacity gates (`ERR_CAPACITY_EXCEEDED`), then uniqueness (`ERR_DUPLICATE`), then proof-timing (`ERR_TOO_EARLY`), and finally optimistic-concurrency staleness (`ERR_STALE_VERSION`). A malformed or out-of-range input field — a bad enum value, a non-positive integer where a positive one is required, an ill-formed date — is rejected with `ERR_VALIDATION`.

### 2.8. Monetary Values and Precision

Money appears in two forms. Invoice and ledger amounts are integer cents — `credit_limit_cents`, `credit_balance_cents`, `admin_pool_cents`, `amount_cents`, `direct_invoice_cents`, `allocated_indirect_cents`, and `allocated_amount_cents` are all exact integers with no fractional part. Unit prices and per-unit costs are dollar figures carried to exactly 2 decimal places using round-half-up — this covers the computed `unit_price` behind each invoice line, the donation `credit_amount`, and the settlement `unit_allocated_cost`. Dollar-valued configuration such as `flat_transfer_price` preserves its input precision. Where a calculation mixes the two, the order of operations is pinned by the relevant workflow: round the unit price to 2 decimal places first, then multiply by units to obtain an exact integer-cent invoice total.

### 2.9. Optimistic Concurrency Control

Two write operations require a client-supplied optimistic-concurrency token, and the check is a hard rejection — not an optional nicety.

- Creating a cafe order requires the `expected_cafe_version` field, carrying the `version` of the target `Cafe` as the client last observed it. If the cafe's version has since advanced — because a prior order was created, submitted, amended, or cancelled against it, a payment was posted, a plan close invoiced it, or a donation credit landed — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client's view of the cafe aggregate is stale.
- Releasing a production plan requires the `expected_facility_version` field, carrying the `version` of the owning `DoughFacility` as the client last observed it. A mismatch with the facility's current version — advanced by an overlapping plan's creation, lock, release, or close — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

Amending a cafe order's quantity also carries `expected_cafe_version` and obeys the same rule. A missing or non-integer OCC token on any of these endpoints is rejected with `ERR_VALIDATION`. Endpoints not named here do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Master Data: Facilities, Dough Types, and Cafes

A `FacilityPlanner` begins by standing up the network. Each dough facility is created with a display `name` and an `effective_capacity_units` ceiling — the maximum number of effective production units the facility can turn out on a single production date, which must be a positive integer. Effective units are not raw units: a conventional dough unit consumes one effective unit of capacity, while an artisan unit consumes two, reflecting the longer bench time artisan dough occupies on the line.

Dough types are the catalog against which cafes order. Each `DoughType` carries a globally unique `code` (for example, `WHITE-CONV`), a `category` of either `CONVENTIONAL` or `ARTISAN`, a `shelf_life_hours` value (a positive integer counting hours from the start of the production date until the dough expires), an `order_cutoff_local` in `HH:MM` form (between 00:00 and 23:59) marking the cafe-local instant on the day before the production date at and after which orders and amendments are refused, a `substitution_allowed` flag encoding the no-substitution rule, and a `flat_transfer_price` — a number that must be strictly greater than zero, the facility's base per-unit transfer price in dollars before any ownership markup, and also the per-unit basis on which donation credits are priced. Creating a dough type whose `code` duplicates an existing one is rejected with `ERR_DUPLICATE`. The catalog can be browsed with an optional `category` filter.

Cafes are the demand side. A cafe is registered with a `name`, the `facility_id` of the home facility that supplies it, an `ownership_type` of `COMPANY` or `FRANCHISE` — a classification that drives both the transfer-pricing markup and the overhead burden share at settlement — and a `credit_limit_cents` ceiling on its outstanding receivable balance, which must be positive. A `facility_id` that does not resolve to an existing facility rejects the create with `ERR_NOT_FOUND`. The system-maintained `credit_balance_cents` starts at 0 when the cafe is created and thereafter tracks the outstanding receivable: invoice totals are added when a plan close bills the day, payments subtract from it, and donation credits subtract from it but can never push it below zero. Cafes can be listed with optional `facility_id` and `ownership_type` filters.

### 3.2. Placing and Amending Cafe Orders

A cafe's ordering week starts when a `CafeManager` places a next-day order. One order covers exactly one dough type line: the payload names the `cafe_id`, the `dough_type_id`, the `production_date` on which the dough will be produced and delivered, and the requested `quantity` (a positive integer), plus the OCC token `expected_cafe_version` described in §2.9. A newly created order lands in `DRAFT` with `billing_status` `UNBILLED`, its `actual_quantity` still null, and its `adjusted_quantity` initialized from whichever demand adjustment is currently `ACTIVE` for that cafe and date (or equal to `quantity` when none is). Creating the order touches the cafe aggregate, so the cafe's `version` increments by 1.

Submitting a `DRAFT` order is the point of commitment, and it is where three independent gates fire. First, the credit check: the cafe's current `credit_balance_cents` plus the provisional invoice total for the new line must not exceed the cafe's `credit_limit_cents`, or the submission is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. The provisional total projects the invoice using the order's `quantity` (not the adjusted figure) multiplied by the current unit transfer price — the same per-unit price the final invoice will use, computed per the transfer-pricing rule in §3.8 — so the provisional and final amounts can diverge when a demand adjustment reshapes the line before close or when the line ships short. Second, the cutoff: submission must occur strictly before the dough type's `order_cutoff_local` on the day before the `production_date`; at or after that instant the attempt is rejected with `ERR_ORDER_CUTOFF_PASSED`. A successful submission moves the order to `SUBMITTED` and increments the cafe's `version`. The cafe's `credit_balance_cents` aggregates invoices across every dough type the cafe orders, so a single aggregate balance check covers all of the cafe's lines.

Amendment walks the order backwards. Amending a `SUBMITTED` order returns it to `DRAFT` and replaces both `quantity` and `adjusted_quantity` from the payload values — the payload carries the new `quantity` and the `expected_cafe_version` token, and the adjusted figure is recomputed against whatever demand adjustment is `ACTIVE` at that moment. Amendment is only possible strictly before the order cutoff; afterwards the request is rejected with `ERR_ORDER_CUTOFF_PASSED`. Cancellation is available while the order is `DRAFT` or `SUBMITTED` — regardless of whether the cutoff has since passed — and moves it to the terminal `CANCELLED` state. Both amendment and cancellation increment the cafe's `version` by 1, and any attempt to amend or cancel once the order has reached `LOCKED` or beyond is rejected with `ERR_ORDER_LOCKED`; an attempt to amend a still-`DRAFT` order is rejected with `ERR_INVALID_STATE`, and cancelling an already-`CANCELLED` order is likewise `ERR_INVALID_STATE`.

When the cutoff instant arrives, an auto-lock sweep moves every still-`SUBMITTED` order for that dough type and date into `LOCKED` — a submission whose cutoff has already passed locks in the same breath. The sweep runs when the logical clock advances and again at production-plan creation; fetching a single order also applies any due sweep before responding, and the sweep bumps the `version` of each order it locks. A locked order is immutable: the amendment window has closed for good.

### 3.3. Demand Adjustments: Weather and Events

Demand rarely stands still between order placement and the cutoff. A `FacilityPlanner` records a `DemandAdjustment` for a cafe and a production date, supplying the `cafe_id`, the `production_date`, a `reason` of `WEATHER` or `EVENT`, and a signed whole-percent `demand_delta_pct` between −80 and +100 — a snowstorm might justify −40, a street festival +20. The new adjustment is born `ACTIVE`.

At most one adjustment may be `ACTIVE` per cafe and production date. Creating a new one for a pair that already has an `ACTIVE` adjustment flips the older one to `SUPERSEDED` with its `superseded_by_id` pointing at the newcomer (the field is null until then). Every affected order for that cafe and date in `DRAFT`, `SUBMITTED`, or `LOCKED` then recomputes its `adjusted_quantity` from the newly active adjustment. The adjusted figure is the requested `quantity` scaled by the active adjustment's percentage: the quantity is multiplied by one hundred plus the delta, divided by one hundred, and rounded down to a whole unit, with a floor of zero — so an adjustment can shrink a line to nothing but never below nothing. With no adjustment active, `adjusted_quantity` simply equals `quantity`.

A planner may also rescind an `ACTIVE` adjustment outright, moving it to `RESCINDED`; every affected order in `DRAFT`, `SUBMITTED`, or `LOCKED` then reverts to `adjusted_quantity` equal to its plain `quantity`. Adjustments can be listed with optional `cafe_id`, `production_date`, `status`, and `superseded_by_id` filters. Because the supersede and rescind flows only touch the adjustment and the orders' computed field, they do not by themselves reject anything — but they do change the planned volumes that capacity checks and invoicing will later see. Each recompute bumps the `version` of every affected order by 1.

### 3.4. Production Planning and Facility Capacity

Once the cutoff has locked the day's orders, the `FacilityPlanner` creates the facility's `ProductionPlan` for the date — one plan per facility per `production_date`, enforced by uniqueness (`ERR_DUPLICATE` on a second attempt). Plan creation sweeps every `LOCKED` order for that facility and date into the plan, moving each to `PLANNED`, and computes the plan's load: `total_effective_units` is the sum over attached planned lines of each line's `adjusted_quantity` weighted by category — one effective unit per conventional unit, two per artisan unit. The `over_capacity` flag is set when that total exceeds the facility's `effective_capacity_units`. Plan creation also increments the facility's `version`.

Locking the plan is a hard gate. Locking is only permitted while the plan is `OPEN` and its `total_effective_units` is within the facility's `effective_capacity_units`; an over-capacity plan cannot lock at all and the attempt is rejected with `ERR_CAPACITY_EXCEEDED`. Before locking, the planner may relieve the load by detaching orders — the convention is to detach the smallest effective-unit order first, breaking ties by the earliest order `created_at`. Detaching an order is done by cancelling it (`CANCELLED` orders attached to a plan no longer count toward `total_effective_units`); no standalone detach endpoint exists. Once the plan is `LOCKED`, late-arriving locked orders can no longer attach: any such attach is rejected with `ERR_PLAN_LOCKED`. In practice no new `LOCKED` order can arise once a plan exists for that facility and date — the auto-lock sweep has already run at plan creation, every still-`SUBMITTED` order's cutoff has passed by definition, and no further orders may be submitted past the cutoff — so the `ERR_PLAN_LOCKED` guard is unreachable.

Releasing moves the plan from `LOCKED` to `RELEASED` and requires the `expected_facility_version` OCC token per §2.9 — a mismatch is rejected with `ERR_STALE_VERSION`. The plan must not be `over_capacity` at release. Release advances every attached planned order from `PLANNED` to `ROUTED`, and the planned quantities become the load plan the route dispatcher works against; from this point, route stop availability is the delivery constraint.

Closing the plan is the day's financial reckoning. It is permitted only when the plan is `RELEASED` and every attached order has reached a terminal state — `DELIVERED`, `SHIPPED_SHORT`, or `CANCELLED`. Close creates one invoice line per delivered or shipped-short order using the transfer-pricing rule of §3.8, flips each billed order's `billing_status` from `UNBILLED` to `INVOICED`, and adds each invoice total to the ordering cafe's `credit_balance_cents`. The facility's `version` increments on lock, release, and close alike. Orders cancelled through a route cascade while attached to a plan drop out of that plan's `total_effective_units` and `over_capacity` recomputation, and the plan's `version` increments once when the cascade recomputes it. Close returns the plan object itself; the invoice totals it posts are observable through the orders' `billing_status` transitions and the cafes' `credit_balance_cents`, and through the settlement `direct_invoice_cents` at period close. Plans can be browsed per facility or across facilities, with optional `facility_id`, `production_date`, and `status` filters.

### 3.5. Overnight Routes and Stop Windows

The `RouteDispatcher` owns the overnight network. A `DeliveryRoute` is created under a facility for a `production_date` — the route physically runs the night before that date — with a `vehicle_capacity_units` value (a positive integer) stating the raw units the truck carries. Raw units are category-blind here: conventional and artisan units each count once against the truck, unlike the facility's effective-unit accounting.

Stops are added to a route in visit order. Each `RouteStop` carries a `seq` (the visit order on the route, unique per route, starting at 1), the `cafe_id` being served, a `planned_arrival` instant, the `window_start_local` and `window_end_local` bounds of the cafe's receiving window in `HH:MM` form, and the `planned_units` of raw dough this stop will deliver (a positive integer that counts against the route's vehicle capacity). The planned arrival must fall inside the half-open window — strictly after the open bound and at or before the close bound; a stop created outside its window is rejected with `ERR_STOP_WINDOW_VIOLATION`. Only the clock time of `planned_arrival` is compared against the window bounds. A window whose close is at or before its open wraps midnight: the arrival must fall strictly after the open bound or at or before the close bound on the following day. Stops may only be added while the route is `DRAFT`; adding to a route in any later state is rejected with `ERR_INVALID_STATE`. The same code guards a subtler case: two stops on the same cafe must not have overlapping windows with zero gap between them — windows touching at a bound are also rejected, and an already-`CANCELLED` stop's window is ignored for this check.

Publishing a route requires that it still be `DRAFT`, that at least one stop exists, and that the sum of the stops' planned raw units fits within `vehicle_capacity_units` — otherwise the publish is rejected with `ERR_CAPACITY_EXCEEDED`; a load exactly equal to the vehicle capacity publishes. Publishing moves the route to `PUBLISHED`; a separate depart call moves a `PUBLISHED` route to `IN_TRANSIT`. The route completes automatically the moment every stop on it has reached a terminal state.

Cancellation is the heavy hammer, available while the route is `DRAFT` or `PUBLISHED`. Cancelling a route cascades: every stop moves to `CANCELLED`; every order attached to those stops moves to `CANCELLED` regardless of whether it was `DRAFT`, `SUBMITTED`, `LOCKED`, `PLANNED`, or `ROUTED`; and each cancelled order's `billing_status` is forced to `CREDITED` with a zero invoice — there is no charge for an undelivered day, so the cafe's `credit_balance_cents` is left unchanged by the cascade. The cascade bumps the `version` of each cancelled order and stop, and of any production plan whose totals it recomputes (a plan that loses all of its orders this way keeps its current status).

### 3.6. Arrival, Delivery, and the No-Substitution Rule

Arrivals are recorded stop by stop, in sequence: the route must be `IN_TRANSIT`, and every earlier-`seq` stop on the route must already be in a terminal state before the next arrival can be logged. Recording an arrival stamps `actual_arrival` with the current clock and moves the stop from `SCHEDULED` into `ARRIVED`, from which the window outcome resolves automatically. An `ARRIVED` stop whose arrival falls inside the half-open window — strictly after `window_start_local` and at or before `window_end_local` — resolves to `ON_TIME`. An arrival at or before the window's open bound is rejected outright with `ERR_STOP_WINDOW_VIOLATION`; the truck has shown up before the cafe can receive it. An arrival after the close bound but still on the same local day resolves to `LATE`, and one that lands on a later local day than planned resolves to `MISSED`. An arrival before the planned delivery day is rejected with `ERR_STOP_WINDOW_VIOLATION`. Window outcome resolution uses the same half-open, midnight-wrapping semantics as stop creation; for a wrapping window an arrival on the planned day is always at least `ON_TIME` (never rejected for being early), and the window's bounds are compared against the arrival's clock time on the planned delivery day. The arrive payload may carry an optional `loaded_units`; when omitted, the stop's `loaded_units` defaults to its `planned_units`. When supplied, `loaded_units` must be a non-negative integer.

Delivery of the stop's orders rides on the same call. The orders a stop serves are the `ROUTED` orders for the stop's cafe whose `production_date` equals the route's `production_date`. When the loaded quantity covers the planned quantity — or the dough type's `substitution_allowed` is true — each of the stop's orders moves from `ROUTED` to `DELIVERED` and its `actual_quantity` is set to the planned quantity, where the planned quantity is the order's `adjusted_quantity`. When the truck is short on a dough type whose `substitution_allowed` is false, no other dough type may fill the gap: the line ships short, moving to `SHIPPED_SHORT` with `actual_quantity` set to the loaded quantity allocated to it. A shortage is judged against the sum of the served orders' planned quantities, and when the load is short the remaining units are allocated across the served orders in order-creation order, each order taking the lesser of its planned quantity and the units still remaining; an order receiving its full planned quantity still delivers in full even mid-shortage, and one receiving fewer ships short with that partial `actual_quantity` (which may be zero). Attempting to satisfy a shortage on a no-substitution dough type with substitute product is rejected with `ERR_SUBSTITUTION_FORBIDDEN`; because the payload carries no substitution channel, this rejection is unreachable in practice — shortages on such dough simply ship short. Note that an order's `billing_status` does not move at delivery — it stays `UNBILLED` until the plan's close invoices the day. Each delivered or shipped-short order's `version` bumps, and any production plan it belongs to recomputes its totals and bumps its own `version` once. A route auto-completes when all of its stops have reached terminal states. Routes and stops can be browsed per facility or flat across the network; stop lists accept optional `cafe_id` and `status` filters, and the flat stop list also accepts `route_id`.

### 3.7. The Cafe Bake Day: Schedules, Proofing, and Shelf Life

On the cafe side, a `CafeManager` opens each bake day through a `CafeSchedule`. One schedule exists per cafe per `business_date` — a second schedule for the same pair is rejected with `ERR_DUPLICATE`. The schedule is created `PLANNED` and can only be opened on the day itself: opening requires that the current cafe-local date equal the schedule's `business_date`, at which point it becomes `OPEN`.

Bake entries commit dough to the oven line. Each `BakeEntry` references the `cafe_order_id` of the delivered (or shipped-short) order supplying the dough, a `quantity` of units committed to the entry, a `proof_start_at` instant, and a `proof_minutes` duration — baking starts exactly `proof_minutes` after proofing starts. An entry's proof interval (from `proof_start_at` for `proof_minutes`, treated as half-open) must not overlap the proof interval of any other non-terminal entry on the same schedule — back-to-back adjacency is legal — and a violation is rejected with `ERR_STOP_WINDOW_VIOLATION`. Entries begin `SCHEDULED`. Starting proof requires the schedule to be `OPEN`, the referenced order to be `DELIVERED` or `SHIPPED_SHORT`, and the current time to be at or after `proof_start_at`; an early attempt is rejected with `ERR_TOO_EARLY`. Starting the bake requires the entry to be `PROOFING`, the current time to be at or after the proof-start instant plus the proof duration (`ERR_TOO_EARLY` again if early), and — critically — the dough to still be alive: the bake must start strictly before the dough's expiry instant, which is midnight at the start of the order's `production_date` plus the dough type's `shelf_life_hours`. A bake started at or after that instant is rejected with `ERR_SHELF_LIFE_EXCEEDED`. When both would fail at once, the shelf-life gate reports first, so the expiry rejection takes precedence over the too-early one. From `BAKING`, the entry is completed to `COMPLETED`; from either `PROOFING` or `BAKING` it may instead be discarded to `DISCARDED`.

Closing the schedule requires that every entry on it be in a terminal state — `COMPLETED` or `DISCARDED`. Once the schedule is `CLOSED`, the day's unsold counts become available for donation logging. Schedules can be listed per cafe or flat across cafes with optional `business_date` and `status` filters (the flat list also accepts `cafe_id`), and entries can be listed per schedule or flat with optional `cafe_order_id` and `status` filters (the flat list also accepts `schedule_id`).

### 3.8. Transfer Pricing, Invoicing, and Payments

Invoicing happens once, at production plan close, and the arithmetic is fixed. For each delivered or shipped-short order, the unit price starts from the dough type's `flat_transfer_price` and is marked up according to the ordering cafe's `ownership_type`: a `COMPANY` cafe pays an 18 percent markup, a `FRANCHISE` cafe pays 12 percent. The marked-up price is rounded half-up to 2 decimal places, then compared against a floor — four dollars ($4.00) per unit for `ARTISAN` dough, three dollars fifty ($3.50) per unit for `CONVENTIONAL` — and raised to the floor if it falls short. The invoice total is that rounded unit price multiplied by the order's `actual_quantity` (the delivered quantity, which equals the planned quantity except on a short shipment), converted to exact integer cents. The rounding order is pinned: round the unit price first, then multiply. This final, close-time computation is authoritative; the provisional projection used at order submit time differs only in that it applies the same unit price to the requested `quantity` instead, which is why a demand adjustment landing between submit and close — or a short shipment — makes the two figures diverge.

Each invoice flips the order's `billing_status` from `UNBILLED` to `INVOICED` and adds the invoice total to the cafe's `credit_balance_cents`. The other path into `CREDITED` is the zero invoice: a route-cancellation cascade (or a donation credit posting against an unbilled order) forces `UNBILLED` to `CREDITED` with no charge and no movement in the cafe's balance.

A `FinanceAdmin` settles receivables by posting a payment against a cafe, supplying an `amount_cents` that must be positive. The payment applies oldest-first across the cafe's `INVOICED` orders, ordered by order `created_at` (ties are impossible — server timestamps are unique): each order becomes `PAID` only when its invoice is fully covered, and a partial remainder stays on the oldest partially paid order, which remains `INVOICED`. The posting subtracts the amount from the cafe's `credit_balance_cents` (floored at zero — an overpayment never drives the balance negative), increments the cafe's `version`, and returns `201 Created` with the `applied_cents` (the portion of the payment absorbed by invoices), the list of `settled_order_ids`, and the resulting `credit_balance_cents`.

### 3.9. Day-End Donations

Unsold baked goods do not go to waste. A `DonationCoordinator` logs a `DonationPickup` against a cafe, supplying the `schedule_id` of the day whose goods are being donated, the `partner_name` of the receiving organization, and the counts `unsold_conventional` and `unsold_artisan` (each zero or greater). The pickup is born `LOGGED`; its `credit_amount` is computed at confirmation, not at logging, and remains null until then. Logging requires only that the schedule exist and belong to the cafe — it need not be `CLOSED` yet.

Confirming a pickup requires the pickup to be `LOGGED` and the referenced schedule to be `CLOSED`; confirmation moves the pickup to the terminal `CONFIRMED` state. Confirmation computes the donation credit: the total unsold units — conventional plus artisan — multiplied by the facility's reference conventional dough type's `flat_transfer_price`, multiplied by one quarter (a 0.25 credit rate), rounded half-up to 2 decimal places. The reference dough type is the `CONVENTIONAL` dough type with the lowest `shelf_life_hours` — dough types are a global catalog not owned by any facility, so this is the network-wide conventional dough type meeting that rule — with ties broken by the earliest `DoughType` `created_at`; confirming when no `CONVENTIONAL` dough type exists at all is rejected with `ERR_NOT_FOUND`. Note the asymmetry: the credit always prices at the conventional rate even when the unsold units are artisan. The credit then reduces the cafe's `credit_balance_cents`, floored at zero, and increments the cafe's `version`. Crucially, the credit does not reopen settled invoices — billing lines already `CREDITED` remain `CREDITED`. A pickup that should never have been logged can instead be voided while it is still `LOGGED`, moving it to `VOIDED` with no financial effect. Pickups can be listed per cafe or flat, with optional `schedule_id` and `status` filters (the flat list also accepts `cafe_id`).

### 3.10. Billing Periods and Overhead Settlement

Periodically, a `FinanceAdmin` settles the facility's books. A `BillingPeriod` is opened under a facility with an inclusive `period_start` and `period_end` date and an `admin_pool_cents` amount (zero or more) — the facility's administrative overhead pool for the period. A new period's `total_cafe_hours` starts at 0. While the period is `OPEN`, the admin adds one `SettlementLine` per cafe, supplying the `cafe_id` and the `cafe_hours` of labor that cafe consumed in the period (zero or more). Until the period closes, a line's computed fields stand at their initial values: `direct_invoice_cents`, `allocated_indirect_cents`, `allocated_amount_cents`, and `cafe_total_units` at 0, and `burden_share` and `unit_allocated_cost` null.

Closing the period — permitted only while it is `OPEN` and at least one settlement line exists — runs the overhead allocation in two passes. Pass one computes `total_cafe_hours` as the sum of `cafe_hours` across all of the period's lines, zero-hour cafes included; this total is fixed before any per-line figure is derived, and per-line values never feed back into it. Pass two computes, per line: the `direct_invoice_cents`, summing the invoice totals for that cafe's billed lines — those with `billing_status` `INVOICED`, `PAID`, or `CREDITED` — whose `production_date` falls within the period's inclusive bounds; the `allocated_indirect_cents`, the cafe's proportional share of the overhead pool (the pool multiplied by the line's hours and divided by the period's total hours), rounded half-up to whole cents (when every line carries zero hours, each line's indirect share is zero); the `burden_share`, which is 0.60 for `FRANCHISE` cafes and 0.45 for `COMPANY` cafes; and the `allocated_amount_cents`, the indirect share multiplied by the burden share and rounded down to whole cents.

The line's `unit_allocated_cost` then divides the cafe's total cost — direct invoices plus allocated overhead — by the cafe's delivered units in the period, rounded half-up to 2 decimal places, and is null when the cafe delivered no units. The denominator itself depends on ownership, and this dual basis is deliberate: a `FRANCHISE` cafe's `cafe_total_units` counts all delivered units, while a `COMPANY` cafe's `cafe_total_units` counts only its artisan delivered units — the same ledger data with a different denominator, diverging from transfer pricing's all-units basis. Closing the period also stamps `total_cafe_hours` with the pass-one total and returns the period object; the computed lines are read through the settlement-line endpoints. Finally, settling a `CLOSED` period moves it to `SETTLED`, at which point the settlement amounts become authoritative and the lines immutable. Periods and lines can be listed per facility or flat, with optional `status`, `facility_id`, `billing_period_id`, and `cafe_id` filters as each list allows.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The exceptions are payment posting (§3.8), which returns `201 Created` for the posted payment, and the logical-clock advance (§1), which returns `200 OK`. A request to a path outside this table is rejected with `ERR_NOT_FOUND` (HTTP 404); a recognized path hit with the wrong method is rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405). All endpoints are mounted under the `/dough-ops` prefix. Request bodies, response payloads, and side effects are specified in §3's workflows; the table below is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dough-ops/_clock/set_current_utc` | Advance the logical clock | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities` | Create a dough facility | FacilityPlanner |
| GET | `/dough-ops/facilities/{facility_id}` | Get a facility | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/dough-types` | Create a dough type | FacilityPlanner |
| GET | `/dough-ops/dough-types` | List dough types | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/dough-types/{dough_type_id}` | Get a dough type | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafes` | Create a cafe | FacilityPlanner |
| GET | `/dough-ops/cafes` | List cafes | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/cafes/{cafe_id}` | Get a cafe | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafes/{cafe_id}/payments` | Post a payment against the cafe's outstanding invoices | FinanceAdmin |
| POST | `/dough-ops/demand-adjustments` | Create a weather/event demand adjustment; supersedes any active one for the same cafe and date | FacilityPlanner |
| GET | `/dough-ops/demand-adjustments` | List demand adjustments | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/demand-adjustments/{adjustment_id}` | Get a demand adjustment | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/demand-adjustments/{adjustment_id}/rescind` | Rescind an active adjustment | FacilityPlanner |
| POST | `/dough-ops/cafe-orders` | Create a next-day dough order | CafeManager |
| GET | `/dough-ops/cafe-orders` | List orders | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/cafe-orders/{order_id}` | Get an order | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafe-orders/{order_id}/submit` | Submit a draft order | CafeManager |
| POST | `/dough-ops/cafe-orders/{order_id}/amend` | Amend a submitted order's quantity | CafeManager |
| POST | `/dough-ops/cafe-orders/{order_id}/cancel` | Cancel a draft or submitted order | CafeManager |
| POST | `/dough-ops/facilities/{facility_id}/production-plans` | Create a production plan; sweeps locked orders into it | FacilityPlanner |
| GET | `/dough-ops/facilities/{facility_id}/production-plans` | List production plans for a facility | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/production-plans` | Flat list of production plans across facilities | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/production-plans/{plan_id}` | Get a production plan | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/lock` | Lock an open plan | FacilityPlanner |
| POST | `/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/release` | Release a locked plan | FacilityPlanner |
| POST | `/dough-ops/facilities/{facility_id}/production-plans/{plan_id}/close` | Close a released plan and invoice the day | FacilityPlanner |
| POST | `/dough-ops/facilities/{facility_id}/routes` | Create an overnight delivery route | RouteDispatcher |
| GET | `/dough-ops/facilities/{facility_id}/routes` | List routes for a facility | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/routes` | Flat list of routes across facilities | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/routes/{route_id}` | Get a route | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/routes/{route_id}/publish` | Publish a draft route | RouteDispatcher |
| POST | `/dough-ops/facilities/{facility_id}/routes/{route_id}/depart` | Depart a published route | RouteDispatcher |
| POST | `/dough-ops/facilities/{facility_id}/routes/{route_id}/cancel` | Cancel a draft or published route | RouteDispatcher |
| POST | `/dough-ops/facilities/{facility_id}/routes/{route_id}/stops` | Add a stop to a route | RouteDispatcher |
| GET | `/dough-ops/facilities/{facility_id}/routes/{route_id}/stops` | List stops on a route | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/route-stops` | Flat list of route stops across routes | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/route-stops/{stop_id}` | Get a route stop | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/routes/{route_id}/stops/{stop_id}/arrive` | Record arrival at a stop; resolves the window outcome and delivers the stop's orders | RouteDispatcher |
| POST | `/dough-ops/cafes/{cafe_id}/schedules` | Create a bake-day schedule | CafeManager |
| GET | `/dough-ops/cafes/{cafe_id}/schedules` | List schedules for a cafe | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/schedules` | Flat list of cafe schedules across cafes | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/schedules/{schedule_id}` | Get a schedule | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/open` | Open the schedule on its business date | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/close` | Close the schedule once all bake entries are terminal | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries` | Add a bake entry to a schedule | CafeManager |
| GET | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries` | List bake entries for a schedule | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/bake-entries` | Flat list of bake entries across schedules | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/bake-entries/{entry_id}` | Get a bake entry | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/start-proof` | Start proofing an entry | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/start-bake` | Start baking an entry | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/complete` | Complete a baking entry | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/schedules/{schedule_id}/entries/{entry_id}/discard` | Discard a proofing or baking entry | CafeManager |
| POST | `/dough-ops/cafes/{cafe_id}/donation-pickups` | Log a day-end donation pickup | DonationCoordinator |
| GET | `/dough-ops/cafes/{cafe_id}/donation-pickups` | List donation pickups for a cafe | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/donation-pickups` | Flat list of donation pickups across cafes | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/donation-pickups/{pickup_id}` | Get a donation pickup | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/cafes/{cafe_id}/donation-pickups/{pickup_id}/confirm` | Confirm a pickup and post the donation credit | DonationCoordinator |
| POST | `/dough-ops/cafes/{cafe_id}/donation-pickups/{pickup_id}/void` | Void a logged pickup | DonationCoordinator |
| POST | `/dough-ops/facilities/{facility_id}/billing-periods` | Open a billing period | FinanceAdmin |
| GET | `/dough-ops/facilities/{facility_id}/billing-periods` | List billing periods for a facility | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/billing-periods` | Flat list of billing periods across facilities | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/billing-periods/{period_id}` | Get a billing period | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settlement-lines` | Add a settlement line for a cafe | FinanceAdmin |
| GET | `/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settlement-lines` | List settlement lines for a period | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/settlement-lines` | Flat list of settlement lines across periods | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| GET | `/dough-ops/settlement-lines/{line_id}` | Get a settlement line | FacilityPlanner, RouteDispatcher, CafeManager, DonationCoordinator, FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/close` | Close the period and compute the overhead allocation | FinanceAdmin |
| POST | `/dough-ops/facilities/{facility_id}/billing-periods/{period_id}/settle` | Settle a closed period; lines become authoritative | FinanceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is the code-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_LOCKED` | 409 |
| `ERR_PLAN_LOCKED` | 409 |
| `ERR_ORDER_CUTOFF_PASSED` | 409 |
| `ERR_SUBSTITUTION_FORBIDDEN` | 422 |
| `ERR_SHELF_LIFE_EXCEEDED` | 422 |
| `ERR_STOP_WINDOW_VIOLATION` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_TOO_EARLY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_METHOD_NOT_ALLOWED` | 405 |
| `ERR_INTERNAL` | 500 |
