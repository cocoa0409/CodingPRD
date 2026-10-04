# Volunteer Classroom Programs API — Product Requirements Document

## 1. Introduction

A youth-entrepreneurship nonprofit runs its classroom programs on borrowed talent: employees of corporate partners volunteer to teach multi-week sequences in local schools, work through hands-on activities drawn from pre-packed curriculum kits, and finish with a capstone day at a simulated town or finance park facility. Running that model across an area office's territory means coordinating four calendars at once — the school district relationship, the teacher's classroom, the volunteer's credentials, and the warehouse's kit stock — while keeping corporate sponsors informed enough to renew their funding year after year.

The Volunteer Classroom Programs API is the operational system of record for that territory model. It manages the pipeline from area office to district to school, recruits volunteers from corporate partners and tracks their background screening and training as independent credential dimensions, plans classroom deliveries as sequences of cadenced weekly sessions with substitution when a volunteer drops out, accounts for every curriculum kit from assembly through classroom reconciliation, runs capstone events under facility capacity limits, and converts paired student surveys into funder-facing evaluation reports. A logical clock drives all date-sensitive behavior — credential expiry, session delivery windows, and automatic no-show marking — so that time-based rules are deterministic rather than incidental.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, invariants, and ordering rules that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request with a missing or unrecognized header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles, spelled as follows: `PlatformAdmin`, `AreaDirector`, `PartnershipManager`, `ProgramCoordinator`, `LogisticsCoordinator`, and `Funder`. For every one of these six roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any resource's `id`. Once authenticated, a role may invoke only the operations assigned to it; any other attempt is rejected with `ERR_FORBIDDEN` (HTTP 403).

The role surfaces are deliberately disjoint on the write side. A `PlatformAdmin` seeds the platform: area offices, the program catalog, and the logical clock. An `AreaDirector` owns territory districts, schools, and partnership agreements. A `PartnershipManager` owns corporate partners, volunteer recruitment, and volunteer credential events. A `ProgramCoordinator` runs program delivery: classroom deliveries, sessions and substitution, capstone events, rosters, and surveys. A `LogisticsCoordinator` owns kit inventory rows and stock movements. A `Funder` holds no write operations at all. On the read side, all six roles may query every resource collection; the single exception is the computed evaluation report, which only `AreaDirector`, `PartnershipManager`, and `Funder` may read.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets how many items are skipped and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

All date-sensitive behavior in the system is governed by a logical clock rather than wall-clock time. Before any client advances it, the clock reads the fixed default `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` moves time forward by submitting `to_iso8601`; the response reports the new `current_utc`.

Advancing the clock also runs the system's scheduled sweeps. A volunteer whose background-screening clearance has lapsed — the clock now reading later than `screening_expires_on` — moves from CLEARED to EXPIRED, and a volunteer whose training currency has lapsed past `training_expires_on` moves from COMPLETED to EXPIRED; each expiry cascades to that volunteer's SCHEDULED sessions as described in §3.2. Independently, any session still in SCHEDULED or NEEDS_SUBSTITUTE whose delivery window has fully passed — the clock now reading later than seven days after its `scheduled_date` — is marked NO_SHOW automatically, as described in §3.5.

### 2.5. Common Resource Properties

Every resource in the API carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation. `version` is a system-managed integer that increments by 1 on every mutation of the resource — including mutations caused by cascades, such as a delivery whose `sessions_blocked_count` is recomputed when one of its sessions loses its volunteer. All twelve resource types — area offices, districts, schools, corporate partners, volunteers, program catalog entries, partnership agreements, classroom deliveries, sessions, kit inventory rows, capstone events, and student participants — carry this common set.

### 2.6. Optimistic Concurrency Control

Two write operations guard a parent entity with optimistic concurrency control; endpoints not named here accept no version field.

Creating a classroom delivery requires the client to supply `expected_agreement_version`, carrying the parent partnership agreement's `version` as the client last observed it. If the agreement's current `version` no longer matches — for example because the agreement was just amended, or another delivery was just created under it — the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), preventing a delivery from being built on superseded terms.

Substituting a session's volunteer requires the client to supply `expected_delivery_version`, carrying the parent delivery's `version` as last observed. If the delivery's current `version` no longer matches — for example because a credential-expiry cascade or an earlier substitution has recomputed the delivery's blocked-session count since the client last read it — the request is rejected with `ERR_STALE_DELIVERY_VERSION` (HTTP 412).

Version increments are themselves part of the contract: every successful partnership-agreement mutation increments the agreement's `version` by 1, creating a delivery increments its parent agreement's `version` by 1, and a successful substitution increments the parent delivery's `version` by 1.

### 2.7. Validation Order and Error Priority

Every request is validated against an ordered ladder, and the first failing tier reports its error; later tiers are never consulted once an earlier one fails.

1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role name is recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization: the acting role is listed among the endpoint's allowed roles, else `ERR_FORBIDDEN`.
3. Body shape: required fields are present, no undeclared fields appear, enum and `action` values are recognized, and scalar ranges are sane — minutes in range, dates parseable — else `ERR_VALIDATION`.
4. Existence: referenced resource ids exist — path identifiers validated left-to-right, then body foreign keys in their declared input order — else `ERR_NOT_FOUND`.
5. Stale parent versions: the optimistic-concurrency checks of §2.6, reporting `ERR_STALE_AGREEMENT_VERSION` or `ERR_STALE_DELIVERY_VERSION` on their respective endpoints.
6. State legality: the target entity is in a state from which the requested transition or action is defined, including terminal-state lockdown, else `ERR_INVALID_STATE`.
7. Volunteer eligibility for assignment — evaluated on delivery planning, session confirmation, and session substitution — else `ERR_VOLUNTEER_INELIGIBLE`.
8. Cross-entity state gates on agreement activation: the school's district is checked first, reporting `ERR_DISTRICT_NOT_PARTNER`, and the sponsor partner second, reporting `ERR_SPONSOR_NOT_ACTIVE`; the district precedes the sponsor because the school foreign key precedes the sponsor foreign key in the agreement's declared input order.
9. Temporal rules, covering session confirmation, rescheduling, substitution, delivery and no-show recording, and capstone creation and confirmation. Within this tier a fixed sub-order applies: date validity (`ERR_SESSION_DATE_INVALID`) is evaluated first, then volunteer time overlap (`ERR_SESSION_OVERLAP`), then cadence (`ERR_CADENCE_VIOLATION`); facility capacity failures report `ERR_FACILITY_CAPACITY_EXCEEDED`.
10. Constraint rules — enrollment within program bounds, grade-band overlap, the territory district cap, kit inventory uniqueness per office-and-program pair, the single live capstone per delivery, kit stock sufficiency, write-off bounds, role-assignment completeness, survey score range, and the scheduling gates on teacher confirmation, kit reservation, and session counts — each reporting its own error id at the point described in §3.
11. Fiscal rules: the funding floor at activation and amendment ratification, and the pledge ceiling on funding records and amendments, reporting `ERR_FUNDING_BELOW_FLOOR` or `ERR_FUNDING_EXCEEDS_PLEDGE`.

### 2.8. Resource Addressing and Referenced-Id Validation

The API mounts all resources flat under `/ja-programs`; relationships travel as foreign keys in request bodies rather than as nested path segments. When a request carries a resource identifier in its path — `district_id`, `school_id`, `partner_id`, `volunteer_id`, `program_id`, `agreement_id`, `delivery_id`, `session_id`, `inventory_id`, `capstone_id`, or `student_id` — existence is validated left-to-right, and the first identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404). Foreign keys supplied in the request body are then validated in their declared input order.

### 2.9. Kit Stock Accounting Invariants

Curriculum-kit stock is accounted per warehouse pair: one kit inventory row per area-office-and-program combination, unique across the system. Each row keeps six counters — `assembled_count`, `available_count`, `reserved_count`, `distributed_count`, `written_off_count`, and `consumed_count` — and one invariant holds at all times: the lifetime `assembled_count` always equals the sum of the other five counters. Every stock movement described in §3.6 preserves this invariant.

### 2.10. Numbers, Money, and Rounding

Money is integer cents everywhere; no fractional cents exist. Volunteer hours are decimal but rounded per session first: each session's hours are its duration in minutes divided by 60, rounded half-up to exactly two decimal places, and only then summed into any total — never sum-then-round. Evaluation figures round half-up as well: growth averages and the completion percentage to one decimal place, hour totals to two. Cadence gaps between sessions are measured in whole days with inclusive bounds, kit requirements are whole kits produced by rounding per-session pack counts up, and facility capacities are integer seat counts where a booking exactly equal to capacity still passes.

## 3. Business Logic & Workflows

### 3.1. Building the Territory: Area Offices, Districts, and Schools

A `PlatformAdmin` establishes the territory by creating area offices, each with a display `name`, a short `region_code` such as METRO-NORTH, and a `max_districts` capacity bounding how many live district relationships the office may carry.

An `AreaDirector` then cultivates districts under an office by supplying the managing `area_office_id` and the district `name`. A new district starts in PROSPECT. The territory cap is enforced at creation: if the office already manages `max_districts` districts whose `relationship_status` is anything other than CHURNED, the create is rejected with `ERR_TERRITORY_LIMIT_REACHED` — the count of non-churned districts must remain strictly below the cap for the addition to succeed.

The district relationship is a branching-but-revertible lifecycle, driven by a transition request naming an `action`. ACTIVATE moves PROSPECT to PARTNER; FLAG_RISK moves PARTNER to AT_RISK; RESTORE moves AT_RISK back to PARTNER; and CHURN moves either PARTNER or AT_RISK to CHURNED, the terminal state — both churn branches behave identically. A district sitting in AT_RISK triggers no cascade of its own, but because agreement activation requires a PARTNER district (§3.3), no agreement at its schools can be activated while the risk flag stands. Churn is the consequential path: every partnership agreement at a school of the churned district whose `status` is PROPOSED, ACTIVE, or AMENDMENT_PENDING transitions to TERMINATED, and each so-terminated agreement runs its own termination cascade — deliveries cancelled, their sessions cancelled, their kits released — described in §3.3 and §3.4.

Schools sit under districts. The `AreaDirector` registers a school with its owning `district_id`, a `name`, the grade span it serves from `grade_band_low` (the lowest grade, between 1 and 12) to `grade_band_high` (no lower than the low end), and the `instructional_days` on which classroom sessions may run — each entry drawn from MON, TUE, WED, THU, or FRI. These school facts later gate delivery planning through grade-band overlap (§3.4) and session scheduling through instructional-day membership (§3.5).

### 3.2. Corporate Partners and the Volunteer Credential Pipeline

Corporate partners fund the programs and supply the volunteers. A `PartnershipManager` registers a partner with its organization `name` and `industry` label; the partner starts in PROSPECT. ACTIVATE moves the partner to ACTIVE; SUSPEND moves an ACTIVE partner to SUSPENDED; REINSTATE returns a SUSPENDED partner to ACTIVE; and EXIT moves a partner from ACTIVE or SUSPENDED to EXITED, the terminal state — both exit branches carry the same cascade.

Suspension is deliberately gentle: it triggers no volunteer state changes and leaves existing SCHEDULED sessions untouched, but because volunteer eligibility requires an ACTIVE partner, a suspended partner's volunteers cannot take new assignments while the suspension stands.

Exit is the consequential path, a three-link cascade. First, every volunteer recruited by the partner whose `engagement_status` is still ACTIVE becomes DEPARTED. Second, each departed volunteer's sessions in SCHEDULED move to NEEDS_SUBSTITUTE. Third, every delivery touched by those sessions recomputes its `sessions_blocked_count`, mutating the delivery and bumping its `version`.

Volunteers are recruited from a partner by supplying `corporate_partner_id`, `full_name`, and `email`. A new volunteer starts with `screening_status` INITIATED, `training_status` NOT_STARTED, and `engagement_status` ACTIVE, and both expiry fields — `screening_expires_on` and `training_expires_on` — are null until armed. These are three parallel dimensions, not a single ladder: a training BEGIN or COMPLETE is legal while screening sits FLAGGED, and a screening event never touches training.

A `PartnershipManager` advances one dimension at a time by posting a credential event naming a `kind` and an `event`; only the declared pairs are valid, and anything else is rejected with `ERR_VALIDATION`. For kind SCREENING: CLEAR moves INITIATED to CLEARED and arms `screening_expires_on` to the logical clock's current instant plus 365 days; FLAG moves INITIATED to FLAGGED; REINITIATE moves FLAGGED back to INITIATED, and likewise moves EXPIRED back to INITIATED — both re-initiation branches clear `screening_expires_on` to null. For kind TRAINING: BEGIN moves NOT_STARTED to IN_PROGRESS and — for a volunteer whose credential lapsed — also moves EXPIRED back to IN_PROGRESS; COMPLETE moves IN_PROGRESS to COMPLETED and arms `training_expires_on` to the current instant plus 365 days. For kind ENGAGEMENT: DEPART moves ACTIVE to DEPARTED, the same destination the partner-exit cascade writes.

Three events render a volunteer ineligible and share one cascade: screening lapsing from CLEARED to EXPIRED under the clock sweep, training lapsing from COMPLETED to EXPIRED under the sweep, and engagement ending at DEPARTED. In each case the volunteer's sessions in SCHEDULED move to NEEDS_SUBSTITUTE, and each affected delivery recomputes `sessions_blocked_count`, bumping its `version`. A volunteer's computed `eligible` flag is true exactly when screening is CLEARED, training is COMPLETED, engagement is ACTIVE, and the recruiting partner's `status` is ACTIVE — all four conjuncts, no partial credit. Reads of a volunteer also expose the computed `hours_contributed`, the sum of session hours over that volunteer's DELIVERED sessions with per-session rounding applied before summation (§3.5).

### 3.3. Partnership Agreements: Proposal, Activation, Funding, and Amendment

The partnership agreement binds a school, a program, and a sponsor for one school year. An `AreaDirector` creates it with `school_id`, `program_catalog_id`, `sponsor_partner_id`, the `school_year` label such as 2026-2027, and `funding_pledged_cents` — the sponsor's pledge in integer cents. A new agreement starts in DRAFT with `funding_received_cents` at zero, both pending-amendment fields null, `sponsor_volunteer_hours` at zero, `recognition_tier` NONE, and `deliveries_completed_count` at zero.

PROPOSE moves the agreement from DRAFT to PROPOSED. WITHDRAW abandons it from either DRAFT or PROPOSED into WITHDRAWN — both withdrawal branches behave identically, and WITHDRAWN is terminal.

ACTIVATE moves PROPOSED to ACTIVE and is the most heavily gated transition on the agreement. Three checks fire in the validation ladder's order: the school's district must currently be PARTNER, else `ERR_DISTRICT_NOT_PARTNER`; the sponsor partner must currently be ACTIVE, else `ERR_SPONSOR_NOT_ACTIVE`; and the pledge must meet the program's funding floor, else `ERR_FUNDING_BELOW_FLOOR`. The floor is a base of 75,000 cents plus 25,000 cents for each session the program requires — a four-session program floors at 175,000 cents, a five-session program at 200,000 cents — and a pledge exactly equal to the floor passes.

Once ACTIVE, funding arrives through RECORD_FUNDING, a self-loop that keeps the agreement ACTIVE. The `amount_cents` of a funding record must be at least 1 (else `ERR_VALIDATION`), and the running total may never exceed the pledge: if `funding_received_cents` plus the new `amount_cents` would pass `funding_pledged_cents`, the record is rejected with `ERR_FUNDING_EXCEEDS_PLEDGE`. A successful record adds the amount to `funding_received_cents` and recomputes the sponsor recognition tier.

Amendments follow a propose-then-decide cycle. PROPOSE_AMENDMENT moves ACTIVE to AMENDMENT_PENDING and may carry `new_program_catalog_id`, `new_funding_pledged_cents`, or both — at least one must be present, else `ERR_VALIDATION` — storing them in `pending_program_catalog_id` and `pending_funding_pledged_cents`, with an absent value leaving its pending field null. RATIFY_AMENDMENT returns the agreement to ACTIVE: the effective post-amendment pledge — the pending pledge if one was proposed, otherwise the current pledge — must meet the funding floor of the effective post-amendment program, else `ERR_FUNDING_BELOW_FLOOR`; and if the amendment would cut the pledge below the funding already received, it is rejected with `ERR_FUNDING_EXCEEDS_PLEDGE` instead. Ratification copies the pending values into `program_catalog_id` and `funding_pledged_cents`, clears both pending fields to null, and leaves existing deliveries on their snapshotted program. REJECT_AMENDMENT also returns to ACTIVE, clearing the pending fields while leaving the program and the pledge untouched.

TERMINATE ends an agreement from ACTIVE or AMENDMENT_PENDING — either at the `AreaDirector`'s hand or as the middle link of a district-churn cascade — and both branches run the same consequence: every delivery of the agreement in DRAFT, PLANNED, SCHEDULED, or IN_PROGRESS is cancelled, each running the full delivery-cancellation cascade of §3.4. COMPLETE moves ACTIVE to COMPLETED only when every delivery of the agreement is COMPLETED or CANCELLED with at least one COMPLETED, else `ERR_INVALID_STATE`; completion recomputes the recognition tier one final time. COMPLETED, TERMINATED, and WITHDRAWN are the terminal states.

The sponsor's recognition tier balances volunteer labor against money. Hours for the tier are sponsor volunteer hours: session hours over the agreement's deliveries whose assigned volunteer belongs to `sponsor_partner_id`. The persisted `recognition_tier` is the EARNED variant, counting DELIVERED sessions only, and it is recomputed on every funding record and on every delivered session. The ladder runs in strict precedence: GOLD requires at least 40 sponsor hours and at least 2,000,000 cents of recorded funding; failing that, SILVER requires at least 25 hours together with at least 1,000,000 cents, or at least 60 hours alone; failing that, BRONZE requires at least 10 hours together with at least 500,000 cents, or funding alone of at least 2,000,000 cents; otherwise the tier is NONE. Note the asymmetry: a funding-only path exists to BRONZE, but GOLD never passes without the 40-hour threshold. The evaluation report additionally computes a PROJECTED variant (§3.8) that is never persisted, while the agreement's own `sponsor_volunteer_hours` always counts DELIVERED sessions only.

### 3.4. Planning a Classroom Delivery

Before any delivery can be planned, a `PlatformAdmin` seeds the program catalog. Each entry carries a unique program `code` such as JA-OUR-CITY, a `title`, the targeted grade span from `grade_band_low` to `grade_band_high`, the `session_count` of consecutive classroom sessions the program requires (between 4 and 7), the advisory `minutes_per_session`, a `capstone_required` flag, a `capstone_facility` of SIMULATED_TOWN, FINANCE_PARK, or NONE — NONE exactly when `capstone_required` is false and a real facility when it is true, any other combination rejected as `ERR_VALIDATION` — and the enrollment bounds `min_students` and `max_students`.

A `ProgramCoordinator` opens a classroom delivery by supplying `agreement_id`, `lead_volunteer_id`, a `classroom_label` such as Room 12 - Ms. Alvarez, the coordinating `teacher_email`, the planned `enrolled_count`, and `expected_agreement_version`. The agreement must be ACTIVE, else `ERR_INVALID_STATE`, and the optimistic-concurrency rule of §2.6 applies: a stale `expected_agreement_version` is rejected with `ERR_STALE_AGREEMENT_VERSION`. Creation snapshots the agreement's current program into the delivery's own `program_catalog_id` — later amendments never retro-change an existing delivery — computes the immutable `required_kits`, and starts the delivery in DRAFT with `kit_status` NONE, `teacher_confirmed` false, `kits_consumed` zero, and both session counters at zero. Creating a delivery also increments the parent agreement's `version` by 1.

The kit requirement is computed once, at creation, with the rounding order pinned. The per-session pack count is the `enrolled_count` multiplied by the session-pack ratio of 0.20, rounded up to the next whole kit; `required_kits` is then 3 base kits plus the program's `session_count` times that per-session count. The ceiling is applied per session before the multiplication — never multiply first and round once. For 27 enrolled students in a five-session program, the per-session count is 27 times 0.20, which is 5.4 rounded up to 6, and the requirement is 3 plus 5 times 6: 33 kits. The forbidden sum-then-round order would yield 30; the two differ, and per-session-first is law.

While the delivery is DRAFT or PLANNED, the coordinator builds the roster in bulk, supplying `delivery_id` with a non-empty `students` array whose entries carry `full_name` and `external_ref` — an empty or malformed array is `ERR_VALIDATION`, and a delivery that has left PLANNED is `ERR_INVALID_STATE`. The resulting roster size must stay within the program's `max_students`, else `ERR_ENROLLMENT_OUT_OF_RANGE`, and the response lists the created students in the same order as the input array. Each student starts with `survey_status` NONE and all score and capstone fields null (§3.7, §3.8).

Planning the delivery — DRAFT to PLANNED — enforces four gates: the agreement is ACTIVE, else `ERR_INVALID_STATE`; `enrolled_count` lies within the program's `min_students` to `max_students` inclusive, else `ERR_ENROLLMENT_OUT_OF_RANGE`; the school's grade band overlaps the program's, meaning the school's `grade_band_low` does not exceed the program's `grade_band_high` and the program's `grade_band_low` does not exceed the school's `grade_band_high`, else `ERR_PROGRAM_GRADE_MISMATCH`; and the lead volunteer is eligible, else `ERR_VOLUNTEER_INELIGIBLE`.

Teacher coordination is explicit: CONFIRM_TEACHER is a self-loop on PLANNED that sets `teacher_confirmed` true, recording that the teacher behind `teacher_email` has confirmed the `classroom_label`. Only then can the delivery be scheduled. SCHEDULE moves PLANNED to SCHEDULED when four conditions hold together: `teacher_confirmed` is true, else `ERR_TEACHER_NOT_CONFIRMED`; the count of the delivery's sessions in SCHEDULED equals the program's `session_count`, else `ERR_SESSIONS_INCOMPLETE`; `kit_status` is RESERVED or DISTRIBUTED, else `ERR_KITS_NOT_RESERVED`; and the full cadence re-check across the SCHEDULED sessions passes, else `ERR_CADENCE_VIOLATION` (§3.5).

The first session recorded DELIVERED bubbles the delivery from SCHEDULED to IN_PROGRESS automatically, recomputing `sessions_delivered_count`. From IN_PROGRESS, COMPLETE requires every session of the delivery DELIVERED, else `ERR_SESSIONS_INCOMPLETE`, and — when the snapshotted program's `capstone_required` is set — the delivery's capstone event COMPLETED, else `ERR_CAPSTONE_REQUIRED`; completion recomputes the agreement's `deliveries_completed_count`. CANCEL is available from DRAFT, PLANNED, SCHEDULED, or IN_PROGRESS — at the coordinator's hand or as the downstream link of an agreement termination — and runs a deep cascade: the delivery's sessions in TENTATIVE, SCHEDULED, NEEDS_SUBSTITUTE, or NO_SHOW become CANCELLED; its kits are released back to inventory per §3.6; and its non-terminal capstone event is cancelled with students' capstone fields cleared. COMPLETED and CANCELLED are terminal.

### 3.5. Sessions: Cadence, Delivery Recording, and Substitution

Sessions are the atomic classroom visits. A coordinator adds one to a delivery by supplying `delivery_id`, `volunteer_id`, a `scheduled_date` in ISO YYYY-MM-DD form, `start_minutes` after midnight from 0 through 1439, and `end_minutes` after midnight, which must be later than `start_minutes` and no later than 1440 — violations are `ERR_VALIDATION`. The owning delivery must not be in a terminal status, else `ERR_INVALID_STATE`. A new session starts TENTATIVE — an unordered placeholder — receives a `sequence_no` one greater than the highest existing sequence number within its delivery, and derives `duration_minutes` as end minus start.

Confirming a session moves TENTATIVE to SCHEDULED through a battery of checks. The delivery must be PLANNED, else `ERR_INVALID_STATE`, and the assigned volunteer must be eligible, else `ERR_VOLUNTEER_INELIGIBLE`. The `scheduled_date` must not precede the logical clock's current date, and its weekday must be one of the school's `instructional_days`; either failure is `ERR_SESSION_DATE_INVALID`. The candidate must not overlap any other SCHEDULED session of the same volunteer on the same date, where overlap uses half-open intervals: two sessions clash when the candidate starts before the other ends and the other starts before the candidate ends, so back-to-back sessions are allowed — a clash is `ERR_SESSION_OVERLAP`. Finally the cadence check runs; a failure there is `ERR_CADENCE_VIOLATION`.

Cadence keeps consecutive classroom visits within a weekly rhythm. Take the delivery's SCHEDULED sessions — TENTATIVE placeholders are excluded — sorted by `scheduled_date` ascending with `created_at` ascending as a pure determinism tie-break, since a same-date pair already violates the minimum gap and the tie-break never changes the verdict. Only adjacent pairs in that ordering are checked, and each gap must be at least 3 days and at most 14 days, both bounds inclusive. At confirm or reschedule time the candidate's date is inserted into the sorted set and only the gaps to its immediate predecessor and immediate successor — whichever exist — are evaluated; at delivery scheduling time the full adjacent-pair sweep runs over the whole SCHEDULED set.

Rescheduling is a self-loop from SCHEDULED to SCHEDULED and also the recovery path from NO_SHOW back to SCHEDULED; both branches are identical. The request must carry `new_date`, `new_start_minutes`, and `new_end_minutes` — any that is absent is `ERR_VALIDATION` — and re-runs the same date, overlap, and cadence checks evaluated against the new values; success replaces the date and minute fields and recomputes `duration_minutes`.

Recording a session as delivered moves SCHEDULED to DELIVERED. The delivery must be SCHEDULED or IN_PROGRESS, else `ERR_INVALID_STATE`, and the logical clock's date must fall inside the session's delivery window: on or after `scheduled_date` and no later than seven days after it, both ends inclusive, else `ERR_SESSION_DATE_INVALID`. Success credits the volunteer session hours — the session's duration in minutes divided by 60, rounded half-up to two decimal places for that session before joining any sum — and then recomputes everything the session feeds: the volunteer's `hours_contributed`, the agreement's `sponsor_volunteer_hours` and EARNED recognition tier, and the delivery's `sessions_delivered_count`. If the delivery was still SCHEDULED, it bubbles up to IN_PROGRESS. NO_SHOW and CANCELLED sessions contribute no hours to any total.

A no-show moves SCHEDULED to NO_SHOW and credits nothing. A coordinator records it manually while the delivery is SCHEDULED or IN_PROGRESS, else `ERR_INVALID_STATE`, and only once the logical clock's date has reached the `scheduled_date`, else `ERR_SESSION_DATE_INVALID`; the clock sweep also marks it automatically — for sessions still in SCHEDULED or NEEDS_SUBSTITUTE — once the clock moves beyond seven days after the scheduled date.

NEEDS_SUBSTITUTE is entered only by system cascade, never by direct request, when the assigned volunteer becomes ineligible through screening expiry, training expiry, or departure; the delivery's `sessions_blocked_count` is recomputed and its `version` bumps. Recovery is substitution, which moves a SCHEDULED or NEEDS_SUBSTITUTE session back to SCHEDULED. The request carries `new_volunteer_id` and the concurrency field `expected_delivery_version` per §2.6: a stale version is rejected with `ERR_STALE_DELIVERY_VERSION`; the new volunteer must differ from the session's current `volunteer_id`, else `ERR_VALIDATION`; the new volunteer must be eligible, else `ERR_VOLUNTEER_INELIGIBLE`; and the new volunteer must have no half-open overlap with their own SCHEDULED sessions at the session's existing date and time, else `ERR_SESSION_OVERLAP`. Success writes `volunteer_id`, recomputes `sessions_blocked_count`, and increments the delivery's `version` by 1.

CANCEL moves a session from TENTATIVE, SCHEDULED, NEEDS_SUBSTITUTE, or NO_SHOW to CANCELLED, whether requested directly or arriving as a delivery cascade; DELIVERED and CANCELLED are terminal.

### 3.6. Curriculum Kits: Assembly Through Reconciliation

Kit stock lives in inventory rows owned by the warehouse office. A `LogisticsCoordinator` creates a row by naming `area_office_id` and `program_catalog_id`; the pair is unique, and a duplicate create is rejected with `ERR_DUPLICATE_INVENTORY`. All six counters start at zero. A delivery's stock identity is resolved through its school: the row matching the school's area office — school to district to office — and the delivery's snapshotted `program_catalog_id`.

Two stock transitions move kits onto and off the shelf. ASSEMBLE takes a `quantity` of at least 1, else `ERR_VALIDATION`, and increases `assembled_count` and `available_count` by that quantity. WRITE_OFF takes a `quantity` no greater than `available_count`, else `ERR_WRITE_OFF_EXCEEDS_AVAILABLE`, and moves that many kits from `available_count` into `written_off_count`. Both preserve the stock invariant of §2.9.

Deliveries draw stock through a kit lifecycle that runs parallel to delivery status, advancing independently except where a gate crosses the two: reserve before scheduling, distribute after scheduling, reconcile after completion. RESERVE_KITS moves `kit_status` from NONE to RESERVED while the delivery is PLANNED, else `ERR_INVALID_STATE`, and requires the inventory's `available_count` to be at least `required_kits` — a missing inventory row counts as zero stock — with any shortfall rejected as `ERR_KIT_SHORTAGE`; success moves `required_kits` from `available_count` into `reserved_count` and bumps the inventory row's `version`. DISTRIBUTE_KITS moves RESERVED to DISTRIBUTED while the delivery is SCHEDULED, else `ERR_INVALID_STATE`, moving `required_kits` from `reserved_count` into `distributed_count`. RECONCILE_KITS moves DISTRIBUTED to RECONCILED while the delivery is COMPLETED, else `ERR_INVALID_STATE`, and carries a `kits_consumed` between zero and `required_kits` inclusive, else `ERR_VALIDATION`; the delivery records `kits_consumed`, `distributed_count` decreases by `required_kits`, `consumed_count` increases by `kits_consumed`, and the unconsumed remainder returns to `available_count`.

Cancellation releases stock rather than consuming it. When a delivery is cancelled, a `kit_status` of RESERVED becomes RELEASED and `required_kits` move from `reserved_count` back to `available_count`; a DISTRIBUTED status becomes RELEASED as a full return, with `required_kits` moving from `distributed_count` back to `available_count` and none recorded as consumed.

### 3.7. Capstone Events at the Simulated Town and Finance Park

Programs flagged `capstone_required` culminate in a facility day at the simulated town or the finance park. A coordinator creates the event with `delivery_id`, `facility`, `event_date`, `start_minutes`, `end_minutes`, and a `rotation_slot_count` of at least 1. The delivery must be PLANNED, SCHEDULED, or IN_PROGRESS, else `ERR_INVALID_STATE`; `facility` must equal the snapshotted program's `capstone_facility` and the program must require a capstone, else `ERR_VALIDATION`; `event_date` must not precede the logical clock's date, else `ERR_SESSION_DATE_INVALID`; `end_minutes` must fall after `start_minutes`; and a delivery may carry at most one non-CANCELLED capstone event — a live duplicate is `ERR_DUPLICATE_CAPSTONE`. The event starts PLANNED.

Confirming the event — PLANNED to READY — runs the buffered capacity check. Every event occupies an effective interval from its `start_minutes` to 30 minutes past its `end_minutes`, the turnover buffer. Conflicting events are those at the same facility on the same `event_date` with status READY, ROLES_ASSIGNED, or COMPLETED whose effective intervals intersect the candidate's: intersection means the other event starts before the candidate's buffered end and the candidate starts before the other's buffered end, so an event beginning exactly at another's end plus the buffer does not conflict. The candidate delivery's `enrolled_count` plus the enrollments of all conflicting events' deliveries must not exceed the facility's seat capacity — 60 seats at SIMULATED_TOWN, 90 at FINANCE_PARK — with a total exactly equal to capacity allowed and anything greater rejected as `ERR_FACILITY_CAPACITY_EXCEEDED`. Capacity is thus reserved against `enrolled_count` before any roster student is locked into a role.

Assigning roles — READY to ROLES_ASSIGNED — carries the `assignments` payload. The delivery's roster size must equal its `enrolled_count`, the assignments must cover every roster student exactly once, each assignment's role must belong to the facility's role catalog, and each `rotation_group` must lie within 1 through `rotation_slot_count`; any violation is `ERR_ROLE_ASSIGNMENT_INVALID`. Success stamps each assigned student with this event's `capstone_event_id` plus their `rotation_group` and `capstone_role`, and sets the event's `assigned_student_count` to the roster size.

Completing the capstone — ROLES_ASSIGNED to COMPLETED — requires every session of the delivery DELIVERED, else `ERR_SESSIONS_INCOMPLETE`: the facility day is the culminating event, never an interlude. CANCEL from PLANNED, READY, or ROLES_ASSIGNED — directly or via the delivery cascade — clears every assigned student's `capstone_event_id`, `rotation_group`, and `capstone_role` to null and resets `assigned_student_count` to zero. COMPLETED and CANCELLED are terminal.

### 3.8. Student Surveys and the Evaluation Report

Each roster student's survey track begins at `survey_status` NONE with `pre_score` and `post_score` null. SUBMIT_PRE moves NONE to PRE_SUBMITTED, requires the delivery to be PLANNED, SCHEDULED, or IN_PROGRESS, else `ERR_INVALID_STATE`, and carries a `score` that must be present, else `ERR_VALIDATION`, and within 0 to 100 inclusive, else `ERR_SURVEY_SCORE_OUT_OF_RANGE`; it stores `pre_score`. SUBMIT_POST moves PRE_SUBMITTED to PAIRED under a stricter gate — the delivery must be COMPLETED, else `ERR_INVALID_STATE` — with the same score rules, storing `post_score`. VALIDATE moves PAIRED to VALIDATED. EXCLUDE moves PRE_SUBMITTED to EXCLUDED or PAIRED to EXCLUDED, both exclusion branches identical. VALIDATED and EXCLUDED are terminal.

For funders, the system computes — and never persists — an evaluation report per agreement, readable by an `AreaDirector`, a `PartnershipManager`, or a `Funder`, with the `variant` query parameter selecting PROVISIONAL, the default, or FINAL. The report carries `agreement_id`, `variant`, `sessions_delivered`, `sessions_scheduled`, `total_volunteer_hours`, `sponsor_volunteer_hours`, `students_included`, `students_paired`, `avg_growth_score`, `completion_rate_pct`, `recognition_tier_earned`, `recognition_tier_projected`, and `generated_at`.

The variant selects inclusion sets. PROVISIONAL counts roster students across all of the agreement's deliveries whose `survey_status` is PRE_SUBMITTED, PAIRED, or VALIDATED; FINAL counts VALIDATED students only, and either way the count lands in `students_included`. `students_paired` is the number of included students with both scores present, and `avg_growth_score` is the mean of each paired student's post-minus-pre difference, rounded half-up to one decimal place — null when no paired students exist.

Session accounting runs over the agreement's deliveries. `sessions_delivered` counts the agreement's sessions in DELIVERED; `sessions_scheduled` counts those in TENTATIVE, SCHEDULED, or NEEDS_SUBSTITUTE. The hour totals draw on a session pool: DELIVERED sessions only under FINAL, or DELIVERED plus TENTATIVE, SCHEDULED, and NEEDS_SUBSTITUTE under PROVISIONAL. Each session contributes its duration in minutes divided by 60, rounded half-up to two decimal places before any summation. `total_volunteer_hours` sums the whole pool; `sponsor_volunteer_hours` sums only pool sessions whose assigned volunteer belongs to the sponsor partner. `completion_rate_pct` is the delivered-session count times 100 divided by the agreement's total session requirement — the sum of `session_count` across the snapshotted programs of its deliveries — rounded half-up to one decimal place.

Two recognition figures close the report. `recognition_tier_earned` applies the tier ladder of §3.3 to sponsor hours over DELIVERED sessions only — the same variant persisted on the agreement. `recognition_tier_projected` applies the same ladder to sponsor hours counting TENTATIVE, SCHEDULED, NEEDS_SUBSTITUTE, and DELIVERED sessions alike, giving funders a look ahead; the projection lives only in this report and is never stored.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — transitions of any kind, credential events, substitutions, funding records, clock advances — return `200 OK`, as do all reads. The table below is intentionally minimal: request fields, gates, and side effects for each operation are defined by the workflows of §3, and this table supplies only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ja-programs/_clock/set_current_utc` | Advance the logical clock and run time-driven sweeps | PlatformAdmin |
| POST | `/ja-programs/area-offices` | Create an area office | PlatformAdmin |
| POST | `/ja-programs/districts` | Create a school district under an area office | AreaDirector |
| GET | `/ja-programs/districts` | List districts with filters | Any |
| GET | `/ja-programs/districts/{district_id}` | Get a district | Any |
| POST | `/ja-programs/districts/{district_id}/transition` | Transition a district's relationship status | AreaDirector |
| POST | `/ja-programs/schools` | Create a school under a district | AreaDirector |
| GET | `/ja-programs/schools` | List schools with filters | Any |
| GET | `/ja-programs/schools/{school_id}` | Get a school | Any |
| POST | `/ja-programs/corporate-partners` | Create a corporate partner | PartnershipManager |
| POST | `/ja-programs/corporate-partners/{partner_id}/transition` | Transition a partner's status | PartnershipManager |
| POST | `/ja-programs/volunteers` | Recruit a volunteer from a corporate partner | PartnershipManager |
| GET | `/ja-programs/volunteers` | List volunteers with filters | Any |
| GET | `/ja-programs/volunteers/{volunteer_id}` | Get a volunteer with computed fields | Any |
| POST | `/ja-programs/volunteers/{volunteer_id}/credential-events` | Advance one volunteer credential dimension | PartnershipManager |
| POST | `/ja-programs/program-catalogs` | Create a program catalog entry | PlatformAdmin |
| GET | `/ja-programs/program-catalogs/{program_id}` | Get a program catalog entry | Any |
| POST | `/ja-programs/partnership-agreements` | Create a partnership agreement | AreaDirector |
| GET | `/ja-programs/partnership-agreements` | List agreements with filters | Any |
| GET | `/ja-programs/partnership-agreements/{agreement_id}` | Get an agreement | Any |
| POST | `/ja-programs/partnership-agreements/{agreement_id}/transition` | Transition an agreement, record funding, or decide an amendment | AreaDirector |
| GET | `/ja-programs/partnership-agreements/{agreement_id}/evaluation` | Computed evaluation report for funders | AreaDirector, PartnershipManager, Funder |
| POST | `/ja-programs/deliveries` | Create a classroom delivery (OCC-guarded on the agreement) | ProgramCoordinator |
| GET | `/ja-programs/deliveries` | List deliveries with filters | Any |
| GET | `/ja-programs/deliveries/{delivery_id}` | Get a delivery | Any |
| POST | `/ja-programs/deliveries/{delivery_id}/transition` | Transition a delivery, including kit actions | ProgramCoordinator |
| POST | `/ja-programs/sessions` | Create a session under a delivery | ProgramCoordinator |
| GET | `/ja-programs/sessions` | List sessions with filters | Any |
| GET | `/ja-programs/sessions/{session_id}` | Get a session | Any |
| POST | `/ja-programs/sessions/{session_id}/transition` | Transition a session | ProgramCoordinator |
| POST | `/ja-programs/sessions/{session_id}/substitute` | Replace the assigned volunteer (OCC-guarded on the delivery) | ProgramCoordinator |
| POST | `/ja-programs/kit-inventories` | Create the kit stock row for an office-and-program pair | LogisticsCoordinator |
| GET | `/ja-programs/kit-inventories` | List kit inventories with filters | Any |
| GET | `/ja-programs/kit-inventories/{inventory_id}` | Get a kit inventory row | Any |
| POST | `/ja-programs/kit-inventories/{inventory_id}/transition` | Assemble or write off kit stock | LogisticsCoordinator |
| POST | `/ja-programs/capstone-events` | Create a capstone facility event for a delivery | ProgramCoordinator |
| GET | `/ja-programs/capstone-events` | List capstone events with filters | Any |
| GET | `/ja-programs/capstone-events/{capstone_id}` | Get a capstone event | Any |
| POST | `/ja-programs/capstone-events/{capstone_id}/transition` | Transition a capstone event | ProgramCoordinator |
| POST | `/ja-programs/students` | Bulk-add roster students to a delivery | ProgramCoordinator |
| GET | `/ja-programs/students` | List students with filters | Any |
| GET | `/ja-programs/students/{student_id}` | Get a student participant | Any |
| POST | `/ja-programs/students/{student_id}/transition` | Transition a student's survey lifecycle | ProgramCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the guarded workflow lives; this catalogue is intentionally minimal.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DELIVERY_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VOLUNTEER_INELIGIBLE` | 409 Conflict |
| `ERR_DISTRICT_NOT_PARTNER` | 409 Conflict |
| `ERR_SPONSOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_CADENCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SESSION_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_GRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_TERRITORY_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INVENTORY` | 409 Conflict |
| `ERR_DUPLICATE_CAPSTONE` | 409 Conflict |
| `ERR_ROLE_ASSIGNMENT_INVALID` | 422 Unprocessable Entity |
| `ERR_SURVEY_SCORE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_KIT_SHORTAGE` | 422 Unprocessable Entity |
| `ERR_WRITE_OFF_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_TEACHER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_KITS_NOT_RESERVED` | 409 Conflict |
| `ERR_SESSIONS_INCOMPLETE` | 409 Conflict |
| `ERR_CAPSTONE_REQUIRED` | 409 Conflict |
| `ERR_FUNDING_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_FUNDING_EXCEEDS_PLEDGE` | 422 Unprocessable Entity |
