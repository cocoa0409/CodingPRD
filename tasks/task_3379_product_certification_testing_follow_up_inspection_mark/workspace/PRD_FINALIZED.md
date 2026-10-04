# Product Certification Followup API — Product Requirements Document

## 1. Introduction

Product safety certification is not a one-time laboratory event but a continuing relationship among three parties: the manufacturer whose product carries the certification mark, the certification body whose engineers test and decide, and the authorities having jurisdiction who accept certified or field-evaluated equipment in their territory. This document specifies the Product Certification Followup API, a system that administers that relationship end to end. It covers the registration of standards with their construction requirements and performance test protocols; the opening of certification projects with standards selection pinned at creation; sample submission, triage, and laboratory testing against the pinned edition; the documentation of certified construction as frozen, revisable records; certification issuance as a listing report that constrains permitted component variations; periodic follow-up inspection of the factories producing certified product; controlled component substitution with mandatory pre-implementation evaluation; mark licensing with label authorization, counting, and serial traceability; field evaluation of installed, never-certified equipment with jurisdictional acceptance; and — when conformity breaks down — suspension, withdrawal, and public notice.

The system is built around segregation of duties and evidentiary discipline. The engineer who records a test result may not decide the certification that depends on it; the representative of a manufacturer may act only on that manufacturer's own resources; an authority having jurisdiction decides acceptance only for installations in its own territory. A single logical clock drives every time-dependent behavior — standard effectiveness windows, inspection overdue marking, certification expiry, withdrawal enforcement, and conformity aging — so that the passage of time is itself an administered, testable input rather than a side effect of the host machine.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level structures, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly seven roles: `CertificationBodyAdmin`, `ManufacturerRep`, `TestEngineer`, `CertificationReviewer`, `FactoryInspector`, `ComplianceOfficer`, and `AHJAuthority`. A request that omits either header, carries an `X-User-Role` that is not one of the declared roles, or — for an entity-backed role — carries an `X-User-ID` that is not the `id` of an instance of the backing entity is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `ManufacturerRep`, `X-User-ID` is the `id` of the acting `Manufacturer`; ownership checks on any resource that references a `Manufacturer` compare the resource's `manufacturer_id` field to `X-User-ID`. A `ManufacturerRep` may mutate only resources whose `manufacturer_id` equals their own `X-User-ID` — this scope covers certification projects, samples, construction records, substitution requests, mark licenses, label batches, and field evaluations. When `X-User-Role` is `AHJAuthority`, `X-User-ID` is the `id` of the acting `Jurisdiction`, and an `AHJAuthority` may decide acceptance only on a field evaluation whose `site_jurisdiction_id` equals that `X-User-ID`. A violation of either ownership scope is rejected with `ERR_FORBIDDEN` (HTTP 403).

The remaining five roles are opaque. When `X-User-Role` is `CertificationBodyAdmin`, `TestEngineer`, `CertificationReviewer`, `FactoryInspector`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `triaged_by` on a sample, `recorded_by` on a test result, `decided_by` on a project or substitution decision, `inspector_ref` on an inspection, or `evaluated_by` on a field evaluation — but does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system — manufacturers, factories, standards, jurisdictions, certification projects, samples, construction records, certifications, substitution requests, follow-up inspections, mark licenses, label batches, field evaluations, and withdrawal notices — carries four system-managed properties. `id` is a server-minted UUID with no type prefix, rendered in the canonical RFC 4122 string form: 32 lowercase hexadecimal digits in five hyphen-separated groups of 8, 4, 4, 4, and 12 (for example `3f6b8a2e-1c4d-4e5f-8a9b-0123456789ab`). `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation. `version` is an integer that increments by 1 on every mutation of the resource.

Automatic transitions and cascades count as mutations. When the system transitions a resource without a client request targeting it — a mark license becoming `EXHAUSTED` after a batch issuance, a certification suspended by a critical inspection finding, a construction record superseded by a newer revision — the mutated resource's `updated_at` refreshes and its `version` increments.

### 2.5. The Logical Clock and the Time Sweep

All time-dependent behavior in the system reads a single logical clock. At startup the logical clock stands at exactly 2026-09-01T00:00:00Z, and it never falls back to the host's wall clock. A `CertificationBodyAdmin` advances it through an admin-only test-driving capability by supplying a target instant in `to_iso8601`; the response echoes the new `current_utc`.

Setting the clock triggers a sweep with five effects, each applied against the new current time. First, withdrawal enforcement: every `PUBLISHED` withdrawal notice whose `effective_on` is at or before the current time becomes `EFFECTIVE`, driving its certification to `WITHDRAWN` with the full cascade described in §3.9. Second, certification expiry: every `ACTIVE` certification whose `expires_on` is set and is at or before the current time becomes `EXPIRED`; `SUSPENDED` certifications do not expire. Third, overdue marking: every `SCHEDULED` inspection whose `scheduled_for` is before the current time becomes `OVERDUE`. Fourth, standard refresh: every standard's `status` is recomputed from its effectiveness window per §2.6. Fifth, conformity aging: the `conformity_score` of every `STANDARD`-regime factory is recomputed, so findings that have aged out of the trailing 24-month window stop counting; `PROBATION`-regime scores are time-invariant and are never recomputed on the sweep.

### 2.6. Standard Editions and Their Effectiveness Windows

A standard edition's effectiveness window is half-open: it begins at `effective_from` (inclusive) and ends at `effective_to` (exclusive), and a null `effective_to` means the edition is open-ended. A standard's `status` is derived from the logical clock against this window: before `effective_from` the edition is `UPCOMING`; at or after `effective_from` and before `effective_to` it is `ACTIVE`; at or after `effective_to` it is `RETIRED`. The derivation is refreshed on every clock sweep.

Editions of the same standard share the pair of `category_code` and `standard_code`, and their effectiveness windows must never overlap. When a new edition is registered, its window is compared against every existing edition of the same pair, in any status: if the new edition's `effective_from` falls before the existing edition's end (treating an open-ended edition as never ending) and the existing edition's `effective_from` falls before the new edition's end (likewise), the registration is rejected with `ERR_STANDARD_EDITION_OVERLAP` (HTTP 409). Because both comparisons are strict, adjacency is legal — one edition's `effective_to` may equal another edition's `effective_from`, and two such touching windows do not overlap.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and no other endpoint takes a version field.

- Creating a construction-record revision (`POST /certification/projects/{id}/construction-records`) requires the request to carry `expected_project_version`, the `version` of the project as the client last observed it. Creating a revision legitimately supersedes the previously `FROZEN` record, so a writer holding a stale project version would silently supersede a revision it never saw.
- Implementing an approved substitution request (`POST /certification/substitution-requests/{id}/implement`) requires the request to carry `expected_certification_version`, the `version` of the certification as the client last observed it. Implementation re-pins the certification's construction revision, so a stale writer would re-pin on top of a certification state it never saw — for example after a suspend-and-reinstate cycle.

In both cases the field is non-optional. If the supplied value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no mutation occurs.

### 2.8. The Validation Pipeline

Every request is validated against an ordered pipeline, and a failure at an earlier stage produces that stage's error rather than a later stage's. The stages, in order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present, the role must be declared, and for entity-backed roles the `X-User-ID` must resolve to an instance of the backing entity; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role permission** — the role must be permitted on this endpoint; otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Ownership scope** — an entity-backed actor must own the target resource: a `ManufacturerRep`'s `X-User-ID` must equal the resource's `manufacturer_id`, and an `AHJAuthority`'s `X-User-ID` must equal the field evaluation's `site_jurisdiction_id`; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. **Existence** — every referenced resource (project, sample, certification, license, batch, inspection, notice, standard, factory, manufacturer, jurisdiction) must exist. Path references are validated left to right, and the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) for that resource before later segments are examined.
5. **Optimistic concurrency** — on the two OCC-guarded writes of §2.7, the supplied expected version must match the parent entity's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
6. **State admissibility** — the target entity must be in a state that admits the requested transition (all stage-6 errors carry HTTP 409): a project decision requires the project to be `EVALUATION` (`ERR_PROJECT_NOT_EVALUABLE`); recording a result requires the sample to be `ACCEPTED` or `TESTED` (`ERR_SAMPLE_NOT_ACCEPTED`); an operation that requires an `ACTIVE` certification fails with `ERR_CERTIFICATION_NOT_ACTIVE`; label batch issuance requires an `ACTIVE` license (`ERR_LICENSE_NOT_ACTIVE`); project creation requires an `ACTIVE` manufacturer (`ERR_MANUFACTURER_SUSPENDED`) and an `ACTIVE` standard (`ERR_STANDARD_NOT_ACTIVE`); an acceptance decision requires the field evaluation to have passed (`ERR_FIELD_EVALUATION_NOT_PASSED`); an entity already in a terminal state — `REJECTED`, `WITHDRAWN`, `EXPIRED`, `VOIDED`, `IMPLEMENTED`, or `EVALUATED_FAIL` — rejects all further transitions with `ERR_ALREADY_TERMINAL`, with one exception: the certification decision of §3.4 applies its own `EVALUATION`-only gate to every project state, so deciding a project that is not `EVALUATION` — including one already terminally `APPROVED` or `REJECTED` — is rejected with `ERR_PROJECT_NOT_EVALUABLE` rather than `ERR_ALREADY_TERMINAL`; and any other inadmissible state yields `ERR_INVALID_STATE`.
7. **Compliance gates at decision points** (HTTP 409) — segregation of duties: the reviewer deciding a project must not have recorded any test result on that project (`ERR_SEGREGATION_OF_DUTIES`); and every safety-critical protocol's latest outcome must be `PASS` before approval (`ERR_SAFETY_PROTOCOL_NOT_PASSED`).
8. **Cross-reference coherence** (HTTP 422) — a project's `category_code` must equal its standard's `category_code` (`ERR_CATEGORY_STANDARD_MISMATCH`); a result's `protocol_code` must be declared in the pinned standard (`ERR_UNKNOWN_PROTOCOL_CODE`); a substitution's `slot` must exist among the pinned construction record's `components` (`ERR_UNKNOWN_COMPONENT_SLOT`); a finding's `certification_id`, when present, must belong to the inspected factory (`ERR_FINDING_CERTIFICATION_MISMATCH`); and a construction record must cover every required slot exactly once (`ERR_MISSING_REQUIRED_SLOT`, `ERR_DUPLICATE_COMPONENT_SLOT`).
9. **Temporal rules** — standard edition windows must not overlap within the same `category_code` and `standard_code` (`ERR_STANDARD_EDITION_OVERLAP`, HTTP 409); an inspection's `scheduled_for` must not be before the current logical time (`ERR_INSPECTION_DATE_PAST`, HTTP 422) and must respect the minimum scheduling gap against other non-`VOIDED` inspections of the factory (`ERR_INSPECTION_GAP_VIOLATION`, HTTP 409).
10. **Aggregate and structural rules** (HTTP 409) — every mandatory protocol's latest outcome must be `PASS` or `CONDITIONAL` at approval (`ERR_MANDATORY_PROTOCOL_FAILING`); a field-label acceptance must satisfy the one-hop reciprocity rule (`ERR_RECIPROCITY_NOT_GRANTED`).
11. **Quota rules** — a label batch's `quantity` must be at least 1 (`ERR_INVALID_LABEL_QUANTITY`, HTTP 400) and must fit the license's remaining quota (`ERR_LABEL_QUOTA_EXCEEDED`, HTTP 422).

Separately from this pipeline, a request that is missing a required field, carries a value of the wrong type, or supplies an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Precision, Rounding, and Calendar Arithmetic

Two families of numeric precision apply throughout. Quantities kept at two decimal places — test-result margins and factory conformity scores — are rounded half-up to two decimal places. Money is integer cents: every fee line, discount, and surcharge is rounded half-up to whole cents at the step where it is computed, never deferred to the end, and per-line rounding always precedes summation. Label quotas and serial numbers are whole numbers. Follow-up inspection intervals are added as calendar months onto the completion date, and the minimum scheduling gap between inspections is compared as an absolute difference in whole days.

### 2.10. Cascading State Changes Across Aggregates

State changes propagate across aggregate boundaries, and every propagated change is a real mutation that refreshes `updated_at` and increments `version` on the affected resource. Suspending a certification suspends every one of its mark licenses that is `ACTIVE` or `EXHAUSTED`. Reinstating a certification returns each `SUSPENDED` license to `ACTIVE` or `EXHAUSTED` according to its quota consumption. Withdrawing a certification revokes every non-`REVOKED` license and, one level deeper, voids every `ISSUED` label batch on each revoked license. Voiding a completed inspection unwinds the suspensions that inspection's findings caused, provided no manual suspension cause remains. Because cascades are system-driven, no client request targets the cascaded resources directly; the server reconciles them as part of the triggering write or clock sweep.

## 3. Business Logic & Workflows

### 3.1. Registering the System's Participants and Rulebooks

Before any product can be certified, the certification body registers its rulebooks and enrolls the parties. A `CertificationBodyAdmin` registers each standard edition by supplying the `category_code` of the product category it belongs to, the `standard_code` — editions of the same standard share the pair of `category_code` and `standard_code` — a human-readable `edition_label`, and the effectiveness window of §2.6 via `effective_from` and an optional `effective_to`. The edition also declares its `construction_requirements`, the array of component slot names that a certified product must document (for example an enclosure or a power supply), and its `test_protocols`, an array in which every entry names a `protocol_code`, a display `name`, whether the protocol is `mandatory`, whether it is `safety_critical`, its `pass_threshold`, and its `base_fee_cents`. A registration whose window overlaps an existing edition of the same pair is rejected with `ERR_STANDARD_EDITION_OVERLAP`, and the new edition's `status` is computed immediately from the current logical time.

Jurisdictions are registered by the same administrator role. Each jurisdiction carries a unique `jurisdiction_code` and a display `name`, the boolean `accepts_field_labels` recording whether this authority directly accepts field-evaluation labels, the boolean `accepts_reciprocity` recording whether it honors one-hop reciprocity, an optional `reciprocity_sources` array listing the jurisdiction codes accepted as reciprocity sources (empty by default), and a `reciprocity_group` of `NONE`, `NATIONAL`, `BILATERAL_EU`, or `CUSTOMS_UNION`, defaulting to `NONE`. These attributes are the entire input to the reciprocity rule exercised later at field-label acceptance in §3.8.

Manufacturers are the certification clients. Registration records the `legal_name`, the `home_jurisdiction_code` where the manufacturer is domiciled, and an `annual_revenue_tier` of `MICRO`, `SMALL`, `STANDARD`, or `ENTERPRISE`; the tier drives the fee discount described in §3.4. A manufacturer is registered in `ACTIVE` status with a null `suspension_reason`. A `ComplianceOfficer` may later suspend a manufacturer, supplying a `reason` that is recorded as `suspension_reason`; from that moment the manufacturer's `status` is `SUSPENDED` and any attempt to open a new certification project for that manufacturer is rejected with `ERR_MANUFACTURER_SUSPENDED`.

Each manufacturer operates one or more factories, registered under the manufacturer with a `site_code` unique within that manufacturer, the `country_code` of the site, and the `jurisdiction_code` under which the site will be inspected; the factory's `manufacturer_id` ties it to its owning manufacturer. A new factory begins with `conformity_regime` `STANDARD`, a `conformity_score` of 100, zero `open_critical_findings`, and no inspection history — `last_inspection_completed_on` and `next_inspection_due_on` are both null until the first inspection is completed. The factories of a manufacturer can be listed, and an individual factory can be fetched together with its computed conformity fields.

### 3.2. From Project Opening to Evaluation Readiness

A `ManufacturerRep` opens a certification project by naming the production site (`factory_id`), the product category (`category_code`), the standard edition to certify against (`standard_id`), and the `product_model` under certification. The project's `manufacturer_id` is set from the representative's `X-User-ID`, never from the payload. Three gates guard creation: the manufacturer must be `ACTIVE` (`ERR_MANUFACTURER_SUSPENDED`); the selected standard must be `ACTIVE` at the current logical time — an `UPCOMING` or `RETIRED` edition is rejected with `ERR_STANDARD_NOT_ACTIVE`; and the supplied `category_code` must equal the selected standard's `category_code` (`ERR_CATEGORY_STANDARD_MISMATCH`). The `standard_id` is pinned at creation and is immutable thereafter. A new project is `STANDARD_SELECTED`, with `retest_count` at zero, `fee_snapshot_cents` null until the project first reaches evaluation, and `decided_by` and `decided_on` null until a decision is rendered. Projects can be listed with optional filters on `manufacturer_id`, `factory_id`, `standard_id`, and `status`.

With the project open, the manufacturer ships samples. Each sample is submitted with a `serial_no` supplied by the manufacturer and a declared `condition` of `INTACT` or `DAMAGED` — a damaged sample caps its outcomes at `CONDITIONAL` and raises the fee multiplier applied to results recorded on it, as §3.4 details. A sample is created `SUBMITTED` under its `project_id`, with an empty `results` array and `triaged_by` null. The samples of a project can be listed.

A `TestEngineer` triages each submitted sample with a `decision` and an optional `note`. Accepting moves the sample to `ACCEPTED`; rejecting moves it to `REJECTED`, which is terminal. Either way, `triaged_by` records the engineer's `X-User-ID`. Acceptance is admitted only while the project is `STANDARD_SELECTED` or `TESTING` — accepting against a project in any other state is rejected with `ERR_INVALID_STATE` — while rejection carries no project-state precondition. When a project's first sample is accepted, the project moves automatically from `STANDARD_SELECTED` to `TESTING` and becomes eligible to accumulate protocol results.

Testing itself is the recording of protocol results by a `TestEngineer`, who supplies a `protocol_code` and a `measured_value` against a sample. The protocol code must be declared among the pinned standard's `test_protocols` (`ERR_UNKNOWN_PROTOCOL_CODE`), and the sample must be `ACCEPTED` or `TESTED` — recording against a `SUBMITTED` or `REJECTED` sample is rejected with `ERR_SAMPLE_NOT_ACCEPTED`. The recorded outcome is computed deterministically. The threshold is the protocol's `pass_threshold`, and a conditional band floor is computed as the `pass_threshold` multiplied by 0.95, rounded half-up to two decimal places. The raw outcome is `PASS` when the `measured_value` is at least the threshold, `CONDITIONAL` when it falls below the threshold but is at least the band floor, and `FAIL` when it falls below the band floor. Two overrides then apply, in this order: if the raw outcome is `PASS` and the sample is `DAMAGED`, the outcome is `CONDITIONAL`, because a damaged sample can never pass outright; otherwise, if the raw outcome is `CONDITIONAL` and the protocol is both `mandatory` and `safety_critical`, the outcome is `FAIL`, because safety-critical protocols never yield `CONDITIONAL`. In all other cases the raw outcome stands. The result's `margin` is the `measured_value` minus the `pass_threshold`, rounded half-up to two decimal places.

Each recorded result is appended to the sample's `results`, an append-only array, carrying the `protocol_code`, the `measured_value`, the computed `outcome`, the `margin`, the engineer's `X-User-ID` as `recorded_by`, and the current logical time as `recorded_at`. The first result recorded on a sample moves it automatically from `ACCEPTED` to `TESTED`.

After every result recording, every sample triage, and every construction-record creation, the system re-evaluates the project's readiness for evaluation. Only samples in `ACCEPTED` or `TESTED` are eligible — `SUBMITTED` and `REJECTED` samples never contribute results. The latest outcome of a protocol is the outcome of that protocol's result, across eligible samples, with the latest `recorded_at`; ties on `recorded_at` are broken in favor of the higher `measured_value`. The readiness gate is satisfied when every `mandatory` protocol of the pinned standard has a latest outcome and exactly one `FROZEN` construction record exists for the project. When the gate becomes satisfied while the project is `TESTING`, the project advances automatically from `TESTING` to `EVALUATION`, and its `fee_snapshot_cents` is computed and stored at that moment.

### 3.3. Construction Records: The Frozen Bill of Materials

The certified construction of the product is documented in construction records, created by the `ManufacturerRep` against a project. Each record carries a `components` array whose entries each name a `slot`, a `component_name`, a `material`, a `part_number`, and a `rating`. The array must cover every slot named in the pinned standard's `construction_requirements` exactly once: omitting a required slot is rejected with `ERR_MISSING_REQUIRED_SLOT`, and listing the same slot twice is rejected with `ERR_DUPLICATE_COMPONENT_SLOT`.

Each new record receives a `revision_no` one greater than the highest existing revision number on the project, is created `FROZEN`, and automatically supersedes the previously `FROZEN` revision, which becomes `SUPERSEDED` (terminal). After the first creation there is exactly one `FROZEN` revision per project at all times; this invariant is enforced by the evaluation-readiness gate of §3.2, and it is not re-checked at decision time.

Because creating a revision legitimately supersedes a record the client may never have seen, the write is guarded by optimistic concurrency per §2.7: the request must carry `expected_project_version` matching the project's current `version`, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful creation increments the project's `version` by 1. The revisions of a project can be listed for audit.

### 3.4. The Certification Decision and the Listing Report

Decisions are the exclusive province of a `CertificationReviewer`, and only while the project is `EVALUATION` — deciding at any other time, including after the project has reached the terminal `APPROVED` or `REJECTED` state, is rejected with `ERR_PROJECT_NOT_EVALUABLE`. The reviewer supplies an `outcome` of `APPROVED`, `REJECTED`, or `RETEST`.

Approval is guarded by three checks, evaluated in this order. First, segregation of duties: the deciding reviewer's `X-User-ID` must differ from every `recorded_by` on every result of the project's samples — a reviewer who recorded any result on the project is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, every `safety_critical` protocol's latest outcome must be `PASS` (`ERR_SAFETY_PROTOCOL_NOT_PASSED`). Third, every `mandatory` protocol's latest outcome must be `PASS` or `CONDITIONAL` (`ERR_MANDATORY_PROTOCOL_FAILING`). Rejection and retest are guarded by the segregation-of-duties check alone. Whatever the outcome, the project records `decided_by` and `decided_on`.

By the time a project reaches `EVALUATION`, its program fee has been snapshotted into `fee_snapshot_cents`, computed line by line over the pinned standard's protocols that have a latest result. Each line takes the protocol's `base_fee_cents`, multiplies it by 1.25 when the sample carrying that latest result is `DAMAGED` (an `INTACT` sample multiplies by one), and rounds the line half-up to whole cents before any summation. The subtotal is the sum of these rounded lines. A manufacturer whose `annual_revenue_tier` is `SMALL` then receives a ten percent discount — the subtotal multiplied by 0.9 and rounded half-up to whole cents; every other tier pays the subtotal unchanged. The retest surcharge is the after-discount amount multiplied by 0.5 and by the project's `retest_count`, rounded half-up to whole cents. The snapshot is the after-discount amount plus the surcharge. The pinned rounding order matters: per-line rounding happens before summation, and summing unrounded lines first produces a different, incorrect fee.

The snapshot is stored on entry to `EVALUATION` and is not recomputed during the decision. A `RETEST` decision loops the project back from `EVALUATION` to `TESTING`, increments `retest_count` by 1, and clears `fee_snapshot_cents` to null, so the fee is recomputed — now with the surcharge reflecting the additional retest — the next time the project reaches `EVALUATION`. `APPROVED` and `REJECTED` are terminal states for the project.

Approval creates the certification — the listing report. The server mints a `listing_number`: the letter E followed by a zero-padded six-digit sequence assigned in creation order. The certification pins the project through `project_id` (unique — one certification per approved project), the `manufacturer_id` and `factory_id` denormalized from the project, the pinned `standard_id`, and the currently `FROZEN` construction record through `construction_record_id` and `construction_record_revision`. `issued_on` is the logical time of approval. `expires_on` is `issued_on` plus the `validity_months` supplied with the decision, or null when no `validity_months` was supplied, meaning the certification never expires. `permitted_variations` is taken from the decision payload or defaults to an empty array; each entry constrains one `slot` to a list of `allowed_alternates` part numbers. The certification begins `ACTIVE` with an empty `suspension_causes` array. Certifications can be listed with optional filters on `project_id`, `manufacturer_id`, `factory_id`, `standard_id`, `construction_record_id`, and `status`.

### 3.5. Component Substitutions on a Live Certification

Certified construction is not immutable: a `ManufacturerRep` may request a component substitution against an `ACTIVE` certification — requests against a certification in any other state are rejected with `ERR_CERTIFICATION_NOT_ACTIVE`. The request names the `slot` proposed for substitution, the `proposed_component` with its `component_name`, `material`, `part_number`, and `rating`, and an engineering `rationale`. The substitution request is created `SUBMITTED` under its `certification_id`, with `decided_by` and `decided_on` null. The requests of a certification can be listed.

A `CertificationReviewer` evaluates the request and decides with an `outcome` of `APPROVE` or `REJECT` and an optional `note`. Approval requires that the proposed `slot` exists among the pinned construction record's `components` (`ERR_UNKNOWN_COMPONENT_SLOT`); rejection carries no further precondition. Either way, `decided_by` and `decided_on` are recorded, and the request moves to `APPROVED` or `REJECTED` — the latter terminal.

Implementation is the manufacturer's act, moving an `APPROVED` request to `IMPLEMENTED`, and it is guarded twice: the certification must still be `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), and the request must carry `expected_certification_version` matching the certification's current `version` per §2.7, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). On success, the system freezes a new construction-record revision on the certification's project — the pinned `components` with the substituted slot replaced by the `proposed_component` — superseding the previously `FROZEN` revision; the certification re-pins `construction_record_id` and `construction_record_revision` to the new revision; the certification's `permitted_variations` gains an entry for the slot listing the `proposed_component`'s `part_number` as an allowed alternate; and the certification's `version` increments by 1, the standard mutation bump of this write. `IMPLEMENTED` is terminal.

### 3.6. Follow-Up Inspections and the Factory Conformity Score

Certification is maintained through follow-up service: a `FactoryInspector` schedules periodic inspections of each factory, supplying a `scheduled_for` instant. The instant must not be before the current logical time (`ERR_INSPECTION_DATE_PAST`, HTTP 422), and it must leave a buffer of at least 25 days against every other non-`VOIDED` inspection of the same factory — whether `SCHEDULED`, `OVERDUE`, or `COMPLETED`. The buffer compares the absolute difference between the two scheduled instants in whole days; a gap of exactly 25 days is allowed, and anything smaller is rejected with `ERR_INSPECTION_GAP_VIOLATION`. The inspector's `X-User-ID` is recorded as `inspector_ref`, the inspection is created `SCHEDULED` with `completed_on` and `result` null and an empty `findings` array, and a clock sweep that later finds `scheduled_for` in the past marks the inspection `OVERDUE`. The inspections of a factory can be listed.

Completion — admitted from either `SCHEDULED` or `OVERDUE`, with lateness observable as a `completed_on` later than `scheduled_for` — is recorded by a `FactoryInspector` supplying `findings` and an optional `note`. Each finding carries a `finding_ref`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a `description`, and may optionally name a `certification_id`, which when present must belong to the inspected factory (`ERR_FINDING_CERTIFICATION_MISMATCH`). Completion stamps `completed_on` with the current logical time, moves the inspection to `COMPLETED`, and derives its `result` — one of `CONFORMING`, `MINOR_NC`, `MAJOR_NC`, or `CRITICAL_NC` — as the maximum severity over its findings: a `CRITICAL` finding maps to `CRITICAL_NC` and outranks `MAJOR`, which maps to `MAJOR_NC`, which in turn outranks `MINOR`, which maps to `MINOR_NC`; the result is `CONFORMING` when no findings were recorded. Until completion, `result` is null.

Completion then recomputes the factory's conformity posture. Each finding is worth a penalty by `severity`: 40 points for `CRITICAL`, 15 for `MAJOR`, and 5 for `MINOR`. The factory's `conformity_score` is 100 minus the sum of penalties over the included findings, never below zero, kept to two decimal places rounded half-up. Which findings are included depends on the factory's `conformity_regime`. For a `STANDARD` factory, the window is the trailing 24 months: findings on non-`VOIDED` `COMPLETED` inspections whose `completed_on` is at or after the instant 24 months before now count — the lower bound is inclusive — and older findings stop counting, which is why a clock sweep recomputes `STANDARD`-regime scores. For a `PROBATION` factory, every finding on a non-`VOIDED` `COMPLETED` inspection counts regardless of age, so the score is time-invariant and sweeps never touch it.

The regime itself is re-evaluated after each completion or void. A `STANDARD` factory drops to `PROBATION` when a new `CRITICAL` finding is recorded against it or when its windowed score falls below 70. A `PROBATION` factory returns to `STANDARD` when a completed inspection records zero findings, or when a void leaves it with no open `CRITICAL` findings and a windowed score of at least 70. Alongside the score, `open_critical_findings` counts the `CRITICAL` findings on the factory's non-`VOIDED` `COMPLETED` inspections, and `last_inspection_completed_on` is the completion time of the latest such inspection, or null if none exists.

The inspection interval is then derived in a pinned order — score first, then regime, then interval — which breaks the apparent circularity between score and interval. A `PROBATION` factory, or any factory whose `conformity_score` is below 70, is due every 3 months; a factory scoring at least 70 but below 90 is due every 6 months; a factory scoring 90 or above is due every 12 months. `next_inspection_due_on` is `last_inspection_completed_on` plus that interval, added in calendar months onto the completion date, and is null before the first inspection.

Every `CRITICAL` finding that names a certification also suspends that certification, if it is `ACTIVE`, adding a cause string of 'CRITICAL_FINDING:' followed by the `finding_ref` to its `suspension_causes` and cascading the suspension to its mark licenses as §3.9 describes.

Voiding is the compensating action, performed by a `ComplianceOfficer` supplying a `reason`, and is available only on a `COMPLETED` inspection. The inspection becomes `VOIDED`, which is terminal. Its findings cease to count: the factory's `conformity_score`, `conformity_regime`, `open_critical_findings`, `last_inspection_completed_on`, and `next_inspection_due_on` are all recomputed without them. And each certification whose `suspension_causes` contained only causes contributed by this inspection's findings — and no 'MANUAL' cause — is automatically reinstated to `ACTIVE`, cascading to its `SUSPENDED` mark licenses.

### 3.7. Mark Licenses, Label Batches, and Serial Traceability

A certification entitles its manufacturer to apply the certification mark, administered through mark licenses. Creating one against a certification names a `label_type` of `STANDARD`, `HOLOGRAM`, or `SECURED`, and a `declared_annual_volume` feeding the quota calculation. At creation the system selects the license's `quota_variant` from the conformity regime of the certification's factory at that moment — `STANDARD_QUOTA` for a `STANDARD` factory, `PROBATION_QUOTA` for a `PROBATION` factory — and computes the `authorized_quantity`. Under `STANDARD_QUOTA`, the raw authorization is the `declared_annual_volume` multiplied by 1.10, rounded down to a whole number and capped at 100,000. Under `PROBATION_QUOTA`, the raw authorization is the `declared_annual_volume` multiplied by 0.25, rounded down to a whole number and hard-capped at 500 — an identical declared volume yields a far smaller authorization under probation. In both variants, the `authorized_quantity` is the raw value rounded down to the nearest multiple of 100, with a minimum lot of 100 labels.

The license is minted with a `serial_prefix` — the certification's `listing_number`, followed by a hyphen, followed by the first letter of the `label_type` — with `used_quantity` at zero, `next_serial` at 1, and `status` `ACTIVE`, all tied to the certification through `certification_id`. The licenses of a certification can be listed, and a single license can be fetched together with its quota usage.

Labels are issued in batches against a license. Issuance requires the license to be `ACTIVE` — a batch against an `EXHAUSTED`, `SUSPENDED`, or `REVOKED` license is rejected with `ERR_LICENSE_NOT_ACTIVE` — and supplies a `quantity`. A `quantity` below 1 is rejected with `ERR_INVALID_LABEL_QUANTITY` (HTTP 400). The remaining quota is the `authorized_quantity` minus the `used_quantity`; a `quantity` that exceeds the remainder is rejected with `ERR_LABEL_QUOTA_EXCEEDED`, while an exact fit, where the `quantity` equals the remainder, is allowed. The batch's `serial_start` is the license's `next_serial` at that instant, and its `serial_end` is `serial_start` plus `quantity` minus one. The license's `next_serial` then advances by `quantity` and its `used_quantity` increases by `quantity`; when `used_quantity` reaches `authorized_quantity`, the license becomes `EXHAUSTED` automatically. Each batch is created `ISSUED` under its `license_id`, and the batches of a license can be listed for traceability.

A `ManufacturerRep` may void an `ISSUED` batch, supplying a `reason`. The batch becomes `VOIDED`, which is terminal, and the license's `used_quantity` falls by the batch's `quantity` — `used_quantity` always equals the sum of `quantity` over the license's `ISSUED` (non-`VOIDED`) batches. The license's `next_serial` is never rewound: serials are never reused, and a voided range is simply skipped. If the license was `EXHAUSTED` and is neither `SUSPENDED` nor `REVOKED`, it returns automatically to `ACTIVE` once the void drops usage below the authorization. A license therefore oscillates between `ACTIVE` and `EXHAUSTED` purely on quota consumption; `SUSPENDED` and `REVOKED` arrive only by cascade from the certification, as §3.9 describes.

### 3.8. Field Evaluations and Jurisdictional Acceptance

Equipment already installed and never certified can still be labeled through a field evaluation. A `ManufacturerRep` requests one by naming the `standard_id` that is the evaluation basis, the `evaluating_jurisdiction_id` under which the certification body evaluates, the `site_jurisdiction_id` of the authority where the equipment is installed and which will decide acceptance, plus an `equipment_description` and the `site_address`; the requester's `X-User-ID` becomes the `manufacturer_id`. A field evaluation carries two independent status dimensions that evolve on independent triggers: `eval_status` begins `REQUESTED`, and `acceptance_status` begins `PENDING`. Field evaluations can be listed with optional filters on `manufacturer_id`, `standard_id`, `evaluating_jurisdiction_id`, and `site_jurisdiction_id`.

A `TestEngineer` records the engineering outcome with an `outcome` of `PASS` or `FAIL` and optional `notes`, and the engineer's `X-User-ID` is recorded as `evaluated_by`. A `PASS` moves `eval_status` to `EVALUATED_PASS`. A `FAIL` moves it to `EVALUATED_FAIL`, which is terminal for the evaluation dimension: no further evaluation may be recorded and no acceptance approval may follow, although the acceptance dimension may still be resolved by rejection — while a fail leaves `acceptance_status` at `PENDING`, only a rejection can follow.

Acceptance is decided by an `AHJAuthority` supplying a `decision` of `ACCEPT` or `REJECT` and an optional `basis`. The authority's `X-User-ID` must equal the field evaluation's `site_jurisdiction_id` — an authority decides only for installations in its own jurisdiction, and any other authority is rejected with `ERR_FORBIDDEN`. An acceptance additionally requires `eval_status` to be `EVALUATED_PASS`; attempting to accept a failed or not-yet-evaluated evaluation is rejected with `ERR_FIELD_EVALUATION_NOT_PASSED`, and attempting any acceptance decision while `eval_status` is still `REQUESTED` meets the same error. A rejection is permitted on any evaluated status — `EVALUATED_PASS` or `EVALUATED_FAIL`.

An acceptance must also satisfy the one-hop reciprocity rule. The site jurisdiction accepts the label outright when its own `accepts_field_labels` is true. Otherwise exactly one hop of reciprocity is available: the site jurisdiction must have `accepts_reciprocity` set, the evaluating jurisdiction's `jurisdiction_code` must appear in the site jurisdiction's `reciprocity_sources`, the evaluating jurisdiction must itself have `accepts_field_labels` set, and the two jurisdictions' `reciprocity_group` values must be equal — unless both are `NONE`, which also qualifies. Sources-of-sources are never consulted; there is no transitive closure. When none of this holds, the acceptance is rejected with `ERR_RECIPROCITY_NOT_GRANTED`.

On acceptance, `acceptance_status` becomes `ACCEPTED`, `label_issued_on` is set to the current logical time, and `ahj_decided_by` records the decider's `X-User-ID`. On rejection, `acceptance_status` becomes `REJECTED` with `ahj_decided_by` recorded, and `label_issued_on` stays null.

### 3.9. Suspension, Withdrawal, and Public Notice

Compliance action against a certification begins with suspension. A `ComplianceOfficer` suspends an `ACTIVE` certification, supplying a `reason`; the certification becomes `SUSPENDED` with 'MANUAL' added to its `suspension_causes`, and every one of its mark licenses in `ACTIVE` or `EXHAUSTED` cascades to `SUSPENDED`. Suspension also arrives by cascade from critical inspection findings, as §3.6 describes, with one 'CRITICAL_FINDING:'-prefixed cause per finding. A certification may therefore accumulate several causes, and reinstatement requires them all to be gone.

Reinstatement is the officer's reverse act on a `SUSPENDED` certification. It is blocked while any open `CRITICAL` finding naming the certification remains — that is, while the factory's count of `CRITICAL` findings naming this certification on non-`VOIDED` `COMPLETED` inspections is nonzero — and the attempt is rejected with `ERR_OPEN_CRITICAL_FINDINGS`. On reinstatement the certification returns to `ACTIVE`, its `suspension_causes` are cleared, and each `SUSPENDED` mark license returns to `ACTIVE` when its `used_quantity` is below its `authorized_quantity`, or to `EXHAUSTED` when the two are equal. The same reinstatement happens automatically when an inspection void removes the certification's last finding-derived cause and no 'MANUAL' cause remains — the system cascade, unlike the officer's act, needs no separate precondition because the void itself removes the cause.

Withdrawal is terminal and always publicly noticed. A `ComplianceOfficer` drafts a withdrawal notice against a certification with a `reason_code` of `SAFETY`, `NONCONFORMITY`, `VOLUNTARY`, or `MISUSE_OF_MARK` and the `public_text` of the notice; the notice is created `DRAFT` under its `certification_id`, with `published_on` and `effective_on` null. The notices of a certification can be listed. Publishing — allowed while the certification is `ACTIVE` or `SUSPENDED` — stamps `published_on` with the current logical time, sets `effective_on` to 14 days after `published_on` as a cooling-off period before enforcement, and moves the notice to `PUBLISHED`. When a clock sweep finds a `PUBLISHED` notice whose `effective_on` is at or before the current time, the notice becomes `EFFECTIVE` — terminal — and its certification, whether `ACTIVE` or `SUSPENDED`, becomes `WITHDRAWN`. Withdrawal cascades two levels deep: every non-`REVOKED` mark license of the certification becomes `REVOKED`, and on each revoked license every `ISSUED` label batch becomes `VOIDED`, with `used_quantity` recomputed on each affected license. Separately, an `ACTIVE` certification whose `expires_on` has been reached becomes `EXPIRED` on the sweep; `EXPIRED` is likewise terminal, and `SUSPENDED` certifications do not expire.

## 4. Endpoint Definitions

Operations that create a new resource — including a new revision in a collection, a new label batch, or a new test-result record appended to a sample — return `201 Created`. Operations that modify an existing resource's state return `200 OK`. The complete request payloads, response shapes, preconditions, and side effects of every operation are specified in the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/certification/_clock/set_current_utc` | Advance the logical clock and run the time sweep | CertificationBodyAdmin |
| POST | `/certification/standards` | Register a standard edition for a product category | CertificationBodyAdmin |
| POST | `/certification/jurisdictions` | Register a jurisdiction / AHJ with reciprocity arrangement | CertificationBodyAdmin |
| POST | `/certification/manufacturers` | Register a manufacturer (certification client) | CertificationBodyAdmin |
| GET | `/certification/manufacturers/{id}` | Get a manufacturer | Any |
| POST | `/certification/manufacturers/{id}/suspend` | Suspend a manufacturer; blocks new project creation | ComplianceOfficer |
| POST | `/certification/manufacturers/{id}/factories` | Register a factory for a manufacturer | CertificationBodyAdmin |
| GET | `/certification/manufacturers/{id}/factories` | List factories of a manufacturer | Any |
| GET | `/certification/factories/{id}` | Get a factory with computed conformity fields | Any |
| POST | `/certification/projects` | Open a certification project with standards selection pinned | ManufacturerRep |
| GET | `/certification/projects` | List and filter projects | Any |
| GET | `/certification/projects/{id}` | Get a project | Any |
| POST | `/certification/projects/{id}/decide` | Certification decision: approve, reject, or retest | CertificationReviewer |
| POST | `/certification/projects/{id}/samples` | Submit a test sample to a project | ManufacturerRep |
| GET | `/certification/projects/{id}/samples` | List samples of a project | Any |
| POST | `/certification/samples/{id}/triage` | Accept or reject a submitted sample | TestEngineer |
| POST | `/certification/samples/{id}/results` | Record a protocol test result on a sample | TestEngineer |
| POST | `/certification/projects/{id}/construction-records` | Create a new frozen construction-record revision (OCC-guarded) | ManufacturerRep |
| GET | `/certification/projects/{id}/construction-records` | List construction-record revisions of a project | Any |
| GET | `/certification/certifications` | List and filter certifications (the listing reports) | Any |
| GET | `/certification/certifications/{id}` | Get a certification | Any |
| POST | `/certification/certifications/{id}/suspend` | Suspend a certification; cascades to its mark licenses | ComplianceOfficer |
| POST | `/certification/certifications/{id}/reinstate` | Reinstate a suspended certification | ComplianceOfficer |
| POST | `/certification/certifications/{id}/substitution-requests` | Request a component substitution against an active certification | ManufacturerRep |
| GET | `/certification/certifications/{id}/substitution-requests` | List substitution requests of a certification | Any |
| POST | `/certification/substitution-requests/{id}/decide` | Evaluate and decide a substitution request | CertificationReviewer |
| POST | `/certification/substitution-requests/{id}/implement` | Implement an approved substitution (OCC-guarded) | ManufacturerRep |
| POST | `/certification/factories/{id}/inspections` | Schedule a follow-up inspection | FactoryInspector |
| GET | `/certification/factories/{id}/inspections` | List inspections of a factory | Any |
| POST | `/certification/inspections/{id}/complete` | Complete an inspection with findings | FactoryInspector |
| POST | `/certification/inspections/{id}/void` | Void a completed inspection as a correction | ComplianceOfficer |
| POST | `/certification/certifications/{id}/mark-licenses` | Authorize a mark license with a computed label quota | ManufacturerRep |
| GET | `/certification/certifications/{id}/mark-licenses` | List mark licenses of a certification | Any |
| GET | `/certification/mark-licenses/{id}` | Get a mark license with quota usage | Any |
| POST | `/certification/mark-licenses/{id}/label-batches` | Issue a batch of mark labels with serial-range allocation | ManufacturerRep |
| GET | `/certification/mark-licenses/{id}/label-batches` | List label batches of a license (traceability) | Any |
| POST | `/certification/label-batches/{id}/void` | Void an issued batch; quantity returns to the license quota | ManufacturerRep |
| POST | `/certification/field-evaluations` | Request a field evaluation of installed, never-certified equipment | ManufacturerRep |
| GET | `/certification/field-evaluations` | List and filter field evaluations | Any |
| GET | `/certification/field-evaluations/{id}` | Get a field evaluation | Any |
| POST | `/certification/field-evaluations/{id}/evaluate` | Record the engineering evaluation outcome | TestEngineer |
| POST | `/certification/field-evaluations/{id}/decide-acceptance` | AHJ decides jurisdictional acceptance of the field label | AHJAuthority |
| POST | `/certification/certifications/{id}/withdrawal-notices` | Draft a public withdrawal notice for a certification | ComplianceOfficer |
| GET | `/certification/certifications/{id}/withdrawal-notices` | List withdrawal notices of a certification | Any |
| POST | `/certification/withdrawal-notices/{id}/publish` | Publish a notice; enforcement follows at the effective date | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_MANUFACTURER_SUSPENDED | 409 |
| ERR_CATEGORY_STANDARD_MISMATCH | 422 |
| ERR_STANDARD_NOT_ACTIVE | 409 |
| ERR_STANDARD_EDITION_OVERLAP | 409 |
| ERR_UNKNOWN_PROTOCOL_CODE | 422 |
| ERR_SAMPLE_NOT_ACCEPTED | 409 |
| ERR_PROJECT_NOT_EVALUABLE | 409 |
| ERR_SAFETY_PROTOCOL_NOT_PASSED | 409 |
| ERR_MANDATORY_PROTOCOL_FAILING | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_MISSING_REQUIRED_SLOT | 422 |
| ERR_DUPLICATE_COMPONENT_SLOT | 422 |
| ERR_UNKNOWN_COMPONENT_SLOT | 422 |
| ERR_CERTIFICATION_NOT_ACTIVE | 409 |
| ERR_OPEN_CRITICAL_FINDINGS | 409 |
| ERR_LICENSE_NOT_ACTIVE | 409 |
| ERR_LABEL_QUOTA_EXCEEDED | 422 |
| ERR_INVALID_LABEL_QUANTITY | 400 |
| ERR_INSPECTION_DATE_PAST | 422 |
| ERR_INSPECTION_GAP_VIOLATION | 409 |
| ERR_FINDING_CERTIFICATION_MISMATCH | 422 |
| ERR_RECIPROCITY_NOT_GRANTED | 409 |
| ERR_FIELD_EVALUATION_NOT_PASSED | 409 |
