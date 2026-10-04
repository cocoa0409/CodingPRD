# Charter Candidate Progression API — Product Requirements Document

## 1. Introduction

A professional charter program stands or falls on the credibility of its gates: who may enter the program, who may sit which examination and when, whose scores count toward progression, whose experience qualifies them for the charter, and whose conduct remains beyond reproach. This document specifies the Charter Candidate Progression API, a system that administers the complete lifecycle of a charter candidate — registration and paid program enrollment under education or work-experience eligibility pathways, computer-based examination windows with seat capacity, rescheduling and exam-day policy enforcement, score publication against a minimum passing standard, work-experience verification with independent references, professional-conduct investigation and sanction, charter award, and post-charter society membership with continuing-education obligations.

Two design commitments run through every workflow. First, the entire program runs on a single **logical clock**: every deadline, fee tier, expiry, suspension and standing derivation reads that clock and never the wall clock, so the program's temporal behavior is fully deterministic and testable. Second, every derived figure — ledger balances, progression markers, curriculum access lists, continuing-education standing — is recomputed from current underlying data at the moment it is observed and is visible in the same response envelope as the write that triggered it; nothing is cached. Sensitive decisions are deliberately segregated: the operator who investigates a misconduct case may never adjudicate it, a candidate may never vouch for themselves as a reference, and the staff who check candidates in on exam day play no part in scoring or adjudication.

All resources described here are mounted under the `/charter` URL prefix, with the sole exception of the administrative clock capability described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract shapes and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles, spelled as follows: `Candidate`, `ProgramAdmin`, `Proctor`, `ExperienceReviewer`, `ReferenceProvider`, `ConductInvestigator`, and `ConductAdjudicator`. A request missing either header, or carrying a role name outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are **entity-backed**, tying the header identity to a persisted record. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; ownership checks on any resource that references a candidate compare the resource's candidate foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This ownership rule applies whenever a `Candidate` acts on a candidate-scoped resource — their own candidate record, their own enrollment, their own appointment, their own experience submission, their own misconduct case, their own membership. When `X-User-Role` is `ReferenceProvider`, `X-User-ID` is the `id` of the `ReferenceContact` record being answered; a reference response submitted under any other identifier fails the same ownership check with `ERR_OWNERSHIP_MISMATCH`.

The remaining five roles are **opaque**. When `X-User-Role` is `ProgramAdmin`, `Proctor`, `ExperienceReviewer`, `ConductInvestigator` or `ConductAdjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `investigator_user_id` when a case is opened, as `adjudicator_user_id` when a case is decided, or as `reviewer_user_id` when an experience review is issued — but it never compares such an identifier against any entity's `id` for ownership purposes.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program's Logical Clock

All temporal evaluation in the program — scheduling deadlines, reschedule deadlines, early-fee boundaries, appeal windows, reference expiry, suspension standing, continuing-education years, curriculum cycle effectiveness — reads a single server-held logical clock. Before any administrative call has been made, the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A test-driving capability, restricted to `ProgramAdmin`, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Lazy state derivations described later in this document — most notably reference expiry — are evaluated against the new clock value on subsequent reads and actions, not retroactively at the moment the clock moves.

### 2.5. Common Resource Properties

Every resource in the system — candidates, program enrollments, exam levels, curriculum cycles, exam windows, test centers, exam appointments, exam attempts, work-experience submissions, reference contacts, misconduct cases, societies and society memberships — carries the same four system-managed properties:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: a system-managed integer that increments by one with every mutation of the resource.

A mutation is any change to the resource's own fields, including changes to derived figures stored on it. These properties provide a uniform audit trail and the basis for optimistic concurrency control (§2.7).

### 2.6. The Validation Pipeline: Headers First, Money Last

Every request passes through a fixed validation pipeline, and the **first** failing check wins — its error is the one returned, and later checks are never consulted for that request. The pipeline stages, in order, are:

1. **Header presence and role validity.** `X-User-ID` and `X-User-Role` must be present and the role must be one of the seven declared names, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The acting role must be listed for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. **Path identifier existence, left to right.** Each identifier embedded in the URL path is resolved in left-to-right order, and the first one that does not exist fails the request with its own entity-specific error: `ERR_CANDIDATE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_EXAM_LEVEL_NOT_FOUND`, `ERR_EXAM_WINDOW_NOT_FOUND`, `ERR_TEST_CENTER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_REFERENCE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SOCIETY_NOT_FOUND` or `ERR_MEMBERSHIP_NOT_FOUND`. A nested request therefore reports the missing container before ever considering the nested resource.
4. **Request shape.** Required fields must be present, types must be correct, enum values must belong to their declared sets, numeric ranges must hold, payload fields unknown to the endpoint are rejected outright, pathway-conditional fields must accompany their pathway, a reschedule must carry at least one change field, and an adjudication with a sanctioning outcome must name a sanction type. Violations surface as `ERR_INVALID_REQUEST`; a score outside its permitted range surfaces as `ERR_SCORE_OUT_OF_RANGE`; a non-positive payment surfaces as `ERR_INVALID_PAYMENT_AMOUNT`.
5. **Body foreign keys, in declared field order.** Foreign keys carried in the request body are resolved in the exact order the endpoint's input fields are listed — for appointment booking, `program_enrollment_id` first, then `exam_window_id`, then `test_center_id` — each raising the corresponding not-found error from stage 3's family.
6. **Ownership.** Entity-backed callers must own their target per §2.1, else `ERR_OWNERSHIP_MISMATCH`.
7. **Optimistic concurrency.** The expected-version check of §2.7 fires here — after ownership, before any business rule — else `ERR_STALE_VERSION`.
8. **State preconditions.** The target resource must sit in the state its transition demands: enrollment `ENROLLED` for booking or award (`ERR_ENROLLMENT_NOT_ENROLLED`); window `OPEN` for booking or retargeting (`ERR_WINDOW_NOT_OPEN`) and `OPEN` for cancellation (`ERR_WINDOW_NOT_CANCELLABLE`); appointment `SCHEDULED` for reschedule, cancel or check-in (`ERR_APPOINTMENT_NOT_SCHEDULED`); attempt `AWAITING_SCORE` for scoring (`ERR_ATTEMPT_ALREADY_SCORED`); submission `DRAFT` for submit and `SUBMITTED` for review (`ERR_INVALID_SUBMISSION_STATE`); submission `RETURNED_FOR_REVISION` for amend (`ERR_SUBMISSION_NOT_EDITABLE`); reference `PENDING` for a response (`ERR_REFERENCE_NOT_PENDING`); case `OPENED` or `APPEALED` for adjudication and `SANCTIONED` for appeal (`ERR_INVALID_CASE_STATE`); membership `ACTIVE` for renewal (`ERR_INVALID_MEMBERSHIP_STATE`).
9. **Clock rules.** Booking and retargeting must occur no later than the relevant scheduling deadline (`ERR_WINDOW_SCHEDULING_CLOSED`); the exam date must fall inside its window (`ERR_EXAM_DATE_OUTSIDE_WINDOW`); rescheduling must occur no later than the original window's reschedule deadline (`ERR_RESCHEDULE_DEADLINE_PASSED`); check-in requires the clock's calendar date to equal the exam date (`ERR_CHECKIN_NOT_ON_EXAM_DATE`); scoring requires the window to have concluded (`ERR_WINDOW_NOT_CONCLUDED`); appeals must arrive within thirty days of the sanction (`ERR_APPEAL_WINDOW_EXPIRED`).
10. **Exam-day safety, identity before calculator.** At check-in the identity document is compared first (`ERR_IDENTITY_VERIFICATION_FAILED`), and only then the calculator policy is applied (`ERR_CALCULATOR_POLICY_VIOLATION`).
11. **Capacity, overlap and uniqueness.** Window overlap (`ERR_WINDOW_OVERLAP`), blackout conflicts (`ERR_CENTER_BLACKOUT_CONFLICT`), seat capacity (`ERR_NO_SEAT_CAPACITY`), one active booking per candidate per level (`ERR_DOUBLE_BOOKING_LEVEL`), one open case per appointment (`ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT`), and the uniqueness family: `ERR_DUPLICATE_CANDIDATE_EMAIL`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_EXAM_LEVEL`, `ERR_DUPLICATE_CURRICULUM_YEAR`, `ERR_DUPLICATE_MEMBERSHIP`, `ERR_DUPLICATE_CONDUCT_STATEMENT`.
12. **Cross-entity referential rules.** Eligibility thresholds (`ERR_ELIGIBILITY_NOT_MET`), the level-progression chain (`ERR_LEVEL_ALREADY_PASSED`, `ERR_PREREQUISITE_LEVEL_NOT_PASSED`, `ERR_MAX_ATTEMPTS_REACHED`, `ERR_RETAKE_WINDOW_TOO_SOON`), same-level retargeting (`ERR_WINDOW_LEVEL_MISMATCH`), reference-count gates (`ERR_INSUFFICIENT_REFERENCES`, `ERR_INSUFFICIENT_VERIFIED_REFERENCES`), the award gates (`ERR_LEVELS_NOT_ALL_PASSED`, `ERR_EXPERIENCE_REQUIREMENT_UNMET`, `ERR_MISSING_CONDUCT_STATEMENT`, `ERR_OPEN_MISCONDUCT_CASE`), charter-gated membership (`ERR_CHARTER_REQUIRED`), the continuing-education renewal gate (`ERR_CE_REQUIREMENT_NOT_MET`), and segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
13. **Money gates, always last.** Zero-balance requirements (`ERR_OUTSTANDING_BALANCE`) and exact-dues requirements (`ERR_INCORRECT_DUES_AMOUNT`) are evaluated only after every other rule has passed.

Within a single endpoint, the more specific orderings described in §3 (for example the retake-eligibility chain or the award chain) nest inside the corresponding stage above.

### 2.7. Optimistic Concurrency Control

Three write operations supersede a resource the caller has previously observed, and each therefore requires the caller to state the version it observed:

- Rescheduling an appointment requires `expected_appointment_version`, carrying the caller's last observed `version` of that appointment. If the appointment's current `version` no longer matches — because a prior reschedule, a cancellation, or a check-in side effect has advanced it since the caller's read — the request is rejected as stale with `ERR_STALE_VERSION` (HTTP 412); the supersede must not proceed on an unobserved state.
- Amending a returned work-experience submission requires `expected_submission_version`, carrying the caller's last observed `version` of that submission; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since the `RETURNED_FOR_REVISION` state the caller observed has been superseded by another committed write.
- Adjudicating a misconduct case requires `expected_case_version`, carrying the caller's last observed `version` of that case; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since an appeal or a prior adjudication has advanced the case beyond the caller's observation.

The expected-version field is non-optional on these three operations and is checked after ownership and before all business rules. Endpoints not listed here do not take a version field.

### 2.8. The Enrollment Ledger: Charges, Payments and Credits

Every program enrollment maintains a small ledger of integer-cent figures, recomputed as events post. `lifetime_charges_cents` accumulates every posted charge — the one-time program fee, exam fees, and reschedule fees. `lifetime_payments_cents` accumulates every payment received. `lifetime_credits_posted_cents` accumulates every compensation credit granted by an appointment or window cancellation, while `lifetime_credits_applied_cents` tracks the portion of those credits absorbed by outstanding charges. From these, three derived balances follow at all times: `credit_balance_cents` is the posted credits not yet absorbed by charges — credits posted minus credits applied — and overpayments land here as well; `outstanding_balance_cents` is what the candidate still owes — lifetime charges minus lifetime payments minus applied credits; and `net_billed_cents` is the compensating-invariant anchor — lifetime charges minus credits posted.

Rounding is **per line, then sum**: each individual charge line is its list price multiplied by one minus the enrollment's `scholarship_pct`, rounded half-up to whole cents, and only then added into `lifetime_charges_cents`. Summing list prices first and rounding the total once is a rejected interpretation — the two orders can differ by a cent or more, and the per-line order is the contract. Reschedule fees are never scholarship-discounted.

Credits flow in a fixed direction. When a credit posts to an enrollment, it absorbs outstanding charges first — the applied portion is the lesser of the credit and the current outstanding balance, which reduces `outstanding_balance_cents` and increases `lifetime_credits_applied_cents` — and any remainder raises `credit_balance_cents`. Conversely, when a new charge posts to an enrollment holding a positive credit balance, the credit balance is drawn down against the new charge first, so only the unabsorbed remainder adds to what the candidate owes.

Money gates close the validation pipeline (§2.6, stage 13): booking an appointment, rescheduling an appointment, and awarding the charter each require the enrollment's `outstanding_balance_cents` to be exactly zero before any new charge posts, failing with `ERR_OUTSTANDING_BALANCE` (HTTP 402). Society dues are gated separately: a join or renewal payment must equal the society's dues figure exactly, failing with `ERR_INCORRECT_DUES_AMOUNT` (HTTP 422).

### 2.9. Precision, Rounding and Calendar Conventions

All monetary values are integer cents; the only rounding applied anywhere in the system is the per-line half-up rounding of §2.8. Experience and eligibility durations are whole calendar months, expressed as integers. Continuing-education credit hours carry one decimal place, and their sums are exact. Datetime comparisons are made at second precision. Date fields use the ISO `YYYY-MM-DD` form; datetimes are ISO 8601 in UTC.

Wherever a duration in whole calendar months between a start date and an end date is required — eligibility evaluation and both experience-months variants use it — the count is computed as follows: take the difference in calendar years multiplied by twelve, add the difference in month numbers, and subtract one if the end date's day-of-month is earlier than the start date's day-of-month. So the tenth of January 2022 to the tenth of January 2024 counts as twenty-four months, while the tenth of January 2022 to the ninth of January 2024 counts as twenty-three.

Exam windows are **half-open** intervals: a window covers every instant from its `window_opens_at` (inclusive) up to but not including its `window_closes_at`. Two windows of the same level whose boundaries merely touch do not overlap.

### 2.10. Progression, Curriculum Access and Cascade Discipline

A candidate's progression marker, `highest_level_passed_code`, is a derived figure: it names the highest level, in the ordering `LEVEL_I` then `LEVEL_II` then `LEVEL_III`, for which the candidate holds at least one passing attempt whose validity is `VALID` or `REINSTATED`, and it is `null` when no such attempt exists. It is recomputed — never cached — immediately after any score publication, invalidation, or reinstatement commits, and the recompute may move the marker in either direction: an invalidation can drop it, a later reinstatement restores it.

The same three triggers recompute each enrollment's `curriculum_access_cycle_ids`. While an enrollment is `PENDING_PAYMENT`, the access list is empty. While it is `ENROLLED`, the list contains the `PUBLISHED` curriculum cycles of every level up to and including the candidate's **lowest unpassed** level. Once the enrollment reaches `CHARTER_AWARDED`, the list widens to all `PUBLISHED` cycles. When a curriculum cycle is archived, it drops out of every enrollment's access list at once.

Cascades are immediate: when one operation mutates several entities — a sanction invalidating attempts, a window cancellation crediting enrollments, a dismissal restoring standing — every affected entity reflects the change in the same response envelope, and each mutated resource has its own `updated_at` refreshed and `version` incremented.

## 3. Business Logic & Workflows

### 3.1. Candidate Registration and Program Enrollment

A `ProgramAdmin` registers each candidate with an `email`, a `full_name`, a `date_of_birth` in ISO date form, and a `gov_id_number` — the government identity document number that will be compared verbatim at exam-day check-in. Email addresses are unique across the program; a duplicate registration is rejected with `ERR_DUPLICATE_CANDIDATE_EMAIL`. A freshly registered candidate has `charter_awarded` false, `conduct_revoked` false, no suspension, `highest_level_passed_code` equal to `null`, and an empty append-only `conduct_statements` collection. Reading a candidate record exposes their conduct standing, progression marker and charter flag to every role.

Enrolling the candidate in the program is a shared capability: a `Candidate` may enroll themselves — the path's candidate must be their own record, else `ERR_OWNERSHIP_MISMATCH` — and a `ProgramAdmin` may enroll anyone. The enrollment request declares a `pathway` of either `EDUCATION` or `WORK_EXPERIENCE`, and each pathway demands its own inputs. The education pathway requires `degree_completed` and `graduation_date`; the work-experience pathway requires `declared_work_months` and `declared_work_hours`. A request missing its pathway's required fields is malformed (`ERR_INVALID_REQUEST`), as is any request carrying fields the endpoint does not declare. An optional `scholarship_pct` between 0 and 0.5 inclusive, defaulting to 0, records a per-line discount that applies to the program fee and to exam fees — but never to reschedule fees.

Eligibility is evaluated per pathway from the enrollment request alone, against the logical clock's current date. Under `EDUCATION`, the candidate qualifies when their degree is completed, or when the graduation date lies strictly in the future and the whole-calendar-month distance from today to that date is at most 23 months. Under `WORK_EXPERIENCE`, the candidate qualifies when they declare at least 36 months of experience **and** at least 4,000 hours of it. Each pathway evaluates only its own inputs — a candidate can qualify under one pathway and fail the other. An ineligible request is rejected with `ERR_ELIGIBILITY_NOT_MET` (HTTP 422) and no enrollment is created. A candidate may hold exactly one program enrollment, ever: a second attempt is rejected with `ERR_DUPLICATE_ENROLLMENT`.

Creation posts the program's enrollment charge: a list price of 35,003 cents, discounted per line by the enrollment's `scholarship_pct` with half-up rounding before the line enters `lifetime_charges_cents` (§2.8). The enrollment is born in `PENDING_PAYMENT`, and while it remains there its `curriculum_access_cycle_ids` list is empty.

Payments are applied by the candidate or a `ProgramAdmin` in `amount_cents`; a non-positive amount is rejected with `ERR_INVALID_PAYMENT_AMOUNT`. Each payment raises `lifetime_payments_cents` and reduces `outstanding_balance_cents`; any amount paid beyond what is owed lands in `credit_balance_cents`. The moment the outstanding balance reaches zero, the enrollment automatically advances from `PENDING_PAYMENT` to `ENROLLED` and its curriculum access list is recomputed per §2.10. Enrollments can be listed with `candidate_id` and `status` filters, which is the supported way to reverse-reach a candidate's enrollment from its foreign key. Much later, a successful charter award stamps the enrollment's `chartered_at` with the logical clock (§3.8).

### 3.2. Exam Levels, Curriculum Cycles, Windows and Test Centers

Before any scheduling can occur, a `ProgramAdmin` configures the exam structure. Each **exam level** carries a `level_code` of `LEVEL_I`, `LEVEL_II` or `LEVEL_III` — unique per program, with duplicates rejected as `ERR_DUPLICATE_EXAM_LEVEL` — and the enum order is the progression order: `LEVEL_I` has no prerequisite, and each later level requires its predecessor. The level also fixes its `mps_scaled_score`, the minimum passing scaled score on the 0-to-1000 scale; its `max_attempts`, between 1 and 10, counted over attempts whose validity is `VALID` or `REINSTATED`; and its fee card — `early_fee_cents`, which must be positive, and `standard_fee_cents`, which must be at least the early fee.

Each level's content evolves on an annual cycle. Publishing a **curriculum cycle** for a level records a `cycle_year` (unique within that level, else `ERR_DUPLICATE_CURRICULUM_YEAR`), an `effective_from` instant marking the inclusive start of the cycle's effectiveness, an `effective_to` instant marking the exclusive end — which must lie strictly after the start — and a `content_version` edition label. A new cycle is born `PUBLISHED`. When a cycle with a newer `cycle_year` is published for the same level, the previously published cycle of that level is automatically archived — `PUBLISHED` to `ARCHIVED` — and every enrollment's `curriculum_access_cycle_ids` is recomputed, dropping the archived cycle from all access lists. Cycles can be listed with `exam_level_id` and `status` filters.

An **exam window** defines a bookable half-open interval for one level, referenced by `exam_level_id`. Its `window_opens_at` is the first exam instant, inclusive; its `window_closes_at` is the last, exclusive. Three deadlines govern it: `scheduling_deadline_at`, which must fall no later than the window's opening and after which no new bookings are accepted; `reschedule_deadline_at`, which must fall no later than the window's close and after which no reschedules are accepted; and `early_fee_deadline_at`, which must fall no later than the scheduling deadline and marks the boundary of the early fee tier. A window is born `OPEN` and ends either `RESULTS_PUBLISHED` or `CANCELLED`. Two windows of the same level may not overlap under the half-open convention — adjacent windows whose boundaries merely touch are allowed — and a conflicting creation is rejected with `ERR_WINDOW_OVERLAP`. Windows can be listed with `exam_level_id` and `status` filters.

**Test centers** provide the seats. Each is created with a `name`, a `city`, a `daily_seat_capacity` of at least one — the seats available per exam date — and an optional `blackout_windows` list of maintenance closures. Each blackout entry carries a `blackout_start_date`, a `blackout_end_date`, and a `reason`; both dates are ISO dates and **both bounds are inclusive**, and a one-day buffer on each side of the closed range also blocks bookings. Any attempt to seat a candidate at that center on a blocked date is rejected with `ERR_CENTER_BLACKOUT_CONFLICT`.

### 3.3. Booking an Exam Appointment

A booking pairs an enrollment with a window, a center and a date. The booking caller — a `Candidate` booking their own enrollment, or a `ProgramAdmin` — supplies `program_enrollment_id`, `exam_window_id`, `test_center_id`, an `exam_date` in ISO form, and a declared `calculator_model`, which must be one of the two approved models, `TI_BA_II_PLUS` or `HP_12C`. Body foreign keys are resolved in the order the fields are listed — enrollment, then window, then center — each raising its own not-found error before the next is consulted.

The business gates then apply in pipeline order (§2.6). The enrollment must be `ENROLLED` (`ERR_ENROLLMENT_NOT_ENROLLED`); the window must be `OPEN` (`ERR_WINDOW_NOT_OPEN`); the logical clock must be no later than the window's `scheduling_deadline_at` (`ERR_WINDOW_SCHEDULING_CLOSED`). The exam date, interpreted as midnight UTC at the start of that day, must fall on or after `window_opens_at` and strictly before `window_closes_at` (`ERR_EXAM_DATE_OUTSIDE_WINDOW`). The chosen center and date must not fall inside a blackout's inclusive range or its one-day buffers (`ERR_CENTER_BLACKOUT_CONFLICT`), and at least one seat must remain at that center on that date (`ERR_NO_SEAT_CAPACITY`). A candidate may hold only one active appointment per level — active meaning `SCHEDULED` or `CHECKED_IN` — and a second active booking for the same level is rejected with `ERR_DOUBLE_BOOKING_LEVEL`.

**Retake eligibility** is evaluated next, in a pinned order whose steps feed each other and must not be rearranged. First, the candidate's passed levels are computed: the set of level codes holding a passing attempt whose validity is `VALID` or `REINSTATED`. Second, if the target level is already in that set, the booking is rejected with `ERR_LEVEL_ALREADY_PASSED`. Third, the target level's predecessor in the enum ordering — if it has one — must appear in the passed set, else `ERR_PREREQUISITE_LEVEL_NOT_PASSED`. Fourth, the count of the candidate's attempts at the target level with validity `VALID` or `REINSTATED` must be smaller than the level's `max_attempts` — invalidated attempts do not count — else `ERR_MAX_ATTEMPTS_REACHED`. Fifth, if the candidate has a most-recent failed attempt at the target level — latest by creation among attempts with result `FAIL` and validity `VALID` or `REINSTATED` — the target window's opening must lie strictly after that failed attempt's window closed, else `ERR_RETAKE_WINDOW_TOO_SOON`. Because invalidation (which an appeal can later reverse into `REINSTATED`) changes the first, fourth and fifth steps, eligibility is always recomputed from current attempt validity at scheduling time, never cached.

Seat accounting is exact. The seats consumed at a center on a date are the appointments at that center on that date whose booking status is `SCHEDULED`, `CHECKED_IN`, `COMPLETED` or `NO_SHOW`; a `CANCELLED` appointment releases its seat, while a no-show keeps the seat consumed — the seat was held through exam day and the fee is forfeited. Availability is the center's `daily_seat_capacity` minus the consumed count. A booking requires at least one seat free: the booking that fills the last seat succeeds, and the next one fails with `ERR_NO_SEAT_CAPACITY`.

Only after every other gate does the money rule fire: the enrollment's `outstanding_balance_cents` must be zero before the exam fee posts, else `ERR_OUTSTANDING_BALANCE`. The appointment's `fee_tier` is `EARLY` when its `created_at` falls on or before the window's `early_fee_deadline_at` — an appointment created exactly at the deadline books at the early tier — and `STANDARD` otherwise. The `exam_fee_cents` line is the level's fee for that tier, scholarship-discounted per line with half-up rounding per §2.8, and posts to the enrollment ledger with any credit balance drawn down first.

A new appointment is born with `booking_status` `SCHEDULED` and `compliance_status` `CLEAR`, `reschedule_count` zero and `reschedule_fees_total_cents` zero. The candidate's `candidate_id` is denormalized onto the appointment so that the appointments listing can be filtered by `candidate_id` — alongside `program_enrollment_id`, `exam_window_id`, `test_center_id`, `booking_status` and `status` filters — and the appointment's `version` begins its mutation count.

### 3.4. Rescheduling and Cancelling Appointments

Rescheduling supersedes the appointment's current schedule, so it is a guarded write: the request must carry `expected_appointment_version` matching the appointment's current `version`, and a stale expectation is rejected with `ERR_STALE_VERSION` before any business rule is consulted (§2.7). The request must also change something — at least one of `exam_window_id`, `test_center_id`, `exam_date` or `calculator_model`, else `ERR_INVALID_REQUEST`. Either the owning `Candidate` or a `ProgramAdmin` may reschedule.

The business rules then apply in order. The appointment must still be `SCHEDULED` (`ERR_APPOINTMENT_NOT_SCHEDULED`). The logical clock must be no later than the **original** window's `reschedule_deadline_at` (`ERR_RESCHEDULE_DEADLINE_PASSED`) — the deadline of the window the appointment currently sits in governs, even when the reschedule retargets a different window. When the window does change, four further checks bind the retarget: the target window must be `OPEN` (`ERR_WINDOW_NOT_OPEN`), it must belong to the same level (`ERR_WINDOW_LEVEL_MISMATCH`), the clock must be no later than the target's `scheduling_deadline_at` (`ERR_WINDOW_SCHEDULING_CLOSED`), and the retake gap of §3.3 is re-checked against the new window (`ERR_RETAKE_WINDOW_TOO_SOON`). The effective exam date must fall inside the effective window's half-open interval (`ERR_EXAM_DATE_OUTSIDE_WINDOW`); the effective center and date must clear the blackout rule (`ERR_CENTER_BLACKOUT_CONFLICT`); and a seat must be free at the effective center and date, **excluding the appointment's own current seat** from the count (`ERR_NO_SEAT_CAPACITY`). Finally, per §2.8, the enrollment's outstanding balance must be zero before the reschedule fee posts (`ERR_OUTSTANDING_BALANCE`).

The reschedule fee is tiered. Let the notice period be the number of whole days between the logical clock's current date and the appointment's **current** exam date. The fee starts at a base of 25,000 cents. If the notice period is shorter than 14 days, a late surcharge of 25,000 cents is added. Then 10,000 cents is added for each prior reschedule on the appointment, counting at most two priors — the `reschedule_count` as it stands before this reschedule. The total is capped at 60,000 cents. So a first reschedule nine days before the exam costs the base plus the surcharge, 50,000 cents; with one prior reschedule the per-prior component brings the quote to exactly 60,000 cents, where the cap just binds; with two prior reschedules the uncapped 70,000 cents is trimmed to the same 60,000-cent cap; and a first reschedule twenty days out costs only the 25,000-cent base. The fee is never scholarship-discounted.

A successful reschedule mutates the appointment's `exam_window_id`, `test_center_id`, `exam_date` and `calculator_model` to their effective values, increments `reschedule_count` by one, posts the quoted fee to the enrollment ledger, adds it to the appointment's `reschedule_fees_total_cents`, releases the seat at the old center and date while consuming one at the new center and date, and increments the appointment's `version` by one.

Cancellation is simpler. The appointment must be `SCHEDULED` (`ERR_APPOINTMENT_NOT_SCHEDULED`); the owning candidate or a `ProgramAdmin` may cancel. The seat is released. Whether money moves depends on timing: a candidate- or admin-initiated cancellation credits the appointment's full `exam_fee_cents` to the enrollment when the logical clock is no later than the window's `scheduling_deadline_at`, and credits nothing once that deadline has passed; reschedule fees are never credited under any circumstances. Posted credits follow the standard mechanics of §2.8 — outstanding charges first, remainder to `credit_balance_cents`.

A `ProgramAdmin` may also cancel an entire window, provided it is still `OPEN` — a window already `RESULTS_PUBLISHED` or `CANCELLED` rejects the attempt with `ERR_WINDOW_NOT_CANCELLABLE`. The cascade walks the window's appointments in creation order: every appointment still `SCHEDULED` flips to `CANCELLED` (appointments already `CHECKED_IN` are not touched), and each so-cancelled appointment is compensated with its **full** `exam_fee_cents`, deadline-independent, posted per the standard credit mechanics. The window cancellation creates no attempts and leaves every appointment's `compliance_status` untouched.

### 3.5. Exam Day: Check-in, Scoring and Results Publication

On exam day, a `Proctor` checks the candidate in. The appointment must be `SCHEDULED` (`ERR_APPOINTMENT_NOT_SCHEDULED`) — note that the appointment's `compliance_status` does **not** gate check-in — and the logical clock's calendar date must equal the appointment's `exam_date` (`ERR_CHECKIN_NOT_ON_EXAM_DATE`). Two exam-day policy checks then fire in a fixed order. Identity comes first: the presented `identity_document_number` must equal the candidate's registered `gov_id_number`, compared verbatim, else `ERR_IDENTITY_VERIFICATION_FAILED`. Only then is the calculator policy applied: the `actual_calculator_model` presented at the desk must equal the appointment's declared `calculator_model` and be one of the two approved models, else `ERR_CALCULATOR_POLICY_VIOLATION`.

A successful check-in advances the booking from `SCHEDULED` to `CHECKED_IN` and creates the appointment's **exam attempt** as a side effect. The new attempt links back through `exam_appointment_id`, denormalizes the `candidate_id` and the window's level into `exam_level_code` for list filtering, and opens with `score_status` `AWAITING_SCORE` and `validity` `VALID`. Its `attempt_sequence` is the one-based count of **all** attempts ever created for that candidate at that level, ordered by creation — invalidated attempts included in the count. Attempts can be listed with `exam_appointment_id` and `candidate_id` filters.

Scoring is a `ProgramAdmin` act performed per attempt once the window has concluded: the logical clock must be no earlier than the window's `window_closes_at` (`ERR_WINDOW_NOT_CONCLUDED`), the attempt must still be `AWAITING_SCORE` (`ERR_ATTEMPT_ALREADY_SCORED`), and the submitted `scaled_score` must lie between 0 and 1000 inclusive — a score outside that range is malformed and rejected as `ERR_SCORE_OUT_OF_RANGE` at the request-shape stage, before state or clock rules are consulted. The result is a pure threshold comparison against the level's `mps_scaled_score`: the attempt's `result` is `PASS` when the scaled score is at least the minimum — a score exactly equal to the boundary passes, and one point below it `FAIL`s.

Scoring one attempt propagates widely. The candidate's `highest_level_passed_code` is recomputed per §2.10, as is the enrollment's `curriculum_access_cycle_ids`. Within the scored attempt's window, the first scoring event flips every appointment still sitting in `SCHEDULED` to `NO_SHOW` — no attempt is created for a no-show, the exam fee is forfeited with no credit, and the seat remains consumed. And when a scoring event leaves **every** attempt belonging to the window in `SCORED`, the window itself auto-publishes, moving from `OPEN` to `RESULTS_PUBLISHED`: as part of publication, any appointment of the window still `SCHEDULED` is flipped to `NO_SHOW` first, and then every `CHECKED_IN` appointment of the window advances to `COMPLETED`.

### 3.6. Work Experience Submissions and Reference Verification

Toward the charter, a `Candidate` builds a **work-experience submission** from their own record: the submission is created under the candidate and opens in `DRAFT`, carrying a `segments` array in which each entry records an `employer_name`, a `role_title`, a `start_date`, an `end_date` no earlier than the start, a `qualifying_activity_pct` between 0 and 100, and a positive `hours` figure. Submissions can be listed with `candidate_id` and `status` filters.

Submitting moves the submission from `DRAFT` to `SUBMITTED` (from any other state the call fails with `ERR_INVALID_SUBMISSION_STATE`) and requires at least two attached reference contacts in any non-`EXPIRED` status, else `ERR_INSUFFICIENT_REFERENCES`. At submission time the system computes `provisional_months`, the **cumulative** variant of the experience figure: among the qualifying segments — those whose `qualifying_activity_pct` is at least 50 — the whole-calendar-month length of each segment (per the convention of §2.9) is summed, and overlapping periods are deliberately counted twice. Segments below the 50-percent qualifying bar feed neither variant.

Review belongs to an `ExperienceReviewer`, who issues a `decision` of `APPROVED`, `REJECTED` or `RETURNED_FOR_REVISION` — optionally annotated with `reviewer_notes` — against a `SUBMITTED` submission (any other state fails with `ERR_INVALID_SUBMISSION_STATE`). Approval carries an extra gate: at least two of the submission's references must stand at `VERIFIED`, else `ERR_INSUFFICIENT_VERIFIED_REFERENCES`. On approval or rejection the system computes and stores `committee_months`, the **contiguous** variant: the qualifying segments are sorted by `start_date` — ties broken by earlier `end_date`, then by the segment's order in the array — and merged into runs wherever the next segment starts on or before one day after the current run's end, so that touching periods count as contiguous; the whole-month lengths of the merged runs are then summed, counting every overlap only once. On a return-for-revision no months figure is stored; in every case the acting reviewer's identifier is recorded in `reviewer_user_id` as the latest decision-maker. The two variants answer the same inputs with different totals: consider one segment running from the tenth of January 2022 to the tenth of January 2024 at eighty percent qualifying activity, and a second from the tenth of July 2023 to the tenth of June 2025 at sixty percent. The first measures twenty-four months and the second twenty-three, so `provisional_months` reports forty-seven; interval-merged into a single run from the tenth of January 2022 to the tenth of June 2025, `committee_months` reports forty-one.

A returned submission cycles back to `DRAFT` through amendment, a guarded write: the request carries the replacement `segments` and must carry `expected_submission_version` matching the submission's current `version`, else `ERR_STALE_VERSION` (§2.7); only a `RETURNED_FOR_REVISION` submission is amendable, else `ERR_SUBMISSION_NOT_EDITABLE`. Amending replaces the segments wholesale, resets both `provisional_months` and `committee_months` to `null`, increments the submission's `version` by one, and leaves the attached references in whatever status they currently hold.

References are attached by the candidate with a `referee_name` and a `referee_email`, and each is born `PENDING` with `expires_at` set to thirty days after its creation. The reference then answers for itself: a `ReferenceProvider` acts under an `X-User-ID` equal to the reference contact's own `id` — anything else fails ownership with `ERR_OWNERSHIP_MISMATCH` — and submits a `decision`, optionally with `attestation_text`. A `VERIFIED` decision stamps `verified_at` with the current clock; a `DECLINED` decision closes the reference without verification. Expiry is lazy: a response arriving when the clock has already passed `expires_at` first transitions the reference to `EXPIRED` and then the call fails with `ERR_REFERENCE_NOT_PENDING`, and the same error greets any response to a reference no longer `PENDING`. References can be listed with `experience_submission_id` and `status` filters.

### 3.7. Professional Conduct Statements and Misconduct Adjudication

Every candidate files an annual professional conduct statement. Filing appends an entry — `disclosure_year`, `has_disclosures`, an optional `disclosure_text`, and the filing timestamp — to the candidate's `conduct_statements` collection, and the pair of candidate and `disclosure_year` must be unique, else `ERR_DUPLICATE_CONDUCT_STATEMENT`. A statement whose `has_disclosures` is true automatically opens a misconduct case against the candidate: the case is born `OPENED` with `origin` `CONDUCT_STATEMENT` and a `null` `investigator_user_id`, there being no human investigator.

Cases may also be opened manually by a `ConductInvestigator` or a `Proctor`, who supply the `candidate_id` and a free-text `allegation`, with an optional `appointment_id` and an optional explicit `origin`. The acting operator's identifier is recorded as `investigator_user_id`. When an `appointment_id` is present the case reports an exam-day incident: its `origin` becomes `EXAM_INCIDENT` and the flagged appointment's `compliance_status` moves from `CLEAR` to `POLICY_FLAGGED`; a manual case without an appointment defaults its `origin` to `EXTERNAL_REPORT`. An appointment may carry only one case in `OPENED`, `SANCTIONED` or `APPEALED` state at a time — a second is rejected with `ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT`. Cases can be listed with `candidate_id`, `appointment_id` and `status` filters.

Adjudication belongs exclusively to a `ConductAdjudicator` and is a guarded write: `expected_case_version` must match the case's current `version`, else `ERR_STALE_VERSION` (§2.7). The case must stand in `OPENED` or `APPEALED` (`ERR_INVALID_CASE_STATE`), and segregation of duties is enforced — the adjudicator's `X-User-ID` must differ from the case's `investigator_user_id` whenever that field is non-null, else `ERR_SEGREGATION_OF_DUTIES`; auto-opened statement cases, whose investigator is `null`, carry no such bar. The adjudication submits an `outcome`. A sanctioning outcome requires a `sanction_type` — `WARNING`, `SUSPENSION_12M`, `EXAM_INVALIDATION` or `CHARTER_REVOCATION` — and its absence is malformed (`ERR_INVALID_REQUEST`). Either outcome records the `adjudicator_user_id`, and a sanction stamps `sanctioned_at` with the current clock; the case's `version` increments by one on each adjudication.

Each sanction type cascades differently. A `WARNING` has no further effects. A `SUSPENSION_12M` sets the candidate's `suspended_until` to the sanction instant plus 365 days. An `EXAM_INVALIDATION` targets attempts: for an appointment-linked case, that appointment's attempt is invalidated — `VALID` to `INVALIDATED` — and the appointment's `compliance_status` advances from `POLICY_FLAGGED` to `CONFIRMED_VIOLATION`; for a case with no appointment, **all** of the candidate's attempts currently `VALID` are invalidated. Either way the candidate's progression marker and curriculum access are then recomputed, and both may shrink. A `CHARTER_REVOCATION` clears the candidate's `charter_awarded` to false, sets `conduct_revoked` true, and terminates every `ACTIVE` society membership the candidate holds — `ACTIVE` to `TERMINATED`. The candidate's derived `conduct_standing` reads `REVOKED` whenever `conduct_revoked` is set, else `SUSPENDED` while `suspended_until` lies in the future relative to the logical clock, else `GOOD_STANDING`.

The sanctioned candidate — and only the candidate whose case it is — may appeal, moving the case from `SANCTIONED` to `APPEALED` (from anything else, `ERR_INVALID_CASE_STATE`), provided the logical clock is no later than thirty days after `sanctioned_at`, else `ERR_APPEAL_WINDOW_EXPIRED`. The appeal records the `appeal_reason` and increments the case's `version`. An appealed case may be sanctioned again; the new sanction's effects apply on top of the current state, and attempts previously invalidated by the case stay `INVALIDATED` unless the case is later dismissed.

Dismissal, reachable from `OPENED` or `APPEALED`, closes the case `DISMISSED` and clears any flagged appointment's `compliance_status` to `CLEARED` — from `POLICY_FLAGGED` or from `CONFIRMED_VIOLATION` alike. Compensation fires only when a prior sanction existed on this case: every attempt that case invalidated is reinstated — `INVALIDATED` to `REINSTATED`; `suspended_until` is cleared to `null`; `conduct_revoked` returns to false, with `charter_awarded` restored to true when this case's revocation had cleared it; and progression and curriculum access are recomputed, restoring what invalidation had removed. One loss is permanent: memberships terminated by the revocation cascade are **not** restored.

### 3.8. Awarding the Charter

The charter award is a `ProgramAdmin` act against a single enrollment, gated by six conditions evaluated in a fixed order. The enrollment must be `ENROLLED` (`ERR_ENROLLMENT_NOT_ENROLLED`). The candidate must hold a passing attempt, of validity `VALID` or `REINSTATED`, for **every** configured exam level (`ERR_LEVELS_NOT_ALL_PASSED`). The sum of `committee_months` across the candidate's `APPROVED` submissions must reach at least 36 months (`ERR_EXPERIENCE_REQUIREMENT_UNMET`). The candidate's `conduct_statements` must contain an entry whose `disclosure_year` equals the logical clock's current calendar year (`ERR_MISSING_CONDUCT_STATEMENT`). No misconduct case for the candidate may stand in `OPENED` or `APPEALED` (`ERR_OPEN_MISCONDUCT_CASE`). And the enrollment's `outstanding_balance_cents` must be zero (`ERR_OUTSTANDING_BALANCE`).

Awarding flips the enrollment from `ENROLLED` to `CHARTER_AWARDED`, sets the candidate's `charter_awarded` true, stamps the enrollment's `chartered_at` with the current clock, and widens the enrollment's `curriculum_access_cycle_ids` to every `PUBLISHED` cycle in the program.

### 3.9. Societies, Membership and Continuing Education

Beyond the charter lie the local societies. A `ProgramAdmin` creates each society with a unique `society_code` (`ERR_DUPLICATE_SOCIETY_CODE`), a `name`, a `region`, a strictly positive `annual_dues_cents` fixing the exact dues amount for both joining and renewing, and an optional `ce_credits_required_per_year` that defaults to twenty — the calendar-year continuing-education credits a member needs to renew.

Joining is open to a chartered candidate acting for themselves, or to a `ProgramAdmin`: the join supplies the `candidate_id` in the body under the society in the path, and dues are exact — `dues_payment_cents` must equal the society's `annual_dues_cents` to the cent, else `ERR_INCORRECT_DUES_AMOUNT`. Joining requires the candidate's `charter_awarded` to be true (`ERR_CHARTER_REQUIRED`), and a candidate may hold only one `ACTIVE` membership per society (`ERR_DUPLICATE_MEMBERSHIP`). A new membership opens `ACTIVE` with `paid_through_year` set to the logical clock's current calendar year and an empty `ce_records` list. Memberships can be listed with `candidate_id`, `society_id` and `status` filters.

Members self-report continuing education by appending records of `activity_title`, `credit_hours` (one decimal place) and `completed_on` to their membership's `ce_records`; each append recomputes the membership's standing figures and increments its `version`. Two credit totals are maintained. `calendar_year_credits` sums the `credit_hours` of records whose `completed_on` falls within the logical clock's current calendar year, first of January through thirty-first of December inclusive. `rolling_12m_credits` sums records whose `completed_on` lies strictly after the date 365 days before the current date — the trailing 365 days, today included. The standing flag `ce_standing_met` is true exactly when `calendar_year_credits` reaches at least the society's `ce_credits_required_per_year`. The two variants answer the same records differently: at a clock reading the fifteenth of June 2027, records of five hours completed on the twentieth of December 2026, fifteen hours on the tenth of March 2027 and six hours on the fifteenth of June 2027 give `calendar_year_credits` of twenty-one and `rolling_12m_credits` of twenty-six.

Renewal advances the membership one calendar year and uses the **calendar-year** variant only: the membership must be `ACTIVE` (`ERR_INVALID_MEMBERSHIP_STATE`), its `calendar_year_credits` for the current clock year must meet the society's requirement (`ERR_CE_REQUIREMENT_NOT_MET`), and the dues payment must again match exactly (`ERR_INCORRECT_DUES_AMOUNT`). A successful renewal increments `paid_through_year` by exactly one and bumps the membership's `version`. Memberships end only one way: the charter-revocation cascade of §3.7 terminates every `ACTIVE` membership of the revoked candidate, and a later dismissal of that case does not restore them.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a candidate, an enrollment, a level, a cycle, a window, a test center, an appointment, a submission, a reference, a case, a society, a membership — return `201 Created`. Operations that modify an existing resource or drive one of its state transitions — payments, awards, cancellations, reschedules, check-ins, scoring, submits, reviews, amends, responses, adjudications, appeals, renewals, CE-record appends, and the clock setter — return `200 OK`. Readers must combine this table with the narratives of §3 to reconstruct each operation's full request and response contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProgramAdmin |
| POST | `/charter/candidates` | Register a candidate | ProgramAdmin |
| GET | `/charter/candidates/{candidateId}` | Read a candidate (standing, progression, charter flag) | All roles |
| POST | `/charter/candidates/{candidateId}/program-enrollments` | Enroll a candidate in the charter program | Candidate, ProgramAdmin |
| GET | `/charter/program-enrollments` | List enrollments | All roles |
| GET | `/charter/program-enrollments/{enrollmentId}` | Read one enrollment | All roles |
| POST | `/charter/program-enrollments/{enrollmentId}/payments` | Apply a payment to the outstanding balance | Candidate, ProgramAdmin |
| POST | `/charter/program-enrollments/{enrollmentId}/award-charter` | Award the charter after all gates | ProgramAdmin |
| POST | `/charter/exam-levels` | Create an exam level configuration | ProgramAdmin |
| POST | `/charter/exam-levels/{levelId}/curriculum-cycles` | Publish an annual curriculum cycle for a level | ProgramAdmin |
| GET | `/charter/curriculum-cycles` | List curriculum cycles | All roles |
| GET | `/charter/curriculum-cycles/{cycleId}` | Read one curriculum cycle | All roles |
| POST | `/charter/exam-windows` | Create a computer-based exam window | ProgramAdmin |
| GET | `/charter/exam-windows` | List exam windows | All roles |
| GET | `/charter/exam-windows/{windowId}` | Read one exam window | All roles |
| POST | `/charter/exam-windows/{windowId}/cancel` | Cancel an OPEN window with cascade compensation | ProgramAdmin |
| POST | `/charter/test-centers` | Create a test center | ProgramAdmin |
| POST | `/charter/appointments` | Schedule an exam appointment | Candidate, ProgramAdmin |
| GET | `/charter/appointments` | List appointments | All roles |
| GET | `/charter/appointments/{appointmentId}` | Read one appointment | All roles |
| POST | `/charter/appointments/{appointmentId}/reschedule` | Reschedule an appointment (OCC) | Candidate, ProgramAdmin |
| POST | `/charter/appointments/{appointmentId}/cancel` | Cancel a SCHEDULED appointment | Candidate, ProgramAdmin |
| POST | `/charter/appointments/{appointmentId}/check-in` | Exam-day check-in with identity and calculator policy | Proctor |
| GET | `/charter/exam-attempts` | List exam attempts | All roles |
| GET | `/charter/exam-attempts/{attemptId}` | Read one exam attempt | All roles |
| POST | `/charter/exam-attempts/{attemptId}/score` | Publish a scaled score for an attempt | ProgramAdmin |
| POST | `/charter/candidates/{candidateId}/experience-submissions` | Create a DRAFT work-experience submission | Candidate |
| GET | `/charter/experience-submissions` | List experience submissions | All roles |
| GET | `/charter/experience-submissions/{submissionId}` | Read one experience submission | All roles |
| POST | `/charter/experience-submissions/{submissionId}/amend` | Amend a RETURNED_FOR_REVISION submission (OCC) | Candidate |
| POST | `/charter/experience-submissions/{submissionId}/submit` | Submit a DRAFT submission for review | Candidate |
| POST | `/charter/experience-submissions/{submissionId}/review` | Reviewer decision on a submission | ExperienceReviewer |
| POST | `/charter/experience-submissions/{submissionId}/references` | Attach a reference contact to a submission | Candidate |
| GET | `/charter/references` | List reference contacts | All roles |
| GET | `/charter/references/{referenceId}` | Read one reference contact | All roles |
| POST | `/charter/references/{referenceId}/respond` | Reference verifies or declines | ReferenceProvider |
| POST | `/charter/candidates/{candidateId}/conduct-statements` | File the annual professional conduct statement | Candidate |
| POST | `/charter/misconduct-cases` | Open a misconduct case | ConductInvestigator, Proctor |
| GET | `/charter/misconduct-cases` | List misconduct cases | All roles |
| GET | `/charter/misconduct-cases/{caseId}` | Read one misconduct case | All roles |
| POST | `/charter/misconduct-cases/{caseId}/adjudicate` | Adjudicate a case (OCC) | ConductAdjudicator |
| POST | `/charter/misconduct-cases/{caseId}/appeal` | Appeal a sanction | Candidate |
| POST | `/charter/societies` | Create a local society | ProgramAdmin |
| POST | `/charter/societies/{societyId}/memberships` | Join a society | Candidate, ProgramAdmin |
| GET | `/charter/memberships` | List memberships | All roles |
| GET | `/charter/memberships/{membershipId}` | Read one membership | All roles |
| POST | `/charter/memberships/{membershipId}/renew` | Renew a membership for the next year | Candidate |
| POST | `/charter/memberships/{membershipId}/ce-records` | Self-report a continuing-education record | Candidate |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the normative list of identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_CANDIDATE_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_LEVEL_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SOCIETY_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SCORE_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_INVALID_PAYMENT_AMOUNT` | 400 Bad Request |
| `ERR_DUPLICATE_CANDIDATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_EXAM_LEVEL` | 409 Conflict |
| `ERR_DUPLICATE_CURRICULUM_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 Conflict |
| `ERR_DUPLICATE_CONDUCT_STATEMENT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ELIGIBILITY_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_WINDOW_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ATTEMPT_ALREADY_SCORED` | 409 Conflict |
| `ERR_INVALID_SUBMISSION_STATE` | 409 Conflict |
| `ERR_SUBMISSION_NOT_EDITABLE` | 409 Conflict |
| `ERR_REFERENCE_NOT_PENDING` | 409 Conflict |
| `ERR_INVALID_CASE_STATE` | 409 Conflict |
| `ERR_INVALID_MEMBERSHIP_STATE` | 409 Conflict |
| `ERR_WINDOW_SCHEDULING_CLOSED` | 422 Unprocessable Entity |
| `ERR_EXAM_DATE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_RESCHEDULE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CHECKIN_NOT_ON_EXAM_DATE` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_CONCLUDED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_IDENTITY_VERIFICATION_FAILED` | 422 Unprocessable Entity |
| `ERR_CALCULATOR_POLICY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CENTER_BLACKOUT_CONFLICT` | 409 Conflict |
| `ERR_NO_SEAT_CAPACITY` | 409 Conflict |
| `ERR_DOUBLE_BOOKING_LEVEL` | 409 Conflict |
| `ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT` | 409 Conflict |
| `ERR_LEVEL_ALREADY_PASSED` | 422 Unprocessable Entity |
| `ERR_PREREQUISITE_LEVEL_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_MAX_ATTEMPTS_REACHED` | 422 Unprocessable Entity |
| `ERR_RETAKE_WINDOW_TOO_SOON` | 422 Unprocessable Entity |
| `ERR_WINDOW_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_REFERENCES` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_VERIFIED_REFERENCES` | 422 Unprocessable Entity |
| `ERR_LEVELS_NOT_ALL_PASSED` | 422 Unprocessable Entity |
| `ERR_EXPERIENCE_REQUIREMENT_UNMET` | 422 Unprocessable Entity |
| `ERR_MISSING_CONDUCT_STATEMENT` | 422 Unprocessable Entity |
| `ERR_OPEN_MISCONDUCT_CASE` | 409 Conflict |
| `ERR_CHARTER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CE_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OUTSTANDING_BALANCE` | 402 Payment Required |
| `ERR_INCORRECT_DUES_AMOUNT` | 422 Unprocessable Entity |
