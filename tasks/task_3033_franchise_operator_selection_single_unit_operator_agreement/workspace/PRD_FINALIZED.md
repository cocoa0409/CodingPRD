# Franchise Operator Selection API — Product Requirements Document

## 1. Introduction

This document specifies the Franchise Operator Selection API, the system of record for identifying, vetting, contracting, and stewarding single-unit restaurant operators under a franchisor-led selection program. The model is deliberately unusual in the franchise world: candidates pass through a multi-stage selection pipeline — screening, interviews, a written business assessment, and hands-on in-restaurant experience — while being asked for only a modest initial financial commitment. In return, the winning operator signs an agreement that is non-transferable, carries no equity stake in the site or equipment, and binds them to exactly one restaurant with residency and full-time involvement obligations. The franchisor retains ownership of the real estate and equipment, and operators are compensated through a revenue-share arrangement rather than traditional franchise royalties.

Because the franchisor owns the site, the system also carries the operational calendar: every restaurant runs a six-day operating week (closed Sundays), and weekly forecasting, labor planning, and revenue-share settlement all flow through that calendar. Operator performance is governed by a published scorecard spanning food safety, service speed, and community engagement; a failing scorecard can suspend an operator outright. Exceptions to the single-unit rule — relocations and rare second-location grants — require committee votes, and operator exits run through a structured successor-selection process so a restaurant is never left leaderless. Time-sensitive behaviors (application expiry, experience-block start and shortfall detection, week opening) are driven by a controllable logical clock rather than wall-clock time, so the entire lifecycle can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Independently of role, a request body that is missing a required field or carries a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Independently of role, a request body that is missing a required field or carries a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The system recognizes six roles, spelled exactly as follows: `SystemAdmin`, `Candidate`, `FieldConsultant`, `SelectionCommittee`, `Operator`, and `FinanceAdmin`.

Two of these roles are entity-backed. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` record; ownership checks on any resource that references a `Candidate` — an application, its assessment, a withdrawal — compare the resource's candidate reference to `X-User-ID`, and acting on another person's record is refused. When `X-User-Role` is `Operator`, `X-User-ID` is likewise the `id` of the acting `Operator` record, and operator-scoped actions (attestation, relocation requests, exits, scorecard disputes) are valid only against the caller's own operator record.

The remaining four roles are opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `SystemAdmin`, `FieldConsultant`, `SelectionCommittee`, or `FinanceAdmin`, `X-User-ID` is not compared against any entity's `id`. The server may record it where a workflow captures an actor — for example, `interviewer_id` on an interview round or `committee_member_id` on a committee vote — but it performs no identity-to-entity matching for these roles.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response always carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Transitions

The system never consults wall-clock time. All temporal reasoning — expiry, scheduled starts, grace periods, week boundaries — runs against a logical clock whose current instant is controlled by a privileged `SystemAdmin` capability that sets the clock to a supplied `to_iso8601` value and returns the resulting `current_utc`. Before the clock has ever been set, it reads exactly 2026-09-01T00:00:00Z, and it must never silently fall back to wall-clock time. Whenever the clock is advanced, every scheduled automatic transition is re-evaluated: `SUBMITTED` applications whose `submitted_at` is older than thirty days expire to `EXPIRED`; experience blocks whose `starts_on` has been reached move from `SCHEDULED` to `IN_PROGRESS`; experience blocks that ended more than a day ago without enough signed-off shifts fall to `SHORTFALL`; and planned operating weeks whose `week_start_on` has been reached open from `PLANNED` to `OPEN`. Advancing the clock reports success with a 200 status.

### 2.5. Common Resource Properties

Every primary resource — candidates, applications, interview rounds, business assessments, restaurants, in-restaurant experiences, operators, operator agreements, operating weeks, scorecards, relocation requests, exit cases, and revenue share statements — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, underpinning optimistic concurrency control.

The one exception is the committee vote. A `CommitteeVote` is an immutable ballot: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it can never be modified after being cast.

### 2.6. Nested Resource Retrieval

Endpoints that address a resource nested under a parent — an interview round under an application, a scorecard under an operator, an exit case under an operator — validate path identifiers strictly left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path segment whose identifier does not correspond to an existing resource, before any later segment or any business rule is evaluated. A request naming a valid application but a nonexistent interview round therefore fails on the round, while a request naming a nonexistent application fails on the application regardless of what follows.

### 2.7. Money, Basis Points, and Rounding

All monetary values are integer cent amounts (`*_cents` fields) and all percentage rates are integer basis points (`*_bps` fields, where 5000 basis points means 50.00 percent). Calculations that produce a cent amount round half-up to a whole cent at the step where the scaffold of each calculation dictates; several calculations deliberately round each line item independently before summing, and the PRD prose in §3 pins that order per calculation. Calculations that produce an integer score apply a floor (round down) at the final step. Calculations that produce an average carry exactly two decimal places, rounded half-up. Hour quantities are integers rounded up to the next whole hour. These precision rules are restated alongside each calculation in §3 and are contractual.

### 2.8. Validation Ordering

When a request could fail more than one rule, failures surface in a fixed priority order, and the caller sees the earliest applicable failure. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, left-to-right existence of every path identifier (`ERR_NOT_FOUND`); fourth, whether the target resource's current state permits the requested transition (`ERR_INVALID_STATE`); and only then the domain-specific business checks — the scorecard-publish operator-state rule, the single-unit restriction, agreement immutability, the closed-Sunday block rule, the week-elapsed rule, the exit notice-period rule, the interview stage rule, successor eligibility, scorecard period overlap, missing actuals, duplicate statements, and duplicate weeks — each with its own error as narrated in §3. A request that would trip two business rules reports the one listed earlier in this sequence. When the applicable rules attach to different resources on the same request — for example, an interview-scoring request that violates both a round's own state rule (`ERR_INVALID_STATE`) and the parent application's stage rule (`ERR_STAGE_MISMATCH`) — either applicable error may surface, and the request is refused without mutating any resource.

### 2.9. Optimistic Concurrency Control

Two write operations require the caller to prove they have observed the current state of the resource being mutated, using optimistic concurrency control.

Recording a committee decision on an application requires the request to carry `expected_application_version`, holding the `version` of the application as the committee member last read it. If the application's current `version` no longer matches — because another writer advanced it in the interim — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no decision is recorded. A committee decision that legitimately landed earlier moved the application out of `COMMITTEE_REVIEW` and bumped its `version`, so the later writer's stale view cannot silently overwrite it.

Closing an operating week likewise requires `expected_week_version`, holding the `version` of the week as the caller last read it. A mismatch with the week's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A prior close moved the week to `CLOSED`, issued the provisional statement, and bumped the version; the second caller's stale view must not produce a second close.

No other endpoint takes a version field.

## 3. Business Logic & Workflows

### 3.1. Registering Candidates and Entering the Pipeline

A `SystemAdmin` registers each prospective operator as a candidate, supplying the `legal_name`, a contact `email`, the `home_market_code` identifying the US state or market where the candidate resides (for example, GA), a boolean `relocation_willing` declaring whether the candidate is open to moving for a restaurant assignment, and a self-declared `liquid_capital_cents` amount that must be zero or greater. The email address is unique across all candidates regardless of status. A freshly registered candidate's `candidate_status` reads `REGISTERED`, and its `active_application_id` is null because no application exists yet. A candidate with no live application may withdraw entirely, moving from `REGISTERED` to the terminal `WITHDRAWN` status; alternatively, a `FieldConsultant` may disqualify a candidate who is `IN_SELECTION`, moving them to the terminal `DISQUALIFIED` status and cascading their active application to `REJECTED`. Withdrawal and disqualification each increment the candidate's `version` by one.

A candidate begins the selection pipeline by submitting an application with a `target_market_code` naming the market they wish to operate in. Submission is permitted only while the candidate is `REGISTERED` and has no non-terminal application; a candidate who already has a live application is refused with `ERR_DUPLICATE_APPLICATION`. On submission the candidate moves from `REGISTERED` to `IN_SELECTION`, the application is created with its `stage` set to `SUBMITTED` and its `submitted_at` stamped from the logical clock, the candidate's `active_application_id` is set to the new application, and the candidate's `version` increments. An application that sits in `SUBMITTED` without progressing is not kept forever: when the logical clock shows the application has been in `SUBMITTED` for more than thirty days, it automatically moves to `EXPIRED`, and the candidate bubbles back from `IN_SELECTION` to `REGISTERED` with `active_application_id` cleared to null — free to apply again.

### 3.2. Screening and the Application Pipeline

The moment an application is created, the system computes its `screening_score`, an integer between 0 and 100 derived from three components. The capital component takes the candidate's `liquid_capital_cents`, capped at a reference of 1,000,000 cents (ten thousand dollars), and scales it to a maximum of 40 points — declared capital divided by the ten-thousand-dollar reference, times 40, with any capital above the reference counting as the full 40. The market component awards 40 points when the application's `target_market_code` matches the candidate's `home_market_code`; when it does not match but the candidate declared `relocation_willing`, it awards 20 points; otherwise it awards nothing. The name component contributes one point per character of the candidate's `legal_name`, capped at 20 points. The three components are summed and floored to a whole integer. An application in `SUBMITTED` may be advanced to `SCREENING` by a `FieldConsultant` only when its `screening_score` is at least 60; a score below that bar is refused with `ERR_SCREENING_BELOW_THRESHOLD`. A `FieldConsultant` may also reject a `SUBMITTED` application outright, moving it to `REJECTED` and bubbling the candidate back to `REGISTERED` with `active_application_id` cleared.

From `SCREENING`, advancement to `INTERVIEWS` is unconditional — a `FieldConsultant` simply moves the application forward once screening work is done. The interview stage is where the pipeline becomes quantitative again, and it is detailed next.

### 3.3. Interviews and the Business Assessment

While an application is in `INTERVIEWS`, a `FieldConsultant` schedules interview rounds, each carrying an `interviewer_id` (the opaque identifier of the field consultant conducting the round) and a `scheduled_for` timestamp on the logical clock. Rounds are numbered sequentially in creation order via a 1-based `round_index`, and each round begins with its `status` field at `SCHEDULED`. Scoring a round — performed by a `FieldConsultant` supplying a `score` between 0 and 100 inclusive — moves the round's `status` to `SUBMITTED`; a score outside that range is refused with `ERR_SCORE_OUT_OF_RANGE`. Scoring is only meaningful while the application's `stage` is actually `INTERVIEWS`; an attempt to score a round for an application in any other stage is refused with `ERR_STAGE_MISMATCH`. A scheduled round may instead be cancelled by a `FieldConsultant`, moving its `status` to `CANCELLED`. Every round belongs to exactly one application, recorded on the round as its `application_id`.

Every score submission or cancellation recomputes the application's `interview_average`: the arithmetic mean of the `score` values of exactly the application's `SUBMITTED` rounds — `SCHEDULED` and `CANCELLED` rounds never participate — carried to two decimal places with round-half-up. When no scored rounds exist, the average is null. Advancing from `INTERVIEWS` to `BUSINESS_ASSESSMENT` requires three things, all enforced together: at least two interview rounds exist for the application, every one of the application's rounds is in `SUBMITTED` status, and the `interview_average` is at least 70. Any shortfall is refused with `ERR_INTERVIEW_GATE`.

In the `BUSINESS_ASSESSMENT` stage the candidate authors their own assessment: a `market_plan_text` narrative and a `financial_projection_cents` projecting first-year revenue, which must be greater than zero. The assessment is created in `DRAFT` status; submitting it — again the candidate's own action — requires the application to actually be in `BUSINESS_ASSESSMENT`, the `market_plan_text` to be non-empty, and the `financial_projection_cents` to be positive, and moves the assessment to `SUBMITTED`. A `FieldConsultant` then evaluates the submitted assessment, which computes the `rubric_score`: the plan component takes the length of `market_plan_text` in characters, capped at 2,000, and scales it to a maximum of 50 points; the projection component takes `financial_projection_cents`, capped at a reference of 500,000,000 cents (five million dollars), and likewise scales it to a maximum of 50 points; the two components are summed and floored to a whole integer. Evaluation moves the assessment to its terminal `EVALUATED` status and sets the application's `assessment_verdict` — `PENDING` until evaluation runs, then `PASS` when the `rubric_score` is at least 55, otherwise `FAIL`. Advancing the application from `BUSINESS_ASSESSMENT` to `IN_RESTAURANT` requires an `EVALUATED` assessment on file and an `assessment_verdict` of `PASS`.

### 3.4. The In-Restaurant Experience and Committee Decision

The final gate before the committee is hands-on. Once an application reaches `IN_RESTAURANT`, a `FieldConsultant` schedules an in-restaurant experience block: the `host_restaurant_id` of the restaurant hosting the shifts, a `starts_on` date, and an `ends_on` date, each expressed as a date at 00:00:00Z. The block covers the days from `starts_on` through `ends_on` inclusive — equivalently, the half-open interval running from `starts_on` up to one day past `ends_on`. Because the brand never operates on Sundays, the system computes the block's `required_shift_count` at creation: the number of calendar dates in that inclusive range whose weekday is not Sunday. A block that contains no non-Sunday operating day at all — for instance, a block exactly one Sunday long — is refused with `ERR_NO_OPERATING_DAYS`. The block begins in `SCHEDULED` status with `completed_shift_count` at zero, and it moves to `IN_PROGRESS` automatically at logical-clock midnight once `starts_on` is reached.

During the block, a `FieldConsultant` signs off each worked shift, incrementing `completed_shift_count` by one per sign-off, capped at `required_shift_count`. When the signed-off count equals the required count, completing the block — a `FieldConsultant` action — moves it to `COMPLETED` and sets the application's `experience_verdict` — `PENDING` until the outcome is decided — to `PASS`. If the logical clock runs one day past `ends_on` while `completed_shift_count` still falls short of `required_shift_count`, the block automatically falls to `SHORTFALL` and the verdict is set to `FAIL`. Attempting to complete a block whose signed-off shifts fall short is refused with `ERR_SHIFT_SHORTFALL`. A block still in `SCHEDULED` may be cancelled by a `FieldConsultant`, moving it to `CANCELLED`.

Advancing from `IN_RESTAURANT` to `COMMITTEE_REVIEW` requires a `COMPLETED` experience and an `experience_verdict` of `PASS`. Entering `COMMITTEE_REVIEW` is also the moment the program's signature low initial financial commitment is charged: the application's `application_fee_cents` is set to a fixed 1,000,000 cents — ten thousand dollars — regardless of market or restaurant.

In `COMMITTEE_REVIEW`, a `SelectionCommittee` member records the committee's `decision`. The write must carry `expected_application_version` per §2.9, and the application must still be in `COMMITTEE_REVIEW`. A decision of `APPROVE` moves the application to the terminal `APPROVED` stage, records `committee_decision` as `APPROVE`, and bubbles the candidate from `IN_SELECTION` to `SELECTED` with `active_application_id` cleared. A decision of `REJECT` moves the application to `REJECTED`, records `committee_decision` as `REJECT`, and bubbles the candidate back to `REGISTERED` with `active_application_id` cleared. The committee write increments the application's `version` by one. Until the committee acts, the application's `committee_decision` reads `NONE`.

### 3.5. Withdrawal Cascades Across the Pipeline

A candidate may withdraw their own application at any pre-terminal stage — `SUBMITTED`, `SCREENING`, `INTERVIEWS`, `BUSINESS_ASSESSMENT`, `IN_RESTAURANT`, or `COMMITTEE_REVIEW` — moving it to `WITHDRAWN`. Every withdrawal bubbles the candidate from `IN_SELECTION` back to `REGISTERED` and clears `active_application_id`, but the deeper the stage, the wider the cascade. Withdrawal during `INTERVIEWS` additionally moves all of the application's `SCHEDULED` interview rounds to `CANCELLED`. Withdrawal during `IN_RESTAURANT` additionally moves a `SCHEDULED` or `IN_PROGRESS` experience block to `CANCELLED`. Withdrawing the candidate entirely while `IN_SELECTION` cascades the active application to `WITHDRAWN` and lands the candidate in terminal `WITHDRAWN`; disqualification by a `FieldConsultant` instead cascades the active application to `REJECTED` and lands the candidate in `DISQUALIFIED`.

### 3.6. Restaurants, Operators, and the Agreement

Restaurants enter the system when a `SystemAdmin` registers a site with a unique `site_code` (for example, GA-ATL-042), the `market_code` it trades in, a `baseline_weekly_revenue_cents` reference figure that must be greater than zero, and the `equipment_value_cents` book value of the franchisor-owned equipment — value the operator will never acquire equity in. A site's `restaurant_status` runs through `PIPELINE`, `AVAILABLE`, `ASSIGNED`, and `TRANSITION` across its lifecycle. A site's `restaurant_status` runs through `PIPELINE`, `AVAILABLE`, `ASSIGNED`, and `TRANSITION` across its lifecycle. A new site starts with `restaurant_status` at `PIPELINE`; a `SystemAdmin` makes it available, moving `restaurant_status` to `AVAILABLE`, the only status in which a site is open for operator assignment. Every restaurant's `sunday_closed` flag is always true; the closed-Sunday calendar is not negotiable. A site's `current_operator_id` is null while unassigned.

Once a candidate is `SELECTED`, a `SelectionCommittee` member creates the operator record, supplying the `candidate_id`, the `restaurant_id` of an `AVAILABLE` site (assigning against a site in any other status is refused with `ERR_RESTAURANT_NOT_AVAILABLE`), the `base_share_bps` revenue-share rate in basis points, and the agreement's `effective_from` timestamp, which must not lie in the past relative to the logical clock. There is exactly one operator record per candidate. The operator is created with `operator_status` at `ONBOARDING`, `residency_verified` and `full_time_attested` both false, and `lifetime_revenue_share_cents` at zero; simultaneously a draft operator agreement is created binding that operator to that restaurant — the agreement carries its own `operator_id` and `restaurant_id` references, both immutable — with `transferable` always false and `equity_stake_bps` always zero, and its `agreement_status` at `DRAFT`. Any write that attempts to set `transferable` true or a non-zero `equity_stake_bps` — at execution or on any agreement modification — is refused with `ERR_AGREEMENT_IMMUTABLE`. The operator record references its governing agreement through `agreement_id` and its single licensed restaurant through `restaurant_id`.

The new operator then attests, under their own identity, that residency within the market has been verified and that they commit to full-time involvement for the current period, setting `residency_verified` and `full_time_attested`; attestation increments the operator's `version` by one. Executing the agreement is a `SelectionCommittee` action requiring the agreement to be `DRAFT`, its `effective_from` to be no earlier than the current logical-clock instant, and the operator to be `ONBOARDING`; execution moves the agreement's `agreement_status` to `EXECUTED` and simultaneously moves the restaurant to `ASSIGNED` with `current_operator_id` set to this operator. Throughout, the single-unit restriction holds: an operator may be linked to at most one `ASSIGNED` restaurant, and any operation that would breach that — agreement execution included — is refused with `ERR_SINGLE_UNIT_VIOLATION`. Finally, a `FieldConsultant` activates the operator, moving them from `ONBOARDING` to `ACTIVE`; activation requires `residency_verified` and `full_time_attested` both true, the linked agreement `EXECUTED`, and the linked restaurant `ASSIGNED` to this operator.

Suspension and reinstatement are paired `FieldConsultant` actions. Suspending an `ACTIVE` operator moves them to `SUSPENDED` and cascades the agreement from `EXECUTED` to `SUSPENDED`. Reinstating requires `residency_verified` to still hold true, moves the operator back to `ACTIVE`, and cascades the agreement back from `SUSPENDED` to `EXECUTED`.

### 3.7. The Six-Day Operating Week and Revenue Share

Each restaurant's trading rhythm is planned one operating week at a time. A `FieldConsultant` plans a week for a restaurant by supplying its `week_start_on`, the Monday at 00:00:00Z that opens the week; the same restaurant may not hold two weeks with the same `week_start_on` — a duplicate is refused with `ERR_DUPLICATE_WEEK`. Every operating week has an `operating_day_count` of exactly 6, Monday through Saturday, because Sunday is excluded by the closed-Sunday calendar. The week starts with `week_status` at `PLANNED` and opens automatically — `PLANNED` to `OPEN` — at logical-clock midnight when `week_start_on` arrives.

At planning time the system computes two derived figures. The `forecast_revenue_cents` comes in two variants. While the restaurant has no `CLOSED` week on file, the provisional variant derives the forecast from the site's seven-day baseline adjusted for the six-day calendar: `baseline_weekly_revenue_cents` multiplied by six, divided by seven, rounded half-up to a whole cent. Once the restaurant has at least one `CLOSED` week, the trailing variant ignores the baseline entirely and forecasts from actuals: the arithmetic mean of `actual_revenue_cents` across the restaurant's four most recent `CLOSED` operating weeks, taken most-recent-first by `week_start_on` — averaging however many closed weeks exist when fewer than four are on file — rounded half-up to a whole cent. In both variants the `planned_labor_hours` are the forecast divided by a labor rate of 15,000 cents per planned hour (that is, 150 dollars of forecast revenue per labor hour), rounded up to the next whole hour.

Closing a week is a `FieldConsultant` action with strict guards. The week must be `OPEN`; the request must supply `actual_revenue_cents`, zero or greater — a close without actuals is refused with `ERR_MISSING_ACTUALS`; the logical clock must have reached at least six days past `week_start_on`, meaning the six operating days have elapsed with Sunday excluded — closing earlier is refused with `ERR_WEEK_NOT_ELAPSED`; and the request must carry `expected_week_version` per §2.9. A successful close moves the week to its terminal `CLOSED` status, increments its `version` by one, and automatically issues a revenue share statement for the restaurant's current operator.

### 3.8. Revenue Share Statements and Settlement

A revenue share statement settles one operating week for one operator; each statement records its `operator_id` and the `operating_week_id` it settles. The pair is unique: at most one statement may exist for a given operator and operating week, and a second issue for the same pairing — whether at week close or during finalization — is refused with `ERR_DUPLICATE_STATEMENT`. The statement's money fields are computed entirely server-side; any client-supplied values for `gross_revenue_cents`, `brand_fee_cents`, `occupancy_charge_cents`, or `operator_share_cents` are ignored.

The split follows a pinned evaluation order: brand fee first, occupancy second, share last. The `gross_revenue_cents` is taken from the closed week's `actual_revenue_cents`. The `brand_fee_cents` is the gross multiplied by 1,500 basis points (15 percent), divided by ten thousand, rounded half-up to a whole cent. Subtracting the brand fee from the gross leaves the net-after-fee amount; the `occupancy_charge_cents` — the franchisor's charge for the site and equipment it owns — is that net amount multiplied by 800 basis points (8 percent), divided by ten thousand, rounded half-up. What remains after occupancy is the shareable base, and the operator's share is tiered across it. The first 50,000,000 cents (five hundred thousand dollars) of the shareable base earns the agreement's `base_share_bps`; any remainder above that threshold earns `base_share_bps` reduced by 500 basis points, floored at zero so the tier-two rate never goes negative. Each tier's share is computed as the tier's cents multiplied by the tier's basis-point rate divided by ten thousand and rounded half-up independently, and the `operator_share_cents` is the sum of the two independently rounded tier amounts.

Statements carry a `statement_kind`. The statement issued automatically at week close is `PROVISIONAL`; a provisional statement may later be re-issued as `FINAL` during an open exit (see §3.10) — same formula, different lifecycle. A statement begins with `statement_status` at `ISSUED`. A `FinanceAdmin` settles an `ISSUED` statement, moving it to `SETTLED` and adding its `operator_share_cents` to the operator's `lifetime_revenue_share_cents` cumulative total. A `FinanceAdmin` may instead void an `ISSUED` statement, but only while its kind is `PROVISIONAL`; `FINAL` statements are never voidable, and the attempt is refused with `ERR_STATEMENT_NOT_VOIDABLE`. Voiding moves the statement to its terminal `VOID` status without touching the operator's lifetime total.

### 3.9. Operator Scorecards

Performance is measured through scorecards drafted by a `FieldConsultant`, each covering a `period_start_on` through `period_end_on` (the period runs from the start date up to one day past the end date) and carrying three component scores supplied as input: `food_safety_score`, `service_speed_score`, and `community_engagement_score`, each between 0 and 100. A new scorecard's `scorecard_status` begins at `DRAFT`.

Publishing a scorecard is the consequential act, and it is guarded. The operator must be in `ACTIVE` or `SUSPENDED` status — publishing against an `ONBOARDING`, `EXITING`, or `EXITED` operator is refused outright with `ERR_OPERATOR_NOT_SCORABLE`. The new scorecard's period must not overlap the period window of any existing `PUBLISHED`, `DISPUTED`, or `FINAL` scorecard for the same operator; an overlap is refused with `ERR_SCORECARD_OVERLAP`. On publish, the system computes the `composite_score`: the food safety score weighted at one half, the service speed score weighted at three tenths, and the community engagement score weighted at one fifth, summed and floored to a whole integer. The `rating` bands off the composite: a composite of at least 90 earns `EXCEEDS`; at least 70 earns `MEETS`; at least 50 earns `BELOW`; anything lower is `CRITICAL`. Food safety comes first in this program: when a published scorecard lands `CRITICAL` and the operator is `ACTIVE`, the operator is immediately cascaded from `ACTIVE` to `SUSPENDED` (with the agreement cascade of §3.6 following from that suspension).

The scored operator may dispute a `PUBLISHED` scorecard under their own identity, moving it to `DISPUTED`. After review, a `FieldConsultant` republishes it, moving it back to `PUBLISHED` and recomputing `composite_score` and `rating` from the component scores under the same weights and bands. Finalization closes the loop: a `FieldConsultant` may finalize a `PUBLISHED` or `DISPUTED` scorecard only once the logical clock has reached at least seven days past `period_end_on`; finalizing earlier is refused with `ERR_FINALIZE_TOO_EARLY`. A finalized scorecard is terminal in `FINAL` status.

### 3.10. Relocation, Second Locations, and Committee Votes

The single-unit rule has two sanctioned exceptions, both requested by the operator and decided by the committee. An operator submits a relocation request under their own identity with a `kind` of `RELOCATION` or `SECOND_LOCATION`, the `target_restaurant_id` they seek to move to or add, and an operator-authored `reason_text`. The request starts with `request_status` at `SUBMITTED` and `votes_for` and `votes_against` both at zero; the requesting operator may withdraw it while it is still `SUBMITTED`, moving it to `WITHDRAWN`.

A `SelectionCommittee` member opens review on a submitted request, moving it to `COMMITTEE_REVIEW`; opening review requires the operator to be `ACTIVE` and the target restaurant to be `AVAILABLE`. During review, committee members cast ballots, each vote recording the `relocation_request_id` it ballots on, the `committee_member_id`, and a `vote` of `FOR` or `AGAINST`, stamped with a `cast_at` from the logical clock. Each member may vote at most once per request — a repeat ballot is refused with `ERR_DUPLICATE_VOTE` — and each ballot increments the request's `votes_for` or `votes_against` tally accordingly.

The committee's decision is quorum-based. Approval requires at least 3 votes in favor — the committee quorum — and strictly more votes in favor than against. Denial applies when at least 3 votes are against, or when the votes in favor fail to exceed the votes against. If neither side reaches quorum and the for-votes strictly exceed the against-votes without reaching quorum, no decision can be rendered and the attempt is refused with `ERR_QUORUM_NOT_MET`. An approved `RELOCATION` moves the operator to the target: the operator's `restaurant_id` becomes the target restaurant, the source restaurant returns to `AVAILABLE` with `current_operator_id` cleared, and the target becomes `ASSIGNED` with `current_operator_id` set to the operator. An approved `SECOND_LOCATION` assigns the target restaurant to the operator as an additional site — but the single-unit rule still binds at decision time: the approval is valid only when the operator's current restaurant count is exactly one, and a second-location decision that would leave the operator bound to more than one additional restaurant beyond that grant is refused with `ERR_SINGLE_UNIT_VIOLATION`. A denied request lands in terminal `DENIED`.

### 3.11. Operator Exit and Successor Selection

An `ACTIVE` operator may open an exit case under their own identity, supplying a `reason` of `VOLUNTARY`, `INVOLUNTARY`, or `NON_RENEWAL` and an `effective_on` date. The case opens with `exit_status` at `OPEN` and `notice_given_on` stamped from the logical clock, and the operator moves from `ACTIVE` to `EXITING`. Notice must be genuine: `effective_on` must be at least thirty days after the notice date, and a shorter runway is refused with `ERR_NOTICE_TOO_SHORT`. An operator may hold at most one non-terminal exit case; opening a second while one is `OPEN`, `SUCCESSOR_PENDING`, or `SUCCESSOR_APPROVED` is refused with `ERR_EXIT_ALREADY_OPEN`. While the case is still `OPEN`, the operator may cancel it, which moves the case to `CANCELLED` and returns the operator from `EXITING` to `ACTIVE`.

Succession proceeds in steps. A `FieldConsultant` proposes a successor by `successor_candidate_id`; the proposed person must be a `SELECTED` candidate whose approved application targets the same market as the exiting operator's restaurant — anything else is refused with `ERR_SUCCESSOR_INELIGIBLE`. A valid proposal moves the case to `SUCCESSOR_PENDING`. The committee then rules: approval moves the case to `SUCCESSOR_APPROVED`, while rejection returns it to `OPEN` and clears the `successor_candidate_id`, restarting the successor search.

Completion is the final, guarded step, performed by a `FieldConsultant`. The logical clock must have reached the `effective_on` date, and a `FINAL` revenue share statement must be on file for the operator's most recent `CLOSED` operating week — that statement is produced by re-issuing the settled provisional statement as `FINAL`, a `FinanceAdmin` action permitted only while the operator has an `OPEN`, `SUCCESSOR_PENDING`, or `SUCCESSOR_APPROVED` exit case. Completing too early, or without the final statement, is refused with `ERR_EXIT_NOT_COMPLETABLE`. A successful completion links the exit case's `final_statement_id` to that terminal statement, moves the case to `COMPLETED`, moves the operator from `EXITING` to the terminal `EXITED` status, cascades the agreement to `TERMINATED`, returns the restaurant to `AVAILABLE` with `current_operator_id` cleared — and, in the same breath, creates the successor's operator record in `ONBOARDING` bound to a fresh `DRAFT` agreement for the same restaurant, so the site is never left without a path to new leadership.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource or record an action against it return `200 OK`. The logical-clock capability also returns `200 OK`. All request and response bodies follow the envelope of §2.2, and list endpoints follow the pagination contract of §2.3. A request whose body is missing a required field or carries a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/franchise/_clock/set_current_utc` | Set the logical clock | SystemAdmin |
| POST | `/franchise/candidates` | Register a candidate | SystemAdmin |
| GET | `/franchise/candidates/{candidateId}` | Get a candidate | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/candidates` | List candidates with filters | SystemAdmin, FieldConsultant, SelectionCommittee |
| POST | `/franchise/candidates/{candidateId}/withdraw` | Withdraw a candidate | Candidate |
| POST | `/franchise/candidates/{candidateId}/disqualify` | Disqualify a candidate | FieldConsultant |
| POST | `/franchise/candidates/{candidateId}/applications` | Submit an application for a candidate | Candidate |
| GET | `/franchise/applications/{applicationId}` | Get an application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/applications` | List applications | SystemAdmin, FieldConsultant, SelectionCommittee |
| POST | `/franchise/applications/{applicationId}/advance` | Advance the application one pipeline stage | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/reject` | Reject an application in SUBMITTED | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/withdraw` | Withdraw an application | Candidate |
| POST | `/franchise/applications/{applicationId}/committee-decision` | Record the committee decision | SelectionCommittee |
| GET | `/franchise/interviews` | List interview rounds, filterable by application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/assessments` | List business assessments, filterable by application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/experiences` | List in-restaurant experiences | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/agreements` | List operator agreements | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/weeks` | List operating weeks across restaurants | SystemAdmin, FieldConsultant, Operator |
| GET | `/franchise/scorecards` | List scorecards across operators | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/relocation-requests` | List relocation requests | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/exits` | List exit cases | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/statements` | List revenue share statements | SystemAdmin, FinanceAdmin, Operator |
| GET | `/franchise/committee-votes` | List committee votes | SystemAdmin, SelectionCommittee |
| GET | `/franchise/interviews/{roundId}` | Get a single interview round | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/assessments/{assessmentId}` | Get a single business assessment | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/experiences/{experienceId}` | Get a single in-restaurant experience | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| GET | `/franchise/agreements/{agreementId}` | Get a single operator agreement | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/weeks/{weekId}` | Get a single operating week | SystemAdmin, FieldConsultant, Operator |
| GET | `/franchise/scorecards/{scorecardId}` | Get a single scorecard | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/exits/{exitId}` | Get a single exit case | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/committee-votes/{voteId}` | Get a single committee vote | SystemAdmin, SelectionCommittee |
| POST | `/franchise/applications/{applicationId}/interviews` | Schedule an interview round | FieldConsultant |
| GET | `/franchise/applications/{applicationId}/interviews` | List interview rounds of an application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| POST | `/franchise/applications/{applicationId}/interviews/{roundId}/score` | Score a scheduled interview round | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/interviews/{roundId}/cancel` | Cancel a scheduled interview round | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/assessment` | Create the business assessment draft | Candidate |
| GET | `/franchise/applications/{applicationId}/assessment` | Get the assessment of an application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| POST | `/franchise/applications/{applicationId}/assessment/submit` | Submit the business assessment | Candidate |
| POST | `/franchise/applications/{applicationId}/assessment/evaluate` | Evaluate the submitted assessment | FieldConsultant |
| POST | `/franchise/restaurants` | Register a restaurant site | SystemAdmin |
| GET | `/franchise/restaurants/{restaurantId}` | Get a restaurant | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/restaurants` | List restaurants | SystemAdmin, FieldConsultant, SelectionCommittee |
| POST | `/franchise/restaurants/{restaurantId}/make-available` | Move a PIPELINE restaurant to AVAILABLE | SystemAdmin |
| POST | `/franchise/applications/{applicationId}/experiences` | Schedule the in-restaurant experience block | FieldConsultant |
| GET | `/franchise/applications/{applicationId}/experiences` | List experiences of an application | SystemAdmin, FieldConsultant, SelectionCommittee, Candidate |
| POST | `/franchise/applications/{applicationId}/experiences/{experienceId}/signoff` | Sign off one completed shift | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/experiences/{experienceId}/complete` | Complete the experience when all shifts are signed off | FieldConsultant |
| POST | `/franchise/applications/{applicationId}/experiences/{experienceId}/cancel` | Cancel a scheduled experience | FieldConsultant |
| POST | `/franchise/operators` | Create an operator record from a SELECTED candidate | SelectionCommittee |
| GET | `/franchise/operators/{operatorId}` | Get an operator | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/operators` | List operators | SystemAdmin, FieldConsultant, SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/attest` | Operator attests residency and full-time involvement | Operator |
| POST | `/franchise/operators/{operatorId}/agreement/execute` | Execute the DRAFT agreement | SelectionCommittee |
| GET | `/franchise/operators/{operatorId}/agreement` | Get the operator's agreement | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| POST | `/franchise/operators/{operatorId}/activate` | Activate an ONBOARDING operator | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/suspend` | Suspend an ACTIVE operator | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/reinstate` | Reinstate a SUSPENDED operator | FieldConsultant |
| POST | `/franchise/restaurants/{restaurantId}/weeks` | Plan an operating week | FieldConsultant |
| GET | `/franchise/restaurants/{restaurantId}/weeks` | List operating weeks of a restaurant | SystemAdmin, FieldConsultant, Operator |
| POST | `/franchise/restaurants/{restaurantId}/weeks/{weekId}/close` | Close an OPEN operating week with actuals | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/scorecards` | Draft a scorecard | FieldConsultant |
| GET | `/franchise/operators/{operatorId}/scorecards` | List scorecards of an operator | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| POST | `/franchise/operators/{operatorId}/scorecards/{scorecardId}/publish` | Publish a draft scorecard | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/scorecards/{scorecardId}/dispute` | Operator disputes a published scorecard | Operator |
| POST | `/franchise/operators/{operatorId}/scorecards/{scorecardId}/republish` | Republish a disputed scorecard | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/scorecards/{scorecardId}/finalize` | Finalize a scorecard after the grace period | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/relocation-requests` | Submit a relocation or second-location request | Operator |
| GET | `/franchise/operators/{operatorId}/relocation-requests` | List relocation requests of an operator | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| GET | `/franchise/relocation-requests/{requestId}` | Get a relocation request | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| POST | `/franchise/operators/{operatorId}/relocation-requests/{requestId}/open-review` | Open committee review on a request | SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/relocation-requests/{requestId}/votes` | Cast a committee vote | SelectionCommittee |
| GET | `/franchise/relocation-requests/{requestId}/votes` | List votes of a relocation request | SystemAdmin, SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/relocation-requests/{requestId}/decide` | Decide a relocation request from committee votes | SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/relocation-requests/{requestId}/withdraw` | Operator withdraws a submitted request | Operator |
| POST | `/franchise/operators/{operatorId}/exits` | Open an exit case | Operator |
| GET | `/franchise/operators/{operatorId}/exits` | List exit cases of an operator | SystemAdmin, FieldConsultant, SelectionCommittee, Operator |
| POST | `/franchise/operators/{operatorId}/exits/{exitId}/propose-successor` | Propose a successor candidate | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/exits/{exitId}/approve-successor` | Committee approves the proposed successor | SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/exits/{exitId}/reject-successor` | Committee rejects the proposed successor | SelectionCommittee |
| POST | `/franchise/operators/{operatorId}/exits/{exitId}/complete` | Complete the exit with a FINAL statement on file | FieldConsultant |
| POST | `/franchise/operators/{operatorId}/exits/{exitId}/cancel` | Operator cancels an open exit case | Operator |
| GET | `/franchise/operators/{operatorId}/statements` | List revenue share statements of an operator | SystemAdmin, FinanceAdmin, Operator |
| GET | `/franchise/statements/{statementId}` | Get a statement | SystemAdmin, FinanceAdmin, Operator |
| POST | `/franchise/statements/{statementId}/settle` | Settle an issued statement | FinanceAdmin |
| POST | `/franchise/statements/{statementId}/void` | Void a provisional statement | FinanceAdmin |
| POST | `/franchise/statements/{statementId}/finalize` | Re-issue a settled provisional statement as FINAL | FinanceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this table lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_WEEK | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_SCREENING_BELOW_THRESHOLD | 422 |
| ERR_INTERVIEW_GATE | 422 |
| ERR_STAGE_MISMATCH | 409 |
| ERR_SCORE_OUT_OF_RANGE | 422 |
| ERR_NO_OPERATING_DAYS | 422 |
| ERR_SHIFT_SHORTFALL | 409 |
| ERR_WEEK_NOT_ELAPSED | 409 |
| ERR_MISSING_ACTUALS | 400 |
| ERR_DUPLICATE_STATEMENT | 409 |
| ERR_STATEMENT_NOT_VOIDABLE | 409 |
| ERR_OPERATOR_NOT_SCORABLE | 409 |
| ERR_SCORECARD_OVERLAP | 409 |
| ERR_FINALIZE_TOO_EARLY | 409 |
| ERR_SINGLE_UNIT_VIOLATION | 422 |
| ERR_AGREEMENT_IMMUTABLE | 422 |
| ERR_RESTAURANT_NOT_AVAILABLE | 409 |
| ERR_QUORUM_NOT_MET | 409 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_NOTICE_TOO_SHORT | 422 |
| ERR_SUCCESSOR_INELIGIBLE | 422 |
| ERR_EXIT_ALREADY_OPEN | 409 |
| ERR_EXIT_NOT_COMPLETABLE | 409 |
