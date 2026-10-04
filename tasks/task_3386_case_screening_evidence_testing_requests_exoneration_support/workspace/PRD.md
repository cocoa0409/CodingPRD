# Innocence Case Review API — Product Requirements Document

## 1. Introduction

A post-conviction innocence review organization operates one of the longest and most consequential pipelines in the legal services world. A request for assistance arrives from an incarcerated person; screeners weigh the claim of actual innocence and the likelihood that biological evidence still exists; analysts chase court, police, and laboratory records that frequently reveal materials destroyed or missing; attorneys negotiate testing agreements with prosecutors or litigate contested motions; results are interpreted with consulting experts and compared against DNA databases in the hope of identifying an alternate perpetrator; petitions, appeals, and clemency applications play out under statutes that differ sharply from one jurisdiction to the next; and for the client who is finally exonerated, the work continues through release logistics, statutory compensation claims, and reentry services. Alongside the casework, the organization aggregates what it learns — destroyed evidence, denied compensation, database hits, obstructed records — into policy reform initiatives. Each of these stages can span years, and the client relationship must be actively maintained across all of them.

This document specifies the API that backs that pipeline. The system enforces segregation of duties on screening decisions — the specialist who recommends an outcome may not decide it — and it treats jurisdictional statutes as feature flags that open or close entire legal paths. Because records responses, laboratory events, and court rulings all ripple outward, the API derives a family's worth of computed state (evidence posture, testing readiness, pattern counts, contact compliance) from a small set of primitive mutations, and it guards the handful of genuinely concurrent writes with optimistic version checks. Every state change is attributable, every deadline is evaluated against a controllable logical clock, and every error the API can raise is catalogued here.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request in which either header is missing or empty, or whose `X-User-Role` value is not one of the declared role names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes exactly eight roles: `PlatformAdmin`, `IntakeSpecialist`, `ManagingAttorney`, `StaffAttorney`, `EvidenceAnalyst`, `ClientServicesAdvocate`, `PolicyDirector`, and `Client`. Each endpoint admits a fixed set of roles (§4); a request whose role is well-formed but not admitted by the addressed endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` record; ownership checks on any resource that references a `Client` compare the resource's client-reference field to `X-User-ID`. Concretely, a `Client` may read its own `Client` record, may read an intake request only when the request's `client_id` equals `X-User-ID`, may read a case only when the case's `intake_request_id` leads to an intake request whose `client_id` equals `X-User-ID`, and may submit supplemental information only on its own requests; a `Client` self-submitting an intake request must supply a `client_id` equal to `X-User-ID`. Any `Client`-role call that fails one of these ownership checks is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). For the other seven roles — `PlatformAdmin`, `IntakeSpecialist`, `ManagingAttorney`, `StaffAttorney`, `EvidenceAnalyst`, `ClientServicesAdvocate`, and `PolicyDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `recommended_by_user_id` or `decided_by_user_id` on an intake request, `created_by_user_id` on a testing authorization, or `assigned_attorney_id` on a case) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources accept the pagination query parameters `limit` and `offset` alongside any filter parameters documented for the endpoint. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

List filters are exact-match query parameters scoped to the collection being listed: the intake-request list accepts `status`, `client_id`, and `jurisdiction_id`; a case's evidence-item list accepts `location_status` and `testing_status`; a case's records-request and compensation-claim lists accept `status`; a case's testing-authorization list accepts `kind` and `status`; a case's legal-petition list accepts `status` and `petition_type`; and the reentry-referral lists (under a case or a provider) accept `status` and, on the case-scoped list, `provider_id`.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All timestamps the server writes — `last_contact_at`, `filed_at`, `decided_at`, `exoneration_date`, and every other business timestamp described in §3 — are read from a server-side logical clock, never from wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`; the server must not silently fall back to the host's wall clock under any circumstance.

A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through the clock-setting capability (§4); the response reports the resulting `current_utc`. Setting the clock mutates no entity: deadlines, overdue evaluations, and window gates that read the clock are only re-evaluated when some operation on the affected resource actually runs.

### 2.5. Common Resource Properties

Every entity in the system — jurisdictions, clients, intake requests, cases, evidence items, records requests, testing authorizations, lab analyses, legal petitions, compensation claims, reentry providers, reentry referrals, and policy initiatives — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted UUID with no type prefix. The `id` is an identity token only; it is forbidden from participating in selector, ranking, or tie-break decisions anywhere in the system.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every mutation of the resource, including mutations the resource suffers as the target of a cascade.
- **`version` (integer):** starts at 1 at creation and increments by exactly 1 on every mutation, again including cascaded side effects. This is the field optimistic concurrency control (§2.7) reads.

### 2.6. Derived State and Cascade Discipline

Many fields in this system are never written by clients; the server derives them from primitive events and re-derives them whenever a relevant input changes. The case's `evidence_posture`, an evidence item's `testing_status`, a case's `contact_interval_days`, a provider's `slots_in_use`, a policy initiative's `pattern_case_count`, and an evidence item's `remaining_sample_ng` all behave this way. Whenever such a derivation or a cascade touches an entity, that entity's `updated_at` is refreshed and its `version` is incremented — a cascade is a mutation like any other.

Two cascade chains recur throughout §3 and are worth naming up front. **Chain A** runs from a records response to a reported evidence destruction: the response mutates the evidence item's location, the destruction increments the owning case's `destroyed_evidence_count` and re-derives its `evidence_posture`, and every evidence-preservation policy initiative in the case's jurisdiction has its `pattern_case_count` re-derived — three links past the triggering write. **Chain B** runs from a database-comparison hit on a lab analysis to the owning case's `exculpatory_evidence_flag` being set true, followed by re-derivation of the case's `evidence_posture`, where the exculpatory result takes precedence over every other posture input. Because each link of either chain is a mutation, intermediate entities show the bump in `version` and `updated_at` even though no client addressed them directly.

One convention keeps §3 readable: a field described as stamped, recorded, or computed by a particular event carries null until that event has occurred. This applies to `recommendation`, `decision`, `decided_by_user_id`, `accepted_case_id`, `resolution`, `exoneration_date`, `filed_at`, `decided_at`, `decision_vacates_conviction`, `outcome`, `actual_consumed_ng`, `profile_obtained`, `expert_name`, `expert_interpretation`, `db_matched_subject_name`, `last_ruling`, `final_award_cents`, and `paid_amount_cents`.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control; no other endpoint takes a version field.

The first guards case strategy updates. A request to update a case's `strategy_notes`, `theory_of_case`, or `assigned_attorney_id` must carry `expected_case_version`, set to the value of the case's `version` the client last observed. If another writer has advanced the case's version since that read — including a writer whose write was an entirely legitimate cascade, such as a records response that bumped the case — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because the stale writer's view of the case predates a completed update it never observed.

The second guards testing-agreement amendments. Recording an amendment to a testing authorization's `terms` or `proposed_test_types` must carry `expected_testing_authorization_version` matching the authorization's current `version`. A mismatch means the authorization has legitimately advanced — a new amendment superseding the terms the client saw — and the request is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412) rather than being layered over terms the client never read.

In both rules the version check is evaluated after existence and ownership checks but before any business logic of the endpoint.

### 2.8. Jurisdictional Statutory Flags

The law governing post-conviction relief is not uniform, and the system models that directly. Each `Jurisdiction` record carries the statutory feature flags that reshape what is legal for cases convicted there: `has_post_conviction_dna_statute` records whether the jurisdiction has a post-conviction DNA testing statute at all; `clemency_available` records whether clemency petitions exist; `compensation_statute_exists` records whether a wrongful-conviction compensation statute exists; `post_conviction_deadline_years` records the number of years after conviction within which a post-conviction petition must be filed (a null value means the jurisdiction imposes no statutory deadline); `compensation_cap_cents` records the statutory cap on the tiered portion of a compensation award, in cents (null means uncapped); and `actual_innocence_enhancement_pct` records the percentage enhancement applied to the tiered award when the case carries exculpatory evidence, defaulting to 0 (no enhancement) and bounded between 0 and 100.

These flags gate behavior throughout §3: a contested testing motion cannot be created where no testing statute exists, a clemency petition cannot be drafted where clemency does not exist, and a compensation claim cannot be opened where no compensation statute exists. The specific rejections are named where each workflow is described. A jurisdiction is identified by its `state_code` — a unique two-letter uppercase code; a duplicate registration is rejected with `ERR_DUPLICATE_STATE_CODE` (HTTP 409) — and carries a human-readable `name`.

### 2.9. Validation Order and Error Precedence

When a single request violates several rules, the system evaluates checks in a fixed priority order so that the error the caller receives is deterministic. The order is:

1. **User context.** `X-User-ID` and `X-User-Role` must both be present and non-empty, and the role must be one of the eight declared names — else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This applies to every endpoint.
2. **Role admission.** The role must appear in the endpoint's authorized set — else `ERR_UNAUTHORIZED_ROLE`. This also applies to every endpoint.
3. **Existence.** Resource identifiers must resolve. Path identifiers are validated first, strictly left-to-right; identifiers referenced in the request body (`client_id`, `jurisdiction_id`, `case_id`, `evidence_item_id`, `authorization_id`, `provider_id`) are then validated in payload field order. The first unresolved reference produces the corresponding not-found error: `ERR_JURISDICTION_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INTAKE_REQUEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_TESTING_AUTHORIZATION_NOT_FOUND`, `ERR_LAB_ANALYSIS_NOT_FOUND`, `ERR_LEGAL_PETITION_NOT_FOUND`, `ERR_COMPENSATION_CLAIM_NOT_FOUND`, `ERR_REENTRY_PROVIDER_NOT_FOUND`, `ERR_REENTRY_REFERRAL_NOT_FOUND`, or `ERR_POLICY_INITIATIVE_NOT_FOUND`, each HTTP 404.
4. **Ownership.** When the role is `Client`, the ownership chain of §2.1 must hold — else `ERR_OWNERSHIP_MISMATCH`. This check follows existence, so a `Client` probing a nonexistent id receives the 404, not the 403.
5. **Stale versions.** The OCC checks of §2.7 run here, after existence and ownership and before any business logic — `ERR_STALE_VERSION` or `ERR_STALE_AUTHORIZATION_VERSION`.
6. **Request shape.** Required fields must be present, types must be correct, enum values must be in vocabulary, integer floors must hold (`initial_sample_ng` at least 1, `required_sample_ng` at least 1, `years_incarcerated_claimed` at least 1, `total_capacity` at least 1, `years_served` at least 0, `documented_legal_fees_cents` at least 0), unknown fields are rejected, a lab window's `scheduled_end` must be strictly after its `scheduled_start`, and a service window's `service_end` must be strictly after its `service_start` — any violation is `ERR_INVALID_REQUEST` (HTTP 400).
7. **Event vocabulary.** On advance-style endpoints, the payload's `event` must belong to the endpoint's declared vocabulary — else `ERR_INVALID_TRANSITION_EVENT` (HTTP 400).
8. **From-state.** The target resource's current status must admit the requested transition, including kind-conditional legality on testing authorizations (an agreement event on a motion, or vice versa, is illegal regardless of status) — else `ERR_INVALID_STATE` (HTTP 409).
9. **Cross-entity state gates.** Operations gated on a related resource's state fail here: `ERR_CASE_NOT_IN_LITIGATION`, `ERR_CASE_NOT_EXONERATED`, `ERR_CASE_NOT_READY_FOR_TESTING_AUTH`, `ERR_CASE_NOT_IN_TESTING`, `ERR_NO_PRESERVED_EVIDENCE`, `ERR_NO_TEST_RESULTS` (all HTTP 409), and `ERR_EVIDENCE_NOT_IN_CUSTODY` (HTTP 422) — the HTTP code is pinned per error id in §5; this priority governs only which check fires first.
10. **Segregation of duties.** The intake decision may not be made by the recommending specialist — `ERR_DECISION_SELF_APPROVAL` (§3.1).
11. **Referenced-entity validity.** A lab analysis must reference a testing authorization that is actually effective — `ERR_AUTHORIZATION_NOT_EFFECTIVE` (§3.5).
12. **Temporal gates.** Filing deadlines, lab-window overlaps, release dates, and service-window starts are enforced here — `ERR_FILING_DEADLINE_EXCEEDED` (HTTP 422), `ERR_LAB_SCHEDULE_OVERLAP`, `ERR_RELEASE_DATE_NOT_REACHED`, and `ERR_SERVICE_WINDOW_NOT_STARTED` (HTTP 409 each).
13. **Domain constraints**, evaluated in this sub-order: (a) jurisdictional statute flags — `ERR_JURISDICTION_NO_TESTING_STATUTE`, `ERR_CLEMENCY_NOT_AVAILABLE`, `ERR_NO_COMPENSATION_STATUTE`, and the exculpatory-basis gate `ERR_NO_EXCULPATORY_BASIS`; (b) screening criteria — `ERR_SCREENING_CRITERIA_NOT_MET`; (c) sample sufficiency and consumption bounds — `ERR_INSUFFICIENT_SAMPLE`, `ERR_CONSUMED_EXCEEDS_RESERVED`; (d) provider capacity — `ERR_PROVIDER_CAPACITY_EXCEEDED`; (e) the policy pattern threshold — `ERR_INSUFFICIENT_PATTERN_EVIDENCE`; (f) aggregate close gates — `ERR_OPEN_PETITIONS_EXIST`, `ERR_ACTIVE_LAB_ANALYSES_EXIST`; (g) miscellaneous — `ERR_WAITLIST_EMPTY`, `ERR_NOT_APPEALABLE`, `ERR_DUPLICATE_STATE_CODE`, `ERR_PAYMENT_AMOUNT_MISMATCH`.

### 2.10. Numeric Precision and Rounding

Screening scores are carried to exactly 2 decimal places using round-half-up, and the rounding order is pinned: each weighted factor product is rounded to 2 decimals first, and the score is the plain sum of those four rounded products with no final re-rounding. Compensation amounts are integer cents throughout; the one non-integer intermediate (the exculpatory enhancement multiplier) is floored to whole cents. Sample masses are integer nanograms. Contact-overdue evaluation works in whole days, taking the floor of the UTC day difference between the clock and the last contact timestamp.

## 3. Business Logic & Workflows

### 3.1. Client Registration, Intake, and Screening

Every engagement begins with the people. An `IntakeSpecialist` registers each incarcerated requester as a `Client`, capturing the person's `full_name`, department-of-corrections `inmate_number`, and optionally the current `facility_name`. The client record is the identity anchor for everything that follows: a caller acting with the `Client` role is that record, per §2.1.

A request for assistance is opened as an `IntakeRequest` carrying the `client_id` of the requester, the `jurisdiction_id` of the jurisdiction of conviction, the `conviction_date` (an ISO 8601 date that later drives petition filing deadlines and the verified incarceration duration), a free-text `conviction_summary`, and the screener's four assessment inputs: whether the request asserts factual innocence (`claim_of_actual_innocence`), the `claim_strength` on the scale `WEAK`, `MODERATE`, `STRONG`, `COMPELLING`, the `evidence_potential` on the scale `NONE_KNOWN`, `UNCERTAIN`, `LIKELY_STORED`, `CONFIRMED_STORED`, and the `health_urgency` on the scale `NONE`, `MODERATE`, `CRITICAL`. The request also records `years_served`, the whole years already incarcerated (zero or more), and an optional `expedited_review` flag defaulting to false that selects which weight profile will govern the frozen waitlist score. An `IntakeSpecialist` may create the request on a client's behalf; a `Client` may self-submit, in which case the payload's `client_id` must equal the caller's `X-User-ID` or the create is rejected with `ERR_OWNERSHIP_MISMATCH`. A new request lands in `RECEIVED` status.

Screening is a staffed, iterative process with a cyclic information-gathering loop. An `IntakeSpecialist` begins screening, moving the request from `RECEIVED` to `SCREENING`. When the file is incomplete, the specialist requests more information, moving it from `SCREENING` to `MORE_INFO_REQUESTED`; the request returns to `SCREENING` when a supplement is submitted, an action open to the assigned specialist or to the owning `Client`, carrying `supplement_notes` which are stored as the request's most recent supplement text. Requesting a transition from a status that does not admit it — for example, beginning screening twice — is rejected with `ERR_INVALID_STATE`.

When the file is ready, the specialist records a recommendation, transitioning the request from `SCREENING` to `DECISION_PENDING` with a payload `recommendation` of `ACCEPT`, `REJECT`, or `WAITLIST`. Recommending acceptance is gated on the screening criteria: `claim_of_actual_innocence` must be true and `evidence_potential` must be `LIKELY_STORED` or `CONFIRMED_STORED`; otherwise the recommendation is rejected with `ERR_SCREENING_CRITERIA_NOT_MET` (HTTP 422). A successful recommendation stamps the request's `recommendation` field, records the acting specialist's `X-User-ID` in `recommended_by_user_id`, and computes two screening scores that are stored on the request: `screening_score_standard` and `screening_score_expedited`. Both are null until this moment.

The screening priority score converts the four assessment factors to integers — `claim_strength` maps `WEAK` to 25, `MODERATE` to 55, `STRONG` to 80, `COMPELLING` to 95; `evidence_potential` maps `NONE_KNOWN` to 0, `UNCERTAIN` to 35, `LIKELY_STORED` to 65, `CONFIRMED_STORED` to 95; `health_urgency` maps `NONE` to 0, `MODERATE` to 45, `CRITICAL` to 90 — and adds a time-served factor computed as one hundred times `years_served` divided by thirty, capped at one hundred and rounded to 2 decimals half-up (so time served saturates at thirty years). Each profile then weights the four factors. The STANDARD profile is claim-heavy: claim 0.425, evidence 0.275, time 0.185, urgency 0.115. The EXPEDITED profile is urgency-heavy: claim 0.260, evidence 0.240, time 0.155, urgency 0.345. Per §2.10, each weighted product is rounded to 2 decimals half-up first, and the score is the sum of the four rounded products with no final re-round. For illustration, a request rated `STRONG`, `LIKELY_STORED`, 7 years served, and `CRITICAL` yields a time factor of 23.33 and, under STANDARD, the products 34.00, 17.88, 4.32, and 10.35 — a `screening_score_standard` of 66.55; the identical inputs under EXPEDITED produce 71.07 as the `screening_score_expedited`. Both variants are always computed and stored at recommendation time, regardless of the `expedited_review` flag.

### 3.2. Decision, the Waitlist, and Case Inception

A recommendation never decides anything by itself. The decision on a `DECISION_PENDING` request belongs to a `ManagingAttorney`, and the system enforces a hard segregation of duties: the deciding attorney's `X-User-ID` must differ from the `recommended_by_user_id` recorded at recommendation time. A self-decision is rejected with `ERR_DECISION_SELF_APPROVAL` (HTTP 403). The decision payload carries a `decision` of `ACCEPTED`, `REJECTED`, or `WAITLISTED`, and whichever branch is taken stamps `decision` and `decided_by_user_id` on the request; an optional `rejection_reason` in the payload is recorded as the request's `decision_reason`.

Acceptance is generative. When the decision is `ACCEPTED`, the server creates a `Case` whose `intake_request_id` points back to this intake request — the case carries no direct client or jurisdiction reference of its own; client identity and jurisdiction are reached only through `intake_request_id` to the intake request's `client_id` and `jurisdiction_id`. The new case opens in `OPEN` status with `assigned_attorney_id` taken from the decision payload when supplied, `exculpatory_evidence_flag` false, `destroyed_evidence_count` 0, `evidence_posture` `NO_EVIDENCE`, `release_readiness` `NOT_APPLICABLE`, `last_contact_at` set to the current logical clock, `contact_count` 0, `contact_overdue` false, and `contact_interval_days` 90. The intake request's `accepted_case_id` is set to the new case's id, and `ACCEPTED` is terminal for the request. Rejection is terminal as well: a `REJECTED` decision records the rationale in `decision_reason` and ends the pipeline for that request.

A `WAITLISTED` decision parks the request instead. At decide time the server freezes `waitlist_priority_score` on the request: the `screening_score_expedited` value when the request's `expedited_review` flag is true, the `screening_score_standard` value otherwise. The field stays null on any request whose decision was not `WAITLISTED`. Waitlisted capacity is managed through a selector: when a `ManagingAttorney` activates the next waitlist entry, the system considers every request in `WAITLISTED` status, ranks them by `waitlist_priority_score` descending, breaks ties by `created_at` ascending, and returns the chosen request to `SCREENING` for a fresh recommendation cycle. The request's `decision`, `decided_by_user_id`, and recommendation fields are retained through the re-entry; its screening scores are recomputed at the next recommendation. The `id` never participates in the ranking or the tie-break. If no request is waitlisted, the activation is rejected with `ERR_WAITLIST_EMPTY` (HTTP 409) and nothing changes.

### 3.3. Evidence Registration, Location Tracking, and Records Requests

Once a case exists, the hunt for physical evidence begins. An `EvidenceAnalyst` registers each item on the case with a payload carrying the `case_id`, a human-readable `description`, an `evidence_type` of `BIOLOGICAL_SWAB`, `CLOTHING`, `WEAPON`, `FINGERPRINT_CARD`, or `OTHER`, the `custodian_type` of the agency believed to hold it (`COURT_CLERK`, `POLICE_PROPERTY`, `CRIME_LAB`, or `MEDICAL_EXAMINER`), and the `initial_sample_ng`, the testable sample mass in nanograms, which must be at least 1. The new item's `location_status` starts at `IDENTIFIED`, its `remaining_sample_ng` starts equal to `initial_sample_ng`, and its arrival re-derives the owning case's `evidence_posture` — a case with no prior items moves from `NO_EVIDENCE` to `SEEKING`.

An evidence item carries two independent state dimensions on one row. The location dimension, `location_status`, is moved by explicit analyst advances and by records-response cascades; the testing dimension, `testing_status`, is never set directly — it is a pure derivation over the item's remaining sample, its sibling lab analyses, and its testing authorizations (§3.5). A transition on one dimension never writes the other. The location dimension walks `IDENTIFIED` → `SEARCHING` when the analyst starts the search; `SEARCHING` → `LOCATED` when material is found; and — the found-after-reported-missing cycle — `REPORTED_MISSING` → `LOCATED` when material written off resurfaces. From `IDENTIFIED` or `SEARCHING` an analyst may mark the item `REPORTED_MISSING`. From `LOCATED`, custody confirmation moves the item to `CUSTODY_CONFIRMED`, re-deriving both the case's `evidence_posture` and the item's `testing_status`. An item reported destroyed may later have that destruction verified: `REPORTED_DESTROYED` → `DESTRUCTION_VERIFIED` re-derives the case posture but leaves the destruction count unchanged, because the item was already counted when the destruction was first reported. Each of these advances from an inadmissible status is rejected with `ERR_INVALID_STATE`.

The destruction path deserves emphasis: there is no analyst event that marks an item destroyed. Only a records response carrying a reveal disposition of `DESTROYED` can move an item from `IDENTIFIED`, `SEARCHING`, or `REPORTED_MISSING` to `REPORTED_DESTROYED`, and that entry is unrecoverable — the LOCATED cascade can resurface a `REPORTED_MISSING` item but never a `REPORTED_DESTROYED` one. Every entry into `REPORTED_DESTROYED` increments the owning case's `destroyed_evidence_count` by one (the count never decrements), re-derives `evidence_posture`, refreshes the case's `updated_at` and `version`, and re-derives the `pattern_case_count` of every `EVIDENCE_PRESERVATION` policy initiative in the case's jurisdiction (§2.6, chain A).

The case's `evidence_posture` is an aggregation over all of its items. Let destroyed items be those in `REPORTED_DESTROYED` or `DESTRUCTION_VERIFIED`, and confirmed items those in `CUSTODY_CONFIRMED`. Evaluated top-down with the first match winning: if the case's `exculpatory_evidence_flag` is true the posture is `EXCULPATORY`; else if the case has no items, `NO_EVIDENCE`; else with at least one confirmed and no destroyed items, `SECURED`; with at least one confirmed and at least one destroyed, `PARTIALLY_COMPROMISED`; with none confirmed and at least one destroyed, `FULLY_COMPROMISED`; otherwise `SEEKING`.

Most location news arrives through the records pipeline. An `EvidenceAnalyst` opens a `RecordsRequest` against an agency with `case_id`, an `agency_type` of `COURT`, `POLICE`, `LABORATORY`, or `MEDICAL_EXAMINER`, the specific `agency_name`, and a `request_summary` describing the scope sought; the request starts in `DRAFT`. Submitting moves it to `SUBMITTED`, after which the analyst records the agency's response with a payload `disposition` of `FULFILLED`, `PARTIALLY_FULFILLED`, or `DENIED`. A fulfilling or partially fulfilling response carries `items_revealed`, an array of entries each pairing an `evidence_item_id` with a disposition of `LOCATED`, `DESTROYED`, or `MISSING`; each reveal is applied to the referenced item in payload array order, with `LOCATED` behaving exactly like a mark-located, `DESTROYED` triggering the full destruction cascade above, and `MISSING` moving the item to `REPORTED_MISSING`. Each reveal is legal only against the item's current location: `LOCATED` requires the item to be in `SEARCHING` or `REPORTED_MISSING`; `DESTROYED` requires `IDENTIFIED`, `SEARCHING`, or `REPORTED_MISSING`; `MISSING` requires `IDENTIFIED` or `SEARCHING` — an illegal reveal rejects the whole response with `ERR_INVALID_STATE`. A `DENIED` response must carry an absent or empty `items_revealed`, else `ERR_INVALID_REQUEST`. The response's disposition is stored as `response_disposition` (null until the first response) and the reveal array as `items_revealed` (empty until a fulfilling response); a denial additionally re-derives the `pattern_case_count` of every `RECORDS_TRANSPARENCY` initiative in the case's jurisdiction. `FULFILLED` and `PARTIALLY_FULFILLED` are terminal. A `DENIED` request may be appealed, moving to `APPEALED`, and an appealed request accepts a fresh response with the same rules — including another `DENIED`, which may itself be appealed again, so the records-appeal loop can iterate until the agency produces something. Responses are accepted from either `SUBMITTED` or `APPEALED`; recording one from any other status is `ERR_INVALID_STATE`.

### 3.4. Authorizing Post-Conviction Testing: Agreements and Motions

No laboratory touches preserved evidence without authority, and the system models both legal paths to that authority through one entity with two disjoint lifecycles. A `StaffAttorney` creates a `TestingAuthorization` with the `case_id`, the `evidence_item_id` of the preserved item, and an immutable `kind`: `AGREEMENT` for the consent path negotiated with the prosecutor, or `MOTION` for a contested court motion. Optional `terms` capture the negotiated scope, laboratory, and cost narrative, and `proposed_test_types` lists the analysis types proposed. Creation records the acting attorney's `X-User-ID` in `created_by_user_id` and lands the authorization in `DRAFTED`.

Three gates guard creation. The owning case must be in `INVESTIGATION` or `TESTING` status, else `ERR_CASE_NOT_READY_FOR_TESTING_AUTH` (HTTP 409). The evidence item's `location_status` must be `CUSTODY_CONFIRMED`, else `ERR_EVIDENCE_NOT_IN_CUSTODY` (HTTP 422). And a `MOTION` is available only where the case's jurisdiction — reached through the intake request — has `has_post_conviction_dna_statute` true, else `ERR_JURISDICTION_NO_TESTING_STATUTE` (HTTP 422); the `AGREEMENT` path has no statutory prerequisite.

The agreement lifecycle is a negotiation loop. From `DRAFTED` the attorney proposes terms (`PROPOSED`); from `PROPOSED` or `NEGOTIATING` a counter-offer keeps the talks in `NEGOTIATING` — countering from `NEGOTIATING` is a legal self-loop for each further round. From `PROPOSED` or `NEGOTIATING` the parties either sign, reaching the terminal `SIGNED`, or the prosecution refuses, reaching the terminal `REJECTED_BY_PROSECUTION`.

The motion lifecycle is a ruling cycle. From `DRAFTED` the attorney files, reaching `FILED`; from `FILED` or `APPEALED` the court's ruling is recorded with a payload `ruling` of `GRANTED` or `DENIED`, stamped into `last_ruling` (null until the first ruling). A denial from `DENIED` may be appealed to `APPEALED`, and a fresh ruling is recorded from there — `DENIED` is terminal only in the sense that its sole exit is an appeal. `GRANTED` and an unappealed `DENIED` end the lifecycle.

The two graphs share the entity but not the transition vocabulary: an agreement event presented against a `MOTION`, or a motion event against an `AGREEMENT`, is `ERR_INVALID_STATE` no matter the current status, as is any event the current status does not admit. Either path to effectiveness — a signature reaching `SIGNED` or a ruling reaching `GRANTED` — re-derives the linked evidence item's `testing_status`, which becomes `TESTING_AUTHORIZED` when no laboratory activity exists on the item yet (§3.5).

While an `AGREEMENT` remains in `DRAFTED`, `PROPOSED`, or `NEGOTIATING`, its `terms` and `proposed_test_types` may be amended. Amendments are recorded under optimistic concurrency control per §2.7: the request must carry `expected_testing_authorization_version` matching the authorization's current `version`, and a stale base is rejected with `ERR_STALE_AUTHORIZATION_VERSION`. Amendments against a `MOTION`, or against an agreement that has left the negotiable statuses, are rejected with `ERR_INVALID_STATE`. A successful amendment applies the provided fields, bumps `version`, and refreshes `updated_at`.

### 3.5. Laboratory Analysis and the Sample Ledger

With an effective authorization in hand, a `StaffAttorney` schedules a `LabAnalysis` against a preserved item: the payload names the `evidence_item_id`, the `authorization_id`, the `lab_name` performing the work, a `test_type` of `DNA_STR`, `DNA_TOUCH`, `DNA_YSTR`, `MITOCHONDRIAL_DNA`, or `SEROLOGY`, the `required_sample_ng` to reserve (at least 1), and the bench window `scheduled_start` to `scheduled_end`, a half-open interval whose end must be strictly after its start.

Creation is the most heavily gated write in the system. The case that owns the evidence item must be in `TESTING` status, else `ERR_CASE_NOT_IN_TESTING` (HTTP 409). The referenced authorization must currently be `SIGNED` or `GRANTED`, else `ERR_AUTHORIZATION_NOT_EFFECTIVE` (HTTP 422). The item's `remaining_sample_ng` must cover the request and stay testable — both at least `required_sample_ng` and at least 5 nanograms, the minimum testable mass — else `ERR_INSUFFICIENT_SAMPLE` (HTTP 422). And the laboratory's bench cannot be double-booked: if another analysis for the same `lab_name` in any status other than `CANCELLED` has a strictly overlapping half-open window — the existing window starts before the new window ends and ends after the new window starts; an endpoint touching an endpoint does not overlap — creation is rejected with `ERR_LAB_SCHEDULE_OVERLAP` (HTTP 409).

A successful creation debits the sample ledger: the item's `remaining_sample_ng` drops by `required_sample_ng`, the analysis records `reserved_sample_ng` equal to that amount, the analysis lands in `SCHEDULED`, and the item's `testing_status` is re-derived — typically to `SAMPLE_RESERVED`. Shipping the sample moves the analysis from `SCHEDULED` to `SAMPLE_SHIPPED`. Recording the result is legal only from `SAMPLE_SHIPPED` and carries the lab's `outcome` (`EXCLUSIONARY`, `INCLUSIONARY`, `INCONCLUSIVE`, or `NO_PROFILE`), the `actual_consumed_ng` (which must be at least 1 and no more than `reserved_sample_ng`, else `ERR_CONSUMED_EXCEEDS_RESERVED`), and whether a comparable profile was obtained (`profile_obtained`). Result entry settles the ledger: any unconsumed portion of the reservation — the difference between `reserved_sample_ng` and `actual_consumed_ng` — is refunded to the item's `remaining_sample_ng`, and the testing status is re-derived. Cancelling is possible only from `SCHEDULED` — once the sample has shipped, the reservation is committed — and refunds the entire `reserved_sample_ng`, again re-deriving the status; the analysis ends `CANCELLED`.

The ledger obeys a strict conservation invariant over each evidence item: `initial_sample_ng` always equals `remaining_sample_ng` plus the reservations of that item's analyses in `SCHEDULED` or `SAMPLE_SHIPPED`, plus the consumed masses of its analyses in `RESULT_RECORDED` or `INTERPRETED`.

The item's `testing_status` re-derives top-down, first match winning, whenever its remaining mass mutates, a sibling analysis changes status, or one of its authorizations becomes effective: below 5 nanograms remaining, `SAMPLE_EXHAUSTED`; else any analysis in `SCHEDULED` or `SAMPLE_SHIPPED`, `SAMPLE_RESERVED`; else any analysis in `RESULT_RECORDED` or `INTERPRETED`, `TESTED`; else any authorization in `SIGNED` or `GRANTED`, `TESTING_AUTHORIZED`; otherwise `UNTESTED`. Because exhaustion is just the top rule, a cancellation refund that restores the remaining mass to at least 5 nanograms flips the item back out of `SAMPLE_EXHAUSTED` on the next derivation.

Two further events refine a recorded result. An expert consultation moves the analysis from `RESULT_RECORDED` to `INTERPRETED`, recording the consulting `expert_name` and an `expert_interpretation` of `SUPPORTS_INNOCENCE`, `NEUTRAL`, or `SUPPORTS_CONVICTION`. And a database comparison may be run from either `RESULT_RECORDED` or `INTERPRETED` — a self-loop that leaves the analysis in its current status — but only when `profile_obtained` is true, else `ERR_INVALID_STATE`. The comparison payload names the `database_name`, a `comparison_result` of `HIT`, `NO_HIT`, or `PARTIAL`, and, on a hit only, a `matched_subject_name`, which is stored on the analysis as `db_matched_subject_name` (null otherwise); supplying a matched name without a `HIT` is `ERR_INVALID_REQUEST`. The outcome lands in `db_comparison_status` (which starts at `NOT_RUN`) as `COMPLETED_HIT`, `COMPLETED_NO_HIT`, or `COMPLETED_PARTIAL`. A `HIT` is the single most consequential write in the pipeline: it sets the owning case's `exculpatory_evidence_flag` true — a flag never auto-cleared once set — re-derives the case's `evidence_posture` (where the flag takes precedence, §3.3), and re-derives the `pattern_case_count` of every `DATABASE_ACCESS` initiative in the case's jurisdiction (§2.6, chain B).

### 3.6. Litigation, Deadlines, and the Path to Exoneration

A case deepens through four working statuses, driven by a `StaffAttorney` or `ManagingAttorney`. From `OPEN`, beginning the investigation moves the case to `INVESTIGATION`, keeping the 90-day contact interval. From `INVESTIGATION`, beginning testing requires that at least one child evidence item be in `CUSTODY_CONFIRMED` — else `ERR_NO_PRESERVED_EVIDENCE` (HTTP 409) — and moves the case to `TESTING`, tightening the contact interval to 60 days (any `contact_overdue` flag is recomputed only when the next sweep runs, §3.7). From `TESTING`, beginning litigation requires that at least one lab analysis on a case evidence item has reached `RESULT_RECORDED` or `INTERPRETED` — else `ERR_NO_TEST_RESULTS` (HTTP 409) — and moves the case to `LITIGATION` with a 30-day contact interval. There is no direct advance into `EXONERATED`; only the petition cascade below enters it.

A case can be abandoned from any working status. Closing is legal from `OPEN`, `INVESTIGATION`, `TESTING`, or `LITIGATION`, requires a payload `resolution` of `UNSUBSTANTIATED`, `EVIDENCE_LOST`, `CLIENT_WITHDREW`, or `OTHER`, and is blocked by unfinished business: any child petition still in `DRAFT`, `FILED`, or `APPEAL_FILED` rejects the close with `ERR_OPEN_PETITIONS_EXIST` (HTTP 409), and any lab analysis on a case item still in `SCHEDULED` or `SAMPLE_SHIPPED` rejects it with `ERR_ACTIVE_LAB_ANALYSES_EXIST` (HTTP 409). A closed case records its `resolution`, sets `contact_interval_days` to null, and clears `contact_overdue`; `CLOSED` is terminal.

Between milestones, the responsible `StaffAttorney` keeps the working file current through the case-update operation of §2.7, which is the only way to mutate a case's `strategy_notes`, `theory_of_case`, and `assigned_attorney_id`. A successful update applies the provided fields, increments the case's `version` by one, and refreshes `updated_at`; the stale-version rejection of §2.7 protects the update against writers whose view of the case predates a completed mutation.

Litigation itself proceeds through `LegalPetition` records drafted by a `StaffAttorney` with the `case_id`, a `petition_type` of `POST_CONVICTION`, `DIRECT_APPEAL`, `CLEMENCY`, or `HABEAS_CORPUS`, the `court_name` or clemency authority addressed, and a `claim_basis` of `ACTUAL_INNOCENCE`, `PROCEDURAL`, or `BOTH`. Drafting requires the case to be in `LITIGATION`, else `ERR_CASE_NOT_IN_LITIGATION` (HTTP 409). Two jurisdictional and evidentiary gates apply at creation: a `CLEMENCY` petition requires the jurisdiction's `clemency_available` flag, else `ERR_CLEMENCY_NOT_AVAILABLE` (HTTP 422); and a `claim_basis` of `ACTUAL_INNOCENCE` or `BOTH` requires the case's `exculpatory_evidence_flag` to be true — database-confirmed exculpatory evidence, per §3.5 — else `ERR_NO_EXCULPATORY_BASIS` (HTTP 422). A new petition sits in `DRAFT`.

Filing moves a petition from `DRAFT` to `FILED` and stamps `filed_at` from the logical clock. Filing re-checks that the case is in `LITIGATION` (`ERR_CASE_NOT_IN_LITIGATION`), and for a `POST_CONVICTION` petition it enforces the statutory deadline: when the jurisdiction's `post_conviction_deadline_years` is not null, the current clock must be no later than the anniversary of the intake request's `conviction_date` that many years out — filing exactly on the anniversary is timely; strictly later is rejected with `ERR_FILING_DEADLINE_EXCEEDED` (HTTP 422). A null deadline means the petition may be filed at any time.

A filed petition awaits the court. Recording a decision is legal from `FILED` or `APPEAL_FILED` and carries a `decision` of `GRANTED` or `DENIED` plus a `vacates_conviction` flag; the flag may be true only on a grant, so a denial carrying `vacates_conviction` true is `ERR_INVALID_REQUEST`. Either branch stamps `decided_at` from the clock, and a grant additionally records the payload's `vacates_conviction` value into the petition's `decision_vacates_conviction`. A grant with `vacates_conviction` true fires the exoneration cascade: the petition's case moves to `EXONERATED`, its `exoneration_date` is set to the current logical clock, `release_readiness` becomes `PLANNING`, and the contact interval tightens to 14 days. A grant without vacatur, or any denial, leaves the case untouched; a denial records `decision_vacates_conviction` false and the petition lands in `DECIDED_DENIED`. `DECIDED_GRANTED` is terminal.

A denied petition may be appealed from `DECIDED_DENIED` to `APPEAL_FILED` — with one exception baked into the domain: clemency denials are unappealable, so appealing a `CLEMENCY` petition is rejected with `ERR_NOT_APPEALABLE` (HTTP 409). The appeal loop then repeats: a fresh decision from `APPEAL_FILED`, and a twice-denied petition may be appealed again.

### 3.7. Client Communication and Release Logistics

Cases run for years, and silence is itself a risk the system tracks. A `ClientServicesAdvocate` logs each client-communication event against the case with a `channel`, an `expectation_setting` of `CAUTIOUS`, `NEUTRAL`, or `OPTIMISTIC` — the level recorded on the case as `last_expectation_setting`, null until the first contact — and an optional `summary`. Each logged contact stamps `last_contact_at` from the logical clock, increments `contact_count`, and clears `contact_overdue` immediately, without waiting for any sweep.

The `contact_overdue` flag is otherwise written only by the contact-overdue sweep, an administrative checkpoint a `PlatformAdmin` runs across every case not in `CLOSED`. The interval a case may go silent depends on its status: 90 days in `OPEN` or `INVESTIGATION`, 60 days in `TESTING`, 30 days in `LITIGATION`, and 14 days in `EXONERATED`; the stored `contact_interval_days` mirrors this map and is null on a `CLOSED` case. For each swept case the sweep computes the whole days between the clock and `last_contact_at` and sets the flag true exactly when that figure strictly exceeds the interval — a case precisely at its interval is not overdue. Cases in `CLOSED` are skipped entirely, their flags left false. Every case whose flag changes — newly overdue or newly cleared — has its `version` incremented, and the sweep reports `swept_case_count`, `newly_overdue_count`, and the `newly_overdue_case_ids`.

Exoneration opens the release checklist. While the case is `EXONERATED` and its `release_readiness` is `PLANNING` or `READY`, the attorney team records checklist progress: the payload's `housing_arranged`, `id_documents_ready`, and `transportation_arranged` keys map onto the case's `release_housing_ready`, `release_id_documents_ready`, and `release_transportation_ready` flags respectively, each key optional with an absent key leaving its flag unchanged, and `scheduled_release_date` is stored when provided. After each update the readiness re-derives: `READY` when all three flags are true, `PLANNING` otherwise — regressing from `READY` back to `PLANNING` by clearing a flag is legal. Attempting the update on a case not in `EXONERATED` is rejected with `ERR_CASE_NOT_EXONERATED` (HTTP 409); on an `EXONERATED` case whose readiness is no longer in the planning states, with `ERR_INVALID_STATE`.

Executing the release is the final step. It requires the case to be `EXONERATED` (`ERR_CASE_NOT_EXONERATED` otherwise), requires `release_readiness` to be exactly `READY` — else `ERR_RELEASE_NOT_READY` (HTTP 409) — and requires the logical clock to have reached the `scheduled_release_date`, else `ERR_RELEASE_DATE_NOT_REACHED` (HTTP 409). A successful execution sets `release_readiness` to `RELEASED`. Until a case is exonerated its readiness reads `NOT_APPLICABLE`; the full progression is `NOT_APPLICABLE` → `PLANNING` → `READY` → `RELEASED`, with the `PLANNING` ↔ `READY` oscillation driven purely by the checklist flags.

### 3.8. Statutory Compensation for the Exonerated

Where a jurisdiction has a wrongful-conviction compensation statute, the organization pursues it. A `StaffAttorney` opens a `CompensationClaim` against an `EXONERATED` case — any other status is `ERR_CASE_NOT_EXONERATED` — in a jurisdiction whose `compensation_statute_exists` flag is true, else `ERR_NO_COMPENSATION_STATUTE` (HTTP 422). The claim carries the `case_id`, the claimant-declared `years_incarcerated_claimed` (at least 1), and optionally `documented_legal_fees_cents` (zero or more, defaulting to 0). It starts in `DRAFT`, and creation freezes a provisional estimate into `provisional_estimate_cents`.

The provisional estimate is deliberately simple: a flat 5,000,000 cents per claimed year, capped at the jurisdiction's `compensation_cap_cents` when that cap is not null — with no exculpatory enhancement and no fee reimbursement. The final award, computed when the claim is approved, is a different and larger instrument, evaluated in a pinned order. First, the system-verified duration replaces the declared one: `verified_years` is the whole-year floor of the days between the intake request's `conviction_date` and the case's `exoneration_date`, reached through the case's `intake_request_id`, dividing the UTC day count by 365 and discarding the remainder. Second, a tiered base is priced at 5,000,000 cents per year for the first 5 verified years and 7,500,000 cents per verified year beyond 5. Third, when the case's `exculpatory_evidence_flag` is true and the jurisdiction's `actual_innocence_enhancement_pct` is greater than zero, the tiered base is multiplied by one plus that percentage over one hundred and floored to whole cents. Fourth, the statutory cap bites: the award before fees is the lesser of the enhanced tiered base and `compensation_cap_cents`, or the enhanced base itself when the cap is null. Fifth — and only after the cap — the fee reimbursement is added: the lesser of `documented_legal_fees_cents` and the 2,500,000-cent reimbursement ceiling. The cap never eats the fee reimbursement.

Two worked anchors pin the arithmetic. With a conviction date of 2016-03-15 and an exoneration date of 2026-11-20, the day count is 3902 and the verified duration 10 years; with 10 years claimed, a 10 percent enhancement with the exculpatory flag set, a cap of 100,000,000 cents, and 3,000,000 cents of documented fees, the provisional estimate is 50,000,000 cents, while the final award is the enhanced base of 68,750,000 (under the cap) plus the capped 2,500,000 of fees: 71,250,000 cents. With the same facts but a cap of 60,000,000 cents, the cap bites the enhanced base first and the fees still ride on top: 60,000,000 plus 2,500,000 equals 62,500,000 cents.

The claim lifecycle mirrors the courts'. Filing moves `DRAFT` to `FILED`. Recording a decision from `FILED` or `APPEALED` either approves the claim — computing `final_award_cents` per the final verified formula above — or denies it, and a denial re-derives the `pattern_case_count` of every `COMPENSATION_REFORM` initiative in the case's jurisdiction. A `DENIED` claim may be appealed to `APPEALED`, from which a fresh decision is recorded with the same two branches. An `APPROVED` claim is paid by recording a `paid_amount_cents` that must equal `final_award_cents` exactly — any other figure is `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — moving the claim to its terminal `PAID` status.

### 3.9. Reentry Referrals and Policy Reform

Release is the beginning of the client's hardest stretch, and the organization books services against real provider capacity. A `ClientServicesAdvocate` registers each `ReentryProvider` with a `name`, a `service_type` of `HOUSING`, `EMPLOYMENT`, `MEDICAL`, or `COUNSELING`, and a `total_capacity` of at least 1 — the maximum number of referrals whose service windows may overlap. The provider's `slots_in_use` is a computed count of its referrals in `PENDING` or `ACTIVE` status, written on referral creation, completion, and cancellation; it starts at 0.

Referring an exonerated client creates a `ReentryReferral` with the `case_id`, the `provider_id`, and a half-open service window `service_start` to `service_end` whose end must be strictly after its start. The case must be `EXONERATED`, else `ERR_CASE_NOT_EXONERATED`. Capacity is enforced as an overlapping-window aggregate: counting the provider's live referrals — those in `PENDING` or `ACTIVE` — whose windows strictly overlap the new one (the existing window starts before the new window ends and ends after the new window starts; a window that merely touches the new one at an endpoint does not overlap), the create is allowed only when that count is below `total_capacity`; a count already equal to capacity means the provider is full for that window and the create is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED` (HTTP 409). A successful create lands the referral in `PENDING` and increments the provider's `slots_in_use` (bumping the provider's `version`). Activation moves a `PENDING` referral to `ACTIVE` once the logical clock has reached `service_start` — earlier activation is `ERR_SERVICE_WINDOW_NOT_STARTED` (HTTP 409) — and changes no slot accounting, since a pending referral already occupies a slot. Completion from `ACTIVE`, or cancellation from `PENDING` or `ACTIVE`, releases the slot: `slots_in_use` decrements and the provider's `version` increments. `COMPLETED` and `CANCELLED` are terminal.

The last workflow turns casework into reform. A `PolicyDirector` opens a `PolicyInitiative` with the `jurisdiction_id` whose case patterns inform it, a `topic` of `EVIDENCE_PRESERVATION`, `COMPENSATION_REFORM`, `DATABASE_ACCESS`, or `RECORDS_TRANSPARENCY`, and a `title`; the initiative starts `PROPOSED` with an initial `pattern_case_count` derivation. The pattern count aggregates distinct cases in the initiative's jurisdiction — reached through each case's intake request, and counting cases of any status, open or closed — that match the topic's pattern: for `EVIDENCE_PRESERVATION`, a case whose `destroyed_evidence_count` is at least 1; for `COMPENSATION_REFORM`, a case with at least one compensation claim in `DENIED` or `APPEALED`; for `DATABASE_ACCESS`, a case with at least one descendant lab analysis whose `db_comparison_status` is `COMPLETED_HIT`; for `RECORDS_TRANSPARENCY`, a case with at least one records request in `DENIED`. The count is stored on the initiative and re-derived whenever a qualifying case mutation occurs — the destruction cascade, a claim denial, a database hit, or a records denial — refreshing `updated_at` and bumping `version` when the number actually changes.

An initiative's lifecycle tracks the advocacy work: research begins from `PROPOSED` to `RESEARCHING`; submitting a draft moves `RESEARCHING` to `DRAFTED` and is gated on evidence — `pattern_case_count` must be at least 3, the pattern threshold, else `ERR_INSUFFICIENT_PATTERN_EVIDENCE` (HTTP 409); adoption moves `DRAFTED` to the terminal `ADOPTED`. Initiatives also stall: from `RESEARCHING` or `DRAFTED` a stall moves the initiative to `STALLED`, and a resume returns it to `RESEARCHING`, from where the pattern threshold must be satisfied again before another draft submission.

## 4. Endpoint Definitions

All resources live at the top level of the API; paths below are absolute from the domain root. Operations that create a new resource return `201 Created`; reads, list operations, state advances, updates, and all other actions on existing resources return `200 OK`. The request and response bodies of each endpoint are governed by the narratives in §2 and §3 rather than by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/ops/contact-overdue-sweep` | Re-evaluate contact-overdue flags across all open cases | PlatformAdmin |
| POST | `/jurisdictions` | Register a jurisdiction and its statutory feature flags | PlatformAdmin |
| GET | `/jurisdictions/{id}` | Read one jurisdiction | All roles |
| GET | `/jurisdictions/{id}/policy-initiatives` | List policy initiatives of a jurisdiction | All roles except Client |
| POST | `/clients` | Register an incarcerated person requesting assistance | IntakeSpecialist |
| GET | `/clients/{id}` | Read one client (Client role reads only its own record) | All roles |
| POST | `/intake-requests` | Create an intake request (Client self-submission allowed) | IntakeSpecialist, Client |
| GET | `/intake-requests` | List intake requests with filters | All roles except Client |
| GET | `/intake-requests/{id}` | Read one intake request (Client role: own requests only) | All roles |
| POST | `/intake-requests/{id}/advance` | Screening transitions: BEGIN_SCREENING, REQUEST_MORE_INFO, RECOMMEND | IntakeSpecialist |
| POST | `/intake-requests/{id}/submit-supplement` | Supply requested supplemental information | Client, IntakeSpecialist |
| POST | `/intake-requests/{id}/decide` | Managing-attorney decision; acceptance creates the case | ManagingAttorney |
| POST | `/intake-requests/activate-waitlist-next` | Activate the highest-priority waitlisted request back into screening | ManagingAttorney |
| GET | `/intake-requests/{id}/cases` | List the case created from this intake request (0 or 1 element) | All roles except Client |
| GET | `/cases/{id}` | Read one case (Client role: own case only) | All roles |
| PUT | `/cases/{id}` | Update case strategy fields under optimistic concurrency | StaffAttorney |
| POST | `/cases/{id}/advance` | Case lifecycle: BEGIN_INVESTIGATION, BEGIN_TESTING, BEGIN_LITIGATION, UPDATE_RELEASE_CHECKLIST, EXECUTE_RELEASE, CLOSE | StaffAttorney, ManagingAttorney |
| POST | `/cases/{id}/log-contact` | Log a client-communication event at the current logical clock | ClientServicesAdvocate |
| GET | `/cases/{id}/evidence-items` | List evidence items of a case | All roles except Client |
| GET | `/cases/{id}/records-requests` | List records requests of a case | All roles except Client |
| GET | `/cases/{id}/testing-authorizations` | List testing authorizations of a case | All roles except Client |
| GET | `/cases/{id}/legal-petitions` | List legal petitions of a case | All roles except Client |
| GET | `/cases/{id}/compensation-claims` | List compensation claims of a case | All roles except Client |
| GET | `/cases/{id}/reentry-referrals` | List reentry referrals of a case | All roles except Client |
| POST | `/evidence-items` | Register a physical evidence item on a case | EvidenceAnalyst |
| GET | `/evidence-items/{id}` | Read one evidence item | All roles except Client |
| POST | `/evidence-items/{id}/advance` | Location-dimension transitions: START_SEARCH, MARK_LOCATED, MARK_MISSING, CONFIRM_CUSTODY, VERIFY_DESTRUCTION | EvidenceAnalyst |
| GET | `/evidence-items/{id}/testing-authorizations` | List testing authorizations for an evidence item | All roles except Client |
| GET | `/evidence-items/{id}/lab-analyses` | List lab analyses for an evidence item | All roles except Client |
| POST | `/records-requests` | Open a records request to a court, police, laboratory, or medical-examiner agency | EvidenceAnalyst |
| POST | `/records-requests/{id}/advance` | Records lifecycle: SUBMIT, RECORD_RESPONSE, APPEAL | EvidenceAnalyst |
| POST | `/testing-authorizations` | Create a testing agreement or testing motion for a preserved item | StaffAttorney |
| GET | `/testing-authorizations/{id}` | Read one testing authorization | All roles except Client |
| POST | `/testing-authorizations/{id}/advance` | Kind-conditional lifecycle: PROPOSE, COUNTER, SIGN, REJECT (agreement); FILE, RECORD_RULING, APPEAL (motion) | StaffAttorney |
| POST | `/testing-authorizations/{id}/amendments` | Amend agreement terms under optimistic concurrency | StaffAttorney |
| GET | `/testing-authorizations/{id}/lab-analyses` | List lab analyses authorized by this authorization | All roles except Client |
| POST | `/lab-analyses` | Schedule a lab analysis, reserving sample mass and a bench window | StaffAttorney |
| POST | `/lab-analyses/{id}/advance` | Lab lifecycle: SHIP_SAMPLE, RECORD_RESULT, RECORD_EXPERT_INTERPRETATION, RUN_DATABASE_COMPARISON, CANCEL | StaffAttorney, EvidenceAnalyst |
| POST | `/legal-petitions` | Draft a legal petition for a case in litigation | StaffAttorney |
| POST | `/legal-petitions/{id}/advance` | Petition lifecycle: FILE, RECORD_DECISION, APPEAL | StaffAttorney |
| POST | `/compensation-claims` | Open a statutory compensation claim for an exonerated case | StaffAttorney |
| POST | `/compensation-claims/{id}/advance` | Claim lifecycle: FILE, RECORD_DECISION, APPEAL, RECORD_PAYMENT | StaffAttorney |
| POST | `/reentry-providers` | Register a reentry service provider with a fixed capacity | ClientServicesAdvocate |
| GET | `/reentry-providers/{id}` | Read one reentry provider | All roles except Client |
| GET | `/reentry-providers/{id}/reentry-referrals` | List referrals held by a provider | All roles except Client |
| POST | `/reentry-referrals` | Refer an exonerated client to a provider for a service window | ClientServicesAdvocate |
| POST | `/reentry-referrals/{id}/advance` | Referral lifecycle: ACTIVATE, COMPLETE, CANCEL | ClientServicesAdvocate |
| POST | `/policy-initiatives` | Open a policy-reform initiative informed by case patterns | PolicyDirector |
| POST | `/policy-initiatives/{id}/advance` | Initiative lifecycle: BEGIN_RESEARCH, SUBMIT_DRAFT, ADOPT, STALL, RESUME | PolicyDirector |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can raise and the HTTP status it carries. The conditions under which each error fires are specified in the narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_INTAKE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_EVIDENCE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_RECORDS_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_TESTING_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_ANALYSIS_NOT_FOUND` | 404 Not Found |
| `ERR_LEGAL_PETITION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPENSATION_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REENTRY_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_REENTRY_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_INITIATIVE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TRANSITION_EVENT` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AUTHORIZATION_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_IN_LITIGATION` | 409 Conflict |
| `ERR_CASE_NOT_EXONERATED` | 409 Conflict |
| `ERR_CASE_NOT_READY_FOR_TESTING_AUTH` | 409 Conflict |
| `ERR_CASE_NOT_IN_TESTING` | 409 Conflict |
| `ERR_NO_PRESERVED_EVIDENCE` | 409 Conflict |
| `ERR_NO_TEST_RESULTS` | 409 Conflict |
| `ERR_OPEN_PETITIONS_EXIST` | 409 Conflict |
| `ERR_ACTIVE_LAB_ANALYSES_EXIST` | 409 Conflict |
| `ERR_WAITLIST_EMPTY` | 409 Conflict |
| `ERR_NOT_APPEALABLE` | 409 Conflict |
| `ERR_RELEASE_NOT_READY` | 409 Conflict |
| `ERR_RELEASE_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_SERVICE_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_LAB_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_PROVIDER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_PATTERN_EVIDENCE` | 409 Conflict |
| `ERR_DECISION_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SCREENING_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_NOT_IN_CUSTODY` | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_SAMPLE` | 422 Unprocessable Entity |
| `ERR_CONSUMED_EXCEEDS_RESERVED` | 422 Unprocessable Entity |
| `ERR_FILING_DEADLINE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CLEMENCY_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_JURISDICTION_NO_TESTING_STATUTE` | 422 Unprocessable Entity |
| `ERR_NO_EXCULPATORY_BASIS` | 422 Unprocessable Entity |
| `ERR_NO_COMPENSATION_STATUTE` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STATE_CODE` | 409 Conflict |
