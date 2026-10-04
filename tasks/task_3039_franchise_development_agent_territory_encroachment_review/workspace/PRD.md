# Franchise Development Agent Territory & Encroachment Review API — Product Requirements Document

## 1. Introduction

Franchise brands that grow through a development agent model face a recurring governance problem: a third-party firm sells and supports franchise locations inside an exclusive territory, but the brand must retain control over where new stores go, how existing operators are protected from encroachment, and whether the agent itself is performing. This document specifies the API for a system that administers exactly that model for a quick-service sandwich franchise.

The platform governs the full commercial lifecycle: registration of territories, development agents, and franchisees; new-store site applications carrying a quantified impact study on nearby existing stores; a franchisee protest process with mediation and escalation for alleged encroachment; transfer and resale approvals gated on buyer training completion; remodel mandates with financing options and downtime charges; a compliance inspection pipeline whose outcomes can put a store on probation or on the path to termination; national promotion votes with per-store funding allocation and funding disputes; and periodic fee statements that split royalties between the development agent and the franchisor under two calculation variants.

All workflows run against a logical clock that the platform operator drives explicitly, so time-dependent behavior — protest windows, mediation deadlines, voting windows, lazy expirations — is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, identifying the operational capacity in which they act. A request missing either header, or carrying an empty value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes six roles, spelled exactly: `PlatformAdmin`, `FranchisorOps`, `DevelopmentAgent`, `Franchisee`, `Mediator`, and `Inspector`. Attempting an operation outside the caller's role, or failing an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The identity semantics of `X-User-ID` differ by role. When `X-User-Role` is `DevelopmentAgent`, `X-User-ID` is the `id` of the acting DevelopmentAgent record; ownership checks on any resource that references a territory compare the territory's `assigned_agent_id` to `X-User-ID`. When `X-User-Role` is `Franchisee`, `X-User-ID` is the `id` of the acting Franchisee record; ownership checks compare the relevant store's, protest's, or dispute's franchisee foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `FranchisorOps`, `Mediator`, or `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `mediator_ref` on a Protest or `inspector_ref` on an Inspection where the workflow writes it — but it does not compare such opaque identifiers to any entity's `id`, except where segregation-of-duties rules explicitly require it (see §2.7).

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Certain list endpoints accept additional filters — the territory list accepts optional `status` and `assigned_agent_id`, and the protest list accepts optional `protesting_franchisee_id` and `status` — applied before pagination.

### 2.4. Common Resource Properties and Mutation Semantics

Every business resource carries a standard system-managed property set. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. `version` is an integer that increments by exactly 1 on every mutation of the resource and underpins optimistic concurrency control.

State changes triggered as side effects of an operation on another resource — for example, a store entering `PROBATION` because an inspection was finalized, or a site application entering `SUSPENDED` because its territory entered reassignment — are mutations of the affected resource and therefore increment that resource's `version` and refresh its `updated_at`, exactly as a direct write would. Where a workflow section states that a specific transition "increments version by 1", that statement is reinforcement of this universal rule, not an exception.

### 2.5. Optimistic Concurrency Control on Capacity-Consuming Creates

Two creation endpoints are guarded by optimistic concurrency control against a parent resource, because the create consumes capacity or supersedes a pending commercial arrangement that another writer may already have changed.

Creating a site application requires the request to carry `expected_territory_version` — a non-optional field holding the client's last observed `version` of the target territory. If the territory's current `version` has advanced since (for example because another writer created an application against it or reassigned it), the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a transfer request requires the request to carry `expected_store_version` — a non-optional field holding the client's last observed `version` of the target store. A mismatch with the store's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named in this subsection do not take a version field.

### 2.6. The Logical Clock and Lazy Time-Driven Transitions

All time-dependent logic — protest windows, mediation deadlines, voting windows, promotion campaign windows, enrollment expiry, remodel overdue detection, store age, fee statement periods — reads a single server-side logical clock. Before any operator call, the logical clock reads exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; after each such call, lazy transitions are re-evaluated on subsequent reads.

Two lazy transitions are applied on read rather than by a background job: a TrainingEnrollment whose `expires_on` has passed reads as `EXPIRED`, and a RemodelMandate still in `ISSUED` or `SCHEDULED` whose `due_by` has passed reads as `OVERDUE`. The lazy expiry of an enrollment carries the same cascade as an explicit failure: any of that franchisee's transfer requests sitting in `BUYER_TRAINING` revert to `PENDING`.

### 2.7. Segregation of Duties

The platform separates recording authority from disposition authority in two places. On inspections, the `Inspector` who records findings must be the operator whose `X-User-ID` equals the inspection's `inspector_ref`, and that same operator is barred from finalizing the inspection — finalization is performed by `FranchisorOps`, and the finalizer must not be the operator recorded as `inspector_ref`. On protests, only the operator recorded as `mediator_ref` may record the mediation outcome, and the mediator may not resolve the protest; direct or post-escalation resolution is a `FranchisorOps` act.

### 2.8. Validation Order and Nested Path Resolution

Every request is validated against a fixed priority ladder, and the first failing rung determines the error returned. In order: (1) authentication headers; (2) role and entity-backed ownership authorization; (3) path-template identifier existence, validated left-to-right so the first non-resolving id produces its `404`; (4) request-body foreign-key existence, validated in the endpoint's declared input order; (5) state validity — the target must be in a from-state of the requested transition, terminal states reject everything, and OCC `expected_*_version` must match; (6) the buyer-training gate on transfer advancement and approval; (7) business referential rules (store status, territory assignment, participation); (8) temporal windows; (9) uniqueness constraints; (10) interval, capacity, and quorum constraints; (11) fiscal rules; and (12) request shape — field presence, enum membership, numeric ranges, and whole-week statement periods — which is checked last, so a structurally malformed request to an otherwise-failing operation reports the earlier failure. Existence failures return the resource-specific 404 error id (for example `ERR_TERRITORY_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_FRANCHISEE_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_SITE_APPLICATION_NOT_FOUND`, `ERR_IMPACT_STUDY_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_MANDATE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or `ERR_STATEMENT_NOT_FOUND`). State failures return `ERR_INVALID_STATE` (HTTP 409); stale-version failures return `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Monetary Values and Rounding Discipline

All monetary amounts are integers of cents wherever the API stores a final figure, and all percentage rates are expressed as decimal fractions (a royalty of eight percent is written `0.08`). Two precision regimes apply. Fee splits, transfer fees, promotion funding shares, and downtime charges are computed to whole cents — 0 decimal places, round half up. Impact projections, inspection scores, and performance scores are computed to 2 decimal places, round half up. Where a calculation's rounding order is pinned — per-store lines rounded then summed, per-category scores rounded before summation — the governing workflow section states that order explicitly, and the pinned order is normative.

### 2.10. Fee Conservation Invariant

Every fee statement honors a conservation invariant at all times: the development agent's share plus the franchisor's share equals the gross fees, exactly. Rounding remainders are always allocated to the franchisor's share, never to the agent's, so `da_share_cents + franchisor_share_cents == gross_fees_cents` holds at generation, at finalization, and is re-verified at settlement.

## 3. Business Logic & Workflows

### 3.1. Territories, Development Agents, and the Reassignment Cascade

A `FranchisorOps` operator establishes the commercial map by creating territories — each with a unique `code`, a human-readable `region`, a `royalty_rate_pct` applied to weekly store sales, and a `development_quota_stores` floor expressing the minimum number of stores the development agent must keep open. A new territory is `UNASSIGNED`, its `assigned_agent_id` is null, and its `open_store_count` — the count of its stores in `OPEN`, `CLOSED_FOR_REMODEL`, `PROBATION`, or `TERMINATION_PENDING` status — starts at zero. Agents are registered with their `legal_name`, `contact_email`, `agreement_start`, and `agreement_end`; a new agent enters `ACTIVE` with `underperformance_strikes` at zero. Franchisees register with `legal_name` and `contact_email` and begin as `PROSPECT`; a franchisee flips to `ACTIVE` automatically the first time a store opens under their ownership or is transferred to them.

Assigning an agent to a territory — the request carries the `agent_id` of the target agent — moves the territory `UNASSIGNED → ASSIGNED`, sets `assigned_agent_id`, and increments the territory's `version` by 1; the target agent must be `ACTIVE`, otherwise the assignment is refused with `ERR_AGENT_NOT_ACTIVE`. An agent's `performance_score` is recomputed on every read of the agent record: across the agent's assigned territories in any status, the approval rate is the share of non-`DRAFT` site applications that reached `APPROVED` or later (zero if there are none), the inspection pass rate is the share of finalized inspections with outcome `PASS` among all finalized inspections (zero if none), and the remodel on-time rate is the share of completed mandates whose downtime stayed within the financing allowance among all completed mandates (zero if none). The score is one hundred times the weighted sum — thirty percent approval rate, forty percent inspection pass rate, thirty percent remodel on-time rate — rounded half up to 2 decimal places. A score strictly below 60.00 marks the agent eligible for an underperformance strike; a score of exactly 60.00 does not.

Recording an underperformance strike against an `ACTIVE` agent increments `underperformance_strikes` by one and moves the agent to `UNDER_REVIEW`; clearing the review returns the agent to `ACTIVE`. Recording a strike against an agent already `UNDER_REVIEW` — the second strike within the trailing 24 months — increments the count to two and flips the agent to `UNDERPERFORMING`, which detonates a three-hop cascade: every territory assigned to that agent in `ASSIGNED` status moves to `REASSIGNMENT_PENDING`; every site application of such a territory sitting in `SUBMITTED` or `IMPACT_REVIEW` moves to `SUSPENDED`; and every `PROVISIONAL` impact study of a suspended application is voided. Terminating an agent requires the agent to be `UNDERPERFORMING` and, additionally, that no territory assigned to it remains in `ASSIGNED` status — the franchisor must first move each territory through reassignment.

Reassignment can also be initiated directly on a territory whose assigned agent is `UNDERPERFORMING` (any other agent status is refused with `ERR_AGENT_NOT_ACTIVE`), moving the territory `ASSIGNED → REASSIGNMENT_PENDING` with the same application-suspension and study-voiding cascade, and incrementing the territory's `version` by 1. Assigning a new agent to a `REASSIGNMENT_PENDING` territory requires the new agent to be `ACTIVE` and to differ from the previously assigned agent; the move back to `ASSIGNED` replaces `assigned_agent_id`, resumes the territory's `SUSPENDED` applications by returning them to `SUBMITTED` — the re-entry point of the review pipeline, so a fresh impact study must be commissioned — and increments the territory's `version` by 1.

### 3.2. Site Applications and Impact Studies

A development agent originates a new location by creating a site application carrying `territory_id`, `applicant_franchisee_id`, `proposed_address`, `proposed_lat`, `proposed_lng`, and `proposed_open_date`, plus the OCC guard `expected_territory_version` described in §2.5. The application is born `DRAFT` with `revision_count` zero and `store_id` null, and the create itself increments the territory's `version` by 1 — which is exactly why a second agent's concurrent create, observed against the older version, fails stale.

Submitting a `DRAFT` application moves it to `SUBMITTED`; the caller must be the territory's assigned agent, and the territory must be `ASSIGNED` — submission against an `UNASSIGNED` or `REASSIGNMENT_PENDING` territory is refused with `ERR_TERRITORY_UNASSIGNED`. Once submitted, `FranchisorOps` commissions the impact study by supplying a `radius_miles`, which moves the application `SUBMITTED → IMPACT_REVIEW` and creates the study in `PROVISIONAL` status with its `site_application_id` back-reference. Only one study may be live for an application: if a study in `PROVISIONAL` or `FINAL` status already exists, creation is rejected with `ERR_INVALID_STATE`.

The study quantifies projected sales diversion onto existing stores. The input set is every store of the application's territory in `OPEN`, `CLOSED_FOR_REMODEL`, or `PROBATION` status whose distance from the proposed site is within the radius. Distance is Manhattan degrees, pinned: the absolute difference of the store's `geo_lat` and the proposed latitude plus the absolute difference of `geo_lng` and the proposed longitude, and a store enters the input set when that sum is strictly less than the radius in miles multiplied by 0.0145 degrees per mile. Each in-radius store is assigned an impact bucket by distance: a store closer than 0.01 degrees diverts twelve percent of its weekly sales; at 0.01 degrees or more but closer than 0.02 degrees, seven percent; at 0.02 degrees or more but closer than 0.04 degrees, three percent; at 0.04 degrees or more the store is excluded entirely. `affected_store_count` is the number of stores receiving a nonzero bucket. For the provisional variant, each affected store's line is its `estimated_weekly_sales_cents` multiplied by its bucket percentage, rounded half up to 2 decimal places, and `provisional_impact_cents` is the sum of those rounded lines. Finalizing the study moves it `PROVISIONAL → FINAL` and recomputes every line against the store's `actual_avg_weekly_sales_cents` — the trailing thirteen-week actual average — producing `final_impact_cents`; provisional and final figures differ whenever estimates diverge from actuals.

From `IMPACT_REVIEW`, `FranchisorOps` may request revisions, supplying `revision_notes`, moving the application to `REVISION_REQUESTED`. The agent's resubmission returns it to `SUBMITTED`, increments `revision_count` by one, and voids the existing study — the study moves to `VOID` and must be redone from scratch. Approval requires the application's study to be in `FINAL` status, otherwise `ERR_IMPACT_STUDY_NOT_FINAL`; approval stamps `approved_on` with the logical clock, creates a `PIPELINE` store owned by the applicant franchisee at the proposed address and coordinates with `source_site_application_id` pointing back to the application, sets the application's `store_id`, and recomputes the territory's `open_store_count`. Rejection, which carries a `reason`, moves the application to terminal `REJECTED` and voids its study. The agent may withdraw any application in `DRAFT`, `SUBMITTED`, `IMPACT_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`; withdrawal voids any `PROVISIONAL` or `FINAL` study, and if the application was `APPROVED`, its `PIPELINE` store is terminated and the territory's `open_store_count` recomputed. `REJECTED` and `WITHDRAWN` are terminal.

### 3.3. Encroachment Protests and Mediation

An existing operator who believes a newly approved site encroaches may file a protest, naming the `site_application_id`, their own `protesting_store_id`, and free-text `grounds`. The protesting store must be `OPEN` and in the same territory as the application — otherwise `ERR_STORE_NOT_OPEN` — and the filing is only valid within thirty days of the application's `approved_on`; a filing after that window is refused with `ERR_PROTEST_WINDOW_EXPIRED`. The system derives `protesting_franchisee_id` from the protesting store's owner and requires it to equal the caller. Only one non-terminal protest may exist per protesting store and application pair; a second live filing is refused with `ERR_PROTEST_ALREADY_FILED`. An accepted filing stamps `filed_on` from the logical clock, creates the protest in `FILED` status, and moves the application `APPROVED → PROTESTED`.

`FranchisorOps` begins review (`FILED → UNDER_REVIEW`) and then chooses between two dispositions. Direct resolution supplies a `resolution` of `UPHELD` or `REJECTED`. Alternatively, sending the protest to mediation supplies the `mediator_ref` and a `mediation_deadline`, moving it `UNDER_REVIEW → MEDIATION` and recording both values. The assigned mediator — and only that operator — records the mediation `outcome`: `UPHELD` or `REJECTED` resolve the protest in that direction, while `FAILED` moves it to `MEDIATION_FAILED`. Any mediation outcome recorded after the `mediation_deadline` is refused with `ERR_MEDIATION_DEADLINE_PASSED`; an outcome on or before the deadline is timely. After a failed mediation, the protesting franchisee — who must own the protesting store — may escalate, moving the protest `MEDIATION_FAILED → ESCALATED`, whereupon `FranchisorOps` resolves it by arbitration with the same `resolution` field.

Both resolution values carry cross-entity consequences. A protest resolved `UPHELD` — whether directly, by mediation, or after escalation — lands in terminal `RESOLVED_UPHELD` and moves the application `PROTESTED → REJECTED`, voids its study, terminates the `PIPELINE` store created at approval, and recomputes the territory's `open_store_count`. A protest resolved `REJECTED` lands in terminal `RESOLVED_REJECTED` and returns the application `PROTESTED → APPROVED`, but only once no other non-terminal protest remains on the application; multiple concurrent protests against one application are possible across different protesting stores, and the last one to resolve determines the timing of the return.

### 3.4. Transfers, Resales, and the Buyer Training Gate

A franchisee sells a store by creating a transfer request naming the `store_id`, the `buyer_franchisee_id`, the agreed `sale_price_cents`, and the OCC guard `expected_store_version` (§2.5). The seller of record, `seller_franchisee_id`, is captured from the store's current owner at creation. The transfer fee is computed once, at creation, and frozen thereafter — later edits to the sale price are impossible. The fee tiers on the sale price: a sale under 25,000,000 cents pays a flat 500,000 cents; a sale of at least 25,000,000 but under 75,000,000 cents pays two percent of the price, rounded half up to whole cents; a sale of 75,000,000 cents or more pays one and a half percent, rounded half up to whole cents. If the store is at least ten whole years old — measured from its `opened_on` to the logical clock — the fee is then multiplied by 0.90, again rounded half up to whole cents, yielding `transfer_fee_cents`.

The request lifecycle then hinges on the buyer's training. Advancing a `PENDING` request to `BUYER_TRAINING` requires the buyer to hold a `TRANSFER_BUYER` training enrollment in `ENROLLED` or `COMPLETED` status, failing which the advance is refused with `ERR_BUYER_TRAINING_INCOMPLETE`; if the buyer's enrollment is already `COMPLETED`, the request advances through to `PENDING_APPROVAL` in the same call. While a request waits in `BUYER_TRAINING`, the buyer's enrollment outcome drives it: the enrollment flipping to `COMPLETED` moves the request to `PENDING_APPROVAL`, while the enrollment flipping to `FAILED` — or lazily expiring — reverts the request to `PENDING`, and the buyer must obtain a fresh enrollment before advancing again.

Approving a `PENDING_APPROVAL` request requires the buyer's enrollment to be `COMPLETED` (otherwise `ERR_BUYER_TRAINING_INCOMPLETE`) and the store to be outside `TERMINATION_PENDING` and `TERMINATED` (otherwise `ERR_STORE_NOT_TRANSFERABLE`). Completing an approved request applies the same store-status guard, flips the store's `franchisee_id` to the buyer, recognizes `transfer_fee_cents`, and increments the store's `version` by 1. Rejection, carrying a `reason`, is terminal; the seller may also cancel any request in `PENDING`, `BUYER_TRAINING`, or `PENDING_APPROVAL`, moving it to terminal `CANCELLED`. Independently of any manual action, a store entering `PROBATION` or `TERMINATION_PENDING` cancels every one of its requests in those same three statuses — the sale cannot proceed over a compliance event.

Training enrollments themselves are created by `FranchisorOps` with `franchisee_id`, `program_code`, and `expires_on`, entering `ENROLLED` with `score` and `completed_on` null. Recording a result supplies the `score`: a score of at least 80 completes the enrollment (stamping `completed_on`), provided the logical clock has not passed `expires_on`; a score below 80 fails it. Both outcomes cascade to the franchisee's `BUYER_TRAINING` transfer requests as described above.

### 3.5. Remodel Mandates, Closure Windows, and Downtime Charges

`FranchisorOps` issues a remodel mandate against a store with a `due_by` deadline, a `financing_option` of `SELF_FINANCED`, `DA_LOAN`, or `FRANCHISOR_DEFERRAL`, and an `estimated_cost_cents`; the mandate is born `ISSUED` with its closure window unset. Choosing `DA_LOAN` financing requires the store's territory's assigned agent to be `ACTIVE` — otherwise the create fails with `ERR_AGENT_NOT_ACTIVE`. A mandate still `ISSUED` or `SCHEDULED` whose `due_by` passes reads as `OVERDUE` (§2.6).

Scheduling is the development agent's job and is the most heavily guarded transition in the system. The caller must be the assigned agent of the store's territory. The store must be `OPEN` — otherwise `ERR_STORE_NOT_OPEN`. The proposed half-open closure window `closure_start` to `closure_end` (end exclusive) must not intersect any other `SCHEDULED` or `IN_PROGRESS` closure window of the same store — otherwise `ERR_CLOSURE_WINDOW_OVERLAP`. And the new `closure_start` must fall at least seven days after every prior `closure_end` of the same store, giving the store a recovery buffer between closures — otherwise `ERR_CLOSURE_BUFFER_VIOLATION`. A successful schedule records the window, computes `downtime_days` as the whole days in the half-open interval, and moves the mandate to `SCHEDULED`. An `OVERDUE` mandate may be rescheduled under exactly the same window and buffer rules, replacing the closure window.

Inside the closure window — the logical clock at or after `closure_start` and before `closure_end` — the store's owning franchisee begins the remodel, moving the mandate `SCHEDULED → IN_PROGRESS` and the store `OPEN → CLOSED_FOR_REMODEL`, incrementing the store's `version` by 1. Completing the remodel requires the same ownership, returns the store to `OPEN` (again incrementing its version), moves the mandate to `COMPLETED`, and computes the downtime charge. The allowance in whole days depends on the financing option: twenty-one days for `SELF_FINANCED`, twenty-eight for `DA_LOAN`, fourteen for `FRANCHISOR_DEFERRAL`. Days beyond the allowance are charged at 150,000 cents each, so `downtime_charge_cents` is the overage days multiplied by 150,000; a downtime exactly equal to the allowance is within allowance and charges zero. `FranchisorOps` may waive a mandate in `ISSUED`, `SCHEDULED`, or `OVERDUE`; and when a store is terminated, every one of its mandates in those three statuses is waived automatically. `COMPLETED` and `WAIVED` are terminal.

### 3.6. Compliance Inspections and the Road to Termination

The compliance pipeline starts when `FranchisorOps` schedules an inspection for a store with a `scheduled_on` date and an `inspector_ref`; the inspection is born `SCHEDULED` with all findings fields null. The assigned inspector — per §2.7, the operator whose `X-User-ID` equals `inspector_ref`, and no one else — records the findings: `food_safety_score`, `cleanliness_score`, and `operations_score`, each between 0 and 100 with two decimal places, plus the integer `critical_violations`. Recording findings moves the inspection `SCHEDULED → CONDUCTED` and computes `final_score`: each category score is first multiplied by its weight — 0.40 for food safety, 0.30 for cleanliness, 0.30 for operations — and each weighted category is rounded half up to 2 decimal places; the three rounded figures are summed; two and a half points per critical violation are subtracted; the result is rounded half up to 2 decimal places and floored at zero. This per-category-rounding-before-summation order is pinned. Findings cannot be recorded against a `TERMINATED` store.

Finalization is reserved to `FranchisorOps`, and the finalizer must not be the inspector of record. Finalizing derives the `outcome`: `FAIL_CRITICAL` when `critical_violations` is three or more; otherwise `PASS` when `final_score` is at least 60.00; otherwise `FAIL`. The outcome then cascades to the store. A non-critical `FAIL` against an `OPEN` store moves it to `PROBATION` and increments its `consecutive_failed_inspections` — and, as covered in §3.4, cancels its in-flight transfer requests. A `PASS` finalized against a store on `PROBATION` returns it to `OPEN` and resets `consecutive_failed_inspections` to zero. A `FAIL_CRITICAL`, or a `FAIL` against a store whose `consecutive_failed_inspections` already stood at one or more — the second consecutive failure — moves the store from `OPEN` or `PROBATION` to `TERMINATION_PENDING`: the failure count increments, in-flight transfers cancel, and every still-`SCHEDULED` inspection of the store is voided. Each of these cascades increments the store's `version` by 1.

A store in `TERMINATION_PENDING` is terminated by `FranchisorOps`, which recomputes the territory's `open_store_count`, waives the store's open mandates (§3.5), and increments the store's `version` by 1. `TERMINATED` is terminal and rejects every further transition with `ERR_INVALID_STATE`.

A store's life begins in one of two ways. Directly registered pre-existing stores — created with `store_number`, `territory_id`, `franchisee_id`, `address`, `geo_lat`, `geo_lng`, `opened_on`, `estimated_weekly_sales_cents`, and `actual_avg_weekly_sales_cents`, and a null `source_site_application_id` — enter `OPEN` immediately, flipping their `PROSPECT` franchisee to `ACTIVE` and recomputing the territory's `open_store_count`. Stores born of an approved site application instead sit in `PIPELINE` until `FranchisorOps` opens them, the move `PIPELINE → OPEN` incrementing the store's `version` by 1 and recomputing `open_store_count` again.

### 3.7. National Promotions: Voting, Funding, and Disputes

A national promotion is created with a `name`, a voting window from `voting_open` (inclusive) to `voting_close` (exclusive), a campaign window from `active_start` (inclusive) to `active_end` (exclusive), and a `base_cost_per_store_cents`; it enters `PROPOSED` with all tallies at zero. Voting may be opened only while the logical clock is within the voting window, moving the promotion `PROPOSED → VOTING`.

Each store's operator casts one ballot — `FOR`, `AGAINST`, or `ABSTAIN` — by supplying the `store_id` and `ballot`. The store must be `OPEN` or `CLOSED_FOR_REMODEL` (otherwise `ERR_STORE_NOT_OPEN`), the caller must own the store, the cast must fall inside the voting window (otherwise `ERR_VOTING_CLOSED`), and at most one live ballot exists per store and promotion: a second non-retracted ballot is refused with `ERR_ALREADY_VOTED`. A ballot may be retracted while voting remains open — the vote's `retracted` flag flips to true, and a retracted ballot never counts again. The promotion's `votes_for`, `votes_against`, and `votes_abstain` are live tallies of non-retracted ballots, recomputed on every cast and retract.

Closing the vote is permitted once the logical clock reaches `voting_close`. The `eligible_voter_count` is the number of stores in `OPEN` or `CLOSED_FOR_REMODEL` status at that moment. Quorum has two legs, both inclusive at the boundary: the `FOR` tally multiplied by three must be at least twice the eligible voter count — exactly two-thirds approval passes — and the total ballots cast, doubled, must be at least the eligible voter count — half turnout. When quorum holds, the promotion moves `VOTING → APPROVED` and the funding allocation computes in pinned order: `participating_store_count` is the number of stores holding a live `FOR` ballot; the subsidy tier keys on that count — fifteen percent when at least twelve stores participate, ten percent for six through eleven, five percent otherwise; `store_share_cents` is the `base_cost_per_store_cents` reduced by the subsidy, rounded half up to whole cents; and `total_pool_cents` is the participating count multiplied by the per-store share. When quorum fails, closing the vote without more is refused with `ERR_QUORUM_NOT_MET`; the operator may instead pass `force_reject` set to true, moving the promotion to terminal `REJECTED`.

Activation requires the logical clock to have reached `active_start`, and enforces a per-territory capacity rule: for every territory containing a participating store, fewer than two other `ACTIVE` promotions may overlap the campaign window — a third concurrent campaign in the same territory is refused with `ERR_PROMOTION_OVERLAP_EXCEEDED`. Once `ACTIVE`, a participating store's operator may raise a funding dispute by naming the `promotion_id`, their `store_id`, the `disputed_amount_cents`, and a free-text `reason`. The promotion must be `ACTIVE` — otherwise `ERR_PROMOTION_NOT_ACTIVE` — the store must be a participating one (it holds a live `FOR` ballot), and the disputed amount must equal the promotion's computed `store_share_cents` exactly, otherwise `ERR_DISPUTE_AMOUNT_MISMATCH`. Disputes are born `OPEN`; `FranchisorOps` resolves each with a `resolution` of `DA_ABSORBS`, `FRANCHISEE_PAYS`, or `FRANCHISOR_ABSORBS`, moving it to the matching resolved status. A promotion may close once the logical clock reaches `active_end` and no dispute of the promotion remains `OPEN` — an open dispute blocks closure with `ERR_INVALID_STATE` — moving it to terminal `CLOSED`.

### 3.8. Fee Statements and the Development Agent Split

Periodically, `FranchisorOps` generates a fee statement for an agent–territory pair by supplying `development_agent_id`, `territory_id`, `period_start` (inclusive), and `period_end` (exclusive). The territory must be assigned to that agent — otherwise `ERR_TERRITORY_UNASSIGNED` — the period must run a whole number of weeks with `period_end` after `period_start` — otherwise `ERR_INVALID_REQUEST` — and no non-settled statement may already overlap the requested period for the same agent and territory, otherwise `ERR_FISCAL_PERIOD_OVERLAP`. The statement is born `PROVISIONAL` with `variant` set to `PROVISIONAL_ESTIMATE`.

The two variants compute gross fees differently. The provisional estimate is forward-looking: it sums over the territory's stores in `OPEN` or `PIPELINE` status, each store contributing its `estimated_weekly_sales_cents` multiplied by the territory's `royalty_rate_pct` multiplied by the number of whole weeks in the period, rounded half up to whole cents. Finalizing the statement moves it to `FINALIZED`, flips `variant` to `FINAL_RECONCILIATION`, and recomputes gross fees chronologically against actuals: only `OPEN` stores contribute, each on its `actual_avg_weekly_sales_cents` under the same rate-and-weeks product and rounding; the same period therefore yields a different gross whenever estimates diverge from actuals. Under either variant, the agent's share percentage tiers on the territory's store count — counting stores in `PIPELINE`, `OPEN`, `CLOSED_FOR_REMODEL`, or `PROBATION`: forty-five percent when the count is at least five, forty percent otherwise. `da_share_cents` is the gross multiplied by that percentage, rounded half up to whole cents, and `franchisor_share_cents` is the gross minus the agent's share, so the rounding remainder always lands with the franchisor and the conservation invariant of §2.10 holds. Settling a finalized statement re-verifies the invariant and moves the statement to terminal `SETTLED`.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; all other successful operations — state transitions, reads, and list retrievals — return HTTP 200. Failed operations return the HTTP status paired with their `error_id` in §5. The table below is a navigational summary; request payloads, side effects, and preconditions are specified by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/territories` | Create a territory (UNASSIGNED) | FranchisorOps |
| GET | `/territories/{id}` | Get a territory | FranchisorOps, DevelopmentAgent |
| GET | `/territories` | List territories (filters: `status`, `assigned_agent_id`) | FranchisorOps, DevelopmentAgent |
| POST | `/territories/{id}/assign-agent` | Assign or reassign a development agent | FranchisorOps |
| POST | `/territories/{id}/initiate-reassignment` | Begin reassignment for an underperforming agent | FranchisorOps |
| GET | `/territories/{id}/stores` | List stores in a territory | FranchisorOps, DevelopmentAgent |
| GET | `/territories/{id}/site-applications` | List site applications in a territory | FranchisorOps, DevelopmentAgent |
| GET | `/territories/{id}/fee-statements` | List fee statements of a territory | FranchisorOps, DevelopmentAgent |
| POST | `/development-agents` | Register a development agent (ACTIVE) | FranchisorOps |
| GET | `/development-agents/{id}` | Get an agent (performance score computed on read) | FranchisorOps, DevelopmentAgent |
| POST | `/development-agents/{id}/flag-underperformance` | Record an underperformance strike; second strike cascades | FranchisorOps |
| POST | `/development-agents/{id}/clear-review` | Clear UNDER_REVIEW back to ACTIVE | FranchisorOps |
| POST | `/development-agents/{id}/terminate` | Terminate an underperforming agent | FranchisorOps |
| GET | `/development-agents/{id}/territories` | List territories assigned to an agent | FranchisorOps, DevelopmentAgent |
| GET | `/development-agents/{id}/fee-statements` | List fee statements of an agent | FranchisorOps, DevelopmentAgent |
| POST | `/franchisees` | Register a franchisee (PROSPECT) | FranchisorOps |
| GET | `/franchisees/{id}` | Get a franchisee | FranchisorOps, Franchisee |
| GET | `/franchisees/{id}/stores` | List stores owned by a franchisee | FranchisorOps, Franchisee |
| GET | `/franchisees/{id}/training-enrollments` | List training enrollments of a franchisee | FranchisorOps, Franchisee |
| GET | `/franchisees/{id}/transfer-requests` | List transfer requests involving a franchisee | FranchisorOps, Franchisee |
| GET | `/franchisees/{id}/site-applications` | List site applications filed for a franchisee | FranchisorOps, Franchisee, DevelopmentAgent |
| GET | `/franchisees/{id}/promotion-votes` | List promotion votes cast by a franchisee | FranchisorOps, Franchisee |
| POST | `/stores` | Register a pre-existing operating store (OPEN) | FranchisorOps |
| GET | `/stores/{id}` | Get a store | FranchisorOps, DevelopmentAgent, Franchisee |
| POST | `/stores/{id}/open` | Open a PIPELINE store | FranchisorOps |
| POST | `/stores/{id}/terminate` | Terminate a TERMINATION_PENDING store | FranchisorOps |
| GET | `/stores/{id}/site-applications` | List site applications that produced this store | FranchisorOps, DevelopmentAgent |
| GET | `/stores/{id}/protests` | List protests filed by this store | FranchisorOps, DevelopmentAgent, Franchisee |
| GET | `/stores/{id}/transfer-requests` | List transfer requests of this store | FranchisorOps, Franchisee |
| GET | `/stores/{id}/remodel-mandates` | List remodel mandates of this store | FranchisorOps, DevelopmentAgent, Franchisee |
| GET | `/stores/{id}/inspections` | List inspections of this store | FranchisorOps, Inspector |
| GET | `/stores/{id}/promotion-votes` | List promotion votes of this store | FranchisorOps, Franchisee |
| GET | `/stores/{id}/funding-disputes` | List funding disputes of this store | FranchisorOps, Franchisee |
| POST | `/site-applications` | Create a site application (DRAFT); OCC-guarded on the territory | DevelopmentAgent |
| GET | `/site-applications/{id}` | Get a site application | FranchisorOps, DevelopmentAgent |
| POST | `/site-applications/{id}/submit` | Submit or resubmit after a revision request | DevelopmentAgent |
| POST | `/site-applications/{id}/request-revision` | Request revisions from IMPACT_REVIEW | FranchisorOps |
| POST | `/site-applications/{id}/approve` | Approve (requires FINAL impact study); creates PIPELINE store | FranchisorOps |
| POST | `/site-applications/{id}/reject` | Reject a site application | FranchisorOps |
| POST | `/site-applications/{id}/withdraw` | Withdraw a non-terminal application | DevelopmentAgent |
| GET | `/site-applications/{id}/stores` | List stores produced by this application (length 0 or 1) | FranchisorOps, DevelopmentAgent |
| GET | `/site-applications/{id}/protests` | List protests against an application | FranchisorOps, DevelopmentAgent, Franchisee |
| POST | `/site-applications/{id}/impact-studies` | Create the impact study (SUBMITTED → IMPACT_REVIEW) | FranchisorOps |
| GET | `/site-applications/{id}/impact-studies` | List impact studies of an application | FranchisorOps, DevelopmentAgent |
| GET | `/impact-studies/{id}` | Get an impact study | FranchisorOps, DevelopmentAgent |
| POST | `/impact-studies/{id}/finalize` | Finalize a study (final variant recompute) | FranchisorOps |
| POST | `/protests` | File an encroachment protest against an APPROVED application | Franchisee |
| GET | `/protests/{id}` | Get a protest | FranchisorOps, DevelopmentAgent, Franchisee, Mediator |
| GET | `/protests` | List protests (filters: `protesting_franchisee_id`, `status`) | FranchisorOps, Mediator |
| POST | `/protests/{id}/begin-review` | Move protest FILED → UNDER_REVIEW | FranchisorOps |
| POST | `/protests/{id}/send-to-mediation` | Send protest to mediation (sets mediator and deadline) | FranchisorOps |
| POST | `/protests/{id}/record-mediation-outcome` | Mediator records outcome (assigned mediator only) | Mediator |
| POST | `/protests/{id}/resolve` | Franchisor resolves directly or after escalation | FranchisorOps |
| POST | `/protests/{id}/escalate` | Escalate a failed mediation | Franchisee |
| POST | `/transfer-requests` | Create a transfer/resale request; OCC-guarded on the store | Franchisee |
| GET | `/transfer-requests/{id}` | Get a transfer request | FranchisorOps, Franchisee |
| POST | `/transfer-requests/{id}/advance-to-training` | Advance PENDING → BUYER_TRAINING | FranchisorOps |
| POST | `/transfer-requests/{id}/approve` | Approve PENDING_APPROVAL (buyer training COMPLETED) | FranchisorOps |
| POST | `/transfer-requests/{id}/reject` | Reject a transfer request | FranchisorOps |
| POST | `/transfer-requests/{id}/complete` | Complete an approved transfer; ownership flips | FranchisorOps |
| POST | `/transfer-requests/{id}/cancel` | Seller cancels a non-terminal transfer request | Franchisee |
| POST | `/training-enrollments` | Enroll a franchisee in a training program | FranchisorOps |
| GET | `/training-enrollments/{id}` | Get an enrollment (lazy EXPIRED applied on read) | FranchisorOps, Franchisee |
| POST | `/training-enrollments/{id}/record-result` | Record training result; score of at least 80 completes | FranchisorOps |
| POST | `/remodel-mandates` | Issue a remodel mandate | FranchisorOps |
| GET | `/remodel-mandates/{id}` | Get a remodel mandate (lazy OVERDUE applied on read) | FranchisorOps, DevelopmentAgent, Franchisee |
| POST | `/remodel-mandates/{id}/schedule` | Schedule the closure window (ISSUED or OVERDUE) | DevelopmentAgent |
| POST | `/remodel-mandates/{id}/begin` | Begin the remodel inside the closure window | Franchisee |
| POST | `/remodel-mandates/{id}/complete` | Complete the remodel; downtime charge computed | Franchisee |
| POST | `/remodel-mandates/{id}/waive` | Waive an open mandate | FranchisorOps |
| POST | `/inspections` | Schedule an inspection | FranchisorOps |
| GET | `/inspections/{id}` | Get an inspection | FranchisorOps, Inspector |
| POST | `/inspections/{id}/record-findings` | Inspector records category scores (assigned inspector only) | Inspector |
| POST | `/inspections/{id}/finalize` | Franchisor finalizes (not the inspector); outcome cascades | FranchisorOps |
| POST | `/promotions` | Create a national promotion (PROPOSED) | FranchisorOps |
| GET | `/promotions/{id}` | Get a promotion | FranchisorOps, DevelopmentAgent, Franchisee |
| POST | `/promotions/{id}/open-voting` | Open the voting window | FranchisorOps |
| POST | `/promotions/{id}/close-voting` | Close voting; quorum met → APPROVED with funding, else REJECTED | FranchisorOps |
| POST | `/promotions/{id}/activate` | Activate an approved promotion (overlap capacity enforced) | FranchisorOps |
| POST | `/promotions/{id}/close` | Close an active promotion (no OPEN disputes) | FranchisorOps |
| GET | `/promotions/{id}/votes` | List votes of a promotion | FranchisorOps, DevelopmentAgent, Franchisee |
| GET | `/promotions/{id}/funding-disputes` | List funding disputes of a promotion | FranchisorOps, DevelopmentAgent, Franchisee |
| POST | `/promotions/{id}/votes` | Cast a ballot for a store | Franchisee |
| GET | `/promotion-votes/{id}` | Get a vote | FranchisorOps, Franchisee |
| POST | `/promotion-votes/{id}/retract` | Retract a live ballot while voting is open | Franchisee |
| POST | `/funding-disputes` | Dispute the funding share charged to a participating store | Franchisee |
| GET | `/funding-disputes/{id}` | Get a funding dispute | FranchisorOps, Franchisee |
| POST | `/funding-disputes/{id}/resolve` | Resolve a dispute: DA absorbs, franchisee pays, or franchisor absorbs | FranchisorOps |
| POST | `/fee-statements/generate` | Generate a provisional fee statement for an agent, territory, and period | FranchisorOps |
| GET | `/fee-statements/{id}` | Get a fee statement | FranchisorOps, DevelopmentAgent |
| POST | `/fee-statements/{id}/finalize` | Finalize: recompute under the final variant | FranchisorOps |
| POST | `/fee-statements/{id}/settle` | Settle a finalized statement (invariant re-verified) | FranchisorOps |

## 5. Error Code Catalogue

The catalogue below pairs each error identifier with its HTTP status. Trigger conditions are specified in the workflow narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TERRITORY_NOT_FOUND` | 404 |
| `ERR_AGENT_NOT_FOUND` | 404 |
| `ERR_FRANCHISEE_NOT_FOUND` | 404 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_SITE_APPLICATION_NOT_FOUND` | 404 |
| `ERR_IMPACT_STUDY_NOT_FOUND` | 404 |
| `ERR_PROTEST_NOT_FOUND` | 404 |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_MANDATE_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_PROMOTION_NOT_FOUND` | 404 |
| `ERR_VOTE_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AGENT_NOT_ACTIVE` | 422 |
| `ERR_TERRITORY_UNASSIGNED` | 422 |
| `ERR_STORE_NOT_OPEN` | 422 |
| `ERR_STORE_NOT_TRANSFERABLE` | 422 |
| `ERR_BUYER_TRAINING_INCOMPLETE` | 422 |
| `ERR_IMPACT_STUDY_NOT_FINAL` | 422 |
| `ERR_PROTEST_WINDOW_EXPIRED` | 422 |
| `ERR_MEDIATION_DEADLINE_PASSED` | 422 |
| `ERR_VOTING_CLOSED` | 422 |
| `ERR_PROTEST_ALREADY_FILED` | 409 |
| `ERR_ALREADY_VOTED` | 409 |
| `ERR_FISCAL_PERIOD_OVERLAP` | 409 |
| `ERR_CLOSURE_WINDOW_OVERLAP` | 422 |
| `ERR_CLOSURE_BUFFER_VIOLATION` | 422 |
| `ERR_PROMOTION_OVERLAP_EXCEEDED` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_DISPUTE_AMOUNT_MISMATCH` | 422 |
| `ERR_PROMOTION_NOT_ACTIVE` | 422 |
