# Ehr Implementation Go Live API — Product Requirements Document

## 1. Introduction

Bringing a new electronic health record online across a multi-hospital health system is one of the largest coordinated undertakings a care organization ever attempts. Every departmental application must be configured, every clinician trained and verified, every legacy record converted, every laboratory, imaging, pharmacy and device interface proven to carry valid messages, and every order reconciled against the paper slips that accumulate during downtime — all against a contracted go-live instant that does not move. This document specifies the API that serves as the single system of record for that program of work, from the first planning meeting through post-live optimization and eventual archival.

The API is organized around an implementation program that owns a tree of facilities and departments, and around a set of cross-cutting satellite resources — staff, build items, test scenarios and defects, conversion batches, patient orders, interface channels and messages, cutover tasks, command-center tickets and staffing shifts — that describe the operational work. Its distinguishing characteristic is that the program advertises an aggregate *readiness posture* which is recomputed after every child mutation and which gates forward movement across the entire hierarchy; a program that has fallen into rollback posture admits only remediation work until it recovers. Layered on top of that gating are an ops-run epoch that scopes test and interface measurements, a logical clock that all time-derived values follow, optimistic concurrency on a small number of version-carrying write endpoints, and a segregation-of-duties model that keeps the person who tests a clinician separate from the person who certifies them.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request that omits either header, or that names a role the system does not recognise, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Beyond authentication, each operation is bound to a permitted set of roles; a caller whose `X-User-Role` is not authorized for the requested operation receives `ERR_UNAUTHORIZED` (HTTP 403).

The system recognises fourteen roles, spelled exactly as follows: `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TestLead`, `TrainingCoordinator`, `CredentialedTrainer`, `ConversionAnalyst`, `OrderReconciler`, `RevenueCycleAnalyst`, `InterfaceEngineer`, `CutoverLead`, `CommandCenterLead`, `TriageCommander`, and `OptimizationLead`.

Thirteen of these roles are `opaque` identities. When `X-User-Role` is `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TestLead`, `TrainingCoordinator`, `ConversionAnalyst`, `OrderReconciler`, `RevenueCycleAnalyst`, `InterfaceEngineer`, `CutoverLead`, `CommandCenterLead`, `TriageCommander`, or `OptimizationLead`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for instance as the proctor of record, or as the actor stamped on a segregation-of-duties decision — but it is never compared to any entity's `id`. The remaining role, `CredentialedTrainer`, is `entity_backed:CredentialedTrainer`: when `X-User-Role` is `CredentialedTrainer`, `X-User-ID` is the `id` of the acting `CredentialedTrainer` row itself, and ownership checks on any resource that references a trainer compare that resource's foreign-key field to `X-User-ID`. This is what allows the system to verify, for example, that the credential of the trainer proctoring an exam is current.

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

List endpoints accept a `limit` query parameter giving the maximum number of items to return; when it is absent the value is 10, the minimum accepted value is 1, and the maximum accepted value is 100. A companion `offset` parameter gives the number of items to skip and defaults to 0. Unless a list endpoint's description says otherwise, returned collections are ordered by creation timestamp ascending.

Every list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, whether or not the caller supplied pagination parameters. Note that the command-center ticket collection is the one listing that also accepts `limit` and `offset` directly among its declared query parameters, alongside its filter keys.

### 2.4. Common Resource Properties and Identifier Conventions

Entities created with the standard common-field treatment carry four system-managed properties. The `id` is a server-minted UUID with no type prefix or other decoration. The `created_at` is an ISO 8601 UTC timestamp with exactly three fractional digits (for example `2025-05-24T10:30:00.123Z`), set when the row is first created. The `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row — including mutations performed by the server without an explicit client request on that row, such as a cascade triggered by a parent's transition. The `version` is an integer that begins at 1 and increments by exactly one on every mutation of that row; it is the value that optimistic-concurrency checks compare against, and it is never accepted from a client as input.

`InterfaceMessage` is the exception: it does not use the common-field treatment. A message row carries only `id` and `created_at`. It has no `updated_at` and no `version`, and no operation compares a version against it. This matters because message rows are immutable observations — a received message is either later validated through its own `validation_status` dimension or rejected, and its audit trail is the `received_utc` stamp rather than a mutation counter.

### 2.5. Readiness Posture and Gating of Child Operations

An implementation program exposes a computed `readiness_posture` that is one of exactly three values: `OPEN`, `RESTRICTED`, or `ROLLBACK_REQUIRED`. This posture is an aggregate derived from the program's open defect load and its interface-channel health, and it is recomputed after every child mutation — it is never set directly by a client. Its companion `readiness_score` is a number between 0.00 and 100.00 inclusive.

The posture is a gate, not merely a report. Whenever the posture is `ROLLBACK_REQUIRED`, every forward-progress trigger is refused with `ERR_POSTURE_BLOCKS_OPERATION` (HTTP 409); only remediation triggers remain admissible — resolving a defect, the rollback decision itself, and the epoch-restore capability. The set of operations that consult the posture is: starting the program's build phase, starting the program's validation phase, finalizing validation, executing go-live, activating the command center, configuring facility build, marking a facility validated, completing the facility cutover dress rehearsal, opening departmental training, and beginning work on a system build item. When the posture is `OPEN` or `RESTRICTED`, those same operations proceed subject to their own additional preconditions — the posture gate has only two settings, blocking and non-blocking, and an operation with a stricter requirement (such as the requirement that posture be exactly `OPEN` before validation can be finalized) states that stricter requirement in its own workflow.

### 2.6. The Ops-Run Epoch and the Logical Clock

The program carries an integer `current_epoch_index` that begins at 0 and is advanced by exactly one each time the epoch-advance capability is exercised by an `ImplementationDirector`; no other operation changes it. The epoch is the scoping dimension for metrics that must be measured per run: a test scenario records the `executed_epoch` in which it last ran, and interface channels tally `validated_message_count` and `rejected_message_count` only for messages decided in the current epoch. Advancing the epoch triggers a program-wide sweep: `test_cycles_passed` is recomputed for every system build item of the program, and both message counters are recomputed for every interface channel of the program.

All time-derived behavior follows a logical clock rather than wall-clock time. The server's startup default for that clock is exactly `2026-09-01T00:00:00Z`: before any call the clock reads that instant, and it never silently falls back to the host's wall-clock time. The clock is moved only through an admin test-driving capability, restricted to `ImplementationDirector`, that accepts a `to_iso8601` instant and sets the logical clock to it; every time-derived computed value — defect `aging_hours`, message `latency_minutes`, trainer expiry, accounts-receivable age factors, training due dates — is subsequently measured against that value.

### 2.7. Optimistic Concurrency on Version-Carrying Writes

Three write operations carry an explicit optimistic-concurrency guard. Each requires the client to supply the version it last observed for the parent entity; when that observed version does not match the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The framing is a stale-read guard, not an overlapping-writer mechanic: the client is prevented from acting on a parent whose state has legitimately moved on since it last read it.

Staging a legacy data-conversion load against a facility requires `expected_facility_version` carrying the client's last observed `version` of that `Facility`, and a mismatch yields `ERR_STALE_VERSION`. Starting a trainer certification record against a staff member requires `expected_staff_version` carrying the client's last observed `version` of that `Staff`, with the same rejection; this matters because a prior certification or proficiency write legitimately changes the staffer's readiness, so a trainer certification must be evaluated against fresh state. Raising an optimization backlog item against a program requires `expected_ehr_implementation_version` carrying the client's last observed `version` of that `EhrImplementation`, again with `ERR_STALE_VERSION`; epoch advances and department-tree mutations change the program between reads, so the stale client view must re-read before scheduling work.

Only these three operations take a version field of this kind. Every other endpoint — including every other creating endpoint — does not accept an `expected_*_version` input, and one supplied to such an endpoint is refused as an invalid request.

### 2.8. Nested Resource Retrieval and Existence Ordering

The API validates path resources strictly left to right. When a path names more than one resource identifier, the system confirms the existence of the first, then the second, then the third, in the order the route declares them, and the request is rejected with the error corresponding to the *first* identifier that does not resolve. A conversion batch requested beneath a facility that does not exist yields `ERR_FACILITY_NOT_FOUND` (HTTP 404) before the system ever considers the batch id; a message requested beneath a channel that does not exist yields `ERR_CHANNEL_NOT_FOUND` (HTTP 404).

Body-supplied foreign keys are validated with the same discipline. Where a creating endpoint's input list declares several foreign-key fields, they are checked strictly in the order declared, and the first unresolved key determines the error. The distinct not-found identifiers are `ERR_EHR_IMPLEMENTATION_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_BUILD_ITEM_NOT_FOUND`, `ERR_TEST_SCENARIO_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CONVERSION_BATCH_NOT_FOUND`, and `ERR_PATIENT_ORDER_NOT_FOUND`, all at HTTP 404. The polymorphic reference carried by a command-center ticket is resolved with the same rule: a `target_ref` that names a `Department`, `Facility` or `InterfaceChannel` identifier which does not exist is reported as `ERR_DEPARTMENT_NOT_FOUND`.

Collection endpoints accept optional narrowing filters as query parameters, each mirroring a property the resource already carries: `status`, `severity`, `triage_state`, `clinical_state`, `billing_state`, `validation_status`, `scenario_class`, `task_class`, `support_role`, `application_code`, `staff_type`, `payload_class`, `channel_type` and `rollout_wave`, together with the relationship keys `ehr_implementation_id`, `facility_id`, `department_id`, `staff_id`, `primary_facility_id`, `preceptor_staff_id`, `system_build_item_id`, `interface_channel_id`, `proctored_by_trainer_id` and `linked_test_defect_id`. A filter that is omitted imposes no constraint.

### 2.9. Precision, Rounding and Representation of Numeric Values

Every numeric output the API publishes is rounded with the half-up rule, applied to the stated number of decimal places, and applied exactly once at the point the specification pins. Monetary-adjacent computed values — `readiness_score` and its optimistic sibling, `customization_risk_points`, `provisional_charge_cents`, `final_charge_cents`, `charge_variance_cents`, `variance_penalty_points`, `conversion_variance_index`, `proficiency_cleared_ratio`, `interface_message_validation_pass_rate`, `revenue_cycle_stabilization_index` — are published to two decimal places. The command-center SLA is published to zero decimal places, that is, as a whole number of minutes. Integer-valued results — `test_cycles_passed`, `order_reconciliation_balance`, `scheduled_epoch`, `variance_count` — are never fractional and are not rounded at all.

Where rounding order is consequential it is pinned explicitly and must be honoured. Charge capture rounds each line item to two decimal places first and sums the rounded lines afterwards; summing first and rounding once would change the reported cents whenever any line carries a half-cent residue. Customization risk accumulates the full unrounded total through every tier, weight and multiplier and rounds only once, at the very end.

### 2.10. Segregation of Duties and Trainer Credentialing Safeguards

Two paired activities must not be performed by the same principal. A caller whose `X-User-ID` has already recorded the result of a proficiency exam may not also certify that same staff member as a credentialed trainer; and a caller who approved a go/no-go decision may not also resolve the test defect linked to that decision. Violations are refused with `ERR_SOD_VIOLATION` (HTTP 403), on the result-recording and trainer-certification operations for the first pair and on the cutover-completion and defect-resolution operations for the second.

Independently of who acts, an exam may only be recorded by a proctor who legitimately holds the credential for the application under assessment. The proctor of record must hold a `CredentialedTrainer` row whose `status` is `CERTIFIED` for the exam's `application_code`; otherwise the recording attempt is refused with `ERR_UNVERIFIED_TRAINER` (HTTP 403).

### 2.11. Validation Priority Ladder

When more than one rule could reject the same request, the system applies a fixed ladder and reports the error of the earliest failing rung. Authentication is tested first and authorization second. Segregation of duties is tested third, and the trainer-credential check for exam recording fourth. Existence checks follow in path order, then body-declared foreign-key order, then polymorphic-reference resolution.

The ladder then moves through state: the target must be in the exact from-state of the transition being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409); it must not already be terminal where the operation forbids it (otherwise `ERR_ALREADY_TERMINAL`, HTTP 409); the owning program's `readiness_posture` must not be `ROLLBACK_REQUIRED` where the operation consults it (otherwise `ERR_POSTURE_BLOCKS_OPERATION`, HTTP 409); and a conversion batch's `attempt_epoch` must equal the program's `current_epoch_index` (otherwise `ERR_EPOCH_MISMATCH`, HTTP 409). Business-safety and business-constraint rungs come next, then temporal rungs, then referential rungs, and finally the capacity rungs. Two structural gates sit outside the ladder entirely and are evaluated before it: a request-shape gate refuses a malformed payload with `ERR_INVALID_REQUEST` (HTTP 400) — a missing required field, an invalid type or enum member, or any attempt to supply a server-managed `id`, `created_at` or `version` — while a negative or non-integer conversion batch size is refused with `ERR_BATCH_SIZE_INVALID` (HTTP 400).

Two rungs deserve their relative ordering called out explicitly. Because the trainer-credential check sits ahead of the state rungs, an exam recorded by an uncredentialed proctor surfaces as `ERR_UNVERIFIED_TRAINER` rather than being masked by a later state complaint. And because the segregation check sits ahead of the trainer-credential check, a self-dealing certifier surfaces as `ERR_SOD_VIOLATION` even when their credential is also defective.

### 2.12. Foundation Content, Local Customization and the Risk Ceiling

Each system build item declares how far it departs from the vendor's foundation content. The `build_classification` is exactly one of `FOUNDATION_ADOPTED`, `FOUNDATION_ADAPTED` or `LOCAL_CUSTOM`; `FOUNDATION_ADOPTED` means the foundation content was taken as shipped, `FOUNDATION_ADAPTED` means it was taken and lightly adjusted, and `LOCAL_CUSTOM` means it was replaced or extended locally. The `customization_depth` is a non-negative integer describing how deep that local modification runs, and is 0 for pure foundation adoption. The `local_custom_fields` is a list naming the individual fields or build records that were customized locally.

Completing a build item's build work scores that customization into `customization_risk_points`, and the score is a signal the organization treats as a control: a `LOCAL_CUSTOM` build item whose `customization_risk_points` exceeds 40.00 is not admissible to advance either out of build or out of validation without a remediation record, and the attempt is refused with `ERR_CUSTOMIZATION_LIMIT_EXCEEDED` (HTTP 422). Foundation-adopted items are not exposed to this ceiling because their classification weight caps the achievable score below it.

Build items are expected to survive at most three round trips through rejection. An item that has been rejected and returned to build can be reworked while its `rejection_count` is at most 3. Once the count exceeds 3 the item may no longer be reworked; instead it is reset entirely, returning to `DRAFT` with its `rejection_count` and its `test_cycles_passed` both returned to 0 so the item is re-scored from a clean slate.

### 2.13. The Training and Certification Floors

Three numeric floors govern whether a person may be trusted with the system on go-live day. A curriculum assignment is measured by the hours accrued through it; the cumulative `accumulated_training_hours` on a staff member is what certification readiness reads. A staff member is certification-ready when their accumulated hours reach the 40-hour floor and every non-waived assignment of theirs has reached `COMPLETED` — both conditions, not either.

An exam is passed at a `passing_score` of 80: a recorded `exam_score` of exactly 80 passes, and any score below 80 fails. A failed attempt sets the `next_attempt_eligible_utc` cooldown instant, and no retake may be recorded before the logical clock reaches it (`ERR_RETEST_COOLDOWN_ACTIVE`, HTTP 409).

Trainer certification has its own observation floor. A `CredentialedTrainer` may only be certified, or recertified after expiry, when the recorded `observation_hours` meets the minimum observation requirement of the requested `certification_level`; a shortfall is refused with `ERR_TRAINER_OBSERVATION_INSUFFICIENT` (HTTP 422). The `certification_level` is exactly one of `STANDARD` or `ADVANCED`. A successful certification or recertification stamps `certified_utc` with the logical clock and sets `expires_utc` to that instant plus 365 days (`CERTIFICATION_VALIDITY_DAYS`), after which the row moves to `EXPIRED` without any client request.

### 2.14. Conserved Quantities

Two counters in this system are conservation ledgers rather than running totals, and they are expected to return to a prior value after a matched pair of actions.

The program's `order_reconciliation_balance` counts converted EHR orders reconciled minus paper order slips backfilled. Reconciling an order credits the balance by one; backfilling a paper slip against an order debits it by one. A reconcile paired with a matching paper backfill must therefore leave the balance exactly where it started — the compensating slip gives back precisely the unit the reconciliation took. The program-level target for reconciled orders is 350, a benchmark rather than a hard gate.

The program's `net_trainer_count` counts credentialed-trainer rows currently in `CERTIFIED` status. It follows the same shape: certifying a trainer raises it and revoking that trainer lowers it by the same unit, so a certify/revoke pair restores the pre-pair value.

## 3. Business Logic & Workflows

### 3.1. Program Lifecycle and Readiness Posture

An `ImplementationDirector` opens a program by naming it. The creation payload carries the `program_name`, the `vendor_release` under implementation (for example `2026.2`), and the contracted `go_live_target_utc`. A newly created program is in `PLANNING` status, its `current_epoch_index` is 0, and its `readiness_posture` is `OPEN`. The program's status advances through exactly these values: `PLANNING`, `BUILD_IN_PROGRESS`, `VALIDATION_IN_PROGRESS`, `CUTOVER_READY`, `GO_LIVE_ACTIVE`, `COMMAND_CENTER_ACTIVE`, `STABILIZED`, `POST_LIVE_OPTIMIZATION`, and the terminal `ARCHIVED`.

Moving from planning into build requires that the program is in `PLANNING`, that its posture is not `ROLLBACK_REQUIRED`, and that at least one of its facilities has reached `SITE_REGISTERED` or `BUILD_CONFIGURED` — there must be something to build before build formally begins. Moving from build into validation is stricter about the build estate: every non-archived system build item belonging to the program must be in `BUILD_COMPLETE`, `IN_TESTING` or `VALIDATION_COMPLETE` — none may remain in `DRAFT`, `IN_BUILD` or `BUILD_REJECTED`. The move out of validation into cutover readiness requires the posture to be exactly `OPEN` and the `readiness_score` to have reached the cutover threshold of 85.00. Executing go-live requires the program to be in `CUTOVER_READY`, the posture again to be exactly `OPEN`, and the facility's `GO_NO_GO_DECISION` cutover task to be `COMPLETE`; its cascade is described in §3.9. Activating the command center requires `GO_LIVE_ACTIVE`, a posture of `OPEN`, and at least one staffing shift of the program in `SCHEDULED` status whose `start_utc` is at or before the logical clock; activation stamps `command_center_activated_utc` with the clock and moves every facility of the program that is `LIVE` or `STABILIZATION_AT_RISK` into `STABILIZED`.

Two of the later moves are system-driven rather than requested. The program settles into `STABILIZED` once no facility of the program remains in any pending state — that is, once none is `SITE_REGISTERED`, `BUILD_CONFIGURED`, `VALIDATED`, `CUTOVER_READY` or `LIVE`, leaving every facility either `STABILIZED` or `STABILIZATION_AT_RISK`. Opening post-live optimization requires every facility of the program to have reached a `revenue_cycle_stabilization_index` of at least 80.00 (see §3.8). Archival has no precondition beyond the program being in `POST_LIVE_OPTIMIZATION`; `ARCHIVED` is a terminal state from which nothing further follows.

The `readiness_score` driving the validation gate is a weighted deduction from a perfect 100. The scoring set is the program's open defects only — those in `OPEN`, `IN_REMEDIATION` or `REOPENED` status. Defects that have reached `RESOLVED` or `DEFERRED` are excluded from the calculation entirely. Open defects are grouped by the department that owns the build item they were raised against, and each department contributes a single penalty equal to the *largest* severity penalty among its open defects, not the sum of them: a department holding three `SEV2` defects contributes 25 points, exactly as a department holding one does. The severity penalties are 40 points for `SEV1`, 25 for `SEV2`, 10 for `SEV3` and 3 for `SEV4`, and a department with no open defect contributes 0.

Interface trouble enters the same score through a replacement rule rather than an addition. When any interface channel of the program has amassed at least 25 rejected messages, a flat 15-point interchannel penalty applies and the per-department penalties described above are dropped from the calculation entirely — the score becomes 100 minus 15, and no other term participates. When no channel has reached 25 rejections the interchannel penalty is 0 and the per-department penalties apply instead. The result is clamped into the range 0.00 to 100.00 inclusive and published to two decimal places.

The posture itself is then read off the score: a score of at least 60.00 is `OPEN`; a score of at least 40.00 but below 60.00 is `RESTRICTED`; a score below 40.00 is `ROLLBACK_REQUIRED`. Note the asymmetry in what each posture does — `OPEN` and `RESTRICTED` are both non-blocking for the operations listed in §2.5, while `ROLLBACK_REQUIRED` blocks all of them and leaves only remediation open.

A program also publishes an `optimistic_readiness_score`, a second figure computed over identical inputs with a single substitution: a defect whose owning build item is sitting in `BUILD_REJECTED` mid-remediation contributes the smaller of its severity penalty and 5 points rather than its full severity penalty, while a defect whose build item is in any other status contributes the full penalty as usual. This variant therefore returns a strictly higher figure than the base score whenever any build item of the program is in `BUILD_REJECTED`. It is surfaced when a caller reads a single program with the `posture_view` query parameter set to `OPTIMISTIC`; the field is present on the program resource in every case, and the base `readiness_score` remains the value the cutover gate consults.

### 3.2. Facility Rollout, Data Conversion and Cutover Readiness

A facility joins the program through an `ImplementationDirector` who supplies its `name`, its `facility_type`, its `bed_count`, its `rollout_wave` and its `conversion_scope`. The `facility_type` is exactly one of `ACUTE_CARE`, `CRITICAL_ACCESS`, `AMBULATORY` or `SPECIALTY`; an ambulatory site carries a `bed_count` of 0. The `rollout_wave` is a 1-based sequencing number, and the `conversion_scope` is exactly one of `FULL_RECORD`, `DEMOGRAPHICS_ONLY` or `SCHEDULING_ONLY`. A new facility starts in `SITE_REGISTERED` with `is_live` false. The facility status vocabulary is `SITE_REGISTERED`, `BUILD_CONFIGURED`, `REMEDIATION_REQUIRED`, `VALIDATED`, `CUTOVER_READY`, `LIVE`, `STABILIZED` and `STABILIZATION_AT_RISK`.

Configuring the build moves a registered facility to `BUILD_CONFIGURED` and requires only that the program's posture is `OPEN`. Marks of validation are deliberately demanding: a facility may be marked validated only when every one of its departments has an open proficiency gate (`proficiency_gate_open` true), when every one of its departments has a `build_blocking_defect_count` of 0, and when the program's posture is `OPEN`. Cutover readiness is granted at the close of the dress rehearsal and requires that every cutover task of the facility other than the `GO_NO_GO_DECISION` task is in `COMPLETE` or `SKIPPED`, and that at least one test scenario of class `CHARGE_CAPTURE_TO_CLAIM` belonging to the facility has reached `PASSED`. The facility then waits: it moves to `LIVE`, with `is_live` set true, only when the program itself enters `GO_LIVE_ACTIVE` (§3.9). When it does, the cascade runs three levels deep in a single action. Executing go-live moves the program to `GO_LIVE_ACTIVE`; that in turn moves every facility of the program that is `CUTOVER_READY` to `LIVE` with `is_live` true; and that facility change in turn moves each of its departments that is `READY_FOR_GO_LIVE` to the terminal `LIVE`. The departmental move fires because the *facility* entered `LIVE`, not because of the original go-live request — the program's transition reaches the departments only through the facility. Activating the command center completes the picture, moving every facility of the program that is `LIVE` or `STABILIZATION_AT_RISK` into `STABILIZED`.

A facility can fall backwards as well as forwards, which is why its status vocabulary is not a simple line. If a department of a facility with `BUILD_CONFIGURED` status slides into `BUILD_REJECTED`, the facility follows it into `REMEDIATION_REQUIRED` without any client request; it returns to `BUILD_CONFIGURED` once no department of it remains `BUILD_REJECTED`. Once live, a denial on any of its orders pulls the facility from `LIVE` to `STABILIZATION_AT_RISK` (§3.8), and it recovers to `LIVE` as soon as no order of the facility remains in `CLAIM_DENIED`.

Data conversion runs in batches, one per `payload_class` — `PATIENT_DEMOGRAPHICS`, `APPOINTMENTS`, `ORDERS` or `BALANCES` — under a `ConversionAnalyst` who supplies the `attempt_epoch`, the `source_count` read from the legacy system and the `reconciled_count` confirmed in the target, alongside the facility version guard described in §2.7. A batch begins in `STAGED` and moves through `VALIDATING`, `LOADED` and `RECONCILED`, with `FAILED` and `ROLLED_BACK` as its other terminal outcomes. Beginning validation requires the batch's `attempt_epoch` to equal the program's `current_epoch_index` (`ERR_EPOCH_MISMATCH` if it does not) and computes `variance_count` as the absolute difference between `source_count` and `reconciled_count`.

The variance measure itself is `variance_penalty_points`, the absolute count difference expressed as a percentage of the source count, rounded half-up to two decimal places. A batch that read nothing computes a penalty of 100.00; a batch with no variance at all computes 0.00. Each payload class carries its own ceiling: 1.00 for `PATIENT_DEMOGRAPHICS`, 1.50 for `APPOINTMENTS`, 2.00 for `ORDERS` and 0.50 for `BALANCES`. The load gate compares the batch's penalty against its ceiling with a strict *greater than*, so a batch sitting exactly on its ceiling loads successfully. A batch whose penalty exceeds its ceiling is refused with `ERR_BALANCE_VARIANCE_EXCEEDED` (HTTP 422), and if it is instead allowed to fail on its own the batch moves to `FAILED`. Loading a batch credits the facility: a `PATIENT_DEMOGRAPHICS` load adds its `reconciled_count` to `converted_patient_count`, and a `BALANCES` load records its `reconciled_count` as `applied_balance_cents`, applying that many cents to the `balance_cents` carried by the affected patient orders. Reconciling requires `reconciled_count` to equal `source_count` exactly, and refreshes the facility's `conversion_variance_index` to the largest `variance_penalty_points` observed among its reconciled batches. Rolling back may be done from `LOADED` or from `RECONCILED`; it subtracts `reconciled_count` from `converted_patient_count` — so a load followed by a rollback leaves the count where it began — and, for a `BALANCES` batch, reverses the applied balance on the affected patient orders by `applied_balance_cents`. Attempting to roll back a batch that has already reached `FAILED` or `ROLLED_BACK` is refused as `ERR_ALREADY_TERMINAL`. Two guards sit outside the workflow entirely: an `attempt_epoch` the client may not choose freely, and a `source_count` or `reconciled_count` that is negative or non-integer, refused with `ERR_BATCH_SIZE_INVALID` (HTTP 400) before the priority ladder runs.

Reports read four facility-level measures: `converted_patient_count`, the conserved count of active patients loaded and not rolled back; `conversion_variance_index`; `revenue_cycle_stabilization_index`; and `is_live`. Read-only analytics roles see every facility of a program, and facilities can also be listed across programs, filtered by program or by wave.

### 3.3. Department Structure, Build Items and Customization Risk

A `BuildAnalyst` creates a department under a facility, supplying its `department_code` — unique within that facility — its `application_scope`, a list of the application codes the department staffs, and its `required_staff_count`, which becomes the denominator of the proficiency gate in §3.4. A new department begins in `BUILD_PENDING`, and its status vocabulary runs `BUILD_PENDING`, `BUILD_COMPLETE`, `TRAINING_IN_PROGRESS`, `READY_FOR_GO_LIVE`, `REMEDIATION_REQUIRED` and `LIVE`. Closing the department's build requires that at least one of its build items has reached `BUILD_COMPLETE`, `IN_TESTING` or `VALIDATION_COMPLETE`; the department then moves to `BUILD_COMPLETE`.

The build item is where the department does its actual configuration work. Creating one records the `application_code` it configures, its `build_classification`, its `customization_depth` and the `local_custom_fields` it touches; the item starts in `DRAFT` with `test_cycles_passed` at 0. The item's status vocabulary is `DRAFT`, `IN_BUILD`, `BUILD_COMPLETE`, `IN_TESTING`, `VALIDATION_COMPLETE` and the rejection state `BUILD_REJECTED`. Beginning build work requires the program's posture to be `OPEN` and moves the item to `IN_BUILD`. Completing the build is where the customization is scored, and the item moves to `BUILD_COMPLETE` carrying its freshly computed `customization_risk_points`. Moving into testing requires only `BUILD_COMPLETE`; closing validation requires that at least one test scenario has passed in the current epoch (`test_cycles_passed` of at least 1) and that `open_defect_count` has returned to 0, at which point the item reaches the terminal `VALIDATION_COMPLETE`.

Rejection is what makes the build item a cyclic resource. Any test scenario of the item that transitions into `FAILED` pushes the item from `IN_TESTING` into `BUILD_REJECTED`, and each such rejection increments `rejection_count` by one and forces a recomputation of the owning department's `build_blocking_defect_count`. From `BUILD_REJECTED` the item may be reworked back to `IN_BUILD` — permitted while `rejection_count` is at most 3 — or, once `rejection_count` exceeds 3, reset entirely back to `DRAFT`, which also returns `rejection_count` and `test_cycles_passed` to 0.

The customization score is computed once, on completion of the build, and is deliberately tiered, weighted and multiplied before any rounding happens. The starting quantity is the number of *distinct* field names in `local_custom_fields` — a list naming the same field twice counts once. That count is then capped at 12 billable units; units beyond the twelfth are not counted at all. The billable units are priced in marginal tiers: each of the first 4 units is worth 2 points, each of units 5 through 8 is worth 3 points, and each of units 9 through 12 is worth 5 points. For example, 3 units earn 6 points, 8 units earn 20 points (4 at 2 plus 4 at 3), and 12 units earn 40 points (4 at 2, 4 at 3, 4 at 5).

That tier total is then multiplied by a classification weight taken from the build classification: 1.0 for `FOUNDATION_ADOPTED`, 1.5 for `FOUNDATION_ADAPTED` and 2.0 for `LOCAL_CUSTOM`. The weighted result is then multiplied by a depth multiplier of 1 plus 0.15 for each unit of `customization_depth` beyond the first — so a depth of 1, and equally a depth of 0, contributes no multiplier at all and the depth factor is simply 1, while a depth of 3 applies 1.30. The product is rounded half-up to two decimal places exactly once, at the very end; no intermediate tier, weight or multiplier is rounded on its way through. This single final rounding is what makes the score reproducible: a batch re-scoring pass that summed several unrounded item totals and rounded the batch once could differ from the per-item scores by up to 0.01 multiplied by one less than the number of items.

A build item's reported `open_defect_count` covers the defects raised against its own scenarios and, where scenarios nest, those of its child scenarios; a defect counts toward it until it reaches `RESOLVED` or `DEFERRED`. The owning department's `build_blocking_defect_count` is narrower — only open `SEV1` and `SEV2` defects belonging to the department's build items are counted, because those are the ones that block go-live. Testing is measured through `test_cycles_passed`, the count of scenarios in the item's current epoch that have reached `PASSED`; scenarios still sitting in `DEFINED` are excluded from the measurement entirely, being neither a pass nor a run. The minimum cycle requirement depends on the scenario class and is a floor rather than an exact target: 3 passing cycles for `UNIT`, 2 for `INTEGRATED` and 1 for `CHARGE_CAPTURE_TO_CLAIM`.

### 3.4. Role-Based Training, Proficiency Gating and Trainer Credentialing

A `TrainingCoordinator` registers each person who will use the system, supplying their `full_name`, their `staff_type`, their `primary_facility_id`, the `department_id` whose proficiency gate they will feed, an optional `preceptor_staff_id`, and their `hired_on` date. The `staff_type` is exactly one of `PROVIDER`, `NURSE`, `ALLIED_HEALTH`, `REGISTRATION`, `BILLING` or `ANALYST`. The `preceptor_staff_id` is a self-referential mentorship link to another staff member's `id`; it is left empty for a chain root, so mentorship chains are traversable by repeated lookup. A newly registered person starts in `REGISTERED` status with `accumulated_training_hours` at 0. The staff status vocabulary is `REGISTERED`, `TRAINING_ASSIGNED`, `TRAINED`, `PROFICIENCY_VERIFIED`, `CREDENTIALED` and `PROFICIENCY_FAILED`; the last two, together with the failure state, are where a person's journey ends.

Opening a department's training pushes every person of that department in `REGISTERED` or `TRAINING_ASSIGNED` status into `TRAINING_ASSIGNED` in a single sweep, and the department itself moves to `TRAINING_IN_PROGRESS`; the operation requires the program's posture to be `OPEN`. A curriculum is then attached to a person by supplying the `curriculum_code` (for example `CLN100`), the `application_code` it covers, the `required_hours` it demands and its `due_utc`. The assignment starts in `ASSIGNED`, and the person moves to `TRAINING_ASSIGNED` as a consequence. An assignment's status vocabulary is `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, `OVERDUE` and `WAIVED`.

Hours are logged against an assignment rather than set: a logging call supplies an `hours` quantity that must be strictly greater than zero, and that quantity is added to `completed_hours`. The same call recomputes `completion_pct` as 100 multiplied by `completed_hours` divided by `required_hours`, capped at 100, and moves the assignment to `IN_PROGRESS`. Logging is admissible from either `ASSIGNED` or `IN_PROGRESS`, so an assignment may be topped up over several calls. Completing an assignment requires that `completed_hours` have reached `required_hours` — a shortfall is refused with `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422) — and completes the assignment, which in turn recomputes the staff member's `accumulated_training_hours`. An assignment that is still `ASSIGNED` or `IN_PROGRESS` when the logical clock passes its `due_utc` moves to `OVERDUE` without any client request.

Waiving is the escape hatch and it is bounded. A waiver may be applied from `ASSIGNED`, `IN_PROGRESS` or `OVERDUE`, and requires a non-empty `waiver_reason` together with a floor on the person's accrued hours that is a function of that reason: the staff member's `accumulated_training_hours` must be at least the minimum the supplied reason demands. A successful waiver moves the assignment to `WAIVED` and recomputes the staff member's `accumulated_training_hours` with that row excluded from the sum. Attempting to waive an assignment that is already `COMPLETED` or `WAIVED` is refused as `ERR_ALREADY_TERMINAL`.

The `accumulated_training_hours` figure is deliberately narrower than the total of all hours ever logged. It sums `completed_hours` over the person's assignments that are in `IN_PROGRESS` or `COMPLETED` status, and it excludes rows in `ASSIGNED`, `OVERDUE` or `WAIVED` status entirely. This is why a training dashboard's "hours remaining" projection can disagree with the certification figure: the projection divides by a count of non-waived assignments that includes `OVERDUE` rows, while the accumulated total leaves `OVERDUE` rows out of the sum, and the two agree only when nothing is overdue.

A person becomes `TRAINED` without any client request once every one of their non-waived assignments has reached `COMPLETED`; the transition refreshes their `accumulated_training_hours`. Certification readiness is a separate, stricter reading of the same data: a person is certification-ready when their accumulated hours have reached 40 and every non-waived assignment of theirs is `COMPLETED`. Both conditions must hold.

Proficiency is assessed by exam. A `TrainingCoordinator` schedules an exam by naming the `application_code` under assessment and the `proctored_by_trainer_id` of the trainer acting as proctor of record. The exam starts in `SCHEDULED` status with an `attempt_number` one greater than the count of previous attempts for that person and application pair. Its status vocabulary is `SCHEDULED`, `COMPLETED_PASS`, `COMPLETED_FAIL` and `NO_SHOW`, and `passing_score` is fixed at 80. Recording a result is the exclusive province of a `CredentialedTrainer` and supplies the `exam_score`. A score of at least 80 moves the exam to `COMPLETED_PASS`, which in turn lifts the person from `TRAINED` to `PROFICIENCY_VERIFIED` and refreshes the department's `proficiency_cleared_ratio`. A score below 80 moves the exam to `COMPLETED_FAIL`, sets `next_attempt_eligible_utc` to the logical clock plus the retest cooldown, and likewise refreshes the department ratio. A result may only be recorded while the exam is `SCHEDULED` and while the retest cooldown has elapsed — an attempt before `next_attempt_eligible_utc` is refused with `ERR_RETEST_COOLDOWN_ACTIVE`. A no-show may be marked while the exam is `SCHEDULED`, only once the clock has passed `next_attempt_eligible_utc` or that instant is null, and only while the person is `TRAINED` or `PROFICIENCY_VERIFIED`; it moves the exam to `NO_SHOW` and sets the same cooldown instant.

Trainer credentialing runs in parallel. A `TrainingCoordinator` starts a trainer record against a staff member by supplying the `application_code` the person will teach, their `certification_level`, the `observation_hours` they have accumulated under proctoring, and the staff version guard described in §2.7, which also increments the staff member's `version` by one. The record begins in `PENDING_OBSERVATION`. Its status vocabulary is `PENDING_OBSERVATION`, `CERTIFIED`, `EXPIRED` and `REVOKED`. Certifying requires the observation floor of §2.13 and stamps `certified_utc` with the logical clock and `expires_utc` with the clock plus 365 days. Once the clock reaches `expires_utc` the record becomes `EXPIRED` without any client request, and an expired record may be recertified under the same observation floor, which resets both instants afresh. Revoking may be done from `CERTIFIED` and moves the record to the terminal `REVOKED`, refreshing the program's `net_trainer_count`.

A person holding `PROFICIENCY_VERIFIED` status may be issued their go-live credential, which moves them to `CREDENTIALED`. The issuance carries a precondition that is one of the few places the API distinguishes staff types: the person must either hold at least one trainer record in `CERTIFIED` status, or have a `staff_type` of `REGISTRATION`. A person whose exam fails outright does not simply retry from scratch — the failure moves them to `PROFICIENCY_FAILED`, which refreshes the department ratio, and returning them to training is a deliberate coordinator action that restores them to `TRAINING_ASSIGNED` and, as a side effect, returns every one of their `COMPLETED` assignments to `IN_PROGRESS` so the hours must be re-earned.

The department's proficiency measure is `proficiency_cleared_ratio`, the count of the department's staff whose status is `PROFICIENCY_VERIFIED` or `CREDENTIALED` — a figure the department also publishes as `proficiency_cleared_count` — expressed as a percentage of the department's `required_staff_count` and rounded half-up to two decimal places. Staff in `REGISTERED`, `TRAINING_ASSIGNED`, `TRAINED` or `PROFICIENCY_FAILED` contribute nothing to the numerator while still counting in the denominator, so an untrained population drags the ratio down. A department with a `required_staff_count` of 0 computes a ratio of 100.00 and its gate is open. The gate itself, `proficiency_gate_open`, is true when the ratio is at least 80.00 — the boundary value is inclusive. Closing the gate to declare a department ready for go-live requires the gate to be open and the department's `build_blocking_defect_count` to be 0; a closed gate on a department whose ratio is short is refused with `ERR_PROFICIENCY_GATE_CLOSED` (HTTP 422), and an open blocking defect is refused with `ERR_DEFECT_BLOCKS_DEPARTMENT`. A department whose ratio falls below the gate while it is `TRAINING_IN_PROGRESS` slides into `REMEDIATION_REQUIRED` on its own; a department that is ready and whose facility goes live reaches the terminal `LIVE`.

### 3.5. Test Cycles, Defect Remediation and the Blocking Chain

Testing is organized as scenarios attached to a build item. A `TestLead` defines one by naming its `scenario_class` — exactly one of `UNIT`, `INTEGRATED` or `CHARGE_CAPTURE_TO_CLAIM` — and its `step_count`, the number of steps in the script. The scenario starts in `DEFINED`, and its status vocabulary is `DEFINED`, `PASSED` and `FAILED`, the latter two being terminal.

Execution is where the epoch discipline bites. An execution supplies an `outcome` of `PASS` or `FAIL` together with an `executed_epoch`, and the scenario may only be executed while it is `DEFINED` and while the supplied `executed_epoch` equals the program's `current_epoch_index` — a stale epoch is refused. A passing outcome moves the scenario to `PASSED`, records the epoch and refreshes the build item's `test_cycles_passed`; a failing outcome moves the scenario to `FAILED`, records the epoch, and pushes the owning build item from `IN_TESTING` into `BUILD_REJECTED` on the spot. A failed scenario may be returned to `DEFINED` for re-execution, which is how a re-test after remediation begins.

A defect is raised against a failing scenario by supplying a `defect_code` and a `severity` of `SEV1`, `SEV2`, `SEV3` or `SEV4`, and the raised row starts in `OPEN`; its `test_scenario_id` records the scenario that owns it, and the department's `build_blocking_defect_count` is refreshed at that moment. The defect's status vocabulary is `OPEN`, `IN_REMEDIATION`, `RESOLVED`, `DEFERRED` and `REOPENED`. A `BuildAnalyst` begins remediation, moving the defect from `OPEN` to `IN_REMEDIATION`; a `TestLead` may defer a defect only when its severity is `SEV3` or `SEV4`, and a deferral attempt on a `SEV1` or `SEV2` defect is refused with `ERR_DEFECT_SEVERITY_NOT_DEFERRABLE` (HTTP 422). Severity also drives the `blocks_go_live` flag, which is true precisely while the severity is `SEV1` or `SEV2` and the defect has not reached `RESOLVED`; resolution clears it to false, and reopening restores it to true.

The defects also age. `aging_hours` reports how long a defect has been open, measured in hours against the logical clock rather than wall-clock time, so moving the clock forward ages every open defect at once. Each defect tracks an `attempt_count` of reopen attempts against a ceiling of 3, and a `resolution_epoch` recording the epoch in which it reached `RESOLVED`.

Resolving a defect is the most consequential single action in the build estate, because it cascades through four links in strict order. The first link decrements the `open_defect_count` of the scenario that owns the defect by one. The second decrements the `open_defect_count` of the build item that owns that scenario by one. The third decrements the owning department's `build_blocking_defect_count` by one when the defect's severity is in `SEV1` or `SEV2`, and once that count reaches 0 the department moves from `BUILD_REJECTED` back to `BUILD_COMPLETE`. The fourth link reaches the facility: if the owning facility is sitting in `REMEDIATION_REQUIRED` and no department of it remains `BUILD_REJECTED`, the facility returns to `BUILD_CONFIGURED`. Resolution also stamps `resolution_epoch` with the current epoch and clears `blocks_go_live`.

Reopening a defect pulls the whole chain back up. A defect may be reopened only from `RESOLVED`, only while its `resolution_epoch` is still the current epoch, and only while its `attempt_count` is below 3; the reopen moves it to `REOPENED`, restores `blocks_go_live` to true, and registers the attempt. A reopened defect is remediated along the same path as an open one.

A defect whose build chain has walked all the way back carries no special exemption: an open `SEV1` or `SEV2` defect anywhere in the program refuses the go-live decision and refuses a facility's stabilization with `ERR_GO_LIVE_BLOCKED` (HTTP 422), and an open `SEV1` or `SEV2` defect belonging to a department refuses that department's gate closure and its facility's mark of validation with `ERR_DEFECT_BLOCKS_DEPARTMENT`. The separation-of-duties rule of §2.10 means the actor who approved a go/no-go decision may not also resolve the defect linked to that decision, and the resolution attempt is then refused with `ERR_SOD_VIOLATION`.

### 3.6. Interface Build, Message Validation and Cutover Readiness

Laboratory, imaging, pharmacy and device connectivity is modelled as channels, each an `InterfaceEngineer`'s build to a third-party system. Defining a channel records its `channel_type` — exactly one of `LAB`, `IMAGING`, `PHARMACY` or `DEVICE` — the `external_system` it connects to, its `message_format` (exactly one of `HL7_V2`, `FHIR`, `DICOM` or `CSV`), its contractual `throughput_per_hour` and its contractual `max_latency_minutes`. A new channel begins in `DEFINED` with `validated_message_count` and `rejected_message_count` both at 0. Its status vocabulary is `DEFINED`, `BUILDING`, `IN_MESSAGE_VALIDATION`, `VALIDATED` and `VALIDATION_FAILED`.

The channel build proceeds through opening build work (`BUILDING`), opening message validation (`IN_MESSAGE_VALIDATION`), and closing validation — the last of which requires the channel's `interface_message_validation_pass_rate` to have reached at least 95.00 and moves the channel to the terminal `VALIDATED`. The pass rate is computed per epoch: it divides `validated_message_count` by the sum of `validated_message_count` and `rejected_message_count`, expressed as a percentage and rounded half-up to two decimals, and it counts only messages decided in the current epoch. When no message has yet been decided the rate is 0.00 rather than undefined — an empty measurement is not a pass. A channel that has fallen to `VALIDATION_FAILED` may be returned to `BUILDING`, which zeroes both counters so validation restarts cleanly.

Messages are received against a channel and are observations rather than mutations. A received message records its `message_code`, its `direction` of `INBOUND` or `OUTBOUND`, and the `sent_utc` of the sending system; the server stamps `received_utc` with the logical clock and computes `latency_minutes` as the interval between send and receipt expressed in minutes and rounded to two decimals. A message begins with `validation_status` of `RECEIVED`, and its vocabulary is `RECEIVED`, `VALIDATED` and `REJECTED`.

Validation is a two-condition gate, and both conditions are checks the system performs rather than judgement calls. The message's `message_code` — one of `ADT_A01`, `ORM_O01`, `ORU_R01`, `RDE_O11` or `DICOM_STOW` — must be a member of the valid code set for the owning `channel_type`; a code that does not belong to that channel's vocabulary is refused with `ERR_INTERFACE_MESSAGE_INVALID` (HTTP 422). And the message's `latency_minutes` must not exceed the owning channel's `max_latency_minutes`; a message that arrived too slowly is refused with `ERR_INTERFACE_LATENCY_EXCEEDED` (HTTP 422). A message that satisfies both conditions may be validated, which sets `validation_status` to `VALIDATED` and refreshes the channel's `validated_message_count`.

A message that fails either condition is rejected without surviving into a validated state. Rejection sets `validation_status` to `REJECTED`, refreshes the channel's `rejected_message_count`, and populates `validation_error_code` — a field that is empty on every non-rejected message — with either `ERR_INTERFACE_MESSAGE_INVALID` or `ERR_INTERFACE_LATENCY_EXCEEDED` according to which condition failed. Rejection also cascades one level: if the owning channel is currently `IN_MESSAGE_VALIDATION`, the channel itself falls to `VALIDATION_FAILED`, which is the second link of the message-rejection cascade that begins with the message.

Cutover readiness is what all of this feeds into. No facility may be granted cutover readiness, no program may finalize its validation phase, and no cutover step may complete while any interface channel of the program remains short of `VALIDATED`; the refusal carries `ERR_CHANNEL_NOT_VALIDATED` (HTTP 422). This is the mechanism by which a single unproven laboratory feed holds an entire enterprise release at the gate, which is exactly the intent.

### 3.7. Patient Orders: Conversion, Charge Capture and Paper Backfill

Converting a legacy order creates a patient order carrying the `patient_mrn` of the converted active patient, its `order_type` (exactly one of `MEDICATION`, `LAB`, `IMAGING` or `PROCEDURE`), its legacy `encounter_utc` and the `legacy_charge_cents` the old system captured. The order starts in clinical state `CONVERTED` and billing state `UNPOSTED`, and at creation the system computes and publishes a provisional charge. A patient order carries two independent state dimensions that advance on the same row: its clinical state, whose vocabulary is `CONVERTED`, `RECONCILED` and `PAPER_BACKFILL_REQUIRED`, and its billing state, whose vocabulary is `UNPOSTED`, `CHARGE_POSTED`, `CLAIM_SUBMITTED`, `CLAIM_ACCEPTED`, `CLAIM_DENIED` and `CLAIM_PAID`.

Charge capture is computed from the legacy charge by expanding the order into priced line items according to its type. Every order carries a base line equal to the full `legacy_charge_cents`. On top of the base, a lab order carries one processing line of 5.0 percent of the legacy charge; an imaging order carries a technology line of 12.5 percent and a contrast line of 7.5 percent; a medication order carries a dispensing line of 3.0 percent; and a procedure order carries an operating-room line of 20.0 percent and an anesthesia line of 5.0 percent. Each line is rounded half-up to two decimal places *first*, and the rounded lines are then summed; that order is pinned and must not be inverted. The sum is published as the provisional charge to two decimals.

The final, reconciled charge adds one further element that the provisional charge omits. For a procedure order only, a charge-capture gap line is added, computed as 3.0 percent of the unrounded sum of all the order's line items, rounded once to two decimal places, and this gap line is a final-variant-only construct. The final charge is the provisional charge plus that gap, rounded half-up to two decimals, and the order's `charge_variance_cents` reports the final charge minus the provisional charge. Non-procedure orders have no gap line and their final charge equals their provisional charge. The frozen final figure is published at reconciliation, and it is recomputed and republished when the order's charge is posted.

Reconciling the clinical order requires that the order is in clinical state `CONVERTED`. There are two ways through. The straightforward path applies when `paper_backfill_count` is 0: reconciliation moves the order to `RECONCILED`, publishes the final charge, credits the program's `order_reconciliation_balance` by one. The second path applies when the order already carries at least one paper backfill; it likewise moves the order to `RECONCILED` and credits the reconciliation balance by one, and it exists because an order can be backfilled before it is reconciled. Reconciling a `PROCEDURE` order is a credentialed act: an actor without the charge-capture credential is refused with `ERR_PROCEDURE_CREDENTIAL_MISSING` (HTTP 422).

Paper backfill is the compensating action for the downtime window. When a facility goes live while an order is still `UNPOSTED` and that order was placed during the downtime window, the order's clinical state moves to `PAPER_BACKFILL_REQUIRED` on its own. Backfilling the paper slip — an `OrderReconciler` action — moves the order to `RECONCILED`, increments `paper_backfill_count` by one, and debits the program's `order_reconciliation_balance` by one. That debit is exactly what makes reconciliation a conserved quantity: reconcile a converted order and the balance rises by one, backfill its matching paper slip and the balance falls by one, so a matched pair leaves the balance where it began. A downtime reconciliation report that counted paper slips as reconciled orders would disagree with this ledger, and the two agree only when nothing has been backfilled.

Charge posting is a deliberate step rather than an automatic consequence of reconciliation. An `RevenueCycleAnalyst` posts the charge, moving the order from `UNPOSTED` to `CHARGE_POSTED` and recomputing the final charge at that moment; posting is admissible while the order's clinical state is `CONVERTED` or `RECONCILED`, and an order that has been reconciled should have its charge posted to begin the billing journey.

### 3.8. Revenue Cycle Stabilization and the Denial Revert

Billing advances along its own axis, gated at each step by the clinical dimension. A charge may be submitted as a claim once the order is in billing state `CHARGE_POSTED` and its clinical state is `RECONCILED`; this is the point at which the clinical and billing dimensions must converge, and submitting a claim on an order that has not been clinically reconciled is refused with `ERR_ORDER_NOT_RECONCILED` (HTTP 422). Submission moves the order to `CLAIM_SUBMITTED` and refreshes the owning facility's `revenue_cycle_stabilization_index`. Likewise the payer's response may only be recorded while the order is `CLAIM_SUBMITTED`, and an attempt before reconciliation is refused with the same `ERR_ORDER_NOT_RECONCILED`.

The response is a `claim_response` value drawn from `ACCEPTED`, `DENIED` or `PAID`, and it must be compatible with the order's current billing state; an incompatible pairing is refused with `ERR_CLAIM_RESPONSE_INVALID` (HTTP 422). An acceptance moves a submitted claim to `CLAIM_ACCEPTED`, a denial moves it to `CLAIM_DENIED`, and a payment moves an accepted claim to `CLAIM_PAID`, which is terminal. A denied claim is not a dead end: it may be reopened for correction, which returns the order to `CHARGE_POSTED` so the charge can be corrected and resubmitted.

Denial has a consequence that reaches well beyond the order. When any order of a live facility enters `CLAIM_DENIED`, the facility itself is pulled from `LIVE` back to `STABILIZATION_AT_RISK` with no client request, and the facility's stabilization index is recomputed. The facility returns to `LIVE` on its own as soon as no order of it remains in `CLAIM_DENIED`. This is the intended meaning of the at-risk state — a facility that has gone live can be sent backwards by its own revenue cycle, and it recovers by correcting the claim rather than by asking to recover.

The `revenue_cycle_stabilization_index` is a weighted blend of two factors, computed over the facility's orders whose clinical state is `CONVERTED` or `RECONCILED`. The first factor rewards currency of the receivable: it is 100 when the order's encounter is no more than 7 days behind the logical clock, 80 when it is 8 to 14 days behind, 50 when it is 15 to 30 days behind, and drops to 20 once it is more than 30 days behind. The second factor is a blunt denial penalty: it is 0 if any order of the facility is in `CLAIM_DENIED` and 100 otherwise. The index weights the receivables factor at 0.60 and the denial factor at 0.40, rounds half-up to two decimal places, and is recomputed on every change to any order's billing state. A facility holding a single denied claim therefore cannot exceed 60.00 however fresh its other receivables are, which is why 80.00 — the floor for both facility stabilization and the program's move into post-live optimization — is only reachable once denials have been cleared.

### 3.9. Cutover Planning, Downtime and the Go/No-Go Decision

The cutover plan is a facility's ordered sequence of steps, and its ordering is enforced rather than advisory. A `CutoverLead` adds a step by naming its `task_class` — exactly one of `DOWNTIME_PREP`, `ORDER_RECONCILIATION`, `PAPER_BACKFILL`, `DRESS_REHEARSAL` or `GO_NO_GO_DECISION` — its `sequence_index` within the plan, and its planned window as a `planned_start_utc` that is inclusive and a `planned_end_utc` that is exclusive. The server derives `duration_minutes` as the interval between those two instants expressed in minutes. A new step begins in `PLANNED`, and the status vocabulary is `PLANNED`, `IN_PROGRESS`, `COMPLETE`, `SKIPPED` and `BLOCKED`.

Two temporal constraints govern the plan's shape. A new step's window must leave the standard handoff buffer of 30 minutes clear after the preceding step and must not overlap the step that follows it; a window that violates either rule is refused with `ERR_TEMPORAL_OVERLAP` (HTTP 409). And starting a step requires that the step immediately before it in `sequence_index` order has already reached `COMPLETE` or `SKIPPED`; a start attempted while any earlier-sequence step is still `PLANNED`, `IN_PROGRESS` or `BLOCKED` is refused with `ERR_PRECEDING_STEP_INCOMPLETE` (HTTP 409). Those two rules together mean a cutover plan proceeds in order and cannot be parallelized by accident.

Skipping is restricted to the steps that can be forgone: a step may be skipped only while it is `PLANNED` and only when its `task_class` is `DOWNTIME_PREP` or `DRESS_REHEARSAL`. Any other class — notably the reconciliation and backfill work and the go/no-go decision itself — must actually be carried out. A step that has begun may be blocked, which requires a non-empty `block_reason`, and unblocked again; a blocked step is `BLOCKED`, `COMPLETE` and `SKIPPED` are terminal.

The `GO_NO_GO_DECISION` step is the plan's pivot. Everything else in the plan must be `COMPLETE` or `SKIPPED` before the dress rehearsal may be closed, but the decision step itself is what the enterprise go-live waits on: executing go-live requires that the facility's `GO_NO_GO_DECISION` task have reached `COMPLETE`. Completing it is also where the go-live date discipline applies, and the same discipline applies to the go-live execution itself — if the decision instant would fall later than the program's `go_live_target_utc` plus any approved extension, the operation is refused with `ERR_GO_LIVE_AFTER_TARGET` (HTTP 422).

### 3.10. Command Center Staffing and Issue Triage

Once the enterprise is live, support shifts from project work to at-the-elbow support, and the command center is the mechanism. A `CommandCenterLead` schedules a shift by naming the `staff_id` who will work it, the `facility_id` it covers, the `support_role` — exactly one of `AT_THE_ELBOW`, `TRIAGE_COMMANDER`, `APPLICATION_ANALYST` or `CHARGE_CAPTURE_SPECIALIST` — and its window as an inclusive `start_utc` and an exclusive `end_utc`. The server stamps `handoff_buffer_minutes` at 30. A shift begins in `SCHEDULED`, and its status vocabulary is `SCHEDULED`, `ACTIVE`, `COMPLETED`, `NO_SHOW` and `REASSIGNED`.

Two scheduling constraints protect the support roster. A shift may not overlap another shift of the same staff member, and two `AT_THE_ELBOW` shifts at the same facility may not overlap either; exact adjacency, where one shift ends precisely as the next begins, is permitted. A violation of either rule is refused with `ERR_SHIFT_OVERLAP` (HTTP 409). Separately, the staff member's `primary_facility_id` must equal the facility the shift covers, because the system will not post someone to a site that is not their home site; a mismatch is refused with `ERR_PRIMARY_FACILITY_MISMATCH` (HTTP 422). That same home-site rule applies to command-center tickets.

Activating a shift requires that the shift is `SCHEDULED`, that the logical clock has reached its `start_utc`, and that the assigned staff member holds `CREDENTIALED` status — an uncredentialed person cannot staff the command center. A shift that is still `SCHEDULED` a full handoff buffer after its start instant has passed moves to `NO_SHOW` on its own, and that no-show opens a coverage gap for the facility's at-the-elbow support. A shift that has not yet begun may be reassigned, which is permitted only while the clock is still before its `start_utc`; an active shift is completed rather than reassigned.

Tickets are how issues surface. A ticket is raised by a `CommandCenterLead` or a `TriageCommander` with a `facility_id`, an optional `department_id`, a `target_ref`, a `severity`, an `at_the_elbow_zone` and an optional `linked_test_defect_id`. The `target_ref` is a polymorphic reference that may point at a department, a facility, an interface channel or a patient order; a reference that does not resolve is refused as described in §2.8. The `linked_test_defect_id` ties a ticket back to the test defect that gave rise to it, when one did. The server stamps `reported_utc` with the logical clock and computes `resolution_sla_minutes`. A new ticket starts in `REPORTED` with a `triage_state` vocabulary of `REPORTED`, `TRIAGED`, `IN_RESOLUTION`, `RESOLVED` and `ESCALATED`.

The response target is computed from four inputs. A severity weight scales the base 60-minute target: 0.25 for `SEV1`, 0.50 for `SEV2`, 1.00 for `SEV3` and 2.00 for `SEV4`, so the most severe issues carry the tightest commitments. A zone modifier adjusts for where the issue was raised: 0.80 in the emergency department, 0.70 in the operating room, 0.75 in intensive care, 1.00 on the medical-surgical floors, 1.10 in radiology and 1.05 in pharmacy. A coverage modifier halves the target to 0.50 when there is no at-the-elbow cover available — that is, when the ticket's facility has no shift in `SCHEDULED` or `ACTIVE` status with `support_role` `AT_THE_ELBOW` whose `end_utc` is still ahead of the clock — and is otherwise 1.00. The four factors multiply the 60-minute base, and the product is published as `resolution_sla_minutes` rounded half-up to a whole number of minutes.

Triage is a `TriageCommander`'s work. Triaging a `REPORTED` ticket moves it to `TRIAGED`, and it carries a side effect worth noting: if the ticket carries a `linked_test_defect_id` that resolves to an existing defect and that defect currently has `blocks_go_live` true, the linked defect is pushed back into `REOPENED`. Beginning resolution moves a `TRIAGED` ticket to `IN_RESOLUTION`. A ticket may be escalated on its own while it is `TRIAGED` or `IN_RESOLUTION` once the logical clock passes `reported_utc` plus the escalation window, and a `SEV1` or `SEV2` ticket is the kind that escalates on its own rather than waiting for someone to ask. Resolution is reached either from `IN_RESOLUTION` or from `ESCALATED`, which makes `RESOLVED` the sole terminal state and lets a ticket that escalated still be closed.

Every ticket carries an `ehr_implementation_id` backlink, a `severity` that is one of `SEV1`, `SEV2`, `SEV3` or `SEV4`, its `at_the_elbow_zone`, its `resolution_sla_minutes`, its `triage_state`, and the `reported_utc` stamp. Tickets are listable across the program and filterable by facility, department, linked defect, severity and triage state, and this is the one collection that also takes `limit` and `offset` among its declared query parameters.

### 3.11. Post-Live Optimization Backlog

Once a program has stabilized, the improvements it could not make before go-live are collected rather than forgotten. An `OptimizationLead` raises a backlog item against a department by supplying a `title`, an `effort_points` estimate, and the program version guard described in §2.7, which also increments the program's `version` by one. The item is stamped with `requested_epoch` equal to the program's `current_epoch_index` at the moment it is raised, and it begins in `NEW`. Its status vocabulary is `NEW`, `TRIAGED`, `SCHEDULED`, `IN_PROGRESS`, `RELEASED` and `REJECTED`.

Triaging moves the item to `TRIAGED`, and from there it may either be scheduled or rejected. Scheduling is where the release train's capacity is allocated, and the allocation is a waterfall rather than a per-item decision. Each epoch offers a release capacity of 30 points. The capacity is filled in a strict priority order over the items awaiting scheduling: items in `TRIAGED` status are taken smallest-first by `effort_points`, ties are broken by `requested_epoch` ascending, and any remaining tie is broken by creation time ascending. The head of that queue is offered the capacity of the epoch named by the scheduling request's `target_epoch` — the 30-point budget less the `effort_points` already committed by items already `SCHEDULED` for that same epoch. An item whose effort fits within what remains is scheduled into the requested epoch; an item that overflows rather than fits is scheduled into the following epoch instead, so it lands at the next release rather than being refused. An item whose `effort_points` exceeds a whole epoch's capacity can never be scheduled at all, and the attempt is refused with `ERR_RELEASE_CAPACITY_EXCEEDED` (HTTP 409). Nothing in this allocation rounds: points are integers and unallocated capacity is simply carried forward as unfilled.

The consequence of smallest-first ordering is visible whenever a large request precedes a small one: the large item overflows to the next epoch while the small item, raised later, fits into the current one. A backlog view that ordered purely by request time would allocate in a different sequence and produce a different `scheduled_epoch` for at least one item. The allocator's ordering is the binding one, and the resulting epoch is published on the item as `scheduled_epoch`.

A scheduled item may proceed into `IN_PROGRESS`, and it may be released once the program's `current_epoch_index` has reached its `scheduled_epoch` — an item cannot ship ahead of the release it was allocated to. Release is terminal. An item that is not going to be done is rejected from `TRIAGED`, and rejection is the other terminal outcome.

## 4. Endpoint Definitions

Operations that bring a new, stand-alone resource into existence — creating an implementation program, registering a facility, defining a build item or a test scenario, receiving an interface message, raising a ticket or a backlog item — return `201 Created`. Operations that modify an existing resource, including those that add a distinct resource to an existing collection such as a staff member's training assignment or a facility's cutover step, return `200 OK`. Every path is mounted at the deployment root, so each resource type is addressed by its own top-level path segment. The authorized roles column below names the roles permitted to invoke the operation; a caller authenticated under any other role receives `ERR_UNAUTHORIZED`.

### 4.1. Implementation Programs

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ehr-implementations` | Create an implementation program | `ImplementationDirector` |
| GET | `/ehr-implementations` | List implementation programs | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `CutoverLead`, `CommandCenterLead` |
| GET | `/ehr-implementations/{id}` | Get one program with its readiness posture | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `CutoverLead`, `CommandCenterLead` |
| POST | `/ehr-implementations/{id}/advance-epoch` | Advance the ops-run epoch | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/start-build` | Begin the build phase | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/start-validation` | Begin the validation phase | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/finalize-validation` | Close validation and grant cutover readiness | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/execute-go-live` | Execute the enterprise go-live | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/activate-command-center` | Activate the go-live command center | `CommandCenterLead` |
| POST | `/ehr-implementations/{id}/begin-optimization` | Open the post-live optimization phase | `ImplementationDirector` |
| POST | `/ehr-implementations/{id}/archive` | Archive the program | `ImplementationDirector` |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability) | `ImplementationDirector` |

### 4.2. Facilities and Cutover

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ehr-implementations/{id}/facilities` | Register a facility in the rollout | `ImplementationDirector` |
| GET | `/ehr-implementations/{id}/facilities` | List a program's facilities | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `CutoverLead`, `CommandCenterLead` |
| GET | `/facilities` | List facilities filtered by program or wave | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `CutoverLead`, `CommandCenterLead` |
| GET | `/facilities/{id}` | Get one facility | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `CutoverLead`, `CommandCenterLead` |
| POST | `/facilities/{id}/configure-build` | Configure facility build | `BuildAnalyst` |
| POST | `/facilities/{id}/mark-validated` | Mark facility validated | `ImplementationDirector` |
| POST | `/facilities/{id}/complete-cutover-dress-rehearsal` | Close the dress rehearsal and grant cutover readiness | `CutoverLead` |
| POST | `/facilities/{id}/stabilize` | Mark a live facility stabilized | `CommandCenterLead` |
| POST | `/facilities/{id}/cutover-tasks` | Add a cutover plan step | `CutoverLead` |
| GET | `/facilities/{id}/cutover-tasks` | List a facility's cutover tasks | `ImplementationAnalyst`, `CutoverLead` |
| GET | `/cutover-tasks` | List cutover tasks filtered by facility | `ImplementationAnalyst`, `CutoverLead` |
| GET | `/cutover-tasks/{id}` | Get one cutover task | `ImplementationAnalyst`, `CutoverLead` |
| POST | `/cutover-tasks/{id}/start` | Start a cutover step | `CutoverLead` |
| POST | `/cutover-tasks/{id}/complete` | Complete a cutover step | `CutoverLead` |
| POST | `/cutover-tasks/{id}/skip` | Skip a non-essential cutover step | `CutoverLead` |
| POST | `/cutover-tasks/{id}/block` | Block a cutover step | `CutoverLead` |
| POST | `/cutover-tasks/{id}/unblock` | Unblock a cutover step | `CutoverLead` |

### 4.3. Departments and System Build Items

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities/{id}/departments` | Create a department | `BuildAnalyst` |
| GET | `/facilities/{id}/departments` | List a facility's departments | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TrainingCoordinator` |
| GET | `/departments` | List departments filtered by facility or program | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TrainingCoordinator` |
| GET | `/departments/{id}` | Get one department | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TrainingCoordinator` |
| POST | `/departments/{id}/complete-build` | Close department build | `BuildAnalyst` |
| POST | `/departments/{id}/begin-training` | Open department training | `TrainingCoordinator` |
| POST | `/departments/{id}/close-proficiency-gate` | Declare department readiness for go-live | `TrainingCoordinator` |
| POST | `/departments/{id}/system-build-items` | Create a build item | `BuildAnalyst` |
| GET | `/departments/{id}/system-build-items` | List a department's build items | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TestLead` |
| GET | `/system-build-items` | List build items filtered by department or program | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TestLead` |
| GET | `/system-build-items/{id}` | Get one build item | `ImplementationDirector`, `ImplementationAnalyst`, `BuildAnalyst`, `TestLead` |
| POST | `/system-build-items/{id}/start-build` | Begin build work | `BuildAnalyst` |
| POST | `/system-build-items/{id}/complete-build` | Complete build and score customization risk | `BuildAnalyst` |
| POST | `/system-build-items/{id}/start-testing` | Begin integrated testing | `TestLead` |
| POST | `/system-build-items/{id}/complete-validation` | Close validation for the build item | `TestLead` |
| POST | `/system-build-items/{id}/rework` | Return a rejected build item to build | `BuildAnalyst` |
| POST | `/system-build-items/{id}/reset-to-draft` | Reset an over-rejected build item to draft | `BuildAnalyst` |

### 4.4. Staff, Training, Trainers and Proficiency

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ehr-implementations/{id}/staffs` | Register a staff member | `TrainingCoordinator` |
| GET | `/ehr-implementations/{id}/staffs` | List a program's staff | `ImplementationDirector`, `ImplementationAnalyst`, `TrainingCoordinator`, `CommandCenterLead` |
| GET | `/staffs` | List staff filtered by program, department or preceptor | `ImplementationDirector`, `ImplementationAnalyst`, `TrainingCoordinator`, `CommandCenterLead` |
| GET | `/staffs/{id}` | Get one staff member | `ImplementationDirector`, `ImplementationAnalyst`, `TrainingCoordinator`, `CommandCenterLead` |
| POST | `/staffs/{id}/issue-credential` | Issue the go-live credential | `TrainingCoordinator` |
| POST | `/staffs/{id}/reassign-training` | Return a failed staff member to training | `TrainingCoordinator` |
| POST | `/staffs/{id}/training-assignments` | Assign a curriculum | `TrainingCoordinator` |
| GET | `/staffs/{id}/training-assignments` | List a staff member's assignments | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/training-assignments` | List assignments filtered by staff | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/training-assignments/{id}` | Get one assignment | `ImplementationAnalyst`, `TrainingCoordinator` |
| POST | `/training-assignments/{id}/log-hours` | Log curriculum hours against an assignment | `TrainingCoordinator` |
| POST | `/training-assignments/{id}/complete` | Complete a curriculum assignment | `TrainingCoordinator` |
| POST | `/training-assignments/{id}/waive` | Waive a curriculum assignment | `TrainingCoordinator` |
| POST | `/staffs/{id}/credentialed-trainers` | Start a trainer certification record | `TrainingCoordinator` |
| GET | `/staffs/{id}/credentialed-trainers` | List a staff member's trainer records | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/credentialed-trainers` | List trainer records filtered by staff | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/credentialed-trainers/{id}` | Get one trainer record | `ImplementationAnalyst`, `TrainingCoordinator` |
| POST | `/credentialed-trainers/{id}/certify` | Certify a credentialed trainer | `TrainingCoordinator` |
| POST | `/credentialed-trainers/{id}/revoke` | Revoke a trainer certification | `TrainingCoordinator` |
| POST | `/credentialed-trainers/{id}/recertify` | Recertify an expired trainer | `TrainingCoordinator` |
| POST | `/staffs/{id}/proficiency-exams` | Schedule a proficiency exam | `TrainingCoordinator` |
| GET | `/staffs/{id}/proficiency-exams` | List a staff member's exams | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/proficiency-exams` | List exams filtered by staff or proctor | `ImplementationAnalyst`, `TrainingCoordinator` |
| GET | `/proficiency-exams/{id}` | Get one exam | `ImplementationAnalyst`, `TrainingCoordinator` |
| POST | `/proficiency-exams/{id}/record-result` | Record the proctored exam result | `CredentialedTrainer` |
| POST | `/proficiency-exams/{id}/mark-no-show` | Record an exam no-show | `CredentialedTrainer` |

### 4.5. Test Scenarios and Defects

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/system-build-items/{id}/test-scenarios` | Define a test scenario | `TestLead` |
| GET | `/system-build-items/{id}/test-scenarios` | List a build item's scenarios | `ImplementationAnalyst`, `TestLead`, `BuildAnalyst` |
| GET | `/test-scenarios` | List scenarios filtered by build item | `ImplementationAnalyst`, `TestLead`, `BuildAnalyst` |
| GET | `/test-scenarios/{id}` | Get one scenario | `ImplementationAnalyst`, `TestLead`, `BuildAnalyst` |
| POST | `/test-scenarios/{id}/execute` | Execute a test scenario | `TestLead` |
| POST | `/test-scenarios/{id}/reset` | Return a failed scenario to `DEFINED` for re-execution | `TestLead` |
| POST | `/test-scenarios/{id}/record-defect` | Raise a defect against a failing scenario | `TestLead` |
| GET | `/test-defects` | List defects filtered by scenario | `ImplementationAnalyst`, `TestLead`, `BuildAnalyst` |
| GET | `/test-defects/{id}` | Get one defect | `ImplementationAnalyst`, `TestLead`, `BuildAnalyst` |
| POST | `/test-defects/{id}/begin-remediation` | Begin defect remediation | `BuildAnalyst` |
| POST | `/test-defects/{id}/resolve` | Resolve a defect | `BuildAnalyst` |
| POST | `/test-defects/{id}/defer` | Defer a non-blocking defect | `TestLead` |
| POST | `/test-defects/{id}/reopen` | Reopen a defect in the current epoch | `TestLead` |

### 4.6. Data Conversion and Patient Orders

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities/{id}/data-conversion-batches` | Stage a legacy data-conversion load | `ConversionAnalyst` |
| GET | `/facilities/{id}/data-conversion-batches` | List a facility's conversion batches | `ImplementationAnalyst`, `ConversionAnalyst` |
| GET | `/data-conversion-batches` | List conversion batches filtered by facility | `ImplementationAnalyst`, `ConversionAnalyst` |
| GET | `/data-conversion-batches/{id}` | Get one conversion batch | `ImplementationAnalyst`, `ConversionAnalyst` |
| POST | `/data-conversion-batches/{id}/begin-validation` | Begin batch validation | `ConversionAnalyst` |
| POST | `/data-conversion-batches/{id}/load` | Load validated rows into the target | `ConversionAnalyst` |
| POST | `/data-conversion-batches/{id}/reconcile` | Reconcile a loaded batch | `ConversionAnalyst` |
| POST | `/data-conversion-batches/{id}/rollback` | Roll back a loaded or reconciled batch | `ConversionAnalyst` |
| POST | `/facilities/{id}/patient-orders` | Convert an active patient order | `ConversionAnalyst` |
| GET | `/facilities/{id}/patient-orders` | List a facility's orders | `ImplementationAnalyst`, `ConversionAnalyst`, `OrderReconciler`, `RevenueCycleAnalyst` |
| GET | `/patient-orders` | List orders filtered by facility | `ImplementationAnalyst`, `ConversionAnalyst`, `OrderReconciler`, `RevenueCycleAnalyst` |
| GET | `/patient-orders/{id}` | Get one patient order | `ImplementationAnalyst`, `ConversionAnalyst`, `OrderReconciler`, `RevenueCycleAnalyst` |
| POST | `/patient-orders/{id}/reconcile` | Reconcile the clinical order | `OrderReconciler` |
| POST | `/patient-orders/{id}/backfill-paper-order` | Backfill a paper order slip | `OrderReconciler` |
| POST | `/patient-orders/{id}/post-charge` | Post the captured charge | `RevenueCycleAnalyst` |
| POST | `/patient-orders/{id}/submit-claim` | Submit the claim | `RevenueCycleAnalyst` |
| POST | `/patient-orders/{id}/record-claim-response` | Record the payer claim response | `RevenueCycleAnalyst` |
| POST | `/patient-orders/{id}/reopen-claim` | Reopen a denied claim for correction | `RevenueCycleAnalyst` |

### 4.7. Interfaces and Messages

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ehr-implementations/{id}/interface-channels` | Define an interface channel | `InterfaceEngineer` |
| GET | `/ehr-implementations/{id}/interface-channels` | List a program's interface channels | `ImplementationAnalyst`, `InterfaceEngineer` |
| GET | `/interface-channels` | List interface channels filtered by program | `ImplementationAnalyst`, `InterfaceEngineer` |
| GET | `/interface-channels/{id}` | Get one interface channel | `ImplementationAnalyst`, `InterfaceEngineer` |
| POST | `/interface-channels/{id}/begin-build` | Begin channel build | `InterfaceEngineer` |
| POST | `/interface-channels/{id}/begin-validation` | Begin message validation | `InterfaceEngineer` |
| POST | `/interface-channels/{id}/complete-validation` | Close channel validation | `InterfaceEngineer` |
| POST | `/interface-channels/{id}/return-to-build` | Return a failed channel to build | `InterfaceEngineer` |
| POST | `/interface-channels/{id}/messages` | Receive an interface message | `InterfaceEngineer` |
| GET | `/interface-channels/{id}/messages` | List a channel's messages | `ImplementationAnalyst`, `InterfaceEngineer` |
| GET | `/interface-messages` | List messages filtered by channel | `ImplementationAnalyst`, `InterfaceEngineer` |
| GET | `/interface-messages/{id}` | Get one interface message | `ImplementationAnalyst`, `InterfaceEngineer` |
| POST | `/interface-messages/{id}/validate` | Validate a received message | `InterfaceEngineer` |

### 4.8. Command Center Tickets, Staffing and Optimization Backlog

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/command-center-tickets` | Raise a command-center ticket | `CommandCenterLead`, `TriageCommander` |
| GET | `/command-center-tickets` | List command-center tickets | `CommandCenterLead`, `TriageCommander`, `ImplementationAnalyst` |
| GET | `/command-center-tickets/{id}` | Get one ticket | `CommandCenterLead`, `TriageCommander`, `ImplementationAnalyst` |
| POST | `/command-center-tickets/{id}/triage` | Triage a reported ticket | `TriageCommander` |
| POST | `/command-center-tickets/{id}/begin-resolution` | Begin ticket resolution | `TriageCommander` |
| POST | `/command-center-tickets/{id}/resolve` | Resolve a ticket | `TriageCommander` |
| POST | `/staffing-shifts` | Schedule a command-center shift | `CommandCenterLead` |
| GET | `/staffing-shifts` | List staffing shifts | `CommandCenterLead`, `ImplementationAnalyst` |
| GET | `/staffing-shifts/{id}` | Get one staffing shift | `CommandCenterLead`, `ImplementationAnalyst` |
| POST | `/staffing-shifts/{id}/activate` | Activate a shift at its start | `CommandCenterLead` |
| POST | `/staffing-shifts/{id}/complete` | Complete a shift | `CommandCenterLead` |
| POST | `/staffing-shifts/{id}/reassign` | Reassign a future shift | `CommandCenterLead` |
| POST | `/optimization-backlog-items` | Raise an optimization backlog item | `OptimizationLead` |
| GET | `/departments/{id}/optimization-backlog-items` | List a department's optimization items | `OptimizationLead`, `ImplementationAnalyst` |
| GET | `/optimization-backlog-items` | List optimization items | `OptimizationLead`, `ImplementationAnalyst` |
| GET | `/optimization-backlog-items/{id}` | Get one optimization item | `OptimizationLead`, `ImplementationAnalyst` |
| POST | `/optimization-backlog-items/{id}/triage` | Triage an optimization item | `OptimizationLead` |
| POST | `/optimization-backlog-items/{id}/schedule` | Schedule an item into a release epoch | `OptimizationLead` |
| POST | `/optimization-backlog-items/{id}/start` | Begin optimization work | `OptimizationLead` |
| POST | `/optimization-backlog-items/{id}/release` | Release an optimization item | `OptimizationLead` |
| POST | `/optimization-backlog-items/{id}/reject` | Reject an optimization item | `OptimizationLead` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_UNVERIFIED_TRAINER` | 403 Forbidden |
| `ERR_EHR_IMPLEMENTATION_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BUILD_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_SCENARIO_NOT_FOUND` | 404 Not Found |
| `ERR_DEFECT_NOT_FOUND` | 404 Not Found |
| `ERR_CHANNEL_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_CONVERSION_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_BATCH_SIZE_INVALID` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_POSTURE_BLOCKS_OPERATION` | 409 Conflict |
| `ERR_EPOCH_MISMATCH` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_NOT_RECONCILED` | 422 Unprocessable Entity |
| `ERR_PROCEDURE_CREDENTIAL_MISSING` | 422 Unprocessable Entity |
| `ERR_CUSTOMIZATION_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEFECT_BLOCKS_DEPARTMENT` | 422 Unprocessable Entity |
| `ERR_CHANNEL_NOT_VALIDATED` | 422 Unprocessable Entity |
| `ERR_GO_LIVE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_DEFECT_SEVERITY_NOT_DEFERRABLE` | 422 Unprocessable Entity |
| `ERR_TRAINER_OBSERVATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CLAIM_RESPONSE_INVALID` | 422 Unprocessable Entity |
| `ERR_PRIMARY_FACILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BALANCE_VARIANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INTERFACE_MESSAGE_INVALID` | 422 Unprocessable Entity |
| `ERR_INTERFACE_LATENCY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRAINING_HOURS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PROFICIENCY_GATE_CLOSED` | 422 Unprocessable Entity |
| `ERR_TEMPORAL_OVERLAP` | 409 Conflict |
| `ERR_PRECEDING_STEP_INCOMPLETE` | 409 Conflict |
| `ERR_RETEST_COOLDOWN_ACTIVE` | 409 Conflict |
| `ERR_GO_LIVE_AFTER_TARGET` | 422 Unprocessable Entity |
| `ERR_RELEASE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |