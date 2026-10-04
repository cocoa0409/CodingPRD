# Protective Coating Specification & Applicator Approval API — Product Requirements Document

## 1. Introduction

Owners of bridges, storage tanks, pipelines, and structural steel assets stake enormous capital on the premise that a protective coating system, once specified, is applied exactly as its technical data sheet demands — with the correct surface preparation, the correct film build, and an applicator whose workmanship has been independently verified. In practice, specifications drift as data sheets are revised, owners name competing products mid-project to save money, applicators cut corners on surface preparation, and environmental regulators tighten volatile organic compound (VOC) limits jurisdiction by jurisdiction. Each of these failure modes surfaces months or years later as corrosion underfilm, adhesion loss, or delamination, at which point the only question that matters — was it the product or the applicator? — is nearly impossible to answer without a complete, tamper-evident record of what was specified, what was applied, and what was inspected.

This document specifies the Protective Coating Specification & Applicator Approval API, a REST service mounted under the `/coating` prefix, which governs that record end to end. The system administers a catalogue of coating systems (both house products and competitor products named in substitution challenges), jurisdiction-scoped VOC regulation windows, applicator companies and the qualification programs that certify them, owner projects with their specifications and substitution requests, work orders with surface-preparation hold points, per-coat application records with film thickness, adhesion, and holiday testing, joint-liability warranties between manufacturer and applicator, and formal failure investigations that adjudicate fault. A deterministic logical clock drives time-dependent behavior such as quality-score decay, and every inspection verdict, VOC compliance check, and liability split is computed by the server from recorded measurements rather than asserted by the caller.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint in the system: authentication, response envelopes, pagination, resource identity, timekeeping, numeric precision, concurrency control, validation ordering, and time-window semantics.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly seven roles, spelled as follows: `PlatformAdmin`, `TechnicalServiceEngineer`, `ProjectEngineer`, `OwnerRepresentative`, `ApplicatorRep`, `Inspector`, and `ComplianceOfficer`. Each write endpoint is restricted to a named subset of these roles (enumerated in §4); a request whose role is not authorized for the endpoint it targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ApplicatorRep`, `X-User-ID` is the `id` of the acting `Applicator`; ownership checks on any resource that references an applicator — for example a work order's `applicator_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `TechnicalServiceEngineer`, `ProjectEngineer`, `OwnerRepresentative`, `Inspector`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `inspector_id` on a filed inspection report) but does not compare it to any entity's `id`, with one deliberate exception: the segregation-of-duties protocol in §3.5, which compares an inspector's `X-User-ID` against the applicator identity of the work order being inspected.

The roles divide responsibilities along segregation-of-duties lines. A `PlatformAdmin` is the platform operator and exclusively registers applicator companies and drives the logical clock. A `TechnicalServiceEngineer` represents the manufacturer's technical service organization and exclusively owns coating-system registration, revision, and obsolescence; qualification-program creation; certification, suspension, reinstatement, and revocation of applicator qualifications; substitution review and decisions; testing waivers; warranty voiding; and failure-investigation evidence gathering and adjudication. A `ProjectEngineer` is the owner-side engineer who exclusively creates, completes, and cancels projects; creates, issues, and withdraws specifications; creates, completes, and cancels work orders; and issues warranties. An `OwnerRepresentative` is the asset owner's delegate and exclusively files substitution requests and warranty claims. An `ApplicatorRep` exclusively enrolls their company in qualification programs, begins preparation inspection on work orders, records coating applications, and marks coats cured. An `Inspector` is an independent coating inspector who exclusively files surface-preparation inspections and post-application inspection reports. A `ComplianceOfficer` exclusively creates and supersedes VOC regulation windows. Read endpoints are broadly shared across roles as itemized in §4.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, and any supplied value must be at least 1 and at most 100. The `offset` parameter sets the number of items skipped before the page begins and defaults to 0. Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — coating systems, VOC regulations, applicators, qualification programs, applicator qualifications, projects, specifications, substitution requests, work orders, surface-preparation inspections, coating applications, inspection reports, warranties, and failure investigations — carries a uniform set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource, and which underlies the optimistic concurrency control described in §2.7.

Recomputes of derived fields count as modifications. When an applicator's `quality_history_score` or `consecutive_passed_inspections` is recomputed, when a project's `committed_warranty_exposure_cents` moves, when a coating system's `spec_revision` is bumped, or when any cascade touches a parent record, that parent record's `updated_at` is refreshed and its `version` is incremented as an independent mutation.

### 2.5. The Logical Clock and the Monthly Quality Decay Sweep

The server maintains a logical clock that never reads wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `current_utc` instant (an ISO 8601 UTC timestamp), and every timestamp-sensitive rule in this document — regulation-window coverage, application-window containment, cure windows, and the decay sweep below — evaluates against the logical clock.

When a clock-setting call crosses one or more calendar-month boundaries, the quality-history decay sweep fires: for each elapsed calendar month in which an applicator recorded no `ACCEPTED` inspection report, that applicator's `quality_history_score` is reduced by 5 points. The sweep's consequences — including the suspension cascade of §3.3 when a decayed score falls below a certified program's floor — are identical to those of any other score-changing event.

### 2.6. Numeric Precision and Rounding

Different quantities in the system obey different precision contracts, and an implementation must reproduce each exactly:

- **VOC values.** Any computed VOC figure — `voc_at_issuance_gpl` on a specification or `applied_voc_gpl` on a coating application — is rounded half-up to exactly 1 decimal place before it is stored or compared against a regulation limit.
- **Film-thickness averages.** The average of a set of spot dry-film-thickness readings is rounded half-up to exactly 1 decimal place before any acceptance comparison is made against it.
- **Holiday density.** The holiday density (holidays per square metre) is computed in full precision, and the comparison against the applicable limit is exact, with no intermediate rounding.
- **Quality history score.** The applicator `quality_history_score` is pure integer arithmetic: event deltas are whole points, no rounding occurs anywhere, and after each event the score is clamped into the inclusive range from 0 to 1000.
- **Warranty shares.** Liability shares are integer cents. The manufacturer's `material_share_cents` is the exposure multiplied by the fault fraction, rounded half-up to a whole cent; the applicator's `application_share_cents` is whatever remainder keeps the two shares summing exactly to the exposure.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two:

- Issuing a specification (the specification issuance endpoint, `POST /coating/projects/{projectId}/specifications/{id}/issue`) requires the request body to carry `expected_project_version`, a non-optional field holding the `version` of the parent `Project` as last observed by the client. If the project's current `version` does not match — for example because another writer has just issued a superseding specification, an act which itself bumps the project's version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from issuing against a project state it has not observed.
- Certifying an applicator qualification (the certification endpoint, `POST /coating/applicators/{applicatorId}/qualifications/{id}/certify`) requires the request body to carry `expected_applicator_version`, a non-optional field holding the `version` of the parent `Applicator` as last observed by the client. Score-affecting events — inspection results, preparation failures, VOC violations, adjudications — mutate the applicator's `quality_history_score` and bump its `version`, so a mismatch means the certifier's evidence view is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these two accepts a version field. Every other write in the system is processed without any optimistic-concurrency check.

### 2.8. Nested Resource Retrieval and Request Validity

For any endpoint whose path contains resource identifiers — the path parameters used across the API are `id`, `applicatorId`, `projectId`, `specId`, `woId`, `appId`, and `warrantyId` — the server validates the identifiers' existence sequentially, left to right, and rejects the request immediately with the not-found error corresponding to the first identifier that does not resolve to an existing resource — before any later identifier, state check, or business rule is examined. The not-found catalog is: `ERR_COATING_SYSTEM_NOT_FOUND`, `ERR_VOC_REGULATION_NOT_FOUND`, `ERR_APPLICATOR_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_SPECIFICATION_NOT_FOUND`, `ERR_SUBSTITUTION_REQUEST_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_COATING_APPLICATION_NOT_FOUND`, `ERR_INSPECTION_REPORT_NOT_FOUND`, `ERR_WARRANTY_NOT_FOUND`, and `ERR_INVESTIGATION_NOT_FOUND` (all HTTP 404). A request addressing a coating system beneath a non-existent project therefore fails with `ERR_PROJECT_NOT_FOUND` before the system even considers the child identifier.

Independently of path resolution, a request body that is missing a required field, supplies a value of the wrong type, names an enumeration value outside the defined set, or violates an array cardinality rule — fewer than three spot film-thickness readings, zero adhesion readings, or a non-positive tested area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Validation Priority Order

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the first failing check determines the error returned. That order is:

1. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400), on every endpoint.
2. Role authorization for the target endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403), on every endpoint.
3. Existence of path resources, validated left to right (the not-found catalog of §2.8, HTTP 404), on every nested or parameterized endpoint.
4. State preconditions of the requested transition (`ERR_INVALID_STATE` or the state-specific aliases `ERR_SPEC_NOT_ISSUED`, `ERR_QUALIFICATION_NOT_CERTIFIED`, `ERR_WARRANTY_NOT_ACTIVE`, `ERR_COAT_NOT_CURED`, `ERR_HOLD_POINT_NOT_RELEASED`, `ERR_SYSTEM_OBSOLETE`, and `ERR_PROGRAM_NOT_ACTIVE`, HTTP 409), on every state-transition endpoint.
5. Segregation of duties on inspection filings (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, HTTP 403), on the two inspection-filing endpoints.
6. VOC compliance against the applicable regulation limit (`ERR_VOC_LIMIT_EXCEEDED`, HTTP 422), on specification issuance, substitution approval decisions, and coating-application recording.
7. Thinner usage within both the system's permitted maximum and the absolute cap (`ERR_THINNER_LIMIT_EXCEEDED`, HTTP 422), on coating-application recording.
8. Existence of a regulation window covering the evaluation time (`ERR_REGULATION_NOT_FOUND`, HTTP 422), on specification issuance and coating-application recording.
9. Work-order window conflicts (`ERR_WINDOW_CONFLICT`, HTTP 409), on work-order creation.
10. Regulation-window overlap or gap (`ERR_REGULATION_OVERLAP` or `ERR_REGULATION_GAP`, HTTP 409), on regulation creation and supersede.
11. Application-window containment and cure-window satisfaction (`ERR_APPLICATION_OUTSIDE_WINDOW` or `ERR_CURE_WINDOW_NOT_MET`, HTTP 422), on coating-application recording and mark-cured.
12. The cross-entity qualification gate (`ERR_QUALIFICATION_NOT_CERTIFIED`, HTTP 409), on work-order creation and begin-prep-inspection.
13. Coat-number uniqueness and count (`ERR_DUPLICATE_COAT` or `ERR_COAT_COUNT_EXCEEDED`, HTTP 409), on coating-application recording.
14. Substitution review-round, decision-reason, and film-build regression rules (`ERR_REVIEW_ROUND_EXHAUSTED`, `ERR_DECISION_REASON_REQUIRED`, or `ERR_DFT_REGRESSION`, HTTP 422), on substitution request-info and decide.
15. Adjudication fault-percentage consistency (`ERR_FAULT_PCT_MISMATCH`, HTTP 422), on investigation adjudication.
16. The warranty budget gate (`ERR_WARRANTY_BUDGET_EXCEEDED`, HTTP 422), on warranty issuance.
17. Referential linkability of named resources — coating system active, specification issued and current, work order completed for warranty issuance (`ERR_SYSTEM_IN_USE`, `ERR_SPEC_NOT_ISSUED`, or `ERR_WORK_ORDER_NOT_COMPLETED`, HTTP 409).

A request that fails an earlier check never reaches a later one: a malformed header masks every other defect; a segregation-of-duties violation on an inspection filing surfaces before any film-thickness verdict is computed; and a stale-version rejection under §2.7 is determined by the write it guards.

### 2.10. Time Window Semantics

The system uses two different interval conventions, and confusing them changes observable behavior.

**VOC regulation windows are half-open.** A regulation is in force from its `effective_from` instant (inclusive) up to but not including its `effective_to` instant. Two regulations for the same jurisdiction-and-method pair conflict — and the incoming one is rejected with `ERR_REGULATION_OVERLAP` — when the new window's `effective_from` falls strictly before the existing window's `effective_to` and, simultaneously, the existing window's `effective_from` falls strictly before the new window's `effective_to`. Under half-open semantics a window that begins exactly when its predecessor ends does not overlap it; such zero-gap abutment is not merely legal but is required of a successor at supersede time, where a gap of any size is rejected with `ERR_REGULATION_GAP`.

**Work-order application windows are closed.** A work order's window runs from `window_start` (inclusive) through `window_end` (inclusive). Two work orders on the same project and the same `asset_zone` conflict — and the incoming one is rejected with `ERR_WINDOW_CONFLICT` — when the new window's start falls at or before an existing window's end and, simultaneously, the existing window's start falls at or before the new window's end. Because both endpoints are inclusive, windows that merely touch — one starting at the exact instant another ends — still count as overlapping, so back-to-back scheduling on one zone is rejected. The candidate set for the conflict test is every work order on that project and zone in `SCHEDULED`, `PREP_INSPECTION`, `PREP_APPROVED`, `COATING_IN_PROGRESS`, or `ON_HOLD`; terminal work orders no longer participate. The equipment-corridor exception applies across zones: two work orders with different `asset_zone` values never conflict, no matter how their times overlap.

All datetime comparisons in these rules are made at second precision against the logical clock.

## 3. Business Logic & Workflows

### 3.1. The Coating System Catalogue and Data-Sheet Revision

Everything in the system ultimately traces back to a **coating system**: the manufacturer's published pairing of a surface-preparation standard with a multi-coat film build. A `TechnicalServiceEngineer` registers a system by supplying its unique `system_code` (for example a manufacturer's product code), the `manufacturer_name`, the required `surface_prep_standard` — one of `SSPC_SP10_NEAR_WHITE`, `SSPC_SP6_COMMERCIAL`, `SSPC_SP11_POWER_TOOL`, or `SSPC_SP1_SOLVENT` — the acceptable anchor-profile band `min_surface_profile_mils` through `max_surface_profile_mils` (the maximum must be at least the minimum), the `coat_count` (an integer from 1 to 4), the aggregate dry-film-thickness band `total_dft_min_mils` through `total_dft_max_mils`, the as-supplied `base_voc_gpl` and the recommended thinner's `thinner_voc_gpl` (both in grams per litre), and the minimum pull-off `adhesion_min_psi`. Two fields carry defaults: `is_competitor_system` defaults to false and is set true only when the record describes a competing, non-house system named in a substitution request; and `max_thinner_pct`, the maximum permitted thinner addition as a fraction of mixed volume, defaults to 0 and may range from 0 up to 0.25. A request that violates any of these shapes — an inverted profile band, a coat count outside 1 through 4, a thinner ceiling above one quarter of mixed volume — is rejected with `ERR_INVALID_REQUEST`. A newly registered system begins life `ACTIVE` with `spec_revision` set to 1.

Data sheets evolve. When the manufacturer issues a new revision, a `TechnicalServiceEngineer` revises the system: `spec_revision` increments by 1 and the system record's `version` increments by 1, while the system remains `ACTIVE` (revising a system that is no longer active fails with `ERR_SYSTEM_OBSOLETE`). Revision deliberately does **not** migrate history: specifications already issued keep the `pinned_spec_revision` they were issued against, so an issued spec always names the data-sheet revision that was current at its issuance. Revision does, however, invalidate pending work — every `DRAFT` specification that references the revised system is invalidated to `WITHDRAWN`, with the owning project's `version` incremented for each affected project.

When a system leaves the market entirely, a `TechnicalServiceEngineer` marks it `OBSOLETE`. Obsolescence is refused while the system is still load-bearing: if any specification in `DRAFT` or `ISSUED` references the system, the request fails with `ERR_SYSTEM_IN_USE`. When obsolescence succeeds, every substitution request that proposed this system and is still pending — in `SUBMITTED`, `UNDER_REVIEW`, or `MORE_INFO_REQUESTED` — is rejected outright, with its `decision_reason` recorded as "proposed system obsoleted".

### 3.2. VOC Regulation Windows and Compliance Arithmetic

Environmental compliance is anchored in the **VOC regulation**: a rule, owned by a `ComplianceOfficer`, stating that within one `jurisdiction_code` (for example a state, air-quality district, or national code) and for one `application_method` — `SPRAY_AIRLESS`, `SPRAY_CONVENTIONAL`, or `BRUSH_ROLLER` — no coating may be applied whose VOC exceeds `voc_limit_gpl` grams per litre during the half-open window from `effective_from` (inclusive) to `effective_to` (exclusive). A regulation is created `ACTIVE`. Creation enforces the window-uniqueness rule of §2.10 against every recorded regulation for the same jurisdiction-and-method pair, whether `ACTIVE` or `SUPERSEDED`: any overlap is rejected with `ERR_REGULATION_OVERLAP`.

Regulations are tightened over time by supersession rather than mutation. Superseding a regulation takes a payload of `new_voc_limit_gpl`, `new_effective_from`, and `new_effective_to`; the successor window must abut its predecessor with zero gap, meaning `new_effective_from` must equal the superseded regulation's `effective_to` exactly — any gap fails with `ERR_REGULATION_GAP`, any overlap with `ERR_REGULATION_OVERLAP`. On success the existing regulation becomes `SUPERSEDED` and a successor regulation is created `ACTIVE` carrying the successor window, the new limit, and the same `jurisdiction_code` and `application_method`.

Compliance arithmetic itself comes in two variants. The **as-supplied** variant is evaluated at specification issuance and again at substitution-approval review: the VOC figure is simply the coating system's `base_voc_gpl`, ignoring thinner entirely. The **as-applied** variant is evaluated once per recorded coat: the thinner fraction `thinner_pct_used` actually used is checked against the system's `max_thinner_pct` and against the absolute hard cap of 0.25 of mixed volume — exceeding either limit rejects the recording with `ERR_THINNER_LIMIT_EXCEEDED` — and the as-applied VOC is then the volume-weighted mix of the two contributions: `base_voc_gpl` scaled by one minus `thinner_pct_used`, plus `thinner_voc_gpl` scaled by `thinner_pct_used`. Whenever thinner is added and the thinner's VOC differs from the base coating's, the as-applied figure diverges from the as-supplied one. Both variants round the resulting VOC half-up to 1 decimal place (§2.6) and compare it against the covering regulation: the covering regulation is the `ACTIVE` one for the project's `jurisdiction_code` and the specification's `application_method` whose half-open window contains the evaluation time (issuance time for a specification, the coat's `applied_at` for an application); if no such regulation exists the operation fails with `ERR_REGULATION_NOT_FOUND`, and if the computed VOC exceeds the regulation's `voc_limit_gpl` the compliance check fails — note the boundary is inclusive, so a VOC exactly equal to the limit is compliant. At issuance and at substitution approval the failure is a rejection with `ERR_VOC_LIMIT_EXCEEDED`; at coat-recording time the consequences take the INVALID-coat form described in §3.6.

### 3.3. Applicator Qualification and the Quality History Score

An **applicator** is a contracting company that physically applies coatings. A `PlatformAdmin` registers one with a `company_name` and `contact_email`; the record begins in `REGISTERED` status with a `quality_history_score` of exactly 500 and a `consecutive_passed_inspections` streak of 0. The score is a running measure of workmanship on a scale from 0 to 1000, and the streak counts consecutive accepted inspection reports, resetting to 0 on any rejected one.

Certification happens under a **qualification program**, created by a `TechnicalServiceEngineer` with a unique `program_code`, the `coating_system_id` of the system it certifies applicators for, a `min_quality_history_score` floor, and three defaulted requirements: `min_consecutive_passed_inspections` defaults to 3, `requires_training` defaults to true, and `requires_equipment_audit` defaults to true. A program is created `ACTIVE`; the enumeration also admits `RETIRED`, and certification against a program that is not `ACTIVE` always fails.

An `ApplicatorRep` enrolls their company in a program, creating an **applicator qualification** in `CANDIDATE` status. Enrollment records the `program_id`; the `applicator_id` is fixed by the parent applicator in the path; `training_completed_at` (the timestamp of completed manufacturer training) may be null at creation; `equipment_audit_passed` defaults to false; and `suspension_count` starts at 0. From `CANDIDATE`, a `TechnicalServiceEngineer` certifies the qualification. Certification is OCC-guarded on the parent applicator per §2.7 — the request must carry `expected_applicator_version` matching the applicator's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412) — and then enforces five gates: the program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`); the applicator's `quality_history_score` must be at least the program's `min_quality_history_score` (`ERR_QUALITY_SCORE_TOO_LOW`); the applicator's `consecutive_passed_inspections` must be at least the program's `min_consecutive_passed_inspections` (`ERR_INSUFFICIENT_PASS_STREAK`); if the program's `requires_training` is true then `training_completed_at` must not be null (`ERR_TRAINING_MISSING`); and if the program's `requires_equipment_audit` is true then `equipment_audit_passed` must be true (`ERR_EQUIPMENT_AUDIT_MISSING`). On success the qualification becomes `CERTIFIED`, the applicator's `version` increments by 1, and — when this is the applicator's first certification — the applicator itself moves automatically from `REGISTERED` to `ACTIVE`.

The **quality history score** is recomputed chronologically, in `created_at` order of the triggering records, from five event families. A failed surface-preparation inspection subtracts 25 points. An accepted inspection report adds 10 points and increments `consecutive_passed_inspections` by 1. A rejected inspection report subtracts 75 points and resets `consecutive_passed_inspections` to 0. An environmentally non-compliant coating application subtracts 100 points. An adjudication of application error subtracts 150 points. The monthly decay sweep of §2.5 subtracts a further 5 points per elapsed calendar month that passed without any accepted inspection report. After every single event the score is clamped into the inclusive range 0 to 1000 — it can never go negative and never exceeds 1000. Every score-changing event also re-evaluates the suspension rule: if the resulting score has fallen below the `min_quality_history_score` of any program under which the applicator currently holds a `CERTIFIED` qualification, that qualification moves automatically to `SUSPENDED` and the work-order cascade below fires.

Suspension, reinstatement, and revocation complete the lifecycle. Suspending a `CERTIFIED` qualification — whether invoked by a `TechnicalServiceEngineer` or triggered by the score cascade — increments `suspension_count` by 1 (suspending anything not currently `CERTIFIED` fails with `ERR_QUALIFICATION_NOT_CERTIFIED`) and immediately places every work order naming this applicator that is in `SCHEDULED`, `PREP_INSPECTION`, or `PREP_APPROVED` into `ON_HOLD`. Reinstating a `SUSPENDED` qualification is permitted only while `suspension_count` is below 3 — a qualification that has already been suspended three times can never be reinstated again, and the attempt fails with `ERR_REINSTATE_LIMIT_EXCEEDED` — and only while the applicator's score is at least the program's floor (`ERR_QUALITY_SCORE_TOO_LOW`); reinstatement returns each `ON_HOLD` work order for this applicator to its pre-hold state, namely `SCHEDULED` when the order's `hold_point_prep_released` is false and `PREP_APPROVED` when it is true. Revoking moves the qualification to `REVOKED`, the terminal state of the qualification lifecycle, and is only available from `SUSPENDED` — revoking anything else fails with `ERR_QUALIFICATION_NOT_SUSPENDED`; revocation cancels every `ON_HOLD` work order for this applicator and touches nothing else, leaving already-issued warranties unaffected.

One further dimension of the lifecycle is probation. When a failure investigation concludes that a warranty claim arose from application error, the applicator qualification that was used on the failed work order moves automatically from `CERTIFIED` to `PROBATION` and the applicator's score takes the 150-point probation penalty. While on probation the applicator is on notice: accumulating 2 consecutive accepted inspection reports after entering probation automatically restores the qualification to `CERTIFIED`, whereas any rejected inspection report during probation automatically moves the qualification to `SUSPENDED` — incrementing `suspension_count` by 1 and firing the same work-order hold cascade as a manual suspension.

### 3.4. Projects, Specification Issuance, and Substitution Review

A **project** is the owner's umbrella for one coating engagement. A `ProjectEngineer` creates it with a `project_name`, the `owner_name`, the `jurisdiction_code` where the work occurs (which drives every VOC compliance check on the project), the `asset_type` — one of `BRIDGE`, `TANK_EXTERIOR`, `TANK_INTERIOR`, `PIPELINE`, or `STRUCTURAL_STEEL` — and a `warranty_budget_cents`, the owner-funded ceiling on total warranty exposure. The project begins in `PLANNING` with `committed_warranty_exposure_cents` at 0; that committed figure is recomputed as the sum of `exposure_cents` across all of the project's warranties in `ACTIVE` or `CLAIMED` status. The project lifecycle then advances automatically: the moment the project's first specification reaches `ISSUED`, the project moves from `PLANNING` to `SPECIFIED`, and the moment the project's first work order leaves `SCHEDULED`, the project moves from `SPECIFIED` to `IN_PROGRESS`. A `ProjectEngineer` completes an `IN_PROGRESS` project only when every work order on it has reached a terminal state — `COMPLETED` or `CANCELLED` — otherwise the completion fails with `ERR_OPEN_WORK_ORDERS_EXIST`. Cancellation is staged by how far the project has progressed. Cancelling a `PLANNING` project withdraws its `DRAFT` specifications. Cancelling a `SPECIFIED` project withdraws its `DRAFT` specifications, supersedes its `ISSUED` specifications, and cancels its `SCHEDULED` work orders. Cancelling an `IN_PROGRESS` project is permitted only when all of its work orders are already terminal (`ERR_OPEN_WORK_ORDERS_EXIST`), and it withdraws `DRAFT` specifications and supersedes `ISSUED` ones. `COMPLETED` and `CANCELLED` are terminal.

Within a project, a `ProjectEngineer` drafts a **project specification** naming a `coating_system_id` — which may be a house system or a competitor system — and the planned `application_method`. A draft may optionally carry `supersedes_specification_id`, a self-referential link to an earlier specification on the same project that this one revises; the project's first specification leaves it null. The draft's `project_id` is fixed by the parent in the path. A draft can be withdrawn at any time, moving it to `WITHDRAWN` — whether by an explicit withdrawal from a `ProjectEngineer`, or automatically as part of a project cancellation or a coating-system revision invalidation.

Issuance is the pivotal act that freezes a specification. When a `ProjectEngineer` issues a draft, the request must carry `expected_project_version` under §2.7 (mismatch: `ERR_STALE_VERSION`, HTTP 412), and four preconditions hold: the project must be in `PLANNING` or `SPECIFIED` (`ERR_PROJECT_NOT_SPECIFIABLE`); the referenced coating system must be `ACTIVE` (`ERR_SYSTEM_OBSOLETE`); the as-supplied VOC of §3.2 must not exceed the limit of the regulation that will be pinned (`ERR_VOC_LIMIT_EXCEEDED`), with that covering regulation itself required to exist (`ERR_REGULATION_NOT_FOUND`); and no other specification on this project may currently be `ISSUED` unless this issuance supersedes it through the draft's `supersedes_specification_id` link (`ERR_ACTIVE_SPEC_EXISTS`). On success the issuance stamps three frozen values onto the specification: `pinned_spec_revision` takes the coating system's `spec_revision` at this instant and is never migrated by later revisions; `pinned_voc_regulation_id` takes the `ACTIVE` regulation for the project's jurisdiction and the specification's application method whose half-open window contains the issuance time; and `voc_at_issuance_gpl` records the as-supplied VOC figure computed at issuance. Issuance increments the project's `version` by 1 — the mutation the OCC guard exists to serialize — and moves a `PLANNING` project to `SPECIFIED`. If the issued draft carried a `supersedes_specification_id`, the superseded specification moves to `SUPERSEDED`, every pending substitution request against it is rejected with `decision_reason` "specification superseded", and every `SCHEDULED` work order referencing it is cancelled. The same `ISSUED`-to-`SUPERSEDED` transition with the same cascades also fires automatically when a successor specification naming this one is issued, on project cancellation, or on coating-system revision invalidation.

When an owner names a competing system against an issued specification, an `OwnerRepresentative` files a **substitution request** carrying the `proposed_coating_system_id` and a free-text `rationale`; the challenged `specification_id` is fixed by the path. The request is born `SUBMITTED` with `review_round` at 1, and `max_review_rounds` — the ceiling on how many rounds of clarification the reviewer may demand — defaults to 3. A `TechnicalServiceEngineer` starts review, moving the request from `SUBMITTED` to `UNDER_REVIEW`; this requires the challenged specification to still be `ISSUED` (`ERR_SPEC_NOT_ISSUED`). From `UNDER_REVIEW` the reviewer may request more information, moving the request to `MORE_INFO_REQUESTED`, but only while `review_round` is still below `max_review_rounds` — once the round count has reached the cap the request fails with `ERR_REVIEW_ROUND_EXHAUSTED` and the reviewer is forced to a final decision. The owner answers by resubmitting with a fresh `rationale`, which returns the request from `MORE_INFO_REQUESTED` to `SUBMITTED` and increments `review_round` by 1.

The decision itself is a `TechnicalServiceEngineer` act on a request in `UNDER_REVIEW`, carrying a `decision` of approve or reject and a `decision_reason`. The `decision_reason` is required on both approval and rejection — its absence fails with `ERR_DECISION_REASON_REQUIRED` — and forbidden on every other transition of the request. Rejection moves the request to `REJECTED`, a terminal state. Approval is gated by three further checks: the proposed coating system must be `ACTIVE` (`ERR_SYSTEM_OBSOLETE`); the proposed system's as-supplied VOC must not exceed the `voc_limit_gpl` of the challenged specification's pinned regulation (`ERR_VOC_LIMIT_EXCEEDED`); and the proposed system must not regress the film build — its `total_dft_min_mils` must be at least the incumbent system's `total_dft_min_mils` (`ERR_DFT_REGRESSION`). An approved request becomes `APPROVED`, also terminal, and the approval automatically creates a new `DRAFT` specification on the same project whose `coating_system_id` is the proposed system and whose `supersedes_specification_id` is the challenged specification — the seed from which the `ProjectEngineer` issues the superseding specification.

### 3.5. Work Orders, Scheduling Windows, and the Surface-Preparation Hold Point

A **work order** schedules one applicator onto one zone of a project. A `ProjectEngineer` creates it with the `specification_id` of the specification being executed, the `applicator_id` of the company doing the work, a free-form `asset_zone` label, and the closed application window `window_start` through `window_end`; the `project_id` comes from the path. Creation enforces two cross-entity gates before the window check: the referenced specification must be `ISSUED` and current — not superseded (`ERR_SPEC_NOT_ISSUED`) — and the named applicator must hold a `CERTIFIED` qualification under a program whose `coating_system_id` matches the specification's coating system (`ERR_QUALIFICATION_NOT_CERTIFIED`). Then the closed-interval window-conflict rule of §2.10 runs against sibling work orders on the same project and zone, rejecting conflicts with `ERR_WINDOW_CONFLICT`. A new work order begins `SCHEDULED` with `hold_point_prep_released` false.

When the applicator is ready for the surface to be verified, an `ApplicatorRep` begins preparation inspection, moving the work order from `SCHEDULED` to `PREP_INSPECTION`; the certification gate is re-checked at this moment (`ERR_QUALIFICATION_NOT_CERTIFIED`), and if this is the project's first work order to leave `SCHEDULED` the project moves automatically from `SPECIFIED` to `IN_PROGRESS`.

The inspection itself is filed by an `Inspector` and is the system's first hold point. The filing carries four measured values: the `observed_prep_standard` (the same four-value SSPC enumeration as the system's required standard), the `measured_profile_mils` anchor profile, the `soluble_salt_ug_cm2` contamination reading, and the `ambient_dew_point_spread_c` — the steel temperature minus the dew point, in degrees Celsius. The filing's `work_order_id` is fixed by the path and its `inspector_id` is the filing inspector's `X-User-ID`. Segregation of duties is absolute here: the inspector filing a preparation inspection must not be an `ApplicatorRep` of the same work order's applicator, and the same `X-User-ID` may never perform both the preparation inspection and the coating application on one work order; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

The verdict is computed by the server at filing, never asserted. Four checks run against the coating system reached through the work order's specification. First, the `observed_prep_standard` must equal the system's required `surface_prep_standard` exactly, otherwise the reason `PREP_STANDARD_MISMATCH` is recorded. Second, the `measured_profile_mils` must lie within the closed band from `min_surface_profile_mils` to `max_surface_profile_mils` — both bounds inclusive — otherwise `PROFILE_OUT_OF_RANGE` is recorded. Third, the `soluble_salt_ug_cm2` must be at most 10.0 micrograms per square centimetre — a reading of exactly 10.0 passes — otherwise `SALT_EXCEEDED` is recorded; however, when the project's `asset_type` is `TANK_INTERIOR` the salt limit tightens to 5.0, so a reading of 7.0 that would pass on a bridge fails on an interior tank lining. Fourth, the `ambient_dew_point_spread_c` must be at least 3.0 degrees — exactly 3.0 passes — otherwise `DEW_POINT_SPREAD_TOO_SMALL` is recorded. The inspection's `result` is `PASSED` when no reasons were recorded and `FAILED` otherwise, with `failure_reasons` holding the ordered list of the violated checks (empty on a pass).

The verdict drives the work order. A `PASSED` filing moves the work order automatically from `PREP_INSPECTION` to `PREP_APPROVED` and sets `hold_point_prep_released` to true — the hold point is released and coating may begin. A `FAILED` filing bounces the work order back to `SCHEDULED` and assesses the 25-point preparation-failure penalty against the applicator's `quality_history_score`, which may in turn cascade a certified qualification into `SUSPENDED` per §3.3.

The remainder of the work-order lifecycle is bookkeeping attached to those gates. A `ProjectEngineer` completes a work order and may cancel a `SCHEDULED` one; cancellation of a scheduled order also arrives automatically when its specification is superseded. Suspension, reinstatement, and revocation of the applicator's qualification move the order into and out of `ON_HOLD` exactly as §3.3 describes: `SCHEDULED`, `PREP_INSPECTION`, and `PREP_APPROVED` orders freeze to `ON_HOLD` on suspension; reinstatement returns them to `SCHEDULED` when `hold_point_prep_released` is false and to `PREP_APPROVED` when it is true; and revocation cancels them outright. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Coating Application, Cure, and Inspection Verdicts

Once the hold point is released, an `ApplicatorRep` records each coat as a **coating application**. The recording names the 1-based `coat_number`, the `applied_at` timestamp, and optionally `thinner_pct_used`, the thinner fraction actually mixed, which defaults to 0. The `work_order_id` is fixed by the path. Three constraint families guard the recording. The hold point must be released: attempting a coat before a passing preparation inspection is rejected with `ERR_HOLD_POINT_NOT_RELEASED` (HTTP 409). The `applied_at` instant must fall inside the work order's closed window from `window_start` to `window_end` — either boundary inclusive — otherwise `ERR_APPLICATION_OUTSIDE_WINDOW` (HTTP 422). And the coat index must be legitimate: `coat_number` must be unique within the work order among all applications whose cure state is not `INVALID` (a duplicate is `ERR_DUPLICATE_COAT`, HTTP 409) and must not exceed the coating system's `coat_count` (an excess is `ERR_COAT_COUNT_EXCEEDED`, HTTP 409).

Every recorded coat carries two parallel status dimensions, stored as the `cure_state` and `acceptance_state` fields. The cure dimension `cure_state` begins at `WET`; the acceptance dimension `acceptance_state` begins at `UNTESTED`. At recording time the server computes the as-applied VOC of §3.2 — enforcing the thinner ceiling, so a `thinner_pct_used` beyond the system's `max_thinner_pct` or beyond the absolute 0.25 hard cap is rejected with `ERR_THINNER_LIMIT_EXCEEDED` — stores it as `applied_voc_gpl`, and evaluates it against the regulation covering the project's jurisdiction and the specification's application method at `applied_at` (no covering regulation: `ERR_REGULATION_NOT_FOUND`). The outcome is stored as `voc_compliant`; the boundary is inclusive, so an as-applied VOC exactly equal to the limit is compliant. The first coat recorded on a work order moves the order automatically from `PREP_APPROVED` to `COATING_IN_PROGRESS`. When the computed coat is non-compliant, the recording still stands but the system marks the coat's cure dimension `INVALID` instead of leaving it `WET`: the applicator's score takes the 100-point VOC-violation penalty (which may cascade a certification into suspension per §3.3), the work order remains `COATING_IN_PROGRESS`, and the offending coat must simply be done over — because `INVALID` applications do not count for uniqueness, the same `coat_number` may be re-used by a fresh recording.

A `WET` coat cures with time: an `ApplicatorRep` marks a coat cured only once at least twenty-four hours — one full day per coat — have elapsed since its `applied_at`; an earlier attempt fails with `ERR_CURE_WINDOW_NOT_MET` (HTTP 422), and success moves the cure dimension to `CURED`. Testing is the rule, but on structural steel it can be waived: a `TechnicalServiceEngineer` may move a coat's acceptance dimension from `UNTESTED` to `WAIVED`, which requires the coat to be `CURED` (`ERR_COAT_NOT_CURED`, HTTP 409) and the project's `asset_type` to be `STRUCTURAL_STEEL` — waivers on any other asset type are rejected with `ERR_WAIVER_NOT_PERMITTED` (HTTP 422).

Otherwise an `Inspector` files an **inspection report** against a cured coat — filing against a coat not yet `CURED` fails with `ERR_COAT_NOT_CURED`, and the same segregation-of-duties rule as §3.5 bars any inspector whose `X-User-ID` overlaps the applicator side of the work order (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). The report's `coating_application_id` is fixed by the path, its `inspector_id` is the filer's `X-User-ID`, and the payload carries the measurements: `spot_dft_readings_mils`, a list of at least three spot dry-film-thickness readings in mils, one per gage measurement; `adhesion_readings_psi`, a list of at least one pull-off adhesion reading; `holiday_count`, the number of pinholes or holidays found; and `tested_area_m2`, the tested surface area in square metres, which must be greater than 0. Too few readings or a non-positive area is `ERR_INVALID_REQUEST`.

Filing the report computes three sub-verdicts, moves the coat's acceptance dimension from `UNTESTED` to `TESTED`, and updates the applicator's score and streak per §3.3: a rejected report resets `consecutive_passed_inspections` to 0 and subtracts 75 points, while an accepted one increments the streak by 1 and adds 10 points.

The **film-thickness verdict** `dft_verdict` comes in two variants selected by the coating system's `surface_prep_standard`. Under the default spot-average variant, the average of `spot_dft_readings_mils` is rounded half-up to 1 decimal place before any comparison, and the coat passes when that rounded average is at least the system's `total_dft_min_mils`, at most its `total_dft_max_mils`, and no individual spot reading falls below eighty percent of `total_dft_min_mils` — the 80/20 rule's single-spot floor of 0.8. Under the gage 80/20 variant, used when the system's `surface_prep_standard` is `SSPC_SP11_POWER_TOOL`, the verdict is count-based rather than average-based: the coat passes when the number of spots individually within the closed band from `total_dft_min_mils` to `total_dft_max_mils` is at least the result of rounding up eighty percent of the total number of readings — so with five readings at least four must be in band — and under this variant the average may fall below the specification minimum while the coat still passes.

The **adhesion verdict** `adhesion_verdict` is a single comparison: the coat passes when the smallest reading in `adhesion_readings_psi` is at least the system's `adhesion_min_psi`. The **holiday verdict** `holiday_verdict` computes the defect density as `holiday_count` divided by `tested_area_m2`, in full precision, and passes when the density is at most the applicable limit — an inclusive boundary, so a density exactly equal to the limit passes. The limit is 0.1 holidays per square metre for every asset type except `TANK_INTERIOR`, where it tightens to 0.0 and any single holiday fails the coat. The report's `overall_verdict` is `ACCEPTED` when all three sub-verdicts pass and `REJECTED` otherwise.

A `ProjectEngineer` completes a `COATING_IN_PROGRESS` work order only when every coat on it is fully resolved: each application's cure dimension must be `CURED` and its acceptance dimension must be either `TESTED` with the latest report's verdict `ACCEPTED`, or `WAIVED` — anything outstanding fails with `ERR_UNRESOLVED_COATS_EXIST` (HTTP 409). Completion also recomputes the applicator's `consecutive_passed_inspections`. Both dimensions' terminal values — `CURED` or `INVALID` for cure, `TESTED` or `WAIVED` for acceptance — are final for the coat they describe.

### 3.7. Warranties, Budget Exposure, and Failure Adjudication

A **warranty** binds the manufacturer and the applicator into joint liability for finished work. A `ProjectEngineer` issues one against a completed job: the `work_order_id` must name a work order in `COMPLETED` (`ERR_WORK_ORDER_NOT_COMPLETED`, HTTP 409), and the payload fixes the `term_years` — an integer term from 1 to 20 years — and the `exposure_cents`, the total joint liability the two parties share. The project's budget gate runs at issuance: the project's `committed_warranty_exposure_cents` plus the new `exposure_cents` must not exceed its `warranty_budget_cents`; the boundary is inclusive, so landing exactly on the budget is allowed and only a strictly greater sum is rejected with `ERR_WARRANTY_BUDGET_EXCEEDED` (HTTP 422). The `project_id` comes from the path, and issuance increments the project's committed exposure by the new warranty's `exposure_cents`.

Liability between the two parties is expressed as the warranty's `manufacturer_fault_pct`, which begins at 50 and stays there until a failure investigation decides otherwise. The split into shares follows one invariant at all times: `material_share_cents` plus `application_share_cents` must equal `exposure_cents` exactly. At issuance the manufacturer's `material_share_cents` is half the exposure — the exposure multiplied by 0.50, rounded half-up to a whole cent — and the applicator's `application_share_cents` is the remainder, absorbing any rounding residue. When an adjudication later sets the fault percentage to some value f, the manufacturer's share is recomputed as the exposure multiplied by f and divided by 100, rounded half-up, with the applicator's share again taking the remainder.

A warranty is born `ACTIVE`. An `OwnerRepresentative` files a claim against it — which requires it to still be `ACTIVE` (`ERR_WARRANTY_NOT_ACTIVE`, HTTP 409) — supplying the observed `defect_mode` (one of `ADHESION_LOSS`, `CRACKING`, `CORROSION_UNDERFILM`, `DELAMINATION`, or `COLOR_GLOSS_DRIFT`) and `evidence_notes` summarizing the field evidence. Claiming moves the warranty to `CLAIMED` and automatically opens a **failure investigation** in `OPENED` status with `opened_by` recorded as `OWNER` (the enumeration also admits `MANUFACTURER` and `APPLICATOR`), carrying the claim's defect mode and evidence notes. The investigation's `warranty_id` is fixed by the warranty under which it was opened. Separately, a `TechnicalServiceEngineer` may void an `ACTIVE` warranty for documented applicator fraud or work-order misrepresentation; the void requires a non-empty free-text `void_reason` (`ERR_VOID_REASON_REQUIRED`, HTTP 422), moves the warranty to `VOIDED`, and releases its exposure from the project's committed total.

Investigation proceeds in two steps, both by a `TechnicalServiceEngineer`. Beginning evidence moves the investigation from `OPENED` to `EVIDENCE_GATHERING`. Adjudication then closes it with an `outcome` of `PRODUCT_DEFECT`, `APPLICATION_ERROR`, `SHARED`, or `NO_DEFECT`, moving the investigation from `EVIDENCE_GATHERING` to `ADJUDICATED_PRODUCT_DEFECT`, `ADJUDICATED_APPLICATION_ERROR`, `ADJUDICATED_SHARED`, or `CLOSED_NO_DEFECT` respectively — and an `adjudicated_fault_pct` — the final manufacturer fault percentage from 0 to 100, settable only through adjudication — whose consistency with the outcome is strictly enforced. A pure product defect means total manufacturer fault: the adjudicated percentage must equal exactly 100. A pure application error means zero manufacturer fault: the percentage must equal exactly 0. A shared outcome requires the percentage to lie strictly between 0 and 100. A no-defect outcome carries no fault split at all: the percentage must be omitted or null. Any inconsistency between outcome and percentage is rejected with `ERR_FAULT_PCT_MISMATCH` (HTTP 422).

Adjudication resolves the warranty and reallocates money and blame. Any of the three defect outcomes moves the warranty to `RESOLVED`: the warranty's `manufacturer_fault_pct` is set to the adjudicated percentage and the liability shares are re-split per the formula above — on a product-defect outcome the manufacturer share pays the full exposure; on an application-error outcome the blame cascade extends further, moving the applicator qualification used on the warranty's work order from `CERTIFIED` to `PROBATION` and applying the 150-point probation penalty to the applicator's score per §3.3. A no-defect outcome instead moves the warranty to `DENIED`. Either way — resolved or denied — the warranty's `exposure_cents` is released from the project's `committed_warranty_exposure_cents`, because only warranties still in `ACTIVE` or `CLAIMED` count against the budget. `RESOLVED`, `DENIED`, and `VOIDED` are terminal for the warranty, and all four adjudicated states are terminal for the investigation.

Finally, the system exposes flat, cross-parent read routes for reverse reachability — qualifications across a program, specifications across projects, substitution requests, work orders, inspection reports, and warranties — each supporting the same pagination contract of §2.3 and the filter query parameters itemized in §4, so that an auditor can walk the graph from any direction without knowing the parent identifiers in advance.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or annotate an existing resource return `200 OK`. List and single-resource reads return `200 OK`. The table below is a summary only: request payloads, computed fields, preconditions, and side effects are governed by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coating/_clock/set_current_utc` | Set the server's logical clock; crossing a month boundary fires the score decay sweep | PlatformAdmin |
| POST | `/coating/coating-systems` | Register a coating system (house or competitor) | TechnicalServiceEngineer |
| GET | `/coating/coating-systems` | List coating systems (filters: `status`, `is_competitor_system`) | Any authenticated role |
| GET | `/coating/coating-systems/{id}` | Get one coating system | Any authenticated role |
| POST | `/coating/coating-systems/{id}/revise` | Issue a new technical data-sheet revision; issued specs keep their pin, drafts are withdrawn | TechnicalServiceEngineer |
| POST | `/coating/coating-systems/{id}/obsolete` | Mark a system OBSOLETE; pending substitution requests proposing it are rejected | TechnicalServiceEngineer |
| POST | `/coating/voc-regulations` | Create a VOC regulation window for a jurisdiction-and-method pair | ComplianceOfficer |
| GET | `/coating/voc-regulations` | List regulations (filters: `jurisdiction_code`, `application_method`) | Any authenticated role |
| GET | `/coating/voc-regulations/{id}` | Get one regulation | Any authenticated role |
| POST | `/coating/voc-regulations/{id}/supersede` | Supersede a regulation; successor window must abut with zero gap | ComplianceOfficer |
| POST | `/coating/applicators` | Register an applicator company | PlatformAdmin |
| GET | `/coating/applicators` | List applicators (filter: `status`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer |
| GET | `/coating/applicators/{id}` | Get one applicator | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| POST | `/coating/qualification-programs` | Create a qualification program bound to a coating system | TechnicalServiceEngineer |
| GET | `/coating/qualification-programs` | List qualification programs (filter: `coating_system_id`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| GET | `/coating/qualification-programs/{id}` | Get one program | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| POST | `/coating/applicators/{applicatorId}/qualifications` | Enroll an applicator in a program (CANDIDATE) | ApplicatorRep |
| GET | `/coating/applicators/{applicatorId}/qualifications` | List an applicator's qualifications | PlatformAdmin, TechnicalServiceEngineer, ComplianceOfficer, ApplicatorRep |
| GET | `/coating/applicators/{applicatorId}/qualifications/{id}` | Get one qualification | PlatformAdmin, TechnicalServiceEngineer, ComplianceOfficer, ApplicatorRep |
| POST | `/coating/applicators/{applicatorId}/qualifications/{id}/certify` | Certify a CANDIDATE qualification (OCC-guarded on the applicator's version) | TechnicalServiceEngineer |
| POST | `/coating/applicators/{applicatorId}/qualifications/{id}/suspend` | Suspend a CERTIFIED qualification | TechnicalServiceEngineer |
| POST | `/coating/applicators/{applicatorId}/qualifications/{id}/reinstate` | Reinstate a SUSPENDED qualification (lifetime maximum three suspensions) | TechnicalServiceEngineer |
| POST | `/coating/applicators/{applicatorId}/qualifications/{id}/revoke` | Revoke a SUSPENDED qualification (terminal) | TechnicalServiceEngineer |
| POST | `/coating/projects` | Create a project | ProjectEngineer |
| GET | `/coating/projects` | List projects (filter: `status`) | Any authenticated role |
| GET | `/coating/projects/{id}` | Get one project | Any authenticated role |
| POST | `/coating/projects/{id}/complete` | Complete a project (all work orders terminal) | ProjectEngineer |
| POST | `/coating/projects/{id}/cancel` | Cancel a project with the staged specification and work-order cascades | ProjectEngineer |
| POST | `/coating/projects/{projectId}/specifications` | Create a DRAFT specification for a project | ProjectEngineer |
| GET | `/coating/projects/{projectId}/specifications` | List a project's specifications (filter: `status`) | Any authenticated role |
| GET | `/coating/projects/{projectId}/specifications/{id}` | Get one specification | Any authenticated role |
| POST | `/coating/projects/{projectId}/specifications/{id}/issue` | Issue a specification; pins system revision and VOC regulation (OCC-guarded on the project's version) | ProjectEngineer |
| POST | `/coating/projects/{projectId}/specifications/{id}/withdraw` | Withdraw a DRAFT specification | ProjectEngineer |
| POST | `/coating/specifications/{specId}/substitution-requests` | File a substitution request naming a competing system against an ISSUED spec | OwnerRepresentative |
| GET | `/coating/specifications/{specId}/substitution-requests` | List substitution requests for a spec (filter: `status`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative |
| GET | `/coating/specifications/{specId}/substitution-requests/{id}` | Get one substitution request | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative |
| POST | `/coating/specifications/{specId}/substitution-requests/{id}/start-review` | Move SUBMITTED to UNDER_REVIEW | TechnicalServiceEngineer |
| POST | `/coating/specifications/{specId}/substitution-requests/{id}/request-info` | Move UNDER_REVIEW to MORE_INFO_REQUESTED | TechnicalServiceEngineer |
| POST | `/coating/specifications/{specId}/substitution-requests/{id}/resubmit` | Move MORE_INFO_REQUESTED back to SUBMITTED, incrementing the review round | OwnerRepresentative |
| POST | `/coating/specifications/{specId}/substitution-requests/{id}/decide` | Approve or reject an UNDER_REVIEW substitution | TechnicalServiceEngineer |
| POST | `/coating/projects/{projectId}/work-orders` | Create a work order (closed-interval window; applicator must be CERTIFIED for the spec's system) | ProjectEngineer |
| GET | `/coating/projects/{projectId}/work-orders` | List a project's work orders (filter: `status`) | Any authenticated role |
| GET | `/coating/projects/{projectId}/work-orders/{id}` | Get one work order | Any authenticated role |
| POST | `/coating/projects/{projectId}/work-orders/{id}/begin-prep-inspection` | Move SCHEDULED to PREP_INSPECTION | ApplicatorRep |
| POST | `/coating/projects/{projectId}/work-orders/{id}/complete` | Complete a work order (all coats resolved) | ProjectEngineer |
| POST | `/coating/projects/{projectId}/work-orders/{id}/cancel` | Cancel a SCHEDULED work order | ProjectEngineer |
| POST | `/coating/work-orders/{woId}/prep-inspections` | Inspector files a surface-preparation inspection; the verdict is computed at filing | Inspector |
| GET | `/coating/work-orders/{woId}/prep-inspections` | List preparation inspections for a work order | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| GET | `/coating/prep-inspections/{id}` | Get one preparation inspection | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| POST | `/coating/work-orders/{woId}/applications` | Record a coat application (hold point must be released; VOC computed and checked) | ApplicatorRep |
| GET | `/coating/work-orders/{woId}/applications` | List coats for a work order | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| GET | `/coating/applications/{id}` | Get one coating application | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| POST | `/coating/work-orders/{woId}/applications/{id}/mark-cured` | Mark a coat cured (twenty-four-hour cure window) | ApplicatorRep |
| POST | `/coating/work-orders/{woId}/applications/{id}/waive-testing` | Waive testing (STRUCTURAL_STEEL projects only) | TechnicalServiceEngineer |
| POST | `/coating/work-orders/{woId}/applications/{appId}/inspection-reports` | Inspector files a film/adhesion/holiday inspection report; verdicts computed at filing | Inspector |
| GET | `/coating/work-orders/{woId}/applications/{appId}/inspection-reports` | List inspection reports for a coat | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| GET | `/coating/inspection-reports/{id}` | Get one inspection report | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| POST | `/coating/projects/{projectId}/warranties` | Issue a joint-liability warranty on a COMPLETED work order | ProjectEngineer |
| GET | `/coating/projects/{projectId}/warranties` | List a project's warranties (filter: `status`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |
| GET | `/coating/projects/{projectId}/warranties/{id}` | Get one warranty | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |
| POST | `/coating/projects/{projectId}/warranties/{id}/claim` | Owner files a warranty claim; opens a failure investigation | OwnerRepresentative |
| POST | `/coating/projects/{projectId}/warranties/{id}/void` | Void a warranty for fraud or misrepresentation | TechnicalServiceEngineer |
| GET | `/coating/warranties/{warrantyId}/investigations` | List investigations for a warranty | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |
| GET | `/coating/warranties/{warrantyId}/investigations/{id}` | Get one investigation | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |
| POST | `/coating/warranties/{warrantyId}/investigations/{id}/begin-evidence` | Move OPENED to EVIDENCE_GATHERING | TechnicalServiceEngineer |
| POST | `/coating/warranties/{warrantyId}/investigations/{id}/adjudicate` | Adjudicate with outcome PRODUCT_DEFECT, APPLICATION_ERROR, SHARED, or NO_DEFECT | TechnicalServiceEngineer |
| GET | `/coating/qualification-programs/{id}/qualifications` | List qualifications enrolled under one program | PlatformAdmin, TechnicalServiceEngineer, ComplianceOfficer |
| GET | `/coating/specifications` | Filtered list of specifications across projects (filters: `project_id`, `coating_system_id`, `pinned_voc_regulation_id`, `supersedes_specification_id`, `status`) | Any authenticated role |
| GET | `/coating/specifications/{id}` | Get one specification by id (flat route) | Any authenticated role |
| GET | `/coating/substitution-requests` | Filtered list of substitution requests (filters: `proposed_coating_system_id`, `status`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative |
| GET | `/coating/substitution-requests/{id}` | Get one substitution request by id (flat route) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative |
| GET | `/coating/work-orders` | Filtered list of work orders (filters: `project_id`, `specification_id`, `applicator_id`, `status`) | Any authenticated role |
| GET | `/coating/work-orders/{id}` | Get one work order by id (flat route) | Any authenticated role |
| GET | `/coating/inspection-reports` | Filtered list of inspection reports (filter: `coating_application_id`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, ComplianceOfficer, Inspector, ApplicatorRep |
| GET | `/coating/warranties` | Filtered list of warranties (filters: `project_id`, `work_order_id`, `status`) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |
| GET | `/coating/warranties/{id}` | Get one warranty by id (flat route) | PlatformAdmin, TechnicalServiceEngineer, ProjectEngineer, OwnerRepresentative, ComplianceOfficer |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API can return and its HTTP status code. The conditions under which each error is raised are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_COATING_SYSTEM_NOT_FOUND` | 404 |
| `ERR_VOC_REGULATION_NOT_FOUND` | 404 |
| `ERR_APPLICATOR_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_QUALIFICATION_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_SPECIFICATION_NOT_FOUND` | 404 |
| `ERR_SUBSTITUTION_REQUEST_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_COATING_APPLICATION_NOT_FOUND` | 404 |
| `ERR_INSPECTION_REPORT_NOT_FOUND` | 404 |
| `ERR_WARRANTY_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SPEC_NOT_ISSUED` | 409 |
| `ERR_ACTIVE_SPEC_EXISTS` | 409 |
| `ERR_PROJECT_NOT_SPECIFIABLE` | 409 |
| `ERR_OPEN_WORK_ORDERS_EXIST` | 409 |
| `ERR_SYSTEM_OBSOLETE` | 409 |
| `ERR_SYSTEM_IN_USE` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_QUALITY_SCORE_TOO_LOW` | 409 |
| `ERR_INSUFFICIENT_PASS_STREAK` | 409 |
| `ERR_TRAINING_MISSING` | 409 |
| `ERR_EQUIPMENT_AUDIT_MISSING` | 409 |
| `ERR_QUALIFICATION_NOT_CERTIFIED` | 409 |
| `ERR_QUALIFICATION_NOT_SUSPENDED` | 409 |
| `ERR_REINSTATE_LIMIT_EXCEEDED` | 409 |
| `ERR_VOC_LIMIT_EXCEEDED` | 422 |
| `ERR_THINNER_LIMIT_EXCEEDED` | 422 |
| `ERR_REGULATION_NOT_FOUND` | 422 |
| `ERR_REGULATION_OVERLAP` | 409 |
| `ERR_REGULATION_GAP` | 409 |
| `ERR_WINDOW_CONFLICT` | 409 |
| `ERR_APPLICATION_OUTSIDE_WINDOW` | 422 |
| `ERR_CURE_WINDOW_NOT_MET` | 422 |
| `ERR_HOLD_POINT_NOT_RELEASED` | 409 |
| `ERR_COAT_NOT_CURED` | 409 |
| `ERR_DUPLICATE_COAT` | 409 |
| `ERR_COAT_COUNT_EXCEEDED` | 409 |
| `ERR_UNRESOLVED_COATS_EXIST` | 409 |
| `ERR_WAIVER_NOT_PERMITTED` | 422 |
| `ERR_REVIEW_ROUND_EXHAUSTED` | 422 |
| `ERR_DECISION_REASON_REQUIRED` | 422 |
| `ERR_DFT_REGRESSION` | 422 |
| `ERR_FAULT_PCT_MISMATCH` | 422 |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 |
| `ERR_WORK_ORDER_NOT_COMPLETED` | 409 |
| `ERR_WARRANTY_BUDGET_EXCEEDED` | 422 |
| `ERR_VOID_REASON_REQUIRED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |
