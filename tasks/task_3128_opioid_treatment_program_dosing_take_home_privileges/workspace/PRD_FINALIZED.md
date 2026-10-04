# OTP Dosing, Take-Home Privileges and Compliance API — Product Requirements Document

## 1. Introduction

Opioid Treatment Programs operate under a regulatory regime in which a single milligram of dispensed medication is a matter of public record. A clinic that cannot account for what it poured, what it returned, and what a patient carried home is a clinic that cannot survive an inspection — and, more urgently, a clinic whose patients may be diverting medication into the community. This document specifies the API that a multi-site treatment organization uses to run that regime: admission and diagnosis confirmation, dual-enrollment screening, observed daily dosing with nurse verification, the granting and revocation of take-home privileges, counseling and treatment-plan review cadence, guest dosing coordination across clinics, and the inventory accounting that ties it all together.

The product exists because the work is currently spread across paper logs, spreadsheet reconciliations and institutional memory. Staff cannot answer, at a moment's notice, whether a patient cleared the threshold for carries, whether the clinic's carry pool has room, or whether last month's inventory variance was within tolerance. Regulators arrive without warning and ask exactly those questions. The API therefore treats regulatory readiness not as a reporting feature bolted on at the end, but as a live property of the system: every program carries a dispensing posture, every patient carries parallel compliance standings, and every medication movement is a recorded, witnessed, and reconcilable event.

Three structural constraints shape the design. First, the clinic's authority over a patient is not absolute — a program's posture can be restricted or frozen by diversion findings, corrective actions, or inventory variance, and in those states the system must refuse to dispense, defer, schedule or grant medication. Second, take-home carries are a finite, program-wide resource governed by an explicit quota ledger; a patient's clinical eligibility and the program's pool must both permit a grant. Third, the medication itself is conserved: milligrams issued, voided, consumed and drawn must reconcile, and the system exposes conserved quantities that must remain at their invariant values no matter what sequence of actions the operator performs.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API, independent of any specific workflow.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` names the operational capacity in which that user acts. If either header is absent, or if the supplied role is not one of the six declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Role membership alone is not sufficient to perform an operation: if the acting role is not among the roles authorized for that operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly six roles, spelled as follows: `ProgramAdministrator`, `Physician`, `Nurse`, `Counselor`, `MedicalDirector` and `RegulatoryAuditor`.

The `ProgramAdministrator` is the clinic operations administrator, owning intake, scheduling, inventory custody, guest-dosing paperwork and corrective-action paperwork. The role deliberately has no authority to confirm diagnoses, authorise doses or grant carries, which is why a `ProgramAdministrator` can register a patient but cannot admit one. When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow writes a staff identifier, but it never compares it to an entity's `id`.

The `Physician` is the prescribing physician — confirming diagnoses, owning dose orders, signing exception requests and plan reviews. The role has no inventory custody and cannot grant carries. The `Nurse` is the dispensing nurse, owning the observed-dose pipeline from check-in through dispense, witnessing waste, and acknowledging inbound guest dosing; a nurse cannot verify a dose for a patient outside the nurse's own program. The `Counselor` owns the counseling cadence that feeds the counseling standing dimension, and holds no medication, carry or inspection authority. The `MedicalDirector` holds the sole authority to grant or revoke take-home privileges, to decide exception requests and to reinstate a suspended patient; by segregation of duties a director may never decide an exception the director authored. The `RegulatoryAuditor` is the external regulator and diversion-control auditor, suspending and resuming programs, running inspections, recording findings and driving diversion cases to disposition, but never dispensing, prescribing or granting carries.

For each of these five roles — `Physician`, `Nurse`, `Counselor`, `MedicalDirector` and `RegulatoryAuditor` — the identity is entity-backed. When `X-User-Role` is one of them, `X-User-ID` is the `id` of the acting `User`; ownership checks on any resource that references a `User` compare the resource's foreign-key field to `X-User-ID`. Thus the acting `Physician` is resolved to a `User` row and the acting `Nurse` likewise, and the `MedicalDirector`, `Counselor` and `RegulatoryAuditor` roles carry the same entity-backed identity. Only the `ProgramAdministrator` carries an opaque identifier — the other opaque identity in this system belongs to regulator accounts that hold no clinic membership, and that role nonetheless remains part of the mandatory six-role enumeration for authentication.

Two further cross-cutting authorization rules deserve emphasis because they are checked before workflow-specific logic. Segregation of duties (priority 3 overall) forbids the acting user from colliding with any physician, supervisor or witness identifier that the same action nominates for a different step; a violation is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 400). Program-membership checks are narrower still: a `Nurse` acting on a resource belonging to another program is rejected with `ERR_NURSE_NOT_IN_PROGRAM` (HTTP 403), and a `Physician` confirming a diagnosis for a patient admitted at a different clinic is rejected with `ERR_PHYSICIAN_NOT_IN_PROGRAM` (HTTP 403).

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

List operations accept two query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10, must be no smaller than 1, and must be no larger than 100. The `offset` parameter states how many items to skip before the page begins and defaults to 0. Unless a specific workflow says otherwise, every list response is ordered by `created_at` ascending.

List-based responses (in both their paginated and non-paginated forms) place four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count` and `has_more`. Note that `GET /otp/programs/{id}/carry-quota` returns its single ledger wrapped as a one-element array rather than as a bare object.

### 2.4. Common Resource Properties

Every persisted resource in this API — `Program`, `CarryQuotaLedger`, `Patient`, `DoseOrder`, `DoseDispense`, `TakeHomePrivilege`, `TakeHomeException`, `TakeHomeCarryLedger`, `InventoryLot`, `InventoryTransaction`, `CounselingSession`, `TreatmentPlanReview`, `GuestDosingArrangement`, `ComplianceInspection`, `ComplianceFinding`, `CorrectiveAction`, `DiversionCase` and `User` — carries the same four system-managed properties. No resource in this scaffold is declared without them, so the following applies without exception:

- `id` (string) — a unique, server-minted identifier formatted as a UUID. Identifiers carry no type prefix: an `InventoryLot` and a `DoseDispense` are distinguished by which collection they were read from, not by a prefix on the identifier. Server-minted identifiers never participate in any ranking or tie-break expression.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string) — an ISO 8601 UTC timestamp recording the most recent modification.
- `version` (integer) — a system-managed integer that increments on every modification to the resource. It is the anchor for optimistic concurrency control (see §2.10).

Any mutation of a derived or computed field is a real mutation: it refreshes `updated_at` and increments `version`. This matters most for `Program`, whose computed posture counters and inventory variance are recomputed by background rules rather than by explicit client writes; a recomputation that changes a value is still a version bump.

### 2.5. The Two Stability Channels

A single number is not enough to describe a patient in this system, so the design splits the concept in two. Both channels are computed over the same `Patient` and evaluated at the same instant, but they are read by different consumers and disagree by construction.

The first channel is the published stability reading, the DIRECTION_A_STABILITY score, which the system exposes as the patient's `stability_score` on every patient read. It starts from a base of 50.0 and credits the patient for time in treatment — the smaller of 25.0 and one quarter of one point per whole day of `time_in_treatment_days` — and for completed work: two points per completed dose in the trailing 28 days, and one point per completed counseling session in that same window, capped at four sessions. It subtracts a penalty that grows with the current missed-dose streak — nothing at all when the streak is zero, and for a streak of one or more, three points per missed dose plus half a point per pair of missed doses counted triangularly — and it subtracts one and a half points for each missed dose recorded in the trailing twelve months. The result is rounded half up to one decimal place and clamped to the range 0.0 through 100.0. The DIRECTION_A_STABILITY value is what a patient read returns, and it is copied into the cached `stability_posting` field on the same row whenever the channel is recomputed.

The second channel is the DIRECTION_B_TAKE_HOME_READINESS score. It begins from the DIRECTION_A_STABILITY value computed at the same instant and then applies a series of standing penalties that the published channel deliberately ignores: eight points per dose in the current missed-dose streak; twelve points when `transportation_type` is `NO_RELIABLE_TRANSPORT`; twenty points when `diversion_standing` is `CONFIRMED_DIVERSION`; ten points when `diversion_standing` is `UNDER_INVESTIGATION`; six points when `counseling_standing` is `COUNSELING_DEFICIENT`; and four points when `counseling_standing` is `REVIEW_OVERDUE`. The intermediate is rounded half up to one decimal place and clamped to 0.0 through 100.0. The channel then applies a journal look-back discount over the patient's dose journal window, removing exactly two entries from the regulation journal window when both are present: the entry whose `created_at` is earliest in the window costs two points, and the entry whose `created_at` is latest costs one and a half points. When the window holds fewer than two entries, only the entries actually present are discounted, taken in that order. The result is rounded half up to one decimal place and clamped to 0.0 through 100.0 once more.

The DIRECTION_B_TAKE_HOME_READINESS number is never returned by a patient read. It gates carries, and it does so against a phase-dependent floor: the readiness reading must be at least 70.0 when the patient's `treatment_phase` is `MAINTENANCE`, and at least 75.0 in every other phase. Because Direction B subtracts penalties that Direction A does not, the two channels will publish different numbers for the same patient at the same instant; an implementer who caches one and serves it for the other will produce a measurable discrepancy.

### 2.6. The Compliance Posture Ladder

A program is never unconditionally open for business. The `posture` field on a `Program` takes one of three values — `NORMAL`, `RESTRICTED` or `FROZEN` — and gates operations on the program's children. The value is assigned by a single ladder evaluated in a fixed order, where the first matching branch wins:

1. If the program's `status` is `SUSPENDED`, posture is `FROZEN` and `posture_reason_code` is `PROGRAM_SUSPENDED_BY_REGULATOR`.
2. Otherwise, if `open_diversion_case_count` is at least 1, posture is `RESTRICTED` and the reason code is `DIVERSION_CASE_OPEN`.
3. Otherwise, if `open_critical_finding_count` is at least 1, posture is `RESTRICTED` and the reason code is `CRITICAL_CORRECTIVE_ACTION_OPEN`.
4. Otherwise, if `latest_inventory_variance_mg` is strictly greater than 500.0, posture is `RESTRICTED` and the reason code is `INVENTORY_VARIANCE_OVER_THRESHOLD`.
5. Otherwise posture is `NORMAL` and `posture_reason_code` is null.

Two subtleties are load-bearing. Step 2 fires on the first open diversion case, so a second or third open case produces no further state change — which is also why the transition table models the `ACTIVE`-to-`ACTIVE` posture recomputation as requiring between one and two open cases, no critical findings, and variance at or below the restricted threshold of 500 milligrams. The ladder runs on every mutation of a diversion case, a corrective action, inventory variance, or program status; it does not wait to be asked.

The posture value determines which operations a program will accept. A `FROZEN` posture blocks any operation that dispenses, defers, schedules or grants medication: diagnosis confirmation, dose-order activation, dose check-in, dispense, and guest-dosing transmission are all rejected with `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409). A `RESTRICTED` posture is a narrower and stricter gate: carries are not merely FROZEN-blocked but forbidden entirely, so a restricted clinic may not grant take-home privileges or decide exception requests at all, and those requests are rejected with `ERR_PROGRAM_POSTURE_RESTRICTED` (HTTP 403). Confirm-diagnosis additionally requires `NORMAL` rather than merely non-`FROZEN`; dose-order activation likewise; and a `SUSPENDED` program's `status` forces the `FROZEN` posture through step 1 of the ladder.

### 2.7. Carry Quota and Milligram Conservation

Take-home carries are a finite resource held at the program level. Each `Program` may have one `CarryQuotaLedger`, opened with an `allotted_carries` figure that states the total number of take-home carry slots the program may have outstanding. The ledger maintains `granted_carries` as the sum of `approved_carries` across all of the program's privilege rows whose `decision` is `APPROVED` or `APPROVED_WITH_EXCEPTION`; rows whose decision is `PENDING_REVIEW`, `DENIED` or `REVOKED` contribute nothing. From these the ledger derives `available_carries`, the global conserved quantity C1, which must equal `allotted_carries` minus `granted_carries` at all times.

The companion quantity lives on the patient. Each `Patient` may have one `TakeHomeCarryLedger`, which tracks carries at the patient level: `owns_privilege_count` counts the patient's privilege rows with decision `APPROVED` or `APPROVED_WITH_EXCEPTION`; `carries_used` sums the carries consumed by those privileges less the carries restored by revocation; and `carry_variance` is a second conserved quantity that must stay at 0 across every privilege and exception action. The program ledger carries its own two reports of work in flight: `held_privilege_count` counts the program's privilege rows whose decision is `PENDING_REVIEW`, and `pending_waste_mg` records the sum of wasted milligrams over the program's `WASTE` inventory movements whose status is `RECORDED`. The patient-level ledger also holds the milligram conservation identity C2: `carried_balance_mg` carries the expression `carried_issued_mg` minus `carried_voided_mg` minus `carried_dispensed_mg` minus `carried_consumed_mg`, and must remain 0.0 across every take-home dispense, waste, return and privilege void. Its terms are defined as follows: `carried_issued_mg` is the sum of `ordered_mg` over take-home dose rows ever created for the patient; `carried_dispensed_mg` is the sum of `dispensed_mg` over `COMPLETED` take-home dose rows; `carried_voided_mg` is the sum of `ordered_mg` over take-home dose rows cancelled because their privilege was revoked before the dose completed; and `carried_consumed_mg` is the sum of `wasted_mg` plus `returned_mg` over `COMPLETED` take-home dose rows — the portion of the drawn milligrams poured off or put back rather than swallowed.

Two further ledger fields make the hold mechanism auditable. `carries_held` counts appended outstanding holds awaiting a system posting, and `charges_held` is the left-hand term of the C1 identity at the patient level: the sum of `hold_ledger_delta` over the patient's privilege rows whose decision is `PENDING_REVIEW`. Every privilege row carries that signed `hold_ledger_delta`, recording the change the row made to the ledger: it is -1 when the privilege is opened on hold, +1 when it is approved, 0 when it is denied, +1 when it is revoked, and -1 when a reissue is approved.

### 2.8. Clinic Hours, Open Days and Dose Capacity

A program declares its operating envelope on the `Program` row itself, whose `name` is the clinic program name: `clinic_hours_start` and `clinic_hours_end` give the local open and close times in 24-hour `HH:MM` form; `open_days` lists the ISO weekday abbreviations on which the clinic operates, drawn from `MO`, `TU`, `WE`, `TH`, `FR`, `SA` and `SU`; `max_daily_dose_slots` caps the number of observed doses the clinic will accept in a single open day; and `dose_checkin_grace_minutes` — defaulting to 30 — states how many minutes past `clinic_hours_end` a check-in is still accepted.

Dosing is governed by these values rather than by wall-clock convenience. A scheduled dose carries a `scheduled_datetime` that must fall on one of the program's open days and inside the clinic window. Check-in is accepted only while the logical clock's instant is no later than the end of the program's open-day window plus `dose_checkin_grace_minutes`; an instant outside that envelope is rejected with `ERR_OUTSIDE_CLINIC_HOURS` (HTTP 409). A dose date that is not one of the program's `open_days` is rejected with `ERR_NOT_AN_OPEN_DAY`; a day already holding `max_daily_dose_slots` non-terminal doses is rejected with `ERR_NO_DOSE_CAPACITY`; and a patient who already has a non-terminal dose on the same `dose_date` is rejected with `ERR_DUPLICATE_ACTIVE_DOSE`. All three are HTTP 409.

The distinction between those last two rules is deliberate and easy to get wrong. The slot capacity counts the occupants of an open day and permits equality to hold — the `max_daily_dose_slots`-th dose is accepted, and the one after it is refused. The per-patient daily rule is a uniqueness constraint and forecloses equality: two non-terminal doses for the same patient on the same `dose_date` are never permitted, though doses on adjacent dates obviously are.

### 2.9. Inventory Custody and Lot Selection

Medication enters the system as an `InventoryLot`, received with a `lot_number` that must be unique within its program and medication, an `expiration_date` that is exclusive — the lot is unusable on and after that date — and a `quantity_received_mg`. Two optional attributes shape how it may be used: `dose_potency_mg_per_unit`, defaulting to 1.0, states the milligrams of active drug per dispensed unit, and `reusable_for_take_home`, defaulting to false, marks a lot that take-home doses may draw from. Each lot maintains `running_on_hand_mg` as its received quantity plus the sum of `quantity_mg` over its `InventoryTransaction` rows with status `RECORDED` or `RECONCILED`, accumulated in transaction `created_at` order; `on_hand_mg` is a read alias of that running figure; `is_expired` is true when the logical clock's date is on or after the lot's `expiration_date`.

A lot's `status` moves through `RECEIVED`, `IN_USE`, `DEPLETED`, `QUARANTINED` and `DESTROYED`. It becomes `IN_USE` automatically when the first transaction referencing it is recorded, and `DEPLETED` automatically once `running_on_hand_mg` falls to 0.0001 or below, after which no further `DISPENSE` transaction may be recorded against it. Quarantining is permitted only from `RECEIVED` or `IN_USE` — otherwise `ERR_LOT_NOT_QUARANTINABLE` (HTTP 409) — and removing a lot from the selector pool is the point of the operation. Releasing a quarantine requires the lot to actually be `QUARANTINED`, else `ERR_LOT_NOT_QUARANTINED` (HTTP 409), and returns it to the candidate pool. Destruction requires the lot to be fully emptied: a lot still holding milligrams cannot be destroyed and yields `ERR_LOT_NOT_EMPTY` (HTTP 409), and the destruction itself requires a witness identifier distinct from the acting user, else `ERR_WITNESS_REQUIRED` (HTTP 422).

When a dose is dispensed, the lot it draws from is chosen by a single deterministic selector rather than by operator preference. The candidate set is every lot satisfying all of the following: it belongs to the dose's program; its medication matches the order's medication; its status is `RECEIVED` or `IN_USE`; it is not expired; its `running_on_hand_mg` is at least the dose's `ordered_mg`; and, when the dose's `source_type` is `TAKE_HOME_ISSUANCE`, its `reusable_for_take_home` flag is true. Candidates are ranked by `expiration_date` ascending so that the earliest usable expiration is drawn first, with ties broken by `created_at` ascending. If the candidate set is empty the dispense fails with `ERR_NO_ELIGIBLE_LOT` (HTTP 409). There is no deferred queue and no second-choice lot; server-minted identifiers play no part in the ranking or the tie-break.

Two related ceilings protect the supply. A requested quantity that would exceed the selected lot's `running_on_hand_mg` is rejected with `ERR_INVENTORY_CEILING_EXCEEDED` (HTTP 402). A lot that has expired yields `ERR_LOT_EXPIRED` (HTTP 409) and one that is `QUARANTINED` yields `ERR_LOT_QUARANTINED` (HTTP 409), both distinct from the empty-candidate-set failure.

### 2.10. Optimistic Concurrency Control

Three create operations require the client to prove that it has observed the parent resource's current version. Each names its expected version explicitly in the request body, and the field is not optional.

Creating a take-home privilege requires `expected_patient_version`. It must equal the target `Patient`'s current `version` at the moment the write is applied. If the patient's version has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because approve and revoke actions on an existing privilege legitimately append new privilege rows under the cyclic reissue rules, so a writer holding a stale view of the patient would be attaching a privilege to a version of the patient that no longer exists.

Creating a take-home exception requires `expected_privilege_version`, matching the target `TakeHomePrivilege`'s current `version`. Because approving or denying a privilege records a decision on precisely the row the exception was meant to challenge, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The challenged privilege is not a client input on the create request; it is resolved from the patient, being that patient's `DENIED` privilege.

Creating a guest dosing arrangement requires `expected_patient_version` against the travelling `Patient`. Transmitting or acknowledging another arrangement for the same patient bumps that patient's version, so the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint in this API takes a version field. The stale-version check sits at priority 6 in the global validation order, after existence checks but before state-precondition checks.

### 2.11. Nested Resource Retrieval and Validation Order

Resource identifiers appearing in a path are validated left to right, in the order they appear in the path. The path variable naming convention is collection-specific: `programId` and the program-scoped `id` name a program, `patientId` a patient, `doseOrderId` a dose order, `doseId` a dose, `privilegeId` a take-home privilege, `exceptionId` a take-home exception, `arrangementId` a guest dosing arrangement, `lotId` an inventory lot, `transactionId` an inventory movement, `inspectionId` a compliance inspection, `findingId` a compliance finding, `actionId` a corrective action, `caseId` a diversion case, `userId` a staff member, `sessionId` a counseling session, `reviewId` a treatment plan review and `ledgerId` a carry ledger; the reconciliation `period` is the year-and-month path segment that names the period being closed. The request fails with the 404 code corresponding to the first identifier that does not resolve — for example, `ERR_PROGRAM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_DOSE_ORDER_NOT_FOUND`, `ERR_DOSE_NOT_FOUND`, `ERR_PRIVILEGE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_DIVERSION_CASE_NOT_FOUND`, `ERR_ACTION_NOT_FOUND`, `ERR_ARRANGEMENT_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` or `ERR_CARRY_LEDGER_NOT_FOUND`. Foreign keys supplied in a request body are validated in the order the endpoint's input list declares them, and a failure yields the same family of 404 codes.

Beyond existence, the system evaluates validations in a fixed global priority order, and the ordering is observable because it decides which error a caller sees when several rules would fail at once. Authentication comes first (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (priority 2, `ERR_INSUFFICIENT_PERMISSIONS`), then segregation of duties (priority 3, `ERR_SELF_REVIEW_FORBIDDEN`), then path-existence (priority 4), body foreign-key existence (priority 5), and the optimistic-concurrency check (priority 6, `ERR_STALE_VERSION`). State-precondition checks follow at priority 7, yielding the `409` family of transition errors. The safety gates follow: posture (priorities 8 and 9), diversion control (priority 10), guest-dosing clinic constraints (priority 11), travel-window overlap (priority 12), and the clinic-day schedule rules (priority 13). Constraint checks then run: titration (priority 14), mass balance (priority 15), partial-dispense accumulation (priority 16), witness requirements (priority 17), carry determination (priority 18), the stability floor (priority 19), carry quota (priority 20), the inventory ceiling (priority 21), lot usability (priority 22), guest token validity (priority 23), exception carry caps (priority 24), text minimum lengths (priority 25) and finally closed-enum and numeric-range checks (priority 26, `ERR_INVALID_REQUEST`).

The practical consequence is worth stating plainly, because it is the source of the most common integration error: when a request violates both a state rule and a safety rule, the state rule wins and the caller sees the `409` transition error rather than the safety error. Likewise, when a request is both over the day's capacity and under-stocked on inventory, the temporal capacity check at priority 13 fires before the inventory ceiling at priority 21. And when a patient is both short of the required time in treatment and below the stability floor, the carry determination at priority 18 reports the insufficient-time error before the stability check at priority 19 reports `ERR_STABILITY_BELOW_THRESHOLD`.

### 2.12. Numeric Precision and Rounding

Every computed figure in this API is rounded half up to a declared number of places, and the declaration differs by quantity. The DIRECTION_A_STABILITY and DIRECTION_B_TAKE_HOME_READINESS channels round to one decimal place and clamp to the range 0.0 to 100.0. The patient risk score `risk_score_points` rounds to one decimal place, and its tier thresholds are inclusive — 25.0 or more is `HIGH`, 12.0 or more but under 25.0 is `MODERATE`, and anything below 12.0 is `LOW`. The inspection `readiness_score` rounds to one decimal place with inclusive tier thresholds at 85.0 (`READY`) and 60.0 (`NEEDS_ATTENTION`). Inventory variances and the dose tariff round to two decimal places. Carry counts are integers, and the integer floor operation appears in exactly one place — the pool term of the carry waterfall.

## 3. Business Logic & Workflows

### 3.1. Admission, Diagnosis Confirmation and Dual-Enrollment Screening

A patient enters the system when a `ProgramAdministrator` or a `Physician` registers them into an admitting clinic, supplying the `program_id` of that clinic together with the patient's `full_name`, `date_of_birth`, `government_id_hash`, `diagnosis_code`, `home_state_code`, `home_address`, `transportation_type` and `one_way_travel_minutes`. The registration lands the patient in `PENDING_ADMISSION` with `diagnosis_confirmed` false, `time_in_treatment_days` at 0, and a freshly computed published stability reading copied into `stability_posting`. The counseling and diversion dimensions are not recomputed at registration: they are seeded with their declared defaults — `counseling_standing` `CURRENT` and `diversion_standing` `CLEAR` — and the counseling reading is left to the cadence calculation when the record is next read. The `diagnosis_code` must be one of the ICD-10 opioid dependence codes `F11_10`, `F11_20` or `F11_99`; anything else is refused with `ERR_INVALID_DIAGNOSIS_CODE` (HTTP 400). The `transportation_type` is likewise an enumeration — `PRIVATE_VEHICLE`, `PUBLIC_TRANSIT`, `RIDE_SHARE` or `NO_RELIABLE_TRANSPORT` — and the `one_way_travel_minutes` figure is a deterministic estimate of travel time to the admitting clinic, not a geocoded value. A patient whose `home_state_code` differs from the program's two-letter `state_code` is thereby marked as a guest-only candidate.

Registration alone does not admit anyone. Admission is a separate act of clinical judgement performed by a `Physician`, and the system refuses to treat registration as consent. The admitting physician moves the patient from `PENDING_ADMISSION` to `ADMITTED`, and the request must satisfy six gates. The patient must actually be `PENDING_ADMISSION`, or the request fails with `ERR_PATIENT_NOT_PENDING_ADMISSION` (HTTP 409). The `diagnosis_code` must fall within the F11 block, or `ERR_INVALID_DIAGNOSIS_CODE` applies. The acting physician's own `program_id` must match the patient's admitting `program_id`, or the request is refused with `ERR_PHYSICIAN_NOT_IN_PROGRAM` (HTTP 403). No diversion case in `OPEN` or `UNDER_REVIEW` status may reference this patient, or the admission is blocked with `ERR_PATIENT_FLAGGED_FOR_DIVERSION` (HTTP 403). The patient's time-in-treatment tracker row must report a dual-enrollment screening flag of false, or the request is refused with `ERR_DUAL_ENROLLMENT_DETECTED` (HTTP 409) — this is the registry check that stops a patient being dosed by two clinics at once. Finally, the program's posture must be `NORMAL`, else `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409).

Dual-enrollment screening deserves a note on its key. The registry matches on the pair formed by the `government_id_hash` and the `date_of_birth`, using the hash verbatim as the screening key. The hash is stored opaquely, so two records collide only when both the hash and the date of birth agree.

Confirmation has consequences that ripple through the rest of the patient's record. The `diagnosis_confirmed` flag is set true — never by client input, always by the admitting physician's action. The `admission_datetime` is stamped with the logical clock, and `time_in_treatment_days` resets to 0. The DIRECTION_A_STABILITY channel is recomputed with the admission term applied, and the resulting value is copied into `stability_posting`. From that instant onward, `time_in_treatment_days` is derived as the whole number of days from `admission_datetime` to the logical clock, floor-rounded, and remains 0 while the patient is not yet admitted.

### 3.2. Patient Standing, Risk Tiering and Travel Accessibility

Three parallel standings describe a patient independently of their clinical status, and each one feeds a different downstream rule.

The `treatment_phase` dimension takes one of four values — `INDUCTION`, `STABILIZATION`, `MAINTENANCE` or `MEDICAL_WITHDRAWAL` — and defaults to `INDUCTION` at registration. It is moved only by a `Physician` or a `MedicalDirector`. The `counseling_standing` dimension takes `CURRENT`, `COUNSELING_DEFICIENT` or `REVIEW_OVERDUE`, defaults to `CURRENT`, and is driven by the cadence rules in §3.8. The `diversion_standing` dimension takes `CLEAR`, `UNDER_INVESTIGATION` or `CONFIRMED_DIVERSION`, defaults to `CLEAR`, and is driven by the disposition of diversion cases in §3.11. None of the three is a state of the patient's main `status` field; they are orthogonal readings that coexist with it.

Risk is a separate derivation. The `risk_score_points` figure is a weighted sum of four terms. The transport term is 12.0 points when `transportation_type` is `NO_RELIABLE_TRANSPORT`, 5.0 points for `RIDE_SHARE`, 1.5 points for `PUBLIC_TRANSIT`, and nothing for `PRIVATE_VEHICLE`. The diversion term is 30.0 points when `diversion_standing` is `CONFIRMED_DIVERSION`, 8.0 points when it is `UNDER_INVESTIGATION`, and nothing when it is `CLEAR`. The denial term is one point for each `MISSED` record among the patient's last twelve months of doses, capped at twelve such records. The streak term is two points per dose in the current missed-dose streak. Finally a phase-decay term applies: 30.0 points less one tenth of a point per whole day of `time_in_treatment_days`, floored at zero, so that long-tenured patients carry progressively less of this component. The sum is rounded half up to one decimal place, and the `risk_tier` is cut from it: `HIGH` at 25.0 points or above, `MODERATE` at 12.0 points or above (and below 25.0), and `LOW` below 12.0.

Two events outside the risk formula also move risk. Reinstating a suspended patient adds a flat 5.0 points before the tier is recut, and confirming diversion adds 25.0 points before the tier is recut — the latter on top of the 30.0-point diversion component that the new `diversion_standing` value already contributes to the next recomputation.

Travel accessibility is not merely a scored attribute; it feeds the carry determination directly, because a patient with `NO_RELIABLE_TRANSPORT` carries a twelve-point penalty in the take-home readiness channel described in §2.5. A rural patient with an unreliable vehicle is therefore structurally harder to clear for carries than an otherwise identical urban patient, which is the intended policy: fewer clinic visits means more risk of unobserved doses, and the system prices that risk rather than ignoring it.

### 3.3. Dose Orders and Titration Discipline

A `Physician` opens a dose order by supplying the `patient_id`, the `medication` — either `METHADONE` or `BUPRENORPHINE` — the `ordered_daily_mg`, and optionally `split_dose_authorized`, which defaults to false. The order is created in `DRAFT` status. At creation the system snapshots the applicable regulatory ceiling into `medication_ceiling_mg`: the program's `max_daily_mg_methadone` when the medication is methadone, or its `max_daily_mg_buprenorphine` when it is buprenorphine. Those ceilings themselves default to 120 milligrams and 24 milligrams respectively if the program did not state them. The `previous_ordered_daily_mg` field is initialised to 0.0, and it is worth understanding what it is for: it records the ordered milligrams that were in force immediately before the most recent increase or decrease, and the titration ceiling is read from it. The `last_increase_date` records the ISO date of the most recent increase, or remains null if the order has never been increased. The `phase_at_authorization` field is stamped when the order is activated, not when it is drafted, and it captures the patient's `treatment_phase` at that instant so that later phase changes do not retroactively reinterpret the authorisation.

Activation is where the dose order meets both the patient and the clinic. Moving the order from `DRAFT` to `ACTIVE` requires five things to hold. The order must genuinely be `DRAFT`, else `ERR_DOSE_ORDER_NOT_DRAFT` (HTTP 409). The patient must be `ADMITTED`, else `ERR_PATIENT_NOT_ADMITTED` (HTTP 409) — activation is the act that enrols the patient into the dosing population, so it cannot precede admission. The `ordered_daily_mg` must not exceed `medication_ceiling_mg`, or the request is refused with `ERR_DOSE_EXCEEDS_MEDICATION_CEILING` (HTTP 422). And the ordered milligrams must not exceed the previous ordered figure by more than 10.0 milligrams; a steeper jump is refused with `ERR_DOSE_TITRATION_TOO_FAST` (HTTP 422). The clinic's posture must be `NORMAL`, else `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409). Both the ceiling rule and the incremental rule are enforced at order creation as well as at activation, so a clinician who submits an over-ceiling or over-fast dose is told at once rather than at the last step.

The titration rule is deliberately phrased as a ceiling above the previous figure rather than as a fixed maximum. A patient dosed at 60 milligrams yesterday may be moved to 70 today, but not to 75; the constraint is on the size of the step, and it is a step of 10.0 milligrams or less, inclusive.

When activation succeeds, the order becomes `ACTIVE`, `phase_at_authorization` is stamped from the patient's current phase, and — when the patient was `ADMITTED` — the patient's own status advances to `ACTIVE`. That is the second and final step of the patient's admission arc. From `ACTIVE` the order may be suspended, which returns it to `SUSPENDED` and cancels its `SCHEDULED` doses; a suspended order may be reactivated, though reactivation from `SUSPENDED` again requires the clinic's posture to be `NORMAL` and reports `ERR_DOSE_ORDER_NOT_DRAFT` when the order is in neither `DRAFT` nor `SUSPENDED`. Suspending or reactivating an order in the wrong status reports `ERR_DOSE_ORDER_NOT_ACTIVE` (HTTP 409). Discontinuation is available from `DRAFT`, `ACTIVE` or `SUSPENDED` and is refused with `ERR_DOSE_ORDER_NOT_DISCONTINUABLE` (HTTP 409) once the order is already `DISCONTINUED`; it likewise cancels the order's `SCHEDULED` doses. `DISCONTINUED` is terminal, and orders are driven there automatically when their patient is discharged or completes a medically managed withdrawal.

### 3.4. The Observed Dose Pipeline and the Dose Tariff

Dose scheduling produces a `DoseDispense` row. A `Nurse` or a `ProgramAdministrator` supplies the `dose_order_id`, the `dose_date` and the `scheduled_datetime`, and may state a `source_type`, an `inventory_lot_id`, a `guest_arrangement_id` and a `privilege_id`. The `source_type` defaults to `OBSERVED_CLINIC` and may otherwise be `TAKE_HOME_ISSUANCE` or `GUEST_OBSERVED`. The new row begins in `SCHEDULED`. The `ordered_mg` is snapshotted from the active order's `ordered_daily_mg` together with its ceiling tariff, so that the dose is priced and checked against the values in force on the `dose_date` rather than against whatever the order says later. The `carry_count` is computed as 1 when the `source_type` is `TAKE_HOME_ISSUANCE` and 0 otherwise. The payload's `guest_arrangement_id` must be present and name an arrangement when the `source_type` is `GUEST_OBSERVED` and must be absent otherwise; the `privilege_id` must be present and name an approved privilege when the `source_type` is `TAKE_HOME_ISSUANCE` and must be absent otherwise. The `dispensed_mg`, `wasted_mg` and `returned_mg` figures all begin at 0, as do `carry_count`, `carries_before` and `carries_after`; `verification_result`, `arrived_at` and `completed_at` are null until their respective steps occur.

Scheduling is also where the clinic-day rules bind (§2.8), so a dose whose `dose_date` is not an `open_day`, whose `scheduled_datetime` falls outside the clinic window, whose day is already at `max_daily_dose_slots`, or which duplicates another non-terminal dose for the same patient on the same `dose_date` is refused with `ERR_NOT_AN_OPEN_DAY`, `ERR_OUTSIDE_CLINIC_HOURS`, `ERR_NO_DOSE_CAPACITY` or `ERR_DUPLICATE_ACTIVE_DOSE` respectively.

The patient's arrival advances the dose from `SCHEDULED` to `ARRIVED_AT_CLINIC` and stamps `arrived_at` with the logical clock. Five conditions guard this step. The dose must be `SCHEDULED`, else `ERR_DOSE_NOT_SCHEDULED` (HTTP 409). A dose whose `source_type` is `TAKE_HOME_ISSUANCE` may never be checked in — a carry is issued, not walked in to be swallowed under observation — and any attempt is refused with `ERR_TAKE_HOME_NOT_CHECKED_IN` (HTTP 409). The acting nurse's `program_id` must match the dose's `program_id`, or `ERR_NURSE_NOT_IN_PROGRAM` (HTTP 403). The instant must be no later than the end of the program's open-day window plus `dose_checkin_grace_minutes`, or `ERR_OUTSIDE_CLINIC_HOURS` (HTTP 409). And the clinic's posture must not be `FROZEN`, or `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409).

Verification is the nurse's identity and order check, passed or failed by the `identity_matched` flag in the request. A successful verification moves the dose to `NURSE_VERIFIED` and sets `verification_result` to `PASSED`; the acting nurse's identifier is recorded as `verification_staff_id`, taken from `X-User-ID`. A failed verification moves the dose to `VERIFICATION_FAILED`, sets `verification_result` to `FAILED`, and — this is deliberate — leaves the patient's `counseling_standing` and `risk_score_points` entirely unchanged. A patient who arrives and cannot prove identity is turned away without being penalised as a defaulter. A successful verification must additionally satisfy four gates: the dose must be `ARRIVED_AT_CLINIC`, else `ERR_DOSE_NOT_ARRIVED` (HTTP 409); the acting nurse must belong to the dose's program, else `ERR_NURSE_NOT_IN_PROGRAM` (HTTP 403); the patient's status must be one of `ACTIVE`, `ADMITTED` or `SUSPENDED_NON_COMPLIANT`, else `ERR_PATIENT_NOT_DOSABLE` (HTTP 409); and the dose's frozen `ordered_mg` must still match the order's snapshot — the frozen order must remain authoritative — else `ERR_DOSE_ORDER_CHANGED` (HTTP 409).

Dispensing draws the medication from inventory and moves the dose from `NURSE_VERIFIED` to `DISPENSED`. The nurse supplies `dispensed_mg` and may supply `wasted_mg`, `returned_mg`, `inventory_lot_id` and `witness_staff_id`. Four rules govern the step. The dose must be `NURSE_VERIFIED`, else `ERR_DOSE_NOT_VERIFIED` (HTTP 409). The dispensed, wasted and returned milligrams must sum exactly to the dose's `ordered_mg`, with every component non-negative, else `ERR_DOSE_MASS_MISMATCH` (HTTP 422); the dispense must also respect the cumulative view, in which the sum of previously dispensed, wasted and returned milligrams plus this movement may not exceed `ordered_mg`, or the request is refused with `ERR_PARTIAL_EXCEEDS_ORDERED` (HTTP 422). Any waste greater than zero requires a `witness_staff_id` that is present and differs from the acting nurse's `X-User-ID`, else `ERR_WITNESS_REQUIRED` (HTTP 422). The clinic's posture must be `NORMAL`, else `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409), and a lot must satisfy the selector of §2.9, else the dispense fails with `ERR_NO_ELIGIBLE_LOT` (HTTP 409), `ERR_LOT_EXPIRED` (HTTP 409) or `ERR_LOT_QUARANTINED` (HTTP 409).

The dispense leaves an inventory trail rather than merely adjusting a balance. A `DISPENSE` movement is appended with a negative `quantity_mg` equal to the dispensed milligrams and the selected lot recorded as `lot_id`; when `wasted_mg` is greater than zero a `WASTE` movement is appended with a negative quantity equal to the wasted milligrams; and when `returned_mg` is greater than zero a `RETURN` movement is appended with a positive quantity equal to the returned milligrams. The lot's `running_on_hand_mg` is then recomputed in transaction `created_at` order. When the dose's `source_type` is `TAKE_HOME_ISSUANCE`, the patient's carry ledger `carries_used` is set to the dose's `carries_after` figure, which is the `carries_before` snapshot plus the `carry_count`.

Completion closes the dose. A dose in `DISPENSED` moves to `COMPLETED` and stamps `completed_at` with the logical clock; a dose in any other status is refused with `ERR_DOSE_NOT_DISPENSED` (HTTP 409). Completion recomputes the carry ledger's `carried_dispensed_mg` and `carried_consumed_mg` and restates `carried_balance_mg` as `carried_issued_mg` minus `carried_voided_mg` minus `carried_dispensed_mg` minus `carried_consumed_mg` — an identity that must hold at 0.0 (§2.7). Completion also credits the patient: the DIRECTION_A_STABILITY channel is recomputed with the completion credit applied.

Not every dose is swallowed. A refusal is available from `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` and moves the dose to `REFUSED` with `completed_at` stamped; a dose in any other status yields `ERR_DOSE_NOT_REFUSABLE` (HTTP 409). Cancellation is available from `SCHEDULED`, `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` and moves the dose to `CANCELLED` with `completed_at` stamped; a terminal dose yields `ERR_DOSE_NOT_CANCELLABLE` (HTTP 409). The terminal statuses of this state machine are `COMPLETED`, `VERIFICATION_FAILED`, `REFUSED`, `MISSED` and `CANCELLED`.

Rescheduling is the one operation that both checks and re-prices a dose. It requires a `new_scheduled_datetime`, an `executed_carries` figure and a `schedule_id` in the payload, and it enforces the clinic-day rules of §2.8 together with the mass-balance and partial-dispense rules above; on success the dose's `scheduled_datetime` is replaced and the tariff is recomputed with the reschedule surcharge applied. The division of labour here is intentional: the same temporal and mass constraints that guard scheduling and dispensing also guard rescheduling, so a dose cannot be moved into an illegal slot or inflated past its ordered milligrams by rescheduling around the pipeline.

Finally, the charge for a dispensed dose is a tariff rather than a simple rate. Let `step_tier_sum(m)` denote the charge for `m` milligrams under the step schedule: 2.90 per milligram for the first 10 milligrams; 3.30 per milligram for milligrams 11 through 40; 5.25 per milligram for milligrams 41 through 90; and 6.80 per milligram beyond 90. The base pair is computed either as a single application of that schedule to `ordered_mg`, when `split_dose_authorized` is false, or as twice the schedule applied to half the ordered milligrams, when `split_dose_authorized` is true — the split-dose variant exists so that a patient dosed in two sittings is priced as two half-doses rather than one whole one. For an order of 90 milligrams this yields 390.50 under the single tariff and 308.50 under the split tariff, the latter being twice the schedule applied to 45 milligrams.

The over-ceiling surcharge starts from the number of milligrams by which `ordered_mg` exceeds the applicable program ceiling, floored at zero and rounded up to a whole milligram, and charges 1.25 for each such milligram. The base charge is that surcharge plus the base pair, rounded half up to two decimal places. On top of the base charge the dispense carries three further components, each computed on the billed amounts: a handling fee of 0.0125 per billed dispensed milligram and a security fee of 0.0075 per billed dispensed milligram, both rounded half up to two decimal places; and a waste fee of 1.15 for each whole block of ten milligrams of billed waste beyond a ten-milligram free allowance, again rounded half up to two decimal places. The billed dispensed and billed wasted quantities are the dose's `dispensed_mg` and `wasted_mg` when the program's posture is `NORMAL` and the patient's status is `ACTIVE`, and zero otherwise — the dose is priced whether or not anyone is billed.

The rounding order of this tariff is pinned and is the single most easily mis-implemented rule in the system. Every component is rounded half up to two decimal places first, and the rounded components are then summed; the unrounded sum is never the reported figure. For an order of 90 milligrams of methadone against a 120-milligram ceiling, with no waste and no split authorisation, the reported total is 392.31. An implementation that sums the unrounded components and rounds once at the end will produce a reconciling figure one cent lower at 392.30, and this is exposed rather than hidden: the charge-preview reading for an already-dispensed dose returns both variants side by side, as `total_charge_per_component_rounded` and `total_charge_sum_then_round`, together with `per_component_delta` stating the difference between them.

### 3.5. Missed Doses, Streaks and Non-Compliance Suspension

A dose that is never taken does not simply disappear from the schedule. When the logical clock's date has moved past a dose's `dose_date` and the dose is still `SCHEDULED`, the system moves it to `MISSED` automatically, provided the patient is in `ADMITTED`, `ACTIVE` or `SUSPENDED_NON_COMPLIANT`. A nurse or physician may also record the outcome explicitly with the same result. Four consequences follow from a miss.

The patient's `denial_count_12mo` is recomputed over the trailing 365 days at the logical clock, so the window slides rather than accumulating forever. The `missed_dose_streak` is set to the previous streak plus one; the streak counts consecutive `MISSED` rows with no intervening `COMPLETED` row, ordered oldest `created_at` first, so any completed dose resets it to zero. The DIRECTION_B_TAKE_HOME_READINESS channel is recomputed and its value copied into `stability_posting` — the take-home readiness of a patient who has just missed a dose is the number that matters to the carry rules, not the published stability figure. And for every one of the patient's privilege rows whose `decision` is `PENDING_REVIEW`, the `timetable_reconciled` flag is recomputed as true exactly when the patient's `journal_reconciled_through_date` is on or after the day immediately before the missed dose's `dose_date`.

Two second-hop cascades hang off the miss. When the recomputed `missed_dose_streak` reaches 3 or more, the patient's own transition to `SUSPENDED_NON_COMPLIANT` fires automatically, and every one of the patient's `ACTIVE` dose orders is moved to `SUSPENDED`. The streak threshold is three consecutive misses: two missed doses suspend nothing, and the third triggers the whole cascade in a single chain.

That cascade is thorough. Every dose for the patient still in `SCHEDULED`, `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` is cancelled. Every privilege the patient holds with decision `APPROVED` or `APPROVED_WITH_EXCEPTION` is revoked, with `freed_carries` set to that privilege's `approved_carries` so the program pool can reclaim the slots. Every privilege in `PENDING_REVIEW` whose `timetable_reconciled` is true is denied with `denial_reason_code` set to `ACTIVE_DENIAL_HISTORY` and `hold_ledger_delta` set to 0. Take-home dose rows still `SCHEDULED` are cancelled, and the sum of their `ordered_mg` is added to the carry ledger's `carried_voided_mg` — which is what keeps the milligram identity of §2.7 balanced when carries are snatched back. The DIRECTION_B_TAKE_HOME_READINESS channel is recomputed and published into `stability_posting`. And the patient's `risk_score_points` is increased by the missed-streak penalty multiplied by the streak, after which `risk_tier` is recut.

Reinstatement is available only to a `MedicalDirector` and only against four conditions. The patient must actually be `SUSPENDED_NON_COMPLIANT`, else `ERR_PATIENT_NOT_SUSPENDED` (HTTP 409). The `missed_dose_streak` must have fallen below 3 — a patient still in an active default cannot be reinstated — else `ERR_REINSTATEMENT_DENIAL_STREAK` (HTTP 409). The `counseling_standing` must not be `COUNSELING_DEFICIENT`, else `ERR_COUNSELING_CADENCE_BREACHED` (HTTP 403); this is the rule that makes reinstatement a joint clinical and compliance decision rather than a purely clinical one. And the program's posture must not be `FROZEN`, else `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409). A successful reinstatement returns the patient to `ACTIVE`, adds a flat 5.0 points to `risk_score_points` and recuts the tier, resets `treatment_phase` to `INDUCTION`, and recomputes the DIRECTION_A_STABILITY channel with the result copied into `stability_posting`. The phase reset is not punitive decoration — a reinstated patient is treated as restarting the induction pathway, which is why their carry eligibility must be re-earned rather than resumed.

### 3.6. Take-Home Privileges: Request, Hold and Evaluation

A take-home privilege begins its life as a request. A `MedicalDirector` supplies the `patient_id`, the `requested_carries` the patient is asking for, a `carry_interval_days` figure stating the days between mandatory clinic returns — which must fall between 1 and 28 inclusive — and an `expected_patient_version` that must match the patient's current version (§2.10). Optionally the request may carry a `reissued_from_privilege_id` naming a privilege being replaced. The new row begins in `PENDING_REVIEW` with `approved_carries` at 0, `freed_carries` at 0 and `expires_on` null — the expiration stamp is written at approval, not at request. Three ledger effects are immediate: the row's `hold_ledger_delta` is set to -1, the patient's carry ledger `charges_held` is incremented by one, and the same ledger's `carries_held` is incremented by one. A privilege sitting on hold therefore visibly occupies a hold slot in the ledger without yet consuming any part of the program pool.

A reissue is the cyclic path back into the process. When the request carries a `reissued_from_privilege_id`, that privilege's decision must be `REVOKED`, else the request is refused with `ERR_REISSUE_SOURCE_NOT_REVOKED` (HTTP 409); the patient must be `ACTIVE`, else `ERR_PATIENT_NOT_ACTIVE` (HTTP 409); and the program's posture must be `NORMAL`, else `ERR_PROGRAM_POSTURE_RESTRICTED` (HTTP 403). A reissue creates a fresh privilege row in `PENDING_REVIEW` with `hold_ledger_delta` of -1, raising `charges_held` and `carries_held` by one each exactly as a first-time request does. This is what closes the cycle `APPROVED` to `REVOKED` back to `PENDING_REVIEW` and on to `APPROVED` again: the product does not let a revoked patient acquire a new privilege by any other route.

Evaluation is the decision point, and it is the only operation that reads the carry tables. It is available to a `MedicalDirector` and has two outcomes on the non-exception path. The approval branch requires six conditions simultaneously. The privilege must be in `PENDING_REVIEW` or in `DENIED` — the denied case being re-evaluation, treated below — else `ERR_PRIVILEGE_NOT_PENDING` (HTTP 409). The patient's `time_in_treatment_days` must be at least 90, else `ERR_TIME_IN_TREATMENT_INSUFFICIENT` (HTTP 422). The privilege's `timetable_reconciled` must be true, else `ERR_TIMETABLE_LOOKAHEAD_FAILED` (HTTP 422) — and recall from §3.5 how that flag is recomputed, namely as true exactly when the patient's journal has been reconciled through the day immediately before the evaluation. The patient's `denial_count_12mo` must not exceed 2, else `ERR_ACTIVE_DENIAL_HISTORY` (HTTP 422). The patient's DIRECTION_B_TAKE_HOME_READINESS reading must be at least 70.0 when the phase is `MAINTENANCE` and at least 75.0 otherwise, else `ERR_STABILITY_BELOW_THRESHOLD` (HTTP 422). And the program's posture must be `NORMAL` — note this is the carry-specific gate, so a `RESTRICTED` clinic is refused with `ERR_PROGRAM_POSTURE_RESTRICTED` (HTTP 403) rather than the more general FROZEN block.

When every condition holds, the evaluation computes the grant size through the carry waterfall, records `evaluation_basis` as `TIME_IN_TREATMENT`, and stamps `expires_on` with the withdrawal-report expiration date computed as of the approval instant. It then releases the hold: `hold_ledger_delta` becomes 0 and the patient's `charges_held` is decremented by one, reversing the hold placed at request time. Finally, the system schedules the actual medication: a take-home dose row is synthesized for each of the first `approved_carries` open days with `source_type` `TAKE_HOME_ISSUANCE`, and the sum of their `ordered_mg` is added to the carry ledger's `carried_issued_mg`, which is the term that keeps the milligram identity balanced.

The denial branch fires when at least one of those approval conditions fails, and it is deliberately quiet about which one. The privilege moves to `DENIED`, the hold is released in exactly the same way — `hold_ledger_delta` set to 0 and `charges_held` decremented — but no carries are held and no dose row is synthesized. A `denial_reason_code` may be recorded from the enumeration `TIME_IN_TREATMENT_INSUFFICIENT`, `STABILITY_BELOW_THRESHOLD`, `ACTIVE_DENIAL_HISTORY`, `TIMETABLE_LOOKAHEAD_FAILED`, `CLINIC_MAX_CARRIES_EXCEEDED`, `SUPERVISOR_REVIEW_REQUIRED`, `TRANSPORTATION_RISK_UNMITIGATED`, `DIVERSIONS_OR_FINDINGS_OPEN` or `PROGRAM_POSTURE_RESTRICTED`, and the decision response returns the privilege so that the reason is visible.

Evaluation is also available against a privilege already in `DENIED`, and this path — unlike the others — reports the stale-state code `ERR_PRIVILEGE_NOT_PENDING` (HTTP 409) rather than a `NOT_DENIED` code when the row is in some third state. It succeeds when every one of the six approval conditions now holds at the current logical clock, in which case the privilege moves to `APPROVED`, its `denial_reason_code` is cleared to null, `approved_carries` is set from the waterfall, and the take-home dose rows are synthesized as on a first approval. A privilege denied for insufficient time in treatment is therefore re-evaluable once the patient's clock has advanced and the other conditions are met.

One rule deserves emphasis because it is a common trap. A grant smaller than what the patient requested is not an error. When the waterfall returns a cap below `requested_carries`, the evaluation returns HTTP 200 with the reduced count, and `denial_reason_code` is left unset. Only a complete refusal produces a `DENIED` decision; a partial grant is a successful evaluation.

### 3.7. The Carry Table and the Cap Waterfall

Carry entitlement is read from one of two tables, and the choice between them is determined by the path taken. The time-in-treatment table maps whole days in treatment to a carry allowance: at least 90 days earns 1 carry, at least 180 days earns 2, at least 270 days earns 3, at least 365 days earns 6, at least 540 days earns 13, and at least 730 days earns 27. Below the lowest threshold the allowance is zero. The table is walked in descending threshold order and the first threshold the patient's `time_in_treatment_days` meets or exceeds is the one that applies.

The second table maps treatment phase to an allowance independent of tenure: `INDUCTION` earns 0, `STABILIZATION` earns 1, `MAINTENANCE` earns 6, and `MEDICAL_WITHDRAWAL` earns 0. This table is consulted only on the exception path described in §3.9; the ordinary evaluation path reads the time-in-treatment table and nothing else.

The waterfall itself is a three-way minimum, and its second term is the one that surprises implementers. On the ordinary evaluation path, the system reads the program's carry quota ledger, taking `allotted_carries` and `granted_carries` for the privilege's program and deriving `available_carries` as the difference. It computes a pool cap as the integer floor of half the available carries, never below zero — the division by two is deliberate, so that no single patient can drain the program's pool even when the pool is large. It then sets the privilege's `eligible_carry_cap` to the smallest of three numbers: the privilege's `requested_carries`, the table allowance for the patient's time in treatment, and the pool cap. The `approved_carries` is then set equal to that cap. Once the grant is recorded, the program's `granted_carries` is increased by `approved_carries` and `available_carries` is restated as `allotted_carries` minus `granted_carries`, preserving the C1 identity.

The pool term applies before the table term in the sense that both are minima, but it is worth being explicit about the arithmetic: with an allotted quota of 40 and 30 already granted, the remainder is 10, the pool cap is the floor of half of 10, which is 5, and a patient requesting 13 carries under a table allowance of 13 is granted 5. The grant is the minimum of 13, 13 and 5.

If the pool remainder is zero or negative, the evaluation cannot grant anything, and the request is refused with `ERR_PROGRAM_CARRY_QUOTA_EXHAUSTED` (HTTP 402) — a payment-required code rather than a conflict, because the constraint is resource exhaustion rather than an illegal state. A related code, `ERR_EXCEPTION_CARRIES_EXCEED_CAP` (HTTP 422), guards the exception path when a director attempts to grant more than the applicable table allows.

Revocation reverses the quota consumption but not in the way the field names suggest. On revocation, the program's `granted_carries` is reduced by `freed_carries` and a separate reporting field, `released_carries`, is increased by the same amount. Because the availability invariant is defined as `allotted_carries` minus `granted_carries`, the released figure is a reporting field only and is never added back into the pool. An implementer who treats `released_carries` as an addition to `available_carries` will double-count the release and inflate the pool.

### 3.8. Counseling Cadence and Treatment Plan Review

Counseling attendance is credited against a rolling window whose length depends on the patient's phase. The cadence is 7 days during `INDUCTION`, 14 days during `STABILIZATION`, 30 days during `MAINTENANCE`, and 7 days during `MEDICAL_WITHDRAWAL`. A `Counselor` schedules a session by supplying the `patient_id`, a `session_type` of `INDIVIDUAL`, `GROUP` or `FAMILY`, the `scheduled_datetime`, the contracted `duration_minutes`, and optionally a `counselor_staff_id`; the session begins in `SCHEDULED`. Completion records how much of the session was actually attended: the counselor supplies `attended_minutes`, which is credited toward the weekly cadence and is at most the contracted `duration_minutes`. A no-show moves the session to `NO_SHOW` instead, and in both cases the patient's `counseling_standing` is recomputed. Only `COMPLETED` sessions count toward the cadence; `SCHEDULED`, `NO_SHOW` and `CANCELLED` rows contribute nothing.

The counseling half of the standing is a simple threshold. The system sums `attended_minutes` across the patient's completed sessions whose `completed_at` falls in the window running from the cadence length before the logical clock through the clock itself, inclusive at both ends. If that sum reaches 60 minutes, the counseling reading is `CURRENT`; below 60 minutes it is `COUNSELING_DEFICIENT`.

The plan-review half is a three-way reading with a grace band. A `Physician` or a `MedicalDirector` records a review by supplying the `patient_id`, a `reviewer_physician_id`, the `reviewed_at` instant, and optionally a `signed_off` flag that defaults to true. The review is stored as `COMPLETED` immediately, with the `cadence_days_applied` selected by the patient's phase at review time and `next_due_at` computed as the review instant plus that cadence. The review standing reads from the most recent completed review — the one with the greatest `reviewed_at`, tie-broken by greatest `created_at` — and is `CURRENT` while the logical clock is before `next_due_at`; `REVIEW_OVERDUE` once the clock has reached `next_due_at` but is still less than three days beyond it; and `COUNSELING_DEFICIENT` once the clock is three days or more past the due date. The grace band is asymmetric by design: the start is boundary-inclusive and the grace edge is boundary-exclusive, so the clock exactly at `next_due_at` is already overdue, while the clock exactly three days past is already deficient. A patient who has no completed review at all is treated as `REVIEW_OVERDUE` until the logical clock is more than three days past the admission datetime, after which the reading becomes `COUNSELING_DEFICIENT`.

The two readings are merged into a single `counseling_standing` by taking the more severe of the two, ordered `COUNSELING_DEFICIENT` above `REVIEW_OVERDUE` above `CURRENT`. This merged value then propagates: it penalises the take-home readiness channel by six points when deficient and four points when overdue (§2.5), it blocks reinstatement of a suspended patient (§3.5), and it drives the inspection readiness penalty of §3.12. Review dates are also not purely informational — the `next_due_at` stamp is what makes a clinic's plan-review currency inspectable without re-deriving it.

The treatment phase itself is moved by a `Physician` or a `MedicalDirector`, who supplies the new `treatment_phase` and may optionally supply a `reconciled_days` count. When `reconciled_days` is at least 1, the phase advance also advances the regulated phase journal, setting the patient's `journal_reconciled_through_date` to the logical clock's date. That field is the one the privilege evaluation reads when it recomputes `timetable_reconciled`, which is why a patient's carry eligibility depends on their phase-journal discipline and not solely on their clinical stability. The phase change also triggers a recomputation of `counseling_standing`, since the cadence window length changes with the phase, and a recomputation of the published stability reading.

### 3.9. Documented Exceptions

The exception mechanism exists so that a medical director can lift a patient to the better of the two carry tables when clinical circumstances justify it, and it is deliberately slow. A `Physician` opens an exception by supplying the `patient_id`, the `requested_carries`, an `exception_type` drawn from `TIME_IN_TREATMENT_WAIVER`, `TRAVEL_HARDSHIP`, `CLINIC_CLOSURE` or `EMERGENCY`, a free-text `clinical_justification`, a `supervisor_id`, and an `expected_privilege_version` that must match the target privilege's current version (§2.10). The row begins in `REQUESTED`, and the `requesting_physician_id` is taken from `X-User-ID` rather than from the payload — the signing physician is the acting physician. The `clinical_justification` must run to at least 40 characters, and a shorter one is refused with `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400).

Routing the exception to the medical director is the physician's second act, and it enforces the separation of duties at the point of routing rather than only at the point of decision. The exception must still be `REQUESTED`, else `ERR_EXCEPTION_NOT_REQUESTED` (HTTP 409); the `requesting_physician_id` must differ from the `supervisor_id`, else `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 400); and the `clinical_justification` must again meet its 40-character minimum, else `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400). On success the exception moves to `SUPERVISOR_REVIEW` and the system evaluates the domain-B condition, setting `evaluated_domain_b` to true exactly when the granting physician's DIRECTION_B_TAKE_HOME_READINESS score has cleared the applicable stability floor.

The medical director's decision is the third act and is available from `SUPERVISOR_REVIEW` only, else `ERR_EXCEPTION_NOT_AWAITING_SUPERVISOR` (HTTP 409). A denial moves the exception to `DENIED` and does nothing else; `DENIED` and `REVOKED` are this entity's terminal statuses. A grant requires three conditions beyond the state check. The `evaluated_domain_b` flag must be true, else the grant is refused with `ERR_STABILITY_BELOW_THRESHOLD` (HTTP 422) — a director cannot grant an exception on a patient whose readiness never cleared the floor. The `granted_carries` must not exceed the applicable carry-table cap, which for the exception path is the larger of the time-in-treatment allowance and the phase allowance for the patient's current phase, else `ERR_EXCEPTION_CARRIES_EXCEED_CAP` (HTTP 422) — the nested maximum is what lets an exception lift the patient to whichever table treats them more generously, so a `MAINTENANCE` patient at a low tenure is bounded by the phase table's allowance rather than the time table's. And the separation-of-duties rule applies again as a global check, so the deciding director may not be the requesting physician (§2.1). Note also that segregation of duties is enforced not only by the exception's own state machine but by the global validation at priority 3, which compares the acting identifier against every physician, supervisor and witness identifier the request nominates.

A grant triggers the exception cap calculation, which is a nested minimum-and-maximum rather than a plain minimum. The system reads the time-in-treatment table allowance for the patient's tenure and the phase table allowance for the patient's current phase, computes the pool cap as the integer floor of half of the program's available carries, floored at zero, and then sets the exception cap to the smallest of three numbers: the exception's `requested_carries`, the larger of the phase allowance and the time allowance, and the pool cap. The nested maximum of the two table figures is precisely what lets an exception lift a patient to whichever table treats them more generously, and the outer minimum with the pool cap is precisely what stops an exception from draining the program. That cap becomes the exception's `granted_carries`, and the linked privilege's `approved_carries` and `eligible_carry_cap` are set to the same figure.

The grant then cascades into the privilege. The privilege whose `exception_id` equals this exception, and whose decision is `DENIED`, moves to `APPROVED_WITH_EXCEPTION`; its `evaluation_basis` becomes `PHASE_STABILITY`, recording that the phase table was the one read; `expires_on` is stamped with the withdrawal-report expiration date; and `exception_id` is set to the exception's identifier. Take-home dose rows are synthesized for each of the first `granted_carries` open days, with their `ordered_mg` summed into `carried_issued_mg`. The patient's `treatment_phase` is unchanged by the grant, but the take-home readiness channel is recomputed. The exception itself becomes `GRANTED`.

An exception may be revoked by a `MedicalDirector` from `GRANTED` only, else `ERR_EXCEPTION_NOT_GRANTED` (HTTP 409). Revocation moves the exception to `REVOKED` and, as a second hop, moves the linked privilege — the one whose decision is `APPROVED_WITH_EXCEPTION` — to `REVOKED`. Every take-home dose row for that privilege still in `SCHEDULED` is cancelled, and the sum of their `ordered_mg` is added to the carry ledger's `carried_voided_mg`. This is the mechanism that keeps the milligram conservation identity balanced when an exception is withdrawn after doses have already been issued against it.

### 3.10. Revocation, Diversion and Program Suspension

A granted privilege can be revoked by two distinct routes, and both produce the same cascade. A `MedicalDirector` or a `RegulatoryAuditor` may revoke directly, or the system may revoke automatically when the patient's `diversion_standing` becomes `CONFIRMED_DIVERSION`. Either way the privilege must currently be `APPROVED` or `APPROVED_WITH_EXCEPTION`, else `ERR_PRIVILEGE_NOT_ACTIVE` (HTTP 409); on the automatic route the patient's diversion standing must be `CONFIRMED_DIVERSION`, which is the condition that fires the revocation.

Revocation of a privilege is not a single field write. The decision becomes `REVOKED`, `freed_carries` is set to the privilege's `approved_carries` so the program pool can reclaim the slots, and `approved_carries` is reset to 0. Every take-home dose row belonging to this privilege that is still `SCHEDULED` is cancelled, and the sum of those rows' `ordered_mg` is added to the patient's `carried_voided_mg`. The patient's carry ledger `carries_used` is reduced by the number of cancelled take-home dose rows — floored at 0, so that a revocation which cancels more doses than the ledger records cannot drive the counter negative — and the patient's own `carries_used` field is set to the ledger value. The patient's `treatment_phase` is reset to `INDUCTION`. And, as a third hop, each cancelled take-home dose's referenced lot, named by its `inventory_lot_id`, is moved to `QUARANTINED`, removing it from the selector pool for everyone.

That third hop is the depth-three cascade from diversion confirmation down through privilege, dose and finally lot. Its purpose is custody: medication that was drawn and set aside for a patient now under confirmed diversion investigation is not returned to general stock, it is held out of circulation. The quarantine is sticky in the sense that it requires an explicit release, and the release returns the lot to `RECEIVED` — note that it returns to `RECEIVED` rather than to `IN_USE`, so the lot must re-enter use through the ordinary first-transaction path.

Revoking an exception-backed privilege carries one additional step. When the privilege being revoked is `APPROVED_WITH_EXCEPTION`, the `TakeHomeException` rows referenced by that privilege with status `GRANTED` are themselves moved to `REVOKED`. A privilege and the exception that authorised it therefore stay in lockstep: a revoked privilege cannot leave a live exception behind it.

The diversion case itself is the regulator's instrument, driven by a `RegulatoryAuditor`. A case is opened against a patient with a `program_id`, `patient_id`, an optional `related_dose_dispense_id` naming the dose that raised it, a `detection_source` of `COUNT_MISMATCH`, `URINE_SCREEN`, `WITNESS_REPORT` or `GUEST_CLINIC_REPORT`, and a `severity` of `MINOR`, `MAJOR` or `CRITICAL`; it begins `OPEN` and its opening recomputes the program's open case count and reevaluates the posture ladder. Beginning review moves the case to `UNDER_REVIEW` and sets the patient's `diversion_standing` to `UNDER_INVESTIGATION` — note this alone does not revoke anything, it merely warns the system and penalises the patient's readiness channel by ten points. Confirmation is the heavy step: the case moves to `CONFIRMED` and stamps `confirmed_at`, the patient's `diversion_standing` becomes `CONFIRMED_DIVERSION`, the patient's `risk_score_points` is increased by 25.0 with the tier recut, and every privilege the patient holds whose decision is `APPROVED` or `APPROVED_WITH_EXCEPTION` is revoked — the first hop of the depth-three cascade. Confirmation requires an `outcome_summary` present and at least 20 characters long, else `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400). The open case count and the posture ladder are recomputed on the confirmation.

A case that is not substantiated moves to `UNSUBSTANTIATED` and clears the patient's `diversion_standing` back to `CLEAR`, again recomputing the case count and posture. Closure is available from `UNSUBSTANTIATED` or `CONFIRMED`, moving the case to `CLOSED` — a case still `OPEN` or `UNDER_REVIEW` cannot be closed, and the attempt yields `ERR_DIVERSION_CASE_NOT_CLOSABLE` (HTTP 409) — and closing a `CONFIRMED` case recomputes the program's open case count and the posture ladder, because reducing the open count is what can move a restricted program back toward `NORMAL`. `CLOSED` is the terminal status of this entity; `CONFIRMED` and `UNSUBSTANTIATED` are penultimate, from which only closure follows.

Program suspension is the regulator's nuclear option and is available only to a `RegulatoryAuditor`. Suspending a program that is already `SUSPENDED` is refused with `ERR_PROGRAM_ALREADY_SUSPENDED` (HTTP 409). A successful suspension forces the posture to `FROZEN` with reason `PROGRAM_SUSPENDED_BY_REGULATOR` and then reaches into four collections at once: every dose for the program still in `SCHEDULED`, `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` is cancelled; every privilege for the program in `PENDING_REVIEW` whose `timetable_reconciled` is true is denied with `denial_reason_code` set to `PROGRAM_POSTURE_RESTRICTED` and `hold_ledger_delta` set to 0; and every guest dosing arrangement whose `receiving_program_id` is this program and whose status is `PENDING_RECEIVING_ACK` or `ACTIVE` is cancelled. Resuming requires the program to actually be `SUSPENDED`, else `ERR_PROGRAM_NOT_SUSPENDED` (HTTP 409); it resets posture to `NORMAL` with a null reason code and then recomputes the open diversion case count, so that if the program still has an open case the posture ladder immediately moves it back to `RESTRICTED`. Resumption is therefore not a clean slate — it is a return to whatever posture the program's current facts justify.

Two further safety rules cut across all of this. A patient whose `diversion_standing` is `CONFIRMED_DIVERSION` may not receive a carry and may not be admitted to a new program, and the same refusal guards five operations: diagnosis confirmation, privilege evaluation, exception decision, dose scheduling and guest-dosing transmission. In all five the rejection is `ERR_DIVERSIONS_OR_FINDINGS_OPEN` (HTTP 403). And a patient with an open diversion case — one in `OPEN` or `UNDER_REVIEW` status — is blocked from admission confirmation with `ERR_PATIENT_FLAGGED_FOR_DIVERSION` (HTTP 403). The distinction between the two is the difference between a suspicion and a finding: an open case blocks admission but leaves existing privileges intact, while a confirmation revokes privileges outright.

### 3.11. Guest Dosing and Continuity of Care Across Clinics

A patient who travels must still be dosed, and the program that doses them is not the program that knows them. The guest dosing arrangement is the instrument that bridges the two, and it exists to make the receiving clinic's authority bounded, single-purpose and revocable.

A `ProgramAdministrator` opens an arrangement by supplying the `patient_id`, a `receiving_program_id` naming the clinic the patient will dose at while travelling, the `travel_start_date` and `travel_end_date` that bound the guest window inclusive at both ends, and an `expected_patient_version` that must match the patient's current version (§2.10). The `originating_program_id` is not supplied by the client at all — it is taken from the patient's own admitting `program_id`. The arrangement begins in `DRAFT` status with `token_consumed` false, `receiving_acknowledged_at` null and `dose_authorization_token` unset; the token is minted at transmission, not at creation.

Transmission is the step that puts seven conditions to the test at once, and its ordering reflects the priority ladder of §2.11. The arrangement must be `DRAFT`, else `ERR_ARRANGEMENT_NOT_DRAFT` (HTTP 409). The originating program recorded on the arrangement must equal the patient's current `program_id`, else `ERR_ARRANGEMENT_PROGRAM_MISMATCH` (HTTP 409) — a stale arrangement referring to a clinic the patient has since left cannot be transmitted. The `receiving_program_id` must differ from the `originating_program_id`, else `ERR_SAME_PROGRAM_GUEST_DOSING` (HTTP 409); a patient cannot guest-dose at their own clinic, because the entire purpose of the mechanism is a different dispensing location. The receiving program must have `guest_dosing_enabled` true, else `ERR_GUEST_DOSING_NOT_ENABLED` (HTTP 409). The patient must be `ACTIVE`, else `ERR_PATIENT_NOT_ACTIVE` (HTTP 409). The receiving program's posture must be `NORMAL`, else `ERR_PROGRAM_OPERATIONALLY_BLOCKED` (HTTP 409). And the receiving program must have an open clinic day whose window overlaps the requested travel window, else `ERR_NO_OVERLAPPING_VISIT_WINDOW` (HTTP 409) — an arrangement to dose at a clinic that is closed for the whole trip is not an arrangement. Note that the origin-versus-receiving clinic checks run before the two safety gates in the global ordering, so a request that both mismatches the originating clinic and points at a program with guest dosing disabled reports the mismatch first.

On success, two things are written. The arrangement receives a server-issued one-time `dose_authorization_token`, and its `authorized_mg` is set to the patient's active dose order's `ordered_daily_mg` — the receiving clinic is authorised to give exactly what the prescribing clinic ordered, no more. The status becomes `PENDING_RECEIVING_ACK`.

Acknowledgement belongs to the receiving clinic and is performed by a `Nurse`. The arrangement must be `PENDING_RECEIVING_ACK`, else `ERR_ARRANGEMENT_NOT_PENDING_ACK` (HTTP 409), and the acting nurse's `program_id` must match the `receiving_program_id`, else `ERR_NURSE_NOT_IN_PROGRAM` (HTTP 403) — the acknowledgement is meaningless if issued by anyone other than the clinic that will be dosing. On success the status becomes `ACTIVE` and `receiving_acknowledged_at` is stamped with the logical clock.

The receiving clinic may instead reject, which is available from `PENDING_RECEIVING_ACK` only, else `ERR_ARRANGEMENT_NOT_PENDING_ACK` (HTTP 409); rejection moves the arrangement to `REJECTED` and clears the `dose_authorization_token` to null, so that a token which was minted but never honoured cannot be redeemed later.

Once an arrangement is `ACTIVE`, it becomes the authority under which the receiving clinic records observed doses. A dose is scheduled with the `source_type` set to `GUEST_OBSERVED` and the arrangement's identifier carried in the `guest_arrangement_id` field. Redeeming the token is guarded by three conditions, all HTTP 409. The token must be present, must have been minted, and must belong to the arrangement in question, else `ERR_GUEST_TOKEN_INVALID`. It must not have been redeemed already, else `ERR_GUEST_TOKEN_ALREADY_CONSUMED`. And the logical clock must fall within the inclusive travel window from `travel_start_date` through `travel_end_date`, else `ERR_GUEST_DOSING_WINDOW_CLOSED`. The window is therefore half-open in the sense that matters for slot occupancy but closed at both of its own ends: a dose on the start date is permitted and a dose on the end date is permitted, and a dose the day after the end date is not. Setting `token_consumed` true records the redemption.

Closing an arrangement is how the originating clinic reclaims it, and it is available to a `ProgramAdministrator` from `ACTIVE` only, else `ERR_ARRANGEMENT_NOT_ACTIVE` (HTTP 409). It also requires the logical clock's date to have moved past `travel_end_date`, not merely to it, else `ERR_TRAVEL_WINDOW_NOT_ENDED` (HTTP 409); the same travel-window overlap condition also guards dose scheduling, so a dose cannot be scheduled into a window the arrangement does not cover. A successful close stamps `token_consumed` true and moves the arrangement to `COMPLETED`. Cancellation is the escape hatch, available from `DRAFT`, `PENDING_RECEIVING_ACK` or `ACTIVE`, and refused with `ERR_ARRANGEMENT_NOT_CANCELLABLE` (HTTP 409) once the arrangement is terminal. `COMPLETED`, `REJECTED` and `CANCELLED` are the three terminal statuses for this entity.

Arrangements are also swept up by broader events, and it is worth naming those because they are easy to forget. Discharging a patient cancels every arrangement for that patient still in `DRAFT`, `PENDING_RECEIVING_ACK` or `ACTIVE`. Suspending a program cancels every arrangement whose `receiving_program_id` is that program and whose status is `PENDING_RECEIVING_ACK` or `ACTIVE`. And because any transmission or acknowledgement for a patient advances that patient's version, a second arrangement opened against a stale view of the same patient is rejected at creation with `ERR_STALE_VERSION` (HTTP 412) before any of the transmission conditions are even examined.

### 3.12. Inventory Reconciliation, Variance and Write-Off

The medication ledger is where the program's custody of controlled substances becomes auditable, and it is deliberately intolerant of approximation.

Movements against a lot are recorded as `InventoryTransaction` rows. A row may be created directly by a `ProgramAdministrator` or a `Nurse` supplying a `lot_id`, a `transaction_type`, a `quantity_mg`, and optionally a `patient_id`, a `dose_dispense_id` and a `witness_staff_id`. The `transaction_type` is one of `RECEIPT`, `DISPENSE`, `WASTE`, `RETURN`, `ADJUSTMENT` or `DESTRUCTION`. The `quantity_mg` is signed, and the sign convention is part of the contract: it is positive for `RECEIPT` and `RETURN`; negative for `DISPENSE`, `WASTE` and `DESTRUCTION`; and may be either positive or negative for `ADJUSTMENT`. The `patient_id` and `dose_dispense_id` are null for program-level movements such as a receipt or a destruction. A `witness_staff_id` is required for `WASTE` and `DESTRUCTION` movements, and must differ from the acting user, else `ERR_WITNESS_REQUIRED` (HTTP 422). New rows begin in `RECORDED`, and the lot's `running_on_hand_mg` is recomputed after each one. The `reconciliation_period` is derived as the year and month of the logical clock at recording time, and `residual_variance_mg` and `cumulative_write_off_mg` begin at 0. The row's `status` moves among `RECORDED`, `RECONCILED`, `FLAGGED` and `VOIDED`.

Receiving a lot is the first movement of any lot's life and sets `running_on_hand_mg` equal to the received quantity. It requires a `program_id`, a `medication`, a `lot_number`, an `expiration_date` and a `quantity_received_mg`, and accepts optional `dose_potency_mg_per_unit` and `reusable_for_take_home` flags. Destroying an emptied lot appends a `DESTRUCTION` movement with a `quantity_mg` of 0, reflecting the fact that nothing remained to debit.

Closing a period is the reconciliation act, and it is performed by a `ProgramAdministrator` or a `RegulatoryAuditor` against a `period` expressed as a year and month, with the `program_id` supplied in the request body. The calculation walks the program's lots in ascending order of `created_at` then `id`, and for each lot whose status is not `QUARANTINED` at period end it computes a reconciled on-hand figure as the lot's `quantity_received_mg` plus the sum of `quantity_mg` over that lot's rows whose status is `RECONCILED` and whose `created_at` is at or before the period end. It then subtracts an expired quantity: the magnitude of milligrams already debited for that lot by `DESTRUCTION` or `ADJUSTMENT` rows dated on or after the lot's `expiration_date`. The difference is the delivered on-hand figure for the lot.

Only `RECONCILED` rows participate in the reconciled balance; `RECORDED`, `FLAGGED` and `VOIDED` rows are excluded from it and are counted only in the delivered balance. This is the third conservation identity the system maintains: reconciled on-hand equals the received quantity plus the sum of `quantity_mg` over the reconciled rows, lot by lot.

The program variance is stated as the sum of the delivered on-hand figures across lots minus the sum of the reconciled on-hand figures. The tolerance is the larger of 50.0 milligrams and two percent of the period's total dispensed milligrams. The period is flagged when the absolute variance is strictly greater than that tolerance; a variance exactly equal to the tolerance is not flagged, and the boundary is deliberately exclusive on the flagging side. When the period is flagged, an `ADJUSTMENT` row is appended with status `FLAGGED` and the program's `latest_inventory_variance_mg` is stored with the period variance.

The write-off is computed against a floor. The write-off amount is the larger of zero and the negated variance reduced by the program's `cumulative_write_off_mg`; the program's cumulative figure is then increased by the write-off, with the accumulated total held at or above zero. As a worked instance: writing off an adjustment for a variance of -700.00 against a cumulative write-off of 200.00 produces a write-off of 500.00, moves the cumulative figure to 700.00, and leaves `latest_inventory_variance_mg` at 0.00. Closing the period also moves the period's transaction rows to `RECONCILED`, stores the program variance on the program row, and reevaluates the posture ladder — so a period close that leaves a variance above 500.0 will, by itself, restrict the program.

The audit worksheet reading reports the same figures in a different variant, and the difference is a deliberate trap. The worksheet does not net expired stock out, so its delivered on-hand figure equals its reconciled on-hand figure and its reported variance omits the expired-lot term entirely. The two variants therefore differ by exactly the expired milligrams, and an implementer who serves one variant's arithmetic for the other will produce a discrepancy the tests can measure directly. The reconciliation response itself reports the delivered variant and returns the period, the reconciled and delivered on-hand figures, the program variance, the tolerance, the flagged boolean and the write-off amount.

### 3.13. Inspection Readiness, Findings and Corrective Action

A regulator arrives without warning, and the system's answer to that is a live readiness score rather than a report assembled after the fact.

An inspection is announced by a `RegulatoryAuditor` with a `program_id`, an `inspecting_agency`, a `scheduled_date` and an `inspection_type` of `ROUTINE`, `COMPLAINT_DRIVEN` or `DIVERSION_FOCUSED`; it begins in `SCHEDULED`. Beginning the inspection requires the inspection to be `SCHEDULED`, else `ERR_INSPECTION_NOT_SCHEDULED` (HTTP 409), moves it to `IN_PROGRESS` and recomputes the readiness score against the program's live dossier state. Findings are recorded by the same role against an inspection, each carrying the `inspection_id` of the inspection it belongs to, a `requirement_code` drawn from `DOSING_LOG_COMPLETE`, `WASTE_WITNESSED`, `COUNSELING_CADENCE_MET`, `PLAN_REVIEW_CURRENT`, `INVENTORY_RECONCILED` and `DUAL_ENROLLMENT_SCREENED`, and a `severity` of `MINOR`, `MAJOR` or `CRITICAL`. A finding begins `OPEN`, and the owning inspection's `finding_count` and the finding's `corrected_at` reflect its progress; a finding moves to `CORRECTED` or `WAIVED` over its life, and only `OPEN` findings carry any penalty.

The readiness score starts at 100.0 and is reduced by a series of weighted penalties. Each open `CRITICAL` finding costs 12.0 points, each open `MAJOR` finding 6.0, and each open `MINOR` finding 2.0. Each diversion case for the program in `OPEN` or `UNDER_REVIEW` status costs 10.0 points. A program whose `latest_inventory_variance_mg` exceeds 500.0 loses 15.0 points. A program with at least one patient whose `counseling_standing` is `COUNSELING_DEFICIENT` loses 20.0 points. And a program with at least one privilege whose decision is `APPROVED` or `APPROVED_WITH_EXCEPTION` and whose `expires_on` falls on or before the logical clock's date loses 10.0 points — a lapsed carry is a finding in waiting. Findings whose status is `WAIVED` or `CORRECTED` contribute nothing. The score is rounded half up to one decimal place, and the `readiness_tier` is cut from it: `READY` at 85.0 or above, `NEEDS_ATTENTION` at 60.0 or above (and below 85.0), and `NOT_READY` below 60.0. The readiness reading returns the score, the tier, the count of open critical findings and the count of open diversion cases together, so that a regulator can see which term dragged the score down.

Completing an inspection is the one transition in this area with a hard clinical prerequisite: no `CRITICAL` finding belonging to the inspection may still be `OPEN`. An inspection in `IN_PROGRESS` with an open critical finding is refused with `ERR_CRITICAL_FINDING_OPEN` (HTTP 409), and an inspection in any other status is refused with `ERR_INSPECTION_NOT_IN_PROGRESS` (HTTP 409). A successful completion moves the inspection to `COMPLETED` and recomputes `finding_count` as the count of findings recorded against it. Cancellation is available from `SCHEDULED` only, else `ERR_INSPECTION_NOT_SCHEDULED` (HTTP 409), and moves the inspection to `CANCELLED`.

Corrective actions are the program's remedy and live at the program level rather than the inspection level, which is why a `finding_id` is optional: an action may be self-initiated. A `ProgramAdministrator` opens one with a `program_id`, an optional `finding_id`, a `severity`, a `plan_text` of at least 20 characters, and a `due_date`. A `plan_text` shorter than its minimum is refused with `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 400). The action begins `OPEN`. When its severity is `CRITICAL`, opening it recomputes the program's open critical finding count and reevaluates the posture ladder — so a critical corrective action can restrict the program the moment it is opened. Implementation moves the action from `OPEN` to `IMPLEMENTED` and is refused with `ERR_ACTION_NOT_OPEN` (HTTP 409) otherwise; verification moves it from `IMPLEMENTED` to `VERIFIED_CLOSED` and is refused with `ERR_ACTION_NOT_IMPLEMENTED` (HTTP 409) otherwise, and it recomputes the open critical finding count before reevaluating posture. Verification is the regulator's act, implementation the administrator's, which is the segregation that makes closure meaningful. Cancellation is available from `OPEN`, by a `MedicalDirector`, and likewise recomputes the open critical finding count and posture. `VERIFIED_CLOSED` and `CANCELED` are terminal.

The posture ladder is therefore fed from three separate directions, and it is worth restating them together: diversion cases change the open case count, corrective actions change the open critical finding count, and period-close reconciliation changes the inventory variance. All three converge on the same five-branch ladder of §2.6, and any one of them can move a program from `NORMAL` to `RESTRICTED` without a client ever touching the program resource.

### 3.14. Administrative Discharge, Withdrawal Completion and the Logical Clock

A patient leaves the program by one of two doors, and neither is reversible. Administrative discharge is a `Physician`'s act and requires the patient's status to be one of `ADMITTED`, `ACTIVE` or `SUSPENDED_NON_COMPLIANT` — a patient already in a terminal status yields `ERR_PATIENT_NOT_DISCHARGEABLE` (HTTP 409). The request must carry a `reason_code` of `TRANSFER`, `REGULATORY`, `NON_PAYMENT` or `BEHAVIORAL`; anything else is refused with `ERR_INVALID_DISCHARGE_REASON` (HTTP 400). A discharge sweeps the patient's open work: `ACTIVE` dose orders become `DISCONTINUED`; doses still in `SCHEDULED`, `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED` are cancelled; privileges with decision `APPROVED` or `APPROVED_WITH_EXCEPTION` are revoked with `freed_carries` set to their `approved_carries`; and guest arrangements still in `DRAFT`, `PENDING_RECEIVING_ACK` or `ACTIVE` are cancelled.

Completion of a medically managed withdrawal is the other door, and it is a `MedicalDirector`'s act. It requires the patient to be `ACTIVE`, else `ERR_PATIENT_NOT_ACTIVE` (HTTP 409); the patient's `treatment_phase` must be `MEDICAL_WITHDRAWAL`, else `ERR_NOT_IN_WITHDRAWAL_PHASE` (HTTP 409); and no dose for the patient may remain in `SCHEDULED`, `ARRIVED_AT_CLINIC` or `NURSE_VERIFIED`, else `ERR_OPEN_DOSES_REMAIN` (HTTP 409) — a withdrawal is not complete while a dose is still pending. On success the patient moves to `COMPLETED_WITHDRAWAL`, `ACTIVE` dose orders become `DISCONTINUED`, and privileges with decision `APPROVED` or `APPROVED_WITH_EXCEPTION` are revoked with `freed_carries` set to their `approved_carries`. `ADMINISTRATIVELY_DISCHARGED` and `COMPLETED_WITHDRAWAL` are the two terminal statuses of the patient machine.

Underpinning every temporal rule in this document is a logical clock rather than the wall clock. The server's clock begins at exactly 2026-09-01T00:00:00Z at startup and never tracks real time; the only way to move it is the admin-only test-driving capability, which a `ProgramAdministrator` or a `RegulatoryAuditor` invokes by supplying a `to_iso8601` instant and receives back a `logical_clock_utc` confirmation. Advancing the clock has no eager side effects beyond making every time-derived computation produce a new answer on its next read, which is precisely why streaks, denial windows, cadence windows, travel windows, lot expiration and readiness lapses can all be driven deterministically by a test or an operator. An implementer who reads the host clock instead will find that no window boundary can be exercised.

### 3.15. Staff Registration and Role Assignment

Staff are persisted before they act. A `ProgramAdministrator` registers a staff member by supplying a `full_name` and a `staff_role`, and for the clinical roles a `license_number`. The `staff_role` is one of `PHYSICIAN`, `NURSE`, `COUNSELOR`, `MEDICAL_DIRECTOR`, `PROGRAM_ADMIN`, or `REGULATOR`. A `license_number` is required when the role is `PHYSICIAN`, `NURSE` or `MEDICAL_DIRECTOR`, and there is no requirement to supply one for the other roles. A `program_id` is supplied for staff who work at a clinic and omitted for regulator accounts. Newly registered staff are active.

Registration is not the same as authorization. The persisted `staff_role` describes what a person is; the `X-User-Role` header describes what capacity they are acting in for a given request, and the role enumeration used to authorize a request is the six-member role set of §2.1 rather than the `staff_role` enumeration above. The two vocabularies overlap in spelling for `PHYSICIAN`, `NURSE`, `COUNSELOR`, `MEDICAL_DIRECTOR` and `REGULATOR`-versus-`RegulatoryAuditor`, and diverge for the administrator, whose `staff_role` is `PROGRAM_ADMIN` while the acting role is `ProgramAdministrator`. An implementer must not conflate the two lists: `staff_role` is a field on a persisted user row, while `X-User-Role` drives every authorization decision in §2.1.

A staff member is never deleted. Deactivation — flipping `is_active` to false — keeps historical references resolvable, which matters because dose rows carry a `verification_staff_id`, dose dispense payloads carry a `witness_staff_id`, exceptions carry a `requesting_physician_id` and a `supervisor_id`, plan reviews carry a `reviewer_physician_id`, counseling sessions carry a `counselor_staff_id` and diversion cases carry an `opened_by_user_id`. All of these are opaque staff identifiers rather than resolved relationships, and all of them must remain readable after a departure. A related consequence falls out of §2.1: because a witness identifier is compared against the acting identifier for inequality and not resolved to a `User` row, the witness check works identically whether the witness is a registered physician, a registered nurse, or an administrator acting in an opaque capacity.

## 4. Endpoint Definitions

Operations that bring a new stand-alone resource into existence — a program, a user, a patient, a dose order, a scheduled dose, a privilege request, an exception request, a guest arrangement, a lot, an inventory movement, a counseling session, a plan review, an inspection, a finding, a corrective action or a diversion case — return HTTP 201. Operations that modify an existing resource, including the whole family of state-transition endpoints, return HTTP 200. The same rule applies to sub-resource collections: adding a distinct new resource to an existing parent's collection is a creation and returns 201.

The table below states only the routing contract. Request bodies, response payloads, validation ordering, side effects and the exact error each failure produces are specified in §2 and §3; an implementer must reconstruct them from the narrative there rather than from this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/otp/_clock/set_current_utc` | Set the logical clock from a supplied instant | ProgramAdministrator, RegulatoryAuditor |
| POST | `/otp/programs` | Create a treatment program | ProgramAdministrator |
| GET | `/otp/programs` | List programs | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/programs/{id}` | Read a program including its posture | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/programs/{id}/suspend` | Suspend a program | RegulatoryAuditor |
| POST | `/otp/programs/{id}/resume` | Resume a suspended program | RegulatoryAuditor |
| POST | `/otp/programs/{id}/carry-quota` | Open the program's carry quota ledger | ProgramAdministrator |
| GET | `/otp/programs/{id}/carry-quota` | Read the carry quota ledger as a one-element array | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/users` | Register a staff member | ProgramAdministrator |
| GET | `/otp/users` | List staff members | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/users/{userId}` | Read a staff member | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/patients` | Register a patient into a program | ProgramAdministrator, Physician |
| GET | `/otp/patients` | List patients | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/patients/{patientId}` | Read a patient | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/patients/{patientId}/confirm-diagnosis` | Confirm the diagnosis and admit the patient | Physician |
| POST | `/otp/patients/{patientId}/reinstate` | Reinstate a suspended patient | MedicalDirector |
| POST | `/otp/patients/{patientId}/discharge` | Discharge the patient administratively | Physician |
| POST | `/otp/patients/{patientId}/complete-withdrawal` | Complete a medically managed withdrawal | MedicalDirector |
| PATCH | `/otp/patients/{patientId}/treatment-phase` | Move the patient between treatment phases | Physician, MedicalDirector |
| GET | `/otp/patients/{patientId}/time-in-treatment-tracker` | Read the phase journal tracker and dual-enrollment flag | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/dose-orders` | Create a dose order | Physician |
| GET | `/otp/dose-orders` | List dose orders | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/dose-orders/{doseOrderId}` | Read a dose order | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/dose-orders/{doseOrderId}/activate` | Activate a dose order | Physician |
| POST | `/otp/dose-orders/{doseOrderId}/suspend` | Suspend a dose order | Physician |
| POST | `/otp/dose-orders/{doseOrderId}/discontinue` | Discontinue a dose order | Physician |
| POST | `/otp/dose-dispenses` | Schedule a dose | Nurse, ProgramAdministrator |
| GET | `/otp/dose-dispenses` | List doses | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/dose-dispenses/{doseId}` | Read a dose | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/dose-dispenses/{doseId}/check-in` | Check the patient in at the clinic | Nurse |
| POST | `/otp/dose-dispenses/{doseId}/verify` | Verify patient identity against the frozen order | Nurse |
| POST | `/otp/dose-dispenses/{doseId}/dispense` | Thread the dose from inventory | Nurse |
| POST | `/otp/dose-dispenses/{doseId}/complete` | Close out a dispensed dose | Nurse |
| POST | `/otp/dose-dispenses/{doseId}/refuse` | Record a patient refusal | Nurse |
| POST | `/otp/dose-dispenses/{doseId}/cancel` | Cancel a dose before completion | Nurse, Physician |
| POST | `/otp/dose-dispenses/{doseId}/reschedule` | Reschedule a non-terminal dose | Nurse, ProgramAdministrator |
| POST | `/otp/dose-dispenses/{doseId}/mark-missed` | Record an overdue dose as not taken | Nurse, Physician |
| GET | `/otp/dose-dispenses/{doseId}/charge-preview` | Read the dose tariff in both rounding variants | ProgramAdministrator, RegulatoryAuditor |
| POST | `/otp/take-home-privileges` | Open a take-home privilege request | MedicalDirector |
| GET | `/otp/take-home-privileges` | List privileges | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/take-home-privileges/{privilegeId}` | Read a privilege including its eligible carry cap | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/take-home-privileges/{privilegeId}/evaluate` | Evaluate a held or denied privilege | MedicalDirector |
| POST | `/otp/take-home-privileges/{privilegeId}/revoke` | Revoke a granted privilege | MedicalDirector, RegulatoryAuditor |
| POST | `/otp/take-home-exceptions` | Open an exception request against a denied privilege | Physician |
| GET | `/otp/take-home-exceptions` | List exceptions | ProgramAdministrator, Physician, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/take-home-exceptions/{exceptionId}` | Read an exception | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/take-home-exceptions/{exceptionId}/route` | Route an exception to the medical director | Physician |
| POST | `/otp/take-home-exceptions/{exceptionId}/decision` | Grant or deny an exception | MedicalDirector |
| POST | `/otp/take-home-exceptions/{exceptionId}/revoke` | Revoke a granted exception | MedicalDirector |
| GET | `/otp/take-home-carry-ledgers` | List carry ledgers | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/take-home-carry-ledgers/{ledgerId}` | Read a carry ledger including the conserved quantities | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/inventory-lots` | Receive a medication lot | ProgramAdministrator |
| GET | `/otp/inventory-lots` | List lots | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/inventory-lots/{lotId}` | Read a lot including expired and on-hand status | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/inventory-lots/{lotId}/quarantine` | Quarantine a lot | ProgramAdministrator, RegulatoryAuditor |
| POST | `/otp/inventory-lots/{lotId}/release-quarantine` | Release a quarantined lot | ProgramAdministrator |
| POST | `/otp/inventory-lots/{lotId}/destroy` | Destroy an emptied lot under witness | ProgramAdministrator |
| POST | `/otp/inventory-transactions` | Record a manual inventory movement | ProgramAdministrator, Nurse |
| GET | `/otp/inventory-transactions` | List inventory movements | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/inventory-transactions/{transactionId}` | Read one inventory movement | ProgramAdministrator, Nurse, RegulatoryAuditor |
| POST | `/otp/inventory-reconciliations/{period}/close` | Close a reconciliation period | ProgramAdministrator, RegulatoryAuditor |
| GET | `/otp/inventory-reconciliations` | Read the reconciliation worksheet for a period | ProgramAdministrator, RegulatoryAuditor |
| POST | `/otp/counseling-sessions` | Schedule a counseling session | Counselor, ProgramAdministrator |
| GET | `/otp/counseling-sessions` | List counseling sessions | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/counseling-sessions/{sessionId}` | Read a counseling session | ProgramAdministrator, Physician, Nurse, Counselor, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/counseling-sessions/{sessionId}/complete` | Complete a session with attended minutes | Counselor |
| POST | `/otp/counseling-sessions/{sessionId}/no-show` | Record a counseling no-show | Counselor |
| POST | `/otp/treatment-plan-reviews` | Record a treatment plan review | Physician, MedicalDirector |
| GET | `/otp/treatment-plan-reviews` | List plan reviews | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/treatment-plan-reviews/{reviewId}` | Read a plan review | ProgramAdministrator, Physician, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/guest-dosing-arrangements` | Open a guest dosing arrangement | ProgramAdministrator |
| GET | `/otp/guest-dosing-arrangements` | List guest arrangements | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/guest-dosing-arrangements/{arrangementId}` | Read a guest arrangement including its token | ProgramAdministrator, Physician, Nurse, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/guest-dosing-arrangements/{arrangementId}/transmit` | Transmit the arrangement and mint the token | ProgramAdministrator |
| POST | `/otp/guest-dosing-arrangements/{arrangementId}/acknowledge` | Acknowledge inbound guest dosing | Nurse |
| POST | `/otp/guest-dosing-arrangements/{arrangementId}/reject` | Reject inbound guest dosing | Nurse |
| POST | `/otp/guest-dosing-arrangements/{arrangementId}/close` | Close a guest arrangement after the travel window | ProgramAdministrator |
| POST | `/otp/guest-dosing-arrangements/{arrangementId}/cancel` | Cancel a guest arrangement | ProgramAdministrator |
| POST | `/otp/compliance-inspections` | Announce an inspection | RegulatoryAuditor |
| GET | `/otp/compliance-inspections` | List inspections | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/compliance-inspections/{inspectionId}` | Read an inspection including its readiness score | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/compliance-inspections/{inspectionId}/readiness` | Compute readiness score and tier on demand | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/compliance-inspections/{inspectionId}/begin` | Begin an inspection | RegulatoryAuditor |
| POST | `/otp/compliance-inspections/{inspectionId}/complete` | Complete an inspection | RegulatoryAuditor |
| POST | `/otp/compliance-inspections/{inspectionId}/cancel` | Cancel an announced inspection | RegulatoryAuditor |
| POST | `/otp/compliance-findings` | Record a compliance finding | RegulatoryAuditor |
| GET | `/otp/compliance-findings` | List findings | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/compliance-findings/{findingId}` | Read one compliance finding | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/corrective-actions` | Open a corrective action plan | ProgramAdministrator |
| GET | `/otp/corrective-actions` | List corrective actions | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/corrective-actions/{actionId}` | Read one corrective action | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/corrective-actions/{actionId}/implement` | Mark a corrective action implemented | ProgramAdministrator |
| POST | `/otp/corrective-actions/{actionId}/verify` | Verify closure of a corrective action | RegulatoryAuditor |
| POST | `/otp/corrective-actions/{actionId}/cancel` | Cancel a corrective action | MedicalDirector |
| POST | `/otp/diversion-cases` | Open a diversion case | RegulatoryAuditor, Nurse, ProgramAdministrator |
| GET | `/otp/diversion-cases` | List diversion cases | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| GET | `/otp/diversion-cases/{caseId}` | Read a diversion case | ProgramAdministrator, MedicalDirector, RegulatoryAuditor |
| POST | `/otp/diversion-cases/{caseId}/begin-review` | Begin review of a diversion case | RegulatoryAuditor |
| POST | `/otp/diversion-cases/{caseId}/confirm` | Confirm diversion | RegulatoryAuditor |
| POST | `/otp/diversion-cases/{caseId}/unsubstantiate` | Close a case as unsubstantiated | RegulatoryAuditor |
| POST | `/otp/diversion-cases/{caseId}/close` | Close a resolved diversion case | RegulatoryAuditor |

## 5. Error Code Catalogue

The catalogue below states each error's machine-readable identifier and the HTTP status it carries. The conditions that trigger each error are stated in the narrative sections that describe the operation it guards, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOSE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_DOSE_NOT_FOUND` | 404 Not Found |
| `ERR_PRIVILEGE_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEPTION_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_DIVERSION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_ARRANGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_USER_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_CARRY_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_ALREADY_SUSPENDED` | 409 Conflict |
| `ERR_PROGRAM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PATIENT_NOT_PENDING_ADMISSION` | 409 Conflict |
| `ERR_PATIENT_NOT_ADMITTED` | 409 Conflict |
| `ERR_PATIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PATIENT_NOT_DOSABLE` | 409 Conflict |
| `ERR_PATIENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PATIENT_NOT_DISCHARGEABLE` | 409 Conflict |
| `ERR_DOSE_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_DOSE_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_DOSE_ORDER_NOT_DISCONTINUABLE` | 409 Conflict |
| `ERR_DOSE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DOSE_NOT_ARRIVED` | 409 Conflict |
| `ERR_DOSE_NOT_VERIFIED` | 409 Conflict |
| `ERR_DOSE_NOT_DISPENSED` | 409 Conflict |
| `ERR_DOSE_NOT_REFUSABLE` | 409 Conflict |
| `ERR_DOSE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_TAKE_HOME_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_DOSE_ORDER_CHANGED` | 409 Conflict |
| `ERR_PRIVILEGE_NOT_PENDING` | 409 Conflict |
| `ERR_PRIVILEGE_NOT_DENIED` | 409 Conflict |
| `ERR_PRIVILEGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_REISSUE_SOURCE_NOT_REVOKED` | 409 Conflict |
| `ERR_EXCEPTION_NOT_REQUESTED` | 409 Conflict |
| `ERR_EXCEPTION_NOT_AWAITING_SUPERVISOR` | 409 Conflict |
| `ERR_EXCEPTION_NOT_GRANTED` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_PENDING_ACK` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ARRANGEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_LOT_NOT_QUARANTINABLE` | 409 Conflict |
| `ERR_LOT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_LOT_NOT_EMPTY` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_DIVERSION_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_DIVERSION_CASE_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_DIVERSION_CASE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_ACTION_NOT_OPEN` | 409 Conflict |
| `ERR_ACTION_NOT_IMPLEMENTED` | 409 Conflict |
| `ERR_CRITICAL_FINDING_OPEN` | 409 Conflict |
| `ERR_NOT_IN_WITHDRAWAL_PHASE` | 409 Conflict |
| `ERR_OPEN_DOSES_REMAIN` | 409 Conflict |
| `ERR_GUEST_TOKEN_ALREADY_CONSUMED` | 409 Conflict |
| `ERR_TRAVEL_WINDOW_NOT_ENDED` | 409 Conflict |
| `ERR_REINSTATEMENT_DENIAL_STREAK` | 409 Conflict |
| `ERR_PROGRAM_OPERATIONALLY_BLOCKED` | 409 Conflict |
| `ERR_PROGRAM_POSTURE_RESTRICTED` | 403 Forbidden |
| `ERR_DIVERSIONS_OR_FINDINGS_OPEN` | 403 Forbidden |
| `ERR_PATIENT_FLAGGED_FOR_DIVERSION` | 403 Forbidden |
| `ERR_DUAL_ENROLLMENT_DETECTED` | 409 Conflict |
| `ERR_WITNESS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STABILITY_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_SELF_REVIEW_FORBIDDEN` | 400 Bad Request |
| `ERR_NURSE_NOT_IN_PROGRAM` | 403 Forbidden |
| `ERR_PHYSICIAN_NOT_IN_PROGRAM` | 403 Forbidden |
| `ERR_GUEST_DOSING_NOT_ENABLED` | 409 Conflict |
| `ERR_COUNSELING_CADENCE_BREACHED` | 403 Forbidden |
| `ERR_ARRANGEMENT_PROGRAM_MISMATCH` | 409 Conflict |
| `ERR_SAME_PROGRAM_GUEST_DOSING` | 409 Conflict |
| `ERR_GUEST_TOKEN_INVALID` | 409 Conflict |
| `ERR_NO_OVERLAPPING_VISIT_WINDOW` | 409 Conflict |
| `ERR_GUEST_DOSING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_OUTSIDE_CLINIC_HOURS` | 409 Conflict |
| `ERR_NOT_AN_OPEN_DAY` | 409 Conflict |
| `ERR_NO_DOSE_CAPACITY` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_DOSE` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_LOT_QUARANTINED` | 409 Conflict |
| `ERR_DOSE_MASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PARTIAL_EXCEEDS_ORDERED` | 422 Unprocessable Entity |
| `ERR_DOSE_TITRATION_TOO_FAST` | 422 Unprocessable Entity |
| `ERR_DOSE_EXCEEDS_MEDICATION_CEILING` | 422 Unprocessable Entity |
| `ERR_INVALID_DISCHARGE_REASON` | 400 Bad Request |
| `ERR_INVALID_DIAGNOSIS_CODE` | 400 Bad Request |
| `ERR_JUSTIFICATION_TOO_SHORT` | 400 Bad Request |
| `ERR_EXCEPTION_CARRIES_EXCEED_CAP` | 422 Unprocessable Entity |
| `ERR_TIME_IN_TREATMENT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_TIMETABLE_LOOKAHEAD_FAILED` | 422 Unprocessable Entity |
| `ERR_ACTIVE_DENIAL_HISTORY` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_CARRY_QUOTA_EXHAUSTED` | 402 Payment Required |
| `ERR_INVENTORY_CEILING_EXCEEDED` | 402 Payment Required |
| `ERR_NO_ELIGIBLE_LOT` | 409 Conflict |