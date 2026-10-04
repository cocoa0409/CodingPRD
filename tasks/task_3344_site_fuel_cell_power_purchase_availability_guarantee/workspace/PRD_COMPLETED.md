# On-Site Fuel Cell Power Purchase API — Product Requirements Document

## 1. Introduction

Commercial and industrial facility owners who want on-site power generation face a tangle of
interlocking questions before a fuel cell system can be sited: is the electrical load large
enough, is gas actually deliverable to the address, will the utility territory allow the
interconnection, how much physical footprint does the equipment need, and what does the
customer actually pay when the utility tariff, the gas commodity index and the equipment's
own efficiency all move independently? This document specifies the API that answers those
questions and then administers the commercial relationship that follows. It covers the
customer facility as a first-class resource, the power purchase agreement that governs the
sale of electricity, the fuel supply chain that feeds the system, the maintenance and remote
monitoring regime that keeps it running, and the settlement machinery that reconciles what a
customer owes against output and availability guarantees that the operator has made.

The product is built around the notion that a site is a pool of physical and commercial
resources that is drawn down, replenished and reconciled — electrical capacity against
installation footprint, clearance radius against available yard space, committed feedstock
against contracted generation, and money against money. Every resource that a site exposes is
governed by a posture that can be suspended and restored, and every suspension propagates
down the hierarchy from the facility to the contracts it hosts, to the service plans that
maintain those contracts, and to the customer relationship that ultimately carries the credit
risk. Because the same physical installation can change hands when a facility is sold or a
tenant vacates, the agreement itself is transferable, and the API records the basis on which
each contract is held.

The system is operated by a segregated set of internal roles rather than by the customer
itself, and it must remain auditable: monetary figures are reconciled rather than
recomputed on demand, guarantee remedies draw against escrowed reserves rather than against
unbounded goodwill, and the accrual ledger is append-only, with corrections expressed as
matched reversals instead of deletions. The API is mounted under the `/power` prefix.

## 2. Global Specifications & System-Wide Principles

This section collects the rules that hold across the whole surface of the API: how a request
identifies itself and proves its authority, what every response looks like regardless of the
resource involved, and the cross-cutting invariants — posture gates, precision, escalation,
optimistic concurrency and the logical clock — that every workflow in §3 depends on.

### 2.1. Request Identity and Segregation of Duties

Every request must carry two headers. `X-User-ID` identifies the acting party and
`X-User-Role` names the operational capacity in which that party is acting. A request that
omits either header, or that supplies a role string which does not name one of the seven
declared roles, is refused with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is
declared but whose identity is not a real instance of the entity that role speaks for is
refused the same way — see the identity rules below. A request that is properly authenticated
but whose role is not among the roles the addressed operation admits is refused with
`ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `SiteOperator`, `Customer`, `CustomerService`, `FuelCoordinator`,
`ServiceEngineer`, `SettlementAnalyst` and `SettlementApprover`.

Identity is carried differently depending on the role. When `X-User-Role` is `Customer`,
`X-User-ID` is the `id` of the acting `Customer`; the value is not opaque, and any operation
that reaches a resource belonging to a customer compares the resource's customer reference
against `X-User-ID`. A `Customer` may read only those contracts whose offtaker is the acting
customer, and may list only its own contracts. For the remaining six roles — `SiteOperator`,
`CustomerService`, `FuelCoordinator`, `ServiceEngineer`, `SettlementAnalyst` and
`SettlementApprover` — `X-User-ID` is an opaque operator identifier not tied to any persisted
entity. The server may record it, for example on the transition record that a state change
writes, but does not compare it against any entity's `id`, and one operator identity is as
good as another for the authority those roles carry.

Authority is separated on purpose. A `SiteOperator` owns facilities, interconnection posture
and the contract itself, and is the only role permitted to freeze or unfreeze a site, to run
the portfolio-level batch operations, to advance the logical clock, and to record the
customer-side contract actions of exit, cure, termination and renewal. A `CustomerService`
operator owns the commercial relationship posture and the renewal review dimension, including
credit exposure holds and renewal offers. A `FuelCoordinator` owns gas sourcing and delivery
custody. A `ServiceEngineer` owns remote monitoring, maintenance windows and module
replacement staging. A `SettlementAnalyst` prepares settlement lines and accruals, issues
allowances and reconciles the ledger, but cannot approve or apply what it prepared; a
`SettlementApprover` approves, settles and reverses lines, and cannot create them. No single
internal role can both prepare and apply a settlement, which is the point of the split.

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
- A resource object is rendered exactly as it is stored, except that server-internal bookkeeping
  keys — the insertion counter behind the `created_at` tie-break, a deferred action's trigger
  instant — are never exposed in a response body.

### 2.3. Pagination

Every operation that returns a collection accepts `limit` and `offset` as query parameters.
`limit` caps how many items a single response may carry; when it is not supplied the server
uses 10, and any supplied value is clamped into the range whose floor is 1 and whose ceiling
is 100 — a request for zero items is not a valid way to probe a collection, and a request for
more than a hundred is served at a hundred. `offset` states how many items of the ordered
result to skip and defaults to 0; a negative `offset` is served as zero, and a value supplied
for either parameter that is not a whole number falls back to that parameter's default rather
than being clamped. Unless an operation says otherwise, collections are ordered
by `created_at` ascending, so the oldest resource in a collection is the first item a client
sees and paging forward with a growing `offset` walks the collection in creation order. Rows
that share a `created_at` instant — the logical clock is frozen between calls, so ties are
common — are ordered by the order in which they were created, and never by their identifier.

List responses carry the pagination state in the `meta` object alongside the request
identifiers: `limit`, `offset`, `total_count` and `has_more`. `total_count` reports the size
of the full filtered collection, not the size of the page, and `has_more` reports whether
further items remain beyond the page that was returned.

### 2.4. Resource Identity, Common Properties and Collection Filters

Every persisted resource is addressed by an `id` that the server mints as a UUID. The
identifier carries no type prefix and no semantic content; a `Site` and a `Ppa` are
distinguishable by the collection they were fetched from, never by the shape of their
identifier.

Resources that carry the standard envelope of system-managed properties expose four of them.
`id` is the UUID described above. `created_at` is the instant the row was first persisted,
rendered as an ISO 8601 timestamp in UTC with exactly three fractional digits. `updated_at`
is the instant of the most recent modification to any of the resource's properties, including
properties the server derives rather than accepts, and it is refreshed on every such
modification. `version` is a system-managed integer that begins at its initial value and
increments by one on every modification; it is the anchor that optimistic concurrency in §2.7
compares against. A recomputation of a derived field is a modification in the sense of this
paragraph: it moves `updated_at` forward and advances `version` exactly as an edit to an
accepted input field would.

Nine resources are exposed: `Site`, `Customer`, `Ppa`, `ServicePlan`, `FuelDelivery`,
`SettlementLine`, `PpaAccrual`, `SettlementAllowance` and `PpaTransition`. All of them carry
the common properties except `PpaTransition`, which is an append-only audit record. The
transition record carries only `id` and `created_at`: it has no `updated_at` field and no
`version` field, it is never edited after it is written, and no operation accepts an expected
version for it. The one exception to that immutability is the `transition_reversed` flag,
which a later compensating transition may flip to true; the flag is the record's only mutable
property. The record also carries the contract it belongs to as `ppa_id`, the `from_state` and
`to_state` the contract moved between, the `trigger_code` naming the business trigger that
drove the move, and the `actor_role` of the party that drove it.

Collections are filtered rather than searched. The site collection accepts a filter on
`status` and on `lifecycle_state`. The customer collection filters on `credit_tier`, `status`
and `renewal_stage`. The contract collection filters on `site_id`, `customer_id`, `state`,
`assigned_service_plan_id` and `originating_ppa_id`. The service plan collection filters on
`lifecycle_state`. The fuel delivery collection filters on `lifecycle_state`,
`attesting_customer_id` and `selected_ppa_id` when it is listed site-first. The contract-first
listing is scoped to the deliveries whose `selected_ppa_id` is that contract and accepts no
further filter, and the customer-first listing is scoped to the deliveries naming that customer
as their attesting party and likewise accepts none. The settlement line collection filters on `status` and
`allocation_basis`. The accrual collection filters on `ppa_id`, `site_id`, `accrual_type`,
`lifecycle_state`, `source_settlement_line_id` and `applied_allowance_id`. The allowance
collection filters on `allowance_kind`, `lifecycle_state`, `applied_to_accrual_id` and
`applied_to_ppa_id`. The transition collection filters on `to_state`. Every one of these
list operations also accepts `limit` and `offset` per §2.3.

Addressing a nested resource is a left-to-right walk, and where a path nests one identifier
inside another the identifier on the left is resolved before the one on the right. A path that
names a site resolves that site first; a site that does not exist is refused with
`ERR_SITE_NOT_FOUND` (HTTP 404) before the server ever looks at anything nested beneath it. A
path that names a contract resolves that contract next, and a contract that does not exist — or
one whose `site_id` does not equal the site identifier the path also names — is refused with
`ERR_PPA_NOT_FOUND` (HTTP 404). A path that names a customer resolves that customer with
`ERR_CUSTOMER_NOT_FOUND` (HTTP 404) when no such customer exists. Any remaining identifier
appearing in a body or a path that names a service plan, a fuel delivery, a settlement line, a
settlement allowance or an accrual must resolve to a row that exists and that belongs to the
parent the request addresses; a reference that fails either test is refused with
`ERR_REFERENCE_NOT_FOUND` (HTTP 404). An identifier carried in a body rather than in the path
resolves the same way: a body-named `site_id` or `customer_id` is refused with
`ERR_SITE_NOT_FOUND` or `ERR_CUSTOMER_NOT_FOUND` (HTTP 404) exactly as a path-named one is,
while a body-named service plan, fuel delivery, settlement line, settlement allowance or
accrual is refused with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). The identifiers a body carries
are read before anything is resolved, so a body that omits one of them is a malformed request
under `ERR_INVALID_REQUEST` (HTTP 400) even when another identifier it carries would not
resolve. The same resolution applies to the links a resource
carries inside itself: a contract's `assigned_service_plan_id`, a service plan's `ppa_id`, a
transition's `ppa_id` and a contract's `originating_ppa_id` must each resolve to a declared row
whenever they are set rather than null.

Validation runs in a fixed order, and the order is observable because only the first failure is
reported. Authentication is tested first: the two headers must be present, the role value must
name a declared role, and an entity-backed role's identifier must match a real instance of the
entity it speaks for, with any failure surfacing as `ERR_UNAUTHENTICATED` (HTTP 401). Only once
identity is established is authorization tested, and a role that is not among the operation's
admitted roles surfaces as `ERR_UNAUTHORIZED` (HTTP 403). Only once the caller is entitled does
the server resolve the resources the request addresses, in the left-to-right order above. Only
once the addressed resources exist are their states tested: a resource whose state does not
admit the requested operation surfaces as `ERR_INVALID_STATE` (HTTP 409), and an operation
aimed at a resource that has already reached a terminal state surfaces as
`ERR_ALREADY_TERMINAL` (HTTP 409). Business rules are evaluated only after state, which means a
request aimed at a contract in the wrong state is reported as a state problem rather than as
whichever business rule would also have failed, and a request that would breach both a safety
rule and a fiscal rule is reported against the safety rule. Field-level validation runs last of
all: a missing required field, a field carrying the wrong type, an enum member outside its
declared values, or a paired field supplied without its partner surfaces as
`ERR_INVALID_REQUEST` (HTTP 400).

### 2.5. Site Posture and the Suspension Cascade

A facility has two independent state dimensions. The first is its availability posture,
carried in `status`, whose values are `SITE_ACTIVE` and `SITE_SUSPENDED`. The second is its
resource-draw dimension, carried in `lifecycle_state`, whose values are `RESOURCE_AVAILABLE`,
`RESOURCE_DRAWING` and `RESOURCE_CLOSED`. The two move on their own schedules: a site can be
actively drawing fuel from its pool while its posture is suspended, and a site can hold an
available fuel pool while drawing nothing.

Suspension is the system's heaviest cascade and it is only ever driven by a `SiteOperator`.
A facility may be suspended only while its posture is currently `SITE_ACTIVE` and only while
at least one of its contracts is in `PPA_ACTIVE` — a site with no live contract has nothing
to suspend, and both of those gates are refused with `ERR_INVALID_STATE` (HTTP 409) before the
`reason` is even read, so a malformed reason on a site that could not be suspended anyway is
reported as the state problem. The suspension call carries a `reason`, which must be one of `FUEL_SHORTAGE`,
`GRID_INTERCONNECT_FAILURE`, `NONPAYMENT` or `CUSTOMER_REQUEST`; any other value is rejected
as a malformed request under `ERR_INVALID_REQUEST` (HTTP 400). Once accepted, the freeze
walks the hierarchy in a fixed order and each step is caused by the step above it rather than
by the original request. The site's `status` becomes `SITE_SUSPENDED` and its
`lifecycle_state` is left untouched by this step alone. Every contract hosted at that site
in `PPA_ACTIVE` moves to `PPA_SUSPENDED` — a reachable state, not a terminal one — and each
such contract has its `version` advanced and a transition record appended carrying the
trigger code `SITE_FROZEN` with `from_state` `PPA_ACTIVE` and `to_state` `PPA_SUSPENDED`.
Every service plan belonging to a suspended contract that is in `SERVICE_ACTIVE` or
`SERVICE_MAINTENANCE_WINDOW_OPEN` moves to `SERVICE_SUSPENDED`, which releases its
`radius_buffer_m` back to the site and forces a recomputation of the site's
`clearance_zone_used`. Any such plan whose `module_replacement_stage` is
`REPLACEMENT_SCHEDULED` is moved to `REPLACEMENT_BLOCKED`. On the commercial side, each
affected customer has `exposure_hold_pct` recomputed and has `hold_armed` set to true when
that customer's `credit_tier` is `CREDIT_SUBSTANDARD`; for any other credit tier the armed
flag is left exactly as it was. The freeze then recomputes the site's `active_ppa_count`,
`contracted_purchase_cents` and `committed_feedstock_therms`.

The `reason` value also steers two side branches. When the reason is `NONPAYMENT` or
`CUSTOMER_REQUEST`, every customer of record for the site's suspended contracts moves from
`CUSTOMER_ACTIVE` to `CUSTOMER_SUSPENDED`. When the reason is `GRID_INTERCONNECT_FAILURE`,
the site's own `lifecycle_state` moves from `RESOURCE_DRAWING` to `RESOURCE_CLOSED`, because
an interconnect that has failed is no longer a resource the site can draw against.

Restoration is deliberately harder than suspension, because three separate things must be
true at once. A `SiteOperator` may lift a suspension only when the site's posture is
`SITE_SUSPENDED`, only when the site's `draw_position_therms` is at least
`MIN_RESUME_DRAW_THERMS`, which is 1,000 therms — a site that has burned through its allocatable fuel pool has no
business resuming operations — and only when every service plan at that site has left
`SERVICE_MAINTENANCE_WINDOW_OPEN`, since resuming a contract while its own equipment is mid
maintenance would double-book the same physical resource. A further condition applies at the
customer level: no customer of record for the site's suspended contracts may be sitting in
`RENEWAL_DECLINED`. A resume request that fails the fuel-pool test is refused with
`ERR_DRAW_POSITION_BELOW_RESUME` (HTTP 422); a site whose posture is not `SITE_SUSPENDED`, a
site that still has a plan in `SERVICE_MAINTENANCE_WINDOW_OPEN`, and a site one of whose
suspended contracts' customers is sitting in `RENEWAL_DECLINED` are each refused with
`ERR_INVALID_STATE` (HTTP 409). When the resume is accepted, the site's
`status` returns to `SITE_ACTIVE`, every contract in `PPA_SUSPENDED` returns to `PPA_ACTIVE`,
each restored contract has a transition record appended with trigger code `SITE_UNFROZEN`,
each of their service plans returns to `SERVICE_ACTIVE`, `clearance_zone_used` is
recomputed, and every affected customer whose `credit_tier` is not `CREDIT_SUBSTANDARD` has
`hold_armed` cleared. A customer that the freeze moved to `CUSTOMER_SUSPENDED` returns to
`CUSTOMER_ACTIVE` on the same resume, since the site it was suspended with has become
`SITE_ACTIVE` again in that same transaction. A site whose `lifecycle_state` is
`RESOURCE_CLOSED` returns to `RESOURCE_AVAILABLE` in that same resume: the API records no
exit-fee acknowledgement and no separate confirmation step gates the resource dimension's
return, so an unfreeze always restores a closed site whose other gates pass.

### 2.6. The Fuel Pool, Delivery Windows and Sourcing Configuration

The fuel pool is the quantity that makes a site operational, and it is tracked in
`draw_position_therms`. It is an opening balance plus what has been delivered minus what has
been consumed, and because a delivery is a reservation before it is a physical event, the
system treats scheduling a delivery as an immediate draw against the pool and treats
cancelling one as an immediate restoration. The opening balance is the operator-funded
`initial_fuel_inventory_therms` recorded when the facility is first registered, plus every
closed delivery volume, less every therm actually consumed by generation. A site's
`current_avoided_fuel_cost_cents_per_therm` records the most recent delivery that has been
confirmed — a settled delivery still counts as confirmed — taking that delivery's
`effective_commodity_rate_cents_per_therm` capped at the site's declared
`gas_commodity_rate_cents_per_therm` multiplied by `SOURCED_INDEX_CEILING_MULTIPLE` and rounded
to four decimal places, and it reads as zero while no delivery has been confirmed. "Most
recent" is read in creation order, with a tie broken by insertion order rather than by
identifier.

Two hard guards protect the pool. First, a delivery's `volume_therms` may not exceed the
site's `draw_position_therms` at the time the request is evaluated; a request that asks for
more fuel than the site holds is refused with `ERR_INSUFFICIENT_DRAW_POSITION` (HTTP 422).
This guard is applied not only when a delivery is scheduled but also when a resource hold is
taken against the pool and when a delivery in transit is confirmed, so the same shortfall is
caught whichever step it surfaces in. Second, a site may carry only a bounded number of
simultaneous commitments: the count of its deliveries in `DELIVERY_SCHEDULED` or
`DELIVERY_IN_TRANSIT` must remain strictly below `MAX_ACTIVE_DEMANDS_PER_SITE`, which is 5, at all times,
and a request that would take the count to that ceiling — whether it is a scheduled delivery,
a resource hold, or the dispatch of an in-transit load — is refused with
`ERR_SITE_DEMAND_LIMIT` (HTTP 422). The count used by this guard excludes the delivery
being evaluated.

Fuel may be sourced two ways, and the configuration must be internally consistent. A
delivery declares `sourcing_mode`, whose values are `FIXED_PRICE_BLEND` and
`INDEXED_BLEND`. `INDEXED_BLEND` requires a non-null `index_rate_cents_per_therm`; a request
that names the indexed mode while leaving the index leg unset is refused with
`ERR_FUEL_SOURCING_MODE_INVALID` (HTTP 422). `FIXED_PRICE_BLEND` requires `hedged_fraction`
to equal exactly 1; a fixed-price request that hedges only part of its volume is refused with
the same code. The blend itself is what prices the delivery: `hedged_fraction` of the volume
is priced at `fixed_price_cents_per_therm` and the remainder at `index_rate_cents_per_therm`,
the two products are computed first and summed, and the sum is rounded once to four decimal
places using round half up. A customer that sources its own gas must be corroborated before
its attestation counts: when a delivery names an `attesting_customer_id`, that
`Customer` must exist, its `status` must be `CUSTOMER_ACTIVE`, and at least one contract at
the site must carry `fuel_responsibility` of `CUSTOMER_SOURCED_GAS`. A delivery naming an
attesting customer that fails any of those three tests is refused with
`ERR_CUSTOMER_SOURCING_UNVERIFIED` (HTTP 422) — both when the delivery is scheduled and
again when it is confirmed.

Time is treated as a closed interval wherever physical occupancy is concerned, and as a
half-open interval wherever accounting periods are concerned. A delivery or resource hold
occupies the closed interval from `hold_window_start_iso8601` to `hold_window_end_iso8601`,
and two such windows at the same site may never overlap — not even by touching, since a
window whose end equals another's start is treated as overlapping rather than adjacent. A
request that would create such an overlap is refused with `ERR_DELIVERY_WINDOW_OVERLAP`
(HTTP 422). The two window boundaries are supplied together or not at all; supplying one
without the other is a malformed request under `ERR_INVALID_REQUEST`. Confirmation of a
delivery is also time-gated in one direction only: the delivery may not be confirmed before
the logical clock has reached its `confirm_after_iso8601` instant — a confirmation at exactly
that instant is admitted, and only an earlier one is refused with
`ERR_CONFIRM_TOO_EARLY` (HTTP 422). The window boundaries are the delivery's occupancy
record, not its confirmation gate; a delivery may carry no window at all.

### 2.7. Optimistic Concurrency on Contract Writes

Three writes are guarded by optimistic concurrency control, and no other write in the system
accepts a version field. A guarded request must carry the expected version of its parent
resource, and the check is a plain equality test against that parent's current `version` as
it stands when the request is evaluated. A mismatch is rejected with `ERR_STALE_VERSION`
(HTTP 412) and nothing is persisted; a request that omits the field entirely is a malformed
request under `ERR_INVALID_REQUEST`, because a guarded write may not opt out of the check.

Scheduling a fuel delivery against a site is guarded: the request must carry
`expected_site_version` equal to the target `Site`'s current `version`. A site may legitimately
hold many scheduled deliveries, so the only thing that can make a second, otherwise valid
create illegitimate is that the client is acting on a site view that an earlier write has
already superseded — that earlier write will have advanced `Site.version` through its own
cascades into `draw_position_therms`. The rejection code is `ERR_STALE_VERSION` at HTTP 412.

Creating a settlement line against a contract is guarded the same way, with
`expected_ppa_version` compared against the target `Ppa`'s current `version`. Opening a second
settlement period is otherwise a legitimate act, so again the sole guard is the caller's
observed contract version, which an earlier create has already advanced by rewriting the
contract's pool-derived fields. The rejection code is `ERR_STALE_VERSION` at HTTP 412.

Issuing a settlement allowance against a contract is the third guarded write, and it too
carries `expected_ppa_version` compared against the target `Ppa`'s current `version`. Issuing
a further allowance is otherwise legitimate; a stale observed contract version is the only
thing that blocks it. The rejection code is `ERR_STALE_VERSION` at HTTP 412.

### 2.8. Money, Precision and Escalation

Money is carried in integer cents, and fractional-cent results are eliminated at the point of
computation rather than at the point of display. Two rounding conventions are used, and which
one applies is a property of the quantity rather than of the caller's preference. Monetary
and rate values are rounded to two decimal places using round half up. Commodity rate blends
are the exception: the blended rate is rounded to four decimal places using round half up.
Where a value is an integer count — accrued tokens, applied days, contracted kilowatts,
committed kilowatt-hours remaining — rounding does not apply and the value is a whole number.

Rounding order is part of the contract, not an implementation detail. Where a figure is
assembled from several components, each component is rounded to two decimal places on its own
and the rounded components are then summed; rounding the whole sum once at the end produces a
different cent figure and is not the specified behaviour. Where a figure is assembled from a
sequence of sub-intervals, the same discipline applies line by line: each line is rounded to
two decimal places and the rounded lines are summed, so a period that straddles a boundary
values its parts and not its total. Where a floor operation is specified — the number of whole
years elapsed in an escalation ladder, the number of whole days a rebate covers, the number of
whole days an allowance buys — the value is truncated toward zero, never rounded to the
nearest whole number, and the truncation is applied before the value is used, not after.

The customer's energy rate escalates on a whole-year ladder anchored to the contract's own
start. The rate is the contract's `tariff_base_cents_per_kwh` multiplied by one plus
`escalator_pct`, raised to the number of whole years elapsed since the contract's
`state_entered_at` instant, floored, and then rounded once to two decimal places. A contract
that is exactly one second short of its first anniversary still evaluates at the base rate,
and a contract exactly at its first anniversary evaluates at exactly one escalation step; the
ladder counts whole years and nothing finer. Because `state_entered_at` is refreshed on every
state change, a cure or a renewal restarts the ladder at zero. A newly drafted contract
reports `effective_tariff_cents_per_kwh` equal to its `tariff_base_cents_per_kwh`, and the
same field name carries the escalated rate once the contract is live — there is no separate
field for the two situations. A contract's `escalated_rate_cents_per_kwh` is the same ladder
read for a settlement period rather than for "now", counting whole years from the contract's
`state_entered_at` to that period's `period_start`.

Contract terms are constrained at the commercial layer. The committed terms are 10, 12, 15
and 20 years, and a `term_years` outside that set is refused with
`ERR_TERM_COMMITMENT_INVALID` (HTTP 422). A contract's declared capacity and efficiency must
both be strictly positive — `contracted_kw` greater than zero and
`contracted_efficiency_kwh_per_therm` greater than zero — and a contract proposing either
value at zero or below is refused with `ERR_EFFICIENCY_INVALID` (HTTP 422); the same test is
re-applied when contract terms are adjusted after activation. The annual escalator must lie
within the closed interval from 0 to `ESCALATOR_MAX_PCT`, which is 0.06, and a value outside
that interval — including a negative one — is refused with `ERR_ESCALATOR_OUT_OF_RANGE`
(HTTP 422).

### 2.9. Reserves, Stop-Loss and the Credit Exposure Cap

Two escrowed reserves stand behind the guarantees the operator makes. The output-guarantee
reserve, held in `output_guarantee_reserve_cents`, is the guaranteed output shortfall for the
contract's annual period valued at the escalated customer rate: the excess, floored at zero,
of `contracted_annual_kwh` over the actual annual output, multiplied by
`effective_tariff_cents_per_kwh`. The capacity-guarantee reserve, held in
`capacity_guarantee_reserve_cents`, is the availability shortfall valued at the availability
penalty rate: the excess, floored at zero, of the contracted availability shortfall in
kilowatt-hours over nothing at all — that is, the shortfall itself — multiplied by
`availability_penalty_cents_per_kwh`. The availability shortfall is the fraction of load the
contract does not guarantee, applied to the site's expected annual load: one minus
`guaranteed_availability_pct`, multiplied by `expected_annual_site_load_kwh`, floored at
zero. The penalty rate is the site's `grid_tariff_rate_cents_per_kwh` multiplied by
`AVAILABILITY_PENALTY_MULTIPLE`, which is 1.20, rounded to two decimal places.

The capacity reserve is not merely a balance; it is a stop-loss. The contract opens with an
operator commitment recorded as `capacity_reserve_pre_cents`, defaulting to 1,000,000 cents
when the drafter does not state one, and a floor recorded as `loss_floor_cents`, defaulting
to 0. Credits that draw against the reserve accumulate in `capacity_reserve_credits_cents`,
which is the sum of the applied amount of every `CAPACITY_ALLOWANCE` that has been applied as
time plus the nominal amount of every `TRUEUP_ACCRUAL` recorded against the contract, whatever
that accrual's lifecycle state; an allowance of the avoided-cost kind does not draw against the
capacity reserve at all. A credit that was handed back because the settlement line that
produced it was reversed is excluded from the accumulation, because the hand-back returns the
allowance to `ALLOWANCE_ISSUED` and only an applied-as-time capacity allowance is counted. The headroom
is the opening commitment minus the floor. The evaluation is ordered: headroom is computed
first, the entire accumulated credit figure is compared against it, and only if the comparison
passes is the reserve written. Any write that would push accumulated credits past the headroom
is refused outright with `ERR_GUARANTEE_FLOOR_BREACH` (HTTP 422) and nothing is persisted, so
`capacity_guarantee_reserve_cents`, which is the opening commitment minus the accumulated
credits, can never fall below the contract's floor. The guard is read differently by its two
callers. Applying an allowance tests the prospective figure — the accumulated credits already
recorded plus the amount the application would add — against the headroom, and only a
`CAPACITY_ALLOWANCE` is tested this way. Settling a line tests the accumulated credit figure
already recorded against the same headroom, without projecting the allowance the settle itself
consumes, so the two paths do not perform the same arithmetic even though they share the same
headroom and the same error code.

A second ceiling caps how much credit a single settlement can deliver. On settlement,
`net_charge_cents` minus `output_guarantee_credit_cents` must not exceed the customer's
lifetime billable base as recorded in `lifetime_customer_billable_cents` plus
`SETTLEMENT_CREDIT_CAP_CENTS`, which is 50,000,000 cents. A settlement that would exceed that
ceiling is refused with `ERR_BUMPER_EXCEEDED` (HTTP 422). The same ceiling is checked when an
allowance is applied, but there it is tested against the allowance's nominal `amount_cents`
rather than against a settlement line's net charge less its output-guarantee credit.

Commercial exposure is capped by credit tier, not by request. Each customer carries
`exposure_hold_pct`, which is 0.40 for `CREDIT_SUBSTANDARD`, 0.15 for `CREDIT_STANDARD` and
0.0 for `CREDIT_PRIME`. A credit exposure hold may be armed only against a customer whose
`credit_tier` is not `CREDIT_PRIME` and whose `exposure_hold_pct` is greater than zero; a
request to arm it against a prime-tier customer is refused with `ERR_CREDIT_TIER_INELIGIBLE`
(HTTP 422). The same code covers the mirror-image case on transfer: a contract transfer may be
requested for a `CREDIT_SUBSTANDARD` customer only while that customer's hold is armed. Arming
a hold is a cascade in its own right — the customer's `status` becomes `CUSTOMER_CREDIT_HOLD`,
`hold_armed` becomes true, every one of that customer's contracts in `PPA_ACTIVE` moves to
`PPA_SUSPENDED`, each such contract's service plan in `SERVICE_ACTIVE` moves to
`SERVICE_SUSPENDED`, and every affected site has `active_ppa_count` recomputed and a
transition record appended for each suspended contract, each carrying the trigger code
`EXPOSURE_HOLD_ARMED`. Arming a hold that is already in force is not a special case: the
customer must still be `CUSTOMER_ACTIVE` when the request is evaluated, and a customer already
sitting in `CUSTOMER_CREDIT_HOLD` or `CUSTOMER_SUSPENDED` is refused with `ERR_INVALID_STATE`
(HTTP 409). Releasing the hold is gated on the
customer's exposure actually being clear: `outstanding_balance_cents` must be exactly zero
and every site hosting one of that customer's contracts must be `SITE_ACTIVE`. When the
release is accepted, the customer returns to `CUSTOMER_ACTIVE`, `hold_armed` is cleared, every
suspended contract returns to `PPA_ACTIVE` with a transition record carrying the trigger code
`EXPOSURE_HOLD_RELEASED` and its suspended service plan returning to `SERVICE_ACTIVE`, and
`active_ppa_count` is recomputed for each affected site. A customer that is not sitting in
`CUSTOMER_CREDIT_HOLD`, one whose `outstanding_balance_cents` is not exactly zero, and one
hosting a contract at a site that is not `SITE_ACTIVE` are each refused the release with
`ERR_INVALID_STATE` (HTTP 409).

### 2.10. The Logical Clock and Deferred Actions

The system runs on a logical clock rather than on wall-clock time, and the difference matters
for every temporal rule in this document. A `SiteOperator` may set the clock to any supplied
`current_utc` instant, and the server starts, before any such call, at exactly
`2026-09-01T00:00:00Z`; it never falls back to the host machine's wall-clock time, and every
comparison the system makes against "now" — cure deadlines, confirmation gates, reversal
windows, escalation ladders, stale-accrual ages, deferred revert timers — is made against the
logical clock.

Two deferred actions are armed by ordinary operations and fire when the clock reaches their
trigger instant rather than when a client asks for them. Requesting a contract exit records a
cure deadline at the exit-request instant plus the contract's `customer_cure_deadline_days`.
That deadline is not self-executing: no termination fires when it passes, and the contract
leaves `PPA_EXIT_PENDING` only through a cure or through the explicit termination call, which
is admitted only once the deadline has passed. Dispatching a module
replacement arms a revert that returns the hardware stage to `REPLACEMENT_NONE` at the
dispatch instant plus `MODULE_REPLACEMENT_REVERT_HOURS`, which is 24 hours. The check that fires
these actions runs before every request is served and again immediately after the clock is set,
so an armed action takes effect on the first request that observes the clock at or past its
trigger instant; a plan that reaches a maintenance window boundary is swept by the same check.
Both are described in full in §3.
While a service plan's remote monitoring link is degraded, the plan's
`monitoring_degraded_days` is read as the whole days between the current logical clock and
`monitoring_degraded_at`; when `monitoring_degraded_at` is null the value is zero. No operation
ever sets that instant — a plan is created with it null whatever `remote_monitoring_status` the
request declares, and nothing else writes it — so the figure reads zero and `dispatch_hold`
stays false for every plan the API can produce. The hold is computed but never armed: were the
figure to exceed `MODULE_DISPATCH_HOLD_DAYS`, which is 7 days, the plan's `dispatch_hold` would
be true and module replacement dispatch held back, but no reachable request can push it past
that tolerance.

## 3. Business Logic & Workflows

### 3.1. Siting a Facility and Reading Its Evaluation

A customer facility enters the system when a `SiteOperator` registers it. Registration asks
for the customer facility `name` and the `utility_territory` code it interconnects under — a
value such as `PGE_CA`, whose trailing territory suffix is load-bearing and is read elsewhere
when the system decides which governing law applies to a transfer. The operator then declares
the commercial and physical facts the evaluation will reason over: the blended
`grid_tariff_rate_cents_per_kwh` the site pays when it buys from the utility instead of
generating; the observed `grid_outage_events_per_year` and the total
`grid_annual_outage_hours` that make on-site generation attractive in the first place; the
prevailing local `gas_commodity_rate_cents_per_therm` that becomes the default fuel basis for
every contract at the site; the `expected_annual_site_load_kwh` that the availability
guarantee will later be measured against; and the `tax_rate_pct` applied to charges and
credits. Alongside those come the physical constraints: the `footprint_sqm` available for
power modules, the `clearance_zone_capacity` for concurrent service footprints, the
`allowed_downtime_hours_per_year` the availability guarantee will tolerate, and the two
interconnection economics figures, `standby_charge_cents_per_kw_month` and
`interconnect_exit_fee_cents_per_kw`. A newly registered facility starts with `status` of
`SITE_ACTIVE`, a `lifecycle_state` of `RESOURCE_AVAILABLE`, and its `draw_position_therms`
set from the operator-funded `initial_fuel_inventory_therms`, which is 1,000,000 therms. The
figure is not a registration input: the site records it as its own
`initial_fuel_inventory_therms` and opens the pool at that value. Its
`clearance_zone_used`, `committed_feedstock_therms` and
`current_avoided_fuel_cost_cents_per_therm` all begin at zero.

Evaluation is a read-shaped operation with a write-shaped side effect: a `SiteOperator` asks
the server to evaluate a facility, and the evaluation returns four figures without creating a
new resource. The first is the `standby_charge_cents` the utility will levy on the
interconnection, which is the total contracted capacity at the site multiplied by
`standby_charge_cents_per_kw_month` and again by twelve, since standby is billed monthly and
the evaluation states it annually. The second is the `exit_fee_cents` exposure if the
interconnection is abandoned, which is the same total contracted capacity multiplied by the
site's `interconnect_exit_fee_cents_per_kw`. The total contracted capacity in both of those
figures is summed over every contract the site hosts, whatever its state, as each contract's
`contracted_kw`, counted once per contract — this set is wider than the three-state set the
footprint rule counts, and a terminated contract still contributes its capacity — the fee is
charged per kilowatt contracted rather than per kilowatt actually
generated, so a contract whose equipment underperforms still carries its full capacity
exposure. A site with no contracts reports both figures as zero. The evaluation records what
it read, advancing the facility's `version` by one even though no new row is created.

The third figure is the fixed consideration the operator charges for the gas it has committed
to the site, recorded as `fixed_consideration_cents`. It is the site's
`committed_feedstock_therms` multiplied by the site's `gas_commodity_rate_cents_per_therm`,
rounded to two decimal places. A facility carries no in-service date and the API defines no
fixed-consideration cutoff, so the line is always charged and its status is always recorded as
`IN_SERVICE`; `NOT_IN_SERVICE` is never written. The
fourth figure is the currently escalated customer rate, reported as
`escalated_rate_cents_per_kwh`, read from the same annual ladder described in §2.8 for the
site's earliest-created contract whatever that contract's state, and reported as zero when the
site hosts no contract at all. The response also echoes the evaluated site's `site_id` and its
`site_version` as it stands after the evaluation's version advance.
Evaluation also refreshes the contract-level bases it depends on, including the index ceiling
and the guarantee reserves described in §3.2, so a portfolio-wide recompute and a
single-site evaluation never disagree about the same contract.

Committed feedstock is the site's exposure measured in therms, and it is derived rather than
declared. For every contract at the site whose `state` is `PPA_DRAFT`, `PPA_ACTIVE` or
`PPA_SUSPENDED`, the contract's `term_years` is multiplied by 365 to give its contract days,
that product is multiplied by its `contracted_kwh`, and the result is divided by its
`contracted_efficiency_kwh_per_therm`; those per-contract figures are summed into
`committed_feedstock_therms`, and that site-level sum is carried to four decimal places. The
site's `clearance_zone_used` is carried to four decimal places the same way. The related monetary exposure, `contracted_purchase_cents`, is
the sum over the same set of contracts of the contract's `purchase_price_cents_per_kwh`
multiplied by its `contracted_kw`. The capacity exposure is tracked separately as
`total_contracted_kw`, the sum of `contracted_kw` over the same three-state set of contracts,
and this is the figure the footprint rule compares against the site's `footprint_sqm`
multiplied by `KW_PER_SQM`, which is 10 kilowatts of capacity per square metre. That comparison is a hard gate in two places: a new facility may
not be registered with declared capacity that exceeds its available footprint, and a contract
may not be activated in a state where the site's capacity would breach it. Both refusals
carry `ERR_FOOTPRINT_EXCEEDED` (HTTP 422).

One more site-level figure reconciles the fuel market against physical delivery. The site's
`current_avoided_fuel_cost_cents_per_therm` is the smaller of the most recent confirmed
delivery's `effective_commodity_rate_cents_per_therm` and the site's declared
`gas_commodity_rate_cents_per_therm` multiplied by `SOURCED_INDEX_CEILING_MULTIPLE`, which is
1.25. That ceiling exists so that a single bad index day cannot inflate the avoided-cost
basis the whole portfolio reads; when no delivery has yet been confirmed at the site the
figure is zero.

### 3.2. Structuring and Activating a Power Purchase Agreement

A customer offtaker is created by a `CustomerService` operator, who names the customer legal
entity through `name`, classifies it through `industry_code`, and assigns its credit standing
through `credit_tier`, whose values are `CREDIT_PRIME`, `CREDIT_STANDARD` and
`CREDIT_SUBSTANDARD`. A new customer starts with a `status` of `CUSTOMER_ACTIVE` and a
`renewal_stage` of `RENEWAL_NONE`, and its commercial exposure is derived immediately from its
credit tier per §2.9 rather than being declared.

A contract is drafted by a `SiteOperator` through a payload that names the facility it serves
and the offtaker it serves them, carried as `site_id` and `customer_id`. The commercial terms
follow: `term_years`, which must be one of the committed terms and is refused with
`ERR_TERM_COMMITMENT_INVALID` otherwise; `contracted_kw`, the capacity the system will be
metered against; `contracted_efficiency_kwh_per_therm`, the guaranteed electrical efficiency
in kilowatt-hours per therm of fuel; `contracted_annual_kwh`, the annual delivered output the
output guarantee measures; `tariff_base_cents_per_kwh`, the energy rate at contract start;
`escalator_pct`, the annual escalation applied to that base; and
`fuel_adder_cents_per_therm`, the commodity adder applied to the site's gas index. The
guarantee terms come next: `guaranteed_availability_pct`, expressed as a fraction such as
0.97, and `guaranteed_delivery_kwh`, the annual delivered output the output guarantee
promises. The drafting call also carries `customer_cure_deadline_days`, the number of days
the customer has to cure a breach before an exit fee attaches, and `fuel_responsibility`,
whose value is either `PPA_FUEL_INCLUDED` or `CUSTOMER_SOURCED_GAS` and which determines who
is expected to source the gas the system burns. Two fiscal parameters close the payload: the
opening capacity-guarantee escrow `capacity_reserve_pre_cents`, described in §2.9, and
`loss_floor_cents`, the minimum exposure retained regardless of credits. A contract that
declares a `contracted_kw` of zero or less, or a
`contracted_efficiency_kwh_per_therm` of zero or less, is refused with
`ERR_EFFICIENCY_INVALID` (HTTP 422), and a contract whose `escalator_pct` falls outside the
interval from zero to 0.06 inclusive is refused with `ERR_ESCALATOR_OUT_OF_RANGE`
(HTTP 422).

A freshly drafted contract sits in `PPA_DRAFT`, its `state_entered_at` set to the current
logical clock, and its `effective_tariff_cents_per_kwh` equal to its declared
`tariff_base_cents_per_kwh`. Its `purchase_price_cents_per_kwh` is recorded as the operator's
purchase basis — the contract's `effective_tariff_cents_per_kwh` divided by its `term_years`,
rounded to two decimal places — and its `exit_fee_cents` reports the site-wide interconnection
exposure described in §3.1 rather than a zero placeholder. The contract immediately begins
carrying provisional values for the whole battery
of derived figures described in §3.5 and §3.6 — the base charge, the recurring pools, the
guarantee remedy and the availability escrow draw — so that a drafter can see what the
contract would cost before it is ever activated. Its `output_guarantee_reserve_cents` and
`capacity_guarantee_reserve_cents` are projected in the same way, and the two are not projected
alike. The capacity reserve of a draft is the opening commitment with no credits netted against
it, so a draft contract always reports a capacity reserve strictly larger than the same
contract will report once it is live; the output reserve carries the trailing-year shortfall
reading described in §2.9 whichever state the contract sits in, because it never nets credits
in the first place. The
settlement line, not the contract, carries the provisional forecast band: the line's
`expected_net_low_cents` is its `metered_kwh` valued at the contract's
`effective_tariff_cents_per_kwh` plus the index basis divided by the contract's
`contracted_efficiency_kwh_per_therm`, and its `expected_net_high_cents` is the same reading
with the contract's index ceiling in place of the index basis, each rounded to two decimal
places. Both are system-computed, and both shift when the underlying index
moves, so neither should be read as a commitment.

The fuel adder is capped in three places, and the caps are not the same number. The
contract's index ceiling, `contract_index_ceiling_cents_per_therm`, is the site's
`gas_commodity_rate_cents_per_therm` multiplied by `INDEX_CEILING_MULTIPLE`, which is 1.5.
The contract's post-escalation adder, `effective_fuel_adder_cents_per_therm`, is the smaller
of the declared `fuel_adder_cents_per_therm` and `HARD_CAP_CENTS_PER_THERM`, which is 14.0.
The settlement-facing basis, `index_basis_cents_per_therm`, is the smaller of the site's
`gas_commodity_rate_cents_per_therm` and `contract_index_ceiling_cents_per_therm`. All three
are recomputed when a contract is activated, when a service plan's maintenance window opens,
and when a `SiteOperator` runs the portfolio-wide index-basis recompute, so the
same contract never prices fuel against a stale ceiling. The index leg a contract prices
against is the site's declared `gas_commodity_rate_cents_per_therm` whatever the contract's
state: the API does not switch a live or suspended contract onto the site's
`current_avoided_fuel_cost_cents_per_therm`. That avoided-cost reading is a site-level figure
which the delivery blend consults for a load that is still scheduled or in transit, not a
contract's own pricing input, so a contract's index basis does not move when a delivery is
confirmed.

Activation is the single densest operation in the system. A `SiteOperator` may activate a
drafted contract only when five conditions hold together. The facility's `status` must be
`SITE_ACTIVE`; a facility that is suspended refuses the activation with `ERR_SITE_FROZEN`
(HTTP 409). The offtaker's `status` must be `CUSTOMER_ACTIVE`. The contract's `term_years`
must be one of the committed terms. The site must either be hosting no live contracts at all
— `active_ppa_count` equal to zero — or already be in the `RESOURCE_DRAWING` lifecycle state,
which prevents a facility from being silently switched into draw mode by an activation it did
not expect. And the capacity test must pass: the sum of `contracted_kw` across the site's
contracts in `PPA_DRAFT`, `PPA_ACTIVE` or `PPA_SUSPENDED`, including the one being activated,
must not exceed the site's `footprint_sqm` multiplied by `KW_PER_SQM`. A contract that would
breach the footprint is refused with `ERR_FOOTPRINT_EXCEEDED` (HTTP 422). Those gates are
evaluated in a fixed order — the site's posture, then the offtaker's status, then the
contract's own state, then the clearance total, then the footprint, and finally the committed
term — and only the first failure is reported, so a contract that is both mis-termed and out of
state is reported as the state problem. Activation also
re-tests the site's clearance total against its `clearance_zone_capacity` and refuses with the
same `ERR_FOOTPRINT_EXCEEDED` (HTTP 422) when the zone is already exhausted, although the plan
the cascade creates carries a zero radius and adds nothing to that total itself.

Once the gates pass, activation runs a cascade whose later steps are caused by earlier ones
rather than by the original request. The contract's `state` becomes `PPA_ACTIVE`,
`state_entered_at` is set to the current logical clock, and a transition record is appended
carrying `from_state` `PPA_DRAFT`, `to_state` `PPA_ACTIVE`, trigger code `PPA_ACTIVATED` and
the `actor_role` of the operator driving it. The facility's `lifecycle_state` becomes
`RESOURCE_DRAWING` and its `active_ppa_count` increases by one. A service plan is then
created for the contract in `SERVICE_PLAN_DRAFT` with a `module_replacement_stage` of
`REPLACEMENT_NONE`, a `radius_buffer_m` of 0.0 and both `window_start_iso8601` and
`window_end_iso8601` null, and the contract's `assigned_service_plan_id` is set to the new
plan's identifier. That brand-new plan immediately transitions itself from
`SERVICE_PLAN_DRAFT` to `SERVICE_ACTIVE` on the `ON_PLAN_CREATED` trigger, and because both
window boundaries are null it does not enter a maintenance window. Any other plan already
sitting in `SERVICE_PLAN_DRAFT` against this contract rides the same edge and is moved to
`SERVICE_ACTIVE` in the same transaction. The site's
`clearance_zone_used` is then recomputed twice — once against the new plan as it stands, and
once again over every plan at the site in `SERVICE_ACTIVE` or
`SERVICE_MAINTENANCE_WINDOW_OPEN` — because the plan's contribution to the clearance total
depends on the lifecycle state it just entered. The site's `draw_position_therms` is
recomputed in the same pass.

The cascade finishes on the derived-field fan-out. The site's `contracted_purchase_cents`
and `committed_feedstock_therms` are recomputed from the newly active contract. The contract
itself has its `effective_tariff_cents_per_kwh`, `purchase_price_cents_per_kwh`,
`exit_fee_cents`, `annual_customer_cost_cents`, `committed_kwh_remaining` and
`loss_floor_cents` recomputed; the committed kilowatt-hours remaining is the contract's
`term_years` multiplied by its `contracted_annual_kwh`, less the kilowatt-hours already
settled against it, so activation pins the contract's remaining commitment to its full term.
The offtaker's `active_ppa_count`, `reconcile_cadence_slots`, `hold_armed` and
`exposure_hold_pct` are recomputed last. Each of the mutations in this paragraph advances the
`version` of the resource it touches and refreshes its `updated_at`, which is why the
optimistic-concurrency guards in §2.7 see a movement after an activation even though no
client sent a second edit.

Contract terms are not frozen at activation. A `SiteOperator` may adjust a contract,
supplying a revised `contracted_kw`, `contracted_annual_kwh` and
`guaranteed_availability_pct` — all three are required — and may optionally name a
`target_ppa_id` to state which sibling contract the revision should be netted against; the
operation is not gated on the contract's state, so a draft or a terminated contract may be
adjusted as readily as a live one, and a `target_ppa_id` that does not resolve is refused with
`ERR_REFERENCE_NOT_FOUND` (HTTP 404). Adjusting contract terms re-applies
the positivity test on the supplied capacity and on the contract's stored efficiency, and
refuses a violation with `ERR_EFFICIENCY_INVALID` (HTTP 422). When a target contract is named,
the revision produces a netting figure rather than a fresh charge, and that figure is reported
on the response as `commitment_swap_netting_cents`. The first partition is the net charge of
the target contract's earliest-created line in `SETTLEMENT_APPLIED`, or zero when the target
contract has no applied line; the second is the customer's total settled amount across every
one of its contracts less the target contract's own settled total. The netting figure is the
smaller of those two partitions, so a customer holding exactly one contract nets against
nothing and produces a figure of zero, while a customer holding several contracts can net
against the rest of its portfolio and produces the larger figure.

### 3.3. Fuel Supply, Custody and Allocation of Output

Fuel reaches a site through the hands of a `FuelCoordinator`, and the moment a delivery is
scheduled it is accounted for even though nothing has physically moved. The scheduling
payload declares the `volume_therms`, the `delivered_at` instant and the
`confirm_after_iso8601` instant before which the load may not be receipted; it may declare a
`sourcing_mode`, and a payload that leaves the mode unset is admitted with neither sourcing
rule applied — the index leg is not required and the hedged fraction is not constrained. It
may also carry
the gas-pricing legs `index_rate_cents_per_therm`, `fixed_price_cents_per_therm` and
`hedged_fraction` together with an `attesting_customer_id` when the customer rather than the
operator is sourcing the gas. It may also block out the occupancy window it needs at the
site, supplied as `hold_window_start_iso8601` and `hold_window_end_iso8601`. The request must
carry `expected_site_version` per §2.7. Before the delivery is created the server runs the
gauntlet described in §2.6, in this order: the two occupancy-window boundaries must be supplied
together or not at all, the site must not already be at its
simultaneous-commitment ceiling, the volume must fit inside the site's remaining draw
position, any named attesting customer must be corroborated, the occupancy window must not
overlap an existing one, and the observed site version must match the site's current one. Only
once those pass are the body's remaining field-level defects reported, and the sourcing
configuration is tested last of all, so a body that is missing a required field is refused
with `ERR_INVALID_REQUEST` (HTTP 400) rather than with the sourcing code the same request would
also have earned. A scheduled delivery
immediately reduces the site's `draw_position_therms` by its `volume_therms` and starts life
in `DELIVERY_SCHEDULED`; confirming reality later is a separate act from reserving the fuel.
The delivery's `effective_commodity_rate_cents_per_therm` is computed at this point by the
blend rule in §2.6 and rounded once to four decimal places.

The rate a delivery carries is not immutable, and the same delivery can be evaluated under
two bases. Once the delivery is in `DELIVERY_CONFIRMED` or `DELIVERY_SETTLED`, the blend is
priced against the `index_rate_cents_per_therm` that was captured when it was confirmed, and
later movement in the gas market does not re-price it — a receipted load is a fact. While the
delivery is still `DELIVERY_SCHEDULED` or `DELIVERY_IN_TRANSIT`, and whenever a projection
evaluates it as a what-if, the blend instead uses the site's current
`gas_commodity_rate_cents_per_therm` as its index leg, so the very same delivery prices
differently before and after confirmation. The rate actually recorded for the delivery once
it is receipted is held in `fuel_basis_rate_cents_per_therm`.

A resource hold is a delivery that exists to reserve capacity rather than to move gas. A
`SiteOperator` takes one by supplying `requested_therms` and the pair of window boundaries
`window_start_iso8601` and `window_end_iso8601`; the server creates a delivery in
`DELIVERY_SCHEDULED` with that volume, decrements the site's `draw_position_therms`, and
moves the site's `lifecycle_state` to `RESOURCE_DRAWING`. The hold is governed by the same
fuel-pool, ceiling and window rules as any other delivery, and a hold that would breach any
of them is refused with the corresponding code rather than being partially created.
Releasing a hold is a `SiteOperator` action that names the hold through `delivery_id`: the
named delivery moves to `DELIVERY_CANCELLED`, the site's `draw_position_therms` is increased
by exactly the released `volume_therms` so that the pool returns to its prior value without
drift, and the site's `lifecycle_state` returns to `RESOURCE_AVAILABLE` — but only when the
site's `active_ppa_count` is zero, because a site still hosting live contracts has no business
declaring itself resource-free. When several holds are open at once, none of them is selected
implicitly: the release acts only on the delivery the request names, that delivery must belong
to the named site and must still be sitting in `DELIVERY_SCHEDULED`, and a delivery that does
not exist at that site is refused with `ERR_REFERENCE_NOT_FOUND` (HTTP 404) while one that has
already left the scheduled state is refused with `ERR_INVALID_STATE` (HTTP 409). The response
carries the updated site object rather than the cancelled delivery.

The resource dimension of a facility moves on its own axis through these edges. Taking
a resource hold moves a site from `RESOURCE_AVAILABLE` to `RESOURCE_DRAWING`, and it requires
the site to be `SITE_ACTIVE` — a suspended site refuses the hold with `ERR_SITE_FROZEN`
(HTTP 409) — to hold at least the requested volume in
`draw_position_therms`, and to be below its simultaneous-commitment ceiling counting all
deliveries in `DELIVERY_SCHEDULED` or `DELIVERY_IN_TRANSIT` other than the one being created.
Releasing a hold moves `RESOURCE_DRAWING` back to `RESOURCE_AVAILABLE` and requires the site
to have no live contracts left; a site whose `active_ppa_count` is not zero keeps the state it
had. A freeze carrying the reason `GRID_INTERCONNECT_FAILURE`
moves a drawing site to `RESOURCE_CLOSED`, as §2.5 describes. And an unfreeze moves
`RESOURCE_CLOSED` back to `RESOURCE_AVAILABLE` in the same transaction, with no exit-fee
acknowledgement standing between the two. The same restoration is applied by a cancellation
that empties the site's active count and by a termination that does, so a closed site whose
last contract is terminated returns to `RESOURCE_AVAILABLE` without an unfreeze.

Custody itself has three forward edges and one terminal cancellation per origin. A
`FuelCoordinator` dispatches a scheduled load, moving it from `DELIVERY_SCHEDULED` to
`DELIVERY_IN_TRANSIT`; dispatch requires the site to be `SITE_ACTIVE` and requires the count
of deliveries already in transit at that site to be strictly below
`MAX_ACTIVE_DEMANDS_PER_SITE`, and a site that is already saturated refuses with
`ERR_SITE_DEMAND_LIMIT` (HTTP 422). A scheduled load may be cancelled at any time by its
sourcing coordinator, moving `DELIVERY_SCHEDULED` to `DELIVERY_CANCELLED`; because the volume
was already deducted when the load was scheduled, cancellation returns the canceled
`volume_therms` to the site's `draw_position_therms` and, when the site has no live contracts,
returns its `lifecycle_state` to `RESOURCE_AVAILABLE`. A load already in transit may still be
cancelled, but only while the logical clock is strictly before its `confirm_after_iso8601`
instant, moving `DELIVERY_IN_TRANSIT` to `DELIVERY_CANCELLED` and restoring the volume the
same way; a cancellation asked for at or after that instant is refused with
`ERR_INVALID_STATE` (HTTP 409) rather than being treated as terminal, and a scheduled load is
always cancellable whatever the clock reads. `DELIVERY_CANCELLED` is terminal, and a cancellation aimed at a load that is
already cancelled or already settled is refused with `ERR_ALREADY_TERMINAL` (HTTP 409) rather
than silently succeeding — the same guard protects a second termination of a contract and a
second reversal of a settlement line.

Confirmation is where custody becomes accounting, and it is the system's second-deepest
cascade. A `FuelCoordinator` may receipt an in-transit load only once the logical clock has
reached the load's `confirm_after_iso8601`, only while the load's `volume_therms` still fits
within the site's `draw_position_therms`, and only while any named attesting customer passes
the three-part corroboration test. The confirmation itself is a chain: the delivery's
`lifecycle_state` becomes `DELIVERY_CONFIRMED` and its
`fuel_basis_rate_cents_per_therm` is frozen; the site's
`current_avoided_fuel_cost_cents_per_therm` is set to that delivery's
`effective_commodity_rate_cents_per_therm` capped at the sourced-index ceiling as §2.6
describes, so the whole portfolio's fuel basis now reads the
real delivery; a `PpaAccrual` of type `CHARGE_ACCRUAL` is opened in `ACCRUAL_OPEN` against the
contract that won the allocation, carrying the delivery's `volume_therms` multiplied by the
receipted rate and rounded to two decimal places, with its `source_settlement_line_id` set to
that contract's earliest-created settlement line whatever that line's state — or left null
when the contract has no line at all — and its `period_anchor_iso8601` set to the delivery's
`delivered_at`; a second `PpaAccrual` of type `CAPACITY_ACCRUAL` is opened
against the same contract carrying the availability shortfall in kilowatt-hours valued at the
contract's `availability_penalty_cents_per_kwh` and rounded to two decimal places, with its
source line left null and the same anchor; and the winning contract has its `output_guarantee_reserve_cents`
and `capacity_guarantee_reserve_cents` recomputed, while the site has its
`committed_feedstock_therms`, `draw_position_therms` and `lifetime_availability_credit_cents`
recomputed. No contract transition record is written by a confirmation: delivery custody and
contract state are separate machines, and a receipted load says nothing about whether a
contract is active. A confirmed load settles when the contract it supplied has at least one
settlement line in `SETTLEMENT_APPLIED`; at that point the delivery moves to
`DELIVERY_SETTLED`, its terminal state, and the site's `lifetime_customer_billable_cents` and
`lifetime_settled_kwh` are recomputed.

Not every load is consumed by the whole portfolio. When a delivery is scheduled — or a
resource hold is taken — the system ranks the site's contracts as candidates, and it does not
re-rank them when the load is confirmed. Candidate A, held in
`candidate_ppa_a_kwh`, is the volume multiplied by the `contracted_efficiency_kwh_per_therm`
of the earliest-created contract in `PPA_ACTIVE` at the site. Candidate B, held in
`candidate_ppa_b_kwh`, is the volume multiplied by the efficiency of the site contract with
the smallest `contracted_kw` — counted over every contract at the site whatever its state,
with a tie in capacity broken on `created_at` ascending — excluding whichever contract was
selected. The contract selected is the earliest-created contract in `PPA_ACTIVE`, or, when the
site hosts no active contract at all, the earliest-created contract in `PPA_DRAFT`,
`PPA_ACTIVE` or `PPA_SUSPENDED`; a site with no active contract therefore records a candidate A
figure of zero even though a draft contract may still be selected. The distance recorded
for the selected candidate is `candidate_ppa_distance_km`, which the system records as zero, and the output actually awarded to
the two candidates under the allocation-order basis is held in `allocated_ppa_a_kwh` and
`allocated_ppa_b_kwh`: the first candidate takes the smaller of its own figure and the selected
contract's output — the volume multiplied by that contract's efficiency — and the second takes
the smaller of its own figure and whatever the first allocation left. All four candidate
figures are carried to four decimal places. The count of the site's other pending commitments during the decision
is preserved as `active_candidate_demands_at_site`, which is the number of deliveries at the
site in `DELIVERY_SCHEDULED` or `DELIVERY_IN_TRANSIT` other than this one. The contract that
wins carries the allocation and is recorded on the delivery as `selected_ppa_id`; that
identifier is what later links the delivery to the accruals opened at confirmation, and it is
also the filter a contract-first delivery listing uses to report the loads it was awarded.

Allocation eligibility is computed, not assigned. For a contract and its offtaker, the
remaining commitment is `remaining_committed_kwh`, which is the contract's `term_years`
multiplied by its `contracted_annual_kwh` less its `lifetime_settled_kwh`. A party is
identified by joining the contract's `ppa_id` with its `customer_id`, and the party's
committed pool `party_committed_kwh` is the sum of `remaining_committed_kwh` over every one of
that party's contracts in `PPA_DRAFT`, `PPA_ACTIVE` or `PPA_SUSPENDED` at the site, treated as
a single member-level pool rather than as separate contracts. The party's already-allocated
figure `party_allocated_kwh` sums the allocated kilowatt-hours on this contract from
allocations whose period end is later than the delivery's own period. The rights figure is
the smaller of the contract's remaining commitment and the party's unallocated pool, with the
pool floored at zero. A scope ratio is then taken as the allocated kilowatt-hours divided by
the contract's `contracted_kw`, capped at `SCOPE_RATIO_CEILING`, which is 3, and a weighted
score is built from three normalised inputs weighted 0.5 for the rights figure, 0.3 for the
scope ratio and 0.2 for the term in months, scaled by 100 and rounded to two decimal places.
When the allocation carries an active party-effective flag, the allocation is additionally
capped by the party's contracted commitment. The size of the rights figure depends on how the
party is structured: a customer holding at least two contracts at the site pools its remaining
kilowatt-hours across them before the minimum is taken, while a customer holding exactly one
contract reads the single contract and therefore yields the smaller rights figure for the same
delivery.

Accruals are posted directly as well as by cascade. A `SettlementAnalyst` may post an accrual
to a contract's ledger, supplying `ppa_id`, `site_id`, an optional
`source_settlement_line_id` when the accrual traces back to a settlement line, the
`accrual_type`, the nominal `amount_cents` and a `period_anchor_iso8601` used for batch
ordering. The accrual type is one of `CHARGE_ACCRUAL`, `OUTPUT_GUARANTEE_ACCRUAL`,
`TRUEUP_ACCRUAL` or `CAPACITY_ACCRUAL`. A posted accrual opens in `ACCRUAL_OPEN` and its
`signed_amount_cents` is derived from its type: a `CHARGE_ACCRUAL` and a `CAPACITY_ACCRUAL`
both carry their `amount_cents` forward positively, while an `OUTPUT_GUARANTEE_ACCRUAL`
carries the negation of its `amount_cents`. Accruals created by a confirmation of a capacity
kind carry no `source_settlement_line_id` and leave it null. An accrual may also be reconciled
without a settlement: a `SettlementAnalyst` may run a reconciliation against a contract,
optionally naming the `accrual_id` to target. A named accrual is reconciled directly — it must
belong to the contract, or the request is refused with `ERR_REFERENCE_NOT_FOUND` (HTTP 404) —
and when no accrual is named the server takes the earliest `OPEN` accrual of that contract by
`created_at`. A contract holding no open accrual at all is refused with
`ERR_NO_ELIGIBLE_ACCRUAL` (HTTP 422), and a named accrual that is not open is refused with
`ERR_ALREADY_TERMINAL` (HTTP 409). Either way the logical clock must have reached that
accrual's creation instant plus `ACCRUAL_RECONCILE_SLA_DAYS`, which is 1 day, or the request is
refused with `ERR_INVALID_STATE` (HTTP 409); there is no further ambiguity test beyond the
creation-order walk. Each reconciliation recomputes the site's
`lifetime_settle_reconcile_count` and the customer's `reconcile_cadence_slots`; the site's
figure is derived rather than incremented, reading as the number of that site's accruals
currently sitting in `ACCRUAL_RECONCILED`, so a reversal that returns an accrual to
`ACCRUAL_OPEN` lowers it again. A
reconciliation that would leave the contract's signed accrual sum for the period unbalanced is
refused with `ERR_ACCRUAL_UNBALANCED` (HTTP 422); the same balance test guards the application
of an allowance. Where an accrual is applied against an allowance, the resulting allowance
identifier is recorded on the accrual as `applied_allowance_id`, and left null when no
allowance was applied.

### 3.4. The Settlement Line Lifecycle, Reversal and the Accrual Ledger

A settlement period is prepared by a `SettlementAnalyst` and applied by a different role
entirely, which is the point of the split in §2.1. Preparing a line requires the contract's
`expected_ppa_version` per §2.7, together with the period's `period_start` and `period_end`,
the `metered_kwh` the system actually delivered, the `downtime_hours` it was unavailable, the
`customer_source_deadline_iso8601` by which a self-sourcing customer must attest a conforming
gas index for the period — the deadline is recorded on the line and no rule reads it, so it is
a required field rather than an enforced gate — an optional `customer_index_cents_per_therm`
carrying the
customer's own gas index, and an optional `hourly_settlement` flag that defaults to false.
The line opens in `SETTLEMENT_DRAFT`. Three temporal or structural defects are caught before
it is even posted. Its `period_end` must be strictly after its `period_start`, or the request
is refused with `ERR_SETTLEMENT_PERIOD_INVALID` (HTTP 422). Its half-open interval from
`period_start` to `period_end` must not overlap any existing line on the same contract other
than lines that have been reversed, or the request is refused with
`ERR_SETTLEMENT_PERIOD_OVERLAP` (HTTP 422). And its `period_start` must not fall before the
contract's `state_entered_at` instant, or the request is refused with
`ERR_SETTLEMENT_PERIOD_BEFORE_ACTIVATION` (HTTP 422). Those three tests are evaluated before
the request's `expected_ppa_version` is compared, so a stale observed version on a malformed
period is reported as the period problem rather than as `ERR_STALE_VERSION`; the version
comparison in turn runs before the body's remaining field-level defects are reported. A line whose interval ends exactly where
its successor's interval begins does not double-count that instant, because the period is
half-open at the end.

When a customer is sourcing its own gas, the line is priced against a normalised basis rather
than the raw attested index. The customer-sourced index `customer_sourced_index_cents_per_therm`
is the smaller of the customer's `customer_index_cents_per_therm` and the site's
`gas_commodity_rate_cents_per_therm` multiplied by `SOURCED_INDEX_CEILING_MULTIPLE`, which is
1.25. An attested index above that ceiling is capped rather than rejected, and a customer that
never attests leaves the normalised basis at zero.

Validation is the analyst's act and it has its own ordering rule. A `SettlementAnalyst` may
validate a draft line only while the contract is in `PPA_ACTIVE` or `PPA_SUSPENDED`, only
while the period ends after it begins, and only while the line's
`cap_side_pool_cents` is greater than zero — a period whose cap-side pool is empty has nothing
to reconcile and may not be validated, the refusal carrying `ERR_NO_ELIGIBLE_ACCRUAL`
(HTTP 422). It must also be next in sequence: the line's ordinal
within the contract's period sequence must be strictly greater than the ordinal of the
contract's most recently applied line, or the validation is refused with `ERR_OUT_OF_ORDER`
(HTTP 422). Validation moves the line to `SETTLEMENT_VALIDATED` and computes its
`net_charge_cents` and `expected_net_charge_cents`.

Approval belongs to the `SettlementApprover` and is narrower than validation. The line must
already be `SETTLEMENT_VALIDATED`; the contract must be `PPA_ACTIVE`, which means a contract
sitting in `PPA_SUSPENDED` or `PPA_EXIT_PENDING` cannot push a line forward no matter how
complete the line is; and the contract must hold at least one issued settlement allowance of
kind `CAPACITY_ALLOWANCE` that has not yet been applied — a contract holding no such allowance
refuses the approval with `ERR_INVALID_STATE` (HTTP 409). A line whose ordinal within the
contract's period sequence — its one-based position in creation order among the contract's
lines — is greater than the contract's consumed allocation count, which is the number of its
lines sitting in `SETTLEMENT_VALIDATED`, `SETTLEMENT_APPROVED` or `SETTLEMENT_APPLIED`, is
refused with `ERR_ALLOCATION_LIMIT` (HTTP 422). Approval moves the line to
`SETTLEMENT_APPROVED`, freezes its cap-side pool at the value the line carried when it left
validation, and
computes its `availability_credit_cents` and `output_guarantee_credit_cents` under the rules
in §3.5.

Application is where the ledger moves. A `SettlementApprover` applies an approved line, and
before anything is written the ceiling from §2.9 is tested: the line's `net_charge_cents`
minus its `output_guarantee_credit_cents` may not exceed the customer's
`lifetime_customer_billable_cents` plus `SETTLEMENT_CREDIT_CAP_CENTS`, on pain of
`ERR_BUMPER_EXCEEDED` (HTTP 422). The stop-loss test from §2.9 is also re-evaluated here,
against the credit figure already accumulated rather than against a projection. When
the apply is accepted the cascade runs in a fixed order. The line moves to
`SETTLEMENT_APPLIED` and is stamped with an `applied_at` instant; the earliest-created
allowance of kind `CAPACITY_ALLOWANCE` still sitting in `ALLOWANCE_ISSUED` is consumed — its
`lifecycle_state` becoming `ALLOWANCE_APPLIED` with its `applied_direction` recorded as
`ALLOWANCE_APPLIED_AS_TIME`, and its applied-cap, applied-days and applied-amount readings
computed against the line being settled — while an allowance of the avoided-cost kind is never
consumed by a settle. A confirmed delivery whose `selected_ppa_id` is the settling contract
moves to `DELIVERY_SETTLED` in the same pass.
Every open accrual of that contract whose creation instant is at or before the settling
line's own creation instant is reconciled — its `lifecycle_state` becomes `ACCRUAL_RECONCILED`
— and the site's `lifetime_settle_reconcile_count` is recomputed as the count of the site's
accruals then sitting in `ACCRUAL_RECONCILED`. The site's `lifetime_customer_billable_cents`,
`lifetime_availability_credit_cents` and `lifetime_settled_kwh` are then recomputed, followed
by the customer's `outstanding_balance_cents`, `lifetime_settled_cents`,
`lifetime_output_guarantee_credit_cents`, `lifetime_availability_credit_cents` and
`reconcile_cadence_slots`, and finally the contract's own `lifetime_settled_kwh`,
`lifetime_settled_cents`, `committed_kwh_remaining` and `realized_guarantee_credit_cents`.
A line that has been applied is the only thing that ever moves a contract's settled totals:
draft, validated and approved lines all read the same pool but none of them writes to it.

Reversal is the correction path and it is deliberately time-boxed. A `SettlementApprover` may
reverse an applied line only while the logical clock has not passed the line's applied
instant plus `SETTLEMENT_REVERSAL_WINDOW_DAYS`, which is 15 days; a request past that window is refused with
`ERR_REVERSAL_WINDOW_CLOSED` (HTTP 409), and a reversal aimed at a line that is already
reversed is refused with `ERR_ALREADY_TERMINAL` (HTTP 409). The applied instant is read from
the line's own `applied_at` field, and a line that carries no such instant is refused the same
way; a line that has not reached `SETTLEMENT_APPLIED` at all is refused with
`ERR_INVALID_STATE` (HTTP 409) instead. Reversal moves the line to
`SETTLEMENT_REVERSED`, its terminal state, and simultaneously sets its `allocation_basis` to
`UNIT_INDEX` — the reversal itself is what reclassifies the period's allocation basis, which
is why a reversed sibling changes how its non-reversed neighbours are valued in §3.5. The
consumed allowance is handed back to `ALLOWANCE_ISSUED` when its `applied_direction` was
`ALLOWANCE_APPLIED_AS_TIME`. Every accrual that this line reconciled — the ones now sitting in
`ACCRUAL_RECONCILED` whose creation instant is at or before this line's creation instant —
returns to `ACCRUAL_OPEN`, restoring the pool to exactly its pre-application value. The
contract's `lifetime_settled_cents` is reduced by the line's `net_charge_cents` and its
`committed_kwh_remaining` is increased by the line's `metered_kwh`, because the period is
being un-delivered. The contract's `customer_earned_ppa_tokens` advances by the number of the
period's lines sitting in `SETTLEMENT_REVERSED` once this reversal has been written — never by
fewer than `EARNED_TOKEN_PER_REVERSAL`, which is 1 — while its `customer_spent_ppa_tokens`
advances by `SPENT_TOKEN_PER_REVERSAL`, which is 2; that is how the token ledger credits the
correction, and a second reversal in the same period therefore advances the earned counter by
more than the first one did. The site's `lifetime_customer_billable_cents` and the
customer's `outstanding_balance_cents` are recomputed last, and the recomputation must land on
zero drift — a reversal that leaves either aggregate disagreeing with its constituents is a
defect, not a rounding difference.

Every reversal also considers a true-up. The system counts the lines in the contract's most
recent period that are in `SETTLEMENT_REVERSED`, and separately counts the contract's accruals
that are in `ACCRUAL_OPEN`. Both counts are read before any write in the request, so the
request sees a snapshot rather than its own effects. Only when the reversed count is strictly
greater than the open count — a strict comparison, so equal counts produce a true-up of zero —
does the system write a true-up: the line's `net_charge_cents` multiplied by
`TRUEUP_EXCESS_PCT`, which is 0.15, rounded to two decimal places. Exactly one
`PpaAccrual` of type `TRUEUP_ACCRUAL` is created or updated in `ACCRUAL_OPEN` for the contract
carrying that amount, and a true-up accrual's `signed_amount_cents` is its `amount_cents`
carried positively. A contract carries at most one open true-up accrual at a time: a reversal
that earns a true-up overwrites the amount of the contract's latest-created open
`TRUEUP_ACCRUAL` when one exists and otherwise creates it, so repeated reversals move the same
accrual to the newest figure rather than accumulating increments, and a reconciliation run
writes no true-up of its own — only a reversal does. When several lines in a period are affected,
the charge carried by each non-reversed line is adjusted by the reversal: the line's discount
is the stored base allocation multiplied by the allocation discount percentage, where that
percentage is the count of the contract's non-reversed lines in the period divided by the
period's total line count including reversed lines, capped at
`ALLOCATION_DISCOUNT_CEILING_PCT`, which is 0.35; the adjusted charge is the line's
`net_charge_cents` less that discount. The evaluation order is pinned left to right — read the
stored base allocation first, apply the discount second, compare against the period cap only
afterwards — and the adjusted figure is never fed back into the discount computation. Because
the base charge ignores the reversal and the discount keys on it, the adjusted charge
`net_charge_allocated_cents` is the base less the discount and nothing further. The
non-reversed count includes lines in `SETTLEMENT_VALIDATED`, `SETTLEMENT_APPROVED` and
`SETTLEMENT_APPLIED`; the total additionally counts reversed lines. Recomputing the period's
lines in creation order means each line's discount is measured against the running
non-reversed count as it stood at that line, while recomputing in descending unit index means
each line sees the fully adjusted period count immediately and the first line processed is
discounted less than it would be under the creation-order walk. The per-period allocation
remainder is capped at `PERIOD_ALLOCATION_CENT_CAP`, which is 75,000 cents. The line also
carries an `hourly_charge_cents`, which is zero unless the line was settled on the hourly
basis, in which case it is the sibling ratio of the contract's hourly line count over that
count plus one, applied to the line's `net_charge_cents`.

A `SiteOperator` may also drive the period forward in bulk. The rollover process works
site by site — the request may name a `site_id`, and when it does not every site is walked in
creation order — and at each site it selects that site's lines that are in
`SETTLEMENT_APPROVED` and whose `period_end` is at or before the current logical clock. It
walks them in a pinned order — by
`period_end` ascending, then by `created_at` ascending, then by `net_charge_cents`
descending — and settles each one against a running pool that opens at `POOL_OPENING_CENTS`,
which is 500,000 cents. For each row in that order the pool is reduced by the row's settled
amount; if the pool would go negative, the row's settled amount is clamped downward by exactly
the shortfall and the pool is set to zero, so the shortfall carries forward rather than landing
as a negative balance, and the clamped figure is written onto the row as `settled_cents` while
its `net_charge_cents` keeps the value it carried. Each row is then moved to
`SETTLEMENT_APPLIED` and stamped with an `applied_at` instant, and every open accrual of that
row's contract whose creation instant is at or before the row's own creation instant is
reconciled with it. The pool is per site, not per contract: it restarts from its opening figure
at each site the walk reaches. There is no post-pass over tied rows and no fallback to the
earliest-created row — the walk above is the whole of the ordering. The
rollover also computes the two-offtaker savings split described in §3.5 over the site's applied
lines, and the response reports the settled line identifiers, the sites processed, the closing
pool of the last site walked and that site's savings figure.

The contract also carries a term-end rebate that only becomes visible on the last day, and the
API does not compute it: no operation derives leftover days, an unused paid amount or a
used-paid figure, and no contract field records any of them. The only rebate the system applies
is the constant `REBATE_CENTS`, which is zero, subtracted from the buyer cost of the transfer
valuation described in §3.8, so a contract held on the transferred basis and one held on the
as-built basis value that line identically.

### 3.5. Escalated Rates, Pool Waterfalls and the Two Charge Bases

A settlement line carries two competing statements of what the period costs, and the
difference between them is deliberate. The realized figure, `net_charge_cents`, is assembled
from four pools. The `cap_side_pool_cents` is the sum of the contract's open accruals whose
type is `CHARGE_ACCRUAL` or `OUTPUT_GUARANTEE_ACCRUAL` and whose lifecycle state is
`ACCRUAL_OPEN`, ordered by creation instant ascending, taking each accrual's
`signed_amount_cents`. The `variable_energy_cents` is the period's `metered_kwh` multiplied by
the contract's `effective_tariff_cents_per_kwh`, plus the period's `metered_kwh` multiplied by
the contract's `effective_fuel_adder_cents_per_therm` and divided by its
`contracted_efficiency_kwh_per_therm`, with each of the two products rounded to two decimal
places on its own before they are summed. The `fixed_purchase_cents` is the contract's
`term_years` multiplied by its `contracted_annual_kwh`, multiplied by its
`purchase_price_cents_per_kwh`, divided by twelve, rounded to two decimal places. The
`loss_component_cents` is the `cap_side_pool_cents` multiplied by `LOSS_ALLOCATION_PCT`, which
is 0.04, rounded to two decimal places. The line's `net_charge_cents` is then the sum of four
separately rounded floors: the pool rounded to two decimal places, plus the variable energy
rounded to two decimal places, plus the fixed purchase rounded to two decimal places, plus the
loss component rounded to two decimal places. Rounding the assembled total once instead would
land on a different cent figure and is not what the system does. The line also exposes the
untaken path for auditability: `component_sum_cents` is the sum of the four escalation-step
components each rounded independently, and `single_round_cents` is the same four steps summed
unrounded and rounded once at the end, so the two fields differ exactly by the rounding
remainder.

Which accruals a line sees depends on where the line sits. A line in `SETTLEMENT_DRAFT` or
`SETTLEMENT_VALIDATED` reads accruals that are still `ACCRUAL_OPEN` at the moment it is read,
which means a later confirmation of a delivery changes a draft figure. A line in
`SETTLEMENT_APPROVED` or `SETTLEMENT_APPLIED` freezes its pool at the value observed when the
line left `SETTLEMENT_VALIDATED`, so subsequent accrual reconciliation does not move it and the
same inputs produce a different total than the draft basis would. Reconciled accruals are
excluded from the pool but replay into the contract's `lifetime_settled_cents`.

The second statement is the forecast, `expected_net_charge_cents`, which is built by a
different route and does not agree with the realized figure by construction. Its input is the
line's `escalated_rate_cents_per_kwh`, the rate read from the ladder at this period rather
than at the present instant. It is built in steps. Each of the period's lines contributes a
per-line amount equal to the smaller of the days that line covers and the days remaining —
where remaining days are the contract's `committed_kwh_remaining` divided by its
`contracted_annual_kwh` and multiplied by 365 — multiplied by that line's own
`escalated_rate_cents_per_kwh` and rounded to two
decimal places; those per-line amounts are then summed, so the period's figure is the sum of
rounded lines rather than a rounded sum of lines. Then a straddling tax is added: when at least
one of the period's lines spans a month boundary, the summed straddling line amounts are
multiplied by the site's `tax_rate_pct` and rounded to two decimal places, and when no line
straddles a boundary the straddling tax is zero. Then an escalation tax delta is added: the
whole years elapsed since the contract's `state_entered_at`, multiplied by the contract's
daily rate and rounded to two decimal places, then multiplied by `TAX_DELTA_PCT`, which is
0.06, and rounded to two decimal places again. The expected net charge is the period figure
plus the straddling tax plus the escalation tax delta. The elapsed-year count is floored, so a
period that begins exactly on the contract's anniversary uses the un-escalated rate. The delta
term is not the same for a past period and a future one: a line whose `period_end` has already
passed uses `TAX_DELTA_PCT` as stated, while a line whose `period_end` lies after the current
logical clock replaces it with `TAX_DELTA_PCT` multiplied by `FORECAST_DISCOUNT_PCT`, which is
0.85, so the identical line yields a smaller expected charge when it is still a forecast.

The recurring pools resolve in a waterfall rather than in one formula. The resource-side pool,
`resource_side_pool_cents`, is the sum of the contract's `CAPACITY_ACCRUAL` accruals that are
`ACCRUAL_OPEN`. The pool remaining after resources is the `cap_side_pool_cents` less the
resource-side pool, floored at zero. A loss headroom equal to the line's `loss_component_cents`
is then deducted, again flooring the result at zero, giving the pool after loss. Two shortfalls
are then subtracted from it. The output shortfall is the excess, floored at zero, of the
guaranteed period output over the actual period output, valued at the contract's
`effective_tariff_cents_per_kwh` and rounded to two decimal places; the guaranteed period
output is the contract's `contracted_annual_kwh` multiplied by the period's days and divided by
365, the period's days being the span from `period_start` to `period_end` divided by 86,400 and
truncated to a whole number, and the actual period output sums `metered_kwh` over the
contract's `SETTLEMENT_APPLIED` lines whose `period_start` falls inside the window from
`period_end` minus the period's days up to `period_end`. The capacity shortfall is the
availability shortfall in kilowatt-hours — one minus `guaranteed_availability_pct`, multiplied
by `expected_annual_site_load_kwh`, floored at zero — valued at the contract's
`availability_penalty_cents_per_kwh` and rounded to two decimal places. The line's realized
figure is not this residual: `net_charge_cents` remains the four-pool sum assembled above, and
the two shortfalls are read separately rather than being subtracted from it, so a shortfall
that exceeds the pool after loss is not carried into a later period's `cap_side_pool_cents`.
None of those intermediate readings is materialized on the line: the pool fields a line
publishes are its cap-side pool, its resource-side pool and its loss component, and the two
shortfalls are computed where the guarantee remedy and the reserve need them rather than being
stored as a waterfall residual. Which value the line's `allocation_basis` carries does not
change its net charge either — `net_charge_cents` is the four-pool sum under either value. The
basis is a label a reversal sets, and the re-pricing it signals is carried by the discount the
period's non-reversed siblings take, which is the count of non-reversed lines in the period
divided by the period's total line count and capped at `ALLOCATION_DISCOUNT_CEILING_PCT`; that
discount is what turns `net_charge_cents` into `net_charge_allocated_cents`.

The availability guarantee is funded by a monthly escrow draw rather than by an unbudgeted
payment. The `availability_credit_cents` on a line is `AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT`,
which is 0.60, multiplied by the contract's `capacity_guarantee_reserve_cents`, rounded to two
decimal places. The reserve the draw reads is the escrowed `capacity_guarantee_reserve_cents`
described in §2.9 — the opening commitment less the accumulated credits — so the monthly
credit is the same fraction of the live reserve the contract actually holds, and a reserve
already drawn down by earlier credits funds a smaller monthly credit. The shortfall that drives the credit is measured against the whole modelled
facility load when the line is settled monthly, and against the contracted capacity when the
line is settled hourly — the contracted-capacity reading being `contracted_kw` multiplied by
8,760 hours and by one minus the guaranteed availability fraction — so the identical site can
produce a smaller or larger credit depending on which basis the line used.

The output guarantee pays a remedy through two tiers and a gate, and it is capped by the pool.
The billed monthly charge for the gate is the line's `net_charge_cents` rounded to two decimal
places. The output shortfall is the same guaranteed-versus-actual excess described above,
valued at the escalated customer rate and rounded to two decimal places. An energy component is
then derived: the output shortfall multiplied by `ENERGY_REMEDY_PCT`, which is 0.92, and
multiplied again by the smaller of one and the ratio of the billed monthly charge to
`OUTPUT_REMEDY_REFERENCE_CENTS`, which is 380,000 cents, with the result rounded to two decimal
places. That component is then tiered: when it is at or below `OUTPUT_REMEDY_TIER0_CENTS`,
which is 100,000 cents, it is multiplied by `TIER0_PAYOUT_PCT`, which is 1.35; otherwise it is
capped at `OUTPUT_REMEDY_TIER1_CENTS`, which is 90,000 cents. A separate availability
component is the availability shortfall in kilowatt-hours valued at the contract's
`availability_penalty_cents_per_kwh`, floored at zero and rounded to two decimal places. The
divisor applied to the energy component is itself gated on the billed charge: when the billed
monthly charge is at least `OUTPUT_REMEDY_TIER0_CENTS` the gate percentage is
`TIER1_PAYOUT_PCT`, which is 0.80, and otherwise it is `TIER0_PAYOUT_PCT`. The line's
`output_guarantee_credit_cents` is the energy component multiplied by the gate percentage,
rounded to two decimal places, plus the availability component rounded to two decimal places.
The remedy as a whole is then capped at the line's `cap_side_pool_cents`, so the guarantee can
never pay out more than the pool funded. The two high-load multiples the constant table names,
`HIGH_LOAD_TIER_1_MULTIPLE` at 1.75 and `HIGH_LOAD_TIER_2_MULTIPLE` at 1.55, are not reached by
any operation: the remedy is the tiered path above and no high-load variant of it is produced
or exposed. When a line is settled on the hourly basis rather than monthly, the energy component is
multiplied by the sibling ratio of the period's hourly line count over that count plus one, so
the identical shortfall yields a smaller credit.

Shortfalls are valued for the guarantee remedy, but the API exposes no pair of counter-pools
that reconcile against each other: no operation computes a `forecast_pool_cents`, a per-line
unit pool, or a funded forecast figure, and no reversal window is applied when the actual
output behind a shortfall is summed — a reversed line simply drops out of the sum, because only
`SETTLEMENT_APPLIED` lines are read. The shortfall figures the system does publish are the
per-line output shortfall described above and the contract's `output_guarantee_reserve_cents`,
which is the shortfall over the contract's trailing year of applied output — the applied lines
whose `period_start` falls within the year ending at the current logical instant — valued at
the escalated customer rate, with a draft contract's reserve reading as its opening commitment
with no credits netted against it.

### 3.6. Settlement Allowances and the Two Faces of a Credit

A settlement allowance is a credit the operator grants against a contract, and it passes
through two hands. A `SettlementAnalyst` issues one by supplying the `allowance_kind`, the
nominal `amount_cents` and the contract's `expected_ppa_version` per §2.7. The kind is either
`AVOIDED_COST_ALLOWANCE` or `CAPACITY_ALLOWANCE`. Issuing is gated on the contract actually
having something to credit: at least one accrual at that contract must be sitting in
`ACCRUAL_OPEN`, and a contract whose ledger is fully reconciled refuses the issuance with
`ERR_NO_ELIGIBLE_ACCRUAL` (HTTP 422). That gate is evaluated before the version comparison, so
a stale observed version on a contract with nothing to credit is reported as the accrual
problem rather than as `ERR_STALE_VERSION`. An issued allowance sits in `ALLOWANCE_ISSUED` with its
`applied_direction` null, and it has no effect on any balance until it is applied.

Applying the allowance is a separate act by the same analyst role, and which of two branches
it takes is decided by the contract's ledger as a whole rather than by any period the request
names. When the contract carries no reversed line, or carries one but has no open accrual to
offset, the allowance is applied as time: its `lifecycle_state` becomes
`ALLOWANCE_APPLIED` and its `applied_direction` is recorded as `ALLOWANCE_APPLIED_AS_TIME`.
When the contract carries at least one reversed line and at least one open accrual, the
allowance is applied as a reversal instead, targeting the contract's earliest-created accrual
still in `ACCRUAL_OPEN`. In that branch the
allowance's `applied_to_accrual_id` is set to that accrual and its `applied_to_ppa_id` is set
to that accrual's own contract, its `applied_direction` is recorded as
`ALLOWANCE_APPLIED_AS_REVERSAL`, and the target accrual's `signed_amount_cents` is recorded as
offset by the allowance amount — unless that offset would drive the signed amount below zero
while the accrual's nominal `amount_cents` is positive, which is refused with
`ERR_ACCRUAL_UNBALANCED` (HTTP 422). An allowance that has already been applied is refused
with `ERR_ALREADY_TERMINAL` (HTTP 409). The two branches are not interchangeable: applying a
reversal-directed allowance as time, or applying a time-directed one as a reversal, is a
defect rather than a preference. The apply also runs the stop-loss test from §2.9 and the
credit ceiling from §2.9, and a violation is refused with `ERR_GUARANTEE_FLOOR_BREACH`
(HTTP 422) or `ERR_BUMPER_EXCEEDED` (HTTP 422) respectively; an application that would leave
the contract's signed accrual sum for the period unbalanced is refused with
`ERR_ACCRUAL_UNBALANCED` (HTTP 422).

What an allowance is actually worth in days is computed rather than declared. The target line
every reading below is taken from is the contract's most recently created settlement line,
whatever state that line sits in; a contract with no line at all leaves the applied cap at
zero, so the allowance still buys its single floor day. The applied cap,
`applied_cap_cents`, is the smaller of the allowance's `amount_cents` and twice the target
line's `net_charge_cents` — an allowance never credits more than two periods' worth of charge,
however large the nominal amount. The daily energy figure, `daily_energy_cents`, is the target
line's daily kilowatt-hours multiplied by `effective_tariff_cents_per_kwh`, rounded to two
decimal places, where the daily figure is the line's `metered_kwh` divided by `DAILY_KWH_DIVISOR`,
which is 30. The capped daily energy, `capped_daily_energy_cents`, is that figure capped at
`DAILY_ENERGY_CAP_CENTS`, which is 250,000 cents — the cap applies to the energy leg only. The
daily fixed figure, `daily_fixed_cents`, is the daily kilowatt charge `daily_kw_charge_cents_per_kw`,
which is 1 cent per kilowatt per day, multiplied by the target contract's `contracted_kw`, rounded to two decimal places; the fixed
leg is never capped. The number of days the allowance buys, `applied_days`, is the applied cap
divided by the sum of the capped daily energy and the daily fixed figure, truncated toward zero,
and then floored at one — an allowance whose cap is smaller than a single day still buys
exactly one day, and the truncation is a floor rather than a rounding, so a cap that would buy
1.9 days buys 1. The applied amount, `applied_amount_cents`, is that day count multiplied by
the sum of the capped daily energy and the daily fixed figure. The two allowance kinds diverge
here: the two kinds compute their day counts identically — both take the applied cap from twice
the target line's `net_charge_cents`, both cap the energy leg at `DAILY_ENERGY_CAP_CENTS` while
leaving the fixed leg uncapped, and both floor the day count at one — so the same nominal
amount buys the same number of days whichever kind it is. The kinds diverge in what they leave
behind: a `CAPACITY_ALLOWANCE`, once applied, increments the site's
`reserved_capacity_hold_count` and is the only kind that draws against the capacity reserve,
while an avoided-cost allowance moves no site counter at all.

An avoided-cost credit does not simply add a charge to a running balance; it folds into it.
Under the chronological reading, the delta is the new line's `net_charge_cents` added on top of
the already-reduced running balance, which means every prior reversed line in the period has
already been pre-netted and the new line is the only addition still outstanding. Under the
forward-looking reading, the delta is the new line's `net_charge_cents` less the gross charge
of the specific reversed line the allowance names, and the running fold is ignored entirely.
For identical evidence the two readings do not agree: a period that contains at least one
reversed line produces a strictly larger credit under the chronological reading precisely
because reversed lines have been pre-netted, while a period with no reversed line but a
replacement line named by the allowance produces only the net delta and therefore credits
less.

The settlement machinery carries one field that is a placeholder rather than a feature. A
settlement line accepts `expense_hold_days`, but the system does not implement a deferral
behind it: it defaults to 0 and a line that expresses no deferral sets it to 0, and no
behaviour in the system reads a non-zero value. It exists so that the field is present for
compatibility and it must not be treated as an instruction to defer anything.

### 3.7. Remote Monitoring, Maintenance Windows and Module Replacement

Every live contract is maintained through a service plan created by a `ServiceEngineer`, and
the plan carries three independent dimensions that move on their own schedules: an operational
lifecycle, an independent hardware-replacement stage, and a monitoring health reading. A plan
may be created against a contract with a declared `remote_monitoring_status` of
`MONITORING_LINKED` or `MONITORING_DEGRADED`, a clearance `radius_buffer_m`, and a maintenance
window declared as `window_start_iso8601` and `window_end_iso8601`. A plan created by hand
starts in `SERVICE_PLAN_DRAFT` — unlike the plan an activation cascade creates, which moves
itself to `SERVICE_ACTIVE` immediately. Both window boundaries are nullable, and the plan's
contribution to the site's clearance total is its `radius_buffer_m` counted only while the
plan is in `SERVICE_ACTIVE` or `SERVICE_MAINTENANCE_WINDOW_OPEN`; a suspended plan releases
its radius back to the site. Two safety rules govern a new plan. Maintenance windows at one
site must be pairwise separated by at least `MAINTENANCE_GAP_DAYS`, which is 7 days, and a new window that comes
closer than that to a window already declared at the same site is refused with
`ERR_WINDOW_VIOLATION` (HTTP 422) — the comparison covers every non-archived plan at that site
which declares a window, whatever its lifecycle state, not only the plans currently in a
maintenance window. A window whose start is not strictly before its own end is refused with the
same code, and the two boundaries are supplied together or not at all, a half-supplied pair
being a malformed request under `ERR_INVALID_REQUEST` (HTTP 400). And the summed clearance
radius across the site's active and
window-open plans must not exceed the site's `clearance_zone_capacity`; a plan that would push
the sum past the capacity is refused with `ERR_FOOTPRINT_EXCEEDED` (HTTP 422). Creating a plan
is not gated on the contract's state: a plan may be declared against a contract in any state,
including a terminated one. A plan may also
not have its maintenance window overlap the cure window of a contract at the same site that is
in `PPA_EXIT_PENDING`, unless the plan is that exiting contract's own plan and its window
start is strictly earlier than its window end; a conflict is refused with
`ERR_EXIT_WINDOW_CONFLICT` (HTTP 422), and the same guard applies when an exit is requested
that would collide with an existing window. A plan's `rollout_schedule_compliant` flag reports
whether the site's open plan windows are pairwise separated by the required gap.

The plan lifecycle has one entry edge and several exits. A plan moves from `SERVICE_PLAN_DRAFT`
to `SERVICE_ACTIVE` when its contract enters `PPA_ACTIVE` in the same transaction, which is
what the activation cascade in §3.2 exercises. A plan already `SERVICE_ACTIVE` whose window
boundaries are both non-null enters `SERVICE_MAINTENANCE_WINDOW_OPEN` when the logical clock
reaches the window: the window's start must be at or before the current instant and the current
instant must be at or before the window's end, and the site must be able to accommodate the
plan's radius within its remaining clearance capacity. Entering a maintenance window is not
cosmetic — it recomputes the site's `clearance_zone_used` over every plan in `SERVICE_ACTIVE`
or `SERVICE_MAINTENANCE_WINDOW_OPEN`, and it recomputes the parent contract's
`effective_tariff_cents_per_kwh` and `availability_penalty_cents_per_kwh`, because a system
sitting in a maintenance window is not delivering the output its tariff was priced against. A
plan in a maintenance window returns to `SERVICE_ACTIVE` either when the clock moves past the
window's end or when the site is unfrozen, and that edge is a cycle: the plan can re-enter a
maintenance window later. A plan moves from either `SERVICE_ACTIVE` or
`SERVICE_MAINTENANCE_WINDOW_OPEN` to `SERVICE_SUSPENDED` when its contract leaves `PPA_ACTIVE`
in the same transaction — through a site freeze, through an exposure hold, or through any other
route — and in both cases the site's clearance total is recomputed because a suspended plan
releases its radius. A suspended plan returns to `SERVICE_ACTIVE` when its contract re-enters
`PPA_ACTIVE` in the same transaction and the site's `status` is `SITE_ACTIVE`; that edge is
also a cycle. And a plan reaches its terminal state `SERVICE_ARCHIVED` from `SERVICE_ACTIVE`,
from `SERVICE_SUSPENDED` or from `SERVICE_MAINTENANCE_WINDOW_OPEN` when its contract enters
`PPA_TERMINATED`, with the site's clearance total recomputed every time.

Hardware replacement runs on its own axis, independent of the lifecycle. A `ServiceEngineer`
schedules a module replacement against a plan, moving `REPLACEMENT_NONE` to
`REPLACEMENT_SCHEDULED`; the operation requires the parent contract to be `PPA_ACTIVE`, the
plan to be `SERVICE_ACTIVE`, and the plan's `monitoring_degraded_days` to be at most
`MODULE_DISPATCH_HOLD_DAYS`; the hardware stage must also still be `REPLACEMENT_NONE`, and a
contract that is not active, a plan that is not active, a stage other than `REPLACEMENT_NONE`,
and a link degraded beyond the tolerance are each refused with `ERR_INVALID_STATE` (HTTP 409).
A site that is not active refuses the scheduling with
`ERR_SITE_FROZEN` (HTTP 409), because a replacement cannot be staged on a site whose
operations are suspended. Dispatching the scheduled replacement moves `REPLACEMENT_SCHEDULED`
to `REPLACEMENT_DISPATCHED`, requires the stage to be `REPLACEMENT_SCHEDULED`, requires the
contract's `assigned_service_plan_id` to be this plan — a plan that is not the contract's
assigned plan is refused with `ERR_INVALID_STATE` (HTTP 409) — requires the plan's
`dispatch_hold` to be false, also refused with `ERR_INVALID_STATE`, and arms a deferred action that returns
the stage to `REPLACEMENT_NONE` once the logical clock reaches the dispatch instant plus
`MODULE_REPLACEMENT_REVERT_HOURS`; that revert is what closes the loop and makes the hardware
axis cyclic. When a site is frozen, every plan whose stage is `REPLACEMENT_SCHEDULED` moves to
`REPLACEMENT_BLOCKED`, and when the site is unfrozen, every blocked plan whose lifecycle is
`SERVICE_ACTIVE` returns to `REPLACEMENT_SCHEDULED`. A dispatched replacement is not blocked by
a freeze — the parts are already moving.

Monitoring health feeds the replacement gate through a single derived reading. The plan records
`monitoring_degraded_at`, the logical instant the link last reported degraded, null while the
link is healthy, and derives `monitoring_degraded_days` as the whole days between the current
logical clock and that instant, reading zero when the instant is null. The instant is never
written by any request — a plan is created with it null whatever `remote_monitoring_status` it
declares — so `monitoring_degraded_days` reads zero and `dispatch_hold` is false on every plan
the API can produce. The gate that would hold a dispatch back when the figure exceeds
`MODULE_DISPATCH_HOLD_DAYS` is therefore computed but never armed, and a link degraded for
longer than the tolerance cannot arise through any operation the API exposes. Because the plan's daily energy and fixed figures are read at the line level rather than
at the plan level, a plan in a maintenance window does not stop the contract's settlement lines
from being prepared — it changes the tariff they are priced against, as described above.

### 3.8. Exit, Cure, Termination and Transfer of a Contract

A contract that is live does not simply stop; it passes through a cure window before it is
terminated, and a customer that fixes the problem keeps the contract. A `SiteOperator`
records an exit request on a contract that is either `PPA_ACTIVE` or `PPA_SUSPENDED`. The
request requires that the site host no deliveries in `DELIVERY_SCHEDULED` or
`DELIVERY_IN_TRANSIT` at that moment — a contract whose fuel is already moving cannot be
walked away from mid-load — and requires the contract's `customer_cure_deadline_days` to be
at least 1, since a cure window of zero days would make the deferred termination immediate. A
contract whose state is neither of the two admitted states, a site with fuel in motion and a
zero-day cure window are each refused with `ERR_INVALID_STATE` (HTTP 409).
When the contract is currently `PPA_ACTIVE` the site must additionally be `SITE_ACTIVE`; a
site that requires an exit request while it is suspended refuses the request with
`ERR_SITE_FROZEN` (HTTP 409). The request also refuses when the contract's `transfer_stage` is
`TRANSFER_BLOCKED`, with `ERR_TRANSFER_BLOCKED` (HTTP 409); the same freeze applies to a
renewal and to a transfer request, so a contract that is blocked from moving cannot be
renewed, transferred or exited until the block is lifted. When the request is accepted, the
contract's `state` becomes `PPA_EXIT_PENDING`, its `state_entered_at` is refreshed to the
current logical clock, its `exit_fee_cents` is recomputed from the interconnection basis
described in §3.1, a transition record is appended with trigger code `EXIT_REQUESTED` — or
`EXIT_REQUESTED_FROM_SUSPENDED` when the request came from the suspended state — and the
contract's cure deadline is recorded as the exit-request instant plus
`customer_cure_deadline_days` in the contract's `exit_deadline_iso8601` field, which is cleared
again whenever the contract leaves `PPA_EXIT_PENDING`. A request that would collide with a
maintenance window is refused with `ERR_EXIT_WINDOW_CONFLICT` (HTTP 422): the collision test
reads every plan at the site other than the contract's own plan which declares both window
boundaries, and refuses when that window starts before the cure deadline the request would set
while ending after the current instant. That deadline is not self-executing: the contract is terminated
only by the explicit termination call, which is admitted once the deadline has passed.

Curing is the customer's remedy and it reverts the contract cyclically. A `SiteOperator`
records a cure on a contract in `PPA_EXIT_PENDING`, and the cure is accepted only while the
logical clock is at or before the contract's `state_entered_at` plus
`customer_cure_deadline_days`, and only while the site is `SITE_ACTIVE`. A contract that is
not sitting in `PPA_EXIT_PENDING` and a cure asked for after the deadline has passed are each
refused with `ERR_INVALID_STATE` (HTTP 409), and a cure attempted while the site is not
`SITE_ACTIVE` is refused with `ERR_SITE_FROZEN` (HTTP 409). On acceptance the
contract returns to `PPA_ACTIVE` — this is the cyclic edge that makes the contract state
machine non-linear, the path from `PPA_ACTIVE` through `PPA_EXIT_PENDING` and back — its
`state_entered_at` is refreshed, its `exit_fee_cents` is reset to zero, the most recent
transition record for that contract has its `transition_reversed` flag set to true, and a new
transition record is appended with trigger code `EXIT_CURED`. The cure also recomputes the
contract's escalated rate — the `effective_tariff_cents_per_kwh` the annual ladder reads at the
refreshed `state_entered_at` — and it grants no extension of any kind: no operation derives,
records or exposes a `contract_extension_days` figure, and the downtime-shortfall machinery
behind one is not reached by any request. Note that a cure does not undo the fuel and succession accounting
the exit request triggered; only the fee itself is zeroed.

Termination is the terminal edge and it is reachable only after the cure window has actually
lapsed. A `SiteOperator` terminates a contract in `PPA_EXIT_PENDING` only while the logical
clock is strictly past the contract's `state_entered_at` plus
`customer_cure_deadline_days`; a termination attempted before that instant is rejected with
`ERR_INVALID_STATE` (HTTP 409), and a termination aimed at a contract that is not sitting in
`PPA_EXIT_PENDING` is refused the same way. A
second termination of the same contract is refused outright with `ERR_ALREADY_TERMINAL`
(HTTP 409), and so is any operation aimed at a contract whose state is `PPA_TERMINATED` other
than a renewal — the terminal-state guard is a state precondition of the machine, not a
concurrency rule, and it reads the contract's state rather than its version. Termination moves
the contract to `PPA_TERMINATED`, refreshes `state_entered_at`, decrements the site's
`active_ppa_count`, returns the site's `lifecycle_state` to `RESOURCE_AVAILABLE` when the
active count has reached zero and the site still holds a positive `draw_position_therms`,
moves the contract's assigned service plan to `SERVICE_ARCHIVED`, recomputes the site's
`clearance_zone_used`, `contracted_purchase_cents` and `committed_feedstock_therms`, recomputes
the customer's `active_ppa_count` and `reconcile_cadence_slots`, and appends a transition
record with trigger code `PPA_TERMINATED`. The termination also recomputes the site's
`exit_fee_cents` exposure from the standby and interconnection basis, because a terminated
contract leaves physical equipment behind.

Renewal is the only way back out of the terminal state, and it runs through the renewal
review dimension rather than through the contract alone. A `CustomerService` operator offers a
renewal to a customer whose `status` is `CUSTOMER_ACTIVE` and whose `active_ppa_count` is at
least 1, moving the customer's `renewal_stage` from `RENEWAL_NONE` — or from
`RENEWAL_DECLINED`, which is how a declined review is reopened — to `RENEWAL_OFFERED`. An offer
made to a customer who is not active, who holds no active contract, or whose review is already
`RENEWAL_OFFERED` or `RENEWAL_ACCEPTED` is refused with `ERR_INVALID_STATE` (HTTP 409). The
same `CustomerService` role then records the customer's answer, because no other role is
admitted to those two operations: acceptance moves `RENEWAL_OFFERED` to `RENEWAL_ACCEPTED`
and carries no monetary effect until a contract is actually renewed; declining moves
`RENEWAL_OFFERED` to `RENEWAL_DECLINED` and appends a transition record with trigger code
`PPA_RENEWAL_REFUSED` for every one of that customer's contracts sitting in `PPA_SUSPENDED`. An
accept or decline requested while the customer's `renewal_stage` is not `RENEWAL_OFFERED` is
refused with `ERR_RENEWAL_STAGE_INVALID` (HTTP 409) — the review dimension admits no shortcuts
past the offer. Because a decline is itself reversible, offering a renewal again moves
`RENEWAL_DECLINED` back to `RENEWAL_OFFERED` under the same conditions as the first offer, so
the renewal dimension is cyclic and evolves independently of the relationship posture
dimension: a customer can be in `CUSTOMER_CREDIT_HOLD` and `RENEWAL_OFFERED` at the same time.
A `SiteOperator` then renews a terminated contract, which requires the customer to be
`CUSTOMER_ACTIVE`, the customer's `renewal_stage` to be `RENEWAL_ACCEPTED` and the site to be
`SITE_ACTIVE`; a contract that is not terminated, a customer who is not active and a review
that has not been accepted are each refused with `ERR_INVALID_STATE` (HTTP 409), and a
suspended site is refused with `ERR_SITE_FROZEN` (HTTP 409). The renewal moves the contract
back to `PPA_ACTIVE`, refreshes
`state_entered_at`, moves the site's `lifecycle_state` to `RESOURCE_DRAWING`, increments the
site's `active_ppa_count`, returns the contract's archived service plan to `SERVICE_ACTIVE`
when it has one, resets the customer's `renewal_stage` from `RENEWAL_ACCEPTED` back
to `RENEWAL_NONE`, and appends a transition record with trigger code `PPA_RENEWED`. A renewal
requested while the contract's `transfer_stage` is `TRANSFER_BLOCKED` is refused with
`ERR_TRANSFER_BLOCKED` (HTTP 409).

Transfer is how a contract changes hands when a facility is sold. A `SiteOperator` requests a
transfer, naming the contract through `ppa_id`, the receiving party through
`accepting_customer_id` and, optionally, the basis the contract will be held on through
`transfer_basis`; a request that leaves the basis unstated transfers the contract onto
`PPA_BASIS_TRANSFERRED`, while one naming `PPA_BASIS_AS_BUILT` leaves it on the as-built basis.
An `accepting_customer_id` that does not resolve to a real customer is refused with
`ERR_REFERENCE_NOT_FOUND` (HTTP 404).
The transfer requires the customer relationship to actually be in a state that justifies
reassignment: a `CREDIT_SUBSTANDARD` customer may only have a transfer requested for it while
its hold is armed, and a transfer requested outside that condition is refused with
`ERR_CREDIT_TIER_INELIGIBLE` (HTTP 422). A transfer requested while the contract's
`transfer_stage` is `TRANSFER_BLOCKED` is refused with `ERR_TRANSFER_BLOCKED` (HTTP 409).
Those two conditions, together with the ordinary resolution and field validation of what the
request names, are the whole of the transfer's refusals: the request is not gated on the site's
posture or on the contract's `state`, so a contract hosted at a suspended site may still be
transferred. Nothing in this document sets `transfer_stage` to `TRANSFER_BLOCKED` — the
freeze cascade leaves the stage untouched — so the guard is a condition the transfer reads
rather than one the operations described here produce. On
acceptance the contract's `customer_id` becomes the accepting customer, its `contract_basis`
becomes the basis the request named — or `PPA_BASIS_TRANSFERRED` when it named none — and the
contract's `customer_earned_output_tokens` is
increased by the transfer token grant, which is 1 token. The response carries the updated
contract with the valuation attached to it as a `transfer_valuation` object. A contract that has never been transferred carries the
`contract_basis` value `PPA_BASIS_AS_BUILT`, which is also the value its `contract_basis`
takes by default when it is drafted, and it carries the `transfer_stage` value `TRANSFER_NONE`
until something blocks it; `transfer_stage` moves independently of `state`, so a contract can
be `PPA_ACTIVE` and `TRANSFER_BLOCKED` at the same time. No operation ever sets a contract's
`originating_ppa_id`: a transfer moves the contract itself onto a new offtaker rather than
creating a successor row, so the listing of the contracts transferred from a contract is always
empty and the field stays null on every contract the API can produce. The valuation the transfer reports is assembled from
three down payments and a set of load-shaped adjustments. The first down payment is
`DOWN_PAYMENT_1_PCT`, which is 0.055, multiplied by the contract's
`effective_tariff_cents_per_kwh` and by the site's `expected_annual_site_load_kwh`, rounded to
two decimal places. The second is `DOWN_PAYMENT_2_PCT`, which is 0.035, multiplied by a
`fee_cents_per_therm` and by the site's `expected_annual_site_load_kwh` divided by the
contract's `contracted_efficiency_kwh_per_therm`, rounded to two decimal places. The third is
`DOWN_PAYMENT_3_PCT`, which is 0.02, multiplied by the site's
`grid_tariff_rate_cents_per_kwh` and by the site's `expected_annual_site_load_kwh`, rounded to
two decimal places. The down payment is the sum of the three. A term discount of
`TERM_DISCOUNT_CENTS_PER_YEAR`, which is 100 cents per year, is multiplied by the contract's
`term_years` and rounded to two decimal places. A summer percentage is one plus
`SUMMER_HEAT_DELTA` (0.10) plus `SUMMER_HEAT_MAX` (0.35) multiplied by the site's
`grid_outage_events_per_year` and by `SUMMER_HEAT_MULTIPLIER` (0.018); a winter percentage is
one plus `WINTER_HEAT_DELTA` (0.25) plus `WINTER_HEAT_MAX` (0.40) divided by the larger of one
and the site's `grid_outage_events_per_year` multiplied by `WINTER_HEAT_DIVISOR` (2.0). When
the period's month is June, July, August or September the heating percentage is the summer
figure and a grid fee of `SUMMER_GRID_FEE_CENTS`, which is 1,000 cents, is charged, rounded to
two decimal places; for any other month the heating percentage is the winter figure and the
grid fee is zero. A heating charge is the heating percentage multiplied by a heating indicator
and by `HEATING_BASE_CENTS`, which is 100 cents, rounded to two decimal places. A baseline
percentage is one minus the site's `grid_annual_outage_hours` divided by 8,760 and multiplied
by `BASELINE_DEGRADE_PCT` (0.25), floored at zero after the subtraction is taken as a whole
from one. A tax charge is the site's `tax_rate_pct` multiplied by the baseline percentage and
by the contract's `annual_customer_cost_cents`, rounded to two decimal places; an excise charge
is `DEFAULT_EXCISE_RATE` (0.0385) plus the site's `tax_rate_pct`, multiplied by the contract's
`annual_customer_cost_cents`, rounded to two decimal places; the contract's
`annual_customer_cost_cents` is itself its `contracted_annual_kwh` multiplied by its
`effective_tariff_cents_per_kwh`, rounded to two decimal places. An asset-owner cost is the down
payment less the term discount, plus the site's `grid_outage_events_per_year` multiplied by
`FIXED_LINE_CENTS`, rounded to two decimal places; a buyer cost is the down payment plus the tax
charge plus the heating charge plus the grid fee, plus the site's `grid_outage_events_per_year`
multiplied by `OTHER_CENTS`, less the rebate, rounded to two decimal places. The two
outage-scaled line items behave differently below a threshold: while the site's
`grid_outage_events_per_year` is greater than `OUTAGE_FIXED_LINE_THRESHOLD`, which is 3, the
fixed line is `FIXED_LINE_CENTS` multiplied by that count and the other line is `OTHER_CENTS`
multiplied by that count, both rounded to two decimal places; at or below the threshold both
lines are zero; that threshold governs the two reported line items only, because the asset-owner
and buyer costs add the raw count-scaled product whatever the count reads and are therefore
unaffected by it. Three flags are read from the site rather than from the request: an escrow flag
is true when the site's `interconnect_exit_fee_cents_per_kw` is greater than zero, a
contribution flag is true when the contract's `term_years` is at least `CONTRIBUTION_TERM_YEARS`,
which is 15, and a governing-law flag is true when the site's `utility_territory` ends with the
suffix `_CA`. The valuation takes one shape rather than two: the tax charge, the summer grid
fee and the heating charge are assembled the same way whatever basis the contract is held on or
is being transferred onto, so the basis the transfer names does not change the figure. The
escrow and governing-law flags are read from the site and the contribution flag from the
contract's own `term_years`, and both outage-scaled line items are read from the site's outage
count. The valuation object reports its readings under the field names `down_payment_1_cents`,
`down_payment_2_cents`, `down_payment_3_cents`, `down_payment_cents`, `term_discount_cents`,
`summer_pct`, `winter_pct`, `heating_cents`, `grid_fee_cents`, `baseline_pct`, `tax_cents`,
`excise_cents`, `fixed_line_cents`, `other_cents`, `asset_owner_cost_cents`, `buyer_cost_cents`,
`escrow_flag`, `contribution_flag` and `governing_law_flag`.

### 3.9. Portfolio Reconciliations, Availability Measurement and the Token Ledger

The portfolio-level reading the API exposes is the saving attributable to generation, which is
split between the offtakers that share a site. The site's billed energy is the sum of
`metered_kwh` over the site's lines in `SETTLEMENT_APPLIED` — every applied line at the site,
not only the lines of the period being rolled, and reversed lines are excluded because a
reversed line is no longer applied — and it is split in proportion to the site's commitments:
the earliest-created contract among the site's `PPA_DRAFT`, `PPA_ACTIVE` and `PPA_SUSPENDED`
contracts takes the share its `contracted_kw` bears to their total, and the remainder of the
billed energy falls to the other contracts, so a site whose total commitment is zero puts the
whole figure on the first partition. The base saving is the sum of
the two split quantities multiplied by a rate difference in cents per kilowatt-hour, whose
default is `DEFAULT_RATE_DIFFERENCE_CENTS_PER_KWH`, which is 2.2. An adjustment is then keyed
on that base: when the base saving is at least `RATE_CAP_REFERENCE_CENTS`, which is 300,000
cents, the adjustment is `BASE_SAVINGS_REFERENCE_CENTS`, which is 2 cents; otherwise the
adjustment is the base saving divided by `RATE_CAP_REFERENCE_CENTS` and multiplied by
`BASE_SAVINGS_REFERENCE_CENTS`. The customer saving is the base saving plus the adjustment, and
it is then hard-capped: a saving above `MAX_SAVINGS_CAP_CENTS`, which is 1,500,000 cents, is
written down to that cap. Each step reads only the value produced by the step above it and
nothing is fed back, so the sequence is a chain rather than a circular dependency. Ties in the
contract ordering are broken on `created_at` ascending — and, for rows sharing that instant, on
insertion order — never on a per-contract identifier. The commitments are read at the rollover
execution instant rather than at any period boundary, so the split reflects the contracts as
they stand when the rollover runs.

The plant's home-availability measure is a reading the API does not surface: no operation
returns a year availability fraction, a prior-year fraction, an availability ratio, a potential
ratio or an expected annual site output, and no contract or site field carries one. The
constants that would feed it — `AVAILABILITY_HEADROOM_CEILING_PCT`, `AVAILABILITY_FALLBACK_PCT`,
`PR_YEAR_LOAD_FALLBACK_PCT` and `SPECIAL_AGE_FALLBACK_PCT` — are named in the constant table but
reached by no request, so nothing in the system computes or reports the measure, and it must not
be read as a figure the API can be asked for.

No third aggregate is exposed. The API computes a contract's guaranteed period output — its
`contracted_annual_kwh` multiplied by the period's days and divided by 365 — and the shortfall
behind it for the guarantee remedy described in §3.5, but it does not assemble the two
counter-pools that would value that shortfall at the current `effective_tariff_cents_per_kwh`
and line by line, it exposes neither a reconciled pair nor a funded forecast figure, and no
divergence between such pools is detected anywhere.

Corrections are tracked in a token ledger rather than in a mutable balance, and the counters
live on the contract while the customer's figures are derived from them. A `Customer`'s
`earned_customer_tokens` is the sum over that customer's contracts of
`customer_earned_ppa_tokens` plus `customer_earned_output_tokens`, and its
`spent_customer_tokens` is the sum of `customer_spent_ppa_tokens` plus
`customer_spent_output_tokens`. Both totals are derived on the customer from its contracts'
counters, but the API stores and exposes no net figure and applies no floor to the difference,
so those two totals are the only token readings the system reports and the subtraction is left
to the reader. A reversal is what moves the
counters: as §3.4 describes, a reversal advances the contract's earned counter by at least
`EARNED_TOKEN_PER_REVERSAL`, which is 1, and
advances the contract's spent counter by `SPENT_TOKEN_PER_REVERSAL`, which is 2, so two spent
tokens are required to settle a single earned token and the derived net can move
backwards after a correction. The customer's `reconcile_cadence_slots` is a separate derived reading
of the same relationship: it is the count of that customer's contracts in `PPA_ACTIVE` or
`PPA_SUSPENDED` less the count of that customer's accruals sitting in `ACCRUAL_OPEN`, and it
measures how far the customer's reconciliation has lagged the contracts it owes on.

## 4. Endpoint Definitions

Operations that bring a new, standalone resource into existence, or that add a distinct
resource to a collection, answer with `201 Created`; operations that modify an existing
resource, including operations that add data inside an existing resource, answer with `200 OK`.
Reads answer with `200 OK`. Every path below is mounted under the `/power` prefix, and every
request must carry the headers and satisfy the role rules set out in §2.1. Where a path nests
one identifier inside another, the identifier on the left is validated before the one on the
right, so a request naming a site that does not exist is refused with `ERR_SITE_NOT_FOUND`
before the server ever considers the resource nested under it. The table records only the
method, the path, a short description and the roles the operation admits; the request payloads,
the computed side effects and the state transitions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/power/sites` | Register a customer facility for on-site fuel cell evaluation | `SiteOperator` |
| GET | `/power/sites` | List sites | `SiteOperator`, `CustomerService`, `SettlementAnalyst`, `SettlementApprover`, `FuelCoordinator` |
| GET | `/power/sites/{id}` | Get a site | `SiteOperator`, `CustomerService`, `SettlementAnalyst`, `SettlementApprover`, `FuelCoordinator` |
| GET | `/power/sites/{id}/ppas` | List the PPAs hosted at a site | `SiteOperator`, `CustomerService`, `SettlementAnalyst`, `SettlementApprover` |
| POST | `/power/sites/{id}/evaluate` | Evaluate load, gas availability, footprint, interconnection and avoided feed-in tariff | `SiteOperator` |
| POST | `/power/sites/{id}/freeze` | Suspend site operations; cascades to PPAs, service plans and customers | `SiteOperator` |
| POST | `/power/sites/{id}/unfreeze` | Resume site operations; restores PPAs and service plans | `SiteOperator` |
| POST | `/power/sites/{id}/transfer-ppa` | Transfer a service contract to a new owner; returns the transfer valuation | `SiteOperator` |
| POST | `/power/customers` | Create a customer offtaker | `CustomerService` |
| GET | `/power/customers` | List customers | `CustomerService`, `SiteOperator`, `SettlementAnalyst` |
| GET | `/power/customers/{id}` | Get a customer | `CustomerService`, `SiteOperator`, `SettlementAnalyst` |
| GET | `/power/customers/{id}/ppas` | List the PPAs held by a customer | `CustomerService`, `SettlementAnalyst`, `SettlementApprover`, `Customer` |
| GET | `/power/customers/{id}/fuel-deliveries` | List the deliveries a customer attested under its own-procurement option | `CustomerService`, `FuelCoordinator` |
| POST | `/power/customers/{id}/apply-exposure-hold` | Arm the credit exposure hold | `CustomerService` |
| POST | `/power/customers/{id}/release-exposure-hold` | Release the credit exposure hold | `CustomerService` |
| POST | `/power/customers/{id}/offer-renewal` | Offer a renewal to the customer | `CustomerService` |
| POST | `/power/customers/{id}/accept-renewal` | Accept the renewal offer | `CustomerService` |
| POST | `/power/customers/{id}/decline-renewal` | Decline the renewal offer | `CustomerService` |
| POST | `/power/ppas` | Draft a power purchase agreement | `SiteOperator` |
| GET | `/power/ppas` | List PPAs | `SiteOperator`, `CustomerService`, `SettlementAnalyst`, `SettlementApprover` |
| GET | `/power/ppas/{id}` | Get a PPA | `SiteOperator`, `CustomerService`, `SettlementAnalyst`, `SettlementApprover`, `Customer` |
| GET | `/power/ppas/{id}/transfers` | List the PPAs transferred from this contract | `SiteOperator`, `CustomerService` |
| POST | `/power/ppas/{id}/activate` | Activate the contract; cascades into service plan creation | `SiteOperator` |
| POST | `/power/ppas/{id}/request-exit` | Request exit; opens the cure window | `SiteOperator` |
| POST | `/power/ppas/{id}/cure` | Cure the exit request inside the cure window; reverts to active | `SiteOperator` |
| POST | `/power/ppas/{id}/terminate` | Terminate the contract after the cure window lapses | `SiteOperator` |
| POST | `/power/ppas/{id}/renew` | Renew a terminated contract | `SiteOperator` |
| POST | `/power/ppas/{id}/adjust-contract` | Adjust contract terms after activation | `SiteOperator` |
| POST | `/power/ppas/{id}/service-plans` | Create a service plan with monitoring, replacement scope and a maintenance window | `ServiceEngineer` |
| GET | `/power/ppas/{id}/service-plans` | List service plans for a PPA | `ServiceEngineer`, `SiteOperator`, `SettlementAnalyst` |
| GET | `/power/ppas/{id}/service-plans/{id}` | Get a service plan | `ServiceEngineer`, `SiteOperator` |
| POST | `/power/ppas/{id}/service-plans/{id}/schedule-replacement` | Schedule a module replacement | `ServiceEngineer` |
| POST | `/power/ppas/{id}/service-plans/{id}/dispatch-module-replacement` | Dispatch the scheduled module replacement | `ServiceEngineer` |
| POST | `/power/sites/{id}/fuel-deliveries` | Schedule a fuel delivery or the operator's initial fuel inventory | `FuelCoordinator` |
| GET | `/power/sites/{id}/fuel-deliveries` | List fuel deliveries for a site | `FuelCoordinator`, `SiteOperator`, `SettlementAnalyst` |
| GET | `/power/sites/{id}/fuel-deliveries/{id}` | Get a fuel delivery | `FuelCoordinator`, `SiteOperator` |
| POST | `/power/sites/{id}/fuel-deliveries/{id}/dispatch` | Dispatch a scheduled delivery into custody | `FuelCoordinator` |
| POST | `/power/sites/{id}/fuel-deliveries/{id}/confirm` | Confirm custody; cascades into accruals and reserves | `FuelCoordinator` |
| POST | `/power/sites/{id}/fuel-deliveries/{id}/cancel` | Cancel a delivery before confirmation | `FuelCoordinator` |
| POST | `/power/sites/{id}/resource-holds` | Consume the site's allocatable fuel pool into an in-service hold | `SiteOperator` |
| POST | `/power/sites/{id}/release-resource-hold` | Release an in-service resource hold back to the pool | `SiteOperator` |
| POST | `/power/ppas/{id}/settlement-lines` | Create a settlement period line | `SettlementAnalyst` |
| GET | `/power/ppas/{id}/settlement-lines` | List settlement lines for a PPA | `SettlementAnalyst`, `SettlementApprover`, `SiteOperator` |
| GET | `/power/ppas/{id}/settlement-lines/{id}` | Get a settlement line | `SettlementAnalyst`, `SettlementApprover` |
| POST | `/power/ppas/{id}/settlement-lines/{id}/validate` | Validate a draft settlement line | `SettlementAnalyst` |
| POST | `/power/ppas/{id}/settlement-lines/{id}/approve` | Approve a validated line and compute guarantee remedies | `SettlementApprover` |
| POST | `/power/ppas/{id}/settlement-lines/{id}/settle` | Apply a line and reconcile the accrual ledger | `SettlementApprover` |
| POST | `/power/ppas/{id}/settlement-lines/{id}/reverse` | Reverse an applied line within the reversal window | `SettlementApprover` |
| POST | `/power/ppa-accruals` | Post an accrual to a contract's ledger | `SettlementAnalyst` |
| GET | `/power/ppa-accruals` | List accruals, optionally filtered by contract | `SettlementAnalyst`, `SettlementApprover`, `SiteOperator` |
| GET | `/power/ppa-accruals/{id}` | Get an accrual | `SettlementAnalyst`, `SettlementApprover` |
| GET | `/power/ppa-accruals/{id}/applied-allowances` | List the allowances applied to an accrual | `SettlementAnalyst`, `SettlementApprover` |
| POST | `/power/ppas/{id}/reconcile-accruals` | Reconcile the earliest stale accrual of a contract | `SettlementAnalyst` |
| GET | `/power/ppas/{id}/fuel-deliveries` | List the fuel deliveries allocated to a contract | `FuelCoordinator`, `SettlementAnalyst` |
| POST | `/power/ppas/{id}/allowances` | Issue a settlement allowance against a contract | `SettlementAnalyst` |
| GET | `/power/ppas/{id}/allowances` | List allowances for a PPA | `SettlementAnalyst`, `SettlementApprover` |
| GET | `/power/ppas/{id}/allowances/{id}` | Get a settlement allowance | `SettlementAnalyst`, `SettlementApprover` |
| POST | `/power/ppas/{id}/allowances/{id}/apply` | Apply an issued allowance to the contract ledger | `SettlementAnalyst` |
| GET | `/power/ppa-transitions` | List contract transition records | `SiteOperator`, `CustomerService`, `SettlementAnalyst` |
| GET | `/power/ppa-transitions/{id}` | Get a contract transition record | `SiteOperator`, `SettlementAnalyst` |
| GET | `/power/ppas/{id}/transitions` | List transition records for a PPA | `SiteOperator`, `SettlementAnalyst` |
| POST | `/power/_ops/recompute-index-bases` | Batch recompute of escalated rates, index bases and guarantee reserves | `SiteOperator` |
| POST | `/power/_ops/rollover-period` | Batch settle eligible lines in the rollover period | `SiteOperator` |
| POST | `/power/_clock/set_current_utc` | Set the logical clock | `SiteOperator` |

## 5. Error Code Catalogue

The table below lists every error identifier the API can return and the HTTP status that
accompanies it. The conditions that trigger each identifier are not repeated here; they are
stated where the rule lives, in §2 and §3. Three framework-level refusals sit outside the
table's one-to-one reading of identifier against status: a request aimed at a path the API does
not route at all is answered with `ERR_REFERENCE_NOT_FOUND` at HTTP 404, a request that names a
routed path but a method that path does not admit is answered with `ERR_INVALID_REQUEST` at
HTTP 405 rather than at 400, and a request that fails unexpectedly is answered with
`ERR_INVALID_REQUEST` at HTTP 500. Those three carry the identifier's usual envelope but not the
identifier's usual status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_PPA_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TERM_COMMITMENT_INVALID` | 422 Unprocessable Entity |
| `ERR_EFFICIENCY_INVALID` | 422 Unprocessable Entity |
| `ERR_ESCALATOR_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_FUEL_SOURCING_MODE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SITE_FROZEN` | 409 Conflict |
| `ERR_RENEWAL_STAGE_INVALID` | 409 Conflict |
| `ERR_REVERSAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_TRANSFER_BLOCKED` | 409 Conflict |
| `ERR_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_FOOTPRINT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CONFIRM_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_SITE_DEMAND_LIMIT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_DRAW_POSITION` | 422 Unprocessable Entity |
| `ERR_DRAW_POSITION_BELOW_RESUME` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SOURCING_UNVERIFIED` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_BEFORE_ACTIVATION` | 422 Unprocessable Entity |
| `ERR_EXIT_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_LIMIT` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_ACCRUAL` | 422 Unprocessable Entity |
| `ERR_CREDIT_TIER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_GUARANTEE_FLOOR_BREACH` | 422 Unprocessable Entity |
| `ERR_BUMPER_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ACCRUAL_UNBALANCED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
