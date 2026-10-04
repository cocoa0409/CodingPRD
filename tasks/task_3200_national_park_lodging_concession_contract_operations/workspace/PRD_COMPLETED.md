# National Park Concession Operations API — Product Requirements Document

## 1. Introduction

Operating lodging, food service, retail, and tour businesses inside a national park is unlike ordinary hospitality: the concessioner runs on government-owned land and government-owned buildings, under a multi-year concession contract that caps what can be charged, dictates what must be maintained, and dictates what happens to the buildings when the contract ends. Rates are not set by the market — they are submitted by the concessioner and approved by the federal agency against a comparability study of similar properties. Seasonality is extreme, workforces are seasonal and must be housed and transported into remote locations, and the contract carries explicit environmental obligations around waste, water, and wildlife.

This document specifies a REST API that administers the full operational lifecycle of such a concession contract: contract setup and activation, season planning, rate filing and agency approval against comparability studies, reservation intake under a lottery-style release window, monthly gross-receipts reporting per service line and the resulting franchise fee statements, capital improvement projects on government assets with leasehold surrender interest accounting, seasonal hiring with employee housing and transport, environmental incident management with corrective-plan deadlines, and finally contract expiration and recompetition with asset transfer to a designated successor.

The system is deliberately audit-oriented. Roles are split between concessioner staff and agency staff so that no single actor both submits and approves the same artifact. Money is tracked in integer cents, and the order in which rounding is applied is pinned by contract. Time is a first-class input: the server runs on a logical clock that drives season opening and closing, reservation allocation runs, no-show sweeps, and contract expiry, so that multi-year seasonal behavior can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational capacity in which the user acts. A request missing either header, or carrying a value the server does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes eleven roles, spelled exactly as follows: `AgencyContractingOfficer`, `AgencyRateAnalyst`, `ConcessionerRateManager`, `ConcessionerOpsManager`, `ConcessionerFrontDesk`, `ConcessionerAccountant`, `AgencyFinancialAuditor`, `ConcessionerMaintenanceChief`, `ConcessionerHRManager`, `AgencyEnvironmentalInspector`, and `SystemTestHarness`.

For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on a gross receipts report at submission time — but it never compares it to any resource's `id`. Its primary uses are audit recording and segregation-of-duties comparisons: when the rules require that the user approving an artifact differ from the user who submitted it, the comparison is made between the `X-User-ID` values on the two requests.

Role assignments in brief: the `AgencyContractingOfficer` owns contract creation, service-line authorization and suspension, capital project authorization and approval, and all recompetition transitions. The `AgencyRateAnalyst` registers comparability studies and adjudicates rate filings. The `ConcessionerRateManager` submits and revises rate filings. The `ConcessionerOpsManager` activates contracts, manages seasons and room classes, reports environmental incidents, and submits corrective plans. The `ConcessionerFrontDesk` takes reservations, cancellations, and check-ins. The `ConcessionerAccountant` files gross receipts reports and issues and pays franchise fee statements. The `AgencyFinancialAuditor` accepts or returns receipts reports. The `ConcessionerMaintenanceChief` proposes and completes capital projects. The `ConcessionerHRManager` manages housing units, seasonal hires, and transport vouchers. The `AgencyEnvironmentalInspector` reviews incidents, requires corrective plans, closes incidents, and may also report incidents. The `SystemTestHarness` exists solely to drive the logical clock and performs no business operation.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; unlike resource `created_at`/`updated_at` (§2.6), it is taken from the wall clock, not the logical clock.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and a client may request at least 1 and at most 100 items per page. The `offset` parameter says how many items to skip before the first returned item and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are always sorted by creation timestamp ascending — the oldest resource comes first. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching resources and `has_more` reports whether further items exist beyond the returned page.

### 2.4. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock, independent of the wall clock. Before any clock-setting call, the logical clock reads exactly `2026-09-01T00:00:00Z` — a fixed startup default that never falls back to wall-clock time. The `SystemTestHarness` may set the logical clock to a supplied `current_utc` instant. Advancing the clock is the trigger for every system-driven transition in the system: seasons open when the clock reaches their opening instant and close when it reaches their closing instant; the reservation allocation run fires when the lottery window closes; no-show sweeps fire when grace periods elapse; approved rate filings expire at season close; and a contract expires when the clock reaches its `end_date`. A comparability study whose `valid_through` the clock has passed is moved to `STALE`. A single clock advance must apply every time-based transition whose precondition now holds. The clock may be set backwards as well as forwards; all sweeps are conditional on their preconditions, so no transition is ever undone.

### 2.5. Contract Hierarchy and Cascading Consistency

Every business resource in the system belongs to exactly one concession contract and is addressed beneath it. When a contract changes state in a way that alters what its children may do, the cascade is applied immediately: a contract that expires pushes every unreconciled season to closed and suspends every service line, and transition finalization terminates or decommissions operational structures while recreating their equivalents on the successor contract. Cascades in the other direction also exist: several child-level events — season reconciliation, rate filing approval, capital project approval, and the creation of filings, receipts reports, and reservations — bump the contract's `version` by one as a bubble-up effect, refreshing the contract's `updated_at` in the process. Nested paths are validated left to right: the contract identifier is resolved first (an unknown one yields `ERR_CONTRACT_NOT_FOUND`), and only then is the child identifier resolved within that contract, with a missing child producing the corresponding not-found error — for example `ERR_SEASON_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, or `ERR_RESERVATION_NOT_FOUND` — for the first path segment that fails to resolve.

### 2.6. Common Resource Properties

Every resource in this system carries a standard set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation. Consistent with §2.4, `created_at` and `updated_at` are stamped from the server's logical clock — never the wall clock — so a resource created or mutated while the logical clock reads a given instant carries that instant in its timestamps. The `version` is an integer starting at one that increments by one on every mutation of the resource. Because every entity in this system participates in audit and optimistic-concurrency behavior, all entities carry the full common field set — `id`, `created_at`, `updated_at`, and `version` — with no exceptions.

### 2.7. Money, Precision, and Rounding

All monetary quantities in this API are integer counts of cents — a field named with the `_cents` suffix holds a whole number of cents, never a decimal. Every computed cent value is produced with round-half-up rounding: a fractional remainder of exactly one half rounds away from zero. Wherever a calculation involves multiple rounding points, the order in which rounding is applied is part of the specification and is stated alongside the calculation; two evaluation orders that differ only in where rounding occurs are legitimate sources of different results, and the payable figure is always the one this document designates.

### 2.8. Optimistic Concurrency Control

Three creation endpoints are guarded by optimistic concurrency control against the parent contract. When a client creates a rate filing, a gross receipts report, or a reservation, the request body must carry `expected_contract_version`, holding the contract `version` the client last observed. If the contract's current `version` differs from the supplied value — because, for example, another filing was approved in the meantime and the approval bumped the contract's version — the creation is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). This is a stale-view rejection, not a timing rule: it fires whenever the client's view of the contract predates the current version, regardless of how the versions came to diverge. Endpoints other than these three creations do not accept a version field.

### 2.9. Segregation of Duties

Two approval steps in the system are segregation-of-duties gates enforced by comparing `X-User-ID` values. A rate filing may only be approved by a user whose `X-User-ID` differs from the `X-User-ID` that submitted the filing, and a gross receipts report may only be accepted by a user whose `X-User-ID` differs from the `X-User-ID` recorded on the report at submission. Violating either gate is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because the submitting and approving roles are distinct in both cases — rate manager versus rate analyst, and concessioner accountant versus agency auditor — the duty split is structural, and the `X-User-ID` comparison is the backstop that prevents one operator from wearing both hats.

### 2.10. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. Authentication comes first: missing or invalid `X-User-ID` or `X-User-Role` headers are rejected before anything else, and a role not permitted for the operation is rejected second. Existence checks follow — path identifiers are resolved left to right, and then foreign references in the request body (the season, room class, comparability study, service line, housing unit, or revision filing a payload names) are verified to exist within the same contract. Contract-level operational state is checked next: a contract must be `ACTIVE` for ordinary operational writes, and only transition finalization may proceed while the contract is `TRANSITION_PENDING`; a violation yields `ERR_CONTRACT_NOT_OPERATIONAL`. Target-entity state checks come after that — a filing must be `SUBMITTED` or `UNDER_REVIEW` for adjudication actions, a report must be `DRAFT` or `RETURNED` to be submitted, a hire must be `HIRED` or `ARRIVED` for its lifecycle actions — with violations producing `ERR_INVALID_STATE`. Only then are business rules evaluated, in this relative order: environmental safety gates, temporal window rules, cross-entity state requirements (a registered study, an open season, an active room class, an authorized service line), then hard business constraints such as the rate cap, the lottery window, housing capacity, and fiscal gates such as duplicate periods and cost overruns, then segregation of duties, and finally the optimistic-concurrency version check.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Concession Contract

An `AgencyContractingOfficer` opens the engagement by creating the concession contract itself. The creation payload carries the `park_code` identifying the park, a `contract_number` that must be unique across the entire system (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the `term_months` of the contract, the `start_date` on which the contract takes effect, the `franchise_fee_rate` the concessioner will owe on gross receipts, the `employee_housing_capacity` giving the total seasonal employee bed capacity — an integer of at least 1 —, the `lsi_annual_schedule_type` choosing between `LINEAR` and `DECLINING_BALANCE` surrender-interest schedules, and the `environmental_plan_due_day_of_year`, a day-of-year between 1 and 365 by which the annual environmental plan must be filed (the due day is recorded on the contract; the API exposes no environmental-plan filing resource, and no endpoint consumes it). The term must be a positive whole number of years: `term_months` must be greater than zero and evenly divisible by twelve. The fee rate must be greater than zero and no greater than 0.20. From `start_date` and `term_months` the server computes `end_date` by advancing the start date by the full term in months. A new contract begins life in `DRAFT` status.

While the contract is `DRAFT`, the operational scaffolding is erected. These setup writes — service lines, seasons, and room classes — are not gated on the contract being `ACTIVE`; they are the readiness inputs to activation and are accepted while the contract is `DRAFT` (and, per §2.10, while it is `TRANSITION_PENDING`). The `AgencyContractingOfficer` creates the four service lines the contract form requires — one each of `line_type` `LODGING`, `FOOD`, `RETAIL`, and `TOURS`. Each service line is created with `authorized` and `separate_reporting_required` flags, both of which default to true when omitted; under this contract form every line reports its gross receipts separately. Service lines begin in `AUTHORIZED` status. The `ConcessionerOpsManager` plans operating seasons, each identified by a calendar `year` of 2000 or later, an `open_date`, a `close_date` that must fall strictly after the opening, a `lottery_open_date` that must fall strictly before the opening, and a `lottery_window_hours` of at least one. Violations of the open/close ordering produce `ERR_INVALID_DATE_RANGE`; a lottery release that is not strictly before the season opening, or a window shorter than one hour, produces `ERR_LOTTERY_WINDOW`. The server derives each season's `month_offset`, the whole number of months elapsed between the contract's `start_date` and the season's `open_date`, rounded down. New seasons begin `PLANNED`. Room classes are also registered now, each with a `code` unique within the contract (for example `CABIN_STANDARD`), a `total_rooms` physical room count of at least one, and the `peak_season_months` — a non-empty array of calendar month numbers from 1 to 12 used for comparability matching. Room classes begin `ACTIVE`.

Activation is the concessioner's step: a `ConcessionerOpsManager` activates the contract, moving it from `DRAFT` to `ACTIVE`; a contract not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Activation is gated on operational readiness — the contract must have at least one operating season and must have all four service line records present, one of each line type; otherwise the request is rejected with `ERR_CONTRACT_NOT_ACTIVATABLE`. A successful activation increments the contract's `version` by one. Ordinary operational writes are only accepted while the contract is `ACTIVE`; against a contract in any other state they are rejected with `ERR_CONTRACT_NOT_OPERATIONAL`.

### 3.2. Comparability Studies and the Rate Filing Cycle

Concession rates are not market-set. Before any rate can be approved, an `AgencyRateAnalyst` registers a comparability study against the contract. The study carries a `title`, the `prepared_at` instant, a `valid_through` horizon that must fall strictly after `prepared_at` (a reversed range yields `ERR_INVALID_DATE_RANGE`), and a list of `comparables`. Each comparable names a `property_name`, a `nightly_rate_cents`, and a positive `weight`, and the study must contain at least three comparables. On registration the server computes the study's `weighted_mean_cents`: each comparable's nightly rate is multiplied by its weight, the products are summed, the sum of the weights is taken, the first sum is divided by the second, and the quotient is rounded half-up to a whole number of cents. Studies begin in `REGISTERED` status; a study whose validity horizon has passed — the logical clock strictly after `valid_through`, with the exact instant still treated as valid — is moved to `STALE` by the clock sweep. The lifecycle also admits an `ARCHIVED` status, though no operation in this contract moves a study there.

With a registered study in hand, a `ConcessionerRateManager` submits a rate filing naming the `season_id` and `room_class_id` it covers, the `reference_study_id` it cites, and the `submitted_rates` — an array of exactly three entries, one for each occupancy band `SOLO`, `DOUBLE`, and `FAMILY`, each entry carrying a positive `nightly_rate_cents`. Because this creation is OCC-guarded, the payload must also carry `expected_contract_version`; a mismatch against the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). Filings are only accepted while the target season is `PLANNED` or `OPEN`; a filing aimed at a `CLOSED` or `RECONCILED` season is rejected with `ERR_SEASON_NOT_OPEN_FOR_FILING`. The cited study must still be valid for the season: if the study's `valid_through` falls strictly before the season's `open_date` — a `valid_through` exactly equal to the open instant is accepted — the submission is rejected with `ERR_STUDY_EXPIRED`. The target room class must be `ACTIVE`, or the submission is rejected with `ERR_ROOM_CLASS_INACTIVE`. Creating a filing bumps the contract's `version` by one, and if a filing in `SUBMITTED` status already exists for the same season and room class, the prior filing is pushed to `SUPERSEDED` — submitting a fresh filing for a slot that already has a live submission quietly displaces it.

Adjudication belongs to the `AgencyRateAnalyst`. Starting review moves a `SUBMITTED` filing to `UNDER_REVIEW`, and is permitted only while the cited study is still `REGISTERED`; otherwise the request is rejected with `ERR_STUDY_NOT_CURRENT`. Rejection is possible from either `SUBMITTED` or `UNDER_REVIEW` and requires a `reason` in the request body; a rejected filing lands in `REJECTED`. Approval, available only from `UNDER_REVIEW`, applies three gates. The study is re-checked: it must still be `REGISTERED` at approval time, or the approval fails with `ERR_STUDY_NOT_CURRENT`. The rate cap is then enforced band by band: the cap is the cited study's `weighted_mean_cents` multiplied by 1.05, with the product rounded half-up to a whole number of cents, and every band's submitted nightly rate must be at most that cap — a rate exactly equal to the cap passes, a rate one cent above it fails with `ERR_RATE_EXCEEDS_COMPARABILITY`. Finally, segregation of duties: the approving user's `X-User-ID` must differ from the submitting user's, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Approval freezes the filing's economics. The filing's `effective_date` is set to the season's `open_date`, and its `approved_weighted_mean_cents` is pinned to the study's `weighted_mean_cents` as of the approval moment, so that a later change in study state cannot rewrite history. Any previously `APPROVED` filing for the same season and room class is moved to `SUPERSEDED` — a supersession the system performs automatically whenever a subsequent filing for the same slot reaches `APPROVED` — and the contract's `version` is bumped by one. An `APPROVED` filing eventually expires of its own accord: when the logical clock reaches the season's `close_date`, the filing moves to `EXPIRED`.

Rejection is not the end of the road. A `ConcessionerRateManager` may submit a revision by creating a new filing whose `revision_of_id` references a `REJECTED` filing of the same contract and which covers the same season and room class as the rejected filing. A referenced filing that is not `REJECTED` yields `ERR_INVALID_STATE`; a referenced filing covering a different season or room class yields `ERR_INVALID_REQUEST` (HTTP 400). The revision is created fresh in `SUBMITTED` status, while the rejected filing remains `REJECTED` — the loop from rejection back to submission is cyclic and may repeat. For a first filing, `revision_of_id` is simply absent.

### 3.3. Reservations, the Lottery Window, and Deposits

Reservations are created by the `ConcessionerFrontDesk` against a specific season and room class, and their intake is governed by the season's lottery window. A reservation request names the `season_id`, the `room_class_id`, a `guest_ref` string identifying the guest, the `check_in_date` and `check_out_date`, the `occupancy_band` (`SOLO`, `DOUBLE`, or `FAMILY`), and — because creation is OCC-guarded — the `expected_contract_version`. Two optional inputs refine pricing: `occupancy_mode`, which defaults to `BANDED`, and `beds_occupied`, which is required exactly when the mode is `ACTUAL_HEADCOUNT` and must then be between 1 and 3.

Several gates apply at intake, evaluated after the generic existence and state checks. The season must be `PLANNED` or `OPEN`, else `ERR_SEASON_NOT_OPEN`. The room class must be `ACTIVE`, else `ERR_ROOM_CLASS_INACTIVE`. The stay must lie entirely inside the season — from `open_date` through `close_date` — or the request is rejected with `ERR_STAY_OUTSIDE_SEASON`, and the stay must span at least one whole night, meaning `check_out_date` must fall strictly after `check_in_date`, else `ERR_INVALID_DATE_RANGE`. A request that arrives before the lottery window has opened is rejected with `ERR_LOTTERY_NOT_OPEN`. A guest may not hold two overlapping live reservations: if the same `guest_ref` already holds a non-terminal reservation whose stay overlaps the requested stay, the creation is rejected with `ERR_DUPLICATE_RESERVATION`.

The price quoted at booking comes from the `APPROVED` rate filing for the season and room class, and it depends on the pricing variant. Under the default `BANDED` mode, the `quoted_nightly_rate_cents` is simply the approved filing's nightly rate for the declared `occupancy_band`, regardless of how many guests actually stay. Under `ACTUAL_HEADCOUNT`, the rate follows the exact bed count supplied in `beds_occupied`: one bed prices at the `SOLO` rate, two beds at the `DOUBLE` rate, three beds at the `FAMILY` rate. The two variants deliberately price identical inputs differently — a family-band reservation actually occupied by two guests quotes the family rate under `BANDED` but the double rate under `ACTUAL_HEADCOUNT`. The quoted rate is frozen on the reservation at booking.

From the quote, the server derives the rest of the reservation's money fields. The `nights` of the stay is the whole number of days between check-in and check-out — calendar-day arithmetic is floored, so a sub-24-hour tail beyond a whole number of days does not add a night. The `total_charge_cents` is the quoted nightly rate multiplied by the number of nights. The `deposit_cents` is the total charge multiplied by 0.2, rounded half-up to whole cents, but capped at 50000 cents — the deposit is the smaller of the rounded twenty-percent figure and the cap. A new reservation begins in `REQUESTED` status, and its creation bumps the contract's `version` by one.

Confirmation is not immediate for window-period requests. Pricing, however, always requires an `APPROVED` rate filing for the season and room class: if none exists at intake, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). When the logical clock reaches the end of the lottery window — the `lottery_open_date` plus `lottery_window_hours` hours — the system runs the allocation. Every `REQUESTED` reservation for the season whose stay lies entirely within the season bounds is a candidate. Candidates are processed oldest first by `created_at`, with ties broken by `guest_ref` ascending; the reservation `id` is never used as a tie-break. For each candidate, the system checks every night of the stay: the number of rooms already allocated in that room class for that night must be below the class's `total_rooms`. Nights are treated as half-open intervals from check-in to check-out, so adjacent stays — one guest checking out on the day another checks in — do not conflict. A candidate that fits on every night is confirmed and allocated per night; a candidate that does not fit remains `REQUESTED` as a waitlist entry. Requests created after the window has closed skip the queue and are allocated immediately in arrival order against whatever inventory remains, first-come by `created_at`.

Cancellation by the `ConcessionerFrontDesk` moves the reservation to its terminal `CANCELLED` status, and it behaves differently depending on whether the reservation had been confirmed. Cancelling a still-`REQUESTED` reservation frees nothing and sets `cancellation_fee_cents` to zero — no allocation existed yet. Cancelling a `CONFIRMED` reservation applies the refund policy: if the cancellation occurs fewer than 30 days before the `check_in_date` — strictly less, so a cancellation exactly 30 days out is free — the full deposit is forfeit and `cancellation_fee_cents` equals `deposit_cents`; otherwise the cancellation is free and the fee is zero. Cancelling a confirmed reservation also releases its per-night inventory, and the release triggers waitlist promotion: the longest-waiting `REQUESTED` reservation — again ordered by `created_at` ascending with `guest_ref` ascending as tie-break — that now fits on every night of its stay is promoted to `CONFIRMED`.

Guests who neither arrive nor cancel are swept. If the logical clock passes the `check_in_date` plus a grace of 24 hours — strictly past, so the exact grace endpoint does not yet trigger the sweep — with no check-in recorded, a `CONFIRMED` reservation becomes `NO_SHOW` and forfeits its deposit: `cancellation_fee_cents` is set to `deposit_cents`. A check-in recorded by the front desk before the grace elapses prevents the no-show sweep, and a checked-in reservation is swept to `FULFILLED` at season close. The no-show sweep does not release the reservation's per-night room inventory — the rooms stand empty for the booked stay.

When the season itself closes — the logical clock reaching its `close_date` — every still-`CONFIRMED` reservation is resolved by the close sweep: those whose `check_out_date` falls on or before the close date become `FULFILLED`, and those whose check-out falls after the close date become `NO_SHOW` and forfeit the deposit — `cancellation_fee_cents` is set to `deposit_cents`, matching the grace-period sweep.

### 3.4. Season Lifecycle and Reconciliation

A season's own lifecycle is driven mostly by the clock. A `PLANNED` season opens automatically when the logical clock reaches its `open_date`, moving to `OPEN`. An `OPEN` season closes automatically when the clock reaches its `close_date`, moving to `CLOSED` and triggering the reservation close sweep described above. The final step, from `CLOSED` to `RECONCILED`, is manual: a `ConcessionerOpsManager` reconciles the season once the books are clean. Reconciliation requires that every seasonal hire attached to the season has reached a terminal state — `DEPARTED`, `NO_SHOW`, or `TERMINATED` — and that every gross receipts report whose `period_month` overlaps the season — the calendar month [first-of-month, first-of-next-month) intersecting the season's [open_date, close_date) window — has been `ACCEPTED`; if either condition fails, the request is rejected with `ERR_UNRECONCILED_SEASON`. The environmental gate also applies: a season cannot reconcile while the contract carries an incident in `REPORTED`, `UNDER_REVIEW`, or `CORRECTIVE_PLAN_REQUIRED` status, and such an attempt is rejected with `ERR_OPEN_ENVIRONMENTAL_INCIDENT`. No further environmental-plan check is applied at reconciliation. A successful reconciliation moves the season to `RECONCILED` and bumps the contract's `version` by one as a bubble-up.

### 3.5. Gross Receipts Reporting and Franchise Fee Statements

Reporting is monthly and per service line. A `ConcessionerAccountant` creates a gross receipts report naming the `service_line_id`, the `period_month` in `YYYY-MM` form — a year of 2000 or later and a month from 01 to 12, malformed values rejected with `ERR_INVALID_REQUEST` —, the `gross_receipts_cents` (a non-negative integer), and — because creation is OCC-guarded — the `expected_contract_version`; a stale version is rejected with `ERR_STALE_CONTRACT_VERSION`. Each report belongs to one line and one month: if an `ACCEPTED` report already exists for the same service line and period, a new one is rejected with `ERR_DUPLICATE_PERIOD_REPORT`. The service line must be in `AUTHORIZED` status; against a `SUSPENDED` or `TERMINATED` line the creation is rejected with `ERR_SERVICE_LINE_SUSPENDED`. New reports are created in `DRAFT` status, and creation bumps the contract's `version` by one.

The report then flows through an agency audit loop. Submission by the `ConcessionerAccountant` moves a `DRAFT` report to `SUBMITTED` and records the submitting operator's role and identity in `submitted_by_role` and `submitted_by_user_id`. The `AgencyFinancialAuditor` may then accept the report or return it for rework with a `reason`; acceptance moves it to `ACCEPTED`, return moves it to `RETURNED`. Acceptance is segregation-of-duties gated: the accepting user's `X-User-ID` must differ from the `X-User-ID` recorded at submission, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Acceptance has a downstream consequence: if a franchise fee statement for the same `period_month` is currently `ISSUED`, that statement is marked stale — an internal marker not exposed in the statement's representation, which remains `ISSUED` — and must be reissued, because the accepted figures have changed beneath it. A returned report re-enters the loop: the accountant resubmits it, re-supplying `gross_receipts_cents` in the resubmission body, which moves it back to `SUBMITTED` and records the new submitter identity. The rework loop is cyclic and may repeat.

Once at least one report for a period has been `ACCEPTED`, the `ConcessionerAccountant` issues the franchise fee statement for that `period_month`; with no accepted reports the issuance is rejected with `ERR_NO_ACCEPTED_REPORTS`. The statement month must be unique within the contract — a second statement for a month that already has one, in any status, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The statement's `lines` array carries one row per accepted report in the period, ordered by the reports' creation order, each row holding the `service_line_id`, the line's `line_gross_cents`, and the line's `line_fee_cents`. The fee math is pinned to a per-line-then-sum order: each line's fee is that line's gross receipts multiplied by the contract's `franchise_fee_rate`, rounded half-up to whole cents, and the statement's `total_fee_cents` is the sum of those per-line fees. The statement's `reporting_method` is frozen at issuance as `PER_LINE_ROUNDED`, and that per-line figure is the only payable one. For transparency the statement also carries `aggregate_diagnostic_cents`, computed in the opposite order — all lines' gross receipts summed first, then multiplied by the fee rate and rounded half-up once — which may legitimately differ from the payable total; it is a diagnostic only and is never the amount owed. A new statement is `ISSUED`. Payment by the `ConcessionerAccountant` moves it to `PAID`, records the payment, and renders the statement immutable thereafter. A staled `ISSUED` statement (staled by a later acceptance, per above) may still be paid: payment moves it to `PAID` and, the month now occupied, blocks any reissue under the uniqueness rule.

### 3.6. Capital Projects and Leasehold Surrender Interest

Concessioners are obligated to invest in the government-owned assets they operate, and in return they accrue a leasehold surrender interest — compensation for the unamortized value of improvements if the contract ends. A `ConcessionerMaintenanceChief` proposes a capital project with a `title`, the `asset_ref` identifying the government asset being improved, and a positive `authorized_cost_cents`. Projects begin `PROPOSED`. An `AgencyContractingOfficer` authorizes the project, moving it to `AUTHORIZED`.

Completion is reported by the maintenance chief, who supplies the `actual_cost_cents` and may optionally supply the `in_service_month_offset` — the whole number of months after the contract's `start_date` at which the asset went into service, a non-negative integer. When the offset is omitted it defaults to the contract's current month offset at completion. The actual cost defaults to zero and may be set only while the project is `COMPLETED` and not yet approved; it must be non-negative and may not exceed the authorized cost by more than ten percent — that is, it must be at most the authorized cost multiplied by 1.10 — or the completion is rejected with `ERR_COST_OVERRUN`. At completion the server also computes the project's `accrued_lsi_cents` at the current contract offset.

Approval of a completed project is the contracting officer's step, and it is segregation-of-duties enforced by `X-User-ID` comparison, the same backstop as §2.9: the approving user's `X-User-ID` must differ from the `X-User-ID` of the user who completed the project — the maintenance chief completes, the contracting officer approves, so the duty split is structural and the id comparison is the backstop — and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval moves the project to `APPROVED`, starts leasehold surrender interest accrual at the `in_service_month_offset`, and bumps the contract's `version` by one.

The accrual schedule depends on the contract's `lsi_annual_schedule_type`, and in both variants accrual is measured month by month against the contract's current month offset, counting only months strictly after the in-service offset and never beyond the contract term; each month-step amount — the phase's (or, under `LINEAR`, the whole term's) per-month rate — is rounded half-up to whole cents once, then multiplied by the number of accrued months. Under `LINEAR`, the accrual is straight-line: the per-month step is the authorized cost divided by the term in months, rounded half-up, and the accrued amount at a given offset is that step multiplied by the number of accrued months — the current offset clamped to the term, minus the in-service offset, floored at zero. Under `DECLINING_BALANCE`, accrual is phase-weighted: half of the authorized cost amortizes linearly across the first half of the term months, thirty percent across the next forty percent of the term, and the remaining twenty percent across the final ten percent of the term. Phase windows are computed in whole months with round-half-up: the first phase spans months 1 through round-half-up(0.5·T), the second the next round-half-up(0.4·T) months, and the third the remainder. Within each phase the per-month step is the phase's share of the authorized cost divided by the phase's window length in months, rounded half-up, and the phase contributes that step times the number of months strictly after the in-service offset that fall inside the phase's window and no later than the current offset. The two schedules diverge as offsets cross phase boundaries: an identical project and offset can produce a lower accrued figure under the declining schedule than under the linear one once the offset passes the first phase boundary. Every read of `accrued_lsi_cents` is computed against the current offset, so the figure grows as the logical clock advances. Projects still `PROPOSED` or `AUTHORIZED` (which have no in-service offset yet) report `accrued_lsi_cents` of zero, and an `EXPENDED` project keeps the figure frozen at transition. The completion and approval responses carry the accrual computed at the current offset as of that call.

### 3.7. Seasonal Hiring, Housing, and Transport

Remote lodges live and die by their seasonal workforce. The `ConcessionerHRManager` first registers employee housing units, each with a `unit_code` unique within the contract and a `bed_count` of at least one; units begin `AVAILABLE`. A unit may be taken `OFFLINE`, after which no new hire may be assigned to it.

Hiring a seasonal employee creates a `SeasonalHire` naming the `season_id`, the employing `service_line_id`, an `employee_ref` string, the assigned `housing_unit_id`, and the `arrival_date` and `departure_date`, where departure must fall strictly after arrival. The hire dates must lie within the hiring season — from its `open_date` through its `close_date` inclusive; a hire outside the season is rejected with `ERR_INVALID_DATE_RANGE`. Two optional fields govern transport: `needs_transport`, which defaults to true, and `transport_origin`, the pickup location, which is required exactly when `needs_transport` is true.

Housing capacity is enforced at hire time, against the unit the request names. A hire occupies one bed from the moment of hiring through arrival — `HIRED` and `ARRIVED` hires both occupy beds — and the bed is released when the hire becomes `DEPARTED`, `NO_SHOW`, or `TERMINATED`. The assigned unit must be `AVAILABLE` or the creation is rejected with `ERR_UNIT_OFFLINE`, and the unit must have a free bed for the season: the number of beds already assigned to hires in `HIRED` or `ARRIVED` status for the same season must leave at least one free. If no available unit has a free bed, the creation is rejected with `ERR_HOUSING_FULL`.

When the hire needs transport, creation also books a `TransportVoucher` in `BOOKED` status for the hire — with `origin` set to the hire's `transport_origin`, a single booked seat, and `travel_date` set to the hire's `arrival_date` — and the hire's `transport_voucher_id` records it. Additional vouchers can be booked for a hire directly, each carrying the `hire_id`, an `origin`, a positive `booked_seats` count, and a `travel_date` that must fall within the season.

The hire lifecycle then tracks the season. When the employee shows up, the HR manager marks the hire arrived, moving it from `HIRED` to `ARRIVED`; the linked booked voucher is consumed to `USED` in the same breath. If the logical clock passes the `arrival_date` plus the 24-hour grace — strictly past, as with the reservation sweep — with no arrival recorded, the hire becomes `NO_SHOW`: its housing bed is released and its linked booked voucher is `VOID`. Termination by the HR manager — which requires a `reason` — moves a `HIRED` or `ARRIVED` hire to `TERMINATED`, releases the bed, and voids the linked booked voucher if one exists. A hire who has arrived may later be marked departed, moving from `ARRIVED` to `DEPARTED` and releasing the bed. A booked voucher may also be voided directly by the HR manager, moving it to `VOID`.

### 3.8. Environmental Stewardship and Incident Handling

The contract imposes environmental obligations across three protocols. An incident is reported — by either the `ConcessionerOpsManager` or the `AgencyEnvironmentalInspector` — with a `protocol` of `WASTE`, `WATER`, or `WILDLIFE`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, the `occurred_at` instant, and a free-text `description`. At report time the server computes the `corrective_plan_deadline` as exactly 14 days after `occurred_at`, and the incident begins in `REPORTED` status.

Review belongs to the `AgencyEnvironmentalInspector`, who moves the incident from `REPORTED` to `UNDER_REVIEW` by starting review. If the findings warrant it, the inspector requires a corrective plan, moving the incident to `CORRECTIVE_PLAN_REQUIRED`; the deadline was already fixed at report time, and compliance with it is evaluated when a plan is submitted. The concessioner's response is the corrective plan: the `ConcessionerOpsManager` submits a plan carrying `plan_text`, which returns the incident to `UNDER_REVIEW` — the review loop is cyclic and a further plan requirement may follow. The deadline is hard: if the logical clock has already passed the `corrective_plan_deadline` when the plan is submitted — strictly past; a submission at the exact deadline instant is accepted — the submission is rejected with `ERR_CORRECTIVE_PLAN_LATE`. An incident under review is closed by the inspector, moving it to `CLOSED`, the terminal state.

Open incidents freeze the big moves. Any incident in `REPORTED`, `UNDER_REVIEW`, or `CORRECTIVE_PLAN_REQUIRED` status blocks both season reconciliation and the initiation of contract transition, surfacing as `ERR_OPEN_ENVIRONMENTAL_INCIDENT` in both places.

### 3.9. Expiration, Recompetition, and Asset Transfer

A contract expires on its own: when the logical clock reaches the contract's `end_date`, an `ACTIVE` contract moves to `EXPIRED`. Expiry cascades immediately — every operating season not yet `RECONCILED` and not already `CLOSED` is forced to `CLOSED`, and every service line not already `SUSPENDED` is moved to `SUSPENDED` — and the contract's `version` is bumped by one.

Recompetition begins when an `AgencyContractingOfficer` initiates the transition, moving the contract from `ACTIVE` or `EXPIRED` into `TRANSITION_PENDING`. Initiation demands a clean slate: no environmental incident may be open, else `ERR_OPEN_ENVIRONMENTAL_INCIDENT`, and every capital project on the contract that is still `PROPOSED`, `AUTHORIZED`, or `COMPLETED` must first be brought to `APPROVED` or `EXPENDED` — a live project anywhere in the pipeline blocks initiation with `ERR_OPEN_CAPITAL_PROJECT`. Per the validation order in §2.10, the environmental gate is evaluated first: when both an open incident and a live capital project exist, the request surfaces `ERR_OPEN_ENVIRONMENTAL_INCIDENT`. Initiation bumps the contract's `version`.

While the contract is `TRANSITION_PENDING`, the contracting officer designates the successor: a separate contract, still in `DRAFT`, whose id is supplied as `successor_contract_id` and recorded on the outgoing contract, bumping its `version`. This self-referential link is what makes the final asset transfer possible; without it, finalization is rejected with `ERR_NO_SUCCESSOR_DESIGNATED`.

Finalization completes the handoff, moving the contract from `TRANSITION_PENDING` to its terminal `CLOSED` state. Beyond the designated successor, finalization requires that every franchise fee statement on the contract has been `PAID` — otherwise `ERR_STATEMENT_NOT_PAID` — and that every gross receipts report has been `ACCEPTED`, with a non-accepted report rejected as `ERR_INVALID_STATE`. The transfer itself is a sweeping cascade. Each `APPROVED` capital project is marked `EXPENDED`, its `accrued_lsi_cents` frozen at the transition offset, and an identical project — same `title`, `asset_ref`, and `authorized_cost_cents`, with `actual_cost_cents` reset to zero and its in-service offset left unset — is created in `PROPOSED` status on the successor contract. Each service line on the outgoing contract is marked `TERMINATED`, and a matching service line for each — same `line_type` and flags, one per line on the outgoing contract — is created fresh in `AUTHORIZED` status on the successor. Each `ACTIVE` room class is marked `DECOMMISSIONED`, and an equivalent room class — same `code`, `total_rooms`, and `peak_season_months` — is created in `ACTIVE` status on the successor. Finally, the accrued leasehold surrender interest is paid out: the sum of the frozen `accrued_lsi_cents` across all approved projects is recorded internally on the transition (the finalization response carries the closed contract; no separate transition-report resource is exposed). Finalization bumps the contract's `version` by one.

### 3.10. Cross-References and Read Access

Every child resource carries a `contract_id` identifying its owning contract, and cross-aggregate references are carried through ordinary foreign keys in payloads and responses: a hire's voucher is reachable through `transport_voucher_id` on the hire and `hire_id` on the voucher; filings, reservations, and receipts reports reference their season, room class, study, or service line through `season_id`, `room_class_id`, `reference_study_id`, and `service_line_id`. All roles may read every resource. Beyond the nested views under each contract, the API also exposes flat retrieval and flat list forms for the child resources — useful when a client already holds an id, since ids are globally unique. Flat list endpoints accept foreign-key filters (such as `contract_id`, `season_id`, `room_class_id`, `service_line_id`, `housing_unit_id`, or `hire_id`) alongside `status`, `limit`, and `offset`.

## 4. Endpoint Definitions

All endpoints follow the status-code conventions described in §2: creating a new resource returns 201, while state transitions and modifications return 200. Reads return 200. List endpoints paginate per §2.3 and accept the foreign-key filter parameters described in §3.10 in addition to `limit` and `offset`. The authorized roles for each endpoint are listed below; any other role attempting the operation receives `ERR_INSUFFICIENT_PERMISSIONS`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock (fixed startup default 2026-09-01T00:00:00Z); advances all due time-based transitions; returns 200 with an empty data object | SystemTestHarness |
| POST | /contracts | Create a concession contract | AgencyContractingOfficer |
| GET | /contracts | List contracts (filters: `status`, `successor_contract_id`) | All roles except SystemTestHarness |
| GET | /contracts/{id} | Get a contract | All roles except SystemTestHarness |
| POST | /contracts/{id}/activate | Activate a DRAFT contract | ConcessionerOpsManager |
| POST | /contracts/{id}/initiate-transition | Begin recompetition/transition (from ACTIVE or EXPIRED) | AgencyContractingOfficer |
| POST | /contracts/{id}/designate-successor | Designate a DRAFT successor contract | AgencyContractingOfficer |
| POST | /contracts/{id}/finalize-transition | Complete transition and asset transfer to the successor | AgencyContractingOfficer |
| POST | /contracts/{id}/seasons | Create an operating season | ConcessionerOpsManager |
| GET | /contracts/{id}/seasons | List seasons for a contract | All roles except SystemTestHarness |
| GET | /contracts/{id}/seasons/{seasonId} | Get a season | All roles except SystemTestHarness |
| POST | /contracts/{id}/seasons/{seasonId}/reconcile | Reconcile a CLOSED season | ConcessionerOpsManager |
| POST | /contracts/{id}/service-lines | Create a service line (LODGING / FOOD / RETAIL / TOURS) | AgencyContractingOfficer |
| GET | /contracts/{id}/service-lines | List service lines | All roles except SystemTestHarness |
| POST | /contracts/{id}/service-lines/{lineId}/suspend | Suspend a service line (new receipts reports rejected) | AgencyContractingOfficer |
| POST | /contracts/{id}/service-lines/{lineId}/reinstate | Reinstate a suspended service line | AgencyContractingOfficer |
| POST | /contracts/{id}/room-classes | Create a room class | ConcessionerOpsManager |
| GET | /contracts/{id}/room-classes | List room classes | All roles except SystemTestHarness |
| POST | /contracts/{id}/comparability-studies | Register a comparability study | AgencyRateAnalyst |
| GET | /contracts/{id}/comparability-studies | List comparability studies | All roles except SystemTestHarness |
| GET | /contracts/{id}/comparability-studies/{studyId} | Get a comparability study | All roles except SystemTestHarness |
| POST | /contracts/{id}/rate-filings | Submit a rate filing (or a revision of a REJECTED filing); OCC-guarded | ConcessionerRateManager |
| GET | /contracts/{id}/rate-filings | List rate filings | All roles except SystemTestHarness |
| GET | /contracts/{id}/rate-filings/{filingId} | Get a rate filing | All roles except SystemTestHarness |
| POST | /contracts/{id}/rate-filings/{filingId}/start-review | Move a SUBMITTED filing to UNDER_REVIEW | AgencyRateAnalyst |
| POST | /contracts/{id}/rate-filings/{filingId}/approve | Approve a filing (rate-cap, SoD, and study-current gates) | AgencyRateAnalyst |
| POST | /contracts/{id}/rate-filings/{filingId}/reject | Reject a filing | AgencyRateAnalyst |
| POST | /contracts/{id}/reservations | Create a reservation (lottery window rules apply); OCC-guarded | ConcessionerFrontDesk |
| GET | /contracts/{id}/seasons/{seasonId}/reservations | List reservations for a season | All roles except SystemTestHarness |
| GET | /contracts/{id}/room-classes/{roomClassId}/reservations | List reservations for a room class | All roles except SystemTestHarness |
| GET | /contracts/{id}/reservations | List reservations | All roles except SystemTestHarness |
| GET | /contracts/{id}/reservations/{resId} | Get a reservation | All roles except SystemTestHarness |
| POST | /contracts/{id}/reservations/{resId}/cancel | Cancel a reservation (fee per refund policy; waitlist promotion) | ConcessionerFrontDesk |
| POST | /contracts/{id}/reservations/{resId}/check-in | Record guest check-in (prevents no-show sweep) | ConcessionerFrontDesk |
| POST | /contracts/{id}/receipts-reports | Create a gross receipts report; OCC-guarded | ConcessionerAccountant |
| GET | /contracts/{id}/receipts-reports | List receipts reports | All roles except SystemTestHarness |
| POST | /contracts/{id}/receipts-reports/{reportId}/submit | Submit a DRAFT or RETURNED report | ConcessionerAccountant |
| POST | /contracts/{id}/receipts-reports/{reportId}/accept | Accept a SUBMITTED report (SoD gate; stales ISSUED statement) | AgencyFinancialAuditor |
| POST | /contracts/{id}/receipts-reports/{reportId}/return | Return a SUBMITTED report for rework | AgencyFinancialAuditor |
| POST | /contracts/{id}/fee-statements | Issue the franchise fee statement for a period (per-line rounding) | ConcessionerAccountant |
| GET | /contracts/{id}/fee-statements | List fee statements | All roles except SystemTestHarness |
| POST | /contracts/{id}/fee-statements/{stmtId}/pay | Pay an ISSUED statement | ConcessionerAccountant |
| POST | /contracts/{id}/capital-projects | Propose a capital improvement on a government-owned asset | ConcessionerMaintenanceChief |
| GET | /contracts/{id}/capital-projects | List capital projects | All roles except SystemTestHarness |
| GET | /contracts/{id}/capital-projects/{projId} | Get a capital project | All roles except SystemTestHarness |
| POST | /contracts/{id}/capital-projects/{projId}/authorize | Authorize a proposed project | AgencyContractingOfficer |
| POST | /contracts/{id}/capital-projects/{projId}/complete | Mark an authorized project complete with actual cost | ConcessionerMaintenanceChief |
| POST | /contracts/{id}/capital-projects/{projId}/approve | Approve a completed project (starts LSI accrual) | AgencyContractingOfficer |
| POST | /contracts/{id}/housing-units | Create an employee housing unit | ConcessionerHRManager |
| GET | /contracts/{id}/housing-units | List housing units | All roles except SystemTestHarness |
| POST | /contracts/{id}/housing-units/{unitId}/take-offline | Take a housing unit offline | ConcessionerHRManager |
| POST | /contracts/{id}/seasonal-hires | Hire a seasonal employee (assigns housing; books voucher when needed) | ConcessionerHRManager |
| GET | /contracts/{id}/seasonal-hires | List seasonal hires | All roles except SystemTestHarness |
| POST | /contracts/{id}/seasonal-hires/{hireId}/mark-arrived | Mark a hire arrived (consumes the booked voucher) | ConcessionerHRManager |
| POST | /contracts/{id}/seasonal-hires/{hireId}/mark-departed | Mark an arrived hire departed (releases the bed) | ConcessionerHRManager |
| POST | /contracts/{id}/seasonal-hires/{hireId}/terminate | Terminate a hire (releases the bed; voids the voucher) | ConcessionerHRManager |
| POST | /contracts/{id}/transport-vouchers | Book an additional transport voucher for a hire | ConcessionerHRManager |
| GET | /contracts/{id}/transport-vouchers | List transport vouchers | All roles except SystemTestHarness |
| POST | /contracts/{id}/transport-vouchers/{voucherId}/void | Void a BOOKED voucher | ConcessionerHRManager |
| POST | /contracts/{id}/environmental-incidents | Report an environmental incident (waste/water/wildlife) | ConcessionerOpsManager, AgencyEnvironmentalInspector |
| GET | /contracts/{id}/environmental-incidents | List environmental incidents | All roles except SystemTestHarness |
| POST | /contracts/{id}/environmental-incidents/{incId}/start-review | Start review of a reported incident | AgencyEnvironmentalInspector |
| POST | /contracts/{id}/environmental-incidents/{incId}/require-corrective-plan | Require a corrective plan | AgencyEnvironmentalInspector |
| POST | /contracts/{id}/environmental-incidents/{incId}/submit-corrective-plan | Submit a corrective plan (deadline-gated; returns to UNDER_REVIEW) | ConcessionerOpsManager |
| POST | /contracts/{id}/environmental-incidents/{incId}/close | Close an incident under review | AgencyEnvironmentalInspector |
| GET | /seasons/{seasonId} | Get a season by id (flat form; ids are globally unique) | All roles except SystemTestHarness |
| GET | /service-lines/{lineId} | Get a service line by id (flat form) | All roles except SystemTestHarness |
| GET | /room-classes/{roomClassId} | Get a room class by id (flat form) | All roles except SystemTestHarness |
| GET | /comparability-studies/{studyId} | Get a comparability study by id (flat form) | All roles except SystemTestHarness |
| GET | /rate-filings/{filingId} | Get a rate filing by id (flat form) | All roles except SystemTestHarness |
| GET | /reservations/{resId} | Get a reservation by id (flat form) | All roles except SystemTestHarness |
| GET | /receipts-reports/{reportId} | Get a receipts report by id (flat form) | All roles except SystemTestHarness |
| GET | /fee-statements/{stmtId} | Get a fee statement by id (flat form) | All roles except SystemTestHarness |
| GET | /capital-projects/{projId} | Get a capital project by id (flat form) | All roles except SystemTestHarness |
| GET | /housing-units/{unitId} | Get a housing unit by id (flat form) | All roles except SystemTestHarness |
| GET | /seasonal-hires/{hireId} | Get a seasonal hire by id (flat form) | All roles except SystemTestHarness |
| GET | /transport-vouchers/{voucherId} | Get a transport voucher by id (flat form) | All roles except SystemTestHarness |
| GET | /environmental-incidents/{incId} | Get an environmental incident by id (flat form) | All roles except SystemTestHarness |
| GET | /rate-filings | List rate filings (flat form with FK filters) | All roles except SystemTestHarness |
| GET | /reservations | List reservations (flat form with FK filters) | All roles except SystemTestHarness |
| GET | /receipts-reports | List receipts reports (flat form with FK filters) | All roles except SystemTestHarness |
| GET | /seasonal-hires | List seasonal hires (flat form with FK filters) | All roles except SystemTestHarness |
| GET | /transport-vouchers | List transport vouchers (flat form with FK filters) | All roles except SystemTestHarness |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API may return, with its HTTP status. The conditions that trigger each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_SEASON_NOT_FOUND | 404 |
| ERR_SERVICE_LINE_NOT_FOUND | 404 |
| ERR_ROOM_CLASS_NOT_FOUND | 404 |
| ERR_STUDY_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_HOUSING_UNIT_NOT_FOUND | 404 |
| ERR_HIRE_NOT_FOUND | 404 |
| ERR_VOUCHER_NOT_FOUND | 404 |
| ERR_INCIDENT_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_OPERATIONAL | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_CONTRACT_NOT_ACTIVATABLE | 409 |
| ERR_LOTTERY_NOT_OPEN | 409 |
| ERR_SEASON_NOT_OPEN | 409 |
| ERR_DUPLICATE_RESERVATION | 409 |
| ERR_STUDY_NOT_CURRENT | 409 |
| ERR_SEASON_NOT_OPEN_FOR_FILING | 409 |
| ERR_ROOM_CLASS_INACTIVE | 409 |
| ERR_SERVICE_LINE_SUSPENDED | 409 |
| ERR_DUPLICATE_PERIOD_REPORT | 409 |
| ERR_NO_ACCEPTED_REPORTS | 409 |
| ERR_STATEMENT_NOT_PAID | 409 |
| ERR_COST_OVERRUN | 409 |
| ERR_OPEN_CAPITAL_PROJECT | 409 |
| ERR_OPEN_ENVIRONMENTAL_INCIDENT | 409 |
| ERR_CORRECTIVE_PLAN_LATE | 409 |
| ERR_HOUSING_FULL | 409 |
| ERR_UNIT_OFFLINE | 409 |
| ERR_NO_SUCCESSOR_DESIGNATED | 409 |
| ERR_UNRECONCILED_SEASON | 409 |
| ERR_STALE_CONTRACT_VERSION | 412 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_LOTTERY_WINDOW | 422 |
| ERR_STAY_OUTSIDE_SEASON | 422 |
| ERR_RATE_EXCEEDS_COMPARABILITY | 422 |
| ERR_STUDY_EXPIRED | 422 |
