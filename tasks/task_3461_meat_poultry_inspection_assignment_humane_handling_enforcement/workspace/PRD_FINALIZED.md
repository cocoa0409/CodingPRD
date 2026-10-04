# Meat & Poultry Inspection API — Product Requirements Document

## 1. Introduction

Federal meat and poultry inspection rests on a simple statutory promise: no slaughter establishment operates without an inspector present, and no product reaches commerce bearing a mark of inspection that has not been earned. Delivering on that promise across thousands of establishments generates an operational problem of considerable depth — inspectors must be qualified for the species on the line, scheduled against planned shift windows without gaps, and supported by an enforcement apparatus that escalates from a written noncompliance record all the way to suspension or withdrawal of the grant of inspection when an establishment fails to correct its course.

This document specifies the Meat & Poultry Inspection API, the system of record for that apparatus. It governs the grant of inspection lifecycle (application, adequacy review of facility, sanitation, and hazard plans, and the grant or denial decision), the planning and verification of continuous inspection coverage on slaughter and processing shifts, the issuance and escalation of noncompliance records, the enforcement ladder from notice through suspension to withdrawal, humane handling observation with immediate suspension authority for egregious events, pathogen sampling programs that categorize establishments by their results, pre-market label claim approval, recall coordination with class-driven effectiveness verification, and a supervisory appeals process with strict segregation of duties. All API resources described here are mounted under the `/inspection` URL prefix, with the single exception of the platform's logical-clock endpoint described in §2.4.

The system is built around two ideas an implementer should hold onto throughout. First, every enforcement-relevant fact about an establishment is derived, not declared: risk scores, compliance scores, pathogen categories, and open-record counts are computed from the underlying records under precisely pinned formulas, so two readers of the same data always agree. Second, enforcement is cascading but reversible where the statute allows: a suspension propagates to shift windows and label applications in the same request that causes it, and lifting a suspension unwinds exactly the effects that are meant to unwind — no more, no less.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, the logical clock, the establishment's dual status dimensions, common resource fields, the fixed validation pipeline, optimistic concurrency control, numeric precision, derived scoring, and the cascading-consistency principle.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose declared role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same error also reports a failed ownership check wherever a workflow pins `X-User-ID` to a specific resource's identifier.

The system recognizes exactly seven roles. `EstablishmentManager` acts for a single establishment: filing grant and label applications, planning shift windows, responding to noncompliance records, and filing appeals. `Inspector` is the field force: issuing noncompliance records, reporting humane handling events, collecting pathogen samples and recording their results, verifying shift coverage, and confirming their own assignments. `SupervisoryReviewer` decides appeals and confirms or dismisses humane handling events. `DistrictManager` runs the district office: grant application review and decisions, the enforcement action lifecycle, and recall class determination. `LabelOfficer` reviews and decides label applications. `RecallCoordinator` opens recalls, records effectiveness checks, and closes recalls. `ProgramAdministrator` is agency operations: registering establishments and inspectors, deactivating inspectors, building shift coverage, cancelling assignments, and driving the logical clock.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `EstablishmentManager`, `X-User-ID` is the `id` of the acting Establishment; ownership checks on any resource that references an establishment compare the resource's establishment foreign-key field to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting Inspector, and inspector-ownership checks (for example, confirming one's own assignment, or matching the issuing inspector on a record) compare the relevant inspector foreign key to `X-User-ID`. When `X-User-Role` is `SupervisoryReviewer`, `X-User-ID` is likewise the `id` of an Inspector entity — the reviewer is a senior inspector acting in a supervisory capacity — and segregation-of-duties checks compare it against the inspector who issued or reported the item under review. When `X-User-Role` is `DistrictManager`, `LabelOfficer`, `RecallCoordinator`, or `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by_reviewer_id` on an appeal decision) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order; in particular, the enforcement-action listing of an establishment is returned in `created_at` ascending order so that indexed access into the list is deterministic. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All temporal rules in this system — trailing windows, observation-time ceilings, abatement periods — evaluate against a single logical clock maintained by the platform, never against wall-clock time. Before any call to the clock endpoint, the logical clock reads exactly `2026-09-01T00:00:00Z`; there is no wall-clock fallback at startup or at any later point.

A `ProgramAdministrator` advances the clock through the platform endpoint `POST /_clock/set_current_utc`. This endpoint sits outside the `/inspection` prefix — its path is exactly `/_clock/set_current_utc`. Its request body carries a single field, `to_iso8601`, an ISO 8601 UTC timestamp; on success (HTTP 200) the logical clock is set to that instant and the response reports the new value as `current_utc`. Only the `ProgramAdministrator` role may invoke it.

Wherever a workflow below says a timestamp "must not be after the logical clock," or that a count is taken "within the trailing N days," the comparison instant is this logical clock. An `observed_at`, `collected_at`, or `checked_at` that lies after the logical clock is rejected with `ERR_FUTURE_OBSERVATION` (HTTP 422).

### 2.5. Two Parallel Status Dimensions on Every Establishment

An Establishment carries two independent status dimensions on one row. The grant dimension, `grant_status`, moves through `UNGRANTED`, `GRANTED`, and `WITHDRAWN`; the inspection dimension, `inspection_status`, moves through `INACTIVE`, `ACTIVE`, and `SUSPENDED`. A newly registered establishment begins at `UNGRANTED` × `INACTIVE`. Granting inspection moves the pair to `GRANTED` × `ACTIVE` in a single request. Suspension and lifting move only the inspection dimension (`ACTIVE` ↔ `SUSPENDED`); the grant dimension is untouched. Withdrawal of the grant is terminal: `grant_status` becomes `WITHDRAWN`, `inspection_status` becomes `INACTIVE`, and both dimensions freeze — any subsequent operational write against a withdrawn establishment is rejected with `ERR_ESTABLISHMENT_WITHDRAWN` (HTTP 409).

Many operations are gated on these dimensions. Operations that require an active grant — planning a shift window, logging a pathogen sample, approving a label application, activating a suspension — are rejected with `ERR_ESTABLISHMENT_NOT_GRANTED` (HTTP 409) when `grant_status` is not `GRANTED`. Operations barred during a suspension — shift planning, assignment creation, label approval, label resubmission — are rejected with `ERR_ESTABLISHMENT_SUSPENDED` (HTTP 409) while `inspection_status` is `SUSPENDED`.

### 2.6. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC timestamp with three fractional digits; `updated_at` follows the same format and refreshes on every mutation. The `version` is an integer that starts at 1 when the resource is created and increments by 1 on every mutation of that resource — including mutations caused by system cascades, so a client watching a parent's `version` sees every derived change.

One resource is deliberately thinner. A recall effectiveness check is an append-only event record: it carries `id` and `created_at` only, with no `updated_at` and no `version`, and it is never modified after creation.

### 2.7. The Validation Pipeline and Nested Resource Retrieval

Every request is evaluated against a fixed, ordered validation pipeline. When several checks could fail, the earliest tier's error is the one reported.

1. **User context.** `X-User-ID` and `X-User-Role` are present and the role is one of the seven declared roles — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission.** The declared role is permitted on the endpoint, and any endpoint-level ownership pinning of `X-User-ID` holds — otherwise `ERR_FORBIDDEN` (HTTP 403).
3. **Existence.** Resource identifiers in the path are validated left to right, and body-supplied foreign-key references are then checked — a missing Establishment yields `ERR_ESTABLISHMENT_NOT_FOUND`, and correspondingly `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_SHIFT_WINDOW_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`, `ERR_NONCOMPLIANCE_RECORD_NOT_FOUND`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND`, `ERR_HUMANE_EVENT_NOT_FOUND`, `ERR_PATHOGEN_SAMPLE_NOT_FOUND`, `ERR_LABEL_APPLICATION_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND` (all HTTP 404). On a nested path such as a shift window's assignments collection, a non-existent window id is reported before the request body is examined.
4. **Optimistic concurrency.** On the two endpoints declared in §2.8, the client-supplied expected version must match the parent resource's current `version` — otherwise the declared stale-version error (HTTP 412). This tier is evaluated after existence and before all business rules.
5. **State legality.** The target entity is in a state from which the requested transition is defined, including terminal-state lockdown and double-transition attempts — otherwise `ERR_INVALID_STATE` (HTTP 409). This tier also carries the establishment gates `ERR_ESTABLISHMENT_NOT_GRANTED`, `ERR_ESTABLISHMENT_SUSPENDED`, and `ERR_ESTABLISHMENT_WITHDRAWN`, and the inspector gate `ERR_INSPECTOR_INACTIVE` (HTTP 409) when an inspector-gated operation names an inspector whose `employment_status` is not `ACTIVE`.
6. **Inspector qualification.** For assignment creation, the inspector's `species_qualifications` must cover every member of the shift establishment's `species_classes` — otherwise `ERR_INSPECTOR_NOT_QUALIFIED` (HTTP 422). A deactivated inspector surfaces earlier, at tier 5, as `ERR_INSPECTOR_INACTIVE`.
7. **Temporal and interval rules.** Observation timestamps at or before the logical clock, well-formed half-open intervals inside their shift window, no same-line overlapping coverage, and the cross-establishment travel buffer — violations surface as `ERR_FUTURE_OBSERVATION` (HTTP 422), `ERR_INVALID_REQUEST` (HTTP 400) for malformed intervals, `ERR_ASSIGNMENT_OVERLAP` (HTTP 409), or `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 409).
8. **Aggregate and eligibility gates.** Enforcement basis eligibility, label documentation minimums, and recall close criteria — violations surface as `ERR_ESCALATION_THRESHOLD_NOT_MET` (HTTP 409), `ERR_WITHDRAWAL_CONDITIONS_NOT_MET` (HTTP 409), `ERR_INSUFFICIENT_DOCUMENTATION` (HTTP 422), or `ERR_EFFECTIVENESS_CRITERIA_NOT_MET` (HTTP 409).
9. **Cross-entity referential consistency.** A noncompliance record's optional shift link must belong to the same establishment, a humane event's species must be one the establishment handles, and a pathogen sample's establishment must hold a grant — violations surface as `ERR_SHIFT_WINDOW_MISMATCH` (HTTP 422), `ERR_SPECIES_NOT_SUPPORTED` (HTTP 422), or `ERR_ESTABLISHMENT_NOT_GRANTED` (HTTP 409).
10. **Segregation of duties.** A `SupervisoryReviewer` must not decide an appeal, or confirm or dismiss a humane event, that they themselves issued or reported — otherwise `ERR_SOD_REVIEWER_IS_ISSUER` (HTTP 403). This tier is evaluated after the state checks, so a segregation-violating decision attempted on an appeal that is no longer `FILED` reports the state error first.

Field-shape failures anywhere — a missing required field, a type mismatch, an enum member outside its declared set, an empty `species_classes` array, a `quantity_lbs` that is not greater than 0, an interval whose end is not strictly after its start or that falls outside its window, `grounds` shorter than 10 characters, `abatement_evidence` shorter than 20 characters, or a duplicate `badge_number` — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Optimistic Concurrency Control

Two write endpoints are protected by optimistic concurrency control, and each declares its own expected-version field and stale-version error.

Creating an enforcement action against an establishment requires the request body to carry `expected_establishment_version`, holding the client's last observed `version` of that establishment. If the establishment's version has advanced since — for example because a categorization cascade or a grant decision mutated it in between — the creation is rejected with `ERR_STALE_ESTABLISHMENT_VERSION` (HTTP 412), and the client must re-read the establishment and re-base the proposal.

Adding a shift assignment to a shift window requires the request body to carry `expected_shift_window_version`, holding the client's last observed `version` of that window. Because every assignment creation itself increments the window's `version` by 1, a client stacking several assignments must re-read the window between creations; a mismatch is rejected with `ERR_STALE_SHIFT_WINDOW_VERSION` (HTTP 412).

Both fields are non-optional on their endpoints. Endpoints not listed here do not take a version field.

### 2.9. Numeric Precision and Rounding

Coverage gaps are integer minutes. Risk scores and the enforcement priority score are integer points. The recall effectiveness ratio is rounded half-up to exactly 2 decimal places and compared against its class threshold as that rounded value. Each family's compliance penalty is rounded half-up to exactly 1 decimal place before the penalties are summed — the pinned nested-rounding order is detailed in §2.10, and the final subtraction from 100 is exact at the 0.1 scale and is never rounded again. Pathogen positive-rates are compared as exact rational numbers (positive count over resulted count) with no rounding before comparison; boundary equalities resolve exactly as §3.6 states. All numeric values are represented in responses as standard JSON numbers, and timestamps as ISO 8601 UTC strings with three fractional digits.

### 2.10. Derived Establishment Scores

Every read of an Establishment reports a set of computed fields, each derived from the underlying records at read time under a pinned formula.

`open_nr_count` is the number of the establishment's noncompliance records whose `status` is one of `OPEN`, `RESPONSE_SUBMITTED`, `ESCALATED`, or `APPEALED`. `suspension_count` is the lifetime number of the establishment's enforcement actions of type `SUSPENSION` that have reached `IN_EFFECT`.

`compliance_score` is a weighted per-family score. For each regulation family F among `SANITATION`, `HACCP`, and `HUMANE`, count the establishment's records in family F whose status is one of the four open statuses above; multiply that count by 10 and divide by 3, rounding the result half-up to 1 decimal place to obtain the family penalty. The score is 100 minus the sum of the three rounded family penalties. The rounding order is pinned: round each family penalty to 0.1 first, then subtract the sum of the rounded penalties from 100; the result is exact at the 0.1 scale and is not rounded again. The non-conformant alternative — summing the raw thirds and rounding once — is forbidden: with one `OPEN` record in each of the three families the pinned order yields 100 − (3.3 + 3.3 + 3.3) = 90.1, while the alternative yields 90.0. The score is read against a passing benchmark of 80.0.

`enforcement_priority_score` orders the district's enforcement queue. Its evaluation order is pinned to remove the circularity between score and tier. First, the base is computed from the establishment's current fields: 10 points per open noncompliance record (`open_nr_count`) plus 25 points per lifetime effective suspension (`suspension_count`). Second, the tier is derived from the base alone: a base of at least 100 is `HIGH` with a bonus of 15; a base of at least 50 but below 100 is `MEDIUM` with a bonus of 10; a base below 50 is `LOW` with a bonus of 5. Third, the score is the base plus the bonus. The tier must not be derived from the post-bonus score.

`rolling_risk_score` is the establishment's current operational risk: the sum, over its noncompliance records in the four open statuses whose `issued_at` lies within the trailing 90 days of the logical clock, of a family weight times a recency factor. Family weights are 2 for `SANITATION`, 3 for `HACCP`, 5 for `HUMANE`, 1 for `LABELING`, and 1 for `OTHER`. The recency factor depends on the record's age in days from `issued_at` to the logical clock: 3 when the age is at most 30 days, 2 when the age is 31 to 60 days, and 1 when the age is 61 to 90 days; a record older than 90 days contributes 0. `lifetime_risk_score` is the unwindowed companion used for trend auditing: the sum of the family weight alone over all of the establishment's records whose status is not `VACATED`, with no recency factor and no window. For identical record sets the lifetime value is always greater than or equal to the rolling value.

### 2.11. Cascading Consistency

Enforcement in this domain is hierarchical: one decision on a parent resource propagates to every dependent resource whose legality depends on it, in the same request. A grant decision activates the establishment; a suspension blocks its planned shift windows and holds its in-review label applications; a withdrawal blocks the windows and rejects the label applications outright; lifting an enforcement action restores exactly the label applications its activation held; deactivating an inspector cancels their scheduled assignments. Each cascade mutates every resource it touches, refreshing that resource's `updated_at` and incrementing its `version` per §2.6 — so the establishment's `version` advances on every grant, suspension, withdrawal, and lift that touches it, and a shift window's `version` advances on every assignment created against it. The complete inventory of cascades appears with the workflows that trigger them in §3.

## 3. Business Logic & Workflows

### 3.1. Establishment Registration and the Grant of Inspection

A `ProgramAdministrator` registers each establishment by supplying its `name`, the `species_classes` it handles — a non-empty array drawn from `CATTLE`, `SWINE`, `POULTRY`, and `SHEEP` (an empty array is rejected with `ERR_INVALID_REQUEST`) — and the `slaughter_capable` flag, which records whether the establishment performs slaughter and is therefore subject to the continuous-presence verification regime of §3.2. The new establishment begins life at `grant_status` `UNGRANTED` and `inspection_status` `INACTIVE`, at `version` 1.

Before an establishment may operate, it must win a grant of inspection. The `EstablishmentManager` files an application carrying the applicant's `establishment_id` and three document references: `facility_doc_ref` for facility adequacy, `sanitation_plan_ref` for the sanitation standard-operating plan, and `haccp_plan_ref` for the hazard analysis plan. Filing is an ownership-pinned operation: the caller's `X-User-ID` must equal the application's `establishment_id`, otherwise the request is rejected with `ERR_FORBIDDEN`. A fresh application lands in `SUBMITTED` with all three findings — `facility_finding`, `sanitation_finding`, and `haccp_finding` — at `PENDING`, a `revision_count` of 0, and no `decided_at`.

Review is a `DistrictManager` workflow. Beginning review moves the application from `SUBMITTED` to `UNDER_REVIEW`; invoking it in any other status is rejected with `ERR_INVALID_STATE`. While under review, the district manager records adequacy findings one dimension at a time: each call names a `dimension` — one of `FACILITY`, `SANITATION`, or `HACCP` — and a `finding` of `ADEQUATE` or `DEFICIENT`, and sets exactly the corresponding one of the three finding fields. This is a self-loop on `UNDER_REVIEW`: the application's `status` does not change, each call is idempotent in itself, and a later call may overwrite a prior finding on the same dimension.

The decision call takes a `decision` of `GRANT` or `DENY`. Both require the application to be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`, reported before any findings check, since state legality outranks business rules in the §2.7 pipeline). A grant additionally requires all three findings to be `ADEQUATE`; if any finding is still `PENDING` or has been recorded `DEFICIENT`, the grant is rejected with `ERR_GRANT_DECISION_BLOCKED` (HTTP 409). A successful grant stamps `decided_at` with the logical clock, moves the application to `GRANTED`, and — in the same request — moves the establishment's `grant_status` to `GRANTED` and its `inspection_status` to `ACTIVE`, incrementing the establishment's `version` by 1. A denial stamps `decided_at` and moves the application to `DENIED`.

Denial is not the end of the road. The `EstablishmentManager` may resubmit a `DENIED` application with refreshed `facility_doc_ref`, `sanitation_plan_ref`, and `haccp_plan_ref` values; the same ownership pinning applies (`X-User-ID` must equal the application's `establishment_id`, else `ERR_FORBIDDEN`), and resubmission from any status other than `DENIED` is rejected with `ERR_INVALID_STATE`. Resubmission returns the application to `SUBMITTED`, increments `revision_count` by 1, resets all three findings to `PENDING`, and replaces the document references with the payload's. Alternatively, the establishment may withdraw an application that is `SUBMITTED` or `UNDER_REVIEW`; withdrawal moves it to the terminal `WITHDRAWN` status and is likewise ownership-pinned. An application in `GRANTED`, `DENIED`, or `WITHDRAWN` cannot be withdrawn — the attempt is rejected with `ERR_INVALID_STATE`.

### 3.2. Inspector Staffing and Continuous Shift Coverage

The agency's inspection presence is delivered by inspectors, onboarded by a `ProgramAdministrator` with a `full_name`, a `badge_number`, and their `species_qualifications` — an array drawn from the same four-member species enum as establishments. Badge numbers are unique across the agency: onboarding with a `badge_number` already in use is rejected with `ERR_INVALID_REQUEST`. A new inspector's `employment_status` is `ACTIVE`. Deactivation, also a `ProgramAdministrator` operation, moves an `ACTIVE` inspector to `INACTIVE` (calling it on an already-inactive inspector is rejected with `ERR_INVALID_STATE`) and, in the same request, cancels every one of that inspector's assignments still in `SCHEDULED` status, moving each to `CANCELLED`.

Coverage is planned against shift windows. An `EstablishmentManager` plans a window for their own establishment (`X-User-ID` must equal the payload's `establishment_id`, else `ERR_FORBIDDEN`) by supplying `start_utc` and `end_utc` — the window is the half-open interval from `start_utc` inclusive to `end_utc` exclusive, and `end_utc` must be strictly after `start_utc` — a `shift_type` of `SLAUGHTER` or `PROCESSING`, and a `planned_line_count`, the number of slaughter or processing lines requiring coverage, which must be at least 1. Planning requires the establishment to hold a grant (otherwise `ERR_ESTABLISHMENT_NOT_GRANTED`), to be free of suspension (otherwise `ERR_ESTABLISHMENT_SUSPENDED`), and not to be withdrawn (otherwise `ERR_ESTABLISHMENT_WITHDRAWN`). A new window is `PLANNED`, and both of its gap fields, `provisional_gap_minutes` and `final_gap_minutes`, remain null until the first coverage verification.

A `ProgramAdministrator` then builds coverage by creating assignments against the window. Each assignment names an `inspector_id`, a `line_index` — the 1-based line number, which must lie between 1 and the window's `planned_line_count` inclusive — and a coverage interval whose `start_utc` must lie within the window's half-open interval and whose `end_utc` must be strictly after the assignment's own `start_utc` and no later than the window's `end_utc`; a malformed interval is rejected with `ERR_INVALID_REQUEST`. Because the window's `version` increments by 1 on every assignment creation, the request must also carry `expected_shift_window_version` per §2.8, and a stale value is rejected with `ERR_STALE_SHIFT_WINDOW_VERSION` (HTTP 412). At creation the assignment's `establishment_id` is denormalized from its shift window, and its `status` begins at `SCHEDULED`.

Assignment creation is the most heavily gated write in the system, and the §2.7 pipeline orders the gates: optimistic concurrency first, then state, then qualification, then temporal rules. The named inspector must be `ACTIVE` (a deactivated inspector is rejected with `ERR_INSPECTOR_INACTIVE`, HTTP 409), and the establishment must not be `SUSPENDED` (`ERR_ESTABLISHMENT_SUSPENDED`). The inspector's `species_qualifications` must cover every member of the shift establishment's `species_classes`; a single uncovered species class yields `ERR_INSPECTOR_NOT_QUALIFIED` (HTTP 422). On the same window and the same `line_index`, the new interval must not overlap any existing non-`CANCELLED` assignment's interval — intervals are half-open, so one assignment ending exactly when another begins is continuous, legal coverage — and a violation is rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409). Assignments on different lines of the same window may overlap freely. Finally, an inspector may not be scheduled at two different establishments within 30 minutes of one another: if the named inspector holds a non-`CANCELLED` assignment at a different establishment whose interval falls within 30 minutes of the requested interval, the creation is rejected with `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 409). Same-establishment assignments are exempt from the travel buffer. The window's own `status` is not among these gates: assignment creation never inspects it, so a window in any status — `PLANNED`, `COVERAGE_GAP_FLAGGED`, `VERIFIED_COVERED`, or `BLOCKED` — accepts new assignments whenever all of the operation's other specified checks pass.

The assigned inspector confirms their own presence: confirmation moves an assignment from `SCHEDULED` to `CONFIRMED`, requires `X-User-ID` to equal the assignment's `inspector_id` (otherwise `ERR_FORBIDDEN`), and is rejected with `ERR_INVALID_STATE` from any other status. A `ProgramAdministrator` may cancel a `SCHEDULED` assignment, moving it to `CANCELLED`; `CONFIRMED` and `CANCELLED` are terminal.

Verification closes the loop. An `Inspector` verifies coverage on a window in `PLANNED` or `COVERAGE_GAP_FLAGGED` status (otherwise `ERR_INVALID_STATE`), which recomputes both gap fields and stores them. The gap algorithm runs per line: for each line number from 1 to `planned_line_count`, collect the window's non-`CANCELLED` assignments on that line, merge their half-open intervals, and measure the minutes of the window's own interval left uncovered; adjacent intervals, where one assignment's `end_utc` equals the next's `start_utc`, leave zero uncovered minutes between them. The window's gap is the sum of uncovered minutes across all lines. Two variants are computed from the same rows: the provisional variant counts both `SCHEDULED` and `CONFIRMED` assignments and is stored as `provisional_gap_minutes`, while the final variant counts `CONFIRMED` assignments only and is stored as `final_gap_minutes` — for the same assignment rows the final gap is always greater than or equal to the provisional gap. The final gap drives the transition: a final gap of exactly 0 moves the window to `VERIFIED_COVERED`, and a final gap greater than 0 moves it to `COVERAGE_GAP_FLAGGED`. When a `SLAUGHTER` window is flagged, the system additionally issues a noncompliance record in the same request: `regulation_family` `OTHER`, `description` "inspection presence gap", `observed_at` at the logical clock, issued by the verifying inspector, in `OPEN` status. A flagged window can be re-verified after corrective scheduling and will move to `VERIFIED_COVERED` once the final gap reaches 0. Windows in `VERIFIED_COVERED` or `BLOCKED` are terminal and cannot be re-verified.

### 3.3. Noncompliance Records and the Escalation Ladder

When an inspector observes a regulatory failure, they issue a noncompliance record against the establishment. The issuance payload carries the cited `establishment_id`, the `issued_by_inspector_id` — which must equal the caller's `X-User-ID`, otherwise `ERR_FORBIDDEN` — an optional `shift_window_id` linking the record to the shift during which the noncompliance was observed, the `regulation_family` (one of `SANITATION`, `HACCP`, `HUMANE`, `LABELING`, or `OTHER`), a free-text `description`, and the `observed_at` timestamp, which must not be after the logical clock (otherwise `ERR_FUTURE_OBSERVATION`). When `shift_window_id` is supplied, the referenced window must belong to the same establishment as the record; a cross-establishment link is rejected with `ERR_SHIFT_WINDOW_MISMATCH` (HTTP 422). The record is born `OPEN`, with `issued_at` stamped from the logical clock.

The establishment answers through its `EstablishmentManager`: responding moves an `OPEN` record to `RESPONSE_SUBMITTED` and stores the supplied `response_text`. Responding is ownership-pinned — `X-User-ID` must equal the record's `establishment_id`, else `ERR_FORBIDDEN` — and is defined only from `OPEN`, so a response to an already-answered record is rejected with `ERR_INVALID_STATE`.

An `Inspector` then judges the corrective action through verification, supplying an `outcome` of `VERIFY` or `ESCALATE`. Verification is defined from either `OPEN` or `RESPONSE_SUBMITTED` (otherwise `ERR_INVALID_STATE`): `VERIFY` moves the record to the terminal `VERIFIED` status, while `ESCALATE` moves it to `ESCALATED`.

Escalation is where records become enforcement. At the moment a record enters `ESCALATED` — whether directly from `OPEN`, from `RESPONSE_SUBMITTED`, or through an appeal affirmance per §3.9 — the system counts the establishment's qualifying records in the same `regulation_family`: those with status `OPEN`, `RESPONSE_SUBMITTED`, or `ESCALATED` (records in `APPEALED` or `VACATED` never qualify), whose `issued_at` lies within the trailing 90 days of the logical clock inclusive of the boundary day, including the record that just escalated, now counted in its `ESCALATED` state. If that count reaches 3 — exactly at threshold fires — the system automatically creates an enforcement action against the establishment: `action_type` `SUSPENSION`, `basis` `NR_LINKAGE`, `regulation_family` set to the escalating record's family, `status` `PROPOSED`, and `auto_created` true. This automatic proposal still requires district-manager activation before it bites; see §3.4.

A record in `OPEN`, `RESPONSE_SUBMITTED`, or `ESCALATED` may also be appealed (§3.9), which moves it to `APPEALED`. The terminal outcomes of a record are `VERIFIED` and `VACATED`; a vacated record is excluded from `open_nr_count`, from escalation counts, and from both risk scores.

### 3.4. Enforcement Actions: Proposal, Activation, and Abatement

Enforcement actions are the district office's instrument. A `DistrictManager` proposes one against an establishment by naming an `action_type` — `NOTICE_OF_INTENDED_ENFORCEMENT`, `WITHHOLD_MARKS`, `SUSPENSION`, or `WITHDRAWAL` — and a `basis` of `NR_LINKAGE`, `EGREGIOUS_HUMANE`, `CATEGORY_3_PATHOGEN`, or `ADMINISTRATIVE`. When the basis is `NR_LINKAGE`, a `regulation_family` must also be supplied, naming the family whose qualifying-record count is evaluated; omitting it is rejected with `ERR_INVALID_REQUEST`. The proposal must carry `expected_establishment_version` per §2.8 — a mismatch is rejected with `ERR_STALE_ESTABLISHMENT_VERSION` (HTTP 412) — and its creation increments the establishment's `version` by 1. A manually proposed action is born `PROPOSED` with `auto_created` false and no `effective_at`.

Eligibility is not taken on faith: it is validated when the action is created and re-evaluated when it is activated, so a proposal whose factual basis has evaporated by activation time is refused then too. The eligibility rules per action type:

- A `NOTICE_OF_INTENDED_ENFORCEMENT` is always eligible.
- A `WITHHOLD_MARKS` is eligible when the establishment has at least 1 qualifying noncompliance record — status `OPEN`, `RESPONSE_SUBMITTED`, or `ESCALATED`, issued within the trailing 90 days — for the given `regulation_family`, or a `CONFIRMED` `EGREGIOUS` humane handling event, or a current `pathogen_category` of `CAT_3`, or when the basis is `ADMINISTRATIVE`.
- A `SUSPENSION` requires one of three bases: `NR_LINKAGE` with a qualifying-record count for the family of at least 3 within the trailing 90 days (otherwise `ERR_ESCALATION_THRESHOLD_NOT_MET`, HTTP 409); `EGREGIOUS_HUMANE` backed by a `CONFIRMED` `EGREGIOUS` humane event; or `CATEGORY_3_PATHOGEN` backed by a current `pathogen_category` of `CAT_3`. `ADMINISTRATIVE` is never an eligible basis for suspension.
- A `WITHDRAWAL` requires that the establishment has an `IN_EFFECT` suspension whose `effective_at` is at least 30 days before the logical clock, or that at least 2 of its suspension actions with status `IN_EFFECT` or `LIFTED` were created within the trailing 365 days. When neither condition holds, activation (or creation) is rejected with `ERR_WITHDRAWAL_CONDITIONS_NOT_MET` (HTTP 409).

Activation moves a `PROPOSED` action to `IN_EFFECT` (from any other status, `ERR_INVALID_STATE`), stamps `effective_at` from the logical clock, and fires the cascade for its type. Activating a `SUSPENSION` moves the establishment's `inspection_status` from `ACTIVE` to `SUSPENDED` — which first requires `grant_status` to be `GRANTED`, otherwise `ERR_ESTABLISHMENT_NOT_GRANTED` — and in the same request increments the establishment's `suspension_count` by 1, moves every shift window in `PLANNED` or `COVERAGE_GAP_FLAGGED` to `BLOCKED`, moves every label application in `UNDER_REVIEW` to `HELD`, and increments the establishment's `version` by 1. Activating a `WITHHOLD_MARKS` moves every label application of the establishment in `SUBMITTED` or `UNDER_REVIEW` to `HELD`. Activating a `WITHDRAWAL` moves the establishment's `grant_status` to `WITHDRAWN` and its `inspection_status` to `INACTIVE`, moves every shift window in `PLANNED` or `COVERAGE_GAP_FLAGGED` to `BLOCKED`, rejects every label application in `SUBMITTED`, `UNDER_REVIEW`, or `HELD` with the rejection reason of withdrawal, and increments the establishment's `version` by 1; withdrawal is terminal for both establishment dimensions per §2.5. Activating a `NOTICE_OF_INTENDED_ENFORCEMENT` changes no other entity.

Abatement unwinds what can be unwound. Lifting requires the action to be `IN_EFFECT` (otherwise `ERR_INVALID_STATE`) and requires `abatement_evidence` of at least 20 characters (otherwise `ERR_INVALID_REQUEST`); the evidence is stored on the action, which moves to the terminal `LIFTED` status. Lifting a `SUSPENSION` moves the establishment's `inspection_status` from `SUSPENDED` back to `ACTIVE`, moves every label application in `HELD` back to `UNDER_REVIEW`, and leaves blocked shift windows `BLOCKED` — their windows lie in the past and are not resurrected. Lifting a `WITHHOLD_MARKS` returns every label application it holds in `HELD` to the status it occupied before the hold, `SUBMITTED` or `UNDER_REVIEW`. Lifting a `NOTICE_OF_INTENDED_ENFORCEMENT` or a `WITHDRAWAL` touches no other entity — a withdrawn grant is never restored by a lift.

### 3.5. Humane Handling Observation and Egregious-Event Authority

Humane handling is enforced through a two-step observation-and-confirmation workflow with segregation of duties. An `Inspector` reports an observation with the `establishment_id`, their own id as `reported_by_inspector_id` (it must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`), the `species` concerned — which must be a member of the establishment's `species_classes`, otherwise `ERR_SPECIES_NOT_SUPPORTED` (HTTP 422) — a `severity` of `EGREGIOUS` or `NON_EGREGIOUS`, the `observed_at` timestamp (not after the logical clock, else `ERR_FUTURE_OBSERVATION`), and a free-text `description`. The event is born `REPORTED`.

Only a `SupervisoryReviewer` may confirm or dismiss, and never their own report: the caller's `X-User-ID` must differ from the event's `reported_by_inspector_id`, otherwise `ERR_SOD_REVIEWER_IS_ISSUER` (HTTP 403). Both decisions require the event to be `REPORTED` (otherwise `ERR_INVALID_STATE`), and per §2.7 the state check is evaluated before the segregation check, so a decision attempted on an already-decided event reports the state error. Dismissal moves the event to the terminal `DISMISSED` status with no side effects.

Confirmation moves the event to `CONFIRMED`, and its consequences depend on severity. A confirmed `NON_EGREGIOUS` event triggers no enforcement cascade. A confirmed `EGREGIOUS` event exercises the agency's immediate suspension authority: in the same request, the system creates an enforcement action with `action_type` `SUSPENSION`, `basis` `EGREGIOUS_HUMANE`, `status` `IN_EFFECT`, `auto_created` true, and `effective_at` stamped from the logical clock — and that action's activation cascade fires immediately, exactly as in §3.4: the establishment's `inspection_status` moves to `SUSPENDED`, its `suspension_count` increments by 1, its planned and gap-flagged shift windows move to `BLOCKED`, and its in-review label applications move to `HELD`.

### 3.6. Pathogen Sampling and Establishment Categorization

The sampling program tracks pathogen performance over a trailing 90-day window. An `Inspector` logs a sample against an establishment — which must hold a grant, otherwise `ERR_ESTABLISHMENT_NOT_GRANTED` — supplying the `establishment_id`, their own id as `collected_by_inspector_id` (pinned to `X-User-ID`, else `ERR_FORBIDDEN`), the `pathogen` (`SALMONELLA` or `CAMPYLOBACTER`), and the `collected_at` timestamp (not after the logical clock, else `ERR_FUTURE_OBSERVATION`). The sample's `result` begins at `PENDING`.

Recording a result — a `result` of `POSITIVE` or `NEGATIVE` on a `PENDING` sample, otherwise `ERR_INVALID_STATE` — stamps `resulted_at` from the logical clock and immediately recomputes the establishment's pathogen categorization. The computation runs per pathogen. Over the establishment's samples of that pathogen with a recorded `POSITIVE` or `NEGATIVE` result whose `resulted_at` lies within the trailing 90 days of the logical clock, count the resulted samples and the positive ones. Fewer than 10 resulted samples means that pathogen contributes no categorization at all. Otherwise the positive rate is the positive count divided by the resulted count, compared as an exact rational number with no rounding. The pathogen is a `CAT_1` candidate when its positive rate is at most half the standard rate for that pathogen, a `CAT_2` candidate when its rate is at most the standard rate, and a `CAT_3` candidate when its rate exceeds the standard rate. The boundaries are pinned: a rate exactly equal to the standard rate is `CAT_2`, never `CAT_3`; a rate exactly equal to half the standard is `CAT_1`. The standard rates are 0.10 for `SALMONELLA` and 0.15 for `CAMPYLOBACTER`.

The establishment's `pathogen_category` is the worst category across the pathogens that have sufficient samples — `CAT_3` outranks `CAT_2`, which outranks `CAT_1`. If no pathogen has sufficient samples, the category is unchanged (null if the establishment has never been categorized).

Crossing into the worst category is an enforcement event. Whenever a result recording causes any pathogen's recomputed category to transition to `CAT_3` from a different value, the system automatically creates an enforcement action against the establishment in the same request: `action_type` `NOTICE_OF_INTENDED_ENFORCEMENT`, `basis` `CATEGORY_3_PATHOGEN`, `status` `IN_EFFECT`, `auto_created` true, and `effective_at` stamped from the logical clock. A re-computation that lands on `CAT_3` from `CAT_3`, or that moves between `CAT_1` and `CAT_2`, creates nothing.

### 3.7. Label Claim Review and Documentation Minimums

Claims on a label — that a product is grass-fed, raised without antibiotics, organic, or of a specific breed — must be substantiated before the mark may be used. An `EstablishmentManager` submits an application naming the `establishment_id` (ownership-pinned to `X-User-ID`, else `ERR_FORBIDDEN`), the `product_name`, the `label_claim` — one of `GRASS_FED`, `NO_ANTIBIOTICS`, `ORGANIC`, or `BREED_SPECIFIC` — and the `documentation_refs`, an array of production-practice documentation references. The application is born `SUBMITTED` with `revision_count` 0.

A `LabelOfficer` begins review, moving the application from `SUBMITTED` to `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`), and later decides it with a `decision` of `APPROVE`, `REJECT`, or `RETURN`, each defined only from `UNDER_REVIEW`. Approval carries three gates beyond state, reported in pipeline order: the establishment's `grant_status` must be `GRANTED` (otherwise `ERR_ESTABLISHMENT_NOT_GRANTED`), its `inspection_status` must not be `SUSPENDED` (otherwise `ERR_ESTABLISHMENT_SUSPENDED`), and the count of `documentation_refs` must meet the minimum for the claim — 2 references for `GRASS_FED`, 2 for `NO_ANTIBIOTICS`, 3 for `ORGANIC`, and 1 for `BREED_SPECIFIC`; exactly at the minimum passes, and a shortfall is rejected with `ERR_INSUFFICIENT_DOCUMENTATION` (HTTP 422). Approval moves the application to the terminal `APPROVED` status; rejection moves it to the terminal `REJECTED` status; a return moves it to `RETURNED`.

A returned application may be resubmitted by the `EstablishmentManager` with refreshed `documentation_refs`: resubmission requires `RETURNED` status (otherwise `ERR_INVALID_STATE`), is ownership-pinned to the application's `establishment_id` (else `ERR_FORBIDDEN`), and is barred while the establishment is `SUSPENDED` (otherwise `ERR_ESTABLISHMENT_SUSPENDED`). It moves the application back to `SUBMITTED`, increments `revision_count` by 1, and replaces `documentation_refs` with the payload's array.

Label applications are also reached by the enforcement cascades of §3.4: an activated suspension holds every `UNDER_REVIEW` application, an activated `WITHHOLD_MARKS` holds every `SUBMITTED` or `UNDER_REVIEW` application, and an activated withdrawal rejects every `SUBMITTED`, `UNDER_REVIEW`, or `HELD` application outright. A `HELD` application returns to `UNDER_REVIEW` when the holding action is lifted — or, for an application held by `WITHHOLD_MARKS` from `SUBMITTED`, back to `SUBMITTED`.

### 3.8. Recall Coordination and Effectiveness Verification

When product in commerce must come back, a `RecallCoordinator` opens a recall case with the `establishment_id`, a `product_description`, the `quantity_lbs` in commerce — which must be greater than 0, otherwise `ERR_INVALID_REQUEST` — and a `reason_code` of `PATHOGEN`, `MISBRANDING`, or `FOREIGN_MATTER`. The case is born `INITIATED` with `recall_class` null and both requirement fields, `required_min_checks` and `required_effectiveness_ratio`, unset; its effectiveness counters `checks_performed` and `checks_effective` start at 0 and its `effectiveness_ratio` is null while no checks are recorded.

Classification is a `DistrictManager` decision: determining the class supplies a `recall_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III` and moves the recall from `INITIATED` to `CLASS_DETERMINED` (otherwise `ERR_INVALID_STATE`). The class pins the closure requirements: a `CLASS_I` recall requires at least 10 effectiveness checks and an effectiveness ratio of at least 0.95; `CLASS_II` requires at least 5 checks and 0.80; `CLASS_III` requires at least 4 checks and 0.75. Both values are stored on the recall as `required_min_checks` and `required_effectiveness_ratio`.

Evidence gathering is append-only. While the recall is `CLASS_DETERMINED`, the `RecallCoordinator` records effectiveness checks, each carrying the `consignee_name` contacted, an `outcome` of `EFFECTIVE` or `INEFFECTIVE`, and the `checked_at` timestamp (not after the logical clock, else `ERR_FUTURE_OBSERVATION`). Recording a check before classification — or after the recall has left `CLASS_DETERMINED` — is rejected with `ERR_RECALL_CLASS_REQUIRED` (HTTP 409). Each check is an immutable event referencing its parent via `recall_id`, carrying only `id` and `created_at` as system fields per §2.6, and the recall's derived counters update immediately: `checks_performed` increments by 1, `checks_effective` increments by 1 exactly when the outcome is `EFFECTIVE`, and `effectiveness_ratio` is recomputed as `checks_effective` divided by `checks_performed`, rounded half-up to 2 decimal places.

Closure is computed, not chosen. The `RecallCoordinator` closes a `CLASS_DETERMINED` recall (otherwise `ERR_INVALID_STATE`); with fewer than `required_min_checks` checks performed, the close is rejected with `ERR_EFFECTIVENESS_CRITERIA_NOT_MET` (HTTP 409). Otherwise the outcome falls out of the ratio: an `effectiveness_ratio` greater than or equal to `required_effectiveness_ratio` closes the recall as `CLOSED_EFFECTIVE` — equality closes as effective — and a ratio below the requirement closes it as `CLOSED_INEFFECTIVE`.

An ineffective recall is not abandoned; it is reclassified. Determining the class of a `CLOSED_INEFFECTIVE` recall — the only statuses from which classification is defined are `INITIATED` and `CLOSED_INEFFECTIVE`, otherwise `ERR_INVALID_STATE` — replaces the `recall_class`, recomputes `required_min_checks` and `required_effectiveness_ratio` for the new class, returns the recall to `CLASS_DETERMINED`, and resets the effectiveness evidence: `checks_performed` and `checks_effective` return to 0 and `effectiveness_ratio` to null, so the new classification is monitored on fresh evidence.

### 3.9. Appeals and Supervisory Review

An establishment that disputes a finding appeals it. The `EstablishmentManager` files an appeal naming the `noncompliance_record_id` and stating its `grounds`, which must be at least 10 characters long (otherwise `ERR_INVALID_REQUEST`). Filing requires the record to be `OPEN`, `RESPONSE_SUBMITTED`, or `ESCALATED` (otherwise `ERR_INVALID_STATE`) and is ownership-pinned: `X-User-ID` must equal the record's `establishment_id` (otherwise `ERR_FORBIDDEN`). Filing creates the appeal in `FILED` status and, in the same request, moves the record to `APPEALED`, recording the status it held at filing time in the record's `status_before_appeal` field.

Decisions belong to a `SupervisoryReviewer` who is not the issuing inspector. Deciding requires the appeal to be `FILED` and the underlying record to be `APPEALED` — a decision attempted when either has moved on is rejected with `ERR_INVALID_STATE` — and the caller's `X-User-ID` must differ from the record's `issued_by_inspector_id`, otherwise `ERR_SOD_REVIEWER_IS_ISSUER` (HTTP 403); per §2.7 the state check fires first, so a segregation violation on a stale appeal still reports the state error. Every decision stamps `decided_by_reviewer_id` with the caller's `X-User-ID` and `decided_at` with the logical clock, and the record moves with the outcome:

- An `outcome` of `AFFIRM` moves the appeal to `AFFIRMED` and the record from `APPEALED` to `ESCALATED`. The escalation count of §3.3 is re-evaluated at affirm time, so an affirmance that pushes the family's qualifying-record count to 3 within the trailing 90 days auto-creates the `PROPOSED` `NR_LINKAGE` suspension exactly as a direct escalation would.
- An `outcome` of `REMAND` moves the appeal to `REMANDED` and the record from `APPEALED` back to `OPEN`, reopening the finding for correction and response.
- An `outcome` of `VACATE` moves the appeal to `VACATED` and the record from `APPEALED` to `VACATED`. A vacated record disappears from every derived measure: it no longer counts toward `open_nr_count`, toward escalation qualification, or toward either risk score.

All three appeal outcomes are terminal for the appeal, and `VERIFIED` and `VACATED` are terminal for the record.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. Request bodies, gating rules, and side effects for each endpoint are specified by the workflows in §3 and the global rules in §2; this table is a navigational index only. The logical-clock endpoint is mounted outside the `/inspection` prefix; every other path below is mounted under `/inspection` exactly as written.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default `2026-09-01T00:00:00Z`, no wall-clock fallback) | ProgramAdministrator |
| POST | `/inspection/establishments` | Register an establishment (`UNGRANTED` × `INACTIVE`) | ProgramAdministrator |
| GET | `/inspection/establishments/{id}` | Get one establishment incl. computed fields (`pathogen_category`, `open_nr_count`, `suspension_count`, `compliance_score`, `enforcement_priority_score`, risk scores) | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, LabelOfficer, RecallCoordinator, ProgramAdministrator |
| POST | `/inspection/grant-applications` | Submit a grant of inspection application | EstablishmentManager |
| GET | `/inspection/establishments/{id}/grant-applications` | List grant applications of an establishment | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/grant-applications/{id}/begin-review` | Move application `SUBMITTED` → `UNDER_REVIEW` | DistrictManager |
| POST | `/inspection/grant-applications/{id}/record-adequacy` | Record one adequacy finding (facility, sanitation, or hazard plan) | DistrictManager |
| POST | `/inspection/grant-applications/{id}/decide` | Grant or deny the application | DistrictManager |
| POST | `/inspection/grant-applications/{id}/resubmit` | Resubmit a `DENIED` application with refreshed document references | EstablishmentManager |
| POST | `/inspection/grant-applications/{id}/withdraw` | Withdraw a `SUBMITTED` or `UNDER_REVIEW` application | EstablishmentManager |
| POST | `/inspection/inspectors` | Onboard an inspector | ProgramAdministrator |
| POST | `/inspection/inspectors/{id}/deactivate` | Deactivate an inspector; cancels their `SCHEDULED` assignments | ProgramAdministrator |
| POST | `/inspection/shift-windows` | Plan an operating shift for a granted establishment | EstablishmentManager |
| GET | `/inspection/establishments/{id}/shift-windows` | List shift windows of an establishment | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| GET | `/inspection/shift-windows/{id}` | Get one shift window incl. stored gap fields and version | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/shift-windows/{id}/verify-coverage` | Recompute provisional/final coverage gaps; transition to `VERIFIED_COVERED` or `COVERAGE_GAP_FLAGGED` | Inspector |
| POST | `/inspection/shift-windows/{id}/assignments` | Assign an inspector to a coverage interval on one line (OCC on window version) | ProgramAdministrator |
| GET | `/inspection/shift-assignments` | List/filter shift assignments | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| GET | `/inspection/shift-assignments/{id}` | Get one shift assignment | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/shift-assignments/{id}/confirm` | Assigned inspector confirms presence | Inspector |
| POST | `/inspection/shift-assignments/{id}/cancel` | Cancel a `SCHEDULED` assignment | ProgramAdministrator |
| POST | `/inspection/noncompliance-records` | Issue a noncompliance record | Inspector |
| GET | `/inspection/noncompliance-records` | List/filter noncompliance records | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| GET | `/inspection/noncompliance-records/{id}` | Get one noncompliance record | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/noncompliance-records/{id}/respond` | Establishment responds to an `OPEN` record | EstablishmentManager |
| POST | `/inspection/noncompliance-records/{id}/verify-response` | Inspector verifies corrective action (`VERIFY`) or escalates (`ESCALATE`) | Inspector |
| POST | `/inspection/establishments/{id}/enforcement-actions` | Propose an enforcement action (OCC on establishment version) | DistrictManager |
| GET | `/inspection/establishments/{id}/enforcement-actions` | List enforcement actions of an establishment, `created_at` ascending | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/enforcement-actions/{id}/activate` | Activate a `PROPOSED` enforcement action (basis re-evaluated) | DistrictManager |
| POST | `/inspection/enforcement-actions/{id}/lift` | Lift an `IN_EFFECT` action with abatement evidence | DistrictManager |
| POST | `/inspection/humane-handling-events` | Report a humane handling observation | Inspector |
| GET | `/inspection/humane-handling-events` | List/filter humane handling events | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| GET | `/inspection/humane-handling-events/{id}` | Get one humane handling event | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/humane-handling-events/{id}/confirm` | Supervisory confirmation; `EGREGIOUS` triggers the suspension cascade | SupervisoryReviewer |
| POST | `/inspection/humane-handling-events/{id}/dismiss` | Supervisory dismissal of a reported event | SupervisoryReviewer |
| POST | `/inspection/pathogen-samples` | Log a pathogen sample collection | Inspector |
| GET | `/inspection/pathogen-samples` | List/filter pathogen samples | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| GET | `/inspection/pathogen-samples/{id}` | Get one pathogen sample | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/pathogen-samples/{id}/record-result` | Record `POSITIVE` or `NEGATIVE`; recomputes `pathogen_category`; `CAT_3` transition auto-creates a notice | Inspector |
| POST | `/inspection/label-applications` | Submit a label claim application with production-practice documentation | EstablishmentManager |
| GET | `/inspection/establishments/{id}/label-applications` | List label applications of an establishment | EstablishmentManager, LabelOfficer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/label-applications/{id}/begin-review` | Move label application `SUBMITTED` → `UNDER_REVIEW` | LabelOfficer |
| POST | `/inspection/label-applications/{id}/decide` | Approve, reject, or return for revision | LabelOfficer |
| POST | `/inspection/label-applications/{id}/resubmit` | Resubmit a `RETURNED` application with refreshed documentation | EstablishmentManager |
| POST | `/inspection/recalls` | Open a recall coordination case | RecallCoordinator |
| GET | `/inspection/recalls/{id}` | Get one recall incl. derived effectiveness fields | EstablishmentManager, Inspector, DistrictManager, RecallCoordinator, ProgramAdministrator |
| GET | `/inspection/establishments/{id}/recalls` | List recalls of an establishment | EstablishmentManager, Inspector, DistrictManager, RecallCoordinator, ProgramAdministrator |
| POST | `/inspection/recalls/{id}/determine-class` | Set or re-set the recall class; re-opens a `CLOSED_INEFFECTIVE` recall and resets effectiveness evidence | DistrictManager |
| POST | `/inspection/recalls/{id}/effectiveness-checks` | Record one effectiveness check; recall counters update immediately | RecallCoordinator |
| GET | `/inspection/recalls/{id}/effectiveness-checks` | List effectiveness checks of a recall | EstablishmentManager, Inspector, DistrictManager, RecallCoordinator, ProgramAdministrator |
| POST | `/inspection/recalls/{id}/close` | Close a `CLASS_DETERMINED` recall; outcome computed from effectiveness criteria | RecallCoordinator |
| POST | `/inspection/appeals` | Appeal a noncompliance record (record moves to `APPEALED`) | EstablishmentManager |
| GET | `/inspection/noncompliance-records/{id}/appeals` | List appeals filed against one noncompliance record | EstablishmentManager, Inspector, SupervisoryReviewer, DistrictManager, ProgramAdministrator |
| POST | `/inspection/appeals/{id}/decide` | Supervisory decision: `AFFIRM`, `REMAND`, or `VACATE` (segregation of duties enforced) | SupervisoryReviewer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each is raised — and the precedence among them — are specified by the validation pipeline in §2.7 and the workflow rules in §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ESTABLISHMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTOR_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_NONCOMPLIANCE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_ENFORCEMENT_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_HUMANE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_PATHOGEN_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_LABEL_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_ESTABLISHMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SHIFT_WINDOW_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ESTABLISHMENT_NOT_GRANTED` | 409 Conflict |
| `ERR_ESTABLISHMENT_SUSPENDED` | 409 Conflict |
| `ERR_ESTABLISHMENT_WITHDRAWN` | 409 Conflict |
| `ERR_INSPECTOR_INACTIVE` | 409 Conflict |
| `ERR_GRANT_DECISION_BLOCKED` | 409 Conflict |
| `ERR_ESCALATION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_WITHDRAWAL_CONDITIONS_NOT_MET` | 409 Conflict |
| `ERR_INSPECTOR_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_SPECIES_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_TRAVEL_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_FUTURE_OBSERVATION` | 422 Unprocessable Entity |
| `ERR_SHIFT_WINDOW_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_DOCUMENTATION` | 422 Unprocessable Entity |
| `ERR_SOD_REVIEWER_IS_ISSUER` | 403 Forbidden |
| `ERR_RECALL_CLASS_REQUIRED` | 409 Conflict |
| `ERR_EFFECTIVENESS_CRITERIA_NOT_MET` | 409 Conflict |
