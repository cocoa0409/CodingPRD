# Driver Incentives API — Product Requirements Document

## 1. Introduction

Rideshare platforms live and die by the gap between rider demand and driver supply. When a market runs short — a rainy Friday in a dense urban cell, a stadium letting out, a rural zone with thin coverage — the platform's lever of choice is the incentive: a streak bonus for consecutive accepted rides, a geographic bonus zone that multiplies fares in a hot area, a time-bounded challenge that pays out when a ride target is hit, or a weekly earnings guarantee that promises a driver a minimum gross in exchange for completing a minimum number of qualifying trips. Each of these instruments moves real money, and each interacts with the others in ways that are easy to get wrong: bonuses stack or suppress each other, guarantees must be reconciled against what a driver actually earned, and the entire apparatus has to be defensible against drivers who inflate rides or collude in rings to harvest payouts they did not earn.

This document specifies the Driver Incentives API, the backend that authorizes, tracks, and settles those incentive instruments. It covers the lifecycle of a market's weekly incentive budget — how programs reserve against it, how payouts spend against it, and how the remaining headroom constrains what new programs may be activated; the parallel posture dimensions each driver carries (an eligibility dimension derived from rolling acceptance and cancellation rates, and an independent fraud dimension derived from confirmed fraud signals); the dual-variant guarantee computation that distinguishes provisional from final make-up payments; the cost-forecasting workflow that lets incentive designers justify spend before activation; and the appeal machinery that gives drivers a structured channel to dispute statements and eligibility determinations. The intended audience is the engineering team building this service. Product managers and operations staff will find the business rules stated as they are meant to behave; engineers will find every rule grounded in a named entity, field, state, or error.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers on every request: `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which that user is acting. The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `IncentiveOps`, `PaymentsOfficer`, `FraudAnalyst`, and `Driver`. A request that arrives without both headers, or whose role is not among those authorized for the target endpoint, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles differ in how `X-User-ID` is interpreted:

- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity itself. Ownership checks on any resource that references a `Driver` compare the resource's `driver_id` field to `X-User-ID`. A driver can only record rides as themselves, file or withdraw their own appeals, and provide requested information on their own appeals.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`.
- When `X-User-Role` is `IncentiveOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`.
- When `X-User-Role` is `PaymentsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`.
- When `X-User-Role` is `FraudAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`.

A request whose headers are present but whose role is not authorized for the endpoint is also rejected with `ERR_UNAUTHORIZED`. There is no separate error for "wrong role" versus "missing headers" — both surface as `ERR_UNAUTHORIZED`.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format. The same envelope shape is used when the server cannot route a request — an unmatched path returns 404 carrying `ERR_NOT_FOUND`, and a malformed JSON request body returns 400 carrying `ERR_INVALID_REQUEST`:

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

List endpoints accept two query parameters: `limit`, which caps the number of items returned, and `offset`, which skips a number of items from the front of the result set. When `limit` is omitted, it defaults to 10; the minimum legal value is 1 and the maximum legal value is 100. When `offset` is omitted, it defaults to 0; the minimum legal value is 0. A `limit` or `offset` that fails to parse as an integer, or falls outside its legal range, is refused with `ERR_INVALID_REQUEST`. All list endpoints sort their results by `created_at` in ascending order, with ties broken by `id` ascending, unless stated otherwise.

The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. The value of `total_count` is the number of items matching the filter irrespective of pagination, and `has_more` is true when further items exist beyond the current page.

### 2.4. Common Resource Properties

Every primary entity in the system — Market, Driver, IncentiveProgram, Ride, IncentiveEnrollment, GuaranteeSettlement, EarningsStatement, Appeal, FraudFlag, SupplyShortfall, and CostForecast — carries a common set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, generated at creation time.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed integer starting at 1 that increments by exactly 1 on every mutation. It is the field OCC checks are evaluated against.

A cascade that touches a parent entity (for example, freezing a market that pauses its programs, or a fraud confirm that updates a driver's posture) counts as a mutation of each affected entity: each one's `updated_at` is refreshed and each one's `version` is incremented. Derived-field recomputation (for example, recomputing a market's `budget_reserved_cents` or a driver's `acceptance_rate_bps`) is also a mutation for this purpose.

### 2.5. The Logical Clock and Time Semantics

The platform's notion of "now" is governed by a logical clock, not by wall-clock time. At server startup, before any clock-setting call has been made, the current logical instant is exactly `2026-09-01T00:00:00Z`. The clock advances only when a `PlatformAdmin` explicitly sets it via the clock-control capability, supplying a `to_iso8601` timestamp; the server then returns the current instant under `current_utc`. The clock MUST NOT fall back to wall-clock time under any circumstance — every time-dependent rule in this document (window boundaries, expiry, week bucketing, age-based decay) is evaluated against the logical clock.

Time-dependent expirations are lazy: when the logical clock passes a program's `window_end_utc` or rolls past the week a supply shortfall applied to, the corresponding `EXPIRED` transitions are evaluated on the next read or write that touches the affected resource, not on a background timer. A consequence is that a program or enrollment may report its pre-expiry state on a stale read if nothing has forced evaluation yet; clients that need a firm answer should touch the resource. A program that crosses its own `window_end_utc` does not by itself transition to a new status — the program row remains in its prior status (`ACTIVE`, `PAUSED`, …) and the only observable expiration is on the enrollments, which move from `ACTIVE` to `EXPIRED` the next time they are read or written. A supply shortfall expires to `EXPIRED` strictly after the logical clock passes the market's `created_at` week anchor plus one week plus the shortfall's `hour_bucket` hours — the comparison is strict (`now > expires_at`), so a shortfall whose `expires_at` coincides exactly with the current clock remains `OPEN` until the clock advances past it.

### 2.6. Monetary Precision and Rounding

All monetary quantities in this system are integer cents. There is no floating-point money anywhere in the API. Where a calculation involves a multiplier or division — zone multipliers, guarantee make-up, cost projections, recommended bonuses — the result is rounded to integer cents at the step where the multiplier is applied, using the rounding mode pinned to that specific calculation: zone bonuses and basis-point projections use floor; shortfall recommendations use ceiling; weekly-total aggregations sum their already-integer inputs directly, so no rounding step is needed at the aggregation layer (the "round-half-up on fractional inputs" case never arises because no aggregation ever sees a fractional input). Two rounding orders are explicitly pinned because they diverge when fractional multipliers are involved:

- For per-ride bonus accumulation (zone bonuses), the floor is applied to each ride's bonus first and the integer results are accumulated. Computing the floor over the sum of fares is forbidden. For example, three rides of 333 cents each under a 15000-basis-point multiplier yield 3 × floor(333 × 5000 / 10000) = 3 × 166 = 498 cents, not floor(999 × 5000 / 10000) = 499.
- For weekly aggregation into statements and settlements, each ride's qualifying earnings are already integer cents, so the sum is taken directly; the per-ride-then-sum order is pinned and sum-then-round is forbidden.

### 2.7. Market Budget Ledger Discipline

Each Market maintains a weekly incentive budget as three derived counters: `budget_spent_cents` (the sum of `make_up_cents` over the market's GuaranteeSettlements in `PAID` status plus the bonus payout ledger for the current week), `budget_reserved_cents` (the sum of `promised_make_up_max_cents` across the market's `ACTIVE` GUARANTEE programs), and `budget_available_cents` (the weekly `incentive_budget_cents` minus spent minus reserved). The available figure is never negative — any operation that would drive it below zero is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402). Reservations move in lockstep with program state: activation of a GUARANTEE program adds its `guaranteed_weekly_cents` to the reservation and pausing or retiring an active GUARANTEE program releases it; the market's `version` and `updated_at` are refreshed on each such adjustment.

### 2.8. Optimistic Concurrency Control

Two write endpoints in the system carry an optimistic-concurrency contract; no other endpoint takes a version field.

- Updating a market's weekly incentive budget requires the client to supply `expected_market_version` carrying the market's `version` as the client last observed it. If the market's current `version` no longer matches — for example because a program activation has advanced the budget reservation since the client read the market — the update is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412). This prevents a client whose snapshot predates a recent reservation from shrinking the budget ceiling below committed spend.
- Approving a CostForecast requires the client to supply `expected_program_version` carrying the owning IncentiveProgram's `version` as the client last observed it. A mismatch — which happens, for example, when a prior approval has already advanced the program's version — is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Approval legitimately supersedes any prior `APPROVED` forecast for the same program, so a second approval built on an older program snapshot must not silently overwrite the newer headroom math.

Endpoints not listed above do not accept a version field and do not perform an OCC check.

### 2.9. Hierarchical Validation Order

When a request targets a nested path or references multiple entities, existence is validated strictly left-to-right along the path: the market first, then the program or driver, then any deeper child resource. The first missing identifier short-circuits with `ERR_NOT_FOUND` (HTTP 404); later segments are not consulted. Validation across the whole API proceeds in a fixed priority order: authentication and role authorization first (`ERR_UNAUTHORIZED`); existence second (`ERR_NOT_FOUND`); state-machine legality third (`ERR_INVALID_STATE`); fraud-gating fourth (`ERR_FRAUD_RESTRICTED`); temporal/window rules fifth (`ERR_PROGRAM_WINDOW_CONFLICT`); cross-entity referential coherence sixth (`ERR_CROSS_MARKET_REFERENCE`); eligibility gating seventh (`ERR_DRIVER_INELIGIBLE`); budget checks eighth (`ERR_BUDGET_EXCEEDED`); program-type configuration completeness ninth (`ERR_PROGRAM_CONFIG_INCOMPLETE`); and finally general request-shape validation (`ERR_INVALID_REQUEST`). Where several of these could fire on the same request, the earlier priority wins — so, for example, a fraudulent driver attempting to enroll into a program with a malformed window surfaces `ERR_FRAUD_RESTRICTED` rather than the window conflict.

### 2.10. Driver Posture as Two Parallel Dimensions

Every Driver carries two independent posture dimensions, and nothing about one implies anything about the other. The first, `rate_posture`, is derived from rolling dispatch-event statistics and moves among `ELIGIBLE`, `PROBATION`, and `INELIGIBLE`. The second, `fraud_posture`, is derived from the driver's confirmed FraudFlags and moves among `CLEAR`, `WATCH`, and `RESTRICTED`. A driver may be `ELIGIBLE` on rates and `RESTRICTED` on fraud at the same time, or vice versa; both dimensions gate different operations, and §3 calls out which dimension guards which workflow.

### 2.11. Settlement Basis Variants

Guarantee make-up amounts are computed under one of two named basis variants, and the variant is recorded on the settlement as `basis_variant` so downstream readers can see which rule produced the figure. The `PROVISIONAL` variant applies when a settlement is first computed in `DRAFT`: it excludes rides currently in `UNDER_REVIEW` from both the earnings basis and the qualifying ride count. The `FINAL` variant applies at finalize time: it re-includes rides whose review resolved back to `COMPLETED` and permanently excludes `VOIDED` rides. The same underlying ride set can therefore produce two different `make_up_cents` figures under the two variants — this is intentional and is the reason the variant is named on the settlement.

## 3. Business Logic & Workflows

### 3.1. Markets, Budgets, and the Weekly Cycle

A `PlatformAdmin` opens a new operating region by creating a Market with a `market_code` (such as SFO or AUS), a list of `geo_cells` that partition the region for targeting purposes, and an `incentive_budget_cents` ceiling for the weekly incentive budget; the ceiling must be zero or greater. The server does not enforce global uniqueness of `market_code` across markets — it is a caller-supplied label. A freshly created market starts in `ACTIVE` status with `budget_spent_cents` and `budget_reserved_cents` both at zero and `budget_available_cents` equal to the declared ceiling. The market's `status` walks a small lifecycle: `ACTIVE` may move to `FROZEN`, `FROZEN` may return to `ACTIVE`, and either `ACTIVE` or `FROZEN` may move to the terminal `CLOSED`.

Freezing a market — a `PlatformAdmin` action available while the market is `ACTIVE` — is the emergency brake. It transitions every IncentiveProgram in that market whose status is `ACTIVE` or `DRAFT` into `PAUSED`, and each such pause releases the program's `promised_make_up_max_cents` reservation from the market's `budget_reserved_cents`. Unfreezing returns the market to `ACTIVE` but deliberately does not auto-resume the paused programs: each program must be resumed explicitly, and the market's `budget_reserved_cents` is recomputed from whichever programs are actually `ACTIVE` after the unfreeze. Closing a market is the terminal act; it is only permitted when no IncentiveProgram in the market remains `ACTIVE` and no GuaranteeSettlement in the market sits in `DRAFT` or `REOPENED`. The close cascade retires every remaining program that is still in `DRAFT` or `PAUSED` (programs already in `RETIRED` are untouched, and by the close precondition no `ACTIVE` programs remain) and expires every `OPEN` SupplyShortfall in the market.

The budget ceiling itself can be adjusted by a `PlatformAdmin` submitting a new `incentive_budget_cents` together with `expected_market_version`. The update recomputes `budget_available_cents`, increments the market's `version`, and is refused with `ERR_BUDGET_EXCEEDED` when the proposed ceiling would fall below what is already spent plus reserved. A stale `expected_market_version` is refused with `ERR_STALE_MARKET_VERSION` per §2.8.

### 3.2. Drivers, Rolling Rates, and Rate Posture

An `IncentiveOps` operator onboards a driver by supplying the `market_id` of the driver's home market and a `display_name`. The new Driver starts with `account_status` `ACTIVE`, `rate_posture` `ELIGIBLE`, `fraud_posture` `CLEAR`, and all rolling counters zeroed: `offers_total`, `accepted_total`, and `cancelled_total` are each zero, and `acceptance_rate_bps` and `cancellation_rate_bps` start at their empty-window defaults.

Dispatch activity flows into the driver's record as rate events. An `IncentiveOps` operator records a batch of them via the `events` payload on the rate-event capability; the recognized event `type` values are `OFFER_RECORDED`, `OFFER_ACCEPTED`, `OFFER_DECLINED`, and `DRIVER_CANCEL`, and an event of any other type is refused with `ERR_INVALID_REQUEST`. Accept, decline, and driver-cancel outcomes from individual rides also fold into the same statistics internally (as `OFFER_ACCEPTED`, `OFFER_DECLINED`, and `DRIVER_CANCEL` events respectively). The rolling window is the trailing 100 dispatch events — the constant is exactly 100 — with the oldest events evicted beyond that size, ordered by event `recorded_at` ascending with ties broken by `created_at` ascending (never by `id`). From this window, `offers_total` counts offers that were either accepted or declined (`OFFER_ACCEPTED` plus `OFFER_DECLINED`), `accepted_total` counts accepted offers, and `cancelled_total` counts driver-cancels after acceptance; `OFFER_RECORDED` events — including those emitted when a ride offer is first created — are part of the rolling history but do not increment any of the three counters and therefore do not move either rate. The acceptance rate in basis points is 10000 when `offers_total` is zero and otherwise the floor of 10000 times `accepted_total` divided by `offers_total`; the cancellation rate in basis points is zero when `accepted_total` is zero and otherwise the floor of 10000 times `cancelled_total` divided by `accepted_total`. Both rates are integer basis points — 10000 represents 100%.

From those two rates, `rate_posture` is derived after every recompute. When `offers_total` is below 20 — the minimum-evidence constant — the posture is left unchanged regardless of what the rates say. Otherwise: if `acceptance_rate_bps` is at least 9000 and `cancellation_rate_bps` is at most 1000, the posture is `ELIGIBLE`. Failing that, if `acceptance_rate_bps` is at least 7500 and `cancellation_rate_bps` is at most 2000, the posture is `PROBATION`. Anything else is `INELIGIBLE`. The boundary comparisons are exactly as stated — an acceptance rate of exactly 9000 basis points satisfies the `ELIGIBLE` acceptance threshold. When a recompute lands the driver in `INELIGIBLE`, the cascade fires immediately: every IncentiveEnrollment of that driver in `ACTIVE` status is moved to `CANCELLED`, and each such cancellation releases any bonus-zone capacity slot it was holding so the program's headroom is recomputed.

Recording rate events requires the driver's `account_status` to be `ACTIVE`; attempts against a deactivated driver are rejected with `ERR_INVALID_STATE`. Deactivation itself is a `PlatformAdmin` action, permitted only when the driver is `ACTIVE` and has no GuaranteeSettlement in `DRAFT` or `REOPENED`; it cancels all `ACTIVE` enrollments, dismisses all `OPEN` FraudFlags on the driver, and moves `account_status` to `DEACTIVATED`.

### 3.3. Designing Programs: Types, Windows, and Stacking

An `IncentiveOps` operator authors an IncentiveProgram with a `market_id`, a `program_type` of `STREAK`, `BONUS_ZONE`, `CHALLENGE`, or `GUARANTEE`, a human-readable `title`, a half-open operating window given by `window_start_utc` and `window_end_utc`, a `stacking_class` of `STACKABLE` or `EXCLUSIVE`, and a list of `excluded_ride_types` drawn from the platform's ride types `STANDARD`, `SHARED`, `SCHEDULED`, and `LUX`. A ride whose `ride_type` appears in a program's `excluded_ride_types` earns neither progress nor payout under that program. The window is half-open — a program whose window ends at the exact instant another begins does not overlap it — and the start must be strictly earlier than the end, or creation fails.

Each program type carries its own required configuration, and a create call that omits a type's required fields is rejected with `ERR_PROGRAM_CONFIG_INCOMPLETE` (HTTP 400). A `STREAK` program requires `streak_length` (the number of consecutive qualifying rides with no decline or driver-cancel that completes the streak — a positive integer at least 1) and `streak_payout_cents` (the bonus paid on completion — zero or greater). A `BONUS_ZONE` program requires `geo_cell_id` — which must be a member of the owning market's `geo_cells`, with violations rejected as `ERR_GEO_CELL_UNKNOWN` — plus `zone_multiplier_bps` (strictly greater than 10000, since 10000 represents par) and `capacity` (the maximum number of concurrently `ACTIVE` enrollments the zone supports, an integer at least 1 when supplied; an omitted `capacity` means the zone is uncapped). A `CHALLENGE` program requires `challenge_ride_target` (an integer at least 1) and `challenge_payout_cents` (zero or greater). A `GUARANTEE` program requires `guaranteed_weekly_cents` (zero or greater) and `guaranteed_min_rides` (zero or greater). For any non-zone program, `geo_cell_id` is null — a non-null `geo_cell_id` supplied on a non-`BONUS_ZONE` create is silently dropped and the program is stored with `geo_cell_id` null. New programs are born in `DRAFT` status.

Activation is the gate where a program becomes real. An `IncentiveOps` operator may activate a `DRAFT` program only when the owning market is `ACTIVE` (any other market state is refused with `ERR_INVALID_STATE`); when the program is a GUARANTEE, only when the market's `budget_available_cents` is at least the program's `guaranteed_weekly_cents` so the reservation fits; when the program is a `BONUS_ZONE`, only when no other `ACTIVE` zone program in the same market covers the same `geo_cell_id` with an overlapping half-open window; and only when the program's latest CostForecast, if any exists, is `APPROVED` with a `projected_cost_cents` no greater than the market's `budget_available_cents` — a program with no forecast at all may still be activated from `DRAFT`, though enrollment remains gated by the other rules; a program whose latest forecast exists but is not `APPROVED` (still `DRAFT`, already `REJECTED`, or already `SUPERSEDED`) is refused with `ERR_INVALID_STATE`. A window or overlap violation surfaces as `ERR_PROGRAM_WINDOW_CONFLICT`; an over-budget reservation surfaces as `ERR_BUDGET_EXCEEDED`. Successful activation of a GUARANTEE program sets its `promised_make_up_max_cents` to `guaranteed_weekly_cents` and adds that amount to the market's `budget_reserved_cents`; for all other program types `promised_make_up_max_cents` is zero.

Pausing an `ACTIVE` program — either by explicit `IncentiveOps` action or via the market freeze cascade — moves it to `PAUSED` and, for GUARANTEE programs, subtracts the reservation from the market and zeroes `promised_make_up_max_cents`. Resuming a `PAUSED` program requires the market to be `ACTIVE` (any other market state is refused with `ERR_INVALID_STATE`) and, for GUARANTEE programs, requires the reservation to fit the freshly recomputed `budget_available_cents`; on success the reservation is re-added. Resuming a `BONUS_ZONE` program also re-checks the zone overlap rule of §3.3 against the market's currently-`ACTIVE` zone programs and is refused with `ERR_PROGRAM_WINDOW_CONFLICT` on collision. Retirement moves a program from `DRAFT`, `ACTIVE`, or `PAUSED` to `RETIRED` and is permitted only when no enrollment on the program remains `ACTIVE`; retiring an `ACTIVE` GUARANTEE program releases its reservation, and every `OPEN` SupplyShortfall whose recommended program was this one — linked by matching `geo_cell_id` and hour-bucket coverage (computed over the program's window, walking hour by hour from the Monday 00:00:00Z of the program's `window_start_utc` week and including every hour-of-week in `[0, 167]` the window touches) — is marked `ADDRESSED`.

Programs also carry a `forecast_headroom_cents` figure, the incentive budget remaining after the latest `APPROVED` CostForecast for that program; it is recomputed each time a forecast is approved, and is `null` on a program that has never had a forecast approved.

### 3.4. Forecasting the Cost of an Incentive

Before committing budget, an `IncentiveOps` operator models a program's economics by creating a CostForecast under the program with `baseline_rides` (projected rides in the window without the incentive — zero or greater), `lift_bps` (the projected volume lift in basis points attributable to the incentive — zero or greater), and `cannibalization_bps` (the share of lifted rides expected to be pulled from other programs, in basis points of the lifted volume — zero or greater). Creation computes the projected fields and stores the forecast in `DRAFT` with a `forecast_revision` number that is monotonic per program starting at 1.

The projection runs in a pinned four-step order, with floor applied at each stage. First, `projected_incremental_rides` is the floor of `baseline_rides` times `lift_bps` divided by 10000. Second, `projected_cannibalized_rides` is the floor of `projected_incremental_rides` times `cannibalization_bps` divided by 10000. Third, the net new ride count is `projected_incremental_rides` minus `projected_cannibalized_rides`. Fourth, `projected_cost_cents` depends on the program type: for a `STREAK` program it is the floor of net new rides divided by the larger of 1 and `streak_length`, multiplied by `streak_payout_cents`; for a `BONUS_ZONE` program it is the floor of the market median base fare times `zone_multiplier_bps` minus 10000, divided by 10000, multiplied by net new rides, where the median is taken over `COMPLETED`-ride `base_fare_cents` in the market over the prior four weeks and is zero when no such history exists; for a `CHALLENGE` program it is the floor of net new rides divided by the larger of 1 and `challenge_ride_target`, multiplied by `challenge_payout_cents`; for a `GUARANTEE` program it is simply `guaranteed_weekly_cents`, a worst-case figure independent of volume. The dependency looks circular — projected cost feeds forecast headroom, which gates activation, which changes realized volume — and the pinned order is what makes the value well-defined at write time.

Approval is the act that gives a forecast force. An `IncentiveOps` operator approves a `DRAFT` forecast by supplying `expected_program_version`; the approval succeeds only when the forecast is `DRAFT` (otherwise `ERR_FORECAST_NOT_DRAFT`, HTTP 409), when `expected_program_version` is supplied and matches the program's current `version` (a missing field surfaces as `ERR_INVALID_REQUEST`; a stale value surfaces as `ERR_STALE_PROGRAM_VERSION` per §2.8), and when `projected_cost_cents` does not exceed the market's `budget_available_cents` (otherwise `ERR_BUDGET_EXCEEDED`). On approval, any prior `APPROVED` forecast for the same program transitions to `SUPERSEDED`, the program's `forecast_headroom_cents` is recomputed as the market's `budget_available_cents` minus the newly approved forecast's `projected_cost_cents`, and the program's `version` increments by one. Rejecting a `DRAFT` forecast moves it to `REJECTED` with no other effect. An `APPROVED` forecast moves to `SUPERSEDED` only when a newer forecast for the same program is approved.

### 3.5. Enrolling Drivers: Eligibility, Fraud, and Capacity Gates

Enrollment is the junction between a Driver and an IncentiveProgram. An `IncentiveOps` operator enrolls a driver into a program by naming the `driver_id`; the new IncentiveEnrollment is born `ACTIVE` with `progress_count` zero and `streak_broken` false. Creation enforces a stack of gates, and their evaluation order matters. The state gate comes first among the business rules: the program must be `ACTIVE` to accept an enrollment, and a `DRAFT`, `PAUSED`, or `RETIRED` program is refused with `ERR_INVALID_STATE`. The fraud gate comes next: a driver whose `fraud_posture` is `RESTRICTED` is refused with `ERR_FRAUD_RESTRICTED` (HTTP 422); the same gate blocks settlement finalization, so a `RESTRICTED` driver cannot have a settlement finalized either. Window and capacity rules come next: the enrollment must respect the program's window, and a `BONUS_ZONE` program with a `capacity` must have a free slot — a full zone is refused with `ERR_PROGRAM_WINDOW_CONFLICT`. Referential coherence follows: the driver's home market must equal the program's market, with violations refused as `ERR_CROSS_MARKET_REFERENCE`. Eligibility is next: a driver whose `rate_posture` is `INELIGIBLE` is refused with `ERR_DRIVER_INELIGIBLE`, while `ELIGIBLE` and `PROBATION` drivers pass. Finally, a driver who already holds an `ACTIVE` enrollment on the same program is refused with `ERR_ENROLLMENT_DUPLICATE` (HTTP 409).

An enrollment's `progress_count` carries a different meaning per program type: for `STREAK` it is the current consecutive-run length; for `CHALLENGE` it is the count of qualifying rides so far; for `GUARANTEE` it is the count of qualifying completed rides in the current week; for `BONUS_ZONE` progress is tracked through `payout_cents` instead. The `streak_broken` flag exists only for `STREAK` enrollments and latches true when a decline or driver-cancel breaks the run before completion. For `GUARANTEE` enrollments, `earned_qualifying_cents` accumulates the sum of `qualifying_earnings_cents` over the driver's `COMPLETED` rides in the program window for the current week.

Enrollments terminate in three ways. When the progress target is reached — for a `STREAK`, when `progress_count` equals the program's `streak_length` with `streak_broken` false; for a `CHALLENGE`, when `progress_count` equals `challenge_ride_target` — the system moves the enrollment to `COMPLETED` and sets its payout under the stacking resolution of §3.7. When the logical clock passes the program's `window_end_utc`, the enrollment moves to `EXPIRED` with progress retained for audit and no payout. And an `ACTIVE` enrollment may be moved to `CANCELLED` — by the driver themselves, by `IncentiveOps`, or by the system as part of the `INELIGIBLE`-rate, `RESTRICTED`-fraud, or deactivation cascades; when the cancelled enrollment belongs to a `BONUS_ZONE` program with a `capacity`, the released slot returns to the program's headroom.

### 3.6. The Ride Lifecycle and Qualifying Earnings

Rides begin life when a Driver records a ride offer with their own `driver_id` (a `driver_id` that does not match the acting `X-User-ID` is refused with `ERR_UNAUTHORIZED`), the `market_id` where the ride occurs (which may differ from the driver's home market), a `ride_type`, the `geo_cell_id` of the pickup, a `base_fare_cents` of zero or more, and `tips_cents` of zero or more. A `geo_cell_id` that is not a member of the ride market's `geo_cells` is refused with `ERR_GEO_CELL_UNKNOWN`; a `market_id` that does not exist is refused under the cross-reference rule as `ERR_CROSS_MARKET_REFERENCE`. The new ride starts in `OFFERED` with `qualifying_earnings_cents` zero, the offer event folds into the driver's rolling statistics immediately, and `request_offer_recorded` is set true on creation to record that the fold has happened.

From `OFFERED`, the driver may accept — moving the ride to `ACCEPTED`, counting the accept in their rolling rates — or decline, moving the ride to `DECLINED`. Accepting a ride requires the driver's `account_status` to be `ACTIVE`; attempting to accept on a deactivated account is refused with `ERR_INVALID_STATE`. A decline does two things beyond the rate fold: it latches `streak_broken` true and zeroes `progress_count` on every `ACTIVE` `STREAK` enrollment the driver holds. From `ACCEPTED`, completing the ride moves it to `COMPLETED`; cancelling moves it to `DRIVER_CANCELLED` or `RIDER_CANCELLED` depending on the `cancelled_by` value supplied (one of `DRIVER` or `RIDER`). A driver-cancel increments `cancelled_total`, recomputes the rolling rates, and breaks any open streak runs exactly as a decline does; a rider-cancel has no rate impact and leaves streaks untouched. Attempting to complete, flag, or void a ride from a state that does not source that transition is refused with `ERR_RIDE_NOT_COMPLETABLE`, and acting on a ride that has already reached a terminal state (`COMPLETED`, `DRIVER_CANCELLED`, `RIDER_CANCELLED`, `DECLINED`, or `VOIDED`) when a live state is required is refused with `ERR_RIDE_NOT_TERMINAL`-style semantics under `ERR_RIDE_ALREADY_TERMINAL` — both are HTTP 409. The terminal-state check is evaluated before the live-state check, so a ride in a terminal state always surfaces `ERR_RIDE_ALREADY_TERMINAL` regardless of which transition was attempted. Only the ride's own driver may accept, decline, complete, or cancel a ride — an acting `X-User-ID` that does not match the ride's `driver_id` is refused with `ERR_UNAUTHORIZED`.

Completion is where money starts moving. On the `ACCEPTED` → `COMPLETED` transition the system computes the ride's `qualifying_earnings_cents`: it equals `base_fare_cents` for a `COMPLETED` ride, and zero for any non-completed or voided ride; tips never count toward the guarantee basis. The completion instant is the current logical clock, and the ride's `completed_at` is set to that instant. Evaluated per enrollment, a ride whose `ride_type` is in the covering program's `excluded_ride_types` contributes zero to that program's progress even when completed. Each `ACTIVE` enrollment of the driver whose program window covers the completion instant (as a half-open `[window_start_utc, window_end_utc)` interval, evaluated against the logical clock) then advances per its program's rules: `STREAK` runs extend by one and complete at `streak_length`; `CHALLENGE` counts up toward `challenge_ride_target`; `BONUS_ZONE` enrollments whose `geo_cell_id` matches the ride's pickup cell accrue the per-ride zone bonus; `GUARANTEE` enrollments accumulate into `earned_qualifying_cents`. Enrollments on programs whose status is not `ACTIVE` are skipped. Streak and challenge completions move the enrollment to `COMPLETED` and add the payout to the market's `budget_spent_cents`; zone bonuses accrue ride-by-ride and each accrual increments `budget_spent_cents` individually.

### 3.7. Streaks, Zones, and the Stacking Rules

The payout arithmetic on ride completion deserves its own treatment because three program types interact on the same ride. A ride qualifies for a `STREAK` program when its `geo_cell_id` is a member of the ride market's `geo_cells`, its `ride_type` is not among the program's `excluded_ride_types`, its completion instant falls inside the half-open window `[window_start_utc, window_end_utc)`, and the enrollment's `streak_broken` is false. On the ride that completes the streak, the base payout is `streak_payout_cents`; if an `ACTIVE` `BONUS_ZONE` enrollment of the same driver covers the ride's cell, a zone boost is added equal to the floor of the base payout times `zone_multiplier_bps` minus 10000, divided by 10000. The raw total is then subject to stacking: if the same ride also advanced an `ACTIVE` enrollment in an `EXCLUSIVE`-class program, the `STACKABLE` streak payout is suppressed to zero — `EXCLUSIVE` wins. Otherwise the payout is the smaller of the raw total and the market's `budget_available_cents` at that moment, and that amount lands in the enrollment's `payout_cents`.

Zone bonuses on a `BONUS_ZONE` enrollment accumulate per qualifying ride: each `COMPLETED` ride whose `geo_cell_id` matches the zone's cell and whose `ride_type` is not excluded contributes the floor of its `base_fare_cents` times `zone_multiplier_bps` minus 10000, divided by 10000, added into `payout_cents`. The per-ride rounding order of §2.6 is binding here — each ride's bonus is floored to integer cents before accumulation, and computing the floor over summed fares is forbidden. Zone bonuses are not subject to the `EXCLUSIVE` suppression rule — only the one-shot streak and challenge payouts are — so a zone bonus accrues even on a ride whose other programs triggered suppression. A `CHALLENGE` pays its full `challenge_payout_cents` in one shot when the target is reached, subject to the same `EXCLUSIVE` suppression when the deciding ride also advanced an `EXCLUSIVE` enrollment; the challenge payout is not clamped to `budget_available_cents` the way the streak payout is — the ride-completion pipeline does not gate the challenge payout on remaining headroom (the activation-time forecast and the activation-time guarantee-reservation checks are the budget discipline for these instruments).

### 3.8. Weekly Guarantees: Compute, Finalize, Pay

The weekly guarantee is the most delicate instrument, because it compares a promise to a moving target. A `PaymentsOfficer` initiates settlement by computing a GuaranteeSettlement for a `driver_id`, a `program_id`, and a `week_start_utc` that is the Monday 00:00:00Z of the settled week. The program must be a `GUARANTEE` program — compute against any other type is refused with `ERR_PROGRAM_NOT_GUARANTEE` (HTTP 422) — and a `RESTRICTED` driver's settlements are blocked from finalization under the fraud gate. The newborn settlement is `DRAFT` under the `PROVISIONAL` basis variant: `promised_cents` snapshots the program's `guaranteed_weekly_cents`, `actual_gross_cents` sums `qualifying_earnings_cents` over the driver's `COMPLETED`, non-excluded rides whose completion week equals `week_start_utc` excluding any ride currently `UNDER_REVIEW` — where "non-excluded" means the ride's `ride_type` is not among the program's `excluded_ride_types`, so a ride whose type the program excludes contributes to neither `actual_gross_cents` nor `qualifying_ride_count` — `qualifying_ride_count` counts the rides that contributed, and `make_up_cents` is zero when `qualifying_ride_count` is below the program's `guaranteed_min_rides` and otherwise the larger of zero and `promised_cents` minus `actual_gross_cents`.

Finalization converts the settlement to the `FINAL` variant. It is permitted from `DRAFT` or `REOPENED`, requires every ride for the driver in the settled week to be in a terminal state — any week ride still `UNDER_REVIEW` blocks finalization with `ERR_SETTLEMENT_RIDES_PENDING` (HTTP 409) — and recomputes `make_up_cents` including rides whose review resolved back to `COMPLETED` while permanently excluding `VOIDED` ones, with the program's `excluded_ride_types` filter applied to the recomputed basis exactly as in the `PROVISIONAL` computation. Finalization writes the recomputed `promised_cents`, `actual_gross_cents`, `qualifying_ride_count`, and `make_up_cents` back onto the settlement in place — the recomputation is not merely a side-effect-free check. Payment is permitted from `FINALIZED` only, requires the market's `budget_available_cents` to cover `make_up_cents` (over-budget payments are refused with `ERR_BUDGET_EXCEEDED`), adds the make-up to the market's `budget_spent_cents`, sets `paid_at_utc`, and triggers recompute of the week's EarningsStatement `make_up_total_cents` and `total_cents`. Notably, paying a settlement does not release the GUARANTEE program's reservation — that release happens at week rollover or program retire.

A finalized settlement can be pulled back: reopening moves `FINALIZED` to `REOPENED`, restoring `PROVISIONAL` semantics until re-finalized. A ride flagged for fraud review after its week's settlement was finalized forces the same reopen cascade automatically, as §3.9 describes; the cascade flips the settlement's `basis_variant` back to `PROVISIONAL` to signal that the recorded figures no longer reflect the FINAL rules. Voiding is available from `DRAFT`, `FINALIZED`, or `REOPENED` — never from `PAID`, and attempting to reopen or void a `PAID` settlement is refused with `ERR_SETTLEMENT_ALREADY_PAID` — and a `VOID` settlement is excluded from all budget and statement aggregations.

### 3.9. Fraud: Flags, Scores, and the Review Loop

Fraud control runs on its own axis, independent of the rate-based posture of §3.2. A `FraudAnalyst` opens a FraudFlag by naming the flagged `driver_id`, the anchor `ride_id`, a `signal_type` of `INFLATED_RIDE`, `COLLUSION`, or `LOCATION_SPOOF`, an integer `severity` between 1 and 10 inclusive, and optionally a `ring_id` shared across driver accounts suspected of collusion (null for solo fraud). The flag is born `OPEN`, and the driver's `acute_score` and `chronic_score` are computed over the confirmed set; the freshly created flag itself carries the driver's current scores in its `acute_score` and `chronic_score` fields for audit.

The two score variants measure different things. The `acute_score` is the flat sum of `severity` across the driver's `CONFIRMED` flags — no decay. The `chronic_score` is a decay-weighted sum over the same confirmed set: each flag contributes the floor of its severity times 100 divided by two raised to the number of full four-week age buckets since the flag was confirmed, the intermediate divided by 100 — equivalently, each confirmed flag's severity halves per full four-week bucket of age. From these scores, `fraud_posture` is derived: `RESTRICTED` when `acute_score` is at least 10; otherwise `WATCH` when `acute_score` is at least 4 or `chronic_score` is at least 4; otherwise `CLEAR`.

Confirming a flag — permitted only from `OPEN`, and landing the flag in the terminal `CONFIRMED` state — recomputes the flagged driver's posture and, when the anchor ride is still `COMPLETED`, forces it to `UNDER_REVIEW`. When the confirmed flag carries a non-null `ring_id`, every other driver holding an `OPEN` or `CONFIRMED` flag sharing that `ring_id` also has their posture recomputed with a `WATCH` floor: their derived posture is computed from their own confirmed set per the rules above, and if that derivation leaves them at `CLEAR` they are forced up to `WATCH` (drivers already at `WATCH` or `RESTRICTED` are unchanged). When the recompute lands a driver at `RESTRICTED`, the cascade of §3.5 fires: the driver's `ACTIVE` enrollments are cancelled. Dismissing a flag — also only from `OPEN`, and landing the flag in the terminal `DISMISSED` state — simply recomputes the driver's posture.

The ride-level review loop is the analyst's other lever. Flagging a `COMPLETED` ride for review moves it to `UNDER_REVIEW`, which excludes it from `PROVISIONAL` guarantee basis and forces any `FINALIZED` settlement covering that driver and week into `REOPENED` (with `basis_variant` flipped back to `PROVISIONAL`). Clearing the review returns the ride to `COMPLETED` and re-includes it in the `FINAL` basis; clearing does not by itself re-finalize any settlement that was reopened. Voiding requires the ride to be `UNDER_REVIEW` and a `CONFIRMED` FraudFlag to exist whose `ride_id` is this ride; voiding zeroes the ride's `qualifying_earnings_cents`, claws back any zone-bonus payouts accrued from the ride on the driver's `ACTIVE` `BONUS_ZONE` enrollments whose `geo_cell_id` matches the ride's pickup cell and whose `excluded_ride_types` does not include the ride's `ride_type` — each enrollment's `payout_cents` is reduced by the per-ride bonus amount (floored at zero) and the market's `budget_spent_cents` is reduced by the total clawback (floored at zero) — and writes the total clawback as a negative adjustment on the driver's EarningsStatement for the ride's week. The driver's fraud posture is recomputed with the `RESTRICTED` cascade attached.

### 3.10. Statements, Appeals, and Dispute Resolution

At the end of the week, a `PaymentsOfficer` computes an EarningsStatement for a `driver_id` and `week_start_utc`. The statement aggregates `base_fares_cents` (the sum of `base_fare_cents` over the driver's `COMPLETED` rides that week), `tips_cents_total` (the same week's tips), `bonus_total_cents` (the sum of `payout_cents` over enrollments that completed that week), `make_up_total_cents` (the sum of `make_up_cents` over the driver's settlements paid that week), and `adjustments_cents` (the signed total of dispute adjustments applied through appeal resolution). The `total_cents` is the sum of those five components, and the invariant `total_cents` equals `base_fares_cents` plus `tips_cents_total` plus `bonus_total_cents` plus `make_up_total_cents` plus `adjustments_cents` is maintained on every mutation.

A statement is born `DRAFT` and becomes `PUBLISHED` only when every GuaranteeSettlement for the same driver and week is `PAID` or `VOID`; publishing while any week settlement sits in `DRAFT`, `FINALIZED`, or `REOPENED` is refused with `ERR_STATEMENT_SETTLEMENTS_OPEN` (HTTP 409). Publication is what the driver sees, and it is what they can dispute.

Appeals are the structured dispute channel, and they come in two subjects. A Driver files an appeal with their own `driver_id`, a `subject_type` of `ELIGIBILITY` or `STATEMENT`, and a free-text `reason`. A `STATEMENT` appeal must carry a `statement_id` referencing one of the driver's own statements — a statement belonging to a different driver is refused as `ERR_CROSS_MARKET_REFERENCE` — and filing it moves that statement from `PUBLISHED` to `DISPUTED`; an `ELIGIBILITY` appeal carries no `statement_id`. The appeal is born `FILED` with `round_count` zero.

Review proceeds under the `PaymentsOfficer`. Starting review moves `FILED` to `UNDER_REVIEW`. Requesting more information moves `UNDER_REVIEW` to `MORE_INFO`, and is available only while `round_count` is below 2 — requesting a third round is refused with `ERR_APPEAL_ROUNDS_EXHAUSTED` (HTTP 422). The driver responds by providing the requested information, which returns the appeal to `UNDER_REVIEW` and increments `round_count`; only the appeal's own driver may provide information, and an acting `X-User-ID` that does not match the appeal's `driver_id` is refused with `ERR_APPEAL_IDENTITY_MISMATCH` (HTTP 403). Resolution from `UNDER_REVIEW` (or `ESCALATED`, see below) takes an `outcome` of `UPHELD` or `OVERTURNED` and lands the appeal in the corresponding terminal state `RESOLVED_UPHELD` or `RESOLVED_OVERTURNED`. Upholding a `STATEMENT` appeal returns the statement to `PUBLISHED` unchanged. Overturning a `STATEMENT` appeal requires a non-zero `adjustment_cents` to be supplied — its absence (or a zero value) is refused with `ERR_APPEAL_ADJUSTMENT_REQUIRED` (HTTP 400) — and moves the statement to `AMENDED` with the signed adjustment added into `adjustments_cents` and `total_cents` recomputed under the invariant. Overturning an `ELIGIBILITY` appeal resets the driver's `rate_posture` to `ELIGIBLE`, zeroes the rolling counters (`offers_total`, `accepted_total`, `cancelled_total`), resets `acceptance_rate_bps` to its empty-window default of 10000 and `cancellation_rate_bps` to its empty-window default of 0, and clears the rolling event history — a logged manual override; it does not undo the INELIGIBLE cascade's effect on enrollments (enrollments already cancelled stay `CANCELLED`).

When both information rounds have been consumed — `round_count` exactly 2 — the `PaymentsOfficer` may escalate, moving `UNDER_REVIEW` to `ESCALATED`; escalating earlier is refused with `ERR_APPEAL_NOT_ESCALATABLE`. An escalated appeal can only be resolved by a `PlatformAdmin`, with the same `UPHELD` and `OVERTURNED` outcomes and the same side effects as the officer's resolution. At any point before resolution — from `FILED`, `UNDER_REVIEW`, or `MORE_INFO` — the driver may withdraw, moving the appeal to `WITHDRAWN`; withdrawal is likewise restricted to the appeal's own driver under `ERR_APPEAL_IDENTITY_MISMATCH`, and withdrawing a `STATEMENT` appeal whose statement is `DISPUTED` returns the statement to `PUBLISHED` with no monetary change.

### 3.11. Supply Shortfalls and Targeting

The final workflow closes the loop from observed scarcity to incentive design. An `IncentiveOps` operator declares a SupplyShortfall by naming a `market_id`, a `geo_cell_id` within that market's cells, an `hour_bucket` between 0 and 167 inclusive identifying the hour-of-week the shortage applies to, and a `severity_bps` between 1 and 10000 inclusive expressing the magnitude of unmet demand in basis points. A `geo_cell_id` outside the market's `geo_cells` is refused with `ERR_GEO_CELL_UNKNOWN`. Creation computes a `recommended_bonus_cents` suggestion: the market's median `base_fare_cents` over `COMPLETED` rides in the cell across the prior four weeks (zero when no history exists) is multiplied by `severity_bps` and divided by 10000, with the result rounded up to the next integer cent. When the ride set has an even number of fares the median is the floor of the average of the two middle fares. At the boundary, a `severity_bps` of exactly 10000 doubles the median fare exactly.

A shortfall is born `OPEN`. The operator may mark it `ADDRESSED` once an incentive has been stood up to cover it, and the program-retire cascade of §3.3 marks linked shortfalls `ADDRESSED` automatically. When the logical clock rolls past the shortfall's hour bucket in the following week, the shortfall expires to `EXPIRED` under the lazy-evaluation rule of §2.5 — concretely, the expiry instant is the Monday 00:00:00Z of the week containing the market's `created_at`, plus one week, plus the shortfall's `hour_bucket` hours; the market close cascade also expires every `OPEN` shortfall in the market.

## 4. Endpoint Definitions

Operations that create a new resource — a market, a driver, a program, a ride, an enrollment, a forecast, a settlement, a statement, an appeal, a fraud flag, or a shortfall — return `201 Created` with the new resource in the response's `data`. Operations that modify an existing resource, including all state-transition actions, return `200 OK` with the updated resource. Readers must consult §3 for the request and response semantics attached to each operation; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/markets` | Create a market | PlatformAdmin |
| GET | `/markets/{id}` | Get a market | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| GET | `/markets` | List markets | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst |
| PUT | `/markets/{id}` | Update market budget (OCC) | PlatformAdmin |
| POST | `/markets/{id}/freeze` | Freeze market (pause programs) | PlatformAdmin |
| POST | `/markets/{id}/unfreeze` | Unfreeze market | PlatformAdmin |
| POST | `/markets/{id}/close` | Close market | PlatformAdmin |
| GET | `/markets/{id}/supply-shortfalls` | List shortfalls in market | PlatformAdmin, IncentiveOps |
| POST | `/drivers` | Onboard a driver | IncentiveOps |
| GET | `/drivers/{id}` | Get a driver | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| GET | `/drivers` | List drivers | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst |
| POST | `/drivers/{id}/rate-events` | Record dispatch rate events and recompute posture | IncentiveOps |
| POST | `/drivers/{id}/deactivate` | Deactivate driver | PlatformAdmin |
| GET | `/drivers/{id}/enrollments` | List driver enrollments | PlatformAdmin, IncentiveOps, PaymentsOfficer, Driver |
| GET | `/drivers/{id}/rides` | List driver rides | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| GET | `/drivers/{id}/settlements` | List driver guarantee settlements | PlatformAdmin, PaymentsOfficer, Driver |
| GET | `/drivers/{id}/statements` | List driver earnings statements | PlatformAdmin, PaymentsOfficer, Driver |
| POST | `/incentive-programs` | Create an incentive program | IncentiveOps |
| GET | `/incentive-programs/{id}` | Get a program | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| GET | `/incentive-programs` | List programs | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| POST | `/incentive-programs/{id}/activate` | Activate program | IncentiveOps |
| POST | `/incentive-programs/{id}/pause` | Pause program | IncentiveOps |
| POST | `/incentive-programs/{id}/resume` | Resume paused program | IncentiveOps |
| POST | `/incentive-programs/{id}/retire` | Retire program | IncentiveOps |
| GET | `/incentive-programs/{id}/enrollments` | List program enrollments | PlatformAdmin, IncentiveOps, PaymentsOfficer |
| GET | `/incentive-programs/{id}/cost-forecasts` | List program cost forecasts | PlatformAdmin, IncentiveOps |
| POST | `/incentive-programs/{id}/cost-forecasts` | Create a cost forecast | IncentiveOps |
| POST | `/cost-forecasts/{id}/approve` | Approve forecast (OCC on program version) | IncentiveOps |
| POST | `/cost-forecasts/{id}/reject` | Reject draft forecast | IncentiveOps |
| POST | `/incentive-programs/{id}/enrollments` | Enroll a driver in a program | IncentiveOps |
| GET | `/enrollments/{id}` | Get an enrollment | PlatformAdmin, IncentiveOps, PaymentsOfficer, Driver |
| POST | `/enrollments/{id}/cancel` | Cancel an active enrollment | IncentiveOps, Driver |
| POST | `/rides` | Record a ride offer | Driver |
| POST | `/rides/{id}/accept` | Accept offered ride | Driver |
| POST | `/rides/{id}/decline` | Decline offered ride | Driver |
| POST | `/rides/{id}/complete` | Complete accepted ride | Driver |
| POST | `/rides/{id}/cancel` | Cancel accepted ride | Driver |
| POST | `/rides/{id}/flag-review` | Flag a completed ride for fraud review | FraudAnalyst |
| POST | `/rides/{id}/clear-review` | Clear ride back to completed | FraudAnalyst |
| POST | `/rides/{id}/void` | Void a ride confirmed fraudulent | FraudAnalyst |
| GET | `/rides/{id}` | Get a ride | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst, Driver |
| GET | `/rides` | List rides | PlatformAdmin, IncentiveOps, PaymentsOfficer, FraudAnalyst |
| POST | `/fraud-flags` | Open a fraud flag | FraudAnalyst |
| GET | `/fraud-flags/{id}` | Get a fraud flag | PlatformAdmin, FraudAnalyst |
| GET | `/fraud-flags` | List fraud flags | PlatformAdmin, FraudAnalyst |
| POST | `/fraud-flags/{id}/confirm` | Confirm a fraud flag | FraudAnalyst |
| POST | `/fraud-flags/{id}/dismiss` | Dismiss a fraud flag | FraudAnalyst |
| POST | `/settlements/compute` | Compute (create DRAFT) a guarantee settlement | PaymentsOfficer |
| GET | `/settlements/{id}` | Get a settlement | PlatformAdmin, PaymentsOfficer, Driver |
| GET | `/settlements` | List settlements | PlatformAdmin, PaymentsOfficer |
| POST | `/settlements/{id}/finalize` | Finalize settlement (FINAL variant) | PaymentsOfficer |
| POST | `/settlements/{id}/pay` | Pay make-up amount | PaymentsOfficer |
| POST | `/settlements/{id}/reopen` | Reopen a finalized settlement | PaymentsOfficer |
| POST | `/settlements/{id}/void` | Void an unpaid settlement | PaymentsOfficer |
| POST | `/statements/compute` | Compute (create DRAFT) an earnings statement | PaymentsOfficer |
| GET | `/statements/{id}` | Get a statement | PlatformAdmin, PaymentsOfficer, Driver |
| GET | `/statements` | List statements | PlatformAdmin, PaymentsOfficer |
| POST | `/statements/{id}/publish` | Publish statement | PaymentsOfficer |
| POST | `/appeals` | File an appeal | Driver |
| GET | `/appeals/{id}` | Get an appeal | PlatformAdmin, PaymentsOfficer, Driver |
| GET | `/appeals` | List appeals | PlatformAdmin, PaymentsOfficer |
| POST | `/appeals/{id}/start-review` | Start reviewing an appeal | PaymentsOfficer |
| POST | `/appeals/{id}/request-info` | Request more info from driver | PaymentsOfficer |
| POST | `/appeals/{id}/provide-info` | Driver provides requested info | Driver |
| POST | `/appeals/{id}/resolve` | Resolve appeal (UPHELD or OVERTURNED) | PaymentsOfficer, PlatformAdmin |
| POST | `/appeals/{id}/escalate` | Escalate after both info rounds exhausted | PaymentsOfficer |
| POST | `/appeals/{id}/withdraw` | Driver withdraws appeal | Driver |
| POST | `/supply-shortfalls` | Declare a supply shortfall | IncentiveOps |
| GET | `/supply-shortfalls/{id}` | Get a shortfall | PlatformAdmin, IncentiveOps |
| POST | `/supply-shortfalls/{id}/address` | Mark a shortfall addressed | IncentiveOps |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MARKET_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_CONFIG_INCOMPLETE` | 400 Bad Request |
| `ERR_PROGRAM_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CROSS_MARKET_REFERENCE` | 422 Unprocessable Entity |
| `ERR_DRIVER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_FRAUD_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_RIDE_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_RIDE_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SETTLEMENT_RIDES_PENDING` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_PAID` | 409 Conflict |
| `ERR_STATEMENT_SETTLEMENTS_OPEN` | 409 Conflict |
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_APPEAL_NOT_ESCALATABLE` | 422 Unprocessable Entity |
| `ERR_APPEAL_ADJUSTMENT_REQUIRED` | 400 Bad Request |
| `ERR_APPEAL_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_FORECAST_NOT_DRAFT` | 409 Conflict |
| `ERR_ENROLLMENT_DUPLICATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_GUARANTEE` | 422 Unprocessable Entity |
| `ERR_GEO_CELL_UNKNOWN` | 422 Unprocessable Entity |
