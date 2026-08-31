# Workforce Reduction & WARN Act Compliance API — Product Requirements Document

## 1. Introduction

A corporate restructuring is one of the few HR events where a clerical slip becomes a federal liability. When a company decides to eliminate positions, it must document why each person was chosen, prove statistically that the choice did not fall disproportionately on a protected class, count the resulting employment losses against both the federal WARN Act and whichever state mini-WARN statute governs the site, deliver sixty days of advance notice to the right audiences with the right content, and — if anyone selected is forty or older — hand that person an OWBPA-compliant disclosure of the decisional unit's age bands together with a release they may consider for weeks and revoke for a further seven days. Each of these obligations has its own clock, its own counting rules, and its own definition of who is even in scope. Today restructuring teams reconcile them in spreadsheets, and the reconciliation is where the exposure lives.

This document specifies the Workforce Reduction & WARN Act Compliance API: a system of record that carries a reduction-in-force programme from an empty plan through criteria documentation, employee selection, adverse-impact testing, legal clearance, threshold determination, notice issuance, individual notification, severance pricing and release execution, ending with the rehire restrictions that keep a freshly vacated seat from being quietly backfilled. The API is deliberately opinionated about ordering. A selection cannot be scored before its criteria are frozen; a plan cannot be approved while its adverse-impact analysis is unexplained; an offer cannot be priced before the individual has been notified; the reduction cannot be executed while a triggered site still lacks an issued notice.

Two design commitments run through everything that follows. First, **counting is jurisdictional, not universal** — the same roster on the same day yields one employment-loss count under the federal rule and a different one under a state mini-WARN rule, and the system keeps both numbers side by side rather than reconciling them into a single "truth". Second, **every compensating action must restore the world exactly** — rescinding a selection returns the site's headcount partition to its pre-decision values, and revoking a signed release returns both plan ledgers to their pre-issue and pre-signature values, to the cent.

## 2. Global Specifications & System-Wide Principles

This section establishes the contract-level rules that apply uniformly to every resource and every operation in the API. Where a rule below conflicts with a narrative statement in §3, this section governs the mechanics and §3 governs the domain intent.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. A request that omits either header, or supplies either as an empty string, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs.

The system recognises exactly five roles: `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SeparatingEmployee`, and `SystemAdmin`. A value of `X-User-Role` that is not one of those five, or that names a role the target operation does not admit, is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The `RestructuringLead` builds the plan, documents and freezes the criteria, maintains the site roster, proposes and decides selections, runs notification logistics, and executes the reduction. `EmploymentCounsel` renders the legal decision, runs and clears adverse-impact analysis, generates OWBPA disclosures, determines and issues WARN notices, and waives rehire restrictions. The `BenefitsAdministrator` prices severance offers, issues them against the plan budget, and owns benefit continuation and outplacement tiering. A `SeparatingEmployee` is the individual receiving the release and may only sign or revoke it. The `SystemAdmin` configures the federal and state WARN rule rows and drives the logical clock.

Role identity binds to `X-User-ID` differently depending on the role. When `X-User-Role` is `SeparatingEmployee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's foreign-key field to `X-User-ID` — concretely, signing or revoking a severance offer requires that `X-User-ID` equal the `employee_id` of the `Selection` that offer was priced for, and a mismatch is rejected with `ERR_NOT_OFFER_RECIPIENT` (HTTP 403); those two write operations are the only ownership-checked ones, so a `SeparatingEmployee` reading an offer at `GET /severance-offers/{id}` is never compared against its recipient. When `X-User-Role` is `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` or `approved_by_user_id` on a `ReductionPlan`, as `cleared_by_user_id` on an adverse-impact analysis, or as `waived_by_user_id` on a rehire restriction — but it never compares any of those four identifiers to an entity's `id`.

One further rule follows from the separation of duties this domain demands. The person who hands a plan to counsel and the person who renders the legal decision on it must be different principals, even when the same human being holds both roles. Rendering a legal decision from an `X-User-ID` equal to the plan's recorded `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. The `offset` parameter is the number of records to skip and defaults to 0; negative values are not accepted. A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its records sorted by `created_at` in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the request's filters before pagination is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Resource Identity, Timestamps and Revision Counters

Every resource the API persists — reduction plans, sites, employees, selections, WARN rules, adverse-impact analyses, OWBPA disclosures, WARN notices, severance offers, and position restrictions — carries an `id` that is a server-minted UUID with no type prefix of any kind, and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional-second digits.

Most resources additionally carry two mutation-tracking fields. `updated_at` is an ISO 8601 UTC timestamp, again with three fractional digits, refreshed on every change to the resource; `version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on every persisted mutation of that resource. This applies to reduction plans, sites, employees, selections, adverse-impact analyses, OWBPA disclosures, WARN notices, severance offers, and position restrictions. A recomputation of a derived field counts as a mutation: when a site's counters are recalculated because one of its employees changed employment status, that site's `updated_at` is refreshed and its `version` advances, and the same holds when a plan's ledger rollups or WARN posture are recalculated by a cascade. A recomputation that leaves every stored field identical is not a mutation, however: `updated_at` is refreshed and `version` advances only when the recomputation actually changes at least one value.

The one exception is the `WarnRule` resource. A configured statute row is immutable once written, so it carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field, and neither field appears in its representation.

### 2.5. The Logical Compliance Clock

Every deadline, window boundary and age computation in this system reads a server-held **logical clock** rather than wall-clock time. On server startup the clock stands at exactly `2026-08-01T00:00:00.000Z`, and it never falls back to real time. A `SystemAdmin` moves it with the clock-setting operation at `POST /_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response reports the resulting `current_utc`. Advancing the clock is how the test harness ages an offer past its consideration deadline or carries a rehire restriction past its expiry, and moving the clock beyond a restriction's `restricted_until_utc` is what causes that restriction to be treated as released at its next evaluation.

Dates that describe calendar facts rather than instants — `birth_date`, `hire_date`, `separation_date`, `proposed_separation_date`, `earliest_separation_date`, `window_start_date` and `window_end_date` — are date-only strings in `YYYY-MM-DD` form. Instant-valued fields, all of which end in `_utc`, are full ISO 8601 UTC timestamps. Where a rule adds a whole number of days to a date-only value to produce an instant, the date is taken at `00:00:00.000Z` of that day and the days are added to it.

### 2.6. Order of Evaluation for Request Rejection

When a request violates more than one rule, exactly one error is returned, and it is always the violation with the lowest priority number in the ladder below. This ordering is normative: a test that supplies a request breaching both rule 12 and rule 23 must receive rule 12's error identifier. The ladder runs as follows.

1. Header presence — `X-User-ID` and `X-User-Role` present and non-empty on every endpoint; otherwise `ERR_UNAUTHENTICATED` (401).
2. Role admissibility — the supplied `X-User-Role` is one of the five roles and is listed for the target endpoint; otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. Request and query well-formedness — every required input field present, every enum value a declared member, integers and booleans correctly typed, `limit` between 1 and 100 inclusive, `offset` not negative, every `weight_pct` an integer, every criterion `score` an integer from 0 through 100 inclusive, every date in `YYYY-MM-DD` form, and `state_code` exactly two uppercase letters; otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint.
4. Path resource existence — identifiers in the URL are resolved left to right and each must exist, yielding whichever of `ERR_PLAN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND` or `ERR_WARN_RULE_NOT_FOUND` matches the missing segment (404). Applies to every path-parameterised endpoint.
5. Body foreign-key existence — `plan_id`, `site_id`, `employee_id`, each element of `employee_ids`, `selection_id` and each element of `selection_ids` must resolve to a live record, yielding `ERR_PLAN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND` or `ERR_SELECTION_NOT_FOUND` (404). This check guards `POST /selections`, `POST /reduction-plans/{id}/selection-batch`, `POST /reduction-plans/{id}/decide-batch`, `POST /employees`, `POST /adverse-impact-analyses`, `POST /owbpa-disclosures`, `POST /warn-notices` and `POST /severance-offers`.
6. Statute-row existence — the `WarnRule` for the requested jurisdiction must be configured; `ERR_WARN_RULE_NOT_FOUND` (404) on `POST /warn-notices`.
7. Offer recipient ownership — `ERR_NOT_OFFER_RECIPIENT` (403) on `POST /severance-offers/{id}/sign` and `POST /severance-offers/{id}/revoke`.
8. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403) on `POST /reduction-plans/{id}/legal-decision`.
9. Declared transition availability — the target resource must currently sit in a state from which the requested transition is declared, otherwise `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_SELECTION_STATE`, `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_NOTICE_STATE`, `ERR_INVALID_OFFER_STATE` or `ERR_INVALID_RESTRICTION_STATE` (409). Applies to every state-changing endpoint.
10. Cross-entity state guards — the `Selection` behind a severance-offer operation must be `SELECTED`, and the `ReductionPlan` behind a decide or a rescind must not be `EXECUTED`; otherwise `ERR_INVALID_SELECTION_STATE` (409). This guards `POST /severance-offers`, `POST /severance-offers/{id}/issue`, `POST /selections/{id}/decide` and `POST /selections/{id}/rescind`.
11. Optimistic concurrency — `expected_plan_version` must equal the plan's current `version` and `expected_selection_version` must equal the selection's current `version`, otherwise `ERR_STALE_PLAN_VERSION` or `ERR_STALE_SELECTION_VERSION` (412), on `POST /adverse-impact-analyses` and `POST /severance-offers` respectively.
12. Criteria frozen — `ERR_CRITERIA_NOT_LOCKED` (422) on `POST /selections` and `POST /reduction-plans/{id}/selection-batch`.
13. Adverse-impact clearance — `ERR_IMPACT_ANALYSIS_NOT_CLEARED` (422) on `POST /reduction-plans/{id}/legal-decision` carrying the approve decision, on `POST /selections/{id}/deliver-notice`, and on `POST /severance-offers`.
14. Disclosure present — `ERR_OWBPA_DISCLOSURE_MISSING` (422) on `POST /severance-offers`.
15. Disclosure current — `ERR_OWBPA_DISCLOSURE_STALE` (422) on `POST /severance-offers`.
16. Individual notice delivered — `ERR_NOTICE_NOT_DELIVERED` (422) on `POST /severance-offers` and on `POST /reduction-plans/{id}/execute`.
17. Site notices issued — `ERR_WARN_NOTICE_REQUIRED` (422) on `POST /reduction-plans/{id}/execute`.
18. Sufficient individual notice period — `ERR_NOTICE_PERIOD_INSUFFICIENT` (422) on `POST /selections/{id}/deliver-notice`.
19. Consideration period open — `ERR_CONSIDERATION_PERIOD_EXPIRED` (422) on `POST /severance-offers/{id}/sign`.
20. Revocation window open — `ERR_REVOCATION_WINDOW_CLOSED` (422) on `POST /severance-offers/{id}/revoke`.
21. Offer window free — `ERR_OFFER_WINDOW_CONFLICT` (409) on `POST /severance-offers` and `POST /severance-offers/{id}/issue`.
22. Aggregation window free — `ERR_WARN_WINDOW_COLLISION` (409) on `POST /selections` and `POST /reduction-plans/{id}/selection-batch`.
23. No duplicate selection — `ERR_DUPLICATE_SELECTION` (409) on `POST /selections` and `POST /reduction-plans/{id}/selection-batch`.
24. Criteria weights valid — `ERR_CRITERIA_WEIGHT_INVALID` (422) on `POST /reduction-plans`.
25. Score sheet matches criteria — `ERR_CRITERION_SCORE_MISMATCH` (422) on `POST /selections` and `POST /reduction-plans/{id}/selection-batch`.
26. Notice content complete — `ERR_WARN_CONTENT_INCOMPLETE` (422) on `POST /warn-notices/{id}/issue`.
27. Statute row uniqueness — `ERR_WARN_RULE_ALREADY_EXISTS` (409) on `POST /warn-rules`.
28. Reissue cap — `ERR_OFFER_REISSUE_LIMIT` (422) on `POST /severance-offers/{id}/issue`.
29. Analysable pool — `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA` (422) on `POST /adverse-impact-analyses`.
30. Plan approved before individual notice — `ERR_PLAN_NOT_APPROVED` (422) on `POST /selections/{id}/deliver-notice`.
31. Script matches jurisdiction — `ERR_SCRIPT_JURISDICTION_MISMATCH` (422) on `POST /selections/{id}/deliver-notice`.
32. Non-empty workforce denominator — `ERR_WARN_WORKFORCE_EMPTY` (422) on `POST /warn-notices`.
33. Backfill restriction — `ERR_BACKFILL_RESTRICTED` (409) on `POST /employees` and `POST /sites/{id}/roster-import`.
34. Severance budget headroom — `ERR_SEVERANCE_BUDGET_EXCEEDED` (422) on `POST /severance-offers/{id}/issue`.

The semantics of each of these checks are developed in §3 alongside the workflow each one guards; the ladder above fixes only which one wins when several fail at once.

### 2.7. Precision, Rounding and Monetary Representation

All money in this system is carried as whole integer numbers of **cents**; there are no fractional cents anywhere, and every field whose name ends in `_cents` is an integer. Wherever a rule calls for rounding, the method is **round half up**, meaning a value exactly halfway between two candidates rounds away from zero to the larger magnitude.

Rounding order is part of the specification, not an implementation detail. Where a formula prescribes rounding an intermediate rate to whole cents before multiplying it, computing the product first and rounding once at the end produces a different — and incorrect — answer, and the system must follow the step order the formula states.

Not every quantity is monetary. The percentage of a site's workforce lost is carried to **two decimal places, round half up**, and every threshold comparison is made against that already-rounded value. The weighted composite score of a selection is likewise carried to **two decimal places, round half up**. The adverse-impact statistics — the focal selection rate, the reference selection rate, the impact ratio and the standard-deviation measure — are each carried to **four decimal places, round half up**. Counts of people, days, months and weeks-of-service tiers are exact integers, with the single exception of awarded severance weeks, which may carry a half-week under one of the two severance variants.

### 2.8. Optimistic Concurrency on Plan and Selection Revisions

Two write operations in this API replace or supersede work that was computed over a snapshot of another resource, and both are therefore guarded by optimistic concurrency control against that resource's `version`.

Creating an adverse-impact analysis at `POST /adverse-impact-analyses` requires a non-optional `expected_plan_version` field in the request body, carrying the `version` of the `ReductionPlan` the client last observed. If that value does not equal the plan's current `version`, the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP status 412. The guard exists because a new analysis legitimately supersedes the plan's prior analysis: without it, a writer working from a stale view of the plan would replace an analysis that was computed over a selection set that has since changed.

Creating a severance offer at `POST /severance-offers` requires a non-optional `expected_selection_version` field carrying the `version` of the `Selection` the client last observed. If that value does not equal the selection's current `version`, the request is rejected with `ERR_STALE_SELECTION_VERSION` and HTTP status 412. A fresh offer legitimately supersedes a prior revoked or expired offer for the same selection, so without the guard a writer holding a stale view would price a release against criterion scores, a separation date or a notice record that has since moved.

No other endpoint in this API accepts a version field. Operations not named above take no `expected_plan_version`, no `expected_selection_version`, and no equivalent of either.

### 2.9. Cascade Discipline and the Headcount Identity

Many operations in this domain mutate several entities at once, and the secondary mutations are as much part of the contract as the primary one. When a selection is decided, the cascade reaches the employee, then the employee's site, then every plan holding a selection at that site, then that plan's disclosures and analyses; when a plan is executed, the cascade reaches the selections, the employees, the sites and the newly created rehire restrictions. Each entity touched by a cascade independently refreshes its own `updated_at` and increments its own `version`; a cascade is not a single mutation shared across entities.

Two invariants are absolute. The first is a **headcount identity** on every site: at every moment, `roster_count` equals the sum of `active_headcount`, `pending_separation_count` and `separated_count`. Every employee at the site is counted in exactly one of those three partitions and none is counted twice or omitted. The identity must hold after every individual mutation, not merely at rest, and it is recomputed whenever an employee is hired onto the site and whenever a selection decision, a rescission or a plan execution moves one of the site's employees between employment states.

The second is a **round-trip invariant** on compensating actions. Deciding a selection into the selected branch and then rescinding it must return the site's `active_headcount` and `pending_separation_count` to their exact pre-decision values while `roster_count` never moves at all. Likewise, issuing an offer, having it signed and then having it revoked must leave the plan's `severance_reserve_cents` at exactly its pre-issue value and its `benefit_liability_cents` at exactly its pre-signature value. Drift of any size is a defect.

Because these rollups are recomputed rather than nudged, the correct implementation of every contributing transition is to re-derive the aggregate from the contributing rows, not to add or subtract from a running total and hope the two stay in step.

### 2.10. Resource Addressing and Left-to-Right Resolution

The API has a flat topology: every resource lives at its own root collection and parentage travels in request bodies as identifier fields rather than in the URL. Two operations are scoped actions on a parent — the roster import beneath a site, and the selection-batch and decide-batch actions beneath a plan — and one is a maintenance capability on the logical clock; none of these implies ownership nesting.

Where a URL does contain more than one identifier, the identifiers are resolved strictly left to right, and the first one that names no existing record decides the response. A roster import addressed to a site that does not exist yields `ERR_SITE_NOT_FOUND` without any inspection of the entries payload, and a batch action addressed to a plan that does not exist yields `ERR_PLAN_NOT_FOUND` before any listed selection identifier is looked at. The same precedence extends to bodies: within a single request, path identifiers are resolved before body foreign keys, and body foreign keys are resolved before any business rule is evaluated. Inside an array of identifiers, the first element that resolves to nothing decides the response. A request addressed to a path the API does not expose at all, or using a method that path does not admit, is not a resource-existence failure: it is answered with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Opening a Reduction Programme and Freezing Its Criteria

A restructuring begins when a `RestructuringLead` opens a reduction plan. The creation payload carries a `name` for the programme, a `decisional_unit_name` that labels the OWBPA decisional unit and is reproduced verbatim on every disclosure the plan later generates, a `selection_criteria` array documenting how people will be ranked, and a `severance_budget_cents` figure that acts as a hard ceiling on the money the plan may reserve. The budget is a whole number of cents and may not be negative — a negative figure is malformed and refused with `ERR_INVALID_REQUEST` — and zero is permitted and simply means no offer can ever be issued against the plan.

The `selection_criteria` array is the documentary heart of the programme. It holds between one and six entries inclusive — an empty array, or one carrying a seventh entry, is malformed and refused with `ERR_INVALID_REQUEST` — each an object with a `criterion_code`, an integer `weight_pct`, and an optional free-text `description` explaining what the criterion measures that defaults to an empty string when omitted. No `criterion_code` may repeat within the array, and the `weight_pct` values must sum to exactly 100: a total of 99 or 101 is as invalid as a total of 50. A payload whose weights sum to any other number, or that repeats a code, is refused with `ERR_CRITERIA_WEIGHT_INVALID`.

A newly created plan is inert in every dimension. Its `criteria_status` begins at `DRAFT`, its `approval_status` at `DRAFT`, and its `warn_status` at `NOT_ASSESSED`. Its `version` begins at 1. Every derived figure starts at its zero point: `severance_reserve_cents`, `benefit_liability_cents`, `selected_count`, `pool_count`, `legal_return_count` and `required_notice_days` all start at 0, `owbpa_consideration_days` starts at 21, `owbpa_required` starts false, and `earliest_separation_date`, `notice_deadline_utc`, `submitted_by_user_id` and `approved_by_user_id` all start null.

Before anyone may be scored against the criteria, the lead must freeze them. Locking the criteria advances `criteria_status` from `DRAFT` to `LOCKED` and increments the plan's `version` by 1. From that point the documented ranking basis is fixed for the life of the programme, which is exactly what an EEOC or plaintiff-side reviewer will later ask to see. Any attempt to create a selection while the plan's `criteria_status` is still `DRAFT` is refused with `ERR_CRITERIA_NOT_LOCKED`.

Note that the plan carries **two independent status axes** that advance on entirely different triggers. The governance axis, `approval_status`, moves `DRAFT → IN_LEGAL_REVIEW → APPROVED → EXECUTED`, with a return arc from `IN_LEGAL_REVIEW` back to `DRAFT`, and is driven by explicit human decisions. The compliance axis, `warn_status`, moves `NOT_ASSESSED → THRESHOLD_PENDING → NOTICES_ISSUED → NOTICE_PERIOD_SATISFIED` and is advanced only by system cascades from site recomputation, notice issuance and plan execution. Neither axis constrains the other's position: a plan may reach `APPROVED` while still sitting at `NOT_ASSESSED`, and it may sit at `THRESHOLD_PENDING` while its governance axis is still `DRAFT`.

### 3.2. Sites of Employment, the Roster, and Backfill Control

WARN counting happens per **site of employment**, so a plan's arithmetic depends entirely on how sites are registered. A `RestructuringLead` registers a site with a `name`, a two-letter `state_code` that selects which state mini-WARN rule governs it, and an optional `is_single_site` flag that defaults to true and records whether the location qualifies as a single site of employment for plant-closing analysis. Every counter on a fresh site starts at 0 — `roster_count`, `active_headcount`, `pending_separation_count`, `separated_count`, `federal_loss_count`, `state_loss_count` and `required_notice_days` — its `warn_trigger_status` starts at `NONE`, and its `window_start_date` starts null.

Hiring one person onto a roster requires a `site_id` naming the site, a `full_name`, a `job_title`, a `birth_date`, a `hire_date`, an `annual_base_cents` figure that must be strictly greater than zero, a `weekly_hours` figure that may not be negative, a `demographic_code` drawn from `CLASS_A`, `CLASS_B` or `CLASS_C`, and an optional `monthly_premium_cents` recording the employer's group-health monthly premium for that person, which defaults to 90000 cents when omitted. On creation the person's `employment_status` is `ACTIVE`, `separation_date` is null, `age_at_separation` and `years_of_service` are null, `release_signed` is false, `benefit_continuation_status` is `NONE`, `benefit_subsidy_months` and `benefit_subsidy_cents` are 0, and `outplacement_tier` is `NONE`. The derived `is_part_time` flag is true when the person's `weekly_hours` is below 20 hours per week and false otherwise — the same twenty-hour line the federal statute draws. The other two derived fields track the `separation_date`: whenever one is set, `age_at_separation` becomes the employee's completed whole years from `birth_date` to that `separation_date` and `years_of_service` is derived as §3.8 describes, and both return to null whenever the `separation_date` is cleared again. Each hire recomputes the site's `roster_count` and `active_headcount`. The four headcount figures are defined by partition: `active_headcount` is the number of the site's employees whose `employment_status` is `ACTIVE`, `pending_separation_count` the number at `PENDING_SEPARATION`, `separated_count` the number at `SEPARATED`, and `roster_count` the number of the site's employees in any employment status whatsoever.

Bulk roster loads from an HRIS follow the same rules. A site-scoped roster import accepts an `entries` array, each element carrying the same per-person attributes described above, and creates one employee per entry in `ACTIVE` status. The response reports a `created_count` and an `employee_ids` array whose order matches the order in which the `entries` were supplied. As with single hires, the site's `roster_count` and `active_headcount` are recomputed afterwards.

Hiring is also the **backfill control point**, and this is where the programme's rehire discipline bites. Before a hire is admitted — whether individually or through a roster import — the system checks whether any position restriction in status `RESTRICTED` matches the incoming person's `site_id` and `job_title` pair. If one does, the hire is refused with `ERR_BACKFILL_RESTRICTED`; in a roster import every entry is tested before any row is created, so one blocked entry rejects the whole import and leaves no employee behind. Crucially, this check runs *after* expiry evaluation: on every individual hire the system first releases any restriction whose `restricted_until_utc` the logical clock has now passed, and only then tests the remaining restrictions. A seat whose freeze has elapsed is therefore backfillable on the very next request without any explicit release call.

Employees can be listed with optional filters on `site_id`, on `employment_status`, and on `job_title`, alongside the usual `limit` and `offset`.

### 3.3. Proposing Selections and Resolving the Selection Fork

With criteria locked, the lead proposes individuals. A selection is created against a `plan_id` and an `employee_id`, carrying a `proposed_separation_date` — the intended last day of employment — and a `criterion_scores` array of objects each pairing a `criterion_code` with an integer `score` between 0 and 100 inclusive. The set of `criterion_code` values in `criterion_scores` must equal the plan's locked criterion code set **exactly**: neither a missing code nor an extra code nor a code repeated across two entries is tolerated, and any of those failures is refused with `ERR_CRITERION_SCORE_MISMATCH`.

From those scores the system derives the selection's `composite_score`. For each criterion in the plan's locked `selection_criteria`, the criterion's `score` from the submitted sheet is multiplied by that criterion's `weight_pct` and the product is divided by 100; the resulting per-criterion contributions are summed across all locked criteria, and the sum is rounded half up to two decimal places. Because the weights are required to total 100, a candidate scoring identically on every criterion receives that score as their composite. A newly created selection is persisted with `status` of `PROPOSED`, `exemption_reason` and `rescind_reason` null, `notice_status` of `NOT_DELIVERED`, `notice_script_code` and `notice_delivered_utc` null, `notice_days_before_separation` null, and `short_notice_acknowledged` false. Creating it recomputes the plan's `pool_count`. The plan's two population figures are defined over its own selections: `pool_count` is the number of the plan's selections whose `status` is `PROPOSED`, `SELECTED`, `EXEMPTED` or `SEPARATED`, with `RESCINDED` rows excluded, and `selected_count` is the number whose `status` is `SELECTED` or `SEPARATED`.

Two guards protect the proposal itself. An employee may hold at most one selection per plan in any status other than `RESCINDED`; a second live proposal for the same plan-and-employee pair is refused with `ERR_DUPLICATE_SELECTION`. And a proposal whose `proposed_separation_date` falls inside the frozen aggregation window of an already-issued WARN notice for that person's site is refused with `ERR_WARN_WINDOW_COLLISION` — the mechanics of those frozen windows are set out in §3.4.

Selections can also be created in bulk under a plan. The batch payload supplies an `employee_ids` array, a single shared `proposed_separation_date`, and a single shared `criterion_scores` sheet applied to every listed person; the response reports a `created_count` and a `selection_ids` array ordered to match the supplied `employee_ids`. Every rule that governs an individual proposal — criteria locked, exact score-code match, no duplicate, no aggregation-window collision — governs each row of the batch identically, and an `employee_ids` array that names the same person twice is itself a duplicate and is refused with `ERR_DUPLICATE_SELECTION`. Selections may be listed with optional `plan_id`, `employee_id` and `status` filters.

Resolving a proposal is a **fork with radically asymmetric consequences**, and the asymmetry is deliberate. The lead supplies a `decision` of either `SELECT` or `EXEMPT`; those two admissible values resolve the proposal to the selected branch and the exempted branch respectively. Both branches require the plan's `approval_status` to be one of `DRAFT` or `IN_LEGAL_REVIEW`, so a fork cannot be resolved once counsel has approved or the reduction has been executed: a plan standing at `APPROVED` refuses the fork with `ERR_INVALID_PLAN_STATE`, while a plan already `EXECUTED` refuses it with `ERR_INVALID_SELECTION_STATE`.

Taking the **selected branch** (`PROPOSED → SELECTED`) additionally requires the plan's `criteria_status` to be `LOCKED` — an unlocked plan refuses this branch with `ERR_INVALID_PLAN_STATE`, `ERR_CRITERIA_NOT_LOCKED` being reserved for the two proposal endpoints — and sets off a four-hop cascade. The first hop moves the employee from `ACTIVE` to `PENDING_SEPARATION` and copies the selection's `proposed_separation_date` onto the employee's `separation_date`. The second hop, triggered by that employee's status change, recomputes the employee's site: `active_headcount` falls by one, `pending_separation_count` rises by one, and `window_start_date`, `federal_loss_count`, `state_loss_count`, `required_notice_days` and `warn_trigger_status` are all re-derived. The third hop fires when that recomputation moves the site's `warn_trigger_status` away from `NONE`: every reduction plan that holds a selected selection at that site advances its `warn_status` from `NOT_ASSESSED` to `THRESHOLD_PENDING` and re-derives its own `required_notice_days` and `notice_deadline_utc`. The fourth hop propagates the change in the plan's selection set into its compliance paperwork: every OWBPA disclosure of the plan in status `ATTACHED` whose `snapshot_selected_count` or `snapshot_pool_count` no longer matches the plan's current counts becomes `STALE`, and every adverse-impact analysis of the plan in status `CLEARED` becomes `STALE`. Alongside the cascade the plan's own `selected_count`, `pool_count`, `earliest_separation_date`, `owbpa_required` and `owbpa_consideration_days` are recomputed, and the selection's `version` increments by 1.

Taking the **exempted branch** (`PROPOSED → EXEMPTED`) requires that an `exemption_reason` be supplied and non-empty, failing which the request is malformed and refused with `ERR_INVALID_REQUEST`, and it records that reason on the selection. It touches nothing downstream at all: the employee's `employment_status` stays `ACTIVE`, their `separation_date` stays null, no site counter moves, no plan `warn_status` advances, and no disclosure or analysis is invalidated. The only plan-level figure that changes is `pool_count` — an exempted person remains in the analysis pool — while `selected_count` is unaffected. The selection's `version` increments by 1. The contrast is the point: the selected branch mutates four downstream entities and the exempted branch mutates none.

Batch resolution of the fork is available under the plan. It accepts a `selection_ids` array, a shared `decision`, and an optional `exemption_reason`; every listed identifier must name a selection of that same plan, and one naming no selection at all, or a selection belonging to another plan, is refused with `ERR_SELECTION_NOT_FOUND`. Every listed selection is checked for the `PROPOSED` from-state before any of them is mutated, so a single row in another status refuses the whole request without partial effect; otherwise it processes the listed selections strictly in the order supplied. The full per-selection cascade described above runs for each row that takes the selected branch. The response reports `decided_count`, `selected_count` and `exempted_count`.

Rescission is the **compensating action** for a selected decision (`SELECTED → RESCINDED`). It requires a `rescind_reason`, requires that the plan's `approval_status` is not `EXECUTED`, and requires that no severance offer of the selection currently sits in `ISSUED`, `SIGNED` or `EFFECTIVE` status, on pain of `ERR_INVALID_OFFER_STATE`; a live offer means the money has already moved and the selection can no longer be quietly unwound. The compensation runs in three hops. First, the employee returns from `PENDING_SEPARATION` to `ACTIVE` and their `separation_date` is cleared to null. Second, the employee's site recomputes: `active_headcount` rises by one, `pending_separation_count` falls by one, and `window_start_date`, `federal_loss_count`, `state_loss_count`, `required_notice_days` and `warn_trigger_status` are re-derived. Third, if that recomputation leaves no site of the plan with a `warn_trigger_status` other than `NONE`, the plan's `warn_status` returns from `THRESHOLD_PENDING` to `NOT_ASSESSED`. That return arc is guarded on its from-state: it fires only for a plan whose `warn_status` currently reads `THRESHOLD_PENDING`, and a plan whose compliance axis has already advanced past that state — to `NOTICES_ISSUED` or `NOTICE_PERIOD_SATISFIED` — is left standing where it is by this recomputation, however the site recount came out. Independently of that arc, and whatever `warn_status` the plan holds, the plan's `required_notice_days` and `notice_deadline_utc` are re-derived from the plan-level rules of §3.4, which resolve to 0 and null respectively once no site of the plan is triggered. In addition, every `CLEARED` adverse-impact analysis of the plan becomes `STALE` and every `ATTACHED` disclosure whose snapshot no longer matches becomes `STALE`; the `rescind_reason` is recorded; the plan's `selected_count`, `pool_count`, `earliest_separation_date`, `owbpa_required` and `owbpa_consideration_days` are recomputed; and the selection's `version` increments by 1. Rescission also voids any issued WARN notice whose site has returned to `warn_trigger_status` of `NONE`.

### 3.4. Jurisdictional Threshold Determination and WARN Notices

Threshold counting is table-driven. A `SystemAdmin` configures one statute row per jurisdiction: a `jurisdiction` of `FEDERAL` for the national statute, whose `state_code` is recorded as `US`, or a `jurisdiction` of `STATE` for a mini-WARN row, whose `state_code` is the two-letter code of the jurisdiction it governs. Each row carries a `rule_code` citation label that is stamped onto every notice applying it, a `min_loss_count` at or above which the count test is satisfied, a `min_percent` percent-of-workforce test carried to two decimal places where a value of 0 disables the percent test entirely, an `absolute_count` loss figure that triggers regardless of percentage where a value of 0 disables the absolute test, a `notice_days` figure giving the advance notice that jurisdiction demands, a `window_days` aggregation window length, a `counts_part_time` flag, a `min_service_days` service floor, and a `required_content_codes` array listing the content elements a notice under this rule must carry before it may be issued. At most one row may exist per `jurisdiction` and `state_code` pair; a second attempt is refused with `ERR_WARN_RULE_ALREADY_EXISTS`.

The counting algorithm is the same shape for both jurisdictions but differs in two pinned respects, and the two counts are maintained side by side on every site as `federal_loss_count` and `state_loss_count`.

Counting is anchored on the site's `window_start_date`, which is the earliest `separation_date` among that site's employees whose `employment_status` is `PENDING_SEPARATION` or `SEPARATED`. When no such employee exists, the anchor is null, the loss count and the workforce count are both 0, and the threshold is not met. The applicable rule is the `FEDERAL` row for federal counting, and for state counting the `STATE` row whose `state_code` equals the site's `state_code`; when a cascade recomputation finds no such row, that jurisdiction simply contributes a loss count of 0 with the threshold unmet, whereas an explicit notice request naming a jurisdiction with no configured row is refused with `ERR_WARN_RULE_NOT_FOUND`. The window ends `window_days` days after the anchor.

**The interval semantics differ by jurisdiction and must not be unified.** Under the `FEDERAL` rule the window is half-open: a separation date counts when it falls on or after the window start and strictly before the window end. Under a `STATE` rule the window is closed: a separation date counts when it falls on or after the window start and on or before the window end. A separation landing exactly on the window end day is therefore inside a state window and outside the federal one.

The numerator — `employment_loss_count` — counts the site's employees whose `employment_status` is `PENDING_SEPARATION` or `SEPARATED`, whose `separation_date` falls inside the window under the jurisdiction's interval convention, who are not excluded as part-time (that is, either the rule's `counts_part_time` is true, or the person's `is_part_time` is false), and whose service — the number of days from their `hire_date` to their `separation_date` — is at least the rule's `min_service_days`.

The denominator — `workforce_count` — counts the site's employees whose `employment_status` is `ACTIVE`, `PENDING_SEPARATION` or `SEPARATED`, whose `hire_date` is on or before the window start, and who are not excluded as part-time on the same `counts_part_time` test. The service floor is deliberately **not** applied to the denominator: a short-service employee drops out of the numerator but remains in the workforce base. If the denominator comes out at zero, an explicit notice request is refused with `ERR_WARN_WORKFORCE_EMPTY`, while a cascade recomputation instead treats `loss_percent` as 0 and lets the percent test evaluate false. Otherwise `loss_percent` is 100 multiplied by the loss count and divided by the workforce count, rounded half up to two decimal places.

Three tests then run against the rounded percentage and the raw counts. The count test passes when the loss count is at least the rule's `min_loss_count`. The percent test passes when the rule's `min_percent` is 0, or when `loss_percent` is at least `min_percent`. The absolute test passes when the rule's `absolute_count` is greater than 0 and the loss count is at least that `absolute_count`. `threshold_met` is true when both the count test and the percent test pass, or when the absolute test passes on its own. When `threshold_met` is true and the loss count equals the workforce count, the `trigger_type` is `PLANT_CLOSING`; when `threshold_met` is true otherwise, it is `MASS_LAYOFF`; when the threshold is not met it is `NONE`.

The same three values roll up onto the site itself. A site's `warn_trigger_status` is `PLANT_CLOSING` when a triggered jurisdiction's loss count equals its workforce count, otherwise `MASS_LAYOFF` when either jurisdiction reports its threshold met, and otherwise `NONE`. The site's `required_notice_days` is the largest `notice_days` among the jurisdictions whose threshold is met for that site, and is 0 when `warn_trigger_status` is `NONE`.

In practice the two jurisdictions are configured to disagree. A federal row typically excludes part-time employees and imposes a service floor of 180 days, so both short-service and part-time people fall out of the numerator while part-time people also fall out of the denominator. A state row typically counts part-time employees and imposes no service floor at all, so the identical roster produces a strictly larger numerator and a strictly larger denominator under the state rule than under the federal one. Two jurisdictions reaching opposite conclusions on the same data is the expected outcome, not a defect.

Plan-level WARN figures are derived from the sites. A plan's `required_notice_days` is the largest `required_notice_days` among the distinct sites of that plan's selections in `SELECTED` or `SEPARATED` status, and is 0 when no site of the plan is triggered. Its `notice_deadline_utc` is the plan's `earliest_separation_date` taken at midnight UTC, less that many days; it is null whenever `required_notice_days` is 0 or `earliest_separation_date` is null. The plan's `earliest_separation_date` is itself the earliest `proposed_separation_date` among its selections in `SELECTED` or `SEPARATED` status, and is null when that set is empty.

Counsel drafts a notice by naming a `plan_id`, a `site_id`, a `jurisdiction`, and the `content_codes` the notice document carries. Creating the notice runs the counting algorithm for that jurisdiction against that site and **freezes the result onto the row**: `applied_rule_code` records the `rule_code` of the row applied, and `employment_loss_count`, `workforce_count`, `loss_percent`, `threshold_met`, `trigger_type`, `required_notice_days`, `window_start_date` and `window_end_date` all record the determination as made, `required_notice_days` taking the applied rule's `notice_days` whether or not the threshold came out met. The notice's `window_end_date` is its `window_start_date` plus the applied rule's `window_days`, and the interval it stands for is half-open at the end for a `FEDERAL` notice and closed for a `STATE` notice. Its `notice_deadline_utc` is the `window_start_date` at midnight UTC less `required_notice_days` days, and is null whenever `threshold_met` came out false. The notice is persisted with `status` of `DRAFT` and `issued_utc` null. Notices may be listed with optional `plan_id`, `site_id`, `jurisdiction` and `status` filters.

Issuing a notice (`DRAFT → ISSUED`) is counsel's act and demands two things: the notice's `threshold_met` must be true, and its `content_codes` must be a superset of the applied rule's `required_content_codes` — every required code present, extra codes permitted. A notice whose content omits a required code is refused with `ERR_WARN_CONTENT_INCOMPLETE`, and issuing a notice that is not in `DRAFT` is refused with `ERR_INVALID_NOTICE_STATE`. Issuance stamps `issued_utc` from the logical clock and increments the notice's `version` by 1. It also does two things beyond the notice itself. It advances the plan's `warn_status` from `THRESHOLD_PENDING` to `NOTICES_ISSUED`, but only once every site of the plan's selected selections whose `warn_trigger_status` is other than `NONE` now carries an issued notice for that plan-and-site pair. And it **freezes the site's aggregation window**: from that moment, a later proposal whose `proposed_separation_date` falls inside the notice's frozen interval — on or after `window_start_date` and strictly before `window_end_date` for a `FEDERAL` notice, or on or after `window_start_date` and on or before `window_end_date` for a `STATE` notice — is refused with `ERR_WARN_WINDOW_COLLISION`.

The freeze is released the same way it was created. Whenever any recomputation moves a site from a triggered `warn_trigger_status` back to `NONE` — a rescission being the ordinary cause — every issued notice for that site moves `ISSUED → VOID`, its frozen aggregation window is released, and its `version` increments by 1.

### 3.5. Adverse-Impact Testing and Legal Clearance

Before counsel will approve anything, the selection set must be tested for disparate impact. An analysis is created by `EmploymentCounsel` against a `plan_id` with a chosen `method` — either `IMPACT_RATIO` or `STANDARD_DEVIATION` — and the `expected_plan_version` guard described in §2.8. The statistic is computed at creation, and the row is persisted directly in whichever of `COMPUTED` or `FLAGGED` the outcome dictates; there is no separate evaluation step. Creating a new analysis supersedes every earlier analysis of the same plan, moving each of them into `SUPERSEDED` from whichever of `COMPUTED`, `FLAGGED` or `CLEARED` it held, incrementing each superseded row's `version` by 1, and incrementing the plan's `version` by 1 as well.

The pool is the plan's own selections in status `PROPOSED`, `SELECTED`, `EXEMPTED` or `SEPARATED`; rescinded selections are excluded, and an employee who holds no selection never enters the pool even when they sit in the same decisional unit. The analysis records `pool_count` as the size of that pool and `selected_count` as the number of pooled rows in `SELECTED` or `SEPARATED` status. If the pool is empty, or nobody in it is selected, the request is refused with `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`.

For each `demographic_code` present in the pool, the system computes that class's selection rate as its selected count divided by its pooled count, using the unrounded quotient purely for ordering. The `focal_class_code` is the class with the smallest such rate, with ties broken by class code ascending so that `CLASS_A` precedes `CLASS_B` which precedes `CLASS_C`. The focal class's pooled and selected counts are recorded as `focal_pool_count` and `focal_selected_count`. If removing the focal class leaves no reference group at all — that is, the pool count and the focal pooled count are equal — the request is refused with `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`.

The `focal_rate` is the focal selected count divided by the focal pooled count, rounded half up to four decimal places. The `reference_rate` is the pool's selected count less the focal selected count, divided by the pool count less the focal pooled count, again rounded half up to four decimal places. A `reference_rate` of zero also yields `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`, since no ratio against it is meaningful. The `shortfall_count` is that recorded four-decimal `reference_rate` multiplied by the focal pooled count and rounded up to the next whole number, less the focal selected count, with any negative result reported as 0. The `small_sample_suppressed` flag is true when the focal pooled count is below 3 — a class of one or two people cannot carry a statistical finding, and the flag suppresses flagging no matter what the statistic says.

The two methods then diverge on identical inputs. Under `IMPACT_RATIO`, the `impact_ratio` is the recorded `focal_rate` divided by the recorded `reference_rate` — that is, the two values as already rounded to four decimal places, not their raw unrounded quotients — with the result itself then rounded half up to four decimal places, `standard_deviations` is null, and the analysis is flagged when the impact ratio is strictly below the four-fifths threshold of 0.80 and small-sample suppression is not in force. The comparison is strict, so an impact ratio of exactly 0.8000 is not flagged. Under `STANDARD_DEVIATION`, `impact_ratio` is null and the hypergeometric shortfall is measured instead: the expected number of focal selections is the focal pooled count multiplied by the pool's selected count and divided by the pool count; the variance is the pool's selected count, multiplied by the pool count less the selected count, multiplied by the focal pooled count, multiplied by the pool count less the focal pooled count, all divided by the product of the pool count, the pool count again, and the pool count less one; and the standard deviation is the square root of that variance. `standard_deviations` is 0 when the standard deviation is 0, and otherwise the expected focal selections less the actual focal selections, divided by the standard deviation, rounded half up to four decimal places. The analysis is flagged when `standard_deviations` is at least the threshold of 2.0 and small-sample suppression is not in force; that comparison is inclusive, so exactly 2.0000 is flagged. Running both methods over one pool routinely yields opposite conclusions on the same data — that is a property of the statistics, and the system reports each faithfully.

Clearance is counsel's judgement call. Clearing an analysis (`COMPUTED → CLEARED` or `FLAGGED → CLEARED`) requires a `justification` that is supplied and non-empty, records that business-necessity narrative on the row along with `cleared_by_user_id`, and increments the analysis's `version` by 1. Attempting to clear a row that is already `CLEARED`, or one that has become `SUPERSEDED` or `STALE`, is refused with `ERR_INVALID_ANALYSIS_STATE`. A cleared analysis does not stay cleared through changes to the underlying pool: whenever a selection of the plan subsequently enters `SELECTED`, `EXEMPTED` or `RESCINDED`, every `CLEARED` analysis of the plan moves `CLEARED → STALE` with its `version` incremented by 1. Analyses may be listed with optional `plan_id` and `status` filters.

Legal review is the governance gate. Submitting a plan for review (`DRAFT → IN_LEGAL_REVIEW`) is the lead's act and requires that the plan's `criteria_status` is `LOCKED` and that its `selected_count` is at least 1, either shortfall being refused with `ERR_INVALID_PLAN_STATE`; it records the calling `X-User-ID` as `submitted_by_user_id` and increments the plan's `version` by 1. Re-submission after a return is the same transition and overwrites `submitted_by_user_id` with the new submitter.

Counsel then renders a `decision` of either `APPROVE` or `RETURN`, optionally accompanied by a `comment`. Both outcomes require that the acting `X-User-ID` differ from the plan's `submitted_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`. Approving the plan (`IN_LEGAL_REVIEW → APPROVED`) additionally requires that the plan's most recent adverse-impact analysis, ordered by `created_at` descending with `version` descending as the tie-break, exists and stands in `CLEARED` status; an absent analysis, or a latest analysis sitting in `COMPUTED`, `FLAGGED`, `SUPERSEDED` or `STALE`, is refused with `ERR_IMPACT_ANALYSIS_NOT_CLEARED`. Approval records `approved_by_user_id` from the calling `X-User-ID` and increments the plan's `version` by 1. Returning the plan (`IN_LEGAL_REVIEW → DRAFT`) increments `legal_return_count` by 1, clears `submitted_by_user_id` back to null, and increments the plan's `version` by 1; a plan may be returned and re-submitted any number of times.

### 3.6. The OWBPA Decisional-Unit Disclosure

Whenever anyone forty or older is asked to sign a release, the Older Workers Benefit Protection Act demands a disclosure describing the decisional unit and the ages of those selected and not selected within it. The plan tracks whether that obligation has arisen: `owbpa_required` is true when at least one selection of the plan in `SELECTED` or `SEPARATED` status belongs to an employee whose age on that selection's `proposed_separation_date` is 40 or more.

The plan also tracks how long protected employees get to think. `owbpa_consideration_days` is 45 whenever the plan's `selected_count` is at least 2, and 21 otherwise — the statute's group-programme window versus its individual window — and it is applied only to offers made to employees aged 40 or over.

Counsel generates a disclosure by naming a `plan_id`. The **decisional unit** is every employee whose `site_id` is among the site identifiers of that plan's selections in `PROPOSED`, `SELECTED`, `EXEMPTED` or `SEPARATED` status, and whose own `employment_status` is `ACTIVE`, `PENDING_SEPARATION` or `SEPARATED`. The disclosure is about the unit, not about the selected group: selected and non-selected employees alike are counted, including people who hold no selection at all.

Ages are measured against a single anchor, the plan's `earliest_separation_date`. When that anchor is null — no selection of the plan has yet been selected — the disclosure cannot be computed and the request is refused with `ERR_INVALID_PLAN_STATE`. Each unit member's age is their completed whole years between `birth_date` and the anchor. From those ages the disclosure records `eligible_count` as the number of unit members aged 40 or over, `selected_count` as the number of unit members holding a selection of this plan in `SELECTED` or `SEPARATED` status, and `non_selected_count` as the size of the unit less that selected figure. It records `min_age` and `max_age` as the lowest and highest unit ages, and `age_bands` as one entry per distinct age actually held by a unit member, each entry carrying that `age` together with its own `selected_count` and `non_selected_count`, sorted by age ascending. No band is invented for an age nobody holds.

Three further values are snapshotted at generation. `decisional_unit_name` is copied verbatim from the plan, `consideration_days` captures the plan's `owbpa_consideration_days` as it stood at generation, and `snapshot_selected_count` and `snapshot_pool_count` capture the plan's `selected_count` and `pool_count`. The disclosure is persisted with `status` of `ATTACHED` and a `generated_utc` stamp from the logical clock. Generating a new disclosure supersedes every earlier disclosure of the same plan, moving each from `ATTACHED` or `STALE` into `SUPERSEDED` with its `version` incremented by 1, and incrementing the plan's `version` by 1.

Those two snapshot counts are the staleness detector. Whenever a decide or a rescind moves the plan's `selected_count` or `pool_count` away from what a disclosure recorded, that disclosure moves `ATTACHED → STALE` and its `version` increments by 1 — the paperwork no longer describes the population it claims to describe. Disclosures may be listed with optional `plan_id` and `status` filters.

### 3.7. Notification Logistics and Manager Scripting

Individual notification is the moment the reduction becomes real to the person affected, and the system gates it hard. Before a notice may be delivered for a selection, three conditions must hold: the plan's `approval_status` must be `APPROVED`, failing which the request is refused with `ERR_PLAN_NOT_APPROVED`; the plan's latest adverse-impact analysis must stand in `CLEARED` status, failing which it is refused with `ERR_IMPACT_ANALYSIS_NOT_CLEARED`; and the delivery must satisfy the notice-period and scripting rules below.

Delivery is recorded by the `RestructuringLead` with a `script_code` naming the manager script used, and an optional `acknowledge_short_notice` flag. Recording it moves `notice_status` from `NOT_DELIVERED` to `DELIVERED`, stamps `notice_delivered_utc` from the logical clock, records the supplied script as `notice_script_code`, and derives `notice_days_before_separation` as the number of whole calendar days from the date part of `notice_delivered_utc` to the selection's `proposed_separation_date`. That derived figure stays null while the notice is undelivered. Delivery increments the selection's `version` by 1.

The notice-period rule compares that derived figure against the site's requirement. When `notice_days_before_separation` is less than the site's `required_notice_days`, the delivery is refused with `ERR_NOTICE_PERIOD_INSUFFICIENT` — unless the caller passes `acknowledge_short_notice` as true, in which case the delivery is accepted and the selection's `short_notice_acknowledged` flag is set to true to record that the shortfall was taken knowingly. A delivery at or beyond the required number of days is always accepted and leaves `short_notice_acknowledged` false.

Scripting is jurisdiction-sensitive. Three scripts exist: `MANAGER_SCRIPT_STANDARD`, `MANAGER_SCRIPT_REMOTE` and `MANAGER_SCRIPT_UNION`. Whenever the state mini-WARN rule applying to that employee's site lists `UNION_NOTICE` among its `required_content_codes`, the only acceptable `script_code` is `MANAGER_SCRIPT_UNION`; a delivery using either of the other two scripts in such a jurisdiction is refused with `ERR_SCRIPT_JURISDICTION_MISMATCH`. Where the state rule does not require union notice, all three scripts are acceptable.

### 3.8. Pricing the Separation Package

Severance is priced by the `BenefitsAdministrator` against a `selection_id`, choosing a `variant` of either `STANDARD` or `ENHANCED_RELEASE`, and supplying the `expected_selection_version` guard described in §2.8. The offer copies the selection's plan onto its own `plan_id`, and creating it increments the referenced selection's `version` by 1. Pricing runs at creation and every monetary field is frozen onto the row from that moment; a later change to the employee's salary or the site's notice requirement does not re-price an existing offer.

Five gates precede pricing, and their relative precedence is fixed by §2.6. The referenced selection must be in `SELECTED` status, failing which the request is refused with `ERR_INVALID_SELECTION_STATE`. The plan's latest adverse-impact analysis must be `CLEARED`, failing which `ERR_IMPACT_ANALYSIS_NOT_CLEARED`. For an employee whose `age_at_separation` is 40 or over, the plan must carry an OWBPA disclosure in status `ATTACHED` or `STALE` — that is, a disclosure that exists and has not been superseded — failing which `ERR_OWBPA_DISCLOSURE_MISSING`; and that disclosure must actually be `ATTACHED`, its `snapshot_selected_count` and `snapshot_pool_count` still matching the plan's current `selected_count` and `pool_count`, failing which `ERR_OWBPA_DISCLOSURE_STALE`. The distinction matters: a plan with a merely stale disclosure fails on staleness, not on absence. Finally the selection's `notice_status` must already be `DELIVERED`, failing which `ERR_NOTICE_NOT_DELIVERED` — nobody is priced before they are told. Where the disclosure gate applies, the `ATTACHED` disclosure that satisfied it is pinned onto the offer as `owbpa_disclosure_id`; for a release to an employee under 40 that field stays null.

Pricing itself runs in a **pinned order**, and the order is load-bearing because the benefit tier is keyed on a subtotal that is itself a component of the final total.

First, the weekly rate. `weekly_rate_cents` is the employee's `annual_base_cents` divided by 52 and rounded half up to a whole number of cents. This rounding happens **before** any multiplication; folding the division and the multiplication into a single expression and rounding once at the end produces a different, incorrect figure.

Second, the base week entitlement, tiered on the employee's `years_of_service` — the whole number of completed years obtained by taking the days from `hire_date` to `separation_date`, dividing by 365, and discarding any fraction. Under two completed years the entitlement is 2 weeks. From two up to but not including five years it is 4 weeks plus 1 further week for each completed year beyond the second. From five up to but not including ten years it is 7 weeks plus 1.5 further weeks for each completed year beyond the fifth. At ten years and above it is 14.5 weeks plus 2 further weeks for each completed year beyond the tenth. The entitlement is then capped at 52 weeks, a full year of pay being the programme's ceiling.

Third, the variant is applied to produce `weeks_awarded`. The `STANDARD` variant discards any half week, taking the largest whole number of weeks not exceeding the capped entitlement, and grants no bonus. The `ENHANCED_RELEASE` variant retains half-week precision and adds a release bonus of 2 further weeks on top of the capped entitlement. Identical inputs therefore yield materially different awards under the two variants, which is the point of offering an enhanced release in exchange for a signature.

Fourth, `base_severance_cents` is the weekly rate multiplied by `weeks_awarded`, rounded half up exactly once.

Fifth comes the notice shortfall. `notice_shortfall_days` is the site's `required_notice_days` less the selection's `notice_days_before_separation`, with any negative result reported as 0; where the site is not triggered its requirement is 0, and where the notice is undelivered the actual figure is treated as 0. The daily rate is the weekly rate divided by 7 and rounded half up to whole cents — again, rounded **before** multiplying — and `notice_pay_offset_cents` is that daily rate multiplied by `notice_shortfall_days`, rounded half up.

Sixth, the benefit tier. The tier key is a pre-benefit subtotal formed by adding `notice_pay_offset_cents` to `base_severance_cents`. When that subtotal is below 1000000 cents, `benefit_subsidy_months` is 3; when it is at least 1000000 cents but below 2500000 cents, it is 6; and at 2500000 cents or above it is 9. The monthly subsidy is the employee's `monthly_premium_cents` multiplied by 0.65 — the employer covering sixty-five per cent of the group-health premium — and rounded half up to whole cents; `benefit_subsidy_cents` is that monthly figure multiplied by `benefit_subsidy_months`.

Seventh, outplacement follows the benefit tier. That tier is `PREMIUM` when `benefit_subsidy_months` is 6 or more and `STANDARD` otherwise, and it governs `outplacement_fee_cents`, which is 350000 cents for a premium engagement and 120000 cents for a standard one; the tier itself is not a field of the offer representation — only `outplacement_fee_cents` appears there — and `outplacement_tier` is carried on the employee record instead. (On the employee record the same tier is reported as `NONE` while no signed offer is in force, `STANDARD` when the subsidy carried by the signed offer runs from 1 to 5 months, and `PREMIUM` when it runs to 6 months or more.)

Eighth and last, `total_separation_cost_cents` is the sum of `base_severance_cents`, `notice_pay_offset_cents`, `benefit_subsidy_cents` and `outplacement_fee_cents`. Every step is a whole number of cents and each rounding happens exactly where the numbered step places it and nowhere else.

The offer is persisted with `status` of `DRAFT`, an `issue_count` of 0, a `consideration_days_applied` of 0, and `issued_utc`, `signed_utc`, `revoked_utc`, `consideration_deadline_utc`, `revocation_deadline_utc` and `blocking_window_end_utc` all null. Offers may be listed with optional `selection_id`, `plan_id`, `owbpa_disclosure_id` and `status` filters.

### 3.9. The Release Cycle, Both Ledgers, and the Consideration Windows

An offer that has been priced is not yet an offer to anyone. The `BenefitsAdministrator` issues it, and issuance is the point at which money is committed. Issuance is admissible from `DRAFT` and — this is the cycle that makes the domain interesting — again from `REVOKED`, so the sequence `ISSUED → SIGNED → REVOKED → ISSUED` is a legitimate loop. Attempting to issue from any other status is refused with `ERR_INVALID_OFFER_STATE`.

Every issuance requires that the underlying selection is still `SELECTED`, that the offer's `issue_count` is below 3, and that the plan has budget headroom: the plan's `severance_reserve_cents` plus this offer's `total_separation_cost_cents` must be no greater than its `severance_budget_cents`. A fourth issuance is refused with `ERR_OFFER_REISSUE_LIMIT`, and an issuance that would push the reserve past the ceiling is refused with `ERR_SEVERANCE_BUDGET_EXCEEDED`. Re-issuing after a revocation carries one extra condition: the logical clock must have advanced strictly past the offer's `blocking_window_end_utc` plus one day.

Issuance stamps `issued_utc` from the logical clock, sets `consideration_days_applied`, derives `consideration_deadline_utc`, increments `issue_count` by 1, adds the offer's `total_separation_cost_cents` to the plan's `severance_reserve_cents`, and increments the offer's `version` by 1. A re-issuance from `REVOKED` re-stamps `issued_utc` and recomputes `consideration_deadline_utc` from that fresh issuance rather than carrying the old deadline forward, and clears `signed_utc`, `revoked_utc` and `revocation_deadline_utc` back to null.

The consideration window is age-driven and frozen at issuance. When the employee's `age_at_separation` is 40 or more, `consideration_days_applied` is 45 if the owning plan's `selected_count` is at least 2 at that moment, and 21 otherwise. When the employee is under 40 the OWBPA does not apply and `consideration_days_applied` is 14. The comparison against 40 is inclusive, so an employee who turns exactly 40 on their separation date is protected. `consideration_deadline_utc` is `issued_utc` advanced by `consideration_days_applied` whole days.

Signing is the separating employee's act, and only theirs: `X-User-ID` must equal the `employee_id` of the offer's selection. Signing is admissible only from `ISSUED`, and only while the logical clock stands at or before `consideration_deadline_utc`. A sign attempt made after that deadline fails with `ERR_CONSIDERATION_PERIOD_EXPIRED` and leaves the offer in `EXPIRED` — the attempt is rejected but the offer's own lifecycle has ended, its `total_separation_cost_cents` is subtracted back out of the plan's `severance_reserve_cents`, and its `version` increments by 1. A successful signature (`ISSUED → SIGNED`) stamps `signed_utc`, derives `revocation_deadline_utc`, and increments the offer's `version` by 1. The revocation window is likewise age-driven: for an employee aged 40 or over the deadline is `signed_utc` plus 7 days, the statutory seven-day revocation right; for an employee under 40 it is `signed_utc` itself, leaving no revocation window at all.

Signing cascades twice. The first hop reaches the employee: `release_signed` becomes true, `benefit_continuation_status` moves `NONE → ACTIVE`, and the employee's `benefit_subsidy_months` and `benefit_subsidy_cents` are copied from the offer, their `outplacement_tier` being set from that copied month count by the employee-record rule of §3.8. The second hop reaches the plan: because that employee's benefit continuation became active, the employee's `benefit_subsidy_cents` is added to the plan's `benefit_liability_cents`.

Revoking is also the separating employee's act alone, is admissible only from `SIGNED`, and only while the logical clock stands at or before `revocation_deadline_utc`; a later attempt is refused with `ERR_REVOCATION_WINDOW_CLOSED`. Revocation requires a `revocation_reason`, stamps `revoked_utc`, and unwinds both cascades exactly. The employee's `release_signed` returns to false, their `benefit_continuation_status` moves `ACTIVE → TERMINATED`, their `benefit_subsidy_months` and `benefit_subsidy_cents` reset to 0 and their `outplacement_tier` to `NONE`; the plan's `benefit_liability_cents` has exactly the subsidy the signature added subtracted back out; and the plan's `severance_reserve_cents` has the offer's `total_separation_cost_cents` subtracted back out. The offer's `version` increments by 1.

Both plan ledgers are defined as aggregates rather than running tallies, and must be recomputed from the contributing rows on every contributing transition. `severance_reserve_cents` is the sum of `total_separation_cost_cents` across the plan's offers whose `status` is `ISSUED`, `SIGNED` or `EFFECTIVE`; offers sitting in `DRAFT`, `REVOKED` or `EXPIRED` contribute nothing. `benefit_liability_cents` is the sum of `benefit_subsidy_cents` across the employees who hold a selection of this plan and whose `benefit_continuation_status` is `ACTIVE`; employees at `NONE` or `TERMINATED` contribute nothing. The round-trip invariant of §2.9 applies here in its strongest form: issue, sign, then revoke must leave the reserve at exactly its pre-issue value and the liability at exactly its pre-signature value.

One offer per person may occupy the field at a time. A new offer may not be priced, and an existing one may not be issued, while another offer for the same employee still occupies the closed interval from its `issued_utc` through its `blocking_window_end_utc`, extended by a one-day cooldown; concretely, the request is refused with `ERR_OFFER_WINDOW_CONFLICT` while the logical clock stands at or before that other offer's `blocking_window_end_utc` plus one day. The `blocking_window_end_utc` follows the offer's own status: it is `consideration_deadline_utc` while the offer is `ISSUED`, `revocation_deadline_utc` while it is `SIGNED`, `revoked_utc` once it is `REVOKED`, `consideration_deadline_utc` once it is `EXPIRED`, and null while it is `DRAFT` or `EFFECTIVE`.

### 3.10. Executing the Reduction and Freezing the Vacated Seats

Execution is the lead's final act and the only transition that separates anybody. It is admissible only from `APPROVED`, and it demands two things of the programme's state. Every selection of the plan in `SELECTED` status must have `notice_status` of `DELIVERED`, failing which the request is refused with `ERR_NOTICE_NOT_DELIVERED`. And for every distinct site of those selections whose `warn_trigger_status` is other than `NONE`, an issued WARN notice must exist for that plan-and-site pair; a triggered site without one is refused with `ERR_WARN_NOTICE_REQUIRED`.

Execution advances `approval_status` from `APPROVED` to `EXECUTED` and runs a three-hop cascade. In the first hop every selection of the plan in `SELECTED` status moves to `SEPARATED`, each incrementing its own `version` by 1. In the second hop, because a selection entered `SEPARATED`, its employee moves from `PENDING_SEPARATION` to `SEPARATED`. In the third hop, because an employee entered `SEPARATED`, a position restriction is created for that person in status `RESTRICTED` with `restricted_until_utc` set to the current logical clock plus 90 days, and that employee's site recomputes its counters — `pending_separation_count` falls by one and `separated_count` rises by one, with `roster_count` unchanged throughout, exactly as the headcount identity of §2.9 requires.

Execution also settles the release paperwork and the compliance axis. Every severance offer of the plan sitting in `SIGNED` whose `revocation_deadline_utc` the logical clock has already passed moves `SIGNED → EFFECTIVE` and is frozen — no further transition of any kind is possible on an effective offer — with its `version` incremented by 1. On the compliance axis, `warn_status` becomes `NOTICE_PERIOD_SATISFIED` in the same request, arriving there from `NOTICES_ISSUED` on a plan that had triggered sites, and directly from `NOT_ASSESSED` on a plan no site of which was ever triggered. The plan's own `version` increments by 1.

The position restrictions created by that third hop are the programme's backfill control, and they are created **only** by the execution cascade — there is no way to post one directly. Each restriction records the separated incumbent as `employee_id`, copies that person's `site_id` and `job_title` at creation, and holds `restriction_status` of `RESTRICTED` with `waiver_reason` and `waived_by_user_id` null. Together the `site_id` and `job_title` form the key that the hiring check of §3.2 tests against. Restrictions may be listed with optional `employee_id`, `site_id`, `job_title` and `restriction_status` filters — that listing is the only discovery channel for rows the cascade created.

A restriction leaves `RESTRICTED` by one of two routes. `EmploymentCounsel` may waive it (`RESTRICTED → WAIVED`) with a `waiver_reason` that is supplied and non-empty, recording that reason together with `waived_by_user_id` from the acting `X-User-ID` and incrementing the restriction's `version` by 1; waiving a restriction that is not `RESTRICTED` is refused with `ERR_INVALID_RESTRICTION_STATE`. Alternatively the freeze simply expires: once the logical clock stands strictly past `restricted_until_utc`, the restriction becomes `RELEASED` with its `version` incremented by 1. That expiry is evaluated on every hire and on every read of the restriction, so the transition surfaces without any explicit request. Either route unblocks hiring for that `site_id` and `job_title` pair.

## 4. Endpoint Definitions

The table below lists every operation the API exposes. Endpoints that bring a new resource into existence answer with HTTP 201; endpoints that read or modify an existing resource answer with HTTP 200. The request and response payloads are not repeated here — the input fields each operation accepts, the values it derives, and the cascades it sets off are specified in the narratives of §3, and the envelope that wraps every payload is specified in §2.2.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/reduction-plans` | Open a reduction-in-force plan with its documented selection criteria. | `RestructuringLead` |
| GET | `/reduction-plans/{id}` | Read a plan including both status axes and both ledger rollups. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/reduction-plans/{id}/lock-criteria` | Freeze the documented selection criteria so selections may be scored against them. | `RestructuringLead` |
| POST | `/reduction-plans/{id}/submit-legal-review` | Hand the plan to employment counsel; records the submitting user for the segregation-of-duties check. | `RestructuringLead` |
| POST | `/reduction-plans/{id}/legal-decision` | Counsel approves the plan or returns it to drafting. | `EmploymentCounsel` |
| POST | `/reduction-plans/{id}/execute` | Carry out the reduction: separate every noticed selection and freeze the vacated seats. | `RestructuringLead` |
| POST | `/reduction-plans/{id}/selection-batch` | Create one proposed selection per listed employee with a shared separation date and score sheet. | `RestructuringLead` |
| POST | `/reduction-plans/{id}/decide-batch` | Resolve the selection fork for a list of selections in one request. | `RestructuringLead` |
| POST | `/sites` | Register a single site of employment for WARN counting. | `RestructuringLead` |
| GET | `/sites/{id}` | Read a site including both jurisdictions' loss counts and the derived trigger status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/sites/{id}/roster-import` | HRIS roster load: create many employee rows at this site in one request. | `RestructuringLead` |
| POST | `/employees` | Hire one person onto a site roster; also the backfill control point. | `RestructuringLead` |
| GET | `/employees/{id}` | Read one employee including derived separation, benefit and outplacement fields. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/employees` | List employees, filterable by site, employment status and job title. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/selections` | Propose one employee for the reduction, scored against the plan's locked criteria. | `RestructuringLead` |
| GET | `/selections/{id}` | Read one selection including notice fields and the current version. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/selections` | List selections, filterable by plan, employee and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/selections/{id}/decide` | Resolve the fork for one selection. | `RestructuringLead` |
| POST | `/selections/{id}/rescind` | Compensating action for a select decision; restores employee, site counters and WARN posture. | `RestructuringLead` |
| POST | `/selections/{id}/deliver-notice` | Record the manager-script delivery of the individual notice at the current logical clock. | `RestructuringLead` |
| POST | `/warn-rules` | Configure the federal statute row or a state mini-WARN row. | `SystemAdmin` |
| GET | `/warn-rules/{id}` | Read one configured WARN rule. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/adverse-impact-analyses` | Run the adverse-impact statistic over the plan's current selection pool. | `EmploymentCounsel` |
| GET | `/adverse-impact-analyses/{id}` | Read one analysis including both statistics' fields and the suppression flag. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/adverse-impact-analyses` | List analyses, filterable by plan and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/adverse-impact-analyses/{id}/clear` | Record the business-necessity justification that clears an analysis. | `EmploymentCounsel` |
| POST | `/owbpa-disclosures` | Generate the OWBPA decisional-unit disclosure and snapshot the plan counts behind it. | `EmploymentCounsel` |
| GET | `/owbpa-disclosures/{id}` | Read one disclosure including its age bands and staleness snapshot. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/owbpa-disclosures` | List disclosures, filterable by plan and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/warn-notices` | Determine the WARN threshold for one site under one jurisdiction and draft the notice. | `EmploymentCounsel` |
| GET | `/warn-notices/{id}` | Read one notice including its frozen determination. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/warn-notices` | List notices, filterable by plan, site, jurisdiction and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/warn-notices/{id}/issue` | Issue the notice; freezes the site's aggregation window against later selections. | `EmploymentCounsel` |
| POST | `/severance-offers` | Price a severance offer for a selected employee. | `BenefitsAdministrator` |
| GET | `/severance-offers/{id}` | Read one offer including every computed monetary field and both deadline stamps. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin`, `SeparatingEmployee` |
| GET | `/severance-offers` | List offers, filterable by selection, plan, pinned disclosure and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/severance-offers/{id}/issue` | Deliver the offer to the employee and reserve its cost against the plan budget. | `BenefitsAdministrator` |
| POST | `/severance-offers/{id}/sign` | The separating employee signs the release. | `SeparatingEmployee` |
| POST | `/severance-offers/{id}/revoke` | The separating employee exercises the seven-day revocation right. | `SeparatingEmployee` |
| GET | `/position-restrictions/{id}` | Read one rehire restriction. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| GET | `/position-restrictions` | List rehire restrictions, filterable by employee, site, job title and status. | `RestructuringLead`, `EmploymentCounsel`, `BenefitsAdministrator`, `SystemAdmin` |
| POST | `/position-restrictions/{id}/waive` | Counsel waives a rehire restriction so the seat may be backfilled early. | `EmploymentCounsel` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied instant. | `SystemAdmin` |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in the `error_id` field of the envelope's `data` object, together with the HTTP status shown. The circumstances that raise each identifier are given in the narratives of §2 and §3; the relative precedence when several apply at once is fixed by the ladder in §2.6.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 |
| `ERR_SELECTION_NOT_FOUND` | 404 |
| `ERR_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_RESTRICTION_NOT_FOUND` | 404 |
| `ERR_WARN_RULE_NOT_FOUND` | 404 |
| `ERR_NOT_OFFER_RECIPIENT` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_PLAN_STATE` | 409 |
| `ERR_INVALID_SELECTION_STATE` | 409 |
| `ERR_INVALID_ANALYSIS_STATE` | 409 |
| `ERR_INVALID_NOTICE_STATE` | 409 |
| `ERR_INVALID_OFFER_STATE` | 409 |
| `ERR_INVALID_RESTRICTION_STATE` | 409 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_STALE_SELECTION_VERSION` | 412 |
| `ERR_CRITERIA_NOT_LOCKED` | 422 |
| `ERR_CRITERIA_WEIGHT_INVALID` | 422 |
| `ERR_CRITERION_SCORE_MISMATCH` | 422 |
| `ERR_IMPACT_ANALYSIS_NOT_CLEARED` | 422 |
| `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA` | 422 |
| `ERR_OWBPA_DISCLOSURE_MISSING` | 422 |
| `ERR_OWBPA_DISCLOSURE_STALE` | 422 |
| `ERR_NOTICE_NOT_DELIVERED` | 422 |
| `ERR_WARN_NOTICE_REQUIRED` | 422 |
| `ERR_NOTICE_PERIOD_INSUFFICIENT` | 422 |
| `ERR_CONSIDERATION_PERIOD_EXPIRED` | 422 |
| `ERR_REVOCATION_WINDOW_CLOSED` | 422 |
| `ERR_OFFER_WINDOW_CONFLICT` | 409 |
| `ERR_WARN_WINDOW_COLLISION` | 409 |
| `ERR_DUPLICATE_SELECTION` | 409 |
| `ERR_WARN_CONTENT_INCOMPLETE` | 422 |
| `ERR_WARN_RULE_ALREADY_EXISTS` | 409 |
| `ERR_WARN_WORKFORCE_EMPTY` | 422 |
| `ERR_OFFER_REISSUE_LIMIT` | 422 |
| `ERR_PLAN_NOT_APPROVED` | 422 |
| `ERR_SCRIPT_JURISDICTION_MISMATCH` | 422 |
| `ERR_BACKFILL_RESTRICTED` | 409 |
| `ERR_SEVERANCE_BUDGET_EXCEEDED` | 422 |
