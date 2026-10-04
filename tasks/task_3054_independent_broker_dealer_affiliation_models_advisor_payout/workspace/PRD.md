# Broker Dealer Advisor Payout API — Product Requirements Document

## 1. Introduction

Independent broker-dealers compete for advisor talent on economics as much as on culture, and the economics are famously hard to explain. An advisor who joins under one affiliation channel is paid on a different grid than a colleague who joins under another; a book that arrives at 62 percent portability is treated differently from one that arrives at 81 percent; a transition assistance loan that looked generous at signing quietly becomes the reason a departure is blocked three years later. This document specifies the API that makes those relationships computable, auditable, and reproducible.

The platform serves four distinct operating roles. Firm-level administrators stand up branches and advisors and drive a logical clock that all window arithmetic reads. Advisor services staff act *as* a specific advisor for enrollment, affiliation, and payout work, which means most advisor-scoped calls are ownership-checked rather than merely permission-checked. Branch principals run the payout cycle and the retention contest that follows a resignation. Compliance officers own the supervisory levers: suspension, reinstatement, reopening a posted period, confirming a transfer, and settling a departure.

The requirements below cover the full arc of an advisor relationship — recruiting and enrollment, affiliation economics, loan amortization and forgiveness, periodic payout release and retroactive true-up, expense and errors-and-omissions settlement, advisory fee levelization, supervision escalation through the office of supervisory jurisdiction, departure, and the account retention contest that decides which accounts stay. Monetary values are carried in whole cents, rates in integer basis points, and every rate computation is deterministic so that two runs of the same history produce the same number.

## 2. Global Specifications & System-Wide Principles

This section states the rules that apply across the whole API: authentication and ownership, the response envelope, pagination, identifier and timestamp conventions, rate and rounding discipline, concurrency control, and the global order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` names their operational capacity. A request whose `X-User-Role` header is absent, or which names a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` at HTTP 401. A request from a recognized role that attempts an operation outside that role's grant is rejected with `ERR_UNAUTHORIZED` at HTTP 403, as is any entity-backed actor reaching for another advisor's resource.

The platform recognizes exactly four roles, spelled `PlatformAdmin`, `AdvisorOps`, `BranchManager`, and `ComplianceOfficer`.

`PlatformAdmin` is a firm-level operator that onboards branches and advisors, extends transition assistance loans, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it, but it is never compared to any entity's `id`.

`AdvisorOps` is the advisor services team acting as a specific advisor for advisor-scoped operations, and it owns enrollment, affiliation, and payouts. When `X-User-Role` is `AdvisorOps`, `X-User-ID` is the `id` of the acting `Advisor`; ownership checks on any resource that references an `Advisor` compare the resource's advisor foreign-key field to `X-User-ID`.

`BranchManager` is the supervising branch principal who runs payout periods and the retention contest. When `X-User-Role` is `BranchManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

`ComplianceOfficer` is the supervision and surveillance role that owns suspensions, reopenings, transfer confirmations, and departure settlement. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

For every operation, the platform first confirms that the acting role appears among the roles authorized for that operation; a role absent from the grant table is refused with `ERR_UNAUTHORIZED` before any resource lookup occurs. Advisors and branches are addressed in business terms throughout: advisor-scoped payloads carry `advisor_code` and branch-scoped payloads carry `branch_code`, and a branch is never addressed by its server-minted identifier in a request body.

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

List endpoints accept a `limit` query parameter that caps how many items are returned. If omitted, `limit` defaults to 10; the smallest accepted value is 1 and the largest is 100. A second query parameter, `offset`, states how many items to skip before the page begins, and defaults to 0 when omitted. Together they page through a result set without changing its contents.

Unless a requirement says otherwise, every list endpoint returns its resources ordered by creation timestamp ascending, so a page taken with a larger `offset` continues exactly where the previous page stopped.

List responses carry four pagination fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` reports the size of the full result set and `has_more` reports whether further pages exist beyond the current one.

### 2.4. Branch Supervision and the Office of Supervisory Jurisdiction

A branch is more than a reporting line: it is the supervisory container that authorizes a whole class of operations. Every branch is created from four inputs — a `branch_code` that is unique and immutable after creation, a display `name`, a `transmittal_account` the branch clears through that is likewise unique, and an `osj_name` naming the office of supervisory jurisdiction responsible for it. It also carries an `osj_enabled` flag that begins `false` and stays false until the first supervisory enrollment completes. Two fields express the branch's supervisory posture. The `state` field takes the values `SUPERVISED` and `UNSUPERVISED`, while the `status` field takes `DRAFT` and `ACTIVE`; the two move in lockstep, so a branch cannot be `ACTIVE` without being `SUPERVISED` and cannot be `DRAFT` while `SUPERVISED`. The `supervising_advisor_count` is derived from the advisor-to-branch links on the branch whose `is_supervisor` flag is true, and `current_payout_period_id` points at the payout period currently tagged to the branch, remaining null until the first period is opened for it.

Only supervisor enrollments escalate a branch. Ordinary advisor assignments — a plain link with `is_supervisor` false — never move supervision. The escalation is driven by the count of supervisors crossing from zero to one: when the first supervisor becomes enrolled, `osj_enabled` flips to true and `status` becomes `ACTIVE`; when the last supervisor is removed and no enrolled supervisor enrollment and no assigned supervisor link remains, `osj_enabled` returns to false and `status` returns to `DRAFT`. Every mutation of a branch that touches supervision also increments the branch's `version`, which is the value clients later present as `expected_branch_version`.

### 2.5. Advisor Addressability, Book Portability and Affiliation Economics

An advisor is the economic unit of the platform. Advisors are identified in every request by their `advisor_code` — a human key that is unique and immutable after creation — and by a `crd_number` that is likewise unique. The `full_name` carries the legal name. Each advisor is bound to exactly one affiliation channel through `affiliation_model`, which takes the values `IC`, `EMPLOYEE`, `HYBRID`, and `INSTITUTIONAL`, and to a home office through `primary_branch_code`, which names a branch by its `branch_code`.

Book quality is expressed through three fields. `ingested_book_total_cents` records the gross value of the production book the advisor brings in, and `book_transferred_cents` records the gross value that actually arrives at enrollment. Their ratio is exposed as `book_portability_pct`, expressed in basis points: it is the transferred value multiplied by 10000 and divided by the ingested value using integer floor division, and it is 0 whenever `ingested_book_total_cents` is 0. Whether the advisor's prior firm was a protocol signatory is carried by `protocol_eligible`, which defaults to false.

Risk posture is carried by `eo_coverage_level`, which takes the values `STANDARD`, `PREMIUM`, and `LIMITED` and defaults to `STANDARD`; the errors-and-omissions charge already settled for the current year is `eo_charge_locked_cents`, and the technology and service pass-through already settled for the current year is `pass_through_locked_cents`. Trailing production and pay history are exposed through `t12_production_cents` (the sum of `gross_commission_cents` over the advisor's released revenue in the trailing twelve months), `ytd_payout_earned_cents`, `ytd_payout_paid_cents`, and `outstanding_loan_balance_cents`. The `annual_payout_cap_hit` flag is false until the advisor's cumulative released payout reaches the annual gross payout cap. The advisor's supervision posture with respect to the contest process is `retention_status`, taking the values `NOT_AT_RISK`, `CONTESTED`, `RETAINED`, and `DEPARTED_CONFIRMED`, and the advisor's own lifecycle is `status`, taking `PROSPECT`, `ONBOARDING`, `ACTIVE`, `SUSPENDED`, `DEPARTING`, and `DEPARTED`.

### 2.6. Common Resource Properties

All fourteen primary resources in the platform carry the same system-managed fields, and no resource in this API sets `common_fields` to false:

- `**id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix or kind marker embedded in it.
- `**created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `**updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, recording when the resource was last modified. Any mutation of the resource — including a derived-field recomputation driven by a child's transition — refreshes this field.
- `**version` (integer):** A system-managed integer that increments by one on every modification to the resource. Clients read it to drive the optimistic concurrency contract described in §2.8.

Every write operation that changes a resource returns the updated resource in the `data` field of the envelope, so the caller observes the new `version` without a follow-up read.

### 2.7. Money, Basis-Point Rate Arithmetic and Rounding Discipline

Monetary fields are integer cents. Rate and ratio fields — `provisional_base_rate_bps`, `amortization_rate_bps`, `retention_rate_bps`, `rafee_effective_bps`, `book_portability_pct`, and `retention_ratio_bps` — are integers expressed in basis points, where 10000 basis points is the whole. No monetary or rate value is ever transmitted as a floating-point decimal.

Every rounding step in the platform uses the same method: round half up, applied once at the point the scaffolded rule names. Where a computation sums per-entry amounts, the rounding happens per entry and the rounded entries are then summed; summing first and rounding once produces a different number and is not the specified behavior. Where a computation divides to obtain a ratio — `book_portability_pct` and `retention_ratio_bps` — the division is integer floor division rather than half-up rounding, and a zero denominator yields 0. Where a computation applies a percentage of a principal as an integer — the forgiveness milestone amount — the division is floor division and is not rounded.

One consequence deserves emphasis because it is easy to get wrong: the errors-and-omissions pool is computed against the gross payout basis before any expense pool reduces it, and is never clipped by the expenses that precede it in the waterfall, so a negative true-up does not shrink the errors-and-omissions charge. Only regulatory pass-through rows are subject to clipping against what remains of the payout basis.

### 2.8. Optimistic Concurrency Control and the Staleness Rejection

Clients mutate branch-scoped and advisor-scoped aggregates by presenting the version they last observed. Two request fields carry that observation: `expected_branch_version` for aggregates whose parent is a `Branch`, and `expected_advisor_version` for aggregates whose parent is an `Advisor`. Any endpoint whose declared input includes one of these fields requires it; omitting it is a malformed request and is rejected with `ERR_INVALID_REQUEST` at HTTP 400.

A mismatch between the supplied value and the parent's current `version` is rejected with `ERR_STALE_VERSION` at HTTP 412 — the value the client observed is stale, and the server refuses to compute against a view it can no longer reproduce. Three of these guards are worth calling out individually because the aggregate that advances is not the resource the client is addressing.

The payout-period lifecycle endpoint `POST /payout-periods/{id}/state`, which closes, posts, reopens, or voids a period, requires `expected_branch_version` matching the `Branch` the period is tagged to. Any advisor link, account move, or supervisory enrollment on that branch legitimately advances the branch's `version`, so a client holding a pre-change view is rejected with `ERR_STALE_VERSION` (HTTP 412).

The payout-line settlement endpoint `POST /advisor-payout-lines/{id}/settlement` requires `expected_advisor_version` matching the `Advisor` the line belongs to. A release, a loan amortization, or a book move advances the advisor's `version`, and a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Transition opening at `POST /transitions` requires `expected_advisor_version` matching the target `Advisor`. Account freezes, loan balance changes, and retention flags all advance the advisor's `version`, and a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Lifecycle transitions are requested by naming the target state rather than the transition: a payout period is moved by supplying `to_state`, while a supervisory enrollment, an advisor link, an advisor, and an expense pass-through row are moved by supplying `to_status`. In both cases the named value must be a state the entity's model permits from where it currently stands, and the same request may also carry the version field that guards the parent aggregate.

The same rule binds every other endpoint whose declared input carries a version field: updating branch descriptive fields, advancing or revoking a supervisory enrollment, deactivating or reactivating an advisor link, recomputing a period on the true-up path, updating an advisor's book or coverage tier, moving an advisor through enrollment, affiliation, suspension, reinstatement, departure, or departure settlement, correcting a registration number, releasing an advisor's open book for transfer, closing the retention contest, and booking a forgiveness milestone.

### 2.9. Nested Resource Retrieval and Identifier Resolution Order

Requests that address a resource through a nested path segment — where the path carries a parent identifier and then a child identifier — are validated left to right. The platform resolves the first identifier in the path before it attempts to resolve any subsequent identifier, and rejects the request immediately with the error that corresponds to the first identifier that does not resolve. A subordinate resource addressed through a parent that does not exist therefore never produces a "child not found" error; the caller learns that the parent is missing.

Identifier resolution follows a fixed precedence by the kind of key involved. A `branch_code` that does not resolve to a branch yields `ERR_BRANCH_NOT_FOUND` at HTTP 404. An `advisor_code` that does not resolve to an advisor yields `ERR_ADVISOR_NOT_FOUND` at HTTP 404. A server-minted identifier — the `id` of an `Account`, `RevenueEntry`, `PayoutPeriod`, `AdvisorPayoutLine`, `PayoutLoan`, `LoanAmortizationEntry`, `ExpensePassThrough`, `AdvisoryRevenueSplit`, `TransitionRecord`, `AccountRetention`, `AdvisorBranchLink`, or `BranchSupervisorEnrollment` — that does not resolve to a resource of the type the path implies yields `ERR_NOT_FOUND` at HTTP 404. The mount point of the API is the server root.

### 2.10. Global Validation Order and Rejection Precedence

When several checks could apply to the same request, the platform evaluates them in a fixed order and reports the first failure. The order below is binding: a request that would fail two checks is rejected with the error of the earlier check.

1. Authentication: `X-User-Role` must be present and must name a declared role, otherwise `ERR_UNAUTHENTICATED` (401).
2. Authorization: the acting role must appear in the operation's grant set, and for entity-backed roles the acting principal must own the resource, otherwise `ERR_UNAUTHORIZED` (403).
3. Retention-contest slot: a contest may only be opened for an account whose status is `PENDING_TRANSFER`; an account already contested, already retained, or already `TRANSFERRED_OUT` cannot be contested again for the same payout period, otherwise `ERR_INVALID_STATE` (409).
4. Payout cap: opening a payout line requires that the line's period is tagged to the advisor's primary branch and that the advisor's `annual_payout_cap_hit` is not already true, otherwise `ERR_PAYOUT_CAP_REACHED` (409).
5. Supervisory suspension: an advisor can only be suspended or reinstated from a supervised branch — the branch named by the advisor's `primary_branch_code` must have `state` `SUPERVISED`, and no draft revenue entry may remain — otherwise `ERR_INVALID_STATE` (409).
6. Period uniqueness: the combination of `branch_code`, `year`, `month`, and `period_index` may hold only one payout period, otherwise `ERR_PERIOD_ALREADY_EXISTS` (409).
7. Existence of the branch named by `branch_code`, otherwise `ERR_BRANCH_NOT_FOUND` (404).
8. Existence of the advisor named by `advisor_code`, otherwise `ERR_ADVISOR_NOT_FOUND` (404).
9. Existence of a path-resolved server-minted identifier, otherwise `ERR_NOT_FOUND` (404).
10. Staleness of `expected_branch_version` or `expected_advisor_version`, otherwise `ERR_STALE_VERSION` (412).
11. Logical clock: any operation that reads twelve-month or twenty-four-hour window arithmetic requires that the clock has been set, otherwise `ERR_CLOCK_NOT_SET` (409).
12. Period openness: no payout period tagged to the advisor's primary branch may be `OPEN` or `REOPENED`, and the period being closed or posted must be tagged to the branch addressed, otherwise `ERR_PERIOD_NOT_CLOSED` (409).
13. Coverage: the advisor's errors-and-omissions coverage must not be `LIMITED` and the relevant branch's office of supervisory jurisdiction must be active, otherwise `ERR_EO_COVERAGE_INSUFFICIENT` (403).
14. Book portability: the advisor's portability ratio must meet the threshold the operation requires, and the advisor must be a protocol signatory when the ratio alone is insufficient, otherwise `ERR_BOOK_PORTABILITY_BELOW_MINIMUM` (422).
15. Loan settlement: the advisor's transition assistance loan balance must be zero, or the loan must be discharged by departure settlement, otherwise `ERR_LOAN_BALANCE_OUTSTANDING` (409).
16. Period posting state: the period a retention contest or book transfer consumes must not be already `PAID` or `VOID`, otherwise `ERR_PERIOD_ALREADY_POSTED` (409).
17. From-state: the resource must be in the state the requested transition requires, otherwise `ERR_INVALID_STATE` (409).
18. Child settleability: no child row of the aggregate may still be pending — no account of the advisor may be `FROZEN` and no retention row of the transition may still be `PENDING` — otherwise `ERR_FROZEN_ACCOUNTS_REMAIN` (409).

### 2.11. The Logical Clock

All window arithmetic — the trailing twelve months of production, the twelve-month milestone window on a loan, and the twenty-four-hour supervisory hold before a transfer confirms — is evaluated against a logical clock, not against wall-clock time. Until the clock is set, it reads the fixed startup default `2026-09-01T00:00:00Z` and must never fall back to the host's real time. Setting the clock is a privileged capability: a request carrying `current_utc` moves the clock, and every subsequent window calculation is evaluated against the new instant. An operation that depends on window arithmetic and runs before the clock has been set is rejected with `ERR_CLOCK_NOT_SET` at HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Recruiting and Onboarding an Advisor into the Grid

The relationship begins when a firm-level administrator creates an advisor record. The payload carries the advisor's business identity (`advisor_code`, `crd_number`, `full_name`), the economics (`affiliation_model`, `ingested_book_total_cents`, `book_transferred_cents`, `protocol_eligible`) and the home office (`primary_branch_code`), with the coverage tier (`eo_coverage_level`) optional and defaulting to `STANDARD`. A newly created advisor sits at `status` `PROSPECT` with `retention_status` `NOT_AT_RISK`, and its `book_portability_pct` is derived immediately from the transferred and ingested values. Recruiting lists arrive through a bulk capability whose payload is an array of `advisors`; each parsed row is created at `PROSPECT`, while a row whose branch or advisor code does not resolve is skipped without rolling back the rows that were accepted, and the response reports `created_count`, `skipped_count`, `created_advisor_codes`, and `skipped_advisor_codes`.

Book portability is the first economic gate an advisor must clear, and it is expressed in basis points. A book that transferred 5,000 basis points or more of its ingested value clears the affiliation minimum; below that the affiliation is refused with `ERR_BOOK_PORTABILITY_BELOW_MINIMUM` at HTTP 422. Portability alone is not sufficient at the low end of the range: unless the advisor's prior firm was a protocol signatory, the ratio must reach 7,000 basis points, and an advisor who is neither a signatory nor above that ratio is refused with `ERR_PORTABILITY_PROTOCOL_FAILURE` at HTTP 403. The same ratio gates the retirement of an advisor's book from the branch later in the lifecycle, where a transfer requires at least 6,000 basis points.

Enrollment is the only door into the payout grid. Moving an advisor from `PROSPECT` to `ONBOARDING` requires that the advisor has a non-empty `crd_number`, that the branch named by `primary_branch_code` exists, and — mirroring the real transition-assistance contract — that a transition assistance loan for the advisor already exists in `REQUESTED` or `ACTIVE` status. Enrollment without such a loan is refused with `ERR_NO_TRANSITION_LOAN` at HTTP 409.

Activation is the second door. Moving an advisor from `ONBOARDING` to `ACTIVE` requires all four of: portability of at least 5,000 basis points; either protocol eligibility or portability of at least 7,000 basis points; a `primary_branch_code` whose branch has `status` `ACTIVE` (otherwise `ERR_BRANCH_NOT_ACTIVE` at HTTP 409); and an `eo_coverage_level` other than `LIMITED` (otherwise `ERR_EO_COVERAGE_INSUFFICIENT` at HTTP 403). Activation sets the advisor's `status` to `ACTIVE`, resets `retention_status` to `NOT_AT_RISK`, and cascades every transition assistance loan of that advisor from `REQUESTED` to `ACTIVE`. Jumping straight from `PROSPECT` to `ACTIVE` is not a legal path and is refused with `ERR_INVALID_STATE`.

Advisors are attached to branches through link records that carry `advisor_code`, `branch_code`, `assignment_type` (either `PRIMARY` or `SECONDARY`), and an `is_supervisor` flag that defaults to false. Creating a link starts it at `ASSIGNED`, recomputes the branch's `supervising_advisor_count`, and advances the branch's `version`. Deactivating or reactivating a link moves it between `ASSIGNED` and `INACTIVE`, recomputes the supervisor count, and likewise advances the branch's version — which is why a client that cached a branch version before a link change must refresh it before closing a period.

### 3.2. Transition Assistance Loans: Amortization, Forgiveness and Discharge

A transition assistance loan is the firm's bet on an advisor's future production, and it is created with four inputs: `advisor_code`, the `principal_cents`, the `amortization_rate_bps` that every release draw will repay against it, and the `forgiveness_milestone_pct` that will retire part of the principal once a production milestone is met. The principal is strictly positive and may not exceed 50,000,000 cents (the parity principal cap). A new loan sits at `status` `REQUESTED` with `remaining_balance_cents` equal to `principal_cents` and `milestone_progress_cents` at zero. The `amortization_rate_bps` must be strictly positive, and the milestone percentage may be 0 and may not exceed 100.

A loan is conserved by construction: at every point the `principal_cents` equals the `remaining_balance_cents` plus the sum of all posted amortization amounts plus the sum of all posted forgiveness amounts. Nothing may over-repay: a draw is clipped so that the loan is never paid beyond zero. Amortization rows are addressed by the loan they reduce, `payout_loan_id`, and by the period the draw came from, `payout_period_id`.

Amortization is driven by release. When a payout line is released, the draw is the line's `release_amount_cents` multiplied by the loan's `amortization_rate_bps` and divided by 10000, rounded half up to whole cents, and then clipped to whatever balance remains. The draw is recorded as a `LoanAmortizationEntry` at `status` `POSTED` against the loan and the `payout_period_id` it came from, `remaining_balance_cents` falls by that amount, and the loan moves to `AMORTIZING`. A period may also be amortized directly through a dedicated capability that takes a `payout_period_id` and posts the draw for that period. An amortization draw recomputes the advisor's `outstanding_loan_balance_cents` but does not advance the advisor's `version`.

A negative true-up behaves differently from a positive one. A positive true-up is income and is paid out; it never touches the loan. A negative true-up is a shortfall, and the whole signed amount is added back to the loan balance by posting a `LoanAmortizationEntry` whose `amortization_amount_cents` is negative, with `remaining_balance_cents` rising by the same magnitude. Because the entry is signed, the conservation identity still holds. When a payout period is reopened, the compensating entry posted by the true-up is voided and the balance is restored.

Forgiveness runs on a milestone measured over production. `milestone_progress_cents` is the sum of `gross_commission_cents` over the advisor's revenue entries, counting only those in `RELEASED` or `TRUE_UP_APPLIED` status, whose `production_date` falls within the twelve months following the first released entry for the loan and no later than the current clock, and it is capped at the milestone threshold. The milestone threshold is the `principal_cents` multiplied by the `forgiveness_milestone_pct` and divided by 100, rounded half up. When `milestone_progress_cents` reaches that threshold, `forgiveness_amount_cents` is the `principal_cents` multiplied by the milestone percentage using integer floor division by 100 — this division is floor-divided and is not rounded — clipped so that it never exceeds the remaining balance; the balance falls by that amount and the loan becomes `FORGIVEN`. If instead the balance has reached zero without a milestone, the loan settles at `REPAID`.

A loan is discharged when the advisor's departure is settled. At settlement a `LoanAmortizationEntry` is posted carrying a `forgiveness_amount_cents` equal to whatever balance remains, the `remaining_balance_cents` is set to zero, and the loan's `status` becomes `DISCHARGED`. A supervisory audit export surfaces the loan's `loan_id`, `principal_cents`, `remaining_balance_cents`, `milestone_progress_cents`, `milestone_threshold_cents`, `configured_forgiveness_milestone_pct`, `gross_commission_sum_cents`, `milestone_matured`, and `status`, and an amortization schedule export reports the `amortization_total_cents`, the `milestone_forgiveness_applied_cents`, and the residual `remaining_balance_cents`.

### 3.3. Payout Periods and the Production Basis

Payout is organized into periods, and a period belongs to a branch. It is opened with `branch_code`, the `year`, the `month` from 1 through 12, and a `period_index` from 1 through 5 — five periods are permitted within a calendar month. The combination of branch, year, month, and index may exist only once; a duplicate is refused with `ERR_PERIOD_ALREADY_EXISTS` at HTTP 409. A new period begins at `state` `OPEN` and `status` `OPEN`, and opening it points the branch's `current_payout_period_id` at the new period and advances the branch's `version`.

Revenue is booked before it can be paid. A revenue entry carries the producing `advisor_code`, the `account_id` it was generated against, a `product_type` (`EQUITY`, `MUTUAL_FUND`, `ANNUITY`, `BROKERAGE_TRAIL`, or `ADVISORY`), a strictly positive `gross_commission_cents`, and a `production_date`. Entries are created at `status` `DRAFT` and contribute to no basis until released. Release is available one entry at a time or, on departure, en masse for the whole draft book. An entry may only be released while its owning account is `OPEN` or `FROZEN`; an account that has reached `TRANSFERRED_OUT` can no longer earn and the release is refused with `ERR_INVALID_STATE`. Release recomputes the advisor's trailing-twelve-month production and the period's gross.

Back-dating is honored. An entry's `production_date` — not its creation order — determines which period's calendar month it belongs to, and therefore which month's gross and which advisor's payout base it feeds. Within a month, entries are processed by `production_date` ascending, with creation order breaking ties. The period's `period_gross_cents` is the sum of `gross_commission_cents` over released entries whose `production_date` falls in the period's calendar month.

Periods advance through `OPEN`, `CLOSED`, `PAID`, `REOPENED`, and `VOID`, and the `state` and `status` fields mirror each other. Closing requires at least one entry produced in the period's calendar month by an advisor on the period's branch that has status `RELEASED` — an empty period is refused with `ERR_PERIOD_HAS_NO_RELEASED_PRODUCTION` at HTTP 409 — and requires that no such entry is still `DRAFT`, otherwise `ERR_PERIOD_HAS_DRAFT_ENTRIES` at HTTP 409. Posting requires the same cleanliness over the whole month for advisors on the period's branch: every entry must be `RELEASED` or `TRUE_UP_APPLIED`, and every payout line's `provisional_base_rate_bps` must equal the grid base rate for its `projected_annual_production_cents`, otherwise `ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH` at HTTP 409. A period may be voided only from `CLOSED` and only while no line of the period has been released or true-upped; otherwise `ERR_PERIOD_ALREADY_POSTED` at HTTP 409, and voiding moves every draft line of the period to `VOID`. Going `PAID` and then `REOPENED` and then `PAID` again is a reachable cycle.

Posting a period is the heaviest single operation in the system. It sets the period to `PAID`; releases every draft line of the period at its provisional rate, computing the line's `release_amount_cents` with no true-up applied; posts every pending expense pass-through row of the period and pins its `amount_cents`; posts every pending advisory revenue split of the period and pins its `advisory_revenue_cents`; and amortizes loans. Specifically, for each advisor whose line is released, a loan still at `ACTIVE` becomes `AMORTIZING` and receives the draw described in §3.2. Posting also recomputes `period_payout_cents`, and it may flip an advisor's `annual_payout_cap_hit` to true when cumulative released payout reaches the annual gross payout cap. Advancing a period requires `expected_branch_version` matching the branch the period is tagged to; a stale value is refused with `ERR_STALE_VERSION` at HTTP 412.

Reopening a posted period reverses what posting did, and it is a compliance action. Every line of the period that carries a true-up returns to `RELEASED` with its `true_up_amount_cents` reset to zero; every loan amortization entry posted by the period is voided and its balance restored; every expense pass-through row the period posted returns to `PENDING`; and every advisory revenue split the period posted is voided. Re-posting after a reopening applies exactly the posting cascade again. `period_payout_cents` and `true_up_amount_cents` are recomputed at each step.

A payout line is opened explicitly for an advisor within a period, with `payout_period_id` and the `projected_annual_production_cents` that will serve as the provisional tier basis. It begins at `status` `DRAFT`, and its `provisional_base_rate_bps` is derived from that projected basis. The projected basis is immutable once the line is released. Opening a line is subject to the payout cap check of §2.10: the period must be tagged to the advisor's primary branch and the advisor's cumulative released payout must not already have reached the annual gross payout cap, otherwise `ERR_PAYOUT_CAP_REACHED` at HTTP 409. A released line can be recomputed through the true-up path, and a line whose period is not in a state that permits true-up — the period must be `CLOSED`, `PAID`, or `REOPENED` — is refused with `ERR_PERIOD_NOT_CLOSED` at HTTP 409.

### 3.4. The Payout Grid: Provisional Release and Retroactive True-Up

Rates are produced by a two-stage grid. The first stage maps the production basis to a base rate in basis points: below 100,000,000 cents the base is 7,000; from 100,000,000 cents up to but not including 250,000,000 cents the base is 8,000; and at 250,000,000 cents and above the base is 9,000. The boundaries are inclusive on the lower side — a basis of exactly 100,000,000 cents lands in the 8,000 tier and a basis of exactly 250,000,000 cents lands in the 9,000 tier, while 249,999,999 cents remains in the 8,000 tier.

The second stage adjusts that base twice. A product delta is added according to `product_type`: `EQUITY` adds 0, `MUTUAL_FUND` subtracts 500, `ANNUITY` subtracts 700, `BROKERAGE_TRAIL` subtracts 300, and `ADVISORY` adds 500. An affiliation offset is then subtracted according to `affiliation_model`: `IC` subtracts 0, `EMPLOYEE` subtracts 500, `HYBRID` subtracts 250, and `INSTITUTIONAL` subtracts 6,500. The result is finally clamped into the band from 500 basis points to 9,000 basis points inclusive. When the clamp raises a rate that would otherwise have fallen below the floor, the computed rate is not the rate the client asked for and the operation reports `ERR_RATE_FLOOR_APPLIED` at HTTP 422.

Two variants of the same grid are computed at different moments, and the distinction is the heart of retroactive true-up. The provisional rate uses the line's `projected_annual_production_cents` as the tier basis and applies the entry's product delta and the advisor's affiliation offset; every entry of the period is paid at that single rate. The final rate uses the advisor's cumulative year production up to and including each entry as the tier basis, so two entries in the same period may be paid at different rates when the year's production straddles a tier boundary. Cumulative production sums `gross_commission_cents` over the advisor's entries in calendar-year order by `production_date` ascending, breaking ties by creation order, up to and including the entry being priced. Only entries in `RELEASED` or `TRUE_UP_APPLIED` status count toward any basis; `DRAFT` and `VOID` entries are excluded from every basis without exception.

A line's `release_amount_cents` is not a rounded total; it is the sum of per-entry rounded amounts. Each entry's contribution is its `gross_commission_cents` multiplied by the applicable rate and divided by 10000, rounded half up to a whole cent, and the contributions are then added. Entries are processed in `production_date` ascending order with creation order as the tie-break. A line that has not yet been true-upped contributes at the provisional rate; a line whose final rate applies contributes at the final rate per entry.

The true-up recomputes the period against the final grid and applies the signed difference. The final income is the sum over the period's entries of each entry's gross multiplied by its final grid rate and divided by 10000, rounded half up. The provisional income is the sum over the same entries of each entry's gross multiplied by the single provisional rate and divided by 10000, rounded half up. The line's `true_up_amount_cents` is the final income minus the provisional income, and it is signed: when cumulative year production has crossed into a higher tier the true-up is positive and adds income to the advisor's released payout for the period, and when the year's production leaves the advisor at a lower effective rate than the provisional basis implied, the true-up is negative and is applied against the loan balance as described in §3.2 rather than reducing the released amount. A true-up also recomputes the line's `release_amount_cents` at the final applied rate, recomputes the period's `true_up_amount_cents` and `period_payout_cents`, and recomputes the advisor's `ytd_payout_earned_cents`. The line moves from `RELEASED` to `TRUE_UP_APPLIED`. True-up is refused with `ERR_INVALID_STATE` when the line has not been released, and with `ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH` when the line's provisional base rate does not match the grid base rate for its projected basis.

### 3.5. Expense Pass-Throughs and the Net Settlement Waterfall

The firm recovers technology, clearing, and regulatory costs from advisors, and carries errors-and-omissions coverage charges as a separate pool. These are raised as expense pass-through rows, each carrying the billed `advisor_code`, the `payout_period_id` it draws from, a `category` of `TECHNOLOGY`, `CLEARING`, `E_AND_O`, or `REGULATORY`, and a `billing_model` that is either `FLAT_MONTHLY` or `PCT_OF_GROSS`. Rows are created at `status` `PENDING` with their `amount_cents` derived only when the period is posted or the settlement is computed. A row may be pinned to `POSTED`, which fixes its `amount_cents`, or waived to `WAIVED`, which removes it from the waterfall entirely. Only rows in `PENDING` or `POSTED` participate in settlement.

Settlement is a strictly ordered waterfall, and the order changes the answer.

The first step establishes the payout basis: the period's `period_payout_cents` plus the period's `period_true_up_amount_cents`.

The second step fills the expense pool. Pass-through rows are walked in ascending `category` order. A row billed on a percentage basis takes the payout basis multiplied by its category rate and divided by 10000, rounded half up; a row billed flat takes its category's fixed amount. The percentage rates are 200 basis points for `TECHNOLOGY`, 100 basis points for `CLEARING`, and 50 basis points for `REGULATORY`; the flat amounts are 3,000,000 cents for `TECHNOLOGY`, 500,000 cents for `CLEARING`, and 600,000 cents for `REGULATORY`. Each row's amount is then clipped so that it never exceeds what the payout basis can still absorb after the rows already processed — the clip is the larger of zero and the payout basis minus the pool accumulated so far — and the clipped amount is added to the pool. The running total after all rows is the `pass_through_cents`.

The third step fills the errors-and-omissions pool, and it is computed on the payout basis measured *before* the expense pool is subtracted, not on the remainder. The rows walked here are those in the `E_AND_O` and `REGULATORY` categories, again in ascending `category` order. Every such row takes the payout basis multiplied by the errors-and-omissions rate for the advisor's `eo_coverage_level` and divided by 10000, rounded half up; the rates are 120 basis points for `STANDARD`, 350 basis points for `PREMIUM`, and 900 basis points for `LIMITED`. Each amount is clipped so that it does not exceed the payout basis minus the already-computed `pass_through_cents` minus the errors-and-omissions pool accumulated so far, and the clipped amounts sum to the `eo_charge_cents`. Because the regulator category participates in both pools, only `REGULATORY` rows are clipable against the payout basis, while `E_AND_O` rows are not — they are never reduced by the expenses that precede them. The practical consequence is that a negative true-up shrinks the payout basis and can therefore shrink the expenses collected, but it does not shrink the errors-and-omissions charge.

The fourth step is the net. The `net_settlement_cents` is the payout basis minus the `pass_through_cents` minus the `eo_charge_cents`, floored at zero so that a settlement is never negative. Only after that net is established is the supervisory override keyed on it: the `supervisory_override_cents` is the net settlement multiplied by the override rate for the advisor's `affiliation_model` and divided by 10000, rounded half up. The override rates are 0 basis points for `IC`, 0 for `EMPLOYEE`, 100 for `HYBRID`, and 250 for `INSTITUTIONAL`. A settlement call returns `net_settlement_cents`, `pass_through_cents`, `eo_charge_cents`, and `supervisory_override_cents`, and it pins the advisor's expense rows for the period to their computed amounts. The advisor's `eo_charge_locked_cents` and `pass_through_locked_cents` track what has already been settled for the year, and the annual gross payout cap that flips `annual_payout_cap_hit` is 500,000,000 cents; the cap flags the payout rather than truncating an already-released line, so a release at or past the cap is paid in full and only a subsequent line opening is refused.

### 3.6. Advisory Fee Levelization and the Revenue Split

Advisory accounts are billed annually rather than per trade, and the platform levelizes those fees so that two advisors carrying comparable books are credited comparably. An account records whether it is `ADVISORY` or `BROKERAGE` through `account_type`, its `balance_cents`, and — for advisory accounts — its `annual_fee_cents`. The account also carries whether it is `held_away` from the firm, in which case it is excluded from revenue splits altogether, and the `fee_levelized` flag that marks it as already swept this year. An account is opened at `status` `OPEN` with `fee_levelized` false.

Levelization runs as a sweep for one advisor's accounts in one period, and it only touches accounts that are advisory, not held away, and not already levelized. When an account enters its first sweep its `base_annual_fee_cents` is stamped from its current `annual_fee_cents` and never changed again, preserving the fee the account started the year with. The account's effective rate is then `rafee_effective_bps`, computed as the base fee multiplied by 10000 and divided by the balance, rounded half up, or 0 when the balance is zero. The levelization delta is the balance multiplied by the difference between the levelization target of 85 basis points and the effective rate, divided by 10000, rounded half up once on the signed result — a single rounding on the delta, not on its components. The account's `annual_fee_cents` is then rewritten to the base fee plus the delta, so that a second sweep within the same calendar year finds the account already levelized and leaves it untouched.

The advisor's `advisory_revenue_cents` for the account is the base fee multiplied by a portability-banded rebate rate and divided by 10000, rounded half up, with the levelization delta added to that result. The rebate bands are read from the advisor's `book_portability_pct`: band one applies 6,000 basis points when portability is at least 0 and below 6,000; band two applies 7,000 basis points when portability is at least 6,000 and below 8,000; and band three applies 8,000 basis points when portability is at least 8,000 and at most 10,000. The credited advisory revenue is finally clipped so that it does not exceed 30,000,000 cents. Each swept account produces an `AdvisoryRevenueSplit` row at `status` `POSTED` carrying the `account_id`, the `payout_period_id`, the `advisory_fee_cents` allocated to the period, the `brokerage_revenue_cents` that the same account generated from `BROKERAGE_TRAIL` entries in the same period, the credited `advisory_revenue_cents`, and the `levelization_delta_cents`. When every eligible advisory account of the advisor has already been levelized for the calendar year, the sweep is refused with `ERR_YEAR_ALREADY_LEVELIZED` at HTTP 409. Brokerage accounts never enter levelization; their economics flow exclusively through `BROKERAGE_TRAIL` revenue entries.

A transferred account is closed out of the sweep: when an account reaches `TRANSFERRED_OUT`, its `fee_levelized` flag is set to true so that no further sweep can touch it, and the advisor's draft revenue entries are voided at the same moment.

### 3.7. Supervision, Suspension and Departure

Supervision is conferred by enrollment. A supervisory enrollment is opened with `branch_code`, the `advisor_code` of the advisor being enrolled as supervisor, and an `effective_date`; it begins at `status` `REQUESTED`. The lesson of this design is that the office of supervisory jurisdiction identity is always the acting advisor, so a branch is addressed by its `branch_code` and never by a server-minted identifier. Advancing an enrollment from `REQUESTED` to `ENROLLED` requires that no other enrollment on the branch is already `ENROLLED` — a second concurrent supervisor is refused with `ERR_INVALID_STATE` — and it sets the branch's `state` to `SUPERVISED`, its `osj_enabled` to true, and its `status` to `ACTIVE`, recomputing `supervising_advisor_count`. Revoking an enrollment, or deactivating the last assigned supervisor link, returns the branch to `UNSUPERVISED`, `osj_enabled` false, and `status` `DRAFT`, provided no enrolled supervisor enrollment and no assigned supervisor link remains and no payout period tagged to the branch is `OPEN` or `REOPENED`. The two guards are evaluated in that order: a branch that still carries an enrolled supervisor enrollment or an assigned supervisor link is refused with `ERR_INVALID_STATE` at HTTP 409, and only once the branch is genuinely down to zero supervisors does an open or reopened period block the demotion with `ERR_PERIOD_NOT_CLOSED` at HTTP 409. Demotion re-blocks every operation that requires a supervised branch.

Suspension is supervisory rather than voluntary, and it is a compliance action. Moving an advisor from `ACTIVE` to `SUSPENDED` requires that the advisor's primary branch has `state` `SUPERVISED` and that no revenue entry of the advisor is still `DRAFT`; either condition failing yields `ERR_INVALID_STATE`. Suspension freezes every `OPEN` account of the advisor. Reinstatement from `SUSPENDED` to `ACTIVE` requires the same branch-level supervision, and it returns every `FROZEN` account to `OPEN`; because reinstatement releases the freeze that suspension applied, the pair `SUSPENDED` and `ACTIVE` forms a reachable cycle. Neither direction may proceed while any account of the advisor remains frozen in a way the settlement rules do not permit, which is refused with `ERR_FROZEN_ACCOUNTS_REMAIN` at HTTP 409. A frozen account cannot receive new revenue entries until it returns to `OPEN`.

Departure begins when advisor services starts the process. Moving an advisor from `ACTIVE` to `DEPARTING` requires that the advisor's `outstanding_loan_balance_cents` is exactly zero — otherwise `ERR_LOAN_BALANCE_OUTSTANDING` at HTTP 409 — and that no payout period tagged to the advisor's primary branch is `OPEN` or `REOPENED`, otherwise `ERR_PERIOD_NOT_CLOSED` at HTTP 409. Departure freezes every `OPEN` account of the advisor, releases every `DRAFT` revenue entry of the advisor so that frozen books still earn, and moves `retention_status` to `CONTESTED` when a transition record is opened for the advisor, leaving it `NOT_AT_RISK` otherwise.

A departure can be reversed. Reinstatement from `DEPARTING` to `ACTIVE` requires that no transition record for the advisor has reached `SETTLED`, otherwise `ERR_TRANSITION_ALREADY_SETTLED` at HTTP 409. It returns every `FROZEN` account and every `RETENTION_CONTESTED` account to `OPEN`, and sets `retention_status` to `RETAINED`. This is the cycle edge that makes `DEPARTING` and `ACTIVE` mutually reachable, and it reverses the freeze cascade that departure applied.

Departure settles only after the retention contest resolves. Moving an advisor from `DEPARTING` to `DEPARTED` requires that the advisor's transition record has reached `SETTLED` — otherwise `ERR_TRANSITION_NOT_SETTLED` at HTTP 409 — and that every retention row of that transition is in `POSTED`, `RETAINED`, or `LOST` status, otherwise `ERR_INVALID_STATE`. Settlement sets the advisor to `DEPARTED`; moves every `POSTED` retention row of the transition to `RETAINED`; discharges every loan still at `ACTIVE` or `AMORTIZING` as described in §3.2, driving `outstanding_loan_balance_cents` to zero; sets `retention_status` to `DEPARTED_CONFIRMED`; and moves every `RELEASED` revenue entry of the advisor to `TRUE_UP_APPLIED`.

### 3.8 Book Transfer, Retention Contests and Departure Settlement

An advisor's book leaves the branch through transfers that honor a supervisory hold, and the accounts that might leave are contested before they go.

Book transfer is started by advisor services for a departing advisor. Moving an advisor's open accounts out requires that the advisor's `status` is `DEPARTING` or `DEPARTED` — otherwise `ERR_INVALID_STATE` — and that the advisor's `book_portability_pct` is at least 6,000 basis points, otherwise `ERR_BOOK_PORTABILITY_BELOW_MINIMUM` at HTTP 422. Every `OPEN` account of the advisor moves to `PENDING_TRANSFER`, and as it does so the account's `pending_transfer_at` is stamped with the current logical clock, because the supervisory window is measured from that instant and from nothing else.

Confirming the transfer is a separate, delayed act. An account in `PENDING_TRANSFER` may only be confirmed once the logical clock is at or after its `pending_transfer_at` plus twenty-four hours — exactly twenty-four hours having passed is sufficient — and a confirmation attempted earlier is refused with `ERR_TRANSFER_HOLD_PERIOD` at HTTP 409. Confirmation also requires an active office of supervisory jurisdiction, so an advisor with `LIMITED` coverage or a branch that is not supervised is refused with `ERR_EO_COVERAGE_INSUFFICIENT` at HTTP 403. Confirming moves the account to `TRANSFERRED_OUT`, sets its `fee_levelized` flag, and voids the owning advisor's draft revenue entries so that an account that has left can no longer earn against the firm.

Before the window closes, an account can be contested. A transition record is opened for a departing advisor with the `advisor_code` and the `payout_period_id` the departure is booked in; it starts at `CONTESTED` when the advisor's `status` is `DEPARTING` and the advisor has at least one account in `FROZEN`, `PENDING_TRANSFER`, or `RETENTION_CONTESTED` status, and at `PENDING` otherwise. Opening it derives `accounts_in_contest_count` from the frozen book and sets the advisor's `retention_status` to `CONTESTED`. A contest may only be opened for an account whose status is `PENDING_TRANSFER`; an account already contested, already retained, or already `TRANSFERRED_OUT` cannot be contested again within the same period, so the combination of `payout_period_id` and `account_id` is occupied for the life of the contest, and a repeated attempt is refused with `ERR_INVALID_STATE`. Contests and retention rows are addressed through the transition they belong to, `transition_record_id`, and a contest is refused with `ERR_TRANSITION_NOT_CONTESTED` at HTTP 409 when the transition it targets is not in `CONTESTED` status. A contest is also refused while the period it consumes is already `PAID` or `VOID`, with `ERR_PERIOD_ALREADY_POSTED` at HTTP 409.

Contesting an account grants it a retention credit and moves it to `RETENTION_CONTESTED`. A retention row moves through the statuses `PENDING`, `POSTED`, `RETAINED`, `LOST`, and `VOID`, and a newly contested account is written `POSTED`; only `POSTED` rows count toward the contest's settled book credit and toward the retention ratio, and a row that is voided while still `PENDING` is excluded from both, returning its account to the transfer window with `pending_transfer_at` re-stamped. The credit is recorded as `credit_amount_cents` on the retention row, computed from the account's `balance_cents` and the row's `retention_rate_bps`: the balance multiplied by the rate and divided by 10000, rounded half up, and then clipped by whatever remains of the book's retention credit cap. That rate must be strictly positive. The cap is 200 basis points of the advisor's `book_transferred_cents` — the transferred book value multiplied by 200 and divided by 10000, rounded half up — and it is consumed as a running watermark in ascending `account_number` order. Critically, the watermark is consumed by posted rows only: a lost row keeps its recorded credit and does not release cap, so a reversal never frees a slot for another account. When the watermark has already reached the cap, no further account can be contested and the attempt is refused with `ERR_RETENTION_CREDIT_EXHAUSTED` at HTTP 409, with no row posted. An advisor who arrived with no transferred book value has a cap of zero, so the very first contest against such an advisor is refused the same way.

The contest closes on a retention ratio measured in basis points, and only posted rows count toward it — a row still `PENDING` contributes to neither side of the ratio. While the contest is open, `accounts_retained_count` counts the advisor's accounts currently sitting at `RETENTION_CONTESTED`; the closing call replaces it with the number of accounts submitted as retained. The ratio is `accounts_retained_count` multiplied by 10000 and divided by `accounts_in_contest_count` using integer floor division, and it is 0 when the contest count is 0. The firm's target is 7,000 basis points.

Closing the contest as retained submits `account_ids_retained`, the accounts the firm kept, and the ratio is measured from that list's length against `accounts_in_contest_count`. The close is refused with `ERR_RETENTION_TARGET_MISSED` at HTTP 409 when the ratio falls below 7,000 basis points, and with `ERR_INVALID_STATE` when any submitted account does not carry a `POSTED` retention row on this transition. On success the transition becomes `SETTLED`; every submitted account and its retention row become `RETAINED`; every other contested account and its row become `LOST` and return to `PENDING_TRANSFER` with `pending_transfer_at` re-stamped; every frozen account of the advisor is returned to `OPEN`; `accounts_retained_count` is set from the submitted list; and the advisor's `retention_status` becomes `RETAINED`.

Closing the contest as lost submits `account_ids_lost`, the accounts the firm failed to keep, and every account not named in that list is treated as retained. This close is refused with `ERR_RETENTION_TARGET_MET` at HTTP 409 when `account_ids_lost` multiplied by 10000 and floor-divided by `accounts_in_contest_count` exceeds the shortfall of 10000 minus 7,000 basis points — that is, when the ratio has already reached the target, the contest cannot be recorded as lost. On success the transition becomes `SETTLED`; every submitted account and its row become `LOST` and the accounts return to `PENDING_TRANSFER` with `pending_transfer_at` stamped; every other contested account and its row become `RETAINED`; `accounts_retained_count` is set to `accounts_in_contest_count` minus the submitted list; and the advisor's `retention_status` becomes `DEPARTED_CONFIRMED`. Both closes require `expected_advisor_version` matching the advisor.

Two supporting levers round out the contest. A pending retention row may be voided, which excludes it from the transition's book credit set and returns the account to `PENDING_TRANSFER` with `pending_transfer_at` re-stamped. The transition's `settled_amount_cents` is the sum of credit amounts over its `POSTED`, `RETAINED`, and `LOST` rows, with `VOID` rows excluded, and `retention_credit_cents` on the transition records the contest credit granted to the advisor.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection, return `201 Created`. Operations that modify an existing resource — including advancing a lifecycle state, releasing or true-upping a payout line, settling a contest, or running a computational sweep — return `200 OK`. Every endpoint returns the standard envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; the clock reads 2026-09-01T00:00:00Z until set | PlatformAdmin |
| POST | `/branches` | Create a branch | PlatformAdmin |
| GET | `/branches` | List branches | PlatformAdmin, BranchManager, ComplianceOfficer |
| GET | `/branches/{id}` | Get a branch | Any |
| PATCH | `/branches/{id}` | Update branch descriptive fields under optimistic concurrency | PlatformAdmin |
| GET | `/branches/{id}/advisor-links` | List the advisor links on a branch | Any |
| GET | `/branches/{id}/payout-periods` | List the payout periods tagged to a branch | Any |
| GET | `/branches/{id}/supervisor-enrollments` | List the supervisory enrollments on a branch | PlatformAdmin, BranchManager, ComplianceOfficer |
| POST | `/branch-supervisor-enrollments` | Open a supervisory enrollment on a branch | PlatformAdmin, BranchManager |
| POST | `/branch-supervisor-enrollments/{id}/state` | Advance or revoke a supervisory enrollment | PlatformAdmin, BranchManager |
| GET | `/advisor-links` | List advisor-to-branch links | Any |
| GET | `/advisor-links/{id}` | Get an advisor link | Any |
| POST | `/advisor-links` | Assign an advisor to a branch | AdvisorOps, BranchManager, PlatformAdmin |
| POST | `/advisor-links/{id}/state` | Deactivate or reactivate an advisor link | AdvisorOps, BranchManager, PlatformAdmin |
| POST | `/advisors` | Create an advisor record | PlatformAdmin, AdvisorOps |
| GET | `/advisors` | List advisors | Any |
| GET | `/advisors/{id}` | Get an advisor | Any |
| PATCH | `/advisors/{id}` | Update book transfer value, protocol status or coverage tier | AdvisorOps, PlatformAdmin |
| POST | `/advisors/{id}/enrollment` | Move an advisor from PROSPECT to ONBOARDING | AdvisorOps |
| POST | `/advisors/{id}/affiliation` | Activate an advisor under an affiliation model | AdvisorOps |
| POST | `/advisors/{id}/state` | Suspend or reinstate an advisor | ComplianceOfficer |
| POST | `/advisors/{id}/departure` | Begin an advisor departure | AdvisorOps |
| POST | `/advisors/{id}/departure/settle` | Settle a departure into DEPARTED | ComplianceOfficer |
| POST | `/advisors/{id}/departure/reinstate` | Reverse a departure | AdvisorOps |
| POST | `/advisors/{id}/payout-lines` | Open a payout line for the advisor in a period | AdvisorOps, BranchManager |
| GET | `/advisor-payout-lines` | List advisor payout lines | Any |
| GET | `/advisor-payout-lines/{id}` | Get an advisor payout line | Any |
| POST | `/account-retentions/{id}/state` | Void a pending retention row | BranchManager |
| POST | `/advisor-payout-lines/{id}/settlement` | Net the payout basis against the expense and errors-and-omissions pools | BranchManager, AdvisorOps |
| POST | `/advisors/{id}/crd-change` | Supervisory correction of the registration number | PlatformAdmin, ComplianceOfficer |
| POST | `/advisors/bulk-import` | Bulk onboard a recruiting list of advisors | PlatformAdmin, AdvisorOps |
| POST | `/accounts` | Open a client account under an advisor | AdvisorOps, BranchManager |
| GET | `/accounts` | List accounts | Any |
| GET | `/accounts/{id}` | Get an account | Any |
| GET | `/accounts/{id}/advisory-splits` | List the advisory revenue splits of an account | AdvisorOps, BranchManager, ComplianceOfficer |
| GET | `/accounts/{id}/revenue-entries` | List the revenue entries of an account | Any |
| POST | `/advisors/{id}/book-transfer` | Start moving an advisor's open accounts out | AdvisorOps |
| POST | `/accounts/{id}/transfer/confirm` | Confirm a book transfer after the supervisory hold period | AdvisorOps, ComplianceOfficer, BranchManager |
| POST | `/revenue-entries` | Book a commission or fee entry against an account | AdvisorOps, BranchManager |
| GET | `/revenue-entries` | List revenue entries | Any |
| GET | `/revenue-entries/{id}` | Get a revenue entry | Any |
| POST | `/revenue-entries/{id}/release` | Release a single draft revenue entry into the payout basis | AdvisorOps, BranchManager |
| POST | `/revenue-entries/{id}/release` | Release a single draft revenue entry into the payout basis | AdvisorOps, BranchManager |
| POST | `/payout-periods` | Open a payout period for a branch | BranchManager, PlatformAdmin |
| GET | `/payout-periods` | List payout periods | Any |
| GET | `/payout-periods/{id}` | Get a payout period | Any |
| POST | `/payout-periods/{id}/state` | Advance a payout period through CLOSED, PAID, REOPENED and VOID | BranchManager, ComplianceOfficer |
| POST | `/payout-periods/{id}/true-up` | Recompute a released payout line on cumulative year production | BranchManager, AdvisorOps |
| POST | `/payout-periods/{id}/net-settlement` | Compute the net settlement for one advisor in the period | BranchManager, AdvisorOps |
| GET | `/payout-periods/{id}/payout-lines` | List the payout lines of a period | Any |
| GET | `/payout-periods/{id}/expense-pass-throughs` | List the expense pass-through rows of a period | BranchManager, AdvisorOps, ComplianceOfficer |
| POST | `/payout-loans` | Create a transition assistance loan | AdvisorOps, PlatformAdmin |
| GET | `/payout-loans` | List transition assistance loans | AdvisorOps, PlatformAdmin, ComplianceOfficer |
| GET | `/payout-loans/{id}` | Get a transition assistance loan | Any |
| GET | `/payout-loans/{id}/amortization-entries` | List the amortization entries of a loan | AdvisorOps, ComplianceOfficer, PlatformAdmin |
| GET | `/payout-loans/{id}/forgiveness-audit` | Supervisory audit export for a loan | AdvisorOps, ComplianceOfficer, PlatformAdmin |
| GET | `/payout-loans/{id}/amortization-schedule` | Amortization schedule projection for a loan | AdvisorOps, ComplianceOfficer, PlatformAdmin |
| POST | `/payout-loans/{id}/amortize` | Post the period's amortization draw against a loan | AdvisorOps, BranchManager |
| POST | `/payout-loans/{id}/forgive` | Book the forgiveness milestone against a loan | AdvisorOps, PlatformAdmin |
| GET | `/loan-amortization-entries` | List loan amortization entries | AdvisorOps, ComplianceOfficer, PlatformAdmin |
| GET | `/loan-amortization-entries/{id}` | Get a loan amortization entry | AdvisorOps, ComplianceOfficer, PlatformAdmin |
| POST | `/expense-pass-throughs` | Raise an expense pass-through line for an advisor in a period | AdvisorOps, BranchManager |
| GET | `/expense-pass-throughs` | List expense pass-through rows | Any |
| GET | `/expense-pass-throughs/{id}` | Get an expense pass-through row | Any |
| POST | `/expense-pass-throughs/{id}/state` | Waive or settle an expense pass-through row | BranchManager, AdvisorOps |
| POST | `/advisory-splits/levelize` | Run the advisory fee levelization sweep | AdvisorOps, BranchManager |
| GET | `/advisory-splits` | List advisory revenue splits | Any |
| GET | `/advisory-splits/{id}` | Get an advisory revenue split | Any |
| POST | `/transitions` | Open a transition record for a departing advisor | AdvisorOps, BranchManager |
| GET | `/transitions` | List transition records | Any |
| GET | `/transitions/{id}` | Get a transition record | Any |
| GET | `/transitions/{id}/retention-rows` | List the account retention rows of a transition | AdvisorOps, BranchManager, ComplianceOfficer |
| POST | `/transitions/{id}/retention/contest` | Contest one account onto a transition | BranchManager |
| POST | `/transitions/{id}/retention/settle` | Close the retention contest on the retained accounts | BranchManager |
| POST | `/transitions/{id}/retention/lose` | Close the retention contest on the lost accounts | BranchManager |
| GET | `/account-retentions` | List account retention rows | Any |
| GET | `/account-retentions/{id}` | Get an account retention row | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_BRANCH_NOT_FOUND` | 404 |
| `ERR_ADVISOR_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CLOCK_NOT_SET` | 409 |
| `ERR_PERIOD_ALREADY_EXISTS` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_PERIOD_HAS_NO_RELEASED_PRODUCTION` | 409 |
| `ERR_PERIOD_HAS_DRAFT_ENTRIES` | 409 |
| `ERR_PERIOD_ALREADY_POSTED` | 409 |
| `ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH` | 409 |
| `ERR_EO_COVERAGE_INSUFFICIENT` | 403 |
| `ERR_BOOK_PORTABILITY_BELOW_MINIMUM` | 422 |
| `ERR_PORTABILITY_PROTOCOL_FAILURE` | 403 |
| `ERR_LOAN_BALANCE_OUTSTANDING` | 409 |
| `ERR_NO_TRANSITION_LOAN` | 409 |
| `ERR_BRANCH_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FROZEN_ACCOUNTS_REMAIN` | 409 |
| `ERR_TRANSITION_ALREADY_SETTLED` | 409 |
| `ERR_TRANSITION_NOT_SETTLED` | 409 |
| `ERR_TRANSITION_NOT_CONTESTED` | 409 |
| `ERR_RETENTION_TARGET_MET` | 409 |
| `ERR_RETENTION_TARGET_MISSED` | 409 |
| `ERR_RETENTION_CREDIT_EXHAUSTED` | 409 |
| `ERR_TRANSFER_HOLD_PERIOD` | 409 |
| `ERR_YEAR_ALREADY_LEVELIZED` | 409 |
| `ERR_RATE_FLOOR_APPLIED` | 422 |
| `ERR_PAYOUT_CAP_REACHED` | 409 |