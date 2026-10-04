# Service Corps Placement API — Product Requirements Document

## 1. Introduction

Running a full-time service corps across a city's schools is an exercise in controlled commitment. Each operating site recruits a cohort of young adults, places them as teams into partner schools under signed district agreements, pays them a modest living stipend out of a blended funding pool, and — at the end of a verified term of service — certifies an education award governed by national service program rules. Every one of those commitments is auditable: hours must be verified within a fixed window, stipend disbursements must respect segregation of duties and site-level fiscal headroom, and a district's cost share must reconcile to the cent across installment schedules.

This document specifies the Service Corps Placement API, the system of record for that operation. It covers corps member recruitment with age, education, and service-eligibility screening; school partnership agreements with an independent data-sharing dimension; team formation, deployment, mid-year attrition, and bounded backfill; student focus lists with cyclic caseload assignment and attendance tracking; service hour logging and verification; stipend scheduling, approval, payment, forfeiture, and clawback; education award projection and certification; and evaluation reporting back to districts. All resources are mounted under the `/corps` URL prefix. The requirements below are written for the engineer implementing the service: §2 states the system-wide contracts, §3 walks the business workflows, §4 summarizes the endpoint surface, and §5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every endpoint and every resource in the API, regardless of the workflow that invokes them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Each endpoint admits a specific list of roles (enumerated in §4); a caller whose role is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes six roles: `SiteDirector`, `ProgramManager`, `StipendAdministrator`, `SchoolLiaison`, `CorpsMember`, and `Applicant`. A `SiteDirector` is the site executive, owning site configuration, funding receipts, school agreements, team lifecycle, and the logical clock. A `ProgramManager` runs recruitment, placement, coaching, and hour verification. A `StipendAdministrator` administers living stipends and education awards; deliberate segregation of duties keeps this role away from hour verification and keeps a `ProgramManager` away from stipend approval. A `SchoolLiaison` is the district-side signatory for one school. A `CorpsMember` is an enrolled member logging service hours. An `Applicant` is a prospective member submitting an application and answering an offer.

Two roles are entity-backed. When `X-User-Role` is `SchoolLiaison`, `X-User-ID` is the `id` of the acting School; ownership checks on any school-scoped write compare the target school's `id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_ENTITY_OWNER` (HTTP 403). When `X-User-Role` is `CorpsMember`, `X-User-ID` is the `id` of the acting CorpsMember; the member may act on and read only the member record whose `id` equals `X-User-ID`, with violations again rejected as `ERR_NOT_ENTITY_OWNER`. The remaining four roles — `SiteDirector`, `ProgramManager`, `StipendAdministrator`, and `Applicant` — treat `X-User-ID` as an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by` on a stipend payment or `reviewed_by` on an hour entry) but never compares it to any entity's `id`.

Segregation of duties is enforced beyond coarse role membership: the operator who approves a stipend payment must be a different individual than the one who created it, and any attempt to self-approve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Several list endpoints additionally accept domain filters — for example `agreement_status` on the schools-of-a-site listing, `service_status` and `stipend_status` on the members listing, `status` on assignments, hour entries, stipend payments, and evaluation reports, `focus_list_type` and `caseload_status` on student listings, and `category` and `service_date` on hour entries — each of which narrows the result set to exact matches on the named field.

### 2.4. The Logical Clock

All temporal reasoning in the system — service-date windows, verification windows, backfill deadlines, report submission windows, service-year completion checks, and the forward-looking award projection — is evaluated against a server-side logical clock, never against wall-clock time. Before any client sets it, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. Comparisons use the clock's date part.

A `SiteDirector`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, and the response echoes the new reading as `current_utc`. Clock-dependent projections (each member's `projected_hours_total` and `award_projected_cents`) are not rewritten eagerly; they are recomputed lazily on the next read of the affected resource.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation — including mutations that arrive via cascaded side effects from another resource's transition. `version` is an integer that starts at 1 and increments by 1 on every mutation, again including cascaded ones; it is the basis for optimistic concurrency control.

One resource deviates from this convention: a ServiceHourEntry carries only `id` and `created_at`. Both `updated_at` and `version` are absent from hour entries.

### 2.6. Money, Hours, and Rounding

All monetary values are represented as integer cents — never fractional currency units. Wherever a division or proration produces a fractional cent, the result is rounded half up to the nearest whole cent. Hour quantities are decimal numbers carried to two decimal places; hour entries are additionally quantized, as §3.6 describes. The one percentage the system computes, `pct_improved` on an evaluation report, is rounded half up to one decimal place.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency on a parent resource's `version`, and each requires a dedicated request field carrying the client's last-observed version of that parent:

- Amending a school's agreement requires `expected_school_version` matching the school's current `version`. If another writer has advanced the school's version since the client last read it — by amending it or by driving an agreement transition — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the agreement terms is stale.
- Exiting a corps member requires `expected_member_version` matching the member's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the award certification would otherwise be computed against verified-hour and placement data the client has not observed.
- Creating a team assignment requires `expected_team_version` matching the team's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because roster capacity and backfill accounting must be evaluated against the current roster, not a superseded one.

No other endpoint takes a version field. The OCC check is framed purely as staleness detection: the field is compared to the parent's current version at the moment the write is evaluated, independently of how the versions came to differ.

### 2.8. Validation Order and Nested Path Resolution

When a single request violates several rules, the response carries the error of the lowest-numbered matching priority — the checks are not unordered, and the reported error is deterministic. The evaluation order runs from the outside in. Authentication comes first: header presence and well-formedness (`ERR_UNAUTHENTICATED`), then role admission (`ERR_UNAUTHORIZED_ROLE`), then entity-backed ownership (`ERR_NOT_ENTITY_OWNER`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Next, the request body is checked for shape: required fields present, enums in range, dates well-formed, hours a positive multiple of 0.25 not exceeding 12, monetary values non-negative integer cents, and any `period_end` on or after its `period_start` — violations surface as `ERR_INVALID_REQUEST`. Only then does the system resolve path identifiers: for any endpoint whose URL nests one resource under another, identifiers are validated left-to-right, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not exist, before any later identifier or business rule is examined.

After existence, state-level checks run: the OCC staleness comparison (`ERR_STALE_VERSION`) precedes the question of whether the target resource's current state permits the requested transition (`ERR_INVALID_STATE`). Business rules follow, layered as temporal windows first (service-date validity, the 30-day verification window, the backfill deadline, the 45-day report window), then referential gates (agreement active, data sharing signed, member active, member placed, award earned), then constraint checks (daily hour cap, fundraising cap, caseload size, caseload conflict, assignment overlap, team capacity, backfill budget, deploy staffing, duplicate payment period, completion hours), and finally the fiscal gate on stipend payment (`ERR_SITE_FUNDING_DEFICIT`). §3 states the concrete ordering wherever one endpoint is guarded by several of these rules.

### 2.9. Hierarchical Consistency and Cascades

State changes on a parent resource propagate to the resources it owns, without requiring an explicit client call on each child. Terminating a school's agreement dissolves its teams; dissolving a team ends its assignments; ending a member's last assignment can suspend that member's stipend and forfeit scheduled payments; exiting a member releases caseloads and re-evaluates team staffing. Each resource mutated along such a cascade is an independent mutation: its `updated_at` refreshes and its `version` increments. Automatic transitions of this kind follow the same state machines as manual ones — a team that drops below minimum staffing moves to `UNDERSTAFFED` whether the triggering assignment ended by manual action, by member exit, or by school termination.

## 3. Business Logic & Workflows

### 3.1. Sites and the Funding Ledger

A `SiteDirector` opens an operating site by supplying a `name`, the `city` it serves, the service-year bookends `service_year_start` and `service_year_end` — the end must fall after the start — and the per-member `annual_stipend_cents`, which must be greater than zero. Three optional funding commitments may be recorded at creation: `district_committed_cents`, `philanthropy_committed_cents`, and `federal_committed_cents`, each defaulting to 0 and never negative. A new site begins in `SETUP` status with all of its received-funding counters at zero.

Every site maintains a computed funding ledger. The channels `district_received_cents`, `philanthropy_received_cents`, and `federal_received_cents` each start at 0 and advance only when funding is received. Their sum is exposed as `total_received_cents`. Against those receipts stand two debit views: `stipend_outlay_cents`, the net stipend cash actually out the door — the sum of `net_amount_cents` over the site's payments in `PAID` minus the sum over payments in `CLAWED_BACK` — and `projected_obligations_cents`, the forward commitment computed as `annual_stipend_cents` multiplied by the number of the site's corps members whose `stipend_status` is `ACTIVE`. Subtracting outlay and projected obligations from total receipts yields `funding_headroom_cents`, and the headroom drives `funding_posture`: `DEFICIT` when headroom is negative, `TIGHT` when headroom is zero or positive but below 500000 cents (a $5,000 buffer), and `FUNDED` otherwise. A freshly created site has zero receipts, zero outlay, and zero obligations, so its headroom is 0 and its posture reads `TIGHT`.

Recording a funding receipt is a `SiteDirector` action carrying a `funding_type` — selecting the district, philanthropy, or federal channel — and an `amount_cents`. The matching received counter is increased by the amount, `total_received_cents`, `funding_headroom_cents`, and `funding_posture` are recomputed, and the site's `version` increments.

A site moves from `SETUP` to `ACTIVE` on a `SiteDirector`'s state call with `to_status` of `ACTIVE`; recruitment enrollment, team formation, and most operational writes require the site to be `ACTIVE`. Closing a site — `ACTIVE` to `CLOSED`, which is terminal — is permitted only when nothing is still running: no corps member of the site may have `service_status` of `ENROLLED`, `ACTIVE`, or `SUSPENDED`, and no team at any of the site's schools may be `FORMING`, `DEPLOYED`, or `UNDERSTAFFED`. Either violation is rejected with `ERR_INVALID_STATE`.

The site also carries the district cost-share rollup — `cost_share_installment_1_cents`, `cost_share_installment_2_cents`, and `cost_share_total_cents` — all three initialized to zero at site creation and recomputed as schools qualify; §3.2 defines the schedule, since its inputs are the site's schools.

### 3.2. School Partnerships, Cost Share, and Data Sharing

Partnership with a school begins when a `SiteDirector` creates the school record under a site, providing the school's `name`, the counterparty `district_name`, the contracted `team_size` (at least 3), the `service_scope` — a non-empty subset of `ATTENDANCE_SUPPORT`, `LITERACY_TUTORING`, `MATH_TUTORING`, and `WHOLE_SCHOOL_EVENTS` — and the `annual_cost_share_cents` the district contributes (zero or more). A school is governed by two independent state dimensions, both starting at `DRAFT`: `agreement_status` for the partnership agreement itself, and `data_sharing_status` for the student outcome data-sharing agreement with the district. While the agreement is `DRAFT` the school contributes nothing to the site's cost-share totals.

Signing is the district's act. A `SchoolLiaison` whose `X-User-ID` equals the school's `id` moves the agreement from `DRAFT` to `SIGNED`; any other liaison identity is rejected with `ERR_NOT_ENTITY_OWNER`. Activation — `SIGNED` to `ACTIVE` — is a `SiteDirector` action with two preconditions: the school's `data_sharing_status` must be `SIGNED` (else `ERR_DATA_SHARING_NOT_SIGNED`), and the site must be `ACTIVE` (else `ERR_INVALID_STATE`). On activation the school enters the cost-share input set and the site's three cost-share fields are recomputed.

The cost-share schedule is computed per school and then aggregated. For each school of the site whose agreement is `SIGNED`, `ACTIVE`, `AMENDMENT_REVIEW`, or `COMPLETED` — `DRAFT` and `TERMINATED` schools are excluded — the first installment is half of that school's `annual_cost_share_cents`, rounded half up to a whole cent, and the second installment is the remainder of the annual amount after subtracting that school's first installment. Rounding is pinned to happen per school before any summation; rounding the summed amount instead would produce different cents and is forbidden. The site's `cost_share_installment_1_cents` is the sum of the per-school first installments, `cost_share_installment_2_cents` the sum of the second installments, and `cost_share_total_cents` the sum of the two site-level installment totals. The rollup is recomputed whenever a school is created, whenever an agreement enters or leaves the qualifying set (signing, activation, amendment review, completion, termination), and whenever an amendment changes `annual_cost_share_cents`.

Amendments to an `ACTIVE` agreement are `SiteDirector` actions guarded by optimistic concurrency: the request must carry `expected_school_version` equal to the school's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The amendment may revise `team_size`, `annual_cost_share_cents`, or `service_scope`; the revised values take effect immediately, the school's `version` increments by 1, the agreement moves to `AMENDMENT_REVIEW`, and the cost-share rollup is recomputed with the amended amount. Confirmation — returning the agreement from `AMENDMENT_REVIEW` to `ACTIVE` — belongs to the school's own `SchoolLiaison` (ownership-checked as at signing, and requiring `data_sharing_status` still `SIGNED`, else `ERR_DATA_SHARING_NOT_SIGNED`). Note that the team snapshot rule in §3.4 means amended `team_size` never rewrites existing teams.

Suspension severs operations without ending the partnership. A `SiteDirector` may move an `ACTIVE` agreement to `SUSPENDED`, and the same transition happens automatically whenever the school's data sharing lapses to `EXPIRED` — including from `AMENDMENT_REVIEW`, which likewise falls to `SUSPENDED` on expiry. While an agreement is `SUSPENDED`, team creation and deployment at that school and evaluation report submission are blocked until the agreement is resumed. Resumption — `SUSPENDED` back to `ACTIVE` — is a `SiteDirector` action requiring data sharing to be `SIGNED` again; re-signing data sharing on its own deliberately does not resume the agreement.

The data-sharing dimension has its own small machine. The `SchoolLiaison` of the school signs it (`DRAFT` to `SIGNED`, ownership-checked), and either the liaison or a `SiteDirector` may let it expire (`SIGNED` to `EXPIRED`), which triggers the conditional auto-suspension of the agreement described above. An expired agreement can be re-signed by the liaison (`EXPIRED` to `SIGNED`); the agreement status stays `SUSPENDED` and a `SiteDirector` must resume it explicitly. Both dimensions are driven through the same school state capability: an optional `dimension` selector chooses `AGREEMENT` (the default) or `DATA_SHARING`, and `to_status` names the target state.

Completion and termination end the agreement. A `SiteDirector` may move `ACTIVE` to `COMPLETED` once the logical clock's date has reached or passed the site's `service_year_end` (earlier attempts are `ERR_INVALID_STATE`); any teams at the school still `DEPLOYED` or `UNDERSTAFFED` automatically transition to `COMPLETED`, their `ACTIVE` assignments ending with `end_date` set to the clock date, and the school remains in the cost-share input set. Termination — `ACTIVE` or `SUSPENDED` to `TERMINATED`, by a `SiteDirector` — is the heavy cascade, and it runs in three linked steps. Link 1: every team of the school in `FORMING`, `DEPLOYED`, or `UNDERSTAFFED` moves to `DISSOLVED`. Link 2: each dissolved team's `ACTIVE` assignments end, with `end_date` set to the clock date. Link 3: for each member whose last `ACTIVE` assignment ends in this cascade — the member's `active_assignment_count` reaching zero — and whose `service_status` is `ACTIVE`, the member's `stipend_status` moves from `ACTIVE` to `SUSPENDED` and that member's stipend payments in `SCHEDULED` are forfeited with `decision_reason` recorded as `TEAM_DISSOLVED`. In the same act, every student of the school with `enrollment_status` `ACTIVE` moves to `EXITED`, and any of them still `ASSIGNED` to a caseload are released: `caseload_status` returns to `UNASSIGNED`, `assigned_end_date` is set to the clock date, and `assigned_member_id` is cleared to null. Finally, because a terminated school leaves the cost-share input set, the site's cost-share totals are recomputed.

### 3.3. Recruitment, Eligibility, and Enrollment

An `Applicant` enters the pipeline by submitting an application naming the target `site_id`, a `full_name`, a `date_of_birth`, an `education_level`, a `citizenship_status`, a count of `prior_service_terms`, and a count of `prior_full_awards_received`. Hard eligibility is enforced at creation, before the application ever exists, and the three checks run in a fixed order. Age is evaluated first: the applicant's age at the site's `service_year_start` must be at least 17 and at most 25 — computed from `date_of_birth`, with a birthday falling exactly on `service_year_start` counting as having reached that age — otherwise the submission is rejected with `ERR_AGE_INELIGIBLE`. Education comes second: an `education_level` of `LESS_THAN_HS` is ineligible and rejected with `ERR_EDUCATION_INELIGIBLE`, while `HS_DIPLOMA`, `GED`, `SOME_COLLEGE`, `ASSOCIATES`, and `BACHELORS_PLUS` are eligible. Service history comes third: a `citizenship_status` of `OTHER` is ineligible (`US_CITIZEN`, `US_NATIONAL`, and `PERMANENT_RESIDENT` are eligible), `prior_service_terms` must be fewer than 4, and `prior_full_awards_received` must be fewer than 2; any failure is rejected with `ERR_SERVICE_INELIGIBLE`. A submission passing all three lands in `SUBMITTED` status, with `rejection_reason` null — it is only ever set when the application lands in `REJECTED`, `WITHDRAWN`, or `DECLINED`.

Screening is a soft evaluation, deliberately distinct from the hard gates. When a `ProgramManager` advances an application with `to_status` of `SCREEN`, the call always succeeds: it lands the application in `SCREENED_ELIGIBLE`, unless the request carries `rejection_reason` of `BACKGROUND_CHECK_FAILED`, in which case it lands in `REJECTED` with that reason recorded on the entity. Because hard eligibility failures are rejected at creation, `BACKGROUND_CHECK_FAILED` is the only screening outcome that produces a rejection here.

From `SCREENED_ELIGIBLE`, a `ProgramManager` moves the candidate to `INTERVIEWED`, and from `INTERVIEWED` either to `OFFERED` or — again recording `BACKGROUND_CHECK_FAILED` — to `REJECTED`. The offer is the applicant's to answer: an `Applicant` accepts (`OFFERED` to `ACCEPTED`) or declines (`OFFERED` to `DECLINED`, with `rejection_reason` set to `OFFER_DECLINED`). Withdrawal is available from every pre-terminal, pre-enrollment state — `SUBMITTED`, `SCREENED_ELIGIBLE`, `INTERVIEWED`, `OFFERED`, and `ACCEPTED` alike — to `WITHDRAWN`, performed by the `Applicant` or a `ProgramManager`, and always records `rejection_reason` of `APPLICANT_WITHDREW`.

Enrollment is the pipeline's one constructive transition. A `ProgramManager` moves an `ACCEPTED` application to `ENROLLED`, permitted only while the site is `ACTIVE` (else `ERR_INVALID_STATE`). At that moment the system creates the CorpsMember: `site_id` and `full_name` are copied from the application, `service_status` begins at `ENROLLED`, `stipend_status` at `NOT_STARTED`, `award_status` at `NOT_EARNED`, and every computed counter starts at zero. The application's `enrolled_member_id`, null until this moment, is set to the new member's `id`, closing the loop between the two records. `ENROLLED`, `REJECTED`, `WITHDRAWN`, and `DECLINED` are the application's terminal states.

### 3.4. Team Formation, Placement, and Backfill

A `SiteDirector` forms a team at a school by providing the `school_id`, a `name`, and a `backfill_deadline`, with an optional `backfill_limit` that defaults to 2 and may not be negative. Creation requires the site to be `ACTIVE` and the school's agreement to be `ACTIVE` — otherwise `ERR_AGREEMENT_NOT_ACTIVE`. At creation the team freezes the school's contracted size into `team_size_snapshot`; later agreement amendments to `team_size` never retro-update existing teams. The minimum staffing floor `min_active_members` is derived as `team_size_snapshot` minus 2. The team's `status` begins at `FORMING`, and both roster counters — `active_assignment_count` and `backfill_count` — start at 0.

Placing a member onto a team is a `ProgramManager` action carrying `corps_member_id`, a `start_date`, the OCC token `expected_team_version`, and an optional `role` that defaults to `CORPS_MEMBER` and may be `TEAM_LEADER`. The new assignment's `team_id` is taken from the team addressed by the request rather than from the payload. The assignment occupies the half-open interval from `start_date` up to but not including `end_date`; while open-ended, `end_date` is null. The guards run in priority order. First the OCC comparison: a stale `expected_team_version` is rejected with `ERR_STALE_VERSION`. Then state legality. Then, for a backfill creation, the backfill window: the logical clock date must be on or before the team's `backfill_deadline`, else `ERR_BACKFILL_WINDOW_CLOSED`. The placed member must have `service_status` of `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`). The member's own assignment intervals must be pairwise non-overlapping: an existing assignment whose `end_date` equals the new `start_date` does not overlap (the intervals are half-open), while an open-ended existing assignment overlaps any later start — violations are `ERR_ASSIGNMENT_OVERLAP`. Team capacity is enforced per calendar date: for every date the new assignment would cover, the count of the team's assignments covering that date must stay at or below `team_size_snapshot`, else `ERR_TEAM_CAPACITY_EXCEEDED`. Finally the backfill budget: any assignment created while the team is `DEPLOYED` or `UNDERSTAFFED` is a backfill (`is_backfill` is set true), and it is allowed only while the team's `backfill_count` is still below its `backfill_limit` — a team that has exhausted its budget rejects the placement with `ERR_BACKFILL_LIMIT_REACHED`. A successful creation raises the team's `active_assignment_count` by 1, raises `backfill_count` by 1 when the assignment is a backfill, increments the team's `version`, and — when the team was `UNDERSTAFFED` and the addition restores the roster to at least `min_active_members` — automatically returns the team to `DEPLOYED`.

Deployment is the `SiteDirector`'s gate from `FORMING` to `DEPLOYED`: the roster must already meet the floor, `active_assignment_count` at least `min_active_members`, else `ERR_TEAM_STAFFING_BELOW_MINIMUM`, and the school agreement must be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`.

Assignments can end early. A `ProgramManager` ends an `ACTIVE` assignment, optionally supplying an `end_date`; when omitted, the logical clock date is used, and a supplied date earlier than the assignment's `start_date` is rejected as `ERR_INVALID_REQUEST`. The assignment's `status` becomes `ENDED`, the team's `active_assignment_count` drops by 1 and its `version` increments, the member's `active_assignment_count` is recomputed, and a `DEPLOYED` team whose roster falls below `min_active_members` automatically slides to `UNDERSTAFFED`. The `DEPLOYED` ↔ `UNDERSTAFFED` pair is cyclic: recovery through backfill returns the team to `DEPLOYED` just as attrition pushed it out.

Completion and dissolution close teams out. A `SiteDirector` may move a `DEPLOYED` or `UNDERSTAFFED` team to `COMPLETED` once the clock date has reached the site's `service_year_end` (earlier, `ERR_INVALID_STATE`); the same transition fires automatically when the school's agreement completes. Either way, the team's `ACTIVE` assignments end with `end_date` set to the clock date. Dissolution — from `FORMING`, `DEPLOYED`, or `UNDERSTAFFED` to `DISSOLVED` — is available to a `SiteDirector` directly and fires automatically under the school-termination cascade of §3.2; in all cases the team's `ACTIVE` assignments end at the clock date, and each ended assignment triggers the link-3 member cascade described there: stipend suspension for a member left with no active assignments, and forfeiture of that member's `SCHEDULED` payments with `decision_reason` of `TEAM_DISSOLVED`. `COMPLETED` and `DISSOLVED` are terminal.

### 3.5. Student Focus Lists and Caseloads

Within a school whose agreement is `ACTIVE`, a `ProgramManager` enrolls students onto a focus list by supplying the `school_id`, the district-issued `external_student_ref` (an opaque reference), the `grade_level` (an integer from 0 through 12), the `focus_list_type` — one of `ATTENDANCE`, `LITERACY`, or `MATH` — and the `baseline_attendance_pct`, a percentage between 0 and 100 carried to one decimal. Attempts under a non-active agreement are rejected with `ERR_AGREEMENT_NOT_ACTIVE`. A new student is `ACTIVE` in enrollment and `UNASSIGNED` on caseload, with `assigned_member_id` null and `current_attendance_pct` null until the first metrics posting.

Caseload assignment binds a student to the member who will work with them. A `ProgramManager` drives it with an `action` of `ASSIGN` and a `corps_member_id`; the checks run in order. The student must be `ACTIVE` in enrollment (else `ERR_INVALID_STATE`). The target member must have `service_status` of `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`). The member must be placed at the student's school — holding an `ACTIVE` team assignment whose team's school is the student's school and whose team is `DEPLOYED` or `UNDERSTAFFED` — else `ERR_MEMBER_NOT_PLACED`. The member's caseload must have room: `active_caseload_count` below 12, meaning the twelfth assignment succeeds and the thirteenth is rejected with `ERR_CASELOAD_FULL`. And the student must not already be `ASSIGNED`, else `ERR_STUDENT_CASELOAD_CONFLICT` — note that the capacity check precedes the already-assigned check when both would fail. A successful assignment records `assigned_member_id` as the given member, stamps `assigned_start_date` with the clock date, clears `assigned_end_date` to null, and increments the member's `active_caseload_count` by 1.

Release is the reverse. An `action` of `UNASSIGN` — which takes no member — sets `assigned_end_date` to the clock date, clears `assigned_member_id`, and decrements the member's `active_caseload_count`. The caseload machine is cyclic: re-assigning a student after an unassign is allowed, and the new `assigned_start_date` simply begins a fresh interval on top of the closed one.

Attendance tracking is deliberately lightweight: a `ProgramManager` posts the student's latest `current_attendance_pct` through the metrics capability, updating the field and bumping the student's `version`.

When a student leaves the program — a `ProgramManager` moving enrollment from `ACTIVE` to `EXITED`, or the automatic exit under school termination — a student still `ASSIGNED` is released in the same act: `caseload_status` becomes `UNASSIGNED`, `assigned_end_date` takes the clock date, `assigned_member_id` clears, and the member's caseload count is recomputed. `EXITED` is terminal.

### 3.6. Service Hours: Logging, Verification, and the Fundraising Cap

Corps members log their own service. A `CorpsMember` creates an hour entry with `corps_member_id` — which must equal the caller's `X-User-ID`, else `ERR_NOT_ENTITY_OWNER` — a `service_date`, the `hours` served, a `category` of `DIRECT_SERVICE`, `TRAINING`, or `FUNDRAISING`, and an optional free-text `description` that defaults to empty. Logging requires the member to be actively serving: the member's `service_status` must be `ACTIVE`, else the creation is rejected with `ERR_MEMBER_NOT_ACTIVE`. The hours must be positive, no more than 12, and an exact multiple of 0.25; the date must fall on or after the site's `service_year_start` and on or before the logical clock date — a date outside that window is rejected with `ERR_SERVICE_DATE_INVALID`. A created entry is `PENDING`, with `reviewed_by` and `review_reason` both null until a review lands. As noted in §2.5, hour entries are the system's one append-and-review record: they carry `id` and `created_at` but no `updated_at` and no `version`.

Review belongs to the `ProgramManager`, who supplies a `decision` of `VERIFY`, `REJECT`, or `VOID`, with an optional `reason`. Verification — `PENDING` to `VERIFIED` — is gated by three checks evaluated in this order. The verification window: the gap between the clock date and the entry's `service_date` must not exceed 30 days, else `ERR_VERIFICATION_WINDOW_EXPIRED`. The daily cap: summing the member's entries on the same `service_date` across both `PENDING` and `VERIFIED`, the candidate included, must not exceed 12.0 hours, else `ERR_DAILY_HOUR_CAP_EXCEEDED`. And for a `FUNDRAISING` entry, the fundraising cap described below, else `ERR_FUNDRAISING_CAP_EXCEEDED`. A successful verification stamps `reviewed_by` with the reviewer's `X-User-ID` and recomputes the member's hour totals.

The fundraising cap pins down a circular-looking dependency by fixing the evaluation order. First, form the member's post-verification total: the current `verified_hours_total` plus the candidate entry's hours. Second, compute the cap as ten percent of that post-verification total, floored down to the nearest quarter hour. Third, accept the entry only if `verified_fundraising_hours` plus the candidate's hours stays at or under that cap. Computing the cap against the pre-verification total instead would yield a strictly smaller cap and wrongly reject entries this order accepts.

Rejection — `PENDING` to `REJECTED` — requires a `reason` (else `ERR_INVALID_REQUEST`), which is recorded as `review_reason` alongside `reviewed_by`. Voiding — `VERIFIED` to `VOIDED` — is the compensating action for an entry verified in error: it likewise requires a `reason`, records `review_reason`, and recomputes the member's totals downward. `REJECTED` and `VOIDED` are terminal. Verify and void both increment the member's `version`.

The member's hour ledger is a pure aggregation over entry states: `verified_hours_total` sums `hours` across the member's `VERIFIED` entries, and `verified_fundraising_hours` sums only those `VERIFIED` entries in the `FUNDRAISING` category, with `PENDING`, `REJECTED`, and `VOIDED` entries excluded from both. The ledger is self-reconciling — verifying an entry and later voiding it returns both totals to exactly their prior values.

### 3.7. Stipends, Awards, and the Member Lifecycle

A member's three dimensions evolve semi-independently, and the service dimension is steered by a `ProgramManager` through the member state capability with `dimension` of `SERVICE` (the default) and a `to_status`. Activation — `ENROLLED` to `ACTIVE` — requires the site to be `ACTIVE` (else `ERR_INVALID_STATE`) and cascades inside the member record: `stipend_status` moves from `NOT_STARTED` to `ACTIVE`, and the site's `projected_obligations_cents` and `funding_posture` are recomputed. Suspension — `ACTIVE` to `SUSPENDED` — moves the stipend dimension from `ACTIVE` to `SUSPENDED` only when it is currently `ACTIVE`, again recomputing site obligations and posture. Return from suspension — `SUSPENDED` back to `ACTIVE` — unconditionally moves `stipend_status` from `SUSPENDED` to `ACTIVE` and recomputes the same site fields.

The stipend dimension itself is a `StipendAdministrator` responsibility (`dimension` of `STIPEND`): a manual hold moves `ACTIVE` to `SUSPENDED`, and a resume moves `SUSPENDED` to `ACTIVE` — but the resume carries a cross-dimension guard, permitted only while the member's `service_status` is `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`. Both moves recompute the site's projected obligations and funding posture, since obligations count only members whose stipend is `ACTIVE`.

Payroll begins when a `StipendAdministrator` schedules a stipend payment for a member, supplying a `period_start` and a `period_end` on or after it. Scheduling requires the member's `stipend_status` to be `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`), and the `period_start` must be unique across that member's payments — a second payment opening on the same day is rejected with `ERR_DUPLICATE_PAYMENT_PERIOD`. At scheduling the system records `created_by` from the caller's `X-User-ID`, computes `period_days` as the count of calendar days from `period_start` through `period_end` inclusive, and sets the provisional amount: `base_amount_cents` is the site's `annual_stipend_cents` divided across the 26 stipend periods of a service year, rounded half up to a whole cent. The provisional base deliberately ignores the period's actual length — it assumes a standard 14-day period — and `final_gross_cents` and `net_amount_cents` remain null. The payment sits in `SCHEDULED`.

Approval — `SCHEDULED` to `APPROVED`, by a `StipendAdministrator` — enforces segregation of duties before anything else: the approver's `X-User-ID` must differ from the payment's `created_by`, else `ERR_SEGREGATION_OF_DUTIES`. The member's `stipend_status` must still be `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`). At approval the final variant is computed: `final_gross_cents` prorates the provisional base by the period's actual length — `base_amount_cents` multiplied by `period_days`, divided by the 14 days of a standard period, rounded half up — and `net_amount_cents` is that gross minus the `deduction_cents` supplied at approval (a non-negative amount defaulting to 0), floored at zero so a payment never nets negative. For a non-14-day period or a nonzero deduction, these final values differ from the provisional base computed on identical period data. The approver's identity lands in `approved_by`.

Disbursement — `APPROVED` to `PAID` — passes through the fiscal gate: the site's `funding_headroom_cents` must cover the payment's `net_amount_cents`, else the payment is rejected with `ERR_SITE_FUNDING_DEFICIT`. On payment, the site's `stipend_outlay_cents` rises by the net amount, the member's `net_stipend_received_cents` rises by the same amount, and the site's headroom and posture are recomputed. Clawback — `PAID` to `CLAWED_BACK`, with a `reason` required (else `ERR_INVALID_REQUEST`) — is the exact compensating action: outlay and the member's net received each fall by the payment's net amount, headroom and posture recompute, and the reason is preserved in `decision_reason`. Cash is conserved across pay and clawback: the pair returns both ledgers to their prior values.

Forfeiture — `SCHEDULED` or `APPROVED` to `FORFEITED` — may be manual, with a `reason` required, or automatic under the member-exit and team-dissolution cascades; the reason is recorded in `decision_reason` (`MEMBER_EXITED` or `TEAM_DISSOLVED` for the cascades). `FORFEITED` and `CLAWED_BACK` are terminal.

While a member serves, the education award is projected forward-looking. The projection counts the calendar days from the day after the logical clock date through the site's `service_year_end` inclusive — zero once the clock has reached the year's end — and assumes 8.0 hours of service on each of those remaining days. Adding that allowance to `verified_hours_total` yields `projected_hours_total`, and the projected award `award_projected_cents` follows: the full 739500 cents when the projection reaches at least 120 hours; a pro-rata share — 739500 cents multiplied by the projected hours, divided by 120, rounded half up — when the projection reaches at least 24 hours but fewer than 120; and zero below 24. The projection is recomputed whenever verified hours change or the clock advances, observed on the next read of the member.

Certification happens once, at exit, and looks only backward. Until exit, the member's `exit_type`, `exit_date`, and `award_amount_cents` are all null; exit fixes them. A `ProgramManager` exits a member by supplying `expected_member_version` (the OCC guard of §2.7; a stale value is `ERR_STALE_VERSION`), an `exit_type`, and an optional `exit_date` defaulting to the clock date. Exit is available from `ACTIVE`, `SUSPENDED`, or `ENROLLED`. When `exit_type` is `COMPLETED_TERM`, the member must have reached at least 120 verified hours — `PENDING`, `REJECTED`, and `VOIDED` entries never count — else the exit is rejected with `ERR_COMPLETION_HOURS_NOT_MET`; a qualifying completion certifies `award_status` of `EARNED_FULL` with `award_amount_cents` of 739500, and the member's service ends in `COMPLETED`. Early exits (`COMPELLING_CIRCUMSTANCE`, `FOR_CAUSE`, or `NON_COMPELLING`) land the member in `EXITED_EARLY`: a compelling circumstance with at least 24 verified hours earns a partial award — `EARNED_PARTIAL` with `award_amount_cents` set to 739500 cents multiplied by the verified hours, divided by 120, rounded half up — while a compelling exit below 24 hours, or any for-cause or non-compelling exit, forfeits the award (`FORFEITED`, amount 0). Exiting directly from `ENROLLED` always forfeits, with `award_amount_cents` of 0. Because certification counts only entries verified by exit time, the same member can project a full award mid-year yet certify a smaller pro-rata amount — the projection's assumed future hours are excluded at certification.

Every exit also runs the exit cascade. The member's `version` increments and `exit_date` is recorded. Link 1: the member's `ACTIVE` team assignments end, with `end_date` set to the exit date. Link 2: each affected team recomputes its `active_assignment_count`, and a `DEPLOYED` team that drops below `min_active_members` automatically moves to `UNDERSTAFFED`. Students on the member's caseload are released: those `ASSIGNED` with `assigned_member_id` pointing at the member become `UNASSIGNED`, with `assigned_end_date` set to the exit date and `assigned_member_id` cleared, and the member's `active_caseload_count` is recomputed. The member's payments in `SCHEDULED` or `APPROVED` are forfeited with `decision_reason` of `MEMBER_EXITED`, and `stipend_status` moves to `ENDED`, its terminal state. `COMPLETED` and `EXITED_EARLY` are terminal for the service dimension.

Finally, an earned award can be disbursed: a `StipendAdministrator` drives the award dimension (`dimension` of `AWARD`) from `EARNED_FULL` or `EARNED_PARTIAL` to `DISBURSED`. Attempting disbursement while the award is in any other state is rejected with `ERR_AWARD_NOT_EARNED`; `DISBURSED` (like `FORFEITED`) is terminal.

### 3.8. Evaluation Reporting to Districts

Accountability closes the loop with the district. A `ProgramManager` drafts an evaluation report for a school by supplying the `school_id` and a reporting window `period_start` through `period_end` (the end on or after the start). Drafting requires the school's agreement to be `ACTIVE` or `COMPLETED` — any other agreement state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The report's metrics are snapshotted at creation, while the report is still `DRAFT`.

The snapshot counts students, not effort. `eligible_student_count` covers students of the school whose `enrollment_status` is `ACTIVE` or `EXITED` and whose caseload interval overlaps the reporting window: `assigned_start_date` set and on or before `period_end`, with `assigned_end_date` either null (still assigned) or on or after `period_start`. Students never assigned within the window are excluded. Among the eligible, `improved_student_count` counts those with a `current_attendance_pct` on record whose improvement over `baseline_attendance_pct` is at least 5.0 percentage points. The headline metric `pct_improved` is one hundred times the improved count divided by the eligible count, rounded half up to one decimal place — and defined as 0.0 when no students are eligible.

Submission — `DRAFT` or `RETURNED` to `SUBMITTED`, by a `ProgramManager` — is gated twice: the school's `data_sharing_status` must be `SIGNED` (else `ERR_DATA_SHARING_NOT_SIGNED`), and the clock date must be no more than 45 days past `period_end` (else `ERR_REPORT_WINDOW_CLOSED`). Resubmission from `RETURNED` runs the same gates and clears the prior `return_reason` to null. Review belongs to the district: a `SchoolLiaison` whose `X-User-ID` equals the report's school `id` (else `ERR_NOT_ENTITY_OWNER`) accepts the report — `SUBMITTED` to `ACCEPTED`, which is terminal — or returns it, `SUBMITTED` to `RETURNED`, with a `return_reason` required (else `ERR_INVALID_REQUEST`) and recorded for the revision loop.

## 4. Endpoint Definitions

Operations that create a new resource — a site, school, application, team, assignment, student, hour entry, stipend payment, or evaluation report — return `201 Created`. Operations that modify an existing resource, drive a state transition, record a funding receipt, post metrics, or set the clock return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/corps/_clock/set_current_utc` | Set the server's logical UTC instant | SiteDirector |
| POST | `/corps/sites` | Create a Site in SETUP | SiteDirector |
| GET | `/corps/sites/{id}` | Get a Site with computed funding and cost-share fields | SiteDirector, ProgramManager, StipendAdministrator |
| POST | `/corps/sites/{id}/state` | Transition Site status (ACTIVE, CLOSED) | SiteDirector |
| POST | `/corps/sites/{id}/funding/receive` | Record receipt of funds against one funding channel | SiteDirector |
| POST | `/corps/schools` | Create a School partnership agreement in DRAFT | SiteDirector |
| GET | `/corps/schools/{id}` | Get a School | SiteDirector, ProgramManager, SchoolLiaison |
| POST | `/corps/schools/{id}/amend` | Amend an ACTIVE agreement (OCC-guarded); moves to AMENDMENT_REVIEW | SiteDirector |
| POST | `/corps/schools/{id}/state` | Transition a School dimension (AGREEMENT default, or DATA_SHARING) | SiteDirector, SchoolLiaison |
| POST | `/corps/applications` | Submit a corps member application; hard eligibility checks at creation | Applicant |
| POST | `/corps/applications/{id}/state` | Advance the recruitment pipeline (SCREEN, INTERVIEWED, OFFERED, ACCEPTED, DECLINED, REJECTED, WITHDRAWN, ENROLLED) | ProgramManager, Applicant |
| GET | `/corps/members/{id}` | Get a CorpsMember with computed totals and projections (CorpsMember role restricted to own id) | SiteDirector, ProgramManager, StipendAdministrator, CorpsMember |
| POST | `/corps/members/{id}/state` | Transition one member dimension (SERVICE default, STIPEND, AWARD) | ProgramManager, StipendAdministrator |
| POST | `/corps/members/{id}/exit` | Exit a member (OCC-guarded); certifies the education award and runs the exit cascade | ProgramManager |
| POST | `/corps/teams` | Create a Team at a school (FORMING); snapshots team size | SiteDirector |
| GET | `/corps/teams/{id}` | Get a Team with roster counters | SiteDirector, ProgramManager |
| POST | `/corps/teams/{id}/state` | Transition Team status (DEPLOYED, COMPLETED, DISSOLVED) | SiteDirector |
| POST | `/corps/teams/{id}/assignments` | Create a TeamAssignment (OCC-guarded on team version); post-DEPLOYED creations count as backfill | ProgramManager |
| POST | `/corps/team-assignments/{id}/end` | End an ACTIVE TeamAssignment early | ProgramManager |
| POST | `/corps/students` | Create a focus-list Student at a school | ProgramManager |
| POST | `/corps/students/{id}/state` | Transition Student enrollment (EXITED) | ProgramManager |
| POST | `/corps/students/{id}/caseload` | Assign or unassign the student's caseload (ASSIGN requires corps_member_id) | ProgramManager |
| POST | `/corps/students/{id}/metrics` | Post the student's current attendance percentage | ProgramManager |
| POST | `/corps/hour-entries` | Log a ServiceHourEntry (PENDING); corps_member_id must equal X-User-ID | CorpsMember |
| POST | `/corps/hour-entries/{id}/review` | Verify, reject, or void an hour entry | ProgramManager |
| POST | `/corps/members/{id}/stipend-payments` | Schedule a stipend payment for a member (provisional amount; period_start unique per member) | StipendAdministrator |
| POST | `/corps/stipend-payments/{id}/state` | Transition a stipend payment (APPROVED, PAID, FORFEITED, CLAWED_BACK) | StipendAdministrator |
| POST | `/corps/evaluation-reports` | Create an EvaluationReport (DRAFT) with metrics snapshot | ProgramManager |
| POST | `/corps/evaluation-reports/{id}/state` | Transition a report (SUBMITTED, ACCEPTED, RETURNED) | ProgramManager, SchoolLiaison |
| GET | `/corps/sites/{id}/schools` | List Schools of a Site | SiteDirector, ProgramManager, SchoolLiaison |
| GET | `/corps/sites/{id}/applications` | List CorpsMemberApplications of a Site | SiteDirector, ProgramManager |
| GET | `/corps/sites/{id}/members` | List CorpsMembers of a Site | SiteDirector, ProgramManager, StipendAdministrator |
| GET | `/corps/schools/{id}/teams` | List Teams of a School | SiteDirector, ProgramManager, SchoolLiaison |
| GET | `/corps/teams/{id}/assignments` | List TeamAssignments of a Team | SiteDirector, ProgramManager |
| GET | `/corps/members/{id}/assignments` | List TeamAssignments of a CorpsMember | SiteDirector, ProgramManager, CorpsMember |
| GET | `/corps/schools/{id}/students` | List Students of a School | SiteDirector, ProgramManager, SchoolLiaison |
| GET | `/corps/members/{id}/students` | List Students currently or formerly assigned to a CorpsMember's caseload | SiteDirector, ProgramManager, CorpsMember |
| GET | `/corps/members/{id}/hour-entries` | List ServiceHourEntries of a CorpsMember | SiteDirector, ProgramManager, StipendAdministrator, CorpsMember |
| GET | `/corps/members/{id}/stipend-payments` | List StipendPayments of a CorpsMember | SiteDirector, ProgramManager, StipendAdministrator, CorpsMember |
| GET | `/corps/schools/{id}/evaluation-reports` | List EvaluationReports of a School | SiteDirector, ProgramManager, SchoolLiaison |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_ENTITY_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_EDUCATION_INELIGIBLE` | 422 |
| `ERR_SERVICE_INELIGIBLE` | 422 |
| `ERR_SERVICE_DATE_INVALID` | 422 |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 422 |
| `ERR_BACKFILL_WINDOW_CLOSED` | 422 |
| `ERR_REPORT_WINDOW_CLOSED` | 422 |
| `ERR_DAILY_HOUR_CAP_EXCEEDED` | 422 |
| `ERR_FUNDRAISING_CAP_EXCEEDED` | 422 |
| `ERR_CASELOAD_FULL` | 422 |
| `ERR_STUDENT_CASELOAD_CONFLICT` | 409 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_TEAM_CAPACITY_EXCEEDED` | 422 |
| `ERR_BACKFILL_LIMIT_REACHED` | 422 |
| `ERR_TEAM_STAFFING_BELOW_MINIMUM` | 422 |
| `ERR_DUPLICATE_PAYMENT_PERIOD` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_DATA_SHARING_NOT_SIGNED` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_NOT_PLACED` | 422 |
| `ERR_AWARD_NOT_EARNED` | 409 |
| `ERR_COMPLETION_HOURS_NOT_MET` | 422 |
| `ERR_SITE_FUNDING_DEFICIT` | 422 |
