# Concierge Pre-Sale Advance API — Product Requirements Document

## 1. Introduction

Selling a home often demands renovation capital the homeowner does not have on hand, and the renovation itself must be coordinated, funded, and quality-checked against a listing timeline that the market does not guarantee. This document specifies a pre-sale home improvement advance program in the style of Compass Concierge: the program fronts the cost of value-adding improvements with no upfront homeowner payment, and is repaid out of sale proceeds at closing under fee terms that depend on whether the home sells inside a planned listing window.

The system manages the full lifecycle of a property's engagement with the program. An eligibility assessment weighs the property's estimated value, the expected sale proceeds, and the execution of a listing agreement that carries the required program disclosure. An agent develops the improvement scope, recommending projects expected to lift the sale price, and an advance limit is set against estimated proceeds. Vendors are engaged under capacity-aware scheduling, disbursements are administered against the advance ledger, and workmanship or cost disputes are tracked to resolution. When the home sells — or fails to sell within the listing window — a closing statement computes the repayment: advance principal, a program fee whose rate switches with the outcome, late accrual where applicable, and any vendor holdback. The document is written for the engineer building the API: §2 fixes the wire-level contracts, §3 narrates the business workflows in which every rule lives, §4 summarizes the endpoint surface, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is well-formed but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The platform recognizes six role names, spelled exactly as follows: `PlatformAdmin`, `ListingAgent`, `Homeowner`, `Vendor`, `ProgramUnderwriter`, and `Any`. `PlatformAdmin` is the system administrator for reference data — agents, vendors, vendor capacity windows, and the logical clock. `ListingAgent` is the real-estate agent who creates cases, recommends projects, engages vendors, and records listing events. `Homeowner` is the property owner who approves plans, projects, and change orders, cancels work, and pays closing statements. `Vendor` is the contractor who starts and completes engagements and files change orders. `ProgramUnderwriter` is program staff who decide eligibility, administer disbursements, review and resolve disputes, and finalize closing statements. `Any` denotes shared read access: every GET endpoint accepts any authenticated role.

Role identity is bound to persisted entities for two roles. When `X-User-Role` is `ListingAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on any resource that references an `Agent` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`, and the same comparison rule applies to resources that reference a `Vendor`. When `X-User-Role` is `PlatformAdmin`, `Homeowner`, `ProgramUnderwriter`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` controls the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many records are skipped and defaults to 0. List responses are sorted by `created_at` in ascending order. For list endpoints, the `meta` object of the success envelope carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries the common properties `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. `version` is an integer that is incremented by one on every mutation of the resource, and `updated_at` is refreshed whenever the resource changes.

Resources are nested beneath their parents in the URL hierarchy — projects beneath cases, capacity windows beneath vendors, and so on. The URL path variables used throughout the API are `agentId`, `vendorId`, `caseId`, `projectId`, `engagementId`, `disbursementId`, `changeOrderId`, `disputeId`, and `statementId`, each naming the resource at its segment. Nested resource paths are validated left to right: each path segment's identifier must resolve to an existing resource, and each child must actually belong to the parent named in the path. A failure at any point — a missing parent, a missing child, or a child that belongs to a different parent — is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. Money, Precision, and Rounding

All monetary amounts in the system are integer cents; no fractional cents exist anywhere. Wherever a fee line is produced by multiplying a principal by a rate, the result is rounded half-up to a whole cent, and when a fee is composed of several lines each line is rounded half-up individually before the lines are summed. Wherever a cap is produced by multiplying proceeds by a rate, the result is floored down to a whole cent. Vendor quality is tracked in integer basis points on a scale from 0 to 10000.

### 2.6. The Program Clock

The platform runs on a logical clock rather than wall-clock time. At server startup the logical clock reads 2026-09-01T00:00:00Z. An admin-only test-driving capability sets the logical clock to a supplied `current_utc` instant and returns the resulting `{ current_utc }` reading; only `PlatformAdmin` may invoke it, and it answers with HTTP 200. Whether a vendor engagement finishes on time, whether the listing window has elapsed, and every other temporal judgment in this document are evaluated against this logical clock.

### 2.7. Optimistic Concurrency Control on Case-Mutating Writes

Two write operations require the client to state which version of the case it observed before deciding to write. Approving an improvement plan and approving a disbursement each require a non-optional request field, `expected_case_version`, carrying the client's last observed `version` of the target `ConciergeCase`. If the value does not match the case's current `version` — because another writer has advanced the case since the client last read it, for example by approving a project, approving a change order, or approving a different disbursement, each of which bumps the case version through the advance-total cascade — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a case state it has not observed. Endpoints not named here do not take a version field.

### 2.8. Validation Order and Error Selection

When several checks could reject the same request, the server evaluates them in a fixed order and reports the first failure. Request authentication comes first — a missing or malformed user context yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is examined. Role permission comes second, yielding `ERR_FORBIDDEN_FOR_ROLE`. Resource existence comes third: any identifier that does not resolve yields `ERR_NOT_FOUND`. State appropriateness comes fourth: a resource in the wrong state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409). Fifth, homeowner-initiated cancellation and withdrawal actions are blocked on a `FROZEN` case with `ERR_CASE_FROZEN` (HTTP 409). Sixth, creating a vendor engagement requires the referenced project to be approved, failing with `ERR_PROJECT_NOT_APPROVED` (HTTP 409). Seventh, starting an engagement enforces vendor capacity coverage, failing with `ERR_VENDOR_CAPACITY_EXCEEDED` (HTTP 409). Eighth, advance-limit headroom is enforced on disbursement approval and change-order approval, failing with `ERR_ADVANCE_LIMIT_EXCEEDED` (HTTP 409). Ninth, releasing a disbursement is blocked by an active dispute on the same engagement with `ERR_DISPUTE_ACTIVE` (HTTP 409). Tenth, listing events must respect their required sequence, failing with `ERR_LISTING_EVENT_ORDER` (HTTP 409). Eleventh, an unsold closing requires the listing window to have elapsed, failing with `ERR_LISTING_WINDOW_NOT_ELAPSED` (HTTP 409). Twelfth and last, finalizing a closing statement requires every dispute on the case to be terminal, failing with `ERR_DISPUTE_NOT_TERMINAL` (HTTP 409). Independently of this ordering, a structurally malformed request body, a negative or zero amount where a positive one is required, or an unrecognized enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Case Posture as a Cross-Cutting Gate

Every case carries a derived `posture`, one of `OPEN`, `RESTRICTED`, or `FROZEN`, recomputed whenever a dispute is opened, moved into review, resolved, or withdrawn, and whenever the market-risk indicator on the case's latest listing event changes. When any dispute on the case is in `OPEN` or `IN_REVIEW` and the market-risk indicator `market_risk_flag` is true, the posture is `FROZEN`. When any dispute on the case is in `OPEN` or `IN_REVIEW` but the market-risk indicator is not true, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`. A `FROZEN` posture blocks the homeowner-initiated actions of cancelling the case, cancelling a project, cancelling an engagement, and withdrawing a dispute; each is rejected with `ERR_CASE_FROZEN`. Approving the improvement plan requires the posture to be `OPEN`.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Agents, Vendors, and Capacity Windows

Before any case can move, the platform's reference data must exist. A `PlatformAdmin` registers each listing agent with a `display_name`, a state real-estate `license_number`, and a `brokerage`. Vendors are likewise registered by a `PlatformAdmin` with a `legal_name` and a `trade`, where the trade is exactly one of `GENERAL`, `ELECTRIC`, `PLUMBING`, `HVAC`, `PAINT`, or `LANDSCAPE`. A newly created vendor starts with a spotless record: its `quality_score_bp` is initialized to 10000 and its `on_time_streak` to 0. The vendor list endpoint accepts an optional `trade` query parameter to filter by trade.

A vendor's availability is expressed through capacity windows. A `PlatformAdmin` creates a `VendorCapacityWindow` for a vendor by supplying `window_start`, `window_end`, and `capacity_crew_days`, the number of crew-days the vendor can field in that window. The window covers a half-open interval: `window_start` is inclusive and `window_end` is exclusive. A new window starts with `reserved_crew_days` at 0 and `status` of `OPEN`; a window's status is one of `OPEN`, `FULL`, or `CANCELLED`.

### 3.2. Case Intake and Eligibility Underwriting

A `ListingAgent` opens a `ConciergeCase` by submitting the property's `address_line`, the `estimated_property_value_cents` (the current appraised or agent-estimated market value before improvements), and the `expected_sale_proceeds_cents` (the gross expected sale price minus seller closing costs), together with the listing-agreement attestations `listing_agreement_signed` and `listing_agreement_disclosure_ack`, each of which defaults to false when not supplied. The create payload may optionally carry `homeowner_contribution_cents`, an upfront homeowner co-pay that defaults to 0, and `listing_window_days`, the number of days from first listing to the no-sale penalty trigger, which defaults to 180. It may also optionally seed `advance_total_cents`; when omitted, the case begins with no approved or disbursed advances, so the running total is zero. A new case enters `ELIGIBILITY_REVIEW`, and the system derives its `upfront_payment_track` from the contribution: a `homeowner_contribution_cents` greater than zero places the case on the `CONTRIBUTION` track, while a zero contribution places it on the `NO_UPFRONT` track. Cases can be listed with optional filters `status`, `limit`, and `offset`.

Eligibility is decided by a `ProgramUnderwriter`. Approval requires all four of the following: the `estimated_property_value_cents` is greater than zero; the `expected_sale_proceeds_cents` exceeds the `estimated_property_value_cents` multiplied by 1.10, the program's minimum equity ratio; `listing_agreement_signed` is true; and `listing_agreement_disclosure_ack` is true, confirming the listing agreement carries the program disclosure clause. If any of these fails, the approval is rejected with `ERR_ELIGIBILITY_FAILED` (HTTP 409). On approval the case advances from `ELIGIBILITY_REVIEW` to `SCOPE_PLANNING` and its `advance_limit_cents` is computed: the hard cap on total program advances is the `expected_sale_proceeds_cents` multiplied by 0.15, floored down to a whole cent — and if the `homeowner_contribution_cents` is greater than zero, the cap is additionally clamped to no more than the `expected_sale_proceeds_cents` minus the `estimated_property_value_cents`, taking the smaller of the two figures. A `ProgramUnderwriter` may instead reject eligibility, which moves the case from `ELIGIBILITY_REVIEW` directly to `CANCELLED` with no further effect.

### 3.3. Shaping the Improvement Plan

During `SCOPE_PLANNING`, the agent builds the improvement scope as a set of `ImprovementProject` children of the case. Creating a project takes a `title` (a short label such as "Kitchen refresh"), a `recommended_by_agent` flag recording whether the listing agent recommended the project, an `expected_sale_price_lift_cents` estimate of the sale-price lift the project should produce, and an `estimated_cost_cents` used for advance-limit headroom checks; the project is born in `DRAFT` and belongs to the case through its `concierge_case_id`. The agent then proposes a project, moving it from `DRAFT` to `PROPOSED`; proposing is only valid while the case itself is in `SCOPE_PLANNING`, and is otherwise rejected with `ERR_INVALID_STATE` (HTTP 409).

The homeowner approves each proposed project. Project approval from `PROPOSED` to `APPROVED` requires the case to be in `SCOPE_PLANNING` and requires headroom: the case's `advance_total_cents` plus the project's `estimated_cost_cents` must not exceed the case's `advance_limit_cents`, or the approval fails with `ERR_ADVANCE_LIMIT_EXCEEDED` (HTTP 409). On approval the project's `approved_cost_cents` is locked to its `estimated_cost_cents`, the locked amount is added to the case's `advance_total_cents`, and the case's `version` is incremented by 1. A homeowner may cancel a project while it is in `DRAFT` or `PROPOSED`, moving it to `CANCELLED`; as a homeowner-initiated action this is blocked on a `FROZEN` case with `ERR_CASE_FROZEN`.

Once the scope is set, the homeowner approves the plan as a whole, moving the case from `SCOPE_PLANNING` to `PLAN_APPROVED`. Three conditions gate this transition, and they interact with the concurrency contract of §2.7. At least one project must be in `APPROVED` status — otherwise the request is rejected with `ERR_NO_APPROVED_PROJECTS` (HTTP 409). The sum of `approved_cost_cents` across the `APPROVED` projects must not exceed the case's `advance_limit_cents`. And the case `posture` must be `OPEN`. The request must carry `expected_case_version` matching the case's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the case's `listing_price_target_cents` is recomputed as the `estimated_property_value_cents` plus the sum of the `expected_sale_price_lift_cents` of every `APPROVED` project, and the case's `version` is incremented by 1.

### 3.4. Engaging Vendors and Managing Capacity

With the plan approved, the `ListingAgent` engages vendors by creating a `VendorEngagement`, supplying the `improvement_project_id` it belongs to, the `vendor_id` of the contractor, the `agreed_price_cents` contract price, and the scheduled `start_date` and `end_date`, where `end_date` is treated as inclusive for scheduling purposes. Creation requires the referenced project to be in `APPROVED` status; engaging against a project in any other state is rejected with `ERR_PROJECT_NOT_APPROVED`. A new engagement is born `SCHEDULED`, and when a project's first engagement becomes `SCHEDULED` the project itself advances automatically from `APPROVED` to `SCHEDULED`. Each engagement also carries a computed `completion_deadline`, which is its `end_date` plus 7 days, the program's late-completion grace period. Engagements can be listed with the optional filters `improvement_project_id` and `vendor_id`, and can also be read back per vendor or per project.

The vendor starts the work, transitioning the engagement from `SCHEDULED` to `IN_WORK`. Two conditions guard the start. The parent project must be in `APPROVED`, `SCHEDULED`, or `IN_WORK`. And the vendor must have an `OPEN` capacity window covering the engagement: the window covers the half-open interval from `window_start` inclusive to `window_end` exclusive, an engagement overlaps a window for capacity purposes when the engagement's `start_date` falls strictly before the window's `window_end` and the engagement's `end_date` falls strictly after the window's `window_start` — note that `end_date` is exclusive for capacity purposes even though the `completion_deadline` is computed from it — and the window's `reserved_crew_days` plus the engagement's `required_crew_days` (the crew-days the engagement needs across its scheduled span) must not exceed the window's `capacity_crew_days`. A start that cannot find such a window is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`. On a successful start, the engagement's `required_crew_days` are added to the matching window's `reserved_crew_days`. The first engagement to enter `IN_WORK` moves its project from `SCHEDULED` to `IN_WORK`, and the first engagement across the case to enter `IN_WORK` moves the case from `FUNDED` to `IN_PROGRESS`.

When the vendor finishes, completing the engagement is judged against the logical clock. If the current clock reading is at or before the `completion_deadline`, the engagement moves from `IN_WORK` to `COMPLETE_ON_TIME`: the vendor's `on_time_streak` grows by 1, and when the engagement completes on time with no dispute attached to it, the vendor's `quality_score_bp` rises by 50 basis points, capped at 10000. If the current clock reading is strictly after the `completion_deadline`, the engagement instead moves to `COMPLETE_LATE`: the vendor's `on_time_streak` resets to 0 and its `quality_score_bp` drops by 200 basis points, never below 0. When every non-`CANCELLED` engagement of a project has reached `COMPLETE_ON_TIME` or `COMPLETE_LATE`, the project advances automatically from `IN_WORK` to `COMPLETE`.

A homeowner may cancel an engagement while it is `SCHEDULED`, moving it to `CANCELLED`, provided no disbursement for that engagement is in `RELEASED` status — cancelling an engagement with released funds is rejected with `ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT` (HTTP 409) — and provided the case is not `FROZEN`, which would surface `ERR_CASE_FROZEN`. Cancelling an engagement releases the reserved crew-days on the matching capacity window. An engagement in `IN_WORK` cannot be cancelled through this path; instead, a dispute referencing it moves it to `DISPUTED`, as described in §3.6.

### 3.5. Funding the Work: Disbursements and Change Orders

Money reaches vendors through the `Disbursement` ledger. A `ProgramUnderwriter` creates a disbursement by naming the `concierge_case_id`, the `improvement_project_id`, the `vendor_engagement_id`, the `amount_cents` gross amount to be paid to the vendor, and a `kind` of exactly `DEPOSIT`, `PROGRESS`, `FINAL`, or `CHANGE_ORDER`. The new disbursement enters `REQUESTED` and is assigned a `sequence_in_case`, a monotone counter within the case that serves as a stable tie-breaker. Disbursements can be listed with the optional filters `concierge_case_id` and `improvement_project_id`, and per case.

Approving a disbursement — moving it from `REQUESTED` to `APPROVED` — is a concurrency-guarded write: the request must carry `expected_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. Two further conditions apply. The case's `advance_total_cents` plus the disbursement's `amount_cents` must not exceed the `advance_limit_cents`, failing with `ERR_ADVANCE_LIMIT_EXCEEDED`. And the referenced vendor engagement must be in `SCHEDULED` or `IN_WORK`, failing with `ERR_INVALID_STATE`. On approval the `amount_cents` is added to the case's `advance_total_cents` and the case's `version` is incremented by 1. The very first disbursement to move from `REQUESTED` to `APPROVED` on a case automatically advances the case from `PLAN_APPROVED` to `FUNDED`.

Releasing a disbursement moves it from `APPROVED` to `RELEASED` and pays the vendor. Release requires the engagement to be in `IN_WORK`, `COMPLETE_ON_TIME`, or `COMPLETE_LATE`, and requires that no dispute on that engagement is in `OPEN` or `IN_REVIEW` — an active dispute blocks the release with `ERR_DISPUTE_ACTIVE`. A `ProgramUnderwriter` may also void a disbursement. Voiding from `REQUESTED` simply moves it to `VOIDED`. Voiding from `APPROVED` moves it to `VOIDED` and reverses the ledger: the disbursement's `amount_cents` is subtracted from the case's `advance_total_cents`, so the advance ledger is conserved across the void path. `RELEASED` and `VOIDED` are terminal.

Cost growth mid-project is handled through change orders. A `Vendor` files a `ChangeOrder` with the `improvement_project_id`, the `vendor_engagement_id`, a signed `delta_cents` (a positive value denotes an overrun), and a `reason` of exactly `SCOPE_CREEP`, `HIDDEN_DAMAGE`, `MATERIAL_PRICE`, `CODE_UPGRADE`, or `OTHER`; the order enters `PENDING`, and orders can be listed with the optional filter `improvement_project_id` or per project. The homeowner approves or rejects. Approval from `PENDING` to `APPROVED` requires the project to be in `SCHEDULED` or `IN_WORK`, and requires headroom: the case's `advance_total_cents` plus the `delta_cents` must not exceed the `advance_limit_cents`, failing with `ERR_ADVANCE_LIMIT_EXCEEDED`. On approval the project's `cost_overrun_cents` is recomputed — take the total of the `delta_cents` across the project's `APPROVED` change orders, raise that total to zero if it is negative, then subtract the project's `approved_cost_cents` — the `delta_cents` is added to the case's `advance_total_cents`, and the case's `version` is incremented by 1. Rejection moves the order from `PENDING` to `REJECTED` with no side effects. `APPROVED` and `REJECTED` are terminal.

### 3.6. Disputes, Quality Accountability, and Readiness to List

Workmanship complaints and cost-overrun disagreements are raised as `Dispute` records. Either the `Homeowner` or the `Vendor` may file one, supplying the `concierge_case_id`, the `improvement_project_id`, the `vendor_engagement_id`, a `dispute_kind` of exactly `WORKMANSHIP`, `COST_OVERRUN`, or `SCHEDULE_DELAY`, and the `claimed_amount_cents` the filer wants held back or refunded. A dispute is born `OPEN`. Its creation recomputes the case's `posture`, and if the engagement it references is currently `IN_WORK`, that engagement is automatically moved to `DISPUTED`. Disputes can be listed with the optional filters `concierge_case_id` and `vendor_engagement_id`, and read back per case, per project, or per engagement.

A `ProgramUnderwriter` moves a dispute from `OPEN` to `IN_REVIEW`, which again recomputes the case `posture` — a case with any open or in-review dispute is at least `RESTRICTED`. Resolution moves a dispute from `IN_REVIEW` to one of two terminal outcomes chosen by the underwriter's `resolution` input: `RESOLVED_VENDOR_FAULT` or `RESOLVED_HOMEOWNER_FAULT`. A vendor-fault resolution additionally cuts the responsible vendor's `quality_score_bp` by 500 basis points, never below 0. Every resolution recomputes the case `posture`, and if the referenced engagement was `DISPUTED`, it returns to `IN_WORK`. The homeowner may instead withdraw a dispute while it is still `OPEN`, moving it to `WITHDRAWN` — a homeowner-initiated action blocked on a `FROZEN` case with `ERR_CASE_FROZEN` — which likewise recomputes the posture and returns a `DISPUTED` engagement to `IN_WORK`.

Disputes gate the surrounding workflow. A disbursement cannot be released while its engagement carries an `OPEN` or `IN_REVIEW` dispute (§3.5). A project cannot be verified while a dispute on that project is `OPEN` or `IN_REVIEW`: verification, performed by the `ListingAgent`, moves a project from `COMPLETE` to `VERIFIED` only when no such dispute exists. When every project on a case has reached `VERIFIED` or `CANCELLED` and no dispute on the case is `OPEN` or `IN_REVIEW`, the case advances automatically from `IN_PROGRESS` to `READY_TO_LIST`. `VERIFIED` and `CANCELLED` are terminal for projects; `RESOLVED_VENDOR_FAULT`, `RESOLVED_HOMEOWNER_FAULT`, and `WITHDRAWN` are terminal for disputes; `COMPLETE_ON_TIME`, `COMPLETE_LATE`, `CANCELLED`, and `DISPUTED` are terminal for engagements.

### 3.7. Listing, Market Events, and the Path to Closing

Once a case is `READY_TO_LIST`, the `ListingAgent` records the property's market life as a sequence of `ListingEvent` records on the case, each carrying an `event_kind`, an `event_at` timestamp, an optional `price_cents`, and an optional `market_risk_flag` that defaults to false and marks a material deterioration of market conditions from the improvement plan baseline. The `event_kind` is exactly one of `LISTED`, `PRICE_REDUCED`, `OFFER_ACCEPTED`, `CLOSED_SOLD`, `CLOSED_UNSOLD`, or `DELISTED`. A `price_cents` is required for `LISTED`, `PRICE_REDUCED`, `OFFER_ACCEPTED`, and `CLOSED_SOLD`. Listing events must respect a monotonic sequence — `LISTED` before `OFFER_ACCEPTED` before `CLOSED_SOLD` — and an out-of-order event is rejected with `ERR_LISTING_EVENT_ORDER`.

Recording the first `LISTED` event moves the case from `READY_TO_LIST` to `LISTED` and stamps the case's `listed_at` with the event's `event_at`; only one `LISTED` event may exist for a case, and a second attempt is rejected with `ERR_DUPLICATE_LISTED_EVENT` (HTTP 409). `PRICE_REDUCED` and `DELISTED` events are recorded without driving a case transition. An `OFFER_ACCEPTED` event moves the case from `LISTED` to `UNDER_CONTRACT`. A `CLOSED_SOLD` event moves the case from `UNDER_CONTRACT` to `CLOSED_SOLD`, stamps `closed_at` with the event's `event_at`, and creates the case's `ClosingStatement` in `DRAFT` with its payoff basis computed. A `CLOSED_UNSOLD` event moves the case from `LISTED` to `CLOSED_UNSOLD`, but only once the listing window has elapsed: the number of days between the case's `listed_at` and the event's `event_at` must be at least `listing_window_days`, failing otherwise with `ERR_LISTING_WINDOW_NOT_ELAPSED`; it likewise stamps `closed_at` and creates a `DRAFT` closing statement whose payoff basis is `NOT_LISTED_WITHIN_WINDOW`. `CLOSED_SOLD`, `CLOSED_UNSOLD`, and `CANCELLED` are the terminal states of a case.

A homeowner may cancel the case outright from `SCOPE_PLANNING` or from `LISTED`. Cancellation requires the case `posture` to be anything other than `FROZEN`, failing with `ERR_CASE_FROZEN`; cancelling from `LISTED` additionally requires that no disbursement is in `RELEASED` status without being covered by a closing statement. On cancellation every project not already in a terminal state is moved to `CANCELLED`, and every engagement not already in a terminal state is moved to `CANCELLED`.

### 3.8. The Closing Statement: Payoff Basis, Fees, and Settlement

Closing the case — sold or unsold — spawns a `ClosingStatement` in `DRAFT`. The statement carries the `gross_sale_price_cents`, the actual sale price at closing, which is null when the home did not sell. Its `payoff_basis` is one of `LISTED_WITHIN_WINDOW`, `NOT_LISTED_WITHIN_WINDOW`, `SOLD_WITHIN_WINDOW`, or `SOLD_AFTER_WINDOW`: a sold case is `SOLD_WITHIN_WINDOW` when the number of days between `listed_at` and the closing event is fewer than `listing_window_days`, and `SOLD_AFTER_WINDOW` once the window has elapsed; an unsold case, which can only close after the window has elapsed, is `NOT_LISTED_WITHIN_WINDOW`. Its `advance_repayment_cents` is the total advance principal being repaid: the sum of the `amount_cents` of every disbursement on the case in `RELEASED` status.

Finalization by a `ProgramUnderwriter` moves the statement from `DRAFT` to `FINALIZED` and computes the money. Every dispute on the case must be in a terminal status — finalizing while any dispute is still open or in review is rejected with `ERR_DISPUTE_NOT_TERMINAL`. The computation follows a pinned evaluation order, because the fee depends on the payoff basis, the payoff basis depends on the listing events and clock, and the principal depends on the ledger: first `advance_repayment_cents` is summed from released disbursements; second the `payoff_basis` is determined; third `program_fee_cents` is computed; fourth `late_fee_cents`; fifth `vendor_holdback_cents`; and sixth the `net_repayment_cents`.

The program fee has two variants. Under variant A — a `payoff_basis` of `SOLD_WITHIN_WINDOW` or `LISTED_WITHIN_WINDOW`, meaning the home listed and sold within the listing window — the `program_fee_cents` is the `advance_repayment_cents` multiplied by 0.03, rounded half-up to a whole cent: a single 3 percent fee on the advance principal. Under variant B — a `payoff_basis` of `NOT_LISTED_WITHIN_WINDOW` or `SOLD_AFTER_WINDOW`, meaning the home did not sell within the listing window — the `program_fee_cents` is the sum of two lines, each rounded half-up to a whole cent before summing: the `advance_repayment_cents` multiplied by 0.01, a reduced 1 percent base fee, plus the `advance_repayment_cents` multiplied by 0.005 per month late, a 0.5 percent monthly accrual. The number of months late is computed by taking the days between `listed_at` and `closed_at`, subtracting `listing_window_days`, dividing by 30, and rounding up to a whole month. The `late_fee_cents` applies only under variant B: it is the `advance_repayment_cents` multiplied by 0.002 per month late, rounded half-up to a whole cent, with the months-late figure computed the same way; under variant A the `late_fee_cents` is 0. The `vendor_holdback_cents` is the sum of the `claimed_amount_cents` across the case's disputes in `IN_REVIEW` status — disputes merely `OPEN` are excluded; only in-review disputes trigger holdback. Finally the `net_repayment_cents` is the `advance_repayment_cents` plus the `program_fee_cents` plus the `late_fee_cents` minus the `vendor_holdback_cents`.

Settlement closes the loop. The homeowner records payment, moving a `FINALIZED` statement to `PAID`, which requires the case to be `CLOSED_SOLD` or `CLOSED_UNSOLD`. Alternatively, a `ProgramUnderwriter` may waive the fees, moving a `FINALIZED` statement to `WAIVED`, but only when the case is `CLOSED_UNSOLD` and the most recent listing event recorded before `closed_at` carries a `market_risk_flag` of true — the market moved against the homeowner through no fault of the program. Waiving adjusts the `net_repayment_cents` to the `advance_repayment_cents` only, so that just the advance principal is owed. `PAID` and `WAIVED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under the API prefix implied by the paths below, with the clock endpoint standing outside it. Creating a new resource returns HTTP 201; operations that modify an existing resource, trigger state transitions, or read data return HTTP 200. All failures return the 4xx status paired with the error identifier in §5. Request payloads, response payloads, and side effects for each operation are as narrated in §3; this table is a summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-09-01T00:00:00Z) | PlatformAdmin |
| POST | /concierge/agents | Create an Agent | PlatformAdmin |
| GET | /concierge/agents/{agentId} | Get an Agent | Any |
| POST | /concierge/vendors | Create a Vendor | PlatformAdmin |
| GET | /concierge/vendors/{vendorId} | Get a Vendor | Any |
| GET | /concierge/vendors | List Vendors (optional `trade` filter) | Any |
| POST | /concierge/vendors/{vendorId}/capacity-windows | Create a VendorCapacityWindow | PlatformAdmin |
| GET | /concierge/vendors/{vendorId}/capacity-windows | List capacity windows for a vendor | Any |
| GET | /concierge/vendors/{vendorId}/engagements | List engagements for a vendor | Any |
| POST | /concierge/cases | Create a ConciergeCase | ListingAgent |
| GET | /concierge/cases/{caseId} | Get a ConciergeCase | Any |
| GET | /concierge/cases | List ConciergeCases (optional `status`, `limit`, `offset`) | Any |
| POST | /concierge/cases/{caseId}/eligibility/approve | Approve case eligibility | ProgramUnderwriter |
| POST | /concierge/cases/{caseId}/eligibility/reject | Reject case eligibility | ProgramUnderwriter |
| POST | /concierge/cases/{caseId}/plan/approve | Approve improvement plan (requires `expected_case_version`) | Homeowner |
| POST | /concierge/cases/{caseId}/cancel | Cancel a ConciergeCase | Homeowner |
| POST | /concierge/cases/{caseId}/projects | Create an ImprovementProject | ListingAgent |
| GET | /concierge/cases/{caseId}/projects/{projectId} | Get an ImprovementProject | Any |
| GET | /concierge/cases/{caseId}/projects | List projects for a case | Any |
| POST | /concierge/cases/{caseId}/projects/{projectId}/propose | Propose a project | ListingAgent |
| POST | /concierge/cases/{caseId}/projects/{projectId}/approve | Approve a project | Homeowner |
| POST | /concierge/cases/{caseId}/projects/{projectId}/verify | Verify a completed project | ListingAgent |
| POST | /concierge/cases/{caseId}/projects/{projectId}/cancel | Cancel a project | Homeowner |
| POST | /concierge/cases/{caseId}/listing-events | Record a listing event | ListingAgent |
| GET | /concierge/cases/{caseId}/listing-events | List listing events for a case | Any |
| GET | /concierge/cases/{caseId}/closing-statement | Get the closing statement for a case | Any |
| GET | /concierge/cases/{caseId}/disbursements | List disbursements for a case | Any |
| GET | /concierge/cases/{caseId}/disputes | List disputes for a case | Any |
| POST | /concierge/engagements | Create a VendorEngagement | ListingAgent |
| GET | /concierge/engagements/{engagementId} | Get a VendorEngagement | Any |
| GET | /concierge/engagements | List VendorEngagements (optional `improvement_project_id`, `vendor_id`) | Any |
| POST | /concierge/engagements/{engagementId}/start | Start a vendor engagement | Vendor |
| POST | /concierge/engagements/{engagementId}/complete | Complete a vendor engagement | Vendor |
| POST | /concierge/engagements/{engagementId}/cancel | Cancel a vendor engagement | Homeowner |
| GET | /concierge/engagements/{engagementId}/disputes | List disputes for an engagement | Any |
| POST | /concierge/disbursements | Create a Disbursement | ProgramUnderwriter |
| GET | /concierge/disbursements/{disbursementId} | Get a Disbursement | Any |
| GET | /concierge/disbursements | List Disbursements (optional `concierge_case_id`, `improvement_project_id`) | Any |
| POST | /concierge/disbursements/{disbursementId}/approve | Approve a disbursement (requires `expected_case_version`) | ProgramUnderwriter |
| POST | /concierge/disbursements/{disbursementId}/release | Release a disbursement to vendor | ProgramUnderwriter |
| POST | /concierge/disbursements/{disbursementId}/void | Void a disbursement | ProgramUnderwriter |
| POST | /concierge/change-orders | Create a ChangeOrder | Vendor |
| GET | /concierge/change-orders/{changeOrderId} | Get a ChangeOrder | Any |
| GET | /concierge/change-orders | List ChangeOrders (optional `improvement_project_id`) | Any |
| POST | /concierge/change-orders/{changeOrderId}/approve | Approve a change order | Homeowner |
| POST | /concierge/change-orders/{changeOrderId}/reject | Reject a change order | Homeowner |
| POST | /concierge/disputes | Create a Dispute | Homeowner, Vendor |
| GET | /concierge/disputes/{disputeId} | Get a Dispute | Any |
| GET | /concierge/disputes | List Disputes (optional `concierge_case_id`, `vendor_engagement_id`) | Any |
| POST | /concierge/disputes/{disputeId}/review | Move dispute to IN_REVIEW | ProgramUnderwriter |
| POST | /concierge/disputes/{disputeId}/resolve | Resolve a dispute (carries `resolution`) | ProgramUnderwriter |
| POST | /concierge/disputes/{disputeId}/withdraw | Withdraw a dispute | Homeowner |
| GET | /concierge/projects/{projectId}/engagements | List engagements for a project | Any |
| GET | /concierge/projects/{projectId}/change-orders | List change orders for a project | Any |
| GET | /concierge/projects/{projectId}/disputes | List disputes for a project | Any |
| POST | /concierge/closing-statements/{statementId}/finalize | Finalize a closing statement | ProgramUnderwriter |
| POST | /concierge/closing-statements/{statementId}/pay | Record payment of closing statement | Homeowner |
| POST | /concierge/closing-statements/{statementId}/waive | Waive fees on a closing statement | ProgramUnderwriter |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status code. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CASE_FROZEN | 409 |
| ERR_PROJECT_NOT_APPROVED | 409 |
| ERR_ADVANCE_LIMIT_EXCEEDED | 409 |
| ERR_DISPUTE_ACTIVE | 409 |
| ERR_VENDOR_CAPACITY_EXCEEDED | 409 |
| ERR_LISTING_EVENT_ORDER | 409 |
| ERR_LISTING_WINDOW_NOT_ELAPSED | 409 |
| ERR_DISPUTE_NOT_TERMINAL | 409 |
| ERR_DUPLICATE_LISTED_EVENT | 409 |
| ERR_NO_APPROVED_PROJECTS | 409 |
| ERR_ELIGIBILITY_FAILED | 409 |
| ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT | 409 |
