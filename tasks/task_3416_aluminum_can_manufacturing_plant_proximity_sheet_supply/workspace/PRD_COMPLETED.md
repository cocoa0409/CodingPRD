# Aluminum Can Manufacturing API — Product Requirements Document

## 1. Introduction

Empty aluminum cans are a bulky, low-value-density product: freight economics push can plants to site as close as possible to the filling customers they serve, and long-term supply agreements bind a plant's production capacity to a beverage filler's demand for years at a time. This document specifies the API for operating such a manufacturing network end to end — registering plants and filling customers, negotiating supply agreements whose prices pass through movements in the published aluminum index alongside a conversion-cost component for bodymaker, decorator, and necking work, scheduling production runs across plant lines, and settling each run into an auditable invoice.

The system also models the operational texture that distinguishes a real can plant. Specialty can sizes and shapes demand tooling investment that is amortized against minimum volume commitments and surfaces as early-termination exposure when an agreement ends before its volume is delivered. Graphics changeovers for seasonal graphics and craft-customer variety cost line time and add spoilage. Quality incidents covering seam integrity, coating, and customer filling-line performance can escalate into line-wide holds that block scheduling. Customer forecasts are tracked for accuracy on both a rolling and a lifetime basis, a closed-loop scrap program credits returned metal into each plant's recycled content percentage, and warehouse congestion — empty cans accumulate quickly — is projected forward so a plant never silently over-commits its space. A test-driving logical clock governs every temporal rule in this document, so agreement expiry, scrap pickup expiry, and year-to-date accumulators all behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the user's operational capacity. The system recognizes exactly five roles: `PlatformAdmin`, `PlantManager`, `LineScheduler`, `CustomerPlanner`, and `QualityEngineer`. A request missing either header, or presenting an `X-User-Role` value outside these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint, or that violates the ownership rule below, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles divide the work of the network as follows:

- A `PlatformAdmin` operates the network itself: registering plants and filling customers, publishing the monthly aluminum price index, and driving the logical clock.
- A `PlantManager` runs a plant: creating production lines, proposing and tooling can formats, drafting supply agreements, amending and terminating agreements, settling completed runs, running the operations checkpoint, and crediting scrap returns.
- A `LineScheduler` schedules and executes production: creating runs under agreements, and starting, completing, cancelling, and voiding them.
- A `CustomerPlanner` acts for one filling customer: signing and reopening that customer's agreements, filing and closing that customer's volume forecasts, and scheduling that customer's closed-loop scrap pickups.
- A `QualityEngineer` owns product quality: opening quality incidents on runs, and escalating or resolving them.

All roles share read access: every retrieval and list endpoint in the API accepts any of the five roles.

Role identity binds `X-User-ID` to resources differently per role. When `X-User-Role` is `CustomerPlanner`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's customer foreign-key field to `X-User-ID`. Concretely, a `CustomerPlanner` may sign an agreement or reopen its renegotiation only when `X-User-ID` equals that agreement's `customer_id`, may file a forecast under an agreement only under the same equality, may close a forecast only when `X-User-ID` equals the `customer_id` of the forecast's parent agreement, and may schedule a scrap return only for the Customer identified in the request path. When `X-User-Role` is `PlatformAdmin`, `PlantManager`, `LineScheduler`, or `QualityEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records the actor but never compares it to any entity's `id`. Two existence interactions pin the ordering of this rule against §2.6: when ownership is defined by the Customer id in the request path itself (scrap-return scheduling), the comparison is made before any existence check, so a mismatched `X-User-ID` is rejected with `ERR_UNAUTHORIZED` even when that customer does not exist; when ownership is defined by the `customer_id` field of another resource (an agreement, or a forecast's parent agreement), the comparison can only be made once that resource is loaded, so a request naming a nonexistent resource is rejected with `ERR_NOT_FOUND` regardless of who is calling.

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

Requests to an undefined path, or to a defined path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope. An unexpected server failure returns HTTP 500 in the same envelope with error_id `ERR_INTERNAL`.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both must be integers: a non-integer value, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. A filter parameter whose value matches no resource simply yields an empty page; filter values themselves are never validated.

Beyond pagination, list endpoints accept filters. The agreement list accepts `plant_id`, `customer_id`, and `status`; the format list accepts `plant_id`, `customer_id`, and `status`; the production-run list accepts `line_id`, `agreement_id`, `format_id`, and `status`; an agreement's forecast list accepts `status`; the scrap-return list accepts `customer_id`, `plant_id`, and `status`; the quality-incident list accepts `run_id`, `line_id`, and `status`; and a plant's line list paginates with `limit` and `offset` alone.

### 2.4. The Logical Clock and the Operations Checkpoint

All temporal behavior in the system is driven by a logical clock, never by wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; until it is explicitly set it remains at that default and never falls back to the host's clock. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied `current_utc` instant and answers with the new `current_utc`; setting the clock mutates no entity. The supplied `current_utc` may be any valid ISO 8601 instant — earlier or later than the current reading — is echoed verbatim in the response's `current_utc` field, and, like every request timestamp in this document, is read as UTC when it carries no explicit offset.

Time becomes operational through the operations checkpoint, a `PlantManager` action performed on a plant. Running the checkpoint increments that plant's `ops_run_index` by 1 and bumps the plant's `version`, then performs two expiry sweeps against the logical clock:

- Every supply agreement still in `ACTIVE` or `RENEGOTIATING` status whose `end_date` is strictly before the logical clock's current date transitions to `EXPIRED`, incrementing that agreement's `version` by 1.
- Every scrap return still `SCHEDULED` whose `pickup_window_end` is strictly before the logical clock transitions to `EXPIRED`, incrementing that return's `version` by 1.

Year-to-date accumulators follow the same clock. A plant's `scrap_credit_lbs_ytd` and `metal_consumed_lbs_ytd` accumulate a scrap credit or a run completion only when the calendar year of that mutation equals the logical clock's calendar year at the moment the mutation occurs, and the derived `recycled_content_pct` therefore always reflects the current clock year. Concretely, each run completion and each scrap credit records a ledger event tagged with the logical clock's calendar year at the moment it occurs, and voiding a completed run records a compensating negative event tagged with the calendar year of the completion it reverses; each accumulator is then the sum of its own events whose tag equals the clock's current calendar year, so advancing the clock across a year boundary re-derives both accumulators from the new year's events alone.

### 2.5. Common Resource Properties

Every primary resource — plants, customers, supply agreements, production lines, can formats, production runs, forecasts, scrap returns, and quality incidents — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by 1 on every modification, including system-driven transitions and cascade-driven updates from related resources.

`created_at` and `updated_at` are stamped from the server's wall clock; the logical clock of §2.4 governs the business temporal rules (expiry sweeps, window-versus-clock comparisons, year tagging) and never these record-keeping timestamps.

The one exception is the metal price index. A published index row is immutable after creation and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Nested Paths, Foreign Keys, and Existence Order

Requests that address nested resources are validated strictly left to right along the path: the first path-segment identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and later segments are never consulted. Once path resources exist, foreign keys carried in the request body are checked in the endpoint's declared input order, and each missing reference maps to its own error: a `plant_id` that matches no plant is rejected with `ERR_PLANT_NOT_FOUND`, a `customer_id` with `ERR_CUSTOMER_NOT_FOUND`, a `line_id` with `ERR_LINE_NOT_FOUND`, and a `format_id` with `ERR_FORMAT_NOT_FOUND` (all HTTP 404).

### 2.7. Validation Priority Order

Every request passes through nine ordered validation gates, and a request that would fail several gates is always rejected with the error from the earliest failing gate:

1. **Authentication** — the header and declared-role check of §2.1 (`ERR_UNAUTHENTICATED`), applied to all endpoints.
2. **Authorization** — role permission for the endpoint plus the `CustomerPlanner` ownership rule (`ERR_UNAUTHORIZED`), applied to all endpoints.
3. **Body shape** — required fields present, types valid, enum membership respected, declared ranges honored (a `scheduled_qty` below 5,000, a `committed_annual_units` below 1,000,000, or a non-positive value for any field declared strictly positive), ISO date and timestamp formats, and the interval rules `window_end` strictly after `window_start`, `pickup_window_end` strictly after `pickup_window_start`, and `end_date` strictly after `start_date`. Field typing is fixed: `warehouse_capacity_units`, `filling_lines_count`, `committed_annual_units`, `expected_agreement_version`, `nominal_speed_cans_per_hour`, `tooling_investment_cents`, `min_volume_commitment_units`, `scheduled_qty`, `produced_qty`, `spoiled_qty`, `forecast_qty`, and `actual_qty` must be JSON integers, while `pass_through_pct`, `conversion_cost_cents_per_1000`, `metal_lbs_per_1000_units`, `base_spoilage_pct`, `index_cents_per_lb`, `declared_weight_lbs`, and `actual_weight_lbs` accept any JSON number. Violations are rejected with `ERR_VALIDATION` (HTTP 400).
4. **Existence** — path resources validated left to right, then body foreign keys in declared input order (the 404 family of §2.6).
5. **Stale-version control** — the optimistic-concurrency checks of §2.9 on the two endpoints that carry them (`ERR_STALE_VERSION`, HTTP 412).
6. **State preconditions** — evaluated in a fixed inner order: first the target resource's own from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409, including attempts made from terminal states), then the state of the parent resource named in the path (signing when the clock has passed the agreement's end date: `ERR_AGREEMENT_WINDOW_PASSED`; run creation or run start under an agreement that is not `ACTIVE`: `ERR_AGREEMENT_NOT_ACTIVE`), then the state of resources named by body foreign keys (run creation against a format that is not `QUALIFIED`: `ERR_FORMAT_NOT_QUALIFIED`). All of these are HTTP 409.
7. **Safety gates** — a line in `QUALITY_HOLD` blocks run creation and run start (`ERR_LINE_QUALITY_HOLD`, HTTP 409), and a plant in `LOCKDOWN` posture blocks run creation (`ERR_PLANT_LOCKDOWN`, HTTP 409). The quality-hold check is evaluated before the lockdown check.
8. **Temporal conflicts** — for production runs, window overlap on the line (`ERR_LINE_WINDOW_OVERLAP`) is checked before the graphics changeover buffer (`ERR_CHANGEOVER_BUFFER_VIOLATION`); for scrap pickups, the pickup window conflict (`ERR_PICKUP_WINDOW_CONFLICT`) is checked before the daily pickup limit (`ERR_PICKUP_DAILY_LIMIT`). All are HTTP 409.
9. **Business constraints** — warehouse capacity on run creation (`ERR_WAREHOUSE_CAPACITY_EXCEEDED`), format retirement with open runs (`ERR_FORMAT_HAS_OPEN_RUNS`), a required price index missing at completion or settlement (`ERR_INDEX_NOT_PUBLISHED`), tooling terms missing on a specialty format at tooling time (`ERR_TOOLING_TERMS_REQUIRED`), and duplicate periods on forecasts and the price index (`ERR_DUPLICATE_PERIOD`). All are HTTP 409.

Because the gates are ordered, an earlier failure always masks later ones: a malformed body surfaces `ERR_VALIDATION` rather than any state error, and a stale agreement version surfaces `ERR_STALE_VERSION` before any state, safety, temporal, or capacity error is reported.

### 2.8. Units, Precision, and Rounding

All money is counted in cents. Unit prices are expressed in cents per thousand cans and are rounded half-up to exactly 2 decimal places whenever they are computed and stored. Invoice amounts are rounded half-up to 2 decimal places **per production run, before any summation**: each run's settled amount is rounded first, and only then are the per-run amounts summed into the agreement ledger. The alternative order — summing unrounded amounts and rounding the total — is forbidden, because the two orders yield different cents. Early-termination exposure components are rounded half-up to whole cents (0 decimal places) per component before the components are summed. Spoilage expectations and the spoilage comparison are carried at 4 decimal places with round-half-up. Forecast accuracy percentages are rounded half-up to 2 decimal places. Warehouse arithmetic — capacity, on-hand, and projection — is exact integer arithmetic in units of cans, and the congestion threshold uses an integer floor.

### 2.9. Optimistic Concurrency Control on the Agreement

Two write endpoints take a required optimistic-concurrency field, both guarding the supply agreement's `version`:

- A `POST /supply-agreements/{id}/amend` request must carry `expected_agreement_version` holding the agreement `version` the client last observed. If the supplied value does not equal the agreement's current `version` — whether it lags behind or runs ahead — the request is rejected with `ERR_STALE_VERSION` (HTTP 412): each amendment legitimately supersedes the prior terms under the renegotiation cycle, so a writer holding an older view of the agreement must not overwrite terms it has not observed.
- A `POST /supply-agreements/{id}/production-runs` request must likewise carry `expected_agreement_version` matching the agreement's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the new run must be priced under the terms the client actually observed.

No other endpoint accepts a version field. Note that creating a production run itself increments the parent agreement's `version` by 1, as do amendment and the settlement and void cascades — a client holding an `expected_agreement_version` must re-read the agreement after any of these operations.

### 2.10. Warehouse Projection and Plant Posture

Empty cans are bulky, so the system projects warehouse occupancy forward. A plant's `projected_warehouse_units` equals its `warehouse_on_hand_units` plus the sum of `scheduled_qty` over all of the plant's runs whose status is `SCHEDULED`, `IN_PROGRESS`, or `HELD`; runs in `COMPLETED`, `SETTLED`, `CANCELLED`, or `VOIDED` do not count toward the projection. A run counts toward the warehouse of its line's plant — plant attribution flows through the run's line, and the same attribution governs the lockdown check of §2.7, the capacity gate below, and the on-hand cascade of §3.5. The projection is recomputed whenever a run is created, cancelled, completed, or voided.

Subtracting the projection from `warehouse_capacity_units` gives the plant's free units, and free units derive the plant's `posture`: `LOCKDOWN` when free units are zero or negative; `CONGESTED` when free units are positive but do not exceed the integer floor of one fifth (20 percent) of `warehouse_capacity_units`; and `OPEN` otherwise. `LOCKDOWN` blocks the creation of new production runs with `ERR_PLANT_LOCKDOWN`; `CONGESTED` is reported on the plant but blocks nothing.

Independently of posture, run creation enforces a hard capacity gate: a new run with a given `scheduled_qty` is allowed only when the current `projected_warehouse_units` plus that `scheduled_qty` does not exceed `warehouse_capacity_units`. Equality with the capacity is allowed; any strict excess is rejected with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Plants, Customers, and the Price Index

A `PlatformAdmin` commissions a plant by supplying its `name`, a `region` code such as US-SW — siting near filling customers is what keeps empty-can freight economical — and its `warehouse_capacity_units`, the total can capacity of the plant's warehouse, which must be strictly positive. A new plant starts with `warehouse_on_hand_units` and `projected_warehouse_units` at 0, `posture` of `OPEN`, an `ops_run_index` of 0, and its year-to-date accumulators `scrap_credit_lbs_ytd` and `metal_consumed_lbs_ytd` at 0, which leaves the derived `recycled_content_pct` at 0 as well.

Filling customers — the beverage fillers who buy the cans — are registered by a `PlatformAdmin` with a `name`, a `home_region` code, and `filling_lines_count`, the number of filling lines the customer operates, which must be at least 1 and later gives context to filling-line performance quality specifications.

Pricing across the network hangs off a single published reference: the monthly aluminum price index. A `PlatformAdmin` publishes an index row by declaring its `period` in YYYY-MM form and the `index_cents_per_lb`, which must be strictly positive. Periods are globally unique — a second publication for a period that already exists is rejected with `ERR_DUPLICATE_PERIOD`. Both pricing moments of a production run read from this series: completion reads the index of the month one month before the run's delivery month, and settlement reads the index of the delivery month itself (§3.5, §3.6).

### 3.2. The Supply Agreement Lifecycle

A `PlantManager` drafts a long-term supply agreement between a plant and a filling customer by providing the `plant_id` and `customer_id`, the commercial terms — `committed_annual_units`, the minimum volume commitment per contract year, at least 1,000,000 cans; `pass_through_pct`, the fraction of aluminum index movement passed through to the customer, strictly greater than 0 and at most 1; and `conversion_cost_cents_per_1000`, the bodymaker, decorator, and necker conversion component in cents per thousand cans, strictly positive — plus the inclusive `start_date` and `end_date`, where the end date must fall strictly after the start date. At creation the system computes the agreement's `freight_zone` once and freezes it: `NEAR` when the plant's `region` equals the customer's `home_region`, `MID` when the two region codes differ but share their first two characters, and `FAR` otherwise. A new agreement is `DRAFT`, with `ytd_settled_units` at 0, `delivered_revenue_cents` at 0, `volume_tier` of `STANDARD`, and both accuracy fields — `rolling_accuracy_pct` and `lifetime_accuracy_pct` — at 100 until forecasts close.

Signing is the customer's act: a `CustomerPlanner` acting for the agreement's customer moves the agreement from `DRAFT` to `ACTIVE`. Signing is only possible while the logical clock's date is on or before the agreement's `end_date`; once the clock's date has passed the end date, signing is rejected with `ERR_AGREEMENT_WINDOW_PASSED`. Either side may later unwind the commercial terms: the customer's planner can reopen an `ACTIVE` agreement into `RENEGOTIATING`, and a `PlantManager` then amends it back to `ACTIVE`, applying any subset of amended `committed_annual_units`, `pass_through_pct`, `conversion_cost_cents_per_1000`, and `end_date` — terms not supplied remain unchanged — and re-evaluating the agreement's `volume_tier` against the amended commitment using the current `ytd_settled_units`. This renegotiation cycle may loop `ACTIVE` → `RENEGOTIATING` → `ACTIVE` any number of times, and every sign, reopening, and amendment increments the agreement's `version` by 1.

The `volume_tier` itself is a pure function of delivery progress: it is `REBATE` whenever `ytd_settled_units` has reached `committed_annual_units`, and `STANDARD` below that threshold. The tier matters twice — it discounts the conversion component of subsequent run pricing (§3.5), and the moment it flips, a retroactive true-up cascades across the agreement's already-settled runs (§3.6).

A `PlantManager` may early-terminate an agreement in `ACTIVE` or `RENEGOTIATING`, moving it to `TERMINATED`. Termination computes the customer's early-exit exposure and returns the breakdown in the response — `agreement_id`, the resulting `status`, `shortfall_fee_cents`, `unamortized_tooling_cents`, and `total_exposure_cents`. The shortfall fee charges for undelivered commitment: the shortfall in units is the greater of zero and `committed_annual_units` minus `ytd_settled_units`, and the fee is that shortfall divided by one thousand and multiplied by 400 cents, rounded half-up to whole cents. The tooling component sums, over every can format belonging to the agreement's customer at the agreement's plant that still stands `TOOLED` or `QUALIFIED`, each format's unamortized exposure as defined in §3.3 — each format's amount rounded half-up to whole cents first, and only then summed. The total exposure is the shortfall fee plus the unamortized tooling.

Agreements also expire of their own accord: when the operations checkpoint of §2.4 runs and the logical clock's date has passed an `ACTIVE` or `RENEGOTIATING` agreement's `end_date`, that agreement becomes `EXPIRED`. `EXPIRED` and `TERMINATED` are the agreement's terminal states, and any further transition attempted on them is rejected with `ERR_INVALID_STATE`.

### 3.3. Production Lines and Can Formats

Within a plant, a `PlantManager` commissions production lines — each a bodymaker, decorator, and necker train — by naming the line (`name`), its `nominal_speed_cans_per_hour` (strictly positive), and its `base_spoilage_pct`, the baseline spoilage fraction across those operations, which must be at least 0 and strictly less than 1. Each line records its parent through a system-populated `plant_id` taken from the request path. A line's `operational_status` starts at `RUNNING` and stands in `QUALITY_HOLD` while any quality incident on a run of that line is `ESCALATED` (§3.9).

Can formats are proposed at a plant, again by a `PlantManager`, with the `customer_id` they serve — specialty formats are customer-specific, reflecting craft customer variety — a `size_code` such as 12OZ, 16OZ, or 8OZ-SLEEK, a `shape` of `STANDARD`, `SLEEK`, `SLIM`, or `STUBBY`, the `is_specialty` flag, the format's metal intensity `metal_lbs_per_1000_units` (strictly positive), the `tooling_investment_cents`, and the `min_volume_commitment_units`. For a non-specialty format both the tooling investment and the minimum volume commitment are 0; for a specialty format both must be strictly positive — the tooling dollars and the committed volume that amortizes them travel together. That pairing is enforced at tooling time, not at proposal: at creation both fields accept any integer of zero or more whatever `is_specialty` says, so a specialty format proposed with either term at 0 is persisted but can never leave `PROPOSED`. A proposed format starts in `PROPOSED` with `delivered_units` at 0 and `unamortized_exposure_cents` at 0.

Tooling is the investment decision: a `PlantManager` tools a `PROPOSED` format into `TOOLED`. When the format is specialty, tooling is rejected with `ERR_TOOLING_TERMS_REQUIRED` unless `tooling_investment_cents` and `min_volume_commitment_units` are both strictly positive; upon tooling, a format with a positive volume commitment initializes its `unamortized_exposure_cents` to the full `tooling_investment_cents`. A tooled format is then qualified for production (`TOOLED` → `QUALIFIED`), and only `QUALIFIED` formats may be scheduled onto runs. Retirement moves a `TOOLED` or `QUALIFIED` format to `RETIRED`, but only while no run of that format stands in `SCHEDULED`, `IN_PROGRESS`, or `HELD`; otherwise retirement is rejected with `ERR_FORMAT_HAS_OPEN_RUNS`. `RETIRED` is terminal.

Amortization is tracked continuously on the format once it has been tooled — while the format stands `PROPOSED`, `unamortized_exposure_cents` reads 0: `delivered_units` accumulates the `produced_qty` of the format's settled runs and reverses when a settled run is voided, and `unamortized_exposure_cents` is the `tooling_investment_cents` multiplied by the undelivered fraction of the commitment — one minus `delivered_units` divided by `min_volume_commitment_units`, floored at zero — rounded half-up to whole cents, and simply 0 when the commitment is 0.

### 3.4. Scheduling a Production Run

A `LineScheduler` schedules a production run under an agreement — the run's `agreement_id` is taken from the path — supplying the `line_id` and `format_id`, the planned `scheduled_qty` (at least 5,000 cans), the `graphics_code` identifying the decoration, the half-open scheduling interval `window_start` to `window_end` (the end must be strictly after the start), and the concurrency token `expected_agreement_version` described in §2.9. The `line_id` and `format_id` are not cross-checked against the agreement's plant or customer: any existing line and any existing `QUALIFIED` format may be named, and the plant whose warehouse, posture, and ledgers the run affects is its line's plant (§2.10). The month of `window_end` — its YYYY-MM — is the run's delivery period and decides which price index rows price the run.

Scheduling is gated by a strict gauntlet, evaluated in the order of §2.7. The parent agreement must be `ACTIVE`, otherwise the create is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The format must be `QUALIFIED`, otherwise `ERR_FORMAT_NOT_QUALIFIED`. The line must not stand in `QUALITY_HOLD` (`ERR_LINE_QUALITY_HOLD`), and the plant must not stand in `LOCKDOWN` posture (`ERR_PLANT_LOCKDOWN`). The new window must not overlap any other run of the same line that stands in `SCHEDULED`, `IN_PROGRESS`, or `HELD`: windows are half-open, so a run whose `window_start` coincides exactly with another run's `window_end` touches without overlapping and is allowed, while any true intersection is rejected with `ERR_LINE_WINDOW_OVERLAP`. Decoration changes cost line time: when the previous run on the same line — the predecessor defined in §3.5 — carried a different `graphics_code`, at least 240 minutes (four hours) must separate that run's `window_end` from the new run's `window_start`, otherwise the create is rejected with `ERR_CHANGEOVER_BUFFER_VIOLATION`. Finally the warehouse capacity gate of §2.10 applies, rejecting with `ERR_WAREHOUSE_CAPACITY_EXCEEDED` when the projection plus the new `scheduled_qty` strictly exceeds capacity.

A created run starts in `SCHEDULED`. Its creation recomputes the plant's warehouse projection — the new `scheduled_qty` joins the projection set — and increments the parent agreement's `version` by 1, which is precisely why the next writer's `expected_agreement_version` must be re-read.

### 3.5. Executing, Completing, and Voiding Runs

Starting a run moves it from `SCHEDULED` to `IN_PROGRESS` and is a `LineScheduler` action. It is permitted only while the line's `operational_status` is `RUNNING` — a line under `QUALITY_HOLD` rejects the start with `ERR_LINE_QUALITY_HOLD` — and while the parent agreement remains `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise).

Completion is where production becomes fact. The `LineScheduler` reports the `produced_qty` of good cans and the `spoiled_qty` lost across bodymaker, decorator, and necking operations, and the run moves from `IN_PROGRESS` to `COMPLETED`. The system then records `sheet_lbs_consumed` — the total cans made, good plus spoiled, divided by one thousand and multiplied by the format's `metal_lbs_per_1000_units`, carried without rounding — and `effective_spoilage_pct`, the spoiled share of total cans made, defined as 0 when both quantities are 0.

That effective spoilage is judged against an expectation. The expected spoilage is the line's `base_spoilage_pct`, plus a specialty premium of 0.03 when the format is specialty, plus a changeover penalty of 0.02 when the run's `graphics_code` differs from the previous run's — and the whole sum is capped at 0.15, so when the sum exceeds the cap, the cap itself is the expectation. "Previous run" means the non-terminal run on the same line — one in `SCHEDULED`, `IN_PROGRESS`, `HELD`, `COMPLETED`, or `SETTLED` — with the latest `window_end` at or before this run's `window_start`, with ties broken by earliest `created_at`. When the effective spoilage, both sides carried at 4 decimal places with round-half-up, is strictly greater than the expectation, the run's `spoilage_flag` — false by default — is set true; an exact tie leaves it false.

Completion also locks the run's provisional economics. The unit price blends metal and conversion: the metal component is the format's `metal_lbs_per_1000_units` multiplied by the aluminum index in `index_cents_per_lb` and by the agreement's `pass_through_pct`; the conversion component is the agreement's `conversion_cost_cents_per_1000` multiplied by two factors — a volume factor of 0.96 (the four percent rebate) when the agreement's `ytd_settled_units` already reached `committed_annual_units` before this run's units are counted, and 1.0 otherwise, and a specialty factor of 1.12 (the twelve percent surcharge) when the format is specialty, and 1.0 otherwise. The sum of the two components is rounded half-up to 2 decimal places and stored as `provisional_unit_price_cents_per_1000`. The provisional variant reads the published index whose `period` is exactly one month before the run's delivery month; if that index row has not been published, completion is rejected with `ERR_INDEX_NOT_PUBLISHED`. Completion then cascades into the plant: `warehouse_on_hand_units` increases by `produced_qty`, `metal_consumed_lbs_ytd` increases by `sheet_lbs_consumed` when the completion falls in the logical clock's current calendar year, and the plant's projection, `posture`, and `recycled_content_pct` are recomputed.

Two reversals exist. Cancelling moves a `SCHEDULED` or `HELD` run to `CANCELLED`; its `scheduled_qty` leaves the warehouse projection set, and cancelling a `HELD` run additionally re-evaluates the line's hold — the line stays in `QUALITY_HOLD` while an `ESCALATED` incident remains on another of its runs. Voiding is the compensating reversal for recorded production: voiding a `COMPLETED` run moves it to `VOIDED`, subtracts `produced_qty` from `warehouse_on_hand_units`, subtracts `sheet_lbs_consumed` from `metal_consumed_lbs_ytd` when the completion fell in the clock's current calendar year, and recomputes the plant's projection, `posture`, and `recycled_content_pct`. Voiding a `SETTLED` run additionally reverses the settlement ledger — the agreement's `ytd_settled_units` decreases by `produced_qty`, its `delivered_revenue_cents` decreases by the run's `settled_amount_cents` plus its `tier_delta_cents`, and the format's `delivered_units` decreases by `produced_qty` with `unamortized_exposure_cents` recomputed — and re-evaluates the volume tier, as §3.6 describes. Both settlement and the voiding of a `SETTLED` run increment not only the run's `version` but also the parent agreement's `version` by 1; voiding a `COMPLETED` (never settled) run touches no agreement ledger and leaves the agreement's `version` unchanged. `CANCELLED` and `VOIDED` are the run's terminal states.

### 3.6. Settlement, Invoicing, and the Volume-Tier True-Up

Settlement converts a `COMPLETED` run into money. A `PlantManager` settles the run, moving it from `COMPLETED` to `SETTLED`. Settlement requires the published index whose `period` equals the run's delivery month — the YYYY-MM of its `window_end` — and is rejected with `ERR_INDEX_NOT_PUBLISHED` when that row is missing. With the delivery-month index in hand, the system computes `final_unit_price_cents_per_1000` with exactly the same formula as §3.5 but on the final variant of the index: the provisional price reads the month exactly one month before delivery, the final price reads the delivery month itself, so whenever those two published rows differ, identical inputs price differently. The run's invoice amount `settled_amount_cents` is the final unit price multiplied by `produced_qty` and divided by one thousand, rounded half-up to 2 decimal places — and this rounding is per run: the agreement's `delivered_revenue_cents` is the sum over its `SETTLED` runs of each run's already-rounded `settled_amount_cents` plus its `tier_delta_cents`, never a rounding of an unrounded total. Both `final_unit_price_cents_per_1000` and `settled_amount_cents` remain null until the run is settled, and every run's `tier_delta_cents` starts at 0 and stays 0 unless a tier flip touches it.

Settlement synchronizes three ledgers. The agreement's `ytd_settled_units` increases by the run's `produced_qty` and its `delivered_revenue_cents` by the `settled_amount_cents`. The format's `delivered_units` increases by `produced_qty`, with `unamortized_exposure_cents` recomputed. And the agreement's `volume_tier` is re-evaluated now that the new units count.

The tier flip is where the true-up lives. The run that crosses the commitment threshold is itself priced under the tier in force before its units were added — `STANDARD` — and is excluded from the true-up. But when that settlement flips the agreement from `STANDARD` to `REBATE`, every other `SETTLED` run of the agreement receives a retroactive credit: each such run's `tier_delta_cents` is set to the negative of its rebate on the conversion component — concretely, the agreement's `conversion_cost_cents_per_1000`, multiplied by 1.12 when that run's format is specialty and by 1.0 otherwise, then multiplied by 0.04, then multiplied by the run's `produced_qty` divided by one thousand, the whole rounded half-up to 2 decimal places and negated. The agreement's `delivered_revenue_cents` then increases by the sum of these deltas — a negative adjustment that credits the customer. Symmetrically, when voiding a settled run drops the agreement from `REBATE` back to `STANDARD`, the agreement's `delivered_revenue_cents` is decreased by the sum of the remaining `SETTLED` runs' existing `tier_delta_cents` — those deltas being negative, the decrease returns the credited rebate — and each of those runs has its `tier_delta_cents` reset to 0.

### 3.7. Forecasts and Accuracy Tracking

A `CustomerPlanner` files a volume forecast under its own agreement, declaring the `period` in YYYY-MM form and the `forecast_qty`, which may be 0 but never negative. Periods are unique per agreement: a second forecast for a period the agreement already has is rejected with `ERR_DUPLICATE_PERIOD`. Forecasts start `OPEN`.

When the period's actuals are known, the customer's planner closes the forecast by reporting `actual_qty`, moving it from `OPEN` to `CLOSED`. Closing stamps the forecast's `accuracy_pct`: defined as 100 when both the forecast and the actual are 0, and otherwise 100 times one minus the absolute gap between `forecast_qty` and `actual_qty` divided by the larger of the two, rounded half-up to 2 decimal places. `CLOSED` is terminal.

Closing cascades to the agreement, which tracks accuracy two ways from the same closed set — and the two deliberately disagree whenever per-period errors cancel out. The `rolling_accuracy_pct` is a mean of ratios: the mean of `accuracy_pct` over the up-to-three most recent closed forecasts, ordered by `period` descending with ties broken by `created_at` descending, rounded half-up to 2 decimal places; it drives line-scheduling confidence. The `lifetime_accuracy_pct` is a ratio of aggregates: 100 times one minus the absolute difference between the summed `forecast_qty` and the summed `actual_qty` across all closed forecasts, divided by the larger of the two sums, rounded half-up to 2 decimal places; it drives contract-tier confidence. When an agreement has no closed forecasts, both read 100; when every closed forecast is zero on both sides, so the two sums are both 0, `lifetime_accuracy_pct` is likewise defined as 100.

### 3.8. Closed-Loop Scrap Returns and Recycled Content

Under the closed-loop program, a `CustomerPlanner` schedules a scrap pickup for its own customer site, naming the receiving `plant_id`, the pickup window `pickup_window_start` to `pickup_window_end` (the end strictly after the start), and the `declared_weight_lbs`, which must be strictly positive. Pickup windows conflict under closed-interval semantics: two windows of the same customer that merely touch — one's end equal to the other's start — already conflict, and any overlap with another `SCHEDULED` return of that customer is rejected with `ERR_PICKUP_WINDOW_CONFLICT`. A customer may also hold at most two `SCHEDULED` pickups on a single UTC day, the day being the UTC calendar date of each pickup's `pickup_window_start`; a request whose own `pickup_window_start` date would push that day's count beyond two is rejected with `ERR_PICKUP_DAILY_LIMIT`, and per §2.7 the window-conflict check is evaluated before this daily cap. A scheduled pickup waits in `SCHEDULED`.

Verification happens at the plant: a `PlantManager` credits a scheduled return, reporting the `actual_weight_lbs` weighed on receipt and the `grade` of the scrap — `UBC`, `PROCESS`, or `MIXED`. The verified weight is recorded as `credited_weight_lbs` alongside the `grade`, and the return moves from `SCHEDULED` to `CREDITED`. The credit feeds the plant's environmental ledger: `scrap_credit_lbs_ytd` increases by the credited weight when the credit falls in the logical clock's current calendar year, and the plant's `recycled_content_pct` is recomputed as 100 times `scrap_credit_lbs_ytd` divided by `metal_consumed_lbs_ytd`, rounded half-up to 2 decimal places — and defined as 0 while no metal has been consumed in the current clock year.

A pickup that never happens expires: when the operations checkpoint of §2.4 runs and the logical clock has passed a still-`SCHEDULED` return's `pickup_window_end`, the return becomes `EXPIRED` — terminal alongside `CREDITED`.

### 3.9. Quality Incidents and Line Holds

A `QualityEngineer` opens a quality incident on a run — questioning its seam integrity, its coating, or its performance on the customer's filling lines — by supplying a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, a `defect_class` of `SEAM_INTEGRITY`, `COATING`, or `FILLING_LINE_PERFORMANCE`, and a non-empty free-text `note`. The incident starts `OPEN`. Its `run_id` ties it to the run from the path, and its `line_id` is copied from the run at creation so line-level queries never need to dereference the run.

Escalation forks the run's fate. Escalating an `OPEN` incident moves it to `ESCALATED` and, when the linked run stands `IN_PROGRESS`, drives that run to `HELD` — a run in any other status is untouched — while the run's line enters `QUALITY_HOLD`, which blocks new run creation and run starts on that line with `ERR_LINE_QUALITY_HOLD` until the hold clears.

Resolution has two deliberately different branches. Resolving an `OPEN` incident directly — without escalation — moves it straight to `RESOLVED` and leaves the run and the line untouched. Resolving an `ESCALATED` incident releases the hold it caused: the held run returns from `HELD` to `IN_PROGRESS`, but only when no other `ESCALATED` incident remains on that run's line, and the line's `operational_status` returns to `RUNNING` only when no `ESCALATED` incident remains on any run of the line. `RESOLVED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions and the operations checkpoint — return `200 OK`. Request payloads, computed fields, and cascades are specified per workflow in §3; this table is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |
| POST | `/plants` | Create a can plant | PlatformAdmin |
| GET | `/plants/{id}` | Get a plant including computed posture and warehouse fields | Any |
| POST | `/plants/{id}/run-ops` | Run the operations checkpoint and expiry sweeps | PlantManager |
| POST | `/customers` | Create a filling customer | PlatformAdmin |
| POST | `/supply-agreements` | Create a supply agreement (starts `DRAFT`) | PlantManager |
| GET | `/supply-agreements` | List agreements with filters and pagination | Any |
| GET | `/supply-agreements/{id}` | Get one agreement including computed ledger and accuracy fields | Any |
| POST | `/supply-agreements/{id}/sign` | Sign an agreement (`DRAFT` → `ACTIVE`) | CustomerPlanner |
| POST | `/supply-agreements/{id}/open-renegotiation` | Reopen terms (`ACTIVE` → `RENEGOTIATING`) | CustomerPlanner |
| POST | `/supply-agreements/{id}/amend` | Amend terms under optimistic concurrency (`RENEGOTIATING` → `ACTIVE`) | PlantManager |
| POST | `/supply-agreements/{id}/terminate` | Early-terminate an agreement and return the exposure breakdown | PlantManager |
| POST | `/metal-price-indices` | Publish the aluminum price index for a month | PlatformAdmin |
| POST | `/plants/{id}/lines` | Create a production line at a plant | PlantManager |
| GET | `/plants/{id}/lines` | List a plant's lines | Any |
| POST | `/plants/{id}/formats` | Propose a can format at a plant (starts `PROPOSED`) | PlantManager |
| GET | `/formats/{id}` | Get one can format including computed amortization fields | Any |
| GET | `/formats` | List formats filtered by plant and/or customer | Any |
| POST | `/formats/{id}/tool` | Fund and cut tooling (`PROPOSED` → `TOOLED`) | PlantManager |
| POST | `/formats/{id}/qualify` | Qualify a tooled format (`TOOLED` → `QUALIFIED`) | PlantManager |
| POST | `/formats/{id}/retire` | Retire a format (`TOOLED`/`QUALIFIED` → `RETIRED`) | PlantManager |
| POST | `/supply-agreements/{id}/production-runs` | Schedule a production run under an agreement (OCC on the agreement) | LineScheduler |
| GET | `/production-runs` | List runs with filters and pagination | Any |
| GET | `/production-runs/{id}` | Get one run including computed pricing fields | Any |
| POST | `/production-runs/{id}/start` | Start a scheduled run (`SCHEDULED` → `IN_PROGRESS`) | LineScheduler |
| POST | `/production-runs/{id}/complete` | Complete an in-progress run (`IN_PROGRESS` → `COMPLETED`) | LineScheduler |
| POST | `/production-runs/{id}/settle` | Settle a completed run (`COMPLETED` → `SETTLED`) | PlantManager |
| POST | `/production-runs/{id}/cancel` | Cancel a `SCHEDULED` or `HELD` run | LineScheduler |
| POST | `/production-runs/{id}/void` | Void a `COMPLETED` or `SETTLED` run with compensating reversal | LineScheduler |
| POST | `/supply-agreements/{id}/forecasts` | File a volume forecast for a period | CustomerPlanner |
| GET | `/supply-agreements/{id}/forecasts` | List an agreement's forecasts | Any |
| POST | `/forecasts/{id}/close` | Close a forecast with the actual volume | CustomerPlanner |
| POST | `/customers/{id}/scrap-returns` | Schedule a closed-loop scrap pickup | CustomerPlanner |
| GET | `/scrap-returns` | List scrap returns with filters | Any |
| GET | `/scrap-returns/{id}` | Get one scrap return | Any |
| POST | `/scrap-returns/{id}/credit` | Verify and credit a collected scrap return | PlantManager |
| POST | `/production-runs/{id}/quality-incidents` | Open a quality incident on a run | QualityEngineer |
| GET | `/quality-incidents` | List quality incidents with filters | Any |
| GET | `/quality-incidents/{id}` | Get one quality incident | Any |
| POST | `/quality-incidents/{id}/escalate` | Escalate an `OPEN` incident | QualityEngineer |
| POST | `/quality-incidents/{id}/resolve` | Resolve an `OPEN` or `ESCALATED` incident | QualityEngineer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue is the identifier-to-status summary.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PLANT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_FORMAT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_PASSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_FORMAT_NOT_QUALIFIED` | 409 Conflict |
| `ERR_LINE_QUALITY_HOLD` | 409 Conflict |
| `ERR_PLANT_LOCKDOWN` | 409 Conflict |
| `ERR_LINE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CHANGEOVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_PICKUP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PICKUP_DAILY_LIMIT` | 409 Conflict |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FORMAT_HAS_OPEN_RUNS` | 409 Conflict |
| `ERR_INDEX_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TOOLING_TERMS_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE_PERIOD` | 409 Conflict |
