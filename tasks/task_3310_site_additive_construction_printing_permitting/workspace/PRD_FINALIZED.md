# Site Additive Construction API — Product Requirements Document

## 1. Introduction

On-site additive construction — printing structural walls layer by layer directly on the job site — sits at the intersection of heavy civil engineering, municipal permitting, and weather-sensitive concrete chemistry. This document specifies the Site Additive Construction API, the system of record that jurisdictions, engineers, printer operators, permit coordinators, and trade contractors use to coordinate every step from site registration through a finished, inspected, conventional-trade-ready building.

The API is mounted under `/construction`. It governs the registration of jurisdictions and the building-code postures they publish, the lifecycle of structural plans and their engineering revisions, the prosecution of permit applications (including alternative-means-of-compliance review where printed wall systems lack a prescriptive code path), the mobilization and leveling of the gantry printer, the qualification of printed material batches, the scheduling and continuous operation of print jobs with weather gating and interruption handling, the disposition of per-band layer inspections, the orchestration of conventional roof/electrical/plumbing/mechanical trades after printing, and — at the community scale — the tracking of learning-curve effects as a repeated plan is printed across many sites.

Two concerns dominate the design. First, additive construction has strict continuous-operation requirements: once a print starts, it must run with bounded interruptions, and an interruption that outlasts the layer cure window forces an abort. Second, printed construction rarely has a prescriptive building-code path; the system must therefore model the alternative-means review loop, including submission deadlines, resubmission rounds, and tiered fee calculation. Both concerns are time-sensitive, so the API is anchored to a logical clock that test-driving clients can advance explicitly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifying the acting user, and `X-User-Role` declaring the operational capacity the request is made under. The API recognizes eight roles, spelled exactly: `PlatformAdmin`, `SiteManager`, `PermitCoordinator`, `JurisdictionReviewer`, `Engineer`, `PrintOperator`, `QualityInspector`, and `TradeContractor`. A request missing `X-User-Role`, or carrying a role string the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

For every role above — `PlatformAdmin`, `SiteManager`, `PermitCoordinator`, `JurisdictionReviewer`, `Engineer`, `PrintOperator`, `QualityInspector`, and `TradeContractor` — the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `engineer_reviewer_id` or `approval_reviewer_id` on a `PlanRevision` when a transition writes it) but does not compare it to any entity's `id`. Segregation-of-duties checks compare two `X-User-ID` values for equality only.

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

List endpoints accept two query parameters: `limit` (defaults to 10, minimum 1, maximum 100) and `offset` (defaults to 0). Unless explicitly noted otherwise, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object on list responses carries `limit`, `offset`, `total_count`, and `has_more`. Several list endpoints accept additional filters — for example `status`, `trade`, `disposition`, or `outcome` — which narrow the result set before pagination is applied.

### 2.4. The Logical Clock

The system does not consult the host wall clock for any business decision. All timestamps that affect scheduling, cure windows, alternative-means review deadlines, interruption thresholds, and trade-task windows are evaluated against a server-maintained **logical clock**. The logical clock starts at `2026-09-01T00:00:00Z` before any test-driving call is made. A `PlatformAdmin` may advance it by posting a new `current_utc` value to the clock endpoint; the server MUST NOT fall back to wall-clock time under any circumstance.

Advancing the clock is not a passive operation. Each clock-set triggers a family of deferred system evaluations: any `PermitApplication` in `AM_REVIEW` whose `am_decision_due_at` is now in the past transitions to `RESUBMIT_REQUIRED`; any `OPEN` `PrintInterruption` whose elapsed time has crossed its `max_permissible_interruption_minutes` is flagged `OVERRUN`; foundation cure eligibility is re-evaluated; every `Site`'s `posture` is recomputed; and every conventional trade task's readiness (`is_startable` and `start_blockers`, and the `PLANNED` to `READY` auto-transition described in §3.10) is re-evaluated. The same lazy evaluations are also applied on the first read or write that touches an affected resource, so clients always observe a state that is consistent with the current logical clock.

### 2.5. Common Resource Properties

All entities in this system — `Jurisdiction`, `Site`, `CommunityDeployment`, `StructuralPlan`, `PlanRevision`, `PermitApplication`, `PrinterSetup`, `MaterialBatch`, `WeatherObservation`, `PrintJob`, `PrintInterruption`, `LayerInspection`, and `ConventionalTradeTask` — carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` — an integer starting at 1 that increments on every mutation.

Every entity listed above carries the full common set; no entity in this scaffold opts out of `updated_at` or `version`.

### 2.6. Nested Resource Retrieval and Containment

The URL hierarchy encodes containment: a `Site` belongs to a `Jurisdiction`; a `PlanRevision` belongs to a `StructuralPlan`; a `PermitApplication`, `PrinterSetup`, `MaterialBatch`, `WeatherObservation`, and `ConventionalTradeTask` each belong to a `Site`; a `PrintInterruption` and `LayerInspection` each belong to a `PrintJob`. The server validates path identifiers strictly left to right, returning `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist or whose parent linkage does not match the path. A request naming `sites/{site_id}/print-jobs/{job_id}` where the job exists but is parented to a different site is a 404, not a 403 or 409.

### 2.7. Precision, Rounding, and Monetary Representation

Monetary values are integer cents throughout the API (`fee_due_cents`, `fee_paid_cents`, `amount_cents`); no field carries fractional cents. Where a calculation produces a non-integer intermediate — most notably the resubmission markup on permit fees — the final value is rounded half-up to zero decimal places. Engineering values follow their natural units: bond strength in MPa is held to 1 decimal place, layer counts and minute durations are integers, and the learning-curve factor is rounded half-up to 4 decimal places. Whenever this document describes a comparison as inclusive (at least, at most, no later than, no earlier than), the boundary value satisfies the check.

### 2.8. Optimistic Concurrency Control on Site-Scoped Writes

Three creation endpoints require the caller to assert the version of the parent `Site` they last observed, so that site-level mutations made by another writer in the meantime (a foundation pour, a printer leveling, a permit decision) cannot be silently overwritten. Each of these endpoints requires `expected_site_version` as a non-optional request field:

- Creating a `PrinterSetup` on a site.
- Scheduling a `PrintJob` on a site.
- Creating a `ConventionalTradeTask` on a site.

If `expected_site_version` does not match the site's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check is purely a version-equality check; it does not depend on when the two requests arrived relative to one another. Endpoints not listed here do not take a version field.

### 2.9. Idempotency on Writes

Every POST request must carry an `Idempotency-Key` header. A POST missing the header is rejected with `ERR_MISSING_IDEMPOTENCY_KEY` (HTTP 400). Reusing a key with a request body different from the original submission is rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409). Reusing a key with an identical body returns the original response without re-executing the side effects.

### 2.10. Site Posture as a Derived Operating State

A `Site` carries a derived `posture` field — `OPERATING`, `PRECAUTIONARY`, or `STOP` — that summarizes whether it is safe to operate. Posture is recomputed on every weather observation, layer-inspection disposition, print-job state change, permit-application state change, site suspension, and clock advance. The rules are evaluated in priority order, and the first matching rule wins:

1. If the site's `status` is `SUSPENDED`, posture is `STOP`.
2. If any `LayerInspection` on any print job of the site has `disposition` `DEMOLISH_REQUIRED`, posture is `STOP`.
3. If any `PrintInterruption` on any active print job of the site has `status` `OVERRUN`, posture is `STOP`.
4. If the latest `WeatherObservation` (newest by `observed_at`, ties broken by earliest `created_at`) has `is_print_permissible` equal to false, and any print job on the site is `PRINTING` or `PAUSED`, posture is `PRECAUTIONARY`.
5. If any `LayerInspection` on the site has `disposition` `REPAIR_REQUIRED`, posture is `PRECAUTIONARY`.
6. Otherwise, posture is `OPERATING`.

Operations that begin or resume physical work — starting a print, resuming a paused print, starting a trade task, pouring a foundation, or submitting a permit — are blocked when the relevant posture gate fails, surfacing `ERR_POSTURE_BLOCKED` (HTTP 409).

### 2.11. Validation Ordering

When several validation rules could reject the same request, the server applies them in a fixed priority order so that callers observe deterministic failure codes. The order is:

1. **Authentication** — `X-User-Role` presence and recognizability (`ERR_UNAUTHENTICATED`).
2. **Idempotency header presence** on POSTs (`ERR_MISSING_IDEMPOTENCY_KEY`).
3. **Idempotency replay consistency** (`ERR_IDEMPOTENCY_REPLAY_MISMATCH`).
4. **Existence and containment** of every path identifier (`ERR_NOT_FOUND`).
5. **Role authorization** for the endpoint (`ERR_FORBIDDEN`).
6. **Posture and jurisdiction gating** (`ERR_POSTURE_BLOCKED`).
7. **Temporal gates** — alternative-means decision deadline, trade-task earliest/latest window, foundation cure time (`ERR_AM_REVIEW_EXPIRED`, `ERR_TRADE_TOO_EARLY`, `ERR_TRADE_OVERRUN`, `ERR_FOUNDATION_NOT_CURED`).
8. **State-machine legality** — the source state is in the transition's from-set (`ERR_INVALID_STATE`).
9. **Referential integrity of referenced entities** — approved permit, approved revision, qualified printer, pumpable batch, non-superseded revision (`ERR_PERMIT_NOT_APPROVED`, `ERR_PLAN_REVISION_NOT_APPROVED`, `ERR_PRINTER_NOT_QUALIFIED`, `ERR_BATCH_NOT_PUMPABLE`, `ERR_PERMIT_REVISION_SUPERSEDED`).
10. **Segregation of duties** (`ERR_SEGREGATION_OF_DUTIES`).
11. **Domain constraints** — schedule overlap, leveling tolerance, weather gating, batch pumpability (`ERR_PRINT_SCHEDULE_OVERLAP`, `ERR_LEVELING_OUT_OF_TOLERANCE`, `ERR_WEATHER_NOT_PERMISSIBLE`, `ERR_BATCH_NOT_PUMPABLE`).
12. **Fiscal gates** — permit fee settled before approval (`ERR_PERMIT_FEE_OUTSTANDING`).
13. **Interruption-cure ceilings** on resume (`ERR_INTERRUPTION_CURE_EXCEEDED`). On a resume attempt, the check of the job's own interruption against its cure window is evaluated before the priority-6 posture gate: once any interruption on the job is `OVERRUN` — and the `OVERRUN` flag is itself what drives the site's posture to `STOP` — the resume is rejected with `ERR_INTERRUPTION_CURE_EXCEEDED` rather than `ERR_POSTURE_BLOCKED`. The posture gate still applies on resume for a `STOP` posture arising from any other source.
14. **Request shape** — required fields present and well-formed (`ERR_INVALID_REQUEST`).

Lower-priority checks never mask higher-priority failures: a caller submitting with a missing role header will always see `ERR_UNAUTHENTICATED`, never `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Establishing the Jurisdiction and the Community Deployment

Before any site can be registered, a `PlatformAdmin` establishes the permitting authority by creating a `Jurisdiction`. The jurisdiction is described by a stable `code` (unique across the system, e.g. `AUS-TX-TRAVIS`), a human-readable `name`, a boolean `permits_prescriptive_printed_path` recording whether the jurisdiction's building code has a prescriptive path for printed wall systems, an integer `alternative_means_review_days` (at least 1) representing the SLA for alternative-means review, and a `weather_station_id` identifying the external weather station used for gating decisions. Every jurisdiction is created with `status` `ACTIVE`; the suspend/resume surface is not part of this API.

Community-scale deployments — a repeated plan printed across many sites — are modeled by `CommunityDeployment`, also created by a `PlatformAdmin` with a `name`, a `jurisdiction_id`, a `plan_id` referencing the repeated `StructuralPlan`, and a `planned_unit_count` of at least 2. A deployment begins in `PLANNING` with `completed_unit_count` zero and both `learning_curve_baseline_minutes` and `learning_curve_factor` null; its `learning_curve_variant` defaults to `FORWARD_LOOKING`. Activation by a `PlatformAdmin` moves the deployment to `ACTIVE` and requires that the referenced plan is in `APPROVED` status. The `learning_curve_variant` may be flipped between `FORWARD_LOOKING` and `CHRONOLOGICAL` by a `PlatformAdmin` via the variant-switching capability; doing so recomputes `learning_curve_factor` under the new variant.

### 3.2. Site Registration, Foundation, and Readiness

A `SiteManager` registers a `Site` by supplying the `jurisdiction_id` of its permitting authority, the street `address`, an optional `community_deployment_id` (null for a stand-alone site), the geotechnical `soil_class` (`A`, `B`, `C`, or `D`), and the `foundation_kind` (`SLAB`, `PIER_AND_BEAM`, or `FOOTING`). The server assigns the `id` and exposes the `site_id` parent linkage on every child collection under the site. A new site enters `REGISTERED` with `posture` `OPERATING`.

Pouring the foundation transitions the site from `REGISTERED` to `FOUNDATION_POURED`. The action stamps `foundation_poured_at` with the current logical clock and schedules `foundation_cured_at` at exactly seventy-two hours (the foundation-cure window) after the pour; it also increments the site's `version` by 1. Once the logical clock has reached `foundation_cured_at` — the comparison is inclusive — a `SiteManager` may confirm the cure, moving the site from `FOUNDATION_POURED` to `FOUNDATION_CURED` and recomputing the site's posture. Attempting to confirm before the cure window has elapsed is rejected with `ERR_FOUNDATION_NOT_CURED`.

The final readiness step is gated on printer qualification (see §3.4): the first `PrinterSetup` on the site to reach `QUALIFIED` cascades the site from `FOUNDATION_CURED` to `SITE_READY`. While any print job is `PRINTING` or `PAUSED`, the site is in `ACTIVE_PRINT`; when the only active print reaches `COMPLETED`, `ABORTED`, or `CANCELLED` and no other print is active, the site falls back to `SITE_READY`.

A `PlatformAdmin` may suspend a site from `REGISTERED`, `FOUNDATION_POURED`, `FOUNDATION_CURED`, or `SITE_READY`, provided no print job on the site is currently `PRINTING` or `PAUSED`. Suspension cascades: any print job still in `SCHEDULED` or `READY_TO_PRINT` moves to `CANCELLED`; any conventional trade task in `PLANNED` or `READY` moves to `CANCELLED`; and any permit application in `DRAFT`, `SUBMITTED`, or `AM_REVIEW` moves to `WITHDRAWN`. A site may also reach `COMPLETED` from `SITE_READY` — see §3.8.

### 3.3. Structural Plans and Engineering Revisions

An `Engineer` authors a `StructuralPlan` by supplying a `title`, a `structural_system` (`PRINTED_WALL`, `PRINTED_WALL_WITH_CONVENTIONAL_ROOF`, or `HYBRID`), the nominal `wall_thickness_mm` (at least 50), the nominal `wall_height_mm` (at least 2000), and the `plan_area_m2` (strictly positive). A new plan enters `DRAFT` with both `current_revision_id` and `approved_revision_id` null.

Engineering proceeds through `PlanRevision` records created under the plan. An `Engineer` opens a revision by supplying `engineering_notes`, a `required_code_path` (`PRESCRIPTIVE` or `ALTERNATIVE_MEANS`) chosen based on the jurisdiction's capabilities, and optionally a `supersedes_revision_id` naming the revision this one replaces. The server assigns `revision_number` as one plus the count of prior non-`VOIDED` revisions on the same plan, ordered chronologically by `created_at`. A new revision enters `DRAFT` with `engineer_reviewer_id` and `approval_reviewer_id` null.

Submitting a revision (`DRAFT` → `SUBMITTED`) records the submitter's `X-User-ID` in `engineer_reviewer_id` and, if the parent plan is currently `DRAFT`, flips the plan to `UNDER_REVIEW`. Only one revision per plan may be in `SUBMITTED` at a time; a second submission while another revision of the same plan is still `SUBMITTED` is rejected with `ERR_CONCURRENT_REVIEW`.

Deciding a submitted revision is also an `Engineer` action but is subject to segregation of duties: the decider's `X-User-ID` must differ from `engineer_reviewer_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval (`SUBMITTED` → `APPROVED`) stamps `approval_reviewer_id`, transitions the parent plan to `APPROVED`, sets both `approved_revision_id` and `current_revision_id` on the plan to the newly approved revision, and cascades any previously `APPROVED` revision on the same plan to `VOIDED`. That void, in turn, cascades any `PermitApplication` referencing the voided revision and still in `DRAFT` or `SUBMITTED` to `WITHDRAWN`; later submissions referencing the voided revision are rejected with `ERR_PERMIT_REVISION_SUPERSEDED`. Rejection (`SUBMITTED` → `REJECTED`) also stamps `approval_reviewer_id` and, if no other revision on the plan is `SUBMITTED` or `APPROVED`, returns the plan to `DRAFT`.

Plans whose approved revision is later displaced move from `APPROVED` to `SUPERSEDED` when a newer revision on the same plan is approved; the displaced revision itself goes to `VOIDED`. A plan in `SUPERSEDED` may return to `APPROVED` only if the revision that superseded it is itself voided by reviewer action and no other revision is `APPROVED`. A `PlatformAdmin` may archive a plan from `DRAFT` unconditionally, or from `APPROVED` provided no permit application referencing any revision of the plan is in `SUBMITTED` or `AM_REVIEW` and no print job referencing a revision of the plan is in `SCHEDULED`, `READY_TO_PRINT`, `PRINTING`, or `PAUSED`.

### 3.4. Mobilizing the Printer

A `PrintOperator` mobilizes a gantry printer by creating a `PrinterSetup` on a site, naming the `gantry_model` (`VULCAN_II`, `VULCAN_III`, or `PHOENIX`), the `rail_span_mm` (at least 5000), the `leveling_tolerance_mm` (strictly positive), and the `measured_level_deviation_mm` observed after leveling. Creating the setup requires the caller's `expected_site_version` to match the site's current `version` (see §2.8), and the creation itself increments the site's `version` by 1. The server derives `is_within_tolerance` — true when the measured deviation is at most the tolerance. A new setup enters `ASSEMBLED`.

Advancing a setup from `ASSEMBLED` to `LEVELED` requires the site's `status` to be one of `FOUNDATION_POURED`, `FOUNDATION_CURED`, or `SITE_READY`; the advance recomputes `is_within_tolerance` and increments the site's `version` by 1. Advancing further from `LEVELED` to `QUALIFIED` requires `is_within_tolerance` to be true (otherwise the request is rejected with `ERR_LEVELING_OUT_OF_TOLERANCE`) and the site's `status` to be `FOUNDATION_CURED` or `SITE_READY` (otherwise `ERR_FOUNDATION_NOT_CURED`). This qualification is what cascades the site from `FOUNDATION_CURED` to `SITE_READY`, making the site print-eligible.

A `PrintOperator` may demobilize a setup from `ASSEMBLED`, `LEVELED`, or `QUALIFIED`, moving it to `DEMOBILIZED`. Demobilizing a `QUALIFIED` setup is refused while any print job referencing it is in `SCHEDULED`, `READY_TO_PRINT`, `PRINTING`, or `PAUSED`.

### 3.5. Proportioning and Qualifying the Material Batch

The printable material is modeled by `MaterialBatch`. A `PrintOperator` proportions a batch with a `mix_code` (`LAVACRETE_A`, `LAVACRETE_B`, or `LAVACRETE_C`), a `water_cement_ratio` between 0.30 and 0.60 inclusive, a `target_slump_mm` of at least 50, the `measured_slump_mm` taken before pumping, and the observed `pump_consistency_kg_per_min` at the nozzle. A new batch enters `PROPORTIONED`.

The server derives three fields on the batch. `slump_within_band` is true when the absolute difference between measured and target slump is at most 15 mm (the comparison is inclusive). `pump_window_kg_per_min` is the permitted flow range derived from the `mix_code`: for `LAVACRETE_A` the window is 40 to 60 kg/min, for `LAVACRETE_B` it is 55 to 75 kg/min, and for `LAVACRETE_C` it is 30 to 50 kg/min; both endpoints are inclusive. `is_pumpable` is true only when both `slump_within_band` is true and the observed pump consistency falls within the pump window.

Qualifying a batch (`PROPORTIONED` → `QUALIFIED`) requires `is_pumpable` to be true — a non-pumpable batch is rejected with `ERR_BATCH_NOT_PUMPABLE` — and the site's `status` to be one of `FOUNDATION_CURED`, `SITE_READY`, or `ACTIVE_PRINT`. A batch in either `PROPORTIONED` or `QUALIFIED` may be rejected by a `PrintOperator`; rejecting a `QUALIFIED` batch is refused while a print job in `PRINTING` or `PAUSED` is consuming it. When the print job that consumed a `QUALIFIED` batch reaches `COMPLETED` or `ABORTED`, the batch transitions to `EXHAUSTED`.

### 3.6. Weather Observations and Print Permissibility

Both `PrintOperator` and `QualityInspector` may post a `WeatherObservation` on a site, supplying the `observed_at` UTC timestamp, `air_temp_c`, `relative_humidity_pct` (0 through 100), `wind_speed_mps`, and `precipitation_mm` (non-negative). The server derives `is_print_permissible`, true only when all four predicates hold: the air temperature is at least 4 °C and at most 38 °C; the relative humidity is at most 90 percent; the wind speed is at most 12 m/s; and the precipitation is exactly zero. Posting an observation recomputes the site's posture under the rules of §2.10. The "latest" observation for gating purposes is the one with the newest `observed_at`, with ties broken by earliest `created_at`. An observation remains valid for gating for 30 minutes after its `observed_at`, inclusive — the validity window is point-in-time with a trailing lookback, which is intentionally different from the half-open interval semantics used for schedule overlap in §3.7.

### 3.7. Scheduling, Running, and Interrupting a Print Job

A `PrintOperator` schedules a `PrintJob` on a site by naming the `plan_revision_id` to print (which must be the revision covered by the site's approved permit application at schedule time), the `printer_setup_id` of a `QUALIFIED` setup, the `scheduled_start_at` and `scheduled_end_at`, and the upstream-computed `total_layers_planned` (at least 1). The create requires the caller's `expected_site_version` to match the site's current `version`; the create itself increments the site's `version` by 1, initializes `layers_printed` and `cumulative_interruption_minutes` to zero, and stamps the job `SCHEDULED` with posture `READY`.

Moving the job from `SCHEDULED` to `READY_TO_PRINT` is the system's main gating checkpoint, and its checks are evaluated under the ordering rules of §2.11:

- The site's permit application covering `plan_revision_id` must be `APPROVED`; otherwise the transition is rejected with `ERR_PERMIT_NOT_APPROVED`. A permit referencing a superseded (voided) revision surfaces `ERR_PERMIT_REVISION_SUPERSEDED`, and a revision not in `APPROVED` status surfaces `ERR_PLAN_REVISION_NOT_APPROVED`.
- The referenced `PrinterSetup` must be `QUALIFIED`; otherwise `ERR_PRINTER_NOT_QUALIFIED`.
- A `MaterialBatch` on the site must exist in `QUALIFIED` status with `is_pumpable` true; otherwise `ERR_BATCH_NOT_PUMPABLE`.
- The latest `WeatherObservation` (newest by `observed_at`, ties broken by earliest `created_at`) must have `is_print_permissible` true and must have been observed within the last 30 minutes of the current logical clock; otherwise `ERR_WEATHER_NOT_PERMISSIBLE`.
- The scheduled start must be at or after the current logical clock, and the scheduled end strictly after the start.
- The job's half-open scheduled interval must not overlap any other print job on the same site in `SCHEDULED`, `READY_TO_PRINT`, `PRINTING`, or `PAUSED`. Two intervals overlap when each one's start is strictly before the other's end; an incoming start equal to an existing job's end is adjacent, not overlapping, and is permitted. Violations are rejected with `ERR_PRINT_SCHEDULE_OVERLAP`.

Starting the job (`READY_TO_PRINT` → `PRINTING`) requires the logical clock to be at or past `scheduled_start_at`, the site's posture to be anything other than `STOP`, and the latest weather observation to remain print-permissible. The start stamps `actual_start_at` with the current logical clock and cascades the site from `SITE_READY` to `ACTIVE_PRINT`.

Pausing is driven by the job's `transition` capability with `to_state` set to `PAUSED`. It requires a `cause` — one of `WEATHER`, `MATERIAL`, `MECHANICAL`, `OPERATOR`, or `INSPECTOR_HOLD`. Pausing creates an `OPEN` `PrintInterruption` parented under the job via its `print_job_id` back-reference, stamps `paused_at` at the current logical clock, transitions the job to `PAUSED`, and — when the cause is `WEATHER` — recomputes the site's posture. The interruption's `max_permissible_interruption_minutes` is read from the `mix_code` of the batch being consumed at pause time: 30 minutes for `LAVACRETE_A`, 20 minutes for `LAVACRETE_B`, and 45 minutes for `LAVACRETE_C`. If the logical clock advances so that the elapsed time since `paused_at` exceeds that bound while the job is still `PAUSED`, the interruption is auto-flagged `OVERRUN` on the next read or write that touches it, the parent job's posture becomes `BLOCKED`, and any subsequent resume attempt is rejected with `ERR_INTERRUPTION_CURE_EXCEEDED` — at which point aborting is the correct recovery.

Resuming a paused job (`PAUSED` → `PRINTING`) requires the open interruption's duration to be at most its `max_permissible_interruption_minutes`, the latest weather observation to be print-permissible and still within its 30-minute validity window (§3.6) relative to the current logical clock, and — when the cause was `MATERIAL` — a fresh `QUALIFIED` batch to exist on the site. A successful resume closes the interruption (`OPEN` → `CLOSED`), stamps `resumed_at`, computes `duration_minutes` as the whole-minute difference between resume and pause, and computes `cure_penalty_layers`. The penalty applies only when the cause is `WEATHER` or `MATERIAL`: it is the duration divided into 10-minute chunks, rounded up — a duration of exactly 10 minutes yields a penalty of 1, and a duration of zero yields 0. For the other three causes (`MECHANICAL`, `OPERATOR`, `INSPECTOR_HOLD`) the penalty is always zero. Closing an interruption also recomputes the job's `cumulative_interruption_minutes` as the sum of `duration_minutes` over all `CLOSED` interruptions on the job; if that cumulative figure exceeds 60 minutes (the hard cap), the job auto-transitions to `ABORTED`.

A `PrintOperator` may abort a job from either `PRINTING` or `PAUSED`. Aborting closes any open interruption with `resumed_at` set to the current logical clock, transitions the consumed batch from `QUALIFIED` to `EXHAUSTED`, and recomputes the site's status (dropping from `ACTIVE_PRINT` back to `SITE_READY` when no other print is active). Cancellation is also available from `SCHEDULED` or `READY_TO_PRINT` and moves the job to `CANCELLED`.

Completing a print (`PRINTING` → `COMPLETED`) requires `layers_printed` to be at least `total_layers_planned`, every `LayerInspection` on the job to have a `disposition` other than `PENDING`, and no `LayerInspection` on the job to have `disposition` `DEMOLISH_REQUIRED`; any shortfall is rejected with `ERR_PRINT_INCOMPLETE`. Completion stamps `actual_end_at`, computes `continuous_run_minutes` as the elapsed time between `actual_start_at` and `actual_end_at` minus `cumulative_interruption_minutes`, exhausts the consumed batch, recomputes the site's status, and — if the site belongs to a community deployment — triggers the learning-curve recomputation described in §3.9.

### 3.8. Layer Inspections and Quality Disposition

A `QualityInspector` records a `LayerInspection` against a print job by supplying the 1-indexed `layer_index_start` (at least 1) and `layer_index_end` (at least the start) bounding the inspected band, the measured `bond_strength_mpa`, and the maximum `dimensional_deviation_mm` within the band; an optional `supersedes_inspection_id` links a re-inspection to the earlier inspection it replaces. The server derives `passes_bond` (true when bond strength is at least 1.5 MPa, inclusive), `passes_dimensional` (true when the dimensional deviation is at most 6 mm, inclusive), and a four-valued `outcome`: `PASS` when both pass, `FAIL_BOND` when only bond fails, `FAIL_DIMENSIONAL` when only dimensional fails, and `FAIL_BOTH` when both fail. A new inspection enters with `disposition` `PENDING`, and the parent job's `layers_printed` is incremented by the band's layer count (end minus start plus one) only when the outcome is `PASS` and the inspection is not a re-inspection.

Dispositions are applied by a `QualityInspector`, subject to segregation of duties: an inspector may not disposition an inspection they themselves recorded, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. From `PENDING`, an inspection may be moved to `ACCEPTED` only when its outcome is `PASS` — any other outcome is rejected with `ERR_INSPECTION_NOT_PASSING`. It may be moved to `REPAIR_REQUIRED` whenever the outcome is not `PASS`, which recomputes the site's posture (a `REPAIR_REQUIRED` inspection contributes to `PRECAUTIONARY`). It may be moved to `DEMOLISH_REQUIRED` only when the outcome is exactly `FAIL_BOTH`; that disposition forces the site's posture to `STOP` and blocks the parent print job from completing.

Repairs are verified by re-inspection: recording a new inspection whose `supersedes_inspection_id` points to a `REPAIR_REQUIRED` inspection and whose layer range overlaps the earlier range leaves the old inspection at `REPAIR_REQUIRED` while the new one enters `PENDING`. This is the only path by which repair work is re-evaluated, and the site's posture is recomputed each time.

### 3.9. Community-Scale Learning Curve

A deployment's learning curve is tracked in three computed fields on `CommunityDeployment`. `completed_unit_count` is the number of sites in the deployment that have reached `COMPLETED`. `learning_curve_baseline_minutes` is the median of `continuous_run_minutes` over the first 3 completed units of the deployment — the baseline window — processed in chronological order of each site's `foundation_poured_at` with ties broken by earliest `created_at`; it is null until at least 3 units have completed, and once computed it is frozen. `learning_curve_factor` is the ratio of the rolling average to the baseline, rounded half-up to 4 decimal places; it too is null until the baseline exists. A factor below 1 indicates the deployment is printing faster than baseline (learning); a factor above 1 indicates regression.

The rolling average covers the last 3 completed units (the rolling window), and its composition depends on `learning_curve_variant`. Under `FORWARD_LOOKING`, jobs currently `PRINTING` are also mixed into the rolling average at their forward-looking estimate; under `CHRONOLOGICAL`, only completed jobs contribute, using their actual `continuous_run_minutes`.

The forward-looking estimate for an in-flight or completed job is its plan-estimated print time: `total_layers_planned` multiplied by 8 minutes per layer (the rated print rate), rounded up to a whole minute. The corresponding utilization metric also has two variants, both rounded half-up to 4 decimal places and capped at 1.0: the forward-looking utilization divides the estimated minutes by the scheduled window (`scheduled_end_at` minus `scheduled_start_at`, in minutes, with a divisor of at least 1), and the chronological utilization divides `continuous_run_minutes` by the actual window (`actual_end_at` minus `actual_start_at`, in minutes, with a divisor of at least 1). Which variant the deployment reports is selected by `learning_curve_variant` at completion time. Completing a site (see §3.10) increments the deployment's `completed_unit_count` and, when the count reaches the baseline window of 3, computes and freezes `learning_curve_baseline_minutes`; every completion recomputes `learning_curve_factor`.

### 3.10. Permits, Fees, and Conventional Trades

A `PermitCoordinator` opens a `PermitApplication` on a site by naming the `plan_revision_id` under review and the `requested_path` (`PRESCRIPTIVE` or `ALTERNATIVE_MEANS`). A new application enters `DRAFT` with `review_round` zero and `fee_paid_cents` zero; `granted_path`, `am_submitted_at`, and `am_decision_due_at` are null.

Submitting the application (`DRAFT` → `SUBMITTED` or `AM_REVIEW`) is invoked by sending `action` set to `SUBMIT` through the application's action capability. It requires the referenced revision to be `APPROVED` (a voided or never-approved revision surfaces `ERR_PERMIT_REVISION_SUPERSEDED` or `ERR_PLAN_REVISION_NOT_APPROVED` respectively) and the site's jurisdiction to be `ACTIVE`. Routing depends on the requested path and the jurisdiction's posture: if `requested_path` is `PRESCRIPTIVE` and the jurisdiction's `permits_prescriptive_printed_path` is true, the application lands in `SUBMITTED`; if the jurisdiction does not permit a prescriptive printed path, the server reroutes the application to `AM_REVIEW` with `granted_path` still null. A request with `requested_path` `ALTERNATIVE_MEANS` goes to `AM_REVIEW` directly. Submission computes `fee_due_cents` (below) and, for the alternative-means route, stamps `am_submitted_at` with the current logical clock and derives `am_decision_due_at` as `am_submitted_at` plus the jurisdiction's `alternative_means_review_days`.

The permit fee is tiered. The base is 250000 cents; an area component adds the floor of the plan's `plan_area_m2` (the floor is taken before any multiplication) times 4500 cents per square meter; and an alternative-means surcharge of 175000 cents applies when the application is routed to `ALTERNATIVE_MEANS` (the surcharge is zero on the prescriptive path). On a first submission the sum is the fee. On resubmission, the entire sum — including the surcharge — is multiplied by one plus 0.10 times `review_round`, and the result is rounded half-up to zero decimal places. Fee payment is recorded by the `PermitCoordinator` posting an `amount_cents`, which increments `fee_paid_cents`; fees already paid are non-refundable on withdrawal.

A `JurisdictionReviewer` decides a `SUBMITTED` or `AM_REVIEW` application by posting `action` `DECIDE` with a `decision` of `APPROVE` or `DENY`. Approving requires `fee_paid_cents` to be at least `fee_due_cents`, otherwise the decision is rejected with `ERR_PERMIT_FEE_OUTSTANDING`; approving from `AM_REVIEW` additionally requires the logical clock to be at or before `am_decision_due_at`, otherwise `ERR_AM_REVIEW_EXPIRED`. Approval stamps `granted_path` with `PRESCRIPTIVE` or `ALTERNATIVE_MEANS` according to the route taken. Denial moves the application to `DENIED` from either status. If the logical clock passes `am_decision_due_at` without a decision, the application auto-transitions from `AM_REVIEW` to `RESUBMIT_REQUIRED` on the first read or write that touches it. The expired deadline remains operative after that auto-transition: because the temporal gate (§2.11 item 7) outranks state-machine legality (item 8), a subsequent `DECIDE` with `decision` `APPROVE` on an application that reached `RESUBMIT_REQUIRED` by expiry of its alternative-means deadline is rejected with `ERR_AM_REVIEW_EXPIRED`, while a `DECIDE` with `decision` `DENY` on the same application is rejected with `ERR_INVALID_STATE`. A `PermitCoordinator` may then resubmit, which is allowed only while `review_round` is below the maximum of 3 alternative-means review rounds; resubmission increments `review_round` by 1, recomputes `fee_due_cents` under the resubmission multiplier, and re-stamps `am_submitted_at` and `am_decision_due_at`. Withdrawal is available from `DRAFT`, `SUBMITTED`, or `AM_REVIEW` and is final.

With a permit `APPROVED`, printing can proceed; once printing is complete, conventional trades follow. A `SiteManager` plans a `ConventionalTradeTask` by naming the `trade` (`ROOF`, `ELECTRICAL`, `PLUMBING`, or `MECHANICAL`), the `sequence_rank` (at least 1, lower runs first), the `earliest_start_at` and `latest_end_at`, the `depends_on_print_job_id` the trade follows, and optionally a `depends_on_trade_task_id` forming a self-referential chain. The create requires `expected_site_version` to match (see §2.8) and itself increments the site's `version` by 1. A new task enters `PLANNED` with `is_startable` and `start_blockers` computed.

`is_startable` is true only when the depended-upon print job is `COMPLETED`, every `FAIL_BOND`, `FAIL_DIMENSIONAL`, or `FAIL_BOTH` inspection on that job has a `disposition` other than `PENDING`, the prior trade task (if any) is `COMPLETED`, and the logical clock is at or past `earliest_start_at`. The corresponding `start_blockers` list names each unmet condition from the enum `PRINT_INCOMPLETE`, `INSPECTION_PENDING`, `PRIOR_TRADE_INCOMPLETE`, `TOO_EARLY`, and `SITE_STOPPED`. A task transitions from `PLANNED` to `READY` automatically the moment its work-dependency conditions — the depended-upon print job being `COMPLETED` with no failing-outcome inspection left `PENDING`, and the prior trade task (if any) being `COMPLETED` — are satisfied, re-evaluated on every dependency change; a logical-clock advance counts as a dependency change and triggers this re-evaluation. The temporal (`TOO_EARLY`) and posture (`SITE_STOPPED`) conditions do not hold a task in `PLANNED`: a task may reach `READY` while `TOO_EARLY` or `SITE_STOPPED` is still listed in `start_blockers`, in which case starting it is still rejected by the corresponding temporal or posture gate.

Starting work (`READY` → `IN_PROGRESS`) is a `TradeContractor` action requiring the logical clock to be at or past `earliest_start_at` (a too-early start is rejected with `ERR_TRADE_TOO_EARLY`), the site's posture to be anything other than `STOP` (otherwise `ERR_POSTURE_BLOCKED`), and `is_startable` to be true; it stamps `actual_start_at`. Completing (`IN_PROGRESS` → `COMPLETED`) requires the logical clock to be at or before `latest_end_at` (a late completion is rejected with `ERR_TRADE_OVERRUN`), stamps `actual_end_at`, and cascades any downstream task whose `depends_on_trade_task_id` names this task from `PLANNED` to `READY`. A `SiteManager` may cancel a task from `PLANNED` or `READY`; cancelling a `PLANNED` task leaves downstream tasks that depend on it permanently blocked in `PLANNED`.

The site itself reaches `COMPLETED` from `SITE_READY` when every print job on the site is `COMPLETED`, every conventional trade task on the site is `COMPLETED`, and no layer inspection on the site's print jobs has `disposition` `PENDING` or `REPAIR_REQUIRED`. If the site belongs to a community deployment, completion increments the deployment's `completed_unit_count` by 1, freezes `learning_curve_baseline_minutes` when the count first reaches the baseline window of 3, and recomputes `learning_curve_factor`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The clock endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/construction/_clock/set_current_utc` | Advance the logical clock; triggers deferred system evaluations | PlatformAdmin |
| POST | `/construction/jurisdictions` | Create a jurisdiction | PlatformAdmin |
| GET | `/construction/jurisdictions/{id}/sites` | List sites under a jurisdiction | PlatformAdmin, SiteManager, PermitCoordinator, JurisdictionReviewer |
| POST | `/construction/community-deployments` | Create a community deployment | PlatformAdmin |
| GET | `/construction/community-deployments/{id}` | Fetch deployment with learning-curve state | PlatformAdmin, SiteManager, Engineer |
| POST | `/construction/community-deployments/{id}/activate` | Activate a PLANNING deployment | PlatformAdmin |
| POST | `/construction/community-deployments/{id}/set-learning-variant` | Switch learning_curve_variant | PlatformAdmin |
| POST | `/construction/sites` | Register a site | SiteManager |
| GET | `/construction/sites/{id}` | Fetch a site (lazy system transitions evaluated) | PlatformAdmin, SiteManager, PermitCoordinator, JurisdictionReviewer, Engineer, PrintOperator, QualityInspector, TradeContractor |
| GET | `/construction/sites/{id}/permit-applications` | List permit applications for a site | PlatformAdmin, SiteManager, PermitCoordinator, JurisdictionReviewer |
| GET | `/construction/sites/{id}/print-jobs` | List print jobs for a site | PlatformAdmin, SiteManager, PrintOperator, QualityInspector, TradeContractor |
| GET | `/construction/sites/{id}/printer-setups` | List printer setups for a site | PlatformAdmin, SiteManager, PrintOperator |
| GET | `/construction/sites/{id}/material-batches` | List material batches for a site | PlatformAdmin, SiteManager, PrintOperator |
| GET | `/construction/sites/{id}/weather-observations` | List weather observations, newest first | PlatformAdmin, SiteManager, PrintOperator, QualityInspector |
| GET | `/construction/sites/{id}/trade-tasks` | List conventional trade tasks for a site | PlatformAdmin, SiteManager, TradeContractor, QualityInspector |
| POST | `/construction/structural-plans` | Create a structural plan | Engineer |
| GET | `/construction/structural-plans/{id}/revisions` | List revisions for a plan | PlatformAdmin, SiteManager, PermitCoordinator, Engineer |
| POST | `/construction/structural-plans/{id}/revisions` | Create a new revision on a plan | Engineer |
| POST | `/construction/structural-plans/{id}/revisions/{revision_id}/action` | Plan revision action (SUBMIT / APPROVE / REJECT) | Engineer |
| POST | `/construction/sites/{id}/permit-applications` | Open a permit application | PermitCoordinator |
| GET | `/construction/sites/{id}/permit-applications/{application_id}` | Fetch a permit application | PlatformAdmin, SiteManager, PermitCoordinator, JurisdictionReviewer |
| POST | `/construction/sites/{id}/permit-applications/{application_id}/action` | Permit application action (SUBMIT / PAY_FEE / DECIDE / RESUBMIT / WITHDRAW) | PermitCoordinator, JurisdictionReviewer |
| POST | `/construction/sites/{id}/printer-setups` | Create a printer setup for a site | PrintOperator |
| POST | `/construction/sites/{id}/printer-setups/{setup_id}/advance` | Advance a printer setup (to_state=LEVELED or QUALIFIED) | PrintOperator |
| POST | `/construction/sites/{id}/material-batches` | Proportion a new material batch | PrintOperator |
| POST | `/construction/sites/{id}/material-batches/{batch_id}/qualify` | Qualify a batch | PrintOperator |
| POST | `/construction/sites/{id}/weather-observations` | Post a weather observation | PrintOperator, QualityInspector |
| POST | `/construction/sites/{id}/action` | Site lifecycle action (POUR_FOUNDATION / CONFIRM_CURE / COMPLETE / SUSPEND) | SiteManager, PlatformAdmin |
| POST | `/construction/sites/{id}/print-jobs` | Schedule a print job | PrintOperator |
| POST | `/construction/sites/{id}/print-jobs/{job_id}/transition` | PrintJob state transition | PrintOperator |
| POST | `/construction/sites/{id}/print-jobs/{job_id}/layer-inspections` | Record a layer inspection | QualityInspector |
| GET | `/construction/sites/{id}/print-jobs/{job_id}/layer-inspections` | List layer inspections on a job | PlatformAdmin, SiteManager, PrintOperator, QualityInspector |
| POST | `/construction/sites/{id}/print-jobs/{job_id}/layer-inspections/{inspection_id}/disposition` | Disposition a PENDING inspection | QualityInspector |
| POST | `/construction/sites/{id}/trade-tasks` | Plan a conventional trade task | SiteManager |
| POST | `/construction/sites/{id}/trade-tasks/{task_id}/transition` | ConventionalTradeTask state transition | TradeContractor, SiteManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_MISSING_IDEMPOTENCY_KEY` | 400 |
| `ERR_IDEMPOTENCY_REPLAY_MISMATCH` | 409 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_POSTURE_BLOCKED` | 409 |
| `ERR_FOUNDATION_NOT_CURED` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_PERMIT_FEE_OUTSTANDING` | 409 |
| `ERR_PERMIT_REVISION_SUPERSEDED` | 409 |
| `ERR_AM_REVIEW_EXPIRED` | 409 |
| `ERR_PLAN_REVISION_NOT_APPROVED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONCURRENT_REVIEW` | 409 |
| `ERR_LEVELING_OUT_OF_TOLERANCE` | 409 |
| `ERR_PRINTER_NOT_QUALIFIED` | 409 |
| `ERR_BATCH_NOT_PUMPABLE` | 409 |
| `ERR_WEATHER_NOT_PERMISSIBLE` | 409 |
| `ERR_PRINT_SCHEDULE_OVERLAP` | 409 |
| `ERR_INTERRUPTION_CURE_EXCEEDED` | 409 |
| `ERR_PRINT_INCOMPLETE` | 409 |
| `ERR_INSPECTION_NOT_PASSING` | 409 |
| `ERR_TRADE_TOO_EARLY` | 409 |
| `ERR_TRADE_OVERRUN` | 409 |
