# Emissions Certification, Aftertreatment Warranty & Remanufacturing Programs API — Product Requirements Document

## 1. Introduction

Heavy-duty engine manufacturers carry a regulatory obligation that spans the full service life of every engine they sell. Before a single unit enters production, its engine family must be certified against a published emissions standard through a program of laboratory testing; after production, the manufacturer remains responsible for in-use compliance across the family's regulatory useful life, and when field testing reveals non-conformance it must plan and execute recalls or service campaigns through an authorized service network. Alongside these certification and campaign obligations sit three commercial programs: an extended emissions warranty that must distinguish genuine component failure from customer maintenance neglect, a remanufactured engine and component program that issues credits against returned cores, and a telematics pipeline that converts fleet engine data into fault prediction and service scheduling. This document specifies the API through which all of these programs are administered.

The API serves the OEM's certification engineers, regulatory officers, warranty adjudicators, remanufacturing planners, and platform administrators, and it also serves the fleet managers and service center advisors who interact with the programs from the field. Every time-dependent rule in the system — warranty windows, technician certification expiry, diagnostic-tool calibration validity, core return deadlines — is evaluated against a single logical clock rather than wall-clock time, so that compliance outcomes are deterministic and auditable. All program resources are mounted under the `/emissions` path prefix; a small set of administrative test-driving endpoints lives outside that prefix. Section 2 states the structural contract every endpoint shares; Section 3 narrates the business workflows in which the rules engage.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts. If either header is missing, or if the role name is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes exactly seven roles:

- `PlatformAdmin` — the OEM program administrator: owns reference data, service-network administration, telematics ingestion, claim payouts, and all test-driving endpoints.
- `CertificationEngineer` — the powertrain certification engineer: designs engine families and aftertreatment systems and runs the regulatory test program.
- `RegulatoryOfficer` — the compliance authority liaison: publishes and supersedes standards, certifies engine families (though never a family that same officer submitted for review), declares and closes field campaigns, verifies remedies, and records in-use compliance results.
- `FleetManager` — a fleet operator: maintains its own fleet's units, files warranty claims, and answers information requests.
- `ServiceAdvisor` — an authorized service center operator: schedules and runs campaign work orders, files warranty claims as the repairing center, and runs the remanufacturing core pipeline.
- `WarrantyAdjudicator` — the warranty claim adjudicator: reviews claims, requests information, and decides coverage versus maintenance neglect; an adjudicator never files claims.
- `RemanPlanner` — the remanufacturing program planner: grades returned cores and issues final core credits.

Identity semantics differ by role, and they determine what `X-User-ID` is compared against. When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `Fleet`; ownership checks on any resource that references a fleet compare that resource's `fleet_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FLEET_MISMATCH` (HTTP 403). When `X-User-Role` is `ServiceAdvisor`, `X-User-ID` is the `id` of the acting `ServiceCenter`; any claim, work-order, or reman-order create or transition that names a `service_center_id` compares that field to `X-User-ID`, and a mismatch is rejected with `ERR_CENTER_MISMATCH` (HTTP 403). For the remaining five roles — `PlatformAdmin`, `CertificationEngineer`, `RegulatoryOfficer`, `WarrantyAdjudicator`, and `RemanPlanner` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `submitted_by_user_id` on an engine family, `reviewed_by_user_id` on a test run, or `decided_by_user_id` on a warranty claim) but it never compares such an identifier to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the logical clock of §2.4 rather than wall-clock time.
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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when it is not provided it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` below 1 or above 100, or an `offset` below 0 is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — out-of-range values are never clamped. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock and Lazy Expiry

All time-dependent evaluation in the system reads a single logical clock — never wall-clock time. At startup, before any administrative call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and the clock never falls back to wall-clock time at any point afterward. A `PlatformAdmin` may set the clock through a test-driving endpoint that accepts a `current_utc` instant — a value that does not parse as an ISO 8601 datetime is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and echoes the request's `current_utc` string back verbatim, without normalization, in its response. Every window comparison, expiry rule, deadline test, and stamped timestamp in this document reads this clock, so advancing the clock is the only way time passes in the system.

Two resource families carry lazily evaluated expiry states rather than scheduled transitions. A `Technician` whose `certification_expires_at` lies strictly before the logical clock is reported as `EXPIRED` the next time the technician is read or used; at the exact instant of `certification_expires_at` the technician is still `CERT_ACTIVE`, because the comparison is strictly-greater. Likewise a `DiagnosticTool` whose `calibration_valid_until` lies strictly before the logical clock is reported as `RECAL_DUE` on its next read or use. No background process performs these transitions; they materialize when the record is observed or exercised — including when an endpoint reads the record while acting on another resource, as technician lists, tool lists, center authorization, technician recertification, tool recalibration, work-order scheduling, and work-order start all do — and each such materialization is a mutation of the resource: its `updated_at` refreshes and its `version` increments by one. A materialization persists even when the enclosing request is ultimately rejected, and when a single request first materializes a lazy expiry on a record and then mutates that same record, the two are separate mutations and the `version` increments once for each.

### 2.5. Common Resource Properties

The primary resources — `RegulationStandard`, `EngineFamily`, `AftertreatmentSpec`, `CertificationTestRun`, `Fleet`, `EngineUnit`, `ServiceCenter`, `Technician`, `DiagnosticTool`, `WarrantyClaim`, `FieldCampaign`, `CampaignWorkOrder`, and `RemanOrder` — share a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, captured at creation.
- `updated_at` (string): the same timestamp format, refreshed upon any modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation — so `created_at` and `updated_at` are equal at creation — and increments by exactly one on every mutation of the resource, including mutations driven by system cascades rather than direct client action.

Three resources are append-only records and carry only `id` and `created_at`: `MaintenanceRecord`, `TelematicsSnapshot`, and `InUseComplianceResult`. For these three resources both `updated_at` and `version` are absent entirely — they are never modified after creation.

### 2.6. Numeric Precision, Rounding, and Monetary Representation

Emissions measurements and compliance ratios are compared only after rounding. Adjusted emissions values, in-use conformity ratios, campaign completion rates, and dosing deviation percentages are each rounded half-up to 4 decimal places, and the rounded value — never the raw quotient or product — is what every threshold comparison consumes. Dosing targets are rounded half-up to 2 decimal places. All monetary amounts are represented as integer cents; every monetary computation rounds half-up to whole cents at each rounding step the business narrative names, and where a calculation contains several rounding steps the narrative pins their order, because rounding a rate before multiplying is deliberately not the same as multiplying first and rounding the product. Neglect and fault-risk scores are computed with integer arithmetic throughout: any division that feeds them is floored to a whole number before it contributes points, and each such score is capped at 100.

### 2.7. Optimistic Concurrency Control

Two write endpoints — and only these two — require the caller to prove it has observed the current state of a parent entity. Creating a new aftertreatment spec version against an engine family requires the request to carry `expected_engine_family_version`, a non-optional field holding the family `version` the client last observed. Creating a remanufacture order likewise requires the non-optional `expected_engine_unit_version` field, holding the engine unit's last observed `version`. If the supplied value does not equal the parent entity's current `version` — because another writer has advanced the parent since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from silently superseding a spec it never saw or quoting against unit state it never observed. Omitting either field from its endpoint is a request-shape violation rejected with `ERR_INVALID_REQUEST` (HTTP 400). No endpoint other than these two accepts a version field.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order and reports only the first failure. The order is:

1. Presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Whether the caller's role is admitted by the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. Request shape: required fields present, enum values within their declared sets, integer ranges respected (`bay_days` at least 1, `claimed_amount_cents` greater than 0, `sample_size` at least 1, `passing_units` at least 0 and no greater than `sample_size`, `nox_sensor_count` between 1 and 3 inclusive, `quoted_price_cents` greater than 0, `quoted_core_value_cents` at least 0), and `component_type` present if and only if `reman_scope` is `COMPONENT` (`ERR_INVALID_REQUEST`). Request fields beyond those an endpoint names are ignored.
4. Existence: path identifiers first, then foreign-key identifiers in the body, validated left-to-right (`ERR_NOT_FOUND`).
5. Ownership for entity-backed roles (`ERR_FLEET_MISMATCH`, `ERR_CENTER_MISMATCH`).
6. Segregation of duties on family certification (`ERR_SEGREGATION_OF_DUTIES`).
7. State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors `ERR_UNIT_NOT_IN_SERVICE`, `ERR_FLEET_SUSPENDED`, `ERR_CENTER_NOT_AUTHORIZED`, `ERR_FAMILY_NOT_IN_PRODUCTION`, `ERR_CAMPAIGN_NOT_IN_PROGRESS`, `ERR_UNIT_CAMPAIGN_NOT_OPEN`, `ERR_STANDARD_NOT_PUBLISHED`, `ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING`, `ERR_TEST_RESULT_NOT_PASS`, and `ERR_CAMPAIGN_STILL_OPEN`.
8. Optimistic concurrency (`ERR_STALE_VERSION`).
9. Qualification and scoring consistency (`ERR_TECHNICIAN_NOT_QUALIFIED`, `ERR_DECISION_INCONSISTENT_WITH_SCORE`, `ERR_NO_QUALIFIED_TECHNICIAN`).
10. Cross-entity referential rules (`ERR_SUPERSESSION_WINDOW_INVALID`, `ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW`, `ERR_RECALL_REQUIRES_NON_CONFORMANCE`, `ERR_SPEC_NOT_CALIBRATED`).
11. Uniqueness and structural business constraints: duplicate codes and serials, required accepted test coverage, active-spec presence, lab window overlap, published-standard window overlap, review-round exhaustion, notified-unit presence, decommission blockers, and the minimum in-use sample size.
12. Temporal rules: coverage windows, core return timing, odometer and telematics monotonicity, in-service dating, and service odometer bounds.
13. Shop bay capacity (`ERR_CAPACITY_EXCEEDED`).

For endpoints whose path nests one resource beneath another, identifier resolution runs left-to-right: the first path identifier that does not resolve yields `ERR_NOT_FOUND`, and identifiers to its right are never consulted.

### 2.9. Hierarchical Consistency and Cascade Semantics

Many operations in this system mutate more than one resource atomically inside a single request: announcing a field campaign places its engine family on compliance hold and flags every affected unit; verifying a remedy can close a campaign and release the family from that hold; grading or forfeiting a core can suspend a service center; denying a claim for neglect can suspend a fleet. Every hop of such a cascade is an independent mutation of the affected resource — its `updated_at` refreshes and its `version` increments by one at each hop — so a client that re-reads a cascade-touched resource observes a strictly newer version than the one it last held. The hop-by-hop composition of each cascade is stated in §3 alongside the workflow that triggers it.

## 3. Business Logic & Workflows

This section narrates the system's business processes. Endpoint mechanics appear only in §4; here, operations are named by the state change or capability they perform.

### 3.1. Regulation Standards and Model-Year Transition Planning

A `RegulationStandard` is the regulatory anchor for everything else in the program. A `PlatformAdmin` creates one by supplying its `code` — unique across the entire program, so a duplicate submission is rejected with `ERR_DUPLICATE_STANDARD_CODE` (HTTP 409) — together with the certification limits `nox_limit_g_per_bhp_hr` and `pm_limit_g_per_bhp_hr`, the useful-life obligations `useful_life_miles`, `useful_life_hours`, and `useful_life_years`, the base warranty terms `base_warranty_years` and `base_warranty_miles`, and the effective window expressed as the integers `effective_model_year_first` and `effective_model_year_last`. A new standard starts in `DRAFT` status with `published_at` unset and `successor_standard_id` unset.

Publication is performed by a `RegulatoryOfficer` and moves the standard from `DRAFT` to `PUBLISHED`, stamping `published_at` with the logical clock. Publication is refused with `ERR_STANDARD_WINDOW_OVERLAP` (HTTP 409) when any other already-`PUBLISHED` standard has a model-year window that overlaps this one. Two windows are treated as inclusive integer intervals, and they overlap exactly when each window's first model year is no greater than the other window's last model year — so touching boundaries count as overlapping, and at most one `PUBLISHED` standard can cover any given model year.

Transition planning is expressed through supersession. A `RegulatoryOfficer` may mark a `PUBLISHED` standard as `SUPERSEDED` by naming a `successor_standard_id` in the request. The named successor must resolve to an existing standard (`ERR_NOT_FOUND`, HTTP 404), must itself be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`, HTTP 409), and must begin strictly later: the successor's `effective_model_year_first` must be strictly greater than the superseded standard's own `effective_model_year_first`, otherwise the request fails with `ERR_SUPERSESSION_WINDOW_INVALID` (HTTP 409). On success the superseded standard records the successor's id in its own `successor_standard_id`. `SUPERSEDED` is terminal; the chain of supersession links lets the program express regulation change across model years without rewriting history. The standards list endpoint supports filtering by `status` and by `successor_standard_id`.

### 3.2. Engine Family Certification Lifecycle

The `EngineFamily` is the unit of certification. A `CertificationEngineer` creates one against a published standard by supplying a `family_code`, the `model_year`, the target standard's `regulation_standard_id`, the `displacement_liters`, and the aftertreatment `architecture` — one of `DOC_DPF_SCR`, `DOC_DPF_SCR_ASC`, or `EGR_DOC_DPF_SCR`. Three referential checks apply at creation: the named standard must be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`), the `model_year` must lie inside the standard's effective window, inclusive of both `effective_model_year_first` and `effective_model_year_last` (`ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW`, HTTP 422), and the `family_code` must be unique among families of the same `model_year` (`ERR_DUPLICATE_FAMILY_CODE`). A new family begins in `DESIGN`, with `certification_status` driving the lifecycle, `production_entered` false, `in_use_compliance_status` set to `NOT_TESTED`, and both `submitted_by_user_id` and `certified_at` unset.

From `DESIGN`, beginning testing moves the family to `TESTING` and is performed by a `CertificationEngineer`; it requires that an `ACTIVE` aftertreatment spec already exist for the family, otherwise the request is rejected with `ERR_NO_ACTIVE_AFTERTREATMENT_SPEC` (HTTP 409). Once testing has produced sufficient evidence, the engineer submits the family for review, moving it from `TESTING` to `UNDER_REVIEW`. Submission requires, for each of the three required test types `FTP`, `RMC`, and `SET`, at least one certification test run in `ACCEPTED` status; a missing type is reported as `ERR_REQUIRED_TEST_MISSING` (HTTP 409). Submission stamps `submitted_by_user_id` with the caller's `X-User-ID`, which becomes the segregation-of-duties anchor for certification. Should evidence be withdrawn mid-review — for example when an accepted run is invalidated — a `CertificationEngineer` can return the family from `UNDER_REVIEW` to `TESTING` through the revision loop, which carries no preconditions.

Certification itself is performed by a `RegulatoryOfficer` and moves the family from `UNDER_REVIEW` to `CERTIFIED`. Three gates hold at that instant, evaluated in the §2.8 order — segregation of duties first, then the state gates, then the accepted-coverage rule: accepted coverage for each of `FTP`, `RMC`, and `SET` must still exist (`ERR_REQUIRED_TEST_MISSING`); the officer's `X-User-ID` must differ from the family's `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403) — a check that passes when `submitted_by_user_id` is unset; and the family's regulation standard must still be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`). Certification stamps `certified_at` from the logical clock.

A `CERTIFIED` family enters production through a `RegulatoryOfficer`, moving to `IN_PRODUCTION` and setting `production_entered` to true. That flag later decides where the family lands when a compliance hold is released. A family in `CERTIFIED` or `IN_PRODUCTION` is moved to `COMPLIANCE_HOLD` by the system — never directly — as a side effect of a field campaign being announced (§3.8). Symmetrically, when the family's last open campaign closes, the system moves the family out of `COMPLIANCE_HOLD`: to `IN_PRODUCTION` when `production_entered` is true, and back to `CERTIFIED` when it is false.

Phasing out is the terminal act. A `RegulatoryOfficer` may phase out a family from either `IN_PRODUCTION` or `COMPLIANCE_HOLD`, moving it to `PHASED_OUT`, but only while no field campaign of the family sits in `ANNOUNCED`, `IN_PROGRESS`, or `COMPLETION_REVIEW`; an open campaign blocks the transition with `ERR_CAMPAIGN_STILL_OPEN` (HTTP 409). Because `COMPLIANCE_HOLD` is only ever entered through an announced campaign, phasing out from that state in practice means closing the family's campaigns first — which itself releases the hold — and the open-campaign gate is what reports the error in both source states.

Each family's detail view is supplemented by scoped list endpoints: its aftertreatment spec versions, its certification test runs, its serialized engine units, its field campaigns, and its in-use compliance results. The engine-family list endpoint itself supports filtering by `regulation_standard_id` and by `certification_status`.

### 3.3. Aftertreatment Design and Regulatory Test Execution

An `AftertreatmentSpec` describes the emissions hardware fitted to a family. A `CertificationEngineer` creates a new spec version within a family's scope, supplying the `scr_catalyst_part`, the `dpf_part`, the `doser_part`, and the `nox_sensor_count` (an integer between 1 and 3 inclusive). Because the creation supersedes the family's current spec, it is an optimistic-concurrency write: the payload must carry `expected_engine_family_version` equal to the family's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.7. The family must be in `DESIGN` or `TESTING`; a family past testing rejects spec creation with `ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING` (HTTP 409). The new spec receives a `spec_version` one greater than the family's current maximum — 1 for the family's first spec — starts in `DRAFT` status with `calibration_status` `UNCALIBRATED`, and has both `target_def_dosing_g_per_kwh` and `last_deviation_pct` unset. In the same request the family's previous spec, if one exists in `DRAFT` or `ACTIVE` status, is moved to `SUPERSEDED`, and the family's own `version` increments by one — which is precisely the increment a stale writer is protected against.

Calibration is a `CertificationEngineer` operation on a `DRAFT` spec that leaves the spec in `DRAFT` while recomputing its dosing evidence. The calibrate payload carries `observed_def_consumption_g_per_kwh` and `observed_nox_ppm_avg`. The dosing target is computed from the family's displacement: 6.0 grams of DEF per kilowatt-hour, scaled by the family's `displacement_liters` against a 12.0-liter reference displacement, and the result is rounded half-up to 2 decimal places and persisted as `target_def_dosing_g_per_kwh`. The deviation is the absolute difference between the observed consumption and that target, divided by the target, rounded half-up to 4 decimal places and persisted as `last_deviation_pct` (a zero target, possible only at zero displacement, yields a deviation of 0). The spec's `calibration_status` becomes `CALIBRATED` exactly when the deviation is no greater than 0.05 — a deviation of precisely 0.0500 calibrates, because the boundary is inclusive — and the observed NOx average is no greater than 400 parts per million; otherwise it remains (or returns to) `UNCALIBRATED`. Activation moves a spec from `DRAFT` to `ACTIVE` and requires both that `calibration_status` be `CALIBRATED` (`ERR_SPEC_NOT_CALIBRATED`, HTTP 409) and that the family still be in `DESIGN` or `TESTING` (`ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING`).

Regulatory testing is organized as scheduled `CertificationTestRun` records created within a family's scope. The family must be in `TESTING` or `UNDER_REVIEW` for a run to be scheduled; otherwise the request fails as `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The engineer supplies the `test_type` — one of `FTP`, `RMC`, `SET`, or `NTE` — the `lab_code` identifying the test cell, and the half-open scheduling window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive); the end must be strictly after the start, and a window violating that is a shape failure under `ERR_INVALID_REQUEST`. Two runs in the same `lab_code` conflict when both occupy overlapping half-open windows: a new run conflicts with an existing run in `SCHEDULED` or `COMPLETED` status exactly when the new window starts before the existing window ends and the existing window starts before the new window ends. Mere adjacency — the new run starting at the instant an existing run's window ends — does not conflict, and runs in `REJECTED` or `INVALIDATED` status never block anything. A genuine overlap is rejected with `ERR_LAB_WINDOW_OVERLAP` (HTTP 409). A new run starts `SCHEDULED` with `result` `UNRECORDED`, its measured and adjusted values unset, and `deterioration_factor` set to 1.0 at creation — any value supplied at creation is ignored, and the authoritative value arrives with the record-results payload.

Recording results is the engineer's next step, moving a run from `SCHEDULED` to `COMPLETED` with the payload `measured_nox_g_per_bhp_hr`, `measured_pm_g_per_bhp_hr`, and `deterioration_factor`. The system computes `adjusted_nox_g_per_bhp_hr` as the measured NOx multiplied by the deterioration factor, rounded half-up to 4 decimal places, and `adjusted_pm_g_per_bhp_hr` the same way from the measured PM. The run's `result` is `PASS` exactly when the adjusted NOx is no greater than the family standard's `nox_limit_g_per_bhp_hr` and the adjusted PM is no greater than the standard's `pm_limit_g_per_bhp_hr` — equality at either limit passes — and `FAIL` otherwise.

Review belongs to a `RegulatoryOfficer`, whose `decision` — exactly `ACCEPT` or `REJECT` — moves a `COMPLETED` run to `ACCEPTED` or `REJECTED` respectively. Accepting requires the run's `result` to be `PASS`; a `decision` of `ACCEPT` on a `FAIL` run is rejected with `ERR_TEST_RESULT_NOT_PASS` (HTTP 409). Either decision stamps `reviewed_by_user_id` with the officer's `X-User-ID`. Finally, an `ACCEPTED` run may be invalidated by a `RegulatoryOfficer`, moving it to `INVALIDATED` and capturing the supplied `reason` into `invalidated_reason`. Invalidation does not itself re-open the family; the family's accepted test coverage is re-evaluated lazily at the next submit-review or certify, which is where a newly missing test type surfaces as `ERR_REQUIRED_TEST_MISSING`.

### 3.4. Fleets, Engine Units, and In-Use Compliance

A `Fleet` is the program's view of a fleet operator. A `PlatformAdmin` registers a fleet with its `name`, a `fleet_code`, and a `notification_contact` used for campaign notification; the `fleet_code` is stored as supplied and no duplicate-`fleet_code` rejection is performed. A fleet starts `ACTIVE` with `neglect_denial_count` at 0; how it later becomes `SUSPENDED` is a warranty-adjudication side effect described in §3.7, and a `PlatformAdmin` may reinstate a suspended fleet, returning it to `ACTIVE` and resetting `neglect_denial_count` to 0.

An `EngineUnit` is a serialized engine in the field, registered by a `PlatformAdmin` with its `engine_family_id`, its owning `fleet_id`, a `serial_number` unique within the family (`ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409), and an `in_service_date`. Two gates guard registration: the family must be in `IN_PRODUCTION` (`ERR_FAMILY_NOT_IN_PRODUCTION`, HTTP 409), and the `in_service_date` must not lie in the future — a date strictly after the logical clock is rejected with `ERR_IN_SERVICE_DATE_IN_FUTURE` (HTTP 422), while a date exactly equal to the clock is accepted. The unit's `model_year` is copied from its family at registration; any client-supplied value for it is ignored. A new unit starts with `lifecycle` `IN_SERVICE`, `campaign_compliance` `CLEAR`, `accumulated_miles` and `accumulated_hours` at 0, `predictive_service_due` false, and `last_snapshot_at` unset. The two counters are monotonic and advance only through telematics ingestion (§3.5) — nothing else moves them. The unit's `lifecycle` and `campaign_compliance` are two parallel state dimensions on one record and evolve independently: decommissioning acts on the first, campaign cascades on the second. The units list endpoint supports filtering by `engine_family_id`, `fleet_id`, `lifecycle`, and `campaign_compliance`, and a fleet's own units are listed within the fleet's scope.

A computed coverage read is available for any unit: evaluated against the current logical clock, it reports `base_covered` and `base_coverage_end` for the base warranty window, `extended_covered` and `extended_coverage_end` for the extended emissions window, and `extended_applies_to` describing the extended coverage's applicability. Because the read names no failed component class, `extended_covered` reflects only the time, miles, and hours legs of the extended rule, and `extended_applies_to` is the comma-joined class list `AFTERTREATMENT_SCR,AFTERTREATMENT_DPF,DOSING_SYSTEM,NOX_SENSOR,EGR_SYSTEM`. The rule it evaluates is the same coverage determination used when a claim is filed, specified in full in §3.7.

Decommissioning retires a unit: a `PlatformAdmin` moves it from `IN_SERVICE` to `DECOMMISSIONED`, which is terminal. The transition is blocked while any campaign work order for the unit sits in `SCHEDULED` or `IN_BAY` (`ERR_WORK_ORDERS_OUTSTANDING`, HTTP 409) and while any reman order for the unit sits in `QUOTED`, `AWAITING_CORE`, or `CORE_RECEIVED` (`ERR_REMAN_ORDER_OPEN`, HTTP 409).

In-use compliance is recorded per family by a `RegulatoryOfficer` as an `InUseComplianceResult`, an append-only record carrying `test_period_label`, `sample_size`, and `passing_units`. Recording requires the family to be in `IN_PRODUCTION` (`ERR_FAMILY_NOT_IN_PRODUCTION`). The `sample_size` must be at least 5 — a smaller sample is rejected with `ERR_SAMPLE_SIZE_TOO_SMALL` (HTTP 422) — while `passing_units` must be at least 0 and no greater than `sample_size`, with violations caught earlier as shape errors under `ERR_INVALID_REQUEST`. The record's `conformity_ratio` is the passing count divided by the sample size, rounded half-up to 4 decimal places; its `outcome` is `CONFORMING` when that rounded ratio is at least 0.9 — a ratio of exactly 0.9000 conforms, because the threshold is inclusive — and `NON_CONFORMING` otherwise. Each record stamps `recorded_at` from the logical clock. The family's `in_use_compliance_status` is then stamped from the latest result recorded for the family's `test_period_label`: recording order decides, never an average across results, and the stamp is a mutation of the family, so the family's `version` increments. This latest-result rule is what lets a confirmatory test under a repeated `test_period_label` reverse a family's standing from `NON_CONFORMING` back to `CONFORMING`, or the reverse.

### 3.5. Telematics Ingestion, Maintenance History, and Fault Prediction

Two append-only ledgers accumulate around each engine unit: its maintenance history and its telematics stream.

A maintenance record is appended within a unit's scope by the fleet's own `FleetManager` or by a `PlatformAdmin`, and carries `performed_at`, the `maintenance_type` — one of `OIL_CHANGE`, `DPF_CLEAN`, `DEF_SERVICE`, `VALVE_ADJUST`, or `SENSOR_REPLACE` — the `odometer_at_service`, and an optional `def_quality_ok` flag that defaults to true and is only meaningful for `DEF_SERVICE` entries. The odometer reading must not exceed the unit's current `accumulated_miles`; a reading beyond the unit's accumulated miles is rejected with `ERR_ODOMETER_EXCEEDS_UNIT` (HTTP 422). A `FleetManager` whose fleet is `SUSPENDED` may not append maintenance records at all — the attempt is rejected with `ERR_FLEET_SUSPENDED` (HTTP 409) — and a `FleetManager` may only append to units whose `fleet_id` matches their own `X-User-ID` (`ERR_FLEET_MISMATCH`).

Telematics snapshots are ingested by a `PlatformAdmin` within a unit's scope. Each snapshot carries `recorded_at`, `odometer_miles`, `engine_hours`, a `fault_codes` list whose entries each carry a `code` and a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, the `def_consumption_gal` consumed since the previous snapshot, and the `nox_sensor_drift_ppm` magnitude. Monotonicity is enforced in both dimensions: `odometer_miles` must be no less than the unit's `accumulated_miles` and `engine_hours` no less than its `accumulated_hours` (`ERR_NON_MONOTONIC_ODOMETER`, HTTP 409), and `recorded_at` must be strictly after the unit's `last_snapshot_at` — an equal timestamp is not acceptable — (`ERR_NON_MONOTONIC_TELEMATICS`, HTTP 409). On acceptance the unit's accumulated miles and hours advance to the snapshot's readings, `last_snapshot_at` becomes the snapshot's `recorded_at`, and the unit's `version` increments.

Ingestion also computes the snapshot's `fault_risk_score`, an integer capped at 100, from three components. First, fault points: every `fault_codes` entry contributes 40 points when its severity is `CRITICAL`, 20 when `MAJOR`, and 5 when `MINOR`. Second, drift points: the absolute value of `nox_sensor_drift_ppm` is divided by 10 and floored to a whole number, and the result is capped at 30 drift points. Third, a DEF penalty: when `def_consumption_gal` is exactly 0 and the odometer delta — the snapshot's `odometer_miles` minus the unit's accumulated miles as they stood immediately before this ingestion — exceeds 500 miles, a flat 25 penalty points are added; otherwise none. The score is the sum of the three components, capped at 100. When the resulting score is at least 70, the unit's `predictive_service_due` flag is set true; the flag is an advisory latch and is never cleared once set, flagging the unit for service scheduling driven by the data stream.

### 3.6. Service Network: Centers, Technicians, and Diagnostic Tools

Remedy execution and claims repair run through an authorized service network administered by `PlatformAdmin` operators. A `ServiceCenter` is registered with its `name`, `region`, and `bay_capacity_per_day` — the number of work bays usable per calendar day, at least 1. A new center starts with `auth_status` `APPLIED`, `authorization_tier` `BASIC`, and its remanufacturing ledger fields `core_credit_balance_cents` and `core_reversal_count` both at 0.

The authorization lifecycle is deliberate. An audit moves the center from `APPLIED` to `AUDITED`. Authorization then moves it from `AUDITED` to `AUTHORIZED` at a supplied `authorization_tier` of `BASIC`, `CERTIFIED`, or `MASTER`, and is refused with `ERR_NO_QUALIFIED_TECHNICIAN` (HTTP 409) unless at least one of the center's technicians is `CERT_ACTIVE` with `emissions_endorsed` set true at that moment. Suspension moves an `AUTHORIZED` center to `SUSPENDED`, and it happens in two ways: a `PlatformAdmin` may suspend a center directly, or the system suspends it as a side effect of the remanufacturing core-reversal cascade when the center's `core_reversal_count` reaches 2 (§3.9). Reinstatement moves a `SUSPENDED` center back to `AUTHORIZED` and resets its `core_reversal_count` to 0, which is the loop that lets a reversal-suspended center recover. Revocation is terminal: a center in `AUTHORIZED` or `SUSPENDED` may be moved to `REVOKED`, from which no transition leaves.

Technicians are certified into a center by a `PlatformAdmin`, who supplies the technician's `full_name`, a `badge_id` unique within that center (`ERR_DUPLICATE_BADGE_ID`, HTTP 409), a `certification_level` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, and the `emissions_endorsed` flag. A technician cannot be certified into a `REVOKED` center — the attempt is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409); that is the only center-state gate on technician certification, so certification into an `APPLIED`, `AUDITED`, or `SUSPENDED` center proceeds. On certification, `certified_at` is stamped from the logical clock and `certification_expires_at` is set exactly 730 days later; the technician's `cert_status` begins as `CERT_ACTIVE`. Recertification — available from either `CERT_ACTIVE` or `EXPIRED` — restamps `certified_at` from the current clock, extends `certification_expires_at` to 730 days after the recertification instant, and applies an optional `new_level` to `certification_level` when one is supplied. Expiry itself is lazy, per §2.4: whenever the logical clock is strictly later than `certification_expires_at`, the technician is `EXPIRED` on next read or use; at the exact expiry instant the technician remains `CERT_ACTIVE`.

Diagnostic tools follow the same pattern on a shorter cycle. Issuing a tool to a center — no center-state gate applies; a tool may be issued to a center in any `auth_status` — records its `tool_serial` — unique program-wide, so a duplicate is rejected with `ERR_DUPLICATE_TOOL_SERIAL` (HTTP 409) — and its `software_version`, stamps `issued_at` from the clock, and sets `calibration_valid_until` exactly 365 days later, with `tool_status` starting as `CALIBRATED_ACTIVE`. When the clock moves strictly past `calibration_valid_until`, the tool lazily becomes `RECAL_DUE`; recalibration by a `PlatformAdmin` — available only while the tool is `RECAL_DUE`, with a `CALIBRATED_ACTIVE` tool rejecting it as `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — returns it to `CALIBRATED_ACTIVE` and extends `calibration_valid_until` to 365 days after the recalibration instant. Technician lists and tool lists apply these lazy evaluations when read, so a list response always reflects the clock as of the request.

### 3.7. Extended Emissions Warranty: Coverage, Adjudication, and Payment

Warranty claims are filed against a failed unit and adjudicated by an independent adjudicator; the claimant never adjudicates, because the filing roles (`FleetManager`, `ServiceAdvisor`) and the deciding role (`WarrantyAdjudicator`) are disjoint on every claim workflow step.

Coverage determination runs twice in the product surface — when a claim is created, where it stamps the claim's `coverage_variant` or rejects the filing, and in the per-unit coverage read described in §3.4 — and the rule is the same in both places. Let the standard be the regulation standard of the unit's family. The base warranty window is open when the logical clock is strictly earlier than the unit's `in_service_date` plus the standard's `base_warranty_years` calendar years, and the unit's `accumulated_miles` is strictly less than the standard's `base_warranty_miles`; engine hours play no part in the base window. The extended emissions window uses per-axis minimums of program constants against the standard's useful-life obligations: the extended years term is the smaller of 5 years and the standard's `useful_life_years`, the extended mileage term is the smaller of 100,000 miles and the standard's `useful_life_miles`, and the extended hours term is the smaller of 3,000 hours and the standard's `useful_life_hours`. The extended window is open only when all of the following hold: the claim's `failed_component_class` is one of the five emissions component classes — `AFTERTREATMENT_SCR`, `AFTERTREATMENT_DPF`, `DOSING_SYSTEM`, `NOX_SENSOR`, or `EGR_SYSTEM` — and the clock is strictly before `in_service_date` plus the extended years term, and `accumulated_miles` is strictly below the extended mileage term, and `accumulated_hours` is strictly below the extended hours term. When the extended window is open the claim is stamped `EXTENDED_EMISSIONS`; otherwise, when the base window is open, it is stamped `BASE_WARRANTY`; when neither window is open the filing is rejected with `ERR_COVERAGE_EXPIRED` (HTTP 409). Every window comparison is strict: a unit sitting exactly on a limit is not covered by that window. When both windows are open the extended variant takes precedence. A claim on a non-emissions class such as `ENGINE_BASE` can therefore only ever carry the `BASE_WARRANTY` variant.

Filing is performed by a `FleetManager` for a unit of their own fleet — the unit's `fleet_id` must equal the filer's `X-User-ID` (`ERR_FLEET_MISMATCH`) — or by a `ServiceAdvisor` as the repairing center, in which case the claim's `service_center_id` must equal the advisor's `X-User-ID` (`ERR_CENTER_MISMATCH`). The payload names the `engine_unit_id`, the `service_center_id`, the `failed_component_class`, the OEM `failure_code`, and the `claimed_amount_cents`, which must be greater than 0. After shape, existence, and ownership, the filing passes through three state gates in this order: the unit's `lifecycle` must be `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`), the filing fleet must be `ACTIVE` (`ERR_FLEET_SUSPENDED`), and the repairing center's `auth_status` must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); coverage determination runs last. A filed claim starts in `SUBMITTED` with `review_round` 0, captures the filer's `submitted_by_role` and `submitted_by_user_id`, and leaves `neglect_score`, `approved_amount_cents`, `customer_share_cents`, `decided_by_user_id`, and `paid_at` unset. The claims list endpoint supports filtering by `engine_unit_id`, `service_center_id`, and `status`.

Review is a bounded cycle. A `WarrantyAdjudicator` starts review, moving the claim from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the adjudicator may request more information, moving the claim to `INFO_REQUESTED` and incrementing `review_round` — but only while `review_round` is below 2; a claim that has already consumed 2 information rounds rejects the request with `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 409), and the adjudicator must then decide. The filing side answers an information request by resubmitting with a `supplemental_note`, moving the claim from `INFO_REQUESTED` back to `UNDER_REVIEW`; resubmission is accepted from the `FleetManager` of the fleet that owns the claim's unit, or from the `ServiceAdvisor` whose `X-User-ID` equals the claim's `service_center_id`.

Adjudication computes the claim's `neglect_score` from the unit's full maintenance and telematics history — every `MaintenanceRecord` and `TelematicsSnapshot` of the unit, regardless of age — before any decision is accepted. Expected oil changes are the unit's `accumulated_miles` divided by the 15,000-mile maintenance interval, floored to a whole number; missed oil changes are that expectation minus the count of the unit's `OIL_CHANGE` records, and never less than zero. Each missed oil change contributes 25 points. Each `DEF_SERVICE` record with `def_quality_ok` set false contributes 15 points. Each telematics snapshot whose `fault_codes` contain at least one `CRITICAL` entry contributes 20 points. The score is the sum, capped at 100. The score bands are binding on the decision: a score below 30 is consistent only with an `APPROVE_FULL` decision; a score of at least 30 and below 60 is consistent only with `APPROVE_PARTIAL`; a score of at least 60 is consistent only with `DENY_NEGLECT`. A `decision` that falls outside its band is rejected with `ERR_DECISION_INCONSISTENT_WITH_SCORE` (HTTP 422).

The three decisions have distinct financial outcomes. On `APPROVE_FULL` the claim moves to `APPROVED_FULL` with `approved_amount_cents` equal to `claimed_amount_cents` and `customer_share_cents` equal to 0. On `APPROVE_PARTIAL` the claim moves to `APPROVED_PARTIAL` after a proration whose variant is selected by the stamped `coverage_variant`, with a pinned rounding order — the per-unit rate is rounded first, then multiplied. Under the `BASE_WARRANTY` variant the proration is time-based: the term in days is the standard's `base_warranty_years` multiplied by 365; the elapsed days are the whole days from the unit's `in_service_date` to the claim's submission instant, never negative; the daily rate is the `claimed_amount_cents` divided by the term in days, rounded half-up to whole cents; and the raw customer share is that rounded daily rate multiplied by the elapsed days. Under the `EXTENDED_EMISSIONS` variant the proration is mileage-based: the term in miles is the smaller of 100,000 and the standard's `useful_life_miles`; the per-mile rate is the `claimed_amount_cents` divided by that term, rounded half-up to whole cents; and the raw customer share is the rounded per-mile rate multiplied by the unit's `accumulated_miles`. Identical claim data therefore yields different customer shares under the two variants. Under both variants the share is then capped: the cap is half of `claimed_amount_cents` rounded half-up to whole cents, `customer_share_cents` is the smaller of the raw share and the cap, and `approved_amount_cents` is the remainder of the claim after the customer share. On `DENY_NEGLECT` the claim moves to `DENIED_NEGLECT` with `approved_amount_cents` set to 0 and `customer_share_cents` equal to the full `claimed_amount_cents`. Every adjudication stamps `decided_by_user_id` with the adjudicator's `X-User-ID`.

A denial for neglect cascades beyond the claim. The unit's fleet has its `neglect_denial_count` incremented by 1 — a mutation of the fleet that increments the fleet's `version` — and when that count reaches 3, the fleet transitions from `ACTIVE` to `SUSPENDED`, a second fleet mutation within the same adjudication request. A `SUSPENDED` fleet's `FleetManager` can no longer file claims or append maintenance records until a `PlatformAdmin` reinstates the fleet.

Payment is the terminal act for approved claims: a `PlatformAdmin` pays a claim in `APPROVED_FULL` or `APPROVED_PARTIAL`, moving it to `PAID` and stamping `paid_at` from the logical clock. `PAID` and `DENIED_NEGLECT` are both terminal; a denied claim is never paid.

### 3.8. Field Campaigns and Shop Execution

When in-use surveillance or engineering analysis identifies a fleet-wide issue, a `RegulatoryOfficer` declares a `FieldCampaign` against the affected family. Declaration is allowed while the family is in `CERTIFIED`, `IN_PRODUCTION`, or `COMPLIANCE_HOLD`; against any other family state it is rejected as `ERR_INVALID_STATE_TRANSITION`. The declaration carries the `engine_family_id`, a `campaign_code` unique within the family (`ERR_DUPLICATE_CAMPAIGN_CODE`, HTTP 409), the `campaign_type` — `RECALL` or `SERVICE_CAMPAIGN` — a `defect_summary`, a `remedy_description`, the default `remedy_bay_days` per unit remedy (at least 1), and an optional `completion_threshold` that defaults to 0.95 when omitted. A new campaign is `DRAFT`, with `notified_unit_count` and `verified_unit_count` at 0, `completion_rate` at 0, and `announced_at` unset.

Announcement is the campaign's point of no return and its largest cascade. A `RegulatoryOfficer` announces a `DRAFT` campaign, moving it to `ANNOUNCED`. The family must at that moment be in `CERTIFIED` or `IN_PRODUCTION` — announcement from any other family state fails as `ERR_INVALID_STATE_TRANSITION` — and a `RECALL` campaign additionally requires the family's `in_use_compliance_status` to be `NON_CONFORMING`, otherwise the announce is rejected with `ERR_RECALL_REQUIRES_NON_CONFORMANCE` (HTTP 409). On success, three things happen in the same request. First, the family itself transitions to `COMPLIANCE_HOLD`, with the family's `version` incrementing. Second, every engine unit of the family whose `lifecycle` is `IN_SERVICE` and whose `campaign_compliance` is not already `CAMPAIGN_OPEN` transitions to `CAMPAIGN_OPEN`, each such unit's `version` incrementing — this is the fleet notification, and it re-opens units that a prior campaign had left `REMEDIED`. Third, the campaign stamps `announced_at` from the logical clock and records `notified_unit_count` as the number of units flagged. A campaign announced against a family whose units are all decommissioned or already open therefore records a `notified_unit_count` of 0.

Execution begins when a `RegulatoryOfficer` moves the campaign from `ANNOUNCED` to `IN_PROGRESS`, which requires `notified_unit_count` to be greater than 0; announcing into an empty fleet leaves the campaign unable to begin, and the attempt is rejected with `ERR_CAMPAIGN_HAS_NO_UNITS` (HTTP 409).

The unit remedy is the `CampaignWorkOrder`, scheduled by a `ServiceAdvisor` within a campaign's scope with the `engine_unit_id`, the `service_center_id`, the `assigned_technician_id`, the `scheduled_start_day`, and the `bay_days` span (at least 1). Scheduling passes through five gates beyond the standard checks: the campaign must be `IN_PROGRESS` (`ERR_CAMPAIGN_NOT_IN_PROGRESS`, HTTP 409); the unit's `campaign_compliance` must be `CAMPAIGN_OPEN` (`ERR_UNIT_CAMPAIGN_NOT_OPEN`, HTTP 409); the executing center must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409); and the shop's bay capacity must absorb the booking. The advisor's own center ownership applies as well: the `service_center_id` must equal the advisor's `X-User-ID` (`ERR_CENTER_MISMATCH`). The order records the parent campaign's `campaign_id` and starts in `SCHEDULED`.

Bay capacity is evaluated per calendar day, with no time-of-day component. A new work order occupies one bay on every calendar day from its `scheduled_start_day` up to but not including the day `bay_days` later. For each day in that span, the system counts the center's other work orders in `SCHEDULED` or `IN_BAY` status whose own spans cover that day; the create is valid exactly when, for every day of the new span, that occupied count plus one is no greater than the center's `bay_capacity_per_day`. Days on which the span would exceed capacity reject the create with `ERR_CAPACITY_EXCEEDED` (HTTP 409). Work orders in `COMPLETED`, `VERIFIED`, or `CANCELLED` status occupy nothing, so completion, verification, and cancellation all release bays.

Shop execution then walks the order through its lifecycle. Starting the order moves it from `SCHEDULED` to `IN_BAY` and requires the center to hold at least one diagnostic tool whose effective status is `CALIBRATED_ACTIVE` at that moment (`ERR_TOOL_NOT_CALIBRATED`, HTTP 409) — this is where the lazy `RECAL_DUE` evaluation of §2.4 bites, because a tool whose validity has lapsed does not count. Completion moves the order from `IN_BAY` to `COMPLETED` and stamps `completed_at`. Cancellation is available from `SCHEDULED`, moves the order to `CANCELLED`, and releases its occupied bay-days, restoring the capacity invariant. Start, completion, and cancellation are all `ServiceAdvisor` actions constrained to the advisor's own center.

Verification belongs to a `RegulatoryOfficer` and drives the program's deepest cascade. The campaign must be in `IN_PROGRESS` or `COMPLETION_REVIEW` for a verification to land (`ERR_INVALID_STATE_TRANSITION`). On success the order moves to `VERIFIED` — terminal — and stamps `verified_at`; then, in the same request: the unit transitions from `CAMPAIGN_OPEN` to `REMEDIED` when it is currently `CAMPAIGN_OPEN` (unit `version` increments), and a unit in any other `campaign_compliance` state is left unchanged; the campaign's `verified_unit_count` increments by 1 and its `completion_rate` is recomputed (campaign `version` increments); if the campaign is in `COMPLETION_REVIEW` and the recomputed rate meets its threshold, the campaign closes as described below; and if that closure leaves the family with no other open campaign, the family exits `COMPLIANCE_HOLD` (family `version` increments).

Completion governance closes the loop. A `RegulatoryOfficer` may move an `IN_PROGRESS` campaign to `COMPLETION_REVIEW`; the request recomputes the campaign's `completion_rate` — 0 while `notified_unit_count` is 0, otherwise the verified count divided by the notified count, rounded half-up to 4 decimal places — and, when `notified_unit_count` is greater than 0 and the rate is at least the campaign's `completion_threshold` (the boundary is inclusive), the campaign advances all the way to `CLOSED` within the same request. When the rate falls short, the campaign sits in `COMPLETION_REVIEW` until either further verifications push it over the threshold — verification re-evaluates closure while the campaign is in that state — or the officer resumes execution, moving it back from `COMPLETION_REVIEW` to `IN_PROGRESS` in the revert loop. Closure itself is the system transition from `COMPLETION_REVIEW` to `CLOSED`: in addition to the campaign's own `version` increment, if no other campaign of the same family sits in `ANNOUNCED`, `IN_PROGRESS`, or `COMPLETION_REVIEW`, the family exits `COMPLIANCE_HOLD` — to `IN_PRODUCTION` when `production_entered` is true, otherwise to `CERTIFIED`. `CLOSED` is terminal. The work-order list endpoint supports filtering by `campaign_id`, `engine_unit_id`, `service_center_id`, `assigned_technician_id`, and `status`.

### 3.9. Remanufacturing Orders and the Core Credit Ledger

The remanufacturing program exchanges rebuilt engines and components against returned cores, and its money moves through each center's `core_credit_balance_cents` ledger. A `ServiceAdvisor` quotes a `RemanOrder` with the `engine_unit_id` of the unit being remanufactured — which is also the source of the core — the ordering `service_center_id`, the `reman_scope` of `ENGINE` or `COMPONENT`, the `component_type` — one of `SCR_CATALYST`, `DPF`, `DOSER`, `TURBO`, or `INJECTOR` — which is required exactly when the scope is `COMPONENT` and rejected as a shape error (`ERR_INVALID_REQUEST`) when the pairing is violated, the `spec_level` of `STANDARD`, `PLUS`, or `PREMIUM`, the `quoted_price_cents` (greater than 0), the `quoted_core_value_cents` (at least 0), the `expected_core_return_by` deadline, and the optimistic-concurrency field `expected_engine_unit_version` equal to the unit's current `version` (`ERR_STALE_VERSION`, HTTP 412, per §2.7). The unit must be `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`), the center must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`), and the advisor's own-center ownership applies (`ERR_CENTER_MISMATCH`).

Two computed money fields are fixed at creation, in a pinned order. First the `spec_level_surcharge_cents`: the `quoted_price_cents` multiplied by the spec-level multiplier minus one, rounded half-up to whole cents, where the multiplier is 1.0 for `STANDARD` (a surcharge of zero), 1.15 for `PLUS`, and 1.3 for `PREMIUM`. Second, the effective price — the quoted price plus the surcharge — which is not itself stored but anchors everything downstream. Also at creation, the `provisional_core_credit_cents` is computed as 60 percent of the `quoted_core_value_cents` (that is, the quoted core value multiplied by 0.6), rounded half-up to whole cents. A new order is `QUOTED`, with `core_grade` `UNGRADED` and `final_core_credit_cents`, `invoice_total_cents`, and `core_returned_at` unset, and its creation increments the unit's `version` by one — telematics ingestion and campaign cascades can legitimately advance that same version between quote and order, which is exactly the staleness the OCC field guards. The reman-order list endpoint supports filtering by `engine_unit_id`, `service_center_id`, and `status`.

Confirmation moves the order from `QUOTED` to `AWAITING_CORE` and posts the provisional credit: the center's `core_credit_balance_cents` increases by `provisional_core_credit_cents`, a center mutation that increments the center's `version`. Core receipt moves the order from `AWAITING_CORE` to `CORE_RECEIVED` and is only possible while the logical clock is at or before `expected_core_return_by` — the boundary is inclusive, so a core arriving at exactly the deadline is on time; a later arrival is rejected with `ERR_CORE_RETURN_WINDOW_CLOSED` (HTTP 409). Receipt stamps `core_returned_at` from the clock.

Grading belongs to the `RemanPlanner`. Grading a `CORE_RECEIVED` order with a `core_grade` of `A`, `B`, or `C` moves it to `CREDIT_ISSUED` and settles the final credit in a pinned order: the grade value is the `quoted_core_value_cents` multiplied by the grade percentage — the full value (1.0) for grade `A`, 0.75 for grade `B`, and 0.5 for grade `C` — rounded half-up to whole cents; the credit cap is the effective price multiplied by 0.4 (that is, 40 percent), rounded half-up to whole cents; and the `final_core_credit_cents` is the smaller of the two. The cap is computed against the effective price including the spec-level surcharge, never against the bare quoted price — that alternative order is expressly forbidden. The `invoice_total_cents` is then the effective price minus the final credit. The center's ledger absorbs the difference: `core_credit_balance_cents` moves by the final credit minus the provisional credit, with the center's `version` incrementing. Because the provisional credit is a flat 60 percent of quoted core value with no price cap, the provisional and final figures diverge whenever the grade is not `A` or the 40-percent cap binds, and the ledger delta at grading is exactly that divergence.

A grade of `REJECT` — defined as a 0.0 grade percentage — takes a different branch: the order moves to `CORE_REJECTED`, `final_core_credit_cents` is set to 0, the center's balance decreases by the full provisional credit, and the center's `core_reversal_count` increments by 1, all center mutations. When that count reaches 2, the center transitions from `AUTHORIZED` to `SUSPENDED` as a further system mutation of the same request — the reversal-suspension cascade that §3.6's reinstatement loop exists to reverse.

Forfeiture covers cores that never arrive. From `AWAITING_CORE`, a `ServiceAdvisor` (own center) or a `RemanPlanner` may forfeit the core, but only when the logical clock is strictly after `expected_core_return_by`; on or before the deadline the attempt is rejected with `ERR_CORE_NOT_YET_LATE` (HTTP 409). Forfeiture moves the order to `CORE_FORFEIT`, sets `final_core_credit_cents` to 0, and applies the same reversal cascade as a rejected core: the provisional credit is withdrawn from the center's balance, `core_reversal_count` increments, and the center suspends at 2 reversals.

Closure is the quiet end: a `ServiceAdvisor` closes a `CREDIT_ISSUED` order, moving it to `CLOSED`. `CLOSED`, `CORE_REJECTED`, and `CORE_FORFEIT` are all terminal.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including all state transitions and the logical-clock set — return a `200 OK` status code. Request payloads, computed fields, and side effects are specified in §2 and §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/emissions/regulation-standards` | Create a regulation standard | PlatformAdmin |
| GET | `/emissions/regulation-standards` | List regulation standards | Any |
| GET | `/emissions/regulation-standards/{id}` | Get a regulation standard | Any |
| POST | `/emissions/regulation-standards/{id}/publish` | Publish a draft standard | RegulatoryOfficer |
| POST | `/emissions/regulation-standards/{id}/supersede` | Supersede a published standard | RegulatoryOfficer |
| POST | `/emissions/engine-families` | Create an engine family | CertificationEngineer |
| GET | `/emissions/engine-families` | List engine families | Any |
| GET | `/emissions/engine-families/{id}` | Get an engine family | Any |
| POST | `/emissions/engine-families/{id}/begin-testing` | Move a family from design into testing | CertificationEngineer |
| POST | `/emissions/engine-families/{id}/submit-review` | Submit a family for certification review | CertificationEngineer |
| POST | `/emissions/engine-families/{id}/return-to-testing` | Return a family under review to testing | CertificationEngineer |
| POST | `/emissions/engine-families/{id}/certify` | Certify a family under review | RegulatoryOfficer |
| POST | `/emissions/engine-families/{id}/enter-production` | Move a certified family into production | RegulatoryOfficer |
| POST | `/emissions/engine-families/{id}/phase-out` | Phase out a family | RegulatoryOfficer |
| GET | `/emissions/engine-families/{id}/aftertreatment-specs` | List a family's aftertreatment spec versions | Any |
| GET | `/emissions/engine-families/{id}/test-runs` | List a family's certification test runs | Any |
| GET | `/emissions/engine-families/{id}/engine-units` | List a family's serialized units | Any |
| GET | `/emissions/engine-families/{id}/field-campaigns` | List a family's field campaigns | Any |
| GET | `/emissions/engine-families/{id}/in-use-results` | List a family's in-use compliance results | Any |
| POST | `/emissions/engine-families/{familyId}/aftertreatment-specs` | Create a new aftertreatment spec version for a family | CertificationEngineer |
| GET | `/emissions/aftertreatment-specs/{id}` | Get an aftertreatment spec | Any |
| POST | `/emissions/aftertreatment-specs/{id}/calibrate` | Run dosing calibration on a draft spec | CertificationEngineer |
| POST | `/emissions/aftertreatment-specs/{id}/activate` | Activate a calibrated draft spec | CertificationEngineer |
| POST | `/emissions/engine-families/{familyId}/test-runs` | Schedule a certification test run | CertificationEngineer |
| GET | `/emissions/test-runs/{id}` | Get a certification test run | Any |
| POST | `/emissions/test-runs/{id}/record-results` | Record measured results for a scheduled run | CertificationEngineer |
| POST | `/emissions/test-runs/{id}/review` | Accept or reject a completed run | RegulatoryOfficer |
| POST | `/emissions/test-runs/{id}/invalidate` | Invalidate an accepted run | RegulatoryOfficer |
| POST | `/emissions/fleets` | Register a fleet | PlatformAdmin |
| GET | `/emissions/fleets/{id}` | Get a fleet | Any |
| POST | `/emissions/fleets/{id}/reinstate` | Reinstate a suspended fleet | PlatformAdmin |
| GET | `/emissions/fleets/{id}/engine-units` | List units owned by a fleet | Any |
| POST | `/emissions/engine-units` | Register a serialized engine unit | PlatformAdmin |
| GET | `/emissions/engine-units` | List engine units | Any |
| GET | `/emissions/engine-units/{id}` | Get an engine unit | Any |
| POST | `/emissions/engine-units/{id}/decommission` | Decommission a unit | PlatformAdmin |
| GET | `/emissions/engine-units/{id}/coverage` | Computed warranty-coverage read for a unit | Any |
| POST | `/emissions/engine-units/{id}/maintenance-records` | Append a maintenance record | FleetManager, PlatformAdmin |
| GET | `/emissions/engine-units/{id}/maintenance-records` | List a unit's maintenance records | Any |
| POST | `/emissions/engine-units/{unitId}/telematics-snapshots` | Ingest a telematics snapshot | PlatformAdmin |
| GET | `/emissions/engine-units/{id}/telematics-snapshots` | List a unit's telematics snapshots | Any |
| POST | `/emissions/service-centers` | Register a service center | PlatformAdmin |
| GET | `/emissions/service-centers/{id}` | Get a service center | Any |
| POST | `/emissions/service-centers/{id}/audit` | Mark a center audited | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/authorize` | Authorize an audited center at a tier | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/suspend` | Suspend an authorized center | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/reinstate` | Reinstate a suspended center | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/revoke` | Revoke a center (terminal) | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/technicians` | Certify a technician into a center | PlatformAdmin |
| GET | `/emissions/service-centers/{id}/technicians` | List a center's technicians | Any |
| POST | `/emissions/technicians/{id}/recertify` | Recertify a technician, extending expiry | PlatformAdmin |
| POST | `/emissions/service-centers/{id}/diagnostic-tools` | Issue a diagnostic tool to a center | PlatformAdmin |
| GET | `/emissions/service-centers/{id}/diagnostic-tools` | List a center's diagnostic tools | Any |
| POST | `/emissions/diagnostic-tools/{id}/recalibrate` | Recalibrate a tool, extending validity | PlatformAdmin |
| POST | `/emissions/warranty-claims` | File an emissions warranty claim | FleetManager, ServiceAdvisor |
| GET | `/emissions/warranty-claims` | List warranty claims | Any |
| GET | `/emissions/warranty-claims/{id}` | Get a warranty claim | Any |
| POST | `/emissions/warranty-claims/{id}/start-review` | Start adjudication review of a claim | WarrantyAdjudicator |
| POST | `/emissions/warranty-claims/{id}/request-info` | Request information on a claim under review | WarrantyAdjudicator |
| POST | `/emissions/warranty-claims/{id}/resubmit` | Resubmit a claim after an information request | FleetManager, ServiceAdvisor |
| POST | `/emissions/warranty-claims/{id}/adjudicate` | Decide a claim under review | WarrantyAdjudicator |
| POST | `/emissions/warranty-claims/{id}/pay` | Pay an approved claim | PlatformAdmin |
| POST | `/emissions/field-campaigns` | Declare a field campaign | RegulatoryOfficer |
| GET | `/emissions/field-campaigns/{id}` | Get a field campaign | Any |
| POST | `/emissions/field-campaigns/{id}/announce` | Announce a draft campaign | RegulatoryOfficer |
| POST | `/emissions/field-campaigns/{id}/begin-execution` | Begin execution of an announced campaign | RegulatoryOfficer |
| POST | `/emissions/field-campaigns/{id}/completion-review` | Move a campaign into completion review | RegulatoryOfficer |
| POST | `/emissions/field-campaigns/{id}/resume-execution` | Resume execution of a campaign under review | RegulatoryOfficer |
| POST | `/emissions/field-campaigns/{campaignId}/work-orders` | Schedule a unit remedy under a campaign | ServiceAdvisor |
| GET | `/emissions/campaign-work-orders` | List campaign work orders | Any |
| GET | `/emissions/campaign-work-orders/{id}` | Get a campaign work order | Any |
| POST | `/emissions/campaign-work-orders/{id}/start` | Start a scheduled work order | ServiceAdvisor |
| POST | `/emissions/campaign-work-orders/{id}/complete` | Complete an in-bay work order | ServiceAdvisor |
| POST | `/emissions/campaign-work-orders/{id}/verify` | Verify a completed remedy | RegulatoryOfficer |
| POST | `/emissions/campaign-work-orders/{id}/cancel` | Cancel a scheduled work order | ServiceAdvisor |
| POST | `/emissions/reman-orders` | Quote a remanufacture order | ServiceAdvisor |
| GET | `/emissions/reman-orders` | List reman orders | Any |
| GET | `/emissions/reman-orders/{id}` | Get a reman order | Any |
| POST | `/emissions/reman-orders/{id}/confirm` | Confirm a quote and post the provisional core credit | ServiceAdvisor |
| POST | `/emissions/reman-orders/{id}/receive-core` | Record core receipt within the return window | ServiceAdvisor |
| POST | `/emissions/reman-orders/{id}/grade-core` | Grade a received core and settle the final credit | RemanPlanner |
| POST | `/emissions/reman-orders/{id}/forfeit-core` | Forfeit an overdue core | ServiceAdvisor, RemanPlanner |
| POST | `/emissions/reman-orders/{id}/close` | Close a credit-issued order | ServiceAdvisor |
| POST | `/emissions/engine-families/{familyId}/in-use-results` | Record an in-use compliance result | RegulatoryOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in §2 and §3 alongside the rules that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_FLEET_MISMATCH` | 403 Forbidden |
| `ERR_CENTER_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_STANDARD_CODE` | 409 Conflict |
| `ERR_STANDARD_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STANDARD_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SUPERSESSION_WINDOW_INVALID` | 409 Conflict |
| `ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FAMILY_CODE` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_NO_ACTIVE_AFTERTREATMENT_SPEC` | 409 Conflict |
| `ERR_SPEC_NOT_CALIBRATED` | 409 Conflict |
| `ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING` | 409 Conflict |
| `ERR_REQUIRED_TEST_MISSING` | 409 Conflict |
| `ERR_TEST_RESULT_NOT_PASS` | 409 Conflict |
| `ERR_LAB_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL_NUMBER` | 409 Conflict |
| `ERR_FAMILY_NOT_IN_PRODUCTION` | 409 Conflict |
| `ERR_IN_SERVICE_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_UNIT_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_WORK_ORDERS_OUTSTANDING` | 409 Conflict |
| `ERR_REMAN_ORDER_OPEN` | 409 Conflict |
| `ERR_ODOMETER_EXCEEDS_UNIT` | 422 Unprocessable Entity |
| `ERR_NON_MONOTONIC_ODOMETER` | 409 Conflict |
| `ERR_NON_MONOTONIC_TELEMATICS` | 409 Conflict |
| `ERR_FLEET_SUSPENDED` | 409 Conflict |
| `ERR_DUPLICATE_BADGE_ID` | 409 Conflict |
| `ERR_DUPLICATE_TOOL_SERIAL` | 409 Conflict |
| `ERR_NO_QUALIFIED_TECHNICIAN` | 409 Conflict |
| `ERR_CENTER_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_QUALIFIED` | 409 Conflict |
| `ERR_TOOL_NOT_CALIBRATED` | 409 Conflict |
| `ERR_COVERAGE_EXPIRED` | 409 Conflict |
| `ERR_REVIEW_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_DECISION_INCONSISTENT_WITH_SCORE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CAMPAIGN_CODE` | 409 Conflict |
| `ERR_RECALL_REQUIRES_NON_CONFORMANCE` | 409 Conflict |
| `ERR_CAMPAIGN_HAS_NO_UNITS` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_CAMPAIGN_STILL_OPEN` | 409 Conflict |
| `ERR_UNIT_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CORE_RETURN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CORE_NOT_YET_LATE` | 409 Conflict |
| `ERR_SAMPLE_SIZE_TOO_SMALL` | 422 Unprocessable Entity |
