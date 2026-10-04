# Buy-Before-You-Sell Bridge Program API — Product Requirements Document

## 1. Introduction

A household that wants to move usually has to sell the home it lives in before it can qualify for the home it wants to buy, and the gap between those two events is where families lose bidding wars. This API exists to close that gap. It lets a program qualify a household on the strength of the equity locked inside the home they are leaving, advance the money they need to buy the next one, and take the pressure off the sale of the old home by standing behind it with a guaranteed offer. Everything the program does — qualification, interim funding, repairs, marketing, the backup guarantee, settlement — is exposed as a single coherent set of resources so that a transaction coordinator, an underwriter and the household itself can all work against the same record.

The product is deliberately conservative with money and deliberately liberal with time. Money is counted in integer cents and never in floating point; time is governed by a single logical clock that the operations team advances explicitly, so that offer expirations, repayment deadlines and interest accruals are reproducible rather than dependent on when a request happened to arrive. The system is also built to protect against two specific failure modes that plague this kind of workflow: a client acting on a stale view of a record it has already been outrun on, and a guarantee being consumed by the same person who extended it.

This document specifies the resources, the state machines that govern them, the arithmetic that produces every derived amount, and the conditions under which an operation must be refused. It is written for the engineer who will implement the service without further access to the program's internal design, and it assumes nothing about the order in which the sections are read.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply to every resource and every operation in the API. They are the conditions under which any individual workflow in §3 is permitted to run.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting party and `X-User-Role` declares the capacity in which that party is acting. A request that omits either header, or that names a role the system does not recognize, is refused before any business logic runs. The system recognises exactly five roles: `Coordinator`, `Underwriter`, `Homeowner`, `Agent`, and `ProgramAdmin`.

Not all of those identifiers mean the same kind of thing, and the difference matters for ownership checks. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner`; ownership checks on any resource that references a `Homeowner` compare the resource's foreign-key field to `X-User-ID`. The same holds for `Agent`: when `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent`, and ownership checks compare the referencing resource's agent identifier to that value. The remaining three roles are operational rather than entity-backed. When `X-User-Role` is `Coordinator`, when it is `Underwriter`, or when it is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to an entity's `id`. The one exception to that rule is segregation of duties, described below.

Missing or malformed credentials are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not permitted on the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the operations available to a role are exactly those enumerated in §4.

Segregation of duties applies to the backup guarantee. The `Coordinator` who issued a `BackupOffer` must not be the same `Coordinator` who exercises it, which is the only place in the system where two opaque operator identifiers are compared to each other. An exercise attempted by the issuing operator is rejected with `ERR_SOD_BACKUP_APPROVER` (HTTP 403).

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

List operations accept a `limit` and an `offset`. The `limit` is the maximum number of items returned and defaults to 10 when omitted; it must be at least 1 and at most 100. The `offset` is the number of items skipped from the head of the result set and defaults to 0. Unless a specific ordering is stated in §3, list results are ordered by creation timestamp ascending, so the oldest record appears first. Every list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope described in §2.2.

### 2.4. Money, Units and the Integer-Cent Discipline

Every monetary amount in this system is an integer number of cents, and every rate is an integer number of basis points, where one basis point is one hundredth of a percentage point and ten thousand basis points is a factor of one. No monetary field is ever a decimal number or a string, and no intermediate step in any financial calculation is permitted to leave integer arithmetic. Where a formula combines a principal with a rate in basis points, the product is divided by ten thousand, and the division floors toward negative infinity rather than rounding to the nearer integer. Rounding to the nearer integer appears in exactly one family of calculations — the referral economics of §3.7 — where the half-up method is used and stated explicitly there. Everywhere else, a computed cent amount is the floor of its expression. A reader implementing any derived field in §3 should assume floor division at each term unless the prose says otherwise.

Two derived quantities on a `Homeowner` are worth calling out here because they are produced by more than one workflow and read by several others. The `departing_equity_cents` field is the net equity across the household's departing properties and is recomputed whenever a qualification for that household is approved. The `sealed_flag` is a boolean that the system sets to true when every `BridgeProgram` belonging to the household has reached `SETTLED`; it never resets once set, because a household's bridging history is closed at that point.

### 2.5. Common Resource Properties and Identifier Conventions

Every resource in this API is addressable by an `id` that the server mints as a plain UUID — there is no type prefix, no natural key and no significance encoded in the string. Alongside the `id`, every entity carries a `created_at` timestamp in ISO 8601 UTC with three fractional digits, and an `updated_at` timestamp of the same shape that is refreshed on any mutation. Every entity except one also carries a `version` integer that the server increments by one on each mutation; `version` is the field that the optimistic concurrency rules of §2.9 measure against, and a stale version is not a client error the server can detect without it.

Every entity in this API carries all four: a newly registered `Homeowner`, a `Property`, a `BackupOffer`, an `Agent` and a `Disbursement` alike are addressed by a server-minted UUID `id`, and all of them expose `created_at`, `updated_at` and `version`. There is no entity in this system that omits `updated_at` or `version`, and there is no resource whose `id` carries a type prefix or a natural key. A mutation is not limited to an explicit client edit: a state transition caused by the logical clock, or by a cascade from another resource, is still a mutation and still refreshes `updated_at` and increments `version` on every resource it touches. The `version` integer is the field that the optimistic concurrency rules of §2.9 measure against, and an implementation must increment it on every write for those rules to mean anything.

### 2.6. Nested Paths and Left-to-Right Resolution

Many operations name a parent in the path and a child in the same path. When a request addresses a nested resource, the server resolves the path identifiers from left to right and stops at the first one that does not name an existing resource. The error raised is the one belonging to that first missing segment: a missing household yields `ERR_HOMEOWNER_NOT_FOUND`, a missing property yields `ERR_PROPERTY_NOT_FOUND`, a missing qualification yields `ERR_QUALIFICATION_NOT_FOUND`, a missing program yields `ERR_BRIDGE_PROGRAM_NOT_FOUND`, and a missing interim loan yields `ERR_LOAN_NOT_FOUND`. One further code, `ERR_RESOURCE_NOT_FOUND`, covers every other entity addressed by a path identifier — a bridge advance, a carrying cost, a repair advance, a backup offer, a listing, an agent, a referral, a coordination task or a disbursement. That same left-to-right discipline governs operations whose bodies reference several resources at once: the body references are validated before any business rule on the payload is evaluated, so a request naming a household that does not exist is refused for the missing household and never reaches the arithmetic.

### 2.7. The Logical Clock

The system does not consult wall-clock time. It reads a logical clock that starts at exactly `2026-09-01T00:00:00Z` when the server boots and that only moves when a coordinator advances it through the clock-control capability described in §4. Every rule expressed as a date comparison — an offer that expires, a qualification that goes stale, a loan that falls delinquent, an appraisal that ages out, an interest accrual that runs to today — is evaluated against that logical clock and never against real time. Advancing the clock is itself a state-changing event: it can push a qualification into `EXPIRED`, an offer into `EXPIRED`, and a loan into `DELINQUENT` without any client having touched those resources, so the server re-evaluates every clock-gated expiry after the clock moves.

### 2.8. Record Design: Foreign Keys, Enumerations and Independent Axes

A relationship in this system is recorded as an explicit foreign-key field whose name ends in `_id` and whose value is the target resource's `id`: `homeowner_id`, `departing_property_id`, `new_property_id`, `qualification_id`, `bridge_program_id`, `interim_loan_id`, `property_id`, `agent_id`, `referral_id`. These fields are supplied by the client at creation and are never inferred from the URL. Deleting a resource that others reference is out of scope for this API; relationships are only ever created and re-pointed by the rules in §3.

Several resources carry more than one status field, and it is essential not to collapse them. A `BridgeProgram` has two entirely independent lifecycles: `advance_status`, which tracks the money, and `occupancy_status`, which tracks the family and the marketing of the old home. A `Listing` likewise carries a `status` alongside a `marketing_status` that moves on its own. A `CarryingCost` carries a `repayment_status` that is independent of the program's axes, and a `Property` carries a `listing_status` and a `repair_status` that progress separately. Transitions on one axis never imply a transition on another unless §3 says so explicitly.

### 2.9. Optimistic Concurrency Control

Four operations in this API write to a parent entity whose state may have moved since the client last read it, and each of those four requires the client to supply its last-observed version of that parent as a non-optional body field. If the supplied value does not equal the parent's current `version`, the request is refused with `ERR_STALE_VERSION` and an HTTP status of 412. The four operations and their version fields are: funding a bridge program, which requires `expected_bridge_program_version`; posting a repayment against an interim loan, which requires `expected_interim_loan_version`; exercising a backup offer, which requires `expected_backup_offer_version`; and reopening a referral, which requires `expected_referral_version`. The offered version is the client's claim about the parent's `version` at the moment it read the record, and a mismatch means that claim is no longer true. No other operation in this API accepts a version field; an operation not named in this paragraph does not take one, and supplying one to a different operation is not a substitute for the rule above.

### 2.10. Appraisals, Grades and Values That Age

A `Property` carries an `appraised_value_cents` and an `appraisal_date`; the appraisal is a dated observation rather than a permanent fact, and an appraisal is considered stale once more than `APPRAISAL_VALIDITY_DAYS` have elapsed against the logical clock. Staleness is enforced at the two operations that commit the program's money and its guarantee, and it is enforced with `ERR_APPRAISAL_STALE`. Separately, a property carries a `condition_grade` drawn from `A`, `B`, `C` or `D`, which is assigned by the transaction coordinator before listing and which feeds both the capacity arithmetic of §3.2 and the price floor of §3.6. A `Property` whose `kind` is `NEW` also carries a `purchase_price_cents`, and a `Property` whose `kind` is `DEPARTING` carries a `mortgage_payoff_cents` which is zero for a home owned free and clear.

### 2.11. Validation Precedence and Refusal Order

When more than one rule could refuse the same request, the order in which they are evaluated determines which error a client sees, and the order is fixed. Authentication is settled first: a request without usable credentials is refused with `ERR_UNAUTHENTICATED`, and only a request that survives that check is examined for role permission and then for the segregation-of-duties rule that guards the exercise of a backup offer. Only then is the payload itself inspected for missing required fields and for values outside their declared types and ranges, all of which produce `ERR_INVALID_REQUEST`. Referenced resources are resolved next, in the left-to-right order of §2.6, so a 404 always outranks a 409 or a 422 on the same request.

Business rules are then applied in a fixed cascade. State-appropriateness is judged before money: a resource that is not in a state from which the requested transition is declared is refused with `ERR_INVALID_STATE` before any economic check runs, a resource already in a terminal state is refused with `ERR_ALREADY_TERMINAL`, and the specific state conflicts for the backup guarantee, the marketing lifecycle, a repaid loan and the exercise window each carry their own code. Only after the state checks pass does the server evaluate the lender's credit floor, the loan-to-value ceiling, the regulatory price floor, the draw headroom, the repair ceiling, the carrying-cost settlement condition and the reconciliation rules of §3. This ordering is deliberate: a request that is both mistimed and over-budget is refused as mistimed, and an implementation that evaluates the economic checks first will surface the wrong error to the client.

## 3. Business Logic & Workflows

### 3.1. Household Intake, Property Records and the Partner Roster

Everything begins with a household. A transaction coordinator registers one by supplying the principal's `full_name`, a contact `email`, a `credit_score` and an annual `household_income_cents`, and may optionally set a `max_dti_bps` tolerance for the household's debt-to-income ratio, which defaults to 4300 basis points when not supplied. Two of these fields carry hard constraints. The `email` is unique across all homeowners — a second registration reusing an address is refused — and the `credit_score` must lie between 300 and 850 inclusive. A newly registered household starts with a `program_status` of `NONE` and a `sealed_flag` of false, and it holds no equity until a qualification has been approved for it.

Properties are recorded against the household that owns them. Creating a property requires the owning `homeowner_id`, a street `address`, a `kind` of either `DEPARTING` or `NEW`, the `appraised_value_cents`, and a `condition_grade` of `A`, `B`, `C` or `D`. Several fields are optional and carry defaults that an implementer must honour rather than treat as absent: `mortgage_payoff_cents` defaults to 0, which is the correct value for a home owned free and clear; `purchase_price_cents` defaults to 0 and is meaningful only for a home of kind `NEW`; `appraisal_date` defaults to the very start of the logical clock, `2026-09-01T00:00:00Z`; and `repair_progress_bps` defaults to 300. A property's `kind` is not decorative — the two homes in a bridge play different roles throughout the program, and the system refuses any workflow that hands a property to a role its kind does not match, raising `ERR_PROPERTY_KIND_MISMATCH`.

The initial property record also seeds two fields the client never supplies. Every property begins `UNLISTED` in its `listing_status` and `NOT_STARTED` in its `repair_status`, with a `site_visit_count` of zero and a `program_inventory_flag` of false that only ever turns true when the program itself acquires the home.

Pre-listing repairs are paced by physical inspection rather than by paperwork. Each time a coordinator records a site visit against a property, the `site_visit_count` rises by one, and the property's `repair_status` flips from its current value to `COMPLETE` at the moment the visit count, multiplied by one hundred, is at least the property's `repair_progress_bps` requirement. Because the field is expressed as a required-visit count scaled by one hundred, a property left at its default requirement of 300 completes on its third recorded visit. Note that a repair advance, discussed in §3.4, can also move `repair_status` to `IN_PROGRESS`; the two paths are complementary, not exclusive.

The partner side of the business is run on an agent roster. Registering an agent requires a `full_name`, a `brokerage_name` and a state `license_number` that is unique across all agents, and permits an optional `referral_rate_bps` that defaults to 250 basis points. A freshly registered agent is `PENDING` and may not receive referrals. A coordinator moves the agent to `QUALIFIED` once its licence has been verified; the licence number must be present for that step to succeed. Should a partner fall out of good standing, a coordinator can suspend an agent that is either `PENDING` or `QUALIFIED`, and suspension is contagious in exactly one direction: every referral belonging to that agent whose status is `OPEN` is simultaneously moved to `VOIDED`, and the `active_referral_count` on both the agent and each affected program is recomputed. Suspension is a terminal state for this API, but a suspended partner can be brought back by a reinstatement that supplies a `reinstatement_note`; that step returns the agent to `QUALIFIED`. Note that reinstatement does not revive the referrals that were voided when the agent was suspended.

A referral is the commercial tie between a program and a partner. It is created against an `agent_id` and a `bridge_program_id` with a `role_scope` of `DEPARTING_SIDE`, `NEW_SIDE` or `RESALE_SIDE`, and it carries its own `referral_rate_bps`, which is copied from the agent's rate at creation and may be overridden, together with a `qualifying_volume_cents` that defaults to 0. A referral opens in `OPEN`. Two rules constrain its creation. First, the partner must be usable at that moment: an agent whose `qualification_status` is `SUSPENDED` cannot be the subject of a new referral, and the attempt is refused with `ERR_AGENT_NOT_QUALIFIED`. Second, a program may not hold two simultaneously active referrals for the same side of the transaction — a second `OPEN` referral for a `role_scope` already covered on that program is refused with `ERR_DUPLICATE_ACTIVE_REFERRAL`.

### 3.2. Qualification: Two Readings of the Same Equity

A qualification is the program's judgement about how much house a household can commit to, and it is recorded against three resources at once: the `homeowner_id`, the `departing_property_id` whose equity is being counted, and the `new_property_id` being purchased, along with the `target_purchase_price_cents` the household intends to pay. Both referenced properties must belong to the household named in the record, and a qualification that pairs a household with a property it does not own is refused with `ERR_HOMEOWNER_MISMATCH`.

The heart of the qualification is the `capacity_cents`, and it is computed twice over because the product asks the household to choose between two readings of the same equity. The coordinator selects the reading through `variant_used`, which is `CONSERVATIVE` by default and may be set to `OPTIMISTIC`. Both readings begin from the same equity figure: the departing property's `appraised_value_cents` minus its `mortgage_payoff_cents`. Both then apply a base ratio that credits the household with 7000 basis points of that equity, and both add a condition credit earned by the departing home's state of repair.

The condition credit is where the two readings first agree and then diverge. The credit is zero for a home graded `D`, and grows by 500 basis points for each grade above the worst: a `C` home earns 500 basis points of credit, a `B` home earns 1000, and an `A` home earns 1500. That credit is added to the 7000-basis-point base and the sum is applied to equity. The conservative reading stops there. The optimistic reading adds a further 1000 basis points of market appreciation to the ratio before applying it, so the optimistic capacity is at least 1000 basis points of equity larger than the conservative figure for the same home.

Either reading is then clamped against the household's income. The capacity may not exceed the household's `household_income_cents` multiplied by 50000 and divided by 10000 — that is, five times annual income — and whenever the computed capacity would exceed that ceiling it is lowered to the ceiling. After clamping, a floor raises any negative result to zero. Each division in this computation floors, and no intermediate value is rounded. The `equity_ratio` reported alongside the capacity is the net departing equity divided by the appraised value of the departing home, carried to four decimal places.

A qualification opens `PENDING` and is refined before anyone commits to it. The coordinator may revise the reading or the target price while the record is still open, which re-derives both the capacity and the equity ratio. Revision is also permitted on a qualification that has already been approved, in which case the record returns to `PENDING` — but only while no enrolment has moved past its own opening state; a qualification that has already been enrolled and funded can no longer be reopened this way, and the attempt is refused.

Approval is where the household's position in the program is established. A coordinator approves an open qualification to mint the capacity, and the household must clear the lender's floor before that happens: a `credit_score` below 620 is refused with `ERR_CREDIT_SCORE_BELOW_MINIMUM`. Approval recomputes the household's `departing_equity_cents` as the net equity across every departing property the household holds, moves the household's `program_status` to `QUALIFYING`, and takes the qualification to `APPROVED`. Denial is the parallel branch and takes the opposite path: the coordinator supplies a free-text `denial_reason`, the qualification moves to `DENIED`, and the household's `program_status` becomes `WITHDRAWN`. A denial is refused outright if the reason is absent.

Neither branch waits forever. A qualification left `PENDING` for ninety days past its creation expires, and so does an `APPROVED` qualification that has sat for ninety days past its approval without any bridge program ever referencing it. Expiry is not an operator action; it happens when the logical clock reaches those thresholds, and an implementation must re-evaluate both windows every time the clock advances. Expiring a qualification is a mutation in its own right and advances the qualification's `version`, as does expiration of a backup offer.

### 3.3. Enrolment and the Program Fee

An approved qualification is turned into a bridge program by a coordinator, supplying the `homeowner_id`, the `qualification_id`, the `new_property_id`, the `departing_property_id`, a `projected_carry_months` between 1 and 24 inclusive, and an optional `program_fee_basis_points` that defaults to 150 basis points of the interim loan principal. A program opens with `advance_status` of `PENDING` and `occupancy_status` of `VACANT`, and it carries two counters that are derived rather than supplied: `outstanding_carrying_cost_cents`, which is the sum of the unpaid carrying costs attached to the program and is recomputed on every change to any of them, and `active_referral_count`, which counts the program's referrals still in `OPEN` status and begins at zero.

Funding the program is the moment it becomes real, and it is a heavier operation than its name suggests. Four things must hold first. The program must still be `PENDING` on its advance axis. The linked qualification must be `APPROVED`. The linked property must genuinely be the home being bought, that is, of kind `NEW`. And no interim loan may already exist for the program. When those conditions hold, funding originates an interim loan in `ORIGINATED` status whose `principal_cents` is exactly the qualification's `capacity_cents`, stamped with an `originated_at` read from the logical clock; it also creates the disclosure-backed advance entries that represent the program's own charges, recomputes the program's `total_program_charge_cents`, resets the linked departing property's `listing_status` to `UNLISTED`, and moves the household's `program_status` to `ENROLLED`. The program's advance axis becomes `FUNDING`.

Funding is also one of the operations that insists the client is not acting on a stale picture of the program. The request must carry `expected_bridge_program_version`, and if the program's `version` has moved on since the client last read it — which happens whenever another writer funds, or advances, or otherwise touches the program — the funding is refused with `ERR_STALE_VERSION` at HTTP status 412 rather than being allowed to overwrite a state the client has not seen.

Two further gates guard the money at this point. The interim loan principal may not exceed 7500 basis points of the new property's appraised value, measured as the principal multiplied by ten thousand and divided by the appraisal, all rounded down; a loan that would sit above that loan-to-value ceiling is refused with `ERR_LTV_EXCEEDS_LIMIT`. And the appraisal underpinning the whole arrangement must be current: if more than `APPRAISAL_VALIDITY_DAYS` have passed between the property's `appraisal_date` and the logical clock, the funding is refused with `ERR_APPRAISAL_STALE`. The same staleness rule guards the guarantee described in §3.6.

Before committing to the fee, a coordinator can preview it. The disclosure preview reports the `total_program_charge_cents` together with its three components — `origination_cents`, `coordination_cents` and `escalator_cents` — and accepts an optional `projected_carry_months` override so the coordinator can model a different carrying horizon without altering the program. The preview is a read of the arithmetic in §3.4, not a commitment.

### 3.4. Drawing Money: Advances, Headroom and the Repair Ledger

A program that has been funded can disburse money, but only through an advance that has been individually requested and approved. An advance is requested by a coordinator against a `bridge_program_id` and an `interim_loan_id`, with a `purpose` of `DOWN_PAYMENT`, `CARRYING_COST`, `REPAIR`, `FEE` or `DISCLOSURE` and an `amount_cents` that must be strictly greater than zero. The advance opens `PENDING` and is approved or rejected by an underwriter; the approval path is described in §3.8, because it is where the discount waterfall lives.

Headroom is the question an advance has to answer, and the arithmetic reserves the program's fee before it measures. The program fee debit is the interim loan's `principal_cents` multiplied by `PROGRAM_FEE_BPS`, which is 150, and then divided by ten thousand. The remaining drawable amount is the loan's `principal_cents` minus its `outstanding_principal_cents` minus that debit. An advance is acceptable when its `amount_cents` is greater than zero and is at most that remaining amount; the boundary is inclusive, so an advance for exactly the remaining amount is accepted. A request beyond it is refused with `ERR_NO_CAPACITY`. The same ceiling governs the disbursement step and the disbursement of repair funds.

One purpose behaves differently from the others. A `DISCLOSURE` advance is the vehicle for the program's own charges, and the fee reserve described above exists for it: only the `DISCLOSURE` portion of the program's charges may consume the reserved fee, and a `DISCLOSURE` advance must never cause the reserve to be debited a second time. Implementers should treat the reserve as consumed once, by the disclosure entries, and never again.

Disbursement converts an approved advance into money actually drawn. A coordinator disburses an approved advance, which requires that the linked interim loan still has capacity and that the program's advance axis is in `FUNDING` or `FUNDED`. The disbursement raises the loan's `drawn_cents` by the advance amount, recomputes the loan's `outstanding_principal_cents` and `accrued_interest_cents`, and, when the advance is the down payment, moves the program's advance axis to `FUNDED` and the household's `program_status` to `BRIDGED`. Disbursement also has a coordination side effect: the coordination task assigned to that piece of work is moved to `IN_PROGRESS`, and the carrying costs that the advance touches are re-derived.

There is a stakeholder gate on the largest payments. A down payment advance whose `amount_cents` exceeds `STAKE_HOLDER_REVIEW_CENTS`, which is 9000000 cents, is not simply disbursed: it is downgraded to a disclosure-only entry and is not auto-approved, and an attempt to disburse it without that prior stakeholder review is refused with `ERR_STAKEHOLDER_REVIEW_REQUIRED`.

Rejecting an advance is a compensating action, and it has teeth. An underwriter may reject an advance that is `PENDING`, and may also reject one that has already been approved provided that no coordination task linked to the program has yet been completed. On an approved-advance rejection the system unwinds what the approval implied: any coordination task that had been moved to `IN_PROGRESS` is cancelled, and if the rejected advance was the program's sole down payment advance the program's advance axis is returned to `PENDING`. Rejecting the sole down payment advance also retires the interim loan, whose status becomes `REPAID`, and the rejection is only permitted while no coordination task linked to the program has already reached `COMPLETED`. Rejecting an advance that is `PENDING` carries none of this compensation.

Repairs run on their own advance track because they are repaid out of a different pot. A repair advance is requested by a coordinator against the `property_id` being improved and a `bridge_program_id`, with a description of the `scope`, an `approved_amount_cents` ceiling, and an `escrow_release_mode` of `LUMP_SUM` or `MILESTONE` that defaults to `MILESTONE`. It opens `REQUESTED`. Two constraints apply at creation and again at approval: the cumulative approved amount across every repair advance for the property may not exceed that property's repair ceiling, and the request is refused with `ERR_REPAIR_SCOPE_EXCEEDS_CAP` if it would. Approval is an underwriter action and carries three further conditions — the approved amount may not exceed 5000000 cents, the linked property must be of kind `DEPARTING`, and the program must be in a state where repairs make sense, that is, its advance axis must be `FUNDING` or `FUNDED`. An approval attempted while the program's advance axis has closed is refused with `ERR_ADVANCE_WINDOW_CLOSED`; an approval that passes sets the linked property's `repair_status` to `IN_PROGRESS`. Disbursement of an approved repair follows the same headroom arithmetic as any other advance and raises the loan's `drawn_cents` and `outstanding_principal_cents`. Repairs are later clawed back rather than repaid voluntarily, which is covered in §3.9.

### 3.5. Interest, Repayment and the Dual Cost View

An interim loan carries a `principal_cents` and an `interest_rate_bps`, and it opens `ORIGINATED` with `drawn_cents` at zero and `outstanding_principal_cents` and `accrued_interest_cents` derived. Funding a program normally originates the loan as a side effect; the loan can also be originated directly by a coordinator against a `bridge_program_id`, and that path is subject to the same loan-to-value ceiling as funding, refused with `ERR_LTV_EXCEEDS_LIMIT`.

Interest accrues chronologically, and the chronology is the whole substance of the rule. The loan's disbursed advances are ordered by `advanced_at` ascending, breaking ties by creation time ascending, and the accrual walks that order carrying a running principal. For each event in turn, interest is added to the accrued total in an amount equal to the running principal multiplied by `interest_rate_bps`, multiplied by `INTERIM_DAY_COUNT_BPS` — 3000 — and divided by the product of ten thousand and ten thousand, with the division flooring. The running principal is then increased by the event's `amount_cents`, and the process repeats. One final accrual is added after the last event, using the fully accumulated running principal, and then all repayments that have been applied to interest are subtracted. A negative result is raised to zero. Only advances in `DISBURSED` status participate; advances still `PENDING` or already `REJECTED` are excluded from the walk entirely, which is why the accrual must be recomputed whenever an advance's status changes. Accruals normally run through the current logical clock, but once a settlement entry of kind `CLOSING_SALE` has been applied, accrual stops at that entry's creation time instead of continuing to today.

Repayment is the household's side of the bargain, though a coordinator may also post one. A repayment carries an `amount_cents` and, because it moves a balance another writer may have just changed, an `expected_interim_loan_version` that must equal the loan's current `version`; a mismatch is refused with `ERR_STALE_VERSION` at HTTP status 412. This protects the household from repaying against a balance it has not observed, which is precisely the situation that arises when another advance has just been drawn against the same loan.

The size and timing of a repayment determine which of several paths it takes. A payment strictly smaller than the sum of the loan's `outstanding_principal_cents` and `accrued_interest_cents` reduces principal, recomputes interest and puts the loan in `REPAYING`. A payment exactly equal to that sum is a final repayment: it zeroes both principal and interest, takes the loan to `REPAID`, and is the only kind of repayment that can settle the program. A final repayment may not be posted while the program's `outstanding_carrying_cost_cents` is anything but zero — the carrying costs must be cleared first, and the attempt is refused with `ERR_CARRYING_COST_UNPAID`. Nor may a repayment that is intended as final be posted in any amount other than the exact combined balance; a short or long final payment is refused with `ERR_SETTLEMENT_NOT_FULL`. A repayment may also be made against a loan already in `DELINQUENT` status, which returns it to `REPAYING`.

Delinquency is not an operator decision. A loan in `DRAWN` status becomes `DELINQUENT` when the logical clock passes the due date of its earliest unpaid carrying cost and the loan has accrued interest to date. Advancing the clock is therefore a state-changing act, and implementations must re-run this check after every clock movement.

Finally, a repaid loan can be reopened, but only for one reason and only once. An underwriter may reopen a loan that is `REPAID` when a repair advance on the same program has been disbursed and has not yet been fully clawed back — that is, when its `repaid_cents` is still below its `approved_amount_cents`. Reopening restores `outstanding_principal_cents` to the amount of the un-clawed repair advance and returns the loan to `REPAYING`. A reopen attempted against a loan that is not `REPAID`, or a reopen that has already been applied to the same repair, is refused with `ERR_LOAN_ALREADY_REPAID`.

The program can also be read as two costs at once, which is the point of the summary view a coordinator or the household itself may request. That view reports `outstanding_carrying_cost_cents` alongside `true_cost_cents`, `amortized_cost_cents` and the `variance_cents` between them, plus the disclosure figures `total_program_charge_cents`, `origination_cents`, `coordination_cents` and `escalator_cents`. The full construction of the two costs and their variance is treated in §3.9, where the money is closed out.

### 3.6. The Guaranteed Offer and the Marketing Campaign

The promise at the centre of the product is a guaranteed offer on the home the household is leaving, and it is modelled as a `BackupOffer`. A coordinator drafts one against the `departing_property_id` and the `bridge_program_id`, with an `offer_price_cents`, a `window_start` marking when the exercise window opens, and a `window_days` of between 1 and 180 inclusive. The offer opens in `DRAFT` and, at creation, the system computes its `price_basis_cents` from the price floor described below.

The price floor is what stops the guarantee from being written at any number the coordinator likes, and it is the regulatory constraint that makes the product saleable. It begins from the departing property's `appraised_value_cents` reduced by 1200 basis points — that is, the appraisal less a twelve per cent discount — with the division flooring. That discounted figure is then reduced again by a condition modifier that reflects how much work the home needs: no modifier at all for a home graded `A`, 200 basis points for one graded `B`, 450 for one graded `C` and 600 for one graded `D`, again flooring. The result is the discounted floor. It is then compared against a regulatory floor set at 8500 basis points of the appraised value, and whichever of the two is the greater becomes the binding `price_basis_cents`. In practice a well-conditioned home graded `A` or `B` is bound by its discounted floor, while a distressed `C` or `D` home has been pushed by the condition modifier below the regulatory line and is bound by the regulatory floor instead. Every offer whose status is `DRAFT`, `ISSUED`, `EXPIRED`, `EXTENDED` or `EXERCISED` is bounded by this floor. An offer written below it — whether at creation or at the moment it is issued — is refused with `ERR_REGULATORY_PRICE_FLOOR`. Note also that an offer price may not exceed the property's appraised value at all.

Issuing the offer starts the clock on the guarantee, and two things must be true. The offer must still be `DRAFT`, and the logical clock must have reached the offer's `window_start`; issuing before the window opens is refused with `ERR_EXERCISE_WINDOW_NOT_OPEN`. The offer also may not be issued until the household has actually moved: the linked program's `occupancy_status` must be `DEPARTING_LISTED` at the moment of issue, so the guarantee is issued only once the old home is genuinely on the market. Issuing sets the offer's `expires_at` to `window_start` plus `window_days`, and moves it to `ISSUED`.

Marketing is tracked through a `Listing`, which is a coordinator's deployment of the departing home to the market. A listing is drafted against the `departing_property_id` and a `bridge_program_id` with a `list_price_cents`, opening `DRAFT` with a `marketing_status` of `NOT_STARTED`. Publishing a listing is where the two sides of the program meet, because going live floods several records at once. The listing must be `DRAFT`, its ask price must be greater than zero, and the property's `repair_status` must already be `COMPLETE` — a property whose repairs are unfinished is refused with `ERR_REPAIR_NOT_COMPLETE`, and a property with repairs still in progress is refused again at the occupancy layer with `ERR_LISTING_BEFORE_OCCUPANCY` because the household has not been recorded as occupying the new home. The program's `occupancy_status` must have advanced to `OCCUPYING_NEW` first, and it must be the linked property, not the new home, that carries the `repair_status` of `COMPLETE`. When all of that holds, going live sets the listing to `LIVE` and its `marketing_status` to `ACTIVE`, stamps the listing's `listed_at` from the logical clock, sets the property's `listing_status` to `LISTED`, and moves the program's occupancy axis to `DEPARTING_LISTED`. It also performs a sweep: every coordination task belonging to the program that is still `OPEN` and whose `due_date` has already passed the logical clock is escalated to `IN_PROGRESS` in the same operation.

Only one listing may be marketed at a time, and the rule is stated as an interval, not a flag. A listing occupies a half-open interval from the moment it goes live, and a go-live may not overlap another listing for the same departing property that is currently `LIVE`. A new listing may perfectly well be drafted while an older one is still `LIVE`; what is forbidden is going live on the second one before the first has closed. Overlapping go-lives on the same property are refused with `ERR_LISTING_SLOT_OVERLAP`. Separately, any marketing step attempted while the listing or the program is in a state that does not permit it is refused with `ERR_LISTING_STATE_CONFLICT`.

Third-party interest is recorded by moving a listing under contract. The listing must be `LIVE` and the property `LISTED`. Doing so raises the listing's `offer_count` by one, sets the property's `listing_status` to `UNDER_CONTRACT`, and — importantly for the guarantee — extends the linked backup offer if that offer is currently `ISSUED`, pushing its `expires_at` out by a further 30 days and moving it to `EXTENDED`. Closing the sale is a distinct step and requires that the listing's `offer_count` is at least one and the property is `UNDER_CONTRACT`; a close attempted without a recorded offer is refused with `ERR_LISTING_OFFER_REQUIRED`. A closing sets the listing to `CLOSED`, the property to `RESOLD`, and the program's occupancy axis to `DEPARTING_SOLD`, and it records a settlement entry of kind `CLOSING_SALE`. It also voids the guarantee: a `BackupOffer` in `ISSUED` or in `EXTENDED` is moved to `VOIDED` when the home sells to a third party, because the program's promise is no longer needed.

A paused listing can be relisted. Pausing happens as a consequence of the program exercising its own guarantee, described below, or as an operator action, and a coordinator relists through a `relist_after_pause` flag supplied as `true`. The relist is the only thing that endpoint may do: a request that supplies `relist_after_pause` as false is refused with `ERR_INVALID_REQUEST`, because the operation exists to bring a paused listing back to the market and must not be usable to take a live listing backwards to `DRAFT`.

### 3.7. Agent Referrals, Coordination Tasks and Fee Reconciliation

The partner side earns its money through referrals and completes its work through coordination tasks. A referral matures when the coordinator closes it out, and closing it out requires two things: every coordination task belonging to that referral must have reached `COMPLETED`, and the referral's `qualifying_volume_cents` must be greater than zero. A referral that fails either condition stays `OPEN`. A successful completion moves the referral to `COMPLETED` and recomputes the fee fields described below, the agent's `active_referral_count` and the program's `active_referral_count`. A referral may also be voided while it is `OPEN`, but only when its agent has been suspended; voiding recomputes the two counters but does not touch the fee fields, since no fee was ever earned. A referral may be reopened after completion — but not for free, as §2.9 explains.

The fee a referral earns is the sum of three terms, each floored independently before they are added. The base term is the referral's `qualifying_volume_cents` multiplied by its `referral_rate_bps` and divided by ten thousand; this is the `base_fee_cents`, and it is rounded half-up to the nearest cent, as are the other computed fee fields. The second term is a bonus that depends on the agent's standing: an agent whose `qualification_status` is `QUALIFIED` earns a bonus of 300 basis points applied to the base, and any other agent earns no bonus at all. The third term is a coordination credit that rewards completed work but caps out: the number of the referral's coordination tasks that are `COMPLETED`, multiplied by 8000 cents each, and the whole of that capped at 20000 cents, so no more than 20000 cents of coordination credit can ever be earned by one referral. Tasks in `OPEN` or `IN_PROGRESS` count for nothing, and a `CANCELLED` task is excluded outright. The sum of base, bonus and credit is the referral's `reconciled_fee_cents`, and its `fee_variance_cents` is that reconciled figure minus the base figure. An agent that has never been qualified therefore shows a variance driven purely by coordination credit, while a qualified agent's variance includes both the bonus and the credit.

Coordination tasks are the unit of partner work and they are scheduled as intervals. A task is created against a `bridge_program_id`, a `referral_id`, a `task_kind` of `PHOTOGRAPHY`, `INSPECTION`, `APPRAISAL`, `REPAIR_BID`, `CLOSING_PREP` or `RESALE_PREP`, and a `due_date`. It opens `OPEN`. Each task occupies a half-open interval ending at its `due_date` and beginning `TASK_SLOT_DAYS` before it, and a new task may not overlap any non-terminal task already scheduled for the same referral. The half-open convention matters at the boundary: a task that ends exactly where another begins is adjacent rather than overlapping, and only a genuine overlap is refused, with `ERR_OVERLAPPING_TASK`. Completion of a task is performed by the partner agent or by a coordinator, and it is permitted both from `OPEN` and from `IN_PROGRESS`. Completing a task has a knock-on effect on the referral: when the completed task is the referral's last open task, the system re-evaluates whether the referral can now be backfilled as complete, stamps the task's `completed_at` from the logical clock, and recomputes the agent's `active_referral_count`. There is a stricter completion path for a task that is already `IN_PROGRESS` and whose kind is `REPAIR_BID` or `PHOTOGRAPHY` while a repair advance for the program sits `APPROVED` — in that situation completion is what unlocks the repair funds discussed in §3.4, and the referral status is re-evaluated to `COMPLETED` once every one of its tasks has finished successfully.

### 3.8. Underwriting the Draw: Discounts and the Referral Waterfall

An underwriter sits between a request and its money, and the approval of an advance is where a discount can be granted. Approval moves an advance from `PENDING` to `APPROVED`, and the program's version is bumped as a consequence. Approval is not unconditional for the largest down payments: a down payment advance above `STAKE_HOLDER_REVIEW_CENTS` is not auto-approved, as §3.4 describes.

The discount an approval may grant is allocated through a two-pool waterfall, and which pool fills first depends on who is asking. The pools are the agent referral pool of 25000 cents and the coordination credit pool of 10000 cents, and they are consumed in a fixed order — but that order differs by the requesting referral's `role_scope`. When the requesting referral is on the `DEPARTING_SIDE`, the referral pool is drained before the coordination pool is touched. When the requesting referral is on the `NEW_SIDE` or the `RESALE_SIDE`, the coordination pool is drained first and the referral pool only participates once the coordination pool is exhausted. Within a pool the allocation is simply the smaller of what remains to be funded and what the pool still holds; whatever is granted is accumulated, and whatever remains unfunded is reported as the shortfall. The pools are consumed per approval and do not carry across advances, so each approval starts from full pools. Implementers should note that the two orderings produce different splits of the same request between the two pools even though they produce the same total for requests small enough to be fully funded.

### 3.9. Settlement: Carrying Costs, Clawbacks and the Closing of the Books

Two households' worth of bills fall due while a family is between homes, and the system tracks them as `CarryingCost` rows. A cost is recorded by a coordinator against a `bridge_program_id`, with a `kind` drawn from the eight buckets `DEPARTING_TAX`, `DEPARTING_INSURANCE`, `DEPARTING_HOA`, `DEPARTING_UTILITY`, `NEW_TAX`, `NEW_INSURANCE`, `NEW_HOA` and `NEW_UTILITY`, an `amount_cents` and a `due_date`. it opens `UNPAID`, and it may be marked repaid — by the coordinator or the household — which sets its `repayment_status` to `REPAID` and stamps a `repaid_at`. Every time a carrying cost is created or repaid, the program's `outstanding_carrying_cost_cents` is recomputed, and that recomputation is not a simple sum, because one bucket in the set carries a surcharge.

The surcharge models the higher cost of carrying a newly built home, and it lands on a bucket that depends on the condition of the property being bought. When the new property's `condition_grade` is `A` or `B`, the high-cost bucket is `NEW_CONSTRUCTION_INSURANCE`; for any other grade it is `NEW_TAX`. The size of the surcharge is 2500 basis points of the totals involved. The program computes this in one of two ways depending on its `projected_carry_months`, and the two ways can genuinely differ by cents. When the projection is three months or more, the adjustment is pooled: the program sums all its carrying costs, applies the 2500-basis-point surcharge to that pooled total once, floors it, and then adds the whole pool to the high-cost bucket before the buckets are attributed. When the projection is less than three months, the surcharge is applied row by row instead: each carrying cost whose kind is the high-cost bucket has the surcharge applied to its own amount and floored individually before the buckets are summed. Because the two approaches floor at different points, a program whose rows straddle the high-cost bucket can report a different outstanding amount under each; an implementation must select the approach from the projection, not from the data. Whichever way it is computed, only the buckets whose carrying costs are still unpaid contribute to the `outstanding_carrying_cost_cents` a program reports.

The program's own charges are disclosed once and recomputed as the picture changes. The origination charge is the interim loan's `principal_cents` multiplied by the program's `program_fee_basis_points` and divided by ten thousand. The coordination charge is a flat 45000 cents for a single active referral, and for two or more active referrals each additional `OPEN` referral adds a further coordination amount to that flat charge before the subtotal is formed. The subtotal is the origination charge plus the coordination charge, and the escalator is applied to it in a way that repays careful reading. When the subtotal exceeds `DISCLOSURE_MIN_CENTS`, which is 300000 cents, the escalator is a percentage of the actual subtotal — 500 basis points of it when the subtotal also exceeds `DISCLOSURE_REVIEW_CENTS` of 500000 cents, and 250 basis points of it when it does not. When the subtotal is at or below `DISCLOSURE_MIN_CENTS`, however, the escalator is deliberately not computed against the small actual subtotal: it is computed against the fixed reference `SUBTOTAL_REFERENCE_CENTS` of 400000 cents, at 250 basis points. That fixed reference is the evaluation-order trap in this calculation, and a reader should note that the low band ignores the small subtotal it is nominally evaluating. Each term floors, including the escalator itself, and the `total_program_charge_cents` is the subtotal plus the floored escalator.

Repair money is recovered from the resale rather than repaid by the household, and that recovery is recorded as a settlement entry. A `Disbursement` is created against a `bridge_program_id` with a `source_kind` of `CLOSING_SALE`, `RESALE` or `REPAIR_CLAWBACK` and an `amount_cents`, opening `RECORDED`; it moves to `APPLIED` when it is processed. A settlement entry may never exceed the combined outstanding principal and accrued interest of the loan it settles — the attempt is refused with `ERR_DISBURSEMENT_EXCEEDS_BALANCE` — and once applied it is split three ways, into the portion `applied_to_principal_cents`, the portion `applied_to_interest_cents`, and the `remainder_cents` left once principal and interest are satisfied. A clawback is capped as well: a `REPAIR_CLAWBACK` entry may not exceed the linked repair advance's approved amount less whatever has already been clawed back from it. Applying a clawback raises that repair advance's `repaid_cents`, and when the clawback brings `repaid_cents` level with `approved_amount_cents`, the linked property's `repair_status` becomes `COMPLETE`. Applying a closing-sale or resale settlement has its own effects: it sets covered advances to `REPAID`, recomputes the loan's balances, and, when the settlement is a resale, it flips the property's `program_inventory_flag` back to false and its `listing_status` to `RESOLD`.

Exercising the guarantee is the program acting on its own promise, and it is the one operation with a segregation-of-duties guard. A coordinator exercises a `BackupOffer` that is `ISSUED` or `EXTENDED`, and three conditions must hold: the offer must be in one of those two states rather than expired or already consumed, the logical clock must not have passed the offer's `expires_at`, and the property must still be `LISTED` rather than under contract to a third party. An exercise attempted on an offer whose window has lapsed is refused with `ERR_BACKUP_OFFER_EXPIRED`, and an exercise attempted by the same operator that issued the offer is refused with `ERR_SOD_BACKUP_APPROVER`. The request also carries `expected_backup_offer_version`, and a mismatch is refused with `ERR_STALE_VERSION` at HTTP status 412. A successful exercise sets the property's `listing_status` to `SOLD_TO_PROGRAM` and its `program_inventory_flag` to true, pauses the linked listing — moving it to `PAUSED` and its `marketing_status` to `STOPPED` — stamps the offer's `exercised_at` from the logical clock, and records a settlement entry of kind `RESALE`.

A guarantee that is not exercised still has a life. An offer in `ISSUED` expires when the logical clock passes its `expires_at`, and an `EXTENDED` offer does the same once the clock passes the last extension's expiry. A coordinator can extend an offer back onto the market: an `EXPIRED` offer may be reissued when the property is still `LISTED`, which sets a fresh `expires_at` of the current clock plus the original window, and an `EXTENDED` offer that has not yet lapsed may be extended again the same way. Exercising an `EXTENDED` offer is possible under the same terms as exercising an `ISSUED` one, and it produces the same acquisition effects.

Because the two costs of a bridge are different in kind, the program reports both. The true cost counts what has actually happened: the program's `outstanding_carrying_cost_cents` plus interest computed on the loan's `outstanding_principal_cents` at the loan's rate over the whole calendar months that have actually elapsed between the loan's origination and the logical clock. The amortized cost counts what was planned: the same outstanding carrying costs plus interest on the full `principal_cents` over the program's `projected_carry_months`. The `variance_cents` is the true cost minus the amortized cost, and it may legitimately be negative when the loan has amortized faster than the months that have actually elapsed. Which of the two the summary emphasizes follows the program's advance axis — a program in `FUNDED` is read on the actual elapsed months, while a program still in `PENDING` or `FUNDING` is read on the projected horizon.

### 3.10. Occupancy, Settlement of the Program and the Sealed Household

The family's own progress is tracked on the program's occupancy axis, which moves only forward through four states. While the old home is still the family's base, the axis reads `VACANT`; the household itself records its move into the new home, which requires that the axis be `VACANT`, that the money axis have reached `FUNDING` or `FUNDED`, and that the new property not already be the program's own inventory — a home the program acquired through its guarantee is not a home the household is moving into. That step takes the axis to `OCCUPYING_NEW`, and it is the household's own operation rather than the coordinator's. Only once the axis reads `OCCUPYING_NEW` can the old home be published, as §3.6 describes, which takes the axis to `DEPARTING_LISTED`; and only once the old home is `DEPARTING_LISTED` can its sale be closed, which takes the axis to `DEPARTING_SOLD`.

The program as a whole is settled when the money has come back. The final repayment described in §3.5 is the single act that can settle a program, and it is permitted only when the program's money axis is `FUNDED`, the loan is `REPAYING`, the program's `outstanding_carrying_cost_cents` is exactly zero, and every repair advance belonging to the program has reached `SETTLED`. When all of that holds, the program's advance axis becomes `SETTLED` and its outstanding carrying cost is recomputed. A final repayment that would settle the loan but leave the program's carrying costs outstanding is refused earlier with `ERR_CARRYING_COST_UNPAID`, and a loan that is already terminal cannot repay again, which is refused with `ERR_ALREADY_TERMINAL`.

Settling the last program is what seals the household. When the final repayment settles a program and no other program belonging to the same household is still non-terminal, the household's `sealed_flag` is set to true. The household's `program_status` moves through `QUALIFYING`, `ENROLLED` and `BRIDGED` as the journey proceeds, and it is worth being precise about the withdrawal path: a household whose qualification is denied is `WITHDRAWN`, and while the lifecycle's terminal states are `SETTLED` and `WITHDRAWN`, `WITHDRAWN` reflects a household that never bridged and `SETTLED` one whose books are closed. A household's equity is recomputed from its approved qualification, not from the appraised values at large, so the `departing_equity_cents` a household reports is the net equity the program has actually underwritten.

### 3.11. Cross-Cutting Constraints and the Capability Surface

A number of rules cut across the workflows above and are gathered here because they apply wherever their subject appears. They remain hard conditions no matter which operation is being attempted.

On property identity. A program's two homes are not interchangeable, and the system enforces that each referenced property carries the `kind` its role demands, refusing a mismatch with `ERR_PROPERTY_KIND_MISMATCH`. The role a property is used in is fixed at the moment it is referenced: the home being counted for equity and put up for marketing must be a `DEPARTING` property, and the home being purchased must be a `NEW` one.

On capacity ceilings. The loan-to-value ceiling of §3.3 applies both when a program is funded and when an interim loan is originated directly, and the repair ceiling of §3.4 applies both when a repair advance is requested and when it is approved. Neither ceiling is a warning; both are refusals.

On the ordering of the arithmetic. When several of the constraints in this section could apply to the same request, they are evaluated in the order set out in §2.11, and the first failure decides the error the client sees. Implementers who evaluate them in a different order will not change which requests succeed, but they will change which error a failing request reports, and the hidden contract cares about the error.

On the clock-advance capability. All time-based behaviour in this system is driven by a single coordinator-only capability that accepts a `to_iso8601` instant and advances the logical clock to it, reporting the clock's new value as `current_utc`. Advancing the clock re-evaluates every expiry and accrual that depends on it: qualifications that have passed their windows, offers whose exercise periods have lapsed, loans whose carrying costs have fallen past due and interest accruals that must be brought forward to the new instant. The clock starts at `2026-09-01T00:00:00Z` and must never fall back to the server's real time.

On settlement summary. The platform also exposes an aggregate read across all programs, reporting `total_applied_to_principal_cents`, `total_applied_to_interest_cents`, `remainder_cents` and `entry_count`, optionally scoped to a single program. It is a reporting surface only and changes no state.

## 4. Endpoint Definitions

The API is mounted under `/knock`. Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including actions that change its state or attach data to it, return `200 OK`. The clock-control capability and the settlement summary are likewise mounted at the top level. The table below lists every operation, the role or roles permitted to call it, and a one-line description; the request and response shapes are defined by the workflows in §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/knock/homeowners` | Register a household | Coordinator |
| GET | `/knock/homeowners/{id}` | Read a household | Coordinator, Homeowner |
| POST | `/knock/agents` | Register a partner agent | Coordinator |
| GET | `/knock/agents/{id}` | Read a partner agent | Coordinator, Agent |
| POST | `/knock/agents/{id}/qualify` | Mark an agent qualified to receive referrals | Coordinator |
| POST | `/knock/agents/{id}/suspend` | Suspend an agent and void their open referrals | Coordinator |
| PATCH | `/knock/agents/{id}` | Reinstate a suspended agent | Coordinator |
| POST | `/knock/properties` | Create a property owned by a household | Coordinator |
| GET | `/knock/properties` | List properties, optionally filtered by owning household | Coordinator |
| GET | `/knock/properties/{id}` | Read a property | Coordinator, Homeowner |
| POST | `/knock/properties/{id}/site-visits` | Record a coordinator site visit | Coordinator |
| POST | `/knock/qualifications` | Open a qualification combining departing equity, purchase capacity and lending criteria | Coordinator |
| GET | `/knock/qualifications` | List qualifications with optional filters | Coordinator, ProgramAdmin |
| GET | `/knock/qualifications/{id}` | Read a qualification | Coordinator, Homeowner |
| PATCH | `/knock/qualifications/{id}` | Revise the requested capacity variant or target price | Coordinator |
| POST | `/knock/qualifications/{id}/approve` | Approve a qualification, minting purchase capacity | Coordinator |
| POST | `/knock/qualifications/{id}/deny` | Deny a qualification | Coordinator |
| POST | `/knock/bridge-programs` | Enrol an approved qualification into the bridge program | Coordinator |
| GET | `/knock/bridge-programs` | List bridge programs with optional filters | Coordinator, ProgramAdmin |
| GET | `/knock/bridge-programs/{id}` | Read a bridge program | Coordinator, Homeowner |
| POST | `/knock/bridge-programs/{id}/fund` | Fund the program: originates the interim loan and discloses program charges | Coordinator |
| POST | `/knock/bridge-programs/{id}/occupy-new` | Record the household occupying the new home | Coordinator, Homeowner |
| GET | `/knock/bridge-programs/{id}/summary` | Dual carrying-cost view: true cost versus amortized cost | Coordinator, Homeowner |
| POST | `/knock/bridge-programs/{id}/disclosures/preview` | Preview the disclosed program charges before funding | Coordinator |
| POST | `/knock/interim-loans` | Originate an interim loan for a funded program | Coordinator |
| GET | `/knock/interim-loans` | List interim loans with optional filter | Coordinator |
| GET | `/knock/interim-loans/{id}` | Read an interim loan | Coordinator, Homeowner |
| POST | `/knock/interim-loans/{id}/repayments` | Post a repayment toward principal and interest | Coordinator, Homeowner |
| POST | `/knock/interim-loans/{id}/reopen-advance` | Reopen a repaid loan when a repair clawback remains un-repaid | Underwriter |
| POST | `/knock/bridge-advances` | Request an advance against the interim loan for a stated purpose | Coordinator |
| GET | `/knock/bridge-advances` | List bridge advances with optional filters | Coordinator, Underwriter |
| GET | `/knock/bridge-advances/{id}` | Read a bridge advance | Coordinator, Underwriter, Homeowner |
| POST | `/knock/bridge-advances/{id}/approve` | Underwriting approval of an advance | Underwriter |
| POST | `/knock/bridge-advances/{id}/reject` | Reject a pending or approved advance | Underwriter |
| POST | `/knock/bridge-advances/{id}/disburse` | Disburse an approved advance and draw it against the interim loan | Coordinator |
| POST | `/knock/carrying-costs` | Record a dual carrying cost on the program | Coordinator |
| GET | `/knock/carrying-costs` | List carrying costs with optional filters | Coordinator |
| GET | `/knock/carrying-costs/{id}` | Read a carrying cost | Coordinator, Homeowner |
| POST | `/knock/carrying-costs/{id}/repay` | Mark a carrying cost repaid | Coordinator, Homeowner |
| POST | `/knock/repair-advances` | Request pre-listing repair funding | Coordinator |
| GET | `/knock/repair-advances` | List repair advances with optional filters | Coordinator, Underwriter |
| GET | `/knock/repair-advances/{id}` | Read a repair advance | Coordinator, Underwriter |
| POST | `/knock/repair-advances/{id}/approve` | Approve repair scope and funding ceiling | Underwriter |
| POST | `/knock/repair-advances/{id}/disburse` | Disburse approved repair funds to escrow | Coordinator |
| POST | `/knock/backup-offers` | Draft a guaranteed backup offer on the departing home | Coordinator |
| GET | `/knock/backup-offers` | List backup offers with optional filters | Coordinator |
| GET | `/knock/backup-offers/{id}` | Read a backup offer | Coordinator, Homeowner |
| POST | `/knock/backup-offers/{id}/issue` | Issue the backup offer and start the exercise window | Coordinator |
| POST | `/knock/backup-offers/{id}/extend` | Extend an expired or extended backup offer window | Coordinator |
| POST | `/knock/backup-offers/{id}/exercise` | Exercise the backup offer, acquiring the departing home into inventory | Coordinator |
| POST | `/knock/listings` | Draft a listing for the departing home | Coordinator |
| GET | `/knock/listings` | List listings with optional filters | Coordinator |
| GET | `/knock/listings/{id}` | Read a listing | Coordinator, Homeowner |
| PATCH | `/knock/listings/{id}` | Relist a paused listing | Coordinator |
| POST | `/knock/listings/{id}/go-live` | Publish the listing and begin marketing | Coordinator |
| POST | `/knock/listings/{id}/under-contract` | Record a third-party offer accepted under contract | Coordinator |
| POST | `/knock/listings/{id}/close-sale` | Close the marketing sale of the departing home | Coordinator |
| POST | `/knock/referrals` | Create an agent referral relationship for a program | Coordinator |
| GET | `/knock/referrals` | List referrals with optional filters | Coordinator, Agent |
| GET | `/knock/referrals/{id}` | Read a referral | Coordinator, Agent |
| PATCH | `/knock/referrals/{id}` | Update referral volume or rate | Coordinator |
| POST | `/knock/referrals/{id}/complete` | Close out a referral once all coordination tasks are complete | Coordinator |
| POST | `/knock/referrals/{id}/void` | Void a referral against a suspended agent | Coordinator |
| POST | `/knock/referrals/{id}/reopen` | Reopen a completed referral when new coordination work arrives | Coordinator |
| POST | `/knock/coordination-tasks` | Create a coordination task for a referral | Coordinator |
| GET | `/knock/coordination-tasks` | List coordination tasks with optional filters | Coordinator, Agent |
| GET | `/knock/coordination-tasks/{id}` | Read a coordination task | Coordinator, Agent |
| POST | `/knock/coordination-tasks/{id}/complete` | Complete a coordination task | Agent, Coordinator |
| POST | `/knock/disbursements` | Record a settlement disbursement against the program | Coordinator |
| GET | `/knock/disbursements` | List disbursements with optional filters | Coordinator |
| GET | `/knock/disbursements/{id}` | Read a disbursement | Coordinator, Homeowner |
| GET | `/knock/disbursements/summary` | Aggregate settlement totals across all programs | Coordinator, ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every expiry, window and accrual rule | Coordinator |

## 5. Error Code Catalogue

The catalogue below lists every error identifier the API can return and the HTTP status each carries. The conditions that trigger them are stated in the workflows of §3 and in the cross-cutting rules of §2, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SOD_BACKUP_APPROVER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_HOMEOWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_QUALIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_BRIDGE_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_BACKUP_OFFER_EXPIRED` | 409 Conflict |
| `ERR_LISTING_STATE_CONFLICT` | 409 Conflict |
| `ERR_LOAN_ALREADY_REPAID` | 409 Conflict |
| `ERR_CREDIT_SCORE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_LTV_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_REGULATORY_PRICE_FLOOR` | 422 Unprocessable Entity |
| `ERR_STAKEHOLDER_REVIEW_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_CAPACITY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_REFERRAL` | 409 Conflict |
| `ERR_OVERLAPPING_TASK` | 409 Conflict |
| `ERR_REPAIR_SCOPE_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_LISTING_SLOT_OVERLAP` | 409 Conflict |
| `ERR_ADVANCE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CARRYING_COST_UNPAID` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_NOT_FULL` | 422 Unprocessable Entity |
| `ERR_DISBURSEMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_APPRAISAL_STALE` | 422 Unprocessable Entity |
| `ERR_REPAIR_NOT_COMPLETE` | 422 Unprocessable Entity |
| `ERR_PROPERTY_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_HOMEOWNER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AGENT_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_LISTING_OFFER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXERCISE_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_LISTING_BEFORE_OCCUPANCY` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |