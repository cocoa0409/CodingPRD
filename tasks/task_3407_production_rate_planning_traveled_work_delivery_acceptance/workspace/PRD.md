# Aero Production Rate Delivery API — Product Requirements Document

## 1. Introduction

Commercial aircraft are sold years before they are built, and the build rate is the airframer's most consequential public promise. Announcing a higher monthly rate commits suppliers to faster long-lead deliveries and the factory to aggressive hiring; getting it wrong means unfinished jobs traveling down the line as out-of-station work, quality escapes stacking up on completed aircraft, and finished jets sitting in storage accruing preservation cost instead of delivering. This API exists to couple the rate decision to the operational evidence underneath it: a program may only commit to a new rate when supply-chain coverage, workforce readiness, traveled-work burden, and quality posture jointly clear a published gating bar.

The system covers the full loop from rate governance to customer handover. A `ProductionPlanner` opens rate cases that are announced, gated against live readiness evidence, and committed — with each committed rate cascading into supplier commitments that may suddenly find themselves ordered against the wrong assumption. A `SupplierManager` commits capacity and places long-lead orders; a `LineManager` runs station work, absorbs traveled work as costed rework, and closes it against a program budget; a `QualityInspector` drives a segregated escape-investigation chain under regulator-notification discipline; a `DeliveryManager` runs storage, flight tests, and the airframer side of delivery negotiations; and a `Customer` walks the aircraft, accepts delivery, and negotiates compensation when dates slip. A single logical clock — never the wall clock — drives every time-dependent rule so behavior stays deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system declares exactly seven roles, spelled as follows: `ProgramAdmin`, `ProductionPlanner`, `SupplierManager`, `LineManager`, `QualityInspector`, `DeliveryManager`, and `Customer`.

Each role carries a distinct operational remit. `ProgramAdmin` is the platform operator: it registers programs, suppliers, and customers, and drives the test clock. `ProductionPlanner` owns rate decisions, workforce plans, and the assignment of aircraft to the production line. `SupplierManager` acts as a specific supplier, committing capacity and managing long-lead orders. `LineManager` runs the production line: it completes or travels work packages and closes or credits rework. `QualityInspector` reports and investigates quality escapes, with disposition segregated from reporting. `DeliveryManager` runs flight tests, storage and preservation, the opening and configuration stages of the delivery pipeline, and the airframer side of delivery negotiations. `Customer` acts as a specific airline: it conducts the acceptance walkthrough, accepts delivery, and holds the customer side of negotiations. Attempting an operation outside one's role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Read endpoints are broadly shared; §4 lists the authorized roles for every endpoint.

Two roles are **entity-backed**. When `X-User-Role` is `SupplierManager`, `X-User-ID` is the `id` of the acting Supplier: on supplier-scoped writes — every commitment create, confirm, order, and cancel — the server compares the commitment's `supplier_id` against `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer: on customer-scoped writes — the walkthrough, delivery acceptance, and the customer side of a negotiation — the comparison is against the `customer_id` of the aircraft concerned.

The remaining five roles are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity, and the server never compares it against an entity's `id`. The server may still record it for accountability — a `QualityInspector`'s `X-User-ID` is written onto each escape as `reported_by_id` at report time and as `dispositioned_by_id` at disposition time, which is precisely what lets the segregation-of-duties rule of §3.6 compare the two.

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

List endpoints paginate through two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent behavior in the system reads a single server-held **logical clock**; the server never falls back to wall-clock time. At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that reading until a `ProgramAdmin` moves it. The admin-only clock-setting capability takes a `to_iso8601` timestamp in the request body and returns 200; advancing the clock recomputes `is_overdue` on every `ACTIVE` storage preservation and refreshes all clock-dependent computed fields.

Wherever this document needs a notion of "now", it means this clock: the *current logical month* that gates rate-case effective months and order lead times is the calendar month containing the clock's current reading; the stamp written by regulator notification is the clock's reading at that moment; storage fee accrual counts elapsed days against it; and preservation overdue checks compare it against each record's due date.

### 2.5. Common Resource Properties

Every resource in the API — programs, rate cases, suppliers, commitments, workforce plans, customers, aircraft, work packages, rework orders, quality escapes, flight tests, storage preservations, and delivery negotiations — carries four system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at`: the same timestamp format, refreshed on every mutation of the resource.
- `version`: a system-managed integer that increments with every mutation of the resource — including mutations driven by cascade side effects, so a client watching a program's `version` observes case creation, announcement, and commitment all advancing it.

### 2.6. Monetary Precision and Rounding Discipline

Money moves through this system as **integer cents**: prices, penalties, storage fees, budgets, and compensation amounts are whole numbers of cents with no fractional part, and every derived monetary value is rounded half-up to integer cents. Two families of quantities break from integer arithmetic: readiness percentages (`supply_chain_readiness_pct`, `workforce_readiness_pct`, each workforce plan's `readiness_ratio`, and the frozen snapshot counterparts on a rate case) and the `readiness_index` are carried to exactly two decimal places, likewise rounded half-up.

Rounding order is pinned wherever many records aggregate into one figure. Storage fees are rounded per aircraft *before* the program-level sum; the cancellation reserve is rounded per commitment *before* its sum. Summing the raw values and rounding once at the end produces a different cent total and is incorrect — §3.3 and §3.7 restate the pinned orders in their business context.

### 2.7. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency protection, each keyed to a parent entity's `version`.

Creating a rate case against a program requires the request body to carry `expected_program_version`, holding the program `version` the client last observed. If it does not equal the program's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412): another writer's rate activity — creating, announcing, or committing a case all advance the program's `version` — has legitimately superseded the client's baseline, and the client's view of the program is stale.

Countering a delivery negotiation requires `expected_negotiation_version` equal to the negotiation's current `version`. A mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because the other party may have moved the negotiation to a new round with a new date and compensation basis that the current writer has not observed.

On both endpoints the staleness check is evaluated immediately after the parent resource is loaded and before every state and business check on the endpoint. Endpoints not named in this section take no version field at all.

### 2.8. Nested Resource Retrieval and the Validation Ladder

Requests that target nested resources are validated left to right along the path: the program first, then the supplier, customer, or aircraft, then the child resource. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first* path identifier that does not resolve to an existing resource; later identifiers are never examined.

Beyond existence, every request passes through one global validation ladder, evaluated in this order:

1. **Authentication** — presence of both headers and a declared role: `ERR_UNAUTHENTICATED` (401).
2. **Role membership and entity-backed ownership** — the acting role must be authorized for the endpoint, and entity-backed identities must match the resource's owner: `ERR_UNAUTHORIZED_ROLE` (403).
3. **Path existence**, left to right as above: `ERR_NOT_FOUND` (404).
4. **Stale-version checks** on the two OCC-guarded endpoints of §2.7: `ERR_STALE_VERSION` (412).
5. **State gates** — the requested transition must exist from the resource's current state, including terminal-state lockdown and the delivery-pipeline stage gates (`ERR_INVALID_TRANSITION`, 409); flight-test scheduling additionally demands a `CLEAR` quality status (`ERR_QUALITY_HOLD`, 409); storage release and delivery acceptance demand that no `OPEN` rework order remain on the aircraft (`ERR_REWORK_ORDERS_OPEN`, 409).
6. **Safety gates** — regulator notification must precede root-cause work (`ERR_REGULATOR_NOTIFICATION_REQUIRED`, 422), and disposition must be segregated from reporting (`ERR_SEGREGATION_OF_DUTIES`, 403).
7. **Temporal rules** — window ordering and month arithmetic (`ERR_WINDOW_INVALID` and `ERR_LEAD_TIME_VIOLATION`, both 422).
8. **Business constraints** — resource-window overlap, configuration match, rate change, gating verdict, negotiation turn and round limit, goodwill credit standing, and code uniqueness (`ERR_RANGE_WINDOW_OVERLAP`, `ERR_BAY_WINDOW_OVERLAP`, `ERR_CONFIGURATION_MISMATCH`, `ERR_RATE_UNCHANGED`, `ERR_GATING_CRITERIA_UNMET`, `ERR_NEGOTIATION_ACTOR_TURN`, `ERR_NEGOTIATION_ROUND_LIMIT`, `ERR_GOODWILL_REQUIRES_GOOD_CREDIT`, `ERR_DUPLICATE_CODE`).
9. **Fiscal bounds** — order quantity, hire headcount, rework budget, and cancel quantity (`ERR_ORDER_EXCEEDS_COMMITMENT`, `ERR_HIRE_EXCEEDS_REQUIRED`, `ERR_BUDGET_EXCEEDED`, `ERR_CANCEL_QUANTITY_INVALID`, all 422).
10. **Request-body shape, last** — field presence, types, enum membership, and integer lower bounds are validated only after every rule above has passed: `ERR_INVALID_REQUEST` (400).

Where several rungs could fire on a single request, the lower-numbered rung's error is the one returned. Within the state-gate rung, the pipeline-stage check (the transition must exist) precedes the more specific quality-hold and open-rework gates.

### 2.9. Program Health: Readiness Index, Posture, and Live Counters

Every program carries a set of live computed signals that summarize its industrial health, and a plain read of a program recomputes them on the spot — the readiness percentages and index, the cancellation reserve, the storage fee accrual, and the posture — so the returned object always reflects current entity state. The same recomputation runs after any transition that mutates escapes, traveled work, workforce, or commitments.

**Supply-chain readiness.** Count the distinct long-lead component families — distinct `component_code` values — for which the program holds at least one supplier commitment whose `status` is `CONFIRMED`, `ORDERED`, or `AT_RISK` and whose `committed_rate_per_month` is greater than or equal to the target rate under evaluation. Multiply that count by 100 and divide by the program's `required_component_codes`; if `required_component_codes` is zero, supply readiness is defined as 100. The result, capped at 100, is the program's `supply_chain_readiness_pct`.

**Workforce readiness.** Sum `hired_headcount` over all of the program's workforce plans, multiply by 100, and divide by the sum of `required_headcount` over the same plans; if the program has no workforce plans, or the summed requirement is zero, workforce readiness is defined as 100. Capped at 100, this is the program's `workforce_readiness_pct`.

**Burden penalty.** Open traveled work subtracts readiness directly: half a point per open traveled-work hour — 0.5 times `traveled_work_open_hours` — capped at 20.0 points.

**Readiness index.** The program's `readiness_index` is the smaller of the two percentages minus the burden penalty, rounded half-up to two decimal places. The live variant evaluates everything against the program's currently committed rate; the gating-review variant of §3.2 evaluates the same formula against a proposed rate and freezes it onto the case.

**Posture.** The program's `posture` is derived from the index together with quality and commitment state. It is `DISTRESSED` when any of the following holds: the `readiness_index` is below 60.0; any `CRITICAL` quality escape on a program aircraft is in `OPEN`, `ROOT_CAUSE`, or `DISPOSITIONED`; the `open_escape_count` is 3 or more; or any commitment of the program is `AT_RISK`. Otherwise it is `STABLE` when the `readiness_index` is at least 85.0 and the `open_escape_count` is zero. In every remaining case it is `STABILIZING`.

The counters behind these signals are defined as follows. `open_escape_count` counts quality escapes on the program's aircraft whose status is `OPEN`, `ROOT_CAUSE`, or `DISPOSITIONED`. `traveled_work_open_hours` sums `traveled_hours` over work packages in `TRAVELED` status whose linked rework order is neither `CLOSED` nor `CREDITED`. `undelivered_inventory_count` counts the program's aircraft whose `production_status` is `ASSEMBLY_COMPLETE` or `IN_STORAGE`. `rework_budget_consumed_cents` sums `actual_cost_cents` over the program's rework orders in `CLOSED` status only — `OPEN` and `CREDITED` orders are excluded. `cancellation_reserve_cents` and `storage_fees_accrued_cents` follow the pinned-order aggregations of §3.3 and §3.7.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program: Registrations, Workforce, and the Line

A `ProgramAdmin` stands up the commercial cast before any planning can begin. Registering a production program takes a unique `model_code`, the currently committed build rate `current_rate_per_month` (at least one aircraft per month), `required_component_codes` — the count of distinct long-lead component families that supplier commitments must cover before a rate increase can pass gating, at least one — and `rework_budget_total_cents`, the program's lifetime rework budget in integer cents (zero or more). A second program registered under the same `model_code` is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). Suppliers register with a unique `supplier_code` plus a legal `name` and home `region`; customer airlines register with a unique `airline_code`, a `name`, and a `credit_standing` of `GOOD`, `WATCH`, or `POOR` — the same uniqueness error guards both codes.

Workforce planning belongs to the `ProductionPlanner`. Each plan names a `skill_code` (unique within its program, under the same `ERR_DUPLICATE_CODE` discipline) and a `required_headcount` of at least one; `hired_headcount` starts at zero, and the plan's `readiness_ratio` — hired divided by required, carried to two decimal places — feeds program readiness. Recording hires takes a `count` of at least one, and the cumulative `hired_headcount` plus the new `count` may not exceed `required_headcount`; an over-hire is rejected with `ERR_HIRE_EXCEEDS_REQUIRED` (HTTP 422).

Aircraft join the line through the `ProductionPlanner` as well, each carrying its `customer_id`, a `line_number` unique within its program (same uniqueness error), the as-built `configuration_code`, the contracted `ordered_configuration_code` — delivery acceptance later demands equality of the two — a `contract_price_cents` of at least one cent that anchors the liquidated-damages cap, and a `contracted_delivery_date` that anchors the days-late arithmetic of §3.9. A new unit starts with `production_status` `IN_PRODUCTION`, `quality_status` `CLEAR`, `delivery_status` `NOT_STARTED`, a `rework_cost_total_cents` of zero, and a null `scheduled_delivery_date` that only a successful delivery negotiation fills. Three independent state dimensions — production, quality, and delivery — ride on every aircraft; each evolves on its own triggers, and only a handful of gates (delivery acceptance reads all three) cross dimensions. A program's aircraft list and a customer's aircraft list can both be filtered by `production_status`.

### 3.2. Rate Decisions: Announce, Gating Review, Commit, Shelve

Rate governance starts when a `ProductionPlanner` opens a rate case against a program. The case records its target program as `program_id` and carries a `proposed_rate` of at least one aircraft per month, an `effective_month` in `YYYY-MM` form naming the first calendar month the new rate would apply, the `demand_backlog_units` of firm customer backlog justifying the change (zero or more), and the OCC field `expected_program_version`. Three checks fire here beyond the universal ladder, and their relative order follows the ladder: the stale-version rejection of §2.7 (`ERR_STALE_VERSION`, 412) is evaluated first, immediately after the program loads; then an `effective_month` earlier than the current logical month is rejected `ERR_WINDOW_INVALID` (422); then a `proposed_rate` equal to the program's `current_rate_per_month` is rejected `ERR_RATE_UNCHANGED` (422), because a rate case must propose a change. Creating the case — it lands in `DRAFT` — itself increments the program's `version` by one, so a second create against the version a client just read is already stale.

Announcing moves a case `DRAFT` → `ANNOUNCED`, copies its `proposed_rate` into the program's `announced_target_rate`, and advances the program's `version` again. More precisely, the announced target always reflects the `proposed_rate` of the most recently created case currently in `ANNOUNCED` or `GATED_REVIEW` — the latest by `created_at` wins — and falls back to `current_rate_per_month` when no such case exists.

Requesting a gating review (`ANNOUNCED` → `GATED_REVIEW`) freezes the evidence. The readiness formula of §2.9 is evaluated against the case's `proposed_rate` rather than the committed rate, and the results are stamped onto the case as `supply_readiness_snapshot_pct`, `workforce_readiness_snapshot_pct`, `burden_penalty_snapshot`, and `readiness_index_snapshot`; later movement in commitments, hiring, or traveled work never moves a frozen snapshot. The same review sets `gating_verdict` — null until this point — to `PASS` when the frozen readiness index is at least 85.0 and the program's `open_escape_count` is zero at review time, and to `FAIL` otherwise.

Committing (`GATED_REVIEW` → `COMMITTED`) is gated on a `PASS` verdict; any other verdict draws `ERR_GATING_CRITERIA_UNMET` (HTTP 422). A commit lands with a four-link cascade. First, the program's `current_rate_per_month` becomes the case's `proposed_rate`, and the program's `version` advances. Second, commitments re-rate: every commitment of the program in `ORDERED` whose `assumed_rate_at_order` exceeds the newly committed rate flips to `AT_RISK`, and every commitment in `AT_RISK` whose `assumed_rate_at_order` is less than or equal to the new rate recovers to `ORDERED`. Third, the program's `cancellation_reserve_cents` is recomputed over the mutated commitment set, since each flip changes projected penalty exposure. Fourth, the program's `posture` is recomputed — and if it lands on `DISTRESSED`, every other case of the same program still sitting in `GATED_REVIEW` is auto-shelved to `SHELVED`.

Shelving is the planner's discard: any case in `DRAFT`, `ANNOUNCED`, or `GATED_REVIEW` can move to `SHELVED`. Shelving an announced or gated case recomputes the announced target from the remaining `ANNOUNCED` or `GATED_REVIEW` cases, with the committed rate as the fallback when none remain; shelving a draft touches nothing downstream. `COMMITTED` and `SHELVED` are terminal — any further action on such a case is `ERR_INVALID_TRANSITION` (HTTP 409). A program's case list can be filtered by `status`.

### 3.3. Supplier Capacity Commitments and Long-Lead Orders

Long-lead supply is contracted through capacity commitments. A `SupplierManager` — whose `X-User-ID` must equal the `id` of the supplier on record for every write in this section, with mismatches rejected `ERR_UNAUTHORIZED_ROLE` (403) — opens a commitment in `DRAFT`, naming the covered `program_id`, the `component_code` family, a `committed_rate_per_month` of at least one, a `lead_time_months` of at least one whole calendar month, and a `unit_price_cents` of at least one. A fresh commitment shows `ordered_quantity` and `cancelled_quantity` at zero, so `active_ordered_quantity` — ordered minus cancelled — starts at zero as well; `assumed_rate_at_order` stays null until the first order; `cancellation_penalty_cents` is zero unless a cancel computes one.

Confirmation moves the commitment `DRAFT` → `CONFIRMED`. Ordering (`CONFIRMED` → `ORDERED`, and repeatable from `ORDERED` or `AT_RISK` as a top-up) takes a `quantity`, an `assumed_rate_per_month`, and a `required_by_month`; each call adds `quantity` into `ordered_quantity`, overwrites `assumed_rate_at_order` with the payload's rate assumption, and lands the commitment in `ORDERED`. Two bounds police the order. Temporally, `required_by_month` must be at least `lead_time_months` calendar months beyond the current logical month — a tighter window is rejected `ERR_LEAD_TIME_VIOLATION` (422). Fiscally, `quantity` must be at least one and no more than `committed_rate_per_month` multiplied by `lead_time_months` — anything outside that band is `ERR_ORDER_EXCEEDS_COMMITMENT` (422).

Cancellation is all-or-nothing and runs from `CONFIRMED`, `ORDERED`, or `AT_RISK` to `CANCELLED`. The `cancel_quantity` may be omitted, in which case it defaults to the full `active_ordered_quantity`; when provided it must equal `active_ordered_quantity` exactly, else `ERR_CANCEL_QUANTITY_INVALID` (422) — partial cancellations do not exist. Cancelling adds the quantity into `cancelled_quantity`, records a `cancellation_penalty_cents` of thirty percent of the cancelled quantity times `unit_price_cents`, rounded half-up to integer cents, and recomputes the program's reserve. A `CONFIRMED` commitment has an `active_ordered_quantity` of zero, so cancelling one records zero units and a zero penalty.

That reserve — the program's `cancellation_reserve_cents` — prices supply-chain exit risk. Every `AT_RISK` commitment contributes a projected penalty of thirty percent of its `active_ordered_quantity` times `unit_price_cents`, rounded half-up per commitment before any summation; every `CANCELLED` commitment contributes its recorded `cancellation_penalty_cents`; `CONFIRMED` and `ORDERED` commitments contribute nothing. The reserve is recomputed whenever a commitment flips status: on orders, on the commit-driven at-risk cascade and its recovery, and on cancellation. Commitment lists — per supplier or per program — filter by `status`, and the program-scoped list additionally by `component_code`.

### 3.4. Line Execution: Work Packages and Traveled Work

Inside the factory, work on an aircraft is decomposed into station jobs. A `LineManager` adds a work package to an aircraft — the package keeps that link as its `aircraft_id` — with a `station_sequence` of at least one (unique per aircraft), a `description`, and `planned_hours` of at least one; the package starts `OPEN`.

Completing a package moves it `OPEN` → `COMPLETE`. Travelling it — declaring that the job could not finish at its station and must move down the line — moves it `OPEN` → `TRAVELED`, requires a `traveled_hours` payload of at least one, and records those hours on the package. Travel spawns two cascades in the same breath: it creates a rework order with `source` `TRAVELED_WORK` bound to this package and this aircraft (`work_package_id` and `aircraft_id` respectively), provisionally priced per §3.5; and it recomputes the program's `traveled_work_open_hours` over the new traveled set.

Whether the last outstanding package completes or travels, the moment every work package of an aircraft — at least one must exist — sits in `COMPLETE` or `TRAVELED`, the aircraft's `production_status` bubbles up from `IN_PRODUCTION` to `ASSEMBLY_COMPLETE` and the program's `undelivered_inventory_count` is recomputed. Both `COMPLETE` and `TRAVELED` are terminal for a package, and an aircraft's work-package list can be filtered by `status`.

### 3.5. Rework Economics: Provisional Estimates, Final Costs, and the Budget Gate

Rework orders carry a two-variant costing scheme, and the two variants answer different questions. The **provisional variant** prices a job the moment the order is created and stores the figure on `estimated_cost_cents`: an hours basis times 15000 cents per hour times a source multiplier, rounded half-up to integer cents, with parts ignored entirely. The hours basis depends on the order's `source`: for `TRAVELED_WORK`, the linked package's `traveled_hours`; for `QUALITY_ESCAPE` — an order a `QualityInspector` opens against an escape with an `estimated_hours` payload, its `escape_id` set and its `work_package_id` null — that payload's hours; for `FLIGHT_TEST_FAILURE`, the optional `rework_estimated_hours` payload of the failed flight test; and for `WALKTHROUGH_SNAG`, four hours per recorded snag, that is `snag_count` times four. The multiplier is 1.5 for quality escapes, 1.25 for flight-test failures, and 1.0 for both traveled work and walkthrough snags.

The **final variant** prices the job at close and ignores the provisional estimate entirely. When a `LineManager` closes an `OPEN` order with `actual_hours` and `parts_cents`, the order's `actual_cost_cents` — null until this moment — becomes `actual_hours` times 17500 cents per hour plus `parts_cents`, rounded half-up to integer cents. Identical hour inputs therefore produce different provisional and final totals; that divergence is by design. The close is also the program's budget gate: if the program's `rework_budget_consumed_cents` plus this final cost would exceed `rework_budget_total_cents`, the close is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422). A successful close recomputes the program's consumed budget in ledger sync, recomputes the aircraft's `rework_cost_total_cents`, and — for `TRAVELED_WORK` orders — recomputes `traveled_work_open_hours`, because the linked package's hours leave the open set once their rework is closed.

Crediting reverses a closed charge: `CLOSED` → `CREDITED` is the compensating action, and both ledgers drop the order — `rework_budget_consumed_cents` and the aircraft's `rework_cost_total_cents` count `CLOSED` orders only, so the recomputation excludes the credited one. For traveled-work orders, the linked package's hours likewise stop counting as open traveled work. `CREDITED` is terminal; `OPEN` orders never entered the budget in the first place. An aircraft's rework-order list filters by `source` and `status`, and per-package and per-escape listings exist for tracing an order back to its origin.

### 3.6. Quality Escapes: Notification Discipline and Segregated Disposition

Quality escapes follow a strict evidentiary chain. A `QualityInspector` reports an escape against an aircraft with a `severity` of `MAJOR` or `CRITICAL` and a `description`; the reporter's `X-User-ID` is recorded as `reported_by_id`, the escape lands in `OPEN`, the aircraft's `quality_status` moves immediately to `HOLD`, and the program's `open_escape_count` and `posture` are recomputed. `conformance_documented` starts false, and `conformance_refs` starts empty — an append-only list for the rest of the escape's life.

Regulator notification comes next in practice: notifying stamps `regulator_notified_at` with the current logical clock, and the escape's `is_late_notification` reads true exactly when that stamp is later than the escape's `created_at` plus 24 hours. Root-cause work (`OPEN` → `ROOT_CAUSE`) cannot begin before that notification exists — the attempt is rejected with `ERR_REGULATOR_NOTIFICATION_REQUIRED` (HTTP 422) — and it requires a `conformance_refs` payload carrying at least one reference; a successful call appends those references and flips `conformance_documented` to true.

Disposition (`ROOT_CAUSE` → `DISPOSITIONED`) is segregated from reporting: the acting inspector's `X-User-ID` must differ from the escape's `reported_by_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful disposition records the actor as `dispositioned_by_id` and the payload's `disposition_code` — one of `USE_AS_IS`, `REWORK`, or `SCRAP`. Reopening (`DISPOSITIONED` → `ROOT_CAUSE`) nulls both fields and lets the investigation resume; the cycle may repeat.

Closing (`DISPOSITIONED` → `CLOSED`) demands that every rework order spawned from this escape — every order whose `escape_id` points here — already sits in `CLOSED` or `CREDITED`. The close recomputes the program's `open_escape_count`, returns the aircraft's `quality_status` to `CLEAR` when no escape on it remains in `OPEN`, `ROOT_CAUSE`, or `DISPOSITIONED`, and recomputes the program's `posture`. Escape lists filter by `status`.

### 3.7. Storage and Preservation of Undelivered Aircraft

Aircraft that complete assembly ahead of their delivery slot are preserved in storage. A `DeliveryManager` creates a storage preservation for an `ASSEMBLY_COMPLETE` aircraft with a `bay_code`, a `window_start` and `window_end`, a `daily_rate_cents` of at least one, and a `preservation_cycle_days` of at least one. Creation moves the aircraft's `production_status` from `ASSEMBLY_COMPLETE` to `IN_STORAGE` and recomputes the program's `undelivered_inventory_count`; because creation always requires `ASSEMBLY_COMPLETE` and always moves the aircraft out of it, a second active storage record for the same aircraft is structurally impossible. On the record itself, `last_preserved_at` initializes to `window_start`; `next_preservation_due` is `last_preserved_at` plus `preservation_cycle_days` days; and `is_overdue` is true exactly when the record is `ACTIVE` and the logical clock reads strictly later than `next_preservation_due`.

Storage windows are **closed** intervals, and two rules police them. The `window_end` must fall strictly after `window_start`, else `ERR_WINDOW_INVALID` (422). On the same `bay_code`, the new window padded by a two-day turnaround buffer on each side must not intersect any other `ACTIVE` preservation: a conflict exists exactly when the new `window_start` is on or before the existing record's `window_end` plus two days *and* the existing record's `window_start` is on or before the new `window_end` plus two days, and a conflict is rejected with `ERR_BAY_WINDOW_OVERLAP` (HTTP 409).

Preservation maintenance keeps an `ACTIVE` record `ACTIVE`: it resets `last_preserved_at` to the current logical clock and recomputes both the due date and the overdue flag. Releasing (`ACTIVE` → `RELEASED`) is blocked while any rework order of the aircraft remains `OPEN` — `ERR_REWORK_ORDERS_OPEN` (409) — and otherwise returns the aircraft to `ASSEMBLY_COMPLETE`, with `undelivered_inventory_count` recomputed. `RELEASED` is terminal.

Storage fees accrue only while a record is `ACTIVE`. For each active preservation, take the whole days elapsed from `window_start` to the logical clock — fractional days are discarded, and the count never drops below zero when the clock reads earlier than the window start — multiply by `daily_rate_cents`, apply the five-percent volume discount by multiplying by 0.95, and round half-up to integer cents **per aircraft**. The program's `storage_fees_accrued_cents` is then the sum of those per-aircraft rounded fees. The rounding order is pinned: per-aircraft rounding first, summation second; summing the raw values and rounding once produces a different cent total and is incorrect. `RELEASED` records contribute nothing. An aircraft's storage list filters by `status`.

### 3.8. The Delivery Acceptance Pipeline: Flight Tests, Configuration, Walkthrough, Acceptance

The delivery acceptance pipeline is a staged walk along the aircraft's `delivery_status`, and a `DeliveryManager` opens it. Beginning delivery requires `production_status` `ASSEMBLY_COMPLETE` and moves `NOT_STARTED` → `FLIGHT_TESTING`; after a rejection, the same action retries the pipeline (`REJECTED` → `FLIGHT_TESTING`), but the retry is gated on there being no `OPEN` rework order left on the aircraft — attempting the retry while one remains is rejected with `ERR_INVALID_TRANSITION` (HTTP 409).

Flight tests occupy range resources. Scheduling one takes a `range_code` of `RANGE_ALPHA` or `RANGE_BRAVO` and a `window_start`/`window_end` pair, and four rungs of the ladder apply in order: the aircraft must be in `FLIGHT_TESTING` (a pipeline-stage violation is `ERR_INVALID_TRANSITION`, 409); its `quality_status` must be `CLEAR` (`ERR_QUALITY_HOLD`, 409); the `window_end` must fall strictly after `window_start` (`ERR_WINDOW_INVALID`, 422); and the half-open interval — from `window_start` up to but not including `window_end` — must not intersect any other `SCHEDULED` test on the same range, with exact adjacency (one window starting precisely where another ends) permitted (`ERR_RANGE_WINDOW_OVERLAP`, 409). A scheduled test sits in `SCHEDULED` until an outcome is recorded.

Recording an outcome (`SCHEDULED` → `COMPLETED`) takes an `outcome` of `PASS` or `FAIL`. A `PASS` advances nothing by itself: even when every flight test of the aircraft is `COMPLETED` with outcome `PASS` and the aircraft sits in `FLIGHT_TESTING`, the pipeline moves only through configuration verification — there is no auto-advance. A `FAIL` detonates three effects at once: the aircraft's `delivery_status` drops to `REJECTED`; a rework order with `source` `FLIGHT_TEST_FAILURE` is created, provisionally priced from the request's optional `rework_estimated_hours`; and every live negotiation of the aircraft — any in `PROPOSED` or `COUNTERED` — auto-expires to `EXPIRED`, because the delivery state changed underneath it.

Configuration verification (`FLIGHT_TESTING` → `CONFIG_VERIFIED`) demands a clean flight-test record: at least one flight test of the aircraft is `COMPLETED`, every `COMPLETED` test carries outcome `PASS`, and no `SCHEDULED` test may remain — shortfalls are stage violations rejected with `ERR_INVALID_TRANSITION`. It also demands that the as-built `configuration_code` equals the contracted `ordered_configuration_code`; a mismatch is `ERR_CONFIGURATION_MISMATCH` (HTTP 422).

The customer's walkthrough comes next, performed by the buying `Customer` — `X-User-ID` must equal the aircraft's `customer_id` — with a `snag_count` payload. Zero snags pass the walkthrough: `CONFIG_VERIFIED` → `WALKTHROUGH_PASSED`. One or more snags reject it: `CONFIG_VERIFIED` → `REJECTED`, and a rework order with `source` `WALKTHROUGH_SNAG` is created on a hours basis of four hours per snag, provisionally priced per §3.5.

Delivery acceptance is the customer's final signature and the one gate that reads all three state dimensions at once: `production_status` must be `ASSEMBLY_COMPLETE`, `delivery_status` must be `WALKTHROUGH_PASSED`, `quality_status` must be `CLEAR`, no rework order of the aircraft may be `OPEN` (`ERR_REWORK_ORDERS_OPEN`, 409), and the acting `X-User-ID` must equal the aircraft's `customer_id`. Acceptance sets `delivery_status` to `ACCEPTED`, moves `production_status` to `DELIVERED` — its terminal state — and recomputes `undelivered_inventory_count`. An aircraft's flight-test list filters by `status`.

### 3.9. Delivery Schedule Negotiation and Delay Compensation

When an aircraft will miss its contracted date, the airframer and the customer negotiate. A `DeliveryManager` opens the negotiation with a `proposed_delivery_date` and a `compensation_variant` of `CONTRACTUAL_LIQUIDATED` or `GOODWILL`; the negotiation copies `customer_id` from the aircraft, starts at `round_number` 1 in `PROPOSED` — the airframer's proposal — and immediately computes `days_late` and `compensation_cents` for round one. `days_late` is the whole-day difference between the `proposed_delivery_date` and the aircraft's `contracted_delivery_date`, floored at zero, so an on-time or early proposal carries no penalty.

Compensation comes in two variants, recomputed on every round from that round's variant and `days_late`. `CONTRACTUAL_LIQUIDATED` pays 250000 cents per day late, capped at ten percent of the aircraft's `contract_price_cents` with the cap itself rounded half-up to integer cents — the compensation is the smaller of the per-diem total and the cap. `GOODWILL` pays a flat base of 1000000 cents plus 100000 cents per day late with no cap, and it is reserved for customers whose `credit_standing` is `GOOD`: proposing or countering in the `GOODWILL` variant for a customer of any other standing is rejected with `ERR_GOODWILL_REQUIRES_GOOD_CREDIT` (HTTP 422).

Countering is strictly turn-taking. A `PROPOSED` negotiation awaits the `Customer`; a `COUNTERED` one awaits the `DeliveryManager`; a move by the wrong side is rejected `ERR_NEGOTIATION_ACTOR_TURN` (HTTP 403). The counter payload carries a fresh `proposed_delivery_date`, a fresh `compensation_variant`, and `expected_negotiation_version`; per §2.7 the staleness check fires right after the negotiation loads and before the turn and business checks, rejecting a stale base with `ERR_STALE_VERSION` (412). A successful counter replaces the standing date and variant, recomputes `days_late` and `compensation_cents`, increments `round_number` by one, and advances the negotiation's `version` — which is exactly what leaves the other party's next counter stale unless it re-reads. The negotiation allows at most six rounds: a counter attempted when `round_number` is already 6 is rejected with `ERR_NEGOTIATION_ROUND_LIMIT` (HTTP 422), does not advance the round, and the attempt itself pushes the negotiation into `EXPIRED`.

Agreement ends the game in the responder's hands: the `Customer` agrees to a standing airframer proposal (`PROPOSED` → `AGREED`), or the `DeliveryManager` agrees to a customer counter (`COUNTERED` → `AGREED`), under the same turn rule. Agreement writes the standing `proposed_delivery_date` onto the aircraft's `scheduled_delivery_date` and locks `compensation_cents` at its current value. `AGREED` and `EXPIRED` are both terminal — and recall from §3.8 that a failed flight test expires every live negotiation of the aircraft outright. An aircraft's negotiation list filters by `status`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`, shown below with their template variables in braces. Operations that create a new resource return `201 Created`; operations that act on an existing resource — state transitions, recordings, and the clock-setting capability — return `200 OK`. Request payloads, response shapes, and side effects are reconstructed from the narratives of §2 and §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |
| POST | `/api/programs` | Create a production program | ProgramAdmin |
| GET | `/api/programs/{id}` | Read a program with live posture, readiness, reserve, fees, and counters | All roles |
| POST | `/api/programs/{id}/rate-cases` | Create a rate case (DRAFT); OCC-guarded on program version | ProductionPlanner |
| GET | `/api/programs/{id}/rate-cases` | List a program's rate cases | ProgramAdmin, ProductionPlanner |
| POST | `/api/rate-cases/{id}/announce` | Announce the target rate (DRAFT → ANNOUNCED) | ProductionPlanner |
| POST | `/api/rate-cases/{id}/request-gating-review` | Freeze gating snapshots and verdict (ANNOUNCED → GATED_REVIEW) | ProductionPlanner |
| POST | `/api/rate-cases/{id}/commit` | Commit the rate (GATED_REVIEW → COMMITTED) with the at-risk/reserve/posture cascade | ProductionPlanner |
| POST | `/api/rate-cases/{id}/shelve` | Shelve the case (→ SHELVED) | ProductionPlanner |
| POST | `/api/suppliers` | Register a supplier | ProgramAdmin |
| GET | `/api/suppliers/{id}` | Read a supplier | All roles |
| POST | `/api/suppliers/{id}/capacity-commitments` | Open a capacity commitment (DRAFT) | SupplierManager |
| GET | `/api/suppliers/{id}/capacity-commitments` | List a supplier's commitments | ProgramAdmin, ProductionPlanner, SupplierManager |
| GET | `/api/programs/{id}/capacity-commitments` | List commitments covering a program | ProgramAdmin, ProductionPlanner, SupplierManager |
| POST | `/api/capacity-commitments/{id}/confirm` | Confirm a commitment (DRAFT → CONFIRMED) | SupplierManager |
| POST | `/api/capacity-commitments/{id}/place-order` | Place or top up a long-lead order (→ ORDERED) | SupplierManager |
| POST | `/api/capacity-commitments/{id}/cancel` | Cancel all-or-nothing with penalty (→ CANCELLED) | SupplierManager |
| POST | `/api/programs/{id}/workforce-plans` | Create a workforce hiring plan | ProductionPlanner |
| GET | `/api/programs/{id}/workforce-plans` | List a program's workforce plans | ProgramAdmin, ProductionPlanner |
| POST | `/api/workforce-plans/{id}/hire` | Record hires into a plan | ProductionPlanner |
| POST | `/api/customers` | Register a customer airline | ProgramAdmin |
| GET | `/api/customers/{id}` | Read a customer | All roles |
| POST | `/api/programs/{id}/aircraft-units` | Add an aircraft unit to the line | ProductionPlanner |
| GET | `/api/aircraft-units/{id}` | Read an aircraft with all three state dimensions | All roles |
| GET | `/api/programs/{id}/aircraft-units` | List a program's aircraft | ProgramAdmin, ProductionPlanner, LineManager, QualityInspector, DeliveryManager |
| GET | `/api/customers/{id}/aircraft-units` | List a customer's aircraft | ProgramAdmin, DeliveryManager, Customer |
| POST | `/api/aircraft-units/{id}/work-packages` | Add a station job to an aircraft | LineManager |
| GET | `/api/aircraft-units/{id}/work-packages` | List an aircraft's work packages | ProgramAdmin, ProductionPlanner, LineManager |
| GET | `/api/work-packages/{id}` | Read a work package | ProgramAdmin, ProductionPlanner, LineManager |
| POST | `/api/work-packages/{id}/complete` | Complete the job (OPEN → COMPLETE) | LineManager |
| POST | `/api/work-packages/{id}/travel` | Mark the job traveled (OPEN → TRAVELED), spawning rework | LineManager |
| POST | `/api/quality-escapes/{id}/rework-orders` | Open an escape-driven rework order | QualityInspector |
| GET | `/api/aircraft-units/{id}/rework-orders` | List an aircraft's rework orders | ProgramAdmin, ProductionPlanner, LineManager, QualityInspector, DeliveryManager |
| GET | `/api/work-packages/{id}/rework-orders` | List rework orders spawned by a work package | ProgramAdmin, LineManager |
| GET | `/api/quality-escapes/{id}/rework-orders` | List rework orders spawned by an escape | ProgramAdmin, QualityInspector |
| POST | `/api/rework-orders/{id}/close` | Close rework with actuals (OPEN → CLOSED) | LineManager |
| POST | `/api/rework-orders/{id}/credit` | Reverse a closed rework charge (CLOSED → CREDITED) | LineManager |
| POST | `/api/aircraft-units/{id}/quality-escapes` | Report a quality escape (aircraft → quality HOLD) | QualityInspector |
| GET | `/api/quality-escapes/{id}` | Read a quality escape | ProgramAdmin, QualityInspector, DeliveryManager, ProductionPlanner |
| GET | `/api/aircraft-units/{id}/quality-escapes` | List an aircraft's escapes | ProgramAdmin, QualityInspector, DeliveryManager, ProductionPlanner |
| POST | `/api/quality-escapes/{id}/notify-regulator` | Stamp regulator notification at the logical clock | QualityInspector |
| POST | `/api/quality-escapes/{id}/begin-root-cause` | Attach conformance references and open root-cause work (OPEN → ROOT_CAUSE) | QualityInspector |
| POST | `/api/quality-escapes/{id}/disposition` | Disposition the escape, segregated from its reporter (ROOT_CAUSE → DISPOSITIONED) | QualityInspector |
| POST | `/api/quality-escapes/{id}/reopen` | Reopen a dispositioned escape (DISPOSITIONED → ROOT_CAUSE) | QualityInspector |
| POST | `/api/quality-escapes/{id}/close` | Close the escape once linked rework is resolved (DISPOSITIONED → CLOSED) | QualityInspector |
| POST | `/api/aircraft-units/{id}/flight-tests` | Schedule a flight-test window on a range | DeliveryManager |
| GET | `/api/aircraft-units/{id}/flight-tests` | List an aircraft's flight tests | ProgramAdmin, DeliveryManager, Customer |
| POST | `/api/flight-tests/{id}/record-outcome` | Record PASS/FAIL (SCHEDULED → COMPLETED) | DeliveryManager |
| POST | `/api/aircraft-units/{id}/begin-delivery` | Open or retry the delivery pipeline (→ FLIGHT_TESTING) | DeliveryManager |
| POST | `/api/aircraft-units/{id}/verify-configuration` | Verify configuration and flight-test record (FLIGHT_TESTING → CONFIG_VERIFIED) | DeliveryManager |
| POST | `/api/aircraft-units/{id}/conduct-walkthrough` | Customer walkthrough; snags reject with rework | Customer |
| POST | `/api/aircraft-units/{id}/accept-delivery` | Customer accepts delivery (→ ACCEPTED; production → DELIVERED) | Customer |
| POST | `/api/aircraft-units/{id}/storage-preservations` | Move an ASSEMBLY_COMPLETE aircraft into a storage bay | DeliveryManager |
| GET | `/api/aircraft-units/{id}/storage-preservations` | List an aircraft's storage records | ProgramAdmin, DeliveryManager |
| POST | `/api/storage-preservations/{id}/maintain` | Perform preservation maintenance | DeliveryManager |
| POST | `/api/storage-preservations/{id}/release` | Release the aircraft from storage (ACTIVE → RELEASED) | DeliveryManager |
| POST | `/api/aircraft-units/{id}/delivery-negotiations` | Open a delivery-schedule negotiation (round 1, PROPOSED) | DeliveryManager |
| GET | `/api/aircraft-units/{id}/delivery-negotiations` | List an aircraft's negotiations | ProgramAdmin, DeliveryManager, Customer |
| POST | `/api/delivery-negotiations/{id}/counter` | Counter-propose (PROPOSED ↔ COUNTERED); OCC-guarded | DeliveryManager, Customer |
| POST | `/api/delivery-negotiations/{id}/agree` | Agree to the standing proposal (→ AGREED) | DeliveryManager, Customer |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return. Trigger conditions are defined in the narratives of §2 and §3; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_QUALITY_HOLD` | 409 Conflict |
| `ERR_REWORK_ORDERS_OPEN` | 409 Conflict |
| `ERR_REGULATOR_NOTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_VIOLATION` | 422 Unprocessable Entity |
| `ERR_RANGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BAY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CONFIGURATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RATE_UNCHANGED` | 422 Unprocessable Entity |
| `ERR_GATING_CRITERIA_UNMET` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_ACTOR_TURN` | 403 Forbidden |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 422 Unprocessable Entity |
| `ERR_GOODWILL_REQUIRES_GOOD_CREDIT` | 422 Unprocessable Entity |
| `ERR_ORDER_EXCEEDS_COMMITMENT` | 422 Unprocessable Entity |
| `ERR_HIRE_EXCEEDS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CANCEL_QUANTITY_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
