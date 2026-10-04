# Single-Advisor Branch Office API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Single-Advisor Branch Office API, the operational backbone for a retail wealth-management network built around the one-advisor storefront model. Each branch office is run by a single financial advisor, supported by a dedicated branch office administrator, and sited deliberately in smaller communities where the advisor builds the practice household by household through door-knocking in an assigned territory. The network's economics are distinctive: the branch is a profit center in its own right, bearing its own lease, equipment, and administrator payroll charges, and the advisor participates directly in the branch's net profit through a tiered profit-sharing calculation rather than drawing a pure commission split.

The API governs the full lifecycle implied by that model. It tracks an advisor from candidate registration through a training pipeline with production-goal milestones, validation, branch assignment, active practice, and eventually retirement — at which point the practice's goodwill is transferred to a successor through a structured, escrow-backed negotiation. It manages the branch itself as a parallel stateful entity: site selection and lease signing, staffing, opening, suspension, and closure. It keeps the books, closing monthly financial periods, allocating branch charges in a pinned waterfall order, computing the advisor's profit share in provisional and final variants, and carrying deficits forward into the next period. And it enforces the compliance perimeter of a limited product shelf, where solicitation of anything beyond plain-vanilla products requires principal sign-off under strict segregation of duties.

Because branch profitability drives the advisor's paycheck and goodwill valuation drives retirement outcomes, the system's ledger semantics — rounding order, evaluation order, window boundaries, and stale-write protection — are specified here with unusual care. Implementers should treat every calculation narrative in §3 as normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which they are acting. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. Once authenticated, a role that attempts an operation outside its grant is rejected with `ERR_UNAUTHORIZED`.

Four roles exist, spelled exactly as follows:

- `HomeOfficeAdmin` — the home office operations administrator. This is the operational superset role: it creates advisors, territories, branches, administrators, production records, financial periods, and charges; drives branch lifecycle transitions (approve-site, open, suspend, reinstate, close); assigns advisors and administrators to branches; enrolls candidates into training and evaluates milestones; creates, completes, and cancels goodwill transfers; reverses production records and charges; and sets the logical clock. When `X-User-Role` is `HomeOfficeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any resource's `id`.
- `Advisor` — a financial advisor. When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting `Advisor` record; ownership checks on any resource that references an advisor (retirement declarations, milestone submissions, solicitation requests, goodwill negotiations, door-knock contacts) compare the resource's advisor foreign key to `X-User-ID`.
- `BranchAdministrator` — a branch office administrator, a read-only operational support identity. When `X-User-Role` is `BranchAdministrator`, `X-User-ID` is the `id` of the acting `BranchOfficeAdministrator` record, and ownership checks compare the resource's administrator reference to `X-User-ID`. Administrators may read their own record and their employing branch but hold no write operations.
- `CompliancePrincipal` — the compliance principal, who creates and approves product shelf entries and approves or denies solicitation requests. When `X-User-Role` is `CompliancePrincipal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It may, however, be recorded for audit — for example, as `decided_by_role` context on a decided `SolicitationRequest` — without ever being compared to an entity `id`.

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items are skipped and defaults to 0. Requests to unknown paths, and requests whose HTTP method is not defined for a known path, are rejected with `ERR_NOT_FOUND` (HTTP 404). All list endpoints sort by `created_at` ascending (with `id` ascending as the tiebreaker) unless stated otherwise. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties and Optimistic Concurrency Control

Most top-level resources — Advisor, Territory, Branch, BranchOfficeAdministrator, TrainingProgram, LeaseAgreement, BranchFinancialPeriod, BranchCharge, GoodwillTransfer, and SolicitationRequest — share a standard property set: an `id` that is a server-minted UUID with no type prefix; `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits; and an integer `version` that starts at 1 and increments by exactly one on every mutation of the resource. Three resources are deliberately leaner: DoorKnockContact, MilestoneEvaluation, and ProductShelfEntry carry only `id` and `created_at` — they have no `updated_at` and no `version`, because they are either append-only or transition only through dedicated endpoints.

Two write paths are guarded by optimistic concurrency control, and on those two paths the version check is mandatory, not optional. Updating a branch's book attributes requires the request to carry `expected_branch_version` equal to the branch's current `version`; the field is mandatory — a request omitting it, or carrying a non-integer value, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and if another writer has since updated the branch — advancing its version and possibly recomputing its tier — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Input-shape validation of the book attributes runs before the version check. Submitting a counter-offer against a goodwill transfer requires `expected_transfer_version` equal to the transfer's current `version`; if the other party has countered since the client last read the negotiation (advancing both `negotiation_round` and `version`), the counter-offer is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not accept a version field at all. Where `version` is exposed, every mutation of a resource — including the cascaded side effects in §3 — increments that resource's `version` by exactly one and refreshes its `updated_at`.

### 2.5. Nested Resource Retrieval and Validation Order

For any endpoint whose path nests one resource beneath another, identifiers resolve left to right: the server first confirms the parent in the path exists, then the child within that parent's scope, and only then evaluates business rules. A missing identifier anywhere in the chain yields `ERR_NOT_FOUND` for the first unresolvable segment. The same discipline applies to foreign keys in request bodies — an unresolvable reference is `ERR_NOT_FOUND`, raised before state or business checks run.

More generally, every request passes through the validation pipeline in a fixed order. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence resolution (`ERR_NOT_FOUND`), then state-transition legality (`ERR_INVALID_STATE`), then the domain's business-safety, business-constraint, temporal, referential, fiscal, and input-shape rules in the priority order narrated in §3, with `ERR_INVALID_REQUEST` (malformed payloads, invalid enums, out-of-range numbers) acting as the final backstop before the stale-version check and remaining temporal and staffing rules are evaluated. Where several rules could reject the same request, the one named earlier in this pipeline — and, within §3, the one narrated first for that operation — determines which error the caller sees.

### 2.6. Monetary Precision and the Two Rounding Orders

All monetary amounts are integers of whole cents (`*_cents` fields); dollar-denominated inputs such as `assets_under_care_dollars` are whole dollars. Two rounding disciplines run through the system and must not be confused. First, wherever a rate is applied to a money amount — an advisor's payout on a production record, a valuation multiple on trailing revenue, a profit-share tier rate — the multiplication is rounded half-up to whole cents. Second, for multi-component sums, the rounding order is pinned: each component is rounded half-up individually and only then are the rounded components summed. The system never sums unrounded products and rounds the total. This per-record, per-tier rounding discipline is what makes the training-milestone sum and the advisor profit share reproducible from independent implementations.

### 2.7. The Logical Clock

The server maintains a logical clock, distinct from wall-clock time. At startup the clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time; it advances only when a `HomeOfficeAdmin` sets it to a supplied `to_iso8601` instant through the admin-only clock capability — including setting it backward, which is permitted and does not by itself resurrect or refund previously expired transfers. All server-generated timestamps (`created_at`, `updated_at`, stamped transitions, and response metadata) read the logical clock, never wall-clock time. The logical clock drives two time-sensitive behaviors: a financial period becomes closable only when the clock has reached the period's end, and goodwill offers expire once the clock has reached thirty days from offer creation — the boundary is inclusive — without acceptance. Every clock-set performs that expiry sweep as a side effect, and the clock endpoint responds with an empty data object.

### 2.8. Branch P&L Integrity

Each branch keeps its own books through a sequence of `BranchFinancialPeriod` records. Periods for one branch cover half-open intervals — the start is inclusive, the end exclusive — and must never overlap. Within a period, gross revenue is the sum of the branch advisor's posted production lines whose `posted_at` falls inside the period window, and total charges are the sum of posted, non-reversed `BranchCharge` amounts posted to the period. Charges apply in a pinned waterfall order: any `DEFICIT_CARRYOVER` from a prior period first, then `LEASE_RENT`, then `BOA_PAYROLL`, then `EQUIPMENT`; within one charge type, charges apply in the order they were created, never by identifier. A period that closes in the red carries its deficit forward: the absolute value of the negative net becomes a `DEFICIT_CARRYOVER` charge on the branch's next open period — the open period with the earliest `period_start` — so losses are recovered before the advisor shares in future profits. Once a period is finalized its books freeze — no charge may post to a finalized period, and attempts are rejected with `ERR_PERIOD_FINALIZED` — which guarantees the final advisor share never drifts.

### 2.9. Single-Advisor and Single-Administrator Staffing Invariants

The one-advisor model is enforced as a hard invariant: a branch may host at most one advisor whose status is anything other than `RETIRED` or `TERMINATED`, and symmetrically a branch may have at most one `ACTIVE` administrator, with each administrator serving at most one branch. Staffing is tracked on the branch as its own dimension, `staffing_status`, which moves independently of the branch's `operating_status`: a branch is `UNSTAFFED`, then `ADVISOR_ASSIGNED` once an advisor is attached, then `FULLY_STAFFED` only when both an advisor is assigned and an administrator is `ACTIVE`, and it enters `SUCCESSION_PENDING` while its practicing advisor is retiring. `staffing_status` is recomputed from current advisor and administrator presence on every staffing-relevant event — advisor assignment or removal, retirement declaration or rescission, administrator assignment, leave, return, or release, branch close, and succession completion — rather than tracked as an independent flag. Opening or reinstating a branch requires `FULLY_STAFFED`; a request made in any other staffing state is rejected with `ERR_BRANCH_NOT_FULLY_STAFFED`.

## 3. Business Logic & Workflows

### 3.1. Recruiting, Training, and Validating a New Advisor

The advisor pipeline begins when a `HomeOfficeAdmin` registers a candidate with a `full_name`, an `email`, and a `hire_date` marking the day the advisor entered the training pipeline. The new record starts life with `status` set to `CANDIDATE`, `branch_id` null, `predecessor_advisor_id` null, and `cumulative_commissions_cents` at zero. Advisor emails are unique across the network (compared as exact strings); registering a duplicate address is rejected with `ERR_DUPLICATE`. The `hire_date` is an ISO 8601 datetime.

Enrollment into training is a home-office action on a `CANDIDATE` advisor that supplies the new `TrainingProgram`'s `goal_cents` — the cumulative production goal, which must be a positive number of cents — and its `start_date`, the program's day zero. Enrollment flips the advisor `CANDIDATE → TRAINEE` and creates the program in `ACTIVE` status. An advisor may have at most one non-terminal training program at a time, where non-terminal means `ACTIVE`, `MILESTONE_PENDING`, or `REMEDIATION` — `COMPLETED` and `FAILED` are terminal. The enrollment response is the created `TrainingProgram` object (201).

From there the trainee builds production and, when ready, submits for a milestone — allowed only by the program's own advisor and only while the program is `ACTIVE` or in `REMEDIATION` — moving the program to `MILESTONE_PENDING`. A `HomeOfficeAdmin` then evaluates the pending milestone, supplying a `window_end`. The evaluation creates a `MilestoneEvaluation` whose `training_program_id` links the evaluation back to the program under assessment and whose `production_cents` is the sum of the trainee's `commissions_cents` across all `POSTED` production records with `posted_at` on or after the program's `start_date` and on or before `window_end` — the window is closed at both ends. Each production record already carries its own per-record rounded `commissions_cents`, and the milestone simply sums those rounded values; it does not re-round the gross sum. The `outcome` is `PASS` when `production_cents` reaches at least `goal_cents` — the boundary is inclusive, so production exactly equal to the goal passes — and `FAIL` otherwise. An administrator may force an outcome by supplying `force_outcome` (one of `PASS` or `FAIL`; anything else is `ERR_INVALID_REQUEST`), but forcing `PASS` when the computed production falls short of the goal is rejected with `ERR_GOAL_NOT_MET`. Forcing `FAIL` is always accepted. The evaluation endpoint returns the created `MilestoneEvaluation` (201).

A passing evaluation completes the program (`MILESTONE_PENDING → COMPLETED`) and validates the advisor (`TRAINEE → VALIDATED`); the advisor's `cumulative_commissions_cents` is not recomputed by the transition. A failing evaluation drops the program into `REMEDIATION` while the advisor remains a `TRAINEE`, and the remediation loop permits the advisor to submit again from `REMEDIATION` back to `MILESTONE_PENDING`. The loop terminates harshly: if a milestone evaluation fails and an earlier `FAIL` evaluation already exists for the same program — a second failing cycle — the program moves `MILESTONE_PENDING → FAILED` into the terminal `FAILED` status and the advisor is terminated outright (`TRAINEE → TERMINATED`).

### 3.2. Territories and the Door-Knocking Discipline

Territory creation takes a `community_name` and a `household_capacity`, the maximum number of non-archived door-knock contacts the territory may hold, which must be at least one. A new territory is `OPEN` with no assignment. Assigning a territory to an advisor supplies an `advisor_id`, an `assignment_start`, and optionally an `assignment_end`; the current assignment interval is half-open — the start is inclusive and the end exclusive — and an omitted end leaves the interval open-ended. Assignment sets `assigned_advisor_id`, `assignment_start`, and `assignment_end` and moves the territory `OPEN → ASSIGNED`. When an advisor's branch link ends — through termination, branch closure, or reassignment — the assignment is released automatically: `assigned_advisor_id` clears, `assignment_end` is stamped with the release instant, and the territory returns to `OPEN`. An unassigned (`OPEN`) territory may be retired permanently, moving to `RETIRED`.

Assignment is defined for a territory that is `OPEN` or already `ASSIGNED`; assigning a `RETIRED` territory is rejected with `ERR_INVALID_STATE`, and an explicit assignment replaces the current one outright (the interval overlap rule below governs whether the new interval may intersect the old). An explicit `assignment_end`, when supplied, must be strictly after `assignment_start`, otherwise `ERR_INVALID_REQUEST`.

Territory intervals must not collide: a new assignment whose half-open interval intersects the territory's current interval is rejected with `ERR_TERRITORY_OVERLAP`. Adjacency is allowed — a new assignment beginning exactly at the moment the existing interval ends does not overlap, because the existing end is exclusive. When one of the two intervals is open-ended (no end), the intervals overlap unless the closed interval ends at or before the open interval's start.

While holding a territory, the advisor logs door-knock contacts against it. Each contact carries the `territory_id`, a `household_address`, a `contact_outcome` of `NO_ANSWER`, `PITCHED`, `APPOINTMENT_SET`, or `CLIENT_CONVERTED`, and a `contacted_at` timestamp. Two guards apply at logging time, evaluated in this order: capacity first, then window. If the count of non-archived contacts in the territory already equals `household_capacity`, the registration is rejected with `ERR_TERRITORY_CAPACITY`. If `contacted_at` falls outside the current assignment interval — before `assignment_start`, or at or after `assignment_end` when an end is set — the contact is rejected with `ERR_CONTACT_OUTSIDE_WINDOW`; a territory with no current assignment (not `ASSIGNED`, or with no `assignment_start`) has no valid window and rejects every contact with the same error. A `household_address` may appear only once among a territory's non-archived contacts; a repeat address is rejected with `ERR_DUPLICATE`. Contacts support soft deletion through the `archived` flag, which defaults to false; archived contacts do not count against capacity, and contact listings exclude them unless the caller passes `include_archived` set to true. The contact-logging endpoint does not verify that the acting advisor is the territory's assigned advisor — any `Advisor` session may log a contact in any territory whose capacity and window guards pass.

### 3.3. Siting, Leasing, Staffing, and Opening a Branch

A branch is proposed with a `community_name`, a `site_address`, and the `territory_id` of the territory it will serve. It begins `PROPOSED` on the operating dimension and `UNSTAFFED` on the staffing dimension, with `household_count` and `assets_under_care_dollars` both at zero; its `tier_score` and `service_tier` are computed at creation and begin at 0 and `TIER_1` (§3.6). Site approval is the pivotal step: a `HomeOfficeAdmin` approves the site by supplying the lease terms — `monthly_rent_cents`, `term_start`, and `term_end` — which creates a `SIGNED` `LeaseAgreement` for the branch and moves the branch `PROPOSED → SITE_APPROVED`. Approval requires the branch to be `PROPOSED`, requires `territory_id` to be set with a territory that is not `RETIRED`, and is subject to the lease-overlap rule: a branch may not sign a lease whose closed occupancy interval intersects another `SIGNED` lease at the same site address. Lease intervals are closed — both `term_start` and `term_end` are inclusive, with `term_end` on or after `term_start` — so unlike territory assignments, adjacency conflicts: a new lease starting the day after an existing lease's last day still touches the boundary, and the request is rejected with `ERR_LEASE_OVERLAP`. `monthly_rent_cents` must be a positive integer. The overlap scan compares against `SIGNED` leases of other branches sharing the same `site_address`, matched as an exact string; the approve-site response is the updated branch. Leases live through `DRAFT`, `SIGNED`, `EXPIRED`, and `TERMINATED` states.

Staffing proceeds in parallel. A validated advisor is assigned to a branch in the `SITE_APPROVED` or `OPEN` operating state, provided three conditions hold — the advisor is `VALIDATED` (otherwise `ERR_ADVISOR_NOT_VALIDATED`), the branch has no other advisor whose status is neither `RETIRED` nor `TERMINATED` (otherwise `ERR_BRANCH_OCCUPIED`), and the branch's territory is either `OPEN` or already assigned to this advisor — a territory `ASSIGNED` to a different advisor rejects with `ERR_TERRITORY_OVERLAP`, and a `RETIRED` territory rejects with `ERR_INVALID_STATE`. Assignment moves the advisor `VALIDATED → PRACTICING`, sets the advisor's `branch_id`, moves the branch to `ADVISOR_ASSIGNED` (or directly to `FULLY_STAFFED` if an administrator is already `ACTIVE`), and takes the branch's territory under the advisor's door-knocking rights: `assigned_advisor_id` is set, `assignment_start` is stamped to the assignment instant, `assignment_end` is cleared, and the territory becomes `ASSIGNED`. The assign-branch response is the updated advisor object.

Branch office administrators are hired with a `full_name`, a unique `email`, and a positive `monthly_salary_cents` that the employing branch will bear as payroll. A new administrator is `HIRED` and unassigned. Assigning an administrator to a branch names the hire through `administrator_id` and requires the administrator to be `HIRED` and the branch to have no `ACTIVE` administrator — a second active assignment is rejected with `ERR_BOA_ALREADY_ASSIGNED` — and moves the administrator `HIRED → ACTIVE` with `branch_id` set; if an advisor is already assigned, the branch becomes `FULLY_STAFFED`. The branch may be in any operating state; the assign-administrator response is the updated administrator object. Administrators may be placed on leave (`ACTIVE → ON_LEAVE`), which degrades a staffed branch back to `ADVISOR_ASSIGNED` while an advisor remains, and may return from leave (`ON_LEAVE → ACTIVE`), restoring `FULLY_STAFFED` when an advisor is present. Release from either `ACTIVE` or `ON_LEAVE` moves the administrator to the terminal `RELEASED` state and clears `branch_id`, degrading the branch's staffing accordingly.

Only a `FULLY_STAFFED` branch may open: the open action moves a `SITE_APPROVED` branch to `OPEN` and, as a side effect, creates the branch's first `OPEN` financial period covering the current calendar month — the half-open interval from the first instant of the logical clock's current month to the first instant of the following month — with all aggregates zeroed. An open branch may be suspended (`OPEN → SUSPENDED`); while suspended, solicitation requests already submitted by the branch's advisor stay `SUBMITTED` but cannot be approved. Reinstatement (`SUSPENDED → OPEN`) again requires `FULLY_STAFFED`. Closing is terminal and available only from `SUSPENDED`: it requires every financial period of the branch to be `FINALIZED` — none may remain `OPEN` or `CLOSED` — and no goodwill transfer on the branch may be in `OFFERED`, `NEGOTIATING`, or `ACCEPTED` status, otherwise the close is rejected with `ERR_TRANSFER_ACTIVE`. A close cascades: the branch's administrator is released with `branch_id` cleared, the `SIGNED` lease is terminated, and the territory is released back to `OPEN`. The close may also release the assignment of an advisor who is still practicing or retiring; it always releases the branch's administrator, so staffing is recomputed afterward.

Throughout its life the branch's book attributes — `household_count` and `assets_under_care_dollars`, each an integer of zero or more — are updated through the version-guarded branch update described in §2.4. Every such update increments the branch's `version` and triggers the service-tier recomputation described in §3.6.

### 3.4. Production Posting and the Advisor's Cumulative Book

Production is the raw material of both training milestones and branch revenue. A `HomeOfficeAdmin` posts a `ProductionRecord` with the `advisor_id`, a positive `gross_commission_cents`, a `payout_rate`, and a `posted_at` timestamp that determines which period and which milestone windows the record feeds. The payout rate is the advisor's share fraction, strictly greater than zero and at most one. The record's `commissions_cents` is computed at posting time as the gross commission multiplied by the payout rate, rounded half-up to whole cents — the rounding is pinned to the individual record, so downstream sums (milestones, revenue aggregates) always add already-rounded per-record values. A posted record is `POSTED`; reversal flips it to `REVERSED`, and a record that is not `POSTED` cannot be reversed (`ERR_INVALID_STATE`). Both posting and reversal recompute the advisor's `cumulative_commissions_cents`, which is always the sum of `commissions_cents` across that advisor's `POSTED` records since `hire_date` — the `hire_date` boundary is inclusive, and reversed records drop out of the cumulative total. Posting requires no particular advisor status: a record may be posted for any existing advisor.

### 3.5. Closing the Books: Periods, Charges, and the Deficit Carryforward

Beyond the first period created when a branch opens, a `HomeOfficeAdmin` opens further periods by supplying `branch_id`, `period_start`, and `period_end`; a branch's periods never overlap — adjacency is allowed — with each covering the half-open interval from its inclusive start to its exclusive end, and `period_end` strictly after `period_start`. A new period is `OPEN` with all aggregates at zero; the branch need not be in any particular operating state.

Charges post to a specific period of a specific branch. Posting supplies `branch_id`, the target period via the path — each charge also records that target as its `period_id`, and the named branch must own that period or the request is `ERR_NOT_FOUND` — a `charge_type` of `LEASE_RENT`, `BOA_PAYROLL`, `EQUIPMENT`, or `DEFICIT_CARRYOVER`, and a positive `amount_cents`. Posting a charge recomputes the period's aggregates while the period is `OPEN` or `CLOSED`; reversing a charge recomputes them only while the period is `OPEN` — the provisional snapshot taken at close stays frozen through a post-close reversal, and the correction surfaces through the final variant at finalization (§3.6). The aggregates are: `gross_revenue_cents` is the sum of `POSTED` revenue lines for the branch inside the period window; `total_charges_cents` is the sum of `POSTED`, non-reversed charge amounts for the period; `net_profit_cents` is gross revenue minus total charges and may go negative; and `advisor_share_cents` is recomputed in its provisional variant (§3.6). Reversing a charge also increments the parent period's `version` while the period is `OPEN` or `CLOSED`, and touches the charge itself. Charges post with `status` `POSTED` and move to `REVERSED` on reversal; reversed rows are excluded from every aggregate even if they were originally posted inside the window. A charge may never post to a `FINALIZED` period — such attempts are rejected with `ERR_PERIOD_FINALIZED` — and only a `POSTED` charge may be reversed (`ERR_INVALID_STATE` otherwise). Reversing a charge on a `FINALIZED` period leaves that period's aggregates untouched.

Closing a period requires the logical clock to have reached `period_end`; closing earlier is rejected with `ERR_PERIOD_NOT_CLOSABLE`. The close moves the period `OPEN → CLOSED`, recomputes all four aggregates as a provisional snapshot, and, when the net is negative, sets `deficit_carryforward_cents` to the absolute value of the negative net (it is zero otherwise). A closed period may be reopened — but only if no later period exists for the same branch in any status, where "latest" is determined by comparing `period_start` (then `period_end`); reopening any period that is not the branch's latest is rejected with `ERR_PERIOD_NOT_LATEST`. Reopening moves the period back to `OPEN` and resets `deficit_carryforward_cents` to zero, since it will be recomputed on the next close; the other aggregates keep the values snapshot at close until the next recomputation.

Finalization moves a `CLOSED` period to the terminal `FINALIZED` state and does three things. First, it recomputes `advisor_share_cents` in the final variant, which counts every `POSTED` charge as of the finalize instant — including corrections that were reversed and then re-posted after the close — so the final share may differ from the provisional one, and that delta is the payable adjustment to the advisor. Second, when the final net is negative, it creates a `DEFICIT_CARRYOVER` charge on the branch's next `OPEN` period for the carryforward amount — the earliest-starting `OPEN` period, whose aggregates are immediately recomputed — or holds the carryforward if no open period exists; when the final net is non-negative, finalization does not touch `deficit_carryforward_cents`, which retains the value recorded at close. Third, it recomputes the branch's `service_tier` as a threshold trigger (§3.6). Because finalized periods reject further charges, the final figures never drift.

### 3.6. The Advisor Profit Share and the Branch Service Tier

The advisor's compensation is a tiered share of branch net profit, computed identically in structure for the provisional and final variants and differing only in which charges are in scope. Given a period's `net_profit_cents`: when the net is zero or negative, the share is zero. When the net is positive, it is sliced into three tiers against a five-thousand-dollar tier width — that is, each tier spans 500,000 cents. The first tier covers the lesser of the net and 500,000 cents; the second tier covers whatever remains above 500,000 cents, up to another 500,000 cents; the third tier covers everything above 1,000,000 cents. Each tier's base is multiplied by its rate — thirty-eight percent for the first tier, forty-two percent for the second, forty-six percent for the third — and each tier's product is rounded half-up to whole cents first; the three rounded amounts are then summed into `advisor_share_cents`. The rounding order is pinned: per-tier half-up rounding before summation, never the reverse. The provisional variant applies while the period is `OPEN` or `CLOSED` and snapshots the charges currently posted; the final variant applies at finalization and includes late re-posted corrections.

The branch's home-office support tier is derived from a score that depends only on the branch's raw book attributes — never on financial periods, charges, or the branch's previous tier, which makes the evaluation order explicit and non-circular. The `tier_score` is ten points per household — `household_count` multiplied by 10 — plus one point per hundred thousand dollars of assets under care, computed as `assets_under_care_dollars` floor-divided by 100000 (truncating toward zero). The score maps to tiers with an inclusive upper boundary on the middle tier: a score below 300 is `TIER_1`; a score of at least 300 and at most 900 is `TIER_2` — a score of exactly 900 is still `TIER_2`; and a score of 901 or more is `TIER_3`. Both `tier_score` and `service_tier` are recomputed at branch creation, on every book-attribute update, and again at period finalization.

### 3.7. Retirement, Goodwill Valuation, and Succession Negotiation

A practicing advisor declares retirement through their own session — the acting advisor must own the advisor record — moving the advisor `PRACTICING → RETIRING` and flipping the branch's staffing to `SUCCESSION_PENDING`. Retirement is revocable: while no goodwill transfer on the advisor's branch stands in `ACCEPTED` or `COMPLETED` status, the advisor may rescind, returning `RETIRING → PRACTICING` and restoring the branch to `ADVISOR_ASSIGNED` or `FULLY_STAFFED` depending on administrator presence. Note the asymmetry in the block rule: rescission is blocked only by `ACCEPTED` or later transfers, whereas closing the branch (§3.3) is blocked by any transfer in `OFFERED`, `NEGOTIATING`, or `ACCEPTED`; both rejections carry `ERR_TRANSFER_ACTIVE`.

The goodwill transfer itself is created by a `HomeOfficeAdmin` with the `branch_id`, the `retiring_advisor_id`, the `successor_advisor_id`, a `valuation_mode` of `INTERNAL_SUCCESSION` or `OPEN_MARKET`, and the successor's `escrow_deposit_cents`, which may be zero or more. Creation computes the valuation. The `trailing_revenue_cents` is the sum of `gross_commission_cents` across `POSTED` production records of the branch's advisors — reversed rows excluded — whose `posted_at` falls in the trailing window: the twelve complete calendar months before the offer's creation month, running from the first day of the month twelve months before creation up to but not including the first day of the creation month. The initial `offer_price_cents` is that trailing revenue multiplied by the valuation multiple and rounded half-up to whole cents: three-quarters (0.75) for `INTERNAL_SUCCESSION`, a discounted price for a successor continuing the practice internally; or one and one-tenth (1.10) for `OPEN_MARKET`, a premium price when the practice is listed to an external buyer, so identical trailing revenue yields a materially higher offer. A new transfer begins `OFFERED` with `negotiation_round` at zero, and the initial offer is treated as made by the retiring advisor for turn-alternation purposes — so the first negotiation act (counter-offer, acceptance, or decline) must come from the successor. Creation performs no precondition checks on the branch's operating state, the retiring advisor's status, or the successor's status beyond existence; those gates apply at completion instead.

Negotiation is strictly alternating between the two advisor parties, and only those two: a counter-offer, acceptance, or decline from any `Advisor` session whose `X-User-ID` is neither the retiring nor the successor advisor is rejected with `ERR_UNAUTHORIZED`. A counter-offer — allowed while the transfer is `OFFERED` or `NEGOTIATING`, moving it into (or keeping it in) `NEGOTIATING` — must come from either the retiring or the successor advisor, must propose a positive `offer_price_cents`, and must carry the OCC guard `expected_transfer_version` described in §2.4, which is mandatory on every counter-offer. The same party may not speak twice in a row — the turn check applies in both `OFFERED` and `NEGOTIATING` status, counting the initial offer as the retiring advisor's: the acting advisor must not be the maker of the immediately preceding offer, and a violation is rejected with `ERR_NEGOTIATION_TURN`. Each accepted counter-offer increments `negotiation_round` by one and bumps the transfer's `version`. Acceptance and decline likewise belong to the party who did not make the most recent offer — accepting one's own offer or declining it out of turn is also `ERR_NEGOTIATION_TURN`. Acceptance additionally requires escrow sufficiency: `escrow_deposit_cents` must be at least ten percent of the current `offer_price_cents`, computed as the offer price multiplied by 0.10 and rounded half-up to whole cents; insufficient escrow is rejected with `ERR_ESCROW_INSUFFICIENT`. A successful acceptance locks the escrow deposit — from that point there is no refund path except decline or cancellation — and moves the transfer to `ACCEPTED`. Declining refunds the escrow to the successor, returning the escrow balance to zero, and moves the transfer to `DECLINED`. Offers age out: when the logical clock reaches thirty days past the transfer's `created_at` without acceptance, a transfer still `OFFERED` or `NEGOTIATING` expires — the clock-set sweep performs this — refunding the escrow and moving it to `EXPIRED`. A `HomeOfficeAdmin` may also cancel an `OFFERED` or `NEGOTIATING` transfer outright, refunding escrow and moving it to `CANCELLED`.

Completion is the home office's final act on an `ACCEPTED` transfer, and it requires the retiring advisor to be `RETIRING` and the successor to be `VALIDATED` or `PRACTICING`. Completion cascades across four records: the retiring advisor moves `RETIRING → RETIRED` with `branch_id` cleared; the successor's `branch_id` is set to the transfer's branch and the successor's `predecessor_advisor_id` is set to the retiring advisor — this is the only path that populates that field, and it stays null for non-succession advisors — and a successor who is `VALIDATED` moves to `PRACTICING`; the branch's staffing moves to `ADVISOR_ASSIGNED` or `FULLY_STAFFED` depending on administrator presence; and the escrow deposit is applied to the sale, leaving escrow so the transfer's escrow balance returns to zero. Completion performs no territory reassignment: the branch's territory keeps its current assignment.

Terminating an advisor is the heavy cascade of last resort, available to a `HomeOfficeAdmin` while the advisor is `PRACTICING` or `RETIRING`. Terminating a `RETIRING` advisor is permitted only when no transfer on the branch is `ACCEPTED`; any transfer still `OFFERED` or `NEGOTIATING` is automatically cancelled with its escrow refunded as part of the termination. The termination cascade then: clears the advisor's `branch_id`; drops the branch's staffing to `UNSTAFFED` — the administrator stays employed, but the branch loses `FULLY_STAFFED`; suspends the branch's operations (`OPEN → SUSPENDED`-equivalent `operating_status`), since no advisor remains to run the practice; releases the territory assignment — `assigned_advisor_id` cleared, `assignment_end` stamped, territory back to `OPEN`; and withdraws every `SUBMITTED` solicitation request the advisor had outstanding, moving each to `WITHDRAWN`.

### 3.8. The Product Shelf and Solicitation Approval

The firm offers a deliberately limited shelf. A `CompliancePrincipal` proposes a shelf entry with a `product_code`, an `asset_class` of `MUTUAL_FUND`, `ETF`, `ANNUITY`, `BOND`, or `ALTERNATIVE`, and a `complexity_level` of `PLAIN`, `COMPLEX`, or `RESTRICTED`. New entries are `PROPOSED` until approved (`PROPOSED → APPROVED`), and an approved entry may later be retired (`APPROVED → RETIRED`). The `product_code` must be unique among `APPROVED` entries: proposing an entry whose code already belongs to an `APPROVED` entry is rejected with `ERR_DUPLICATE`, and approving a `PROPOSED` entry whose code already belongs to an `APPROVED` entry is likewise rejected with `ERR_DUPLICATE` — which makes product lookup order-sensitive in a useful way: among entries sharing a code, at most one can be `APPROVED`, and that one is the match. Retiring an entry immediately invalidates new solicitations for its code: any subsequent solicitation referencing it fails the shelf check with `ERR_PRODUCT_NOT_ON_SHELF`.

An advisor requests approval to solicit by submitting a `SolicitationRequest` naming the `advisor_id`, the `product_code`, and an opaque `client_household_id`. The request begins `SUBMITTED` with `decided_by_role` null. Submission already enforces the shelf rule: the referenced code must resolve to an `APPROVED` shelf entry, or the submission is rejected with `ERR_PRODUCT_NOT_ON_SHELF`. The acting advisor must be the requester — a session whose `X-User-ID` differs from the body's `advisor_id` is rejected with `ERR_UNAUTHORIZED` — but the advisor's own status and branch state are not checked at submission. The advisor may withdraw their own request while it is `SUBMITTED` (`SUBMITTED → WITHDRAWN`), and a `CompliancePrincipal` may deny a submitted request (`SUBMITTED → DENIED`), landing the request in the terminal `DENIED` status.

Approval is the system's tightest gate, and its checks fire in a deliberate order so that compliance posture surfaces before business state. First, segregation of duties: when the product's `complexity_level` is `COMPLEX` or `RESTRICTED`, the approver must be a `CompliancePrincipal` distinct from the requesting advisor — a principal session whose `X-User-ID` equals the requesting advisor's `id` (i.e., acting for the requester) is rejected with `ERR_SEGREGATION_OF_DUTIES`, and any non-principal role has already been rejected as `ERR_UNAUTHORIZED`. For a `PLAIN` product no segregation-of-duties restriction applies — any `CompliancePrincipal` session may approve. Then the cross-entity gates: the requesting advisor must be `VALIDATED` or `PRACTICING`; the advisor's branch must have `operating_status` `OPEN` — which is why suspended branches freeze pending solicitations even though the requests stay `SUBMITTED`; and the shelf entry for the `product_code` must currently be `APPROVED` (a retirement between submission and approval turns the request unapprovable, again surfacing `ERR_PRODUCT_NOT_ON_SHELF`). A fully cleared approval moves the request `SUBMITTED → APPROVED`. Either decision — approval or denial — records the deciding role in `decided_by_role` (the role string, e.g. `CompliancePrincipal`) for the segregation-of-duties audit trail.

## 4. Endpoint Definitions

All endpoints are mounted under `/branch-office`. Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request and response bodies, side effects, and preconditions for each operation are specified in §2 and §3; this table is the HTTP contract index only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/branch-office/advisors` | Register an advisor candidate | HomeOfficeAdmin |
| GET | `/branch-office/advisors` | List advisors; optional `status`, `branch_id`, `predecessor_advisor_id` filters | HomeOfficeAdmin, CompliancePrincipal |
| GET | `/branch-office/advisors/{id}` | Fetch one advisor | HomeOfficeAdmin, Advisor, CompliancePrincipal |
| GET | `/branch-office/advisors/{id}/goodwill-transfers` | List goodwill transfers where the advisor is the retiring party | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/advisors/{id}/solicitation-requests` | List solicitation requests submitted by the advisor | HomeOfficeAdmin, Advisor, CompliancePrincipal |
| GET | `/branch-office/advisors/{id}/production-records` | List the advisor's production records | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/advisors/{id}/enroll-training` | Enroll a candidate into a training program (CANDIDATE → TRAINEE) | HomeOfficeAdmin |
| POST | `/branch-office/advisors/{id}/assign-branch` | Assign a VALIDATED advisor to a branch (VALIDATED → PRACTICING) | HomeOfficeAdmin |
| POST | `/branch-office/advisors/{id}/declare-retirement` | Practicing advisor declares retirement (PRACTICING → RETIRING) | Advisor |
| POST | `/branch-office/advisors/{id}/rescind-retirement` | Rescind a retirement declaration while no transfer is accepted | Advisor |
| POST | `/branch-office/advisors/{id}/terminate` | Terminate a practicing or retiring advisor | HomeOfficeAdmin |
| POST | `/branch-office/territories` | Create a territory | HomeOfficeAdmin |
| GET | `/branch-office/territories` | List territories; optional `assigned_advisor_id`, `status` filters | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/territories/{id}` | Fetch one territory | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/territories/{id}/assign` | Assign a territory to an advisor for a half-open interval | HomeOfficeAdmin |
| POST | `/branch-office/territories/{id}/retire` | Retire an unassigned territory (terminal) | HomeOfficeAdmin |
| POST | `/branch-office/territories/{id}/contacts` | Log a door-knock contact in the territory | Advisor |
| GET | `/branch-office/territories/{id}/contacts` | List contacts; archived excluded unless `include_archived` is true | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/branches` | Propose a new branch | HomeOfficeAdmin |
| GET | `/branch-office/branches` | List branches; optional `territory_id`, `operating_status`, `service_tier` filters | HomeOfficeAdmin, CompliancePrincipal |
| GET | `/branch-office/branches/{id}` | Fetch one branch | HomeOfficeAdmin, Advisor, BranchAdministrator, CompliancePrincipal |
| PATCH | `/branch-office/branches/{id}` | Update book attributes (OCC-guarded via `expected_branch_version`) | HomeOfficeAdmin |
| POST | `/branch-office/branches/{id}/approve-site` | Approve the site and sign the lease (PROPOSED → SITE_APPROVED) | HomeOfficeAdmin |
| POST | `/branch-office/branches/{id}/open` | Open a fully staffed branch (SITE_APPROVED → OPEN) | HomeOfficeAdmin |
| POST | `/branch-office/branches/{id}/suspend` | Suspend an open branch | HomeOfficeAdmin |
| POST | `/branch-office/branches/{id}/reinstate` | Reinstate a suspended branch | HomeOfficeAdmin |
| POST | `/branch-office/branches/{id}/close` | Close a suspended branch (terminal) | HomeOfficeAdmin |
| GET | `/branch-office/branches/{id}/financial-periods` | List the branch's financial periods | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/branches/{id}/leases` | List the branch's leases | HomeOfficeAdmin |
| GET | `/branch-office/branches/{id}/administrators` | List administrators assigned to the branch | HomeOfficeAdmin |
| GET | `/branch-office/branches/{id}/goodwill-transfers` | List goodwill transfers of the branch | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/branches/{id}/charges` | List all charges borne by the branch across periods | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/administrators` | Hire a branch office administrator | HomeOfficeAdmin |
| GET | `/branch-office/administrators` | List administrators; optional `branch_id`, `status` filters | HomeOfficeAdmin |
| GET | `/branch-office/administrators/{id}` | Fetch one administrator | HomeOfficeAdmin, BranchAdministrator |
| POST | `/branch-office/branches/{id}/assign-administrator` | Assign a HIRED administrator to a branch (HIRED → ACTIVE) | HomeOfficeAdmin |
| POST | `/branch-office/administrators/{id}/place-on-leave` | Place an ACTIVE administrator on leave | HomeOfficeAdmin |
| POST | `/branch-office/administrators/{id}/return-from-leave` | Return an ON_LEAVE administrator to ACTIVE | HomeOfficeAdmin |
| POST | `/branch-office/administrators/{id}/release` | Release an administrator (ACTIVE/ON_LEAVE → RELEASED) | HomeOfficeAdmin |
| POST | `/branch-office/training-programs/{id}/submit-milestone` | Trainee submits for milestone evaluation (→ MILESTONE_PENDING) | Advisor |
| POST | `/branch-office/training-programs/{id}/evaluate` | Evaluate the pending milestone; creates a MilestoneEvaluation | HomeOfficeAdmin |
| GET | `/branch-office/training-programs/{id}` | Fetch one training program | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/training-programs` | List training programs; optional `advisor_id` filter | HomeOfficeAdmin |
| GET | `/branch-office/training-programs/{id}/evaluations` | List milestone evaluations of a program | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/production-records` | Post a production record | HomeOfficeAdmin |
| POST | `/branch-office/production-records/{id}/reverse` | Reverse a posted production record | HomeOfficeAdmin |
| GET | `/branch-office/production-records` | List production records; optional `advisor_id`, `status` filters | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/financial-periods` | Open a financial period for a branch | HomeOfficeAdmin |
| GET | `/branch-office/financial-periods/{id}` | Fetch one financial period | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/financial-periods/{id}/charges` | Post a charge to the period | HomeOfficeAdmin |
| POST | `/branch-office/charges/{id}/reverse` | Reverse a posted charge | HomeOfficeAdmin |
| GET | `/branch-office/financial-periods/{id}/charges` | List charges of a period | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/financial-periods/{id}/close` | Close the period (provisional snapshot) | HomeOfficeAdmin |
| POST | `/branch-office/financial-periods/{id}/reopen` | Reopen a closed period (latest only) | HomeOfficeAdmin |
| POST | `/branch-office/financial-periods/{id}/finalize` | Finalize the period (final share, carryover, tier re-evaluation) | HomeOfficeAdmin |
| POST | `/branch-office/goodwill-transfers` | Create a goodwill transfer offer on a branch | HomeOfficeAdmin |
| GET | `/branch-office/goodwill-transfers` | List goodwill transfers; optional `successor_advisor_id`, `status` filters | HomeOfficeAdmin, Advisor |
| GET | `/branch-office/goodwill-transfers/{id}` | Fetch one goodwill transfer | HomeOfficeAdmin, Advisor |
| POST | `/branch-office/goodwill-transfers/{id}/counter-offer` | Counter the current offer (OCC-guarded, strict alternation) | Advisor |
| POST | `/branch-office/goodwill-transfers/{id}/accept` | Accept the current offer (by the party who did not make it) | Advisor |
| POST | `/branch-office/goodwill-transfers/{id}/decline` | Decline the current offer | Advisor |
| POST | `/branch-office/goodwill-transfers/{id}/complete` | Complete an accepted transfer (succession cascade) | HomeOfficeAdmin |
| POST | `/branch-office/goodwill-transfers/{id}/cancel` | Cancel a pending transfer | HomeOfficeAdmin |
| POST | `/branch-office/product-shelf` | Propose a product shelf entry | CompliancePrincipal |
| POST | `/branch-office/product-shelf/{id}/approve` | Approve a proposed shelf entry | CompliancePrincipal |
| POST | `/branch-office/product-shelf/{id}/retire` | Retire an approved shelf entry (terminal) | CompliancePrincipal |
| GET | `/branch-office/product-shelf` | List shelf entries; optional `status` filter | HomeOfficeAdmin, Advisor, CompliancePrincipal |
| POST | `/branch-office/solicitation-requests` | Submit a solicitation approval request | Advisor |
| POST | `/branch-office/solicitation-requests/{id}/approve` | Approve a solicitation request | CompliancePrincipal |
| POST | `/branch-office/solicitation-requests/{id}/deny` | Deny a solicitation request | CompliancePrincipal |
| POST | `/branch-office/solicitation-requests/{id}/withdraw` | Withdraw one's own solicitation request | Advisor |
| GET | `/branch-office/solicitation-requests` | List solicitation requests; optional `advisor_id`, `status` filters | HomeOfficeAdmin, Advisor, CompliancePrincipal |
| POST | `/branch-office/_clock/set_current_utc` | Set the logical clock; expires aged-out goodwill offers | HomeOfficeAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE` | 409 |
| `ERR_BRANCH_OCCUPIED` | 409 |
| `ERR_BOA_ALREADY_ASSIGNED` | 409 |
| `ERR_TERRITORY_OVERLAP` | 409 |
| `ERR_LEASE_OVERLAP` | 409 |
| `ERR_TERRITORY_CAPACITY` | 409 |
| `ERR_CONTACT_OUTSIDE_WINDOW` | 422 |
| `ERR_PRODUCT_NOT_ON_SHELF` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NEGOTIATION_TURN` | 409 |
| `ERR_ESCROW_INSUFFICIENT` | 422 |
| `ERR_PERIOD_FINALIZED` | 409 |
| `ERR_GOAL_NOT_MET` | 422 |
| `ERR_PERIOD_NOT_LATEST` | 409 |
| `ERR_PERIOD_NOT_CLOSABLE` | 422 |
| `ERR_BRANCH_NOT_FULLY_STAFFED` | 409 |
| `ERR_ADVISOR_NOT_VALIDATED` | 409 |
| `ERR_TRANSFER_ACTIVE` | 409 |
