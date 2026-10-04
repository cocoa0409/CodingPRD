# Montessori Society Accreditation API — Product Requirements Document

## 1. Introduction

The Society operates a voluntary quality-assurance program for schools that practice the Montessori method, and this document specifies the REST API — mounted under `/society` — that runs it. School membership escalates through four levels, from `APPLICANT` through `AFFILIATE` and `MEMBER` to `ACCREDITED`, each step gated by an application, escalating evidence requirements, classroom audits, a self-study, and an on-site verification visit. Alongside the school track, the Society accredits teacher education programs, supervises their adult learners through practicum placements, and issues age-level teaching credentials whose renewal depends on continuing-education credit earned at professional-development events.

Because the method's name is not exclusively controlled, the Society cannot stop an unaffiliated school from calling itself a Montessori school — but it can, and does, police how member schools use the name, and it publishes a public directory so parents can verify a school's claimed standing. Compliance is policed continuously rather than once: classroom audits are scored against a pinned edition of the standards, improvement plans carry hard response deadlines, and a school's public visibility is recomputed from its level, standing, brand compliance and dues currency every time any of those change. All time-dependent behavior — credential lapsing, plan lateness, event completion — is driven by a single logical clock that the API exposes for test-driving.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user acts. A request missing either header, or carrying a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) on every endpoint except the two public directory reads, which accept anonymous callers. A request whose role is authenticated but not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

Eight roles are declared. `Anonymous` is the unauthenticated public caller — a parent verifying a school — and reaches only the directory endpoints; it carries no `X-User-ID` of consequence. `SocietyAdmin` is the Society's operations staff and is an opaque operator identifier not tied to any persisted entity: the server never compares it to an entity's `id`. `AccreditationReviewer`, the Society's accreditation decision-maker, is likewise opaque, as is `Registrar`, the credential issuing authority, and `Consultant`, the verification-visit and classroom-audit practitioner. The consultant's identifier is not an entity `id`, but the server does record it — as `consultant_id` on a `VerificationVisit` and as `auditor_consultant_id` on a `ClassroomAudit` — and ownership checks on report filing and visit-linked audits compare `X-User-ID` against those recorded values.

Three roles are entity-backed. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is the `id` of the acting `School`; ownership checks compare the target school's `id` — or the `school_id` of the target child resource such as an application, self-study or improvement plan — to `X-User-ID`. When `X-User-Role` is `ProgramDirector`, `X-User-ID` is the `id` of the acting `TeacherEducationProgram`; ownership checks compare the target program's `id`, or the enrolling learner's `program_id`, to `X-User-ID`. When `X-User-Role` is `AdultLearner`, `X-User-ID` is the `id` of the acting `AdultLearner`; ownership checks compare the placement's or credential's `learner_id` to `X-User-ID`. An entity-backed ownership mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system share one set of system-managed fields. The `id` is a server-minted UUID carried as a plain string with no type prefix. `created_at` records when the resource was created as an ISO 8601 UTC timestamp with three fractional digits; `updated_at` is the same kind of timestamp for the most recent modification. `version` is a system-managed integer that increments by one on every mutation of the resource and anchors optimistic concurrency control.

Two resources are deliberately leaner. A `ClassroomAudit` and a `CECreditEntry` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because an audit is immutable once filed and a credit entry's only mutation is the void transition.

The `version` of a `School` is deliberately disciplined, because two optimistic-concurrency gates read it. `School.version` increments only on direct school mutations: recording a dues payment, a brand update, a standing transition, a membership-level advance, the creation of a school application, the creation of a self-study, and the acceptance of a self-study. Audit creation, classroom creation, student transfers, improvement-plan auto-creation, and the recomputation of computed fields (`compliant_classroom_count`, `directory_visible`, `annual_dues_cents`, `total_enrollment`) never bump `School.version`; those computed fields are derived on read.

### 2.5. The Logical Clock and Time-Driven Transitions

The platform runs on a logical clock rather than wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-09-01T00:00:00Z, and the server must never fall back to wall-clock time. A `SocietyAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`.

Advancing the clock runs a time sweep over four entity families. A `Credential` in `ACTIVE` flips to `LAPSED` when the current logical date becomes strictly greater than the date of its `expires_at`, and a `LAPSED` credential flips to `EXPIRED` when the current logical date becomes strictly greater than the date of `expires_at` extended by the `ACTIVE` catalog's `renewal_grace_months`. An `ImprovementPlan` in `OPEN` flips to `OVERDUE` when the current logical date becomes strictly greater than its `due_date`, firing the school-standing cascade described in §3.7. A `PDEvent` in `SCHEDULED` flips to `COMPLETED` when the current logical datetime becomes strictly greater than its `end_at`. These sweeps are the only writers of the corresponding transitions.

### 2.6. Standards Editions and Catalog Pinning

The Society publishes classroom and program standards as discrete `StandardsCatalog` editions, each identified by a human `version_label` such as "Standards 2026" and carrying an `effective_from` date. An edition is created in `DRAFT`, moves to `ACTIVE` when a `SocietyAdmin` activates it, and ends in `RETIRED`. Activation is allowed only from `DRAFT`; if another edition is already `ACTIVE`, the incoming edition's `effective_from` must be strictly later than that edition's, otherwise activation is rejected with `ERR_CATALOG_EFFECTIVE_ORDER` (HTTP 422). Activating a newer edition automatically transitions the previously `ACTIVE` edition to `RETIRED` — there is at most one `ACTIVE` catalog at any moment.

Retirement never rewrites history. A `SelfStudy` pins the currently `ACTIVE` catalog at creation, storing `pinned_catalog_id` plus a denormalized `pinned_catalog_label` copied from the edition's `version_label`, and its review proceeds against that edition even if the edition is later retired. When a self-study is accepted, the school adopts that pinned edition as its own `pinned_catalog_id`, which then drives classroom-audit scoring until replaced. Each `ClassroomAudit` records, in its `catalog_id`, the edition it was scored against — the school's pinned edition when one is set, otherwise the catalog that is `ACTIVE` at audit time. A `PracticumPlacement` pins its `target_hours` from the `ACTIVE` catalog at creation, a `Credential`'s validity window is computed from the `ACTIVE` catalog at issuance or renewal, and an improvement plan's `due_date` is computed from the `ACTIVE` catalog at the triggering event. Creating a self-study, a practicum placement, or a classroom audit requires an `ACTIVE` catalog to exist; when none does, the request is rejected with `ERR_NO_ACTIVE_CATALOG` (HTTP 422).

### 2.7. The Validation Pipeline: Ten Tiers, First Failure Wins

Every mutating request passes through a fixed ten-tier validation pipeline, and the tiers are evaluated in the order below — the first failing tier determines the response, so a failure at an early tier masks every later check. Readers should treat this ordering as contractual, not descriptive.

Tier 1 is authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the declared roles, failing with `ERR_UNAUTHENTICATED` (HTTP 401); anonymous callers are accepted only on the two public directory reads. Tier 2 is role authorization: the role must appear in the endpoint's authorized set, failing with `ERR_FORBIDDEN` (HTTP 403). Tier 3 is existence: path identifiers are validated left to right, then body-supplied foreign keys that are present and well-formed — `school_id`, `learner_id`, `classroom_id`, `credential_id`, `self_study_id`, `supervisor_credential_id`, `host_school_id`, `to_classroom_id`, `visit_id` — each failing with its entity-specific 404 (`ERR_SCHOOL_NOT_FOUND`, `ERR_CLASSROOM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_LEARNER_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_SELF_STUDY_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_CE_ENTRY_NOT_FOUND`); a foreign-key field that is simply absent defers to the shape tier. Tier 4 is field shape: required fields present, enum members valid, numeric ranges honored, `materials_groups` non-empty with `present_count` no greater than `required_count` in every group, logged `hours` greater than zero — all failing with `ERR_VALIDATION` (HTTP 400). Later tiers assume well-typed inputs.

Tier 5 is entity-backed ownership, as defined per role in §2.1, failing with `ERR_FORBIDDEN` (HTTP 403). Tier 6 is state: the optimistic-concurrency check of §2.8 is evaluated first, before the state-transition check within this tier, so a stale replay against a since-invalidated state still answers 412 with `ERR_STALE_VERSION`; then the target entity must be in a state from which the requested transition exists — submission only from `DRAFT` or `RETURNED`, verification only from `HOURS_COMPLETE`, report filing only from `SCHEDULED`, attendance only on `COMPLETED` events, renewal only from `ACTIVE` or `LAPSED` (a `REVOKED` or `EXPIRED` credential fails with `ERR_CREDENTIAL_NOT_RENEWABLE`, HTTP 409, which outranks any renewal-window error), a wrong-typed application for the school's level, or enrollment into a `PROBATION` or `SUSPENDED` program — otherwise failing with `ERR_INVALID_STATE` (HTTP 409).

Tier 7 is temporal windows: placement windows, log-hours work dates, consultant scheduling buffers, visit windows, the renewal window, and accreditation tenure, each with its own error code introduced where the workflow is described. Tier 8 is cross-entity reference consistency — age-level agreement, study-to-school and visit-to-school belonging, host-school eligibility — reported as `ERR_AGE_LEVEL_MISMATCH` (HTTP 422) except where a named variant applies (`ERR_SELF_STUDY_REQUIRED`, `ERR_VERIFICATION_VISIT_REQUIRED`, `ERR_HOST_SCHOOL_INELIGIBLE`, all HTTP 422). Tier 9 groups uniqueness, capacity, posture and segregation rules: display-name uniqueness, one in-flight application or self-study per school, duplicate credentials and attendance, supervisor capacity, brand differentiation, classroom clearance, open improvement plans, segregation of duties, and the practicum standard for program accreditation. Tier 10 is fiscal, and it is deliberately last: an application cannot be submitted, nor its approval finalized, while the school's dues are delinquent (`ERR_DUES_DELINQUENT`, HTTP 402), and a renewal's `fee_cents` must match the expected fee exactly (`ERR_FEE_MISMATCH`, HTTP 422).

### 2.8. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control against a parent entity's `version`, and each requires its version field as a non-optional input. Creating a school application (`POST /society/school-applications`) and creating a self-study (`POST /society/self-studies`) both require `expected_school_version`, carrying the client's last observed `version` of the school; if the school's current `version` has advanced since that read — because another writer created an application or self-study, or mutated the school — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Responding to an improvement plan (`POST /society/improvement-plans/{id}/respond`) requires `expected_improvement_plan_version` matching the plan's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field.

### 2.9. Measurements, Money and Rounding

Student-to-adult ratios are stored rounded half-up to 2 decimal places, and the compliance comparison uses that rounded value. Materials-completeness scoring pins a specific rounding order: each group's ratio of `present_count` to `required_count` is first rounded half-up to 2 decimal places individually, the arithmetic mean of those per-group rounded scores is then taken exactly — never re-rounded before comparison — and only the stored display value `materials_score` is rounded half-up to 4 decimal places. Continuing-education hours are kept at 1 decimal place with exact comparisons. All money is integer cents with no rounding. Enrollment counts, adult counts, observed minutes, practicum hours and calendar offsets are whole numbers.

### 2.10. Resolving Nested and Cross-Referenced Resources

When a request path chains identifiers, the server validates existence strictly left to right and rejects with the 404 of the first identifier that does not resolve, before any business rule runs. Body-supplied references are checked immediately after path identifiers, and only then do shape, ownership, state, temporal, referential, constraint and fiscal tiers run, per §2.7. A resource read never fabricates related objects: reverse reachability (for example, listing a school's audits or a credential's credit entries) is served by filtered list endpoints rather than embedded payloads.

## 3. Business Logic & Workflows

### 3.1. Publishing a Standards Edition

Every rule the Society enforces traces back to a `StandardsCatalog` edition, so publishing one is the first act of the platform. A `SocietyAdmin` creates an edition in `DRAFT` by supplying its `version_label` and `effective_from` date together with the full measurement book: `min_uninterrupted_work_minutes_by_level` mapping each age level to the minimum uninterrupted work-period minutes a compliant classroom must offer; `max_students_per_adult_by_level` mapping each level to an inclusive cap on students per supervising adult; `materials_pass_threshold`, the minimum materials-completeness score for a compliant audit (for example 0.9); `min_multi_age_span_years_by_level`, the inclusive minimum declared multi-age span per level; and `practicum_min_hours_by_level`, the minimum practicum hours per level before a placement can be verified. The same payload carries the credentialing book — `ce_hours_required` for renewal, `credential_validity_months` for the validity window, `renewal_window_months` for how early renewal opens and `renewal_grace_months` for how long a lapsed credential may still renew — and the governance book: `min_membership_months_before_accreditation`, the `consultant_travel_buffer_days` that space a consultant's visits, and `plan_response_days`, the deadline imposed on improvement plans.

Activation, covered contractually in §2.6, is the only way an edition leaves `DRAFT`, and it retires its predecessor. Editions otherwise accumulate as an immutable historical record: a catalog read returns any edition by id to every authenticated role.

### 3.2. School Onboarding, Brand and Dues

A school enters the platform when a `SocietyAdmin` onboards it with its legal `name`, a public `display_name`, a `contact_email`, and two brand fields: `uses_method_name`, which is true when the display name incorporates the uncontrolled method name (the constant `METHOD_NAME`, whose value is "Montessori"), and an optional differentiating `descriptor` such as "Inspired". New schools start at membership level `APPLICANT` with standing `GOOD_STANDING`.

Because the Society does not exclusively control the method's name, brand compliance is a standing rule rather than a one-time check. A school's computed `brand_compliant` flag is true when the school does not use the method name, or when the school is `ACCREDITED`, or when a non-`ACCREDITED` school using the method name carries a `descriptor` that actually appears inside its `display_name`. The rule bites at three moments — school onboarding, any later brand update by the school's own `SchoolAdmin` (payload `display_name`, `uses_method_name`, optional `descriptor`), and affiliation submission — and a violation is rejected with `ERR_BRAND_DIFFERENTIATION_REQUIRED` (HTTP 422). Independently, `display_name` must be unique case-insensitively across all schools at any level; a collision is rejected with `ERR_DISPLAY_NAME_TAKEN` (HTTP 409). A successful brand update recomputes `brand_compliant` and `directory_visible` and increments the school's `version`.

The Society funds itself through annual dues. A `SocietyAdmin` records a dues payment with a `period_start`, a `period_end` and an `amount_cents`; the payment sets the school's `dues_paid_through` to `period_end` (null until the first payment), which in turn drives the computed `dues_current` flag — true exactly when `dues_paid_through` is set and is on or after the current logical date. Recording a payment recomputes `dues_current` and `directory_visible` and increments the school's `version`.

What a school owes is quoted on every school read as `annual_dues_cents`, computed from the school's level, its `total_enrollment` — the sum of `enrolled_student_count` over all of its classrooms, regardless of audit state — and its classroom count. The schedule starts from a level base: 40000 cents for `AFFILIATE` (an `APPLICANT` school quotes the `AFFILIATE` schedule), 90000 cents for `MEMBER`, and 150000 cents for `ACCREDITED`. A marginal per-student fee is added — 1500 cents for each of the first 100 students, 1200 cents for each student from 101 through 300, and 900 cents for each student beyond 300, applied marginally rather than as an average — plus a surcharge of 8000 cents per classroom. The raw total is then floored at 60000 cents before being capped at 1500000 cents; the floor applies before the cap. Worked anchors pin the schedule: an `AFFILIATE` school with zero students and one classroom raws to 48000 cents and pays the 60000-cent floor; a `MEMBER` with 250 students and 4 classrooms pays 452000 cents; an `AFFILIATE` with 100 students and one classroom pays 198000 cents, while a 101st student — billed alone at the 1200-cent tier — brings the quote to 199200 cents; an `ACCREDITED` school with 1500 students and 20 classrooms raws to 1780000 cents and pays the 1500000-cent cap.

### 3.3. Classrooms, Enrollment and the Standards Audit

A `SchoolAdmin` builds out the school's physical program one classroom at a time, supplying the owning `school_id`, a `name` such as "Willow Room", the `age_level` served — one of `INFANT_TODDLER`, `EARLY_CHILDHOOD`, `ELEMENTARY_I`, `ELEMENTARY_II`, `SECONDARY` — the `declared_age_span_years` the room claims, the current `enrolled_student_count` (zero or more), and the `assistant_count` of assistant adults regularly in the room (also zero or more). A room may open unstaffed: the optional `lead_credential_id` is null in that case, and when supplied it must reference an `ACTIVE` credential whose age level equals the classroom's — a level mismatch is rejected with `ERR_AGE_LEVEL_MISMATCH` (HTTP 422). Each classroom also carries a system-managed `compliance_override`, normally `NONE`, which the credential-revocation cascade of §3.5 can flip to `NONCOMPLIANT_LEAD`; the override clears when a valid `ACTIVE` lead of matching age level is (re)assigned to the room. The classroom's `latest_audit_verdict` is computed as the verdict of its most recent audit and stays null until one is filed.

Enrollment moves between rooms only through a deliberate transfer. A `SchoolAdmin` transfers students by naming a `to_classroom_id` and a `student_count`; the two rooms must belong to the same school, otherwise `ERR_TRANSFER_CROSS_SCHOOL` (HTTP 422), and must serve the same `age_level`, otherwise `ERR_AGE_LEVEL_MISMATCH` (HTTP 422). The count must be at least one and no greater than the source room's `enrolled_student_count` — exceeding it fails with `ERR_TRANSFER_EXCEEDS_ENROLLMENT` (HTTP 422) — and moving a room's entire enrollment is allowed, leaving the source at zero. The transfer subtracts the count from the source room and adds it to the destination, increments both classrooms' `version`, and answers with `from_classroom_id`, `to_classroom_id`, `from_enrolled_student_count`, `to_enrolled_student_count` and the unchanged `school_total_enrollment`: a school's `total_enrollment` after a transfer equals its value before, by invariant. After creation, `enrolled_student_count` changes only through this operation.

Standards enforcement happens through the `ClassroomAudit`, filed by a `Consultant`. The filing payload names the `classroom_id`, optionally a `visit_id`, and the observations: `students_present` (zero or more), `adults_present` (at least one), `observed_uninterrupted_minutes` (zero or more) for the longest observed work period, and `materials_groups`, a non-empty array of groups each carrying a `domain`, a `required_count` and a `present_count` that may not exceed its `required_count`. Violations of these shapes fail with `ERR_VALIDATION` (HTTP 400). The audit is scored against the school's pinned catalog when one exists, otherwise against the currently `ACTIVE` edition — recorded on the audit as `catalog_id` at creation, with `ERR_NO_ACTIVE_CATALOG` (HTTP 422) when neither exists — and the server stamps `observed_at` with the logical clock and records the filer as `auditor_consultant_id`. When a `visit_id` is supplied, the visit must belong to the classroom's school (a referential failure, HTTP 422), must still be `SCHEDULED` (otherwise `ERR_INVALID_STATE`, HTTP 409), and the filing consultant's `X-User-ID` must equal the visit's `consultant_id` (otherwise `ERR_FORBIDDEN`, HTTP 403).

Four checks are computed at filing, each against the pinned catalog's entry for the classroom's `age_level`. The ratio check divides `students_present` by `adults_present`, rounds half-up to 2 decimal places into `ratio_students_per_adult`, and sets `ratio_pass` when that rounded value is at most the catalog's `max_students_per_adult_by_level` cap — equality passes. The work-period check sets `work_period_pass` when `observed_uninterrupted_minutes` is at least the catalog's `min_uninterrupted_work_minutes_by_level` minimum — sitting exactly on the minimum passes. The multi-age check sets `multi_age_pass` when the classroom's `declared_age_span_years` is at least the catalog's `min_multi_age_span_years_by_level` entry. The materials check is the subtle one: for each group, the ratio of `present_count` to `required_count` is first rounded half-up to 2 decimal places on its own; the materials score is then the exact arithmetic mean of those per-group rounded values; and `materials_pass` holds when that unrounded mean is at least the catalog's `materials_pass_threshold`, while the stored `materials_score` is the mean rounded half-up to 4 decimal places. Summing first and rounding once is forbidden: with groups of 8/9, 8/9, 8/9 and 1/1, the pinned per-group-first order yields a mean of 0.9175 and passes a 0.90 threshold, whereas the sum of 25 over 28 yields 0.8929 and would fail — the pinned order governs.

The audit's `verdict` is `COMPLIANT` exactly when all four pass flags hold, and `NONCOMPLIANT` otherwise; `failed_checks` names the failed components drawn from `RATIO`, `WORK_PERIOD`, `MATERIALS`, `MULTI_AGE`, kept in that fixed order and empty for a compliant audit. Filing an audit refreshes the classroom's `latest_audit_verdict` and recomputes the school's `compliant_classroom_count` — the number of its classrooms whose most recent audit is `COMPLIANT` and whose `compliance_override` is still `NONE` — without touching the school's `version`. Audits are immutable once filed and can be read back individually or listed with filters on `classroom_id`, `catalog_id`, `visit_id` and `verdict`.

### 3.4. Teacher Education Programs, Learners and Practicum Placements

The credentialing pipeline begins with the program. A `SocietyAdmin` registers a `TeacherEducationProgram` with a `name`, a non-empty `age_levels_offered` subset of the age-level enum, and two per-level maps: `course_contact_hours_by_level`, the academic contact hours delivered per level, and `practicum_hours_by_level`, the practicum hours the program schedules per level. A new program holds `PROVISIONAL` status.

Accreditation decisions on a program belong to an `AccreditationReviewer`, who posts a `to_status` with an optional `reason`. Five transitions exist: `PROVISIONAL` to `ACCREDITED`, granted only when the program's `practicum_hours_by_level` meets or exceeds the `ACTIVE` catalog's `practicum_min_hours_by_level` for every offered level — shortfalls are rejected with `ERR_PRACTICUM_STANDARD_UNMET` (HTTP 422); `ACCREDITED` to `PROBATION`; `PROBATION` back to `ACCREDITED`; `ACCREDITED` to `SUSPENDED`; and `PROBATION` to `SUSPENDED`. Any other pairing fails with `ERR_INVALID_STATE` (HTTP 409).

A `ProgramDirector` enrolls an `AdultLearner` into their own program — the payload's `program_id` must equal the director's `X-User-ID` — supplying the learner's `full_name` and `age_level`. Enrollment is open only while the program is `PROVISIONAL` or `ACCREDITED`; attempting it against a `PROBATION` or `SUSPENDED` program fails with `ERR_INVALID_STATE` (HTTP 409), and an `age_level` the program does not offer fails with `ERR_AGE_LEVEL_MISMATCH` (HTTP 422). The learner starts in `ENROLLED` status.

The practicum is where pedagogy meets the classroom. A `ProgramDirector` creates a `PracticumPlacement` — already `ACTIVE` at creation — with a `learner_id` from their own program, a `host_school_id`, an optional `supervisor_credential_id`, and the window `start_date` and `end_date`. The host school's membership level must be `AFFILIATE`, `MEMBER` or `ACCREDITED`; an `APPLICANT` host fails with `ERR_HOST_SCHOOL_INELIGIBLE` (HTTP 422). The window must make sense against the logical clock: `end_date` strictly after `start_date` and strictly after the current logical date, else `ERR_PLACEMENT_WINDOW_INVALID` (HTTP 422). One learner holds at most one date-overlapping placement in `ACTIVE` or `HOURS_COMPLETE`: windows are treated as half-open — the start date inclusive, the end date exclusive — so one placement's `end_date` may equal another's `start_date` without conflict, while a true intersection fails with `ERR_PLACEMENT_WINDOW_OVERLAP` (HTTP 409). At creation the placement copies the learner's `age_level` (immutable thereafter) and pins its `target_hours` from the `ACTIVE` catalog's `practicum_min_hours_by_level` for that level; with no `ACTIVE` catalog the create fails with `ERR_NO_ACTIVE_CATALOG` (HTTP 422). The new placement's `hours_logged` starts at zero, and its creation advances the learner from `ENROLLED` to `IN_PRACTICUM`.

Supervision is deliberately optional to break the bootstrap cycle — a program's first cohort has no credentialed supervisors yet — and a null `supervisor_credential_id` simply leaves the placement unsupervised. When a supervisor is supplied, three conditions attach at creation: the credential must be `ACTIVE`, failing with `ERR_SUPERVISOR_CREDENTIAL_INACTIVE` (HTTP 409) when lapsed, expired or revoked; its age level must equal the learner's, failing with `ERR_AGE_LEVEL_MISMATCH` (HTTP 422); and the credential must be supervising fewer than 3 other `ACTIVE` placements — exactly 3 supervised placements is allowed, and a fourth is rejected with `ERR_SUPERVISOR_CAPACITY_EXCEEDED` (HTTP 422).

Hours accumulate through the learner's own hand. An `AdultLearner` logs practicum hours against their own placement — `X-User-ID` must equal the placement's `learner_id` — supplying `hours`, which must be greater than zero (`ERR_VALIDATION`, HTTP 400), and a `work_date` that must fall inside the placement window from `start_date` through `end_date`, failing outside it with `ERR_PLACEMENT_WINDOW_INVALID` (HTTP 422). Logging is accepted only while the placement is `ACTIVE`; a placement that has already completed, been verified or been cancelled rejects further logging with `ERR_INVALID_STATE` (HTTP 409). Each accepted entry adds its `hours` to `hours_logged` — the accumulator only ever grows — and increments the placement's `version`. When `hours_logged` reaches the pinned `target_hours` the placement auto-transitions from `ACTIVE` to `HOURS_COMPLETE`; landing exactly on the target completes it.

Completion is confirmed, not assumed. A `ProgramDirector` verifies a placement that sits in `HOURS_COMPLETE`, but only for a learner of their own program — the director's `X-User-ID` must equal the learner's `program_id`, else `ERR_FORBIDDEN` (HTTP 403), and any other placement state fails with `ERR_INVALID_STATE` (HTTP 409). Verification moves the placement to `VERIFIED` and advances the learner from `IN_PRACTICUM` to `PRACTICUM_COMPLETE`. A director may instead cancel an `ACTIVE` placement, moving it to `CANCELLED`, which releases the supervisor's capacity and the learner's window for future placements.

The learner's own status machine shadows this pipeline: `ENROLLED` at creation, `IN_PRACTICUM` when a placement is created for them, `PRACTICUM_COMPLETE` when that placement is verified, and `CREDENTIALED` when a credential is issued — the terminal state. Note that placement verification, not mere hours, is what unlocks credentialing, and §3.5 picks up the story from there.

### 3.5. Credentials, Continuing Education and the Renewal Cycle

A credential is the pipeline's terminus. A `Registrar` issues one by supplying a `learner_id` and an `age_level`; the learner must sit in `PRACTICUM_COMPLETE` — issuance ahead of verification fails with `ERR_PRACTICUM_NOT_VERIFIED` (HTTP 422) — the learner's program must be `ACCREDITED`, failing with `ERR_PROGRAM_NOT_ACCREDITED` (HTTP 409), the requested `age_level` must equal the learner's own, failing with `ERR_AGE_LEVEL_MISMATCH` (HTTP 422), and no `ACTIVE` or `LAPSED` credential may already exist for the same learner and level, failing with `ERR_DUPLICATE_CREDENTIAL` (HTTP 409). Issuance lands the credential in `ACTIVE` with `issued_at` stamped from the logical clock, `cycle_start` set to the issuance date, `expires_at` computed as `cycle_start` extended by the `ACTIVE` catalog's `credential_validity_months`, and `renewed_count` at zero; the learner advances to `CREDENTIALED`.

Continuing education runs as a small ledger over professional-development events. A `SocietyAdmin` creates a `PDEvent` with a `title`, a `provider_name`, a `start_at` and `end_at` — the end strictly after the start — and the `ce_hours` granted at full attendance, which must be greater than zero. The event stays `SCHEDULED` until the logical clock passes `end_at`, at which point the sweep marks it `COMPLETED`. Attendance is recorded by a `SocietyAdmin` only on a `COMPLETED` event — a `SCHEDULED` one fails with `ERR_INVALID_STATE` (HTTP 409) — by posting a `credential_id` and an optional `hours_earned`. Each posting creates a `CECreditEntry` whose `pd_event_id` is copied from the event addressed, whose `hours` default to the event's `ce_hours` and otherwise must exceed zero without exceeding the event's `ce_hours`, and whose `earned_at` is set to the event's `end_at` — credit is earned when the event completes, not when the posting lands. At most one non-`VOID` entry may exist per credential and event; a second posting fails with `ERR_DUPLICATE_ATTENDANCE` (HTTP 409). A `SocietyAdmin` may later void an `ACTIVE` entry, moving it to `VOID`; voiding is the ledger's only compensating action, and both posting and voiding recompute the credential's cached totals.

Two totals ride on every credential read. `ce_hours_cycle_credited` sums `hours` over the credential's `ACTIVE` entries whose `earned_at` date falls on or after `cycle_start` — the CYCLE variant. `ce_hours_rolling_credited` sums `hours` over `ACTIVE` entries whose `earned_at` date falls inside the trailing window of the `ACTIVE` catalog's `credential_validity_months` ending today — the ROLLING variant, a provisional estimate that ignores cycle boundaries, so prior-cycle hours still inside the window can inflate ROLLING above CYCLE. Voided rows count in neither. The two variants genuinely diverge: an identical ledger can satisfy the requirement under ROLLING yet fail under CYCLE, and CYCLE alone is authoritative when a renewal is adjudicated.

Renewal restarts the clock on a credential, and it is guarded by four checks evaluated in order. The request may come from the credential holder as an `AdultLearner` — whose `X-User-ID` must equal the credential's `learner_id` — or from a `Registrar`, and it carries a single input, `fee_cents`. First, state: only an `ACTIVE` or `LAPSED` credential can renew; a `REVOKED` or `EXPIRED` one fails with `ERR_CREDENTIAL_NOT_RENEWABLE` (HTTP 409), which outranks any window error. Second, the renewal window: the current logical date must fall inside the inclusive interval that opens `renewal_window_months` before the date of `expires_at` and closes `renewal_grace_months` after it — both boundary dates themselves qualify — otherwise `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422). Third, continuing education: the credential's CYCLE hours must meet or exceed the `ACTIVE` catalog's `ce_hours_required` — exact equality qualifies — failing with `ERR_INSUFFICIENT_CE_HOURS` (HTTP 422). Fourth, the fee: the expected amount is 8500 cents, plus a 5000-cent late fee when the credential is `LAPSED`, and the supplied `fee_cents` must equal that expectation exactly, failing with `ERR_FEE_MISMATCH` (HTTP 422). A successful renewal from `ACTIVE` — or a late renewal from `LAPSED` inside the grace window — returns the credential to `ACTIVE`, sets `cycle_start` to the current logical date, recomputes `expires_at` as today plus the `ACTIVE` catalog's `credential_validity_months`, increments `renewed_count`, refreshes `issued_at` to now, and rebases `ce_hours_cycle_credited` so prior-cycle entries fall out of the CYCLE window. Left alone, a credential instead drifts down the clock sweep of §2.5: `ACTIVE` to `LAPSED` past its expiry date, and `LAPSED` to terminal `EXPIRED` past the grace window.

Revocation is the disciplinary exit, taken by an `AccreditationReviewer` with an optional `reason`, from either `ACTIVE` or `LAPSED`; any other state fails with `ERR_INVALID_STATE` (HTTP 409). Revoking a credential fires a cascade with three tiers. Every classroom whose `lead_credential_id` names the revoked credential is mutated to `compliance_override` `NONCOMPLIANT_LEAD`. Each school owning an affected classroom then recomputes its `compliant_classroom_count`, since an overridden room no longer counts as compliant. Finally, when an affected school's membership level is `ACCREDITED` and at least one of its classrooms flipped, the system auto-creates an `ImprovementPlan` for that school with `visit_id` null, a `required_actions` list reading "Restore a credentialed lead teacher of matching age level", and a `due_date` set to the current logical date plus the `ACTIVE` catalog's `plan_response_days` — an obligation on the school even though no visit occurred, processed through the same plan lifecycle as §3.6.

### 3.6. The Self-Study, the Verification Visit and the Improvement Plan

The road to accreditation runs through introspection first. A `SchoolAdmin` opens a `SelfStudy` for their own school with a `school_id`, a free-text `narrative`, and the concurrency token `expected_school_version` per §2.8 — a stale token fails with `ERR_STALE_VERSION` (HTTP 412). Creation pins the currently `ACTIVE` catalog onto the study as `pinned_catalog_id`, denormalizing its label into `pinned_catalog_label`, so review proceeds against that edition even after it is retired; with no `ACTIVE` catalog the create fails with `ERR_NO_ACTIVE_CATALOG` (HTTP 422). A school may hold only one in-flight self-study at a time — one in `DRAFT`, `SUBMITTED` or `RETURNED_FOR_REVISION` — and a second attempt fails with `ERR_IN_FLIGHT_SELF_STUDY_EXISTS` (HTTP 409). Creating the study is a direct school mutation and increments the school's `version`.

A study in `DRAFT` — or one returned for revision — is submitted by its `SchoolAdmin`; the `narrative` must be non-empty (`ERR_VALIDATION`, HTTP 400), and submission records `submitted_at` and lands the study in `SUBMITTED`. Review belongs to an `AccreditationReviewer` posting an `outcome` with optional `notes`, and only a `SUBMITTED` study is actionable (`ERR_INVALID_STATE`, HTTP 409 otherwise). An `ACCEPTED` outcome is terminal and momentous: the school adopts the study's pinned edition as its own `pinned_catalog_id`, which drives classroom-audit scoring from then on, and the school's `version` increments. A `RETURNED_FOR_REVISION` outcome reopens the cycle, and resubmission re-evaluates against the current state.

With an accepted study in hand, an `AccreditationReviewer` schedules a `VerificationVisit` by naming the `school_id`, the `self_study_id`, the `consultant_id` to send, and the visit window `window_start` through `window_end`. The referenced study must belong to that school and be `ACCEPTED`, failing the referential tier (HTTP 422) otherwise. The window itself must not be malformed — `window_end` before `window_start`, or `window_start` before the current logical date, fails with `ERR_VISIT_WINDOW_INVALID` (HTTP 422). The Society also protects its consultants' calendars: across that consultant's non-`CANCELLED` visits, each existing window expanded by the catalog's `consultant_travel_buffer_days` on both ends must not intersect the requested window — expanded windows that merely touch still count as a conflict — and a clash fails with `ERR_CONSULTANT_SCHEDULE_CONFLICT` (HTTP 409). A scheduled visit sits in `SCHEDULED`; the reviewer may cancel it to `CANCELLED`, a terminal state that frees the consultant's calendar.

After the visit, the assigned `Consultant` files the report. Only the visit's own consultant may file — `X-User-ID` must equal the visit's `consultant_id`, else `ERR_FORBIDDEN` (HTTP 403) — the visit must still be `SCHEDULED` (else `ERR_INVALID_STATE`, HTTP 409), and the current logical date must have reached `window_start` (an early filing fails with `ERR_VISIT_WINDOW_INVALID`, HTTP 422). The report carries `findings`, an array of finding strings, and a `verdict` of `COMPLIANT`, `IMPROVEMENT_REQUIRED` or `NONCOMPLIANT`; filing records both fields plus `report_filed_at` and moves the visit to terminal `REPORT_FILED`.

The verdict decides what happens next. A `COMPLIANT` report ends the matter. An `IMPROVEMENT_REQUIRED` or `NONCOMPLIANT` report auto-creates an `ImprovementPlan` for the visit's school: `school_id` and `visit_id` copied from the visit, `required_actions` copied from the report's `findings`, and a `due_date` set to the filing date plus the `ACTIVE` catalog's `plan_response_days` — the plan becomes `OVERDUE` when the logical date moves strictly past that date. A `NONCOMPLIANT` verdict against a school in `GOOD_STANDING` additionally drops the school to `PROBATION` through the standing cascade of §3.7. Plans created by the credential-revocation cascade of §3.5 arrive with `visit_id` null but are otherwise identical obligations.

The school answers a plan through its `SchoolAdmin`, whose response carries `response_notes` and the concurrency token `expected_improvement_plan_version` — a stale token fails with `ERR_STALE_VERSION` (HTTP 412) per §2.8. Responding is allowed from `OPEN` and, as a late response, from `OVERDUE`; it records the notes, stamps `submitted_at`, increments the plan's `version`, and moves the plan to `SUBMITTED`. An `AccreditationReviewer` then adjudicates a `SUBMITTED` plan with an `outcome` and optional `notes`. A `VERIFIED` outcome is terminal and stamps `verified_at`; when the school then has no remaining plan in `OPEN`, `OVERDUE` or `SUBMITTED` and its standing is `PROBATION`, the school's standing auto-restores to `GOOD_STANDING` with the cascade of §3.7. A `CHANGES_REQUESTED` outcome sends the plan back to `OPEN` with a fresh `due_date` recomputed as the current logical date plus the `ACTIVE` catalog's `plan_response_days`, restarting the response clock. Plans are readable individually and listable with filters on `school_id`, `visit_id` and `status`.

### 3.7. Advancing a School: Applications, Standing and the Cascades

A school climbs levels through the `SchoolApplication`. A `SchoolAdmin` creates one for their own school with a `school_id`, a `type`, and the concurrency token `expected_school_version` per §2.8. The `type` must name the school's next level — `AFFILIATION` for an `APPLICANT` school, `MEMBERSHIP` for an `AFFILIATE`, `ACCREDITATION` for a `MEMBER` — and a wrong-typed application fails with `ERR_INVALID_STATE` (HTTP 409). Only one application per school may be in flight across `DRAFT`, `UNDER_REVIEW`, `RETURNED` and `SUSPENDED`; a second fails with `ERR_IN_FLIGHT_APPLICATION_EXISTS` (HTTP 409). The application starts in `DRAFT`, and creating it increments the school's `version`.

Submitting a `DRAFT` application — or resubmitting a `RETURNED` one, which closes the revision loop and re-evaluates everything against current state — runs the escalating requirement chain in the pipeline's order: state first, then the tenure temporal check, then referential requirements, then the constraint checks, and fiscal last. Every type requires the school's dues to be current at submission, failing with `ERR_DUES_DELINQUENT` (HTTP 402). An `AFFILIATION` submission additionally requires at least one classroom (`ERR_CLASSROOM_REQUIRED`, HTTP 422) and a brand-compliant school (`ERR_BRAND_DIFFERENTIATION_REQUIRED`, HTTP 422). A `MEMBERSHIP` submission requires every classroom to clear under the LATEST_PASS variant below (`ERR_CLASSROOM_NONCOMPLIANT`, HTTP 422). An `ACCREDITATION` submission stacks the most: the current logical date must be at least `member_since` plus the `ACTIVE` catalog's `min_membership_months_before_accreditation` — equality passes — else `ERR_ACCREDITATION_TENURE_TOO_SHORT` (HTTP 422); the school must hold an `ACCEPTED` self-study, else `ERR_SELF_STUDY_REQUIRED` (HTTP 422), which the submission pins onto the application as `supporting_self_study_id`; a `REPORT_FILED` visit on that study must exist, else `ERR_VERIFICATION_VISIT_REQUIRED` (HTTP 422); every classroom must clear under NO_FAIL_IN_CYCLE (`ERR_CLASSROOM_NONCOMPLIANT`, HTTP 422); and no improvement plan of the school may sit in `OPEN`, `OVERDUE` or `SUBMITTED` (`ERR_OPEN_IMPROVEMENT_PLAN`, HTTP 409). A successful submission stamps `submitted_at` and moves the application to `UNDER_REVIEW`.

Classroom clearance has two variants, and the application type chooses which applies. Both consider every audit of each classroom, from any visit and any auditor. Under LATEST_PASS — used at `MEMBERSHIP` submission — a classroom clears when its most recent audit, chosen by greatest `created_at` with same-instant filings tie-broken by server receipt order rather than by id, has verdict `COMPLIANT` and the room's `compliance_override` is `NONE`; earlier failures are forgiven. Under NO_FAIL_IN_CYCLE — used at `ACCREDITATION` submission — a classroom clears when no audit whose `observed_at` date falls inside the trailing 12 calendar months, inclusive of today, has verdict `NONCOMPLIANT`, at least one such in-window audit exists, and the room's `compliance_override` is `NONE`. The school clears only when every classroom clears, and a school with zero classrooms never clears. The same audit history can pass one variant and fail the other: a single `NONCOMPLIANT` audit followed by a `COMPLIANT` one inside the window clears under LATEST_PASS but not under NO_FAIL_IN_CYCLE.

Decision rests with an `AccreditationReviewer`, who posts an `outcome` of `APPROVED`, `DENIED` or `RETURNED` with optional `notes`; only an `UNDER_REVIEW` application is actionable, otherwise `ERR_INVALID_STATE` (HTTP 409). Approval re-checks the school's dues currency at decision time — delinquency now fails with `ERR_DUES_DELINQUENT` (HTTP 402) even though submission passed — and for an `ACCREDITATION` application additionally requires the school's standing to be `GOOD_STANDING`, the supporting `REPORT_FILED` visit to carry verdict `COMPLIANT`, or `IMPROVEMENT_REQUIRED` whose improvement plan has been `VERIFIED`, and segregation of duties: the approving reviewer's `X-User-ID` must differ from the `consultant_id` recorded on that visit, failing with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — the reviewer is never the consultant who filed the supporting report. An approval advances the school's membership level per the application type and stamps the corresponding anniversary — `affiliated_since` when first reaching `AFFILIATE`, `member_since` for `MEMBER` (the tenure anchor for later accreditation), `accredited_since` for `ACCREDITED` — recomputes directory visibility, and increments the school's `version`. Either decision stamps `decided_at` and records the reviewer as `reviewer_user_id`; `DENIED` is terminal, while `RETURNED` reopens the revision cycle.

Standing runs on a parallel dimension, independent of level, driven jointly by reviewers and the clock. An `AccreditationReviewer` may move a school from `GOOD_STANDING` to `PROBATION`, from `PROBATION` to `SUSPENDED`, from `PROBATION` or `SUSPENDED` back to `GOOD_STANDING` — permitted only when no improvement plan of the school remains in `OPEN`, `OVERDUE` or `SUBMITTED` — and from `GOOD_STANDING`, `PROBATION` or `SUSPENDED` to terminal `REVOKED`, posting a `to_standing` with an optional `reason`. The system walks the same ladder downward on plan lateness: when one of the school's plans flips from `OPEN` to `OVERDUE`, the school drops from `GOOD_STANDING` to `PROBATION`, or from `PROBATION` to `SUSPENDED` if a further plan flips while already on probation; a school already `SUSPENDED` or `REVOKED` does not move further on plan lateness. Upward, when the school's last non-`VERIFIED` plan becomes `VERIFIED` — none remaining in `OPEN`, `OVERDUE` or `SUBMITTED` — a `PROBATION` school auto-restores to `GOOD_STANDING`, though a `SUSPENDED` school returns only by reviewer action.

Every standing transition carries the same retinue of side effects. Leaving `GOOD_STANDING` suspends each of the school's `UNDER_REVIEW` applications to `SUSPENDED` — idempotently, so an already-suspended application stays — and returning to `GOOD_STANDING` resumes each `SUSPENDED` application back to `UNDER_REVIEW`. A transition to `REVOKED` denies every application of the school still in `DRAFT`, `UNDER_REVIEW`, `RETURNED` or `SUSPENDED`. Each transition also recomputes directory visibility — which necessarily turns false on revocation — and increments the school's `version`. Applications remain listable throughout with filters on `school_id`, `status`, `type` and `supporting_self_study_id`.

### 3.8. The Public Directory

The Society's promise to parents is the directory. Its list read is public — no identity headers required — and exposes only schools whose `directory_visible` flag is set, returning them as an object with `items`, `total_count` and `has_more`, accepting the usual `limit` and `offset`. That flag is computed, and it demands four things at once: a membership level of `MEMBER` or `ACCREDITED`, a standing of `GOOD_STANDING`, a true `brand_compliant`, and a true `dues_current`. The flag is recomputed whenever the school's level, standing, brand inputs or `dues_paid_through` change, so a school appears and disappears from the directory as its circumstances move.

The per-school verification read answers what a parent actually asks. For a listed school it returns the full public payload: `school_id`, `display_name`, `listed` true, `membership_level`, `standing`, whether the school is `accredited`, and `brand_compliant`. For a school the server knows but which is not currently listed, it answers with `listed` false and the `display_name` only — confirming existence without asserting standing. An unknown identifier fails with `ERR_SCHOOL_NOT_FOUND` (HTTP 404).

## 4. Endpoint Definitions

All endpoints are mounted under `/society`. Endpoints that create a new resource — including ledger-style records such as dues payments, visit reports and attendance postings — answer `201 Created`; endpoints that act on or modify an existing resource answer `200 OK`. Request payloads, preconditions and side effects are defined by the narratives of §2 and §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /society/_clock/set_current_utc | Advance the logical clock; runs the time sweep | SocietyAdmin |
| POST | /society/standards-catalogs | Create a standards catalog edition in `DRAFT` | SocietyAdmin |
| GET | /society/standards-catalogs/{id} | Read one catalog edition | SocietyAdmin, AccreditationReviewer, SchoolAdmin, ProgramDirector, Registrar, Consultant |
| POST | /society/standards-catalogs/{id}/activate | Activate a `DRAFT` catalog; the previously `ACTIVE` one retires | SocietyAdmin |
| POST | /society/schools | Onboard a school at `APPLICANT` in `GOOD_STANDING` | SocietyAdmin |
| GET | /society/schools/{id} | Read one school with its computed fields | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Registrar |
| GET | /society/schools | List schools; filters `membership_level`, `standing`, `pinned_catalog_id` | SocietyAdmin, AccreditationReviewer, Registrar |
| POST | /society/schools/{id}/brand | Update the school's public brand usage | SchoolAdmin |
| POST | /society/schools/{id}/dues-payments | Record a dues payment through `period_end` | SocietyAdmin |
| POST | /society/schools/{id}/standing | Reviewer-driven standing change | AccreditationReviewer |
| GET | /society/directory | Public member-school directory | Anonymous |
| GET | /society/directory/{school_id} | Parent-facing verification for one school | Anonymous |
| POST | /society/classrooms | Create a classroom | SchoolAdmin |
| GET | /society/classrooms/{id} | Read one classroom | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |
| GET | /society/classrooms | List classrooms; filters `school_id`, `lead_credential_id`, `age_level` | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |
| POST | /society/classrooms/{id}/transfer-students | Move students between same-school, same-level classrooms | SchoolAdmin |
| POST | /society/classroom-audits | File a classroom standards audit | Consultant |
| GET | /society/classroom-audits/{id} | Read one audit with all computed fields | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |
| GET | /society/classroom-audits | List audits; filters `classroom_id`, `catalog_id`, `visit_id`, `verdict` | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |

| POST | /society/teacher-education-programs | Register a teacher education program in `PROVISIONAL` | SocietyAdmin |
| GET | /society/teacher-education-programs/{id} | Read one program | SocietyAdmin, AccreditationReviewer, ProgramDirector, Registrar |
| POST | /society/teacher-education-programs/{id}/status | Accreditation decision on a program | AccreditationReviewer |
| POST | /society/adult-learners | Enroll an adult learner into a program | ProgramDirector |
| GET | /society/adult-learners/{id} | Read one learner | SocietyAdmin, AccreditationReviewer, ProgramDirector, Registrar, AdultLearner |
| GET | /society/adult-learners | List learners; filters `program_id`, `status` | SocietyAdmin, AccreditationReviewer, ProgramDirector, Registrar |
| POST | /society/practicum-placements | Create a practicum placement directly in `ACTIVE` | ProgramDirector |
| GET | /society/practicum-placements/{id} | Read one placement | SocietyAdmin, ProgramDirector, AdultLearner, Registrar, AccreditationReviewer |
| GET | /society/practicum-placements | List placements; filters `learner_id`, `host_school_id`, `supervisor_credential_id`, `status` | SocietyAdmin, ProgramDirector, Registrar, AccreditationReviewer |
| POST | /society/practicum-placements/{id}/log-hours | Learner logs practicum hours | AdultLearner |
| POST | /society/practicum-placements/{id}/verify | Program director verifies practicum completion | ProgramDirector |
| POST | /society/practicum-placements/{id}/cancel | Cancel an `ACTIVE` placement | ProgramDirector |
| POST | /society/credentials | Issue a credential by age level | Registrar |
| GET | /society/credentials/{id} | Read one credential with both CE totals | SocietyAdmin, Registrar, AccreditationReviewer, AdultLearner, ProgramDirector, SchoolAdmin |
| GET | /society/credentials | List credentials; filters `learner_id`, `status`, `age_level` | SocietyAdmin, Registrar, AccreditationReviewer |
| POST | /society/credentials/{id}/renew | Renew an `ACTIVE` or `LAPSED` credential | AdultLearner, Registrar |
| POST | /society/credentials/{id}/revoke | Revoke a credential; fires the classroom and school cascade | AccreditationReviewer |
| POST | /society/school-applications | Create a level-advancement application in `DRAFT` | SchoolAdmin |
| GET | /society/school-applications/{id} | Read one application | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| GET | /society/school-applications | List applications; filters `school_id`, `status`, `type`, `supporting_self_study_id` | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| POST | /society/school-applications/{id}/submit | Submit a `DRAFT` or `RETURNED` application | SchoolAdmin |
| POST | /society/school-applications/{id}/review | Reviewer decision: `APPROVED`, `DENIED` or `RETURNED` | AccreditationReviewer |
| POST | /society/self-studies | Create a self-study in `DRAFT`, pinning the `ACTIVE` catalog | SchoolAdmin |
| GET | /society/self-studies/{id} | Read one self-study | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| GET | /society/self-studies | List self-studies; filters `school_id`, `pinned_catalog_id`, `status` | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| POST | /society/self-studies/{id}/submit | Submit a `DRAFT` or `RETURNED_FOR_REVISION` self-study | SchoolAdmin |

| POST | /society/self-studies/{id}/review | Reviewer decision: `ACCEPTED` or `RETURNED_FOR_REVISION` | AccreditationReviewer |
| POST | /society/verification-visits | Schedule a verification visit for an `ACCEPTED` self-study | AccreditationReviewer |
| GET | /society/verification-visits/{id} | Read one visit, including `verdict` and `findings` once filed | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |
| GET | /society/verification-visits | List visits; filters `school_id`, `self_study_id`, `consultant_id`, `status` | SocietyAdmin, AccreditationReviewer, SchoolAdmin, Consultant |
| POST | /society/verification-visits/{id}/cancel | Cancel a `SCHEDULED` visit | AccreditationReviewer |
| POST | /society/verification-visits/{id}/reports | Assigned consultant files the visit report | Consultant |
| GET | /society/improvement-plans/{id} | Read one improvement plan | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| GET | /society/improvement-plans | List plans; filters `school_id`, `visit_id`, `status` | SocietyAdmin, AccreditationReviewer, SchoolAdmin |
| POST | /society/improvement-plans/{id}/respond | School responds to an `OPEN` or `OVERDUE` plan | SchoolAdmin |
| POST | /society/improvement-plans/{id}/review | Reviewer verdict: `VERIFIED` or `CHANGES_REQUESTED` | AccreditationReviewer |
| POST | /society/pd-events | Create a professional-development event in `SCHEDULED` | SocietyAdmin |
| GET | /society/pd-events/{id} | Read one PD event | SocietyAdmin, AccreditationReviewer, Registrar, ProgramDirector, AdultLearner, SchoolAdmin, Consultant |
| POST | /society/pd-events/{id}/attendance | Record attendance at a `COMPLETED` event, creating a CE entry | SocietyAdmin |
| GET | /society/ce-entries/{id} | Read one CE credit entry | SocietyAdmin, Registrar, AccreditationReviewer, AdultLearner |
| GET | /society/ce-entries | List CE entries; filters `credential_id`, `pd_event_id`, `status` | SocietyAdmin, Registrar, AccreditationReviewer, AdultLearner |
| POST | /society/ce-entries/{id}/void | Void a CE entry, the ledger's compensating action | SocietyAdmin |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in the `error_id` field of the envelope. Trigger conditions are defined where each rule lives in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_SCHOOL_NOT_FOUND | 404 |
| ERR_CLASSROOM_NOT_FOUND | 404 |
| ERR_AUDIT_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_LEARNER_NOT_FOUND | 404 |
| ERR_PLACEMENT_NOT_FOUND | 404 |
| ERR_CREDENTIAL_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_SELF_STUDY_NOT_FOUND | 404 |
| ERR_VISIT_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_CATALOG_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_CE_ENTRY_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |

| ERR_CREDENTIAL_NOT_RENEWABLE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NO_ACTIVE_CATALOG | 422 |
| ERR_CATALOG_EFFECTIVE_ORDER | 422 |
| ERR_PLACEMENT_WINDOW_OVERLAP | 409 |
| ERR_PLACEMENT_WINDOW_INVALID | 422 |
| ERR_CONSULTANT_SCHEDULE_CONFLICT | 409 |
| ERR_VISIT_WINDOW_INVALID | 422 |
| ERR_SUPERVISOR_CAPACITY_EXCEEDED | 422 |
| ERR_SUPERVISOR_CREDENTIAL_INACTIVE | 409 |
| ERR_AGE_LEVEL_MISMATCH | 422 |
| ERR_HOST_SCHOOL_INELIGIBLE | 422 |
| ERR_PRACTICUM_NOT_VERIFIED | 422 |
| ERR_PROGRAM_NOT_ACCREDITED | 409 |
| ERR_DUPLICATE_CREDENTIAL | 409 |
| ERR_DUPLICATE_ATTENDANCE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_BRAND_DIFFERENTIATION_REQUIRED | 422 |
| ERR_DISPLAY_NAME_TAKEN | 409 |
| ERR_DUES_DELINQUENT | 402 |
| ERR_SELF_STUDY_REQUIRED | 422 |
| ERR_VERIFICATION_VISIT_REQUIRED | 422 |
| ERR_OPEN_IMPROVEMENT_PLAN | 409 |
| ERR_ACCREDITATION_TENURE_TOO_SHORT | 422 |
| ERR_CLASSROOM_REQUIRED | 422 |
| ERR_CLASSROOM_NONCOMPLIANT | 422 |
| ERR_IN_FLIGHT_APPLICATION_EXISTS | 409 |
| ERR_IN_FLIGHT_SELF_STUDY_EXISTS | 409 |
| ERR_TRANSFER_EXCEEDS_ENROLLMENT | 422 |
| ERR_TRANSFER_CROSS_SCHOOL | 422 |
| ERR_PRACTICUM_STANDARD_UNMET | 422 |
| ERR_INSUFFICIENT_CE_HOURS | 422 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_FEE_MISMATCH | 422 |
