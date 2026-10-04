# Experience Rating API — Product Requirements Document

## 1. Introduction

Workers' compensation insurance depends on a trusted, centralized mechanism for measuring each employer's loss experience relative to its peers and for translating that experience into the premium an employer actually pays. This document specifies the Application Programming Interface for an experience rating bureau service in the style of the NCCI: a system that ingests unit statistical data — payroll and claim detail by policy — from participating carriers, computes experience modification factors from expected losses with a primary/excess split and credibility weighting, and publishes promulgated rating values by state and effective date. Beyond the core computation, the system governs class code assignment through field inspections and governing classification rules, an employer dispute process, mid-term modification revision with retroactive premium adjustment when claim values change after issuance, a formal appeal path for contested modifications, ownership-change and combinability determinations for related entities, and administration of the assigned risk pool including take-out credits when employers exit to the voluntary market.

The audience for this API spans several distinct constituencies with deliberately segregated duties: bureau administrators who register carriers, employers, class codes, and rating tables; carrier data reporters who submit policies and unit statistical reports; bureau analysts who validate data, manage classifications, compute and promulgate experience modifications, decide disputes and appeals, and adjudicate ownership changes; field inspectors; employer representatives who may dispute classifications and appeal modification sheets; pool administrators who run the assigned risk facility; voluntary carrier representatives who file take-out requests; and underwriters who review high-value subjects. Every computation in the system — expected losses, the primary/excess split at the bureau's split point, credibility weighting with ballast, and the take-out credit — must be reproducible from the data on file, because every promulgated number is potentially subject to employer challenge and regulatory audit.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the user acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are well-formed but the declared role is not authorized for the requested endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes exactly these roles:

- `BureauAdmin` — the bureau superuser. Registers bureaus, carriers, employers, and class codes; creates and promulgates rating tables; and operates the logical clock. When `X-User-Role` is `BureauAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `CarrierDataReporter` — a carrier-side user who creates policies and submits unit statistical reports, including corrections. When `X-User-Role` is `CarrierDataReporter`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a `Carrier` compare the resource's foreign-key field to `X-User-ID`.
- `BureauAnalyst` — the bureau's working analyst. Validates unit statistical reports; creates, assigns, and confirms class assignments; reviews and resolves classification disputes; creates, promulgates, and finalizes experience modification sheets; reviews and decides modification appeals; and manages ownership changes and combinability determinations. When `X-User-Role` is `BureauAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Inspector` — a field inspector who completes scheduled inspections. When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `inspector_id` on the `Inspection` the inspector completes.
- `EmployerRepresentative` — an employer or its agent, who withdraws class assignments, files and withdraws classification disputes, and files and withdraws modification appeals. When `X-User-Role` is `EmployerRepresentative`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's foreign-key field to `X-User-ID`.
- `PoolAdministrator` — the assigned risk pool administrator, who creates enrollments, assigns carriers to them, cancels enrollments, and approves or rejects take-out requests. When `X-User-Role` is `PoolAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `VoluntaryCarrierRepresentative` — a voluntary-market carrier user who files take-out requests against pool enrollments. When `X-User-Role` is `VoluntaryCarrierRepresentative`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a `Carrier` compare the resource's foreign-key field to `X-User-ID`.
- `Underwriter` — an underwriter who approves or rejects underwriting reviews. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `reviewer_id` on the `UnderwritingReview` the underwriter decides.
- `Any` — shared read access. All single-resource retrieval and list endpoints are available to every authenticated role; no server-side ownership scoping is applied to reads, and the server does not reject a write request on the basis that the caller's `X-User-ID` names an entity other than the resource's owner — the role alone governs authorization.

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

Endpoints that return lists of resources accept two query parameters. `limit` specifies the maximum number of items to return; it defaults to 10 when not provided, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by `id`. Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix. All resources additionally carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; resource timestamps reflect wall-clock time rather than the logical clock. All resources except the `ClassCode` carry `updated_at`, a timestamp of the same format refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that resource. The `ClassCode` is the single exception: it carries `id` and `created_at` only — both `updated_at` and `version` are absent from it. Enumerated `status` fields always hold one of the exact uppercase strings named in this document; date-only fields such as `effective_date`, `expiration_date`, `rating_effective_date`, and `scheduled_date` are ISO 8601 calendar dates in `YYYY-MM-DD` form.

### 2.5. Monetary Precision and Rounding Discipline

All monetary amounts are stored and transmitted as integer cents — never as floating-point dollars. Every per-line monetary computation is rounded half up to the nearest cent at the line level, and line-level rounded values are then summed; sum-then-round is expressly forbidden. Composite decimal factors carry their own precision: the credibility weight `weight_w` and the short-rate factor used in take-out credits are rounded half up to four decimal places, while the experience `mod_factor` and `provisional_mod_factor` are decimal strings rounded half up to two decimal places (`weight_w` is likewise transmitted as a decimal string). Thresholds and configuration values expressed in basis points are integers, where 10,000 basis points constitute the whole.

### 2.6. Optimistic Concurrency Control

Two write operations in the system guard against stale client state through optimistic concurrency control, and only those two carry a version field in their request payload. When a bureau analyst creates an experience modification sheet for an employer, the request may include `expected_employer_version` carrying the employer's `version` as last observed by the client; if it is present and the employer's current `version` differs — because another writer has advanced it since the client last read it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and if it is omitted no check is performed. A non-integer `expected_employer_version` value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). When a voluntary carrier representative files a take-out request against an assigned risk enrollment, the request may include `expected_enrollment_version` carrying the enrollment's `version` as last observed by the client; when it is present, a mismatch with the enrollment's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and when it is omitted no check is performed. No other endpoint accepts or requires a version field.

### 2.7. Validation Precedence

Incoming requests are validated against a fixed precedence order, so that when several rules would fail at once, the same error surfaces every time. Authentication comes first: header presence and validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Next comes resource existence (`ERR_NOT_FOUND`), followed by state-machine legality (`ERR_INVALID_STATE`). Temporal rules — date ranges and overlapping effective dates (`ERR_TEMPORAL_CONFLICT`) — are evaluated after state checks. Referential rules come next: the referenced class code, carrier, or employer must exist and be in the required status, surfacing `ERR_CLASS_CODE_INACTIVE`, `ERR_CLASS_CODE_NOT_RATED`, `ERR_CARRIER_NOT_ACTIVE`, or `ERR_EMPLOYER_INACTIVE` as applicable. Aggregate and structural business constraints — quota exhaustion, rating eligibility, required revisions, segregation of duties, underwriting review requirements, inspection requirements, unvalidated contributing reports, and duplicate appeals — are evaluated after referential checks. Fiscal sanity checks (`ERR_INVALID_REQUEST`) follow. The optimistic concurrency check (`ERR_STALE_VERSION`) is evaluated last, so a stale client view never masks an earlier, more fundamental rejection.

### 2.8. Logical Time

The system maintains a logical clock that governs time-sensitive evaluations, such as whether a prior completed inspection falls within the past three years. Before any call is made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `BureauAdmin` may advance the clock by supplying a `current_utc` instant through the dedicated clock-setting capability; the value may be an ISO 8601 instant or an ISO 8601 instant followed by a signed day offset such as `+30d` or `-365d`, which shifts the instant by that many days. Time-sensitive rules thereafter evaluate against the supplied logical time.

### 2.9. Hierarchical Consistency and Automatic Transitions

State changes propagate across aggregate boundaries without requiring an explicit client request on each affected resource. When a resource's state transition renders a related resource's state inconsistent — a corrected report invalidating the modification sheet that consumed it, an appeal reversing a contested sheet, a reversed ownership change dissolving its combinability group — the system performs the cascading transition itself. Each cascade independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`. Where endpoints address nested resources, the system validates path parameters left to right: the parent resource is confirmed to exist before any child resource within it is resolved, and a missing parent yields `ERR_NOT_FOUND` without regard to whether the child identifier exists.

## 3. Business Logic & Workflows

### 3.1. Bureau Registration, Carriers, and Employers

Before any rating activity can occur, a `BureauAdmin` registers the rating bureau itself. A bureau is defined by a `code` (for example, `NCCI`) and a display `name`, together with the statewide parameters that drive every downstream computation: `eligibility_threshold_cents`, the annual expected-losses level at or above which an employer becomes eligible for experience rating; `split_point_cents`, the per-claim dividing line between primary and excess losses; `credibility_ballast_bp` and `credibility_excess_divisor_bp`, the two basis-point constants of the credibility weighting formula; and `underwriting_threshold_cents`, the premium level at or above which an underwriting review is inserted into the workflow. A bureau's parameters apply to every computation performed under it, so they are set deliberately and rarely changed.

Carriers join the bureau through registration with their `naic_number` and `legal_name`, plus an `assigned_risk_quota_cents` expressing the maximum assigned-risk premium volume the carrier will accept from the pool. A newly registered carrier starts with `assigned_risk_current_load_cents` at zero and `status` of `ACTIVE`; a carrier whose participation is interrupted moves to `SUSPENDED`, and a carrier that is not `ACTIVE` cannot be referenced where an active carrier is required — any such reference is rejected with `ERR_CARRIER_NOT_ACTIVE`.

Employers are registered by their Federal Employer Identification Number, `fein`, along with their `legal_name` and home `state_code`. A new employer enters as `ACTIVE`; employers under scrutiny sit in `UNDER_REVIEW`, and those no longer writing business become `INACTIVE`. Any workflow that requires an active employer — classification assignment, modification promulgation, pool assignment, or combinability — rejects an employer that is not `ACTIVE` with `ERR_EMPLOYER_INACTIVE`.

### 3.2. Rating Table Promulgation and Policy Issuance

Rating values are promulgated by state and effective date. A `BureauAdmin` creates a `RatingTable` for a `state_code` with an `effective_date` and a `values` array whose entries each carry a `class_code`, its `rate_per_100_payroll_cents`, its expected loss rate `elr_per_100_payroll_cents`, and its discount ratio `d_ratio_bp`. A new table begins in `DRAFT`. Promulgation moves the table to `PROMULGATED` and simultaneously moves any prior promulgated table for the same state to `SUPERSEDED`, stamping that table's `superseded_at`; only one promulgated table is in force for a state at a time, and lookups always resolve against the table in force at the relevant date. A superseded table continues to govern lookups at dates on or after its own `effective_date` and before the `effective_date` of the table that superseded it: the table in force at a given date is the one with the latest `effective_date` on or before that date among the state's promulgated and superseded tables, and at equal effective dates the still-promulgated table prevails over the one it superseded.

With a promulgated table in place — and alongside it the library of class codes, each identified by its `code`, its governing classification `description`, and the `state_code` it applies to — a `CarrierDataReporter` issues a `Policy` by supplying the `employer_id`, the writing `carrier_id`, a `policy_number`, the term bounded by `effective_date` and `expiration_date`, and a `class_codes` array pairing each classification with its estimated `payroll_dollars` for the term. The effective date must precede the expiration date, or the request is rejected with `ERR_TEMPORAL_CONFLICT`. The policy's `manual_premium_cents` is computed at creation: for each line, the payroll in dollars is multiplied by the classification's `rate_per_100_payroll_cents` from the promulgated table in force at the policy's effective date and divided by one hundred, each line rounded half up to whole cents, and the rounded lines summed. A policy whose classifications are not all rated in the in-force table cannot be priced, and the offending lookup surfaces `ERR_CLASS_CODE_NOT_RATED`. The new policy is `ACTIVE`, and its `unit_stat_report_id` remains null until the first unit statistical report is validated for it.

### 3.3. Unit Statistical Reporting and Corrections

Carriers report unit statistical data per policy. A `CarrierDataReporter` submits a `UnitStatReport` naming the `policy_id` and carrying two arrays: `payroll_lines`, each pairing a `class_code` with audited `payroll_dollars`, and `claim_lines`, each carrying a `claim_number`, a `claim_type` of `INDEMNITY` or `MEDICAL`, the `incurred_cents` and `paid_cents` amounts, a `claim_status` of `OPEN` or `CLOSED`, and the `state_code` under which the claim arose. Every report for a policy receives a sequential `submission_number`, starting at one for the first submission. The report enters in `SUBMITTED`.

Validation by a `BureauAnalyst` is the gateway to rating use. Only a report in `SUBMITTED` status can be validated; validating a report in any other status is rejected with `ERR_INVALID_STATE`. Validation enforces its checks in order: the policy must be `ACTIVE`, and a policy that is not `ACTIVE` blocks validation with `ERR_INVALID_STATE`; the report must contain at least one payroll line and at least one claim line, failing with `ERR_INVALID_REQUEST` when either array is empty; every claim line's `state_code` must match the policy's state, failing with `ERR_STATE_MISMATCH` on the first divergence; and every payroll line must reference a class code that is `ACTIVE`, failing with `ERR_CLASS_CODE_INACTIVE` otherwise. A report that passes all four checks moves to `VALIDATED`, and the policy's `unit_stat_report_id` is set to point at it.

Corrections follow a replacement-not-edit discipline. To correct a report that is `VALIDATED` or `LOCKED`, the carrier submits a fresh report whose `correction_of_report_id` names the report being corrected; referencing a report in any other status is rejected with `ERR_INVALID_STATE`. The new report enters in `SUBMITTED` with the next `submission_number`; the referenced report remains in its status until the correction report itself is validated, at which point the referenced report moves to `CORRECTED`. When the corrected report was already `LOCKED` at the time the correction is validated — meaning a promulgated modification sheet had consumed it — that validation also moves the consuming sheet from `PROMULGATED` to `REVISED` and spawns a replacement sheet in `DRAFT` whose `revision_reason` is `CLAIM_VALUE_CHANGE`, as described in §3.6; and any attempt to promulgate a new sheet for the same employer and rating effective date while a prior promulgated sheet exists, where the new sheet does not carry a `revision_reason`, is rejected with `ERR_MOD_REVISION_REQUIRED`. Reports locked into a promulgated sheet are otherwise immutable: a report moves from `VALIDATED` to `LOCKED` automatically when the policy's experience modification sheet is promulgated, after which only the correction path can supersede it.

### 3.4. Class Code Assignment, Inspection, and Employer Disputes

Classifications begin when a `BureauAnalyst` creates a `ClassAssignment` naming the `employer_id`, the proposed `class_code_id`, and an `effective_date`; the referenced employer and class code must exist (`ERR_NOT_FOUND`). The assignment enters in `PENDING_INSPECTION`. The overlap guard is enforced when the assignment moves to `ASSIGNED`: no other assignment for the same employer may hold `ASSIGNED` or `CONFIRMED` status with the same `effective_date`; an overlapping proposal is rejected with `ERR_CLASS_ASSIGNMENT_OVERLAP`, and any malformed date value surfaces `ERR_INVALID_REQUEST`.

Assignment proper — moving the assignment from `PENDING_INSPECTION` to `ASSIGNED` — is performed by a `BureauAnalyst` once the classification review is complete. The employer must be `ACTIVE` and the class code must be `ACTIVE`. When the employer has no prior inspection within the past three years, the act of assignment automatically creates an `Inspection` in `SCHEDULED` status and records its identifier on the assignment's `inspection_id`; the inspection carries the `class_assignment_id`, a null `inspector_id` until an inspector completes it, and a `scheduled_date` set to the creation date. An employer representative who disagrees before assignment completes may withdraw the assignment while it is still `PENDING_INSPECTION`, moving it to `WITHDRAWN`; withdrawing an assignment in any other status is rejected with `ERR_INVALID_STATE`.

Inspections are conducted and recorded by an `Inspector`, who completes the inspection by submitting narrative `findings`; the inspection moves to `COMPLETED` and the completing user's identifier is recorded as `inspector_id`. Alternatively, a `BureauAnalyst` may waive the inspection, moving it to `WAIVED`, but only when the employer has a prior completed inspection within the past three years — the three-year window is measured as 365 days per year back from the logical clock, against the completion timestamp; a waiver without that history is rejected with `ERR_INSPECTION_WAIVE_NOT_ALLOWED`. Confirmation — moving the assignment from `ASSIGNED` to `CONFIRMED` — requires every inspection for the assignment to be `COMPLETED` or `WAIVED`; confirming with an outstanding scheduled inspection fails with `ERR_INSPECTION_REQUIRED`. Once all inspections are closed, the assignment remains `ASSIGNED` until confirmed.

An employer representative who disputes the classification files a `ClassAssignmentDispute` naming the `class_assignment_id` and a `reason` code — `WRONG_CLASS`, `PAYROLL_MISMATCH`, or `OTHER`. The assignment must be `ASSIGNED` or `CONFIRMED`; disputing an assignment in any other status fails with `ERR_INVALID_STATE`. Filing creates the dispute in `OPEN`, derives the dispute's `employer_id` from the assignment, moves the assignment itself to `DISPUTED`, and records the dispute's identifier on the assignment's `dispute_id`. A `BureauAnalyst` moves the dispute from `OPEN` to `IN_REVIEW`; the employer may instead withdraw a dispute that is still `OPEN`, which returns the assignment to its prior status — `ASSIGNED` or `CONFIRMED` as the case was.

Resolution by a `BureauAnalyst` takes one of two forms, and the dispute must be `IN_REVIEW` for either. Resolving with `resolution` of `CONFIRMED` closes the dispute as `RESOLVED` with the original classification upheld: the assignment moves to `CONFIRMED` and the dispute's `resolved_at` is stamped. Resolving with `resolution` of `REASSIGNED` additionally requires a `new_class_code_id` naming an `ACTIVE` class code; the original assignment moves to `REASSIGNED`, the dispute closes as `RESOLVED` with that resolution recorded, and a brand-new `ClassAssignment` is created directly in `ASSIGNED` status carrying the new classification and the original assignment's `effective_date`.

### 3.5. Experience Modification Computation and Promulgation

The experience modification sheet is the system's central artifact. A `BureauAnalyst` creates an `ExperienceModSheet` for an `employer_id` and a `rating_effective_date`, presenting `expected_employer_version` per the concurrency contract in §2.6; a non-integer `expected_employer_version` is rejected with `ERR_INVALID_REQUEST`. The sheet is born in `DRAFT`, and the full computation runs at creation. Creating a sheet mutates the employer record itself, advancing its `version`.

Expected losses anchor the computation. For every payroll line across the employer's unit statistical reports, the payroll in dollars is multiplied by the classification's `elr_per_100_payroll_cents` — looked up from the promulgated rating table in force at the `rating_effective_date` for the employer's home state and class code — and divided by one hundred, rounded half up per line, then summed into `expected_losses_cents`. A payroll line whose class code has no entry in the in-force table causes the sheet computation to fail outright with `ERR_CLASS_CODE_NOT_RATED`. The `d_ratio_bp` used in the expected-losses split is taken from the first payroll line's matching table row.

Actual losses split at the bureau's split point. For each claim line, the primary portion is the lesser of the claim's `incurred_cents` and the bureau's `split_point_cents`; the excess portion is the remainder. Summing the primary portions across all claims yields `actual_primary_cents`; summing the remainders yields `actual_excess_cents`.

Credibility weighting blends actual with expected. The ballast `ballast_cents` is the bureau's `credibility_ballast_bp` divided by ten thousand, multiplied by `expected_losses_cents`, rounded half up to cents. The weight `weight_w` is `expected_losses_cents` divided by the sum of `expected_losses_cents` and the product of the bureau's `credibility_excess_divisor_bp` divided by ten thousand with one hundred million, rounded half up to four decimal places; if that sum is zero, `weight_w` is zero. Expected losses split into `expected_primary_cents` — expected losses multiplied by the rating table's `d_ratio_bp` divided by ten thousand, rounded half up — and `expected_excess_cents`, which is simply expected losses minus the expected primary portion. The numerator of the modification is the sum of four terms: `actual_primary_cents`; the product of `weight_w` and `actual_excess_cents` rounded half up; the product of one minus `weight_w` with `expected_excess_cents` rounded half up; and `ballast_cents`. The denominator is `expected_losses_cents` plus `ballast_cents`. The `mod_factor` is the numerator divided by the denominator, rounded half up to two decimal places — a sheet might therefore promulgate a factor such as 1.44; if the denominator is zero the factor is 1.00.

Two variants of the factor coexist on every sheet. The `mod_factor` described above is the final factor, computed only from reports that are `VALIDATED` or `LOCKED`. The `provisional_mod_factor` applies the identical formula to a broader input set that additionally includes reports still in `SUBMITTED` status; it gives stakeholders an early read while data is pending. When the last `SUBMITTED` report among the consumed inputs is validated, the provisional factor is recomputed and then matches `mod_factor` exactly.

Promulgation is the regulated act that makes a factor effective. A `BureauAnalyst` promulgates a `DRAFT` sheet (a sheet in any other status fails with `ERR_INVALID_STATE`), subject to checks evaluated in a deliberate order: the employer must be `ACTIVE` (`ERR_EMPLOYER_INACTIVE`); no unit statistical report of the employer may still be `SUBMITTED` — the check covers every report in `SUBMITTED`, `VALIDATED`, or `LOCKED` status across the employer's policies, with any still-`SUBMITTED` report surfacing `ERR_UNVALIDATED_REPORTS`; eligibility is then enforced — when the employer's total `expected_losses_cents` are at least the bureau's `eligibility_threshold_cents` the computed `mod_factor` stands, but below that threshold the factor is fixed at exactly 1.00 (unity) and the sheet still promulgates with that value; because the factor is server-computed and itself fixed to unity in this case, promulgation of an ineligible employer's sheet is never rejected on eligibility grounds; finally, if a prior promulgated sheet exists for the same employer and rating effective date, the new sheet must either supersede it as a revision carrying a `revision_reason`, or the promulgation is rejected with `ERR_MOD_REVISION_REQUIRED`. A successful promulgation locks every `VALIDATED` report among the employer's reports — each moves from `VALIDATED` to `LOCKED` — and, when the sheet revises an earlier sheet (its `revision_of_sheet_id` set), moves the referenced sheet from `PROMULGATED` to `REVISED`. When the sheet's `expected_losses_cents` are at least the bureau's `underwriting_threshold_cents`, promulgation additionally creates an `UnderwritingReview` in `PENDING` with `subject_type` of `MOD_SHEET`.

### 3.6. Modification Revision and Retroactive Premium Adjustment

Promulgated factors are not frozen when the underlying facts change. A `PROMULGATED` sheet moves to `REVISED` automatically in three circumstances: a correction report consuming a locked report is validated; a class code reassignment is confirmed; or a rating table revision is promulgated. In each case the system creates a new `ExperienceModSheet` in `DRAFT` whose `revision_of_sheet_id` points at the superseded sheet and whose `revision_reason` records the cause — `CLAIM_VALUE_CHANGE`, `CLASS_CODE_CHANGE`, or `RATE_REVISION` respectively. Each trigger has a defined scope: the claim-value trigger revises every promulgated sheet of the employer whose locked report was corrected; the class-code trigger fires when a classification dispute is resolved with `resolution` of `REASSIGNED` and revises every promulgated sheet of that assignment's employer (the resolution itself performs the revision; a separately confirmed assignment does not); and the rate-revision trigger fires when a rating table is promulgated and revises every promulgated sheet of each employer holding at least one policy in the table's state.

Revised factors carry money with them. The sheet's `retroactive_premium_adjustment_cents` compares what was billed under the prior factor against what should have been billed under the new one: the policy's `manual_premium_cents` is recomputed as the per-line rounded sum of payroll times rate per hundred, exactly as at policy issuance, using the rating table in force at the prior sheet's `rating_effective_date` and the employer's most recently created policy; the old billing is the manual premium multiplied by the prior sheet's `mod_factor`, rounded half up; the new billing is the manual premium multiplied by the new sheet's `mod_factor`, rounded half up; and the adjustment is the new billing minus the old. A negative adjustment is a credit due to the insured. The adjustment applies in full for the elapsed portion of the policy term — no pro-ration is performed, because the modification applies retroactively to the entire policy period. A revised sheet may be moved to `FINAL` by a `BureauAnalyst` once no active appeal exists against it, and an uncontested `DRAFT` sheet may likewise be finalized directly; finalizing a sheet in any other status is rejected with `ERR_INVALID_STATE`.

### 3.7. Contested Modifications and the Appeals Process

An employer who disagrees with a promulgated factor contests it through the appeal process. An `EmployerRepresentative` files a `ModAppeal` naming the `mod_sheet_id` and a free-text `reason`. The sheet must be `PROMULGATED` — appealing a sheet in any other status fails with `ERR_INVALID_STATE` — and no other active appeal (one still `FILED` or `UNDER_REVIEW`) may exist for the sheet, or the filing is rejected with `ERR_APPEAL_ALREADY_ACTIVE`; when both would fail at once, the duplicate-appeal check surfaces first and `ERR_APPEAL_ALREADY_ACTIVE` is returned. The `reason` text itself is required; a missing `reason` is rejected with `ERR_INVALID_REQUEST`. Filing creates the appeal in `FILED`, stamps its `filed_at`, derives its `employer_id` from the sheet, and moves the sheet from `PROMULGATED` to `CONTESTED`. An appeal the employer no longer wishes to press may be withdrawn while `FILED`, which moves the appeal to `WITHDRAWN` and returns the sheet from `CONTESTED` to `PROMULGATED`.

A `BureauAnalyst` moves the appeal from `FILED` to `UNDER_REVIEW`, and then decides it with a `decision` and a free-text `decision_reason`; the appeal must be `UNDER_REVIEW` for a decision, or the attempt fails with `ERR_INVALID_STATE`. Deciding `UPHELD` moves the appeal to `UPHELD`, stamps `decided_at`, and moves the sheet from `CONTESTED` to `FINAL` — the factor stands. Deciding `REVERSED` moves the appeal to `REVERSED` and moves the sheet from `CONTESTED` to `REVISED`, and the system spawns a new `ExperienceModSheet` in `DRAFT` with `revision_of_sheet_id` pointing at the reversed sheet and `revision_reason` of `CLAIM_VALUE_CHANGE`. Finalization of a sheet — from `DRAFT` directly, or from `REVISED` — is only permitted while no active appeal exists for it, surfacing `ERR_APPEAL_ALREADY_ACTIVE` otherwise.

### 3.8. Ownership Change and Combinability

Experience follows ownership. When an employer's ownership changes, a `BureauAnalyst` reports an `OwnershipChange` naming the `employer_id`, the `change_type` — `SALE`, `MERGER`, `FORMATION_OF_NEW_ENTITY`, or `OTHER` — and the `effective_date`. The change enters in `PENDING`.

The combinability determination decides whether the related entities' experience merges. Combining — moving the change from `PENDING` to `COMBINED` — requires every employer in the proposed group to be `ACTIVE` (`ERR_EMPLOYER_INACTIVE`) and none of them to already belong to another `ACTIVE` combinability group (`ERR_ALREADY_COMBINED`). A successful combination creates a `CombinabilityGroup` in `ACTIVE` status whose `member_employer_ids` list the change's employer together with the related employers supplied as `member_employer_ids` in the combine request, records the originating change on the group's `created_from_change_id`, stamps the change's `combinability_group_id`, and creates a combined `ExperienceModSheet` in `DRAFT` — anchored on the change's employer, computed over all group members' `VALIDATED` and `LOCKED` reports with the rating values in force at the creation date — recorded on the group's `combined_mod_sheet_id`. Where the experience does not merge, the analyst instead marks the change `NOT_COMBINED`.

Reversal unwinds a combination. Reversing a change requires the change to be `COMBINED` and its group to be `ACTIVE` (`ERR_INVALID_STATE` otherwise); the change moves to `REVERSED`, the group dissolves to `DISSOLVED`, and the combined modification sheet is voided — moved to `REVISED` with `revision_reason` of `CLASS_CODE_CHANGE`.

### 3.9. Assigned Risk Pool Administration and Take-Out Credits

Employers unable to obtain voluntary coverage are placed in the assigned risk pool. A `PoolAdministrator` creates an `AssignedRiskEnrollment` naming the `employer_id`, the `state_code` of assignment, the term bounded by `effective_date` and `expiration_date`, and the `estimated_annual_premium_cents`; the enrollment enters in `PENDING`. Assigning a carrier moves the enrollment to `ACTIVE`: the employer must be `ACTIVE` (`ERR_EMPLOYER_INACTIVE`), and the selected carrier must have room under its quota — the sum of the carrier's `assigned_risk_current_load_cents` and the enrollment's `estimated_annual_premium_cents` must not exceed the carrier's `assigned_risk_quota_cents`, or the assignment is rejected with `ERR_ASSIGNED_RISK_QUOTA_EXCEEDED`. Assignment adds the estimated premium to the carrier's `assigned_risk_current_load_cents` and records the carrier on the enrollment's `assigned_carrier_id`. The pool also monitors utilization: when a carrier's current load reaches or exceeds eighty percent of its quota — computed in integer basis points as the load multiplied by ten thousand and divided by the quota, rounded half up — the pool administrator is warned, though assignment remains possible until the quota itself would be exceeded. Cancelling an active enrollment moves it to `CANCELLED`, sets its `exit_reason` to `CANCELLED`, and subtracts the estimated premium from the carrier's load (the load never drops below zero).

A voluntary carrier may lift an employer out of the pool through a take-out. A `VoluntaryCarrierRepresentative` files an `AssignedRiskTakeOut` naming the `enrollment_id`, the `voluntary_carrier_id`, and the `exit_date`, presenting `expected_enrollment_version` per §2.6. The enrollment must be `ACTIVE` (`ERR_INVALID_STATE`) and the voluntary carrier must be `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`). Filing creates the take-out in `PENDING` and places a hold on the carrier's pool load — the enrollment's estimated premium is subtracted from `assigned_risk_current_load_cents` pending the decision (the load never drops below zero).

The pool administrator's decision resolves both the credit and the hold. Approval requires the enrollment still to be `ACTIVE` (`ERR_INVALID_STATE`), and — when the computed credit is at least the bureau's `underwriting_threshold_cents` — an approved `UnderwritingReview` for the take-out must already exist, or the approval is rejected with `ERR_UNDERWRITING_REVIEW_REQUIRED`; if no `PENDING` review yet exists for the take-out, the system creates one in `PENDING` as part of the rejection. The credit itself is date-driven: `total_days` is the count of days from the enrollment's `effective_date` through its `expiration_date` inclusive; `earned_days` is the count from the `effective_date` to the `exit_date` (the `exit_date` itself is unearned); and `remaining_days` is the difference, floored at zero. The pro-rata credit is the `estimated_annual_premium_cents` multiplied by the ratio of remaining days to total days and by one half — the pool's share — rounded half up to cents. The short-rate credit first derives a short-rate factor of nine tenths multiplied by the ratio of remaining days to total days, rounded half up to four decimal places, then multiplies the estimated premium by that factor and by one half, rounded half up to cents. Because a take-out exit always carries `exit_reason` of `TAKE_OUT`, the short-rate credit is the amount granted; the pro-rata formula stands for the other exit reasons. On approval the take-out moves to `APPROVED` with `approved_at` stamped and the credit recorded both in the take-out's `credit_cents` and on the enrollment as `take_out_credit_cents` (each zero until approved), the enrollment moves to `EXITED` with its own `exit_date` stamped and `exit_reason` set to `TAKE_OUT`, and the hold on the carrier's load is released. Rejection moves the take-out to `REJECTED`, leaves the enrollment `ACTIVE`, and likewise releases the hold — the carrier's load returns to its pre-filing level.

### 3.10. Underwriting Reviews and Segregation of Duties

High-value subjects pass through an independent underwriting gate. An `UnderwritingReview` is created by the system, in `PENDING` status, whenever a promulgated modification sheet's expected losses reach the bureau's `underwriting_threshold_cents` (`subject_type` of `MOD_SHEET`), and is required before a take-out whose credit reaches the same threshold can be approved (`subject_type` of `TAKE_OUT`); the review's `subject_id` names the sheet or take-out under scrutiny. The subject type may also be `CLASS_ASSIGNMENT` where a classification decision warrants the same scrutiny.

An `Underwriter` approves or rejects the pending review, and the decision records the acting underwriter's identifier as `reviewer_id` with `decided_at` stamped. Segregation of duties is strictly enforced: the underwriter deciding a review must not be the same user who created the subject under review, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` — this is why the user who computed a modification sheet can never also clear its underwriting gate. Rejection cascades where the subject demands it: rejecting a review whose `subject_type` is `TAKE_OUT` moves the take-out itself from `PENDING` to `REJECTED`, with all the consequences described in §3.9.

## 4. Endpoint Definitions

All endpoints share the response envelope described in §2.2. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, trigger a state transition, or read data respond with HTTP 200. Authorization is per the role column below; endpoints marked `Any` are readable by every authenticated role.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/bureaus` | Create a bureau | BureauAdmin |
| GET | `/bureaus/{bureauId}` | Get a bureau | Any |
| POST | `/carriers` | Create a carrier | BureauAdmin |
| GET | `/carriers/{carrierId}` | Get a carrier | Any |
| POST | `/employers` | Create an employer | BureauAdmin |
| GET | `/employers/{employerId}` | Get an employer | Any |
| POST | `/class-codes` | Create a class code | BureauAdmin |
| GET | `/class-codes/{classCodeId}` | Get a class code | Any |
| POST | `/rating-tables` | Create a rating table | BureauAdmin |
| GET | `/rating-tables/{ratingTableId}` | Get a rating table | Any |
| POST | `/rating-tables/{ratingTableId}/promulgate` | Promulgate a rating table | BureauAdmin |
| POST | `/policies` | Create a policy | CarrierDataReporter |
| GET | `/policies/{policyId}` | Get a policy | Any |
| GET | `/policies` | List policies (filterable) | Any |
| POST | `/unit-stat-reports` | Create a unit statistical report | CarrierDataReporter |
| GET | `/unit-stat-reports/{unitStatReportId}` | Get a unit statistical report | Any |
| GET | `/unit-stat-reports` | List unit statistical reports (filterable) | Any |
| POST | `/unit-stat-reports/{unitStatReportId}/validate` | Validate a unit statistical report | BureauAnalyst |
| POST | `/class-assignments` | Create a class assignment | BureauAnalyst |
| GET | `/class-assignments/{classAssignmentId}` | Get a class assignment | Any |
| GET | `/class-assignments` | List class assignments (filterable) | Any |
| POST | `/class-assignments/{classAssignmentId}/assign` | Assign a class code | BureauAnalyst |
| POST | `/class-assignments/{classAssignmentId}/confirm` | Confirm a class assignment | BureauAnalyst |
| POST | `/class-assignments/{classAssignmentId}/withdraw` | Withdraw a class assignment | EmployerRepresentative |
| GET | `/inspections/{inspectionId}` | Get an inspection | Any |
| GET | `/inspections` | List inspections (filterable) | Any |
| POST | `/inspections/{inspectionId}/complete` | Complete an inspection | Inspector |
| POST | `/inspections/{inspectionId}/waive` | Waive an inspection | BureauAnalyst |
| POST | `/class-assignment-disputes` | File a class assignment dispute | EmployerRepresentative |
| GET | `/class-assignment-disputes/{disputeId}` | Get a class assignment dispute | Any |
| GET | `/class-assignment-disputes` | List class assignment disputes (filterable) | Any |
| POST | `/class-assignment-disputes/{disputeId}/review` | Move a dispute to review | BureauAnalyst |
| POST | `/class-assignment-disputes/{disputeId}/resolve` | Resolve a class assignment dispute | BureauAnalyst |
| POST | `/class-assignment-disputes/{disputeId}/withdraw` | Withdraw a class assignment dispute | EmployerRepresentative |
| POST | `/experience-mod-sheets` | Create an experience modification sheet | BureauAnalyst |
| GET | `/experience-mod-sheets/{modSheetId}` | Get an experience modification sheet | Any |
| GET | `/experience-mod-sheets` | List experience modification sheets (filterable) | Any |
| POST | `/experience-mod-sheets/{modSheetId}/promulgate` | Promulgate an experience modification sheet | BureauAnalyst |
| POST | `/experience-mod-sheets/{modSheetId}/finalize` | Finalize an experience modification sheet | BureauAnalyst |
| POST | `/mod-appeals` | File a modification appeal | EmployerRepresentative |
| GET | `/mod-appeals/{appealId}` | Get a modification appeal | Any |
| GET | `/mod-appeals` | List modification appeals (filterable) | Any |
| POST | `/mod-appeals/{appealId}/review` | Move an appeal to review | BureauAnalyst |
| POST | `/mod-appeals/{appealId}/decide` | Decide a modification appeal | BureauAnalyst |
| POST | `/mod-appeals/{appealId}/withdraw` | Withdraw a modification appeal | EmployerRepresentative |
| POST | `/ownership-changes` | Report an ownership change | BureauAnalyst |
| GET | `/ownership-changes/{changeId}` | Get an ownership change | Any |
| GET | `/ownership-changes` | List ownership changes (filterable) | Any |
| POST | `/ownership-changes/{changeId}/combine` | Combine employers into a combinability group | BureauAnalyst |
| POST | `/ownership-changes/{changeId}/not_combined` | Mark employers as not combinable | BureauAnalyst |
| POST | `/ownership-changes/{changeId}/reverse` | Reverse a combinability determination | BureauAnalyst |
| GET | `/combinability-groups/{groupId}` | Get a combinability group | Any |
| GET | `/combinability-groups` | List combinability groups (filterable) | Any |
| POST | `/assigned-risk-enrollments` | Create an assigned risk enrollment | PoolAdministrator |
| GET | `/assigned-risk-enrollments/{enrollmentId}` | Get an assigned risk enrollment | Any |
| GET | `/assigned-risk-enrollments` | List assigned risk enrollments (filterable) | Any |
| POST | `/assigned-risk-enrollments/{enrollmentId}/assign` | Assign a carrier to an enrollment | PoolAdministrator |
| POST | `/assigned-risk-enrollments/{enrollmentId}/cancel` | Cancel an assigned risk enrollment | PoolAdministrator |
| POST | `/assigned-risk-take-outs` | File a take-out request | VoluntaryCarrierRepresentative |
| GET | `/assigned-risk-take-outs/{takeOutId}` | Get a take-out request | Any |
| GET | `/assigned-risk-take-outs` | List take-out requests (filterable) | Any |
| POST | `/assigned-risk-take-outs/{takeOutId}/approve` | Approve a take-out request | PoolAdministrator |
| POST | `/assigned-risk-take-outs/{takeOutId}/reject` | Reject a take-out request | PoolAdministrator |
| GET | `/underwriting-reviews/{reviewId}` | Get an underwriting review | Any |
| POST | `/underwriting-reviews/{reviewId}/approve` | Approve an underwriting review | Underwriter |
| POST | `/underwriting-reviews/{reviewId}/reject` | Reject an underwriting review | Underwriter |
| GET | `/employers/{employerId}/policies` | List policies for an employer | Any |
| GET | `/policies/{policyId}/unit-stat-reports` | List unit statistical reports for a policy | Any |
| GET | `/employers/{employerId}/class-assignments` | List class assignments for an employer | Any |
| GET | `/class-assignments/{classAssignmentId}/inspections` | List inspections for a class assignment | Any |
| GET | `/class-assignments/{classAssignmentId}/disputes` | List disputes for a class assignment | Any |
| GET | `/employers/{employerId}/experience-mod-sheets` | List modification sheets for an employer | Any |
| GET | `/experience-mod-sheets/{modSheetId}/appeals` | List appeals for a modification sheet | Any |
| GET | `/employers/{employerId}/ownership-changes` | List ownership changes for an employer | Any |
| GET | `/employers/{employerId}/assigned-risk-enrollments` | List pool enrollments for an employer | Any |
| GET | `/assigned-risk-enrollments/{enrollmentId}/take-outs` | List take-outs for an enrollment | Any |
| GET | `/carriers/{carrierId}/assigned-risk-enrollments` | List pool enrollments for a carrier | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock | BureauAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TEMPORAL_CONFLICT | 409 |
| ERR_CLASS_CODE_INACTIVE | 409 |
| ERR_CLASS_CODE_NOT_RATED | 409 |
| ERR_CARRIER_NOT_ACTIVE | 409 |
| ERR_EMPLOYER_INACTIVE | 409 |
| ERR_STATE_MISMATCH | 409 |
| ERR_UNVALIDATED_REPORTS | 409 |
| ERR_NOT_ELIGIBLE_FOR_EXPERIENCE_RATING | 409 |
| ERR_MOD_REVISION_REQUIRED | 409 |
| ERR_APPEAL_ALREADY_ACTIVE | 409 |
| ERR_INSPECTION_REQUIRED | 409 |
| ERR_INSPECTION_WAIVE_NOT_ALLOWED | 409 |
| ERR_CLASS_ASSIGNMENT_OVERLAP | 409 |
| ERR_ALREADY_COMBINED | 409 |
| ERR_ASSIGNED_RISK_QUOTA_EXCEEDED | 409 |
| ERR_UNDERWRITING_REVIEW_REQUIRED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
