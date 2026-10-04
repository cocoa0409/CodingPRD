# Municipal Acquisition API — Product Requirements Document

## 1. Introduction

Investor-owned water utilities grow in part by acquiring municipally owned water and wastewater systems. Each such transaction is a long, multi-party negotiation: the utility must assess the physical condition of the target system and estimate deferred capital needs, commission appraisals under valuation methods that the target state's acquisition statute actually permits, shepherd the sale through the municipality's political process — public hearings, a council vote, and in the close-call case a public referendum — and then win approval from the state utility commission, which decides how much of the purchase price may enter the buyer's rate base. Only after all of that can the utility close: migrate customer accounts and deposits, honor or settle employee transitions under collective bargaining constraints, and decide whether the acquired customers move onto a single consolidated tariff or stand alone.

This document specifies the API that supports that pipeline. An **AcquisitionTarget** progresses through a branching lifecycle from `SCREENING` to either `INTEGRATED` or `REJECTED`, driven by the artifacts and events around it: condition assessments, valuation cases and appraisal entries, council events, a regulatory application, customer accounts, transition items, employee transitions, and tariff cases. Because the actors are deliberately segregated — the analyst who drafts an assessment may not accept it, the appraiser who submits a valuation may not finalize the case that selects it — the API enforces role-based access control and segregation-of-duties checks throughout, records monetary values in integer cents with pinned rounding rules, and guards the two write operations that reopen earlier stages (opening a valuation case, refiling a remanded application) with optimistic concurrency control against the target's version.

Time-sensitive rules — hearing notice periods, capital-item execution windows — are evaluated against a server-maintained logical clock, not wall-clock time, so that test fixtures and operational replays are deterministic. The clock starts at exactly `2026-09-01T00:00:00Z` at server startup and only moves when explicitly advanced by an administrator.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming exactly one declared role. A request missing either header, carrying a blank header, or naming a role outside the declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles are: `AcquisitionAnalyst`, `EngineeringReviewer`, `Appraiser`, `MunicipalClerk`, `RegulatoryOfficer`, `Commissioner`, `TransitionManager`, `HRDirector`, and `SystemAdmin`.

- An `AcquisitionAnalyst` is the utility-side deal analyst: creates targets, condition assessments and capital need items, opens valuation cases, and finalizes valuation cases.
- An `EngineeringReviewer` is the independent engineering reviewer who accepts or rejects submitted assessments.
- An `Appraiser` is the independent appraiser who submits valuation entries into open valuation cases.
- A `MunicipalClerk` is the municipality's clerk: schedules public hearings, council votes, and referenda, and records their outcomes.
- A `RegulatoryOfficer` handles utility regulatory affairs: files and refiles commission applications and manages tariff cases.
- A `Commissioner` is the state utility commissioner who decides filed applications.
- A `TransitionManager` is the utility transition lead: schedules and executes capital items, registers and migrates customer accounts, resolves transition items, and closes targets.
- An `HRDirector` manages employee transitions and records offer responses.
- A `SystemAdmin` operates the logical clock.

For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources — as `created_by_user_id` on a condition assessment, `appraiser_user_id` on a valuation entry, and `finalized_by_user_id` on a valuation case — and uses those recordings for segregation-of-duties checks, but it never compares `X-User-ID` to any entity's `id` and performs no ownership checks against persisted users.

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

List endpoints accept two optional query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Both must be integers; a non-integer value, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope, where `has_more` is true exactly when `offset` plus the number of returned items is below `total_count`. Unless a query parameter says otherwise, list endpoints return resources sorted by `created_at` ascending, breaking ties on `id` ascending. Some list endpoints additionally accept filters described in §3 — for example the target list accepts an optional `status` filter and an optional `state_code` filter, the council-event list accepts an optional `kind` filter, and the customer-account list accepts an optional `status` filter.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Because every entity in this domain is mutable through its lifecycle, each resource also carries an `updated_at` timestamp (same format) and an integer `version`. The `version` starts at 1 at creation and increments by exactly 1 on every mutation of that resource; `updated_at` refreshes on the same occasions.

### 2.5. The Logical Clock

Date-sensitive rules — the public-hearing notice period and capital-item execution windows — are evaluated against a server-maintained **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `SystemAdmin` may advance it by supplying a `to_iso8601` instant; the call responds with the current logical time in `current_utc`, and every subsequent date-sensitive rule evaluates against the new reading. The clock never falls back to wall-clock time on its own.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents. Percentages and shares are numbers with two decimal places. Wherever a division or a rate application produces a fractional cent — a capital item's `midpoint_estimate_cents`, a council event's `yes_share_pct`, the premium cap in rate-base admission, the annual phase-in cap on a tariff case — the result is rounded **half-up** to the stated precision. The order of operations matters: for the filing-variant capital estimate, each line item's midpoint is rounded to a whole cent *first* and the rounded midpoints are *then* summed; summing unrounded averages and rounding once at the end is a different number and is not acceptable.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the owning target's `version`, because both reopen an earlier lifecycle stage and must not proceed from a stale view:

- **Opening a valuation case.** The request must carry `expected_target_version`, the client-side last observed `version` of the target. If the target's current `version` has since advanced, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A previously created `OPEN` case legitimately supersedes under the one-open-case rule, so a stale view of the target must fail loudly rather than silently superseding again.
- **Refiling a remanded regulatory application.** The request likewise must carry `expected_target_version` matching the target's current `version`. Between the client's last read and the refile, a council outcome or a rejection cascade may have advanced the target, invalidating the refile's premise; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.8. Nested Resource Retrieval and Existence Checking

Paths nest children under their parents (a capital item under an assessment, an entry under a valuation case, and so on). All path-template resource identifiers are validated for existence **left to right**: the server first checks the leftmost identifier, then the next, and a nested child must actually belong to the parent named in the path. Any missing id, or a child that belongs to a different parent, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Segregation of Duties

Two checkpoints enforce that the actor who produced work is not the actor who approves it. The `EngineeringReviewer` who accepts or rejects a submitted condition assessment must not be the analyst who created it — the request's `X-User-ID` must differ from the assessment's `created_by_user_id`, otherwise the call is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). Likewise, the `AcquisitionAnalyst` who finalizes a valuation case must not be the appraiser of any `SUBMITTED` entry in that case — `X-User-ID` must differ from the `appraiser_user_id` of every submitted entry — and the same `ERR_SEGREGATION_OF_DUTY` (HTTP 403) applies.

### 2.10. Validation Priority

When several checks could fire on one request, they are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication and role checks come first (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`), then path-existence (`ERR_NOT_FOUND`), then segregation of duties (`ERR_SEGREGATION_OF_DUTY`), then state-machine legality (`ERR_INVALID_STATE`), then the window-sanity check (`ERR_INVALID_WINDOW`), then the temporal and referential business rules — event overlap (`ERR_EVENT_OVERLAP`), hearing notice (`ERR_HEARING_NOTICE`), crew capacity (`ERR_CREW_CAPACITY_EXCEEDED`), statutory method permission (`ERR_METHOD_NOT_PERMITTED`), referendum availability (`ERR_REFERENDUM_NOT_AVAILABLE`) — then the prerequisite gates (`ERR_APPROVAL_PREREQ`, `ERR_TRANSITION_PREREQ`, `ERR_ACCOUNTS_PENDING`, `ERR_TRANSITION_INCOMPLETE`, `ERR_EMPLOYEES_PENDING`), then money-range and split validity (`ERR_INVALID_REQUEST`, `ERR_INVALID_SPLIT`), then the account-settled gate (`ERR_ACCOUNT_NOT_SETTLED`), the union rule (`ERR_UNION_ASSUMPTION_REQUIRED`), and finally uniqueness (`ERR_DUPLICATE`). A failure at an earlier tier masks later tiers: for example, a request whose role is wrong reports `ERR_UNAUTHORIZED` even if its payload is also malformed, and an accept attempted by the assessment's creator reports `ERR_SEGREGATION_OF_DUTY` before any state check runs.

## 3. Business Logic & Workflows

### 3.1. Registering a Target and Its Closing Checklist

An `AcquisitionAnalyst` originates a deal by registering an acquisition target. The registration names the municipal system (`system_name`), the owning municipality (`municipality_name`), the two-letter US state code whose acquisition statute governs the transaction (`state_code`), and the nature of the system — `system_type` is one of `WATER`, `WASTEWATER`, or `COMBINED`. The size of the customer base is captured as `customer_count`, which must be greater than zero, and the state's statute determines which valuation approaches are on the table: `permitted_valuation_methods` is a non-empty list drawn from `FMV_INDEPENDENT`, `REPLACEMENT_COST`, and `ORIGINAL_COST_LESS_DEPRECIATION`. A freshly created target starts in `SCREENING`, with `council_approved` false and `filing_estimate_cents` zero; its valuation-related outcomes (`selected_value_cents`, `admitted_rate_base_cents`, `disallowed_premium_cents`) remain null until later stages produce them.

Creating a target also creates its closing checklist automatically. Four `TransitionItem` rows spring into existence alongside the target, in this fixed order — `BILLING_RECORDS`, `DEPOSITS`, `SERVICE_AGREEMENTS`, `METER_READS` — each in `PENDING` with `resolution_note` initialized to the empty string. Each transition item records the owning target's id as its `target_id` — the same `target_id` foreign key carried by every other child resource of the target (assessments, valuation cases, council events, regulatory applications, customer accounts, and employee transitions alike) — and carries an optional `resolution_note` that the transition lead may record when the item is eventually resolved. Because the checklist is auto-created, it cannot be added to manually; the only operations on transition items are retrieval and resolution. The transition-item list endpoint returns the items in this fixed category order — `BILLING_RECORDS`, `DEPOSITS`, `SERVICE_AGREEMENTS`, `METER_READS` — rather than the default `created_at` ordering of §2.3.

The target list supports browsing with an optional `status` filter and an optional `state_code` filter, on top of the standard `limit` and `offset` pagination parameters.

### 3.2. Condition Assessment and Capital Need Estimation

Before a price can be discussed, the utility surveys the physical system. An `AcquisitionAnalyst` creates a condition assessment against a target in any status — free-text survey observations go in `notes`, the server stamps `created_by_user_id` from the request's `X-User-ID` and initializes `revision_count` to zero — and the assessment starts life in `DRAFT`. While in `DRAFT`, the analyst builds up the capital picture by adding capital need items, each of which records the owning assessment's id as its `assessment_id`. Each item names its `category` (one of `DISTRIBUTION`, `COLLECTION`, `TREATMENT`, `SOURCE`, `STORAGE`, or `GENERAL`), its `horizon` (one of `IMMEDIATE`, `SHORT_TERM`, or `LONG_TERM`), a `description` of the scope of work, a cost range via `cost_low_cents` and `cost_high_cents` (both bounds must be at least zero and the high bound must be at least the low bound), and `crews_required`, the number of crews the work will tie up during its execution window (at least one). Every item starts in `PLANNED`; its `window_start` and `window_end` stay unset until scheduling time.

Each item's `midpoint_estimate_cents` is the average of its low and high cost bounds, rounded half-up to a whole cent, computed per item at creation. From these items the assessment derives **two variants** of the capital need estimate, and the two differ deliberately. The planning variant, `planning_estimate_cents`, is the internal view: sum the `cost_low_cents` of every item of the assessment in `PLANNED`, `SCHEDULED`, or `EXECUTED` status (items that are `SPLIT` or `CANCELLED` are excluded), increase the total by a ten percent planning contingency, and round half-up to a whole cent. The filing variant, `filing_estimate_cents`, is the regulatory view: sum the per-item rounded `midpoint_estimate_cents` over the same set of items, increase the total by a fifteen percent filing contingency, and round half-up to a whole cent. The pinned order for the filing variant is per-line rounding then summation — rounding the midpoints item by item first, then adding them up; averaging without rounding and rounding once at the end is forbidden. Both estimates are recomputed on submit and whenever a non-`SPLIT` item is added, cancelled, or split while the assessment is still in `DRAFT`. Estimates live on the assessment itself; the target's `filing_estimate_cents` is a copy written only by the accept cascade described below, so these recomputations do not touch the target.

Items can be restructured while the assessment is in `DRAFT`. An `AcquisitionAnalyst` may cancel a `PLANNED` item outright, moving it to `CANCELLED`, or split it in two. A split takes `split_low_cents` and `split_high_cents`; both must be non-negative and each must not exceed the parent's corresponding bound (`split_low_cents` at most the parent's `cost_low_cents`, `split_high_cents` at most the parent's `cost_high_cents`), otherwise the split is rejected with `ERR_INVALID_SPLIT` (HTTP 422). The parent moves to `SPLIT` and two child items are created in `PLANNED`: child A carries the split amounts as its low and high bounds, child B carries the remainders (the parent's low bound minus `split_low_cents`, and the parent's high bound minus `split_high_cents`). Both children copy the parent's `category`, `horizon`, `description`, and `crews_required`. The split conserves money exactly: the two children's low bounds sum to the parent's low bound, and likewise for the high bounds. Splits and cancels are only possible while the owning assessment is `DRAFT`; attempting either once the assessment has moved on is rejected with `ERR_INVALID_STATE` (HTTP 409).

When the estimate is ready, the analyst submits the assessment, moving it from `DRAFT` to `SUBMITTED` and recomputing both estimate variants. Submission requires the assessment to have at least one non-`SPLIT` capital item; submitting an empty assessment is rejected with `ERR_ASSESSMENT_EMPTY` (HTTP 409). Review then belongs to an `EngineeringReviewer` who is not the assessment's creator (the segregation-of-duties rule of §2.9). The reviewer may reject the assessment, returning it to `DRAFT` and bumping its `revision_count` by one for the revision loop — or accept it, moving it to `ACCEPTED`. Acceptance requires the target to be in `SCREENING` or `VALUATION`; accepting against a later-stage target is rejected with `ERR_INVALID_STATE` (HTTP 409). Acceptance has two cascades. If the target already has another `ACCEPTED` assessment, that earlier assessment is superseded to `SUPERSEDED` so at most one accepted assessment stands. And if the target is still in `SCREENING`, the target automatically advances `SCREENING → VALUATION`: the accepted assessment's `filing_estimate_cents` is copied onto the target, and the target's `version` increments by 1. If the target is already in `VALUATION`, no advance occurs: the target's `filing_estimate_cents` is left unchanged and the target's `version` is not incremented — only the supersede cascade runs.

### 3.3. Valuation Under State Law

Once a target reaches `VALUATION`, an `AcquisitionAnalyst` opens a valuation case. This is one of the two OCC-guarded writes (§2.7): the request must carry `expected_target_version`, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). Exactly one valuation case per target may be `OPEN` at a time; opening a new case while a prior case is still `OPEN` supersedes the prior case — it moves to `SUPERSEDED` and every `SUBMITTED` entry in it moves to `NOT_SELECTED`. Opening a case increments the target's `version` by 1.

Appraisals arrive as entries submitted by an `Appraiser` into an `OPEN` case, each entry recording the owning case's id as its `case_id`. Each entry names its valuation `method` — one of `FMV_INDEPENDENT`, `REPLACEMENT_COST`, or `ORIGINAL_COST_LESS_DEPRECIATION` — the appraised `value_cents` (which must be greater than zero), and a `law_citation` identifying the statute that authorizes the method. The server records the submitting appraiser as `appraiser_user_id`. State law constrains the menu: an entry whose `method` is not among the target's `permitted_valuation_methods` is rejected with `ERR_METHOD_NOT_PERMITTED` (HTTP 422). Every entry starts in `SUBMITTED`.

Finalizing the case is the analyst's decision and a second segregation checkpoint: the finalizer's `X-User-ID` must differ from the `appraiser_user_id` of every `SUBMITTED` entry in the case, otherwise the finalize is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). The request names the winning appraisal via `select_entry_id`; if that identifier does not designate a `SUBMITTED` entry of this case, the finalize is rejected with `ERR_INVALID_STATE` (HTTP 409). On finalize, the selected entry moves to `SELECTED` and every other `SUBMITTED` entry moves to `NOT_SELECTED`; the case moves to `FINALIZED`, recording `selected_entry_id`, the selected appraisal's value in `selected_value_cents`, and the finalizer in `finalized_by_user_id`. Finalization automatically advances a target that is in `VALUATION` `VALUATION → MUNICIPAL_REVIEW`: the case's `selected_value_cents` is copied onto the target, and the target's `version` increments by 1.

### 3.4. The Municipal Process: Hearings, Votes, and Referenda

In `MUNICIPAL_REVIEW` the deal goes before the public. A `MunicipalClerk` schedules council events — a `PUBLIC_HEARING`, a `COUNCIL_VOTE`, or a `REFERENDUM`, given in the event's `kind` — each with a `scheduled_start` and `scheduled_end` delimiting its window. Scheduling is only possible while the target is in `MUNICIPAL_REVIEW`; attempting to schedule an event against a target in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The end must come strictly after the start, otherwise scheduling is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Events of the same target may not overlap: under half-open semantics, each event occupies the interval from its `scheduled_start` up to but not including its `scheduled_end`, so back-to-back events where one ends exactly when the next begins are allowed, and any genuine overlap is rejected with `ERR_EVENT_OVERLAP` (HTTP 409). Every previously created event of the target counts toward the overlap check regardless of its status. The event list supports an optional `kind` filter alongside pagination.

Scheduling a referendum is gated on the council's first answer. A `REFERENDUM` event may only be created while the target's latest recorded `COUNCIL_VOTE` outcome is `FAILED` with a `yes_share_pct` of at least 50.00 — the referendum band described below; creating one in any other circumstance is rejected with `ERR_REFERENDUM_NOT_AVAILABLE` (HTTP 409). A target may therefore host several referenda in sequence, each gated only on that same latest council-vote outcome.

When the scheduled moment passes, the clerk records the outcome. Recording an outcome on a `PUBLIC_HEARING` moves it to `HELD`; the hearing request must not carry `yes_votes` or `no_votes` at all — supplying either against a hearing is rejected with `ERR_INVALID_STATE` (HTTP 409). Recording on a vote or referendum requires `yes_votes` and `no_votes`, each at least zero, whose sum must be greater than zero (a missing vote count, a negative count, or a zero sum is rejected with `ERR_INVALID_REQUEST`, HTTP 422), and computes `yes_share_pct` — the yes votes as a percentage of all votes cast, rounded half-up to two decimal places. The outcome rules differ by kind, and the boundary comparisons are pinned:

- A `COUNCIL_VOTE` **passes** when `yes_share_pct` is at least 60.00 — a supermajority is required, so exactly 60.00 passes and 59.99 fails. A passed council vote sets the target's `council_approved` to true and increments the target's `version` by 1 (its `updated_at` refreshes with it; the target's `status` does not change on a pass). Additionally, a council vote may only be recorded `PASSED` or `FAILED` once the public has had its say with proper notice: at least one `PUBLIC_HEARING` of the same target must be `HELD` with its `scheduled_end` at least 7 days before the current logical clock; recording a council-vote outcome without such a hearing is rejected with `ERR_HEARING_NOTICE` (HTTP 409).
- A `COUNCIL_VOTE` **fails** in one of two bands. When `yes_share_pct` is at least 50.00 but below 60.00, the margin is close enough that the public gets the final word: the event records `FAILED`, the target stays in `MUNICIPAL_REVIEW`, and a `REFERENDUM` may be scheduled — no target rejection occurs. When `yes_share_pct` is below 50.00, the vote has failed decisively and the target's rejection cascade fires (see §3.8).
- A `REFERENDUM` **passes** on a strict majority: `yes_share_pct` greater than 50.00, so exactly 50.00 fails and 50.01 passes. A passed referendum sets the target's `council_approved` to true and likewise increments the target's `version` by 1. A failed referendum fires the target's rejection cascade (see §3.8).

Recording an outcome on an event of the wrong kind — for example, recording votes against a hearing, or recording an outcome for an event not in `SCHEDULED` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Regulatory Approval and Rate-Base Admission

With `council_approved` true, a `RegulatoryOfficer` prepares and files the commission application in one step. Filing before council approval is rejected with `ERR_APPROVAL_PREREQ` (HTTP 409). The application carries the agreed `purchase_price_cents` (greater than zero) and the ratemaking approach the utility will argue for: `rate_base_method` is either `AS_PAID` or `DEPRECIATED_ORIGINAL_COST`. When the method is `DEPRECIATED_ORIGINAL_COST`, the application must also carry `original_cost_less_depreciation_cents`, the seller's net book cost; otherwise that field is optional. The application's `filing_round` starts at 1. The application is created already `FILED` (passing through `PREPARED`), and its filing automatically advances the target `MUNICIPAL_REVIEW → REGULATORY_REVIEW`, incrementing the target's `version` by 1.

The `Commissioner` then decides the filed application, naming the `outcome`. Three outcomes exist, with distinct consequences:

- **`APPROVED`.** The commission computes the rate-base admission and the target advances `REGULATORY_REVIEW → CLOSING`, copying the admitted amounts onto the target and incrementing its `version` by 1.
- **`DENIED`.** The application is terminal, and the denial fires the target's rejection cascade (§3.8).
- **`REMANDED`.** The application returns to the utility for rework, keeping the target in `REGULATORY_REVIEW`.

**Rate-base admission** on approval works as follows. The premium cap is ten percent of the target's `selected_value_cents`, rounded half-up to a whole cent. Under the `AS_PAID` method, the commission admits up to fair value plus that acquisition premium: the as-paid admission is the purchase price or the selected value plus the premium cap, whichever is smaller. Under the `DEPRECIATED_ORIGINAL_COST` method, the cap is instead the seller's net book cost: the base admission is the purchase price or `original_cost_less_depreciation_cents`, whichever is smaller. The admitted rate base is then the base admission capped once more against the capital-need ceiling: the target's `filing_estimate_cents` plus the `selected_value_cents` plus the premium cap, with the admitted amount the smaller of the two. The result is recorded as the application's `admitted_rate_base_cents`, and the excess of price over admission — the purchase price minus the admitted rate base — is recorded as `disallowed_premium_cents`. Both fields also land on the target as it moves to `CLOSING`.

A remand is not the end. The `RegulatoryOfficer` may refile a `REMANDED` application, which returns it to `FILED`, bumps `filing_round` by one, and must restate the full application payload — `purchase_price_cents` and `rate_base_method` are required on every refile (with `original_cost_less_depreciation_cents` again required when the new method is `DEPRECIATED_ORIGINAL_COST`) and replace the previously filed values. Refiling is the second OCC-guarded write: the request must carry `expected_target_version` matching the target's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful refile increments the target's `version` by 1.

### 3.6. Employee Transition and Union Assumption

The people who run the municipal system move under their own track. An `HRDirector` registers each municipal employee for transition against a target in any status with an `employee_ref`, their completed `years_of_service` (at least zero), their `weekly_salary_cents` (greater than zero), and whether the employee is `union_covered` by a collective bargaining agreement. Each registration starts in `PENDING`.

Offer responses may be recorded while the target is in `VALUATION`, `MUNICIPAL_REVIEW`, `REGULATORY_REVIEW`, or `CLOSING`; recording a response outside those statuses is rejected with `ERR_INVALID_STATE` (HTTP 409). The `response` takes three values, and the union rule is strict: a union-covered employee may not decline — declining a union-covered employee is rejected with `ERR_UNION_ASSUMPTION_REQUIRED` (HTTP 409) — and a non-union employee may not be recorded `ASSUMED`, which draws the same error.

- **`ACCEPTED`.** The employee joins the acquirer; `severance_weeks` and `severance_cents` are both zero.
- **`DECLINED`.** Non-union only. Severance is computed by service tier: at least 10 years of service earns 8 weeks; at least 5 years (but fewer than 10) earns 4 weeks; at least 1 year (but fewer than 5) earns 2 weeks; fewer than 1 year earns 1 week. The boundaries are inclusive — exactly 5 years earns 4 weeks, exactly 10 years earns 8, and exactly 0 years earns 1. `severance_cents` is the `severance_weeks` multiplied by the employee's `weekly_salary_cents`.
- **`ASSUMED`.** Union only. The union agreement is assumed in full; `severance_weeks` and `severance_cents` are both zero.

Employees still in `PENDING` when the target is rejected are swept to `WITHDRAWN` with severance remaining zero (§3.8).

### 3.7. Closing: Capital Execution, Customer Migration, and Tariff Consolidation

**Capital execution.** The deferred-maintenance plan that justified the deal is executed while the deal matures. A `TransitionManager` schedules a `PLANNED` capital item into an execution window by supplying `window_start` and `window_end`; the end must come strictly after the start, otherwise scheduling is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Scheduling is only possible once the item's assessment is `ACCEPTED` and the item's target is in `VALUATION` or a later non-terminal status; anything earlier is rejected with `ERR_INVALID_STATE` (HTTP 409). Crews are finite: at every instant of the requested window, the sum of `crews_required` over this item plus all other `SCHEDULED` items of the same target whose windows contain that instant must not exceed 3 crews per target; sibling windows are likewise treated as half-open — they contain their `window_start` but not their `window_end` — so back-to-back execution windows do not overlap. A window that would push concurrent crew demand above 3 at any instant is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409). A scheduled item may be marked executed once the logical clock has reached its `window_start` — executing earlier is rejected with `ERR_WINDOW_NOT_OPEN` (HTTP 409) — and only while the target is in `CLOSING` or `INTEGRATED`; execution moves the item to `EXECUTED`.

**Customer migration.** A `TransitionManager` registers the municipality's legacy customer accounts against the target in any status, each with its legacy account number `account_ref` (unique within the target; a repeat is rejected with `ERR_DUPLICATE`, HTTP 409), the `deposit_cents` the municipality holds (at least zero), and the legacy accounts-receivable balance `ar_balance_cents` owed (at least zero). Accounts start in `LEGACY`.

Migration becomes possible once the target is in `CLOSING` and the billing records have moved: the target's `BILLING_RECORDS` transition item must be `DONE`, otherwise migration is rejected with `ERR_TRANSITION_PREREQ` (HTTP 409); a target not in `CLOSING` is rejected with `ERR_INVALID_STATE` (HTTP 409). On migration the deposit settles against the arrears in a fixed waterfall order. First, `deposit_offset_cents` is the deposit or the outstanding AR balance, whichever is smaller. Second, `new_ar_balance_cents` is the AR balance minus that offset — what carries into the acquirer's billing system. Third, `refund_cents` is the deposit minus the offset — the remainder returned to the customer. The settlement conserves both sides: refund plus offset equals the original deposit, and new AR plus offset equals the original AR balance. The account moves to `MIGRATED`.

An account with nothing left to settle may instead be orphaned — moved `LEGACY → ORPHANED` while the target is in `CLOSING` — but only when both `ar_balance_cents` and `deposit_cents` are exactly zero; orphaning an account with money still on it is rejected with `ERR_ACCOUNT_NOT_SETTLED` (HTTP 409).

**Tariff consolidation.** Rate consolidation is its own debate, and a `RegulatoryOfficer` opens it by creating a tariff case against a target in any status with a `mode` — `SINGLE_TARIFF` to fold the acquired customers onto the acquirer's consolidated tariff, or `STAND_ALONE` to keep them on their own — plus a `representative_old_bill_cents`, the representative monthly bill under legacy rates (greater than zero), and a `consolidated_monthly_bill_cents`, the proposed consolidated monthly bill (greater than zero). The case starts in `DRAFT`.

Adopting the case requires the target to be in `REGULATORY_REVIEW` or `CLOSING`, and no other `ADOPTED` tariff case may exist for the target (a second adoption is rejected with `ERR_DUPLICATE`, HTTP 409). A `SINGLE_TARIFF` adoption further requires the target's regulatory application to be `APPROVED`; adopting single-tariff pricing before commission approval is rejected with `ERR_APPROVAL_PREREQ` (HTTP 409). Adoption computes `phase_in_years`, the number of years needed to reach the consolidated bill under the annual increase cap: the cap per year is five percent of the representative old bill, rounded half-up to a whole cent; the gap is the consolidated bill minus the representative old bill; if the gap is zero or negative, the phase-in is 0 years; otherwise the phase-in is the gap divided by the annual cap, rounded **up** to a whole year — so a gap exactly equal to some whole multiple of the cap yields exactly that many years, never one more. The case moves to `ADOPTED` and stores the computed `phase_in_years`.

With an `ADOPTED` tariff case in place, migrated accounts may be consolidated onto the tariff, moving `MIGRATED → CONSOLIDATED`; consolidation without an adopted case is rejected with `ERR_TARIFF_NOT_ADOPTED` (HTTP 409). No target-status gate applies beyond the account being `MIGRATED` — an adopted case by construction implies the target reached at least `REGULATORY_REVIEW` at adoption time, and consolidation remains available thereafter.

**Resolving the checklist and closing.** The four transition items are resolved by the `TransitionManager`, optionally recording a `resolution_note`, but only while the target is in `CLOSING` — resolving earlier is rejected with `ERR_INVALID_STATE` (HTTP 409). The `DEPOSITS` item carries an extra gate: it can only be resolved once no customer account of the target remains in `LEGACY`; attempting it sooner is rejected with `ERR_ACCOUNTS_PENDING` (HTTP 409).

Closing the transaction — moving the target `CLOSING → INTEGRATED` — is the final gate, and it checks three things: all four transition items must be `DONE` (otherwise `ERR_TRANSITION_INCOMPLETE`, HTTP 409), no customer account may remain in `LEGACY` (otherwise `ERR_ACCOUNTS_PENDING`, HTTP 409), and no employee transition may remain in `PENDING` (otherwise `ERR_EMPLOYEES_PENDING`, HTTP 409). A successful close increments the target's `version` by 1.

### 3.8. Rejection Cascade

A deal dies in two ways: a decisively failed council vote or a failed referendum while the target is in `MUNICIPAL_REVIEW`, or a commission `DENIED` decision. Either way, the target moves to `REJECTED`, and the rejection cascades through everything still in flight. Every `OPEN` or `FINALIZED` valuation case of the target moves to `SUPERSEDED`, and every `SUBMITTED` or `SELECTED` valuation entry of those cases moves to `NOT_SELECTED`. Every `PENDING` transition item moves to `BLOCKED`. Every `PENDING` employee transition moves to `WITHDRAWN`, with severance remaining zero. The target's `version` increments by 1. `REJECTED` and `INTEGRATED` are terminal: no further transitions out of them exist.

## 4. Endpoint Definitions

Status codes follow one rule throughout: creating a new resource returns 201, while every other successful operation — reads, actions, and state transitions — returns 200. Request and response shapes are defined by the workflows in §3; the table below is a routing summary only. All resources are mounted under `/acquisitions`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | SystemAdmin |
| POST | `/acquisitions/targets` | Create an acquisition target; auto-creates the four transition items | AcquisitionAnalyst |
| GET | `/acquisitions/targets/{id}` | Get a target | All roles |
| GET | `/acquisitions/targets` | List targets with pagination | All roles |
| POST | `/acquisitions/targets/{id}/close` | Close the transaction: `CLOSING` → `INTEGRATED` | TransitionManager |
| POST | `/acquisitions/targets/{id}/assessments` | Create a condition assessment in `DRAFT` | AcquisitionAnalyst |
| GET | `/acquisitions/targets/{id}/assessments` | List assessments of a target | All roles |
| GET | `/acquisitions/assessments/{id}` | Get an assessment | All roles |
| POST | `/acquisitions/assessments/{id}/submit` | Submit a `DRAFT` assessment for engineering review | AcquisitionAnalyst |
| POST | `/acquisitions/assessments/{id}/accept` | Accept a `SUBMITTED` assessment (segregation of duties) | EngineeringReviewer |
| POST | `/acquisitions/assessments/{id}/reject` | Reject a `SUBMITTED` assessment back to `DRAFT` | EngineeringReviewer |
| POST | `/acquisitions/assessments/{id}/capital-items` | Add a capital need item to a `DRAFT` assessment | AcquisitionAnalyst |
| GET | `/acquisitions/assessments/{id}/capital-items` | List capital items of an assessment | All roles |
| GET | `/acquisitions/capital-items/{id}` | Get a capital item | All roles |
| POST | `/acquisitions/capital-items/{id}/schedule` | Schedule a `PLANNED` item into an execution window | TransitionManager |
| POST | `/acquisitions/capital-items/{id}/execute` | Mark a `SCHEDULED` item executed | TransitionManager |
| POST | `/acquisitions/capital-items/{id}/split` | Split a `PLANNED` item into two child items | AcquisitionAnalyst |
| POST | `/acquisitions/capital-items/{id}/cancel` | Cancel a `PLANNED` item | AcquisitionAnalyst |
| POST | `/acquisitions/targets/{id}/valuation-cases` | Open a valuation case (OCC-guarded; supersedes any prior `OPEN` case) | AcquisitionAnalyst |
| GET | `/acquisitions/targets/{id}/valuation-cases` | List valuation cases of a target | All roles |
| GET | `/acquisitions/valuation-cases/{id}` | Get a valuation case | All roles |
| POST | `/acquisitions/valuation-cases/{id}/entries` | Submit an appraisal entry into an `OPEN` case | Appraiser |
| GET | `/acquisitions/valuation-cases/{id}/entries` | List entries of a case | All roles |
| POST | `/acquisitions/valuation-cases/{id}/finalize` | Select one entry and finalize the case | AcquisitionAnalyst |
| POST | `/acquisitions/targets/{id}/council-events` | Schedule a public hearing, council vote, or referendum | MunicipalClerk |
| GET | `/acquisitions/targets/{id}/council-events` | List council events of a target | All roles |
| GET | `/acquisitions/council-events/{id}` | Get a council event | All roles |
| POST | `/acquisitions/council-events/{id}/record-outcome` | Record the outcome of a hearing, vote, or referendum | MunicipalClerk |
| POST | `/acquisitions/targets/{id}/regulatory-applications` | Create and immediately file a regulatory application | RegulatoryOfficer |
| GET | `/acquisitions/targets/{id}/regulatory-applications` | List regulatory applications of a target | All roles |
| GET | `/acquisitions/regulatory-applications/{id}` | Get a regulatory application | All roles |
| POST | `/acquisitions/regulatory-applications/{id}/decide` | Commission decides a `FILED` application | Commissioner |
| POST | `/acquisitions/regulatory-applications/{id}/refile` | Refile a `REMANDED` application (OCC-guarded) | RegulatoryOfficer |
| POST | `/acquisitions/targets/{id}/customer-accounts` | Register a legacy customer account | TransitionManager |
| GET | `/acquisitions/targets/{id}/customer-accounts` | List customer accounts of a target | All roles |
| GET | `/acquisitions/customer-accounts/{id}` | Get a customer account | All roles |
| POST | `/acquisitions/customer-accounts/{id}/migrate` | Migrate a `LEGACY` account | TransitionManager |
| POST | `/acquisitions/customer-accounts/{id}/consolidate` | Consolidate a `MIGRATED` account onto the tariff | TransitionManager |
| POST | `/acquisitions/customer-accounts/{id}/orphan` | Orphan a fully settled `LEGACY` account | TransitionManager |
| GET | `/acquisitions/targets/{id}/transition-items` | List transition items of a target | All roles |
| GET | `/acquisitions/transition-items/{id}` | Get a transition item | All roles |
| POST | `/acquisitions/transition-items/{id}/resolve` | Mark a `PENDING` transition item `DONE` | TransitionManager |
| POST | `/acquisitions/targets/{id}/employee-transitions` | Register a municipal employee for transition | HRDirector |
| GET | `/acquisitions/targets/{id}/employee-transitions` | List employee transitions of a target | All roles |
| GET | `/acquisitions/employee-transitions/{id}` | Get an employee transition | All roles |
| POST | `/acquisitions/employee-transitions/{id}/offer-response` | Record offer response: `ACCEPTED`, `DECLINED`, or `ASSUMED` | HRDirector |
| POST | `/acquisitions/targets/{id}/tariff-cases` | Create a tariff consolidation case | RegulatoryOfficer |
| GET | `/acquisitions/targets/{id}/tariff-cases` | List tariff cases of a target | All roles |
| GET | `/acquisitions/tariff-cases/{id}` | Get a tariff case | All roles |
| POST | `/acquisitions/tariff-cases/{id}/adopt` | Adopt a `DRAFT` tariff case | RegulatoryOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_SEGREGATION_OF_DUTY` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_EVENT_OVERLAP` | 409 |
| `ERR_HEARING_NOTICE` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_METHOD_NOT_PERMITTED` | 422 |
| `ERR_REFERENDUM_NOT_AVAILABLE` | 409 |
| `ERR_APPROVAL_PREREQ` | 409 |
| `ERR_TRANSITION_PREREQ` | 409 |
| `ERR_ACCOUNTS_PENDING` | 409 |
| `ERR_TRANSITION_INCOMPLETE` | 409 |
| `ERR_EMPLOYEES_PENDING` | 409 |
| `ERR_ACCOUNT_NOT_SETTLED` | 409 |
| `ERR_UNION_ASSUMPTION_REQUIRED` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_ASSESSMENT_EMPTY` | 409 |
| `ERR_INVALID_SPLIT` | 422 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_TARIFF_NOT_ADOPTED` | 409 |
