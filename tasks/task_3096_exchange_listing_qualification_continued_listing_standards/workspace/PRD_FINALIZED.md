# Exchange Listing Standards API — Product Requirements Document

## 1. Introduction

Public companies seeking to list their securities on a national exchange face a rigorous qualification process that extends well beyond the initial application. Once listed, issuers must continuously satisfy financial, liquidity, and corporate governance standards; failures trigger deficiency notices, cure periods, compliance plans, and—when remediation fails—delisting proceedings with hearings and appeals. The exchange itself must coordinate multiple internal constituencies: listing qualifications staff who evaluate applications and monitor continued compliance, hearings panels that adjudicate staff delisting determinations, a Listing Council that serves as the terminal appellate body, and a finance department that bills entry and annual fees according to tier-specific schedules.

This document specifies the API for an Exchange Listing Qualification and Continued Listing Standards system. The system supports the full lifecycle from issuer registration through initial listing application (including transfers from other exchanges and readmissions after delisting), ongoing market-data surveillance, deficiency detection and cure, tier-transfer planning, delisting execution, and fee administration. A logical clock drives all temporal rules—cure windows, appeal windows, and annual billing cycles—so that every deadline is deterministic and auditable. The design follows a segregation-of-duties model: issuer officers file documents for their own issuer, listing analysts evaluate and decide, hearings officers and council members adjudicate appeals, and finance officers bill—no single actor may perform consecutive steps in the same workflow.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. The absence or emptiness of either header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The role named in `X-User-Role` must be one of the five defined roles—`IssuerOfficer`, `ListingAnalyst`, `HearingsOfficer`, `ListingsCouncil`, or `FinanceOfficer`—and must be authorized for the specific endpoint; otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

When `X-User-Role` is `IssuerOfficer`, `X-User-ID` is the `id` of the acting `Issuer`; ownership checks on any resource that references an `Issuer` compare the resource's foreign-key field to `X-User-ID`. An `IssuerOfficer` acting on a path whose `{issuerId}` segment does not equal `X-User-ID` is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). For the remaining roles—`ListingAnalyst`, `HearingsOfficer`, `ListingsCouncil`, and `FinanceOfficer`—`X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as the actor on a state transition) but does not compare it to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. The `meta` object of a list response includes `limit`, `offset`, `total_count`, and `has_more`. List results are sorted by `created_at` ascending unless the endpoint narrative specifies otherwise.

### 2.4. Common Resource Properties

Every entity carries an `id` field, a server-minted UUID with no type prefix. Entities with `common_fields: true` also carry `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer starting at 1, incremented on every mutation). The `MarketDataSnapshot` and `ComplianceRecord` entities are immutable observation logs: they carry only `id` and `created_at`; both `updated_at` and `version` are absent from their representations.

### 2.5. Logical Clock and Temporal Determinism

The server maintains a logical clock, initialized to exactly 2026-09-01T00:00:00Z before any call. The clock must never fall back to wall-clock time. A `ListingAnalyst` may advance the clock by supplying a `current_utc` instant. All temporal rules—cure windows, appeal windows, snapshot date validation, annual fee billing—read from this logical clock.

### 2.6. Precision and Rounding

All monetary amounts are expressed in integer cents; no rounding is applied. All day counts (consecutive-day streaks, cure windows, appeal windows) are expressed as integer calendar days; no rounding is applied.

### 2.7. Optimistic Concurrency Control

Two write endpoints require optimistic concurrency control against the parent `Issuer`. A request to approve a listing application must carry `expected_issuer_version` matching the target issuer's current `version`. A request to run annual fee assessment must likewise carry `expected_issuer_version` matching the issuer's current `version`. If the issuer's version has advanced since the client last observed it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.8. Hierarchical Consistency and Cascading Finalization

Mutations are atomic within a single request. When a listing is delisted, the system performs a cascade: the listing transitions `ACTIVE` → `SUSPENDED` → `DELISTED` in the same request, the issuer's status becomes `DELISTED`, all pending fee assessments are invoiced, an annual fee row is created if none exists for the current year, open deficiencies are closed as `DELIST_UPHELD`, undecided appeals are affirmed by panel, and submitted corporate actions are cancelled. Each of these side effects is described in the relevant workflow narrative in §3.

### 2.9. Nested Resource Retrieval

URL path parameters are validated left-to-right: the issuer is resolved before any nested resource. An unknown nested identifier yields the entity-specific 404 error—`ERR_ISSUER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, or `ERR_ACTION_NOT_FOUND`—depending on which path segment failed to resolve.

### 2.10. Segregation of Duties

The acting `X-User-ID` must not equal the `X-User-ID` that performed the immediately preceding workflow step on the same resource. This applies to compliance-plan review (the plan filer may not review it), appeal panel decision (the appeal filer may not decide it), and appeal council decision (the appeal filer may not decide it). Violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Issuer Registration and Listing Application

A `ListingAnalyst` registers a new issuer by supplying its `legal_name` and `ticker_symbol`. The ticker must be unique across all issuers regardless of status; a duplicate is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The issuer begins in `PRE_LISTING` status.

An `IssuerOfficer` files a listing application for their issuer, providing the `target_tier` (one of `GLOBAL_SELECT`, `GLOBAL`, or `CAPITAL`), the full `board_directors` array, the `audit_committee` and `compensation_committee` arrays, and a comprehensive set of financial and liquidity metrics: `stockholders_equity_cents`, `market_value_listed_securities_cents`, `market_value_unrestricted_publicly_held_cents`, `total_revenue_cents`, `income_from_continuing_operations_cents`, `bid_price_cents`, `publicly_held_shares`, `unrestricted_publicly_held_shares`, `round_lot_holders`, `total_shareholders`, `market_makers`, and `operating_history_months`. The `is_transfer_from_exchange` flag defaults to false; the `application_kind` defaults to `INITIAL` but may be `TRANSFER`, `TIER_TRANSFER`, or `READMISSION`. A readmission application is selected by passing `readmission` as true; the issuer must be `DELISTED` and must never have had a prior `READMISSION` application rejected—otherwise the create is rejected with `ERR_READMISSION_BARRED` (HTTP 422). The application begins in `DRAFT` status.

### 3.2. Application Submission, Governance Validation, and Tier Evaluation

When the `IssuerOfficer` submits the application, the system first validates governance composition: the board must have a strictly majority of independent directors (more than half of `board_directors` must have `is_independent` true); the audit committee must have at least three members, all independent, with at least one financial expert; the compensation committee must have at least two members, all independent; and every committee member must appear in `board_directors` by `director_name`. Failure is rejected with `ERR_GOVERNANCE_COMPOSITION` (HTTP 422). The issuer must not already have another `SUBMITTED` application; if it does, the submit is rejected with `ERR_MULTIPLE_PENDING_APPLICATIONS` (HTTP 409). For a `TRANSFER` application, `is_transfer_from_exchange` must be true; otherwise `ERR_INVALID_REQUEST` (HTTP 400).

If governance passes, the system evaluates the application against the entry standards of the `target_tier`. The `GLOBAL_SELECT` tier passes if any one of three standards is met: standard 1 requires `income_from_continuing_operations_cents` of at least 1,100,000,000 cents; standard 2 requires `market_value_listed_securities_cents` of at least 45,000,000,000,000 cents and `unrestricted_publicly_held_shares` of at least 1,250,000; standard 3 requires `total_revenue_cents` of at least 9,000,000,000,000 cents and `market_value_listed_securities_cents` of at least 20,000,000,000,000 cents. The `GLOBAL` tier passes if any one of three standards is met: standard 1 requires `stockholders_equity_cents` of at least 1,500,000,000 cents, `market_value_unrestricted_publicly_held_cents` of at least 800,000,000 cents, `round_lot_holders` of at least 400, and `market_makers` of at least 3; standard 2 requires `market_value_listed_securities_cents` of at least 7,500,000,000,000 cents, `market_value_unrestricted_publicly_held_cents` of at least 2,000,000,000 cents, `round_lot_holders` of at least 400, and `market_makers` of at least 3; standard 3 requires `total_revenue_cents` of at least 7,500,000,000,000 cents, `market_value_unrestricted_publicly_held_cents` of at least 2,000,000,000 cents, `round_lot_holders` of at least 400, and `market_makers` of at least 3. The `CAPITAL` tier requires all of the following: `bid_price_cents` of at least 400, `publicly_held_shares` of at least 1,000,000, `round_lot_holders` of at least 300, `market_makers` of at least 3, and any one of: `stockholders_equity_cents` of at least 500,000,000 cents, `market_value_listed_securities_cents` of at least 5,000,000,000,000 cents, or `income_from_continuing_operations_cents` of at least 75,000,000 cents.

The evaluation fills `evaluated_standards` with the per-standard results and margins. If no standard passes, the application auto-transitions from `DRAFT` to `REJECTED` in the same request; the submit returns 200 with the `REJECTED` application. If the application was a `READMISSION`, the system sets `readmission_rejected` to true, barring any future readmission attempt.

### 3.3. Application Adjudication and Listing Creation

A `ListingAnalyst` may approve a `SUBMITTED` application. The request must carry `expected_issuer_version` matching the issuer's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). At least one evaluated standard must have passed; an application that auto-rejected at submit is no longer `SUBMITTED`, so approval surfaces as `ERR_INVALID_STATE` (HTTP 409). For `TIER_TRANSFER` applications, the issuer must have an `ACTIVE` listing and the `target_tier` must be strictly lower than the listing's current tier; failure is `ERR_TIER_TRANSFER_TARGET_INVALID` (HTTP 422). The issuer must also meet the continued (not entry) standards of the target tier, evaluated from the application's metric fields; failure is `ERR_NO_STANDARD_MET` (HTTP 422).

Upon approval, the issuer's `version` increments by 1, and the application becomes `APPROVED`. For `INITIAL`, `TRANSFER`, and `READMISSION` applications, the system creates a `Listing` with `tier` set to the application's `target_tier`, `status` `ACTIVE`, and `application_id` recording which application's approval created the listing; the issuer's status becomes `LISTED`; and an `ENTRY` `FeeAssessment` is created with `tier` equal to the application's `target_tier`, `assessment_year` equal to the logical-clock year, `shares_outstanding` equal to the application's `unrestricted_publicly_held_shares`, and status `PENDING`. The entry fee amount is computed from the inclusive-of-entry-fee bracket table described in §3.10. For `TIER_TRANSFER` applications, no new listing is created; the existing `ACTIVE` listing's `tier` is updated to the `target_tier`, and no entry fee is assessed.

A `ListingAnalyst` may reject a `SUBMITTED` application; the application becomes `REJECTED`. If the application was a `READMISSION`, `readmission_rejected` is set to true.

### 3.4. Market Data Surveillance and Deficiency Detection

A `ListingAnalyst` records end-of-day market observations for an issuer by submitting a `trade_date` (which must equal the logical clock's current date and must be unique per issuer—violations are `ERR_SNAPSHOT_DATE_MISMATCH`, HTTP 422), `closing_bid_cents`, `market_value_publicly_held_cents`, `market_value_listed_securities_cents`, `round_lot_holders`, and `total_shareholders`. A `closing_bid_cents` of 0 is permitted and still counts as an observation day.

A `ListingAnalyst` runs the deficiency monitor for one issuer. The monitor examines the issuer's snapshots ordered by `trade_date` descending. For each monitored standard—`BID_PRICE`, `MVPHS`, `MVLS`, `ROUND_LOT_HOLDERS`, and `TOTAL_SHAREHOLDERS`—it walks backward from the latest snapshot counting consecutive days that strictly fail the tier threshold. The bid-price threshold is 100 cents at every tier. The `MVPHS` threshold is 5,000,000,000 cents at `GLOBAL` and 1,000,000,000 cents at `CAPITAL`; `GLOBAL_SELECT` uses the `MVLS` leg instead. The `MVLS` threshold is 30,000,000,000,000 cents at `GLOBAL_SELECT`, 7,500,000,000,000 cents at `GLOBAL`, and 5,000,000,000,000 cents at `CAPITAL`. The `ROUND_LOT_HOLDERS` and `TOTAL_SHAREHOLDERS` thresholds are 400 at `GLOBAL_SELECT` and `GLOBAL`, and 300 at `CAPITAL`. The walk stops at the first compliant day or when snapshots run out.

If the consecutive failure count reaches the trigger—30 days for `BID_PRICE`, 10 days for all others—and no deficiency for that issuer and standard already exists in a non-terminal status, the system creates a `Deficiency` with `tier_at_detection` set to the listing's current tier, `consecutive_days_failed` set to the run length, `detected_at` set to the logical clock, `compliance_due_at` set to 180 calendar days after detection, and status `OPEN`.

For every non-terminal deficiency of the issuer, the monitor recomputes `still_open` and checks for regain: if the trailing window shows at least 10 consecutive compliant days for the deficiency's standard, the deficiency transitions `OPEN` → `REGAINED` (or `PLAN_SUBMITTED` → `REGAINED` if a plan is pending), a `ComplianceRecord` is created with `method` `NATURAL`, `qualifying_days` set to the run length, and `regained_at` set to the logical clock; the deficiency's `closed_at` is set. `STOCKHOLDERS_EQUITY` is not snapshot-monitored.

### 3.5. Compliance Plans and Tier-Transfer Cure

An `IssuerOfficer` files a compliance plan, naming the target deficiency via `deficiency_id`, against an `OPEN` deficiency whose `compliance_due_at` is strictly in the future. At most one plan ever exists per deficiency; filing against a non-`OPEN` deficiency, a lapsed cure period, or a deficiency that already has a plan is rejected with `ERR_PLAN_NOT_ALLOWED` (HTTP 422). The plan carries `plan_text`, `plan_kind` (`CURE_IN_PLACE` or `TIER_TRANSFER`), and—if `plan_kind` is `TIER_TRANSFER`—a `proposed_target_tier` that must be strictly lower than the deficiency's `tier_at_detection`. Filing the plan transitions the deficiency `OPEN` → `PLAN_SUBMITTED`.

A `ListingAnalyst` reviews the plan, supplying a `decision` (`APPROVE` or `REJECT`) and a `review_decision_reason`. The plan must be `PENDING_REVIEW`; a second review attempt on an already-decided plan is rejected with `ERR_PLAN_UNDER_REVIEW` (HTTP 409). The deficiency must be `PLAN_SUBMITTED`; otherwise `ERR_INVALID_STATE` (HTTP 409). The reviewer must not be the same `X-User-ID` that filed the plan; violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). For a `TIER_TRANSFER` plan, the `proposed_target_tier` must be strictly lower than the listing's current tier, and the issuer's most recent snapshot must satisfy the continued standards of the proposed tier; failure is `ERR_TIER_TRANSFER_TARGET_INVALID` (HTTP 422). The continued standards are: for `GLOBAL_SELECT`, `market_value_listed_securities_cents` of at least 30,000,000,000,000 cents; for `GLOBAL`, `market_value_publicly_held_cents` of at least 5,000,000,000 cents and `round_lot_holders` of at least 400; for `CAPITAL`, `market_value_publicly_held_cents` of at least 1,000,000,000 cents and `round_lot_holders` of at least 300. Snapshot fields map onto these thresholds as: the `MVLS` leg reads `market_value_listed_securities_cents`, the `MVPHS` leg reads `market_value_publicly_held_cents`, and the holders leg reads `round_lot_holders`; `total_shareholders` is monitored but never gates a tier transfer.

Approving a `CURE_IN_PLACE` plan transitions the deficiency `PLAN_SUBMITTED` → `REGAINED` and creates a `ComplianceRecord` with `method` `PLAN_APPROVED` and `qualifying_days` 0. Approving a `TIER_TRANSFER` plan transitions the deficiency `PLAN_SUBMITTED` → `REGAINED`, creates a `ComplianceRecord` with `method` `TIER_TRANSFER` and `qualifying_days` 0, and updates the listing's `tier` to the `proposed_target_tier`. Rejecting a plan leaves the deficiency in `PLAN_SUBMITTED`, allowing staff to proceed to a delisting determination.

### 3.6. Staff Delisting Determination and Appeal Window

A `ListingAnalyst` may issue a staff delisting determination. For an `OPEN` deficiency, the logical clock must be strictly after `compliance_due_at`; otherwise the request is rejected with `ERR_CURE_PERIOD_ACTIVE` (HTTP 422). For a `PLAN_SUBMITTED` deficiency, the determination is allowed if the plan has been `REJECTED` or if the clock has passed `compliance_due_at`; if neither holds, `ERR_CURE_PERIOD_ACTIVE` (HTTP 422). The determination sets `staff_determined_at` to the logical clock and transitions the deficiency to `STAFF_DELIST_DETERMINED`.

An `IssuerOfficer` may appeal the determination by filing an appeal with an `OPEN` hearings panel, identified by `review_id`. The appeal records `filed_at` as the logical-clock timestamp of filing. The appeal must be filed while the deficiency is `STAFF_DELIST_DETERMINED` and no later than 7 calendar days after `staff_determined_at`; filing outside this window is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422). At most one appeal ever exists per deficiency. Filing the appeal transitions the deficiency `STAFF_DELIST_DETERMINED` → `PANEL_REVIEW`.

### 3.7. Hearings Panel and Appeal Adjudication

A `HearingsOfficer` opens a hearings panel for an issuer by supplying the `issuer_id` and a `panel_name`; the panel begins `OPEN`. A panel may be closed by a `HearingsOfficer`; an appeal that references a `CLOSED` panel is rejected with `ERR_HEARING_NOT_OPEN` (HTTP 422).

A `HearingsOfficer` takes a filed appeal under review; the appeal transitions `FILED` → `PANEL_REVIEWING`. The panel then renders a decision. The decider must not be the same `X-User-ID` that filed the appeal; violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An `AFFIRM` decision transitions the appeal `PANEL_REVIEWING` → `PANEL_AFFIRMED`, sets `decided_by` to `PANEL`, and transitions the deficiency `PANEL_REVIEW` → `DELIST_UPHELD` with `closed_at` set. A `REVERSE` decision transitions the appeal `PANEL_REVIEWING` → `PANEL_REVERSED`, sets `decided_by` to `PANEL`, and transitions the deficiency `PANEL_REVIEW` → `DELIST_REVERSED` with `closed_at` set; a new `OPEN` deficiency row is created with the same `standard_code` and `tier_at_detection`, `detected_at` set to the logical clock, and `compliance_due_at` set to 180 days after the clock. The hearings panel remains `OPEN` and may serve other appeals.

A `ListingsCouncil` member may take a decided appeal under council review. Council review is available only from `PANEL_AFFIRMED` or `PANEL_REVERSED`; from any other state the request is rejected with `ERR_COUNCIL_REVIEW_NOT_AVAILABLE` (HTTP 422). The appeal transitions to `COUNCIL_REVIEWING`. The council then renders a decision. The decider must not be the same `X-User-ID` that filed the appeal; violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An `AFFIRM` decision transitions the appeal `COUNCIL_REVIEWING` → `COUNCIL_AFFIRMED`, sets `decided_by` to `COUNCIL`, and—if the deficiency is still in `PANEL_REVIEW`—transitions it to `DELIST_UPHELD`. A `REVERSE` decision transitions the appeal `COUNCIL_REVIEWING` → `COUNCIL_REVERSED`, sets `decided_by` to `COUNCIL`, and transitions the deficiency to `DELIST_REVERSED` with the same new-`OPEN`-deficiency side effect as a panel reversal.

### 3.8. Delisting Execution

A `ListingAnalyst` executes the delisting of a listing whose delisting is final. Execution requires either that the deficiency is `STAFF_DELIST_DETERMINED` with the logical clock strictly after `staff_determined_at` plus 7 days and no appeal filed, or that the deficiency is `DELIST_UPHELD` via a decided appeal (`PANEL_AFFIRMED` or `COUNCIL_AFFIRMED`). An appeal in `PANEL_REVIEWING` or `COUNCIL_REVIEWING` blocks execution; the request is rejected with `ERR_DELISTING_BLOCKED` (HTTP 422).

Execution performs the full cascade in one request: the listing transitions `ACTIVE` → `SUSPENDED` with `suspended_at` set to the logical clock, then `SUSPENDED` → `DELISTED` with `delisted_at` set; the issuer's status becomes `DELISTED`; every `PENDING` fee assessment of the issuer becomes `INVOICED`; if no `ANNUAL` fee assessment (that is, no row whose `fee_kind` is `ANNUAL`) exists for the logical-clock year, one is created with `delisted_mid_year` set to true, `tier` set to the listing's tier at execution, `shares_outstanding` taken from the latest `ANNUAL` assessment if any otherwise from the approving application's `unrestricted_publicly_held_shares`, halved (floor) per `EFFECTIVE` `REVERSE_SPLIT` corporate action in the order those actions became effective (earliest first), status `PENDING` then immediately `INVOICED`; every deficiency in `OPEN`, `PLAN_SUBMITTED`, `STAFF_DELIST_DETERMINED`, or `PANEL_REVIEW` becomes `DELIST_UPHELD` with `closed_at` set; every appeal in `FILED` or `PANEL_REVIEWING` becomes `PANEL_AFFIRMED` with `decided_by` `PANEL`; and every `SUBMITTED` corporate action becomes `CANCELLED`.

### 3.9. Reverse-Split Corporate Actions

An `IssuerOfficer` submits a corporate action; only reverse splits are modelled, so `action_type` is always `REVERSE_SPLIT`. The `split_ratio_denominator` must be at least 2. The action begins `SUBMITTED`, with `announced_at` set to the logical-clock timestamp of submission.

A `ListingAnalyst` makes the action effective. The issuer must have a `BID_PRICE` deficiency in `OPEN` or `PLAN_SUBMITTED` status; otherwise the request is rejected with `ERR_NO_QUALIFYING_DEFICIENCY` (HTTP 422). The system runs a split-adjusted projection over the trailing 10-snapshot window: each day's `closing_bid_cents` is multiplied by the `split_ratio_denominator`; days with a closing bid of 0 never qualify (0 times any denominator remains 0, which is below 100). If the projection finds at least 10 consecutive days with an adjusted bid of at least 100, the qualifying `BID_PRICE` deficiency transitions to `REGAINED` with a `ComplianceRecord` of `method` `REVERSE_SPLIT` and `qualifying_days` equal to the run length. If that deficiency was `PLAN_SUBMITTED`, its plan becomes `REJECTED` (superseded).

A `ListingAnalyst` may reject a `SUBMITTED` action; an `IssuerOfficer` may cancel a `SUBMITTED` action. A delisting execution also cancels all `SUBMITTED` actions.

### 3.10. Fee Assessment and Collection

Fees are computed in integer cents with no rounding, and the computed charge is recorded on the assessment as `amount_cents`. The entry fee is assessed once at listing approval from the inclusive-of-entry-fee bracket table. For `GLOBAL_SELECT` and `GLOBAL` (shared table): 1 to 50,000,000 shares yields 15,000,000 to 25,000,000 cents; 50,000,001 to 75,000,000 shares yields 20,000,000 to 30,000,000 cents; 75,000,001 to 100,000,000 shares yields 25,000,000 to 35,000,000 cents; above 100,000,000 shares yields 29,500,000 to 50,000,000 cents. For `CAPITAL`: 1 to 5,000,000 shares yields 5,000,000 to 7,500,000 cents; 5,000,001 to 15,000,000 shares yields 7,500,000 to 10,000,000 cents; above 15,000,000 shares yields 10,000,000 to 15,000,000 cents. Bracket membership is inclusive on both ends; every share count of at least 1 belongs to exactly one row; counts above the top row's upper bound clamp to the top row's maximum. Within a bracket row, the charged amount equals the share count expressed in cents and clamped to the row's stated range—that is, raised to the row's minimum when below it and lowered to the row's maximum when above it. The same in-bracket rule applies to both the entry table and the annual table below.

A `FinanceOfficer` assesses the annual fee for the logical-clock year by supplying `shares_outstanding` and `expected_issuer_version`. The issuer must be `LISTED` with an `ACTIVE` listing; no `ANNUAL` fee assessment may already exist for the clock year; and `shares_outstanding` must be at least 1. Violation of any of these is rejected with `ERR_FEE_ALREADY_ASSESSED` (HTTP 409). The issuer's version must match `expected_issuer_version`; mismatch is `ERR_STALE_VERSION` (HTTP 412). The annual fee uses the exclusive-of-entry-fee bracket table, which is strictly lower than the entry table for the same tier and share count. For `GLOBAL_SELECT` and `GLOBAL`: 1 to 50,000,000 shares yields 4,500,000 to 10,500,000 cents; 50,000,001 to 75,000,000 shares yields 5,500,000 to 12,500,000 cents; 75,000,001 to 100,000,000 shares yields 6,500,000 to 14,500,000 cents; above 100,000,000 shares yields 7,500,000 to 17,500,000 cents. For `CAPITAL`: 1 to 5,000,000 shares yields 3,000,000 to 5,000,000 cents; 5,000,001 to 15,000,000 shares yields 4,000,000 to 6,500,000 cents; above 15,000,000 shares yields 5,000,000 to 8,000,000 cents. A fee row whose `delisted_mid_year` flag is true adds a flat surcharge of 1,000,000 cents after the bracket clamp; the surcharge is never bracket-adjusted. The annual fee's `tier` is the listing's tier on the logical-clock date of the run, and its `assessment_year` is the billing year. The fee is created in `PENDING` status and immediately becomes `INVOICED`; the issuer's `version` increments by 1.

A `FinanceOfficer` may mark an `INVOICED` fee as `PAID`; a fee on a `DELISTED` issuer may still be paid. A `FinanceOfficer` may waive an `INVOICED` fee, transitioning it to `WAIVED`. Attempting either operation on a fee not in `INVOICED` status is rejected with `ERR_INVALID_STATE` (HTTP 409).

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | /_clock/set_current_utc | Set the server's logical clock | ListingAnalyst |
| POST | /issuers | Register an issuer (PRE_LISTING) | ListingAnalyst |
| GET | /issuers | List issuers | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /issuers/{issuerId} | Get an issuer | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| POST | /issuers/{issuerId}/listing-applications | Create a listing application (DRAFT) | IssuerOfficer |
| GET | /issuers/{issuerId}/listing-applications | List an issuer's applications | ListingAnalyst, IssuerOfficer |
| GET | /listing-applications | Cross-issuer listing application index | ListingAnalyst |
| GET | /listing-applications/{applicationId} | Get an application by id (cross-issuer index) | ListingAnalyst |
| GET | /issuers/{issuerId}/listing-applications/{applicationId} | Get an application (includes evaluated_standards after submit) | ListingAnalyst, IssuerOfficer |
| POST | /issuers/{issuerId}/listing-applications/{applicationId}/submit | Submit: runs governance validation + tier standard evaluation; auto-rejects when no standard passes | IssuerOfficer |
| POST | /issuers/{issuerId}/listing-applications/{applicationId}/approve | Approve a SUBMITTED application (OCC on issuer version) | ListingAnalyst |
| POST | /issuers/{issuerId}/listing-applications/{applicationId}/reject | Reject a SUBMITTED application | ListingAnalyst |
| GET | /issuers/{issuerId}/listings | List an issuer's listings | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /listings | Cross-issuer listing index | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /listings/{listingId} | Get a listing by id (cross-issuer index) | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /issuers/{issuerId}/listings/{listingId} | Get a listing | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| POST | /issuers/{issuerId}/listings/{listingId}/execute-delisting | Execute the delisting of a listing whose delisting is final | ListingAnalyst |
| POST | /issuers/{issuerId}/market-data-snapshots | Record an end-of-day observation | ListingAnalyst |
| GET | /issuers/{issuerId}/market-data-snapshots | List snapshots (trade_date DESC) | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /issuers/{issuerId}/market-data-snapshots/{snapshotId} | Get a snapshot | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /market-data-snapshots | Cross-issuer snapshot index | ListingAnalyst |
| GET | /market-data-snapshots/{snapshotId} | Get a snapshot by id (cross-issuer index) | ListingAnalyst |
| POST | /issuers/{issuerId}/deficiency-monitor/run | Run deficiency detection + regain scan for one issuer | ListingAnalyst |
| GET | /issuers/{issuerId}/deficiencies | List deficiencies | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| GET | /deficiencies | Cross-issuer deficiency index | ListingAnalyst, HearingsOfficer, ListingsCouncil |
| GET | /deficiencies/{deficiencyId} | Get a deficiency by id (cross-issuer index) | ListingAnalyst, HearingsOfficer, ListingsCouncil |
| GET | /deficiencies/{id}/compliance-records | List compliance records for a deficiency | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /deficiencies/{id}/compliance-plans | List compliance plans for a deficiency (0 or 1 rows) | ListingAnalyst, IssuerOfficer |
| GET | /deficiencies/{id}/appeals | List appeals for a deficiency (0 or 1 rows) | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| GET | /issuers/{issuerId}/deficiencies/{deficiencyId} | Get a deficiency | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| POST | /issuers/{issuerId}/deficiencies/{deficiencyId}/staff-determine-delisting | Staff delisting determination after cure lapse or plan rejection | ListingAnalyst |
| GET | /issuers/{issuerId}/compliance-records | List compliance records (regain events) | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /issuers/{issuerId}/compliance-records/{recordId} | Get a compliance record | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /compliance-records | Cross-issuer compliance record index | ListingAnalyst, FinanceOfficer |
| GET | /compliance-records/{recordId} | Get a compliance record by id (cross-issuer index) | ListingAnalyst, FinanceOfficer |
| GET | /compliance-plans | Cross-issuer compliance plan index | ListingAnalyst |
| GET | /compliance-plans/{planId} | Get a compliance plan by id (cross-issuer index) | ListingAnalyst |
| GET | /appeals | Cross-issuer appeal index | ListingAnalyst, HearingsOfficer, ListingsCouncil |
| GET | /appeals/{appealId} | Get an appeal by id (cross-issuer index) | ListingAnalyst, HearingsOfficer, ListingsCouncil |
| GET | /fee-assessments | Cross-issuer fee assessment index | ListingAnalyst, FinanceOfficer |
| GET | /fee-assessments/{feeId} | Get a fee assessment by id (cross-issuer index) | ListingAnalyst, FinanceOfficer |
| GET | /corporate-actions | Cross-issuer corporate action index | ListingAnalyst |
| GET | /corporate-actions/{actionId} | Get a corporate action by id (cross-issuer index) | ListingAnalyst |
| POST | /issuers/{issuerId}/compliance-plans | File a compliance plan against an OPEN deficiency | IssuerOfficer |
| GET | /issuers/{issuerId}/compliance-plans | List compliance plans | ListingAnalyst, IssuerOfficer |
| GET | /issuers/{issuerId}/compliance-plans/{planId} | Get a compliance plan | ListingAnalyst, IssuerOfficer |
| POST | /issuers/{issuerId}/compliance-plans/{planId}/review | Approve or reject a plan | ListingAnalyst |
| POST | /hearings-reviews | Open a hearings panel | HearingsOfficer |
| GET | /hearings-reviews | List hearings panels | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| GET | /hearings-reviews/{reviewId} | Get a hearings panel | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| POST | /hearings-reviews/{reviewId}/close | Close a panel | HearingsOfficer |
| GET | /issuers/{issuerId}/hearings-reviews | List hearings panels for an issuer | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| POST | /issuers/{issuerId}/appeals | File an appeal of a staff delisting determination with an OPEN panel | IssuerOfficer |
| GET | /issuers/{issuerId}/appeals | List appeals | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| GET | /issuers/{issuerId}/appeals/{appealId} | Get an appeal | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| GET | /hearings-reviews/{reviewId}/appeals | List appeals filed with a given hearings panel | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil |
| POST | /issuers/{issuerId}/appeals/{appealId}/panel-review | Panel takes the appeal under review | HearingsOfficer |
| POST | /issuers/{issuerId}/appeals/{appealId}/panel-decision | Panel affirms or reverses | HearingsOfficer |
| POST | /issuers/{issuerId}/appeals/{appealId}/council-review | Listings Council takes a decided appeal under review | ListingsCouncil |
| POST | /issuers/{issuerId}/appeals/{appealId}/council-decision | Council affirms or reverses (terminal) | ListingsCouncil |
| POST | /issuers/{issuerId}/fee-assessments/run-annual-fees | Assess the annual fee for the clock year | FinanceOfficer |
| GET | /issuers/{issuerId}/fee-assessments | List fee assessments | ListingAnalyst, IssuerOfficer, FinanceOfficer |
| GET | /issuers/{issuerId}/fee-assessments/{feeId} | Get a fee assessment | ListingAnalyst, IssuerOfficer, FinanceOfficer |
| POST | /issuers/{issuerId}/fee-assessments/{feeId}/mark-paid | Mark an invoiced fee paid | FinanceOfficer |
| POST | /issuers/{issuerId}/fee-assessments/{feeId}/waive | Waive an invoiced fee | FinanceOfficer |
| POST | /issuers/{issuerId}/corporate-actions | Submit a corporate action (reverse split) | IssuerOfficer |
| GET | /issuers/{issuerId}/corporate-actions | List corporate actions | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| GET | /issuers/{issuerId}/corporate-actions/{actionId} | Get a corporate action | ListingAnalyst, IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer |
| POST | /issuers/{issuerId}/corporate-actions/{actionId}/effect | Make a reverse split effective; runs the split-adjusted bid regain projection | ListingAnalyst |
| POST | /issuers/{issuerId}/corporate-actions/{actionId}/reject | Reject a corporate action | ListingAnalyst |
| POST | /issuers/{issuerId}/corporate-actions/{actionId}/cancel | Withdraw a corporate action | IssuerOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ISSUER_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_LISTING_NOT_FOUND | 404 |
| ERR_DEFICIENCY_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_REVIEW_NOT_FOUND | 404 |
| ERR_FEE_NOT_FOUND | 404 |
| ERR_ACTION_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_READMISSION_BARRED | 422 |
| ERR_GOVERNANCE_COMPOSITION | 422 |
| ERR_MULTIPLE_PENDING_APPLICATIONS | 409 |
| ERR_NO_STANDARD_MET | 422 |
| ERR_TIER_TRANSFER_TARGET_INVALID | 422 |
| ERR_SNAPSHOT_DATE_MISMATCH | 422 |
| ERR_PLAN_NOT_ALLOWED | 422 |
| ERR_CURE_PERIOD_ACTIVE | 422 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_DELISTING_BLOCKED | 422 |
| ERR_COUNCIL_REVIEW_NOT_AVAILABLE | 422 |
| ERR_HEARING_NOT_OPEN | 422 |
| ERR_NO_QUALIFYING_DEFICIENCY | 422 |
| ERR_FEE_ALREADY_ASSESSED | 409 |
| ERR_PLAN_UNDER_REVIEW | 409 |
