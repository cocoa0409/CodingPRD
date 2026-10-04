# Dispatch Health API — Product Requirements Document

## 1. Introduction

DispatchHealth-style acute home-visit programs sit at an uncomfortable seam in the care continuum: the patient is too sick for a scheduled clinic visit, but — when triage works — not sick enough to justify an emergency department transfer. The product described here is the API surface for an On-Demand Acute Home Visit Dispatch and Emergency Diversion platform. It governs the full lifecycle of an in-home acute episode: intake from patients, payers, referring providers, or facilities; clinical triage with a mandatory emergency-diversion gate; market-level coverage and response-window commitments; pairing of an advanced practice provider with a field technician under remote physician oversight; on-scene point-of-care testing, imaging, and intravenous therapy bounded by payer formularies; a disposition decision that either closes the episode at home or escalates the patient to a facility; and, finally, site-of-service claim submission, adjudication, follow-up notification to the primary care physician, and post-visit monitoring.

The system exists because the economics of home-based acute care only work when two things are true at once: true emergencies are redirected to EMS before a vehicle rolls, and every visit that does roll is documented tightly enough to survive payer adjudication at the lower home site-of-service rate. Every rule in this document exists to defend one of those two properties — clinical safety upstream, fiscal defensibility downstream — while giving dispatchers, nurses, field clinicians, and billing staff a deterministic API on which to coordinate.

All endpoints are mounted under the `/dh` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once identity is established, the role is checked against the endpoint's authorization matrix; a role not permitted on the endpoint receives `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes nine roles, spelled exactly as follows: `PlatformAdmin`, `TriageNurse`, `Dispatcher`, `CareTeamMember`, `AdvancedPracticeProvider`, `FieldTechnician`, `SupervisingPhysician`, `BillingSpecialist`, and `PayerAdjudicator`.

For all nine roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity row of its own. The server may record it where a workflow writes an actor — for example, as `physician_preauth_by` on a `DiagnosticOrder`, or implicitly as the team member accepting a dispatch — but it is never compared against an `id` column of a persisted user table. One role carries an additional ownership semantics: when `X-User-Role` is `CareTeamMember`, the acting user's `X-User-ID` is compared against the `app_user_id` and `tech_user_id` recorded on the `CareTeam` referenced by the target `DispatchAssignment`, and the comparison gates the accept, reject, and arrive actions. The `SupervisingPhysician` role's identity is likewise realized through comparison against the `supervising_physician_user_id` on the care team when formulary pre-authorization is validated, and against the identity of the technician who resulted an order when segregation-of-duties is enforced.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and rejects values above 100 (values that fail to parse as integers fall back to the default rather than raising an error, and out-of-range values are clamped into the 1–100 band rather than rejected). The `offset` parameter skips a number of items from the front of the result set and defaults to 0 (unparseable values fall back to 0 and negative values are clamped up to 0). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is still below `total_count`.

### 2.4. Logical Clock and Temporal Determinism

The platform runs on a logical clock, not on wall-clock time. Before any client interaction, the logical clock reads exactly `2026-09-01T00:00:00Z`; it must never fall back to the host's wall clock. A `PlatformAdmin`-only capability sets the logical clock to a supplied `current_utc` instant, canonicalizes it to ISO 8601 UTC with three fractional digits and a `Z` suffix, and echoes that canonical instant back as `current_utc`; this is the single temporal input to every derived timestamp in the system. The missed-check-in sweep is lazy — it is evaluated on demand at the start of every request — as is contract expiry, so both take effect the first time any request is processed after the threshold. Everywhere a rule below says "now", "at acceptance", "at close", or names a system-managed timestamp — `requested_at`, `submitted_at`, `handed_off_at`, `offered_at`, `accepted_at`, `started_at`, `ended_at`, `decided_at`, `dispatched_at`, `arrived_at_facility_at`, `sent_at`, `completed_at`, `adjudicated_at` — the value written is the logical clock at the moment of the write. SLA deadlines, acuity age computations, shift-window membership, contract-window membership, check-in due-ness, and the six-hour missed-check-in rule all evaluate against the logical clock. Note that the logical clock governs only system-managed business timestamps: the `api_request_timestamp` carried in every response envelope's `meta` is the server's wall-clock time at response construction, exactly as illustrated in §2.2, and `id` values are server-minted UUIDs drawn from the host's entropy source.

### 2.5. Common Resource Properties

Every primary resource in this system — `MarketCoverageArea`, `PayerContract`, `FormularyEntry`, `Patient`, `CareTeam`, `VehicleShift`, `VisitRequest`, `TriageAssessment`, `EmsHandoff`, `DispatchAssignment`, `OnSiteEncounter`, `DiagnosticOrder`, `DispositionDecision`, `FacilityTransport`, `Claim`, `ClaimLine`, `FollowUpNotice`, and `MonitoringCheckIn` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer starting at 1 that increments on every mutation; it is the optimistic-concurrency token.

Any mutation described in §3 — a status transition, a computed counter change such as `open_visit_count` or `active_dispatch_count`, an SLA latch — refreshes `updated_at` and increments `version` on the entity being mutated.

### 2.6. Hierarchical Consistency and Cascade Semantics

A visit is the spine of the system, and state propagates outward from it. When a `VisitRequest` advances, the entities hanging off it — its `DispatchAssignment`, its `OnSiteEncounter`, its `Claim`, its `MonitoringCheckIn` schedule — are reconciled in the same transaction so that no reader ever observes an inconsistent slice: an encounter without a dispatch, a claim without a visit in a claim-phase status, a care team holding an `active_dispatch_count` for work that no longer exists. Conversely, when a child resolves (a dispatch is rejected, a transport is cancelled, a diagnostic order is cancelled), the parent visit and the care team's counters are adjusted in the same operation, including the parent visit's `version` increment where the cascade calls for one. Cascade rules for each transition appear in §3 alongside the workflow that triggers them; the general principle is that the system may transition a related resource automatically when a parent event makes the child's prior state meaningless, and each such reconciliation independently updates the touched resource's `updated_at` and `version`.

### 2.7. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers left to right. A request whose path carries a parent id and a child id is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier — scanning left to right — that does not resolve to an existing resource; the system does not continue to deeper path segments once an earlier segment has failed. Foreign keys carried in request bodies (for example `patient_id`, `market_id`, `care_team_id`, `vehicle_shift_id`, `payer_contract_id`, `encounter_id`, `visit_request_id`) are validated separately from path identifiers: an unresolvable body foreign key is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.8. Monetary Values, Scores, and Precision

Money in this system is integer cents, end to end. Rates (`urgent_base_rate_cents`, `standard_base_rate_cents`, `unit_price_cents`), caps (`max_claim_cents`), per-line amounts (`line_amount_cents`, `amount_cents`), and claim totals (`provisional_total_cents`, `final_total_cents`) are all stored and returned as integer cents. Where a multiplication produces a fractional cent — the base visit line applies a percentage modifier to a contracted rate — the line amount is rounded half-up to the nearest integer cent, and the rounding is applied per line before any summation; the system never sums unrounded lines and rounds the total. Clinical scores (`acuity_score`, the dispatch selection score, the readmission risk score) are integers; every intermediate division in their computation is integer floor division, and each score is clamped into its documented range after summation. The monitoring adherence ratio is the one non-integer quantity exposed: it is reported as a whole-number percentage, rounded half-up, and is null when a visit has no check-ins.

### 2.9. Optimistic Concurrency Control

Two write operations accept — and require — an optimistic concurrency token on the parent `VisitRequest`: creating a dispatch offer for a visit, and submitting a claim. Each takes a non-optional `expected_visit_request_version` field carrying the client's last observed `version` of the visit. If the visit's current `version` no longer matches the supplied value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The dispatch-offer check protects a dispatcher whose view of the visit predates an intervening mutation (for example a triage reclassification); the claim-submit check protects a billing specialist whose `final_total_cents` was computed against a visit that has since advanced (for example because a diagnostic order was resulted in the interim). Endpoints other than those two do not accept a version field; their concurrency safety derives from the state-machine preconditions in §3.

### 2.10. Clinical Safety Governance and Segregation of Duties

Three safety invariants cut across every workflow and are stated here once. First, red-flag symptoms dominate scoring: a triage that records chest pain, stroke signs, severe trauma, or altered mental status must end in EMS diversion regardless of the numeric score, and the submit action enforces this with `ERR_RED_FLAG_REQUIRES_EMS`. Second, intravenous therapy is bounded twice — by a per-visit unit cap per drug from the payer's formulary, and by a mandatory supervising-physician pre-authorization for drugs so flagged — and both bounds are enforced at order-creation time, before the drug is administered. Third, result verification is segregated: the user who verifies a diagnostic result must be a different user than the one who resulted it, enforced with `ERR_SOD_VIOLATION`, so no field technician can self-certify a result that flows into a claim.

### 2.11. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so the client always sees the most fundamental failure first: (1) presence and shape of the identity headers, then (2) role permission on the endpoint, then (3) left-to-right resolution of path identifiers, then (4) resolution of foreign keys in the request body, then (5) the optimistic-concurrency version check where the endpoint takes one, then (6) the target entity's state-machine eligibility, and only then (7) the business rules — safety, temporal, fiscal, and payload shape — in the order each subsection of §3 lists them. A request failing an earlier check never surfaces a later check's error code. Structural payload-shape failures — a body that is not a JSON object, a missing required field, or a field of the wrong JSON type, including the structural components of the shape rules named in §3 such as a rationale or payload_summary below its minimum length, a sub-minimum `units` count, or a missing `result_value` — are evaluated as the request is decoded, ahead of the resource checks above; the shape checks named in §3 that depend on workflow context (for example `ERR_FACILITY_REQUIRED` on an escalation, the formulary-cap and pre-authorization guards, and `ERR_AMEND_NO_CHANGE`) remain business rules under (7).

## 3. Business Logic & Workflows

### 3.1. Markets, Payer Contracts, and Formularies

Operations begin with geography. A `PlatformAdmin` defines a **MarketCoverageArea** by supplying a unique `market_code` (an identifier such as "DFW-NORTH"), a human-readable `display_name`, and a `polygon_geojson` boundary expressed as a GeoJSON polygon. The market also carries two response-window commitments: `response_window_minutes_urgent`, the promised minutes from dispatch acceptance to on-scene arrival for an `URGENT` visit, and `response_window_minutes_standard`, the corresponding promise for a `STANDARD` visit. The `is_active` flag, defaulting to true, controls whether the market accepts new visit requests and new dispatch offers; attempting intake or a dispatch offer against a market whose `is_active` is false is rejected with `ERR_MARKET_INACTIVE` (HTTP 409). Each market maintains a computed `open_visit_count` — the number of its visit requests currently in any non-terminal status, meaning `INTAKE` through `DISPOSITIONED` plus `CLAIM_DRAFT`, `CLAIM_SUBMITTED`, and `CLAIM_APPEALED` — which rises by one at intake and falls by one whenever a visit reaches `EMS_DIVERTED`, `DECLINED`, or `CLOSED`. The `market_code` must be unique across all markets; a duplicate is rejected with `ERR_MARKET_CODE_TAKEN` (HTTP 409). Market lists support an `is_active` query filter, parsed leniently: the values "true", "1", and "yes" (case-insensitive) select active markets and anything else selects inactive ones.

Payer economics are per-market. A `PlatformAdmin` creates a **PayerContract** by naming a `payer_code` (for example "AETNA" or "BCBS-TX"), the `market_id` of the market it applies to, the contracted `urgent_base_rate_cents` and `standard_base_rate_cents` (site-of-service rates for home visits, deliberately lower than the emergency-department site rate), a `place_of_service_modifier_pct` applied as a multiplier to the base rate for the home place of service (a value of 0.85 expresses a fifteen percent discount versus office), a hard per-claim ceiling `max_claim_cents`, and an effectiveness window from `effective_from` up to but not including `effective_to`. A contract is created in `DRAFT` status. Activation moves it to `ACTIVE` and requires that `effective_from` is strictly before `effective_to`; a window failing that ordering is rejected with `ERR_CONTRACT_WINDOW_INVALID` (HTTP 400). An `ACTIVE` contract transitions to `EXPIRED` automatically once the logical clock reaches `effective_to` (the expiry sweep is lazy, applied on the first request processed after the threshold), and a `PlatformAdmin` may move an `ACTIVE` contract to `TERMINATED` at any time. Both `TERMINATED` and `EXPIRED` are terminal; a status change attempted from the wrong state is rejected with `ERR_CONTRACT_INVALID_STATE` (HTTP 409). Nothing in the contract schema prevents two contracts from sharing a `payer_code` and `market_id`; wherever the system must resolve the single contract applicable to a visit (see §3.7), the most recently created matching contract wins. Contract lists support filtering by `payer_code`, `market_id`, and `status`.

Under each contract sits its formulary. A `PlatformAdmin` adds a **FormularyEntry** to a specific contract, naming a `drug_code` (such as "IVF-NS-1L" for a liter of normal saline, or "IV-ABX-CEFTRIAXONE-1G" for a gram of IV ceftriaxone), the `max_units_per_visit` billable for that drug on a single visit, whether the drug `requires_physician_preauth` before administration, and the contracted `unit_price_cents`. The formulary is per-contract: two contracts may list the same `drug_code` with different caps and prices. Formulary entries are retrievable as a sub-resource of their contract, which keeps the pricing source reachable from the contract without exposing it to field roles.

### 3.2. Patient Intake and Visit Request Creation

A **Patient** is registered by a `PlatformAdmin` or a `TriageNurse` with a `full_name`, a `date_of_birth` given as an ISO 8601 calendar date, the `payer_code` printed on the insurance card together with the `member_id` under that payer, the primary care physician's `pcp_name` and ten-digit `pcp_npi` (the routing target for follow-up; stored as a string and compared by exact string equality, so any zero-padding convention is the client's responsibility), a `comorbidity_count` of documented chronic conditions (defaulting to zero and feeding acuity scoring), and a `home_address_geo` WGS84 point against which market containment is tested. Patient lists support filtering by `payer_code`. Containment is evaluated by ray-casting against the polygon's exterior ring, and a point lying exactly on the boundary counts as inside.

Intake itself is a **VisitRequest** creation, performed by a `TriageNurse` or a `Dispatcher` (the latter covering facility-side intake). The payload carries the `patient_id`, the chosen `market_id`, a `requestor_role` drawn from `PATIENT`, `PAYER`, `PROVIDER`, or `FACILITY` recording which channel originated the call, and a free-text `chief_complaint`. Two guards run before the visit exists: the chosen market's `is_active` must be true (else `ERR_MARKET_INACTIVE`), and the patient's `home_address_geo` must lie inside that market's `polygon_geojson` boundary (else `ERR_OUT_OF_COVERAGE`, HTTP 422). On success the visit is created in `INTAKE` status, its `requested_at` stamped from the logical clock, and the market's `open_visit_count` rises by one. Visit-request lists support filtering by `patient_id`, `market_id`, `status`, `acuity_band`, `assigned_care_team_id`, and `claim_id`.

A visit request is a sixteen-state machine: `INTAKE`, `TRIAGE_PENDING`, `TRIAGED`, `EMS_DIVERTED`, `DECLINED`, `DISPATCH_PENDING`, `EN_ROUTE`, `ON_SCENE`, `DISPOSITIONED`, `ESCALATED_TRANSPORT`, `CLAIM_DRAFT`, `CLAIM_SUBMITTED`, `CLAIM_ADJUDICATED_PAID`, `CLAIM_ADJUDICATED_DENIED`, `CLAIM_APPEALED`, and `CLOSED`. The terminal states are `EMS_DIVERTED`, `DECLINED`, and `CLOSED`. Any action attempted against a visit that is not in a state from which that action is defined is rejected with `ERR_VR_INVALID_STATE` (HTTP 409). Beyond `status`, the visit carries a computed `acuity_band` (one of `EMERGENT`, `URGENT`, `STANDARD`, `NON_ACUTE`, derived from the latest triage assessment), a computed `assigned_care_team_id` set when a dispatch is accepted and cleared when every dispatch assignment for the visit ends `CANCELLED` or `REJECTED`, a computed `sla_deadline_at` that stays null until a dispatch is accepted, a computed `sla_breached` flag latched false at creation, and a computed `claim_id` that stays null until a claim exists.

### 3.3. Triage Assessment, Acuity Scoring, and Emergency Diversion

A `TriageNurse` opens clinical evaluation by creating a **TriageAssessment** against a visit in `INTAKE`. The payload captures four vitals — `heart_rate` in beats per minute (accepted range 20 to 250), `systolic_bp` in millimeters of mercury (40 to 300), and `spo2_pct` oxygen saturation (50 to 100) — plus four red-flag booleans: `is_chest_pain`, `is_stroke_signs`, `is_severe_trauma`, and `is_altered_mental_status`. Vital values outside their accepted ranges, like any other field-shape violation, are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Only one triage assessment may ever exist for a visit; a second creation attempt is rejected with `ERR_TRIAGE_ALREADY_EXISTS` (HTTP 409). Creating the assessment moves the visit from `INTAKE` to `TRIAGE_PENDING` and leaves the assessment in `DRAFT` outcome. The market's `open_visit_count` does not change at this step — the visit was already counted at intake.

When the nurse submits the assessment with an `outcome`, the system first computes the assessment's `acuity_score`, an integer from 0 to 100 built from six weighted components, with all intermediate divisions computed as integer floor division. The heart-rate component is the absolute difference between `heart_rate` and 80, floor-divided by 4, clamped between 0 and 25. The blood-pressure component is 25 outright when `systolic_bp` is below 90 or above 180; otherwise it is the absolute difference between `systolic_bp` and 120, floor-divided by 5, clamped between 0 and 15 — note the tighter cap on the non-extreme branch, so the component never exceeds 15 unless the pressure is frankly extreme, in which case it is 25. The oxygen component is zero when `spo2_pct` is 95 or higher; below 95 it is twice the shortfall from 95, clamped between 0 and 25. Red-flag symptoms contribute 20 points each, so four true flags contribute 80 points before any vital is considered. Age contributes 10 points for a patient aged at least 75, 5 points for at least 65 but under 75, and nothing younger; age in whole years is the floor of the elapsed days between the patient's `date_of_birth` and the logical-clock date divided by 365.25. Comorbidity burden contributes three points per documented condition, capped at 15 points. The raw sum of all six components is clamped into the 0–100 range to yield the final `acuity_score`.

Band assignment is decided by red-flag presence first and score thresholds second, in that fixed order. If any red-flag symptom is true, the band is `EMERGENT` regardless of the numeric score — even a score below 80 cannot soften a red flag. Otherwise, a score of at least 80 is `EMERGENT`; at least 50 but below 80 is `URGENT`; at least 30 but below 50 is `STANDARD`; below 30 is `NON_ACUTE`. The submission's declared `outcome` must agree with this derivation, and three mismatches are rejected with distinct codes. Declaring `APPROPRIATE` while any red-flag symptom is true is rejected with `ERR_RED_FLAG_REQUIRES_EMS` (HTTP 422) — the same code that rejects any non-diversion outcome declared against a red-flag assessment, since red flags dominate. Declaring `INAPPROPRIATE` requires the score to be below 30 with no red flag true; a score at or above 30 (or any true red flag, which the earlier guard already routes to `ERR_RED_FLAG_REQUIRES_EMS`) is rejected with `ERR_ACUITY_TOO_HIGH_FOR_DECLINE` (HTTP 422). Declaring `EMERGENCY_DIVERTED` requires a score of at least 80 or at least one red-flag symptom; submitting a diversion when neither holds is rejected with `ERR_ACUITY_TOO_LOW_FOR_DIVERSION` (HTTP 422). Submitting an assessment whose outcome is no longer `DRAFT` is rejected with `ERR_TRIAGE_NOT_DRAFT` (HTTP 409).

Each of the three accepted outcomes cascades differently. An `APPROPRIATE` submission stamps `submitted_at` from the logical clock, writes the derived band onto the visit's `acuity_band` (`URGENT` when the score is at least 50, otherwise `STANDARD` — `EMERGENT` is unreachable on this branch by construction), and moves the visit from `TRIAGE_PENDING` to `TRIAGED`. An `EMERGENCY_DIVERTED` submission sets the visit's band to `EMERGENT`, moves the visit to the terminal `EMS_DIVERTED` state, decrements the market's `open_visit_count` by one, and creates an **EmsHandoff** row — carrying the `triage_assessment_id` and `visit_request_id`, the receiving `ems_agency_code` (optional in the payload, defaulting to the string `EMS-DEFAULT` when omitted), a free-text `handoff_reason` (optional in the payload, defaulting to `Emergency diversion` when omitted), and a `handed_off_at` stamp from the logical clock — in the same operation. A handoff is one-to-one with its diverted triage and is retrievable either from the visit or from the triage assessment. An `INAPPROPRIATE` submission sets the band to `NON_ACUTE`, moves the visit to the terminal `DECLINED` state, and decrements the market's `open_visit_count` by one.


### 3.4. Care Teams, Vehicle Shifts, and Dispatch Selection

Field capacity is organized into **CareTeam** rosters. A `Dispatcher` rosters a team by naming its home `market_id`, the `app_user_id` of the advanced practice provider, the `tech_user_id` of the field technician, the `supervising_physician_user_id` of the remote physician overseeing the team, and a `skill_tags` list drawn from `POCT`, `IMAGING`, `IV_INFUSION`, and `PEDIATRIC`. A new team is `ROSTERED`. A `Dispatcher` moves a rostered team to `AVAILABLE` (going available from any other state is rejected with `ERR_TEAM_INVALID_STATE`), and may move an `AVAILABLE` team to `OFF_DUTY` only when its `active_dispatch_count` is zero — sending a team off duty with work in flight is rejected with `ERR_TEAM_HAS_ACTIVE_DISPATCH` (HTTP 409). The computed `active_dispatch_count` tallies the team's dispatch assignments currently in `OFFERED`, `ACCEPTED`, `EN_ROUTE`, or `ARRIVED`. The team status moves on its own: when the first dispatch is created for an `AVAILABLE` team the team becomes `ON_DISPATCH`, and when its `active_dispatch_count` falls back to zero the team returns to `AVAILABLE`. Team lists support filtering by `market_id` and `status`.

Each team works from a vehicle on a **VehicleShift**. A `Dispatcher` schedules a shift with the `care_team_id`, the `market_id` the vehicle will cover, the `vehicle_plate`, and a half-open window from `window_start` up to but not including `window_end`; a `window_end` at or before `window_start` is rejected with `ERR_SHIFT_WINDOW_INVALID` (HTTP 400). Two shifts for the same care team may not overlap — the system tests half-open intersection of their windows, and an overlap is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409). A shift is created `SCHEDULED`. Starting it requires the logical clock to sit inside the window — at or after `window_start` and strictly before `window_end` — and rejects otherwise with `ERR_SHIFT_WINDOW_NOT_OPEN` (HTTP 409), moving the shift to `ACTIVE`. A `Dispatcher` may extend an `ACTIVE` shift by supplying a `new_window_end` strictly later than the current `window_end`, moving the shift to `EXTENDED`. A `SCHEDULED` shift may be cancelled outright. Closing is permitted from `ACTIVE` or `EXTENDED` but only when the operating team's `active_dispatch_count` is zero (`ERR_TEAM_HAS_ACTIVE_DISPATCH` otherwise). At close the shift computes `overtime_minutes` as the whole minutes by which the logical clock has passed the (possibly extended) `window_end`, floored at zero — a close before the window ends yields zero overtime. When overtime is positive the shift also reports a `shift_premium_cents` figure at a rate of 75 cents per overtime minute; with zero overtime the premium is zero.

Dispatch itself is a selector policy, invoked by a `Dispatcher` requesting a dispatch offer against a visit in `TRIAGED`. The request must carry `expected_visit_request_version`; a mismatch against the visit's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) before any selection runs. The visit's market must still be active (`ERR_MARKET_INACTIVE`). The selector then builds a candidate pool: care teams whose `market_id` equals the visit's market, whose status is `AVAILABLE`, whose `active_dispatch_count` is zero, for which a vehicle shift exists in the same market with status `SCHEDULED` or `ACTIVE` and a window containing the logical clock (at or after `window_start`, strictly before `window_end`), and whose `skill_tags` cover the visit's required skills. Required skills always include `POCT`; they additionally include `IMAGING` when the visit's `chief_complaint` mentions "injury" or "fall", and `IV_INFUSION` when it mentions "dehydrat". When the visit requires `IMAGING` or `IV_INFUSION`, teams missing any required skill are excluded from the pool entirely; when the visit requires only `POCT`, every otherwise-eligible team qualifies, since every rostered team carries `POCT`. An empty pool refuses the offer with `ERR_NO_AVAILABLE_CARE_TEAM` (HTTP 409).

Each candidate is scored: start from 1000, subtract 100 per active dispatch (the `active_dispatch_count` term is zero for every pool member by construction but is part of the scoring rule), and subtract the whole minutes elapsed between the team's `updated_at` — the timestamp of its most recent transition into `AVAILABLE` — and the logical clock. Higher score wins; ties are broken deterministically by the team's earlier `created_at`, never by id (the team's `id` plays no part in tie-breaking). The winning team's `selection_score` is recorded on the resulting **DispatchAssignment**, which is created in `OFFERED` status with `offered_at` stamped from the logical clock, linked to the `visit_request_id`, the chosen `care_team_id`, and the `vehicle_shift_id` of the shift that made the team eligible. The offer's side effects land in one transaction: the team's `active_dispatch_count` rises by one, an `AVAILABLE` team flips to `ON_DISPATCH`, the visit moves to `DISPATCH_PENDING`, and the visit's `version` increments.

The team's answer comes from a `CareTeamMember` whose `X-User-ID` matches the assigned team's `app_user_id` or `tech_user_id`; any other user attempting acceptance, rejection, or arrival is rejected with `ERR_NOT_ASSIGNED_TEAM_MEMBER` (HTTP 403), a check applied after the assignment's state guard has passed. Acceptance requires the assignment to be `OFFERED` (`ERR_DISPATCH_INVALID_STATE`, HTTP 409, otherwise) and the referenced vehicle shift to be operational — `SCHEDULED` or `ACTIVE` with the logical clock inside its window — else `ERR_SHIFT_NOT_OPERATIONAL` (HTTP 409). Acceptance stamps `accepted_at` from the logical clock, moves the assignment through `ACCEPTED` into `EN_ROUTE` as a composite transition, writes the team's id onto the visit's `assigned_care_team_id`, computes the visit's `sla_deadline_at` as `accepted_at` plus the market's `response_window_minutes_urgent` when the visit's `acuity_band` is `URGENT` or `response_window_minutes_standard` otherwise (no `EMERGENT` window exists, because emergent visits are diverted before dispatch), and moves the visit to `EN_ROUTE`. Rejection from `OFFERED` moves the assignment to `REJECTED`, decrements the team's `active_dispatch_count` (returning a zeroed team to `AVAILABLE`), and returns the visit to `TRIAGED` — the `DISPATCH_PENDING`-to-`TRIAGED` loop may cycle as often as needed until a team accepts. A `Dispatcher` may likewise cancel an `OFFERED` assignment, which moves it to `CANCELLED`, applies the same team-counter decrement, and returns the visit to `TRIAGED`. When every dispatch assignment for a visit has ended `CANCELLED` or `REJECTED`, the visit's `assigned_care_team_id` is cleared.

Arrival on scene, again by the assigned `CareTeamMember`, requires the assignment to be `EN_ROUTE`. It moves the assignment to `ARRIVED`, creates the visit's **OnSiteEncounter** in `STARTED` status with `started_at` stamped from the logical clock, and moves the visit to `ON_SCENE`. At that moment the SLA latch is evaluated once: if the encounter's `started_at` is strictly after the visit's `sla_deadline_at`, the visit's `sla_breached` is set true and stays true; an arrival exactly at the deadline is not a breach, because the comparison is strictly greater-than.

### 3.5. On-Scene Encounters and Diagnostics

The **OnSiteEncounter** is one-to-one with its visit and records `visit_request_id` and the `dispatch_assignment_id` of the `ARRIVED` dispatch that produced it; its `ended_at` stays null until a disposition is recorded. The `AdvancedPracticeProvider` drives the encounter. From `STARTED`, the APP places **DiagnosticOrder** items against the encounter; the first order moves the encounter from `STARTED` to `DIAGNOSTICS`. An order carries an `order_kind` of `POCT`, `IMAGING`, or `IV_INFUSION`, a `code` identifying the test, study, or drug (for example "POCT-STREP-A", "XR-CHEST-2V", or "IVF-NS-1L"), a `units` count of at least one, and — for formulary-flagged drugs — the pre-authorization fields `physician_preauth_obtained` and `physician_preauth_by`. Creating an order against an encounter not in `STARTED` or `DIAGNOSTICS` is rejected with `ERR_ENCOUNTER_INVALID_STATE` (HTTP 409).

Intravenous orders carry two guards evaluated at creation. First, the per-visit cap: the total units across every intravenous order for the encounter sharing the same drug code — counting orders in `ORDERED`, `COLLECTED`, `RESULTED`, `VERIFIED`, and `AMENDED` alike — must not exceed the formulary entry's `max_units_per_visit` for the applicable payer contract; a breach is rejected with `ERR_FORMULARY_CAP_EXCEEDED` (HTTP 422). Second, pre-authorization: when the formulary entry's `requires_physician_preauth` is true, the order must carry `physician_preauth_obtained` set true and a `physician_preauth_by` equal to the care team's `supervising_physician_user_id`; a missing or mismatched authorization is rejected with `ERR_PREAUTH_REQUIRED` (HTTP 422). Conversely, `physician_preauth_by` is required if and only if `physician_preauth_obtained` is true.

An order's working lifecycle runs `ORDERED` to `COLLECTED` to `RESULTED`. The `FieldTechnician` collects the specimen or performs the imaging from `ORDERED`, then results the order from `COLLECTED` by supplying a `result_value`; a result submission without a `result_value` is rejected with `ERR_RESULT_REQUIRED` (HTTP 400). At the moment an order is resulted, the system resolves its `unit_price_cents` — from the formulary's `unit_price_cents` for an `IV_INFUSION` order, or from a fixed price list keyed by `code` for `POCT` and `IMAGING` — and computes `line_amount_cents` as the units multiplied by the unit price, rounded half-up to integer cents. If a claim already exists for the visit, both of its totals are recomputed in the same operation (see §3.7). A resulted order may be amended by the same `FieldTechnician` supplying a different `result_value`; submitting an identical value is rejected with `ERR_AMEND_NO_CHANGE` (HTTP 422). Amendment moves the order to `AMENDED`, and a subsequent re-result — which is accepted directly from `AMENDED` — moves it back to `RESULTED` with the unit price re-resolved and the line amount recomputed; the `RESULTED`-to-`AMENDED`-to-`RESULTED` cycle may repeat. The system also records, on the order, the id of the `FieldTechnician` who resulted it (as `resulted_by`). A `SupervisingPhysician` verifies a `RESULTED` order, moving it to `VERIFIED`, with segregation of duties enforced: the verifying user's id must differ from the id of the technician who resulted the order, else `ERR_SOD_VIOLATION` (HTTP 403). An APP may cancel an order only while it is still `ORDERED`; cancellation moves it to `CANCELLED` and, when a claim exists, recomputes the claim's provisional total so the cancelled line drops out. The error catalogue defines no order-specific invalid-state code; any collect, result, verify, amend, or cancel action attempted against an order in a state from which that action is not defined is rejected with `ERR_ENCOUNTER_INVALID_STATE` (HTTP 409) — the same code the encounter state machine uses — since the order's lifecycle is a subordinate of its encounter's.

When the clinical picture is complete, the APP begins disposition review. The encounter must be in `STARTED` or `DIAGNOSTICS`, and every diagnostic order on the encounter must already sit in `RESULTED`, `VERIFIED`, `AMENDED`, or `CANCELLED`; any order still in `ORDERED` or `COLLECTED` blocks the review with `ERR_UNRESOLVED_DIAGNOSTICS` (HTTP 409). An encounter with zero orders may pass directly from `STARTED` into `DISPOSITION_REVIEW`. The APP may alternatively abort an encounter, but only from `STARTED` with zero diagnostic orders; aborting with any order present is rejected with `ERR_ENCOUNTER_HAS_ORDERS` (HTTP 409). An abort stamps `ended_at`, moves the encounter to `ABORTED`, completes the dispatch assignment, and returns the visit to `TRIAGED`, where it becomes eligible for a fresh dispatch offer; the abort also clears the visit's `assigned_care_team_id`, `sla_deadline_at`, and `sla_breached` fields, since the dispatch that set them no longer exists.

### 3.6. Disposition, Facility Transport, and Escalation

From `DISPOSITION_REVIEW`, the APP records a **DispositionDecision** carrying the `encounter_id`, the `visit_request_id`, a `disposition` of either `DISCHARGE_HOME` or `ESCALATE_TO_FACILITY`, and a free-text clinical `rationale` of at least 20 characters — a shorter rationale is rejected with `ERR_RATIONALE_TOO_SHORT` (HTTP 400). A decision to escalate must also name a `receiving_facility_id`; omitting it on an escalation is rejected with `ERR_FACILITY_REQUIRED` (HTTP 400), while a home discharge has no such requirement. An optional `transport_mode` — one of `GROUND_AMBULANCE`, `PRIVATE_VEHICLE`, or `WHEELCHAIR_VAN` — may be supplied on the decision itself, where it is recorded and carried onto the created `FacilityTransport` (§3.6); it may be omitted, in which case the transport's `transport_mode` is null, and any other supplied value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `decided_at` stamp comes from the logical clock.

A home discharge resolves the episode on the spot. The encounter moves to `DISCHARGED_HOME` with `ended_at` stamped; the visit moves to `DISPOSITIONED`; the dispatch assignment completes, the care team's `active_dispatch_count` falls by one, and a team reaching zero returns to `AVAILABLE`. A `Claim` row is created automatically in `DRAFT` status with both totals computed (see §3.7), and the visit's `claim_id` is pointed at it. Two **MonitoringCheckIn** rows are scheduled automatically at 24 hours and at 72 hours after `ended_at`. A follow-up notice to the patient's PCP is expected to be queued for the visit, and once a `DRAFT` claim exists and the visit's **FollowUpNotice** is sitting in `QUEUED`, the visit advances automatically from `DISPOSITIONED` to `CLAIM_DRAFT`.

An escalation to a facility runs a parallel track. The encounter moves to `ESCALATED_TRANSPORT` with `ended_at` stamped; the visit moves to `ESCALATED_TRANSPORT`; the dispatch assignment completes and the team's counters reconcile exactly as on a home discharge. A `Claim` is still auto-created in `DRAFT` — partial services rendered on scene are billable — but no monitoring schedule is created, because the patient's follow-up now belongs to the receiving facility. A **FacilityTransport** is created in the same operation, linked to the `disposition_decision_id` and `visit_request_id`, carrying a `transport_mode` of `GROUND_AMBULANCE`, `PRIVATE_VEHICLE`, or `WHEELCHAIR_VAN` as recorded on the decision (null when the decision omitted one), stamped `dispatched_at` from the logical clock, with `arrived_at_facility_at` null until arrival. A `Dispatcher` marks the transport arrived, which requires it to still be `DISPATCHED` (`ERR_TRANSPORT_INVALID_STATE`, HTTP 409, otherwise), stamps `arrived_at_facility_at`, moves the transport to `ARRIVED_AT_FACILITY`, and advances the visit from `ESCALATED_TRANSPORT` to `CLAIM_DRAFT`. A `Dispatcher` may instead cancel a `DISPATCHED` transport, which moves it to `CANCELLED` and returns the visit to `ON_SCENE` — the escalation is reversed, while the encounter row itself remains in `ESCALATED_TRANSPORT` for audit.

### 3.7. Claims, Claim Lines, and Adjudication

A **Claim** is never created by hand; it is the system's response to a recorded disposition, one-to-one with its visit, with the `payer_contract_id` resolved at draft time from the patient's `payer_code` together with the visit's market (when several contracts share that payer and market, the most recently created one wins; when none matches, the claim's `payer_contract_id` is null and the claim's totals remain zero). Each claim is composed of **ClaimLine** rows. Every line names its `claim_id`, a `line_kind` of `BASE_VISIT`, `DIAGNOSTIC`, or `IV_DRUG`, a `description` (a human-readable label; the base line reads "Base home visit", and each order line reads as the order kind, the order code, and the unit count — for example `POCT POCT-STREP-A x1`), and — for non-base lines — the `ref_diagnostic_order_id` of the diagnostic order it bills; the reference is null on the base line. Each line's `amount_cents` is computed: the base visit line is the applicable contracted base rate — `urgent_base_rate_cents` when the visit's `acuity_band` is `URGENT`, `standard_base_rate_cents` otherwise — multiplied by the contract's `place_of_service_modifier_pct`, rounded half-up to integer cents; diagnostic and IV-drug lines take their diagnostic order's `line_amount_cents` verbatim (or, while the order is still `ORDERED` or `COLLECTED`, its current price estimate computed the same way). Rounding is per line, then the lines are summed — the system never sums first and rounds the total. The claim line set is regenerated, and the line rows replaced, whenever the totals recompute, so the rows always mirror the current totals.

The claim exposes two totals with different inclusion sets. The `provisional_total_cents` is optimistic: while the claim is in `DRAFT` it sums the base line plus the lines of every diagnostic order in `ORDERED`, `COLLECTED`, `RESULTED`, or `AMENDED`, using each order's current price estimate (formulary price for IV infusion, list price otherwise), and excludes `VERIFIED` and `CANCELLED` orders. The `final_total_cents` is conservative: it sums the base line plus only the orders in `RESULTED`, `VERIFIED`, or `AMENDED`, excluding `CANCELLED`, and it is the figure submitted to the payer. Both totals recompute whenever a diagnostic order is resulted, amended, re-resulted, or cancelled against the visit.

A `BillingSpecialist` submits a `DRAFT` claim — attempting submission from any other state is rejected with `ERR_CLAIM_INVALID_STATE` (HTTP 409). The request must carry `expected_visit_request_version`; a mismatch against the visit's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because a diagnostic order resulted since the specialist last read the visit would silently change `final_total_cents`. Two fiscal-temporal guards then run, cap first and contract-in-force second. The claim's `final_total_cents` must not exceed the contract's `max_claim_cents`; a total strictly above the cap is rejected with `ERR_CLAIM_CAP_EXCEEDED` (HTTP 422), while a total exactly equal to the cap is allowed, because the comparison is strictly greater-than. And the contract must be in force: its status must be `ACTIVE` and its effectiveness window must contain the encounter's `ended_at` — `effective_from` at or before `ended_at`, which is strictly before `effective_to` — else `ERR_CONTRACT_NOT_IN_FORCE` (HTTP 422). A successful submission moves the claim to `SUBMITTED`, stamps `submitted_at` from the logical clock, moves the visit to `CLAIM_SUBMITTED`, and increments the visit's `version`.

Adjudication belongs to the `PayerAdjudicator`, who submits an `outcome` of `PAID` or `DENIED` against a `SUBMITTED` claim. A paid adjudication moves the claim to `ADJUDICATED_PAID`, stamps `adjudicated_at`, and moves the visit to `CLAIM_ADJUDICATED_PAID`; a denial moves the claim to `ADJUDICATED_DENIED`, stamps `adjudicated_at`, and moves the visit to `CLAIM_ADJUDICATED_DENIED`. A `BillingSpecialist` may appeal a denied claim, moving it to `APPEALED` and the visit to `CLAIM_APPEALED`, and may resubmit an appealed claim, which moves the claim back to `SUBMITTED` with a fresh `submitted_at` and the visit back to `CLAIM_SUBMITTED`. The cycle from `SUBMITTED` through denial and appeal back to `SUBMITTED` is bounded: at most two appeal rounds are permitted, and a resubmission attempted beyond the second appeal is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 422). Claim lists support filtering by `visit_request_id`, `payer_contract_id`, and `status`.

### 3.8. Follow-Up, Monitoring, and Readmission Risk

Two obligations outlive the visit itself. The first is communication back to the primary care physician: a `TriageNurse` queues a **FollowUpNotice** against the visit, supplying the `pcp_npi` the notice is routed to — which must equal the patient's recorded `pcp_npi`, else `ERR_PCP_MISMATCH` (HTTP 422) — and a `payload_summary` of at least 40 characters. The notice is created `QUEUED`; a nurse later marks it `SENT` (stamping `sent_at` from the logical clock) or `FAILED`, and either marking attempted from a non-`QUEUED` notice is rejected with `ERR_NOTICE_INVALID_STATE` (HTTP 409). As described in §3.6, a queued notice together with a `DRAFT` claim advances a `DISPOSITIONED` visit to `CLAIM_DRAFT` automatically.

The second obligation is post-visit monitoring. **MonitoringCheckIn** rows are scheduled automatically at disposition — 24 and 72 hours after the encounter's `ended_at` — and a `TriageNurse` may additionally schedule a manual check-in by supplying a `scheduled_at`; each row is created `SCHEDULED` with `completed_at` null. Completing a check-in requires the logical clock to have reached its `scheduled_at` — completing early is rejected with `ERR_CHECKIN_NOT_DUE` (HTTP 409) — and a recorded `outcome` of `STABLE`, `WORSENING`, or `EMERGENT`; the row then moves to `COMPLETED` with `completed_at` stamped. Completing or escalating from a state other than the expected one is rejected with `ERR_CHECKIN_INVALID_STATE` (HTTP 409). A check-in still `SCHEDULED` when the logical clock passes six hours beyond its `scheduled_at` is moved automatically to `MISSED` — this flip is lazy, applied at the start of the next request processed after the threshold — and it does not touch the visit's `sla_breached` latch, which measures a different promise, but it does recompute the visit's monitoring adherence ratio. A nurse may escalate a `MISSED` check-in, moving it to `ESCALATED`.

Escalation paths reopen the care loop. Completing a check-in with outcome `EMERGENT`, or escalating a `MISSED` check-in, automatically creates a new **VisitRequest** for the same patient with `requestor_role` set to `PROVIDER`, in the same market as the originating visit, with a system-composed `chief_complaint` of "Post-visit monitoring escalation", starting fresh in `INTAKE` — the transitive cascade from a post-visit signal into a new episode — and the market's `open_visit_count` rises by one, exactly as it does at ordinary intake. A visit's monitoring adherence ratio is the count of its `COMPLETED` check-ins divided by the count of all its check-in rows regardless of status, exposed as a whole-number percentage rounded half-up, and null when the visit has no check-ins at all.

The visit closes from `CLAIM_ADJUDICATED_PAID`: once every monitoring check-in for the visit sits in `COMPLETED` or `ESCALATED` — none `SCHEDULED`, none `MISSED` — the visit moves automatically to `CLOSED`, terminal, and the market's `open_visit_count` falls by one.

Finally, when an encounter ends — either `DISCHARGED_HOME` or `ESCALATED_TRANSPORT` — the system computes a readmission risk score for the episode, an integer clamped between 0 and 100, built additively: 30 points when the visit's `acuity_band` is `URGENT`; 25 points when the patient's `comorbidity_count` is at least 3; 20 points when any intravenous order on the encounter reached `RESULTED` or `VERIFIED`; 25 points when the disposition was `ESCALATE_TO_FACILITY` (the escalation bump is absent on a home discharge, where the tier typically lands `MEDIUM` or `LOW`); 15 points for a patient aged at least 75; and 10 points when any monitoring check-in on the visit was `MISSED`. The tier mapping places a score of at least 60 in `HIGH` — in which case the follow-up notice's `payload_summary` must mention "high-risk" — a score of at least 30 but below 60 in `MEDIUM`, and anything lower in `LOW`.

## 4. Endpoint Definitions

Operations that create a new resource — a market, contract, formulary entry, patient, care team, vehicle shift, visit request, triage assessment, dispatch offer, follow-up notice, monitoring check-in, diagnostic order, or disposition decision — return `201 Created`. Operations that act on an existing resource without creating a new one — status transitions, submissions, adjudications, completions, and the clock-setting capability — return `200 OK`. List and single-resource retrievals return `200 OK`. Request payloads, response payloads, and side effects are defined by the workflows in §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dh/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/dh/markets` | Create a market coverage area | PlatformAdmin |
| GET | `/dh/markets` | List markets | PlatformAdmin, Dispatcher, TriageNurse, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/markets/{id}` | Get one market | PlatformAdmin, Dispatcher, TriageNurse, BillingSpecialist, PayerAdjudicator |
| POST | `/dh/payer-contracts` | Create a payer contract (DRAFT) | PlatformAdmin |
| GET | `/dh/payer-contracts` | List payer contracts | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/payer-contracts/{id}` | Get one payer contract | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| POST | `/dh/payer-contracts/{id}/activate` | Activate a DRAFT contract | PlatformAdmin |
| POST | `/dh/payer-contracts/{id}/terminate` | Terminate an ACTIVE contract | PlatformAdmin |
| GET | `/dh/payer-contracts/{id}/formulary-entries` | List formulary entries under a contract | PlatformAdmin, BillingSpecialist, AdvancedPracticeProvider |
| POST | `/dh/payer-contracts/{id}/formulary-entries` | Create a formulary entry under a contract | PlatformAdmin |
| POST | `/dh/patients` | Register a patient | PlatformAdmin, TriageNurse |
| GET | `/dh/patients` | List patients | PlatformAdmin, TriageNurse, Dispatcher, BillingSpecialist |
| GET | `/dh/patients/{id}` | Get one patient | PlatformAdmin, TriageNurse, Dispatcher, BillingSpecialist, AdvancedPracticeProvider |
| GET | `/dh/patients/{id}/visit-requests` | List visit requests for a patient | PlatformAdmin, TriageNurse, Dispatcher, BillingSpecialist |
| POST | `/dh/care-teams` | Roster a care team | Dispatcher |
| GET | `/dh/care-teams` | List care teams | PlatformAdmin, Dispatcher, TriageNurse |
| GET | `/dh/care-teams/{id}` | Get one care team | PlatformAdmin, Dispatcher, TriageNurse, AdvancedPracticeProvider |
| POST | `/dh/care-teams/{id}/go-available` | Mark team AVAILABLE | Dispatcher |
| POST | `/dh/care-teams/{id}/go-off-duty` | Mark team OFF_DUTY | Dispatcher |
| POST | `/dh/vehicle-shifts` | Schedule a vehicle shift | Dispatcher |
| GET | `/dh/vehicle-shifts` | List vehicle shifts | PlatformAdmin, Dispatcher |
| GET | `/dh/vehicle-shifts/{id}` | Get one vehicle shift | PlatformAdmin, Dispatcher |
| POST | `/dh/vehicle-shifts/{id}/start` | Start the shift | Dispatcher |
| POST | `/dh/vehicle-shifts/{id}/extend` | Extend window_end | Dispatcher |
| POST | `/dh/vehicle-shifts/{id}/close` | Close the shift; computes overtime | Dispatcher |
| POST | `/dh/vehicle-shifts/{id}/cancel` | Cancel a SCHEDULED shift | Dispatcher |
| POST | `/dh/visit-requests` | Create a visit request (intake) | TriageNurse, Dispatcher |
| GET | `/dh/visit-requests` | List visit requests | PlatformAdmin, Dispatcher, TriageNurse, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/visit-requests/{id}` | Get one visit request | PlatformAdmin, Dispatcher, TriageNurse, BillingSpecialist, PayerAdjudicator, AdvancedPracticeProvider |
| GET | `/dh/visit-requests/{id}/triage-assessments` | List triage assessments for a visit | PlatformAdmin, TriageNurse, Dispatcher |
| GET | `/dh/visit-requests/{id}/dispatch-assignments` | List dispatch assignments for a visit | PlatformAdmin, Dispatcher, TriageNurse |
| GET | `/dh/visit-requests/{id}/follow-up-notices` | List follow-up notices for a visit | PlatformAdmin, TriageNurse |
| GET | `/dh/visit-requests/{id}/monitoring-checkins` | List monitoring check-ins for a visit | PlatformAdmin, TriageNurse |
| GET | `/dh/visit-requests/{id}/ems-handoffs` | List EMS handoffs for a visit | PlatformAdmin, TriageNurse, Dispatcher |
| GET | `/dh/visit-requests/{id}/encounters` | List on-site encounters for a visit | PlatformAdmin, TriageNurse, Dispatcher, AdvancedPracticeProvider |
| GET | `/dh/visit-requests/{id}/disposition-decisions` | List disposition decisions for a visit | PlatformAdmin, TriageNurse, AdvancedPracticeProvider |
| GET | `/dh/visit-requests/{id}/facility-transports` | List facility transports for a visit | PlatformAdmin, TriageNurse, Dispatcher |
| POST | `/dh/visit-requests/{id}/triage-assessments` | Create triage assessment (DRAFT) | TriageNurse |
| POST | `/dh/visit-requests/{id}/dispatch-offers` | Run selector policy and create a dispatch assignment | Dispatcher |
| POST | `/dh/visit-requests/{id}/follow-up-notices` | Queue a follow-up notice to the patient's PCP | TriageNurse |
| POST | `/dh/visit-requests/{id}/monitoring-checkins` | Schedule an extra monitoring check-in | TriageNurse |
| GET | `/dh/triage-assessments/{id}` | Get one triage assessment | PlatformAdmin, TriageNurse, Dispatcher |
| POST | `/dh/triage-assessments/{id}/submit` | Submit triage with an outcome | TriageNurse |
| GET | `/dh/triage-assessments/{id}/ems-handoff` | Fetch the EMS handoff for a diverted triage | PlatformAdmin, TriageNurse, Dispatcher |
| GET | `/dh/dispatch-assignments` | List dispatch assignments | PlatformAdmin, Dispatcher, TriageNurse |
| GET | `/dh/dispatch-assignments/{id}` | Get one dispatch assignment | PlatformAdmin, Dispatcher, TriageNurse, CareTeamMember |
| POST | `/dh/dispatch-assignments/{id}/accept` | Care team accepts an OFFERED dispatch | CareTeamMember |
| POST | `/dh/dispatch-assignments/{id}/reject` | Care team rejects an OFFERED dispatch | CareTeamMember |
| POST | `/dh/dispatch-assignments/{id}/cancel` | Dispatcher cancels an OFFERED dispatch | Dispatcher |
| POST | `/dh/dispatch-assignments/{id}/arrive` | Mark arrival on scene; creates the encounter | CareTeamMember |
| GET | `/dh/encounters` | List encounters | PlatformAdmin, Dispatcher, TriageNurse, AdvancedPracticeProvider |
| GET | `/dh/encounters/{id}` | Get one encounter | PlatformAdmin, Dispatcher, TriageNurse, AdvancedPracticeProvider, SupervisingPhysician |
| GET | `/dh/encounters/{id}/diagnostic-orders` | List diagnostic orders under an encounter | PlatformAdmin, AdvancedPracticeProvider, FieldTechnician, SupervisingPhysician, BillingSpecialist |
| POST | `/dh/encounters/{id}/diagnostic-orders` | Create a diagnostic order | AdvancedPracticeProvider |
| POST | `/dh/encounters/{id}/begin-disposition-review` | Move encounter to DISPOSITION_REVIEW | AdvancedPracticeProvider |
| POST | `/dh/encounters/{id}/disposition-decisions` | Record disposition | AdvancedPracticeProvider |
| POST | `/dh/encounters/{id}/abort` | Abort an encounter with zero orders | AdvancedPracticeProvider |
| GET | `/dh/encounters/{id}/disposition-decisions` | List disposition decisions for the encounter | PlatformAdmin, TriageNurse, AdvancedPracticeProvider |
| GET | `/dh/diagnostic-orders/{id}` | Get one diagnostic order | PlatformAdmin, AdvancedPracticeProvider, FieldTechnician, SupervisingPhysician, BillingSpecialist |
| POST | `/dh/diagnostic-orders/{id}/collect` | Field tech collects the specimen or performs imaging | FieldTechnician |
| POST | `/dh/diagnostic-orders/{id}/result` | Field tech results the order | FieldTechnician |
| POST | `/dh/diagnostic-orders/{id}/verify` | Supervising physician verifies the result | SupervisingPhysician |
| POST | `/dh/diagnostic-orders/{id}/amend` | Field tech amends a RESULTED order | FieldTechnician |
| POST | `/dh/diagnostic-orders/{id}/cancel` | APP cancels an ORDERED diagnostic | AdvancedPracticeProvider |
| GET | `/dh/diagnostic-orders/{id}/claim-lines` | List claim lines referencing this order | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/disposition-decisions/{id}` | Get one disposition decision | PlatformAdmin, TriageNurse, AdvancedPracticeProvider |
| GET | `/dh/disposition-decisions/{id}/facility-transport` | Get the facility transport for an escalation decision | PlatformAdmin, Dispatcher, TriageNurse |
| POST | `/dh/facility-transports/{id}/mark-arrived` | Mark facility transport arrived | Dispatcher |
| POST | `/dh/facility-transports/{id}/cancel` | Cancel a DISPATCHED transport | Dispatcher |
| GET | `/dh/claims` | List claims | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/claims/{id}` | Get one claim | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| GET | `/dh/claims/{id}/claim-lines` | List claim lines under a claim | PlatformAdmin, BillingSpecialist, PayerAdjudicator |
| POST | `/dh/claims/{id}/submit` | Submit a DRAFT claim | BillingSpecialist |
| POST | `/dh/claims/{id}/adjudicate` | Payer adjudicates a SUBMITTED claim | PayerAdjudicator |
| POST | `/dh/claims/{id}/appeal` | Appeal a DENIED claim | BillingSpecialist |
| POST | `/dh/claims/{id}/resubmit` | Resubmit an APPEALED claim | BillingSpecialist |
| GET | `/dh/follow-up-notices/{id}` | Get one follow-up notice | PlatformAdmin, TriageNurse |
| POST | `/dh/follow-up-notices/{id}/mark-sent` | Mark a QUEUED notice as SENT | TriageNurse |
| POST | `/dh/follow-up-notices/{id}/mark-failed` | Mark a QUEUED notice as FAILED | TriageNurse |
| GET | `/dh/monitoring-checkins/{id}` | Get one monitoring check-in | PlatformAdmin, TriageNurse |
| POST | `/dh/monitoring-checkins/{id}/complete` | Complete a check-in with an outcome | TriageNurse |
| POST | `/dh/monitoring-checkins/{id}/escalate` | Escalate a MISSED check-in | TriageNurse |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 where the guarded workflow is described; this table is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VR_INVALID_STATE` | 409 Conflict |
| `ERR_TRIAGE_NOT_DRAFT` | 409 Conflict |
| `ERR_TRIAGE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_RED_FLAG_REQUIRES_EMS` | 422 Unprocessable Entity |
| `ERR_ACUITY_TOO_HIGH_FOR_DECLINE` | 422 Unprocessable Entity |
| `ERR_ACUITY_TOO_LOW_FOR_DIVERSION` | 422 Unprocessable Entity |
| `ERR_MARKET_INACTIVE` | 409 Conflict |
| `ERR_OUT_OF_COVERAGE` | 422 Unprocessable Entity |
| `ERR_NO_AVAILABLE_CARE_TEAM` | 409 Conflict |
| `ERR_SHIFT_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_SHIFT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_TEAM_HAS_ACTIVE_DISPATCH` | 409 Conflict |
| `ERR_NOT_ASSIGNED_TEAM_MEMBER` | 403 Forbidden |
| `ERR_DISPATCH_INVALID_STATE` | 409 Conflict |
| `ERR_ENCOUNTER_INVALID_STATE` | 409 Conflict |
| `ERR_ENCOUNTER_HAS_ORDERS` | 409 Conflict |
| `ERR_UNRESOLVED_DIAGNOSTICS` | 409 Conflict |
| `ERR_FORMULARY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PREAUTH_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RESULT_REQUIRED` | 400 Bad Request |
| `ERR_AMEND_NO_CHANGE` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_FACILITY_REQUIRED` | 400 Bad Request |
| `ERR_RATIONALE_TOO_SHORT` | 400 Bad Request |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_IN_FORCE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_APPEAL_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_CHECKIN_NOT_DUE` | 409 Conflict |
| `ERR_CHECKIN_INVALID_STATE` | 409 Conflict |
| `ERR_PCP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRANSPORT_INVALID_STATE` | 409 Conflict |
| `ERR_NOTICE_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_INVALID_STATE` | 409 Conflict |
| `ERR_TEAM_INVALID_STATE` | 409 Conflict |
| `ERR_MARKET_CODE_TAKEN` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
