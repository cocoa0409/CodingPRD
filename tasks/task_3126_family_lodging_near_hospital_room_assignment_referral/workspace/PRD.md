# Family Lodging Hospital Referral API — Product Requirements Document

## 1. Introduction

This document specifies the Family Lodging Hospital Referral API, the operational backbone for a network of charity lodging houses serving families whose children are receiving treatment at nearby hospitals (a Ronald McDonald House Charities-style program). The system verifies hospital referrals, scores and ranks waitlisted families, allocates a finite pool of rooms under a transparent prioritization policy, and tracks each family's stay from check-in through checkout. Because rooms are scarce, the system maintains an optimistic-concurrency contract on the two resources most contended by concurrent writers — the Family record and the StayRequest — so that an operator acting on a stale view is refused rather than allowed to silently overwrite newer state.

Beyond room allocation, the API also governs the day-to-day operation of each house: guest registration with a same-day illness screening gate, a volunteer meal program with food-safety certification enforcement, suggested (never mandatory) family contribution requests, care spaces operated inside partner hospitals, in-kind donation intake and distribution, and two administrative sweep checkpoints that expire stale offers, age out referrals, promote the waitlist, and flag long-running stays for transition planning. Every rule in this document is normative; nothing here is advisory.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request carries two mandatory HTTP headers: `X-User-ID` identifies the acting principal and `X-User-Role` names the operational capacity in which they act. The system recognizes five roles — `ProgramAdmin`, `HouseManager`, `HospitalReferrer`, `FamilyContact`, and `VolunteerCoordinator` — spelled exactly as written here. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted for the target endpoint, or whose entity-backed ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity is bound differently per role. When `X-User-Role` is `FamilyContact`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's foreign-key field (for example `family_id` on a `StayRequest`, `CareSpaceBooking`, or the parent `Stay` of a `ContributionRequest`) to `X-User-ID`. When `X-User-Role` is `HospitalReferrer`, `X-User-ID` is the `id` of the acting `Hospital`; a `HospitalReferrer` issuing a `Referral` must pass a `hospital_id` equal to their own `X-User-ID`, and revoking a referral similarly requires the referral's `hospital_id` to match the caller's `X-User-ID`. When `X-User-Role` is `ProgramAdmin`, `HouseManager`, or `VolunteerCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `created_by_user_id` or `verified_by_user_id` on a `Referral`) but does not compare it to any entity's `id`.

Segregation of duties is enforced on referral verification: the `X-User-ID` verifying a referral must differ from the referral's recorded `created_by_user_id`. A verifier who created the referral is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Endpoints that return lists of resources are paginated via two query parameters. `limit` controls the maximum number of items returned and defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls the number of items skipped and defaults to 0. Unless otherwise specified, list endpoints sort resources by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — `Hospital`, `House`, `Room`, `Family`, `Referral`, `StayRequest`, `Stay`, `GuestRegistration`, `ContributionRequest`, `VolunteerGroup`, `MealShift`, `CareSpace`, `CareSpaceBooking`, and `InKindDonation` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits marking when the resource was created. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits marking the most recent modification. `version` is an integer that starts at 1 and increments by one on every mutation. The single exception is `IllnessScreening`, which is immutable after recording and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from screening payloads.

All date and datetime reasoning in the system runs against a logical clock, not the host's wall clock. Before any client call adjusts it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and echoes the resulting `current_utc` value; once advanced, the clock never falls back to wall-clock time, and any date-derived or time-derived field evaluates against the new clock on its next access.

### 2.5. Validation Pipeline Ordering

Every request flows through a fixed validation pipeline, and the ordering is contract-bearing because a request can fail more than one check and the error the caller receives must be the highest-priority failure. The categories are evaluated in this exact order. First, request well-formedness: the body must contain all required fields, no unknown fields, and every field's type and enum value must be valid, otherwise the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Second, authentication: the headers described in §2.1 must be present and the role recognized, otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Third, authorization: the role must be permitted for the endpoint, entity-backed ownership must hold, and segregation-of-duties on referral verification must be respected, otherwise `ERR_FORBIDDEN` (HTTP 403) — except the SoD failure, which surfaces as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Fourth, existence: every identifier appearing in the path is validated left to right, and the first one that does not resolve yields `ERR_NOT_FOUND` (HTTP 404); at the same stage, any `expected_*_version` field on the body is compared to the parent's current `version`, and a mismatch yields `ERR_STALE_VERSION` (HTTP 412). Fifth, state-machine eligibility: the target resource must be in a from-state that permits the requested transition, with `ERR_INVALID_STATE` (HTTP 409) as the generic rejection — though stay-activity gating surfaces as `ERR_STAY_NOT_ACTIVE` (HTTP 409), an expired offer as `ERR_OFFER_EXPIRED` (HTTP 409), an unverified referral as `ERR_REFERRAL_NOT_VERIFIED` (HTTP 409), and a depleted donation as `ERR_DONATION_DEPLETED` (HTTP 409). Sixth, business safety: same-day PASS illness screening for guest registration and food-safety gates for the meal program, surfacing as `ERR_SCREENING_NOT_CLEARED`, `ERR_FOOD_SAFETY_CERT_REQUIRED`, `ERR_FOOD_SAFETY_CERT_EXPIRED`, or `ERR_FOOD_SAFETY_ATTESTATION_REQUIRED` (all HTTP 422). Seventh, business constraints: distance eligibility, room occupancy limits, care-space capacity, room occupancy and reservation conflicts, care-space buffered overlap, one non-terminal referral per (family, hospital), one meal shift per (house, date, meal type), and the extension-count cap — surfacing as `ERR_DISTANCE_INELIGIBLE`, `ERR_GUEST_LIMIT_EXCEEDED`, `ERR_CAPACITY_EXCEEDED`, `ERR_ROOM_NOT_AVAILABLE`, `ERR_CARE_SPACE_CONFLICT`, `ERR_DUPLICATE_ACTIVE_REFERRAL`, `ERR_DUPLICATE_MEAL_SHIFT`, or `ERR_TRANSITION_PLAN_REQUIRED`. Eighth, cross-entity referential fit: a referral must belong to the requesting family, a room must belong to the request's house, and a care-space booking family must hold a verified referral at the care space's hospital — surfacing as `ERR_REFERRAL_FAMILY_MISMATCH`, `ERR_ROOM_HOUSE_MISMATCH`, or `ERR_BOOKING_REFERRAL_MISMATCH`. Ninth, temporal sanity: booking `end_at` strictly after `start_at`, and `expected_nights` at least one night, surfacing as `ERR_INVALID_DATE_RANGE` (HTTP 422). Tenth, fiscal caps: payment amounts may not exceed the outstanding balance and distribution quantities may not exceed a donation's remaining units, surfacing as `ERR_OVERPAYMENT` or `ERR_INSUFFICIENT_SUPPLY` (both HTTP 422).

Because the pipeline is ordered, a request that fails both an authorization check and a state check always reports the authorization failure, and a request that fails both a stale-version check and a business-constraint check always reports the stale version first. Implementations must not reorder these gates.

### 2.6. Optimistic Concurrency Control

Two write endpoints carry a mandatory optimistic concurrency check on a parent entity's `version`. Creating a stay request requires the body to include `expected_family_version` matching the target `Family`'s current `version`. Creating a stay request legitimately supersedes the family's prior `WAITLISTED` or `OFFERED` requests and increments `Family.version`, so a writer holding a stale family view must be rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding state it never observed. Responding to an offer requires the body to include `expected_stay_request_version` matching the `StayRequest`'s current `version`. Offering, score recomputation, or a prior response each advance `StayRequest.version`, so a stale response is refused with `ERR_STALE_VERSION` (HTTP 412) before any state evaluation runs. Endpoints not listed here do not take a version field; a client supplying one on any other endpoint is providing an unknown field and is rejected under §2.5's first gate.

### 2.7. House Occupancy Posture and Derived Counts

A `ProgramAdmin` registers a `House` by supplying its `name`, `city`, and the `associated_hospital_id` of the treating hospital it primarily serves. Each `House` carries three derived counters and one derived enum that recompute on every relevant event — room creation, room status change, offer made, offer rescinded or expired, check-in, check-out, and relocation. `occupied_room_count` is the number of rooms whose `occupied` flag is true. `reserved_room_count` is the number of rooms held by an `OFFERED` stay request (that is, rooms referenced by some request's `offered_room_id`). `available_room_count` is the number of rooms whose `status` is `AVAILABLE`, whose `occupied` flag is false, and which are not currently reserved by any `OFFERED` request. The `posture` enum is derived from a simple ratio. The denominator is the count of the house's rooms whose `status` is `AVAILABLE` — note that an occupied room keeps status `AVAILABLE` while a stay occupies it, so occupied rooms remain in the denominator. When the denominator is zero, the posture is `FULL`. Otherwise, the ratio of `occupied_room_count` to that denominator determines the posture: the house is `FULL` when the ratio equals exactly 1.0, `NEAR_CAPACITY` when the ratio is at least 0.9 but strictly less than 1.0, and `OPEN` when the ratio is strictly below 0.9. The 0.9 boundary is inclusive on the `NEAR_CAPACITY` side; the comparison is exact, with no rounding. A freshly created house with no rooms therefore has a `posture` of `FULL` and all three counters zeroed.

### 2.8. Stay Priority Scoring

Every `StayRequest` carries two scores, both computed by the same weighted algorithm with different acuity inputs. The provisional variant runs at request creation and reads the family's self-reported acuity; the result is stored on `provisional_score`. The verified variant runs when the linked referral becomes `VERIFIED` — either at creation if the referral was already verified, or later as part of the verification cascade — and reads the hospital-attested `acuity_level` from the referral; the result is stored on `verified_score`. Because the two inputs can disagree, identical requests can carry different provisional and verified numbers.

The algorithm proceeds in four steps. First, compute a distance band from the requesting family's `distance_miles`: a distance of at least 50 miles but less than 100 miles yields a band value of 40; at least 100 miles but less than 250 miles yields 60; 250 miles or more yields 80. Second, look up an acuity multiplier: `LOW` contributes a multiplier of 1.0, `MODERATE` 1.25, `HIGH` 1.5, and `CRITICAL` 2.0. Third, compute a stay-length factor by capping `expected_nights` at 30 nights and dividing by 30 — a request for 30 or more nights contributes a factor of exactly 1.0, while a request for 15 nights contributes 0.5. Fourth, the raw score is the band value multiplied by the acuity multiplier, plus 20.0 times the stay-length factor; the raw score is capped at 100.0. The final stored value is the capped raw score rounded to exactly 2 decimal places using round-half-up.

### 2.9. Waitlist Ranking and Room Selection

When the system needs to promote waitlisted requests into freed capacity — during the assignment sweep, during a referral-revocation cascade, or at check-out — it applies a fixed ranking. A request is eligible to be promoted at a given house when its `house_id` matches the house, its `assignment_status` is `WAITLISTED`, and its `verification_status` is `VERIFICATION_OK`. Eligible requests are ranked by `verified_score` in descending order; ties are broken by `waitlisted_since` in ascending order so the longest-waiting request wins; any remaining tie is broken by `created_at` ascending. An empty candidate set is not an error — the promotion simply does nothing.

For each promoted request, the system picks a specific room using a fixed selector. Eligible rooms belong to the same house, have `status` equal to `AVAILABLE`, have `occupied` equal to false, and are not reserved by any `OFFERED` request. Among eligible rooms, the selector picks the one with the smallest `bed_count`; ties are broken by `room_number` in ascending lexicographic order. An empty eligible-room set is not an error — no offer is made for that request, and promotion continues with the next-ranked request. Each successful promotion decrements the sweep's remaining capacity snapshot by one.

### 2.10. Occupancy Intervals and Same-Day Turnover

A room's occupancy is modeled as a half-open interval that begins on the stay's `check_in_date` and ends on the stay's `actual_check_out_date`. The half-open semantics mean a check-out on calendar date D frees the room for a check-in on the same date D — same-day turnover is explicitly allowed. Any offer, check-in, or relocation that targets a room whose `occupied` flag is currently true, or that is reserved by another `OFFERED` request, is rejected with `ERR_ROOM_NOT_AVAILABLE` (HTTP 409).

### 2.11. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, the server validates identifiers from left to right. The first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` for that resource type, and no further path segments are validated. This rule applies uniformly to creation, mutation, and read endpoints.

### 2.12. Monetary Precision

All monetary values are integer cents. Per-night rounding on contribution requests uses round-half-up to the nearest cent (so 502.5 rounds to 503), and the rounding is pinned: the per-night amount is rounded first, and only then multiplied by the number of nights. This pinned order is contract-bearing because the alternative order (multiply first, then round) can yield a different total.

## 3. Business Logic & Workflows

### 3.1. Referral Issuance and Verification

A `Referral` is the hospital's attestation that a named child is being admitted or treated at the referring hospital. A `HospitalReferrer` issues a referral by supplying the `family_id`, the `hospital_id` (which must equal their own `X-User-ID`), the `treating_unit`, the `care_type` (`INPATIENT` or `OUTPATIENT`), the hospital-attested `acuity_level` (`LOW`, `MODERATE`, `HIGH`, or `CRITICAL`), and the `attending_clinician`. A `ProgramAdmin` may also create referrals on a hospital's behalf. The new referral lands in `PENDING` status, and the server records the caller's `X-User-ID` on `created_by_user_id`. At any time, at most one non-terminal referral — that is, one in `PENDING` or `VERIFIED` status — may exist for a given (family, hospital) pair; a second issuance against the same pair is rejected with `ERR_DUPLICATE_ACTIVE_REFERRAL` (HTTP 409).

Verification is a house-side decision made by a `HouseManager` or `ProgramAdmin`, and it is the system's segregation-of-duties boundary: the verifier's `X-User-ID` must differ from the referral's `created_by_user_id`, otherwise the call is rejected with `ERR_SEGREGATION_OF_DUTIES`. The decision is delivered as a `decision` field on the verify call, accompanied by an optional `notes` field. When `decision` is `APPROVE`, the referral must currently be `PENDING` — otherwise `ERR_INVALID_STATE` — and on success the referral transitions to `VERIFIED`, the server stamps `verified_by_user_id` with the verifier's identity, sets `verified_at` to the current logical clock, and computes `valid_until` as `verified_at` plus 30 days. The cascade then touches every stay request whose `referral_id` names this referral and whose `verification_status` is still `UNVERIFIED`: each such request moves to `VERIFICATION_OK` and has its `verified_score` computed using the verified variant of the scoring algorithm in §2.8. When `decision` is `DECLINE`, the same `PENDING`-state precondition and segregation-of-duties check apply, and on success the referral transitions to `DECLINED`; every stay request still waiting on this referral moves its `verification_status` to `VERIFICATION_FAILED`, and no verified score is computed.

### 3.2. Referral Revocation, Expiry, and the Re-Offer Cascade

A verified referral can be withdrawn. Revocation is performed either by a `ProgramAdmin` or by the `HospitalReferrer` whose `X-User-ID` matches the referral's `hospital_id`; a `HospitalReferrer` attempting to revoke another hospital's referral is rejected with `ERR_FORBIDDEN`. Revocation requires the referral to currently be `VERIFIED` — otherwise `ERR_INVALID_STATE` — and triggers a three-hop cascade. Hop 1 flips every linked stay request whose `verification_status` is `VERIFICATION_OK` to `VERIFICATION_FAILED`. Hop 2 takes the subset of those requests whose `assignment_status` is `OFFERED` and rescinds the offer: each moves back to `WAITLISTED`, its `offered_room_id` is cleared, its `offer_expires_at` is cleared, its `waitlisted_since` is restamped to the current logical clock, and the room reservation is released. Hop 3 immediately re-offers each room freed by hop 2 to the highest-ranked eligible waitlisted request at that house, applying the ranking and room-selection rules of §2.9; the promoted request becomes `OFFERED`, `offered_room_id` is set, and `offer_expires_at` is restamped to the current logical clock plus 48 hours. When no eligible request exists for a freed room, that room simply becomes available again with no offer. Independently of the stay-request cascade, any `Stay` whose chain back to this referral is intact and whose `status` is exactly `ACTIVE` is moved to `UNDER_REVIEW` with `review_reason` set to `REFERRAL_REVOKED`; stays already in `UNDER_REVIEW`, `TRANSITION_PLANNED`, or `RELOCATION_REQUIRED` are left alone. The referral itself lands in `REVOKED`.

Referral expiry is the time-driven twin of revocation. During an assignment sweep, any referral still in `VERIFIED` status whose `valid_until` is strictly before the current logical clock transitions to `EXPIRED` and runs the exact same hop 1 / hop 2 / hop 3 cascade as revocation.

### 3.3. Stay Request Creation and Supersession

A `ProgramAdmin` or `HouseManager` registers a `Family` by supplying `family_name`, `primary_contact_name`, `home_city`, `distance_miles`, and `child_patient_name`. The `home_city` and `distance_miles` together anchor the eligibility and scoring rules — `distance_miles` is the one-way distance from the family's home to the treating hospital in miles. A `ProgramAdmin` similarly registers a partner `Hospital` with just its `name` and `city`.

A stay request asks for a room at a specific house on behalf of a specific family. The creating caller — a `FamilyContact` acting for their own family (so `family_id` must equal `X-User-ID`, otherwise `ERR_FORBIDDEN`), a `HouseManager`, or a `ProgramAdmin` — supplies `family_id`, `house_id`, `referral_id`, `expected_nights`, `self_reported_acuity`, and the OCC field `expected_family_version`. The family's `distance_miles` must be at least 50 — otherwise `ERR_DISTANCE_INELIGIBLE` (HTTP 422). The named referral must belong to the same family — otherwise `ERR_REFERRAL_FAMILY_MISMATCH` (HTTP 422). The supplied `expected_family_version` must match the family's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412). `expected_nights` must be at least 1 night — otherwise `ERR_INVALID_DATE_RANGE` (HTTP 422).

Creation is create-with-supersede. Before the new request is persisted, every other stay request of the same family whose `assignment_status` is `WAITLISTED` or `OFFERED` is moved to `CANCELLED`, with `superseded_by_request_id` set to the new request's `id`. If one of the superseded requests was `OFFERED`, its room reservation is released — `offered_room_id` is cleared and the room's reservation count drops — but no re-offer happens at this step; the freed room is picked up by the next sweep or check-out cascade. The family's `version` is incremented by 1 to reflect the supersession, and `updated_at` is refreshed.

The new request lands in `WAITLISTED` on the assignment dimension. On the verification dimension, if the linked referral is already `VERIFIED` at creation time, the request enters `VERIFICATION_OK` immediately and its `verified_score` is computed from the verified variant of §2.8; otherwise the request enters `UNVERIFIED` and `verified_score` remains null. In both cases the `provisional_score` is computed at creation from the `self_reported_acuity` using the provisional variant, and `waitlisted_since` is stamped with the current logical clock.

### 3.4. Offer, Response, and Check-In

A `HouseManager` or `ProgramAdmin` offers a specific room to a waitlisted, verified request. The request must currently be `WAITLISTED` (otherwise `ERR_INVALID_STATE`) and `VERIFICATION_OK` (otherwise `ERR_REFERRAL_NOT_VERIFIED`, HTTP 409). The target `room_id` must belong to the same house as the request's `house_id` — otherwise `ERR_ROOM_HOUSE_MISMATCH` (HTTP 422). The room itself must have `status` equal to `AVAILABLE`, `occupied` equal to false, and must not be reserved by any other `OFFERED` request — any of these failures surfaces as `ERR_ROOM_NOT_AVAILABLE` (HTTP 409). On success the request transitions from `WAITLISTED` to `OFFERED`, `offered_room_id` is set to the chosen room, `offer_expires_at` is stamped with the current logical clock plus 48 hours, and the house's `reserved_room_count` is recomputed. The same WAITLISTED → OFFERED transition can also be triggered by the system — during a sweep or during a cascade re-offer — under the same preconditions.

Only a `FamilyContact` may respond to an offer, and only for their own family's request — `family_id` must equal `X-User-ID`. The respond call carries a `decision` (`ACCEPT` or `DECLINE`) and the OCC field `expected_stay_request_version`, which must match the request's current `version` or the call is refused with `ERR_STALE_VERSION` before any other evaluation. The request must currently be `OFFERED` — otherwise `ERR_INVALID_STATE` — and its `offer_expires_at` must be at or after the current logical clock, otherwise the response is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). When `decision` is `ACCEPT`, the request transitions from `OFFERED` to `ACCEPTED` and its `version` increments by 1. When `decision` is `DECLINE`, the request transitions from `OFFERED` back to `WAITLISTED`, its `offered_room_id` and `offer_expires_at` are cleared, its `waitlisted_since` is restamped, the room reservation is released without an immediate re-offer, and `version` increments by 1.

Separately from a family response, an offer can expire under the assignment sweep: any request still `OFFERED` whose `offer_expires_at` is strictly before the current logical clock is transitioned back to `WAITLISTED` with `offered_room_id` and `offer_expires_at` cleared, `waitlisted_since` restamped, and the room reservation released; the same sweep run later re-offers the freed room per §2.9.

Check-in is performed by a `HouseManager` or `ProgramAdmin` on a request whose `assignment_status` is `ACCEPTED` — otherwise `ERR_INVALID_STATE`. The offered room must still be `AVAILABLE` with `occupied` false at the moment of check-in — otherwise `ERR_ROOM_NOT_AVAILABLE`. On success a new `Stay` is created in `ACTIVE` status: `stay_request_id` points back to the originating request, `family_id` is copied from the request, `room_id` is the offered room, `check_in_date` is the current logical calendar date in `YYYY-MM-DD` form, and `expected_check_out_date` is `check_in_date` plus the request's `expected_nights`. The request itself transitions from `ACCEPTED` to `FULFILLED`, the room's `occupied` flag flips to true, and the house's `occupied_room_count`, `available_room_count`, and `posture` recompute. The new stay is returned with HTTP 201.

Cancellation of a stay request is permitted while the request is `WAITLISTED` or `OFFERED` and moves it to `CANCELLED`. A `FamilyContact` cancelling must own the family; `HouseManager` and `ProgramAdmin` may cancel any. If the request was `OFFERED`, its room reservation is released without a re-offer.

### 3.5. Stay Extensions, Reviews, and Relocation

A stay begins `ACTIVE` and is terminally `CHECKED_OUT`. Three events can move an `ACTIVE` stay into `UNDER_REVIEW`: a family-initiated extension request, a system-initiated length-of-stay flag, and a referral-revocation cascade (already covered in §3.2).

An extension request is initiated by a `FamilyContact` (own stay only) or a `HouseManager` by submitting `additional_nights`. The stay must be `ACTIVE` — otherwise `ERR_STAY_NOT_ACTIVE` (HTTP 409). The stay's `approved_extension_count` must be strictly less than 2 — otherwise `ERR_TRANSITION_PLAN_REQUIRED` (HTTP 409), signalling that the family has exhausted routine extensions and a transition plan must be put in place first. The referral that backs the originating stay request must still be `VERIFIED` — otherwise `ERR_REFERRAL_NOT_VERIFIED`. On success the stay transitions from `ACTIVE` to `UNDER_REVIEW`, `pending_extension_nights` is set to the requested `additional_nights`, and `review_reason` is set to `EXTENSION_REQUEST`.

A `HouseManager` or `ProgramAdmin` then resolves the review with a `decision` field. When `decision` is `APPROVE_EXTENSION` and the stay is `UNDER_REVIEW`, the stay's `review_reason` must be `EXTENSION_REQUEST` — otherwise `ERR_INVALID_STATE` — and on success `expected_check_out_date` is advanced by `pending_extension_nights`, `approved_extension_count` is incremented by 1, `pending_extension_nights` and `review_reason` are cleared, and the stay returns to `ACTIVE`. When `decision` is `DENY_EXTENSION` on an `UNDER_REVIEW` stay, `pending_extension_nights` and `review_reason` are cleared and the stay returns to `ACTIVE` with no date change. When `decision` is `PLAN_TRANSITION` on an `UNDER_REVIEW` stay, the call must carry `transition_plan_notes` — otherwise `ERR_INVALID_REQUEST` — and on success the stay moves to `TRANSITION_PLANNED` with the notes recorded and `pending_extension_nights` cleared.

A stay in `TRANSITION_PLANNED` can still be brought back to `ACTIVE` if the plan is revised. The same `APPROVE_EXTENSION` decision applied to a `TRANSITION_PLANNED` stay requires `approved_extension_count` to be strictly less than 2 (else `ERR_TRANSITION_PLAN_REQUIRED`) and the originating referral to be `VERIFIED` (else `ERR_REFERRAL_NOT_VERIFIED`); on success, `transition_plan_notes` and `review_reason` are cleared and the stay returns to `ACTIVE`.

Relocation is forced by room offlining. When a `HouseManager` or `ProgramAdmin` sets a room's `target_status` to `OFFLINE` while a stay occupies it, the stay transitions from `ACTIVE` to `RELOCATION_REQUIRED` and the offlined room's `occupied` flag is cleared, with the house occupancy recomputed. To resolve a relocation, the reviewer supplies a `relocation_room_id` along with `decision` equal to `RELOCATE`. The stay must currently be `RELOCATION_REQUIRED` (otherwise `ERR_INVALID_STATE`); the replacement room must belong to the same house as the old room, be `AVAILABLE`, unoccupied, and unreserved — otherwise `ERR_ROOM_NOT_AVAILABLE`. On success the stay's `room_id` is updated to `relocation_room_id`, the new room's `occupied` flag flips to true, the house occupancy recomputes, and the stay returns to `ACTIVE`.

### 3.6. Check-Out and the Departure Cascade

Check-out is performed by a `HouseManager` or `ProgramAdmin` on any stay whose status is not already `CHECKED_OUT` — `ACTIVE`, `UNDER_REVIEW`, `TRANSITION_PLANNED`, and `RELOCATION_REQUIRED` are all valid starting points. Checkout is never blocked by unpaid, unwaived, or unforgiven contribution balances; contributions are never a condition of stay. On success, `actual_check_out_date` is stamped with the current logical calendar date, and the stay moves to `CHECKED_OUT`.

The departure cascade then runs in order. First, the stay's room has its `occupied` flag cleared — a no-op when the stay was in `RELOCATION_REQUIRED` because the offlined room was already released. Second, the freed room triggers an immediate promotion at the house: the highest-ranked eligible waitlisted request per §2.9 transitions from `WAITLISTED` to `OFFERED`, holding this room, with `offered_room_id` set and `offer_expires_at` restamped to the clock plus 48 hours; when no request is eligible the room simply becomes available. Third, every `GuestRegistration` on the stay whose `status` is `REGISTERED` flips to `DEPARTED`. Fourth, every `ContributionRequest` on the stay whose `status` is `OPEN` or `PARTIALLY_PAID` is settled and forgiven: the system computes `actual_nights` as the calendar-day difference between `actual_check_out_date` and `check_in_date`, computes `settled_amount_cents` as `per_night_cents` multiplied by `actual_nights`, re-anchors `requested_amount_cents` to that settled value, sets `forgiven_cents` to the resulting `outstanding_cents`, zeroes `outstanding_cents`, and moves the request to `FORGIVEN`.

### 3.7. Guests, Illness Screening, and the Same-Day Clearance Gate

A `FamilyContact` (own stay) or `HouseManager` registers a guest on a stay by supplying `guest_name`, `relationship`, and `is_overnight`. The guest's parent stay is identified through the `stay_id` field on the registration record, which is populated from the path. The stay must be `ACTIVE` — otherwise `ERR_STAY_NOT_ACTIVE`. Overnight guests count against the occupied room's `occupancy_limit`: if the number of `REGISTERED` overnight guests on the stay would exceed that limit, the registration is rejected with `ERR_GUEST_LIMIT_EXCEEDED` (HTTP 422). The registration is also gated on same-day illness screening clearance: a screening must exist for the stay whose `screened_at` calendar date equals the current logical date and whose `result` is `PASS`; otherwise the registration is rejected with `ERR_SCREENING_NOT_CLEARED` (HTTP 422). On success the registration lands in `REGISTERED` status.

Illness screenings are recorded by a `HouseManager` or `ProgramAdmin` against a stay. The body carries `temperature_tenths_c` (temperature in integer tenths of a degree Celsius, so 380 means 38.0 °C), `symptom_count` (a non-negative integer), and an optional `notes` field defaulting to the empty string. The stay must be `ACTIVE` — otherwise `ERR_STAY_NOT_ACTIVE`. The server computes `result` from the new record alone: the screening is `PASS` when `symptom_count` is exactly 0 and `temperature_tenths_c` is strictly less than 380; otherwise it is `FAIL`. The boundary is exact — a reading of exactly 380 tenths (38.0 °C) FAILS, and only a strictly-below reading passes. The server stamps `screened_at` with the current logical clock. Screening records are immutable: they carry `id` and `created_at` but neither `updated_at` nor `version`, and there is no endpoint that mutates them.

### 3.8. Contribution Requests: Suggested, Never Mandatory

A `HouseManager` or `ProgramAdmin` may create a `ContributionRequest` on a stay to suggest a nightly family contribution. The body supplies `nightly_rate_cents` (a positive integer), `planned_nights` (a positive integer), and `hardship_tier` — one of `NONE`, `PARTIAL`, or `FULL`. The server computes a per-night amount by multiplying `nightly_rate_cents` by the hardship factor — 1.0 for `NONE`, 0.5 for `PARTIAL`, and 0.0 for `FULL` — and rounding the product half-up to the nearest integer cent; this rounded value is stored as `per_night_cents`. The `requested_amount_cents` is then `per_night_cents` multiplied by `planned_nights`, computed at creation. `paid_cents`, `waived_cents`, and `forgiven_cents` each start at 0; `settled_amount_cents` is null until the stay checks out. The new request lands in `OPEN` status. Contributions are never a condition of stay: an outstanding balance does not block checkout, does not block extension, and does not block any guest or screening operation.

A `FamilyContact` (own stay) or `HouseManager` records a payment against a request by supplying `amount_cents`. The request must currently be `OPEN` or `PARTIALLY_PAID` — otherwise `ERR_INVALID_STATE`. The `amount_cents` may not exceed the request's `outstanding_cents` — otherwise `ERR_OVERPAYMENT` (HTTP 422). On success, `paid_cents` is incremented by `amount_cents` and `outstanding_cents` recomputes. If the payment equals the prior `outstanding_cents`, the request moves to `PAID` and `outstanding_cents` becomes 0; if the payment is strictly less, the request moves to (or stays in) `PARTIALLY_PAID`.

A `HouseManager` or `ProgramAdmin` may waive a request whose status is `OPEN` or `PARTIALLY_PAID`. Waiving sets `waived_cents` to the current `outstanding_cents`, zeroes `outstanding_cents`, and moves the request to `WAIVED`.

A contribution request's ledger is a conserved quantity at all times: `requested_amount_cents` always equals the sum of `paid_cents`, `waived_cents`, `forgiven_cents`, and `outstanding_cents`. The check-out settle step re-anchors `requested_amount_cents` to `settled_amount_cents` before computing `forgiven_cents`, so the invariant holds across the settle too. Terminal states are `PAID`, `WAIVED`, and `FORGIVEN`.

### 3.9. Volunteer Groups, Food-Safety Certification, and the Meal Program

A `VolunteerCoordinator` or `ProgramAdmin` registers a `VolunteerGroup` by supplying `group_name` and `contact_email`. The new group's `certified_until` is null and its `certification_status` is `UNCERTIFIED`. Certification is granted by a `ProgramAdmin` calling certify with a `certified_until` date in `YYYY-MM-DD` form; an unparseable date is rejected with `ERR_INVALID_REQUEST`. The group's `certification_status` recomputes against the current logical date on every change: `UNCERTIFIED` when `certified_until` is null, `CERTIFIED` when `certified_until` is on or after the current logical date, and `EXPIRED` when `certified_until` is strictly before the current logical date. A certification backdated to before the current logical date therefore lands the group directly in `EXPIRED`, not `CERTIFIED`.

A `HouseManager` or `ProgramAdmin` schedules a `MealShift` at a house by supplying `shift_date` (`YYYY-MM-DD`), `meal_type` (`BREAKFAST`, `LUNCH`, or `DINNER`), and `servings_planned` (a positive integer). At most one meal shift may exist per (house, shift_date, meal_type) triple; a second scheduling against the same triple is rejected with `ERR_DUPLICATE_MEAL_SHIFT` (HTTP 409). The new shift lands in `OPEN` status.

A `VolunteerCoordinator` claims an `OPEN` shift by naming the claiming group via `volunteer_group_id`. The shift must be `OPEN` — otherwise `ERR_INVALID_STATE`. The named group's `certification_status` must not be `UNCERTIFIED` — otherwise `ERR_FOOD_SAFETY_CERT_REQUIRED` (HTTP 422). And the group's `certified_until` must be on or after the shift's `shift_date` — otherwise `ERR_FOOD_SAFETY_CERT_EXPIRED` (HTTP 422). On success the shift transitions from `OPEN` to `CLAIMED` and `claimed_by_group_id` is set.

A `VolunteerCoordinator` or `HouseManager` completes a `CLAIMED` shift by recording `servings_served` and `food_safety_attested`. The shift must be `CLAIMED` — otherwise `ERR_INVALID_STATE`. `food_safety_attested` must be exactly true — otherwise `ERR_FOOD_SAFETY_ATTESTATION_REQUIRED` (HTTP 422). `servings_served` must be a positive integer — otherwise `ERR_INVALID_REQUEST`. On success the shift transitions to `COMPLETED` and both fields are recorded.

Cancellation has two modes. Cancelling an `OPEN` shift moves it to `CANCELLED`, which is terminal. Cancelling a `CLAIMED` shift moves it back to `OPEN` and clears `claimed_by_group_id`, releasing the group. Both modes are available to `VolunteerCoordinator`, `HouseManager`, and `ProgramAdmin`.

### 3.10. Care Spaces and Bookings

A `ProgramAdmin` creates a `CareSpace` inside a hospital by supplying `space_name`, `space_type` (`FAMILY_ROOM` or `MOBILE_CARE_UNIT`), and `capacity` (a positive integer that bounds the party size of any single booking). The space's `hospital_id` is taken from the path. Every `CareSpaceBooking` recorded against a space carries a `care_space_id` foreign key back to its parent space.

A `FamilyContact` (own family) or `HouseManager` books a care space by supplying `family_id`, `start_at`, `end_at`, and `party_size`. `end_at` must be strictly after `start_at` — otherwise `ERR_INVALID_DATE_RANGE`. `party_size` may not exceed the space's `capacity` — otherwise `ERR_CAPACITY_EXCEEDED` (HTTP 422). The booking family must hold a referral in `VERIFIED` status at the care space's hospital — otherwise `ERR_BOOKING_REFERRAL_MISMATCH` (HTTP 422). Booking conflicts are evaluated against the set of `CONFIRMED` bookings on the same care space; `CANCELLED` bookings do not block. Every `CONFIRMED` booking blocks a window that begins at its `start_at` and ends 30 minutes after its `end_at` — a 30-minute cleaning buffer follows each booking. A new booking whose interval intersects any existing blocked window is rejected with `ERR_CARE_SPACE_CONFLICT` (HTTP 409): formally, the new booking conflicts when its start is strictly before the blocked window's end and its end is strictly after the blocked window's start. Adjacency at exactly the buffer's end is allowed — a new booking whose `start_at` equals the prior booking's `end_at` plus 30 minutes is accepted, while one starting even one minute earlier is rejected. On success the booking lands in `CONFIRMED`.

Cancellation by a `FamilyContact` (own family) or `HouseManager` requires the booking to be `CONFIRMED` (otherwise `ERR_INVALID_STATE`) and moves it to `CANCELLED`, freeing the window for future overlap checks.

### 3.11. In-Kind Donations and the Supply Rollup

A `HouseManager` or `ProgramAdmin` records an `InKindDonation` at a house by supplying `donor_name`, `supply_category` (one of `HYGIENE_KIT`, `PANTRY_STAPLE`, `CLEANING_SUPPLY`, or `BABY_SUPPLY`), and `quantity_received` (a positive integer). The new donation lands in `RECEIVED` status with `quantity_distributed` initialized to 0.

Distribution is performed by a `HouseManager` or `ProgramAdmin` supplying a `quantity`. The donation must currently be `RECEIVED` or `PARTIALLY_DISTRIBUTED` — a distribution against a `DEPLETED` donation is rejected with `ERR_DONATION_DEPLETED` (HTTP 409). The requested `quantity` may not exceed the donation's remaining units, computed as `quantity_received` minus `quantity_distributed` — otherwise `ERR_INSUFFICIENT_SUPPLY` (HTTP 422). On success, `quantity_distributed` is incremented by `quantity`. When the distribution consumes strictly fewer than the remaining units, the donation moves to (or stays in) `PARTIALLY_DISTRIBUTED`; when it consumes exactly the remaining units, `quantity_distributed` becomes equal to `quantity_received` and the donation moves to `DEPLETED`.

The house's supply-inventory view aggregates across all donations of the house regardless of status: for each `supply_category`, on-hand is the sum of `quantity_received` minus `quantity_distributed` over every donation in that category, with `DEPLETED` donations naturally contributing 0. On-hand can never go negative because distribution is gated on the donation-level remaining check above.

### 3.12. Assignment Sweep and Stay-Review Sweep

Two admin-run checkpoints advance time-driven work. Both are restricted to `HouseManager` and `ProgramAdmin`.

The assignment sweep at a house runs a pinned four-step evaluation. Step 1 expires stale offers: every stay request whose `assignment_status` is `OFFERED` and whose `offer_expires_at` is strictly before the current logical clock transitions back to `WAITLISTED`, releasing its room reservation. Step 2 expires stale referrals: every referral in `VERIFIED` status whose `valid_until` is strictly before the current logical clock transitions to `EXPIRED`, running the full revocation cascade of §3.2 (which itself can free rooms and re-offer them). Step 3 snapshots capacity: the snapshot is the count of rooms that are `AVAILABLE`, `occupied` false, and unreserved after steps 1 and 2 have completed — note that rooms freed inside step 2's cascade and re-offered there are not double-counted. Step 4 promotes in the waitlist ranking order of §2.9, picking one room per request via the room selector and decrementing the snapshot by 1 per promotion; the sweep stops when the snapshot reaches 0 or the eligible request set is exhausted. Offers made inside step 4 do not re-enter the same sweep's candidate set. The response reports `expired_offer_ids`, `expired_referral_ids`, and `promoted_request_ids` — each a list of resource `id` strings.

The stay-review sweep at a house examines every stay whose `status` is `ACTIVE`. For each, it computes `nights_at_house` as the whole calendar-day difference between the current logical date and the stay's `check_in_date`. When `nights_at_house` is at least 21, the stay transitions to `UNDER_REVIEW` with `review_reason` set to `STAY_LENGTH`. The boundary is exact: a stay at exactly 21 nights is flagged, while a stay at 20 nights is not. The response reports `flagged_stay_ids` as a list of resource `id` strings.

## 4. Endpoint Definitions

Operations that create a new top-level resource or add a new resource to a collection return HTTP 201. Operations that modify an existing resource in place return HTTP 200. All endpoints are mounted under `/api`, except for the clock test-driving endpoint which is mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to `to_iso8601` | ProgramAdmin |
| POST | `/api/hospitals` | Create a treating-hospital partner | ProgramAdmin |
| GET | `/api/hospitals/{id}` | Get a hospital | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| GET | `/api/hospitals/{id}/houses` | List houses associated with a hospital | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| GET | `/api/hospitals/{id}/referrals` | List referrals issued by a hospital, optionally filtered by `status` | ProgramAdmin, HouseManager, HospitalReferrer |
| GET | `/api/hospitals/{id}/care-spaces` | List care spaces inside a hospital, optionally filtered by `space_type` | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| POST | `/api/houses` | Create a lodging house | ProgramAdmin |
| GET | `/api/houses/{id}` | Get a house with derived occupancy fields | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| GET | `/api/houses/{id}/supply-inventory` | Computed per-category on-hand supply rollup | ProgramAdmin, HouseManager |
| POST | `/api/houses/{id}/rooms` | Add a room to a house | ProgramAdmin, HouseManager |
| GET | `/api/houses/{id}/rooms` | List rooms of a house, optionally filtered by `status` | ProgramAdmin, HouseManager |
| GET | `/api/rooms/{id}` | Get a room | ProgramAdmin, HouseManager |
| GET | `/api/rooms/{id}/stay-requests` | List stay requests currently holding an offer on this room | ProgramAdmin, HouseManager |
| POST | `/api/rooms/{id}/set-status` | Transition a room between AVAILABLE / MAINTENANCE / OFFLINE via `target_status` | ProgramAdmin, HouseManager |
| POST | `/api/families` | Register a family | ProgramAdmin, HouseManager |
| GET | `/api/families/{id}` | Get a family | ProgramAdmin, HouseManager, FamilyContact |
| GET | `/api/families/{id}/referrals` | List referrals for a family, optionally filtered by `status` | ProgramAdmin, HouseManager, FamilyContact, HospitalReferrer |
| GET | `/api/families/{id}/stay-requests` | List stay requests of a family, optionally filtered by `assignment_status` | ProgramAdmin, HouseManager, FamilyContact |
| GET | `/api/families/{id}/care-space-bookings` | List care-space bookings of a family, optionally filtered by `status` | ProgramAdmin, HouseManager, FamilyContact |
| POST | `/api/referrals` | Issue a referral for a family at a hospital | HospitalReferrer, ProgramAdmin |
| GET | `/api/referrals/{id}` | Get a referral | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact |
| POST | `/api/referrals/{id}/verify` | House-side verification decision (APPROVE or DECLINE) | HouseManager, ProgramAdmin |
| POST | `/api/referrals/{id}/revoke` | Revoke a verified referral | HospitalReferrer, ProgramAdmin |
| POST | `/api/stay-requests` | Create a stay request with supersession and family-version OCC | FamilyContact, HouseManager, ProgramAdmin |
| GET | `/api/stay-requests/{id}` | Get a stay request | ProgramAdmin, HouseManager, FamilyContact |
| GET | `/api/stay-requests` | List stay requests, filterable by `house_id`, `family_id`, `referral_id`, `assignment_status` | ProgramAdmin, HouseManager, FamilyContact |
| POST | `/api/stay-requests/{id}/offer` | Offer a specific room to a waitlisted, verified request | HouseManager, ProgramAdmin |
| POST | `/api/stay-requests/{id}/respond` | Family accepts or declines an offer with request-version OCC | FamilyContact |
| POST | `/api/stay-requests/{id}/cancel` | Cancel a waitlisted or offered request | FamilyContact, HouseManager, ProgramAdmin |
| POST | `/api/stay-requests/{id}/check-in` | Check an accepted family into the offered room; creates the Stay | HouseManager, ProgramAdmin |
| GET | `/api/stays/{id}` | Get a stay | ProgramAdmin, HouseManager, FamilyContact |
| GET | `/api/stays` | List stays, filterable by `family_id`, `room_id`, `stay_request_id`, `status` | ProgramAdmin, HouseManager |
| POST | `/api/stays/{id}/guests` | Register a guest on a stay | FamilyContact, HouseManager |
| GET | `/api/stays/{id}/guests` | List guest registrations of a stay, optionally filtered by `status` | ProgramAdmin, HouseManager, FamilyContact |
| POST | `/api/stays/{id}/screenings` | Record a daily illness screening | HouseManager, ProgramAdmin |
| GET | `/api/stays/{id}/screenings` | List illness screenings of a stay, optionally filtered by `result` | ProgramAdmin, HouseManager, FamilyContact |
| POST | `/api/stays/{id}/request-extension` | Request additional nights via `additional_nights`; routes the stay into UNDER_REVIEW | FamilyContact, HouseManager |
| POST | `/api/stays/{id}/review` | Resolve a review (APPROVE_EXTENSION / DENY_EXTENSION / PLAN_TRANSITION / RELOCATE) | HouseManager, ProgramAdmin |
| POST | `/api/stays/{id}/check-out` | Check out a stay; cascades room release, promotion, guest departure, contribution settlement | HouseManager, ProgramAdmin |
| POST | `/api/stays/{id}/contribution-requests` | Create a suggested contribution request for a stay | HouseManager, ProgramAdmin |
| GET | `/api/stays/{id}/contribution-requests` | List contribution requests of a stay, optionally filtered by `status` | ProgramAdmin, HouseManager, FamilyContact |
| GET | `/api/contribution-requests/{id}` | Get a contribution request | ProgramAdmin, HouseManager, FamilyContact |
| POST | `/api/contribution-requests/{id}/record-payment` | Record a payment via `amount_cents` toward a contribution request | FamilyContact, HouseManager |
| POST | `/api/contribution-requests/{id}/waive` | Waive the outstanding balance of a contribution request | HouseManager, ProgramAdmin |
| POST | `/api/volunteer-groups` | Register a volunteer group | VolunteerCoordinator, ProgramAdmin |
| GET | `/api/volunteer-groups/{id}` | Get a volunteer group | VolunteerCoordinator, ProgramAdmin, HouseManager |
| POST | `/api/volunteer-groups/{id}/certify` | Certify a volunteer group for food safety through `certified_until` | ProgramAdmin |
| GET | `/api/volunteer-groups/{id}/meal-shifts` | List meal shifts claimed by a volunteer group, optionally filtered by `status` | VolunteerCoordinator, ProgramAdmin, HouseManager |
| POST | `/api/houses/{id}/meal-shifts` | Schedule a volunteer meal shift at a house | HouseManager, ProgramAdmin |
| GET | `/api/houses/{id}/meal-shifts` | List meal shifts at a house, optionally filtered by `shift_date` and `status` | HouseManager, ProgramAdmin, VolunteerCoordinator |
| POST | `/api/meal-shifts/{id}/claim` | Volunteer group claims an open shift via `volunteer_group_id` | VolunteerCoordinator |
| POST | `/api/meal-shifts/{id}/complete` | Complete a claimed shift with a food-safety attestation | VolunteerCoordinator, HouseManager |
| POST | `/api/meal-shifts/{id}/cancel` | Cancel an open shift (terminal) or release a claimed shift back to OPEN | VolunteerCoordinator, HouseManager, ProgramAdmin |
| POST | `/api/hospitals/{id}/care-spaces` | Create a family room or mobile care unit inside a hospital | ProgramAdmin |
| GET | `/api/care-spaces/{id}` | Get a care space | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| POST | `/api/care-spaces/{id}/bookings` | Book a care space for a family | FamilyContact, HouseManager |
| GET | `/api/care-spaces/{id}/bookings` | List bookings of a care space, optionally filtered by `status` | ProgramAdmin, HouseManager, HospitalReferrer, FamilyContact, VolunteerCoordinator |
| POST | `/api/care-space-bookings/{id}/cancel` | Cancel a confirmed booking | FamilyContact, HouseManager |
| POST | `/api/houses/{id}/in-kind-donations` | Record a donation of goods | HouseManager, ProgramAdmin |
| GET | `/api/houses/{id}/in-kind-donations` | List in-kind donations of a house, optionally filtered by `supply_category` and `status` | HouseManager, ProgramAdmin |
| POST | `/api/in-kind-donations/{id}/distribute` | Distribute units from a donation | HouseManager, ProgramAdmin |
| POST | `/api/houses/{id}/run-assignment-sweep` | Run the assignment epoch: expire offers and referrals, then promote the waitlist | HouseManager, ProgramAdmin |
| POST | `/api/houses/{id}/run-stay-review-sweep` | Run the stay-review epoch: flag long-running ACTIVE stays for review | HouseManager, ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STAY_NOT_ACTIVE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_DONATION_DEPLETED` | 409 |
| `ERR_REFERRAL_NOT_VERIFIED` | 409 |
| `ERR_SCREENING_NOT_CLEARED` | 422 |
| `ERR_FOOD_SAFETY_CERT_REQUIRED` | 422 |
| `ERR_FOOD_SAFETY_CERT_EXPIRED` | 422 |
| `ERR_FOOD_SAFETY_ATTESTATION_REQUIRED` | 422 |
| `ERR_DISTANCE_INELIGIBLE` | 422 |
| `ERR_GUEST_LIMIT_EXCEEDED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_ROOM_NOT_AVAILABLE` | 409 |
| `ERR_ROOM_HOUSE_MISMATCH` | 422 |
| `ERR_CARE_SPACE_CONFLICT` | 409 |
| `ERR_DUPLICATE_MEAL_SHIFT` | 409 |
| `ERR_DUPLICATE_ACTIVE_REFERRAL` | 409 |
| `ERR_REFERRAL_FAMILY_MISMATCH` | 422 |
| `ERR_BOOKING_REFERRAL_MISMATCH` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_TRANSITION_PLAN_REQUIRED` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_INSUFFICIENT_SUPPLY` | 422 |
