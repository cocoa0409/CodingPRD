# Wholesale Broker Channel API — Product Requirements Document

## 1. Introduction

The Wholesale Broker Channel API supports the lender-side operating system for a wholesale mortgage business: the bank funds loans that independent mortgage brokerages originate, and every one of those brokerages must be vetted, priced, monitored and, when necessary, constrained. This document specifies the behaviour of the service that manages that relationship end to end — broker approval with licensing verification and financial review, an intraday pricing engine that turns rate sheets into point-and-rate quotes, broker-prepared loan submission, underwriter decisions, turn-time commitments with escalation, post-funding quality control, and repurchase exposure. All resources described here are mounted under the `/wholesale-channel` prefix.

The commercial stakes explain the strictness of the rules that follow. A wholesale channel is only viable if the lender can trust the broker's licence coverage at the moment a file is submitted, if the broker's compensation election is economically consistent with the plan it nominates, and if the price quoted to a borrower can be reconstructed exactly from the sheet that produced it. Regulatory exposure is asymmetric: a single loan funded on a lapsed licence in the property state, or a broker left unrestricted after repeated competitor-exclusivity breaches, is a materially larger loss than a slow quarter. The service therefore prefers explicit refusal — a clear error identifier at a determinate point in the workflow — over a silently permissive path.

The functional surface spans four roles on the lender side (`ChannelManager`, `Underwriter`, `ComplianceOfficer`, `QualityControlAnalyst`), one broker-side role (`BrokerUser`), an operational role for the logical clock (`PlatformAdmin`) and a blanket authenticated reader (`Any`). Because broker files are prepared by the broker and underwritten by the lender, the platform additionally enforces separation of duties: the person who underwrites a loan is never the person who later reviews its quality. Broker-facing tooling, training and lead programs are out of scope for this service; the requirements below cover the channel's transactional and compliance surface only.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must present two mandatory headers: `X-User-ID`, carrying the acting identity, and `X-User-Role`, carrying the acting capacity. If either header is absent, or if `X-User-Role` names a role that the system does not declare, the request is refused with `ERR_MISSING_USER_CONTEXT` and a `400 Bad Request` status. A caller whose role is not permitted for the endpoint being invoked is refused with `ERR_INSUFFICIENT_PERMISSIONS` and a `403 Forbidden` status.

The system declares exactly seven role names, and they are spelled `PlatformAdmin`, `ChannelManager`, `Underwriter`, `ComplianceOfficer`, `QualityControlAnalyst`, `BrokerUser` and `Any`. `PlatformAdmin` operates the logical clock and holds no loan, pricing or compliance authority whatsoever. `ChannelManager` is the lender-side wholesale account manager: broker onboarding decisions, licence recording, financial reviews, product eligibility decisions, exclusivity policies, compensation plans, rate sheet publication and turn-time escalation resolution. `Underwriter` owns the underwriting and closing decision surface on submitted loans and may not price, elect compensation, or review quality. `ComplianceOfficer` owns licence revocation and may not approve brokers, underwrite, or review quality. `QualityControlAnalyst` performs post-funding file review, defect resolution and repurchase exercise, and must not also be the loan's underwriter. `Any` designates any authenticated caller and appears only on read endpoints, which apply no ownership filter.

When `X-User-Role` is `BrokerUser`, `X-User-ID` is the `id` of the acting `Broker`; ownership checks on any resource that references a `Broker` compare the resource's foreign-key field to `X-User-ID`. A `BrokerUser` that invokes a broker-scoped operation for a `broker_id` other than its own `X-User-ID` is refused with `ERR_BROKER_RESOURCE_FORBIDDEN` and a `403 Forbidden` status. When `X-User-Role` is `PlatformAdmin`, `ChannelManager`, `Underwriter`, `ComplianceOfficer`, `QualityControlAnalyst` or `Any`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a rule demands it — for example, as `underwriter_id` on an `UnderwritingDecision`, as `reviewer_id` on a `QualityControlReview` — but never compares it to any entity's `id`.

Finally, the platform enforces a segregation-of-duties rule that cuts across the lender-side roles: the reviewer of a loan's post-funding quality review must not be the underwriter named on that loan's most recent final `UnderwritingDecision`. A violation of that rule is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` and a `403 Forbidden` status.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless a specific ordering is stated for an endpoint, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope. Single-resource reads and mutations carry only `api_request_id` and `api_request_timestamp`, plus the pagination block when the endpoint returns a collection. The closing-pipeline read is not a plain resource list but still carries the pagination block, because it is served over a `limit`/`offset` query surface.

### 2.4. Broker Standing, Automatic Suspension and Reinstatement

A brokerage's standing is not a purely manual decision. The service continuously derives four risk signals on the `Broker` — `rolling_quality_score`, `open_defect_tier`, `financial_strength_score` and `exclusivity_status` — and an `APPROVED` broker is moved to `SUSPENDED` automatically the moment any of four triggers holds. The triggers are evaluated in a fixed first-match order, and the `suspended_reason` records the first one that is true: first, when `rolling_quality_score` is less than 40.00, the reason is `QUALITY`; failing that, when `open_defect_tier` is at least 5, the reason is `DEFECTS`; failing that, when `financial_strength_score` is less than 40.00, the reason is `FINANCIAL`; and failing all of those, when `exclusivity_status` is `BLOCKED`, the reason is `EXCLUSIVITY`. Because the first three are score or count comparisons, they are made at two decimal places for the two scores and as integer comparisons for the defect tier.

This re-evaluation is not a scheduled job; it runs after every `QualityControlReview` creation, after every financial-review decision, after every recomputation of `exclusivity_status`, and on every advance of the logical clock. The same four signals gate manual recovery: a `SUSPENDED` broker may be reinstated to `APPROVED` only when `rolling_quality_score` is at least 60.00, `open_defect_tier` is at most 2, and `exclusivity_status` is not `BLOCKED` — a request that fails the quality gate is refused with `ERR_BROKER_QUALITY_BELOW_REINSTATEMENT`, and one that fails the defect gate is refused with `ERR_BROKER_DEFECT_HOLD`.

Reinstatement is compensating, not generative. If an operator brings `rolling_quality_score` and `financial_strength_score` back to at least 60.00, brings `open_defect_tier` back to at most 2, brings `exclusivity_status` back to `CLEAR`, and then reinstates, the broker returns to `APPROVED` and its `active_loan_count`, `rolling_funded_volume_cents` and `total_active_compensation_commitment_cents` are exactly the values they held immediately before the suspension — the system adds nothing and removes nothing. Every one of these derived-field reconciliations independently mutates the `Broker`, refreshing its `updated_at` and incrementing its `version`.

### 2.5. Compensation Commitment and Funded-Volume Integrity

Two conserved quantities anchor the channel's economics. The first is `total_active_compensation_commitment_cents`, the rolling total of `lender_paid_comp_cents` across the broker's loans in `SUBMITTED`, `UNDERWRITING` or `CONDITIONAL_APPROVAL` status. Because a `BORROWER_PAID` loan carries a `lender_paid_comp_cents` of 0, borrower-paid loans contribute nothing to the commitment. The submission-direction invariant is exact: submitting one lender-paid loan and then withdrawing it leaves `total_active_compensation_commitment_cents` at precisely its pre-submission value.

The second is `rolling_funded_volume_cents`, the sum of `loan_amount_cents` over the broker's `FUNDED` loans, decremented when a funded loan is repurchased. Over its lifetime, every loan of the broker that reaches `FUNDED` or `REPURCHASED` contributes exactly once, and loans in `SUBMITTED`, `UNDERWRITING`, `CONDITIONAL_APPROVAL`, `SUSPENDED_REVIEW`, `CLEAR_TO_CLOSE`, `DENIED` or `WITHDRAWN` contribute zero.

The broker-level reconciliation read reports `total_active_compensation_commitment_cents`, `rolling_funded_volume_cents`, `active_loan_count` and a derived `commitment_drift_cents`. The drift figure is the reconciliation residual between the sum of funded volume and the volume still in suspension and the broker's lifetime funded volume plus loans in flight, and it must be 0 after any compensating sequence.

`active_loan_count` is itself an aggregation over the broker's loan rows: it counts loans in a non-terminal status — `SUBMITTED`, `UNDERWRITING`, `CONDITIONAL_APPROVAL`, `SUSPENDED_REVIEW` and `CLEAR_TO_CLOSE` — while `FUNDED`, `DENIED`, `WITHDRAWN` and `REPURCHASED` loans never contribute. That count is what gates broker termination: a termination requested while `active_loan_count` is non-zero is refused with `ERR_ACTIVE_LOANS_PRESENT`.

### 2.6. Turn-Time Commitments and Escalation Governance

The channel publishes forward-looking deadlines against each loan. `underwriting_due_at` is the instant of the loan's most recent entry into `UNDERWRITING`, `CONDITIONAL_APPROVAL` or `SUSPENDED_REVIEW`, plus ten days. `closing_due_at` is the instant the loan reached `CLEAR_TO_CLOSE`, plus seven days. A reopened escalation's `target_due_at` is the loan's `underwriting_due_at` plus five days. The auto-created quality-control defect-hold decision resets `underwriting_due_at` to the decision instant plus three days. A repurchase review's `repurchase_due_at` is the review-creation instant plus thirty days. Deadlines are whole days added to an ISO 8601 instant, preserving the time of day.

A `TurnTimeEscalation` opens the first time the logical clock reaches or passes the relevant due-at while the loan sits in the matching stage. It opens only if no escalation already exists for the same loan and stage with status `OPEN`, and it is created with `opened_at` equal to the clock, `target_due_at` equal to the lapsed deadline, and status `OPEN`. An escalation is resolved by a `ChannelManager` supplying a `resolution_note`; a resolved escalation never rewrites `closing_path`, because that field is a snapshot taken when the loan reached `CLEAR_TO_CLOSE`.

One further timing note is a fixture convention rather than a rule: the constant `EARLY_FUNDING_CUTOFF_UTC`, fixed at `2026-09-01T00:00:00Z`, exists only to make the rounded base rates in test fixtures reproducible. It is not a business deadline, and no rule reads it.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded against stale reads, and each names the version field it expects in the request body rather than its own resource version. For a write guarded by the broker, the request must carry `expected_broker_version` matching the target `Broker`'s current `version`. If the broker's version has advanced since the client last read it, the write is refused with `ERR_STALE_VERSION` and a `412 Precondition Failed` status. Two operations carry this broker guard: accepting a loan into underwriting, and deciding a product eligibility. The rationale is that `Broker.version` legitimately advances on every licence revocation, every quality-control defect finding, every financial-review decision and every exclusivity escalation, so a client holding an earlier snapshot is acting on facts that are no longer the broker's standing.

The third guarded write is quote pricing, which must carry `expected_rate_sheet_version` matching the target `RateSheet`'s current `version`. A sheet's version advances when a replacement sheet supersedes it and when it is retired, both of which mutate sheet-level fields that a quote inherits; a mismatch is refused with `ERR_STALE_VERSION` and a `412 Precondition Failed` status. Note that this guard is a version guard, not a state guard: pricing a second quote against a sheet that has already been priced against once is permitted, and the iteration of quotes on one sheet is expected.

Endpoints that are not listed above do not accept a version field and perform no such check.

### 2.8. Common Resource Properties and Immutability

Most top-level resources — `Broker`, `BrokerLicense`, `FinancialReview`, `ProductEligibility`, `ExclusivityPolicy`, `RateSheet`, `LoanSubmission`, `CompensationPlan`, `UnderwritingDecision`, `TurnTimeEscalation` and `QualityControlReview` — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits marking first creation. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits marking the last mutation, and it is refreshed on any change to the resource's properties. `version` is an integer that increments with every modification to the resource and is the field clients pin when they use optimistic concurrency control. Mutations to derived fields are ordinary mutations: recomputing `licensed_states` on a broker, for example, refreshes that broker's `updated_at` and increments its `version`.

One resource is deliberately outside that convention. `PricingQuote` is an immutable pricing snapshot: it carries only `id` and `created_at`, and it has no `updated_at`, no `version`, and no update endpoint of any kind. Because a quote is never rewritten, its `rate_sheet_id`, its `broker_id` and its `product_code` are copied at creation so that the snapshot is self-describing.

### 2.9. Precision, Rounding and Monetary Conventions

Monetary amounts are integers expressed in cents and are never rounded to a fraction of a cent. Rate and adjustment values are decimals in percent; `note_rate_pct` is rounded to three decimal places, `price_points` is rounded to three decimal places, `overall_adjustment_pct` and `lock_adjustment_pct` are carried as the signed decimal values the sheet defines, and `rate_impact_pct` is expressed at three decimal places. Quality scores — `rolling_quality_score`, `financial_strength_score` and `computed_financial_strength_score` — are decimals rounded to two decimal places and clamped to the range 0.00 to 100.00. `weighted_defect_points` is rounded to two decimal places, and `defect_multiplier` values are expressed at two decimal places. `max_ltv` on a product eligibility is a decimal fraction with four decimals.

Wherever a rounding step is required, the method is round half up unless a rule explicitly states otherwise. Rounding is applied exactly once, at the point each rule names, after the terms it governs have been summed at full precision — intermediate components are never rounded and then re-summed.

### 2.10. The Logical Clock and Derived-Field Reconciliation

The system does not read wall-clock time. It runs on a logical clock whose startup default is exactly `2026-09-01T00:00:00Z`, and it reads that default until the clock is explicitly advanced. Advancing the clock is an administrative capability that accepts the target instant as `to_iso8601` and reports back `current_utc`, `licenses_expired` and `escalations_opened`. Setting the clock has consequences beyond the timestamp: it expires licences, opens turn-time escalations, and re-derives broker-level state.

Three derived fields are reconciled against the clock. `licensed_states` is the set of distinct `state_code` values across the broker's licences whose status is `ACTIVE` and whose `expires_on` is strictly after the logical clock; the values are sorted ascending by `state_code`, and expired or revoked licences never contribute even when a later licence for the same state remains valid. This field is recomputed whenever a licence is created, whenever a licence is revoked, and on every clock advance. `exclusivity_status` and the broker's suspension state are similarly re-derived on every clock advance.

### 2.11. Nested Resource Resolution Order

Many endpoint paths name more than one resource. For all of them, the system validates existence in a sequential, left-to-right order following the order in which the endpoint's input list declares its identifiers, and it rejects the request with the `404 Not Found` error that corresponds to the first identifier in that order which does not resolve. The catalogue of not-found identifiers is `ERR_BROKER_NOT_FOUND`, `ERR_RATE_SHEET_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_ELIGIBILITY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` and `ERR_ESCALATION_NOT_FOUND`. A `comp_plan_id` that does not name a plan of the loan's own broker is reported through the same not-found family as `ERR_PLAN_NOT_FOUND`.

Validation precedence across categories is fixed. User context is checked first, then the caller's permission for the endpoint, then existence of the referenced resources in left-to-right order, then the version-freshness guards, then the state preconditions of the target resource, and only after all of those the endpoint's business rules, evaluated in a fixed catalogue order of priority. Within that catalogue the exclusivity and licensing rules are probed before the product-envelope, sheet-status and compensation-consistency rules; the malformed-body check that yields `ERR_INVALID_REQUEST` sits late, after those, but is not the last thing evaluated; the acting-brokerage ownership rule follows it; and the broker-standing rule is the final business gate on the operations that carry it. The first gate that fails determines the error identifier returned, and `ERR_DECISION_CONDITIONS_REQUIRED` is the dedicated code for a `CONDITIONAL` underwriting decision whose `conditions` array is missing or empty. A `resolution_note` shorter than ten characters, a defect review created with `remediation_status` `OPEN`, an unknown enum member and a missing required field all travel through `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Brokerage, Licensing and Approval

The channel begins with a brokerage submission. A `ChannelManager` registers the brokerage by supplying its `legal_name`, its NMLS company identifier as `nmls_id`, the two-letter USPS code of its principal place of business as `home_state`, and its approved annual funded-volume expectation in cents as `volume_expectation_cents`. The `nmls_id` is unique across all brokerages; a second registration reusing one that already exists is refused with `ERR_DUPLICATE_NMLS_ID`. On creation the brokerage is stamped into `SUBMITTED` status with a `tier` of `UNRATED`, a `financial_strength_score` of 0.00, a `rolling_quality_score` of 100.00, an `open_defect_tier` of 0, an `exclusivity_status` of `CLEAR`, a `rolling_funded_volume_cents` of 0, an `active_loan_count` of 0, a `total_active_compensation_commitment_cents` of 0, and an empty `licensed_states` list. These initial values are not client-supplied; `status`, `tier` and every rolling field are owned by the system.

Licensing follows immediately and is a precondition of approval rather than an optional enrichment. A `ChannelManager` records a licence with a `state_code`, a state-issued `license_number`, a `license_type` of `MORTGAGE_BROKER`, `MORTGAGE_LENDER` or `DUAL_AUTHORITY`, and an `expires_on` instant. The licence becomes `ACTIVE` on creation, and the broker's `licensed_states` is recomputed so that the new state appears if the licence has not yet lapsed — a licence contributes only while the logical clock is strictly before its `expires_on`. A licence lapses automatically when the clock reaches or passes `expires_on`, at which point its status becomes `EXPIRED` and the broker's `licensed_states` is recomputed; if no other unexpired licence covers that state, the state drops out. Expiry never reverses an approval that has already been granted. It only bites on subsequent operations, because quotation, submission and the licence gates re-read `licensed_states` every time they run.

A `ComplianceOfficer` may instead revoke a licence outright. Revocation requires that the licence still be `ACTIVE` — a licence that is already `EXPIRED` or `REVOKED` cannot be revoked again and yields `ERR_LICENSE_NOT_REVOCABLE` — and it stamps `revoked_at` with the logical clock and recomputes the broker's `licensed_states`. Revocation is the sharpest instrument in the channel because it cascades. Every loan of that broker whose `property_state` equals the revoked licence's `state_code` and whose status is `SUBMITTED` or `UNDERWRITING` is immediately pushed to `SUSPENDED_REVIEW` with `suspended_reason` of `LICENSE_REVOKED`; for each loan so moved, the broker's `total_active_compensation_commitment_cents` is reduced by that loan's `lender_paid_comp_cents`, and every `TurnTimeEscalation` of that loan that had been `RESOLVED` is reopened to `OPEN` with `resolved_at` cleared and `target_due_at` reset to the loan's `underwriting_due_at` plus five days.

Approval itself is a `ChannelManager` decision on a `SUBMITTED` brokerage, and it is gated by a fixed set of checks. The exclusivity gate is applied before every other business precondition: if the broker's `exclusivity_status` is `BLOCKED`, the approval is refused with `ERR_BROKER_EXCLUSIVITY_BLOCKED` regardless of what else is true. After that gate, the remaining probes run in order: the broker's status must be `SUBMITTED`, or the request fails with `ERR_BROKER_NOT_SUBMITTED`; the `open_defect_tier` must be at most 2, or the request fails with `ERR_BROKER_DEFECT_HOLD`; at least one `FinancialReview` of the broker must already carry status `PASSED`, or the request fails with `ERR_FINANCIAL_REVIEW_PENDING`; and at least one `BrokerLicense` whose `expires_on` is strictly after the logical clock must exist, or the request fails with `ERR_NO_VALID_LICENSE`. On success the broker moves from `SUBMITTED` to `APPROVED`, its `tier` is recomputed from its `financial_strength_score`, and its `version` is incremented by one.

Termination and manual suspension share a shape. A `ChannelManager` may suspend an `APPROVED` brokerage, supplying a `reason` that is recorded verbatim in `suspended_reason`; the request is refused with `ERR_BROKER_NOT_SUSPENDABLE` if the broker is not `APPROVED`. A `ChannelManager` may terminate a brokerage from `SUBMITTED`, `APPROVED` or `SUSPENDED`, provided `active_loan_count` is 0, or the request fails with `ERR_ACTIVE_LOANS_PRESENT`. Both manual suspension and termination withdraw the broker's still-unstarted work: every loan of that broker in `SUBMITTED` status is moved to `WITHDRAWN`, and for each loan so withdrawn the broker's `total_active_compensation_commitment_cents` is reduced by that loan's `lender_paid_comp_cents`. In every one of these transitions the broker's `version` increments by one. Note that a broker that is already `SUSPENDED` normally has no non-terminal loans left other than those already pushed to `SUSPENDED_REVIEW` or beyond, so on a suspension-to-termination hop the withdrawal cascade usually finds nothing to withdraw unless a loan was revived by a reinstate-and-underwrite cycle.

### 3.2. Financial Review, Scoring and the Tier Ladder

A `ChannelManager` records a `FinancialReview` against a brokerage with an audited `net_worth_cents`, an audited `liquidity_cents`, audited `total_liabilities_cents`, whole `years_in_business`, the `prior_year_funded_volume_cents` reported for the prior twelve months, and a boolean `audit_attested` that defaults to false. The review is created in `PENDING` status, and its `computed_financial_strength_score` is calculated and stored immediately — but the broker's own `financial_strength_score` is untouched at this point. A pending review leaves the broker exactly where it was, even though the review row itself displays a score.

The score is a weighted blend of four terms on a zero-to-one-hundred scale. The net-worth term takes the smaller of one and the review's `net_worth_cents` divided by one hundred million cents (one million dollars), multiplied by forty. The liquidity term takes the smaller of one and `liquidity_cents` divided by forty million cents (four hundred thousand dollars), multiplied by thirty. The leverage term divides `total_liabilities_cents` by a denominator that is the larger of one and `net_worth_cents` multiplied by three, subtracts that quotient from one, floors the result at zero, and multiplies by twenty. The experience term takes the smaller of one and `years_in_business` divided by five, multiplied by ten. The four terms are summed, the sum is clamped to the range zero to one hundred, and the clamped sum is rounded half up to two decimal places. This rounded value is the review's `computed_financial_strength_score`.

Volume attainment is scored separately and never feeds the score above. The attainment ratio is `prior_year_funded_volume_cents` divided by the broker's `volume_expectation_cents`. A ratio of at least 1.0 places the review in the `MEETS_EXPECTATION` band; failing that, a ratio of at least 0.75 places it in `NEAR_EXPECTATION`; anything lower is `BELOW_EXPECTATION`. The bands correspond to band scores of 100, 75 and 40 respectively, and the band is stored so that the tier ladder can consult it later.

Deciding the review is a `ChannelManager` action that supplies the `outcome`. A review that is not `PENDING` can no longer be decided and yields `ERR_REVIEW_ALREADY_DECIDED`. The passing branch carries two further requirements: the review must have `audit_attested` true — an unattested review can never pass, and the attempt is refused with `ERR_FINANCIAL_REVIEW_PENDING` — and its `net_worth_cents` must be at least twenty-five million cents (two hundred and fifty thousand dollars), or the attempt is refused with `ERR_NET_WORTH_BELOW_MINIMUM`. When those hold, the review becomes `PASSED`, the broker's `financial_strength_score` is overwritten with the review's `computed_financial_strength_score`, the broker's `tier` is recomputed from the new score, and the review becomes the broker's current one: every other `PASSED` review of that broker has its `is_current` set to false and this review has `is_current` set to true. The failing branch is deliberately inert — the review becomes `FAILED`, its `is_current` stays false, and the broker's `financial_strength_score` is not updated at all by a failed review. Either branch increments the broker's `version` by one, and the passing branch re-evaluates the broker's suspension triggers against the new financial score.

The `tier` is derived on approval, on reinstatement, and on every change to the `financial_strength_score`. A score of at least 85.00 yields `TIER_1`; failing that, a score of at least 60.00 yields `TIER_2`; failing that, a score of at least 40.00 yields `TIER_3`; anything lower yields `UNRATED`. With no `PASSED` review on file at all, the tier is `UNRATED`. One cap applies after banding: when the broker's current `PASSED` review (the row whose `is_current` is true) has a band other than `MEETS_EXPECTATION`, a computed `TIER_1` is capped down to `TIER_2`. A `TIER_2` or `TIER_3` result is never capped upward. Thresholds are compared at two decimals.

### 3.3. Product Eligibility and the Broker's Delivery Envelope

A brokerage may only deliver products it has been individually cleared for. A `ChannelManager` requests a `ProductEligibility` with a `product_code` of `CONVENTIONAL`, `FHA`, `VA`, `JUMBO` or `USDA`, a `max_ltv`, a `min_fico` and a `max_loan_amount_cents`. The row is created in `PENDING` status and is inert until decided. The eligibility decision is a `ChannelManager` action that supplies the `outcome` and must carry `expected_broker_version`; the version guard is the broker guard described in §2.7, and a stale value is refused with `ERR_STALE_VERSION` before the decision is attempted. Approving is additionally blocked when the broker's `exclusivity_status` is `BLOCKED`, in which case the attempt is refused with `ERR_BROKER_EXCLUSIVITY_BLOCKED`; revocation has no such gate. A row that is no longer `PENDING` cannot be decided and yields `ERR_ELIGIBILITY_ALREADY_DECIDED`.

An approval sets the status to `APPROVED` and stamps `approved_at` with the logical clock, making the row live; a revocation sets the status to `REVOKED` and clears any claim to approval. Either outcome recomputes the broker's `approved_product_codes` as the distinct `product_code` values of that broker's `APPROVED` eligibilities, and either outcome increments the broker's `version` by one. The approved set is the delivery envelope: a loan submission is only accepted when an `APPROVED` eligibility exists for the submitted product whose `max_ltv`, `min_fico` and `max_loan_amount_cents` all hold as inclusive bounds against the submission's figures, and a submission falling outside that envelope is refused with `ERR_PRODUCT_NOT_ELIGIBLE`.

The broker's standing gates the same operations from the other side. A broker that is not `APPROVED` may not request a quote or create a loan submission, and either attempt is refused with `ERR_BROKER_NOT_APPROVED`. Accepting a loan into underwriting and funding a loan carry the same requirement.

### 3.4. Exclusivity Policies, Breaches and Escalation of Consequences

The lender uses competitor exclusivity agreements to keep its broker relationships exclusive. A `ChannelManager` registers an `ExclusivityPolicy` against a brokerage with a `competitor_identifier` — the portal account identifier of the restricted competitor — a human-readable `competitor_name`, an `effective_from` instant that is inclusive, and an `effective_to` instant that is exclusive and must be strictly after `effective_from`. Two further inputs are optional: `status`, which is the only field on this entity a client may supply and which defaults to `ACTIVE` with the alternatives `DRAFT`, `SUPERSEDED` and `VOIDED`, and `restriction_scope`, which defaults to `LOAN_SUBMISSION` with the alternatives `RATE_LOCK` and `ALL`. Only an `ACTIVE` policy can be breached. Registration starts the policy with a `breach_count` of 0 and recomputes the broker's `exclusivity_status`.

A breach is recorded when a loan discloses a competitor. The loan submission payload carries `competitor_channel_identifier`, the portal account identifier of any competitor involved in the transaction, and that value is matched case-insensitively against the broker's policies. When it matches an `ACTIVE` policy, the submission is refused with `ERR_EXCLUSIVITY_POLICY_BREACH`; the same matching rule applies to a quote request priced on a rate sheet belonging to that broker. Separately, a broker whose `exclusivity_status` has escalated to `RESTRICTED` is held back only on the operations the breached policy actually covers: when the breached policy's `restriction_scope` covers the attempted operation, the request is refused with `ERR_BROKER_EXCLUSIVITY_RESTRICTED`. Because the default scope is `LOAN_SUBMISSION`, a default-scoped breach blocks submission while leaving rate locking open; an `ALL`-scoped breach blocks both.

The `exclusivity_status` itself is derived from breadth rather than from the severity of any single breach. The system counts the distinct `ExclusivityPolicy` rows of the broker, in `ACTIVE` or `SUPERSEDED` status, whose `breach_count` is at least 1. Zero such policies leaves the status `CLEAR`. Exactly one yields `WARNED`. Exactly two yield `RESTRICTED`. Three or more yield `BLOCKED`, and a `BLOCKED` broker is refused on approval, on reinstatement, on eligibility decisions and on loan underwriting with `ERR_BROKER_EXCLUSIVITY_BLOCKED`, in addition to triggering automatic suspension. Whenever a policy is registered, voided, or breached, `exclusivity_status` is recomputed and the broker's `version` is incremented.

### 3.5. Rate Sheets and the Pricing Engine

Pricing starts with a rate sheet. A `ChannelManager` publishes a rate sheet for a brokerage and a product by supplying a `product_code`, a par `base_rate_pct`, and an `adjustment_table` — an ordered list of rows, each carrying a `dim` of `credit`, `ltv`, `occupancy` or `product`, a `bucket` naming the band, and a signed `adjust_pct`. The new sheet enters `PUBLISHED` status with `published_at` set to the logical clock and a `publish_sequence` that is one more than the highest sequence previously used for that broker-and-product pair. Publishing a replacement has an immediate effect on the sheet it replaces: the prior `PUBLISHED` sheet for the same broker and product moves to `SUPERSEDED` with its `superseded_by_sheet_id` set to the new sheet's identifier, and that prior sheet's `version` is incremented by one. The broker's `version` is incremented by one as well.

Repricing does not reach backwards. An existing quote keeps the sheet it was priced from and reports its staleness through `is_repriced`, which is true exactly when the calling broker's `PUBLISHED` sheet has a higher `publish_sequence` than the `publish_sequence` of the sheet the quote names. A sheet may be retired from either `PUBLISHED` or `SUPERSEDED` status by a `ChannelManager`, but only while no `PricingQuote` references it; a retirement attempted while quotes exist is refused with `ERR_SHEET_IN_USE`. A sheet that has already been priced against and then repriced away is therefore readable forever but no longer priceable, and an attempt to price or submit against a sheet whose status is `SUPERSEDED` or `RETIRED` is refused with `ERR_PRICING_QUOTE_SUPERSEDED`.

A `BrokerUser` prices a scenario with `representative_fico`, `ltv_ratio` — a decimal fraction with four decimals — `occupancy_type` of `PRIMARY_RESIDENCE`, `SECOND_HOME` or `INVESTMENT`, `loan_amount_cents`, `lock_period_days`, `loan_purpose` of `PURCHASE`, `RATE_TERM_REFINANCE` or `CASH_OUT_REFINANCE`, and the sheet version guard `expected_rate_sheet_version`. The write is refused with `ERR_STALE_VERSION` when the sheet's version has advanced past what the client observed, and as noted above a second quote against a sheet that has already been priced is permitted rather than rejected on state. Creating the quote increments the sheet's `version` by one.

The quote's `overall_adjustment_pct` is the sum of four dimension adjustments, evaluated and summed in a pinned order: credit, then loan-to-value, then occupancy, then product. The credit row is the sheet row whose dimension is credit and whose bucket contains the `representative_fico`; the bands are closed on the left and open on the right except the last, so a score of 760 or more takes the top band's `-0.125`, a score of 740 up to but excluding 760 takes `-0.050`, 720 up to but excluding 740 takes `0.000`, 700 up to but excluding 720 takes `0.125`, 680 up to but excluding 700 takes `0.250`, and any score below 680 takes `0.500`. The loan-to-value row is selected against bands that are open on the left and closed on the right except the last: an `ltv_ratio` of 0.60 or less takes `0.000`, above 0.60 up to and including 0.70 takes `0.050`, above 0.70 up to and including 0.80 takes `0.125`, above 0.80 up to and including 0.90 takes `0.250`, above 0.90 up to and including 0.95 takes `0.375`, and anything above 0.95 takes `0.500`. The occupancy row matches `occupancy_type` exactly, with `PRIMARY_RESIDENCE` at `0.000`, `SECOND_HOME` at `0.250` and `INVESTMENT` at `0.500`. The product row matches `product_code` exactly, with `CONVENTIONAL` at `0.000`, `FHA` at `0.125`, `VA` at `-0.125`, `JUMBO` at `0.375` and `USDA` at `0.250`. The four selected values, each a signed decimal in percent, are summed. `loan_purpose` is deliberately not a pricing dimension: it never appears in `overall_adjustment_pct`, in `note_rate_pct`, or in the `adjustment_trace`. That trace is an array of exactly four rows, each an object carrying `dim`, `bucket` and `adjust_pct`, emitted in the order credit, loan-to-value, occupancy, product.

The `lock_adjustment_pct` is a surcharge keyed on the requested lock length. A `lock_period_days` below 30 takes `0.125`; from 30 up to but excluding 60 takes `0.000`; 60 or more takes `-0.125`. The `note_rate_pct` is computed in a pinned rounding order that matters: the sheet's `base_rate_pct`, the quote's `overall_adjustment_pct` and the quote's `lock_adjustment_pct` are summed at full precision, and that single sum is rounded half up to three decimal places exactly once. Neither the base rate nor the adjustment total is rounded before the sum. A base of 6.125 with an adjustment of 0.125 and a lock surcharge of 0.125 therefore produces 6.375 exactly.

The `price_points` field is derived from an immutable base grid in seven pinned steps. The first step chooses the credit bucket by rounding `representative_fico` half up to the nearest ten. The second step chooses the loan-to-value band using the same half-open bands described above. The third step reads the base grid at that credit bucket and that band; the grid is a six-by-six table whose rows are the rounded credit buckets 760-and-above, 740, 720, 700, 680, 660 and below 660, and whose columns are the six loan-to-value bands in ascending order — for the 760-and-above row the six values are `-1.00`, `-0.75`, `-0.50`, `-0.25`, `0.00` and `0.25`; for the 740 row they are `-0.75`, `-0.50`, `-0.25`, `0.00`, `0.25` and `0.50`; for the 720 row they are `-0.50`, `-0.25`, `0.00`, `0.25`, `0.50` and `0.75`; for the 700 row they are `-0.25`, `0.00`, `0.25`, `0.50`, `0.75` and `1.00`; for the 680 row they are `0.00`, `0.25`, `0.50`, `0.75`, `1.00` and `1.25`; for the 660 row they are `0.25`, `0.50`, `0.75`, `1.00`, `1.25` and `1.50`; and for the below-660 row they are `0.50`, `0.75`, `1.00`, `1.25`, `1.50` and `1.75`. The fourth step adds the quote's `overall_adjustment_pct` to that base value to obtain the provisional points. The fifth step assigns a discount tier from the provisional value alone: `PLATINUM` when the provisional points are `-0.50` or lower, `GOLD` when they are `0.00` or lower, `SILVER` when they are `0.50` or lower, and `BRONZE` otherwise. The boundaries are inclusive, so exactly `-0.50` is `PLATINUM`, exactly `0.00` is `GOLD`, and exactly `0.50` is `SILVER`. The sixth step reads the tier discount: `PLATINUM` takes `-0.25`, `GOLD` takes `-0.10`, `SILVER` takes `0.000` and `BRONZE` takes `0.25`. The seventh step adds that discount to the provisional points and rounds half up to three decimal places. The evaluation order is deliberately circular-looking and must be preserved: the discount is keyed on the tier of the provisional pre-discount value, so the final `price_points` never re-enters the tier step. And because the grid is snapshotted at creation, an intraday reprice never changes an existing quote's `price_points`; staleness is exposed through `is_repriced` instead.

### 3.6. Loan Submission and the Compensation Election

With a quote in hand, the broker prepares the file. A `BrokerUser` creates a `LoanSubmission` against its own brokerage by supplying `broker_id`, `pricing_quote_id`, `borrower_name`, `property_state`, `loan_amount_cents`, `lock_expires_at`, and optionally `competitor_channel_identifier`, `compensation_election` and `comp_plan_id`. The `property_state` must be covered by an unexpired licence: it must appear in the broker's `licensed_states`, or the submission is refused with `ERR_PROPERTY_STATE_NOT_LICENSED`. The `lock_expires_at` must be strictly after the logical clock, and it is the sole setter of the submission-rate lock countdown. The referenced sheet must still be `PUBLISHED`, or the refusal is `ERR_PRICING_QUOTE_SUPERSEDED` — note that an intraday reprice makes prior quotes stale but never blocks submission on that ground alone, since the sheet-status gate is the only sheet-level check and a quote whose sheet was superseded usually still finds `PUBLISHED` and is accepted with `is_repriced` reporting true. The approved-eligibility envelope of §3.3 and the exclusivity breach rule of §3.4 both apply here as well, and the broker must be `APPROVED`.

On acceptance the loan enters `SUBMITTED`, `submitted_at` is stamped with the logical clock, and `underwriting_due_at` is set to `submitted_at` plus ten days. The broker's `active_loan_count` is recomputed and its `version` is incremented by one.

The compensation decision may be made at submission or afterwards, but only within a narrow window. The election is `LENDER_PAID`, `BORROWER_PAID` or `UNDECIDED`, and it may only move from `UNDECIDED` to one of the two decided values, and only while the loan's status is `SUBMITTED`. A change attempted after the loan leaves `SUBMITTED`, or a call that repeats the already-stored value, is refused with `ERR_COMPENSATION_ELECTION_IMMUTABLE`. The nominated `comp_plan_id` must name an `ACTIVE` `CompensationPlan` of the loan's own broker whose `default_election` equals the elected value; a plan that is not active, not owned by that broker, or whose default differs is refused with `ERR_COMPENSATION_PLAN_MISMATCH`, and a plan identifier that names no plan of the loan's broker is reported as `ERR_PLAN_NOT_FOUND`. A dedicated election call later supplies `compensation_election` and `comp_plan_id` together and increments the broker's `version` by one.

The split itself is a waterfall keyed on the election. When the election is `LENDER_PAID`, `lender_paid_comp_cents` is set to the plan's `lender_paid_amount_cents` and `borrower_paid_comp_cents` is 0. When the election is `BORROWER_PAID`, `lender_paid_comp_cents` is 0 and `borrower_paid_comp_cents` is the plan's `borrower_paid_amount_cents`. While the election is still `UNDECIDED`, both are 0. The broker's `total_active_compensation_commitment_cents` is adjusted by the lender-paid delta, so it rises by the plan's lender-paid amount when the loan commits to the lender-paid branch and carries nothing when the loan is borrower-paid.

The election also moves the rate. `rate_impact_pct` is `0.000` when the election equals the plan's `default_election`; it is `+0.250` when `LENDER_PAID` is elected against a `BORROWER_PAID` default, and `-0.250` in the mirrored case where `BORROWER_PAID` is elected against a `LENDER_PAID` default; while the election is `UNDECIDED` it is `0.000`. The `final_note_rate_pct` is the quote's `note_rate_pct` plus the `rate_impact_pct`, summed and rounded half up to three decimal places, once the election is decided; while the election is `UNDECIDED` the `final_note_rate_pct` is simply the quote's `note_rate_pct`. Amounts are materialized only inside the election block — a loan that never elects carries a `lender_paid_comp_cents` and a `borrower_paid_comp_cents` of 0 rather than a plan default.

A compensation plan is created by a `ChannelManager` against a brokerage with a `broker_id`, a `plan_code` of `PLAN_A`, `PLAN_B` or `PLAN_C` that is unique per broker and is the identifier the broker-wide election consistency rule compares, a `default_election` of `LENDER_PAID` or `BORROWER_PAID`, a `lender_paid_amount_cents`, a `borrower_paid_amount_cents`, and an optional `is_active` that defaults to true. A plan may be deactivated by a `ChannelManager` through an activation toggle that supplies `is_active` and optionally `default_election`, `lender_paid_amount_cents` and `borrower_paid_amount_cents`, but a deactivation must leave at least one other active plan on the broker, or it is refused with `ERR_LAST_ACTIVE_COMPENSATION_PLAN`; deactivation of an already-inactive plan, or reactivation of an already-active one, is refused as `ERR_INVALID_REQUEST`. Loans that have already been decided keep their `lender_paid_comp_cents`, `borrower_paid_comp_cents` and `rate_impact_pct` untouched by any later plan change.

Finally, a broker may withdraw a loan before it clears. Withdrawal is permitted only while the loan is `SUBMITTED`, `UNDERWRITING` or `CONDITIONAL_APPROVAL`, and any other status yields `ERR_LOAN_NOT_WITHDRAWABLE`. Withdrawal sets the loan to `WITHDRAWN`, reduces the broker's `total_active_compensation_commitment_cents` by the loan's `lender_paid_comp_cents`, recomputes `active_loan_count`, and increments the broker's `version` by one. This is the compensating half of the commitment invariant described in §2.5.

### 3.7. Underwriting, Decisions and the Suspended-Review Loop

An `Underwriter` accepts a broker file into underwriting by pinning the broker's version: the call must carry `expected_broker_version`, and a broker whose version has advanced since the client's last read is refused with `ERR_STALE_VERSION`. Once the version check passes, the loan's own status must be `SUBMITTED`, or the request fails with `ERR_LOAN_NOT_SUBMITTED`; then the loan's `compensation_election` must no longer be `UNDECIDED`, or the request fails with `ERR_COMPENSATION_ELECTION_PENDING`; and then the broker must be `APPROVED` and its `exclusivity_status` must not be `BLOCKED`, or the request fails with `ERR_BROKER_NOT_APPROVED` or `ERR_BROKER_EXCLUSIVITY_BLOCKED` respectively. Acceptance moves the loan to `UNDERWRITING`, stamps `submitted_at` with the logical clock, sets `underwriting_due_at` to `submitted_at` plus ten days, recomputes the broker's `active_loan_count`, and increments the broker's `version` by one.

The underwriter's decision is recorded as an `UnderwritingDecision` against a loan that is in `UNDERWRITING`; any other status yields `ERR_LOAN_NOT_UNDERWRITING`. The decision carries `loan_submission_id`, a `decision_type` of `APPROVED`, `CONDITIONAL`, `SUSPENDED` or `DENIED`, and optionally `conditions` and `decision_notes`; the acting underwriter is captured as `underwriter_id` from `X-User-ID` and `decided_at` is the logical clock. The four branches are not symmetric in their downstream effect. A `CONDITIONAL` decision requires a non-empty `conditions` array, and without one the request is refused with `ERR_DECISION_CONDITIONS_REQUIRED`; it moves the loan to `CONDITIONAL_APPROVAL`, sets that decision's `is_final` to true, and resets `underwriting_due_at` to `decided_at` plus ten days. A `SUSPENDED` decision moves the loan to `SUSPENDED_REVIEW` and marks the decision final; when the broker's `open_defect_tier` is at least 1 at that moment, the system additionally auto-creates a second `UnderwritingDecision` carrying `decision_type` of `SUSPENDED`, `is_final` false and `decision_notes` of `QC_DEFECT_HOLD`, and that auto-created row flips the loan's `underwriting_due_at` to the current clock plus three days and sets the broker's `suspended_reason` only if that auto-created row is the first decision recorded for the loan. A `DENIED` decision moves the loan to `DENIED`, and an `APPROVED` decision also moves the loan to `CONDITIONAL_APPROVAL` but carries no conditions — an approval that comes with conditions is expressed as `CONDITIONAL` rather than as an `APPROVED` with a conditions list. When the loan leaves `UNDERWRITING` through a final decision, that decision's `is_final` is true and it cannot afterwards be revised. Every decision increments the broker's `version` by one.

A loan pushed to `SUSPENDED_REVIEW` is not dead; it can be revived by the broker. A `BrokerUser` resubmits it by supplying a `resubmission_note`, but only while the loan actually sits in `SUSPENDED_REVIEW` — any other status yields `ERR_LOAN_NOT_SUSPENDED`. Resubmission returns the loan to `SUBMITTED` and sets `underwriting_due_at` to the logical clock plus ten days, and increments the broker's `version` by one, at which point the loan must pass through underwriting again.

Turn-time governance runs alongside the decision loop. On every advance of the logical clock, the system checks whether `underwriting_due_at` has been reached or passed while the loan is `UNDERWRITING` or `CONDITIONAL_APPROVAL`, and whether `closing_due_at` has been reached or passed while the loan is `CLEAR_TO_CLOSE`. The first time each such condition holds with no existing `OPEN` escalation for that loan and `stage`, a `TurnTimeEscalation` is opened with the `stage` set to `UNDERWRITING` or `CLOSING`, `opened_at` set to the clock, `target_due_at` set to the lapsed deadline, and `status` `OPEN`. A `ChannelManager` resolves one by supplying a `resolution_note`; an escalation that is already `RESOLVED` cannot be resolved again and yields `ERR_ESCALATION_ALREADY_RESOLVED`, and a note that is missing or shorter than ten characters is refused as `ERR_INVALID_REQUEST`. Resolution sets the `status` to `RESOLVED`, stamps `resolved_at` with the logical clock — clearing it back to null is reserved for the automatic reopen that a licence revocation cascade forces on a loan it pushes to `SUSPENDED_REVIEW` — records the note verbatim, and — when the escalation's `stage` is `UNDERWRITING` and the loan is then in `UNDERWRITING` or `CONDITIONAL_APPROVAL` — resets the loan's `underwriting_due_at` to the clock plus ten days. No other loan field changes: a resolved escalation never rewrites `closing_path`.

### 3.8. Clearing to Close, Funding and the Closing Pipeline

Once a loan is `CONDITIONAL_APPROVAL`, an `Underwriter` may clear it to close. Three gates apply in order. The loan's status must be `CONDITIONAL_APPROVAL`, or the request fails with `ERR_LOAN_NOT_CONDITIONAL`. The loan's `defect_remediation_open` flag must be false, or the request fails with `ERR_DEFECT_REMEDIATION_OPEN`. And no `TurnTimeEscalation` of that loan may be `OPEN` with stage `CLOSING`, or the request fails with `ERR_CLOSING_ESCALATION_OPEN`. On success the loan moves to `CLEAR_TO_CLOSE`, `cleared_at` is stamped with the logical clock, `closing_due_at` is set to `cleared_at` plus seven days, and `closing_path` is stamped as a snapshot: it is `ESCALATION_PATH` when any `TurnTimeEscalation` of that loan exists at that instant — any stage, any status — and `STANDARD_PATH` otherwise. The broker's `version` is incremented by one.

Funding is the final forward step and carries four gates, again in order. The loan's status must be `CLEAR_TO_CLOSE`, or the request fails with `ERR_LOAN_NOT_CLEAR_TO_CLOSE`; `defect_remediation_open` must be false, or the request fails with `ERR_DEFECT_REMEDIATION_OPEN`; no `TurnTimeEscalation` of the loan may be `OPEN`, regardless of stage, or the request fails with `ERR_CLOSING_ESCALATION_OPEN`; and the broker must be `APPROVED`, or the request fails with `ERR_BROKER_NOT_APPROVED`. Funding moves the loan to `FUNDED`, adds the loan's `loan_amount_cents` to the broker's `rolling_funded_volume_cents`, recomputes `active_loan_count`, and increments the broker's `version` by one. Funding creates no quality-control review of its own; it only makes the loan eligible for a later one.

The closing-pipeline read publishes the effect of the `closing_path` snapshot. It reports `escalated_count`, `standard_count`, `near_deadline_count`, `escalated_loan_ids` and `standard_loan_ids`, optionally filtered to a single broker, splitting the loans by their stamped path so that operations can see how much of the pipeline is running under escalation.

### 3.9. Quality Control, Defect Remediation and Repurchase

Post-funding review is where the lender absorbs the risk of a bad file. A `QualityControlAnalyst` opens a `QualityControlReview` on a loan by supplying `loan_submission_id`, a `defect_type`, a `severity` and a `remediation_status`. The defect types are `INCOME_DISCREPANCY`, `UNDISCLOSED_LIABILITY`, `APPRAISAL_DEVIATION`, `TITLE_DEFECT` and `LICENSE_DEFECT`, and the severity is `MINOR`, `MAJOR` or `CRITICAL`. Reviewing is only legitimate on a loan that has reached the funded part of its life: the loan's status must be one of `FUNDED`, `CLEAR_TO_CLOSE`, `REPURCHASED` or `CONDITIONAL_APPROVAL`. At most one review may exist per loan submission, and a second attempt is refused with `ERR_QC_REVIEW_EXISTS` — which is exactly why a later dating-only correction travels through the resolve surface rather than through a second review row.

Two checks precede creation. First, a defect review may not be created already in progress: the supplied `remediation_status` must be `NONE` or `REMEDIATED`, and a defect created with `remediation_status` of `OPEN` is refused as `ERR_INVALID_REQUEST`. Second, separation of duties applies: the reviewing analyst must not be the underwriter named on the loan's most recent final `UnderwritingDecision`, and a violation is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

The outcome is derived from the defect type rather than chosen. A `NON_DEFECT` review becomes `CLEAR`, its `remediation_status` becomes `NONE`, and its `weighted_defect_points` is 0.00 — such a review costs nothing and is useful only as a clean-file record. Any other defect type yields `DEFECT`, and the points are the defect type's weight scaled by the severity multiplier and rounded half up to two decimal places. The defect weights are `INCOME_DISCREPANCY` at 8.00, `UNDISCLOSED_LIABILITY` at 5.00, `APPRAISAL_DEVIATION` at 6.00, `TITLE_DEFECT` at 7.00, `LICENSE_DEFECT` at 10.00 and `NON_DEFECT` at 0.00, and the severity multipliers are `MINOR` at 0.50, `MAJOR` at 1.00 and `CRITICAL` at 1.50.

A defect finding debits the broker's `rolling_quality_score`. The debit is the finding's `weighted_defect_points` multiplied by a multiplier read from the broker's `open_defect_tier` at the instant the finding is counted: a tier of 0 gives 1.00, a tier of 1 gives 1.25, a tier of 2 gives 1.50, a tier of 3 gives 2.00, and a tier of 4 or more gives 2.50. The product is subtracted from `rolling_quality_score` and the result is floored at 0.00. The multiplier is read at the moment of counting only; later changes to the tier never retroactively restate a debit that has already been applied. A defect that arrives with `remediation_status` of `OPEN` also increments `open_defect_tier` by one, and when the tier is then at least 1 the loan's `defect_remediation_open` flag is set true — which is precisely what will make a later clear-to-close or funding attempt fail with `ERR_DEFECT_REMEDIATION_OPEN` when the loan is sitting in `CLEAR_TO_CLOSE` or `CONDITIONAL_APPROVAL`.

Two independent consequences branch off a defect. When the finding's `weighted_defect_points` is at least 12.00 and its severity is `CRITICAL`, the review sets `repurchase_required` true and stamps `repurchase_due_at` as the review's `reviewed_at` plus thirty days. Separately, when the loan's status is `CLEAR_TO_CLOSE` at the moment the defect is recorded, the loan is pushed back to `SUSPENDED_REVIEW`; a loan in `CONDITIONAL_APPROVAL` is left in place and merely gated by the remediation flag. Every review creation increments the broker's `version` by one and re-evaluates the broker's suspension triggers, so a severe enough finding can suspend the broker automatically under §2.4.

Remediation works the tier back down. A `QualityControlAnalyst` resolves a finding by supplying a `resolution_type` and a `resolution_note`. When the resolution type is `REMEDIATED` against a finding whose `remediation_status` is `OPEN`, the status becomes `REMEDIATED`, the broker's `open_defect_tier` is decremented by one, and when the loan's `defect_remediation_open` flag had been set by this finding and no other `OPEN` finding remains on the loan, that flag is cleared. Any other resolution type against an `OPEN` finding is refused as `ERR_INVALID_REQUEST`.

Voiding is the compensating path and it restores the score. When the resolution type is `VOIDED` against a `CLEAR` review, the `remediation_status` becomes `VOIDED` and the broker's `rolling_quality_score` is increased by the finding's `weighted_defect_points` multiplied by the defect multiplier read from the broker's current `open_defect_tier`, with the result capped at 100.00; because a `NON_DEFECT` review carries 0.00 points, freezing a clean review and voiding it must leave `rolling_quality_score` exactly where it started. A `VOIDED` resolution against a `CLEAR` review whose `remediation_status` is not `NONE` is refused as `ERR_INVALID_REQUEST`. When the resolution type is `VOIDED` against a `DEFECT` review, the `remediation_status` becomes `VOIDED` and the same capped credit is applied; additionally, if the voided finding's prior `remediation_status` had been `OPEN`, `open_defect_tier` is decremented by one and the loan's `defect_remediation_open` flag is cleared when no other `OPEN` finding remains, while if the voided finding's prior `remediation_status` had been `REMEDIATED`, `open_defect_tier` is left unchanged. Every resolution increments the broker's `version` by one.

A dating-only mint correction is a special shape of `REMEDIATED` resolution. When a finding was created with `remediation_status` already `REMEDIATED` and is then resolved with `resolution_type` `REMEDIATED`, the `remediation_status` stays `REMEDIATED` and the outcome stays `DEFECT`, but the broker's `rolling_quality_score` is debited by the finding's `weighted_defect_points` multiplied by the defect multiplier read from the broker's current `open_defect_tier`, floored at 0.00, and the loan's `defect_remediation_open` flag is set true. This is the route by which a corrected file adds its points to the broker after the fact.

Repurchase is the channel's terminal sanction on a funded loan, and it is exercised by a `QualityControlAnalyst` rather than by the underwriter. Three conditions must hold simultaneously, checked in order. The review must be a `DEFECT` whose `repurchase_required` is true, or the request is refused with `ERR_REPURCHASE_NOT_REQUIRED`. The logical clock must be at or before the review's `repurchase_due_at`, or the request is refused with `ERR_REPURCHASE_WINDOW_EXPIRED`. And no other `QualityControlReview` of the same loan may already have been repurchased, or the loan must not already sit in `REPURCHASED`, or the request is refused with `ERR_LOAN_ALREADY_REPURCHASED`.

A successful repurchase moves the loan to `REPURCHASED` and computes its exposure as a compensating pair. Writing the loan's `loan_amount_cents` as the funded contribution and the broker's `rolling_funded_volume_cents` measured before this repurchase as the pool, the volume-share reversal is the pool multiplied by the contribution, divided by the pool plus the contribution; the origination-fee reversal is exactly half the contribution. The two reversals are summed at full precision and rounded half up once to a whole number of cents to give `repurchase_exposure_cents`. The ordering is pinned: the pool is read before any decrement happens. The quantity is conserving, because the loan-representative share of the pair — the contribution minus the volume-share reversal — plus the volume-share reversal is exactly the contribution. The broker's `rolling_funded_volume_cents` is then reduced by the loan's `loan_amount_cents`, `active_loan_count` is recomputed, and the broker's `version` is incremented by one. Any other review of that same loan keeps its status; only the loan's own status is consumed by the repurchase.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a distinct new resource to a collection, return a `201 Created` status. Operations that modify an existing resource's state or attributes return a `200 OK` status. The table below lists the HTTP surface only; the business rules, request fields and side effects that govern each operation are stated in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wholesale-channel/brokers` | Submit a new brokerage for wholesale channel approval | ChannelManager |
| GET | `/wholesale-channel/brokers` | List brokerages with optional filters | Any |
| GET | `/wholesale-channel/brokers/{id}` | Get one brokerage | Any |
| GET | `/wholesale-channel/brokers/{id}/reconciliation` | Broker-level compensation and volume reconciliation snapshot | Any |
| POST | `/wholesale-channel/brokers/{id}/approve` | Approve a submitted brokerage | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/reinstate` | Reinstate a suspended brokerage | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/suspend` | Manually suspend an approved brokerage | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/terminate` | Terminate a brokerage relationship | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/licenses` | Record a brokerage license | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/licenses` | List a brokerage's licenses | Any |
| POST | `/wholesale-channel/brokers/{id}/licenses/{id}/revoke` | Revoke a license and cascade to affected loans | ComplianceOfficer |
| POST | `/wholesale-channel/brokers/{id}/financial-reviews` | Record a brokerage financial review | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/financial-reviews` | List a brokerage's financial reviews | Any |
| POST | `/wholesale-channel/financial-reviews/{id}/decision` | Record the PASSED or FAILED decision on a financial review | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/product-eligibilities` | Request a product eligibility for a brokerage | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/product-eligibilities` | List a brokerage's product eligibilities | Any |
| POST | `/wholesale-channel/product-eligibilities/{id}/decision` | Approve or revoke a product eligibility | ChannelManager |
| POST | `/wholesale-channel/exclusivity-policies` | Register a competitor exclusivity policy against a brokerage | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/exclusivity-policies` | List a brokerage's exclusivity policies | Any |
| POST | `/wholesale-channel/exclusivity-policies/{id}/void` | Void an exclusivity policy | ChannelManager |
| POST | `/wholesale-channel/compensation-plans` | Create a broker compensation plan | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/compensation-plans` | List a brokerage's compensation plans | Any |
| GET | `/wholesale-channel/compensation-plans/{id}` | Get one compensation plan | Any |
| PUT | `/wholesale-channel/compensation-plans/{id}` | Activate or deactivate a compensation plan | ChannelManager |
| POST | `/wholesale-channel/brokers/{id}/rate-sheets` | Publish a rate sheet for a broker and product; supersedes the prior PUBLISHED sheet | ChannelManager |
| GET | `/wholesale-channel/brokers/{id}/rate-sheets` | List a brokerage's rate sheets | Any |
| POST | `/wholesale-channel/brokers/{id}/rate-sheets/{id}/retire` | Retire a rate sheet that has never been priced against | ChannelManager |
| POST | `/wholesale-channel/rate-sheets/{id}/pricing-quotes` | Price a scenario against an immutable rate sheet | BrokerUser |
| GET | `/wholesale-channel/rate-sheets/{id}/pricing-quotes` | List the quotes priced off a rate sheet | Any |
| GET | `/wholesale-channel/pricing-quotes/{id}` | Get one pricing quote snapshot | Any |
| GET | `/wholesale-channel/pricing-quotes` | List pricing quotes, optionally filtered by broker | Any |
| GET | `/wholesale-channel/rate-sheets` | List rate sheets, optionally filtered by broker or by the sheet that superseded them | Any |
| GET | `/wholesale-channel/rate-sheets/{id}` | Get one rate sheet | Any |
| POST | `/wholesale-channel/loan-submissions` | Submit a broker-prepared loan file against a pricing quote | BrokerUser |
| GET | `/wholesale-channel/loan-submissions` | List loan submissions with filters | Any |
| GET | `/wholesale-channel/loan-submissions/{id}` | Get one loan submission | Any |
| POST | `/wholesale-channel/loan-submissions/{id}/compensation-election` | Elect lender-paid or borrower-paid compensation before underwriting | BrokerUser |
| POST | `/wholesale-channel/loan-submissions/{id}/underwrite` | Accept the broker file into underwriting | Underwriter |
| POST | `/wholesale-channel/loan-submissions/{id}/resubmit` | Return a suspended-review loan to the underwriter queue | BrokerUser |
| POST | `/wholesale-channel/loan-submissions/{id}/withdraw` | Withdraw a loan before it clears | BrokerUser |
| POST | `/wholesale-channel/loan-submissions/{id}/clear-to-close` | Clear the loan to close and stamp its closing commitment | Underwriter |
| POST | `/wholesale-channel/loan-submissions/{id}/fund` | Fund the loan | Underwriter |
| GET | `/wholesale-channel/closing-pipeline` | Closing pipeline view splitting loans by their stamped closing_path | Any |
| POST | `/wholesale-channel/underwriting-decisions` | Record an underwriter decision on a loan in underwriting | Underwriter |
| GET | `/wholesale-channel/loan-submissions/{id}/underwriting-decisions` | List the underwriting decisions recorded on a loan, oldest first | Any |
| GET | `/wholesale-channel/brokers/{id}/underwriting-decisions` | List every underwriting decision recorded against a brokerage's loans | Any |
| GET | `/wholesale-channel/loan-submissions/{id}/turn-time-escalations` | List a loan's turn-time escalations | Any |
| GET | `/wholesale-channel/brokers/{id}/turn-time-escalations` | List a brokerage's turn-time escalations | Any |
| POST | `/wholesale-channel/turn-time-escalations/{id}/resolve` | Resolve or reopen-extend a turn-time escalation | ChannelManager |
| POST | `/wholesale-channel/quality-control-reviews` | Open a post-funding quality control review on a funded loan | QualityControlAnalyst |
| GET | `/wholesale-channel/brokers/{id}/quality-control-reviews` | List a brokerage's quality control reviews | Any |
| GET | `/wholesale-channel/loan-submissions/{id}/quality-control-reviews` | List the quality control reviews recorded on a loan | Any |
| GET | `/wholesale-channel/quality-control-reviews` | List quality control reviews across brokers, optionally filtered by broker or loan | Any |
| POST | `/wholesale-channel/quality-control-reviews/{id}/resolve` | Remediate, void or date-correct a quality control finding | QualityControlAnalyst |
| POST | `/wholesale-channel/quality-control-reviews/{id}/repurchase` | Exercise repurchase on a critical defect inside its window | QualityControlAnalyst |
| POST | `/wholesale-channel/_clock/set_current_utc` | Set the logical clock; re-evaluates license expiry, escalations and derived broker state | PlatformAdmin |

## 5. Error Code Catalogue

Each error identifier below is the exact string the service returns in the `error_id` field of the error envelope. The conditions that trigger each one are stated in §2 and §3 rather than here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_BROKER_RESOURCE_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_BROKER_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_ELIGIBILITY_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ESCALATION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BROKER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_BROKER_NOT_SUSPENDABLE` | 409 Conflict |
| `ERR_BROKER_NOT_APPROVED` | 403 Forbidden |
| `ERR_BROKER_EXCLUSIVITY_BLOCKED` | 403 Forbidden |
| `ERR_BROKER_EXCLUSIVITY_RESTRICTED` | 403 Forbidden |
| `ERR_EXCLUSIVITY_POLICY_BREACH` | 403 Forbidden |
| `ERR_BROKER_DEFECT_HOLD` | 403 Forbidden |
| `ERR_BROKER_QUALITY_BELOW_REINSTATEMENT` | 403 Forbidden |
| `ERR_ACTIVE_LOANS_PRESENT` | 409 Conflict |
| `ERR_FINANCIAL_REVIEW_PENDING` | 409 Conflict |
| `ERR_NO_VALID_LICENSE` | 409 Conflict |
| `ERR_DUPLICATE_NMLS_ID` | 409 Conflict |
| `ERR_PROPERTY_STATE_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PRICING_QUOTE_SUPERSEDED` | 409 Conflict |
| `ERR_COMPENSATION_PLAN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMPENSATION_ELECTION_IMMUTABLE` | 409 Conflict |
| `ERR_COMPENSATION_ELECTION_PENDING` | 409 Conflict |
| `ERR_LOAN_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LOAN_NOT_UNDERWRITING` | 409 Conflict |
| `ERR_LOAN_NOT_CONDITIONAL` | 409 Conflict |
| `ERR_LOAN_NOT_CLEAR_TO_CLOSE` | 409 Conflict |
| `ERR_LOAN_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_LOAN_NOT_SUSPENDED` | 409 Conflict |
| `ERR_DEFECT_REMEDIATION_OPEN` | 409 Conflict |
| `ERR_CLOSING_ESCALATION_OPEN` | 409 Conflict |
| `ERR_QC_REVIEW_EXISTS` | 409 Conflict |
| `ERR_REPURCHASE_NOT_REQUIRED` | 409 Conflict |
| `ERR_REPURCHASE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_LOAN_ALREADY_REPURCHASED` | 409 Conflict |
| `ERR_LAST_ACTIVE_COMPENSATION_PLAN` | 409 Conflict |
| `ERR_SHEET_IN_USE` | 409 Conflict |
| `ERR_ESCALATION_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_REVIEW_ALREADY_DECIDED` | 409 Conflict |
| `ERR_ELIGIBILITY_ALREADY_DECIDED` | 409 Conflict |
| `ERR_LICENSE_NOT_REVOCABLE` | 409 Conflict |
| `ERR_NET_WORTH_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DECISION_CONDITIONS_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |