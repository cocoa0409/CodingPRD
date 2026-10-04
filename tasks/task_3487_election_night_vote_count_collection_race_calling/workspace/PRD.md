# Election Night Race Calling API — Product Requirements Document

## 1. Introduction

Election night is a data-collection race run on somebody else's clock. County election offices report precinct results on their own schedules, electronic feeds arrive from state authorities, and a decision desk must tell thousands of media customers who won — but only when the arithmetic makes a comeback impossible. This document specifies the Election Night Race Calling API: a system for preparing election events, deploying a field stringer network to county offices alongside electronic result feeds, collecting and quality-checking vote tabulations, maintaining per-contest rollups with outstanding-vote estimates, publishing and retracting race calls under a strict certainty standard, handling recounts and contested outcomes, and delivering results to licensed media customers under per-delivery pricing.

The API serves two cooperating populations. Internal operators — event administrators, coverage planners, stringer coordinators, tabulation clerks, the decision desk, and recount officers — prepare the event and run the night. External parties — field stringers, feed operators, and media customers — participate under narrowly-scoped identities. Every operation is gated by the election event's posture, a coarse lifecycle state that decides which kinds of work are even admissible at a given moment, and all time semantics in the system are driven by a logical clock rather than wall-clock time, so that an entire election night can be rehearsed deterministically.

Because the desk may call a race only when no trailing candidate can mathematically catch up, the tabulation and estimation rules in this document are normative rather than advisory. The same formulas drive the quality-control flags on incoming reports, the completeness detection that moves contests toward certification, and the certainty evaluation that gates every published call.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the supplied role is not among the roles an endpoint declares in §4, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes exactly ten roles. `ElectionOpsAdmin` is the election operations administrator: prepares events, contests, candidates, counties, and feeds, advances posture, reviews coverage decisions, and registers media customers. `CoveragePlanner` plans primary and special election coverage and stringer-hour allocation. `StringerCoordinator` deploys and manages the stringer network. `Stringer` is a field stringer stationed at a county election office. `FeedOperator` operates electronic result feeds. `TabulationClerk` is the quality-control desk for tabulation entries. `DecisionAnalyst` is the decision desk analyst who proposes race calls. `DecisionDeskChief` publishes and retracts calls. `RecountOfficer` handles recounts and contested outcomes. `MediaCustomer` is a licensed media outlet consuming result feeds and invoices.

Two of these roles are entity-backed. When `X-User-Role` is `Stringer`, `X-User-ID` is the `id` of the acting `Stringer`; ownership checks on any resource that references a stringer — an assignment's `stringer_id`, a vote report's `submitted_by_stringer_id` — compare that field to `X-User-ID`. When `X-User-Role` is `MediaCustomer`, `X-User-ID` is the `id` of the acting `MediaCustomer`; the customer's self-service reads and invoice operations compare the path's customer id to `X-User-ID`. A failed entity-backed ownership check surfaces as `ERR_UNAUTHORIZED_ROLE`, indistinguishable from a role failure.

The remaining eight roles — `ElectionOpsAdmin`, `CoveragePlanner`, `StringerCoordinator`, `FeedOperator`, `TabulationClerk`, `DecisionAnalyst`, `DecisionDeskChief`, and `RecountOfficer` — use opaque operator identifiers: `X-User-ID` is not tied to any persisted entity. The server may record it, for example as `proposed_by` on a race call at proposal time or as `published_by` when a call is published, but it never compares such a value to any entity's `id`.

One separation-of-duties rule cuts across the role list and is stated here once for emphasis: the decision desk chief may never publish a call whose `proposed_by` equals the chief's own `X-User-ID`. The mechanics of that rule live with the decision desk workflow in §3.6.

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

All list endpoints accept the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List responses report the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a filter parameter says otherwise, every list is sorted by `created_at` ascending.

### 2.4. The Logical Clock and Common Resource Properties

No part of this system reads wall-clock time. All notions of "now" — window checks, timestamp stamping, delivery dating — read a server-side logical clock. At server startup, before any request arrives, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An admin-only test-driving capability moves the clock to a supplied `current_utc` instant, in either direction, and every subsequent clock read uses that value. Timestamps such as `accepted_at`, `published_at`, and `delivered_at` are stamped from this clock at the moment their events occur.

Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Election events, counties, contests, stringers, stringer assignments, vote reports, race calls, recount cases, coverage decisions, and media customers additionally carry `updated_at` — same format, refreshed on every mutation — and `version`, an integer that increments by one on every mutation of that resource. County links, candidates, feed sources, result deliveries, and media invoices carry only `id` and `created_at`: both `updated_at` and `version` are absent on those five resource types.

### 2.5. Event Posture: The Master Switchboard

An election event's `posture` is the master gate for everything that happens beneath it. The lifecycle runs `SETUP` → `CANDIDATES_LOCKED` → `LIVE` → `TABULATION` → `CERTIFICATION` → `ARCHIVED`, with `ARCHIVED` terminal. One edge runs backward: when a recount case of a contest in the event is activated while the posture is `CERTIFICATION`, the event automatically reopens from `CERTIFICATION` to `TABULATION` (see §3.7), so the posture machine is cyclic and the `CERTIFICATION` → `TABULATION` → `CERTIFICATION` cycle may repeat as recounts activate and resolve.

An `ElectionOpsAdmin` requests posture advances through the posture-transition capability, naming a `target_posture`. The requested target must be the declared next state — skipping ahead or stepping backward is not admitted — and the automatic `CERTIFICATION` → `TABULATION` reopen is system-only: it is rejected when requested through this capability. Every successful transition increments the event's `version` by one. A request naming a target that is not the declared next state, or whose transition preconditions are unmet, is rejected with `ERR_INVALID_STATE` (HTTP 409). The forward transitions and their preconditions are:

- `SETUP` → `CANDIDATES_LOCKED` (candidate lock) requires three things: at least one contest exists in the event; every contest in the event has at least two candidates and at least one county link; and, for events whose `event_type` is `PRIMARY` or `SPECIAL`, every contest has at least one coverage decision in status `APPROVED` or `FUNDED`. `GENERAL` and `RUNOFF` events are exempt from the coverage requirement.
- `CANDIDATES_LOCKED` → `LIVE` requires the logical clock to be within election day: at or after midnight UTC of the event's `event_date` and strictly before midnight UTC of the following day.
- `LIVE` → `TABULATION` requires at least one vote report to exist in the event with status `RECEIVED`, `FLAGGED`, or `ACCEPTED`.
- `TABULATION` → `CERTIFICATION` requires every contest in the event to have reached `tabulation_status` `COMPLETE`.
- `CERTIFICATION` → `ARCHIVED` requires that no recount case in status `FILED` or `ACTIVE` exists for any contest of the event.

The posture also decides which operations are admissible at all. Registering counties, contests, candidates, county links, and feed sources, and editing contest configuration, require `SETUP`. Creating stringer assignments and coverage decisions requires `SETUP` or `CANDIDATES_LOCKED`. Stringer check-in and vote-report submission and resubmission require `LIVE` or `TABULATION`. Call proposal and call publication require `TABULATION`. Recount filing requires `TABULATION` or `CERTIFICATION`. Accepting a vote report at the tabulation desk is the one review action admitted beyond tabulation: it is allowed in `LIVE`, `TABULATION`, and `CERTIFICATION`. Any operation attempted in a posture that does not admit it is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409).

### 2.6. Nested Path Resolution

Resource URLs nest: an event segment comes first, then a contest or county segment, then child resources beneath them. Path identifiers resolve left to right, and every referenced id must exist. The first unresolved segment determines the not-found error: `ERR_EVENT_NOT_FOUND` for the event, then `ERR_CONTEST_NOT_FOUND` or `ERR_COUNTY_NOT_FOUND` at the second tier, and `ERR_STRINGER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_RECOUNT_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, or `ERR_CUSTOMER_NOT_FOUND` for the corresponding child resources — all HTTP 404.

Resolving successfully is not the same as belonging. A county or contest that exists but belongs to a different election event than the path's event is a cross-event reference, rejected with `ERR_CROSS_EVENT_REFERENCE` (HTTP 422) at the nested creation endpoints that accept a `county_id` or `contest_id` in their payload — never a 404.

### 2.7. Optimistic Concurrency on the Contest Aggregate

Exactly two write operations carry optimistic concurrency control, both guarded on the contest's `version`: submitting a vote report (`POST /contests/{id}/vote-reports`) and proposing a race call (`POST /contests/{id}/calls`). Each request must carry `expected_contest_version` as a non-optional input field holding the contest `version` the client last observed. If the value does not match the contest's current `version` — because an intervening vote report, review decision, call proposal, publication, retraction, or configuration edit advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the contest before writing. The rule exists because a prior accepted submission or call proposal legitimately advanced the contest's rollups and version, so the current writer's view of the contest is stale.

No other endpoint accepts a version field. The writes that themselves advance the contest's `version` by one are: vote-report submission, call proposal, the ACCEPT and VOID review decisions, call publication, retraction of a published call, and pre-lock contest configuration edits.

### 2.8. Numbers, Precision, and Rounding

Vote figures, precinct counts, stringer-hours, and reliability scores are integers throughout. Ratios — `margin_pct`, `deviation_ratio`, `swing_deviation`, and the filed-margin snapshot — are numbers carried to 6 decimal places, rounded half up. Money is integer cents: each delivery's fee is rounded half up to whole cents at the moment the delivery is created, and an invoice total is a plain integer sum of those already-rounded per-delivery fees, never re-rounded at invoice time. Reliability scores are integers clamped to lie between 0 and 100 inclusive.

### 2.9. Validation Priority Order

When a single request would violate several rules, the check with the lowest priority number produces the response; the twenty checks below are listed in that evaluation order.

1. Authentication: both `X-User-ID` and `X-User-Role` headers present and non-blank, else `ERR_UNAUTHENTICATED`.
2. Role admission: the role is among the endpoint's declared roles, else `ERR_UNAUTHORIZED_ROLE`.
3. Entity-backed ownership: a stringer acting on a stringer assignment must satisfy `X-User-ID` equal to the assignment's `stringer_id`, and a media customer touching the resources beneath their own path must satisfy `X-User-ID` equal to that customer's `id`. This check applies to `POST /assignments/{id}/check-in`, `POST /vote-reports/{id}/resubmit`, `GET /media-customers/{id}`, `GET /media-customers/{id}/deliveries`, `POST /media-customers/{id}/invoices`, and `GET /media-customers/{id}/invoices`; breaches are `ERR_UNAUTHORIZED_ROLE`.
4. Path existence, resolved left to right per §2.6, producing the segment's specific not-found error.
5. The posture gate of §2.5 on every mutating endpoint, else `ERR_POSTURE_FORBIDS`.
6. Entity state preconditions on every state-transition endpoint: the resource must sit in a from-state that admits the transition, else `ERR_INVALID_STATE`. Within this priority, on call publication the two specific guards come first — an active recount surfaces as `ERR_RECOUNT_ACTIVE_BLOCKS_CALL` and an already-called contest as `ERR_CALL_ALREADY_PUBLISHED` — before the generic `ERR_INVALID_STATE`.
7. Optimistic concurrency on the two OCC endpoints of §2.7: `expected_contest_version` must equal the contest's current `version`, else `ERR_STALE_VERSION`.
8. Segregation of duties on call publication: the publisher's `X-User-ID` must differ from the call's `proposed_by`, else `ERR_SEGREGATION_OF_DUTIES`.
9. The calling standard on call publication: the certainty evaluation must pass for the proposed winner, else `ERR_CERTAINTY_NOT_MET`.
10. Cross-event reference: a `county_id` or `contest_id` supplied to a nested creation must belong to the path's event, else `ERR_CROSS_EVENT_REFERENCE` — on assignment creation, coverage-decision creation, and county linking.
11. Membership: a `winner_candidate_id` and every `candidate_votes` entry must belong to the contest, and a vote report's `county_id` must be linked to the contest — `ERR_CANDIDATE_NOT_IN_CONTEST` for the candidate cases, `ERR_COUNTY_NOT_IN_CONTEST` for the county-link case. Applies to call proposals, vote-report submissions, and resubmissions.
12. Collection authority on vote-report submission: a `STRINGER` report needs an `ACTIVE` assignment covering the stringer, county, and event, else `ERR_STRINGER_NOT_DEPLOYED`; a `FEED` report needs a feed source of the event covering the county's state, else `ERR_FEED_COVERAGE_MISSING`.
13. Interval well-formedness on assignment creation, coverage-decision creation, and coverage revision: `window_start` strictly before `window_end`, and `coverage_start` not after `coverage_end`, else `ERR_INVALID_REQUEST`.
14. Assignment window overlap on assignment creation, else `ERR_ASSIGNMENT_WINDOW_OVERLAP`.
15. Clock against window on check-in and the coordinator status actions, else `ERR_OUTSIDE_ASSIGNMENT_WINDOW`.
16. Payload shape on every endpoint: required fields present, enum values in range, integer bounds respected (`expected_precincts` at least 1, vote figures non-negative, `allocated_stringer_hours` at least 1, `candidate_votes` non-empty, `state_codes` and `licensed_states` non-empty), else `ERR_INVALID_REQUEST`.
17. Uniqueness on the creation endpoints: `county_fips` per event (`ERR_DUPLICATE_COUNTY`), `feed_name` per event (`ERR_DUPLICATE_FEED`), `candidate_name` per contest (`ERR_DUPLICATE_CANDIDATE`), the contest-county link pair (`ERR_DUPLICATE_COUNTY_LINK`), and the customer-period invoice pair (`ERR_DUPLICATE_INVOICE`).
18. Bounds and selector on vote-report submission, resubmission, and assignment creation: `precincts_reporting` must not exceed the county's `expected_precincts` (`ERR_PRECINCTS_EXCEED_EXPECTED`), and assignment auto-selection against an empty eligible pool fails with `ERR_NO_ELIGIBLE_STRINGER`.
19. The coverage budget on approval and funding reviews, else `ERR_COVERAGE_BUDGET_EXCEEDED`.
20. License gating on the customer deliveries feed: a `BASIC` customer may not query `CALL` or `CALL_CREDIT` content, else `ERR_LICENSE_TIER_FORBIDS`.

## 3. Business Logic & Workflows

### 3.1. Building the Event: Counties, Contests, Candidates, and Feeds

Preparation begins when an `ElectionOpsAdmin` creates the election event. The event carries a human-readable `event_name`, an `event_date` given as an ISO calendar date — any valid date is accepted, including dates in the past for historical rehearsals — an `event_type` of `GENERAL`, `PRIMARY`, `SPECIAL`, or `RUNOFF`, and a `total_stringer_hour_budget`, the total deployable stringer-hours across all approved coverage decisions for the event, which must be at least 1. The event's `stringer_selection_mode`, either `CAREER` or `RECENT_FORM`, chooses which reliability variant the assignment auto-selector of §3.3 ranks by, and it defaults to `CAREER` when omitted. A new event begins in posture `SETUP`.

While the event is in `SETUP`, the administrator registers its reporting geography. Each county is registered under the event it belongs to (recorded as its `event_id`) with a five-digit `county_fips` unique within the event — a duplicate is rejected with `ERR_DUPLICATE_COUNTY` — a `county_name`, a two-letter `state_code`, an `expected_precincts` count of at least 1, and an `expected_vote_total` of at least 1, the historical-turnout basis against which election-night entries are quality-checked. Two optional baselines refine the desk's picture: `survey_turnout_estimate`, a survey-based turnout estimate for election night that may be null, and `historical_dem_share`, the historical two-party DEM share as a fraction between 0 and 1, also nullable; when it is null, the swing quality check of §3.4 is skipped for that county. A county exposes two computed fields from the outset, `reported_precincts` and `status`, initially zero and `PENDING` respectively (§3.5).

Contests are created in the same `SETUP` window, each with an `office_name`, the two-letter `state_code` the contest is decided in, a `contest_type` of `FEDERAL_EXEC`, `FEDERAL_SENATE`, `FEDERAL_HOUSE`, `STATE`, or `BALLOT_MEASURE`, and `seats` — the number of winners the contest elects, at least 1 and defaulting to 1. A new contest starts with `tabulation_status` `AWAITING` and `call_status` `UNCALLED`, and its rollup fields `reported_precincts`, `total_votes`, `margin_pct`, and `outstanding_estimate` read as zero. Before candidate lock the administrator may still edit the contest's `office_name` and `seats`; each such edit increments the contest's `version` by one.

A contest's reporting geography is assembled county by county. Linking a county into a contest requires only the `county_id`; the county must belong to the same event as the contest (a county of another event is rejected with `ERR_CROSS_EVENT_REFERENCE`), the same contest-county pair may not be linked twice (`ERR_DUPLICATE_COUNTY_LINK`), and every linked county shares the contest's `state_code`, since a contest is decided within a single state. Ballot candidates are added to a contest with a `candidate_name` unique within that contest (`ERR_DUPLICATE_CANDIDATE`), a `party` of `DEM`, `REP`, `IND`, `LIB`, `GRN`, or `OTHER`, and an `is_incumbent` flag for desk notes that defaults to false. `BALLOT_MEASURE` contests carry their YES/NO options as ordinary candidates.

Electronic collection authority is registered as feed sources, again only in `SETUP`: a `feed_name` unique within the event (`ERR_DUPLICATE_FEED`), a non-empty array `state_codes` of two-letter state codes the feed is authorized to report for, and a `priority_tier` of `PRIMARY` or `SECONDARY`, defaulting to `SECONDARY`, which serves purely as a desk priority label and gates nothing.

Candidate lock — the posture transition from `SETUP` to `CANDIDATES_LOCKED` described in §2.5 — is the point of no return for this preparation phase. It demands at least one contest, at least two candidates and one county link on every contest, and, for `PRIMARY` and `SPECIAL` events, an approved or funded coverage decision on every contest (§3.2). Once locked, the structural records of this section are frozen; the remaining lifecycle happens around them.

### 3.2. Coverage Planning and the Stringer-Hour Budget

For primaries and special elections the desk must decide — before candidate lock — which contests earn field coverage, and every such decision spends from a finite purse. A `CoveragePlanner` proposes coverage of a contest while the event is in `SETUP` or `CANDIDATES_LOCKED`, supplying the `contest_id` of a contest of the same event (a contest of another event is rejected with `ERR_CROSS_EVENT_REFERENCE`), the requested `allocated_stringer_hours` of at least 1, and a coverage interval as two ISO calendar dates, `coverage_start` and `coverage_end`. The interval is closed — both boundary days count as covered — and the start must not fall after the end, else the proposal is rejected with `ERR_INVALID_REQUEST`. An optional `rationale` carries the planner's note for the desk. A new decision starts in status `PROPOSED`.

An `ElectionOpsAdmin` then reviews each proposal, naming a `decision` of `APPROVE`, `DECLINE`, or `FUND`. Approval is budgeted: the sum of `allocated_stringer_hours` over the event's decisions already in `APPROVED` or `FUNDED` status whose closed coverage intervals intersect this decision's closed interval, plus this decision's own hours, must not exceed the event's `total_stringer_hour_budget`; if the total would breach the budget, the review is rejected with `ERR_COVERAGE_BUDGET_EXCEEDED`. Because intersection is judged on closed intervals, two decisions that share exactly one boundary day do intersect. Approval moves the decision from `PROPOSED` to `APPROVED`.

Funding is a second, separate gate: a review of `FUND` moves an `APPROVED` decision to `FUNDED` and re-runs the same aggregate budget check at that later moment, since other decisions may have consumed budget in the meantime. `FUNDED` is the terminal status. A `DECLINE` review moves a `PROPOSED` decision to `DECLINED` with no budget implication at all.

Decline is not the end of the road. The planner may revise a `DECLINED` decision back to `PROPOSED`, supplying new `allocated_stringer_hours` and/or new `coverage_start` and `coverage_end` values, and the interval well-formedness rule applies to the revised dates exactly as at creation. This decline-and-revise loop may repeat until the decision is approved or quietly abandoned — which matters because, for `PRIMARY` and `SPECIAL` events, candidate lock in §3.1 waits on every contest holding at least one decision in `APPROVED` or `FUNDED` status.

### 3.3. The Stringer Network: Roster, Reliability, and Deployment

Stringers are field staff stationed at county election offices to phone results in directly. A `StringerCoordinator` registers each stringer on the network roster with a `stringer_name` and a two-letter `home_state`. The roster entry accumulates three lifetime counters — `no_show_count`, `accepted_report_count`, and `voided_report_count`, each starting at 0 — and two reliability scores, `reliability_career` and `reliability_recent_form`, each starting at 100.

Both scores come from one formula evaluated over two windows. The score starts at 100, subtracts twenty-five points for every no-show, subtracts ten points for every authored report that was voided after acceptance, adds two points for every authored report that was accepted, and is then clamped so it never falls below 0 and never rises above 100. The `CAREER` variant counts those outcomes over every election event in which the stringer holds or ever held an assignment. The `RECENT_FORM` variant counts only events whose `event_date` falls later than the date three hundred sixty-five days before the evaluated event's own `event_date`, so old no-shows age out: a stringer who no-showed two years ago and has been clean since scores 100 on `RECENT_FORM` but 75 on `CAREER`. The "evaluated event" is the event an assignment is being selected for; a bare roster read evaluates `RECENT_FORM` against the greatest `event_date` among the stringer's assignments, and against the fixed default date 2026-09-01 when the stringer has none. Both scores are recomputed at exactly three moments: when one of the stringer's assignments is marked no-show, when an authored report is accepted, and when an authored report is voided.

Deployment happens per event. A `StringerCoordinator` deploys a stringer to a county office by creating an assignment — admitted in `SETUP` and `CANDIDATES_LOCKED` — naming the `county_id` of a county of the same event (`ERR_CROSS_EVENT_REFERENCE` otherwise) and a deployment window from `window_start` to `window_end`, both ISO 8601 UTC instants. The window is half-open: it covers every instant at or after `window_start` and strictly before `window_end`, and the start must be strictly before the end, else `ERR_INVALID_REQUEST`. The coordinator may name the `stringer_id` explicitly or omit it to invoke the auto-selector.

One stringer cannot be in two places at once: no stringer may hold two assignments in `SCHEDULED` or `ACTIVE` status whose half-open windows overlap. Touching endpoints are permitted, so a window that ends at the exact instant another begins is legal; a genuinely overlapping request is rejected with `ERR_ASSIGNMENT_WINDOW_OVERLAP`. When `stringer_id` is omitted, the eligible pool is every rostered stringer with no overlapping `SCHEDULED` or `ACTIVE` assignment for the requested window, ranked by the reliability variant named by the event's `stringer_selection_mode` — highest score first, ties broken by earliest roster registration — and an empty pool rejects the request with `ERR_NO_ELIGIBLE_STRINGER`. These guards evaluate in the global order of §2.9: a malformed window surfaces before an overlap, and an overlap before an empty-selector rejection. The assignment records `auto_selected` as true when the selector ran and false when the coordinator named the stringer. A new assignment is `SCHEDULED`.

On election day, check-in is self-service. A stringer checks in to their own assignment — `X-User-ID` must equal the assignment's `stringer_id`, else `ERR_UNAUTHORIZED_ROLE` — while the event is `LIVE` or in `TABULATION`, and while the logical clock sits inside the half-open window; a check-in outside the window is rejected with `ERR_OUTSIDE_ASSIGNMENT_WINDOW`. A successful check-in moves the assignment from `SCHEDULED` to `ACTIVE`.

The coordinator manages the rest of the lifecycle with a named `action`. `RELEASE` moves an `ACTIVE` assignment to `RELEASED` with no further preconditions. `NO_SHOW` moves a `SCHEDULED` assignment to `NO_SHOW`, admitted only once the logical clock has reached or passed the window's end — otherwise `ERR_OUTSIDE_ASSIGNMENT_WINDOW`; the mark increments the stringer's `no_show_count` by one and recomputes both reliability scores, and `NO_SHOW` is absorbing. `REDEPLOY` moves a `RELEASED` assignment back to `ACTIVE`, requiring the logical clock to still be strictly before the window's end. An `ACTIVE` assignment is the credential a stringer needs to file vote reports from the county office, which is the subject of the next section.

### 3.4. Election Night Intake: Vote Reports and Quality Control

Once the event is `LIVE`, results flow in through two channels. A field stringer submits a tabulation entry with `source` `STRINGER`; a feed operator submits one with `source` `FEED`. Both channels are admitted in postures `LIVE` and `TABULATION`, whatever the contest's `tabulation_status` — `AWAITING`, `REPORTING`, or `COMPLETE`, since a report against a completed contest is exactly how corrections arrive during a recount reopen. Each report names the reporting `county_id`, which must be linked to the contest through its geography (else `ERR_COUNTY_NOT_IN_CONTEST`); the `precincts_reporting` count, at least 1 and never more than the county's `expected_precincts` (else `ERR_PRECINCTS_EXCEED_EXPECTED`); a non-empty `candidate_votes` array whose entries pair a `candidate_id` with a non-negative integer `votes`, where every `candidate_id` must belong to the contest (else `ERR_CANDIDATE_NOT_IN_CONTEST`); and the `expected_contest_version` required by §2.7. The guards evaluate in the §2.9 order, so a stale contest version surfaces before a membership problem, and a membership problem before a collection-authority problem.

Collection authority differs by channel. A `STRINGER` report requires an `ACTIVE` assignment covering exactly this stringer — identified by `X-User-ID` — this county, and this event; without one the submission is rejected with `ERR_STRINGER_NOT_DEPLOYED`, and the report records the submitting stringer in `submitted_by_stringer_id`, taken from `X-User-ID`. A `FEED` report requires a feed source of the event whose `state_codes` contains the county's `state_code`; without coverage it is rejected with `ERR_FEED_COVERAGE_MISSING`, and `submitted_by_stringer_id` remains null.

Acceptance into the intake queue has three immediate effects. The contest's `version` increments by one. If this is the contest's first report, its `tabulation_status` moves from `AWAITING` to `REPORTING` regardless of the status the report itself lands in. And the quality-control check runs. The report's `reported_total` — the sum of the votes across its `candidate_votes` entries — is compared with the county's `expected_vote_total` to form the `deviation_ratio`: the absolute difference between the two, divided by `expected_vote_total`, rounded half up to six decimal places. When the county's `historical_dem_share` is not null, the contest fields a `DEM` candidate, and `reported_total` is positive, the check also computes `swing_deviation`: the absolute difference between the county's `historical_dem_share` and the reported DEM share, where the reported DEM share is the contest's DEM candidate's votes divided by the greater of `reported_total` and 1 — again rounded half up to six decimal places. In every other case `swing_deviation` is null. The report lands `FLAGGED` when the `deviation_ratio` is strictly greater than 0.40 — forty percent of the expected total — or when a non-null `swing_deviation` is strictly greater than 0.25, and it lands `RECEIVED` otherwise. Both thresholds are strict: a `deviation_ratio` of exactly 0.400000 does not flag. Quality control never rejects on its own — but three intake failures are hard rejections rather than flags: a precinct count above the county's expectation, a candidate identifier foreign to the contest, and negative vote figures.

A `TabulationClerk` then works the queue with a `decision` of `ACCEPT`, `REJECT`, or `VOID`. ACCEPT moves a `RECEIVED` or `FLAGGED` report to `ACCEPTED` and is admitted in postures `LIVE`, `TABULATION`, and `CERTIFICATION`. The report's `accepted_at` stamps the logical clock; the contest rollup of §3.5 recomputes, which mutates the contest's computed fields and therefore increments the contest's `version` by one, and which may complete the contest; one `VOTE_UPDATE` delivery fans out per eligible media customer per §3.8; and when the report is stringer-authored, the author's `accepted_report_count` increments by one and both reliability scores recompute. REJECT moves a `RECEIVED` or `FLAGGED` report to `REJECTED` and carries no further preconditions.

VOID is the compensation path: it moves an `ACCEPTED` report to `VOIDED`, resets `accepted_at` to null, and recomputes the rollup with the report removed — incrementing the contest's `version` again, and reopening the contest from `COMPLETE` back to `REPORTING` if the reporting county thereby loses the complete latest accepted report that had closed it. A stringer-authored report additionally increments its author's `voided_report_count` by one with a reliability recompute. Because only `ACCEPTED` reports ever feed the rollup, VOID compensates ACCEPT exactly: the contest's totals return to their pre-acceptance values. `VOIDED` is terminal.

A rejected report is not dead. The original channel may resubmit it with corrected `precincts_reporting` and `candidate_votes`; for a `STRINGER` report only the original author may resubmit — `X-User-ID` must equal the report's `submitted_by_stringer_id` — while any `FeedOperator` may resubmit a `FEED` report. Resubmission is admitted in postures `LIVE` and `TABULATION`, enforces the same precinct and candidate-membership bounds as creation, and re-runs the quality-control check, landing the report `RECEIVED` or `FLAGGED` by exactly the same rule as at creation. The reject-and-resubmit cycle may repeat as often as needed.

### 3.5. The Tabulation Board: Rollups, Margins, and Outstanding Votes

The tabulation board is the decision desk's working surface, and everything on it derives from one rule: only reports in `ACCEPTED` status ever enter the rollup — `RECEIVED`, `FLAGGED`, `REJECTED`, and `VOIDED` reports are excluded entirely. For each county linked to the contest, the rollup selects that county's latest accepted report: the one with the greatest `accepted_at`, with ties broken by the greatest `created_at`, never by identifier. A linked county with no accepted report contributes nothing.

Summing the selected reports' `precincts_reporting` over the linked counties yields the contest's `reported_precincts`. Summing each candidate's votes across the selected reports — a candidate missing from a report's entries counts as zero there — yields per-candidate totals, and their sum is the contest's `total_votes`. Candidates are ranked by total, highest first, with ties broken by earliest candidate registration. The contest's `margin_pct` is the difference between the top candidate's total and the runner-up's total, divided by the greater of `total_votes` and 1, rounded half up to six decimal places; when fewer than two candidates have any votes, `margin_pct` is exactly 0.0. A linked county counts as complete when its selected report exists and covers a precinct count equal to the county's `expected_precincts`; the contest's `tabulation_status` becomes `COMPLETE` precisely when every linked county is complete and at least one county is linked, and it falls back to `REPORTING` whenever a recompute finds that no longer true. The rollup runs when a report is accepted, when one is voided, and whenever the board is read.

The board also reports how much vote is still out, per linked county, in two variants. The historical estimate scales the county's `expected_vote_total` by the share of precincts not yet reporting: the expected total multiplied by the ratio of remaining precincts to `expected_precincts`, rounded down to a whole vote, with a county that has no accepted report counting zero precincts reported. The survey estimate, defined only when the county's `survey_turnout_estimate` is not null, is that estimate minus the votes already reported for the county, floored at zero; when the survey estimate is null, the survey estimate falls back to the historical estimate. The county's outstanding figure is the larger of the two variants, and the contest's `outstanding_estimate` is the sum of those per-county figures — so a fully reported county contributes zero. The two variants genuinely differ whenever the survey estimate does not equal the historical scaling of what has been reported, and the desk standard of §3.6 always consumes the maximum of the two.

A read of the board returns `contest_id`, `tabulation_status`, `call_status`, `reported_precincts`, `expected_precincts_total`, the ranked `candidate_totals`, `total_votes`, `margin_pct`, `outstanding_estimate`, and the per-county `outstanding_detail`.

The same latest-accepted selection surfaces at county level. A county's computed `reported_precincts` reflects the maximum `precincts_reporting` among the latest accepted reports naming that county, and reads zero when none exist. The county's `status` reads `PENDING` before any accepted report names it, `REPORTING` once one does, and `COMPLETE` when a linked contest's latest accepted report for the county covers a precinct count equal to the county's `expected_precincts`.

### 3.6. The Decision Desk: Certainty Standards and Call Publication

Race calling is a two-person operation by design: a `DecisionAnalyst` proposes, a `DecisionDeskChief` publishes, and the chief may never publish a call they proposed themselves.

Proposal is admitted only in posture `TABULATION`. The analyst names the `winner_candidate_id`, which must belong to the contest (else `ERR_CANDIDATE_NOT_IN_CONTEST`), and the request carries the `expected_contest_version` of §2.7 — the guards evaluate in the §2.9 order, so a stale version surfaces before a membership problem. A successful proposal increments the contest's `version` by one, records the analyst's `X-User-ID` as the call's `proposed_by`, and lands the call in `PROPOSED`. The certainty standard is deliberately not evaluated at proposal time: an analyst may float a speculative call to focus the desk's attention.

Publication is where the standard bites, and it is evaluated only at publication time, never carried over from proposal. The desk chief acts with an `action` of `PUBLISH`, and the publish path evaluates its guards in the global order of §2.9: the event must be in `TABULATION` posture; then the state checks, within which an `ACTIVE` recount case on the contest is reported as `ERR_RECOUNT_ACTIVE_BLOCKS_CALL` and an already-called contest as `ERR_CALL_ALREADY_PUBLISHED`, both ahead of the generic `ERR_INVALID_STATE` that covers the remaining from-state violations (the contest's `tabulation_status` must be `REPORTING` or `COMPLETE`, and its `call_status` must be `UNCALLED`); then segregation of duties, under which a chief whose `X-User-ID` equals the call's `proposed_by` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); and only then the certainty standard, whose failure rejects with `ERR_CERTAINTY_NOT_MET` (HTTP 422).

The certainty standard is certainty, not projection: the desk calls a winner only when no trailing candidate can catch up on the outstanding vote estimate — never on the basis of poll-close timing or expectation. Let the proposed winner be W, and let the contest elect `seats` winners. For a single-seat contest, W is callable only when W's total strictly exceeds every other candidate's total plus the contest's `outstanding_estimate`; exact equality fails, because a trailing candidate could still tie, and a tie is not certainty. For a multi-seat contest, consider the candidate ranked one place below the last winning rank; when fewer candidates have any votes than `seats` plus one, W is callable exactly when W's total is greater than zero, and otherwise W is callable only when W's total strictly exceeds that next candidate's total plus the `outstanding_estimate` and W ranks within the first `seats` places. A `BALLOT_MEASURE` contest always applies the single-seat rule, whatever its `seats` value, with the YES/NO options standing as the candidates.

A published call flips the contest's `call_status` from `UNCALLED` to `CALLED` and records the winner in the contest's `called_candidate_id`. The call stamps `published_at` from the logical clock, records the chief's `X-User-ID` as `published_by`, increments the contest's `version` by one, and fires the `CALL` delivery fan-out of §3.8. A contest is `CALLED` exactly while one published call exists for it.

Retraction runs from both live states, with an `action` of `RETRACT` and an optional `reason`. Retracting a `PROPOSED` call — nothing was ever published — simply records the supplied `reason` as `retract_reason` and moves the call to `RETRACTED`, with no delivery effects at all. Retracting a `PUBLISHED` call records `retract_reason` likewise — or the fixed reason `RECOUNT_OVERTURNED` when the retraction is system-driven by the recount cascade of §3.7 — clears the contest's `called_candidate_id` to null, flips `call_status` back to `UNCALLED` with another increment of the contest's `version`, and compensates the delivery record as §3.8 describes. The contest's two state dimensions evolve independently: retracting a call never changes `tabulation_status`, and the `UNCALLED` → `CALLED` → `UNCALLED` cycle may repeat. `RETRACTED` is the call's terminal status.

### 3.7. Recounts and Contested Outcomes

A `RecountOfficer` files a recount case against a completed contest while the event is in posture `TABULATION` or `CERTIFICATION`. Filing requires the contest's `tabulation_status` to be `COMPLETE` — a contest still collecting reports is rejected with `ERR_INVALID_STATE` — and its `margin_pct` to be no greater than 0.005, half a percentage point, with the threshold inclusive: a margin of exactly 0.005 is fileable, while anything wider is rejected with `ERR_RECOUNT_MARGIN_EXCEEDED`. The filing accepts an optional `note`, snapshots the contest's current `margin_pct` into the case's `filed_margin_pct`, and lands the case in `FILED`.

Activation moves the case from `FILED` to `ACTIVE` with no further preconditions, and it is the trigger for the posture reopen cycle of §2.5: if the event's posture is `CERTIFICATION` at that moment, the event automatically returns from `CERTIFICATION` to `TABULATION`, and every contest holding an `ACTIVE` recount case reopens from `COMPLETE` to `REPORTING`, readmitting corrected vote reports. The reopen cycle may repeat as further recounts activate and resolve. Running the other direction, the event cannot be archived while any recount case of any of its contests remains `FILED` or `ACTIVE`.

A case that should not proceed is dismissed, moving from `FILED` to `DISMISSED`; the dismissal accepts an optional `note` while leaving `resolution_note` null. A case that runs its course is resolved from `ACTIVE` with an `outcome` of `CONFIRMED` or `OVERTURNED`, and the optional `note` supplied at resolution is recorded as the case's `resolution_note`. Resolving `CONFIRMED` closes the case with no further effect: the original outcome stands.

Resolving `OVERTURNED` fires a three-hop cascade. First, the contest's published race call, if one exists, is retracted with the fixed `retract_reason` `RECOUNT_OVERTURNED`. Second, that retraction flips the contest's `call_status` from `CALLED` back to `UNCALLED` and clears `called_candidate_id` to null. Third, the delivery compensation of §3.8 fires: every `CALL` delivery of the contest still in `SENT` status flips to `STALE`, and each customer that received such a delivery is issued a compensating `CALL_CREDIT` delivery. `DISMISSED`, `RESOLVED_CONFIRMED`, and `RESOLVED_OVERTURNED` are all terminal.

### 3.8. Result Delivery, Licensing, and Monthly Invoicing

Media customers are registered by an `ElectionOpsAdmin` with a `customer_name`, a `license_tier` of `BASIC`, `STANDARD`, or `PREMIUM`, and a non-empty `licensed_states` array of two-letter state codes. The tier gates content: a `BASIC` customer only ever receives `VOTE_UPDATE` content, while `CALL` and `CALL_CREDIT` content requires `STANDARD` or `PREMIUM`. A customer may read their own record, their own delivery feed, and their own invoices — with `X-User-ID` equal to the customer's `id` — and an administrator may read any customer's; a customer touching another customer's resources fails the ownership check of §2.9 with `ERR_UNAUTHORIZED_ROLE`.

Deliveries are never created directly; three system events fan them out, and each delivery records its `customer_id`, its `contest_id`, its `content_type`, its `status`, and a `delivered_at` stamp from the logical clock at creation. Accepting a vote report creates one `VOTE_UPDATE` delivery per customer whose `licensed_states` contains the reporting county's `state_code`, at every license tier. Publishing a race call creates one `CALL` delivery per customer whose `licensed_states` contains the contest's `state_code` and whose tier is `STANDARD` or `PREMIUM`. Retracting a published call — whether by the desk or by the recount cascade — flips every `CALL` delivery of the contest still in `SENT` status to `STALE`, and creates for each customer that received such a delivery a compensating `CALL_CREDIT` delivery in `SENT` status whose `fee_cents` is the exact negation of the original `CALL` delivery's fee. Only `CALL` deliveries ever become `STALE`.

Delivery pricing is fixed at creation, per delivery, in a pinned round-then-sum order. The base fee is 999 cents for a `VOTE_UPDATE` and 4999 cents for a `CALL`. The recipient's tier applies a multiplier of 1.0 for `PREMIUM`, 0.6 for `STANDARD`, and 0.35 for `BASIC`. The product of base and multiplier is rounded half up to whole cents and stored as the delivery's `fee_cents`; a `CALL_CREDIT` carries the negated fee of the `CALL` delivery it compensates, exactly.

The customer's delivery feed is their audit view, filterable by `content_type` and `status`. A `BASIC` customer may not query the `CALL` or `CALL_CREDIT` content types at all — the attempt is rejected with `ERR_LICENSE_TIER_FORBIDS` (HTTP 403).

Billing is monthly and self-service for the customer as well as available to the administrator. Generating an invoice for a `period` given as a `YYYY-MM` billing month counts the customer's deliveries whose `delivered_at` falls inside that UTC calendar month — both `SENT` and `STALE` rows are billed, and `CALL_CREDIT` rows count — into the invoice's `delivery_count`, and sums their already-rounded `fee_cents` into `total_fee_cents`. The invoice total is a plain integer sum of per-delivery fees: the rounding happened at delivery creation, and summing unrounded products with a single rounding at the end is forbidden. For example, three `VOTE_UPDATE` deliveries to a `BASIC` customer bill three times the rounded value of 999 times 0.35 — three times 350, that is 1050 cents — and never the single-rounded alternative of 1049 cents. At most one invoice exists per customer and `period`: a second generation for the same pair is rejected with `ERR_DUPLICATE_INVOICE`.

## 4. Endpoint Definitions

The table below lists every endpoint. Creating a resource that did not exist before the request returns HTTP 201; reads, modifications, and lifecycle actions on existing resources return HTTP 200. Descriptions are summaries only — request payloads, computed fields, guard conditions, and side effects are specified by the workflows of §3 and the principles of §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock to any supplied instant (test-driving; starts at 2026-09-01T00:00:00Z) | ElectionOpsAdmin |
| POST | /election-events | Create an election event in posture SETUP | ElectionOpsAdmin |
| GET | /election-events/{id} | Read one election event including posture | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /election-events/{id}/posture-transitions | Advance the event posture to the declared next state | ElectionOpsAdmin |
| POST | /election-events/{id}/counties | Register a reporting county with expected baselines (SETUP only) | ElectionOpsAdmin |
| GET | /election-events/{id}/counties | List counties of the event | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| GET | /counties/{id} | Read one county including computed reported_precincts and status | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /election-events/{id}/contests | Create a contest in the event (SETUP only); starts AWAITING / UNCALLED | ElectionOpsAdmin |
| GET | /election-events/{id}/contests | List contests of the event, filterable by tabulation_status and call_status | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| GET | /contests/{id} | Read one contest including rollup fields and version (OCC read) | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| PATCH | /contests/{id} | Edit contest configuration (office_name, seats) before candidate lock (SETUP only) | ElectionOpsAdmin |
| POST | /contests/{id}/county-links | Link a county of the same event into the contest's geography (SETUP only) | ElectionOpsAdmin |
| GET | /contests/{id}/county-links | List county links of a contest | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| GET | /counties/{id}/county-links | List county links touching a county | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /contests/{id}/candidates | Add a candidate to a contest (SETUP only) | ElectionOpsAdmin |
| GET | /contests/{id}/candidates | List candidates of a contest | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /election-events/{id}/feed-sources | Register an electronic feed with its authorized states (SETUP only) | ElectionOpsAdmin |
| GET | /election-events/{id}/feed-sources | List feed sources of the event | ElectionOpsAdmin, CoveragePlanner, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /stringers | Register a stringer on the network roster; both reliability scores start at 100 | StringerCoordinator |
| GET | /stringers/{id} | Read one stringer including reliability_career and reliability_recent_form | StringerCoordinator, ElectionOpsAdmin |
| POST | /election-events/{id}/assignments | Deploy a stringer to a county office for a half-open window; omit stringer_id to auto-select | StringerCoordinator |
| GET | /election-events/{id}/assignments | List assignments of the event, filterable by status | StringerCoordinator, ElectionOpsAdmin |
| GET | /stringers/{id}/assignments | List assignments of one stringer | StringerCoordinator, ElectionOpsAdmin |
| GET | /counties/{id}/assignments | List deployments covering one county | StringerCoordinator, ElectionOpsAdmin |
| POST | /assignments/{id}/check-in | Stringer checks in at the county office (SCHEDULED to ACTIVE, self-service) | Stringer |
| POST | /assignments/{id}/status-actions | Coordinator lifecycle action: RELEASE, NO_SHOW, or REDEPLOY | StringerCoordinator |
| POST | /contests/{id}/vote-reports | Submit a tabulation entry from a stringer or feed; QC at intake; OCC on the contest version | Stringer, FeedOperator |
| GET | /contests/{id}/vote-reports | List vote reports of a contest, filterable by status and county_id | ElectionOpsAdmin, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| GET | /counties/{id}/vote-reports | List vote reports naming a county, filterable by status | ElectionOpsAdmin, StringerCoordinator, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| GET | /stringers/{id}/vote-reports | List vote reports authored by one stringer | StringerCoordinator, ElectionOpsAdmin, TabulationClerk |
| POST | /vote-reports/{id}/review-decisions | Tabulation desk review: ACCEPT, REJECT, or VOID | TabulationClerk |
| POST | /vote-reports/{id}/resubmit | Correct and resubmit a REJECTED report; QC re-runs | Stringer, FeedOperator |
| GET | /contests/{id}/tabulation | Computed tabulation board: totals, per-candidate votes, outstanding estimates, margin | ElectionOpsAdmin, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer, StringerCoordinator |
| POST | /contests/{id}/calls | Propose a winner call for the contest (TABULATION only; OCC; certainty not evaluated) | DecisionAnalyst |
| GET | /contests/{id}/calls | List race calls of a contest, filterable by status | ElectionOpsAdmin, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /calls/{id}/decisions | Desk-chief decision: PUBLISH or RETRACT a call | DecisionDeskChief |
| POST | /contests/{id}/recount-cases | File a recount case for a completed contest (margin at most 0.005, inclusive) | RecountOfficer |
| GET | /contests/{id}/recount-cases | List recount cases of a contest | ElectionOpsAdmin, TabulationClerk, DecisionAnalyst, DecisionDeskChief, RecountOfficer |
| POST | /recount-cases/{id}/decisions | Recount progression: ACTIVATE, DISMISS, or RESOLVE with an outcome | RecountOfficer |
| POST | /election-events/{id}/coverage-decisions | Propose coverage of a contest of the event | CoveragePlanner |
| GET | /election-events/{id}/coverage-decisions | List coverage decisions of the event, filterable by status | ElectionOpsAdmin, CoveragePlanner |
| GET | /contests/{id}/coverage-decisions | List coverage decisions for a contest | ElectionOpsAdmin, CoveragePlanner |
| POST | /coverage-decisions/{id}/review | Admin review: APPROVE or DECLINE from PROPOSED, FUND from APPROVED; budget-enforced | ElectionOpsAdmin |
| POST | /coverage-decisions/{id}/revise | Revise a DECLINED decision back to PROPOSED with updated hours or dates | CoveragePlanner |
| POST | /media-customers | Register a media customer with license tier and licensed states | ElectionOpsAdmin |
| GET | /media-customers/{id} | Read one media customer (admin, or the customer themself) | ElectionOpsAdmin, MediaCustomer |
| GET | /media-customers/{id}/deliveries | Customer's result feed, filterable by content_type and status; BASIC may not query CALL or CALL_CREDIT | ElectionOpsAdmin, MediaCustomer |
| GET | /contests/{id}/deliveries | Delivery audit view per contest | ElectionOpsAdmin, TabulationClerk |
| POST | /media-customers/{id}/invoices | Generate the monthly invoice for a period (admin, or the customer themself) | ElectionOpsAdmin, MediaCustomer |
| GET | /media-customers/{id}/invoices | List invoices of a customer | ElectionOpsAdmin, MediaCustomer |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_CONTEST_NOT_FOUND | 404 |
| ERR_COUNTY_NOT_FOUND | 404 |
| ERR_STRINGER_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_CALL_NOT_FOUND | 404 |
| ERR_RECOUNT_NOT_FOUND | 404 |
| ERR_DECISION_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_POSTURE_FORBIDS | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_CALL_ALREADY_PUBLISHED | 409 |
| ERR_RECOUNT_ACTIVE_BLOCKS_CALL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CERTAINTY_NOT_MET | 422 |
| ERR_CROSS_EVENT_REFERENCE | 422 |
| ERR_CANDIDATE_NOT_IN_CONTEST | 422 |
| ERR_COUNTY_NOT_IN_CONTEST | 422 |
| ERR_STRINGER_NOT_DEPLOYED | 422 |
| ERR_FEED_COVERAGE_MISSING | 422 |
| ERR_NO_ELIGIBLE_STRINGER | 422 |
| ERR_ASSIGNMENT_WINDOW_OVERLAP | 409 |
| ERR_OUTSIDE_ASSIGNMENT_WINDOW | 409 |
| ERR_PRECINCTS_EXCEED_EXPECTED | 422 |
| ERR_RECOUNT_MARGIN_EXCEEDED | 422 |
| ERR_COVERAGE_BUDGET_EXCEEDED | 422 |
| ERR_DUPLICATE_COUNTY | 409 |
| ERR_DUPLICATE_FEED | 409 |
| ERR_DUPLICATE_CANDIDATE | 409 |
| ERR_DUPLICATE_COUNTY_LINK | 409 |
| ERR_DUPLICATE_INVOICE | 409 |
| ERR_LICENSE_TIER_FORBIDS | 403 |
