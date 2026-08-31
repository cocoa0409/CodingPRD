# Antitrust Competition Compliance API — Product Requirements Document

## 1. Introduction

Corporate antitrust counsel operate under a permanent asymmetry: the conduct that creates cartel liability is ordinary commercial behaviour — a conversation at a trade show, a standards-body working group, a benchmarking exchange, a slide deck that speculates about what a rival will do with its list price — and the evidence of that conduct is created by the business, not by the legal department. A compliance programme that only publishes policy documents therefore learns about its own exposure years late, usually from a dawn raid. This document specifies the service that closes that gap: a single system of record in which market position is scored, trade-association participation is approved before it happens, every competitor contact is logged and priced, merger filings are tested against statutory thresholds, inspection readiness is drilled, document-creation hygiene is audited, and the decision to run to the enforcement agency for leniency is modelled as a queue position that can be won or lost.

The organising idea is that antitrust risk is **cumulative and fungible**. A single trade-show conversation is not a violation; twenty of them by a sales team in a concentrated market, against a backdrop of flagged meeting minutes and a document audit full of high-risk phrasing, is a pattern that a regulator will find. The service therefore keeps a running exposure ledger per business unit and derives from it a **posture** — a programme-wide gate that progressively withdraws the unit's freedom to enter new trade-association relationships and, at the extreme, suspends the relationships it already has. Posture is never set by hand. It is recomputed from the ledger, the unit's current risk band, and whether the unit is currently standing in the leniency queue, and it cascades downward through participations, delegate clearances and calendar bookings in a fixed order.

Two audiences meet in this API and the specification keeps them apart deliberately. The business side — unit leadership and individual employees — supplies facts: nominations, justifications, contact logs, training completions, meeting minutes. Counsel adjudicates: clearance, verdicts, escalations, risk scores, HSR determinations, leniency strategy. Where the two would collide, segregation of duties forbids the same counsel from both blessing a participation and later reviewing that participation's minutes, or from both flagging an attendance and closing its remediation. Everything the service does is deterministic and testable: every score has a pinned evaluation order, every threshold has a declared inclusivity, and every time-dependent rule reads a logical clock the operator controls rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

Every route in this specification is mounted under the `/compliance` prefix. Collections are flat peers under that prefix — ownership is never expressed by nesting one collection inside another's URL, but by identifier fields carried in request bodies.

### 2.1. User and Role-Based Access Control

Every request, without exception, must carry two headers: `X-User-ID` and `X-User-Role`. If either header is absent, or if `X-User-Role` carries a string that is not one of the four declared roles, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. This check runs before anything else — before body parsing, before existence lookups, before any state inspection.

The four roles are `ComplianceAdmin`, `AntitrustCounsel`, `BusinessLead`, and `Employee`, spelled exactly so.

A `ComplianceAdmin` is the programme administrator. Reference data is theirs: business units, employee records, training curricula and their assignments, trade associations, association meetings, and sites. They also record the enforcement agency's external decisions on leniency markers and disclosure packages, and they drive the logical clock. A `ComplianceAdmin` never adjudicates a compliance question.

An `AntitrustCounsel` is corporate antitrust counsel and adjudicates everything: association approval and prohibition, participation legal clearance, minutes review, competitor-contact review and clearance and escalation, market-position risk assessment, HSR analysis and filing, document audits, and leniency strategy.

A `BusinessLead` speaks for one business unit. An `Employee` is an individual in a sales, pricing, legal or other role.

Identity binds to `X-User-ID` differently per role, and this binding is what ownership checks compare against:

- When `X-User-Role` is `ComplianceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `AntitrustCounsel`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server does record it where a transition demands an accountable author — as `legal_cleared_by_user_id` on a participation, as `minutes_reviewed_by_user_id` on an attendance, as `review_opened_by_user_id` on a competitor contact, and as `analyzed_by_user_id` on an HSR analysis — and those recorded values are compared against a later actor's `X-User-ID` for segregation of duties, but they are never resolved as an entity identifier.
- When `X-User-Role` is `BusinessLead`, `X-User-ID` is the `id` of the acting business unit; ownership checks on any resource that references a business unit compare the resource's owning-unit field to `X-User-ID` — directly where the payload carries `business_unit_id`, and indirectly through a participation's owning unit or a transaction's owning unit.
- When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting employee record; ownership checks compare the resource's owning-employee field to `X-User-ID` — directly where the payload carries `employee_id`, and indirectly through a training assignment's employee, a participation's nominated delegate, or a contact's logging employee.

A syntactically valid role that is simply not listed among an endpoint's authorised roles yields `ERR_FORBIDDEN_ROLE` with HTTP 403. A properly authorised `BusinessLead` or `Employee` who reaches for a resource belonging to a different unit or a different person yields `ERR_NOT_RESOURCE_OWNER`, also HTTP 403. The two are distinct: the first says "your job cannot do this", the second says "this is not yours". All read endpoints are open to all four roles.

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

Every list endpoint accepts two optional query parameters. `limit` defaults to 10 when omitted, and must be an integer no smaller than 1 and no larger than 100. `offset` defaults to 0 when omitted, and must be an integer no smaller than 0; there is no upper bound on `offset`. A `limit` outside the permitted range, or a negative `offset`, or a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION` and HTTP 400.

List results are always ordered by `created_at` ascending. Where two rows share a `created_at` instant the ordering is stable with respect to insertion. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts the rows matching the filters before the window is applied, and `has_more` is true exactly when rows remain beyond the current window.

Filter query parameters are documented with the workflows they serve and are additive: supplying several narrows the result set to rows satisfying all of them. An unrecognised filter value that is not a declared member of the relevant enumeration is treated as a request-shape failure.

### 2.4. Record Identity, Timestamps and the Logical Clock

Every resource in this service carries four common properties. `id` is a server-minted UUID with no type prefix — clients never supply it. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation and never rewritten. `updated_at` is the same format and is refreshed on every mutation of the row. `version` is an integer that begins at 1 when the row is created and increments by exactly 1 on each mutation. All sixteen resource types — business units, employee profiles, training curricula, training assignments, trade associations, association participations, association meetings, meeting attendances, competitor contacts, transactions, HSR analyses, sites, readiness drills, document audits, leniency applications and risk assessments — carry all four.

The `version` counter is not decorative. Cascades that touch a second or third row increment that row's own `version` and refresh its own `updated_at`. Where a recomputation lands on the value the row already held — a posture recomputation that concludes the posture is unchanged, for example — no side effect fires and `version` is **not** incremented a second time. Recomputation is idempotent by design.

Time in this service is a logical clock, not wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and until an administrator moves it, every time-dependent rule — training expiry, the agenda lead time before a meeting, attendance confirmation after a meeting ends, the HSR waiting period, leniency marker validity, and drill window boundaries — evaluates against that fixed instant. An administrator moves the clock by supplying `to_iso8601`; the response body reports the resulting `current_utc`. Moving the clock never retro-fires cascades. Time-gated transitions are evaluated lazily, on the next request that reads or validates the affected row: a completed training assignment whose validity window has elapsed becomes expired the moment something looks at it, and a granted leniency marker whose validity window has elapsed with its disclosure still in draft expires the same way.

### 2.5. Numeric Precision and Rounding Discipline

Unless a rule says otherwise, every monetary and points-bearing figure is carried to 2 decimal places and rounded half up. Exposure points, assessed points, guideline scores, readiness scores and risk indexes all follow that rule. Penalty estimates and every transaction-sizing figure are carried in **integer cents** and never acquire a fractional part; where a division produces one, it is resolved by rounding half up to whole cents. Counsel review load is carried in whole integer minutes.

Where a calculation involves both a cap and a multiplier, or both a rounding step and a summation, the order in which those operations apply is pinned by the rule that defines the calculation and is never rearranged for convenience. Two of these orderings are the most common source of divergence and are called out explicitly where they live: the contact raw-score cap applies **before** the risk-band multiplier, and per-year penalty figures are rounded **before** they are summed.

Thresholds are stated with explicit inclusivity throughout. Where a rule says a value must be at least some figure, a value exactly equal to that figure satisfies it.

### 2.6. Optimistic Concurrency on Parent Records

Two write endpoints in this service replace a parent record's operative determination, and both require the client to prove it was looking at the current state of that parent when it decided to write.

A `POST /compliance/risk-assessments` request must carry `expected_business_unit_version` as a required, non-optional field whose value is the `version` the client last observed on the target business unit. A new assessment legitimately supersedes the unit's prior active assessment and rewrites the unit's `risk_band`, so an author working from a stale view of the unit would silently overwrite an assessment they never saw and would score the unit against exposure and incident counts that have since moved. If the supplied value does not equal the business unit's current `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP 412, and no assessment is created.

A `POST /compliance/hsr-analyses` request must carry `expected_transaction_version` as a required, non-optional field whose value is the `version` the client last observed on the target transaction. Each analysis supersedes the transaction's prior active analysis and re-derives the transaction's status, so an author holding a stale view would replace a determination they never read. A mismatch with the transaction's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412.

A `POST /compliance/business-units/{id}/exposure-adjustments` request likewise carries `expected_business_unit_version` and is rejected with `ERR_STALE_VERSION` and HTTP 412 when it does not match the unit's current `version`.

No other endpoint in this service accepts a version field, and no other endpoint may be rejected for a version mismatch.

### 2.7. The Validation Ladder

Requests are validated against a single, strictly ordered ladder. Rules are evaluated in ascending priority order, the **first** failing rule determines the response, later failures are never reported, and no side effect of any kind — not a cascade, not a counter increment, not a `version` bump — is applied when any rule fails. Implementers should read this ordering as load-bearing: a fixture that trips an early rung will never surface a later rung's error code.

1. **Authentication.** `X-User-Role` and `X-User-ID` are both present and `X-User-Role` is one of the four declared roles — otherwise `ERR_UNAUTHENTICATED`, HTTP 401. Applies to every endpoint.
2. **Role authorisation.** The acting role appears in the endpoint's authorised-role list — otherwise `ERR_FORBIDDEN_ROLE`, HTTP 403. Applies to every endpoint.
3. **Request shape.** Every required field is present, every enum-valued field carries a declared member, numeric values respect their declared ranges (`market_share_bps` from 0 through 10000, `competitor_overlap_pct` from 0 through 100, `gravity_pct` from 0 through 30, `score` from 0 through 100, `sample_size` strictly greater than 0, `affected_years` non-empty), and every datetime is well-formed ISO 8601 UTC — otherwise `ERR_INVALID_REQUEST`, HTTP 400. Applies to every write endpoint.
4. **Pagination shape.** `limit` is an integer from 1 through 100 and `offset` is an integer no smaller than 0 — otherwise `ERR_INVALID_PAGINATION`, HTTP 400. Applies to every list endpoint.
5. **Path existence.** Every resource named in the URL path exists, validated left to right — otherwise the not-found code for the entity that failed, HTTP 404. Applies to every endpoint carrying a path parameter.
6. **Body reference existence.** Every identifier supplied in the request body resolves to a live row, validated in the order the fields are listed for that endpoint — otherwise the not-found code for the entity that failed, HTTP 404. Applies to every write endpoint carrying reference fields.
7. **Ownership.** An identity-backed actor is operating on its own resource: a `BusinessLead`'s `X-User-ID` equals the target unit, whether supplied directly as `business_unit_id` or reached through the participation's or transaction's owning unit; an `Employee`'s `X-User-ID` equals the target person, whether supplied directly as `employee_id` or reached through the assignment's employee, the participation's nominated delegate, or the contact's logging employee — otherwise `ERR_NOT_RESOURCE_OWNER`, HTTP 403. Applies to every write endpoint acted on by a `BusinessLead` or an `Employee`.
8. **Optimistic concurrency.** The supplied `expected_business_unit_version` or `expected_transaction_version` equals the parent's current `version` — otherwise `ERR_STALE_VERSION`, HTTP 412. Applies to risk-assessment creation, HSR-analysis creation, and exposure adjustment.
9. **Segregation of duties.** The acting `X-User-ID` is not the user recorded as having performed the incompatible prior step — otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 409. Applies to minutes review and to remediation closure.
10. **Transition legality.** The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE`, HTTP 409. Applies to every transition endpoint, and covers every attempt from a terminal state and every repeat of an already-applied transition.
11. **Frozen posture.** The governing business unit's `posture` is not `FROZEN` — otherwise `ERR_BUSINESS_UNIT_FROZEN`, HTTP 409. Applies to eight writes: competitor-contact logging, participation nomination, participation submission, legal clearance, business justification, participation reinstatement, meeting-attendance booking, and transaction registration.
12. **Restricted posture.** The governing business unit's `posture` is not `RESTRICTED` — otherwise `ERR_BUSINESS_UNIT_RESTRICTED`, HTTP 409. Applies to participation nomination alone.
13. **Cross-entity state preconditions.** Attendance booking requires the participation to be `ACTIVE`, failing with `ERR_PARTICIPATION_NOT_ACTIVE`; HSR filing requires the transaction to be `ANALYZED` with an `ACTIVE` analysis whose `filing_required` is true, failing with `ERR_TRANSACTION_NOT_ANALYZED`; a marker request requires the unit's `ACTIVE` risk assessment to sit in `HIGH` or `SEVERE`, failing with `ERR_RISK_BAND_TOO_LOW`; a disclosure submission requires `marker_status` to be `MARKER_REQUESTED` or `MARKER_GRANTED`, failing with `ERR_MARKER_NOT_GRANTED`. All four carry HTTP 409.
14. **Training currency.** The acting or nominated employee's `training_status` is `CURRENT` — otherwise `ERR_TRAINING_NOT_CURRENT`, HTTP 422. This rule is **conditional**: it is skipped entirely when the employee's `role_category` is neither `SALES` nor `PRICING`. It guards four writes: competitor-contact logging, participation nomination, participation submission, and clearance grant.
15. **Delegate clearance.** The nominated delegate's `clearance_status` is `GRANTED` — otherwise `ERR_CLEARANCE_NOT_GRANTED`, HTTP 422. Applies to attendance booking.
16. **Association approval.** The trade association's `status` is `APPROVED` — otherwise `ERR_ASSOCIATION_NOT_APPROVED`, HTTP 422. Guards three writes: participation nomination, participation submission, and meeting scheduling.
17. **Curriculum targeting.** The employee's `role_category` is one of the curriculum's `target_role_categories` — otherwise `ERR_CURRICULUM_ROLE_MISMATCH`, HTTP 422. Applies to training assignment.
18. **Participation uniqueness.** No other participation with the same combination of owning unit, association and delegate is in a status other than `REJECTED` or `TERMINATED` — otherwise `ERR_DUPLICATE_PARTICIPATION`, HTTP 409. Applies to participation nomination.
19. **Marker uniqueness.** No other leniency application of the same business unit and the same `cartel_code` has a `marker_status` of `MARKER_REQUESTED`, `MARKER_GRANTED` or `PERFECTED` — otherwise `ERR_MARKER_ALREADY_HELD`, HTTP 409. Applies to the marker request.
20. **Interval well-formedness.** `scheduled_end` is strictly after `scheduled_start`, and `window_end` is strictly after `window_start` — otherwise `ERR_INVALID_INTERVAL`, HTTP 422. Applies to meeting scheduling and drill scheduling.
21. **Agenda deadline.** The meeting's `agenda_received` is true **and** the meeting begins at least 48 hours after the current logical clock — otherwise `ERR_AGENDA_DEADLINE_MISSED`, HTTP 422. Applies to attendance booking.
22. **Delegate occupancy.** The delegate's closed occupancy interval does not intersect any of their other occupying attendances — otherwise `ERR_ATTENDEE_WINDOW_CONFLICT`, HTTP 409. Applies to attendance booking.
23. **Site drill capacity.** Adding the candidate drill would not push concurrency above the site's `concurrent_drill_capacity` at any instant — otherwise `ERR_SITE_DRILL_CAPACITY_EXCEEDED`, HTTP 409. Applies to drill scheduling.
24. **Waiting period.** The current logical clock has reached the transaction's `waiting_period_end` — otherwise `ERR_WAITING_PERIOD_ACTIVE`, HTTP 409. Applies to HSR clearance.
25. **Review-minute budget.** The unit's `review_minutes_consumed` plus the review load this clearance would reserve is no greater than the unit's `review_minutes_budget` — otherwise `ERR_REVIEW_MINUTES_EXCEEDED`, HTTP 422. Applies to legal clearance.
26. **Exposure budget.** The unit's `exposure_points` plus the points this contact would be charged is no greater than the unit's `exposure_budget_points` — otherwise `ERR_EXPOSURE_BUDGET_EXCEEDED`, HTTP 422. Applies to competitor-contact logging.

The not-found codes referenced at rungs 5 and 6 are entity-specific: `ERR_BUSINESS_UNIT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_CURRICULUM_NOT_FOUND`, `ERR_TRAINING_ASSIGNMENT_NOT_FOUND`, `ERR_ASSOCIATION_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_ATTENDANCE_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_HSR_ANALYSIS_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_DRILL_NOT_FOUND`, `ERR_DOCUMENT_AUDIT_NOT_FOUND`, `ERR_LENIENCY_APPLICATION_NOT_FOUND`, and `ERR_RISK_ASSESSMENT_NOT_FOUND`. Each resolves to the entity whose identifier failed to resolve, whether that identifier arrived in the path or in the body — a `source_contact_id` that does not resolve is a missing contact, and a `participation_id` that does not resolve is a missing participation.

### 2.8. The Exposure Ledger and Business-Unit Posture

Each business unit carries a running antitrust exposure ledger in `exposure_points`. The ledger is not incremented ad hoc; it is **recomputed in full** at the end of every request that logs, clears or escalates a competitor contact, reviews meeting minutes, or records a manual exposure adjustment. Its value is the sum of three terms, rounded half up to 2 decimal places and then floored at 0.00 so it can never go negative:

1. The sum of `exposure_points_charged` over the unit's competitor contacts whose `status` is `LOGGED`, `UNDER_REVIEW`, `REMEDIATION_REQUIRED` or `ESCALATED`. Contacts in `CLEARED` are excluded, and because clearing a contact also zeroes its own charge, a cleared contact drops out of the sum from both directions.
2. The sum of `exposure_points_assessed` over the meeting attendances whose participation belongs to this unit and whose `status` is `MINUTES_REVIEWED` or `FLAGGED`. Attendances in `PLANNED`, `ATTENDED`, `MINUTES_SUBMITTED` or `CANCELLED` contribute nothing, because assessed points are only ever written by a minutes review.
3. The unit's `manual_exposure_adjustment_points`, which is itself the running sum of every `points_delta` the service has accepted on that unit. Because the adjustment total is kept as its own running sum rather than folded into the ledger, the identity closes exactly and no drift accumulates across recomputations.

From that ledger, the unit's `risk_band`, and the state of its leniency filings, the service derives `posture`, which takes one of `OPEN`, `RESTRICTED` or `FROZEN`. Posture is recomputed at the end of every request that changes the unit's `exposure_points`, changes its `risk_band`, or changes the `marker_status` of any of its leniency applications. The derivation has **strict precedence** — the first matching clause wins and the clauses are not re-evaluated after a match:

- The posture is `FROZEN` when `exposure_points` is at least 80.00, **or** when the unit has any leniency application whose `marker_status` is `MARKER_REQUESTED`, `MARKER_GRANTED` or `PERFECTED`. Applications in `MARKER_DENIED` or `MARKER_EXPIRED` do not force a freeze.
- Otherwise the posture is `RESTRICTED` when `exposure_points` is at least 40.00, **or** when `risk_band` is `HIGH` or `SEVERE`.
- Otherwise the posture is `OPEN`.

Both thresholds are inclusive at the lower edge: a ledger reading of exactly 40.00 is `RESTRICTED`, and exactly 80.00 is `FROZEN`. A unit that has never been assessed carries `risk_band` of `LOW`, `posture` of `OPEN`, `exposure_points` of 0 and `manual_exposure_adjustment_points` of 0 from the moment it is registered.

What posture *does* is a graduated withdrawal of freedom. `OPEN` gates nothing. `RESTRICTED` refuses new trade-association nominations for that unit with `ERR_BUSINESS_UNIT_RESTRICTED`, but deliberately still permits competitor-contact logging — self-reporting is never blocked, because a programme that punishes disclosure stops receiving it. `FROZEN` refuses all eight of the posture-gated writes listed at rung 11 of the validation ladder with `ERR_BUSINESS_UNIT_FROZEN`, and it also cascades.

The freeze cascade fires the moment posture *enters* `FROZEN` — whether from `OPEN` or from `RESTRICTED` — and runs in a fixed order. First, the unit's `posture` becomes `FROZEN`, its `updated_at` is refreshed and its `version` increments by 1. Then, in the first cascade hop, every participation of that unit whose status is `PARTIALLY_APPROVED` or `ACTIVE` moves to `SUSPENDED`, processed in `created_at` ascending order. Suspension does **not** release the participation's reserved review minutes — the reservation is held through the freeze. Then, in the second hop, each newly suspended participation cancels every one of its attendances that is still `PLANNED` and whose meeting begins strictly after the current logical clock, processed in meeting start ascending order and then `created_at` ascending order; each cancellation records the cascade origin as its `cancellation_reason` and releases the delegate's occupancy interval.

Thawing is deliberately asymmetric. When the ledger falls back below 80.00 and no marker is outstanding, posture recomputes to `RESTRICTED`; when it falls below 40.00, no marker is outstanding, and `risk_band` is neither `HIGH` nor `SEVERE`, it recomputes to `OPEN`. Neither thaw auto-reinstates a suspended participation. Reinstatement is an explicit act by counsel.

### 2.9. Segregation of Duties

Two pairs of decisions may never be made by the same counsel. First, the `AntitrustCounsel` whose `X-User-ID` was recorded as `legal_cleared_by_user_id` when a participation received legal clearance may not later review the minutes of any attendance belonging to that participation. Second, the `AntitrustCounsel` whose `X-User-ID` was recorded as `minutes_reviewed_by_user_id` when an attendance was flagged may not close that attendance's remediation. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 409, evaluated at rung 9 of the ladder — that is, after ownership and concurrency checks but before the transition's own legality is considered.

### 2.10. Occupancy and Capacity Conventions

The service contends two different scarce resources with two deliberately **opposite** adjacency conventions, and conflating them is the most common implementation error in this domain.

A delegate's calendar is contended as a **closed-closed** interval. An attendance's `occupied_start` is the meeting's `scheduled_start` moved earlier by a 60-minute counsel briefing buffer, and its `occupied_end` is the meeting's `scheduled_end` unchanged. Two attendances of the same delegate conflict when the candidate's occupied start is at or before the existing occupied end **and** the existing occupied start is at or before the candidate's occupied end. Touching endpoints *do* conflict: an existing interval ending at exactly some instant collides with a candidate whose interval begins at exactly that instant. The occupying rows are the attendances whose participation names the same delegate and whose status is `PLANNED`, `ATTENDED`, `MINUTES_SUBMITTED`, `MINUTES_REVIEWED` or `FLAGGED`; `CANCELLED` attendances never occupy. The contended resource is the delegate — not the meeting, not the association, not the business unit — and the capacity is exactly one delegate-instant.

A site's drill calendar is contended as a **half-open** interval `[window_start, window_end)` with an aggregate capacity. Adjacency does not conflict here: an existing drill ending at exactly some instant and a candidate beginning at exactly that instant may both exist. Occupying rows are the site's drills whose status is `SCHEDULED` or `IN_PROGRESS`; `COMPLETED` and `ABORTED` drills never occupy. Concurrency is evaluated by sweeping the candidate window's own boundary instants together with the start instant of every occupying drill that falls inside the candidate window; at each such instant, concurrency counts the candidate itself plus every occupying drill whose window has begun at or before that instant and has not yet ended. The drill is refused when the maximum concurrency across those instants exceeds the site's `concurrent_drill_capacity`, which is at minimum 1 and defaults to 1.

Both conventions work at minute resolution. The same pair of back-to-back windows is a conflict for a delegate and entirely legal for a site.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Programme: Units, People and Budgets

Everything begins with a business unit, registered by a `ComplianceAdmin` with the market-position facts that risk banding needs and the two budgets that bound the unit's behaviour. The registration payload carries a `name`, a `market_code` naming the relevant market used for banding, a `market_share_bps` expressing market share in basis points (from 0 through 10000, so a unit holding one third of its market registers as 3333), an `interaction_point_count` counting recurring structural interaction points with competitors such as joint ventures, standards bodies and shared distributors (which may be zero but never negative), and a `competitor_overlap_pct` giving the percentage of revenue in product lines where a direct competitor is also present.

Two optional budget fields complete the picture. `exposure_budget_points` caps the cumulative exposure the unit will tolerate before new competitor contacts are refused outright, and defaults to 100 when omitted; it must be strictly greater than zero. `review_minutes_budget` caps the counsel review minutes the unit may reserve across all its trade-association participations, and defaults to 480 — that is, eight hours of counsel attention per unit — and must likewise be strictly greater than zero. Both budgets are supplied by the administrator and never recomputed.

Alongside those inputs, a freshly registered unit exposes six derived fields that the service maintains on its behalf: `exposure_points` starting at 0, `manual_exposure_adjustment_points` starting at 0, `review_minutes_consumed` starting at 0, `risk_band` starting at `LOW`, `posture` starting at `OPEN`, and `document_violation_count` starting at 0. The consumed-minutes figure is the sum of `review_minutes_reserved` across the unit's participations whose status is `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` or `UNDER_REVIEW`. The violation figure is the sum of `violation_count` across the unit's completed document audits. Business units may be listed with `posture` and `risk_band` filters.

Counsel occasionally needs to move a unit's ledger for reasons the service cannot observe — findings carried over from an external investigation, a regulator's letter, a matter closed on terms. Recording such a movement takes a signed `points_delta`, a `reason` explaining it, and the `expected_business_unit_version` that proves the author was reading the current unit. The delta is added to `manual_exposure_adjustment_points`, the ledger and posture are recomputed, the unit's `version` increments by 1, and the freeze cascade may fire as a consequence — suspending live participations and cancelling their future planned attendances exactly as described for any other route into `FROZEN`. The adjusted unit itself is returned.

People are registered next, each against exactly one unit. An employee record carries the owning `business_unit_id`, a `full_name`, an `email`, and a `role_category` drawn from `SALES`, `PRICING`, `LEGAL` and `OTHER`. That category is doing double duty: it drives which curricula target the person, and it weights how expensively their competitor contacts price into the ledger. A new employee starts with `clearance_status` of `NONE` and `training_status` of `NONE`, and with a null `training_expires_at`. Employees may be listed filtered by their owning unit, their `role_category` and their `clearance_status`.

Trade-association speaking clearance is granted by counsel. A grant is legal from `NONE` and from `SUSPENDED`, moving `clearance_status` to `GRANTED`; the grant is refused unless the employee's training is current, though — as everywhere in this service — that training gate is skipped entirely for `LEGAL` and `OTHER` employees and applies only to `SALES` and `PRICING`. A revocation, which takes a `reason`, is legal from `NONE`, `GRANTED` and `SUSPENDED`, and drives `clearance_status` to the terminal `REVOKED`. Revocation deliberately does **not** cancel existing planned attendances: a revocation is a personnel record, and the delegate's calendar bookings stay on the books — and keep occupying their intervals — until the business lead cancels them explicitly. A grant attempted from `REVOKED` is an illegal transition.

### 3.2. Training Targeted at Sales and Pricing Roles

Antitrust training is only worth mandating where the conduct risk lives, so curricula are targeted rather than universal. A `ComplianceAdmin` defines a curriculum with a `code` that must be unique across all curricula, a human-readable `title`, a `target_role_categories` array naming a non-empty subset of `SALES`, `PRICING`, `LEGAL` and `OTHER`, a `duration_minutes` figure that must be strictly greater than zero, and a `validity_days` figure — also strictly greater than zero — stating how long a completion stays current. A final flag, `is_mandatory`, defaults to true and marks the curriculum as one whose current completion is a precondition for competitor-contact logging and for participation nomination.

Assigning a curriculum to a person creates an assignment carrying `employee_id`, `curriculum_id` and a `due_at` completion deadline, and the assignment opens in `ASSIGNED`. The assignment is refused with `ERR_CURRICULUM_ROLE_MISMATCH` when the employee's `role_category` is not among the curriculum's `target_role_categories` — a pricing curriculum cannot be dropped on a warehouse supervisor to inflate a completion statistic. Assignments may be listed filtered by `employee_id`, `curriculum_id` and `status`.

The employee themselves drives the assignment forward, and only for their own row. Starting moves `ASSIGNED → IN_PROGRESS` and stamps `started_at` with the current logical clock. Completing moves `IN_PROGRESS → COMPLETED`, stamps `completed_at` with the current logical clock, records the supplied `score` (an integer from 0 through 100), and computes `expires_at` as `completed_at` advanced by the curriculum's `validity_days` days. Both actions demand that the acting `X-User-ID` is the assignment's own employee. Counsel may instead waive an assignment that is still `ASSIGNED` or `IN_PROGRESS`, recording a `reason` into `waiver_reason` and driving the assignment to the terminal `WAIVED`. A waiver is an audit record, never a substitute for training: a `WAIVED` assignment contributes nothing to training currency.

Expiry is lazy. A `COMPLETED` assignment whose `expires_at` has been reached moves to the terminal `EXPIRED` at the start of the next request that reads or validates it, and the comparison is **strict** in the sense that an assignment is already expired at the instant the clock reads exactly its `expires_at` — currency requires the clock to be strictly earlier than the expiry instant.

An employee's `training_status` is derived, never set. The qualifying set is the employee's `COMPLETED` assignments whose curriculum is mandatory and whose `target_role_categories` contains the employee's own `role_category`; any qualifying row whose expiry instant has been reached is first moved to `EXPIRED` and thereby leaves the set. What remains is the current set. When the current set is non-empty the status is `CURRENT`, and `training_expires_at` is the latest `expires_at` among those current rows. When the current set is empty but the employee has some history of qualifying completions that have since expired, the status is `EXPIRED` and `training_expires_at` is null. When the employee has never completed a mandatory curriculum targeting their category at all, the status is `NONE`. Waived assignments never qualify, non-mandatory curricula never qualify, and a completed curriculum that does not target the employee's category never qualifies no matter how good the score.

Consider a `SALES` employee whose only mandatory completion lapsed last week. Their `training_status` reads `EXPIRED`, and until a fresh completion lands they cannot log a competitor contact, cannot be nominated to a trade association, cannot be pushed into the approval fork, and cannot be granted speaking clearance — all four rejected with `ERR_TRAINING_NOT_CURRENT`. A `LEGAL` colleague in the identical situation is unaffected, because the gate is skipped for their category entirely.

### 3.3. Scoring Market Position: Risk Assessment and Banding

A risk assessment is counsel's formal read of a unit's structural antitrust exposure, and it exists in two variants that answer two different questions from the same underlying row. Creating one takes the `business_unit_id`, the `variant` — either `BASELINE` or `INCIDENT_ADJUSTED` — and the `expected_business_unit_version` that guards against writing over an assessment the author never saw. The assessment is created in `ACTIVE`; the unit's prior `ACTIVE` assessment, if there is one, moves to the terminal `SUPERSEDED`; the unit's `risk_band` is rewritten to the new assessment's band; the unit's `version` increments by 1 and its posture is recomputed. Only one assessment per unit is ever `ACTIVE`. Assessments may be listed filtered by unit, `variant` and `status`.

The index is a weighted score of three structural components plus, under one variant only, an incident load. Each component is stored on the assessment row so the arithmetic is auditable after the fact.

The `share_component` is a tiered read of the unit's `market_share_bps`: 10 points when the share is below 1500 basis points, 25 points when it is at least 1500 and below 3000, 45 points when it is at least 3000 and below 5000, and 70 points once the share reaches 5000 basis points — that is, once the unit holds half its relevant market.

The `interaction_component` charges 3 points for each recurring structural interaction point the unit reported, but the component is capped: whichever is smaller of 30 and three times `interaction_point_count` is what the assessment carries. A unit with eleven interaction points and a unit with forty both contribute the capped 30.

The `overlap_component` weights the unit's `competitor_overlap_pct` at one fifth — the percentage multiplied by 0.20 — with the product rounded half up to 2 decimal places.

Those three components sum to the structural base, which is identical under both variants. What differs is the `incident_load`. Under `BASELINE` — the position-only view used for periodic programme reporting — the incident load is forced to zero, and the three incident counters `escalated_contact_count`, `flagged_attendance_count` and `document_violation_count` are stored on the assessment as zero without ever being consulted. Under `INCIDENT_ADJUSTED` — the view counsel uses to justify a leniency marker request — each counter is measured at assessment creation across the whole history of the unit, with no time window: `escalated_contact_count` counts the unit's competitor contacts whose status is `ESCALATED` (contacts in `CLEARED`, `LOGGED`, `UNDER_REVIEW` and `REMEDIATION_REQUIRED` are all excluded), `flagged_attendance_count` counts the meeting attendances in `FLAGGED` whose participation belongs to this unit, and `document_violation_count` sums `violation_count` across the unit's `COMPLETED` document audits, with `OPEN` audits excluded. The incident load is then 5 points for each escalated contact plus 3 points for each flagged attendance plus 2 points for each document violation, with the total capped at 25 — whichever is smaller of 25 and that weighted sum.

The `market_risk_index` is the structural base plus the incident load, rounded half up to 2 decimal places, and then held to a ceiling of 100.00. The `risk_band` follows from the index with lower edges inclusive and upper edges exclusive: `LOW` below 25, `MODERATE` from 25 up to but not including 50, `HIGH` from 50 up to but not including 75, and `SEVERE` at 75 and above. Because the two variants share a structural base but diverge on the incident load, the very same business unit row can carry one index and band under `BASELINE` and a materially higher index and band under `INCIDENT_ADJUSTED` — and since a unit's band feeds both its posture and the multiplier applied to newly logged contacts, which variant counsel chooses to run is itself a compliance decision.

### 3.4. Trade Associations and the Two-Branch Participation Fork

A trade association enters the register as a proposal. The administrator supplies its `name`, its `approval_tier` — one of `TIER_1_LOW`, `TIER_2_MEDIUM` or `TIER_3_HIGH`, expressing how much counsel scrutiny membership warrants — and a `competitor_density_pct` giving the percentage of the association's membership that competes with the participating unit. The association opens in `PROPOSED`.

Counsel then rules on it, supplying a `decision`. A decision of `APPROVED` moves `PROPOSED → APPROVED`. A decision of `PROHIBITED` moves either `PROPOSED → PROHIBITED` or `APPROVED → PROHIBITED`, and `PROHIBITED` is terminal. Prohibiting an association that had already been approved is the destructive case: every participation for that association whose status is `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` or `UNDER_REVIEW` is driven to `TERMINATED`, processed in `created_at` ascending order, and each of those terminations releases its reserved review minutes back to its own business unit's budget.

Nomination is the business lead's act. The payload carries `business_unit_id`, `association_id`, the `employee_id` of the nominated delegate, and a `purpose` stating the business reason for participating. A new participation opens in `DRAFT` with `legal_cleared` false, `business_justified` false, `review_load_minutes` of 0 and `review_minutes_reserved` of 0, and with `legal_cleared_by_user_id` and `business_justification` both null. Nomination is refused if the unit's posture is `FROZEN`, refused if it is merely `RESTRICTED`, refused if the association is not `APPROVED`, refused when a `SALES` or `PRICING` delegate's training is not current, and refused with `ERR_DUPLICATE_PARTICIPATION` when the unit already holds a participation with the same association and the same delegate in any status other than `REJECTED` or `TERMINATED`. Terminating a draft frees that combination for a fresh nomination. Participations may be listed filtered by unit, association, delegate and `status`.

Submitting a draft moves `DRAFT → APPROVAL_PENDING` and opens a **fork**: two approval branches that advance independently and are joined only when both have landed. The submission is itself gated — the association must still be `APPROVED`, the unit must not be `FROZEN`, and a `SALES` or `PRICING` delegate must still be current on training.

The **legal branch** is counsel's. It carries a `decision` and optional `notes`. A `decision` of `CLEARED` computes the counsel review load, freezes it onto `review_load_minutes`, sets `review_minutes_reserved` to that same figure, adds the reservation to the unit's `review_minutes_consumed`, increments the unit's `version` by 1, sets `legal_cleared` to true, and records the acting counsel's `X-User-ID` into `legal_cleared_by_user_id`. That last field is the segregation-of-duties key that will later bar this same counsel from reviewing the participation's minutes. A `decision` of `REJECTED` drives the participation to the terminal `REJECTED` — legally from `APPROVAL_PENDING`, and also from `PARTIALLY_APPROVED` provided the legal branch has not already landed — and reserves or releases nothing.

The **business branch** is the lead's. It carries a `justification`, records it into `business_justification`, and sets `business_justified` to true. This branch reserves **no** counsel minutes at all and leaves `review_load_minutes` sitting at 0 if it arrives first.

Whichever branch lands first moves `APPROVAL_PENDING → PARTIALLY_APPROVED` and applies only its own branch-specific effects. Whichever lands second moves `PARTIALLY_APPROVED → ACTIVE`, applying its own effects first and then joining: with `legal_cleared` and `business_justified` both true, the participation becomes `ACTIVE`. A branch that has already landed cannot land again. The join arrival is additionally gated on the unit not being `FROZEN`, and — for the legal branch specifically, whether it arrives first or second — on the review-minute budget having room.

That budget check is the fiscal spine of the participation workflow. Counsel review load is computed in three pinned steps. **Step one** takes a base of 30 minutes, adds the association's tier surcharge — 0 minutes for `TIER_1_LOW`, 20 minutes for `TIER_2_MEDIUM`, 45 minutes for `TIER_3_HIGH` — and then adds 5 minutes for each 25-percentage-point step of competitor density, where the number of steps is the association's `competitor_density_pct` divided by 25 and rounded **up** to a whole number. A density of exactly 0 contributes exactly 0 steps; any density above 0 and up to and including 25 contributes exactly 1 step; a density of exactly 25 contributes 1 step and not 2. **Step two** selects an escalation surcharge keyed on the step-one base **alone**: 0 minutes when the base is below 60, 15 minutes when the base is at least 60 and below 100, and 30 minutes when the base is at least 100. **Step three** adds the two together to give `review_load_minutes`.

The evaluation order in that computation is pinned and non-circular, and getting it wrong changes the number. The surcharge tier reads the step-one base, never the running total. Take a `TIER_3_HIGH` association at 100 percent competitor density: the base is 30 plus 45 plus four density steps of 5 minutes each, giving 95; the pinned order selects the surcharge for 95, which is 15, and the review load is 110 minutes. The alternative reading — re-selecting the surcharge from the 110-minute total and converging on 125 — is forbidden. Implementations must produce 110.

Only if the unit's `review_minutes_consumed` plus that computed load stays within `review_minutes_budget` does the clearance proceed; otherwise it is refused with `ERR_REVIEW_MINUTES_EXCEEDED` and nothing at all is reserved. Because a `TIER_3_HIGH` participation can eat 110 of a default 480-minute budget on its own, a unit can carry only a handful of high-scrutiny memberships at once.

Live participations move between three further states. A freeze suspends them, as described earlier, holding their reservation rather than releasing it. A flagged set of meeting minutes drives an `ACTIVE` participation to `UNDER_REVIEW`, also holding the reservation. Counsel reinstates from either: `SUSPENDED → ACTIVE` requires the unit no longer to be `FROZEN` and requires both `legal_cleared` and `business_justified` to be true, while `UNDER_REVIEW → ACTIVE` requires the unit no longer to be `FROZEN` and requires that no attendance of that participation is still sitting in `FLAGGED`. Both are revision cycles: a participation may go `ACTIVE → SUSPENDED → ACTIVE` or `ACTIVE → UNDER_REVIEW → ACTIVE` any number of times.

Termination, available to the business lead and to counsel alike and carrying a `reason`, is legal from `DRAFT`, `APPROVAL_PENDING`, `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` and `UNDER_REVIEW`, and lands on the terminal `TERMINATED`. Its compensating effect is to release the reservation: the unit's `review_minutes_consumed` is reduced by the participation's `review_minutes_reserved`, that field is reset to 0, and the unit's `version` increments by 1. Terminating from `DRAFT` releases nothing because nothing was ever reserved — `review_minutes_reserved` stays 0 and the unit's consumed figure is untouched — and terminating from `APPROVAL_PENDING` releases nothing when the legal branch has not landed, but does release, and does bump the unit's `version`, when it has. Terminating an `ACTIVE` participation additionally cancels every one of its attendances still in `PLANNED`, processed in meeting start ascending order and then `created_at` ascending order, with no clock condition — a termination cancels bookings whether or not their meetings are still in the future.

### 3.5. Meetings, Delegate Bookings and Minutes Review

Meetings are scheduled by the administrator against an association that must already be `APPROVED`. The payload carries `association_id`, a `meeting_type` drawn from `BOARD`, `COMMITTEE`, `STANDARDS` and `SOCIAL`, a `scheduled_start` and a `scheduled_end` — both ISO 8601 UTC, with the end strictly after the start — and an optional `agenda_received` flag recording whether counsel has the written agenda in hand, which defaults to false. Meetings may be listed filtered by `association_id` and `meeting_type`.

Booking a delegate into a meeting is the business lead's act and carries only `meeting_id` and `participation_id`; the delegate is whoever the participation nominated. It is the most heavily gated write in the service. The participation must be `ACTIVE`, or the booking fails with `ERR_PARTICIPATION_NOT_ACTIVE`. The delegate's `clearance_status` must be `GRANTED`, or it fails with `ERR_CLEARANCE_NOT_GRANTED`. The unit must not be `FROZEN`. The meeting's agenda must already have been received **and** the meeting must begin at least 48 hours — two full days — after the current logical clock, or it fails with `ERR_AGENDA_DEADLINE_MISSED`; counsel cannot brief a delegate on a standards-body agenda that arrives the night before. And the delegate's resulting closed occupancy interval must not intersect any of their other occupying attendances, or it fails with `ERR_ATTENDEE_WINDOW_CONFLICT`.

The successful booking opens in `PLANNED` and freezes its occupancy edges: `occupied_start` is the meeting's `scheduled_start` moved 60 minutes earlier to leave room for the counsel briefing, and `occupied_end` is the meeting's `scheduled_end` unchanged. Attendances may be listed filtered by meeting, participation and `status`.

The business lead may cancel a planned booking, supplying a `reason` that is recorded into `cancellation_reason`; only the lead of the participation's own unit may do so. Cancellation moves `PLANNED → CANCELLED`, which is terminal, and releases the delegate's interval — a cancelled attendance never participates in overlap detection again. The same terminal state is reached by cascade: from a participation entering `SUSPENDED`, from the delegate's clearance entering `SUSPENDED`, and from a participation being terminated. In the two suspension cascades only bookings whose meeting begins strictly after the current logical clock are cancelled, and the recorded `cancellation_reason` names the cascade origin; a termination cascade carries no clock condition.

After the meeting has actually ended — the logical clock must have reached the meeting's `scheduled_end` — the delegate confirms attendance, moving `PLANNED → ATTENDED`. They then submit minutes, moving `ATTENDED → MINUTES_SUBMITTED`, supplying a `summary` that lands in `minutes_summary` and a `topics_discussed` array of declared topic codes. Both acts require the acting `X-User-ID` to be the participation's own delegate.

Counsel then reviews, supplying a `verdict` of `CLEAN`, `CONCERN` or `VIOLATION` together with a `findings` array of counsel finding codes drawn from `PRICING_DISCUSSION`, `CAPACITY_DISCUSSION`, `CUSTOMER_ALLOCATION`, `BID_COORDINATION`, `MARKET_DATA_AGGREGATE` and `NONE`. The verdict lands in `minutes_verdict`, the findings in `minutes_findings`, and the reviewing counsel's `X-User-ID` in `minutes_reviewed_by_user_id`. The reviewer may not be the counsel who granted the participation's legal clearance.

Every review prices exposure, regardless of verdict. The finding points are summed — 8 for a pricing discussion, 6 for a capacity discussion, 10 for customer allocation, 10 for bid coordination, 1 for aggregated market data, and 0 for a finding of `NONE` — and that sum is capped at 15. The verdict points are then added **after** the cap, never before: 0 for `CLEAN`, 5 for `CONCERN`, 12 for `VIOLATION`. The result is multiplied by the business unit's band multiplier — 1.0 at `LOW`, 1.25 at `MODERATE`, 1.5 at `HIGH`, 2.0 at `SEVERE`, read at review time from the participation's unit, and `LOW` whenever the unit has no `ACTIVE` risk assessment — and the product is rounded half up to 2 decimal places into `exposure_points_assessed`. That figure is added into the unit's ledger, the unit's `version` increments by 1, and posture is recomputed.

A verdict of `CLEAN` or `CONCERN` moves `MINUTES_SUBMITTED → MINUTES_REVIEWED`, which is terminal, and there the file closes. A verdict of `VIOLATION` moves `MINUTES_SUBMITTED → FLAGGED` and sets off a four-hop cascade. The first hop is the exposure charge and posture recomputation just described, which on its own may push the unit into `FROZEN` and trigger the freeze cascade. The second hop drives the parent participation `ACTIVE → UNDER_REVIEW`, holding its reserved review minutes rather than releasing them. The third hop moves the delegate's `clearance_status` from `GRANTED` to `SUSPENDED`. The fourth hop cancels every attendance anywhere in the system whose participation names that same delegate, whose status is still `PLANNED`, and whose meeting begins strictly after the current logical clock, processed in meeting start ascending order and then `created_at` ascending order. A single violation verdict therefore takes the person off every future association calendar they were booked into, not merely the one where the violation was found.

Remediation closure is the way back. A **second** counsel — never the one recorded in `minutes_reviewed_by_user_id` — supplies `notes` and moves `FLAGGED → MINUTES_REVIEWED`. The `exposure_points_assessed` figure is deliberately retained: closing the file records that the matter was handled, but it does not refund the exposure the violation created. Only after no attendance of the participation remains in `FLAGGED` can counsel reinstate the participation itself, and the delegate's clearance must be separately re-granted.

### 3.6. The Competitor Contact Log and Pricing Communication Rules

Every contact with a competitor is logged by the employee who had it — self-reporting is the whole point, so this is the one write that a merely `RESTRICTED` unit may still perform. The payload names the owning `business_unit_id` and the reporting `employee_id`, both of which must match the acting identity's unit and person respectively, the `competitor_name`, a `contact_channel` drawn from `IN_PERSON_UNSTRUCTURED`, `TRADE_SHOW`, `PHONE`, `EMAIL` and `WRITTEN_FORMAL`, a `topic_tags` array drawn from `CAPACITY`, `BID`, `CUSTOMER_ALLOCATION`, `TERRITORY`, `STANDARDS` and `BENCHMARKING` which may be empty, a `pricing_topic` boolean recording whether price, discount, margin or list-price timing came up, and an `occurred_at` instant. The contact opens in `LOGGED`. Contacts may be listed filtered by unit, employee and `status`.

The log is priced immediately, once, at log time. The raw score starts at a base of 4 points. If `pricing_topic` is true, 6 further points are added — the single largest raw term, because pricing conversation is the conduct the programme most wants surfaced. Channel points follow: 3 for an unstructured in-person meeting, 2 for a trade show, 1 for a phone call, 1 for an email, and 0 for formal written correspondence. Topic-tag points are summed — 2 for `CAPACITY`, 2 for `BID`, 3 for `CUSTOMER_ALLOCATION`, 3 for `TERRITORY`, 0 for `STANDARDS`, and 1 for `BENCHMARKING` — and that sum alone is capped at 5, with an empty tag array contributing 0. Role points close the raw score: 2 for a `SALES` employee, 3 for `PRICING`, 0 for `LEGAL`, and 1 for `OTHER`.

The summed raw score is then capped at 20 — and this cap applies to the raw sum **before** the band multiplier, never after. Only then is the unit's band multiplier applied: 1.0 at `LOW`, 1.25 at `MODERATE`, 1.5 at `HIGH`, 2.0 at `SEVERE`. The multiplier in force at log time is frozen onto the contact as `band_multiplier_applied`, and the product, rounded half up to 2 decimal places, becomes the contact's `exposure_points_charged`. Freezing the multiplier means a later risk assessment never retro-prices a contact that was already on the books; a unit that deteriorates from `LOW` to `SEVERE` pays double on what it logs next, not on what it logged last quarter.

Before the contact is accepted, the service checks that the unit's `exposure_points` plus this contact's computed charge would stay within `exposure_budget_points`; if it would not, the log is refused with `ERR_EXPOSURE_BUDGET_EXCEEDED` and nothing is written. A `SALES` or `PRICING` employee whose training is not current is refused earlier, at the training gate. On success the contact is stored, the unit's ledger is recomputed, posture is recomputed, and the unit's `version` increments by 1.

Counsel works the log through a cycle. Opening a review moves `LOGGED → UNDER_REVIEW` and records the acting `X-User-ID` into `review_opened_by_user_id`. From `UNDER_REVIEW`, counsel may order remediation, supplying `instructions` that land in `remediation_instructions` and moving the contact to `REMEDIATION_REQUIRED`. The employee — and only the employee who logged it — answers with a `response` recorded into `remediation_response`, moving `REMEDIATION_REQUIRED → UNDER_REVIEW` again. That loop `UNDER_REVIEW → REMEDIATION_REQUIRED → UNDER_REVIEW` may repeat as many times as counsel needs.

Two terminal outcomes end the cycle, and they are financial opposites. Clearing, which takes `notes`, moves `UNDER_REVIEW → CLEARED` and compensates in full: the contact's `exposure_points_charged` is subtracted from the unit's ledger, the charge itself is reset to 0.00, the unit's `version` increments by 1, and posture is recomputed — which may thaw a frozen unit down to `RESTRICTED` or `OPEN`. Escalating, which takes a `reason`, moves `UNDER_REVIEW → ESCALATED` and does the reverse. The surcharge is the contact's current `exposure_points_charged` multiplied by one less than the escalation multiplier of 2.0 — in other words, an amount equal to the existing charge, rounded half up to 2 decimal places — added to `exposure_points_charged` so the charge is doubled, and added to the unit's ledger, with the unit's `version` incrementing by 1. Posture is then recomputed, and if that recomputation lands on `FROZEN`, the unit's `PARTIALLY_APPROVED` and `ACTIVE` participations move to `SUSPENDED`, and each newly suspended participation cancels its future `PLANNED` attendances. An escalation also permanently raises the unit's `escalated_contact_count` for any subsequently created incident-adjusted risk assessment.

### 3.7. Merger Control: HSR Threshold Analysis, Filing and Waiting Period

A business lead registers a prospective merger or acquisition against their own unit. The payload carries `business_unit_id`, the `target_name`, and five monetary figures all expressed in integer cents: `deal_value_cents` for the consideration under the signed agreement, `assumed_liabilities_cents` for the liabilities the acquirer takes on, `market_valuation_cents` for the independently determined market value of the voting securities or assets being acquired, `acquirer_total_assets_cents` for the acquiring person's total assets, and `target_total_assets_cents` for the acquired person's. It also carries the `signed_at` date of the definitive agreement and an optional `exemption_code` — one of `NONE`, `ORDINARY_COURSE`, `FOREIGN_ASSETS` and `INVESTMENT_ONLY` — which defaults to `NONE`. Registration is refused while the unit is `FROZEN`. The transaction opens in `DRAFT` at `version` 1 and may be listed filtered by acquiring unit and `status`.

Counsel then runs an HSR analysis, naming the `transaction_id`, choosing a `valuation_variant` of either `SIGNED_DEAL` or `MARKET_VALUE`, and supplying `expected_transaction_version`. The analysis records the acting counsel in `analyzed_by_user_id` and opens in `ACTIVE`; any prior `ACTIVE` analysis for the same transaction moves to the terminal `SUPERSEDED`, so exactly one analysis is ever operative. Analyses may be listed filtered by transaction, `status` and `valuation_variant`.

The size of the transaction depends on the variant. Under `SIGNED_DEAL` it is `deal_value_cents` plus `assumed_liabilities_cents`; under `MARKET_VALUE` it is `market_valuation_cents` plus `assumed_liabilities_cents`. Either way the result is stored in `size_of_transaction_cents` as integer cents with no rounding of any kind. Because the two variants differ only in the consideration term, the very same transaction row can land on opposite sides of the reporting threshold depending on which valuation counsel runs.

The `determination` then follows a ladder evaluated strictly top to bottom, with the first match winning:

1. If the `exemption_code` is anything other than `NONE`, the determination is `EXEMPT` and `filing_required` is false. An exempt transaction is never sized against any threshold.
2. Otherwise, if the size of the transaction is **strictly below** 120 million dollars — that is, strictly below 12,000,000,000 cents — the determination is `BELOW_THRESHOLD` and `filing_required` is false. A size exactly equal to that figure is *not* below threshold and falls through to the clauses beneath.
3. Otherwise, if the size of the transaction is at least 480 million dollars — 48,000,000,000 cents — the determination is `FILING_REQUIRED` and `filing_required` is true. At and above this upper figure the size-of-person test is **not** applied at all.
4. Otherwise the size sits in the band from the lower threshold up to but not including the upper figure, and the size-of-person test decides. Take the larger of `acquirer_total_assets_cents` and `target_total_assets_cents`, and the smaller of the two. If the larger is at least 480 million dollars (48,000,000,000 cents) **and** the smaller is at least 48 million dollars (4,800,000,000 cents), the determination is `FILING_REQUIRED` and `filing_required` is true. Otherwise the determination is `SIZE_OF_PERSON_NOT_MET` and `filing_required` is false.

Only the named transaction's own row feeds this analysis — no other transaction and no prior analysis contributes anything. The transaction's status is then re-derived from the outcome: a `filing_required` of true drives it to `ANALYZED`, and false drives it to `EXEMPT`, in each case incrementing the transaction's `version` by 1. That re-derivation is legal from `DRAFT`, from `ANALYZED` and from `EXEMPT`, so re-analysis under a different variant may cycle a transaction `EXEMPT → ANALYZED → EXEMPT` as often as counsel needs; the `ACTIVE` analysis is always the transaction's operative determination.

Filing is counsel's next act and is legal only from `ANALYZED`, and only when the transaction's `ACTIVE` analysis carries `filing_required` of true; anything else is refused with `ERR_TRANSACTION_NOT_ANALYZED`. Filing moves the transaction to `FILED`, stamps `filed_at` with the current logical clock, sets `waiting_period_end` to `filed_at` advanced by 30 days, and increments `version` by 1. Recording clearance moves `FILED → CLEARED`, which is terminal, and increments `version` by 1 — but only once the logical clock has reached `waiting_period_end`. An early attempt is refused with `ERR_WAITING_PERIOD_ACTIVE`; the comparison is inclusive, so the clock standing exactly at `waiting_period_end` is enough.

### 3.8. Inspection Readiness and Document-Creation Hygiene

Dawn-raid preparedness is exercised, not asserted. A site is registered with a `name`, an ISO 3166-1 alpha-2 `country_code`, and an optional `concurrent_drill_capacity` — the number of occupying drills allowed to overlap at any instant — which must be at least 1 and defaults to 1. A site also carries a derived `readiness_score`, which starts at 0 and is the mean `score` over that site's `COMPLETED` drills, rounded half up to 2 decimal places; a site with no completed drills reads 0.

Drills are scheduled by an administrator or by counsel with a `site_id`, a `drill_type` of `DAWN_RAID`, `DOCUMENT_HOLD` or `INTERVIEW`, and a half-open occupancy window given by `window_start` (inclusive) and `window_end` (exclusive), the end strictly after the start. The site's aggregate capacity check runs before the drill is created; exceeding it is refused with `ERR_SITE_DRILL_CAPACITY_EXCEEDED`. A scheduled drill opens in `SCHEDULED` and occupies its window from that moment. Drills may be listed filtered by site, `status` and `drill_type`.

Starting a drill moves `SCHEDULED → IN_PROGRESS` and is legal only once the logical clock has reached `window_start`; a running drill continues to occupy its window. Completing it moves `IN_PROGRESS → COMPLETED`, records the supplied `score` (an integer from 0 through 100) and `gaps_found` (a count that may be zero but never negative), stops the occupancy, and recomputes the site's `readiness_score` across all its completed drills. Aborting, which records a `reason` into `abort_reason`, is legal from both `SCHEDULED` and `IN_PROGRESS`, lands on the terminal `ABORTED`, and immediately frees the capacity the drill was holding. `COMPLETED` is likewise terminal.

Document-creation guidelines are audited separately. Counsel opens an audit against a unit with `business_unit_id`, a `sample_size` strictly greater than zero, and a `scope_note` describing what the sample covers; the audit opens in `OPEN`. Audits may be listed filtered by unit and `status`.

Recording findings closes the audit. The payload carries `violation_count` — the number of sampled documents that breached the creation guidelines, which may not exceed the audit's own `sample_size` — and `high_risk_phrase_count`, the number of high-risk phrasing occurrences found. The audit moves `OPEN → COMPLETED`, which is terminal, and its `guideline_score` is computed in two pinned steps. First the violation ratio is the violation count multiplied by 100 and divided by the sample size, **rounded half up to 2 decimal places at that point** rather than carried at full precision. Then the score is 100 minus that rounded ratio minus 2 points for each high-risk phrase occurrence, rounded half up to 2 decimal places and floored at 0.00 so a badly failing sample bottoms out rather than going negative. Closing the audit also recomputes the unit's `document_violation_count` as the sum of `violation_count` across all its completed audits and increments the unit's `version` by 1 — which is what makes those violations available to the next incident-adjusted risk assessment.

### 3.9. Leniency: The Marker Race and the Disclosure Package

Deciding to go to the enforcement agency is the highest-stakes call the programme makes, and the service models it as two **independent dimensions carried on one application row**. The marker dimension, held in `marker_status`, is the queue position in the race to the agency's door. The disclosure dimension, held in `disclosure_status`, is the substantive evidence package. Neither dimension's transitions consume or block the other's; they advance separately and meet exactly once, at perfection.

Counsel opens an application with the `business_unit_id`, a `cartel_code` that opaquely identifies the suspected cartel, and an `affected_years` array. That array must be non-empty and each of its entries is an object pairing a `year` with an `affected_commerce_cents` figure for that year. An optional `source_contact_id` back-references the contact-log entry that surfaced the conduct; it is left null when the application originates from a minutes review or an internal audit instead. The application opens with `marker_status` of `NONE` and `disclosure_status` of `DRAFT`, with `gravity_pct`, `priority_rank`, `estimated_penalty_cents`, `marker_requested_at`, `marker_granted_at` and `withdrawal_reason` all null. Applications may be listed filtered by unit, `cartel_code`, `source_contact_id`, `marker_status` and `disclosure_status`.

**The marker dimension.** Requesting a marker moves `marker_status` from `NONE` to `MARKER_REQUESTED` and stamps `marker_requested_at` with the current logical clock. It is permitted only when the unit has an `ACTIVE` risk assessment whose `risk_band` is `HIGH` or `SEVERE` — an absent assessment or a lower band is refused with `ERR_RISK_BAND_TOO_LOW` — and only when no other application of the same unit and the same `cartel_code` already stands in `MARKER_REQUESTED`, `MARKER_GRANTED` or `PERFECTED`, which is refused with `ERR_MARKER_ALREADY_HELD`. Filing the request forces the unit's posture to `FROZEN` and increments the unit's `version` by 1; from there the freeze cascade runs as always, suspending the unit's `PARTIALLY_APPROVED` and `ACTIVE` participations and cancelling their future planned attendances. That is deliberate: a unit that believes it is inside a cartel stops going to trade-association meetings that same day. The disclosure dimension is untouched by the request.

The administrator records the agency's answer as a `decision`. A `decision` of `GRANTED` moves `MARKER_REQUESTED → MARKER_GRANTED`, stamps `marker_granted_at` with the current logical clock, computes `priority_rank`, and recomputes `estimated_penalty_cents` if `gravity_pct` has already been recorded. A `decision` of `DENIED` moves `MARKER_REQUESTED → MARKER_DENIED`, which is terminal, nulls `priority_rank`, and recomputes the unit's posture — the marker no longer forces a freeze — incrementing the unit's `version` by 1.

A granted marker does not last forever. If the marker has been granted, the disclosure is still sitting in `DRAFT`, and the logical clock has reached `marker_granted_at` advanced by 30 days, the marker lapses to the terminal `MARKER_EXPIRED` at the start of the next request that reads or validates the application. Expiry nulls `priority_rank`, recomputes `estimated_penalty_cents` with a leniency reduction of zero percent, recomputes the unit's posture, and increments the unit's `version` by 1. A marker earns nothing without the evidence behind it.

**The disclosure dimension.** Counsel submits the evidence package with a `gravity_pct` — a number from 0 through 30 expressing the gravity percentage the agency will apply — moving `disclosure_status` from `DRAFT` to `SUBMITTED` and pricing `estimated_penalty_cents`. Submission requires `marker_status` to be `MARKER_REQUESTED` or `MARKER_GRANTED`, and is refused with `ERR_MARKER_NOT_GRANTED` otherwise: a disclosure may legitimately be filed while the marker is still merely requested, but never before a request and never after the marker has been denied or has expired. Submission leaves `marker_status` alone.

The administrator records the agency's `decision` on the package. `ACCEPTED` moves `SUBMITTED → ACCEPTED` and recomputes the penalty estimate; `REJECTED` moves `SUBMITTED → REJECTED`, which is terminal, recomputes the estimate, and deliberately leaves `marker_status` untouched — a rejected disclosure does not surrender the queue position.

**The join.** The two dimensions interact at exactly one point. The instant `disclosure_status` becomes `ACCEPTED`, if `marker_status` is `MARKER_GRANTED` it advances to `PERFECTED` in that same request, retaining both `priority_rank` and `estimated_penalty_cents`. `PERFECTED` is terminal on the marker dimension, and — like `MARKER_REQUESTED` and `MARKER_GRANTED` — it continues to hold the unit `FROZEN`.

**Withdrawal.** Counsel may withdraw from `DRAFT` or from `SUBMITTED`, supplying a `reason` that lands in `withdrawal_reason` and moving `disclosure_status` to the terminal `WITHDRAWN`. Withdrawal is the one act that crosses the dimensions in the other direction: a `marker_status` of `MARKER_REQUESTED` or `MARKER_GRANTED` is set to `MARKER_DENIED` in the same request, `priority_rank` is nulled, the unit's posture is recomputed and its `version` increments by 1. Withdrawing surrenders the queue position.

**Ranking the queue.** An application's `priority_rank` is its 1-based position among the candidates for its `cartel_code`. The candidate set is every application — **across all business units**, because the race is a race across the whole cartel and not within one company — whose `cartel_code` matches and whose `marker_status` is `MARKER_GRANTED` or `PERFECTED`. Candidates are ordered by `marker_granted_at` ascending, and where two grants share the same logical-clock instant, by `created_at` ascending. An application that is not itself a candidate has a null `priority_rank`. The rank is computed when the marker is granted and again whenever the penalty estimate is recomputed. When a rank holder drops out — denied, expired, withdrawn — it simply leaves the queue; the applications behind it keep the ranks they already have and are **not** renumbered.

**Pricing the exposure.** The penalty estimate is built in five pinned steps, all in integer cents. **Step one** rounds each affected year on its own, in `year` ascending order: that year's `affected_commerce_cents` multiplied by `gravity_pct` and divided by 100, rounded half up to whole cents. **Step two** sums those already-rounded per-year figures into the base penalty. The order of these first two steps is pinned and is not interchangeable: rounding each year first and then summing is required, while summing the affected commerce across years first and rounding the single product once is forbidden and yields a different figure whenever the per-year products carry fractional cents. As a worked contrast, affected commerce of 1,000,000,010 cents, 2,000,000,030 cents and 3,000,000,050 cents at a gravity of 15 percent gives per-year figures of 150,000,002, 300,000,005 and 450,000,008 cents, summing to 900,000,015 cents under the required order — against 900,000,014 cents under the forbidden one. **Step three** applies a duration uplift: one tenth is added for each affected year beyond the first, so the multiplier is 1 plus 0.10 multiplied by one less than the number of entries in `affected_years`, held to a ceiling of 2.00 — which is reached at eleven affected years and never exceeded. **Step four** reads the leniency reduction off the queue position: 100 percent for rank 1, 50 percent for rank 2, 30 percent for rank 3, and 0 percent for any rank beyond 3 or for a null rank. First through the door pays nothing; fourth through the door pays everything. **Step five** performs the single final rounding: the base penalty multiplied by the duration multiplier, multiplied by the complement of the reduction percentage — that is, by 100 minus the reduction, divided by 100 — rounded half up to whole cents into `estimated_penalty_cents`. Only this application's own `affected_years` and `gravity_pct` feed the calculation; other applications enter solely through the rank.

## 4. Endpoint Definitions

Every route below is mounted under the `/compliance` prefix. Endpoints that bring a brand-new resource into existence answer with HTTP 201 and return the created resource in `data`; every other successful call — state transitions, adjustments, reads and lists — answers with HTTP 200 and returns the affected or requested resource. Request and response payloads are not repeated here: the fields each call accepts, the effects it has, and the conditions under which it is refused are specified in the narratives of Sections 2 and 3, and this table exists only to bind those narratives to their HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/compliance/business-units` | Register a business unit with its market position inputs and its exposure / review budgets | ComplianceAdmin |
| GET | `/compliance/business-units/{id}` | Read a business unit including its derived exposure ledger, risk band and posture | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/business-units` | List business units with pagination and posture/risk filters | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/business-units/{id}/exposure-adjustments` | Counsel-recorded manual movement of the unit's exposure ledger (findings carried over from an external investigation, a regulator letter, or a clos... | AntitrustCounsel |
| POST | `/compliance/employees` | Register an employee against a business unit with their role category | ComplianceAdmin |
| GET | `/compliance/employees/{id}` | Read an employee including derived training_status and training_expires_at | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/employees` | List employees, filterable by owning business unit, role category and clearance status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/employees/{id}/clearance-grants` | Grant (or reinstate) trade-association speaking clearance | AntitrustCounsel |
| POST | `/compliance/employees/{id}/clearance-revocations` | Revoke trade-association speaking clearance permanently | AntitrustCounsel |
| POST | `/compliance/training-curricula` | Define a training curriculum and the role categories it targets | ComplianceAdmin |
| GET | `/compliance/training-curricula/{id}` | Read a curriculum | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/training-assignments` | Assign a curriculum to an employee | ComplianceAdmin |
| GET | `/compliance/training-assignments/{id}` | Read a training assignment | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/training-assignments` | List training assignments, filterable by employee, curriculum and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/training-assignments/{id}/start` | Employee starts their assigned training | Employee |
| POST | `/compliance/training-assignments/{id}/completion` | Employee completes their assigned training with an assessment score | Employee |
| POST | `/compliance/training-assignments/{id}/waiver` | Counsel waives an outstanding training assignment (audit record only — never satisfies the training gate) | AntitrustCounsel |
| POST | `/compliance/trade-associations` | Propose a trade association with its scrutiny tier and competitor density | ComplianceAdmin |
| GET | `/compliance/trade-associations/{id}` | Read a trade association | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/trade-associations/{id}/approval` | Counsel approves or prohibits a trade association | AntitrustCounsel |
| POST | `/compliance/participations` | Business lead nominates a delegate for participation in an approved trade association | BusinessLead |
| GET | `/compliance/participations/{id}` | Read a participation including its reserved counsel review minutes | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/participations` | List participations, filterable by unit, association, delegate and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/participations/{id}/submission` | Submit a draft participation into the two-branch approval fork | BusinessLead |
| POST | `/compliance/participations/{id}/legal-clearance` | LEGAL BRANCH — counsel clears or rejects the participation; clearing reserves the counsel review load against the unit's budget | AntitrustCounsel |
| POST | `/compliance/participations/{id}/business-justification` | BUSINESS BRANCH — business lead records the commercial justification; reserves no counsel minutes | BusinessLead |
| POST | `/compliance/participations/{id}/reinstatement` | Counsel reinstates a suspended or under-review participation | AntitrustCounsel |
| POST | `/compliance/participations/{id}/termination` | Terminate a participation and release its reserved counsel review minutes | BusinessLead, AntitrustCounsel |
| POST | `/compliance/association-meetings` | Schedule a trade-association meeting | ComplianceAdmin |
| GET | `/compliance/association-meetings/{id}` | Read a meeting | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/association-meetings` | List meetings, filterable by association | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/meeting-attendances` | Book the participation's delegate into a meeting; runs the closed-interval delegate occupancy check | BusinessLead |
| GET | `/compliance/meeting-attendances/{id}` | Read an attendance including its minutes review outcome | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/meeting-attendances` | List attendances, filterable by meeting, participation and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/meeting-attendances/{id}/cancellation` | Business lead cancels a planned attendance, releasing the delegate's occupancy interval | BusinessLead |
| POST | `/compliance/meeting-attendances/{id}/attendance-confirmation` | Delegate confirms they attended (only after the meeting has ended on the logical clock) | Employee |
| POST | `/compliance/meeting-attendances/{id}/minutes` | Delegate submits the meeting minutes for counsel review | Employee |
| POST | `/compliance/meeting-attendances/{id}/minutes-review` | Counsel reviews submitted minutes; a VIOLATION verdict flags the attendance and drives the participation into review | AntitrustCounsel |
| POST | `/compliance/meeting-attendances/{id}/remediation-closure` | A second counsel closes the remediation on a flagged attendance | AntitrustCounsel |
| POST | `/compliance/competitor-contacts` | Employee logs a contact with a competitor; prices the contact into the unit's exposure ledger | Employee |
| GET | `/compliance/competitor-contacts/{id}` | Read a contact-log entry | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/competitor-contacts` | List contact-log entries, filterable by unit, employee and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/competitor-contacts/{id}/review-opening` | Counsel opens a review of a logged contact | AntitrustCounsel |
| POST | `/compliance/competitor-contacts/{id}/remediation-order` | Counsel orders remediation, sending the contact back to the employee | AntitrustCounsel |
| POST | `/compliance/competitor-contacts/{id}/remediation-response` | Employee answers the remediation order, returning the contact to review (closes the revision cycle) | Employee |
| POST | `/compliance/competitor-contacts/{id}/clearance` | Counsel clears the contact and refunds its exposure charge | AntitrustCounsel |
| POST | `/compliance/competitor-contacts/{id}/escalation` | Counsel escalates the contact, doubling its exposure charge and potentially freezing the unit | AntitrustCounsel |
| POST | `/compliance/transactions` | Business lead registers a merger/acquisition for HSR threshold analysis | BusinessLead |
| GET | `/compliance/transactions/{id}` | Read a transaction including its filing status and waiting-period end | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/transactions` | List transactions, filterable by acquiring unit and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/transactions/{id}/filing` | Counsel files the HSR notification, starting the waiting period | AntitrustCounsel |
| POST | `/compliance/transactions/{id}/clearance` | Counsel records expiry of the HSR waiting period | AntitrustCounsel |
| POST | `/compliance/hsr-analyses` | Run an HSR size-of-transaction analysis under one valuation variant; supersedes the transaction's prior ACTIVE analysis (OCC on the transaction's v... | AntitrustCounsel |
| GET | `/compliance/hsr-analyses/{id}` | Read an HSR analysis | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/hsr-analyses` | List HSR analyses, filterable by transaction and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/sites` | Register a site that can host dawn-raid readiness drills | ComplianceAdmin |
| GET | `/compliance/sites/{id}` | Read a site including its mean readiness score | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/readiness-drills` | Schedule a dawn-raid / inspection readiness drill in a half-open window; runs the site aggregate-capacity check | ComplianceAdmin, AntitrustCounsel |
| GET | `/compliance/readiness-drills/{id}` | Read a readiness drill | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/readiness-drills` | List readiness drills, filterable by site and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/readiness-drills/{id}/start` | Begin a scheduled drill (only once the clock has reached window_start) | ComplianceAdmin, AntitrustCounsel |
| POST | `/compliance/readiness-drills/{id}/completion` | Complete a drill with its readiness score and gap count | ComplianceAdmin, AntitrustCounsel |
| POST | `/compliance/readiness-drills/{id}/abort` | Abort a scheduled or running drill, freeing the site capacity it held | ComplianceAdmin, AntitrustCounsel |
| POST | `/compliance/document-audits` | Open a document-creation-guideline audit over a sample of a unit's documents | AntitrustCounsel |
| GET | `/compliance/document-audits/{id}` | Read a document audit including its guideline score | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/document-audits` | List document audits, filterable by unit and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/document-audits/{id}/findings` | Record audit findings and close the audit | AntitrustCounsel |
| POST | `/compliance/leniency-applications` | Open a leniency application file for a suspected cartel, optionally linked to the contact-log entry that surfaced it | AntitrustCounsel |
| GET | `/compliance/leniency-applications/{id}` | Read a leniency application including priority_rank and estimated_penalty_cents | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/leniency-applications` | List leniency applications, filterable by unit, cartel code, source contact and marker status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/leniency-applications/{id}/marker-request` | MARKER DIMENSION — request a leniency marker; freezes the unit while the marker is outstanding | AntitrustCounsel |
| POST | `/compliance/leniency-applications/{id}/marker-decisions` | MARKER DIMENSION — record the agency's decision on the marker request | ComplianceAdmin |
| POST | `/compliance/leniency-applications/{id}/disclosure-submission` | DISCLOSURE DIMENSION — submit the evidence package with its gravity percentage; prices the penalty estimate | AntitrustCounsel |
| POST | `/compliance/leniency-applications/{id}/disclosure-decision` | DISCLOSURE DIMENSION — record the agency's decision on the disclosure package | ComplianceAdmin |
| POST | `/compliance/leniency-applications/{id}/withdrawal` | Withdraw the application, surrendering any outstanding marker | AntitrustCounsel |
| POST | `/compliance/risk-assessments` | Run a market-position risk assessment under one variant; supersedes the unit's prior ACTIVE assessment (OCC on the unit's version) | AntitrustCounsel |
| GET | `/compliance/risk-assessments/{id}` | Read a risk assessment including every component of the index | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| GET | `/compliance/risk-assessments` | List risk assessments, filterable by unit, variant and status | ComplianceAdmin, AntitrustCounsel, BusinessLead, Employee |
| POST | `/compliance/_clock/set_current_utc` | Set the server's logical clock to the supplied instant (see Section 2.4) | ComplianceAdmin |

## 5. Error Code Catalogue

Every error response carries the standard error envelope of Section 2.2, with the identifier below in `error_id` and a human-readable `message`. The conditions that trigger each code are specified in the narratives of Sections 2 and 3 — in particular the ordered validation ladder of Section 2.7, which determines which code surfaces when more than one condition is unsatisfied.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_BUSINESS_UNIT_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 |
| `ERR_CURRICULUM_NOT_FOUND` | 404 |
| `ERR_TRAINING_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 |
| `ERR_PARTICIPATION_NOT_FOUND` | 404 |
| `ERR_MEETING_NOT_FOUND` | 404 |
| `ERR_ATTENDANCE_NOT_FOUND` | 404 |
| `ERR_CONTACT_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_HSR_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_DRILL_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_AUDIT_NOT_FOUND` | 404 |
| `ERR_LENIENCY_APPLICATION_NOT_FOUND` | 404 |
| `ERR_RISK_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BUSINESS_UNIT_FROZEN` | 409 |
| `ERR_BUSINESS_UNIT_RESTRICTED` | 409 |
| `ERR_PARTICIPATION_NOT_ACTIVE` | 409 |
| `ERR_TRANSACTION_NOT_ANALYZED` | 409 |
| `ERR_MARKER_NOT_GRANTED` | 409 |
| `ERR_MARKER_ALREADY_HELD` | 409 |
| `ERR_WAITING_PERIOD_ACTIVE` | 409 |
| `ERR_RISK_BAND_TOO_LOW` | 422 |
| `ERR_TRAINING_NOT_CURRENT` | 422 |
| `ERR_CLEARANCE_NOT_GRANTED` | 422 |
| `ERR_ASSOCIATION_NOT_APPROVED` | 422 |
| `ERR_CURRICULUM_ROLE_MISMATCH` | 422 |
| `ERR_DUPLICATE_PARTICIPATION` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_AGENDA_DEADLINE_MISSED` | 422 |
| `ERR_ATTENDEE_WINDOW_CONFLICT` | 409 |
| `ERR_SITE_DRILL_CAPACITY_EXCEEDED` | 409 |
| `ERR_REVIEW_MINUTES_EXCEEDED` | 422 |
| `ERR_EXPOSURE_BUDGET_EXCEEDED` | 422 |

