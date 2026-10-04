# Center-Based Senior Primary Care Panel Growth API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a center-based senior primary care platform operating under full-risk Medicare Advantage economics. The business model places neighborhood care centers in senior-dense communities, staffs them with interdisciplinary care teams (physicians, community health workers, and behavioral health clinicians), and grows each center's attributed patient panel through outreach events and Medicare Advantage plan enrollment changes. Because the practice bears the total cost of care for attributed members under full-risk contracts, the platform must reconcile per-member-per-month revenue against claims, internal visit costs, and transportation spend on a monthly close cycle — with a center's profitability ramp from opening through panel maturity tracked as a first-class, tiered outcome.

Operations are deliberately high-touch: visits run longer than conventional primary care (twenty, forty, or sixty minutes), practice-provided transportation reduces missed appointments for transport-dependent patients, and an after-hours triage line diverts avoidable emergency department use. Each of these levers carries explicit rules in this document — panel caps per care team, ride dispatch capacity windows, triage severity gates, and a monthly settlement ledger with provisional and final close variants.

The API is consumed by segregated operational roles: network operators who stand up and staff centers, enrollment coordinators who acquire and attribute patients, front desk staff and care team leads who run the visit lifecycle, transport dispatchers who route rides, triage nurses who resolve after-hours cases, claims adjudicators who price cost-of-care claims, and finance roles who run the monthly close. A test-driving logical clock endpoint supports deterministic evaluation of time-dependent behavior (monthly closes, no-show sweeps, triage expiry, and maturity aging).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes nine distinct roles, spelled exactly as follows: `NetworkOperator`, `EnrollmentCoordinator`, `CareTeamLead`, `FrontDesk`, `TransportDispatcher`, `TriageNurse`, `ClaimsAdjudicator`, `FinanceAnalyst`, and `FinanceController`. Duties are deliberately segregated: `ClaimsAdjudicator` prices claims but cannot finalize settlements, `FinanceAnalyst` opens and provisionally closes settlements but cannot finalize them, and `FinanceController` finalizes or voids settlements and owns plan contracts but cannot provisionally close. A request missing either header, or carrying a role string not in this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is authenticated but not permitted for the attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `CareTeamLead`, `X-User-ID` is the `id` of the acting `CareTeam`; ownership checks on any resource that references a `CareTeam` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is any of `NetworkOperator`, `EnrollmentCoordinator`, `FrontDesk`, `TransportDispatcher`, `TriageNurse`, `ClaimsAdjudicator`, `FinanceAnalyst`, or `FinanceController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters controlling pagination. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

All time-sensitive evaluation in the system — month boundaries, check-in windows, pickup windows, no-show marking, triage expiry, and center maturity aging — is driven by a **logical clock**, never by wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under any circumstance. A `NetworkOperator` advances the clock through an admin-only test-driving capability that accepts a `current_utc` instant and returns the accepted `current_utc` value.

Advancing the clock triggers two scheduled evaluations. First, the **nightly sweep** marks any appointment still in `SCHEDULED` whose end time (its `start_utc` plus its `duration_minutes`) has passed as a no-show, recomputes each patient's `no_show_strikes` as the count of `COMPLETED_NO_SHOW` appointments in the trailing ninety days, and expires triage cases that have been `OPEN` for more than twenty-four hours. Second, the **monthly close run** recomputes each center's `maturity_months` as the whole calendar months elapsed between `opened_on` and the logical clock date — day-of-month is ignored, so a center opened on 2026-01-15 reaches `maturity_months` of 12 the moment the clock enters 2027-01 — and refreshes `panel_fill_ratio`. When the clock crosses a month boundary, each center's `ed_referral_count_current_month` resets to 0.

### 2.5. Common Resource Properties

Every primary resource in the system — centers, care teams, patients, health plans, attributions, appointments, rooms, vehicles, ride requests, triage cases, cost-of-care claims, monthly settlements, and outreach events — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 on every mutation, including mutations driven by cascading side effects.

Any change to a resource's computed fields — for example a care team's `active_panel_count` moving as attributions activate and disenroll, or a center's `cumulative_contribution_cents` moving as settlements post — counts as a mutation of that resource and therefore updates `updated_at` and increments `version`. All entities in this system carry the full four-field set; no entity in this domain omits `updated_at` or `version`.

### 2.6. Monetary Values, Ratios, and Precision

All monetary amounts are expressed as integer cents and never as floating-point dollar values. Fields carrying money — `base_pmpm_cents`, `amount_cents`, `adjudicated_amount_cents`, `accrued_revenue_cents`, `total_cost_of_care_cents`, `contribution_cents`, `cumulative_contribution_cents`, `cost_cents`, and the quote response's `quote_cents` — are whole-cent integers produced by rounding **half-up** at the stage the relevant rule pins. Where a rule computes a per-line or per-patient amount, each such amount is rounded half-up to whole cents first and only then summed into aggregates; reversing that order (summing at full precision and rounding once) yields different cents and is not the rule.

Ratios use fixed decimal precision: `panel_fill_ratio` and the ED diversion rate are carried at 4 decimal places with round-half-up, and `staffing_score` is carried at 2 decimal places with round-half-up. A patient's `risk_score` is supplied at 2 decimal places and must lie between 0.50 and 4.00 inclusive. Contract factors on health plans follow bounded input ranges: `risk_adjust_factor` between 0.80 and 1.60, and `revenue_share_pct` between 0.50 and 1.00.

### 2.7. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of a parent entity and require a version field as a non-optional input.

Activating an attribution requires the request to carry `expected_care_team_version` matching the target care team's current `version`. If another writer has advanced the team's `version` since the client last read it — for example, a panel-cap change or another activation that consumed the final headroom — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from attributing against a team it has not observed.

Provisionally closing a monthly settlement requires the request to carry `expected_center_version` matching the center's current `version`. If another settlement posting has advanced the center's `version` since the client last read it — mutating `cumulative_contribution_cents` — the close is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

Every mutation passes through a fixed validation cascade, and the cascade's ordering is itself a contract — when several checks could fail, the first one in this order determines the rejection:

1. Header presence and role validity (missing headers or undeclared role: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the attempted operation (`ERR_UNAUTHORIZED`).
3. Left-to-right existence of path resource identifiers (`ERR_NOT_FOUND`).
4. Request well-formedness — required fields present, enum values legal, and numeric ranges honored, including `risk_score` between 0.50 and 4.00, `panel_cap` at least 1, and an adjudicated amount within the claimed range (`ERR_INVALID_REQUEST`).
5. Temporal legality of date and month inputs — effective months not before the current logical month, event dates not in the past, appointment starts on the 20-minute boundary, and service months not after the current logical month (`ERR_TEMPORAL_VIOLATION`).
6. State preconditions — the target entity sits in the state the transition requires (`ERR_INVALID_STATE`, or the transition-specific 409 codes named throughout §3).
7. Cross-reference consistency — the appointment's patient is attributed to the appointment team's center, the ride's appointment exists, the triage urgent slot belongs to the same center, and `BEHAVIORAL` appointments reserve a `supports_behavioral` room (`ERR_CROSS_REFERENCE_MISMATCH`).
8. Interval conflicts — room half-open overlap at scheduling and vehicle capacity-overlap at dispatch (`ERR_SCHEDULE_CONFLICT`).
9. Clinical safety gates — `HIGH` severity may not be diverted, self-care is `LOW`-only, and wheelchair patients require a `wheelchair_capable` vehicle (`ERR_SAFETY_GATE_VIOLATION`, surfaced through the gate-specific codes of §3.6 and §3.7).
10. Quota gates — panel-cap headroom, the team `accepting` flag, and the patient's transport privilege (`ERR_QUOTA_EXCEEDED`, surfaced through `ERR_PANEL_CAP_REACHED`, `ERR_TEAM_NOT_ACCEPTING`, and `ERR_TRANSPORT_PRIVILEGE_SUSPENDED`).
11. Fiscal gates — the period settlement is not `FINALIZED` for new claims, settlement operations apply to `FULL_RISK` arrangements only, and claims are adjudicated before finalize (`ERR_FISCAL_GATE_VIOLATION`, surfaced through the settlement-specific codes of §3.8).

Because authorization outranks existence, an unauthorized caller probing a non-existent resource is refused with `ERR_UNAUTHORIZED` rather than `ERR_NOT_FOUND`; because existence outranks well-formedness, a malformed body under a missing parent is a 404, not a 400.

### 2.8. The Full-Risk Ledger

Each center operates a running full-risk ledger. Only health plans whose `contract_type` is `FULL_RISK` accrue total-cost-of-care settlement; `SHARED_SAVINGS` plans participate in attribution and revenue reporting but do not enter the full-risk cost settlement. A center's `cumulative_contribution_cents` is the running sum of settled monthly contribution — accrued revenue minus total cost of care — across closed months, and it is negative while a center ramps. A settlement posting (provisional close or finalize) is the only mechanism that mutates this ledger field, and each posting increments the center's `version`.

The evaluation order inside a monthly close is pinned and irreversible: the period's `total_cost_of_care_cents` is computed first as the sum of adjudicated claims plus internal visit bookings plus transport bookings; `contribution_cents` is then computed as `accrued_revenue_cents` minus `total_cost_of_care_cents`; the center's `profitability_tier` is derived from contribution afterward — never the reverse. A period's settlement is unique per center and month: attempting to open a second settlement for the same center and `period_month` is rejected with `ERR_DUPLICATE_SETTLEMENT`. Claims against a period become read-only once that period's settlement is `FINALIZED` — submission, adjudication, or rejection against a finalized period is rejected with `ERR_SETTLEMENT_FINALIZED`.

### 2.9. Panel Capacity, Saturation, and the Waitlist

Every care team declares a `panel_cap` — a positive integer no smaller than 1 — bounding the number of `ACTIVE` attributed patients it may carry, and an `accepting` flag that gates new activations. A center's `panel_fill_ratio` is the sum of `ACTIVE` panel member counts across the center's care teams divided by the sum of those teams' `panel_cap` values, rounded half-up to 4 decimal places.

Two automatic saturation transitions govern the center lifecycle. When `panel_fill_ratio` reaches at least 1.0000 — at any attribution activation or at a monthly close — the center transitions from `OPEN` to `SATURATED`, every care team whose `active_panel_count` has reached its `panel_cap` has `accepting` set to false, and existing `PENDING` attributions targeting full teams transition to `WAITLISTED`. When `panel_fill_ratio` later falls below 0.9000 — after a disenrollment or a panel-cap increase — the center transitions from `SATURATED` back to `OPEN`, teams whose `active_panel_count` is below `panel_cap` have `accepting` set to true, and a waitlist promotion sweep runs: `WAITLISTED` attributions promote to `PENDING` in `created_at` ascending order while headroom exists, each promotion decrementing the team's `waitlist_depth`. Here "headroom" means the team's `panel_cap` minus its `active_panel_count`, and each promotion consumes one unit of headroom — a promoted row sits in `PENDING` and does not itself increment `active_panel_count` — so at most `panel_cap − active_panel_count` of the earliest-created waitlisted rows promote per team per sweep.

### 2.10. Transportation Capacity and Window Overlap

Ride dispatch enforces vehicle seat capacity across overlapping pickup windows with half-open interval semantics. A candidate vehicle is feasible when, at every instant within the new ride's pickup window, the concurrent occupied seats from that vehicle's `DISPATCHED` or `EN_ROUTE` rides whose pickup windows overlap the new window with a non-zero intersection, plus one, do not exceed the vehicle's `seat_capacity`. Windows touching at exactly one endpoint — one window's end equal to another's start — do not overlap; adjacency is free and no buffer minute is applied. A violation is rejected with `ERR_VEHICLE_CAPACITY_EXCEEDED`.

Room reservations for appointments follow the same half-open overlap discipline: two appointments may not occupy the same room over any shared instant of their reserved intervals, and a conflict is rejected with `ERR_SCHEDULE_CONFLICT`.

### 2.11. Clinical Safety Gates and ED Diversion Policy

Triage resolution enforces clinical safety gates. A case with `severity` of `HIGH` must go to the emergency department: diverting a `HIGH` case to urgent care is rejected with `ERR_SEVERITY_REQUIRES_ED`. Self-care advice is permitted only for `LOW` severity; advising self-care on a `MODERATE` or `HIGH` case is rejected with `ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE`. A patient requiring wheelchair transport may only be dispatched to a `wheelchair_capable` vehicle; otherwise dispatch fails with `ERR_VEHICLE_INELIGIBLE`.

The center tracks an ED-referral counter, `ed_referral_count_current_month`, counting triage cases resolving `RESOLVED_ED` or `EXPIRED` for patients attributed to the center within the current logical month. When the count of `RESOLVED_ED` plus `EXPIRED` cases in a period rises strictly above the monthly floor of 10 — from the eleventh such case onward — the center's profitability review is flagged at the next close. `RESOLVED_SELF_CARE` cases are excluded from both the numerator and denominator of the diversion rate.

### 2.12. Nested Resource Retrieval

Requests targeting nested resources are validated left-to-right along the path. The existence of each path identifier is confirmed in order, and the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource — a request for a care team under a non-existent center fails on the center before the team is ever examined. Reverse-reachability listings (a center's teams, rooms, vehicles, and outreach events; a patient's attributions and triage cases; a care team's attributions and appointments; an appointment's ride requests; a vehicle's assigned rides) apply the same left-to-right existence rule to their path prefix before returning the child collection.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Center

A `NetworkOperator` brings a new market online by creating a center with a `name`, a `neighborhood_code` identifying the senior-dense neighborhood it serves (for example, `CHI-SOUTH-04`), and an `opened_on` ISO date recording when the center opens for patients. A newly created center starts in `PRE_OPEN` with `maturity_months` of 0, `profitability_tier` of `RAMP`, and `cumulative_contribution_cents` of 0.

Before a center can receive patients, the operator staffs it: rooms are created under the center with a `room_label` (such as R1 or R2) and an optional `supports_behavioral` flag defaulting to false that marks the room equipped for `BEHAVIORAL` appointments; vehicles are registered with a `plate`, a `seat_capacity` of at least 1, and an optional `wheelchair_capable` flag defaulting to false; and care teams are established as described in §3.2. Opening the center — the `PRE_OPEN → OPEN` transition performed by a `NetworkOperator` — requires the center to still be `PRE_OPEN` (otherwise `ERR_CENTER_NOT_PRE_OPEN`), to have at least one care team (`ERR_CENTER_HAS_NO_TEAMS`), and to have at least one room (`ERR_CENTER_HAS_NO_ROOMS`). A successful open sets the center's `status` to `OPEN` and increments its `version`.

Centers can be listed with an optional `status` filter, and a single center can be fetched by id; both are readable by network, finance, and enrollment roles, with individual center reads also available to a `CareTeamLead`.

Closing a center — available from either `OPEN` or `SATURATED` — is permitted only when no attribution in `PENDING`, `ACTIVE`, or `WAITLISTED` exists for any of the center's teams (`ERR_CENTER_HAS_ACTIVE_PANEL`) and no settlement for the center is in `OPEN` or `CLOSED_PROVISIONAL` (`ERR_CENTER_HAS_OPEN_SETTLEMENT`). A successful close moves the center to the terminal `CLOSED` state, increments its `version`, and renders all of its vehicles and rooms unassignable.

### 3.2. Care Team Staffing and Panel Economics

Within a center, a `NetworkOperator` creates a care team by supplying a `team_label` (for example, "Team Blue"), the `panel_cap` bounding the team's attributed panel, and the staffing counts `physician_count`, `chw_count`, and `behavioral_count`. The team's `staffing_score` is computed as the physician count times 1.0, plus the community health worker count times 0.5, plus the behavioral clinician count times 0.75, rounded half-up to 2 decimal places; it is recomputed whenever any staffing field changes. A client may suggest a `staffing_score` at creation, but the computed value governs. New teams start with `active_panel_count` of 0, `waitlist_depth` of 0, and `accepting` true; creating a team also increments the owning center's `version`. Teams are listable across the network with an optional `center_id` filter, listable per center, and fetchable individually by network, enrollment, team-lead, and finance-analyst readers.

Updating a team's staffing or `panel_cap` is a `NetworkOperator` operation that recomputes `staffing_score` and increments the team's `version` by 1. Lowering `panel_cap` below the team's current `active_panel_count` is rejected with `ERR_INVALID_REQUEST`. Raising `panel_cap` while the owning center is `SATURATED` re-evaluates the center's `OPEN`/`SATURATED` status and, if the fill ratio has fallen below 0.9000, transitions the center back to `OPEN` and runs the waitlist promotion sweep described in §2.9.

### 3.3. Outreach, Registration, and Plan Contracts

Patient acquisition begins in the community. An `EnrollmentCoordinator` schedules an outreach event under a center with an `event_label` (a health fair, a bingo night), a `scheduled_on` ISO date that must not be in the past at creation (violations are `ERR_TEMPORAL_VIOLATION`), and an `expected_attendance` of at least 1. Each event tracks an `attributed_signups` counter, starting at 0, that increments whenever an attribution is created naming the event via the optional `outreach_event_id` on the attribution payload. Events are listable per center or across the network with an optional `center_id` filter, and fetchable individually.

An `EnrollmentCoordinator` registers a patient with `full_name`, `date_of_birth`, a five-digit `zip_code`, a `risk_score` between 0.50 and 4.00 inclusive at 2 decimal places, and an optional `transport_dependent` flag defaulting to false. The patient's `date_of_birth` must place them at age 60 or older at the logical clock time; under-age registrations are rejected. New patients start with `no_show_strikes` of 0. Patient records are readable by enrollment, care team leads, front desk, triage, transport, and claims roles.

Plan contracts are owned by the `FinanceController`, who creates a health plan with a `plan_name`, a `contract_type` of `FULL_RISK` or `SHARED_SAVINGS`, a `base_pmpm_cents` capitation amount in cents, a `risk_adjust_factor` between 0.80 and 1.60, and a `revenue_share_pct` between 0.50 and 1.00. Plans are fetchable individually by finance and enrollment roles.

A **risk-adjusted PMPM quote** prices a patient at a center under a plan: the quote multiplies the plan's `base_pmpm_cents` by the patient's `risk_score` — clamped to the inclusive range 0.50 through 4.00 — and by the plan's `risk_adjust_factor`, then applies a maturity multiplier taken from the center's `profitability_tier` at quote time: 0.95 while the center is `RAMP`, 1.00 at `BREAKEVEN`, and 1.05 at `MATURE`. The product is rounded half-up to whole cents and returned as `quote_cents`, alongside `tier_applied` naming the tier whose multiplier was used. The quote request supplies `risk_score` and `center_id`; it is available to finance and enrollment roles.

### 3.4. Attribution: Growing and Managing the Panel

Attribution records how a patient joined the panel — through Medicare Advantage plan assignment or a primary care selection change. An `EnrollmentCoordinator` creates an attribution in `PENDING` by supplying the `patient_id`, the `health_plan_id` of the MA plan assignment source, the `care_team_id` of the selected team, and an `effective_month` in `YYYY-MM` form; an optional `outreach_event_id` ties the signup to its originating event. The `effective_month` must not be earlier than the current logical month (`ERR_TEMPORAL_VIOLATION`), and the patient must hold no other `PENDING` or `ACTIVE` attribution (`ERR_PATIENT_ALREADY_ATTRIBUTED`). Creation sets the row's `status` to `PENDING` and, when an event is named, increments that event's `attributed_signups`. Attributions are listable with optional `patient_id`, `health_plan_id`, `care_team_id`, and `status` filters; per-patient and per-team reverse listings (the latter with an optional `status` filter) are also available, as are individual reads by enrollment and finance-analyst roles.

Activation — the `PENDING → ACTIVE` transition by an `EnrollmentCoordinator` — carries `expected_care_team_version` per §2.7 and enforces its checks **in order**: first that the attribution is `PENDING` (`ERR_ATTRIBUTION_NOT_PENDING`); second that `effective_month` is not after the current logical month (`ERR_ATTRIBUTION_NOT_YET_EFFECTIVE`); third that the target team's `accepting` flag is true (`ERR_TEAM_NOT_ACCEPTING`); fourth that the team's `active_panel_count` is still below `panel_cap` (`ERR_PANEL_CAP_REACHED`); and finally that the patient holds no other `ACTIVE` or `PENDING` attribution (`ERR_PATIENT_ALREADY_ATTRIBUTED`). A successful activation increments the team's `active_panel_count` by 1 and the team's `version` by 1, and — per §2.9 — triggers the center saturation cascade if the fill ratio reaches 1.0000. When activation is attempted against a full team and overflow policy is `WAITLIST`, the attribution instead moves `PENDING → WAITLISTED` and the team's `waitlist_depth` increments; the system performs the same transition during the saturation cascade.

Disenrollment — the `ACTIVE → DISENROLLED` transition by an `EnrollmentCoordinator` — requires the attribution to be `ACTIVE` (`ERR_ATTRIBUTION_NOT_ACTIVE`), stamps the row's `disenrolled_month` with the current logical month, decrements the team's `active_panel_count`, and increments the team's `version`. If the center was `SATURATED` and the fill ratio drops below 0.9000, the center returns to `OPEN` and the waitlist promotion sweep runs, promoting the earliest-`created_at` `WAITLISTED` rows to `PENDING` while headroom remains.

A disenrolled patient can rejoin through reattribution: an `EnrollmentCoordinator` links a `DISENROLLED` row to a fresh attribution by supplying `new_attribution_id`. The old row must be `DISENROLLED` (`ERR_ATTRIBUTION_NOT_DISENROLLED`), the referenced new attribution must exist and be `PENDING` (`ERR_NEW_ATTRIBUTION_NOT_PENDING`), and the new row's `effective_month` must be strictly after the old row's `disenrolled_month` (`ERR_REATTRIBUTION_MONTH_NOT_AFTER_DISENROLL`). The old row moves to `REATTRIBUTED` and becomes a historical link; the new `PENDING` row is the live record and may then be activated normally. `DISENROLLED` is otherwise terminal for the old row.

### 3.5. Visit Scheduling and the Long-Visit Model

Visits are long by design. Front desk staff and care team leads schedule an appointment by supplying the `care_team_id`, the `patient_id`, the `room_id` to reserve, a `start_utc`, a `duration_minutes` of exactly 20, 40, or 60, and a `kind` of `PRIMARY`, `BEHAVIORAL`, or `CHW_OUTREACH`. The `start_utc` must fall on a 20-minute boundary within center hours (`ERR_TEMPORAL_VIOLATION` when it does not). The patient must hold an `ACTIVE` attribution at the team's center, and cross-references must be consistent — an appointment whose patient is not attributed to the team's center is rejected with `ERR_CROSS_REFERENCE_MISMATCH`. A `BEHAVIORAL` appointment additionally requires the reserved room's `supports_behavioral` to be true (`ERR_CROSS_REFERENCE_MISMATCH` when it is not). Room occupancy follows the half-open overlap rule of §2.10, with violations rejected as `ERR_SCHEDULE_CONFLICT`. New appointments start `SCHEDULED`; appointments are listable with optional `care_team_id`, `patient_id`, `room_id`, and `status` filters, listable per team, and fetchable individually by front desk, team leads, transport, and triage readers.

On the day of the visit, a `FrontDesk` operator checks the patient in. Check-in requires the appointment to be `SCHEDULED` (`ERR_APPOINTMENT_NOT_SCHEDULED`) and the logical clock to lie within the window from thirty minutes before `start_utc` through the appointment's end (`start_utc` plus its duration); a missed window is `ERR_CHECKIN_WINDOW_MISSED`. Successful check-in moves the appointment `SCHEDULED → CHECKED_IN`.

A `FrontDesk` operator may cancel an appointment while it is `SCHEDULED` (`ERR_APPOINTMENT_NOT_SCHEDULED` otherwise) and only while the logical clock is still before `start_utc` — cancellation at or after the start is `ERR_CANCEL_TOO_LATE`. Cancelling moves the appointment to the terminal `CANCELLED` state and cascades to transportation: any linked ride in `REQUESTED` or `DISPATCHED` moves to `CANCELLED` with no transport cost booked, while an `EN_ROUTE` ride is unaffected.

Completion belongs to the `CareTeamLead`. Completing requires the appointment to be `CHECKED_IN` (`ERR_APPOINTMENT_NOT_CHECKED_IN`) and moves it to the terminal `COMPLETED` state. Completion books internal visit cost into cost of care (see §3.8), and if the appointment's ride is `DISPATCHED` or `EN_ROUTE` the ride automatically moves to `DELIVERED` with its transport cost booked.

When a `SCHEDULED` appointment's end time passes without check-in, the nightly sweep marks it `COMPLETED_NO_SHOW`, terminal. The no-show still books cost — at half the full scaled visit cost, rounded half-up to whole cents — and increments the patient's `no_show_strikes`. Once a patient reaches 3 strikes, subsequent ride creation for that patient is rejected with `ERR_TRANSPORT_PRIVILEGE_SUSPENDED`.

### 3.6. Transportation and No-Show Recovery

Transport-dependent patients get practice-provided rides. A `TransportDispatcher` or `FrontDesk` operator creates a ride request against an appointment; the new ride starts in `REQUESTED` with its `appointment_id` and `patient_id` copied from the appointment at creation, and its pickup window computed from the appointment: `pickup_window_start` is ninety minutes before the appointment's `start_utc`, and `pickup_window_end` is thirty minutes before it. While `REQUESTED`, the ride's `assigned_vehicle_id` is null. Creation is rejected with `ERR_TRANSPORT_PRIVILEGE_SUSPENDED` when the patient carries 3 or more `no_show_strikes`. Rides are listable with optional `appointment_id`, `patient_id`, `assigned_vehicle_id`, and `status` filters; reverse listings exist per appointment and per vehicle (the latter with an optional `status` filter), and individual rides are readable by transport and front desk roles.

Dispatch assigns a vehicle. A `TransportDispatcher` dispatches a `REQUESTED` ride (`ERR_RIDE_NOT_REQUESTED` otherwise) by supplying a `vehicle_id`. The vehicle must exist, belong to the appointment's center, and be `wheelchair_capable` when the patient requires wheelchair transport — any failure here is `ERR_VEHICLE_INELIGIBLE`. The capacity-overlap rule of §2.10 applies (`ERR_VEHICLE_CAPACITY_EXCEEDED`), and the patient's strikes must still be below 3 (`ERR_TRANSPORT_PRIVILEGE_SUSPENDED`). A successful dispatch moves the ride to `DISPATCHED` and records the `assigned_vehicle_id`.

When the driver heads out, the dispatcher starts pickup. The ride must be `DISPATCHED` (`ERR_RIDE_NOT_DISPATCHED`) and the logical clock must lie within the inclusive pickup window from `pickup_window_start` to `pickup_window_end`; a missed window is `ERR_PICKUP_WINDOW_MISSED`. The ride moves `DISPATCHED → EN_ROUTE`.

If the passenger fails to appear, the dispatcher marks the ride no-show. The ride must be `EN_ROUTE` (`ERR_RIDE_NOT_EN_ROUTE`); it moves to `FAILED_NO_SHOW`, its `failure_count` increments by 1, and transport cost is booked at 100 percent of the flat ride cost. Recovery is possible while the visit could still happen: a dispatcher recovers a `FAILED_NO_SHOW` ride (`ERR_RIDE_NOT_FAILED` otherwise) as long as the logical clock is still before the appointment's end (`ERR_RECOVERY_WINDOW_MISSED` past it). Recovery passes the ride through a transient `RECOVERED` state and returns it to `REQUESTED` under the same id — `RECOVERED` is never a resting state; the observable state after recovery is `REQUESTED`, ready for a fresh dispatch.

Rides reach their terminal states two ways. A ride in `EN_ROUTE` — or in `DISPATCHED` when pickup never started — moves automatically to `DELIVERED` when the linked appointment completes, booking transport cost at 100 percent of the flat ride cost. A ride in `REQUESTED` or `DISPATCHED` moves to `CANCELLED` when its appointment is cancelled, with no transport cost booked. `DELIVERED` and `CANCELLED` are terminal.

### 3.7. After-Hours Triage and ED Diversion

A `TriageNurse` opens a triage case for a patient by supplying the `patient_id`, a `channel` of `AFTER_HOURS_LINE`, `WALK_IN`, or `CARE_TEAM_ESCALATION`, and a `severity` of `LOW`, `MODERATE`, or `HIGH`. The case starts `OPEN` with a null `disposition`. Cases are listable with optional `patient_id` and `status` filters, listable per patient, and fetchable individually by triage and team-lead readers.

Resolution takes one of three nurse-driven paths, all guarded by the safety gates of §2.11:

- **Divert to urgent care.** Diverting requires the case to be `OPEN` (`ERR_TRIAGE_NOT_OPEN`) and the `severity` to be other than `HIGH` (`ERR_SEVERITY_REQUIRES_ED`). The payload's `urgent_appointment_id` must reference a `SCHEDULED` appointment of `kind` `PRIMARY`, at the same center, starting within the next twenty-four hours of the logical clock — a missing, non-scheduled, wrong-kind, cross-center, or too-distant slot is `ERR_URGENT_SLOT_INVALID` (the cross-center failure also surfaces as `ERR_CROSS_REFERENCE_MISMATCH`). Success moves the case to `RESOLVED_DIVERTED` with `disposition` set to `URGENT_CARE_BOOKED`, and the linked appointment is internally flagged as urgent-fill without any state change. The case's `diversion_success` becomes true only when that linked urgent-care appointment completes; an `ED_REFERRED` disposition always carries `diversion_success` false.
- **Refer to the ED.** Referral requires only an `OPEN` case (`ERR_TRIAGE_NOT_OPEN`). The case moves to `RESOLVED_ED` with `disposition` `ED_REFERRED` and `diversion_success` false, and the patient's center `ed_referral_count_current_month` increments by 1, subject to the monthly floor described in §2.11.
- **Advise self-care.** Self-care requires an `OPEN` case (`ERR_TRIAGE_NOT_OPEN`) and `severity` exactly `LOW` (`ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE`). The case moves to `RESOLVED_SELF_CARE` with `disposition` `SELF_CARE_ADVISED`.

A case still `OPEN` after twenty-four hours is expired by the nightly sweep into the terminal `EXPIRED` state; its `disposition` remains null, and it is treated as ED-equivalent failure in the diversion rate. All four resolved states — `RESOLVED_DIVERTED`, `RESOLVED_ED`, `RESOLVED_SELF_CARE`, and `EXPIRED` — are terminal.

The center-month **ED diversion rate** divides `RESOLVED_DIVERTED` cases by the sum of `RESOLVED_DIVERTED`, `RESOLVED_ED`, and `EXPIRED` cases, carried at 4 decimal places with round-half-up; `RESOLVED_SELF_CARE` cases enter neither numerator nor denominator. The diversion rate feeds the panel-value adjustment at monthly close (§3.8).

### 3.8. Cost-of-Care Claims and the Monthly Settlement Close

Under full risk, every dollar of member cost lands in the center ledger. A `ClaimsAdjudicator` or `FinanceAnalyst` submits a cost-of-care claim with the `center_id` bearing the cost, the `patient_id` the cost belongs to, the `service_month` in `YYYY-MM` form, a `category` of `ED_VISIT`, `INPATIENT`, `SPECIALIST`, `PHARMACY`, `TRANSPORT`, or `INTERNAL_VISIT`, and a positive integer `amount_cents`. The `service_month` must not be after the current logical month (`ERR_TEMPORAL_VIOLATION`), and the period's settlement must not be `FINALIZED` (`ERR_SETTLEMENT_FINALIZED`). New claims start `SUBMITTED`. Claims are listable with optional `center_id`, `patient_id`, `status`, and `service_month` filters, and fetchable individually by claims and finance roles.

A `ClaimsAdjudicator` — segregated from settlement finalize — adjudicates a `SUBMITTED` claim (`ERR_CLAIM_NOT_SUBMITTED` otherwise) by supplying `adjudicated_amount_cents`, which must be at least 0 and no more than the claimed `amount_cents` (`ERR_ADJUDICATED_AMOUNT_INVALID`). The settlement for the claim's center and `service_month` must be `OPEN` or `CLOSED_PROVISIONAL`; against a `FINALIZED` period the attempt is `ERR_SETTLEMENT_FINALIZED`. Adjudication moves the claim to `ADJUDICATED`, sets its `adjudicated_amount_cents`, and recomputes the settlement's `total_cost_of_care_cents`. Alternatively, the adjudicator rejects a `SUBMITTED` claim (`ERR_CLAIM_NOT_SUBMITTED`), moving it to the terminal `REJECTED` state with `adjudicated_amount_cents` set to 0. When a settlement finalizes, all of its `ADJUDICATED` claims move automatically to the terminal `SETTLED` state.

The monthly close is a two-stage, role-segregated process. A `FinanceAnalyst` opens a settlement for a center and `period_month`; the pair must be unique (`ERR_DUPLICATE_SETTLEMENT`), and the settlement starts `OPEN`. Settlements are listable with optional `center_id` and `status` filters and fetchable individually by finance roles. Provisional close is then performed by the `FinanceAnalyst` with `expected_center_version` per §2.7; the settlement must be `OPEN` (`ERR_SETTLEMENT_NOT_OPEN`) and the logical clock must sit in a later month than `period_month` (`ERR_PERIOD_STILL_OPEN` while still inside the period). Provisional close computes `accrued_revenue_cents` with the **chronological (actuals) variant** of panel revenue accrual, computes `total_cost_of_care_cents` and `contribution_cents`, moves the settlement to `CLOSED_PROVISIONAL`, posts `contribution_cents` into the center's `cumulative_contribution_cents` as a provisional posting, and increments the center's `version`.

**Panel revenue accrual** works as follows. For each patient with an attribution whose `ACTIVE` interval intersects the period — rows in `ACTIVE` or `DISENROLLED`, with `REATTRIBUTED` rows counting through their `disenrolled_month` only — the base per-member-per-month amount is the plan's `base_pmpm_cents` multiplied by the plan's `risk_adjust_factor` and the patient's `risk_score`. Each patient's active interval runs from the logical-clock date of the `PENDING → ACTIVE` transition (or the period start, whichever is later) through the logical-clock date of disenrollment (or the period end, whichever is earlier), inclusive of both endpoints, and days-in-month follows the calendar. Each patient's contribution is computed at full precision, rounded half-up to whole cents **first**, and only then summed into `accrued_revenue_cents`. The two variants differ in how `member_months` are counted: at provisional close, any patient active at least one day in the period counts a full member month of 1 (late-arriving claims do not change member months); at finalize, member months are day-prorated as days active in the period divided by days in the period, producing a delta against the provisional figure that posts to the center ledger.

Finalize belongs to the `FinanceController` — segregated from provisional close. Finalizing requires the settlement to be `CLOSED_PROVISIONAL` (`ERR_SETTLEMENT_NOT_PROVISIONAL`) and no `SUBMITTED` claims to remain for the center and period (`ERR_CLAIMS_STILL_PENDING`). Finalize recomputes `accrued_revenue_cents` with the **forward-looking (proration-reconciled) variant**, applies the delta versus provisional to the center's `cumulative_contribution_cents`, settles all `ADJUDICATED` claims for the period, recomputes the center's `maturity_months`, `panel_fill_ratio`, and `profitability_tier`, moves the settlement to the terminal `FINALIZED` state, and increments the center's `version`. A `FinanceController` may instead void a settlement while it is `OPEN` (`ERR_SETTLEMENT_NOT_OPEN`) provided no `ADJUDICATED` claims reference the period (`ERR_CLAIMS_ALREADY_ADJUDICATED`), moving it to the terminal `VOIDED` state.

**Cost of care booking** prices internal activity in whole cents. An internal visit books at a base by `kind` — 18000 cents for `PRIMARY`, 22000 cents for `BEHAVIORAL`, 9000 cents for `CHW_OUTREACH` — scaled by duration as a multiplier of `duration_minutes` over 40 (0.5 for 20 minutes, 1.0 for 40, 1.5 for 60); a no-show books at half the scaled amount, rounded half-up to whole cents. Each `DELIVERED` or `FAILED_NO_SHOW` ride books a flat 3200 cents of `TRANSPORT` cost. The appointment's `cost_cents` field records the booked amount on `COMPLETED` or `COMPLETED_NO_SHOW`. Aggregation follows the pinned order of §2.8: adjudicated claims plus internal visit bookings plus transport bookings form `total_cost_of_care_cents`; `contribution_cents` is accrued revenue minus that total and may be negative; the tier derives from contribution last.

The center's **profitability tier** is a three-way branch evaluated at finalize. If the center's `maturity_months` is below 12, the tier is `RAMP`. Otherwise, if `cumulative_contribution_cents` is negative, the tier remains `RAMP`. Otherwise, if `panel_fill_ratio` is below 0.7500, the tier is `BREAKEVEN`. In all remaining cases the tier is `MATURE`. Boundaries are inclusive on the lower side: a center at exactly 12 maturity months exits `RAMP` only when cumulative contribution is non-negative, and a fill ratio of exactly 0.7500 qualifies for `MATURE`.

At the monthly close run, after cost aggregation, the **outcome-adjusted panel value** prices care team performance — a different domain from ride and visit cost booking. The base value is the center-month's `accrued_revenue_cents`. If the ED diversion rate is at least 0.8000, the base is multiplied by 1.05; if it is at least 0.6000 but below 0.8000, the multiplier is 1.00; below 0.6000 the multiplier is 0.97. The tier multiplier is applied to the base and the result rounded half-up to whole cents **first**; the staffing bonus — the sum of `staffing_score` across the center's care teams, multiplied by 150 cents, rounded half-up to whole cents — is computed **second**; the two rounded figures are then summed into the panel value. Reversing the rounding order yields different cents and is not the rule. The outcome-adjusted panel value is an internal analytic: it is not persisted on any resource and is not carried as a field in any API response.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the clock-set capability — return a `200 OK` status code. All resources are mounted under the `/senior-care` prefix, with the logical clock capability mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | NetworkOperator |
| POST | `/senior-care/centers` | Create a center in PRE_OPEN | NetworkOperator |
| GET | `/senior-care/centers` | List centers, optionally filtered by status | NetworkOperator, FinanceAnalyst, FinanceController, EnrollmentCoordinator |
| GET | `/senior-care/centers/{centerId}` | Get one center | NetworkOperator, FinanceAnalyst, FinanceController, EnrollmentCoordinator, CareTeamLead |
| POST | `/senior-care/centers/{centerId}/open` | Open a PRE_OPEN center | NetworkOperator |
| POST | `/senior-care/centers/{centerId}/close` | Close an OPEN/SATURATED center with no active panel or open settlement | NetworkOperator |
| GET | `/senior-care/centers/{centerId}/care-teams` | List care teams of a center | NetworkOperator, EnrollmentCoordinator, CareTeamLead, FinanceAnalyst |
| POST | `/senior-care/centers/{centerId}/care-teams` | Create a care team | NetworkOperator |
| GET | `/senior-care/care-teams` | List care teams, optionally filtered by center | NetworkOperator, EnrollmentCoordinator, CareTeamLead, FinanceAnalyst |
| GET | `/senior-care/care-teams/{teamId}` | Get one care team | NetworkOperator, EnrollmentCoordinator, CareTeamLead, FinanceAnalyst |
| PATCH | `/senior-care/care-teams/{teamId}` | Update staffing or panel cap | NetworkOperator |
| GET | `/senior-care/care-teams/{teamId}/attributions` | List attributions of a care team | EnrollmentCoordinator, CareTeamLead |
| GET | `/senior-care/care-teams/{teamId}/appointments` | List appointments of a care team | FrontDesk, CareTeamLead |
| GET | `/senior-care/centers/{centerId}/rooms` | List rooms of a center | NetworkOperator, FrontDesk, CareTeamLead |
| POST | `/senior-care/centers/{centerId}/rooms` | Create a room | NetworkOperator |
| GET | `/senior-care/rooms` | List rooms, optionally filtered by center | NetworkOperator, FrontDesk, CareTeamLead |
| GET | `/senior-care/rooms/{roomId}` | Get one room | NetworkOperator, FrontDesk, CareTeamLead |
| GET | `/senior-care/centers/{centerId}/vehicles` | List vehicles of a center | NetworkOperator, TransportDispatcher |
| POST | `/senior-care/centers/{centerId}/vehicles` | Create a vehicle | NetworkOperator |
| GET | `/senior-care/vehicles` | List vehicles, optionally filtered by center | NetworkOperator, TransportDispatcher |
| GET | `/senior-care/vehicles/{vehicleId}` | Get one vehicle | NetworkOperator, TransportDispatcher |
| GET | `/senior-care/vehicles/{vehicleId}/ride-requests` | List ride requests assigned to a vehicle | TransportDispatcher |
| GET | `/senior-care/centers/{centerId}/outreach-events` | List outreach events of a center | NetworkOperator, EnrollmentCoordinator |
| POST | `/senior-care/centers/{centerId}/outreach-events` | Create an outreach event | EnrollmentCoordinator |
| GET | `/senior-care/outreach-events` | List outreach events, optionally filtered by center | NetworkOperator, EnrollmentCoordinator |
| GET | `/senior-care/outreach-events/{eventId}` | Get one outreach event | NetworkOperator, EnrollmentCoordinator |
| POST | `/senior-care/patients` | Register a patient | EnrollmentCoordinator |
| GET | `/senior-care/patients/{patientId}` | Get one patient | EnrollmentCoordinator, CareTeamLead, FrontDesk, TriageNurse, TransportDispatcher, ClaimsAdjudicator |
| GET | `/senior-care/patients/{patientId}/attributions` | List attributions of a patient | EnrollmentCoordinator, FinanceAnalyst |
| GET | `/senior-care/patients/{patientId}/triage-cases` | List triage cases of a patient | TriageNurse, CareTeamLead |
| POST | `/senior-care/health-plans` | Create a health plan contract | FinanceController |
| GET | `/senior-care/health-plans/{planId}` | Get one health plan | FinanceAnalyst, FinanceController, EnrollmentCoordinator |
| GET | `/senior-care/health-plans/{planId}/quote` | Quote a risk-adjusted PMPM for a patient at a center | FinanceAnalyst, FinanceController, EnrollmentCoordinator |
| POST | `/senior-care/patient-attributions` | Create an attribution in PENDING | EnrollmentCoordinator |
| GET | `/senior-care/patient-attributions` | List attributions, optionally filtered by patient, plan, or team | EnrollmentCoordinator, FinanceAnalyst |
| GET | `/senior-care/patient-attributions/{attrId}` | Get one attribution | EnrollmentCoordinator, FinanceAnalyst |
| POST | `/senior-care/patient-attributions/{attrId}/activate` | Activate a PENDING attribution (OCC on the care team) | EnrollmentCoordinator |
| POST | `/senior-care/patient-attributions/{attrId}/disenroll` | Disenroll an ACTIVE attribution | EnrollmentCoordinator |
| POST | `/senior-care/patient-attributions/{attrId}/reattribute` | Link a DISENROLLED attribution to a new PENDING one | EnrollmentCoordinator |
| POST | `/senior-care/appointments` | Schedule an appointment with room reservation | FrontDesk, CareTeamLead |
| GET | `/senior-care/appointments` | List appointments, optionally filtered by team, patient, or room | FrontDesk, CareTeamLead, TransportDispatcher, TriageNurse |
| GET | `/senior-care/appointments/{apptId}` | Get one appointment | FrontDesk, CareTeamLead, TransportDispatcher, TriageNurse |
| POST | `/senior-care/appointments/{apptId}/check-in` | Check in a scheduled appointment | FrontDesk |
| POST | `/senior-care/appointments/{apptId}/complete` | Complete a checked-in appointment | CareTeamLead |
| POST | `/senior-care/appointments/{apptId}/cancel` | Cancel a scheduled appointment | FrontDesk |
| POST | `/senior-care/appointments/{apptId}/ride-requests` | Create a ride request for an appointment | TransportDispatcher, FrontDesk |
| GET | `/senior-care/appointments/{apptId}/ride-requests` | List ride requests for an appointment | TransportDispatcher, FrontDesk |
| GET | `/senior-care/ride-requests` | List ride requests, optionally filtered by appointment, patient, or vehicle | TransportDispatcher, FrontDesk |
| GET | `/senior-care/ride-requests/{rideId}` | Get one ride request | TransportDispatcher, FrontDesk |
| POST | `/senior-care/ride-requests/{rideId}/dispatch` | Dispatch a ride to a vehicle | TransportDispatcher |
| POST | `/senior-care/ride-requests/{rideId}/start-pickup` | Mark dispatched ride en route | TransportDispatcher |
| POST | `/senior-care/ride-requests/{rideId}/mark-no-show` | Mark en-route ride as passenger no-show | TransportDispatcher |
| POST | `/senior-care/ride-requests/{rideId}/recover` | Recover a failed ride (returns it to REQUESTED) | TransportDispatcher |
| POST | `/senior-care/triage-cases` | Open a triage case | TriageNurse |
| GET | `/senior-care/triage-cases` | List triage cases, optionally filtered by patient | TriageNurse, CareTeamLead |
| GET | `/senior-care/triage-cases/{caseId}` | Get one triage case | TriageNurse, CareTeamLead |
| POST | `/senior-care/triage-cases/{caseId}/divert` | Divert a triage case to an urgent-care appointment | TriageNurse |
| POST | `/senior-care/triage-cases/{caseId}/refer-ed` | Refer a triage case to the ED | TriageNurse |
| POST | `/senior-care/triage-cases/{caseId}/advise-self-care` | Resolve a LOW-severity case with self-care advice | TriageNurse |
| POST | `/senior-care/cost-claims` | Submit a cost-of-care claim | ClaimsAdjudicator, FinanceAnalyst |
| GET | `/senior-care/cost-claims` | List cost claims with filters | ClaimsAdjudicator, FinanceAnalyst, FinanceController |
| GET | `/senior-care/cost-claims/{claimId}` | Get one cost claim | ClaimsAdjudicator, FinanceAnalyst, FinanceController |
| POST | `/senior-care/cost-claims/{claimId}/adjudicate` | Adjudicate a submitted claim | ClaimsAdjudicator |
| POST | `/senior-care/cost-claims/{claimId}/reject` | Reject a submitted claim | ClaimsAdjudicator |
| POST | `/senior-care/monthly-settlements` | Open a monthly settlement for a center and period | FinanceAnalyst |
| GET | `/senior-care/monthly-settlements` | List settlements with filters | FinanceAnalyst, FinanceController |
| GET | `/senior-care/monthly-settlements/{settlementId}` | Get one settlement | FinanceAnalyst, FinanceController |
| POST | `/senior-care/monthly-settlements/{settlementId}/close-provisional` | Provisionally close a settlement (OCC on the center) | FinanceAnalyst |
| POST | `/senior-care/monthly-settlements/{settlementId}/finalize` | Finalize a provisional settlement | FinanceController |
| POST | `/senior-care/monthly-settlements/{settlementId}/void` | Void an open settlement | FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TEMPORAL_VIOLATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_SAFETY_GATE_VIOLATION` | 422 |
| `ERR_QUOTA_EXCEEDED` | 409 |
| `ERR_FISCAL_GATE_VIOLATION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CENTER_NOT_PRE_OPEN` | 409 |
| `ERR_CENTER_HAS_NO_TEAMS` | 409 |
| `ERR_CENTER_HAS_NO_ROOMS` | 409 |
| `ERR_CENTER_HAS_ACTIVE_PANEL` | 409 |
| `ERR_CENTER_HAS_OPEN_SETTLEMENT` | 409 |
| `ERR_ATTRIBUTION_NOT_PENDING` | 409 |
| `ERR_ATTRIBUTION_NOT_YET_EFFECTIVE` | 409 |
| `ERR_TEAM_NOT_ACCEPTING` | 409 |
| `ERR_PANEL_CAP_REACHED` | 409 |
| `ERR_PATIENT_ALREADY_ATTRIBUTED` | 409 |
| `ERR_ATTRIBUTION_NOT_ACTIVE` | 409 |
| `ERR_ATTRIBUTION_NOT_DISENROLLED` | 409 |
| `ERR_NEW_ATTRIBUTION_NOT_PENDING` | 409 |
| `ERR_REATTRIBUTION_MONTH_NOT_AFTER_DISENROLL` | 422 |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 |
| `ERR_CHECKIN_WINDOW_MISSED` | 409 |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 |
| `ERR_CANCEL_TOO_LATE` | 409 |
| `ERR_RIDE_NOT_REQUESTED` | 409 |
| `ERR_VEHICLE_INELIGIBLE` | 422 |
| `ERR_VEHICLE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TRANSPORT_PRIVILEGE_SUSPENDED` | 409 |
| `ERR_RIDE_NOT_DISPATCHED` | 409 |
| `ERR_PICKUP_WINDOW_MISSED` | 409 |
| `ERR_RIDE_NOT_EN_ROUTE` | 409 |
| `ERR_RIDE_NOT_FAILED` | 409 |
| `ERR_RECOVERY_WINDOW_MISSED` | 409 |
| `ERR_TRIAGE_NOT_OPEN` | 409 |
| `ERR_SEVERITY_REQUIRES_ED` | 422 |
| `ERR_URGENT_SLOT_INVALID` | 422 |
| `ERR_SEVERITY_TOO_HIGH_FOR_SELF_CARE` | 422 |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 |
| `ERR_ADJUDICATED_AMOUNT_INVALID` | 400 |
| `ERR_SETTLEMENT_FINALIZED` | 409 |
| `ERR_SETTLEMENT_NOT_OPEN` | 409 |
| `ERR_PERIOD_STILL_OPEN` | 409 |
| `ERR_SETTLEMENT_NOT_PROVISIONAL` | 409 |
| `ERR_CLAIMS_STILL_PENDING` | 409 |
| `ERR_CLAIMS_ALREADY_ADJUDICATED` | 409 |
| `ERR_DUPLICATE_SETTLEMENT` | 409 |
