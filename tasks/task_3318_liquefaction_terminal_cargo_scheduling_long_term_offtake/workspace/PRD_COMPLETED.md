# Liquefaction Terminal Cargo Scheduling API - Product Requirements Document

## 1. Introduction

A liquefaction terminal that sells LNG under long-term sale and purchase agreements operates at the intersection of three hard-to-reconcile clocks: the multi-decade commercial calendar of offtake contracts with annual contract quantities and fixed liquefaction fees, the annual and monthly cadence of cargo scheduling with flexibility windows, and the minute-level reality of vessel arrivals, laytime, and demurrage. On top of that, the physical plant itself is not static — new liquefaction trains pass through construction, commissioning, and commercial operation, and existing trains periodically go into maintenance turnarounds that take berths and feed-gas pipelines out of service with them.

This document specifies the Liquefaction Terminal Cargo Scheduling API. The system manages buyer registration and long-term agreement execution, annual delivery program construction with cargo slot allocation under a contractual quantity cap, feed-gas nomination against pipeline day schedules with proration, vessel nomination and berth-window assignment, laytime accounting with two alternative billing bases, cargo cancellation economics including fixed-fee recovery and feed-gas resale, and maintenance turnaround scheduling with terminal-wide production impact. A logical clock governs all temporal reasoning in the system; physical time is never consulted.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request carries `X-User-ID` to identify the acting principal and `X-User-Role` to specify their operational capacity. The system recognizes five roles, spelled exactly: `TerminalOperator`, `CommercialManager`, `GasScheduler`, `MarineScheduler`, and `CustomerRep`. A request whose headers are missing or malformed, or whose role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same error applies when a `CustomerRep` performs a state-changing operation — ADP confirmation, vessel nomination, notice-of-readiness tender, cargo cancellation, feed-gas nomination, laytime agreement or dispute — against a resource whose owning buyer does not match their identity. Read (GET) endpoints perform no ownership check: any authenticated role may fetch any resource.

Identity semantics differ across roles and must be understood precisely. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that traces back to a buyer — an SPA, an ADP, a cargo slot, a vessel call, a laytime statement — compare the resource's owning-customer field to `X-User-ID`. When `X-User-Role` is `TerminalOperator`, `CommercialManager`, `GasScheduler`, or `MarineScheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proposed_by_user_id` and `approved_by_user_id` on a turnaround) but never compares it to any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, where `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. The Logical Clock

The terminal's notion of "now" is a server-managed logical clock, never wall-clock time. At startup, before any clock-setting call, the current logical UTC is exactly `2026-09-01T00:00:00Z`. An admin-only test-driving capability — restricted to the `TerminalOperator` role — advances the clock to a supplied `to_iso8601` instant; the clock never falls back to wall-clock time between calls. Every timestamp the system writes on its own (notice-of-readiness, all-fast, departure, cancellation registration) is stamped from this clock, and every temporal validation (cancellation notice, turnaround start gating, SPA expiry, reconciliation timing) is evaluated against it. Certain system transitions are lazy: the SPA `EXPIRED` transition, for example, is applied on any subsequent read or write of the SPA once the clock has passed the contract's final instant, not by a background sweep.

### 2.5. Common Resource Properties

Every primary resource in the system — customers, SPAs, trains, annual delivery programs, cargo slots, berths, vessel calls, laytime statements, pipelines, pipeline day schedules, feed gas nominations, cargo cancellations, feed gas resales, and maintenance turnarounds — carries a standard set of system-managed fields:

- `id` (string): a unique, system-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp recording when the resource was created, rendered per the timestamp-rendering rule below.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, rendered per the timestamp-rendering rule below.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation, including every state transition and every system-driven cascade that touches the resource.

Timestamp-rendering rule: every datetime the system stores or echoes — `created_at` and `updated_at` on every resource, every logical-clock stamp such as `nor_tendered_at`, `berthed_at`, `departed_at`, `cancelled_at`, and `laytime_start_at`, stored window bounds such as a cargo slot's or vessel call's `window_start`/`window_end`, and the `current_utc` echo of the clock-setting endpoint — is rendered with exactly three fractional digits when the underlying instant carries a non-zero sub-second component, and with no fractional digits at all (whole seconds, for example `2026-09-01T00:00:00Z`) when the underlying instant's sub-second component is zero. The startup default clock of §2.4 therefore renders as exactly `2026-09-01T00:00:00Z`. This rule governs stored timestamps only; the envelope's `api_request_timestamp` of §2.2 always carries three fractional digits.

Recomputing a derived quantity on a parent (for example, an ADP's scheduled quantity after a slot shift) is a mutation of that parent: its `updated_at` refreshes and its `version` increments.

Lifecycle-bearing resources also expose a system-managed `status` field whose value is one of the enumerated states for that resource's state machine; `status` changes only through the transitions described in §3, never through direct writes.

### 2.6. Nested Resource Retrieval

Requests targeting nested resources validate path identifiers sequentially from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Body-supplied foreign-key references — `customer_id`, `spa_id`, `berth_id`, `cargo_slot_id`, and their analogues — are likewise validated for existence, and a dangling reference produces the same `ERR_NOT_FOUND`.

### 2.7. Monetary Values, Quantities, and Precision

All monetary amounts (invoice values, demurrage amounts, fixed fees, credits, settlement figures) are computed with decimal arithmetic and stored and returned at exactly 2 decimal places using round-half-up. Where a calculation has intermediate steps, each numbered step of the calculation rounds half-up to 2 decimal places before the next step consumes it. Hour quantities in laytime accounting are carried at 2 decimal places, round-half-up. LNG and gas volumes are integer MMBTU unless a specific rule says otherwise (the feed-gas requirement rounds up to a whole MMBTU; the proration algorithm allocates whole MMBTU).

### 2.8. Optimistic Concurrency Control

Two write operations in the system require the client to declare the version of the parent aggregate it last observed, and both reject a mismatch with `ERR_STALE_VERSION` (HTTP 412). In both cases the expected-version field is optional in the body: omitting it skips the check, and a present-but-non-integer value is rejected with `ERR_INVALID_REQUEST`; only a present integer that differs from the parent's current `version` produces `ERR_STALE_VERSION`.

First, creating a vessel nomination against a cargo slot requires the request to carry `expected_cargo_slot_version` matching the cargo slot's current `version`. A nomination legitimately supersedes a prior `NOMINATED` vessel call, so a request carrying a stale expected version must fail rather than supersede a call the client never saw. Second, creating a new annual delivery program revision requires `expected_spa_version` matching the owning SPA's current `version`; a new revision supersedes the prior revision for the same contract year, so a stale expected version must fail rather than silently supersede state the client never observed. Endpoints not listed here take no version field at all; the version-check failure, when it occurs, carries HTTP status 412 and the error id `ERR_STALE_VERSION`.

### 2.9. Validation Order

When several checks could reject the same request, the system evaluates them in a fixed order so that the surfaced error is deterministic: authentication and role authorization first, then existence of every path identifier and referenced body foreign key, then state legality of the requested transition, then business checks in their declared sequence — physical safety compatibility, berth-window overlap, turnaround interval overlap, cancellation-notice sufficiency, slot-window validity, turnaround segregation of duties, commissioning completeness, day-schedule capacity and gas-day uniqueness, nomination quantity bounds, resale volume bounds, referential prerequisites (commercial train present, pipeline serviceable, berth serviceable, reconciliation timing), the ACQ fiscal cap — and finally body-schema conformance. A request failing an earlier check never surfaces a later check's error.

### 2.10. Terminal-Wide Integrity and Cascades

The plant is one physical system, and the data model reflects that. While any maintenance turnaround on any train is in progress, every berth is taken `OUT_OF_SERVICE` and every pipeline enters `OUTAGE`; when the last in-progress turnaround completes, all berths return to `IN_SERVICE` and all pipelines return to `IN_SERVICE`. Cargo slots whose windows collide with a turnaround are shifted automatically by the system, and each such shift recomputes the owning delivery program's quantities. Cancelling a cargo slot cuts its feed-gas nominations and re-runs proration on the affected day schedules. The lazy SPA `EXPIRED` transition of §3.1 is applied on the SPA fetch, on the SPA's ADP listing, on the customer SPA listing, on commence-deliveries, and on ADP creation — each of these refreshes the SPA before acting. These cascades execute atomically with the triggering transition, and every resource they touch observes the `version` and `updated_at` discipline of §2.5.

## 3. Business Logic & Workflows

### 3.1. Buyers and Long-Term Agreements

A `TerminalOperator` registers a buyer by supplying the buyer's `legal_name`, a `credit_rating` drawn from `AAA`, `AA`, `A`, or `BBB`, and optionally a `billing_currency` which defaults to `USD` when omitted. Once registered, a `CommercialManager` executes a long-term sale and purchase agreement against the buyer. The SPA is created with the buyer's `customer_id`, the first contract year `contract_year_start`, the number of contract years `term_years` (at least 1), the `annual_contract_quantity_mmbtu` per contract year (greater than zero), the `fixed_liquefaction_fee_usd_per_mmbtu` payable even on cancelled cargoes, the `commodity_multiplier` applied to the commodity index (for example 1.15 for 115% of Henry Hub), the `commodity_index` itself as one of `HENRY_HUB`, `TTF`, or `JKM`, the `destination_flexibility` of `FOB` (the customer controls destination) or `DES` (the terminal delivers), the `title_transfer_point` of `LOADING_FLANGE` or `DISCHARGE_PORT`, the `cancellation_notice_days` minimum whole days of notice before a cargo's window start (zero or more), the annual take-or-pay `tolerance_pct` as a fraction between 0 and 1 inclusive, and the `estimated_index_price_usd_per_mmbtu` used for provisional invoicing (greater than zero).

An SPA is born `EXECUTED`. Once at least one liquefaction train anywhere at the terminal has reached `COMMERCIAL_OPERATION`, a `CommercialManager` may commence deliveries, moving the SPA from `EXECUTED` to `DELIVERIES_COMMENCED`; attempting this with no commercial train in service is rejected with `ERR_NO_COMMERCIAL_TRAIN`, and attempting it twice or against an already-expired SPA is rejected with `ERR_SPA_INVALID_STATE`. The SPA's final transition is driven by the logical clock: when the current logical UTC reaches or passes the first instant after the last contract year — that is, the start of the year obtained by adding `term_years` to `contract_year_start` — the SPA moves from `DELIVERIES_COMMENCED` to `EXPIRED`, applied lazily on the next read or write of the agreement. Every SPA mutation increments its `version`; a lazily applied `EXPIRED` transition is itself such a mutation, refreshing `updated_at` and incrementing `version` at the moment it fires.

### 3.2. Trains: Construction, Commissioning, and Commercial Operation

A `TerminalOperator` registers a liquefaction train with a unique `name`, a `design_capacity_mtpa` nameplate capacity, a `daily_capacity_mmbtu` assumed daily LNG output while commercially operating, and the `commissioning_cargoes_required` count of testing cargoes that must complete before commercial operation (zero or more). The train starts in `CONSTRUCTION`.

Beginning commissioning moves the train from `CONSTRUCTION` to `COMMISSIONING`; repeating the call or declaring COD straight from construction is rejected with `ERR_TRAIN_INVALID_STATE`. While commissioning, the operator records each completed testing cargo via a self-transition that stays in `COMMISSIONING` and increments `commissioning_cargoes_completed` by one; the recording call carries a `proceeds_usd` amount for the test cargo. Declaring commercial operation moves the train from `COMMISSIONING` to `COMMERCIAL_OPERATION` and sets the `cod_date` supplied in the request. The COD declaration is gated: the recorded `commissioning_cargoes_completed` must be at least `commissioning_cargoes_required`, and the request's `performance_test_passed` flag must be true; failing either condition is rejected with `ERR_COMMISSIONING_INCOMPLETE`. A train's terminal state is `DECOMMISSIONED`, and the only other in-service interruption — turnaround — is covered in §3.8.

### 3.3. Building the Annual Delivery Program

Each contract year of a live SPA gets an **Annual Delivery Program**. A `CommercialManager` creates the first ADP for a given contract year by naming the parent `spa_id` and the `contract_year` (which must fall within the SPA's term); the request must also carry `expected_spa_version` per §2.8. The first revision receives `revision_no` 1 and is born `DRAFT`. Creating another ADP for the same SPA and contract year produces the next revision (`revision_no` increments per superseding revision) and flips the prior revision — whatever its state, `DRAFT`, `PROPOSED`, or `CONFIRMED` — to `SUPERSEDED`; the superseded revision's non-`CANCELLED` cargo slots are re-parented to the new revision (their `adp_id` changes), and the scheduled and unallocated quantities on both revisions are recomputed, with both revisions' versions incremented, and every re-parented slot itself observing the `version` and `updated_at` mutation discipline of §2.5. The SPA's `version` also increments when a new revision is created.

Into a `DRAFT` ADP, the commercial desk adds cargo slots, each defined by a flexibility `window_start` (inclusive), a `window_end` (exclusive) that must be strictly after the window start, and a `quantity_mmbtu` greater than zero. The slot window must lie entirely within the ADP's contract year — from the first instant of the year up to, but not including, the first instant of the following year — and a window violating either bound is rejected with `ERR_SLOT_WINDOW_INVALID`; adding a slot to a program that is no longer `DRAFT` is rejected with `ERR_ADP_INVALID_STATE`. Slot creation computes the cargo's `scheduled_feed_gas_mmbtu` (see §3.6) and recomputes the program's `scheduled_quantity_mmbtu` and `unallocated_quantity_mmbtu`, incrementing the ADP's `version`.

The ADP then walks its approval gauntlet in order. Proposing by a `CommercialManager` moves `DRAFT` to `PROPOSED` and requires at least one cargo slot — proposing an empty program is rejected with `ERR_ADP_INVALID_STATE`. Confirming is the buyer's act: a `CustomerRep` whose `X-User-ID` equals the owning SPA's `customer_id` moves `PROPOSED` to `CONFIRMED`, and the system enforces the fiscal cap — the sum of the program's cargo-slot quantities must not exceed the SPA's `annual_contract_quantity_mmbtu`, or the confirmation is rejected with `ERR_ACQ_EXCEEDED`. Locking by a `CommercialManager` moves `CONFIRMED` to `LOCKED`. Out-of-order transitions (confirming a draft, locking a draft) are rejected with `ERR_ADP_INVALID_STATE`. Each transition increments the ADP's `version`.

Three computed quantities track the program's posture at all times: `scheduled_quantity_mmbtu` is the sum of `quantity_mmbtu` over the program's non-`CANCELLED` cargo slots; `cancelled_quantity_mmbtu` is the same sum over `CANCELLED` slots; `unallocated_quantity_mmbtu` is the SPA's annual contract quantity minus the scheduled quantity minus the cancelled quantity.

### 3.4. From Slot to Ship: Vessel Nomination and Berth Assignment

A cargo slot carries two parallel status dimensions. Its `lift_status` tracks the physical lifting lifecycle — `SCHEDULED`, `VESSEL_NOMINATED`, `BERTH_ASSIGNED`, `LOADED`, `CANCELLED`, `RESCHEDULED` — while its `billing_status` tracks invoicing — `UNBILLED`, `PROVISIONALLY_INVOICED`, `FINAL_INVOICED` — and the two evolve independently.

When the owning ADP is `CONFIRMED` or `LOCKED`, the buyer's `CustomerRep` nominates a vessel against a `SCHEDULED` slot, supplying `vessel_name`, `imo_number`, `vessel_loa_m`, `vessel_dwt_t`, the contract `demurrage_rate_usd_per_day` (greater than zero), and `expected_cargo_slot_version` per §2.8. This creates a `VesselCall` in `NOMINATED` linked to the slot and moves the slot's `lift_status` from `SCHEDULED` to `VESSEL_NOMINATED`, incrementing the slot's `version`. If the slot is already `VESSEL_NOMINATED` and its current call is still `NOMINATED`, a fresh nomination is permitted: the prior call moves to `SUPERSEDED` and the new call takes its place; a superseded call leaves the slot in `VESSEL_NOMINATED` under the new call — the slot's `lift_status` never regresses to `SCHEDULED` on a supersede. Nominating against a `CANCELLED` or `LOADED` slot is rejected with `ERR_SLOT_INVALID_STATE`, as is nominating against a `BERTH_ASSIGNED` or `RESCHEDULED` slot (a slot whose current call is `ACCEPTED` or further along the arrival sequence is no longer nominatable).

A `MarineScheduler` then accepts a `NOMINATED` call, assigning a `berth_id` and an assigned berth window with its own `window_start` and `window_end`. Acceptance enforces three checks. The berth must exist and be `IN_SERVICE` — a berth knocked out by a turnaround in progress yields `ERR_BERTH_NOT_SERVICEABLE`. The vessel must physically fit: its `vessel_loa_m` must not exceed the berth's `max_loa_m` and its `vessel_dwt_t` must not exceed the berth's `max_dwt_t`, with violations rejected as `ERR_VESSEL_BERTH_INCOMPATIBLE`. The assigned window must lie within the cargo slot's flexibility window — its start at or after the slot's `window_start` and its end at or before the slot's `window_end` — and must not conflict with any other accepted-or-later call (`ACCEPTED`, `NOR_TENDERED`, `BERTHED`, or `DEPARTED`) on the same berth under the berth-window overlap rule of §3.5, with conflicts rejected as `ERR_BERTH_WINDOW_OVERLAP`. An assigned window whose start is not strictly before its end is rejected with `ERR_INVALID_REQUEST`. On success the call stores its berth and window, moves from `NOMINATED` to `ACCEPTED`, and the slot's `lift_status` advances from `VESSEL_NOMINATED` to `BERTH_ASSIGNED`.

Thereafter the call walks the arrival sequence in strict order, each step stamped from the logical clock and each step incrementing the call's `version`. The buyer's `CustomerRep` tenders notice of readiness, moving `ACCEPTED` to `NOR_TENDERED` and recording `nor_tendered_at`. A `MarineScheduler` then records the vessel all-fast, moving `NOR_TENDERED` to `BERTHED` with `berthed_at`, and finally records departure, moving `BERTHED` to `DEPARTED` with `departed_at`. Attempting any of these out of order — berthing before NOR, departing before berthed — is rejected with `ERR_CALL_INVALID_STATE`. Departure is the billing pivot: the slot's `lift_status` moves from `BERTH_ASSIGNED` to `LOADED`, its provisional invoice is computed per §3.5, and its `billing_status` moves from `UNBILLED` to `PROVISIONALLY_INVOICED`, with the slot's `version` incremented.

After departure, a `CommercialManager` issues the final invoice by supplying the settled `actual_index_price_usd_per_mmbtu`. This requires the slot to be `LOADED` with `billing_status` exactly `PROVISIONALLY_INVOICED` — invoicing before departure or after finalization is rejected with `ERR_SLOT_INVALID_STATE` — and it computes `final_invoice_usd`, moves `billing_status` to `FINAL_INVOICED`, and leaves `lift_status` untouched at `LOADED`, incrementing the slot's `version`.

### 3.5. Cargo Invoicing and Laytime Accounting

The berth-window overlap rule referenced in §3.4 is pinned here: two windows conflict when they intersect as half-open intervals after each is padded by a 2-hour changeover buffer — a candidate window `[ws, we)` conflicts with an existing window `[cs, ce)` whenever `ws < ce + 2h` and `we > cs - 2h`; abutting inside the buffer counts as a conflict, while a gap of exactly two hours on each side does not.

The cargo invoice amount is a tiered-price calculation with two variants. In both variants the invoice is the slot's `quantity_mmbtu` multiplied by the sum of the SPA's `fixed_liquefaction_fee_usd_per_mmbtu` and the SPA's `commodity_multiplier` times an index price, rounded half-up to 2 decimal places. The provisional variant fires at vessel departure and uses the SPA's `estimated_index_price_usd_per_mmbtu` as the index price, recording the result as `provisional_invoice_usd`. The final variant fires at final-invoice issuance and uses the supplied `actual_index_price_usd_per_mmbtu`, recording `final_invoice_usd`; for an identical quantity the two variants differ whenever the estimated and actual index prices differ.

Laytime is accounted per completed vessel call. Once a call is `DEPARTED`, a `MarineScheduler` creates a laytime statement naming the covered call via `vessel_call_id`, the `billing_basis` — `SOF_BASIS` for the statement-of-facts variant or `PUMP_LOG_BASIS` for the pump-log variant — optionally a list of `excluded_periods`, each an interval with a `start`, an `end`, and a `reason` that must lie within the span from laytime start to departure (terminal-fault or weather time not counting against the charterer), and optionally `pump_hours`, which is required whenever the billing basis is `PUMP_LOG_BASIS` (omitting it there is rejected with `ERR_INVALID_REQUEST`; a non-numeric `pump_hours`, a non-list `excluded_periods`, and an excluded period whose end precedes its start are likewise rejected with `ERR_INVALID_REQUEST`). Submitting a statement for a call that has not departed is rejected with `ERR_CALL_INVALID_STATE`.

The statement derives its figures as follows, all hour values at 2 decimal places round-half-up and all money at 2 decimal places round-half-up. Laytime begins at `laytime_start_at`, the earlier of two instants: six hours after `nor_tendered_at`, or `berthed_at`. The `allowed_laytime_hours` is the slot quantity divided by the terminal loading rate of 240,000 MMBTU per hour, rounded up to a whole number of hours, plus a berth allowance of 4 hours. The `elapsed_hours` is the difference between `departed_at` and `laytime_start_at` expressed in hours, rounded half-up to 2 decimal places. Under the statement-of-facts variant, the rounding order is pinned: each excluded period's duration is first rounded half-up to whole minutes, the rounded periods are summed and converted to hours (that hour figure itself rounded half-up to 2 decimal places), and only then is the sum subtracted from the rounded `elapsed_hours` to yield `used_laytime_hours_sof`, itself rounded half-up to 2 decimal places (summing raw seconds and rounding once at the end yields a different cent result and is not permitted). Under the pump-log variant, `used_laytime_hours_pumplog` is `pump_hours` plus a connection allowance of 2 hours, rounded half-up to 2 decimal places; this figure, and the pump-log demurrage amount, are null when `pump_hours` was not supplied. Demurrage accrues only when used laytime is strictly greater than allowed laytime — at exact equality the amount is exactly zero — and equals the excess hours divided by 24 and multiplied by the call's `demurrage_rate_usd_per_day`, rounded half-up to 2 decimal places, computed independently as `demurrage_amount_sof_usd` and `demurrage_amount_pumplog_usd`; both variants' figures are computed and stored on every statement, whichever `billing_basis` was chosen. The `billed_demurrage_usd` is the variant selected by `billing_basis`; for identical calls the two variants differ whenever the pump hours plus the 2-hour connection allowance do not equal the elapsed hours minus the excluded periods.

The statement is born `SUBMITTED` with `adjusted_demurrage_usd` null until a resolution records it. The buyer's `CustomerRep` either agrees, moving `SUBMITTED` to `AGREED` and closing the matter, or disputes — optionally with a `reason` — moving `SUBMITTED` to `DISPUTED`. A `CommercialManager` resolves a disputed statement by supplying an `adjusted_demurrage_amount_usd` and optionally a `resolution_note`; resolution records the commercially agreed override in `adjusted_demurrage_usd` (which may differ from `billed_demurrage_usd`) and moves `DISPUTED` to `RESOLVED`. Agreeing after a dispute, or resolving a statement that was never disputed, is rejected with `ERR_STATEMENT_INVALID_STATE`.

### 3.6. Feed Gas: Pipelines, Day Schedules, and Proration

Every cargo slot's feed-gas requirement is fixed at creation: `scheduled_feed_gas_mmbtu` is the slot quantity multiplied by 1.10 — the terminal assumes ten percent fuel and loss over delivered LNG — rounded up to a whole MMBTU.

A `TerminalOperator` registers a feed-gas pipeline with a unique `name` and a `daily_capacity_mmbtu` ceiling; the pipeline starts `IN_SERVICE`. Against a pipeline, a `GasScheduler` opens a day schedule — naming the parent `pipeline_id`, a `gas_day` (a calendar date unique per pipeline) and the firm `capacity_mmbtu` offered that day, which must be greater than zero and no more than the pipeline's daily capacity; breaches of either rule are rejected with `ERR_SCHEDULE_CAPACITY_EXCEEDED`. The schedule is born `OPEN` and tracks three running totals: `total_nominated_mmbtu` over all nominations regardless of status, `total_confirmed_mmbtu` over `CONFIRMED` nominations (reconciled nominations keep their confirmed volume and remain counted here after reconciliation), and `total_cut_mmbtu` over `CUT` nominations plus the cut volume on `CONFIRMED` nominations (again with `RECONCILED` nominations counted alongside `CONFIRMED` for both components).

Feed-gas nominations are made against an `OPEN` schedule by either a `GasScheduler` or a `CustomerRep` — the nomination names the day schedule via `pipeline_day_schedule_id`, the `cargo_slot_id` the gas feeds, and a `nominated_mmbtu` volume greater than zero and no more than the linked slot's `scheduled_feed_gas_mmbtu`; a volume outside that band is rejected with `ERR_NOMINATION_QUANTITY_MISMATCH`. Nominating against a schedule that has been closed is rejected with `ERR_SCHEDULE_INVALID_STATE`, and nominating while the pipeline is in `OUTAGE` (a turnaround in progress) is rejected with `ERR_PIPELINE_NOT_SERVICEABLE`. A nomination is born `SUBMITTED` with `confirmed_mmbtu` zero and `cut_mmbtu` zero; each new nomination refreshes the schedule's `total_nominated_mmbtu` and, per §2.5, increments the schedule's `version`.

Closing the schedule is the allocation event. A `GasScheduler` closes an `OPEN` schedule — closing twice is rejected with `ERR_SCHEDULE_INVALID_STATE` — and the system runs the proration waterfall over the schedule's `SUBMITTED` nominations. If the total nominated volume is no more than the day's capacity, every nomination is confirmed in full: `confirmed_mmbtu` equals `nominated_mmbtu`, `cut_mmbtu` is zero, and the nomination becomes `CONFIRMED`. Otherwise a pro-rata factor is formed as the day's capacity divided by the total nominated volume, and each nomination's base allocation combines a guaranteed minimum with the pro-rata term: the pro-rata term is the nomination's volume times the factor rounded down to a whole MMBTU, the term is raised to a floor of 5,000 MMBTU when it falls below that floor — the floor itself applied as the lesser of the nomination's volume and the floor itself, so a nomination smaller than the floor is guaranteed at most its own volume — and the base allocation is then the smaller of the nominated volume and that raised term; equivalently, `min(nominated, max(min(nominated, 5000), floor(nominated × factor)))` whole MMBTU. The remainder — capacity minus the sum of base allocations — is then distributed one MMBTU at a time to the nominations with the largest fractional part of their nominated-times-factor product (the raw, un-floored product), ties on the fractional part broken by nomination creation time with the earliest first, cycling back to the head of the ranking whenever a pass through the ranked list leaves remainder undistributed, and no nomination may receive more than it nominated. A nomination whose confirmed volume comes out at zero becomes `CUT` with `cut_mmbtu` equal to its `nominated_mmbtu`; every other nomination becomes `CONFIRMED`, and every nomination the waterfall touches — including one confirmed in full — observes the `version` and `updated_at` discipline of §2.5. The waterfall's re-run after a cancellation (§3.7) operates over the schedule's remaining non-`CUT` nominations — `SUBMITTED`, `CONFIRMED`, and `RECONCILED` alike — and reallocates them by the same rules, with `CONFIRMED` and `RECONCILED` nominations keeping their status when their confirmed volume remains non-zero and becoming `CUT` when it comes out at zero. The schedule's three totals are then recomputed, the schedule becomes `CLOSED`, and its `version` increments. The conservation invariant holds at all times: the sum of confirmed volumes plus the sum of cut volumes equals the sum of nominated volumes.

After the gas has flowed, a `GasScheduler` reconciles a `CONFIRMED` nomination, moving it to `RECONCILED`; the nomination's day schedule must already be `CLOSED`, and reconciling a nomination that is not `CONFIRMED` is rejected with `ERR_NOMINATION_INVALID_STATE`.

### 3.7. Cargo Cancellation and Feed-Gas Resale

A buyer may forgo a cargo. The buyer's `CustomerRep` cancels a slot whose `lift_status` is `SCHEDULED`, `VESSEL_NOMINATED`, or `BERTH_ASSIGNED` — cancelling a `LOADED` slot is rejected with `ERR_SLOT_INVALID_STATE`. The cancellation is notice-gated: the whole days between the current logical instant and the slot's `window_start`, rounded down, must be at least the SPA's `cancellation_notice_days`, otherwise the request is rejected with `ERR_INSUFFICIENT_NOTICE` — equality with the SPA's `cancellation_notice_days` is sufficient. On success a `CargoCancellation` is created in `REGISTERED`, stamped with `cancelled_at` from the logical clock and the computed `notice_days_provided`, and the fixed fee `fixed_fee_due_usd` is computed immediately as the slot's `quantity_mmbtu` times the SPA's `fixed_liquefaction_fee_usd_per_mmbtu`, rounded half-up to 2 decimal places. The cancellation is also born with `resale_credit_usd` zero and `net_due_usd` null, both replaced by the settlement computation of §3.7.

Cancellation cascades widely. The slot's `lift_status` becomes `CANCELLED`. Every feed-gas nomination of the slot still in `SUBMITTED` or `CONFIRMED` becomes `CUT` with `confirmed_mmbtu` set to zero and `cut_mmbtu` set to its `nominated_mmbtu` (a nomination already `RECONCILED` is left untouched, since its gas has already flowed), and each such cut triggers a recompute of its day schedule's totals and a fresh run of the proration waterfall over that schedule's remaining non-`CUT` nominations; the waterfall re-run fires only on a schedule that is already `CLOSED`, while an `OPEN` schedule is just re-totalled, and either way the schedule's `version` increments. If the slot had a `NOMINATED` vessel call, that call becomes `SUPERSEDED`; if it had an `ACCEPTED` call, that call likewise becomes `SUPERSEDED` and its berth window is freed. The owning ADP's scheduled, cancelled, and unallocated quantities are recomputed, and the slot's `version` increments.

While the cancellation is `REGISTERED`, a `GasScheduler` may offer part of the freed feed gas for resale by naming the parent `cargo_cancellation_id`, creating a `FeedGasResale` in `OFFERED` with an `offered_volume_mmbtu` greater than zero; the cumulative offered volume across all of the cancellation's resales that are not `UNSOLD` must never exceed the cancelled slot's `scheduled_feed_gas_mmbtu`, and a breach — including a non-positive offered volume — is rejected with `ERR_RESALE_VOLUME_EXCEEDED`. Offering a resale against an already-`SETTLED` cancellation is rejected with `ERR_CANCELLATION_INVALID_STATE`. A `GasScheduler` records an achieved sale by supplying the `sale_price_usd_per_mmbtu` (greater than zero), which moves the resale from `OFFERED` to `SOLD` and computes `gross_proceeds_usd` as the offered volume times the sale price, rounded half-up to 2 decimal places; selling a resale that is no longer `OFFERED` is rejected with `ERR_RESALE_INVALID_STATE`.

Settlement closes the loop. A `CommercialManager` settles a `REGISTERED` cancellation — settling an already-settled one is rejected with `ERR_CANCELLATION_INVALID_STATE` — and the settlement computation runs in a pinned order, each step rounding half-up to 2 decimal places. First, the fixed fee due is as recorded at registration. Second, the gross proceeds are the sum of `gross_proceeds_usd` over the cancellation's `SOLD` resales. Third, the handling fee is 2% of the fixed fee due — computed on the gross fee, never on the net, which is what breaks the otherwise circular dependency. Fourth, the pipeline tariff is 0.35 USD per MMBTU times the sum of `offered_volume_mmbtu` over the `SOLD` resales. Fifth, `resale_credit_usd` is the lesser of the fixed fee due and the greater of zero and the gross proceeds minus the handling fee minus the pipeline tariff. Sixth, `net_due_usd` is the fixed fee due minus the resale credit. Any resale still `OFFERED` at settlement is automatically flipped to `UNSOLD`. The cancelled slot's `billing_status` moves directly from `UNBILLED` to `FINAL_INVOICED` — the fixed fee is the final bill for a cancelled cargo, and since a slot can only be cancelled from `UNBILLED` (§3.4 restricts nomination, berthing, and departure against `CANCELLED` slots), the transition always applies — and the cancellation becomes `SETTLED`.

### 3.8. Maintenance Turnarounds and Terminal-Wide Impact

A `TerminalOperator` proposes a maintenance turnaround on a train by supplying a `planned_start_date` and a `planned_end_date`, both calendar dates, with the end date on or after the start date; the interval is closed — both the first and the last day are out of service. The proposal names the train via its `train_id`, records the proposer's `X-User-ID` as `proposed_by_user_id`, and is born `PROPOSED` — its `status` field tracking the turnaround lifecycle. The new interval must not intersect any non-`CANCELLED` turnaround of the same train — touching end and start dates count as overlap — and a clash is rejected with `ERR_TURNAROUND_OVERLAP`.

Approval is a segregated duty: a `TerminalOperator` approves a `PROPOSED` turnaround, but the approver's `X-User-ID` must differ from `proposed_by_user_id`, with violations rejected as `ERR_TURNAROUND_SOD_VIOLATION`; the same interval-overlap check is enforced again at approval. Approval records `approved_by_user_id` and computes the `lost_production_mmbtu` as the turnaround length in days — end date minus start date plus one, since both endpoints count — multiplied by the train's `daily_capacity_mmbtu`. Approving twice is rejected with `ERR_TURNAROUND_INVALID_STATE`.

Beginning an `APPROVED` turnaround is allowed once the current logical UTC date reaches `planned_start_date`, and requires the train to be in `COMMERCIAL_OPERATION`. Beginning before the planned start date or from any status other than `APPROVED` is rejected with `ERR_TURNAROUND_INVALID_STATE`; beginning against a train not in `COMMERCIAL_OPERATION` is rejected with `ERR_TRAIN_INVALID_STATE`. The begin transition sets off the terminal-wide cascade: the train moves from `COMMERCIAL_OPERATION` to `TURNAROUND`; every berth in the terminal goes `OUT_OF_SERVICE` and every pipeline goes `OUTAGE`; every cargo slot terminal-wide whose half-open window intersects the turnaround's closed interval — intersection meaning the window starts before the day after the turnaround's end date and ends after the turnaround's start date — and whose `lift_status` is `SCHEDULED` or `VESSEL_NOMINATED` is shifted forward: both `window_start` and `window_end` advance by the turnaround length in days, the slot passes through `RESCHEDULED` and immediately back to `SCHEDULED` once the shift completes (the system applies this reversion right after the shift, since the window now sits in a non-conflicting position), and each shift recomputes the owning ADP's `scheduled_quantity_mmbtu` and `unallocated_quantity_mmbtu` and increments the ADP's `version`. The turnaround records how many slots were shifted in `shifted_cargo_slot_count`.

Completing the `IN_PROGRESS` turnaround returns the train from `TURNAROUND` to `COMMERCIAL_OPERATION`, moves the turnaround to `COMPLETED`, and — when no turnaround anywhere remains `IN_PROGRESS` — returns every berth to `IN_SERVICE` and every pipeline to `IN_SERVICE`. Completing a turnaround that is not `IN_PROGRESS` is rejected with `ERR_TURNAROUND_INVALID_STATE`, and completing one whose train is not in `TURNAROUND` is rejected with `ERR_TRAIN_INVALID_STATE`. The turnaround lifecycle carries no exposed cancel operation; a `CANCELLED` turnaround state does not occur in practice, and any turnaround in any state remains in force for the overlap checks of this section, which consider all non-`CANCELLED` turnarounds.

### 3.9. Annual Reconciliation and Take-or-Pay Deficiency

After a contract year closes, the commercial desk runs the annual reconciliation on a `LOCKED` ADP. The call requires the current logical UTC to have reached or passed the first instant of the year following the ADP's contract year — reconciliation at exactly that first instant is permitted — and the ADP to be `LOCKED`; running it earlier or against a program in any other state is rejected with `ERR_RECONCILE_PREMATURE`. The caller supplies the `reference_index_price_usd_per_mmbtu` for the year (greater than zero; a non-positive price is rejected with `ERR_INVALID_REQUEST`).

Reconciliation computes three figures and stores them on the ADP, incrementing its `version`. The `delivered_equivalent_mmbtu` is the sum of `quantity_mmbtu` over the program's `LOADED` slots plus the same sum over its `CANCELLED` slots — a cancelled cargo still counts toward take-or-pay because the fixed fee was paid. The contractual lower bound is the annual contract quantity multiplied by one minus the `tolerance_pct`, and the `shortfall_mmbtu` is the greater of zero and the lower bound rounded down to a whole MMBTU minus the delivered equivalent; when the delivered equivalent exactly equals the rounded-down bound, the shortfall is zero and no deficiency arises — the bound is inclusive. The `deficiency_amount_usd` is the shortfall multiplied by the sum of the SPA's `fixed_liquefaction_fee_usd_per_mmbtu` and the `commodity_multiplier` times the reference index price, rounded half-up to 2 decimal places.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new, distinct resources to a collection return a `201 Created` status code. Operations that modify an existing resource — including every state transition — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/customers` | Register a buyer | TerminalOperator |
| GET | `/api/customers/{id}` | Fetch one customer | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/customers/{id}/spas` | List SPAs of a customer (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/spas` | Execute a long-term sale and purchase agreement | CommercialManager |
| GET | `/api/spas/{id}` | Fetch one SPA (applies lazy EXPIRED transition) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/spas/{id}/adps` | List annual delivery programs of an SPA (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/spas/{id}/commence-deliveries` | Move SPA to DELIVERIES_COMMENCED once a train is commercial | CommercialManager |
| POST | `/api/trains` | Register a liquefaction train | TerminalOperator |
| GET | `/api/trains/{id}` | Fetch one train | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/trains/{id}/begin-commissioning` | Move train from CONSTRUCTION to COMMISSIONING | TerminalOperator |
| POST | `/api/trains/{id}/record-commissioning-cargo` | Record one completed testing cargo | TerminalOperator |
| POST | `/api/trains/{id}/declare-cod` | Declare commercial operation when testing cargoes complete | TerminalOperator |
| POST | `/api/trains/{id}/turnarounds` | Propose a maintenance turnaround window | TerminalOperator |
| GET | `/api/trains/{id}/turnarounds` | List turnarounds of a train (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/turnarounds/{id}` | Fetch one turnaround | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/turnarounds/{id}/approve` | Approve a proposed turnaround (segregation of duties) | TerminalOperator |
| POST | `/api/turnarounds/{id}/begin` | Begin an approved turnaround; cascades train, slots, berths, pipelines | TerminalOperator |
| POST | `/api/turnarounds/{id}/complete` | Complete an in-progress turnaround; restore service | TerminalOperator |
| POST | `/api/adps` | Create an ADP revision; supersedes any prior revision; OCC on SPA version | CommercialManager |
| GET | `/api/adps/{id}` | Fetch one ADP | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/adps/{id}/propose` | Move ADP from DRAFT to PROPOSED | CommercialManager |
| POST | `/api/adps/{id}/confirm` | Confirm a proposed ADP; enforces ACQ cap | CustomerRep |
| POST | `/api/adps/{id}/lock` | Lock a confirmed ADP | CommercialManager |
| POST | `/api/adps/{id}/reconcile` | Annual reconciliation on a LOCKED ADP after contract year end | CommercialManager |
| POST | `/api/adps/{id}/cargo-slots` | Add a cargo slot with a flexibility window to a DRAFT ADP | CommercialManager |
| GET | `/api/adps/{id}/cargo-slots` | List cargo slots of an ADP (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/cargo-slots/{id}` | Fetch one cargo slot | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/cargo-slots/{id}/vessel-nominations` | Nominate a vessel against a slot; OCC on slot version | CustomerRep |
| GET | `/api/cargo-slots/{id}/vessel-calls` | List vessel calls of a cargo slot (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/cargo-slots/{id}/cancellations` | Cancel a cargo; pays fixed fee, cascades nomination cuts | CustomerRep |
| GET | `/api/cargo-slots/{id}/cancellations` | List cancellations of a cargo slot (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/cargo-slots/{id}/nominations` | List feed gas nominations of a cargo slot (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/cargo-slots/{id}/issue-final-invoice` | Issue final invoice at the settled index price | CommercialManager |
| POST | `/api/berths` | Register a loading berth | TerminalOperator |
| GET | `/api/berths/{id}` | Fetch one berth | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/berths/{id}/vessel-calls` | List vessel calls assigned to a berth (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/vessel-calls/{id}` | Fetch one vessel call | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/vessel-calls/{id}/accept` | Accept a nominated call and assign berth window | MarineScheduler |
| POST | `/api/vessel-calls/{id}/tender-nor` | Vessel tenders notice of readiness | CustomerRep |
| POST | `/api/vessel-calls/{id}/berth` | Vessel all-fast at berth | MarineScheduler |
| POST | `/api/vessel-calls/{id}/depart` | Vessel departs; slot becomes LOADED with provisional invoice | MarineScheduler |
| POST | `/api/vessel-calls/{id}/laytime-statements` | Create and submit a laytime statement for a DEPARTED call | MarineScheduler |
| GET | `/api/vessel-calls/{id}/laytime-statements` | List laytime statements of a vessel call (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/laytime-statements/{id}` | Fetch one laytime statement | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/laytime-statements/{id}/agree` | Customer accepts the statement | CustomerRep |
| POST | `/api/laytime-statements/{id}/dispute` | Customer disputes the statement | CustomerRep |
| POST | `/api/laytime-statements/{id}/resolve` | Resolve a disputed statement with an adjusted demurrage amount | CommercialManager |
| POST | `/api/pipelines` | Register a feed gas pipeline | TerminalOperator |
| GET | `/api/pipelines/{id}` | Fetch one pipeline | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/pipelines/{id}/day-schedules` | Create an OPEN day schedule for a gas day | GasScheduler |
| GET | `/api/pipelines/{id}/day-schedules` | List day schedules of a pipeline (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/pipeline-day-schedules/{id}` | Fetch one day schedule with totals | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/pipeline-day-schedules/{id}/close` | Close nomination window and run proration | GasScheduler |
| POST | `/api/pipeline-day-schedules/{id}/nominations` | Nominate feed gas for a cargo slot against an OPEN schedule | GasScheduler, CustomerRep |
| GET | `/api/pipeline-day-schedules/{id}/nominations` | List nominations of a day schedule (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| GET | `/api/feed-gas-nominations/{id}` | Fetch one nomination | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/feed-gas-nominations/{id}/reconcile` | Reconcile a CONFIRMED nomination after flow | GasScheduler |
| GET | `/api/cargo-cancellations/{id}` | Fetch one cancellation | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/cargo-cancellations/{id}/settle` | Settle cancellation economics | CommercialManager |
| POST | `/api/cargo-cancellations/{id}/resales` | Offer part of the cancelled cargo's feed gas for resale | GasScheduler |
| GET | `/api/cargo-cancellations/{id}/resales` | List resales of a cancellation (paginated) | TerminalOperator, CommercialManager, GasScheduler, MarineScheduler, CustomerRep |
| POST | `/api/feed-gas-resales/{id}/sell` | Record the achieved sale of an offered resale | GasScheduler |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | TerminalOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SPA_INVALID_STATE` | 409 |
| `ERR_NO_COMMERCIAL_TRAIN` | 422 |
| `ERR_TRAIN_INVALID_STATE` | 409 |
| `ERR_COMMISSIONING_INCOMPLETE` | 422 |
| `ERR_TURNAROUND_INVALID_STATE` | 409 |
| `ERR_TURNAROUND_SOD_VIOLATION` | 403 |
| `ERR_TURNAROUND_OVERLAP` | 409 |
| `ERR_ADP_INVALID_STATE` | 409 |
| `ERR_ACQ_EXCEEDED` | 422 |
| `ERR_RECONCILE_PREMATURE` | 422 |
| `ERR_SLOT_INVALID_STATE` | 409 |
| `ERR_SLOT_WINDOW_INVALID` | 422 |
| `ERR_INSUFFICIENT_NOTICE` | 422 |
| `ERR_VESSEL_BERTH_INCOMPATIBLE` | 422 |
| `ERR_BERTH_WINDOW_OVERLAP` | 409 |
| `ERR_BERTH_NOT_SERVICEABLE` | 422 |
| `ERR_CALL_INVALID_STATE` | 409 |
| `ERR_STATEMENT_INVALID_STATE` | 409 |
| `ERR_SCHEDULE_INVALID_STATE` | 409 |
| `ERR_SCHEDULE_CAPACITY_EXCEEDED` | 422 |
| `ERR_PIPELINE_NOT_SERVICEABLE` | 422 |
| `ERR_NOMINATION_QUANTITY_MISMATCH` | 422 |
| `ERR_NOMINATION_INVALID_STATE` | 409 |
| `ERR_CANCELLATION_INVALID_STATE` | 409 |
| `ERR_RESALE_INVALID_STATE` | 409 |
| `ERR_RESALE_VOLUME_EXCEEDED` | 422 |
