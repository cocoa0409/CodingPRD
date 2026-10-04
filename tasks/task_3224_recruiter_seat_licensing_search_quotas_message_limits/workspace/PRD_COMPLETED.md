# Recruiter Seats API — Product Requirements Document

## 1. Introduction

Recruiting organisations that license a recruiter platform do not buy seats — they buy a contract. The contract sets the product tier, which in turn determines how many seats can be provisioned, how many candidate searches each seated recruiter may run per month, how many message credits each seat carries, and how wide a single search page may grow. Everything else in the system — seat assignment, search quota ledgers, message credit pools, anti-spam throttling, job posting budget pacing, ATS write-back, talent-insight privacy floors, and renewal true-up — hangs off that contract boundary.

This document specifies the Recruiter Seats API: a multi-root REST surface that governs contract lifecycle, seat licensing, search and messaging quotas, candidate visibility rules, job posting pacing, ATS synchronisation, aggregated talent insights, and renewal / true-up accounting. The audience is the engineer implementing the service. Throughout, we privilege narrative over schema: rules are stated where they apply, identifiers are named where they live, and the request / response contract is left to §4 and the error catalogue in §5.

A few structural notes. Most resources are hierarchical — a seat belongs to a contract; a quota ledger, a credit pool, a search project, a job posting, an ATS integration, and a talent insight report each belong to a contract (or to a seat, which itself belongs to a contract). Candidate profiles are peer entities: recruiters see them through a visibility filter that respects member privacy. Renewal events are first-class objects so that contract-affecting changes (suspension, renewal, seat true-up) carry an audit trail. The platform also exposes a test-driving endpoint that lets an administrator move the server's logical clock forward; that clock drives period rollover, contract renewal windows, message expiry, and posting pacing decisions.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must present two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the caller's operational role. The system recognises five roles, spelled exactly: `ContractAdmin`, `SeatAdmin`, `RecruiterUser`, `AtsService`, and `Auditor`. A missing or unrecognised `X-User-Role` header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorised for the target endpoint (per §4) is rejected with `ERR_ROLE_FORBIDDEN`.

The five roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `RecruiterUser`, `X-User-ID` is the `id` of the acting `Recruiter` entity; ownership checks on any seat-scoped resource compare the seat's `assigned_recruiter_id` to `X-User-ID`, and a seated recruiter can only operate against the seat they currently hold. When `X-User-Role` is `ContractAdmin`, `SeatAdmin`, `AtsService`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by` on a `RenewalEvent` when an `Auditor` proposes one) but does not compare it against any entity's `id`.

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

The success envelope is also used by the candidate-search endpoint (§3.4), whose `data` is an array of candidate profiles; and by the clock endpoint (§3.10), whose `data` is an object carrying `now_iso8601`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must not be negative; a non-integer or out-of-range `limit`/`offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise stated, list endpoints return resources sorted by `created_at` in ascending order (ties broken by creation sequence). Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties

Every primary resource — `RecruiterContract`, `Seat`, `Recruiter`, `QuotaLedger`, `MessageCreditPool`, `Message`, `CandidateProfile`, `SearchProject`, `JobPosting`, `PromotedSlot`, `AtsIntegration`, `AtsSyncRecord`, `TalentInsightReport`, `RenewalEvent` — carries a standard set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version`: an integer that starts at 1 at creation and increments by 1 on every mutation to the resource. This field is the basis for optimistic concurrency control where the API requires it.

All entities in this domain carry these common fields — no entity in this product omits `updated_at` or `version`.

### 2.5. Nested Resource Retrieval

Endpoints whose path contains multiple identifiers — for example a seat addressed under a contract, or a promoted slot addressed under a posting under a contract — are validated left-to-right. The path-parameter names used across the API surface are `contract_id`, `seat_id`, `recruiter_id`, `project_id`, `message_id`, `job_posting_id`, `integration_id` (for ATS integrations), `report_id` (for talent-insight reports), `renewal_event_id`, `record_id` (for ATS sync records), and `candidate_id`. The system resolves each identifier in turn: the parent is located first, then each child within its parent's scope. The request is rejected with `ERR_NOT_FOUND` as soon as any identifier in the chain does not resolve, without inspecting identifiers further to the right. A reference to a child of a non-existent parent always surfaces as "the parent was not found," never as a business-rule failure on the child.

### 2.6. Precision and Monetary Values

Two precisions apply in this product. Counters, quota balances, credit balances, day counts, and derived aggregates are integers. All monetary amounts — `budget_cents`, `daily_cap_cents`, `reserved_cents`, `amount_cents`, `spent_cents`, `proration_credit_cents` — are integer cents; no fractional cents ever appear in stored values or responses. Where a formula requires division (budget pacing, proration), each intermediate step uses integer floor division unless the rule explicitly states round-half-up; the proration credit is rounded half-up to integer cents as its final step.

### 2.7. Optimistic Concurrency Control

Two write endpoints in this API require the caller to attest to the version of a parent resource they last observed, and only those two.

- A seat-assignment request must carry `expected_seat_version`, holding the client's last-observed `version` of the target `Seat`. If the seat's current `version` no longer matches — because another writer has mutated the seat since the client read it — the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A renewal-event creation request must carry `expected_contract_version`, holding the client's last-observed `version` of the parent `RecruiterContract`. A mismatch with the contract's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The canonical case is two auditors proposing true-ups against the same contract; the second proposer's view of `seats_purchased` is stale once the first event is recorded.

Endpoints not named above do not take a version field and perform no OCC check.

### 2.8. Hierarchical Consistency and Cascades

State changes propagate downward so that a parent never claims operational capacity its children no longer have. When a contract is suspended, every seat in `ASSIGNED` status under that contract moves to `SUSPENDED`, and every message on those seats whose `response_status` is `AWAITING` is moved to `EXPIRED` — a three-level cascade from contract through seat to message. When a contract resumes, suspended seats revert to their pre-suspension status. When a contract expires without renewal, every seat under it moves to `REVOKED`, every `assigned_recruiter_id` is cleared, and every recruiter whose `active_seat_id` pointed at one of those seats has it cleared.

Cascades also flow along other edges. Revoking a seat — whether by expiration cascade or by negative true-up — closes every `OPEN` quota ledger and every `OPEN` or `THROTTLED` credit pool attached to that seat, moving them to `CLOSED`. Disabling an ATS integration fails every `QUEUED` sync record under it. Closing, pausing-and-closing, or exhausting a job posting releases every `RESERVED` promoted slot it still holds.

Each cascade step that mutates a resource refreshes that resource's `updated_at` and increments its `version`. The contract-level transitions (activate, suspend, resume, true-up apply, renewal apply) each increment the parent contract's `version` by exactly 1, regardless of how many children moved. The clock-driven transitions to `RENEWAL_PENDING` and to `EXPIRED` (§3.10) likewise each increment the contract's `version` by exactly 1 when they fire.

### 2.9. Product Tier Derived Limits

A `RecruiterContract` carries a `product_tier` that takes one of `RECRUITER_LITE`, `RECRUITER_PRO`, or `RECRUITER_CORP`. The tier fixes three derived, read-only contract quantities:

- `monthly_credit_per_seat`: 30 for `RECRUITER_LITE`, 100 for `RECRUITER_PRO`, 150 for `RECRUITER_CORP`. This is the credit grant each seat's monthly credit pool is initialised with.
- `monthly_search_quota_per_seat`: 100 for `RECRUITER_LITE`, 1000 for `RECRUITER_PRO`, 10000 for `RECRUITER_CORP`. This is the search quota each seat's monthly quota ledger is initialised with.
- `search_result_page_cap`: 40 for `RECRUITER_LITE`, 100 for `RECRUITER_PRO`, 1000 for `RECRUITER_CORP`. This caps the number of candidate profiles returned by a single search invocation on any seat under the contract.

A `seat_cap` of between 1 and 5000 bounds the total number of seats the contract can ever purchase. A `true_up_allowed` boolean (defaulting to `true` when omitted at contract creation) governs whether true-up renewal events may be approved.

### 2.10. Validation Priority

When multiple checks could fail on the same request, the system surfaces the earliest one in this fixed priority order: (1) request authentication — the `X-User-Role` header must be present and one of the five recognised roles, else `ERR_UNAUTHENTICATED`; (2) role authorisation against the endpoint's role list, else `ERR_ROLE_FORBIDDEN`; (2.5) request shape — every required body field present, types matching the endpoint schema, enum values in range, else `ERR_INVALID_REQUEST`; (3) path-parameter existence — every id resolves, else `ERR_NOT_FOUND`; (3.5) OCC version match on the two guarded endpoints, else `ERR_STALE_VERSION`; (4) entity state preconditions for the requested transition, else `ERR_INVALID_STATE`; (4.1) seat consumption state — the seat must be `ASSIGNED` to consume search quota or message credits, else `ERR_INVALID_STATE`; (4.2) recruiter-identity seat ownership when the caller is `RecruiterUser`, else `ERR_ROLE_FORBIDDEN`. Business rules then run in ascending priority: anti-spam throttle (priority 5, `ERR_ANTISPAM_THROTTLED`), candidate visibility (priority 6, `ERR_CANDIDATE_NOT_VISIBLE`), recruiter-already-seated (priority 7, `ERR_RECRUITER_ALREADY_SEATED`), seat-not-available (priority 8, `ERR_SEAT_NOT_AVAILABLE`), manager-active (priority 9, `ERR_MANAGER_INACTIVE`), aggregation floor (priority 10, `ERR_AGGREGATION_FLOOR`), no-credits (priority 11, `ERR_NO_CREDITS_REMAINING`), quota-exhausted (priority 12, `ERR_QUOTA_EXHAUSTED`), pacing-violation (priority 13, `ERR_PACING_VIOLATION`), true-up bounds (priority 14, `ERR_TRUEUP_BOUNDS`), invalid date range (priority 15, `ERR_INVALID_DATE_RANGE`), and uniqueness (priority 16, `ERR_DUPLICATE`). Two refinements pin how this order is realised. On the seat-assignment endpoint the recruiter referenced by `recruiter_id` is resolved as part of step (3) path/body id resolution, so an unresolvable `recruiter_id` surfaces `ERR_NOT_FOUND` before the OCC check at (3.5). And on both the seat-assignment and renewal-event-creation endpoints, the `expected_seat_version` / `expected_contract_version` field is required: omitting it is a shape failure yielding `ERR_INVALID_REQUEST` at step (2.5), not a stale-version failure.

### 2.11. Uniqueness Constraints

The following uniqueness rules are enforced with `ERR_DUPLICATE`: a contract's `contract_number` is unique across the tenant; a recruiter's `email` is unique across the tenant (stored lowercase); a `seat_label` is unique within its parent contract; a `SearchProject` `name` is unique within its parent contract; and the pair of `vendor` and `external_tenant_id` on an `AtsIntegration` is unique within its parent contract. A candidate's `member_id` is also unique tenant-wide.

## 3. Business Logic & Workflows

### 3.1. Contracts: Provisioning, Activation, Suspension, and Renewal Windows

A `ContractAdmin` opens the relationship by creating a `RecruiterContract`. The caller supplies a human-facing `contract_number`, the `product_tier` (one of `RECRUITER_LITE`, `RECRUITER_PRO`, `RECRUITER_CORP`), a `seat_cap`, and optionally `true_up_allowed` (which defaults to `true` when omitted). The contract begins life in `PENDING_ACTIVATION` with `seats_purchased` set to 0, `seats_assigned` at 0, and the tier-derived quantities from §2.9 computed and attached. The `contract_status` enum takes values `PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, `RENEWAL_PENDING`, and `EXPIRED`.

Activation is the moment the contract starts billing periods. The `ContractAdmin` activates a contract by submitting `seats_purchased_initial`. The contract must be in `PENDING_ACTIVATION` and the submitted initial purchase must be at least 1 and no greater than `seat_cap`; any other state or count yields `ERR_INVALID_STATE`. On activation, the server sets `seats_purchased` to the submitted value, mints that many `UNASSIGNED` `Seat` rows (each labelled `SEAT-<sequence>` via the `seat_label` field, unique within the contract), records `current_period_start` as now, sets `current_period_end` to exactly 30 days after start, sets `period_index` to 1, transitions the contract to `ACTIVE`, and bumps the contract's `version`. From this point the contract's monthly cadence is fixed: a period is always 30 days.

While the contract is `ACTIVE`, an `Auditor` may suspend it — but only through the renewal-event machinery described in §3.9. Direct suspension requires that an approved `RenewalEvent` of kind `SUSPENSION` already exist for the contract. On suspension the contract moves from `ACTIVE` to `SUSPENDED`, every `ASSIGNED` seat cascades to `SUSPENDED`, every message still `AWAITING` a response on those seats moves to `EXPIRED`, and the contract's `version` increments. Resume moves the contract from `SUSPENDED` back to `ACTIVE`, returns each `SUSPENDED` seat to its pre-suspension `ASSIGNED` posture, and bumps `version`. Resume requires no precondition beyond the contract being `SUSPENDED`.

As time advances, the contract's lifecycle is also driven by the logical clock (§3.10). When current time reaches or crosses `current_period_end` minus 7 days, an `ACTIVE` contract transitions to `RENEWAL_PENDING`; this is a flag transition only and has no quota or credit effect. If the contract remains in `RENEWAL_PENDING` strictly past `current_period_end` plus 14 days (i.e. `now > current_period_end + 14 days`) without a renewal event being applied, the contract expires: it moves to `EXPIRED`, every seat under it moves to `REVOKED`, every seat's `assigned_recruiter_id` is cleared, and every recruiter whose `active_seat_id` pointed at one of those seats has it cleared. The renewal path from `RENEWAL_PENDING` back to `ACTIVE` is described in §3.9.

The contract exposes several derived counters. `seats_assigned` is always the count of `Seat` rows in `ASSIGNED` status under this contract; it is incremented on seat assignment and decremented on unassignment, recruiter deactivation, and the seat-revocation cascade (it is clamped at zero and never goes negative). `seats_purchased` starts at 0, is set at activation, and thereafter only moves when a true-up is applied. `period_index` starts at 0 at contract creation, becomes 1 at activation, and increments by 1 on each renewal apply. The `current_period_start` and `current_period_end` bracket the active period (both are null before activation); `current_period_end` is exclusive.

### 3.2. Recruiters and Seats: Assignment and Non-Sharing

Recruiters are the humans who hold seats. A `ContractAdmin` onboards a `Recruiter` by supplying `email` (unique tenant-wide, stored lowercase), `full_name`, the `home_contract_id` of the contract under which the recruiter is being onboarded (an unresolvable `home_contract_id` is rejected with `ERR_INVALID_REQUEST`), and optionally a `manager_recruiter_id` referencing another recruiter. When `manager_recruiter_id` is provided, it must reference a recruiter whose `recruiter_status` is `ACTIVE`; otherwise the create is rejected with `ERR_MANAGER_INACTIVE` — this covers both the unknown-id case and the deactivated-manager case. A recruiter's `recruiter_status` starts at `ACTIVE` and may later become `DEACTIVATED`; `active_seat_id` is null until a seat is assigned, and a recruiter holds at most one seat at a time.

A `Seat` is the licence unit. Each seat has a system-minted `seat_label`, a `seat_status` taking values `UNASSIGNED`, `ASSIGNED`, `SUSPENDED`, or `REVOKED`, an `assigned_recruiter_id` that is null when the seat is `UNASSIGNED` or `REVOKED`, an `assignment_started_at` timestamp set on the most recent assign (null if never assigned), an `assignment_audit_count` that increments on every successful assign (an audit counter for compliance), and a `last_period_credit_refresh` recording the `period_index` at which the seat's credit pool was last refreshed (0 before the first refresh).

Assignment is the central seat operation. A `SeatAdmin` assigns a seat by naming the `recruiter_id` and supplying `expected_seat_version` (the OCC guard described in §2.7). The assignment enforces, in order: the parent contract must be `ACTIVE`; the named recruiter must have `recruiter_status` of `ACTIVE` — a recruiter in any other status yields `ERR_INVALID_STATE`; the recruiter must not already hold a seat — if the recruiter's `active_seat_id` is non-null the request is rejected with `ERR_RECRUITER_ALREADY_SEATED`; the target seat's `seat_status` must be `UNASSIGNED` — a seat in any other state is rejected with `ERR_SEAT_NOT_AVAILABLE`; and the seat's `assigned_recruiter_id` must be null. On success the seat moves from `UNASSIGNED` to `ASSIGNED`, `assigned_recruiter_id` is set to the recruiter, `assignment_started_at` is recorded, `assignment_audit_count` increments by 1, the recruiter's `active_seat_id` is set to the seat, the contract's `seats_assigned` increments by 1, and the seat's `version` increments (the recruiter's `version` also increments; the contract's `version` does not). Assignment also creates the seat's period-scoped accounting rows: if no `OPEN` `QuotaLedger` exists for this seat at the current `period_index`, one is created with `search_quota_total` snapshotted from the contract's `monthly_search_quota_per_seat`; if no `OPEN` or `THROTTLED` `MessageCreditPool` exists for this seat at the current `period_index`, one is created with `credits_granted` snapshotted from the contract's `monthly_credit_per_seat`, and the seat's `last_period_credit_refresh` is set to that `period_index` only when a new pool is created.

Unassignment returns the seat to the pool. A `SeatAdmin` may unassign a seat that is `ASSIGNED` provided the parent contract is `ACTIVE`. The recruiter's `active_seat_id` is cleared, the seat's `assigned_recruiter_id` and `assignment_started_at` are cleared, the contract's `seats_assigned` decrements by 1, and the seat moves back to `UNASSIGNED`. Importantly, any `OPEN` quota ledger and any `OPEN` or `THROTTLED` credit pool for the seat at the current period remain in place but become unusable — they cannot be consumed while their owning seat is `UNASSIGNED`.

Individual seat suspension and resume mirror the contract-level cascade at seat scope. A `SeatAdmin` (or the system, as part of a contract suspension) moves a seat from `ASSIGNED` to `SUSPENDED`; every message on the seat whose `response_status` is `AWAITING` moves to `EXPIRED` regardless of its `delivery_status`. A seat in `SUSPENDED` may be resumed to `ASSIGNED` provided the parent contract is `ACTIVE`; the seat's `assigned_recruiter_id` and `assignment_started_at` are preserved across suspension and resume. Both transitions increment the seat's `version`. Seat revocation is system-driven only: expiration cascade and negative true-up are the two paths, and both close the seat's ledgers and pools (see §3.3). Negative true-up never revokes an `ASSIGNED` seat — only `UNASSIGNED` ones; the expiration cascade revokes both.

Recruiter offboarding is a soft delete. Deactivating a recruiter sets `recruiter_status` to `DEACTIVATED` (the row remains); deactivating an already-`DEACTIVATED` recruiter is rejected with `ERR_INVALID_STATE`. If the recruiter holds a seat, that seat is unassigned in the same operation: the seat moves to `UNASSIGNED`, the recruiter's `active_seat_id` is cleared, and the contract's `seats_assigned` decrements by 1. Recruiter listings exclude soft-deleted recruiters by default; a `recruiter_status` filter exposes them when needed. The recruiter list also accepts `home_contract_id`, `manager_recruiter_id`, and `active_seat_id` filters.

### 3.3. Search Quotas and Message Credits: Period-Scoped Pools

Each seat's monthly activity is metered by two period-scoped children.

A `QuotaLedger` covers one seat for one `period_index`. It records `search_quota_total` (the snapshot of the contract's `monthly_search_quota_per_seat` taken when the ledger was opened), `searches_used` (a running count of candidate searches invoked against the seat in this period), and `searches_remaining`, which is always `search_quota_total` minus `searches_used` and can never go negative. The ledger's `ledger_status` starts at `OPEN`. When `searches_used` reaches `search_quota_total`, the system moves the ledger from `OPEN` to `EXHAUSTED`, after which further candidate searches on this seat are rejected. At period rollover or seat revocation, the system closes the ledger from either `OPEN` or `EXHAUSTED` to `CLOSED`.

A `MessageCreditPool` likewise covers one seat for one `period_index`. It records `credits_granted` (the snapshot of the contract's `monthly_credit_per_seat` taken when the pool was opened), `credits_used` (the sum of credits consumed by messages that reached `SENT` in this pool), `credits_returned` (the sum of credits returned by messages that transitioned to `RESPONDED`, capped per policy), and `credits_available`, computed as `credits_granted` minus `credits_used` plus `credits_returned`, with a floor at zero. The pool also carries a `spam_strike_count`, described in §3.5. The pool's `pool_status` starts at `OPEN`, may move to `THROTTLED` when strikes accumulate, may return from `THROTTLED` to `OPEN` when a positive response offsets a strike, and is closed to `CLOSED` at period rollover or seat revocation from either `OPEN` or `THROTTLED`.

Both resources are introspectable: clients can list the ledgers and pools for a seat, optionally filtered by `period_index`.

### 3.4. Candidate Visibility and Search

Candidate profiles are peer entities. A `ContractAdmin` creates a `CandidateProfile` by supplying `member_id` (the external member identifier, unique tenant-wide), `full_name`, `headline`, `privacy_setting`, `open_to_work`, `open_to_work_visibility`, `years_experience`, and `current_title`; all eight fields are required on creation. The `privacy_setting` takes values `PUBLIC`, `CONNECTIONS_ONLY`, or `PRIVATE`. The `open_to_work_visibility` takes values `ALL_MEMBERS`, `RECRUITERS_ONLY`, or `NONE`. There is no deletion on this entity.

Visibility governs both candidate search and talent insights. A candidate row is visible to a given recruiter search if and only if at least one of the following holds:

- The candidate's `privacy_setting` is `PUBLIC`; or
- The candidate's `privacy_setting` is `CONNECTIONS_ONLY` and, walking the `manager_recruiter_id` links upward starting from the requesting seat's `assigned_recruiter_id` (with cycles guarded), at least one recruiter encountered as a manager along that chain has `recruiter_status` of `ACTIVE` (this is the system's simplified "connection" proxy); or
- The candidate's `open_to_work` is true and the candidate's `open_to_work_visibility` is either `ALL_MEMBERS` or `RECRUITERS_ONLY` (this third clause applies regardless of `privacy_setting`, so an open-to-work `PRIVATE` candidate is still visible).

For talent-insight generation (§3.8), where there is no requesting seat, the `CONNECTIONS_ONLY` proxy instead resolves to visible whenever at least one `ACTIVE` recruiter exists anywhere in the tenant.

A candidate search runs against a seat and consumes one unit of search quota. The caller submits a `filter_spec` object whose fields may include `current_title` (matched as a case-sensitive substring against the candidate's `current_title`), `min_years_experience` (the candidate's `years_experience` must be at least this value), and `open_to_work_only` (when true, only candidates whose `open_to_work` is true qualify); `filter_spec` may be omitted entirely, in which case every visible candidate matches. Before the search runs, three gates apply: the seat must be `ASSIGNED` (otherwise `ERR_INVALID_STATE`); when the caller is a `RecruiterUser`, the caller's `X-User-ID` must equal the seat's `assigned_recruiter_id` (otherwise `ERR_ROLE_FORBIDDEN`); and the seat's current-period `QuotaLedger` in `OPEN` or `EXHAUSTED` status must exist and have `searches_remaining` of at least 1 — a missing current ledger, or a search against an exhausted quota, is rejected with `ERR_QUOTA_EXHAUSTED`. On success the system applies the visibility filter first, then the `filter_spec`, then truncates the result list to the contract's `search_result_page_cap` — 40 on `RECRUITER_LITE`, 100 on `RECRUITER_PRO`, 1000 on `RECRUITER_CORP`; the returned candidates are sorted by `created_at` ascending before truncation. The search increments `searches_used` on the seat's current ledger by 1 (refreshing the ledger's `updated_at` and `version`); if that brings `searches_used` to `search_quota_total`, the ledger transitions from `OPEN` to `EXHAUSTED` as a side effect.

### 3.5. Search Projects and Messaging

A `SearchProject` is a contract-scoped workspace owned by a seat. A `SeatAdmin` creates one under a contract by providing a `name` (unique within the contract — duplicates are rejected with `ERR_DUPLICATE`), the `owner_seat_id` of the seat that will own it (it must reference a seat under the same contract; an unknown or cross-contract seat is rejected with `ERR_INVALID_REQUEST`), and optionally `pinned_candidate_ids`, an ordered list of `CandidateProfile` ids pinned to the project, capped at 100 entries (more than 100 is rejected with `ERR_INVALID_REQUEST`). The seat need not be `ASSIGNED` at creation; that is enforced only on the DRAFT → OPEN transition. The project's `project_status` begins at `DRAFT` and may move `DRAFT` → `OPEN`, `OPEN` → `ON_HOLD`, `ON_HOLD` → `OPEN`, `OPEN` → `CLOSED`, or `ON_HOLD` → `CLOSED`. The DRAFT → OPEN transition additionally requires the parent contract to be `ACTIVE` and the `owner_seat_id` to reference an `ASSIGNED` seat on the same contract. The ON_HOLD → OPEN transition requires the parent contract to be `ACTIVE`. The project carries a `message_count` derived field: the number of messages tagged with this `project_id` whose `delivery_status` is `SENT`.

Messages are sent from a seat to a candidate. A `RecruiterUser` or `SeatAdmin` sends a message by supplying `candidate_id`, `project_id`, the `body` text, and optionally `job_posting_id` when the send is in the context of a job. The `candidate_id` must resolve to an existing `CandidateProfile`, the `project_id` must resolve to an existing `SearchProject` (the project may be in any `project_status` and need not belong to the same contract as the seat), and a supplied `job_posting_id` must likewise resolve; an unresolvable id is rejected with `ERR_NOT_FOUND`. When the caller is a `RecruiterUser`, the caller's `X-User-ID` must equal the sending seat's `assigned_recruiter_id`; otherwise the request is rejected with `ERR_ROLE_FORBIDDEN`. The seat itself must be `ASSIGNED`; otherwise `ERR_INVALID_STATE`. The seat's current pool must not be `THROTTLED`; a send against a throttled pool is rejected with `ERR_ANTISPAM_THROTTLED`. The recipient candidate must be visible to the sending recruiter under the §3.4 visibility rule; an invisible recipient is rejected with `ERR_CANDIDATE_NOT_VISIBLE`.

Credit accounting happens at send. If the recipient's `open_to_work` is true and their `open_to_work_visibility` is `ALL_MEMBERS`, the message is sent without consuming a credit — the message's `credit_consumed` is 0. Otherwise the pool's `credits_available` must be at least 1; if it is 0 — or if no current-period pool exists for the seat at all — the send is rejected with `ERR_NO_CREDITS_REMAINING`, and on success `credit_consumed` is 1 and the pool's `credits_used` increments by 1. Every new `Message` starts with `delivery_status` of `PENDING` and `response_status` of `AWAITING`. Dispatch resolves immediately within the send call: if dispatch succeeds, the message moves to `delivery_status` of `SENT` (the moment of dispatch is recorded internally as the message's sent-at time); if dispatch fails — for example because the recipient's `privacy_setting` is `PRIVATE` and they are not open-to-work — the message moves to `delivery_status` of `FAILED` and no credit is consumed (a `FAILED` message never contributes to `credits_used`, even on the free-send path where `credit_consumed` was computed as 1 at the gate). Once `SENT`, the message's `response_status` remains `AWAITING` until a response is recorded, the seat is suspended, or 30 days elapse from the recorded sent-at time. A send against a `SUSPENDED` seat is rejected with `ERR_INVALID_STATE` before any throttle or credit check (priority 4.1).

Responses are recorded by the `AtsService` role via a record-response call carrying a `response_kind` — one of `RESPONDED`, `NEGATIVE_RESPONSE`, or `REPORTED_AS_SPAM`. The message must currently have `delivery_status` of `SENT` and `response_status` of `AWAITING`; otherwise the call is rejected with `ERR_INVALID_STATE`. The three kinds behave as follows.

- `RESPONDED` moves the message to `response_status` of `RESPONDED`. If the message's `credit_consumed` is 1 and its `credit_returned_flag` is false, the pool's `credits_returned` increments by 1 and `credit_returned_flag` flips to true — a credit is returned exactly once per message, and the no-credit case (`credit_consumed` 0, the open-to-work `ALL_MEMBERS` path) and the already-returned case are no-ops, protecting against double returns. If, after this response, the pool is `THROTTLED` and its `spam_strike_count` has dropped below 3, the pool returns to `OPEN`.
- `NEGATIVE_RESPONSE` moves the message to `response_status` of `NEGATIVE_RESPONSE`, adds 1 to the pool's `spam_strike_count`, and returns no credit.
- `REPORTED_AS_SPAM` moves the message to `response_status` of `REPORTED_AS_SPAM`, adds 2 to the pool's `spam_strike_count`, and returns no credit.

Spam-strike scoring drives throttling. Each response applies a signed delta to the pool's `spam_strike_count`: `NEGATIVE_RESPONSE` adds 1, `REPORTED_AS_SPAM` adds 2, `EXPIRED` adds 0, and `RESPONDED` subtracts 1 only when the message was `SENT` while the pool was `OPEN` (that is, the message predates the current throttle episode) and the pool's `spam_strike_count` is currently greater than 0; otherwise `RESPONDED` contributes 0. The new count is floored at zero. When the recomputed count reaches or exceeds 3 and the pool is `OPEN`, the pool transitions to `THROTTLED`, and further message sends on the seat are rejected with `ERR_ANTISPAM_THROTTLED`. When the recomputed count falls below 3 and the pool is `THROTTLED`, the pool returns to `OPEN`. The throttle memory belongs to the pool — a positive response that drops the count below 3 does not consume the strike; the strike remains recorded on the pool.

Independently of responses, a message still `AWAITING` 30 days after reaching `SENT` expires: the system moves it to `response_status` of `EXPIRED`, with no credit returned. Seat suspension likewise expires every `AWAITING` message on the seat (see §3.1 and §3.2).

### 3.6. Job Postings, Promoted Slots, and Budget Pacing

A `SeatAdmin` creates a `JobPosting` under a contract by supplying `title`, `budget_cents`, `daily_cap_cents`, `pacing_mode`, `start_at`, `end_at`, and `created_by_seat_id` (the seat must exist under the same contract — an unknown or cross-contract seat is rejected with `ERR_INVALID_REQUEST` — but need not be `ASSIGNED`). `budget_cents` must be at least 1000. `daily_cap_cents` must be at least 100 and no greater than `budget_cents`. `pacing_mode` takes values `EVEN` or `FRONT_LOADED`. The posting begins with `spent_cents` at 0 and `posting_status` of `DRAFT`. The temporal validation on creation is that `start_at` is strictly before `end_at`, and `end_at` minus `start_at` is at least one full day; a violation is rejected with `ERR_INVALID_DATE_RANGE`. The `posting_status` enum takes values `DRAFT`, `ACTIVE`, `PAUSED`, `EXHAUSTED`, `CLOSED`.

Promoted slots are the unit of reserved spend. A `SeatAdmin` reserves a `PromotedSlot` under a posting by supplying `slot_date` (a UTC calendar day in `YYYY-MM-DD` form) and `reserved_cents` (at least 1). The slot's `slot_date` must fall within the posting's date range — on or after the `start_at` calendar date and strictly before the `end_at` calendar date; a slot outside the range is rejected with `ERR_INVALID_DATE_RANGE`. The slot's `slot_status` takes values `RESERVED`, `CONFIRMED`, `RELEASED`.

Activation requires that the parent contract be `ACTIVE`, that the posting have at least one `PromotedSlot` in `RESERVED` or `CONFIRMED`, and that the current time satisfy `start_at` on or before now, strictly before `end_at`. On success the posting moves from `DRAFT` to `ACTIVE`. An `ACTIVE` posting may be paused to `PAUSED`, and a `PAUSED` posting may be resumed to `ACTIVE` provided `spent_cents` is strictly less than `budget_cents` and now is strictly before `end_at`. Closing is permitted from `ACTIVE`, `PAUSED`, or `EXHAUSTED` and moves the posting to `CLOSED`. Whenever a posting transitions to `EXHAUSTED` (from `ACTIVE` via spend) or to `CLOSED` (from `ACTIVE` or `PAUSED`), every `RESERVED` promoted slot it holds is moved to `RELEASED`.

Spend is recorded against a posting in integer cents. Each spend event carries an `amount_cents` and is accepted only while the posting is `ACTIVE`; a spend event against a posting in any other status is rejected with `ERR_INVALID_STATE`. The acceptance test then has four parts, all of which must hold: (i) `amount_cents` is at least 1; (ii) `amount_cents` does not exceed `daily_cap_cents`; (iii) `spent_cents` plus `amount_cents` does not exceed today's cumulative pacing cap (defined below); (iv) `spent_cents` plus `amount_cents` does not exceed `budget_cents`. A violation of any of these is rejected with `ERR_PACING_VIOLATION`.

The cumulative pacing cap depends on the `pacing_mode`. Let `total_days` be the number of whole UTC days in the half-open interval from `start_at` to `end_at` (the validation above guarantees this is at least 1). Let `elapsed_days` be the number of whole UTC days from `start_at` to today's UTC date, plus 1 for today itself, clamped to lie between 1 and `total_days` inclusive.

- Under `EVEN` pacing, today's cumulative cap is the floor of `budget_cents` multiplied by `elapsed_days` and divided by `total_days` — a uniform ramp over the posting's lifetime.
- Under `FRONT_LOADED` pacing, the first half of the period ramps at one-and-a-half times the uniform rate and the second half ramps at half the uniform rate. Let `front_days` be `total_days` divided by 2 rounded up to a whole number of days. When `elapsed_days` is at most `front_days`, the cap is the smaller of `budget_cents` and the floor of `budget_cents` multiplied by 1.5, multiplied by `elapsed_days`, and divided by `total_days`. When `elapsed_days` exceeds `front_days`, the cap is the smaller of `budget_cents` and the floor of `budget_cents` multiplied by the quantity "1.5 times `front_days` plus 0.5 times the difference between `elapsed_days` and `front_days`", all divided by `total_days`.

The two variants deliver the same total spend capacity by `end_at` but accept a different set of spend events on identical inputs; `EVEN` is the uniform ramp, `FRONT_LOADED` concentrates capacity in the first half. All caps are integer cents, computed with floor division at each floor step.

On acceptance the posting's `spent_cents` increments by `amount_cents`. If the new `spent_cents` is greater than or equal to `budget_cents`, the posting transitions from `ACTIVE` to `EXHAUSTED` and every `RESERVED` slot moves to `RELEASED`.

### 3.7. ATS Integrations and Write-Back

An `AtsIntegration` links a contract to an external applicant-tracking system. A `ContractAdmin` creates one by supplying `vendor` (one of `GREENHOUSE`, `LEVER`, `WORKDAY`, `ICIMS`), `external_tenant_id` (the ATS-side tenant identifier, unique in combination with `vendor` within the contract), and optionally `write_back_enabled` (defaulting to `true` when omitted). The integration's `integration_status` begins at `PROVISIONING` and may move `PROVISIONING` → `CONNECTED`, `CONNECTED` → `SYNC_ERROR`, `SYNC_ERROR` → `CONNECTED`, `CONNECTED` → `DISABLED`, or `SYNC_ERROR` → `DISABLED`.

A `ContractAdmin` connects a `PROVISIONING` or `SYNC_ERROR` integration; the contract must be in `ACTIVE` or `RENEWAL_PENDING` status, otherwise the connect is rejected with `ERR_INVALID_STATE`. Disabling an integration from either `CONNECTED` or `SYNC_ERROR` moves it to `DISABLED` and immediately fails every `QUEUED` `AtsSyncRecord` under it — each such record's `sync_status` moves to `FAILED`.

An `AtsSyncRecord` represents a single event pushed back to the ATS. The `AtsService` role creates one by supplying `ats_integration_id`, `candidate_id`, `external_candidate_ref`, `event_type`, and a `payload`. The `event_type` is one of `APPLICATION_FORWARDED`, `STAGE_CHANGED`, `HIRED`, or `DISQUALIFIED`. The server computes a `payload_fingerprint` deterministically from the integration's `vendor`, its `external_tenant_id`, the `candidate_id`, the `event_type`, and the normalized payload JSON — the payload JSON is normalized by serialising it with keys sorted and no insignificant whitespace, and the fingerprint is the SHA-1 hex digest of those five components joined with a pipe (`|`) separator. The `payload` itself is stored with the record but is not returned in API responses. The `sync_status` begins at `QUEUED` and is resolved by the system at creation time according to the following precedence:

1. If another `AtsSyncRecord` under the same `ats_integration_id` already has the same `payload_fingerprint` and is in `sync_status` of `WRITTEN`, the new record's `sync_status` is set to `DUPLICATE_SKIPPED`. This is the duplicate-handling rule: a redelivery of an identical event is acknowledged but never written twice.
2. Otherwise, if the integration is in `integration_status` of `CONNECTED` and `write_back_enabled` is true, the record is written back immediately and its `sync_status` becomes `WRITTEN`.
3. Otherwise, if the integration is `DISABLED`, the record's `sync_status` becomes `FAILED`.
4. Otherwise the record remains `QUEUED` — for example while the integration is still `PROVISIONING` or in `SYNC_ERROR`.

A `QUEUED` record may later resolve to `WRITTEN` once the integration reaches `CONNECTED` with `write_back_enabled` true and no duplicate fingerprint already written exists: on each successful connect, the system flushes that integration's `QUEUED` records in `created_at`-ascending order, marking each `WRITTEN` unless an identical fingerprint is already `WRITTEN` under the integration, in which case the record is marked `DUPLICATE_SKIPPED`. A `QUEUED` record transitions to `FAILED` when the integration is disabled or when dispatch is attempted while the integration is not `CONNECTED`; when this failure occurs on an integration that was `CONNECTED` at the time, the integration itself moves from `CONNECTED` to `SYNC_ERROR` as a side effect.

### 3.8. Talent Insights and the Privacy Aggregation Floor

A `TalentInsightReport` aggregates member data under a contract. A `ContractAdmin` creates one by supplying `report_name` and a `filter_spec` (the same shape used by candidate search — `current_title`, `min_years_experience`, `open_to_work_only`). The report's `report_status` begins at `DRAFT`, its `aggregation_floor` field is fixed at 25 from creation, and its `matched_count` is null until the report is first generated.

Generation is the compute step. A `ContractAdmin` generates a `DRAFT` report; the parent contract must be in `ACTIVE` or `RENEWAL_PENDING` status, otherwise the request is rejected with `ERR_INVALID_STATE`. The system applies the same visibility rule and filter logic as candidate search (§3.4) to compute `matched_count` — the number of `CandidateProfile` rows visible and matching — but unlike candidate search, the result is **not** truncated by the contract's `search_result_page_cap`; `matched_count` is stored raw. The report moves from `DRAFT` to `GENERATED`.

Publishing is gated by a privacy aggregation floor. The report's `aggregation_floor` is fixed at 25. To move a `GENERATED` report to `PUBLISHED`, `matched_count` must be at least 25; an attempt to publish below the floor is rejected with `ERR_AGGREGATION_FLOOR`, and the report remains `GENERATED` — publishing never moves a report to `SUPPRESSED`. Independently, the system's privacy-aggregation sweep may move a `GENERATED` report whose `matched_count` has fallen below 25 to `SUPPRESSED`, ensuring that small-cohort reports are never shareable.

### 3.9. Renewal Events, True-Up, and Proration

Contract-affecting administrative changes — suspension, renewal, and seat true-up — are mediated by a `RenewalEvent` so they carry an audit trail. An `Auditor` proposes an event by supplying the parent `contract_id` in the path, an `event_kind` of `TRUE_UP`, `RENEWAL`, or `SUSPENSION`, an optional `seats_delta` (an integer when present — a non-integer is rejected with `ERR_INVALID_REQUEST`; used only for `TRUE_UP` and ignored for the other kinds), and the OCC guard `expected_contract_version` matching the contract's current `version` (§2.7). The server records the proposer's `X-User-ID` in `requested_by` and echoes the submitted `expected_contract_version` back on the stored event; `proration_credit_cents` is null at proposal time. The event's `event_status` begins at `PROPOSED`, and proposing the event increments the parent contract's `version` by 1.

From `PROPOSED`, an `Auditor` may either approve or reject the event. Rejection moves it to `REJECTED` with no preconditions. Approval moves it to `APPROVED` provided the contract is in `ACTIVE` or `RENEWAL_PENDING`; for `TRUE_UP` events the contract's `true_up_allowed` must also be true (a violation of either precondition yields `ERR_INVALID_STATE`). Approval of a `TRUE_UP` event treats a missing or null `seats_delta` as 0. Approval of a `TRUE_UP` event with a negative `seats_delta` additionally computes `proration_credit_cents` (below) and stores it on the event; for all other events the field remains null. Approval of a `TRUE_UP` event enforces the bounds: `seats_purchased` plus `seats_delta` must be at least `seats_assigned` and at least 1, and must not exceed `seat_cap`; a violation is rejected with `ERR_TRUEUP_BOUNDS`. Application moves an `APPROVED` event to `APPLIED` and triggers the contract-level transition described below; application reuses the same preconditions as the underlying contract transition.

Applying a `SUSPENSION` event suspends the contract (see §3.1) and requires the contract to be `ACTIVE`. Applying a `RENEWAL` event requires the contract to be `RENEWAL_PENDING`; it moves the contract from `RENEWAL_PENDING` back to `ACTIVE`, increments `period_index` by 1, sets `current_period_start` to the previous `current_period_end`, sets `current_period_end` to 30 days after that, closes every `OPEN` or `EXHAUSTED` `QuotaLedger` for the contract's seats (each moves to `CLOSED`) and creates a fresh `OPEN` `QuotaLedger` for the new period per non-`REVOKED` seat, closes every `OPEN` or `THROTTLED` `MessageCreditPool` (each moves to `CLOSED`) and creates a fresh `OPEN` pool per non-`REVOKED` seat (updating each such seat's `last_period_credit_refresh` to the new `period_index`), and increments the contract's `version`. Applying a `TRUE_UP` event requires the contract to be `ACTIVE` and leaves it in `ACTIVE` while mutating its seat inventory: `seats_purchased` increases by `seats_delta` (which may be negative); when `seats_delta` is positive, that many new `Seat` rows are created in `UNASSIGNED` status under the contract, each taking the lowest not-currently-used `SEAT-<sequence>` label (previously used labels of since-revoked seats are not reused); when `seats_delta` is negative, that many `UNASSIGNED` seats — chosen oldest-first by `created_at` — are moved to `REVOKED` (with the ledger and pool closure cascade described in §2.8 and §3.3); and the contract's `version` increments by 1.

The proration credit compensates the customer for seats removed mid-period. The variant selection depends on the contract's `product_tier`: `RECRUITER_LITE` and `RECRUITER_PRO` contracts use the REMAINING variant, while `RECRUITER_CORP` contracts use the ELAPSED variant. The period length is fixed at 30 days. `days_remaining` is the number of days from now to `current_period_end` rounded up to a whole number of days, floored at zero. `days_elapsed` is 30 minus `days_remaining`. The per-seat period cost in cents is the contract's `monthly_credit_per_seat` multiplied by 100 — one dollar per credit as the contract accounting unit. Under the REMAINING variant, `proration_credit_cents` is the absolute value of `seats_delta` multiplied by the per-seat period cost, multiplied by `days_remaining`, divided by 30, with the final result rounded half-up to integer cents. Under the ELAPSED variant, the same formula applies with `days_elapsed` in place of `days_remaining`. The two variants deliberately differ: one credits for the unused remainder of the period, the other only for the fraction already elapsed, so identical inputs yield different outputs across tiers.

### 3.10. Logical Clock

The server's notion of "now" is a logical UTC clock, not the wall clock. A `ContractAdmin` may advance it through a test-driving capability that sets the current logical time to a supplied `to_iso8601` instant (an unparseable value is rejected with `ERR_INVALID_REQUEST`). Before any set, the default logical time is 2026-09-01T00:00:00Z. The endpoint returns the new `now_iso8601`. This clock drives every time-dependent behaviour in this document: the `ACTIVE` → `RENEWAL_PENDING` transition at `current_period_end` minus 7 days, the `RENEWAL_PENDING` → `EXPIRED` transition at `current_period_end` plus 14 days, the 30-day message-response expiry, the period rollover performed by renewal apply, and the `elapsed_days` input to budget pacing. Clock-driven transitions are evaluated lazily — whenever the server handles any request (and immediately upon a clock set) — rather than by a background timer.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a contract, a recruiter, a candidate profile, a search project, a job posting, a promoted slot, an ATS integration, an ATS sync record, a talent insight report, a renewal event, a message) return `201 Created`. Operations that modify an existing resource — activation, suspension, resume, assign, unassign, open, hold, close, connect, disable, record-response, record-spend, generate, publish, approve, reject, apply, clock set — return `200 OK`; the candidate-search operation also returns `200 OK`. Read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/contracts` | Create a recruiter contract | ContractAdmin |
| GET    | `/contracts/{contract_id}` | Fetch a contract | ContractAdmin, SeatAdmin, Auditor |
| GET    | `/contracts` | List contracts (paginated) | ContractAdmin, Auditor |
| POST   | `/contracts/{contract_id}/activate` | Activate a PENDING_ACTIVATION contract; starts period 1 | ContractAdmin |
| POST   | `/contracts/{contract_id}/suspend` | Suspend an ACTIVE contract | Auditor |
| POST   | `/contracts/{contract_id}/resume` | Resume a SUSPENDED contract | ContractAdmin |
| GET    | `/contracts/{id}/seats` | List seats for a contract (paginated) | ContractAdmin, SeatAdmin, Auditor |
| GET    | `/contracts/{contract_id}/seats/{seat_id}` | Fetch a seat | ContractAdmin, SeatAdmin, Auditor, RecruiterUser |
| POST   | `/contracts/{contract_id}/seats/{seat_id}/assign` | Assign seat to recruiter (OCC) | SeatAdmin |
| POST   | `/contracts/{contract_id}/seats/{seat_id}/unassign` | Unassign a seat from its recruiter | SeatAdmin |
| POST   | `/contracts/{contract_id}/seats/{seat_id}/suspend` | Suspend a single seat | SeatAdmin |
| POST   | `/contracts/{contract_id}/seats/{seat_id}/resume` | Resume a suspended seat | SeatAdmin |
| POST   | `/recruiters` | Onboard a recruiter | ContractAdmin |
| GET    | `/recruiters/{recruiter_id}` | Fetch a recruiter | ContractAdmin, SeatAdmin, Auditor |
| GET    | `/recruiters` | List recruiters (paginated; soft-deleted excluded by default) | ContractAdmin, SeatAdmin, Auditor |
| POST   | `/recruiters/{recruiter_id}/deactivate` | Soft-delete a recruiter | ContractAdmin |
| GET    | `/seats/{seat_id}` | Fetch a seat by id | ContractAdmin, SeatAdmin, Auditor, RecruiterUser |
| GET    | `/seats/{id}/projects` | List projects owned by a seat | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/seats/{id}/job-postings` | List job postings created by a seat | SeatAdmin, Auditor |
| GET    | `/seats/{id}/quota-ledgers` | List quota ledgers for a seat | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/seats/{id}/credit-pools` | List credit pools for a seat | SeatAdmin, RecruiterUser, Auditor |
| POST   | `/candidate-profiles` | Create a candidate profile (test-driving data setup) | ContractAdmin |
| GET    | `/candidate-profiles/{candidate_id}` | Fetch a candidate profile | ContractAdmin, SeatAdmin, RecruiterUser, Auditor |
| GET    | `/candidate-profiles/{id}/messages` | List messages addressed to a candidate | ContractAdmin, Auditor |
| POST   | `/seats/{seat_id}/candidate-search` | Run a candidate search; consumes 1 search quota | RecruiterUser, SeatAdmin |
| POST   | `/contracts/{id}/projects` | Create a search project | SeatAdmin |
| GET    | `/contracts/{contract_id}/projects/{project_id}` | Fetch a project | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/contracts/{id}/projects` | List projects for a contract | SeatAdmin, RecruiterUser, Auditor |
| POST   | `/projects/{project_id}/open` | Open a project (DRAFT->OPEN or ON_HOLD->OPEN) | SeatAdmin |
| GET    | `/projects/{project_id}` | Fetch a project by id | SeatAdmin, RecruiterUser, Auditor |
| POST   | `/projects/{project_id}/hold` | Place a project on hold | SeatAdmin |
| POST   | `/projects/{project_id}/close` | Close a project | SeatAdmin |
| POST   | `/seats/{id}/messages` | Send an InMail message; consumes a credit unless open-to-work ALL_MEMBERS | RecruiterUser, SeatAdmin |
| GET    | `/messages/{message_id}` | Fetch a message | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/messages` | List messages (filtered by project or job posting) | SeatAdmin, Auditor |
| GET    | `/seats/{id}/messages` | List messages sent by a seat | SeatAdmin, RecruiterUser, Auditor |
| POST   | `/messages/{message_id}/record-response` | Record candidate response; triggers credit return / strike | AtsService |
| POST   | `/contracts/{id}/job-postings` | Create a job posting | SeatAdmin |
| GET    | `/contracts/{contract_id}/job-postings/{job_posting_id}` | Fetch a job posting | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/contracts/{id}/job-postings` | List postings for a contract | SeatAdmin, Auditor |
| POST   | `/contracts/{contract_id}/job-postings/{job_posting_id}/activate` | Activate a posting (requires >=1 RESERVED/CONFIRMED slot) | SeatAdmin |
| POST   | `/contracts/{contract_id}/job-postings/{job_posting_id}/pause` | Pause a posting | SeatAdmin |
| POST   | `/contracts/{contract_id}/job-postings/{job_posting_id}/resume` | Resume a posting | SeatAdmin |
| POST   | `/contracts/{contract_id}/job-postings/{job_posting_id}/close` | Close a posting | SeatAdmin |
| POST   | `/contracts/{id}/job-postings/{job_posting_id}/promoted-slots` | Reserve a promoted slot for a UTC day | SeatAdmin |
| GET    | `/contracts/{id}/job-postings/{job_posting_id}/promoted-slots` | List promoted slots for a posting | SeatAdmin, Auditor |
| POST   | `/contracts/{contract_id}/job-postings/{job_posting_id}/record-spend` | Record spend against a promoted slot for today; enforces pacing | SeatAdmin |
| GET    | `/job-postings/{job_posting_id}` | Fetch a job posting by id | SeatAdmin, RecruiterUser, Auditor |
| GET    | `/job-postings/{id}/promoted-slots` | List promoted slots for a posting (top-level form) | SeatAdmin, Auditor |
| POST   | `/contracts/{id}/ats-integrations` | Create an ATS integration | ContractAdmin |
| GET    | `/contracts/{contract_id}/ats-integrations/{integration_id}` | Fetch an integration | ContractAdmin, Auditor |
| GET    | `/ats-integrations/{integration_id}` | Fetch an integration by id | ContractAdmin, Auditor |
| GET    | `/contracts/{id}/ats-integrations` | List integrations | ContractAdmin, Auditor |
| POST   | `/contracts/{contract_id}/ats-integrations/{integration_id}/connect` | Mark integration CONNECTED (PROVISIONING->CONNECTED or SYNC_ERROR->CONNECTED) | ContractAdmin |
| POST   | `/contracts/{contract_id}/ats-integrations/{integration_id}/disable` | Disable an integration | ContractAdmin |
| POST   | `/ats-sync-records` | Create an ATS sync record; server computes fingerprint and duplicate status | AtsService |
| GET    | `/ats-sync-records/{record_id}` | Fetch a sync record | ContractAdmin, Auditor |
| GET    | `/ats-sync-records` | List sync records (filtered) | ContractAdmin, Auditor |
| POST   | `/contracts/{id}/talent-insights` | Create a talent insight report (DRAFT) | ContractAdmin |
| GET    | `/contracts/{contract_id}/talent-insights/{report_id}` | Fetch a report | ContractAdmin, Auditor |
| GET    | `/contracts/{id}/talent-insights` | List reports for a contract | ContractAdmin, Auditor |
| POST   | `/contracts/{contract_id}/talent-insights/{report_id}/generate` | Compute matched_count (DRAFT->GENERATED) | ContractAdmin |
| POST   | `/contracts/{contract_id}/talent-insights/{report_id}/publish` | Publish a report (GENERATED->PUBLISHED; below-floor publish is rejected with ERR_AGGREGATION_FLOOR) | ContractAdmin |
| POST   | `/contracts/{id}/renewal-events` | Propose a renewal/true-up/suspension event (OCC on contract; proposing increments the contract's version by 1) | Auditor |
| GET    | `/renewal-events/{renewal_event_id}` | Fetch a renewal event | Auditor, ContractAdmin |
| GET    | `/contracts/{id}/renewal-events` | List renewal events | Auditor, ContractAdmin |
| POST   | `/renewal-events/{renewal_event_id}/approve` | Approve a proposed event; computes proration_credit for TRUE_UP | Auditor |
| POST   | `/renewal-events/{renewal_event_id}/reject` | Reject a proposed event | Auditor |
| POST   | `/renewal-events/{renewal_event_id}/apply` | Apply an approved event; mutates contract | Auditor |
| POST   | `/_clock/set_current_utc` | Set the server's logical UTC clock | ContractAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_RECRUITER_ALREADY_SEATED` | 409 Conflict |
| `ERR_SEAT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_MANAGER_INACTIVE` | 422 Unprocessable Entity |
| `ERR_NO_CREDITS_REMAINING` | 402 Payment Required |
| `ERR_QUOTA_EXHAUSTED` | 402 Payment Required |
| `ERR_ANTISPAM_THROTTLED` | 429 Too Many Requests |
| `ERR_CANDIDATE_NOT_VISIBLE` | 403 Forbidden |
| `ERR_PACING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_AGGREGATION_FLOOR` | 422 Unprocessable Entity |
| `ERR_TRUEUP_BOUNDS` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
