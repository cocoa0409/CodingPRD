# Pop-Up Free Clinic Event Operations & Volunteer Licensing API — Product Requirements Document

## 1. Introduction

Remote Area Medical-style pop-up free clinics compress an entire health-delivery operation into a single day on a borrowed venue: an arena, a fairground, or a school gymnasium is converted overnight into a field hospital where patients begin queueing before dawn. The operational stakes are unusually high. A dental chair that is not sterilization-cleared cannot serve anyone; a volunteer dentist licensed in the wrong state cannot legally treat; a ticket issued past capacity turns into a family turned away at the door; and every patient who cannot be seen must be documented so that unmet demand is visible to the community partners who inherit the follow-up work. The software that coordinates such an event cannot be a loose collection of forms — it must enforce, at the API level, the gating logic that keeps the event safe, legal, and fair.

This document specifies the **Pop-Up Free Clinic Event Operations & Volunteer Licensing API**. The system models an event's lifecycle as a posture machine: each `ClinicEvent` progresses from `PLANNING` through `SITE_LOCKED`, `STAFFING`, `READY`, `IN_SERVICE`, and `TEARDOWN` to either `CLOSED` or `CANCELLED`, and the current posture gates which child operations are permitted at any moment. Around that spine, the API manages venue vetting and host agreements with liability caps and cost-share computation, volunteer recruitment across the `DENTAL`, `VISION`, `MEDICAL`, and `GENERAL` disciplines with per-event license verification and state practice authorization, a fairness-preserving patient ticket queue with hard capacity ceilings, service stations with throughput-driven capacity projection, equipment manifests and sterilization cycles, one-time patient encounters with referral bundles, unmet-demand reporting, and the final community handoff. All resources are mounted under the `/clinic-events` API surface described in §4.

The audience for this document is the engineering team building the service. Every rule in §2 and §3 is a contract: where the prose states a threshold, a rounding rule, or a transition precondition, the implementation must match it exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role. A request that arrives without these headers, or with a malformed or unrecognized role value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the authorized list for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly nine roles, spelled as follows: `EventDirector`, `LogisticsCoordinator`, `VolunteerCoordinator`, `CredentialingOfficer`, `QueueMarshal`, `StationLead`, `SterilizationTech`, `CommunityPartnerRep`, and `PlatformAdmin`. The `EventDirector` owns the event lifecycle itself — opening doors, ending service, closing or cancelling the event, confirming or rejecting host agreements, generating unmet-demand reports, and assembling handoff packets. The `LogisticsCoordinator` owns venues, agreement drafting and submission, station layout, and equipment manifests. The `VolunteerCoordinator` owns volunteer registration, verification requests, authorization, suspension, reinstatement, and rostering. The `CredentialingOfficer` approves or denies license verifications and is deliberately segregated from the `VolunteerCoordinator`: the coordinator who requests a verification can never be the one who approves it. The `QueueMarshal` runs patient intake and the fair queue. The `StationLead` runs clinical service delivery at stations — marking stations operational, beginning service on tickets, completing or abandoning encounters, and checking in assigned volunteers. The `SterilizationTech` runs sterilization cycles and is segregated from the `StationLead`: the lead who serves patients cannot also certify sterilization. The `CommunityPartnerRep` accepts or disputes the referral handoff on behalf of the receiving partner organization. The `PlatformAdmin` is an operator role that controls the server's logical clock and holds global read access.

All nine roles are **opaque** identities: the `X-User-ID` value is an operator identifier not tied to any persisted entity in this system. The server may record it for audit purposes, but it never compares `X-User-ID` against any resource's `id` for ownership checks. Authorization is purely role-based, per the matrix implied by §4.

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

List endpoints accept two query parameters: `limit`, the maximum number of items to return, and `offset`, the number of items to skip. When `limit` is omitted it defaults to 10; its minimum permitted value is 1 and its maximum permitted value is 100. When `offset` is omitted it defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Event Posture as the Master Gate

The `ClinicEvent` carries a derived `posture` field whose value is always one of `PLANNING`, `SITE_LOCKED`, `STAFFING`, `READY`, `IN_SERVICE`, `TEARDOWN`, `CLOSED`, or `CANCELLED`. This posture is the master gate for the whole event: nearly every child operation — drafting an agreement, setting up a station, issuing a ticket, dismantling a lane — is permitted only when the parent event's posture allows it, and a forbidden attempt is rejected with `ERR_EVENT_POSTURE_FORBIDS` (HTTP 409). The event's *own* posture moves are different: when `open-doors`, `end-service`, `close`, or `cancel` is attempted while the event is not in the required from-posture (`READY`, `IN_SERVICE`, `TEARDOWN`, or a pre-service posture respectively), the failure is a from-state failure on the event itself and is reported as `ERR_INVALID_STATE` (HTTP 409) rather than `ERR_EVENT_POSTURE_FORBIDS`; `ERR_EVENT_POSTURE_FORBIDS` is reserved for child operations gated on the parent event's posture. Two posture moves are operator-driven (opening doors and ending service, closing, and cancelling); the remaining forward moves — `PLANNING` to `SITE_LOCKED`, `SITE_LOCKED` to `STAFFING`, and `STAFFING` to `READY` — are computed by the server automatically whenever the child aggregates that feed them change. Because posture is recomputed on every child mutation, a suspension that erodes authorized coverage can also move an event *backwards*, regressing `READY` to `STAFFING` when the coverage floor is no longer met. Every posture change increments the event's `version` and refreshes its `updated_at`.

### 2.5. Common Resource Properties

Most resources in this API carry the standard system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` advances on every mutation. `version` is an integer that starts on creation and increments on every mutation, including mutations caused by derived-field reconciliation — recomputing a `ClinicEvent`'s counters or posture counts as a mutation and therefore bumps its `version` and `updated_at`.

Two resources deliberately deviate from this convention: `ReferralRecord` and `UnmetDemandReport` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these two resources, because referral records are written once inside an encounter-completion bundle and unmet-demand reports are append-only snapshots that are never modified after generation.

### 2.6. Hierarchical Validation and Nested Resource Retrieval

Many endpoints address a child resource through its parent — a station within an event, a license verification within a volunteer, a ticket within an event. When a request path contains multiple identifiers, the server validates them left to right: the event identifier is checked before the station identifier, the volunteer identifier before the license verification identifier, and so on. The first identifier in the path that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no later validation is attempted. `ERR_NOT_FOUND` is reserved for these missing *path* identifiers: a foreign-key target named in the request *body* that does not exist (or sits in an incompatible state) is instead a referential-integrity failure reported as `ERR_REFERENCE_INVALID`, per the priority order below. Only after every path-referenced resource exists does the server evaluate state and business rules.

More generally, validation on any endpoint runs in a fixed priority order. Authentication and role authorization come first (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`), then path existence (`ERR_NOT_FOUND`), then the parent event's posture gate (`ERR_EVENT_POSTURE_FORBIDS`), then the target resource's own from-state (`ERR_INVALID_STATE`, HTTP 409). Only after those gates pass do business checks run: clinical safety and state-practice rules, the sterilization gate, temporal windows, capacity and resource constraints, referential integrity, and fiscal rules. Referential integrity requires that every foreign-key target named in a request exists and sits in a compatible state — the referenced site must be `VETTED` when an agreement is confirmed, a station must belong to the event under which it is addressed, the treating volunteer must be `AUTHORIZED` when service begins, and an agreement's supersede target must itself be `CONFIRMED`; a target that is missing or in an incompatible state is rejected with `ERR_REFERENCE_INVALID`. Optimistic-concurrency staleness (`ERR_STALE_VERSION`) is checked last among the validation categories, so that a request which fails a cheaper state or posture check reports that failure rather than a version mismatch.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the parent `ClinicEvent`'s `version`. Both require the client to supply `expected_event_version` carrying the event `version` the client last observed; if the event's current `version` has advanced past that value — because another agreement was confirmed, another volunteer was suspended, a posture recompute fired, or any other mutation occurred — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The first guarded write is the creation of a new host agreement for an event. A stale writer here could silently miss the fact that a prior agreement was confirmed in the interim, which legitimately locks the site selection, so the rejection protects that serialization point. The second guarded write is the authorization of a volunteer for an event. The coverage gate that lifts an event into `READY` is computed from event aggregates, and an authorization issued against a stale event view could rest on a coverage score that a superseding site agreement or another suspension has already changed. Endpoints not named here do not accept a version field at all.

### 2.8. Money, Thresholds, and Precision

All fiscal amounts are integer cents — `liability_cap_cents` on an agreement and the computed `cost_share_cents` — never fractional currency. Where a calculation produces a fractional intermediate (the surcharge tiers of the host cost-share computation), rounding is round-half-up to whole cents, applied exactly once after the surcharge components are summed; per-bucket rounding is forbidden because it yields different totals. Coverage scoring uses a different precision: the `discipline_coverage_score` is rounded half-up to two decimal places. Queue positions, cycle sequences, batch sizes, and headcounts are plain integers, and the station-throughput projection floors each station's contribution *before* summing, never after.

Two thresholds recur throughout the specification and are stated once here. An autoclave cycle may carry at most 24 instrument kits — `instrument_batch_size` must be at least 1 and at most 24, and a larger request is rejected with `ERR_BATCH_TOO_LARGE`. The sterilization backlog ceiling is 6 pending batches: a sterilization-requiring `OPERATIONAL` station degrades only when the event's pending batch count is strictly greater than 6, so a backlog of exactly 6 leaves stations alone while a backlog of 7 degrades them.

### 2.9. The Logical Clock

Time-gated rules — license expiry relative to an event's `service_date`, verification review expiry — are evaluated against a server-side logical clock, not wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it by submitting a target instant `to_iso8601`; the response echoes the new clock value as `current_utc`. The clock never falls back to wall-clock time on its own. Advancing the clock past an event's `service_date` while a license verification for that event is still `PENDING` transitions that verification to `EXPIRED_REVIEW`.

## 3. Business Logic & Workflows

### 3.1. Venues: From Prospect to Vetted Site

A `LogisticsCoordinator` registers a prospective venue by supplying its `site_name`, a `site_type` of `ARENA`, `FAIRGROUND`, or `SCHOOL`, the two-letter `state_code` where the venue sits, its usable `square_footage`, whether it `has_loading_dock` for equipment transport, its available `power_capacity_kw` in kilowatts, and whether it is `sterilization_capable` — that is, whether the building has the ventilation and water service to host a sterilization suite. A new venue begins life as a `PROSPECT`.

Due diligence moves a `PROSPECT` site to `VETTED`. The vetting action enforces two physical minimums: the venue's `square_footage` must be at least 2000, and its `power_capacity_kw` must be greater than zero. A too-small venue is rejected with `ERR_SITE_TOO_SMALL`; a venue with no usable electrical capacity fails generic validation with `ERR_VALIDATION` (HTTP 400). Vetting increments the site's `version`.

A `VETTED` site may later be retired, moving it to `RETIRED`, but only while no live negotiation depends on it: if any `SiteAgreement` in `DRAFT`, `NEGOTIATING`, or `CONFIRMED` status references the site, the retire is rejected with `ERR_SITE_IN_USE`. Retired sites remain readable for historical reporting.

### 3.2. Creating the Event and Negotiating the Host Agreement

An `EventDirector` creates a `ClinicEvent` by supplying a human-readable unique `event_code` (for example `RAM-2026-APP-01`), a display `name`, the two-letter `host_state_code` where the event will physically be held, the ISO-8601 calendar `service_date` of the single service day, the `doors_open_utc` timestamp at which the patient queue opens (typically pre-dawn), and the `total_patient_capacity` — a hard ceiling on tickets issuable for the event, which must be at least 1. A new event starts in `PLANNING` posture with `confirmed_site_agreement_id` unset and all computed counters — `dental_chair_count`, `vision_lane_count`, `medical_bay_count`, `verified_volunteer_count`, `tickets_issued_count`, `tickets_served_count`, `unmet_demand_count`, `projected_servable_patients`, and `sterilization_cycles_completed` — at zero.

With an event on the books, a `LogisticsCoordinator` drafts a host agreement against it, supplying the `site_id` of the venue being negotiated, the legal `host_org_name` of the host organization (a school board, a fairground authority), the `liability_cap_cents` the host will accept, and the `insurance_certificate_ref` for the certificate of insurance on file. A negative liability cap is a fiscal violation rejected with `ERR_FISCAL_RULE_VIOLATION`. Because agreement creation is OCC-guarded per §2.7, the request must also carry `expected_event_version`; a stale version is rejected with `ERR_STALE_VERSION`. The draft may optionally name a `supersedes_agreement_id` — the identifier of a prior `CONFIRMED` agreement this new one is intended to replace — enabling a create-with-supersede flow for renegotiated venues. On creation, the server computes a provisional `cost_share_cents` for display purposes using the uncapped variant of the cost-share formula, increments the event's `version`, and records the agreement in `DRAFT` status. Draft agreements list under their event and are also reachable through a cross-event filtered listing by `clinic_event_id`, `site_id`, or `status`.

Submission by a `LogisticsCoordinator` moves an agreement from `DRAFT` to `NEGOTIATING`; this is permitted only while the parent event's posture is `PLANNING` or `SITE_LOCKED`, otherwise `ERR_EVENT_POSTURE_FORBIDS`, and only from `DRAFT` itself, otherwise `ERR_INVALID_STATE`. Confirmation is the `EventDirector`'s call and is the most heavily gated move in the venue workflow. Four checks run, in this order: the referenced site must be `VETTED` (otherwise `ERR_SITE_NOT_VETTED`); the site's `state_code` must equal the event's `host_state_code` (otherwise `ERR_SITE_STATE_MISMATCH`); the `insurance_certificate_ref` must be non-empty (otherwise `ERR_INSURANCE_MISSING`); and the parent event's posture must still be `PLANNING` or `SITE_LOCKED`. A confirmed agreement becomes the event's single confirmed site: `confirmed_site_agreement_id` is set to it, the final `cost_share_cents` is computed with the liability cap applied, the event's `version` increments, and the posture recompute fires — the first confirmation lifts the event from `PLANNING` to `SITE_LOCKED`. If the confirmed agreement named a `supersedes_agreement_id` pointing at a prior `CONFIRMED` agreement, that prior agreement is transitioned `CONFIRMED → SUPERSEDED` as part of the same operation and `confirmed_site_agreement_id` is reassigned to the successor. The `EventDirector` may instead reject a `NEGOTIATING` agreement, moving it to `REJECTED`; both `SUPERSEDED` and `REJECTED` are terminal.

The host cost share itself is computed as follows. Every venue type carries a base cost in cents: 800000 for an `ARENA`, 500000 for a `FAIRGROUND`, and 300000 for a `SCHOOL`. On top of the base, a square-footage surcharge applies in ordered tiers. Footage below 10000 square feet adds nothing. Footage from 10000 up to but not including 30000 contributes a partial tier-two factor: the portion of footage above 10000, capped at 20000, divided by 20000, multiplied by 15 percent of the base. Once the venue reaches at least 30000 square feet, a flat tier-three factor of 25 percent of the base applies in full. The surcharge is the base multiplied by the sum of those two factors, rounded half-up to whole cents in a single rounding step. The raw share is the base plus the surcharge, and the persisted `cost_share_cents` is the raw share truncated at the host's `liability_cap_cents` — the cap always applies last. The provisional value shown at draft time skips that truncation, so the provisional figure is always greater than or equal to the final confirmed figure.

### 3.3. Volunteers, License Verification, and State Practice Authorization

A `VolunteerCoordinator` registers each volunteer with a `full_name`, a contact `email` (unique across all volunteers — a duplicate registration is rejected with `ERR_DUPLICATE_EMAIL`, HTTP 409), a `discipline` of `DENTAL`, `VISION`, `MEDICAL`, or `GENERAL`, and the licensing triple `license_number`, `license_state_code`, and `license_expiry_date`. For `GENERAL` volunteers the licensing triple may be empty strings; for any clinical discipline all three must be present. New volunteers start as `REGISTERED`.

Verification is event-specific: a volunteer licensed and verified for one event is not automatically cleared for another, because state practice authorization depends on where the event is held. When a `VolunteerCoordinator` requests verification for a volunteer — permissible from either `REGISTERED` or `VERIFIED` (the latter covering re-verification for a new event) — the request names the target `clinic_event_id` — which must reference an existing event, otherwise `ERR_REFERENCE_INVALID` — and may carry free-text `reviewer_notes`. If the volunteer's discipline is not `GENERAL` and any of `license_number`, `license_state_code`, or `license_expiry_date` is empty, the request fails with `ERR_LICENSE_FIELDS_REQUIRED`. Otherwise the volunteer moves to `VERIFICATION_PENDING` and a `LicenseVerification` is created in `PENDING` status. Each verification carries an `attempt_sequence`: a monotonic counter scoped to the volunteer-and-event pair that starts at 1 on the first request and increments on every subsequent verification request for the same pair. Verification attempts for a volunteer can be listed under that volunteer, and a cross-volunteer filtered listing exists by `volunteer_id`, `clinic_event_id`, or `status`.

Adjudication belongs exclusively to the `CredentialingOfficer`, segregated from the requesting coordinator. Approving a `PENDING` verification requires that the volunteer's `discipline` match the discipline sought — a mismatch is rejected with `ERR_DISCIPLINE_MISMATCH` — and that the volunteer's `license_expiry_date` fall strictly after the linked event's `service_date`; an expired license auto-denies the verification with the denial code `LICENSE_EXPIRED`. On approval the verification moves `PENDING → APPROVED` and the volunteer moves `VERIFICATION_PENDING → VERIFIED`, which recomputes the event's `verified_volunteer_count`, increments the event's `version`, and may fire the posture recompute. Denial moves the verification `PENDING → DENIED` and requires a `denial_code` from the set `LICENSE_EXPIRED`, `STATE_MISMATCH`, `UNVERIFIABLE`, `DISCIPLINE_MISMATCH`; an absent or out-of-enum code fails generic validation. The denial's effect on the volunteer splits by code: `UNVERIFIABLE` and `DISCIPLINE_MISMATCH` are terminal and push the volunteer `VERIFICATION_PENDING → REJECTED`, while `LICENSE_EXPIRED` and `STATE_MISMATCH` leave the volunteer eligible to request verification again — for instance after renewing a license or targeting an event in their licensed state. Finally, if the logical clock advances past the linked event's `service_date` while a verification is still `PENDING`, the verification transitions to `EXPIRED_REVIEW` with no effect on the volunteer's status.

Whether a verification is adjudicated or expires unresolved, the volunteer is never stranded in `VERIFICATION_PENDING`. When a verification is denied under `LICENSE_EXPIRED` or `STATE_MISMATCH` — including the automatic expiry denial on approval — the volunteer returns to the status they held when the verification was requested (`REGISTERED`, or `VERIFIED` when the request was a re-verification for a new event). A denial under `UNVERIFIABLE` or `DISCIPLINE_MISMATCH` moves the volunteer to `REJECTED` regardless of their prior status, as stated above. A verification that lapses into `EXPIRED_REVIEW` leaves the volunteer's status untouched.

A `VERIFIED` volunteer becomes practice-authorized for a specific event when a `VolunteerCoordinator` authorizes them, naming the `clinic_event_id` — which must reference an existing event, otherwise `ERR_REFERENCE_INVALID` — and — because this write is OCC-guarded per §2.7 — the `expected_event_version` they last observed; a stale version is rejected with `ERR_STALE_VERSION`. Authorization enforces the clinical safety rules in order: an `APPROVED` verification must exist for the event (a volunteer with no `APPROVED` verification for the named event is rejected with `ERR_REFERENCE_INVALID`); the volunteer's `license_expiry_date` must be strictly after the event's `service_date`, otherwise `ERR_LICENSE_EXPIRED`; and either the volunteer's `license_state_code` must equal the event's `host_state_code` or the volunteer's discipline must be `GENERAL`, otherwise `ERR_STATE_PRACTICE_FORBIDDEN`. Success moves the volunteer `VERIFIED → AUTHORIZED`, recomputes `verified_volunteer_count` and the event's discipline coverage score, and may fire the posture recompute.

Authorization can be revoked. Suspending an `AUTHORIZED` volunteer requires a `suspension_reason` in the request body (its absence fails generic validation) and the `clinic_event_id` whose assignments are affected — which must reference an existing event, otherwise `ERR_REFERENCE_INVALID` — and moves the volunteer to `SUSPENDED`, recording the reason. Suspension cascades: every `ROSTERED` or `CONFIRMED` `DisciplineAssignment` for that volunteer transitions to `RELEASED`, coverage is recomputed, and if the loss of coverage drops the event below its coverage floor the posture regresses from `READY` back to `STAFFING`. A `SUSPENDED` volunteer can be reinstated for a named `clinic_event_id` — which must reference an existing event, otherwise `ERR_REFERENCE_INVALID` — returning them to `VERIFIED`, not directly to `AUTHORIZED` — provided the license verification that originally authorized them remains `APPROVED`; when no `APPROVED` verification for that event remains, the reinstatement fails with `ERR_INVALID_STATE`; reinstatement also recomputes coverage and may fire the posture recompute.

### 3.4. Roster: Discipline Assignments and the Coverage Score

The `VolunteerCoordinator` rosters volunteers onto an event by creating `DisciplineAssignment` rows naming the `volunteer_id`, a `shift_code` of `FULL_DAY`, `MORNING`, or `AFTERNOON`, and optionally a `station_id` pinning the volunteer to a specific station. Assignments begin as `ROSTERED`. Confirmation moves an assignment `ROSTERED → CONFIRMED`; on service day the `StationLead` checks the volunteer in, moving a `CONFIRMED` assignment to `CHECKED_IN`; and release by the coordinator moves a `ROSTERED` or `CONFIRMED` assignment to `RELEASED`. Assignments list under their event and through a cross-event filtered listing by `clinic_event_id`, `volunteer_id`, or `status`; creating or releasing an assignment for an `AUTHORIZED` volunteer recomputes coverage.

Coverage is the gate that turns a staffed event into a ready one. The **discipline coverage score** is computed on every volunteer status mutation and every assignment mutation for the event. For each of the three clinical disciplines, the count of authorized contributors is the number of volunteers whose status is `AUTHORIZED`, whose `discipline` matches, and who hold at least one assignment for the event in `ROSTERED`, `CONFIRMED`, or `CHECKED_IN` status. The station count for a discipline is the number of the event's stations of that `station_type` whose status is `SET_UP`, `STERILIZATION_CLEARED`, `OPERATIONAL`, or `DEGRADED` — stations still `PLANNED` or already `OFFLINE` or `DISMANTLED` do not count. Per-discipline coverage is the authorized count divided by the station count (treating zero stations as a divisor of one), capped at 1.0. The three per-discipline coverages are then combined with fixed demand weights — dental carries weight 0.5, vision 0.3, and medical 0.2 — and the weighted sum is multiplied by 100 and rounded half-up to two decimal places. Weights are never renormalized: a discipline with zero stations simply contributes zero, and the weights sum to 1.0 by construction.

The event's `verified_volunteer_count` counter is a separate, stricter headcount than the coverage numerator: it counts volunteers whose status is `AUTHORIZED` and who hold at least one assignment **for this event** in `CONFIRMED` status — `ROSTERED` and `CHECKED_IN` assignments, assignments on other events, and volunteers in any other status do not count. The counter is derived on read, so it moves immediately whenever a volunteer's status or an assignment's status changes.

An event's coverage floor is 60: the recompute that moves `STAFFING → READY` requires a score of at least 60, and a suspension that drags the score below 60 while the event is `READY` regresses it to `STAFFING`.

### 3.5. Stations, Equipment, and Sterilization

Station layout begins once the site is locked. A `LogisticsCoordinator` plans a `ServiceStation` by supplying a human `station_label` such as `DENTAL-03`, a `station_type` of `TRIAGE`, `DENTAL`, `VISION`, `MEDICAL`, `GLASSES_LAB`, or `DENTURE_LAB`, the parallel `chair_count` (at least 1), the average `minutes_per_patient` (at least 5), whether the station `requires_sterilization` — true for `DENTAL` and `MEDICAL` stations whose instruments must cycle through sterilization between patients — and the service window bounded by `service_window_open_utc` and `service_window_close_utc`. The close must be strictly after the open; an inverted or zero-length window is rejected with `ERR_TEMPORAL_WINDOW_INVALID`. New stations are `PLANNED`, and their creation may fire the posture recompute that moves `SITE_LOCKED → STAFFING`.

Marking a station set up moves it `PLANNED → SET_UP`. This is permitted only while the event's posture is `SITE_LOCKED` or `STAFFING`, and it enforces the venue's electrical budget: the confirmed site's `power_capacity_kw` must cover the sum of the power draw of all stations already set up plus this station's draw, otherwise `ERR_POWER_CAPACITY_EXCEEDED`. Individual station power draw is not a field of the station resource, so stations contribute a zero-kilowatt draw and the budget check can never trip in practice; it is retained as an extension point for deployments that meter per-station draw. From `SET_UP`, the path to `OPERATIONAL` forks on sterilization. A station that does not require sterilization can be marked operational directly by a `StationLead`, provided the event posture is `SITE_LOCKED`, `STAFFING`, `READY`, or `IN_SERVICE`. A station that does require sterilization must first be cleared: when any sterilization cycle for the event completes, every sterilization-requiring station sitting in `SET_UP` transitions automatically to `STERILIZATION_CLEARED`, and only from there can it be marked `OPERATIONAL`. Attempting to bring a sterilization-requiring station online without a completed cycle is rejected with `ERR_STERILIZATION_NOT_CLEARED`. Stations list under their event and through a cross-event filtered listing by `clinic_event_id`, `station_type`, or `status`.

Equipment travels in manifests. A `LogisticsCoordinator` creates an `EquipmentManifest` with a `manifest_label` such as `TRUCK-1`, an `item_count` of at least 1, a gross `weight_kg` greater than zero, a `requires_loading_dock` flag for dock-level unloading, and a `contains_sterilizer` flag marking shipments that include an autoclave. Manifests start as `PACKED`. Shipping moves `PACKED → IN_TRANSIT` and is gated on the event having a confirmed site agreement — posture at least `SITE_LOCKED`, otherwise `ERR_EVENT_POSTURE_FORBIDS` — and, when `requires_loading_dock` is true, on the confirmed site actually having a loading dock, otherwise `ERR_LOADING_DOCK_REQUIRED`. Delivery moves `IN_TRANSIT → DELIVERED`; unpacking moves `DELIVERED → UNPACKED` and, for a manifest with `contains_sterilizer` true, unlocks the ability to start sterilization cycles for the event. Repacking moves `UNPACKED → REPACKED` and is permitted only once the event has reached `TEARDOWN`. Manifests list under their event and through a cross-event filtered listing by `clinic_event_id` or `status`.

A `SterilizationTech` starts a sterilization cycle by supplying the `instrument_batch_size` — the number of instrument kits in the batch, at least 1 and at most 24, with oversize batches rejected as `ERR_BATCH_TOO_LARGE`. Starting a cycle requires an `UNPACKED` manifest with `contains_sterilizer` true to exist for the event. The server stamps `started_utc` and assigns the `cycle_sequence`, a monotonic per-event number whose first value is 1; the cycle runs in `RUNNING` status. Completing a `RUNNING` cycle moves it to `COMPLETED`, stamps `completed_utc`, increments the event's `sterilization_cycles_completed`, clears every sterilization-requiring `SET_UP` station into `STERILIZATION_CLEARED`, and returns any `DEGRADED` station whose backlog has fallen back within the ceiling to `OPERATIONAL`. Failing a cycle moves it to `FAILED` and returns its batch to the pending backlog. Cycles list under their event and through a cross-event filtered listing by `clinic_event_id` or `status`.

The **sterilization backlog** is the count of pending instrument batches for the event: the sum of `instrument_batch_size` over all `RUNNING` cycles, plus batches from `FAILED` cycles that have not yet been resubmitted. Whenever the backlog for an event with a sterilization-requiring `OPERATIONAL` station rises strictly above 6 pending batches, that station degrades automatically to `DEGRADED`; a backlog of exactly 6 does not trigger degradation. A `DEGRADED` station returns to `OPERATIONAL` automatically when a cycle completes and the backlog falls back to 6 or fewer. Degradation halves a station's effective capacity in the throughput projection, as described in §3.7. The `StationLead` may also take a station offline deliberately — from `OPERATIONAL` or `DEGRADED` to `OFFLINE` — but only while no `OPEN` encounter exists at that station, otherwise `ERR_ACTIVE_ENCOUNTERS_REMAIN`. Bringing an `OFFLINE` station back to `OPERATIONAL` re-applies the sterilization gate: if the station requires sterilization, at least one cycle must have completed *since* the station went offline, otherwise `ERR_STERILIZATION_NOT_CLEARED`. Every transition into or out of `OPERATIONAL`, `DEGRADED`, or `OFFLINE` recomputes the event's station counts and its projected servable-patients figure.

### 3.6. Doors Open: Tickets and the Fair Queue

The event's posture advances from `READY` to `IN_SERVICE` when the `EventDirector` opens the doors. Two readiness gates guard this move beyond the posture itself. First, every `EquipmentManifest` for the event must be `UNPACKED`; a manifest still in transit or merely delivered blocks opening with `ERR_MANIFEST_NOT_UNPACKED`. Second, every `DENTAL` or `MEDICAL` station with `requires_sterilization` true must have at least one `COMPLETED` sterilization cycle behind it, otherwise `ERR_STERILIZATION_NOT_CLEARED`.

Once doors are open, pre-dawn intake begins. A `QueueMarshal` issues a `PatientTicket` by recording the opaque `patient_ref` supplied at intake (no PII beyond this reference), the patient's `arrival_utc` timestamp, the `requested_service` — `DENTAL`, `VISION`, or `MEDICAL` — and a `priority_tier` of `STANDARD` or `VULNERABLE`, the latter covering elderly, pregnant, and disabled patients. The patient's arrival must fall within the service day window that begins at `doors_open_utc` and ends 24 hours later — `arrival_utc` must satisfy `doors_open_utc ≤ arrival_utc < doors_open_utc + 24h`; an arrival outside that window is rejected with `ERR_TEMPORAL_WINDOW_INVALID`. Issuance requires the event posture to be `IN_SERVICE` and enforces the capacity ceiling: when `tickets_issued_count` already equals `total_patient_capacity`, further issuance is rejected with `ERR_CAPACITY_EXHAUSTED` — the boundary is inclusive, so issuing at exactly capacity fails. A successfully issued ticket enters `QUEUED` status, the event's `tickets_issued_count` increments, and the ticket receives its `queue_position`, which is immutable thereafter.

Fair sequencing governs both position assignment and the order in which patients are called. At issue time, the new ticket's `queue_position` is one greater than the maximum position ever assigned within this event across tickets in *any* status — including `WITHDRAWN` and `TURNED_AWAY` tickets — so positions are never reused. When the marshal calls the next patient for a given service, the eligible set is the event's `QUEUED` tickets whose `requested_service` matches; the head of the queue is the ticket that sorts first by priority rank, where `VULNERABLE` ranks ahead of `STANDARD`, then by earliest `arrival_utc`, then by earliest `created_at`. The ticket `id` is never used as a tie-breaker. Calling a ticket moves it `QUEUED → CALLED`; the call requires `IN_SERVICE` posture and fails with `ERR_NOT_QUEUE_HEAD` if the named ticket is not the fair-sequence head for its service. Every ticket mutation — call, begin-service, requeue, no-show, withdrawal, and the system-driven transitions out of `IN_SERVICE` and `QUEUED` — increments the ticket's `version` and refreshes its `updated_at`. Only ticket issuance and calling the next patient are gated on `IN_SERVICE` posture; the remaining ticket transitions — begin-service, requeue, no-show, and withdrawal — have no event-posture gate of their own (an attempt from the wrong ticket status still fails with `ERR_INVALID_STATE`, and ending service is separately blocked while any ticket remains `CALLED` or `IN_SERVICE`, per §3.8). Tickets list under their event with filters on `status`, `requested_service`, and `priority_tier`, and through a cross-event filtered listing by `clinic_event_id` or `status`.

A called patient may step away. The marshal can requeue a `CALLED` ticket back to `QUEUED`, but at most once per ticket — a second requeue attempt is rejected with `ERR_REQUEUE_EXHAUSTED`. A requeued ticket re-enters at the tail of the queue: its new `queue_position` is one greater than the current maximum. A called patient who simply never appears is marked `CALLED → NO_SHOW`, which decrements `tickets_issued_count`. A still-queued patient may withdraw, moving `QUEUED → WITHDRAWN`, likewise decrementing `tickets_issued_count`.

Service begins when a `StationLead` begins service on a `CALLED` ticket, supplying the `station_id` and `volunteer_id` performing the service, the `encounter_type` — `TRIAGE`, `EXTRACTION`, `DENTURE_FIT`, `EYE_EXAM`, `GLASSES_DISPENSE`, or `MEDICAL_CONSULT` — a free-text `findings_summary` for the one-time clinical record, and a `requires_followup` flag. Beginning service requires a compatible `OPERATIONAL` station for the ticket's requested service whose service window is open at the server's logical clock — that is, `service_window_open_utc ≤ current logical time ≤ service_window_close_utc` (the close bound is inclusive); otherwise `ERR_NO_STATION_AVAILABLE`. The treating volunteer must be `AUTHORIZED` — a volunteer in any other status is rejected with `ERR_VOLUNTEER_NOT_AUTHORIZED` — with a discipline matching the service; a discipline mismatch is rejected with `ERR_DISCIPLINE_MISMATCH`. On success the ticket moves `CALLED → IN_SERVICE` and a `PatientEncounter` is created in `OPEN` status, linked to the `ticket_id`.

Completing an encounter is the `StationLead`'s close-out. The treating volunteer must still be `AUTHORIZED` at completion time, otherwise `ERR_VOLUNTEER_NOT_AUTHORIZED`; the station must be `OPERATIONAL` or `DEGRADED`, otherwise `ERR_STATION_NOT_SERVING`. When the encounter's `requires_followup` is true, the completion request must bundle at least one referral — submitted via the `referrals` collection in the request — otherwise `ERR_REFERRAL_REQUIRED`. Each bundled referral names its `referral_type` (`DENTAL_FOLLOWUP`, `VISION_FOLLOWUP`, `MEDICAL_FOLLOWUP`, or `URGENT_CARE`), the receiving `partner_org_name`, an `urgency` of `ROUTINE`, `URGENT`, or `EMERGENT`, and free-text `notes`; the server links each referral to the `encounter_id` and the denormalized `clinic_event_id`. Completion moves the encounter `OPEN → COMPLETED`, transitions the ticket `IN_SERVICE → SERVED`, increments the station's `served_count`, increments the event's `tickets_served_count` while decrementing `tickets_issued_count`, and — for follow-up encounters — folds the new referrals into the event's referral packet, recomputing `referral_packet_count` on the relevant handoff. Encounters list under their event with filters on `station_id`, `volunteer_id`, and `status`, and through a cross-event filtered listing by `clinic_event_id` or `ticket_id`; referrals list under their encounter and through a cross-event filtered listing by `clinic_event_id`, `encounter_id`, or `referral_type`.

An encounter can instead be abandoned, moving `OPEN → ABANDONED`. Abandonment sends the patient back to the queue: the ticket transitions `IN_SERVICE → QUEUED` with a fresh tail-of-queue `queue_position`.

### 3.7. Throughput Projection and the Readiness Ledger

The event's headline numbers are derived, not entered. `dental_chair_count`, `vision_lane_count`, and `medical_bay_count` sum the `chair_count` of the event's `OPERATIONAL` stations of the corresponding type. The **projected servable patients** figure is recomputed on every station status mutation and at doors-open, and answers the question: given the stations now standing, how many patients can each discipline serve? For each discipline, the projection considers the event's stations of the matching type whose status is `OPERATIONAL` or `DEGRADED` — stations in any other status are excluded entirely. Each contributing station's effective chair count is its full `chair_count` when `OPERATIONAL`, or half its `chair_count` rounded down when `DEGRADED`. The station's service window length in minutes — the difference between `service_window_close_utc` and `service_window_open_utc` — divided by its `minutes_per_patient` gives patients per chair; multiplying by the effective chairs and rounding the result down yields that station's contribution. The per-station contributions are floored *before* summing — summing raw values and flooring afterwards is forbidden because it yields a different integer — and the event's `projected_servable_patients` is the sum of the three discipline capacities. One deliberate variant exists: when this projection is used inside the posture recompute that gates `READY`, `DEGRADED` stations are counted at their full `chair_count` rather than half, producing an optimistic figure that is strictly larger whenever a degraded station has an odd chair count. The pessimistic base formula — degraded at half capacity — is the one used in unmet-demand reporting.

The recompute machinery ties the whole event together. When the first agreement for an event reaches `CONFIRMED`, posture moves `PLANNING → SITE_LOCKED`. When at least one station exists at `PLANNED` or beyond and at least one license verification exists at `VERIFICATION_PENDING` or beyond for the event, posture moves `SITE_LOCKED → STAFFING`. When no station remains in `PLANNED`, no verification remains `PENDING`, and the discipline coverage score reaches at least 60, posture moves `STAFFING → READY`. Each of these moves increments the event's `version`.

### 3.8. Ending Service, Unmet Demand, and Community Handoff

When the `EventDirector` ends service, the event moves `IN_SERVICE → TEARDOWN`. The move is blocked while any ticket remains `CALLED` or `IN_SERVICE` — those patients are mid-encounter — with `ERR_ACTIVE_ENCOUNTERS_REMAIN`. The end-of-service cascade turns away everyone still waiting: every `QUEUED` ticket transitions to `TURNED_AWAY` with `turn_away_reason` set to `EVENT_ENDED`, which — because `tickets_issued_count` counts only `QUEUED`, `CALLED`, and `IN_SERVICE` tickets — removes those tickets from the outstanding-issued count, and the event's `unmet_demand_count` is recomputed. Tickets can also be turned away at intake time when capacity is exhausted; in that case the `turn_away_reason` is `CAPACITY_EXHAUSTED`. In both paths the event's `unmet_demand_count` — the count of `TURNED_AWAY` tickets — reflects the loss.

Documenting what the event could *not* serve is a first-class deliverable. The `EventDirector` generates an `UnmetDemandReport` by naming a `report_variant` of `OBSERVED_ONLY` or `WITH_EXTRAPOLATION`; reports are append-only snapshots, stamped with `generated_at_utc`, listable under their event, and never modified after creation. Each report snapshots `turned_away_count` at generation time. In the `OBSERVED_ONLY` variant, `estimated_unserved_beyond_queue` is zero and the `projected_shortfall_patients` is the observed turn-away count plus any capacity gap. In the `WITH_EXTRAPOLATION` variant, the report extrapolates demand that never reached ticketing: the extrapolation factor is one plus the ratio of tickets still `QUEUED` at the end-of-service cascade to the event's `tickets_served_count` (with a served count of zero treated as one to keep the ratio defined). "Tickets still `QUEUED` at the end-of-service cascade" is evaluated at report-generation time: it counts every ticket the cascade would have swept — that is, tickets currently in `QUEUED` status plus tickets already turned away by the cascade (`TURNED_AWAY` with `turn_away_reason` `EVENT_ENDED`). Because a report generated after service has ended sees no live `QUEUED` tickets, the swept `EVENT_ENDED` turn-aways are what keep the extrapolation non-trivial; a report generated before service ends instead extrapolates from the live queue. The `estimated_unserved_beyond_queue` is then the observed count multiplied by that factor, rounded half-up, minus the observed count itself. The `projected_shortfall_patients` is the observed count plus the extrapolated estimate, plus the amount by which `total_patient_capacity` exceeds the pessimistic `projected_servable_patients` — or zero when the projection meets or exceeds capacity. The extrapolated variant's shortfall is strictly greater than the observed-only variant's whenever any patient was still queued at close.

Teardown itself is enforced through the close gate. Dismantling stations — `OPERATIONAL`, `DEGRADED`, or `OFFLINE` to `DISMANTLED` — is a `LogisticsCoordinator` action permitted only in `TEARDOWN` posture, and it recomputes station counts. Repacking manifests likewise requires `TEARDOWN`. The `EventDirector` then assembles the community handoff: a `CommunityHandoff` is created naming the `partner_org_name` accepting responsibility for follow-ups and a `teardown_checklist_complete` flag recording whether venue teardown is fully signed off, starting in `DRAFT`. Assembling the packet — permitted while the event is `IN_SERVICE` or `TEARDOWN` — moves the handoff `DRAFT → PACKET_ASSEMBLED` and recomputes `referral_packet_count` as the count of referral records for the event. Acceptance belongs to the `CommunityPartnerRep`, who moves `PACKET_ASSEMBLED → ACCEPTED` only when `teardown_checklist_complete` is true, otherwise `ERR_TEARDOWN_INCOMPLETE`; the partner may instead dispute the packet, moving it to `DISPUTED`. Handoffs list under their event and through a cross-event filtered listing by `clinic_event_id` or `status`.

Closing the event — `TEARDOWN → CLOSED` — is the final gate and checks three things: every station must be `DISMANTLED` (otherwise `ERR_STATIONS_NOT_DISMANTLED`), every manifest must be `REPACKED` (otherwise `ERR_MANIFEST_NOT_REPACKED`), and a handoff must exist in `ACCEPTED` status (otherwise `ERR_HANDOFF_NOT_ACCEPTED`). Cancellation is the alternate terminal path: from any pre-service posture — `PLANNING`, `SITE_LOCKED`, `STAFFING`, or `READY` — the `EventDirector` may cancel the event, which moves it to `CANCELLED`, transitions every non-terminal site agreement to `REJECTED`, and releases every `ROSTERED` or `CONFIRMED` assignment to `RELEASED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. List endpoints follow the pagination contract in §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/sites` | Register a prospective venue | LogisticsCoordinator |
| GET | `/sites` | List venues with pagination and optional filters | LogisticsCoordinator, EventDirector, PlatformAdmin |
| GET | `/sites/{id}` | Fetch one venue | LogisticsCoordinator, EventDirector, PlatformAdmin |
| POST | `/sites/{id}/vet` | Mark a PROSPECT site as VETTED | LogisticsCoordinator |
| POST | `/sites/{id}/retire` | Retire a VETTED site not referenced by live agreements | LogisticsCoordinator |
| POST | `/clinic-events` | Create a clinic event in PLANNING posture | EventDirector |
| GET | `/clinic-events` | List events with pagination and optional filters | EventDirector, LogisticsCoordinator, VolunteerCoordinator, CredentialingOfficer, QueueMarshal, StationLead, SterilizationTech, CommunityPartnerRep, PlatformAdmin |
| GET | `/clinic-events/{id}` | Fetch one event including all computed counters | EventDirector, LogisticsCoordinator, VolunteerCoordinator, CredentialingOfficer, QueueMarshal, StationLead, SterilizationTech, CommunityPartnerRep, PlatformAdmin |
| POST | `/clinic-events/{id}/open-doors` | READY → IN_SERVICE; opens the patient queue | EventDirector |
| POST | `/clinic-events/{id}/end-service` | IN_SERVICE → TEARDOWN; cascades queued tickets to turned-away | EventDirector |
| POST | `/clinic-events/{id}/close` | TEARDOWN → CLOSED | EventDirector |
| POST | `/clinic-events/{id}/cancel` | Cancel the event from any pre-service posture | EventDirector |
| POST | `/clinic-events/{id}/site-agreements` | Create a DRAFT host agreement (OCC-guarded; optional supersedes) | LogisticsCoordinator |
| GET | `/clinic-events/{id}/site-agreements` | List agreements for an event | LogisticsCoordinator, EventDirector, PlatformAdmin |
| GET | `/site-agreements` | Filtered list of agreements across events | LogisticsCoordinator, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/site-agreements/{aid}/submit` | DRAFT → NEGOTIATING | LogisticsCoordinator |
| POST | `/clinic-events/{id}/site-agreements/{aid}/confirm` | NEGOTIATING → CONFIRMED; fires supersede cascade and posture recompute | EventDirector |
| POST | `/clinic-events/{id}/site-agreements/{aid}/reject` | NEGOTIATING → REJECTED | EventDirector |
| POST | `/volunteers` | Register a volunteer | VolunteerCoordinator |
| GET | `/volunteers` | List volunteers with pagination and optional filters | VolunteerCoordinator, CredentialingOfficer, EventDirector, PlatformAdmin |
| GET | `/volunteers/{id}` | Fetch one volunteer | VolunteerCoordinator, CredentialingOfficer, EventDirector, PlatformAdmin |
| POST | `/volunteers/{id}/request-verification` | Request license verification for a specific event | VolunteerCoordinator |
| GET | `/volunteers/{id}/license-verifications` | List verification attempts for a volunteer | VolunteerCoordinator, CredentialingOfficer, PlatformAdmin |
| GET | `/license-verifications` | Filtered list of verifications across volunteers | VolunteerCoordinator, CredentialingOfficer, PlatformAdmin |
| POST | `/volunteers/{vid}/license-verifications/{id}/approve` | PENDING → APPROVED; volunteer becomes VERIFIED | CredentialingOfficer |
| POST | `/volunteers/{vid}/license-verifications/{id}/deny` | PENDING → DENIED with a denial code | CredentialingOfficer |
| POST | `/volunteers/{id}/authorize` | VERIFIED → AUTHORIZED for a given event (OCC-guarded) | VolunteerCoordinator |
| POST | `/volunteers/{id}/suspend` | AUTHORIZED → SUSPENDED; releases live assignments | VolunteerCoordinator |
| POST | `/volunteers/{id}/reinstate` | SUSPENDED → VERIFIED | VolunteerCoordinator |
| POST | `/clinic-events/{id}/assignments` | Roster a volunteer onto the event (optionally onto a station) | VolunteerCoordinator |
| GET | `/clinic-events/{id}/assignments` | List assignments for an event | VolunteerCoordinator, EventDirector, StationLead, PlatformAdmin |
| GET | `/assignments` | Filtered list of assignments across events | VolunteerCoordinator, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/assignments/{aid}/confirm` | ROSTERED → CONFIRMED | VolunteerCoordinator |
| POST | `/clinic-events/{id}/assignments/{aid}/check-in` | CONFIRMED → CHECKED_IN on service day | StationLead |
| POST | `/clinic-events/{id}/assignments/{aid}/release` | ROSTERED/CONFIRMED → RELEASED | VolunteerCoordinator |
| POST | `/clinic-events/{id}/stations` | Plan a service station | LogisticsCoordinator |
| GET | `/clinic-events/{id}/stations` | List stations for an event | LogisticsCoordinator, EventDirector, StationLead, SterilizationTech, PlatformAdmin |
| GET | `/stations` | Filtered list of stations across events | LogisticsCoordinator, EventDirector, StationLead, PlatformAdmin |
| POST | `/clinic-events/{id}/stations/{sid}/mark-set-up` | PLANNED → SET_UP; checks site power budget | LogisticsCoordinator |
| POST | `/clinic-events/{id}/stations/{sid}/mark-operational` | SET_UP / STERILIZATION_CLEARED / OFFLINE → OPERATIONAL | StationLead |
| POST | `/clinic-events/{id}/stations/{sid}/take-offline` | OPERATIONAL / DEGRADED → OFFLINE | StationLead |
| POST | `/clinic-events/{id}/stations/{sid}/dismantle` | OPERATIONAL / DEGRADED / OFFLINE → DISMANTLED (TEARDOWN only) | LogisticsCoordinator |
| POST | `/clinic-events/{id}/tickets` | Issue a patient ticket at intake | QueueMarshal |
| GET | `/clinic-events/{id}/tickets` | List tickets for an event with filters | QueueMarshal, EventDirector, StationLead, PlatformAdmin |
| GET | `/tickets` | Filtered list of tickets across events | QueueMarshal, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/tickets/{tid}/call` | QUEUED → CALLED; must be the fair-sequence head for its service | QueueMarshal |
| POST | `/clinic-events/{id}/tickets/{tid}/begin-service` | CALLED → IN_SERVICE; creates an OPEN encounter | StationLead |
| POST | `/clinic-events/{id}/tickets/{tid}/requeue` | CALLED → QUEUED (once only); tail-of-queue position | QueueMarshal |
| POST | `/clinic-events/{id}/tickets/{tid}/mark-no-show` | CALLED → NO_SHOW | QueueMarshal |
| POST | `/clinic-events/{id}/tickets/{tid}/withdraw` | QUEUED → WITHDRAWN | QueueMarshal |
| GET | `/clinic-events/{id}/encounters` | List encounters for an event | StationLead, EventDirector, PlatformAdmin |
| GET | `/encounters` | Filtered list of encounters across events | StationLead, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/encounters/{eid}/complete` | OPEN → COMPLETED; requires a referral bundle when follow-up is needed | StationLead |
| POST | `/clinic-events/{id}/encounters/{eid}/abandon` | OPEN → ABANDONED; ticket returns to the queue tail | StationLead |
| GET | `/clinic-events/{id}/encounters/{eid}/referrals` | List referrals for an encounter | StationLead, EventDirector, CommunityPartnerRep, PlatformAdmin |
| GET | `/referrals` | Filtered list of referrals | StationLead, EventDirector, CommunityPartnerRep, PlatformAdmin |
| POST | `/clinic-events/{id}/manifests` | Create an equipment manifest (PACKED) | LogisticsCoordinator |
| GET | `/clinic-events/{id}/manifests` | List manifests for an event | LogisticsCoordinator, EventDirector, PlatformAdmin |
| GET | `/manifests` | Filtered list of manifests across events | LogisticsCoordinator, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/manifests/{mid}/ship` | PACKED → IN_TRANSIT; loading-dock check against the confirmed site | LogisticsCoordinator |
| POST | `/clinic-events/{id}/manifests/{mid}/deliver` | IN_TRANSIT → DELIVERED | LogisticsCoordinator |
| POST | `/clinic-events/{id}/manifests/{mid}/unpack` | DELIVERED → UNPACKED; unlocks sterilization when a sterilizer is aboard | LogisticsCoordinator |
| POST | `/clinic-events/{id}/manifests/{mid}/repack` | UNPACKED → REPACKED (TEARDOWN only) | LogisticsCoordinator |
| POST | `/clinic-events/{id}/sterilization-cycles` | Start a sterilization cycle (RUNNING) | SterilizationTech |
| GET | `/clinic-events/{id}/sterilization-cycles` | List cycles for an event | SterilizationTech, StationLead, EventDirector, PlatformAdmin |
| GET | `/sterilization-cycles` | Filtered list of cycles across events | SterilizationTech, EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/sterilization-cycles/{cid}/complete` | RUNNING → COMPLETED; clears stations and backlog | SterilizationTech |
| POST | `/clinic-events/{id}/sterilization-cycles/{cid}/fail` | RUNNING → FAILED; batch returns to the backlog | SterilizationTech |
| POST | `/clinic-events/{id}/unmet-demand-reports` | Generate an unmet demand report snapshot (append-only) | EventDirector |
| GET | `/clinic-events/{id}/unmet-demand-reports` | List reports for an event | EventDirector, PlatformAdmin |
| POST | `/clinic-events/{id}/handoffs` | Create a community handoff (DRAFT) | EventDirector |
| GET | `/clinic-events/{id}/handoffs` | List handoffs for an event | EventDirector, CommunityPartnerRep, PlatformAdmin |
| GET | `/handoffs` | Filtered list of handoffs across events | EventDirector, CommunityPartnerRep, PlatformAdmin |
| POST | `/clinic-events/{id}/handoffs/{hid}/assemble-packet` | DRAFT → PACKET_ASSEMBLED; recomputes the referral packet count | EventDirector |
| POST | `/clinic-events/{id}/handoffs/{hid}/accept` | PACKET_ASSEMBLED → ACCEPTED; requires teardown checklist complete | CommunityPartnerRep |
| POST | `/clinic-events/{id}/handoffs/{hid}/dispute` | PACKET_ASSEMBLED → DISPUTED | CommunityPartnerRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVENT_POSTURE_FORBIDS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SITE_NOT_VETTED` | 422 |
| `ERR_SITE_STATE_MISMATCH` | 422 |
| `ERR_SITE_TOO_SMALL` | 422 |
| `ERR_SITE_IN_USE` | 422 |
| `ERR_INSURANCE_MISSING` | 422 |
| `ERR_LICENSE_FIELDS_REQUIRED` | 422 |
| `ERR_LICENSE_EXPIRED` | 422 |
| `ERR_STATE_PRACTICE_FORBIDDEN` | 422 |
| `ERR_DISCIPLINE_MISMATCH` | 422 |
| `ERR_VOLUNTEER_NOT_AUTHORIZED` | 422 |
| `ERR_CAPACITY_EXHAUSTED` | 422 |
| `ERR_NOT_QUEUE_HEAD` | 422 |
| `ERR_REQUEUE_EXHAUSTED` | 422 |
| `ERR_NO_STATION_AVAILABLE` | 422 |
| `ERR_STATION_NOT_SERVING` | 422 |
| `ERR_STERILIZATION_NOT_CLEARED` | 422 |
| `ERR_BATCH_TOO_LARGE` | 422 |
| `ERR_POWER_CAPACITY_EXCEEDED` | 422 |
| `ERR_LOADING_DOCK_REQUIRED` | 422 |
| `ERR_MANIFEST_NOT_UNPACKED` | 422 |
| `ERR_MANIFEST_NOT_REPACKED` | 422 |
| `ERR_STATIONS_NOT_DISMANTLED` | 422 |
| `ERR_ACTIVE_ENCOUNTERS_REMAIN` | 422 |
| `ERR_REFERRAL_REQUIRED` | 422 |
| `ERR_TEARDOWN_INCOMPLETE` | 422 |
| `ERR_HANDOFF_NOT_ACCEPTED` | 422 |
| `ERR_TEMPORAL_WINDOW_INVALID` | 422 |
| `ERR_REFERENCE_INVALID` | 422 |
| `ERR_FISCAL_RULE_VIOLATION` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
