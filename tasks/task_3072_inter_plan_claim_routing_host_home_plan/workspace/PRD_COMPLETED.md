# Inter-Plan Claim Routing API — Product Requirements Document

## 1. Introduction

Independent Blue Cross Blue Shield licensees operate under a shared brand but settle with one another in real money. When a member whose ID card names one plan — the **home plan** — receives care inside another plan's licensed territory, the treating plan — the **host plan** — prices the claim at its own locally negotiated rate, forwards the claim across plan boundaries for benefit determination, pays the provider out of its own funds, and later recovers both the claim dollars and a negotiated access fee from the home plan. This document specifies the API that governs that entire inter-plan workflow: licensee registration and brand licensing, member enrollment under home plans, national account arrangements that span many territories under a single controlling plan, negotiated rate and access fee schedule publication, claim submission, pricing, routing, benefit determination, denial, payment, post-payment adjustment and recovery, periodic settlement between plan pairs, and cross-plan eligibility inquiry.

The design problem is reconciliation across organizational boundaries. Two peer plans must agree on the same claim numbers while each mutates its own view: the host prices and pays, the home determines benefits, the host may adjust after payment, the home may reject or acknowledge the adjustment, and the association itself disburses settlement only after both sides agree. Every number that moves between plans — allowed amounts, access fees, administrative charges, recoveries, batch totals — is an integer cent value computed by deterministic rules stated here, and every cross-plan hand-off is guarded by state machines, license gating, and optimistic concurrency so that neither plan can act on a stale view of a shared artifact.

A logical clock under association control drives all pricing-date-sensitive behavior, so that rate windows keyed on "today" behave deterministically; the clock is settable only through a test-driving capability and starts each server run at a fixed instant rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes three distinct roles: `AssociationAdmin`, `HomePlanOperator`, and `HostPlanOperator`. A request missing either header, or carrying a role string not among these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `AssociationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the association is the governing body and does not own plan-scoped resources, so no ownership comparison is ever performed for this role. When `X-User-Role` is `HomePlanOperator`, `X-User-ID` is the `id` of the acting `Plan`; ownership checks on any resource that references a `Plan` as the home plan compare the resource's home-plan foreign-key field to `X-User-ID`. When `X-User-Role` is `HostPlanOperator`, `X-User-ID` is likewise the `id` of the acting `Plan`, and ownership checks compare the resource's host-plan (or creditor-plan) foreign-key field to `X-User-ID`. A plan-scoped operator that attempts to act on a plan other than its own — for example a `HostPlanOperator` pricing a claim hosted by a different plan — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

A request to a path the API does not define is rejected with `ERR_NOT_FOUND` (HTTP 404); a request using an undefined method on a defined path is rejected with HTTP 405 carrying the same `ERR_NOT_FOUND` error envelope. Any unexpected internal failure surfaces as `ERR_VALIDATION_FAILED` (HTTP 400).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_VALIDATION_FAILED` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; ties on `created_at` are broken by creation (insertion) order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of items matching the filters and `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

All primary resources in the system — Plans, Members, National Accounts, Rate Schedules, Access Fee Schedules, Claims, Adjustments, Settlement Batches, and Eligibility Inquiries — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments with every modification to the resource, including mutations driven by cross-entity side effects such as a payment crediting a plan's balances.

Because every entity in this system is mutable after creation, every entity carries both `updated_at` and `version` — no resource in this API omits them. The `created_at` and `updated_at` timestamps are taken from wall-clock UTC time, not from the logical clock of §2.6.

### 2.5. Money, Integer Cents, and Rounding

All monetary values in the system are integer amounts of cents: billed amounts, negotiated rates, allowed amounts, access fees, administrative charges, provider payments, recoveries, batch totals, and plan balances are all integer cent fields, never floating-point dollars. Wherever a percentage is applied to a cent amount — the tier-2 access fee, the national account discount, and each administrative-charge bracket slice — the product is rounded to the nearest integer cent using the round-half-up method. Pricing and recovery arithmetic introduce no rounding of their own; both the allowed amount and the recovery amount are exact integer-cent results of the comparisons and subtractions described in §3.

### 2.6. The Logical Clock

The server maintains a logical clock whose current date and time answer every question of the form "what is today". Final claim pricing keys its rate-window lookup on the logical clock's current date, never on wall-clock time. At server startup the logical clock reads 2026-09-01T00:00:00Z, and it never falls back to wall-clock time afterward. An `AssociationAdmin` may advance or reposition the clock through an admin-only test-driving capability that accepts a `current_utc` ISO 8601 instant and returns the clock's new reading as an object `{"current_utc": ...}`; the accepted instant is normalized to UTC with a `Z` suffix before storage (an instant without an explicit offset is interpreted as UTC), and a value that is not a parseable ISO 8601 string is rejected with `ERR_VALIDATION_FAILED` (HTTP 400). No other role may set the clock, and the clock is not affected by any business operation.

### 2.7. Optimistic Concurrency Control

Two write operations in this API carry an optimistic concurrency guard, and only these two.

Creating an adjustment against a claim requires the request to carry `expected_claim_version`, a non-optional input field holding the claim `version` the client last observed. If the claim's current `version` does not match — because another writer has since created an adjustment (which legitimately supersedes the prior initiated one) or applied one (returning the claim to paid and advancing its version) — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This version check is evaluated before the adjustment's own business rules (such as the non-zero delta requirement).

Re-finalizing a disputed settlement batch requires the request to carry `expected_settlement_batch_version`, a non-optional input field holding the batch `version` the client last observed. If the batch's current `version` does not match — because another writer has already re-finalized it or otherwise moved it out of the disputed state — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field. Reads, ordinary state transitions, and resource creations other than adjustment creation proceed without any optimistic-concurrency check.

### 2.8. Request Validation Order

Every request passes through an ordered validation pipeline, and the first failing check determines the error returned. The checks, in order, are: authentication of the headers (§2.1, `ERR_UNAUTHENTICATED`); endpoint-level role authorization (`ERR_UNAUTHORIZED`, HTTP 403); on resource-creation endpoints, presence and type validation of the body fields needed to resolve references (`ERR_VALIDATION_FAILED`, HTTP 400); existence of every path identifier and every foreign key referenced in the body, validated left to right as each reference is needed (`ERR_NOT_FOUND`, HTTP 404); plan-scoped ownership, checked as soon as the plan foreign key it is compared against has been resolved — which may interleave with the existence checks of later-referenced foreign keys (`ERR_UNAUTHORIZED`, HTTP 403); whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409) — on adjustment creation and batch re-finalization this state check also precedes validation of the remaining body fields; and finally the business rules — license status, service area, window overlap, same-plan, uniqueness, amount, and floor constraints — each of which is described alongside the workflow it guards in §3. A malformed request body — a missing required field, a wrong type, or an unparseable value — surfaces as `ERR_VALIDATION_FAILED` (HTTP 400) at the point in the pipeline indicated above.

### 2.9. Resource Addressing and Existence Checking

The API is mounted under the `/v1` prefix. Resources in this system are top-level and addressed by their own `id`; there are no nested URL hierarchies. When a request path contains an identifier, or a request body references other resources by foreign key — for example a claim submission carrying `member_id` and `host_plan_id`, or an eligibility inquiry carrying `inquiring_plan_id`, `home_plan_id`, and a `member_number` — every referenced resource must exist, and references are validated in left-to-right order. The first missing reference yields `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated.

### 2.10. Ledger Principles for Inter-Plan Balances

Each plan carries two running ledgers, both starting at zero and both expressed in integer cents. `claims_paid_balance_cents` accumulates the provider payments the plan has made in its capacity as host, and decreases only when an applied downward adjustment recovers funds on a claim the plan hosted. `fees_receivable_balance_cents` accumulates the access fees and administrative charges the plan has earned as host on routed claims, and decreases only when a settlement batch in which the plan is the creditor is disbursed under the net variant, clearing those receivables. Recoveries never touch the receivables ledger: a recovery debits only `claims_paid_balance_cents`, and its effect on what the home plan owes is folded into the fee total at batch finalize time. Every balance mutation — credit at payment, debit at adjustment application, clearing at disbursement — updates the plan's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Plans, Brand Licensing, and Service Areas

The association onboards each independent licensee by registering a **Plan** with a `plan_code` (a short licensee code such as BCBSTX, unique across all plans — a duplicate registration is rejected with `ERR_DUPLICATE_PLAN_CODE`), a `legal_name`, and a non-empty `service_area_states` list of US state codes constituting the plan's licensed territory (an empty list is rejected with `ERR_VALIDATION_FAILED`, HTTP 400). A newly registered plan's `brand_license_status` begins at `PENDING`, and both of its balances, `claims_paid_balance_cents` and `fees_receivable_balance_cents`, begin at zero.

An `AssociationAdmin` governs the brand license lifecycle. Activation moves a plan from `PENDING` to `LICENSED`. Suspension moves a `LICENSED` plan to `SUSPENDED`; while suspended, the plan continues to participate in claims already in flight, but no new claim submission that names the plan as home or host, and no routing of a priced claim involving the plan, is permitted — both are rejected with `ERR_PLAN_LICENSE_SUSPENDED` (HTTP 409). Reinstatement returns a `SUSPENDED` plan to `LICENSED`. Revocation moves a `LICENSED` plan to the terminal `REVOKED` state, but only when no claim hosted or owned by the plan is in any non-terminal state — that is, no such claim may be in `RECEIVED`, `PRICED`, `ROUTED`, `BENEFIT_DETERMINED`, or `ADJUSTMENT_PENDING` at the moment of revocation; when such a claim exists, the revocation is refused with `ERR_INVALID_STATE` because its precondition is unmet. Revocation has a sweeping cascade: every national account controlled by the revoked plan that is currently `ACTIVE` or `SUSPENDED` automatically transitions to `TERMINATED` (the cascade increments each affected account's `version` like any other transition). Each license transition increments the plan's `version`.

Plans and their balances are readable by all three roles, and the plan list supports an optional `brand_license_status` filter alongside the standard `limit` and `offset` pagination parameters.

### 3.2. Members and Eligibility

A member is registered under a home plan by a `HomePlanOperator` (or by the association on the plan's behalf), supplying `home_plan_id`, the `member_number` printed on the ID card, the member's `full_name`, and optionally a `national_account_id` when the member is covered under a national account — this last field is `null` for members not under such an arrangement. The `member_number` is unique within its home plan: registering a second member with the same `member_number` under the same `home_plan_id` is rejected with `ERR_DUPLICATE_MEMBER_NUMBER` (HTTP 409). A member's `eligibility_status` begins at `ACTIVE` and can be moved to `TERMINATED` only by a `HomePlanOperator` of that home plan; termination is the only eligibility transition and it increments the member's `version`.

Before treatment, a host plan may verify a cardholder's standing by filing an **eligibility inquiry** with the `inquiring_plan_id` (the host plan asking), the `home_plan_id` named by the card prefix, and the `member_number` being verified. The inquiry is created in `ROUTED` status. A `HomePlanOperator` of the home plan then resolves it in one of two ways. Answering the inquiry succeeds only when a member with the inquired `member_number` exists under that home plan — when no such member exists, the answer attempt fails with `ERR_MEMBER_NOT_FOUND` (HTTP 404), and the inquiry's only remaining path is rejection, moving it from `ROUTED` to `REJECTED`. On a successful answer, the inquiry's `answer_eligibility_status` is populated with the member's current `eligibility_status` (either `ACTIVE` or `TERMINATED`) and the inquiry moves from `ROUTED` to `ANSWERED`. Alternatively, the home plan may reject the inquiry outright at any time while it is `ROUTED`, with no answer recorded — `answer_eligibility_status` remains `null`. Both terminal resolutions increment the inquiry's `version`. Inquiries are listed with optional `inquiring_plan_id`, `home_plan_id`, `member_number`, and `status` filters.

### 3.3. National Account Arrangements

Large employer groups are covered across many territories under a single **national account** controlled by exactly one plan. An `AssociationAdmin` creates the arrangement by supplying the `controlling_plan_id`, the employer group display `account_name`, the external `employer_group_id`, the non-empty `territory_states` list covered by the arrangement (an empty list is rejected with `ERR_VALIDATION_FAILED`, HTTP 400), and a closed effective window from `effective_start` through `effective_end`, both ISO dates and both inclusive, with `effective_end` no earlier than `effective_start` (an inverted window is rejected with `ERR_ACCOUNT_WINDOW_OVERLAP`, HTTP 422). Territory windows are unique per employer: for the same pair of controlling plan and employer group identifier, no two national account windows may overlap, and because the windows are closed intervals, adjacency that shares an endpoint date already counts as overlap; a violating creation is rejected with `ERR_ACCOUNT_WINDOW_OVERLAP` (HTTP 422).

A national account begins in `PROPOSED` status. Activation moves it from `PROPOSED` to `ACTIVE` and is permitted only while the controlling plan's `brand_license_status` is `LICENSED`. An `ACTIVE` account may be suspended, moving it to `SUSPENDED`, and while suspended the members of that account lose the national-account access-fee discount described in §3.5. Reactivation returns a `SUSPENDED` account to `ACTIVE`, again only while the controlling plan is `LICENSED`. Termination moves an `ACTIVE` account to the terminal `TERMINATED` state; the historical link is retained, so each member's `national_account_id` continues to reference the terminated account. Each of these transitions is performed by an `AssociationAdmin` and increments the account's `version`. Accounts are listed with optional `controlling_plan_id` and `status` filters.

### 3.4. Rate Schedules and Access Fee Schedules

The host plan's local negotiated rates are published as **rate schedules**, each recording the `plan_id` of the host plan whose rate this is, the rendering provider's `provider_npi`, the `procedure_code` the rate applies to, the `negotiated_rate_cents` (which must be greater than zero, otherwise `ERR_INVALID_AMOUNT`), and a half-open effective window running from `effective_start` (inclusive) to `effective_end` (exclusive); the end must be strictly later than the start, and an end on or before the start is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 422). A date falls inside the window when it is on or after the start and strictly before the end. For a given triple of plan, provider, and procedure code, half-open windows may never overlap; because the windows are half-open, a new window whose start equals an existing window's end does not overlap it, while any other intersection is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 422). Rate schedules may be published by a `HostPlanOperator` or the association, and listed with optional `plan_id`, `provider_npi`, and `procedure_code` filters.

The **access fee schedule** between a home and a host plan is published by the association alone. It records the `home_plan_id` that owes the fee and the `host_plan_id` that earns it, the flat-tier ceiling `tier1_cap_cents` and the corresponding flat fee `tier1_fee_cents`, the percentage `tier2_rate` applied above the cap, an optional `national_account_discount_pct` expressing the fraction of the fee waived for qualifying national account members (a value from 0 to 1, defaulting to 0, meaning no discount), and a closed effective window from `effective_start` through `effective_end`, both inclusive, with the end no earlier than the start (an inverted window is rejected with `ERR_FEE_WINDOW_OVERLAP`, HTTP 422). A date falls inside this window when it is on or after the start and on or before the end. Tier values must be non-negative and the cap must be greater than zero; violations are rejected with `ERR_INVALID_AMOUNT` (HTTP 422). For a given home-host pair, closed windows may never overlap — and here, unlike rate windows, adjacency sharing an endpoint date does count as overlap, since both endpoints are inclusive — with violations rejected as `ERR_FEE_WINDOW_OVERLAP` (HTTP 422). A schedule whose home and host plan are the same plan is permitted. On creation, the window-inversion check is evaluated before the tier-value checks, which in turn precede the overlap check. Fee schedules are listed with optional `home_plan_id` and `host_plan_id` filters.

### 3.5. Claim Submission, Pricing, and Routing

An inter-plan claim is born when a `HostPlanOperator` submits care rendered in its own territory to a member of another plan. The submission payload names the `member_id` of the member who received care, the `host_plan_id` in whose territory care was received, the rendering `provider_npi`, the billed `procedure_code`, the `service_date` on which care was rendered, the `service_state` where care was rendered, and the provider's `billed_amount_cents`, which must be greater than zero (otherwise `ERR_INVALID_AMOUNT`). At submission the system copies the member's home plan and national account affiliation onto the claim as `home_plan_id` and `national_account_id` — the latter remaining `null` when the member has no national account — and these copies never change afterward.

Submission enforces three guards before the claim is accepted, evaluated in the order listed, with the `billed_amount_cents` positivity check evaluated after all three. First, the named `host_plan_id` must differ from the member's home plan; a claim whose host equals the home plan is a local claim, not an inter-plan claim, and is rejected with `ERR_SAME_PLAN_CLAIM` (HTTP 422). Second, the `service_state` must lie within the host plan's `service_area_states`; care rendered outside the host's licensed territory is rejected with `ERR_OUT_OF_SERVICE_AREA` (HTTP 422). Third, both the home plan and the host plan must hold `brand_license_status` of `LICENSED` at submission; a `PENDING`, `SUSPENDED`, or `REVOKED` plan on either side yields `ERR_PLAN_LICENSE_SUSPENDED`. The claim is created in `RECEIVED` status, with `priced_allowed_cents`, `current_allowed_cents`, `access_fee_cents`, `admin_charge_cents`, and `provider_payment_cents` all `null` until the workflow step that populates each of them runs.

Pricing happens in two variants, both computing an allowed amount as the lesser of the billed amount and the negotiated rate. The **provisional** variant runs immediately at submission: it looks up the host plan's rate schedule for the submitted provider and procedure whose half-open window covers the `service_date`, sets `provisional_allowed_cents` to the smaller of `billed_amount_cents` and that schedule's `negotiated_rate_cents`, and — when no schedule window covers the service date — falls back to setting `provisional_allowed_cents` equal to the full `billed_amount_cents`. The **final** variant runs when the host plan prices the claim, moving it from `RECEIVED` to `PRICED`: it looks up the same rate schedule triple but keys the half-open window on the current logical clock date — the pricing date — and sets `priced_allowed_cents` to the smaller of `billed_amount_cents` and the matched `negotiated_rate_cents`. Final pricing has no fallback: when no rate window covers the pricing date, the transition fails with `ERR_RATE_SCHEDULE_MISSING` (HTTP 422). A successful pricing also sets `current_allowed_cents` equal to `priced_allowed_cents`; `current_allowed_cents` is the running allowed amount that later adjustments will move, and it equals `priced_allowed_cents` until an adjustment applies.

Routing, performed by a `HostPlanOperator` of the host plan, moves a claim from `PRICED` to `ROUTED` and is the moment money starts accruing between the plans. Routing first re-checks that both the home and host plans are `LICENSED` (a plan suspended between submission and routing blocks the transition with `ERR_PLAN_LICENSE_SUSPENDED`), then locates the access fee schedule for the home-host pair whose closed window covers the claim's `service_date`; when none exists, routing fails with `ERR_FEE_SCHEDULE_MISSING` (HTTP 422). With the schedule in hand, the system computes two charges on the claim.

The **access fee** is tiered on `current_allowed_cents`. When the current allowed amount is at or below the schedule's `tier1_cap_cents` — the boundary is inclusive — the base fee is the flat `tier1_fee_cents`. When the current allowed amount exceeds the cap, the base fee is the full allowed amount multiplied by `tier2_rate`, rounded half-up to integer cents; the percentage applies to the entire allowed amount, not merely the excess above the cap. The base fee is then discounted when the claim's `national_account_id` references a national account that is controlled by the claim's home plan, is in `ACTIVE` status, and whose closed effective window covers the `service_date`: in that case the access fee is the base fee multiplied by one minus the schedule's `national_account_discount_pct`, rounded half-up to integer cents. When any of those conditions fails — no national account on the claim, an account controlled by a different plan, a suspended or terminated account, or a service date outside the account window — the fee is simply the undiscounted base fee. The result is stored as `access_fee_cents`.

The **administrative charge** is a cumulative marginal tiering on `current_allowed_cents` with three brackets: the slice of the allowed amount up to and including 10000 cents is charged at 5 percent; the slice above 10000 and up to and including 100000 cents is charged at 3 percent; and any slice above 100000 cents is charged at 1 percent. Each bracket's charge is computed on its own slice and rounded half-up to integer cents first, and only then are the rounded bracket charges summed — rounding per bracket and then summing is the pinned order; summing the raw slices and rounding once is forbidden. The result is stored as `admin_charge_cents`. Routing increments the claim's `version` along with every other claim mutation.

### 3.6. Benefit Determination and Provider Payment

Once routed, the claim crosses to the home plan. A `HomePlanOperator` of the home plan — and only of that plan, since the operator's identity must equal the claim's `home_plan_id` — either determines benefits or denies the claim. Benefit determination moves the claim from `ROUTED` to `BENEFIT_DETERMINED` and requires the member's `eligibility_status` to be `ACTIVE` at that moment; a member who has since been terminated causes the determination to fail with `ERR_MEMBER_INELIGIBLE` (HTTP 422). Denial moves the claim from `ROUTED` to the terminal `DENIED` state; a denied claim never generates a provider payment and never appears on any settlement line.

Payment is the host plan's act. A `HostPlanOperator` of the host plan pays a `BENEFIT_DETERMINED` claim, moving it to `PAID`. At payment the claim's `provider_payment_cents` is set equal to `current_allowed_cents`, and the host plan's ledgers move in the same operation: the payment amount is added to the host plan's `claims_paid_balance_cents`, and the sum of the claim's `access_fee_cents` and `admin_charge_cents` is added to the host plan's `fees_receivable_balance_cents`. The claim stays in `PAID` — visible to settlement sweeps — until it is either adjusted or swept into a reconciled batch, at which point it reaches the terminal `SETTLED` state.

Claims are listed with optional `home_plan_id`, `host_plan_id`, `member_id`, `national_account_id`, and `status` filters, all three roles may read them, and every claim transition described in this section increments the claim's `version`.

### 3.7. Post-Payment Adjustments and Recovery

A paid claim may be corrected through an **adjustment**, created by a `HostPlanOperator` of the host plan against a claim in `PAID` or `ADJUSTMENT_PENDING` status. The creation payload carries a free-text `reason`, a signed non-zero `delta_allowed_cents` describing the change to the allowed amount (a zero delta is rejected with `ERR_INVALID_AMOUNT`), and — per §2.7 — the `expected_claim_version` guard, under which a stale view of the claim fails with `ERR_STALE_VERSION` (HTTP 412). Creating the adjustment moves a `PAID` claim to `ADJUSTMENT_PENDING`; when the claim is already `ADJUSTMENT_PENDING`, its state is unchanged. If any earlier adjustment on the same claim is still sitting in `INITIATED` status, that prior adjustment is superseded: it transitions from `INITIATED` to `REJECTED`, and the new adjustment's `supersedes_adjustment_id` records which adjustment it replaced (`null` when there was none). The claim's `version` increments as part of the creation.

The new adjustment begins in `INITIATED` status with `recovery_amount_cents` set to 0, and then walks a two-plan handshake. Validation, performed by a `HostPlanOperator` of the host plan, moves it from `INITIATED` to `VALIDATED` and requires the parent claim to still be in `ADJUSTMENT_PENDING`. Propagation, performed by a `HomePlanOperator` of the claim's home plan, moves it from `VALIDATED` to `PROPAGATED`; propagation is the home plan's acknowledgment of the adjustment, after which any recovery becomes collectable. Application, again by the host plan, moves a `PROPAGATED` adjustment to `APPLIED` and returns the parent claim from `ADJUSTMENT_PENDING` to `PAID`. Alternatively, the home plan may reject an adjustment that is still in `INITIATED` or `VALIDATED` status, moving it to `REJECTED`; rejection reverts the parent claim from `ADJUSTMENT_PENDING` back to `PAID` with no balance change whatsoever. Every adjustment transition increments the adjustment's `version`.

Applying an adjustment runs the recovery computation. A guard applies first: an applied downward adjustment must never drive the claim's allowed amount negative, so when the claim's `current_allowed_cents` plus the signed `delta_allowed_cents` would fall below zero, the application is rejected outright with `ERR_NEGATIVE_ALLOWED` (HTTP 422) and nothing changes. Otherwise the claim's `current_allowed_cents` increases by the signed `delta_allowed_cents`. The adjustment's `recovery_amount_cents` is the magnitude of the delta when the delta is negative and the claim had been paid — that is, the larger of zero and the negated delta — and zero for any upward delta. The host plan's `claims_paid_balance_cents` is then reduced by the recovery amount; the receivables ledger is untouched by recoveries. When the claim belongs to a settlement batch that is still `OPEN`, applying the adjustment leaves the batch's net settlement to be recomputed at finalize. Adjustments are listed with optional `claim_id`, `status`, and `supersedes_adjustment_id` filters.

### 3.8. Settlement Batches and Reconciliation

Periodically the host plan sweeps what it is owed into a **settlement batch**. A `HostPlanOperator` opens a batch by naming the `debtor_plan_id` (the home plan that owes funds), the `creditor_plan_id` (the host plan owed funds, which must differ from the debtor — a batch whose creditor equals its debtor is rejected with `ERR_VALIDATION_FAILED`, HTTP 400), a closed sweep window from `period_start` through `period_end`, both ISO dates and both inclusive with the end no earlier than the start (an inverted window is rejected with `ERR_VALIDATION_FAILED`, HTTP 400), and optionally the `settlement_variant`, which must be `NET` or `GROSS` (any other value is rejected with `ERR_VALIDATION_FAILED`, HTTP 400) and defaults to `NET`. The batch begins in `OPEN` status with its totals unpopulated — `gross_claims_total_cents`, `fees_total_cents`, and `net_settlement_cents` are `null` until finalization — and the batch resource exposes no field listing its swept claims.

Finalization, performed by a `HostPlanOperator` of the creditor plan, moves the batch from `OPEN` to `FINALIZED` and runs the settlement sweep. The sweep deterministically includes every claim whose home plan is the debtor, whose host plan is the creditor, whose status is `PAID`, and whose `service_date` falls within the closed batch window; for audit replay, the swept claims are ordered by `service_date` ascending and then by `created_at` ascending. If the scope contains no `PAID` claim at all, finalization fails with `ERR_EMPTY_BATCH` (HTTP 422). From the swept claims the system computes `gross_claims_total_cents` as the sum of their `provider_payment_cents`, and `fees_total_cents` as the sum of each swept claim's `access_fee_cents` plus `admin_charge_cents`, minus the sum of the `recovery_amount_cents` over all applied adjustments attached to swept claims. The `net_settlement_cents` — the amount to be disbursed — then depends on the variant: under the `NET` variant the fees are deducted from the remittance, so the net settlement is the gross claims total minus the fees total; under the `GROSS` variant the full provider-payment gross is remitted and the fees are settled separately, so the net settlement equals the gross claims total alone.

The debtor home plan then responds. Acknowledgment by a `HomePlanOperator` of the debtor plan moves the batch from `FINALIZED` to `ACKNOWLEDGED`. Dispute, also by the debtor's operator, moves it from `FINALIZED` to `DISPUTED` instead. A disputed batch can be re-finalized by a `HostPlanOperator` of the creditor plan, moving it from `DISPUTED` back to `FINALIZED`; re-finalization recomputes all totals with the same sweep rule as the original finalization — including the `ERR_EMPTY_BATCH` (HTTP 422) failure when the re-swept scope contains no `PAID` claim — and is guarded by the `expected_settlement_batch_version` optimistic-concurrency field per §2.7, rejecting a stale view with `ERR_STALE_VERSION`. A batch may cycle `FINALIZED` to `DISPUTED` to `FINALIZED` repeatedly until it is acknowledged.

Disbursement and reconciliation belong to the association. An `AssociationAdmin` disburses an `ACKNOWLEDGED` batch, moving it to `DISBURSED`; under the `NET` variant this clears the creditor plan's receivables by subtracting the batch's `fees_total_cents` from the creditor's `fees_receivable_balance_cents`, while the creditor's `claims_paid_balance_cents` is unchanged — under the `GROSS` variant no receivables are cleared at disbursement, since fees settle separately. Finally, an `AssociationAdmin` reconciles a `DISBURSED` batch, moving it to the terminal `RECONCILED` state, at which point every swept claim transitions from `PAID` to `SETTLED`. Every batch transition increments the batch's `version`. Batches are listed with optional `debtor_plan_id`, `creditor_plan_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — a plan, a member, a national account, a rate schedule, an access fee schedule, a claim, an adjustment, a settlement batch, or an eligibility inquiry — return a `201 Created` status code. Operations that modify or transition an existing resource, and all reads, return a `200 OK` status code. The full request and response shapes of each operation are defined by the narratives in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/plans` | Register an independent licensee plan (starts PENDING) | AssociationAdmin |
| GET | `/v1/plans` | List plans; optional `brand_license_status` filter; paginated | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| GET | `/v1/plans/{id}` | Read a plan including computed balances | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| POST | `/v1/plans/{id}/activate-license` | PENDING → LICENSED | AssociationAdmin |
| POST | `/v1/plans/{id}/suspend-license` | LICENSED → SUSPENDED | AssociationAdmin |
| POST | `/v1/plans/{id}/reinstate-license` | SUSPENDED → LICENSED | AssociationAdmin |
| POST | `/v1/plans/{id}/revoke-license` | LICENSED → REVOKED (terminal); cascades controlled national accounts to TERMINATED | AssociationAdmin |
| POST | `/v1/members` | Register a member under a home plan | HomePlanOperator, AssociationAdmin |
| GET | `/v1/members` | List members; optional `home_plan_id`, `member_number`, `national_account_id` filters; paginated | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| GET | `/v1/members/{id}` | Read a member | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| POST | `/v1/members/{id}/terminate` | Member eligibility ACTIVE → TERMINATED | HomePlanOperator |
| POST | `/v1/national-accounts` | Create a national account arrangement controlled by one plan | AssociationAdmin |
| GET | `/v1/national-accounts` | List national accounts; optional `controlling_plan_id`, `status` filters; paginated | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| GET | `/v1/national-accounts/{id}` | Read a national account | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| POST | `/v1/national-accounts/{id}/activate` | PROPOSED → ACTIVE | AssociationAdmin |
| POST | `/v1/national-accounts/{id}/suspend` | ACTIVE → SUSPENDED | AssociationAdmin |
| POST | `/v1/national-accounts/{id}/reactivate` | SUSPENDED → ACTIVE | AssociationAdmin |
| POST | `/v1/national-accounts/{id}/terminate` | ACTIVE → TERMINATED | AssociationAdmin |
| POST | `/v1/rate-schedules` | Publish a host plan negotiated rate window (half-open) | HostPlanOperator, AssociationAdmin |
| GET | `/v1/rate-schedules` | List rate schedules; optional `plan_id`, `provider_npi`, `procedure_code` filters; paginated | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| GET | `/v1/rate-schedules/{id}` | Read a rate schedule | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| POST | `/v1/access-fee-schedules` | Publish the access-fee tier schedule between a home and host plan (closed window) | AssociationAdmin |
| GET | `/v1/access-fee-schedules` | List fee schedules; optional `home_plan_id`, `host_plan_id` filters; paginated | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| GET | `/v1/access-fee-schedules/{id}` | Read an access fee schedule | AssociationAdmin, HomePlanOperator, HostPlanOperator |
| POST | `/v1/claims` | Submit an inter-plan claim; provisional pricing runs immediately | HostPlanOperator |
| GET | `/v1/claims` | List claims; optional `home_plan_id`, `host_plan_id`, `member_id`, `national_account_id`, `status` filters; paginated | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| GET | `/v1/claims/{id}` | Read a claim | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| POST | `/v1/claims/{id}/price` | RECEIVED → PRICED; final pricing variant keyed on the logical clock date | HostPlanOperator |
| POST | `/v1/claims/{id}/route` | PRICED → ROUTED; access fee and admin charge computed | HostPlanOperator |
| POST | `/v1/claims/{id}/determine-benefit` | ROUTED → BENEFIT_DETERMINED by the home plan | HomePlanOperator |
| POST | `/v1/claims/{id}/deny` | ROUTED → DENIED by the home plan (terminal) | HomePlanOperator |
| POST | `/v1/claims/{id}/pay` | BENEFIT_DETERMINED → PAID; host pays the provider; host balances updated | HostPlanOperator |
| POST | `/v1/claims/{id}/adjustments` | Create an adjustment on a PAID or ADJUSTMENT_PENDING claim; OCC-guarded; supersedes a prior INITIATED adjustment | HostPlanOperator |
| GET | `/v1/adjustments` | List adjustments; optional `claim_id`, `status`, `supersedes_adjustment_id` filters; paginated | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| GET | `/v1/adjustments/{id}` | Read an adjustment | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| POST | `/v1/adjustments/{id}/validate` | INITIATED → VALIDATED by the host plan | HostPlanOperator |
| POST | `/v1/adjustments/{id}/propagate` | VALIDATED → PROPAGATED by the home plan (acknowledges recovery) | HomePlanOperator |
| POST | `/v1/adjustments/{id}/apply` | PROPAGATED → APPLIED by the host; claim returns to PAID; recovery computed | HostPlanOperator |
| POST | `/v1/adjustments/{id}/reject` | INITIATED or VALIDATED → REJECTED by the home plan; claim reverts to PAID | HomePlanOperator |
| POST | `/v1/settlement-batches` | Open a settlement batch between debtor (home) and creditor (host) plan | HostPlanOperator |
| GET | `/v1/settlement-batches` | List batches; optional `debtor_plan_id`, `creditor_plan_id`, `status` filters; paginated | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| GET | `/v1/settlement-batches/{id}` | Read a settlement batch | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| POST | `/v1/settlement-batches/{id}/finalize` | OPEN → FINALIZED; the settlement sweep computes totals | HostPlanOperator |
| POST | `/v1/settlement-batches/{id}/acknowledge` | FINALIZED → ACKNOWLEDGED by the debtor home plan | HomePlanOperator |
| POST | `/v1/settlement-batches/{id}/dispute` | FINALIZED → DISPUTED by the debtor home plan | HomePlanOperator |
| POST | `/v1/settlement-batches/{id}/refinalize` | DISPUTED → FINALIZED; totals re-swept; OCC-guarded | HostPlanOperator |
| POST | `/v1/settlement-batches/{id}/disburse` | ACKNOWLEDGED → DISBURSED; under the NET variant creditor fee receivables are cleared | AssociationAdmin |
| POST | `/v1/settlement-batches/{id}/reconcile` | DISBURSED → RECONCILED; swept claims become SETTLED | AssociationAdmin |
| POST | `/v1/eligibility-inquiries` | Host plan routes an eligibility inquiry to the home plan named by the card prefix | HostPlanOperator |
| GET | `/v1/eligibility-inquiries` | List inquiries; optional `inquiring_plan_id`, `home_plan_id`, `member_number`, `status` filters; paginated | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| GET | `/v1/eligibility-inquiries/{id}` | Read an eligibility inquiry | HomePlanOperator, HostPlanOperator, AssociationAdmin |
| POST | `/v1/eligibility-inquiries/{id}/answer` | ROUTED → ANSWERED; the home plan reports member eligibility | HomePlanOperator |
| POST | `/v1/eligibility-inquiries/{id}/reject` | ROUTED → REJECTED by the home plan | HomePlanOperator |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); startup default is 2026-09-01T00:00:00Z | AssociationAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described alongside the workflows that raise them in §2 and §3; this table is a reference summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_PLAN_CODE` | 409 Conflict |
| `ERR_DUPLICATE_MEMBER_NUMBER` | 409 Conflict |
| `ERR_PLAN_LICENSE_SUSPENDED` | 409 Conflict |
| `ERR_OUT_OF_SERVICE_AREA` | 422 Unprocessable Entity |
| `ERR_SAME_PLAN_CLAIM` | 422 Unprocessable Entity |
| `ERR_RATE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_FEE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_RATE_SCHEDULE_MISSING` | 422 Unprocessable Entity |
| `ERR_FEE_SCHEDULE_MISSING` | 422 Unprocessable Entity |
| `ERR_MEMBER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_ALLOWED` | 422 Unprocessable Entity |
| `ERR_EMPTY_BATCH` | 422 Unprocessable Entity |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
