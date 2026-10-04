# Laboratory Accreditation API — Product Requirements Document

## 1. Introduction

Laboratory accreditation is built on three pillars that must reinforce one another continuously rather than at a single point in time: enrollment in each testing discipline with an assigned inspection checklist, ongoing external proficiency testing with graded performance, and periodic peer inspection by inspectors drawn from other accredited laboratories. This document specifies the requirements for the Laboratory Accreditation Inspection & Proficiency Testing API, a system that coordinates the full lifecycle of these activities — laboratory application, discipline enrollment and checklist assignment, proficiency-testing subscriptions, challenge shipments, atomic result grading, performance investigations, corrective action and testing cessation, peer-inspection team assembly with conflict screening, finding citation and response, accreditation decisions, appeal and interim self-inspection, personnel qualification and competency assessment, and method validation evidence.

The system serves a quality-program audience with strict segregation of duties: accreditation program staff orchestrate cycles and render decisions, laboratory directors respond for their own institutions, peer inspectors cite and adjudicate findings, and proficiency-testing coordinators manage shipment logistics. Because several workflows hinge on logical time (submission deadlines, response deadlines, appeal windows, competency validity, and revocation cooling-off periods), the server maintains a settable logical clock so program staff and test harnesses can drive time-dependent transitions deterministically. Everything the system computes — performance standing, readiness posture, deficiency burden, provisional decisions — is a function of recorded history and the logical clock, never of wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity. The system recognizes five roles, spelled exactly: `PlatformAdmin`, `AccreditationOfficer`, `LaboratoryDirector`, `PTCoordinator`, and `Inspector`. A request missing either header, or carrying a role not in this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity binds differently per role. When `X-User-Role` is `LaboratoryDirector`, `X-User-ID` is the `id` of the acting `Laboratory`; ownership checks on any resource that references a `Laboratory` compare the resource's `laboratory_id` to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `InspectorProfile`; this is what lets the server stamp `cited_by_inspector_id` on a finding and enforce segregation of duties at accept time. When `X-User-Role` is `PlatformAdmin`, `AccreditationOfficer`, or `PTCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in narratives but never compares it to any entity's `id`.

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

List endpoints accept two optional query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock rather than consulting wall-clock time. Before any administrative call sets it, the logical clock reads exactly 2026-09-01T00:00:00Z and must never fall back to the host's wall clock. A `PlatformAdmin` may advance the clock by supplying a `current_utc` instant through the clock-setting capability.

Advancing the clock fires three families of automatic transitions: any `OPEN` shipment whose `due_at` the new clock value exceeds is closed with `closure_reason` set to `DEADLINE_ELAPSED`; any finding still `CITED` whose `response_due_at` the new clock value passes moves to `ESCALATED` and its parent cycle's burden is recomputed; and any `QUALIFIED` testing person whose latest competency assessment's `valid_until` the new clock value exceeds moves to `COMPETENCY_REVIEW`. All deadline comparisons, window checks, and age computations elsewhere in this document read this same logical clock.

### 2.5. Common Resource Properties

Every top-level resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter starting at creation that increments by one on every mutation to the resource, including mutations driven by cascades originating elsewhere.

When one write cascades into another entity (for example, a checklist assignment that activates its enrollment and enrolls its laboratory), each affected resource is mutated independently: its own `updated_at` is refreshed and its own `version` is incremented.

### 2.6. Cascading Consistency and Cross-Aggregate Propagation

Accreditation posture is hierarchical: a laboratory's `accreditation_status` and its `active_discipline_count` are functions of its enrollments, and enrollment status in turn propagates from probation cascades, reinstatement, investigation corrective action, and investigation cessation. Whenever any enrollment's `status` changes for any reason, the parent laboratory's `active_discipline_count` is recomputed as the number of that laboratory's enrollments whose `status` is `ACTIVE`. Probation and reinstatement additionally cascade to inspector profiles: when a laboratory enters `PROBATION`, every one of its affiliated inspectors in `ACTIVE` status becomes `SUSPENDED`; when a laboratory is reinstated from `PROBATION`, every suspended affiliated inspector returns to `ACTIVE`. These cascades are atomic with the triggering write — a laboratory decision and its downstream enrollment, inspector, and derived-counter mutations commit together.

### 2.7. Nested Resource and Identifier Validation

Requests that reference resources by identifier are validated in a strict left-to-right order, path parameters before body identifiers. The first identifier that does not correspond to an existing resource short-circuits the request with the corresponding not-found error: `ERR_LABORATORY_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RESULT_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`, or `ERR_METHOD_VALIDATION_NOT_FOUND` (or the generic `ERR_NOT_FOUND`), each with HTTP 404. Existence checks run before any state, safety, or temporal rule is evaluated, so a request to act on a nonexistent section under a nonexistent enrollment fails on the enrollment first.

### 2.8. Validation Ordering

When a request could violate several rules at once, the checks are evaluated in a fixed priority order, and only the first failing check's error is returned: (1) authentication of the two headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) existence of every referenced identifier (the 404 family); (4) state-machine admissibility, including terminal-state lockdown (`ERR_INVALID_STATE` and its domain variants); (5) regulatory safety rules such as self-inspection, reciprocal conflict, inspector suspension, specialty match, segregation of duties, the PT collection window, active-enrollment requirements, and the rolling-unsatisfactory cessation gate; (6) structural constraints such as duplicates, window overlaps, and payload-shape requirements; (7) temporal windows such as deadlines and appeal periods; (8) gate checks such as cycle posture, deficiency burden, validation-study adequacy, and the no-findings floor; and finally (9) cross-entity referential integrity beyond raw existence, such as a finding's section belonging to the cycle's laboratory. A conflict that could surface as two different errors therefore always surfaces as the higher-priority one.

### 2.9. Optimistic Concurrency Control

Exactly one write in the system carries an optimistic-concurrency guard. Assigning a checklist to a testing section whose parent enrollment is still `WAITING` is a mutating read of the enrollment's posture: it flips the enrollment to `ACTIVE` and may flip the laboratory from `APPLIED` to `ENROLLED`. When the parent enrollment is `WAITING`, the assignment request must carry `expected_enrollment_version` equal to the enrollment's current `version`. If another writer has advanced the enrollment's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than re-applying the activation cascade against a posture the client never observed. When the parent enrollment is no longer `WAITING`, the `expected_enrollment_version` field is ignored. No other endpoint in the system takes a version field.

### 2.10. Numeric Precision and Rounding

Two quantities in the system have pinned rounding behavior. A proficiency-testing `event_score` is expressed with exactly one decimal place, rounded half-up. A competency `composite_score` is expressed with exactly two decimal places, rounded half-up, and — critically — each per-element weight contributing to it is itself rounded half-up to four decimal places *before* the weights are summed. This round-then-sum order is pinned; summing raw ratios and rounding only at the end can differ in the second decimal place and is not an acceptable implementation. All other numeric fields (`correlation_r_squared`, `precision_cv_pct`, individual analyte and element scores) preserve the precision at which they were supplied.

### 2.11. Interval Semantics for Overlap Checks

Two resources in the system reject overlapping time windows, with deliberately different interval semantics. Inspection cycles for the same laboratory use half-open windows — the window begins at `scheduled_start` (inclusive) and ends at `scheduled_end` (exclusive) — so a new cycle whose `scheduled_start` equals an existing cycle's `scheduled_end` merely touches the existing window and is permitted. Proficiency-testing shipments for the same subscription use closed windows inclusive at both ends, from `shipped_at` through `due_at` — so a new shipment whose `shipped_at` equals an existing open shipment's `due_at` *is* an overlap and is rejected. These two conventions are not interchangeable; §3 states the exact status filters under which each check applies.

## 3. Business Logic & Workflows

### 3.1. Laboratories, Enrollment, and the First-Activation Cascade

An `AccreditationOfficer` registers a laboratory by supplying its legal `name` and its CLIA certificate number `clia_number`, which must be unique across all laboratories in the system; a duplicate submission is rejected with `ERR_DUPLICATE_CLIA`. A new laboratory begins life in `APPLIED` accreditation status with an `active_discipline_count` of zero. `ACCREDITATION_REVOKED` is the laboratory's only terminal state.

A `LaboratoryDirector` then enrolls the laboratory in testing disciplines by creating a `DisciplineEnrollment` with a `laboratory_id` and a `discipline` drawn from `CHEMISTRY`, `HEMATOLOGY`, `MICROBIOLOGY`, `IMMUNOLOGY`, `MOLECULAR`, or `TRANSFUSION`. Each laboratory may hold at most one enrollment per discipline; a second enrollment in the same discipline for the same laboratory is rejected with `ERR_DUPLICATE_ENROLLMENT`. A new enrollment begins in `WAITING` status with both standing fields, `standing_per_event` and `standing_rolling`, reading `SATISFACTORY` and an `unsuccessful_event_streak` of zero.

Within an enrollment, the director defines one or more `TestingSection` records — for example a "Core Chemistry Bench" — by supplying the `enrollment_id` and a `section_name`. The optional `critical_testing` flag defaults to false and marks critical-care or stat benches; as §3.6 describes, it doubles a deficiency's weight in the cycle burden. Every section begins with `checklist_status` equal to `UNASSIGNED` and with `checklist_code` and `checklist_version` both null until an assignment occurs.

An `AccreditationOfficer` assigns a checklist edition to a section by naming the desired `checklist_code` and `checklist_version`. The section must currently be `UNASSIGNED` — attempting to assign a section whose `checklist_status` is already `ASSIGNED` is rejected with `ERR_CHECKLIST_ALREADY_ASSIGNED` — and the parent enrollment must be in `ACTIVE` or `WAITING` status, otherwise the request fails with `ERR_ENROLLMENT_INACTIVE`. The named edition must be a registered, non-retired checklist edition or the request fails with `ERR_CHECKLIST_UNKNOWN`. When the parent enrollment is still `WAITING`, the OCC rule of §2.9 applies and the payload must carry `expected_enrollment_version`. On a successful assignment the section's `checklist_code` and `checklist_version` are pinned from the request, the section moves to `ASSIGNED`, and the parent enrollment's `version` is incremented by one. If this assignment is the one that leaves the enrollment with zero `UNASSIGNED` sections while the enrollment was `WAITING`, the enrollment cascades to `ACTIVE` as part of the same write; and if the laboratory was still `APPLIED`, that same write further cascades the laboratory to `ENROLLED`. The laboratory's `active_discipline_count` is recomputed. `CEASED` is the enrollment's only terminal state.

Checklist editions themselves are governed by the officer. Registering a `ChecklistEditionSummary` requires a `checklist_code` (the family, such as CHM) and a `checklist_version` (the edition string, such as 2026), which must be unique per checklist family; a duplicate edition registration is rejected with `ERR_INVALID_REQUEST`. Registration optionally names a `retires_checklist_version`. When it does, every section whose `checklist_code` matches the family, whose pinned `checklist_version` equals the retired edition, and whose `checklist_status` is `ASSIGNED` flips automatically to `CHECKLIST_INVALIDATED`, and the edition summary's `retired_count` records how many sections were invalidated. An invalidated section may be re-assigned through the same assignment action — assignment from `CHECKLIST_INVALIDATED` is permitted as long as the parent enrollment is not `CEASED` (else `ERR_ENROLLMENT_INACTIVE`) — and pins the new edition, but re-assignment from `CHECKLIST_INVALIDATED` does not cascade enrollment state: it never re-activates an enrollment.

### 3.2. Proficiency Testing: Subscriptions, Shipments, and Atomic Grading

Once an enrollment is `ACTIVE`, a `LaboratoryDirector` subscribes it to proficiency testing by creating a `PTSubscription` with the `enrollment_id` and an `analytes` array. Each analyte is an object with a `name` and a `critical` boolean; the array must be non-empty and at least one analyte must be flagged critical, otherwise the request is rejected with `ERR_INVALID_REQUEST`. Subscribing a non-active enrollment fails with `ERR_ENROLLMENT_INACTIVE`.

A `PTCoordinator` records each challenge shipment against a subscription by supplying the `subscription_id` and an `event_code` such as "C-2026-A". The server stamps `shipped_at` with the current logical time and computes `due_at` as exactly ten calendar days after `shipped_at`. A new shipment begins `OPEN` with `closure_reason` null. Shipments of one subscription may not overlap in time: the closed interval from `shipped_at` through `due_at`, inclusive at both ends, must not intersect the corresponding interval of any other `OPEN` shipment of the same subscription — including the boundary case where the new `shipped_at` equals the existing shipment's `due_at` — or the request is rejected with `ERR_SHIPMENT_WINDOW_OVERLAP`. A coordinator may close an `OPEN` shipment administratively, which sets `closure_reason` to `ADMIN_CLOSED`; closing a shipment that is no longer `OPEN` fails with `ERR_SHIPMENT_CLOSED`. Independently, the logical clock closes shipments whose deadline elapses, setting `closure_reason` to `DEADLINE_ELAPSED` (§2.4). A missed deadline is a scored absence, not an unsuccessful event: no grading cascade and no standing change follows from a deadline closure.

Result submission is the atomic heart of the proficiency program. A `LaboratoryDirector` submits a `PTResult` naming the `shipment_id`, the `collected_at` instant at which the laboratory ran the challenge sample, and an `analyte_scores` array of objects pairing each analyte `name` with a `score` from 0 to 100. Grading is atomic with submission: a successfully created result has already transitioned from `SUBMITTED` to `GRADED` within the same write. Several guards protect the submission. The shipment must still be `OPEN` (`ERR_SHIPMENT_CLOSED` otherwise); the current logical time must not exceed the shipment's `due_at` (`ERR_SUBMISSION_DEADLINE_PASSED`); the `collected_at` must fall within the closed viability window from `shipped_at` through five calendar days after `shipped_at` (`ERR_PT_COLLECTION_WINDOW`); the parent enrollment must be `ACTIVE` (`ERR_ENROLLMENT_INACTIVE`); and the analyte names in `analyte_scores` must cover exactly the subscription's analyte names — no missing names, no extras — (`ERR_INVALID_REQUEST`).

Grading computes two derived fields. Let the total analyte count be the size of the subscription's `analytes` array, and let the passed count be the number of submitted entries whose `score` is at least 80. The `event_score` is one hundred times the passed count divided by the total count, rounded half-up to one decimal place. The `event_evaluation` is `UNSATISFACTORY` when the `event_score` is below 80.0 or when any analyte flagged `critical` in the subscription received a `score` below 80; otherwise it is `SATISFACTORY`. Both thresholds are inclusive in the passing direction — an `event_score` of exactly 80.0 with no critical failure is `SATISFACTORY`. The dual rule means a two-analyte subscription with one critical analyte scored 79 fails twice over, while the same 79 on a non-critical analyte fails only through the aggregate.

Each grading also recomputes the enrollment's three standing fields over its graded history. Consider the sequence of this enrollment's results in `GRADED` status — `VOID` results are excluded entirely — ordered by the shipment's `shipped_at` ascending, ties broken by the result's `created_at` ascending. `standing_per_event` is `UNSATISFACTORY` if the most recent element of that sequence was `UNSATISFACTORY`, otherwise `SATISFACTORY` (an empty history reads `SATISFACTORY`); this variant reacts to every event and self-heals on the next satisfactory grading. `standing_rolling` is `UNSATISFACTORY` if the history holds at least two graded results and at least two of the last three graded results (or the last `N` when the history is shorter than three) are `UNSATISFACTORY`; this variant is sticky — one new satisfactory grading cannot clear it while the window still holds two unsuccessful events — so a sequence of unsuccessful, unsuccessful, satisfactory heals per-event standing but leaves rolling standing `UNSATISFACTORY`. `unsuccessful_event_streak` counts the consecutive most-recent graded results that were unsuccessful and resets to zero on a satisfactory event.

If, after a grading, either standing variant reads `UNSATISFACTORY` and no investigation for this enrollment sits in a non-terminal status (`OPEN`, `UNDER_REVIEW`, or `CORRECTIVE_ACTION_REQUIRED`), the system automatically opens a `PTInvestigation` in `OPEN` status, records which variants fired in `trigger_variant` as `PER_EVENT`, `ROLLING`, or `BOTH`, stamps the `enrollment_id`, and appends this result's id to `linked_result_ids`. Grading alone never changes enrollment status, even when the streak grows; cessation requires investigation action. A `PTCoordinator` may void a result that is still `SUBMITTED` (a test-driving correction); attempting to void a `GRADED` result is rejected with `ERR_RESULT_ALREADY_GRADED`. `GRADED` and `VOID` are the result's terminal states.

### 3.3. Investigations: Corrective Action, Resolution, and Testing Cessation

Investigations are the enforcement arm of the proficiency program. An `AccreditationOfficer` drives each one through a small state machine whose terminal states are `RESOLVED` and `TESTING_CEASED`.

Beginning review moves an investigation from `OPEN` to `UNDER_REVIEW`; any other source state is rejected with `ERR_INVALID_INVESTIGATION_STATE`. Requiring corrective action moves it from `UNDER_REVIEW` to `CORRECTIVE_ACTION_REQUIRED` and demands a non-empty `corrective_action_notes` plan text in the payload (an absent or empty note fails with `ERR_INVALID_REQUEST`). This transition carries a hard cross-entity cascade: the parent enrollment moves to `SUSPENDED` and the laboratory's `active_discipline_count` is recomputed.

Resolution is available from three source states with slightly different consequences. Resolving from `CORRECTIVE_ACTION_REQUIRED` returns the parent enrollment to `ACTIVE`, recomputes the laboratory's `active_discipline_count`, and resets the enrollment's `unsuccessful_event_streak` to zero. Resolving directly from `OPEN` or from `UNDER_REVIEW` resets the streak to zero as well but does not touch enrollment status. In all three cases the standing fields are deliberately left alone: `standing_per_event` and `standing_rolling` are functions of graded history and are not cleared by resolution.

Ceasing testing is the severe remedy, available from `OPEN` or `UNDER_REVIEW` only (any other source state fails with `ERR_INVALID_INVESTIGATION_STATE`), and only while the enrollment's `standing_rolling` is `UNSATISFACTORY` — otherwise the request fails with `ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY`. Cessation cascades the parent enrollment to `CEASED` and recomputes the laboratory's `active_discipline_count`. Enrollment suspension is cyclic with activation: an enrollment in `SUSPENDED` returns to `ACTIVE` through laboratory reinstatement or investigation resolution, and in either case the standing fields are preserved exactly as graded history dictates.

### 3.4. Inspection Cycles and Team Assembly

The peer-inspection model has accredited laboratories inspect one another. An `AccreditationOfficer` schedules an `InspectionCycle` for a laboratory by supplying the `laboratory_id`, a `scheduled_start` (inclusive window start), and a `scheduled_end` (exclusive window end); the end must be strictly after the start or the request fails with `ERR_INVALID_REQUEST`. One laboratory's cycles may not pile up: if the half-open window from `scheduled_start` to `scheduled_end` intersects the window of any existing cycle of the same laboratory whose status is `TEAM_ASSEMBLY`, `SCREENED`, `CONDUCTED`, or `FINDINGS_ISSUED`, the creation is rejected with `ERR_CYCLE_WINDOW_OVERLAP`; windows that merely touch — the existing cycle's `scheduled_end` equal to the new `scheduled_start` — do not overlap. A new cycle begins in `TEAM_ASSEMBLY` with `posture_ready` false, `deficiency_burden_score` zero, `provisional_decision` and `final_decision` null, and `appeal_count` zero.

The officer builds the team by creating `TeamAssignment` records pairing an `inspection_cycle_id` with an `inspector_id` and a `role_in_team` of `LEAD` or `MEMBER`; each assignment begins `PENDING`. Inspectors themselves are registered as `InspectorProfile` records with a `full_name`, the `affiliated_laboratory_id` of their employer laboratory, and a non-empty `specialties` array drawn from the six discipline values. An inspector profile is `ACTIVE` by default and becomes `SUSPENDED` only through the laboratory probation cascade (§2.6), restored to `ACTIVE` by reinstatement.

Clearing a `PENDING` assignment is the conflict-screening gate, and it enforces four checks. The inspector must be `ACTIVE` (`ERR_INSPECTOR_SUSPENDED`); the inspector's `specialties` must include at least one discipline in which the cycle's laboratory holds a `WAITING` or `ACTIVE` enrollment (`ERR_SPECIALTY_MISMATCH`); the inspector's `affiliated_laboratory_id` must differ from the cycle's laboratory (`ERR_SELF_INSPECTION`); and the inspector's affiliated laboratory must not have participated in inspecting this laboratory recently — specifically, there must be no other cycle of this laboratory, in any status from `CONDUCTED` onward through `RE_DECIDED`, whose `scheduled_start` falls within the 365 days before this cycle's `scheduled_start` and which carries any team assignment (in `CLEARED`, `PENDING`, or `REPLACED` status) whose inspector shares this inspector's affiliated laboratory — (`ERR_RECIPROCAL_CONFLICT`). Clearing a non-`PENDING` assignment fails with `ERR_INVALID_STATE`. The officer may instead flag a `PENDING` assignment as `CONFLICTED`, and may then replace a `CONFLICTED` assignment by supplying a `replacement_inspector_id`; the replacement id must reference an existing inspector profile (`ERR_INSPECTOR_NOT_FOUND`) and the replacement creates a fresh `PENDING` assignment on the same cycle with the same `role_in_team`, leaving the original assignment in its terminal `REPLACED` state. `CLEARED`, `CONFLICTED`, and `REPLACED` are all terminal for an assignment.

Screening the team moves the cycle from `TEAM_ASSEMBLY` to `SCREENED`. It requires at least one `CLEARED` assignment with `role_in_team` equal to `LEAD` and no lingering `PENDING` assignments — every assignment on the cycle must be `CLEARED` or `REPLACED` — otherwise the request fails with `ERR_TEAM_INCOMPLETE`; and it requires that no assignment on the cycle remain `CONFLICTED` (conflicted inspectors must be replaced first), otherwise `ERR_CONFLICTED_INSPECTOR`. Screening from any state other than `TEAM_ASSEMBLY` fails with `ERR_INVALID_STATE`.

### 3.5. Readiness Posture, Personnel, and Method Validation

Conducting the on-site inspection is gated by a derived readiness posture stored on the cycle as `posture_ready`. The posture is recomputed and stored on every mutation that touches its inputs — checklist assignment, enrollment status change, personnel qualification change, or method-validation approval — and it is computed over the laboratory's *current* state, not the state at cycle creation. `posture_ready` is true only when all four conditions hold: every testing section belonging to an `ACTIVE` enrollment of the cycle's laboratory has `checklist_status` equal to `ASSIGNED`; every personnel record belonging to an `ACTIVE` enrollment of the laboratory has `qualification_status` equal to `QUALIFIED`; every `ACTIVE` enrollment of the laboratory has at least one `APPROVED` method validation; and the laboratory has at least one `ACTIVE` enrollment. `SUSPENDED` and `CEASED` enrollments are excluded from the first three requirements entirely.

Personnel evidence begins with the `LaboratoryDirector` registering a `PersonnelRecord` under an enrollment, supplying `enrollment_id`, `person_name`, and a `personnel_role` of `DIRECTOR`, `TECHNICAL_SUPERVISOR`, or `TESTING_PERSONNEL`. A new record starts `PROVISIONAL` with `consecutive_failed_assessments` zero. An `AccreditationOfficer` verifies the record, moving it from `PROVISIONAL` to `QUALIFIED` (from any other state the verification fails with `ERR_INVALID_STATE`). `DISQUALIFIED` is terminal.

Competency is then demonstrated periodically. The director records a `CompetencyAssessment` with the `personnel_id`, an `assessed_at` instant, and an `element_scores` array of exactly six numbers, each between 0 and 100 inclusive, in a fixed element order; any other shape fails with `ERR_INVALID_REQUEST`. Chronology must be strictly increasing: `assessed_at` must be strictly after the `assessed_at` of every prior assessment for the same person, with no backdating, otherwise the request fails with `ERR_ASSESSMENT_OVERLAP`; the personnel must exist under a non-`CEASED` enrollment (`ERR_ENROLLMENT_INACTIVE`). From the six element scores the system computes a `composite_score`: each element score is divided by 600.0 and that per-element ratio is rounded half-up to four decimal places; the six rounded ratios are summed, multiplied by one hundred, and the result is rounded half-up to two decimal places. This round-then-sum order is pinned (§2.10). The assessment `passed` when the `composite_score` is at least 85.0 and every element score is at least 70. Its `valid_until` is exactly 365 days after `assessed_at`, treated as a closed interval end.

Assessment outcomes drive personnel status automatically. A passing assessment moves the person to `QUALIFIED` (including recovery from `COMPETENCY_REVIEW`) and resets `consecutive_failed_assessments` to zero. A failing assessment increments `consecutive_failed_assessments`; when the count is below two the person moves from `QUALIFIED` to `COMPETENCY_REVIEW`, and when the count reaches two the person moves to `DISQUALIFIED` — from either `QUALIFIED` or `COMPETENCY_REVIEW`. Independently, the logical clock moves a `QUALIFIED` person to `COMPETENCY_REVIEW` when it advances beyond the `valid_until` of their latest assessment (§2.4).

Method evidence follows a parallel track. The director registers a `MethodValidation` under an enrollment with a `method_name`, the `instrument_name` the method runs on, the correlation study's `correlation_r_squared`, and the precision study's `precision_cv_pct`; the record starts `DRAFT`. The director submits it (`DRAFT` to `SUBMITTED`), and an `AccreditationOfficer` then approves or rejects it. Approval requires the record to be `SUBMITTED` (else `ERR_INVALID_STATE`), the parent enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_INACTIVE`), and the study to meet both thresholds: `correlation_r_squared` at least 0.95 and `precision_cv_pct` at most 10.0, failing which the request is rejected with `ERR_VALIDATION_STUDY_INADEQUATE`. Rejection from `SUBMITTED` moves the record to `REJECTED`; both `APPROVED` and `REJECTED` are terminal. Approval is one of the posture inputs, so it triggers a recompute of every cycle's `posture_ready` for that laboratory.

### 3.6. Findings, Burden, and the Response Clock

With the team screened, conducting the inspection moves the cycle from `SCREENED` to `CONDUCTED`. Two gates apply: the cycle's `posture_ready` must be true (`ERR_CYCLE_NOT_READY`), and the current logical time must fall within the inspection window — at or after `scheduled_start` and strictly before `scheduled_end` — otherwise `ERR_INSPECTION_WINDOW_NOT_OPEN`. Conducting from any state other than `SCREENED` fails with `ERR_INVALID_STATE`.

During a conducted cycle, an `Inspector` cites deficiencies by creating an `InspectionFinding` with the `inspection_cycle_id`, the `section_id` of the testing section where the deficiency was observed, the `checklist_item_code` being cited (such as "CHM.10230"), and a `deficiency_level` of `LEVEL_1` or `LEVEL_2`. The cited section must belong to an enrollment of the cycle's laboratory; citing a section from another laboratory's enrollment fails with `ERR_SECTION_NOT_IN_LABORATORY`. The server stamps `cited_by_inspector_id` from the citing inspector's `X-User-ID`. A new finding begins `CITED` with `response_due_at` null, and its creation recomputes the parent cycle's `deficiency_burden_score`.

The burden is the cycle's live risk metric. It sums, over the cycle's findings in `CITED`, `RESPONSE_SUBMITTED`, or `ESCALATED` status, a per-finding weight: 4 for a `LEVEL_2` deficiency, 2 for a `LEVEL_1`, doubled when the cited section's `critical_testing` flag is true. `ACCEPTED` and `WITHDRAWN` findings contribute nothing. Because the burden is recomputed whenever a finding is cited, accepted, withdrawn, or escalated, and is evaluated live at decision time, a pending `RESPONSE_SUBMITTED` finding still counts toward the burden with its full weight.

Issuing findings moves the cycle from `CONDUCTED` to `FINDINGS_ISSUED` and requires that at least one finding on the cycle stand in `CITED`, `RESPONSE_SUBMITTED`, or `ACCEPTED` status (`ERR_NO_FINDINGS` otherwise). Issuance stamps, on every finding still `CITED` or `RESPONSE_SUBMITTED`, a `response_due_at` computed from the issuance instant: a `LEVEL_1` finding is due exactly fourteen calendar days after issuance, while a `LEVEL_2` finding is due at 23:59:59Z on the fifth business day strictly after the issuance date, where business days are Monday through Friday with no holiday calendar — advancing one calendar day at a time and counting only weekdays, so a Friday issuance gives a `LEVEL_2` finding a seven-calendar-day effective window. Issuance also computes the cycle's `provisional_decision`, a forward-looking, deliberately pessimistic projection that treats every currently unresolved finding as remaining unresolved: burden zero yields `ACCREDITED`, burden above zero and at most 6 yields `CONDITIONAL`, and burden above 6 yields `DENIED`.

The laboratory answers each citation through its `LaboratoryDirector`, submitting `response_text` against a finding that is still `CITED`; responding is only admitted while the parent cycle is `FINDINGS_ISSUED` (`ERR_FINDING_NOT_RESPONDABLE` otherwise) and while the current logical time has not passed `response_due_at` (`ERR_RESPONSE_DEADLINE_PASSED`). A successful response moves the finding to `RESPONSE_SUBMITTED`. An `Inspector` then adjudicates: acceptance moves the finding to `ACCEPTED` and recomputes the cycle's burden, but segregation of duties forbids the citing inspector from accepting the response to their own citation — if `X-User-ID` equals the finding's `cited_by_inspector_id`, the request fails with `ERR_SEGREGATION_OF_DUTIES`. An inspector may alternatively withdraw a `CITED` finding, moving it to `WITHDRAWN` and recomputing the burden. Findings that outlive their deadline escalate automatically under the logical clock (§2.4): a `CITED` finding whose `response_due_at` passes moves to `ESCALATED`, the burden is recomputed, and the escalated finding remains in the burden permanently — it permanently blocks any non-denial accreditation decision. `ACCEPTED`, `ESCALATED`, and `WITHDRAWN` are terminal.

### 3.7. Decisions, Appeals, and the Probation Arc

Deciding the cycle moves it from `FINDINGS_ISSUED` to `DECIDED`. The officer supplies a `decision` field of `ACCREDITED`, `CONDITIONAL`, or `DENIED` (any other value or a missing field fails with `ERR_INVALID_REQUEST`). The burden gates the outcome: if the cycle's `deficiency_burden_score` is above zero — including any contribution from findings still awaiting acceptance in `RESPONSE_SUBMITTED` — the only admissible decision is `DENIED`, and any other decision is rejected with `ERR_DECISION_BLOCKED_BY_BURDEN`. A successful decision sets `final_decision` and cascades to the laboratory: an `ACCREDITED` decision moves an `ENROLLED` laboratory to `ACCREDITED` (a no-op if it is already accredited), while a `DENIED` decision drives the laboratory into `PROBATION`, which cascades every `ACTIVE` enrollment of the laboratory to `SUSPENDED` and every `ACTIVE` affiliated inspector profile to `SUSPENDED`, recomputing `active_discipline_count` as part of the same atomic write (§2.6).

Appeals give the laboratory a bounded second track. From `DECIDED`, the `LaboratoryDirector` may appeal, provided the current logical time is within thirty days of the decision instant — the `updated_at` stamp of the transition into `DECIDED` — (`ERR_APPEAL_WINDOW_CLOSED` thereafter) and the cycle's `appeal_count` is below two (`ERR_APPEAL_LIMIT_REACHED` at the limit). Appealing increments `appeal_count` by one and moves the cycle to `APPEALED`. The director then performs an interim self-inspection, moving the cycle to `INTERIM_SELF_INSPECTION`, after which the officer re-decides from `INTERIM_SELF_INSPECTION` to `RE_DECIDED` under the same rules as the original decision — a valid `decision` value, and `DENIED` forced whenever the burden is above zero (`ERR_DECISION_BLOCKED_BY_BURDEN`). Re-deciding overwrites `final_decision` and applies the identical laboratory cascade: `ACCREDITED` accredits the laboratory, `DENIED` drives the probation cascade. The loop is cyclic: from `RE_DECIDED` the laboratory may appeal again within thirty days of the re-decision, subject to the same two-appeal ceiling, walking `DECIDED` to `APPEALED` to `INTERIM_SELF_INSPECTION` to `RE_DECIDED` and back while appeals remain.

A laboratory in `PROBATION` has two exits. An `AccreditationOfficer` may reinstate it to `ENROLLED`, but only while no investigation of any of the laboratory's enrollments sits in a non-terminal status (`OPEN`, `UNDER_REVIEW`, or `CORRECTIVE_ACTION_REQUIRED`) — otherwise the request fails with `ERR_OPEN_INVESTIGATION_EXISTS` — and only from `PROBATION` itself (`ERR_INVALID_STATE`). Reinstatement cascades every `SUSPENDED` enrollment of the laboratory back to `ACTIVE` and every `SUSPENDED` affiliated inspector back to `ACTIVE`. Alternatively, after a sustained probation, the officer may revoke accreditation entirely: revocation requires the laboratory to be in `PROBATION` (`ERR_INVALID_STATE`) and requires the current logical time to be at least 180 days after the most recent `DENIED` final decision issued for this laboratory (`ERR_REVOKE_TOO_EARLY` otherwise). Revocation lands the laboratory in its terminal `ACCREDITATION_REVOKED` state.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource or drive a state transition return `200 OK`. All endpoints enforce the envelope, pagination, and error rules of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock; fires time-based automatic transitions | PlatformAdmin |
| POST | `/laboratories` | Create a laboratory | AccreditationOfficer |
| GET | `/laboratories` | List laboratories | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/laboratories/{labId}` | Get a laboratory | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/laboratories/{labId}/reinstate` | Reinstate a PROBATION laboratory to ENROLLED | AccreditationOfficer |
| POST | `/laboratories/{labId}/revoke` | Revoke accreditation after sustained probation | AccreditationOfficer |
| GET | `/laboratories/{labId}/enrollments` | List a laboratory's enrollments | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/inspector-profiles` | Register an inspector | AccreditationOfficer |
| GET | `/inspector-profiles` | List inspector profiles; filterable by affiliation | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/inspector-profiles/{inspectorId}` | Get an inspector profile | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/enrollments` | Enroll a laboratory in a discipline | LaboratoryDirector |
| GET | `/enrollments` | List enrollments; filterable by laboratory | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/enrollments/{enrollmentId}` | Get an enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/enrollments/{enrollmentId}/sections` | List an enrollment's sections | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/sections` | Create a testing section under an enrollment | LaboratoryDirector |
| GET | `/sections` | List sections; filterable by enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/sections/{sectionId}` | Get a section | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/sections/{sectionId}/assign-checklist` | Assign (or re-assign after invalidation) a section's checklist edition | AccreditationOfficer |
| POST | `/checklist-editions` | Register a checklist edition, optionally retiring the previous edition | AccreditationOfficer |
| GET | `/checklist-editions` | List registered checklist editions | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/pt-subscriptions` | Subscribe an ACTIVE enrollment to proficiency testing | LaboratoryDirector |
| GET | `/pt-subscriptions` | List PT subscriptions; filterable by enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/pt-subscriptions/{subscriptionId}` | Get a PT subscription | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/pt-shipments` | Record a challenge shipment for a subscription | PTCoordinator |
| GET | `/pt-shipments` | List shipments; filterable by subscription | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/pt-shipments/{shipmentId}` | Get a shipment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/pt-shipments/{shipmentId}/close` | Administratively close an open shipment | PTCoordinator |
| POST | `/pt-results` | Submit challenge results; grading is atomic with submission | LaboratoryDirector |
| GET | `/pt-results` | List PT results; filterable by shipment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/pt-results/{resultId}` | Get a PT result | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/pt-results/{resultId}/void` | Void an ungraded result | PTCoordinator |
| GET | `/pt-investigations` | List investigations; filterable by enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/pt-investigations/{investigationId}` | Get an investigation | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/pt-investigations/{investigationId}/begin-review` | Move an investigation from OPEN to UNDER_REVIEW | AccreditationOfficer |
| POST | `/pt-investigations/{investigationId}/require-corrective-action` | Require corrective action; suspends the enrollment | AccreditationOfficer |
| POST | `/pt-investigations/{investigationId}/resolve` | Resolve an investigation from OPEN, UNDER_REVIEW, or CORRECTIVE_ACTION_REQUIRED | AccreditationOfficer |
| POST | `/pt-investigations/{investigationId}/cease-testing` | Cease testing from OPEN or UNDER_REVIEW; ceases the enrollment | AccreditationOfficer |
| POST | `/inspection-cycles` | Schedule an inspection cycle for a laboratory | AccreditationOfficer |
| GET | `/inspection-cycles` | List cycles; filterable by laboratory | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/inspection-cycles/{cycleId}` | Get a cycle | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/inspection-cycles/{cycleId}/screen-team` | Move a cycle from TEAM_ASSEMBLY to SCREENED | AccreditationOfficer |
| POST | `/inspection-cycles/{cycleId}/conduct` | Move a cycle from SCREENED to CONDUCTED (gated by posture and window) | AccreditationOfficer |
| POST | `/inspection-cycles/{cycleId}/issue-findings` | Move a cycle from CONDUCTED to FINDINGS_ISSUED; stamps deadlines and provisional decision | AccreditationOfficer |
| POST | `/inspection-cycles/{cycleId}/decide` | Move a cycle from FINDINGS_ISSUED to DECIDED; cascades laboratory status | AccreditationOfficer |
| POST | `/inspection-cycles/{cycleId}/appeal` | Appeal a DECIDED or RE_DECIDED cycle | LaboratoryDirector |
| POST | `/inspection-cycles/{cycleId}/self-inspect` | Move a cycle from APPEALED to INTERIM_SELF_INSPECTION | LaboratoryDirector |
| POST | `/inspection-cycles/{cycleId}/re-decide` | Move a cycle from INTERIM_SELF_INSPECTION to RE_DECIDED | AccreditationOfficer |
| POST | `/team-assignments` | Assign an inspector to a cycle team | AccreditationOfficer |
| GET | `/team-assignments` | List assignments; filterable by cycle or inspector | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/team-assignments/{assignmentId}` | Get an assignment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/team-assignments/{assignmentId}/clear` | Clear a PENDING assignment after conflict screening | AccreditationOfficer |
| POST | `/team-assignments/{assignmentId}/flag-conflict` | Flag a PENDING assignment as CONFLICTED | AccreditationOfficer |
| POST | `/team-assignments/{assignmentId}/replace` | Replace a CONFLICTED assignment; creates a new PENDING assignment | AccreditationOfficer |
| POST | `/inspection-findings` | Cite a deficiency during a conducted cycle | Inspector |
| GET | `/inspection-findings` | List findings; filterable by cycle, section, or citing inspector | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/inspection-findings/{findingId}` | Get a finding | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/inspection-findings/{findingId}/respond` | Laboratory responds to a cited finding | LaboratoryDirector |
| POST | `/inspection-findings/{findingId}/accept` | Inspector accepts a response (not the citing inspector) | Inspector |
| POST | `/inspection-findings/{findingId}/withdraw` | Inspector withdraws a cited finding | Inspector |
| POST | `/personnel-records` | Register a testing person under an enrollment | LaboratoryDirector |
| GET | `/personnel-records` | List personnel; filterable by enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/personnel-records/{personnelId}` | Get a personnel record | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/personnel-records/{personnelId}/verify-qualification` | Move a personnel record from PROVISIONAL to QUALIFIED | AccreditationOfficer |
| POST | `/competency-assessments` | Record a competency assessment; drives personnel status transitions | LaboratoryDirector |
| GET | `/competency-assessments` | List assessments; filterable by personnel | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/competency-assessments/{assessmentId}` | Get a competency assessment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/method-validations` | Register a method validation study | LaboratoryDirector |
| GET | `/method-validations` | List method validations; filterable by enrollment | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| GET | `/method-validations/{mvId}` | Get a method validation | PlatformAdmin, AccreditationOfficer, LaboratoryDirector, PTCoordinator, Inspector |
| POST | `/method-validations/{mvId}/submit` | Move a method validation from DRAFT to SUBMITTED | LaboratoryDirector |
| POST | `/method-validations/{mvId}/approve` | Approve a SUBMITTED method validation (threshold-gated) | AccreditationOfficer |
| POST | `/method-validations/{mvId}/reject` | Reject a SUBMITTED method validation | AccreditationOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_LABORATORY_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_SECTION_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_RESULT_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_PERSONNEL_NOT_FOUND` | 404 |
| `ERR_METHOD_VALIDATION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_CLIA` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_CHECKLIST_ALREADY_ASSIGNED` | 409 |
| `ERR_CHECKLIST_UNKNOWN` | 409 |
| `ERR_ENROLLMENT_INACTIVE` | 409 |
| `ERR_SHIPMENT_CLOSED` | 409 |
| `ERR_SUBMISSION_DEADLINE_PASSED` | 409 |
| `ERR_PT_COLLECTION_WINDOW` | 409 |
| `ERR_RESULT_ALREADY_GRADED` | 409 |
| `ERR_INVALID_INVESTIGATION_STATE` | 409 |
| `ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY` | 409 |
| `ERR_OPEN_INVESTIGATION_EXISTS` | 409 |
| `ERR_REVOKE_TOO_EARLY` | 409 |
| `ERR_SELF_INSPECTION` | 409 |
| `ERR_RECIPROCAL_CONFLICT` | 409 |
| `ERR_INSPECTOR_SUSPENDED` | 409 |
| `ERR_SPECIALTY_MISMATCH` | 409 |
| `ERR_TEAM_INCOMPLETE` | 409 |
| `ERR_CONFLICTED_INSPECTOR` | 409 |
| `ERR_CYCLE_NOT_READY` | 409 |
| `ERR_INSPECTION_WINDOW_NOT_OPEN` | 409 |
| `ERR_NO_FINDINGS` | 409 |
| `ERR_FINDING_NOT_RESPONDABLE` | 409 |
| `ERR_RESPONSE_DEADLINE_PASSED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_DECISION_BLOCKED_BY_BURDEN` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_SECTION_NOT_IN_LABORATORY` | 409 |
| `ERR_VALIDATION_STUDY_INADEQUATE` | 409 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_ASSESSMENT_OVERLAP` | 409 |
| `ERR_SHIPMENT_WINDOW_OVERLAP` | 409 |
