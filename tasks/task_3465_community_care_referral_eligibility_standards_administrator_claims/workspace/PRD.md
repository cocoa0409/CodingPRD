# Community Care Referral API — Product Requirements Document

## 1. Introduction

When the Veterans Health Administration cannot furnish care that is geographically accessible or timely enough inside its own facilities, an enrolled veteran may instead receive that care from a community provider. This API is the system of record for that community-care pathway. It determines a veteran's eligibility for community care against drive-time, wait-time, and service-availability access standards (including the veteran's statutory choice element), issues referral authorizations that scope an episode of care by visit count and calendar duration, and then tracks the episode through scheduling, delivery, documentation return, and final settlement.

Two administrative realities shape the design. First, the community network is run by third-party administrators under contract: providers are credentialed into those networks, appointments are scheduled by whichever side the provider's contract assigns, claims flow through the administering third-party administrator, and a denial-rate surveillance mechanism can suspend an entire network automatically. Second, the benefit is compliance-audited end to end — a visit ledger on every authorization and a set of payment buckets on every provider are kept conserved at all times, and every time-dependent rule reads a controllable logical clock rather than the wall clock. VAMC-side staff (eligibility clerks, care coordinators, network managers), administrator operators, community provider representatives, veterans, and system pharmacists all act on the same resources under a strict role-and-ownership model. All resources are mounted under `/community-care`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request where either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The system recognizes exactly eight roles, spelled as follows: `PlatformAdmin`, `EligibilityClerk`, `CareCoordinator`, `NetworkManager`, `TPAAdministrator`, `ProviderRep`, `Veteran`, and `SystemPharmacist`.

`PlatformAdmin` is the platform operator who seeds reference data (care stations, third-party administrators) and drives the logical clock. `EligibilityClerk` is the VAMC enrollment and eligibility clerk who enrolls veterans, runs eligibility determinations, and may register urgent care visits on a veteran's behalf. `CareCoordinator` is the VAMC care coordinator who authors and authorizes referrals, schedules VAMC-side appointments, reviews returned documentation, and decides extension requests. `NetworkManager` is the VAMC community-care network manager who runs credentialing and contracting decisions. `TPAAdministrator` is a third-party administrator operator who onboards providers into its own network, schedules TPA-side appointments, and adjudicates and reverses claims. `ProviderRep` is a community provider representative who completes appointments, returns documentation, submits and resubmits claims, and originates prescriptions. `Veteran` is the veteran, who self-registers urgent care visits and may cancel their own referrals. `SystemPharmacist` is the system pharmacy operator who fills or refuses routed prescriptions.

Role identity — the meaning of `X-User-ID` — differs by role and is part of the contract:

- When `X-User-Role` is `TPAAdministrator`, `X-User-ID` is the `id` of the acting `ThirdPartyAdministrator`; ownership checks on any resource that references a third-party administrator compare the resource's `tpa_id` foreign key to `X-User-ID`.
- When `X-User-Role` is `ProviderRep`, `X-User-ID` is the `id` of the acting `CommunityProvider`; ownership checks on any resource that references a community provider compare the resource's `provider_id` foreign key to `X-User-ID`.
- When `X-User-Role` is `Veteran`, `X-User-ID` is the `id` of the acting `Veteran`; ownership checks on any resource that references a veteran compare the resource's `veteran_id` foreign key to `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `EligibilityClerk`, `CareCoordinator`, `NetworkManager`, or `SystemPharmacist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

An ownership failure — an entity-backed caller acting on a resource owned by a different entity, or a scheduler whose role does not match the authorization's scheduling responsibility — is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this contract — care stations, third-party administrators, community providers, veterans, eligibility assessments, referral authorizations, extension requests, appointments, medical documentation records, claims, urgent care visits, and prescription fill requests — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations performed by automatic cascades.

Because cascades and reviewer decisions mutate parent resources, a `version` can advance without the client having touched the parent directly; clients that act on a parent should always read its current `version` first. No entity in this contract omits `updated_at` or `version`.

### 2.5. The Logical Clock and Its Scheduled Sweeps

All time-dependent behavior in the system — deadlines, episode windows, timestamped transitions, visit dates — is governed by a single logical clock, never by the wall clock. At startup the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability, `POST /community-care/_clock/set_current_utc`, advances the clock to a caller-supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every system-stamped field in this document (authorization timestamps, completion timestamps, submission timestamps, documentation deadlines, review decision timestamps, urgent care visit dates) is taken from this logical clock at the moment the operation executes.

Each clock set triggers three system sweeps, executed in this exact order:

1. **Episode expiry sweep.** Every authorization in `AUTHORIZED` or `ACTIVE` status whose current calendar date has reached or passed its `end_date_exclusive`, while its `remaining_visits` is still greater than zero, transitions to `EXPIRED`, with the expiry cascades described in §3.3 (scheduled appointments cancelled, pending extension requests auto-denied).
2. **Documentation overdue sweep.** Every medical documentation record in `AWAITED` status whose `deadline_at` is earlier than the new clock instant transitions to `OVERDUE`, cascading its authorization into `DOCS_SUSPENDED` (when the authorization is `AUTHORIZED` or `ACTIVE`) and auto-denying that authorization's pending extension requests, as described in §3.6.
3. **Auto-close sweep.** Every authorization in `EXPIRED` or `EXHAUSTED` status that has no documentation record in `AWAITED`, `RECEIVED`, or `OVERDUE` transitions to `CLOSED`.

### 2.6. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control, each guarded on the version of a parent entity:

- A `POST /community-care/veterans/{id}/eligibility-assessments` request must carry `expected_veteran_version` equal to the target veteran's current `version`. If another writer has advanced the veteran's version since the client last read it — for example because a prior successful assessment creation for the same veteran superseded the older current assessment and bumped the veteran's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of which assessment is current is out of date.
- A `POST /community-care/referral-authorizations/{id}/extension-requests/{extId}/decide` request must carry `expected_referral_authorization_version` equal to the parent authorization's current `version`. If the authorization's version has advanced since the reviewer last observed it — for example because an approved extension mutated the episode scope and bumped the version — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the reviewer from deciding on an obsolete episode scope.

Both fields are non-optional on their respective endpoints. Endpoints not listed here do not take a version field.

### 2.7. Units, Precision, and Rounding

All monetary amounts in the system — billed totals, paid amounts, contract rates, fee deductions, copayments, and the provider payment buckets — are integer cents; no fractional cents ever appear. Drive times are expressed in minutes with exactly 1 decimal place, rounded half up. The network denial rate is a ratio with exactly 4 decimal places, rounded half up, and is defined as zero while no claim-finalization events exist. Claim payment computation rounds the administrator fee half up to a whole cent on each service line individually, and only then sums the per-line nets; rounding the aggregate instead of the lines is non-conformant. Calendar arithmetic (episode windows, filing windows, timeliness lags) operates on whole calendar dates, and every window in this contract is half-open: the start date is included, the end date is excluded.

### 2.8. The Request Validation Pipeline and Error Precedence

Every mutation request passes through a fixed validation pipeline. Stages are evaluated in the order below, and the first failing stage produces the response — an earlier failure masks all later checks, so the error a caller receives always identifies the earliest unmet obligation:

1. **Header context (all endpoints).** `X-User-ID` and `X-User-Role` must be present and non-empty; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role admission (all endpoints).** The supplied role must be listed among the endpoint's authorized roles; otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Existence (all resource endpoints).** Path identifiers are validated left to right, and foreign keys supplied in the request body must reference existing resources; otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **Request shape (all mutation endpoints).** Required fields must be present, types must be correct, enum members must be valid, arrays that require elements must contain at least one, and exactly one of `urgent_care_visit_id` or `appointment_id` must be present on a prescription fill request; otherwise `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency (only the two endpoints named in §2.6).** The expected parent version must match the parent's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
6. **Ownership (ownership-scoped endpoints).** An entity-backed caller must own the target — a `Veteran` acts only on their own `veteran_id`, a `ProviderRep` only on their own provider's appointments, claims, and documentation, a `TPAAdministrator` only on their own network's providers and claims — and the scheduling caller's role must match the authorization's `scheduling_responsibility` (a `TPAAdministrator` of the authorization's `tpa_id` when it is `TPA`, a `CareCoordinator` when it is `VAMC`); otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
7. **Lifecycle state gates (state-gated endpoints, HTTP 409).** Claim creation requires the authorization to be in `ACTIVE`, `EXPIRED`, `EXHAUSTED`, or `CLOSED` (else `ERR_REFERRAL_NOT_ACTIVE`) and the administering network to be `ACTIVE` (else `ERR_TPA_SUSPENDED`); referral creation requires a `CURRENT` assessment (else `ERR_ASSESSMENT_SUPERSEDED`); extension creation requires an `AUTHORIZED` or `ACTIVE` authorization (else `ERR_EXTENSION_WINDOW_CLOSED`); every other transition guard of every state machine rejects with `ERR_INVALID_STATE`.
8. **Regulatory and safety gates (HTTP 422).** Referral creation requires an eligible assessment (else `ERR_SERVICE_NOT_ELIGIBLE`), a `CREDENTIALED` provider (else `ERR_PROVIDER_NOT_CREDENTIALED`), and no `OVERDUE` documentation on any of the veteran's authorizations (else `ERR_DOCS_OUTSTANDING`); claim creation and claim adjudication each require a `CREDENTIALED` provider (else `ERR_PROVIDER_NOT_CREDENTIALED`); prescription fill creation rejects a `controlled_substance` request (else `ERR_CONTROLLED_RX_NOT_ALLOWED`) and requires the submitting provider representative to be `CREDENTIALED` (else `ERR_PROVIDER_NOT_CREDENTIALED`); extension approval requires that no documentation of the authorization is in `AWAITED`, `RECEIVED`, or `OVERDUE` (else `ERR_DOCS_NOT_ACCEPTED`).
9. **Temporal rules (HTTP 422).** A claim's `service_date` must lie within the timely filing window of the submission date (else `ERR_UNTIMELY_FILED`, checked on claim creation and again on resubmission) and inside the episode window (else `ERR_SERVICE_DATE_OUTSIDE_EPISODE`); an appointment's scheduled date must lie inside the episode window (else `ERR_AUTH_WINDOW_VIOLATION`); an urgent care visit colliding with another recorded visit of the same veteran on the same calendar date is rejected with `ERR_SAME_DAY_URGENT_VISIT`.
10. **Constraint rules (HTTP 409).** A provider's 60-minute appointment slots may not overlap (else `ERR_APPOINTMENT_SLOT_CONFLICT`); a new episode may not overlap a non-terminal episode of the same veteran and service code (else `ERR_EPISODE_OVERLAP`); extension requests beyond the visit or day caps are rejected with `ERR_EXTENSION_CAP`; scheduling with no visits remaining is rejected with `ERR_NO_VISITS_REMAINING`; a days-of-supply above the link-type cap is rejected with `ERR_DAYS_SUPPLY_EXCEEDED`; a claim that has already been resubmitted the maximum number of times is rejected with `ERR_RESUBMISSION_LIMIT`.
11. **Referential consistency (HTTP 422).** A referral's `service_code` must equal the referenced assessment's `service_code` (else `ERR_SERVICE_CODE_MISMATCH`); the provider's contracted `service_codes` must contain the requested `service_code` (else `ERR_PROVIDER_SERVICE_MISMATCH`); a claim requires a completed appointment on the authorization whose scheduled date equals the claim's `service_date` (else `ERR_NO_MATCHING_COMPLETED_APPOINTMENT`).
12. **Fiscal sanity (HTTP 422, claim creation and resubmission).** Every claim service line must have `units` of at least 1 and a positive `unit_billed_cents`; otherwise `ERR_AMOUNT_INVALID`.

### 2.9. Nested Resource Retrieval

Requests that target nested resources validate the path's identifiers strictly left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later identifier or body reference is examined. A request for an extension request under a non-existent authorization, for example, fails on the authorization identifier before the extension identifier is even looked up.

### 2.10. Conserved Ledgers: Visit Accounting and Provider Payment Buckets

Two quantities are conserved at all times and may be relied upon by any reader. First, the visit ledger of every authorization always balances: `authorized_visits` plus `extended_visits` equals `completed_visits` plus `reserved_visits` plus `remaining_visits`. Scheduling an appointment is the forward action (the reserved count rises by one and the remaining count falls by one); cancelling a scheduled appointment is the compensating action (the reserved count falls by one and the remaining count rises by one). Second, the payment buckets of every provider always balance: `lifetime_paid_cents` equals `current_paid_cents` plus `reversed_cents`. A paid adjudication adds the paid amount to both the lifetime and current buckets; a payment reversal moves the paid amount from the current bucket to the reversed bucket, leaving the lifetime total untouched. Reversals never decrement the lifetime figure, which is therefore monotonic over the provider's history.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Care Stations, Administrators, and Provider Credentialing

Before any veteran can be evaluated, the platform seeds its reference data. A `PlatformAdmin` registers each VA **care station** with its `name`, its geodetic position (`latitude` between -90 and 90 decimal degrees, `longitude` between -180 and 180), and the two wait-time yardsticks used by the access standards: `primary_wait_days`, the current average next-available wait in days for primary care at that station, and `specialty_wait_days`, the same figure for specialty care; both waits are non-negative integers. The station's `service_codes` list — an array of strings that may be empty — records which services are clinically available there, and it anchors the service-availability leg of eligibility.

A `PlatformAdmin` also registers each **third-party administrator** with a `name` and the `region_code` it administers. A new administrator begins with `contract_status` `ACTIVE` and a clean surveillance slate: `adjudicated_events` and `denied_events` both zero and `denial_rate` zero. Reading an administrator back always exposes those live denial metrics alongside its contract status.

Network growth happens one provider at a time. A `TPAAdministrator` onboards a **community provider** into its own network — the administrator in the path must be the caller's own, or the request fails with `ERR_OWNERSHIP_MISMATCH`. The onboarding payload carries the practice's `name`, the `service_codes` it is contracted to deliver, its `contract_scheduling` designation (`TPA` when the administrator schedules appointments for episodes routed to this provider, `VAMC` when the health system does), its practice `latitude` and `longitude`, and an optional `contract_rates` map from service code to a per-unit allowed rate in cents; when present, a contract rate overrides the Medicare base rate for that service code on claims, and when absent the map defaults to empty. The provider's administering `tpa_id` is taken from the creation path, not from the payload. A freshly onboarded provider starts with `credentialing_status` `PENDING` and all three payment buckets (`lifetime_paid_cents`, `current_paid_cents`, `reversed_cents`) at zero. A network's provider roster can be listed with an optional `credentialing_status` filter.

Credentialing is a lifecycle driven by a `NetworkManager` through credentialing decisions that name a `target_status`. Exactly five transitions are legal: `PENDING` to `CREDENTIALED`, `PENDING` to `DECREDENTIALED`, `CREDENTIALED` to `SUSPENDED`, `SUSPENDED` to `CREDENTIALED`, and `CREDENTIALED` to `DECREDENTIALED`. Any decision whose target does not form one of these pairs with the provider's current status — including any move out of `DECREDENTIALED`, which is terminal — is rejected with `ERR_INVALID_STATE`.

Decredentialing a `CREDENTIALED` provider carries a two-link cascade. First, every claim of that provider still in `RECEIVED` status is auto-denied, with its `denial_reason` recorded as `PROVIDER_DECREDENTIALED`. Second, each of those cascade auto-denials is a claim-finalization event on the claim's administrator: `adjudicated_events` and `denied_events` each increase by one, `denial_rate` is recomputed, and the auto-suspension check runs.

That surveillance check guards every network continuously. On every claim-finalization event — an adjudication decided `PAID`, an adjudication decided `DENIED`, or a cascade auto-denial — the administrator's `adjudicated_events` rises by one, and `denied_events` rises by one whenever the outcome was a denial; resubmissions and payment reversals do not move either counter. The `denial_rate` is the denied count divided by the adjudicated count, rounded half up to 4 decimal places, and is zero while no events exist. When a recompute lands on an `adjudicated_events` of at least 5 **and** a `denial_rate` strictly greater than 0.20, the administrator's `contract_status` flips from `ACTIVE` to `SUSPENDED` automatically; a rate of exactly 0.20 does not suspend. While an administrator is `SUSPENDED`, new claim submissions for authorizations under that network are rejected with `ERR_TPA_SUSPENDED`. Suspension is absorbing — this contract defines no reinstatement path back to `ACTIVE`.

### 3.2. Veteran Enrollment and the Eligibility Determination

An `EligibilityClerk` enrolls each **veteran** with a `full_name`, the `home_station_id` of the veteran's VA home station (the yardstick against which access standards are measured), an integer `priority_group` from 1 to 8, and the residence coordinates `home_latitude` and `home_longitude` that serve as the drive-time origin. Veterans can be listed with optional `home_station_id` and `priority_group` filters.

Eligibility for community care is determined per service by running an **eligibility assessment** against a veteran. The clerk supplies the `service_code` being evaluated (for example, `PT_EVAL`), the `service_category` (`PRIMARY_CARE` or `SPECIALTY_CARE`, which selects which drive-time and wait-time standards apply), the `geo_classification` (`URBAN` or `RURAL`, which selects the drive-time variant), a `choice_requested` flag recording whether the veteran invokes the community-care choice element, and the OCC field `expected_veteran_version` described in §2.6.

Creation computes the determination in a fixed sequence. First, `drive_time_minutes` measures the journey from the veteran's residence to the home station: the great-circle distance in miles between the two coordinate pairs is computed with the haversine formula using an earth radius of 3958.8 miles, and that crow-fly distance is converted to road minutes under the selected variant. The urban variant multiplies the distance by a circuity factor of 1.4 and assumes 40 miles per hour — that is, distance times 1.4, divided by 40, times 60, exactly 2.1000 minutes per crow-fly mile. The rural variant multiplies by a circuity factor of 1.2 and assumes 55 miles per hour — distance times 1.2, divided by 55, times 60, exactly 1.3091 minutes per crow-fly mile, so identical coordinates always yield fewer rural minutes than urban. The result is rounded half up to 1 decimal place.

Second, `wait_days` is read from the home station field matching the requested category — `primary_wait_days` for `PRIMARY_CARE`, `specialty_wait_days` for `SPECIALTY_CARE` — as it stands at assessment time. Third, `service_available` is true exactly when the home station's `service_codes` contain the requested `service_code`.

The three access-standard flags follow. `drive_standard_failed` is true exactly when `drive_time_minutes` is strictly greater than the category standard — 30 minutes for `PRIMARY_CARE`, 60 minutes for `SPECIALTY_CARE`; a drive time exactly equal to the standard passes. `wait_standard_failed` is true exactly when `wait_days` is strictly greater than the category standard — 20 days for `PRIMARY_CARE`, 28 days for `SPECIALTY_CARE`; a wait exactly equal to the standard passes. `choice_granted` is true exactly when `choice_requested` is true and the veteran's `priority_group` is at most 4. Finally, `eligible` is true when any one leg holds: the service is not available at the home station, or the drive-time standard failed, or the wait-time standard failed, or the choice element was granted. Every computed field is stored on the assessment alongside the inputs.

An assessment's `status` begins as `CURRENT`. Because eligibility drifts with station conditions, creating a new assessment for the same veteran and the same `service_code` supersedes the previous `CURRENT` assessment for that pair, moving it to `SUPERSEDED`; supersession is a mutation of the veteran, so the veteran's `version` increments by one on every successful assessment creation. That increment is precisely why the create is version-guarded: a clerk whose expected version is stale is working from an obsolete picture of which assessment is current, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding an assessment the caller never saw. A veteran's assessment history, both `CURRENT` and `SUPERSEDED`, can be listed with optional `status` and `service_code` filters.

### 3.3. Referral Authorizations: Episode Scope, Activation, and Cancellation

A `CareCoordinator` turns a favorable determination into care by creating a **referral authorization**, naming the `veteran_id`, the `assessment_id` of the supporting assessment, the `provider_id` of the chosen community provider, the `service_code`, the `authorized_visits` count (an integer from 1 to the initial cap of 12), the episode `duration_days` (from 1 to at most 365 days), and the `start_date` as an ISO calendar date. The episode window is half-open on calendar dates: it includes `start_date` and excludes `end_date_exclusive`, which is computed as `start_date` plus `duration_days` plus the sum of `requested_extra_days` over that authorization's approved extensions.

Creation is one of the most heavily gated operations in the system, and each gate maps to the pipeline stage of §2.8. The referenced assessment must still be `CURRENT` (a superseded one is rejected with `ERR_ASSESSMENT_SUPERSEDED`) and must have `eligible` true (else `ERR_SERVICE_NOT_ELIGIBLE`). The requested `service_code` must equal the assessment's `service_code` (else `ERR_SERVICE_CODE_MISMATCH`), and the provider's contracted `service_codes` must contain it (else `ERR_PROVIDER_SERVICE_MISMATCH`). The provider must be `CREDENTIALED` (else `ERR_PROVIDER_NOT_CREDENTIALED`). No documentation record on any of the veteran's authorizations — not just the new one — may be `OVERDUE` (else `ERR_DOCS_OUTSTANDING`). And no non-terminal authorization may already exist for the same veteran and the same `service_code` whose half-open episode window overlaps the requested window (else `ERR_EPISODE_OVERLAP`).

At creation the authorization denormalizes its administrative context: `tpa_id` is copied from the provider's administering administrator, and `scheduling_responsibility` is derived as `TPA` exactly when the provider's `contract_scheduling` is `TPA`, otherwise `VAMC`. The visit ledger opens with `extended_visits`, `reserved_visits`, and `completed_visits` at zero and `remaining_visits` equal to `authorized_visits`. The `authorized_at` timestamp stays null and `docs_suspension_return_state` stays null while the authorization waits in its initial `PENDING_REVIEW` status. Authorizations can be listed with `veteran_id`, `provider_id`, `tpa_id`, `assessment_id`, and `status` filters.

Authorization itself is an explicit act: a `CareCoordinator` authorizes a `PENDING_REVIEW` referral, moving it to `AUTHORIZED`, stamping `authorized_at` with the current logical clock, and incrementing the authorization's `version` by one; from any other status the attempt is rejected with `ERR_INVALID_STATE`. Thereafter the episode comes alive on first use — creating the first appointment against an `AUTHORIZED` referral flips it to `ACTIVE` automatically.

Time and usage both close episodes. When a logical-clock set finds an `AUTHORIZED` or `ACTIVE` authorization whose current date has reached or passed `end_date_exclusive` with `remaining_visits` still above zero, the episode transitions to `EXPIRED`: every `SCHEDULED` appointment on it is cancelled (releasing its reserved visit), `remaining_visits` is recomputed per cancellation, and every `PENDING` extension request is auto-denied with `denial_reason` `AUTH_CANCELLED`. Independently, whenever a completion or cancellation recompute drives `remaining_visits` to exactly zero, an `ACTIVE` authorization becomes `EXHAUSTED`. Either way, if no documentation record of the authorization is in `AWAITED`, `RECEIVED`, or `OVERDUE` at that moment, the authorization falls straight through to `CLOSED`; otherwise it waits until the last non-accepted documentation of the episode becomes `ACCEPTED`, at which point `EXPIRED` or `EXHAUSTED` moves to `CLOSED`.

Cancellation is the manual close. A `CareCoordinator`, or the `Veteran` who owns the referral, may cancel it from `AUTHORIZED`, `ACTIVE`, or `DOCS_SUSPENDED`; from any other status the attempt is rejected with `ERR_INVALID_STATE`, and a veteran-role caller whose `X-User-ID` does not match the authorization's `veteran_id` is rejected with `ERR_OWNERSHIP_MISMATCH`. Cancellation cascades exactly like expiry: every `SCHEDULED` appointment becomes `CANCELLED` with its reserved visit released, and every `PENDING` extension request is auto-denied with `denial_reason` `AUTH_CANCELLED`. `CLOSED` and `CANCELLED` are terminal.

### 3.4. Extension Requests: Widening an Episode

When an episode proves too small, either side of the care relationship — a `ProviderRep` or a `CareCoordinator` — files an **extension request** against the authorization, asking for `requested_visits` additional visits and `requested_extra_days` additional episode days. The request must stay within the extension caps: at most 12 additional visits and at most 180 additional days, with the visit ask at least 1 and the day ask at least 0; an ask above either cap is rejected with `ERR_EXTENSION_CAP` (HTTP 409). Extensions can only be requested while the authorization is `AUTHORIZED` or `ACTIVE`; once the episode has moved on, the attempt fails with `ERR_EXTENSION_WINDOW_CLOSED` (HTTP 409). A new request waits in `PENDING` status, with `decided_at` null, and an authorization's extension requests can be listed with an optional `status` filter.

Only a `CareCoordinator` decides, supplying a `decision` of `APPROVED` or `DENIED`, an optional `denial_reason`, and the OCC field `expected_referral_authorization_version`. A decision against a request no longer `PENDING` is rejected with `ERR_INVALID_STATE`; a decision whose expected version does not match the authorization's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.6. Approval carries one further regulatory gate: every documentation record of the authorization must be accepted — none may sit in `AWAITED`, `RECEIVED`, or `OVERDUE` — or the approval is rejected with `ERR_DOCS_NOT_ACCEPTED` (HTTP 422).

An approval widens the episode in place: the authorization's `extended_visits` increases by `requested_visits`, its `end_date_exclusive` is recomputed to absorb the `requested_extra_days`, and the authorization's `version` increments by one. A reviewer denial records the supplied `denial_reason`, stamps `decided_at`, and likewise increments the authorization's `version` by one. Not every denial comes from a reviewer: when an authorization is suspended for overdue documentation, each of its `PENDING` extension requests is auto-denied with `denial_reason` `DOCS_OVERDUE`, and when an authorization expires or is cancelled, each is auto-denied with `denial_reason` `AUTH_CANCELLED`. `APPROVED` and `DENIED` are both terminal.

### 3.5. Scheduling and Delivering Appointments

Who books an appointment depends on the episode's `scheduling_responsibility`. When it is `TPA`, only a `TPAAdministrator` who owns the authorization's `tpa_id` may schedule; when it is `VAMC`, only a `CareCoordinator` may. A caller whose role or network does not match that responsibility is rejected with `ERR_OWNERSHIP_MISMATCH`. The booking payload carries the `scheduled_start` instant (ISO 8601 UTC) and the `requested_date` — the calendar date the veteran asked for, which anchors VAMC-side timeliness. The new appointment's `provider_id` is copied from its authorization as a denormalized read cache; the canonical link remains the `referral_authorization_id` taken from the path.

Three constraint gates protect the booking. The visit ledger must have something left to reserve: scheduling with `remaining_visits` at zero is rejected with `ERR_NO_VISITS_REMAINING` (HTTP 409). The appointment must land inside the episode: the calendar date of `scheduled_start` outside the half-open window from `start_date` up to but not including `end_date_exclusive` is rejected with `ERR_AUTH_WINDOW_VIOLATION` (HTTP 422). And the provider's diary must be free: each appointment occupies the half-open slot from its `scheduled_start` through the following 60 minutes, so a booking that overlaps any of the provider's other `SCHEDULED` appointments' 60-minute slots is rejected with `ERR_APPOINTMENT_SLOT_CONFLICT` (HTTP 409).

A successful booking reserves one visit — `reserved_visits` rises by one and `remaining_visits` falls by one — computes the appointment's timeliness flag, and, if it is the first appointment of an `AUTHORIZED` episode, flips the authorization to `ACTIVE`. Timeliness is measured against an anchor that follows the scheduling split: `timeliness_anchor` is `AUTHORIZED_AT` when the administrator schedules and `REQUESTED_DATE` when the health system schedules, and `within_standard` is true exactly when the number of calendar days from the anchor date (the date part of `authorized_at`, or the `requested_date`) to the date of `scheduled_start` is at most 5 days — the comparison is inclusive, and a negative lag counts as within standard. Because the two variants measure from different anchors, an identical `scheduled_start` can flip `within_standard` between a TPA-scheduled and a VAMC-scheduled episode. Appointments can be listed per authorization with an optional `status` filter.

Delivery is reported by the treating provider. A `ProviderRep` completes one of their own appointments — the caller's identity must equal the appointment's `provider_id`, else `ERR_OWNERSHIP_MISMATCH`, and only a `SCHEDULED` appointment can complete, else `ERR_INVALID_STATE`. Completion stamps `completed_at` from the logical clock, auto-creates the appointment's medical documentation record in `AWAITED` status with a deadline 30 days out, and settles the ledger: `reserved_visits` falls by one, `completed_visits` rises by one, and `remaining_visits` is recomputed; if the remaining count thereby reaches zero, the authorization becomes `EXHAUSTED` as described in §3.3.

Cancelling an appointment — a `CareCoordinator` or `TPAAdministrator` act, or a system cascade from expiry or authorization cancellation — moves a `SCHEDULED` appointment to `CANCELLED` and releases its reservation: `reserved_visits` falls by one and `remaining_visits` is recomputed. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Medical Documentation: Return, Review, and the Suspension Loop

Every completed appointment creates exactly one **medical documentation** record, born `AWAITED` with its `referral_authorization_id` copied from the appointment as a read cache and its `deadline_at` set to the completion timestamp plus 30 days. Until the first submission its `submitted_at` is null. The record for an appointment can be read back as a collection of length zero or one.

Returning documentation is the provider's duty. A `ProviderRep` submits the bundle for one of their own appointments, supplying the `content_ref` (with an optional `note`); a caller who does not own the appointment is rejected with `ERR_OWNERSHIP_MISMATCH`. Submission is only meaningful while the record is `AWAITED` or `OVERDUE` — if no record exists for the appointment, or it is already `RECEIVED` or `ACCEPTED`, the attempt fails with `ERR_DOCUMENTATION_NOT_PENDING` (HTTP 409). A successful submission moves the record to `RECEIVED` and stamps `content_ref` and `submitted_at`. When the record was `OVERDUE`, the episode does not heal on submission alone: the authorization stays `DOCS_SUSPENDED` until a reviewer accepts the bundle.

Review belongs to the `CareCoordinator`, who submits a `decision` of `ACCEPTED` or `REJECTED` (with an optional `rejection_note`). Only a `RECEIVED` record can be reviewed; anything else is rejected with `ERR_DOC_NOT_REVIEWABLE` (HTTP 409). Acceptance is the episode's healing event: when the accepted record leaves no other documentation of the authorization in `AWAITED`, `OVERDUE`, or `RECEIVED`, a `DOCS_SUSPENDED` authorization returns to the state remembered in `docs_suspension_return_state` (`AUTHORIZED` or `ACTIVE`), and an `EXPIRED` or `EXHAUSTED` authorization closes. Rejection loops the record back to `AWAITED`: `rejection_count` rises by one, `deadline_at` resets to the current logical clock plus a 15-day resubmission grace, and the cleared `content_ref` awaits a fresh bundle.

The clock enforces the return requirement even when nobody acts. On each logical-clock set, every `AWAITED` record whose `deadline_at` has passed becomes `OVERDUE`, and that transition cascades: an authorization in `AUTHORIZED` or `ACTIVE` moves to `DOCS_SUSPENDED` with its current state remembered in `docs_suspension_return_state`, and every `PENDING` extension request of the authorization is auto-denied with `denial_reason` `DOCS_OVERDUE`. The suspension lifts when the last `OVERDUE` or `AWAITED` record of the authorization becomes `ACCEPTED`, restoring the remembered state — the authorization can oscillate in and out of `DOCS_SUSPENDED` across an episode, and each entry re-denies whatever extensions are pending at that moment.

### 3.7. Claims: Submission, Adjudication, Resubmission, and Recoupment

Once care is delivered, the provider bills the episode through the administrator. A `ProviderRep` submits a **claim** as the authorization's provider — the caller must own that provider identity, else `ERR_OWNERSHIP_MISMATCH` — supplying the `referral_authorization_id`, the `service_date` as a calendar date, and a non-empty `service_lines` array whose every line names a `service_code`, a `service_category` (`PRIMARY_CARE` or `SPECIALTY_CARE`), an integer `units` of at least 1, and a positive integer `unit_billed_cents`. The claim's `provider_id` and `tpa_id` are copied from the authorization, its `billed_total_cents` is computed as the sum over all lines of `unit_billed_cents` multiplied by `units`, and it enters `RECEIVED` status with `submitted_at` stamped from the logical clock, `resubmit_count` at zero, and `paid_amount_cents` null until a payment decision.

Submission runs the full gauntlet of §2.8's later stages. The authorization must be in `ACTIVE`, `EXPIRED`, `EXHAUSTED`, or `CLOSED` — billing a merely authorized or suspended episode fails with `ERR_REFERRAL_NOT_ACTIVE` (HTTP 409) — and the administering network must be `ACTIVE`, else `ERR_TPA_SUSPENDED` (HTTP 409). The provider must be `CREDENTIALED`, else `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422). Timely filing binds the paperwork to the care: the number of days from `service_date` to the submission date must be at most 180 — the window is inclusive, so exactly 180 days files on time and 181 or more is rejected with `ERR_UNTIMELY_FILED` (HTTP 422). The `service_date` must fall inside the half-open episode window, else `ERR_SERVICE_DATE_OUTSIDE_EPISODE` (HTTP 422). The claim must correspond to delivered care: a `COMPLETED` appointment on the same authorization whose scheduled date equals the `service_date` must exist, else `ERR_NO_MATCHING_COMPLETED_APPOINTMENT` (HTTP 422). And every line must pass fiscal sanity — `units` at least 1, `unit_billed_cents` greater than zero — else `ERR_AMOUNT_INVALID` (HTTP 422). Claims can be listed with `provider_id`, `referral_authorization_id`, `tpa_id`, and `status` filters.

Adjudication belongs to the `TPAAdministrator` who owns the claim's network — any other administrator is rejected with `ERR_OWNERSHIP_MISMATCH`. Only a `RECEIVED` claim can be adjudicated (else `ERR_INVALID_STATE`), and the provider must still be `CREDENTIALED` (else `ERR_PROVIDER_NOT_CREDENTIALED`). The decision is `PAID` or `DENIED`; a denial must carry a `denial_reason` — one of `PROVIDER_DECREDENTIALED`, `CLINICAL_REVIEW`, `DUPLICATE`, or `OTHER` — and a reviewer denial without one is rejected with `ERR_INVALID_REQUEST`.

A `PAID` decision prices the claim line by line, in pinned order, never sum-then-round. For each line, the applicable per-unit rate is the provider's `contract_rates` entry for the line's `service_code` when one exists, and otherwise the Medicare fallback for the line's category: 10000 cents per unit for `PRIMARY_CARE`, 18000 cents per unit for `SPECIALTY_CARE`. The line's allowed amount is the lesser of its billed amount (`unit_billed_cents` times `units`) and the rate times `units`. The administrator's fee on the line is that allowed amount multiplied by 2.5 percent, rounded half up to a whole cent. The line's net is its allowed amount minus its fee, and `paid_amount_cents` is the sum of the per-line nets. Because the fee is rounded per line before summing, the total can differ from a single rounding of the aggregate — and because the rate source is chosen per line, identical lines can price differently depending on whether a contract rate exists. Payment flows into the provider's buckets: `lifetime_paid_cents` and `current_paid_cents` each rise by `paid_amount_cents`. The decision is also a claim-finalization event on the network: `adjudicated_events` rises by one, `denial_rate` is recomputed, and the §3.1 suspension check runs.

A `DENIED` decision — whether by the reviewer or by the decredentialing cascade — records the `denial_reason` and counts doubly against the network: `adjudicated_events` and `denied_events` each rise by one, `denial_rate` is recomputed, and the suspension check runs again.

A denial is not necessarily the end. The owning `ProviderRep` may resubmit a `DENIED` claim with corrected `service_lines`, cycling it back to `RECEIVED` — at most twice per claim: a resubmission attempted when `resubmit_count` has already reached 2 is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 409), and resubmitting from any status but `DENIED` fails with `ERR_INVALID_STATE`. Resubmission re-validates rather than grandfathering: timely filing is re-checked against the claim's `service_date` at resubmission time (else `ERR_UNTIMELY_FILED`), the service date must still sit inside the episode window and match a completed appointment as at creation (else `ERR_SERVICE_DATE_OUTSIDE_EPISODE` or `ERR_NO_MATCHING_COMPLETED_APPOINTMENT`), the replacement lines must again pass fiscal sanity (else `ERR_AMOUNT_INVALID`), and the network must be `ACTIVE` (else `ERR_TPA_SUSPENDED`). A successful resubmission increments `resubmit_count` by one, replaces the lines, recomputes `billed_total_cents`, and resets `submitted_at` to the current logical clock.

Finally, a paid claim can be clawed back. The owning `TPAAdministrator` reverses a `PAID` claim, supplying a free-text `reason`; from any other status the attempt is rejected with `ERR_INVALID_STATE`, and a foreign administrator with `ERR_OWNERSHIP_MISMATCH`. The claim moves to `REVERSED`, its `reversed_reason` is recorded, and the provider's buckets rebalance per §2.10: `current_paid_cents` falls by `paid_amount_cents` while `reversed_cents` rises by the same amount, leaving `lifetime_paid_cents` unchanged. A reversal is not a new claim-finalization event, so the network's denial counters do not move. `REVERSED` is terminal.

### 3.8. The Urgent Care Benefit and Pharmacy Coordination

Urgent care stands apart from referrals: an in-network visit needs no authorization. The veteran self-registers the visit — a `Veteran`-role caller must act on their own `veteran_id`, else `ERR_OWNERSHIP_MISMATCH` — or an `EligibilityClerk` registers it on the veteran's behalf, supplying the `veteran_id` and the `facility_name` of the in-network facility. The `visit_date` is taken from the logical clock's calendar date at creation, and the visit's `fiscal_year` follows the federal year that begins on October 1: when the visit month is October or later the fiscal year is the calendar year plus one, otherwise it is the calendar year. Only one urgent care visit per veteran per calendar date is recordable — a second `RECORDED` visit for the same veteran on the same `visit_date` is rejected with `ERR_SAME_DAY_URGENT_VISIT` (HTTP 422). A recorded visit never transitions: `RECORDED` is its single, permanent status. A veteran's visits can be listed with an optional `fiscal_year` filter.

The copayment is computed at recording time in a fixed order. The visit's `priority_band` derives from the veteran's `priority_group`: `LOW` for groups 1 through 3, `MID` for groups 4 through 6, `HIGH` for groups 7 and 8. The `visit_index_in_fy` is the count of the veteran's other `RECORDED` urgent care visits in the same fiscal year — the new visit is not yet counted — plus one, so the October 1 reset restarts every veteran's annual sequence. The `copay_cents` then follows the band: `LOW` pays 0 cents on every visit; `MID` pays 1500 cents for a `visit_index_in_fy` of 3 or less and 3000 cents from the fourth visit of the fiscal year onward; `HIGH` pays 3000 cents for a `visit_index_in_fy` of 3 or less and 4500 cents from the fourth onward.

Prescriptions originating in the community route back to the system pharmacy through **prescription fill requests**. A `ProviderRep` creates one with a `medication_name`, a `days_supply`, a `controlled_substance` flag, and a link to exactly one care context — an `urgent_care_visit_id` or an `appointment_id`; supplying both or neither is rejected with `ERR_INVALID_REQUEST`. The supply cap follows the link type: at most 14 days of supply when urgent-care-linked and at most 90 days when appointment-linked, with an excess rejected as `ERR_DAYS_SUPPLY_EXCEEDED` (HTTP 409). Safety gates bind the requester: controlled substances are never fillable through this channel, so a request with `controlled_substance` true is rejected with `ERR_CONTROLLED_RX_NOT_ALLOWED` (HTTP 422); the submitting provider must be `CREDENTIALED` (else `ERR_PROVIDER_NOT_CREDENTIALED`); and an appointment-linked request must name one of the caller's own appointments (else `ERR_OWNERSHIP_MISMATCH`) that has already been `COMPLETED` (a lifecycle state gate, else `ERR_INVALID_STATE`). A created request waits in `REQUESTED` status with `decided_at` null, and the collection can be listed with `urgent_care_visit_id`, `appointment_id`, and `status` filters.

A `SystemPharmacist` closes the loop with a `decision` of `FILLED` or `REFUSED`. Only a `REQUESTED` request can be decided, else `ERR_INVALID_STATE`; a refusal must carry a `refusal_reason`, else `ERR_INVALID_REQUEST`. Either decision stamps `decided_at`, a refusal records its `refusal_reason`, and both `FILLED` and `REFUSED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The table below is a routing summary only — request payloads, computed fields, side effects, and the validation pipeline are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/community-care/_clock/set_current_utc` | Set the logical clock and run the time-based sweeps | PlatformAdmin |
| POST | `/community-care/care-stations` | Register a VA care station | PlatformAdmin |
| POST | `/community-care/tpas` | Register a third-party administrator | PlatformAdmin |
| GET | `/community-care/tpas/{id}` | Get a TPA with live denial metrics and contract status | Any |
| POST | `/community-care/tpas/{id}/providers` | Onboard a community provider into a TPA network | TPAAdministrator |
| GET | `/community-care/tpas/{id}/providers` | List the providers of one TPA network | Any |
| POST | `/community-care/providers/{id}/credential-decision` | Credentialing lifecycle decision on a provider | NetworkManager |
| POST | `/community-care/veterans` | Enroll a veteran | EligibilityClerk |
| GET | `/community-care/veterans/{id}` | Get a veteran | Any |
| GET | `/community-care/veterans` | List veterans, filterable by home station and priority group | Any |
| POST | `/community-care/veterans/{id}/eligibility-assessments` | Run an eligibility determination; supersedes the current assessment for the same service | EligibilityClerk |
| GET | `/community-care/veterans/{id}/eligibility-assessments` | List a veteran's assessments, current and superseded | Any |
| POST | `/community-care/referral-authorizations` | Create a referral authorization scoping an episode of care | CareCoordinator |
| GET | `/community-care/referral-authorizations/{id}` | Get an authorization with its visit ledger | Any |
| GET | `/community-care/referral-authorizations` | List authorizations, filterable | Any |
| POST | `/community-care/referral-authorizations/{id}/authorize` | Authorize a pending referral | CareCoordinator |
| POST | `/community-care/referral-authorizations/{id}/cancel` | Cancel an authorization | CareCoordinator, Veteran |
| POST | `/community-care/referral-authorizations/{id}/extension-requests` | Request more visits and/or days on an episode | ProviderRep, CareCoordinator |
| GET | `/community-care/referral-authorizations/{id}/extension-requests` | List an authorization's extension requests | Any |
| POST | `/community-care/referral-authorizations/{id}/extension-requests/{extId}/decide` | Approve or deny an extension request | CareCoordinator |
| POST | `/community-care/referral-authorizations/{id}/appointments` | Schedule an appointment against an authorization | CareCoordinator, TPAAdministrator |
| GET | `/community-care/referral-authorizations/{id}/appointments` | List an authorization's appointments | Any |
| GET | `/community-care/appointments/{id}` | Get an appointment | Any |
| POST | `/community-care/appointments/{id}/complete` | Mark an appointment completed; auto-creates awaited documentation | ProviderRep |
| POST | `/community-care/appointments/{id}/cancel` | Cancel a scheduled appointment, releasing its visit | CareCoordinator, TPAAdministrator |
| POST | `/community-care/appointments/{id}/documentation` | Submit the episode documentation bundle | ProviderRep |
| GET | `/community-care/appointments/{id}/documentation` | Get the appointment's documentation record (length 0 or 1) | Any |
| POST | `/community-care/medical-documentation/{id}/review` | Accept or reject returned documentation | CareCoordinator |
| POST | `/community-care/claims` | Submit a claim through the administrator | ProviderRep |
| GET | `/community-care/claims/{id}` | Get a claim | Any |
| GET | `/community-care/claims` | List claims, filterable | Any |
| POST | `/community-care/claims/{id}/adjudicate` | Adjudicate a received claim | TPAAdministrator |
| POST | `/community-care/claims/{id}/resubmit` | Resubmit a denied claim with corrected lines | ProviderRep |
| POST | `/community-care/claims/{id}/reverse-payment` | Reverse a paid claim | TPAAdministrator |
| POST | `/community-care/urgent-care-visits` | Record an in-network urgent care visit | Veteran, EligibilityClerk |
| GET | `/community-care/veterans/{id}/urgent-care-visits` | List a veteran's urgent care visits | Any |
| POST | `/community-care/prescription-fill-requests` | Route a community-originated prescription to the system pharmacy | ProviderRep |
| GET | `/community-care/prescription-fill-requests/{id}` | Get a prescription fill request | Any |
| GET | `/community-care/prescription-fill-requests` | List prescription fill requests, filterable | Any |
| POST | `/community-care/prescription-fill-requests/{id}/decide` | Fill or refuse a prescription fill request | SystemPharmacist |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions that raise each error are defined where the corresponding rule lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_REFERRAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_TPA_SUSPENDED` | 409 Conflict |
| `ERR_ASSESSMENT_SUPERSEDED` | 409 Conflict |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SERVICE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PROVIDER_NOT_CREDENTIALED` | 422 Unprocessable Entity |
| `ERR_CONTROLLED_RX_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DOCS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_DOCS_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_UNTIMELY_FILED` | 422 Unprocessable Entity |
| `ERR_SERVICE_DATE_OUTSIDE_EPISODE` | 422 Unprocessable Entity |
| `ERR_AUTH_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SAME_DAY_URGENT_VISIT` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_SLOT_CONFLICT` | 409 Conflict |
| `ERR_EPISODE_OVERLAP` | 409 Conflict |
| `ERR_EXTENSION_CAP` | 409 Conflict |
| `ERR_NO_VISITS_REMAINING` | 409 Conflict |
| `ERR_DAYS_SUPPLY_EXCEEDED` | 409 Conflict |
| `ERR_RESUBMISSION_LIMIT` | 409 Conflict |
| `ERR_SERVICE_CODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROVIDER_SERVICE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_MATCHING_COMPLETED_APPOINTMENT` | 422 Unprocessable Entity |
| `ERR_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_DOCUMENTATION_NOT_PENDING` | 409 Conflict |
| `ERR_DOC_NOT_REVIEWABLE` | 409 Conflict |
