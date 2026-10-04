# Guaranteed Savings Performance Contract API — Product Requirements Document

## 1. Introduction

Energy Service Companies (ESCOs) win retrofit business on a simple promise: the energy savings will pay for the work, and if they do not, the vendor writes the check. Delivering on that promise across a multi-decade contract requires far more rigor than a sales slide — a metered baseline must be fixed and agreed, conservation measures must be bundled so that quick-payback lighting projects subsidize slow-payback envelope work, financing must be sized so guaranteed savings always cover the debt service, construction must proceed inside occupied buildings without breaching disruption budgets, and every guarantee year must close with a reconciled savings figure both parties have attested to. Disputes over attribution — a warmer winter, an added wing, changed operating hours — are not exceptions; they are the norm, and the system must model them as first-class workflow.

This document specifies the API for a **Building Automation Retrofit & Guaranteed Savings Performance Contract** platform in the Johnson Controls ESCO mold. It governs the full arc of a performance contract: the facility energy audit that establishes the measurement baseline and identifies candidate measures; project scoping with measure bundling and cross-subsidy; execution of a guaranteed-savings contract under which the vendor is financially responsible for any shortfall against the pinned baseline; selection of a measurement-and-verification protocol with weather normalization and occupancy adjustment; financing arranged through lease, bond, or third-party structures paid from avoided cost; phased construction inside occupied facilities with explicit disruption limits; and the annual measurement, attestation, reconciliation, baseline-restatement, and dispute-resolution machinery that runs for the life of the guarantee.

All amounts of money are carried as integer cents. All timestamps are ISO 8601 UTC. The platform is API-only; every behavior described below is observable and drivable through the endpoints catalogued in Section 4.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which that principal acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are well-formed but the named role is not permitted to call the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `PlatformAdmin` — an opaque operator role that manages the logical clock and registers identity actors.
- `ESCOEngineer` — the vendor-side engineer who runs the audit, builds the scope, drives construction, and submits savings reports.
- `OwnerRep` — the facility owner's representative who approves the baseline, executes and closes the contract, attests reports, and signs off construction phases.
- `LenderOfficer` — the third-party financier who approves financing facilities and draws and adjudicates savings disputes.

Identity semantics differ per role. When `X-User-Role` is `OwnerRep`, `X-User-ID` is the `id` of the acting `OwnerRep`; ownership-style checks that reference an owner representative — most notably the `attested_by_owner_rep_id` recorded on a savings report at attestation — compare against `X-User-ID`. When `X-User-Role` is `ESCOEngineer`, `X-User-ID` is likewise the `id` of the acting `ESCOEngineer` entity, and any resource field that references an engineer resolves against registered engineers. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `LenderOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, even though the role wields decisive authority over financing and dispute resolution. Any non-empty string is a well-formed header value; and where an endpoint records an identity taken from a header — the `attested_by_owner_rep_id` written at attestation, or the filer side of a dispute — the server records the header value as given without verifying that it names a registered identity actor.

Before any identity actor can act, a `PlatformAdmin` registers it: an owner representative is registered with a `full_name` and an `organization`; an ESCO engineer is registered with a `full_name` and a professional `license_number`. Both registrations are exclusive to `PlatformAdmin`, as is the clock-setting capability described in §2.6. Read access is broad: all four roles may call every GET endpoint.

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
- A request to a path the API does not define is rejected with `ERR_INVALID_REQUEST` (HTTP 404), and a defined path called with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 405).

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending, with ties broken by `id` ascending.

### 2.4. Common Resource Properties and Money

Every persisted resource carries an `id` minted by the server as a UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version` integer that starts at 1 and increments by exactly 1 on every mutation of that resource. The two exceptions are the financing draw and the disruption log: those resources carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and no optimistic-concurrency field ever targets them.

All monetary quantities are integer cents — never floats, never dollars. Wherever the platform computes a money amount, the result is rounded half-up to integer cents. Two intermediate quantities follow different precision rules: kilowatt-hour figures inside normalization arithmetic are held at 4 decimal places before final rounding, and a financing facility's `coverage_ratio` is held at 4 decimal places. A bundle's `blended_payback_years` is reported at 2 decimal places, rounded half-up. Non-integer numeric fields accepted as decimals — degree-day figures, occupancy factors, `annual_rate_pct`, and tier prices — serialize in responses as a JSON integer when their value is integral and as a JSON number otherwise; a measure's `simple_payback_years` is serialized unrounded.

### 2.5. The Logical Clock

Guarantee periods, construction windows, financing maturities, and report deadlines all compare against a **logical clock**, never the wall clock. The logical clock starts at exactly `2026-09-01T00:00:00Z` before any call has set it, and it never falls back to wall-clock time. A `PlatformAdmin` may advance it by supplying a `current_utc` instant through the clock-setting capability; the server responds with the now-current `current_utc`. Rules phrased below as "the logical clock has reached" or "before the window ends" always refer to this clock.

### 2.6. Nested Resource Addressing and Validation Order

Resources are addressed through nested paths — a contract, then a child collection beneath it, then a grandchild beneath that. Path segment identifiers are validated left to right: the contract first, then the bundle, facility, phase, report, adjustment, or dispute beneath it, then the measure or draw beneath that. A segment that does not exist, or that exists but is not nested under the previously validated parent, yields the segment's own not-found error — `ERR_CONTRACT_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, or `ERR_DISPUTE_NOT_FOUND` (all HTTP 404).

Identifiers referenced inside a request body rather than the path — the `report_id` supplied when filing a dispute, or the `supersedes_adjustment_id` supplied when proposing a baseline adjustment — are checked after the path resolves, and an unresolvable body reference is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404).

Validation across an endpoint runs in a fixed global order. First the authentication headers are checked, then role permission, then path-segment existence and nesting, then body-referenced existence, then whether the target entity's current state even permits the requested transition, and only then the business rules — safety budgets, window containment, fiscal thresholds, temporal gates, and referential integrity — each of which is described where it applies in Section 3 and catalogued by error id in Section 5. A malformed body, an invalid enum value, or a negative or zero value that violates a field constraint is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Resource-creation endpoints (baselines, bundles, measures, facilities, draws, phases, reports, and adjustments) do not gate on the parent contract's status; contract-state and resource-state gates apply only where an endpoint's description states them.

### 2.7. Optimistic Concurrency Control

Two write operations in the platform are guarded by optimistic concurrency control, and only these two.

Reconciling a savings report requires the request to carry `expected_contract_version`, holding the contract `version` the caller last observed. If the contract's current `version` does not match — because, for example, another report has been reconciled in the meantime, advancing `cumulative_verified_savings_cents` and `guarantee_shortfall_reserve_cents` — the reconcile is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because reconciliation mutates the contract-level ledger; a caller working from a stale ledger view must not be allowed to write over a state it has not observed.

Approving a baseline adjustment requires the request to carry `expected_baseline_version`, holding the baseline `version` the caller last observed. If the baseline's current `version` does not match — because another adjustment has just been approved against it, restating the baseline and bumping its `version_tag` — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). A stale chain position would otherwise let an old `kwh_delta` land on top of a restated baseline the caller never saw.

No other endpoint accepts an expected-version field. Endpoints not named above must not require one.

### 2.8. Tariff Tiering and Rate Schedules

A baseline's `rate_schedule` is an ordered array of tariff tiers, each tier a pair of an `up_to_kwh` ceiling and a `cents_per_kwh` price. Tiers must be contiguous: the first tier's `up_to_kwh` is greater than zero, each subsequent tier picks up exactly where the previous one ended (tier ceilings must be strictly increasing), and the final tier carries an `up_to_kwh` of `null` meaning unbounded — a single-tier schedule whose sole tier is unbounded is therefore valid. Every `cents_per_kwh` must be greater than zero. Pricing a quantity of energy walks the tiers in array order: each tier absorbs the smaller of the remaining kilowatt-hours and its own ceiling (an unbounded tier absorbs all that remains), the absorbed kilowatt-hours are multiplied by that tier's price and accumulated into the cost, and the walk continues until no energy remains. This tiered-pricing procedure is the single pricer used by the baseline cost computation and the measured savings computation alike.

### 2.9. Cross-Aggregate Cascades and Derived Fields

A single request frequently mutates more than one entity, and every such cascade is atomic within the request. Completing an audit pins the contract's `executed_baseline_id` to the approved baseline. Executing a contract locks that baseline and activates every approved bundle. Mobilizing a contract flips an approved financing facility into funding so draws become available. Excluding a subsidized measure returns its draw to the bundle's pool and re-runs the subsidy waterfall over the remaining included measures. Approving a baseline adjustment restates the baseline, recomputes every in-flight savings report's verified savings and shortfall, and re-derives the contract's cumulative verified savings — all in one atomic step. Wherever a mutation touches an entity that carries `version`, that entity's `version` increments and its `updated_at` refreshes; derived fields are recomputed synchronously rather than by any background job. The one exception is the contract under a baseline-adjustment approval: its ledgers are re-derived and its `updated_at` refreshes, but its `version` does not increment (see §3.6).

The contract keeps two ledger fields that the whole lifecycle feeds: `cumulative_verified_savings_cents`, the running sum of verified savings across all reconciled guarantee years, and `guarantee_shortfall_reserve_cents`, the vendor's cumulative liability — shortfall payments owed minus shortfall payments settled, floored at zero. Both are recomputed synchronously whenever a report reconciles or a baseline restatement lands, and both gate the final close of the contract.

## 3. Business Logic & Workflows

### 3.1. Opening the Contract: the Audit and Its Baseline

An `ESCOEngineer` opens a performance contract by providing the `facility_name`, the guarantee length in `contract_term_years` (at least 1 and at most 25), the `guarantee_start_date` on which the first guarantee period begins, the measurement-and-verification `mv_protocol` (one of `IPMVP_A`, `IPMVP_B`, `IPMVP_C`, or `IPMVP_D`), the committed `guaranteed_annual_savings_cents` (greater than zero), and the total installed `contract_value_cents` (greater than zero). The new contract begins life in `AUDIT` status with `version` 1. The `guarantee_start_date` must be later than the audit's completion date at the moment the audit completes; a start date on or before that point is invalid.

During the audit the engineer establishes the measurement baseline. A baseline is created under the contract with the historical window `baseline_period_start` (inclusive) and `baseline_period_end` (exclusive, strictly after the start), the metered `annual_energy_kwh` for that window (greater than zero), the `rate_schedule` of tariff tiers described in §2.8, the observed `heating_degree_days` and `cooling_degree_days` (each at least zero), and the `occupancy_factor` — the facility's weekly occupied hours divided by 168, strictly greater than zero and at most 1. A fresh baseline is a `DRAFT`.

When the engineer submits the baseline — allowed only while the contract is still in `AUDIT`; a baseline not in `DRAFT` is rejected with `ERR_BASELINE_NOT_DRAFT`, and a contract no longer in `AUDIT` yields `ERR_CONTRACT_NOT_IN_AUDIT` — the platform computes the baseline's `adjusted_annual_cost_cents` for the first time. The computation weather- and occupancy-normalizes the consumption, then prices it through the tiered rate schedule. Normalization scales `annual_energy_kwh` by three multiplicative factors. The heating factor is one plus 0.05 times the relative deviation between a contract-average heating-degree-day figure and the baseline's own `heating_degree_days`, where the relative deviation is the difference divided by the larger of 1 and the baseline's `heating_degree_days`; at initial submission the average is the baseline itself, so this factor is exactly 1. The cooling factor works identically with a coefficient of 0.08 against `cooling_degree_days`, and is likewise 1 at initial submission. The occupancy factor is the baseline's `occupancy_factor` divided by the reference occupancy of 0.5. The resulting normalized kilowatt-hours — held at 4 decimal places — are priced tier by tier through the `rate_schedule` in array order, and the accumulated cost is rounded half-up to integer cents to become `adjusted_annual_cost_cents`.

An `OwnerRep` then approves or rejects the submitted baseline. Both actions require the baseline to be in `SUBMITTED`; otherwise the call fails with `ERR_BASELINE_NOT_SUBMITTED`. Approval moves the baseline to `APPROVED`; rejection moves it to `REJECTED`, a terminal state.

The audit itself concludes when the engineer completes it, moving the contract from `AUDIT` to `SCOPED`. Three preconditions guard this step, and each carries its own error: the contract must be in `AUDIT` (`ERR_CONTRACT_NOT_IN_AUDIT`); a baseline must exist for the contract and be in `APPROVED` state (`ERR_BASELINE_NOT_APPROVED`); and at least one measure must exist in `PROPOSED` or `INCLUDED` state across the contract's bundles (`ERR_NO_MEASURES_IDENTIFIED`). On completion the contract pins `executed_baseline_id` to the approved baseline's `id` — when more than one approved baseline exists, the earliest-created one (ties broken by `id`) is pinned — this is the baseline the guarantee will run against for the rest of the contract's life, and it is the guard that keeps later restatements honest — and the contract's `version` increments. The completion-date rule is evaluated against the logical clock at the moment of completion: a `guarantee_start_date` not strictly later than the current logical instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.2. Scoping the Work: Bundles, Measures, and the Subsidy Pool

ESCO scoping groups conservation measures into bundles so that fast-payback items subsidize slow ones. An engineer creates a measure bundle under a contract with a `name`; the bundle starts in `DRAFT`. Measures are then created inside a bundle with a `measure_type` (one of `LIGHTING`, `HVAC`, `CONTROLS`, `ENVELOPE`, `WATER`, or `OTHER`), a fully installed `installed_cost_cents` (greater than zero), and an engineering-estimated `annual_savings_cents` (zero or greater). A new measure is `PROPOSED`. Each measure carries a denormalized `contract_id` alongside its `bundle_id` so the contract-wide measure listing can filter without walking bundles.

Two derived numbers describe each bundle's financial posture. The `blended_payback_years` is the sum of `installed_cost_cents` over the counted measures divided by the sum of their `annual_savings_cents`, reported at 2 decimal places rounded half-up; while the bundle is `DRAFT` or `PROPOSED` the counted set is measures in `PROPOSED` or `INCLUDED`, and once the bundle is approved the counted set is `INCLUDED` measures only. If the summed annual savings are zero the blended payback is `null` — the platform never divides by zero. The `subsidy_pool_cents` is the bundle's cross-subsidy capacity: for each counted measure whose `simple_payback_years` is at most 3 years, the pool accrues the larger of zero and the measure's `annual_savings_cents` multiplied by 3 minus its `installed_cost_cents`. A measure's own `simple_payback_years` is its `installed_cost_cents` divided by its `annual_savings_cents`, or `null` when the savings are zero. Both bundle figures are recomputed whenever a measure is created on the bundle, included, excluded, or otherwise changes.

Proposing a bundle — an engineer action requiring the bundle in `DRAFT` (`ERR_BUNDLE_NOT_DRAFT`), the contract in `AUDIT` or `SCOPED` (`ERR_CONTRACT_NOT_SCOPABLE`), and at least one measure in `PROPOSED` or `INCLUDED` (`ERR_BUNDLE_EMPTY`) — moves it to `PROPOSED` and recomputes both derived figures. These gates are evaluated in the order named: the bundle's `DRAFT` state is checked first, then the contract's scopability, then the non-emptiness rule, so a request that violates more than one gate surfaces the earliest failing error.

An `OwnerRep` approves a proposed bundle. Approval requires the bundle in `PROPOSED` (`ERR_BUNDLE_NOT_PROPOSED`) and requires `blended_payback_years` not to exceed the contract's `contract_term_years`; the check uses the freshly recomputed pre-approval figure, and a bundle whose blended payback outlasts the guarantee — including one whose blended payback is `null` because the counted measures' summed annual savings are zero — is rejected with `ERR_BUNDLE_PAYBACK_EXCEEDS_TERM` (HTTP 422). On approval, every `PROPOSED` measure in the bundle moves to `INCLUDED`, the subsidy waterfall runs, and the bundle's `version` increments. The waterfall considers only the bundle's `INCLUDED` measures whose `simple_payback_years` is not `null`, sorted ascending by `simple_payback_years` with ties broken by `created_at` ascending and further ties by `id` ascending. Walking that order, each measure whose simple payback exceeds 7 years may draw from the pool: its need is its `installed_cost_cents` minus its `annual_savings_cents` multiplied by 7, and its `subsidy_draw_cents` becomes the smaller of that need and the remaining pool, which is then decremented by the draw. Every other `INCLUDED` measure receives a `subsidy_draw_cents` of zero, and measures start at a default draw of zero. `EXCLUDED` measures never draw.

An engineer may withdraw a bundle while it is in `DRAFT` or `PROPOSED` (`ERR_BUNDLE_NOT_WITHDRAWABLE` otherwise); withdrawal moves the bundle to `WITHDRAWN` and every `PROPOSED` measure in it to `EXCLUDED`. Individual measures may be excluded while `PROPOSED` or `INCLUDED` (`ERR_MEASURE_NOT_EXCLUDABLE` otherwise), provided the contract is not in `PERFORMANCE`, `CLOSED`, or `TERMINATED` — once the contract reaches those states the measure set is immutable and the attempt fails with `ERR_CONTRACT_LOCKED`. Excluding a measure zeroes its `subsidy_draw_cents` and unconditionally recomputes the bundle's `blended_payback_years` and `subsidy_pool_cents` and re-runs the waterfall over the remaining `INCLUDED` measures, so any draw the excluded measure held returns to the pool.

With at least one bundle approved, an `OwnerRep` executes the contract, moving it from `SCOPED` to `EXECUTED`. Execution requires the contract in `SCOPED` (`ERR_CONTRACT_NOT_SCOPED`), at least one `MeasureBundle` in `APPROVED` (`ERR_NO_APPROVED_BUNDLE`), and a financing facility in `APPROVED` or `FUNDING` (`ERR_NO_APPROVED_FINANCING`); it also re-checks that every approved bundle's `blended_payback_years` does not exceed `contract_term_years`, surfacing `ERR_BUNDLE_PAYBACK_EXCEEDS_TERM` if the scope has drifted — a bundle whose blended payback is `null` fails this re-check as well. Execution cascades: the baseline pinned by `executed_baseline_id` transitions from `APPROVED` to `LOCKED`, every approved bundle moves to `ACTIVE` (its `INCLUDED` measures remain `INCLUDED`), and the contract's `version` increments.

An owner may instead terminate the contract from `AUDIT` or `SCOPED`; from any later state termination fails with `ERR_CONTRACT_NOT_TERMINABLE`. Termination cascades broadly: every non-terminal bundle (one not already `WITHDRAWN` or `COMPLETE`) moves to `WITHDRAWN` and its non-terminal measures (those not already `VERIFIED` or `EXCLUDED`) to `EXCLUDED`, every `DRAFT` or `SUBMITTED` financing facility moves to `CANCELLED`, and the contract's `version` increments.

### 3.3. Financing the Retrofit: Facilities, Payments, and Draws

The retrofit is paid from avoided cost, so the financing must be sized so that guaranteed savings always cover the debt service. An `ESCOEngineer` creates a financing facility under the contract with a `facility_type` of `LEASE`, `BOND`, or `THIRD_PARTY`; a financed `principal_cents` greater than zero and no greater than the parent contract's `contract_value_cents`; a nominal `annual_rate_pct` of at least 0 and at most 30 percent; and a `term_years` of at least 1, at most 30, and no greater than the parent contract's `contract_term_years`. A new facility is `DRAFT` with a `drawn_cents` of zero.

Submitting a facility — an engineer action requiring the facility in `DRAFT` (`ERR_FACILITY_NOT_DRAFT`) and the contract in `SCOPED` (`ERR_CONTRACT_NOT_SCOPED`) — computes its level `annual_payment_cents` and its `coverage_ratio`. The payment algorithm differs per facility type, and the same principal, rate, and term deliberately produce different payments under different types. For a `LEASE`, the payment is the plain annuity on the note rate: with the rate expressed as a fraction and the term in years, the payment is the principal times the rate, divided by one minus one-plus-the-rate raised to the negative term — rounded half-up to integer cents; when the rate is exactly zero, the payment is simply the principal divided by the term, rounded half-up. For a `BOND`, the same annuity is computed and then multiplied by the bond fee uplift of 1.02 before rounding, so identical inputs yield a higher payment than a lease. For `THIRD_PARTY`, the annuity is computed at the note rate plus a spread of 0.015 — one and a half percentage points added to the rate before the annuity formula runs. The `coverage_ratio` is then the contract's `guaranteed_annual_savings_cents` divided by the computed payment, rounded to 4 decimal places.

A `LenderOfficer` approves a submitted facility. Approval requires the facility in `SUBMITTED` (`ERR_FACILITY_NOT_SUBMITTED`) and a `coverage_ratio` of at least 1.0000; a facility whose guaranteed savings would not fully cover its annual payment is rejected with `ERR_COVERAGE_BELOW_ONE` (HTTP 422). The same lender may instead cancel a facility while it is in `DRAFT` or `SUBMITTED` (`ERR_FACILITY_NOT_CANCELLABLE` otherwise); cancelling a `SUBMITTED` facility rejects every `REQUESTED` draw on it.

Once the contract moves from `EXECUTED` into `CONSTRUCTION`, every approved facility automatically moves to `FUNDING` and draws become available. An engineer requests a draw with an `amount_cents` (greater than zero) and a free-text `purpose`; the draw is born `REQUESTED`. Draw requests are accepted whatever the facility's current status — the funding gate is enforced at approval time, not at request time. Draws carry only `id` and `created_at` — they have no `version` and no `updated_at`. A lender approves a requested draw only while the facility is in `FUNDING`; the draw's own state is checked first (`ERR_DRAW_NOT_REQUESTED` if the draw has left `REQUESTED`), then the facility's (`ERR_FACILITY_NOT_FUNDING` if it is not in `FUNDING`), and only then the availability rule: the `amount_cents` must fit within the facility's `principal_cents` minus its `drawn_cents` minus the sum of every other approved-but-not-yet-released draw on the facility. An over-availability draw is rejected with `ERR_DRAW_EXCEEDS_AVAILABLE` (HTTP 422). Releasing an approved draw (`ERR_DRAW_NOT_APPROVED` if it is not in `APPROVED`) moves it to `RELEASED` and adds its amount to the facility's `drawn_cents`; a lender may instead reject a requested draw outright.

A facility in `FUNDING` is paid off by an `OwnerRep` once its term has fully elapsed — the logical clock must have reached the `guarantee_start_date` plus `term_years` years, otherwise the payoff is rejected with `ERR_FACILITY_TERM_NOT_ELAPSED` (HTTP 422); a facility not in `FUNDING` yields `ERR_FACILITY_NOT_FUNDING`. Payoff moves the facility to `PAID_OFF`. At contract close, a funding facility whose draws have been fully serviced — that is, whose `drawn_cents` is exactly zero — also transitions to `PAID_OFF`; if it has not, that fact is informational only — close is blocked solely by the shortfall-reserve rule described in §3.5.

### 3.4. Construction in Occupied Facilities: Phases and Disruption

Construction proceeds in phases so an occupied building never absorbs more disruption than its budget allows. An engineer creates a work phase with a `phase_label`, a construction window from `window_start` (inclusive) to `window_end` (exclusive, strictly after the start), and a `disruption_budget_hours` greater than zero. A phase begins `PLANNED` with `consumed_disruption_hours` at zero.

Mobilizing a phase — an engineer action requiring the phase in `PLANNED` (`ERR_PHASE_NOT_PLANNED`) and the contract in `EXECUTED` (`ERR_CONTRACT_NOT_EXECUTED`) — moves it to `MOBILIZED`, provided its window does not overlap any other `MOBILIZED` or `IN_PROGRESS` phase window of the same contract. Windows are half-open: one window ending exactly when another begins does not overlap, and is allowed; any true overlap is rejected with `ERR_PHASE_WINDOW_OVERLAP`. Once at least one phase is mobilized, the engineer mobilizes the contract itself, moving it from `EXECUTED` to `CONSTRUCTION` (`ERR_NO_MOBILIZED_PHASE` if no phase stands mobilized). This is the transition that flips an approved facility into `FUNDING`, and it increments the contract's `version`.

Starting a phase moves it from `MOBILIZED` to `IN_PROGRESS` and requires the logical clock to have reached `window_start`; starting earlier fails with `ERR_PHASE_WINDOW_NOT_STARTED`. The same start endpoint also resumes a `SUSPENDED` phase: resuming requires the logical clock to still be before `window_end`, else `ERR_PHASE_WINDOW_CLOSED`. A phase in any state other than `MOBILIZED` or `SUSPENDED` cannot be started or resumed, and the attempt fails with `ERR_PHASE_NOT_MOBILIZED`. While a phase is in progress, the engineer logs occupant disruptions against it with an `occurred_at` instant, a whole-number `hours` greater than zero, and a free-text `cause`; these body fields are shape-validated first (`ERR_INVALID_REQUEST` on a malformed value), before the state gate. Logging a disruption then requires the phase to be `IN_PROGRESS`; against a phase in any other state the log is rejected with `ERR_PHASE_NOT_IN_PROGRESS` (HTTP 409). Two safety checks then guard every disruption log, evaluated in this order: first the budget check — if the phase's `consumed_disruption_hours` plus the new `hours` would exceed `disruption_budget_hours`, the log is rejected with `ERR_DISRUPTION_BUDGET_EXCEEDED` (HTTP 422); then the window check — the `occurred_at` must fall inside the phase window, at or after `window_start` and strictly before `window_end`, else `ERR_DISRUPTION_OUTSIDE_WINDOW` (HTTP 422). An accepted log adds its `hours` to `consumed_disruption_hours`. Disruption logs, like draws, carry only `id` and `created_at`.

Completing a phase is an owner action requiring the phase in `IN_PROGRESS` (`ERR_PHASE_NOT_IN_PROGRESS`). Completion is straightforward while the logical clock is still before `window_end`; after the window has closed, completion is allowed only when every measure of the contract — the check spans all of the contract's measures, not only those scheduled to the phase — is already `INSTALLED`, `VERIFIED`, or `EXCLUDED`; late completion with outstanding work is rejected with `ERR_PHASE_OVERRUN`. An owner may instead suspend an in-progress phase, moving it to `SUSPENDED`, and the engineer may later start it again via the resume path described above.

Measure installation is tied to these windows. An engineer installs an `INCLUDED` measure (`ERR_MEASURE_NOT_INCLUDED` otherwise) only while the contract is in `CONSTRUCTION` (`ERR_CONTRACT_NOT_IN_CONSTRUCTION`) and only while at least one `IN_PROGRESS` phase of the contract has a window containing the logical clock — if no active phase window covers the current instant, the install is rejected with `ERR_NO_ACTIVE_PHASE_WINDOW`. Installation moves the measure to `INSTALLED`. An `OwnerRep` then verifies an installed measure (`ERR_MEASURE_NOT_INSTALLED` otherwise), moving it to `VERIFIED`; when the verifying measure leaves a bundle with no remaining non-`EXCLUDED` measure unverified, that bundle automatically completes, moving from `ACTIVE` to `COMPLETE`.

When construction wraps up, the owner commences the performance period, moving the contract from `CONSTRUCTION` to `PERFORMANCE`. The gate is strict: the contract must be in `CONSTRUCTION` (`ERR_CONTRACT_NOT_IN_CONSTRUCTION`), every work phase must be `COMPLETE` (`ERR_PHASES_INCOMPLETE`), every measure in an active bundle must be `VERIFIED` or `EXCLUDED` (`ERR_MEASURES_UNVERIFIED`), and the logical clock must have reached the `guarantee_start_date` — commencing earlier fails with `ERR_GUARANTEE_PERIOD_NOT_STARTED` (HTTP 422). The contract's `version` increments.

### 3.5. The Guarantee Years: Savings Reports, Verification, and Reconciliation

Each guarantee year produces one savings report. An engineer creates a report under the contract with a 1-indexed `period_year`, the metered `actual_energy_kwh` for that year (zero or greater), the observed `period_hdd` and `period_cdd` (each at least zero), and the observed `period_occupancy_factor` (greater than zero, at most 1). Only one report may exist per `period_year` per contract; a duplicate guarantee-year report is rejected with `ERR_DUPLICATE_REPORT_PERIOD`. A new report is `DRAFT`.

Submitting a report is the moment the year's savings are computed. The report must be in `DRAFT` (`ERR_REPORT_NOT_DRAFT`), the contract must be in `PERFORMANCE` (`ERR_CONTRACT_NOT_IN_PERFORMANCE`), and the guarantee year must actually have ended: the logical clock must have reached the `guarantee_start_date` plus `period_year` years minus one day, otherwise the submission is rejected with `ERR_PERIOD_NOT_ENDED` (HTTP 422). "Plus `period_year` years" is calendar-year addition: a February 29 anniversary lands on February 28 in a non-leap year. On submission the platform computes `verified_savings_cents` using the contract's locked-or-restated baseline — the one pinned by `executed_baseline_id` — and the variant keyed by the contract's `mv_protocol`.

Under the measured variant (`IPMVP_B` and `IPMVP_C`), metered consumption drives the result. The report's `actual_energy_kwh` is weather- and occupancy-normalized against the baseline: the heating adjustment multiplies by one minus 0.05 times the relative deviation of `period_hdd` from the baseline's `heating_degree_days` (the difference divided by the larger of 1 and the baseline's `heating_degree_days`); the cooling adjustment multiplies by one minus 0.08 times the analogous relative deviation of `period_cdd` from the baseline's `cooling_degree_days`; and the occupancy adjustment multiplies by the baseline's `occupancy_factor` divided by the report's `period_occupancy_factor`. The normalized kilowatt-hours, held at 4 decimal places, are priced through the baseline's current `rate_schedule` using the tiered walk of §2.8, and `verified_savings_cents` is the baseline's current `adjusted_annual_cost_cents` minus that period cost, rounded half-up to integer cents. Under the stipulated variant (`IPMVP_A` and `IPMVP_D`), meter readings are ignored entirely: `verified_savings_cents` is 95 percent of the sum of `annual_savings_cents` over the contract's `VERIFIED` measures, rounded half-up to integer cents. Identical weather and meter inputs therefore produce different verified savings under the two variants — a deliberate dual calculation.

Either way, the report's `shortfall_cents` is then the larger of zero and the contract's `guaranteed_annual_savings_cents` minus the `verified_savings_cents`.

An `OwnerRep` attests a submitted report (`ERR_REPORT_NOT_SUBMITTED` otherwise), moving it to `ATTESTED`; the attesting representative is recorded on the report as `attested_by_owner_rep_id`, taken from the caller's `X-User-ID`. Reconciliation is the owner's final step for the year and is OCC-guarded as described in §2.7: the report's `ATTESTED` state is checked first (`ERR_REPORT_NOT_ATTESTED`), then the request must carry an integer `expected_contract_version` — a missing or non-integer value is `ERR_INVALID_REQUEST` (HTTP 400) — matching the contract's current `version`, else `ERR_STALE_VERSION` (HTTP 412). A successful reconcile moves the report to `RECONCILED` — a terminal state — and re-derives the contract ledger atomically from the set of `RECONCILED` reports: `cumulative_verified_savings_cents` becomes the sum of their `verified_savings_cents` and `guarantee_shortfall_reserve_cents` becomes the sum of their `shortfall_cents`, floored at zero, and the contract's `version` increments by exactly 1. The reserve is the vendor's open liability: it accumulates shortfalls as they reconcile, is floored at zero, and must stand at zero before the contract can close.

Closing the contract — moving from `PERFORMANCE` to `CLOSED` — is an owner action with a three-part gate. First, a reconciled report must exist for every `period_year` from 1 through `contract_term_years`; any missing year yields `ERR_RECONCILIATION_INCOMPLETE`. Second, no dispute may be in `OPEN` or `ESCALATED` state; lingering disputes yield `ERR_OPEN_DISPUTES_EXIST`. Third, the `guarantee_shortfall_reserve_cents` must be exactly zero; an unpaid reserve yields `ERR_UNPAID_SHORTFALL_RESERVE`. A contract not in `PERFORMANCE` cannot close (`ERR_CONTRACT_NOT_IN_PERFORMANCE`). On close, any funding facility whose draws have been fully serviced moves to `PAID_OFF`, and the contract's `version` increments.

### 3.6. Restating the Baseline: Adjustments and the Restatement Chain

Facilities change over a decades-long guarantee — wings are added, equipment is replaced, tariffs shift — and the baseline must be able to move without breaking the ledger. An engineer proposes a baseline adjustment under the contract, naming the target `baseline_id`, a `reason` (one of `FACILITY_EXPANSION`, `FACILITY_REDUCTION`, `OCCUPANCY_CHANGE`, `EQUIPMENT_CHANGE`, or `RATE_CHANGE`), a signed `kwh_delta` (which may be negative, though the resulting `annual_energy_kwh` must remain greater than zero), and an optional `occupancy_factor_override` (greater than zero and at most 1 when present). The adjustment also carries a `supersedes_adjustment_id`: `null` for the first adjustment on a baseline, otherwise the `id` of the latest approved adjustment on that baseline — the adjustments form a self-referential restatement chain. A new adjustment is `PROPOSED`.

Approving an adjustment is an owner action with a strict precondition stack: the adjustment must be `PROPOSED` (`ERR_ADJUSTMENT_NOT_PROPOSED`); the referenced baseline must be `LOCKED` or `RESTATED` (`ERR_BASELINE_NOT_LOCKED`); the `supersedes_adjustment_id` must be `null` or equal the latest approved adjustment on that baseline — a chain break is rejected with `ERR_STALE_ADJUSTMENT_CHAIN`; the OCC guard of §2.7 applies, so the request must carry an integer `expected_baseline_version` — a missing or non-integer value is `ERR_INVALID_REQUEST` (HTTP 400) — matching the baseline's current `version` or the approval fails with `ERR_STALE_VERSION` (HTTP 412); and the resulting `annual_energy_kwh` after applying `kwh_delta` must remain greater than zero, else `ERR_BASELINE_WOULD_GO_NONPOSITIVE` (HTTP 422). An owner may instead reject a proposed adjustment (`ERR_ADJUSTMENT_NOT_PROPOSED` if it has left `PROPOSED`).

An approved adjustment restates its baseline. The baseline moves from `LOCKED` or `RESTATED` to `RESTATED`; its `version_tag` — a restatement counter that starts at 1 — increments by 1; its `annual_energy_kwh` absorbs the `kwh_delta`; if the adjustment carried an `occupancy_factor_override`, that value replaces the baseline's `occupancy_factor`; and the baseline's `version` increments. The restated `adjusted_annual_cost_cents` is then recomputed with the same tiered procedure as at submission: the heating and cooling deviation factors compare against the baseline's stored pre-adjustment degree days — and since adjustments never change the stored degree days, both weather factors evaluate to exactly 1 at restatement — while the occupancy factor uses the post-restatement `occupancy_factor`, so a restatement that changes rates or occupancy produces a different adjusted cost than a naive recompute would. The cascade continues outward: every savings report of the contract currently in `SUBMITTED` or `ATTESTED` state has its `verified_savings_cents` and `shortfall_cents` recomputed against the restated baseline, while `RECONCILED` reports are not reopened and `DISPUTED` reports are not reopened; and the contract's `cumulative_verified_savings_cents` is re-derived over the `RECONCILED` reports only. This cascade refreshes the contract's `updated_at` but does not increment the contract's `version`.

### 3.7. Savings Disputes: Filing, Escalation, Resolution, Withdrawal

Either side may contest a report's savings figure, and which side may file depends on where the report stands. While a report is `SUBMITTED`, an `OwnerRep` may file a dispute against it (`ERR_REPORT_NOT_SUBMITTED` if it has moved on); once the report is `ATTESTED`, an `ESCOEngineer` may file instead (`ERR_REPORT_NOT_ATTESTED` if it is not attested). Filing supplies the disputed `report_id` — which must equal the report named in the path, else `ERR_REFERENCED_RESOURCE_NOT_FOUND` — and the filer's counter-claim `claimed_savings_cents` (zero or greater). The filing creates a dispute notice in `OPEN` state with `filed_by_role` derived from the caller: `OWNER` for an owner rep, `ESCO` for an engineer; simultaneously the report moves to `DISPUTED`.

An owner may escalate an open dispute to `ESCALATED` (`ERR_DISPUTE_NOT_OPEN` otherwise). Resolution belongs to the `LenderOfficer`, from either `OPEN` or `ESCALATED` (`ERR_DISPUTE_NOT_OPEN` from any other state): the lender supplies a `resolution_savings_cents` of zero or greater (a negative value is `ERR_INVALID_REQUEST`), the dispute moves to `RESOLVED`, and the report returns from `DISPUTED` to `ATTESTED` with its `verified_savings_cents` set to the resolution figure, its `shortfall_cents` recomputed accordingly, and its `attested_by_owner_rep_id` restored to the value it held before the dispute was filed.

The filer — and only the filer's side — may withdraw an open dispute: an `OWNER`-filed dispute is withdrawn by an `OwnerRep`, an `ESCO`-filed dispute by an `ESCOEngineer`, and a withdrawal attempted by the wrong side fails with `ERR_INSUFFICIENT_PERMISSIONS`; this side check is evaluated before the state check. Withdrawal requires the dispute in `OPEN` (`ERR_DISPUTE_NOT_OPEN` otherwise) and moves it to `WITHDRAWN`; the report then returns to the state it held before the dispute — `SUBMITTED` if the dispute was filed pre-attestation, `ATTESTED` if filed afterward — with its `attested_by_owner_rep_id` restored to its pre-dispute value.

### 3.8. Reading the Portfolio: Nested and Cross-Contract Views

Every entity in the contract tree is readable both through its nested path and, for most collections, through a top-level filtered listing. Nested listings sit beneath their parents: baselines, bundles, phases, reports, adjustments, and disputes beneath a contract; measures beneath a bundle; draws beneath a facility; disruption logs beneath a phase. Cross-cutting listings span the portfolio: baselines, bundles, measures, facilities, draws, phases, disruptions, reports, adjustments, and disputes are each listable across contracts, with filters such as `contract_id`, `bundle_id`, `facility_id`, `phase_id`, `report_id`, `baseline_id`, and `supersedes_adjustment_id` narrowing the set as the endpoint table indicates. The contract listing itself can be narrowed by `status` or by the pinned `executed_baseline_id`, and the cross-contract measures listing accepts a `contract_id` filter that resolves against each measure's denormalized contract reference. The report listing additionally filters by `attested_by_owner_rep_id`, and a reverse lookup lists all reports attested by a given owner representative. All of these listings follow the pagination and sorting contract of §2.3 and are available to all four roles. Top-level lookups for which no dedicated not-found error exists — an unregistered owner representative or ESCO engineer fetched by id, a disruption log fetched by id, and the attested-reports reverse lookup for an unregistered owner representative — fail with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404).

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`. State transitions and other modifications return HTTP 200 with the updated resource. All responses use the envelope of §2.2; all list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock (default before any call: exactly 2026-09-01T00:00:00Z; never falls back to wall-clock) | PlatformAdmin |
| POST | `/owner-reps` | Register an owner representative | PlatformAdmin |
| GET | `/owner-reps/{ownerRepId}` | Get an owner rep | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/esco-engineers` | Register an ESCO engineer | PlatformAdmin |
| GET | `/esco-engineers/{engineerId}` | Get an ESCO engineer | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts` | Create a performance contract in AUDIT | ESCOEngineer |
| GET | `/performance-contracts` | List contracts (filters: status, executed_baseline_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}` | Get a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/complete-audit` | AUDIT → SCOPED; pins executed_baseline_id | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/execute` | SCOPED → EXECUTED; locks baseline, activates bundles | OwnerRep |
| POST | `/performance-contracts/{contractId}/mobilize` | EXECUTED → CONSTRUCTION; facility APPROVED → FUNDING | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/commence-performance` | CONSTRUCTION → PERFORMANCE | OwnerRep |
| POST | `/performance-contracts/{contractId}/close` | PERFORMANCE → CLOSED | OwnerRep |
| POST | `/performance-contracts/{contractId}/terminate` | AUDIT/SCOPED → TERMINATED; cascades bundles, measures, facilities | OwnerRep |
| POST | `/performance-contracts/{contractId}/baselines` | Create a baseline (DRAFT) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/baselines` | List baselines of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/baselines/{baselineId}` | Get a baseline | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/baselines/{baselineId}/submit` | Baseline DRAFT → SUBMITTED; computes adjusted_annual_cost_cents | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/baselines/{baselineId}/approve` | Baseline SUBMITTED → APPROVED | OwnerRep |
| POST | `/performance-contracts/{contractId}/baselines/{baselineId}/reject` | Baseline SUBMITTED → REJECTED | OwnerRep |
| POST | `/performance-contracts/{contractId}/bundles` | Create a measure bundle (DRAFT) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/bundles` | List bundles of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/bundles/{bundleId}` | Get a bundle | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/propose` | Bundle DRAFT → PROPOSED; recomputes blended payback and subsidy pool | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/approve` | Bundle PROPOSED → APPROVED; measures INCLUDED, subsidy waterfall assigned | OwnerRep |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/withdraw` | Bundle DRAFT/PROPOSED → WITHDRAWN; measures EXCLUDED | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/measures` | Create a measure (PROPOSED) in a bundle | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/bundles/{bundleId}/measures` | List measures of a bundle | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/bundles/{bundleId}/measures/{measureId}` | Get a measure | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/measures` | Filtered list of measures across the contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/measures/{measureId}/exclude` | Measure PROPOSED/INCLUDED → EXCLUDED; waterfall re-run | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/measures/{measureId}/install` | Measure INCLUDED → INSTALLED | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/bundles/{bundleId}/measures/{measureId}/verify` | Measure INSTALLED → VERIFIED; bundle may auto-complete | OwnerRep |
| POST | `/performance-contracts/{contractId}/financing-facilities` | Create a financing facility (DRAFT) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/financing-facilities` | List facilities of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/financing-facilities/{facilityId}` | Get a facility | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/submit` | Facility DRAFT → SUBMITTED; computes annual_payment_cents and coverage_ratio | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/approve` | Facility SUBMITTED → APPROVED | LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/cancel` | Facility DRAFT/SUBMITTED → CANCELLED; REQUESTED draws rejected | LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/payoff` | Facility FUNDING → PAID_OFF | OwnerRep |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/draws` | Request a draw (REQUESTED) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/draws` | List draws of a facility | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/draws/{drawId}/approve` | Draw REQUESTED → APPROVED | LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/draws/{drawId}/release` | Draw APPROVED → RELEASED; adds to drawn_cents | LenderOfficer |
| POST | `/performance-contracts/{contractId}/financing-facilities/{facilityId}/draws/{drawId}/reject` | Draw REQUESTED → REJECTED | LenderOfficer |
| POST | `/performance-contracts/{contractId}/phases` | Create a work phase (PLANNED) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/phases` | List phases of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/phases/{phaseId}` | Get a phase | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/phases/{phaseId}/mobilize` | Phase PLANNED → MOBILIZED; window overlap check | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/phases/{phaseId}/start` | Phase MOBILIZED/SUSPENDED → IN_PROGRESS | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/phases/{phaseId}/complete` | Phase IN_PROGRESS → COMPLETE | OwnerRep |
| POST | `/performance-contracts/{contractId}/phases/{phaseId}/suspend` | Phase IN_PROGRESS → SUSPENDED | OwnerRep |
| POST | `/performance-contracts/{contractId}/phases/{phaseId}/disruptions` | Log a disruption against a phase; budget enforcement | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/phases/{phaseId}/disruptions` | List disruptions of a phase | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/reports` | Create a savings report (DRAFT) for a guarantee year | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/reports` | List reports of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/reports/{reportId}` | Get a report | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/reports/{reportId}/submit` | Report DRAFT → SUBMITTED; savings verification computed | ESCOEngineer |
| POST | `/performance-contracts/{contractId}/reports/{reportId}/attest` | Report SUBMITTED → ATTESTED; records attesting owner rep | OwnerRep |
| POST | `/performance-contracts/{contractId}/reports/{reportId}/reconcile` | Report ATTESTED → RECONCILED; OCC on contract version | OwnerRep |
| POST | `/performance-contracts/{contractId}/reports/{reportId}/disputes` | File a dispute on a SUBMITTED or ATTESTED report | OwnerRep, ESCOEngineer |
| POST | `/performance-contracts/{contractId}/baseline-adjustments` | Propose a baseline adjustment (PROPOSED) | ESCOEngineer |
| GET | `/performance-contracts/{contractId}/baseline-adjustments` | List adjustments of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/baseline-adjustments/{adjustmentId}` | Get an adjustment | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/baseline-adjustments/{adjustmentId}/approve` | Adjustment PROPOSED → APPROVED; OCC on baseline version; restates baseline | OwnerRep |
| POST | `/performance-contracts/{contractId}/baseline-adjustments/{adjustmentId}/reject` | Adjustment PROPOSED → REJECTED | OwnerRep |
| GET | `/performance-contracts/{contractId}/disputes` | List disputes of a contract | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/performance-contracts/{contractId}/disputes/{disputeId}` | Get a dispute | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| POST | `/performance-contracts/{contractId}/disputes/{disputeId}/escalate` | Dispute OPEN → ESCALATED | OwnerRep |
| POST | `/performance-contracts/{contractId}/disputes/{disputeId}/resolve` | Dispute OPEN/ESCALATED → RESOLVED; sets report verified savings | LenderOfficer |
| POST | `/performance-contracts/{contractId}/disputes/{disputeId}/withdraw` | Dispute OPEN → WITHDRAWN; filer side only | OwnerRep, ESCOEngineer |
| GET | `/baselines` | Filtered list of baselines across contracts (filter: contract_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/baselines/{baselineId}` | Get a baseline by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/bundles` | Filtered list of bundles across contracts (filter: contract_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/bundles/{bundleId}` | Get a bundle by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/measures` | Filtered list of measures across bundles (filters: bundle_id, contract_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/measures/{measureId}` | Get a measure by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/financing-facilities` | Filtered list of financing facilities across contracts (filter: contract_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/financing-facilities/{facilityId}` | Get a facility by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/financing-draws` | Filtered list of draws across facilities (filter: facility_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/financing-draws/{drawId}` | Get a draw by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/phases` | Filtered list of work phases across contracts (filter: contract_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/phases/{phaseId}` | Get a phase by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/disruptions` | Filtered list of disruption logs across phases (filter: phase_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/disruptions/{disruptionId}` | Get a disruption log by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/reports` | Filtered list of savings reports across contracts (filters: contract_id, attested_by_owner_rep_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/reports/{reportId}` | Get a savings report by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/baseline-adjustments` | Filtered list of baseline adjustments across contracts (filters: contract_id, baseline_id, supersedes_adjustment_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/baseline-adjustments/{adjustmentId}` | Get a baseline adjustment by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/disputes` | Filtered list of disputes across contracts (filters: contract_id, report_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/disputes/{disputeId}` | Get a dispute by id | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |
| GET | `/owner-reps/{ownerRepId}/attested-reports` | Reports attested by an owner rep (reverse lookup on attested_by_owner_rep_id) | PlatformAdmin, OwnerRep, ESCOEngineer, LenderOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_BASELINE_NOT_FOUND | 404 |
| ERR_BUNDLE_NOT_FOUND | 404 |
| ERR_MEASURE_NOT_FOUND | 404 |
| ERR_FACILITY_NOT_FOUND | 404 |
| ERR_DRAW_NOT_FOUND | 404 |
| ERR_PHASE_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_ADJUSTMENT_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_REFERENCED_RESOURCE_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_IN_AUDIT | 409 |
| ERR_CONTRACT_NOT_SCOPABLE | 409 |
| ERR_CONTRACT_NOT_SCOPED | 409 |
| ERR_CONTRACT_NOT_EXECUTED | 409 |
| ERR_CONTRACT_NOT_IN_CONSTRUCTION | 409 |
| ERR_CONTRACT_NOT_IN_PERFORMANCE | 409 |
| ERR_CONTRACT_NOT_TERMINABLE | 409 |
| ERR_CONTRACT_LOCKED | 409 |
| ERR_BASELINE_NOT_APPROVED | 409 |
| ERR_BASELINE_NOT_DRAFT | 409 |
| ERR_BASELINE_NOT_SUBMITTED | 409 |
| ERR_BASELINE_NOT_LOCKED | 409 |
| ERR_BASELINE_WOULD_GO_NONPOSITIVE | 422 |
| ERR_NO_MEASURES_IDENTIFIED | 409 |
| ERR_NO_APPROVED_BUNDLE | 409 |
| ERR_NO_APPROVED_FINANCING | 409 |
| ERR_BUNDLE_PAYBACK_EXCEEDS_TERM | 422 |
| ERR_BUNDLE_NOT_DRAFT | 409 |
| ERR_BUNDLE_NOT_PROPOSED | 409 |
| ERR_BUNDLE_NOT_WITHDRAWABLE | 409 |
| ERR_BUNDLE_EMPTY | 409 |
| ERR_MEASURE_NOT_EXCLUDABLE | 409 |
| ERR_MEASURE_NOT_INCLUDED | 409 |
| ERR_MEASURE_NOT_INSTALLED | 409 |
| ERR_MEASURES_UNVERIFIED | 409 |
| ERR_NO_MOBILIZED_PHASE | 409 |
| ERR_PHASES_INCOMPLETE | 409 |
| ERR_PHASE_NOT_PLANNED | 409 |
| ERR_PHASE_NOT_MOBILIZED | 409 |
| ERR_PHASE_NOT_IN_PROGRESS | 409 |
| ERR_PHASE_WINDOW_OVERLAP | 409 |
| ERR_PHASE_WINDOW_NOT_STARTED | 409 |
| ERR_PHASE_WINDOW_CLOSED | 409 |
| ERR_PHASE_OVERRUN | 409 |
| ERR_NO_ACTIVE_PHASE_WINDOW | 409 |
| ERR_DISRUPTION_BUDGET_EXCEEDED | 422 |
| ERR_DISRUPTION_OUTSIDE_WINDOW | 422 |
| ERR_FACILITY_NOT_DRAFT | 409 |
| ERR_FACILITY_NOT_SUBMITTED | 409 |
| ERR_FACILITY_NOT_CANCELLABLE | 409 |
| ERR_FACILITY_NOT_FUNDING | 409 |
| ERR_FACILITY_TERM_NOT_ELAPSED | 422 |
| ERR_COVERAGE_BELOW_ONE | 422 |
| ERR_DRAW_NOT_REQUESTED | 409 |
| ERR_DRAW_NOT_APPROVED | 409 |
| ERR_DRAW_EXCEEDS_AVAILABLE | 422 |
| ERR_REPORT_NOT_DRAFT | 409 |
| ERR_REPORT_NOT_SUBMITTED | 409 |
| ERR_REPORT_NOT_ATTESTED | 409 |
| ERR_PERIOD_NOT_ENDED | 422 |
| ERR_DUPLICATE_REPORT_PERIOD | 409 |
| ERR_ADJUSTMENT_NOT_PROPOSED | 409 |
| ERR_STALE_ADJUSTMENT_CHAIN | 409 |
| ERR_DISPUTE_NOT_OPEN | 409 |
| ERR_RECONCILIATION_INCOMPLETE | 409 |
| ERR_OPEN_DISPUTES_EXIST | 409 |
| ERR_UNPAID_SHORTFALL_RESERVE | 409 |
| ERR_GUARANTEE_PERIOD_NOT_STARTED | 422 |
