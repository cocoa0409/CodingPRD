# Independent Agent and Owner-Operator Network Settlement API — Product Requirements Document

## 1. Introduction

Freight moves through this network on arrangements, not on payroll. Independent freight agencies source shipments and are paid a commission on the revenue those shipments earn; business capacity owners put trucks on the road under lease agreements and are paid a split of the owner-operator base; the network operator in the middle takes the remainder, holds the escrow and maintenance accounts that keep a driver solvent between settlements, carries the liability and occupational-accident programs, and decides who is fit to haul. This document specifies the API that runs all of it.

The hard part of this business is not booking a load — it is closing one. A single delivered shipment produces a three-way split, four percentage-based withholdings, a maintenance reserve, an advance recovery, and a pair of ledger entries that must land on the correct account with the correct sign, all while the parties involved are simultaneously changing qualification posture, filing credentials that expire, and competing for the same truck. Three-quarters of the requirements below exist because money that is split three ways out of one revenue pool can silently fail to add back up, and because a truck that is committed twice, or a driver whose medical card lapsed last Tuesday, has to be caught before dispatch rather than after.

Two further commitments shape the design. First, every lifecycle decision — whether a credential is still valid, whether a customer is still exclusively owned, whether a unit's inspection is overdue, whether an offer has lapsed — is evaluated against a logical clock the network advances explicitly, never against wall-clock time. Second, financial mutations are guarded by optimistic concurrency control on the version of the parent whose posture a decision depends on, so that an operator who read a stale board or a stale hold flag is stopped rather than silently overwriting a colleague's work.

---

## 2. Global Specifications & System-Wide Principles

This section collects the rules that hold across every resource and every endpoint: who may call what, how responses are shaped, how lists are paged, how the board selector and the customer book are policed, how money is rounded, and how concurrency and validation ordering behave. Everything here applies uniformly; the workflows in §3 assume it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting party and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role that is not one of the roles declared below, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but is not authorized for the operation it is attempting is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Where an operation acts on a resource the caller is expected to own, an authenticated caller acting on a resource it does not own is rejected with `ERR_UNAUTHORIZED`; separately, a business capacity owner attempting to act on an offer that was directed to a different capacity owner is rejected with `ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER`.

The network recognizes exactly six roles, spelled as follows: `FreightAgent`, `CapacityOwnerOperator`, `SafetyReviewer`, `SettlementOperator`, `NetworkAdministrator`, and `AgentManager`.

Two of the six roles are backed by persisted entities. When `X-User-Role` is `FreightAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on any resource that references an `Agent` — a load's `agent_id`, a customer account's `agent_id`, an offer's parent load — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `CapacityOwnerOperator`, `X-User-ID` is the `id` of the acting `CapacityOwner`; ownership checks on any resource that references a `CapacityOwner` — an offer's `capacity_owner_id`, a trip's `capacity_owner_id`, a fleet unit's `capacity_owner_id`, a credential's `capacity_owner_id`, a ledger entry's `capacity_owner_id` — compare that field to `X-User-ID`. These comparisons read the header value verbatim; the server
keeps no credential store, so an identity header that names an entity is trusted to act as that
entity, and role authorization likewise rests only on the declared role string.

The remaining four roles are opaque operator identities. When `X-User-Role` is `SafetyReviewer`, `SettlementOperator`, `NetworkAdministrator`, or `AgentManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier (in particular, the identity that submitted a settlement is recorded so that the segregation-of-duties check has something to compare against) but it does not compare it to any entity's `id`. `NetworkAdministrator` additionally holds the sole authority to drive the logical clock.

Role authority is enforced per operation, and the matrix is deliberately narrow. A `FreightAgent` promotes and cancels loads, posts and withdraws board offers, registers customer accounts, reads loads and customer accounts, and reads its own commission reconciliation; it may not accept an offer or drive a trip. A `CapacityOwnerOperator` accepts and declines board offers, covers an awarded load, dispatches a trip, records delivery, and aborts a non-terminal trip, and reads its own fleet, credentials, ledger and trips. A `SafetyReviewer` qualifies capacity owners, records inspections, places units out of service, files and re-evaluates credentials, and reads capacity owners and inspection histories. A `SettlementOperator` creates, submits, settles and voids settlements, posts and reverses ledger entries, verifies proofs of delivery, and evaluates the per-load fee schedule. A `NetworkAdministrator` holds the override authority — enrolling agents and capacity owners, activating, suspending, reinstating and terminating agents, retiring units, approving and rejecting settlements, driving the logical clock, and running a period close — and performs audit reads across every collection. An `AgentManager` is read-only over agent books, customer ownership records, and an agent's sourced loads. Where a role performs an operation in more than one capacity, the endpoint table in §4 lists every role permitted.

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

List responses are paged with two query-string parameters. `limit` sets the maximum number of entries returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. `offset` sets how many entries to skip and defaults to 0; a `limit` or `offset` that is not an
integer, a `limit` outside its range, or a negative `offset` is refused as malformed with
`ERR_INVALID_REQUEST`.

Unless a specific ordering is stated for an endpoint, list endpoints return resources sorted by creation timestamp ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, alongside `api_request_id` and `api_request_timestamp`.

### 2.4. The Internal Load Board and Its Ranking Precedence

A load may only be awarded while it is genuinely on the board. Each load carries a read-only `board_required` flag, true when the promoting agent's `status` is `ACTIVE` and that agent's `settlement_hold` is false, and false otherwise. A load whose `board_required` is false may never be awarded, and that condition is enforced both when the offer is posted and again at award time, so a load that loses its board eligibility between offer and acceptance is refused with `ERR_LOAD_NOT_OPEN_FOR_AWARD`.

Board competition is resolved by a single derived ordering. Every offer carries a read-only `selected_rank`, the rank of that offer among the `OPEN` offers on the same load, where a lower number is better. The ranking key is the offer's `offered_pay_cents` in descending order, then its `offered_at` ascending, then its `created_at` ascending. Ranks are re-derived for every remaining open offer whenever the set of open offers changes — when one is accepted, declined, withdrawn, or reaches its expiry — and no snapshot of a rank taken before such a change is authoritative afterwards; the rank a read reports is the one the selector policy yields on that read. Ranks never go stale.

Two derived properties on an offer constrain what may be posted. The `owner_pay_ceiling_cents` is the sum of the parent load's `linehaul_revenue_cents` and `fuel_surcharge_cents`, multiplied by the offering capacity owner's `revenue_split_pct` and rounded half up to an integer number of cents. An offer whose `offered_pay_cents` exceeds that ceiling is refused with `ERR_OFFER_EXCEEDS_PAY_CEILING`. The `expires_at` is the offer's time-to-live boundary; once the logical clock is at or after that instant the offer is no longer acceptable, and the refusal is `ERR_OFFER_EXPIRED`. The `expires_at` is derived from the offer's `offered_at` by adding a fixed time-to-live of 365 days; it is fixed when the offer is posted and does not move as the clock advances. Reading a load's board returns the offers under the same selector policy the ranks encode — `selected_rank` ascending, that is, descending pay, then ascending `offered_at`, then ascending `created_at` — and offers that have already reached `expires_at` are still listed but report status `EXPIRED`.

### 2.5. Agent Territory and the Customer Book

Territory is a first-class constraint, not a preference. An agent carries an ordered `territory_codes` list of two-letter state codes — the order *is* the precedence — and a load's `origin_state` must be a member of the promoting agent's list for that load to be promotable or awardable. A promotion or award outside the list is refused with `ERR_TERRITORY_VIOLATION`; a missing or empty list is refused at enrollment as malformed with `ERR_INVALID_REQUEST`, and an
activation that finds the row holding no territory is refused with `ERR_AGENT_TERRITORY_EMPTY`.

Where two agents both list the same state and both are in a live status — meaning `ACTIVE` or `SUSPENDED` — the state belongs to the agent that listed it earlier *within its own list*, and the earliest index wins. When two agents list the state at the same index, the agent whose row was created first takes it. This tie-break uses the agent's creation timestamp and never its identifier. A state may in practice be listed by more than one live agent: activation does not consult the
precedence rule and is never refused on that ground, so `ERR_TERRITORY_CONFLICT` is reserved
rather than raised, and the precedence rule above governs only how such an overlap is read.

Customer ownership is the second half of the same principle. Each customer account records a `first_booked_at` and a derived `ownership_expires_at`, which is the first-booking instant advanced by the owning agent's `customer_ownership_days` in days (the account's expiry equals the first-booking instant exactly when that field is zero). The derived `exclusivity_status` is `OWNED_EXCLUSIVE` strictly before `ownership_expires_at`, and `OPEN_SHARED` at or after it — except that when the account carries a `released_reason` its status is `RELEASED` regardless of the clock, and when the owning agent's `customer_ownership_days` is zero the account is `OPEN_SHARED` from creation. Promotion against a customer under another arrangement's live exclusivity — an `OWNED_EXCLUSIVE`
account of another agent carrying the same `customer_ref` — is refused with
`ERR_CUSTOMER_NON_SOLICITATION_ACTIVE`. A released account is not caught at promotion; it is
caught at award, refused with `ERR_NON_SOLICITATION_BREACH`, only while its release lies inside
the non-solicitation radius, so once a released account has aged past that radius the rule stops
applying.

### 2.6. Resource Identity and Common Properties

Every primary resource in this API — `Agent`, `CapacityOwner`, `Equipment`, `ComplianceDocument`, `CustomerAccount`, `Load`, `LoadOffer`, `Trip`, `Settlement`, and `EscrowTransaction` — carries the same four system-managed properties:

- `id` — a unique, server-minted identifier formatted as a UUID. It carries no resource-type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the row. It is the currency of the optimistic concurrency control described in §2.8.

Derived fields are mutations like any other. When a rule recomputes a derived property — an agent's `settlement_hold` or `active_customer_count` or `awarded_load_count`, a capacity owner's `escrow_balance_cents` or `maintenance_balance_cents` or `safety_score` or `qualification_posture` or `qualified_until`, an offer's `selected_rank` or `owner_pay_ceiling_cents` or `expires_at`, a load's `board_required`, a trip's `on_time` or `maintenance_reserve_cents`, a ledger entry's `resulting_escrow_balance_cents` or `resulting_maintenance_balance_cents` — the owning row's `updated_at` is refreshed and its `version` is incremented. A derived field is, however, re-evaluated as often as the clock or a read demands: a re-derivation that reproduces the value already on the row records no mutation at all, leaving `updated_at` and `version` untouched, so a read that merely refreshes a clock-derived field does not advance the row. No resource in this API is created without the full set of four properties, and no resource omits `version` or `updated_at`.

### 2.7. Monetary Precision and Rounding

All monetary quantities in this API are integer cents and are never expressed as fractional cents. Three rounding disciplines are used, and which one applies is not optional:

- Round half up. The two proportional split shares — the agent's commission share and the owner-operator's gross share — are each rounded half up to the nearest whole cent.
- Round up (ceiling). Every percentage-based withholding — the occupational-accident premium, the insurance premium, the escrow withholding, and the advance-repayment cap — is rounded up to the nearest whole cent, so a fractional cent never escapes the bucket being withheld.
- Floor. Division used to report an aggregate fee on a per-load basis is floored to a whole cent.

Because the split shares are rounded half up while the withholdings are rounded up, the settlement's conserved total is protected by construction rather than by rounding the total independently (§3.7). Configuration-style inputs such as `commission_rate_pct`, `revenue_split_pct`, and `liability_insurance_deductible_cents` preserve the precision they were supplied with; the derived outputs are integers.

### 2.8. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control on the version of the parent entity whose posture the decision depends on. In each case the request body must carry the named field, non-optionally; it holds the version of the parent entity that the caller last observed. If the supplied value does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION`.

- Posting an offer requires `expected_network_load_version`, carrying the client's last observed version of the parent `Load`. A mismatch is rejected with `ERR_STALE_VERSION`. This guard exists because a board mutation written by another party — a rival offer that now occupies the top rank, or an award that already consumed the load — legitimately supersedes the offer the caller was about to place, so the caller's board view is stale.
- Qualifying a capacity owner requires `expected_network_capacity_owner_version`, carrying the reviewer's last observed version of that `CapacityOwner`. A mismatch is rejected with `ERR_STALE_VERSION`, because a credential or an escrow deposit recorded in between supersedes the qualification decision the reviewer was about to sign.
- Submitting a settlement for approval requires `expected_network_agent_version`, carrying the operator's last observed version of the owning `Agent`. A mismatch is rejected with `ERR_STALE_VERSION`, because that agent's `settlement_hold` posture may have been recomputed in between by a status change or an advance.
- Settling a settlement requires `expected_network_load_version`, carrying the operator's last observed version of the parent `Load`. A mismatch is rejected with `ERR_STALE_VERSION`, because the load may already carry the settlement effect the operator was about to apply.

These four are the only version-guarded writes in the API. Endpoints that are not named above do not consume a version field: a body that supplies one to an
endpoint whose declared input list does not include it is accepted with that field ignored,
exactly as any other undeclared key is.

### 2.9. Equipment, Credential and Clock Currency

Every lifecycle decision that depends on time is evaluated against the network's logical clock rather than wall-clock time. Before any call that sets it, the clock reads the fixed default `2026-09-01T00:00:00Z`; it never falls back to real time. An administrative capability sets the clock to a supplied `current_utc`, and every clock-derived field — a credential's `status`, a customer account's `exclusivity_status`, a unit's `inspection_status`, an offer's expiry, an agent's `settlement_hold` — is re-evaluated on the next read.

Inspection currency on a fleet unit is derived, not stored. When the unit's `status` is `RETIRED` its `inspection_status` is `RETIRED`. Otherwise, if `inspection_passed_at` is set, is strictly before `inspection_due_at`, and the clock is not past `inspection_due_at` (the clock at the deadline instant itself is not past it), the status is `CURRENT`. Otherwise, if the clock is before `inspection_due_at`, the status is `DUE`. Otherwise the status is `OVERDUE`. A pass recorded strictly before the deadline therefore carries `CURRENT` through the deadline instant rather than flipping to `OVERDUE` there. Recording a passing inspection requires the supplied `inspected_at` to be strictly before the unit's `inspection_due_at`; the deadline instant itself is already too late, and an inspection recorded exactly at `inspection_due_at` is refused with `ERR_EQUIPMENT_INSPECTION_OVERDUE`. This exclusive form of the boundary is the pinned reading.

Credential currency follows the same clock. A credential's status is `REJECTED` when it has been explicitly rejected by the verifying clerk, is `VALID` strictly before its `expires_at`, is `EXPIRING_SOON` when the remaining time before `expires_at` is greater than zero and at most 30 days, and is `EXPIRED` once the clock reaches `expires_at`. Credential status is never client-supplied.

### 2.10. Validation Priority Order

When several checks apply to one request, they are evaluated in a fixed order. The order matters because it determines which error surfaces when more than one condition fails.

1. Authentication and user context — both headers present and the role declared. Refusal: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authority on the operation. Refusal: `ERR_INSUFFICIENT_PERMISSIONS`.
3. Existence. Path identifiers are resolved left to right, and a body foreign key must exist; the left-to-right order within a body is the order the endpoint's declared input list gives. Refusal by resource type: `ERR_AGENT_NOT_FOUND`, `ERR_CAPACITY_OWNER_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_CUSTOMER_ACCOUNT_NOT_FOUND`, `ERR_COMPLIANCE_DOCUMENT_NOT_FOUND`, `ERR_ESCROW_TRANSACTION_NOT_FOUND`.
4. Resource state. The target must be in the state the operation requires. Refusals come from the transition preconditions of §3 and include `ERR_LOAD_NOT_OPEN_FOR_AWARD`, `ERR_OFFER_NOT_OPEN`, `ERR_AGENT_NOT_ACTIVE`, `ERR_SETTLEMENT_NOT_DRAFT`, `ERR_TRIP_NOT_EN_ROUTE`, and `ERR_EQUIPMENT_NOT_IN_SERVICE`.
5. Ownership. Where the role model assigns ownership, the caller must own the resource it is acting on. Refusal: `ERR_UNAUTHORIZED`.
6. Business safety. The capacity owner's derived posture and the safety preconditions must hold. Refusals include `ERR_CAPACITY_OWNER_NOT_QUALIFIED`, `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`, `ERR_CAPACITY_OWNER_BUSY`, `ERR_EQUIPMENT_INSPECTION_OVERDUE`, `ERR_EQUIPMENT_INSPECTION_NOT_CURRENT`, `ERR_EQUIPMENT_NOT_IN_SERVICE`, `ERR_SAFETY_SCORE_BELOW_MINIMUM`, and `ERR_SAFETY_DOCUMENT_MISSING`.
7. Compliance. Territory, the live non-solicitation window, and the agent's settlement hold are the network's regulatory gate, evaluated after existence and state. Refusals include `ERR_TERRITORY_VIOLATION`, `ERR_CUSTOMER_NON_SOLICITATION_ACTIVE`, `ERR_AGENT_SETTLEMENT_HELD`, and `ERR_AGENT_SETTLEMENTS_OUTSTANDING`.
8. Business referential conflict. The capacity owner must not already hold a non-terminal load and the unit must not already be on a non-terminal trip. The refusals that are actually raised are `ERR_CAPACITY_OWNER_BUSY` — the single-commitment guard that catches the owner already holding a load — the turnaround-window conflict `ERR_EQUIPMENT_TURNAROUND_OVERLAP`, and `ERR_EQUIPMENT_ALREADY_ASSIGNED`. The names `ERR_CAPACITY_OWNER_ALREADY_ON_LOAD` and `ERR_OFFER_TIME_OVERLAP` are catalogued but reserved rather than raised.
9. Business constraint against the fleet. The awarded capacity owner must own at least one unit, the equipment type must fit the haul, and the offer ceiling must not be exceeded. Refusals include `ERR_EQUIPMENT_FLEET_EMPTY`, `ERR_EQUIPMENT_TYPE_MISMATCH`, `ERR_OFFER_EXCEEDS_PAY_CEILING`, and `ERR_TRIP_OWNER_MISMATCH`.
10. Fiscal invariants. Before any financial mutation: the allocation must conserve the union base, net owner-operator pay must not be negative, and no balance may go negative. Refusals include `ERR_SETTLEMENT_ALLOCATION_IMBALANCE`, `ERR_OWNER_OPERATOR_PAY_NEGATIVE`, `ERR_ESCROW_BALANCE_INSUFFICIENT`, `ERR_MAINTENANCE_BALANCE_INSUFFICIENT`, `ERR_ESCROW_ALREADY_MATCHED`, `ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN`, and `ERR_LOAD_ALREADY_SETTLED`.
11. Temporal windows. The offer must not have reached its expiry and the customer's exclusivity window must still be running. Refusals: `ERR_OFFER_EXPIRED` and `ERR_CUSTOMER_EXCLUSIVITY_EXPIRED`.

### 2.11. The Escrow, Maintenance and Advance Ledger

Every movement of a capacity owner's restricted money is a posted `EscrowTransaction`. The entry's direction is implied by its `transaction_type` and never by the sign of its
`amount_cents`, which is always a positive integer magnitude; a manually posted entry must carry
at least 1 cent, while a settlement pays out its whole charge schedule so a bucket that computes
to zero still posts its row, and such a zero-magnitude row moves neither restricted account. A forward entry carries `reverses_transaction_id` as null; a compensating entry sets it to the identifier of the entry it reverses, and when it is set the entry's own `transaction_type` must be the declared compensating type for its target's type. Deposits add and releases subtract on the escrow account; maintenance deposits add and maintenance withdrawals subtract on the maintenance account; an `ADVANCE` is an advance paid out to the driver and an `ADVANCE_REPAYMENT` is a recovery. An `ADVANCE` moves the escrow account negatively and an `ADVANCE_REPAYMENT` moves it positively, so an advance moved through the normal business path reduces the owner's escrow balance, while the two premium deductions — `OA_PREMIUM_DEDUCTION` and `INSURANCE_PREMIUM_DEDUCTION` — are recorded in the ledger but move neither restricted account at all, adding nothing to and subtracting nothing from either balance. An entry carries the instant it takes effect as `effective_at`, a `status` of `POSTED` or `REVERSED`, and the two derived balances the account held immediately after the entry was applied — `resulting_escrow_balance_cents` and `resulting_maintenance_balance_cents`. Because both balances are read off the whole ledger, those two reported figures are, for every entry of a capacity owner and at every read, that owner's current `escrow_balance_cents` and `maintenance_balance_cents`, not a historical snapshot frozen at the entry's own `effective_at`.

Two boundaries are absolute. The escrow account has a floor of zero: no mutation may drive `escrow_balance_cents` below zero, and a mutation that would do so is refused with `ERR_ESCROW_BALANCE_INSUFFICIENT`. The maintenance account has the same zero floor, guarded by `ERR_MAINTENANCE_BALANCE_INSUFFICIENT`. Additionally, the escrow balance must be at least `ESCROW_MIN_CENTS` — a floor of 100000 cents, the same floor the withholding schedule calls `ESCROW_BALANCE_FLOOR_CENTS` — whenever an operation requires the account to be at the floor, and the refusal there is also `ERR_ESCROW_BALANCE_INSUFFICIENT`.

Corrections are never deletions. Reversing an entry posts the declared compensating entry for the target's type and marks the original `REVERSED`; the compensating map is fixed — `ESCROW_DEPOSIT` against `ESCROW_RELEASE`, `MAINTENANCE_DEPOSIT` against `MAINTENANCE_WITHDRAWAL`, `ADVANCE` against `ADVANCE_REPAYMENT`, and the reverse of each of those four; and `OA_PREMIUM_DEDUCTION` and `INSURANCE_PREMIUM_DEDUCTION` each against `ESCROW_RELEASE`. A reversal whose target is already `REVERSED`, or whose type is not the declared compensating type for its target, is refused with `ERR_ESCROW_ALREADY_MATCHED`. Reversing a maintenance deposit restores the pre-mutation maintenance balance exactly.

A capacity owner's `outstanding_advance_cents` is a read-only aggregate derived from that owner's `ADVANCE` and `ADVANCE_REPAYMENT` entries, and an agent's own `outstanding_advance_cents` is the analogous read-only aggregate on its side of the ledger; settlement submission and settlement both depend on the capacity owner's figure, and settlement recomputes that figure. The advance balance is a running liability that the escrow balance does not mirror: posting an advance lowers the owner's escrow balance by the advanced amount while raising `outstanding_advance_cents` by the same amount, and a recovery — whether the advance entry is reversed or a repayment is posted by a settlement — adds the recovered amount back to the escrow balance and reduces the outstanding figure by the same amount. Movement of the escrow account can cross the floor in either direction, so `qualification_posture` is recomputed whenever that boundary is crossed.

---

## 3. Business Logic & Workflows

### 3.1. Enrolling Agents, Defending Territory and Keeping the Customer Book

An independent freight agency enters the network when a `NetworkAdministrator` enrolls it with an `agent_code` that must be unique across the whole network (a repeat is refused with `ERR_DUPLICATE_AGENT_CODE`), a `legal_name`, a two-letter `home_state`, a `commission_rate_pct` between zero and one inclusive, an ordered `territory_codes` list that must be non-empty and free of duplicates, and an optional `customer_ownership_days` that defaults to 365. The row lands in `PENDING_ENROLLMENT`. Its derived `settlement_hold` is recomputed to true, because the status is not yet `ACTIVE`; its `active_customer_count` and `awarded_load_count` both start at zero. Every load the agent will ever promote hangs off its `agent_id`.

Activation is the enrollment gate rather than a territory arbitration. Moving from
`PENDING_ENROLLMENT` to `ACTIVE` requires the row to still be in `PENDING_ENROLLMENT` — otherwise
the refusal is `ERR_AGENT_NOT_ENROLLABLE` — and requires the `territory_codes` list to be non-empty
(else `ERR_AGENT_TERRITORY_EMPTY`). No other agent's holdings are consulted, so an activation
that overlaps a state a rival live agent already lists succeeds, and the precedence rule from
§2.5 governs only how such an overlap is read. On success the status becomes `ACTIVE`, `settlement_hold` is recomputed to false, and `board_required` is recomputed on every load this agent owns — true for each load still in `POSTED`.

Suspension is a board-clearing event. Moving from `ACTIVE` to `SUSPENDED` requires the row to be `ACTIVE` (else `ERR_AGENT_NOT_ACTIVE`) and a present, non-empty `reason_code` in the body (else `ERR_INVALID_REQUEST`). The status becomes `SUSPENDED` and `settlement_hold` becomes true, which is what stops the agent's money: a held agent may neither promote loads nor have settlements paid, and both are refused with `ERR_AGENT_SETTLEMENT_HELD`. At cascade depth one, every load of this agent whose status is `POSTED` becomes `CANCELLED` and each of those loads' offers that were `OPEN` become `WITHDRAWN`. Then `board_required` is recomputed to false on every load the agent owns. Reinstatement from `SUSPENDED` back to `ACTIVE` requires the row to be `SUSPENDED` (else `ERR_AGENT_NOT_SUSPENDED`), and it recomputes `settlement_hold` and `board_required` on the same sets in the opposite direction.

Termination is the deepest cascade in the agent lifecycle. The `NetworkAdministrator` may terminate from `PENDING_ENROLLMENT`, `ACTIVE`, or `SUSPENDED`; a row already `TERMINATED` is refused with `ERR_AGENT_ALREADY_TERMINATED`, and any agent still carrying a settlement in `PENDING_APPROVAL` or `APPROVED` blocks the operation with `ERR_AGENT_SETTLEMENTS_OUTSTANDING`. The status becomes `TERMINATED` and `settlement_hold` becomes true. At depth one, the same `POSTED` loads are cancelled and their `OPEN` offers withdrawn. At depth two, every customer account of this agent whose `exclusivity_status` is `OWNED_EXCLUSIVE` receives `released_reason` `AGENT_TERMINATED`, which recomputes its `exclusivity_status` to `RELEASED` and decrements the agent's `active_customer_count`. At depth three, any such released account whose `customer_ref` matches the `customer_ref` of an open load promoted
by another agent inside the non-solicitation radius of 90 days causes that load's next award attempt to be refused with `ERR_NON_SOLICITATION_BREACH` — the network does not let a terminated book walk out of the door and back in through a competitor.

Customer accounts themselves are registered under an agent through a payload carrying the `agent_id`, a `customer_ref` unique within that agent (a repeat is refused with `ERR_DUPLICATE_CUSTOMER_REF`), a `shipper_name`, a `first_booked_at`, and an optional `released_reason` that is null by default and otherwise takes one of `NON_SOLICITATION_BREACH`, `AGENT_TERMINATED`, or `CUSTOMER_REQUEST`. The derived `ownership_expires_at` is the `first_booked_at` advanced by the owning agent's `customer_ownership_days`, and the derived `exclusivity_status` starts `OWNED_EXCLUSIVE` and flips to `OPEN_SHARED` at or after that instant, with `RELEASED` overriding both when a reason is set. Registering the account recomputes the owning agent's `active_customer_count`, and that count only includes accounts evaluated as `OWNED_EXCLUSIVE` against the current clock.

### 3.2. Qualifying Business Capacity Owners and Their Fleets

A business capacity owner enters when a `NetworkAdministrator` enrolls one with an `owner_code` unique across the network (a repeat is refused with `ERR_DUPLICATE_OWNER_CODE`), a `legal_name`, a `home_terminal_city`, a `revenue_split_pct` between zero and one inclusive, an optional `oa_enrolled` that defaults to false, and an optional `liability_insurance_deductible_cents` that defaults to 250000. The row lands in `PENDING_QUALIFICATION` with `escrow_balance_cents` and `maintenance_balance_cents` both zero and `safety_score` initialized to 100. Its `qualification_posture` is recomputed and comes out `QUALIFICATION_RESTRICTED`, because an empty escrow account sits below the floor. An administrative test-driving capability can also create a fresh capacity owner row that carries the same identified attributes as a source row — `revenue_split_pct`, `oa_enrolled`, `liability_insurance_deductible_cents`, and `home_terminal_city` copied verbatim, with `owner_code` and `legal_name` given a distinct suffix so network-wide uniqueness still holds — starting `PENDING_QUALIFICATION` with zero balances, a safety score of 100, and no fleet, credential, trip or settlement children.

Credentials are filed by a `SafetyReviewer` against a capacity owner with a `document_type`, a `document_number`, an `issued_at` and an `expires_at` that must be strictly after the issued date. The six document types the network tracks are `CDL`, `MEDICAL_CARD`, `MVR_REPORT`, `DRUG_TEST`, `OA_ENROLLMENT`, and `LIABILITY_INSURANCE`. The credential's status is derived against the logical clock exactly as §2.9 describes and is
never taken from the caller; a freshly filed credential has not yet been re-verified, so an
already-lapsed `expires_at` on a new row does not by itself freeze or penalize the owner until a
verification observes it (§3.3). Filing it recomputes the host capacity owner's `qualification_posture` and its `qualified_until`, the latter being the earliest `expires_at` among that owner's credentials that are not `REJECTED`, and null when the owner has none. Re-evaluating a credential later with a `verified_at` recomputes its status, recomputes the host owner's `safety_score` from the current expired count, and recomputes the posture.

Fleet units are added by a `SafetyReviewer` or `NetworkAdministrator` with the owning `capacity_owner_id`, a `unit_number` unique within that owner (a repeat is refused with `ERR_DUPLICATE_UNIT_NUMBER`), an `equipment_type`, a `model_year` between 1980 and 2030 inclusive, and an `inspection_due_at`. The five equipment types are `TRACTOR`, `STRAIGHT_TRUCK`, `VAN_TRAILER`, `REEFER_TRAILER`, and `FLATBED_TRAILER`; only `TRACTOR` and `STRAIGHT_TRUCK` are power units capable of hauling, and a haul attempted with a trailer type is refused with `ERR_EQUIPMENT_TYPE_MISMATCH`. A new unit lands in `PENDING_INSPECTION` with a null `inspection_passed_at`, and adding it recomputes the owning capacity owner's `qualification_posture` — because a unit in `PENDING_INSPECTION` is one of the restriction inputs.

Recording an inspection is the only path a unit has back into service. The payload carries an `inspected_at` that is required, a `result`, and an `inspector_certificate`
that must be present and non-empty only on the path that returns a unit to service from
`PENDING_INSPECTION` or `OUT_OF_SERVICE`; a result recorded against a unit that is already
`IN_SERVICE` need not carry one. From `PENDING_INSPECTION` or from `OUT_OF_SERVICE`, a passing result moves the unit to `IN_SERVICE` after checking that the `inspected_at` is strictly before `inspection_due_at` and that the owning capacity owner's status is `PENDING_QUALIFICATION` or `QUALIFIED`. From `IN_SERVICE`, a failing result moves the unit backwards to `PENDING_INSPECTION`, aborting any non-terminal trip on that unit and penalizing the owner's safety score by 15 for each one; a *passing* result recorded on a unit that is already `IN_SERVICE` is not an error and not a transition — it refreshes `inspection_passed_at` and leaves the status where it is. A unit already `RETIRED` refuses any inspection with `ERR_EQUIPMENT_ALREADY_RETIRED`, a result other than `PASS` on a path that demands one is refused with `ERR_EQUIPMENT_INSPECTION_FAILED`, and a late `inspected_at` is refused with `ERR_EQUIPMENT_INSPECTION_OVERDUE`.

### 3.3. Qualification Posture, Safety Scoring and the Out-of-Service Cascades

A capacity owner's `qualification_posture` is a read-only verdict derived over the owner and all of its children, and it is the single most load-bearing derived field in the network. It is `QUALIFICATION_FROZEN` when the owner's status is `DECERTIFIED` or when any of its
credentials has been observed, at a verification, to have lapsed — a credential whose derived
status is `EXPIRED` counts against the owner only once a verification has looked at it, so an
expired date on a row no verification has observed does not freeze the account. It is
`QUALIFICATION_RESTRICTED` when the status is `OUT_OF_SERVICE`, or the safety score has fallen
below the minimum of 70, or the escrow balance has dropped below the floor of 100000 cents, or at
least one fleet unit sits in `PENDING_INSPECTION` or has been taken off the road by an explicit
fleet action — a unit the reviewer places out of service, or one whose inspection fails; a unit
that a cascade merely moved to `OUT_OF_SERVICE` because its owner went out of service is not by
itself a restriction input once the owner is reinstated. Otherwise it is `QUALIFIED_CLEAR`. Two postures gate operations directly: a capacity owner that is not `QUALIFIED_CLEAR` may not be awarded a load, may not cover one, and may not dispatch a trip, all refused with `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`; and a `QUALIFICATION_FROZEN` owner may not have a settlement submitted against it, refused with `ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN`.

The safety score is a recomputed function of current child state, never an accumulator. It starts at a base of 100, subtracts 15 for each of the owner's trips whose status is `ABORTED`, and subtracts 5 for each of the owner's credentials whose lapse a verification has observed — the
count is of credentials seen to expire, not of every credential whose `expires_at` has passed —
floored at 0 and capped at the base. Because it is a function of the current expired count rather than a running decrement, re-running an expiry verification job against a document that is still expired does not charge it twice. The score is recomputed when a trip aborts, when a credential is verified, and on any read of the capacity owner.

Qualification itself requires a great deal at once. Moving from `PENDING_QUALIFICATION` to `QUALIFIED` requires the row to still be `PENDING_QUALIFICATION` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIABLE`); requires every one of the six document types to have at least one credential that is not `REJECTED` and whose `expires_at` is strictly after the clock (else `ERR_SAFETY_DOCUMENT_MISSING`); requires the escrow balance to be at or above the floor (else `ERR_ESCROW_BALANCE_INSUFFICIENT`); requires the safety score to be at or above the minimum of 70 (else `ERR_SAFETY_SCORE_BELOW_MINIMUM`); and requires at least one fleet unit already in `IN_SERVICE` (else `ERR_EQUIPMENT_NOT_QUALIFIED`, which is also the refusal when the owner holds no equipment at all and an award cannot be covered, there carrying `ERR_EQUIPMENT_FLEET_EMPTY`). On success the posture is recomputed to `QUALIFIED_CLEAR` when every restriction input is clear, and `qualified_until` is recomputed to the earliest non-rejected credential expiry. This is one of the four version-guarded writes: the caller must supply `expected_network_capacity_owner_version` matching the owner's current version, and a stale value is refused with `ERR_STALE_VERSION`.

Placing a qualified owner out of service — the `QUALIFIED` to `OUT_OF_SERVICE` move — requires the row to be `QUALIFIED` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED`) and a present, non-empty `reason_code` (else `ERR_INVALID_REQUEST`). The posture immediately becomes `QUALIFICATION_RESTRICTED`. At depth one, every unit this owner has that is `IN_SERVICE` becomes `OUT_OF_SERVICE`. At depth two, every trip of this owner that is `DISPATCH_PENDING` or `EN_ROUTE` becomes `ABORTED` and the safety score drops by 15 per aborted trip. At depth three, every load whose `awarded_capacity_owner_id` points at this owner and whose status is `AWARDED` returns to `POSTED` with the awarded owner cleared, and each such load's accepted offer becomes `DECLINED`. Reinstatement back to `QUALIFIED` requires the row to be `OUT_OF_SERVICE` (else `ERR_CAPACITY_OWNER_NOT_OUT_OF_SERVICE`), a safety score at or above the minimum (else `ERR_SAFETY_SCORE_BELOW_MINIMUM`), an escrow balance at or above the floor (else `ERR_ESCROW_BALANCE_INSUFFICIENT`), and no unit of this owner carrying an `OVERDUE` inspection status (else `ERR_EQUIPMENT_INSPECTION_OVERDUE`).

Decertification is terminal and freezes the account. From `PENDING_QUALIFICATION`, `QUALIFIED`, or `OUT_OF_SERVICE`, the operation requires the escrow balance to be at or above `MIN_ESCROW_FOR_DECERT_CENTS`, a decertification floor of 25000 cents — otherwise `ERR_ESCROW_BALANCE_INSUFFICIENT` — and an owner already `DECERTIFIED` is refused with `ERR_CAPACITY_OWNER_ALREADY_DECERTIFIED`. The status becomes `DECERTIFIED` and the posture `QUALIFICATION_FROZEN`. From `QUALIFIED` and from `OUT_OF_SERVICE` the cascade matches the out-of-service cascade and then goes further: `IN_SERVICE` units become `OUT_OF_SERVICE`, `DISPATCH_PENDING` and `EN_ROUTE` trips become `ABORTED`, and loads whose status is `AWARDED` or `COVERED` return to `POSTED` with the awarded owner cleared.

Individual units can also be taken off the road without touching the owner's status. Placing an `IN_SERVICE` unit out of service requires that status (else `ERR_EQUIPMENT_NOT_IN_SERVICE`) and a present, non-empty `reason_code` (else `ERR_INVALID_REQUEST`); it aborts every `DISPATCH_PENDING` or `EN_ROUTE` trip on that unit, penalizing the owner's safety score by 15 per aborted trip, and recomputes the posture to `QUALIFICATION_RESTRICTED`. Retirement, which only a `NetworkAdministrator` performs, requires the unit not already be `RETIRED` (else `ERR_EQUIPMENT_ALREADY_RETIRED`); retiring an `IN_SERVICE` unit additionally requires that no trip on that unit be `DISPATCH_PENDING` or `EN_ROUTE` (else `ERR_EQUIPMENT_HAS_ACTIVE_TRIP`), while retiring a `PENDING_INSPECTION` unit requires instead that no `OPEN` offer reference a load whose awarded owner is this unit's owner and whose `origin_state` lies in this unit's owner's territory (else `ERR_INVALID_REQUEST`). Either retirement aborts any non-terminal trip on the unit and recomputes the posture.

### 3.4. Promoting Loads onto the Board and Running the Offer Book

A `FreightAgent` promotes a load with a payload carrying the owning `agent_id`, the `customer_ref` the load books under — recorded verbatim and never validated to name an existing account — an `origin_state` and a `destination_state`, a `linehaul_revenue_cents` greater than zero, an optional `fuel_surcharge_cents` defaulting to zero, an optional `accessorial_revenue_cents` defaulting to zero, and a `dispatched_miles` greater than zero. The load lands in `POSTED` with a null awarded owner and a recomputed `board_required`. Promotion is evaluated in the §2.10 order: the origin state must be inside the promoting agent's territory (else `ERR_TERRITORY_VIOLATION`); no other agent's `OWNED_EXCLUSIVE` account may carry the same `customer_ref` (else `ERR_CUSTOMER_NON_SOLICITATION_ACTIVE`) — the released-account, non-solicitation-radius gate is not applied at promotion but at award; and the promoting agent's `settlement_hold` must be false (else `ERR_AGENT_SETTLEMENT_HELD`), which is likewise the refusal while the agent is not in a live status.

A posted load can be taken down by its own agent through a cancellation carrying a `reason_code`; the load must still be `POSTED` (else `ERR_LOAD_NOT_CANCELLABLE`) and the caller must own it (else `ERR_UNAUTHORIZED`). Cancellation flips the load to `CANCELLED` and withdraws every `OPEN` offer on it. The same outcome occurs without a caller when the owning agent later suspends or terminates: the `POSTED` load becomes `CANCELLED`, its `OPEN` offers become `WITHDRAWN`, and its `board_required` is recomputed to false.

Offers are how a capacity owner bids for that load. Posting an offer requires the load's `id`, the bidding `capacity_owner_id`, an `offered_pay_cents` greater than zero, an `offered_at`, and the version guard `expected_network_load_version`. The offer lands `OPEN`, recomputes `selected_rank` for every open offer on the load, and re-derives the `owner_pay_ceiling_cents` and `expires_at` described in §2.4. An offer whose `offered_pay_cents` exceeds the ceiling is refused with `ERR_OFFER_EXCEEDS_PAY_CEILING`, and an offer whose `expected_network_load_version` no longer matches the load's version is refused with `ERR_STALE_VERSION`. The posting party here is the agent side of the house; the offer's own acceptance and refusal rights sit with the capacity owner it names, and an offer directed to one capacity owner cannot be accepted or declined by another (both refusals are `ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER`).

An offer's life is short and its endings are all rank-disturbing. A capacity owner declines its own open offer with a `declined_at`, which is refused if the offer is not `OPEN` (`ERR_OFFER_NOT_OPEN`) and otherwise moves it to `DECLINED` and re-derives the ranks of the remaining open offers. The promoting agent withdraws an offer with a `reason_code`, refused if the offer is not `OPEN` (`ERR_OFFER_NOT_OPEN`) or if the caller does not own the parent load (`ERR_UNAUTHORIZED`), and the move to `WITHDRAWN` re-derives ranks in exactly the same way. An offer whose time-to-live has elapsed moves to `EXPIRED` on the clock alone, with no caller, re-deriving ranks as well. In all three cases the load is not touched beyond the rank re-derivation.

### 3.5. Awarding, Covering and Running the Haul

Awarding happens when a capacity owner accepts an offer, supplying the `accepted_at` instant at which the board decision is taken. Acceptance requires that the load be `POSTED` with `board_required` still true (else `ERR_LOAD_NOT_OPEN_FOR_AWARD`); that the accepting capacity owner is the offer's own `capacity_owner_id` (else `ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER`); that the offer still be `OPEN` (else `ERR_OFFER_NOT_OPEN`); that the clock not have reached the offer's `expires_at` (else `ERR_OFFER_EXPIRED`); that the offer be the top-ranked open offer on its load by `selected_rank` (else `ERR_OFFER_NOT_TOP_RANKED`); that the capacity owner be `QUALIFIED_CLEAR` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`) and its status `QUALIFIED` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED`); that no other load already in `AWARDED`, `COVERED`, or `IN_TRANSIT` points its `awarded_capacity_owner_id` at this same owner, since a truck can only be in one place (else `ERR_CAPACITY_OWNER_BUSY`); and that the load's `origin_state` be inside the owning agent's territory (else `ERR_TERRITORY_VIOLATION`). A separation-of-duties-adjacent conflict on the same slot — an offer whose haul window overlaps a window in which the capacity owner is already committed — is catalogued as `ERR_OFFER_TIME_OVERLAP` but is reserved rather than raised: the network detects the conflict through the single-commitment rule above and refuses it with `ERR_CAPACITY_OWNER_BUSY`.

On success the offer becomes `ACCEPTED`, the load's `awarded_capacity_owner_id` is set to the accepting owner, the load becomes `AWARDED`, and the cascade runs: at depth one every other open offer on that load becomes `DECLINED` with its rank re-derived to null; at depth two the owning agent's `awarded_load_count` increments by one; at depth three the agent's `settlement_hold` is recomputed, which normally leaves it unchanged unless an advance ceiling was crossed in the meantime. A load can also return to the board without an acceptance — when its awarded capacity owner goes out of service or is decertified, or when a trip aborts, the load becomes `POSTED` with the awarded owner cleared and the previously accepted offer becomes `DECLINED`, which re-derives the ranks of everything still open.

Covering the load is the next step: a `CapacityOwnerOperator` creates a trip carrying the `load_id`, a `capacity_owner_id` that must
equal the load's awarded owner (else `ERR_TRIP_OWNER_MISMATCH`), an `equipment_id` that must
belong to that same owner (else `ERR_EQUIPMENT_NOT_FOUND`), a `departed_at`, and a `deadline_at` —
every one of the four required, a missing instant being refused as malformed. The load must be `AWARDED` (else `ERR_LOAD_NOT_AWARDED`); the owner must be `QUALIFIED_CLEAR` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`); the named unit must have an `inspection_status` of `CURRENT` (else `ERR_EQUIPMENT_INSPECTION_NOT_CURRENT`) and a status of `IN_SERVICE` (else `ERR_EQUIPMENT_NOT_IN_SERVICE`); the unit must be a power unit, meaning a `TRACTOR` or a `STRAIGHT_TRUCK` (else `ERR_EQUIPMENT_TYPE_MISMATCH`); and no trip referencing that unit may already be `DISPATCH_PENDING` or `EN_ROUTE` (else `ERR_EQUIPMENT_ALREADY_ASSIGNED`), with a departure that falls inside the mandatory two-hour turnaround buffer after the unit's previous delivery refused as `ERR_EQUIPMENT_TURNAROUND_OVERLAP`. A deadline at or before the departure instant is refused outright with `ERR_INVALID_TRIP_WINDOW`. The new trip lands in `DISPATCH_PENDING` and the load moves to `COVERED` with its awarded owner still set.

Dispatch is a re-check rather than a formality. Moving a load from `COVERED` to `IN_TRANSIT` requires the caller to supply a well-formed
`dispatched_at` instant, which is validated for shape but is not used to stamp any field — the
trip's `departed_at` was already fixed when it was covered — and requires the load to still be
`COVERED` (else `ERR_LOAD_NOT_COVERED`), the trip to be `DISPATCH_PENDING` (else `ERR_TRIP_NOT_DISPATCH_PENDING`), and the capacity owner to be `QUALIFIED_CLEAR` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`) — this is the point at which a posture that degraded between covering and dispatch is caught. The trip becomes `EN_ROUTE` and the load becomes `IN_TRANSIT`. A unit whose inspection has gone overdue in the same interval is refused here with `ERR_EQUIPMENT_INSPECTION_NOT_CURRENT`.

Completion closes the haul and stamps the derived facts. The payload carries an `actual_miles` greater than zero and a `proof_of_delivery_code` that must be present and non-empty, both refusals being `ERR_INVALID_REQUEST`; the load must be `IN_TRANSIT` (else `ERR_LOAD_NOT_IN_TRANSIT`) and the trip `EN_ROUTE` (else `ERR_TRIP_NOT_EN_ROUTE`). On success `delivered_at` is stamped from the logical clock, `actual_miles` is recorded, the trip becomes `DELIVERED`, and the load becomes `DELIVERED`. Lateness is permitted: a delivery at or before the trip's `deadline_at` records `on_time` true, with exact equality counting as on time, and anything later simply records `on_time` false without rejection. The completion also derives `maintenance_reserve_cents` from the miles actually run — the miles divided by the 1000-mile reserve chunk, rounded up, multiplied by the 1200-cent reserve per chunk — and withholds that figure from owner-operator pay when the settlement computes (see §3.8).

Aborting ends a haul early. From `DISPATCH_PENDING` or `EN_ROUTE` — anything else is refused with `ERR_TRIP_NOT_ABORTABLE` — the operator may abort with a `reason_code`. The trip becomes `ABORTED`; at depth one the capacity owner's safety score drops by 15 and the posture is recomputed; at depth two the load returns to `POSTED` with its awarded owner cleared; at depth three the previously accepted offer becomes `DECLINED` and the remaining open offers have their ranks re-derived. The same cascade fires without a caller when the hauling owner is placed out of service or decertified, or when the assigned unit leaves `IN_SERVICE`.

### 3.6. Proof of Delivery and the Settlement Approval Chain

A settlement cannot be submitted until the trip has been signed off. A `SettlementOperator` verifies the proof of delivery with a `pod_verified` flag that must be true — the trip must be `DELIVERED` (else `ERR_TRIP_NOT_DELIVERED`), and either a missing trip `proof_of_delivery_code` or a `pod_verified` that is not true is refused with `ERR_POD_MISSING`. The flag must be the literal boolean `true`, and a trip that carries no `proof_of_delivery_code`
is refused before the flag is read. On success the trip becomes `COMPLETED`, which is the state
that makes a final settlement admissible, and its `maintenance_reserve_cents` is re-derived from
`actual_miles` as described in §3.5.

A settlement is created in `DRAFT` for a delivered or completed trip — the missile payload is simply the `trip_id` and the `settlement_method` — and at creation every derived allocation field is computed under the selected variant and `variant_delta_cents` is recomputed. The `settlement_method` is `PROVISIONAL` or `FINAL` and it selects which pairing of split variants in §3.7 is evaluated: `PROVISIONAL` is admissible only while the referenced trip is `COMPLETED`, and `FINAL` is admissible only once the trip's proof of delivery is on file and the load is `DELIVERED` or `SETTLED`. A computed split can also be inspected without being persisted, through an evaluation that returns the settled-shaped figures for `agent_share_cents`, `owner_operator_share_cents`, `company_share_cents`, `oa_premium_cents`, `insurance_premium_cents`, `escrow_withholding_cents`, `maintenance_withholding_cents`, `advance_repayment_cents`, `net_owner_operator_pay_cents`, `net_agent_pay_cents`, and `settled_total_cents`.

Submission moves the settlement from `DRAFT` to `PENDING_APPROVAL` and is guarded on several fronts at once. The settlement must be `DRAFT` (else `ERR_SETTLEMENT_NOT_DRAFT`); the referenced trip must be `DELIVERED` or `COMPLETED` (else `ERR_TRIP_NOT_SETTLEABLE`); a `FINAL` submission additionally requires the trip to be `COMPLETED` (else `ERR_POD_MISSING`); the owning agent's `settlement_hold` must be false (else `ERR_AGENT_SETTLEMENT_HELD`); the capacity owner's posture must not be `QUALIFICATION_FROZEN` (else `ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN`); and the caller must supply `expected_network_agent_version` matching the owning agent's current version, a mismatch being refused with `ERR_STALE_VERSION`. Submission recomputes every derived allocation field under the selected method before the settlement advances.

Approval is a `NetworkAdministrator` action and is deliberately separated from submission. The settlement must be `PENDING_APPROVAL` (else `ERR_SETTLEMENT_NOT_PENDING_APPROVAL`) and the approving identity must differ from the identity that submitted it, a violation being refused with `ERR_SEGREGATION_OF_DUTIES`. Three fiscal guards ride along: the `settled_total_cents` must equal the sum of `linehaul_revenue_allocated_cents`, `fuel_surcharge_allocated_cents`, and `accessorial_allocated_cents` exactly (else `ERR_SETTLEMENT_ALLOCATION_IMBALANCE`); `net_owner_operator_pay_cents` must not be negative (else `ERR_OWNER_OPERATOR_PAY_NEGATIVE`); and when the settlement's method is `FINAL` its `variant_delta_cents` must be zero, meaning the provisional and final splits for the same trip have been reconciled (else `ERR_SETTLEMENT_VARIANT_DIVERGENCE`). A rejected settlement returns to `DRAFT` with every derived allocation field reset to null pending
recomputation and the recorded submitting identity cleared so the draft may be resubmitted by
anyone, and rejection shares the segregation-of-duties check.

Settling is the final step and it moves real money. It requires the settlement to be `APPROVED` (else `ERR_SETTLEMENT_NOT_APPROVED`); requires `expected_network_load_version` to match the parent load's current version (else `ERR_STALE_VERSION`); and, where the load-side preconditions are evaluated, requires the load to be `DELIVERED` or `SETTLED` (else `ERR_LOAD_NOT_SETTLEABLE`), the trip to be `COMPLETED` (else `ERR_TRIP_NOT_COMPLETED`), and the settlement's method to be `FINAL` (else `ERR_SETTLEMENT_METHOD_MISMATCH`), and refuses a load that is already closed with `ERR_LOAD_ALREADY_SETTLED`. A held agent is refused here too with `ERR_AGENT_SETTLEMENT_HELD`, and the reserved split is
recomputed before the money moves. On success the settlement becomes `SETTLED`, the load becomes
`SETTLED`, and the ledger work runs: one ledger row per bucket is posted for the capacity owner —
an occupational-accident deduction only when the owner is enrolled, an insurance deduction, a
maintenance deposit, an escrow deposit, and an advance-repayment row — five rows at most, a bucket
that computes to zero still posting its row. The capacity owner's and agent's advance balances and postures are recomputed afterwards. A draft that was never submitted can instead be voided — it must be `DRAFT` (else `ERR_SETTLEMENT_NOT_DRAFT`) — moving it to its terminal `VOID` state; because no transaction was ever posted for a draft, voiding moves no escrow or maintenance balances. Approval is the only settlement operation that records the submitting identity; it does so specifically so that the segregation-of-duties comparison has something to compare against.

### 3.7. Computing the Three-Way Settlement Split

Every derived allocation figure on a settlement is produced by an eight-step waterfall. The evaluation order is pinned: a later step may read the value an earlier step wrote, but never the reverse.

Step one copies the load's billed components onto the settlement. `linehaul_revenue_allocated_cents` is the load's `linehaul_revenue_cents`, `fuel_surcharge_allocated_cents` is the load's `fuel_surcharge_cents`, and `accessorial_allocated_cents` is the load's `accessorial_revenue_cents`. No load in any other status participates: only the single load the settlement's trip belongs to.

Step two forms two aggregates. The union base is the linehaul plus the fuel surcharge plus the accessorial revenue. The `commissionable_base_cents` is the linehaul plus the accessorial revenue — the fuel surcharge is excluded from it, deliberately, because fuel is not commissioned.

Step three computes the agent's side: `agent_share_cents` is the `commissionable_base_cents` multiplied by the agent's `commission_rate_pct`, rounded half up.

Step four computes the owner-operator's gross side: `owner_operator_share_cents` is the linehaul plus the fuel surcharge, multiplied by the capacity owner's `revenue_split_pct`, rounded half up. The owner-operator base therefore also excludes accessorials, but unlike the agent it does include the fuel surcharge.

Step five computes `company_share_cents` as the union base minus the agent share minus the owner-operator share. The company bucket stands last in the waterfall and therefore absorbs every rounding remainder produced upstream.

Step six reads only step four's output as the derived base for the provisional variant's percentage withholdings, and derives from step one's figures the four bases the final variant needs: the occupational-accident base is the linehaul plus the accessorial revenue; the insurance base is the linehaul plus the fuel surcharge; the escrow base is the linehaul plus the accessorial revenue; and the advance-repayment base is the linehaul alone.

Step seven computes the withholdings, and every one of them is a ceiling so that no bucket's remainder is lost. When the capacity owner is not enrolled in the occupational-accident program, `oa_premium_cents` is zero; otherwise it is the occupational-accident base multiplied by the occupational-accident premium rate of 1.50%, rounded up. `insurance_premium_cents` is the insurance base multiplied by the insurance premium rate of 2.10%, rounded up. `maintenance_withholding_cents` equals the trip's `maintenance_reserve_cents`. `escrow_withholding_cents` is the escrow base multiplied by the escrow withholding rate of 5.00%, rounded up — subject to the floor-first rule in §3.8. An advance cap is the advance-repayment base multiplied by the advance repayment rate of 10.00%, rounded up, and `advance_repayment_cents` is the smaller of the capacity owner's `outstanding_advance_cents` and that cap. Finally, if the insurance premium would exceed the owner-operator share, it is reduced to that share. Order within this step is immaterial, because every input is a step-six base.

Step eight closes the arithmetic. `net_owner_operator_pay_cents` is the owner-operator share minus the occupational-accident premium, the insurance premium, the maintenance withholding, the escrow withholding, and the advance repayment. `net_agent_pay_cents` equals the agent share — the recovered advance is the capacity owner's liability and the agent's net pay carries no advance deduction. `settled_total_cents` is the agent share plus the owner-operator share plus the company share.

The invariant on top of all of it is a conserved quantity: `settled_total_cents` must equal the linehaul plus the fuel surcharge plus the accessorial revenue *exactly*, for both variants. The company bucket absorbing the rounding remainder is what makes that hold by construction; an implementation that rounds the total independently will drift and will be caught by the allocation-imbalance guard at approval.

The two variants differ in exactly one place — the base the two percentage premiums are computed on. Under `PROVISIONAL`, step seven computes the occupational-accident premium and the insurance premium from the owner-operator base, that is from step four's `owner_share_cents`; under `FINAL`, it computes them from the separate bases step six derived — linehaul plus accessorial for the occupational-accident premium, and linehaul plus fuel surcharge for the insurance premium. The escrow withholding, the maintenance withholding, and the advance repayment are identical under both variants, as are all three split shares and the conserved total. Only `net_owner_operator_pay_cents` and the two premium fields move, and a provider whose ceiling arithmetic matches between the two bases will see them agree. The difference between the two variants for a given trip is what `variant_delta_cents` records: once both a provisional and a final split have been computed for the trip, it is the final variant's `net_owner_operator_pay_cents` minus the provisional variant's; before then it is zero.

### 3.8. Withholdings, Advances and the Escrow Accounts

The occupational-accident premium is tiered by safety performance, and the tier boundary is inclusive at the top. A capacity owner who is not enrolled pays nothing at all, regardless of score, and no occupational-accident deduction entry is posted for it at settle; an enrolled owner pays its base multiplied by a rate chosen by the safety score — a score of 95 or above takes 1.50%, a score of exactly 94 takes 1.75%, a score of exactly 93 takes 1.75%, and a score of 92 or below takes 2.00%. The boundary at 95 is the one that catches implementations: 95 takes the standard rate, 94 takes the elevated rate. As §3.7 says, "base" means the owner-operator share under the provisional variant and the linehaul plus accessorial under the final variant, and the premium is rounded up in both.

The insurance premium is a straight percentage of its base — 2.10% of the owner-operator share under the provisional variant, or of the linehaul plus fuel surcharge under the final variant — rounded up, and clamped so that it never exceeds the owner-operator share itself. The maintenance withholding is not a percentage at all: it is exactly the reserve the trip already derived from the miles actually run, being the actual miles divided by the 1000-mile chunk, rounded up, multiplied by 1200 cents per chunk. The reserve is derived at completion and again finalized at proof-of-delivery verification, and the settlement simply carries it.

The escrow withholding is the most contrived of the four, because it is sized against a floor before a target. Its own target for the settlement is the escrow base — linehaul plus accessorial — multiplied by the withholding rate of 5.00%, rounded up. If the capacity owner's escrow balance already stands at or above the floor of 100000 cents, the withholding is zero: a solvent driver is not asked to contribute again. Otherwise the withholding is the smaller of that target and the larger of two deficits measured against the current balance — the deficit up to the floor, and a deficit computed against a higher target balance of 200000 cents. The pinned reading is floor-first: an under-floor owner fills the floor bucket first and contributes nothing toward the higher target.

Advances are the operator's cash position, and they are recovered from pay. Posting an advance or a repayment is an ordinary ledger entry carrying the owning `capacity_owner_id`, a `transaction_type`, a positive `amount_cents`, and an `effective_at`; posting it recomputes the owner's escrow and maintenance balances, recomputes the owner's `outstanding_advance_cents` when the type is an advance or a repayment, and recomputes the qualification posture when the escrow floor has been crossed in either direction. A test-driving capability collapses the whole advance flow into one call, taking a `capacity_owner_id`, an `amount_cents`, and an `effective_at`, posting the advance mark as a `POSTED` ledger row, and reporting back the new entry's identifier
alongside the resulting escrow balance and the resulting outstanding advance; an advance that
would drive the escrow account below zero is refused with `ERR_ESCROW_BALANCE_INSUFFICIENT`. Settlement recovery is capped: the recovery on any one settlement is the smaller of the outstanding advance and 10.00% of the linehaul, rounded up, so a driver is never wiped out by a single settlement.

### 3.9. Commission Reconciliation and the Per-Load Fee Schedule

An agent's own book is reconciled chronologically through a settlement summary carrying an optional `order` selector and reporting a gross commission figure, a settlement count, and a period label. The counted rows are that agent's settlements whose status is `APPROVED` or `SETTLED`, each contributing its `agent_share_cents` as gross. Two rules govern the series. First, the ordering key is the referenced trip's `delivered_at` ascending, tie-broken by the settlement's `created_at` ascending — so a settlement approved late for an early trip lands at its delivery position in the running series rather than at the end of the ledger. Second, only the single settlement row with the highest delivery-and-creation key per trip counts; earlier rows for the same trip are superseded revisions and contribute nothing. A final row supersedes the provisional row for the trip it settles. The same readings under a creation-date ordering net to the same total but diverge in the running series after the first out-of-order approval.

The network also bills each agent a per-load settlement fee against a rolling calendar month, and the month window is half-open. The window anchors at the first instant of the calendar month containing the logical clock, at 00:00:00Z, and ends one calendar month later; a load created exactly at that end instant belongs to the next month. An eligible load for the count is any load of that agent whose status is `AWARDED`, `COVERED`, `IN_TRANSIT`, `DELIVERED`, or `SETTLED`, with a `created_at` at or after the window start and strictly before the window end; a stable enumeration of them orders by `created_at` ascending. The per-load rate is banded by the eligible count — up to and including 50 eligible loads bills 4500 cents each, up to and including 150 bills 4000 cents each, and more than 150 bills 3500 cents each — with one deliberate exception at the bottom: a month with no eligible loads at all still bills the base rate of 5000 cents, because the schedule is never zero. The period fee is the eligible count multiplied by that one band rate, and the reported effective per-load fee is the period fee divided by the eligible count with the quotient floored to a whole cent — the aggregate-versus-marginal boundary of the whole calculation, and undefined arithmetic when the count is zero, which the empty-set floor exists to avoid. A second reading of the same schedule charges each band cumulatively and sums the fill: sixty eligible loads bills fifty at 5000 plus ten at 4500, which is 295000 cents, against 270000 cents under the flat marginal reading. A separate reconciliation figure counts the agent's `DELIVERED` and `SETTLED` loads as its paid
count; it is an all-time count over the agent's book, not narrowed to the reporting month.

A test-driving capability runs the settlement period close for one agent and one calendar month, taking the `agent_id` and a `period_month` and returning the period row — the month, the eligible and paid counts, the per-load fee, the period fee, and the effective per-load fee — without persisting any charge. The `period_month` is supplied in `YYYY-MM` form and selects that calendar month; a value that is not a well-formed year-month is refused as malformed with `ERR_INVALID_REQUEST`.

---

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection, return `201 Created`; operations that modify an existing resource, including the state-transition operations, return `200 OK`. Every response is wrapped in the envelope of §2.2. The table below is a routing summary only — request bodies, response bodies, and cascading side effects are specified in §2 and §3 and are deliberately not repeated here. Endpoints whose path begins with `/_clock` or `/_events` are administrative test-driving capabilities rather than business operations.

Every list form is consistent about what it does with its filter argument. The capacity owner list narrows by `status` or `qualification_posture`. A fleet list under one capacity owner narrows by `status` or `inspection_status`. A credentials list under one capacity owner narrows by `document_type` or `status`. A ledger list under one capacity owner narrows by `transaction_type`, `status`, `from_effective_at` and `to_effective_at`. A trips list under one capacity owner narrows by `status`, `from_departed_at` and `to_departed_at`. A settlement-revision list under one trip, and an agent's or a capacity owner's own settlement list, each narrow by `status` and, where the revision matters, `settlement_method`. The network-wide agents list narrows by `status` or `territory_state` — a *state code*, so that supplying a two-letter code returns the agents whose `territory_codes` contain it rather than a single agent by identifier. The network-wide loads list narrows by `agent_id`, `awarded_capacity_owner_id`, `status` or `origin_state`; the network-wide offers list by `load_id`, `capacity_owner_id` or `status`; the network-wide trips list by `load_id`, `capacity_owner_id`, `equipment_id` or `status`; and the network-wide settlements list by `trip_id`, `agent_id`, `capacity_owner_id`, `status` or `settlement_method`. Every one of these list forms accepts the `limit` and `offset` of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/network/load-offers/board` | Read one load's offer board under the selector policy | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| POST | `/network/capacity-owners` | Enroll a business capacity owner | NetworkAdministrator |
| GET | `/network/capacity-owners` | List business capacity owners | FreightAgent, NetworkAdministrator, SettlementOperator |
| GET | `/network/capacity-owners/{id}` | Get one business capacity owner | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| POST | `/network/capacity-owners/{id}/qualify` | Qualify a capacity owner | SafetyReviewer |
| POST | `/network/capacity-owners/{id}/deep-clone` | Clone a capacity owner's identified attributes into a fresh row from its `source_capacity_owner_id` | NetworkAdministrator |
| POST | `/network/capacity-owners/{id}/suspend` | Place a capacity owner out of service | SafetyReviewer |
| POST | `/network/capacity-owners/{id}/reinstate` | Reinstate an out-of-service capacity owner | SafetyReviewer |
| POST | `/network/capacity-owners/{id}/decertify` | Decertify a capacity owner permanently | SafetyReviewer |
| POST | `/network/equipment` | Add a fleet unit to a capacity owner | SafetyReviewer, NetworkAdministrator |
| GET | `/network/capacity-owners/{id}/equipment` | List one capacity owner's fleet units | FreightAgent, CapacityOwnerOperator, SafetyReviewer, NetworkAdministrator |
| GET | `/network/equipment` | List fleet units across the network | SafetyReviewer, NetworkAdministrator |
| GET | `/network/equipment/{id}` | Get one fleet unit | CapacityOwnerOperator, SafetyReviewer, NetworkAdministrator |
| POST | `/network/equipment/{id}/record-inspection` | Record a periodic inspection result | SafetyReviewer |
| POST | `/network/equipment/{id}/place-out-of-service` | Remove a unit from service | SafetyReviewer |
| POST | `/network/equipment/{id}/retire` | Retire a unit permanently | NetworkAdministrator |
| POST | `/network/compliance-documents` | File a safety credential for a capacity owner | SafetyReviewer |
| GET | `/network/compliance-documents` | List safety credentials across the network | SafetyReviewer, NetworkAdministrator |
| GET | `/network/capacity-owners/{id}/compliance-documents` | List one capacity owner's credentials | CapacityOwnerOperator, SafetyReviewer, NetworkAdministrator |
| GET | `/network/compliance-documents/{id}` | Get one credential | CapacityOwnerOperator, SafetyReviewer, NetworkAdministrator |
| POST | `/network/compliance-documents/{id}/verify` | Re-evaluate a credential against the clock | SafetyReviewer |
| POST | `/network/escrow-transactions` | Post a forward ledger entry | SettlementOperator, NetworkAdministrator |
| GET | `/network/escrow-transactions` | List ledger entries across the network | CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/capacity-owners/{id}/escrow-transactions` | List one capacity owner's ledger entries, narrowed by `transaction_type`, `status`, `from_effective_at` and `to_effective_at` | CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/escrow-transactions/{id}` | Get one ledger entry | CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| POST | `/network/escrow-transactions/{id}/reverse` | Post the declared compensating entry | SettlementOperator, NetworkAdministrator |
| POST | `/network/agents` | Enroll an independent freight agent | NetworkAdministrator |
| GET | `/network/agents` | List agents | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| GET | `/network/agents/{id}` | Get one agent | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| POST | `/network/agents/{id}/activate` | Activate an enrolled agent | NetworkAdministrator |
| POST | `/network/agents/{id}/suspend` | Suspend an active agent | NetworkAdministrator |
| POST | `/network/agents/{id}/reinstate` | Reinstate a suspended agent | NetworkAdministrator |
| POST | `/network/agents/{id}/terminate` | Terminate an agent | NetworkAdministrator |
| GET | `/network/agents/{id}/settlement-summary` | Read an agent's chronological commission reconciliation | FreightAgent, SettlementOperator, NetworkAdministrator |
| POST | `/network/agents/{id}/per-load-settlement-tier` | Evaluate the per-load settlement fee schedule for the current month | SettlementOperator, NetworkAdministrator |
| POST | `/network/customer-accounts` | Register a shipper under an agent | FreightAgent, NetworkAdministrator |
| GET | `/network/customer-accounts` | List customer accounts | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| GET | `/network/customer-accounts/{id}` | Get one customer account | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| GET | `/network/agents/{id}/customer-accounts` | List one agent's customer accounts | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| POST | `/network/loads` | Promote a load onto the agent's board | FreightAgent |
| GET | `/network/loads` | List loads | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/loads/{id}` | Get one load | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/agents/{id}/loads` | List one agent's sourced loads | FreightAgent, AgentManager, SettlementOperator, NetworkAdministrator |
| POST | `/network/loads/{id}/cancel` | Cancel a posted load | FreightAgent |
| POST | `/network/loads/{id}/settlement` | Evaluate the settlement split for a load without persisting it | SettlementOperator, NetworkAdministrator |
| POST | `/network/load-offers` | Post an offer to a load's board | FreightAgent |
| GET | `/network/load-offers` | List board offers | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/load-offers/{id}` | Get one board offer | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/loads/{id}/load-offers` | List one load's board offers | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| POST | `/network/load-offers/{id}/accept` | Accept a board offer and award the load | CapacityOwnerOperator |
| POST | `/network/load-offers/{id}/decline` | Decline a board offer | CapacityOwnerOperator |
| POST | `/network/load-offers/{id}/withdraw` | Withdraw a board offer | FreightAgent |
| POST | `/network/trips` | Cover an awarded load with a fleet unit | CapacityOwnerOperator |
| GET | `/network/trips` | List trips | CapacityOwnerOperator, SettlementOperator, SafetyReviewer, NetworkAdministrator |
| GET | `/network/trips/{id}` | Get one trip | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/loads/{id}/trips` | List one load's trips | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/capacity-owners/{id}/trips` | List one capacity owner's trips | CapacityOwnerOperator, SettlementOperator, SafetyReviewer, NetworkAdministrator |
| GET | `/network/equipment/{id}/trips` | List one unit's trips | CapacityOwnerOperator, SafetyReviewer, NetworkAdministrator |
| POST | `/network/trips/{id}/dispatch` | Dispatch a pending trip | CapacityOwnerOperator |
| POST | `/network/trips/{id}/complete` | Record delivery and proof of delivery | CapacityOwnerOperator |
| POST | `/network/trips/{id}/verify-pod` | Verify the proof of delivery | SettlementOperator |
| POST | `/network/trips/{id}/abort` | Abort a non-terminal trip | CapacityOwnerOperator |
| POST | `/network/settlements` | Create a draft settlement for a trip | SettlementOperator |
| GET | `/network/settlements` | List settlements | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/settlements/{id}` | Get one settlement | FreightAgent, CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| GET | `/network/trips/{id}/settlements` | List one trip's settlement revisions | FreightAgent, SettlementOperator, NetworkAdministrator |
| GET | `/network/agents/{id}/settlements` | List one agent's settlements | FreightAgent, SettlementOperator, NetworkAdministrator |
| GET | `/network/capacity-owners/{id}/settlements` | List one capacity owner's settlements | CapacityOwnerOperator, SettlementOperator, NetworkAdministrator |
| POST | `/network/settlements/{id}/submit` | Submit a draft settlement for approval | SettlementOperator |
| POST | `/network/settlements/{id}/approve` | Approve a submitted settlement | NetworkAdministrator |
| POST | `/network/settlements/{id}/reject` | Reject a submitted settlement back to draft | NetworkAdministrator |
| POST | `/network/settlements/{id}/settle` | Settle an approved settlement and post the ledger entries | SettlementOperator |
| POST | `/network/settlements/{id}/void` | Void a draft settlement | SettlementOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every expiry and currency rule | NetworkAdministrator |
| POST | `/_events/run_advance_post` | Post a driver advance through the normal business path | SettlementOperator, NetworkAdministrator |
| POST | `/_events/run_period_close` | Run a settlement period close for one agent and month | NetworkAdministrator |

---

## 5. Error Code Catalogue

Every refusal described in §2 and §3 is reported through the envelope of §2.2 with one of the identifiers below. The trigger conditions are not repeated here; they live beside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_AGENT_NOT_FOUND` | 404 |
| `ERR_CAPACITY_OWNER_NOT_FOUND` | 404 |
| `ERR_LOAD_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_TRIP_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_ESCROW_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TRIP_WINDOW` | 400 |
| `ERR_EQUIPMENT_TYPE_MISMATCH` | 400 |
| `ERR_EQUIPMENT_FLEET_EMPTY` | 400 |
| `ERR_OFFER_EXCEEDS_PAY_CEILING` | 400 |
| `ERR_TRIP_OWNER_MISMATCH` | 400 |
| `ERR_AGENT_TERRITORY_EMPTY` | 400 |
| `ERR_EQUIPMENT_INSPECTION_FAILED` | 400 |
| `ERR_DUPLICATE_AGENT_CODE` | 409 |
| `ERR_DUPLICATE_OWNER_CODE` | 409 |
| `ERR_DUPLICATE_CUSTOMER_REF` | 409 |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 |
| `ERR_AGENT_NOT_ENROLLABLE` | 409 |
| `ERR_AGENT_NOT_ACTIVE` | 409 |
| `ERR_AGENT_NOT_SUSPENDED` | 409 |
| `ERR_AGENT_ALREADY_TERMINATED` | 409 |
| `ERR_TERRITORY_CONFLICT` | 422 |
| `ERR_TERRITORY_VIOLATION` | 422 |
| `ERR_AGENT_SETTLEMENT_HELD` | 422 |
| `ERR_AGENT_SETTLEMENTS_OUTSTANDING` | 422 |
| `ERR_CUSTOMER_NON_SOLICITATION_ACTIVE` | 422 |
| `ERR_NON_SOLICITATION_BREACH` | 422 |
| `ERR_CAPACITY_OWNER_NOT_QUALIFIABLE` | 409 |
| `ERR_CAPACITY_OWNER_NOT_QUALIFIED` | 409 |
| `ERR_CAPACITY_OWNER_NOT_OUT_OF_SERVICE` | 409 |
| `ERR_CAPACITY_OWNER_ALREADY_DECERTIFIED` | 409 |
| `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR` | 422 |
| `ERR_CAPACITY_OWNER_QUALIFICATION_FROZEN` | 422 |
| `ERR_CAPACITY_OWNER_BUSY` | 409 |
| `ERR_OFFER_TIME_OVERLAP` | 409 |
| `ERR_EQUIPMENT_TURNAROUND_OVERLAP` | 409 |
| `ERR_SAFETY_DOCUMENT_MISSING` | 422 |
| `ERR_SAFETY_SCORE_BELOW_MINIMUM` | 422 |
| `ERR_EQUIPMENT_NOT_IN_SERVICE` | 409 |
| `ERR_EQUIPMENT_ALREADY_RETIRED` | 409 |
| `ERR_EQUIPMENT_HAS_ACTIVE_TRIP` | 409 |
| `ERR_EQUIPMENT_NOT_QUALIFIED` | 422 |
| `ERR_EQUIPMENT_INSPECTION_OVERDUE` | 409 |
| `ERR_EQUIPMENT_INSPECTION_NOT_CURRENT` | 409 |
| `ERR_LOAD_NOT_OPEN_FOR_AWARD` | 409 |
| `ERR_LOAD_NOT_AWARDED` | 409 |
| `ERR_LOAD_NOT_COVERED` | 409 |
| `ERR_LOAD_NOT_IN_TRANSIT` | 409 |
| `ERR_LOAD_NOT_CANCELLABLE` | 409 |
| `ERR_LOAD_NOT_SETTLEABLE` | 409 |
| `ERR_OFFER_NOT_OPEN` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_NOT_TOP_RANKED` | 409 |
| `ERR_TRIP_NOT_DISPATCH_PENDING` | 409 |
| `ERR_TRIP_NOT_EN_ROUTE` | 409 |
| `ERR_TRIP_NOT_DELIVERED` | 409 |
| `ERR_TRIP_NOT_ABORTABLE` | 409 |
| `ERR_TRIP_NOT_SETTLEABLE` | 409 |
| `ERR_POD_MISSING` | 409 |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 |
| `ERR_SETTLEMENT_NOT_PENDING_APPROVAL` | 409 |
| `ERR_SETTLEMENT_NOT_APPROVED` | 409 |
| `ERR_SETTLEMENT_METHOD_MISMATCH` | 409 |
| `ERR_SETTLEMENT_ALLOCATION_IMBALANCE` | 402 |
| `ERR_OWNER_OPERATOR_PAY_NEGATIVE` | 402 |
| `ERR_SETTLEMENT_VARIANT_DIVERGENCE` | 402 |
| `ERR_ESCROW_BALANCE_INSUFFICIENT` | 402 |
| `ERR_MAINTENANCE_BALANCE_INSUFFICIENT` | 402 |
| `ERR_ESCROW_ALREADY_MATCHED` | 402 |
| `ERR_STALE_VERSION` | 412 |