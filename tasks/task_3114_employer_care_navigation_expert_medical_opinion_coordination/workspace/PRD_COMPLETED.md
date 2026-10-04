# Employer Care Navigation API — Product Requirements Document

## 1. Introduction

Employers increasingly buy a care-navigation benefit on top of their health plan: a service that helps covered employees and their families find the right care, in the right network, at the right price — and that backs clinical uncertainty with an expert medical opinion and billing confusion with professional advocacy. This document specifies the API that powers such a platform. It governs the full journey from the moment an employer's eligibility file is loaded, through a member's first navigation intake, to appointment steerage, medical-record retrieval, expert medical opinion coordination, claim repricing, billing negotiation, and the employer-facing utilization and savings reporting that justifies the program's per-employee-per-month fee.

The platform is operated by several segregated workforces — nurse navigators, care advocates, physician advisors, records specialists, expert reviewers, billing advocates, and health-plan administrators — each holding only the capabilities their function requires. Because members' medical records, claims, and consent decisions are involved, the system treats consent capture, segregation of duties between the records compiler and the expert reviewer, and exact-cent financial computation as first-class invariants rather than afterthoughts. Two aggregation families — the prospective cost-share estimate shown before care and the retrospective utilization report shown to the employer — are computed from the same underlying claims and appointment data, so the rules for rounding, chronological deductible application, and steerage attribution are spelled out exactly once and referenced everywhere.

The document is written for engineers implementing the service. Section 2 fixes the system-wide contract: authentication, envelope, pagination, validation ordering, concurrency control, and cross-cutting clinical and fiscal principles. Section 3 walks the business workflows in the order a member experiences them. Section 4 lists the HTTP endpoints, and Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The recognized role names, spelled exactly, are `PlatformAdmin`, `EmployerAdmin`, `Member`, `NurseNavigator`, `CareAdvocate`, `PhysicianAdvisor`, `RecordsSpecialist`, `ExpertReviewer`, `BillingAdvocate`, and `PlanAdministrator`. A request missing either header, or naming a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403).

The interpretation of `X-User-ID` differs by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` resource itself: ownership checks on any member-scoped resource compare the resource's `member_id` to `X-User-ID`, and — because dependents act through their subscriber — a `Member` caller whose `relationship` is not `SELF` may also act on resources owned by the dependent whose `subscriber_id` equals the caller's `id`. This dependent-proxy rule applies to every member-scoped check of §2.6 step two, writes included: a subscriber may revoke a dependent's consent, appeal a dependent's denial, accept or reject a dependent's settlement, deliver or withdraw a dependent's opinion case, or open a consent, navigation case, expert opinion case, or authorization on the dependent's behalf. A member attempting to touch another member's resources is rejected with `ERR_MEMBER_MISMATCH` (403). When `X-User-Role` is any of `PlatformAdmin`, `EmployerAdmin`, `NurseNavigator`, `CareAdvocate`, `PhysicianAdvisor`, `RecordsSpecialist`, `ExpertReviewer`, `BillingAdvocate`, or `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires attribution (for example `assigned_user_id` on a navigation case, `booked_by_user_id` on an appointment, `attached_by_user_id` on a bundle item, `compiler_user_id` and `reviewer_user_id` on an expert opinion case) but never compares it to an entity's `id` for ownership.

Role capabilities in brief: the `PlatformAdmin` loads employers and members, manages providers, quality snapshots, and coverage windows, deactivates and reactivates members, and drives the logical clock. The `EmployerAdmin` reads the employer roster and the utilization report. A `Member` grants and revokes consent, opens navigation cases and expert opinion cases, requests authorizations, accepts or rejects settlement proposals, appeals denials, withdraws opinion cases, and receives delivered recommendations. `NurseNavigator`, `CareAdvocate`, and `PhysicianAdvisor` share navigation-case work gated by discipline; navigators and advocates additionally book and manage appointments, and navigators may request authorizations. The `RecordsSpecialist` retrieves medical records and builds expert-opinion bundles. The `ExpertReviewer` claims reviews and writes recommendations — and is barred from reviewing a bundle they compiled. The `BillingAdvocate` opens billing cases and negotiates settlements. The `PlanAdministrator` imports and adjudicates claims and decides authorizations. Section 4 lists the authorized roles per endpoint.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

The platform never consults the wall clock for business decisions. All temporal logic — consent expiry, appointment due-ness, appeal windows — reads a single logical clock. Before any client sets it, the logical clock reads 2026-09-01T00:00:00Z. A `PlatformAdmin` advances it through a test-driving capability that accepts a target instant `to_iso8601` and returns the new `current_utc`. The capability sets the clock directly to the given instant without any monotonicity check — a target earlier than the current reading is accepted — and then performs the consent-expiry sweep described in §2.8. Readings of the logical clock are rendered as ISO 8601 UTC without fractional digits — the default reading is `2026-09-01T00:00:00Z`, and fields stamped with the logical clock time, such as `revoked_at` and `decided_at`, are rendered in that same form (the three-fractional-digit rule of §2.5 applies to `created_at`, `updated_at`, and `api_request_timestamp`, not to logical-clock readings). Reading a consent whose `expires_at` has been reached also expires it on the spot. Several endpoints compare the logical clock against stored timestamps; these comparisons are spelled out where the workflows are described in §3.

### 2.5. Common Resource Properties and Money Representation

Every persisted top-level resource — Employer, Member, CoverageWindow, Provider, QualitySnapshot, ConsentGrant, NavigationCase, Appointment, RecordRequest, ExpertOpinionCase, OpinionRecordItem, Claim, BillingCase, PlanAuthorization — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits; `updated_at`, refreshed on every mutation; and `version`, an integer that starts at 1 at creation and is incremented on every mutation. One resource deviates: the ProviderMatch returned by the provider-matching capability is an ephemeral computed view, never persisted — it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

All monetary amounts are integer cents — `pepm_fee_cents`, `avg_in_out_cost_delta_cents`, `deductible_limit_cents`, `oop_max_cents`, `billed_amount_cents`, `allowed_amount_cents`, and their computed counterparts. Where a calculation produces a fractional cent, the result is rounded half-up to whole cents; where a score calculation produces a fractional score, the result is rounded half-up to two decimal places. The rounding order matters and is pinned per calculation in §3: in particular, claim repricing rounds each line to whole cents before summing, never the reverse.

### 2.6. Validation Order and Nested Resource Resolution

Every request passes through a fixed pipeline of checks, and the order is part of the contract. First, authentication: the headers must be present and the role declared (else `ERR_UNAUTHENTICATED`). Second, authorization: the role must be permitted on the endpoint (else `ERR_UNAUTHORIZED_ROLE`), and an entity-backed `Member` caller may only touch their own resources or those of their dependents (else `ERR_MEMBER_MISMATCH`). Third, request shape: required fields present, types and enum values valid, conditional inputs supplied (else `ERR_INVALID_REQUEST`). Fourth, reference resolution: every identifier in the path and body must resolve to an existing resource, validated left to right — for example, a request naming an employer and a member under it rejects with `ERR_NOT_FOUND` (404) on the employer before the member is even looked up. Fifth, member eligibility: member-scoped creations require an `ACTIVE` member (else `ERR_MEMBER_INELIGIBLE`). Sixth, state-machine legality: the target entity must be in a valid from-state (else `ERR_INVALID_STATE` or the more specific state error the workflow declares). Only after all of these do business rules run — consent gates, uniqueness constraints, capacity limits, fiscal guards, temporal windows — each at the priority stated in §3 where the rule lives. Optimistic-concurrency checks come last, evaluated after state checks and before any mutation: a stale `expected_member_version` or `expected_opinion_version` is rejected with `ERR_STALE_VERSION` (412). The lone exception is the opinion-submission staleness check of §2.7: because that rejection protects the reviewer from overwriting a superseded draft regardless of the case's current state, the `expected_opinion_version` check on submit-recommendation is evaluated before the state-machine check, so a submission carrying a mismatched `expected_opinion_version` is rejected with `ERR_STALE_VERSION` (412) even when the case has already left `IN_REVIEW`.

### 2.7. Optimistic Concurrency Control

Two write operations mutate a parent aggregate in ways that legitimately supersede an earlier state, and both are guarded by optimistic concurrency control so that a client acting on a stale view cannot silently overwrite a change it never observed.

Creating a coverage window for a member must carry `expected_member_version`, equal to the member's current `version` as last read by the client. Because opening an open-ended window auto-closes the member's prior open window and advances the member's `version`, a creation request carrying an `expected_member_version` below the member's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's view of the member's coverage is stale because an earlier window creation has already advanced the aggregate.

Submitting a recommendation on an expert opinion case must carry `expected_opinion_version`, equal to the case's current `version` as last read by the reviewer. Because each submission supersedes the prior draft and advances the case's `version`, a submission carrying an `expected_opinion_version` that does not match the case's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the reviewer from overwriting a draft superseded by one they have not observed. Endpoints not named here do not take a version field.

### 2.8. Consent as a Cross-Cutting Gate

Members control what the platform may do on their behalf through consent grants. A `ConsentGrant` has a `scope` drawn from `RECORD_RETRIEVAL`, `APPOINTMENT_BOOKING`, `EMO_REVIEW`, and `BILLING_ADVOCACY`, an `expires_at` datetime, and a `status` of `ACTIVE`, `REVOKED`, or `EXPIRED`. Four operations are consent-gated: booking or rescheduling an appointment requires an `ACTIVE` `APPOINTMENT_BOOKING` grant; creating or retrying a record request requires an `ACTIVE` `RECORD_RETRIEVAL` grant; opening or compiling an expert opinion case requires an `ACTIVE` `EMO_REVIEW` grant; and opening a billing case requires an `ACTIVE` `BILLING_ADVOCACY` grant. Each gate fails with `ERR_CONSENT_REQUIRED` (409). A member may hold at most one `ACTIVE` grant per scope; a second grant for the same scope is rejected with `ERR_CONSENT_ALREADY_ACTIVE` (409).

Expiry is driven by the logical clock: whenever the clock advances — and whenever a consent is read — any grant whose `expires_at` is at or before the current logical time transitions to `EXPIRED` (the boundary is inclusive: an `expires_at` exactly equal to now expires the grant). Capturing a consent whose `expires_at` is already at or before the current logical time therefore produces a grant that is born `ACTIVE` and immediately transitions to `EXPIRED` within the same request. A member's consents can be listed with optional `scope` and `status` filters. Revocation and expiry share a cascade, detailed in §3.5: the loss of `RECORD_RETRIEVAL` consent cancels the member's pending record requests, which can block expert opinion cases awaiting records, which in turn escalates the linked navigation case.

### 2.9. Segregation of Duties and Assignment Binding

Three workflows bind a case to the specific operator who performed an earlier step, and one workflow forbids the same operator from performing two steps. A navigation case in progress records its worker in `assigned_user_id`, and only that operator may resolve it (else `ERR_NOT_ASSIGNED_NAVIGATOR`). An expert opinion case records the records specialist who compiled the bundle in `compiler_user_id`, and only that operator may submit the bundle for review (else `ERR_NOT_ASSIGNED_COMPILER`); it records the reviewer who claimed the review in `reviewer_user_id`, and only that reviewer may request changes or submit a recommendation (else `ERR_NOT_ASSIGNED_REVIEWER`). Finally, the reviewer who claims a case must not be the same operator recorded as its compiler — a claim-review attempt where `X-User-ID` equals `compiler_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Starting work on a navigation case is additionally gated by discipline: the acting role's discipline must match the case's `routed_discipline`, else `ERR_DISCIPLINE_MISMATCH` (403).

### 2.10. Member Eligibility as a Global Precondition

A member whose `eligibility_status` is not `ACTIVE` is frozen: no new consents, navigation cases, appointments, record requests, expert opinion cases, billing cases, or authorizations may be created for them. Each such attempt is rejected with `ERR_MEMBER_INELIGIBLE` (409). Deactivation and reactivation are `PlatformAdmin`-only operations and each advances the member's `version`.

## 3. Business Logic & Workflows

### 3.1. Loading the Employer Book of Business

Everything begins with the employer. A `PlatformAdmin` registers an `Employer` with its legal `name`, the negotiated `pepm_fee_cents` navigation fee, the employer-provided `avg_in_out_cost_delta_cents` — the average cost difference between an in-network and an out-of-network appointment, used later for steerage savings attribution — and the `emo_benefit_enabled` flag indicating whether the employer sponsors the expert medical opinion benefit. An expert opinion case may only be opened for a member whose employer has `emo_benefit_enabled` set.

Members arrive through the employer's eligibility file, and each loaded member records its owning employer in `employer_id`. Loading a member requires `full_name`, `date_of_birth`, a `relationship` of `SELF`, `SPOUSE`, or `CHILD`, an `external_member_ref` from the file, and the plan-feed values `deductible_limit_cents` and `oop_max_cents`. The `external_member_ref` must be unique within the employer; a duplicate load is rejected with `ERR_DUPLICATE_MEMBER_REF` (409). A dependent — any member whose `relationship` is not `SELF` — must additionally carry `subscriber_id` naming the subscriber member they belong to; a `SELF` member carries none. The `subscriber_id` must resolve to an existing member (else `ERR_NOT_FOUND`); the platform does not require the subscriber to belong to the same employer. Supplying a dependent without a subscriber, or a `CLINICAL` intake without `acuity`, or a `COST` intake without `estimated_cost_cents`, or a denial without `denial_reason`, are all malformed requests rejected with `ERR_INVALID_REQUEST` (400) — the shape check runs before any reference resolution. A freshly loaded member starts with `eligibility_status` `ACTIVE` and both accumulators — `deductible_used_cents` and `oop_used_cents` — at zero. A `PlatformAdmin` may later deactivate a member, moving `ACTIVE` to `INACTIVE`, or reactivate them back; each transition bumps the member's `version` by one, requires the member to currently be in the opposite state (deactivating a non-`ACTIVE` member or reactivating a non-`INACTIVE` one is rejected with `ERR_INVALID_STATE`), and deactivation is what arms the eligibility freeze of §2.10.

Coverage over time is tracked by `CoverageWindow` records: each carries a `coverage_tier` of `EMPLOYEE_ONLY`, `EMPLOYEE_SPOUSE`, `EMPLOYEE_CHILDREN`, or `FAMILY`, an inclusive `effective_start` date, and an `effective_end` date that is null for an open-ended window. Windows of a member use closed-interval semantics: a new window whose `[effective_start, effective_end]` shares even one day with an existing window of the same member is rejected with `ERR_COVERAGE_OVERLAP` (409), while pure contiguity — an existing window ending the day before the new one begins — is allowed. The overlap check runs before the optimistic-concurrency check of §2.7. One overlap is exempted: an open-ended new window may overlap the member's prior `OPEN` window, which it supersedes automatically — the prior window's `effective_end` is set to the day before the new window's `effective_start`, its `status` becomes `CLOSED`, and the member's `version` increments because the supersede mutates the member aggregate (this is why window creation is OCC-guarded per §2.7). The supersede fires only when the new window starts strictly after the prior window's `effective_start`; an open-ended window whose `effective_start` is on or before the prior window's start leaves the prior window untouched and simply coexists as a second `OPEN` window. A `PlatformAdmin` may also close a window early by terminating it with a `terminated_on` date, which must not precede the window's `effective_start` (else `ERR_INVALID_REQUEST`); terminating a window that is not `OPEN` is rejected with `ERR_WINDOW_NOT_OPEN` (409), and a successful termination records `terminated_on` as the window's `effective_end` and moves it to `CLOSED`. Coverage windows of a member can be listed with an optional `status` filter (a value outside `OPEN`/`CLOSED` is `ERR_INVALID_REQUEST`); members of an employer can be listed with optional `eligibility_status` and `relationship` filters (a value outside the corresponding enum is `ERR_INVALID_REQUEST`); a member's dependents can be listed via the subscriber relationship.

### 3.2. Provider Network and Claims-Derived Quality

Providers are registered by a `PlatformAdmin` with a practice `name`, a `specialty` code such as `CARDIOLOGY`, and a `network_status` of `IN_NETWORK` or `OUT_OF_NETWORK`. Quality is measured from claims data: a `PlatformAdmin` publishes a `QualitySnapshot` for a provider giving the measurement window (`period_start`, `period_end`), three component scores — `outcome_score`, `cost_efficiency_score`, and `access_score`, each on a 0–100 scale — and the `claims_volume` behind the measurement. Only one snapshot may exist per provider and `period_start`; a duplicate is rejected with `ERR_DUPLICATE_SNAPSHOT` (409).

On publication the server computes the snapshot's `composite_quality_score`. The raw score is a weighted blend: half the outcome score, three-tenths the cost-efficiency score, and one-fifth the access score. When the snapshot is backed by at least thirty adjudicated claims — the full-confidence volume threshold, and exactly thirty qualifies — the composite equals the raw blend. Below that volume, the score is shrunk toward the network mean of 70.0 in proportion to the evidence: the composite is the claims volume divided by thirty, times the raw blend, plus one minus that fraction, times 70.0. The result is rounded half-up to two decimal places.

Members and navigation staff can request a ranked provider match list for a specialty. The candidate set is every provider whose `specialty` equals the requested one and who has at least one quality snapshot; each candidate is represented by its snapshot with the latest `period_end`. Each candidate's `match_score` is its `composite_quality_score` multiplied by a network factor — 1.0 for an `IN_NETWORK` provider, 0.8 for an `OUT_OF_NETWORK` one — rounded half-up to two decimal places. Matches are ordered by `match_score` descending; ties break first by the latest snapshot's `period_end` descending, then by the provider's `created_at` ascending (never by id). Each returned `ProviderMatch` exposes `provider_id`, `provider_name`, `specialty`, `network_status`, `composite_quality_score`, `network_factor`, `match_score`, and its 1-based `rank`. If the candidate set is empty, the request is rejected with `ERR_NO_PROVIDER_MATCH` (422).

### 3.3. Navigation Intake, Routing, and Escalation

When a member or a navigator opens a navigation case, the intake records the `question_type` — `CLINICAL`, `BENEFIT`, or `COST` — plus the conditional inputs: `acuity` (`LOW`, `MEDIUM`, or `HIGH`) is required exactly when the question is `CLINICAL`, and `estimated_cost_cents` is required exactly when the question is `COST`. A conditional input that does not apply is not stored: `acuity` is null unless the question is `CLINICAL`, and `estimated_cost_cents` is null unless the question is `COST`. The case is born in `ROUTED` status with its `routed_discipline` computed at creation. Clinical questions route to a `PHYSICIAN` when `acuity` is `HIGH`, and otherwise to a `PHYSICIAN` when the member's `relationship` is `CHILD` — children always see a physician — and to a `NURSE` for everyone else. Benefit questions always route to an `ADVOCATE`. Cost questions route to a `NURSE` when the estimated cost is at least 500000 cents — exactly five thousand dollars qualifies, since the comparison is inclusive — and to an `ADVOCATE` below that. Routing is integer arithmetic on cents with no rounding.

Work begins when a navigator of the matching discipline starts the case: a `NURSE` routing wants a `NurseNavigator`, an `ADVOCATE` routing a `CareAdvocate`, a `PHYSICIAN` routing a `PhysicianAdvisor`; a mismatch is rejected with `ERR_DISCIPLINE_MISMATCH`. Starting moves the case from `ROUTED` — or from `ESCALATED` after an escalation, again discipline-checked against the escalated routing — to `IN_PROGRESS` and stamps `assigned_user_id` with the caller's `X-User-ID`. Any navigator working an in-progress case may escalate it: the case moves to `ESCALATED`, its `escalation_count` increases by one, its `assigned_user_id` is cleared, and its `routed_discipline` climbs one level — an `ADVOCATE` case becomes a `NURSE` case, a `NURSE` case becomes a `PHYSICIAN` case, and a `PHYSICIAN` case stays a `PHYSICIAN` case (the top of the ladder is a no-op). The same escalation also fires automatically, as a system cascade, when a linked expert opinion case becomes blocked on records or on authorization — but only if the navigation case is currently `IN_PROGRESS`; already-escalated or terminal cases are left untouched. Only the operator recorded in `assigned_user_id` may resolve an in-progress case, moving it to `RESOLVED` (anyone else hears `ERR_NOT_ASSIGNED_NAVIGATOR`), and any navigation-discipline role may then close it, moving `RESOLVED` to `CLOSED`. From a case, readers can also list the appointments it steered and the expert opinion cases it originated.

### 3.4. Booking Appointments and Steering to Network

With an `ACTIVE` `APPOINTMENT_BOOKING` consent in place, a `NurseNavigator` or `CareAdvocate` books an appointment on the member's behalf, supplying the `provider_id`, the `slot_start` and `slot_end` datetimes, optionally the originating `navigation_case_id` (the steerage attribution link), and optionally `redirected_from_out_of_network` — true when the member originally asked for an out-of-network provider and navigation steered them to this in-network booking; it defaults to false. The booking is born `BOOKED` with `late_cancel` initially false, records `booked_by_user_id` from the caller, and increments the provider's occupancy for that day — occupancy is not stored on the provider but derived on demand as the count of the provider's `BOOKED` appointments whose `slot_start` falls on that UTC calendar date.

Slots are half-open intervals on a single provider: a new `[slot_start, slot_end)` conflicts with an existing `BOOKED` slot when the new start is before the existing end and the existing start is before the new end — pure adjacency, where one slot's end equals the other's start, is allowed. Overlaps are rejected with `ERR_SLOT_CONFLICT` (409). Independently, a provider takes at most eight `BOOKED` appointments per UTC calendar date of the slot's start: the eighth booking succeeds and the ninth is rejected with `ERR_PROVIDER_DAY_CAPACITY` (422).

A `BOOKED` appointment may be rescheduled by a navigator or advocate to a new `slot_start` and `slot_end`; rescheduling re-checks the `APPOINTMENT_BOOKING` consent gate, both the overlap and the daily-capacity checks run again against the new slot with the appointment itself excluded from both counts, and a successful reschedule keeps the appointment `BOOKED` while incrementing its `version`. Cancellation — by a navigator, advocate, or the member — moves the appointment to `CANCELLED`, computes `late_cancel` as true exactly when the logical clock has reached the `slot_start` at cancellation time, and decrements the provider-day occupancy by one, so that a book followed by a cancel leaves occupancy unchanged. A member cancelling their own appointment is not consent-gated; the consent gate applies only to booking and rescheduling. Once the logical clock has reached the slot's end, a navigator or advocate completes the appointment (`COMPLETED`); completing before `slot_end` is rejected with `ERR_APPOINTMENT_NOT_DUE` (409). Marking a no-show is stricter: it requires the logical clock to be strictly past `slot_end`, moving the appointment to `NO_SHOW`, with the same `ERR_APPOINTMENT_NOT_DUE` rejection at or before the boundary. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal. Appointments can be listed per member, per provider, or per originating navigation case, with an optional `status` filter.

### 3.5. Retrieving Records and the Consent Cascade

Medical-record retrieval is the records specialist's domain and the origin of the platform's deepest cascade. With an `ACTIVE` `RECORD_RETRIEVAL` consent, a `RecordsSpecialist` creates a `RecordRequest` naming the custodian `provider_id`; the request is born `REQUESTED`. A request can be marked received with a `record_pages` count of at least one (a missing or non-positive count is `ERR_INVALID_REQUEST`), moving it to `RECEIVED` and recomputing `attached_received_count` on every expert opinion case whose bundle references the request. It can be marked failed, moving to `FAILED`; and a failed request can be retried, moving back to `REQUESTED` — but only while `retry_count` is below two, so a third retry is rejected with `ERR_RETRY_EXHAUSTED` (422), and only while the member still holds an `ACTIVE` `RECORD_RETRIEVAL` consent (else `ERR_CONSENT_REQUIRED`). Each retry increments `retry_count`.

A pending request can be cancelled directly by a records specialist, or automatically by the consent cascade: when the member revokes their `RECORD_RETRIEVAL` consent — which stamps `revoked_at` with the logical clock time and moves the grant to `REVOKED` — or when that consent expires, every one of the member's requests still in `REQUESTED` moves to `CANCELLED`. Requests already `RECEIVED` or `FAILED` are untouched. Revoking a consent one does not own is rejected with `ERR_MEMBER_MISMATCH`; revoking one not `ACTIVE` with `ERR_INVALID_STATE`. Cancellation of a pending request then propagates: for each of the member's expert opinion cases sitting in `RECORDS_COLLECTION` whose `attached_received_count` has fallen below three and which no longer has any request in `REQUESTED`, the case moves to `RECORDS_BLOCKED` — and that blockage escalates the linked navigation case per §3.3. Record requests can be listed globally (optionally filtered by `provider_id` and `status`) or per member.

### 3.6. The Expert Medical Opinion Pipeline

An expert medical opinion case is opened by the member or a records specialist, requires an `ACTIVE` `EMO_REVIEW` consent, an employer with the benefit enabled (a member whose employer lacks the benefit is rejected with `ERR_INVALID_REQUEST`), and a `condition_summary` describing the clinical question — the checks run in the pinned order of §2.6, eligibility before the benefit check before the consent gate; it may optionally link back to an originating `navigation_case_id`. The case is born in `INTAKE` and waits for two things: records, and plan authorization.

Records flow in as bundle items: a records specialist attaches a record request by its `record_request_id`, creating an `OpinionRecordItem` stamped with `attached_by_user_id` and linked to the owning case through its `opinion_id`. Attachment accepts a case in any non-terminal state — only the record-side conditions below are enforced. The attached request must belong to the opinion's member, must be in `RECEIVED` status, and must not already be attached to another expert opinion case that is still live — that is, not in `DELIVERED` or `WITHDRAWN`; any violation — including a `record_request_id` that resolves to nothing — is rejected with `ERR_RECORD_NOT_READY` (409). The first successful attachment moves the case from `INTAKE` to `RECORDS_COLLECTION` (attachments to a case already past `INTAKE` leave its status unchanged). Bundle items can be listed per opinion case or per record request. The case's `attached_received_count` tracks how many of its attached requests are currently `RECEIVED`, recomputed whenever a referenced request is received.

With at least one record attached, a records specialist compiles the bundle, moving the case to `COMPILING` and stamping `compiler_user_id`. Compilation requires the member's `EMO_REVIEW` consent to still be `ACTIVE`. When the bundle is ready, the same operator who compiled it submits it for review — anyone else is rejected with `ERR_NOT_ASSIGNED_COMPILER`. Submission is gated twice: the case must have `attached_received_count` of at least three (else `ERR_RECORDS_INSUFFICIENT`, 422), and the member must hold a plan authorization whose `service_code` is `EXPERT_MEDICAL_OPINION` in `APPROVED` status (else `ERR_AUTHORIZATION_REQUIRED`, 409). Passing both moves the case to `READY_FOR_REVIEW`.

An `ExpertReviewer` then claims the review — anyone recorded as the case's `compiler_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — moving the case to `IN_REVIEW` and stamping `reviewer_user_id`. From `IN_REVIEW`, that reviewer either sends the bundle back, moving the case to `CHANGES_REQUESTED` — from which a records specialist compiles it again, the revision loop cycling through `COMPILING` and `READY_FOR_REVIEW` — or writes the recommendation. A submission carries the `recommendation_text` and the OCC field `expected_opinion_version` per §2.7; a stale version is rejected with `ERR_STALE_VERSION` (412). A successful submission stores the text, increments `recommendation_version` by one (superseding the prior draft), increments the case's `version`, and moves the case to `RECOMMENDATION_SUBMITTED`. Review actions by anyone other than the recorded reviewer are rejected with `ERR_NOT_ASSIGNED_REVIEWER`. Delivery belongs to the member: the case's own member takes delivery, moving the case to its terminal `DELIVERED` state; a different member is rejected with `ERR_MEMBER_MISMATCH`. At any point before delivery, the member — or a `PlatformAdmin` — may withdraw the case, moving it to terminal `WITHDRAWN` from any non-terminal state and releasing the compiler and reviewer assignments (both fields nulled).

Two blockers can interrupt the pipeline, both delivered as cascades. If the member's `EXPERT_MEDICAL_OPINION` authorization is denied while the case awaits one in `INTAKE`, the case moves to `AUTH_BLOCKED`; a later approval moves it back to `INTAKE`. If records dry up per §3.5, a case in `RECORDS_COLLECTION` moves to `RECORDS_BLOCKED`; creating any new record request for the member while the case is blocked moves it back to `RECORDS_COLLECTION`. Either blockage escalates the linked navigation case, as described in §3.3.

### 3.7. Claims, Adjudication, and the Member's Accumulators

Claims arrive from the health plan feed through a `PlanAdministrator`, who supplies the `member_id`, `provider_id`, `service_date`, `billed_amount_cents`, `allowed_amount_cents`, and the `lines` array — each line carrying a `line_code`, a `billed_cents` amount, a `schedule_rate`, and an `error_flag` of `NONE`, `DUPLICATE`, or `UPCODING`. The claim is born `RECEIVED` with its `error_line_count` computed at creation as the number of lines whose error flag is not `NONE`; `repriced_total_cents`, `deductible_applied_cents`, and `member_responsibility_cents` remain null until adjudication. Claim import is a plan-feed operation and is not gated by the member's `eligibility_status`: claims for an `INACTIVE` member are accepted and may be adjudicated and voided normally, and §2.10's freeze does not name claims.

Adjudication is a pinned two-step computation. Step one, repricing: walk the lines in array order. A `DUPLICATE` line reprices to zero cents. An `UPCODING` line reprices to its `billed_cents` multiplied by its `schedule_rate`, rounded half-up to whole cents. A clean line keeps its `billed_cents`. The claim's `repriced_total_cents` is the sum of the per-line rounded amounts — each line is rounded first and then summed, never summed unrounded and rounded once, because the two orders can disagree by a cent. Step two, cost share: claims of a member apply against the deductible in `service_date` ascending order, ties broken by the claim's `created_at` ascending (never by id). The remaining deductible is the member's `deductible_limit_cents` minus `deductible_used_cents`, floored at zero; this claim's `deductible_applied_cents` is the smaller of that remainder and the claim's `allowed_amount_cents` — a member whose used amount already equals the limit exactly applies nothing. The coinsurance is one-fifth of the allowed amount left after the deductible portion, rounded half-up to whole cents, and `member_responsibility_cents` is the deductible portion plus the coinsurance. Adjudicated responsibility is factual: it is not capped by the member's `oop_max_cents` — the cap applies only to the prospective estimate below. Adjudication then adds `deductible_applied_cents` to the member's `deductible_used_cents`, adds `member_responsibility_cents` to `oop_used_cents`, and bumps the member's `version`. Adjudicating a claim not in `RECEIVED` is rejected with `ERR_CLAIM_ALREADY_ADJUDICATED` (409).

Voiding reverses adjudication exactly: the same amounts are subtracted from the member's two accumulators, the member's `version` bumps again, and the claim moves to terminal `VOID`. Voiding also cascades to billing: any linked billing case in `OPENED`, `ERROR_IDENTIFIED`, `NEGOTIATING`, or `SETTLEMENT_PROPOSED` moves to `VOIDED` with its savings fields nulled, while cases already `RESOLVED_ACCEPTED`, `RESOLVED_NO_CHANGE`, or `CLOSED` are left unchanged. Claims can be listed globally — with optional `provider_id` and `status` filters — or per member.

Members and their advocates can ask for a prospective cost-share estimate before receiving care, supplying the target `provider_id` and an `allowed_amount_cents`. The estimate reads the persisted accumulators only and never mutates them. For an `OUT_OF_NETWORK` provider the member's responsibility is simply two-fifths of the allowed amount, rounded half-up to whole cents — no deductible offset, no out-of-pocket cap. For an `IN_NETWORK` provider the estimate mirrors adjudication: the deductible portion is the smaller of the remaining deductible and the allowed amount; the coinsurance portion is one-fifth of the remainder, rounded half-up; the uncapped total is their sum; and the final `member_responsibility_cents` is the smaller of that uncapped total and the room left under the member's `oop_max_cents` (the maximum minus `oop_used_cents`, floored at zero). The response reports `member_responsibility_cents`, `deductible_portion_cents`, `coinsurance_portion_cents`, and an `oop_capped` flag that is true exactly when the cap reduced the uncapped total.

### 3.8. Billing Advocacy and Negotiated Settlement

When a member disputes a claim, a `BillingAdvocate` — gated by the member's `ACTIVE` `BILLING_ADVOCACY` consent — opens a `BillingCase` naming the disputed `claim_id`; the case is born `OPENED`. The claim must resolve and belong to the path's member — a claim that does not exist or whose `member_id` differs is rejected with `ERR_NOT_FOUND` (404) — and this reference check precedes the eligibility and consent gates. Error identification requires the linked claim to be `ADJUDICATED` (else `ERR_CLAIM_NOT_ADJUDICATED`, 409) and to carry at least one error-flagged line (else `ERR_NO_LINE_ERRORS`, 422). Identifying errors moves the case to `ERROR_IDENTIFIED` and computes the provisional savings view: `provisional_savings_cents` is the claim's `billed_amount_cents` minus its `repriced_total_cents` — the system-priced fair-value view of what the member should save.

Negotiation proceeds in rounds. The advocate proposes a settlement by naming a `counter_offer_cents`, which must be strictly below the claim's `billed_amount_cents` — a settlement at or above billed saves nothing and is rejected with `ERR_SETTLEMENT_EXCEEDS_BILLED` (422). A case may carry at most three proposals; a fourth is rejected with `ERR_NEGOTIATION_ROUND_EXCEEDED` (422). Each proposal increments `proposal_count` and moves the case to `SETTLEMENT_PROPOSED`, whether from `ERROR_IDENTIFIED` or, cyclically, from `NEGOTIATING`. The member then decides. Accepting moves the case to `RESOLVED_ACCEPTED`, copies the accepted `counter_offer_cents` into `settled_amount_cents`, and computes the final, negotiated-outcome savings view: `final_savings_cents` is the claim's `billed_amount_cents` minus `settled_amount_cents`. The provisional and final views routinely differ for identical claim data whenever the negotiated settlement differs from the system repricing. Rejecting moves the case back to `NEGOTIATING`, retaining the refused `counter_offer_cents` as the last rejected offer. Only the case's own member may accept or reject (else `ERR_MEMBER_MISMATCH`). Alternatively, the advocate may abandon a case in `NEGOTIATING`, moving it to `RESOLVED_NO_CHANGE` with `final_savings_cents` zero. Either resolved state can be closed by the advocate, moving the case to terminal `CLOSED`; and per §3.7, a voided claim voids the case, nulling its savings fields. Billing cases can be listed per member or per claim.

### 3.9. Plan Authorizations and the Appeal Window

Certain services require the health plan's prior authorization. A member or nurse navigator requests one by naming the `service_code` — `EXPERT_MEDICAL_OPINION`, `PROCEDURE`, or `IMAGING` — and the `units` requested, at least one. The authorization is born `REQUESTED`. A member may hold at most one non-terminal authorization per service code: an existing `REQUESTED` or `APPEALED` authorization blocks a new request for the same code with `ERR_DUPLICATE_AUTHORIZATION` (409).

A `PlanAdministrator` decides. Approval — of a `REQUESTED` or an `APPEALED` authorization alike — moves it to terminal `APPROVED` and stamps `decided_at` with the logical clock time (re-stamping it when approving an appealed authorization, overwriting the denial's stamp); when the approved service code is `EXPERT_MEDICAL_OPINION`, any of the member's expert opinion cases sitting in `AUTH_BLOCKED` return to `INTAKE`. Denial of a `REQUESTED` authorization requires a `denial_reason`, stamps `decided_at`, and moves it to `DENIED`; when the denied service code is `EXPERT_MEDICAL_OPINION`, the member's opinion cases waiting in `INTAKE` move to `AUTH_BLOCKED`, and that blockage escalates the linked navigation case per §3.3. The member may appeal a denial — only their own, else `ERR_MEMBER_MISMATCH` — moving the authorization to `APPEALED`, but only within thirty days of `decided_at` by the logical clock — the window is inclusive, so an appeal at the logical time exactly thirty days after `decided_at` still succeeds; an appeal after that window is rejected with `ERR_APPEAL_WINDOW_CLOSED` (422). A denied-again appeal is final: denying an `APPEALED` authorization moves it to terminal `DENIED_FINAL`, re-stamps `decided_at`, and fires the same authorization-block cascade for the member's `INTAKE` opinion cases. Authorizations can be listed per member with an optional `status` filter.

### 3.10. Employer Reporting: Utilization and Attributed Savings

The employer-facing utilization report is a computed read over everything above, returned to an `EmployerAdmin` or `PlatformAdmin`. It reports `members_active`, the count of the employer's members whose `eligibility_status` is `ACTIVE`; `navigation_cases_total`, all navigation cases of the employer's members in any status; `navigation_cases_closed`, those in `CLOSED`; and `emos_delivered`, the count of expert opinion cases in `DELIVERED`.

Savings come in the two billing variants plus two steerage variants. `billing_savings_provisional_cents` sums `provisional_savings_cents` over the employer's billing cases in `ERROR_IDENTIFIED`, `NEGOTIATING`, `SETTLEMENT_PROPOSED`, `RESOLVED_ACCEPTED`, or `CLOSED` whose linked claim is not `VOID` — voided cases are excluded. `billing_savings_final_cents` sums `final_savings_cents` over cases in `RESOLVED_ACCEPTED` or `CLOSED` (a `RESOLVED_NO_CHANGE` case contributes zero). Steerage savings consider the base set of the employer members' appointments that are `BOOKED` or `COMPLETED`, with an in-network provider, and booked through a navigation case. The naive view, `steerage_naive_cents`, credits every such appointment: the count of the base set times the employer's `avg_in_out_cost_delta_cents`. The counterfactual view, `steerage_counterfactual_cents`, credits only genuine redirections: the count of base-set appointments with `redirected_from_out_of_network` true, times the same delta. The two differ whenever any in-network navigation-booked appointment was not a redirection, and both are reported side by side. Finally, `total_attributed_savings_cents` is the sum of `billing_savings_final_cents` and `steerage_counterfactual_cents`. All report figures are integer cents.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act on an existing resource, and all reads, return `200 OK`. The request and response shapes for each endpoint are defined by the workflows in §3; the table below is the routing and authorization contract only. A request to a path no route matches — or a method the matched path does not support — is rejected with `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps consent expiry | PlatformAdmin |
| POST | `/care/employers` | Create an employer account | PlatformAdmin |
| GET | `/care/employers/{id}` | Get an employer | PlatformAdmin, EmployerAdmin |
| GET | `/care/employers/{id}/members` | List members of an employer | PlatformAdmin, EmployerAdmin |
| GET | `/care/employers/{id}/utilization-report` | Utilization, steerage, and savings report | EmployerAdmin, PlatformAdmin |
| POST | `/care/employers/{id}/members` | Load a member from the eligibility file | PlatformAdmin |
| GET | `/care/members/{id}` | Get a member | PlatformAdmin, EmployerAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor, RecordsSpecialist, ExpertReviewer, BillingAdvocate, PlanAdministrator |
| GET | `/care/members/{id}/dependents` | List a member's dependents | PlatformAdmin, EmployerAdmin, Member, NurseNavigator, CareAdvocate |
| POST | `/care/members/{id}/deactivate` | Deactivate member eligibility | PlatformAdmin |
| POST | `/care/members/{id}/reactivate` | Reactivate member eligibility | PlatformAdmin |
| POST | `/care/members/{id}/coverage-windows` | Open a coverage window (supersedes prior open window when open-ended; OCC) | PlatformAdmin |
| GET | `/care/members/{id}/coverage-windows` | List a member's coverage windows | PlatformAdmin, EmployerAdmin, Member, CareAdvocate |
| POST | `/care/coverage-windows/{id}/terminate` | Close a coverage window early | PlatformAdmin |
| POST | `/care/providers` | Register a provider | PlatformAdmin |
| GET | `/care/providers/{id}` | Get a provider | PlatformAdmin, EmployerAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/providers/{id}/quality-snapshots` | Publish a claims-derived quality snapshot | PlatformAdmin |
| GET | `/care/providers/{id}/quality-snapshots` | List a provider's quality snapshots | PlatformAdmin, NurseNavigator, CareAdvocate, PhysicianAdvisor, Member |
| GET | `/care/members/{id}/provider-matches` | Ranked provider match list for a specialty | Member, NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/members/{id}/consents` | Capture member consent for a scope | Member |
| GET | `/care/members/{id}/consents` | List member consents | Member, PlatformAdmin, NurseNavigator, CareAdvocate, RecordsSpecialist, BillingAdvocate |
| POST | `/care/consents/{id}/revoke` | Revoke a consent (cascades to pending record requests) | Member |
| POST | `/care/members/{id}/navigation-cases` | Open a navigation intake (routing computed) | Member, NurseNavigator, CareAdvocate |
| GET | `/care/navigation-cases/{id}` | Get a navigation case | PlatformAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor |
| GET | `/care/members/{id}/navigation-cases` | List member navigation cases | PlatformAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/navigation-cases/{id}/start` | Start work on a routed/escalated case (discipline-gated) | NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/navigation-cases/{id}/escalate` | Escalate an in-progress case one discipline level | NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/navigation-cases/{id}/resolve` | Resolve an in-progress case (assigned navigator only) | NurseNavigator, CareAdvocate, PhysicianAdvisor |
| POST | `/care/navigation-cases/{id}/close` | Close a resolved case | NurseNavigator, CareAdvocate, PhysicianAdvisor |
| GET | `/care/navigation-cases/{id}/appointments` | List appointments steered by this case | PlatformAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor, EmployerAdmin |
| GET | `/care/navigation-cases/{id}/expert-opinions` | List expert opinions originating from this case | PlatformAdmin, Member, NurseNavigator, PhysicianAdvisor, RecordsSpecialist, ExpertReviewer |
| POST | `/care/members/{id}/appointments` | Book an appointment on the member's behalf (consent-gated) | NurseNavigator, CareAdvocate |
| GET | `/care/appointments/{id}` | Get an appointment | PlatformAdmin, Member, NurseNavigator, CareAdvocate, PhysicianAdvisor |
| GET | `/care/members/{id}/appointments` | List member appointments | PlatformAdmin, Member, NurseNavigator, CareAdvocate |
| GET | `/care/providers/{id}/appointments` | List provider appointments | PlatformAdmin, NurseNavigator, CareAdvocate |
| POST | `/care/appointments/{id}/reschedule` | Move a booked appointment to a new slot | NurseNavigator, CareAdvocate |
| POST | `/care/appointments/{id}/cancel` | Cancel a booked appointment | NurseNavigator, CareAdvocate, Member |
| POST | `/care/appointments/{id}/complete` | Complete a booked appointment once the slot has ended | NurseNavigator, CareAdvocate |
| POST | `/care/appointments/{id}/mark-no-show` | Mark a booked appointment no-show once the slot has passed | NurseNavigator, CareAdvocate |
| POST | `/care/members/{id}/record-requests` | Request medical records from a provider (consent-gated) | RecordsSpecialist |
| GET | `/care/record-requests/{id}` | Get a record request | PlatformAdmin, RecordsSpecialist, ExpertReviewer, Member |
| GET | `/care/record-requests` | List record requests, optionally by provider and status | PlatformAdmin, RecordsSpecialist |
| GET | `/care/members/{id}/record-requests` | List a member's record requests | PlatformAdmin, RecordsSpecialist, Member |
| POST | `/care/record-requests/{id}/receive` | Mark records received with a page count | RecordsSpecialist |
| POST | `/care/record-requests/{id}/fail` | Mark a record request failed | RecordsSpecialist |
| POST | `/care/record-requests/{id}/retry` | Retry a failed record request (max two retries) | RecordsSpecialist |
| POST | `/care/record-requests/{id}/cancel` | Cancel a pending record request | RecordsSpecialist |
| POST | `/care/members/{id}/expert-opinions` | Open an expert medical opinion case (consent- and benefit-gated) | Member, RecordsSpecialist |
| GET | `/care/expert-opinions/{id}` | Get an expert opinion case | PlatformAdmin, Member, RecordsSpecialist, ExpertReviewer, PhysicianAdvisor |
| GET | `/care/members/{id}/expert-opinions` | List member expert opinion cases | PlatformAdmin, Member, RecordsSpecialist, ExpertReviewer |
| POST | `/care/expert-opinions/{id}/attach-records` | Attach a received record request to the opinion bundle | RecordsSpecialist |
| GET | `/care/expert-opinions/{id}/record-items` | List opinion bundle items | PlatformAdmin, RecordsSpecialist, ExpertReviewer, Member |
| GET | `/care/record-requests/{id}/opinion-items` | List bundle items referencing a record request | PlatformAdmin, RecordsSpecialist |
| POST | `/care/expert-opinions/{id}/compile` | Compile the record bundle (sets compiler; revision re-entry) | RecordsSpecialist |
| POST | `/care/expert-opinions/{id}/submit-for-review` | Submit the compiled bundle for specialist review | RecordsSpecialist |
| POST | `/care/expert-opinions/{id}/claim-review` | Reviewer claims the case (reviewer must differ from compiler) | ExpertReviewer |
| POST | `/care/expert-opinions/{id}/request-changes` | Reviewer sends the bundle back for revision | ExpertReviewer |
| POST | `/care/expert-opinions/{id}/submit-recommendation` | Submit the written recommendation (OCC on case version) | ExpertReviewer |
| POST | `/care/expert-opinions/{id}/deliver` | Deliver the written recommendation to the member | Member |
| POST | `/care/expert-opinions/{id}/withdraw` | Withdraw a non-terminal opinion case | Member, PlatformAdmin |
| POST | `/care/claims` | Import a claim from the health plan feed | PlanAdministrator |
| GET | `/care/claims/{id}` | Get a claim | PlatformAdmin, PlanAdministrator, BillingAdvocate, Member |
| GET | `/care/claims` | List claims, optionally by provider and status | PlatformAdmin, PlanAdministrator, BillingAdvocate |
| GET | `/care/members/{id}/claims` | List member claims | PlatformAdmin, PlanAdministrator, BillingAdvocate, Member |
| POST | `/care/claims/{id}/adjudicate` | Adjudicate a claim (repricing then deductible application) | PlanAdministrator |
| POST | `/care/claims/{id}/void` | Void an adjudicated claim (reverses accumulators; voids open billing cases) | PlanAdministrator |
| POST | `/care/members/{id}/billing-cases` | Open a billing advocacy case on a claim (consent-gated) | BillingAdvocate |
| GET | `/care/billing-cases/{id}` | Get a billing case | PlatformAdmin, BillingAdvocate, Member |
| GET | `/care/members/{id}/billing-cases` | List member billing cases | PlatformAdmin, BillingAdvocate, Member |
| GET | `/care/claims/{id}/billing-cases` | List billing cases on a claim | PlatformAdmin, BillingAdvocate |
| POST | `/care/billing-cases/{id}/identify-errors` | Identify claim errors and compute provisional savings | BillingAdvocate |
| POST | `/care/billing-cases/{id}/propose-settlement` | Propose a negotiated amount (max three proposals) | BillingAdvocate |
| POST | `/care/billing-cases/{id}/accept-settlement` | Member accepts the proposed settlement | Member |
| POST | `/care/billing-cases/{id}/reject-settlement` | Member rejects the proposal (back to negotiation) | Member |
| POST | `/care/billing-cases/{id}/abandon` | Close negotiation with no change | BillingAdvocate |
| POST | `/care/billing-cases/{id}/close` | Close a resolved billing case | BillingAdvocate |
| POST | `/care/members/{id}/authorizations` | Request a plan authorization | Member, NurseNavigator |
| GET | `/care/authorizations/{id}` | Get an authorization | PlatformAdmin, PlanAdministrator, Member, NurseNavigator |
| GET | `/care/members/{id}/authorizations` | List member authorizations | PlatformAdmin, PlanAdministrator, Member, NurseNavigator |
| POST | `/care/authorizations/{id}/approve` | Approve a requested or appealed authorization | PlanAdministrator |
| POST | `/care/authorizations/{id}/deny` | Deny a requested or appealed authorization (cascades to opinion cases) | PlanAdministrator |
| POST | `/care/authorizations/{id}/appeal` | Member appeals a denial within thirty days | Member |
| GET | `/care/members/{id}/cost-share-estimate` | Prospective member cost share for a provider and allowed amount | Member, CareAdvocate, NurseNavigator, PlanAdministrator |

## 5. Error Code Catalogue

The trigger conditions for each error are defined where the corresponding rule lives in §2 and §3; this table is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_MEMBER_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_MEMBER_INELIGIBLE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_CONSENT_REQUIRED` | 409 |
| `ERR_CONSENT_ALREADY_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DISCIPLINE_MISMATCH` | 403 |
| `ERR_NOT_ASSIGNED_NAVIGATOR` | 403 |
| `ERR_NOT_ASSIGNED_REVIEWER` | 403 |
| `ERR_NOT_ASSIGNED_COMPILER` | 403 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_PROVIDER_DAY_CAPACITY` | 422 |
| `ERR_NO_PROVIDER_MATCH` | 422 |
| `ERR_DUPLICATE_SNAPSHOT` | 409 |
| `ERR_DUPLICATE_AUTHORIZATION` | 409 |
| `ERR_DUPLICATE_MEMBER_REF` | 409 |
| `ERR_RECORD_NOT_READY` | 409 |
| `ERR_RECORDS_INSUFFICIENT` | 422 |
| `ERR_AUTHORIZATION_REQUIRED` | 409 |
| `ERR_CLAIM_ALREADY_ADJUDICATED` | 409 |
| `ERR_CLAIM_NOT_ADJUDICATED` | 409 |
| `ERR_NO_LINE_ERRORS` | 422 |
| `ERR_SETTLEMENT_EXCEEDS_BILLED` | 422 |
| `ERR_NEGOTIATION_ROUND_EXCEEDED` | 422 |
| `ERR_APPOINTMENT_NOT_DUE` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_RETRY_EXHAUSTED` | 422 |
| `ERR_STALE_VERSION` | 412 |
