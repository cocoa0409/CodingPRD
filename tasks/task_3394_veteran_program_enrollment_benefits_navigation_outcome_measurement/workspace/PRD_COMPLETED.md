# Veteran Program Outcomes API — Product Requirements Document

## 1. Introduction

Veteran-serving nonprofits live or die by two questions: are we reaching the right veterans, and did their lives actually improve? This document specifies the Veteran Program Outcomes platform, a single REST API that runs the full arc of that mission — registering post-service injured veterans and their family support members, verifying eligibility against service era and injury connection, enrolling members into mental health, physical health, career counseling, and independence program tracks, and then measuring whether any of it worked. Along the way the platform assists with disability compensation and healthcare access claims through accredited representatives, routes members into intensive outpatient treatment through clinical partner sites, places them with employer partners, and brings them together at community engagement events with accessibility accommodations and travel support.

Two cross-cutting obligations shape every workflow below. First, **duplication avoidance**: donors and regulators demand that the organization not pay for services a member already receives from another veteran service organization, so external service records act as a standing guard on enrollment, claim, and referral creation. Second, **outcome measurement**: every completed enrollment spawns a schedule of wellbeing surveys, and those surveys feed an immutable donor report computed under a declared statistical methodology. All state is addressed under a single API mount, `/veteran-services`, and all temporal behavior is driven by a server-held logical clock so that eligibility windows, appeal deadlines, survey windows, and milestone gates are fully deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not name one of the declared roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller who is authenticated but whose role is not listed for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are exactly these nine: `PlatformAdmin`, `IntakeCoordinator`, `AccreditedRepresentative`, `BenefitsOfficer`, `ClinicalPartner`, `CareerCounselor`, `EventCoordinator`, `OutcomeAnalyst`, and `ProgramMember`.

Two roles are **entity-backed**. When `X-User-Role` is `ProgramMember`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403). A `ProgramMember` may read only their own member record, list only their own eligibility cases, and submit only surveys belonging to one of their own enrollments. When `X-User-Role` is `ClinicalPartner`, `X-User-ID` is the `id` of the `PartnerSite` the caller staffs; a referral transition is owned only when the referral's `partner_site_id` equals `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403).

The remaining seven roles — `PlatformAdmin`, `IntakeCoordinator`, `AccreditedRepresentative`, `BenefitsOfficer`, `CareerCounselor`, `EventCoordinator`, and `OutcomeAnalyst` — carry an opaque operator identifier not tied to any persisted entity. The server may record such an identifier (for example, a `BenefitsOfficer`'s `X-User-ID` is written onto claims and appeals as `decided_by_officer_id`, and is later consulted by the segregation-of-duties rule in §3.4), but it never compares these identifiers to any entity's `id` for ownership.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is request metadata taken from wall-clock time — the platform's only wall-clock read — and drives no temporal rule.
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

Beyond the domain catalogue of §5, three transport-level failures also use this envelope: a request to a path that does not exist is rejected with `ERR_NOT_FOUND` (HTTP 404), a request using a method the path does not support is rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server fault yields `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0, with a minimum of 0. A non-integer value, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are always sorted by `created_at` ascending, with ties broken by creation (insertion) order. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of returned rows is still below `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource exposes a server-minted `id` — a UUID with no type prefix — plus a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry `updated_at` (same format) and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource. Supplied datetimes are floored to second precision at ingestion, and a naive datetime (one carrying no offset) is read as UTC; because every stored timestamp is held at second precision, resource timestamps are always emitted with `.000` fractional digits. Two resources are deliberately leaner: an `Assessment` and a `DonorReport` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those two resources — assessments are append-only and donor reports are immutable once created, so there is nothing to version.

The topology is flat: every resource is addressed at its collection root under `/veteran-services`, and parentage is carried by foreign-key fields in request bodies (for example, an enrollment is created with a `member_id` and a `program_track_id` in its payload) rather than by deep URL nesting. Reverse lookups are served either by dedicated sub-resource list reads (such as a member's eligibility cases, external service records, claims, appeals of a claim, assessments of an enrollment, or surveys of an enrollment) or by filtered list reads on the flat collections.

### 2.5. The Logical Clock and the Clock Sweep

Apart from the request-metadata timestamp of §2.2, the platform never reads wall-clock time. A server-held **logical clock** supplies `created_at`, `updated_at`, and every temporal rule in this document — appeal deadlines, survey windows, milestone gates, treatment-window expiry, event cutoffs. At startup the clock is exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it through the test-driving capability that accepts a `to_iso8601` instant and replies with the resulting `current_utc`; the clock never falls back to wall-clock time on its own.

Every clock set runs the **full clock sweep** against the new time, in this fixed order:

1. Each `OutcomeSurvey` in `SCHEDULED` whose `window_open_at` is less than or equal to the clock moves to `OPEN`.
2. Each `OutcomeSurvey` in `OPEN` whose `window_close_at` is strictly before the clock moves to `EXPIRED`.
3. Each `BenefitsClaim` in `DECIDED` whose `decided_at` lies more than 97 days before the clock — that is, the 90-day appeal window plus a further 7-day close grace — moves to `CLOSED`.
4. Each `Referral` in `PENDING_MATCH` whose `treatment_start` is strictly before the clock moves to `EXPIRED`.
5. Each `EventRegistration` still in `CONFIRMED` whose event's `ends_at` is strictly before the clock moves to `NO_SHOW`; any travel award already granted is not clawed back.
6. Each `EventRegistration` still in `WAITLISTED` whose event's `starts_at` is strictly before the clock moves to `EXPIRED`.
7. Each `ExternalServiceRecord` in `ACTIVE` whose `end_date` is set and strictly before the clock moves to `CLOSED`; once closed, the record no longer counts toward any duplication-avoidance check.

Each transition the sweep performs is a mutation of the affected record, so its `version` increments by 1 and its `updated_at` refreshes under §2.4. All datetime comparisons are evaluated at second precision, and the boundary comparisons apply exactly as written above: survey opening uses "at or after", while survey expiry, claim closing, referral expiry, event no-show, waitlist expiry, and external-record closing all use "strictly after".

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent `Member`, because each of them silently supersedes an in-flight sibling record the client may never have seen.

- **Opening an eligibility case.** The request must carry `expected_member_version`, holding the `version` of the target `Member` as the client last observed it. If the member's current `version` has advanced since then, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a new case legitimately supersedes any existing `UNDER_REVIEW` or `PENDED` case for that member; the stale expected version marks the client's view of the member as out of date before such a blind supersede can happen.
- **Creating a clinical referral.** The request must likewise carry `expected_member_version` matching the target member's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a new referral supersedes the member's existing `PENDING_MATCH` referral.

No other endpoint accepts or requires a version field.

### 2.7. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a single fixed priority order, and the **first** failure wins. The order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the nine declared roles — otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Request well-formedness.** All required input fields are present, enum values fall within their declared sets, integer ranges are honored (domain scores 0 through 10, Likert items 1 through 5, disability rating steps of 10 within 0 through 100, non-negative amounts), datetime fields parse, `treatment_end` is strictly after `treatment_start`, `ends_at` is strictly after `starts_at`, `period_end` is greater than or equal to `period_start`, and a supplied `track_weights` map sums to exactly 1.0 — otherwise `ERR_INVALID_REQUEST` (HTTP 400). This check runs only on endpoints with a request body. One field-presence rule is deliberately entity-dependent and runs later: on the claim-decision endpoint alone, the requirement that a `GRANTED` outcome carry `decided_rating_pct` is evaluated immediately after the claim's existence check (priority 4) and before the state precondition (priority 7), so a missing claim masks a missing rating and a missing rating masks a wrong state.
3. **Role authorization.** The authenticated role appears in the endpoint's role list — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
4. **Existence.** Every identifier in the path resolves to an existing resource, validated left to right (a member before its case, an enrollment before its survey, a claim before its appeal); then body foreign keys are resolved in the order the endpoint's input list declares them. A missing reference yields the matching 404 identifier — `ERR_MEMBER_NOT_FOUND`, `ERR_ELIGIBILITY_CASE_NOT_FOUND`, `ERR_PROGRAM_TRACK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND` (all HTTP 404).
5. **Entity-backed ownership.** A `ProgramMember` may act only on resources whose owning member's `id` equals `X-User-ID`; a `ClinicalPartner` may transition a referral only once its `partner_site_id` is set and equal to `X-User-ID` — a referral whose `partner_site_id` is still null falls through to the state checks below rather than failing ownership. Violations yield `ERR_RESOURCE_NOT_OWNED` (HTTP 403).
6. **Optimistic concurrency.** On the two guarded writes of §2.6, `expected_member_version` must equal the member's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).
7. **State preconditions.** The target resource sits in a state from which the requested transition exists, and the creation-time gates hold: enrollment, claim, and referral creation each require the member's `verification_status` to be `VERIFIED`, and appeal creation requires the claim to be in `DECIDED` — otherwise `ERR_INVALID_STATE`, `ERR_MEMBER_NOT_VERIFIED`, or `ERR_CLAIM_NOT_APPEALABLE` (all HTTP 409).
8. **Segregation of duties.** The `BenefitsOfficer` deciding an appeal must not be the officer who issued the claim's standing decision — otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
9. **Eligibility policy.** A `VERIFIED` case decision must satisfy the service-era and injury-connection policy of §3.1 — otherwise `ERR_ELIGIBILITY_CRITERIA_NOT_MET` (HTTP 409).
10. **Duplication avoidance and program prerequisites.** External-service conflicts and the enrollment prerequisites for placements and referrals — otherwise `ERR_EXTERNAL_SERVICE_CONFLICT`, `ERR_NO_ACTIVE_CAREER_ENROLLMENT`, or `ERR_INTENSITY_TIER_INSUFFICIENT` (all HTTP 409).
11. **Deadlines and windows.** Appeal filing inside its window, milestone confirmation not before its day gate, attendance marking not before the event starts — otherwise `ERR_APPEAL_WINDOW_CLOSED`, `ERR_MILESTONE_TOO_EARLY`, or `ERR_EVENT_NOT_STARTED` (all HTTP 422).
12. **Overlap and uniqueness.** Treatment-window conflicts, event-schedule conflicts, appeal eligibility by claim type, and track-code uniqueness — otherwise `ERR_TREATMENT_WINDOW_CONFLICT`, `ERR_EVENT_SCHEDULE_CONFLICT`, `ERR_CLAIM_TYPE_NOT_APPEALABLE`, or `ERR_DUPLICATE_TRACK_CODE` (all HTTP 409).
13. **Capacity and budget.** Track seat capacity and employer requisition availability — otherwise `ERR_TRACK_CAPACITY_REACHED` or `ERR_NO_OPEN_REQUISITIONS` (both HTTP 409).
14. **Aggregate computability.** A donor report must count at least one member in at least one track — otherwise `ERR_EMPTY_COHORT` (HTTP 422).

The relative order is load-bearing: an authentication failure masks a malformed body, a malformed body masks a role failure, a missing resource masks an ownership failure, an ownership failure masks a stale version, a stale version masks a state error, and so on down the list.

### 2.8. Money, Scores, and Rounding

All monetary values are integer cents — never floats — and any computed monetary figure is rounded half-up to whole cents using decimal arithmetic. Wherever this document names a dollar amount in prose, the stored and transmitted value is the corresponding integer-cent figure. Donor-report effect sizes are the one non-integer quantity in the platform: they are carried as numbers rounded half-up to two decimal places, again under decimal arithmetic, and the per-track rounding happens before any weighting (see §3.8). Acuity scores and wellbeing scores are integers; the acuity computation rounds half-up using decimal arithmetic at its single rounding step (see §3.3). Occupancy ratios used in partner-site ranking are compared as exact rational numbers — census divided by capacity — with no rounding at all.

### 2.9. Nested Reads and Identifier Resolution

Because the topology is flat, a small number of sub-resource reads exist for reverse lookup: a member's eligibility cases, a member's external service records, a member's claims, a claim's appeals, an enrollment's assessments, and an enrollment's surveys. On any URL that chains identifiers, each identifier is validated to exist **left to right** — the member is resolved before its case, the enrollment before its survey, the claim before its appeal — and the first unresolvable identifier produces its specific 404 from the list in §2.7. Request-body foreign keys are likewise resolved in the order the endpoint's input list declares them. List endpoints accept the filter parameters named against them in §4 (for example `status`, `member_id`, `program_track_id`, `employer_partner_id`, `community_event_id`, `partner_site_id`, `region`, `specialty`, `service_category`, `wave`, or `track_code`) in addition to the pagination parameters of §2.3. Filters are exact-match and are never validated against any declared value set: a filter value that matches nothing — including one outside the field's enum — simply yields an empty page rather than an error.

## 3. Business Logic & Workflows

### 3.1. Member Registration and Eligibility Verification

An `IntakeCoordinator` registers each new participant as a `Member`, capturing the member's `full_name`, their `member_type` (`VETERAN` or `FAMILY_SUPPORT`), the self-reported `service_era_claimed` (one of `POST_911`, `PRE_911_GULF`, `VIETNAM_ERA`, or `PEACETIME`), and the self-reported `injury_connection_claimed` (`SERVICE_CONNECTED` or `NON_SERVICE_CONNECTED`). A `branch_of_service` (`ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, or `SPACE_FORCE`) may be supplied for a veteran; it must be null for a `FAMILY_SUPPORT` member and defaults to null when omitted. At registration the member's `verification_status` is `UNVERIFIED` and their `engagement_status` is `INACTIVE`; the system-maintained `verified_service_era` and `verified_injury_connection` remain null until a case decision sets them, and the computed `total_monthly_compensation_cents` starts at 0.

Verification happens through an `EligibilityCase`. Opening a case names the `member_id` and is one of the two OCC-guarded writes of §2.6, so the request must carry `expected_member_version` or be rejected with `ERR_STALE_VERSION`. Creating a case has a blunt consequence: any existing case for the same member in `UNDER_REVIEW` or `PENDED` is automatically moved to `SUPERSEDED`, the member's `version` increments by 1, and the new case starts in `UNDER_REVIEW`.

Each case-machine request names its desired `target_status`, which must be one of `PENDED`, `UNDER_REVIEW`, `VERIFIED`, or `DENIED` — `SUPERSEDED` is reached only by supersession, never through this endpoint, and requesting it (or any other undeclared value) is rejected with `ERR_INVALID_REQUEST` (HTTP 400). `pend_reason` and `denial_reason` are optional free text, defaulting to null. From `UNDER_REVIEW`, an `IntakeCoordinator` may pend the case, moving it to `PENDED` and recording the supplied `pend_reason`; a pended case can later resume to `UNDER_REVIEW`, and resuming leaves the recorded `pend_reason` untouched. Attempting either step from the wrong state fails with `ERR_INVALID_STATE`. A decision takes the case from `UNDER_REVIEW` to either `VERIFIED` or `DENIED`; both stamp `decided_at` from the logical clock. A decision request to `VERIFIED` must carry both `verified_service_era` and `verified_injury_connection`; a missing or null field is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Payload fields that do not apply to the requested target are accepted and ignored: a `pend_reason` is stored only on a pend, a `denial_reason` only on a denial, and the `verified_*` pair is read only on a `VERIFIED` decision. A denial records the supplied `denial_reason` and leaves the member's `verification_status` unchanged — the member stays `UNVERIFIED` unless an earlier case already verified them. A verification is gated by the **eligibility policy**: the decision payload's `verified_service_era` must be `POST_911`, and either the member's `member_type` must be `FAMILY_SUPPORT` or the payload's `verified_injury_connection` must be `SERVICE_CONNECTED`. A decision that fails this policy is rejected with `ERR_ELIGIBILITY_CRITERIA_NOT_MET` (HTTP 409). When verification succeeds, the member's `verification_status` becomes `VERIFIED`, the case's `verified_service_era` and `verified_injury_connection` are copied onto the member record, and the member's `version` increments by 1. `VERIFIED`, `DENIED`, and `SUPERSEDED` are terminal for a case.

Duplication avoidance begins at intake: an `IntakeCoordinator` records any services the member already receives elsewhere as an `ExternalServiceRecord` with `organization_name`, a `service_category` of `MENTAL_HEALTH`, `PHYSICAL_HEALTH`, `CAREER`, `INDEPENDENCE`, or `BENEFITS`, a `start_date`, and optionally an `end_date` (null means open-ended). Records start `ACTIVE` and are closed only by the clock sweep of §2.5. As later sections show, an `ACTIVE` record in the matching category blocks enrollment, claim, and referral creation unless the corresponding consent flag is supplied.

### 3.2. Program Tracks and the Enrollment Lifecycle

A `PlatformAdmin` defines the program catalog as a set of `ProgramTrack` records. Each track has a `track_code` — one of `MENTAL_HEALTH`, `PHYSICAL_HEALTH`, `CAREER`, or `INDEPENDENCE` — which must be unique across all tracks (a duplicate is rejected with `ERR_DUPLICATE_TRACK_CODE`, HTTP 409), a display `name`, and a `capacity` that must be greater than 0. The computed `active_enrollment_count` tracks how many enrollments on the track currently sit in `INTAKE`, `ACTIVE`, or `SUSPENDED`.

An `IntakeCoordinator` enrolls a member by supplying the `member_id` and `program_track_id`, plus an optional `coordination_consent` that defaults to false. Creation is gated by three business checks. First, the member's `verification_status` must be `VERIFIED` — otherwise `ERR_MEMBER_NOT_VERIFIED` (HTTP 409). Second, duplication avoidance: if the member holds an `ACTIVE` external service record whose `service_category` equals the target track's `track_code`, creation is rejected with `ERR_EXTERNAL_SERVICE_CONFLICT` (HTTP 409) unless `coordination_consent` is true, recording the member's consent to coordinate with the other organization. Third, the track's `active_enrollment_count` must be below its `capacity`; a full track rejects with `ERR_TRACK_CAPACITY_REACHED` (HTTP 409) — the boundary is inclusive-full, so a count equal to capacity rejects.

A new enrollment starts in `INTAKE`. Its creation increments the track's `active_enrollment_count` by 1 and bumps the track's `version`, stamps the enrollment's `intensity_tier` and `latest_acuity_score` as null until the first assessment, and schedules the member's `BASELINE` outcome survey (see §3.8). It also re-derives the member's `engagement_status` and increments the member's `version`.

A member's `engagement_status` is fully derived from their enrollments, and the derivation runs on every enrollment creation and every enrollment exit: it is `ENGAGED` while the member holds at least one enrollment in `INTAKE`, `ACTIVE`, or `SUSPENDED`; `GRADUATED` when no enrollment remains in those states and at least one sits in `COMPLETED`; and `INACTIVE` when none remain active and none are completed. Each recomputation that flips the value increments the member's `version` by 1. In state terms: the first enrollment landing in `INTAKE` moves a member from `INACTIVE` to `ENGAGED`; a completion that leaves no active enrollments moves `ENGAGED` to `GRADUATED`; a withdrawal that leaves no active enrollments and no completions moves `ENGAGED` back to `INACTIVE`; and a fresh `INTAKE` enrollment moves a `GRADUATED` member back to `ENGAGED`.

The enrollment-machine request likewise names a `target_status`, one of `SUSPENDED`, `ACTIVE`, `COMPLETED`, or `WITHDRAWN` — `INTAKE` is never a valid target. While enrolled, an `IntakeCoordinator` may suspend an `ACTIVE` enrollment (`ACTIVE` → `SUSPENDED`) and later resume it (`SUSPENDED` → `ACTIVE`); from any other state these requests fail with `ERR_INVALID_STATE`. Exit is possible from `INTAKE`, `ACTIVE`, or `SUSPENDED` and takes one of two dispositions, recorded in `exit_disposition`, with `exit_at` stamped from the logical clock and the coordinator's optional free-text `exit_reason` (defaulting to null) stored; an `exit_reason` supplied on a suspend or resume is ignored:

- **Completion** (`ACTIVE` → `COMPLETED`): the track's `active_enrollment_count` decrements by 1, and the system schedules two surveys for the enrollment — the `EXIT` wave and the `FOLLOWUP_90` wave (windows in §3.8) — before re-deriving the member's engagement.
- **Withdrawal** (`INTAKE`, `ACTIVE`, or `SUSPENDED` → `WITHDRAWN`): the track count decrements by 1, **no** outcome surveys are created, and the member's engagement is re-derived.

Requesting an exit from an enrollment not in one of the listed source states is rejected with `ERR_INVALID_STATE`. `COMPLETED` and `WITHDRAWN` are terminal.

### 3.3. Intake Assessments and Acuity Scoring

Assessments are the clinical yardstick of the platform. An `IntakeCoordinator` records an assessment against a specific enrollment — the enrollment is identified in the request path, so the stored `enrollment_id` comes from the URL rather than the body — supplying four domain scores: `psych_score` (psychological), `phys_score` (physical), `voc_score` (vocational), and `soc_score` (social), each an integer from 0 through 10, plus optional free-text `notes` which default to null.

From the four scores the system computes the assessment's `acuity_score`, an integer from 0 to 100, and its `tier_result` of `STANDARD`, `ENHANCED`, or `INTENSIVE`. The computation weights the four domains, and the weight set depends on the owning member's `member_type`:

- For a `VETERAN`, the weights are psychological 0.4, physical 0.3, vocational 0.2, and social 0.1.
- For a `FAMILY_SUPPORT` member, the weights are psychological 0.5, physical 0.1, vocational 0.2, and social 0.2.

The weighted sum of the four scores lies between 0 and 10; multiplying by 10 and rounding half-up to an integer under decimal arithmetic yields the `acuity_score`. The tier mapping is threshold-based: an acuity of at least 70 is `INTENSIVE`; an acuity of at least 40 but below 70 is `ENHANCED`; anything below 40 is `STANDARD`. Because the two weight sets differ, the identical four domain scores produce a different acuity for a family support member than for a veteran — and can land in a different tier.

Every assessment writes its result back onto the enrollment: the enrollment's `intensity_tier` becomes the new `tier_result`, its `latest_acuity_score` becomes the new `acuity_score`, and the enrollment's `version` increments by 1. The **first** assessment on an enrollment additionally flips it from `INTAKE` to `ACTIVE`. Subsequent re-assessments on an `ACTIVE` or `SUSPENDED` enrollment simply recompute the tier in place and leave the status untouched. Recording an assessment against an enrollment that has already reached `COMPLETED` or `WITHDRAWN` is rejected with `ERR_INVALID_STATE`. Assessments are append-only and are listed in creation order; per §2.4 they carry no `updated_at` and no `version`.

### 3.4. Benefits Claims, Appeals, and Monthly Compensation

Benefits navigation is run by an `AccreditedRepresentative`, who files a `BenefitsClaim` for a member by naming the `member_id` and a `claim_type` of `DISABILITY_COMPENSATION` or `HEALTHCARE_ACCESS`. Filing requires the member's `verification_status` to be `VERIFIED` (otherwise `ERR_MEMBER_NOT_VERIFIED`) and is blocked while the member holds an `ACTIVE` external service record in the `BENEFITS` category — the rejection is `ERR_EXTERNAL_SERVICE_CONFLICT` unless the filing carries `coordination_consent` set to true (it defaults to false), recording consent to proceed despite the overlapping service.

For a disability claim the representative supplies `claimed_rating_pct` — the claimed disability rating, which must be one of the statutory steps 0, 10, 20, and so on up to 100. The field is required exactly when the `claim_type` is `DISABILITY_COMPENSATION` and must be null for `HEALTHCARE_ACCESS`. `dependent_count` records dependents for the award computation; it defaults to 0 and must be at least 0. A new claim starts in `FILED`. At filing the system also computes `provisional_monthly_cents`, a plain estimate shown to the claimant: it is exactly the base rate for the *claimed* rating from the statutory rate table, with no cost-of-living adjustment and no dependent allowance. The base rates, in integer cents per month, are: 0 percent → 0 cents; 10 percent → 17500 cents ($175.00); 20 percent → 34600 cents ($346.00); 30 percent → 52400 cents ($524.00); 40 percent → 75500 cents ($755.00); 50 percent → 105700 cents ($1,057.00); 60 percent → 134000 cents ($1,340.00); 70 percent → 166100 cents ($1,661.00); 80 percent → 193200 cents ($1,932.00); 90 percent → 217200 cents ($2,172.00); 100 percent → 373700 cents ($3,737.00). For a `HEALTHCARE_ACCESS` claim the provisional figure stays null.

A `BenefitsOfficer` decides a claim that sits in `FILED` — deciding from any other state is `ERR_INVALID_STATE` — by supplying the `outcome` (`GRANTED` or `DENIED`) and the `decided_rating_pct`. The `decided_rating_pct` is required exactly when the outcome is `GRANTED`, identically for both claim types; a rating supplied with a `DENIED` outcome is disregarded. On decision the claim moves `FILED` → `DECIDED`; the officer's `X-User-ID` is written to `decided_by_officer_id`, `decided_at` is stamped from the logical clock, and the award is computed under the **final variant**: a denied claim records a `decided_rating_pct` of 0 and a `final_monthly_cents` of 0; a granted claim's `final_monthly_cents` is the base rate for the *decided* rating plus a dependent allowance, the sum then multiplied by 1.025 — the statutory cost-of-living adjustment of 2.5 percent — and rounded half-up to whole cents under decimal arithmetic. The dependent allowance is zero when the decided rating is below 30 percent; at 30 percent or above it is zero for no dependents, 16000 cents ($160.00) for exactly one dependent, and for two or more dependents it is 31000 cents ($310.00) plus a further 9000 cents ($90.00) for each dependent beyond the second. Because the provisional estimate ignores both the adjustment and dependents, identical claim data yields a lower provisional figure than the final award whenever either applies.

Each claim decision — and each appeal decision below, whether the appeal is upheld or overturned — recomputes the member's `total_monthly_compensation_cents`, which is the sum of `final_monthly_cents` over all of the member's claims in `DECIDED` or `CLOSED`, adding the per-claim **rounded** values (each claim is rounded to whole cents before the member-level sum; the order is pinned). The recomputation increments the member's `version` by 1.

A representative may appeal a claim only while the claim is in `DECIDED` — an appeal against a `FILED`, `APPEAL_PENDING`, or `CLOSED` claim is rejected with `ERR_CLAIM_NOT_APPEALABLE` (HTTP 409) — and only when the claim is a `DISABILITY_COMPENSATION` claim, since a `HEALTHCARE_ACCESS` claim is rejected with `ERR_CLAIM_TYPE_NOT_APPEALABLE` (HTTP 409). The appeal must also be filed within the **appeal window**: the logical clock must be no later than the claim's `decided_at` plus 90 days. The window's upper bound is inclusive — the final instant of the 90th day is still inside the window, and one second later is not — and a late filing is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422). Filing an appeal records optional free-text `grounds` (defaulting to null), stamps `filed_at` from the logical clock, opens the appeal in `OPEN`, and moves the claim `DECIDED` → `APPEAL_PENDING`.

A `BenefitsOfficer` then decides an `OPEN` appeal — any other appeal state is `ERR_INVALID_STATE` — under a hard **segregation of duties**: the officer's `X-User-ID` must differ from the claim's standing `decided_by_officer_id`; the same officer deciding their own appeal is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The decision supplies an `outcome` of `UPHELD` or `OVERTURNED`; `new_rating_pct` is required exactly when the outcome is `OVERTURNED` and must be one of the rating steps 0 through 100 by tens. Deciding stamps the appeal's `decided_by_officer_id` and `decided_at` and returns the claim from `APPEAL_PENDING` to `DECIDED`. When the appeal is overturned, the claim's `outcome` becomes `GRANTED`, the claim's `decided_rating_pct` is replaced by the appeal's `new_rating_pct`, the claim's `final_monthly_cents` is recomputed under the final variant, and the claim's `decided_by_officer_id` becomes the appeal's deciding officer. In every case the claim's `decided_at` is re-anchored to the appeal's `decided_at` — a consequence being that the appeal window and the clock-sweep close of §2.5 (which moves `DECIDED` → `CLOSED` once the clock passes 97 days after `decided_at`) both measure from the most recent decision. `CLOSED` is terminal; a closed claim still contributes its `final_monthly_cents` to the member's total.

### 3.5. Clinical Referrals and Partner-Site Matching

Members whose mental-health needs exceed program-based care are referred to intensive outpatient treatment at a `PartnerSite`. A `PlatformAdmin` registers each site with a `name`, the `region` it serves, a non-empty `specialties` list drawn from `PTSD`, `TBI`, `SUBSTANCE_USE`, and `DEPRESSION`, and a `capacity` greater than 0. The computed `current_census` counts referrals matched to the site in `MATCHED` or `IN_TREATMENT` and starts at 0.

An `IntakeCoordinator` creates a `Referral` by naming the `member_id`, the `region` the member can attend, a `required_specialty` (one of the four specialties above), and the planned window `treatment_start` to `treatment_end` — the end must be strictly after the start. Creation is the second OCC-guarded write of §2.6 and must carry `expected_member_version` matching the member's current `version`, or it is rejected with `ERR_STALE_VERSION`. Three further gates apply. The member must be `VERIFIED` (`ERR_MEMBER_NOT_VERIFIED`). The member must hold an enrollment on a `MENTAL_HEALTH` track in `ACTIVE` or `SUSPENDED` whose `intensity_tier` is `INTENSIVE`; without one, creation is rejected with `ERR_INTENSITY_TIER_INSUFFICIENT` (HTTP 409). And duplication avoidance applies to the `MENTAL_HEALTH` category: an `ACTIVE` external record in that category blocks creation with `ERR_EXTERNAL_SERVICE_CONFLICT` unless `coordination_consent` (defaulting to false) is supplied as true.

Referrals also cannot stack overlapping treatment. For each of the member's other referrals in `PENDING_MATCH`, `MATCHED`, or `IN_TREATMENT`, the existing window is extended by a 7-day recovery buffer past its `treatment_end`, and the new window is likewise extended by 7 days past its own `treatment_end`. The extended intervals are **closed**: they conflict when the new start falls on or before the existing extended end and the existing start falls on or before the new extended end — so a new window whose `treatment_start` lands exactly on another referral's buffered end still conflicts. Any conflict rejects the creation with `ERR_TREATMENT_WINDOW_CONFLICT` (HTTP 409).

Two creation-time cascades follow. First, every referral the member already holds in `PENDING_MATCH` — there can be more than one when their treatment windows do not overlap — is moved to `SUPERSEDED`. Second, the member's `version` increments by 1. Every referral receives a `request_seq` — a globally monotonic sequence starting from 1 across all referrals, assigned at creation — which later drives deterministic re-match order.

Matching itself is a deterministic selector that runs at creation. A partner site qualifies when its `region` equals the referral's `region`, the referral's `required_specialty` appears in the site's `specialties`, and the site's `current_census` is below its `capacity`. Qualified candidates are ranked by occupancy — the exact rational ratio of `current_census` to `capacity`, compared without rounding — ascending; ties break by the site's `created_at` ascending, then by the site's `name` ascending, and finally by site registration order; identifiers are never consulted. The first row of that ordering wins: the referral's `partner_site_id` is set, `matched_at` is stamped from the logical clock, the referral moves `PENDING_MATCH` → `MATCHED`, and the site's `current_census` increments by 1. A referral matched by the selector at creation is still returned at `version` 1 — the match is part of the creation write, not a separate mutation — while the matched site's `version` does increment for its census change. When no site qualifies the referral simply stays in `PENDING_MATCH` — this is not an error — with `partner_site_id` and `matched_at` null. A referral still in `PENDING_MATCH` is moved to `EXPIRED` by the clock sweep once the logical clock passes its `treatment_start`.

Each referral transition request carries an `action` of ADMIT or DISCHARGE. From `MATCHED`, the clinical partner admits the member, moving the referral to `IN_TREATMENT` and stamping `admitted_at`; from `IN_TREATMENT`, the partner discharges the member to `DISCHARGED`, stamping `discharged_at`. Both steps are driven by a `ClinicalPartner` and both are ownership-gated: the referral's `partner_site_id` must equal the caller's `X-User-ID`, otherwise `ERR_RESOURCE_NOT_OWNED`; a referral whose `partner_site_id` is still null falls through to the state check, and requesting either action from the wrong state is `ERR_INVALID_STATE`. Discharge also decrements the site's `current_census` by 1 — and the freed slot is immediately offered to the eligible `PENDING_MATCH` referral with the smallest `request_seq`, where eligible means its `region` equals the freed site's `region` and its `required_specialty` appears in the site's `specialties`. That referral moves `PENDING_MATCH` → `MATCHED` to the freed site, with `partner_site_id` set, `matched_at` stamped, and the census incremented by 1; if no pending referral is eligible, the slot simply stays open. Re-match fires only on a discharge — nothing re-scans the waiting list at any other time.

### 3.6. Career Counseling, Employer Partners, and Placement Milestones

The career program pairs verified members with employer partners and follows each placement through its first 180 days. A `CareerCounselor` registers an `EmployerPartner` with a `name`, an `industry` label, and the number of currently fillable `open_requisitions` — a non-negative integer defaulting to 0.

Placing a member names the `member_id` and `employer_partner_id`, the employment `start_date` (which anchors every milestone clock), and the annualized `salary_cents`, a non-negative integer. Two gates guard creation. The member must hold an enrollment on a `CAREER` track in `ACTIVE` status — placement without one is rejected with `ERR_NO_ACTIVE_CAREER_ENROLLMENT` (HTTP 409). And the employer must actually have a requisition open: when `open_requisitions` is 0 the create is rejected with `ERR_NO_OPEN_REQUISITIONS` (HTTP 409). A successful placement starts in `ACTIVE`, decrements the employer's `open_requisitions` by 1, and bumps the employer partner's `version` by 1.

Retention is tracked as a strict milestone ladder, climbed one rung at a time by the `CareerCounselor`: `ACTIVE` → `MILESTONE_30` → `MILESTONE_90` → `MILESTONE_180` → `RETAINED`. Each confirmation request carries an `action` of CONFIRM_MILESTONE together with a `milestone` of DAY_30, DAY_90, or DAY_180, and is allowed only from the immediately preceding rung; confirming out of order is `ERR_INVALID_STATE`. Each confirmation is also gated against the calendar: the day-30 confirmation requires the logical clock to be at or after `start_date` plus 30 days, day-90 at or after 90 days, and day-180 at or after 180 days. The exact day is allowed; confirming earlier is rejected with `ERR_MILESTONE_TOO_EARLY` (HTTP 422). The day-180 confirmation is special — it moves the placement straight through `MILESTONE_180` into `RETAINED` in the same action, and `RETAINED` is terminal.

A placement can also end early. A separation request instead carries an `action` of SEPARATE. Separation is available from `ACTIVE`, `MILESTONE_30`, `MILESTONE_90`, or `MILESTONE_180` — any other state is `ERR_INVALID_STATE` — and moves the placement to `SEPARATED`, stamping `separated_at` from the logical clock; an optional free-text `separation_reason` may accompany the request but is accepted without being stored on the placement record, and a `milestone` supplied on a SEPARATE request is ignored. Whether the employer gets the requisition back depends on how long the placement lasted: separating from `ACTIVE` or `MILESTONE_30` — that is, any time before the day-90 milestone — restores the employer's `open_requisitions` by 1, while separating from `MILESTONE_90` or later does not. The accounting invariant across the lifecycle is that an employer's current `open_requisitions`, plus its placements sitting in `ACTIVE`, `MILESTONE_30`, `MILESTONE_90`, `MILESTONE_180`, or `RETAINED`, plus its placements that separated at day 90 or later, always equals the `open_requisitions` the employer was registered with.

### 3.7. Community Events, Registration Seating, and Travel Support

Community engagement events are where members reconnect. An `EventCoordinator` creates a `CommunityEvent` with a `name`, a `starts_at` and an `ends_at` (the end must be strictly after the start), a `capacity` greater than 0 limiting confirmed seats, an `accessibility_seat_count` — the number of seats able to honor accommodation needs, at least 0 and no more than `capacity` — and a `travel_budget_cents` pool, a non-negative integer funding travel support. The computed counters `registered_count`, `accessibility_seats_used`, and `travel_budget_remaining_cents` start at 0, 0, and the full travel budget respectively.

Either an `EventCoordinator` or an `IntakeCoordinator` registers a member by naming the `member_id` and `community_event_id`, optionally with `accommodation_needs` — a subset of `WHEELCHAIR`, `ASL_INTERPRETER`, `SERVICE_ANIMAL`, and `SENSORY_FRIENDLY`, defaulting to empty — and a `travel_request_cents` amount, defaulting to 0 and never negative. Each registration draws the next `queue_position` for its event: a per-event monotonic sequence starting from 1, unique and gap-free within the event, which later fixes waitlist promotion order. Before any seat is offered, the member's calendar is checked: the new event's half-open interval — from its `starts_at` up to but not including its `ends_at` — is compared against the intervals of every other event for which the member holds a `CONFIRMED` or `WAITLISTED` registration. The two conflict when the new event starts before the existing one ends and the existing one starts before the new one ends; an event starting exactly when another ends does **not** conflict. Any conflict rejects the registration with `ERR_EVENT_SCHEDULE_CONFLICT` (HTTP 409).

Seating is decided at creation by the event's counters. The registration lands in `CONFIRMED` when the event's `registered_count` is still below `capacity` **and**, for a registration with a non-empty `accommodation_needs`, the event's `accessibility_seats_used` is still below its `accessibility_seat_count`; a registration with no accommodation needs ignores the accessibility check. The capacity boundary is inclusive-full: once `registered_count` equals `capacity`, further registrations waitlist. A confirmation increments `registered_count` by 1, increments `accessibility_seats_used` by 1 when the registration carries accommodation needs, and immediately grants a **travel award**: `travel_award_cents` is the smallest of the registration's `travel_request_cents`, a per-registration cap of 50000 cents ($500.00), and the event's `travel_budget_remaining_cents`; the granted amount is debited from `travel_budget_remaining_cents`. A registration that does not seat lands in `WAITLISTED` with a `travel_award_cents` of 0 — waitlisted rows hold no award until promoted.

The registration transition request carries an `action` of CANCEL or ATTEND. Cancellation works from either live state. Cancelling a `CONFIRMED` registration decrements `registered_count` by 1, decrements `accessibility_seats_used` by 1 when the registration had accommodation needs, and returns its `travel_award_cents` to `travel_budget_remaining_cents`. The freed seat then triggers **waitlist promotion**: among the event's `WAITLISTED` registrations, the system considers those whose accommodation needs fit the now-available seats — meaning their `accommodation_needs` are empty, or the event's `accessibility_seats_used` is below its `accessibility_seat_count` — takes the one with the smallest `queue_position`, and promotes exactly that one to `CONFIRMED`, recomputing its `travel_award_cents` under the same minimum-of-three rule and debiting the budget; if no waitlisted row fits, nothing happens. Cancelling a `WAITLISTED` registration releases nothing, since the row held no seat and no award. Requesting a cancellation from any state other than `CONFIRMED` or `WAITLISTED` is `ERR_INVALID_STATE`.

Attendance is marked against a `CONFIRMED` registration once the event has begun: marking before the event's `starts_at` — measured on the logical clock — is rejected with `ERR_EVENT_NOT_STARTED` (HTTP 422), while marking at or after the start moves the registration to `ATTENDED`. Registrations that never resolve are handled by the clock sweep of §2.5: a registration still `CONFIRMED` once the clock passes the event's `ends_at` becomes `NO_SHOW` (its travel award is not clawed back), and a registration still `WAITLISTED` once the clock passes the event's `starts_at` becomes `EXPIRED`. `CANCELLED`, `ATTENDED`, `NO_SHOW`, and `EXPIRED` are terminal.

### 3.8. Outcome Surveys and Donor Reporting

Outcome measurement is survey-driven, and surveys are **system-created, never client-created**. Each `OutcomeSurvey` belongs to an enrollment through its `enrollment_id` and runs one of three waves, named by `wave`:

- The `BASELINE` wave is created at enrollment creation, with a window from the enrollment's `created_at` through 14 days later.
- The `EXIT` wave is created when an enrollment completes, with a window from the enrollment's `exit_at` through 30 days later.
- The `FOLLOWUP_90` wave is created at the same time, with a window centered 90 days after exit and a 7-day grace on each side — that is, from `exit_at` plus 83 days through `exit_at` plus 97 days.

Both window bounds — `window_open_at` and `window_close_at` — are inclusive for submission. A withdrawn enrollment receives no surveys at all. Every survey starts `SCHEDULED`; the clock sweep of §2.5 moves it to `OPEN` once the clock reaches `window_open_at`, and a survey still `OPEN` once the clock passes `window_close_at` becomes `EXPIRED` without a score.

A survey is answered through submission of the five wellbeing items `q1`, `q2`, `q3`, `q4`, and `q5`, each an integer Likert score from 1 through 5. Submission is allowed only while the survey is `OPEN` — submitting in any other state is `ERR_INVALID_STATE` — and is open to two callers: the member themselves, acting as a `ProgramMember`, who may submit only surveys belonging to one of their own enrollments (any other survey is `ERR_RESOURCE_NOT_OWNED`), or an `IntakeCoordinator` capturing responses by phone. A successful submission moves the survey to `SUBMITTED`, stamps `submitted_at` from the logical clock, and computes the `wellbeing_score`: the five item scores are summed and the sum multiplied by 4, yielding an integer from 20 to 100. Before submission the items and the score are null.

Finally, an `OutcomeAnalyst` generates a `DonorReport` — an immutable aggregate, created once and never modified — by naming a `period_start` and a `period_end` (the end must be at or after the start) and a `methodology` of `ITT` or `COMPLETER`. The report's cohort, per program track, is the set of enrollments on that track in `COMPLETED` whose `exit_at` falls within the period, both bounds inclusive. For each cohort member the effect is the delta between two submitted surveys: the `SUBMITTED` `BASELINE` wave's `wellbeing_score` and the `SUBMITTED` `EXIT` wave's `wellbeing_score` of the same enrollment, delta being exit minus baseline. The two methodologies differ in how they treat missing data:

- Under `ITT` (intent-to-treat), every cohort member counts; a missing baseline score is imputed as 50, and a missing exit score is imputed as that member's baseline — the actual baseline if submitted, otherwise the imputed 50 — which dilutes the measured effect relative to completer analysis on identical data.
- Under `COMPLETER`, only members whose enrollment has both a submitted baseline and a submitted exit are counted.

Each track's effect is the mean of its counted members' deltas, rounded half-up to two decimal places under decimal arithmetic — and this per-track rounding happens **before** any weighting; the rounded per-track figures appear on the report as `per_track`, an array of entries each carrying the track's `track_code`, its `cohort_size`, and its `effect`, ordered by `track_code` ascending. The report's `overall_effect` is the weighted sum of the per-track effects, itself rounded half-up to two decimal places. The weights come from the optional `track_weights` map — an object of numeric values that must sum to exactly 1.0 across all supplied entries when the map is supplied, otherwise rejected with `ERR_INVALID_REQUEST` (HTTP 400); when omitted, each included track is weighted by its share of the total counted cohort. Tracks whose counted cohort is empty are dropped from the computation and the remaining weights renormalized proportionally: entries naming dropped or unknown tracks still count toward the 1.0 sum but take no part in the weighting, an included track the map does not name weighs 0 before renormalization, and if the surviving weights sum to zero or less the included tracks are weighted equally. `cohort_size_total` records the members counted across all included tracks, and the report record echoes the request's `period_start`, `period_end`, `methodology`, and `track_weights` (null when omitted). If every track's counted cohort is empty, report creation is rejected with `ERR_EMPTY_COHORT` (HTTP 422).

## 4. Endpoint Definitions

All endpoints are mounted under `/veteran-services`. Creating a new resource returns HTTP 201 with the created resource in `data`; reads, transitions, decisions, submissions, and the clock-set capability return HTTP 200. Error responses carry the identifiers catalogued in §5, raised under the precedence rules of §2.7. Request payloads, side effects, and preconditions for each row are defined by the narratives of §2 and §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/veteran-services/_clock/set_current_utc` | Set the logical clock; each set runs the full clock sweep | PlatformAdmin |
| POST | `/veteran-services/program-tracks` | Create a program track (mental health, physical health, career, independence) | PlatformAdmin |
| GET | `/veteran-services/program-tracks` | List program tracks with computed active enrollment counts | PlatformAdmin, IntakeCoordinator, CareerCounselor, OutcomeAnalyst |
| POST | `/veteran-services/members` | Register a veteran or family support member (verification starts UNVERIFIED) | IntakeCoordinator |
| GET | `/veteran-services/members/{member_id}` | Get a member; a ProgramMember may read only their own record | IntakeCoordinator, OutcomeAnalyst, AccreditedRepresentative, BenefitsOfficer, CareerCounselor, EventCoordinator, ProgramMember |
| POST | `/veteran-services/eligibility-cases` | Open an eligibility case; supersedes any UNDER_REVIEW/PENDED case; OCC-guarded on the member | IntakeCoordinator |
| GET | `/veteran-services/members/{id}/eligibility-cases` | List a member's eligibility cases; a ProgramMember lists only their own | IntakeCoordinator, ProgramMember |
| POST | `/veteran-services/eligibility-cases/{case_id}/transition` | Drive the case machine: pend, resume, verify, or deny per state preconditions | IntakeCoordinator |
| POST | `/veteran-services/external-service-records` | Record services the member receives from another veteran service organization | IntakeCoordinator |
| GET | `/veteran-services/members/{id}/external-service-records` | List a member's external service records | IntakeCoordinator |
| POST | `/veteran-services/enrollments` | Enroll a VERIFIED member into a program track | IntakeCoordinator |
| GET | `/veteran-services/enrollments` | List enrollments, filterable by member, track, and status | IntakeCoordinator, CareerCounselor, OutcomeAnalyst |
| GET | `/veteran-services/enrollments/{enrollment_id}` | Get one enrollment | IntakeCoordinator, CareerCounselor, OutcomeAnalyst |
| POST | `/veteran-services/enrollments/{enrollment_id}/assessments` | Record an intake or re-assessment; computes acuity and tier; first assessment flips INTAKE to ACTIVE | IntakeCoordinator |
| GET | `/veteran-services/enrollments/{id}/assessments` | List an enrollment's assessments in creation order | IntakeCoordinator, OutcomeAnalyst |
| POST | `/veteran-services/enrollments/{enrollment_id}/transition` | Drive the enrollment machine: suspend, resume, complete, or withdraw | IntakeCoordinator |
| POST | `/veteran-services/claims` | File a benefits claim for a VERIFIED member | AccreditedRepresentative |
| GET | `/veteran-services/members/{id}/claims` | List a member's claims | AccreditedRepresentative, BenefitsOfficer, IntakeCoordinator |
| GET | `/veteran-services/claims/{claim_id}` | Get one claim | AccreditedRepresentative, BenefitsOfficer |
| POST | `/veteran-services/claims/{claim_id}/decide` | Issue the claim decision (granted or denied, with rating) | BenefitsOfficer |
| POST | `/veteran-services/appeals` | Open an appeal on a DECIDED disability claim within the appeal window | AccreditedRepresentative |
| GET | `/veteran-services/claims/{id}/appeals` | List a claim's appeals | AccreditedRepresentative, BenefitsOfficer |
| POST | `/veteran-services/appeals/{appeal_id}/decide` | Decide an appeal under segregation of duties | BenefitsOfficer |
| POST | `/veteran-services/referrals` | Create a clinical referral; the site selector runs at creation; supersedes the member's PENDING_MATCH referral; OCC-guarded on the member | IntakeCoordinator |
| GET | `/veteran-services/referrals` | List referrals, filterable by member, partner site, and status | IntakeCoordinator, ClinicalPartner |
| GET | `/veteran-services/referrals/{referral_id}` | Get one referral | IntakeCoordinator, ClinicalPartner |
| POST | `/veteran-services/referrals/{referral_id}/transition` | Admit or discharge a referral for the caller's own site | ClinicalPartner |
| POST | `/veteran-services/partner-sites` | Register an intensive outpatient partner site | PlatformAdmin |
| GET | `/veteran-services/partner-sites` | List partner sites with computed census | PlatformAdmin, IntakeCoordinator, ClinicalPartner |
| POST | `/veteran-services/employer-partners` | Register an employer partner with open requisitions | CareerCounselor |
| GET | `/veteran-services/employer-partners` | List employer partners with live requisition counts | CareerCounselor |
| POST | `/veteran-services/placements` | Place a member with an ACTIVE career enrollment into an employer requisition | CareerCounselor |
| GET | `/veteran-services/placements` | List placements, filterable by member, employer, and status | CareerCounselor, OutcomeAnalyst |
| GET | `/veteran-services/placements/{placement_id}` | Get one placement | CareerCounselor |
| POST | `/veteran-services/placements/{placement_id}/transition` | Confirm a milestone (day 30, 90, or 180) or record a separation | CareerCounselor |
| POST | `/veteran-services/community-events` | Create a community event with capacity, accessibility seats, and a travel budget | EventCoordinator |
| GET | `/veteran-services/community-events` | List community events with computed counters | EventCoordinator, IntakeCoordinator, ProgramMember |
| POST | `/veteran-services/event-registrations` | Register a member for an event; seating logic decides CONFIRMED vs WAITLISTED; travel award computed on confirmation | EventCoordinator, IntakeCoordinator |
| GET | `/veteran-services/event-registrations` | List event registrations, filterable by member, event, and status | EventCoordinator, IntakeCoordinator |
| GET | `/veteran-services/event-registrations/{registration_id}` | Get one event registration | EventCoordinator, IntakeCoordinator |
| POST | `/veteran-services/event-registrations/{registration_id}/transition` | Cancel (releasing seat, award, and triggering waitlist promotion) or mark attendance once the event has started | EventCoordinator, IntakeCoordinator |
| GET | `/veteran-services/enrollments/{id}/surveys` | List an enrollment's system-created outcome surveys | IntakeCoordinator, OutcomeAnalyst |
| POST | `/veteran-services/surveys/{survey_id}/submit` | Submit survey responses while the wave window is open; a ProgramMember submits only their own enrollment's surveys | ProgramMember, IntakeCoordinator |
| POST | `/veteran-services/donor-reports` | Generate an immutable donor outcome report for a period under a methodology | OutcomeAnalyst |
| GET | `/veteran-services/donor-reports/{report_id}` | Get a donor report | OutcomeAnalyst |

## 5. Error Code Catalogue

The full error vocabulary is below. Trigger conditions for each code are defined where the corresponding rule lives in §2 and §3, under the precedence order of §2.7.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_RESOURCE_NOT_OWNED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_ELIGIBILITY_CASE_NOT_FOUND | 404 |
| ERR_PROGRAM_TRACK_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_EMPLOYER_NOT_FOUND | 404 |
| ERR_PLACEMENT_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_REGISTRATION_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_NOT_FOUND | 404 |
| ERR_METHOD_NOT_ALLOWED | 405 |
| ERR_INVALID_STATE | 409 |
| ERR_MEMBER_NOT_VERIFIED | 409 |
| ERR_ELIGIBILITY_CRITERIA_NOT_MET | 409 |
| ERR_EXTERNAL_SERVICE_CONFLICT | 409 |
| ERR_CLAIM_NOT_APPEALABLE | 409 |
| ERR_CLAIM_TYPE_NOT_APPEALABLE | 409 |
| ERR_TREATMENT_WINDOW_CONFLICT | 409 |
| ERR_INTENSITY_TIER_INSUFFICIENT | 409 |
| ERR_EVENT_SCHEDULE_CONFLICT | 409 |
| ERR_NO_ACTIVE_CAREER_ENROLLMENT | 409 |
| ERR_TRACK_CAPACITY_REACHED | 409 |
| ERR_NO_OPEN_REQUISITIONS | 409 |
| ERR_DUPLICATE_TRACK_CODE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_MILESTONE_TOO_EARLY | 422 |
| ERR_EVENT_NOT_STARTED | 422 |
| ERR_EMPTY_COHORT | 422 |
| ERR_INTERNAL | 500 |
