# Reverse Nurse Marketplace API — Product Requirements Document

## 1. Introduction

Hospitals struggle to hire nurses; nurses struggle to be seen. This product flips the conventional job board on its head: rather than nurses applying to hundreds of requisitions into a black hole, employers browse a curated pool of verified candidates and initiate applications *to* the nurse. The reverse-marketplace dynamic forces speed — every application an employer submits arrives with a binding response deadline, every offer expires on a clock, and every placement carries a guarantee window that converts hiring risk into a refundable fee.

This document specifies the API that powers that marketplace, mounted under `/marketplace`. It covers the full lifecycle: nurse profile creation and license verification; employer registration under either a subscription or per-placement billing model; requisition authoring and algorithmic candidate matching; employer-initiated applications with candidate response deadlines; interview scheduling under per-nurse overlap and per-unit daily-capacity rules; credential and background screening running on parallel axes; offer issuance, acceptance, and the placement cascade that follows; and finally the guarantee window, termination refunds, and invoice settlement that close the financial loop. Because nurse livelihoods are at stake, confidentiality is a first-class invariant — a nurse can hide their profile from their current employer, and the system enforces that cloak at matching time, at read time, and at application-creation time.

A logical clock underlies every deadline, expiry, and guarantee computation in the system. The marketplace does not trust wall-clock time; a platform-controlled clock drives all time-based behavior so that deadlines, expirations, and cascades are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring their capacity. The system recognizes exactly three roles, spelled as follows: `Candidate`, `Employer`, and `PlatformAdmin`. A request missing either header, carrying a role outside this enumeration, or — for an entity-backed role — omitting `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint, or whose `X-User-ID` does not match the owning entity on an ownership-scoped endpoint, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics are as follows. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Nurse`; ownership checks on any resource that references a nurse compare the resource's `nurse_id` foreign key to `X-User-ID`. When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an employer compare the resource's `employer_id` foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated via two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Every list response's `meta` object carries `limit`, `offset`, `total_count`, and `has_more`. Unless otherwise specified, all list endpoints sort by `created_at` ascending.

### 2.4. The Logical Clock

All time-dependent behavior — deadlines, expirations, guarantee windows, day buckets — reads a single logical clock, never wall-clock time. Before any administrative call sets it, the clock reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time. A `PlatformAdmin`-only capability advances the clock by supplying a `current_utc` instant; the response echoes `current_utc` verbatim — the exact string the client supplied — and reports `fired_transitions`, the count of system transitions the advance triggered.

Advancing the clock fires every due system transition in a deterministic order: license expirations first, then application deadline expirations, then offer expirations, then placement start and guarantee transitions. Each fired transition executes its documented cascades in full — for example, a license expiration that flips a nurse's verified status can push an `ACTIVE` nurse to `INACTIVE` inside the same clock advance.

### 2.5. Common Resource Properties

Every primary resource — Nurse, LicenseVerification, Employer, Requisition, Application, Interview, Offer, Screening, OnboardingDocument, Placement, and Invoice — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, refreshed on every mutation; and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource.

Two resources are exceptions. **Certification** rows are immutable attachments: they carry `id` and `created_at` only — both `updated_at` and `version` are absent. **Match** rows are regenerated artifacts and likewise carry `id` and `created_at` only, with no `updated_at` and no `version`; a match additionally records `generated_at`, the logical-clock timestamp of the generation run that produced it.

### 2.6. Nested Resource Retrieval and Existence Ordering

Requests that reference resources through path segments or body identifiers are validated left-to-right: the system first confirms that every referenced nurse, employer, requisition, application, interview, offer, screening, document, placement, and invoice exists, in the order those references appear in the request, before evaluating any state or business rule. The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Existence checks (priority 3) always run after authentication (priority 1) and authorization (priority 2), and before state-machine legality (priority 4) and every business rule (priorities 5 through 11). Within business rules, deadline checks (priority 5) precede confidentiality (priority 6), which precede credential gates (priority 7), which precede matching-field constraints (priority 8), which precede scheduling conflicts (priority 9) and unit day-capacity (priority 9.5), which precede quota checks (priority 10), which precede duplicate guards (priority 11). A request that fails several checks surfaces the error from the earliest-priority check that fails.

### 2.7. Optimistic Concurrency Control

Two write endpoints guard their parent entities against stale reads. Neither framing depends on requests overlapping in time; the rule is purely that the client's last observed version must still be current at write time.

Creating an application — the employer-initiated application write — requires the request to carry `expected_nurse_version`, a non-optional field holding the `version` of the target `Nurse` as the employer last observed it. If the nurse's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_NURSE_VERSION` (HTTP 412). Issuing an offer on an application requires `expected_requisition_version`, likewise non-optional, holding the `version` of the parent `Requisition` as last observed; a mismatch with the requisition's current `version` is rejected with `ERR_STALE_REQUISITION_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.8. Candidate Confidentiality

A nurse's profile carries `confidentiality_exclusions`, an array of employer ids the nurse hides from; it defaults to an empty array at registration. The cloak is enforced in three places, with three different mechanics. At match generation, a requisition whose `employer_id` appears in the nurse's `confidentiality_exclusions` still produces a `Match` row, but that row is persisted with `suppressed` set to true and is never returned to the `Employer` role. At application creation, an employer named in the nurse's `confidentiality_exclusions` who attempts to initiate an application to that nurse is rejected with `ERR_CANDIDATE_CONFIDENTIAL` (HTTP 403). At read time, an employer who is excluded receives `ERR_NOT_FOUND` when reading the nurse's profile — the cloak pretends the nurse does not exist rather than admitting the exclusion.

### 2.9. Monetary Values and Precision

All monetary amounts are integer cents; no floating-point arithmetic appears anywhere in the financial pipeline. Rates such as `desired_hourly_rate_cents`, `offered_hourly_rate_cents`, and `proposed_hourly_rate_cents` are whole cents per hour. Where a calculation produces a fractional cent — the per-placement fee computation and the guarantee refund computation — the result is rounded half-up, and rounding is applied exactly once, to the final product or quotient, never to an intermediate fraction. Match scores are integers, rounded half-up only at the final step with no intermediate rounding. SLA measurements are whole hours, truncated toward zero.

### 2.10. Hierarchical Consistency and Cascading Mutations

State transitions on one entity routinely mutate others. Accepting an offer creates a placement, fills a requisition seat, hires the nurse, and issues an invoice in one atomic cascade; terminating a placement inside its guarantee window refunds the invoice, reopens the requisition seat, and returns the nurse to the market. Every such cascade increments the `version` and refreshes the `updated_at` of each entity it mutates. The system maintains a conservation invariant across all of this: for every requisition, `openings_filled` always equals the count of its placements in `PENDING_START`, `GUARANTEE_ACTIVE`, or `COMPLETED`, and always satisfies zero at minimum and `openings_total` at maximum. Placements in `TERMINATED_IN_GUARANTEE` are excluded from the count — the seat returns to the pool in the same request that terminates the placement.

## 3. Business Logic & Workflows

### 3.1. Nurse Registration, Licensing, and Market Entry

A nurse enters the marketplace by self-registering as a `Candidate`. Registration captures `full_name`, a login `email` that must be unique across all nurses (a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`), the two-letter `home_state`, a `primary_specialty` drawn from `ICU`, `ER`, `MED_SURG`, `TELEMETRY`, `OR`, `PEDIATRICS`, `LABOR_DELIVERY`, or `ONCOLOGY`, whole `years_experience` between 0 and 60, a `desired_shift` of `DAY`, `NIGHT`, or `ROTATING`, a floor `desired_hourly_rate_cents` of at least 2000 cents, a `max_commute_miles` between 1 and 500, and the nurse's `current_employer_name` — an empty string when the nurse is unemployed. Malformed bodies, missing required fields, out-of-range enums, or numeric range violations (a rate below 2000 cents, for instance) are rejected with `ERR_VALIDATION` (HTTP 400). The new profile starts in `DRAFT` with `version` 1.

Before a profile can reach the market, the nurse submits at least one **LicenseVerification**, supplying `nurse_id`, the state-issued `license_number` (unique within its `license_state`; duplicates rejected with `ERR_DUPLICATE_RESOURCE`), the two-letter `license_state`, and an `expiry_date`. A verification starts `PENDING`. Once at least one verification exists in `PENDING` or `VERIFIED`, the nurse — still acting as `Candidate` on their own profile — submits the profile, moving it from `DRAFT` to `PENDING_VERIFICATION`.

From `PENDING_VERIFICATION` two system-driven outcomes exist. The moment a `PlatformAdmin` verifies a license — which requires the verification still be `PENDING` and its `expiry_date` be strictly after the clock's current date, otherwise the verify action is rejected with `ERR_LICENSE_EXPIRED` (HTTP 422) — the nurse's `license_verified` flag is recomputed. That flag is true if and only if the nurse has exactly one verification in `VERIFIED` whose `license_state` equals the nurse's `home_state` and whose `expiry_date` is strictly after clock now, and it is recomputed on every verification transition and every clock advance. When the flag flips true while the nurse is `PENDING_VERIFICATION`, the nurse activates: status becomes `ACTIVE`, and — this is the confidentiality bootstrap — if `current_employer_name` is non-empty and an `Employer` row exists whose `legal_name` equals it, that employer's id is appended to the nurse's `confidentiality_exclusions`. Conversely, if the nurse's last non-expired verification is rejected by a `PlatformAdmin` (the reject action requires a `rejection_reason` in the body; a missing one is rejected with `ERR_REVIEW_NOTE_REQUIRED`) and no other verification remains `PENDING`, the nurse reverts to `DRAFT`. A verification in `VERIFIED` transitions to `EXPIRED` on any clock advance that reaches or passes its `expiry_date`, and if that expiration flips `license_verified` to false while the nurse is `ACTIVE`, the nurse falls to `INACTIVE`.

An `ACTIVE` nurse may leave the market voluntarily. Deactivation moves `ACTIVE` to `INACTIVE` but is permitted only when the nurse's `active_application_count` — the count of their applications in `SUBMITTED` or `UNDER_REVIEW` — is zero in the sense that no application exists in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED`; attempting deactivation with any such live application is rejected with `ERR_NURSE_HAS_LIVE_APPLICATIONS` (HTTP 409). Reactivation moves `INACTIVE` back to `ACTIVE` and requires that `license_verified` be true at reactivation time; a reactivation attempted when `license_verified` is false is rejected with `ERR_CREDENTIALS_INCOMPLETE` (HTTP 422) at the credential-gate priority, while a reactivation attempted from any state other than `INACTIVE` is rejected with `ERR_INVALID_STATE`. Either state may instead withdraw permanently: withdrawal moves the nurse to the terminal `WITHDRAWN`, requires that the nurse have no placement in `PENDING_START` or `GUARANTEE_ACTIVE`, and cascades — every application of theirs in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to `WITHDRAWN`, and any application in `OFFER_EXTENDED` sees its attached offer cascade to `RESCINDED`. Any transition attempted from a state where it does not exist is rejected with `ERR_INVALID_STATE` (HTTP 409).

Separately from licensing, a nurse attaches immutable **Certification** rows to their profile by supplying `nurse_id`, a `cert_code` of `BLS`, `ACLS`, `PALS`, `CCRN`, `CEN`, `RNC`, or `ONC`, and an `expires_on` date that must be strictly after the clock's current date at creation — a certification already lapsed is rejected with `ERR_LICENSE_EXPIRED`. Certification rows never mutate: they carry no `updated_at` and no `version`.

### 3.2. Employer Registration and Requisition Authoring

Hospitals enter through a `PlatformAdmin`, who registers an **Employer** in `ACTIVE` status with `credit_balance_cents` starting at zero. Registration captures the hospital's `legal_name`, the two-letter `facility_state` of the hiring facility, a `fee_model` of `SUBSCRIPTION` or `PER_PLACEMENT`, a `subscription_tier` of `BASIC`, `PRO`, or `ENTERPRISE` (meaningful only under the subscription model), an `sla_response_hours` service level between 24 and 168 whole hours, a `guarantee_days` window between 30 and 120 days, and a `placement_fee_bps` between 500 and 3000 basis points (meaningful only under the per-placement model). An `sla_response_hours` outside its range is rejected with `ERR_VALIDATION`.

A `PlatformAdmin` may suspend an `ACTIVE` employer, moving it to `SUSPENDED`, and later reinstate it. Suspension blocks two operations for that employer: initiating new applications and issuing offers, both rejected with `ERR_NO_OPENINGS` (HTTP 409) at the quota-check priority.

An `Employer` authors a **Requisition** for one of its units, supplying `employer_id`, a `specialty` from the same enum as nurse specialties, a `unit_name` such as "ICU-4West", a `required_certs` array of certification codes every matched nurse must hold unexpired (the array may be empty), the `facility_state` where the unit sits, a `distance_from_facility_miles` tag between 0 and 500 used for geography matching, a `shift` of `DAY`, `NIGHT`, or `ROTATING`, an `offered_hourly_rate_cents` floor of at least 2000 cents, and `openings_total` between 1 and 20 seats. A requisition starts `OPEN` with `openings_filled` at zero.

The employer who owns a requisition may pause it (`OPEN` to `PAUSED`), resume it (`PAUSED` to `OPEN`, permitted only while `openings_filled` is still below `openings_total`), or close it from `OPEN`, `PAUSED`, or `FILLED` — closure requires that no application against the requisition be in `OFFER_EXTENDED`, and cascades every application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` to `WITHDRAWN`. Two transitions are system-driven: when a placement fills the last seat, the requisition moves `OPEN` to `FILLED` and cascades — applications in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` go to `WITHDRAWN`, and any in `OFFER_EXTENDED` see their offers cascade to `RESCINDED`. When a placement on a `FILLED` requisition is later terminated inside its guarantee window, the seat returns and the requisition moves `FILLED` back to `OPEN`.

Shift preference semantics are deliberately subtle. A `DAY` shift occupies the closed interval from 07:00 through 19:00 — both endpoints included. A `NIGHT` shift occupies the interval from 19:00 up to but not including 07:00 the next morning, wrapping midnight: 19:00 belongs to night, 07:00 belongs to day. A `ROTATING` shift occupies both windows and therefore overlaps everything; a nurse whose `desired_shift` is `ROTATING` matches any requisition shift. For partial scoring credit, `DAY` and `NIGHT` are treated as non-overlapping.

### 3.3. Candidate Matching and Scoring

An employer (or a `PlatformAdmin`) triggers match generation for a requisition. The candidate pool is every nurse who is `ACTIVE`, license-verified, and whose `primary_specialty` equals the requisition's `specialty`. Nurses whose `confidentiality_exclusions` contain the requisition's `employer_id` are still scored, but their `Match` rows are persisted with `suppressed` true and are excluded from every employer-visible read; `Candidate` and `PlatformAdmin` readers of a nurse's matches see the suppressed rows, while the employer-facing requisition match list never returns them. Generation is idempotent per requisition: prior non-suppressed `Match` rows for the requisition are replaced by the new run.

Each generated `Match` records `nurse_id`, `requisition_id`, a `match_score`, the `suppressed` flag, and `generated_at`. The score starts at zero and accumulates. Geography contributes 40 points when the nurse's `home_state` equals the requisition's `facility_state`, otherwise nothing. Experience contributes 25 points scaled by the nurse's `years_experience` capped at ten years — that is, 25 multiplied by the lesser of the nurse's years and ten, divided by ten; a nurse at ten or more years earns the full 25. Shift alignment contributes 20 points when `desired_shift` equals the requisition's `shift`; failing that, 10 points when either side is `ROTATING`; otherwise nothing. Commute feasibility contributes 15 points when the nurse's `max_commute_miles` is at least the requisition's `distance_from_facility_miles`. Finally, when `required_certs` is non-empty and the nurse lacks any required cert unexpired, a hard penalty of 20 points is subtracted — the nurse is penalized, not excluded. The raw score is clamped into the range from 0 to 100 inclusive, then rounded half-up to an integer — rounding happens at this final step only. The returned ranking orders by `match_score` descending, breaking ties by the nurse's `created_at` ascending; ties beyond that are impossible because creation timestamps are unique.

When the employer-facing match list is read, it is paginated and may be filtered with the optional `include_suppressed` query parameter; regardless of that parameter, the `Employer` role never sees suppressed rows. Nurses can also read their own match list — the reverse reachability of `Match.nurse_id` — paginated via `limit` and `offset`.

### 3.4. Employer-Initiated Applications and Response Deadlines

The marketplace's signature inversion happens here: the **Employer**, not the nurse, initiates an **Application**. The employer supplies the `requisition_id`, the target `nurse_id`, a `proposed_hourly_rate_cents`, a `proposed_shift`, and — per §2.7 — `expected_nurse_version`. Creation is a layered gate. The nurse must be `ACTIVE` and license-verified, or creation fails with `ERR_CREDENTIALS_INCOMPLETE` (HTTP 422). An employer named in the nurse's `confidentiality_exclusions` is rejected with `ERR_CANDIDATE_CONFIDENTIAL`. A suspended employer is rejected with `ERR_NO_OPENINGS`. The proposed terms must match the requisition: `proposed_shift` must equal the requisition's `shift`, and `proposed_hourly_rate_cents` must be at least the requisition's `offered_hourly_rate_cents`; violations are rejected with `ERR_TERMS_MISMATCH` (HTTP 422).

On success the application is created in `SUBMITTED`, its `employer_id` copied from the requisition and immutable thereafter, its `revision_count` at zero and `deadline_extended` false. Its `response_deadline_at` is set to the moment of submission plus 72 hours on the logical clock — three full days for the nurse to react. Creation also increments the nurse's `version` by 1 and recomputes the nurse's `active_application_count`; this is exactly why the OCC guard exists — each application legitimately advances the nurse's version, so a second employer working from a stale nurse read is rejected with `ERR_STALE_NURSE_VERSION`.

The nurse, acting as `Candidate`, moves the application from `SUBMITTED` to `UNDER_REVIEW` by reviewing it — permitted only while clock now is still before `response_deadline_at`; an action at or past the deadline is rejected with `ERR_DEADLINE_PASSED` (HTTP 409). The nurse may instead decline from `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, moving the application to the terminal `DECLINED`. The employer may withdraw from the same three states, moving the application to `WITHDRAWN` and cascading any of its interviews still `SCHEDULED` to `CANCELLED`; the withdrawing employer must own the application's `employer_id`.

An employer may also counter — revising terms while the application is `UNDER_REVIEW` — by supplying a new `proposed_hourly_rate_cents` and optionally a new `proposed_shift`. Each counter increments `revision_count`, which is hard-capped at 2; a counter attempted at the cap is rejected with `ERR_TERMS_MISMATCH`. The first counter additionally extends the deadline: when `deadline_extended` is false, `response_deadline_at` gains a further 48 hours and `deadline_extended` flips true; a second counter leaves the deadline unchanged but still increments `revision_count`. The revised terms remain subject to the same matching-field constraints as creation — the shift must equal the requisition's and the rate must meet its floor.

Time is the final arbiter. On any clock advance that reaches `response_deadline_at`, an application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` transitions to the terminal `EXPIRED` — the boundary is inclusive, so a clock reading exactly equal to the deadline expires the application — and any of its interviews still `SCHEDULED` cascade to `CANCELLED`. Every decline, withdrawal, and expiry recomputes the nurse's `active_application_count`.

### 3.5. Interview Scheduling: Overlap and Unit Capacity

Once an application is `UNDER_REVIEW`, the employer schedules interviews by supplying `starts_at` and `ends_at`. Both are ISO 8601 UTC instants; `starts_at` must be strictly after clock now at scheduling time, `ends_at` must be strictly after `starts_at`, and the duration between them must be at least 30 minutes and at most 240 minutes — a duration outside that band is rejected with `ERR_TERMS_MISMATCH`. The first interview scheduled on an application moves it from `UNDER_REVIEW` to `INTERVIEWING`; the requisition's posture is unchanged and the application remains deadline-bound, so scheduling at or past `response_deadline_at` is rejected with `ERR_DEADLINE_PASSED`. Each interview records `scheduled_by_employer_at`, the logical-clock timestamp of scheduling, which serves as the SLA baseline.

Two independent safety rules guard every scheduling, evaluated after the deadline and terms checks. The first protects the nurse's calendar. Collect every interview in `SCHEDULED` across all of that nurse's applications — not just the one at hand. Each existing interval is expanded by a 30-minute buffer on both sides, and the new interval collides if it overlaps any buffered existing interval: the new `starts_at` falling before the existing end plus 30 minutes while the existing start minus 30 minutes falls before the new `ends_at` constitutes overlap. Adjacency at exactly the buffer's edge is permitted — a new interview starting at the precise instant 30 minutes after an existing interview's end is accepted, because the comparison is strict on the buffered half-open form. A collision is rejected with `ERR_INTERVIEW_CONFLICT` (HTTP 409).

The second rule protects the unit's daily capacity, and its semantics are deliberately different from the per-nurse rule: there is no buffer and no interval arithmetic at all, only a start-day bucket count. For the requisition's unit — the (`facility_state`, `unit_name`) pair — a calendar day accepts at most 6 interview-starts, counted across all applications of all requisitions sharing that pair. Only interviews in `SCHEDULED` or `COMPLETED` whose `starts_at` calendar day equals the new interview's start day count toward the bucket. The day window is the closed interval from 00:00 through 23:59 of that day on the logical clock: an interview starting at exactly 23:59 counts toward that day, and one starting at exactly 00:00 counts toward the new day, not the previous one. When the target day already carries 6 such interview-starts, the scheduling is rejected with `ERR_UNIT_DAY_CAPACITY` (HTTP 409).

An interview in `SCHEDULED` may be completed by the employer once the clock has reached its `ends_at`, moving it to `COMPLETED` — completion attempted before the window has passed is rejected with `ERR_DEADLINE_PASSED`. The employer may instead cancel a `SCHEDULED` interview at any time, moving it to `CANCELLED`, or mark it `NO_SHOW` once the clock has moved strictly past `ends_at`. All three outcomes are terminal.

### 3.6. Offers, Screening, and Onboarding Documents

With an application in `INTERVIEWING` and at least one of its interviews `COMPLETED`, the employer issues an **Offer**, supplying `offered_hourly_rate_cents`, a `start_date`, and — per §2.7 — `expected_requisition_version`. Issuance enforces, in priority order: the deadline must not have passed (`ERR_DEADLINE_PASSED`); the `offered_hourly_rate_cents` must equal the application's current `proposed_hourly_rate_cents` — including any counter revisions — and the `start_date` must fall between 14 and 90 days after the clock's current date at issuance, with violations rejected as `ERR_TERMS_MISMATCH`; the requisition must be `OPEN` with `openings_filled` still below `openings_total` and the employer not suspended, otherwise `ERR_NO_OPENINGS`; and no other non-terminal offer may exist for the application, otherwise `ERR_DUPLICATE_RESOURCE`. A requisition whose version advanced since the employer's last read — a sibling application may have filled the last opening in between — rejects the issuance with `ERR_STALE_REQUISITION_VERSION`. On success the offer is created `ISSUED`, its `issued_at` set to clock now and its `offer_expires_at` computed as issuance plus 48 hours; the application moves to `OFFER_EXTENDED`; and the requisition's `version` increments by 1.

Before the nurse can accept, two compliance artifacts must be in place, both keyed to the application. The employer opens a **Screening** — exactly one per application; a second is rejected with `ERR_DUPLICATE_RESOURCE` — by supplying the `application_id`. A screening tracks two independent axes in parallel: `credential_status` moving among `PENDING`, `VERIFIED`, and `FAILED`, and `background_status` moving among `PENDING`, `CLEARED`, and `FLAGGED`. Both axes start at `PENDING`, making the derived `overall_status` begin as `IN_PROGRESS`. The derived value is a compound: `COMPLETE` when credentials are `VERIFIED` and background is `CLEARED`; `BLOCKED` when either axis is `FAILED` or `FLAGGED`; otherwise `IN_PROGRESS`. A `PlatformAdmin` verifies the credential axis — which additionally requires that the nurse hold every cert code in the requisition's `required_certs` with `expires_on` strictly after the clock's current date — or fails it; and separately clears or flags the background axis. Failing credentials or flagging background flips `overall_status` to `BLOCKED` and, if the application's offer is currently `ISSUED`, cascades: the offer transitions to `RESCINDED` and the application to `WITHDRAWN`.

The nurse, meanwhile, uploads **OnboardingDocument** rows by supplying `application_id` and a `doc_type` of `I9`, `W4`, `DIRECT_DEPOSIT`, `HEALTH_RECORD`, or `SIGNED_CONTRACT`. Each document starts `RECEIVED`; the owning employer then approves it to `APPROVED` or rejects it to `REJECTED` — rejection requires a `review_note` in the body, and a missing one is rejected with `ERR_REVIEW_NOTE_REQUIRED` (HTTP 400).

Acceptance is the strictest gate in the system. The nurse accepting must own the application; the offer must still be `ISSUED`; clock now must be strictly before `offer_expires_at` (at or past it, `ERR_DEADLINE_PASSED`); the application must be `OFFER_EXTENDED`; the application's screening must exist with `overall_status` equal to `COMPLETE`; an onboarding document with `doc_type` `SIGNED_CONTRACT` in `APPROVED` status must exist for the application — a missing screening or missing approved contract is rejected with `ERR_CREDENTIALS_INCOMPLETE`; and the requisition must still have openings remaining, otherwise `ERR_NO_OPENINGS`.

The offer's other exits are simpler. The nurse may decline an `ISSUED` offer, which moves the offer to `DECLINED` and the application from `OFFER_EXTENDED` to `DECLINED`. The owning employer may rescind an `ISSUED` offer, moving it to `RESCINDED` and the application from `OFFER_EXTENDED` to `WITHDRAWN`. And on any clock advance that reaches `offer_expires_at` — the boundary inclusive — an `ISSUED` offer transitions to `EXPIRED` and its application transitions from `OFFER_EXTENDED` to `EXPIRED`.

### 3.7. Acceptance and the Placement Cascade

Offer acceptance is an atomic multi-entity commit, and it is where the marketplace's financial machinery engages. The evaluation order is pinned because the fee computation and the placement creation form a circular-looking pair: the provisional fee must exist before the guarantee window can later refund a fraction of it, yet the fee derives from a salary that is only well-defined on the placement row the same accept creates.

First, a **Placement** is created in `PENDING_START`. Its `application_id`, `requisition_id`, `nurse_id`, and `employer_id` are copied from the application; its `hourly_rate_cents` is copied from the accepted offer's `offered_hourly_rate_cents`; its `start_date` is copied from the offer's `start_date`. Its `annualized_salary_cents` is computed once, now, as the hourly rate in cents multiplied by 2080 — forty hours per week across fifty-two weeks — and stored on the placement, because the placement, not the terminal-locked offer, is the billable source of truth. Its `guarantee_ends_on` is the `start_date` plus the employer's `guarantee_days` days.

Second, the requisition's `openings_filled` increases by 1; if it thereby equals `openings_total`, the requisition transitions `OPEN` to `FILLED`, which itself cascades every sibling application in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING` to `WITHDRAWN` and every sibling application in `OFFER_EXTENDED` to offer-`RESCINDED`. Third, the nurse transitions `ACTIVE` to `HIRED`, which cascades all of that nurse's other live applications — any in `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, or `OFFER_EXTENDED` — to `WITHDRAWN`. Fourth, the application itself transitions to `ACCEPTED`.

Fifth, an **Invoice** is created in `ISSUED` with `amount_credited_cents` at zero, its `invoice_kind` set to `PLACEMENT_FEE`, its `employer_id` and `placement_id` wired to the new placement. The provisional `amount_due_cents` depends on the employer's billing model. Under `PER_PLACEMENT`, the fee is the `annualized_salary_cents` multiplied by the employer's `placement_fee_bps` and divided by 10000, rounded half-up to whole cents — rounding applied to that product only. Under `SUBSCRIPTION`, the fee is a tiered flat amount: 2500000 cents on the `BASIC` tier, 2000000 cents on `PRO`, and 1500000 cents on `ENTERPRISE`.

### 3.8. Guarantee Windows, Termination Refunds, and Invoice Settlement

A placement's early life is clock-driven. On any clock advance reaching the placement's `start_date` — the boundary inclusive — a `PENDING_START` placement transitions to `GUARANTEE_ACTIVE`. On any clock advance moving strictly past `guarantee_ends_on`, a `GUARANTEE_ACTIVE` placement transitions to `COMPLETED`, and its linked placement-fee invoice transitions to `SETTLED`: the provisional fee becomes final and no refund is possible thereafter.

Inside the guarantee window, the owning employer may terminate the placement, moving it from `PENDING_START` or `GUARANTEE_ACTIVE` to `TERMINATED_IN_GUARANTEE`. Termination requires the clock's current date be on or before `guarantee_ends_on`; this guarantee-window date check is evaluated before the state-machine legality check, so a termination attempted after that date is rejected with `ERR_PLACEMENT_GUARANTEE_EXPIRED` (HTTP 409) regardless of the placement's current state, because the placement is complete and the fee is final. Termination fires a four-part cascade. The requisition's `openings_filled` decreases by 1, and if the requisition was `FILLED` it transitions back to `OPEN` — the seat returns to the pool. The nurse transitions from `HIRED` back to `ACTIVE`. The linked invoice is credited per the guarantee-refund rule below. And the employer's `credit_balance_cents` grows by the credited amount.

The refund amount is computed with a pinned rounding order, because rounding the intermediate fraction instead of the final quotient yields different cents. Days served is the whole-day difference between the clock's current date and the placement's `start_date`, floored at zero. If the placement was terminated while still `PENDING_START`, the refund numerator is the employer's full `guarantee_days`; otherwise it is `guarantee_days` minus days served, floored at zero. The refund in cents is the invoice's `amount_due_cents` multiplied by that numerator and divided by `guarantee_days`, rounded half-up exactly once at the final quotient. The refund is added to the invoice's `amount_credited_cents`. The invoice then transitions to `VOID` when the refund equals the full `amount_due_cents` — the shape a pre-start termination takes — and to `PARTIALLY_CREDITED` when the refund is positive but smaller.

Settlement closes the loop. An employer may settle any invoice in `ISSUED` or `PARTIALLY_CREDITED`; settling draws down the employer's `credit_balance_cents` first, decreasing it by the lesser of the available credit and the invoice's outstanding balance — its `amount_due_cents` minus its `amount_credited_cents` — adds that drawn-down amount to the invoice's `amount_credited_cents`, and moves the invoice to the terminal `SETTLED`. Invoices are browsable by `employer_id`, `placement_id`, or `status`, with `invoice_kind` distinguishing `PLACEMENT_FEE` bills from `SUBSCRIPTION_RENEWAL` invoices — the latter carrying a null `placement_id`. Placements are likewise browsable by `nurse_id`, `employer_id`, `requisition_id`, `application_id`, or `status`, and applications by `nurse_id`, `employer_id`, `requisition_id`, or `status`.

Performance transparency closes the marketplace loop. A computed SLA report on a requisition evaluates every application against it that has left `SUBMITTED`. For each, the employer's first-action time is the whole hours — truncated toward zero — from application creation to the earliest of: the first interview's scheduling timestamp, the first counter, the offer's `issued_at`, or an employer withdrawal. An application breaches when that first-action time is strictly greater than the employer's `sla_response_hours`; exactly equal is not a breach. The report returns `breach_count`, the number of breaching applications, `evaluated_count`, the number evaluated, and `rapid_offer_target_met`, which is true when the accepted application's time-to-offer — whole hours from application creation to the offer's `issued_at` — is at most 120 hours.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The clock-set capability also returns `200 OK`. All endpoints are mounted under `/marketplace`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marketplace/_clock/set_current_utc` | Set the logical clock; fires due system transitions | PlatformAdmin |
| POST | `/marketplace/nurses` | Create nurse profile (DRAFT) | Candidate |
| GET | `/marketplace/nurses/{id}` | Read nurse profile; excluded employers get 404 | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/nurses` | List nurses; employers see only ACTIVE non-excluding nurses | Employer, PlatformAdmin |
| POST | `/marketplace/nurses/{id}/submit` | Submit profile for verification | Candidate |
| POST | `/marketplace/nurses/{id}/deactivate` | Deactivate an ACTIVE nurse with no live applications | Candidate |
| POST | `/marketplace/nurses/{id}/reactivate` | Reactivate an INACTIVE license-verified nurse | Candidate |
| POST | `/marketplace/nurses/{id}/withdraw` | Permanently withdraw; cascades live applications | Candidate |
| GET | `/marketplace/nurses/{id}/license-verifications` | List a nurse's license verifications | Candidate, PlatformAdmin |
| GET | `/marketplace/nurses/{id}/certifications` | List a nurse's certifications | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/nurses/{id}/applications` | List applications naming this nurse | Candidate, PlatformAdmin |
| GET | `/marketplace/nurses/{id}/matches` | List Match rows naming this nurse (suppressed included) | Candidate, PlatformAdmin |
| POST | `/marketplace/license-verifications` | Submit a license for verification | Candidate |
| GET | `/marketplace/license-verifications/{id}` | Read one verification | Candidate, PlatformAdmin |
| POST | `/marketplace/license-verifications/{id}/verify` | Mark a PENDING verification VERIFIED | PlatformAdmin |
| POST | `/marketplace/license-verifications/{id}/reject` | Reject a PENDING verification | PlatformAdmin |
| POST | `/marketplace/certifications` | Attach an immutable certification to a nurse | Candidate |
| GET | `/marketplace/certifications/{id}` | Read one certification | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/employers` | Register an employer | PlatformAdmin |
| GET | `/marketplace/employers/{id}` | Read employer | Employer, PlatformAdmin |
| GET | `/marketplace/employers/{id}/requisitions` | List an employer's requisitions | Employer, PlatformAdmin |
| GET | `/marketplace/employers/{id}/invoices` | List an employer's invoices | Employer, PlatformAdmin |
| POST | `/marketplace/employers/{id}/suspend` | Suspend an ACTIVE employer | PlatformAdmin |
| POST | `/marketplace/employers/{id}/reinstate` | Reinstate a SUSPENDED employer | PlatformAdmin |
| POST | `/marketplace/requisitions` | Create a requisition (OPEN) | Employer |
| GET | `/marketplace/requisitions/{id}` | Read requisition | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/requisitions/{id}/pause` | Pause an OPEN requisition | Employer |
| POST | `/marketplace/requisitions/{id}/resume` | Resume a PAUSED requisition | Employer |
| POST | `/marketplace/requisitions/{id}/close` | Close a requisition; cascades live applications | Employer |
| POST | `/marketplace/requisitions/{id}/generate-matches` | Generate Match rows for the requisition | Employer, PlatformAdmin |
| GET | `/marketplace/requisitions/{id}/matches` | List ranked matches; employers never see suppressed rows | Employer, PlatformAdmin |
| GET | `/marketplace/requisitions/{id}/sla-report` | Computed SLA report for the requisition | Employer, PlatformAdmin |
| POST | `/marketplace/applications` | Employer initiates an application to a nurse (OCC-guarded) | Employer |
| GET | `/marketplace/applications/{id}` | Read application | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/applications` | Filtered list of applications | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/applications/{id}/review` | Nurse moves application SUBMITTED to UNDER_REVIEW | Candidate |
| POST | `/marketplace/applications/{id}/counter` | Employer revises terms; extends deadline once | Employer |
| POST | `/marketplace/applications/{id}/decline` | Nurse declines the application | Candidate |
| POST | `/marketplace/applications/{id}/withdraw` | Employer withdraws the application | Employer |
| GET | `/marketplace/applications/{id}/interviews` | List interviews for an application | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/applications/{id}/offers` | List offers for an application | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/applications/{id}/screenings` | List screenings for an application | Employer, PlatformAdmin |
| GET | `/marketplace/applications/{id}/onboarding-documents` | List onboarding documents for an application | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/applications/{id}/interviews` | Schedule an interview; enforces overlap and day-capacity rules | Employer |
| GET | `/marketplace/interviews/{id}` | Read interview | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/interviews/{id}/complete` | Mark a SCHEDULED interview COMPLETED | Employer |
| POST | `/marketplace/interviews/{id}/cancel` | Cancel a SCHEDULED interview | Employer |
| POST | `/marketplace/interviews/{id}/no-show` | Mark a SCHEDULED interview NO_SHOW | Employer |
| POST | `/marketplace/applications/{id}/offers` | Issue an offer on an INTERVIEWING application (OCC-guarded) | Employer |
| GET | `/marketplace/offers/{id}` | Read offer | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/offers/{id}/accept` | Nurse accepts an offer; fires the placement cascade | Candidate |
| POST | `/marketplace/offers/{id}/decline` | Nurse declines an offer | Candidate |
| POST | `/marketplace/offers/{id}/rescind` | Employer rescinds an ISSUED offer | Employer |
| POST | `/marketplace/screenings` | Open the screening package for an application | Employer |
| GET | `/marketplace/screenings/{id}` | Read screening | Employer, PlatformAdmin |
| POST | `/marketplace/screenings/{id}/verify-credentials` | Verify the credential axis | PlatformAdmin |
| POST | `/marketplace/screenings/{id}/fail-credentials` | Fail the credential axis; rescinds any ISSUED offer | PlatformAdmin |
| POST | `/marketplace/screenings/{id}/clear-background` | Clear the background axis | PlatformAdmin |
| POST | `/marketplace/screenings/{id}/flag-background` | Flag the background axis; rescinds any ISSUED offer | PlatformAdmin |
| POST | `/marketplace/onboarding-documents` | Upload an onboarding document | Candidate |
| GET | `/marketplace/onboarding-documents/{id}` | Read document | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/onboarding-documents/{id}/approve` | Approve a RECEIVED document | Employer |
| POST | `/marketplace/onboarding-documents/{id}/reject` | Reject a RECEIVED document with a review note | Employer |
| GET | `/marketplace/placements/{id}` | Read placement | Candidate, Employer, PlatformAdmin |
| GET | `/marketplace/placements` | Filtered list of placements | Candidate, Employer, PlatformAdmin |
| POST | `/marketplace/placements/{id}/terminate` | Terminate a placement inside its guarantee window | Employer |
| GET | `/marketplace/invoices/{id}` | Read invoice | Employer, PlatformAdmin |
| GET | `/marketplace/invoices` | Filtered list of invoices | Employer, PlatformAdmin |
| POST | `/marketplace/invoices/{id}/settle` | Settle an invoice, applying employer credit first | Employer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_CANDIDATE_CONFIDENTIAL` | 403 |
| `ERR_CREDENTIALS_INCOMPLETE` | 422 |
| `ERR_TERMS_MISMATCH` | 422 |
| `ERR_INTERVIEW_CONFLICT` | 409 |
| `ERR_NO_OPENINGS` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_STALE_NURSE_VERSION` | 412 |
| `ERR_STALE_REQUISITION_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_LICENSE_EXPIRED` | 422 |
| `ERR_NURSE_HAS_LIVE_APPLICATIONS` | 409 |
| `ERR_PLACEMENT_GUARANTEE_EXPIRED` | 409 |
| `ERR_REVIEW_NOTE_REQUIRED` | 400 |
| `ERR_UNIT_DAY_CAPACITY` | 409 |
