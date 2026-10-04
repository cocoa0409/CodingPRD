# Smelter Power Curtailment API — Product Requirements Document

## 1. Introduction

Primary aluminum smelting is one of the most electricity-intensive industrial processes in the world. Potlines are designed to run continuously: molten cryolite baths freeze when power is withdrawn for too long, and a full shutdown triggers pot relining capital that dwarfs the cost of a brief curtailment. Power itself is procured under layered contracts — fixed-price blocks, market-indexed tranches, and interruptible volume the grid operator can call down — so the economics of producing the next tonne of metal swing with both the power curve and the aluminum curve. When spot power spikes or metal prices sag, curtailing a potline can be worth more than the metal forgone; but the decision is physically sticky, because the cost of coming back depends on how long the line has been down.

This document specifies the API that operationalizes those decisions for a multi-site producer in the mold of an integrated aluminum major. The system manages smelter sites and their potlines, the power contracts and grid-operator interruptions that feed them, market price observations and metal hedge positions, internal alumina transfer pricing between the upstream refinery segment and the downstream smelter segment, a two-stage curtailment approval pipeline with segregation of duties and labor notice periods, class-based restart planning, environmental permits, collective labor agreements, and monthly product-mix plans across billet, slab, and value-added forms. All temporal semantics — contract windows, observation validity, downtime measurement, notice periods, lazy expiries — are driven by a single server-owned logical clock described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to declare the operational capacity in which they act. The system recognizes exactly seven roles: `PlatformAdmin`, `EnergyManager`, `TradingAnalyst`, `SmelterManager`, `Controller`, `VPOperations`, and `EHSManager`. A request missing either header, or carrying an `X-User-Role` value that is not one of these seven declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For every one of the seven roles — `PlatformAdmin`, `EnergyManager`, `TradingAnalyst`, `SmelterManager`, `Controller`, `VPOperations`, and `EHSManager` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `proposed_by_user_id`, `economic_reviewed_by_user_id`, or `approved_by_user_id` on a curtailment decision where the approval pipeline writes it) but does not compare it to any entity's `id` for ownership purposes. Segregation-of-duties checks compare `X-User-ID` against these recorded operator stamps, never against resource identifiers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Lazy Expiry

Every temporal rule in this system reads a single server-owned **logical clock** — never the wall clock. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and before any explicit adjustment it continues to read that default rather than falling back to wall-clock time. A `PlatformAdmin` may advance the clock through a test-driving capability whose request carries a `to_iso8601` instant and whose response reports the resulting `current_utc`; this capability is mounted outside the `/smelter-ops` business surface. After any clock adjustment, lazy lifecycle transitions re-evaluate on subsequent reads.

Three resource families expire lazily, without any explicit client action. A `PowerContract` flips from `ACTIVE` to `EXPIRED` whenever it is read or referenced while the logical clock has reached its `window_end`. A `HedgePosition` still `OPEN` flips to `EXPIRED` when the logical clock passes the last day of its `delivery_month`. An `EnvironmentalPermit` still `ACTIVE` flips to `EXPIRED` when the logical clock reaches its `valid_to`. Each such lazy flip is a real mutation: the resource's `version` increments by 1 and its `updated_at` refreshes.

### 2.5. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 with every modification, including system-applied lazy transitions and cascade side effects.

Two resource families are immutable, append-only records and therefore carry only `id` and `created_at`: a `PriceObservation` and an `InterruptEvent` have neither `updated_at` nor `version` — both fields are absent on those resources.

### 2.6. Nested Resource Retrieval and Existence Ordering

Requests that target nested resources are validated in a strict left-to-right order along the path: each path identifier must resolve to an existing resource, and the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any later identifier or any business rule is examined. The same existence obligation covers body foreign-key fields — `smelter_id`, `potline_id`, and `contract_id` must each resolve to an existing resource — and a failure there likewise yields `ERR_NOT_FOUND`. Existence always precedes state checks, business rules, and value validation.

### 2.7. Request Evaluation Order

When several checks could reject the same request, the platform evaluates them in one fixed global order, and a lower-numbered check masks every higher-numbered one. The order is:

1. Authentication of the two headers — `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — `ERR_UNAUTHORIZED`.
3. Existence of path identifiers and body foreign keys — `ERR_NOT_FOUND`.
4. Segregation of duties on the two curtailment-decision approval steps — `ERR_SEGREGATION_OF_DUTIES`.
5. Optimistic-concurrency version match on the two version-gated creation endpoints — `ERR_STALE_VERSION` (evaluated after existence, before any other business rule of the endpoint).
6. Potline state compatibility — `ERR_POTLINE_INVALID_STATE`.
7. A duplicate live restart plan for the potline — `ERR_RESTART_PLAN_EXISTS`.
8. Curtailment-decision state compatibility — `ERR_DECISION_INVALID_STATE`.
9. Restart-plan state compatibility — `ERR_RESTART_PLAN_INVALID_STATE`.
10. Lifecycle state on hedge close, permit suspend, contract activate, and labor-agreement expire — `ERR_INVALID_LIFECYCLE_STATE`.
11. Presence of an active spent-potlining-disposal permit on restart start — `ERR_PERMIT_NOT_ACTIVE`.
12. The labor notice period on decision execution — `ERR_LABOR_NOTICE_PERIOD`.
13. Presence of an active labor agreement on decision execution — `ERR_LABOR_AGREEMENT_INACTIVE`.
14. Contract window overlap on activation — `ERR_CONTRACT_WINDOW_OVERLAP`.
15. Temporal field validity on creation payloads — `ERR_INVALID_REQUEST`.
16. Request shape and composition (required fields, enum values, numeric ranges, component and allocation composition) — `ERR_INVALID_REQUEST`.
17. Labor-agreement uniqueness per smelter at creation — `ERR_LABOR_AGREEMENT_EXISTS`.
18. Permit uniqueness per smelter and permit type at creation — `ERR_PERMIT_DUPLICATE_TYPE`.
19. Curtailment depth rules on the emergency curtail action — `ERR_CURTAILMENT_DEPTH_INVALID`.
20. The interruptible-hours annual cap — `ERR_INTERRUPTIBLE_CAP_EXCEEDED`.
21. Product-mix capacity on plan publication — `ERR_PRODUCT_MIX_OVER_CAPACITY`.
22. Availability of required price observations — `ERR_NO_PRICE_OBSERVATION`.
23. Presence of a covering active power contract — `ERR_NO_ACTIVE_POWER_CONTRACT`.
24. The hedge volume cap at hedge creation — `ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE`.
25. The hedge coverage floor at decision execution — `ERR_HEDGE_COVERAGE_INSUFFICIENT`.

So, for example, a request that is both unauthenticated and malformed always surfaces `ERR_UNAUTHENTICATED`; a stale version surfaces before any state or business complaint; and on decision creation a missing price observation (rule 22) surfaces before a missing covering contract (rule 23).

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints are version-gated. Creating a curtailment decision requires the request to carry `expected_potline_version` holding the client's last observed `version` of the target potline; if the potline's current `version` has advanced beyond that value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Publishing a production plan likewise requires `expected_smelter_version` matching the smelter's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). This protects a writer from acting on a stale view of the parent: decision creation itself increments the potline's `version` by 1, and plan publication increments the smelter's `version` by 1, so a second writer who has not re-read the parent since its last mutation is detectably stale. Per §2.7, the version check runs after existence resolution and before any other business rule of the endpoint. No endpoint other than these two accepts or requires a version field.

### 2.9. Precision, Rounding, and Quoted Values

All monetary and unit-price outputs of the platform are expressed at exactly 2 decimal places using round-half-up. Where a computation is pinned to a specific rounding order, that order is part of the contract: the forward and settled power costs and the alumina transfer price round once, on the final figure; the monthly power settlement rounds each hour's cost to 2 decimals first and then sums already-rounded hours into days and days into the month — accumulating raw hourly values and rounding once at the end is a different number and is not the contract; the product-mix margin rounds each allocation's per-tonne margin to 2 decimals first, then multiplies by tonnage, then sums. Restart costs are whole USD values built from integral constants and require no rounding. The hedge coverage ratio is kept unrounded for gating decisions and is displayed at 4 decimal places. Market price observations are quoted with at most 2 decimal places at intake.

### 2.10. Market Data: Price Observations

`TradingAnalyst` and `EnergyManager` operators append immutable `PriceObservation` records to the market-data log; each record carries an `instrument`, a `region_code`, an `observed_at` timestamp, and a `price_usd`. Four instruments exist: `POWER_SPOT`, `ALUMINUM_LME`, `REGIONAL_PREMIUM`, and `ALUMINA_INDEX`. Regional discipline is enforced per instrument: for `POWER_SPOT` and `REGIONAL_PREMIUM` the `region_code` is required and must name one of the four smelter regions — `NA_NORTHWEST`, `NA_MIDWEST`, `EU_NORDIC`, or `AU_EAST`; for `ALUMINUM_LME` and `ALUMINA_INDEX` the `region_code` must be `GLOBAL`. The `observed_at` timestamp may not lie after the current logical clock, and `price_usd` must be positive — quoted in USD per MWh for `POWER_SPOT` and USD per tonne for every other instrument.

"Latest observation" selectors used throughout the pricing engine pick the qualifying record with the greatest `observed_at` at or before the logical clock, breaking ties by `created_at` descending (the most recently recorded observation wins). Chronological replays instead walk qualifying records in `observed_at` ascending order, breaking ties by `created_at` ascending.

### 2.11. Derived State and Computed Reads

Several load-bearing fields are computed on read and never stored. A smelter read exposes `operating_posture`, derived from the live states of its potlines: `FULL_OPERATION` when the smelter has no potlines at all or every potline is `OPERATING`; `SHUTDOWN` when at least one potline exists and every potline is `SHUTDOWN`; `FULL_CURTAILMENT` when no potline is `OPERATING` or `RESTARTING` and the potlines are not all `SHUTDOWN`; and `PARTIAL_CURTAILMENT` in every remaining configuration. The same read exposes `open_hedged_tonnes` (the summed `volume_tonnes` of the smelter's `OPEN` hedge positions), `curtailed_capacity_tpd` (the summed `capacity_tpd` of its potlines in `CURTAILED`, `IDLE`, or `SHUTDOWN` — a `RESTARTING` line does not count), and `hedge_coverage_ratio` (`open_hedged_tonnes` divided by the monthly capacity basis `rated_capacity_tpd` multiplied by 30, reading 0.0 when rated capacity is zero).

A potline read exposes `restart_cost_class`: `HOT` while the potline is `OPERATING` or `CURTAILED`, or while it has been `IDLE` for less than 24 hours; `WARM` once it has been `IDLE` for at least 24 hours but less than 720 hours (thirty days); and `COLD` when the potline is `SHUTDOWN`, or has been `IDLE` for 720 hours or more. Downtime is measured from `curtailed_since` for an `IDLE` line and from `last_full_shutdown_at` for a `SHUTDOWN` line, up to the current logical clock.

Computed reads that depend on market data degrade to null rather than raising when their inputs are missing: the contract cost fields `forward_cost_per_mwh`, `settled_cost_per_mwh`, and `month_to_date_settlement_usd`, and a market-linked agreement's `current_transfer_price`, read null in the absence of the price observations they need. The same missing data on a write that needs it — curtailment-decision creation or production-plan publication — is instead rejected with `ERR_NO_PRICE_OBSERVATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Sites, Potlines, and the Operating Lifecycle

A `PlatformAdmin` onboards a **Smelter** by supplying its `name`, its `region_code` — one of `NA_NORTHWEST`, `NA_MIDWEST`, `EU_NORDIC`, or `AU_EAST` — its `rated_capacity_tpd` (strictly positive; the site's monthly production capacity basis is always thirty times this daily figure), and its direct `labor_headcount` (zero or more). The smelter is the root of every aggregate in the system: potlines, power contracts, hedge positions, alumina agreements, permits, labor agreements, and production plans all belong to one.

Under an onboarded smelter, a `SmelterManager` creates a **Potline** through a payload carrying the owning `smelter_id`, an operator `line_code` unique within that smelter, a strictly positive `capacity_tpd`, and a strictly positive `amperage_ka`. Creation is gated on power: the smelter must have an `ACTIVE` power contract whose delivery window covers the current logical clock, or the request is rejected with `ERR_NO_ACTIVE_POWER_CONTRACT` (HTTP 422). A new potline starts in `OPERATING` status with `curtailment_depth_pct` at 0; `curtailed_since`, `last_full_shutdown_at`, and `active_decision_id` are all null.

Emergency — decision-less — curtailment is the `SmelterManager`'s direct lever on a potline, driven by a requested `depth_pct`. From `OPERATING`, a depth strictly between 0 and 100 moves the potline to `CURTAILED`: the depth is recorded on `curtailment_depth_pct`, `curtailed_since` is set to the logical clock, `active_decision_id` is set to null (emergency curtailment carries no decision), and the potline's `version` increments. From `OPERATING`, a depth of exactly 100 moves the potline to `IDLE` instead, with `curtailment_depth_pct` at 100 and `curtailed_since` freshly stamped. From `CURTAILED`, a positive depth that strictly exceeds the current `curtailment_depth_pct` but stays below 100 deepens the curtailment in place (only the depth and `version` change); a depth of exactly 100 completes the idle — the potline moves to `IDLE` while `curtailed_since` is deliberately left unchanged, because the downtime clock runs continuously from the moment the line first left `OPERATING`. From `CURTAILED`, a depth of exactly 0 restores the line to `OPERATING`, clearing `curtailment_depth_pct` to 0 and `curtailed_since` to null — but this restore is only permitted while `active_decision_id` is null; a decision-linked curtailment must be unwound through the decision's own reversal, not through a direct restore.

Depth discipline is strict: a `depth_pct` outside the inclusive range from 0 to 100, a positive deepen that does not strictly exceed the current depth, or a zero-depth restore while `active_decision_id` is set are all rejected with `ERR_CURTAILMENT_DEPTH_INVALID` (HTTP 422). Invoking the curtail action from an `operating_status` for which no matching transition exists — for example curtailing an `IDLE`, `RESTARTING`, or `SHUTDOWN` line — is rejected with `ERR_POTLINE_INVALID_STATE` (HTTP 409).

Full shutdown is deliberately hard to reach. A `SmelterManager` may shut down only an `IDLE` potline, and only when its `active_decision_id` references a curtailment decision that is `EXECUTED` at a `depth_pct` of 100 — an emergency idled line can never be shut down directly, which is what makes a full shutdown reachable solely through the governed decision pipeline. The transition to `SHUTDOWN` stamps `last_full_shutdown_at` with the logical clock and increments the potline's `version`. A shutdown attempted on a potline that is not `IDLE` — or one whose `active_decision_id` does not reference such an executed full-depth decision — is rejected with `ERR_POTLINE_INVALID_STATE` (HTTP 409). Every potline mutation — curtail, deepen, restore, idle, shutdown, restart — forces the parent smelter's `operating_posture` and `curtailed_capacity_tpd` to recompute on the next read.

### 3.2. Power Procurement: Contracts, Windows, and Interruptible Dispatch

An `EnergyManager` drafts a **PowerContract** for a smelter by naming the counterparty `supplier_name`, the delivery window (`window_start` inclusive, `window_end` exclusive — a half-open interval, with `window_start` strictly before `window_end`), the `components` array, and optionally `take_or_pay_pct`, the fraction of contracted energy that must be paid even if not taken, which defaults to 0.9 and must be greater than 0 and at most 1. A contract's `status` is `DRAFT` on creation.

The `components` array is the heart of the contract. It must contain at least one component and at most one `INTERRUPTIBLE` component. Each component declares a `component_type` of `FIXED`, `MARKET_INDEXED`, or `INTERRUPTIBLE`, plus a strictly positive `volume_mw`. A `FIXED` component must carry a `fixed_price_per_mwh` of zero or more; an `INTERRUPTIBLE` component must carry a strictly positive `interruptible_cap_hours_per_year`. Composition violations — a missing component list, a second interruptible tranche, a fixed tranche without its price, an interruptible tranche without its cap — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Activation moves a contract from `DRAFT` to `ACTIVE` and is refused when the new contract's half-open window would overlap the window of another `ACTIVE` contract for the same smelter; touching windows, where one contract's `window_end` equals the other's `window_start`, do not overlap and are allowed. An overlapping activation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409), while activating a contract that is not `DRAFT` is rejected with `ERR_INVALID_LIFECYCLE_STATE` (HTTP 409). Thereafter the contract expires lazily per §2.4.

Grid dispatch against the interruptible tranche is recorded as an **InterruptEvent**: an `EnergyManager` supplies the `contract_id`, a `start_at` at or after the contract's `window_start` and not after the logical clock, an `end_at` strictly after `start_at` and not after the logical clock, and a strictly positive `mw_reduced` no greater than the interruptible component's `volume_mw`. The event's `hours` are computed as the elapsed difference between `end_at` and `start_at` in hours and may be fractional. An annual cap guards the tranche: the cumulative hours of all events whose `start_at` falls inside the current contract year — the 365-day window beginning on the anniversary of `window_start` that contains the current logical clock — must not exceed `interruptible_cap_hours_per_year`. Landing exactly on the cap is allowed; exceeding it is rejected with `ERR_INTERRUPTIBLE_CAP_EXCEEDED` (HTTP 422). The contract's computed `interruptible_hours_used` exposes this running contract-year total on read.

### 3.3. Pricing the Electron: Forward Cost, Settled Cost, and Monthly Settlement

The **effective power cost** of a contract blends its components into a single USD-per-MWh figure and comes in two variants that share one scaffolding: `f` is the sum over `FIXED` components of each `volume_mw` multiplied by its `fixed_price_per_mwh`; `m_mw` and `i_mw` are the summed volumes of the `MARKET_INDEXED` and `INTERRUPTIBLE` tranches; `total_mw` is the summed volume of every component; and `spot` is the latest `POWER_SPOT` observation for the contract smelter's `region_code`. Spot is required only when market exposure exists: when every component is `FIXED`, the cost is simply `f` divided by `total_mw` regardless of observations, but when `m_mw` and `i_mw` together exceed zero and no qualifying observation exists, both variant outputs read null — this is not an error condition.

The FORWARD variant is projective: it feeds the `forward_cost_per_mwh` read field and the curtailment economics snapshot, and it prices the contract as `f` plus `m_mw` times the single latest spot plus `i_mw` times that same spot discounted by a quarter (interruptible energy prices at 75% of spot), all divided by `total_mw`. Dispatch history is ignored entirely.

The SETTLED variant is the ex-post view exposed as `settled_cost_per_mwh`, and it replays the calendar month containing the current logical clock chronologically. Every `POWER_SPOT` observation for the region with `observed_at` inside the window from the month start through the earlier of the month end and the current clock is collected in ascending `observed_at` order (ties broken by `created_at` ascending). Each observation's price is weighted by the number of hours from its own timestamp — the month start, for the first observation — until the next observation or the window end, and the time-weighted average is the weighted sum divided by total elapsed hours. The settled cost substitutes that time-weighted average for spot in the same blend: `f` plus `m_mw` times the average plus `i_mw` times the average discounted by a quarter, over `total_mw`. An empty observation set in the month yields a null settled field. Identical contract inputs therefore produce different forward and settled numbers whenever the curve moved intra-month. Both variants round half-up to 2 decimal places, applied once to the final cost, and interruptible energy actually curtailed by recorded interruptions is not netted out of either variant — take-or-pay applies only in the monthly settlement.

The settlement itself surfaces as `month_to_date_settlement_usd`, computed hour by hour for the calendar month containing the logical clock. For each elapsed hour from the month start through the clock, every component bills its `volume_mw` times one hour of energy times the applicable price times a loss factor: a `FIXED` component bills at its `fixed_price_per_mwh` with a loss factor of 1.0, while `MARKET_INDEXED` and `INTERRUPTIBLE` components bill at the latest spot observation at or before that hour — the interruptible tranche again at a 25% discount — with a loss factor of 1.037 applied to both market-exposed tranches. Each hour's raw total is rounded half-up to 2 decimal places before any summation; the rounded hourly amounts then sum into days and the days into the month-to-date figure. This pinned order — round per hour, then sum — is contractual. When the contract carries `MARKET_INDEXED` or `INTERRUPTIBLE` pricing and no `POWER_SPOT` observation exists at or before the clock, the settlement field reads null.

Finally, the boolean `take_or_pay_exposed` marks a contract that is `ACTIVE` while its smelter's `operating_posture` has left `FULL_OPERATION` for `PARTIAL_CURTAILMENT`, `FULL_CURTAILMENT`, or `SHUTDOWN` — the signature that an executed curtailment has cascaded through the site and that take-or-pay volumes now bill regardless of interrupted delivery.

### 3.4. Alumina Supply and Internal Transfer Pricing

Alumina moves from the upstream refinery segment to the smelter under an internal transfer-pricing regime. A `Controller` registers an **AluminaSupplyAgreement** naming the consuming `smelter_id`, the internal `refinery_name`, a `pricing_model` of `COST_PLUS` or `MARKET_LINKED`, and a strictly positive `monthly_volume_tonnes`. The two models carry mutually exclusive parameter sets: `COST_PLUS` requires `base_cost_per_tonne` (the refinery cash cost per tonne) and `markup_pct` (the inter-segment markup fraction, zero or more) and forbids `market_discount_pct`; `MARKET_LINKED` requires `market_discount_pct` (a fraction at least 0 and strictly below 1) and forbids both `base_cost_per_tonne` and `markup_pct`. Violating the conditional shape is rejected with `ERR_INVALID_REQUEST`. Agreements take effect immediately on registration — there is no separate activation step — and where a computation needs "the smelter's transfer price" it uses the most recently created agreement.

The computed `current_transfer_price` is read-side and rounded half-up to 2 decimal places on the final price. Under `COST_PLUS` it is the `base_cost_per_tonne` multiplied by one plus the `markup_pct`, ignoring the alumina market index entirely. Under `MARKET_LINKED` it is the latest `GLOBAL` `ALUMINA_INDEX` observation multiplied by one minus the `market_discount_pct`, reading null when no such observation exists — so identical refinery economics produce different transfer prices than the cost-plus model whenever the index diverges from cost.

### 3.5. The Curtailment Decision Pipeline

When economics or grid conditions demand it, curtailment proper runs through a governed **CurtailmentDecision**. A `SmelterManager` proposes one against a specific potline with a payload carrying the `potline_id`, the OCC field `expected_potline_version` per §2.8, a declared `trigger_type` of `POWER_PRICE`, `METAL_PRICE`, `GRID_EMERGENCY`, or `MAINTENANCE`, a `depth_pct` strictly greater than 0 and at most 100 (100 means a full idle of the potline), and a window with `planned_start` strictly before `planned_end`. The target potline must be `OPERATING` or `CURTAILED` — proposing against an `IDLE`, `RESTARTING`, or `SHUTDOWN` line is rejected with `ERR_POTLINE_INVALID_STATE`.

Creation freezes an `economics_snapshot` so that later reviewers see the exact numbers the proposer saw. The snapshot's `lme_price_usd` is the latest `GLOBAL` `ALUMINUM_LME` observation at or before the clock, and `regional_premium_usd` is the latest `REGIONAL_PREMIUM` observation for the potline's smelter region. The `transfer_price_per_tonne` is the `current_transfer_price` of the smelter's most recently created alumina supply agreement, falling back to the latest `GLOBAL` `ALUMINA_INDEX` observation when no agreement exists. The `power_cost_per_mwh` is the FORWARD effective power cost of the smelter's `ACTIVE` power contract whose half-open window covers the clock. From these, `margin_per_tonne` is the LME price plus the regional premium, minus 1.92 tonnes of alumina per tonne of metal times the transfer price, minus 13.5 MWh per tonne times the power cost, minus a further 420 USD per tonne of other conversion cost. `curtailment_economic` is true exactly when `margin_per_tonne` falls below the 150 USD per-tonne restart reserve; `avoidable_loss_per_tonne` is that shortfall — the reserve minus the margin — floored at zero; and `restart_cost_class` copies the potline's class at snapshot time. Each snapshot figure is rounded half-up to 2 decimal places. Missing LME, premium, or transfer inputs are rejected with `ERR_NO_PRICE_OBSERVATION` (HTTP 422); the absence of a covering `ACTIVE` contract is rejected with `ERR_NO_ACTIVE_POWER_CONTRACT` (HTTP 422) — and when both fail, the price-observation failure surfaces first per the evaluation order of §2.7. Creation also increments the potline's `version` by 1, records the creator in `proposed_by_user_id`, and flips any prior decision still sitting in `ECONOMIC_REVIEW` for the same potline to `SUPERSEDED` (bumping that prior decision's `version`). A new decision enters with `status` set to `ECONOMIC_REVIEW`.

Economic approval belongs to a `Controller`, who moves the decision from `ECONOMIC_REVIEW` to `LABOR_REVIEW`, stamping `economic_reviewed_by_user_id`. Segregation of duties forbids the reviewer from being the proposer: an `X-User-ID` equal to `proposed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Labor and community approval belongs to a `VPOperations`, who moves the decision from `LABOR_REVIEW` to `APPROVED`, stamping `approved_by_user_id` and freezing `approved_at` to the logical clock. The segregation net widens here: the labor approver must differ from both the proposer and the economic reviewer, or the same `ERR_SEGREGATION_OF_DUTIES` fires.

Rejection is available to either a `Controller` or a `VPOperations` from either review state — `ECONOMIC_REVIEW → REJECTED` and `LABOR_REVIEW → REJECTED` — and may carry an optional `reason`. Rejection is not terminal for the idea: a `SmelterManager` may revise a `REJECTED` decision back into `ECONOMIC_REVIEW`, supplying a fresh `depth_pct` (strictly greater than 0, at most 100), `planned_start`, and `planned_end`; the `economics_snapshot` is recomputed at revise time and `economic_reviewed_by_user_id` is cleared, forcing the decision through a fresh economic review. Any decision action invoked from a status for which that transition is not declared — approving an already-`APPROVED` decision, acting on terminal `REVERSED` or `SUPERSEDED` decisions, or reversing after the potline has left `CURTAILED` — is rejected with `ERR_DECISION_INVALID_STATE` (HTTP 409). Each successful approval, rejection, or revision increments the decision's `version`.

Execution is where the decision bites. A `SmelterManager` executes an `APPROVED` decision; the potline must currently be `OPERATING` or `CURTAILED`. Three gates then apply, in the §2.7 order: the labor notice gate requires the logical clock to have reached `approved_at` plus the smelter labor agreement's `notice_period_days` — arriving exactly at the boundary is allowed, and arriving earlier is rejected with `ERR_LABOR_NOTICE_PERIOD` (HTTP 422); the agreement-presence gate requires an `ACTIVE` labor agreement for the smelter at all, or execution is rejected with `ERR_LABOR_AGREEMENT_INACTIVE` (HTTP 409); and the hedge gate requires the smelter's `hedge_coverage_ratio` to be at least 0.5, compared unrounded, or execution is rejected with `ERR_HEDGE_COVERAGE_INSUFFICIENT` (HTTP 422). Per §2.7, the notice-period check sits ahead of the agreement-presence check in the declared evaluation order.

A successful execution cascades across three links. First, decision to potline: the potline moves from `OPERATING` or `CURTAILED` to `CURTAILED` at the decision's depth when that depth is below 100, or to `IDLE` at a depth of 100; `curtailment_depth_pct` is set to the decision's `depth_pct`; `curtailed_since` is stamped with the clock when the line leaves `OPERATING` (a deepened line keeps its existing downtime clock); `active_decision_id` is set to the decision's `id`; and the potline's `version` increments. Second, potline to smelter: the potline mutation forces `operating_posture` and `curtailed_capacity_tpd` to recompute on the next read. Third, smelter to contract: the posture change flips every `ACTIVE` power contract of the smelter whose window covers the clock into take-or-pay exposure, so settled billing thereafter covers at least `take_or_pay_pct` of contracted energy regardless of interrupted volume. The decision itself records `executed_at` and increments its `version`.

Reversal compensates an execution, but only while physics allows. A `SmelterManager` may reverse an `EXECUTED` decision only while the potline is still `CURTAILED` and its `active_decision_id` still points at that decision: the potline returns from `CURTAILED` to `OPERATING` with `curtailment_depth_pct` cleared to 0, `curtailed_since` and `active_decision_id` cleared to null, and its `version` incremented — unwinding the execute cascade so the smelter's curtailed capacity returns to its pre-execute value — while the decision moves to terminal `REVERSED` with its own `version` bump. Once the potline has reached `IDLE` or `SHUTDOWN`, the curtailment is irreversible through this action: molten metal that has been let freeze does not unfreeze on a signature.

### 3.6. Restart Planning and the Cost of Coming Back

Bringing a line back is planned, not improvised. A `SmelterManager` creates a **RestartPlan** for a potline that is `IDLE` or `SHUTDOWN` — any other status is rejected with `ERR_POTLINE_INVALID_STATE` — supplying the `potline_id` and a `planned_restart_at` that may not lie before the current logical clock. Only one live plan may exist per potline: creating a plan while another is `PLANNED` or `IN_PROGRESS` for the same potline is rejected with `ERR_RESTART_PLAN_EXISTS` (HTTP 409).

Creation freezes two things. The plan's own `restart_cost_class` copies the potline's class at that moment, and `estimated_cost_usd` is computed forward-looking on the class schedule: a `HOT` restart carries a base of 80,000 USD plus 40 USD per tonne-per-day of the potline's `capacity_tpd`; a `WARM` restart carries a base of 350,000 USD plus 120 USD per tonne-per-day plus 2,500 USD per idle day; a `COLD` restart carries a base of 1,800,000 USD — pot relining capital included — plus 400 USD per tonne-per-day plus 6,000 USD per idle day. Idle days for the estimate run from the potline's `curtailed_since` (or its `last_full_shutdown_at` when the line is `SHUTDOWN`) to `planned_restart_at`, counted in whole calendar days — the hour difference floored into 24-hour units. All schedule constants are integral, so restart costs are whole USD with no rounding.

Starting the plan moves it from `PLANNED` to `IN_PROGRESS` — a start invoked from any other plan `status` is rejected with `ERR_RESTART_PLAN_INVALID_STATE` (HTTP 409) — and is gated on environmental compliance: an `ACTIVE` environmental permit of the `SPL_DISPOSAL` family must exist for the potline's smelter, and a permit that is absent, suspended, or expired yields `ERR_PERMIT_NOT_ACTIVE` (HTTP 409). A successful start drives the potline from `IDLE` or `SHUTDOWN` into `RESTARTING`, incrementing both the plan's and the potline's `version`. Completing the plan moves its `status` from `IN_PROGRESS` to `COMPLETED` — completion from any other `status` is rejected as `ERR_RESTART_PLAN_INVALID_STATE` (HTTP 409) — and returns the potline from `RESTARTING` to `OPERATING`, clearing `curtailment_depth_pct` to 0 and both `curtailed_since` and `active_decision_id` to null, again bumping both versions.

Completion also reconciles the money. The plan's `actual_cost_usd` — null until then — is computed chronologically from realized timestamps on the same class schedule: the base plus the per-tonne-per-day rate times `capacity_tpd`, plus the per-idle-day rate times the realized idle days from `curtailed_since` or `last_full_shutdown_at` to the start timestamp, plus a crew cost of 15,000 USD per realized restart day from start to completion, with all day counts again whole calendar days. The estimate excludes this crew cost entirely, so identical plan inputs diverge between estimate and actual whenever realized timing slips.

### 3.7. Hedging and Metal Price Exposure

The trading desk manages aluminum price exposure through **HedgePosition** records. A `TradingAnalyst` opens one with the hedged `smelter_id`, an `instrument` of `LME_SWAP` or `PREMIUM_SWAP`, a strictly positive `volume_tonnes`, a strictly positive `strike_price_usd`, and a `delivery_month` in `YYYY-MM` format that may not be earlier than the month containing the current logical clock. A volume gate keeps hedges honest: the aggregate `OPEN` volume for the same smelter and delivery month, plus the new volume, must not exceed the smelter's monthly capacity basis (`rated_capacity_tpd` multiplied by 30); equality is allowed, and an excess is rejected with `ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE` (HTTP 422). A new hedge's `status` is `OPEN`, and it immediately counts into the smelter's `open_hedged_tonnes` and `hedge_coverage_ratio` on subsequent reads.

Closing moves an `OPEN` hedge to `CLOSED`: the request records `closed_price_usd`, and the position's `realized_pnl_usd` — null while `OPEN` — is computed as the closed price minus the strike, multiplied by the volume, rounded half-up to 2 decimal places. Closing drops the volume out of `open_hedged_tonnes` on the next smelter read and increments the hedge's `version`. Closing a hedge that is not `OPEN` is rejected with `ERR_INVALID_LIFECYCLE_STATE`. An `OPEN` hedge left untouched past the last day of its `delivery_month` lapses to `EXPIRED` lazily per §2.4.

### 3.8. Environmental Permits and Labor Agreements

Two compliance artifacts gate the heavy operations above. An `EHSManager` registers an **EnvironmentalPermit** with the `smelter_id`, a `permit_type` of `EMISSIONS` or `SPL_DISPOSAL` (spent potlining disposal), and a validity window with `valid_from` strictly before `valid_to`. At most one `ACTIVE` permit may exist per smelter and permit type: registering a duplicate live pair is rejected with `ERR_PERMIT_DUPLICATE_TYPE` (HTTP 409). A permit's `status` is `ACTIVE` on creation; an `EHSManager` may suspend an `ACTIVE` permit, moving its `status` to `SUSPENDED`, which is terminal — suspending one that is not `ACTIVE` is rejected with `ERR_INVALID_LIFECYCLE_STATE` — and permits also expire lazily to `EXPIRED` at `valid_to` per §2.4. The `SPL_DISPOSAL` family is the one restart starts depend on (§3.6).

A `PlatformAdmin` registers the smelter's collective **LaborAgreement** with the `union_name`, a `notice_period_days` of zero or more — the minimum number of days that must elapse between a curtailment decision's approval and its execution — a `severance_weeks_per_year` of zero or more recording the severance owed per year of service on permanent layoff, and an optional `community_impact_clause` flag that defaults to false and is recorded for review purposes while gating nothing beyond the notice mechanics. At most one agreement may be `ACTIVE` per smelter; a second live registration is rejected with `ERR_LABOR_AGREEMENT_EXISTS` (HTTP 409). A `PlatformAdmin` may expire an `ACTIVE` agreement, moving its `status` to terminal `EXPIRED`; expiring one that is not `ACTIVE` is rejected with `ERR_INVALID_LIFECYCLE_STATE`.

### 3.9. Production Planning and the Product Mix

Each month, a `Controller` publishes a **ProductionPlan** fixing how the smelter's capacity splits across product forms. The payload carries the `smelter_id`, the OCC field `expected_smelter_version` per §2.8, a `period_month` in `YYYY-MM` format that may not lie before the month containing the logical clock, and an `allocations` array. The array must contain exactly one entry per `product_form` — `BILLET`, `SLAB`, and `VALUE_ADDED` all present, with no duplicates — each entry pairing the form with a strictly positive `tonnes`. The summed tonnage must not exceed the smelter's monthly capacity basis; equality with `rated_capacity_tpd` times 30 is allowed, and an excess is rejected with `ERR_PRODUCT_MIX_OVER_CAPACITY` (HTTP 422). The computed `total_tonnes` exposes that sum.

Publication freezes the plan's economics into `total_margin_usd`. The latest `GLOBAL` `ALUMINUM_LME` observation and the latest `REGIONAL_PREMIUM` observation for the smelter's region — both at or before the clock, ties broken by `created_at` descending — feed every line, and a missing either one is rejected with `ERR_NO_PRICE_OBSERVATION`. Each allocation's per-tonne margin is the LME price plus the regional premium minus a conversion cost — 180 USD per tonne for `BILLET`, 220 for `SLAB`, 350 for `VALUE_ADDED` — and `VALUE_ADDED` lines additionally earn a premium whose tier depends on the whole basket: the value-added share of the plan's total tonnage is computed before any line is priced, and a share below 10% earns 120 USD per tonne, a share from 10% through 25% earns 180 (the 25% boundary belongs to this middle tier), and a share above 25% earns 240. The pinned rounding order rounds each line's per-tonne margin half-up to 2 decimals first, then multiplies by that line's tonnage, then sums the products into `total_margin_usd`. Because the share depends on the basket total, recomputing any line's margin without the whole basket is invalid.

Publication is also the supersession point: creating a plan increments the smelter's `version` by 1, and any prior plan still `PUBLISHED` for the same smelter and `period_month` flips to terminal `SUPERSEDED` with its own `version` bump. A plan's `status` is `PUBLISHED` on creation and never returns once superseded.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a smelter, adding a potline, drafting a contract, recording an interruption or price observation, opening a hedge, registering an agreement, proposing a decision, planning a restart, registering a permit or labor agreement, or publishing a production plan — return `201 Created`. Reads, state-changing actions, and the clock-set capability return `200 OK`. The complete request parameters, preconditions, and side effects of every endpoint are specified by the narratives of §2 and §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving; outside the `/smelter-ops` business surface) | PlatformAdmin |
| POST | `/smelter-ops/smelters` | Onboard a smelter site | PlatformAdmin |
| GET | `/smelter-ops/smelters/{id}` | Read a smelter including computed posture, open hedged tonnage, curtailed capacity, and hedge coverage | All roles |
| POST | `/smelter-ops/potlines` | Create a potline (starts `OPERATING`); requires a covering `ACTIVE` power contract | SmelterManager |
| GET | `/smelter-ops/potlines/{id}` | Read a potline including computed restart cost class | All roles |
| POST | `/smelter-ops/potlines/{id}/curtail` | Emergency curtail, deepen, or restore by `depth_pct` | SmelterManager |
| POST | `/smelter-ops/potlines/{id}/shutdown` | Full shutdown of an `IDLE` potline reached through an executed depth-100 decision | SmelterManager |
| POST | `/smelter-ops/power-contracts` | Create a power contract in `DRAFT` with fixed, market-indexed, and interruptible components | EnergyManager |
| GET | `/smelter-ops/power-contracts/{id}` | Read a contract including computed forward and settled costs and settlement (nulls when price data is missing) | All roles |
| POST | `/smelter-ops/power-contracts/{id}/activate` | Activate a `DRAFT` contract; rejects on half-open window overlap | EnergyManager |
| POST | `/smelter-ops/interrupt-events` | Record a grid-operator interruption of a contract's interruptible component | EnergyManager |
| POST | `/smelter-ops/price-observations` | Append an immutable market price observation | TradingAnalyst, EnergyManager |
| POST | `/smelter-ops/hedge-positions` | Open a hedge; aggregate `OPEN` volume per smelter and delivery month is capped at monthly capacity | TradingAnalyst |
| POST | `/smelter-ops/hedge-positions/{id}/close` | Close an `OPEN` hedge at a price; computes realized P&L | TradingAnalyst |
| POST | `/smelter-ops/alumina-agreements` | Register an internal alumina transfer-pricing agreement (effective immediately) | Controller |
| POST | `/smelter-ops/curtailment-decisions` | Propose a curtailment decision (`ECONOMIC_REVIEW`); OCC on `expected_potline_version`; supersedes a prior `ECONOMIC_REVIEW` decision | SmelterManager |
| POST | `/smelter-ops/curtailment-decisions/{id}/economic-approve` | Controller economic approval: `ECONOMIC_REVIEW` to `LABOR_REVIEW`; reviewer must differ from proposer | Controller |
| POST | `/smelter-ops/curtailment-decisions/{id}/labor-approve` | VPOperations labor and community approval: `LABOR_REVIEW` to `APPROVED`; approver must differ from proposer and economic reviewer | VPOperations |
| POST | `/smelter-ops/curtailment-decisions/{id}/reject` | Reject a decision in `ECONOMIC_REVIEW` or `LABOR_REVIEW` | Controller, VPOperations |
| POST | `/smelter-ops/curtailment-decisions/{id}/revise` | Revise a `REJECTED` decision back into `ECONOMIC_REVIEW`; recomputes the economics snapshot | SmelterManager |
| POST | `/smelter-ops/curtailment-decisions/{id}/execute` | Execute an `APPROVED` decision after the labor notice period and with sufficient hedge coverage; cascades onto potline, smelter posture, and contract take-or-pay exposure | SmelterManager |
| POST | `/smelter-ops/curtailment-decisions/{id}/reverse` | Reverse an `EXECUTED` decision, restoring a `CURTAILED` potline to `OPERATING`; blocked once the potline reached `IDLE` or `SHUTDOWN` | SmelterManager |
| POST | `/smelter-ops/restart-plans` | Create a restart plan for an `IDLE` or `SHUTDOWN` potline; freezes cost class and estimate | SmelterManager |
| POST | `/smelter-ops/restart-plans/{id}/start` | Begin the restart; requires an `ACTIVE` `SPL_DISPOSAL` permit; potline to `RESTARTING` | SmelterManager |
| POST | `/smelter-ops/restart-plans/{id}/complete` | Complete the restart; potline to `OPERATING`; reconciles actual cost | SmelterManager |
| POST | `/smelter-ops/environmental-permits` | Register an environmental permit (`EMISSIONS` or `SPL_DISPOSAL`); at most one `ACTIVE` per type | EHSManager |
| POST | `/smelter-ops/environmental-permits/{id}/suspend` | Suspend an `ACTIVE` permit (terminal) | EHSManager |
| POST | `/smelter-ops/labor-agreements` | Register the smelter's collective labor agreement; at most one `ACTIVE` per smelter | PlatformAdmin |
| POST | `/smelter-ops/labor-agreements/{id}/expire` | Expire an `ACTIVE` labor agreement (terminal) | PlatformAdmin |
| POST | `/smelter-ops/production-plans` | Publish the monthly product-mix plan; OCC on `expected_smelter_version`; supersedes the prior `PUBLISHED` plan | Controller |
| GET | `/smelter-ops/smelters/{id}/potlines` | List the potlines of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/power-contracts` | List the power contracts of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/hedge-positions` | List the hedge positions of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/alumina-agreements` | List the alumina transfer-pricing agreements of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/environmental-permits` | List the environmental permits of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/labor-agreements` | List the labor agreements of a smelter | All roles |
| GET | `/smelter-ops/smelters/{id}/production-plans` | List the production plans of a smelter | All roles |
| GET | `/smelter-ops/potlines/{id}/curtailment-decisions` | List the curtailment decisions of a potline | All roles |
| GET | `/smelter-ops/potlines/{id}/restart-plans` | List the restart plans of a potline | All roles |
| GET | `/smelter-ops/power-contracts/{id}/interrupt-events` | List the interrupt events of a power contract | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POTLINE_INVALID_STATE` | 409 Conflict |
| `ERR_DECISION_INVALID_STATE` | 409 Conflict |
| `ERR_RESTART_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_LIFECYCLE_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PERMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LABOR_AGREEMENT_INACTIVE` | 409 Conflict |
| `ERR_LABOR_NOTICE_PERIOD` | 422 Unprocessable Entity |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CURTAILMENT_DEPTH_INVALID` | 422 Unprocessable Entity |
| `ERR_INTERRUPTIBLE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_MIX_OVER_CAPACITY` | 422 Unprocessable Entity |
| `ERR_PERMIT_DUPLICATE_TYPE` | 409 Conflict |
| `ERR_LABOR_AGREEMENT_EXISTS` | 409 Conflict |
| `ERR_RESTART_PLAN_EXISTS` | 409 Conflict |
| `ERR_NO_ACTIVE_POWER_CONTRACT` | 422 Unprocessable Entity |
| `ERR_NO_PRICE_OBSERVATION` | 422 Unprocessable Entity |
| `ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE` | 422 Unprocessable Entity |
| `ERR_HEDGE_COVERAGE_INSUFFICIENT` | 422 Unprocessable Entity |
