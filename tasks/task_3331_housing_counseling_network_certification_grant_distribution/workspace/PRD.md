# Housing Counseling Network API — Product Requirements Document

## 1. Introduction

This document specifies the Housing Counseling Network API, the operational backbone for a national housing counseling network modeled on a chartered-membership grantmaker. The network charters local member organizations after a structured organizational assessment, runs a training institute that certifies counselors and practitioners across five program areas, and distributes federal grant funds to those members through a blended formula-and-competitive allocation process with non-federal match requirements. Every dollar that flows to a member is subject to expenditure reporting, compliance audit, and — where spending is disallowed — clawback, and every member's standing is continuously re-evaluated from open findings, failed reviews, and lapsed credentials.

The system exists to solve three intertwined problems. First, chartering decisions and grant awards must be defensible: scoring is weighted and banded, and the people who submit scores are never the people who countersign or award them. Second, grant funds must be conserved: formula pools and competitive pools are allocated under hard caps, disbursements can never exceed an award's total, and disallowed spending is credited back to the originating pools so no money vanishes. Third, compliance posture must be a living signal, not a quarterly report: a single failed file review, an unresolved audit finding, or too many lapsed certifications tightens a member's posture immediately and blocks operations accordingly, while escalation of an audit freezes the member outright.

All time-dependent behavior in the system — course windows opening and closing, certification lapse deadlines expiring, corrective plans going overdue — is driven by a single logical clock that the network director can advance explicitly. Nothing in this API reads the wall clock. The remainder of this document defines the global contracts every endpoint honors (§2), the business workflows and the rules scattered through them (§3), the endpoint table (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles: `NetworkDirector`, `Assessor`, `TrainingRegistrar`, `GrantOfficer`, `MemberAdmin`, `ComplianceReviewer`, and `Auditor`.

The `NetworkDirector` is the chartering authority and performance-review owner. When `X-User-Role` is `NetworkDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, though it may record it for audit. The `Assessor` runs organizational assessments but cannot adjudicate them; the `TrainingRegistrar` operates the training institute — courses, enrollments, grading, and certifications; the `ComplianceReviewer` reviews client files but cannot audit expenditures or review performance; the `Auditor` conducts expenditure audits and is deliberately segregated from the `GrantOfficer` who flags reports. When `X-User-Role` is any of `Assessor`, `TrainingRegistrar`, `ComplianceReviewer`, or `Auditor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, except that the server records it onto resources where the workflow requires a segregation-of-duties anchor: the `assessor_id` on an assessment that an `Assessor` submits, the `reviewer_id` on a grant application that a `GrantOfficer` scores, the `reviewer_id` on a file review that a `ComplianceReviewer` opens, and the `auditor_id` on a compliance audit. The `GrantOfficer` role is also opaque and follows the same recording rule. When `X-User-Role` is `MemberAdmin`, `X-User-ID` is the `id` of the acting `NetworkMember`; ownership checks on any resource that references a `NetworkMember` compare the resource's foreign-key field to `X-User-ID`. A `MemberAdmin` may therefore withdraw only their own organization's draft applications, register counselors only under their own organization, and act only on files and reports belonging to their own organization.

Segregation of duties is enforced as a first-class rule wherever one person's work must be checked by another: the operator who countersigns an assessment's scores must differ from the one who submitted them, and the operator who awards a grant application must differ from the one who recorded its competitive review score. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items before returning the page; it defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. `version` is an integer starting at its initial value on creation and incrementing by exactly one on every mutation, including mutations caused by cascading side effects from operations on other resources. All thirteen resource types in this system — members, assessments, counselors, courses, enrollments, certifications, grant cycles, grant applications, grant awards, disbursements, client files, file reviews, expenditure reports, compliance audits, and performance reviews — carry the full set; none omit `updated_at` or `version`.

### 2.5. The Logical Clock

All temporal reasoning in the system runs against a single logical clock, never the wall clock. At server startup the clock reads exactly `2026-09-01T00:00:00Z`; before any explicit set call it continues to read exactly that instant and does not advance on its own. A `NetworkDirector` may advance the clock to a supplied `to_iso8601` instant through the admin-only clock-setting capability; the response echoes the new reading as `current_utc`. Advancing the clock fires every system transition whose clock precondition now holds, in deterministic order: courses whose delivery window has opened move from `SCHEDULED` to `IN_SESSION`; courses whose delivery window has closed move from `IN_SESSION` to `CONCLUDED`, and any enrollment still `REGISTERED` at that moment fails with no score recorded and no continuing-education credit; certifications that have been `LAPSED` beyond their grace window move to `EXPIRED`. Timestamps the server records on behalf of workflows — `chartered_at`, `certified_at`, `opened_on`, `reviewed_at`, deadlines — are all taken from this logical clock.

### 2.6. Monetary Values, Scores, and Rounding

All money in the system is expressed as integer cents; there are no fractional-cent amounts anywhere. Where an allocation or requirement does not divide evenly, the rounding rule is stated with the calculation itself: competitive tier percentages and per-member formula shares are rounded down to whole cents before the waterfall remainder distributes the leftover cents, while match requirements are rounded up to whole cents. Composite assessment scores are the one non-integer quantity: they are rounded half up to exactly two decimal places. Counseling effort is recorded in hours with exactly one decimal place. Performance, review, enrollment, and assessment dimension scores are integers in the range 0 to 100 inclusive.

### 2.7. Nested and Referential Validation

When a request path or payload references resources by identifier, every identifier must resolve to an existing resource before any business rule is evaluated. Path identifiers are validated left to right, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Foreign keys carried in request bodies — a counselor's employing member, an application's cycle and member, an award's application, a disbursement's or report's award, a file's member and counselor, a review's client file, an audit's award or parent audit — are validated the same way. Beyond mere existence, the system enforces cross-entity referential integrity: the counselor assigned to a client file must belong to the member organization that owns the file, a certification's program area must agree with the program area of the course or file it is matched against, and an award's member and cycle are copied from its application rather than supplied independently. Violations of these consistency rules are rejected with `ERR_CROSS_ENTITY_MISMATCH` (HTTP 422).

### 2.8. Optimistic Concurrency Control

Two write operations in the system require the caller to declare the version of a parent entity it last observed, so that a client acting on a stale view cannot overwrite changes it has not seen.

Creating a grant application requires the non-optional field `expected_cycle_version`, carrying the client-observed `version` of the target grant cycle. If the cycle's current `version` has advanced since the client read it — for example because the formula phase was locked or another application was created against the cycle — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Note that successfully creating an application itself increments the cycle's `version` by one, so two applications drafted against the same observed version cannot both succeed without the second re-reading the cycle.

Activating a grant award requires the non-optional field `expected_award_version`, carrying the client-observed `version` of the award. If the award's current `version` has advanced — because a match verification or a clawback adjusting entry mutated it in the meantime — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). Verifying match and activating each increment the award's `version` by one. Endpoints not named here do not take a version field.

### 2.9. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed order so that the error a client receives is deterministic. The order is: first authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization for the endpoint (`ERR_UNAUTHORIZED`); then existence of every referenced resource, path identifiers left to right (`ERR_NOT_FOUND`); then whether the target resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`); then segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`); then the member compliance-posture gate (`ERR_MEMBER_POSTURE_BLOCKED`); then course capacity (`ERR_COURSE_FULL`); then course prerequisites (`ERR_PREREQUISITE_NOT_MET`); then logical-clock window gates (`ERR_WINDOW_CLOSED`); then cross-entity referential integrity (`ERR_CROSS_ENTITY_MISMATCH`); then fiscal sufficiency of pools, award totals, and disbursed amounts (`ERR_POOL_EXHAUSTED`); then the match requirement at activation (`ERR_MATCH_NOT_MET`); then uniqueness constraints (`ERR_DUPLICATE`); then payload shape, enum validity, and range checks (`ERR_INVALID_REQUEST`); and finally the optimistic-concurrency version check (`ERR_STALE_VERSION`). A charter requirement — such as the rule that only `CHARTERED` members may submit applications — surfaces as `ERR_MEMBER_NOT_CHARTERED` (HTTP 422) within this ordering at the point where the business rule is evaluated.

### 2.10. Compliance Posture

Every member organization carries a derived `compliance_posture`, one of `CLEAR`, `WATCH`, `RESTRICTED`, or `FROZEN`, recomputed whenever any of its inputs change: a file review failing or being remediated, an audit issuing findings, resolving, or escalating, a performance review entering corrective action or closing its plan, or a counselor's certification lapsing. The recompute proceeds in a fixed propagation order: first the member's `open_finding_count` is recomputed, then its `failed_review_flag`, then the posture itself. Posture gates operations throughout the system: `FROZEN` members cannot begin counseling on client files, submit grant applications, receive awards, or receive new disbursements, and `RESTRICTED` members additionally cannot submit grant applications. Each such refusal carries `ERR_MEMBER_POSTURE_BLOCKED` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Chartering a Member Organization

A prospective member enters the system when a `NetworkDirector` registers it with its `legal_name`, its nine-digit `ein`, the two-letter `state_code` of its principal office, and the list of `service_regions` — county FIPS codes, at least one and at most fifty — it proposes to serve. The legal name and the EIN must each be unique across all member organizations, and the EIN must be exactly nine digits; duplicates are rejected with `ERR_DUPLICATE`. The new member begins life as an `APPLICANT`, with `chartered_at` null, `open_finding_count` at zero, `failed_review_flag` false, and `compliance_posture` derived as `CLEAR`.

Chartering proceeds through an organizational assessment. An `Assessor` begins the assessment on an `APPLICANT` member, which moves the member to `UNDER_ASSESSMENT`, increments the member's `version` by one, and creates the assessment record in `DRAFT`. The assessor then submits the three dimension scores — `governance_score`, `finance_score`, and `program_capacity_score`, each an integer from 0 to 100 — and all three must be present for the submission to be accepted. Submitting records the caller's `X-User-ID` as the assessment's `assessor_id` and computes the provisional results: the provisional `composite_score` is the weighted sum of the three dimensions — governance weighted at 0.40, finance at 0.35, and program capacity at 0.25 — rounded half up to two decimal places, and the `provisional_rating` is read off the rating bands described below. The assessment is then `SUBMITTED`.

Countersigning is a separate act by a `NetworkDirector`, and the director who countersigns must not be the assessor who submitted; if they are the same operator the countersign is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful countersign moves the assessment from `SUBMITTED` to `SCORED`. A `DRAFT` assessment may instead be withdrawn by an `Assessor`, moving it to `WITHDRAWN` and returning the member to `APPLICANT` if it was `UNDER_ASSESSMENT`.

Final adjudication belongs to the `NetworkDirector` and accepts a `site_visit_adjustment`, an integer from -10 to +10 reflecting the site visit. Adjudication recomputes the composite under the final variant: the same weighted base as the provisional computation, plus the site-visit adjustment, clamped so the result never exceeds 100, then rounded half up to two decimal places. The `final_rating` falls out of the bands: a composite of at least 85 is `STRONG`, at least 70 but below 85 is `ADEQUATE`, at least 50 but below 70 is `MARGINAL`, and below 50 is `DEFICIENT`. The same bands apply to the provisional rating; identical dimension scores yield a different composite and potentially a different rating whenever the adjustment is non-zero. The adjudicated rating drives the member's charter transition: a `STRONG` or `ADEQUATE` final rating moves the member from `UNDER_ASSESSMENT` to `PROVISIONAL`, while a `DEFICIENT` rating sends the member back to `APPLICANT` to revise and try again; both outcomes increment the member's `version`. `ADJUDICATED` and `WITHDRAWN` are the assessment's terminal states.

A `PROVISIONAL` member becomes `CHARTERED` when the `NetworkDirector` charters it, but only once at least one counselor of the member holds a certification in `CERTIFIED` status. Chartering stamps `chartered_at` with the current logical clock and increments the member's `version`. Chartering date matters beyond ceremony: the member's tenure relative to `chartered_at` determines which match rate applies to its grant awards for the first twenty-four months.

Probation and revocation close the loop. A member in `PROBATION` may be reinstated to `CHARTERED` by the `NetworkDirector` only when its `open_finding_count` is zero and its `failed_review_flag` is false; otherwise the reinstatement is refused. A `NetworkDirector` may revoke the charter of a `PROBATION` member, recording the supplied `revocation_reason`. Revocation is the member's terminal state and cascades forcefully: every grant award of the member in `DISBURSING`, `ACTIVE`, or `SUSPENDED` status transitions to `TERMINATED`; every counselor of the member in `ACTIVE` status transitions to `SUSPENDED`; and every certification in `CERTIFIED` status held by those counselors transitions to `REVOKED`. The member's `version` increments by one. `REVOKED` members are excluded from congressional reporting aggregates.

### 3.2. Counselors and the Training Institute

Counselors are registered under a member organization by a `MemberAdmin` of that member or by a `NetworkDirector`, supplying `member_id`, `full_name`, and `email`; the email must be unique across all counselors. A counselor starts `ACTIVE`, with `ce_credits_accumulated` at zero and `ce_window_end` set to the registration timestamp plus twenty-four months — the length of the continuing-education window. A counselor whose member is revoked is suspended automatically; a `NetworkDirector` may also suspend an `ACTIVE` counselor directly, and either path lapses every certification that counselor holds in `CERTIFIED` status, moving each to `LAPSED`. A `SUSPENDED` counselor may be reactivated only while their employing member is `CHARTERED`; reactivating a counselor whose member is in any other charter state is refused with `ERR_MEMBER_NOT_CHARTERED`. Separation is terminal: separating an `ACTIVE` or `SUSPENDED` counselor moves them to `SEPARATED`, withdraws every enrollment of theirs still in `REGISTERED` status — each withdrawal decrementing the owning course's `seats_taken` by one — and revokes every certification of theirs not already in a terminal state.

Courses are the institute's catalog. A `TrainingRegistrar` creates a course with a `course_code` — two to four uppercase letters, a hyphen, and three digits, unique across the catalog — plus a `title`, the `program_area` it certifies toward, a `capacity` of between 1 and 500 seats, whether it is `ce_eligible`, how many `ce_credits` completion awards when it is (from 0 to 60), and a delivery window from `delivery_start` (inclusive) to `delivery_end` (exclusive, strictly after the start). A course may declare a `prerequisite_course_id`, a self-referential link to another course, or none. Courses begin `SCHEDULED`; the logical clock moves them to `IN_SESSION` when it reaches the delivery start and to `CONCLUDED` when it reaches the delivery end. A `TrainingRegistrar` may cancel a `SCHEDULED` course, moving it to `CANCELLED`, which withdraws every registration and decrements `seats_taken` accordingly. Seat occupation follows half-open semantics over the delivery window: enrollment is only possible while the clock is within the window and while `seats_taken` remains strictly below `capacity`; a course at capacity rejects further enrollments with `ERR_COURSE_FULL`, and an enrollment attempted outside the delivery window is rejected with `ERR_WINDOW_CLOSED`. Where a prerequisite is declared, the counselor must hold a `COMPLETED` enrollment in that prerequisite course, failing which the enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`; delivery windows of courses sharing a prerequisite chain must not overlap unless sequential. Each successful enrollment names its `course_id` and `counselor_id`, increments the course's `seats_taken` by one, and starts the enrollment in `REGISTERED`.

Grading happens while the course is `IN_SESSION`. A `TrainingRegistrar` records a `score` from 0 to 100 against an enrollment. The enrollment's `pass_threshold` is snapshotted at grading time from the course policy constant of 70. A score at or above the threshold completes the enrollment; if the course is CE-eligible, the counselor's `ce_credits_accumulated` grows by the course's `ce_credits`, and every certification the counselor holds in `CERTIFIED` status has its `continuing_requirement_met` recomputed. A score below the threshold fails the enrollment and frees the seat, decrementing `seats_taken` by one. Any enrollment still `REGISTERED` when the course concludes fails automatically with a null score and no CE credit. A registration may also be withdrawn by a `TrainingRegistrar` or a `MemberAdmin`, which likewise decrements `seats_taken` by one.

### 3.3. Certifications and Continuing Education

A certification opens in `CANDIDATE` status when a `TrainingRegistrar` creates it for a counselor in one of the five program areas: `HOMEOWNERSHIP`, `RENTAL`, `COMMUNITY_DEVELOPMENT`, `FINANCIAL_CAPABILITY`, or `FORECLOSURE_PREVENTION`. Certifying a candidate requires three things at once: the counselor holds a `COMPLETED` enrollment in a course of the same program area as the certification — a mismatch is rejected with `ERR_CROSS_ENTITY_MISMATCH`, and the absence of any such completion with `ERR_CERTIFICATION_REQUIREMENT_UNMET`; the counselor is `ACTIVE`; and the counselor's member is `PROVISIONAL` or `CHARTERED`. Certification stamps `certified_at` from the logical clock and sets `lapse_deadline` to twenty-four months later, matching the continuing-education window length.

Continuing compliance is evaluated against the requirement of 30 CE credits: `continuing_requirement_met` is true exactly when the holder's `ce_credits_accumulated` is at least 30 at evaluation time. After the lapse deadline passes, a `TrainingRegistrar` may evaluate the continuing requirement; evaluation before the deadline is rejected with `ERR_WINDOW_CLOSED`. When the requirement is unmet, the certification lapses, moving from `CERTIFIED` to `LAPSED`, and the member's posture is recomputed if the lapse pushes the member's lapsed-certification count above the posture threshold described in §3.7. A lapsed certification can be reinstated — the loop back to `CERTIFIED` — once the counselor has accumulated at least 30 CE credits and is `ACTIVE`; reinstatement with insufficient credits is rejected with `ERR_CERTIFICATION_REQUIREMENT_UNMET`. Reinstatement restamps `certified_at` and resets the `lapse_deadline` to a fresh window. A certification left `LAPSED` for more than 90 days past its lapse deadline expires automatically when the logical clock crosses that grace boundary, moving to `EXPIRED`, which is terminal; `REVOKED` is the other terminal state, reached through counselor separation, suspension cascades, and member revocation.

### 3.4. Grant Cycles and Applications

A `GrantOfficer` opens a grant cycle for a `fiscal_year` — an integer from 2000 to 2100, unique across cycles — declaring the `formula_pool_cents` available for the formula component and the `competitive_pool_cents` available for the competitive component, each zero or greater. The cycle begins `OPEN`, with `formula_committed_cents` and `competitive_committed_cents` both at zero.

A `MemberAdmin` drafts an application against an open cycle, naming the `cycle_id`, the `member_id` of their own organization, the `program_area` the application covers, the `requested_formula_cents`, the `requested_competitive_cents` (zero means a formula-only application), and the `pledged_match_cents` of non-federal match the organization pledges. The draft request must also carry `expected_cycle_version` as described in §2.8, and its creation increments the cycle's `version` by one. Submitting the draft is allowed only while the cycle is `OPEN` — a submission against a cycle that has moved on is rejected with `ERR_WINDOW_CLOSED` — and only for a member whose `charter_status` is `CHARTERED` (otherwise `ERR_MEMBER_NOT_CHARTERED`) and whose `compliance_posture` is `CLEAR` or `WATCH`; a `RESTRICTED` or `FROZEN` member's submission is rejected with `ERR_MEMBER_POSTURE_BLOCKED`. A draft may be withdrawn by a `MemberAdmin` of the applicant member.

When the `GrantOfficer` locks the formula phase, the cycle moves from `OPEN` to `FORMULA_LOCKED`, every submitted application in the cycle moves to `UNDER_REVIEW`, and the cycle's `version` increments. Opening competitive review advances the cycle to `COMPETITIVE_REVIEW`, again incrementing its `version`. While applications are under review, a `GrantOfficer` records each application's competitive `review_score` — an integer from 0 to 100 — which also records the scorer's `X-User-ID` as the application's `reviewer_id`. A `review_score` is required for any application whose requested competitive component is greater than zero before the cycle can be finalized. Finalizing moves the cycle from `COMPETITIVE_REVIEW` to `AWARDED` and increments its `version`; finalization is blocked while any under-review application with a competitive request lacks a score.

Awarding happens per application, after the cycle is `AWARDED`, and creates the grant award with all of its computed components; each application yields exactly one award, and a second award attempt against the same application is rejected with `ERR_DUPLICATE`. The award's `cycle_id` and `member_id` are copied from the application. Awarding is refused when the applicant member's posture is `FROZEN` (`ERR_MEMBER_POSTURE_BLOCKED`), and the awarding officer must not be the operator who recorded the application's review score (`ERR_SEGREGATION_OF_DUTIES`). An under-review application may instead be declined outright, moving it to `DECLINED`.

The formula component of the award is computed across the whole cycle at award time. The eligible set is the members who are `CHARTERED` and hold an under-review application in the cycle; applications declined or withdrawn are excluded. Each eligible member's weight is one plus the households it served in the prior fiscal year (per the rollup in §3.8), multiplied by the regional need factor for the member's state — 1.0 by default. Each member's raw share is the formula pool multiplied by its weight divided by the total weight across the eligible set. The per-application cap applies next: the member's formula allocation is the smaller of its raw share and its `requested_formula_cents`, and when the request falls below the raw share the excess redistributes to uncapped members through the same waterfall. Rounding is deliberate: each member's share is rounded down to whole cents first, then the residual cents are distributed one at a time to members in order of decreasing weight, breaking ties by the application's creation timestamp ascending, until the residual is exhausted. The result lands on the award as `formula_component_cents`, and no award may push the cycle's `formula_committed_cents` above `formula_pool_cents`; an allocation that would exceed the pool is rejected with `ERR_POOL_EXHAUSTED`.

The competitive component tiers on the application's `review_score`, applied marginally to the request rather than cumulatively across tiers. A score of at least 90 funds the full request. A score of at least 75 but below 90 funds 80 percent of the request, rounded down to whole cents. A score of at least 60 but below 75 funds 50 percent of the request, rounded down to whole cents. A score below 60 funds nothing: the competitive component is zero, and an application with a competitive request but a score below the competitive floor of 60 cannot be awarded that component — attempting the award is rejected with `ERR_COMPETITIVE_SCORE_TOO_LOW` — though the same application may still win its formula component. A formula-only application (zero competitive request) always has a zero competitive component regardless of score. The result lands as `competitive_component_cents`, and the cycle's `competitive_committed_cents` likewise may never exceed `competitive_pool_cents`, with overflow rejected as `ERR_POOL_EXHAUSTED`. Committing an award adds its formula component to the cycle's `formula_committed_cents` and its competitive component to the cycle's `competitive_committed_cents`.

Finally, closing the cycle is allowed only from `AWARDED` and only once every award in the cycle has reached a terminal award state — `RECONCILED`, `CLOSED`, or `TERMINATED`.

### 3.5. Awards, Match, and Disbursements

A new award begins in `DISBURSING`, with `disbursed_cents` at zero and `verified_match_cents` at zero. The award carries a `required_match_cents` computed at creation: take the total of the formula and competitive components first, then select the rate by member tenure — ten percent when the member was chartered within the preceding twenty-four months (the provisional-period rate), otherwise twenty-five percent — and round the product up to whole cents. The rate never feeds back into the total; evaluation order is total, then rate, then ceiling.

Match verification grows monotonically: each verification by a `GrantOfficer` adds the supplied `additional_match_cents` to `verified_match_cents` and increments the award's `version` by one. Activation moves the award from `DISBURSING` to `ACTIVE` and is permitted only once `verified_match_cents` is at least `required_match_cents`; activating short of the requirement is rejected with `ERR_MATCH_NOT_MET`. Activation must carry `expected_award_version` as described in §2.8 and itself increments the award's `version`.

Disbursements are tranches against the award. A `GrantOfficer` creates a disbursement with the `award_id` and an `amount_cents` greater than zero; the tranche starts `PENDING` and receives a `tranche_index`, its 1-based ordinal within the award assigned by creation order ascending. Posting a tranche requires the award to be `DISBURSING` or `ACTIVE` and requires that the award's already-disbursed total plus this tranche not exceed the sum of the award's formula and competitive components; an over-posting is rejected with `ERR_POOL_EXHAUSTED`. Posting moves the tranche to `POSTED` and ledger-syncs the award: `disbursed_cents` grows by exactly the tranche amount. A pending tranche may be voided instead, moving it to `VOIDED`. Creating a new disbursement against an award whose member is `FROZEN` is blocked by the posture gate, and a suspended award blocks new disbursement creation while suspended.

An `ACTIVE` award may be suspended by a `GrantOfficer`, and resume only when no audit in `FINDINGS_ISSUED` or `ESCALATED` exists for it. Reconciliation is the fiscal endgame: an `ACTIVE` award reconciles only when its `disbursed_cents` equals the sum of its two components exactly and every expenditure report against it has reached `ACCEPTED` or `AUDITED`; a premature reconcile is rejected with `ERR_AWARD_NOT_RECONCILABLE`. A reconciled award closes to `CLOSED`. Awards in `DISBURSING`, `ACTIVE`, or `SUSPENDED` whose member's charter is revoked terminate automatically.

### 3.6. Expenditure Reports, Audits, and Clawback

Against an active grant, the member's `MemberAdmin` submits expenditure reports covering a period from `period_start` (inclusive) to `period_end` (exclusive, strictly after the start), claiming `reported_spent_cents` for the period. Each report derives a `cumulative_spent_cents`: the sum of reported spending over that award's reports in `ACCEPTED` or `AUDITED` status whose period starts on or before this report's period start. A report begins `SUBMITTED`. A `GrantOfficer` accepts it only while its cumulative spend stays within the award's `disbursed_cents`; a report whose cumulative claim exceeds what has been disbursed is rejected with `ERR_POOL_EXHAUSTED`. Acceptance moves the report to `ACCEPTED` and reconciles the award-level spending totals. Alternatively, the officer flags the report, moving it to `FLAGGED` and spawning a compliance audit in `OPEN` for the award — the first link of a transitive cascade.

Audits belong to an `Auditor`, whose `X-User-ID` is recorded as the audit's `auditor_id`, and who is organizationally segregated from the officer who flagged the report. Issuing findings moves the audit from `OPEN` to `FINDINGS_ISSUED` and records a `disallowance_cents` of zero or more; issuance moves the linked flagged report from `FLAGGED` to `AUDITED` — the second cascade link — and recomputes the member's `open_finding_count`, since an audit in `FINDINGS_ISSUED` counts as an open finding. Findings resolve to `RESOLVED`, again recomputing the member's open findings. Where remediation fails, the auditor re-opens the findings: the re-open creates a successor audit in `OPEN` whose `parent_audit_id` links back to the superseded one, forming a self-referential chain; initial audits carry no parent.

Escalation is the hard edge and is available only when the disallowance is greater than zero. Escalating moves the audit to `ESCALATED` and fires the third cascade link: the award transitions to `SUSPENDED`; the award's `disbursed_cents` is reduced by `disallowance_cents` through a clawback adjusting entry; and the disallowed amount is credited back to the cycle's pools in waterfall order — the competitive pool's committed total first, then the formula pool's — so that the cycle's pools are conserved. Escalation also forces the member's `compliance_posture` to `FROZEN` on recompute. An audit in `ESCALATED` is terminal, as is one in `RESOLVED`.

### 3.7. Client Files, File Reviews, and the Posture Rule

Member organizations serve households through client files. A `MemberAdmin` opens a file with the `member_id` of their own organization, the assigned `counselor_id`, the `program_area` under which the household is served, and the `household_size` — between 1 and 20 persons. The counselor must belong to the file's member, or creation is rejected with `ERR_CROSS_ENTITY_MISMATCH`. The file records its `opened_on` from the logical clock, starts in `OPEN`, and carries `counseling_hours` starting at zero, recorded to one decimal place, and a null `outcome_code`.

Beginning counseling requires the assigned counselor to be `ACTIVE` and to hold a certification in `CERTIFIED` status whose program area matches the file's; a mismatch is again `ERR_CROSS_ENTITY_MISMATCH`. The member's posture must not be `FROZEN`, else the action is rejected with `ERR_MEMBER_POSTURE_BLOCKED`. Counseling moves the file from `OPEN` to `COUNSELING`.

Recording an outcome moves the file from `COUNSELING` to `OUTCOME_RECORDED`. The `outcome_code` is one of `PURCHASED_HOME`, `MORTGAGE_READY`, `RENTAL_STABILIZED`, `FORECLOSURE_AVERTED`, `BUDGET_PLAN_ADOPTED`, or `NO_OUTCOME`, and `counseling_hours` is recorded alongside. A file recorded with `NO_OUTCOME` must show at least 2.0 hours of counseling; recording `NO_OUTCOME` with fewer hours is rejected with `ERR_OUTCOME_HOURS_INSUFFICIENT`. Closing the file requires every file review against it to have reached `PASSED` or `REMEDIATED`; a close attempted while a review is still `OPEN` or `FAILED` is rejected with `ERR_REVIEW_PENDING`.

File reviews are the ComplianceReviewer's instrument. Opening a review on a client file records the reviewer's `X-User-ID` as `reviewer_id` and starts the review `OPEN`. Passing the review stamps `reviewed_at` and recomputes the member's `open_finding_count`. Failing the review requires a non-empty list of `deficiency_codes`, stamps `reviewed_at`, increments the member's `open_finding_count` by one, and recomputes posture; when the failure pushes the member's failed-review ratio past the configured failed-review ratio threshold, the member's `failed_review_flag` is set to true. Remediating a failed review decrements `open_finding_count` by one and recomputes posture again.

The posture rule itself, restated in full because so many workflows depend on it: recompute `open_finding_count` as the count of the member's file reviews in `FAILED` status plus the count of compliance audits in `FINDINGS_ISSUED` against the member's awards; count the member's lapsed certifications; then classify. If any audit against the member is `ESCALATED`, the posture is `FROZEN`. Otherwise, if the open finding count is at least 3 or the member is in `PROBATION`, the posture is `RESTRICTED`. Otherwise, if there is at least one open finding, or the `failed_review_flag` is set, or the member's lapsed certifications exceed 2, the posture is `WATCH`. Otherwise the posture is `CLEAR`.

### 3.8. Performance Reviews and Congressional Reporting

The `NetworkDirector` opens a performance review for a member and a `review_period` label such as FY2026-H1, unique per member; a duplicate period for the same member is rejected with `ERR_DUPLICATE`. The review opens in `OPEN`. Scoring it records a `review_score` from 0 to 100 and recomputes the review's `households_served`: the count of the member's client files in `OUTCOME_RECORDED` or `CLOSED` status whose outcome code is recorded and is not `NO_OUTCOME` and whose `opened_on` falls within the federal fiscal-year window — on or after October 1 of the prior calendar year and strictly before October 1 of the named fiscal year's calendar year (equivalently, the half-open window from FY October 1 through the following September 30). Files still open or in counseling never count.

Resolution forks on the score, with the verdict supplied as `verdict`. A score of at least 70 resolves the review as `SATISFACTORY`, a terminal state with no further side effects. A score below 70 resolves to `CORRECTIVE_ACTION`, which sets `corrective_plan_due` to the current logical clock plus 60 days, sets the member's `failed_review_flag` to true, and recomputes posture. From corrective action there are two exits. Closing the plan is permitted only while the logical clock has not passed the plan's due date — an attempt after the deadline is rejected with `ERR_WINDOW_CLOSED` — and only while the member's `open_finding_count` is zero; closing moves the review to `CLOSED`, clears the `failed_review_flag` to false, and recomputes posture. Escalating an overdue corrective plan — one whose due date has passed — moves the review to `ESCALATED` and moves the member from `CHARTERED` to `PROBATION`, with posture recomputed (the member becomes `RESTRICTED` or `FROZEN` per the posture rule) and the member's `version` incremented.

For congressional reporting, the system answers a households-served rollup for a given `fiscal_year`: the same per-member count defined above, aggregated across all members whose charter has not been revoked, grouped by program area. The report returns the `fiscal_year`, the `total_households` across those members, and the per-area breakdown in `by_program_area`. Because the congressional variant aggregates across members and groups by program area, its numbers differ from any single member's review rollup even though both draw on the same underlying files.

## 4. Endpoint Definitions

All endpoints are mounted under the `/housing-network` prefix. Creating a new resource returns HTTP 201; operations that modify or transition an existing resource return HTTP 200. All request and response bodies follow the envelope in §2.2, list endpoints paginate per §2.3, and the authorized roles below are exhaustive — any other role is rejected with `ERR_UNAUTHORIZED`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /housing-network/_clock/set_current_utc | Advance the logical clock; fires due system transitions | NetworkDirector |
| POST | /housing-network/members | Register a network member applicant | NetworkDirector |
| GET | /housing-network/members | List members, filterable by `charter_status`, `state_code`, `compliance_posture` | NetworkDirector, Assessor, GrantOfficer, Auditor, ComplianceReviewer, MemberAdmin, TrainingRegistrar |
| GET | /housing-network/members/{id} | Get one member | NetworkDirector, Assessor, GrantOfficer, Auditor, ComplianceReviewer, MemberAdmin, TrainingRegistrar |
| POST | /housing-network/members/{id}/begin-assessment | Move an APPLICANT member into assessment; creates a DRAFT assessment | Assessor |
| POST | /housing-network/members/{id}/charter | Charter a PROVISIONAL member | NetworkDirector |
| POST | /housing-network/members/{id}/reinstate | Return a PROBATION member to CHARTERED | NetworkDirector |
| POST | /housing-network/members/{id}/revoke | Revoke a PROBATION member's charter; cascades to awards, counselors, certifications | NetworkDirector |
| GET | /housing-network/assessments | List assessments, filterable by `member_id`, `assessment_status` | NetworkDirector, Assessor |
| GET | /housing-network/assessments/{id} | Get an assessment | NetworkDirector, Assessor |
| POST | /housing-network/assessments/{id}/submit | Submit dimension scores; computes provisional composite and rating | Assessor |
| POST | /housing-network/assessments/{id}/score | Director countersigns submitted scores | NetworkDirector |
| POST | /housing-network/assessments/{id}/adjudicate | Final adjudication with site-visit adjustment; drives the charter transition | NetworkDirector |
| POST | /housing-network/assessments/{id}/withdraw | Withdraw a DRAFT assessment | Assessor |
| POST | /housing-network/counselors | Register a counselor under a member | MemberAdmin, NetworkDirector |
| GET | /housing-network/counselors | List counselors, filterable by `member_id`, `counselor_status` | NetworkDirector, MemberAdmin, TrainingRegistrar, ComplianceReviewer |
| GET | /housing-network/counselors/{id} | Get a counselor | NetworkDirector, MemberAdmin, TrainingRegistrar, ComplianceReviewer |
| POST | /housing-network/counselors/{id}/suspend | Suspend an ACTIVE counselor; lapses their certifications | NetworkDirector |
| POST | /housing-network/counselors/{id}/reactivate | Reactivate a SUSPENDED counselor of a CHARTERED member | NetworkDirector |
| POST | /housing-network/counselors/{id}/separate | Separate a counselor; withdraws registrations and revokes certifications | NetworkDirector |
| POST | /housing-network/courses | Create a course | TrainingRegistrar |
| GET | /housing-network/courses | List courses, filterable by `program_area`, `course_status`, `prerequisite_course_id` | NetworkDirector, TrainingRegistrar, MemberAdmin |
| GET | /housing-network/courses/{id} | Get a course | NetworkDirector, TrainingRegistrar, MemberAdmin |
| GET | /housing-network/courses/{id}/enrollments | List enrollments of a course | NetworkDirector, TrainingRegistrar |
| POST | /housing-network/courses/{id}/cancel | Cancel a SCHEDULED course; withdraws its enrollments | TrainingRegistrar |
| POST | /housing-network/courses/{id}/enrollments | Enroll a counselor in a course | TrainingRegistrar, MemberAdmin |
| GET | /housing-network/enrollments | List enrollments, filterable by `counselor_id`, `enrollment_status` | NetworkDirector, TrainingRegistrar, MemberAdmin |
| GET | /housing-network/enrollments/{id} | Get an enrollment | NetworkDirector, TrainingRegistrar, MemberAdmin |
| POST | /housing-network/enrollments/{id}/grade | Grade an enrollment of an IN_SESSION course | TrainingRegistrar |
| POST | /housing-network/enrollments/{id}/withdraw | Withdraw a registration | TrainingRegistrar, MemberAdmin |
| POST | /housing-network/certifications | Open a CANDIDATE certification for a counselor in a program area | TrainingRegistrar |
| GET | /housing-network/certifications | List certifications, filterable by `counselor_id`, `certification_status`, `program_area` | NetworkDirector, TrainingRegistrar, MemberAdmin, ComplianceReviewer |
| GET | /housing-network/certifications/{id} | Get a certification | NetworkDirector, TrainingRegistrar, MemberAdmin, ComplianceReviewer |
| POST | /housing-network/certifications/{id}/certify | Certify a CANDIDATE after the required course completion | TrainingRegistrar |
| POST | /housing-network/certifications/{id}/evaluate-continuing-requirement | Evaluate CE compliance after the lapse deadline | TrainingRegistrar |
| POST | /housing-network/certifications/{id}/reinstate | Reinstate a LAPSED certification when CE credits suffice | TrainingRegistrar |
| POST | /housing-network/grant-cycles | Create a grant cycle | GrantOfficer |
| GET | /housing-network/grant-cycles | List grant cycles, filterable by `cycle_status` | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| GET | /housing-network/grant-cycles/{id} | Get a grant cycle | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| POST | /housing-network/grant-cycles/{id}/lock-formula | Lock the formula phase; SUBMITTED applications move UNDER_REVIEW | GrantOfficer |
| POST | /housing-network/grant-cycles/{id}/open-competitive-review | Advance the cycle to competitive review | GrantOfficer |
| POST | /housing-network/grant-cycles/{id}/finalize | Finalize the cycle to AWARDED | GrantOfficer |
| POST | /housing-network/grant-cycles/{id}/close | Close an AWARDED cycle once all awards are terminal | GrantOfficer |
| POST | /housing-network/grant-applications | Create a DRAFT grant application (OCC on cycle version) | MemberAdmin |
| GET | /housing-network/grant-applications | List applications, filterable by `cycle_id`, `member_id`, `application_status` | NetworkDirector, GrantOfficer, MemberAdmin |
| GET | /housing-network/grant-applications/{id} | Get an application | NetworkDirector, GrantOfficer, MemberAdmin |
| POST | /housing-network/grant-applications/{id}/submit | Submit a DRAFT application | MemberAdmin |
| POST | /housing-network/grant-applications/{id}/score | Record the competitive review score | GrantOfficer |
| POST | /housing-network/grant-applications/{id}/award | Award an UNDER_REVIEW application; computes allocation and match | GrantOfficer |
| POST | /housing-network/grant-applications/{id}/decline | Decline an UNDER_REVIEW application | GrantOfficer |
| POST | /housing-network/grant-applications/{id}/withdraw | Withdraw a DRAFT application | MemberAdmin |
| GET | /housing-network/grant-awards | List awards, filterable by `cycle_id`, `member_id`, `application_id`, `award_status` | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| GET | /housing-network/grant-awards/{id} | Get an award | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| POST | /housing-network/grant-awards/{id}/verify-match | Verify additional non-federal match | GrantOfficer |
| POST | /housing-network/grant-awards/{id}/activate | Activate a DISBURSING award once match is met (OCC on award version) | GrantOfficer |
| POST | /housing-network/grant-awards/{id}/suspend | Suspend an ACTIVE award | GrantOfficer |
| POST | /housing-network/grant-awards/{id}/resume | Resume a SUSPENDED award with no open findings | GrantOfficer |
| POST | /housing-network/grant-awards/{id}/reconcile | Reconcile a fully disbursed and reported award | GrantOfficer |
| POST | /housing-network/grant-awards/{id}/close | Close a RECONCILED award | GrantOfficer |
| POST | /housing-network/disbursements | Create a PENDING disbursement tranche against an award | GrantOfficer |
| GET | /housing-network/disbursements | List disbursements, filterable by `award_id`, `disbursement_status` | NetworkDirector, GrantOfficer, Auditor |
| GET | /housing-network/disbursements/{id} | Get a disbursement | NetworkDirector, GrantOfficer, Auditor |
| POST | /housing-network/disbursements/{id}/post | Post a PENDING tranche; ledger-syncs the award's disbursed total | GrantOfficer |
| POST | /housing-network/disbursements/{id}/void | Void a PENDING tranche | GrantOfficer |
| POST | /housing-network/client-files | Open a client file | MemberAdmin |
| GET | /housing-network/client-files | List client files, filterable by `member_id`, `counselor_id`, `file_status`, `program_area` | NetworkDirector, MemberAdmin, ComplianceReviewer |
| GET | /housing-network/client-files/{id} | Get a client file | NetworkDirector, MemberAdmin, ComplianceReviewer |
| POST | /housing-network/client-files/{id}/begin-counseling | Begin counseling; requires a certified counselor in the file's program area | MemberAdmin |
| POST | /housing-network/client-files/{id}/record-outcome | Record outcome and hours | MemberAdmin |
| POST | /housing-network/client-files/{id}/close | Close a file once its reviews pass | MemberAdmin |
| POST | /housing-network/file-reviews | Open a review on a client file | ComplianceReviewer |
| GET | /housing-network/file-reviews | List file reviews, filterable by `client_file_id`, `review_status` | NetworkDirector, ComplianceReviewer, MemberAdmin |
| GET | /housing-network/file-reviews/{id} | Get a file review | NetworkDirector, ComplianceReviewer, MemberAdmin |
| POST | /housing-network/file-reviews/{id}/pass | Pass a review | ComplianceReviewer |
| POST | /housing-network/file-reviews/{id}/fail | Fail a review with deficiency codes | ComplianceReviewer |
| POST | /housing-network/file-reviews/{id}/remediate | Remediate a FAILED review | ComplianceReviewer |
| POST | /housing-network/expenditure-reports | Submit an expenditure report for an award period | MemberAdmin |
| GET | /housing-network/expenditure-reports | List expenditure reports, filterable by `award_id`, `report_status` | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| GET | /housing-network/expenditure-reports/{id} | Get an expenditure report | NetworkDirector, GrantOfficer, MemberAdmin, Auditor |
| POST | /housing-network/expenditure-reports/{id}/accept | Accept a report whose cumulative spend is within disbursed | GrantOfficer |
| POST | /housing-network/expenditure-reports/{id}/flag | Flag a report; spawns an OPEN compliance audit | GrantOfficer |
| GET | /housing-network/compliance-audits | List compliance audits, filterable by `award_id`, `audit_status`, `parent_audit_id` | NetworkDirector, Auditor, GrantOfficer |
| GET | /housing-network/compliance-audits/{id} | Get an audit | NetworkDirector, Auditor, GrantOfficer |
| POST | /housing-network/compliance-audits/{id}/issue-findings | Issue findings with a disallowance | Auditor |
| POST | /housing-network/compliance-audits/{id}/resolve | Resolve findings | Auditor |
| POST | /housing-network/compliance-audits/{id}/escalate | Escalate findings; suspends the award, claws back funds, freezes the member | Auditor |
| POST | /housing-network/compliance-audits/{id}/reopen | Re-open findings as a successor audit | Auditor |
| POST | /housing-network/performance-reviews | Open a performance review for a member and period | NetworkDirector |
| GET | /housing-network/performance-reviews | List performance reviews, filterable by `member_id`, `review_status` | NetworkDirector, MemberAdmin |
| GET | /housing-network/performance-reviews/{id} | Get a performance review | NetworkDirector, MemberAdmin |
| POST | /housing-network/performance-reviews/{id}/score | Score a review; recomputes the households-served rollup | NetworkDirector |
| POST | /housing-network/performance-reviews/{id}/resolve | Resolve a scored review as SATISFACTORY or CORRECTIVE_ACTION | NetworkDirector |
| POST | /housing-network/performance-reviews/{id}/close-plan | Close a corrective plan within its deadline and with zero open findings | NetworkDirector |
| POST | /housing-network/performance-reviews/{id}/escalate | Escalate an overdue corrective plan; member to PROBATION | NetworkDirector |
| GET | /housing-network/reports/congressional | Households-served rollup across non-revoked members by program area for a fiscal year | NetworkDirector, GrantOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_MEMBER_POSTURE_BLOCKED | 422 |
| ERR_MEMBER_NOT_CHARTERED | 422 |
| ERR_COURSE_FULL | 422 |
| ERR_PREREQUISITE_NOT_MET | 422 |
| ERR_WINDOW_CLOSED | 422 |
| ERR_CROSS_ENTITY_MISMATCH | 422 |
| ERR_POOL_EXHAUSTED | 422 |
| ERR_MATCH_NOT_MET | 422 |
| ERR_DUPLICATE | 409 |
| ERR_COMPETITIVE_SCORE_TOO_LOW | 422 |
| ERR_REVIEW_PENDING | 422 |
| ERR_OUTCOME_HOURS_INSUFFICIENT | 422 |
| ERR_CERTIFICATION_REQUIREMENT_UNMET | 422 |
| ERR_AWARD_NOT_RECONCILABLE | 422 |
