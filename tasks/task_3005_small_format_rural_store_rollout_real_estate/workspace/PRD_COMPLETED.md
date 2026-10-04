# Rural Store Rollout API — Product Requirements Document

## 1. Introduction

Dollar-format retail expansion into rural trade areas is a capital-intensive, multi-year orchestration problem: thousands of candidate sites must be screened on demographic criteria, the surviving sites must be tied down through build-to-suit developer agreements with enforceable delivery dates, opening calendars must be choreographed against fixture-kit logistics and seasonal labor, and every new store's projected economics must be weighed against the sales it will siphon from nearby existing stores. The Rural Store Rollout API is the system of record for that pipeline. It governs the full lifecycle of a rollout program — from trade-area screening on drive-time, household, income, and grocery-gap criteria, through site control, construction, distribution-center assignment, self-distribution route planning, and grand-opening execution — and it closes the loop with cannibalization analysis and a capital-planning workflow that ranks remodel, relocation, and new-build projects against a single finite new-build capital budget.

The API serves five operator roles with a strict approval chain: program administration, real estate, network planning, store operations, and finance. Its central financial discipline is a per-program capital ledger: every construction start commits capital, every approval of a capital project commits capital, every kill or termination releases exactly what it committed, and the sum of committed and available capital must equal the program's budget at every instant. A program-scoped, strictly-ordered event log records the milestones that matter — program activation, deactivation, closure, trade-area qualification, and store opening — so downstream reporting can reconstruct the rollout's history without inference.

This document is the complete specification. Section 2 covers system-wide contracts: authentication, response envelopes, pagination, resource identity, monetary precision, the capital ledger invariant, event sourcing, optimistic concurrency, and the validation cascade. Section 3 narrates the business workflows. Sections 4 and 5 give the endpoint and error catalogues in tabular form.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly five roles, spelled exactly as follows: `PROGRAM_ADMIN`, `REAL_ESTATE_MANAGER`, `NETWORK_PLANNER`, `OPERATIONS_LEAD`, and `FINANCE_ANALYST`. A request whose `X-User-Role` header is missing or whose value is not one of these five roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Only the `X-User-Role` header is enforced; `X-User-ID` is never validated for presence and is simply read as provided (and may be absent).

All five roles are opaque identities: `X-User-ID` is an operator identifier not tied to any persisted entity in the system. The server may record it where a workflow demands attribution — most notably, when a `FINANCE_ANALYST` submits a capital project, the submitting user's `X-User-ID` is captured on the project as `submitted_by` so the segregation-of-duties check at decision time can compare the deciding `PROGRAM_ADMIN`'s `X-User-ID` against it — but no ownership check ever compares `X-User-ID` to an entity's `id`.

Role responsibilities in brief: `PROGRAM_ADMIN` owns the program lifecycle, trade areas, store registration, developer registration, capital decisions, and the test clock. `REAL_ESTATE_MANAGER` runs the real-estate pipeline: format selection, site control agreements, and store kills. `NETWORK_PLANNER` owns the supply-chain network: distribution centers, DC assignments, route plans, and store volume tuning. `OPERATIONS_LEAD` owns grand-opening planning and execution. `FINANCE_ANALYST` owns sales recording, cannibalization studies, and capital-project origination. All read endpoints are shared across all five roles.

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
- Requests to unknown paths, and requests using an unsupported method on a known path, return the error envelope with `ERR_NOT_FOUND` (HTTP 404); any other unhandled server failure surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints accept two optional query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. These bounds are enforced, not clamped: a non-integer value, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints sort by `created_at` ascending (ties broken by insertion order), except the program-events listing, which orders as described in §2.7. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints expose scoping and filter query parameters drawn from the resource's own fields. Every program-scoped listing accepts `rollout_program_id`. Trade areas filter by `status`; stores filter by `status`, `format_type`, `trade_area_id`, and `existing_store_id`; site agreements filter by `developer_id` and `store_id`; DC assignments filter by `store_id`, `distribution_center_id`, and `status`; route plans and opening plans filter by `store_id` and `status`; cannibalization studies filter by `store_id` and `status`; capital projects filter by `kind`, `status`, and `store_id`; and the program-events listing filters by `rollout_program_id`. Reading a single cannibalization study additionally accepts the `variant` query parameter described in §3.7.

### 2.4. Common Resource Properties

Every persistent resource carries a system-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. With one exception, every resource also carries `updated_at`, refreshed on every mutation, and `version`, an integer starting at 1 and incremented by exactly 1 on every mutation of that resource. The exception is the `RolloutEvent` resource: events are append-only facts and carry only `id` and `created_at`; neither `updated_at` nor `version` exists on them.

A `version` increment accompanies every state transition and every derived-field recomputation on the owning resource. When one operation cascades into several resources — for example, an agreement activation that moves a store and commits capital on the program — each affected resource's `updated_at` and `version` advance independently.

### 2.5. Monetary Values, Percentages, and Rounding

All monetary values are integer cents throughout the API: budgets, prices, costs, penalties, revenues, and uplifts are never fractional. Where a calculation would produce a fractional cent (for example, the low-volume stem-cost multiplier or an agreement kill fee), the result is rounded half up to the nearest whole cent. Percentages and scores reported by the API — `trade_area_score`, `truck_fill_pct`, `transfer_pct`, `capital_score`, per-entry impact percentages — are numbers carried to exactly 2 decimal places, rounded half up. Timestamps supplied by clients, such as `committed_delivery_date`, `opening_date`, and `actual_delivery_date`, are ISO 8601 datetimes.

### 2.6. The Program Capital Ledger

Each rollout program owns a capital ledger with three figures: `new_build_capital_budget_cents`, the total capital allocated to the program at creation (adjustable later only while the program is `ACTIVE`); `committed_capital_cents`, the sum of capital currently spoken for; and `available_capital_cents`, which is always exactly `new_build_capital_budget_cents` minus `committed_capital_cents`. The invariant — committed plus available equals budget — holds at every instant, with no drift permitted.

Committed capital has exactly four sources, and the reconciliation recomputes on every mutation that creates or removes committed capital (agreement activation, agreement termination, store kill, capital decision). First, every store that has advanced to `UNDER_CONSTRUCTION`, `DELIVERED`, or `OPEN` contributes its `build_cost_cents`. Second, every `APPROVED` `NEW_BUILD` capital project contributes its `new_build_cost_cents`. Third, every `APPROVED` `RELOCATION` project contributes its `project_cost_cents`. Fourth, every `APPROVED` `REMODEL` project contributes its `remodel_cost_cents`. Killing an `UNDER_CONSTRUCTION` store or terminating an `ACTIVE` agreement must release exactly the store's `build_cost_cents` — no more, no less.

### 2.7. The Program Event Log

Every rollout program maintains an append-only event log of `RolloutEvent` records. Each event carries the owning program's `rollout_program_id`, a `sequence_number`, an `event_type`, an optional `store_id` identifying the subject store (nullable and informational only — events are program-scoped even when the store lives outside the program), and a `payload` object holding an event-specific snapshot (for example, the score at qualification, or the `opening_date` at store opening). Five event types exist: `PROGRAM_ACTIVATED`, `PROGRAM_DEACTIVATED`, `PROGRAM_CLOSED`, `TRADE_AREA_QUALIFIED`, and `STORE_OPENED`.

Sequence numbers run strictly from 1 upward per program, assigned in `created_at` order; the first event ever appended to a program — normally its first activation — bears `sequence_number` 1. The program's `event_log_cursor` field always mirrors the sequence number of the most recently appended event, starting at 0 for a program with no events. Events are read through the program-events listing in sequence order; the listing orders rows by `rollout_program_id` and then `sequence_number` (not by the generic `created_at` sort). The program-lifecycle events (`PROGRAM_ACTIVATED`, `PROGRAM_DEACTIVATED`, `PROGRAM_CLOSED`) carry an empty `payload` object and a null `store_id`; `TRADE_AREA_QUALIFIED` carries the score snapshot as `payload.trade_area_score` and a null `store_id`; `STORE_OPENED` carries `payload.opening_date` and the opened store's id.

### 2.8. Hierarchical Path Validation

The API's resources form a hierarchy: a rollout program contains trade areas, developers, distribution centers, and capital projects; a trade area contains stores; a store contains site control agreements, DC assignments, route plans, opening plans, and cannibalization studies. When a request path contains multiple resource identifiers, the system validates them strictly left to right: it first confirms that each path resource exists and belongs to the chain implied by the URL — rollout, then trade area, then store, then the child resource — and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) before any later identifier or any business rule is examined. References supplied in request bodies are checked separately as referential-integrity rules (see §2.11 and the per-workflow narratives); a body reference that points at an entity which is missing, in the wrong state, or outside the program is rejected with `ERR_BAD_REFERENCE` (HTTP 422). In particular, operations addressed to a path resource that also carry `rollout_program_id` in the body require it to equal the path resource's owning program; a mismatch is `ERR_BAD_REFERENCE`, and a `rollout_program_id` that does not resolve to any program is likewise `ERR_BAD_REFERENCE`.

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control on a parent entity's `version`; no other endpoint accepts a version field.

The trade-area scoring operation requires `expected_trade_area_version`, carrying the caller's last observed `version` of the `TradeArea`. If the trade area's current `version` has advanced beyond what the caller observed — because an earlier screening run or a market-data refresh already moved it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's view of the trade area's status and score is stale.

The store format-selection operation requires `expected_store_version`, carrying the caller's last observed `version` of the `Store`. A mismatch against the store's current `version` — a prior format selection or another store mutation having landed in between — is rejected with `ERR_STALE_VERSION` (HTTP 412).

The capital-project decision operation requires `expected_program_version`, carrying the caller's last observed `version` of the parent `Rollout`. Because an approval mutates the program's committed capital, deciding against a program version the caller has not observed risks budgeting against stale figures; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. The Program Logical Clock

Opening-calendar rules depend on a per-program logical clock, not on wall-clock time. Before any clock-setting call for a program, the clock reads exactly `2026-09-01T00:00:00Z` — the server startup default — and it must never fall back to real wall-clock time. A `PROGRAM_ADMIN` advances a program's clock through a test-driving capability that accepts the target program's `rollout_program_id` and a `to_iso8601` instant, and returns the program's `current_utc`; a `rollout_program_id` that does not resolve fails with `ERR_NOT_FOUND` (HTTP 404), and a malformed `to_iso8601` fails with `ERR_INVALID_REQUEST`. All temporal validations in §3 — the 45-day minimum lead on `opening_date`, the 3-day execution window, delivery lateness — evaluate against this logical clock.

### 2.11. Validation Ordering

When several checks could reject the same request, the server applies them in a fixed priority order, and the client sees the first failure only. Two refinements apply throughout: the `rollout_program_id` body reference, when an operation carries one, is resolved immediately after authorization and any path-existence checks and before the remaining request-shape checks, so an unresolvable program reference yields `ERR_BAD_REFERENCE` ahead of other body validation; and where a §3 narrative states a more specific check order for an endpoint, that endpoint-specific order governs. The general order is: (1) authentication — the `X-User-Role` header must be present and declare a known role, else `ERR_UNAUTHENTICATED`; (2) authorization — the role must be permitted on this endpoint, else `ERR_FORBIDDEN`; (3) path existence — path resources must exist and chain correctly, else `ERR_NOT_FOUND`; (4) request shape — required body fields must be present and well-typed and enum values must come from their declared sets, else `ERR_INVALID_REQUEST` (a well-typed value that nonetheless violates a declared constraint, such as a percentage outside its range, surfaces as `ERR_VALIDATION`); (5) state legality — the target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`; (6) program activity — child-creating and committing operations require the program to be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; (7) opening-calendar clock gates, else `ERR_OPENING_TOO_EARLY`; (8) referential integrity of body references, else `ERR_BAD_REFERENCE`; (9) singleton rules — one open agreement per store, one `ACTIVE` DC assignment per store, one `ACTIVE` route plan per store, one `PLANNED` or `LOCKED` opening plan per store — else `ERR_DUPLICATE_ACTIVE`; (10) store-level preconditions on format selection, volume updates, and opening-plan creation, else `ERR_STORE_PRECONDITION`; (11) fixture lead time at opening-plan lock, else `ERR_FIXTURE_LEAD_TIME`; (12) cannibalization gating at study finalize, else `ERR_CANNIBALIZATION_BLOCKED`; (13) the final-study requirement at capital-project submit, else `ERR_STUDY_NOT_FINAL`; (14) segregation of duties at capital decision, else `ERR_SEGREGATION_OF_DUTIES`; (15) developer capacity at agreement activation, else `ERR_DEVELOPER_CAPACITY_EXCEEDED`; (16) DC capacity at assignment, else `ERR_DC_CAPACITY_EXCEEDED`; (17) capital budget at approval, else `ERR_CAPITAL_BUDGET_EXCEEDED`; and (18) optimistic-concurrency checks, else `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

### 3.1. Program Lifecycle: Activation, Deactivation, and Closure

A `PROGRAM_ADMIN` creates a rollout program by supplying a `name`, a `fiscal_year` label (an integer), the `new_build_capital_budget_cents` for the program (an integer, which must be at least 0 — a negative budget fails as `ERR_VALIDATION`), and optionally a `cannibalization_coefficient` — the sales-transfer coefficient used by cannibalization studies, defaulting to 0.40 when omitted and otherwise accepted as any number without range constraint. The program is born in `DRAFT` status with `committed_capital_cents` at 0 and `available_capital_cents` equal to the budget. Program names are unique across all rollout programs; the same uniqueness discipline applies within a program to trade-area names, store names, developer names, and DC names, and a duplicate name fails as `ERR_VALIDATION`.

Activation moves the program `DRAFT → ACTIVE` and appends a `PROGRAM_ACTIVATED` event to the program's log. A program's lifecycle `status` is one of `DRAFT`, `ACTIVE`, or `CLOSED`; closure is terminal. While `DRAFT`, the program refuses every child-creating and committing operation — screening, store creation, agreement activation, opening-plan creation, study creation, capital submission, and capital decisions all reject with `ERR_PROGRAM_NOT_ACTIVE` until activation has occurred (route planning, trade-area registration and refresh, developer and DC registration, DC assignment, agreement drafting/execution/delivery/termination, capital-project creation, and capital-project cancellation are not gated on program activity). While the program is `ACTIVE`, the administrator may adjust its settings — `new_build_capital_budget_cents` and `cannibalization_coefficient` — and each such adjustment recomputes `available_capital_cents`. The settings update checks program activity before validating the supplied field values, and a budget reduction below the currently committed amount is permitted, in which case `available_capital_cents` simply goes negative. Activation from a non-`DRAFT` program, deactivation from a non-`ACTIVE` program, and closure of an already `CLOSED` program each fail with `ERR_INVALID_STATE`.

The lifecycle is cyclic between `DRAFT` and `ACTIVE`: deactivation returns an `ACTIVE` program to `DRAFT` and appends `PROGRAM_DEACTIVATED`, but only when no store in the program sits mid-pipeline. A store in `SITE_CONTROL`, `UNDER_CONSTRUCTION`, or `DELIVERED` blocks deactivation with `ERR_PROGRAM_HAS_ACTIVE_STORES`; stores in `PROPOSED`, `KILLED`, `OPEN`, or `EXISTING` do not. Closure is terminal from either `DRAFT` or `ACTIVE` and appends `PROGRAM_CLOSED`. From `ACTIVE`, closing additionally requires that every store in the program be `KILLED`, `OPEN`, or `EXISTING`. From either source state, every capital project in the program must have reached a decision — `APPROVED`, `REJECTED`, or `CANCELLED` — or the close is rejected with `ERR_PROGRAM_CLOSE_BLOCKED`.

### 3.2. Trade-Area Screening and the Rescreen Loop

A `PROGRAM_ADMIN` registers candidate trade areas by supplying the program's `rollout_program_id`, a `name`, and four market-data inputs: `drive_time_minutes` (the median drive time from the candidate centroid to the trade-area population, an integer from 0 to 45), `household_count` (which must be greater than 0), `median_household_income_cents` (an integer, with no range constraint), and `grocery_gap_pct` (the percent of grocery demand currently unserved, a number from 0 to 100; a value outside that range fails as `ERR_VALIDATION`). Registration itself is permitted regardless of the program's lifecycle status; only scoring runs are gated on an `ACTIVE` program. The trade area starts in `SCREENING` with `screening_count` 0, `trade_area_score` null until the first scoring run, and `projected_revenue_cents` 0 until a first format selection.

Scoring runs against the logical state of the trade area's current inputs. The score is a weighted blend of four normalized components. The grocery-gap component is the trade area's `grocery_gap_pct` divided by 40, capped at 1.0. The income component is the trade area's median household income, converted from cents to dollars, reduced by 25,000, divided by 50,000, and clamped into the range from 0 to 1.0. The drive-time component is 1 minus `drive_time_minutes` divided by 45, floored at 0. The household component is `household_count` divided by 6,000, capped at 1.0. The raw score weights these components at 0.35, 0.25, 0.20, and 0.20 respectively, and the **standard** score is the raw score multiplied by 100, rounded half up to two decimal places.

When other stores of the same program already operate nearby, scoring switches to the **cannibalization-adjusted** variant. The overlap percentage is built from every store in the same program with status `OPEN` or `EXISTING` whose own trade area's `drive_time_minutes` lies within 10 minutes of this trade area's `drive_time_minutes`: each such store contributes the smaller of its trade area's `grocery_gap_pct` and 25, and the contributions sum to an overlap capped at 100. When the overlap is greater than zero, the adjusted score is the raw score multiplied by 100 and then by 1 minus half the overlap fraction (the overlap percentage divided by 100, halved), rounded half up to two decimal places; when the overlap is zero the standard score stands. The resulting value is recorded on the trade area as `trade_area_score` — the adjusted value whenever the overlap is greater than zero, otherwise the standard score, regardless of whether the run qualifies.

A trade area qualifies only when all five criteria hold: `drive_time_minutes` at most 30, `household_count` at least 650, `median_household_income_cents` at least 3,500,000, `grocery_gap_pct` at least 12, and the final score at least 40. A qualifying run moves the trade area `SCREENING → QUALIFIED` (or, on rescreen, `REJECTED → QUALIFIED`), increments `screening_count` by 1, and appends a `TRADE_AREA_QUALIFIED` event carrying the score snapshot. A failing run moves it to `REJECTED` — from `SCREENING`, from `QUALIFIED`, or staying at `REJECTED` on a still-failing rescreen — and increments `screening_count` by 1, with no event appended. A rescreen that would push a `QUALIFIED` trade area to `REJECTED` is permitted only while no store of that trade area exists in any status other than `KILLED`; otherwise the request fails with `ERR_INVALID_STATE`.

Market data is refreshable: while a trade area remains `SCREENING` or `REJECTED`, the administrator may update any subset of `drive_time_minutes`, `household_count`, `median_household_income_cents`, and `grocery_gap_pct` by supplying `rollout_program_id` and `trade_area_id`, and each refresh call increments the trade area's `version` by 1, even when the call changes no field. A refresh attempted on a `QUALIFIED` trade area fails with `ERR_INVALID_STATE`. Refresh is not gated on the program being `ACTIVE`. Every scoring run — initial or rescreen — is a guarded write under optimistic concurrency (§2.9): the request must carry `expected_trade_area_version` matching the trade area's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412), because a prior screening or refresh has already advanced the trade area past the caller's view. Each scoring run itself increments the trade area's `version` by 1.

### 3.3. Store Registration, Format Selection, and Volume Tuning

Store creation has two paths, both gated on an `ACTIVE` program (`ERR_PROGRAM_NOT_ACTIVE` otherwise) and both initiated by a `PROGRAM_ADMIN` supplying `rollout_program_id`, `trade_area_id`, and a `name`.

The pipeline path creates a store in `PROPOSED` status and requires the referenced trade area to be `QUALIFIED`; a trade area in any other status yields `ERR_TRADE_AREA_NOT_QUALIFIED`. The registration path sets `is_existing` to true and creates the store directly in the terminal `EXISTING` status, for cannibalization and remodel analysis of the legacy fleet; the referenced trade area must exist in the program but may be in any status, and format selection, site agreements, and opening plans never apply to such a store. On the registration path the caller supplies `format_type` directly — `TRADITIONAL`, `DG_FRESH`, or `DG_MARKET` — and may link the record to the legacy store it replaces via `existing_store_id`, a self-referential link for which cross-program references are allowed but which must resolve to an existing store or the creation fails with `ERR_BAD_REFERENCE` (greenfield pipeline stores carry `existing_store_id` null). The registration path may also carry `open_year_sales_cents` directly at creation; otherwise a `FINANCE_ANALYST` later records the legacy store's actual first-year sales via `open_year_sales_cents`, which feeds cannibalization studies and remodel ROI, and each sales recording increments the store's `version` by 1. Sales recording is permitted only on `EXISTING` stores; on any other store status it fails with `ERR_INVALID_STATE`. The `is_existing` flag defaults to false when omitted. A newly created store carries `stem_miles` 0, `volume_index` 1.0, and null `format_type`, `weekly_case_volume_base`, `projected_revenue_cents`, `build_cost_cents`, and `opening_date` until the workflows that set them run (the registration path sets `format_type` immediately).

For a pipeline store, format selection is a `REAL_ESTATE_MANAGER` operation with optimistic concurrency on the store: the request carries `rollout_program_id` and `expected_store_version`, and a mismatch with the store's current `version` rejects with `ERR_STALE_VERSION` (HTTP 412). Selection requires the store to be `PROPOSED` and to have no agreement in `ACTIVE` or `EXECUTED` status; violations fail with `ERR_STORE_PRECONDITION`. The selection projects annual revenue per format from the store's trade area: the trade area's `household_count` multiplied by the format's per-household revenue — 420 dollars for `TRADITIONAL`, 560 for `DG_FRESH`, 640 for `DG_MARKET` — and then uplifted by the trade area's grocery gap (multiplied by 1 plus `grocery_gap_pct` divided by 100), yielding an integer-cent figure. A format is feasible when its projected revenue meets its minimum bar: at least 40,000,000 cents for `TRADITIONAL`, at least 90,000,000 cents for `DG_FRESH`, at least 220,000,000 cents for `DG_MARKET`. Candidates are evaluated in preference order — `DG_MARKET` first, then `DG_FRESH`, then `TRADITIONAL` — and the first feasible format wins. If no format is feasible, the request fails with `ERR_NO_FEASIBLE_FORMAT` (HTTP 422).

A successful selection stamps four computed fields onto the store: `format_type`; `projected_revenue_cents`, the winning format's projection; `weekly_case_volume_base`, the baseline weekly case volume of the format — 900 for `TRADITIONAL`, 1,400 for `DG_FRESH`, 2,600 for `DG_MARKET`; and `build_cost_cents`, the all-in build cost — 350,000,000 cents for `TRADITIONAL`, 500,000,000 cents for `DG_FRESH`, 700,000,000 cents for `DG_MARKET`. The same `projected_revenue_cents` is copied onto the store's trade area, and the store's `version` increments by 1. Note that `format_type` is never client-supplied on the pipeline path — it is always computed by selection.

While a store remains `PROPOSED`, a `NETWORK_PLANNER` may tune its `volume_index`, the weekly case volume multiplier against baseline, which starts at 1.0; the update supplies `rollout_program_id` and the new `volume_index` (accepted as any number, without range constraint), increments the store's `version` by 1, and is rejected with `ERR_STORE_PRECONDITION` once the store has advanced past `PROPOSED`. Volume index feeds both stem-cost tiering (§3.5) and route planning.

Killing is the pipeline store's early exit, performed by a `REAL_ESTATE_MANAGER` supplying `rollout_program_id`. A store may be killed from `PROPOSED`, `SITE_CONTROL`, or `UNDER_CONSTRUCTION` — a store in any other status fails with `ERR_INVALID_STATE` — but only when no agreement for the store remains open — that is, no agreement in any status other than `TERMINATED` or `COMPLETED`; an open agreement blocks the kill with `ERR_SITE_CONTROL_ACTIVE`. The store-status check fires first, so a store in an unkilled-ineligible status holding an open agreement still fails with `ERR_INVALID_STATE`. The kill cascades: the store's `ACTIVE` DC assignment, if any, becomes `SUPERSEDED` and the affected distribution center's `assigned_store_count` decreases by 1; the store's `ACTIVE` route plan, if any, becomes `SUPERSEDED`; and any opening plan in `PLANNED` or `LOCKED` status is `CANCELLED`. When the killed store was `UNDER_CONSTRUCTION`, the program's `committed_capital_cents` additionally decreases by exactly the store's `build_cost_cents`, releasing the construction commitment.

### 3.4. Site Control: Developer Agreements, Delivery, and Penalties

Site control runs through build-to-suit developers. A `PROGRAM_ADMIN` registers a developer within a program by `rollout_program_id` and `name`; the developer's `active_agreement_count` starts at 0, and no developer may hold more than 3 `ACTIVE` agreements at once.

A `REAL_ESTATE_MANAGER` drafts a site control agreement for a `PROPOSED` store by supplying `rollout_program_id`, `store_id`, `developer_id`, the contractually committed `committed_delivery_date`, the `base_price_cents` (which must be greater than 0), and the `earnest_money_cents` deposit (which must be greater than 0 and strictly less than `base_price_cents`; a deposit that meets or exceeds the base price fails as `ERR_VALIDATION`). The developer reference must resolve inside the program, else `ERR_BAD_REFERENCE`. At most one agreement per store may be open — in any status other than `TERMINATED` or `COMPLETED` — so drafting a second open agreement for a store that already has one fails with `ERR_DUPLICATE_ACTIVE`. Per the §2.11 priority order, this singleton check (level 9) precedes the `PROPOSED`-store precondition (level 10): when a store both holds an open agreement and is no longer `PROPOSED` (for example, a store in `SITE_CONTROL` whose agreement is `EXECUTED`), the drafting request fails with `ERR_DUPLICATE_ACTIVE`, not `ERR_STORE_PRECONDITION`. The agreement begins in `DRAFT` with `late_days` 0 and `penalty_cents` 0.

Executing the agreement moves it `DRAFT → EXECUTED` and simultaneously moves the store `PROPOSED → SITE_CONTROL`. Execution requires the store to still be `PROPOSED` (failing with `ERR_STORE_PRECONDITION`) and re-verifies the earnest-money rule (greater than 0 and strictly less than `base_price_cents`, failing with `ERR_VALIDATION`), checking the store state before the earnest-money rule. Drafting, execution, delivery recording, and termination are not gated on the program being `ACTIVE`; only agreement activation is. Activation then moves the agreement `EXECUTED → ACTIVE`: it requires an `ACTIVE` program (`ERR_PROGRAM_NOT_ACTIVE` otherwise), requires the developer's `active_agreement_count` to be below 3 (`ERR_DEVELOPER_CAPACITY_EXCEEDED` otherwise), increments that count by 1, moves the store `SITE_CONTROL → UNDER_CONSTRUCTION`, and commits capital — the program's `committed_capital_cents` increases by the store's `build_cost_cents`.

Recording delivery moves the agreement `ACTIVE → DELIVERED` and the store to `DELIVERED`; an agreement in any other status fails with `ERR_INVALID_STATE`. The caller supplies the `actual_delivery_date`. Lateness is computed in whole calendar days: zero when the delivery lands on or before `committed_delivery_date`, otherwise the number of days between the committed and actual dates, with any partial day discarded. The delivery penalty accrues at 500,000 cents per late day, but accrual stops at day 180 — days beyond 180 earn nothing further at the base rate. Separately, a lateness bonus applies once delivery is more than 60 days late: each day beyond day 60 adds half the daily rate, that is 250,000 cents per such day. The penalty is the base accrual plus the bonus, capped at 45,000,000 cents, and lands on the agreement as `penalty_cents` alongside `late_days`. Delivery releases the developer slot — `active_agreement_count` decreases by 1 — and a badly late delivery has one further consequence: when `late_days` reaches 30 or more, the store's opening plan, if it is `PLANNED` or `LOCKED`, is cancelled, because the opening calendar built around the committed delivery date is no longer usable.

Termination unwinds the agreement from any of `DRAFT`, `EXECUTED`, or `ACTIVE`; an agreement in any other status fails with `ERR_INVALID_STATE`. From `DRAFT`, termination is clean: the earnest money is fully refunded and no kill fee applies. From `EXECUTED` or `ACTIVE`, termination forfeits a kill fee of 10 percent of `earnest_money_cents`, rounded down to whole cents, and the store reverts to `PROPOSED`. Terminating from `ACTIVE` additionally decrements the developer's `active_agreement_count` by 1 and releases the construction commitment — the program's `committed_capital_cents` decreases by exactly the store's `build_cost_cents`.

The final agreement transition happens at store opening (§3.6): the agreement that delivered the store moves `DELIVERED → COMPLETED`, and its accrued `penalty_cents` becomes a penalty credit on the program ledger, available to reduce the effective cost of a `NEW_BUILD` capital project for that store (§3.8).

### 3.5. Distribution: Centers, Assignments, Stem Cost, and Route Plans

A `NETWORK_PLANNER` registers distribution centers within a program by `rollout_program_id`, `name`, and `store_capacity` — the maximum number of stores the DC may serve, which must be greater than 0. DC registration is not gated on the program being `ACTIVE`. Each DC tracks `assigned_store_count`, the number of `ACTIVE` assignments pointing at it (counting existing-store and rollout-store assignments alike), and `remaining_capacity`, which is always `store_capacity` minus `assigned_store_count`.

Assigning a DC to a store is a `NETWORK_PLANNER` operation supplying `rollout_program_id`, `store_id`, `distribution_center_id`, `stem_miles` (the one-way road miles from DC to store, which must be greater than 0), and `deliveries_per_week` (the baseline weekly delivery frequency before route planning, at least 1). The DC reference must resolve inside the program, else `ERR_BAD_REFERENCE`, and the DC must have `remaining_capacity` of at least 1, else `ERR_DC_CAPACITY_EXCEEDED`; this capacity check fires before any supersession of the store's prior assignment, so reassigning a store to a DC with no spare capacity fails even when the supersession would free a slot elsewhere. Assignment is permitted for a store in any status (existing stores included) and is not gated on the program being `ACTIVE`. A store carries at most one `ACTIVE` assignment: creating a new assignment supersedes the prior `ACTIVE` one (its status becomes `SUPERSEDED` and the old DC's `assigned_store_count` decreases by 1), while the new assignment is born `ACTIVE`, the new DC's `assigned_store_count` increases by 1, and the store's `stem_miles` is copied from the assignment.

Each assignment computes `stem_cost_cents_per_week` once, at creation, from the store's then-current `weekly_case_volume_base` and `volume_index` (a store whose `weekly_case_volume_base` has not been set yet counts as 0 and therefore takes the low-volume variant); the computed cost is not revisited when the store's volume later changes. The standard cost is `stem_miles` doubled (round trip), multiplied by 285 cents per mile, multiplied by `deliveries_per_week`. When the store's effective weekly case volume — `weekly_case_volume_base` multiplied by `volume_index` — is below 1,800 cases, the store runs sub-truckload, and the low-volume variant applies: the standard cost multiplied by 1.25, rounded half up to whole cents. Stores at or above 1,800 effective weekly cases pay the plain standard rate.

Route planning turns an assignment into a concrete self-distribution schedule. Planning or replanning a store requires an `ACTIVE` DC assignment — without one the request fails with `ERR_NO_ACTIVE_ASSIGNMENT` — and is performed by a `NETWORK_PLANNER` supplying `rollout_program_id` and `store_id`. Route planning is not gated on the program being `ACTIVE`. The plan computes the store's effective weekly cases (`weekly_case_volume_base` times `volume_index`), then sets `deliveries_per_week` to the number of 1,800-case truckloads needed — the weekly cases divided by 1,800, rounded up to a whole number, but never fewer than 1 delivery per week. `cases_per_truck` is the weekly cases divided by the planned delivery count, rounded up. `truck_fill_pct` is the cases per truck expressed as a percentage of the 1,800-case capacity, rounded half up to two decimal places. A weekly cost is assembled per delivery and multiplied by the delivery count: each delivery costs the round-trip mileage (`stem_miles` doubled, times 285 cents per mile) plus a 35,000-cent per-stop charge, plus a low-fill surcharge of 15,000 cents that applies to every delivery whenever `truck_fill_pct` falls below 55. The result lands on the plan as `weekly_cost_cents`. Each store carries at most one `ACTIVE` route plan: replanning supersedes the prior `ACTIVE` plan and publishes the new one as `ACTIVE`.

### 3.6. Grand-Opening Planning, Locking, and Execution

Once a store holds an executed agreement, an `OPERATIONS_LEAD` creates its opening plan by supplying `rollout_program_id`, `store_id`, the planned `opening_date`, and a `peak_season` flag indicating whether the opening lands in the peak season window. Creation requires an `EXECUTED` agreement on the store — without one the request fails with `ERR_STORE_PRECONDITION` — and the calendar must leave room for delivery: the agreement's `committed_delivery_date` must be at most 30 days after the planned `opening_date`, else `ERR_STORE_PRECONDITION`. The date itself must sit at least 45 days in the future relative to the program's logical clock; a nearer date fails with `ERR_OPENING_TOO_EARLY`. A store carries at most one opening plan per cycle in `PLANNED` or `LOCKED` status; a second live plan fails with `ERR_DUPLICATE_ACTIVE`. For this endpoint the checks fire in this order, overriding the generic §2.11 cascade: the program-activity gate, then the 45-day clock gate, then the two agreement-driven store preconditions, and the singleton check last.

Two derived dates are computed at creation: `fixture_kit_ship_date`, exactly 21 days before `opening_date`, and `inventory_push_date`, exactly 10 days before `opening_date`. The plan also computes its grand-opening labor. Base hours depend on the store's `format_type`: 220 hours for `TRADITIONAL`, 340 for `DG_FRESH`, 520 for `DG_MARKET`. When `peak_season` is true, the base is uplifted by 15 percent — multiplied by 1.15 and rounded up to whole hours — to produce `labor_hours`; otherwise `labor_hours` is the base. `labor_cost_cents` is the labor hours multiplied by the labor rate of 2,400 cents per hour. The store's `opening_date` is copied from the plan at creation. The plan is born `PLANNED`.

Locking freezes the calendar, moving the plan `PLANNED → LOCKED`; a plan in any other status fails with `ERR_INVALID_STATE`. Locking requires the store to be in `SITE_CONTROL` — any other store status fails with `ERR_OPENING_PLAN_STATE` — and requires the store to currently hold an `EXECUTED` agreement, without which the lock fails with `ERR_STORE_PRECONDITION`; that agreement must then promise delivery no later than the fixture kit's ship date: the `committed_delivery_date` must be on or before `fixture_kit_ship_date`, so fixtures arrive before building-delivery pressure, else the lock fails with `ERR_FIXTURE_LEAD_TIME`. While `LOCKED`, the `opening_date` is immutable. Unlocking returns the plan `LOCKED → PLANNED` and unfreezes the calendar; it is permitted while the store is `SITE_CONTROL` or `PROPOSED` — a store in any other status fails with `ERR_INVALID_STATE`.

Execution performs the grand opening, moving the plan `LOCKED → EXECUTED`; a plan in any other status fails with `ERR_INVALID_STATE`. Execution requires the store to be `DELIVERED` and the delivering agreement to be in `DELIVERED` status — a store or agreement in any other status fails with `ERR_INVALID_STATE` — and the program's logical clock must have reached at least 3 days before `opening_date`; an earlier attempt fails with `ERR_OPENING_TOO_EARLY`. Execution cascades across three records: the agreement moves `DELIVERED → COMPLETED` and its accrued `penalty_cents` posts to the program ledger as a penalty credit available to `NEW_BUILD` capital scoring; the store moves `DELIVERED → OPEN`; and a `STORE_OPENED` event is appended to the program log with the opening date in its payload. Plans may also be cancelled without execution: a plan in `PLANNED` or `LOCKED` moves to `CANCELLED` when the store is killed or when a delivery lands 30 or more days late (§3.4).

### 3.7. Cannibalization Studies

Before capital is committed to a new store near the existing fleet, a `FINANCE_ANALYST` authors a cannibalization study for the subject store by supplying `rollout_program_id`, `store_id`, and `overlap_entries` — a non-empty array of entries, each pairing an `existing_store_id` with an `overlap_weight`. The subject store itself must exist in the program but may be in any status; its reference is validated before the program-activity gate fires. Every entry's existing store must belong to the same program, must be in `OPEN` or `EXISTING` status, and must have `open_year_sales_cents` recorded; a missing, out-of-program, out-of-state, or sales-less reference fails with `ERR_BAD_REFERENCE`. Each `overlap_weight` must be greater than 0 and at most 1 — a well-typed weight outside that range fails as `ERR_VALIDATION` — and no `existing_store_id` may appear twice in the array, a duplication failing as `ERR_INVALID_REQUEST`. A store carries one live study at a time: creating a new study supersedes the store's prior study whether that prior study was `DRAFT` or `FINAL`, and when a `FINAL` study is superseded, capital-project approval gating re-targets the newest `FINAL` study.

The study's sales-transfer computation proceeds entry by entry, and the rounding order is pinned: round per line, then sum. For each entry, the transferred sales are the existing store's `open_year_sales_cents` multiplied by the entry's `overlap_weight` multiplied by the program's `cannibalization_coefficient`, rounded half up to whole cents. The entry's impact percentage is that rounded transferred amount divided by the same `open_year_sales_cents`, expressed as a percentage and rounded half up to two decimal places (an existing store whose recorded sales are 0 contributes an impact percentage of 0.0). The total transferred is the sum of the per-entry transferred amounts (already rounded per line), and `transfer_pct` is that total divided by the new store's `projected_revenue_cents`, expressed as a percentage and rounded half up to two decimal places (0.0 when the subject store has no projected revenue).

The `recommendation` falls into one of three bands. It is `BLOCKED` when any entry's impact percentage exceeds 20 or the aggregate `transfer_pct` exceeds 15. Failing that, it is `MITIGATE` when any entry's impact percentage exceeds 12 or `transfer_pct` exceeds 8. Otherwise it is `PROCEED`. Finalizing a study moves it `DRAFT → FINAL` and locks it as the reference for capital-project approval gating — but a study whose recommendation is `BLOCKED` cannot be finalized and fails with `ERR_CANNIBALIZATION_BLOCKED`. A sensitivity variant exists for reporting only: it computes each entry's transfer as the existing store's sales multiplied by the entry's weight multiplied by the average of half the program coefficient and half the entry's weight — a formula that weights heavily-overlapped stores more heavily — and is exposed alongside the primary figures when a study is read with the `variant` query parameter set to `symmetric_overlap`. The variant appears as an additional `symmetric_overlap` object on the read response, carrying its own `overlap_entries` (each with `existing_store_id`, `overlap_weight`, and `transferred_cents` — no impact percentages), `total_transferred_cents`, and `transfer_pct`. The sensitivity variant never feeds the recommendation, which always uses the sales-transfer formula.

### 3.8. Capital Projects: Remodels, Relocations, and New Builds

The capital pipeline arbitrates between three kinds of investment. A `FINANCE_ANALYST` originates a capital project by supplying `rollout_program_id`, the `kind` — `REMODEL`, `RELOCATION`, or `NEW_BUILD` — and the subject `store_id`; an unrecognized `kind` fails as `ERR_INVALID_REQUEST`. Project creation is not gated on the program being `ACTIVE`. A `REMODEL` or `RELOCATION` project requires an `EXISTING` store; a `NEW_BUILD` project requires a `PROPOSED` store that has no agreement in `ACTIVE` or `EXECUTED` status. A subject-store reference that is missing, in the wrong state, or outside the program fails with `ERR_BAD_REFERENCE`. Cost inputs depend on kind: a `RELOCATION` project must carry `project_cost_cents`, a `REMODEL` project must carry `remodel_cost_cents`, and both may carry `projected_uplift_cents`, the projected annual revenue uplift; `projected_uplift_cents` is ignored for `NEW_BUILD`, whose uplift derives from the store's own `projected_revenue_cents`. For `NEW_BUILD`, the effective cost `new_build_cost_cents` is computed, not supplied: it is the store's `build_cost_cents` reduced by the sum of penalty credits from the store's `COMPLETED` agreements, and zero when no agreement has completed; it is computed at creation and recomputed again at submission. The project begins in `DRAFT`, with `decided_at`, `rank`, `submitted_by`, and `capital_score` all null until the workflows that set them run.

Submission moves the project `DRAFT → SUBMITTED` and computes its `capital_score`; a project in any other status fails with `ERR_INVALID_STATE`. Submission requires an `ACTIVE` program (`ERR_PROGRAM_NOT_ACTIVE` otherwise) and a positive cost basis for the kind: `remodel_cost_cents` present and greater than 0 for `REMODEL`, `project_cost_cents` present and greater than 0 for `RELOCATION`, and a `new_build_cost_cents` greater than 0 for `NEW_BUILD`; a missing or non-positive cost basis fails as `ERR_VALIDATION`. The status check and the program-activity gate fire before the cost-basis validation. A `NEW_BUILD` submission additionally requires the subject store to hold a `FINAL` cannibalization study that has not been superseded; without one the submit fails with `ERR_STUDY_NOT_FINAL`. Submission records the submitting analyst's `X-User-ID` on the project as `submitted_by`. The score itself is a three-year net-present-value ratio: the uplift — `projected_uplift_cents` for remodels and relocations, the store's `projected_revenue_cents` for new builds — is multiplied by 3 and reduced by the effective cost to give the NPV in cents; `capital_score` is the NPV divided by the effective cost, expressed as a percentage, multiplied by a kind multiplier — 1.1 for `REMODEL`, 0.9 for `RELOCATION`, 1.0 for `NEW_BUILD` — and rounded half up to two decimal places.

Decisions belong to `PROGRAM_ADMIN` and move a `SUBMITTED` project to `APPROVED` or `REJECTED` according to the `decision` supplied, which must be spelled exactly `APPROVE` or `REJECT`; any other value fails as `ERR_INVALID_REQUEST`, and a project in any status other than `SUBMITTED` fails with `ERR_INVALID_STATE`. The decision is an optimistic-concurrency write on the program: the request must carry `expected_program_version` matching the program's current `version`, else it is rejected with `ERR_STALE_VERSION` (HTTP 412), because another decision or commitment may have moved the budget since the caller last read it; the decision itself increments the program's `version` by 1. Segregation of duties is enforced first among the business checks: the deciding `PROGRAM_ADMIN` must not be the `FINANCE_ANALYST` recorded in `submitted_by`; a match fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The comparison is on the raw `X-User-ID` header values, so if the deciding request carries no `X-User-ID` and `submitted_by` was recorded as absent, the two compare equal and the decision is rejected. Approval then checks the budget: the project's effective cost — `remodel_cost_cents`, `project_cost_cents`, or `new_build_cost_cents` according to kind — must not exceed the program's `available_capital_cents`, else `ERR_CAPITAL_BUDGET_EXCEEDED`. An approval commits capital: the program's `committed_capital_cents` increases by the effective cost. Every decision, whether approval or rejection, stamps `decided_at` with the decision timestamp and recomputes `rank` across all decided (`APPROVED` or `REJECTED`) projects in the program: projects sort by `capital_score` descending, with ties broken by `decided_at` ascending so earlier decisions rank first. A project in `DRAFT` or `SUBMITTED` may instead be cancelled by a `FINANCE_ANALYST`, moving it to `CANCELLED` with no further effect; a project in any other status fails with `ERR_INVALID_STATE`, and cancellation is not gated on the program being `ACTIVE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The API is mounted under `/rollouts`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rollouts` | Create a rollout program (DRAFT) | PROGRAM_ADMIN |
| GET | `/rollouts` | List rollout programs (paginated) | Any |
| POST | `/rollouts/_clock-set` | Set a program's logical clock | PROGRAM_ADMIN |
| GET | `/rollouts/{pid}` | Get a rollout program | Any |
| POST | `/rollouts/{pid}/activate` | Activate program (DRAFT → ACTIVE) | PROGRAM_ADMIN |
| POST | `/rollouts/{pid}/deactivate` | Return program to DRAFT; blocked by mid-pipeline stores | PROGRAM_ADMIN |
| POST | `/rollouts/{pid}/close` | Close program (terminal); blocked by undecided projects or mid-pipeline stores | PROGRAM_ADMIN |
| GET | `/rollouts/program-events` | List rollout events in sequence order; filter by program | Any |
| PATCH | `/rollouts/{pid}/settings` | Update program settings (coefficient, budget) — ACTIVE only | PROGRAM_ADMIN |
| POST | `/rollouts/trade-areas` | Create a trade area (SCREENING) | PROGRAM_ADMIN |
| GET | `/rollouts/trade-areas` | List trade areas (paginated; optional status filter) | Any |
| GET | `/rollouts/trade-areas/{taid}` | Get a trade area by id | Any |
| PATCH | `/rollouts/trade-area-updates` | Refresh market data for a trade area (SCREENING/REJECTED only) | PROGRAM_ADMIN |
| POST | `/rollouts/trade-areas/{taid}/screen` | Run or re-run trade-area scoring (OCC on TradeArea) | PROGRAM_ADMIN |
| POST | `/rollouts/stores` | Create a pipeline store or register an EXISTING store | PROGRAM_ADMIN |
| GET | `/rollouts/stores` | List stores (paginated; filterable) | Any |
| GET | `/rollouts/stores/{sid}` | Get a store by id | Any |
| PATCH | `/rollouts/stores/{sid}` | Update volume_index (PROPOSED stores only) | NETWORK_PLANNER |
| POST | `/rollouts/stores/{sid}/select-format` | Run format selection for a PROPOSED store (OCC on Store) | REAL_ESTATE_MANAGER |
| POST | `/rollouts/stores/{sid}/kill` | Kill a pipeline store; cascades assignments, plans, capital | REAL_ESTATE_MANAGER |
| POST | `/rollouts/stores/{sid}/record-sales` | Record first-year sales on an EXISTING store | FINANCE_ANALYST |
| POST | `/rollouts/developers` | Register a build-to-suit developer | PROGRAM_ADMIN |
| GET | `/rollouts/developers` | List developers | Any |
| GET | `/rollouts/developers/{devid}` | Get a developer by id | Any |
| POST | `/rollouts/site-agreements` | Create a site control agreement (DRAFT) for a PROPOSED store | REAL_ESTATE_MANAGER |
| GET | `/rollouts/site-agreements` | List site control agreements (filterable) | Any |
| GET | `/rollouts/site-agreements/{agid}` | Get a site control agreement by id | Any |
| POST | `/rollouts/site-agreements/{agid}/execute` | Execute agreement; store → SITE_CONTROL | REAL_ESTATE_MANAGER |
| POST | `/rollouts/site-agreements/{agid}/activate` | Activate agreement; developer capacity enforced; capital committed | REAL_ESTATE_MANAGER |
| POST | `/rollouts/site-agreements/{agid}/deliveries` | Record building delivery; computes lateness and penalty | REAL_ESTATE_MANAGER |
| POST | `/rollouts/site-agreements/{agid}/terminate` | Terminate agreement; kill fee and capital release per state | REAL_ESTATE_MANAGER |
| POST | `/rollouts/distribution-centers` | Register a distribution center | NETWORK_PLANNER |
| GET | `/rollouts/distribution-centers` | List distribution centers | Any |
| GET | `/rollouts/distribution-centers/{dcid}` | Get a distribution center by id | Any |
| POST | `/rollouts/dc-assignments` | Assign a DC to a store; supersedes prior; computes stem cost | NETWORK_PLANNER |
| GET | `/rollouts/dc-assignments` | List DC assignments (filterable) | Any |
| GET | `/rollouts/dc-assignments/{asgid}` | Get a DC assignment by id | Any |
| POST | `/rollouts/route-plans` | Plan or replan self-distribution for a store | NETWORK_PLANNER |
| GET | `/rollouts/route-plans` | List route plans (filterable) | Any |
| GET | `/rollouts/route-plans/{rpid}` | Get a route plan by id | Any |
| POST | `/rollouts/opening-plans` | Create the grand-opening plan (PLANNED) | OPERATIONS_LEAD |
| GET | `/rollouts/opening-plans` | List opening plans (filterable) | Any |
| GET | `/rollouts/opening-plans/{opid}` | Get an opening plan by id | Any |
| POST | `/rollouts/opening-plans/{opid}/lock` | Lock the opening calendar | OPERATIONS_LEAD |
| POST | `/rollouts/opening-plans/{opid}/unlock` | Unlock the opening calendar | OPERATIONS_LEAD |
| POST | `/rollouts/opening-plans/{opid}/execute` | Execute the grand opening; store → OPEN | OPERATIONS_LEAD |
| POST | `/rollouts/cannibalization-studies` | Create a cannibalization study (DRAFT); supersedes prior | FINANCE_ANALYST |
| GET | `/rollouts/cannibalization-studies` | List cannibalization studies (filterable) | Any |
| GET | `/rollouts/cannibalization-studies/{csid}` | Get a cannibalization study by id | Any |
| POST | `/rollouts/cannibalization-studies/{csid}/finalize` | Finalize a study; blocked when recommendation is BLOCKED | FINANCE_ANALYST |
| POST | `/rollouts/capital-projects` | Create a capital project (DRAFT) | FINANCE_ANALYST |
| GET | `/rollouts/capital-projects` | List capital projects (paginated; filterable) | Any |
| GET | `/rollouts/capital-projects/{cpid}` | Get a capital project by id | Any |
| POST | `/rollouts/capital-projects/{cpid}/submit` | Submit a project; computes capital score | FINANCE_ANALYST |
| POST | `/rollouts/capital-projects/{cpid}/decide` | Approve or reject (OCC on Rollout; segregation of duties) | PROGRAM_ADMIN |
| POST | `/rollouts/capital-projects/{cpid}/cancel` | Cancel a project | FINANCE_ANALYST |
| GET | `/rollouts/program-events/{evid}` | Get a program event by id | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_PROGRAM_HAS_ACTIVE_STORES` | 409 |
| `ERR_PROGRAM_CLOSE_BLOCKED` | 409 |
| `ERR_TRADE_AREA_NOT_QUALIFIED` | 409 |
| `ERR_NO_FEASIBLE_FORMAT` | 422 |
| `ERR_STORE_PRECONDITION` | 409 |
| `ERR_SITE_CONTROL_ACTIVE` | 409 |
| `ERR_DUPLICATE_ACTIVE` | 409 |
| `ERR_DEVELOPER_CAPACITY_EXCEEDED` | 409 |
| `ERR_DC_CAPACITY_EXCEEDED` | 409 |
| `ERR_FIXTURE_LEAD_TIME` | 409 |
| `ERR_OPENING_TOO_EARLY` | 409 |
| `ERR_CANNIBALIZATION_BLOCKED` | 409 |
| `ERR_STUDY_NOT_FINAL` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CAPITAL_BUDGET_EXCEEDED` | 409 |
| `ERR_BAD_REFERENCE` | 422 |
| `ERR_NO_ACTIVE_ASSIGNMENT` | 409 |
| `ERR_OPENING_PLAN_STATE` | 409 |
