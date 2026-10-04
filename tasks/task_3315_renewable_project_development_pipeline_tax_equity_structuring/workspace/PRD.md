# Renewable Pipeline Tax Equity API — Product Requirements Document

## 1. Introduction

Utility-scale renewable developers run a long, compliance-heavy pipeline: a project begins as a prospect with little more than a nameplate ambition, matures through land control and interconnection queue positioning, contracts its revenue through power purchase agreements, procures turbines and modules under safe-harbor timing rules, qualifies for federal investment tax credits under continuity-of-work doctrines, and is finally financed through a tax equity partnership whose cash and credit waterfalls flip once the investor reaches its target return. Each of these steps is gated by documentary evidence, by hard calendar deadlines measured against a logical clock, and by segregation-of-duties rules that keep the person who submits construction evidence from being the person who certifies it.

This document specifies the REST API that backs that pipeline. The API models twelve resources — projects, site control instruments, interconnection requests and studies, offtake agreements, supply agreements and procurement orders, construction milestones, tax credit qualifications, tax equity partnerships and their ledger entries, and debt facilities — and drives them through explicit state machines whose transitions enforce the commercial and regulatory gates of the domain. The platform is built around four structural commitments: optimistic concurrency on writes whose inputs can be invalidated by other writers; cascading side effects, where one certification at commercial operation date fans out across the credit, debt, and partnership ledgers; dual-variant calculations, where the same qualification step evaluates differently under the two safe-harbor methods or the two continuity doctrines; and temporal windowing, where exercise windows, safe-harbor confirmation windows, continuity gaps, and cure windows are all measured against a single controllable logical clock.

The audience is the engineering team implementing the service. Every rule in this document is normative. Where a threshold, an operator, or an enumeration value is given, it is exact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which the operator acts. A request whose `X-User-Role` header is missing or does not name one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). These two checks run before any resource lookup or payload validation, in that order.

Nine roles are declared. For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it (for example, as `submitted_by_user_id` or `certified_by_user_id` on a milestone, where a transition writes it) but does not compare it to any entity's `id`.

- `DeveloperAdmin` — developer organization administrator; owns projects and site control.
- `OriginationManager` — originates interconnection requests, manages studies, and runs offtake negotiations.
- `ProcurementLead` — owns supply agreements and procurement orders, including safe-harbor deposits.
- `ConstructionManager` — plans milestones and submits work evidence; may NOT certify (segregation of duties).
- `TaxCounsel` — certifies milestones, drives tax credit qualification, structures partnerships, and runs distributions and the flip; may NOT submit evidence (segregation of duties).
- `InvestorManager` — tax equity investor operator; posts capital contributions only.
- `LenderAgent` — debt provider; owns facilities, draws, conversion, retirement, and default.
- `Auditor` — read-only oversight across all resources.
- `PlatformAdmin` — platform operator; drives the logical clock and interconnection upgrade cost allocation, and holds read access to all resources.

The full authorization matrix is given per endpoint in §4.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless otherwise specified, list results are sorted by `created_at` in ascending order.

### 2.4. Resource Identity and Timestamps

Every persisted resource exposes a server-minted `id` — a UUID with no type prefix. Every resource with the standard field set also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and an integer `version` that increments by one on every mutation of the resource. Partnership ledger entries are the single exception: a ledger entry is an immutable record carrying `id` and `created_at` only — it has no `updated_at` and no `version`, and no update endpoint exists for it.

### 2.5. The Logical Clock

All temporal rules in this document are evaluated against a single logical clock maintained by the platform, never against wall-clock time. Before any call has set it, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin` advances or sets the clock through a test-driving capability that takes a supplied `to_iso8601` instant and returns the resulting `current_utc`. Option exercise windows, safe-harbor confirmation windows, continuity assessments, cure windows, offtake expiry, and the stamping of `cod_date`, `safe_harbor_established_date`, `lapse_date`, and `flip_date` all read this clock.

### 2.6. Monetary Precision and Rounding

All monetary amounts are computed and stored to 2 decimal places using round-half-up rounding, and this applies to safe-harbor thresholds, credit amounts, upgrade cost shares, waterfall tiers, term debt sizing, and liquidated damages alike. Where a calculation rule below specifies a different unit (whole days, integer queue positions, percent ratios), the rule says so explicitly; everything else monetary is 2-decimal round-half-up.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency against a parent resource's `version`, and these are the only two sanctioned OCC checks in the system; endpoints not named here take no version field.

When opening an offtake negotiation against a project, the request must carry `expected_project_version`, the client-side last observed `version` of the project. If the project's current `version` has advanced beyond that value — for example because another writer has just executed or terminated an offtake on the project, legitimately changing the active-offtake set — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), since the current writer's view of the project is stale.

When electing the flip on a tax equity partnership, the request must carry `expected_partnership_version`, the client-side last observed `version` of the partnership. Contributions and distributions each advance the partnership `version`, so a stale version means the IRR basis the client relied on is no longer current; the flip election is then rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Nested Resource Retrieval and Path Validation

URLs nest child resources under their parents (a study under an interconnection request under a project, and so on). Every id appearing in a request path is validated left-to-right: each id must exist, and each child must belong to the declared parent chain of the ids to its left. Each child resource carries its parent reference as a field — `project_id` on site control instruments, interconnection requests, offtake agreements, supply agreements, construction milestones, tax credit qualifications, tax equity partnerships, and debt facilities; `request_id` on interconnection studies; `supply_agreement_id` on procurement orders; and `partnership_id` on partnership ledger entries — and the chain check compares these references. Any failure along the chain is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Validation Order

When several checks could fail on the same request, the server evaluates them in a fixed priority order and reports the first failure: authentication of the role header comes first (priority 1, `ERR_UNAUTHENTICATED`), then role authorization for the endpoint (priority 2, `ERR_FORBIDDEN`), then existence and parent-chain validation of path ids (priority 3, `ERR_NOT_FOUND`), then payload shape — required fields present, types and enum values valid, `start_date` strictly before `end_date`, `window_start` not after `window_end`, amounts positive where required (priority 4, `ERR_VALIDATION`), then optimistic-concurrency version checks (priority 5, `ERR_STALE_VERSION`), then from-state validity of the requested transition (priority 6, `ERR_INVALID_STATE`), then segregation of duties on milestone certification (priority 7, `ERR_SEGREGATION_OF_DUTIES`), then the time-window rules (priority 8 — `ERR_OPTION_WINDOW_LAPSED`, `ERR_SAFE_HARBOR_WINDOW_LAPSED`, `ERR_CONTINUITY_LAPSED`, `ERR_CURE_WINDOW_EXPIRED`), then structural constraints — parcel overlap, study-window conflicts, the single-active-offtake rule, milestone sequence ordering (priority 9 — `ERR_PARCEL_OVERLAP`, `ERR_STUDY_WINDOW_CONFLICT`, `ERR_ACTIVE_OFFTAKE_EXISTS`, `ERR_MILESTONE_OUT_OF_ORDER`), then cross-entity state gates (priority 10 — `ERR_OFFTAKE_REQUIRED`, `ERR_INTERCONNECTION_NOT_EXECUTED`, `ERR_SUPPLY_AGREEMENT_NOT_EXECUTED`, `ERR_PHASE_STUDY_NOT_ACCEPTED`, `ERR_UPGRADE_ALLOCATION_REQUIRED`, `ERR_COD_MILESTONE_PREREQUISITE`), then the money rules (priority 11 — `ERR_PRICE_FLOOR_BREACH`, `ERR_SAFE_HARBOR_TEST_FAILED`, `ERR_CONTRIBUTION_EXCEEDS_COMMITMENT`, `ERR_DISTRIBUTION_EXCEEDS_CASH`, `ERR_DSCR_BELOW_MINIMUM`, `ERR_TARGET_IRR_NOT_ACHIEVED`), and finally the tax-credit anchor state (priority 12 — `ERR_SAFE_HARBOR_NOT_QUALIFIED`, `ERR_CREDIT_DISQUALIFIED`). A mid-flight authentication or path failure therefore always surfaces before any business rule, and a stale version surfaces before any state or fiscal check.

## 3. Business Logic & Workflows

### 3.1. Project Inception and Site Control

A `DeveloperAdmin` creates a project by supplying its `name`, its `technology` (one of `WIND`, `SOLAR`, or `HYBRID`), its `target_capacity_mw` nameplate figure, and its `resource_class` assessment grade (one of `A`, `B`, or `C`). Two certification flags may be supplied at creation and default to false when omitted: `energy_community_eligible`, which marks the site as a qualifying energy community, and `domestic_content_certified`, which marks the project-level domestic content certification. An `availability_guarantee_pct` may also be supplied for the operations handoff; it defaults to 97.0 percent. A new project enters in `PROSPECT` status, and creating the project automatically creates exactly one tax credit qualification for it in `NOT_ELIGIBLE` status — one per project, always, with no separate creation step. The project also exposes two computed fields that mirror the qualification: `tax_credit_anchored` is true while the qualification sits in `SAFE_HARBOR_ESTABLISHED`, `CONTINUITY_MAINTAINED`, `CURED`, or `QUALIFIED`, and `total_itc_credits_usd` mirrors the qualification's `qualified_credit_usd` once the qualification reaches `QUALIFIED`, reading 0.00 before then.

Land control is established through site control instruments created under the project, each identified by a `parcel_id`, an `instrument_type` of `LAND_OPTION` or `EASEMENT`, a window from `start_date` to `end_date`, and an `exercise_price_usd`. The window is a half-open interval — it covers `start_date` and runs up to but not including `end_date` — and `end_date` must be strictly greater than `start_date`. A new instrument enters in `DRAFT`. Executing it (moving it to `EXECUTED`) is refused with `ERR_PARCEL_OVERLAP` (HTTP 409) when any other instrument on the same `parcel_id` is in `EXECUTED`, `EXERCISED`, or `RECORDED` and its half-open window overlaps this one; pure adjacency, where one instrument's `end_date` equals the other's `start_date`, is not an overlap.

An `EXECUTED` instrument may be exercised — moving to `EXERCISED` — only while the logical clock has not passed its `end_date`. An exercise attempted after the window has closed is rejected with `ERR_OPTION_WINDOW_LAPSED` (HTTP 409), and the failed attempt itself pushes the instrument into `EXPIRED`. An exercised instrument is later perfected by recording it (`EXERCISED` to `RECORDED`), and both `EXECUTED` and `EXERCISED` instruments may be terminated. Terminating an exercised instrument triggers a posture re-evaluation: if no remaining instrument of the project is `EXERCISED` or `RECORDED` and the project is currently `SITE_SECURED`, the project reverts to `PROSPECT`. Exercise of any instrument likewise causes the project's site control posture to be re-evaluated.

The project lifecycle proper begins when the first instrument reaches `EXERCISED` or `RECORDED`: a `DeveloperAdmin` can then advance the project from `PROSPECT` to `SITE_SECURED`. From `SITE_SECURED` the project may step back to `PROSPECT` freely, or advance to `DEVELOPMENT` once at least one interconnection request exists for the project that is not `WITHDRAWN`. From `DEVELOPMENT` the project may likewise step back to `SITE_SECURED`, or advance to `READY_FOR_CONSTRUCTION`, which is gated on two cross-entity conditions — at least one offtake agreement of the project in `EFFECTIVE` status (otherwise `ERR_OFFTAKE_REQUIRED`, HTTP 409) and at least one interconnection request in `AGREEMENT_EXECUTED` or `IN_SERVICE` (otherwise `ERR_INTERCONNECTION_NOT_EXECUTED`, HTTP 409).

### 3.2. Interconnection Queueing, Studies, and Upgrade Cost Allocation

An `OriginationManager` submits an interconnection request under a project, supplying a `cluster_id` identifying the queue cluster and a `requested_capacity_mw` figure that later drives upgrade cost shares. The request enters in `QUEUED`, and its `queue_position` is assigned as one more than the highest position among non-`WITHDRAWN` requests in the same cluster — or 1 when the cluster is empty. Every request also carries `upgrade_allocated` (false until an allocation has run over its cluster), `upgrade_cost_share_usd` (this request's allocated share), and `last_upgrade_total_usd` (the cluster-wide upgrade total used for the most recent allocation, mirrored onto every request in the cluster and reused when a withdrawal forces re-allocation; it starts at 0.0).

The request advances through the queue in fixed order: `QUEUED` to `FEASIBILITY_STUDY`, then to `SYSTEM_IMPACT_STUDY`, then to `FACILITIES_STUDY`, then to `AGREEMENT_EXECUTED`, and finally to `IN_SERVICE`. The phase gates are documentary. Moving from `FEASIBILITY_STUDY` to `SYSTEM_IMPACT_STUDY` requires that the most recently created (by `created_at`) `FEASIBILITY`-phase study of the request be `ACCEPTED`, failing with `ERR_PHASE_STUDY_NOT_ACCEPTED` (HTTP 409) otherwise. Moving from `SYSTEM_IMPACT_STUDY` to `FACILITIES_STUDY` requires both that the latest `SYSTEM_IMPACT` study be `ACCEPTED` (same error) and that `upgrade_allocated` be true for this request (otherwise `ERR_UPGRADE_ALLOCATION_REQUIRED`, HTTP 409). Moving from `FACILITIES_STUDY` to `AGREEMENT_EXECUTED` requires the latest `FACILITIES` study to be `ACCEPTED`. The step into `QUEUED` from creation, and the final `AGREEMENT_EXECUTED` to `IN_SERVICE` step, carry no preconditions.

Studies are scoped against a request with a `phase` (`FEASIBILITY`, `SYSTEM_IMPACT`, or `FACILITIES`) and a study window from `window_start` to `window_end`; the window is a closed interval covering both endpoints, so `window_end` must be greater than or equal to `window_start`. Scoping is rejected with `ERR_STUDY_WINDOW_CONFLICT` (HTTP 409) when another study of the same phase exists on the same cluster whose window, widened by a 5-calendar-day buffer on each side, collides with the new one — concretely, when the existing study's `window_end` is at least the new `window_start` minus 5 days and its `window_start` is at most the new `window_end` plus 5 days. A scoped study moves from `SCOPED` to `IN_PROGRESS`, then to `DELIVERED`, and is then either accepted (`DELIVERED` to `ACCEPTED`, which unblocks the parent request's next phase gate) or found deficient (`DELIVERED` to `DEFICIENT`). A deficient study re-enters `IN_PROGRESS` through the rework loop, and each such rework increments the study's `rework_count`, which starts at 0. `ACCEPTED` is terminal for a study.

Withdrawing an interconnection request is permitted from any status other than `IN_SERVICE` or `WITHDRAWN` itself (an attempt from either of those fails with `ERR_INVALID_STATE`). Withdrawal fires a three-step cluster cascade. First, the withdrawn request's `queue_position` is set to 0. Second, the cluster reseats: every non-`WITHDRAWN` request in the same cluster whose position was greater than the withdrawn position is decremented by one, processed in ascending `queue_position` order, so that after the reseat the positions of the remaining non-`WITHDRAWN` requests are exactly the consecutive integers from 1 up to the count of remaining requests. Third, the reseat itself triggers a recomputation of upgrade cost shares across the remaining non-`WITHDRAWN` cluster requests using the mirrored `last_upgrade_total_usd` — this recomputation is skipped when `last_upgrade_total_usd` is 0 — and the recomputation marks each remaining request's `upgrade_allocated` true, which can cure an allocation gate for requests still waiting to enter facilities study.

The allocation itself is run by a `PlatformAdmin` against any request of the cluster, supplying a `total_upgrade_cost_usd` figure. The pool is every non-`WITHDRAWN` request sharing the `cluster_id`; `WITHDRAWN` requests contribute no capacity and receive no share. Each request's `upgrade_cost_share_usd` is the total upgrade cost multiplied by its `requested_capacity_mw` and divided by the sum of `requested_capacity_mw` across the pool, rounded half-up to 2 decimal places, computed over the pool in ascending `queue_position` order. If the rounded shares sum to less or more than the total, the remainder — the total minus the sum of the shares — is added to the share of the pool request with the largest `requested_capacity_mw`, breaking ties by earliest `created_at` and never by id. Every request in the pool then has `upgrade_allocated` set to true and `last_upgrade_total_usd` set to the supplied total.

### 3.3. Offtake Contracting

An `OriginationManager` opens an offtake negotiation under a project by supplying the `buyer_type` (`UTILITY` or `CORPORATE`), a `base_price_usd_mwh`, an annual `escalator_pct`, a `term_years` delivery term, and a `delivery_start_date`. Because opening a negotiation changes the project's active-offtake set, the request must carry `expected_project_version` per §2.7; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create puts the agreement in `NEGOTIATING` and increments the project's `version` by 1.

The negotiation cycle runs between `NEGOTIATING` and `COUNTERED`. Moving from `NEGOTIATING` to `COUNTERED` increments the agreement's `counter_count` (which starts at 0), and moving from `COUNTERED` back to `NEGOTIATING` increments it again — each direction of the loop counts one round. On either transition the payload may supply a replacement `base_price_usd_mwh`, which overwrites the agreement's price when present.

Execution is reachable from either `NEGOTIATING` or `COUNTERED` and carries two guards, evaluated with equal force from both branches. First, the agreement's `base_price_usd_mwh` must be at least 20.00 dollars per MWh — a price below the floor fails with `ERR_PRICE_FLOOR_BREACH` (HTTP 422). Second, no other offtake agreement of the same project may be in `EXECUTED` or `EFFECTIVE` status — a second active offtake fails with `ERR_ACTIVE_OFFTAKE_EXISTS` (HTTP 409). A successful execution also increments the project's `version` by 1. From `EXECUTED` the agreement is activated into `EFFECTIVE` without further preconditions. Expiry is system-driven: once the logical clock passes the `delivery_start_date` plus the full `term_years` term, an `EFFECTIVE` agreement moves to `EXPIRED`. Termination is permitted from any status other than `EXPIRED` or `TERMINATED` (an attempt from either fails with `ERR_INVALID_STATE`); terminating an `EFFECTIVE` agreement also increments the project's `version` by 1 and means the project can no longer satisfy the offtake gate for `READY_FOR_CONSTRUCTION`.

### 3.4. Equipment Procurement and Safe Harbor Qualification

A `ProcurementLead` creates a supply agreement under a project, naming the `equipment_type` (`TURBINE` or `MODULE`), the `supplier_name`, the `total_contract_usd` value, and optionally the supplier's own `domestic_content_certified` flag, which defaults to false. The agreement enters in `DRAFT` and is executed without preconditions. Once `EXECUTED`, it supports an amendment cycle: moving to `AMENDMENT_PENDING` requires the payload to carry an `amendment_total_contract_usd` (omitting it fails with `ERR_VALIDATION`, HTTP 400), and the return move from `AMENDMENT_PENDING` back to `EXECUTED` replaces `total_contract_usd` with that amendment value and increments the agreement's `amendment_count`, which starts at 0. From `EXECUTED` the agreement may also move to `DELIVERING` and then to terminal `FULFILLED`. Termination is permitted from `DRAFT` or from `EXECUTED`; in both cases, every procurement order of the agreement not yet in `DELIVERED` or `ACCEPTED` is cancelled, and the safe-harbor clawback cascade of §3.5 applies to any such order that had qualified.

Procurement orders are placed under a supply agreement with an `order_amount_usd`, a `safe_harbor_method` of `FIVE_PERCENT_COST` or `PHYSICAL_WORK`, and an `eligible_cost_basis_usd` against which the five-percent test will be measured. The parent agreement need not be executed at order-placement time — the execution gate is enforced later, at safe-harbor confirmation. The order enters in `PLACED` and tracks a `deposit_paid_usd` accumulator starting at 0.0. Deposits are paid through a deposit transition requiring a `deposit_amount_usd` that is present and greater than zero (otherwise `ERR_VALIDATION`): the first deposit moves the order from `PLACED` to `DEPOSIT_PAID`, and further deposits loop within `DEPOSIT_PAID`, each adding its amount into `deposit_paid_usd`.

Confirming safe harbor — moving the order from `DEPOSIT_PAID` to `SAFE_HARBOR_QUALIFIED` — is the temporal heart of procurement. Four gates apply. The logical clock must not have passed the order's `created_at` plus 183 days (otherwise `ERR_SAFE_HARBOR_WINDOW_LAPSED`, HTTP 422). The parent supply agreement must be in `EXECUTED`, `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` (otherwise `ERR_SUPPLY_AGREEMENT_NOT_EXECUTED`, HTTP 409). The project's tax credit qualification must not be `DISQUALIFIED` (otherwise `ERR_CREDIT_DISQUALIFIED`, HTTP 409). And the method-specific test must pass, evaluated on the single order being transitioned with no other orders consulted. Under the `FIVE_PERCENT_COST` method, the order qualifies if and only if its `deposit_paid_usd` is at least the five-percent threshold — the threshold being 5 percent of `eligible_cost_basis_usd` rounded half-up to 2 decimal places, with a deposit exactly equal to the threshold qualifying; falling short fails with `ERR_SAFE_HARBOR_TEST_FAILED` (HTTP 422), and any evidence URI is irrelevant to this variant. Under the `PHYSICAL_WORK` method, cost amounts are irrelevant and qualification turns entirely on the presence of a `physical_work_evidence_uri` in the transition payload — an order with zero deposit can qualify, while an order with a full deposit but no evidence cannot; a missing URI fails with `ERR_VALIDATION` (HTTP 400). A successful confirmation sets `safe_harbor_qualified` to true.

From `SAFE_HARBOR_QUALIFIED` the order moves to `DELIVERED` and then to terminal `ACCEPTED`. Cancellation is permitted from `PLACED`, `DEPOSIT_PAID`, or `SAFE_HARBOR_QUALIFIED`. Cancelling from the qualified state fires the two-link clawback cascade: first, the order's `safe_harbor_qualified` reverts to false, and if no other procurement order of the project remains in `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` and the project's tax credit qualification is in `SAFE_HARBOR_ESTABLISHED`, the qualification reverts to `NOT_ELIGIBLE`; second, that revert recomputes the project's `tax_credit_anchored` to false.

### 3.5. Tax Credit Qualification, Continuity, and the Credit Computation

The tax credit qualification is the compliance spine of the project. It is created automatically with the project in `NOT_ELIGIBLE`, records a `continuity_variant` — `FOUR_YEAR_SAFE_HARBOR` or `FACTS_AND_CIRCUMSTANCES` — that is pinned at establishment and immutable thereafter, and tracks the `safe_harbor_established_date`, the most recent `lapse_date`, and a `lapse_count` starting at 0.

A `TaxCounsel` establishes safe harbor — moving the qualification from `NOT_ELIGIBLE` to `SAFE_HARBOR_ESTABLISHED` — once at least one procurement order of the project is in `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` (otherwise `ERR_SAFE_HARBOR_NOT_QUALIFIED`, HTTP 409), and the transition payload must carry the `continuity_variant` (omitting it fails with `ERR_VALIDATION`, HTTP 400). Establishment stamps `safe_harbor_established_date` from the logical clock and sets the project's `tax_credit_anchored` to true.

Continuity is assessed on the transition into `CONTINUITY_MAINTAINED`, reachable from `SAFE_HARBOR_ESTABLISHED` and again from `CURED` after a cure. The assessment works over the project's `CERTIFIED` milestones of type `CONTINUOUS_WORK` only — planned, evidence-submitted, and rejected milestones are excluded — ordered by `work_date` ascending with ties broken by `created_at` ascending. Under the `FOUR_YEAR_SAFE_HARBOR` variant the assessment passes if and only if the logical clock is at or before the `safe_harbor_established_date` plus four years — a 1461-day window inclusive of one leap day — or the project itself already sits in `COMMERCIAL_OPERATION` or `OPERATIONAL`; internal work gaps are never examined under this variant. Under the `FACTS_AND_CIRCUMSTANCES` variant the calendar deadline is irrelevant: the assessment builds a date series consisting of the `safe_harbor_established_date`, then each certified continuous-work milestone's `work_date` in order, then the current logical clock reading, and passes if and only if every consecutive gap in that series is at most 365 days. The same work history and clock can therefore pass under one variant and lapse under the other. A failed assessment does not merely reject: the qualification auto-transitions into `CONTINUITY_LAPSED`, its `lapse_date` is stamped from the logical clock, its `lapse_count` increments by one, and the caller receives `ERR_CONTINUITY_LAPSED` (HTTP 409).

Cure from `CONTINUITY_LAPSED` requires two conditions. The logical clock must be at or before the `lapse_date` plus 90 days — a cure attempted after that window fails with `ERR_CURE_WINDOW_EXPIRED` (HTTP 422) and the failed attempt itself pushes the qualification into terminal `DISQUALIFIED`, which also sets the project's `tax_credit_anchored` to false and ends all further qualification for the project. And at least one `CERTIFIED` `CONTINUOUS_WORK` milestone of the project must carry a `work_date` on or after the `lapse_date`. A successful cure moves the qualification to `CURED`, from which continuity is assessed again as above.

Qualification into `QUALIFIED` is reachable from `CONTINUITY_MAINTAINED`, either by direct transition or by the COD cascade of §3.6, and requires the project to be in `COMMERCIAL_OPERATION` or `OPERATIONAL` (otherwise `ERR_INVALID_STATE`). At qualification the credit is computed. The rate starts at a 30.00 percent base. A 10.00 percent domestic content adder applies when the project's `domestic_content_certified` flag is true and at least one supply agreement of the project has its own `domestic_content_certified` true while in `EXECUTED`, `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` status. A further 10.00 percent energy community adder applies when the project's `energy_community_eligible` flag is true. The resulting rate is stored as `credit_rate_pct`. The eligible basis is the sum of `order_amount_usd` over the project's procurement orders in `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` status — orders still `PLACED` or `DEPOSIT_PAID`, and cancelled orders, contribute nothing. The `qualified_credit_usd` is the rate divided by 100 and multiplied by that basis, rounded half-up to 2 decimal places, and the project's `total_itc_credits_usd` is set to the same figure.

Two further reversions bound the machine. The clawback cascade of §3.4 can drop the qualification from `SAFE_HARBOR_ESTABLISHED` back to `NOT_ELIGIBLE` when the last safe-harbor-qualified order is cancelled and no `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` order of the project remains, clearing `tax_credit_anchored`. And the expired-cure path into `DISQUALIFIED` is terminal.

### 3.6. Construction Milestones, Evidence, and the COD Cascade

A `ConstructionManager` plans milestones under a project, each with a `milestone_type` — `FOUNDATION`, `ERECTION`, `ENERGIZATION`, `SUBSTANTIAL_COMPLETION`, `COMMERCIAL_OPERATION`, or `CONTINUOUS_WORK` — a `sequence_no` ordering key that is unique within the project, and a `planned_date`. The milestone enters in `PLANNED`. The manager later submits evidence, moving the milestone to `EVIDENCE_SUBMITTED`; the submission must carry both an `evidence_uri` and a `work_date` recording when the physical work occurred (omitting either fails with `ERR_MILESTONE_EVIDENCE_REQUIRED`, HTTP 400), and the server records the caller's `X-User-ID` as `submitted_by_user_id`. A milestone whose evidence was rejected may be resubmitted along the same path, replacing the `evidence_uri` and `work_date` and re-stamping `submitted_by_user_id`.

Certification belongs to `TaxCounsel`, never to the submitting manager. The certify call carries a `decision`. In either direction the certifier's `X-User-ID` must differ from the milestone's `submitted_by_user_id` — self-certification fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and the certifier's id is recorded as `certified_by_user_id`. Certification (`decision` of `CERTIFIED`) additionally requires that every other milestone of the same project with a `sequence_no` lower than this milestone's is already `CERTIFIED`, failing with `ERR_MILESTONE_OUT_OF_ORDER` (HTTP 409) when an earlier sequence number is still open; and for a milestone of type `COMMERCIAL_OPERATION`, the project must currently be in `COMMISSIONING`, failing with `ERR_COD_MILESTONE_PREREQUISITE` (HTTP 409) otherwise. Rejection (`decision` of `REJECTED`) carries the segregation check only. `CERTIFIED` is terminal for a milestone; `REJECTED` loops back through resubmission.

The project's own advance from `READY_FOR_CONSTRUCTION` to `UNDER_CONSTRUCTION` requires the tax credit qualification to be anchored — in `SAFE_HARBOR_ESTABLISHED`, `CONTINUITY_MAINTAINED`, `CURED`, or `QUALIFIED` — failing with `ERR_SAFE_HARBOR_NOT_QUALIFIED` when the qualification is `NOT_ELIGIBLE` and with `ERR_CREDIT_DISQUALIFIED` when it is `DISQUALIFIED`; the transition also recomputes the project's `tax_credit_anchored`. The advance from `UNDER_CONSTRUCTION` to `COMMISSIONING` requires that milestones of all four types `FOUNDATION`, `ERECTION`, `ENERGIZATION`, and `SUBSTANTIAL_COMPLETION` exist and are `CERTIFIED`, failing with `ERR_COD_MILESTONE_PREREQUISITE` otherwise.

The step from `COMMISSIONING` to `COMMERCIAL_OPERATION` is cascade-only: there is no direct project transition for it, and a direct attempt fails with `ERR_INVALID_STATE`. Instead, certifying the `COMMERCIAL_OPERATION` milestone while the project is in `COMMISSIONING` fires a four-way fan-out. The project itself moves to `COMMERCIAL_OPERATION` and its `cod_date` is stamped from the logical clock. A tax credit qualification sitting in `CONTINUITY_MAINTAINED` or `CURED` auto-transitions to `QUALIFIED`, recomputing `credit_rate_pct` and `qualified_credit_usd` per the credit computation of §3.5 and updating the project's `total_itc_credits_usd`. A debt facility sitting in `CONSTRUCTION_DRAWING` auto-transitions to `CONVERSION_PENDING`. And a tax equity partnership sitting in `FULLY_FUNDED` auto-transitions to `PRE_FLIP_OPERATING`.

Handoff to operations — the step from `COMMERCIAL_OPERATION` to `OPERATIONAL` — requires the payload to carry a `measured_availability_pct` (omitting it fails with `ERR_AVAILABILITY_MEASUREMENT_REQUIRED`, HTTP 400). At handoff, liquidated damages are assessed against the project's `availability_guarantee_pct`. The shortfall is the guarantee minus the measured figure. When the shortfall is zero or negative — including a measured availability exactly equal to the guarantee — the `availability_ld_usd` is 0.00. Otherwise the damages are the shortfall multiplied by 25,000 dollars per percentage point, rounded half-up to 2 decimal places, capped at 500,000.00 dollars.

Abandonment is available from any status other than `OPERATIONAL` (an attempt from `OPERATIONAL` fails with `ERR_INVALID_STATE`) and moves the project to terminal `ABANDONED` with a full teardown cascade: every non-terminal site control instrument of the project moves to `TERMINATED`; every non-terminal interconnection request moves to `WITHDRAWN`, each firing the queue reseat and upgrade re-allocation cascade of §3.2; every non-terminal offtake agreement moves to `TERMINATED`; every non-terminal supply agreement moves to `TERMINATED`; and every procurement order not in `ACCEPTED` moves to `CANCELLED`, with the safe-harbor clawback cascade applying to any order that had qualified.

### 3.7. Tax Equity Partnership, Ledger, and the Flip

A `TaxCounsel` structures a tax equity partnership under a project by naming the `investor_name`, the total `commitment_usd` of committed capital, and the investor's `target_irr_pct`. At most one partnership not in `DISSOLVED` may exist per project. The partnership enters in `STRUCTURING`, carrying two fixed share figures: an `investor_pre_flip_share_pct` of 99.00 and an `investor_post_flip_share_pct` of 5.00. Its `flip_date` is null until the flip occurs. Three computed aggregates summarize its ledger: `contributed_usd`, the sum of all `CONTRIBUTION` entries; `retained_cash_usd`, the `contributed_usd` minus the sum of all `DISTRIBUTION_INVESTOR` and `DISTRIBUTION_DEVELOPER` entries; and `investor_irr_pct`, computed as the sum of investor cash distributions plus investor credit allocations, divided by investor contributions, minus one, multiplied by 100, and rounded half-up to 2 decimal places — reading 0.00 when no contributions exist.

Executing the commitment — moving the partnership from `STRUCTURING` to `COMMITMENT_EXECUTED` — requires the project's tax credit qualification to be anchored in `SAFE_HARBOR_ESTABLISHED`, `CONTINUITY_MAINTAINED`, `CURED`, or `QUALIFIED` (otherwise `ERR_SAFE_HARBOR_NOT_QUALIFIED`, HTTP 409). Funding then proceeds through contributions posted by an `InvestorManager`, each carrying an `amount_usd` and the accounting `period_end_date`. A contribution is accepted only while the partnership is in `COMMITMENT_EXECUTED` or `FUNDING` (from any other status it fails with `ERR_INVALID_STATE`), and it may not push `contributed_usd` above the `commitment_usd` cap (otherwise `ERR_CONTRIBUTION_EXCEEDS_COMMITMENT`, HTTP 422). Each accepted contribution creates a `CONTRIBUTION` ledger entry and increments the partnership's `version` by 1. The first contribution auto-advances the partnership from `COMMITMENT_EXECUTED` to `FUNDING`, and the contribution that brings `contributed_usd` exactly equal to `commitment_usd` auto-advances it from `FUNDING` to `FULLY_FUNDED`. When the project later reaches commercial operation, the COD cascade moves a `FULLY_FUNDED` partnership into `PRE_FLIP_OPERATING`.

Distributions are run by a `TaxCounsel` while the partnership is in `PRE_FLIP_OPERATING` or `FLIPPED`, supplying an `amount_usd` and a `period_end_date`; the amount may not exceed `retained_cash_usd` (otherwise `ERR_DISTRIBUTION_EXCEEDS_CASH`, HTTP 422), and each distribution run increments the partnership's `version` by 1. The waterfall splits the cash between investor and developer at the investor share for the current stage — 99.00 percent before the flip, 5.00 percent after — with a pinned rounding order: the investor tier is rounded first, as the amount multiplied by the investor share percentage divided by 100, rounded half-up to 2 decimal places, and the developer tier takes the remainder of the amount. A credit tier runs alongside the cash tier only while unallocated credits remain: the unallocated credit is the project's `total_itc_credits_usd` minus the sum of all existing credit allocation entries, and when that remainder is positive, it is split at the same stage share with the same rounding order — investor tier rounded first, developer tier taking the remainder. A distribution therefore creates four ledger entries on the first run — a `DISTRIBUTION_INVESTOR`, a `DISTRIBUTION_DEVELOPER`, a `CREDIT_ALLOCATION_INVESTOR`, and a `CREDIT_ALLOCATION_DEVELOPER` — and two entries thereafter once credits are fully allocated. Across every run, the cumulative sum of investor credit allocations plus the cumulative sum of developer credit allocations always equals the project's `total_itc_credits_usd`. Every ledger entry records its `entry_type`, its computed `amount_usd` (distribution and credit amounts are computed by the waterfall and are never client-supplied per tier), and its `period_end_date`; entries are immutable, and the entry list may be filtered by `entry_type`.

The flip — moving the partnership from `PRE_FLIP_OPERATING` to `FLIPPED` — is the OCC-guarded election of §2.7: the request must carry `expected_partnership_version` matching the partnership's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The flip also carries an IRR gate evaluated against a pinned, non-circular order over the current ledger before any flip: first, cumulative contributions are summed from the `CONTRIBUTION` entries; second, the cumulative investor return is summed from the `DISTRIBUTION_INVESTOR` and `CREDIT_ALLOCATION_INVESTOR` entries; third, the `investor_irr_pct` snapshot is computed from those two sums exactly as defined above — 0.00 when contributions are zero — and this snapshot never includes hypothetical post-flip distributions; fourth, the flip is permitted if and only if that snapshot is at least the `target_irr_pct`, failing with `ERR_TARGET_IRR_NOT_ACHIEVED` (HTTP 409) below target. Only after a successful flip do subsequent distribution runs switch to the post-flip shares. A successful flip stamps `flip_date` from the logical clock. A `FLIPPED` partnership may finally be dissolved into terminal `DISSOLVED` without preconditions.

### 3.8. Construction Financing and Term Conversion

A `LenderAgent` commits a construction debt facility under a project, supplying the lender's `commitment_usd`, the annual `interest_rate_pct`, and the `projected_cfads_usd` — the projected annual cash flow available for debt service. At most one facility not in `RETIRED` may exist per project. The facility enters in `COMMITMENT`, carrying a fixed `min_dscr` of 1.30 and a `drawn_usd` accumulator starting at 0.0.

Draws move the facility from `COMMITMENT` into `CONSTRUCTION_DRAWING` and then loop within `CONSTRUCTION_DRAWING`. Each draw requires a `draw_amount_usd` that is present and greater than zero, and the draw must keep the running total within commitment — the existing `drawn_usd` plus the new `draw_amount_usd` must not exceed `commitment_usd`, failing with `ERR_DRAW_EXCEEDS_COMMITMENT` (HTTP 422) otherwise. Each accepted draw adds its amount into `drawn_usd`. When the project reaches commercial operation, the COD cascade moves a facility in `CONSTRUCTION_DRAWING` to `CONVERSION_PENDING`.

Conversion to term repayment is gated on debt service coverage and on sizing. The coverage check divides the `projected_cfads_usd` by the annual debt service — the `drawn_usd` multiplied by the `interest_rate_pct` divided by 100 — and requires the ratio to be at least 1.30, inclusive; a ratio below the minimum fails with `ERR_DSCR_BELOW_MINIMUM` (HTTP 422), and a facility with nothing drawn fails with `ERR_VALIDATION` (HTTP 400). On a successful conversion the `term_debt_usd` is sized as the smallest of three figures: the `commitment_usd`, the `drawn_usd`, and 80 percent of the eligible project cost rounded half-up to 2 decimal places — where the eligible project cost is the sum of `order_amount_usd` over the project's procurement orders in `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` status. From `TERM_REPAYMENT` the facility may be retired into terminal `RETIRED`. Default is reachable from `CONSTRUCTION_DRAWING` or from `TERM_REPAYMENT` and moves the facility to terminal `DEFAULTED`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201 on creation; modifications, transitions, and action-style operations return HTTP 200. All endpoints are mounted under the `/api` prefix. Request and response bodies are not repeated here — each operation's payload fields, side effects, and error conditions are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock (test-driving endpoint); before any call the clock reads exactly 2026-09-01T00:00:00Z and never falls back to wall-clock time | PlatformAdmin |
| POST | /api/projects | Create a Project; auto-creates its TaxCreditQualification in NOT_ELIGIBLE | DeveloperAdmin |
| GET | /api/projects | List projects with pagination and optional `status` filter | DeveloperAdmin, OriginationManager, ProcurementLead, ConstructionManager, TaxCounsel, InvestorManager, LenderAgent, Auditor, PlatformAdmin |
| GET | /api/projects/{id} | Get a project | DeveloperAdmin, OriginationManager, ProcurementLead, ConstructionManager, TaxCounsel, InvestorManager, LenderAgent, Auditor, PlatformAdmin |
| POST | /api/projects/{id}/transitions | Advance/revert project lifecycle per the Project state machine (payload `to`, optional `measured_availability_pct`); COD is cascade-only | DeveloperAdmin |
| POST | /api/projects/{id}/site-control-instruments | Create a site control instrument (land option or easement) in DRAFT | DeveloperAdmin |
| GET | /api/projects/{id}/site-control-instruments | List a project's site control instruments | DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| GET | /api/site-control-instruments/{id} | Get a site control instrument | DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| POST | /api/site-control-instruments/{id}/transitions | Execute / exercise / record / terminate a site control instrument (payload `to`) | DeveloperAdmin |
| POST | /api/projects/{id}/interconnection-requests | Submit an interconnection request; `queue_position` assigned as max active position in cluster + 1 (or 1) | OriginationManager |
| GET | /api/projects/{id}/interconnection-requests | List a project's interconnection requests | OriginationManager, DeveloperAdmin, Auditor, PlatformAdmin |
| GET | /api/interconnection-requests/{id} | Get an interconnection request | OriginationManager, DeveloperAdmin, Auditor, PlatformAdmin |
| POST | /api/interconnection-requests/{id}/transitions | Advance queue phase or withdraw (payload `to`); withdrawal reseats the cluster and re-allocates upgrade shares | OriginationManager |
| POST | /api/interconnection-requests/{id}/allocate-upgrade-costs | Allocate a cluster-wide interconnection upgrade total across non-WITHDRAWN cluster requests, pro-rata by `requested_capacity_mw` | PlatformAdmin |
| POST | /api/interconnection-requests/{id}/studies | Scope a study; window conflicts on the same cluster use closed intervals plus a 5-calendar-day buffer | OriginationManager |
| GET | /api/interconnection-requests/{id}/studies | List studies of an interconnection request | OriginationManager, DeveloperAdmin, Auditor, PlatformAdmin |
| GET | /api/interconnection-studies/{id} | Get a study | OriginationManager, DeveloperAdmin, Auditor, PlatformAdmin |
| POST | /api/interconnection-studies/{id}/transitions | Advance study lifecycle (payload `to`); DEFICIENT to IN_PROGRESS is the rework loop | OriginationManager |
| POST | /api/projects/{id}/offtake-agreements | Open offtake (PPA) negotiation; OCC-guarded on project version via `expected_project_version` | OriginationManager |
| GET | /api/projects/{id}/offtake-agreements | List a project's offtake agreements | OriginationManager, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| GET | /api/offtake-agreements/{id} | Get an offtake agreement | OriginationManager, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| POST | /api/offtake-agreements/{id}/transitions | Counter / execute / activate / terminate a PPA (payload `to`, optional `base_price_usd_mwh`); NEGOTIATING to COUNTERED and back is the negotiation cycle | OriginationManager |
| POST | /api/projects/{id}/supply-agreements | Create a turbine/module supply agreement in DRAFT | ProcurementLead |
| GET | /api/projects/{id}/supply-agreements | List a project's supply agreements | ProcurementLead, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| GET | /api/supply-agreements/{id} | Get a supply agreement | ProcurementLead, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| POST | /api/supply-agreements/{id}/transitions | Execute / amend / deliver / fulfill / terminate (payload `to`, optional `amendment_total_contract_usd`); EXECUTED to AMENDMENT_PENDING to EXECUTED is the amendment cycle | ProcurementLead |
| POST | /api/supply-agreements/{id}/procurement-orders | Place a procurement order under a supply agreement (agreement need not be EXECUTED yet; safe-harbor confirm enforces that later) | ProcurementLead |
| GET | /api/supply-agreements/{id}/procurement-orders | List a supply agreement's procurement orders | ProcurementLead, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| GET | /api/procurement-orders/{id} | Get a procurement order | ProcurementLead, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| POST | /api/procurement-orders/{id}/transitions | Deposit / confirm safe harbor / deliver / accept / cancel (payload `to`, optional `deposit_amount_usd`, optional `physical_work_evidence_uri`); SAFE_HARBOR_QUALIFIED to CANCELLED fires the clawback cascade | ProcurementLead |
| POST | /api/projects/{id}/construction-milestones | Plan a construction or continuous-work milestone | ConstructionManager |
| GET | /api/projects/{id}/construction-milestones | List a project's milestones | ConstructionManager, TaxCounsel, DeveloperAdmin, Auditor, PlatformAdmin |
| GET | /api/construction-milestones/{id} | Get a milestone | ConstructionManager, TaxCounsel, DeveloperAdmin, Auditor, PlatformAdmin |
| POST | /api/construction-milestones/{id}/submit-evidence | Submit work evidence; records `submitted_by_user_id` from X-User-ID (segregation-of-duties input) | ConstructionManager |
| POST | /api/construction-milestones/{id}/certify | Certify or reject evidence (payload `decision`); certifier must differ from submitter; certifying the COMMERCIAL_OPERATION milestone fires the COD cascade | TaxCounsel |
| GET | /api/projects/{id}/tax-credit-qualifications | List a project's tax credit qualification (array of 0-1) | TaxCounsel, DeveloperAdmin, InvestorManager, Auditor, PlatformAdmin |
| GET | /api/tax-credit-qualifications/{id} | Get a tax credit qualification | TaxCounsel, DeveloperAdmin, InvestorManager, Auditor, PlatformAdmin |
| POST | /api/tax-credit-qualifications/{id}/transitions | Establish safe harbor / assess continuity / cure / qualify (payload `to`, optional `continuity_variant`) | TaxCounsel |
| POST | /api/projects/{id}/tax-equity-partnerships | Structure a tax equity partnership | TaxCounsel |
| GET | /api/projects/{id}/tax-equity-partnerships | List a project's tax equity partnerships | TaxCounsel, InvestorManager, DeveloperAdmin, Auditor, PlatformAdmin |
| GET | /api/tax-equity-partnerships/{id} | Get a partnership (computed `investor_irr_pct`, `contributed_usd`, `retained_cash_usd`) | TaxCounsel, InvestorManager, DeveloperAdmin, Auditor, PlatformAdmin |
| POST | /api/tax-equity-partnerships/{id}/transitions | Execute commitment / elect flip (OCC via `expected_partnership_version` plus the IRR gate) / dissolve (payload `to`) | TaxCounsel |
| POST | /api/tax-equity-partnerships/{id}/contributions | Post an investor capital contribution; requires partnership in COMMITMENT_EXECUTED or FUNDING; auto-advances FUNDING and FULLY_FUNDED | InvestorManager |
| POST | /api/tax-equity-partnerships/{id}/distributions | Run the cash distribution + credit allocation waterfall | TaxCounsel |
| GET | /api/tax-equity-partnerships/{id}/ledger-entries | List a partnership's ledger entries with optional `entry_type` filter | TaxCounsel, InvestorManager, DeveloperAdmin, Auditor, PlatformAdmin |
| GET | /api/partnership-ledger-entries/{id} | Get a ledger entry (immutable; no update endpoint) | TaxCounsel, InvestorManager, DeveloperAdmin, Auditor, PlatformAdmin |
| POST | /api/projects/{id}/debt-facilities | Commit a construction debt facility | LenderAgent |
| GET | /api/projects/{id}/debt-facilities | List a project's debt facilities | LenderAgent, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| GET | /api/debt-facilities/{id} | Get a debt facility | LenderAgent, DeveloperAdmin, TaxCounsel, Auditor, PlatformAdmin |
| POST | /api/debt-facilities/{id}/transitions | Draw construction funds / convert to term debt at COD (DSCR-gated) / retire / default (payload `to`, optional `draw_amount_usd`) | LenderAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are specified where the guarded rule is described in §2 and §3; this table is the reference index of identifiers to status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_MILESTONE_EVIDENCE_REQUIRED | 400 |
| ERR_MILESTONE_OUT_OF_ORDER | 409 |
| ERR_COD_MILESTONE_PREREQUISITE | 409 |
| ERR_PARCEL_OVERLAP | 409 |
| ERR_OPTION_WINDOW_LAPSED | 409 |
| ERR_STUDY_WINDOW_CONFLICT | 409 |
| ERR_PHASE_STUDY_NOT_ACCEPTED | 409 |
| ERR_UPGRADE_ALLOCATION_REQUIRED | 409 |
| ERR_ACTIVE_OFFTAKE_EXISTS | 409 |
| ERR_PRICE_FLOOR_BREACH | 422 |
| ERR_OFFTAKE_REQUIRED | 409 |
| ERR_INTERCONNECTION_NOT_EXECUTED | 409 |
| ERR_SUPPLY_AGREEMENT_NOT_EXECUTED | 409 |
| ERR_SAFE_HARBOR_WINDOW_LAPSED | 422 |
| ERR_SAFE_HARBOR_TEST_FAILED | 422 |
| ERR_SAFE_HARBOR_NOT_QUALIFIED | 409 |
| ERR_CONTINUITY_LAPSED | 409 |
| ERR_CURE_WINDOW_EXPIRED | 422 |
| ERR_CREDIT_DISQUALIFIED | 409 |
| ERR_CONTRIBUTION_EXCEEDS_COMMITMENT | 422 |
| ERR_DISTRIBUTION_EXCEEDS_CASH | 422 |
| ERR_TARGET_IRR_NOT_ACHIEVED | 409 |
| ERR_DSCR_BELOW_MINIMUM | 422 |
| ERR_DRAW_EXCEEDS_COMMITMENT | 422 |
| ERR_AVAILABILITY_MEASUREMENT_REQUIRED | 400 |

