# Integrated Resource Planning API — Product Requirements Document

## 1. Introduction

Electric utilities file integrated resource plans on a statutory cycle: multi-decade blueprints that reconcile load growth, aging generation, environmental compliance exposure, and capital procurement under the watch of a public utility commission. The planning process is adversarial by design — the utility proposes, intervenors testify, the public comments, and the commission decides — and every number in the record must be reconstructible after the fact. This document specifies the Integrated Resource Planning API, the system of record that carries a plan from its first load forecast through commission review, procurement commitments, and the deviation reports filed against an approved plan year after year.

The platform serves five constituencies with sharply different privileges. Utility planning staff build the plan: load forecasts across residential, commercial, industrial, and electrification scenarios; resource portfolios assembled from the existing fleet and a shelf of candidate projects; reliability snapshots that accredit each resource's contribution to the capacity margin; and retirement analyses that weigh compliance cost against replacement cost for aging units. Registered intervenors file testimony while a plan is under review. Members of the public comment during a fixed thirty-day window. Commissioners approve, conditionally approve, or reject the plan and award the procurement commitments that flow from it. A platform operator maintains the intervenor registry and drives the logical clock against which every statutory deadline, retirement year, and window boundary is evaluated.

Because plans are filed on a statutory cycle with hard deadlines, reopened only within a capped count, and superseded when a successor plan for the same cycle year is approved, the API treats time, versioning, and cross-entity consistency as first-class concerns. Every mutation that matters bumps a version counter; every comparison against "today" reads a server-controlled logical clock rather than the wall clock; and every approval decision is guarded against stale client state.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal acts. A request missing either header, or presenting a role this API does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or which violates an ownership or segregation-of-duties rule described below — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are exactly five: `UtilityPlanner`, `Commissioner`, `Intervener`, `PublicCommenter`, and `PlatformAdmin`.

- `UtilityPlanner` is utility resource-planning staff. Planners create and drive plans through their lifecycle, author and update load forecasts, register fleet resources and candidates, build portfolios and positions, compute reliability snapshots, register and finalize retirement analyses, file sensitivity analyses, acknowledge public comments, issue and cancel procurement commitments, and file deviation reports. When `X-User-Role` is `UtilityPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — notably as `created_by_user_id` on a procurement commitment at issue time — but does not compare it to any entity's `id` except where segregation of duties explicitly says so (§3.8).
- `Commissioner` is the commission reviewer. Commissioners decide plans under review and award issued procurement commitments. When `X-User-Role` is `Commissioner`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is compared to `created_by_user_id` on commitments for segregation-of-duties enforcement, and to nothing else.
- `Intervener` is a registered intervening party. When `X-User-Role` is `Intervener`, `X-User-ID` is the `id` of the acting `Intervenor` record; ownership checks on testimony compare the testimony's `intervenor_id` field to `X-User-ID`, and a filing whose `intervenor_id` does not match the caller's `X-User-ID` is rejected.
- `PublicCommenter` is a member of the public who may file comments during the comment window. When `X-User-Role` is `PublicCommenter`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is never compared to entity ids.
- `PlatformAdmin` is the platform operator. Admins register intervenors and, together with planners, drive the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All five roles may call read endpoints, subject to the per-endpoint role lists in §4; role lists there are exhaustive.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response reports the applied `limit` and `offset` in `meta`, along with `total_count` (the full size of the filtered result set) and `has_more` (whether results remain past the current page). Unless an endpoint states otherwise, list results are sorted by `created_at` ascending.

### 2.4. The Logical Clock and Statutory Calendar

The server maintains a logical clock, set exclusively through an operator-facing clock-setting capability carrying a `to_iso8601` instant. Before any clock-setting call, the clock reads exactly 2026-09-01T00:00:00Z; it never falls back to the wall clock. Every temporal comparison in the domain — comment-window membership, retirement lead time, the cycle-year filing deadline, retirement-year arrival, candidate feasibility windows — resolves "now" against this clock's calendar date or calendar year.

Setting the clock forward has a real side effect: any fleet resource in `DECIDED` status whose `retirement_year` is less than or equal to the new clock calendar year automatically transitions to `RETIRED`, and each auto-transitioned resource's `version` increments by 1. Clock-setting is available to `UtilityPlanner` and `PlatformAdmin` and responds with the new `current_utc` value, rendered as an ISO 8601 UTC timestamp without fractional digits (for example `2026-09-01T00:00:00Z`).

Two statutory constants shape the plan calendar. The public comment window lasts thirty calendar days from the date the plan opens for comment. The cycle filing deadline is September 1 of the plan's `cycle_year`: a plan that would be opened for comment with a `submitted_on` date after September 1 of its `cycle_year` is rejected at open-comment time with `ERR_CYCLE_DEADLINE_MISSED` (HTTP 422).

### 2.5. Common Resource Properties

Every persisted entity carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most entities additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer starting at 1, incremented by 1 on every mutation of that entity).

Three entity kinds are deliberately thinner. A `Position` is an append-only junction row and carries only `id` and `created_at`; it has no `updated_at` and no `version`, and it is never updated — removal is expressed by flipping its `selected` flag. A `ReliabilitySnapshot` is a computed, immutable artifact and likewise carries only `id` and `created_at`, with no `updated_at` or `version`; change is expressed by replacing the snapshot, not editing it. A `PlanDeviationReport` is an immutable periodic filing and carries only `id` and `created_at`; a report, once filed, is never modified.

Date-valued fields named `comment_window_opens_on`, `comment_window_closes_on`, and `submitted_on` are ISO dates (YYYY-MM-DD) at day resolution; comparisons against the logical clock use the clock's calendar date, not its time of day.

### 2.6. Versioning, Optimistic Concurrency, and Stale-State Rejection

Every mutable entity's `version` increments by exactly 1 on each mutation — including mutations caused by cascades rather than direct calls. Two write operations are additionally guarded by optimistic concurrency control, because a decision made from an obsolete view of the aggregate is a silent integrity failure in a regulatory record.

The commission-review operation on a plan requires a non-optional `expected_plan_version` input carrying the client's last observed `version` of the plan. If that value does not match the plan's current `version` at the moment of the call — because another review decision, a reopen, or a supersede cascade has advanced it since the client last read the plan — the call is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412).

The snapshot-compute operation on a portfolio requires a non-optional `expected_portfolio_version` input carrying the client's last observed `version` of the portfolio. Retire and cancel-retirement cascades bump the `version` of every portfolio under the deciding plan (§3.4), so a snapshot computed against an older view would silently embed obsolete fleet state; when the supplied value does not match the portfolio's current `version`, the call is rejected with `ERR_STALE_PORTFOLIO_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.7. Numeric Precision and Rounding

All rounding in the domain is round-half-up. Megawatt quantities and snapshot outputs (`total_peak_mw`, `effective_load_mw`, `accredited_supply_mw`, `load_mw`, `capacity_margin_mw`, `procurement_deviation_mw`) are carried to 2 decimal places. Monetary cost totals on retirement analyses and sensitivity analyses (`compliance_cost_usd`, `replacement_cost_usd`, `fixed_om_avoided_usd`, `net_retirement_benefit_usd`, `base_score_usd`, `adjusted_score_usd`) are carried to 0 decimal places — whole dollars — with each per-year or per-position component rounded to whole dollars before summing, not after (round-per-component-then-sum). The deviation percentage `load_deviation_pct` is carried to 4 decimal places, round-half-up. Two ranking computations are exceptions to rounding: derating factors are rounded to 2 decimal places per unit after multiplication by the base accreditation factor and before summation; and the per-MW screening-cost ranking in §3.6 uses full precision, with no rounding applied before ranking.

### 2.8. Hierarchical Consistency and Cascade Semantics

Nested paths are validated left to right: for a path naming a plan and then a child, the plan's existence is checked first (a missing plan yields `ERR_PLAN_NOT_FOUND`), and only then the child under that plan (a missing child yields the child-specific not-found error such as `ERR_FORECAST_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, or `ERR_COMMENT_NOT_FOUND`). Body-referenced identifiers (`snapshot_id`, `candidate_id`, `plan_id`, condition ids) are validated for existence in the same pass. The full not-found family is `ERR_PLAN_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_TESTIMONY_NOT_FOUND`, `ERR_INTERVENOR_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, and `ERR_CONDITION_NOT_FOUND`; each is HTTP 404.

Mutations propagate along the plan tree. Opening a plan for comment locks every forecast row of the plan; submitting it for review freezes every portfolio; reopening a rejected plan unfreezes portfolios and unlocks forecasts; a retire or cancel-retirement decision bumps the `version` of every portfolio under the deciding plan; awarding a commitment discharges the conditions it lists, bumping each discharged condition's `version`. Each affected entity's `updated_at` refreshes and `version` increments on its own mutation. Where a cascade touches many rows, each row's bump is independent and observable through the flat read endpoints (§4).

### 2.9. Validation Ordering Across a Request

When several checks could reject the same call, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication comes first (missing or undeclared credentials yield `ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_FORBIDDEN`), then existence of every path and body-referenced identifier (the 404 family, validated left to right), then optimistic-concurrency staleness (the 412 family) on the two guarded endpoints, then state gates (the 409 state family: plan-status gates, frozen portfolios, locked forecasts, commitment and testimony state), then temporal window checks (comment window, retirement lead time, cycle deadline, candidate online year — the 422 temporal family), then structural uniqueness constraints (duplicate snapshot, report, forecast, preferred-portfolio conflict, duplicate names, nameplate overcommit, duplicate position), then cross-entity referential checks (eligible-candidate, snapshot-plan mismatch, intervenor standing, referential integrity), and finally the reliability and fiscal gates on plan transitions (preferred-portfolio presence, reliability met, reopen limit, base-forecast and portfolio presence). A call failing an earlier check never surfaces a later one.

## 3. Business Logic & Workflows

### 3.1. Filing a Plan and Building the Load Forecast

A `UtilityPlanner` begins a planning cycle by creating a resource plan, supplying a human-readable `plan_name`, the statutory `cycle_year` the plan is filed under, and a `planning_horizon_years` count of modeled calendar years that must be at least 10. The plan is born in `DRAFT` status with `reopen_count` at 0. Each plan belongs to exactly one cycle year, and the cycle year later drives both the September 1 filing deadline (§2.4) and the supersession cascade (§3.8).

With the plan shell in place, the planner authors load forecast rows. Each row carries a `scenario_tag` of `BASE`, `HIGH_ELECTRIFICATION`, or `LOW_GROWTH`; a `forecast_year` naming the calendar year the row applies to, which must fall within the plan's modeled horizon — concretely, a `forecast_year` greater than `cycle_year` plus `planning_horizon_years` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); and four class contributions in megawatts — `residential_mw`, `commercial_mw`, `industrial_mw`, and `electrification_mw` — each of which must be zero or greater. Within one plan, the combination of scenario tag and forecast year is unique: a second row repeating an existing pair is rejected with `ERR_DUPLICATE_FORECAST` (HTTP 409). Rows may be created only while the owning plan is `DRAFT`; attempts against a plan that has moved on are rejected with `ERR_PLAN_NOT_DRAFT` (HTTP 409).

Two totals are computed on every forecast row. The `total_peak_mw` is the plain, unweighted sum of the four class contributions. The `effective_load_mw` is the figure reliability modeling actually consumes, and it is variant-aware. Under the default `COINCIDENT` variant, the effective load is the residential contribution at full value, plus the commercial contribution at full value, plus the industrial contribution multiplied by an industrial coincidence factor of 0.95, plus the electrification contribution at full value (a factor of 1.00). Under the `NET_PEAK` variant — which recognizes that vehicle and building electrification charging shifts off-peak — the electrification contribution counts at only sixty percent of its value (a factor of 0.60), while the other three classes are treated identically. The stored `effective_load_mw` on a forecast row always reflects the `COINCIDENT` variant; the `NET_PEAK` variant exists only as a snapshot-time request (§3.5), where the same inputs produce a lower modeled load and therefore a higher capacity margin. Both totals are carried to 2 decimal places, round-half-up, and both are recomputed whenever a row is updated.

A planner may revise an unlocked row's class contributions, in whole or in part, and the two totals recompute on save with the row's `version` incrementing. Once the plan leaves `DRAFT` for the first time, every one of its forecast rows flips `locked` to true, and any further modification of a locked row is rejected with `ERR_FORECAST_LOCKED` (HTTP 409). A rejected plan that is reopened unlocks its rows again (§3.8). Forecast rows are readable per plan or across plans, with the cross-plan list filterable by `plan_id` and the per-plan list filterable by `scenario_tag`.

### 3.2. The Fleet Registry and the Candidate Shelf

The existing fleet lives in a flat registry of resources, independent of any plan. Registering a unit takes its `unit_name`, a `resource_type` drawn from `COAL`, `GAS_CC`, `GAS_CT`, `NUCLEAR`, `HYDRO`, `SOLAR`, `WIND`, `STORAGE`, and `DEMAND_RESPONSE`, a strictly positive `nameplate_mw`, the original `in_service_year` of commercial operation, and a `fuel_type` drawn from `COAL`, `NATURAL_GAS`, `URANIUM`, `WATER`, `SUN`, `WIND`, and `NONE`. Units of type `STORAGE` or `DEMAND_RESPONSE` must declare fuel `NONE`. A new unit enters as `ACTIVE`, with `retirement_year`, `decision_year`, and `plan_id` all empty until a retirement decision attaches them (§3.4). The fleet list is filterable by `status`, `resource_type`, and `plan_id`.

The candidate shelf holds new-build projects that portfolios may draw on. Registering a candidate takes a globally unique, case-sensitive `candidate_name` — a duplicate registration is rejected with `ERR_DUPLICATE_CANDIDATE_NAME` (HTTP 409) — plus its `resource_type` and `fuel_type` from the same enumerations as fleet units (again, `STORAGE` and `DEMAND_RESPONSE` candidates must use `NONE`), a strictly positive `nameplate_mw` of offered capacity, an `online_year` of first availability that must be 2026 or later, a strictly positive overnight capital cost `capex_usd_per_kw`, a fixed operating cost `fixed_om_usd_per_kw_year` of zero or more, and a `build_lead_years` count of at least 1 from procurement commitment to online date. At registration the server stamps each candidate with a `global_sequence_index`: a single global counter assigned in candidate creation order, starting at 1 and spanning all portfolios and plans. This index — never the candidate's `id` — is the chronological tie-breaker wherever candidates are ranked by cost (§3.6, §3.9). The candidate list is filterable by `resource_type`.

### 3.3. Assembling Portfolios and Positions

A resource plan's supply-side answer is one or more portfolios. Creating a portfolio under a plan takes a non-empty `portfolio_name` (no further uniqueness rule applies to the name) and an optional `preferred_flag` that defaults to false. At most one portfolio per plan may hold the preferred flag; creating a second preferred portfolio under the same plan is rejected with `ERR_PREFERRED_PORTFOLIO_CONFLICT` (HTTP 409). Portfolios are born in `DRAFT` status. Portfolios may be created only while the owning plan is `DRAFT`; the same `ERR_PLAN_NOT_DRAFT` gate that protects forecasts applies here.

A portfolio's content is a set of positions, each joining the portfolio to one candidate with a `committed_mw` allocation. Adding a position takes the `candidate_id` and a `committed_mw` that must be strictly positive and no greater than the candidate's `nameplate_mw`; an allocation exceeding nameplate is rejected with `ERR_NAMEPLATE_EXCEEDED` (HTTP 409). A portfolio may hold at most one selected position per candidate: adding a position for a `(portfolio, candidate)` pair that already has a selected position is rejected with `ERR_DUPLICATE_POSITION` (HTTP 409). Adding a position bumps the owning portfolio's `version` by 1. Position add and remove are allowed only while the portfolio is `DRAFT`; on a `FROZEN` portfolio they are rejected with `ERR_PORTFOLIO_FROZEN` (HTTP 409).

Removing a position is a soft removal: the row's `selected` flag flips to false, the row is retained for audit, and the owning portfolio's `version` bumps by 1. A position whose `selected` flag is false no longer counts toward portfolio totals, accreditation, or scoring. Positions are listable per portfolio (filterable by `selected`), per candidate, and across portfolios with `portfolio_id` and `candidate_id` filters, and a single position is retrievable by id.

### 3.4. Retirement Decisions and Their Cascades

Retirement analysis begins with a decision against the fleet. A planner may mark an `ACTIVE` unit for retirement by naming a `retirement_year` and the `plan_id` of the draft plan under which the decision is taken. Two temporal guards apply. Checks fire in a fixed order: after existence (of both the resource and the referenced plan), the resource's own state gate fires first — retiring a unit that is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Then the retirement year must be at least two full calendar years ahead of the logical clock's current calendar year (the minimum retirement lead); a nearer year is rejected with `ERR_RETIREMENT_TOO_EARLY` (HTTP 422). Only then is the referenced plan examined: a reference to a `SUPERSEDED` plan is a referential failure surfaced as `ERR_REFERENTIAL_INTEGRITY` (HTTP 422), while a reference to a plan in any other non-draft but otherwise live state surfaces `ERR_PLAN_NOT_DRAFT` (HTTP 409).

A successful decision moves the unit `ACTIVE → DECIDED`, stamps `decision_year` with the clock's calendar year, records the deciding plan on the unit's `plan_id`, and fixes `retirement_year` — which is immutable thereafter. The unit's `version` increments by 1. The decision then cascades through the deciding plan: for every portfolio under that plan, the portfolio's `version` increments by 1, and every reliability snapshot of those portfolios whose `forecast_year` is greater than or equal to the retirement year is retire-flagged. A retire-flagged snapshot has two defining properties: it cannot satisfy the reliability precondition of commission review (§3.8), and it no longer occupies its `(portfolio_id, forecast_year)` uniqueness slot, so computing a fresh snapshot for the same slot replaces the flagged row rather than colliding with it — the fresh row carries no flag. Because the cascade bumps portfolio versions, any client holding a stale portfolio version will see its next snapshot compute rejected under the OCC rule of §2.6; this is the intended serialization point between fleet decisions and reliability modeling.

While a unit is `DECIDED` but not yet retired, two exits exist. A planner may mothball the unit when its retirement is imminent — specifically when `retirement_year` is no more than one calendar year beyond the clock's current year — moving it `DECIDED → MOTHBALLED`, a terminal state. Or the planner may cancel the retirement, moving the unit `DECIDED → ACTIVE` and clearing `retirement_year`, `decision_year`, and `plan_id`. Cancellation is allowed only while the deciding plan is in `DRAFT` or `REJECTED` status — the simplified guarantee that no live procurement was justified by the decision — and is otherwise rejected with `ERR_PLAN_NOT_DRAFT`. Cancellation also cascades: the `version` of every portfolio under the former deciding plan increments by 1 alongside the unit's own bump. When the logical clock's calendar year reaches a `DECIDED` unit's `retirement_year`, the unit auto-transitions `DECIDED → RETIRED` (terminal) as part of the clock-setting side effect (§2.4).

### 3.5. Reliability Snapshots: Accreditation, Derating, and the Capacity Margin

A reliability snapshot freezes, for one portfolio and one `forecast_year`, the arithmetic that answers the regulator's core question: does this portfolio serve load with an adequate reserve? Computing a snapshot takes the `forecast_year`, a `scenario_tag` selecting which load forecast scenario drives the modeled load, a strictly positive `fuel_price_usd_per_mmbtu` natural-gas price assumption that retirement analysis (§3.6) and sensitivity scoring (§3.7) later reference, and the OCC guard `expected_portfolio_version` described in §2.6. Two optional modifiers tune the computation. A `variant` of `NET_PEAK` — meaningful together with a `scenario_tag` of `HIGH_ELECTRIFICATION` — evaluates the snapshot's load under the net-peak electrification factor of 0.60 described in §3.1; absent the flag, load uses the `COINCIDENT` variant. An `accreditation_mode` of `DECIDED_INCLUSIVE` runs the conservative what-if described below; the default is `DECIDED_EXCLUSIVE`. The computed snapshot stores both modifiers verbatim as given (`variant` stored as null when omitted, `accreditation_mode` always stored with its resolved value), together with the request's `scenario_tag` and `fuel_price_usd_per_mmbtu` and the computed `accredited_supply_mw`, `load_mw`, `capacity_margin_mw`, `meets_requirement`, and `retire_flagged` fields. Snapshot compute is allowed while the portfolio is `DRAFT` or `FROZEN` — recompute-after-flag is precisely how a frozen portfolio's snapshots are refreshed after a retirement cascade — even though position add and remove are restricted to `DRAFT`.

The snapshot's supply side is `accredited_supply_mw`: the sum, over contributing units, of each unit's megawatts multiplied by a static accreditation factor for its resource type and an age- or step-based derating factor. The static factors are 0.90 for `COAL`, 0.88 for `GAS_CC`, 0.85 for `GAS_CT`, 0.95 for `NUCLEAR`, 0.80 for `HYDRO`, 0.40 for `SOLAR`, 0.15 for `WIND`, 0.75 for `STORAGE`, and 0.70 for `DEMAND_RESPONSE`. Contributing units are the active fleet plus the portfolio's selected positions. A fleet unit contributes its `nameplate_mw` when it is `ACTIVE`, or when it is `DECIDED` and the snapshot's `forecast_year` is strictly earlier than its `retirement_year`; otherwise it contributes zero. Under the `DECIDED_INCLUSIVE` accreditation mode, a `DECIDED` unit instead counts at full nameplate for every forecast year — the retirement decision is ignored — so the same fleet data yields a higher accredited supply and brackets the reliability outcome from above. A position's candidate contributes the position's `committed_mw` when the candidate's `online_year` is not later than the `forecast_year` and the position is selected; otherwise zero.

The derating factor refines each unit's contribution per forecast year. Coal units derate with age, where age is the forecast year minus the unit's in-service year: at age forty or below the factor is 1.00; at age fifty or above the factor reaches its floor of 0.90; between the two, the factor declines linearly by one hundredth per year, so age forty-one yields 0.99 and age forty-nine yields 0.91. A `DECIDED` coal unit's age is evaluated as of the earlier of the forecast year and its retirement year — a unit does not degrade beyond its retirement. Storage candidates and units derate with cycles, where cycles are the forecast year minus the unit's own reference year — its `online_year` for a candidate and its `in_service_year` for a fleet unit: at twenty cycles or more the factor drops to 0.75, otherwise 1.00. Demand response steps up over time: for forecast years before 2030 the factor is 0.85, and from 2030 onward it is 1.00. All other resource types carry a factor of 1.00 at every age. Candidate units drawn through positions are always treated as age zero or cycle zero relative to their own `online_year` — a candidate's in-service history is its online year. The product of megawatts, static factor, and derating factor is rounded to 2 decimal places per unit before the per-unit terms are summed into `accredited_supply_mw`.

The demand side is `load_mw`: the effective load for the snapshot's scenario and forecast year, under the snapshot's variant, drawn from the plan's stored forecasts and carried to 2 decimal places. The load is read from the stored forecast row matching the snapshot's `scenario_tag` and `forecast_year`; when the requested scenario is not `BASE` — either `HIGH_ELECTRIFICATION` or `LOW_GROWTH` — and no row exists for that scenario and year, the `BASE` row for that forecast year supplies the class contributions instead, still evaluated under the snapshot's variant. When no usable forecast row exists for the plan and forecast year at all, the compute is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The capacity question is then settled by `capacity_margin_mw`, computed as the accredited supply minus the load grossed up by a fifteen percent reserve margin — that is, the load multiplied by 1.15 is subtracted from the accredited supply, with the difference rounded to 2 decimal places. A snapshot `meets_requirement` when its capacity margin is zero or greater; a margin of exactly 0.00 passes.

Each `(portfolio_id, forecast_year)` pair hosts at most one unflagged snapshot: computing into an occupied, unflagged slot is rejected with `ERR_DUPLICATE_SNAPSHOT` (HTTP 409), while a retire-flagged occupant (§3.4) is replaced by the recompute and its flag does not carry over. Every successful compute — including such a recompute — creates a fresh snapshot row and returns HTTP 201 with it. Computing a snapshot bumps the owning portfolio's `version` by 1. Snapshots are immutable once computed, listable per portfolio (filterable by `forecast_year`) or across portfolios (filterable by `portfolio_id`), and retrievable individually by id.

### 3.6. Screening Costs and the Retirement Analysis

Two computations share a levelized-cost engine. For a candidate delivering `committed_mw` in a given year, the annual levelized cost combines a capital-recovery term and a fixed operating term. The capital-recovery factor annualizes overnight cost over a 25-year asset life at a seven percent discount rate: it is the discount rate multiplied by one-plus-the-rate raised to the 25th power, divided by one-plus-the-rate raised to the 25th power minus one. The capital term is the candidate's `capex_usd_per_kw` multiplied by that factor, multiplied by the committed megawatts and by one thousand kilowatts per megawatt. The operating term is the candidate's `fixed_om_usd_per_kw_year` multiplied by the committed megawatts and by one thousand. Their sum is the levelized annual cost for that position. A candidate is infeasible for a delivery year when its `build_lead_years` exceed the gap between the delivery year and the decision year — the logical clock's calendar year at the time the analysis is created.

A retirement analysis weighs one fleet unit's future against its replacement. Creating one names the `plan_id` of the draft plan the analysis attaches to and the `snapshot_id` whose fuel price and capacity margin feed it; the snapshot must belong to a portfolio of the same plan, or creation is rejected with `ERR_SNAPSHOT_PLAN_MISMATCH` (HTTP 422), and the analysis is born in `DRAFT` status. Any fleet unit may anchor an analysis regardless of its current status; the computation reads the unit's stored `retirement_year`, so a unit with no retirement year set cannot be analyzed — creation against one is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The analysis window runs ten calendar years inclusive, from the unit's `retirement_year` through nine years beyond.

Three cost streams are computed over the window, each per-year component rounded to whole dollars before summing. The `compliance_cost_usd` is the environmental compliance exposure avoided by retiring: for each window year, a per-MW schedule value for the unit's resource type multiplied by the unit's `nameplate_mw`. Coal's schedule starts at a base of $42,000 per MW-year, flat for years before 2030, and from 2030 onward steps up by $8,000 per MW-year for each year past 2030, never dropping below the base. Combustion-turbine gas carries a flat $6,000 per MW-year; all other resource types carry no scheduled compliance cost. The `fixed_om_avoided_usd` is the fixed operating cost avoided: for each window year, the unit type's fixed O&M rate per MW-year multiplied by `nameplate_mw` — $38,000 for coal, $14,000 for combustion-turbine gas, and $9,000 for every other type — summed across the window.

The `replacement_cost_usd` prices the capacity that must replace the retiring unit, year by year, and its allocation is pinned to remove ambiguity. First, the required replacement for a year is the retiring unit's own accredited megawatts in its retirement year — its nameplate times its static accreditation factor times its derating factor for that year, computed for that unit alone. Second, the feasible candidate set for a year comprises candidates whose `online_year` is not later than that year and whose lead time fits the decision-to-delivery gap; any candidate coming online after the year is excluded for that year. Third, the feasible set is ranked by levelized cost per megawatt-year ascending at full precision, with ties broken by `global_sequence_index` ascending — never by candidate id. Fourth, candidates are allocated greedily in rank order until cumulative allocated megawatts cover the requirement; the final candidate may be partially allocated. Years are processed strictly in ascending order, and each year's allocation is independent — megawatts allocated for one year do not reserve the candidate for the next. The year's replacement cost is the sum of the levelized annual costs of that year's allocation.

The bottom line is `net_retirement_benefit_usd`: the compliance cost avoided, plus the fixed O&M avoided, minus the replacement cost. When the benefit is strictly positive the analysis `recommendation` is `RETIRE`; when it is zero or negative the recommendation is `KEEP` — an exactly-zero benefit recommends keeping the unit. An analysis may be finalized, moving `DRAFT → FINAL` with a version bump, and later reopened, moving `FINAL → DRAFT`, provided the analysis's plan is back in `DRAFT` status — reopening against a plan in any other state is rejected with `ERR_PLAN_NOT_DRAFT`. Reopening recomputes every cost field and the recommendation from the snapshot's current fuel price, and bumps the analysis's `version`. Analyses are listable per resource, per plan, and across the system with `resource_id`, `plan_id`, and `snapshot_id` filters.

### 3.7. Sensitivity Analysis: Stressing the Portfolio Score

Commissions routinely ask how a preferred portfolio behaves when the world refuses to hold still. A sensitivity analysis perturbs one snapshot of a plan along one dimension and reports whether the portfolio's economics are robust. Creating one names the `snapshot_id` of the base snapshot — which must belong to the plan the analysis is filed under, or creation is rejected with `ERR_SNAPSHOT_PLAN_MISMATCH` — a `dimension` of `FUEL_PRICE`, `POLICY`, or `TECHNOLOGY_COST`, and a signed `delta_pct` perturbation fraction (a value of 0.25 means a twenty-five percent increase) that must lie between negative 0.50 and positive 0.50 inclusive; a delta outside that band is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The `base_score_usd` is the sum, over the snapshot's portfolio's selected positions, of each position's levelized annual cost at the snapshot's `forecast_year`, using the levelized engine of §3.6 in its per-position form. The `adjusted_score_usd` depends on the dimension. Under `FUEL_PRICE`, an optional `scoring_variant` selects the pass-through model: the default `COST_PLUS` variant moves only the fuel share of cost, so the adjusted score is the base score scaled by one plus thirty-five percent of the delta — the base multiplied by one plus the product of a 0.35 fuel share and `delta_pct`; the `MARKET` variant moves the full score with the price, so the adjusted score is the base multiplied by one plus `delta_pct`, yielding a materially larger swing from the same inputs. Under `POLICY`, only positions whose candidate's resource type is `COAL`, `GAS_CC`, or `GAS_CT` absorb the perturbation, at half strength: the adjusted score is the base cost of all other positions, unadjusted, plus the base cost of the fossil positions multiplied by one plus the product of a 0.5 policy factor and `delta_pct`. Under `TECHNOLOGY_COST`, each position's capital term is scaled by one plus `delta_pct` while its fixed operating term is left unscaled. Both scores are whole-dollar, round-half-up.

The analysis then renders a verdict: `robust_flag` is true when the absolute difference between the adjusted and base scores is at most ten percent of the base score — the boundary is inclusive, so a difference of exactly ten percent still counts as robust. Sensitivity analyses are listable per plan (filterable by `dimension` and `snapshot_id`), across plans with `plan_id` and `snapshot_id` filters, and retrievable individually by id.

### 3.8. The Plan Lifecycle: Comment, Review, Decision, Reopen, Supersede

A plan moves through seven statuses: `DRAFT`, `OPEN_FOR_COMMENT`, `UNDER_REVIEW`, `APPROVED`, `APPROVED_WITH_CONDITIONS`, `REJECTED`, and the terminal `SUPERSEDED`.

Opening a plan for comment is the first public act, and it enforces its checks in a deliberate order after the generic layers of §2.9: a plan with no `BASE`-scenario forecast row is rejected with `ERR_PLAN_MISSING_BASE_FORECAST` (HTTP 422), a plan with no portfolio at all is rejected with `ERR_PLAN_MISSING_PORTFOLIO` (HTTP 422), and a plan whose filing would miss the cycle deadline is rejected with `ERR_CYCLE_DEADLINE_MISSED`. On success the transition `DRAFT → OPEN_FOR_COMMENT` sets `submitted_on` and `comment_window_opens_on` to the clock's calendar date — `submitted_on` is immutable once set — sets `comment_window_closes_on` thirty calendar days later, locks every forecast row, and bumps the plan's `version`. The plan list is filterable by `status`, `cycle_year`, `approved_snapshot_id`, and `preferred_portfolio_id`.

During the window the public record builds (§3.10). When the window closes, the planner submits the plan for review. Submission requires the clock's calendar date to have reached `comment_window_closes_on`; an early submission is rejected with `ERR_COMMENT_WINDOW_OPEN` (HTTP 422). It also requires exactly the preferred-portfolio marker: a plan with no portfolio carrying `preferred_flag` true is rejected with `ERR_NO_PREFERRED_PORTFOLIO` (HTTP 422). The transition `OPEN_FOR_COMMENT → UNDER_REVIEW` freezes every portfolio of the plan (`DRAFT → FROZEN`, each portfolio's `version` bumping by 1), pins the plan's `preferred_portfolio_id` to the unique preferred portfolio, and bumps the plan's `version`.

The commission's review is a single guarded operation carrying a `decision` of `APPROVE`, `APPROVE_WITH_CONDITIONS`, or `REJECT` — any other value is `ERR_INVALID_REQUEST` — plus the `expected_plan_version` guard of §2.6, and it is restricted to plans in `UNDER_REVIEW` (otherwise `ERR_PLAN_NOT_UNDER_REVIEW`, HTTP 409). For either approving decision, the preferred portfolio must present at least one snapshot with `meets_requirement` true that is not retire-flagged; without one the decision is rejected with `ERR_RELIABILITY_NOT_MET` (HTTP 422). Approval, `UNDER_REVIEW → APPROVED`, sets the plan's `approved_snapshot_id` to the preferred portfolio's most recent snapshot by `created_at` descending (ties are not broken by id; the server rejects ambiguity rather than guessing). Conditional approval, `UNDER_REVIEW → APPROVED_WITH_CONDITIONS`, additionally requires a non-empty `conditions` payload — an empty list is `ERR_INVALID_REQUEST` — and for each element creates a `PlanCondition` under the plan carrying the element's `description` and `required_procurement_mw` (zero or greater) in `OPEN` status. Rejection, `UNDER_REVIEW → REJECTED`, has no further preconditions. Every review outcome bumps the plan's `version`.

Approval carries a cycle-wide side effect: when a plan reaches `APPROVED` or `APPROVED_WITH_CONDITIONS`, any other plan with the same `cycle_year` already in either approved state auto-transitions to `SUPERSEDED`, each superseded plan's `version` bumping by 1. A superseded plan's `OPEN` conditions remain attached for audit, but no new commitment may reference them.

A rejected plan is not dead. While `reopen_count` is below the hard cap of two, the planner may reopen a plan sitting in `REJECTED`; a reopen attempted when the count has already reached two is rejected with `ERR_PLAN_REOPEN_LIMIT` (HTTP 422), and reopening a plan in any status other than `REJECTED` is `ERR_INVALID_STATE`. The transition `REJECTED → DRAFT` increments `reopen_count` by 1, unfreezes every portfolio (`FROZEN → DRAFT`, each portfolio's `version` bumping), unlocks every forecast row, clears `preferred_portfolio_id`, `approved_snapshot_id`, both comment-window dates, and `submitted_on`, and bumps the plan's `version` — returning the plan to a fully editable state for another pass through the cycle.

### 3.9. Procurement Commitments and Plan Conditions

An approved plan authorizes procurement. Issuing a commitment against a plan requires the plan to be in `APPROVED` or `APPROVED_WITH_CONDITIONS`; against any other status the issue is rejected with `ERR_PLAN_NOT_APPROVED` (HTTP 409). The commitment names a strictly positive `committed_mw` and a `solicitation_type` of `RFP` or `SELF_BUILD`, and ordinarily names the `candidate_id` being procured. At issue the server stamps `created_by_user_id` with the issuing planner's `X-User-ID` for later segregation of duties. The aggregate committed megawatts per candidate across all commitments in `ISSUED` or `AWARDED` status must never exceed the candidate's `nameplate_mw`; when the named candidate has no uncommitted nameplate remaining at all the issue is rejected with `ERR_NO_ELIGIBLE_CANDIDATE` (HTTP 422), and when some capacity remains but the requested block would breach the cap the issue is rejected with `ERR_NAMEPLATE_EXCEEDED` (HTTP 409). A commitment is born in `ISSUED` status.

As an alternative to naming a candidate, the issue may set `auto_select` to true and supply only the megawatt block, asking the server to run the accreditation waterfall. The eligible set comprises candidates whose `online_year` is no later than the clock's calendar year plus their own `build_lead_years` — that is, candidates that can actually be online when needed — and whose aggregate committed megawatts across live commitments remain below nameplate. The set is ranked by screening levelized cost per megawatt ascending (the §3.6 engine at the delivery year), ties broken by `global_sequence_index` ascending. Allocation proceeds in rank order, each candidate contributing the lesser of the remaining need and its uncommitted nameplate. If the eligible set is empty or cannot cover the requested block, the issue is rejected with `ERR_NO_ELIGIBLE_CANDIDATE`. The first candidate in rank order to receive an allocation becomes the commitment's `candidate_id`.

A commitment may also carry `condition_discharge_ids`: a possibly empty array of plan-condition ids the commitment is meant to discharge. Every listed condition must belong to the same plan as the commitment; a condition id that does not exist or belongs to a different plan is rejected with `ERR_CONDITION_NOT_FOUND` (HTTP 404), and other cross-plan referential failures surface as `ERR_REFERENTIAL_INTEGRITY`. Listing a condition that is already `DISCHARGED` is silently ignored at issue: the condition is validated but is dropped from the commitment's stored `condition_discharge_ids`, which records only the conditions still `OPEN` at issue time.

Award is the commission's act: a `Commissioner` moves a commitment `ISSUED → AWARDED`, with the same plan-status gate as issue (`ERR_PLAN_NOT_APPROVED` otherwise) and a state gate that rejects award of a commitment not in `ISSUED` with `ERR_COMMITMENT_NOT_ISSUABLE` (HTTP 409). Segregation of duties binds here: the awarding commissioner's `X-User-ID` must differ from the commitment's recorded `created_by_user_id`; the issuer awarding their own commitment is rejected with `ERR_FORBIDDEN` (HTTP 403). On award, each listed condition that is still `OPEN` transitions to `DISCHARGED`, its `version` bumping by 1, and the commitment's own `version` bumps by 1. Cancelling instead moves `ISSUED → CANCELLED` at a planner's hand, frees the commitment's megawatts from the candidate's aggregate, and bumps the commitment's `version` — but only while every listed condition is still `OPEN`; cancelling a commitment whose listed condition has already been discharged would orphan the discharge and is rejected with `ERR_CONDITION_ALREADY_DISCHARGED` (HTTP 409). Commitments are listable per plan, per candidate, and across plans with `plan_id`, `candidate_id`, and `status` filters; conditions are listable per plan (filterable by `status`), across plans by `plan_id`, and individually by id.

### 3.10. The Public Record: Comments, Intervenors, and Testimony

While a plan sits in `OPEN_FOR_COMMENT`, the public record accumulates. Anyone may file a comment carrying a `commenter_name`, a `commenter_email`, and a `body` that must be non-empty after trimming — an empty body is `ERR_INVALID_REQUEST`. Filing is gated twice: the plan must be in `OPEN_FOR_COMMENT` status (otherwise `ERR_PLAN_NOT_OPEN_FOR_COMMENT`, HTTP 409), and the clock's calendar date must fall within the comment window inclusive of both ends — a comment filed on the closing date itself is accepted, while one filed before the window opens or after it closes is rejected with `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422). A comment is born `RECEIVED`; a planner may acknowledge it (`RECEIVED → ACKNOWLEDGED`, version bumping) only while the plan remains `OPEN_FOR_COMMENT` — acknowledging against a plan in any other status is rejected with `ERR_PLAN_NOT_OPEN_FOR_COMMENT` (HTTP 409), and acknowledging a comment that is not `RECEIVED` (for example, one already acknowledged) is rejected with `ERR_INVALID_STATE` (HTTP 409). Comments are listable per plan (filterable by `status`), across plans by `plan_id`, and individually by id.

Intervenors are registered parties, not self-declared ones. A `PlatformAdmin` registers an intervenor with a globally unique, case-sensitive `legal_name` — duplicates rejected with `ERR_DUPLICATE_INTERVENOR` (HTTP 409) — a `party_type` of `CONSUMER_ADVOCATE`, `INDUSTRIAL_GROUP`, `ENVIRONMENTAL_ORG`, or `MUNICIPALITY`, and an optional `standing_approved` flag that defaults to true when omitted.

Testimony is filed while a plan is `UNDER_REVIEW`, by the intervenor acting as itself: the caller's `X-User-ID` must equal the payload's `intervenor_id`, and a mismatch — or an intervenor whose `standing_approved` is false, or an `intervenor_id` that is not even a string — is rejected with `ERR_INTERVENOR_NO_STANDING` (HTTP 422); a plan in the wrong status yields `ERR_PLAN_NOT_UNDER_REVIEW`. The filing carries a `topic` and a non-empty `body`. Each filing receives a `volume_no`: a per-intervenor, per-plan ordinal starting at 1 and incrementing by 1 for each non-withdrawn filing. A testimony is born `FILED`. Its owner — and only its owner, with ownership mismatches rejected as `ERR_FORBIDDEN` — may withdraw it (`FILED → WITHDRAWN`) and later refile it (`WITHDRAWN → FILED`), each gated on the plan still being `UNDER_REVIEW` and each bumping the testimony's `version`; refiled testimony keeps its original `volume_no`, which is never reassigned. Operating on a testimony in the wrong state (for example, withdrawing one not `FILED`) is `ERR_INVALID_STATE`. Testimonies are listable per plan (filterable by `status` and `intervenor_id`), across plans with `plan_id` and `intervenor_id` filters, and individually by id.

### 3.11. Deviation Reporting Against an Approved Plan

An approved plan is a living obligation: each year, the utility reports how reality diverged from the filing. Filing a deviation report names the `report_year` covered and the observed `actual_load_mw` coincident peak (zero or greater). The plan must be in `APPROVED` or `APPROVED_WITH_CONDITIONS` status — otherwise `ERR_PLAN_NOT_APPROVED` — and one report per plan per year is the limit: a duplicate `(plan_id, report_year)` pair is rejected with `ERR_DUPLICATE_REPORT` (HTTP 409).

The report's baseline is `baseline_load_mw`: the modeled load for `report_year` taken from the plan's approved snapshot, or — when that snapshot covers a different year — from the snapshot of the approved snapshot's portfolio for `report_year`. When no such snapshot exists, filing is rejected with `ERR_SNAPSHOT_NOT_FOUND` (HTTP 404); when the baseline load is exactly zero, filing is rejected with `ERR_INVALID_REQUEST` (HTTP 400), since the deviation percentage would divide by zero. The `load_deviation_pct` is the signed difference between actual and baseline load divided by the baseline, carried to 4 decimal places round-half-up.

Procurement discipline is measured alongside load. The `committed_procurement_mw` sums `committed_mw` over the plan's commitments in `ISSUED` or `AWARDED` status; the `required_procurement_mw` sums the demand of the plan's conditions still `OPEN`; and the `procurement_deviation_mw` is the former minus the latter, carried to 2 decimal places, with a negative value meaning the plan is short of its conditions. A report is a `material_breach` when either measure trips its wire: the absolute load deviation is strictly greater than five percent — an exactly 0.0500 deviation is not a breach — or the procurement deviation is strictly negative. Reports are immutable once filed, listable per plan or across plans by `plan_id`, and retrievable individually by id.

## 4. Endpoint Definitions

All endpoints are root-mounted. Creation of a new resource returns HTTP 201 with the created resource; modifications, state transitions, and reads return HTTP 200. Error responses use the codes catalogued in §5. Request payloads, computed fields, and side effects are defined by the narratives of §2 and §3; the table below is a routing summary only. Path parameters are `planId`, `forecastId`, `resourceId`, `portfolioId`, `positionId`, `candidateId`, `snapshotId`, `analysisId`, `commentId`, `intervenorId`, `testimonyId`, `sensitivityId`, `commitmentId`, `conditionId`, and `reportId`; each names the `id` of the corresponding resource and is validated for existence left to right as described in §2.8.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock; auto-retires `DECIDED` resources whose year has arrived | UtilityPlanner, PlatformAdmin |
| POST | `/plans` | Create a resource plan in `DRAFT` | UtilityPlanner |
| GET | `/plans` | List plans, filterable by status, cycle year, and pinned references | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/plans/{planId}` | Get one plan | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| POST | `/plans/{planId}/open-comment` | Move `DRAFT → OPEN_FOR_COMMENT`; locks forecasts, sets window and filing date, enforces the cycle deadline | UtilityPlanner |
| POST | `/plans/{planId}/submit-for-review` | Move `OPEN_FOR_COMMENT → UNDER_REVIEW`; freezes portfolios and pins the preferred portfolio | UtilityPlanner |
| POST | `/plans/{planId}/commission-review` | Decide the plan: approve, approve with conditions, or reject; OCC-guarded; supersedes same-cycle approved plans | Commissioner |
| POST | `/plans/{planId}/reopen` | Move `REJECTED → DRAFT` within the reopen cap; unfreezes portfolios and unlocks forecasts | UtilityPlanner |
| POST | `/plans/{planId}/forecasts` | Create a forecast row on a `DRAFT` plan | UtilityPlanner |
| GET | `/plans/{planId}/forecasts` | List a plan's forecast rows | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/plans/{planId}/forecasts/{forecastId}` | Get one forecast row under a plan | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| PUT | `/plans/{planId}/forecasts/{forecastId}` | Update a forecast row's class contributions while unlocked | UtilityPlanner |
| GET | `/forecasts` | List forecast rows across plans, filterable by `plan_id` | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/forecasts/{forecastId}` | Get one forecast row by id (flat form) | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| POST | `/resources` | Register a fleet resource in `ACTIVE` | UtilityPlanner |
| GET | `/resources` | List fleet resources, filterable by `status`, `resource_type`, `plan_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/resources/{resourceId}` | Get one fleet resource | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/resources/{resourceId}/retire` | Move `ACTIVE → DECIDED`; stamps retirement fields and retire-flags affected snapshots | UtilityPlanner |
| POST | `/resources/{resourceId}/cancel-retirement` | Move `DECIDED → ACTIVE` while the deciding plan is `DRAFT` or `REJECTED` | UtilityPlanner |
| POST | `/resources/{resourceId}/mothball` | Move `DECIDED → MOTHBALLED` when retirement is within one year | UtilityPlanner |
| GET | `/resources/{resourceId}/retirement-analyses` | List retirement analyses for a resource | UtilityPlanner, Commissioner, PlatformAdmin |
| POST | `/plans/{planId}/portfolios` | Create a portfolio in `DRAFT`; enforces the single-preferred rule | UtilityPlanner |
| GET | `/plans/{planId}/portfolios` | List a plan's portfolios | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/plans/{planId}/portfolios/{portfolioId}` | Get one portfolio under a plan | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/portfolios/{portfolioId}` | Get one portfolio by id (flat form) | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/portfolios` | List portfolios across plans, filterable by `plan_id` | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| POST | `/portfolios/{portfolioId}/positions` | Add a candidate position to a `DRAFT` portfolio | UtilityPlanner |
| GET | `/portfolios/{portfolioId}/positions` | List a portfolio's positions, filterable by `selected` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| DELETE | `/portfolios/{portfolioId}/positions/{positionId}` | Soft-remove a position (`selected` false; row retained) | UtilityPlanner |
| GET | `/positions/{positionId}` | Get one position by id (flat form) | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/positions` | List positions across portfolios, filterable by `portfolio_id`, `candidate_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/portfolios/{portfolioId}/snapshots` | Compute or recompute a reliability snapshot; OCC-guarded; allowed on `DRAFT` and `FROZEN` portfolios | UtilityPlanner |
| GET | `/portfolios/{portfolioId}/snapshots` | List a portfolio's snapshots, filterable by `forecast_year` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/portfolios/{portfolioId}/snapshots/{snapshotId}` | Get one snapshot under a portfolio | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/snapshots` | List snapshots across portfolios, filterable by `portfolio_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/snapshots/{snapshotId}` | Get one snapshot by id (flat form) | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/candidates` | Register a resource candidate; assigns the global sequence index | UtilityPlanner |
| GET | `/candidates` | List candidates, filterable by `resource_type` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/candidates/{candidateId}` | Get one candidate | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/candidates/{candidateId}/positions` | List positions referencing a candidate | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/candidates/{candidateId}/procurement-commitments` | List commitments referencing a candidate | UtilityPlanner, Commissioner, PlatformAdmin |
| POST | `/resources/{resourceId}/retirement-analyses` | Create a retirement analysis against a snapshot of the same plan | UtilityPlanner |
| GET | `/retirement-analyses/{analysisId}` | Get one retirement analysis | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/plans/{planId}/retirement-analyses` | List analyses attached to a plan | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/retirement-analyses` | List retirement analyses across the system, filterable by `resource_id`, `plan_id`, `snapshot_id` | UtilityPlanner, Commissioner, PlatformAdmin |
| POST | `/retirement-analyses/{analysisId}/finalize` | Move `DRAFT → FINAL` | UtilityPlanner |
| POST | `/retirement-analyses/{analysisId}/reopen` | Move `FINAL → DRAFT`; recomputes from the current snapshot fuel price | UtilityPlanner |
| POST | `/plans/{planId}/comments` | File a public comment within the comment window | PublicCommenter, UtilityPlanner |
| GET | `/plans/{planId}/comments` | List a plan's comments, filterable by `status` | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/comments` | List comments across plans, filterable by `plan_id` | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| GET | `/comments/{commentId}` | Get one comment by id (flat form) | UtilityPlanner, Commissioner, Intervener, PublicCommenter, PlatformAdmin |
| POST | `/plans/{planId}/comments/{commentId}/acknowledge` | Move a comment `RECEIVED → ACKNOWLEDGED` during the comment period | UtilityPlanner |
| POST | `/intervenors` | Register an intervenor | PlatformAdmin |
| GET | `/intervenors` | List intervenors | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/intervenors/{intervenorId}` | Get one intervenor | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/plans/{planId}/testimonies` | File testimony on a plan under review, acting as the registered intervenor | Intervener |
| GET | `/plans/{planId}/testimonies` | List a plan's testimonies, filterable by `status`, `intervenor_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/testimonies/{testimonyId}` | Get one testimony | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/testimonies` | List testimonies across plans, filterable by `plan_id`, `intervenor_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/testimonies/{testimonyId}/withdraw` | Move `FILED → WITHDRAWN` (owner only) | Intervener |
| POST | `/testimonies/{testimonyId}/refile` | Move `WITHDRAWN → FILED`, preserving the volume number (owner only) | Intervener |
| POST | `/plans/{planId}/sensitivities` | Run a sensitivity analysis on a snapshot of the plan | UtilityPlanner |
| GET | `/plans/{planId}/sensitivities` | List a plan's sensitivity analyses, filterable by `dimension`, `snapshot_id` | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/sensitivities` | List sensitivity analyses across plans, filterable by `plan_id`, `snapshot_id` | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/sensitivities/{sensitivityId}` | Get one sensitivity analysis by id (flat form) | UtilityPlanner, Commissioner, PlatformAdmin |
| POST | `/plans/{planId}/procurement-commitments` | Issue a commitment against an approved plan; supports `auto_select` waterfall | UtilityPlanner |
| GET | `/plans/{planId}/procurement-commitments` | List a plan's commitments, filterable by `status` | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/procurement-commitments/{commitmentId}` | Get one commitment | UtilityPlanner, Commissioner, PlatformAdmin |
| GET | `/procurement-commitments` | List commitments across plans, filterable by `plan_id`, `candidate_id`, `status` | UtilityPlanner, Commissioner, PlatformAdmin |
| POST | `/procurement-commitments/{commitmentId}/award` | Move `ISSUED → AWARDED`; discharges listed open conditions; segregation of duties applies | Commissioner |
| POST | `/procurement-commitments/{commitmentId}/cancel` | Move `ISSUED → CANCELLED`; frees committed megawatts | UtilityPlanner |
| GET | `/plans/{planId}/conditions` | List a plan's conditions, filterable by `status` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/conditions` | List plan conditions across plans, filterable by `plan_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/conditions/{conditionId}` | Get one plan condition by id (flat form) | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| POST | `/plans/{planId}/deviation-reports` | File the statutory deviation report for an approved plan and report year | UtilityPlanner |
| GET | `/plans/{planId}/deviation-reports` | List a plan's deviation reports | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/deviation-reports` | List deviation reports across plans, filterable by `plan_id` | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |
| GET | `/deviation-reports/{reportId}` | Get one deviation report by id (flat form) | UtilityPlanner, Commissioner, Intervener, PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the canonical id-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_METHOD_NOT_ALLOWED` | 405 |
| `ERR_INTERNAL` | 500 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_FORECAST_NOT_FOUND` | 404 |
| `ERR_PORTFOLIO_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_CANDIDATE_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_TESTIMONY_NOT_FOUND` | 404 |
| `ERR_INTERVENOR_NOT_FOUND` | 404 |
| `ERR_COMMITMENT_NOT_FOUND` | 404 |
| `ERR_CONDITION_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_OPEN_FOR_COMMENT` | 409 |
| `ERR_PLAN_NOT_UNDER_REVIEW` | 409 |
| `ERR_PLAN_NOT_APPROVED` | 409 |
| `ERR_PORTFOLIO_FROZEN` | 409 |
| `ERR_FORECAST_LOCKED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COMMITMENT_NOT_ISSUABLE` | 409 |
| `ERR_CONDITION_ALREADY_DISCHARGED` | 409 |
| `ERR_COMMENT_WINDOW_CLOSED` | 422 |
| `ERR_COMMENT_WINDOW_OPEN` | 422 |
| `ERR_RETIREMENT_TOO_EARLY` | 422 |
| `ERR_CYCLE_DEADLINE_MISSED` | 422 |
| `ERR_DUPLICATE_SNAPSHOT` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_DUPLICATE_FORECAST` | 409 |
| `ERR_PREFERRED_PORTFOLIO_CONFLICT` | 409 |
| `ERR_DUPLICATE_CANDIDATE_NAME` | 409 |
| `ERR_DUPLICATE_INTERVENOR` | 409 |
| `ERR_NAMEPLATE_EXCEEDED` | 409 |
| `ERR_DUPLICATE_POSITION` | 409 |
| `ERR_NO_ELIGIBLE_CANDIDATE` | 422 |
| `ERR_SNAPSHOT_PLAN_MISMATCH` | 422 |
| `ERR_INTERVENOR_NO_STANDING` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_NO_PREFERRED_PORTFOLIO` | 422 |
| `ERR_RELIABILITY_NOT_MET` | 422 |
| `ERR_PLAN_REOPEN_LIMIT` | 422 |
| `ERR_PLAN_MISSING_BASE_FORECAST` | 422 |
| `ERR_PLAN_MISSING_PORTFOLIO` | 422 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_STALE_PORTFOLIO_VERSION` | 412 |
