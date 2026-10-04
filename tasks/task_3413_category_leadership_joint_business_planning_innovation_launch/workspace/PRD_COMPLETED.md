# Category Leadership JBP API — Product Requirements Document

## 1. Introduction

Joint business planning between a global manufacturer and its retail partners lives or dies on follow-through. Growth targets are agreed in a conference room and then drift; promotional calendars overlap; trade funds leak through unverified deduction claims; innovation launches miss their distribution build and nobody notices until the post-launch review. This document specifies the Category Leadership JBP API, a system that formalizes the entire manufacturer–retailer planning cycle — from the first proposed growth target, through a bounded counter-offer negotiation and activation, into execution tracking of events, shelf changes, forecasts and phase-gated launches, and finally into the post-launch reckoning that decides whether a product keeps its shelf space.

The manufacturer operates here in a category-captain capacity. It analyzes total category performance — including competitor data where the category's data-governance scope permits — recommends shelf assortment and space changes to the retailer, pencils a promotional calendar whose events are funded out of a trade fund, plans innovation launches with capacity, distribution and trade spending phased across a launch year, and administers promotion funding split between everyday price support and event-based features. A supply-chain collaborator publishes weekly baseline forecasts the retailer can commit against; a finance function posts accruals and resolves retailer deduction claims; and a joint scorecard grades each launch's delisting risk once enough selling time has elapsed.

Because six peer roles act on the same shared plan at different moments, the system leans on explicit lifecycle state machines, a server-owned logical clock that every time-windowed rule reads, optimistic concurrency at the one genuinely racy write, and a dual-basis trade-fund ledger that keeps accrual and cash views of every cent. All resources are mounted under the `/jbp` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names their operational capacity. The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `ManufacturerPlanner`, `RetailerBuyer`, `CategoryAdvisor`, `SupplyChainPlanner`, and `FinanceAnalyst`. A request missing either header, or carrying a role name outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles divide the joint-planning work as peers rather than as a hierarchy:

- `PlatformAdmin` is the manufacturer-side platform operator. It seeds reference data — creating retailers and categories — and is the only role allowed to drive the server's logical clock. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `ManufacturerPlanner` is the manufacturer's joint-business planner. It owns plan creation and activation, the promotional calendar, launches and their phase gates, price-pack proposals, and the opening of post-launch reviews. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `RetailerBuyer` is the retail-side buyer — the counterparty in negotiation and the decision-maker for analyses, shelf recommendations, and price-pack decisions; it also files deduction claims, commits forecast volumes, and finalizes performance reviews. When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting `Retailer`: ownership checks on any resource compare the `retailer_id` of the `JointBusinessPlan` that owns the target resource — reached either directly through a plan path parameter or through the target entity's plan, launch, or fund chain — against `X-User-ID`. A mismatch is rejected with `ERR_RETAILER_SCOPE_MISMATCH` (HTTP 403). The same scope restriction applies to reads: a `RetailerBuyer` browsing list or detail endpoints sees only its own retailer's data.
- `CategoryAdvisor` is the manufacturer category-captain analyst. It produces category analyses and shelf recommendations and later audits their in-store implementation. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `SupplyChainPlanner` is the manufacturer supply-chain collaborator; it publishes the weekly baseline forecasts. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `FinanceAnalyst` is the manufacturer trade-finance analyst; it posts fund accruals and resolves deduction claims. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100 — a `limit` outside the range 1 to 100 is a body-shape violation rejected with `ERR_VALIDATION` (HTTP 400). The `offset` parameter says how many items to skip and defaults to 0. A negative `offset`, or a non-integer `limit` or `offset`, is likewise a body-shape violation rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Shared Logical Clock

The server does not trust wall-clock time. Instead it maintains a single logical clock, and every time-windowed rule in this document — implementation deadlines, launch-date readiness, review eligibility — evaluates against that clock and nothing else. Before any operator has touched it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time on its own.

An admin-only, test-driving capability sets the clock: a `PlatformAdmin` supplies a `to_iso8601` instant, and a successful call answers 200 OK with the resulting `current_utc`. The clock is monotonic non-decreasing — an attempt to set it to an instant earlier than its current reading is rejected with `ERR_VALIDATION` (HTTP 400). Every subsequent time-gated precondition in the system evaluates against the newly set instant, so advancing the clock is the only way review windows open, implementation deadlines lapse, and launch dates arrive.

### 2.5. Common Resource Properties

Every primary resource in the system — `Retailer`, `Category`, `JointBusinessPlan`, `PromotionalEvent`, `CategoryAnalysis`, `ShelfRecommendation`, `InnovationLaunch`, `LaunchPhase`, `TradeFund`, `Deduction`, `Forecast`, `PricePackDecision`, and `PerformanceReview` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created, stamped from the server's logical clock (§2.4) rather than wall-clock time.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource, likewise stamped from the logical clock.
- `version` (integer): a system-managed integer set to 1 at creation and incremented by exactly 1 on every mutation of the resource, including the automatic transitions the server performs on its own (supersessions, expirations, cascades). This is the field optimistic concurrency control reads.

All thirteen entity types carry all four fields; none omits `updated_at` or `version`. Because a single client-visible action can cascade — a delist retiring price-pack decisions, a new forecast superseding an old one — every entity touched by such a cascade registers its own `version` increment and `updated_at` refresh.

### 2.6. Nested Resource Retrieval and Path Validation

The API is organized as a shallow hierarchy: plans hang off retailers and categories, and everything operational — events, analyses, shelf recommendations, launches and their phases, the fund and its deductions, forecasts, price-pack decisions, performance reviews — hangs off a plan or off one of the plan's children. Any request whose path contains several identifiers is validated left to right. The server first resolves the retailer or category referenced in a creation body, then the plan in the path, then the child entity named deeper in the path, and it stops at the first identifier that does not resolve.

The not-found error mirrors that ordering. A `retailer_id` in a plan-creation body that does not resolve yields `ERR_RETAILER_NOT_FOUND` (HTTP 404); an unresolvable `category_id` in the same body yields `ERR_CATEGORY_NOT_FOUND` (HTTP 404); an unresolvable plan id in a path yields `ERR_PLAN_NOT_FOUND` (HTTP 404); and a deeper child id — an event, analysis, shelf recommendation, launch, phase, fund, deduction, forecast, price-pack decision, or review — that does not resolve under its named parent yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A child id that exists but belongs to a different parent is reported as not found under the requested parent, never as a cross-parent leak.

### 2.7. Money, Percentages, and Rounding Discipline

All monetary quantities in the API are carried as integer cents — budgets, prices, accruals, reservations, settlements — so no floating-point drift can enter the ledger. Wherever a computation produces a fractional cent, it is rounded half-up to a whole cent, and the rounding points are pinned per calculation rather than left to the implementer: the fund accrual rounds each period's credit and each bucket share to whole cents before anything is summed; the event cost estimate rounds half-up exactly once, at the end. Per-unit prices round differently on purpose: a pack's `price_per_unit_cents` is its `list_price_cents` divided by its `unit_count` rounded UP to the next whole cent, never merely to the nearest one.

Percentages travel as numbers and land at two levels of precision. Attainment, bias, and distribution-projection outputs are rounded half-up to exactly 2 decimal places. The delisting risk score is a whole number between 0 and 100 inclusive, produced by a single round-half-up applied to the weighted raw total — the underlying components keep their full precision until that one final rounding. Input-side percentages obey their stated bounds exactly, including at the boundary: a check described as "at most 15" passes at exactly 15.

### 2.8. Optimistic Concurrency Control

Exactly one write in the API is guarded by optimistic concurrency control: the creation of a new shelf recommendation. That request must carry `expected_plan_version`, set to the `version` of the owning `JointBusinessPlan` the client last observed. The check is exact equality against the plan's current `version`: if the plan's current `version` has advanced past the submitted value — or the submitted value otherwise fails to match it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is created. The rule exists because a successful create legitimately supersedes the plan's currently `PROPOSED` recommendation to `WITHDRAWN`; a client working from a stale read would silently withdraw a recommendation it never saw. No other endpoint in the API accepts or requires a version field — every other write is serialized purely by the state machines.

### 2.9. The Validation Pipeline and Its Priority Order

When a request violates several rules at once, the error it receives is not arbitrary. The server evaluates checks in a fixed priority order and reports the first failure it encounters; a lower-priority problem is masked until every higher-priority problem is resolved. The pipeline runs as follows:

1. Authentication: both headers present and the role name recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role appears in the endpoint's role list, else `ERR_FORBIDDEN`.
3. Retailer scope: for any request made as `RetailerBuyer`, `X-User-ID` equals the `retailer_id` of the plan that owns the target resource, else `ERR_RETAILER_SCOPE_MISMATCH`.
4. Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored — including the pagination `limit` range, the promotional discount-depth cap, the shelf space-change cap, the store-count range, the rule that `sku_adds` and `sku_drops` must not overlap, positive committed volumes, a positive sales target, review and event windows whose end is strictly after their start, the `YYYY-MM` accrual period format, and the requirement that a price-pack's `channel` belongs to the plan retailer's channel set. Any breach is `ERR_VALIDATION` (HTTP 400).
5. Growth-target range: a well-formed `growth_target_pct` that is still outside its negotiated bounds is rejected with `ERR_GROWTH_TARGET_OUT_OF_RANGE` (HTTP 400) on plan creation and on every negotiation move.
6. Existence: path and body identifiers resolve left to right per §2.6, else the matching not-found error.
7. State fit: the target entity sits in a from-state that the requested transition permits, else `ERR_INVALID_STATE` (HTTP 409). This is also the check that catches a suspended retailer at plan activation, an event lock against a plan in the wrong lifecycle position when no more specific error applies, and a shelf-recommendation verification attempted on a recommendation that is not `IMPLEMENTING`.
8. Terminality: an entity already in a terminal state rejects every further transition with `ERR_ALREADY_TERMINAL` (HTTP 409). Terminality is the more specific rule and pre-empts state fit wherever both would bite: a terminal entity always reports `ERR_ALREADY_TERMINAL`, never `ERR_INVALID_STATE`, whatever transition is attempted.
9. Mover mapping: negotiation and decision calls honor whose move it is — from `PROPOSED` only the `RetailerBuyer` may move, from `COUNTERED` only the `ManufacturerPlanner` — else `ERR_NOT_YOUR_MOVE` (HTTP 403).
10. Negotiation budget: a negotiation move attempted after the round budget is spent fails with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` and expires the plan in the same breath (see §3.1).
11. Concurrency: the shelf-recommendation create's `expected_plan_version` matches the plan's current `version`, else `ERR_STALE_VERSION`.
12. Activation gating: event locking, forecast creation, and launch creation all demand an `ACTIVATED` plan, and shelf-recommendation creation demands a plan in `ACCEPTED` or `ACTIVATED`; violations are `ERR_PLAN_NOT_ACTIVATED` (HTTP 409).
13. Advisory prerequisite: shelf-recommendation creation additionally requires an accepted category analysis on the plan, else `ERR_ANALYSIS_NOT_ACCEPTED` (HTTP 409).
14. Through 34. The remaining domain rules — phase-gate completeness before launch, phase editability, forecast publishability, the ordered shelf-verification checks, the data-governance boundary, the uniqueness rules for plans, reviews, claims, and accrual periods, the distribution and phase-budget caps, the club-pack minimum, the channel-conflict pair (pairwise gap first, e-commerce undercut second), promotional overlap, week alignment, fiscal-year fit, launch separation, launch-date readiness, review timing, fund sufficiency, and the activation split floor — each fire at their own priority, and each is described next to the workflow it guards in §3. Where two of these rules could bite the same request, the one whose check is listed first in this document's pipeline order wins.

Two ordering commitments deserve emphasis because tests lean on them. Executing a launch checks the phase gates before it checks the calendar: a launch with an unpassed gate reports `ERR_PHASE_GATES_INCOMPLETE` even if its date has also not arrived, and only a fully gated launch can ever see `ERR_LAUNCH_DATE_NOT_REACHED`. Approving a price-pack decision checks the pairwise channel price-gap rule before the e-commerce undercut rule, so a decision that violates both reports `ERR_CHANNEL_CONFLICT`, never `ERR_ECOMMERCE_UNDERCUT`.

### 2.10. Plan Lifecycle Discipline and Terminal States

Every entity in the system moves through an explicit state machine, and terminal states are absorbing. A plan in `REJECTED` or `EXPIRED`, an event in `CANCELLED`, an analysis in `ACCEPTED` or `RETURNED`, a shelf recommendation in `REJECTED`, `VERIFIED`, `STALLED`, or `WITHDRAWN`, a launch in `REVIEWED` or `DELISTED`, a deduction in `SETTLED`, `REJECTED`, or `WRITTEN_OFF`, a price-pack decision in `REJECTED` or `RETIRED`, and a review in `FINALIZED` all refuse every further transition with `ERR_ALREADY_TERMINAL`. A forecast's publication axis ends at `SUPERSEDED`, though its commitment axis is independent and survives supersession (see §3.7).

Two failures in the system deliberately couple an error response with a state change in the same request, and both are worth reading twice. A negotiation move attempted when the round budget is exhausted is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — and the plan still transitions to `EXPIRED`, version incremented, inside that same failed request. A shelf-recommendation verification attempted after its implementation deadline is rejected with `ERR_IMPLEMENTATION_STALLED` — and the recommendation still transitions to `STALLED`, version incremented, inside that same failed request. In both cases the client receives an error and the world has moved anyway; a subsequent read is the only way to see the new state.

### 2.11. Trade Fund Ledger Principles

Each activated plan owns exactly one trade fund, created at the moment of activation with every computed balance at zero. The fund is the single source of truth for promotion money and is kept under two accounting lenses at once. The accrual lens tracks what has been earned: `edlp_accrued_cents` and `event_accrued_cents` accumulate each posted period's bucket shares, while `total_invoiced_cents` accumulates the raw invoiced sales those shares were computed from. The cash lens shadows it: `edlp_cash_cents` and `event_cash_cents` accumulate the same period shares after a collection haircut, so the cash view of identical activity is always the smaller one whenever any share is positive. Money leaves the fund through two doors. Locking a promotional event reserves its estimated cost into `event_reserved_cents`, and cancelling a locked event releases exactly that amount back. Resolving a deduction settles money into `edlp_settled_cents` or `event_settled_cents` — including amounts the manufacturer absorbs on a write-off, which are booked into the settled ledger just the same.

Availability is derived, never stored inconsistently: the EDLP bucket's `edlp_available_cents` is what accrued minus what settled, and the event bucket's `event_available_cents` is what accrued minus what is currently reserved minus what has settled. Funding checks — locking an event, settling a deduction — always read these derived availabilities, so the ledger can never pay the same cent twice.

## 3. Business Logic & Workflows

### 3.1. Reference Data, Plan Negotiation, and Activation

Before any planning can happen, a `PlatformAdmin` seeds the two reference entities. A **Retailer** is created with a display `name`, a `country_code` given as an ISO 3166-1 alpha-2 code (carried as an opaque string — the server does not re-validate the alpha-2 format), and `channels` — a non-empty, duplicate-free array drawn from the channel alphabet `MASS`, `GROCERY`, `CLUB`, `ECOMMERCE`, and `CONVENIENCE` describing where the retailer trades. A retailer also carries a lifecycle `status` from `ACTIVE` and `SUSPENDED`, settable only at creation and defaulting to `ACTIVE`; it matters exactly once, at plan activation, where a suspended retailer blocks the transition. A **Category** is created with a `name` such as "Laundry Care" and an `advisory_scope` of either `FULL_CATEGORY` or `MANUFACTURER_ONLY`, defaulting to `FULL_CATEGORY` when omitted — the data-governance switch that decides whether competitor data may enter advisory analyses (see §3.3).

With reference data in place, a `ManufacturerPlanner` opens a **JointBusinessPlan** by naming the `retailer_id` and `category_id` it covers, a `fiscal_year` as an integer from 2026 through 2030 inclusive, the opening `growth_target_pct` proposal, a `weekly_baseline_cases` volume and an `avg_unit_net_price_cents` that together anchor later event cost estimates — both strictly positive. A body naming a retailer or category that does not exist is rejected with `ERR_RETAILER_NOT_FOUND` or `ERR_CATEGORY_NOT_FOUND` respectively. The growth target may range from -20 percent to 50 percent, both bounds inclusive, and the same bound is re-checked on every later negotiation move, with `ERR_GROWTH_TARGET_OUT_OF_RANGE` greeting any breach. A plan is born directly into `PROPOSED` with its `negotiation_round` at 1. Uniqueness is enforced across the joint calendar: at most one plan per combination of retailer, category, and fiscal year may exist in a non-terminal status — a duplicate attempt while a live sibling exists fails with `ERR_PLAN_ALREADY_EXISTS` (HTTP 409), though a plan whose predecessor ended `REJECTED` or `EXPIRED` is free to be re-created. Anyone reading a plan receives its `version`, which a category advisor will later need to capture before recommending shelf changes.

Negotiation is a bounded, alternating exchange. While the plan is `PROPOSED`, the `RetailerBuyer` of the plan's own retailer may counter: the call carries a new `growth_target_pct`, and on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`. While the plan is `COUNTERED`, the mirror leg belongs to the `ManufacturerPlanner`, whose re-proposal moves the plan `COUNTERED → PROPOSED` with the same field and round bookkeeping. Either party attempting to move out of turn — a retailer move from `COUNTERED`, a manufacturer move from `PROPOSED` — is refused with `ERR_NOT_YOUR_MOVE` (HTTP 403). The exchange is capped at a round budget of 6: when a negotiation move is attempted while the plan's `negotiation_round` has already reached 6, the request is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409), and in the very same failed request the plan auto-transitions to `EXPIRED` with its `version` incremented — the exhaustion error and the expiration are inseparable, whether the plan was sitting `PROPOSED` or `COUNTERED`.

Acceptance and rejection follow the same mover mapping. From `PROPOSED`, only the plan's own `RetailerBuyer` may decide: a `decision` of `ACCEPT` moves the plan `PROPOSED → ACCEPTED`, while `REJECT` moves it to the terminal `REJECTED`. From `COUNTERED`, only the `ManufacturerPlanner` may decide, accepting the retailer's counter into `ACCEPTED` or rejecting it into `REJECTED`. Every successful decision increments the plan's `version`, and a decide call by the wrong party fails with `ERR_NOT_YOUR_MOVE` just as a negotiation call would.

Activation is the manufacturer's final handshake. A `ManufacturerPlanner` activates an `ACCEPTED` plan by supplying the fund parameters `accrual_rate_pct` — the percent of invoiced sales that will accrue into the fund, which must be greater than 0 and at most 5 — and `edlp_split_pct`, the percent of each period credit routed to everyday-price support, an integer from 0 to 80 inclusive. The split floor protects the event program: because the event bucket must receive at least 20 percent of every period credit, an `edlp_split_pct` above 80 is rejected with `ERR_EVENT_SPLIT_TOO_LOW` (HTTP 422). Any other breach of these activation parameter ranges — an `accrual_rate_pct` outside (0, 5] or an `edlp_split_pct` below 0 — is a body-shape violation rejected with `ERR_VALIDATION` (HTTP 400). Activation also demands that the plan's retailer still be `ACTIVE`; attempting it against a `SUSPENDED` retailer fails with `ERR_INVALID_STATE`. On success the server creates the plan's one and only **TradeFund** — stamped with the plan's id, the locked `accrual_rate_pct` and `edlp_split_pct`, and every computed balance at zero — snapshots the negotiated target into the plan's `committed_growth_pct`, stamps `activated_at` from the logical clock (both fields null until this moment), moves the plan `ACCEPTED → ACTIVATED`, and increments its `version`. From this moment the fund parameters are immutable and the operational workflows of §3.2 onward unlock.

### 3.2. The Promotional Calendar and Event Funding

A `ManufacturerPlanner` pencils promotional events onto the plan's calendar at any time while the plan is alive — that is, while its status is `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `ACTIVATED`; a terminal plan refuses all new events with `ERR_ALREADY_TERMINAL`. Each **PromotionalEvent** is created under its plan with a `name`, an `event_type` drawn from `FEATURE`, `DISPLAY`, `PRICE_REDUCTION`, and `IN_STORE_DEMO`, a `start_date` taken at midnight UTC (the server parses any ISO 8601 instant and enforces no alignment on event dates), an `end_date` that must be strictly after the start, and a `discount_depth_pct` greater than 0 and at most 40 — the ceiling on how deep any event may discount. An event occupies the half-open interval from its `start_date` up to but not including its `end_date`, and the calendar forbids collisions: within one plan and one `event_type`, a new event whose interval intersects an existing `PENCILED` or `LOCKED` event is rejected with `ERR_PROMO_OVERLAP` (HTTP 409), while pure adjacency — one event's `end_date` equal to another's `start_date` — is expressly allowed. Events of different types, and events already `CANCELLED`, never block the calendar. Every event is born `PENCILED` with its `estimated_cost_cents` still null, and the plan's event list can be browsed filtered by `status` or `event_type`.

Locking is the moment an event becomes a financial commitment. When the `ManufacturerPlanner` locks a `PENCILED` event, the plan must first be `ACTIVATED` — locking against a plan in any other state fails with `ERR_PLAN_NOT_ACTIVATED` — and then the server computes the event's funding estimate. The baseline comes from the forecasts the retailer relationship has produced: among the plan's forecasts whose `pub_status` is `PUBLISHED` and whose week bucket contains the event's start — the bucket running from a `week_start` on or before the `start_date` through six days later — the one with the latest `week_start` wins, and no tie is possible because at most one `PUBLISHED` forecast exists per plan and week. When no forecast qualifies, the plan's own `weekly_baseline_cases` serves as the fallback baseline. The estimate itself is that baseline multiplied by the plan's `avg_unit_net_price_cents`, multiplied by the event's `discount_depth_pct`, divided by 100, with a single round-half-up to a whole cent applied at the very end. The result is persisted as the event's `estimated_cost_cents` and immediately stress-tested against the fund: if it exceeds the plan fund's `event_available_cents` at that instant, the lock is refused with `ERR_INSUFFICIENT_FUNDS` (HTTP 422). A successful lock moves the event `PENCILED → LOCKED`, adds the estimate to the fund's `event_reserved_cents` — which correspondingly lowers `event_available_cents` — and increments the event's `version`.

Cancellation is the compensating move, available to the `ManufacturerPlanner` from either live state. Cancelling a `PENCILED` event simply moves it to `CANCELLED` and increments its `version`; no money was ever reserved, so none moves. Cancelling a `LOCKED` event releases the reservation — the event's `estimated_cost_cents` is subtracted from the fund's `event_reserved_cents`, restoring availability — before the event lands `CANCELLED` with its `version` incremented. Lock-then-cancel is thus the compensating pair that keeps the fund's reservation invariant exact, and `CANCELLED` is terminal.

### 3.3. Category Advisory and Data Governance

Category-captain work begins with analysis. A `CategoryAdvisor` submits a **CategoryAnalysis** under a plan, carrying a `title`, a free-form `period_label` such as "2027-H1", the analyst-reported `total_category_growth_pct`, and the `manufacturer_share_pct` of category sales, expressed as a percent between 0 and 100 inclusive. The submission may also set `includes_competitor_data`, which defaults to false when omitted. The system's data-governance boundary sits exactly here: an analysis that incorporates competitor data is only lawful when the plan's category carries an `advisory_scope` of `FULL_CATEGORY`; submitting one with `includes_competitor_data` set to true against a `MANUFACTURER_ONLY` category is rejected with `ERR_GOVERNANCE_BOUNDARY` (HTTP 422). Every analysis carries a computed `competitor_share_pct`, derived as 100 minus the `manufacturer_share_pct`, so the manufacturer's view of the category always accounts for the full hundred points. Submission is not gated on the plan's lifecycle status: an analysis may be filed under a plan in any status, including a terminal one.

An analysis is born `SUBMITTED` and waits on the retailer. The `RetailerBuyer` of the plan's retailer decides it: a `decision` of `ACCEPT` moves it `SUBMITTED → ACCEPTED`, a `decision` of `RETURN` moves it `SUBMITTED → RETURNED`, and either way the record's `version` increments. Both outcomes are terminal; `RETURNED` in particular closes the record for good — a reworked analysis enters the system as a brand-new submission rather than a resurrection. Acceptance is more than courtesy: a plan must hold at least one `ACCEPTED` analysis before any shelf recommendation may be created against it (§3.4), and the plan's analysis list can be browsed filtered by `status`.

### 3.4. Shelf Assortment Recommendations and Implementation Tracking

With an accepted analysis in hand, the `CategoryAdvisor` turns insight into shelf action by submitting a **ShelfRecommendation** under the plan. The recommendation names a `title`, a `space_change_pct` — the recommended total shelf-space change for the manufacturer's portfolio, whose absolute value may not exceed 30 percent in either direction — and a `target_store_count`, an integer from 1 to 10000, recording how many stores must implement the change for it to count as verified. Two optional assortment arrays accompany it: `sku_adds`, the SKU codes to add, and `sku_drops`, the SKU codes to remove. Either may be empty and both default to empty, but they must never intersect — a SKU listed in both is a body-shape violation under `ERR_VALIDATION`.

This create is the API's single OCC-guarded write, and its guard ordering is fixed. After authentication, scope, body shape, and existence have passed, the server first checks `expected_plan_version` against the plan's current `version` and answers `ERR_STALE_VERSION` (HTTP 412) on a mismatch; only then does it check that the plan's status is `ACCEPTED` or `ACTIVATED` — anything else fails with `ERR_PLAN_NOT_ACTIVATED` — and only then that the plan holds at least one `ACCEPTED` category analysis, failing with `ERR_ANALYSIS_NOT_ACCEPTED` (HTTP 409) when none exists. The OCC rule exists because of what a successful create does to the incumbent: the plan's currently `PROPOSED` recommendation, if one exists, is auto-superseded to `WITHDRAWN` with its own `version` incremented, and the plan's `version` itself increments by 1, so the next advisor must read afresh before recommending again. The newcomer is born `PROPOSED`, with `accepted_at` and `verified_store_count` still null, and the plan's recommendation list can be browsed filtered by `status`.

The retailer then decides. A `RetailerBuyer` of the plan's retailer accepting a `PROPOSED` recommendation moves it `PROPOSED → IMPLEMENTING`, stamping `accepted_at` from the logical clock and incrementing its `version`; rejecting it moves it to the terminal `REJECTED`. Once `IMPLEMENTING`, the clock starts on the implementation SLA: the manufacturer has 90 days from `accepted_at` to see the change land in stores.

Verification is the `CategoryAdvisor`'s audit, and its three checks fire in a fixed order. Before any of them, the payload is body-shape checked: `implemented_store_count` must be present and a non-negative integer, else `ERR_VALIDATION`. First, the recommendation must actually be `IMPLEMENTING` — verifying a `PROPOSED` recommendation fails with `ERR_INVALID_STATE`, while a terminal recommendation refuses the attempt with `ERR_ALREADY_TERMINAL` per §2.10. Second, the elapsed logical time since `accepted_at` must not exceed the 90-day SLA — a verification attempted later is rejected with `ERR_IMPLEMENTATION_STALLED` (HTTP 409), and in the same failed request the recommendation auto-transitions to `STALLED`, terminal, with its `version` incremented; the error and the stall are inseparable. Third, the payload's `implemented_store_count` must be at least the recommendation's `target_store_count` — a within-SLA audit that falls short fails with `ERR_IMPLEMENTATION_INCOMPLETE` (HTTP 422) and changes nothing: the recommendation stays `IMPLEMENTING` for another attempt. A verification that passes all three moves the recommendation to the terminal `VERIFIED`, records the audited count into `verified_store_count`, and increments its `version`.

### 3.5. Innovation Launch Planning and Phase Gates

Innovation launches are planned against activated plans only. A `ManufacturerPlanner` creates an **InnovationLaunch** with a `product_name`, a `pack_family` key that will later link this launch to the price-pack decisions sharing the same family for delisting purposes, a `launch_date` taken at midnight UTC (likewise accepted as any ISO 8601 instant, with no alignment enforcement), and a strictly positive `total_trade_budget_cents` that funds the launch year. The plan must be `ACTIVATED` — otherwise `ERR_PLAN_NOT_ACTIVATED` — and two temporal rules then apply. The `launch_date`'s UTC calendar year must equal the plan's `fiscal_year`; a date outside it is rejected with `ERR_LAUNCH_OUTSIDE_FISCAL_YEAR` (HTTP 422). And the calendar must breathe: the new `launch_date` must sit at least 84 days away from the `launch_date` of every other launch of the same plan that is still `PLANNING` or already `LAUNCHED`, with a separation of exactly 84 days passing; a closer date fails with `ERR_LAUNCH_TOO_CLOSE` (HTTP 422).

Creation builds the launch's execution skeleton automatically: exactly four **LaunchPhase** children appear, each stamped with the owning launch's id as its `launch_id`, carrying `phase_index` 1 through 4 and, by index, the `phase_type` values `CAPACITY_BUILD`, `DISTRIBUTION_BUILD`, `TRADE_SPEND`, and `SUSTAIN`. All four are born `PENDING` with `distribution_target_pct`, `capacity_cases`, and `trade_spend_cents` all at 0. The launch itself is born `PLANNING`, its `budget_remaining_cents` initialized to the full `total_trade_budget_cents`, both distribution projections at 0, and `launched_at` null. The phase list always reads in `phase_index` ascending order.

Phasing the launch year is an iterative loop of revision and gate evaluation, both performed by the `ManufacturerPlanner`. Revising a phase patches any of `distribution_target_pct` — the incremental ACV distribution the phase builds, between 0 and 100 — `capacity_cases` of reserved production, and `trade_spend_cents` of allocated spending, each at least zero. A patch is only lawful while the phase is `PENDING` or `GATE_FAILED` and the launch is still `PLANNING`; anything else is refused with `ERR_PHASE_LOCKED` (HTTP 409). Two caps guard the write. The sum of `distribution_target_pct` across all of the launch's phases after the write must not exceed 100 percent — a breach fails with `ERR_DISTRIBUTION_SUM_EXCEEDED` (HTTP 422) — and the sum of `trade_spend_cents` across all phases after the write must fit within the launch's `total_trade_budget_cents`, equivalently the new spend must fit within `budget_remaining_cents` plus the phase's own current spend, else `ERR_PHASE_BUDGET_EXCEEDED` (HTTP 422). A successful patch applies the field updates, returns a `GATE_FAILED` phase to `PENDING` (a `PENDING` phase simply stays `PENDING`), recomputes the launch's `budget_remaining_cents` as the total budget minus the sum of phase spends, refreshes both distribution projections, and increments the phase's `version`.

Gate evaluation is the pass/fail exam each `PENDING` phase sits; evaluating a phase in any other state fails with `ERR_INVALID_STATE`. A phase passes its gate — moving `PENDING → GATE_PASSED` — exactly when the launch is still `PLANNING`, every lower-indexed phase of the launch has already passed (a condition vacuously true for the first phase), its `distribution_target_pct` is greater than 0, and its `capacity_cases` is greater than 0. If the launch is still `PLANNING` but any of the gate's own conditions fails — a lower-indexed phase not yet passed, a zero distribution target, or zero capacity — the phase moves `PENDING → GATE_FAILED` instead: the evaluation itself always succeeds as a call; it is the gate that fails. Either outcome recomputes both distribution projections on the launch and increments the phase's `version`, and a failed phase re-enters the revision loop through the patch described above.

The two projections are the planning team's twin reads on distribution build. The committed read, `projected_distribution_committed_pct`, sums each phase's `distribution_target_pct` with `GATE_PASSED` phases weighted at 1.0 and phases in any other status weighted at 0.0. The pipeline read, `projected_distribution_weighted_pct`, sums the same targets fractionally: a weight of 1.0 for `GATE_PASSED`, 0.25 for `PENDING`, and 0.0 for `GATE_FAILED`. Both are stored rounded half-up to 2 decimal places and are refreshed on every phase creation, patch, and evaluation. For identical phase data the pipeline read is always at least the committed read, and strictly greater whenever any `PENDING` phase carries a positive target; no clamping is ever needed because the 100-percent phase-sum cap already bounds every weighting of the same targets.

Executing the launch is the manufacturer's final gate. The state check comes first: every child phase must stand at `GATE_PASSED`, and a launch attempted with any gate unpassed fails with `ERR_PHASE_GATES_INCOMPLETE` (HTTP 409) regardless of the calendar. Only then does the temporal check apply: the logical clock must have reached the `launch_date`, else the attempt fails with `ERR_LAUNCH_DATE_NOT_REACHED` (HTTP 422). A successful execution moves the launch `PLANNING → LAUNCHED`, stamps `launched_at` from the logical clock, and increments the launch's `version`. The plan's launch list can be browsed filtered by `status`.

### 3.6. Fund Accruals and Deduction Resolution

Money enters the fund period by period. A `FinanceAnalyst` posts one accrual per period against a fund, supplying the `period` as a `YYYY-MM` string and the period's `invoiced_sales_cents` — an integer cents figure with no positivity constraint, so a zero or negative posting simply accrues by the same waterfall; each period may be posted to a fund only once, and a repeat is rejected with `ERR_DUPLICATE_ACCRUAL_PERIOD` (HTTP 409). Every posting runs the same waterfall. The period credit is the `invoiced_sales_cents` multiplied by the fund's `accrual_rate_pct` and divided by 100, rounded half-up to a whole cent. The EDLP bucket's share of that credit is the period credit multiplied by the fund's `edlp_split_pct` and divided by 100, again rounded half-up to a whole cent, and the EVENT bucket receives the remainder — the period credit minus the EDLP share — so the rounding remainder always routes to the event side. In the same pass the server computes the cash-basis shadow: each bucket's share is multiplied by the collection factor 0.92 and rounded half-up to a whole cent, which makes the cash figures strictly smaller than their accrual counterparts whenever a share is positive. The rounding order is pinned and not negotiable: each period's credit and bucket shares are rounded to whole cents before they are summed into the fund's running totals — summing unrounded period values and rounding once at the end is forbidden, because it produces different cents. The period's accrual-basis shares accumulate into `edlp_accrued_cents` and `event_accrued_cents`, the cash shares into `edlp_cash_cents` and `event_cash_cents`, the raw invoiced amount into `total_invoiced_cents`, and the fund's `version` increments. A successful posting answers 201 with the updated fund object — derived availabilities included — in the `data` field. Anyone can inspect the resulting fund — all six roles read funds, and the fund list accepts a `plan_id` filter that locates a plan's single fund.

Money leaves the fund through deduction claims filed by the retailer. A `RetailerBuyer` files a **Deduction** against a fund — the new claim's `fund_id` ties it to that fund — with a `claim_reference` — the retailer-side claim number, unique within the fund, with duplicates rejected `ERR_DUPLICATE_CLAIM` (HTTP 409) — a `bucket` of `EDLP` or `EVENT`, and a strictly positive `amount_cents`. A claim is born `RECEIVED` with `settled_amount_cents` null, `short_paid` false, and `absorbed_by_manufacturer` false, and the fund's deduction list can be browsed filtered by `status` or `bucket`.

Resolution belongs to the `FinanceAnalyst`, who acts on a claim with an `action` of `DISPUTE`, `SETTLE`, `REJECT`, or `WRITE_OFF`. Four resolutions exist, each lawful only from particular states. `DISPUTE` moves a `RECEIVED` claim to `DISPUTED`. `SETTLE` — lawful from either `RECEIVED` or `DISPUTED` — moves the claim to `SETTLED` and pays it against bucket availability: the `settled_amount_cents` becomes the smaller of the claimed `amount_cents` and the fund's availability in the claim's bucket (the event bucket's `event_available_cents` for an `EVENT` claim, the EDLP bucket's `edlp_available_cents` for an `EDLP` claim), `short_paid` flags whether the settled amount fell short of the claim, and the settled sum accumulates into the fund's `edlp_settled_cents` or `event_settled_cents` accordingly. `REJECT` — lawful only from `DISPUTED` — moves the claim to `REJECTED` with no fund movement at all. `WRITE_OFF` — also only from `DISPUTED` — moves the claim to `WRITTEN_OFF`: it computes `settled_amount_cents` as the same smaller-of-claim-and-availability figure, sets `absorbed_by_manufacturer` to true (the manufacturer absorbs the cost without matching retailer activity), flags `short_paid` the same way, and books the absorbed amount into the settled ledger exactly as a settlement would. Every resolution increments the deduction's `version`; an action attempted from a state that does not permit it fails with `ERR_INVALID_STATE`, and the terminal trio of `SETTLED`, `REJECTED`, and `WRITTEN_OFF` refuses everything with `ERR_ALREADY_TERMINAL`.

Deduction activity is the friction signal for post-launch scoring, so every status change fans out into a three-hop cascade. At hop one the fund's own balances mutate — or, on a dispute or rejection, only the claim's membership in the friction set changes. At hop two the server recomputes `friction_count` on every `OPEN` performance review whose launch belongs to the fund's plan: that count covers the fund's deductions created within the review's window whose status is `DISPUTED` or `WRITTEN_OFF`, plus those `SETTLED` with `short_paid` true, so a dispute adds friction and a rejection of a disputed claim removes it again. At hop three those reviews recompute their `risk_score` and `risk_posture`, which can flip a review's posture across the risk thresholds (§3.9) while the review is still open.

### 3.7. Weekly Forecasts and Retailer Commitments

Supply-chain collaboration runs on weekly baseline forecasts. A `SupplyChainPlanner` publishes a **Forecast** under a plan — the plan must be `ACTIVATED`, else `ERR_PLAN_NOT_ACTIVATED` — naming a `week_start` and a strictly positive `baseline_cases`, the manufacturer's statistical demand for that week. The `week_start` must fall on a Monday at midnight UTC and anchors the half-open week that runs seven days forward from it; any other alignment is rejected with `ERR_WEEK_NOT_ALIGNED` (HTTP 422).

A forecast carries two independent state axes. Its publication axis, `pub_status`, begins at `PUBLISHED` and can end at `SUPERSEDED`; its commitment axis, `commit_status`, begins at `UNCOMMITTED` — with `committed_cases` and `committed_at` both null — and can reach `COMMITTED`. The axes never leak into each other: when a planner publishes a new forecast for a plan and `week_start` that already has a `PUBLISHED` forecast, the incumbent auto-transitions to `SUPERSEDED` with its `version` incremented — yet its `commit_status` is preserved untouched, so a committed week stays committed even after a fresher baseline replaces it. Supersession never clears a commitment, and a superseded forecast can never receive a new one.

Commitment is the retailer's move. The `RetailerBuyer` of the plan's retailer commits volume against a forecast by supplying `committed_cases`, which must be strictly positive. The commit requires the forecast to be both `PUBLISHED` and `UNCOMMITTED`; attempting it against a superseded or already-committed forecast fails with `ERR_FORECAST_NOT_PUBLISHED` (HTTP 409). A successful commit moves `commit_status` to `COMMITTED`, records the `committed_cases`, stamps `committed_at` from the logical clock, and increments the forecast's `version`. Committed, published forecasts are exactly the population that later feeds the forecast-bias leg of the post-launch risk score, and the plan's forecast list can be browsed filtered by `pub_status`, `commit_status`, or `week_start`.

### 3.8. Price-Pack Architecture and Channel Conflict

Price-pack architecture is proposed by the manufacturer and ratified by the retailer. A `ManufacturerPlanner` proposes a **PricePackDecision** under a plan, naming the target `channel` — one of `MASS`, `GROCERY`, `CLUB`, `ECOMMERCE`, or `CONVENIENCE`, and it must be a channel the plan's retailer actually operates, with anything outside the retailer's `channels` refused as an `ERR_VALIDATION` body-shape breach — plus a `pack_family` key shared with the launch side of the system, a `pack_code` identifying the pack within the plan (unique within the plan by naming convention — the server performs no duplicate-`pack_code` check), a `unit_count` of selling units per pack of at least 1, and a strictly positive `list_price_cents`. The plan's lifecycle status imposes no gate on proposals. Club economics demand scale: a `CLUB`-channel pack whose `unit_count` falls below 12 is rejected with `ERR_CLUB_PACK_TOO_SMALL` (HTTP 422). Every decision carries a computed `price_per_unit_cents`, its `list_price_cents` divided by `unit_count` rounded UP to the next whole cent — never banker's, never nearest — so per-unit comparisons across channels always use whole-cent figures. A proposal is born `PROPOSED`, and the plan's decision list can be browsed filtered by `channel`, `status`, or `pack_family`.

The `RetailerBuyer` of the plan's retailer then decides. A `decision` of `REJECT` moves the decision `PROPOSED → REJECTED`, terminal, with its `version` incremented. A `decision` of `APPROVE` is guarded by the channel-conflict rules, and they fire in a fixed order against the plan's already-`APPROVED` decisions. The pairwise price-gap rule runs first: for every other approved decision of the plan, the gap between the candidate's `price_per_unit_cents` and the sibling's is taken as the absolute difference divided by the smaller of the two per-unit prices and expressed as a percent, and every such gap must be at most 15 percent — a gap of exactly 15 percent passes. Any breach rejects the approval with `ERR_CHANNEL_CONFLICT` (HTTP 422). Only after the pairwise rule passes does the e-commerce undercut rule run, and only when the candidate's `channel` is `ECOMMERCE`: the candidate's per-unit price must be at least the lowest per-unit price among the plan's approved non-e-commerce decisions, reduced by 10 percent and rounded up to the next whole cent; falling below that floor rejects the approval with `ERR_ECOMMERCE_UNDERCUT` (HTTP 422). A candidate that clears both gates moves `PROPOSED → APPROVED` with its `version` incremented.

Approval is not the end of the story. When a post-launch review finalizes with a delist outcome (§3.9), every approved price-pack decision of the same plan whose `pack_family` matches the delisted launch's `pack_family` is swept to `RETIRED` by the system itself, each with its own `version` increment — the mechanism that clears the pack family from the shelf when its launch fails.

### 3.9. Post-Launch Performance Review and Delisting Risk

Every launch eventually faces its review. A `ManufacturerPlanner` opens the **PerformanceReview** on a launched product — the new record's `launch_id` identifies the launch under review — supplying the review window as `period_start` and `period_end` — both inclusive bounds, with the end required to be strictly after the start — together with the retailer-reported `actual_sales_cents` (zero or more), the joint `sales_target_cents` (strictly positive), and the distribution pair `target_distribution_pct` and `distribution_achieved_pct`, each between 0 and 100 inclusive. Two gates guard the opening. Timing: the logical clock must have reached the launch's `launch_date` plus 84 days — exactly at that boundary the review is allowed, and any earlier attempt fails with `ERR_REVIEW_TOO_EARLY` (HTTP 422). Uniqueness: at most one review may ever exist for a launch, and a second attempt fails with `ERR_REVIEW_ALREADY_EXISTS` (HTTP 409).

Creation is also computation: five derived fields are evaluated the moment the review opens. The `sales_attainment_pct` is the `actual_sales_cents` divided by the `sales_target_cents`, expressed as a percent and rounded half-up to 2 decimal places. The `forecast_bias_pct` measures how badly committed forecasts missed: among the plan's forecasts that are both `PUBLISHED` and `COMMITTED` with a `week_start` falling inside the review window inclusive of both ends — superseded forecasts never contribute, even committed ones — each contributes the absolute difference between its `committed_cases` and its `baseline_cases`, divided by its `baseline_cases`, expressed as a percent; the bias is the mean of those per-forecast figures, rounded half-up to 2 decimal places, and an empty qualifying set yields a bias of exactly 0. The `friction_count` tallies the fund's deductions created within the review window — again inclusive of both ends — whose status is `DISPUTED` or `WRITTEN_OFF`, together with those `SETTLED` while `short_paid`. From those ingredients the `risk_score` is assembled as a weighted sum of four components. The sales component is 100 minus the `sales_attainment_pct`, clamped into the range 0 to 100. The distribution component is the `target_distribution_pct` minus the `distribution_achieved_pct`, clamped the same way, so distribution over-delivery scores zero rather than going negative. The forecast component takes the `forecast_bias_pct` capped at 25 and multiplies it by 4, scaling a bias of 0 to 25 onto 0 to 100. The friction component takes the `friction_count` capped at 5 and multiplies it by 20, scaling zero to five frictions onto 0 to 100. The raw score weighs these at 0.40 for sales, 0.30 for distribution, 0.20 for forecast bias, and 0.10 for friction, and the final `risk_score` is that raw total rounded half-up to a whole number and clamped between 0 and 100. The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`. The review is born `OPEN` with its `decision` still null — and while it stays open, the deduction cascade of §3.6 keeps recomputing its friction, score, and posture as claims move.

Finalization belongs to the retailer. The `RetailerBuyer` of the plan that owns the review's launch closes an `OPEN` review with a `decision` of `CONTINUE` or `DELIST`; the payload value is recorded on the review, the review moves `OPEN → FINALIZED`, and its `version` increments. The decision then propagates. `CONTINUE` moves the launch `LAUNCHED → REVIEWED`, terminal, with its `version` incremented — the product keeps its place. `DELIST` moves the launch `LAUNCHED → DELISTED` with its `version` incremented and then fires the pack-family cascade of §3.8: every `APPROVED` price-pack decision of the same plan sharing the launch's `pack_family` transitions to `RETIRED`, each incrementing its own `version`. A launch's review list — which ever holds at most one entry — is readable by all six roles.

## 4. Endpoint Definitions

Operations that create a new resource — retailers, categories, plans, events, analyses, shelf recommendations, launches, accrual postings, deductions, forecasts, price-pack decisions, and performance reviews — return `201 Created`. Operations that modify an existing resource or drive a state transition — negotiation, decisions, activation, locking, cancellation, verification, launch execution, phase revision and evaluation, deduction resolution, forecast commitment, review finalization, and the clock-setting capability — return `200 OK`, as do all reads. The table below is a summary only: request payloads, response shapes, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jbp/_clock/set_current_utc` | Set the server's logical clock (monotonic non-decreasing) | PlatformAdmin |
| POST | `/jbp/retailers` | Create a retailer account | PlatformAdmin |
| POST | `/jbp/categories` | Create a category with its advisory data-governance scope | PlatformAdmin |
| POST | `/jbp/plans` | Create a JointBusinessPlan (lands `PROPOSED`, round 1) | ManufacturerPlanner |
| GET | `/jbp/plans/{id}` | Read one plan, including its `version` | All six roles |
| GET | `/jbp/plans` | List plans, filterable by `retailer_id`, `category_id`, `status`, `fiscal_year` | All six roles |
| POST | `/jbp/plans/{id}/negotiate` | Counter (retailer, from `PROPOSED`) or re-propose (manufacturer, from `COUNTERED`) | ManufacturerPlanner, RetailerBuyer |
| POST | `/jbp/plans/{id}/decide` | Accept or reject the live offer | ManufacturerPlanner, RetailerBuyer |
| POST | `/jbp/plans/{id}/activate` | Activate an `ACCEPTED` plan and create its TradeFund | ManufacturerPlanner |
| POST | `/jbp/plans/{id}/events` | Pencil a promotional event onto the plan calendar | ManufacturerPlanner |
| GET | `/jbp/plans/{id}/events` | List events of a plan, filterable by `status`, `event_type` | All six roles |
| POST | `/jbp/events/{id}/lock` | Lock a `PENCILED` event, computing its cost estimate and reserving funds | ManufacturerPlanner |
| POST | `/jbp/events/{id}/cancel` | Cancel a `PENCILED` or `LOCKED` event, releasing any reservation | ManufacturerPlanner |
| POST | `/jbp/plans/{id}/category-analyses` | Submit a category advisory analysis | CategoryAdvisor |
| GET | `/jbp/plans/{id}/category-analyses` | List analyses of a plan, filterable by `status` | All six roles |
| POST | `/jbp/category-analyses/{id}/decide` | Accept or return a `SUBMITTED` analysis | RetailerBuyer |
| POST | `/jbp/plans/{id}/shelf-recommendations` | Submit a shelf recommendation (OCC-guarded); supersedes the incumbent | CategoryAdvisor |
| GET | `/jbp/plans/{id}/shelf-recommendations` | List shelf recommendations of a plan, filterable by `status` | All six roles |
| POST | `/jbp/shelf-recommendations/{id}/decide` | Accept (to `IMPLEMENTING`) or reject a `PROPOSED` recommendation | RetailerBuyer |
| POST | `/jbp/shelf-recommendations/{id}/verify` | Audit in-store implementation against SLA and store count | CategoryAdvisor |
| POST | `/jbp/plans/{id}/launches` | Create an innovation launch and its four phases | ManufacturerPlanner |
| GET | `/jbp/plans/{id}/launches` | List launches of a plan, filterable by `status` | All six roles |
| GET | `/jbp/launches/{id}` | Read one launch with budget remainder and both projections | All six roles |
| POST | `/jbp/launches/{id}/launch` | Execute the launch (gates first, date second) | ManufacturerPlanner |
| GET | `/jbp/launches/{id}/phases` | List the launch's phases in `phase_index` ascending order | All six roles |
| PATCH | `/jbp/launches/{id}/phases/{phase_id}` | Revise a phase's targets, capacity, or trade spend | ManufacturerPlanner |
| POST | `/jbp/launches/{id}/phases/{phase_id}/evaluate` | Evaluate the phase gate from `PENDING` | ManufacturerPlanner |
| GET | `/jbp/funds/{id}` | Read one trade fund with all accrual, cash, reserved, settled, and available fields | All six roles |
| GET | `/jbp/funds` | List trade funds, filterable by `plan_id` | All six roles |
| POST | `/jbp/funds/{id}/accruals` | Post one period's invoiced sales into the fund | FinanceAnalyst |
| POST | `/jbp/funds/{id}/deductions` | File a deduction claim against a fund bucket | RetailerBuyer |
| GET | `/jbp/funds/{id}/deductions` | List deductions of a fund, filterable by `status`, `bucket` | All six roles |
| POST | `/jbp/deductions/{id}/resolve` | Resolve a deduction: dispute, settle, reject, or write off | FinanceAnalyst |
| POST | `/jbp/plans/{id}/forecasts` | Publish a weekly baseline forecast, superseding any incumbent | SupplyChainPlanner |
| GET | `/jbp/plans/{id}/forecasts` | List forecasts of a plan, filterable by `pub_status`, `commit_status`, `week_start` | All six roles |
| POST | `/jbp/forecasts/{id}/commit` | Commit retailer volume against a published, uncommitted forecast | RetailerBuyer |
| POST | `/jbp/plans/{id}/price-pack-decisions` | Propose a channel price-pack decision | ManufacturerPlanner |
| GET | `/jbp/plans/{id}/price-pack-decisions` | List price-pack decisions of a plan, filterable by `channel`, `status`, `pack_family` | All six roles |
| POST | `/jbp/price-pack-decisions/{id}/decide` | Approve (channel-conflict checked) or reject a `PROPOSED` decision | RetailerBuyer |
| POST | `/jbp/launches/{id}/performance-reviews` | Open the launch's single post-launch performance review | ManufacturerPlanner |
| GET | `/jbp/launches/{id}/performance-reviews` | List the launch's reviews (at most one) | All six roles |
| POST | `/jbp/performance-reviews/{id}/finalize` | Finalize an `OPEN` review as `CONTINUE` or `DELIST` | RetailerBuyer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, next to the workflow each rule guards. Three framework-level rejections sit outside this domain catalogue but still use the standard error envelope: a request that matches no route receives `ERR_RESOURCE_NOT_FOUND` (HTTP 404), a matched route invoked with the wrong method receives `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server fault receives `ERR_INTERNAL` (HTTP 500).

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_RETAILER_SCOPE_MISMATCH` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_GROWTH_TARGET_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_RETAILER_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_NOT_YOUR_MOVE` | 403 Forbidden |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_NOT_ACTIVATED` | 409 Conflict |
| `ERR_ANALYSIS_NOT_ACCEPTED` | 409 Conflict |
| `ERR_PHASE_GATES_INCOMPLETE` | 409 Conflict |
| `ERR_PHASE_LOCKED` | 409 Conflict |
| `ERR_FORECAST_NOT_PUBLISHED` | 409 Conflict |
| `ERR_IMPLEMENTATION_STALLED` | 409 Conflict |
| `ERR_IMPLEMENTATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_GOVERNANCE_BOUNDARY` | 422 Unprocessable Entity |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_REVIEW_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_DUPLICATE_ACCRUAL_PERIOD` | 409 Conflict |
| `ERR_DISTRIBUTION_SUM_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PHASE_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CLUB_PACK_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_CHANNEL_CONFLICT` | 422 Unprocessable Entity |
| `ERR_ECOMMERCE_UNDERCUT` | 422 Unprocessable Entity |
| `ERR_PROMO_OVERLAP` | 409 Conflict |
| `ERR_WEEK_NOT_ALIGNED` | 422 Unprocessable Entity |
| `ERR_LAUNCH_OUTSIDE_FISCAL_YEAR` | 422 Unprocessable Entity |
| `ERR_LAUNCH_TOO_CLOSE` | 422 Unprocessable Entity |
| `ERR_LAUNCH_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_REVIEW_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_EVENT_SPLIT_TOO_LOW` | 422 Unprocessable Entity |
