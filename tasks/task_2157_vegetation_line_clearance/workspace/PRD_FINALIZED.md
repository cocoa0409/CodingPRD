# Vegetation Line Clearance API — Product Requirements Document

## 1. Introduction

Utilities do not lose power to wind; they lose it to trees. A distribution feeder that has drifted two years past its trim cycle will, sooner or later, pay for that drift in customer-minutes of interruption, and the crews sent to fix it will cost more than the cycle trim would have. This document specifies the server-side platform that a line-clearance contractor and its utility client jointly operate to run a vegetation management program end to end: writing trim prescriptions by voltage class and growth zone, resolving each circuit onto the prescription that governs it, budgeting a program-year work plan, mapping and releasing individual spans, booking contractor crews against those spans, recording daily production, notifying the customers whose property the crews will enter, adjudicating hazard trees that stand outside the right-of-way, permitting herbicide application, reassigning crews when a storm hits, and finally settling the contractor's invoice under either a unit-price or a time-and-materials contract.

The platform's hardest requirement is that these threads are not independent. A customer who permanently refuses access withholds units from a span, which reprices a draft invoice line, which changes the plan's committed spend against its budget ceiling. A storm that pulls a crew off a span suspends the plan and puts the circuit's cycle at risk, and demobilizing the storm has to put every one of those counters back exactly where it was. An outage attributed to a tree raises the circuit's reliability tier, which shortens the trim cycle, which moves the next-due date. Every one of these chains is specified here as a deterministic cascade with a defined order, defined rounding, and a defined conserved quantity — because the contractor gets paid from these numbers and the utility's regulator reads them.

All resources are mounted under the `/vm` prefix. The service is a pure JSON REST API with no session state: every request carries its own identity headers, and every mutation is evaluated against the server's current stored state and its logical program clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint — reads included — must present two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` holds a string that is not one of the seven roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the named role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `UtilityForester`, `ContractorPlanner`, `CrewForeman`, `CertifiedArborist`, `CustomerAdvocate`, `BillingAnalyst`, and `PlatformAdmin`. All seven may read: every retrieval and list endpoint in the catalogue accepts any of the seven. Write authority is narrowed per operation and is described alongside each workflow in §3 and summarized in the §4 table.

- The `UtilityForester` is the utility-side program owner. It alone authors and activates prescriptions, registers circuits and re-resolves their prescriptions, creates and cancels work plans, records outages, finalizes customer refusals, decides hazard trees, decides and revokes herbicide permits, declares/activates/demobilizes/closes storm events, and reviews and pays billing lines.
- The `ContractorPlanner` is the contractor-side planner. It releases plans for field execution, creates spans, maps them, releases them, starts them, completes them, cancels them, registers crews, books and releases crew assignments, and posts storm reassignments.
- The `CrewForeman` is a field foreman acting on behalf of one specific crew. It files daily production entries and records hazard-tree removals.
- The `CertifiedArborist` identifies and assesses hazard trees and requests and activates herbicide permits.
- The `CustomerAdvocate` opens premise notifications, delivers them, records the customer's response, and escalates a refusal. It cannot finalize a refusal.
- The `BillingAnalyst` drafts, submits, resubmits and voids billing lines. It cannot review, approve or pay them.
- The `PlatformAdmin` owns the logical clock and nothing else.

Identity semantics differ by role. When `X-User-Role` is `CrewForeman`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks on any resource that references a `Crew` compare the resource's crew foreign-key field to `X-User-ID`. Concretely, a `CrewForeman` filing production must name a booking whose `crew_id` equals its own `X-User-ID`, and a `CrewForeman` recording a hazard-tree removal must hold an `ACTIVE` booking, under that crew id, on the span the tree is assigned to; a mismatch is `ERR_NOT_CREW_OWNER` (HTTP 403).

When `X-User-Role` is `UtilityForester`, `ContractorPlanner`, `CertifiedArborist`, `CustomerAdvocate`, `BillingAnalyst`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `identified_by_user_id` and `assessed_by_user_id` on a hazard tree, or as `approved_by_user_id` on a herbicide permit — but it never compares those values to any entity's `id`. It does compare them to each other: an arborist may not assess a tree it identified, and that check is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The billing side enforces its own separation by role rather than by user id: the analyst that drafts and submits a line is a `BillingAnalyst`, and only a `UtilityForester` may review, approve or pay it.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be an integer, and must lie between 1 and 100 inclusive. `offset` defaults to 0 when omitted, must be an integer, and must be zero or greater; there is no upper bound on `offset`. A `limit` outside the inclusive range 1 through 100, a negative `offset`, or a non-integer value for either is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

List results are always ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of records matching the request's filters before the page window is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page.

### 2.4. Record Identity, Timestamps and the Version Counter

Every resource carries a server-minted `id`: a UUID string with no type prefix of any kind. Clients never supply an `id`, and a client-supplied `id` in a create body is ignored rather than honoured. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly three fractional-second digits, stamped from the logical clock at creation.

Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation of the record, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every mutation of that record — including mutations caused by a cascade from another entity, not just direct writes. Two entities are exceptions and are deliberately immutable once written: a production entry and an outage record carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on a `ProductionEntry` or an `OutageRecord`, and neither may be echoed on them.

Fields marked as computed or system-owned throughout this document are never accepted from the client. If a create or transition body contains such a field, the value is silently discarded; the server computes its own value and returns that. This applies to every derived counter — `planned_unit_count` on a plan, `actual_units_completed`, `refusal_blocked_unit_count`, `entry_cents`, `risk_score`, and the whole billing settlement chain among them.

### 2.5. Path Resolution and Referential Integrity

Path identifiers are resolved strictly left to right. Where a path names more than one resource, the leftmost is looked up first, and the first identifier that does not resolve determines the response — a request naming a nonexistent span and a nonexistent billing line fails on the span. Each entity type has its own not-found code: `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_WORK_PLAN_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`, `ERR_PRODUCTION_ENTRY_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_HAZARD_TREE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_STORM_EVENT_NOT_FOUND`, `ERR_BILLING_LINE_NOT_FOUND` and `ERR_OUTAGE_RECORD_NOT_FOUND`, each returned with HTTP 404.

The same rule and the same codes govern foreign keys supplied in a request body. A body naming a circuit, span, booking, crew, permit or notification that does not exist fails with that entity's not-found code before any business rule touches the request.

### 2.6. The Logical Program Clock

The server keeps a logical UTC clock rather than reading wall time. Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time. A `PlatformAdmin` moves it by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc`. Every time-sensitive evaluation in this specification reads that clock and only that clock: permit window openings and expiries, the 30-day billing dispute deadline, the rolling 36-month and program-year-to-date reliability windows, the date stamped into a circuit's `last_trim_completed_on` at cycle completion, and the `notified_at`, `submitted_at` and `completed_at` stamps.

### 2.7. Money, Units and Rounding Discipline

All money in this system is expressed in whole cents as integers — `budget_cents`, `hourly_rate_cents`, `gross_cents`, `retainage_cents`, `storm_premium_cents`, `net_payable_cents`, `mobilization_credit_cents`, `final_payable_cents`, `committed_cents` and `entry_cents` are all integer cent quantities, never decimals of dollars. Wherever a monetary result is produced by multiplication, it is rounded to a whole cent using round-half-up (a fractional remainder of exactly one half rounds away from zero).

Ratio and score outputs are carried to exactly two decimal places, also with round-half-up: `production_pct`, `crew_production_rate`, `risk_score`, `density_multiplier`, `reliability_index_36mo` and `reliability_index_ytd` all follow this rule. `cycle_months` is a whole number of months and is rounded half-up before any clamping is applied. Unit counts — `planned_unit_count`, `actual_units_completed`, `completed_unit_count`, `billable_units`, `units_trimmed`, `refusal_blocked_unit_count`, `unit_count_at_premise` — are exact integers and are never rounded.

Where a total is assembled from many parts, the point at which rounding happens is part of the contract and is stated with each calculation in §3. Two of these are load-bearing: time-and-materials value is rounded once per production entry and the rounded per-entry values are then added, and a plan's committed spend is the exact integer sum of already-rounded per-line amounts. Summing unrounded parts and rounding the total once is wrong in both cases and can differ by one or more cents.

### 2.8. Stale-Read Protection on Span and Crew Writes

Two write operations are guarded by optimistic concurrency control, because in both the server would otherwise let a client destroy or redirect something it never observed. Both guards work the same way: the request body carries a non-optional integer field holding the `version` of a parent record as the client last read it, and if that number differs from the parent's current `version` the write is refused outright.

A `POST /vm/work-orders/{id}/billing-lines` request must carry `expected_work_order_version`, holding the client's last observed `version` of the span named in the path. If the span's current `version` differs — because production was filed, a refusal was finalized, or an earlier draft was created since the client read it — the request is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412). This guard matters because a new draft legitimately supersedes any existing `DRAFT` line on the same span, voiding it; a client working from a stale view would silently discard a draft it never saw, and would price its line against a `refusal_blocked_unit_count` that has since changed.

A `POST /vm/storm-events/{id}/reassignments` request must carry `expected_crew_version`, holding the client's last observed `version` of the `Crew` named by `crew_id` in the body. If the crew's current `version` differs, the request is rejected with `ERR_STALE_CREW_VERSION` (HTTP 412). A crew that is already `STORM_DEPLOYED` may legitimately be re-attributed to a different event, so no state precondition blocks the operation; the stale-version check is the only thing standing between a planner and a crew whose bookings or posture changed after the planner's last read.

No other endpoint takes a version field. Requests to any endpoint outside these two neither require nor accept `expected_work_order_version` or `expected_crew_version`.

### 2.9. Order of Rejection

When a request violates more than one rule, exactly one error is returned, and which one is not a matter of implementation convenience. Checks are evaluated in the ascending priority order below, and the first check that fails determines both the `error_id` and the HTTP status. A later check never masks an earlier one.

1. Header presence and role validity — `ERR_UNAUTHENTICATED` (401).
2. The acting role appears on the endpoint's authorized list — `ERR_UNAUTHORIZED` (403).
3. Crew ownership for a `CrewForeman`: when filing production, `X-User-ID` must equal the `crew_id` of the booking named by `crew_assignment_id`; when recording a hazard-tree removal, `X-User-ID` must be the crew holding an `ACTIVE` booking on the tree's `work_order_id`. Otherwise `ERR_NOT_CREW_OWNER` (403). This check guards exactly two operations: filing a production entry, and recording a hazard-tree removal.
4. Segregation of duties on hazard-tree assessment: the assessing `X-User-ID` must differ from the tree's `identified_by_user_id` — `ERR_SEGREGATION_OF_DUTIES` (403). This check guards the assess operation only.
5. Existence of every id in the request path, left to right — the corresponding not-found code (404).
6. Existence of every foreign key supplied in the request body — the corresponding not-found code (404).
7. Shape and value validation: required body fields present, enum values drawn from their declared sets, numeric fields inside their declared ranges, dates and datetimes well formed, and uniqueness respected on `circuit_code` across circuits, `crew_code` across crews, `event_code` across storm events, and `premise_code` within one span's notifications. Any of these fails with `ERR_VALIDATION` (400). Computed and system-owned fields supplied by the client are ignored at this step, never rejected and never echoed back.
8. Pagination bounds on list endpoints — `ERR_PAGINATION_INVALID` (400).
9. The supplied expected-version field equals the parent's current `version` — `ERR_STALE_WORK_ORDER_VERSION` or `ERR_STALE_CREW_VERSION` (412), on the two operations named in §2.8.
10. The target resource is in a state from which the requested transition is declared — `ERR_INVALID_STATE` (409). This applies to every transition endpoint.
11. The target resource is not already sitting in one of its terminal states — `ERR_ALREADY_TERMINAL` (409). This too applies to every transition endpoint.
12. A span's `execution_status` is `COMPLETED` before a billing line may be drafted against it or submitted for it — `ERR_WORK_ORDER_NOT_COMPLETE` (409). This guards both drafting a line on a span and submitting a drafted line.

Beyond this common prefix, the domain checks are themselves ordered relative to one another, and their relative order is stated with each workflow in §3. For reference, their ascending order across the whole system is: permit-active (20), permit-window date (21), buffer violation (22), clearance below prescription (23), no strike potential (24), risk below threshold (25), off-right-of-way consent (26), herbicide not prescribed (27), no active prescription (30), prescription not active (31), billing-method mismatch (32), outage cause invalid (33), crew unavailable (40), crew-type mismatch (41), refusal blocking completion (42), notification round limit (43), empty work plan (44), units exceeding plan (45), billing line not supersedable (46), storm not active (47), crew schedule conflict (50), permit window conflict (51), dispute window expired (52), permit window not open (53), and budget exceeded (60). Where several of these apply to one endpoint, the lower number is evaluated first.

### 2.10. Cascade Discipline and Conserved Quantities

Several operations in this system mutate more than one record. Every such cascade is synchronous and immediate: by the time the response is written, every downstream record has already been updated, its `updated_at` refreshed and its `version` incremented. There is no deferred or eventual settlement anywhere in the platform, and a read issued immediately after a cascading write observes the fully settled state.

Three conserved quantities anchor the cascades and are the clearest way to check an implementation. The first is planned units: a plan's `planned_unit_count` is always the sum of `planned_unit_count` over its spans whose `execution_status` is anything other than `CANCELLED`, and the storm split that carves a remainder child out of a preempted parent is engineered to leave that sum unchanged. The second is committed cents: a plan's `committed_cents` is always the exact integer sum of `final_payable_cents` over the billing lines of its spans that are in `DRAFT`, `SUBMITTED`, `APPROVED` or `PAID`, so voiding a line returns the plan's committed total to precisely the value it held before that line existed. The third is production: units and hours recorded on a production entry are never discarded by a later transition of the booking they were filed under.

Circuit posture follows plan posture rather than being set directly. A circuit's `trim_status` moves `NOT_SCHEDULED` to `SCHEDULED` when its plan is released, `SCHEDULED` to `ACTIVE_CYCLE` when the plan begins executing, `ACTIVE_CYCLE` to `CYCLE_AT_RISK` when a storm suspends the plan, `CYCLE_AT_RISK` back to `ACTIVE_CYCLE` when the storm demobilizes, `ACTIVE_CYCLE` to `CYCLE_COMPLETE` when the plan completes, and back to `NOT_SCHEDULED` when the plan is cancelled. Each of these changes bumps the circuit's `version`.

## 3. Business Logic & Workflows

### 3.1. Prescriptions: What a Circuit Is Entitled To

Everything in the program starts with a **prescription** — a standing instruction, authored by a `UtilityForester`, describing how a class of circuits is to be trimmed. A prescription is written for exactly one combination of `voltage_class` and `growth_zone`. The `voltage_class` is one of `DISTRIBUTION_4KV`, `DISTRIBUTION_12KV`, `DISTRIBUTION_35KV`, `SUBTRANSMISSION_69KV` or `TRANSMISSION_115KV`; the `growth_zone` is one of `SLOW`, `MODERATE` or `RAPID`. The forester states the nominal cycle length in `base_cycle_years`, which must be greater than zero and at most 10, and the `clearance_radius_ft` that a crew must cut to, which must be at least 1 and at most 40. Two further switches are optional at authoring time: `ground_to_sky`, which declares whether the corridor must be cleared floor to canopy and which defaults to false when omitted, and `herbicide_allowed`, which governs whether chemical control may be permitted on circuits governed by this prescription and which defaults to true when omitted. Finally, `effective_from` is a `YYYY-MM-DD` date naming the day the prescription becomes eligible for selection.

A prescription is born in `DRAFT` and does nothing while it sits there. Activation by a `UtilityForester` moves it `DRAFT → ACTIVE`, and activation has a peer-level consequence: any other prescription sharing the same `voltage_class` and the same `growth_zone` that was in `ACTIVE` is pushed `ACTIVE → SUPERSEDED`, with its own `version` incremented. `SUPERSEDED` is terminal; nothing revives a superseded prescription. Activation increments the activated prescription's `version` by 1 as well. What activation deliberately does **not** do is re-point any circuit: circuits keep the prescription they were resolved to until a forester explicitly asks for re-resolution. Prescriptions can be listed and filtered by `voltage_class`, `growth_zone` and `status`.

Resolution is a selector, not a foreign key the client supplies. When a circuit is registered, and again whenever a forester asks for the circuit's prescription to be re-resolved, the server assembles the candidate set: every prescription whose `status` is `ACTIVE`, whose `voltage_class` equals the circuit's `voltage_class`, and whose `growth_zone` equals the circuit's `growth_zone`. Prescriptions in `DRAFT` or `SUPERSEDED` are never candidates. If the candidate set is empty, the request is rejected with `ERR_NO_ACTIVE_PRESCRIPTION` (HTTP 422) and the circuit's `prescription_id` is left exactly as it was. Otherwise the candidates are ranked by `effective_from` descending — the latest effective date wins — and ties on `effective_from` are broken by `created_at` descending, so the most recently authored of two equally effective prescriptions is chosen. The record `id` is never used as a tiebreaker. The winner's identifier is written to the circuit's `prescription_id`. Dates are compared as exact `YYYY-MM-DD` strings.

### 3.2. Circuits, Trim Cycles, and What Outages Do to Them

A `UtilityForester` registers a circuit with its `circuit_code` (unique across all circuits, between 3 and 32 characters), its `voltage_class`, its `growth_zone`, the `customer_count` it serves (zero or more), and `last_trim_completed_on`, the `YYYY-MM-DD` date the previous cycle finished. Registration resolves the prescription as described above and then immediately computes the cycle. A newly registered circuit starts at `reliability_tier` `TIER_NORMAL`, `trim_status` `NOT_SCHEDULED`, `tree_caused_outage_count_36mo` of 0, and both `reliability_index_36mo` and `reliability_index_ytd` at 0.00. Circuits are listed with optional filters on `prescription_id`, `voltage_class`, `growth_zone`, `trim_status` and `reliability_tier`.

The cycle computation produces two fields: `cycle_months`, a whole number of months, and `next_trim_due_on`, the date the circuit is next due. Start from the resolved prescription's `base_cycle_years` and convert it to months by multiplying by 12. Multiply that by the growth factor for the circuit's `growth_zone` — a `SLOW` zone stretches the cycle by a quarter at a factor of 1.25, a `MODERATE` zone leaves it unchanged at 1.00, and a `RAPID` zone compresses it to three quarters at 0.75. Multiply again by the reliability factor for the circuit's current `reliability_tier` — 1.00 at `TIER_NORMAL`, 0.80 at `TIER_ELEVATED`, and 0.60 at `TIER_CRITICAL`. Round that product half-up to a whole number of months, and only then clamp it into the band the voltage class permits. The floor is 24 months for `DISTRIBUTION_4KV` and `DISTRIBUTION_12KV`, 30 months for `DISTRIBUTION_35KV`, and 36 months for `SUBTRANSMISSION_69KV` and `TRANSMISSION_115KV`. The ceiling is 72 months for `DISTRIBUTION_4KV` and `DISTRIBUTION_12KV`, 84 months for `DISTRIBUTION_35KV`, and 96 months for `SUBTRANSMISSION_69KV` and `TRANSMISSION_115KV`. The clamp lifts the value to the floor if it is below it and lowers it to the ceiling if it is above it, and the clamp is applied to the rounded value, never to the unrounded product. The clamped result is `cycle_months`, and `next_trim_due_on` is `last_trim_completed_on` advanced by that many calendar months; when the source day of month does not exist in the target month, it is clamped back to the last valid day of that month, so 31 January plus one month lands on 29 February in a leap year.

This computation is re-run in four situations: when a circuit is registered, when a forester re-resolves its prescription, when an outage record changes the circuit's `reliability_tier`, and when a work plan reaches completion. Re-resolution also increments the circuit's `version`.

Outage records are how reliability outcomes enter the system, and only a `UtilityForester` may file one. An outage names its `circuit_id`, an `outage_at` instant, a `cause_code` of `TREE_GROWN_IN`, `TREE_FELL_ON` or `NON_TREE`, the `customers_affected` count, and the `customer_minutes` of interruption; both counts must be zero or greater. Optionally it names a `work_order_id`, attributing the outage to the span whose clearance was missed. Two attribution rules are enforced together and rejected with `ERR_OUTAGE_CAUSE_INVALID` (HTTP 422): an outage whose `cause_code` is `NON_TREE` may not carry a `work_order_id` at all, and an outage that does carry one must name a span whose owning plan covers the same circuit as the outage's `circuit_id`. Outage records are immutable once filed — they carry `id` and `created_at` and nothing else of the common properties — and they can be listed filtered by `circuit_id`, `work_order_id` and `cause_code`.

Filing an outage re-scores the circuit. Only tree causes count: a record whose `cause_code` is `TREE_GROWN_IN` or `TREE_FELL_ON` qualifies, and a `NON_TREE` record never enters either window even though it is stored and returned like any other. The reliability index over a window is the sum of `customer_minutes` across the circuit's qualifying records whose `outage_at` falls inside the window, divided by the circuit's `customer_count` — or by 1 if the circuit serves zero customers, so the division is always defined — and rounded half-up to two decimal places. Two windows are maintained side by side from the same qualifying set. The rolling window runs from the instant 36 calendar months before the logical clock through the logical clock, with both ends inclusive, and its result is stored as `reliability_index_36mo`. The program-year-to-date window runs from midnight UTC on 1 January of the logical clock's calendar year through the logical clock, again with both ends inclusive, and its result is stored as `reliability_index_ytd`; because it starts later, it yields a strictly smaller numerator whenever any qualifying outage predates that 1 January, and it never influences the tier. `tree_caused_outage_count_36mo` is the count — not the customer-minutes — of qualifying records inside the rolling 36-month window. The tier is read off that count: six or more qualifying outages in the rolling window puts the circuit at `TIER_CRITICAL`, four or five puts it at `TIER_ELEVATED`, and anything below four leaves it at `TIER_NORMAL`. When the tier changes, `cycle_months` and `next_trim_due_on` are recomputed on the spot with the new reliability factor; either way, filing an outage increments the circuit's `version` by 1.

A dedicated reliability read reports both variants together for one circuit: the `circuit_id`, the `rolling_36_month_index`, the `program_year_to_date_index`, the `tree_caused_outage_count_36mo`, the `reliability_tier`, the `cycle_months` and the `next_trim_due_on`. It recomputes both indices against the logical clock at read time.

### 3.3. The Program-Year Plan and the Spans Beneath It

A `UtilityForester` opens a work plan for one circuit and one program year. The plan names its `circuit_id`, its `program_year` (an integer between 2000 and 2100 inclusive), the `planned_span_miles` it intends to clear (greater than zero), and the `budget_cents` authorizing spend (zero or more, in whole cents). A new plan begins in `DRAFT` with `planned_unit_count` at 0, `completed_unit_count` at 0, `committed_cents` at 0 and `production_pct` at 0.00. Plans are listed with optional filters on `circuit_id`, `status` and `program_year`.

Spans hang off the plan. A `ContractorPlanner` creates each one against a `work_plan_id`, declaring the `span_miles` it covers (greater than zero), the `billing_method` the contract uses for it — either `UNIT_PRICE` or `TIME_AND_MATERIALS` — and the `planned_unit_count` of trim units, meaning trees or poles, budgeted for it (zero or more). A new span sits at `execution_status` `PLANNED` and `billing_status` `NOT_BILLABLE`, and its creation immediately refreshes the owning plan's `planned_unit_count`. These two status dimensions are independent: field execution and invoicing evolve on the same record without either driving the other except at the single hand-off point described in §3.9.

Mapping is the planner's second visit to the span. It supplies `clearance_radius_ft`, the radial clearance the crew will actually cut to, and may optionally supply `mapped_unit_count` to replace the earlier estimate — when it does, that value becomes the span's `planned_unit_count` and the plan's `planned_unit_count` is recomputed. Mapping requires the span to be at `PLANNED` and the owning plan to be in `DRAFT`, `RELEASED` or `IN_PROGRESS`. It also enforces the prescription: the supplied `clearance_radius_ft` must be at least the `clearance_radius_ft` of the prescription resolved onto the plan's circuit. A narrower cut is rejected with `ERR_CLEARANCE_BELOW_PRESCRIPTION` (HTTP 422); an equal radius is acceptable. A successful mapping moves the span `PLANNED → MAPPED` and increments both the span's `version` and the plan's `version` by 1.

Before the field sees a plan it must be released, and only a `ContractorPlanner` may release it. A plan may be released only from `DRAFT`, and only if at least one of its spans is sitting at `MAPPED`; a plan with no mapped span is rejected with `ERR_EMPTY_WORK_PLAN` (HTTP 422). Release moves the plan `DRAFT → RELEASED`, pushes the circuit's `trim_status` `NOT_SCHEDULED → SCHEDULED`, and increments both the plan's `version` and the circuit's `version` by 1.

Individual spans are then released one at a time by the planner, moving `MAPPED → RELEASED` and incrementing the span's `version` by 1. Two things must hold: the plan itself must already be in `RELEASED` or `IN_PROGRESS`, and the prescription that the plan's circuit currently resolves to must still be in `ACTIVE`. If a newer prescription has since superseded it, span release fails with `ERR_PRESCRIPTION_NOT_ACTIVE` (HTTP 409) — the fix is for the forester to re-resolve the circuit first, which is precisely why prescription activation does not cascade onto circuits automatically.

Starting a released span moves it `RELEASED → IN_PROGRESS` and requires at least one booking on that span sitting at `SCHEDULED`. The start does three further things: every `SCHEDULED` booking on the span moves `SCHEDULED → ACTIVE`, the plan moves `RELEASED → IN_PROGRESS` if it was still merely released, and through that plan transition the circuit's `trim_status` moves `SCHEDULED → ACTIVE_CYCLE`. Plan production is recomputed at the same time.

Completing a span is the planner's last act on the execution dimension, and it is gated by the customer. If any notification on the span is still in `REFUSED` or `ESCALATED`, completion is rejected with `ERR_CUSTOMER_REFUSAL_BLOCKING` (HTTP 409) — an unresolved refusal must be either acknowledged, or escalated and then finalized, before the crew's work on that span can be closed out. On success the span moves `IN_PROGRESS → COMPLETED`, its `completed_at` is stamped from the logical clock, its `billing_status` moves `NOT_BILLABLE → BILLABLE`, and every booking on the span still in `SCHEDULED` or `ACTIVE` is moved to `RELEASED`, with each freed crew returning `ASSIGNED → AVAILABLE` provided it holds no other booking in `SCHEDULED` or `ACTIVE`. Plan production is recomputed. If every span of the plan is now in `COMPLETED` or `CANCELLED` and at least one is `COMPLETED`, the plan moves `IN_PROGRESS → COMPLETED`; that plan completion pushes the circuit's `trim_status` `ACTIVE_CYCLE → CYCLE_COMPLETE`, sets the circuit's `last_trim_completed_on` to the UTC date part of the logical clock, recomputes the circuit's `cycle_months` and `next_trim_due_on` from that new anchor, and increments the circuit's `version` by 1.

Cancellation exists at both levels and may carry an optional free-text `reason`. A planner may cancel a span from `PLANNED`, `MAPPED` or `RELEASED` — never once it is in progress or beyond — which removes it from the plan's conserved planned-unit sum and moves every booking on it in `SCHEDULED` or `ACTIVE` to `RELEASED`, freeing each crew under the same "no other live booking" rule. A `UtilityForester` may cancel the whole plan from `DRAFT`, `RELEASED`, `IN_PROGRESS` or `SUSPENDED`, and the cascade is identical whichever of those four states the plan was in: every span of the plan whose `execution_status` is not already `COMPLETED` or `CANCELLED` moves to `CANCELLED`, each of those spans releases its `SCHEDULED` and `ACTIVE` bookings and returns those crews to `AVAILABLE`, every `DRAFT` billing line on any span of the plan — the spans just cancelled and the plan's already `COMPLETED` spans alike — moves `DRAFT → VOID`, the plan's `planned_unit_count` and `committed_cents` are both recomputed, and the circuit's `trim_status` returns to `NOT_SCHEDULED`. `COMPLETED` and `CANCELLED` are the plan's terminal states.

Plan production is a single ratio, recomputed whenever a production entry is filed, whenever any span changes `execution_status`, and whenever the plan's production summary is read. The denominator, written back to the plan's `planned_unit_count`, is the sum of `planned_unit_count` over every span of the plan whose `execution_status` is not `CANCELLED` — cancelled spans leave the denominator entirely. The numerator, written back to `completed_unit_count`, is the sum of `actual_units_completed` over the plan's spans whose `execution_status` is `IN_PROGRESS`, `STORM_PREEMPTED` or `COMPLETED`; spans still at `PLANNED`, `MAPPED` or `RELEASED` contribute nothing to it. `production_pct` is 100 multiplied by the numerator, divided by the denominator, rounded half-up to two decimal places — and when the denominator is zero the answer is exactly 0.00, never an error and never a division by zero.

The plan's production summary is a computed read available to every role. It returns the `work_plan_id`, the `planned_unit_count`, the `completed_unit_count`, the `production_pct`, the `committed_cents`, a `budget_remaining_cents` equal to the plan's `budget_cents` less its `committed_cents`, and the `crew_production_rate` described in the next subsection.

### 3.4. Crews, Bookings, and the Daily Production Sheet

Contractor crews are registered by a `ContractorPlanner`. A crew carries a `crew_code` unique across all crews, a `crew_type` that is one of `BUCKET`, `CLIMBING`, `MANUAL`, `HERBICIDE` or `STORM`, a `headcount` between 1 and 12 inclusive, an `hourly_rate_cents` giving the fully burdened straight-time labor rate per hour in whole cents (zero or more), and a `home_district` string. A new crew starts at `status` `AVAILABLE` with `version` 1. The `crew_type` does double duty: it gates who may apply herbicide, and it sets the equipment rate the crew's hours bill at. Crews are listed with optional filters on `status`, `crew_type` and `home_district`.

Booking a crew onto a span is the planner's scheduling act. The booking names its `work_order_id` and `crew_id` and an interval given by `start_at` (inclusive) and `end_at` (exclusive). Two guards apply, and their relative order matters: crew availability is checked first, then interval conflict. A crew whose `status` is `STORM_DEPLOYED` cannot take new work bookings at all and is rejected with `ERR_CREW_UNAVAILABLE` (HTTP 409); a crew at `AVAILABLE` or `ASSIGNED` may be booked, since one crew legitimately holds several non-overlapping bookings. Then the interval is tested against every other booking of the same crew that is currently in `SCHEDULED` or `ACTIVE`, with a 60-minute travel buffer appended to the end of each interval before the comparison. The requested booking conflicts with an existing one when the requested `start_at` is earlier than that booking's `end_at` plus 60 minutes **and** the requested `end_at` plus 60 minutes is later than that booking's `start_at`; if any existing booking satisfies both conditions the request is rejected with `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409). Bookings that merely touch — where the gap between them is 60 minutes or more — do not conflict. A successful booking is created at `SCHEDULED`, moves an `AVAILABLE` crew to `ASSIGNED`, and increments the crew's `version` by 1.

Bookings move through a small lifecycle. The span's start pushes every `SCHEDULED` booking on it to `ACTIVE`, and a crew touched by that transition ends at `ASSIGNED` whether it was `AVAILABLE` or already `ASSIGNED`. A planner may release a booking early from either `SCHEDULED` or `ACTIVE`, moving it to the terminal state `RELEASED`, returning the crew `ASSIGNED → AVAILABLE` only when that crew holds no other booking in `SCHEDULED` or `ACTIVE`, and incrementing the crew's `version` by 1. Storm preemption takes a booking from `SCHEDULED` or `ACTIVE` to `PREEMPTED` and stamps `preempted_by_storm_event_id`; demobilization takes it from `PREEMPTED` to `RELEASED` and returns the crew `STORM_DEPLOYED → AVAILABLE`. Bookings can be listed filtered by `work_order_id`, `crew_id`, `preempted_by_storm_event_id` and `status`.

Production is filed by the `CrewForeman` of the booked crew, one entry per crew per day. The entry names the `crew_assignment_id` it is filed under and a `work_date` in `YYYY-MM-DD` form, and reports `units_trimmed` (zero or more), `labor_hours` (between 0 and 24 inclusive), and `equipment_hours` (between 0 and 24 inclusive). Two further quantities are optional and default to 0 when omitted: `disposal_tons`, the chip and log tonnage hauled off, and `gallons_applied`, the herbicide volume put down that day. When `gallons_applied` is greater than zero the entry must also name a `herbicide_permit_id`; when it is zero, `herbicide_permit_id` is left null. Production entries are immutable audit records: they carry `id` and `created_at` only, with no `updated_at` and no `version`. They are listed filtered by `crew_assignment_id`, `herbicide_permit_id` and `work_date`.

Filing an entry is checked against the plan before it is accepted. The span's `actual_units_completed` plus the entry's `units_trimmed` may not exceed the span's `planned_unit_count` multiplied by 1.10 and then truncated downward to a whole number — a ten percent overrun tolerance, with the fractional part discarded rather than rounded. Exceeding it is `ERR_UNITS_EXCEED_PLANNED` (HTTP 422). Herbicide entries face additional gates described in §3.7; of the two crew-side checks, note that the permit checks are evaluated before the crew-capability check, so an entry filed by a `BUCKET` crew against a permit that is not `ACTIVE` reports the permit problem rather than the crew-type problem. An accepted entry computes its `entry_cents`, adds its `units_trimmed` to the span's `actual_units_completed`, recomputes the plan's `completed_unit_count` and `production_pct`, and increments the span's `version` by 1.

Each entry's `entry_cents` is a rounded whole-cent value assembled from four parts. Labor splits at a 10-hour daily break: the straight-time portion is the lesser of the entry's `labor_hours` and 10, and the overtime portion is whatever `labor_hours` exceed 10, or zero if none do. Straight-time hours bill at the crew's `hourly_rate_cents`; overtime hours bill at that same rate multiplied by 1.5. Equipment bills the entry's `equipment_hours` at the crew's equipment rate, which is 9,500 cents per hour for a `BUCKET` crew, 3,000 for `CLIMBING`, 1,500 for `MANUAL`, 4,000 for `HERBICIDE` and 11,000 for `STORM`. Disposal bills the entry's `disposal_tons` at 2,800 cents per ton. Those four amounts are added together and the sum is rounded half-up to a whole cent, and that whole-cent figure is the stored `entry_cents`. Herbicide gallons themselves are not priced; they are a compliance quantity, not a billing one.

Across a plan, the crew production rate summarizes how many units the contractor turns out per labor hour. Take every production entry reachable through the bookings of every span of the plan whose `execution_status` is not `CANCELLED`, sum their `units_trimmed`, sum their `labor_hours`, and divide the first sum by the second, rounding half-up to two decimal places. When total labor hours across that set are zero — including when the set is empty — the rate is exactly 0.00.

### 3.5. Notifying the Customer, and What a Refusal Costs

No crew enters private property unannounced. A `CustomerAdvocate` opens one notification record per premise on a span, naming the `work_order_id`, a `premise_code` identifying the service point, the `contact_method` to be used — `DOOR_HANGER`, `PHONE` or `CERTIFIED_MAIL` — and `unit_count_at_premise`, the number of trim units physically located on that premise (zero or more). The `premise_code` must be unique within one span's notifications, though the same code may recur on different spans. A new record starts at `PENDING` with `refusal_round` at 0 and `notified_at` null. Notifications are listed filtered by `work_order_id` and `status`.

Delivering the notification moves it `PENDING → NOTIFIED` and stamps `notified_at` from the logical clock; the advocate may supply a `contact_method` on delivery to record a change from the originally planned channel. Delivery is permitted from `PENDING` and from `ESCALATED`, and it is refused only if the owning span has been cancelled — refusal handling deliberately continues after the crew has left the span, so any other `execution_status` is acceptable. A delivery made from `ESCALATED` closes the refusal loop `NOTIFIED → REFUSED → ESCALATED → NOTIFIED` and leaves `refusal_round` exactly at the value the escalation set; re-delivery never resets the round counter.

The customer's answer is recorded against a delivered notification by supplying `response`. A `response` of `ACKNOWLEDGED` moves the record `NOTIFIED → ACKNOWLEDGED`, which is terminal and which also unblocks any hazard-tree removal decision linked to that record. A `response` of `REFUSED` moves it `NOTIFIED → REFUSED`, and from that moment the owning span cannot reach `COMPLETED` until the refusal is resolved one way or the other. Both branches require the record to be sitting at `NOTIFIED`.

Escalating a refusal moves it `REFUSED → ESCALATED` and increases `refusal_round` by 1, and the program permits at most three rounds: if the round that escalation would produce would exceed 3, the request is rejected with `ERR_NOTIFICATION_ROUND_LIMIT` (HTTP 422). After escalation the advocate normally tries again, delivering the notification afresh; the cycle can run until the third round is exhausted.

Finalization is a utility decision, not a contractor or advocate one — only a `UtilityForester` may take it, and this is the one notification operation the `CustomerAdvocate` cannot perform. Finalizing requires the record to be at `ESCALATED` with `refusal_round` of at least 2, meaning the customer has been approached and has refused across at least two escalation rounds. Finalization moves the record `ESCALATED → FINAL_REFUSAL`, which is terminal, and then runs a four-hop cascade. First the record enters `FINAL_REFUSAL`. Second, the span's `refusal_blocked_unit_count` is recomputed as the sum of `unit_count_at_premise` across every notification of that span whose `status` is `FINAL_REFUSAL` — and only `FINAL_REFUSAL`, so records merely at `REFUSED` or `ESCALATED` withhold nothing. Third, the changed withholding forces every `DRAFT` billing line on that span to reprice from scratch: `billable_units`, `density_multiplier`, `gross_cents`, `retainage_cents`, `net_payable_cents`, `mobilization_credit_cents` and `final_payable_cents` are all recomputed. Fourth, the changed `final_payable_cents` forces the owning plan's `committed_cents` to be recomputed. The span's `version` is incremented by 1 as part of this cascade — which is precisely why a billing analyst holding a pre-finalization view of the span will be turned away by the stale-version guard when it tries to draft against it.

### 3.6. Hazard Trees Beyond the Right-of-Way

Not every threatening tree stands inside the corridor the utility has the right to cut. A `CertifiedArborist` walking a circuit records each one as a hazard tree, naming the `circuit_id` it threatens, its `species` — one of `SILVER_MAPLE`, `COTTONWOOD`, `ASH`, `OAK` or `CONIFER` — its `defect_class` — one of `DEAD`, `CAVITY`, `LEAN`, `CODOMINANT` or `HEALTHY` — its `height_ft` (greater than zero) and its `offset_ft`, the horizontal distance in feet from the conductor to the trunk, where zero means the trunk sits on the right-of-way edge. The arborist may also name the `work_order_id` of the span under which removal would be executed, or leave it unassigned for now. The record is created at `IDENTIFIED`, its `identified_by_user_id` is stamped from the acting `X-User-ID`, its `assessed_by_user_id` and `customer_notification_id` are null, and the risk arithmetic runs immediately. Hazard trees are listed filtered by `circuit_id`, `work_order_id`, `customer_notification_id` and `status`.

The scoring begins with reach. A tree has `strike_potential` when its `offset_ft` is less than or equal to its `height_ft` — a tree exactly as far from the line as it is tall counts as a strike, because it can reach the conductor lying down. When there is no strike potential the `risk_score` is fixed at 0.00, `removal_required` is false, and no further arithmetic is performed. Otherwise four weights are added. The defect weight is 40 for `DEAD`, 30 for `CAVITY`, 25 for `LEAN`, 15 for `CODOMINANT` and 0 for `HEALTHY`. The species weight is 20 for `SILVER_MAPLE`, 18 for `COTTONWOOD`, 15 for `ASH`, 8 for `OAK` and 5 for `CONIFER`. The proximity contribution is worth up to 30 points and falls off linearly with distance: divide `offset_ft` by `height_ft`, subtract that ratio from 1, multiply by 30, take zero if the result would be negative, and round that figure half-up to two decimal places **before** it enters the sum. The target weight reflects what is at stake on the conductor and is read from the `voltage_class` of the circuit named by `circuit_id`: 6 for `DISTRIBUTION_4KV`, 8 for `DISTRIBUTION_12KV`, 12 for `DISTRIBUTION_35KV`, 16 for `SUBTRANSMISSION_69KV` and 20 for `TRANSMISSION_115KV`. The four are added, the total is rounded half-up to two decimal places, and the result is capped at 100.00. That is the `risk_score`. `removal_required` is true exactly when the `risk_score` is 60.00 or higher.

A second arborist must confirm the finding, and it may not be the first one: assessment requires the acting `X-User-ID` to differ from the record's `identified_by_user_id`, and an attempt by the same person is rejected with `ERR_SEGREGATION_OF_DUTIES`. Assessment moves the record `IDENTIFIED → ASSESSED`, stamps `assessed_by_user_id`, and may correct the field measurements: an assessing arborist may supply a revised `defect_class`, `height_ft` or `offset_ft`, and may supply a `customer_notification_id` linking the tree to the consent record for the premise it stands on. Whatever is supplied is applied, and `strike_potential`, `risk_score` and `removal_required` are then recomputed from the resulting values.

The utility decides. A `UtilityForester` supplies an `outcome` on an assessed tree, and the three branches carry different weight. An `outcome` of `DECLINE` moves the record `ASSESSED → DECLINED`, a terminal state, and increments its `version` by 1. An `outcome` of `DEFER` moves it `ASSESSED → DEFERRED` and likewise increments `version` by 1; a deferred tree is not finished, and a second arborist assessment takes it `DEFERRED → ASSESSED` again — still subject to the same rule that the assessor differs from the identifier — recomputing `strike_potential`, `risk_score` and `removal_required` on the way. That revision loop `ASSESSED → DEFERRED → ASSESSED` may run as many times as the utility wants.

An `outcome` of `APPROVE_REMOVAL` moves the record `ASSESSED → APPROVED_REMOVAL` and increments its `version` by 1, but only after three checks that are evaluated in this order. First, the tree must have `strike_potential` true; a tree that cannot reach the line is rejected with `ERR_NO_STRIKE_POTENTIAL` (HTTP 422). Second, its `risk_score` must be at least 60.00; below that it is rejected with `ERR_HAZARD_RISK_BELOW_THRESHOLD` (HTTP 422). Third, consent: a tree whose `offset_ft` is exactly 0 sits on the right-of-way and needs no permission, but a tree whose `offset_ft` is greater than 0 stands on someone's property, and it may only be approved when its `customer_notification_id` names a notification currently in `ACKNOWLEDGED`. A missing link, or a link to a record in any other state, is rejected with `ERR_OFF_ROW_CONSENT_REQUIRED` (HTTP 409). Because the checks are ordered, a scoreless tree off the right-of-way reports the strike-potential failure, not the consent failure.

Removal is recorded in the field by the `CrewForeman` whose crew is actually there. It requires the tree to be at `APPROVED_REMOVAL`, requires its `work_order_id` to be set and that span's `execution_status` to be `IN_PROGRESS`, and requires the acting foreman's crew — identified by `X-User-ID` — to hold a booking on that span whose `status` is `ACTIVE`; a foreman without such a booking is rejected with `ERR_NOT_CREW_OWNER`. Success moves the record `APPROVED_REMOVAL → REMOVED`, which is terminal, and increments its `version` by 1.

### 3.7. Herbicide: Permits, Windows and Buffers

Chemical control is permitted, not assumed. A `CertifiedArborist` requests a permit for one circuit, naming the `circuit_id`, the `chemical_code` — one of `GLYPHOSATE`, `TRICLOPYR`, `IMAZAPYR` or `AMINOPYRALID` — the `applicator_license_no` under which the work will be done, the `buffer_ft` no-spray setback from sensitive features (zero or more), and the application window given by `window_start` and `window_end` as `YYYY-MM-DD` dates. That window is a **closed** interval: both the start date and the end date are themselves inside the window. A requested permit begins at `REQUESTED` with `approved_by_user_id` null. Permits are listed filtered by `circuit_id`, `status` and `chemical_code`.

A `UtilityForester` decides the request by supplying an `outcome`. `DENY` moves the permit `REQUESTED → DENIED`, a terminal state, and increments its `version` by 1. `APPROVE` moves it `REQUESTED → APPROVED` and stamps `approved_by_user_id` from the acting `X-User-ID`, but only after two checks in this order. First, the prescription currently resolved onto the permit's circuit must have `herbicide_allowed` true; a circuit governed by a no-chemical prescription is rejected with `ERR_HERBICIDE_NOT_PRESCRIBED` (HTTP 422). Second comes window capacity on that circuit, counting only the circuit's other permits whose `status` is `APPROVED` or `ACTIVE` — permits in `REQUESTED`, `DENIED`, `REVOKED` or `EXPIRED` are invisible to this count. Two conditions must both hold: the candidate's closed `[window_start, window_end]` interval must not intersect the closed interval of any counted permit carrying the same `chemical_code`, and approving the candidate must not produce a group of more than two permits whose closed windows all mutually intersect. Either violation is rejected with `ERR_PERMIT_WINDOW_CONFLICT` (HTTP 409). Because the intervals are closed, two windows that merely share an endpoint date do intersect. Revoking a permit removes it from this count and frees the slot.

Approval is not authorization to spray. A `CertifiedArborist` activates an approved permit, moving it `APPROVED → ACTIVE`, and activation is allowed only while the logical clock's date lies inside the closed `[window_start, window_end]` interval — on the first day and on the last day included. Activating too early or too late is rejected with `ERR_PERMIT_WINDOW_NOT_OPEN` (HTTP 422). Once `ACTIVE`, the permit may be named on production entries. A permit that is evaluated — whether at an activation attempt or when a production entry references it — while the logical clock's date is later than its `window_end` moves `ACTIVE → EXPIRED`, a terminal state, and no further herbicide entry may be filed against it. A `UtilityForester` may revoke a permit from either `APPROVED` or `ACTIVE`, moving it to the terminal `REVOKED` and optionally recording a `reason`.

Field application is where the permit does its real work. Whenever a production entry reports `gallons_applied` greater than zero, four checks run against it, in this order. The named `herbicide_permit_id` must resolve to a permit whose `status` is `ACTIVE`; anything else — still merely `APPROVED`, already `EXPIRED`, `REVOKED`, `DENIED` or `REQUESTED` — is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 422). The entry's `work_date` must lie inside that permit's closed `[window_start, window_end]` interval, endpoints included; outside it the entry is rejected with `ERR_APPLICATION_OUTSIDE_PERMIT_WINDOW` (HTTP 422). The span the entry rolls up to must not carry any notification in `FINAL_REFUSAL` whose premise sits inside the permit's `buffer_ft` setback; spraying next to a premise whose owner has permanently refused is rejected with `ERR_BUFFER_VIOLATION` (HTTP 422). And the filing crew's `crew_type` must be `HERBICIDE`; a `BUCKET`, `CLIMBING`, `MANUAL` or `STORM` crew reporting gallons is rejected with `ERR_CREW_TYPE_MISMATCH` (HTTP 422). An entry that reports zero gallons, or omits `gallons_applied` entirely, is subject to none of these four and needs no permit reference at all.

### 3.8. Storm Response: Preemption and the Way Back

When weather arrives, cycle trimming stops and restoration starts. A `UtilityForester` declares the event with an `event_code` unique across storm events, a `severity_level` integer between 1 and 5 inclusive, and the `affected_district` the storm has hit. A declared event begins at `DECLARED` with `reassigned_crew_count` and `preempted_assignment_count` both 0, and it must be activated by a forester — moving it `DECLARED → ACTIVE` — before any crew can be pulled onto it. Storm events are listed filtered by `status` and `affected_district`.

Reassignment is posted by a `ContractorPlanner` against an active event, naming the `crew_id` to pull and the `expected_crew_version` that client last observed for that crew. The version guard is evaluated before the storm's own eligibility rules, so a planner working from a stale crew record is told about the stale read rather than about the storm. Eligibility then requires three things of the target event and crew together: the event's `status` must be `ACTIVE`, its `severity_level` must be 3 or higher — a level 1 or 2 storm does not justify preempting work in progress — and the crew's `home_district` must equal the event's `affected_district`. Any of the three failing yields `ERR_STORM_NOT_ACTIVE` (HTTP 409). Notably no state precondition blocks a crew that is already `STORM_DEPLOYED`: re-attributing a deployed crew from one event to another is legitimate, and the version guard is the only protection against doing so from a stale view.

An accepted reassignment runs a four-hop cascade, and every hop is completed before the response is written. Hop one sets the crew's `status` to `STORM_DEPLOYED` and increments its `version` by 1. Hop two takes every booking of that crew whose `status` is `SCHEDULED` or `ACTIVE` to `PREEMPTED` and stamps each one's `preempted_by_storm_event_id` with the event. Hop three looks at each span that just lost a crew: a span whose `execution_status` is `IN_PROGRESS` and whose bookings are now all in `PREEMPTED` or `RELEASED` — that is, the preemption removed its last working crew — moves `IN_PROGRESS → STORM_PREEMPTED`, and its `version` is incremented by 1. Hop four propagates upward: a plan in `IN_PROGRESS` all of whose spans outside `CANCELLED` and `PLANNED` now sit at `STORM_PREEMPTED`, with at least one of them doing so, moves `IN_PROGRESS → SUSPENDED`, which in turn pushes the circuit's `trim_status` `ACTIVE_CYCLE → CYCLE_AT_RISK`. Plan production is recomputed along the way, and the event's `reassigned_crew_count` and `preempted_assignment_count` are updated to reflect the crews currently deployed to it and the bookings currently attributed to it.

Hop three does something subtler than it looks, because the units already earned on the preempted span must not evaporate and the plan's planned total must not move. When a span is preempted, a **remainder child** span is spawned in `PLANNED`, carrying `parent_work_order_id` pointing at the preempted parent, `storm_event_id` naming the triggering event, and the parent's `work_plan_id`, `span_miles` and `billing_method` copied across. The child's `planned_unit_count` is the parent's `planned_unit_count` less the parent's `actual_units_completed` — the work that was left undone — and the parent's `planned_unit_count` is simultaneously reduced to its `actual_units_completed`. Parent plus child therefore total exactly what the parent alone totalled before, so the plan's conserved `planned_unit_count` does not move at all. Note where `storm_event_id` lands: on the spawned child, never on the preempted parent. That matters at invoice time, because the storm premium is keyed on a span carrying `storm_event_id`. Spans can be listed filtered by `parent_work_order_id` to find remainder children and by `storm_event_id` to find spans attributed to a storm, alongside `work_plan_id`, `execution_status` and `billing_status`.

Demobilization is the exact inverse and is taken by a `UtilityForester` on an active event, moving it `ACTIVE → DEMOBILIZING`. Every booking carrying that event's `preempted_by_storm_event_id` moves `PREEMPTED → RELEASED`, and every crew in `STORM_DEPLOYED` attributed to the event returns to `AVAILABLE`. Every span in `STORM_PREEMPTED` whose preempted bookings carried this event moves `STORM_PREEMPTED → RELEASED` — back into the ordinary lifecycle, ready to be started again, closing the cycle `IN_PROGRESS → STORM_PREEMPTED → RELEASED → IN_PROGRESS`. Each such span's remainder child, still sitting in `PLANNED`, moves `PLANNED → CANCELLED`, and the child's `planned_unit_count` is added back onto the parent's, restoring the pre-storm value exactly. The plan's `planned_unit_count` and `production_pct` are recomputed, and once no span of the plan remains in `STORM_PREEMPTED` a plan sitting in `SUSPENDED` moves back `SUSPENDED → IN_PROGRESS`, which returns the circuit's `trim_status` `CYCLE_AT_RISK → ACTIVE_CYCLE`. Finally the event's `reassigned_crew_count` and `preempted_assignment_count` are both set to 0.

Closing is the last step: a forester moves an event `DEMOBILIZING → CLOSED`, and the transition is permitted only when no booking still carries that event's `preempted_by_storm_event_id` while sitting in `PREEMPTED`. `CLOSED` is terminal, and the transition increments the event's `version` by 1.

### 3.9. Billing the Work: Two Contracts, One Ledger

The billing dimension of a span begins the moment field execution ends. When a span reaches `COMPLETED` and carries no billing line outside `VOID`, its `billing_status` moves `NOT_BILLABLE → BILLABLE`. That transition is the single hand-off between the two dimensions; nothing in the billing dimension ever moves the execution dimension back.

A `BillingAnalyst` drafts a line against a billable span, supplying the `billing_method` the line is priced under and the `expected_work_order_version` described in §2.8. The span's `execution_status` must be `COMPLETED` — a line drafted against a span still in the field is rejected with `ERR_WORK_ORDER_NOT_COMPLETE` (HTTP 409). The line's `billing_method` must equal the span's own `billing_method`; a `UNIT_PRICE` line on a `TIME_AND_MATERIALS` span, or the reverse, is rejected with `ERR_BILLING_METHOD_MISMATCH` (HTTP 422), and that check is evaluated before the supersession check below. A new draft may supersede an earlier `DRAFT` line on the same span, but only a `DRAFT` line: if any line on the span is in `SUBMITTED`, `APPROVED` or `PAID`, the new draft is rejected with `ERR_BILLING_LINE_NOT_SUPERSEDABLE` (HTTP 409). When a prior `DRAFT` line does exist, it moves `DRAFT → VOID` and its `superseded_by_billing_line_id` is set to the new line's identifier. Drafting is permitted while the span's `billing_status` is `BILLABLE`, `LINE_DRAFTED` or `DISPUTED`, and it leaves that status at `LINE_DRAFTED` and increments the span's `version` by 1. Where more than one non-`VOID` line exists on a span, the span's `billing_status` is always derived from the newest of them, ranked by `created_at` descending with ties broken by `version` descending. Lines are listed filtered by `work_order_id`, `superseded_by_billing_line_id`, `status` and `billing_method`.

Pricing depends entirely on which contract the span runs under, and the two variants read completely different inputs from the same field outcome. Under `UNIT_PRICE`, the line first establishes `billable_units`: the span's `actual_units_completed` less its `refusal_blocked_unit_count`, floored at zero so a span whose refusals exceed its production bills nothing rather than a negative quantity. Density is then measured as `billable_units` divided by the span's `span_miles`, and the `density_multiplier` is read off that figure in three bands — a sparse span of fewer than 40 units per mile bills at 1.15, because scattered work costs more per tree; a span at 40 or more but under 80 units per mile bills at 1.00; and a dense span at 80 or more units per mile bills at 0.92. The gross is `billable_units` multiplied by the unit rate for the circuit's `voltage_class` — 4,200 cents per unit at `DISTRIBUTION_4KV`, 4,800 at `DISTRIBUTION_12KV`, 6,100 at `DISTRIBUTION_35KV`, 7,500 at `SUBTRANSMISSION_69KV` and 9,000 at `TRANSMISSION_115KV` — multiplied by the `density_multiplier`, with the product rounded half-up to a whole cent and stored as `gross_cents`. Labor hours, equipment hours and disposal tonnage are ignored entirely by this variant.

Under `TIME_AND_MATERIALS` the arithmetic is the mirror image: refusals and the density tier are ignored entirely, so the line records `billable_units` of 0 and a `density_multiplier` of 1.00, and the gross is assembled from the production sheets instead. Every production entry reachable through the span's bookings contributes its `entry_cents` — the per-entry, already-rounded whole-cent value computed as described in §3.4 from straight-time and overtime labor, equipment hours at the crew-type rate, and disposal tonnage. Entries are taken in order of `work_date` ascending with ties broken by `created_at` ascending, and every entry counts regardless of what became of the booking it was filed under: bookings in `SCHEDULED`, `ACTIVE`, `RELEASED` and `PREEMPTED` all contribute, because production is never discarded by a later assignment transition. `gross_cents` is the sum of those rounded `entry_cents` values. This rounding order is pinned: round each entry to a whole cent first, then add. Adding the unrounded entry values and rounding the total once is wrong and can differ from the correct answer by one or more cents. The consequence worth stating plainly is that an identical field outcome yields a different `gross_cents` under the two variants — they are not two views of one number.

Once the gross is known, settlement runs as a strict six-step waterfall in which each step consumes only the results of steps before it. Step one takes `gross_cents` from the pricing variant above. Step two withholds retainage, and the retainage percentage is keyed on the **gross** tier: a gross below 500,000 cents withholds nothing, a gross of at least 500,000 cents but below 2,000,000 cents withholds 5 percent, and a gross of 2,000,000 cents or more withholds 10 percent. `retainage_cents` is the gross multiplied by that percentage, rounded half-up to a whole cent. Step three computes the storm premium: when the span carries a `storm_event_id`, `storm_premium_cents` is 20 percent of the **gross**, rounded half-up to a whole cent, and when it does not, `storm_premium_cents` is 0. The premium is keyed on gross, never on any net figure. Step four gives `net_payable_cents` as `gross_cents` minus `retainage_cents` plus `storm_premium_cents`, in exact integer arithmetic with no further rounding. Step five awards a mobilization credit keyed on the **net** tier: `mobilization_credit_cents` is 25,000 when `net_payable_cents` is at least 1,000,000, and 0 otherwise. Step six gives `final_payable_cents` as `net_payable_cents` minus `mobilization_credit_cents`, again exact integer arithmetic. The credit awarded in step five never re-enters the tier decision of step two even though it changes what is actually paid — a re-entrant reading would flip the retainage tier for lines sitting near a boundary, and that reading is wrong.

The plan's `committed_cents` is the ledger these lines feed. It is the exact integer sum of `final_payable_cents` across every billing line belonging to any span of the plan whose `status` is `DRAFT`, `SUBMITTED`, `APPROVED` or `PAID`, regardless of what `execution_status` those spans are in. Lines in `DISPUTED` and `VOID` are excluded. Each summand has already been rounded to a whole cent by the settlement waterfall, so the summation itself is exact — round per line, then add, never the other way round. `committed_cents` is recomputed on every line creation, submission, review, resubmission and void, on hop four of the refusal cascade, and in the plan-cancellation cascade.

Submitting a drafted line is the analyst's request for payment. It requires the line to be at `DRAFT` and the owning span to be at `COMPLETED`, and it enforces the budget ceiling: the plan's `committed_cents`, recomputed with this line included, must not exceed the plan's `budget_cents`. Exceeding it is `ERR_BUDGET_EXCEEDED` (HTTP 422), and the same ceiling is enforced again on resubmission. On success the line moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, and the span's `billing_status` moves `LINE_DRAFTED → SUBMITTED`.

Review belongs to the utility, and never to the analyst that drafted or submitted the line — a `BillingAnalyst` cannot approve its own work, and only a `UtilityForester` may review, approve or pay. The reviewer supplies an `outcome` and may attach a `dispute_reason`. An `outcome` of `APPROVE` moves the line `SUBMITTED → APPROVED` and the span's `billing_status` `SUBMITTED → APPROVED`. An `outcome` of `DISPUTE` moves the line `SUBMITTED → DISPUTED` and the span's `billing_status` `SUBMITTED → DISPUTED`, and it removes the line from the plan's committed set, so `committed_cents` is recomputed downward. Disputing is time-limited: the logical clock may be at most 30 calendar days after the line's `submitted_at`, and a later dispute is rejected with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422).

A disputed line is not dead. The `BillingAnalyst` resubmits it unchanged, moving it `DISPUTED → SUBMITTED`, resetting `submitted_at` to the current logical clock — which restarts the 30-day dispute window — and re-entering it into the committed set so `committed_cents` is recomputed upward, subject once more to the budget ceiling. The span's `billing_status` follows `DISPUTED → SUBMITTED`. This cycle `SUBMITTED → DISPUTED → SUBMITTED` may repeat.

Voiding is available to the analyst from `DRAFT` or `DISPUTED`, optionally with a `reason`, and it is also what the plan-cancellation cascade and a superseding draft perform. A voided line leaves the committed set, and `committed_cents` returns to precisely the value it held before the line existed — the cents conservation invariant. When the void was caused by a newer draft on the same span, `superseded_by_billing_line_id` records which line replaced it. If no non-`VOID` line remains on the span afterwards, the span's `billing_status` falls back to `BILLABLE`.

Payment closes the loop: a `UtilityForester` moves an approved line `APPROVED → PAID`, and the span's `billing_status` moves `APPROVED → SETTLED`. `PAID` and `VOID` are the line's terminal states, and `SETTLED` is terminal on the span's billing dimension. A paid line stays in the committed set, so a fully settled plan's `committed_cents` reflects everything the utility has actually paid out.

## 4. Endpoint Definitions

Every path below is served under the `/vm` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation, including every state transition and every read, returns HTTP 200. The table names only the HTTP contract and the roles authorized to call each operation — request bodies, response payloads and side effects are specified in the §3 narratives, and an implementer must read those to reconstruct what each call accepts and changes.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/vm/prescriptions` | Create a voltage/growth-zone trim prescription in DRAFT. | UtilityForester |
| POST | `/vm/prescriptions/{id}/activate` | Activate a DRAFT prescription; supersedes the previously ACTIVE one for the same (voltage_class, growth_zone). | UtilityForester |
| GET | `/vm/prescriptions/{id}` | Read one prescription. | All seven roles |
| GET | `/vm/prescriptions` | List prescriptions with filters and pagination. | All seven roles |
| POST | `/vm/circuits` | Register a circuit; resolves its prescription and computes the trim cycle. | UtilityForester |
| POST | `/vm/circuits/{id}/resolve-prescription` | Re-run the prescription selector after a newer prescription was activated, and recompute the cycle. | UtilityForester |
| GET | `/vm/circuits/{id}` | Read one circuit including its computed cycle and reliability fields. | All seven roles |
| GET | `/vm/circuits` | List circuits; prescription_id filters the circuits resolved to a given prescription. | All seven roles |
| GET | `/vm/circuits/{id}/reliability` | Computed read returning both variants of calculations.circuit_reliability_index side by side. | All seven roles |
| POST | `/vm/outage-records` | Record an outage; tree causes re-score the circuit's reliability and may accelerate the trim cycle. | UtilityForester |
| GET | `/vm/outage-records/{id}` | Read one outage record. | All seven roles |
| GET | `/vm/outage-records` | List outage records filtered by circuit, attributed span or cause. | All seven roles |
| POST | `/vm/work-plans` | Create a program-year work plan for a circuit, in DRAFT. | UtilityForester |
| POST | `/vm/work-plans/{id}/release` | Release a plan for field execution; requires at least one MAPPED span. | ContractorPlanner |
| POST | `/vm/work-plans/{id}/cancel` | Cancel a plan and cascade-cancel its non-terminal spans, assignments and draft billing lines. | UtilityForester |
| GET | `/vm/work-plans/{id}` | Read one work plan with its derived counters. | All seven roles |
| GET | `/vm/work-plans` | List work plans filtered by circuit, status or program year. | All seven roles |
| GET | `/vm/work-plans/{id}/production-summary` | Computed read of plan production and budget consumption. | All seven roles |
| POST | `/vm/work-orders` | Create a mapped span placeholder in PLANNED under a work plan. | ContractorPlanner |
| POST | `/vm/work-orders/{id}/map` | Attach mapped geometry and the cut clearance; validated against the circuit's resolved prescription. | ContractorPlanner |
| POST | `/vm/work-orders/{id}/release` | Release a mapped span to the field; guarded by the circuit's prescription still being ACTIVE. | ContractorPlanner |
| POST | `/vm/work-orders/{id}/start` | Start field work; activates scheduled crew assignments and advances the plan and circuit. | ContractorPlanner |
| POST | `/vm/work-orders/{id}/complete` | Complete the span; blocked while any notification is REFUSED or ESCALATED. | ContractorPlanner |
| POST | `/vm/work-orders/{id}/cancel` | Cancel a span before it starts. | ContractorPlanner |
| GET | `/vm/work-orders/{id}` | Read one span including both status dimensions. | All seven roles |
| GET | `/vm/work-orders` | List spans; parent_work_order_id finds storm-spawned remainder children, storm_event_id finds spans attributed to a storm. | All seven roles |
| POST | `/vm/work-orders/{id}/billing-lines` | Draft a billing line for a completed span; supersedes any existing DRAFT line. OCC-guarded on the span's version. | BillingAnalyst |
| POST | `/vm/crews` | Register a contractor crew in AVAILABLE. | ContractorPlanner |
| GET | `/vm/crews/{id}` | Read one crew. | All seven roles |
| GET | `/vm/crews` | List crews filtered by posture, capability class or district. | All seven roles |
| POST | `/vm/crew-assignments` | Book a crew onto a span for a half-open interval; rejected on buffer-extended overlap. | ContractorPlanner |
| POST | `/vm/crew-assignments/{id}/release` | Release a booking early. | ContractorPlanner |
| GET | `/vm/crew-assignments/{id}` | Read one booking. | All seven roles |
| GET | `/vm/crew-assignments` | List bookings; preempted_by_storm_event_id finds the assignments a storm took. | All seven roles |
| POST | `/vm/production-entries` | File a day of crew production against a booking; herbicide gallons require an ACTIVE permit and a HERBICIDE crew. | CrewForeman |
| GET | `/vm/production-entries/{id}` | Read one production entry. | All seven roles |
| GET | `/vm/production-entries` | List production entries by booking, permit or date. | All seven roles |
| POST | `/vm/customer-notifications` | Open a premise notification record in PENDING. | CustomerAdvocate |
| POST | `/vm/customer-notifications/{id}/notify` | Deliver (or re-deliver, after an escalation) the notification. | CustomerAdvocate |
| POST | `/vm/customer-notifications/{id}/respond` | Record the customer's answer to a delivered notification. | CustomerAdvocate |
| POST | `/vm/customer-notifications/{id}/escalate` | Escalate a refusal to the next round, capped at 3 rounds. | CustomerAdvocate |
| POST | `/vm/customer-notifications/{id}/finalize-refusal` | Accept the refusal permanently; withholds the premise's units and reprices every draft line of the span. | UtilityForester |
| GET | `/vm/customer-notifications/{id}` | Read one notification. | All seven roles |
| GET | `/vm/customer-notifications` | List notifications for a span. | All seven roles |
| POST | `/vm/hazard-trees` | Identify a hazard tree; computes strike potential and risk score immediately. | CertifiedArborist |
| POST | `/vm/hazard-trees/{id}/assess` | Second-arborist assessment; may correct the measurements and link the consent record. | CertifiedArborist |
| POST | `/vm/hazard-trees/{id}/decision` | Utility decision on an assessed hazard tree. | UtilityForester |
| POST | `/vm/hazard-trees/{id}/remove` | Crew records the removal of an approved hazard tree. | CrewForeman |
| GET | `/vm/hazard-trees/{id}` | Read one hazard tree. | All seven roles |
| GET | `/vm/hazard-trees` | List hazard trees by circuit, span or linked consent record. | All seven roles |
| POST | `/vm/herbicide-permits` | Request a herbicide permit for a closed application window on a circuit. | CertifiedArborist |
| POST | `/vm/herbicide-permits/{id}/decision` | Approve or deny a requested permit; approval enforces the circuit window-capacity rule. | UtilityForester |
| POST | `/vm/herbicide-permits/{id}/activate` | Activate an approved permit; only inside its closed window. | CertifiedArborist |
| POST | `/vm/herbicide-permits/{id}/revoke` | Revoke an approved or active permit and free its window slot. | UtilityForester |
| GET | `/vm/herbicide-permits/{id}` | Read one permit. | All seven roles |
| GET | `/vm/herbicide-permits` | List permits for a circuit. | All seven roles |
| POST | `/vm/storm-events` | Declare a storm event. | UtilityForester |
| POST | `/vm/storm-events/{id}/activate` | Activate a declared storm so crews can be reassigned to it. | UtilityForester |
| POST | `/vm/storm-events/{id}/reassignments` | Reassign a crew to storm duty. OCC-guarded on the crew's version; drives the four-hop preemption cascade. | ContractorPlanner |
| POST | `/vm/storm-events/{id}/demobilize` | Demobilize the storm and restore every preempted booking, span, plan and circuit. | UtilityForester |
| POST | `/vm/storm-events/{id}/close` | Close a demobilized storm. | UtilityForester |
| GET | `/vm/storm-events/{id}` | Read one storm event with its reassignment counters. | All seven roles |
| GET | `/vm/storm-events` | List storm events. | All seven roles |
| POST | `/vm/billing-lines/{id}/submit` | Submit a draft line for utility review; enforces the plan budget ceiling. | BillingAnalyst |
| POST | `/vm/billing-lines/{id}/review` | Utility approves or disputes a submitted line. | UtilityForester |
| POST | `/vm/billing-lines/{id}/resubmit` | Re-submit a disputed line unchanged; re-enters the committed ledger. | BillingAnalyst |
| POST | `/vm/billing-lines/{id}/void` | Void a draft or disputed line; the committed ledger returns to its pre-line value exactly. | BillingAnalyst |
| POST | `/vm/billing-lines/{id}/pay` | Pay an approved line. | UtilityForester |
| GET | `/vm/billing-lines/{id}` | Read one billing line with its full settlement breakdown. | All seven roles |
| GET | `/vm/billing-lines` | List billing lines for a span; superseded_by_billing_line_id finds the line a void points at. | All seven roles |
| POST | `/vm/_clock/set_current_utc` | Set the server's logical UTC clock. Before any call to this endpoint the logical clock reads exactly 2026-08-01T00:00:00Z; it never falls back to real wall-clock time. | PlatformAdmin |
## 5. Error Code Catalogue

Every error response carries one of the identifiers below in `data.error_id` together with the matching HTTP status. The conditions that trigger each one are stated in the §2 and §3 narratives, alongside the rules they enforce; the precedence between them when several apply at once is fixed by the ordering in §2.9.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_CREW_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_CIRCUIT_NOT_FOUND` | 404 |
| `ERR_WORK_PLAN_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_CREW_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_ENTRY_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_HAZARD_TREE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_STORM_EVENT_NOT_FOUND` | 404 |
| `ERR_BILLING_LINE_NOT_FOUND` | 404 |
| `ERR_OUTAGE_RECORD_NOT_FOUND` | 404 |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 |
| `ERR_STALE_CREW_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_WORK_ORDER_NOT_COMPLETE` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 422 |
| `ERR_APPLICATION_OUTSIDE_PERMIT_WINDOW` | 422 |
| `ERR_BUFFER_VIOLATION` | 422 |
| `ERR_CLEARANCE_BELOW_PRESCRIPTION` | 422 |
| `ERR_NO_STRIKE_POTENTIAL` | 422 |
| `ERR_HAZARD_RISK_BELOW_THRESHOLD` | 422 |
| `ERR_OFF_ROW_CONSENT_REQUIRED` | 409 |
| `ERR_HERBICIDE_NOT_PRESCRIBED` | 422 |
| `ERR_NO_ACTIVE_PRESCRIPTION` | 422 |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_BILLING_METHOD_MISMATCH` | 422 |
| `ERR_OUTAGE_CAUSE_INVALID` | 422 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_CREW_TYPE_MISMATCH` | 422 |
| `ERR_CUSTOMER_REFUSAL_BLOCKING` | 409 |
| `ERR_NOTIFICATION_ROUND_LIMIT` | 422 |
| `ERR_EMPTY_WORK_PLAN` | 422 |
| `ERR_UNITS_EXCEED_PLANNED` | 422 |
| `ERR_BILLING_LINE_NOT_SUPERSEDABLE` | 409 |
| `ERR_STORM_NOT_ACTIVE` | 409 |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 |
| `ERR_PERMIT_WINDOW_CONFLICT` | 409 |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 |
| `ERR_PERMIT_WINDOW_NOT_OPEN` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
