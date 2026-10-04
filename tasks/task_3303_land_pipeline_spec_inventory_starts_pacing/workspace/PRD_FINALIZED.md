# Land Pipeline Spec Pacing API — Product Requirements Document

## 1. Introduction

National homebuilders carry a structural tension: growth demands land, but raw land on the balance sheet destroys return on equity. The dominant answer in the industry is the option-contract pipeline — the builder secures the right, but not the obligation, to purchase finished lots from a land developer on a scheduled takedown cadence, paying a non-refundable option fee and earnest money up front and drawing lots down community by community as sales absorption justifies. That pipeline only works if the rest of the operating machine is synchronized: communities must be planned with product series positioned across price points, speculative homes must be started before a buyer is identified, starts must be paced against sales absorption, construction cycle time, and trade-partner framing capacity, and standing inventory must be worked down with price cuts, closing cost credits, and rate buydowns before it ages into a write-off.

This document specifies the API that supports that operating machine end to end. It covers land parcels and the option contracts written against them, scheduled takedowns that release lots into communities under escalation and tiered developer-credit pricing, community lifecycle from planning through close-out, product series price bands, speculative home starts gated by a three-way constraint of trade capacity, pacing quota, and inventory allowance, completion-stage pricing that ratchets as a home moves through build stages, incentive programs whose value stacks under a community-phase-dependent cap, sales contracts from pending through closing, trade partner capacity commitments, and the pacing plans that authorize starts per period. A single logical clock drives every time-dependent behavior in the system — takedown windows, escalation quarters, incentive activation windows, absorption trailing windows, and lazy defaulting of expired takedowns — so that the entire pipeline is deterministic and testable.

The audience is the engineering team implementing the service. The document is organized as global cross-cutting principles first, then business workflows told as narrative, then the endpoint and error catalogues. Where a rule is stated once, it is authoritative; where it is reinforced from a different angle later, the statements are consistent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing the `X-User-Role` header, or carrying a role value outside the enumerated set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other check runs.

Five roles exist, spelled exactly as follows:

- `DIVISION_PRESIDENT` — division executive. Owns community creation, phase advancement, pacing plan publication, trade partner creation, and the logical clock. When `X-User-Role` is `DIVISION_PRESIDENT`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `LAND_MANAGER` — land acquisition manager. Owns land parcels, option contracts, and takedowns. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `COMMUNITY_MANAGER` — community operator. Opens communities, defines product series, starts homes, deploys and cancels incentives, advances build stages, and approves and closes sales contracts. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `SALES_AGENT` — sales agent. Creates, renegotiates, and terminates sales contracts. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `TRADE_PARTNER` — trade contractor. When `X-User-Role` is `TRADE_PARTNER`, `X-User-ID` is the `id` of the acting `TradePartner`; the partner may only create capacity commitments under its own trade-partner path and may only reduce its own commitments. A `TRADE_PARTNER` acting on another partner's resources — where the path's trade-partner id does not equal `X-User-ID`, or the targeted commitment belongs to a different partner — is rejected with `ERR_FORBIDDEN` (HTTP 403).

A request whose role is authenticated but not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403). All five roles may invoke every read endpoint.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`. Every list is sorted by `created_at` ascending unless stated otherwise.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries an `id` minted by the server as a bare UUID with no type prefix, plus a `created_at` timestamp. All entities additionally carry `updated_at` and an integer `version`; there are no exceptions in this domain. Timestamps are ISO 8601 UTC with three fractional digits. Both `created_at` and `updated_at` are stamped from the logical clock described below, never from wall time, so every timestamp in the system moves only when the logical clock moves. `version` starts at 1 on creation and increments by exactly 1 on every mutation of that row; `updated_at` refreshes on the same mutations.

Time inside the system is not wall time. A single logical clock governs every temporal rule — takedown windows, escalation quarters, incentive windows, trailing absorption windows, and lazy defaulting. The clock starts at 2026-09-01T00:00:00Z when the server boots and never falls back to wall time. An admin-only test-driving capability available to the `DIVISION_PRESIDENT` sets the clock to a supplied `to_iso8601` instant; after the clock moves, incentive statuses recompute for the new instant and absorption windows recompute. Notably, setting the clock does not, by itself, default expired takedowns — defaulting is applied lazily on reads and execute attempts, as described in §3.2.

### 2.5. Nested Resources and Path Validation

Several resources are addressed through their parent — a takedown under its option contract, a product series, lot list, home, incentive, or pacing plan under its community, a capacity commitment under its trade partner. Path resource identifiers are validated left to right: the server first confirms the leftmost id exists, then the next, and so on. The first id that does not exist produces `ERR_NOT_FOUND` (HTTP 404). A nested create that targets an existing parent inherits its ownership — for example a takedown's `option_contract_id`, a home's `community_id`, a capacity commitment's `trade_partner_id` — is set from the path, not from the request body.

### 2.6. Idempotency of Creates and Actions

Every POST request must carry an `Idempotency-Key` header; a POST without one is rejected with `ERR_MISSING_IDEMPOTENCY_KEY` (HTTP 400). Re-sending a POST with the same `Idempotency-Key` and an identical request body returns the original result without re-executing side effects. Reusing the same key with a different request body is rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409).

### 2.7. Optimistic Concurrency Control

Two write endpoints guard against stale views of their parent aggregate through an expected-version field. All other endpoints take no version field.

Creating a pacing plan for a community requires the request to carry `expected_community_version` holding the community's current `version` as the client last observed it. If the community's version has advanced since — because counters moved, a phase changed, or another plan was published — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because publishing a new plan legitimately supersedes the currently published one, and a stale view of the community's pacing inputs must not silently fork the plan sequence.

Scheduling a takedown under an option contract requires the request to carry `expected_contract_version` holding the contract's current `version`. Execution and prior scheduling advance the contract's version as lots are drawn down, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) to prevent oversubscribing the remaining lots from a stale view.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integer cents; no field carries fractional cents. Wherever a computation produces a fractional cent — escalation, tiered credits, rate buydowns, stacking caps — the value is rounded half-up to the nearest integer cent at the pinned step where the scaffold of the calculation says rounding occurs, and not before or after. Incentive stacking has a pinned order with a deliberately rejected alternative: each incentive's component is rounded to integer cents individually first, then the already-rounded components are summed, then the cap (itself rounded half-up to integer cents) is applied. Summing unrounded components and rounding once at the end is the rejected alternative; it can differ by cents when two rate-buydown components are fractional. Rates used in absorption math are kept exact (rational), and months-of-supply is compared exactly at its thresholds. Cycle time is whole days by floor; the community average cycle time is reported rounded half-up to two decimal places.

### 2.9. Validation Priority Ordering

When a single request could fail more than one check, failures surface in a fixed priority order so the same request always yields the same error:

1. Authentication — the `X-User-Role` header is present and valid (`ERR_UNAUTHENTICATED`).
2. Idempotency key presence on POST (`ERR_MISSING_IDEMPOTENCY_KEY`).
3. Idempotency replay consistency (`ERR_IDEMPOTENCY_REPLAY_MISMATCH`).
4. Path resource existence, left to right (`ERR_NOT_FOUND`).
5. Role authorization, including the trade-partner self-scope (`ERR_FORBIDDEN`).
6. The target resource's own state or phase permits the operation (`ERR_INVALID_STATE`, `ERR_COMMUNITY_NOT_OPEN`, `ERR_INVALID_PHASE_TRANSITION`, `ERR_HOME_NOT_COMPLETE`).
7. Business-referential preconditions on linked entities — the lot is `BANKED` (`ERR_LOT_NOT_AVAILABLE`), the home is `UNSOLD` (`ERR_HOME_NOT_UNSOLD`), the contract is `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), a `PUBLISHED` pacing plan covering the clock exists (`ERR_NO_PUBLISHED_PACING_PLAN`).
8. Business-temporal window checks — takedown window not yet open (`ERR_TAKEDOWN_WINDOW_NOT_OPEN`) or expired (`ERR_TAKEDOWN_WINDOW_EXPIRED`), incentive window conflicts (`ERR_INCENTIVE_WINDOW_CONFLICT`), capacity period overlap (`ERR_CAPACITY_PERIOD_OVERLAP`).
9. Business-constraint checks — product series band overlap (`ERR_SERIES_BAND_OVERLAP`) and gross price within the series band (`ERR_PRICE_OUT_OF_SERIES_BAND`).
10. Business-fiscal checks — the overheld posture block (`ERR_STARTS_BLOCKED_OVERHELD`), pacing quota (`ERR_STARTS_QUOTA_EXCEEDED`), framing capacity (`ERR_NO_CAPACITY_REMAINING`), commitment reduction below allocation (`ERR_CAPACITY_BELOW_ALLOCATED`), the contract price floor (`ERR_PRICE_BELOW_NET_FLOOR`), and lot exhaustion (`ERR_CONTRACT_EXHAUSTED`).

Within a priority tier, the specific failing rule determines the returned error id. A malformed payload — a missing required field, an invalid enum value, or a mistyped value — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.10. Community Posture as a Computed Gate

A community's posture is a computed signal, never stored as input, and it gates real behavior. The posture is `OVERHELD` when months of supply reaches 4.0 or more, `STARVED` when months of supply is below 1.5, and `NORMAL` otherwise. Months of supply is the standing speculative count divided by the effective absorption rate, where the effective absorption rate is the trailing absorption rate or a floor of 1.0, whichever is larger — the floor prevents division blow-ups in young communities. Posture feeds three behaviors: an `OVERHELD` community cannot start homes at all, a `STARVED` community always retains an inventory allowance of at least one start, and the flip into `OVERHELD` can wake dormant incentives flagged for auto-activation. The formulas and cascades appear in §3.4 and §3.6.

## 3. Business Logic & Workflows

### 3.1. Securing the Land: Parcels and Option Contracts

Land enters the system when a `LAND_MANAGER` registers a land parcel with its `name`, `market_code` (a market identifier such as DFW), and gross `acres`. Parcels are inert reference data — they carry no state machine of their own.

Against a parcel, the land manager writes an option contract by naming the `land_parcel_id` and posting the commercial terms: the non-refundable `option_fee_cents` paid at execution, the `earnest_money_cents` deposit held against takedowns, the `total_lots` contracted across all takedowns, and the `lot_base_price_cents` per lot before escalation. A new contract is born in `DRAFT` with `lots_taken_down` at zero and `executed_at` null.

Executing the contract — an action reserved to the `LAND_MANAGER` — flips it from `DRAFT` to `ACTIVE`, stamps `executed_at` with the current logical clock, and increments the contract's `version` by 1. Attempting execution on a contract that is not in `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409). Only an `ACTIVE` contract supports takedowns.

Contracts can also be listed, optionally filtered by `land_parcel_id` or by `state`.

### 3.2. Drawing Lots Down: Takedown Scheduling, Windows, and Default

Under an `ACTIVE` contract, the land manager schedules takedowns. Each takedown names the `community_id` that will receive the released lots, the `lot_count` being released, and a closed execution window from `window_start` (inclusive) through `window_end` (inclusive). The create carries `expected_contract_version` per the OCC rule in §2.7; the new takedown is born `SCHEDULED`, and scheduling it increments the owning contract's `version` by 1. Takedowns can be listed per contract (optionally filtered by `community_id`) or globally with optional `community_id`, `option_contract_id`, and `state` filters.

Executing a scheduled takedown is the moment money and lots move. Five preconditions guard it, and their priority ordering matters: the takedown must be `SCHEDULED` (else `ERR_INVALID_STATE`); the contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`, a business-referential check at priority 7); the clock must have reached `window_start` (else `ERR_TAKEDOWN_WINDOW_NOT_OPEN`, priority 8); the clock must not have passed `window_end` — and if it has, the takedown flips to `DEFAULTED` as a side effect of the attempt and the call returns `ERR_TAKEDOWN_WINDOW_EXPIRED`; finally the contract must have enough lots left, meaning the contract's `lots_taken_down` plus this `lot_count` must not exceed `total_lots` (else `ERR_CONTRACT_EXHAUSTED`, a business-fiscal check at priority 10).

Two orderings pin down how those preconditions interact with the lazy defaulting below. The contract-`ACTIVE` precondition is evaluated against the contract's state as observed on entry to the attempt, before the attempt itself performs any lazy defaulting: an execute attempt that arrives after `window_end` on a still-`SCHEDULED` takedown whose contract has not previously been observed defaulted therefore returns `ERR_TAKEDOWN_WINDOW_EXPIRED` — flipping the takedown and, per the cascade, its contract to `DEFAULTED` as side effects — rather than `ERR_CONTRACT_NOT_ACTIVE`, while an attempt whose contract was already `DEFAULTED` on entry (because an earlier observation applied the cascade) returns `ERR_CONTRACT_NOT_ACTIVE` and leaves the expired takedown untouched. Conversely, once the attempt's own takedown is known to be `SCHEDULED` and inside its window, the attempt applies lazy defaulting to any *other* expired takedowns before the lot-exhaustion check, so an in-window execute on a contract carrying a sibling expired takedown fails with `ERR_CONTRACT_NOT_ACTIVE`.

A successful execution stamps `executed_at`, runs the takedown pricing described in §3.3, creates `lot_count` lots in the target community each in state `BANKED`, every lot recording the executing takedown's id as its `source_takedown_id` for provenance, adds `lot_count` to the contract's `lots_taken_down`, increments the contract's `version`, and — when the running total reaches `total_lots` — flips the contract to `EXHAUSTED`, its terminal state.

Default is lazy, and this is deliberate. A `SCHEDULED` takedown whose `window_end` has passed flips to `DEFAULTED` when the system observes it — on a read of the takedown itself, on a read of its contract or the contract's takedown list, or on a takedown execute attempt (per the ordering pinned above) — but not merely because the clock was set past the window. When a takedown defaults, its owning contract cascades from `ACTIVE` to `DEFAULTED` on the same lazy observation. The cascade is stateless: it fires on every lazy observation that finds the contract `ACTIVE` while any of its takedowns is `DEFAULTED`, with no memory of past cures.

A defaulted contract is not dead. The land manager can cure it, which charges the `cure_fee_cents` — computed as the contract's `option_fee_cents` times ten percent, rounded half-up to integer cents — and returns the contract from `DEFAULTED` to `ACTIVE`, incrementing its `version` by 1, even though some of its takedowns remain `DEFAULTED`. Because the cascade above is stateless, that reprieve lasts only until the next lazy observation: as long as any of the contract's takedowns remains `DEFAULTED`, the next read or execute attempt that applies lazy defaulting flips the contract back to `DEFAULTED`, so curing does not by itself re-enable execution of the contract's remaining in-window takedowns. Curing a contract that is not in `DEFAULTED` is rejected with `ERR_INVALID_STATE`. Note the asymmetry: a contract in `EXHAUSTED` is terminal and cannot be cured, and a contract only reaches `EXHAUSTED` from `ACTIVE` when an execution brings `lots_taken_down` exactly to `total_lots`.

### 3.3. Takedown Pricing: Escalation and the Cumulative-Lot Credit

Takedown pricing runs once, at execution, and writes four computed fields onto the takedown: `escalated_lot_price_cents`, `credit_per_lot_cents`, `net_due_per_lot_cents`, and `total_net_due_cents`. All four are null until the takedown reaches `EXECUTED`. The evaluation order is pinned to resolve what would otherwise look like a circular tier dependency:

1. Count the full elapsed quarters between the contract's `executed_at` and this takedown's execution instant: take the whole days between the two timestamps and divide by 91 (the quarter length in days), discarding any fractional quarter.
2. Escalate the per-lot price: the escalated price is the contract's `lot_base_price_cents` plus the base price times one percent times the number of full quarters, with that increment rounded half-up to integer cents before being added.
3. Compute cumulative lots **including this takedown**: the contract's `lots_taken_down` before this execution plus this takedown's `lot_count`.
4. Determine the developer credit percentage from the cumulative total: zero percent when cumulative lots are fewer than 20, two percent when cumulative lots are at least 20 but fewer than 40, and three percent when cumulative lots reach 40 or more.
5. The `credit_per_lot_cents` is that percentage times the escalated per-lot price, rounded half-up to integer cents.
6. The `net_due_per_lot_cents` is the escalated price minus the per-lot credit.
7. The `total_net_due_cents` is the net per-lot amount times this takedown's `lot_count`.

Because the cumulative count includes the executing takedown, a single large takedown can push a contract across a tier boundary and earn the higher credit on every lot in that takedown.

### 3.4. Community Lifecycle and Phase-Gated Pricing

A `DIVISION_PRESIDENT` creates a community with its `name`, `market_code`, the planned `absorption_target_per_month`, and the `months_supply_target` for standing spec inventory. A community is born with its `phase` in `PLANNING` and all counters at zero: `standing_spec_count`, `starts_this_period`, and `lifetime_closed_sales` all start at 0.

The community walks a one-way phase ladder. Opening the community — a `COMMUNITY_MANAGER` action — moves it from `PLANNING` to `OPEN_FOR_SALES` and increments the community's `version` by 1; opening a community that is not in `PLANNING` is rejected with `ERR_INVALID_STATE`. From there, a `DIVISION_PRESIDENT` advances the phase one step at a time: `OPEN_FOR_SALES` to `SELLING_OUT`, `SELLING_OUT` to `CLOSE_OUT`, and `CLOSE_OUT` to `CLOSED`. Each advance increments the community's `version` by 1. Skipping a rung — `PLANNING` straight to `CLOSED`, for instance — or advancing from `CLOSED` is rejected with `ERR_INVALID_PHASE_TRANSITION` (HTTP 409).

The phase transition into `CLOSE_OUT` has a pricing side effect: the incentive stacking cap rises from six percent of adjusted price to ten percent, and every applicable home's stacked incentive and net effective price are recomputed under the new cap. The cap values by phase are: `PLANNING` 0.06, `OPEN_FOR_SALES` 0.06, `SELLING_OUT` 0.06, `CLOSE_OUT` 0.10, `CLOSED` 0.10.

### 3.5. Product Series and Price Bands

Within a community, the `COMMUNITY_MANAGER` defines product series — the price-point ladder that lets one market carry an entry-level and a move-up offering side by side. A series is created with a `series_code` of `EXPRESS`, `CLASSIC`, `VENTURE`, or `FREEDOM`, and an inclusive price band from `min_price_cents` to `max_price_cents`. Bands may not overlap: a new series whose band intersects an existing series' band in the same community is rejected with `ERR_SERIES_BAND_OVERLAP` (HTTP 422). The band is enforced again at home-start time: a home whose gross price falls outside its series' band is rejected with `ERR_PRICE_OUT_OF_SERIES_BAND` (HTTP 422). Series can be read back individually or listed per community.

### 3.6. Starting Spec Homes: The Three-Way Gate

Starting a speculative home is the most heavily guarded write in the system, because a start consumes a scarce lot, scarce framing capacity, and scarce pacing quota all at once. A `COMMUNITY_MANAGER` starts a home in a community by naming the `lot_id` of the homesite, the `product_series_id` positioning the price point, the `base_price_cents`, and optionally `lot_premium_cents` (which defaults to 0). The request is checked in the global priority order of §2.9; the business narrative of each gate is:

- The community's phase must be `OPEN_FOR_SALES` or `SELLING_OUT`; starting in `PLANNING`, `CLOSE_OUT`, or `CLOSED` is rejected with `ERR_COMMUNITY_NOT_OPEN` (HTTP 409).
- The named lot must belong to the community and be `BANKED`; otherwise `ERR_LOT_NOT_AVAILABLE`.
- A `PUBLISHED` pacing plan covering the current clock must exist; otherwise `ERR_NO_PUBLISHED_PACING_PLAN`.
- The community's posture must not be `OVERHELD`; an overheld community is blocked from starting outright with `ERR_STARTS_BLOCKED_OVERHELD`. This fiscal-tier check means a request can pass every referential and temporal gate and still be refused because the standing inventory has grown too deep relative to absorption.
- The pacing quota must have room: quota remaining is the published plan's `max_starts` minus the community's `starts_this_period`, floored at zero; when quota remaining is zero the start is rejected with `ERR_STARTS_QUOTA_EXCEEDED`.
- Framing capacity must have room. The eligible capacity pool is the set of capacity commitments whose trade partner's `trade` is `FRAMING`, whose `community_id` is this community, whose period covers the clock as a half-open interval (start inclusive, end exclusive), and whose `remaining_units` is greater than zero. From that pool the commitment with the earliest `period_start` is selected, with ties broken by earliest `created_at`. If the pool is empty — no eligible commitment, or all eligible commitments fully allocated — the start is rejected with `ERR_NO_CAPACITY_REMAINING`.

A home that clears all six gates is created with `build_stage` `PERMITTED` and `sales_status` `UNSOLD`, and its arrival cascades: the lot flips from `BANKED` to `CONSUMED`, the community's `standing_spec_count` increases by 1, `starts_this_period` increases by 1, the selected framing commitment's `allocated_units` increases by 1 (and its `remaining_units` decreases by 1, preserving the invariant that `committed_units` always equals allocated plus remaining), the community's posture is recomputed, and the community's `version` increments by 1.

Two derived community counters tell the pacing story at a glance. `max_starts_remaining` is the minimum of three quantities — the selected framing commitment's `remaining_units` (zero when no eligible commitment exists), the quota remaining (zero when no `PUBLISHED` plan covers the clock), and the inventory allowance. The inventory allowance is the target spec depth minus what is already standing: the effective absorption rate times the community's `months_supply_target`, rounded up to a whole number, minus `standing_spec_count`, floored at zero — except that a `STARVED` community always keeps an allowance of at least 1. When `max_starts_remaining` is zero, `starts_halted` is true. These two values are exposed on the community and in the pacing summary so a division can see the constraint that is actually binding.

The authorization rule is also recomputed live for the pacing summary, so a reader sees the same gate a start would face.

### 3.7. Building the Home: Stage Advance, Completion-Stage Pricing, and Cycle Time

A home carries two independent state dimensions on one row: `build_stage` tracks construction (`PERMITTED`, `FOUNDATION`, `FRAME`, `DRYWALL`, `COMPLETE`, `CLOSED`) and `sales_status` tracks the commercial side (`UNSOLD`, `RESERVED`, `SOLD`, `CLOSED_SALE`). They evolve independently — a home can be framed while unsold, or complete and merely reserved.

A `COMMUNITY_MANAGER` advances the build one stage at a time: `PERMITTED` to `FOUNDATION`, `FOUNDATION` to `FRAME`, `FRAME` to `DRYWALL`, and `DRYWALL` to `COMPLETE`. Each advance requires the home to currently sit in the expected prior stage (otherwise `ERR_INVALID_STATE`), and each advance recomputes the home's pricing, because the price ratchets with construction progress. The advance into `COMPLETE` is special: it stamps `completed_at` with the clock, computes `cycle_time_days` as the whole days from the home's `created_at` to `completed_at` (fractional days discarded), releases the framing allocation back to the commitment that funded the start — `allocated_units` decreases by 1 and `remaining_units` increases by 1 on that same commitment — and recomputes pricing.

Home pricing is a two-variant calculation over the same base. The `gross_price_cents` is the `base_price_cents` plus the `lot_premium_cents`. A stage multiplier is then applied: 1.00 while `PERMITTED`, 1.00 at `FOUNDATION`, 1.01 at `FRAME`, 1.02 at `DRYWALL`, and 1.03 at both `COMPLETE` and `CLOSED` — the multiplier is read from the home's current `build_stage`, so a mid-build price increase happens automatically as stages advance. The `adjusted_price_cents` — the list-price variant, gross of incentives — is the gross price times the stage multiplier, rounded half-up to integer cents. The `net_effective_price_cents` is the adjusted price minus the `stacked_incentive_cents` described in §3.8; it is the variant used as the approval price floor, and it diverges from the list variant whenever any applicable incentive is active. The computed pricing fields are stored on the home and recomputed on every write that touches the home's pricing inputs (stage advance, incentive create or cancel, phase advance into `CLOSE_OUT`, approval, closing, and the termination cascade); in addition, reading a home through `GET /homes/{id}` or listing homes through `GET /homes` recomputes each returned home's pricing snapshot from the current logical clock before responding, so clock-driven incentive activations and expiries — which moving the clock does not by itself write back — are reflected on those reads. Homes can be read individually (with computed pricing) or listed with optional `lot_id`, `community_id`, `product_series_id`, and `sales_status` filters.

The community also reports `avg_cycle_time_days` — the mean of `cycle_time_days` across its homes whose `build_stage` is `COMPLETE` or `CLOSED`, rounded half-up to two decimal places — as part of the pacing summary.

### 3.8. Incentives on Standing Inventory

When spec homes stand unsold, the `COMMUNITY_MANAGER` deploys incentives against the community. An incentive is created with a `type` of `PRICE_CUT`, `CLOSING_COST_CREDIT`, or `RATE_BUYDOWN`; an effective window from `window_start` (inclusive) to `window_end` (inclusive — a closed interval); an optional `series_code` restricting it to one series (null means it applies to all series); and an optional `auto_activate_on_overheld` flag defaulting to false. Flat incentives (`PRICE_CUT` and `CLOSING_COST_CREDIT`) carry `value_cents` and leave `value_pct` null; a `RATE_BUYDOWN` carries `value_pct` — a fraction of the adjusted price — and leaves `value_cents` null.

An incentive's `status` is computed from the clock, never stored as input. It is `CANCELLED` when the `cancelled` flag has been set; otherwise `ACTIVE` when the window covers the clock, or when the flag is set, the community posture is `OVERHELD`, and the clock has not passed `window_end`; otherwise `SCHEDULED` when the clock is still before `window_start`; otherwise `EXPIRED`. Auto-activation therefore lets an incentive fire before its window opens, but only while the community is overheld and never past the window's end. A community manager can cancel an incentive while it is `SCHEDULED` or `ACTIVE`, which sets `cancelled` to true; cancelling one already `CANCELLED` or `EXPIRED` is rejected with `ERR_INVALID_STATE`. Every activation, expiry, and cancellation recomputes the incentive stack of every applicable home. Incentives can be listed per community with optional `status` and `type` filters, or read individually.

To prevent stacking two overlapping discount programs of the same kind, same-type incentives scoped to the same series (including two community-wide ones, where both series codes are null) must keep their windows apart: overlapping windows, or windows separated by less than a 7-day buffer, are rejected at creation with `ERR_INCENTIVE_WINDOW_CONFLICT` (HTTP 409).

The incentive stack on a home is computed as a waterfall. The applicable set is the `ACTIVE` incentives of the home's community whose `series_code` is null or matches the home's series, evaluated in order of `created_at` ascending. Each incentive contributes a component rounded individually to integer cents (half-up): a `PRICE_CUT` or `CLOSING_COST_CREDIT` contributes its `value_cents`, and a `RATE_BUYDOWN` contributes its `value_pct` times the home's `adjusted_price_cents`, rounded half-up. A `value_pct` participates in this multiplication as the exact decimal written in the request (e.g. a `value_pct` sent as `0.0147` is the decimal 0.0147); any binary floating-point artifact introduced by JSON number parsing is not part of the computation. The raw stack is the sum of those already-rounded components. The cap is the community's phase-dependent cap percentage (§3.4) times the adjusted price, itself rounded half-up to integer cents. The `stacked_incentive_cents` is the raw stack or the cap, whichever is smaller — so two generous programs can find their combined value clipped at the phase cap.

### 3.9. Selling the Home: Contracts, Approval Floors, and the Termination Cascade

A `SALES_AGENT` writes a sales contract against a home by naming the `home_id`, the `buyer_name`, and the negotiated `contract_price_cents`. The home must be `UNSOLD`, else `ERR_HOME_NOT_UNSOLD`. Creation puts the contract in `PENDING`, flips the home from `UNSOLD` to `RESERVED`, decreases the community's `standing_spec_count` by 1, and recomputes posture.

Approval belongs to the `COMMUNITY_MANAGER` and carries the system's headline price floor: the contract must be `PENDING` (else `ERR_INVALID_STATE`), and the `contract_price_cents` must be at least the home's `net_effective_price_cents` at approval time — incentives included — else the approval is rejected with `ERR_PRICE_BELOW_NET_FLOOR` (HTTP 422). Because the floor is evaluated at approval time, a mid-flight incentive activation or a build-stage advance between contract creation and approval changes what price will clear. Approval stamps `approved_at`, moves the contract to `APPROVED`, and flips the home from `RESERVED` to `SOLD`.

An approved deal can unwind in two directions. A `SALES_AGENT` can renegotiate, which moves the contract from `APPROVED` back to `PENDING`, increments `renegotiation_count` by 1, and flips the home from `SOLD` back to `RESERVED`; renegotiating a contract that is not `APPROVED` is rejected with `ERR_INVALID_STATE`. The cycle `APPROVED` back to `PENDING` and forward to `APPROVED` may repeat, with `renegotiation_count` counting each return to `PENDING`; the renegotiate call carries a new `contract_price_cents`, which is then re-tested against the floor at the next approval. Alternatively, either a `PENDING` or an `APPROVED` contract can be terminated by a `SALES_AGENT`, moving it to `TERMINATED`.

Termination is where the deepest cascade in the system lives, and every link matters:

1. The home returns to `UNSOLD` — from `RESERVED` when the terminated contract was `PENDING`, from `SOLD` when it was `APPROVED`.
2. The community's `standing_spec_count` increases by 1 and its posture is recomputed.
3. If that recomputation flips the community's posture to `OVERHELD`, every incentive in the community flagged with `auto_activate_on_overheld` whose window has not passed becomes `ACTIVE`, and the applicable homes' stacks and net effective prices recompute.

A `CLOSED` or already-`TERMINATED` contract cannot be terminated; the attempt is rejected with `ERR_SALES_CONTRACT_NOT_TERMINABLE` (HTTP 409).

Closing is the terminal handshake, owned by the `COMMUNITY_MANAGER`. The contract must be `APPROVED` (else `ERR_INVALID_STATE`) and the home's `build_stage` must be `COMPLETE` (else `ERR_HOME_NOT_COMPLETE`) — a buyer cannot close on a home still standing at drywall. Closing stamps `closed_at`, moves the contract to `CLOSED`, flips the home from `SOLD` to `CLOSED_SALE` and its `build_stage` from `COMPLETE` to `CLOSED`, increases the community's `lifetime_closed_sales` by 1, and recomputes the trailing and forward absorption rates. Contracts can be read individually or listed per home.

### 3.10. Trade Partner Capacity Commitments

A `DIVISION_PRESIDENT` registers a trade partner with its `name` and its `trade` — one of `FRAMING`, `PLUMBING`, `ELECTRICAL`, `HVAC`, or `MASONRY`. Only framing capacity gates starts in the current model, but partners of every trade are registered through the same path.

A trade partner then commits capacity to a community, acting as itself (its `X-User-ID` must equal the trade-partner id in the path, per §2.1). The commitment names the `community_id`, a half-open period from `period_start` (inclusive) to `period_end` (exclusive), and the `committed_units` the partner will frame in that period. A commitment is born with `allocated_units` at 0 and `remaining_units` equal to `committed_units`. Periods for the same partner serving the same community may not overlap; because the interval is half-open, adjacency — one commitment's `period_end` equal to the next's `period_start` — is allowed, and only true overlap is rejected with `ERR_CAPACITY_PERIOD_OVERLAP`.

A partner can also reduce a commitment by posting a smaller `new_committed_units`, but never below the units already allocated to started, not-yet-complete homes; a reduction that would put `committed_units` under `allocated_units` is rejected with `ERR_CAPACITY_BELOW_ALLOCATED`. A successful reduction recomputes `remaining_units`, and because capacity is one of the three terms in the starts authorization, it can push the community's `max_starts_remaining` to zero and set `starts_halted`. Allocation and release follow the lifecycle in §3.6 and §3.7: a start allocates one unit, and the advance into `COMPLETE` releases exactly one unit back to the same commitment. Commitments are readable individually, per partner, and per community.

### 3.11. Pacing Plans and the Starts Counter

The `DIVISION_PRESIDENT` publishes a pacing plan for a community by naming the closed period from `period_start` (inclusive) through `period_end` (inclusive) and the `max_starts` authorized in that period, carrying `expected_community_version` per §2.7. Publication supersedes: the prior `PUBLISHED` plan for the community, if any, flips to `SUPERSEDED`, the new plan is born `PUBLISHED`, and the community's `version` increments by 1. `SUPERSEDED` is terminal.

The community's `starts_this_period` counts homes created within the current `PUBLISHED` plan's period — the closed interval from that plan's `period_start` to its `period_end`. When no `PUBLISHED` plan exists the counter reads zero, and when a new plan supersedes the old one the counter resets to match the new plan's period. Because the plan period is closed on both ends while capacity commitment periods are half-open, a single instant near a boundary can be inside a pacing plan but outside a commitment, or vice versa; the starts gate evaluates each on its own terms.

### 3.12. Absorption, Supply, and the Pacing Summary

Two absorption rates share one trailing window but answer different questions. The window is the closed interval from 90 days before the clock through the clock itself. The `trailing_absorption_rate` is the count of the community's sales contracts in state `CLOSED` whose `closed_at` falls inside that window, divided by 3.0 — a backward-looking monthly pace. The `forward_pace_rate` adds the contracts currently `PENDING` or `APPROVED` to the same closed count before dividing by 3.0 — a forward-looking pace that diverges from the trailing rate whenever an open pipeline exists. Both are kept exact as rationals.

The `months_of_supply` divides `standing_spec_count` by the effective absorption — the trailing rate or the 1.0 floor, whichever is larger — and the posture thresholds of §2.10 apply exactly: `OVERHELD` at 4.0 or more, `STARVED` below 1.5, `NORMAL` in between. These quantities move on every event that touches them: contract creation, approval, termination, and closing; home starts; stage completion; and clock advancement all recompute the relevant pieces.

The pacing summary for a community — readable by every role — packages the whole picture into one computed view: `trailing_absorption_rate`, `forward_pace_rate`, `months_of_supply`, `posture`, `standing_spec_count`, `starts_this_period`, `max_starts_remaining`, `starts_halted`, and `avg_cycle_time_days`. It is the same arithmetic the starts gate uses, so what the summary shows is what a start would face.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify an existing resource or perform an action return HTTP 200; all reads return HTTP 200. The table is a summary only — request fields, computed fields, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /land-parcels | Create a land parcel | LAND_MANAGER |
| GET | /option-contracts | List option contracts, optionally by parcel or state | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /option-contracts | Create an option contract in `DRAFT` | LAND_MANAGER |
| GET | /option-contracts/{id} | Get an option contract (lazy defaults applied before read) | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /option-contracts/{id}/execute | Execute a `DRAFT` contract to `ACTIVE` | LAND_MANAGER |
| POST | /option-contracts/{id}/cure | Cure a `DEFAULTED` contract back to `ACTIVE`, charging the cure fee | LAND_MANAGER |
| POST | /option-contracts/{id}/takedowns | Schedule a takedown (OCC on contract version) | LAND_MANAGER |
| GET | /option-contracts/{id}/takedowns | List a contract's takedowns, optionally by community | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /takedowns/{id}/execute | Execute a scheduled takedown within its window; releases lots | LAND_MANAGER |
| GET | /takedowns/{id} | Get a takedown (lazy default applied before read) | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /takedowns | List takedowns with optional filters | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /communities | Create a community in `PLANNING` | DIVISION_PRESIDENT |
| GET | /communities/{id} | Get a community with computed counters and posture | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /communities/{id}/open | Open the community for sales | COMMUNITY_MANAGER |
| POST | /communities/{id}/advance-phase | Advance phase one step; entering `CLOSE_OUT` raises the incentive cap | DIVISION_PRESIDENT |
| POST | /communities/{id}/product-series | Add a product series with a non-overlapping price band | COMMUNITY_MANAGER |
| GET | /communities/{id}/product-series | List a community's product series | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/lots | List a community's lots | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/homes | List a community's homes | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/incentives | List a community's incentives, optionally by status or type | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/pacing-plans | List a community's pacing plans | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/capacity-commitments | List capacity commitments serving a community | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /communities/{id}/pacing-summary | Computed starts-pacing summary for a community | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /communities/{id}/homes | Start a spec home on a banked lot | COMMUNITY_MANAGER |
| POST | /communities/{id}/incentives | Create an incentive program for standing inventory | COMMUNITY_MANAGER |
| POST | /incentives/{id}/cancel | Cancel a `SCHEDULED` or `ACTIVE` incentive | COMMUNITY_MANAGER |
| GET | /incentives/{id} | Get an incentive | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /communities/{id}/pacing-plans | Publish a pacing plan (OCC on community version); supersedes the prior plan | DIVISION_PRESIDENT |
| GET | /homes/{id} | Get a home with computed pricing | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /homes | List homes with optional filters | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| GET | /homes/{id}/sales-contracts | List a home's sales contracts | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /homes/{id}/advance-stage | Advance build stage one step; `DRYWALL` to `COMPLETE` issues the CO | COMMUNITY_MANAGER |
| POST | /sales-contracts | Create a sales contract on an `UNSOLD` home | SALES_AGENT |
| GET | /sales-contracts/{id} | Get a sales contract | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /sales-contracts/{id}/approve | Approve a `PENDING` contract (price floor enforced) | COMMUNITY_MANAGER |
| POST | /sales-contracts/{id}/renegotiate | Renegotiate an `APPROVED` contract back to `PENDING` with a new price | SALES_AGENT |
| POST | /sales-contracts/{id}/close | Close an `APPROVED` contract on a `COMPLETE` home | COMMUNITY_MANAGER |
| POST | /sales-contracts/{id}/terminate | Terminate a `PENDING` or `APPROVED` contract | SALES_AGENT |
| POST | /trade-partners | Create a trade partner | DIVISION_PRESIDENT |
| GET | /trade-partners/{id} | Get a trade partner | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /trade-partners/{id}/capacity-commitments | Commit trade capacity to a community for a half-open period | TRADE_PARTNER |
| GET | /trade-partners/{id}/capacity-commitments | List a trade partner's capacity commitments | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /capacity-commitments/{id}/reduce | Reduce committed units (not below allocated) | TRADE_PARTNER |
| GET | /capacity-commitments/{id} | Get a capacity commitment | DIVISION_PRESIDENT, LAND_MANAGER, COMMUNITY_MANAGER, SALES_AGENT, TRADE_PARTNER |
| POST | /_clock/set_current_utc | Test-driving endpoint: set the logical clock | DIVISION_PRESIDENT |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_MISSING_IDEMPOTENCY_KEY | 400 |
| ERR_IDEMPOTENCY_REPLAY_MISMATCH | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_COMMUNITY_NOT_OPEN | 409 |
| ERR_INVALID_PHASE_TRANSITION | 409 |
| ERR_HOME_NOT_COMPLETE | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_CONTRACT_EXHAUSTED | 409 |
| ERR_TAKEDOWN_WINDOW_NOT_OPEN | 409 |
| ERR_TAKEDOWN_WINDOW_EXPIRED | 409 |
| ERR_LOT_NOT_AVAILABLE | 409 |
| ERR_HOME_NOT_UNSOLD | 409 |
| ERR_STARTS_QUOTA_EXCEEDED | 409 |
| ERR_STARTS_BLOCKED_OVERHELD | 409 |
| ERR_NO_CAPACITY_REMAINING | 409 |
| ERR_NO_PUBLISHED_PACING_PLAN | 409 |
| ERR_CAPACITY_PERIOD_OVERLAP | 409 |
| ERR_CAPACITY_BELOW_ALLOCATED | 409 |
| ERR_INCENTIVE_WINDOW_CONFLICT | 409 |
| ERR_SERIES_BAND_OVERLAP | 422 |
| ERR_PRICE_OUT_OF_SERIES_BAND | 422 |
| ERR_PRICE_BELOW_NET_FLOOR | 422 |
| ERR_SALES_CONTRACT_NOT_TERMINABLE | 409 |
