# Volunteer Home Repair API — Product Requirements Document

## 1. Introduction

A community-affiliate home repair program in the Rebuilding Together model exists to close a gap that neither the housing market nor public assistance reaches: low-income homeowners — disproportionately older adults, veterans, and people with disabilities — living in homes whose safety hazards, accessibility deficiencies, and critical-system failures they cannot afford to fix. Running that program is an exercise in constrained allocation. Money arrives as a base appropriation plus corporate sponsor commitments; labor arrives as unskilled volunteers, skilled volunteers, and a registry of licensed trade contractors for the electrical, plumbing, and roofing work volunteers may not legally perform; and demand always exceeds both. Every program year the affiliate must verify which households qualify, send assessors to scope and cost each home's repairs, rank the candidates, select the set of projects its funding can actually carry, staff a rebuild-day event at each selected home, and stand behind the finished work with a warranty.

This document specifies the Volunteer Home Repair API, the REST interface — mounted under the `/rebuild` path prefix — through which staff, volunteers, homeowners, sponsor representatives, trade partners, and platform administrators drive that pipeline. It governs funding cycles and their pool ledgers, sponsorship commitments, homeowner applications, home assessments and their scope items, priority-ranked selection runs, repair projects, rebuild events and volunteer enrollments, trade contractors and their work orders, material orders, and post-project warranty claims. Because the program's rules are saturated with dates — event scheduling, training validity, warranty windows, contractor credential expiry — every date-sensitive rule in the system evaluates against a single controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid in general but absent from the target endpoint's authorization list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system declares nine roles: `PlatformAdmin`, `AffiliateStaff`, `Assessor`, `Homeowner`, `Volunteer`, `TradePartner`, `SponsorRep`, `Anonymous`, and the shared pseudo-role `Any`.

Four roles are entity-backed, meaning the presented `X-User-ID` is the `id` of a persisted resource and ownership checks compare it against foreign keys on the resource being touched. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `HomeownerApplication`, and ownership checks on any resource in that application's chain — the application itself, or a warranty claim targeting its project — compare the chain's application id against `X-User-ID`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`, and enrollment-ownership checks compare the enrollment's `volunteer_id` against it. When `X-User-Role` is `TradePartner`, `X-User-ID` is the `id` of the acting `TradeContractor`, compared against a work order's `contractor_id`. When `X-User-Role` is `SponsorRep`, `X-User-ID` is the `id` of the acting `Sponsor`, compared against a commitment's `sponsor_id`. An entity-backed identity mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining roles are opaque. When `X-User-Role` is `PlatformAdmin`, `AffiliateStaff`, or `Assessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any resource's `id`. `Anonymous` is likewise opaque and represents the unauthenticated public caller: it presents the two headers like any other caller but may only submit a homeowner application or register as a volunteer, and it is explicitly excluded from `Any`-authorized endpoints. `Any` is a listing pseudo-role meaning any caller presenting a declared role except `Anonymous`; it authorizes the read (GET) endpoints, with one restriction noted in §4 for the application list.

Entity-backed roles are further constrained in which fields they may write. A `Homeowner` actor may drive its own application to `WITHDRAWN` and nothing else: any other `status` value from a `Homeowner` is a role-field violation rejected with `ERR_FORBIDDEN`. A `Volunteer` actor may set only `waiver_signed_on`, and only on its own volunteer record; attempting to write `safety_training_completed_on` as a `Volunteer` is likewise `ERR_FORBIDDEN`. A `TradePartner` actor may move only its own work orders, and only to `QUOTED` (carrying `quote_cents`) or `INVOICED` (carrying `invoice_cents`).

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

The server keeps a logical clock that is deliberately divorced from wall-clock time. Before any call has set it, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `PlatformAdmin`-only test-driving capability advances the clock to a supplied instant: the caller provides a `to_iso8601` value and receives the new `current_utc` in response. Every date-sensitive rule in this document — rebuild-event dates, assessment scheduling, safety-training validity, the warranty window, contractor license and insurance expiry, check-in day equality, follow-up visit ordering, and the earliest day trade work may commence — is evaluated against this logical clock.

### 2.5. Common Resource Properties

All primary resources share four system-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource came into existence. The `updated_at` field, in the same format, refreshes on every mutation. The `version` field is an integer that increments by one on every mutation of the resource, and it is the value that optimistic concurrency checks (§2.9) compare against. Exactly one entity breaks this pattern: the `ScopeItem` carries only `id` and `created_at`, and both `updated_at` and `version` are absent from scope items.

### 2.6. The Funding Pool Ledger

Every funding cycle maintains four derived ledger figures, and together they are the single source of truth for what the program can still spend:

- `pool_cents` is the cycle's `total_budget_cents` plus the `amount_cents` of every sponsorship commitment whose status is `RECEIVED` or `ALLOCATED`. `PLEDGED` money is not yet in the pool; `WITHDRAWN` money has left it.
- `reserved_cents` is the sum of `reserved_balance_cents` over all of the cycle's projects — the portion of selected-project funding envelopes still being held against the pool.
- `spent_cents` is cumulative outflow: the `invoice_cents` of `PAID` trade work orders, plus the `total_cents` of material orders in `DELIVERED`, plus the `payout_cents` of `RESOLVED` warranty claims. Because returning a delivered material order subtracts its `total_cents` back out, `spent_cents` is net of material refunds.
- `available_cents` is exactly `pool_cents` minus `reserved_cents` minus `spent_cents`.

One compensating invariant governs the ledger: `available_cents` equals `pool_cents` minus `reserved_cents` minus `spent_cents` before and after every mutation, with no exceptions. A selection that reserves an envelope, paired with a later cancellation that releases it, leaves `available_cents` unchanged; a material delivery that adds to `spent_cents`, paired with a return that subtracts the same amount, leaves it unchanged; and an invoice payment that shifts funds from reserved to spent, followed by a project completion that releases the remainder, leaves it unchanged as well.

### 2.7. Money Handling, Precision, and Rounding

All monetary quantities are integer cents. The API never accepts or emits fractional cents, and money is never materialized as a floating-point value mid-calculation. Where a computation genuinely produces a fraction — a scope-item midpoint, a contingency envelope, a per-line material total, the delivery fee, the priority score, the warranty reserve — the result is rounded half up to the nearest integer cent (or, for the priority score, the nearest integer point). Ratio comparisons such as the income-limit test are cross-multiplied in integer arithmetic so that no ratio ever becomes a float.

### 2.8. Project Readiness Posture

Every project continuously carries a computed `readiness_posture` of `READY` or `BLOCKED`, and this two-state posture is the gatekeeper for the rebuild day. The posture is `READY` exactly when both halves of a conjunction hold: every scope item in `INCLUDED` whose `volunteer_performable` is false is covered by a trade work order in one of `SCHEDULED`, `IN_PROGRESS`, `PENDING_INSPECTION`, `INSPECTED`, `INVOICED`, or `PAID`; and no material order of the project is in `ORDERED` or `STAGED`. If any licensed-trade item lacks live coverage, or any material order is still in flight, the posture is `BLOCKED`. Posture is not decorative: it gates event locking (§3.6) and drives the automatic `PLANNING`-to-`READY` promotion and `READY`-to-`PLANNING` demotion described in §3.5, §3.7, and §3.8.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and on both the version field is non-optional. Creating a selection run against a funding cycle requires the request to carry `expected_funding_cycle_version` equal to the cycle's current `version`. Amending a project's scope requires `expected_project_version` equal to the project's current `version`. In either case, if the client's last observed version has fallen behind the server's — another writer advanced the parent since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed. On success, each operation increments the parent entity's `version` by one. Endpoints other than these two do not accept a version field at all.

### 2.10. Validation Priority Order

A single request can fail several checks at once, so the server evaluates checks in a fixed priority order and reports the first failure encountered. The order is:

1. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN`).
3. Entity-backed ownership and role-specific field rules (`ERR_NOT_RESOURCE_OWNER`, with `ERR_FORBIDDEN` for the field-rule violations of §2.1).
4. Existence of path identifiers, validated left to right, then existence of body foreign-key references (the not-found family of §2.11).
5. Optimistic-concurrency version match (`ERR_STALE_VERSION`).
6. State-machine from-state legality (`ERR_INVALID_STATE` and the specific state errors `ERR_CYCLE_NOT_SELECTION_OPEN`, `ERR_EVENT_NOT_PUBLISHED`, `ERR_EVENT_NOT_LOCKABLE`, `ERR_PROJECT_NOT_COMPLETED`).
7. Volunteer safety eligibility (`ERR_VOLUNTEER_NOT_ELIGIBLE`).
8. Contractor credential qualification (`ERR_CONTRACTOR_NOT_QUALIFIED`).
9. Temporal rules (`ERR_EVENT_DATE_PAST`, `ERR_INVALID_DATE_RANGE`, `ERR_TRADE_WINDOW_CONFLICT`, `ERR_VOLUNTEER_DOUBLE_BOOKED`, `ERR_CONTRACTOR_DAY_CAPACITY`, `ERR_WARRANTY_EXPIRED`).
10. Constraint rules (`ERR_EVENT_AT_CAPACITY`, `ERR_TEAM_LEADER_ALREADY_ASSIGNED`, `ERR_TRADE_MISMATCH`, `ERR_SCOPE_ITEM_ALREADY_COVERED`, `ERR_PERMIT_REQUIRED`, `ERR_SCOPE_ITEM_NOT_DROPPABLE`, `ERR_INCOME_LIMIT_EXCEEDED`, `ERR_VERIFICATION_INCOMPLETE`).
11. Fiscal rules, always last (`ERR_INSUFFICIENT_FUNDING`, `ERR_ENVELOPE_EXCEEDED`, `ERR_WARRANTY_CAP_EXCEEDED`).

The ordering is observable. A scope amendment sent with a stale project version that would also exceed available funding is rejected with `ERR_STALE_VERSION`, never `ERR_ENVELOPE_EXCEEDED`; an enrollment attempt on an event that is not yet open reports `ERR_EVENT_NOT_PUBLISHED` before the volunteer's eligibility is even examined.

### 2.11. Nested Resource Retrieval and Reference Existence

Endpoints that address a nested resource validate every identifier in the path in strict left-to-right order and reject with the first missing resource's 404 before examining anything further; a selection-run creation under a non-existent cycle fails on the cycle before the request body is even considered. After path identifiers, the server validates body foreign keys: `funding_cycle_id`, `application_id`, `project_id`, `event_id`, `volunteer_id`, `contractor_id`, `sponsor_id`, and each element of `scope_item_ids`. The concrete not-found codes, all HTTP 404, are `ERR_FUNDING_CYCLE_NOT_FOUND`, `ERR_SELECTION_RUN_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_MATERIAL_ORDER_NOT_FOUND`, and `ERR_WARRANTY_CLAIM_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Funding Cycles and Sponsor Money

A program year begins when a `PlatformAdmin` creates a funding cycle with a human-readable `name`, a four-digit `fiscal_year`, and the base appropriation `total_budget_cents`, which may not be negative. The cycle's scoring variant, `priority_mode`, is either `STANDARD` or `HAZARD_PRIORITY` and defaults to `STANDARD` when omitted. A new cycle is born `OPEN` with its pool equal to the base budget and both `reserved_cents` and `spent_cents` at zero, so `available_cents` initially equals the entire `pool_cents`.

Cycle administration is deliberately linear. From `OPEN`, a `PlatformAdmin` opens selection by moving the cycle to `SELECTION_OPEN`; attempting the move from any other source state is rejected with `ERR_INVALID_STATE`. From `SELECTION_OPEN` the administrator seals the cycle (`SELECTION_OPEN` → `SEALED`), which does three things atomically: every selection run of the cycle still in `COMPUTED` is discarded to `DISCARDED`; every application of the cycle still in `CANDIDATE` is deferred to `DEFERRED` with `decision_reason` set to the literal `CYCLE_SEALED`; and the cycle's `version` increments by one. From `SEALED` the administrator closes the cycle, but only when every project of the cycle has already reached `CLOSED` or `CANCELLED` — a single straggler project keeps the cycle unclosable and the attempt is `ERR_INVALID_STATE`. Each successful transition increments the cycle's `version` by one.

Sponsor money enters through two records. A `PlatformAdmin` first registers the sponsor itself with a legal `name`, a `contact_email`, and an optional `sponsor_tier` of `COMMUNITY`, `REGIONAL`, or `NATIONAL` (defaulting to `COMMUNITY`). A pledge against a specific cycle is then created — by a `SponsorRep` whose `X-User-ID` equals the pledge's `sponsor_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), or by `AffiliateStaff` — carrying `sponsor_id`, `funding_cycle_id`, a strictly positive `amount_cents`, and an optional `team_build_event_date` naming the sponsor's team-building day, which may be null. A commitment is born `PLEDGED`, and pledged money is not yet in the pool.

Marking a `PLEDGED` commitment `RECEIVED` is staff work: it stamps `received_at` from the logical clock and immediately raises the cycle's `pool_cents` and `available_cents` by `amount_cents`. The only other operator-driven moves are withdrawals, and their cost depends on the state left behind. Withdrawing a `PLEDGED` commitment merely stamps `withdrawn_at`; the pool is unchanged because the money never entered it. Withdrawing a `RECEIVED` or `ALLOCATED` commitment stamps `withdrawn_at`, drops `pool_cents` and `available_cents` by `amount_cents`, and — for an allocated commitment — returns its `allocated_amount_cents` to zero. Because received money may already be reserved against selected projects, this second kind of withdrawal runs a four-link compensating cascade:

1. The cycle ledger is recomputed under the invariant of §2.6.
2. While `reserved_cents` exceeds `pool_cents` minus `spent_cents`, the lowest-priority cancellable project — one in `PLANNING` or `READY`, chosen by `priority_score_snapshot` ascending with ties broken by the project's `created_at` descending, so that among equals the most recently created is sacrificed first — is cancelled with `cancellation_reason` `FUNDING_WITHDRAWN`, repeating until the invariant holds again.
3. Each cancelled project releases its `reserved_balance_cents` back to the cycle, its application falls to `DEFERRED` with `decision_reason` `FUNDING_WITHDRAWN`, and every non-terminal rebuild event of the project is cancelled.
4. Every enrollment of such a cascade-cancelled event that sits in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN` is withdrawn to `WITHDRAWN`.

The remaining commitment transition, `RECEIVED` → `ALLOCATED`, is never operator-driven: it fires only inside a selection-run apply, when the sponsor waterfall assigns a positive `allocated_amount_cents` to the commitment (§3.4).

### 3.2. Homeowner Applications, Eligibility, and Priority

A household enters the pipeline when an application is submitted — self-service by an `Anonymous` caller, or assisted by `AffiliateStaff` — carrying the `funding_cycle_id` of the cycle applied to (a dangling reference is `ERR_FUNDING_CYCLE_NOT_FOUND`), the `homeowner_name`, the primary applicant's `date_of_birth`, the `household_size` (an occupant count between 1 and 8 inclusive), the annual `household_income_cents` (zero or more), two flags `is_veteran` and `has_disability`, two documentation flags `ownership_doc_provided` and `occupancy_doc_provided`, and the home's `address`. The application is born `SUBMITTED`, and at creation the server computes `is_older_adult` from `date_of_birth` against the logical clock using calendar birthday math: an applicant aged at least 62 — exactly 62 counts — is an older adult.

Verification is staff work. An `AffiliateStaff` operator first moves `SUBMITTED` → `UNDER_VERIFICATION` (any other source state is `ERR_INVALID_STATE`), and from there either rejects the application to `REJECTED` with a `decision_reason` recorded, or verifies it. Verification enforces two checks. First, income eligibility: the household qualifies when `household_income_cents` scaled by one hundred is at most eighty times the area median income for its household size — equivalently, annual income at or below 80% of AMI, inclusive, so an income of exactly 80% of AMI passes and one cent above fails with `ERR_INCOME_LIMIT_EXCEEDED`. The AMI table, in integer cents, is: one occupant 5,400,000 (that is, $54,000); two occupants 6,170,000; three 6,940,000; four 7,710,000; five 8,330,000; six 8,950,000; seven 9,560,000; eight 10,180,000. The comparison is computed entirely in integer cents — income times 100 against 80 times the AMI figure — and never as a floating-point ratio. Second, documentation: both `ownership_doc_provided` and `occupancy_doc_provided` must be true, otherwise `ERR_VERIFICATION_INCOMPLETE`.

The same income figure fixes the household's need tier for scoring, using the same cross-multiplied integer comparisons. Income at or below 30% of AMI is the deep-need tier; income above 30% but at or below 50% of AMI is the low tier; anything higher that still passed the 80% eligibility ceiling is the standard tier.

A verified application's `priority_score` is computed at the moment it reaches `VERIFIED`, and recomputed later when an assessment is scoped (§3.3). The score starts from a base of 40 points when `is_older_adult` is true, plus 25 points when `is_veteran` is true, plus 30 points when `has_disability` is true. The base is then multiplied by the tier factor — one and a half for the deep-need tier, one and a quarter for the low tier, exactly one for the standard tier — then a hazard bonus is added, then the result is rounded half up to an integer, and finally the score is clamped into the inclusive range 0 to 100. The evaluation order is pinned: multiply first, add the hazard bonus second, round third, clamp last. At verification time the hazard bonus is always zero.

Later lifecycle moves are simple state steps. `AffiliateStaff` may nominate an `ASSESSED` application to `CANDIDATE`, or defer a `CANDIDATE` application to `DEFERRED` with a `decision_reason` recorded; both reject a wrong source state with `ERR_INVALID_STATE`. A deferred application can be restored to `CANDIDATE`, but only while its cycle is `OPEN` or `SELECTION_OPEN`, otherwise `ERR_INVALID_STATE`. Selection (`CANDIDATE` → `SELECTED`) is system-driven by the apply described in §3.4, and fulfillment (`SELECTED` → `FULFILLED`) is system-driven when the project completes (§3.9).

Withdrawal is broad but role-shaped. A `SUBMITTED` application may be withdrawn by staff. From `UNDER_VERIFICATION`, `VERIFIED`, `CANDIDATE`, or `DEFERRED`, either staff or the owning homeowner — a `Homeowner` actor whose `X-User-ID` equals the application's `id` — may withdraw it. Withdrawing a `SELECTED` application is heavier: the linked project is cancelled with `cancellation_reason` `HOMEOWNER_WITHDRAWN` under the full project-cancellation cascade of §3.9. The same identity rule governs reads: a `Homeowner` may retrieve its own application, and attempting to read another household's record is `ERR_NOT_RESOURCE_OWNER`.

### 3.3. Home Assessments and the Scope of Work

Once an application is verified, staff schedule a home assessment by naming the `application_id` and a `scheduled_on` visit date. The application must be `VERIFIED`, `ASSESSING`, or `ASSESSED` — anything else is `ERR_INVALID_STATE` — and `scheduled_on` must fall on or after the logical clock date, otherwise `ERR_INVALID_DATE_RANGE`. Creating the assessment flips the application from `VERIFIED` to `ASSESSING`; scheduling a fresh assessment on an already-`ASSESSED` application flips it back to `ASSESSING` as well, which is the re-assessment loop. A still-`SCHEDULED` assessment may be cancelled to `CANCELLED` by staff.

Field findings are recorded by an `Assessor`, whose completion call carries the `safety_hazard_max_severity` (an integer from 0 to 5), the `accessibility_needs_count`, an optional free-text `critical_systems_notes`, and a non-empty `scope_items` array. Each proposed scope item declares a `category` of `SAFETY`, `ACCESSIBILITY`, `CRITICAL_SYSTEMS`, `ENERGY`, or `GENERAL`; a `required_trade` of `NONE`, `CARPENTRY`, `ELECTRICAL`, `PLUMBING`, `ROOFING`, or `HVAC`; the booleans `volunteer_performable` and `requires_permit`; a low estimate `est_low_cents` that must be strictly positive; a high estimate `est_high_cents` that must be at least `est_low_cents`; and a free-text `description`. One coherence rule binds two of those fields together: `required_trade` must be `NONE` exactly when `volunteer_performable` is true — a volunteer-performable item naming a licensed trade, or a trade item marked volunteer-performable, fails as `ERR_INVALID_REQUEST`, as do an empty item list and an estimate range whose high end sits below its low end.

Completion creates every scope item in status `INCLUDED`, with each item's `midpoint_cents` computed as the sum of `est_low_cents` and `est_high_cents` halved and rounded half up to the cent, and stamps `completed_on` from the logical clock; the assessment is then `COMPLETED`. Staff or the assessor subsequently move `COMPLETED` → `SCOPED`. When the scoped assessment is the application's latest one, the application leaves `ASSESSING` for `ASSESSED` and its `priority_score` is recomputed — and this recomputation is where the hazard bonus enters. Under a cycle whose `priority_mode` is `HAZARD_PRIORITY`, the score's hazard bonus is ten points per severity level of the `safety_hazard_max_severity` recorded on the latest `SCOPED` assessment, while under `STANDARD` the bonus is zero and severity never enters the score at all. While no assessment has been scoped, the hazard term is zero regardless of mode. The same pinned evaluation order from §3.2 applies: multiply the base by the tier factor, add the hazard bonus, round half up, clamp to the 0–100 band.

### 3.4. Selection Runs, Funding Envelopes, and the Sponsor Waterfall

Ranking happens inside a selection run. `AffiliateStaff` (or a `PlatformAdmin`) create a run against a cycle that is `SELECTION_OPEN` — any other cycle state is `ERR_CYCLE_NOT_SELECTION_OPEN` — and the request must carry `expected_funding_cycle_version` per §2.9. At creation the run freezes the cycle's `priority_mode` into `priority_mode_snapshot`, computes `ranked_application_ids` as every application of the cycle sitting in `CANDIDATE`, ordered by `priority_score` descending with ties broken by the application's `created_at` ascending so earlier applicants win ties, supersedes any previous `COMPUTED` run of the cycle to `SUPERSEDED`, and increments the cycle's `version` by one. The new run is `COMPUTED`, with `applied_at` null until an apply.

Applying a `COMPUTED` run is the allocation step, restricted to `AffiliateStaff`, and it again demands a cycle in `SELECTION_OPEN` (`ERR_CYCLE_NOT_SELECTION_OPEN`) and a run still in `COMPUTED` (`ERR_INVALID_STATE`). The apply walks the ranking greedily as a first-fit: each application's funding envelope is computed, and if the envelope fits the cycle's remaining `available_cents` the application is selected; if it does not fit, that application is skipped — not terminated — and the walk continues down the ranking, so a smaller project later in the list can still be funded. The fitting subset is recorded in the run's `selected_application_ids`.

Each selected application becomes `SELECTED` and spawns a project in `PLANNING`. The project's `envelope_cents` is its provisional estimate plus a tiered contingency, computed in a pinned order. First comes the provisional estimate itself: the sum of `midpoint_cents` over the project's `INCLUDED` scope items, where scope estimates are labor-inclusive for licensed-trade items and full-cost for volunteer-performable items, and where material orders are tracked separately and never enter the figure. Then a contingency rate is keyed on that pre-contingency estimate: 15% when the estimate is below 500,000 cents; 10% when it is 500,000 cents or more but still below 2,000,000 cents; and 5% when it reaches 2,000,000 cents or more — so an estimate of exactly 500,000 cents falls into the 10% band, never the 15% band. Finally the envelope is the estimate scaled by one plus the rate, rounded half up to the cent. The envelope is frozen onto the project at selection, `reserved_balance_cents` starts equal to `envelope_cents`, `priority_score_snapshot` copies the application's `priority_score`, and the cycle's `reserved_cents` rises by the sum of the created envelopes.

The apply then runs the sponsor waterfall. The need is the sum of the newly created envelopes, and funding sources are consumed in a pinned order: the cycle's base `total_budget_cents` first, then each `RECEIVED` commitment in `received_at` ascending order with ties broken by the commitment's `created_at` ascending. Each commitment in turn is allocated the lesser of its `amount_cents` and the remaining need. Any commitment receiving a positive allocation transitions to `ALLOCATED` with its `allocated_amount_cents` recorded — a partially allocated commitment still takes `ALLOCATED` with its partial amount, and its unallocated remainder simply stays in the pool. `PLEDGED` and `WITHDRAWN` commitments are never touched by the waterfall. When the walk ends, the run is `APPLIED` with `applied_at` stamped, the cycle's `version` increments by one, and the response summarizes the outcome as an object carrying `applied_count`, `project_ids`, and `deferred_application_ids`.

### 3.5. Scope Amendments and Cost Reconciliation

Between selection and the build, staff may amend a project's scope, provided the project is still `PLANNING` or `READY` — any other state is `ERR_INVALID_STATE` — and the request carries `expected_project_version` per §2.9. The amendment payload may add items through `add_items`, where each element follows the scope-item input shape minus `assessment_id` because amendment-added items join the project's existing assessment; drop items through `drop_item_ids`; and restore previously dropped items through `restore_item_ids`. Dropping requires the item to be `INCLUDED` (else `ERR_INVALID_STATE`) and not covered by any non-terminal trade work order — a covered item refuses to drop with `ERR_SCOPE_ITEM_NOT_DROPPABLE`. Restoring requires the item to be `DROPPED` (else `ERR_INVALID_STATE`).

Every amendment recomputes the project's economics. The `provisional_estimate_cents` is re-aggregated over the surviving `INCLUDED` items, `envelope_cents` is re-derived through the tiered-contingency formula of §3.4, and `reserved_balance_cents` is adjusted by the envelope delta. If the recomputed envelope would push the project's reserved balance above the cycle's available headroom, the amendment is rejected with `ERR_ENVELOPE_EXCEEDED` (HTTP 402). A successful amendment increments the project's `version` by one.

Two cost figures shadow each project through its life. The provisional estimate — the selection and planning basis already defined in §3.4 — sums midpoints over `INCLUDED` items and ignores actual invoices and material deliveries. The reconciled cost, carried on the project as `reconciled_cost_cents`, progressively replaces estimates with actuals as the build advances: it sums the `invoice_cents` of the project's work orders in `INVOICED` or `PAID`, plus the midpoints of volunteer-performable scope items in `INCLUDED` or `COMPLETED` that are not covered by any invoiced or paid work order, plus the `total_cents` of material orders in `DELIVERED`. Provisional midpoints of trade-covered items drop out of the reconciled figure as soon as real invoices exist for them. The reconciled figure recomputes on scope-item completion, on invoicing and payment, and on material delivery or return, and it is finalized when the project completes.

### 3.6. Rebuild Events, Volunteers, and Enrollments

Volunteers self-register through an open call carrying `full_name`, `email`, an optional `skills` array drawn from the trade values `NONE`, `CARPENTRY`, `ELECTRICAL`, `PLUMBING`, `ROOFING`, and `HVAC` (defaulting to an empty array), and an optional `team_leader_eligible` flag (defaulting to false). A new volunteer is `REGISTERED` with `waiver_signed_on` and `safety_training_completed_on` both null. The waiver is self-service: the volunteer sets `waiver_signed_on` on its own record, and may set nothing else (§2.1). Safety training is staff-recorded: `AffiliateStaff` sets `safety_training_completed_on`.

A volunteer's derived `is_eligible` is the conjunction of four facts: the volunteer is `REGISTERED`, a `waiver_signed_on` date is present, a `safety_training_completed_on` date is present, and the training date plus 365 days is on or after the logical clock date — training completed exactly 365 days ago still qualifies. Staff may deactivate a volunteer (`REGISTERED` → `DEACTIVATED`), which withdraws that volunteer's `ENROLLED` or `CONFIRMED` enrollments on events in `PUBLISHED` or `LOCKED`; reinstatement flips the volunteer back to `REGISTERED`.

Events live on project sites. Staff create an event by naming the `project_id`, a `name`, an `event_date`, and the site's `max_volunteers` capacity, which must be at least 1 (otherwise `ERR_INVALID_REQUEST`). The host project must be `PLANNING`, `READY`, or `EVENT_SCHEDULED` (else `ERR_INVALID_STATE`), and `event_date` must fall on or after the logical clock date (else `ERR_EVENT_DATE_PAST`). The event is born `DRAFT`; staff later publish it (`DRAFT` → `PUBLISHED`) to open enrollment.

Capacity accounting is exact. An event's `open_slots` is `max_volunteers` minus the count of active enrollments — those in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN` — and a team-leader enrollment occupies one slot exactly like any other. The enrollment that brings the active count equal to `max_volunteers` succeeds; the next attempt fails with `ERR_EVENT_AT_CAPACITY`. The invariant that `max_volunteers` equals the active count plus `open_slots` holds at all times, and an enrollment paired with a later withdrawal leaves `open_slots` unchanged.

Enrollment is open to a `Volunteer` actor enrolling itself — the payload's `volunteer_id` must equal the caller's `X-User-ID`, otherwise `ERR_NOT_RESOURCE_OWNER` — and to staff enrolling anyone. The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`), the volunteer must satisfy `is_eligible` (`ERR_VOLUNTEER_NOT_ELIGIBLE`), a slot must be free, and the volunteer must not already hold an active enrollment on another event sharing the same calendar `event_date` (`ERR_VOLUNTEER_DOUBLE_BOOKED`). A payload setting `is_team_leader` adds two further checks: the volunteer must be `team_leader_eligible` (else `ERR_INVALID_REQUEST`), and the event must not already carry an active team-leader enrollment (else `ERR_TEAM_LEADER_ALREADY_ASSIGNED`).

Locking is the point of no return before the build. Staff move `PUBLISHED` → `LOCKED`, which demands two proofs, each reported as `ERR_EVENT_NOT_LOCKABLE`: at least one active team-leader enrollment exists on the event — `is_team_leader` true with the enrollment in `ENROLLED` or `CONFIRMED` — and the host project's `readiness_posture` is `READY`. On lock, every `ENROLLED` enrollment of the event becomes `CONFIRMED`, and the host project advances `READY` → `EVENT_SCHEDULED`.

On the day itself, attendance is recorded per enrollment. A `CONFIRMED` enrollment becomes `CHECKED_IN` only when the logical clock date equals the event's `event_date` — any other day is `ERR_INVALID_STATE` — and only at the hand of `AffiliateStaff` or of the event's team leader, meaning a `Volunteer` whose `X-User-ID` matches the `volunteer_id` of a team-leader enrollment on the same event (otherwise `ERR_NOT_RESOURCE_OWNER`). Staff may also mark a `CONFIRMED` enrollment `NO_SHOW` directly.

Executing a `LOCKED` event requires the clock date to be on or after `event_date`. Execution finalizes attendance — every `CHECKED_IN` enrollment becomes `COMPLETED` and every still-`CONFIRMED` enrollment becomes `NO_SHOW` — completes the volunteer work by moving every `INCLUDED` scope item of the project's assessment with `volunteer_performable` true to `COMPLETED`, and advances the project `EVENT_SCHEDULED` → `IN_BUILD`. One interplay with §3.7 matters here: if a contractor suspension has dropped the project's posture since the event locked, the project stays `EVENT_SCHEDULED` but the event cannot execute until readiness returns, because the posture is re-checked at execution time.

Volunteers (or staff) may withdraw an `ENROLLED` or `CONFIRMED` enrollment to `WITHDRAWN`, releasing the slot so `open_slots` rises. A withdrawn enrollment may later re-enroll (`WITHDRAWN` → `ENROLLED`), and re-enrollment re-runs the full creation gauntlet: the event still `PUBLISHED`, the volunteer still eligible, a slot free, the same-day double-booking check re-evaluated, and — for a `Volunteer` actor — ownership of the enrollment.

Cancelling an event, whether by staff action or by cascade, withdraws every enrollment sitting in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN`. Cancelling a `LOCKED` event additionally returns the host project from `EVENT_SCHEDULED` to `READY` when its posture is still `READY`.

### 3.7. Licensed Trade Work and Contractor Oversight

Some work volunteers may not legally perform, and for that the affiliate keeps a registry of licensed trade contractors. A `PlatformAdmin` registers each firm with its `legal_name`, its `trade` (one of `CARPENTRY`, `ELECTRICAL`, `PLUMBING`, `ROOFING`, `HVAC`), the `license_number`, the `license_expires_on` and `insurance_expires_on` dates, and an optional `max_concurrent_jobs` defaulting to 1 — the maximum number of the firm's distinct work orders whose visit windows may share one calendar day. A contractor is born `ACTIVE` with `strike_count` zero.

Staff commission trade work by creating a work order naming the `project_id`, the `contractor_id`, and the `scope_item_ids` the order will cover. Commissioning enforces a stack of checks: the project must be `PLANNING` or `READY` (`ERR_INVALID_STATE`); the contractor must exist (`ERR_CONTRACTOR_NOT_FOUND`) and be `ACTIVE` (`ERR_CONTRACTOR_NOT_QUALIFIED`); every element of `scope_item_ids` must resolve to an `INCLUDED` scope item of the project's assessment (a dangling id is `ERR_SCOPE_ITEM_NOT_FOUND`, an item no longer `INCLUDED` is `ERR_INVALID_STATE`); every covered item must have `volunteer_performable` false and a `required_trade` equal to the contractor's trade (`ERR_TRADE_MISMATCH`); and no covered item may already sit under another work order that is not `CANCELLED` (`ERR_SCOPE_ITEM_ALREADY_COVERED`). The order is born `QUOTE_REQUESTED` with its `trade` copied from the contractor's record, and the project's posture is recomputed.

The commercial loop then runs quote, approve, schedule. The `TradePartner` whose `X-User-ID` equals the order's `contractor_id` quotes by moving `QUOTE_REQUESTED` → `QUOTED` carrying a strictly positive `quote_cents`; a foreign contractor is `ERR_NOT_RESOURCE_OWNER` and a non-positive quote is `ERR_INVALID_REQUEST`. Staff approve `QUOTED` → `APPROVED`, and when any covered scope item has `requires_permit` true the approval must carry a `permit_number`, otherwise `ERR_PERMIT_REQUIRED`. Staff then schedule `APPROVED` → `SCHEDULED` by supplying `visit_start` and `visit_end`.

Scheduling enforces four rules, in ascending specificity. The window must be well formed: `visit_end` strictly after `visit_start`, otherwise `ERR_INVALID_DATE_RANGE`. The contractor must still be credentialed: `ACTIVE`, with `license_expires_on` and `insurance_expires_on` each on or after the visit start date, otherwise `ERR_CONTRACTOR_NOT_QUALIFIED`. The window must not collide: treating each visit as a half-open interval, a conflict exists exactly when an existing order of the same contractor in `SCHEDULED` or `IN_PROGRESS` starts before the new visit ends and the new visit starts before that existing visit ends; back-to-back windows, where one order's `visit_end` equals the other's `visit_start`, are expressly permitted, and a true overlap is `ERR_TRADE_WINDOW_CONFLICT`. And the day must not overflow: the count of that contractor's distinct `SCHEDULED` or `IN_PROGRESS` orders whose `visit_start` falls on the same UTC calendar day (day boundaries at 00:00:00Z) must be below `max_concurrent_jobs`, otherwise `ERR_CONTRACTOR_DAY_CAPACITY`. A successful schedule records the window on the order and recomputes the project's posture, which may fire the automatic `PLANNING` → `READY` promotion.

Work commences when the clock allows: `SCHEDULED` → `IN_PROGRESS` requires the logical clock date on or after the `visit_start` date (otherwise `ERR_INVALID_STATE`), and a host project still in `EVENT_SCHEDULED` advances to `IN_BUILD` at the same moment. When the crew reports done, staff move the order `IN_PROGRESS` → `PENDING_INSPECTION`.

Inspection is the quality gate, and the inspection call carries an `outcome` of `PASSED` or `FAILED` plus an optional free-text `notes`. A passing outcome moves the order to `INSPECTED`, stamps `inspected_on` from the logical clock, moves every covered scope item to `COMPLETED`, and recomputes the project's posture and `reconciled_cost_cents`. A failing outcome moves the order to `INSPECTION_FAILED`, stamps `inspected_on`, and adds one to the contractor's `strike_count`; when the count reaches 3 the contractor auto-suspends (`ACTIVE` → `SUSPENDED`) and the full suspension cascade below fires. Rework loops the order `INSPECTION_FAILED` → `IN_PROGRESS`, permitted only while the contractor is `ACTIVE` (else `ERR_CONTRACTOR_NOT_QUALIFIED`).

Payment closes the loop. The owning `TradePartner` invoices `INSPECTED` → `INVOICED` carrying a strictly positive `invoice_cents`, under the same ownership and positivity rules as the quote. Staff then pay `INVOICED` → `PAID`, but only while `invoice_cents` is at most the project's `reserved_balance_cents` — an invoice larger than the remaining reserve is `ERR_ENVELOPE_EXCEEDED` (HTTP 402). Payment moves money through the ledger of §2.6: the cycle's `spent_cents` rises by `invoice_cents`, the project's `reserved_balance_cents` falls by the same amount, the cycle's `reserved_cents` falls with it, and the project's reconciled cost recomputes. `PAID` is terminal.

Staff may cancel a work order from any of `QUOTE_REQUESTED`, `QUOTED`, `APPROVED`, or `SCHEDULED`; cancellation records a free-text `cancellation_reason`, recomputes the project's posture, and may demote a `READY` project back to `PLANNING`. `CANCELLED` is terminal alongside `PAID`.

Contractor discipline is platform work. A `PlatformAdmin` may suspend an `ACTIVE` contractor, reinstate a `SUSPENDED` one (which resets `strike_count` to zero), or terminate from either `ACTIVE` or `SUSPENDED`; wrong source states are `ERR_INVALID_STATE`, and each of these transitions increments the contractor's `version` by one. Suspension — whether manual or automatic at three strikes — runs a three-link cascade. First, every work order of the contractor in `QUOTE_REQUESTED`, `QUOTED`, `APPROVED`, or `SCHEDULED` is cancelled with `cancellation_reason` set to the literal `CONTRACTOR_SUSPENDED`. Second, each affected project's `readiness_posture` is recomputed, and a `READY` project whose posture drops to `BLOCKED` demotes to `PLANNING`. Third, a project in `EVENT_SCHEDULED` whose posture drops stays `EVENT_SCHEDULED`, but its events can no longer execute until readiness returns, because posture is re-checked at execution. Termination from `ACTIVE` or `SUSPENDED` runs the same work-order cancellation cascade.

### 3.8. Material Orders and Logistics

Materials are ordered per project by staff, with an optional `supplier` name (null allowed) and a non-empty `lines` array; each line carries an `item_name`, a `quantity` of at least 1, and a `unit_price_dollars` greater than zero, with violations rejected as `ERR_INVALID_REQUEST`. The lines are immutable once the order exists. The host project must be `PLANNING`, `READY`, `EVENT_SCHEDULED`, or `IN_BUILD` — anything else is `ERR_INVALID_STATE`.

Order totals are computed in a pinned rounding order. Each line is first converted to cents on its own — `quantity` times `unit_price_dollars` times one hundred, rounded half up — and the order's `subtotal_cents` is the sum of those individually rounded line amounts. The `delivery_fee_cents` is then the subtotal times three and a half percent, rounded half up, computed on the already-rounded subtotal. The `total_cents` is the subtotal plus the fee. Summing raw dollar amounts across lines first and rounding once at the end is a different, non-conforming algorithm and yields different cents on fractional inputs. At creation the order's `total_cents` must fit within the cycle's `available_cents`, otherwise `ERR_INSUFFICIENT_FUNDING` (HTTP 402).

A new order is born `ORDERED`, and because an outstanding order blocks readiness under §2.8, creating one recomputes the project's posture and can drop a `READY` project back to `PLANNING`. Staff then stage the order (`ORDERED` → `STAGED`) and record delivery (`STAGED` → `DELIVERED`); delivery raises the cycle's `spent_cents` by `total_cents` and recomputes posture, which may fire the automatic `PLANNING` → `READY` promotion. Returns are permitted from any non-terminal state. Returning an `ORDERED` or `STAGED` order merely recomputes posture. Returning a `DELIVERED` order refunds `total_cents` out of the cycle's `spent_cents` and recomputes posture, possibly demoting `READY` back to `PLANNING`. `RETURNED` is terminal.

### 3.9. Completion, Warranty, and Project Close-Out

When the work is done, staff complete the project from `IN_BUILD`. Completion refuses to fire while loose ends remain: every scope item of the project's assessment must be `COMPLETED` or `DROPPED`, and every trade work order of the project must be `PAID` or `CANCELLED`, with violations reported as `ERR_INVALID_STATE`. Completion stamps `completed_on` from the logical clock, sets `warranty_valid_until` to twelve calendar months after `completed_on` inclusive, releases the remaining reserve back to the cycle — the cycle's `reserved_cents` drops by the project's `reserved_balance_cents`, which itself goes to zero — moves the application `SELECTED` → `FULFILLED`, and finalizes `reconciled_cost_cents`.

The thirty-day follow-up visit opens the warranty period: staff set `follow_up_completed_on` on a `COMPLETED` project, and the visit date must be on or after `completed_on` (otherwise `ERR_INVALID_DATE_RANGE`); recording it moves the project to `WARRANTY_ACTIVE`. Final closure (`WARRANTY_ACTIVE` → `CLOSED`) is allowed only once the logical clock date is after `warranty_valid_until` and no warranty claim of the project remains in `SUBMITTED` or `APPROVED`; either violation is `ERR_INVALID_STATE`.

Projects can also be cancelled outright: by staff from `PLANNING`, `READY`, or `EVENT_SCHEDULED`, or by the funding-withdrawal and homeowner-withdrawal cascades of §3.1 and §3.2. A project in `IN_BUILD` or any later state cannot be cancelled, and the attempt is `ERR_INVALID_STATE`. Cancellation records a `cancellation_reason` of `FUNDING_WITHDRAWN`, `STAFF_DECISION`, or `HOMEOWNER_WITHDRAWN` — the field stays null unless the project is `CANCELLED` — and runs the full cascade: the remaining `reserved_balance_cents` is released to the cycle; every non-terminal rebuild event of the project is cancelled and those events' non-terminal enrollments are withdrawn; every non-terminal trade work order is cancelled; every material order in `ORDERED` or `STAGED` becomes `RETURNED`; and the application falls to `DEFERRED` (with `decision_reason` `FUNDING_WITHDRAWN` or `STAFF_DECISION`) or to `WITHDRAWN` for the homeowner cascade.

Within the warranty window the household may file claims. A claim — created by the owning `Homeowner`, whose `X-User-ID` must equal the project's `application_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), or by `AffiliateStaff` — carries the `project_id`, a `description` of the defect, and a strictly positive `claim_amount_cents`. The project must be `WARRANTY_ACTIVE` (`ERR_PROJECT_NOT_COMPLETED`), and the claim must arrive while the logical clock date is on or before `warranty_valid_until`: a claim filed exactly on the anniversary date is valid, and a later one is `ERR_WARRANTY_EXPIRED`. The claim is born `SUBMITTED` with `submitted_on` stamped from the clock.

Staff adjudicate claims. Denial moves `SUBMITTED` → `DENIED` with an optional `resolution_note`. Approval moves `SUBMITTED` → `APPROVED` carrying a `payout_cents` that must be strictly positive and no more than `claim_amount_cents` (otherwise `ERR_INVALID_REQUEST`) and, more interestingly, no more than the project's remaining warranty reserve (otherwise `ERR_WARRANTY_CAP_EXCEEDED`, HTTP 402). The reserve is the lesser of two figures — eight percent of the project's `reconciled_cost_cents`, rounded half up, and a hard cap of 250,000 cents — and the remaining reserve is that figure minus the `payout_cents` of the project's claims already in `APPROVED` or `RESOLVED`; a payout exactly equal to the remaining reserve succeeds. An approved claim is later resolved (`APPROVED` → `RESOLVED`) with an optional `resolution_note`, and resolution raises the cycle's `spent_cents` by `payout_cents`. `DENIED` and `RESOLVED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`, and this covers every state-driving PATCH as well as the action-style calls that apply a selection run, record assessment completion, schedule or inspect a work order, and advance the logical clock. The scope-amendment call is the one nuance: it returns `201 Created` because it can add new scope-item records to the project's assessment. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rebuild/funding-cycles` | Create a funding cycle (status `OPEN`, ledgers zeroed) | PlatformAdmin |
| GET | `/rebuild/funding-cycles/{cycleId}` | Get one funding cycle including computed ledger fields | Any |
| PATCH | `/rebuild/funding-cycles/{cycleId}` | Drive cycle transitions: `SELECTION_OPEN` \| `SEALED` \| `CLOSED` | PlatformAdmin |
| POST | `/rebuild/funding-cycles/{cycleId}/selection-runs` | Create and compute a selection run (supersedes a prior `COMPUTED` run); OCC-guarded | AffiliateStaff, PlatformAdmin |
| GET | `/rebuild/selection-runs` | List selection runs, filterable by cycle | Any |
| GET | `/rebuild/selection-runs/{runId}` | Get one selection run with its ranking | Any |
| POST | `/rebuild/selection-runs/{runId}/apply` | Apply a `COMPUTED` run: greedy first-fit selection, project creation, sponsor waterfall | AffiliateStaff |
| POST | `/rebuild/sponsors` | Register a corporate sponsor | PlatformAdmin |
| GET | `/rebuild/sponsors/{sponsorId}` | Get one sponsor | Any |
| POST | `/rebuild/commitments` | Pledge a sponsorship commitment to a cycle | SponsorRep, AffiliateStaff |
| GET | `/rebuild/commitments` | List commitments; filters by sponsor and/or cycle | Any |
| GET | `/rebuild/commitments/{commitmentId}` | Get one commitment | Any |
| PATCH | `/rebuild/commitments/{commitmentId}` | Drive commitment transitions: `RECEIVED` \| `WITHDRAWN` | AffiliateStaff |
| POST | `/rebuild/applications` | Submit a homeowner application (self-service or staff-assisted) | Anonymous, AffiliateStaff |
| GET | `/rebuild/applications` | List applications; filters by cycle and status | AffiliateStaff, PlatformAdmin, Assessor |
| GET | `/rebuild/applications/{applicationId}` | Get one application (a `Homeowner` may read only its own) | Any |
| PATCH | `/rebuild/applications/{applicationId}` | Drive application transitions: `UNDER_VERIFICATION` \| `VERIFIED` \| `REJECTED` \| `DEFERRED` \| `CANDIDATE` \| `WITHDRAWN` (Homeowner: `WITHDRAWN` only, on own record) | AffiliateStaff, Homeowner |
| POST | `/rebuild/assessments` | Schedule a home assessment for a `VERIFIED`/`ASSESSED` application | AffiliateStaff |
| GET | `/rebuild/assessments` | List assessments; filter by application | Any |
| GET | `/rebuild/assessments/{assessmentId}` | Get one assessment | Any |
| POST | `/rebuild/assessments/{assessmentId}/complete` | Record field findings and the proposed scope of work | Assessor |
| PATCH | `/rebuild/assessments/{assessmentId}` | Drive assessment transitions: `SCOPED` \| `CANCELLED` | Assessor, AffiliateStaff |
| GET | `/rebuild/scope-items` | List scope items; filter by assessment and status | Any |
| GET | `/rebuild/scope-items/{scopeItemId}` | Get one scope item | Any |
| GET | `/rebuild/projects` | List projects; filters by application and/or cycle | Any |
| GET | `/rebuild/projects/{projectId}` | Get one project with computed posture, estimate, envelope, and ledger fields | Any |
| PATCH | `/rebuild/projects/{projectId}` | Drive project transitions: `COMPLETED` \| `CANCELLED` \| `CLOSED`; setting `follow_up_completed_on` on a `COMPLETED` project opens `WARRANTY_ACTIVE` | AffiliateStaff |
| POST | `/rebuild/projects/{projectId}/scope-amendments` | Amend project scope (add/drop/restore items); OCC-guarded | AffiliateStaff |
| POST | `/rebuild/events` | Create a rebuild-day event on a project site | AffiliateStaff |
| GET | `/rebuild/events` | List events; filter by project and status | Any |

| GET | `/rebuild/events/{eventId}` | Get one event including computed `open_slots` | Any |
| PATCH | `/rebuild/events/{eventId}` | Drive event transitions: `PUBLISHED` \| `LOCKED` \| `EXECUTED` \| `CANCELLED` | AffiliateStaff |
| POST | `/rebuild/volunteers` | Open volunteer registration | Anonymous |
| GET | `/rebuild/volunteers/{volunteerId}` | Get one volunteer including computed `is_eligible` | Any |
| PATCH | `/rebuild/volunteers/{volunteerId}` | Update waiver (self), safety training (staff), or status `DEACTIVATED` \| `REGISTERED` (staff) | Volunteer, AffiliateStaff |
| POST | `/rebuild/enrollments` | Enroll a volunteer in a published event | Volunteer, AffiliateStaff |
| GET | `/rebuild/enrollments` | List enrollments; filters by event and/or volunteer | Any |
| GET | `/rebuild/enrollments/{enrollmentId}` | Get one enrollment | Any |
| PATCH | `/rebuild/enrollments/{enrollmentId}` | Drive enrollment transitions: `CHECKED_IN` \| `NO_SHOW` \| `WITHDRAWN` \| `ENROLLED` (re-enroll from `WITHDRAWN`) | Volunteer, AffiliateStaff |
| POST | `/rebuild/trade-contractors` | Register a licensed trade contractor | PlatformAdmin |
| GET | `/rebuild/trade-contractors/{contractorId}` | Get one contractor | Any |
| PATCH | `/rebuild/trade-contractors/{contractorId}` | Drive contractor transitions: `SUSPENDED` \| `ACTIVE` (reinstate) \| `TERMINATED` | PlatformAdmin |
| POST | `/rebuild/trade-work-orders` | Commission licensed trade work covering scope items volunteers cannot perform | AffiliateStaff |
| GET | `/rebuild/trade-work-orders` | List work orders; filters by project and/or contractor | Any |
| GET | `/rebuild/trade-work-orders/{workOrderId}` | Get one work order | Any |
| POST | `/rebuild/trade-work-orders/{workOrderId}/schedule` | Set the visit window (half-open); credential, overlap, and day-capacity checks | AffiliateStaff |
| POST | `/rebuild/trade-work-orders/{workOrderId}/inspect` | Record an inspection outcome for work pending inspection | AffiliateStaff |
| PATCH | `/rebuild/trade-work-orders/{workOrderId}` | Drive work-order transitions; TradePartner (own orders): `QUOTED` with `quote_cents`, `INVOICED` with `invoice_cents`; AffiliateStaff: `APPROVED` \| `IN_PROGRESS` \| `PENDING_INSPECTION` \| `PAID` \| `CANCELLED` | TradePartner, AffiliateStaff |
| POST | `/rebuild/material-orders` | Place a material order for a project (lines rounded per line, then fee) | AffiliateStaff |
| GET | `/rebuild/material-orders` | List material orders; filter by project and status | Any |
| GET | `/rebuild/material-orders/{orderId}` | Get one material order with computed totals | Any |
| PATCH | `/rebuild/material-orders/{orderId}` | Drive material transitions: `STAGED` \| `DELIVERED` \| `RETURNED` | AffiliateStaff |
| POST | `/rebuild/warranty-claims` | File a warranty claim on a completed repair within the twelve-month window | Homeowner, AffiliateStaff |
| GET | `/rebuild/warranty-claims` | List warranty claims; filter by project and status | Any |
| GET | `/rebuild/warranty-claims/{claimId}` | Get one warranty claim | Any |
| PATCH | `/rebuild/warranty-claims/{claimId}` | Drive claim transitions: `APPROVED` (with `payout_cents`) \| `DENIED` \| `RESOLVED` | AffiliateStaff |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; all date-sensitive rules evaluate against it | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier the API can return and its HTTP status. Trigger conditions for each error live in the workflow narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FUNDING_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_SELECTION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCOPE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_NOT_SELECTION_OPEN` | 409 Conflict |
| `ERR_EVENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_EVENT_NOT_LOCKABLE` | 409 Conflict |
| `ERR_PROJECT_NOT_COMPLETED` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CONTRACTOR_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_EVENT_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_TRADE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_VOLUNTEER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CONTRACTOR_DAY_CAPACITY` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EVENT_AT_CAPACITY` | 409 Conflict |
| `ERR_TEAM_LEADER_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_TRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SCOPE_ITEM_ALREADY_COVERED` | 409 Conflict |
| `ERR_PERMIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SCOPE_ITEM_NOT_DROPPABLE` | 422 Unprocessable Entity |
| `ERR_INCOME_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDING` | 402 Payment Required |
| `ERR_ENVELOPE_EXCEEDED` | 402 Payment Required |
| `ERR_WARRANTY_CAP_EXCEEDED` | 402 Payment Required |
