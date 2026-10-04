# Plasma Donation Center API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Source Plasma Donation Center API, the system of record for a network of plasma collection centers operating under federal biologics regulation. The platform orchestrates the full donor lifecycle — from identity-verified intake and medical screening, through on-floor phlebotomy, post-donation observation, unit quarantine, viral-marker look-back, and finally donor compensation with promotional structures and year-end tax reporting.

Two concerns dominate the design. The first is regulatory safety: donors must be screened across four independent sub-records (identity, health history, physical exam, viral markers), a new donor's plasma cannot be released to the manufacturing pipeline until a second donation within a fixed window establishes a baseline, and any reactive viral marker on a subsequent screening triggers an immediate look-back over the donor's prior in-window units. The second is fiscal integrity: compensation is computed from a versioned schedule pinned at check-in, reconciled from a provisional to a final amount at completion, accumulated against a per-calendar-year tax-reporting threshold, and clawed back when a look-back destroys the underlying unit.

The system also manages physical throughput across the three scarce floor resources — screening lanes, donor-floor beds, and post-donation observation chairs — enforcing deterministic slot assignment, frequency caps across all centers in a rolling window, and a minimum inter-donation gap, while giving Compliance Officers the authority to halt an entire center's pipeline with an inspection hold when regulators arrive on-site.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles, spelled exactly: `PlatformAdmin`, `ComplianceOfficer`, `Recorder`, `MedicalScreener`, and `Phlebotomist`. Failure to provide valid headers produces an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400). An attempt to perform an action outside of the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For every role in this system, the `X-User-ID` value is an **opaque operator identifier** that is not tied to any persisted entity. The server records the identifier when a workflow requires attribution — for example, a ScreeningSubRecord captures the Recorder's `X-User-ID` as its `recorded_by_user_id`, and a DeferralRegistryEntry captures the Compliance Officer's `X-User-ID` as its `filed_by_user_id` — but the server does not compare `X-User-ID` to any entity's `id` for ownership purposes. The segregation-of-duties rule on screening clearance is the one place where `X-User-ID` is compared against another stored user id (see §3.3).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Scheduled Actions

The system does not consult wall-clock time. All temporal comparisons — screening expiry, donation no-show, deferral clearance, applicant-window lapse — are evaluated against a server-maintained **logical clock** whose default instant is `2026-09-01T00:00:00Z` before any client sets it. A `PlatformAdmin` can advance the logical clock through a dedicated test-driving capability by supplying a `current_utc` instant; the server responds with the accepted `current_utc`. Every automatic transition whose threshold has passed at the new instant is then fired, in chronological order of the threshold being crossed. The clock never falls back to wall time, even after a restart.

The logical clock is what the system compares against when it evaluates the twenty-four-hour screening expiry, the six-hour donation no-show, the end of a temporary deferral, and the one-hundred-eighty-day applicant window. Every entity timestamp written by the system (`created_at`, `updated_at`, `collected_at`, `released_at`, `destroyed_at`, `payment_issued_on`, `opened_at`, `resolved_at`, `variant_switched_at`, `applicant_window_started_on`, `deferral_ends_on`, `observed_at` checks, and snapshot instants) is stamped from the logical clock, not from the host's clock. Client-supplied datetimes that the server persists (`scheduled_for`, `observed_at`, a deferral entry's `deferral_ends_on`, a schedule's `effective_from`/`effective_to`, and the clock's accepted `current_utc`) are likewise stored and returned in the server's canonical ISO 8601 UTC form with three fractional digits, not echoed verbatim from the request payload.

### 2.5. Common Resource Properties

All primary resources in this API — PlasmaCenter, Donor, ScreeningVisit, ScreeningSubRecord, DonationVisit, AdverseReaction, DonationUnit, CompensationSchedule, CompensationPayment, DeferralRegistryEntry, LookBackCase, and CenterCapacitySnapshot — share a standard set of system-managed fields.

- **`id` (string).** A server-minted UUID. Identifiers carry no type prefix.
- **`created_at` (string).** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted.
- **`updated_at` (string).** An ISO 8601 UTC timestamp with three fractional digits recording the most recent mutation. Any change to a resource — including system-side cascading updates to derived fields — refreshes this value.
- **`version` (integer).** A system-managed integer that starts at 1 and increments on every mutation of the resource, including mutations that originate in side effects rather than in a direct client write.

### 2.6. Monetary Values and Precision

All monetary amounts in the system are carried as **integer cents**; there is no floating-point arithmetic anywhere in the compensation pipeline. Compensation fields such as `base_cents_first_donation`, `base_cents_second_donation`, `base_cents_subsequent_donation`, `promo_bonus_cents`, `base_cents`, `promo_cents`, `net_cents`, and the donor's `ytd_compensation_cents` are all integer cent quantities. Where a calculation would otherwise produce a fraction (specifically, the abort compensation), the multiplication is performed first and the result is then rounded down to the nearest whole cent; the minimum-payout floor is applied after the rounding, in that fixed order.

The tax-reporting threshold that governs the donor's `requires_1099` flag is fixed at 60000 cents (i.e., $600 of compensation within a single calendar year).

### 2.7. Optimistic Concurrency Control

Three write operations in this API require the client to attest to the version of the parent resource it last observed. The request body for each carries a non-optional field naming the expected version of the relevant parent; the server compares the submitted value against the parent's current `version`, and on mismatch the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check is performed **before** any business-rule evaluation, so a stale write is reported as a stale write even when a business rule would also have rejected it.

- **Creating a CompensationSchedule under a center.** The request carries `expected_center_version`, matched against the current `version` of the parent PlasmaCenter. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just transitioned the center (for example onto inspection hold, which legitimately forbids new schedule creation), leaving the current writer's view of the center stale.
- **Placing a center on inspection hold.** The request carries `expected_center_version`, matched against the current `version` of the PlasmaCenter being held. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The prior writer may have just created a new CompensationSchedule (which bumps the center's `version` via the auto-supersede side effect), so the holder's snapshot of the center is stale.
- **Retiring a CompensationSchedule.** The request carries `expected_schedule_version`, matched against the schedule's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The prior writer may have just superseded the schedule by creating a replacement — which legitimately transitions the schedule out of `ACTIVE` — so a stale retire would otherwise double-fire the retirement side effects.

Endpoints not listed above do not take a version field. Note that clearing an inspection hold and decommissioning a center also require `expected_center_version`, enforced by the same `ERR_STALE_VERSION` semantics.

### 2.8. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example a center id followed by a schedule id, or a donor id followed by a screening-visit id — the system resolves each identifier in left-to-right order, returning `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. The same rule applies to foreign keys carried in the request body: a body-supplied reference (such as the `screening_visit_id` on a donation visit) that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404) before any business-rule evaluation proceeds.

### 2.9. Validation Priority

When multiple validation rules could reject the same incoming request, the server evaluates them in the following fixed priority order and reports the **first** rule that fails:

1. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the operation → `ERR_INSUFFICIENT_PERMISSIONS`.
3. Left-to-right resolution of path-template identifiers → `ERR_NOT_FOUND`.
4. Resolution of foreign-key references carried in the request body → `ERR_NOT_FOUND`.
5. Optimistic-concurrency check on `expected_*_version` → `ERR_STALE_VERSION`.
6. State-machine applicability of the requested transition → `ERR_INVALID_STATE`.
7. Center operational status (an inspection hold blocks all visit-pipeline writes at the center; a decommissioned center blocks everything) → `ERR_CENTER_NOT_OPERATIONAL`.
8. Donor eligibility by status → `ERR_DONOR_NOT_ELIGIBLE`.
9. Absence of an active deferral at check-in → `ERR_DONOR_DEFERRED`.
10. Segregation of duties on screening clearance → `ERR_SEGREGATION_OF_DUTIES`.
11. Rolling frequency cap → `ERR_FREQUENCY_LIMIT_EXCEEDED`.
12. Minimum inter-donation gap → `ERR_INTER_DONATION_GAP_VIOLATION`.
13. Screening clearance, ownership, and consumption → `ERR_SCREENING_NOT_CLEARED`.
14. Screening-center match → `ERR_SCREENING_CENTER_MISMATCH`.
15. Bed availability at check-in → `ERR_NO_BED_AVAILABLE`.
16. Observation-chair availability at complete-collection → `ERR_NO_OBSERVATION_CHAIR`.
17. Active compensation schedule covering the check-in instant → `ERR_NO_ACTIVE_COMP_SCHEDULE`.
18. Actual-volume sanity → `ERR_INVALID_ACTUAL_VOLUME`.
19. Observation dwell time → `ERR_OBSERVATION_TOO_EARLY`.
20. Absence of an open look-back at manual release → `ERR_LOOKBACK_OPEN`.
21. Active-deferral uniqueness when filing → `ERR_ACTIVE_DEFERRAL_EXISTS`.
22. Required-field presence, types, enum membership, string-length floors, numeric ranges → `ERR_INVALID_REQUEST`.

The OCC check at step 5 is deliberately early: a client holding a stale version is told so even when a state or business rule further down the list would also have rejected the write. Center status (step 7) precedes donor eligibility (step 8), which in turn precedes every temporal or capacity check, so a mid-flight inspection hold surfaces as `ERR_CENTER_NOT_OPERATIONAL` rather than being masked by a downstream frequency or bed-availability check.

### 2.10. Center Lifecycle and Pipeline Gating

A PlasmaCenter is created with a globally unique `center_code` (for example `CSL-DAL-014`; immutable after create), a `legal_name` on file with the regulator, a two-letter `state_code`, and three positive-integer capacity declarations: `screening_lanes`, `donor_floor_beds`, and `observation_chairs`, each of which must be at least 1. The center's `status` begins at `OPERATIONAL`. A Compliance Officer can move an `OPERATIONAL` center onto `INSPECTION_HOLD`; the hold gates **all** visit-pipeline writes at that center for as long as it is active. Clearing the hold returns the center to `OPERATIONAL`. A `PlatformAdmin` can also move an `OPERATIONAL` center to `DECOMMISSIONED`; that state is terminal. A decommission request is rejected with `ERR_CENTER_NOT_OPERATIONAL` when the center is not currently `OPERATIONAL`, and with `ERR_CENTER_HAS_ACTIVE_VISITS` when any DonationVisit at the center is still in `SCHEDULED`, `IN_PROGRESS`, or `OBSERVATION`, or any ScreeningVisit at the center is still in `SCHEDULED` or `IN_PROGRESS`. Attempting to clear a hold on a center that is not currently on hold is rejected with `ERR_CENTER_NOT_ON_HOLD`.

### 2.11. Capacity Accounting and CenterCapacitySnapshot

Every mutation that changes the operational load on a center — a screening starting, clearing, failing, or expiring; a donation checking in, completing collection, discharging, or aborting; a unit being released; a center being placed on or cleared of inspection hold; a donor qualifying — causes the server to write a **CenterCapacitySnapshot** row capturing the load at that instant. Each snapshot carries `center_id`, the logical-clock `snapshot_at`, four computed counters (`screening_lanes_in_use`, `donor_floor_beds_in_use`, `observation_chairs_in_use`, `pending_releases_count`), and a short `trigger_event` label identifying the transition that produced the snapshot (for example `donation.check_in`, `screening.cleared`, `unit.released`, `center.inspection_hold`, `center.inspection_hold_cleared`, `screening.started`, `screening.failed`, `screening.expired`, `donation.collection_complete`, `donation.completed`, `donation.aborted_reaction`, `donor.qualified`).

The counters are defined precisely. `screening_lanes_in_use` counts ScreeningVisit rows at the center whose `visit_status` is `IN_PROGRESS` with the logical clock inside the half-open interval that begins at `scheduled_for` and ends twenty-four hours later. `donor_floor_beds_in_use` counts DonationVisit rows at the center whose `visit_status` is `IN_PROGRESS`. `observation_chairs_in_use` counts DonationVisit rows at the center whose `visit_status` is `OBSERVATION`. `pending_releases_count` counts DonationUnit rows at the center whose `unit_status` is `QUARANTINED`. Counts are integer tallies with no rounding.

Capacity admission is enforced at two points. Donation check-in requires `donor_floor_beds_in_use` to be **strictly less than** the center's `donor_floor_beds` — equality means the floor is full and the check-in is rejected with `ERR_NO_BED_AVAILABLE`. Complete-collection requires `observation_chairs_in_use` to be strictly less than `observation_chairs`, failing with `ERR_NO_OBSERVATION_CHAIR` at equality. Screening admission is **not** gated on `screening_lanes`: a ScreeningVisit may be created regardless of lane occupancy, and lane assignment is resolved when the first sub-record is written.

The capacity-snapshot list endpoint returns a center's snapshots newest first, ordered by `snapshot_at` descending; because several snapshots can be stamped at the same logical instant, ties are broken by `id` descending. This newest-first ordering is an explicit exception to the ascending `created_at` default of §2.3.

### 2.12. Deterministic Slot Assignment

Beds, observation chairs, and screening lanes are finite pools indexed from 0 up to but not including the declared capacity. The system assigns the **lowest free index** deterministically. For a pool of size N, the occupied set is the indexes currently held by visits in the relevant state; the free set is the complement; the assigned index is the minimum of the free set. When the free set is empty the operation is rejected with the appropriate capacity error (`ERR_NO_BED_AVAILABLE` at check-in, `ERR_NO_OBSERVATION_CHAIR` at complete-collection). Assignment never consults the entity `id`, and there is no tie-breaking on `created_at` because a minimum over a set is total. A bed is freed when its visit leaves `IN_PROGRESS`; an observation chair is freed when its visit leaves `OBSERVATION`.

Screening lanes follow the same lowest-free rule with one refinement: the server assigns the lane whose current-shift intervals do not overlap the new visit, choosing the lowest-index lane among those that qualify, with ties broken by the `created_at` of the conflicting bookings in ascending order. The lane index lands in the range from 0 up to but not including the center's `screening_lanes`.

## 3. Business Logic & Workflows

### 3.1. Center Onboarding and Compensation Schedule Management

A `PlatformAdmin` stands up a center by supplying its `center_code`, `legal_name`, `state_code`, and the three capacity integers `screening_lanes`, `donor_floor_beds`, and `observation_chairs`; the center comes into existence in `OPERATIONAL` status. The same administrator authors the center's compensation economics by creating a **CompensationSchedule** whose payload names the inclusive `effective_from` and the exclusive `effective_to` (which must be strictly later than `effective_from`), three base amounts `base_cents_first_donation`, `base_cents_second_donation`, and `base_cents_subsequent_donation`, and an optional promotional layer consisting of `promo_code`, `promo_bonus_cents`, and `promo_qualifying_donation_count`. When omitted, `promo_code` defaults to null and both `promo_bonus_cents` and `promo_qualifying_donation_count` default to 0; a qualifying count of 0 disables the promo entirely. The request must carry `expected_center_version` matching the center's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

At most one schedule per center is `ACTIVE` at any moment. Creating a new schedule whose `effective_from` precedes the current `ACTIVE` schedule's `effective_to` causes the prior schedule to auto-supersede: its `schedule_status` transitions to `SUPERSEDED`, its `effective_to` is rewritten to the new schedule's `effective_from`, its `version` increments by 1, and the new schedule is created in `ACTIVE` status. The new-schedule creation also bumps the parent center's `version` by 1 as a side effect. A `PlatformAdmin` may also retire an `ACTIVE` schedule by submitting `expected_schedule_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), and attempting to retire a schedule that is not currently `ACTIVE` is rejected with `ERR_SCHEDULE_NOT_ACTIVE`. A successful retirement moves `schedule_status` to `RETIRED` and increments the schedule's `version`. From that instant, future check-ins at the center fail with `ERR_NO_ACTIVE_COMP_SCHEDULE` until a replacement schedule is created. Schedules can be listed under their parent center (optionally filtered by `schedule_status`) and read individually by id.

### 3.2. Donor Registration and Identity Dedupe

A `Recorder` registers a donor by presenting `external_donor_ref`, `legal_first_name`, `legal_last_name`, `date_of_birth` (an ISO 8601 date in `YYYY-MM-DD` form), the most recently measured `weight_kg` in kilograms to one decimal place, and `home_center_id`. The `external_donor_ref` is the government-issued identity reference hashed at intake; it is unique per donor **across all centers**, functioning as the cross-center dedupe key. A registration attempt carrying an `external_donor_ref` that is already on file — regardless of which center originally registered it — is rejected with `ERR_DUPLICATE_DONOR` (HTTP 409). A donor must be at least 18 years old at registration; a `date_of_birth` that violates this is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `home_center_id` designates the donor's primary center and is used for throughput accounting; it does **not** constrain cross-center frequency gating.

A newly registered donor enters the system in `APPLICANT` status, with `lifetime_donation_count` at 0, `ytd_compensation_cents` at 0, `applicant_window_started_on` and `deferral_ends_on` and `deferred_reason_code` and `active_deferral_id` all null, and `requires_1099` at false. Donor reads (by id, or listed with optional `donor_status`, `home_center_id`, and `external_donor_ref` filters) surface the computed `requires_1099` flag alongside the stored fields.

### 3.3. The Screening Visit and Its Four Sub-Records

Before any donation can occur, the donor must clear a screening. A `Recorder` schedules a **ScreeningVisit** by posting `center_id` (which may differ from the donor's `home_center_id`) and `scheduled_for`; the visit begins life in `SCHEDULED`. The screening consists of four sub-records, each of which may be posted at most once per visit. A `Recorder` writes a **ScreeningSubRecord** by supplying its `record_type` — one of `IDENTITY`, `HEALTH_HISTORY`, `PHYSICAL_EXAM`, or `VIRAL_MARKER` — together with a `payload` object whose required members depend on the record type. A second write of the same `record_type` under the same visit is rejected with `ERR_DUPLICATE_SUB_RECORD` (HTTP 409). The server stamps each sub-record with the acting Recorder's `X-User-ID` as its `recorded_by_user_id`.

The required payload members are as follows. A `PHYSICAL_EXAM` payload must include `weight_kg`, `pulse_bpm`, `systolic_mmhg`, `diastolic_mmhg`, `temperature_c`, `hematocrit_pct`, and `total_protein_g_dl`. A `VIRAL_MARKER` payload must include `hiv_ag_ab`, `hbv_surface_ag`, and `hcv_ab`, each with a value of either `NON_REACTIVE` or `REACTIVE`. A `HEALTH_HISTORY` payload must include `risk_flags`, a string array that may be empty. An `IDENTITY` payload's `document_number` must be non-empty to pass.

The server computes each sub-record's `outcome` — `PASS` or `FAIL` — at write time according to per-record-type rules. An `IDENTITY` record passes when `document_number` is non-empty. A `HEALTH_HISTORY` record fails when `risk_flags` is non-empty. A `PHYSICAL_EXAM` record fails when any vital is out of band: `weight_kg` below 50.0 (which surfaces as `ERR_DONOR_UNDERWEIGHT`, HTTP 422), `pulse_bpm` below 50 or above 100, `systolic_mmhg` below 90 or above 180, `diastolic_mmhg` below 50 or above 100, `temperature_c` below 35.5 or above 37.5, `hematocrit_pct` below 38 or above 54, or `total_protein_g_dl` below 6.0 or above 9.0. A `VIRAL_MARKER` record fails when any of `hiv_ag_ab`, `hbv_surface_ag`, or `hcv_ab` is `REACTIVE`.

The first sub-record write under a `SCHEDULED` visit automatically advances the visit to `IN_PROGRESS`, provided the logical clock has not yet passed twenty-four hours past `scheduled_for` (otherwise the visit expires first, see below). That transition writes a capacity snapshot with `trigger_event` set to `screening.started`, and the server assigns the visit's `screening_lane_index` at this instant via the lowest-free-lane rule (§2.12). A physical-exam write has the additional side effect of refreshing the donor's `weight_kg` from the exam's payload value.

Four boolean flags on the visit track completeness — `identity_verified`, `health_history_recorded`, `physical_exam_recorded`, and `viral_marker_recorded` — each initially false and set to true only by the corresponding sub-record write; they are never settable directly.

Clearance is a distinct act, reserved for a `MedicalScreener`. The screener clears an `IN_PROGRESS` visit; a visit that is not `IN_PROGRESS` at clearance time is rejected with `ERR_VISIT_NOT_IN_PROGRESS`. The remaining clearance preconditions are then evaluated in this fixed order: the center must be `OPERATIONAL` (otherwise `ERR_CENTER_NOT_OPERATIONAL`); the donor must be currently `APPLICANT` or `QUALIFIED` (otherwise `ERR_DONOR_NOT_ELIGIBLE`, HTTP 409); every one of the four flags must be true (otherwise `ERR_INCOMPLETE_SCREENING`, HTTP 409); every sub-record's `outcome` must be `PASS` (otherwise `ERR_SCREENING_NOT_PASSABLE`, HTTP 409); and the screener's `X-User-ID` must differ from the `recorded_by_user_id` of **every** sub-record on the visit (a violation surfaces as `ERR_SEGREGATION_OF_DUTIES`, HTTP 403). A successful clearance moves the visit to `CLEARED`, increments its `version`, and writes a snapshot with `trigger_event` `screening.cleared`. This ordering refines §2.9 for the screening-internal checks that §2.9 does not enumerate: a clearance issued against a center on hold surfaces `ERR_CENTER_NOT_OPERATIONAL` before any donor-eligibility concern is consulted, and both fire ahead of the completeness, passability, and segregation-of-duties checks, so a clearance that is simultaneously incomplete and a segregation-of-duties violation reports `ERR_INCOMPLETE_SCREENING` (HTTP 409), not the segregation error.

Any sub-record write whose computed `outcome` is `FAIL` automatically transitions the visit from `IN_PROGRESS` to `FAILED`, with a snapshot `trigger_event` of `screening.failed`. When the failing record is a `VIRAL_MARKER`, the failure has a further consequence described in §3.6: a look-back case is opened for the donor, and every in-window unit the donor has previously produced is swept into a hold.

A screening visit that never completes expires automatically. When the logical clock reaches twenty-four hours past `scheduled_for` and the visit is still `SCHEDULED` or `IN_PROGRESS`, it transitions to `EXPIRED`, with a snapshot `trigger_event` of `screening.expired`. `CLEARED`, `FAILED`, and `EXPIRED` are all terminal states for a screening visit.

### 3.4. Donation Scheduling and Check-In

With a `CLEARED` screening in hand, a `Phlebotomist` schedules a **DonationVisit** under the donor by supplying `center_id`, `screening_visit_id`, and `scheduled_for`. The visit begins life in `SCHEDULED`. Scheduling enforces the screening's integrity: the referenced ScreeningVisit must belong to this donor, must currently be `CLEARED`, and must not have been consumed by any other DonationVisit that is `IN_PROGRESS` or `COMPLETED` — a violation is rejected with `ERR_SCREENING_NOT_CLEARED`. Scheduling also enforces same-center consistency: the referenced screening's `center_id` must equal the donation's `center_id`, with any cross-center reuse rejected as `ERR_SCREENING_CENTER_MISMATCH`. A donor who is `DEFERRED_TEMP` or `DEFERRED_PERM` cannot schedule at all and is rejected under the donor-eligibility rule with `ERR_DONOR_NOT_ELIGIBLE`.

Check-in is the gate where the donation goes live. The Phlebotomist checks in a `SCHEDULED` visit, and the server walks a long precondition chain. A visit that is not `SCHEDULED` is rejected with `ERR_VISIT_NOT_SCHEDULED`. The donor must be `APPLICANT` or `QUALIFIED` — `ERR_DONOR_NOT_ELIGIBLE` otherwise — and must have no `ACTIVE` DeferralRegistryEntry (`ERR_DONOR_DEFERRED` otherwise). The center must be `OPERATIONAL` (`ERR_CENTER_NOT_OPERATIONAL` otherwise). The qualifying screening must still be `CLEARED` and unconsumed (`ERR_SCREENING_NOT_CLEARED`). The center must have a free donor-floor bed at that instant, with `donor_floor_beds_in_use` strictly less than `donor_floor_beds` — equality rejects with `ERR_NO_BED_AVAILABLE`. Finally, an `ACTIVE` CompensationSchedule must cover the check-in instant, or the check-in is rejected with `ERR_NO_ACTIVE_COMP_SCHEDULE`.

Two temporal rules guard the donation at check-in and are worth singling out because they are evaluated against the donor's history **across all centers**, not just the center where check-in occurs.

- **Rolling frequency cap.** The server counts the donor's `COMPLETED` DonationVisits across every center whose collection timestamp falls in the half-open trailing window from seven days before now up to but not including now. The boundary at `now` is exclusive (a completion exactly at `now` cannot yet exist at check-in time), and the boundary at exactly seven days ago is inclusive (a completion exactly one hundred sixty-eight hours in the past does count). When that count is at least 2, the check-in is rejected with `ERR_FREQUENCY_LIMIT_EXCEEDED`. This is a rolling window rather than a calendar-week bucket: a donation six days and twenty-three hours ago still counts; a donation seven days and one second ago does not.
- **Minimum inter-donation gap.** The server finds the donor's most recent `COMPLETED` donation across all centers (latest `collected_at`, tie-broken by `created_at` ascending). When fewer than 48 hours have elapsed between that completion and the present instant, the check-in is rejected with `ERR_INTER_DONATION_GAP_VIOLATION`. The boundary is inclusive on the pass side: a gap of exactly 48 hours passes; a gap one second shorter fails. A donor with no prior completions passes trivially.

A successful check-in has a cluster of side effects. The visit transitions to `IN_PROGRESS`; `bed_index` is assigned via the lowest-free-bed rule; the donor's `weight_kg` is refreshed from the most recent `PHYSICAL_EXAM` sub-record on the qualifying screening; and `programmed_volume_ml` is computed once and frozen. The volume rule is a four-tier weight band. A donor weighing less than 50.0 kilograms would be rejected (the physical exam fails at `ERR_DONOR_UNDERWEIGHT`, so this branch is unreachable at check-in). From 50.0 up to but not including 68.0 kilograms the programmed volume is 625 mL. From 68.0 up to but not including 79.0 kilograms it is 690 mL. From 79.0 up to but not including 110.0 kilograms it is 825 mL. At 110.0 kilograms and above it is 880 mL. Boundaries are strictly greater-or-equal on the lower edge and strictly less-than on the upper edge: a donor weighing exactly 68.0 kg lands in the 690-mL band; exactly 79.0 kg lands in 825; exactly 110.0 kg lands in 880. The value is an integer number of milliliters and requires no rounding. Once written, `programmed_volume_ml` is **frozen** for the life of the visit: a subsequent physical exam that updates `weight_kg` does not retroactively alter the visit's programmed volume. This is the snapshot variant of the volume rule; a distinct hypothetical variant — computed on the fly from the donor's current `weight_kg` whenever a client asks what a new visit would program — legitimately diverges from the snapshot variant when weight has moved since the older visit's check-in.

Check-in also creates the visit's **CompensationPayment** and stores its id on the visit as `compensation_payment_id`. The payment is created in the `PROVISIONAL` variant with `payment_status` `PROVISIONAL`, pinned by `schedule_id` to the `ACTIVE` schedule at check-in (the version of that schedule at pinning time governs all subsequent recomputation). If no `ACTIVE` schedule covers the check-in instant, the check-in is rejected with `ERR_NO_ACTIVE_COMP_SCHEDULE` and no payment is created. A snapshot with `trigger_event` `donation.check_in` is written.

### 3.5. Collection, Observation, and Discharge

Once on the floor, the Phlebotomist reports collection completion by supplying `actual_volume_ml`, the actual collected milliliters reported by the device. The visit must be `IN_PROGRESS` (`ERR_VISIT_NOT_IN_PROGRESS` otherwise). The reported volume must be strictly greater than 0 and at most `programmed_volume_ml`; anything outside that range is rejected with `ERR_INVALID_ACTUAL_VOLUME` (HTTP 422). The center must have a free observation chair — `observation_chairs_in_use` strictly less than `observation_chairs` — or the call is rejected with `ERR_NO_OBSERVATION_CHAIR`. A successful complete-collection moves the visit to `OBSERVATION`, frees the bed back to the floor pool, assigns `observation_chair_index` via the lowest-free-chair rule, stamps `actual_volume_ml` on the visit, and writes a snapshot with `trigger_event` `donation.collection_complete`.

After observation the Phlebotomist discharges the donor. The visit must be `OBSERVATION` (`ERR_VISIT_NOT_OBSERVABLE` otherwise). Discharge is gated on dwell time: the logical clock must be at least fifteen minutes past the instant the visit entered `OBSERVATION`, failing which the call is rejected with `ERR_OBSERVATION_TOO_EARLY`. A successful discharge moves the visit to `COMPLETED`, frees the observation chair, and fires a cascade of side effects that the next three subsections unpack: the unit is created and quarantined, compensation is finalized, the donor's counters and status are updated, and a snapshot with `trigger_event` `donation.completed` is written.

A visit that was never checked in auto-fires `NO_SHOW` when the logical clock passes six hours past `scheduled_for` while the visit is still `SCHEDULED`. The same `NO_SHOW` terminal state is reached by cascade when the donor is deferred or the center is placed on inspection hold; in those cases `scheduled_for` is left unchanged. When a visit transitions to `NO_SHOW` its CompensationPayment (if any) is voided: `payment_status` stays `PROVISIONAL`, the variant is left `PROVISIONAL`, and the row is excluded from year-to-date accumulation; the payment row itself remains in the system for audit.

### 3.6. Unit Creation, Quarantine, and the Viral-Marker Look-Back

Discharge creates exactly one **DonationUnit** for the completed visit, with `volume_ml` equal to the visit's `actual_volume_ml`, `collected_at` stamped from the logical clock, the parent visit's id recorded as `donation_visit_id`, and `donor_id` and `center_id` denormalized onto the row, and `unit_status` `QUARANTINED`. The unit stays in quarantine until the donor is qualified.

A unit can leave quarantine in three directions.

- **Release.** When the donor is `QUALIFIED` at release time and there is no `OPEN` or `UNITS_QUARANTINED` LookBackCase for the donor, a Compliance Officer may release the unit, transitioning it to `RELEASED` and stamping `released_at`. A unit that is not `QUARANTINED` rejects with `ERR_UNIT_NOT_QUARANTINED`; a donor who is not `QUALIFIED` rejects with `ERR_DONOR_NOT_QUALIFIED`; an open look-back rejects with `ERR_LOOKBACK_OPEN`. Release also happens automatically as part of the applicant-to-qualified cascade described in §3.7. A snapshot with `trigger_event` `unit.released` is written.
- **Look-back hold.** When a viral-marker sub-record on a subsequent screening comes back `REACTIVE`, the failing visit moves to `FAILED` and a **LookBackCase** is opened for the donor with `case_status` `OPEN`, an `opened_at` stamp from the logical clock, a fixed `lookback_window_days` of 180, and references to the `triggering_screening_sub_record_id` (the failing viral-marker record) and the `triggering_donation_visit_id` (the donation visit performed under that screening — the visit whose `screening_visit_id` equals the triggering record's screening visit; that triggering visit need not itself be `COMPLETED`, because the reactive marker can surface on the screening of a still-`SCHEDULED` visit). Every DonationUnit the donor has produced whose `collected_at` falls within one hundred eighty days of the reactive instant is moved to `LOOKBACK_HOLD`, whether it was `QUARANTINED` or already `RELEASED`; for a previously released unit the original `released_at` is preserved for audit. When every in-window unit has been moved, the case transitions `OPEN → UNITS_QUARANTINED`; in the degenerate case where zero units fall in the window, the case immediately auto-resolves to `RESOLVED_DESTROYED` with `resolved_at` equal to `opened_at` — a no-op resolution recorded for audit.
- **Destruction on donor permanent deferral.** When the donor becomes `DEFERRED_PERM`, every `QUARANTINED` and `LOOKBACK_HOLD` unit the donor has produced is transitioned to `DESTROYED` with `destruction_reason` `DONOR_PERMANENT_DEFERRAL`; the timestamp `destroyed_at` is stamped on each. A parent LookBackCase whose held units are now all `DESTROYED` transitions to `RESOLVED_DESTROYED`.

A Compliance Officer resolves an `UNITS_QUARANTINED` case by supplying a `resolution` (either `DESTROY` or `RELEASE`) together with a `resolution_rationale` of at least 20 characters — anything shorter is rejected with `ERR_INVALID_REQUEST`. A case that is not `UNITS_QUARANTINED` rejects with `ERR_LOOKBACK_NOT_READY`. Under `DESTROY`, every held unit transitions `LOOKBACK_HOLD → DESTROYED` with `destruction_reason` `REACTIVE_LOOKBACK` and `destroyed_at` stamped; each destroyed unit's CompensationPayment, if it was `FINALIZED`, transitions to `CLAWED_BACK` and the donor's `ytd_compensation_cents` is debited by that payment's `net_cents`. When the last held unit on the case is destroyed, `case_status` becomes `RESOLVED_DESTROYED` with `resolved_at` stamped. Under `RELEASE`, every held unit transitions `LOOKBACK_HOLD → RELEASED` with `released_at` stamped — this is the false-positive retest path — and the donor must be `QUALIFIED` at resolution time (`ERR_DONOR_NOT_QUALIFIED` otherwise). When the last held unit is released, the case transitions to `RESOLVED_RELEASED` with `resolved_at` stamped. `RESOLVED_DESTROYED` and `RESOLVED_RELEASED` are both terminal.

A destroyed unit's history is preserved: `destroyed_at` and `destruction_reason` (one of `DONOR_PERMANENT_DEFERRAL`, `REACTIVE_LOOKBACK`, or `EXPIRED_HOLD`) are recorded on the unit, and the row remains queryable via the unit list and read endpoints.

### 3.7. Donor Qualification and the Applicant Window

A new donor's first completed donation does not by itself release any plasma to manufacturing. The qualification rule looks at the donor's first two completions.

When a donation visit completes, the donor's `lifetime_donation_count` increments by one. The very first completion also stamps `applicant_window_started_on` with the completion timestamp — this anchors the applicant window. If, after this completion, the donor is still `APPLICANT` **and** the donor's lifetime completion count is at least 2 **and** the elapsed time between `applicant_window_started_on` and the current instant is at most 180 days (that is, 180 times 24 hours), the donor is promoted to `QUALIFIED`. The boundary is inclusive: a second completion at exactly 180 days after the first passes; one second later fails. The promotion releases every `QUARANTINED` unit the donor has produced whose triggering visit's screening had no reactive viral marker — each such unit moves to `RELEASED` with `released_at` stamped — and writes a capacity snapshot on the donor's `home_center_id` with `trigger_event` `donor.qualified`.

If instead the second completion arrives more than 180 days after the first, the donor **remains** `APPLICANT`. The applicant window has lapsed. On the completion that outlasts the window, the donor's `applicant_window_started_on` is **reset** to the current completion's timestamp — the donor starts a fresh applicant window, and the donation history prior to this reset is ignored for the purpose of qualification (it is not erased from `lifetime_donation_count`, which is monotonically increasing for audit). The qualification check then compares the next completion against the reset timestamp. A donor whose window lapses repeatedly can cycle through `APPLICANT` status indefinitely.

### 3.8. Compensation Computation

The CompensationPayment attached to a visit is computed in two variants and reconciled at completion.

**The base component.** Let `ordinal` be the count of the donor's `COMPLETED` DonationVisits — across all centers — in the same calendar month as this visit's check-in date. In the `PROVISIONAL` variant the ordinal counts only prior completions (this visit, not yet completed, is excluded). In the `FINAL` variant the ordinal counts this visit as completed; the ordinal is computed after incrementing the lifetime count, so the final ordinal of the just-completed visit equals the number of prior completions in the month. The provisional and final ordinals therefore match for the same visit — but they can diverge if another visit for the same donor completes in between this visit's check-in and completion, in which case the final base can be higher than the provisional base. The base amount is then selected from the pinned schedule: ordinal 0 yields `base_cents_first_donation`, ordinal 1 yields `base_cents_second_donation`, ordinal 2 or higher yields `base_cents_subsequent_donation`. The chosen amount is stored as `base_cents`.

**The promo component.** When the pinned schedule's `promo_code` is null or its `promo_qualifying_donation_count` is 0, `promo_cents` is 0 in both variants. Otherwise, let `window_completed` be the count of the donor's `COMPLETED` DonationVisits whose `collected_at` falls in the half-open interval from the schedule's `effective_from` up to but not including `effective_to`. In the `PROVISIONAL` variant, `promo_cents` equals `promo_bonus_cents` when the count of in-window completions excluding this visit, plus one for this visit, is at least `promo_qualifying_donation_count` **and** no other CompensationPayment for this donor on the same `schedule_id` is already `FINALIZED` with a positive `promo_cents`. In the `FINAL` variant, `promo_cents` equals `promo_bonus_cents` when the in-window completed count including this visit is at least `promo_qualifying_donation_count` and the same no-prior-finalized-promo clause holds. The provisional variant is deliberately optimistic — it assumes the qualifying count will be reached — while the final variant is pessimistic and requires the actual count. The no-prior-finalized clause makes the promo a once-per-schedule-per-donor payout. Because the final variant can yield 0 even when the provisional variant was positive, the delta is absorbed at variant switch: the donor's `ytd_compensation_cents` accumulates only the final `net_cents`.

**Net and reconciliation.** In both variants `net_cents` is the sum of `base_cents` and `promo_cents`. When the visit reaches `COMPLETED`, the payment recomputes in the `FINAL` variant: `variant` transitions `PROVISIONAL → FINAL`, `variant_switched_at` is stamped from the logical clock, `base_cents` and `promo_cents` are recomputed, `net_cents` is finalized, `payment_status` moves to `FINALIZED`, `payment_issued_on` is stamped from the logical clock, and the donor's `ytd_compensation_cents` is increased by the final `net_cents`.

**Year-to-date accumulator and the 1099 flag.** The donor's `ytd_compensation_cents` is recomputed on every finalize and every claw-back as the sum of `net_cents` over all CompensationPayment rows for this donor whose `payment_status` is `FINALIZED` and whose `payment_issued_on` falls within the calendar year of the logical clock. The accumulator is year-scoped: payments issued in a prior calendar year do not roll forward. After every accumulator update the `requires_1099` flag is recomputed: it is true when the accumulator has reached 60000 cents ($600). The flag is **sticky downward** — once true it remains true even if a later claw-back pulls the year-to-date total below the threshold, because a 1099 obligation incurred mid-year is not voided by a later claw-back.

**Claw-back.** When a look-back destroys a unit whose payment was `FINALIZED`, that payment transitions to `CLAWED_BACK` and the donor's `ytd_compensation_cents` is debited by the payment's `net_cents`. The row remains queryable for audit.

**Abort compensation.** When a donation aborts for a reaction (§3.9), the payment is recomputed on a fractional-completion basis. If `actual_volume_ml` is null — meaning the reaction occurred while the visit was still `IN_PROGRESS` before any collection was recorded — the abort amount is 0. Otherwise, the fraction collected is `actual_volume_ml` divided by `programmed_volume_ml`, and the abort amount is the final-variant `base_cents` (computed under the final-ordinal rule) multiplied by that fraction and rounded down to a whole cent. When the result is positive but below 500 cents ($5), it is raised to the 500-cent minimum floor. The rounding order is fixed: multiply first, then floor, then apply the minimum. `promo_cents` is always 0 for an aborted visit, and `net_cents` equals the abort amount; the abort amount is stored in the `base_cents` field for clarity. The payment's `payment_status` transitions to `FINALIZED` with that net, and `variant` transitions to `FINAL`.

### 3.9. Adverse Reactions and Auto-Deferral

A Phlebotomist who observes a reaction records it by supplying `severity` (`MILD`, `MODERATE`, or `SEVERE`), a `reaction_code` from the controlled vocabulary (for example `VASOVAGAL`, `HEMATOMA`, `CITRATE`, `ARTERIAL_PUNCTURE`, `OTHER`), an `observed_at` timestamp that must not be later than the logical clock now, and free-text `notes` of at least 10 characters. The visit must be `IN_PROGRESS` or `OBSERVATION`; any other state rejects with `ERR_VISIT_NOT_ABORTABLE`.

The reaction has a uniform set of side effects regardless of which floor state it interrupts. An AdverseReaction row is created. The visit transitions to `ABORTED_REACTION`. The bed is freed (when the reaction occurred in `IN_PROGRESS`) and the observation chair is freed (when it occurred in `OBSERVATION`). Compensation is recomputed per the abort rule in §3.8. A snapshot with `trigger_event` `donation.aborted_reaction` is written.

Unit creation depends on how far the visit had progressed. When `actual_volume_ml` was already recorded and is greater than 0 — which is always the case for a reaction in `OBSERVATION`, because complete-collection has already run — a DonationUnit is created in `QUARANTINED` status with `volume_ml` set to `actual_volume_ml`. When `actual_volume_ml` is null (a reaction in `IN_PROGRESS` before collection completed), no unit is created.

A `SEVERE` reaction has an additional consequence. The system auto-files a DeferralRegistryEntry on the donor with `deferral_type` `TEMPORARY`, `deferral_ends_on` set 7 days after the current instant, and `reason_code` `ADVERSE_REACTION_SEVERE`. The donor transitions to `DEFERRED_TEMP` with the standard side effects enumerated in §3.10.

### 3.10. Deferral Registry and Compliance Interventions

A Compliance Officer files a deferral on a donor by supplying a `reason_code` from the controlled vocabulary (for example `REACTIVE_HIV`, `REACTIVE_HBV`, `REACTIVE_HCV`, `LOW_HEMATOCRIT`, `TRAVEL_MALARIA`, `ADVERSE_REACTION_SEVERE`, `MEDICAL_HOLD`), a `deferral_type` of either `TEMPORARY` or `PERMANENT`, and — when the type is `TEMPORARY` — a `deferral_ends_on` that must be strictly later than the logical-clock `created_at` of the entry. The donor must currently be `APPLICANT` or `QUALIFIED`; a donor already deferred is rejected with `ERR_DONOR_NOT_DEFERRABLE`. Filing also enforces uniqueness: when an `ACTIVE` DeferralRegistryEntry already exists for this donor, the new filing is rejected with `ERR_ACTIVE_DEFERRAL_EXISTS`. The entry is created in `ACTIVE` registry status, with the filing center's id recorded as `source_center_id` and the acting officer's `X-User-ID` recorded as `filed_by_user_id`.

A `TEMPORARY` filing drives the donor to `DEFERRED_TEMP`; a `PERMANENT` filing drives the donor to `DEFERRED_PERM`. In both cases the donor's `active_deferral_id` is set to the new entry's id, `deferred_reason_code` is set to the entry's `reason_code`, and the donor's `version` increments. For a temporary deferral the donor's `deferral_ends_on` is set to the entry's `deferral_ends_on`; for a permanent deferral `deferral_ends_on` is set to null. Every DonationVisit the donor has in `SCHEDULED` status is moved to `NO_SHOW`. A permanent deferral has two further cascades: every `QUARANTINED` unit the donor has produced is destroyed with `destruction_reason` `DONOR_PERMANENT_DEFERRAL`, and every `LOOKBACK_HOLD` unit is likewise destroyed with the same reason — the latter cascade resolving the parent LookBackCase to `RESOLVED_DESTROYED` when its held units are now all destroyed.

A temporary deferral clears automatically. When the logical clock reaches `deferral_ends_on` and the entry is still `ACTIVE`, the entry's `registry_status` transitions to `CLEARED`, the donor's `active_deferral_id`, `deferral_ends_on`, and `deferred_reason_code` are all set to null, and the donor's `version` increments. The donor's status is recomputed from donation history: a donor with `lifetime_donation_count` 0 returns to `APPLICANT`; a donor with at least one lifetime completion returns to `QUALIFIED`.

A Compliance Officer can override an `ACTIVE` deferral by supplying an `override_rationale` of at least 20 characters — anything shorter is rejected with `ERR_INVALID_REQUEST`. A successful override moves the entry's `registry_status` to `OVERRIDDEN`, clears the donor's `active_deferral_id` to null, and recomputes the donor's status from donation history by the same rule: `APPLICANT` when `lifetime_donation_count` is 0, otherwise `QUALIFIED`.

### 3.11. Inspection Holds and Decommission

When a regulator arrives on-site, a Compliance Officer places the center on hold by submitting `expected_center_version` and a `reason`. The center must currently be `OPERATIONAL`; any other status is rejected with `ERR_CENTER_NOT_OPERATIONAL`. A stale `expected_center_version` is rejected with `ERR_STALE_VERSION`. A successful hold transitions the center to `INSPECTION_HOLD`, increments its `version` by 1, and cascades the pipeline: every DonationVisit at the center still in `SCHEDULED` is moved to `NO_SHOW` (its `scheduled_for` is left unchanged, and its CompensationPayment if any stays `PROVISIONAL`), and every ScreeningVisit at the center still in `SCHEDULED` is moved to `EXPIRED`. A snapshot is written with `trigger_event` `center.inspection_hold`. For as long as the hold is active, every visit-pipeline write at the center — sub-record posting, screening clearance, donation scheduling, check-in, complete-collection, discharge, adverse-reaction recording, schedule creation — is rejected with `ERR_CENTER_NOT_OPERATIONAL`.

Clearing the hold requires `expected_center_version` matching the center's current `version`. A center that is not on hold rejects with `ERR_CENTER_NOT_ON_HOLD`. A successful clear returns the center to `OPERATIONAL`, increments its `version`, and writes a snapshot with `trigger_event` `center.inspection_hold_cleared`.

A `PlatformAdmin` decommissions an `OPERATIONAL` center by supplying `expected_center_version`. The request is rejected with `ERR_CENTER_NOT_OPERATIONAL` when the center is not currently `OPERATIONAL`, with `ERR_STALE_VERSION` when the version is stale, and with `ERR_CENTER_HAS_ACTIVE_VISITS` when any DonationVisit at the center is `SCHEDULED`, `IN_PROGRESS`, or `OBSERVATION`, or any ScreeningVisit at the center is `SCHEDULED` or `IN_PROGRESS`. A successful decommission transitions the center to `DECOMMISSIONED` (a terminal state), increments its `version`, and destroys every `QUARANTINED` unit at the center with `destruction_reason` `EXPIRED_HOLD`. From that point every write against the center is rejected.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (for example a PlasmaCenter or a Donor) or add new, distinct resources to a collection (for example a ScreeningSubRecord under a ScreeningVisit, or an AdverseReaction under a DonationVisit) return a `201 Created` status code. Operations that modify an existing resource — state transitions such as check-in, complete-collection, discharge, clearance, hold, release, resolve, override, retire — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires pending automatic transitions in chronological order | PlatformAdmin |
| POST | `/plasma-centers` | Create a plasma collection center | PlatformAdmin |
| GET | `/plasma-centers` | List centers (optional `state_code` filter) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist, Recorder |
| GET | `/plasma-centers/{centerId}` | Get a center | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist, Recorder |
| POST | `/plasma-centers/{centerId}/inspection-holds` | Place the center on INSPECTION_HOLD; cascades scheduled visits to NO_SHOW / EXPIRED | ComplianceOfficer |
| POST | `/plasma-centers/{centerId}/inspection-holds/clear` | Clear an INSPECTION_HOLD | ComplianceOfficer |
| POST | `/plasma-centers/{centerId}/decommission` | Decommission a center (terminal) | PlatformAdmin |
| GET | `/plasma-centers/{centerId}/capacity-snapshots` | List capacity snapshots for a center, newest first | PlatformAdmin, ComplianceOfficer |
| POST | `/plasma-centers/{centerId}/compensation-schedules` | Create a compensation schedule; auto-supersedes any overlapping ACTIVE schedule | PlatformAdmin |
| GET | `/plasma-centers/{centerId}/compensation-schedules` | List schedules for a center (optional `schedule_status` filter) | PlatformAdmin, ComplianceOfficer |
| GET | `/compensation-schedules/{scheduleId}` | Get a schedule | PlatformAdmin, ComplianceOfficer |
| POST | `/compensation-schedules/{scheduleId}/retire` | Retire an ACTIVE schedule | PlatformAdmin |
| POST | `/donors` | Register a new donor (globally deduped by `external_donor_ref`) | Recorder |
| GET | `/donors` | List donors (optional `donor_status`, `home_center_id`, `external_donor_ref` filters) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist, Recorder |
| GET | `/donors/{donorId}` | Get a donor (includes computed `requires_1099` flag) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist, Recorder |
| POST | `/donors/{donorId}/deferrals` | File a deferral registry entry | ComplianceOfficer |
| GET | `/donors/{donorId}/deferrals` | List deferral entries for a donor (optional `registry_status` filter) | PlatformAdmin, ComplianceOfficer, MedicalScreener |
| POST | `/deferral-registry-entries/{entryId}/override` | Override an ACTIVE deferral (requires `override_rationale` ≥ 20 chars) | ComplianceOfficer |
| POST | `/donors/{donorId}/screening-visits` | Schedule a screening visit | Recorder |
| GET | `/donors/{donorId}/screening-visits` | List screening visits for a donor (optional `visit_status` filter) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Recorder |
| GET | `/screening-visits/{visitId}` | Get a screening visit | PlatformAdmin, ComplianceOfficer, MedicalScreener, Recorder |
| POST | `/screening-visits/{visitId}/sub-records` | Record one of the four screening sub-records | Recorder |
| GET | `/screening-visits/{visitId}/sub-records` | List sub-records for a screening visit (optional `record_type` filter) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Recorder |
| POST | `/screening-visits/{visitId}/clear` | Clear a screening visit (requires four PASS sub-records and segregation of duties) | MedicalScreener |
| POST | `/donors/{donorId}/donation-visits` | Schedule a donation visit against a cleared screening | Phlebotomist |
| GET | `/donors/{donorId}/donation-visits` | List donation visits for a donor (optional `visit_status` filter) | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist |
| GET | `/donation-visits/{visitId}` | Get a donation visit | PlatformAdmin, ComplianceOfficer, MedicalScreener, Phlebotomist |
| POST | `/donation-visits/{visitId}/check-in` | Check in for donation; assigns bed, computes programmed volume, creates PROVISIONAL payment | Phlebotomist |
| POST | `/donation-visits/{visitId}/complete-collection` | Mark collection complete; frees bed, assigns observation chair | Phlebotomist |
| POST | `/donation-visits/{visitId}/discharge` | Discharge from observation; creates DonationUnit, finalizes compensation, may qualify donor | Phlebotomist |
| POST | `/donation-visits/{visitId}/adverse-reactions` | Record an adverse reaction; aborts the visit | Phlebotomist |
| GET | `/donation-visits/{visitId}/adverse-reactions` | List adverse reactions for a visit | PlatformAdmin, ComplianceOfficer, MedicalScreener |
| GET | `/donation-units` | List donation units (optional `donor_id`, `center_id`, `unit_status` filters) | PlatformAdmin, ComplianceOfficer, MedicalScreener |
| GET | `/donation-units/{unitId}` | Get a donation unit | PlatformAdmin, ComplianceOfficer, MedicalScreener |
| POST | `/donation-units/{unitId}/release` | Manually release a QUARANTINED unit | ComplianceOfficer |
| GET | `/lookback-cases` | List look-back cases (optional `donor_id`, `case_status` filters) | PlatformAdmin, ComplianceOfficer |
| GET | `/lookback-cases/{caseId}` | Get a look-back case | PlatformAdmin, ComplianceOfficer |
| POST | `/lookback-cases/{caseId}/resolve` | Resolve a look-back case (DESTROY or RELEASE all held units) | ComplianceOfficer |
| GET | `/donation-visits/{visitId}/compensation-payment` | Get the compensation payment for a visit (array of 0 or 1) | PlatformAdmin, ComplianceOfficer, Phlebotomist |
| GET | `/donors/{donorId}/compensation-payments` | List compensation payments for a donor (optional `payment_status`, `schedule_id` filters) | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CENTER_NOT_OPERATIONAL` | 409 |
| `ERR_CENTER_NOT_ON_HOLD` | 409 |
| `ERR_CENTER_HAS_ACTIVE_VISITS` | 409 |
| `ERR_DONOR_NOT_ELIGIBLE` | 409 |
| `ERR_DONOR_NOT_DEFERRABLE` | 409 |
| `ERR_DONOR_DEFERRED` | 409 |
| `ERR_DONOR_NOT_QUALIFIED` | 409 |
| `ERR_DONOR_UNDERWEIGHT` | 422 |
| `ERR_ACTIVE_DEFERRAL_EXISTS` | 409 |
| `ERR_DUPLICATE_DONOR` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INCOMPLETE_SCREENING` | 409 |
| `ERR_SCREENING_NOT_PASSABLE` | 409 |
| `ERR_SCREENING_NOT_CLEARED` | 409 |
| `ERR_SCREENING_CENTER_MISMATCH` | 409 |
| `ERR_DUPLICATE_SUB_RECORD` | 409 |
| `ERR_VISIT_NOT_IN_PROGRESS` | 409 |
| `ERR_VISIT_NOT_SCHEDULED` | 409 |
| `ERR_VISIT_NOT_OBSERVABLE` | 409 |
| `ERR_VISIT_NOT_ABORTABLE` | 409 |
| `ERR_FREQUENCY_LIMIT_EXCEEDED` | 409 |
| `ERR_INTER_DONATION_GAP_VIOLATION` | 409 |
| `ERR_NO_BED_AVAILABLE` | 409 |
| `ERR_NO_OBSERVATION_CHAIR` | 409 |
| `ERR_OBSERVATION_TOO_EARLY` | 409 |
| `ERR_INVALID_ACTUAL_VOLUME` | 422 |
| `ERR_NO_ACTIVE_COMP_SCHEDULE` | 409 |
| `ERR_SCHEDULE_NOT_ACTIVE` | 409 |
| `ERR_UNIT_NOT_QUARANTINED` | 409 |
| `ERR_LOOKBACK_OPEN` | 409 |
| `ERR_LOOKBACK_NOT_READY` | 409 |
