# CTE Program Of Study & Federal Reporting API — Product Requirements Document

## 1. Introduction

A district career and technical education (CTE) office lives at the intersection of three authorities that rarely agree on a calendar: a state approval agency that signs off on program sequences, a federal grant program that dictates what money may buy, and a high school registrar's office that produces the student records everything is ultimately measured against. Today that reconciliation happens in spreadsheets. A program of study is drafted, walked past an advisory committee, endorsed by a vote nobody can later reconstruct, approved by the state, funded out of a grant whose remaining balance is guessed at, and finally judged against performance targets that were negotiated by email. When a target is missed twice, the sanction that follows has to reach backwards through every one of those layers — and the office has no mechanism that does so reliably.

This document specifies the API that replaces that spreadsheet. The service is mounted under `/cte` and owns four intertwined records of truth: the **program of study** (a secondary-to-postsecondary course sequence with an approved industry-credential list, an instructor roster, and a comprehensive local needs assessment behind it), the **advisory committee** (whose quorate, employer-weighted meetings are the evidence that unlocks approval), the **federal grant award** (whose obligation ledger must balance to the cent at all times), and the **performance indicator** (whose target level is negotiated offer-by-offer between the district and the state, then scored once the reporting year closes). Each of these is a compliance artefact: the answer to "why was this allowed?" must be derivable from stored fields, not from institutional memory.

Two design commitments run through everything that follows. First, **segregation of duties is structural, not advisory** — the operator who authors a program may not certify its needs assessment, the operator who requests a purchase may not certify its allowability, and the party holding the standing negotiation offer may not accept it. Second, **every derived number is recomputed from its inputs rather than accumulated** — the grant ledger, the alignment index, the concentrator classification and the performance actuals are all rebuilt from scratch whenever an input moves, so that a void is an exact compensation for a certification and a reversed credit posting leaves no residue.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operators, Roles and Access Control

Every request to this API carries two headers. `X-User-ID` identifies the operator making the call, and `X-User-Role` declares the capacity in which they are acting. Both must be present and non-empty, and `X-User-Role` must name one of the five roles the system recognises; a request that fails any part of that check is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is examined. When the headers are well-formed but the named role is not permitted to invoke the endpoint being called, the response is `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are `CteDirector`, `StateComplianceReviewer`, `GrantFiscalOfficer`, `CommitteeChair`, and `SchoolRegistrar`.

A `CteDirector` is the district CTE director. This role authors programs of study, builds out the course sequence and the approved credential list, charters advisory committees and seats their members, requests grant expenditures, assigns educators, and drafts improvement plans. A `StateComplianceReviewer` acts for the state: it certifies needs assessments, returns compliance findings, grants state approval, verifies industry-experience hours, opens performance indicators, participates in level negotiation, closes reporting years, and rules on improvement plans. A `GrantFiscalOfficer` owns the money — recording awards, certifying or disallowing allowable use, obligating purchase orders and voiding charges — and never authors a program nor requests the charges it certifies. A `SchoolRegistrar` enrolls students, posts and reverses course credits, records exits, and files credential attainments. A `CommitteeChair` is the seated chair of exactly one advisory committee and may schedule that committee's meetings and file or amend its minutes.

Four of the five roles carry **opaque** identities. When `X-User-Role` is `CteDirector`, `StateComplianceReviewer`, `GrantFiscalOfficer` or `SchoolRegistrar`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow calls for an audit anchor — as `authored_by_user_id` and `clna_certified_by_user_id` on a program of study, as `requested_by_user_id` and `certified_by_user_id` on an expenditure, and as `last_offer_by_user_id` on a performance indicator — and it compares those recorded values against the acting `X-User-ID` when segregation of duties is at stake, but it never resolves `X-User-ID` to the `id` of a stored record.

`CommitteeChair` is the one **entity-backed** role. When `X-User-Role` is `CommitteeChair`, `X-User-ID` is the `id` of the acting `CommitteeMember`. Both chair-only operations resolve the target committee — directly for meeting scheduling, or through the target meeting's `committee_id` when minutes are filed — and then require that a `CommitteeMember` exists whose `id` equals `X-User-ID`, whose `committee_id` is that committee, whose `status` is `ACTIVE`, and whose `is_chair` is true. A caller who fails this identity binding receives `ERR_UNAUTHORIZED` (HTTP 403), the same code used for a plain role mismatch; the binding is evaluated after the endpoint's role list has already admitted `CommitteeChair`, and after path resources have been resolved.

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts two optional query parameters. `limit` controls page size: its default is 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls how many records are skipped before the page begins: its default is 0 and its minimum accepted value is 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a request-shape failure and yields `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific list endpoint states otherwise, results are ordered by `created_at` ascending. Three endpoints override that default: the program-of-study collection returns the most recently created programs first, the grant-award collection returns the highest `fiscal_year` first, and a committee's meeting list returns the latest `scheduled_for` first. A program's sequence-course list is ordered by ascending `position`.

List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the values in force for the page, `total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window.

### 2.4. Resource Identity, Versioning and Audit Timestamps

Every resource this API stores is addressed by an `id`, which is a server-minted UUID carrying no type prefix. Clients never supply an `id`; a create call that includes one has that value ignored.

Almost every resource also carries three common properties. `created_at` is the ISO 8601 UTC instant at which the record was first stored, rendered with three fractional digits. `updated_at` is the same format and is refreshed on every mutation of the record. `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that record, including mutations the record did not itself request — a cascade that changes a program's approval status increments that program's `version` just as an explicit call would. `ProgramOfStudy`, `SequenceCourse`, `Credential`, `Student`, `AdvisoryCommittee`, `CommitteeMember`, `CommitteeMeeting`, `GrantAward`, `Expenditure`, `PerformanceIndicator`, `ImprovementPlan` and `Educator` all carry the full set.

`CredentialAttainment` is the single exception. An attainment record is immutable once filed: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from its representation entirely.

### 2.5. The Logical Clock and Federal Date Arithmetic

Every temporal rule in this specification — needs-assessment expiry, grant obligation windows, committee seat terms, asset service periods, credential lapse, and the capital-review lookback — is evaluated against a **logical UTC clock** that the server owns. Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time. An administrative test-driving capability accepts a `to_iso8601` instant and moves the clock to it; the call mutates no stored entity, but every request that follows evaluates its temporal rules against the new reading. All five roles may drive the clock.

Date-typed fields (`labor_market_data_asof`, `clna_certified_on`, `clna_expires_on`, `attained_on`, `term_start_on`, `term_end_on`, `obligation_window_start`, `obligation_window_end`, `service_period_start`, `service_period_end`, `credential_expires_on`, `exited_on`, `closed_on`, `posted_on`, and the `due_on` inside a milestone) are ISO 8601 calendar dates in `YYYY-MM-DD` form. Datetime-typed fields (`scheduled_for`, `held_at`, `submitted_at`, `accepted_at`) are ISO 8601 UTC instants with three fractional digits. Where a rule compares a calendar date against the clock, the clock's date component is used.

Two interval conventions are deliberately different and must not be conflated. Committee seat terms are **half-open**: a member's term covers every date from `term_start_on` inclusive up to but excluding `term_end_on`, so the seat is free again on `term_end_on` itself and back-to-back terms are legal. Grant obligation windows and asset service periods are **closed** on both ends: `obligation_window_start` and `obligation_window_end` are both obligable days, and `service_period_start` and `service_period_end` are both days of possession.

### 2.6. Path Resolution and Referential Existence

Path parameters are resolved strictly left to right, and the first segment that fails to resolve determines the error. Each collection prefix has its own not-found code: `/cte/programs-of-study/{id}` yields `ERR_PROGRAM_NOT_FOUND`, `/cte/sequence-courses/{id}` yields `ERR_COURSE_NOT_FOUND`, `/cte/students/{id}` yields `ERR_STUDENT_NOT_FOUND`, `/cte/credential-attainments/{id}` yields `ERR_ATTAINMENT_NOT_FOUND`, `/cte/advisory-committees/{id}` yields `ERR_COMMITTEE_NOT_FOUND`, `/cte/committee-members/{id}` yields `ERR_MEMBER_NOT_FOUND`, `/cte/committee-meetings/{id}` yields `ERR_MEETING_NOT_FOUND`, `/cte/grant-awards/{id}` yields `ERR_GRANT_NOT_FOUND`, `/cte/expenditures/{id}` yields `ERR_EXPENDITURE_NOT_FOUND`, `/cte/performance-indicators/{id}` yields `ERR_INDICATOR_NOT_FOUND`, `/cte/improvement-plans/{id}` yields `ERR_PLAN_NOT_FOUND`, and `/cte/educators/{id}` yields `ERR_EDUCATOR_NOT_FOUND`. Every one of these is HTTP 404. The `/cte/credentials/{id}` read resolves to `ERR_CREDENTIAL_NOT_FOUND`, likewise HTTP 404.

Foreign keys supplied in a request body are resolved immediately after the path, and they map to the same code family: an unresolvable `pos_id` gives `ERR_PROGRAM_NOT_FOUND`, an unresolvable `prerequisite_course_id` or `sequence_course_id` gives `ERR_COURSE_NOT_FOUND`, an unresolvable `credential_id` gives `ERR_CREDENTIAL_NOT_FOUND`, and an unresolvable `funding_expenditure_id` gives `ERR_EXPENDITURE_NOT_FOUND`. This body-level resolution applies to expenditure requests, sequence-course creation and revision, credential-attainment filing, credit postings, and improvement-plan drafting.

One list is deliberately exempt. The elements of `attendee_member_ids` supplied with meeting minutes are **not** existence-checked; an identifier that does not resolve to a qualifying member is silently dropped when quorum is evaluated, rather than raising an error.

### 2.7. The Validation Precedence Ladder

Because many operations in this domain can fail several ways at once, the order in which checks run is part of the contract. Checks are evaluated in strictly ascending priority and the **first** failure is the response; no later check can mask an earlier one. The ladder, in order:

1. Header presence and role membership — `ERR_UNAUTHENTICATED`.
2. Endpoint role authorization — `ERR_UNAUTHORIZED`.
3. Request-body and query-string shape: required fields present, enum members valid, string patterns matched, numeric bounds respected (`unit_cost_cents` greater than zero, `quantity` at least 1, `credit_hours` greater than zero, `position` from 1 through 8, `articulated_credit_hours` no greater than `credit_hours`, `vote_yes` and `vote_no` at least zero, `cohort_year` and `reporting_year` from 2020 through 2035, `baseline_pct` and `offered_level_pct` from 0.00 through 100.00, `limit` from 1 through 100, `offset` at least zero), dates parsing as `YYYY-MM-DD` and datetimes as ISO 8601 UTC, `term_end_on` strictly after `term_start_on`, `obligation_window_end` strictly after `obligation_window_start`, `service_period_end` on or after `service_period_start`, and `special_population_codes` free of duplicates — `ERR_INVALID_REQUEST`.
4. Path-parameter existence, left to right — the per-collection not-found codes of §2.6.
5. Body foreign-key existence — the per-target not-found codes of §2.6.
6. The `CommitteeChair` identity binding — `ERR_UNAUTHORIZED`.
7. Segregation of duties on `X-User-ID` — `ERR_SEGREGATION_OF_DUTIES`.
8. Optimistic concurrency on the parent's `version` — `ERR_STALE_PROGRAM_VERSION` or `ERR_STALE_GRANT_VERSION`.
9. State-transition admissibility on the target record — the per-entity invalid-state codes of §2.8.
10. The cross-entity approval gate on expenditure certification — `ERR_POS_NOT_APPROVED`.
11. Needs-assessment certified at least once — `ERR_CLNA_NOT_CERTIFIED`.
12. Needs-assessment not lapsed — `ERR_CLNA_EXPIRED`.
13. Grant obligation window open — `ERR_GRANT_WINDOW_CLOSED`.
14. Labor-market data freshness — `ERR_LABOR_MARKET_DATA_STALE`.
15. Prohibited allowable-use category — `ERR_UNALLOWABLE_USE`.
16. Capital-review evidence — `ERR_CAPITAL_REVIEW_REQUIRED`.
17. Meeting quorum headcount — `ERR_QUORUM_NOT_MET`.
18. Employer representation — `ERR_EMPLOYER_SEAT_SHORTFALL`.
19. Vote arithmetic — `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`.
20. Prerequisite integrity — `ERR_PREREQUISITE_INVALID`.
21. Prerequisite acyclicity — `ERR_PREREQUISITE_CYCLE`.
22. Committee seat-term overlap — `ERR_SEAT_TERM_OVERLAP`.
23. Tagged-asset service-period overlap — `ERR_ASSET_PERIOD_OVERLAP`.
24. Sequence completeness at submit — `ERR_SEQUENCE_INCOMPLETE`.
25. Credential list non-empty at submit — `ERR_CREDENTIAL_LIST_EMPTY`.
26. Instructor coverage at submit — `ERR_NO_ELIGIBLE_INSTRUCTOR`.
27. Needs-assessment stakeholder evidence — `ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING`.
28. Committee endorsement on file at state approval — `ERR_COMMITTEE_ENDORSEMENT_MISSING`.
29. Alignment floor at state approval — `ERR_ALIGNMENT_INDEX_BELOW_FLOOR`.
30. Negotiation budget — `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.
31. Improvement-plan substance — `ERR_MILESTONES_INSUFFICIENT`.
32. Improvement-plan funding validity — `ERR_PLAN_FUNDING_INVALID`.
33. Industry-hour ceiling — `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`.
34. Attainment integrity — `ERR_CREDENTIAL_PROGRAM_MISMATCH`, `ERR_EXAM_SCORE_REQUIRED`, `ERR_DUPLICATE_ATTAINMENT` in that internal order.
35. Uniqueness — `ERR_CIP_CODE_DUPLICATE`, `ERR_COURSE_CODE_DUPLICATE`, `ERR_CREDENTIAL_CODE_DUPLICATE`, `ERR_STUDENT_ID_DUPLICATE`, `ERR_FISCAL_YEAR_DUPLICATE`, `ERR_INDICATOR_DUPLICATE`, `ERR_CHAIR_ALREADY_SEATED`.
36. Suspension block on registrar writes — `ERR_CREDIT_POSTING_BLOCKED`.
37. Credit-posting arithmetic — `ERR_COURSE_NOT_ACTIVE`, then `ERR_CREDIT_BALANCE_NEGATIVE`.
38. Administrative cost cap — `ERR_ADMIN_CAP_EXCEEDED`.
39. Grant capacity — `ERR_GRANT_FUNDS_EXCEEDED`.

Two consequences of this ordering deserve emphasis. Grant capacity is the **last** business check in the system: any state, compliance, constraint or referential failure above it wins a request that would also have overdrawn the award. And uniqueness sits below every compliance gate, so a duplicate submission against an unapproved or lapsed parent surfaces the compliance failure, not the duplicate.

### 2.8. State Axes and Transition Admissibility

Nine lifecycles run inside this system, and one record carries two of them at once. A `ProgramOfStudy` has an `approval_status` that walks `DRAFT`, `SUBMITTED`, `COMMITTEE_REVIEW`, `CHANGES_REQUESTED`, `STATE_APPROVED` and `SUSPENDED`, and — entirely independently, on the same row — a `clna_phase` that walks `NOT_STARTED`, `DATA_COLLECTION`, `STAKEHOLDER_CONSULTATION`, `GAP_ANALYSIS`, `CERTIFIED` and `EXPIRED`. Neither axis constrains the other's shape: a program may sit in `STATE_APPROVED` while its `clna_phase` moves from `CERTIFIED` to `EXPIRED`, and it may sit in `DRAFT` while its `clna_phase` reaches `CERTIFIED`. Neither axis has a terminal state — both are cyclic.

The other lifecycles are: `Expenditure.status` over `REQUESTED`, `CERTIFIED`, `OBLIGATED`, `DISALLOWED`, `VOIDED` and `BLOCKED`, with `DISALLOWED` and `VOIDED` terminal; `PerformanceIndicator.status` over `PROPOSED`, `NEGOTIATING`, `AGREED`, `ARBITRATED`, `MET`, `NOT_MET`, `NOT_SCORED`, `IMPROVEMENT_REQUIRED`, `MONITORING` and `SANCTIONED`, with `MET`, `NOT_SCORED` and `SANCTIONED` terminal; `ImprovementPlan.status` over `DRAFT`, `SUBMITTED`, `RETURNED`, `ACCEPTED` and `REJECTED_FINAL`, with `ACCEPTED` and `REJECTED_FINAL` terminal; `CommitteeMeeting.minutes_status` over `SCHEDULED`, `FINALIZED` and `AMENDED`, with `AMENDED` terminal; `Educator.status` over `PROVISIONAL`, `ELIGIBLE` and `LAPSED`, with `LAPSED` terminal; `AdvisoryCommittee.status` over `FORMING`, `ACTIVE` and `DISSOLVED`; `CommitteeMember.status` over `ACTIVE` and `EXPIRED`; and `GrantAward.status` over `OPEN` and `CLOSED`.

When an action endpoint asks a record to make a transition its current state does not declare, the request is refused at priority 9 with the code belonging to that axis: `ERR_INVALID_APPROVAL_TRANSITION` for `approval_status`, `ERR_INVALID_CLNA_PHASE_TRANSITION` for `clna_phase` (including a requested `to_phase` that is not the declared successor of the current phase), `ERR_INVALID_EXPENDITURE_STATE` for `Expenditure.status`, `ERR_INVALID_INDICATOR_STATE` for `PerformanceIndicator.status`, `ERR_INVALID_PLAN_STATE` for `ImprovementPlan.status`, `ERR_INVALID_MEETING_STATE` for `CommitteeMeeting.minutes_status`, and `ERR_INVALID_EDUCATOR_STATE` for `Educator.status`. All seven are HTTP 409. Writes against a terminal state fall under the same codes — an attempt to certify a `DISALLOWED` or `VOIDED` expenditure, to act on a `MET`, `NOT_SCORED` or `SANCTIONED` indicator, to touch an `ACCEPTED` or `REJECTED_FINAL` plan, to file minutes against an already-`AMENDED` meeting, to file an amendment against a still-`SCHEDULED` meeting, or to verify hours for a `LAPSED` educator are all refused here.

Two cross-entity state gates are evaluated at this same priority rather than later. Drafting an improvement plan requires the target `PerformanceIndicator` to be in `IMPROVEMENT_REQUIRED`, and accepting an improvement plan requires the plan's parent indicator to be in `IMPROVEMENT_REQUIRED`; both raise `ERR_INVALID_INDICATOR_STATE`.

One carve-out is deliberate. An indicator already in `ARBITRATED` is **not** mapped at priority 9 for a further negotiation offer or a level acceptance. Those two calls fall through to priority 30, where the spent negotiation budget is reported as `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 422). Every other call made against an `ARBITRATED` indicator is still handled at priority 9 in the ordinary way.

### 2.9. Optimistic Concurrency on Parent Records

Two create operations are guarded by optimistic concurrency against their parent record's `version`, and only those two. Both take the version field as a **required** input, not an optional one; omitting it is a request-shape failure.

Chartering an advisory committee under a program of study requires `expected_program_of_study_version` in the body, carrying the client's last observed `version` of that `ProgramOfStudy`. If the program's current `version` differs from the supplied value — because any writer has advanced it since the client read the program — the create is refused with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). This guard matters precisely because nothing else blocks the call: a newly chartered committee legitimately supersedes the prior committee on the same program, moving that predecessor to `DISSOLVED`, so no state precondition would reject a second charter. The client's stale view of the program is the only thing that distinguishes an intended supersession from an accidental one.

Requesting an expenditure against a grant award requires `expected_grant_award_version` in the body, carrying the client's last observed `version` of that `GrantAward`. A mismatch with the award's current `version` is refused with `ERR_STALE_GRANT_VERSION` (HTTP 412). Again, two distinct purchase requests against one award are both legitimate under the product semantics and no state check rejects the second; the stale version is what signals that the client sized its request against a superseded `remaining_cents` figure.

No other endpoint in this API accepts a version field. Callers must not send one, and the server does not look for one.

### 2.10. Segregation of Duties under Federal Grant Controls

Three points in the workflow require that two different operators be involved, and all three are enforced on `X-User-ID` at priority 7 with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Certifying a comprehensive local needs assessment — that is, advancing `clna_phase` to `CERTIFIED` — requires that the acting `X-User-ID` differ from the program's `authored_by_user_id`. The author of a program may not certify the needs assessment that justifies it. Certifying or disallowing an expenditure requires that the acting `X-User-ID` differ from that expenditure's `requested_by_user_id`; the officer who asked for the purchase may not be the one who rules on its allowability. And in level negotiation, whenever `last_offer_by_user_id` is non-null, both tabling a further offer and accepting the standing offer require that the acting `X-User-ID` differ from `last_offer_by_user_id` **and** that `X-User-Role` differ from `last_offer_by_role`; the party holding the standing offer may neither answer itself nor accept its own number.

### 2.11. Cents, Credit Hours, Rates and Rounding Discipline

Money in this system is always an integer number of cents — `allocation_cents`, `unit_cost_cents`, `gross_cents`, `approved_cents`, `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents`, `remaining_cents`, `admin_cap_cents` and `admin_obligated_cents` are all whole cents, and every monetary product is rounded to whole cents using round-half-up. Rates are carried at four decimal places: `federal_share_pct` and `indirect_rate` both. Percentages used in accountability — `baseline_pct`, `negotiated_level_pct`, `last_offer_pct`, `met_threshold_pct`, `preliminary_actual_pct` and `actual_pct` — are carried at two decimal places, round-half-up. Credit-hour quantities — `credit_hours`, `articulated_credit_hours`, `secondary_credit_total`, `postsecondary_credit_total`, `articulated_credit_total` and `cte_credits_earned` — are carried at two decimal places, round-half-up. The `alignment_index` is the one four-decimal-place score in the system, likewise round-half-up.

Where a rounding step exists, **where** it happens is part of the contract, not an implementation detail. Two rules are pinned. The federal share of an expenditure is rounded to whole cents once, per expenditure line, at the moment the line is certified; the grant ledger then sums those already-rounded integers. Summing gross amounts across lines first and rounding the product once at the end is forbidden, because it produces a different total. The alignment index, conversely, is rounded exactly once at the very end of its computation: none of its intermediate factors are rounded on the way through.

### 2.12. Dual-Variant Computation and Lazy Re-evaluation

Two of this system's calculations exist in **two variants** that read the same stored data and legitimately produce different answers. The alignment index has a `PROVISIONAL_LOCAL` variant, computed whenever a district submits a program, and a `FEDERAL_CERTIFIED` variant, computed when the state approves one; `alignment_index_variant` records which one produced the currently stored `alignment_index`. The performance actual has a `PRELIMINARY_UNADJUSTED` variant, recomputed on every read of an indicator and surfaced as `preliminary_actual_pct` and `preliminary_status_projection`, and a `FINAL_SMALL_COHORT_ADJUSTED` variant, which is the only variant permitted to persist `actual_pct` or drive a status transition. It is expected and correct for a program's provisional index to exceed its federal-certified index, and for an indicator's `preliminary_status_projection` to read `NOT_MET` while the final scoring records `NOT_SCORED`. §3 gives each variant's precise include set.

Two state changes in this system are driven by the clock rather than by any request field, and both are evaluated **lazily**, as the first step of the affected request, before any other validation on it.

The first is needs-assessment expiry. Whenever the logical clock's date is strictly past a program's `clna_expires_on` and that program's `clna_phase` is still `CERTIFIED`, the phase moves `CERTIFIED → EXPIRED` and the program's `version` increments. This re-evaluation runs at the start of every write addressed to that program of study and at the start of expenditure allowability certification; retrieving a single program of study likewise refreshes it. No request field can move this edge in either direction.

The second is credential lapse. Whenever the logical clock's date is strictly past an educator's `credential_expires_on`, that educator moves to `LAPSED` — from `PROVISIONAL` or from `ELIGIBLE` alike — and the educator's `version` increments. This re-evaluation runs on industry-hour verification and on program submission, so that a submit cannot be satisfied by an instructor whose credential has quietly lapsed. Educator reads also refresh the lapse.

### 2.13. Cascade Chains and Ledger Reconstruction

This domain contains two four-link cascade chains, and the distinction between a link and its cause is load-bearing. Closing a reporting year on a missed indicator increments `consecutive_miss_count` (link 1); reaching the miss tolerance is what fires the escalation to `IMPROVEMENT_REQUIRED` (link 2); that escalation is what suspends the program of study (link 3); and that suspension is what blocks the program's outstanding expenditure requests (link 4). Accepting an improvement plan runs the mirror image: acceptance (link 1) resets the indicator's miss counter and moves it to `MONITORING` (link 2); that reset is what un-suspends the program (link 3); and that un-suspension is what returns the program's blocked expenditure requests to `REQUESTED` (link 4). Each link fires only because its predecessor fired — a link whose own precondition is unmet stops the chain without failing the request that started it. Every entity a chain touches has its `version` incremented and its `updated_at` refreshed.

Derived aggregates are never accumulated incrementally. The grant ledger, a program's three credit subtotals, an educator's verified hours roll-up, a committee's member counts, a credential's attainment count and an indicator's numerator and denominator are all recomputed from their current inputs whenever an input moves. This is what makes voiding a certified expenditure an exact compensation: the ledger is rebuilt over the award's remaining countable lines, restoring `remaining_cents` to precisely the figure it held before the certification, with no drift from repeated addition and subtraction.

## 3. Business Logic & Workflows

### 3.1. Authoring a Program of Study and Building the Course Sequence

A `CteDirector` opens the district's year by creating a program of study. The creation payload carries four values: a `cip_code`, which is the federal classification code and must be exactly two digits, a period, and four further digits; a `title` of between 1 and 120 characters, which is the local program name printed on the state approval packet; a `cluster` naming the career area, which must be one of `HEALTH_SCIENCE`, `ADVANCED_MANUFACTURING`, `INFORMATION_TECHNOLOGY`, `CONSTRUCTION` or `AGRICULTURE`; and a `labor_market_data_asof` calendar date recording which labor-market dataset the needs assessment will lean on. The `cip_code` must be unique across every program of study in the district — a collision is refused with `ERR_CIP_CODE_DUPLICATE`. On creation the new program lands in `approval_status` `DRAFT` and `clna_phase` `NOT_STARTED`, its `version` is 1, its `authored_by_user_id` is set to the acting `X-User-ID`, its `alignment_index` and `alignment_index_variant` are both null, its `narrative_url` is null, its `open_finding_codes` list is empty, its `federal_reporting_eligible` flag is false, its `approval_round` is 0, its `clna_certified_by_user_id`, `clna_certified_on` and `clna_expires_on` are all null, and `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total` are all 0.

Descriptive attributes remain amendable while the program has not yet been approved. A director may revise any of `title`, `cluster` or `labor_market_data_asof` on a program whose `approval_status` is anything other than `STATE_APPROVED`; the amendment increments the program's `version`. Attempting the same amendment against a `STATE_APPROVED` program is refused with `ERR_INVALID_APPROVAL_TRANSITION`.

Adding a course to the sequence is how the secondary-to-postsecondary pathway takes shape. Each `SequenceCourse` carries a `code` of 1 to 24 characters that must be unique among the courses of the same program (a repeat is `ERR_COURSE_CODE_DUPLICATE`), a `title`, a `segment` of either `SECONDARY` or `POSTSECONDARY`, a `position` from 1 through 8 fixing its ordinal place in the sequence, and `credit_hours` greater than zero at two decimal places. Optionally the payload sets `articulated_credit_hours` — the portion of the course's credit that articulates to the postsecondary partner, which defaults to 0 and may be neither negative nor greater than `credit_hours` — an `articulation_verified` flag that defaults to false and turns true only once the postsecondary partner has countersigned the articulation agreement, a `prerequisite_course_id` naming an earlier course, and a `status` that defaults to `DRAFT` and may be set to `ACTIVE` or `RETIRED`. The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0.

Prerequisites are policed in two stages. First, integrity: the named prerequisite must belong to the same program as the course being written, must not be the course itself, must not be a `POSTSECONDARY` course named by a `SECONDARY` course (a `POSTSECONDARY` course naming a `SECONDARY` prerequisite is entirely legal), and must sit at a `position` strictly earlier than the course's own. A breach of any of those four is `ERR_PREREQUISITE_INVALID`. Second, acyclicity: following `prerequisite_course_id` onwards from the written course must reach a course with a null `prerequisite_course_id` without revisiting any course already on the walk, and a revisit is `ERR_PREREQUISITE_CYCLE`. Integrity is checked before acyclicity, so a self-reference reports the integrity breach.

Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules. A revision recomputes `depth_from_root` not only for the revised course but for every course that transitively depends on it, then rebuilds the parent program's three credit subtotals and its `alignment_index` and `alignment_index_variant`, and increments the `version` of both the course and the parent program. Course creation performs the same parent-side recomputation and the same parent `version` increment.

The **alignment index** is the district's secondary-to-postsecondary bridge score, a number between 0.0000 and 1.0000 at four decimal places. Its computation is fixed except for one thing: an *include set* of course statuses that the calling variant chooses. Retired curriculum is invisible to both variants — a course whose `status` is `RETIRED` never contributes. Under the `PROVISIONAL_LOCAL` variant the include set is courses whose `status` is `DRAFT` or `ACTIVE`, and the articulated sum ignores `articulation_verified` entirely, counting every qualifying postsecondary course's `articulated_credit_hours`. Under the `FEDERAL_CERTIFIED` variant the include set is courses whose `status` is `ACTIVE` only, and the articulated sum counts a postsecondary course's `articulated_credit_hours` solely when that course's `articulation_verified` is true. Identical curriculum data therefore yields a `FEDERAL_CERTIFIED` index that is lower than or equal to the `PROVISIONAL_LOCAL` index, never higher.

Given the variant's include set, the evaluation proceeds in a fixed order. Three sums are taken first: the secondary credit subtotal is the sum of `credit_hours` over the program's courses whose `segment` is `SECONDARY` and whose `status` is in the include set; the postsecondary credit subtotal is the same sum over courses whose `segment` is `POSTSECONDARY` and whose `status` is in the include set; and the articulated subtotal is the sum of `articulated_credit_hours` over courses whose `segment` is `POSTSECONDARY`, whose `status` is in the include set, and which satisfy the variant's articulation restriction. Those three sums are what get stored as `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`. Three factors follow. The **depth factor** is the smaller of 1.0 and the secondary credit subtotal divided by the four credit hours of secondary coursework a full pathway is expected to carry. The **bridge factor** is the smaller of 1.0 and the articulated subtotal divided by the larger of 1.0 and the postsecondary credit subtotal — the denominator floor of 1.0 keeps the factor finite when the postsecondary side is empty. The **breadth bonus** is 0.10 when the secondary credit subtotal is greater than zero, the postsecondary credit subtotal is greater than zero, and the articulated subtotal is at least the three articulated credit hours that mark a genuine dual-credit bridge; otherwise the bonus is 0.0. The weighted combination is then formed by multiplying the depth factor by 0.60, multiplying the bridge factor by 0.30, and adding the breadth bonus. That sum is clamped to at most 1.0, and the clamped value is rounded half-up to four decimal places exactly once. Neither the depth factor nor the bridge factor is rounded on the way through, and no rounding happens before the clamp.

The program's approved credential list is built in parallel with the sequence. A `Credential` carries a `code` of 1 to 32 characters unique within the program (a repeat is `ERR_CREDENTIAL_CODE_DUPLICATE`), a `title`, a `tier` of `STATE_RECOGNIZED`, `NATIONAL` or `LOCAL`, and an `exam_required` flag that defaults to true. The server sets `counts_toward_indicator` to true when the `tier` is `STATE_RECOGNIZED` or `NATIONAL`, and to false when the `tier` is `LOCAL` — locally recognised credentials are legitimate to award but never enter a federal performance numerator. A credential's `verified_attainment_count` starts at 0 and thereafter always equals the number of attainment records against it whose `verification_status` is `VERIFIED`. Adding a credential increments the parent program's `version`.

### 3.2. The Comprehensive Local Needs Assessment Cycle

The comprehensive local needs assessment (CLNA) is the evidence base a district must have on file before the state will look at a program at all, and it runs on its own axis of the program record. Both a `CteDirector` and a `StateComplianceReviewer` may drive it, one phase at a time, by naming the target phase in a `to_phase` field and optionally attaching an `evidence_url` documenting the step. A `to_phase` that is not the declared successor of the program's current `clna_phase` is refused with `ERR_INVALID_CLNA_PHASE_TRANSITION`; each accepted advance increments the program's `version`.

Opening the assessment moves `NOT_STARTED → DATA_COLLECTION` and requires only that the program already carry a non-null `labor_market_data_asof`. Leaving data collection for `DATA_COLLECTION → STAKEHOLDER_CONSULTATION` imposes the freshness rule: the labor-market dataset behind the assessment may be at most two years old, meaning the difference between the logical clock's date and `labor_market_data_asof` must be no more than 730 days. A dataset older than that is refused with `ERR_LABOR_MARKET_DATA_STALE`.

`STAKEHOLDER_CONSULTATION → GAP_ANALYSIS` is the documentation gate. At least two committee meetings on the program's `ACTIVE` advisory committee must have `agenda_kind` `CLNA_STAKEHOLDER`, `minutes_status` of either `FINALIZED` or `AMENDED`, and a `quorum_met` value of true. A single qualifying meeting is not enough, and a meeting that convened without quorum does not count no matter how thorough its minutes; the shortfall reports as `ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING`.

Certification — `GAP_ANALYSIS → CERTIFIED` — is where segregation of duties bites. The acting `X-User-ID` must differ from the program's `authored_by_user_id`; an author certifying their own program's assessment is refused with `ERR_SEGREGATION_OF_DUTIES`. On success the server writes `clna_certified_by_user_id` from the acting `X-User-ID`, sets `clna_certified_on` to the logical clock's current date, and sets `clna_expires_on` to that date plus 730 days — a certified needs assessment is good for two years and not a day more.

Expiry is not a request; it is a consequence of the calendar. Once the clock's date passes `clna_expires_on`, the phase moves `CERTIFIED → EXPIRED` at the front of the next write against that program or the next expenditure allowability certification that depends on it, and the program's `version` increments. A district recovers by re-opening the assessment: advancing `to_phase` to `DATA_COLLECTION` is admitted from both `CERTIFIED` and `EXPIRED`, and that re-open clears `clna_certified_on`, `clna_expires_on` and `clna_certified_by_user_id` back to null so that the four-phase walk must be completed afresh.

The distinction between "never certified" and "certified but lapsed" is visible in the errors. Program submission, state approval and expenditure allowability certification all require the governing program's `clna_phase` to be either `CERTIFIED` or `EXPIRED` — a program in `NOT_STARTED`, `DATA_COLLECTION`, `STAKEHOLDER_CONSULTATION` or `GAP_ANALYSIS` has never had its assessment certified and fails all three with `ERR_CLNA_NOT_CERTIFIED`. A program in `EXPIRED` clears that hurdle and then fails the very next one, `ERR_CLNA_EXPIRED`, because the clock's date is past `clna_expires_on`.

### 3.3. Advisory Committee Membership, Meetings and Documented Minutes

Nothing about a program of study advances without an advisory committee behind it, and the committee's own records are the evidence. A `CteDirector` charters one by supplying a `name` for the approval packet, a `quorum_min_members` count between 3 and 15 setting how many eligible members must be present for a meeting to carry quorum, an `employer_seat_min` count between 1 and 8 setting how many of those present must represent employers — a value that may not exceed `quorum_min_members` — and the `expected_program_of_study_version` described in §2.9. A newly chartered committee starts in `status` `FORMING` with `active_member_count` 0, `employer_member_count` 0 and `chair_member_id` null, and its creation increments the parent program's `version`. Chartering a second committee on the same program is permitted and is how a district refreshes its stakeholder body: the earlier committee moves to `DISSOLVED`, and only the newest committee is the program's `ACTIVE` one for every downstream evidence rule.

Members are seated one at a time into named seats. A `CommitteeMember` payload carries a `full_name`, a `sector` of `EMPLOYER`, `POSTSECONDARY`, `LABOR`, `PARENT` or `STUDENT`, a `seat_code` written as three uppercase letters followed by a hyphen and one or two digits, a `term_start_on` date, a `term_end_on` date strictly after it, and an optional `is_chair` flag that defaults to false. A member's `status` begins as `ACTIVE` and becomes `EXPIRED` once the logical clock's date reaches `term_end_on`; the term is inclusive of `term_start_on` and exclusive of `term_end_on`.

Seat occupancy is enforced on that same half-open reading. A new member is refused with `ERR_SEAT_TERM_OVERLAP` when an existing `ACTIVE` member on the same committee holds the same `seat_code` and the two terms genuinely overlap — that is, when the new `term_start_on` falls strictly before the incumbent's `term_end_on` and the incumbent's `term_start_on` falls strictly before the new `term_end_on`. Adjacency is consequently legal: a successor whose `term_start_on` is exactly the incumbent's `term_end_on` is accepted, because a zero-length gap is not an overlap. Chairmanship is likewise exclusive — seating a member with `is_chair` true while the committee already has an `ACTIVE` member whose `is_chair` is true is refused with `ERR_CHAIR_ALREADY_SEATED`.

Each successful seating rebuilds the committee's derived counts. `active_member_count` becomes the number of that committee's members whose `status` is `ACTIVE`, `employer_member_count` becomes the number of those whose `sector` is also `EMPLOYER`, and `chair_member_id` becomes the `id` of the single `ACTIVE` member whose `is_chair` is true (staying null while no such member exists). The committee then flips `FORMING → ACTIVE` the moment all three conditions hold at once: `active_member_count` is at least `quorum_min_members`, `employer_member_count` is at least `employer_seat_min`, and `chair_member_id` is non-null. Seating increments the committee's `version`.

Only the seated chair runs meetings. Scheduling one requires an `agenda_kind` of `CLNA_STAKEHOLDER`, `POS_ENDORSEMENT` or `EQUIPMENT_REVIEW` — each purpose unlocks a different downstream gate — and a `scheduled_for` instant. The new meeting begins with `minutes_status` `SCHEDULED`, an empty `attendee_member_ids` list, `vote_yes` and `vote_no` both at 0, `quorum_met` and `endorsement_passed` both false, and `held_at`, `minutes_url` and `amendment_reason` all null; scheduling increments the owning committee's `version`.

Filing minutes is where attendance becomes arithmetic. The chair supplies the `held_at` instant at which the meeting actually convened, the `attendee_member_ids` list of members recorded present, the `vote_yes` and `vote_no` tallies, a `minutes_url` pointing at the signed document, and — only when re-recording minutes that were already filed — an `amendment_reason`. A `held_at` earlier than the meeting's `scheduled_for` is a malformed filing and is rejected as a request-shape failure with `ERR_INVALID_REQUEST`.

Attendance is resolved before it is counted. A submitted attendee identifier is *eligible* only when it names a `CommitteeMember` whose `committee_id` is this meeting's committee and whose term covers the calendar date of `held_at` — that is, whose `term_start_on` is on or before that date and whose `term_end_on` is strictly after it. Identifiers that do not resolve to such a member are silently discarded rather than raising an error, so a roster typo shrinks the count instead of failing the filing. `eligible_attendee_count` is then the number of eligible attendees, and `employer_attendee_count` is the number of those whose `sector` is `EMPLOYER`.

Quorum requires three things simultaneously: `eligible_attendee_count` at least `quorum_min_members`, `employer_attendee_count` at least `employer_seat_min`, and employer parity — twice `employer_attendee_count` at least `eligible_attendee_count`, meaning employers must hold at least half of the eligible attendance. The parity clause is inclusive, so employers holding exactly half satisfies it. The result is stored in `quorum_met`. The three failure modes report separately and in this order: a headcount below `quorum_min_members` is `ERR_QUORUM_NOT_MET`; then an employer shortfall — either too few employers against `employer_seat_min` or employers holding strictly less than half the eligible attendance — is `ERR_EMPLOYER_SEAT_SHORTFALL`; then `vote_yes` plus `vote_no` exceeding `eligible_attendee_count` is `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`. Because the headcount check precedes the employer check, a meeting that is both short-handed and employer-poor reports the headcount failure.

`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`. A tied vote does not endorse.

A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`. A filing that carries a non-null `amendment_reason` moves the meeting `FINALIZED → AMENDED`, recording the reason, overwriting `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url`, and recomputing `quorum_met` and `endorsement_passed` on the amended figures — the amended attendance must itself satisfy quorum. `AMENDED` admits nothing further, and an amendment filed against a meeting still in `SCHEDULED` is refused; both are `ERR_INVALID_MEETING_STATE`. Either filing increments the meeting's `version`.

One filing has a reach beyond its own record. When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well. The committee must be the program's `ACTIVE` committee for this to fire. A program not in `SUBMITTED` at that moment is simply left alone — the minutes still finalize successfully.

### 3.4. Sequence Approval: Submission, Findings and State Approval

Submission is the district's formal assertion that a program is complete. A `CteDirector` submits by supplying a `narrative_url` linking the narrative packet, and the program moves `DRAFT → SUBMITTED` on a first attempt or `CHANGES_REQUESTED → SUBMITTED` on any resubmission after a state finding. Both edges carry the identical set of six preconditions, and both are refused with `ERR_INVALID_APPROVAL_TRANSITION` when attempted from any other `approval_status`.

The six preconditions, in the order their failures surface: the program's needs assessment must have been certified at least once, so `clna_phase` must be `CERTIFIED` or `EXPIRED` (otherwise `ERR_CLNA_NOT_CERTIFIED`); that certification must still be live, so the logical clock's date must not be past `clna_expires_on` (otherwise `ERR_CLNA_EXPIRED`); the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`); the approved credential list must hold at least one credential (otherwise `ERR_CREDENTIAL_LIST_EMPTY`); and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`). A `DRAFT` course or a `RETIRED` course satisfies neither half of the sequence-completeness rule.

An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`. The program's `version` increments. Note that the provisional index carries no floor: a submission is never refused for a low alignment index.

From `SUBMITTED`, the program waits on its advisory committee. A quorate `POS_ENDORSEMENT` meeting whose vote passes is what advances it to `COMMITTEE_REVIEW`, as described in §3.3; no operator drives that edge directly.

A `StateComplianceReviewer` reviewing a program in `COMMITTEE_REVIEW` has two options. Returning it moves `COMMITTEE_REVIEW → CHANGES_REQUESTED` and requires a `finding_codes` list, optionally accompanied by a `note`; the supplied list **replaces** `open_finding_codes` wholesale, and the program's `version` increments. The district then works the findings and resubmits, which clears the list again — this is the revision cycle, and it may repeat without limit.

Approving it moves `COMMITTEE_REVIEW → STATE_APPROVED`, optionally recording an `approval_note`. Three gates guard the edge beyond the state check. The needs assessment must be `CERTIFIED` or `EXPIRED` and not past `clna_expires_on`, failing as `ERR_CLNA_NOT_CERTIFIED` then `ERR_CLNA_EXPIRED` respectively. A committee endorsement must be on file: some meeting on the program's `ACTIVE` advisory committee must have `agenda_kind` `POS_ENDORSEMENT`, `minutes_status` of `FINALIZED` or `AMENDED`, and `endorsement_passed` true, or the request fails with `ERR_COMMITTEE_ENDORSEMENT_MISSING`. And the alignment index recomputed under the `FEDERAL_CERTIFIED` variant must reach the federal floor of 0.7500, inclusive — an index of exactly 0.7500 passes, anything strictly below it fails with `ERR_ALIGNMENT_INDEX_BELOW_FLOOR`. Only the `FEDERAL_CERTIFIED` variant is ever compared against that floor, which is why a program can submit comfortably on its provisional score and then fail approval on unverified articulation or `DRAFT` coursework.

State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission. It clears `open_finding_codes`. And it increments the program's `version`.

### 3.5. Instructor Certification Pathways

Programs need instructors on file before they can be submitted, and this domain recognises three routes to the classroom. A `CteDirector` assigns an educator to a program with a `full_name`, a `certification_route` of `TRADITIONAL`, `INDUSTRY_EXPERIENCE` or `ALTERNATIVE`, a `claimed_industry_hours` figure of zero or more stating how much industry work the instructor asserts, and a `credential_expires_on` date on which the teaching credential lapses. The educator lands in `status` `PROVISIONAL` with `verified_industry_hours` 0, and the assignment increments the parent program's `version`.

Claimed hours mean nothing until the state verifies them. A `StateComplianceReviewer` files a verification tranche carrying `verified_hours` and a `verification_source` describing the documentation behind it. Each tranche must be worth at least 1 hour, and the running total after it may not exceed what the instructor claimed — `verified_industry_hours` plus the new `verified_hours` must stay within `claimed_industry_hours`, and a breach of either bound is `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`. An accepted tranche adds `verified_hours` to `verified_industry_hours` and increments the educator's `version`.

Whether that tranche confers eligibility depends entirely on the route's hour floor, evaluated against the total *after* the tranche is applied. The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable. The `ALTERNATIVE` route demands 2,000 verified hours, one such year. The `TRADITIONAL` route carries no hour requirement at all: its floor is zero verified hours, so the first accepted verification tranche is sufficient. When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`. When the total is still below the floor, the educator loops `PROVISIONAL → PROVISIONAL` — the hours accumulate, the `version` still increments, and the request succeeds; partial verification is progress, not failure.

Credential lapse overrides both outcomes. Whenever the logical clock's date is strictly past `credential_expires_on`, the educator moves to `LAPSED` — from `PROVISIONAL` or `ELIGIBLE` alike — and this re-evaluation runs on verification filings, on program submission, and on educator reads. `LAPSED` is terminal: a verification attempted against a `LAPSED` educator is refused with `ERR_INVALID_EDUCATOR_STATE`. An instructor whose credential has lapsed therefore cannot satisfy the instructor-coverage precondition on submission, which is exactly how a stale roster surfaces as `ERR_NO_ELIGIBLE_INSTRUCTOR`.

### 3.6. Students, Credit Postings, Credential Attainment and Concentrator Classification

Federal accountability is computed over students, so the registrar's records are the denominator of everything in §3.8. A `SchoolRegistrar` enrolls a student into a program with a `state_student_id` of exactly nine digits — unique among that program's students, a repeat being `ERR_STUDENT_ID_DUPLICATE` — a `cohort_year` between 2020 and 2035 naming the accountability cohort the student is reported under, and an optional `special_population_codes` list whose elements are drawn from `ECON_DISADV`, `IEP`, `EL`, `SINGLE_PARENT` and `NONTRADITIONAL` with no duplicates, defaulting to an empty list. The new student begins with `cte_credits_earned` 0, `verified_qualifying_attainment_count` 0, `concentrator_status` `PARTICIPANT`, and `exited_on` and `exit_reason` both null. Enrollment also refreshes `denominator_count` on every performance indicator of that program whose `cohort_year` matches the student's.

Credits reach a student one posting at a time. A posting names a `sequence_course_id`, a signed `credit_delta`, and a `posted_on` date. The target course must belong to the student's own program and must be in `status` `ACTIVE`; a course from another program or a course in `DRAFT` or `RETIRED` is refused with `ERR_COURSE_NOT_ACTIVE`. A `credit_delta` may be negative, and that is precisely how an earlier posting is reversed — but the running balance may never go under water, so a posting whose delta would drive `cte_credits_earned` below zero is refused with `ERR_CREDIT_BALANCE_NEGATIVE`. Both registrar write operations, posting credits and recording an exit, are additionally blocked outright while the student's program of study sits in `approval_status` `SUSPENDED`; the refusal is `ERR_CREDIT_POSTING_BLOCKED`, and it is evaluated before the course and balance checks.

Recording an exit supplies an `exited_on` date and an `exit_reason` of `GRADUATED`, `TRANSFERRED` or `WITHDREW`. Until an exit is recorded the student is treated as still enrolled and `exited_on` stays null. An exit refreshes `numerator_count` on every matching performance indicator.

Attainments are the credential side of the record and are filed by either a `SchoolRegistrar` or a `CteDirector`. The payload names a `credential_id`, the `attained_on` date the credential was earned, a `verification_status` of either `SELF_REPORTED` or `VERIFIED`, and an `exam_score` between 0 and 100 at two decimal places. Three integrity rules apply in a fixed internal order: the referenced credential must belong to the same program as the student, or the filing fails with `ERR_CREDENTIAL_PROGRAM_MISMATCH`; an `exam_score` must be supplied whenever the referenced credential has `exam_required` true, or the filing fails with `ERR_EXAM_SCORE_REQUIRED`; and no attainment may already exist for that same student-and-credential pairing, a repeat being `ERR_DUPLICATE_ATTAINMENT`. An attainment record is immutable once filed, and it carries `student_id` taken from the addressed student together with the `credential_id` from the payload.

Whether an attainment counts for federal purposes is a conjunction of two facts, and the server records the answer on the row as `counted_for_indicator`: it is true only when the attainment's `verification_status` is `VERIFIED` **and** the referenced credential's `counts_toward_indicator` is true. A verified `LOCAL` credential does not count, and neither does a self-reported `NATIONAL` one. Filing an attainment refreshes the credential's `verified_attainment_count`, the student's `verified_qualifying_attainment_count`, and the `numerator_count` and `preliminary_actual_pct` of every matching indicator.

**Concentrator classification** is recomputed whenever a credit posting, an exit or an attainment lands on a student, and it writes three fields. First, `cte_credits_earned` is rebuilt as the sum of `credit_delta` across every accepted posting for that student whose target course was in `status` `ACTIVE` at the time of posting, rounded half-up to two decimal places. Second, `verified_qualifying_attainment_count` is rebuilt as the number of that student's attainment records whose `counted_for_indicator` is true. Third, `concentrator_status` is decided by a three-way ladder evaluated top to bottom: the student is a `COMPLETER` when `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is non-null **and** `verified_qualifying_attainment_count` is at least 1; failing that, the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at least 2.0 credit hours; failing that, the student is a `PARTICIPANT`. The credit comparison is inclusive — a balance of exactly 2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not — and because postings may be negative, the classification can move backwards from `CONCENTRATOR` to `PARTICIPANT` just as readily as forwards.

Every credit posting also propagates into accountability, refreshing `denominator_count`, `small_cohort_flag`, `preliminary_actual_pct` and `preliminary_status_projection` on each performance indicator of the student's program whose `cohort_year` matches, and increments the student's `version`.

### 3.7. Federal Grant Awards, Allowable-Use Certification and the Obligation Ledger

A `GrantFiscalOfficer` records each year's federal award with a `fiscal_year` between 2020 and 2035 that must be unique across all awards (a repeat is `ERR_FISCAL_YEAR_DUPLICATE`), an `allocation_cents` total greater than zero, and an obligation window bounded by `obligation_window_start` and an `obligation_window_end` strictly after it. A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents. The award's `status` reads `OPEN` while the logical clock's date lies within the inclusive window and `CLOSED` once that date passes `obligation_window_end`.

Purchases are requested by the `CteDirector` who needs them, not by the officer who will rule on them. A request names the `pos_id` of the program the purchase is charged to, a `category`, a `description` for the grant file, a `unit_cost_cents` greater than zero, a `quantity` of at least 1, a `service_period_start` and a `service_period_end` on or after it, optionally an `asset_tag` of 3 to 24 characters drawn from uppercase letters, digits and hyphens, and the `expected_grant_award_version` of §2.9. The `category` is one of `EQUIPMENT`, `CONSUMABLE`, `PROFESSIONAL_DEVELOPMENT`, `ADMINISTRATION` or `ENTERTAINMENT`. A request may only be filed while the award is inside its inclusive obligation window; outside it the answer is `ERR_GRANT_WINDOW_CLOSED`. The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`.

A tagged asset cannot be double-booked, and this rule is deliberately stricter than the committee-seat rule of §3.3. When `asset_tag` is non-null, the new request is refused if any existing expenditure on the same award carries the same `asset_tag`, holds a `status` of `REQUESTED`, `CERTIFIED`, `OBLIGATED` or `BLOCKED`, and has a service period that comes within a two-week mobilisation buffer of the new one. Concretely: the request fails when the new `service_period_start` falls on or before the incumbent's `service_period_end` plus 14 days **and** the new `service_period_end` falls on or after the incumbent's `service_period_start` minus 14 days. Adjacency is therefore illegal here — a gap of exactly 14 days between the two periods is rejected, and only a gap of 15 days or more is accepted. The refusal is `ERR_ASSET_PERIOD_OVERLAP`. `DISALLOWED` and `VOIDED` rows hold no asset and never block a new booking.

The federal share of a purchase is fixed by its category. `PROFESSIONAL_DEVELOPMENT` is reimbursed in full at a share of 1.0000. `EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500. `ENTERTAINMENT` carries a share of 0.0000 and, as described below, never reaches the point where that number matters. The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**. The award ledger then sums those already-rounded integers. Aggregating gross amounts across lines and rounding the product once at the end is forbidden: two lines of 250,010 gross cents at a 0.8500 share round to 212,509 cents each for a total of 425,018, whereas rounding a combined 500,020 gross at 0.8500 would yield 425,017 — and 425,018 is the correct figure.

Certification is the fiscal officer's ruling and carries a `decision` of either `CERTIFY` or `DISALLOW`, with an optional `finding_code` drawn from `ENTERTAINMENT_PROHIBITED`, `ADMIN_CAP`, `NO_CAPITAL_REVIEW`, `OUTSIDE_WINDOW` and `OTHER`. Whichever way it goes, the officer's `X-User-ID` must differ from the expenditure's `requested_by_user_id`, or the ruling is refused with `ERR_SEGREGATION_OF_DUTIES`.

A `CERTIFY` decision moves the expenditure `REQUESTED → CERTIFIED` and must clear a full stack of federal gates. The charged program of study must be in `approval_status` `STATE_APPROVED`, or the answer is `ERR_POS_NOT_APPROVED`. That program's needs assessment must be `CERTIFIED` or `EXPIRED` (`ERR_CLNA_NOT_CERTIFIED` otherwise) and not past `clna_expires_on` (`ERR_CLNA_EXPIRED` otherwise) — and note that the lazy expiry re-evaluation of §2.12 runs at the front of this call, so a program that was live when the request was filed can lapse before it is certified. The award must be inside its inclusive obligation window (`ERR_GRANT_WINDOW_CLOSED`). The `category` must not be `ENTERTAINMENT`: entertainment is never an allowable federal use, so the only lawful ruling on such a line is `DISALLOW` with `finding_code` `ENTERTAINMENT_PROHIBITED`, and an attempt to certify one is `ERR_UNALLOWABLE_USE`. An `EQUIPMENT` line whose `unit_cost_cents` reaches the capital threshold of 500,000 cents — five thousand dollars per unit — additionally requires capital review: a meeting on the program's `ACTIVE` advisory committee with `agenda_kind` `EQUIPMENT_REVIEW`, `minutes_status` of `FINALIZED` or `AMENDED`, `quorum_met` true, and a `held_at` instant no earlier than 365 days before the current logical clock reading. Missing that evidence is `ERR_CAPITAL_REVIEW_REQUIRED`. An `ADMINISTRATION` line must fit under the administrative cost cap: the award's `admin_obligated_cents` plus this line's `approved_cents` may not exceed `admin_cap_cents`, and a breach is `ERR_ADMIN_CAP_EXCEEDED`. Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`.

An accepted certification writes `federal_share_pct` and `approved_cents`, records `certified_by_user_id` from the acting `X-User-ID`, rebuilds the whole award ledger, and increments the `version` of both the expenditure and the award.

A `DISALLOW` decision is the branch sibling and its side effects diverge sharply. It requires a non-null `finding_code` in the request, moves the expenditure `REQUESTED → DISALLOWED`, records that `finding_code` and `certified_by_user_id`, and **leaves `approved_cents` null**. No field of the grant award changes and the award's `version` is *not* incremented — a disallowed line never entered the ledger, so there is nothing to rebuild. Only the expenditure's `version` moves.

**The obligation ledger** is rebuilt from scratch, in six pinned steps, on every certification and every void. Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation. Every addend is an already-rounded integer, so summation order is immaterial. Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500. The lookup is never keyed on `obligated_cents` or `remaining_cents`, even though `obligated_cents` contains the pool this rate produces — that circularity is precisely the mistake the pinning forbids. Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`. Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`, and `admin_cap_cents` is `allocation_cents` multiplied by five percent, rounded half-up to whole cents. After every rebuild, `allocation_cents` must equal `obligated_cents` plus `remaining_cents` exactly — that identity is the conserved quantity of the whole grant model. To make the tier key concrete: an award of 10,000,000 allocation cents carrying a single professional-development line of 4,900,000 approved cents takes the 0.0812 tier, yielding an indirect pool of 397,880 cents, obligated cents of 5,297,880 and remaining cents of 4,702,120. Keying the tier on the resulting 5,297,880 would have picked 0.0650 and is wrong.

Obligating a certified line records the purchase order. The request carries an `obligation_reference`, the expenditure moves `CERTIFIED → OBLIGATED`, and the logical clock's date must still be on or before the award's `obligation_window_end` or the call fails with `ERR_GRANT_WINDOW_CLOSED`. Obligation increments only the expenditure's `version`; because both `CERTIFIED` and `OBLIGATED` rows are countable, the ledger totals do not move.

Voiding is the compensating action and works from either `CERTIFIED → VOIDED` or `OBLIGATED → VOIDED`, with no state preconditions beyond being in one of those two statuses. The request carries a `void_reason`. The void records that reason, sets `approved_cents` back to null so the row can never re-enter the roll-up, and — on the two-step path — retains the `obligation_reference` already stamped on the row for the audit trail. It then rebuilds the ledger identically to a certification, which restores `remaining_cents` to exactly the figure it held before the certification being undone. Both the expenditure's and the award's `version` increment.

### 3.8. Performance Indicators: Negotiation, Year Close and the Sanction Cascade

A `StateComplianceReviewer` opens an indicator for a program and a reporting year. The payload names an `indicator_code` of `1S1_GRAD_RATE`, `2S1_ACADEMIC`, `3S1_POST_PROGRAM`, `4S1_CREDENTIAL` or `5S3_WORK_BASED`, a `reporting_year` between 2020 and 2035, a `baseline_pct` between 0.00 and 100.00 recording prior-year performance, and a `cohort_year` between 2020 and 2035 naming the student cohort that will form the denominator. The combination of program, `indicator_code` and `reporting_year` must be unique — a repeat is `ERR_INDICATOR_DUPLICATE`. The indicator opens in `status` `PROPOSED` with `negotiation_round` 0, `negotiated_level_pct`, `last_offer_pct`, `last_offer_by_user_id`, `last_offer_by_role`, `met_threshold_pct`, `actual_pct` and `closed_on` all null, and `consecutive_miss_count` 0. Its `denominator_count`, `numerator_count`, `small_cohort_flag`, `preliminary_actual_pct` and `preliminary_status_projection` are computed immediately over the students already enrolled for that `cohort_year`.

**Negotiation is an alternating-offer exchange** between the district and the state, and both `CteDirector` and `StateComplianceReviewer` may participate. An offer carries an `offered_level_pct` between 0.00 and 100.00 and an optional `rationale`. The state opens the exchange: the first offer, tabled while `negotiation_round` is 0, moves the indicator `PROPOSED → NEGOTIATING`, and only a `StateComplianceReviewer` satisfies that opening edge — a director's attempt to open the exchange does not match any declared transition out of `PROPOSED` and is refused with `ERR_INVALID_INDICATOR_STATE`. The opening offer sets `negotiation_round` to 1, writes `last_offer_pct` from `offered_level_pct`, `last_offer_by_user_id` from the acting `X-User-ID`, and `last_offer_by_role` as `StateComplianceReviewer`.

Thereafter each counter-offer loops `NEGOTIATING → NEGOTIATING` while `negotiation_round` is strictly below the four-round budget. Alternation is enforced twice over: the acting `X-User-Role` must differ from `last_offer_by_role` and the acting `X-User-ID` must differ from `last_offer_by_user_id`, and a party answering itself is refused with `ERR_SEGREGATION_OF_DUTIES`. Each accepted counter-offer increments `negotiation_round` by 1 and overwrites `last_offer_pct`, `last_offer_by_user_id` and `last_offer_by_role` with the new offer's values.

Accepting the standing offer moves `NEGOTIATING → AGREED` and may carry an `acceptance_note`. The accepter must not be the offering party — the same two-part alternation check applies and fails as `ERR_SEGREGATION_OF_DUTIES` — and there must be a standing offer at all: an acceptance attempted while `last_offer_pct` is null is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. Acceptance copies `last_offer_pct` into `negotiated_level_pct` and sets `met_threshold_pct` to that level multiplied by the federal tolerance of 0.90, rounded half-up to two decimal places. In other words, a district hits its target if it achieves at least ninety percent of the level it agreed to.

The budget branch is the sibling of the counter-offer loop and its side effects diverge. An offer tabled while `negotiation_round` is already exactly 4 drives `NEGOTIATING → ARBITRATED` instead of looping. It still increments `negotiation_round` and still records `offered_level_pct` into `last_offer_pct` along with the offering `last_offer_by_user_id` and `last_offer_by_role` — but **that offered level is discarded as a target**. The federal fallback becomes binding: `negotiated_level_pct` is set to `baseline_pct`, and `met_threshold_pct` becomes `baseline_pct` multiplied by 0.90, rounded half-up to two decimal places. The same alternation requirements apply to this call as to a counter-offer. Once the indicator is `ARBITRATED` the negotiation budget is spent and the arbitrated level is binding, so any further offer or any acceptance against it is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — as noted in §2.8, those two calls specifically are not caught by the state-transition check and fall through to this budget rule.

**The actual performance figure** is an aggregation over the indicator's cohort, and its membership is evaluated at call time rather than snapshotted. `denominator_count` is the number of students whose program matches the indicator's program, whose `cohort_year` matches the indicator's `cohort_year`, and whose `concentrator_status` is `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the numerator nor the denominator. `numerator_count` is the number of those same students whose `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5. The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places.

The two variants read that raw figure differently. The `PRELIMINARY_UNADJUSTED` variant ignores `small_cohort_flag` completely: it publishes the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null. This variant is recomputed on every read of the indicator and on every cascade that changes any cohort member's `concentrator_status`, and it never suppresses anything. The `FINAL_SMALL_COHORT_ADJUSTED` variant is the only one that may persist `actual_pct` or move the indicator's `status`, and it applies the suppression: when `small_cohort_flag` is true, the indicator is scored `NOT_SCORED` and `consecutive_miss_count` is left untouched regardless of how the raw percentage compares to `met_threshold_pct`. Identical student data can therefore show `preliminary_status_projection` of `NOT_MET` while the closed year records `NOT_SCORED`.

Closing the reporting year is the state's act and carries a single `closed_on` date. The call is admissible from `AGREED`, from `ARBITRATED`, from `NOT_MET` and from `MONITORING`; from `NOT_MET` or `MONITORING` it additionally requires the supplied `closed_on` to be strictly later than the `closed_on` already stored, because each close advances the reporting year. The close writes `actual_pct` from the final variant, stores `closed_on`, increments the indicator's `version`, and then takes exactly one of three branches.

When `denominator_count` is below 5 — including the case where it is zero — the indicator is scored `NOT_SCORED`. `actual_pct` still takes the final variant's output, which is null when `denominator_count` is zero and otherwise the unsuppressed percentage, and `consecutive_miss_count` is left exactly as it was. When `denominator_count` is at least 5 and `actual_pct` is at least `met_threshold_pct` (the comparison is inclusive), the indicator is scored `MET` and `consecutive_miss_count` is reset to 0. When `denominator_count` is at least 5 and `actual_pct` is strictly below `met_threshold_pct`, the indicator is scored `NOT_MET` and `consecutive_miss_count` increases by 1; from `NOT_MET` this is a self-loop that re-enters `NOT_MET` for a second consecutive miss. A `MONITORING` indicator that misses lands in `NOT_MET` on the same terms, and a `NOT_MET` or `MONITORING` indicator that recovers lands in `MET` with its miss counter reset to 0.

The increment of `consecutive_miss_count` is cascade link 1, and it is that increment reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates `NOT_MET → IMPROVEMENT_REQUIRED`. Link 2 in turn fires link 3, which suspends the program: a program of study in `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to `open_finding_codes`, and has its `version` incremented. And that suspension fires link 4: every expenditure charged to that program whose `status` is `REQUESTED` moves `REQUESTED → BLOCKED`, each with its own `version` increment. Certified, obligated, disallowed and voided lines are untouched. If the program is not in `STATE_APPROVED` when link 3 would fire, the chain simply stops there and the close still succeeds.

### 3.9. Improvement Plans and Lifting the Sanction

An escalated indicator demands a local improvement plan, and only a `CteDirector` may draft one. Drafting is admitted only while the target indicator's `status` is `IMPROVEMENT_REQUIRED`; any other status is `ERR_INVALID_INDICATOR_STATE`. The payload carries a `milestones` array whose elements each pair a `label` string with a `due_on` calendar date, and optionally a `funding_expenditure_id` naming the certified purchase that finances the work — or null for an unfunded plan. The new plan lands in `status` `DRAFT` with `revision_round` 0, `milestone_count` set to the number of elements in `milestones`, an empty `return_reasons` list, and `submitted_at` and `accepted_at` both null.

Funding, when claimed, must be real: a non-null `funding_expenditure_id` must point at an expenditure whose `status` is `CERTIFIED` or `OBLIGATED` and which is charged to the same program of study as the plan's indicator. A pointer to a merely requested, blocked, disallowed or voided line, or to a line charged to a different program, is refused with `ERR_PLAN_FUNDING_INVALID`. That check runs both when the plan is drafted and again each time it is submitted, because the referenced expenditure may have been voided in between.

Submitting a plan — optionally with a `submission_note` — moves it `DRAFT → SUBMITTED` on the first attempt and `RETURNED → SUBMITTED` on any revision, sets `submitted_at` to the current logical clock instant, and increments the plan's `version`. Substance is checked at submit time: `milestone_count` must be at least 3, and a thinner plan is refused with `ERR_MILESTONES_INSUFFICIENT`.

A `StateComplianceReviewer` rules on a submitted plan. Returning it carries a `return_reason`, appends that reason to the append-only `return_reasons` list, and increments `revision_round` by 1 — and the branch is chosen on the **incremented** value against the three-round revision budget. While the incremented `revision_round` is strictly below 3 the plan moves `SUBMITTED → RETURNED` and the district may revise and resubmit; this is the revision cycle, and since the counter starts at 0, the first and second returns take this branch. When the incremented `revision_round` equals exactly 3 — that is, on the third return — the sibling branch fires instead and the loop terminates: the plan moves `SUBMITTED → REJECTED_FINAL`, its parent indicator moves `IMPROVEMENT_REQUIRED → SANCTIONED`, and the indicator's program of study stays `SUSPENDED` while `PERF_SANCTION` is appended to its `open_finding_codes`. Both branches record the `return_reason` and increment the plan's `version`; only the terminal branch reaches beyond the plan.

Accepting a plan — optionally with an `acceptance_note` — is the mirror image of the sanction cascade and the only way a suspended program recovers. Acceptance requires the plan's parent indicator to be in `IMPROVEMENT_REQUIRED`, failing otherwise with `ERR_INVALID_INDICATOR_STATE`. The plan moves `SUBMITTED → ACCEPTED`, `accepted_at` is set to the current logical clock instant, and the chain runs. Link 2: the parent indicator moves `IMPROVEMENT_REQUIRED → MONITORING` with `consecutive_miss_count` reset to 0. Link 3, caused by that reset: the indicator's program of study moves `SUSPENDED → CHANGES_REQUESTED` and appends `PERF_IMPROVEMENT_ACCEPTED` to its `open_finding_codes`. Link 4, caused by that un-suspension: every expenditure charged to that program whose `status` is `BLOCKED` returns `BLOCKED → REQUESTED`, freeing it to be certified again. Every entity the chain touches has its `version` incremented. Note that the program lands in `CHANGES_REQUESTED` rather than back in `STATE_APPROVED`: recovery restores the district's ability to spend and to resubmit, but state approval must be earned again through the submission cycle of §3.4, and `federal_reporting_eligible` stays false until it is.

## 4. Endpoint Definitions

Status codes follow one rule throughout: an endpoint that brings a new resource into existence answers **201 Created**, and every other successful call — a read, an amendment, a state transition, a clock advance — answers **200 OK**. Failures carry the HTTP status listed against their error identifier in §5. Request and response payloads are not restated here; the fields each operation accepts and the side effects it produces are specified in the §3 workflow that owns it.

Collection reads accept the `limit` and `offset` parameters of §2.3 plus the filters named in their descriptions: programs may be filtered by `approval_status`, `cluster` or `clna_phase`; sequence courses by `segment` or `status`; credentials by `tier`; students by `cohort_year` or `concentrator_status`; committees, members, meetings, expenditures, indicators, plans and educators by `status`, and additionally members by `sector`, meetings by `agenda_kind` or `minutes_status`, expenditures by `category` or `asset_tag`, indicators by `reporting_year`, educators by `certification_route`, grant awards by `fiscal_year`, attainments by `student_id`, `credential_id` or `verification_status`, and improvement plans by `performance_indicator_id` or `funding_expenditure_id`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| GET | `/cte/programs-of-study` | List programs of study, newest created first, with optional filters. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/programs-of-study/{id}` | Retrieve one program of study, including its computed alignment index and CLNA phase. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/programs-of-study/{id}/sequence-courses` | List the sequence courses of a program in ascending position order. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/programs-of-study/{id}/credentials` | List the industry-recognized credentials on a program's approved list. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/programs-of-study/{id}/students` | List students enrolled in a program. | CteDirector, StateComplianceReviewer, SchoolRegistrar |
| GET | `/cte/programs-of-study/{id}/advisory-committees` | List the advisory committees attached to a program. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/programs-of-study/{id}/expenditures` | List expenditures charged to a program. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/programs-of-study/{id}/performance-indicators` | List the accountability indicators negotiated for a program. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/programs-of-study/{id}/educators` | List educators assigned to a program, refreshing any lapsed credential. | CteDirector, StateComplianceReviewer |
| GET | `/cte/sequence-courses/{id}` | Retrieve one sequence course. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/sequence-courses/{id}/dependents` | List the sequence courses that name this course as their prerequisite. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/credentials/{id}` | Retrieve one industry-recognized credential definition. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |
| GET | `/cte/students/{id}` | Retrieve one student, including computed credits earned and concentrator status. | CteDirector, StateComplianceReviewer, SchoolRegistrar |
| GET | `/cte/credential-attainments` | List credential attainments across students and credentials. | CteDirector, StateComplianceReviewer, SchoolRegistrar |
| GET | `/cte/credential-attainments/{id}` | Retrieve one immutable credential attainment record. | CteDirector, StateComplianceReviewer, SchoolRegistrar |
| GET | `/cte/advisory-committees/{id}` | Retrieve one advisory committee, including its quorum configuration and chair pointer. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/advisory-committees/{id}/members` | List committee members and their seat terms. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/committee-members/{id}` | Retrieve one committee member. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/advisory-committees/{id}/meetings` | List meetings of a committee, latest scheduled instant first. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/committee-meetings/{id}` | Retrieve one committee meeting with its documented minutes outcome. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair |
| GET | `/cte/grant-awards` | List federal grant awards, newest fiscal year first. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/grant-awards/{id}` | Retrieve one grant award, including its obligated, remaining and administrative-cap figures. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/grant-awards/{id}/expenditures` | List expenditures drawn against a grant award. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/expenditures/{id}` | Retrieve one expenditure, including its approved amount and allowability finding. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/performance-indicators/{id}` | Retrieve one performance indicator with negotiated level, actuals and miss history. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/improvement-plans` | List improvement plans. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/improvement-plans/{id}` | Retrieve one improvement plan with its revision counter. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer |
| GET | `/cte/educators/{id}` | Retrieve one educator with certification route and verified industry hours. | CteDirector, StateComplianceReviewer |
| POST | `/cte/programs-of-study` | Create a program of study in DRAFT with its CLNA not yet started. | CteDirector |
| PATCH | `/cte/programs-of-study/{id}` | Amend the descriptive attributes of a program of study while it is not state-approved. | CteDirector |
| POST | `/cte/programs-of-study/{id}/sequence-courses` | Add a course to the secondary-to-postsecondary sequence. | CteDirector |
| PATCH | `/cte/sequence-courses/{id}` | Revise a sequence course's credits, articulation flag, prerequisite, position or status. | CteDirector |
| POST | `/cte/programs-of-study/{id}/credentials` | Add an industry-recognized credential to the program's approved list. | CteDirector |
| POST | `/cte/programs-of-study/{id}/clna-advance` | Advance the comprehensive local needs assessment one phase, or re-open a certified or expired assessment. | CteDirector, StateComplianceReviewer |
| POST | `/cte/programs-of-study/{id}/submit` | Submit a draft or returned program of study for advisory-committee review. | CteDirector |
| POST | `/cte/programs-of-study/{id}/request-changes` | Return a program under committee review to the district with compliance findings. | StateComplianceReviewer |
| POST | `/cte/programs-of-study/{id}/state-approve` | Grant state approval to a program under committee review, unlocking federal expenditure certification. | StateComplianceReviewer |
| POST | `/cte/programs-of-study/{id}/students` | Enroll a student in a program of study as a participant. | SchoolRegistrar |
| POST | `/cte/students/{id}/credit-postings` | Post a signed credit delta earned by a student in one sequence course. | SchoolRegistrar |
| POST | `/cte/students/{id}/exit` | Record a student's exit from the program with a federal exit reason. | SchoolRegistrar |
| POST | `/cte/students/{id}/credential-attainments` | Record an immutable credential attainment for a student. | SchoolRegistrar, CteDirector |
| POST | `/cte/programs-of-study/{id}/advisory-committees` | Charter an advisory committee for a program of study, guarded by optimistic concurrency on the program's version. | CteDirector |
| POST | `/cte/advisory-committees/{id}/members` | Seat a member in a named committee seat for a fixed term. | CteDirector |
| POST | `/cte/advisory-committees/{id}/meetings` | Schedule a committee meeting with a declared agenda kind. | CommitteeChair |
| POST | `/cte/committee-meetings/{id}/minutes` | File or amend the minutes of a meeting, recording attendance and the endorsement vote. | CommitteeChair |
| POST | `/cte/grant-awards` | Record a federal grant award with its obligation window. | GrantFiscalOfficer |
| POST | `/cte/grant-awards/{id}/expenditures` | Request a charge against a grant award, guarded by optimistic concurrency on the award's version. | CteDirector |
| POST | `/cte/expenditures/{id}/certify-allowability` | Certify or disallow a requested expenditure under the federal allowable-use rules. | GrantFiscalOfficer |
| POST | `/cte/expenditures/{id}/obligate` | Record the purchase order that obligates a certified expenditure. | GrantFiscalOfficer |
| POST | `/cte/expenditures/{id}/void` | Void a certified or obligated expenditure, releasing its federal share back to the award. | GrantFiscalOfficer |
| POST | `/cte/programs-of-study/{id}/educators` | Assign an educator to a program of study on a declared certification route. | CteDirector |
| POST | `/cte/educators/{id}/verify-industry-hours` | Verify a tranche of documented industry experience hours toward an educator's route. | StateComplianceReviewer |
| POST | `/cte/programs-of-study/{id}/performance-indicators` | Open a federal performance indicator for a reporting year at its baseline level. | StateComplianceReviewer |
| POST | `/cte/performance-indicators/{id}/negotiation-offers` | Table a negotiated-level offer, or spend the final round and arbitrate to the baseline. | CteDirector, StateComplianceReviewer |
| POST | `/cte/performance-indicators/{id}/accept-level` | Accept the standing offer as the negotiated level. | CteDirector, StateComplianceReviewer |
| POST | `/cte/performance-indicators/{id}/close-reporting-year` | Close the reporting year: freeze the final actual, score it, and cascade any sanction. | StateComplianceReviewer |
| POST | `/cte/performance-indicators/{id}/improvement-plans` | Draft a local improvement plan for an indicator that requires one. | CteDirector |
| POST | `/cte/improvement-plans/{id}/submit` | Submit a draft or returned improvement plan to the state for review. | CteDirector |
| POST | `/cte/improvement-plans/{id}/return` | Return a submitted improvement plan for revision, or reject it finally once the revision budget is spent. | StateComplianceReviewer |
| POST | `/cte/improvement-plans/{id}/accept` | Accept a submitted improvement plan, lifting the sanction cascade off the program of study. | StateComplianceReviewer |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock, which every date and window rule reads. | CteDirector, StateComplianceReviewer, GrantFiscalOfficer, CommitteeChair, SchoolRegistrar |

## 5. Error Code Catalogue

Every failure response carries one of the identifiers below in `data.error_id`, together with the HTTP status shown. The condition that triggers each identifier is specified in the §2 or §3 narrative that owns the rule; the precedence between identifiers when a single request breaches several rules is fixed by the ladder in §2.7.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_COURSE_NOT_FOUND` | 404 |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_ATTAINMENT_NOT_FOUND` | 404 |
| `ERR_COMMITTEE_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_MEETING_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_EXPENDITURE_NOT_FOUND` | 404 |
| `ERR_INDICATOR_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_EDUCATOR_NOT_FOUND` | 404 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_STALE_GRANT_VERSION` | 412 |
| `ERR_INVALID_APPROVAL_TRANSITION` | 409 |
| `ERR_INVALID_CLNA_PHASE_TRANSITION` | 409 |
| `ERR_INVALID_EXPENDITURE_STATE` | 409 |
| `ERR_INVALID_INDICATOR_STATE` | 409 |
| `ERR_INVALID_PLAN_STATE` | 409 |
| `ERR_INVALID_MEETING_STATE` | 409 |
| `ERR_INVALID_EDUCATOR_STATE` | 409 |
| `ERR_POS_NOT_APPROVED` | 422 |
| `ERR_CLNA_NOT_CERTIFIED` | 422 |
| `ERR_CLNA_EXPIRED` | 422 |
| `ERR_GRANT_WINDOW_CLOSED` | 422 |
| `ERR_LABOR_MARKET_DATA_STALE` | 422 |
| `ERR_UNALLOWABLE_USE` | 422 |
| `ERR_CAPITAL_REVIEW_REQUIRED` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_EMPLOYER_SEAT_SHORTFALL` | 422 |
| `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE` | 422 |
| `ERR_PREREQUISITE_INVALID` | 422 |
| `ERR_PREREQUISITE_CYCLE` | 422 |
| `ERR_SEQUENCE_INCOMPLETE` | 422 |
| `ERR_CREDENTIAL_LIST_EMPTY` | 422 |
| `ERR_NO_ELIGIBLE_INSTRUCTOR` | 422 |
| `ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING` | 422 |
| `ERR_COMMITTEE_ENDORSEMENT_MISSING` | 422 |
| `ERR_ALIGNMENT_INDEX_BELOW_FLOOR` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 422 |
| `ERR_MILESTONES_INSUFFICIENT` | 422 |
| `ERR_PLAN_FUNDING_INVALID` | 422 |
| `ERR_INDUSTRY_HOURS_EXCEED_CLAIM` | 422 |
| `ERR_CREDENTIAL_PROGRAM_MISMATCH` | 422 |
| `ERR_EXAM_SCORE_REQUIRED` | 422 |
| `ERR_CREDIT_POSTING_BLOCKED` | 422 |
| `ERR_COURSE_NOT_ACTIVE` | 422 |
| `ERR_CREDIT_BALANCE_NEGATIVE` | 422 |
| `ERR_ADMIN_CAP_EXCEEDED` | 422 |
| `ERR_GRANT_FUNDS_EXCEEDED` | 422 |
| `ERR_SEAT_TERM_OVERLAP` | 409 |
| `ERR_ASSET_PERIOD_OVERLAP` | 409 |
| `ERR_DUPLICATE_ATTAINMENT` | 409 |
| `ERR_CIP_CODE_DUPLICATE` | 409 |
| `ERR_COURSE_CODE_DUPLICATE` | 409 |
| `ERR_CREDENTIAL_CODE_DUPLICATE` | 409 |
| `ERR_STUDENT_ID_DUPLICATE` | 409 |
| `ERR_FISCAL_YEAR_DUPLICATE` | 409 |
| `ERR_INDICATOR_DUPLICATE` | 409 |
| `ERR_CHAIR_ALREADY_SEATED` | 409 |
