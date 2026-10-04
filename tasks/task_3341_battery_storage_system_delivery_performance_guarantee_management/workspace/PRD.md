# Battery Storage Guarantees API — Product Requirements Document

## 1. Introduction

Utility-scale battery storage projects are financed on the strength of guarantees: a guaranteed usable capacity at the point of interconnection, a guaranteed round-trip efficiency, a guaranteed delivery date backed by liquidated damages, and a long-term service agreement that keeps the asset inside its warranty envelope for a decade or more. Each guarantee is only as good as the paper trail behind it — the sizing study that justified the nameplate, the safety permits that unlocked contract execution, the commissioning milestone that set the capacity baseline, the periodic capacity and efficiency tests that measure degradation, and the augmentation events that add cells to hold the guaranteed line. When any of these records disagree, owners and suppliers argue from different versions of the truth, and settlement becomes negotiation instead of arithmetic.

This document specifies a Battery Storage System Delivery & Performance Guarantee Management API that makes that paper trail executable. The system tracks projects from scoping (power and energy sizing against the intended market application and duty cycle) through equipment supply agreements with delivery schedules, commissioning milestones and liquidated damages; capacity and round-trip efficiency guarantees measured through periodic testing protocols; augmentation planning that adds cells over time to hold guaranteed capacity as the system degrades; long-term service agreements covering monitoring, maintenance, spare parts and software updates; safety permitting for thermal runaway mitigation, fire code compliance and local approval; market bidding integration with dispatch optimization; and warranty claim handling with cell-replacement logistics. All monetary amounts are carried in integer cents, and every date comparison in the system is evaluated against a controllable logical clock so that window checks, term checks and lateness calculations are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but not permitted for the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The declared roles are exactly: `PlatformAdmin`, `ProjectDeveloper`, `PerformanceEngineer`, `ServiceManager`, `ServiceEngineer`, `WarrantyAdmin`, `SafetyAuthority`, and `MarketOperator`.

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `PlatformAdmin`, `ProjectDeveloper`, `PerformanceEngineer`, `ServiceManager`, `ServiceEngineer`, `WarrantyAdmin`, `SafetyAuthority`, or `MarketOperator`, the server may record the identifier in audit contexts but never compares it to any entity's `id`; authorization is decided by role alone. Broadly: `PlatformAdmin` drives the logical clock and can read everything; `ProjectDeveloper` scopes projects, creates and executes equipment supply agreements, schedules milestones and permits, records milestone outcomes and waives liquidated damages; `PerformanceEngineer` schedules and records performance tests; `ServiceManager` owns the service-agreement lifecycle and can order and cancel spare parts; `ServiceEngineer` plans and executes augmentations and moves spare-part orders through shipment, delivery and installation; `WarrantyAdmin` files, reviews and decides warranty claims; `SafetyAuthority` decides safety permits; `MarketOperator` opens, clears, settles and cancels bid sessions. All roles may use every read endpoint.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. All list endpoints sort by `created_at` ascending.

### 2.4. The Logical Clock

The system never reads wall-clock time for business decisions. A logical clock governs every date comparison in the platform: test windows, augmentation windows, service-agreement term checks, milestone lateness, and lazy service-agreement expiry. Before any call has set it, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the new clock reading as `current_utc`. Advancing the clock does not itself rewrite any agreement; the effects of crossing an `end_date` materialize lazily on the next read or write that touches the agreement, as described in §3.6.

### 2.5. Common Resource Properties

Every entity in the system carries the same four system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits, fixed at creation; `updated_at`, refreshed on every mutation; and `version`, an integer that increments by one on every mutation of the entity. Mutations that cascade into a parent entity — for example, executing an equipment supply agreement — also increment the parent's `version` and refresh its `updated_at`, because those parent fields are recomputed from child state.

### 2.6. Optimistic Concurrency Control

Three write operations guard against stale parent state with an optimistic-concurrency field:

- Executing an equipment supply agreement requires `expected_project_version`, carrying the client's last observed `version` of the parent project. If the project's current `version` has advanced since that read — for example because a sibling agreement was executed or a milestone outcome recomputed the project's capacity fields — the execution is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).
- Executing an augmentation event requires `expected_project_version` against the parent project, rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) on mismatch, since the event's effect on `projected_capacity_mwh` and `augmentation_count` must not overwrite a capacity baseline the client has not observed.
- Creating a spare-part order requires `expected_service_agreement_version`, carrying the client's last observed `version` of the parent service agreement. A mismatch is rejected with `ERR_STALE_LTSA_VERSION` (HTTP 412), forcing a fresh read of the credit-pool balance before credit is drawn.

Endpoints not listed above do not take a version field. The stale-version check is evaluated after existence resolution but before any business validation.

### 2.7. Monetary Amounts, Capacities, and Rounding

All monetary quantities are integer cents; no fractional cents exist anywhere in the system. Energy capacities and durations are expressed to 2 decimal places, rounded half up; this applies to `duration_hours`, `total_price_cents`'s energy operand, `evaluated_capacity_mwh`, `projected_capacity_mwh`, `added_capacity_mwh`, and `cleared_mwh`. Round-trip efficiency ratios are expressed to 4 decimal places, rounded half up. Where a calculation specifies a single final rounding, the full expression is evaluated in exact arithmetic and rounded once at the end; no intermediate rounding is permitted.

### 2.8. Validation Priority Order

When a request could fail more than one check, checks are evaluated in this fixed order, and the first failure wins:

1. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence: every resource id in the path and every foreign-key id in the body must resolve, validated left-to-right with path segments before body fields (`ERR_NOT_FOUND` for path segments; the resource-specific not-found ids for body foreign keys). Pure creation-time shape errors — missing required fields, invalid enum values, non-positive quantities, violated input constraints on a create payload — are also detected at this stage, so a malformed create is rejected with `ERR_INVALID_REQUEST` and never reaches a state check.
4. Optimistic concurrency: the declared `expected_project_version` or `expected_service_agreement_version` must equal the parent's current `version` (`ERR_STALE_PROJECT_VERSION`, `ERR_STALE_LTSA_VERSION`).
5. State-machine legality: the target resource must be in a state from which the requested transition exists (the `ERR_*_NOT_*` family, HTTP 409).
6. Safety gating: the permit-approval requirement on contract execution (`ERR_PERMIT_MISSING_OR_UNAPPROVED`).
7. Temporal windows: test windows, augmentation windows, service-term membership, and milestone outcome/date agreement (`ERR_TEST_WINDOW_NOT_OPEN`, `ERR_AUGMENTATION_WINDOW_NOT_OPEN`, `ERR_LTSA_NOT_IN_TERM`, `ERR_MILESTONE_OUTCOME_MISMATCH`).
8. Structural integrity: window overlap, window ordering, sizing validity, guarantee-versus-rated-energy, and commissioning prerequisites (`ERR_TEST_WINDOW_OVERLAP`, `ERR_BID_WINDOW_OVERLAP`, `ERR_INVALID_WINDOW`, `ERR_SIZING_INVALID`, `ERR_GUARANTEE_EXCEEDS_RATED_ENERGY`, `ERR_PROJECT_NOT_COMMISSIONED`).
9. Cross-entity state references: linked-claim fulfillability, agreement state for claim decisions and milestone scheduling, delivery/commissioning completeness for contract completion, and the active-agreement requirement on guarantee evaluation (`ERR_CLAIM_NOT_FULFILLABLE`, `ERR_ESA_NOT_EXECUTABLE_STATE`, `ERR_DELIVERY_MILESTONES_OPEN`, `ERR_NO_COMMISSIONING_ACHIEVED`, `ERR_NO_ACTIVE_ESA`).
10. Fiscal checks, which are always last: owner budget, spare-parts credit headroom, and waiver headroom (`ERR_BUDGET_EXCEEDED`, `ERR_CREDIT_POOL_EXHAUSTED`, `ERR_WAIVER_EXCEEDS_ACCRUED`, all HTTP 402).

One refinement: request-shape checks on operation payloads — for example an invalid `outcome` enum on a milestone outcome recording, or malformed `rte_intervals` on a results recording (`ERR_INVALID_REQUEST`, `ERR_INVALID_RTE_INTERVALS`, HTTP 400) — are evaluated after the state and business checks above, unlike the creation-time shape errors handled at step 3.

### 2.9. Nested Resources and Lookup Discipline

Resources reference one another through foreign-key fields in request bodies — a payload containing `project_id`, `esa_id`, `service_agreement_id`, or `warranty_claim_id` names the parent it attaches to. Every such reference must resolve to an existing resource, and the specific not-found error identifies which reference failed: `ERR_PROJECT_NOT_FOUND`, `ERR_ESA_NOT_FOUND`, `ERR_LTSA_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_AUGMENTATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, or `ERR_BID_SESSION_NOT_FOUND`. An unresolvable id in the URL path itself yields the generic `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Project Scoping and Sizing Validation

A `ProjectDeveloper` opens a new engagement by creating a project with a `name`, a `market_application` of `ENERGY_ARBITRAGE`, `FREQUENCY_REGULATION`, or `CAPACITY_FIRMING`, a `duty_cycle_profile` of `ONE_CYCLE_DAILY`, `TWO_CYCLES_DAILY`, or `CONTINUOUS`, a `rated_power_mw` and `rated_energy_mwh` that must both be greater than zero, and a `budget_cents` cap that later constrains contract execution. Two derived attributes appear immediately on the created project. `duration_hours` is the nameplate energy divided by the nameplate power, rounded half up to 2 decimal places. `sizing_status` is either `VALID` or `INVALID`, decided by the market application: a `CAPACITY_FIRMING` project is `VALID` only when its duration is at least 4.00 hours and its duty cycle is `ONE_CYCLE_DAILY` — the boundary is inclusive, so exactly 4.00 hours passes while 3.99 fails; a `FREQUENCY_REGULATION` project is `VALID` only when its duty cycle is `CONTINUOUS`; an `ENERGY_ARBITRAGE` project is `VALID` only when its duration is at least 2.00 hours and its duty cycle is anything other than `CONTINUOUS`. The sizing verdict is computed at creation and whenever the market application or duty cycle changes; it gates contract execution later.

A project also carries a commissioning baseline `commissioned_capacity_mwh`, initially zero; a most-recent `equivalent_cycles` count, initially zero; a forward-looking `projected_capacity_mwh`; and an `augmentation_count` of its augmentation events in `PLANNED` or `EXECUTED` status. Either a `ProjectDeveloper` or a `PerformanceEngineer` may ask the system to recompute the projection for a supplied `equivalent_cycles` value; the supplied count is stored and `projected_capacity_mwh` is recomputed per the degradation model in §3.5.

### 3.2. Safety Permitting and the Path to Contract Execution

Before any equipment supply agreement can be executed, the project must clear three safety gates. A `ProjectDeveloper` submits safety permits, each carrying the `project_id`, a `permit_type` of `THERMAL_RUNAWAY_PLAN`, `FIRE_CODE`, or `LOCAL_APPROVAL`, and a free-text `authority_reference` naming the approving authority. A new permit is `SUBMITTED`. A `SafetyAuthority` then decides it: approval moves the permit to `APPROVED`, rejection moves it to `REJECTED`, and either decision stamps `decided_at` with the current logical-clock reading; a decide on a permit that is not `SUBMITTED` is refused with `ERR_PERMIT_NOT_PENDING`. A rejected permit is not dead — the developer may resubmit it, cycling `REJECTED` back to `SUBMITTED` with `decided_at` cleared to null, and there is no bound on the number of resubmission cycles; resubmitting a permit that is not `REJECTED` is refused with `ERR_PERMIT_NOT_REJECTED`. Execution of an agreement is blocked until all three permit types exist for the project in `APPROVED` status; the block surfaces as `ERR_PERMIT_MISSING_OR_UNAPPROVED`.

With permits in hand, the developer drafts the equipment supply agreement. The create payload names the `project_id`, the `contracted_power_mw` and `contracted_energy_mwh` (both greater than zero), a `guaranteed_capacity_mwh` that must be greater than zero and no larger than `contracted_energy_mwh`, a `guaranteed_rte_pct` expressed as a fraction greater than zero and at most one, a non-negative `price_per_mwh_cents`, non-negative `ld_rate_per_day_cents` and `ld_cap_cents`, and the `guaranteed_delivery_date` together with a `longstop_date` that must fall strictly after it. Violating any of these input constraints is a creation-time `ERR_INVALID_REQUEST`. The agreement's `total_price_cents` is computed at creation as the contracted energy — rounded to 2 decimal places first — multiplied by the unit price, kept as integer cents. The agreement starts `DRAFT`, with `accrued_ld_cents`, `waived_ld_cents`, and `net_ld_due_cents` all zero.

Executing the agreement is the point of no return, and its preconditions are evaluated in the fixed order of §2.8: the agreement must be `DRAFT` (otherwise `ERR_ESA_NOT_DRAFT`); all three permit types must be `APPROVED` (otherwise `ERR_PERMIT_MISSING_OR_UNAPPROVED`); the project's `sizing_status` must be `VALID` (otherwise `ERR_SIZING_INVALID`); `guaranteed_capacity_mwh` must not exceed the project's `rated_energy_mwh` (otherwise `ERR_GUARANTEE_EXCEEDS_RATED_ENERGY`); and finally `total_price_cents` must not exceed the project's `budget_cents` (otherwise `ERR_BUDGET_EXCEEDED`). The execution request must also carry `expected_project_version` per §2.6, and a successful execution increments the project's `version` by one, because downstream capacity bookkeeping keys off the execution event.

### 3.3. Delivery Milestones, Liquidated Damages, and Contract Termination

Once an agreement is `EXECUTED`, the developer schedules delivery milestones against it by supplying the `esa_id`, a `kind` of `DELIVERY` or `COMMISSIONING`, and a `planned_date`; scheduling against an agreement that is not in an executable state is refused with `ERR_ESA_NOT_EXECUTABLE_STATE`. Each milestone starts `SCHEDULED` with `days_late`, `ld_applied_cents`, and `ld_waived_cents` all zero — the last of these records liquidated-damages amounts waived in association with that milestone.

Recording the outcome of a milestone takes an `outcome` of `ACHIEVED` or `MISSED` and the `actual_date`. The milestone must still be `SCHEDULED` (`ERR_MILESTONE_NOT_SCHEDULED`), and the outcome must agree with the calendar: `ACHIEVED` requires the actual date to fall on or before the planned date, and `MISSED` requires it to fall strictly after; a disagreement is `ERR_MILESTONE_OUTCOME_MISMATCH`. An on-time recording sets `days_late` to zero and applies no damages. A late recording sets `days_late` to the count of whole calendar days after the planned date up to and including the actual date — any crossing into a new calendar day counts as a full day — and accrues liquidated damages under the cap-aware rule below. The first `COMMISSIONING` milestone recorded `ACHIEVED` also writes the project's commissioning baseline: if `commissioned_capacity_mwh` is still zero, it is set to the agreement's `contracted_energy_mwh` and the capacity projection of §3.5 is recomputed.

Liquidated damages accrue in the exact order outcomes are recorded, each accrual observing the cap headroom left by all prior accruals. For a missed milestone, the headroom is `ld_cap_cents` minus the agreement's current `accrued_ld_cents`; the effective chargeable days are the lesser of `days_late` and the whole-day count that fits in the headroom at `ld_rate_per_day_cents` per day (zero effective days when the daily rate is zero); and `ld_applied_cents` is the effective days multiplied by the daily rate. That amount is added to the agreement's `accrued_ld_cents`, and `net_ld_due_cents` is recomputed as accrued minus waived. The terminal boundary is exact equality: when `accrued_ld_cents` reaches `ld_cap_cents` and the cap is greater than zero, the agreement automatically transitions from `EXECUTED` to `TERMINATED`, and the termination cascades — every still-`SCHEDULED` milestone of the agreement becomes `CANCELLED`; every spare-part order in `ORDERED` status whose `warranty_claim_id` references a warranty claim of this agreement becomes `CANCELLED`, with any credit-covered order returning its draw to the service agreement's `credit_drawn_cents`; and every warranty claim of the agreement in `SUBMITTED` or `UNDER_REVIEW` becomes `REJECTED`.

A developer may also cancel a milestone outright while it is `SCHEDULED`, provided the agreement is `DRAFT` or `EXECUTED` — cancelling against a terminal agreement is refused with `ERR_ESA_TERMINAL_MILESTONE_LOCKED` — and a cancelled milestone leaves all liquidated-damages fields untouched. Separately, the developer may waive accrued damages on a non-`DRAFT` agreement by supplying an `amount_cents`; the waiver must not exceed accrued minus already-waived, or the request fails with `ERR_WAIVER_EXCEEDS_ACCRUED`. Partial waivers are allowed, each adding to `waived_ld_cents` and recomputing `net_ld_due_cents`.

Completion of the agreement closes the commercial phase: every `DELIVERY` milestone must be `ACHIEVED` or `CANCELLED` (otherwise `ERR_DELIVERY_MILESTONES_OPEN`), and at least one `COMMISSIONING` milestone must be `ACHIEVED` (otherwise `ERR_NO_COMMISSIONING_ACHIEVED`); an agreement not in `EXECUTED` is refused with `ERR_ESA_NOT_EXECUTABLE_STATE`. On completion the project's `commissioned_capacity_mwh` is reconciled to the agreement's `contracted_energy_mwh`, matching what the first commissioning achievement set earlier.

### 3.4. Performance Testing and Guarantee Evaluation

A `PerformanceEngineer` schedules periodic guarantee tests against any project that has an agreement in `EXECUTED` or `COMPLETED` status — scheduling without one is refused with `ERR_NO_ACTIVE_ESA`. The create payload carries the `project_id`, a `test_type` of `CAPACITY_TEST` or `RTE_TEST`, and a window from `window_start` (inclusive) to `window_end` (exclusive); an end not strictly after the start is `ERR_INVALID_WINDOW`. Windows are half-open, so two tests on the same project may touch but never overlap: any overlap among tests in `SCHEDULED`, `PASSED`, or `FAILED` status on the same project is rejected with `ERR_TEST_WINDOW_OVERLAP`. The system derives `measurement_basis` at scheduling time: `NAMEPLATE` for `FREQUENCY_REGULATION` projects, `POI` for everything else. A scheduled test may be cancelled while `SCHEDULED`; anything else is `ERR_TEST_NOT_SCHEDULED`.

Results are recorded inside the window — the logical clock must read at or after `window_start` and strictly before `window_end`, else `ERR_TEST_WINDOW_NOT_OPEN`, and the test must still be `SCHEDULED`. For a `CAPACITY_TEST`, the engineer supplies `measured_capacity_mwh` and `aux_load_mwh`. Under the `POI` basis the auxiliary load is subtracted, so `evaluated_capacity_mwh` is the measured discharge energy minus the auxiliary load; under the `NAMEPLATE` basis the auxiliary load is ignored and the evaluated capacity equals the raw measurement. Either way the evaluated value is rounded half up to 2 decimal places, and the test `result` is `PASS` when the evaluated capacity is greater than or equal to the active agreement's `guaranteed_capacity_mwh` — equality passes — and `FAIL` otherwise. Recording results requires the project to have an agreement in `EXECUTED` or `COMPLETED`, else `ERR_NO_ACTIVE_ESA`.

For an `RTE_TEST`, the engineer instead supplies `rte_intervals`, a list of charge/discharge pairs — each element with `charge_mwh` greater than zero and `discharge_mwh` greater than or equal to zero, and the list must contain at least one element; a missing, empty, or non-positive-charge list is `ERR_INVALID_RTE_INTERVALS`. The measured efficiency `measured_rte_pct` is the total discharge energy summed over all intervals divided by the total charge energy summed over all intervals, rounded half up to 4 decimal places — intervals are aggregated as energy sums, never as an average of per-interval ratios. The test passes when `measured_rte_pct` is greater than or equal to the agreement's `guaranteed_rte_pct`, again with equality passing.

A recorded test ends with its `status` at `PASSED` or `FAILED` according to its `result`. A failed `CAPACITY_TEST` has one further consequence: the system automatically creates an augmentation event with `origin` `AUTO` in `PLANNED` status, sized and scheduled per §3.5, and recomputes the project's `projected_capacity_mwh`. A failed `RTE_TEST` creates nothing.

### 3.5. Degradation, Projection, and Augmentation Planning

The forward-looking capacity projection answers the owner's core question: will the plant still hold its guarantee? The projection starts from `commissioned_capacity_mwh`, adds the `added_capacity_mwh` of every augmentation event in `EXECUTED` status — `PLANNED` and `CANCELLED` events never contribute — and subtracts degradation of a per-cycle rate multiplied by the stored `equivalent_cycles`. The per-cycle rate depends on the project's market application and duty cycle: for `ENERGY_ARBITRAGE` it is 0.0006 under `ONE_CYCLE_DAILY`, 0.0012 under `TWO_CYCLES_DAILY`, and 0.0015 under `CONTINUOUS`; for `FREQUENCY_REGULATION` it is 0.0004, 0.0008, and 0.0010 respectively; for `CAPACITY_FIRMING` it is 0.0005, 0.0010, and 0.0012 respectively. Each executed augmentation then attracts a planning penalty: the number of executed events times 0.5 percent times the excess of the pre-penalty projection over the 80 MWh floor — nothing below the floor is penalized, and the excess is floored at zero. `projected_capacity_mwh` is the pre-penalty projection minus that penalty, rounded half up to 2 decimal places. The projection is recomputed whenever the commissioning baseline changes, whenever the executed-event set changes, and whenever `equivalent_cycles` is refreshed through the recompute capability described in §3.1.

When a capacity test fails, the shortfall is the active agreement's `guaranteed_capacity_mwh` minus the smaller of the current projection and the test's evaluated capacity. The auto-created augmentation covers that shortfall with a gross-up: the shortfall is divided by one minus the 0.5 percent penalty — pre-compensating the penalty the new event itself will attract — then rounded up to the next 0.01 MWh to produce its `added_capacity_mwh`. The event's window opens at the current logical clock and closes thirty days later, `[planned_window_start, planned_window_end)` spanning exactly that half-open interval.

A `ServiceEngineer` may also plan an augmentation manually, supplying the `project_id`, `planned_window_start`, `planned_window_end` — the end strictly after the start, else `ERR_INVALID_WINDOW` — and an `added_capacity_mwh` greater than zero. Manual planning requires the project to be commissioned, meaning `commissioned_capacity_mwh` greater than zero, else `ERR_PROJECT_NOT_COMMISSIONED`; auto-created events are exempt from this gate because the system raises them. Manual events carry `origin` `MANUAL`. Either way, a new event lands `PLANNED` and the project's `augmentation_count` is recomputed to count events in `PLANNED` or `EXECUTED` status.

Executing a planned event requires the logical clock inside its half-open window — at or after `planned_window_start` and strictly before `planned_window_end`, else `ERR_AUGMENTATION_WINDOW_NOT_OPEN` — and the event still `PLANNED`, else `ERR_AUGMENTATION_NOT_PLANNED`. The execution request carries `expected_project_version` per §2.6, rejected with `ERR_STALE_PROJECT_VERSION` on a stale read. A successful execution moves the event to `EXECUTED`, increments the project's `version` by one, and recomputes `projected_capacity_mwh` and `augmentation_count`. Cancelling a `PLANNED` event recomputes `augmentation_count` but leaves the projection untouched, since planned events never contributed to it.

### 3.6. Long-Term Service Agreements and the Spare-Parts Credit Pool

A `ServiceManager` drafts the long-term service agreement with the `project_id`, a non-negative `annual_fee_cents`, four scope flags — `covers_monitoring`, `covers_maintenance`, `covers_spare_parts`, and `covers_software_updates` — and a term from `start_date` through `end_date`, both inclusive, with the end strictly after the start (`ERR_INVALID_REQUEST` otherwise). The agreement begins `DRAFT` with `activated_at` null and both credit fields at zero.

Activation is allowed only while the logical clock sits within the inclusive term — at or after `start_date` and at or before `end_date`, else `ERR_LTSA_NOT_IN_TERM` — and only from `DRAFT`, else `ERR_LTSA_NOT_DRAFT`. First activation stamps `activated_at` with the logical clock and computes the spare-parts credit pool exactly once: `credit_pool_cents` is 30 percent of `annual_fee_cents`, rounded down to a whole cent. An active agreement may be suspended (`ACTIVE` to `SUSPENDED`; any other source state is `ERR_LTSA_NOT_ACTIVE`) and later reactivated (`SUSPENDED` to `ACTIVE`; any other source state is `ERR_LTSA_NOT_SUSPENDED`), with reactivation again requiring the clock within the term. Reactivation never recomputes the pool.

Expiry is lazy. There is no background sweeper; instead, the first read or write that touches an agreement whose `end_date` has passed — from either `ACTIVE` or `SUSPENDED` — flips it to `EXPIRED` and runs the expiry cascade: every spare-part order of the agreement in `ORDERED` or `SHIPPED` status becomes `CANCELLED`, and each credit-covered order returns its `part_cost_cents` to `credit_drawn_cents`. The pool itself is historical and is never rewritten; `credit_drawn_cents` is simply recomputed after the cascade.

### 3.7. Spare Part Orders and Warranty Claim Resolution

Spare-part logistics run under the service agreement. Creating an order names the `service_agreement_id`, an optional nullable `warranty_claim_id` linking the order to a claim, a free-text `part_description`, a non-negative `part_cost_cents`, and the `expected_service_agreement_version` guard of §2.6. The agreement must be `ACTIVE` — ordering against a suspended or expired agreement is refused with `ERR_LTSA_NOT_ACTIVE` — and a referenced claim must exist, else `ERR_CLAIM_NOT_FOUND`. When the agreement's scope includes spare parts and the remaining pool — `credit_pool_cents` minus `credit_drawn_cents` — covers the full cost, the order is marked `covered_by_credit` true and the cost is added to `credit_drawn_cents`. When the scope includes spare parts but the headroom falls short, the order is refused outright with `ERR_CREDIT_POOL_EXHAUSTED`; coverage is all-or-nothing, never partial. When the scope excludes spare parts, the order proceeds uncovered and the credit fields stay put. A successful creation increments the service agreement's `version`. The pool is a conserved quantity: it always equals the drawn amount plus what remains available, and cancelling a covered order subtracts its cost back out of `credit_drawn_cents`, returning the books to parity.

The order lifecycle walks `ORDERED` to `SHIPPED` to `DELIVERED` to `INSTALLED`, each step taken by a `ServiceEngineer` and each refusing the wrong source state with `ERR_ORDER_NOT_ORDERED`, `ERR_ORDER_NOT_DELIVERED`'s siblings `ERR_ORDER_NOT_SHIPPED`, and `ERR_ORDER_NOT_DELIVERED` respectively — ship requires `ORDERED`, deliver requires `SHIPPED`, install requires `DELIVERED`. Installation has one cross-entity dependency: when the order's `warranty_claim_id` is set, the linked claim must be `APPROVED`, else `ERR_CLAIM_NOT_FULFILLABLE`, and a successful installation drives that claim from `APPROVED` to `FULFILLED`. A `ServiceManager` may cancel an order while it is `ORDERED` or `SHIPPED` — any later state is `ERR_ORDER_NOT_CANCELLABLE` — and cancelling a covered order restores its draw as above.

Warranty claims themselves are filed by a `WarrantyAdmin` against an agreement in `EXECUTED` or `COMPLETED` status — filing against any other state is refused with `ERR_ESA_NOT_EXECUTABLE_STATE` — with the `esa_id`, a `defect_type` of `CELL_DEFECT`, `CAPACITY_SHORTFALL`, `RTE_SHORTFALL`, or `BMS_FAULT`, and a `claimed_capacity_loss_mwh` greater than zero. There is no upper cap on the claim relative to the guarantee: a claimed loss equal to the full `guaranteed_capacity_mwh` remains claimable. A new claim is `SUBMITTED`; starting review moves it to `UNDER_REVIEW` (any other source state is `ERR_CLAIM_NOT_SUBMITTED`).

Decision is the money step. The administrator decides an `UNDER_REVIEW` claim — any other state is `ERR_CLAIM_NOT_UNDER_REVIEW` — with a `decision` of `APPROVED` or `REJECTED`. Approval additionally requires the claim's agreement to be `EXECUTED` or `COMPLETED` (`ERR_ESA_NOT_EXECUTABLE_STATE`) and takes a `credit_variant`. Under `STRAIGHT_LINE`, the `credit_amount_cents` is the claimed loss multiplied by the agreement's `price_per_mwh_cents`, rounded up to the next whole cent. Under `OUTPUT_BASED`, the decide payload must also supply a `throughput_mwh` greater than zero, and the credit is the claimed loss multiplied by the throughput, multiplied by the agreement's `guaranteed_rte_pct`, multiplied by the unit price, multiplied by one minus the guaranteed efficiency — the degradation rate — with the entire expression evaluated in exact arithmetic and rounded half up to integer cents exactly once at the end. Either way, approval stamps `decided_at` with the logical clock. Rejection stamps `decided_at` the same way and leaves `credit_amount_cents` null. An approved claim waits for logistics: it becomes `FULFILLED` only when a linked spare-part order reaches `INSTALLED`, and it can be swept to `REJECTED` by the termination cascade of §3.3 while still `SUBMITTED` or `UNDER_REVIEW`.

### 3.8. Market Participation and Bid Settlement

Revenue stacking runs through bid sessions opened by a `MarketOperator` on any project with an agreement in `EXECUTED` or `COMPLETED` — again `ERR_NO_ACTIVE_ESA` without one. The create payload carries the `project_id`, a `market` of `DAY_AHEAD` or `REAL_TIME`, a dispatch window from `window_start` inclusive to `window_end` exclusive (`ERR_INVALID_WINDOW` if misordered), an `offer_mwh` greater than zero, and a non-negative `offer_price_cents_per_mwh` floor. Sessions in `OPEN` or `CLEARED` status on the same project may not overlap — adjacency is fine under the half-open convention — and a conflict is rejected with `ERR_BID_WINDOW_OVERLAP`. A new session is `OPEN` with `revenue_cents` at zero.

Recording the market clearing supplies the `clearing_price_cents_per_mwh` and the `market_cleared_mwh` quantity; the session must be `OPEN`, else `ERR_BID_SESSION_NOT_OPEN`. The dispatch optimization then decides the cleared quantity in a pinned order, price floor before capacity cap: if the clearing price is below the offer floor, `cleared_mwh` is zero even when capacity would allow the full offer; otherwise `cleared_mwh` is the smaller of `offer_mwh` and a capacity cap that is itself the smaller of the project's current `projected_capacity_mwh` and `market_cleared_mwh`, rounded half up to 2 decimal places. The session moves to `CLEARED`.

Settlement is a separate step so cleared positions can be reviewed before revenue posts: settling requires `CLEARED`, else `ERR_BID_SESSION_NOT_CLEARED`, and computes `revenue_cents` as `cleared_mwh` multiplied by the clearing price, rounded half up to integer cents, moving the session to `SETTLED`. An `OPEN` session may instead be cancelled outright, ending `CANCELLED`.

## 4. Endpoint Definitions

All endpoints are mounted under the root path `/`. Creating a new resource returns HTTP 201 with the created resource; all other successful operations — state transitions, recordings, settlements, and reads — return HTTP 200. Every response uses the envelope of §2.2, and list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/projects` | Create a project with power/energy sizing | ProjectDeveloper |
| GET | `/projects` | List projects (paginated) | All roles |
| GET | `/projects/{id}` | Get one project | All roles |
| POST | `/projects/{id}/recompute-projection` | Recompute projected capacity for a supplied cycle count | ProjectDeveloper, PerformanceEngineer |
| POST | `/equipment-supply-agreements` | Create an equipment supply agreement (starts DRAFT) | ProjectDeveloper |
| GET | `/equipment-supply-agreements` | List agreements, optionally filtered by project | All roles |
| GET | `/equipment-supply-agreements/{id}` | Get one agreement | All roles |
| POST | `/equipment-supply-agreements/{id}/execute` | Execute a DRAFT agreement (OCC on project version) | ProjectDeveloper |
| POST | `/equipment-supply-agreements/{id}/complete` | Complete an EXECUTED agreement | ProjectDeveloper |
| POST | `/equipment-supply-agreements/{id}/waive-ld` | Waive accrued liquidated damages | ProjectDeveloper |
| POST | `/delivery-milestones` | Schedule a delivery or commissioning milestone | ProjectDeveloper |
| GET | `/delivery-milestones` | List milestones, optionally filtered by agreement | All roles |
| GET | `/delivery-milestones/{id}` | Get one milestone | All roles |
| POST | `/delivery-milestones/{id}/record-outcome` | Record ACHIEVED or MISSED with the actual date | ProjectDeveloper |
| POST | `/delivery-milestones/{id}/cancel` | Cancel a SCHEDULED milestone | ProjectDeveloper |
| POST | `/safety-permits` | Submit a safety permit | ProjectDeveloper |
| GET | `/safety-permits` | List permits, optionally filtered by project | All roles |
| GET | `/safety-permits/{id}` | Get one permit | All roles |
| POST | `/safety-permits/{id}/decide` | Approve or reject a SUBMITTED permit | SafetyAuthority |
| POST | `/safety-permits/{id}/resubmit` | Resubmit a REJECTED permit | ProjectDeveloper |
| POST | `/performance-tests` | Schedule a capacity or RTE test window | PerformanceEngineer |
| GET | `/performance-tests` | List tests, optionally filtered by project | All roles |
| GET | `/performance-tests/{id}` | Get one test | All roles |
| POST | `/performance-tests/{id}/record-results` | Record measurements inside the test window | PerformanceEngineer |
| POST | `/performance-tests/{id}/cancel` | Cancel a SCHEDULED test | PerformanceEngineer |
| POST | `/augmentation-events` | Plan a manual augmentation on a commissioned project | ServiceEngineer |
| GET | `/augmentation-events` | List augmentation events, optionally filtered by project | All roles |
| GET | `/augmentation-events/{id}` | Get one augmentation event | All roles |
| POST | `/augmentation-events/{id}/execute` | Execute a planned augmentation inside its window (OCC on project version) | ServiceEngineer |
| POST | `/augmentation-events/{id}/cancel` | Cancel a PLANNED augmentation | ServiceEngineer |
| POST | `/service-agreements` | Create a long-term service agreement (starts DRAFT) | ServiceManager |
| GET | `/service-agreements` | List service agreements, optionally filtered by project | All roles |
| GET | `/service-agreements/{id}` | Get one service agreement (may trigger lazy expiry) | All roles |
| POST | `/service-agreements/{id}/activate` | Activate a DRAFT agreement within its term | ServiceManager |
| POST | `/service-agreements/{id}/suspend` | Suspend an ACTIVE agreement | ServiceManager |
| POST | `/service-agreements/{id}/reactivate` | Reactivate a SUSPENDED agreement within its term | ServiceManager |
| POST | `/spare-part-orders` | Order a spare part against an ACTIVE agreement (OCC on agreement version) | ServiceManager, ServiceEngineer |
| GET | `/spare-part-orders` | List orders, optionally filtered by agreement or claim | All roles |
| GET | `/spare-part-orders/{id}` | Get one order | All roles |
| POST | `/spare-part-orders/{id}/ship` | Mark an ORDERED order shipped | ServiceEngineer |
| POST | `/spare-part-orders/{id}/deliver` | Mark a SHIPPED order delivered | ServiceEngineer |
| POST | `/spare-part-orders/{id}/install` | Install a DELIVERED order; fulfills the linked claim | ServiceEngineer |
| POST | `/spare-part-orders/{id}/cancel` | Cancel an ORDERED or SHIPPED order | ServiceManager |
| POST | `/warranty-claims` | File a warranty claim against an agreement | WarrantyAdmin |
| GET | `/warranty-claims` | List claims, optionally filtered by agreement | All roles |
| GET | `/warranty-claims/{id}` | Get one claim | All roles |
| POST | `/warranty-claims/{id}/start-review` | Move a SUBMITTED claim to UNDER_REVIEW | WarrantyAdmin |
| POST | `/warranty-claims/{id}/decide` | Approve (with credit variant) or reject an UNDER_REVIEW claim | WarrantyAdmin |
| POST | `/bid-sessions` | Open a market bid window | MarketOperator |
| GET | `/bid-sessions` | List bid sessions, optionally filtered by project | All roles |
| GET | `/bid-sessions/{id}` | Get one bid session | All roles |
| POST | `/bid-sessions/{id}/record-clearing` | Record the market clearing outcome | MarketOperator |
| POST | `/bid-sessions/{id}/settle` | Settle a CLEARED session | MarketOperator |
| POST | `/bid-sessions/{id}/cancel` | Cancel an OPEN session | MarketOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_ESA_NOT_FOUND | 404 |
| ERR_LTSA_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_MILESTONE_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_TEST_NOT_FOUND | 404 |
| ERR_AUGMENTATION_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_BID_SESSION_NOT_FOUND | 404 |
| ERR_STALE_PROJECT_VERSION | 412 |
| ERR_STALE_LTSA_VERSION | 412 |
| ERR_ESA_NOT_DRAFT | 409 |
| ERR_ESA_NOT_EXECUTABLE_STATE | 409 |
| ERR_MILESTONE_NOT_SCHEDULED | 409 |
| ERR_ESA_TERMINAL_MILESTONE_LOCKED | 409 |
| ERR_PERMIT_NOT_PENDING | 409 |
| ERR_PERMIT_NOT_REJECTED | 409 |
| ERR_TEST_NOT_SCHEDULED | 409 |
| ERR_AUGMENTATION_NOT_PLANNED | 409 |
| ERR_LTSA_NOT_DRAFT | 409 |
| ERR_LTSA_NOT_ACTIVE | 409 |
| ERR_LTSA_NOT_SUSPENDED | 409 |
| ERR_ORDER_NOT_ORDERED | 409 |
| ERR_ORDER_NOT_SHIPPED | 409 |
| ERR_ORDER_NOT_DELIVERED | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_CLAIM_NOT_SUBMITTED | 409 |
| ERR_CLAIM_NOT_UNDER_REVIEW | 409 |
| ERR_CLAIM_NOT_FULFILLABLE | 409 |
| ERR_BID_SESSION_NOT_OPEN | 409 |
| ERR_BID_SESSION_NOT_CLEARED | 409 |
| ERR_PERMIT_MISSING_OR_UNAPPROVED | 409 |
| ERR_TEST_WINDOW_NOT_OPEN | 409 |
| ERR_AUGMENTATION_WINDOW_NOT_OPEN | 409 |
| ERR_LTSA_NOT_IN_TERM | 409 |
| ERR_MILESTONE_OUTCOME_MISMATCH | 409 |
| ERR_TEST_WINDOW_OVERLAP | 409 |
| ERR_BID_WINDOW_OVERLAP | 409 |
| ERR_INVALID_WINDOW | 409 |
| ERR_SIZING_INVALID | 409 |
| ERR_GUARANTEE_EXCEEDS_RATED_ENERGY | 409 |
| ERR_PROJECT_NOT_COMMISSIONED | 409 |
| ERR_DELIVERY_MILESTONES_OPEN | 409 |
| ERR_NO_COMMISSIONING_ACHIEVED | 409 |
| ERR_NO_ACTIVE_ESA | 409 |
| ERR_BUDGET_EXCEEDED | 402 |
| ERR_CREDIT_POOL_EXHAUSTED | 402 |
| ERR_WAIVER_EXCEEDS_ACCRUED | 402 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_RTE_INTERVALS | 400 |
