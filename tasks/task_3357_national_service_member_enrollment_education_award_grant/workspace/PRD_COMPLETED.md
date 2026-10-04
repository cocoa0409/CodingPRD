# National Service Member Enrollment, Education Award & Grant Monitoring API — Product Requirements Document

## 1. Introduction

National service runs on a simple bargain: the federal government awards member positions to service organizations through competitive grant competitions, organizations enroll members to fill those positions, and members who complete their terms earn an education award held in trust. This document specifies the API that administers that bargain end to end. It covers the full lifecycle — competition windows and application review, award issuance with matching-fund accountability and per-member cost discipline, member enrollment gated by age, citizenship, and a three-component criminal history check, service hour certification under prohibited-activity and fundraising rules, living allowance disbursement, education award issuance and use, compliance visits and corrective action, member grievances, and national performance measure reporting.

The API serves grantee organizations, enrolled members, and three distinct federal or trust-side operator roles, each with segregated duties. Because position slots are finite and refillable, award balances are debited and restored, and corrective findings can suspend an entire program, the system leans on explicit state machines, deterministic selectors, and optimistic concurrency on its two fiscal parents. Every temporal rule in the system — competition windows, visit spacing, corrective-action due dates, the seven-year award use deadline — is evaluated against a logical clock rather than wall-clock time, so behavior is reproducible in test and in production alike.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across the entire API: who may call it, what responses look like, how collections page, how time works, what every resource carries, how money and minutes are rounded, how concurrent writers are kept honest, and in what order validations fire.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's capacity. A request missing either header, or carrying an `X-User-Role` value outside the declared role set, is rejected with `ERR_UNAUTHENTICATED`. The declared roles are exactly `Anonymous`, `CNCSProgramOfficer`, `GranteeStaff`, `Member`, `ComplianceOfficer`, and `TrustAdministrator`. Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED`.

`Anonymous` is the unauthenticated public caller. Its `X-User-ID` is an opaque identifier not tied to any persisted entity, and the role can do exactly one thing: self-register as a member.

`CNCSProgramOfficer`, `ComplianceOfficer`, and `TrustAdministrator` are operator roles whose `X-User-ID` is likewise opaque — an identifier the server may record (for example, as `created_by_officer_id` when a compliance visit is scheduled, or `decided_by_officer_id` when a finding is decided) but never compares against any entity's `id` for ownership purposes. The program officer runs competitions, adjudicates criminal history checks, makes award decisions, suspends and reinstates and closes awards, resolves escalated grievances, reviews performance reports, and sets the logical clock. The compliance officer schedules and conducts visits, records findings, assigns corrective action, decides on submitted evidence, and runs the overdue sweep. The trust administrator approves, denies, and rescinds education award uses.

When `X-User-Role` is `GranteeStaff`, `X-User-ID` is the `id` of the acting GranteeOrganization. Ownership checks on any org-scoped resource compare the resource's `organization_id` against `X-User-ID`; a mismatch is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member, and member-scoped operations — member self-reads, grievance filing and escalation, education award use requests — compare the target's `member_id` against `X-User-ID`.

On top-level collection endpoints (`GET /applications`, `GET /awards`, `GET /enrollments`, `GET /education-awards`, `GET /findings`), the same scoping is applied as a filter rather than a rejection: a `GranteeStaff` caller's list results are restricted to resources of their own organization, and a `Member` caller's to their own member-scoped resources. Collection endpoints nested under a single parent (for example, an award's slots, an enrollment's hour entries, a member's checks) instead enforce ownership with `ERR_UNAUTHORIZED` as above.

Debarment cuts access off at the organization level. Once a GranteeOrganization is `DEBARRED`, every org-scoped write attempted by its `GranteeStaff` is rejected with `ERR_ORG_DEBARRED`.

These access checks are evaluated in a fixed order before any other validation: authentication first, then role authorization, then entity-backed ownership, then org debarment. Existence checks, shape checks, state guards, and business rules run only after all four access tiers pass.

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

Endpoints that return collections accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Out-of-range values are clamped into range rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a non-integer `limit` or `offset` fails shape validation with `ERR_INVALID_REQUEST`. List endpoints may additionally accept resource-specific filter parameters, which are named in the workflow narratives of §3 and in the endpoint descriptions of §4.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; ties on `created_at` — common under the logical clock — are broken by creation (insertion) order, ascending.

The `meta` object of a list response always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server keeps a logical UTC clock that governs every temporal rule in the system. Before it is ever set, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `CNCSProgramOfficer` may move the clock through an admin-only test-driving capability whose request body carries `to_iso8601`; the response reports the resulting `current_utc`. Competition submission windows, competition close, visit scheduling buffers, corrective-action due dates, the overdue sweep, education award use deadlines, and lazy award expiry all evaluate against this logical clock and nothing else.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer starting at 1 that increments on every mutation.

Mutations include writes to computed or accumulator fields: when an operation adds certified minutes to an enrollment, accumulates match onto an award, or debits an education award's balance, the owning resource's `updated_at` refreshes and its `version` increments, even if no client-supplied field changed.

One resource is the exception. A LivingAllowancePayment is an immutable disbursement record: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, and no operation ever modifies a payment after creation.

### 2.6. Money, Minutes, and Rounding Discipline

All monetary amounts are integer cents; all service durations are integer minutes. Two families of computed figures carry decimals, and both are stated as numbers (never strings):

- Cost-per-MSY figures are rounded half up to exactly 2 decimal places.
- Member-service-year (`msy_requested`) figures are rounded half up to exactly 3 decimal places.

Rounding order is pinned wherever rounding interacts with summation. For match commitments and match reports, each line is rounded half up to integer cents first, and the line values are summed afterward — summing raw values and rounding once at the end is a violation, because the two orders can disagree by a cent. Prorated education award amounts are rounded half up to integer cents. Earned-allowance caps are computed with a floor (round down) to integer cents. Everywhere else, integer arithmetic over cents and minutes applies, with no rounding at all.

### 2.7. Term Categories, the Term Table, and the Member-Service Year

Six term categories exist, spelled exactly `FULL_TIME`, `HALF_TIME`, `REDUCED_HALF_TIME`, `QUARTER_TIME`, `MINIMUM_TIME`, and `ABBREVIATED_TIME`. Each category fixes three numbers that the system consults at application time, at enrollment time, at exit time, and at payment time:

- Required service: `FULL_TIME` demands 102000 minutes (1700 hours), `HALF_TIME` 54000 (900 hours), `REDUCED_HALF_TIME` 40500 (675 hours), `QUARTER_TIME` 27000 (450 hours), `MINIMUM_TIME` 18000 (300 hours), and `ABBREVIATED_TIME` 6000 (100 hours).
- Full education award on successful completion: 739500 cents ($7,395.00) for `FULL_TIME`, 391500 for `HALF_TIME`, 293625 for `REDUCED_HALF_TIME`, 195750 for `QUARTER_TIME`, 130500 for `MINIMUM_TIME`, and 43500 cents for `ABBREVIATED_TIME`.
- Living allowance total over the term: 2200000, 1100000, 825000, 550000, 366700, and 122200 cents for the six categories in the same order.

One member-service year (MSY) is one full-time term: 102000 minutes. An application's `total_term_minutes` is the sum, over its `slot_requests`, of each requested `count` multiplied by the term minutes of its `term_category`, and its `msy_requested` is that total divided by 102000, expressed to 3 decimal places.

### 2.8. Optimistic Concurrency Control

Two write operations act on a parent whose version the client must prove it has observed. Both rejections use the same error and status: `ERR_STALE_VERSION`, HTTP 412.

Creating a MemberEnrollment consumes a position slot and advances the parent GrantAward's `version`. The enrollment-creation request must therefore carry `expected_award_version` equal to the award's current `version`. If the award's version has advanced since the client last read it — so the client's picture of the slot ledger is out of date — the create is rejected with `ERR_STALE_VERSION` (412).

Requesting an EducationAwardUse touches a trust balance that use creation, approval, and rescission all advance. The use-creation request must carry `expected_education_award_version` equal to the education award's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (412), preventing the client from acting on a balance it has not observed.

No endpoint other than these two accepts a version field.

### 2.9. Cascading State Consistency

Parent and child resources move together. When an award is suspended — manually or through the overdue-finding escalation cascade — every one of its `ACTIVE` enrollments is suspended with it, stamped with `suspension_origin` `AWARD_CASCADE`; reinstating the award returns exactly those cascade-suspended enrollments to `ACTIVE` and clears their origin to `NONE`, while manually suspended enrollments stay put. Closing an award retires every still-`OPEN` position slot. A competition finalizes itself: the moment its last pending application reaches a terminal decision, the competition bubbles up from `CLOSED` to `AWARDS_FINALIZED` without any separate request. A compliance visit closes itself the same way once at least one finding exists and every finding of the visit is `RESOLVED`. A vacated position slot is immediately re-evaluated for refill — reopened while the award is `ACTIVE` and the slot's `fill_count` is below 2, retired otherwise — so the slot ledger never sits in an indeterminate state. Education awards enforce their use deadline lazily: on every read and every state-changing call against an award whose deadline has passed, a stored status of `ISSUED` or `PARTIALLY_USED` flips to `EXPIRED` before anything else happens. The lazy flip changes only `status`; it does not refresh `updated_at` or increment `version`, notwithstanding §2.5.

### 2.10. Validation Order and Path Resolution

Validations fire in a fixed priority order, and a request fails at the first tier that rejects it. The order is: (1) authentication (`ERR_UNAUTHENTICATED`), (2) role authorization and (3) entity-backed ownership (`ERR_UNAUTHORIZED`), (4) org debarment (`ERR_ORG_DEBARRED`), (5) path-identifier existence, (6) body foreign-key existence, (7) request shape (`ERR_INVALID_REQUEST` — missing required fields, unknown enum values, range violations), (8) state guards (`ERR_INVALID_STATE` and its state-specific siblings), (9) optimistic concurrency (`ERR_STALE_VERSION`), then business rules — safety checks first, then temporal checks, then constraint checks, then fiscal gates.

Path identifiers resolve left to right. When a path nests one resource under another, the server validates the leftmost identifier first and rejects with the 404 error of the first segment that does not resolve — for example, an unknown award segment yields `ERR_AWARD_NOT_FOUND` before any enrollment, slot, visit, measure, or match-report validation beneath it is attempted. The not-found errors are resource-specific: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_COMPETITION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_EDUCATION_AWARD_NOT_FOUND`, `ERR_USE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_GRIEVANCE_NOT_FOUND`, and `ERR_MEASURE_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Program: Organizations and Competitions

A `CNCSProgramOfficer` begins by registering each prospective service organization. Registration captures the organization's `legal_name`, its `ein` (an employer identification number, recorded as supplied — the server enforces no uniqueness check on it), and its `org_type`, one of `NONPROFIT`, `PUBLIC_AGENCY`, `INSTITUTION_OF_HIGHER_ED`, or `TRIBAL`. A new organization starts `ACTIVE`. If the government later loses confidence in an organization, the officer debars it: the organization's `status` moves from `ACTIVE` to `DEBARRED`, the transition is terminal, and from that moment its staff lose write access — every org-scoped write they attempt comes back `ERR_ORG_DEBARRED`.

Competitions are the other piece of program setup. Opening a competition requires a `title`, the federal `fiscal_year`, and an application window delimited by `application_open_at` and `application_close_at`; the close instant must be strictly later than the open instant, or the request fails shape validation with `ERR_INVALID_REQUEST`. A competition is born `OPEN`, and submissions are accepted at or after `application_open_at` and at or before `application_close_at` — both bounds inclusive. Once the window has passed, the officer closes the competition: closing requires the current logical time to be strictly later than `application_close_at`, and a premature close is rejected with `ERR_INVALID_STATE`. The `OPEN` → `CLOSED` transition is the only manual one a competition ever sees. Its final transition, `CLOSED` → `AWARDS_FINALIZED`, is fired by the system itself the moment no application of that competition remains in `DRAFT`, `UNDER_REVIEW`, or `CLARIFICATION_REQUESTED` — that is, when every application has been awarded or rejected.

### 3.2. The Application Cycle: Drafting, Clarification, and Award Decisions

Applications are org self-service. A `GranteeStaff` caller drafts an application under a competition by supplying `organization_id` (which must equal the caller's own `X-User-ID`, else `ERR_UNAUTHORIZED`), the `federal_share_requested_cents` (integer cents, greater than zero), a `slot_requests` array describing the positions sought — the array must be non-empty, each entry pairing a `term_category` from the term table with a `count` of at least 1 — and a `match_lines` array recording the organization's match commitment, each line carrying a `category` of `CASH` or `IN_KIND` and an `amount_cents`; the `match_lines` array may be empty, and a line's `amount_cents` may be zero but never negative.

Creation computes and stores five derived figures. The `allowable_match_commitment_cents` is the sum over match lines of each line's `amount_cents` multiplied by its category rate — full value for `CASH`, four-fifths value (0.80) for `IN_KIND` — with every line individually rounded half up to integer cents before the sum is taken. The `total_term_minutes` aggregates the slot requests against the term table, and `msy_requested` expresses that total in member-service years to 3 decimal places. Two cost-per-MSY figures follow, both rounded half up to 2 decimal places: `cost_per_msy_federal_cents`, the federal share requested per member-service year, and `cost_per_msy_total_cents`, the same ratio with the allowable match commitment added to the numerator. For any application with a nonzero allowable match, the total-cost basis is strictly larger than the federal basis — an application can sit under the cap on one and over it on the other, and as the next paragraph shows, only the federal basis is gated.

Submitting moves the application `DRAFT` → `UNDER_REVIEW` and runs three gates, in this order. First, the submission must land within the competition window — at or after `application_open_at` and at or before `application_close_at` — else `ERR_COMPETITION_WINDOW_CLOSED`. Second, the federal-basis cost per MSY must not exceed the statutory cap of 2300000.00 cents ($23,000.00 per member-service year); equality with the cap is allowed, and a breach is `ERR_COST_PER_MSY_EXCEEDS_CAP`. Third, the match must clear the statutory floor: the allowable match commitment multiplied by 25 must be at least the federal share requested multiplied by 6 — that is, allowable match of at least 24% of the federal share, with equality allowed — else `ERR_MATCH_BELOW_MINIMUM`. A submit attempted from any state other than `DRAFT` hits the generic transition guard, `ERR_INVALID_STATE`.

Review is a conversation. A `CNCSProgramOfficer` may ask for clarification, moving the application `UNDER_REVIEW` → `CLARIFICATION_REQUESTED` and recording the payload's `question` as the application's `clarification_question`. The applicant answers by responding to the clarification; the payload's `response` is recorded as `clarification_response` and the application returns to `UNDER_REVIEW`. This loop may repeat without bound. Both fields remain null until their respective events set them; a fresh clarification request overwrites `clarification_question` but does not clear a previously recorded `clarification_response`.

Two terminal decisions await. Awarding is permitted only from `UNDER_REVIEW` and only after the competition has been closed; an award attempt while the competition is still `OPEN` is rejected with `ERR_INVALID_STATE`. The officer commits a `federal_share_awarded_cents` — an integer greater than zero, else `ERR_INVALID_REQUEST` — which must not exceed the `federal_share_requested_cents` (else `ERR_AWARD_EXCEEDS_REQUEST`), and the federal-basis cost per MSY recomputed on the awarded amount must again satisfy the 2300000.00-cent cap (else `ERR_COST_PER_MSY_EXCEEDS_CAP`). A successful award does several things at once: the application becomes `AWARDED`; a new GrantAward is created `ACTIVE` at `version` 1, linked back through `application_id`, copying the application's `organization_id`, `competition_id`, and `total_term_minutes`, carrying the `federal_share_awarded_cents`, a freshly computed `cost_per_msy_awarded_cents` (half-up, 2 decimal places), and `allowable_match_cents` starting at 0; and one PositionSlot is minted per requested slot unit — `awarded_slot_count` in total, the sum of the `slot_requests` counts — numbered by `slot_index` from 1 upward in `slot_requests` array order, each `OPEN` with `fill_count` 0. Rejection is simpler: from `UNDER_REVIEW` or `CLARIFICATION_REQUESTED`, the officer supplies a `reason` and the application becomes `REJECTED`. Either decision can be the one that tips the competition into `AWARDS_FINALIZED`.

### 3.3. Awards, Match Accountability, and the Position Slot Ledger

The GrantAward is the fiscal and operational parent for everything that follows. Its lifecycle has three manual transitions. Suspending an `ACTIVE` award records the supplied `reason` as `suspension_reason` — defaulting to `ESCALATED_FINDING_OVERDUE` when the payload omits it or supplies an empty value — and cascades: every enrollment of the award that is `ACTIVE` drops to `SUSPENDED` with `suspension_origin` `AWARD_CASCADE`. Reinstating a `SUSPENDED` award is blocked while any finding of the award stands `ESCALATED` (`ERR_FINDINGS_ESCALATED`); a successful reinstate clears `suspension_reason` back to null and returns exactly the cascade-suspended enrollments — those whose `suspension_origin` is `AWARD_CASCADE` — to `ACTIVE` with origin `NONE`. Closing an `ACTIVE` award is the final act, and it is gated twice: no enrollment of the award may remain in `PENDING_CHECKS`, `ACTIVE`, or `SUSPENDED` (else `ERR_ENROLLMENTS_OPEN`), and the accumulated match must clear the same 24% floor as at submit time — `allowable_match_cents` multiplied by 25 must be at least `federal_share_awarded_cents` multiplied by 6, equality allowed, else `ERR_MATCH_BELOW_MINIMUM`. Closing retires every still-`OPEN` slot of the award (`OPEN` → `RETIRED`).

Match accountability continues after the award is made. The grantee files match reports against an `ACTIVE` award — a report carries a `reporting_period_label` and `lines` in the same shape as the application's match lines — and each report adds its per-line-rounded sum to the award's `allowable_match_cents`. Reporting against a non-`ACTIVE` award is rejected with `ERR_AWARD_SUSPENDED`. Every accepted report also increments the award's `version`, which matters to anyone mid-way through enrolling members under optimistic concurrency.

The position slots are the award's capacity ledger. Each slot's `term_category` is fixed at minting, and its `fill_count` records how many times it has ever reached `FILLED`. Slots move on system events, never on direct request: enrollment creation reserves one (`OPEN` → `RESERVED`); a cleared criminal history check fills it (`RESERVED` → `FILLED`, `fill_count` incremented); a flagged check releases it back (`RESERVED` → `OPEN`); a member exit vacates it (`FILLED` → `VACATED`). Vacancy triggers immediate refill evaluation: if the award is `ACTIVE` and the slot's `fill_count` is still below 2, the slot reopens (`VACATED` → `OPEN`); if the award is anything other than `ACTIVE`, or the slot has already been filled twice, the slot is `RETIRED`. A slot already filled twice is never offered again, and slots still `OPEN` when their award closes retire with it.

### 3.4. Members, Criminal History Checks, and Enrollment

Anyone may self-register as a member through the public registration endpoint; the `Anonymous` caller supplies `full_name`, `date_of_birth` (an ISO calendar date), and `citizenship_status`, one of `US_CITIZEN`, `US_NATIONAL`, or `LAWFUL_PERMANENT_RESIDENT`. A new member is `ACTIVE` with a `for_cause_release_count` of 0.

Before a member can serve, the grantee initiates a criminal history check. Each check carries three independently tracked components — the NSOPR component (`nsopr_status`), the state repository component (`state_status`), and the FBI fingerprint component (`fbi_status`) — each starting `PENDING`. Every check for a member receives a `check_seq`, assigned per member as one more than the highest existing sequence number, starting at 1; the sequence is strictly monotonic, so "the member's latest check" always means the one with the highest `check_seq`, with no clock or identifier comparison ever involved. Starting a second check while one is still `PENDING` for the same member is rejected with `ERR_CHECK_IN_PROGRESS`. A `CNCSProgramOfficer` records component results one at a time by naming the `component` (`NSOPR`, `STATE_REPOSITORY`, or `FBI_FINGERPRINT`) and its `result`; recording a component that already has a result is `ERR_COMPONENT_ALREADY_RECORDED`, and recording anything on a check whose adjudication has already left `PENDING` is `ERR_CHECK_ALREADY_ADJUDICATED`; since every component necessarily carries a result once adjudication has left `PENDING`, `ERR_CHECK_ALREADY_ADJUDICATED` takes precedence whenever both conditions apply. The check's `adjudication` is computed: it stays `PENDING` while any component is pending, becomes `CLEARED` when all three components are `CLEAR`, and becomes `FLAGGED` the moment every component has a result and at least one is `FLAGGED`. When adjudication leaves `PENDING`, `adjudicated_at` is set — and the consequences ripple: on `CLEARED`, every enrollment of that member waiting in `PENDING_CHECKS` becomes `ACTIVE` and each such enrollment's reserved slot fills (`RESERVED` → `FILLED`, `fill_count` incremented); on `FLAGGED`, those enrollments are `CANCELLED` and their slots release back to `OPEN`.

Enrollment itself is the most heavily gated write in the system. A `GranteeStaff` caller enrolls a member against a specific award, supplying `member_id`, the requested `term_category`, the `service_start_date` and `service_end_date` (ISO dates; the end must be strictly later than the start, else `ERR_INVALID_REQUEST`), and the OCC token `expected_award_version` described in §2.8. The gates then run in the system's fixed validation order: the referenced member must exist (`ERR_MEMBER_NOT_FOUND`); the award must be `ACTIVE` (`ERR_AWARD_SUSPENDED`); the member must be at least 17 years old on the service start date — the `date_of_birth` plus seventeen years must fall on or before `service_start_date` (a February 29 birthday rolls to February 28 of the target year) — else `ERR_MEMBER_TOO_YOUNG`; a `DEBARRED` member may never serve again (`ERR_MEMBER_INELIGIBLE`); the member must have at least one criminal history check on file (`ERR_CRIMINAL_CHECK_OUTSTANDING`); and the latest check must not have adjudicated `FLAGGED` (`ERR_CRIMINAL_CHECK_FLAGGED`) — a still-`PENDING` latest check is acceptable, and the enrollment simply waits. The member must also be free of scheduling conflicts: any other enrollment of the same member in `PENDING_CHECKS`, `ACTIVE`, or `SUSPENDED` whose half-open service period — inclusive of its start date, exclusive of its end date — intersects the requested period blocks the create with `ERR_SERVICE_PERIOD_OVERLAP`; back-to-back service, where the new start date equals an existing end date, is allowed. Finally, the slot selector must find a candidate: among the award's slots that are `OPEN` and match the requested `term_category`, it picks the one with the lowest `slot_index` — unique per award, so no tie is possible; were one ever to arise, `created_at` ascending would break it, never the id — and an empty candidate set is `ERR_NO_OPEN_SLOT`.

A successful create is transactional: the selected slot moves `OPEN` → `RESERVED`, the award's `version` increments by 1, and the enrollment lands with its `term_minutes` copied from the term table, its hour and payment accumulators (`certified_minutes`, `fundraising_certified_minutes`, `allowance_paid_cents`) at 0, and `suspension_origin` `NONE`. If the member's latest check is already `CLEARED` at creation time, the enrollment activates immediately — `ACTIVE` from birth, its slot stepping straight through to `FILLED` — otherwise it waits in `PENDING_CHECKS` for the adjudication cascade described above.

While serving, an enrollment can be manually suspended by the grantee (no reason is captured; `suspension_origin` becomes `MANUAL`) and later reinstated, provided the award is `ACTIVE` at reinstate time — reinstating under a suspended award is `ERR_AWARD_SUSPENDED`. Reinstatement clears the origin to `NONE`. Award-level suspension and reinstatement move cascade-origin enrollments without any per-enrollment calls, per §2.9.

### 3.5. Recording and Certifying Service Hours

Hour tracking is timesheet-based. Against an `ACTIVE` enrollment — recording against an enrollment in any other state is `ERR_ENROLLMENT_NOT_ACTIVE` — the grantee records an entry with a `service_date`, a `minutes` count between 1 and 48000 (a single timesheet entry may cover up to 800 hours of service), and an `activity_code` of `DIRECT_SERVICE`, `CAPACITY_BUILDING`, `TRAINING`, `FUNDRAISING`, `PROSELYTIZING`, or `PARTISAN_LOBBYING`. The `service_date` must fall inside the enrollment's half-open service period — on or after `service_start_date` and strictly before `service_end_date` — or the entry is rejected with `ERR_SERVICE_DATE_OUT_OF_RANGE`. Every entry is born `PENDING`.

Certification is where the discipline lives, and its three checks run in a fixed order: the enrollment must still be `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`); the entry's `activity_code` must not be `PROSELYTIZING` or `PARTISAN_LOBBYING` — those two activities are prohibited during service hours and can never be certified (`ERR_PROHIBITED_ACTIVITY`); and for a `FUNDRAISING` entry, the ten-percent cap is evaluated with the pending entry included on both sides — the member's `fundraising_certified_minutes` plus the entry's `minutes`, multiplied by 10, must not exceed `certified_minutes` plus the entry's `minutes`. A fundraising share of exactly one tenth of the new total is allowed; one minute beyond it is `ERR_FUNDRAISING_CAP_EXCEEDED`. A certified entry moves `PENDING` → `CERTIFIED` and adds its `minutes` to the enrollment's `certified_minutes` and, when the activity is `FUNDRAISING`, the same amount to `fundraising_certified_minutes`. Rejection is the other terminal outcome: the grantee supplies a `reason`, it is recorded as `reject_reason`, and the entry moves `PENDING` → `REJECTED`.

### 3.6. Living Allowance Disbursement

Members in service receive a living allowance, disbursed in payments recorded against their enrollment. The grantee supplies an `amount_cents` — an integer of at least 1, else `ERR_INVALID_REQUEST` — and an optional `note` memo; the enrollment must be `ACTIVE`, a state check that precedes every fiscal check (`ERR_ENROLLMENT_NOT_ACTIVE`). Three fiscal gates then fire in pinned order, and which error a bad payment draws depends on which gate it hits first:

1. Period cap: a single payment may not exceed 100000 cents ($1,000.00). Exactly 100000 is allowed; anything more is `ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED`.
2. Term total: the payment must not push `allowance_paid_cents` past the term's allowance total from the term table. A breach is `ERR_ALLOWANCE_EXHAUSTED`.
3. Earned cap: the payment must not push `allowance_paid_cents` past what the member has earned by service — the term allowance total multiplied by the enrollment's `certified_minutes` and divided by its `term_minutes`, floored to integer cents. Landing exactly on the earned cap is allowed; exceeding it is `ERR_ALLOWANCE_EARNED_CAP_EXCEEDED`.

An accepted payment adds its `amount_cents` to the enrollment's `allowance_paid_cents`. Payment records are immutable receipts: per §2.5, a LivingAllowancePayment carries `id` and `created_at` and nothing else of the common field set.

### 3.7. Ending Service: Exits, Education Awards, and the Trust

Every enrollment ends in one of three ways, chosen by the grantee through the `exit_reason` it supplies at exit time: `SUCCESSFUL`, `COMPELLING_CIRCUMSTANCE`, or `FOR_CAUSE`. Exit is permitted from `ACTIVE` and from `SUSPENDED` alike, with identical consequences in both cases; any other from-state trips the generic guard, `ERR_INVALID_STATE`. All three exits stamp `exited_at` with the current logical time, compute an `exit_overpayment_cents`, and vacate the member's slot (`FILLED` → `VACATED`, with the refill evaluation of §3.3 following immediately). They differ in what the member earns and what the member becomes.

A `SUCCESSFUL` exit certifies full completion. It requires the enrollment's `certified_minutes` to be at least its `term_minutes` — reaching the requirement exactly is eligible — else `ERR_MIN_HOURS_NOT_MET`. The system issues an EducationAward for the full category amount from the term table: `issued_amount_cents` is the flat award for the term regardless of hours served beyond the minimum, `remaining_balance_cents` starts equal to it, `issued_at` is the current logical time, and `use_deadline_at` is exactly seven calendar years later (a February 29 issuance rolls to February 28 of the target year). The enrollment records the new award's id in `education_award_id` and lands in `EXITED_SUCCESSFUL`. Because a fully served member has earned the full living allowance, the overpayment is whatever was paid beyond the term's allowance total — `allowance_paid_cents` minus the allowance total, floored at zero.

A `COMPELLING_CIRCUMSTANCE` exit prorates. It requires the member to have certified at least fifteen percent of the term — `certified_minutes` multiplied by 100 must be at least 15 times `term_minutes`, and exactly fifteen percent is eligible — else `ERR_PRORATION_FLOOR_NOT_MET`. The award is proportional: the category's full award multiplied by the ratio of `certified_minutes` to `term_minutes`, rounded half up to integer cents, so the same term category at a partial completion yields a strictly smaller award than full completion. The seven-year use deadline runs from issuance exactly as on the full path, the enrollment lands in `EXITED_COMPELLING`, and the earned side of the overpayment calculation prorates the same way: the allowance total multiplied by the certified-minutes ratio, floored to integer cents, with `exit_overpayment_cents` the excess of `allowance_paid_cents` over that earned figure, never below zero.

A `FOR_CAUSE` release is disciplinary. It is blocked while any grievance of the enrollment stands `ESCALATED` (`ERR_GRIEVANCE_PENDING`) — the member's appeal must run its course first. No education award is created (`education_award_id` stays null), the member is `DEBARRED` from further service, and the member's `for_cause_release_count` increments; that debarment is what later enrollment attempts hit as `ERR_MEMBER_INELIGIBLE`. The enrollment lands in `RELEASED_FOR_CAUSE`, and the overpayment uses the same prorated, floored earned figure as a compelling-circumstance exit.

The issued EducationAward is a trust account. Its `status` begins `ISSUED`; each approved use that leaves a positive balance moves it to `PARTIALLY_USED`; one that drains it moves it to `EXHAUSTED`; and a rescission that restores the full issued amount returns it from `PARTIALLY_USED` to `ISSUED`. The deadline is enforced lazily per §2.9: reads and state-changing calls flip a past-deadline `ISSUED` or `PARTIALLY_USED` award to `EXPIRED` before doing anything else.

A member spends from the trust by requesting a use against their own award, supplying a `use_type` of `TUITION` or `QUALIFIED_LOAN`, an `amount_cents` greater than zero, and the OCC token `expected_education_award_version` of §2.8. Tuition carries an extra eligibility rule: `institution_title_iv` must be true, certifying a Title IV institution, else `ERR_INSTITUTION_NOT_ELIGIBLE`; for a `QUALIFIED_LOAN` use the flag is ignored. Three guards then protect the balance, and their relative order matters. The award's stored status must be `ISSUED` or `PARTIALLY_USED` — a use against a stored `EXHAUSTED` or `EXPIRED` award is `ERR_EDUCATION_AWARD_NOT_USABLE`. Next, the use deadline: the current logical time must be at or before `use_deadline_at`, with the deadline instant itself still usable; a use after the deadline is `ERR_AWARD_USE_DEADLINE_PASSED`, and that very rejection flips the award to `EXPIRED` as a side effect. Note the interplay: an award whose deadline has passed but whose stored status still reads `ISSUED` or `PARTIALLY_USED` is not caught by the first guard — it is caught by the deadline guard. Finally, the requested amount must not exceed `remaining_balance_cents` (`ERR_INSUFFICIENT_AWARD_BALANCE`). A created use enters `PENDING_APPROVAL`, and its creation increments the education award's `version` by 1.

Decisions belong to the `TrustAdministrator`, whose call carries a `decision` of `APPROVE` or `DENY` and an optional `note`. Approving a pending use re-validates the balance at decide time — if `remaining_balance_cents` no longer covers the `amount_cents`, the approval fails with `ERR_INSUFFICIENT_AWARD_BALANCE` — then debits the award: `remaining_balance_cents` falls by the amount, the award's `version` increments, and the award's status becomes `EXHAUSTED` when the balance hits zero and `PARTIALLY_USED` otherwise. Denial moves the use `PENDING_APPROVAL` → `DENIED` and changes no balances. Either way, the payload's optional `note` is recorded as the use's `decision_note`. Deciding a use that is not `PENDING_APPROVAL` is `ERR_USE_NOT_PENDING`. An approved use can later be rescinded — a compensating action requiring a `reason` that moves the use `APPROVED` → `RESCINDED` — which restores the amount to `remaining_balance_cents`, increments the award's `version` again, and recomputes the award's status: `ISSUED` when the restoration returns the balance to the full `issued_amount_cents`, `PARTIALLY_USED` otherwise. Rescinding a use that is not `APPROVED` is likewise `ERR_USE_NOT_PENDING`. Use decisions and rescissions act on the award's stored status as found and do not themselves trigger the lazy expiry of §2.9; likewise, on use creation the flip to `EXPIRED` fires only when the deadline guard itself is reached, so a use request rejected earlier (for example, on a stale version) leaves the stored status untouched.

### 3.8. Compliance Oversight: Visits, Findings, and the Overdue Sweep

Oversight begins with the `ComplianceOfficer` scheduling a visit against an award: a `visit_type` of `SITE_VISIT` or `FILE_REVIEW` and a `scheduled_date`. Visits of the same award must breathe — the new date must sit at least 30 days away, in either direction, from every other visit of that award that is `SCHEDULED` or `CONDUCTED`; exactly 30 days of separation is allowed, anything tighter is `ERR_VISIT_TOO_SOON`. The scheduling officer's identity is captured as `created_by_officer_id`, and that capture is not clerical: it anchors the segregation-of-duties rule that decides who may later close findings from this visit. Conducting the visit stamps `conducted_at` and moves it `SCHEDULED` → `CONDUCTED`.

Findings are recorded on a conducted visit with a `severity` of `LOW` or `HIGH` and a `description` narrative; the finding inherits the visit's `award_id`. A finding opens `OPEN`. Assigning corrective action records the `requirement` and a `due_days` window between 14 and 90 days inclusive (outside that range is `ERR_INVALID_REQUEST`), computes `due_at` as the assignment instant plus that many days, and moves the finding to `ACTION_ASSIGNED`. The grantee answers by submitting evidence — an `evidence_note`, with the submitting organization recorded as `submitted_by_org_id` — which moves the finding to `EVIDENCE_SUBMITTED`; evidence is accepted from `ACTION_ASSIGNED` and, notably, from `ESCALATED` as well, so an escalated finding remains correctable.

Deciding on evidence is segregated: the officer's `decision` is `APPROVE` or `REJECT`, and the deciding officer's `X-User-ID` must differ from the visit's `created_by_officer_id`, with a self-decision rejected as `ERR_SOD_VIOLATION`. The decider is recorded as `decided_by_officer_id`. An approval resolves the finding (`RESOLVED`), and when every finding of the visit is `RESOLVED` — with at least one finding in existence — the visit bubbles itself up to `CLOSED`. A rejection sends the finding back to `ACTION_ASSIGNED` with its `due_at` unchanged, and the corrective cycle repeats: new evidence, new decision, as many rounds as needed.

Findings that outlive their windows escalate. A `ComplianceOfficer` can run the overdue sweep, which finds every finding in `ACTION_ASSIGNED` or `EVIDENCE_SUBMITTED` whose `due_at` is earlier than the current logical time and moves it to `ESCALATED`, processing them in `created_at` ascending order. Escalation is a three-hop cascade: the finding escalates; its award, if `ACTIVE`, is suspended with `suspension_reason` recorded as `ESCALATED_FINDING_OVERDUE`; and that suspension cascades in turn to every `ACTIVE` enrollment of the award, each dropped to `SUSPENDED` with `suspension_origin` `AWARD_CASCADE` — the same posture a manual award suspension produces, which is exactly what blocks award reinstatement until the findings clear (`ERR_FINDINGS_ESCALATED`, §3.3). The sweep reports what it did: the identifiers of the findings it escalated (`escalated_finding_ids`), the awards it suspended (`suspended_award_ids`), and the enrollments it suspended (`suspended_enrollment_ids`).

### 3.9. Member Grievances and Performance Measurement

A member who believes they have been wronged files a grievance against their own enrollment, supplying a `description`; ownership here is member-scoped per §2.1. A grievance is born `FILED`, and the member may escalate it to the federal level (`FILED` → `ESCALATED`). Escalation has teeth: it blocks a `FOR_CAUSE` release of that enrollment for as long as it stands, per §3.7. Only a `CNCSProgramOfficer` may resolve an escalated grievance, recording an `outcome` of `UPHELD` or `DISMISSED` as it moves to `RESOLVED`. Resolving a grievance that is not `ESCALATED`, or escalating one that is not `FILED`, trips the generic transition guard `ERR_INVALID_STATE`.

Performance measurement runs in parallel with everything else. The grantee establishes national performance measures on an `ACTIVE` award — attempting it on a suspended award is `ERR_AWARD_SUSPENDED` — each with a `measure_code` of `MSY_OUTPUT`, `BENEFICIARY_OUTCOME`, or `COMMUNITY_OUTCOME`, a `target_value` greater than zero, and a free-text `unit` label such as beneficiaries or hours. A measure starts `OPEN`. Reporting against it submits a period: `period_start`, `period_end` (which must not precede the start), and an `actual_value` of zero or more; a bad period or negative value is `ERR_INVALID_REQUEST`. Each accepted report moves the measure to `SUBMITTED` and refreshes its `latest_period_start`, `latest_period_end`, and `latest_actual_value`. Federal review then decides, through a `decision` of `ACCEPT` or `RETURN`: acceptance moves the measure `SUBMITTED` → `ACCEPTED` — terminal — and records the officer's `comment`, which may be null, as `review_comment`; a return moves it `SUBMITTED` → `RETURNED` and requires a non-empty `comment` explaining what to fix, with `ERR_INVALID_REQUEST` for a silent return. A returned measure accepts a fresh report, which moves it back to `SUBMITTED` and updates the latest-period fields again — the review cycle repeats until acceptance.

## 4. Endpoint Definitions

Operations that create a new resource — an organization, a competition, an application, an award (created by the award decision), a match report, a member, a criminal history check, an enrollment, an hour entry, an allowance payment, an education award use, a compliance visit, a finding, a grievance, or a performance measure — return `201 Created`. Operations that modify an existing resource in place, including all state transitions, decisions, rescissions, sweeps, and the clock set, return `200 OK`. Unless a list is being returned, the response `data` carries the created or updated resource object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | CNCSProgramOfficer |
| POST | `/organizations` | Register a service organization | CNCSProgramOfficer |
| GET | `/organizations/{orgId}` | Read one organization | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| POST | `/organizations/{orgId}/debar` | Debar an organization; its staff lose write access | CNCSProgramOfficer |
| POST | `/competitions` | Open a grant competition with an application window | CNCSProgramOfficer |
| GET | `/competitions/{competitionId}` | Read one competition | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, TrustAdministrator, Member |
| POST | `/competitions/{competitionId}/close` | Close the competition after the application window ends | CNCSProgramOfficer |
| POST | `/competitions/{competitionId}/applications` | Create a DRAFT application (org self-service) | GranteeStaff |
| GET | `/applications` | List applications, optionally filtered by `competition_id`, `organization_id`, `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/applications/{applicationId}` | Read one application | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| POST | `/applications/{applicationId}/submit` | Submit a DRAFT application for review | GranteeStaff |
| POST | `/applications/{applicationId}/request-clarification` | Ask the applicant a clarification question | CNCSProgramOfficer |
| POST | `/applications/{applicationId}/respond-clarification` | Answer a clarification request; returns to review | GranteeStaff |
| POST | `/applications/{applicationId}/award` | Award the application; creates the GrantAward and all PositionSlots | CNCSProgramOfficer |
| POST | `/applications/{applicationId}/reject` | Reject an application under review or clarification | CNCSProgramOfficer |
| GET | `/awards` | List awards, optionally filtered by `application_id`, `organization_id`, `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/awards/{awardId}` | Read one award | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| POST | `/awards/{awardId}/suspend` | Suspend an award; cascades to its ACTIVE enrollments | CNCSProgramOfficer |
| POST | `/awards/{awardId}/reinstate` | Reinstate a suspended award; reactivates cascade-suspended enrollments | CNCSProgramOfficer |
| POST | `/awards/{awardId}/close` | Close an award; retires its OPEN slots | CNCSProgramOfficer |
| POST | `/awards/{awardId}/match-reports` | Report match contributions toward the award's allowable match | GranteeStaff |
| GET | `/awards/{awardId}/slots` | List the award's position slots, optionally filtered by `status`, `term_category` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/awards/{awardId}/compliance-visits` | List the award's compliance visits, optionally filtered by `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/awards/{awardId}/performance-measures` | List the award's performance measures, optionally filtered by `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/slots/{slotId}` | Read one position slot | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| POST | `/members/register` | Self-register a member | Anonymous |
| GET | `/members/{memberId}` | Read one member | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, Member |
| POST | `/members/{memberId}/criminal-history-checks` | Initiate a three-component criminal history check | GranteeStaff |
| GET | `/members/{memberId}/criminal-history-checks` | List a member's criminal history checks | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, Member |
| POST | `/criminal-history-checks/{checkId}/component-results` | Record one component result; the last pending component adjudicates the check | CNCSProgramOfficer |
| POST | `/awards/{awardId}/enrollments` | Enroll a member against an award (slot selection, OCC on the award) | GranteeStaff |
| GET | `/enrollments` | List enrollments, optionally filtered by `member_id`, `award_id`, `slot_id`, `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, Member |
| GET | `/enrollments/{enrollmentId}` | Read one enrollment | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, Member |
| POST | `/enrollments/{enrollmentId}/suspend` | Manually suspend an ACTIVE enrollment | GranteeStaff |
| POST | `/enrollments/{enrollmentId}/reinstate` | Reinstate a SUSPENDED enrollment | GranteeStaff |
| POST | `/enrollments/{enrollmentId}/exit` | Exit a member: successful, compelling circumstance, or for cause | GranteeStaff |
| GET | `/enrollments/{enrollmentId}/hour-entries` | List an enrollment's hour entries, optionally filtered by `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff, Member |
| GET | `/enrollments/{enrollmentId}/allowance-payments` | List an enrollment's living allowance payments | CNCSProgramOfficer, GranteeStaff, Member |
| GET | `/enrollments/{enrollmentId}/grievances` | List an enrollment's grievances, optionally filtered by `status` | CNCSProgramOfficer, GranteeStaff, Member |
| POST | `/enrollments/{enrollmentId}/hour-entries` | Record a service timesheet entry | GranteeStaff |
| POST | `/hour-entries/{entryId}/certify` | Certify a PENDING hour entry | GranteeStaff |
| POST | `/hour-entries/{entryId}/reject` | Reject a PENDING hour entry with a reason | GranteeStaff |
| POST | `/enrollments/{enrollmentId}/allowance-payments` | Disburse a living allowance payment | GranteeStaff |
| GET | `/education-awards` | List education awards, optionally filtered by `member_id`, `enrollment_id`, `status` | CNCSProgramOfficer, TrustAdministrator, Member |
| GET | `/education-awards/{educationAwardId}` | Read one education award | CNCSProgramOfficer, TrustAdministrator, Member |
| POST | `/education-awards/{educationAwardId}/uses` | Request a use of the education award (OCC on the award) | Member |
| GET | `/education-awards/{educationAwardId}/uses` | List uses of an education award, optionally filtered by `status` | CNCSProgramOfficer, TrustAdministrator, Member |
| POST | `/education-award-uses/{useId}/decide` | Approve or deny a pending use | TrustAdministrator |
| POST | `/education-award-uses/{useId}/rescind` | Rescind an APPROVED use; restores the award balance | TrustAdministrator |
| POST | `/awards/{awardId}/compliance-visits` | Schedule a site visit or file review | ComplianceOfficer |
| POST | `/compliance-visits/{visitId}/conduct` | Mark a scheduled visit conducted | ComplianceOfficer |
| POST | `/compliance-visits/{visitId}/findings` | Record a finding on a conducted visit | ComplianceOfficer |
| GET | `/findings` | List findings, optionally filtered by `visit_id`, `award_id`, `status` | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| GET | `/findings/{findingId}` | Read one finding | CNCSProgramOfficer, ComplianceOfficer, GranteeStaff |
| POST | `/findings/{findingId}/assign-corrective-action` | Assign corrective action with a 14–90 day window | ComplianceOfficer |
| POST | `/findings/{findingId}/submit-evidence` | Submit corrective evidence | GranteeStaff |
| POST | `/findings/{findingId}/decide` | Decide on submitted evidence (segregation of duties) | ComplianceOfficer |
| POST | `/compliance/sweep-overdue` | Escalate every overdue finding; cascades to awards and enrollments | ComplianceOfficer |
| POST | `/enrollments/{enrollmentId}/grievances` | File a grievance on one's own enrollment | Member |
| POST | `/grievances/{grievanceId}/escalate` | Escalate the grievance to the federal level | Member |
| POST | `/grievances/{grievanceId}/resolve` | Resolve an escalated grievance | CNCSProgramOfficer |
| POST | `/awards/{awardId}/performance-measures` | Establish a national performance measure on an ACTIVE award | GranteeStaff |
| POST | `/performance-measures/{measureId}/reports` | Submit a periodic report for a measure | GranteeStaff |
| POST | `/performance-measures/{measureId}/review` | Review a submitted report: accept or return | CNCSProgramOfficer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified where the corresponding workflow lives — §2 for access, envelope, concurrency, and ordering rules, §3 for business rules. Two further identifiers exist outside the API's own validation surface: a request path that routes to nothing is answered `ERR_NOT_FOUND` (404), and an unexpected server fault is answered `ERR_INTERNAL` (500); an unsupported method on a routed path returns `ERR_INVALID_REQUEST` with status 405.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_ORG_DEBARRED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPETITION_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_EDUCATION_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_USE_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_GRIEVANCE_NOT_FOUND` | 404 Not Found |
| `ERR_MEASURE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AWARD_SUSPENDED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_EDUCATION_AWARD_NOT_USABLE` | 409 Conflict |
| `ERR_USE_NOT_PENDING` | 409 Conflict |
| `ERR_CHECK_ALREADY_ADJUDICATED` | 409 Conflict |
| `ERR_COMPONENT_ALREADY_RECORDED` | 409 Conflict |
| `ERR_CHECK_IN_PROGRESS` | 409 Conflict |
| `ERR_ENROLLMENTS_OPEN` | 409 Conflict |
| `ERR_FINDINGS_ESCALATED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_TOO_YOUNG` | 422 Unprocessable Entity |
| `ERR_MEMBER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CRIMINAL_CHECK_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_CRIMINAL_CHECK_FLAGGED` | 422 Unprocessable Entity |
| `ERR_GRIEVANCE_PENDING` | 409 Conflict |
| `ERR_PROHIBITED_ACTIVITY` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_INSTITUTION_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_COMPETITION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_AWARD_USE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_SERVICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_VISIT_TOO_SOON` | 409 Conflict |
| `ERR_NO_OPEN_SLOT` | 409 Conflict |
| `ERR_FUNDRAISING_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MIN_HOURS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PRORATION_FLOOR_NOT_MET` | 422 Unprocessable Entity |
| `ERR_COST_PER_MSY_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_AWARD_EXCEEDS_REQUEST` | 422 Unprocessable Entity |
| `ERR_MATCH_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ALLOWANCE_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_ALLOWANCE_EARNED_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_AWARD_BALANCE` | 422 Unprocessable Entity |
