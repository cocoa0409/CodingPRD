# Comedy Training Ensemble API — Product Requirements Document

## 1. Introduction

A comedy training center in the tradition of The Second City runs far more than a catalog of classes. It operates a continuous pipeline: prospective students enter at an introductory level or petition for advanced standing based on prior training; they progress through a prerequisite-governed curriculum across improv, sketch, stand-up, and conservatory tracks; each term's sections must be staffed by certified instructors within weekly hour caps; end-of-level showcases must be booked into venues whose calendars respect turnover buffers; conservatory and intensive cohorts form through auditions; resident revue ensembles are cast from a mixture of training-pipeline graduates and open calls; touring companies draw principals away from running revues and require understudy coverage back home; and the entire enterprise is financed through tuition invoices, a tiered refund policy, need-based and diversity scholarships, and alumni relations.

This document specifies the API that backs that operation. It is written for the engineers who will implement the service: every rule herein — from the exact refund percentage owed to a student who drops a class three-quarters of the way through a term, to the tie-break ordering used when a waitlisted seat opens up — is a hard requirement. The system maintains its own logical clock (never the wall clock), enforces optimistic concurrency on the two write paths most exposed to conflicting updates, and propagates state changes through a densely connected graph of terms, sections, enrollments, showcases, cohorts, casts, tours, awards, and invoices.

Roles span the organization: a ProgramDirector runs curriculum, terms, sections, venues, showcases, and cohorts; a Registrar registers students and manages enrollments; a PlacementOfficer adjudicates advanced-standing petitions; a CastingDirector runs auditions, ensemble casting, and touring; a FinanceOfficer administers scholarships and invoices; and Students act on their own registrations, petitions, payments, and touring offers. The sections that follow define the global contracts every endpoint obeys, the business workflows that bind the entities together, the complete endpoint table, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role value outside the recognized set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The recognized roles, spelled exactly as the server must accept them, are:

- `ProgramDirector` — runs the training center; owns curriculum levels, terms, instructors, sections, venue slots, showcases, cohort programs, and the logical clock.
- `Registrar` — back-office staff; registers students and manages enrollments and manual invoice issuance.
- `PlacementOfficer` — reviews advanced-standing petitions (placement evaluations).
- `CastingDirector` — owns auditions, ensemble casting, and touring assignments.
- `FinanceOfficer` — owns scholarship adjudication and tuition invoicing.
- `Student` — the end user; enrolls, drops, transfers, petitions placement, pays invoices, applies for scholarships, appeals denied petitions, and accepts or declines touring offers.

Role identity is handled in two ways. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` record; ownership checks on any resource that references a student (enrollments, placement evaluations, scholarship applications, tuition invoices, touring assignments) compare the resource's student foreign-key field to `X-User-ID`, and a student may only act on resources they own. When `X-User-Role` is `ProgramDirector`, `Registrar`, `PlacementOfficer`, `CastingDirector`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

Authorization is checked after header validation and before any resource lookup: a caller with a valid but unauthorized role receives `ERR_UNAUTHORIZED_ROLE` even if the target resource does not exist.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. All list responses sort by `created_at` ascending, and the `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC format with three fractional digits, an `updated_at` timestamp of the same format that refreshes on every mutation, and an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation of that resource.

Time inside the system is governed by a logical clock, never the wall clock. The server boots with the logical clock pinned to `2026-09-01T00:00:00Z`. The only way to advance it is an admin-only test-driving capability that sets the clock to a supplied `current_utc` instant; time-dependent transitions (early-versus-late drop classification, tour departure and return, deadline enforcement) are re-evaluated lazily against the logical clock on the next relevant read or write. Wherever this document says "current time", it means the logical clock.

### 2.5. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of a parent entity, using a non-optional expected-version field.

Creating an enrollment requires `expected_section_version` in the request body, carrying the client's last observed `version` of the target section. If the section's current `version` does not match — because another writer has since confirmed, dropped, or transferred an enrollment, or patched the section, each of which legitimately bumps the section's version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from writing against a stale view of the section's occupancy.

Locking an ensemble cast requires `expected_cast_version` in the request body, carrying the client's last observed `version` of the cast. If the cast's current `version` has advanced since — because another writer has just cast an additional principal or understudy, leaving the client's view of `principal_ids` and `understudy_ids` stale — the lock is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes an expected-version field. Successful mutations of the parent entity increment its `version` by 1, which is precisely what invalidates outstanding expected-version tokens.

### 2.6. Money, Rounding, and Precision

All monetary amounts are integer cents (`base_amount_cents`, `amount_due_cents`, `paid_cents`, `refunded_cents`, `scholarship_applied_cents`, `disbursed_cents`, `amount_cents`, `tuition_cents`). Any computation that produces a fractional cent rounds half-up to the nearest integer cent, and rounding is applied only at the final step of a computation, never to intermediate values. Composite audition scores are the one non-monetary quantity with a precision rule: they are rounded half-up to two decimal places.

### 2.7. Validation Order and Nested Resource Resolution

When a request could fail for several reasons, checks run in a fixed priority order so the surfaced error is deterministic. Authentication context is validated first (missing or malformed headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then the existence of every path identifier read left to right (`ERR_NOT_FOUND`), then whether the target entity's current state permits the requested transition (`ERR_INVALID_STATE`), then temporal rules against the logical clock (`ERR_DEADLINE_PASSED`), and only then business rules such as prerequisite satisfaction, instructor availability, venue conflicts, source-policy compliance, section capacity, scholarship balances, placement eligibility, and understudy eligibility. Malformed request bodies — a missing required field or a value of the wrong type — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

For nested paths, path parameters are resolved left to right: each identifier must resolve to an existing entity before the next segment is considered, and the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404).

### 2.8. Curriculum Graph Integrity

Curriculum levels form a directed acyclic graph within each track through the self-referential `requires_level_code` link. Creating or updating a level walks the prerequisite chain from the level being written; if the walk ever revisits a node, the write is rejected with `ERR_PREREQUISITE_CYCLE` (HTTP 422). Prerequisite satisfaction for enrollment is always evaluated over the transitive closure of this chain, never just the immediate prerequisite, and only over levels whose `status` is `ACTIVE` in the matching track.

### 2.9. Venue Calendar Discipline

Venue slots are half-open intervals: a slot occupies the time from its `start_utc` (inclusive) to its `end_utc` (exclusive). Two slots on the same `venue_name` conflict when the first slot's start is strictly before the second slot's end and the second slot's start is strictly before the first slot's end. Two slots that merely touch — one ending exactly when the other begins — do not conflict on overlap grounds. However, the stage crew needs turnover time: between two RESERVED or BOOKED slots on the same venue there must be either no gap at all or a gap of at least 30 minutes; a positive gap shorter than 30 minutes violates the turnover buffer. Overlap and turnover violations on slot creation or showcase scheduling are rejected with `ERR_VENUE_SLOT_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Building the Curriculum and the Term Calendar

A ProgramDirector begins by shaping the curriculum. Each level carries a stable `code` (for example `L1` through `L5`, or `CONSERVATORY_Y1`), a human-readable `title`, a `track` of `IMPROV`, `SKETCH`, `STANDUP`, or `CONSERVATORY` (defaulting to `IMPROV` when not supplied), and a `sequence_index` giving its zero-based ordering position within its track, where lower positions unlock earlier. The `requires_level_code` field names the immediate prerequisite level by code and is null for entry levels; because this link is self-referential, every write that sets or changes it triggers the cycle check described in §2.8, and a chain that loops back on itself is refused with `ERR_PREREQUISITE_CYCLE`. Two boolean flags govern how a level interacts with the rest of the pipeline: `allows_placement_bypass` (default false) marks a level as enterable through an advanced-standing petition, and `showcase_required` (default false) marks completion as contingent on a graded showcase performance. Levels are born with `status` `ACTIVE` and may later be `RETIRED`.

With the curriculum in place, the ProgramDirector creates a Term with a `name` such as "Winter 2027", a `start_utc` that inclusively opens the term, an `end_utc` that exclusively closes it, and a `drop_deadline_utc` that splits early drops from late drops. A term is born `DRAFT`. Opening scheduling moves it `DRAFT → SCHEDULING` and unlocks section creation for that term. Opening enrollment moves it `SCHEDULING → ENROLLMENT_OPEN`, but only after a staffing audit: every non-cancelled section in the term must have an instructor assigned, and if any does not, the transition is refused with `ERR_SECTION_UNSTAFFED` (HTTP 409). When the audit passes, every section of the term still in `DRAFT` cascades to `OPEN` in the same operation.

Starting the session moves the term `ENROLLMENT_OPEN → IN_SESSION` and sweeps every section of the term: a section in `OPEN` with at least one enrolled student locks into `LOCKED`; a section in `OPEN` with zero enrolled students is `CANCELLED` outright, and that cancellation cascades to its enrollments and invoices exactly as a manual cancellation would (see §3.3); a section already `LOCKED` whose `enrolled_count` has reached `capacity` advances `LOCKED → RUNNING`. Closing the term moves it `IN_SESSION → CLOSED` (the term's terminal state): every `RUNNING` section becomes `COMPLETED`, every `CONFIRMED` enrollment on those sections becomes `COMPLETED`, and for each completed section whose level has `showcase_required` set, the system auto-creates a ShowcaseEvent in `PLANNED` status whose `performer_enrollment_ids` are exactly the enrollments that just completed. A term in any state other than the one a transition starts from rejects that transition with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Staffing Sections with Instructors

Instructors are registered with a `display_name`, a `home_track` naming the track they are primarily certified to teach, a `certified_tracks` array enumerating every track they may teach, and a `max_weekly_hours` cap on scheduled teaching time that defaults to 20 when not supplied. An instructor's `status` begins `ACTIVE` and may move to `ON_LEAVE` or `INACTIVE`.

A CourseSection binds a `term_id`, a `level_id`, an optional `instructor_id` (which may be null while the section is in `DRAFT`), a strictly positive `capacity`, a `tuition_cents` base price, and the `weekly_hours` the section runs. Sections track two computed occupancy counters: `enrolled_count`, the number of enrollments in `REGISTERED` or `CONFIRMED`, and `waitlist_count`, the number in `WAITLISTED`. Both counters move only as enrollment events dictate.

Whenever a section is created with an instructor, or later patched to assign or change `instructor_id`, `capacity`, or `weekly_hours`, two checks guard the write: the instructor must be certified for the track of the section's level, and the instructor's total weekly load across their sections plus this section's `weekly_hours` must not exceed the instructor's `max_weekly_hours`. A violation of either is rejected with `ERR_INSTRUCTOR_UNAVAILABLE` (HTTP 422). A successful patch increments the section's `version` by 1 — which is what invalidates any outstanding `expected_section_version` held by a would-be enrollee.

A ProgramDirector may cancel a section while it is `DRAFT` or `OPEN`; cancelling from any other state is `ERR_INVALID_STATE`. Cancellation consequences depend on timing and are spelled out with the enrollment lifecycle below.

### 3.3. Enrollment, Placement, and the Waitlist Waterfall

The Registrar registers each student with a `full_name` and a unique `email`. Students are born with `standing` `GOOD` (which may later degrade to `FINANCIAL_HOLD` or `SUSPENDED`), with `is_alumni` false, `is_industry_showcase_eligible` false, and two empty computed code sets: `completed_level_codes`, the codes of levels the student has been credited for, and `placement_credit_codes`, the codes covered by granted placement petitions.

**Placement petitions.** An experienced student (or a PlacementOfficer acting on their behalf) petitions to enter a level above the entry point by submitting a PlacementEvaluation naming the `student_id`, the `target_level_id` the student wishes to enter, the `track` the evaluation covers, the `prior_institution` where the student trained, and optionally a `portfolio_score` from 0 to 100 (default 0). The target level must have `allows_placement_bypass` true; a petition aimed at a level that forbids bypass is rejected with `ERR_PLACEMENT_NOT_ALLOWED` (HTTP 422), both at submission time and again at grant time. The server derives the evaluation's `variant` from the `prior_institution`: when the institution is one of iO, UCB, Groundlings, or Second City (another campus), the variant is `AUDITION_BYPASS`; otherwise — including an empty institution string — it is `PORTFOLIO_REVIEW`.

A petition is born `SUBMITTED`. A PlacementOfficer begins review (`SUBMITTED → UNDER_REVIEW`), then either grants or denies. Granting an `AUDITION_BYPASS` petition requires the institution to be one of the four recognized names — otherwise `ERR_UNRECOGNIZED_INSTITUTION` (HTTP 422) — and ignores the portfolio score entirely, granting on institutional reputation alone. Granting a `PORTFOLIO_REVIEW` petition requires a `portfolio_score` of at least 70 — below that threshold the grant fails with `ERR_PORTFOLIO_SCORE_TOO_LOW` (HTTP 422). In both variants the target level must allow bypass, as noted. On a grant, the server computes `granted_level_codes` as the target level plus every prerequisite level below it in the same track, walking the `requires_level_code` chain transitively, and unions those codes into the student's `placement_credit_codes`. Denial moves the petition `UNDER_REVIEW → DENIED`. The student who owns a denied petition may appeal it (`DENIED → APPEALED`), and a PlacementOfficer may then begin review again (`APPEALED → UNDER_REVIEW`) for a second adjudication.

**Enrolling.** A student (or the Registrar) enrolls by naming the `student_id`, the `section_id`, an optional `priority_tier` of `RETURNING` or `NEW` (default `NEW`), and — as §2.5 requires — the `expected_section_version` last observed for the section. The prerequisite check runs first among the business rules: the union of the student's `completed_level_codes` and `placement_credit_codes` must contain the code of every level in the transitive prerequisite closure of the section's level within the same track; a gap anywhere in the chain rejects the enrollment with `ERR_PREREQUISITE_NOT_MET` (HTTP 422).

If the section's `enrolled_count` has reached `capacity`, the new enrollment is born directly into `WAITLISTED` and the section's `waitlist_count` rises by 1. Otherwise it is born `REGISTERED`. Either way, creating the enrollment issues a TuitionInvoice against it and increments the section's `version` by 1.

**Confirming.** A `REGISTERED` enrollment is confirmed by the owning student or the Registrar, but only while the section is `OPEN` or `LOCKED` and still has a vacant seat; confirming into a full section fails with `ERR_SECTION_FULL` (HTTP 409). Confirmation moves the enrollment `REGISTERED → CONFIRMED`, raises the section's `enrolled_count` by 1, and increments the section's `version`. When confirmation fills the last seat no promotion happens — the waitlist only moves when a vacancy opens.

**Dropping.** Before the term's `drop_deadline_utc`, a drop is early: a `CONFIRMED` enrollment moves to `DROPPED_EARLY`, the section's `enrolled_count` falls by 1, the attached invoice is refunded in full (100% of what was paid), and the vacancy triggers the seat-allocation waterfall below. A `REGISTERED` enrollment dropped before the deadline also becomes `DROPPED_EARLY`, but because no payment was ever due its invoice is voided rather than refunded. After the deadline, only a `CONFIRMED` enrollment may drop; it becomes `DROPPED_LATE`, the section's `enrolled_count` falls by 1, the invoice is refunded on the tiered schedule described in §3.4, and the waterfall runs. Dropping an enrollment in any other state is `ERR_INVALID_STATE`. All drop paths increment the section's `version`.

**Transferring.** A `CONFIRMED` enrollment may transfer to a different section of the same term and the same level, provided the target section has a vacant seat or is accepting waitlist entries — otherwise `ERR_SECTION_FULL`. The transfer must also be initiated before the source term's `drop_deadline_utc`; once the deadline has passed, the attempt is refused with `ERR_DEADLINE_PASSED` (HTTP 409), just as a drop attempt by an enrollment in a non-droppable state past the relevant window is. The source enrollment becomes `TRANSFERRED_OUT`, the source section's `enrolled_count` falls by 1, its invoice becomes `TRANSFERRED`, and a brand-new enrollment is created on the target section with `origin_enrollment_id` pointing back at the source and status `REGISTERED`. A fresh invoice is issued against the new enrollment with the prior payments carried over. The vacancy on the source section triggers the waterfall.

**The waterfall.** Whenever a vacancy opens on a section — through a drop, a transfer out, or a cancellation-path rule that frees seats — the system promotes the head of the waitlist. The candidate pool is the section's `WAITLISTED` enrollments. They are ranked first by `priority_tier` with `RETURNING` ahead of `NEW`, then by enrollment `created_at` ascending; ties fall to earlier `created_at`, and the record `id` is never used as a tie-break. The head enrollment transitions `WAITLISTED → REGISTERED`, the section's `waitlist_count` falls by 1, and `enrolled_count` does not change until the promoted student confirms. An empty waitlist makes the waterfall a no-op.

**Crediting.** A `COMPLETED` enrollment becomes `CREDITED` — a terminal state — in one of two ways. When the section's level requires a showcase, crediting waits for the linked ShowcaseEvent to be staged with a `PASS` grade for that enrollment (at which point the enrollment's `graded_showcase_id` records the showcase). When the level does not require a showcase, the enrollment is credited directly at term close. Either way the level's `code` is added to the student's `completed_level_codes`, and the moment any enrollment of the student reaches `CREDITED`, the student's `is_alumni` flips to true.

### 3.4. Tuition, Refunds, and Scholarships

Every enrollment, however it is created, carries a TuitionInvoice. Invoices are also issuable manually by a FinanceOfficer or Registrar — for example to collect an outstanding balance — by naming the `student_id`, the `enrollment_id` the invoice pays for, and the `base_amount_cents` before any adjustment.

The invoice's financial position is recomputed on every event in a pinned order. First the `scholarship_applied_cents` is determined from the student's awards: scholarships in `AWARDED` or `DISBURSED` status are applied oldest-first by award `created_at`, each application limited so that the cumulative `disbursed_cents` of an award never exceeds its `amount_cents` — a disbursement that would overrun the remaining award balance is rejected with `ERR_SCHOLARSHIP_EXHAUSTED` (HTTP 422). Then `paid_cents` — the cumulative payments received — is subtracted. Then refund adjustments are applied. The resulting `amount_due_cents` is the base amount minus the applied scholarship minus payments, plus any refund adjustment owed back; rounding half-up to integer cents happens only at this final step.

Payment. A payment of `amount_cents` against an invoice must be positive and must not push `paid_cents` past `amount_due_cents`: an overpayment is rejected with `ERR_INVOICE_OVERPAYMENT` (HTTP 422). A payment that leaves a balance outstanding moves an `ISSUED` invoice to `PARTIALLY_PAID` and adds to `paid_cents`. A payment that exactly settles the balance — the running `paid_cents` plus this payment equal to `amount_due_cents` — moves an `ISSUED` or `PARTIALLY_PAID` invoice to `PAID`, a terminal state. Payments against an invoice already in a terminal state (`PAID`, `REFUNDED`, `TRANSFERRED`, or `VOID`) are refused with `ERR_INVOICE_ALREADY_SETTLED` (HTTP 409).

Refunds follow the term calendar. When the refund cascades from an early drop or a section cancellation, the invoice goes to `REFUNDED` and `refunded_cents` covers everything — the full `paid_cents` plus the `scholarship_applied_cents` portion is unwound. When the refund cascades from a late drop, the cash portion is tiered by how far the term has elapsed. Let the elapsed fraction be the time from the term's `start_utc` to the current logical time, divided by the term's full length from `start_utc` to `end_utc`. If the elapsed fraction is under one quarter of the term, the student is refunded three quarters of `paid_cents`; from one quarter up to one half, one half of `paid_cents`; from one half up to three quarters, one quarter of `paid_cents`; at three quarters or beyond, nothing. The cash refund is `paid_cents` multiplied by that percentage, rounded half-up to integer cents. The `scholarship_applied_cents` portion is never returned to the student as cash in any refund — it is clawed back to the originating award's balance. A transfer does not refund: the source invoice becomes `TRANSFERRED` and the new enrollment's invoice carries the payments forward. A drop of a never-confirmed enrollment voids the invoice outright (`VOID`), since nothing was due.

Section cancellation — manual or via the term start-session sweep — cascades identically to an early drop for every `REGISTERED` or `WAITLISTED` enrollment on the section: each becomes `DROPPED_EARLY` and its invoice becomes `REFUNDED` in full.

Scholarships themselves have a lifecycle. A student or FinanceOfficer applies by naming the `student_id`, a `kind` of `NEED_BASED`, `DIVERSITY`, or `MERIT`, and the total `amount_cents`; the award is born `APPLIED` with `disbursed_cents` zero. A FinanceOfficer then awards it (`APPLIED → AWARDED`) or denies it (`APPLIED → DENIED`, terminal). An award disburses automatically — `AWARDED → DISBURSED` — when an invoice is issued against the student while that student holds the award and has an invoice outstanding in `ISSUED` or `PARTIALLY_PAID`; the award's `disbursed_cents` rises by the amount applied and the invoice's `scholarship_applied_cents` and `amount_due_cents` recompute as above. An award can be revoked (`AWARDED → REVOKED`, terminal) only while nothing has been disbursed; attempting to revoke an award whose `disbursed_cents` is non-zero fails with `ERR_SCHOLARSHIP_NOT_REVOCABLE` (HTTP 409).

### 3.5. Showcases and the Venue Calendar

A VenueSlot records a `venue_name` (a stage such as "Mainstage" or "e.t.c."), a `start_utc` and `end_utc` forming the half-open interval of §2.9, and an informational audience `capacity`. Slots are born `AVAILABLE`; creating one runs the overlap and turnover checks and rejects conflicts with `ERR_VENUE_SLOT_CONFLICT`.

A ShowcaseEvent belongs to a `level_id` and a `term_id`, names the `venue_slot_id` it will occupy, lists the graduating cohort as `performer_enrollment_ids`, and flags with `is_industry` (default false) whether it is an industry-facing alumni showcase. It is born `PLANNED`.

Scheduling a showcase (`PLANNED → SCHEDULED`) requires its venue slot to be `AVAILABLE` under the half-open conflict and turnover rules — violations are `ERR_VENUE_SLOT_CONFLICT` — and requires the venue's `capacity` to seat at least the number of performers, otherwise `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422). Scheduling moves the slot to `RESERVED`.

Staging a showcase (`SCHEDULED → STAGED`) is where grades land. The request carries `grade_by_enrollment`, a map from each performing enrollment to `PASS` or `FAIL`, and it must cover every entry of `performer_enrollment_ids` — a missing grade rejects the staging with `ERR_GRADES_INCOMPLETE` (HTTP 422). On staging, the venue slot moves `RESERVED → BOOKED`; each enrollment graded `PASS` cascades `COMPLETED → CREDITED` with the consequences of §3.3 (level code into `completed_level_codes`, `is_alumni` flipping, `graded_showcase_id` recorded); each enrollment graded `FAIL` remains `COMPLETED` and earns no credit.

Archiving (`STAGED → ARCHIVED`) releases the venue slot to `RELEASED`. Cancelling from `PLANNED` leaves the slot untouched, while cancelling from `SCHEDULED` releases the reserved slot back to `RELEASED`. Both `ARCHIVED` and `CANCELLED` are terminal.

### 3.6. Conservatory and Intensive Cohorts

A CohortProgram is created by a ProgramDirector with a `kind` of `CONSERVATORY` or `INTENSIVE`, a `track`, the `term_id` it runs in, a `cohort_size` ceiling on admitted students, a `requires_audition` flag (default true), and a `min_track_level_code` naming the minimum level in the track a student must have completed for admission. It is born `FORMING` with `admitted_count` zero.

Beginning auditions moves the cohort `FORMING → AUDITIONING`. Admission happens one student at a time: the ProgramDirector admits by naming an `audition_id`, and the admission validates that the student's `completed_level_codes` cover the cohort's `min_track_level_code` — a student short of the floor is refused with `ERR_MIN_TRACK_LEVEL_NOT_MET` (HTTP 422) — and that the cohort has room, an admission beyond `cohort_size` failing with `ERR_COHORT_OVER_CAPACITY` (HTTP 422). A successful admission moves the audition to `SELECTED` and raises `admitted_count` by 1.

Finalizing the cohort (`AUDITIONING → CASTED`) requires at least one admitted student and no more than `cohort_size`. The cohort then waits: when its term's session starts, the cohort cascades `CASTED → ACTIVE` automatically. After the term has closed, the ProgramDirector graduates the cohort (`ACTIVE → GRADUATED`), and each admitted student's `is_industry_showcase_eligible` is recomputed — it becomes true exactly when the student both is an alumnus and has now graduated from a cohort program. Either flag alone is not enough.

A cohort that never gets off the ground can be dissolved from `FORMING` or `AUDITIONING`, landing in `DISSOLVED`. Dissolution from `FORMING` rejects every still-`SCHEDULED` audition targeting the cohort; dissolution from `AUDITIONING` rejects every non-terminal audition targeting it.

### 3.7. Auditions and the Composite Score

A CastingDirector schedules an Audition naming the `student_id`, a `target_kind` of `COHORT`, `ENSEMBLE`, or `TOURING`, the `cohort_program_id` when the target is a cohort (null otherwise), the `ensemble_cast_id` when the target is an ensemble or a touring company (null otherwise), and `rubric_scores`, a map from dimension to a 0–10 score across dimensions such as scene work, characters, musicality, and game. The audition is born `SCHEDULED`.

Evaluation (`SCHEDULED → EVALUATED`) computes the `composite_score`: each dimension's rubric score is multiplied by that dimension's weight — scene work counts for 40%, characters for 25%, musicality for 20%, and game for 15% — the products are summed, dimensions missing from the rubric contribute zero, and the total is rounded half-up to two decimal places.

From `EVALUATED`, the CastingDirector may waitlist the audition (`EVALUATED → WAITLISTED`) or reject it outright (`EVALUATED → REJECTED`, terminal). A waitlisted audition may still be selected later — when a principal or understudy slot frees, promotion moves it `WAITLISTED → SELECTED` with exactly the same side effects as a direct selection — or may be rejected from the waitlist (`WAITLISTED → REJECTED`). Selection itself is never invoked directly on the audition: it is a system cascade fired when the CastingDirector casts an ensemble or when the ProgramDirector admits a cohort member, and the selector policy (§3.8) is what picks which audition is selected. Selection into a cohort raises the cohort's `admitted_count` by 1; selection into an ensemble appends the student to the cast's `principal_ids` or `understudy_ids`.

### 3.8. Casting a Resident Revue

An EnsembleCast is created by a CastingDirector with a `revue_title`, the `venue_slot_id` of opening night, a `cast_size` of principal positions, a number of `understudy_slots`, and a `source_policy` of `PIPELINE_ONLY`, `OPEN_CALL`, or `MIXED` (default `MIXED`). It is born `OPEN_ROLES` with empty `principal_ids` and `understudy_ids`. Opening casting moves it `OPEN_ROLES → CASTING`.

Casting runs the selector. The candidate pool is the auditions whose `target_kind` is `ENSEMBLE`, whose `ensemble_cast_id` is this cast, and whose `outcome` is `EVALUATED` or `WAITLISTED`. The source policy filters the pool: under `PIPELINE_ONLY`, only students who hold a `CREDITED` enrollment in a conservatory cohort are eligible, and an audition from any other student is refused with `ERR_SOURCE_POLICY_VIOLATION` (HTTP 422); under `OPEN_CALL`, no pipeline filter applies; under `MIXED`, no one is filtered out, but pipeline students receive a half-point bonus on their composite score. The pool is ranked by composite score descending, ties broken by the audition's `created_at` ascending, with the record `id` never used as a tie-break. The top `cast_size` candidates become principals and the next `understudy_slots` become understudies, populating `principal_ids` and `understudy_ids`; each chosen audition transitions to `SELECTED`. Casting increments the cast's `version` by 1. If the filtered pool is empty, the operation fails with `ERR_NO_ELIGIBLE_AUDITIONS` (HTTP 422).

Locking the cast (`CASTING → REHEARSING`) is the OCC-guarded write of §2.5: the request must carry `expected_cast_version` matching the cast's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). Locking also requires the roster to be complete — exactly `cast_size` principals and exactly `understudy_slots` understudies — and the opening-night venue slot to be `BOOKED`; an incomplete roster fails with `ERR_CAST_INCOMPLETE` (HTTP 409). A successful lock increments the cast's `version` by 1.

Opening the revue moves the cast `REHEARSING → RUNNING` (also bumping `version`), and closing it moves `RUNNING → CLOSED` — but only once every non-terminal touring assignment drawn from the cast has reached `RETURNED` or `REPLACED`.

### 3.9. Touring Companies and Understudy Coverage

A TouringAssignment draws a principal away from a running revue. The CastingDirector proposes one by naming the `ensemble_cast_id` the tour draws from, the `principal_student_id` going on the road, the `understudy_student_id` covering the home venue, and the `tour_start_utc` and `tour_end_utc` of the engagement. The window must be sane — the start strictly before the end and not overlapping the cast's other tours — or the proposal fails with `ERR_TOUR_WINDOW_INVALID` (HTTP 422); a proposal whose tour window has already passed under the logical clock is instead refused with `ERR_DEADLINE_PASSED`. The understudy must satisfy the coverage predicate: either the understudy student's `is_alumni` is true, or the student holds a `CREDITED` enrollment in the cast's track; an understudy meeting neither condition is rejected with `ERR_UNDERSTUDY_INELIGIBLE` (HTTP 422), both when the assignment is proposed and again when it is accepted. The assignment is born `PROPOSED` with `travel_committed` false.

The principal — and only the principal; the acting student must be the `principal_student_id` — accepts (`PROPOSED → ACCEPTED`) or declines (`PROPOSED → DECLINED`, terminal). Acceptance sets `travel_committed` true, recording that travel is booked through the end-of-tour return. From `ACCEPTED`, two time-based transitions are evaluated lazily against the logical clock and can be polled through the sync capability: once the current time reaches `tour_start_utc` the assignment moves `ACCEPTED → ON_TOUR`, and once it reaches `tour_end_utc` it moves `ON_TOUR → RETURNED` (terminal) and the understudy's coverage obligation is released.

If a principal must be pulled mid-engagement, the CastingDirector replaces an `ACCEPTED` assignment, supplying a `new_principal_student_id` and a `new_understudy_student_id` in the same call. The old assignment becomes `REPLACED` (terminal) with `travel_committed` cleared, and the replacement assignment is created in `PROPOSED` with the new principal, entering the lifecycle from the top.

## 4. Endpoint Definitions

All endpoints live under the API root. Endpoints that create a new resource respond with 201 and the created resource; endpoints that modify, transition, or read a resource respond with 200. Request and response field details are governed by §2 and §3 rather than restated here; the table lists only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to `current_utc` (server boots pinned to 2026-09-01T00:00:00Z) | ProgramDirector |
| POST | `/curriculum-levels` | Create a curriculum level with self-referential `requires_level_code` prerequisite | ProgramDirector |
| GET | `/curriculum-levels` | List curriculum levels (filters: `track`, `requires_level_code`) | ProgramDirector, PlacementOfficer, Registrar, CastingDirector, Student, FinanceOfficer |
| GET | `/curriculum-levels/{levelId}` | Get a curriculum level | ProgramDirector, PlacementOfficer, Registrar, CastingDirector, Student, FinanceOfficer |
| POST | `/terms` | Create a term | ProgramDirector |
| GET | `/terms` | List terms | ProgramDirector, Registrar, CastingDirector, Student, FinanceOfficer, PlacementOfficer |
| GET | `/terms/{termId}` | Get a term | ProgramDirector, Registrar, CastingDirector, Student, FinanceOfficer, PlacementOfficer |
| POST | `/terms/{termId}/open-scheduling` | Term `DRAFT → SCHEDULING` | ProgramDirector |
| POST | `/terms/{termId}/open-enrollment` | Term `SCHEDULING → ENROLLMENT_OPEN`; cascades DRAFT sections to OPEN | ProgramDirector |
| POST | `/terms/{termId}/start-session` | Term `ENROLLMENT_OPEN → IN_SESSION`; cascades sections to LOCKED/RUNNING/CANCELLED | ProgramDirector |
| POST | `/terms/{termId}/close` | Term `IN_SESSION → CLOSED`; cascades sections, enrollments; auto-creates showcases | ProgramDirector |
| POST | `/instructors` | Create an instructor | ProgramDirector |
| GET | `/instructors` | List instructors | ProgramDirector, Registrar |
| GET | `/instructors/{instructorId}` | Get an instructor | ProgramDirector, Registrar |
| POST | `/sections` | Create a course section | ProgramDirector |
| GET | `/sections` | List sections (filters: `term_id`, `level_id`, `instructor_id`) | ProgramDirector, Registrar, Student, PlacementOfficer |
| GET | `/sections/{sectionId}` | Get a section | ProgramDirector, Registrar, Student, PlacementOfficer |
| PATCH | `/sections/{sectionId}` | Update a section (`instructor_id`, `capacity`, `weekly_hours`); bumps section version | ProgramDirector |
| POST | `/sections/{sectionId}/cancel` | Cancel a DRAFT or OPEN section; cascades enrollments and invoices | ProgramDirector |
| POST | `/students` | Register a student | Registrar |
| GET | `/students` | List students (filter: `is_alumni`) | ProgramDirector, Registrar, CastingDirector, PlacementOfficer, FinanceOfficer |
| GET | `/students/{studentId}` | Get a student | ProgramDirector, Registrar, CastingDirector, PlacementOfficer, FinanceOfficer, Student |
| POST | `/placement-evaluations` | Petition to bypass prerequisite levels; computes the evaluation variant | Student, PlacementOfficer |
| GET | `/placement-evaluations` | List evaluations (filters: `student_id`, `target_level_id`, `decision`) | PlacementOfficer, ProgramDirector |
| GET | `/placement-evaluations/{id}` | Get an evaluation | PlacementOfficer, ProgramDirector, Student |
| POST | `/placement-evaluations/{id}/begin-review` | `SUBMITTED → UNDER_REVIEW` (also `APPEALED → UNDER_REVIEW`) | PlacementOfficer |
| POST | `/placement-evaluations/{id}/grant` | `UNDER_REVIEW → GRANTED`; updates the student's placement credits | PlacementOfficer |
| POST | `/placement-evaluations/{id}/deny` | `UNDER_REVIEW → DENIED` | PlacementOfficer |
| POST | `/placement-evaluations/{id}/appeal` | `DENIED → APPEALED` (must own the evaluation) | Student |
| POST | `/enrollments` | Enroll a student into a section (OCC via `expected_section_version`); issues the tuition invoice | Registrar, Student |
| GET | `/enrollments` | List enrollments (filters: `student_id`, `section_id`, `status`, `origin_enrollment_id`, `graded_showcase_id`) | ProgramDirector, Registrar, Student |
| GET | `/enrollments/{enrollmentId}` | Get an enrollment | ProgramDirector, Registrar, Student |
| POST | `/enrollments/{enrollmentId}/confirm` | `REGISTERED → CONFIRMED` | Student, Registrar |
| POST | `/enrollments/{enrollmentId}/drop` | Drop an enrollment (early vs late via the term's drop deadline) | Student, Registrar |
| POST | `/enrollments/{enrollmentId}/transfer` | Transfer to another section (`target_section_id`) of the same term and level | Student, Registrar |
| POST | `/venue-slots` | Create a venue slot (conflict and turnover checks apply) | ProgramDirector |
| GET | `/venue-slots` | List venue slots (filters: `venue_name`, `status`) | ProgramDirector, CastingDirector, Registrar |
| GET | `/venue-slots/{slotId}` | Get a venue slot | ProgramDirector, CastingDirector, Registrar |
| POST | `/showcases` | Create a showcase (or industry showcase) | ProgramDirector |
| GET | `/showcases` | List showcases (filters: `level_id`, `term_id`, `is_industry`, `venue_slot_id`, `performer_enrollment_ids`) | ProgramDirector, CastingDirector, Registrar, Student |
| GET | `/showcases/{showcaseId}` | Get a showcase | ProgramDirector, CastingDirector, Registrar, Student |
| POST | `/showcases/{showcaseId}/schedule` | `PLANNED → SCHEDULED`; reserves the venue slot | ProgramDirector |
| POST | `/showcases/{showcaseId}/stage` | `SCHEDULED → STAGED`; records `grade_by_enrollment` and credits passing enrollments | ProgramDirector |
| POST | `/showcases/{showcaseId}/archive` | `STAGED → ARCHIVED`; releases the venue slot | ProgramDirector |
| POST | `/showcases/{showcaseId}/cancel` | `PLANNED`/`SCHEDULED → CANCELLED`; releases a reserved slot | ProgramDirector |
| POST | `/cohort-programs` | Create a conservatory or intensive cohort | ProgramDirector |
| GET | `/cohort-programs` | List cohorts (filters: `term_id`, `kind`, `status`) | ProgramDirector, CastingDirector, Registrar, Student |
| GET | `/cohort-programs/{cohortId}` | Get a cohort | ProgramDirector, CastingDirector, Registrar, Student |
| POST | `/cohort-programs/{cohortId}/begin-auditions` | `FORMING → AUDITIONING` | ProgramDirector |
| POST | `/cohort-programs/{cohortId}/admit` | Admit an auditioned student (`audition_id`) into the cohort | ProgramDirector |
| POST | `/cohort-programs/{cohortId}/finalize-cohort` | `AUDITIONING → CASTED` | ProgramDirector |
| POST | `/cohort-programs/{cohortId}/graduate` | `ACTIVE → GRADUATED`; recomputes industry-showcase eligibility | ProgramDirector |
| POST | `/cohort-programs/{cohortId}/dissolve` | `FORMING`/`AUDITIONING → DISSOLVED`; rejects outstanding auditions | ProgramDirector |
| POST | `/auditions` | Schedule an audition | CastingDirector |
| GET | `/auditions` | List auditions (filters: `student_id`, `target_kind`, `cohort_program_id`, `ensemble_cast_id`, `outcome`) | CastingDirector, ProgramDirector |
| GET | `/auditions/{auditionId}` | Get an audition | CastingDirector, ProgramDirector |
| POST | `/auditions/{auditionId}/evaluate` | `SCHEDULED → EVALUATED`; computes `composite_score` | CastingDirector |
| POST | `/auditions/{auditionId}/waitlist` | `EVALUATED → WAITLISTED` | CastingDirector |
| POST | `/auditions/{auditionId}/reject` | `EVALUATED`/`WAITLISTED → REJECTED` | CastingDirector |
| POST | `/ensemble-casts` | Create an ensemble cast (revue) | CastingDirector |
| GET | `/ensemble-casts` | List casts (filters: `status`, `venue_slot_id`, `principal_ids`, `understudy_ids`) | CastingDirector, ProgramDirector |
| GET | `/ensemble-casts/{castId}` | Get an ensemble cast | CastingDirector, ProgramDirector |
| POST | `/ensemble-casts/{castId}/open-casting` | `OPEN_ROLES → CASTING` | CastingDirector |
| POST | `/ensemble-casts/{castId}/cast` | Run the casting selector; fill principals and understudies; bumps cast version | CastingDirector |
| POST | `/ensemble-casts/{castId}/lock-cast` | `CASTING → REHEARSING` (OCC via `expected_cast_version`) | CastingDirector |
| POST | `/ensemble-casts/{castId}/open-revue` | `REHEARSING → RUNNING`; bumps cast version | CastingDirector |
| POST | `/ensemble-casts/{castId}/close-revue` | `RUNNING → CLOSED` once all tours are RETURNED or REPLACED | CastingDirector |
| POST | `/touring-assignments` | Propose a touring assignment | CastingDirector |
| GET | `/touring-assignments` | List touring assignments (filters: `ensemble_cast_id`, `principal_student_id`, `understudy_student_id`, `status`) | CastingDirector, ProgramDirector, Student |
| GET | `/touring-assignments/{assignmentId}` | Get a touring assignment | CastingDirector, ProgramDirector, Student |
| POST | `/touring-assignments/{assignmentId}/accept` | `PROPOSED → ACCEPTED` (must be the principal); sets `travel_committed` | Student |
| POST | `/touring-assignments/{assignmentId}/decline` | `PROPOSED → DECLINED` (must be the principal) | Student |
| POST | `/touring-assignments/{assignmentId}/sync` | Evaluate time-based transitions against the logical clock | CastingDirector, ProgramDirector |
| POST | `/touring-assignments/{assignmentId}/replace` | `ACCEPTED → REPLACED`; creates the replacement assignment in PROPOSED | CastingDirector |
| POST | `/scholarships` | Apply for a scholarship | Student, FinanceOfficer |
| GET | `/scholarships` | List scholarships (filters: `student_id`, `kind`, `status`) | FinanceOfficer, ProgramDirector |
| GET | `/scholarships/{scholarshipId}` | Get a scholarship | FinanceOfficer, ProgramDirector |
| POST | `/scholarships/{scholarshipId}/award` | `APPLIED → AWARDED` | FinanceOfficer |
| POST | `/scholarships/{scholarshipId}/deny` | `APPLIED → DENIED` | FinanceOfficer |
| POST | `/scholarships/{scholarshipId}/revoke` | `AWARDED → REVOKED` (only while nothing disbursed) | FinanceOfficer |
| POST | `/tuition-invoices` | Manually issue an invoice; auto-applies awarded scholarships | FinanceOfficer, Registrar |
| GET | `/tuition-invoices` | List invoices (filters: `student_id`, `enrollment_id`, `status`) | FinanceOfficer, Registrar, Student |
| GET | `/tuition-invoices/{invoiceId}` | Get an invoice | FinanceOfficer, Registrar, Student |
| POST | `/tuition-invoices/{invoiceId}/pay` | Record a payment (`amount_cents`) against an invoice | Student, FinanceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is defined where the guarded workflow appears in §2 and §3; this table enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_SECTION_UNSTAFFED` | 409 |
| `ERR_SECTION_FULL` | 409 |
| `ERR_VENUE_SLOT_CONFLICT` | 409 |
| `ERR_CAST_INCOMPLETE` | 409 |
| `ERR_SCHOLARSHIP_NOT_REVOCABLE` | 409 |
| `ERR_INVOICE_ALREADY_SETTLED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PREREQUISITE_NOT_MET` | 422 |
| `ERR_PREREQUISITE_CYCLE` | 422 |
| `ERR_PLACEMENT_NOT_ALLOWED` | 422 |
| `ERR_PORTFOLIO_SCORE_TOO_LOW` | 422 |
| `ERR_UNRECOGNIZED_INSTITUTION` | 422 |
| `ERR_INSTRUCTOR_UNAVAILABLE` | 422 |
| `ERR_VENUE_CAPACITY_EXCEEDED` | 422 |
| `ERR_SOURCE_POLICY_VIOLATION` | 422 |
| `ERR_NO_ELIGIBLE_AUDITIONS` | 422 |
| `ERR_UNDERSTUDY_INELIGIBLE` | 422 |
| `ERR_TOUR_WINDOW_INVALID` | 422 |
| `ERR_SCHOLARSHIP_EXHAUSTED` | 422 |
| `ERR_INVOICE_OVERPAYMENT` | 422 |
| `ERR_GRADES_INCOMPLETE` | 422 |
| `ERR_COHORT_OVER_CAPACITY` | 422 |
| `ERR_MIN_TRACK_LEVEL_NOT_MET` | 422 |
