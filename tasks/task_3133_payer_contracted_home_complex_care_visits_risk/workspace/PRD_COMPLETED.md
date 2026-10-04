# Payer-Contracted Home Care API — Product Requirements Document

## 1. Introduction

Health plans increasingly pay risk-bearing provider organizations to keep chronically ill members out of the emergency department and out of the hospital, but the operational machinery to do that safely is non-trivial. This document specifies the API for a Payer-Contracted In-Home Complex Care platform — a system modelled on programs such as Landmark Health — that takes responsibility for the full chain from member identification through in-home complex care delivery, urgent response, and contract settlement.

The platform ingests attributed members from a payer data feed, scores each member's chronic-condition burden from claims history, runs an outreach-and-consent funnel to bring eligible members into a supplemental home-based program, composes a multidisciplinary care team around each enrolled member, schedules and routes clinicians to in-home visits across a defined service geography, captures structured assessment data (medication reconciliation, home safety, social needs) that refines the member's risk profile, coordinates with the member's existing primary care physician without ever replacing that relationship, and stands ready to dispatch an urgent-response clinician within a contractual SLA whenever a member, PCP, or plan raises an alarm. Settlement is payer-driven and performance-contingent: the platform supports both capitated per-member-per-month and shared-savings payment models, holds back a quality withhold pending measurement, and reconciles each period against observed medical cost and a composite performance score.

The system is built around a small set of cooperating roles with segregation of duties — outreach specialists cannot schedule visits, coordinators cannot complete visits, and only the assigned clinician can act on a visit or urgent episode in flight. A logical clock, owned by the platform operator, drives urgent-response SLA lapses and period-boundary semantics so that test-driving the program's time dimension is deterministic. This document is the contract-level product specification: §2 enumerates global rules and the response envelope, §3 walks the business workflows in narrative form, §4 gives the endpoint table, and §5 the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint. Domain-specific principles live in §2.4 onward; business workflow detail lives in §3.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` names the operational capacity in which they act. If either header is missing or empty, the server rejects the call with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A non-empty `X-User-Role` value that is not one of the six recognized roles is likewise rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400), not with a permissions error. Beyond authentication, each endpoint permits a fixed set of roles; a call made under a recognized role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `ContractAdministrator`, `EngagementSpecialist`, `CareCoordinator`, `Clinician`, and `PerformanceAnalyst`.

Five of these roles have an opaque identity. When `X-User-Role` is `PlatformAdmin`, `ContractAdministrator`, `EngagementSpecialist`, `CareCoordinator`, or `PerformanceAnalyst`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id` field.

The remaining role is identity-bound. When `X-User-Role` is `Clinician`, `X-User-ID` is interpreted as a clinician id; the server does not independently validate that such a `Clinician` resource exists — the identity is only ever exercised through ownership checks, which compare a resource's foreign-key field (for example, a visit's `clinician_id` or an urgent episode's `dispatched_clinician_id`) against `X-User-ID`. A clinician who attempts a clinician-driven transition on a visit or episode they are not assigned to is rejected with `ERR_NOT_ASSIGNED_CLINICIAN` (HTTP 403).

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

- The `api_request_id` is a server-generated unique identifier for the request consisting of the prefix `req_` followed by 20 random uppercase alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; envelope timestamps use the server's real wall clock and are independent of the logical clock of §2.4, which governs business timestamps only.
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
- Requests to undefined paths, or to defined paths under an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope; any uncaught server-side failure is reported as `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

List endpoints accept two pagination query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, accepts a minimum of 1, and caps at a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Both are optional. A non-integer value, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by `id` ascending. The `meta` object of a list response always carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, regardless of whether the underlying result set spans one page or many; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Individual list endpoints additionally accept optional equality filters on their resource's foreign-key and status-like fields — `care_program_id`, `payer_contract_id`, `pcp_provider_id`, `member_id`, `enrollment_id`, `clinician_id`, `dispatched_clinician_id`, `payment_model`, `discipline`, `status`, `risk_tier`, `visit_type`, `period_index`, and `is_current` — which combine conjunctively; the boolean `is_current` filter treats `true`, `1`, and `yes` (case-insensitive) as true and any other non-empty value as false.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource in the system — `CareProgram`, `PayerContract`, `PCPProvider`, `Clinician`, `Member`, `MemberEnrollment`, `CareTeam`, `Visit`, `VisitAssessment`, `UrgentResponseEpisode`, `PerformanceMeasurement`, `PayerSettlement`, and `MedicalCost` — carries four system-managed fields: an `id` that is a server-minted UUID (no type prefix, no entity-name prefix), a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Timestamps are ISO 8601 UTC with three fractional digits. The `version` starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascade side-effects from a related resource's transition; `updated_at` is refreshed on the same cadence.

Time in this system is logical, not wall-clock. Each `CareProgram` carries a `current_period_index` integer that begins at 0 when the program is created and advances only via the operator-driven period-advance capability, which moves the index forward by a caller-supplied `by_days` number of days. Separately, the server maintains a logical UTC clock, initialized at startup to `2026-09-01T00:00:00Z`; the server MUST NOT fall back to real wall-clock time before the operator first drives the clock. Two operator capabilities control this clock: one sets it to an arbitrary supplied `current_utc` timestamp, and one advances it forward by a supplied `by_hours` count of hours. The automatic lapse of an `UrgentResponseEpisode` whose `sla_deadline` the logical clock has passed (while the episode is still `TRIGGERED` or `DISPATCHED`) is a discrete sweep, not a continuous reaction: the sweep is global across all programs' episodes, and it fires only when any program's period-advance capability runs and when the operator's clock-advance-hours capability runs (see §3.6). Setting the clock to an arbitrary timestamp does NOT trigger this sweep — an episode whose deadline the new clock value has already crossed remains in `TRIGGERED` or `DISPATCHED` until a subsequent period advance or clock advance runs the sweep (a `DISPATCHED` episode so situated may still be arrived, with `sla_met` computed as `false` at arrival per §3.6). Both operator increment capabilities take an integer (`by_hours` for the clock, `by_days` for the period advance) that is added to the current value without any positivity constraint. The two `/_clock/...` endpoints return HTTP 200 with an empty `data` object; the period-advance capability returns the updated `CareProgram`.

### 2.5. Optimistic Concurrency Control

Two write endpoints take an explicit optimistic-concurrency version field on the request payload. Both are guarded against the same failure mode — a caller acting on a stale view of a parent resource — and both report the failure identically.

A request to create a new enrollment for a member must carry `expected_member_version` holding the `Member.version` value the caller most recently observed for that member. If another writer has advanced the member's version since that observation — most commonly because another enrollment creation legitimately superseded the prior `is_current` enrollment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejected client is expected to re-read the member and decide whether the newly created enrollment obviates the one it intended to file.

A request to reschedule a cancelled visit must carry `expected_visit_version` holding the `Visit.version` value the caller most recently observed. A mismatch against the visit's current `version` — for example, because a disenrollment cascade or a prior cancel already advanced it — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named here do not accept a version field. The version-match check fires only at write time against the named parent entity's current `version`; there is no implicit OCC on other operations.

### 2.6. Validation Ordering and Error Discipline

When a single endpoint invocation could violate more than one rule, the server reports exactly one error and the order in which checks are evaluated is fixed. Every endpoint applies the same ladder:

1. Presence and well-formedness of `X-User-ID` and `X-User-Role` — failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint — failure is `ERR_INSUFFICIENT_PERMISSIONS`.
3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies.
4. Body-supplied foreign keys resolve — a payload that names a `payer_contract_id`, `pcp_provider_id`, `member_id`, `enrollment_id`, `primary_np_id`, `social_worker_id`, or `behavioral_clinician_id` that does not exist yields the corresponding `ERR_{REFERENCED}_NOT_FOUND`.
5. State preconditions for the requested transition — the named resource must be in the expected state (see §3); failures surface as resource-specific state errors such as `ERR_ENROLLMENT_NOT_IDENTIFIED`, `ERR_VISIT_NOT_SCHEDULED`, or `ERR_EPISODE_NOT_TRIGGERED`.
6. Enrollment `is_current` invariant on every enrollment state transition — failure is `ERR_ENROLLMENT_SUPERSEDED`.
7. Care-team readiness on visit creation and the NP-discipline requirement on care-team activation — failures are `ERR_CARE_TEAM_NOT_ACTIVE` and `ERR_PRIMARY_NP_INVALID` respectively.
8. Acting-clinician ownership on clinician-driven transitions — failure is `ERR_NOT_ASSIGNED_CLINICIAN`.
9. Urgent-dispatch temporal preconditions — failure is `ERR_SLA_ALREADY_LAPSED` if the logical clock has already crossed `sla_deadline`.
10. Selector candidate-pool emptiness — failure is `ERR_NO_AVAILABLE_CLINICIAN`.
11. Visit-window overlap arithmetic against the assigned clinician's other in-flight visits — failure is `ERR_VISIT_TIME_OVERLAP`.
12. Mark-no-show temporal precondition — failure is `ERR_VISIT_WINDOW_NOT_PAST` if the logical clock has not yet reached the visit's `scheduled_end`.
13. Optimistic-concurrency match on the two versioned write endpoints listed in §2.5 — failure is `ERR_STALE_VERSION`.
14. Contract expiry at settlement finalization — failure is `ERR_CONTRACT_EXPIRED`.
15. Payment-model consistency at contract creation — failure is `ERR_PAYMENT_MODEL_MISMATCH`.

The ladder matters: a caller cannot infer the state of a later check from the absence of an earlier error. A stale-version enrollment create against a member that does not exist reports `ERR_MEMBER_NOT_FOUND`, not `ERR_STALE_VERSION`. One endpoint-specific exception exists: on record-attempt, the outreach-attempt cap check (`ERR_OUTREACH_ATTEMPTS_EXHAUSTED`) is evaluated before the state and `is_current` checks, as specified in §3.3. Request-body field validation — presence, type, and enum-domain checks, including the window-validity rule that `scheduled_end` be strictly later than `scheduled_start` — fails with `ERR_INVALID_REQUEST` (HTTP 400) unless a more specific error is named, and is evaluated between rungs 3 and 5 except where a §3 narrative pins body checks after the state and `is_current` checks (record-consent, disenroll, cancel, resolve).

### 2.7. Deterministic Precision and Rounding

All monetary amounts are integer cents. Aggregation operations that produce fractional cents round half-up at the aggregate level only (see §3.7); per-row amounts are stored as supplied. The composite performance score and each of its components are carried to 4 decimal places with round-half-up at each stage — the components are rounded individually to 4 decimal places before being weighted, and the weighted sum is then rounded to 4 decimal places again. Collapsing the two-stage rounding into a single step is a specification violation and will produce different downstream cents. Burden scores are integer points and never rounded.

### 2.8. Payment-Model Consistency

Every `PayerContract` declares a `payment_model` of either `CAPITATED` or `SHARED_SAVINGS`, and the chosen model dictates which rate fields are required. A `CAPITATED` contract must supply `pmpm_rate_cents` (the per-member-per-month capitation rate in integer cents); a `SHARED_SAVINGS` contract must supply both `shared_savings_baseline_pmpm_cents` (the baseline medical cost per member per month against which savings are computed) and `shared_savings_split_pct` (the provider's share of any pooled savings, expressed as a number between 0 and 1). Mixing models — omitting the rate the chosen model requires — is rejected at creation with `ERR_PAYMENT_MODEL_MISMATCH` (HTTP 400). Rate fields belonging to the other model are not rejected; they are stored as supplied (null when omitted).

Both models share a quality-withhold mechanism. The `quality_withhold_pct` field defaults to 0.10 (ten percent of the gross payment held back) and `min_performance_threshold` defaults to 0.80 (the minimum composite performance score a member's measurement row must reach for that member to count toward the withhold release fraction). A contract that does not override these defaults accepts them.

### 2.9. Geography, Capacity, and Selector Discipline

Clinician routing is deterministic and geography-bound. A `CareProgram` declares `service_geography_zips`, the list of ZIP codes the program serves. A `Clinician` declares a `home_zip` and a `max_daily_visits` capacity; the system tracks an `active_daily_visit_count` per clinician that increments whenever a `Visit` is created or an `UrgentResponseEpisode` is dispatched to that clinician, and decrements when the visit or episode leaves the in-flight states (see §3.4 and §3.6); decrements floor at 0 — the counter never goes negative. A clinician is only eligible for an assignment if their `home_zip` is in the program's `service_geography_zips` list, their `status` is `ACTIVE`, and their `active_daily_visit_count` is strictly less than `max_daily_visits`. When the eligible pool is empty, the assignment is rejected with `ERR_NO_AVAILABLE_CLINICIAN` (HTTP 409).

A clinician's `urgent_response_qualified` flag (default `false`) further gates eligibility for urgent dispatches — only qualified clinicians may be dispatched to `URGENT` work. Discipline restrictions are described in §3.3 and §3.6.

### 2.10. Visit-Window Overlap Arithmetic

Two visit windows are considered overlapping when they intersect under half-open interval semantics: a window covering the half-open interval `[scheduled_start, scheduled_end)` overlaps another window on the same clinician if and only if the two half-open intervals share at least one instant. Back-to-back visits — where one's `scheduled_end` equals the other's `scheduled_start` — do not overlap. The check runs against every other visit currently in `SCHEDULED`, `EN_ROUTE`, or `IN_PROGRESS` status assigned to the same clinician, and a violation is reported as `ERR_VISIT_TIME_OVERLAP` (HTTP 409). This check fires on visit creation and on the reschedule transition.

## 3. Business Logic & Workflows

This section walks the platform's business workflows end to end, organized from population identification through settlement. Cross-references between subsections are intentional; many rules are scattered deliberately.

### 3.1. Program Setup, Payer Contracts, and the Provider Network

A `PlatformAdmin` establishes the operating envelope first. They register a `CareProgram` with a caller-supplied `program_code` (for example, `LANDMARK-TX-001` — the server does not enforce uniqueness of program codes), a human-readable `display_name`, the `service_geography_zips` list, and an optional `urgent_response_sla_hours` that defaults to 24 hours — the contractual ceiling from an urgent trigger to a clinician on scene. At creation the program's `current_period_index` is initialized to 0 and advances only via the operator's period-advance capability, which takes a `by_days` increment.

A `ContractAdministrator` then onboards the payer relationship by creating a `PayerContract` against the program, supplying `care_program_id`, `payer_name`, the `contract_effective_date` and `contract_expiration_date` date strings, and a `payment_model` of `CAPITATED` or `SHARED_SAVINGS`. The two dates are stored as supplied; `contract_expiration_date` is interpreted as an ISO 8601 timestamp only at settlement finalize time. The rate fields that must accompany each model, and the default withhold and threshold values, are described in §2.8. A contract whose `contract_expiration_date` has passed cannot be finalized into a settlement — the finalize transition is rejected with `ERR_CONTRACT_EXPIRED`.

The `PlatformAdmin` also registers the provider network. Each `PCPProvider` carries the program's `care_program_id`, a National Provider Identifier in `npi` (no uniqueness constraint is enforced), the provider's `full_name` and `practice_name`, and a `notification_opt_in` flag (default `true`) that governs whether the system dispatches visit-summary notifications and urgent-episode alerts to that PCP. Each `Clinician` carries the program's `care_program_id`, a `full_name`, a `discipline` of `NP` (nurse practitioner), `SW` (social worker), or `BH` (behavioral health clinician), a `home_zip`, a `max_daily_visits` capacity, and an optional `urgent_response_qualified` flag (default `false`). A newly registered clinician starts with `status` set to `ACTIVE` and `active_daily_visit_count` at 0. The `status` field takes one of two values, `ACTIVE` or `INACTIVE`; only `ACTIVE` clinicians are eligible for selector consideration (§2.9).

### 3.2. Member Identification and Provisional Risk Scoring

Members enter the platform from the payer's attribution feed. A `PlatformAdmin` or `EngagementSpecialist` registers a `Member` against the program and a specific contract, supplying `care_program_id`, `payer_contract_id` (each member is attributed to exactly one contract), the payer-side `member_external_id` (no uniqueness constraint is enforced), `full_name`, `date_of_birth`, the member's `address_zip`, the `pcp_provider_id` of the member's existing primary care physician — this program supplements and never replaces that relationship — a list of `chronic_condition_codes` drawn from the set {`CHF`, `COPD`, `CKD`, `DIABETES`, `DEMENTIA`, `DEPRESSION`, `HTN`} (any other code is rejected with `ERR_INVALID_REQUEST`), and the claims-history counters `prior_ed_visits_12mo` and `prior_inpatient_admits_12mo`.

At creation, the system computes a provisional risk score, `burden_score_provisional`, from claims history alone (the calculation is named `chronic_condition_burden_provisional` in the rule catalogue). The score is the sum of three components. First, each chronic condition code contributes a per-condition weight: `CHF` contributes 6 points, `COPD` 5, `CKD` 4, `DIABETES` 3, `DEMENTIA` 7, `DEPRESSION` 2, and `HTN` 1. Second, each prior emergency-department visit in the trailing twelve months contributes 3 points, so the `prior_ed_visits_12mo` count is multiplied by 3. Third, each prior inpatient admission in the trailing twelve months contributes 5 points, so the `prior_inpatient_admits_12mo` count is multiplied by 5. The three components are summed into a single integer; no rounding applies. The provisional score is recomputed whenever `chronic_condition_codes`, `prior_ed_visits_12mo`, or `prior_inpatient_admits_12mo` change.

A member's `risk_tier` is derived from the burden score against fixed thresholds. A score of at least 25 yields `VERY_HIGH`. A score of at least 15 but below 25 yields `HIGH`. A score of at least 8 but below 15 yields `MEDIUM`. A score below 8 yields `LOW`. Before any in-home assessment has been completed for the member, `burden_score_final` is null and `risk_tier` derives from `burden_score_provisional`; after the first completed initial assessment, `risk_tier` derives from `burden_score_final` instead (§3.5).

### 3.3. The Enrollment Funnel — Outreach, Consent, and Supersession

Each member moves through an enrollment funnel owned by the `EngagementSpecialist`. Creating an enrollment for a member requires the outreach `outreach_channel` (one of `PHONE`, `MAIL`, `IN_PERSON`, `PCP_REFERRAL`) and the optimistic-concurrency guard `expected_member_version` (§2.5). At creation the new `MemberEnrollment` starts in `IDENTIFIED` status with `is_current` set to `true` and `outreach_attempts` at 0, and any prior enrollment for the same member that was still `is_current` flips to `false`. At most one enrollment per member is `is_current` at any moment; this CREATE-with-supersede pattern is the platform's mechanism for re-engagement after a terminal outcome. Creating an enrollment also advances the parent `Member.version` by 1, which is precisely what later guards another writer's stale enrollment create.

From `IDENTIFIED`, the specialist begins outreach, transitioning the enrollment to `OUTREACH`. The same begin-outreach action is also the re-engagement path from `DECLINED` back to `OUTREACH`; the two paths are distinguished by their starting state, and a call against an enrollment in any status other than `IDENTIFIED` or `DECLINED` is rejected with `ERR_ENROLLMENT_NOT_IDENTIFIED`. Both paths require `is_current` to be `true` — operating on a superseded enrollment is rejected with `ERR_ENROLLMENT_SUPERSEDED` — and both reset `outreach_attempts` to 1, initializing the counter on first outreach and resetting it on re-engagement.

While in `OUTREACH`, the specialist records each subsequent contact by recording an attempt. This is a cyclic self-transition that leaves the enrollment in `OUTREACH` and increments `outreach_attempts` by 1. The counter caps at a maximum of 3 attempts. An attempt that would push `outreach_attempts` past the cap is rejected with `ERR_OUTREACH_ATTEMPTS_EXHAUSTED`; an attempt that brings the counter to exactly 3 fires an automatic transition to `DECLINED` with `disenrollment_reason` set to `NON_ENGAGEMENT`, and the same `ERR_OUTREACH_ATTEMPTS_EXHAUSTED` rejection surfaces on any subsequent record-attempt call. For this endpoint the cap check is evaluated first: once `outreach_attempts` has reached 3, record-attempt always reports `ERR_OUTREACH_ATTEMPTS_EXHAUSTED` regardless of the enrollment's current status — it pre-empts the state precondition below and the `is_current` invariant of §2.6. Calling record-attempt from any status other than `OUTREACH` (while the counter is still below the cap) is rejected with `ERR_ENROLLMENT_NOT_IN_OUTREACH`.

Consent is recorded from `OUTREACH` via record-consent, which requires a `consent_document_id` reference to the signed consent document; a missing document is rejected with `ERR_CONSENT_DOCUMENT_REQUIRED`. On success the enrollment moves to `CONSENTED`, the system stamps `consent_recorded_at` with the current logical clock, and a new `CareTeam` is automatically created for this enrollment in `DRAFT` status with its `enrollment_id` and `member_id` populated and all three clinician foreign keys (`primary_np_id`, `social_worker_id`, `behavioral_clinician_id`) null.

A member who declines is recorded via record-decline from `OUTREACH`, moving the enrollment to `DECLINED` with no other side effects. The `DECLINED → OUTREACH` re-engagement path described above is the cycle-closing edge.

Disenrollment ends the funnel, moving the enrollment to the terminal `DISENROLLED` state. From either `CONSENTED` or `ACTIVE`, a `disenrollment_reason` is required — one of `MEMBER_REQUEST`, `PAYER_TERMINATION`, `DECEASED`, `MOVED_OUT_OF_AREA`, or `NON_ENGAGEMENT` — and its absence is rejected with `ERR_DISENROLLMENT_REASON_REQUIRED`, while a value outside that set is rejected with `ERR_INVALID_REQUEST`. The state check and the `is_current` invariant are evaluated before the reason is examined. Calling disenroll from any other status is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The cascade differs by source state and is described fully in §3.7.

### 3.4. Care Team Composition and Activation

The `CareTeam` is owned by the `CareCoordinator` and gates both enrollment activation and visit scheduling. A care team starts in `DRAFT` with no clinicians assigned. The coordinator assigns or updates the team's clinicians by supplying any combination of `primary_np_id`, `social_worker_id`, and `behavioral_clinician_id`; the update endpoint carries no team-status precondition, slots omitted from the request body are left unchanged, and a slot explicitly supplied as null clears that assignment. Each assigned clinician must exist (else `ERR_CLINICIAN_NOT_FOUND`), must be in `ACTIVE` status, and must match the discipline implied by the slot — failure of the status or discipline requirement is rejected with `ERR_INVALID_REQUEST`: `primary_np_id` must reference a clinician with `discipline` equal to `NP`; `social_worker_id` must reference an `SW`; `behavioral_clinician_id` must reference a `BH`. After each assignment the system recomputes `composition_complete`, which is `true` only when all three slots are populated. Reading the care team (`GET`) returns a list envelope containing zero or one care team for the enrollment — an empty array when the enrollment has none yet — rather than a not-found error; `ERR_CARE_TEAM_NOT_FOUND` is raised only by the write endpoints (`PUT`, activate, suspend, reinstate) when no team exists for the enrollment.

Activating the care team requires the team to be in `DRAFT` (else `ERR_CARE_TEAM_NOT_DRAFT`) and requires `primary_np_id` to be populated, to reference an `ACTIVE` clinician, and to reference a clinician whose `discipline` is `NP` — failure of any of these is reported as `ERR_PRIMARY_NP_INVALID`. On success the team moves to `ACTIVE`. Only then can the parent enrollment be activated (see §3.5).

A team in `ACTIVE` may be moved to `SUSPENDED` by the coordinator (the only precondition is that the team really is `ACTIVE`, else `ERR_CARE_TEAM_NOT_ACTIVE`). While a team is `SUSPENDED`, any new visit creation against the parent enrollment is rejected with `ERR_CARE_TEAM_NOT_ACTIVE`. The coordinator may reinstate a `SUSPENDED` team back to `ACTIVE` — calling reinstate from any other status yields `ERR_CARE_TEAM_NOT_SUSPENDED`. Care teams have no direct retire action; instead, the team cascades to `RETIRED` whenever the parent enrollment disenrolls, regardless of whether the team was `DRAFT`, `ACTIVE`, or `SUSPENDED` at the time (§3.7).

### 3.5. Enrollment Activation, Visit Lifecycle, and the In-Home Assessment

Once a care team is `ACTIVE`, the `EngagementSpecialist` activates the enrollment. Activation requires the enrollment to be in `CONSENTED` (else `ERR_ENROLLMENT_NOT_CONSENTED`) and the associated care team to be `ACTIVE` (else `ERR_CARE_TEAM_NOT_ACTIVE`). On success the enrollment moves to `ACTIVE`, becoming eligible for visit scheduling and urgent-response episodes. Activation also seeds the performance infrastructure: a `PerformanceMeasurement` row is created for the triple of (`member.payer_contract_id`, `member.id`, `current_period_index`) if one does not already exist, with every counter at 0 and `composite_score` initialized to 1.0 — each of the score's components falls back to 1.0 when its denominator is empty (§3.7).

Visit scheduling is coordinator-driven. The coordinator creates a `Visit` against an `ACTIVE` enrollment by supplying `enrollment_id`, a `visit_type` of `INITIAL_ASSESSMENT`, `ROUTINE_FOLLOWUP`, or `POST_ED_FOLLOWUP`, and the window's `scheduled_start` and `scheduled_end`, where `scheduled_end` must be strictly later than `scheduled_start`. The server — never the client — assigns the `clinician_id` via a deterministic selector (the routine visit clinician selector, named `routine_visit_clinician_selector` in the rule catalogue). The selector's candidate pool is the set of `ACTIVE` clinicians in the same program as the member, whose `home_zip` is in the program's `service_geography_zips`, whose `discipline` matches the visit type's required discipline, and whose `active_daily_visit_count` is strictly less than their `max_daily_visits`. Required discipline is `NP` for every visit type this endpoint accepts: `INITIAL_ASSESSMENT`, `ROUTINE_FOLLOWUP`, and `POST_ED_FOLLOWUP` all require a nurse practitioner — social workers and behavioral clinicians are not eligible for these visits. A `visit_type` of `URGENT` is rejected at this endpoint with `ERR_INVALID_REQUEST`, immediately after the `enrollment_id` foreign key resolves and before window validation and the state preconditions; urgent work is dispatched through the urgent-episode workflow (§3.6). Within the eligible pool the selector ranks by lowest `active_daily_visit_count` first, then by earliest clinician `created_at`; the clinician `id` is never used as a tie-break. An empty pool is rejected with `ERR_NO_AVAILABLE_CLINICIAN`. The half-open overlap check from §2.10 runs against the chosen clinician's other in-flight visits before the create is committed. On success the new visit lands in `SCHEDULED`, the assigned clinician's `active_daily_visit_count` increments by 1, and the visit's `member_id` is denormalized from the enrollment for direct lookup.

From `SCHEDULED`, the assigned clinician — and only that clinician — drives the visit through its execution states. The clinician marks departure, moving the visit to `EN_ROUTE`; the call requires the visit really be `SCHEDULED` (else `ERR_VISIT_NOT_SCHEDULED`) and the caller's `X-User-ID` to equal the visit's `clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`). Arrival transitions the visit from `EN_ROUTE` to `IN_PROGRESS` (calling arrive from any other state yields `ERR_VISIT_NOT_EN_ROUTE`) and stamps `actual_start` with the current logical clock.

While the visit is `IN_PROGRESS`, the clinician captures the structured `VisitAssessment`. The create-or-update call requires only that the caller be the assigned clinician (and, if an assessment already exists for the visit, that it still be `DRAFT` — updating a non-`DRAFT` assessment is rejected with `ERR_ASSESSMENT_NOT_DRAFT`); it does not itself check the visit's status. Creating or updating the assessment stores it in `DRAFT` status against the visit's `visit_id`, with `member_id` denormalized from the visit. Any of the three structured objects may be omitted from a given call, leaving the stored value unchanged, but a structured object that is supplied must include every one of its subfields (else `ERR_INVALID_REQUEST`); `pcp_coordination_note` is optional at this stage and, when supplied, must be a string. The assessment payload is polymorphic but always carries four parts: a `medication_reconciliation` object containing `medications_reviewed`, `discrepancies_found`, and `high_risk_med_changes` (all integers); a `safety_evaluation` object containing `fall_risk_score` (an integer from 0 to 10), `home_hazard_count`, and `adl_impairment_count`; a `social_needs_screening` object containing the booleans `food_insecurity`, `housing_instability`, and `transportation_barrier` plus a `social_isolation_score` integer from 0 to 10; and a free-text `pcp_coordination_note` describing how the clinician coordinated with the member's PCP.

Submitting the assessment moves it from `DRAFT` to `SUBMITTED`. Calling submit when no assessment exists for the visit is rejected with `ERR_ASSESSMENT_NOT_FOUND`; otherwise the submit requires the assessment to be `DRAFT` (else `ERR_ASSESSMENT_NOT_DRAFT`), the parent visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), and all three structured objects — `medication_reconciliation`, `safety_evaluation`, and `social_needs_screening` — to be present and fully populated (else `ERR_ASSESSMENT_INCOMPLETE`). Reading the assessment (`GET`) returns a list envelope containing zero or one assessment — an empty array when the visit has none yet.

Completing the visit is the deepest cascade in the system. The complete call requires the visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), the caller to be the assigned clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), a `SUBMITTED` assessment to exist for the visit (else `ERR_ASSESSMENT_NOT_SUBMITTED`), and the assessment's `pcp_coordination_note` to be non-empty (else `ERR_PCP_COORDINATION_NOTE_REQUIRED`). On success, the visit moves to `COMPLETED` and `actual_end` is stamped with the current logical clock. The assigned clinician's `active_daily_visit_count` decrements by 1. The assessment locks into `LOCKED` status, after which it is immutable. The member's `burden_score_final` is recomputed from the assessment (§3.5 continues below), and the member's `risk_tier` is re-derived from that final score using the same thresholds as the provisional derivation. If the member's `PCPProvider` has `notification_opt_in` set to `true`, the system marks the assessment's `pcp_notified` as `true` to record that a visit-summary notification was dispatched; otherwise `pcp_notified` remains `false`. Finally, the `PerformanceMeasurement` row for the contract, member, and current period has `visits_completed` incremented by 1, `pcp_coordination_rate` recomputed as the fraction of all of the member's `COMPLETED` visits whose assessment has `pcp_notified` set to `true` (or 0 if no visits have completed), and `composite_score` recomputed per §3.7.

The `burden_score_final` recomputation (named `chronic_condition_burden_final` in the rule catalogue) uses the latest completed initial assessment for the member — specifically the `VisitAssessment` whose parent visit has `visit_type` equal to `INITIAL_ASSESSMENT` and `status` equal to `COMPLETED`, choosing the most recent by the visit's `actual_end` and breaking ties by the visit's `created_at` in ascending order; if no such completed initial assessment exists, `burden_score_final` is left unchanged. The final score starts from the member's `burden_score_provisional` as a base and adds three bonuses on top. The medication-reconciliation bonus is `discrepancies_found` multiplied by 1 plus `high_risk_med_changes` multiplied by 2. The safety bonus is `fall_risk_score` multiplied by 1 plus `home_hazard_count` multiplied by 1 plus `adl_impairment_count` multiplied by 2. The social-needs bonus is 2 points if `food_insecurity` is true (0 otherwise), plus 3 points if `housing_instability` is true (0 otherwise), plus 1 point if `transportation_barrier` is true (0 otherwise), plus `social_isolation_score` multiplied by 1. The four quantities — base, medication bonus, safety bonus, social bonus — are summed into `burden_score_final`, an integer point total. Because the final score incorporates in-home signals on top of claims history, the same member's `risk_tier` may step up after the first completed initial assessment even though their claims history did not change.

Off the happy path, three terminal branches handle the realities of field work. Cancelling a `SCHEDULED` visit is a coordinator action requiring a `cancellation_reason` of `MEMBER_REQUEST`, `CLINICIAN_UNAVAILABLE`, `MEMBER_NO_SHOW`, or `ENROLLMENT_ENDED`; its absence yields `ERR_CANCELLATION_REASON_REQUIRED` and a value outside that set yields `ERR_INVALID_REQUEST`, and calling cancel on a visit that is not `SCHEDULED` yields `ERR_VISIT_NOT_CANCELLABLE` — the state precondition is evaluated before the reason is examined. Cancellation moves the visit to `CANCELLED`, decrements the assigned clinician's `active_daily_visit_count` by 1, and increments `visits_cancelled` on the period's `PerformanceMeasurement` row (with `composite_score` recomputed). A cancelled visit is not necessarily lost: the coordinator may reschedule it back to `SCHEDULED` by supplying a new `scheduled_start` and `scheduled_end` along with the optimistic-concurrency guard `expected_visit_version` (§2.5). The reschedule requires the visit to be `CANCELLED` (else `ERR_VISIT_NOT_CANCELLED`), the visit's `reschedule_count` to be strictly less than the cap of 2 (else `ERR_MAX_RESCHEDULES_EXCEEDED`), the proposed window to clear the half-open overlap check against the clinician's other in-flight visits (else `ERR_VISIT_TIME_OVERLAP`), and the parent enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`). A successful reschedule increments `reschedule_count` by 1, updates `scheduled_start` and `scheduled_end` to the new window, re-increments the clinician's `active_daily_visit_count` by 1, decrements `visits_cancelled` by 1 with `composite_score` recomputed, and advances the visit's `version` by 1 — which is exactly the mechanism by which a concurrent writer's stale reschedule is caught.

The third terminal branch is the no-show. The assigned clinician may mark a `SCHEDULED` visit as `NO_SHOW` once the visit's window has passed: the current logical clock must be at or past `scheduled_end`, and calling before that moment is rejected with `ERR_VISIT_WINDOW_NOT_PAST`. The no-show transition decrements the clinician's `active_daily_visit_count` by 1 and increments `visits_no_show` on the period's measurement row (with `composite_score` recomputed). Calling mark-no-show on a visit that is not `SCHEDULED` yields `ERR_VISIT_NOT_SCHEDULED`; calling under a different clinician yields `ERR_NOT_ASSIGNED_CLINICIAN`.

### 3.6. Urgent Response Episodes and the 24-Hour SLA

The urgent lane runs in parallel with scheduled visits and exists to keep members out of the emergency department. Either a `CareCoordinator` or an `EngagementSpecialist` may trigger an `UrgentResponseEpisode` against an `ACTIVE` enrollment (any other enrollment status is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`) by supplying the `enrollment_id` and a `trigger_source` of `MEMBER_CALL`, `PCP_ALERT`, `PLAN_ALERT`, or `POST_ED_DISCHARGE`. At trigger time the episode lands in `TRIGGERED`, `triggered_at` is stamped with the current logical clock, `sla_deadline` is computed as `triggered_at` plus the parent program's `urgent_response_sla_hours` hours, `member_id` is denormalized from the enrollment, and the period's `PerformanceMeasurement` row has `urgent_episodes_triggered` incremented by 1 with `composite_score` recomputed.

Dispatching is coordinator-only and runs the urgent clinician selector (named `urgent_clinician_selector`). The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss). The urgent selector is stricter than the routine one: candidates must be `ACTIVE` clinicians in the same program as the member, must have `urgent_response_qualified` set to `true`, must have a `home_zip` in the program's `service_geography_zips`, and must have `active_daily_visit_count` strictly below `max_daily_visits`. Discipline is not restricted at dispatch — any discipline may respond to an urgent episode provided they are urgent-qualified. Ranking is by lowest `active_daily_visit_count`, then earliest clinician `created_at`; again, `id` is never a tie-break. An empty pool rejects the dispatch with `ERR_NO_AVAILABLE_CLINICIAN`, and the SLA clock continues to run — the rejection does not pause the deadline. A successful dispatch writes the chosen clinician into `dispatched_clinician_id`, moves the episode to `DISPATCHED`, and increments that clinician's `active_daily_visit_count` by 1.

The dispatched clinician — and only that clinician — marks arrival. The arrive call requires the episode to be `DISPATCHED` (else `ERR_EPISODE_NOT_DISPATCHED`) and the caller's `X-User-ID` to equal `dispatched_clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`). Arrival moves the episode to `ON_SCENE`, stamps `on_scene_at` with the current logical clock, and computes `sla_met` as the boolean outcome of `on_scene_at` being at or before `sla_deadline`.

Resolution requires the episode to be `ON_SCENE` (else `ERR_EPISODE_NOT_ON_SCENE`) and a `resolved_outcome` of `AVOIDED_ED` or `REFERRED_TO_ED` (its absence is rejected with `ERR_RESOLUTION_OUTCOME_REQUIRED`, and any other value with `ERR_INVALID_REQUEST`); only then is the caller checked to be the dispatched clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`). On success the episode moves to `RESOLVED` and the dispatched clinician's `active_daily_visit_count` decrements by 1. If `resolved_outcome` is `AVOIDED_ED`, the period's measurement row has `urgent_episodes_avoided_ed` incremented by 1. Independently, if `sla_met` is `true`, the same row has `urgent_episodes_sla_met` incremented by 1. The `composite_score` is then recomputed. The `REFERRED_TO_ED` branch carries an additional cascade: the system creates a new `Visit` with `visit_type` set to `POST_ED_FOLLOWUP`, status `SCHEDULED`, assigned to the care team's `primary_np_id`, on a window spanning from the current logical clock to 72 hours later. This cascade bypasses the clinician selector, the capacity gate, and the half-open overlap check entirely; when a primary NP is assigned, that clinician's `active_daily_visit_count` increments by 1, and if the enrollment has no care team or no primary NP the visit is created with a null `clinician_id` and no capacity counter moves. This is the platform's guarantee that an ED referral does not silently drop the member — a follow-up is always on the books.

Episodes that stall lapse automatically. When the lapse sweep runs and finds that the logical clock has advanced past an episode's `sla_deadline` while the episode is still `TRIGGERED` or still `DISPATCHED`, the system transitions the episode to `LAPSED`, sets `sla_met` to `false`, and recomputes `composite_score` on the period's measurement row — the lapsed episode remains counted in `urgent_episodes_triggered` but never reaches `urgent_episodes_sla_met`, depressing the SLA ratio. A lapse from `DISPATCHED` additionally decrements the dispatched clinician's `active_daily_visit_count` by 1, releasing the capacity reservation. Both the program's period-advance capability and the operator's clock-advance-hours capability trigger this sweep; the set-the-clock-to-an-arbitrary-timestamp capability does not (§2.4).

### 3.7. Performance Measurement, Withhold Release, and Settlement

Every `PerformanceMeasurement` row tracks one (contract, member, period) triple. The row carries the contract as `payer_contract_id` (derived through the member's attribution), the member as `member_id`, and the `period_index` captured from the program's `current_period_index` at the moment the row was first written. The counters — `urgent_episodes_triggered`, `urgent_episodes_sla_met`, `urgent_episodes_avoided_ed`, `visits_completed`, `visits_no_show`, `visits_cancelled` — accumulate per the workflows above. The `pcp_coordination_rate` is the fraction of the member's `COMPLETED` visits whose assessment has `pcp_notified` set to `true`, or 0 if no visits have completed; it is computed across all of the member's completed visits, not only those of the row's period.

The `composite_score` (computed by the rule named `composite_performance_score`) blends four components, each in the range [0, 1], with two-stage round-half-up at 4 decimal places (§2.7). The SLA component is `urgent_episodes_sla_met` divided by `urgent_episodes_triggered`, falling back to 1.0 when no urgent episodes have been triggered. The ED-avoidance component is `urgent_episodes_avoided_ed` divided by `urgent_episodes_triggered`, with the same 1.0 fallback on an empty denominator. The visit-completion component is `visits_completed` divided by the sum of `visits_completed`, `visits_no_show`, and `visits_cancelled`, again falling back to 1.0 when the denominator is empty. The PCP-coordination component is the `pcp_coordination_rate` itself. Each component is first rounded to 4 decimal places with round-half-up. The weighted sum then multiplies the SLA component by 0.40, the ED-avoidance component by 0.30, the visit-completion component by 0.20, and the PCP-coordination component by 0.10, sums the four products, and rounds the result to 4 decimal places with round-half-up. The composite score is recomputed on every counter update — visit completed, cancelled, or marked no-show; episode triggered, resolved, or lapsed; enrollment activated or disenrolled.

Settlement runs per contract per period and is initiated by the `ContractAdministrator`. Generating a settlement creates a `PayerSettlement` in `PROVISIONAL` status with `period_index` set to the program's current `current_period_index`, and runs the payment-model-appropriate calculation — `capitated_settlement_amount` for a `CAPITATED` contract or `shared_savings_settlement_amount` for a `SHARED_SAVINGS` contract. The `enrolled_member_count` for the period is the count of distinct members attributed to this contract for whom there exists a `MemberEnrollment` that was in `ACTIVE` status at any point during the period (the rule that defines this counting is named `enrolled_member_months`). For the first settlement of a contract, the period spans from program creation to the current `current_period_index`; for later settlements the period spans from the previous settlement's `period_index` to the current one, where "previous" means the greatest `period_index` among all existing settlements for the same contract, regardless of their status (including `VOIDED`). Generating a settlement for a period that already has one is permitted; each generation creates a new `PROVISIONAL` row whose computed amounts are frozen at creation.

For a `CAPITATED` contract, the gross is `enrolled_member_count` multiplied by the contract's `pmpm_rate_cents`, recorded as `gross_capitation_cents`; `gross_savings_share_cents` is null on this branch. The quality withhold is computed on the gross: `quality_withhold_cents` is the product of `gross_capitation_cents` and the contract's `quality_withhold_pct`, rounded half-up to integer cents at the aggregate.

For a `SHARED_SAVINGS` contract, the gross is computed in a pinned multi-step order — per-member delta first, then pooling, then split, then withhold, then release — so that no reader can accidentally compute the withhold before the pool. First, for each enrolled member, `member_actual_cents` is the sum of `MedicalCost.amount_cents` for that member in the settlement's `period_index` (a `ContractAdministrator` records `MedicalCost` rows as costs are observed, supplying `payer_contract_id`, `member_id`, `period_index`, `amount_cents`, and `incurred_date`, where `period_index` and `amount_cents` must be integers greater than or equal to 0). The `member_delta_cents` is the contract's `shared_savings_baseline_pmpm_cents` minus `member_actual_cents`; a positive delta is savings, a negative delta is a loss. Second, the per-member deltas are pooled: `pooled_savings_cents` is the sum of `member_delta_cents` across all enrolled members, so losing members offset winning members. Third, the pool is floored at zero: if `pooled_savings_cents` is less than or equal to 0 the provider's gross share is 0 (there is no clawback); otherwise `gross_savings_share_cents` is the product of `pooled_savings_cents` and the contract's `shared_savings_split_pct`, rounded half-up to integer cents. On this branch `gross_capitation_cents` is null. Fourth, `quality_withhold_cents` is the product of `gross_savings_share_cents` and `quality_withhold_pct`, rounded half-up to integer cents — the same shape as the capitated branch.

While a settlement is `PROVISIONAL`, changes to enrollment or to measurement counters flow through and the row may be recomputed; `withhold_released_cents` and `net_payment_cents` remain null. Finalizing the settlement — a coordinator-independent administrator action — requires the settlement to be `PROVISIONAL` (else `ERR_SETTLEMENT_NOT_PROVISIONAL`) and the contract to be on or before its `contract_expiration_date` (else `ERR_CONTRACT_EXPIRED`). At finalize time the system computes the release fraction: `qualifying_member_count` is the number of `PerformanceMeasurement` rows for this contract and period whose `composite_score` is greater than or equal to the contract's `min_performance_threshold`; `release_fraction` is `qualifying_member_count` divided by `enrolled_member_count`, or 0 if `enrolled_member_count` is 0. The `withhold_released_cents` is then the product of `quality_withhold_cents` and `release_fraction`, rounded half-up to integer cents. The `net_payment_cents` is the gross minus the withhold plus the released withhold — for a `CAPITATED` contract, `gross_capitation_cents` minus `quality_withhold_cents` plus `withhold_released_cents`; for a `SHARED_SAVINGS` contract, `gross_savings_share_cents` minus `quality_withhold_cents` plus `withhold_released_cents`. The settlement moves to `FINALIZED`.

A `FINALIZED` settlement may be marked paid, moving it to `PAID`; the call requires `FINALIZED` status and is otherwise rejected with `ERR_SETTLEMENT_NOT_FINALIZED`. A `PROVISIONAL` settlement may alternatively be voided — moving it to `VOIDED` — with the same `ERR_SETTLEMENT_NOT_PROVISIONAL` precondition as finalize. `PAID` and `VOIDED` are terminal.

Disenrollment reverberates through settlement. When an `ACTIVE` enrollment disenrolls, every `SCHEDULED` visit child of the enrollment cascades to `CANCELLED` with `cancellation_reason` set to `ENROLLMENT_ENDED`, and each cascaded cancellation decrements its assigned clinician's `active_daily_visit_count` by 1. The care team for the enrollment cascades to `RETIRED` — this is the only path by which a care team reaches `RETIRED`, and it fires whether the team was `DRAFT`, `ACTIVE`, or `SUSPENDED`. The enrollment's `is_current` flips to `false`. Finally, the period's `PerformanceMeasurement` row is recomputed with the departing member excluded from the enrolled-member count going forward. When a `CONSENTED` enrollment disenrolls (no visits have yet been scheduled), the cascade is the same minus the visit cancellation: the care team retires and `is_current` flips, but no clinician counters move.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; all other successful operations, including state transitions, return HTTP 200. List endpoints paginate per §2.3 and sort by `created_at` ascending; each list endpoint additionally honours the optional equality filters of §2.3 for the fields its resource carries. Request and response payloads are described in §3 narratives; this table is the authoritative method-and-path index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /care-programs | Create a care program | PlatformAdmin |
| GET | /care-programs | List care programs | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, Clinician, PerformanceAnalyst |
| GET | /care-programs/{programId} | Get a care program | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, Clinician, PerformanceAnalyst |
| POST | /care-programs/{programId}/clock/advance | Advance the program logical period by N days | PlatformAdmin |
| POST | /payer-contracts | Create a payer contract | ContractAdministrator |
| GET | /payer-contracts | List payer contracts | PlatformAdmin, ContractAdministrator, CareCoordinator, PerformanceAnalyst |
| GET | /payer-contracts/{contractId} | Get a payer contract | PlatformAdmin, ContractAdministrator, CareCoordinator, PerformanceAnalyst |
| POST | /medical-costs | Record an observed medical cost row | ContractAdministrator |
| GET | /medical-costs | List medical cost rows | PlatformAdmin, ContractAdministrator, PerformanceAnalyst |
| POST | /pcp-providers | Register a PCP provider | PlatformAdmin |
| GET | /pcp-providers | List PCP providers | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist |
| GET | /pcp-providers/{pcpId} | Get a PCP provider | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist |
| POST | /clinicians | Register a clinician | PlatformAdmin |
| GET | /clinicians | List clinicians | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician |
| GET | /clinicians/{clinicianId} | Get a clinician | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician |
| POST | /members | Register a member from payer data feed | PlatformAdmin, EngagementSpecialist |
| GET | /members | List members | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, PerformanceAnalyst |
| GET | /members/{memberId} | Get a member | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, Clinician, PerformanceAnalyst |
| POST | /members/{memberId}/enrollments | Create a new enrollment (CREATE-with-supersede; OCC on member) | EngagementSpecialist |
| GET | /members/{memberId}/enrollments | List enrollments for a member | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, PerformanceAnalyst |
| GET | /enrollments | Filtered list of all enrollments | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, PerformanceAnalyst |
| GET | /enrollments/{enrollmentId} | Get an enrollment | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, PerformanceAnalyst |
| POST | /enrollments/{enrollmentId}/begin-outreach | Begin (or resume from DECLINED) outreach | EngagementSpecialist |
| POST | /enrollments/{enrollmentId}/record-attempt | Record an outreach attempt (cyclic) | EngagementSpecialist |
| POST | /enrollments/{enrollmentId}/record-consent | Record member consent | EngagementSpecialist |
| POST | /enrollments/{enrollmentId}/record-decline | Record member decline | EngagementSpecialist |
| POST | /enrollments/{enrollmentId}/activate | Activate enrollment (requires ACTIVE care team) | EngagementSpecialist |
| POST | /enrollments/{enrollmentId}/disenroll | Disenroll member (cascades) | EngagementSpecialist |
| GET | /enrollments/{enrollmentId}/care-team | Get the care team for an enrollment (1:1) | PlatformAdmin, ContractAdministrator, CareCoordinator, EngagementSpecialist, PerformanceAnalyst |
| PUT | /enrollments/{enrollmentId}/care-team | Assign or update care team members | CareCoordinator |
| POST | /enrollments/{enrollmentId}/care-team/activate | Activate the care team | CareCoordinator |
| POST | /enrollments/{enrollmentId}/care-team/suspend | Suspend the care team | CareCoordinator |
| POST | /enrollments/{enrollmentId}/care-team/reinstate | Reinstate a suspended care team | CareCoordinator |
| POST | /visits | Schedule a new visit | CareCoordinator |
| GET | /visits | List visits | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician, PerformanceAnalyst |
| GET | /visits/{visitId} | Get a visit | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician, PerformanceAnalyst |
| POST | /visits/{visitId}/depart | Clinician departs for visit (SCHEDULED → EN_ROUTE) | Clinician |
| POST | /visits/{visitId}/arrive | Clinician arrives (EN_ROUTE → IN_PROGRESS) | Clinician |
| POST | /visits/{visitId}/assessment | Create or update the visit's assessment (DRAFT) | Clinician |
| GET | /visits/{visitId}/assessment | Get the visit's assessment (1:1) | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician, PerformanceAnalyst |
| POST | /visits/{visitId}/assessment/submit | Submit the assessment (DRAFT → SUBMITTED) | Clinician |
| POST | /visits/{visitId}/complete | Complete the visit (IN_PROGRESS → COMPLETED) | Clinician |
| POST | /visits/{visitId}/cancel | Cancel a scheduled visit | CareCoordinator |
| POST | /visits/{visitId}/reschedule | Reschedule a cancelled visit (CANCELLED → SCHEDULED; OCC) | CareCoordinator |
| POST | /visits/{visitId}/mark-no-show | Mark a scheduled visit as no-show | Clinician |
| POST | /urgent-episodes | Trigger a new urgent response episode | CareCoordinator, EngagementSpecialist |
| GET | /urgent-episodes | List urgent episodes | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician, PerformanceAnalyst |
| GET | /urgent-episodes/{episodeId} | Get an urgent episode | PlatformAdmin, ContractAdministrator, CareCoordinator, Clinician, PerformanceAnalyst |
| POST | /urgent-episodes/{episodeId}/dispatch | Dispatch a clinician to an urgent episode | CareCoordinator |
| POST | /urgent-episodes/{episodeId}/arrive | Mark clinician on scene | Clinician |
| POST | /urgent-episodes/{episodeId}/resolve | Resolve an urgent episode | Clinician |
| GET | /performance-measurements | List performance measurement rows | PlatformAdmin, ContractAdministrator, PerformanceAnalyst |
| GET | /performance-measurements/{measurementId} | Get a single performance measurement | PlatformAdmin, ContractAdministrator, PerformanceAnalyst |
| POST | /payer-contracts/{contractId}/settlements | Generate a settlement for the current period | ContractAdministrator |
| GET | /payer-contracts/{contractId}/settlements | List settlements for a contract | PlatformAdmin, ContractAdministrator, PerformanceAnalyst |
| GET | /settlements/{settlementId} | Get a settlement | PlatformAdmin, ContractAdministrator, PerformanceAnalyst |
| POST | /payer-contracts/{contractId}/settlements/{settlementId}/finalize | Finalize a settlement | ContractAdministrator |
| POST | /payer-contracts/{contractId}/settlements/{settlementId}/mark-paid | Mark a finalized settlement paid | ContractAdministrator |
| POST | /payer-contracts/{contractId}/settlements/{settlementId}/void | Void a provisional settlement | ContractAdministrator |
| POST | /_clock/set_current_utc | Set the server's logical clock to an arbitrary ISO 8601 timestamp | PlatformAdmin |
| POST | /_clock/advance_hours | Advance the logical clock by N hours; triggers LAPSED sweep | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 narratives; this table is the authoritative id-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_PCP_NOT_FOUND | 404 |
| ERR_CLINICIAN_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_CARE_TEAM_NOT_FOUND | 404 |
| ERR_VISIT_NOT_FOUND | 404 |
| ERR_ASSESSMENT_NOT_FOUND | 404 |
| ERR_EPISODE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_MEASUREMENT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_PAYMENT_MODEL_MISMATCH | 400 |
| ERR_CONSENT_DOCUMENT_REQUIRED | 400 |
| ERR_DISENROLLMENT_REASON_REQUIRED | 400 |
| ERR_CANCELLATION_REASON_REQUIRED | 400 |
| ERR_RESOLUTION_OUTCOME_REQUIRED | 400 |
| ERR_PCP_COORDINATION_NOTE_REQUIRED | 400 |
| ERR_ASSESSMENT_INCOMPLETE | 400 |
| ERR_ENROLLMENT_NOT_IDENTIFIED | 409 |
| ERR_ENROLLMENT_NOT_IN_OUTREACH | 409 |
| ERR_ENROLLMENT_NOT_CONSENTED | 409 |
| ERR_ENROLLMENT_NOT_ACTIVE | 409 |
| ERR_ENROLLMENT_SUPERSEDED | 409 |
| ERR_OUTREACH_ATTEMPTS_EXHAUSTED | 409 |
| ERR_CARE_TEAM_NOT_DRAFT | 409 |
| ERR_CARE_TEAM_NOT_ACTIVE | 409 |
| ERR_CARE_TEAM_NOT_SUSPENDED | 409 |
| ERR_PRIMARY_NP_INVALID | 409 |
| ERR_VISIT_NOT_SCHEDULED | 409 |
| ERR_VISIT_NOT_EN_ROUTE | 409 |
| ERR_VISIT_NOT_IN_PROGRESS | 409 |
| ERR_VISIT_NOT_CANCELLABLE | 409 |
| ERR_VISIT_NOT_CANCELLED | 409 |
| ERR_ASSESSMENT_NOT_DRAFT | 409 |
| ERR_ASSESSMENT_NOT_SUBMITTED | 409 |
| ERR_EPISODE_NOT_TRIGGERED | 409 |
| ERR_EPISODE_NOT_DISPATCHED | 409 |
| ERR_EPISODE_NOT_ON_SCENE | 409 |
| ERR_SETTLEMENT_NOT_PROVISIONAL | 409 |
| ERR_SETTLEMENT_NOT_FINALIZED | 409 |
| ERR_NOT_ASSIGNED_CLINICIAN | 403 |
| ERR_NO_AVAILABLE_CLINICIAN | 409 |
| ERR_VISIT_TIME_OVERLAP | 409 |
| ERR_MAX_RESCHEDULES_EXCEEDED | 409 |
| ERR_SLA_ALREADY_LAPSED | 409 |
| ERR_VISIT_WINDOW_NOT_PAST | 409 |
| ERR_CONTRACT_EXPIRED | 409 |
| ERR_STALE_VERSION | 412 |
