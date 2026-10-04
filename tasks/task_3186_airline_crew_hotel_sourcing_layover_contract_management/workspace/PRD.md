# Airline Crew Hotel Sourcing API — Product Requirements Document

## 1. Introduction

When a wide-body flight diverts to a hub at 02:00 local time, the crew does not have a morning shift to sleep off — they have a federally and contractually regulated rest period that begins the moment the aircraft door closes. Getting that crew into compliant hotel rooms, moving them between the airport and the property on a schedule that preserves every minute of legal rest, and paying the hotel exactly what was negotiated is an operational problem that spans procurement, crew scheduling, ground transportation, quality assurance, and accounts payable at once.

This document specifies the Airline Crew Hotel Sourcing API, the system of record for that workflow. The platform manages stations and the layover requirements that arise at them, runs request-for-proposal cycles through which hotel vendors bid room blocks and nightly rates, negotiates and awards contracts, enforces the union agreement provisions that govern minimum rest, quiet rooms, blackout protections, and acceptable room standards, coordinates ground transportation pickups tied to crew schedules, sources distressed rooms when irregular operations outgrow the contracted block, collects crew feedback and audits of hotel conditions, and reconciles vendor invoices against actual room usage before any payment is released.

The system is deliberately opinionated about ordering: a rest-safety floor is evaluated before any capacity check, a stale read of a negotiation in flight is rejected rather than silently overwriting a counter-offer, and a critical audit finding does not wait for a human to suspend a contract before it releases that contract's outstanding room holds. Readers implementing against this document should treat §2 as the structural contract, §3 as the complete behavioral specification scattered across the business narrative, and §§4–5 as lookup tables only.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The declared roles are exactly `PlatformAdmin`, `SourcingManager`, `CrewOps`, `FinanceAnalyst`, `CrewAuditor`, and `HotelVendorRep`. A request whose `X-User-Role` header is missing, or whose value is not one of these declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); this same rejection covers entity-backed ownership failures, such as a `HotelVendorRep` attempting to withdraw a proposal that belongs to another vendor.

The `X-User-ID` header is interpreted per role. When `X-User-Role` is `HotelVendorRep`, `X-User-ID` is the `id` of the acting `HotelVendor`; ownership checks on any resource that references a `HotelVendor` — for example a proposal's `vendor_id` at withdrawal time — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is any of `PlatformAdmin`, `SourcingManager`, `CrewOps`, `FinanceAnalyst`, or `CrewAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `auditor_id` on an `Audit` where the auditor opening the record supplies it) but does not compare it to any entity's `id`.

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

List endpoints are paged through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-sensitive behavior in the system — deadline enforcement, lazy state settlement, check-in eligibility, no-show eligibility, missed-pickup detection, and audit remediation deadlines — is evaluated against a logical clock, never the wall clock. The logical clock starts at exactly 2026-09-01T00:00:00Z at server startup and advances only when a `PlatformAdmin` sets it to a supplied `to_iso8601` instant through the clock-driving capability; the response of that operation reports the new `current_utc`. Setting the clock lazily settles any contract whose `end_date` has been passed to `EXPIRED`, and any trip whose `pickup_time` has been passed while still `SCHEDULED` to `MISSED`, on the next read or write that touches the record.

### 2.5. Stations, Rest Floors, and the Transport Tax

A **Station** is the geographic anchor of the whole workflow. It is created by a `PlatformAdmin` with a `code` (an uppercase three-letter IATA code, unique across all stations), a human-readable `name`, an IANA `timezone`, a `min_rest_hours` (an integer between 1 and 24 inclusive, the minimum crew rest hours behind the hotel door the station commits to), a `transport_time_minutes` (an integer between 5 and 180 inclusive, the one-way airport-to-hotel ground transport time used in both rest and pickup math), and a `room_availability_commitment` (an integer of at least 0, the rooms the station commits to source per layover night).

Rest is a two-legged problem: the crew rides to the hotel and back, so every layover is taxed by two transport legs when the system evaluates whether the scheduled rest is adequate. The rest floor that applies to a given layover is the stricter of the station's `min_rest_hours` and the minimum rest hours in the union agreement governing the layover's crew population — the system never accepts the looser of the two.

### 2.6. Union Agreements as Compliance Law

A **Union Agreement** is reference data created by a `PlatformAdmin`, named (for example, "APA-2026") via its `name`, scoped to a `crew_type` of either `PILOT` or `FLIGHT_ATTENDANT`, and carrying the contract provisions the system must enforce: `min_rest_hours` (an integer between 8 and 24 inclusive), `quiet_room_required` (a boolean), `min_room_standard` (one of `STANDARD`, `PREMIUM`, or `SUITE`), `blackout_protection_required` (a boolean), and `max_invoice_variance_pct` (a number strictly greater than 0 and at most 100, the largest absolute percent variance between billed and reconciled invoice totals at which invoice approval remains possible).

Union provisions bind at two distinct points in the lifecycle. At award and at contract activation, the quiet-room, blackout-protection, and room-standard provisions gate whether the contract may come into force at all. At invoice approval, the variance provision gates whether finance may approve a reconciled bill. Both gates reject with `ERR_UNION_STANDARD_VIOLATION` and `ERR_INVOICE_VARIANCE_EXCEEDED` respectively when breached.

### 2.7. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` is a system-managed integer that increments by exactly 1 on every mutation, and it is the field that optimistic concurrency control reads.

There is one deliberate exception: **Crew Feedback** records are append-only operational testimony and carry only `id` and `created_at`. A feedback row has no `updated_at` and no `version`; it is never mutated after filing.

### 2.8. Money, Rounding, and Precision

All monetary values in the system are integer cents. Where a calculation produces a fractional cent — the contract value, a distressed-surge charge, a per-line reconciliation amount, or a late-cancel penalty — the value is rounded half-up to whole cents at the points named by the corresponding business rule in §3. Percentages (the invoice variance) are rounded half-up to exactly 2 decimal places. Comparison boundaries are inclusive where §3 states them with "at least" or "no more than" phrasing; a value sitting exactly on a threshold passes the check.

### 2.9. Optimistic Concurrency Control

Two write endpoints carry mandatory optimistic concurrency checks, and only those two. Awarding an RFP cycle requires the request to carry `expected_cycle_version` holding the `version` of the cycle the client last observed; if another writer has advanced the cycle's version since that read — for example by a counter-offer or an open-negotiation call that rewrote proposal rates — the award is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from awarding a negotiation state it has not observed. Booking a layover against a contract requires the request to carry `expected_layover_version` holding the layover's last observed `version`; a mismatch with the layover's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.10. Validation Order and Identifier Resolution

Every request passes through a fixed gauntlet of checks, evaluated in this order: authentication first (missing or undeclared role header, `ERR_UNAUTHENTICATED`), then authorization (role not permitted for the endpoint, or an entity-backed ownership check failure such as a vendor representative withdrawing another vendor's proposal, `ERR_FORBIDDEN`), then existence (every identifier in the path and every foreign-key identifier in the body resolves to an existing entity, validated left-to-right, `ERR_NOT_FOUND`), then state-machine legality (the requested transition exists from the target resource's current state, `ERR_INVALID_STATE`), then the business and safety rules attached to the specific endpoint in the priority order §3 narrates, and finally request shape (required fields present, enum values valid, datetime ranges ordered with the end after the start, `ERR_INVALID_REQUEST`). Nested resources resolve strictly left-to-right: a request to a child under a non-existent parent reports the missing parent before the child is ever looked up.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Sourcing Board: Stations, Agreements, and Vendors

Before any hotel room can be sourced, a `PlatformAdmin` establishes the reference frame. Stations are registered as described in §2.5. Union agreements are registered as described in §2.6, one per crew population they govern; when the system needs "the union agreement for this layover's crew", it means the agreement whose `crew_type` equals the layover's `crew_type`. Hotel vendors are registered with a `name`, a `contact_email`, a `security_certified` boolean recording whether the vendor holds the airline's security certification, and a `quiet_rooms_count` (an integer of at least 0, the count of quiet-standard rooms the vendor operates). A freshly registered vendor enters the system with `status` set to `ACTIVE`; its lifecycle thereafter spans `ACTIVE`, `SUSPENDED`, and `BLACKLISTED`, and only an `ACTIVE` vendor may take part in new business.

The vendor list supports a `status?` filter so a sourcing lead can review only the `SUSPENDED` population, and the union agreement list supports a `crew_type?` filter.

### 3.2. Running an RFP Cycle: From Draft to Award

A `SourcingManager` opens a sourcing effort by creating an **RFP cycle** against a station: the payload names the `station_id`, a `title`, a `response_deadline` (an ISO 8601 UTC instant after which proposals are rejected), a `target_room_count` of at least 1 (the rooms the cycle aims to contract), and a `budget_cap_cents` (a positive integer, the maximum total contract value allowed at award). A new cycle is born in `DRAFT`.

Opening the cycle moves it `DRAFT → OPEN`; this is allowed only while the cycle's `response_deadline` is still in the future relative to the logical clock. Closing the cycle moves it `OPEN → EVALUATION` and, as a cascade, transitions every proposal of the cycle still sitting in `SUBMITTED` to `UNDER_REVIEW`, bumping each such proposal's `version`. The cycle's own `version` increments on every one of these transitions.

Negotiation is a loop, not a line. From `EVALUATION`, the manager may open negotiation — but only if at least one proposal of the cycle is `SHORTLISTED` — moving the cycle `EVALUATION → NEGOTIATION` and incrementing the cycle's `negotiation_round` by 1 (the round counter starts at 0). The same open-negotiation action, invoked while the cycle is already in `NEGOTIATION`, returns it `NEGOTIATION → EVALUATION` when no counter-offer advances the round; the return direction does not increment `negotiation_round`. The cycle may thus oscillate between `EVALUATION` and `NEGOTIATION` any number of times, with `negotiation_round` faithfully counting only the forward entries into negotiation.

During negotiation, the manager rewrites a shortlisted proposal's economics with a counter-offer carrying a `new_rate_cents`; the proposal's `current_rate_cents` is set to that value and its `version` increments. A counter-offer is legal only when the proposal is `SHORTLISTED` and its parent cycle is in `NEGOTIATION`; any other combination is rejected with `ERR_NOT_NEGOTIABLE` (HTTP 409). Each proposal remembers both rates: the `offered_rate_cents` the vendor originally submitted, and the `current_rate_cents` in effect after counter-offers, which is what an eventual award will write into the contract.

Awarding is the heaviest single operation in the system. From `NEGOTIATION`, the manager awards the cycle by naming a `proposal_id` that references a proposal of this cycle whose status is `SHORTLISTED`, and supplying the contract terms: `room_block_size` (at least 1), `start_date`, `end_date` (which must fall after `start_date`), `late_cancel_hours` (at least 0), a `quiet_room_standard` of `BASIC`, `ENHANCED`, or `PREMIUM`, a `security_requirements` array of security clause identifiers (defaulting to an empty array), a `blackout_dates` array of ISO 8601 dates in `YYYY-MM-DD` form on which the negotiated rate does not apply (defaulting to empty), and a `blackout_protection` boolean (defaulting to false) declaring whether rooms must still be honored on blackout dates. Because negotiation may have legitimately moved the cycle since the client last read it, the award must carry `expected_cycle_version` per §2.9, and a stale value is rejected with `ERR_STALE_VERSION`.

Two fiscal and compliance gates guard the award, in this order relative to the cycle-state check. First, union compliance: for the union agreement of the station's crew, if the agreement's `quiet_room_required` is true then the contract's `quiet_room_standard` must not be `BASIC`; if its `blackout_protection_required` is true then the contract's `blackout_protection` must be true; and the room-standard ladder must hold — `min_room_standard` of `STANDARD` accepts any of `BASIC`, `ENHANCED`, or `PREMIUM`, `PREMIUM` accepts only `ENHANCED` or `PREMIUM`, and `SUITE` accepts only `PREMIUM`. A breach is rejected with `ERR_UNION_STANDARD_VIOLATION` (HTTP 422). Second, the budget gate: the preliminary contract value — the proposal's `current_rate_cents` multiplied by the award's `room_block_size` multiplied by the number of whole nights between `start_date` and `end_date` (partial days discarded), the integer product rounded half-up to whole cents once at the end — must be no more than the cycle's `budget_cap_cents`, or the award is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422).

A successful award creates a **Contract** in `DRAFT` with the `rfp_cycle_id`, `proposal_id`, `vendor_id`, and `station_id` copied from the cycle and the accepted proposal, the `negotiated_rate_cents` taken from the proposal's `current_rate_cents`, and the award's terms stamped onto it. The awarded proposal moves `SHORTLISTED → ACCEPTED`; every other proposal of the cycle still in `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED` moves to `REJECTED`; the cycle itself moves `NEGOTIATION → AWARDED`; and all affected resources bump their `version`. The contract's `total_contract_value_cents` is computed at creation with exactly the same formula as the award's budget gate — rate times block times whole nights, rounded half-up once at the end — and this stored figure is the system of record for downstream budget reporting.

Cancellation is the escape hatch: from any non-terminal cycle state (`DRAFT`, `OPEN`, `EVALUATION`, or `NEGOTIATION`), cancelling the cycle moves it to `CANCELLED` and cascades every proposal still in `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED` to `REJECTED`. Both `AWARDED` and `CANCELLED` are terminal.

### 3.3. Vendor Participation: Proposals, Deadlines, and Withdrawal

A `HotelVendorRep` participates by submitting a proposal to an `OPEN` cycle. The submission payload carries the `vendor_id`, an `offered_room_count` of at least 1, an `offered_rate_cents` of at least 0 (the offered nightly room rate), a `quiet_room_commitment` of at least 0 (quiet rooms the vendor commits), and an optional `blackout_dates` array of ISO 8601 `YYYY-MM-DD` dates the vendor excludes from the rate, defaulting to empty. The proposal is created in `SUBMITTED` with `current_rate_cents` initialized to the `offered_rate_cents` and the `rfp_cycle_id` recorded from the cycle it answers. Timing is enforced at submission: if the logical clock has already passed the cycle's `response_deadline`, the submission is rejected with `ERR_DEADLINE_PASSED` (HTTP 422).

From `UNDER_REVIEW`, the manager may shortlist the proposal (`UNDER_REVIEW → SHORTLISTED`, legal only while the parent cycle is in `EVALUATION`) or reject it (`UNDER_REVIEW → REJECTED`); a proposal in `SHORTLISTED` may also be rejected directly. The vendor representative who owns the proposal — the `X-User-ID` matching the proposal's `vendor_id` — may withdraw it from any of `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED`, moving it to `WITHDRAWN`; a representative acting for a different vendor is refused with `ERR_FORBIDDEN`. `REJECTED`, `ACCEPTED`, and `WITHDRAWN` are all terminal. The proposal list supports reverse lookups by `rfp_cycle_id?`, `vendor_id?`, and `status?`.

### 3.4. Bringing a Contract to Life — and Suspending or Ending It

A contract fresh from award sits in `DRAFT`. Activation moves it `DRAFT → ACTIVE` and re-runs the union compliance gate described in §3.2 — quiet-room, blackout-protection, and room-standard ladder — plus a vendor gate: the contract's vendor must currently be `ACTIVE`, not `SUSPENDED` or `BLACKLISTED`, or activation is refused with `ERR_VENDOR_INACTIVE` (HTTP 422). The contract's `start_date` must also fall on or before its `end_date`. Activation carries no payload beyond the path.

Two forces can move a contract out of `ACTIVE`. The first is time: the system evaluates expiry lazily, so any read or write touching a contract whose `end_date` the logical clock has passed settles it to `EXPIRED` before answering. The second is quality enforcement, covered in §3.8.

Termination from `ACTIVE` is evidence-gated: the manager may terminate only when the contract has accumulated at least 3 crew feedback rows with a `rating` of 2 or lower — the three-strike rule — and an attempt short of that count is refused with `ERR_TERMINATION_THRESHOLD` (HTTP 422). Termination from `SUSPENDED` carries no such threshold. Either way, termination cascades: every room allocation of the contract in `HELD` or `CONFIRMED` moves to `CANCELLED`; every layover requirement at the contract's station in `CONFIRMED` whose allocation was cancelled moves to `SURGED`; and the contract's vendor is moved to `SUSPENDED`. Both `TERMINATED` and `EXPIRED` are terminal. The contract list supports `station_id?`, `vendor_id?`, `status?`, `rfp_cycle_id?`, and `proposal_id?` filters.

### 3.5. Planning a Layover and the Rest-Compliance Gate

Crew operations registers a **layover requirement** for a station with the `station_id`, a `crew_type` of `PILOT` or `FLIGHT_ATTENDANT`, a `crew_count` of at least 1 (one room per crew member), the scheduled `arrival_time` and `departure_time` (UTC, departure strictly after arrival), the `required_rest_hours` (at least 1) the schedule was built to provide, and an optional `is_irregular_ops` flag (defaulting to false) marking layovers arising from irregular operations. A new requirement is born `PLANNED`.

At creation — and on every later change to `arrival_time`, `departure_time`, `required_rest_hours`, or `crew_type` — the system computes the layover's `rest_compliant` flag. The layover's span in hours is the whole-hour count between `arrival_time` and `departure_time`, fractional hours discarded. From that span the system subtracts the transport tax: two legs of the station's `transport_time_minutes`, converted to hours. The result is the effective rest the schedule actually delivers behind the hotel door. The layover is rest-compliant when this effective rest is at least — equal counts as compliant — the stricter of the station's `min_rest_hours` and the `min_rest_hours` of the union agreement matching the layover's `crew_type`. For irregular-operations layovers (`is_irregular_ops` true), the `arrival_time` used in this computation is replaced by the current logical clock time whenever the given `arrival_time` lies in the past, reflecting actual wheels-down rather than the original schedule.

### 3.6. Booking Rooms Against a Contract

Booking moves a layover `PLANNED → CONFIRMED` and simultaneously creates a **room allocation** of kind `CONTRACTED` in `HELD`. The booking payload names the `contract_id` and the `stay_date` (the UTC calendar date of the room night), may carry a `blackout_rate_cents` override, and must carry `expected_layover_version` per §2.9 — a stale layover version is rejected with `ERR_STALE_VERSION` before anything else business-side is evaluated. Every allocation carries a `kind` of either `CONTRACTED` (booked against a contract) or `DISTRESSED` (sourced during a surge).

The booking gauntlet then runs, in this order. Rest safety first: `rest_compliant` must currently be true, or the booking is rejected with `ERR_REST_VIOLATION` (HTTP 422) — the rest floor is a safety rule and is evaluated before any capacity check. Blackout handling next: the `stay_date` must not fall in the contract's `blackout_dates` unless the contract's `blackout_protection` is true; a blackout-date booking without protection is rejected with `ERR_BLACKOUT_DATE` (HTTP 422). When protection is in force and the date is blacked out, `blackout_rate_cents` is required and must be at least 0; the honored room night is then priced at that override rather than the negotiated rate. Then the single-occupancy guard: no other allocation for this layover may exist in `HELD` or `CONFIRMED` — the layover resource is occupied at most once — or the booking fails with `ERR_LAYOVER_ALREADY_BOOKED` (HTTP 409). Finally the aggregate occupancy guard: the count of this contract's allocations already in `CONFIRMED` with the same `stay_date` must be strictly less than the contract's `room_block_size`; a block filled to exactly `room_block_size` rejects the next booking with `ERR_ROOM_BLOCK_EXHAUSTED` (HTTP 422).

The named contract must be `ACTIVE` and its `station_id` must equal the layover's `station_id`. On success the allocation records the layover via `layover_requirement_id`, copies the `contract_id`, sets `rooms_held` to the layover's `crew_count`, and prices `nightly_rate_cents` at the contract's `negotiated_rate_cents` — or at the booking's `blackout_rate_cents` when the stay date is blacked out and protected. The `vendor_id` on a `CONTRACTED` allocation is null. The layover's `version` increments.

An allocation held this way is not yet a firm booking. Confirming the allocation moves it `HELD → CONFIRMED`, which requires the allocation still be `HELD` and its layover be `CONFIRMED`. The vendor's representative checks the crew in on the stay date or after — check-in moves the allocation `CONFIRMED → CHECKED_IN`, requires that the allocation's `stay_date` be on or before the logical clock date (a crew cannot check in before the stay date), and cascades the layover `CONFIRMED → COMPLETED`. If the crew never arrives, crew operations marks the allocation `CONFIRMED → NO_SHOW`, legal only once the logical clock date is strictly after the `stay_date`. Crew operations may also release a still-`HELD` allocation (`HELD → RELEASED`); if the allocation's layover is `CONFIRMED`, that release cascades the layover `CONFIRMED → SURGED`, because its housing has evaporated. `RELEASED`, `CANCELLED`, `NO_SHOW`, and `CHECKED_IN` are terminal allocation states. The allocation list supports `layover_requirement_id?`, `contract_id?`, `vendor_id?`, `status?`, `kind?`, and `stay_date?` filters.

### 3.7. Irregular Operations and Distressed Sourcing

A layover in `SURGED` — whether it got there by release or by the contract cascades of §3.8 — needs rooms beyond the contracted block. Crew operations re-houses it with a distressed booking that names a `vendor_id` (which must reference a vendor currently `ACTIVE`, or the request is refused with `ERR_VENDOR_INACTIVE`) and a `rate_cents`. The layover moves `SURGED → CONFIRMED` and a new allocation is created of kind `DISTRESSED` in `HELD`, with `vendor_id` recorded, `contract_id` null, `rooms_held` equal to the layover's `crew_count`, and `nightly_rate_cents` set from the supplied `rate_cents`.

Distressed rooms are priced with a surge multiplier at the moment the allocation is confirmed. The system counts the pre-existing `DISTRESSED` allocations with the same `stay_date` in `HELD`, `CONFIRMED`, or `CHECKED_IN`: when that count is no more than 5 the multiplier is 1.25; when it is more than 5 but no more than 10 the multiplier is 1.50; beyond 10 the multiplier is 2.00. The allocation's `distressed_cost_cents` is then the `nightly_rate_cents` multiplied by `rooms_held` multiplied by the applicable multiplier, the final product rounded half-up to whole cents. For `CONTRACTED` allocations `distressed_cost_cents` stays null.

Cancelling a layover is permitted from `PLANNED`, `CONFIRMED`, or `SURGED` and moves the layover to `CANCELLED`. The cancel cascades: if the layover has an allocation in `HELD` or `CONFIRMED`, that allocation moves to `CANCELLED`; and every transport trip of the layover still `SCHEDULED` moves to `CANCELLED`. For a `CONTRACTED` allocation the cancellation is late — and therefore chargeable on the eventual invoice — exactly when the allocation's `stay_date` minus the contract's `late_cancel_hours` still lies in the future relative to the logical clock; cancelling earlier than that window is free. A `DISTRESSED` allocation is always chargeable on cancellation, whenever it happens.

### 3.8. Quality Enforcement: Feedback, Audits, and the Suspension Cascade

After a layover, crew operations files a **crew feedback** row against the contract that housed it, naming the `contract_id`, the `layover_requirement_id` at which the conditions were experienced, the reporting `crew_type` (`PILOT` or `FLIGHT_ATTENDANT`), a `rating` from 1 (worst) to 5 (best), a primary complaint `category` of `NOISE`, `SECURITY`, `CLEANLINESS`, `TRANSPORT`, or `OTHER`, and an optional free-text `comment` defaulting to empty. Feedback rows are immutable once filed. The feedback list supports `contract_id?`, `layover_requirement_id?`, and `rating?` filters. Three or more rows rated 2 or lower arm the three-strike termination gate of §3.4.

Independent of feedback, a `CrewAuditor` may open an **audit** against a contract, supplying the `contract_id`, an `auditor_id` (the auditor's own opaque identifier), a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a `findings` narrative. The audit is created in `OPEN` with `opened_at` stamped from the logical clock. Opening a `CRITICAL` audit against an `ACTIVE` contract immediately suspends the contract (`ACTIVE → SUSPENDED`) and fires the full suspension cascade: the contract's `remediation_deadline` is set to the logical clock plus 168 hours — one week; every allocation of the contract in `HELD` moves to `RELEASED`; every transport trip referencing the contract in `SCHEDULED` moves to `CANCELLED`; and every layover at the contract's station in `CONFIRMED` whose held allocation was just released moves to `SURGED`. Lesser severities leave the contract untouched.

The auditor then works the audit `OPEN → IN_PROGRESS` and closes it `IN_PROGRESS → CLOSED_PASS` or `IN_PROGRESS → CLOSED_FAIL` according to the supplied `outcome` of `PASS` or `FAIL`. Closing with a fail outcome terminates the contract outright, regardless of whether it stood `ACTIVE` or `SUSPENDED`, and fires the full termination cascade of §3.4 — allocations cancelled, their layovers surged, vendor suspended.

A suspended contract can recover: remediation moves it `SUSPENDED → ACTIVE`, but only when no audit against the contract remains in `OPEN` or `IN_PROGRESS` with severity `CRITICAL`; success clears the `remediation_deadline` back to null. The audit list supports `contract_id?`, `status?`, and `severity?` filters.

### 3.9. Ground Transportation

Once a layover is `CONFIRMED`, crew operations schedules its **transport trips**, one per direction, with a `direction` of `AIRPORT_TO_HOTEL` or `HOTEL_TO_AIRPORT` and a `vehicle_capacity` of at least 1. Scheduling computes the trip's `pickup_time` from the layover and its station. For `AIRPORT_TO_HOTEL`, pickup is the layover's `arrival_time` plus the station's `transport_time_minutes` — the van meets the crew off the aircraft. For `HOTEL_TO_AIRPORT`, pickup is the layover's `departure_time` minus the station's `transport_time_minutes` and minus a further 90-minute buffer, so the crew is at the airport with time to spare; times are minute-precise with no rounding. For irregular-operations layovers, the computed pickup is additionally pushed forward to the later of itself and the logical clock plus 30 minutes, so a trip is never scheduled in the past. The trip is created in `SCHEDULED`, and its `contract_id` is copied from the layover's `CONFIRMED` contracted allocation at schedule time.

Pickup uniqueness is enforced per layover and direction: the computed `pickup_time` must not equal the pickup time of any existing non-`CANCELLED` trip of the same layover in the same direction, or scheduling fails with `ERR_PICKUP_CONFLICT` (HTTP 409).

A scheduled trip is dispatched (`SCHEDULED → DISPATCHED`, requiring the trip's layover to be `CONFIRMED`) and then completed (`DISPATCHED → COMPLETED`). A trip still `SCHEDULED` when the logical clock passes its `pickup_time` settles lazily to `MISSED` on the next read or write that touches it. Trips may also be cancelled en masse by the layover-cancel and contract-suspension cascades. `COMPLETED`, `CANCELLED`, and `MISSED` are terminal. The trip list supports `layover_requirement_id?`, `contract_id?`, `status?`, and `direction?` filters.

### 3.10. Invoice Reconciliation and the Fiscal Gate

The vendor's representative bills the airline by submitting an **invoice** against a contract, supplying the `contract_id`, a `billing_period_start` and `billing_period_end` (UTC, the end on or after the start), the `billed_room_nights` (at least 0) and `billed_amount_cents` (at least 0) the vendor claims. An invoice is born `RECEIVED`; finance may reject it outright (`RECEIVED → REJECTED`) or run reconciliation.

Reconciliation moves the invoice `RECEIVED → RECONCILED` and computes the airline's own view of the bill. The eligible set is the contract's allocations in `CHECKED_IN` whose `stay_date` falls within the billing period, both endpoints inclusive; the `reconciled_room_nights` is the sum of `rooms_held` across that set. Separately, the system collects the contract's allocations in `CANCELLED` within the period whose cancellation was late under the §3.7 late-cancel rule. Each eligible allocation contributes a line amount — its `nightly_rate_cents` multiplied by its `rooms_held`, rounded half-up to whole cents per line — and the `reconciled_amount_cents` is the half-up-rounded sum of those lines plus the late-cancel charge, which is half (50 percent) of the sum of the late-cancelled allocations' own per-line amounts, each line likewise rounded half-up before being summed.

Immediately after, the system computes `variance_pct`. When the reconciled amount is zero, the variance is 0.0 if the billed amount is also zero and 100.0 otherwise. Otherwise the variance is the absolute difference between `billed_amount_cents` and `reconciled_amount_cents` divided by the reconciled amount, expressed as a percentage, rounded half-up to 2 decimal places. (A reporting view that instead divides by the billed amount may surface vendor overstatement differently, but it must never drive approval.)

Approval moves `RECONCILED → APPROVED` and is gated on the union's fiscal provision: the invoice's `variance_pct` must be no more than the `max_invoice_variance_pct` of the union agreement for the station's crew — an exact-threshold variance passes — or approval is refused with `ERR_INVOICE_VARIANCE_EXCEEDED` (HTTP 422). From `APPROVED`, finance marks the invoice paid (`APPROVED → PAID`). Either a reconciled or an approved invoice may instead be disputed (`RECONCILED → DISPUTED` or `APPROVED → DISPUTED`), and a disputed invoice may be re-reconciled (`DISPUTED → RECONCILED`), which re-runs both the reconciliation and the variance computation and overwrites the reconciled fields. `PAID` and `REJECTED` are terminal. The invoice list supports `contract_id?` and `status?` filters.

## 4. Endpoint Definitions

Operations that create a new resource — a station, union agreement, vendor, RFP cycle, proposal, contract (via award), layover requirement, room allocation (via book or distressed-book), transport trip, feedback row, audit, or invoice — return `201 Created`. Operations that mutate an existing resource's state — including all state-transition actions, counter-offers, reconciliation, and the clock set — return `200 OK`. Request payloads, response bodies, and side effects are specified in §3; this table is a lookup index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (starts at 2026-09-01T00:00:00Z) | PlatformAdmin |
| POST | `/stations` | Create a station | PlatformAdmin |
| GET | `/stations` | List stations | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| GET | `/stations/{id}` | Get one station | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| POST | `/union-agreements` | Create a union agreement | PlatformAdmin |
| GET | `/union-agreements` | List union agreements | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor |
| GET | `/union-agreements/{id}` | Get one union agreement | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor |
| POST | `/hotel-vendors` | Create a hotel vendor (born `ACTIVE`) | PlatformAdmin |
| GET | `/hotel-vendors` | List vendors | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| GET | `/hotel-vendors/{id}` | Get one vendor | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| POST | `/rfp-cycles` | Create an RFP cycle in `DRAFT` | SourcingManager |
| GET | `/rfp-cycles` | List RFP cycles | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, HotelVendorRep |
| GET | `/rfp-cycles/{id}` | Get one cycle | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, HotelVendorRep |
| POST | `/rfp-cycles/{id}/open` | `DRAFT → OPEN` | SourcingManager |
| POST | `/rfp-cycles/{id}/close` | `OPEN → EVALUATION`; cascades proposals `SUBMITTED → UNDER_REVIEW` | SourcingManager |
| POST | `/rfp-cycles/{id}/open-negotiation` | `EVALUATION → NEGOTIATION` (round increments) or `NEGOTIATION → EVALUATION` (return) | SourcingManager |
| POST | `/rfp-cycles/{id}/award` | `NEGOTIATION → AWARDED`; creates the `DRAFT` contract; OCC on cycle version | SourcingManager |
| POST | `/rfp-cycles/{id}/cancel` | `→ CANCELLED` from any non-terminal state; rejects remaining proposals | SourcingManager |
| POST | `/rfp-cycles/{id}/proposals` | Vendor submits a proposal to an `OPEN` cycle | HotelVendorRep |
| GET | `/rfp-proposals` | List proposals | PlatformAdmin, SourcingManager, FinanceAnalyst, HotelVendorRep |
| GET | `/rfp-proposals/{id}` | Get one proposal | PlatformAdmin, SourcingManager, FinanceAnalyst, HotelVendorRep |
| POST | `/rfp-proposals/{id}/shortlist` | `UNDER_REVIEW → SHORTLISTED` | SourcingManager |
| POST | `/rfp-proposals/{id}/reject` | `UNDER_REVIEW`/`SHORTLISTED → REJECTED` | SourcingManager |
| POST | `/rfp-proposals/{id}/withdraw` | `→ WITHDRAWN`; only the owning vendor's representative | HotelVendorRep |
| POST | `/rfp-proposals/{id}/counter-offer` | Rewrite `current_rate_cents` during `NEGOTIATION` | SourcingManager |
| GET | `/contracts` | List contracts | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| GET | `/contracts/{id}` | Get one contract (lazy-settles to `EXPIRED` past `end_date`) | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| POST | `/contracts/{id}/activate` | `DRAFT → ACTIVE` with union-compliance and vendor gates | SourcingManager |
| POST | `/contracts/{id}/remediate` | `SUSPENDED → ACTIVE` when no open `CRITICAL` audit remains | SourcingManager |
| POST | `/contracts/{id}/terminate` | `ACTIVE` (three-strike) or `SUSPENDED → TERMINATED` | SourcingManager |
| POST | `/layover-requirements` | Create a layover requirement; computes `rest_compliant` | CrewOps |
| GET | `/layover-requirements` | List layover requirements | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor |
| GET | `/layover-requirements/{id}` | Get one layover requirement | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor |
| POST | `/layover-requirements/{id}/book` | `PLANNED → CONFIRMED`; creates the `CONTRACTED` allocation; OCC on layover version | CrewOps |
| POST | `/layover-requirements/{id}/distressed-book` | `SURGED → CONFIRMED`; creates the `DISTRESSED` allocation | CrewOps |
| POST | `/layover-requirements/{id}/cancel` | `→ CANCELLED` from `PLANNED`/`CONFIRMED`/`SURGED`; cascades allocations and trips | CrewOps |
| POST | `/layover-requirements/{id}/transport-trips` | Schedule a ground transport trip; computes `pickup_time` | CrewOps |
| GET | `/allocations` | List allocations | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| GET | `/allocations/{id}` | Get one allocation | PlatformAdmin, SourcingManager, CrewOps, FinanceAnalyst, CrewAuditor, HotelVendorRep |
| POST | `/allocations/{id}/confirm` | `HELD → CONFIRMED`; computes `distressed_cost_cents` for `DISTRESSED` | CrewOps |
| POST | `/allocations/{id}/check-in` | `CONFIRMED → CHECKED_IN`; cascades layover to `COMPLETED` | HotelVendorRep |
| POST | `/allocations/{id}/no-show` | `CONFIRMED → NO_SHOW` after the stay date | CrewOps |
| POST | `/allocations/{id}/release` | `HELD → RELEASED`; cascades layover `CONFIRMED → SURGED` | CrewOps |
| GET | `/transport-trips` | List transport trips | PlatformAdmin, SourcingManager, CrewOps, CrewAuditor |
| GET | `/transport-trips/{id}` | Get one trip (lazy-settles to `MISSED` past `pickup_time`) | PlatformAdmin, SourcingManager, CrewOps, CrewAuditor |
| POST | `/transport-trips/{id}/dispatch` | `SCHEDULED → DISPATCHED` | CrewOps |
| POST | `/transport-trips/{id}/complete` | `DISPATCHED → COMPLETED` | CrewOps |
| POST | `/crew-feedback` | File crew feedback on a contract | CrewOps |
| GET | `/crew-feedback` | List feedback | PlatformAdmin, SourcingManager, CrewOps, CrewAuditor |
| GET | `/crew-feedback/{id}` | Get one feedback row | PlatformAdmin, SourcingManager, CrewOps, CrewAuditor |
| POST | `/audits` | Open an audit; severity `CRITICAL` suspends the contract | CrewAuditor |
| GET | `/audits` | List audits | PlatformAdmin, SourcingManager, CrewAuditor |
| GET | `/audits/{id}` | Get one audit | PlatformAdmin, SourcingManager, CrewAuditor |
| POST | `/audits/{id}/start` | `OPEN → IN_PROGRESS` | CrewAuditor |
| POST | `/audits/{id}/close` | `IN_PROGRESS → CLOSED_PASS` or `CLOSED_FAIL`; `FAIL` terminates the contract | CrewAuditor |
| POST | `/invoices` | Vendor submits an invoice against a contract | HotelVendorRep |
| GET | `/invoices` | List invoices | PlatformAdmin, SourcingManager, FinanceAnalyst, HotelVendorRep |
| GET | `/invoices/{id}` | Get one invoice | PlatformAdmin, SourcingManager, FinanceAnalyst, HotelVendorRep |
| POST | `/invoices/{id}/reconcile` | `RECEIVED → RECONCILED`; runs reconciliation and variance | FinanceAnalyst |
| POST | `/invoices/{id}/approve` | `RECONCILED → APPROVED`; fiscal variance gate | FinanceAnalyst |
| POST | `/invoices/{id}/dispute` | `RECONCILED`/`APPROVED → DISPUTED` | FinanceAnalyst |
| POST | `/invoices/{id}/re-reconcile` | `DISPUTED → RECONCILED`; re-runs reconciliation | FinanceAnalyst |
| POST | `/invoices/{id}/mark-paid` | `APPROVED → PAID` | FinanceAnalyst |
| POST | `/invoices/{id}/reject` | `RECEIVED → REJECTED` | FinanceAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is a lookup index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DEADLINE_PASSED` | 422 |
| `ERR_NOT_NEGOTIABLE` | 409 |
| `ERR_REST_VIOLATION` | 422 |
| `ERR_BLACKOUT_DATE` | 422 |
| `ERR_ROOM_BLOCK_EXHAUSTED` | 422 |
| `ERR_LAYOVER_ALREADY_BOOKED` | 409 |
| `ERR_PICKUP_CONFLICT` | 409 |
| `ERR_VENDOR_INACTIVE` | 422 |
| `ERR_UNION_STANDARD_VIOLATION` | 422 |
| `ERR_TERMINATION_THRESHOLD` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_INVOICE_VARIANCE_EXCEEDED` | 422 |
