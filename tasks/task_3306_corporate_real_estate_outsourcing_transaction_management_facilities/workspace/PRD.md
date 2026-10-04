# Corporate Real Estate Outsourcing API — Product Requirements Document

## 1. Introduction

Corporate occupiers increasingly delegate their real-estate function rather than staff it internally, and this platform is the operating system for that delegation. It supports account-based outsourcing contracts that bundle three disciplines — transaction management, project management and facilities management — under a single governance structure, so that a client's portfolio is planned, traded, and serviced through one governed book of record.

The pain this product addresses is fragmentation. Lease expirations sit in one spreadsheet, broker deployments in another, vendor service rates in a third, and the fee reconciliation that ties them together is assembled by hand at quarter end. The API therefore makes the **PortfolioAccount** the spine of every operation: leases, transaction requests, broker engagements, facilities vendors, sites, consolidation projects, scorecards, audits, data licences and transition tasks all hang off an account, and account governance determines which of them may move at any moment.

A second design goal is commercial defensibility. Commissions earned by third-party brokers may be credited against the account's management fee, key performance indicators carry both gainshare and penalty legs, and portfolio consolidation is expected to release measurable square footage. Each of those flows is specified as a conserved or reconcilable quantity so that a client, an auditor, or an adversarial implementation can verify that no cent and no square foot was created or destroyed in transit.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: who may act, what responses look like, how collections are paged, and the cross-cutting principles that every workflow in §3 inherits.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which it acts. Eight roles are recognised, and their names must be spelled exactly as follows: `AccountExecutive`, `TransactionManager`, `ApprovalAuthority`, `FacilitiesManager`, `OccupancyPlanner`, `GovernanceManager`, `DataSteward` and `TransitionManager`. A request whose `X-User-Role` header is absent or carries a value outside that enumeration is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), and a request from a recognised role that is not authorised for the operation it invokes is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `X-User-ID` header is interpreted differently depending on the acting role, and implementations must honour that difference. When `X-User-Role` is `AccountExecutive`, `X-User-ID` is the `id` of the acting **PortfolioAccount**; ownership checks on any resource that references a `PortfolioAccount` compare the resource's account foreign-key field to `X-User-ID`. When `X-User-Role` is `ApprovalAuthority`, `X-User-ID` is the `id` of the acting **AccountAssignment**; an approval-chain decision is legitimate only when an `AccountAssignment` exists whose own `id` equals the supplied `X-User-ID` and whose `account_id` equals the account of the resource being decided. The remaining six roles — `TransactionManager`, `FacilitiesManager`, `OccupancyPlanner`, `GovernanceManager`, `DataSteward` and `TransitionManager` — supply an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow captures an operator (for example on the `assignee_name` or `reviewer_name` of a record the operator authors, or on the `broker_name` of a deployed broker) but it does not compare that identifier to any entity's `id`.

Role authorisation is only the first gate. For every operation that mutates a resource carrying an `account_id`, the acting principal must also be operationally assigned to that account through the **AccountAssignment** resource; a principal with the right role but no assignment covering the account is rejected with `ERR_NOT_ASSIGNED` (HTTP 403). Account level assignment is therefore what converts a globally recognised role into a per-account permission.

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

List endpoints accept `limit` and `offset` query parameters. `limit` caps how many items are returned and defaults to 10 when omitted; it accepts no value below 1 and no value above 100, so 1 is the minimum and 100 the maximum. `offset` is the number of leading items to skip and defaults to 0. Unless a narrative below states otherwise, every list response is ordered by the resource's creation timestamp ascending. Responses to list endpoints carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the response envelope.

### 2.4. Account Governance and Lifecycle Gating

The **PortfolioAccount** carries a single stored gate field, `lifecycle_state`, and every child operation is filtered through it. The five values are `DRAFT`, `ACTIVE`, `OFFBOARDING`, `CLOSED_CONVERTED` and `CLOSED_TERMINATED`, and the gate behaves as follows. While the account is `DRAFT`, children may be created but only the account's own activation step may advance `lifecycle_state`. While it is `ACTIVE`, all child mutations are permitted. While it is `OFFBOARDING`, creation of leases and of transaction requests is blocked even though transition tasks remain permitted. While it is `CLOSED_CONVERTED` or `CLOSED_TERMINATED`, every child mutation is blocked and only reads succeed.

Child creation and mutation attempted against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409); the operations this guards are the creation of a Lease, a TransactionRequest, a Scorecard, a BrokerEngagement, a FacilitySite, a FacilitiesVendor, a ServiceLevelKpi, a ConsolidationProject, a DisciplineAudit, and an AuditReview. A mutation attempted on an account whose `lifecycle_state` is already terminal is rejected with `ERR_ACCOUNT_CLOSED` (HTTP 409), and that check runs before any business check — it guards account closure itself, lease creation, transaction-request creation and data-licence creation. Lease and transaction-request creation attempted while the account is mid-offboarding is rejected with `ERR_OFFBOARDING_PENDING` (HTTP 409).

Governance posture is a separate, derived concept that must not be confused with the lifecycle gate. `governance_posture` takes the values `NORMAL`, `ON_WATCH` and `RESTRICTED` and is rolled up from two counts: the number of **DisciplineAudit** rows on the account that are `FAILED` with `remediation_required` true, and the number of **ServiceLevelKpi** rows on the account whose `escalation_status` is `OPEN`. When the failed-and-remediable count is at least 2 the posture is `RESTRICTED`. Otherwise, when exactly one such audit exists, or when at least one open escalation exists, the posture is `ON_WATCH`. Otherwise the posture is `NORMAL`. The same rollup writes the open escalation count into `open_escalation_count` on the account. Posture is recomputed on every audit decision, on every change of a KPI row's `evaluation_state`, and on transition-task completion, and each recomputation increments the account's `version`.

### 2.5. Common Resource Properties

Every entity in this system is a top-level resource carrying the standard system-managed fields. `id` is a server-minted unique identifier formatted as a UUID with no type prefix; `created_at` is an ISO 8601 UTC timestamp recording first creation; `updated_at` is an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification; and `version` is an integer that starts at 1 and is incremented by one on every mutation, including mutations performed as a cascaded side effect rather than in direct response to a client request. All fourteen entity types — **PortfolioAccount**, **Lease**, **TransactionRequest**, **CommissionRecord**, **BrokerEngagement**, **ServiceLevelKpi**, **FacilitiesVendor**, **FacilitySite**, **ConsolidationProject**, **Scorecard**, **DisciplineAudit**, **DataLicense**, **TransitionTask**, **AccountFeeAccrual**, **AccountAssignment** and **AuditReview** — carry this full set. No entity in this system is created with the reduced two-field form; `updated_at` and `version` are present on every one of them.

Several fields are derived rather than supplied, and the derivation is part of the contract. On the account, `client_data_rights` is computed from `platform_tier` and is one of `BROKER_OWNED`, `CLIENT_OWNED_EXCLUSIVE` or `CLIENT_OWNED_SHARED`. `governance_posture`, `open_escalation_count`, `lifecycle_state`, `completion_pct_bps`, `annual_net_fee_cents`, `fee_ledger_credit_cents`, `broker_pool_allocated_cents` and `portfolio_leased_sqft` are all computed. On the lease, `expiration_bucket` (one of `UNASSIGNED`, `NEAR_TERM`, `MID_TERM`, `LONG_TERM`), `pipeline_state` and `revision_count` are computed. On a transaction request, `request_state` (one of `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `WITHDRAWN`, `EXECUTED`, `CANCELLED`), `required_approval_level` (one of `MANAGER`, `DIRECTOR`, `ACCOUNT_EXECUTIVE`), `savings_provisional_cents` and `savings_final_cents` are computed. Computed fields are never accepted from a client payload.

### 2.6. Monetary Precision and Rounding

Money is carried in integer cents in most fields, but the contract distinguishes fields that are integers from fields that are decimals, and the rounding rules differ. All monetary arithmetic that the system performs internally must be evaluated with decimal arithmetic rather than binary floating point, and every intermediate rounding step uses the round-half-up method to 2 decimal places.

Three fields are decimal rather than integer and must be returned as numbers with at most 2 decimal places: the account's `annual_net_fee_cents` and `fee_ledger_credit_cents`, and a commission record's `credit_amount_cents` and a fee accrual's `applied_credit_cents`. Fields that are declared integers are stored as integers even where the arithmetic that produces them passes through a rounded intermediate: an account's `broker_pool_allocated_cents`, a broker engagement's `deal_commission_cents`, `broker_share_cents` and `account_share_cents`, and every savings field on a transaction request or consolidation project. Input configuration values such as the vendor's `service_rate_cents_per_sqft` and a consolidation project's `cost_inflation_factor` preserve the precision they were supplied with.

Where a calculation states that a value is floored to whole basis points or to whole cents, the floor is applied to the rounded intermediate and the truncated value is what is stored. Where a calculation states that a value is rounded to zero decimal places, the integer cent result is what is stored. The specific order in which rounding and summation occur is pinned per calculation and is not interchangeable; §3 states the pinned order for each.

### 2.7. Optimistic Concurrency Control

Two write operations in this system are protected by optimistic concurrency control, and both are anchored to the **PortfolioAccount** that owns the affected resource. The client supplies its last observed account version in a field named `expected_account_version`, which is non-optional on those two requests.

Re-opening a `REJECTED` lease for another revision round requires `expected_account_version`. Because a revision re-opens the transaction approval context on the account, the revision must be priced against the account state the client actually observed; if the supplied value does not equal the account's current `version` at write time, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412). Recording a review round against a discipline audit requires `expected_account_version` for the same reason: recording the round refreshes account-level governance inputs, and it must be anchored to the state the client saw. A mismatch there is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Publishing a scorecard is OCC-protected in the same way, because publication recomputes the account's penalty and fee accrual fields.

No other endpoint accepts a version field. An implementation that requires a version on an unrelated mutation will fail clients that legitimately omit it.

### 2.8. Nested Resource Retrieval and Validation Ordering

When a path or body names several resources, the system resolves them left to right and stops at the first failure. Every path identifier and every foreign-key identifier in a body must resolve to a persisted resource; the first one that does not is reported as `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Later identifiers are not examined once an earlier one has failed, so a request targeting a child of a non-existent account reports the missing account rather than the missing child.

Validation runs in a declared priority order, and the order is observable because a single request can be wrong in several ways at once. Authentication and authorisation come first: the acting role must be declared (else `ERR_UNAUTHENTICATED`, 401), must be authorised for the operation (else `ERR_UNAUTHORIZED`, 403), and must be operationally assigned to the account through **AccountAssignment** when the target carries an `account_id` (else `ERR_NOT_ASSIGNED`, 403). Only then does the system check existence, then the target resource's own state against the transitions it has declared (else `ERR_INVALID_STATE`, 409), then the parent account's lifecycle gate (else `ERR_ACCOUNT_NOT_ACTIVE`, 409), then the terminal-account guard (else `ERR_ACCOUNT_CLOSED`, 409), then the cross-entity preconditions that depend on a sibling or child resource (else `ERR_INVALID_STATE`, 409). Business-safety, business-constraint, temporal, referential and fiscal checks follow, and a missing or wrongly typed body field is reported last as `ERR_INVALID_REQUEST` (HTTP 400). Where two business checks could both fire, the lower-numbered check in the catalogue of §5's ordering notes wins; the notable consequence is that the offboarding guard `ERR_OFFBOARDING_PENDING` (409) is evaluated after the general lifecycle gate, and the OCC check `ERR_STALE_VERSION` (412) is evaluated after every temporal business check on the same endpoint.

### 2.9. Fee Ledger Conservation and Commission Credits

The account's fee position is a conserved ledger, and three of its fields are totals that must never drift. `fee_ledger_credit_cents` is the sum of `credit_amount_cents` over every commission record on the account: posting a record raises it, and applying the credit against a fee accrual transfers value within the ledger without ever changing the total. `broker_pool_allocated_cents` is the sum of `broker_share_cents` plus `account_share_cents` over the account's broker engagements whose `engagement_state` is `EXECUTED`; executing an engagement raises it by the deal commission, and terminating that engagement must return it to exactly its prior value. `portfolio_leased_sqft` is the sum of `sqft` over the account's facility sites whose `vacancy_state` is `OCCUPIED` or `CONSOLIDATING`.

The gross fee base is tiered on portfolio size: the per-square-foot rate is 145 cents when `portfolio_sqft` is at most 250,000, 118 cents when it is at most 750,000, and 96 cents otherwise. The tier is selected from the account's current `portfolio_sqft` before any credit is applied. The account's `annual_net_fee_cents` is the gross fee — the selected tier rate multiplied by `portfolio_sqft` — reduced by the total third-party credit; self-performed credits lift the applied-credit ceiling but are never subtracted from the fee. A per-record commission credit is the record's `base_rent_cents` multiplied by its `commission_pct`, rounded half-up to 2 decimal places, and floored at a minimum of 10,000 cents; no record ever contributes less than that floor.

### 2.10. Occupancy Area Conservation and Committed Intervals

Square footage is conserved the same way money is. A site's `sqft_reduction` is the contribution it makes to its consolidation project, and it defaults to 0 when not supplied. A vendor's `sqft_reduction` defaults to 0 as well and may not be negative. A new site may not claim more than the account's remaining leasable area, which is the account's `portfolio_sqft` minus the sum of the square footage already committed by existing sites on that account; a request that exceeds it is rejected with `ERR_SITE_EXCEEDS_PORTFOLIO` (HTTP 422).

Consolidation windows are half-open intervals `[start, end)`. A vendor carries an optional committed interval through `consolidation_window_start` (inclusive, defaulting to null) and `consolidation_window_end` (exclusive, defaulting to null), and a site commits an interval when it is moved into consolidation. Two committed intervals on the same account may not overlap under half-open semantics; an overlapping interval is rejected with `ERR_SITE_OVERLAP` (HTTP 422). Lease premises are protected by a parallel rule with a different collision model: a new lease on the same account and property address may not start before the prior lease on that address ends, nor within a 30-day cooldown after it ends; a violation is rejected with `ERR_LEASE_OVERLAP` (HTTP 422).

### 2.11. Approval Chain and KPI Thresholds

Transaction requests and consolidation projects are approved by an approval-chain authority rather than by the operator who raised them. A **TransactionRequest** carries the level the decision must clear in `required_approval_level`, computed from its `prior_rent_cents_per_year` at submission: below 25,000,000 cents per year the required level is `MANAGER`; below 75,000,000 cents per year it is `DIRECTOR`; at or above 75,000,000 cents per year it is `ACCOUNT_EXECUTIVE`. Both comparisons are strict at those boundaries. A decision whose actor level is below the required level is rejected with `ERR_APPROVAL_LEVEL_INSUFFICIENT` (HTTP 422). Approval levels are ordered `MANAGER` below `DIRECTOR` below `ACCOUNT_EXECUTIVE`, and an `AccountAssignment` whose `approval_level` is omitted defaults to `MANAGER`. The `approval_level` field is only meaningful when the assignment's `assignment_role` is `APPROVAL_AUTHORITY`, and the operator creating the assignment may leave it unset.

Key performance indicators adjust the account's economics through two legs. A KPI row's `measurement_unit` is either `BPS` or `CENTS` and its `measurement_window` is either `QUARTERLY` or `ANNUAL`. The service-level shortfall base is 3,000,000 cents and the savings shortfall base is 2,000,000 cents. A row also drives escalation: when a BPS row's `actual_value` falls more than 500 basis points below its `target_value`, the row's `escalation_status` becomes `OPEN`; when a CENTS row's `actual_value` falls more than 500,000 cents below its `target_value`, the same happens. Both boundaries are strict — a shortfall of exactly 500 basis points, or of exactly 500,000 cents, does not open an escalation and leaves `escalation_status` at `NONE`. Because the count of open escalations feeds the governance posture rollup, a boundary flip changes the account's posture.

Data rights are tier-dependent and are re-evaluated against the account's current tier rather than against a historical snapshot. `client_data_rights` maps `BASIC` to `BROKER_OWNED`, `COMPLETE` to `CLIENT_OWNED_SHARED` and `ENTERPRISE` to `CLIENT_OWNED_EXCLUSIVE`. A licence that requires written client consent is rejected with `ERR_CONSENT_REQUIRED` (HTTP 422) until explicit consent is recorded, and an account transition that is attempted while an unresolved failed audit demands remediation is rejected with the same code.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Outsourcing Account

An `AccountExecutive` opens an account by supplying `account_name`, `client_name`, `portfolio_sqft` and `platform_tier`. The name is trimmed, must be between 1 and 120 characters, and must be unique across all accounts; the portfolio square footage must be at least 1; and the tier is one of `BASIC`, `COMPLETE` or `ENTERPRISE`. Creation places the account in `DRAFT`, sets `governance_posture` to `NORMAL`, and derives `client_data_rights` from the tier as described in §2.11.

Activation is the account's own move and belongs to the `AccountExecutive` alone. It requires that `lifecycle_state` currently be `DRAFT` and that `platform_tier` is declared, and it advances the account to `ACTIVE`. The side effects are heavier than they look: one **DisciplineAudit** is created for each of the three disciplines `TRANSACTION`, `FACILITIES` and `PROJECT`, each starting in `audit_state` `SCHEDULED`, `governance_posture` is recomputed, and the account's `version` is incremented. A request to activate an account that is already past `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409).

Profile fields can be amended afterwards by the same role. `account_name`, `client_name`, `portfolio_sqft` and `platform_tier` are each optional on an update, and whichever are supplied replace the stored values. Because the tier drives data rights and the square footage drives the fee tier, the update recomputes `client_data_rights` and recomputes `annual_net_fee_cents`, and it increments the account's `version` by one.

The square footage of a new site is also bounded by the portfolio it joins. A **FacilitySite** cannot be created with an `sqft` greater than the account's remaining leasable area — that is, `portfolio_sqft` minus the sum of the `sqft` of the sites already on the account — and a request that would exceed it is rejected with `ERR_SITE_EXCEEDS_PORTFOLIO`.

### 3.2. Leases, Expiration Buckets and the Revision Loop

A `TransactionManager` creates a **Lease** against an account by naming the account in `account_id` and supplying `property_address`, `market_code`, `leased_sqft`, `base_rent_cents_per_year`, `lease_start_date` and `lease_end_date`. Leased area and base rent must each be at least 1, the expiration must fall strictly after the commencement instant, and the combination of `account_id`, `property_address` and `market_code` identifies the premises. A lease begins in `PIPELINE` with `revision_count` set to 0, and its `expiration_bucket` is recomputed on every advance of the account clock. That bucket begins as `UNASSIGNED` and is one of `NEAR_TERM`, `MID_TERM` or `LONG_TERM` once the clock positions it within the expiration pipeline.

Premises are protected against double-counting. Creating a lease on an account and address that a prior lease still occupies, or that falls inside the 30-day cooldown after that prior lease ends, is rejected with `ERR_LEASE_OVERLAP` (HTTP 422). A separate temporal guard applies at submission rather than creation: a lease whose `lease_end_date` is not strictly after the account clock's current instant cannot be submitted for approval and is rejected with `ERR_LEASE_EXPIRED` (HTTP 422). A third guard watches the market as a whole and is described with the request-side workflow in §3.3.

Submission by the `TransactionManager` moves a `PIPELINE` lease to `APPROVAL_PENDING` and nothing more. From `APPROVAL_PENDING` the lease forks. Approval moves it to `BROKER_ASSIGNED` and simultaneously drives the linked transaction request to `APPROVED`; the precondition is that the linked request is currently `PENDING_APPROVAL`. Rejection moves it to `REJECTED` and drives the linked request to `REJECTED`. Both forks require the lease to be `APPROVAL_PENDING`, and a request from any other state is rejected with `ERR_INVALID_STATE`.

The distinctive loop in this workflow is revision. A `REJECTED` lease can be re-opened by the `TransactionManager` into `APPROVAL_PENDING`, which increments `revision_count` by one. At most three such re-openings are permitted: once `revision_count` has reached 3, a further revision attempt is rejected with `ERR_REVISION_LIMIT_REACHED` (HTTP 409). Because a revision re-opens the account's transaction approval context, the request must also carry `expected_account_version`, checked against the account's current `version` under §2.7; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

An approved lease is deployed rather than re-approved. Marketing launch requires the lease to be `BROKER_ASSIGNED` and requires that a **BrokerEngagement** on the lease already exist in state `ASSIGNED`; without one the request is rejected before any business check with `ERR_INVALID_STATE`, and if the lease is not `BROKER_ASSIGNED` the request is rejected with `ERR_NOT_TRANSITIONING` (HTTP 409). A successful launch moves the lease to `IN_MARKET`. Opening negotiation then requires the lease to be `IN_MARKET` and requires that the linked transaction request carry exactly one broker engagement whose `licensed_in_market` is true; a shortfall is rejected with `ERR_INVALID_STATE`. Negotiation moves the lease to `NEGOTIATING`.

### 3.3. Transaction Requests, Approval Levels and Executed Savings

Transaction-management work is raised as a **TransactionRequest**. The `TransactionManager` supplies `account_id`, `lease_id`, `request_type` — one of `RENEWAL`, `NEW_LEASE`, `RESTRUCTURE` or `DISPOSITION` — `prior_rent_cents_per_year`, `proposed_rent_cents_per_year`, `requested_term_months` and `third_party_commission_cents`, plus an optional `has_commission_credit` flag that defaults to false. Both rent figures must be at least 1 and the commission may not be negative. The request is created in `DRAFT`.

Submitting a draft has two preconditions: the request must be `DRAFT`, and the account it references must be `ACTIVE`. Submission moves the request to `PENDING_APPROVAL` and computes two derived fields at once — `required_approval_level` through the banding rule in §2.11, and `savings_provisional_cents` through the savings calculation below. Two temporal guards sit in front of this step. A lease that is overdue and still non-terminal while an already-expired lease exists on the same account and `market_code` blocks the submission with `ERR_LEASE_OVERDUE` (HTTP 422), and the expired-lease check that guards the lease's own submission in §3.2 applies here as well.

**Provisional savings** uses a market benchmark rather than the negotiated rent. The benchmark rate is 1,750 cents per square foot per year, and the benchmark annual figure is that rate multiplied by the request's lease `leased_sqft`. The term window runs from the lease's `lease_start_date` to the same instant advanced by `requested_term_months` calendar months; the window start is inclusive and the window end exclusive. Existing leases considered for the benchmark are the leases on the same `account_id` with the same `market_code` whose `lease_end_date` falls strictly after the window start. Provisional savings are the prior rent minus the benchmark annual figure, floored at zero, multiplied by `requested_term_months` and divided by 12. When more than one transaction request exists on the same lease, only the one with the earliest `created_at` contributes to the benchmark window, with ties broken by the smaller `lease_id`. The result is an integer number of cents, rounded half-up to zero decimal places.

**Final savings** uses the executed rent instead and drops the benchmark entirely: they are the prior rent minus `proposed_rent_cents_per_year`, multiplied by `requested_term_months` and divided by 12, again rounded half-up to a whole number of cents. The final figure therefore diverges from the provisional one by the difference between the benchmark annual figure and the proposed rent, scaled by the term fraction. Final savings are written to `savings_final_cents` at execution.

Decisions are taken by an `ApprovalAuthority` and are supplied as `decision` together with the `level` at which the actor is acting. The request must be `PENDING_APPROVAL` (else `ERR_INVALID_STATE`, 409); an `AccountAssignment` must exist whose `id` equals the supplied `X-User-ID`, whose `account_id` equals the request's account and whose `assignment_role` is `APPROVAL_AUTHORITY`; and the level carried on that assignment must be at least the request's `required_approval_level`, failing which the decision is rejected with `ERR_APPROVAL_LEVEL_INSUFFICIENT` (HTTP 422). An affirmative decision moves the request to `APPROVED`, and the parent lease follows to `BROKER_ASSIGNED`. A negative decision moves it to `REJECTED` and the lease follows to `REJECTED`. Either way the account's `version` is incremented.

Two terminal escapes exist before approval completes. A `DRAFT` request can be withdrawn by the `TransactionManager`, moving it to `WITHDRAWN`; a `PENDING_APPROVAL` request can be cancelled, but only while the referenced account's `lifecycle_state` is `OFFBOARDING`, in which case it moves to `CANCELLED`. A cancellation or withdrawal attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

Execution is described with the broker workflow in §3.4, since it is the broker engagement and not the request that carries the commission arithmetic.

### 3.4. Broker Deployment, Commission Splits and Fee Accruals

Deploying a broker is the `TransactionManager`'s move. A **BrokerEngagement** is created with `account_id`, `transaction_request_id`, `market_code`, `broker_name`, `licensed_in_market` and `broker_class`, where the class is either `SENIOR` or `STANDARD`. It is born in `PENDING`. Two placement rules are enforced at creation: the engagement's `market_code` must match the `market_code` of the lease on its transaction request, and a mismatch is rejected with `ERR_MARKET_MISMATCH` (HTTP 422). At assignment, the broker's `licensed_in_market` flag must be true for the market it will trade in, and an unlicensed placement is rejected with `ERR_BROKER_NOT_LICENSED` (HTTP 422). Assignment requires the engagement to be `PENDING` and licensed, and moves it to `ASSIGNED`.

Executing an engagement is where the deal commission is converted and split. The engagement must be `ASSIGNED` and its linked transaction request must be `APPROVED`; execution moves the engagement to `EXECUTED` and the request to `EXECUTED`, and computes `deal_commission_cents`, `broker_share_cents` and `account_share_cents`. The deal commission is the lesser of the request's `third_party_commission_cents` and the prior-base limit, which is 300 basis points of the request's `prior_rent_cents_per_year` — that is, `prior_rent_cents_per_year` multiplied by 300 and divided by 10,000. The request's third-party commission is consumed exactly once, so a second execution against the same request cannot mint a second pool.

The split depends on the broker's class. A `SENIOR` broker's raw share is the deal commission multiplied by 6,000 and divided by 10,000; a `STANDARD` broker's raw share uses 4,500 in place of 6,000. The `broker_share_cents` is that raw figure floored to a whole cent, and the `account_share_cents` is the deal commission minus the floored broker share, so the account absorbs the rounding remainder. The conservation invariant is exact: `broker_share_cents` plus `account_share_cents` equals `deal_commission_cents`, with no cent created or destroyed. The engagement's execution is the event that raises the account's `broker_pool_allocated_cents`.

Execution closes the transaction on both sides at once. Executing a `NEGOTIATING` lease — the `TransactionManager`'s move — requires the lease to be `NEGOTIATING`, moves it to `EXECUTED`, drives the linked transaction request to `EXECUTED`, computes the request's `savings_final_cents` through the final variant in §3.3, and creates a fresh **CommissionRecord** whose source is `THIRD_PARTY`, whose `base_rent_cents` is the request's `prior_rent_cents_per_year`, whose `commission_pct` is the request's `third_party_commission_cents` divided by that prior rent, and whose `accrual_date` is the current instant. That posting recomputes the account's `annual_net_fee_cents` through the fee rule, and the account's `version` is incremented. The same request-level effect is also reachable from the broker side, where executing an `ASSIGNED` engagement requires the request to be `APPROVED` and drives it to execution; whichever route fires first, the request's third-party commission is consumed exactly once. Execution is therefore the one workflow in which §3.3's savings rule and §3.4's commission arithmetic meet.

Termination is available from `PENDING`, from `ASSIGNED`, and from `EXECUTED`, and moves the engagement to `TERMINATED`; a request from any other state is rejected with `ERR_INVALID_STATE`. Terminating an already-executed engagement is not neutral: it sets `broker_share_cents` and `account_share_cents` back to zero, which restores the account's `broker_pool_allocated_cents` to exactly the value it held before the execution. That restoration is the reason the pool is described as conserved rather than as a running total.

The account's management fee accrues by period. An `AccountFeeAccrual` is created by the `AccountExecutive` with `account_id`, `period` and `base_fee_cents`; the period label is unique per account (for example `2026-Q1`) and the base fee may not be negative. A new accrual opens in `credit_application_state` `OPEN` with `applied_credit_cents` set to zero, and an accrual created for a period the account already carries is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Commission credits also arrive independently of accruals. An `AccountExecutive` or `TransactionManager` posts a **CommissionRecord** with `account_id`, `commission_source`, `base_rent_cents`, `commission_pct` and `accrual_date`. The source is `THIRD_PARTY` or `SELF_PERFORM`; the base rent may not be negative; and the commission percentage must lie between 0 and 0.35 inclusive. A record whose `base_rent_cents` exceeds the account's gross fee base is rejected as uncreditable with `ERR_COMMISSION_EXCEEDS_FEE` (HTTP 422). Posting computes the record's `credit_amount_cents` through the per-record rule in §2.9, recomputes the account's `annual_net_fee_cents`, and increments the account's `version`. Newly posted records carry `credited` false.

Applying credits to a fee accrual is a separate, ordered step performed by the `TransactionManager`. It requires the target accrual to be `OPEN` — an accrual that is not open is rejected with `ERR_FEE_ACCRUAL_LOCKED` (HTTP 409) — and it requires at least one commission record on the account whose `credited` flag is false; without one the request is rejected with `ERR_INVALID_STATE`. Applying the credits moves the accrual to `CREDITED`, sets its `applied_credit_cents` to the sum of the uncredited records' `credit_amount_cents`, marks each consumed record `credited` true, and recomputes the account's `annual_net_fee_cents`. The per-record contributions are ordered by `accrual_date` ascending and then by `created_at` ascending before the running sum is taken. Settlement closes the loop: settling requires the accrual to be `CREDITED` and moves it to `SETTLED`, stamping `settled_at` with the current instant, and an accrual that is not yet `CREDITED` cannot be settled.

### 3.5. Facilities Vendors, Sourcing and Service Delivery

Facilities service lines — `JANITORIAL`, `SECURITY`, `HVAC` and `LANDSCAPING` — are delivered either by the account itself or by a vendor, and the choice is carried on a **FacilitiesVendor** as `delivery_model`, one of `SELF_PERFORM` or `SUBCONTRACTED`. A vendor is created by the `FacilitiesManager` with `account_id`, `vendor_name`, `service_line`, `delivery_model`, `sourcing_program` and `service_rate_cents_per_sqft`. The sourcing programme is `DIVERSITY`, `LOCAL` or `NATIONAL`; the combination of `account_id`, `vendor_name` and `service_line` is unique; and the service rate must be strictly greater than zero. New vendors start in `SOURCING`, and their `kpi_track` — `LEVEL_A`, `LEVEL_B` or `LEVEL_C` — is derived immediately and again on every change to the delivery model or to the set of sites the vendor serves.

The tracking level follows a base-plus-override rule. The base is `LEVEL_A` when the delivery model is `SELF_PERFORM` and `LEVEL_B` when it is `SUBCONTRACTED`. That base is raised to `LEVEL_C` only when both of two conditions hold at once: the sourcing programme is `DIVERSITY`, and the vendor serves at least one site on the account whose `vacancy_state` is `OCCUPIED`. A vendor awarded under `NATIONAL` never rises above its base level.

Vendor lifecycle is tied to account governance. Activation requires the vendor to be `SOURCING` and the account's `lifecycle_state` to be either `ACTIVE` or `OFFBOARDING`, and it moves the vendor to `ACTIVE` while recomputing `kpi_track`. Suspension requires the vendor to be `ACTIVE` and the account's `governance_posture` to be either `ON_WATCH` or `RESTRICTED`, and it moves the vendor to `SUSPENDED` — so a vendor can only be stood down while the account is under scrutiny. Reinstatement requires the vendor to be `SUSPENDED` and moves it back to `ACTIVE`. Standing down a vendor while the account is not under scrutiny is rejected with `ERR_INVALID_STATE` (HTTP 409).

A site is the physical place a vendor serves. The `FacilitiesManager` creates a **FacilitySite** with `account_id`, `vendor_id`, `site_name` and `sqft`, and may additionally supply `sqft_reduction`, `consolidation_project_id`, `consolidation_window_start` and `consolidation_window_end`. The square footage must be at least 1 and is bounded by the account's remaining leasable area as described in §3.1; the reduction defaults to 0 and may not be negative; the project reference and both window endpoints default to null. Sites begin `OCCUPIED` and vacate on request, moving to `VACATED`. Vacancy is a prerequisite for consolidation, and the consolidation path is described in §3.6.

### 3.6. Occupancy Planning and Portfolio Consolidation

Consolidation is planned as a **ConsolidationProject**, created by the `OccupancyPlanner` with `account_id`, `project_name`, `planned_sqft_reduction`, `cost_inflation_factor`, `per_site_rates` and `per_site_sqft_reductions`. The planned reduction must be strictly positive and must equal the sum of the `sqft_reduction` of the sites assigned to the project. Alongside the promise the project tracks `realized_sqft_reduction`, the cumulative square footage actually released by sites that have reached `DISPOSED` and by projects that have executed. The inflation factor must be at least 1.0 but is capped at 1.10 when used, so a larger supplied factor has no additional effect. The two arrays are positional: `per_site_rates` holds a rate in cents per square foot per element and `per_site_sqft_reductions` holds a square-footage reduction per element, and element *i* of each array applies to the *i*-th site when the project's assigned sites are ordered by `created_at` ascending with ties broken by `site_name` ascending. New projects start `PLANNED`.

Sites join a project in two moves. A site is first vacated to `VACATED`, then moved into consolidation. That second move requires the site to be `VACATED`, requires the account's `governance_posture` to be `NORMAL` or `ON_WATCH` — a `RESTRICTED` account blocks it — and requires the site's `consolidation_project_id` to reference a project whose `project_state` is `APPROVED`. The move commits the interval supplied as `window_start` and `window_end`, sets the site to `CONSOLIDATING`, advances the account's open accrual's `applied_credit_cents` by the site's consolidation credit, and recomputes both the account's `portfolio_leased_sqft` and its `annual_net_fee_cents`. The window is half-open, and an interval overlapping one already committed on the account is rejected with `ERR_SITE_OVERLAP` (HTTP 422). Because consolidation depends on an approved project, moving a site whose project is not yet approved is rejected with `ERR_INVALID_STATE`.

Project approval is split across two roles. Submission by the `OccupancyPlanner` requires the project to be `PLANNED` and the account to be `ACTIVE`, moves it to `IN_REVIEW`, and computes `savings_estimate_cents` through the provisional variant below. Approval by an `ApprovalAuthority` requires an `AccountAssignment` whose `id` equals the supplied `X-User-ID` and whose `account_id` and `approval_role` make it the authority for this account; it moves the project to `APPROVED`, copies `planned_sqft_reduction` into `approved_sqft_reduction`, and recomputes `savings_estimate_cents`. A project can also be returned to planning from `IN_REVIEW`, which sets it back to `PLANNED` and zeroes `savings_estimate_cents` — this is the replan path, distinct from the approval fork, and both are reachable from `IN_REVIEW`.

Execution is gated hard. Starting execution requires the project to be `APPROVED`, requires every site assigned to the project to be in `CONSOLIDATING` or `DISPOSED`, and requires the sum of the assigned sites' `sqft_reduction` to equal `approved_sqft_reduction`; a shortfall on that sum is rejected with `ERR_SQFT_MISMATCH` (HTTP 422), and an unready site set is rejected before business checks with `ERR_INVALID_STATE`. Starting execution moves the project to `IN_EXECUTION`, computes `savings_finalized_cents` through the final variant below, and sets every assigned site to `DISPOSED`.

The two savings variants are distinguished only by the order in which rounding and summation happen, and the order is pinned. In the **provisional** variant, each site's reduction is multiplied by that site's rate, the product is rounded half-up to 2 decimal places, and the rounded products are then summed; the sum is multiplied by the effective inflation factor and the result is rounded half-up to 2 decimal places. In the **final** variant, the raw per-site products are summed first without intermediate rounding, the sum is rounded half-up to 2 decimal places once, and only then is it multiplied by the effective inflation factor and rounded half-up to 2 decimal places. The two orders diverge by exactly one cent when per-site products land on a half-cent, which is why the order is pinned rather than left to the implementer.

Cancellation is available from both `PLANNED` and `IN_REVIEW` and moves the project to `CANCELLED` while zeroing `savings_estimate_cents`; a `CANCELLED` project is terminal, as is a `COMPLETED` one.

### 3.7. Governance: Discipline Audits, Scorecards and KPI Evaluation

Governance exists to keep the account's posture honest. A **DisciplineAudit** is created by the `GovernanceManager` with `account_id`, `discipline` — `TRANSACTION`, `FACILITIES` or `PROJECT` — and `finding`. It starts `SCHEDULED`, and starting it requires the account to be `ACTIVE`, moving it to `IN_REVIEW`. The decision step takes an `outcome` and requires the audit to be `IN_REVIEW`. A passing outcome moves it to `PASSED` and sets `remediation_required` false. A failing outcome moves it to `FAILED`, sets `remediation_required` true, and stamps `cooling_off_until` with the current instant plus 72 hours. Either outcome recomputes the account's `governance_posture` through the rollup in §2.4 and increments the account's `version`. While a failed audit's cooling-off window is still open, account closure, conversion, offboarding, approval decisions and consolidation execution are all rejected with `ERR_COOLING_OFF_ACTIVE` (HTTP 422).

Review rounds are recorded against an audit by the `GovernanceManager` with `reviewer_name` and `round_notes`, and each round names the audit it examines through `discipline_audit_id`. Each round is assigned a `review_round_no`, which is the 1-based index of that round within the audit's existing reviews ordered by `created_at` ascending, and recording a round increments the account's `version`. A scorecard also tracks `adjustments_applied`, the count of commission credit adjustments that were applied to the account's fee accrual rows because of that scorecard. Because a round refreshes account-level governance inputs, the request must carry `expected_account_version` under §2.7; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

Service-level performance is graded by a **Scorecard**, created by the `GovernanceManager` with `account_id`, `service_line`, `quality_bps` and `response_bps`. Both scores are basis points bounded by 0 and 10,000 inclusive, and the service line is one of the four facilities lines. A scorecard starts `DRAFT` and reaches its terminal `PUBLISHED` state only through publication, which requires the account's `lifecycle_state` to be `ACTIVE` or `OFFBOARDING`; a scorecard that has been superseded by an operator's manual adjustment is recorded in `scorecard_state` `OVERRIDDEN` instead, and `DRAFT`, `PUBLISHED` and `OVERRIDDEN` are the only three values that field takes.

Publication is the densest cascade in the system. It computes `composite_bps` through a tier-weighted blend: when the account's `platform_tier` is `COMPLETE` or `ENTERPRISE` the quality weight is 6,000 and the response weight is 4,000, and otherwise both weights are 5,000. The weighted numerator is `quality_bps` multiplied by the quality weight plus `response_bps` multiplied by the response weight; dividing that numerator by 10,000 gives the raw composite. That raw value is rounded half-up to 2 decimal places, clamped into the range 0 to 10,000 inclusive, and then floored to a whole number of basis points, because `composite_bps` is stored as an integer. The clamp matters: a quality and response pair that both exceed 10,000 no longer separates from a pair that saturates the ceiling.

Publication then pushes into the account's key performance indicators. The account's `SLA_BPS`-tagged **ServiceLevelKpi** row — the row whose `kpi_code` carries the service-level basis-point measure — has its `actual_value` recomputed to the scorecard's `composite_bps`, and the row's `evaluation_state` becomes `EVALUATED`. That same recompute derives the row's `penalty_cents` and its `gainshare_cents` through the KPI adjustment below, writes their difference into `net_adjustment_cents`, and re-evaluates the row's escalation flag. Finally the account's `annual_net_fee_cents` is recomputed and the account's `version` is incremented. Publication is OCC-protected against the account version because it moves account-level money, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

KPI rows are created by the `GovernanceManager` with `account_id`, `kpi_code`, `kpi_family`, `measurement_unit`, `measurement_window` and `target_value`. The code is unique per account; the family is `SERVICE_LEVEL` or `SAVINGS`; the unit is `BPS` or `CENTS`; the window is `QUARTERLY` or `ANNUAL`; and the target is expressed in the row's own unit. A new row starts with `evaluation_state` `AWAITING_BASELINE` and `escalation_status` `NONE`. A row can also be evaluated on demand by supplying `actual_value`, which moves it to `EVALUATED`, computes its adjustment and escalation, recomputes the account's posture, and increments the account's `version`.

The adjustment itself is a composite rule with a pinned internal order, and both of its legs compare the same two numbers with the same inclusivity. The shortfall base is 3,000,000 cents for a `SERVICE_LEVEL` row and 2,000,000 cents for a `SAVINGS` row, and the threshold is the row's `target_value` expressed in the row's own unit. First, if `actual_value` is at least the threshold the shortfall component is zero; otherwise the shortfall component is the shortfall base multiplied by the difference between the threshold and `actual_value`, divided by 10,000, rounded half-up to 2 decimal places. Second, if `actual_value` is at least the threshold the gainshare is the excess of `actual_value` over the threshold multiplied by 2,500 basis points and divided by 10,000, rounded half-up to 2 decimal places; otherwise the gainshare is zero. Third, `penalty_cents` is the shortfall component, `gainshare_cents` is the figure from the second step, and `net_adjustment_cents` is the gainshare minus the penalty. The comparison is at-least on both legs, so an exact match produces zero shortfall and zero gainshare. Only rows whose `evaluation_state` is `EVALUATED` or `ESCALATED` participate.

### 3.8. Account Transitions, Offboarding and Closure

Offboarding begins when the `AccountExecutive` opens a transition on an `ACTIVE` account whose `governance_posture` is `NORMAL`; a restricted or watched account cannot begin offboarding, and an attempt from the wrong state is rejected with `ERR_INVALID_STATE`. Opening the transition moves the account to `OFFBOARDING`, creates **AccountTransition** rows carrying `completion_pct_bps` zero, and increments the account's `version`. While the account is `OFFBOARDING`, new leases and new transaction requests are blocked with `ERR_OFFBOARDING_PENDING` (HTTP 409).

Progress through offboarding is measured by **TransitionTask** rows rather than by AccountTransition rows. A task is created by the `TransitionManager` with `account_id`, `task_name`, `task_type`, `sequence_no`, `blocking` and `due_at`; the type is one of `DATA_HANDOVER`, `RECORDS_TRANSFER`, `VENDOR_TERMINATION` or `FINAL_RECONCILIATION`, the `blocking` flag records whether the task holds closure while it is not `DONE`, and the sequence number orders tasks within the plan. A new task starts with `task_state` `PENDING`, which is one of `PENDING`, `IN_PROGRESS`, `DONE` or `FAILED`, and it immediately triggers a recomputation of the account's `completion_pct_bps`.

Starting a task requires it to be `PENDING`, requires the account to be `OFFBOARDING`, and requires `due_at` to fall strictly after the account clock's current instant — a task whose due date has already passed is overdue and cannot be started. Completion and failure both require the task to be `IN_PROGRESS` and the account to be `OFFBOARDING`; completion moves the task to `DONE` and failure moves it to `FAILED`, and either one recomputes `completion_pct_bps` and increments the account's `version`. A separate expiry capability is reserved for the clock: once the account clock has passed a task's `due_at`, the task can be marked `FAILED`, which likewise recomputes completion and increments the account version. Note that `completion_pct_bps` counts a failed task as progress, because it measures terminality rather than success.

Completion is computed as a floored ratio. The eligible set is every task on the account — a task joins it the moment it is created and never leaves — and the progressed set is those tasks in `DONE` or `FAILED`. When there are no eligible tasks the completion is zero. Otherwise the completion is the progressed count multiplied by 10,000 and divided by the eligible count, floored to a whole number of basis points. The floor is observable: one task done out of three yields 3,333 basis points, never 3,334, and completion reaches exactly 10,000 only when every task is terminal. Closure compares against exactly 10,000 and does not accept a value at or above it from any other path.

Closure takes one of two compensating routes, both owned by the `AccountExecutive` and both reachable only from `OFFBOARDING` with `completion_pct_bps` at exactly 10,000. A closure attempted before completion is rejected with `ERR_TRANSITION_INCOMPLETE` (HTTP 422), and a closure attempted while any `blocking` task is not `DONE` is rejected with `ERR_BLOCKING_TASK_OPEN` (HTTP 422). The terminated route additionally requires that no audit on the account is `FAILED` with `remediation_required` true, and that every `FINAL_RECONCILIATION` task on the account is `DONE`; it moves the account to `CLOSED_TERMINATED` and drives the termination cascade. The converted route requires only that the account's `governance_posture` is not `RESTRICTED`; it moves the account to `CLOSED_CONVERTED` and revokes the account's data licences. Both routes conserve the account's `fee_ledger_credit_cents` and `portfolio_leased_sqft`, and both increment the account's `version`.

The termination cascade is a three-hop chain that must land in order. The first hop is the account's own closure to `CLOSED_TERMINATED`, which transitions every **FacilitiesVendor** on the account whose `vendor_state` is `ACTIVE` to `TERMINATED`. The second hop is that vendor termination, which sets every **FacilitySite** on the account whose `vendor_id` is that vendor — and which is still `OCCUPIED` — to `DISPOSED`. The third hop is a site reaching `DISPOSED`, which transitions every **DataLicense** on the account whose `data_scope` is `LINE_ITEM` to `REVOKED`. The converted route is shorter: closure to `CLOSED_CONVERTED` revokes every licence on the account directly. A vendor can also be terminated on its own by the `FacilitiesManager`, which moves it to `TERMINATED` and disposes its sites through the same second hop.

An offboarding account can be pulled back. Aborting the transition requires only that the account be `OFFBOARDING` — an abort attempted otherwise is rejected with `ERR_NOT_TRANSITIONING` (HTTP 409) — and it returns the account to `ACTIVE`, marks every non-terminal task `FAILED`, recomputes `completion_pct_bps` from the remaining task states, clears the open AccountTransition rows, and increments the account's `version`.

### 3.9. Data Rights, Licensing and the Logical Clock

Client-owned data is administered by the `DataSteward`. A **DataLicense** is requested with `account_id`, `licensee_name`, `platform_tier_at_issue` and `data_scope`. The tier at issue is `BASIC`, `COMPLETE` or `ENTERPRISE`, recorded as a snapshot of the tier in force at request time; the scope is `AGGREGATE` or `LINE_ITEM`. The licence's `license_state` starts at `REQUESTED` and is one of `REQUESTED`, `GRANTED`, `REJECTED` or `REVOKED`, and its `requires_written_client_consent` is derived immediately. Granting the licence requires it to be `REQUESTED` and requires the account's current `client_data_rights` to be something other than `BROKER_OWNED`; a `BROKER_OWNED` account cannot have its data licensed, and the attempt is rejected with `ERR_INVALID_STATE`. A grant moves the licence to `GRANTED` and recomputes `requires_written_client_consent` against the account's current tier. A request can instead be rejected, moving the licence to `REJECTED`.

Consent is the gate that keeps client-owned data from leaking. The requirement is true exactly when the account's current `client_data_rights` is `CLIENT_OWNED_EXCLUSIVE` and the licence's `data_scope` is `LINE_ITEM`. Because the requirement reads the account's current rights rather than the frozen `platform_tier_at_issue`, a tier change after the request flips the requirement, and a licence that would be granted while consent is required is rejected with `ERR_CONSENT_REQUIRED` (HTTP 422) until explicit consent is recorded through the licence's `client_consent_confirmed` flag. The same code covers the governance case from §3.7: an account closure or transition, a vendor activation, or a licence grant attempted while a failed audit with outstanding remediation is unresolved is rejected with `ERR_CONSENT_REQUIRED`.

Finally, the system runs on a logical clock rather than on wall-clock time, and the clock is a governed capability shared by the `GovernanceManager` and the `AccountExecutive`. Before any call the clock reads the fixed default `2026-09-01T00:00:00Z`, and it never falls back to the host's wall clock. The clock is set by supplying the target instant as `to_iso8601`, and the response reports the resulting `current_utc` together with `advanced_by_hours`. The clock only moves forward: a target instant that is not strictly after the clock's current value is rejected with `ERR_CLOCK_ALREADY_ADVANCED` (HTTP 409). Advancing the clock is not a passive read — it expires work. Every **TransitionTask** whose `due_at` is at or before the new instant and whose state is `PENDING` or `IN_PROGRESS` becomes `FAILED`; the affected accounts' `completion_pct_bps` is recomputed from the new task states; every lease's `expiration_bucket` is recomputed; every KPI row's `actual_value` and `escalation_status` are recomputed; and the affected accounts' `governance_posture` is recomputed through the rollup in §2.4. Because a lease can also be terminated outside the clock — the `TransactionManager` or the `AccountExecutive` can expire a lease's pipeline by moving it to `REJECTED` — the clock's recompute is the mechanism that keeps derived buckets aligned with the approved logical time rather than with the passage of real-world hours.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource, or that add a distinct new resource to a collection, return `201 Created`. These are the creations of accounts, account transitions, operator assignments, leases, transaction requests, commission records, broker engagements, KPI rows, facilities vendors, facility sites, consolidation projects, scorecards, discipline audits, audit review rounds, data licences, transition tasks and fee accruals. Every operation that modifies an existing resource — every state transition, every publication or decision, every settlement and every clock advance — returns `200 OK`. Listing and reading operations also return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/accounts` | Create a PortfolioAccount in DRAFT | AccountExecutive |
| GET | `/api/accounts` | List accounts | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}` | Read one account including derived fields | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| PUT | `/api/accounts/{id}` | Update account profile fields | AccountExecutive |
| POST | `/api/accounts/{id}/activate` | Activate a DRAFT account | AccountExecutive |
| POST | `/api/accounts/{id}/transitions` | Begin offboarding | AccountExecutive |
| POST | `/api/accounts/{id}/abort-transition` | Abort offboarding and return to ACTIVE | AccountExecutive |
| POST | `/api/accounts/{id}/close` | Close the account as CLOSED_TERMINATED | AccountExecutive |
| POST | `/api/accounts/{id}/close-converted` | Close the account as CLOSED_CONVERTED | AccountExecutive |
| GET | `/api/accounts/{id}/leases` | List the account's leases | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/commission-records` | List the account's commission records | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/service-level-kpis` | List the account's KPIs | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/facilities-vendors` | List the account's vendors | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/facility-sites` | List the account's sites | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/scorecards` | List the account's scorecards | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/discipline-audits` | List the account's discipline audits | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/data-licenses` | List the account's data licences | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/transition-tasks` | List the account's transition tasks | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/fee-accruals` | List the account's fee accruals | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/consolidation-projects` | List the account's consolidation projects | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| GET | `/api/accounts/{id}/audit-reviews` | List every audit review round on the account's audits | AccountExecutive, GovernanceManager |
| POST | `/api/accounts/{id}/assignments` | Assign an operator to the account | AccountExecutive |
| GET | `/api/accounts/{id}/assignments` | List the account's operator assignments | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| POST | `/api/account-assignments` | Assign an operator using the account in the body | AccountExecutive |
| GET | `/api/leases` | List leases with optional account filter | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| POST | `/api/leases` | Create a Lease in PIPELINE | TransactionManager |
| GET | `/api/leases/{id}` | Read a lease | AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager |
| POST | `/api/leases/{id}/submit-for-approval` | Move a PIPELINE lease to APPROVAL_PENDING | TransactionManager |
| POST | `/api/leases/{id}/approve` | Approve the pending lease | TransactionManager |
| POST | `/api/leases/{id}/reject` | Reject the pending lease | TransactionManager |
| POST | `/api/leases/{id}/revise` | Re-open a REJECTED lease into a revision round | TransactionManager |
| POST | `/api/leases/{id}/launch-marketing` | Move a BROKER_ASSIGNED lease into market | TransactionManager |
| POST | `/api/leases/{id}/open-negotiation` | Move an IN_MARKET lease into negotiation | TransactionManager |
| POST | `/api/leases/{id}/execute` | Execute a NEGOTIATING lease | TransactionManager |
| POST | `/api/leases/{id}/expire` | Mark a lease expired at the clock | TransactionManager, AccountExecutive |
| POST | `/api/lease-executions/{id}/apply` | Apply accrued credits to the open fee accrual | TransactionManager |
| GET | `/api/transaction-requests` | List transaction requests with optional filters | AccountExecutive, TransactionManager, ApprovalAuthority, GovernanceManager |
| POST | `/api/transaction-requests` | Create a TransactionRequest in DRAFT | TransactionManager |
| GET | `/api/transaction-requests/{id}` | Read a transaction request | AccountExecutive, TransactionManager, ApprovalAuthority, GovernanceManager |
| POST | `/api/transaction-requests/{id}/submit` | Submit a DRAFT request for approval | TransactionManager |
| POST | `/api/transaction-requests/{id}/decide` | Apply an approval-chain decision | ApprovalAuthority |
| POST | `/api/transaction-requests/{id}/withdraw` | Withdraw a DRAFT request | TransactionManager |
| POST | `/api/transaction-requests/{id}/cancel` | Cancel a PENDING_APPROVAL request on an offboarding account | TransactionManager |
| GET | `/api/commission-records` | List commission records with optional account filter | AccountExecutive, TransactionManager, GovernanceManager |
| POST | `/api/commission-records` | Post a CommissionRecord against the account fee | AccountExecutive, TransactionManager |
| GET | `/api/commission-records/{id}` | Read a commission record | AccountExecutive, TransactionManager, GovernanceManager |
| GET | `/api/broker-engagements` | List broker engagements with optional filters | AccountExecutive, TransactionManager, ApprovalAuthority |
| POST | `/api/broker-engagements` | Deploy a broker for a transaction request in a market | TransactionManager |
| GET | `/api/broker-engagements/{id}` | Read a broker engagement | AccountExecutive, TransactionManager, ApprovalAuthority |
| POST | `/api/broker-engagements/{id}/assign` | Assign a PENDING broker engagement | TransactionManager |
| POST | `/api/broker-engagements/{id}/execute` | Execute an ASSIGNED engagement and split the deal commission | TransactionManager |
| POST | `/api/broker-engagements/{id}/terminate` | Terminate an engagement | TransactionManager |
| GET | `/api/service-level-kpis` | List KPI rows with optional filters | AccountExecutive, GovernanceManager, FacilitiesManager |
| POST | `/api/service-level-kpis` | Create a KPI row | GovernanceManager |
| GET | `/api/service-level-kpis/{id}` | Read a KPI row | AccountExecutive, GovernanceManager, FacilitiesManager |
| POST | `/api/service-level-kpis/{id}/evaluate` | Evaluate a KPI row against its target | GovernanceManager |
| GET | `/api/facilities-vendors` | List vendors with optional account filter | AccountExecutive, FacilitiesManager, GovernanceManager |
| POST | `/api/facilities-vendors` | Create a vendor in SOURCING | FacilitiesManager |
| GET | `/api/facilities-vendors/{id}` | Read a vendor | AccountExecutive, FacilitiesManager, GovernanceManager |
| POST | `/api/facilities-vendors/{id}/activate` | Activate a SOURCING vendor | FacilitiesManager |
| POST | `/api/facilities-vendors/{id}/suspend` | Suspend an ACTIVE vendor when the posture allows | FacilitiesManager |
| POST | `/api/facilities-vendors/{id}/reinstate` | Reinstate a SUSPENDED vendor | FacilitiesManager |
| POST | `/api/facilities-vendors/{id}/terminate` | Terminate an ACTIVE vendor and dispose its sites | FacilitiesManager |
| GET | `/api/facility-sites` | List sites with optional filters | AccountExecutive, FacilitiesManager, OccupancyPlanner, GovernanceManager |
| POST | `/api/facility-sites` | Create a FacilitySite in OCCUPIED | FacilitiesManager |
| GET | `/api/facility-sites/{id}` | Read a site | AccountExecutive, FacilitiesManager, OccupancyPlanner, GovernanceManager |
| POST | `/api/facility-sites/{id}/vacate` | Vacate an OCCUPIED site | FacilitiesManager |
| POST | `/api/facility-sites/{id}/consolidate` | Commit a consolidation interval for a VACATED site | FacilitiesManager |
| POST | `/api/facility-sites/{id}/dispose` | Dispose a CONSOLIDATING site | FacilitiesManager |
| GET | `/api/consolidation-projects` | List consolidation projects with optional account filter | AccountExecutive, OccupancyPlanner, GovernanceManager |
| POST | `/api/consolidation-projects` | Create a consolidation project in PLANNED | OccupancyPlanner |
| GET | `/api/consolidation-projects/{id}` | Read a consolidation project | AccountExecutive, OccupancyPlanner, GovernanceManager |
| POST | `/api/consolidation-projects/{id}/submit` | Submit a PLANNED project for review | OccupancyPlanner |
| POST | `/api/consolidation-projects/{id}/approve` | Approve an IN_REVIEW project | ApprovalAuthority |
| POST | `/api/consolidation-projects/{id}/start-execution` | Start execution of an APPROVED project | OccupancyPlanner |
| POST | `/api/consolidation-projects/{id}/return-to-planning` | Return an IN_REVIEW project to PLANNED | OccupancyPlanner |
| POST | `/api/consolidation-projects/{id}/cancel` | Cancel a PLANNED or IN_REVIEW project | OccupancyPlanner |
| GET | `/api/scorecards` | List scorecards with optional account filter | AccountExecutive, GovernanceManager, FacilitiesManager |
| POST | `/api/scorecards` | Create a Scorecard in DRAFT | GovernanceManager |
| GET | `/api/scorecards/{id}` | Read a scorecard | AccountExecutive, GovernanceManager, FacilitiesManager |
| POST | `/api/scorecards/{id}/publish` | Publish a DRAFT scorecard | GovernanceManager |
| GET | `/api/discipline-audits` | List audits with optional account filter | AccountExecutive, GovernanceManager |
| POST | `/api/discipline-audits` | Create a DisciplineAudit in SCHEDULED | GovernanceManager |
| GET | `/api/discipline-audits/{id}` | Read an audit | AccountExecutive, GovernanceManager |
| POST | `/api/discipline-audits/{id}/start` | Start a SCHEDULED audit | GovernanceManager |
| POST | `/api/discipline-audits/{id}/decide` | Decide an IN_REVIEW audit | GovernanceManager |
| GET | `/api/discipline-audits/{id}/reviews` | List the review rounds for an audit | AccountExecutive, GovernanceManager |
| POST | `/api/discipline-audits/{id}/reviews` | Record a review round against an audit | GovernanceManager |
| GET | `/api/audit-reviews/{id}` | Read one audit review round | AccountExecutive, GovernanceManager |
| GET | `/api/data-licenses` | List data licences with optional account filter | AccountExecutive, DataSteward, GovernanceManager |
| POST | `/api/data-licenses` | Request a DataLicense | DataSteward |
| GET | `/api/data-licenses/{id}` | Read a data licence | AccountExecutive, DataSteward, GovernanceManager |
| POST | `/api/data-licenses/{id}/grant` | Grant a REQUESTED licence | DataSteward |
| POST | `/api/data-licenses/{id}/reject` | Reject a REQUESTED licence | DataSteward |
| GET | `/api/transition-tasks` | List transition tasks with optional account filter | AccountExecutive, TransitionManager, GovernanceManager |
| POST | `/api/transition-tasks` | Create a TransitionTask in PENDING | TransitionManager |
| GET | `/api/transition-tasks/{id}` | Read a transition task | AccountExecutive, TransitionManager, GovernanceManager |
| POST | `/api/transition-tasks/{id}/start` | Start a PENDING task | TransitionManager |
| POST | `/api/transition-tasks/{id}/complete` | Complete an IN_PROGRESS task | TransitionManager |
| POST | `/api/transition-tasks/{id}/fail` | Fail an IN_PROGRESS task | TransitionManager |
| POST | `/api/transition-tasks/{id}/expire` | Expire an overdue task once the clock has passed its due date | TransitionManager |
| GET | `/api/fee-accruals` | List fee accruals with optional account filter | AccountExecutive, GovernanceManager, TransactionManager |
| POST | `/api/fee-accruals` | Create an AccountFeeAccrual for a period | AccountExecutive |
| GET | `/api/fee-accruals/{id}` | Read a fee accrual | AccountExecutive, GovernanceManager, TransactionManager |
| POST | `/api/fee-accruals/{id}/settle` | Settle a CREDITED accrual | AccountExecutive |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | GovernanceManager, AccountExecutive |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_OFFBOARDING_PENDING` | 409 Conflict |
| `ERR_NOT_TRANSITIONING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BROKER_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_LEASE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_MARKET_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LEASE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SITE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_COMMISSION_EXCEEDS_FEE` | 422 Unprocessable Entity |
| `ERR_SITE_EXCEEDS_PORTFOLIO` | 422 Unprocessable Entity |
| `ERR_SQFT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_APPROVAL_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FEE_ACCRUAL_LOCKED` | 409 Conflict |
| `ERR_CLOCK_ALREADY_ADVANCED` | 409 Conflict |
| `ERR_TRANSITION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_BLOCKING_TASK_OPEN` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_LEASE_OVERDUE` | 422 Unprocessable Entity |