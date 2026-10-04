# Ocean Detention & Demurrage Billing API — Product Requirements Document

## 1. Introduction

Ocean carriers levy two distinct families of accessorial charges on the cargo interests they serve: **demurrage**, which accrues while a loaded container sits at the marine terminal beyond its allotted free time, and **detention**, which accrues while carrier-owned equipment remains in the customer's possession off-terminal. Both charges are perennial sources of billing friction — free-time arithmetic is entangled with terminal working-day calendars (Sundays, holidays, and sometimes Saturdays), the customer's ability to retrieve a container is bounded by gate appointment availability, and external blockers such as customs inspections and chassis shortages can make accrual genuinely unfair. The result, at any scale, is a standing backlog of billing disputes that must be adjudicated under segregation-of-duties controls and documented waiver authority.

This document specifies the Ocean Detention & Demurrage Billing API, mounted under the `/ocean-billing` path prefix. The system covers the full commercial lifecycle: onboarding customer accounts and service contracts with contract-specific free-time and rate schedules; registering terminals, their holiday calendars, appointment slot inventory, and empty-return depots; tracking each container from discharge through availability, gate-out, empty return, and invoicing; computing demurrage and detention accruals on tiered rate schedules with a hold-overlay rule that stops the clock during excusable delays; and managing the financial tail — invoice aging, payments, disputes with evidence, credit waivers under tiered authority, and write-offs. A logical clock under test control drives every time-dependent rule, so aging posture sweeps, dispute SLA escalation, and contract expiry are deterministic.

The intended audience is the engineering team building the service. Requirements are stated from a product perspective; the narrative deliberately spreads related rules across subsections in the same way the underlying business process spreads them across departments, and §4 and §5 consolidate the HTTP and error-code surface for reference.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly seven roles, spelled as follows: `ContractManager`, `TerminalOperator`, `EquipmentController`, `BillingAgent`, `CreditSupervisor`, `CreditDirector`, and `CustomerRep`. A request missing either header, or presenting a role not in this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The seven roles divide the work along a strict segregation-of-duties boundary. A `ContractManager` owns the commercial master data: customer accounts and service contracts, including account closure and contract activation. A `TerminalOperator` runs the physical terminal side — terminals, holidays, appointment slots, container intake and availability, gate moves, and terminal-side holds. An `EquipmentController` manages the equipment side: return locations, chassis shortage holds, return-location reassignment, and empty returns. A `BillingAgent` issues invoices, tenders payments, reviews disputes, and proposes or applies small credits within the lowest authority tier. A `CreditSupervisor` approves mid-tier credits and resolves disputes within mid-tier limits. A `CreditDirector` holds unbounded credit authority, performs write-offs, and reverses applied waivers. A `CustomerRep` is the external customer-facing role, filing disputes and evidence against their own account's invoices and booking gate appointments.

Identity semantics differ across roles and are part of the contract. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks compare the resource's foreign-key field to `X-User-ID` — a customer representative filing a dispute, for example, may only act on invoices billed to the account whose `id` they present, and any attempt to act on another account's resource is rejected with `ERR_FORBIDDEN`. Ownership enforcement applies to the mutating customer-facing operations — filing and withdrawing a dispute, attaching evidence, and booking or cancelling a gate appointment; read endpoints (single gets and lists) perform no ownership filtering, so a `CustomerRep` may read any resource their role is authorized to list. For the remaining six roles — `ContractManager`, `TerminalOperator`, `EquipmentController`, `BillingAgent`, `CreditSupervisor`, and `CreditDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution (for example, as `applied_by_user_id` on a `CreditWaiver`, or as the reviewing-user stamp captured when a dispute enters review) but never compares it to any entity's `id`.

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

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter controls how many items are skipped and defaults to 0 and must be non-negative. A `limit` or `offset` that is not an integer, or a `limit` outside 1–100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses carry four pagination fields inside the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time Semantics

All time-dependent behavior in the system — free-time computation, accrual, aging buckets, dispute SLA escalation, and contract expiry — reads a single server-maintained **logical clock**, never the host wall clock. At server startup the logical clock is initialized to `2026-09-01T00:00:00Z` and it never falls back to wall-clock time thereafter. An administrative test-driving capability sets the clock: any of the six internal roles — `ContractManager`, `TerminalOperator`, `EquipmentController`, `BillingAgent`, `CreditSupervisor`, `CreditDirector` (but not `CustomerRep`) — may request that the logical clock be set to a supplied `to_iso8601` instant (forward or backward; the value is applied unconditionally), and the response echoes the new `current_utc`. Setting the clock is not a passive act — it triggers the aging-posture sweep (§2.7), flips the `escalated` flag on overdue disputes, and expires service contracts whose coverage window has closed (§3.1).

All calendar arithmetic that feeds free-time windows and accrual day counts is performed in the **terminal's own timezone**, not in UTC. Each `Terminal` carries a `timezone` field holding an IANA timezone name, and a "day" for that terminal means a calendar date as observed in that timezone — not a rolling 24-hour window. Two timestamps stored in UTC may therefore anchor day counts in a local calendar where midnight boundaries differ from UTC boundaries.

### 2.5. Common Resource Properties

Primary resources — `CustomerAccount`, `ServiceContract`, `Terminal`, `TerminalAppointmentSlot`, `EquipmentReturnLocation`, `Container`, `Invoice`, `Dispute`, and `CreditWaiver` — share a standard set of system-managed fields:

- **`id`** (string): a unique server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that increments with every modification, serving as the basis for optimistic concurrency control where declared.

Three resource types are deliberately lighter. `TerminalHoliday`, `ChargeAccrual`, and `Payment` carry only `id` and `created_at`; both `updated_at` and `version` are absent from these entities. Accrual rows and payments are immutable ledger facts once written, and holiday declarations are append-only, so no mutation-tracking machinery is attached to them.

### 2.6. Monetary Values and Precision

All monetary amounts in the system are integer counts of cents — fields such as `outstanding_balance_cents`, `demurrage_amount_cents`, `detention_amount_cents`, `gross_amount_cents`, `credit_total_cents`, `paid_total_cents`, `balance_due_cents`, `contested_amount_cents`, `resolved_amount_cents`, and `amount_cents` never carry fractional values. The tiered rate tables are defined in whole cents per day, so accrual arithmetic produces integer results with no rounding step. API representations of monetary fields are JSON integers, not strings and not decimal floats. Day counts (`demurrage_free_days`, `detention_free_days`, `demurrage_billable_days`, `detention_billable_days`, `billable_days`) are whole-day integers as well.

### 2.7. Aging Posture and Credit-Hold Sweeps

The system continuously monitors receivable aging at the account level through an **aging-posture sweep**. The sweep runs on every advance of the logical clock and again after every payment or credit mutation, and also after invoice issuance. For each `CustomerAccount`, the sweep totals the `balance_due_cents` of that account's invoices whose `aging_bucket` is `DAYS_61_PLUS` and whose status is `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`. The account tracks a consecutive-day counter: the counter increments at a sweep where this `DAYS_61_PLUS` exposure is greater than zero, and resets to zero at any sweep where the exposure is zero. When the counter reaches seven consecutive logical days while the account is `ACTIVE`, the account transitions to `SUSPENDED`, its `credit_hold` flag is set to `true`, and new container intake for the account is thereafter rejected with `ERR_ACCOUNT_CREDIT_HOLD`. Conversely, when a sweep finds the `DAYS_61_PLUS` exposure has returned to zero while the account is `SUSPENDED` — meaning no invoice for the account remains in `DAYS_61_PLUS` with a positive balance — the account transitions back to `ACTIVE` and `credit_hold` is cleared to `false`. Each of these automatic transitions is a mutation of the account and therefore refreshes `updated_at` and increments `version`.

The account-level `outstanding_balance_cents` field is a computed aggregate: it is the sum of `balance_due_cents` over the account's invoices in status `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`, and it is recomputed on every invoice mutation — issuance, payment, credit application, dispute-driven balance change, reversal, or write-off.

### 2.8. Optimistic Concurrency Control

Two write operations in the dispute-and-credit workflow are protected by optimistic concurrency control, and the protection is mandatory, not optional.

Resolving a dispute requires the request to carry `expected_dispute_version`, holding the client's last observed `version` of the `Dispute`. If the dispute's current `version` on the server has advanced beyond that value — for example because another writer returned the dispute to the queue or attached evidence, each of which bumps the version — the resolve request is rejected with `ERR_STALE_VERSION` (HTTP 412). The same pattern guards credit approval: approving a credit waiver requires `expected_waiver_version` matching the `CreditWaiver`'s current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.9. Nested Resource Retrieval

Requests that address nested resources — a contract beneath an account, a slot beneath a terminal, a dispute beneath an invoice, a booking beneath a container — are validated left-to-right along the path. The system confirms the existence of each path identifier in sequence, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any business-rule evaluation begins. A booking cancellation addressed under a nonexistent container therefore fails on the container identifier before the booking identifier is ever consulted.

### 2.10. Validation Order

When several rules could reject the same request, the system applies checks in a fixed priority order so that the surfaced error is deterministic. Authentication context comes first: missing or malformed identity headers produce `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is examined. Role authorization follows, producing `ERR_FORBIDDEN`. Path-resource existence comes third, producing `ERR_NOT_FOUND` with left-to-right semantics per §2.9. Fourth are request-shape checks — missing required fields, invalid enumerations, out-of-range numerics, malformed timestamps, or a window whose end precedes its start — producing `ERR_INVALID_REQUEST`. Fifth, the target resource must be in a state from which the requested transition exists, otherwise `ERR_INVALID_STATE`. Sixth come container-hold safety checks (`ERR_CONTAINER_HELD`). Seventh come terminal working-day and evidence-window checks (`ERR_NOT_A_WORKING_DAY`). Eighth come capacity and uniqueness checks (`ERR_CAPACITY_OR_CONFLICT` and its slot-specific sibling `ERR_SLOT_RELEASED`). Ninth come cross-entity referential guards (`ERR_REFERENTIAL_GUARD` together with the contract/account state guards `ERR_CONTRACT_NOT_IN_EFFECT`, `ERR_ACCOUNT_NOT_ACTIVE`, and `ERR_ACCOUNT_CREDIT_HOLD`). Tenth and last come the fiscal guards on payments, credits, dispute resolutions, and write-offs — amount-within-balance, authority tier, segregation of duties, and the OCC version match — producing the fiscal error codes enumerated in §5. A request that fails several checks reports the earliest failure in this order, never a later one. CustomerRep ownership-based `ERR_FORBIDDEN` checks (§2.1) are not part of the second-step role authorization; they are evaluated only after path-resource existence has been confirmed.

## 3. Business Logic & Workflows

### 3.1. Commercial Onboarding: Accounts and Service Contracts

A `ContractManager` opens the commercial relationship by registering a **CustomerAccount**, supplying a unique `account_code` and the customer's `legal_name`. The account is born `ACTIVE` with `credit_hold` false and `outstanding_balance_cents` at zero; both the flag and the balance are system-managed thereafter. The `account_code` is unique across all accounts — a duplicate is rejected with `ERR_CAPACITY_OR_CONFLICT`.

Beneath each account, the `ContractManager` drafts one or more **ServiceContract** records that define the commercial terms governing that customer's containers. A contract is created in `DRAFT` status with a unique `contract_ref`, two free-time allowances — `demurrage_free_days` and `detention_free_days`, each an integer from 0 to 30 inclusive — and two rate-schedule selections: `demurrage_rate_schedule` and `detention_rate_schedule`, each either `STANDARD` or `EXTENDED_TIERED`. The contract also carries `saturday_counts_as_free_day`, a boolean defaulting to false that decides whether Saturdays consume free time or are skipped like Sundays, and a coverage window bounded by `effective_from` and `effective_to`, both inclusive UTC calendar dates with the end no earlier than the start. Each contract is anchored to its owning account via `customer_account_id`.

A `DRAFT` contract becomes billable only through explicit activation by a `ContractManager`, which moves it from `DRAFT` to `ACTIVE`. Activation is permitted only when the current logical-clock date falls within the contract's effective window — a date before `effective_from` or after `effective_to` is rejected with `ERR_CONTRACT_NOT_IN_EFFECT` — and only while the parent account is `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. Thereafter, when the logical clock advances past `effective_to`, the contract transitions automatically to `EXPIRED`. Expiry never disturbs containers already pinned to the contract: those containers keep the contract's free-time allowances and rate schedules for the remainder of their lifecycle, grandfathered against any later contract.

An account may be closed by a `ContractManager` from either `ACTIVE` or `SUSPENDED` — a close attempt on an account in any other status (in practice, `CLOSED`) is rejected with `ERR_INVALID_STATE`. Closure demands a clean ledger: the account's `outstanding_balance_cents` must be exactly zero, else the close is rejected with `ERR_ACCOUNT_BALANCE_OUTSTANDING`, and no container of the account may remain in `DISCHARGED`, `AVAILABLE`, or `GATE_OUT`, else the close is rejected with `ERR_ACCOUNT_CONTAINERS_ACTIVE`. `CLOSED` is terminal.

### 3.2. Terminal Calendars and Gate Appointment Inventory

A `TerminalOperator` registers each marine **Terminal** with a unique `terminal_code`, the IANA `timezone` that governs its gate-day boundaries, a `daily_appointment_capacity` of at least one slot per working day, and a `gate_closed_weekends` flag — defaulting to true — that records whether gates shut on Saturdays and Sundays. Terminals observe holidays: the operator declares a **TerminalHoliday** for a terminal by supplying the `holiday_date` (a UTC calendar date whose time component is ignored) and a human `name`; the combination of terminal and `holiday_date` is unique. Holiday rows are immutable ledger facts carrying only `id` and `created_at`.

The notion of a **working day** at a terminal underpins everything downstream. A calendar date counts as a working day for a given terminal and contract when all of the following hold: the date is not a Sunday; the date is not declared as a `TerminalHoliday` at that terminal; and the date is not a Saturday unless the governing contract's `saturday_counts_as_free_day` is true. All such determinations are made on the calendar of the terminal's `timezone`.

Gate-out requires appointments, and appointments consume inventory. The operator publishes **TerminalAppointmentSlot** records for a terminal by choosing a `slot_date`, a `slot_seq` sequence number within that date (a positive integer, at least 1), and a `capacity` of at least one; the triple of terminal, `slot_date`, and `slot_seq` is unique. Slot dates must be working days — a slot dated on a Sunday, a declared holiday, or (where `gate_closed_weekends` applies) a closed weekend day is rejected with `ERR_NOT_A_WORKING_DAY`. A new slot is `OPEN` with `booked_count` zero. The system maintains the invariant that `booked_count` never falls below zero and never exceeds `capacity`: when a booking pushes `booked_count` to equal `capacity`, the slot flips from `OPEN` to `FULL`; when a cancellation brings `booked_count` back below `capacity`, a `FULL` slot reopens to `OPEN`. A `TerminalOperator` may also administratively release a slot, moving it from `OPEN` or `FULL` to `RELEASED` (releasing an already `RELEASED` slot is rejected with `ERR_INVALID_STATE`); subsequent booking attempts against a `RELEASED` slot are rejected with `ERR_SLOT_RELEASED`, while the slot's `booked_count` is preserved so that released-but-congested days remain visible as dispute evidence. The slot list endpoint, filterable by `slot_date` and `status`, is the canonical congestion evidence surface.

### 3.3. Container Intake, Availability, and the Demurrage Clock

A `TerminalOperator` registers a discharged **Container** by supplying its unique ISO 6346 `container_number`, an `equipment_type` drawn from `DRY20`, `DRY40`, `DRY40HC`, `REEFER40`, or `FLATRACK40`, the `customer_account_id` of the billed party, the `service_contract_id` whose terms will govern the move, the `terminal_id` of discharge, the `discharge_ts` timestamp, and the `available_ts` timestamp at which the box became available for pickup. Registration succeeds only when the nominated contract is `ACTIVE` — otherwise `ERR_CONTRACT_NOT_IN_EFFECT` — and only while the billed account is not under suspension; intake against an account in `SUSPENDED` with `credit_hold` true is rejected with `ERR_ACCOUNT_CREDIT_HOLD`, and intake against a `CLOSED` account is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. The nominated contract must also belong to the billed account — a contract whose `customer_account_id` differs from the container's `customer_account_id` is rejected with `ERR_REFERENTIAL_GUARD`. The contract pin is immutable: from registration onward the container's free-time allowances and tier schedules are exactly those of the pinned contract, regardless of the contract's later expiry. The container is born `DISCHARGED`.

Marking availability moves the container from `DISCHARGED` to `AVAILABLE`. The move requires `available_ts` to be no earlier than `discharge_ts`; an inverted pair is rejected with `ERR_INVALID_REQUEST`. At this moment the **demurrage free-time clock** anchors: the free window begins on the first terminal working day strictly after `available_ts`, under the working-day definition of §3.2.

While a container is at the terminal it may carry holds. Placing or releasing a hold is performed by a `TerminalOperator` or an `EquipmentController`, supplying a `hold_code` and an `action`. The recognized hold codes are `CUSTOMS_HOLD`, `CHASSIS_SHORTAGE`, and `USDA_HOLD`. A place action appends an entry to the container's `hold_flags` array recording the code, a `placed_ts` stamped from the logical clock, and a null `released_ts`; placing a hold whose code already has an active entry is idempotent — no new entry is appended and the container is returned unchanged. A release action stamps `released_ts` on the active entry of that code; releasing a code with no active entry is rejected with `ERR_INVALID_REQUEST`. A hold whose `released_ts` is null is active. Placing a `CUSTOMS_HOLD` or `USDA_HOLD` while the container is `AVAILABLE` overlays the terminal sub-state `CUSTOMS_HELD` onto `AVAILABLE` — the container's `status` field itself remains `AVAILABLE` — and — as §3.5 details — any calendar day carrying an active customs or USDA hold is excluded from both free and billable demurrage counts.

### 3.4. Gate-Out, Return-Location Selection, and Empty Return

Leaving the terminal is the pivot of the whole billing model. A gate-out performed by a `TerminalOperator` moves the container from `AVAILABLE` to `GATE_OUT` and is guarded by two families of checks. First, no active `CUSTOMS_HOLD` or `USDA_HOLD` may remain in `hold_flags`; an attempt to gate out a held container is rejected with `ERR_CONTAINER_HELD`. Second, the container must hold a confirmed appointment booking at this terminal on the gate-out day — booked in advance by a `TerminalOperator` or the customer's own `CustomerRep` against a specific slot via `slot_id`, which increments the slot's `booked_count` and is refused with `ERR_CAPACITY_OR_CONFLICT` when the slot is `FULL` or `ERR_SLOT_RELEASED` when it is `RELEASED`; a booking whose slot belongs to a different terminal than the container's is refused with `ERR_REFERENTIAL_GUARD`. Bookings are accepted regardless of the container's current lifecycle status, and a container may hold several concurrent bookings; the gate-out check requires at least one non-cancelled booking whose slot's local date equals the gate-out local date. Where appointments genuinely could not be obtained, the gate-out request may instead carry `slot_override` set true together with a documented `slot_override_reason` — an override without a reason is rejected with `ERR_INVALID_REQUEST`; without either a booking or the override the move is rejected with `ERR_APPOINTMENT_REQUIRED`. A booking may also be cancelled, which decrements the slot's `booked_count` and reopens a `FULL` slot to `OPEN`; cancelling an already-cancelled booking is rejected with `ERR_INVALID_STATE`. The booking record carries a `booking_id`, the `slot_id`, the `container_id`, and the `booked_date`.

A successful gate-out stamps `gate_out_ts` from the logical clock and performs three side effects. The demurrage accrual **finalizes**: `demurrage_billable_days` and `demurrage_amount_cents` freeze, and a `ChargeAccrual` row of `charge_kind` `DEMURRAGE` is written. The system selects an empty-return depot: among `EquipmentReturnLocation` records whose `terminal_id` matches the container's terminal, whose `accepts_equipment_types` array contains the container's `equipment_type`, and whose status is `OPEN` or `RESTRICTED`, it picks the location with the highest `daily_empty_capacity`, breaking ties by ascending `location_code`, and records the choice in `assigned_return_location_id`; if the eligible pool is empty the gate-out fails with `ERR_NO_RETURN_LOCATION`. Finally, the **detention free-time clock** anchors at the first working day strictly after `gate_out_ts`, under the same working-day rules.

While the container is in `GATE_OUT`, an `EquipmentController` may reassign the return depot by supplying a new `assigned_return_location_id`; reassignment validates only that the new location serves the container's terminal and accepts its `equipment_type` (else `ERR_REFERENTIAL_GUARD`) — the target location's status is not consulted at reassignment time — and stamps the assignment timestamp from the logical clock. Returning the empty — again an `EquipmentController` action — moves the container from `GATE_OUT` to `EMPTY_RETURNED` and is checked against the assigned depot: the assignment must exist (else `ERR_INVALID_STATE`); the location must not be `CLOSED`, else `ERR_RETURN_LOCATION_CLOSED`; if the location is `RESTRICTED`, only containers assigned before the restriction was set may return there, others being rejected with `ERR_RETURN_LOCATION_RESTRICTED`; and the number of empties already accepted at that location on the return date must be below its `daily_empty_capacity`, else `ERR_CAPACITY_OR_CONFLICT`. A return location refusing a container's `equipment_type` outright raises `ERR_REFERENTIAL_GUARD`. On acceptance, `empty_return_ts` is stamped from the logical clock, the detention accrual finalizes — `detention_billable_days` and `detention_amount_cents` freeze and a `ChargeAccrual` row of `charge_kind` `DETENTION` is written — and the location's daily empty-return counter for that date increments. An `EquipmentController` manages the depots themselves: registering one takes a unique `location_code`, the `terminal_id` whose empties it accepts, the `accepts_equipment_types` array (any of the five equipment types), and a `daily_empty_capacity` of at least one, with the location born `OPEN`; its status may later be set to `OPEN`, `RESTRICTED`, or `CLOSED`.

### 3.5. Free Time, Hold Overlays, and Tiered Accrual

Free time is computed in working days per §3.2. The **demurrage free window** is the first `demurrage_free_days` working days strictly after `available_ts` — zero free days means an empty window — and the **detention free window** is the first `detention_free_days` working days strictly after `gate_out_ts`. Layered over both windows is the **hold overlay**: any calendar day on which the container carried an active `CUSTOMS_HOLD` or `USDA_HOLD` during its demurrage phase, or an active `CHASSIS_SHORTAGE` during its detention phase, is excluded from both the free-day count and the billable-day count. A hold covers the local calendar date on which it was placed through the local date immediately before its release date; the release day itself counts normally, and a hold with no release covers its placed date and every day forward. The clock simply stops on those days; a hold day is neither free nor billable.

**Demurrage accrual** counts billable days as the working days strictly after the demurrage free window, on or before the accrual end, excluding hold-overlay days. Pricing is marginal against the pinned contract's `demurrage_rate_schedule`. Under `STANDARD`, billable days one through three cost 15000 cents per day, days four through seven cost 30000 cents per day, and days eight and beyond cost 45000 cents per day. Under `EXTENDED_TIERED`, days one through five cost 12000 cents per day, days six through ten cost 24000, days eleven through fifteen cost 36000, and days sixteen and beyond cost 50000. Marginal allocation means the k-th billable day is priced at the tier whose range contains k, so a run of days straddling a boundary splits across tiers; the total is the sum over billable days of each day's marginal rate. The evaluation order is fixed: the billable-day count is established first from the working-day sequence, and only then is each day mapped to its tier rate — the tier table never influences which days count.

**Detention accrual** follows the same shape with a deliberately different table. Billable days are working days strictly after the detention free window, on or before the accrual end, excluding days with an active `CHASSIS_SHORTAGE`. Under `STANDARD`, detention days one through four cost 9000 cents per day, days five through nine cost 18000, and days ten and beyond cost 27000. Under `EXTENDED_TIERED`, days one through six cost 7000, days seven through thirteen cost 15000, and days fourteen and beyond cost 22000. Marginal day-index mapping is identical to demurrage.

Each family of accrual exists in two variants. The **final** variant runs at the lifecycle transition — gate-out for demurrage, empty return for detention — with the accrual end set to the transition date; its result is frozen onto the container and persisted as a `ChargeAccrual` row recording `container_id`, `charge_kind`, `billable_days`, `amount_cents`, the `rate_schedule` actually applied, a `computed_at` stamp from the logical clock, and the inclusive day window from `window_from` to `window_to` — the local dates of the first and last billable days, both null when `billable_days` is zero. The **provisional** variant runs whenever a container is read while still accruing — at the terminal in `AVAILABLE` for demurrage, or off-terminal in `GATE_OUT` for detention — with the accrual end set to the current logical date; its result refreshes the container's computed `demurrage_billable_days`, `demurrage_amount_cents`, `detention_billable_days`, and `detention_amount_cents` fields for display but is never persisted as a `ChargeAccrual`. Provisional and final figures diverge whenever the logical clock moves between reads, which is precisely what lets a billing agent quote a customer an as-of-today number before the physical move completes.

`ChargeAccrual` rows are ledger facts and can be voided but never edited: each row's `voided` flag is false at creation, and voided rows are excluded from invoice totals. The voiding rule is tied to credits (§3.8). Accrual history for a container is queryable with filters on `charge_kind` and `voided`.

### 3.6. Invoicing and Aging

Once a container reaches `EMPTY_RETURNED`, a `BillingAgent` issues its **Invoice** — exactly one invoice per container lifecycle — provided the billed account is not `CLOSED`, else `ERR_ACCOUNT_NOT_ACTIVE`. Issuance freezes the financial snapshot: `demurrage_total_cents` and `detention_total_cents` are taken from the non-voided `ChargeAccrual` rows at that instant; `gross_amount_cents` is their sum; `credit_total_cents` starts as the sum of any `APPLIED` credits (zero at issuance) and `paid_total_cents` likewise starts at zero; and `balance_due_cents` is the gross minus credits minus payments, with the invariant that it never goes below zero. The invoice records `issued_at` from the logical clock and `due_at` exactly 30 calendar days later, and is born `ISSUED`. Issuance also moves the container to `BILLED` — its terminal state — and adds the new `balance_due_cents` into the account's `outstanding_balance_cents`.

Every invoice read recomputes its **aging bucket** against the logical clock. The days-past-due figure is the count of calendar days from `due_at` to the current logical date and may be zero or negative while the invoice is inside terms. An invoice whose `balance_due_cents` is zero is always `CURRENT`. Otherwise: days-past-due at or below zero is `CURRENT`; one through thirty is `DAYS_1_30`; thirty-one through sixty is `DAYS_31_60`; and sixty-one or more is `DAYS_61_PLUS`. The boundaries are inclusive downward — exactly 30 days past due is `DAYS_1_30`, exactly 60 is `DAYS_31_60`, and exactly 61 is the first day of `DAYS_61_PLUS`. Invoices may be listed with filters on `customer_account_id`, `status`, `aging_bucket`, and `container_id`, which together form the aging-receivable management surface.

Payments are tendered by a `BillingAgent` against any invoice not yet settled — `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`; only `PAID` and `WRITTEN_OFF` invoices refuse payment, with `ERR_INVOICE_ALREADY_SETTLED`. A payment carries `amount_cents` — at least one cent and never more than the invoice's current `balance_due_cents`, with an overage rejected as `ERR_PAYMENT_EXCEEDS_BALANCE` — and is stamped `tendered_at` from the logical clock with the terminal status `SETTLED`; payments cannot be reversed in this version. A payment below the full balance moves the invoice to `PARTIALLY_PAID`; one exactly equal to the remaining balance moves the invoice to `PAID`. These status transitions apply to a `DISPUTED` invoice as well: a payment tendered while a dispute is open moves the invoice out of `DISPUTED` to `PARTIALLY_PAID` or `PAID` on the same balance rule, without touching the open dispute itself. Every payment adds into `paid_total_cents`, recomputes `balance_due_cents`, subtracts the amount from the account's `outstanding_balance_cents`, and triggers an aging-posture sweep that may unsuspend the account.

### 3.7. Disputes, Evidence, and SLA Escalation

A customer who believes an accrual is wrong files a **Dispute** through their `CustomerRep` against an invoice in `ISSUED` or `PARTIALLY_PAID` — a `DISPUTED` invoice also passes the state gate, but since a `DISPUTED` invoice always has an open dispute the already-open guard below rejects the filing in practice — and only their own: the representative's account must equal the invoice's `customer_account_id`, recorded as `filed_by_account_id`, with a mismatch rejected as `ERR_FORBIDDEN`. Only one dispute may be open per invoice at a time; filing while another dispute on the same invoice is `SUBMITTED` or `UNDER_REVIEW` is rejected with `ERR_DISPUTE_ALREADY_OPEN`. The filing names a `dispute_reason` — one of `APPOINTMENT_UNAVAILABLE`, `CHASSIS_SHORTAGE`, `CUSTOMS_HOLD`, `FREE_TIME_MISCALC`, `RATE_MISMATCH`, or `OTHER` — plus the `contested_amount_cents` (at least one cent and no more than the invoice's `balance_due_cents`, with either bound violated rejected as `ERR_INVALID_REQUEST`), an evidence window bounded by `evidence_window_start` and `evidence_window_end` (end no earlier than start), and a free-text `evidence_summary` that must be non-empty at filing (else `ERR_INVALID_REQUEST`) and for any later credit decision. Filing stamps `submitted_at` from the logical clock, sets `sla_due_at` fourteen calendar days after submission, moves the invoice to `DISPUTED`, and starts the dispute in `SUBMITTED` status. Notably, disputing an invoice does **not** freeze its aging clock: the contested amount remains inside `balance_due_cents` and continues to age through the buckets, so a stalled dispute can still push an account toward suspension.

Evidence accretes onto an open dispute — one in `SUBMITTED` or `UNDER_REVIEW`; attaching to a dispute in any other status is rejected with `ERR_INVALID_STATE` — as **DisputeEvidence** items, attached by the `CustomerRep` (their own account's disputes only, per the §2.1 ownership rule) or a `BillingAgent` via `evidence_type` — `APPOINTMENT_SCREENSHOT`, `CHASSIS_POOL_NOTICE`, `CUSTOMS_HOLD_NOTICE`, `APPOINTMENT_API_LOG`, or `OTHER` — an `evidence_date`, and a `reference_uri` locating the stored artifact. The `evidence_date` must fall within the dispute's evidence window, else `ERR_NOT_A_WORKING_DAY`. An item may carry `supersedes_evidence_id` pointing at an earlier artifact it corrects; the superseded item must belong to the same dispute, else `ERR_REFERENTIAL_GUARD`. The superseded item remains queryable — the evidence list supports filtering by `dispute_id` and `supersedes_evidence_id`, enabling chain traversal — but is excluded from verification totals. Every evidence attachment bumps the dispute's `version`, which is what makes a stale `expected_dispute_version` detectable at resolve time.

A `BillingAgent` picks a dispute out of the queue by starting review, moving it from `SUBMITTED` to `UNDER_REVIEW` and recording the acting `X-User-ID` as the reviewing user. For the three evidence-driven reasons — `APPOINTMENT_UNAVAILABLE`, `CHASSIS_SHORTAGE`, and `CUSTOMS_HOLD` — at least one evidence item must already be attached, otherwise start-review is rejected with `ERR_EVIDENCE_REQUIRED`; the remaining reasons may enter review bare. Review is a cycle, not a one-way door: the agent may return the dispute to the queue, moving it back from `UNDER_REVIEW` to `SUBMITTED` and clearing the reviewing-user stamp.

Disputes have a service-level clock. When the logical clock advances past a dispute's `sla_due_at` while the dispute is still `SUBMITTED` or `UNDER_REVIEW`, the system sets its `escalated` flag true; the dispute list, filterable by `invoice_id`, `filed_by_account_id`, `status`, and `escalated`, is the backlog management surface. Escalation is a flag, not a state change — the dispute remains where it was in the review cycle.

Resolution and withdrawal close the loop; both are covered in §3.8 alongside the credit machinery they drive.

### 3.8. Resolution, Credit Waterfall, and Waiver Authority

Resolving a dispute is performed by a `BillingAgent`, `CreditSupervisor`, or `CreditDirector`, acting on a dispute in `UNDER_REVIEW` (any other status yields `ERR_INVALID_STATE` before the OCC check, per §2.10). The resolve request carries `resolution_code`, `resolution_justification`, the OCC field `expected_dispute_version` (§2.8), and — for credit outcomes — `resolved_amount_cents`. These checks are evaluated in order: the stale-version rejection `ERR_STALE_VERSION` fires first when the client's observed version no longer matches (a non-integer `expected_dispute_version` is instead `ERR_INVALID_REQUEST`); then `resolution_justification` must be non-empty, else `ERR_JUSTIFICATION_REQUIRED`; then the `resolution_code` enumeration is validated (else `ERR_INVALID_REQUEST`); then amount validity and authority-tier coverage; and finally the segregation-of-duties rule — when the resolving actor is a `BillingAgent`, that user must not be the same user who filed any of the dispute's evidence, else `ERR_SEGREGATION_OF_DUTIES`.

Three resolution outcomes exist. A `FULL_CREDIT` resolution requires `resolved_amount_cents` exactly equal to the dispute's `contested_amount_cents` — any other figure is `ERR_RESOLVED_AMOUNT_INVALID` — and moves the dispute to `RESOLVED_FULL_CREDIT`. A `PARTIAL_CREDIT` resolution requires `resolved_amount_cents` of at least one and strictly less than `contested_amount_cents`, else `ERR_RESOLVED_AMOUNT_INVALID`, and moves the dispute to `RESOLVED_PARTIAL_CREDIT`. A `DENIED` resolution takes no amount — the dispute's `resolved_amount_cents` is recorded as 0 — and moves the dispute to `RESOLVED_DENIED`. Every successful resolution — credit or denial — increments the dispute's `version` by one. For the two credit outcomes, the resolution creates a `CreditWaiver` already in `APPLIED` status, linked to the dispute via `dispute_id`, for the resolved amount; the credit flows through the waterfall described below, recomputes the invoice's `credit_total_cents` and `balance_due_cents`, and reduces the account's `outstanding_balance_cents` by the credited amount. If the credit brings `balance_due_cents` to zero the invoice moves to `PAID`; otherwise it returns to `ISSUED` when nothing has been paid or `PARTIALLY_PAID` when `paid_total_cents` is positive. A `DENIED` outcome creates no credit and simply returns the invoice to `ISSUED` or `PARTIALLY_PAID` on the same paid-versus-unpaid rule. Separately, the customer may withdraw a dispute still in `SUBMITTED` — only their own, enforced through the account match with `ERR_FORBIDDEN`, and any other status yields `ERR_INVALID_STATE` — moving it to `WITHDRAWN` (with `resolution_code` recorded as `WITHDRAWN` and the dispute's `version` incremented by one) and reverting the invoice the same way. All four end states are terminal.

The **credit waterfall** decides what a credit actually offsets. A credit offsets the invoice's detention component first, then demurrage: the credited detention portion is the smaller of the credit amount and the remaining detention total after credits already applied, and the credited demurrage portion is the smaller of whatever remains of the credit and the remaining demurrage total after credits already applied. If the two portions together fall short of the credit amount — meaning the credit would exceed the creditable balance or push `balance_due_cents` negative — the credit is rejected outright with `ERR_CREDIT_EXCEEDS_BALANCE`; there is no remainder and credits never offset amounts the customer has already paid. When cumulative credits against one component reach exactly that component's frozen total, every non-voided `ChargeAccrual` row of that kind for the container is flagged `voided` true, selected in order of `computed_at` ascending — never by id.

Authority over credits is tiered by amount and is **derived**, never chosen by the caller. A credit whose amount is at most 50000 cents is `TIER_1_AGENT`, actionable by a `BillingAgent` alone; an amount above 50000 cents and at most 500000 cents is `TIER_2_SUPERVISOR`, requiring a `CreditSupervisor` or `CreditDirector`; any amount above 500000 cents is `TIER_3_DIRECTOR`, requiring a `CreditDirector`. The boundaries are inclusive downward: exactly 50000 cents is `TIER_1_AGENT`, exactly 500000 cents is `TIER_2_SUPERVISOR`. An actor whose tier does not cover the amount is rejected with `ERR_WAIVER_AUTHORITY_EXCEEDED` — in dispute resolution this applies to the resolved amount, and in the goodwill path it applies at approval time (and implicitly at proposal for amounts auto-applied on the spot); see below.

Outside disputes, the **goodwill waiver** path lets a `BillingAgent`, `CreditSupervisor`, or `CreditDirector` propose a credit against an invoice by supplying `amount_cents` (at least one cent) and a non-empty `justification` — a missing justification is `ERR_JUSTIFICATION_REQUIRED`. The invoice must not already be settled: proposing against a `PAID` or `WRITTEN_OFF` invoice is rejected with `ERR_INVOICE_ALREADY_SETTLED`, and an amount exceeding the invoice's current `balance_due_cents` is rejected with `ERR_CREDIT_EXCEEDS_BALANCE` at proposal time. The proposal records the proposer's `X-User-ID` in `applied_by_user_id`, derives `authority_tier` from the amount, and starts the waiver `PROPOSED` — except that a `TIER_1_AGENT` amount is applied immediately, propose-and-apply in one step (every role permitted to propose outranks `TIER_1_AGENT`, so no separate proposer-authority check applies; higher-tier amounts always remain `PROPOSED` and the proposer's own tier is not checked at proposal). A waiver in `PROPOSED` may be approved by a `CreditSupervisor` or `CreditDirector` whose tier covers the waiver's `authority_tier` — `TIER_3_DIRECTOR` outranks `TIER_2_SUPERVISOR`, which outranks `TIER_1_AGENT` — subject to these guards, evaluated after the OCC check: the invoice must not be `PAID` or `WRITTEN_OFF` at approval time (else `ERR_INVOICE_ALREADY_SETTLED`); the amount must not exceed the invoice's `balance_due_cents` at approval time, else `ERR_CREDIT_EXCEEDS_BALANCE`; the approver's tier must cover the waiver's `authority_tier`, else `ERR_WAIVER_AUTHORITY_EXCEEDED`; the approver must not be the proposer, enforced by comparing against `applied_by_user_id` and rejecting with `ERR_SEGREGATION_OF_DUTIES`; and the OCC field `expected_waiver_version` must match the waiver's current `version`, else `ERR_STALE_VERSION` — the stale-version check itself runs before the four other guards. Approval moves the waiver to `APPLIED`, increments the waiver's `version` by one, runs the credit through the waterfall, recomputes the invoice and account balances, and pays the invoice off if the balance reaches zero. A `CreditSupervisor` or `CreditDirector` may instead reject a `PROPOSED` waiver, moving it to `REJECTED`. An `APPLIED` waiver may be unwound only by a `CreditDirector`, only while the invoice is not `PAID` (else `ERR_INVOICE_ALREADY_SETTLED`), and only while the reversal would not push `paid_total_cents` beyond the gross less remaining credits (else `ERR_REVERSAL_EXCEEDS_NET`); reversal requires its own `justification` (else `ERR_JUSTIFICATION_REQUIRED`), requires the waiver to be `APPLIED` (any other status yields `ERR_INVALID_STATE`), moves the waiver to `REVERSED`, adds the amount back into `balance_due_cents` and the account's `outstanding_balance_cents`, and subtracts it from `credit_total_cents`. Reversal also re-derives the container's `ChargeAccrual` `voided` flags from scratch: every accrual row for the container is first reset to non-voided, then the voiding rule is re-applied against the remaining `APPLIED` credits in `created_at` order, so a reversal that drops a component below full credit un-voids that component's rows. Waivers are queryable per invoice and per dispute, each list filterable by `status`, and individually by identifier.

The final financial off-ramp is the **write-off**, reserved for a `CreditDirector`. An invoice in `ISSUED` or `PARTIALLY_PAID` whose `aging_bucket` has reached `DAYS_61_PLUS` may be written off with a documented `justification` — a missing justification is rejected first with `ERR_JUSTIFICATION_REQUIRED`, an invoice in any other status (including `DISPUTED`) with `ERR_INVALID_STATE`, and an invoice aged less with `ERR_INVOICE_NOT_AGED_ENOUGH`. The write-off creates an implicit `TIER_3_DIRECTOR` `CreditWaiver` in `APPLIED` status for the full remaining balance, with `dispute_id` null, moves the invoice to `WRITTEN_OFF`, zeroes its `balance_due_cents`, and subtracts the written-off amount from the account's `outstanding_balance_cents`. `WRITTEN_OFF` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource — registering an account, contract, terminal, holiday, slot, return location, container, booking, invoice, dispute, evidence item, payment, or goodwill waiver — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions such as activation, gate-out, empty return, review actions, resolution, approval, rejection, reversal, write-off, and the logical-clock advance — return `200 OK`. All endpoints are mounted under the `/ocean-billing` prefix. Request payloads, response payloads, and side effects are specified in §3; this table is the address map only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ocean-billing/_clock/set_current_utc` | Advance the logical clock; triggers aging sweep, SLA escalation, contract expiry | ContractManager, TerminalOperator, EquipmentController, BillingAgent, CreditSupervisor, CreditDirector |
| POST | `/ocean-billing/customer-accounts` | Register a customer account | ContractManager |
| GET | `/ocean-billing/customer-accounts` | List customer accounts (filter by `status`) | Any |
| GET | `/ocean-billing/customer-accounts/{accountId}` | Get one customer account | Any |
| POST | `/ocean-billing/customer-accounts/{accountId}/close` | Close an account with zero balance and no active containers | ContractManager |
| POST | `/ocean-billing/customer-accounts/{accountId}/service-contracts` | Create a service contract (DRAFT) for an account | ContractManager |
| GET | `/ocean-billing/customer-accounts/{id}/service-contracts` | List contracts for an account (filter by `status`) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, TerminalOperator, CustomerRep |
| GET | `/ocean-billing/service-contracts/{contractId}` | Get one service contract | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, TerminalOperator, CustomerRep |
| POST | `/ocean-billing/service-contracts/{contractId}/activate` | Activate a DRAFT contract within its effective window | ContractManager |
| POST | `/ocean-billing/terminals` | Register a terminal | TerminalOperator |
| GET | `/ocean-billing/terminals` | List terminals | Any |
| GET | `/ocean-billing/terminals/{terminalId}` | Get one terminal | Any |
| POST | `/ocean-billing/terminals/{terminalId}/holidays` | Declare a terminal holiday | TerminalOperator |
| GET | `/ocean-billing/terminals/{id}/holidays` | List terminal holidays | Any |
| POST | `/ocean-billing/terminals/{terminalId}/appointment-slots` | Create an appointment slot for a working day | TerminalOperator |
| GET | `/ocean-billing/terminals/{id}/appointment-slots` | List appointment slots (filter by `slot_date`, `status`) | Any |
| GET | `/ocean-billing/terminal-appointment-slots/{slotId}` | Get one appointment slot | Any |
| POST | `/ocean-billing/terminal-appointment-slots/{slotId}/release` | Administratively release (close) a slot | TerminalOperator |
| POST | `/ocean-billing/return-locations` | Register an empty-return location | EquipmentController |
| GET | `/ocean-billing/return-locations` | List return locations (filter by `terminal_id`, `status`) | Any |
| GET | `/ocean-billing/return-locations/{locationId}` | Get one return location | Any |
| POST | `/ocean-billing/return-locations/{locationId}/set-status` | Set return location status (OPEN / RESTRICTED / CLOSED) | EquipmentController |
| POST | `/ocean-billing/containers` | Register a discharged container and pin its governing contract | TerminalOperator |
| GET | `/ocean-billing/containers` | List containers (filter by `customer_account_id`, `terminal_id`, `status`, `service_contract_id`, `assigned_return_location_id`) | Any |
| GET | `/ocean-billing/containers/{containerId}` | Get one container; provisional accruals computed as-of the logical clock | Any |
| GET | `/ocean-billing/containers/{id}/accruals` | List charge accrual rows for a container (filter by `charge_kind`, `voided`) | Any |
| POST | `/ocean-billing/containers/{containerId}/mark-available` | Transition DISCHARGED to AVAILABLE | TerminalOperator |
| POST | `/ocean-billing/containers/{containerId}/holds` | Place or release a hold (CUSTOMS_HOLD / CHASSIS_SHORTAGE / USDA_HOLD) | TerminalOperator, EquipmentController |
| POST | `/ocean-billing/containers/{containerId}/appointments` | Book a gate-out appointment against a slot | TerminalOperator, CustomerRep |
| POST | `/ocean-billing/containers/{containerId}/appointments/{bookingId}/cancel` | Cancel a confirmed appointment booking | TerminalOperator, CustomerRep |
| POST | `/ocean-billing/containers/{containerId}/gate-out` | Gate the container out of the terminal; finalizes demurrage | TerminalOperator |
| POST | `/ocean-billing/containers/{containerId}/reassign-return-location` | Reassign the empty-return location while GATE_OUT | EquipmentController |
| POST | `/ocean-billing/containers/{containerId}/return-empty` | Accept empty return; finalizes detention | EquipmentController |
| POST | `/ocean-billing/containers/{containerId}/issue-invoice` | Issue the invoice for an EMPTY_RETURNED container | BillingAgent |
| GET | `/ocean-billing/invoices` | List invoices (filter by `customer_account_id`, `status`, `aging_bucket`, `container_id`) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| GET | `/ocean-billing/invoices/{invoiceId}` | Get one invoice (aging bucket computed as-of the logical clock) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/invoices/{invoiceId}/payments` | Tender a payment against an invoice | BillingAgent |
| POST | `/ocean-billing/invoices/{invoiceId}/write-off` | Write off an invoice aged into DAYS_61_PLUS | CreditDirector |
| GET | `/ocean-billing/invoices/{id}/payments` | List payments for an invoice | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| GET | `/ocean-billing/invoices/{id}/credit-waivers` | List credit waivers for an invoice (filter by `status`) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/invoices/{invoiceId}/disputes` | File a dispute against an ISSUED or PARTIALLY_PAID invoice | CustomerRep |
| GET | `/ocean-billing/disputes` | List disputes (filter by `invoice_id`, `filed_by_account_id`, `status`, `escalated`) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| GET | `/ocean-billing/disputes/{disputeId}` | Get one dispute | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| GET | `/ocean-billing/dispute-evidence/{evidenceId}` | Get one evidence item by id | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| GET | `/ocean-billing/dispute-evidence` | List evidence across disputes (filter by `dispute_id`, `supersedes_evidence_id`) | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/disputes/{disputeId}/evidence` | Attach evidence to a dispute (window-validated) | CustomerRep, BillingAgent |
| GET | `/ocean-billing/disputes/{id}/evidence` | List evidence for a dispute | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/disputes/{disputeId}/start-review` | Move dispute SUBMITTED to UNDER_REVIEW | BillingAgent |
| POST | `/ocean-billing/disputes/{disputeId}/return-to-queue` | Return an UNDER_REVIEW dispute to SUBMITTED | BillingAgent |
| POST | `/ocean-billing/disputes/{disputeId}/resolve` | Resolve a dispute (FULL_CREDIT / PARTIAL_CREDIT / DENIED); OCC-guarded | BillingAgent, CreditSupervisor, CreditDirector |
| POST | `/ocean-billing/disputes/{disputeId}/withdraw` | Customer withdraws a SUBMITTED dispute | CustomerRep |
| GET | `/ocean-billing/disputes/{id}/credit-waivers` | List credit waivers originating from a dispute | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/invoices/{invoiceId}/credit-waivers` | Propose a goodwill credit waiver outside the dispute flow | BillingAgent, CreditSupervisor, CreditDirector |
| GET | `/ocean-billing/credit-waivers/{waiverId}` | Get one credit waiver | ContractManager, BillingAgent, CreditSupervisor, CreditDirector, CustomerRep |
| POST | `/ocean-billing/credit-waivers/{waiverId}/approve` | Approve a PROPOSED waiver; OCC-guarded; approver is not the proposer | CreditSupervisor, CreditDirector |
| POST | `/ocean-billing/credit-waivers/{waiverId}/reject` | Reject a PROPOSED waiver | CreditSupervisor, CreditDirector |
| POST | `/ocean-billing/credit-waivers/{waiverId}/reverse` | Reverse an APPLIED waiver on an unsettled invoice | CreditDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard; this catalogue is the identifier-to-status map. Requests to paths outside this API's route table, or with an unsupported method on a known path, return 404 with `ERR_NOT_FOUND`.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_CREDIT_HOLD` | 409 Conflict |
| `ERR_ACCOUNT_BALANCE_OUTSTANDING` | 409 Conflict |
| `ERR_ACCOUNT_CONTAINERS_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_IN_EFFECT` | 409 Conflict |
| `ERR_CONTAINER_HELD` | 409 Conflict |
| `ERR_APPOINTMENT_REQUIRED` | 409 Conflict |
| `ERR_SLOT_RELEASED` | 409 Conflict |
| `ERR_NOT_A_WORKING_DAY` | 422 Unprocessable Entity |
| `ERR_CAPACITY_OR_CONFLICT` | 409 Conflict |
| `ERR_NO_RETURN_LOCATION` | 422 Unprocessable Entity |
| `ERR_RETURN_LOCATION_CLOSED` | 409 Conflict |
| `ERR_RETURN_LOCATION_RESTRICTED` | 409 Conflict |
| `ERR_REFERENTIAL_GUARD` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_JUSTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RESOLVED_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_WAIVER_AUTHORITY_EXCEEDED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CREDIT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_AGED_ENOUGH` | 409 Conflict |
| `ERR_INVOICE_ALREADY_SETTLED` | 409 Conflict |
| `ERR_REVERSAL_EXCEEDS_NET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
