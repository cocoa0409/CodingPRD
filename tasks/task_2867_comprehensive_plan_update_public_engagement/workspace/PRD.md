# Comprehensive Plan Update API — Product Requirements Document

## 1. Introduction

A comprehensive plan update is the single largest document a city planning department produces, and it is also the one most likely to be rejected on procedural grounds. State law prescribes which elements must exist, how many housing units each income tier must accommodate, how long an environmental document must sit in public circulation, and how much notice a hearing requires. Departments routinely discover a defect — an element approved while its internal-consistency dependencies were still open, an equity outreach target missed by a fraction of a percentage point, a growth scenario computed against acreage that was superseded a week earlier — only after the council has already gavelled in. The cost of that discovery is a full re-submission cycle.

This service replaces the spreadsheets and shared drives with a single system of record for one plan update cycle: the existing-conditions inventories, the growth projection scenarios and their land-capacity analysis, the drafting and review of the statutory elements, the internal-consistency graph that ties those elements together, the public engagement program with its equity-weighted participation accounting, the state mandate filing and determination, the environmental review of the plan and its alternatives, the commission and council adoption hearings with full amendment tracking, and the implementation program with its monitoring indicators. Every write that could change the plan's statutory standing immediately recomputes a derived gate on the plan, and that gate — not an operator's judgement — is what decides whether a hearing may proceed.

The API is mounted under `/planning`, with one additional administrative capability outside that mount for driving the server's logical clock during testing. Two design commitments run through everything that follows. First, **segregation of duties**: the caller who authors an artefact may never be the caller who blesses it. Second, **immediate consistency**: there are no background jobs and no eventual reconciliation — by the time a mutating request returns, every derived counter, every cascaded child state and every recomputed gate on the plan already reflects the write.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the service must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role. If either header is absent, or if `X-User-Role` is not one of the five roles declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are well formed but the named role is not authorized for the requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403). Authorization for each individual endpoint is listed in the endpoint table in section 4.

The five roles are `PlanningStaff`, `PlanningDirector`, `EnvironmentalConsultant`, `CommissionClerk` and `StateReviewer`.

- `PlanningStaff` are the long-range planners. They assemble the existing-conditions inventories, build growth scenarios, draft the elements, wire the internal-consistency network, register meeting venues, run the public engagement program and maintain the implementation program. They author, but they never approve.
- `PlanningDirector` is the department head who owns approvals: opening a plan cycle, certifying inventories, adopting the official growth scenario, deciding element reviews, reconciling consistency links, certifying the environmental document and filing the plan with the state.
- `EnvironmentalConsultant` is the outside consultant who prepares the environmental document and its alternatives, releases it for public comment and runs the preferred-alternative selector. The consultant may not certify the document it prepared and may not touch plan elements.
- `CommissionClerk` is the clerk of the planning commission and the city council. The clerk schedules hearings, gavels them in, records outcomes and keeps the amendment record.
- `StateReviewer` is the state housing and community development reviewer who assigns the housing allocation by income tier and returns the mandate determination on a submitted plan. This role has no authoring and no hearing powers.

Identity in this system is deliberately shallow. When `X-User-Role` is `PlanningStaff`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the same is true when the role is `PlanningDirector`, `EnvironmentalConsultant`, `CommissionClerk` or `StateReviewer`. The server never compares `X-User-ID` to the `id` of any stored row and there is no notion of resource ownership by user. What the server does do is **record** the acting identifier at the moments where a later step must be performed by somebody else: `authored_by_user_id` on an inventory dataset and on a plan element, `certified_by_user_id` on an inventory dataset, `reviewed_by_user_id` on a plan element, `reconciled_by_user_id` on a consistency link, and `proposed_by_user_id` on an amendment. Those recorded values are compared against a later caller's `X-User-ID` by the segregation-of-duties rule described in section 2.7 — that comparison, and nothing else, is what `X-User-ID` is for.

All five roles may read every single-resource read, list and computed-read endpoint under `/planning`, and all five may drive the logical clock.

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

Every list endpoint accepts two optional query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 422) rather than being silently clamped.

List results are always ordered by `created_at` ascending. Where a list endpoint also accepts filters, the filters narrow the result set before pagination is applied, so `total_count` reports the number of rows matching the filters, not the number of rows in the collection. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`; `has_more` is true exactly when rows matching the filters remain beyond the current window.

### 2.4. Record Identity, Timestamps and Versioning

Every persisted row is addressed by an `id`, a server-minted UUID with no type prefix; clients never supply an `id`. Every row also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, stamped once at creation and never modified.

Most rows additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of that row, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the row's own caller never requested, such as a counter being incremented because a child was created, or a state being flipped by a cascade from the parent plan. Plan updates, inventory datasets, growth scenarios, housing allocations, plan elements, consistency links, engagement activities, environmental reviews, plan alternatives, hearings, amendments and implementation actions all behave this way.

Two entities are configuration rather than workflow and are deliberately exempt. A `Venue` carries only `id` and `created_at`: it has no `updated_at` and no `version`, and there is no endpoint that modifies one. A `ParticipationRecord` likewise carries only `id` and `created_at`: participation cannot be edited, re-weighted or deleted once captured, so neither `updated_at` nor `version` exists on it.

All datetime values accepted in request bodies must be ISO 8601 UTC with three fractional digits; a malformed instant is rejected with `ERR_INVALID_REQUEST`.

Time itself is a server concern. The service keeps a **logical clock** whose value on startup is exactly `2026-08-01T00:00:00Z`. Every deadline, notice period, comment period and activity-end comparison in this specification is evaluated against the logical clock, never against real wall-clock time; before the clock has been moved at all, those comparisons are evaluated against that fixed startup default. An administrative capability accepts a `to_iso8601` instant and sets the clock to it, returning the new value as `current_utc`. The clock may be moved both forward and backward, and setting it mutates no entity — subsequent requests simply evaluate every temporal rule against the new instant.

### 2.5. Version Pinning on Cross-Aggregate Writes

Two writes in this system attach a new child to a parent whose content the client must have actually read, and neither can be protected by a state precondition, because repeating the write against the same parent is legitimate. Both therefore require the client to pin the parent's `version`.

`POST /planning/amendments` requires a non-optional `expected_element_version` field carrying the `version` of the target plan element as the clerk last observed it. If that value does not equal the element's current `version`, the request is rejected with `ERR_STALE_ELEMENT_VERSION` (HTTP 412) and nothing is created. Several amendments against the same element are perfectly normal — each supersedes the prior text — so the guard is not "has an amendment already been moved" but "is the clerk moving against text they have seen". An element's `version` advances on every prior amendment docketing, on every content revision, and on every cascade that touches the element, so a clerk who has been away from the record must re-read the element before moving again.

`POST /planning/growth-scenarios` requires a non-optional `expected_inventory_version` field carrying the `version` of the pinned land-use inventory dataset as the analyst last observed it. If that value does not equal the dataset's current `version`, the request is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412) and no scenario is computed. Any number of scenarios may legitimately be pinned to the same certified dataset, so a state precondition cannot express this rule; the stale-version check is precisely what stops a scenario's capacity figures from being computed against acreage the analyst never saw.

No other endpoint in this service takes a version field. In particular, revising an element's content, certifying an inventory, adopting a scenario, reconciling a link, recording a hearing outcome and adopting or rescinding an amendment all proceed without a client-supplied version.

### 2.6. Numeric Precision and Rounding

All rounding in this system is **round half up**, and every rule below states exactly where the rounding happens, because rounding at a different step produces a different answer.

- Land capacity and projected housing demand are whole unit counts. Rounding is applied once, to the final product, never to intermediate acreage or intermediate household figures.
- Housing allocation figures are whole unit counts, and the per-tier capacity share is rounded before the waterfall consumes it — not after the shares have been summed.
- Participation weights, and the two plan-level weight totals accumulated from them, carry one decimal place.
- Equity shares, both on an activity and on a plan, are percentages carried to one decimal place.
- Environmental impact scores — the raw score, the mitigation credit and the net score — each carry two decimal places, and each is rounded independently, in the order the calculation states.
- Monitoring indicator readings are compared at the full precision supplied by the caller and are not rounded.

Comparisons against thresholds are exact and their inclusivity is part of the contract. The plan-wide equity threshold is compared inclusively, so a plan at exactly 40.0 percent satisfies it while a plan at 39.9 percent does not. A monitoring reading exactly equal to its target counts as on track.

### 2.7. Segregation of Duties

Three approval steps in this system must be performed by a different operator than the step they bless. Certifying an inventory dataset requires that `X-User-ID` differ from the dataset's `authored_by_user_id`. Recording a review decision on a plan element requires that `X-User-ID` differ from the element's `authored_by_user_id`. Adopting an amendment requires that `X-User-ID` differ from the amendment's `proposed_by_user_id`. In all three cases a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and no other operation in the service applies this check.

The rule compares identifiers, not roles. Two different `PlanningDirector` operators may certify each other's datasets freely; one director cannot certify their own. Note also that the check runs *after* the state preconditions of the operation, so an operator who tries to certify their own already-certified dataset receives the state error, not the duties error.

### 2.8. Validation Order

Many requests in this system can fail for several reasons at once, and the reported error must be predictable. Validation is therefore a strictly ordered ladder, evaluated from the top, and the first rule that fails determines the response. The ladder is:

1. **Authentication.** Both headers present and `X-User-Role` one of the five declared roles, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The acting role appears in the endpoint's authorized list, otherwise `ERR_ROLE_NOT_PERMITTED` (403).
3. **Path resolution.** Every id embedded in the URL path resolves to an existing row, validated left to right — the plan update id in a nested path is checked before the child id that follows it. The failing id determines the code: `ERR_PLAN_UPDATE_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`, `ERR_SCENARIO_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_LINK_NOT_FOUND`, `ERR_ACTIVITY_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND` or `ERR_ACTION_NOT_FOUND`, all HTTP 404.
4. **Request shape.** The body conforms to the endpoint's input schema: required fields present, enum members recognised, numbers inside their declared ranges, datetimes ISO 8601 UTC with three fractional digits, an activity's `end_at` strictly after its `start_at`, a hearing's `scheduled_end` strictly after its `scheduled_start`, the land-use acreage fields present only on a land-use inventory, `venue_id` present only for a workshop or a targeted-outreach activity, `deficient_element_types` a non-empty subset of the five statutory element types, and `limit`/`offset` inside their bounds on list endpoints. Violations are `ERR_INVALID_REQUEST` (422).
5. **Body foreign keys.** Every foreign key supplied in the body resolves to an existing row, otherwise `ERR_PLAN_UPDATE_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`, `ERR_ELEMENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_HEARING_NOT_FOUND` or `ERR_ACTIVITY_NOT_FOUND` (404).
6. **State preconditions.** The target row is in a state the requested transition permits, and every cross-entity state precondition declared on that transition holds — the plan is not adopted, the inventory is certified, the scenario is a draft, the element is in the required status, the hearing is scheduled or open, the review is draft or circulated, the amendment is proposed or adopted, the action is scheduled. These are the HTTP 409 codes `ERR_PLAN_ALREADY_ADOPTED`, `ERR_PLAN_NOT_DRAFTING`, `ERR_PLAN_NOT_SUBMITTED`, `ERR_PLAN_NOT_CERTIFIED`, `ERR_PLAN_NOT_RECOMMENDED`, `ERR_INVENTORY_NOT_DRAFT`, `ERR_INVENTORY_NOT_CERTIFIED`, `ERR_INVENTORY_TYPE_MISMATCH`, `ERR_ADOPTED_SCENARIO_PINNED`, `ERR_SCENARIO_NOT_DRAFT`, `ERR_SCENARIO_NOT_ADOPTED`, `ERR_INVENTORY_SET_INCOMPLETE`, `ERR_ELEMENT_NOT_DRAFT`, `ERR_ELEMENT_NOT_IN_REVIEW`, `ERR_ELEMENT_NOT_AMENDABLE`, `ERR_LINK_ALREADY_CLEARED`, `ERR_TARGET_ELEMENT_NOT_REVIEWABLE`, `ERR_ACTIVITY_NOT_SCHEDULED`, `ERR_ACTIVITY_CLOSED`, `ERR_REVIEW_NOT_DRAFT`, `ERR_REVIEW_NOT_CIRCULATED`, `ERR_HEARING_NOT_SCHEDULED`, `ERR_HEARING_NOT_OPEN`, `ERR_AMENDMENT_NOT_PROPOSED`, `ERR_AMENDMENT_NOT_ADOPTED`, `ERR_ACTION_NOT_SCHEDULED` and `ERR_ACTION_ALREADY_COMPLETED`.
7. **Version pinning.** Where the endpoint requires it, the supplied version equals the parent's current `version`, otherwise `ERR_STALE_ELEMENT_VERSION` or `ERR_STALE_INVENTORY_VERSION` (412).
8. **Segregation of duties**, as described in section 2.7 — `ERR_SEGREGATION_OF_DUTIES` (403).
9. **Plan posture gate.** A hearing may only be gavelled in, or given an outcome of recommend or adopt, while the plan's `compliance_posture` is `CLEAR`, otherwise `ERR_PLAN_POSTURE_BLOCKED` (409).
10. **Venue occupancy** — `ERR_VENUE_TIME_CONFLICT` (409).
11. **Hearing calendar occupancy** — `ERR_HEARING_SLOT_CONFLICT` (409).
12. **Hearing daily cap** — `ERR_HEARING_DAILY_CAP_EXCEEDED` (409).
13. **Public notice lead time** — `ERR_NOTICE_PERIOD_TOO_SHORT` (422).
14. **Environmental circulation window overlap** — `ERR_REVIEW_WINDOW_OVERLAP` (409).
15. **Logical-clock gates.** Gavelling in requires the clock to have reached `scheduled_start` (`ERR_HEARING_NOT_YET_STARTED`); certifying an environmental document requires the clock to have reached `comment_period_ends_at` (`ERR_COMMENT_PERIOD_OPEN`); completing an activity requires the clock to have reached `end_at` (`ERR_ACTIVITY_NOT_ENDED`); creating an inventory requires its `vintage_year` not to be later than the plan's `base_year` (`ERR_INVENTORY_VINTAGE_TOO_LATE`). All are HTTP 409.
16. **Cross-aggregate ownership.** Both elements of a consistency link belong to one plan; an amendment's target element belongs to its hearing's plan; an implementation action's source element belongs to its plan; a growth scenario's inventory belongs to its plan. The codes are `ERR_CROSS_PLAN_LINK`, `ERR_CROSS_PLAN_AMENDMENT` and `ERR_CROSS_PLAN_ACTION` (409).
17. **Consistency graph integrity**, evaluated in this internal order: the link is not self-referential (`ERR_SELF_CONSISTENCY_LINK`, 422), the source-and-target pair is not already declared (`ERR_DUPLICATE_CONSISTENCY_LINK`, 409), and the new edge does not close a directed cycle (`ERR_CONSISTENCY_CYCLE`, 409).
18. **Scope uniqueness.** One element per element type on a plan (`ERR_DUPLICATE_ELEMENT_TYPE`), one allocation per income tier on a plan (`ERR_DUPLICATE_ALLOCATION_TIER`), one participation record per respondent handle on an activity (`ERR_DUPLICATE_PARTICIPATION`). All 409.
19. **Content readiness.** An element carries at least one policy before review (`ERR_ELEMENT_HAS_NO_POLICIES`); a review carries at least two alternatives before circulation (`ERR_INSUFFICIENT_ALTERNATIVES`); a targeted-outreach activity is booked at an accessible, transit-served venue (`ERR_VENUE_NOT_EQUITY_ELIGIBLE`); an amendment adoption does not drive an element's policy count below zero (`ERR_POLICY_COUNT_NEGATIVE`). All 409.
20. **Hearing outcome legality** — `ERR_OUTCOME_NOT_VALID_FOR_BODY` and `ERR_UNRESOLVED_AMENDMENTS` (409).
21. **State mandate completeness** — `ERR_REQUIRED_ELEMENT_MISSING` and `ERR_ALLOCATION_INCOMPLETE` (409).
22. **Internal consistency** — `ERR_CONSISTENCY_UNRESOLVED` (409).
23. **Environmental review readiness** — `ERR_ENVIRONMENTAL_REVIEW_MISSING`, `ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED` and `ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED` (409).
24. **Council hearing prerequisite** — `ERR_COMMISSION_RECOMMENDATION_REQUIRED` (409).
25. **Land capacity adequacy** — `ERR_HOUSING_SHORTFALL` (409).
26. **Equity target** — `ERR_EQUITY_TARGET_NOT_MET` (409).
27. **Iteration ceilings** — `ERR_RESUBMISSION_LIMIT_EXCEEDED` (409) and `ERR_ESCALATION_OVERRIDE_REQUIRED` (403).
28. **Empty-set guards** — `ERR_NO_ELIGIBLE_ALTERNATIVE`, `ERR_NO_PARTICIPATION_RECORDS`, `ERR_NO_INDICATOR_READING` and `ERR_INDICATOR_OFF_TRACK` (409).

Two consequences of this ordering are worth stating outright, because they are counter-intuitive. A hearing that is both calendar-conflicting and short on public notice reports the calendar conflict, since occupancy (rungs 11 and 12) precedes the notice rule (rung 13). And an environmental document that would both overlap another circulation window and carry too few alternatives reports the window overlap, since the window rule (rung 14) precedes content readiness (rung 19).

### 2.9. The Compliance Posture Gate

Each plan update carries a derived field `compliance_posture` that summarises, in one enumerated value, whether the plan is currently fit to advance through its adoption hearings. It is recomputed — never set by a caller — as a side effect of every mutation that can change one of its inputs: element review decisions, consistency link creation, reconciliation and every cascade that moves a link, scenario adoption, housing allocation creation, activity completion and cancellation, state determinations, and amendment adoption and rescission.

The posture is decided by a precedence ladder in which the first matching rule wins, and that precedence is part of the contract:

1. If the plan's `state_review_status` is `DEFICIENT`, the posture is `FROZEN`.
2. Otherwise, if `open_consistency_link_count` is greater than zero, the posture is `CONSISTENCY_HOLD`.
3. Otherwise, if `adopted_scenario_id` is null or `housing_shortfall_total` is greater than zero, the posture is `CAPACITY_HOLD`.
4. Otherwise, if `equity_share_pct` is below the minimum plan-wide underrepresented participation share of 40.0 percent, the posture is `EQUITY_HOLD`.
5. Otherwise the posture is `CLEAR`.

The equity comparison at step 4 is the inclusive one described in section 2.6: a plan at exactly 40.0 percent passes to `CLEAR`, a plan at 39.9 percent is held at `EQUITY_HOLD`. Because the ladder is ordered, a plan that is simultaneously deficient at the state and short on equity reports `FROZEN`; lifting the equity problem alone will not change that.

Three of the ladder's inputs are themselves derived counters, each computed over an explicit filter. `open_consistency_link_count` is the number of consistency links whose source element belongs to this plan and whose status is either `OPEN` or `STALE` — cleared links do not count, and stale links count exactly as much as open ones. `required_elements_complete_count` is the number of distinct element types on this plan for which an element exists in status `APPROVED` or `ADOPTED`; it is recomputed alongside the posture but does **not** feed the posture ladder — its job is to gate the state filing. `housing_shortfall_total` is the sum of the shortfall figures of the plan's income-tier allocations.

The posture also drives a cascade on the plan's hearings, in both directions. Whenever a cascade pushes the posture out of `CLEAR`, every hearing of that plan in status `SCHEDULED` moves `SCHEDULED → BLOCKED` and its `version` increments by 1. Whenever a later cascade brings the recomputed posture back to `CLEAR`, every hearing of that plan in status `BLOCKED` moves `BLOCKED → SCHEDULED` and its `version` increments by 1. A hearing that has already been gavelled in is never blocked retroactively; only `SCHEDULED` hearings are affected.

### 2.10. Derived Counters and Conservation Invariants

Callers never write a derived field. Counters such as `referencing_scenario_count` on an inventory dataset, `record_count` and `underrepresented_record_count` on an activity, `alternative_count` on an environmental review, `amendment_count` and `adopted_amendment_count` on a hearing, `reading_count` on an implementation action, and `monitoring_on_track_count`, `open_consistency_link_count`, `required_elements_complete_count`, `housing_shortfall_total`, `participation_weight_total`, `underrepresented_weight_total`, `equity_share_pct` and `resubmission_count` on the plan are all maintained by the server as side effects of the writes described in section 3. If a caller supplies such a field in a request body, the value is ignored; the same is true of `is_underrepresented` on a participation record, which the server always derives from the respondent's demographic group.

Two of the derived quantities are **conserved**, meaning that a compensating operation must return them to their exact prior values rather than to a merely nearby value.

The first conserved quantity is weighted participation. After an activity has been completed and then cancelled, the plan's `participation_weight_total` must once again equal the sum of `total_weighted_count` over the plan's activities in status `COMPLETED`, its `underrepresented_weight_total` must once again equal the sum of `underrepresented_weighted_count` over that same set, and its `equity_share_pct` must once again equal one hundred times `underrepresented_weight_total` divided by `participation_weight_total`, rounded half up to one decimal place, or 0.0 when that denominator is zero. This equality is asserted after every completion and after every cancellation of a completed activity; the compensation may not leave the plan's weighted participation drifted by even one tenth.

The second conserved quantity is an element's policy inventory. After an adopted amendment has been rescinded, the target element's `policy_count` must equal the value it held immediately before that amendment was adopted, the element's `status` must equal the amendment's recorded `prior_element_status`, the plan's `open_consistency_link_count` must once again equal the number of links of the plan whose status is `OPEN` or `STALE`, and no consistency link may still carry `staled_by_amendment_id` pointing at the rescinded amendment.

### 2.11. Reading Nested Collections

Several collections are reachable only through their parent's path — a plan's inventory datasets, elements, housing allocations and hearings, an activity's participation records, a review's alternatives. For these, path ids are resolved left to right: the parent id is looked up first, and a request naming a non-existent plan reports `ERR_PLAN_UPDATE_NOT_FOUND` even when the child id is also invalid. Collections that carry their own top-level list endpoint instead expose the parent link as a filter — growth scenarios can be listed by `plan_update_id` or by `land_use_inventory_id`, consistency links by `source_element_id` or `target_element_id`, engagement activities by `plan_update_id` or `venue_id`, environmental reviews by `plan_update_id` or `preferred_alternative_id`, amendments by `hearing_id` or `target_element_id`, implementation actions by `plan_update_id` or `source_element_id`, and plan updates by `adopted_scenario_id`. Those filters are the documented reverse lookup for the corresponding stored reference; a plan's adopted scenario, for instance, is discoverable both by reading the plan and by filtering the plan list on `adopted_scenario_id`.

A dedicated computed read on the plan returns the state-mandate checklist and capacity/equity dashboard in one payload: `plan_update_id`, `compliance_posture`, `state_review_status`, `required_elements_complete_count`, `missing_element_types` (the statutory element types that still lack an element in `APPROVED` or `ADOPTED`), `open_consistency_link_count`, `housing_shortfall_total`, `equity_share_pct`, and — taken from the plan's adopted scenario — `land_capacity_units`, `projected_demand_units` and `capacity_gap_units`, plus `monitoring_on_track_count`.

## 3. Business Logic & Workflows

### 3.1. Opening a Plan Cycle and Building the Existing-Conditions Record

Only a `PlanningDirector` may open a plan update cycle. The opening payload carries a public `title` of 1 to 160 non-blank characters (for example, "Horizon 2045"), a `jurisdiction_code` of 2 to 12 uppercase alphanumeric characters — the identifier the state expects on every mandate filing — and the two years that frame the analysis: `base_year`, the year the existing-conditions picture describes, and `horizon_year`, the statutory planning horizon. Both years must fall between 2000 and 2100, and the horizon must sit at least a full decade beyond the base year: subtracting `base_year` from `horizon_year` must give 10 or more. A cycle that fails that spread is rejected as a malformed request.

A freshly opened plan starts in `DRAFTING` with `state_review_status` at `NOT_SUBMITTED`, `state_findings` and `adopted_scenario_id` and `adopted_at` all null, `resubmission_count`, `open_consistency_link_count`, `required_elements_complete_count`, `housing_shortfall_total` and `monitoring_on_track_count` all zero, and `equity_share_pct`, `participation_weight_total` and `underrepresented_weight_total` all 0.0. Its `compliance_posture` is computed immediately by the posture ladder, and because a brand-new plan has no adopted scenario, the answer is always `CAPACITY_HOLD` — a plan is never born `CLEAR`. The plan's own lifecycle runs `DRAFTING → STATE_SUBMITTED → STATE_CERTIFIED → COMMISSION_RECOMMENDED → ADOPTED`, with two loops back to earlier states described in sections 3.8 and 3.9; `ADOPTED` is terminal, and once a plan reaches it, every write anywhere in its aggregate is refused with `ERR_PLAN_ALREADY_ADOPTED`.

The existing-conditions analysis is assembled by `PlanningStaff` as a set of inventory datasets, each attached to the plan by a payload carrying the `plan_update_id`. An `inventory_type` of `DEMOGRAPHIC`, `HOUSING` or `EMPLOYMENT` describes a tabular dataset and must carry a `record_count` of at least 1 while supplying none of the four acreage fields. An `inventory_type` of `LAND_USE` is the opposite case: all four acreage fields are mandatory and `record_count` is not part of the picture. Those four are `vacant_acres`, the vacant developable acreage; `underutilized_acres`, the redevelopable acreage; `infrastructure_constrained_acres`, that subset of the vacant acreage which currently lacks sewer or water capacity, which must not exceed `vacant_acres`; and `allowed_density_units_per_acre`, the weighted allowed residential density across the inventoried acres, which must be strictly greater than zero. The three acreage figures must each be zero or greater. Supplying acreage on a non-land-use dataset, or omitting it on a land-use one, is a schema violation.

Every dataset also carries a `vintage_year` between 2000 and 2100 recording when the underlying data was collected, and it may not be newer than the picture it claims to describe: a `vintage_year` later than the plan's `base_year` is refused with `ERR_INVENTORY_VINTAGE_TOO_LATE`. For a dataset creation the checks run in the ladder order of section 2.8 — the shape of the acreage payload first, then the existence of the plan, then the plan's not-yet-adopted status, and only then the vintage comparison. A new dataset enters `DRAFT` with `referencing_scenario_count` at zero, and the caller's `X-User-ID` is stamped into `authored_by_user_id`.

Certification is a `PlanningDirector` act that moves a dataset `DRAFT → CERTIFIED`, stamps `certified_by_user_id` with the certifying director's identifier and increments the dataset's `version`. A dataset already `CERTIFIED` or `SUPERSEDED` cannot be certified again (`ERR_INVENTORY_NOT_DRAFT`). Before the segregation-of-duties comparison runs, one further state guard applies: if the plan's currently certified dataset of the same `inventory_type` is pinned by a growth scenario that has already been adopted, certifying a replacement would silently invalidate the plan's official projection, so the attempt is refused with `ERR_ADOPTED_SCENARIO_PINNED`. Only after that guard does the service compare `X-User-ID` against `authored_by_user_id` and reject a self-certification.

Certification is also a supersession event, and it cascades. Any sibling dataset of the same `plan_update_id` and the same `inventory_type` that was `CERTIFIED` moves `CERTIFIED → SUPERSEDED`, with its `version` incremented. That supersession in turn reaches the scenarios: every growth scenario still in `DRAFT` whose pinned land-use inventory is the dataset just superseded moves `DRAFT → SUPERSEDED` and has its own `version` incremented. Draft work built on stale acreage is thereby retired automatically rather than left to be discovered at submission time.

### 3.2. Growth Scenarios: Land Capacity, Projected Demand and Adoption

A growth scenario is a `PlanningStaff` product. Its payload names the `plan_update_id`, the `land_use_inventory_id` of the acreage dataset it is computed from, the `expected_inventory_version` that pins that dataset as described in section 2.5, a `label` of 1 to 80 characters for the capacity-analysis table, a `method` of either `TREND` or `POLICY`, and a `horizon_year` that must equal the parent plan's `horizon_year` exactly — a mismatch is refused with `ERR_HORIZON_YEAR_MISMATCH`, and that comparison is the last check performed on a scenario creation, after the pinned version and the ownership tests have both passed. The projection drivers follow: `base_households`, the household count in the plan's `base_year` taken from the demographic inventory, which must be greater than zero; `annual_household_growth_rate`, the compound annual household growth rate expressed as a decimal fraction between 0 and 0.2 inclusive, so a rate of 1.1 percent per year is supplied as 0.011; `job_growth_total`, the net new jobs expected over the horizon, taken from the employment inventory and at least zero; and `demolition_replacement_units`, the units that must be rebuilt to replace expected demolitions, also at least zero.

The pinned dataset must be a real land-use inventory of the same plan and it must be certified. A dataset of any other `inventory_type` is refused with `ERR_INVENTORY_TYPE_MISMATCH`; a dataset still in `DRAFT`, or already `SUPERSEDED`, is refused with `ERR_INVENTORY_NOT_CERTIFIED`. Uncertified acreage is never silently skipped or substituted. A dataset belonging to a different plan is an ownership violation and is refused with `ERR_CROSS_PLAN_LINK`. When the scenario is accepted it enters `DRAFT`, the pinned dataset's `referencing_scenario_count` is incremented by one and the dataset's `version` is incremented by one — which is exactly why a second scenario pinned to the same dataset must re-read it first.

**Land capacity.** The `method` chosen on the scenario selects the capacity variant, recorded on the scenario as `capacity_variant`: a `TREND` scenario is `GROSS_CAPACITY`, a `POLICY` scenario is `NET_CAPACITY`. Under `GROSS_CAPACITY`, `land_capacity_units` is the vacant acreage plus the underutilized acreage, multiplied by the allowed density per acre, and that single product is rounded half up to whole units. This is the optimistic reading: every vacant and underutilized acre counts at full allowed density, and infrastructure constraints, redevelopment realization and market softness are all ignored. Under `NET_CAPACITY` three discounts apply. The infrastructure-constrained acreage is first subtracted from the vacant acreage; to that is added one half of the underutilized acreage, because only half of the redevelopable land is expected to be realized within the horizon; the resulting acreage is multiplied by the allowed density per acre; and the whole product is then discounted to 85 percent to reflect market softness before being rounded half up to whole units. Rounding happens once, at the very end — intermediate acreage figures are never rounded. On a reference inventory of 400 vacant acres, 250 underutilized acres, 60 infrastructure-constrained acres and 18 allowed units per acre, `GROSS_CAPACITY` yields 11700 units while `NET_CAPACITY` yields 7115: the same inventory row, two legitimately different capacities.

**Projected demand.** `projected_demand_units` is computed from the scenario's own inputs plus the plan's `base_year`, so it never depends on the order in which inventories were certified. First take the number of horizon years, which is the scenario's `horizon_year` less the plan's `base_year`. Household growth is `base_households` compounded at `annual_household_growth_rate` over that many years, less `base_households` — that is, the growth increment rather than the ending total. Job-driven household demand is `job_growth_total` divided by 1.45, the assumed number of jobs supported per household. A `TREND` scenario takes household growth alone as its demand driver; a `POLICY` scenario takes whichever of the two pressures is larger, household growth or job-driven households. The chosen driver is then added to `demolition_replacement_units`, the sum is multiplied by 1.05 to allow a five percent vacancy margin, and only that final figure is rounded half up to whole units. Household growth, job-driven households and the selected driver are all carried at full precision; rounding any of them first changes the answer. Finally `capacity_gap_units` records the demand that the land cannot absorb — the projected demand less the land capacity, floored at zero so it is never negative. The gap is informational: a positive gap does not by itself block the state filing.

**Adoption.** A `PlanningDirector` adopts one scenario as the plan's official projection, moving it `DRAFT → ADOPTED`. A scenario already `ADOPTED` or `SUPERSEDED` cannot be adopted (`ERR_SCENARIO_NOT_DRAFT`), and the plan must not yet be adopted. Adoption also requires the existing-conditions record to be complete: the plan must hold a `CERTIFIED` dataset for each of `DEMOGRAPHIC`, `HOUSING`, `EMPLOYMENT` and `LAND_USE`, and a plan missing any of the four is refused with `ERR_INVENTORY_SET_INCOMPLETE`. On success the previously adopted scenario of that plan, if there is one, moves `ADOPTED → SUPERSEDED` with its `version` incremented; the plan's `adopted_scenario_id` is pointed at the newly adopted scenario; all four of the plan's income-tier housing allocations are recomputed by the capacity waterfall of section 3.3; the plan's `housing_shortfall_total` is refreshed to the sum of the tiers' shortfalls; the plan's `compliance_posture` is recomputed, which is what finally lifts the `CAPACITY_HOLD` a plan is born with, provided no tier is short and no higher-precedence hold applies; and both the plan's `version` and the scenario's `version` are incremented by one.

### 3.3. State Housing Allocations and the Capacity Waterfall

The state, acting through a `StateReviewer`, assigns each plan a housing allocation broken out by income tier. One allocation row is recorded per tier, naming the `plan_update_id`, the `income_tier` — one of `VERY_LOW`, `LOW`, `MODERATE` or `ABOVE_MODERATE` — the `assigned_units` the state expects that tier to accommodate over the cycle, which must be zero or greater, and the `cycle_deadline`, the instant by which the plan must accommodate the allocation. A tier may be assigned only once per plan; a second row for the same tier is refused with `ERR_DUPLICATE_ALLOCATION_TIER`.

Whether a plan can actually accommodate what the state assigned is decided by a **capacity waterfall** that runs over all of the plan's allocation rows. It is re-run in two situations: when a new allocation row is recorded, and when a growth scenario is adopted. In both cases the whole set of tiers is recomputed from scratch, never incrementally patched.

The waterfall proceeds as follows. The capacity pool is the `land_capacity_units` of the scenario named by the plan's `adopted_scenario_id`; when the plan has no adopted scenario yet, the pool is zero, and consequently every tier is fully short. Only the adopted scenario contributes — scenarios still in `DRAFT` and scenarios already `SUPERSEDED` contribute nothing, even if their capacity figures are larger. The tiers are then visited in the fixed statutory order `VERY_LOW`, then `LOW`, then `MODERATE`, then `ABOVE_MODERATE`. This order is never derived from the data: it is not creation order and it is not a sort by assigned units. A running carryover starts at zero. For each tier in that order:

- If the plan has no allocation row for that tier, the tier is skipped: it contributes nothing to the shortfall and it passes the running carryover downstream untouched.
- Otherwise, the tier's `tier_capacity_units` is the pool multiplied by that tier's suitability share, rounded half up to whole units. The shares are 30 percent for `VERY_LOW`, 20 percent for `LOW`, 20 percent for `MODERATE` and 30 percent for `ABOVE_MODERATE`.
- The tier's `carryover_in_units` is the running carryover as it stood on entry to this tier.
- The units available to the tier are its `tier_capacity_units` plus its `carryover_in_units`.
- The tier's `accommodated_units` is the smaller of its `assigned_units` and the units available to it.
- The tier's `shortfall_units` is its `assigned_units` less its `accommodated_units`.
- The running carryover for the next tier becomes the units available to this tier less the units it accommodated — unused capacity flows down the waterfall rather than being discarded.

The plan's `housing_shortfall_total` is then the sum of `shortfall_units` across the four tiers, counting zero for any tier that has no row.

The rounding order here is pinned and it is not merely cosmetic: each tier's share is rounded to whole units **first**, and the waterfall then consumes the rounded figure. The competing reading — sum the exact shares and round the total — diverges whenever a share lands on a half unit. With a pool of 7115 units, per-tier rounding yields 2135, 1423, 1423 and 2135, which is 7116 allocated units in total, one more than the pool itself; under that pinned reading the `ABOVE_MODERATE` tier can accommodate 2781 units where the alternative reading would have allowed only 2780.

### 3.4. Drafting the Statutory Elements and the Director Review Loop

Five statutory elements make up the plan, and `PlanningStaff` draft each of them: `LAND_USE`, `HOUSING`, `TRANSPORTATION`, `PARKS` and `INFRASTRUCTURE`. Creating one carries the `plan_update_id`, the `element_type`, a chapter `title` of 1 to 160 characters as it will appear in the published plan, a `draft_body` of 1 to 20000 characters of narrative, and optionally an initial `policy_count`, the number of numbered policies the chapter contains, which defaults to 0 and can never be negative. Drafting is only possible while the plan is in `DRAFTING` or `STATE_DEFICIENT`; any other plan status is refused with `ERR_PLAN_NOT_DRAFTING`. A plan holds at most one element of each type, so a duplicate `element_type` is refused with `ERR_DUPLICATE_ELEMENT_TYPE`. A new element is stamped with the author's `X-User-ID` in `authored_by_user_id` and starts in `DRAFT` with `consistency_status` at `PENDING` and `revision_round` at zero.

Element content is revised in place. A revision may replace the `title`, the `draft_body` and the `policy_count`, in any combination, and each revision increments the element's `version`. Revising an element that is already in `DRAFT` is a self-loop that changes nothing but content; revising one in `REVISION_REQUESTED` moves it `REVISION_REQUESTED → DRAFT`, which is how the review loop closes. An element in `IN_REVIEW`, `APPROVED` or `ADOPTED` cannot be revised at all and the attempt is refused with `ERR_ELEMENT_NOT_AMENDABLE`. An element in `ESCALATED` is a special case: it moves `ESCALATED → DRAFT`, but only a `PlanningDirector` may perform that revision, and the director's override additionally resets `revision_round` back to zero. `PlanningStaff` attempting to revise an `ESCALATED` element are refused with `ERR_ESCALATION_OVERRIDE_REQUIRED`, which is checked at the very bottom of the validation ladder — after the element's status has already been found revisable.

Submitting a drafted element for review moves it `DRAFT → IN_REVIEW` and increments its `version`. An element in any other status is refused with `ERR_ELEMENT_NOT_DRAFT`, and an element that carries no numbered policies at all — a `policy_count` of zero — is refused with `ERR_ELEMENT_HAS_NO_POLICIES` on the content-readiness rung.

The review decision belongs to a `PlanningDirector` and carries a `decision` of either `APPROVE` or `REQUEST_REVISION`, plus an optional `review_note`. The element must be `IN_REVIEW`, otherwise `ERR_ELEMENT_NOT_IN_REVIEW`. Four further checks then apply, and their relative order matters because a request can trip more than one. First, on the state rung: when the element under review is the `HOUSING` element, the plan must already have an adopted projection — its `adopted_scenario_id` must be set and the scenario it names must be in status `ADOPTED` — because a housing element cannot be blessed without the capacity numbers it is written against; failing that, the decision is refused with `ERR_SCENARIO_NOT_ADOPTED`. Second, the segregation-of-duties comparison: a director whose `X-User-ID` matches the element's `authored_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Third, and only for an approval, every consistency link whose source is this element must already be `CLEARED`; if any is still `OPEN` or `STALE`, the approval is refused with `ERR_CONSISTENCY_UNRESOLVED`.

An approval moves the element `IN_REVIEW → APPROVED`, stamps `reviewed_by_user_id` with the deciding director's identifier, sets the element's `consistency_status` to `CLEARED`, and increments the element's `version`. It also reaches the plan: `required_elements_complete_count` is recomputed as the number of distinct element types now standing in `APPROVED` or `ADOPTED`, `compliance_posture` is recomputed, and the plan's `version` is incremented by one.

A revision request is where the loop lives, and it is bounded. The maximum number of revision rounds an element may absorb is three. A revision request that would leave `revision_round` below three moves the element `IN_REVIEW → REVISION_REQUESTED`, increments `revision_round` by one and stamps `reviewed_by_user_id`. The third such request behaves differently: when `revision_round` stands at exactly two, so that this decision would be the third, the element instead moves `IN_REVIEW → ESCALATED`, its `revision_round` is set to three and `reviewed_by_user_id` is stamped. An escalated element is out of the staff's hands until a director exercises the override described above. In both branches the element's `version` is incremented by one, and in both branches the segregation-of-duties comparison applies exactly as it does to an approval.

Two further element transitions are driven entirely by the system rather than by a reviewer. An element standing in `APPROVED` moves `APPROVED → REVISION_REQUESTED` — with `revision_round` incremented by one, `consistency_status` set to `STALE` and its `version` incremented — when the state returns a deficient determination naming that element's type, or when the council denies the plan; both cascades are described in sections 3.8 and 3.9. And an element standing in `APPROVED` moves `APPROVED → ADOPTED`, with its `version` incremented, when the council adopts the plan. `ADOPTED` is terminal for an element.

### 3.5. The Internal-Consistency Network

State law requires the elements of a plan to be internally consistent, and this service models that requirement explicitly as a directed graph. `PlanningStaff` declare a dependency by naming a `source_element_id` — the dependent element, whose policies rely on another — a `target_element_id`, the element depended upon, and a `dependency_type` drawn from `POLICY_ALIGNMENT`, `CAPACITY_ASSUMPTION`, `FUNDING_ASSUMPTION` and `LEVEL_OF_SERVICE`. Both ids must resolve to existing elements, otherwise `ERR_ELEMENT_NOT_FOUND`; both elements must belong to the same plan, otherwise `ERR_CROSS_PLAN_LINK`; and that plan must not already be adopted.

Three graph-integrity rules then apply, in this order. An element may not depend on itself, so a payload whose two ids are equal is refused with `ERR_SELF_CONSISTENCY_LINK` — the only 422 in this group. The same ordered pair may not be declared twice, so a repeat is refused with `ERR_DUPLICATE_CONSISTENCY_LINK`. And the new edge may not close a directed cycle: walking the plan's existing links in the source-to-target direction, counting every link whose status is `OPEN`, `CLEARED` or `STALE`, the proposed edge must not create a path from the target back to the source. A cycle is refused with `ERR_CONSISTENCY_CYCLE`.

A newly declared link enters `OPEN`. Its source element's `consistency_status` is set to `PENDING` if it had previously reached `CLEARED`, the plan's `open_consistency_link_count` is incremented by one, the plan's `compliance_posture` is recomputed — which, with at least one open link, necessarily yields `CONSISTENCY_HOLD` unless the plan is already frozen at the state — and the plan's `version` is incremented by one. Declaring a dependency is therefore never a free act: it immediately withdraws the plan's eligibility to hold hearings until the dependency is reconciled.

Reconciliation is a `PlanningDirector` act and carries a `reconciliation_note` explaining how the two elements were brought into alignment. A link may be reconciled from either `OPEN` or `STALE`, and the two edges behave identically: `OPEN → CLEARED` and `STALE → CLEARED` have exactly the same effect set. A link already `CLEARED` is refused with `ERR_LINK_ALREADY_CLEARED`. The target element must additionally be far enough along to be relied upon — its status must be `IN_REVIEW`, `APPROVED` or `ADOPTED` — otherwise the attempt is refused with `ERR_TARGET_ELEMENT_NOT_REVIEWABLE`. On success the link records the supplied note, stamps `reconciled_by_user_id` with the reconciling director's identifier and clears `staled_by_amendment_id` back to null. The source element's `consistency_status` becomes `CLEARED` only if every link sourced from it is now `CLEARED`; if any sibling link is still outstanding, the source element's status is left unchanged. The plan's `open_consistency_link_count` and `compliance_posture` are then recomputed, and if the recomputed posture is `CLEAR`, every hearing of that plan sitting in `BLOCKED` returns to `SCHEDULED`. The plan's `version` is incremented by one.

Two system-driven edges take a cleared link back out of alignment. When an amendment is adopted against an element, every `CLEARED` link pointing **at** that element moves `CLEARED → STALE`, recording the adopting amendment's id in `staled_by_amendment_id`, setting the link's source element's `consistency_status` to `STALE` and incrementing the link's `version`. When instead the state returns a deficient determination or the council denies the plan, and the demotion reaches this link's target element, the link moves `CLEARED → OPEN`, its `reconciled_by_user_id` and `reconciliation_note` are both wiped back to null, and its `version` is incremented. A third system edge undoes the first: rescinding the amendment that staled a link moves it `STALE → CLEARED`, clears `staled_by_amendment_id` back to null, recomputes the source element's `consistency_status` and increments the link's `version`. A consistency link has no terminal state — it can be walked around the `CLEARED → STALE → CLEARED` loop indefinitely as the plan is amended and re-amended.

### 3.6. Public Engagement, Venue Booking and the Equity Share

Public engagement is where the plan earns its legitimacy, and the system measures it rather than merely recording it. `PlanningStaff` first register the facilities they will use. A venue carries a public `name` of 1 to 120 characters, a `seated_capacity` greater than zero, a `turnover_buffer_minutes` value between 0 and 240 inclusive that defaults to 0 and represents the setup and teardown time the room needs on both sides of every booking, an `ada_accessible` flag that defaults to true and records whether the facility is step-free, and a `transit_served` flag that defaults to false and records whether the facility sits within 400 metres of a transit stop. Venues are pure configuration: once registered they are never edited.

Activities are then scheduled against the plan. An activity names the `plan_update_id`, an `activity_type` of `WORKSHOP`, `SURVEY` or `TARGETED_OUTREACH`, a public `title` of 1 to 160 characters, a `start_at` and an `end_at` that must be strictly later than the start, and an optional `interpretation_offered` flag defaulting to false that records whether live interpretation was on offer. A workshop and a targeted-outreach session both occupy a room and must therefore carry a `venue_id`; a survey occupies no room and must not carry one. Getting that pairing wrong is a schema violation. A targeted-outreach session carries an additional equity requirement: its venue must be both `transit_served` and `ada_accessible`, and a booking at a venue failing either test is refused with `ERR_VENUE_NOT_EQUITY_ELIGIBLE`. Note that this equity test sits well below the venue occupancy test on the validation ladder, so a targeted-outreach booking that is both double-booked and ineligible reports the occupancy conflict.

**Venue occupancy** is evaluated as a half-open interval expanded symmetrically by the venue's turnover buffer. The proposed activity conflicts with an existing activity at the same venue whose status is `SCHEDULED` or `COMPLETED` when the proposed `start_at` moved earlier by the buffer falls strictly before the existing activity's `end_at`, and at the same time the proposed `end_at` moved later by the buffer falls strictly after the existing activity's `start_at`. Both conditions must hold for a conflict, which is reported as `ERR_VENUE_TIME_CONFLICT`. The consequence of the strict comparisons is worth spelling out: at a venue whose `turnover_buffer_minutes` is 0, an activity starting at the exact instant an earlier one ended is allowed, because neither comparison is satisfied at the boundary; at a venue with any positive buffer, that same back-to-back pair conflicts. Activities in `CANCELLED` release their interval entirely and never conflict with anything.

An accepted activity enters `SCHEDULED` with `record_count`, `underrepresented_record_count`, `total_weighted_count`, `underrepresented_weighted_count` and `equity_share_pct` all at zero, and with its `weighting_variant` fixed at creation: `OUTREACH_WEIGHTED` for a `TARGETED_OUTREACH` session, `STANDARD` for a workshop or a survey.

Participation is captured one pseudonymous record at a time — a survey response, a workshop sign-in or an outreach contact — against an activity that is still `SCHEDULED`; attaching a record to an activity that has been completed or cancelled is refused with `ERR_ACTIVITY_NOT_SCHEDULED`. Each record names the `activity_id`, a `respondent_ref` of 1 to 64 characters serving as a stable pseudonymous handle, a self-reported `demographic_group` of `GENERAL`, `LOW_INCOME`, `LIMITED_ENGLISH`, `YOUTH`, `SENIOR`, `DISABILITY` or `RENTER`, a `census_tract` of 4 to 12 characters recording where the respondent lives for geographic equity reporting, an optional `interpreter_used` flag defaulting to false, and an optional verbatim `comment_text` that defaults to null. The same `respondent_ref` may not be captured twice at one activity; a repeat is refused with `ERR_DUPLICATE_PARTICIPATION`.

Each record is scored as it is captured. Its `is_underrepresented` flag is derived by the server and any client-supplied value is ignored: it is true when the respondent's `demographic_group` is `LOW_INCOME`, `LIMITED_ENGLISH`, `YOUTH`, `DISABILITY` or `RENTER`. `GENERAL` and `SENIOR` are deliberately **not** underrepresented groups. The record's `weight` is 2.0 when the parent activity's `weighting_variant` is `OUTREACH_WEIGHTED` and the respondent's `interpreter_used` is true, and 1.0 in every other case — an interpreter changes nothing at a workshop or a survey. Capturing the record then updates the activity in one step: `record_count` rises by one, `underrepresented_record_count` rises by one if the record is flagged as underrepresented, `total_weighted_count` rises by the record's weight, `underrepresented_weighted_count` rises by that same weight if the record is flagged, and the activity's `version` is incremented by one. All weight sums carry one decimal place, rounded half up.

Completing an activity is what folds it into the plan's equity record, and it is guarded three ways: the activity must be `SCHEDULED`, the logical clock must have reached the activity's `end_at` — an activity cannot be closed before it has happened, otherwise `ERR_ACTIVITY_NOT_ENDED` — and at least one participation record must have been captured, otherwise `ERR_NO_PARTICIPATION_RECORDS`. The completion then fires a five-stage cascade. First, the activity's own `equity_share_pct` is computed as one hundred times its `underrepresented_weighted_count` divided by its `total_weighted_count`, rounded half up to one decimal place, with 0.0 used when the weighted total is zero. Second, the plan's `participation_weight_total` is increased by the activity's `total_weighted_count` and its `underrepresented_weight_total` by the activity's `underrepresented_weighted_count`. Third, the plan's own `equity_share_pct` is recomputed. Fourth, the plan's `compliance_posture` is recomputed, so an `EQUITY_HOLD` lifts to `CLEAR` exactly when the new plan-wide share reaches 40.0 percent and no higher-precedence hold applies. Fifth, if that recomputed posture is `CLEAR`, every hearing of the plan sitting in `BLOCKED` returns to `SCHEDULED`. The activity moves `SCHEDULED → COMPLETED`, and both its `version` and the plan's `version` are incremented by one.

The weighting variant is what makes the activity-level share interesting. Under `STANDARD`, every record weighs 1.0, so the share collapses to a head count: four underrepresented respondents out of ten records gives exactly 40.0. Under `OUTREACH_WEIGHTED`, interpreter-using respondents count double, so five records that would give 60.0 under standard weighting — three of five underrepresented — instead give 71.4 when the two interpreter-using respondents are both underrepresented, because the arithmetic is 5.0 of 7.0 weighted units.

The plan-wide share is an aggregate over **completed activities only**. The plan's `participation_weight_total` is the sum of `total_weighted_count` across the plan's activities in status `COMPLETED`, its `underrepresented_weight_total` the corresponding sum of `underrepresented_weighted_count`, and its `equity_share_pct` is one hundred times the second divided by the first, rounded half up to one decimal place, or 0.0 when the denominator is zero. Activities still `SCHEDULED` have not been held and are excluded; activities `CANCELLED` have been withdrawn from the engagement record and are excluded too. The window is unbounded in time — every completed activity of the plan counts regardless of when it took place — and because no ordering is involved, no tie-break arises. Two completed workshops of ten records each, one with four and one with three underrepresented respondents, give 7.0 of 20.0 weighted units, or 35.0 percent: below the 40.0 threshold even though the first workshop on its own sat exactly at it.

Cancellation is available from both `SCHEDULED` and `COMPLETED` and carries an optional `cancellation_reason`. An activity already `CANCELLED` cannot be cancelled again and is refused with `ERR_ACTIVITY_CLOSED`. Cancelling from `SCHEDULED` releases the venue interval, so the room becomes bookable again, and changes no plan-level counter at all — a scheduled activity had never contributed any weight. Cancelling from `COMPLETED` is a compensation: it requires that the plan not yet be adopted, it debits the plan's `participation_weight_total` by the activity's `total_weighted_count` and its `underrepresented_weight_total` by the activity's `underrepresented_weighted_count`, recomputes the plan's `equity_share_pct` and then its `compliance_posture`, and releases the venue interval. Both the activity's `version` and the plan's `version` are incremented. After that compensation the weighted-participation conservation invariant of section 2.10 must hold exactly: completing an activity and then cancelling it returns all three plan figures to the values they held before the completion, to the tenth.

### 3.7. Environmental Review, Alternatives and the Preferred-Alternative Selector

The environmental review of the plan is prepared by an `EnvironmentalConsultant`. Opening one names the `plan_update_id`, a `document_type` of either `EIR` or `NEGATIVE_DECLARATION`, and a `title` of 1 to 160 characters. The plan must not already be adopted. A new review enters `DRAFT` with `alternative_count` at zero and `comment_period_days`, `circulated_at`, `comment_period_ends_at`, `preferred_alternative_id` and `certified_at` all null.

Alternatives are added while the review is still `DRAFT`; adding one to a review that has been circulated, certified or superseded is refused with `ERR_REVIEW_NOT_DRAFT`. An alternative names the `environmental_review_id`, a `label` of 1 to 80 characters such as "Transit-Focused Growth", and four impact indices, each between 0 and 100 inclusive and each oriented so that a higher number is worse: `traffic_vmt_index` for vehicle-miles-travelled impact, `ghg_index` for greenhouse gas, `habitat_index` for biological and habitat impact, and `water_index` for water supply and quality. Adding an alternative increments the parent review's `alternative_count` by one and its `version` by one, and the new alternative enters `EVALUATED`.

Impact scoring happens at creation and proceeds in three pinned steps. First, `raw_impact_score` is the weighted sum of the four indices — 35 percent of the traffic index, 25 percent of the greenhouse-gas index, 20 percent of the habitat index and 20 percent of the water index, weights that sum to exactly one — rounded half up to two decimal places. Second, `mitigation_credit` is looked up from a tier keyed **on the raw score and never on the net score**: a raw score of 70 or more earns a credit of 15 percent of the raw score, a raw score of at least 50 but below 70 earns 10 percent of the raw score, and anything below 50 earns no credit at all, that is, 0.00. The credit is itself rounded half up to two decimal places. Third, `net_impact_score` is the raw score less the credit, again rounded half up to two decimal places. The three roundings are independent and applied in that order. An alternative with all four indices at 70 illustrates why the tier key matters: its raw score is 70.00, which lands in the high tier, giving a credit of 10.50 and a net score of 59.50 — had the tier been keyed on the net score, the mid tier would have applied instead and produced a credit of 7.00 and a net of 63.00.

Circulation releases the document for public comment and is the consultant's act. The review must be in `DRAFT`. Two further checks apply, and their order is the ladder's, not the intuitive one: the proposed comment window is tested for overlap **before** the alternatives are counted. The window runs from the current logical clock instant to that instant plus the comment period, and it is compared as a closed interval against the window of every other review of the same plan whose status is `CIRCULATED` or `CERTIFIED`, that window running from the other review's `circulated_at` to its `comment_period_ends_at`. An overlap exists when the new window's start is not later than the other window's end and the new window's end is not earlier than the other window's start; the rejection is `ERR_REVIEW_WINDOW_OVERLAP`. Only then is the content-readiness rule applied: a review must carry at least two alternatives before it may circulate, and a review carrying fewer is refused with `ERR_INSUFFICIENT_ALTERNATIVES`. On success the review moves `DRAFT → CIRCULATED`, `circulated_at` is stamped with the logical clock instant, `comment_period_days` is stamped with the statutory period — 45 days for an `EIR` and 30 days for a `NEGATIVE_DECLARATION` — `comment_period_ends_at` is computed as `circulated_at` advanced by that many days, and the review's `version` is incremented by one.

Selecting the preferred alternative is a **server-side** decision: the consultant asks for a selection and supplies no alternative id whatsoever. The review must be `CIRCULATED`, otherwise `ERR_REVIEW_NOT_CIRCULATED`. The candidate pool is every alternative of that review whose status is `EVALUATED`; the incumbent in `PREFERRED` and anything already `SUPERSEDED` are excluded, which means re-running the selector after a prior selection deliberately picks the best of the remaining evaluated alternatives and demotes the incumbent. If the candidate pool is empty the request is refused with `ERR_NO_ELIGIBLE_ALTERNATIVE` and nothing whatsoever is mutated. Otherwise the candidates are ordered by `net_impact_score` ascending, because the lowest environmental impact wins; ties are broken by `raw_impact_score` ascending; and any remaining tie is broken by `created_at` ascending, the earliest-created alternative winning. The randomly minted `id` never participates in the ordering. Comparisons use the stored two-decimal score values as they are and never re-round them. The winner moves `EVALUATED → PREFERRED` with its `version` incremented, any incumbent alternative in `PREFERRED` moves `PREFERRED → SUPERSEDED` with its `version` incremented, and the review's `preferred_alternative_id` is pointed at the winner while the review's `version` is incremented by one.

Certification of the environmental document belongs to the `PlanningDirector`, not to the consultant who wrote it. The review must be `CIRCULATED`, otherwise `ERR_REVIEW_NOT_CIRCULATED`. The comment period must have elapsed — the logical clock must have reached `comment_period_ends_at` — otherwise the attempt is refused with `ERR_COMMENT_PERIOD_OPEN`. And a preferred alternative must already have been selected, so a review whose `preferred_alternative_id` is still null is refused with `ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED`, a check that sits below the clock gate on the ladder. On success the review moves `CIRCULATED → CERTIFIED`, `certified_at` is stamped with the logical clock instant, and every other environmental review of the same plan standing in `DRAFT`, `CIRCULATED` or `CERTIFIED` moves to `SUPERSEDED` with its `version` incremented — a plan carries exactly one live environmental document. Both the review's `version` and the plan's `version` are incremented by one.

### 3.8. Filing with the State and the Determination Cascade

Filing the plan with the state is the `PlanningDirector`'s act and may carry an optional `submission_note`. It is available from two plan statuses only, `DRAFTING` for a first filing and `STATE_DEFICIENT` for a resubmission; from any other status it is refused with `ERR_PLAN_NOT_DRAFTING`. The filing runs the complete state-mandate checklist, and because a half-finished plan can fail several of these at once, the order in which they are evaluated is part of the contract. They are evaluated in exactly this sequence:

1. **Required elements.** The plan must carry an element in status `APPROVED` or `ADOPTED` for each of the five statutory types `LAND_USE`, `HOUSING`, `TRANSPORTATION`, `PARKS` and `INFRASTRUCTURE` — that is, `required_elements_complete_count` must be 5. Otherwise `ERR_REQUIRED_ELEMENT_MISSING`.
2. **Housing allocation completeness.** An allocation row must exist for each of the four income tiers `VERY_LOW`, `LOW`, `MODERATE` and `ABOVE_MODERATE`. Otherwise `ERR_ALLOCATION_INCOMPLETE`.
3. **Internal consistency.** The plan's `open_consistency_link_count` must be exactly zero — no link of the plan may still be `OPEN` or `STALE`. Otherwise `ERR_CONSISTENCY_UNRESOLVED`.
4. **Environmental review.** At least one environmental review of the plan must stand in `CIRCULATED` or `CERTIFIED`; a document still in `DRAFT` is not enough at filing time. Otherwise `ERR_ENVIRONMENTAL_REVIEW_MISSING`.
5. **Land capacity adequacy.** The plan's `housing_shortfall_total` must be exactly zero, meaning every tier's `assigned_units` is fully accommodated by the adopted scenario's capacity waterfall. Otherwise `ERR_HOUSING_SHORTFALL`.
6. **Equity target.** The plan's `equity_share_pct` must be at least the minimum plan-wide underrepresented share of 40.0 percent, compared inclusively so that exactly 40.0 passes. Otherwise `ERR_EQUITY_TARGET_NOT_MET`.
7. **Resubmission ceiling.** On a resubmission only, the plan's `resubmission_count` must still be below the ceiling of two. Otherwise `ERR_RESUBMISSION_LIMIT_EXCEEDED`.

The placement of the resubmission ceiling at the bottom of that list is deliberate and testable: a plan that has exhausted its resubmissions **and** is missing a required element reports the missing element, not the exhausted ceiling.

A successful first filing moves the plan `DRAFTING → STATE_SUBMITTED`, sets `state_review_status` to `SUBMITTED`, wipes `state_findings` back to null, recomputes `compliance_posture` and increments the plan's `version` by one. A successful resubmission moves the plan `STATE_DEFICIENT → STATE_SUBMITTED`, increments `resubmission_count` by one, sets `state_review_status` to `SUBMITTED`, and recomputes `compliance_posture` — which is where a `FROZEN` posture finally lifts, because `state_review_status` is no longer `DEFICIENT`. If that recomputed posture is `CLEAR`, every hearing of the plan sitting in `BLOCKED` returns to `SCHEDULED`. The plan's `version` is incremented by one. `resubmission_count` counts submissions after the first, so with a ceiling of two a plan can be filed at most three times in total.

The determination comes back from a `StateReviewer` and carries a `determination` of either `CERTIFIED` or `DEFICIENT`, the free-text `findings` to be recorded on the plan, and — for a deficient determination — `deficient_element_types`, which must be a non-empty subset of the five statutory element types. That subset is validated as part of the request shape, so a malformed or empty list is reported as a schema violation **before** the plan's status is examined. The plan's `state_review_status` must be `SUBMITTED`; a determination against a plan that is not awaiting one is refused with `ERR_PLAN_NOT_SUBMITTED`.

A `CERTIFIED` determination moves the plan `STATE_SUBMITTED → STATE_CERTIFIED`, sets `state_review_status` to `CERTIFIED`, records the supplied `findings` in `state_findings`, and recomputes `compliance_posture` — at which point a `FROZEN` posture can no longer apply, since the freeze rule keys on a deficient state review. If the recomputed posture is `CLEAR`, every hearing of the plan sitting in `BLOCKED` returns to `SCHEDULED`. The plan's `version` is incremented by one. Certification is what unlocks the adoption hearings.

A `DEFICIENT` determination moves the plan `STATE_SUBMITTED → STATE_DEFICIENT` and fires the deepest cascade in the system, five links long, each caused by the one before it:

1. The plan's `state_review_status` becomes `DEFICIENT` and the supplied `findings` are recorded in `state_findings`.
2. Because the state review is now deficient, every element of the plan whose `element_type` appears in `deficient_element_types` and whose status is `APPROVED` moves `APPROVED → REVISION_REQUESTED`, has its `revision_round` incremented by one, has its `consistency_status` set to `STALE`, and has its `version` incremented.
3. Because those elements were demoted, every consistency link whose target is one of them and whose status is `CLEARED` moves `CLEARED → OPEN`, with `reconciled_by_user_id` and `reconciliation_note` wiped to null and its `version` incremented; the source element of each such link has its `consistency_status` set to `STALE`.
4. Because links were reopened, the plan's `open_consistency_link_count` and `required_elements_complete_count` are recomputed and then `compliance_posture` is recomputed. The result is `FROZEN`: the deficiency rule sits at the top of the posture ladder and dominates the consistency hold that the reopened links would otherwise have produced.
5. Because the posture left `CLEAR`, every hearing of the plan sitting in `SCHEDULED` moves `SCHEDULED → BLOCKED`, with each hearing's `version` incremented.

The plan's `version` is incremented by one. A frozen plan cannot open a hearing and cannot be given a recommend or adopt outcome; the only route forward is to revise the demoted elements, re-reconcile the reopened links and file again.

### 3.9. Adoption Hearings, Amendment Tracking and the Implementation Program

Hearings are the clerk's domain. Scheduling one names the `plan_update_id`, a `body_type` of `COMMISSION` or `COUNCIL`, a `scheduled_start` and a `scheduled_end` strictly after it, and a `notice_published_at` recording when the public notice went out. A hearing can only be put on the calendar once the state has certified the plan: the plan's status must be `STATE_CERTIFIED` or `COMMISSION_RECOMMENDED`, and anything earlier is refused with `ERR_PLAN_NOT_CERTIFIED`.

Four calendar rules then apply, in ladder order. First, **slot occupancy**, compared as a closed interval with no buffer: the new hearing conflicts with an existing hearing of the same `plan_update_id` and the same `body_type` whose status is `SCHEDULED`, `BLOCKED` or `OPEN` when the new `scheduled_start` is not later than the existing `scheduled_end` and the new `scheduled_end` is not earlier than the existing `scheduled_start`. Touching endpoints *are* a conflict here — the exact opposite of the venue rule in section 3.6, where a zero buffer makes adjacency legal — and hearings of the other body never conflict with each other. The rejection is `ERR_HEARING_SLOT_CONFLICT`. Second, the **daily cap**: at most two hearings of the same plan and the same body may have their `scheduled_start` fall on the same UTC calendar date, and that count includes hearings in every status — `SCHEDULED`, `BLOCKED`, `OPEN`, `CONTINUED`, `RECOMMENDED`, `ADOPTED_OUT` and `DENIED` — so a concluded hearing still consumes its slot for the day. Exceeding it is `ERR_HEARING_DAILY_CAP_EXCEEDED`. Third, the **public notice lead time**: `notice_published_at` must fall no later than ten days before `scheduled_start`, and a shorter lead time is refused with `ERR_NOTICE_PERIOD_TOO_SHORT`, the only 422 among the calendar rules. Fourth and last, a **council prerequisite**: a `COUNCIL` hearing may only be scheduled once the plan has reached `COMMISSION_RECOMMENDED`, and an earlier attempt is refused with `ERR_COMMISSION_RECOMMENDATION_REQUIRED`.

A scheduled hearing enters `SCHEDULED` with `amendment_count` and `adopted_amendment_count` at zero and `outcome`, `opened_at` and `closed_at` all null. As described in section 2.9 it may be moved to `BLOCKED` and back to `SCHEDULED` purely by the plan's posture cascades, without any clerk action, each such move incrementing the hearing's `version`.

Gavelling a hearing in moves it `SCHEDULED → OPEN` and stamps `opened_at` with the logical clock instant, incrementing the hearing's `version`. Its guards fire in this order: the hearing must be `SCHEDULED`, so a hearing that has been blocked by the plan's posture — or already opened, continued or concluded — is refused with `ERR_HEARING_NOT_SCHEDULED`; the plan's `compliance_posture` must be `CLEAR`, otherwise `ERR_PLAN_POSTURE_BLOCKED`; the logical clock must have reached `scheduled_start`, otherwise `ERR_HEARING_NOT_YET_STARTED`; and for a `COUNCIL` hearing only, the plan must hold an environmental review in status `CERTIFIED`, otherwise `ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED`.

Recording the outcome carries an `outcome` of `CONTINUE`, `RECOMMEND`, `ADOPT` or `DENY` plus an optional `minutes_note`, and it is where the hearing forks into four terminal states with sharply divergent effects. In all four branches the hearing must be `OPEN`, otherwise `ERR_HEARING_NOT_OPEN`; in all four the `outcome` field is recorded on the hearing, `closed_at` is stamped with the logical clock instant, and the hearing's `version` is incremented by one.

- **`CONTINUE`** moves the hearing `OPEN → CONTINUED` and has no plan-level effect at all: the plan's status is unchanged and no counter moves. Any amendment of that hearing still standing in `PROPOSED` is left in `PROPOSED` and becomes permanently unresolvable, because the hearing is now terminal and amendments can only be adopted, withdrawn or rescinded while their hearing is `OPEN`.
- **`RECOMMEND`** moves the hearing `OPEN → RECOMMENDED` and advances the plan one step. It is legal only on a `COMMISSION` hearing; on a council hearing it is refused with `ERR_OUTCOME_NOT_VALID_FOR_BODY`. The plan must be in `STATE_CERTIFIED`, otherwise `ERR_PLAN_NOT_CERTIFIED`; the plan's posture must be `CLEAR`, otherwise `ERR_PLAN_POSTURE_BLOCKED`; the plan must hold a `CERTIFIED` environmental review, otherwise `ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED`; and no amendment of the hearing may still be `PROPOSED`, otherwise `ERR_UNRESOLVED_AMENDMENTS`. On success the plan moves `STATE_CERTIFIED → COMMISSION_RECOMMENDED` and the plan's `version` is incremented by one.
- **`ADOPT`** moves the hearing `OPEN → ADOPTED_OUT` and carries the heaviest effect set in the system. It is legal only on a `COUNCIL` hearing; on a commission hearing it is refused with `ERR_OUTCOME_NOT_VALID_FOR_BODY`. The plan must be in `COMMISSION_RECOMMENDED`, otherwise `ERR_PLAN_NOT_RECOMMENDED`; the plan's posture must be `CLEAR`, otherwise `ERR_PLAN_POSTURE_BLOCKED`; and no amendment of the hearing may still be `PROPOSED`, otherwise `ERR_UNRESOLVED_AMENDMENTS`. On success the plan moves `COMMISSION_RECOMMENDED → ADOPTED`, its `adopted_at` is stamped with the logical clock instant, every element of the plan standing in `APPROVED` moves `APPROVED → ADOPTED` with its `version` incremented, every implementation action of the plan standing in `PENDING` moves `PENDING → SCHEDULED` with its `due_at` stamped and its `version` incremented, and the plan's `version` is incremented by one. `ADOPTED` is terminal for the plan and locks its whole aggregate against further writes.
- **`DENY`** moves the hearing `OPEN → DENIED` and requires the plan to be in `STATE_CERTIFIED` or `COMMISSION_RECOMMENDED`. Its effect set diverges by body. On a `COMMISSION` hearing the plan's status is left unchanged, but every *other* hearing of that plan standing in `SCHEDULED` moves `SCHEDULED → BLOCKED` with its `version` incremented. On a `COUNCIL` hearing against a plan in `COMMISSION_RECOMMENDED` the plan is demoted all the way back: it moves `COMMISSION_RECOMMENDED → DRAFTING`, its `state_review_status` is reset to `NOT_SUBMITTED`, every element standing in `APPROVED` moves `APPROVED → REVISION_REQUESTED` with `revision_round` incremented by one, every consistency link whose status is `CLEARED` and whose source or target element was among those demoted moves `CLEARED → OPEN`, the plan's `open_consistency_link_count` and `required_elements_complete_count` are recomputed and its `compliance_posture` is recomputed to `CONSISTENCY_HOLD`, every remaining hearing of the plan standing in `SCHEDULED` moves `SCHEDULED → BLOCKED`, and the plan's `version` is incremented by one. A denied plan must be re-drafted, re-reconciled and filed with the state all over again.

Amendments are moved during an open hearing. Recording one names the `hearing_id`, the `target_element_id` of the element it modifies, a `summary` of 1 to 2000 characters describing the amendment as moved, a `policy_delta` between -50 and 50 inclusive giving the signed change to the element's numbered policy count, and the `expected_element_version` that pins the element as described in section 2.5. The hearing must be `OPEN`, otherwise `ERR_HEARING_NOT_OPEN`, and the target element must be standing in `APPROVED` — an element still being drafted or reviewed cannot be amended on the floor — otherwise `ERR_ELEMENT_NOT_AMENDABLE`. The version pin is checked next, then the ownership rule: an element belonging to a plan other than the hearing's plan is refused with `ERR_CROSS_PLAN_AMENDMENT`. On success the amendment enters `PROPOSED`, its `element_version_at_proposal` records the pinned version, `proposed_by_user_id` records the moving clerk's `X-User-ID`, `applied_policy_count` and `prior_element_status` are both null, the hearing's `amendment_count` is incremented by one and the hearing's `version` incremented; and the target element is **docketed**, meaning its `updated_at` is refreshed and its `version` is incremented by one even though its content has not changed. That docketing is what forces the next clerk to re-read the element.

Adopting an amendment requires the amendment to be `PROPOSED`, otherwise `ERR_AMENDMENT_NOT_PROPOSED`, and its hearing still `OPEN`, otherwise `ERR_HEARING_NOT_OPEN`. The clerk adopting must not be the clerk who moved it: a match between `X-User-ID` and `proposed_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Finally, the arithmetic must be sound — the element's `policy_count` plus the amendment's `policy_delta` must be zero or greater, otherwise `ERR_POLICY_COUNT_NEGATIVE`, a check that runs after the duties comparison. Adoption then fires a five-link cascade:

1. The target element's current `status` is captured into the amendment's `prior_element_status`, the amendment's `policy_delta` is added to the element's `policy_count`, the resulting count is recorded on the amendment as `applied_policy_count`, the element's `consistency_status` is set to `STALE`, and the element's `version` is incremented by one.
2. Because the element's text moved, every consistency link whose target is that element and whose status is `CLEARED` moves `CLEARED → STALE`, recording this amendment's id in `staled_by_amendment_id` and incrementing the link's `version`.
3. Because those links went stale, the source element of each of them has its `consistency_status` set to `STALE`.
4. Because links are once again outstanding, the plan's `open_consistency_link_count` is recomputed and its `compliance_posture` is recomputed to `CONSISTENCY_HOLD`.
5. Because the posture left `CLEAR`, every hearing of the plan standing in `SCHEDULED` moves `SCHEDULED → BLOCKED`, with each hearing's `version` incremented.

The amendment moves `PROPOSED → ADOPTED`, the hearing's `adopted_amendment_count` is incremented by one, and both the amendment's `version` and the plan's `version` are incremented by one. Note the deliberate consequence: adopting an amendment on the floor blocks the plan's remaining hearings, so the links it staled must be reconciled before the plan can be recommended or adopted.

Withdrawal is the cheap exit. It carries an optional `withdrawal_reason`, requires the amendment to be `PROPOSED` and its hearing to be `OPEN`, and moves the amendment `PROPOSED → WITHDRAWN` while incrementing only the amendment's `version`. No element field and no plan field changes; in particular the element's `policy_count` is untouched, because a withdrawn amendment was never applied.

Rescission is the expensive exit, and it is a true compensation. It carries a mandatory `rescission_reason`, requires the amendment to be `ADOPTED` — otherwise `ERR_AMENDMENT_NOT_ADOPTED` — and requires its hearing to be still `OPEN`, so an amendment can only be undone during the same sitting. It moves the amendment `ADOPTED → RESCINDED` and unwinds the adoption cascade link by link:

1. The amendment's `policy_delta` is subtracted from the target element's `policy_count`, the element's `status` is restored to the amendment's recorded `prior_element_status`, and the element's `consistency_status` is recomputed to `CLEARED` when every consistency link sourced from that element is `CLEARED` — which is vacuously the case when the element sources no links at all — and to `PENDING` otherwise.
2. Because the element's text is restored, every consistency link carrying this amendment's id in `staled_by_amendment_id` moves `STALE → CLEARED` and has `staled_by_amendment_id` wiped back to null.
3. Because those links cleared, the source element of each of them has its `consistency_status` recomputed to `CLEARED` when all of its own links are now `CLEARED`.
4. Because the link population changed, the plan's `open_consistency_link_count` and `compliance_posture` are recomputed, and if the recomputed posture is `CLEAR`, every hearing of the plan sitting in `BLOCKED` returns to `SCHEDULED`.

The hearing's `adopted_amendment_count` is decremented by one, and both the plan's `version` and the amendment's `version` are incremented by one. After a rescission the policy-inventory conservation invariant of section 2.10 must hold exactly.

The implementation program is assembled by `PlanningStaff` alongside the drafting work, before adoption. An implementation action names the `plan_update_id`, the `source_element_id` of the element whose policy it implements — which must belong to the same plan, otherwise `ERR_CROSS_PLAN_ACTION` — an `action_type` of `ZONING_CODE_UPDATE`, `CAPITAL_PROJECT`, `PROGRAM` or `MONITORING`, a `title` of 1 to 160 characters as printed in the implementation program table, and its monitoring indicator: an `indicator_name` of 1 to 80 characters, an `indicator_direction` of `INCREASE` or `DECREASE` saying whether the indicator must rise or fall to count as healthy, a `baseline_value` giving the indicator's level in the plan's `base_year`, and a `target_value` giving the level the action aims at by the horizon year. The plan must not already be adopted. A new action enters `PENDING` with `reading_count` at zero, `on_track` false, and `latest_reading_value`, `latest_reading_at` and `due_at` all null.

Actions sit dormant until the council adopts the plan, at which point each one standing in `PENDING` moves `PENDING → SCHEDULED` and has its `due_at` stamped as the plan's `adopted_at` instant advanced by the fixed implementation lead time of 365 days.

Monitoring readings may be recorded while an action is either `PENDING` or `SCHEDULED` — a department may begin tracking an indicator before adoption — and are refused once the action is `COMPLETED`, with `ERR_ACTION_ALREADY_COMPLETED`. A reading carries a single `reading_value`. The newest reading always wins outright: `latest_reading_value` is replaced with the supplied value, `latest_reading_at` is stamped with the logical clock instant, `reading_count` is incremented by one, and earlier readings are neither averaged nor retained as rows. The action's `on_track` flag is then recomputed inclusively against the target: for an `INCREASE` indicator the action is on track when `latest_reading_value` is greater than or equal to `target_value`; for a `DECREASE` indicator it is on track when `latest_reading_value` is less than or equal to `target_value`. A reading exactly equal to the target therefore counts as on track. The plan's `monitoring_on_track_count` is then recomputed as the number of the plan's implementation actions whose `on_track` is true, and the action's `version` is incremented by one.

Completing an action is the last write in the plan's life, and it is only available once the action has been scheduled by adoption: an action still `PENDING` is refused with `ERR_ACTION_NOT_SCHEDULED` and one already finished with `ERR_ACTION_ALREADY_COMPLETED`. At least one reading must have been recorded, otherwise `ERR_NO_INDICATOR_READING`, and the indicator must actually be healthy — an action whose `on_track` is false is refused with `ERR_INDICATOR_OFF_TRACK`, in that order. On success the action moves `SCHEDULED → COMPLETED`, and both its own `version` and the plan's `version` are incremented by one. `COMPLETED` is terminal for an implementation action.

## 4. Endpoint Definitions

Every endpoint below is mounted under the `/planning` prefix, with the sole exception of the clock-control endpoint. Endpoints that create a new resource return HTTP 201 with the created resource in the `data` field; every other successful endpoint — reads, lists, state transitions and computed reads — returns HTTP 200. Path segments written as `{id}` are the UUID `id` of the resource named by the preceding collection segment; on the nested list endpoints mounted under `/planning/plan-updates/{id}` and `/planning/engagement-activities/{id}` and `/planning/environmental-reviews/{id}`, `{id}` identifies the parent resource and the response is the child collection. Every query parameter shown in section 3 is optional, and the two pagination parameters `limit` and `offset` are accepted by every list endpoint. All endpoints require the `X-User-Role` and `X-User-ID` headers described in section 2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/planning/plan-updates` | Open a new comprehensive plan update cycle. | PlanningDirector |
| GET | `/planning/plan-updates/{id}` | Read one plan update with all derived compliance counters. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/plan-updates` | List plan updates with pagination; supports filtering by `status`, `jurisdiction_code` and `adopted_scenario_id`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/plan-updates/{id}/state-submission` | Submit the plan to the state for mandate review, running the full mandate checklist; also serves resubmission from `STATE_DEFICIENT`. | PlanningDirector |
| POST | `/planning/plan-updates/{id}/state-determination` | Record the state's mandate determination; `CERTIFIED` unlocks hearings, `DEFICIENT` freezes the plan and demotes the named elements. | StateReviewer |
| GET | `/planning/plan-updates/{id}/compliance-summary` | Computed read: the state-mandate checklist and the capacity and equity dashboard for the plan. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/inventory-datasets` | Create an existing-conditions inventory dataset. | PlanningStaff |
| GET | `/planning/inventory-datasets/{id}` | Read one inventory dataset, including its current `version` for version pinning. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/plan-updates/{id}/inventory-datasets` | List the inventory datasets of a plan, filterable by `inventory_type` and `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/inventory-datasets/{id}/certify` | Certify a draft inventory dataset; the certifier must not be the author. | PlanningDirector |
| POST | `/planning/growth-scenarios` | Create a growth projection scenario pinned to a certified land-use inventory, computing capacity and demand at creation. | PlanningStaff |
| GET | `/planning/growth-scenarios/{id}` | Read one growth scenario with its capacity and demand results. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/growth-scenarios` | List growth scenarios, filterable by `plan_update_id`, `land_use_inventory_id`, `status` and `method`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/growth-scenarios/{id}/adopt` | Adopt a scenario as the plan's official projection, re-running the housing allocation waterfall for all four tiers. | PlanningDirector |
| POST | `/planning/housing-allocations` | Record the state-assigned housing allocation for one income tier of a plan. | StateReviewer |
| GET | `/planning/plan-updates/{id}/housing-allocations` | List the income-tier allocations of a plan with their waterfall results, filterable by `income_tier`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/plan-elements` | Start drafting one statutory element of the plan. | PlanningStaff |
| GET | `/planning/plan-elements/{id}` | Read one plan element, including its current `version` for version pinning by amendments. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/plan-updates/{id}/plan-elements` | List the elements of a plan, filterable by `element_type` and `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| PATCH | `/planning/plan-elements/{id}` | Revise element content; returns a revision-requested element to drafting, or applies the director override to an escalated element. | PlanningStaff, PlanningDirector |
| POST | `/planning/plan-elements/{id}/submit-review` | Submit a drafted element for director review. | PlanningStaff |
| POST | `/planning/plan-elements/{id}/review-decision` | Record the director's review decision: approve, or request a revision which loops the element back or escalates it on the third round. | PlanningDirector |
| POST | `/planning/consistency-links` | Declare an internal-consistency dependency from one element to another; rejects self links, duplicates and cycles. | PlanningStaff |
| GET | `/planning/consistency-links/{id}` | Read one consistency link. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/consistency-links` | List consistency links, filterable by `source_element_id`, `target_element_id`, `status` and `dependency_type`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/consistency-links/{id}/reconcile` | Record that the two elements have been reconciled, clearing the link from open or stale. | PlanningDirector |
| POST | `/planning/venues` | Register a meeting facility usable by engagement activities; venues are immutable configuration rows. | PlanningStaff |
| POST | `/planning/engagement-activities` | Schedule a workshop, survey or targeted-outreach activity, running the venue occupancy test with the venue's turnover buffer. | PlanningStaff |
| GET | `/planning/engagement-activities/{id}` | Read one engagement activity with its participation counters. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/engagement-activities` | List engagement activities, filterable by `plan_update_id`, `venue_id`, `activity_type` and `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/engagement-activities/{id}/complete` | Close an activity that has ended and fold its weighted participation into the plan's equity share. | PlanningStaff |
| POST | `/planning/engagement-activities/{id}/cancel` | Cancel a scheduled or completed activity; cancelling a completed activity compensates the plan's participation totals exactly. | PlanningStaff |
| POST | `/planning/participation-records` | Attach one pseudonymous participation record to a scheduled activity. | PlanningStaff |
| GET | `/planning/engagement-activities/{id}/participation-records` | List the participation records of an activity, filterable by `demographic_group`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/environmental-reviews` | Open an environmental review on the plan and its alternatives. | EnvironmentalConsultant |
| GET | `/planning/environmental-reviews/{id}` | Read one environmental review with its comment-period window and preferred alternative. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/environmental-reviews` | List environmental reviews, filterable by `plan_update_id`, `status`, `document_type` and `preferred_alternative_id`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/environmental-reviews/{id}/circulate` | Release the document for public comment, stamping the statutory comment window from the logical clock. | EnvironmentalConsultant |
| POST | `/planning/environmental-reviews/{id}/select-preferred-alternative` | Server-side selector: picks the eligible alternative with the lowest net impact score and returns the winner; no alternative id is supplied by the client. | EnvironmentalConsultant |
| POST | `/planning/environmental-reviews/{id}/certify` | Certify the environmental document once the comment period has elapsed and a preferred alternative exists. | PlanningDirector |
| POST | `/planning/plan-alternatives` | Add an alternative to a draft environmental review and score its impacts. | EnvironmentalConsultant |
| GET | `/planning/environmental-reviews/{id}/plan-alternatives` | List the alternatives of a review with their impact scores, filterable by `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/hearings` | Schedule a planning commission or council adoption hearing, enforcing notice lead time, closed-interval calendar conflicts and the daily cap per body. | CommissionClerk |
| GET | `/planning/hearings/{id}` | Read one hearing with its outcome and amendment counters. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/plan-updates/{id}/hearings` | List the hearings of a plan, filterable by `body_type` and `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/hearings/{id}/open` | Gavel in a scheduled hearing; requires the clock to have reached the scheduled start and the plan posture to be clear. | CommissionClerk |
| POST | `/planning/hearings/{id}/outcome` | Record the hearing outcome — continue, recommend, adopt or deny — each branch firing a different side-effect set on the plan. | CommissionClerk |
| POST | `/planning/amendments` | Move an amendment against an approved element during an open hearing, pinned to the element version the clerk last observed. | CommissionClerk |
| GET | `/planning/amendments/{id}` | Read one amendment with its applied policy count and captured prior element status. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/amendments` | List amendments, filterable by `hearing_id`, `target_element_id` and `status`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/amendments/{id}/adopt` | Adopt a proposed amendment, applying the policy delta to the element and firing the five-link consistency cascade; the adopter must not be the proposer. | CommissionClerk |
| POST | `/planning/amendments/{id}/withdraw` | Withdraw a proposed amendment before it is voted on, leaving the element untouched. | CommissionClerk |
| POST | `/planning/amendments/{id}/rescind` | Rescind an adopted amendment during the same open hearing, reversing every effect of the adoption. | CommissionClerk |
| POST | `/planning/implementation-actions` | Add a zoning-code update, capital project, program or monitoring action to the implementation program with its monitoring indicator. | PlanningStaff |
| GET | `/planning/implementation-actions/{id}` | Read one implementation action with its latest indicator reading. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| GET | `/planning/implementation-actions` | List implementation actions, filterable by `plan_update_id`, `source_element_id`, `status` and `action_type`. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |
| POST | `/planning/implementation-actions/{id}/record-reading` | Record a monitoring indicator reading, recomputing the on-track flag inclusively against the target value. | PlanningStaff |
| POST | `/planning/implementation-actions/{id}/complete` | Mark an implementation action complete; only allowed once its indicator is on track. | PlanningStaff |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to the supplied `to_iso8601` instant; no entity is mutated and time may be moved forward or backward. | PlanningStaff, PlanningDirector, EnvironmentalConsultant, CommissionClerk, StateReviewer |

## 5. Error Code Catalogue

Every failed request returns the error envelope of section 2.2 with the `error_id` set to one of the identifiers below and the HTTP status shown beside it. When more than one condition is violated by the same request, the identifier returned is the one whose rung comes first in the validation ladder of section 2.8; the remaining violations are not reported.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ESCALATION_OVERRIDE_REQUIRED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PLAN_UPDATE_NOT_FOUND` | 404 |
| `ERR_INVENTORY_NOT_FOUND` | 404 |
| `ERR_SCENARIO_NOT_FOUND` | 404 |
| `ERR_ELEMENT_NOT_FOUND` | 404 |
| `ERR_LINK_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_ACTIVITY_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_AMENDMENT_NOT_FOUND` | 404 |
| `ERR_ACTION_NOT_FOUND` | 404 |
| `ERR_PLAN_ALREADY_ADOPTED` | 409 |
| `ERR_PLAN_NOT_DRAFTING` | 409 |
| `ERR_PLAN_NOT_SUBMITTED` | 409 |
| `ERR_PLAN_NOT_CERTIFIED` | 409 |
| `ERR_PLAN_NOT_RECOMMENDED` | 409 |
| `ERR_INVENTORY_NOT_DRAFT` | 409 |
| `ERR_INVENTORY_NOT_CERTIFIED` | 409 |
| `ERR_INVENTORY_TYPE_MISMATCH` | 409 |
| `ERR_INVENTORY_SET_INCOMPLETE` | 409 |
| `ERR_ADOPTED_SCENARIO_PINNED` | 409 |
| `ERR_SCENARIO_NOT_DRAFT` | 409 |
| `ERR_SCENARIO_NOT_ADOPTED` | 409 |
| `ERR_ELEMENT_NOT_DRAFT` | 409 |
| `ERR_ELEMENT_NOT_IN_REVIEW` | 409 |
| `ERR_ELEMENT_NOT_AMENDABLE` | 409 |
| `ERR_TARGET_ELEMENT_NOT_REVIEWABLE` | 409 |
| `ERR_LINK_ALREADY_CLEARED` | 409 |
| `ERR_ACTIVITY_NOT_SCHEDULED` | 409 |
| `ERR_ACTIVITY_CLOSED` | 409 |
| `ERR_REVIEW_NOT_DRAFT` | 409 |
| `ERR_REVIEW_NOT_CIRCULATED` | 409 |
| `ERR_HEARING_NOT_SCHEDULED` | 409 |
| `ERR_HEARING_NOT_OPEN` | 409 |
| `ERR_AMENDMENT_NOT_PROPOSED` | 409 |
| `ERR_AMENDMENT_NOT_ADOPTED` | 409 |
| `ERR_ACTION_NOT_SCHEDULED` | 409 |
| `ERR_ACTION_ALREADY_COMPLETED` | 409 |
| `ERR_STALE_ELEMENT_VERSION` | 412 |
| `ERR_STALE_INVENTORY_VERSION` | 412 |
| `ERR_CROSS_PLAN_LINK` | 409 |
| `ERR_CROSS_PLAN_AMENDMENT` | 409 |
| `ERR_CROSS_PLAN_ACTION` | 409 |
| `ERR_HORIZON_YEAR_MISMATCH` | 422 |
| `ERR_SELF_CONSISTENCY_LINK` | 422 |
| `ERR_DUPLICATE_CONSISTENCY_LINK` | 409 |
| `ERR_CONSISTENCY_CYCLE` | 409 |
| `ERR_DUPLICATE_ELEMENT_TYPE` | 409 |
| `ERR_DUPLICATE_ALLOCATION_TIER` | 409 |
| `ERR_DUPLICATE_PARTICIPATION` | 409 |
| `ERR_ELEMENT_HAS_NO_POLICIES` | 409 |
| `ERR_INSUFFICIENT_ALTERNATIVES` | 409 |
| `ERR_VENUE_NOT_EQUITY_ELIGIBLE` | 409 |
| `ERR_POLICY_COUNT_NEGATIVE` | 409 |
| `ERR_VENUE_TIME_CONFLICT` | 409 |
| `ERR_HEARING_SLOT_CONFLICT` | 409 |
| `ERR_HEARING_DAILY_CAP_EXCEEDED` | 409 |
| `ERR_NOTICE_PERIOD_TOO_SHORT` | 422 |
| `ERR_REVIEW_WINDOW_OVERLAP` | 409 |
| `ERR_COMMISSION_RECOMMENDATION_REQUIRED` | 409 |
| `ERR_OUTCOME_NOT_VALID_FOR_BODY` | 409 |
| `ERR_UNRESOLVED_AMENDMENTS` | 409 |
| `ERR_HEARING_NOT_YET_STARTED` | 409 |
| `ERR_COMMENT_PERIOD_OPEN` | 409 |
| `ERR_ACTIVITY_NOT_ENDED` | 409 |
| `ERR_INVENTORY_VINTAGE_TOO_LATE` | 409 |
| `ERR_REQUIRED_ELEMENT_MISSING` | 409 |
| `ERR_ALLOCATION_INCOMPLETE` | 409 |
| `ERR_CONSISTENCY_UNRESOLVED` | 409 |
| `ERR_ENVIRONMENTAL_REVIEW_MISSING` | 409 |
| `ERR_ENVIRONMENTAL_REVIEW_NOT_CERTIFIED` | 409 |
| `ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED` | 409 |
| `ERR_PLAN_POSTURE_BLOCKED` | 409 |
| `ERR_RESUBMISSION_LIMIT_EXCEEDED` | 409 |
| `ERR_HOUSING_SHORTFALL` | 409 |
| `ERR_EQUITY_TARGET_NOT_MET` | 409 |
| `ERR_NO_ELIGIBLE_ALTERNATIVE` | 409 |
| `ERR_NO_PARTICIPATION_RECORDS` | 409 |
| `ERR_NO_INDICATOR_READING` | 409 |
| `ERR_INDICATOR_OFF_TRACK` | 409 |
