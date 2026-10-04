# Private Wireless Deployment API — Product Requirements Document

## 1. Introduction

Enterprises operating campuses, factories, venues, logistics yards, and energy facilities increasingly demand wireless infrastructure they own and control — not shared public macro networks whose capacity, latency, and security posture they cannot shape. Delivering such a private wireless network is, however, a deeply regulated and operationally unforgiving undertaking: spectrum must be selected across licensed, shared, and unlicensed bands; shared-band usage must be coordinated and registered with an external Spectrum Access System; radio coverage must be engineered against measured building attenuation; capacity must be proven against a contractual target before a single radio goes on air; and once live, the network carries service-level obligations whose breaches generate monetary credits.

This document specifies the Private Wireless Deployment API, mounted under `/private-wireless`, a Verizon Business service platform that orchestrates that entire lifecycle. It models the full chain from enterprise onboarding, through site survey and RF coverage design, through spectrum leasing and regulator-coordinated authorization, through cell-sector turn-up and device/SIM provisioning, to network slicing, service contracts, SLA monitoring, and coverage remediation after operational feedback. Every stage is a first-class, stateful resource with its own lifecycle, and the transitions between stages are gated by segregation of duties: the field technician who surveys a site may not approve that survey; the spectrum coordinator who files a coordination request may not approve it — only the regulator may.

The API is deliberately strict about the points where money, spectrum, and safety intersect. Spectrum is a finite, leased resource whose per-cell consumption is tracked against lease bandwidth in real time; interference margins are computed against live neighbor cells before any coordination request can be approved; and contractual outage budgets are evaluated on a logical clock, with SLA credits applied automatically when breach thresholds are crossed. The following sections define the global API contract, the business workflows that bind the resources together, the endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which that operator acts. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, with these exact spellings:

- `NetworkArchitect` — the Verizon enterprise solutions architect; owns the Enterprise, Site, NetworkSlice, and ServiceContract lifecycles, approves coverage designs and remediations, and drives the test clock.
- `RFEngineer` — the radio-frequency design engineer; approves or rejects site surveys, authors coverage designs and cell-sector plans, and proposes and starts coverage remediations.
- `SpectrumCoordinator` — the spectrum planning specialist; files coordination requests, manages spectrum leases, and creates spectrum assignments.
- `SpectrumRegulator` — the external regulator (an FCC/SAS administrator proxy); approves or rejects coordination requests and may read spectrum leases, contracts, and coordination requests.
- `FieldTechnician` — the on-site field engineer; performs surveys, configures and turns up cells, creates SIM profiles, provisions devices, manages slice bindings, raises and works monitoring alerts, and verifies remediations.

For all five roles — `NetworkArchitect`, `RFEngineer`, `SpectrumCoordinator`, `SpectrumRegulator`, and `FieldTechnician` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, a coordination request records the filing operator in its `requesting_coordinator_id` field, and a survey records the surveying operator in `surveyor_id`) but does not compare it to any entity's `id` for ownership resolution. Where a workflow ties an action to the same operator (for example, only the filing coordinator may withdraw a request), the comparison is between `X-User-ID` and that recorded field, not against a user table.

Segregation of duties is enforced as a first-class rule: the operator who submitted a SiteSurvey may not approve it, and the operator who submitted a SpectrumCoordinationRequest may not approve it. Attempting either self-approval is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403).
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
- A request to a path the API does not define, or a method not supported on a defined path, is rejected as `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. Results are always returned sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional results exist beyond the returned window.

### 2.4. Common Resource Properties

Every resource in the system carries an `id` field: a server-minted UUID with no type prefix of any kind. Most resources additionally carry `created_at` and `updated_at` timestamps — ISO 8601 UTC with three fractional digits — and a `version` field, an integer starting at 1 that increments by exactly 1 on every mutation of the resource. Two resources are deliberately lighter-weight: SliceBinding and MonitoringAlert carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and any request or expectation of those fields on those two resources is meaningless.

Mutations that touch a parent resource as a documented side effect also increment the parent's `version` and refresh its `updated_at`. For example, approving a site survey moves the parent Site from `PLANNED` to `SURVEYED` and bumps the Site's `version` by 1; creating a coverage design against a Site likewise increments the Site's `version`.

### 2.5. The Logical Clock

The server maintains a logical clock, initialized to 2026-09-01T00:00:00Z before any explicit set, and MUST NOT consult wall-clock time for any business decision. A `NetworkArchitect` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; doing so returns 200 with a data object `{"current_utc": <new logical time>}` and re-evaluates every time-derived rule in the system — spectrum lease expirations, contract breach detection against the current calendar month, remediation windows, and renewal eligibility all respond to the new logical time. All timestamps recorded by the system (`raised_at_utc`, `bound_at_utc`, `resolved_at_utc`, `provisioned_at_utc`, `in_progress_started_at_utc`) are stamped from this logical clock.

### 2.6. Nested Resource Retrieval and Path Validation

Resources form a containment hierarchy: an Enterprise owns Sites, SpectrumLeases, SIMProfiles, and ServiceContracts; a Site owns SiteSurveys, CoverageDesigns, CellSectors, SpectrumCoordinationRequests, NetworkSlices, MonitoringAlerts, and CoverageRemediations; a CellSector owns Devices and SpectrumAssignments; a NetworkSlice owns SliceBindings. When a request path traverses this hierarchy, each path parameter is validated left to right — enterprise first, then site, then the survey/design/contract/request-level resource, then cell, then device — and every segment must reference an existing resource that is actually a child of the resource named by the preceding segment. A failure at any segment is rejected with `ERR_NOT_FOUND` (HTTP 404). Separately, body-supplied foreign-key references — `based_on_survey_id`, `spectrum_lease_id`, `coordination_request_id`, `sim_profile_id`, `supersedes_remediation_id`, and `triggered_by_alert_id` — must each reference an existing resource; a dangling reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control. Both take a mandatory expected-version field, and a mismatch is always a stale-version rejection — the client read the parent at one version, another writer advanced it in the meantime, and the server refuses to let the client overwrite state it never observed.

First, creating a coverage design against a Site requires the request to carry `expected_site_version` equal to the Site's current `version`. This captures the case where a newer site survey was just approved — bumping the Site's `version` — so the client drafting a design on the old survey baseline is working from stale ground. A mismatch is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412).

Second, approving a spectrum coordination request requires the request to carry `expected_request_version` equal to the SpectrumCoordinationRequest's current `version`. This captures the case where the coordinator re-submitted or otherwise modified the request after the regulator's review snapshot. A mismatch is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412).

No other endpoint takes an expected-version field; concurrency enforcement is confined to these two write paths.

### 2.8. Precision, Rounding, and Units

Capacity figures (`predicted_capacity_mbps`, `final_capacity_mbps`, `capacity_shortfall_mbps`, `guaranteed_bandwidth_mbps`, `target_capacity_mbps`) are integer megabits per second. The per-cell capacity contribution in the design calculations is rounded half-up to a whole number of Mbps before any summation across cells — never rounded after summation. Spectrum quantities (`bandwidth_mhz`, `requested_bandwidth_mhz`, `assigned_bandwidth_mhz`, `spectrum_utilization_mhz`) are integer megahertz. Monetary quantities (`monthly_cost_cents`, `sla_credit_balance_cents`, `sla_credit_applied_cents`) are integer cents, with each SLA credit event rounded half-up to a whole cent before monthly aggregation. Interference margins in the coordination `interference_report` are expressed in decibels with one decimal place. Antenna azimuth is an integer number of degrees from 0 through 359 inclusive.
### 2.9. Validation Order and Shared Rejection Semantics

When a request would trip several rules at once, the checks are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication comes first: a request without valid `X-User-ID` and `X-User-Role` headers fails as `ERR_UNAUTHENTICATED` before anything else is examined, and a recognized role without permission for the endpoint fails as `ERR_UNAUTHORIZED` next. Only then does existence checking run — path resources left to right as `ERR_NOT_FOUND`, then body foreign-key references as `ERR_REFERENCE_NOT_FOUND`. The operator-ownership restrictions on workflow transitions (only the surveying technician may submit their survey; only the filing coordinator may submit or withdraw their coordination request) are authorization failures and surface as `ERR_UNAUTHORIZED` (HTTP 403), evaluated after the state and terminality checks below. The segregation-of-duties bar on self-approval, although itself an authorization rule, is likewise evaluated after the state and terminality checks on the approval endpoints. State checks follow: requesting a transition the resource's current state does not allow yields `ERR_INVALID_STATE` (HTTP 409), and attempting to mutate a resource already in a terminal state — `DECOMMISSIONED`, `RETIRED`, `TERMINATED`, `RESOLVED`, `REGISTERED`, `REJECTED`, `WITHDRAWN`, `COMPLETED`, `FALSE_ALARM`, `OFFBOARDED`, `CANCELLED`, `EXPIRED`, and the like — yields `ERR_ALREADY_TERMINAL` (HTTP 409). Business-safety checks (interference margin, survey signal strength, URLLC edge placement, PAL spectrum overlap) come next, then temporal rules (time-window validity, lease coverage, assignment overlap, contract overlap), then business constraints (uniqueness, capacity shortfall, slice bandwidth and device caps, remediation cell counts, open-remediation guards), then referential constraints (cross-enterprise SIM binding, child resources still active at decommission or offboard), then fiscal constraints (lease bandwidth, minimum target capacity), and finally the optimistic-concurrency stale-version checks. Within this ordering, a more specific rule always masks a less specific one: for example, a coordination-request approval that would fail both the interference check and the stale-version check surfaces `ERR_INTERFERENCE_MARGIN_EXCEEDED`, because business-safety rules are evaluated before concurrency rules.

Malformed requests — a required field missing, an enum value outside its defined set, or a numeric outside its documented range — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Shape-level validation of a time window — that its end is strictly later than its start, per §2.11 — is likewise request-shape validation and is evaluated at request-parse time, before the business-rule ordering above; a request carrying a malformed window therefore surfaces `ERR_INVALID_TIME_WINDOW` ahead of any business-safety check such as PAL spectrum overlap. Every state-transition request on a resource whose current state does not permit that transition is `ERR_INVALID_STATE`; the same operation on an already-terminal resource is `ERR_ALREADY_TERMINAL`, and the terminal-state check is the one that surfaces when both could apply to a terminal resource.

Terminality also propagates to the containment hierarchy on write paths. Every site-scoped write endpoint — creating or transitioning a child resource under a Site, including surveys, designs, cells, coordination requests, alerts, remediations, and slices — is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) when the parent Site is `DECOMMISSIONED`. Likewise, creating a Site under an Enterprise that is `OFFBOARDED` is rejected with `ERR_ALREADY_TERMINAL`.

### 2.10. Uniqueness Rules

Several identifiers must be unique, each at a defined scope. Within an Enterprise, a Site's `site_code` is unique, and a NetworkSlice's `slice_name` is unique within its Site, as is a CellSector's `sector_label`. Globally — across all enterprises and sites — a Device's `serial_number` and `imei`, a SIMProfile's `iccid`, a ServiceContract's `contract_code`, and an Enterprise's `erp_account_code` are each unique. A creation request colliding with any of these is rejected with `ERR_DUPLICATE_IDENTIFIER` (HTTP 409).

### 2.11. Time Windows

Every time window in the system is half-open: the start instant is inclusive and the end instant is exclusive. This applies to a SpectrumLease's `lease_start_utc`/`lease_end_utc`, a SpectrumCoordinationRequest's `requested_start_utc`/`requested_end_utc`, a SpectrumAssignment's `assignment_start_utc`/`assignment_end_utc`, and a ServiceContract's `contract_start_utc`/`contract_end_utc`. In every case the end must be strictly later than the start; a window whose end equals or precedes its start is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400). Overlap between two half-open windows means they share at least one instant — two windows that merely touch at a boundary (one ends exactly when the other begins) do not overlap.
## 3. Business Logic & Workflows

### 3.1. Onboarding an Enterprise and Registering Its Sites

A `NetworkArchitect` begins by creating an Enterprise with its `legal_name`, an externally meaningful `erp_account_code` used as the billing reference (unique across all Enterprises), and an `industry_vertical` drawn from `CAMPUS`, `FACTORY`, `VENUE`, `LOGISTICS`, or `ENERGY`. An optional `security_posture` may be supplied as `STANDARD`, `ELEVATED`, or `CRITICAL`; when omitted it defaults to `STANDARD`, and the posture gates identity and slicing defaults downstream. The new Enterprise enters `ONBOARDING` with `sla_credit_balance_cents` and `active_site_count` both starting at 0.

Sites are registered under the Enterprise by the same role. Each Site carries a human `site_code` (unique within the Enterprise), a street `address`, a centroid given as `geo_latitude` and `geo_longitude` in decimal degrees, a covered `site_area_sqm` in square meters, and two contractual targets: `target_capacity_mbps` (an integer of at least 1), the aggregate downlink capacity the deployment must deliver, and `target_availability_pct`, the availability percentage the service is held to (for example 99.95). A new Site starts in `PLANNED` status. Its `posture` — a derived field beginning at `DORMANT` — is the operator-facing summary of where the site stands and gates what child operations are meaningful; its legal values are `DORMANT`, `DESIGNING`, `COORDINATING`, `DEPLOYING`, `OPERATIONAL`, and `REMEDIATING`. Two further derived counters live on the Site and stay current automatically: `spectrum_utilization_mhz`, the sum of `assigned_bandwidth_mhz` across all `ACTIVE` spectrum assignments on the site's cells, and `device_count`, the number of non-decommissioned devices under the site.

An Enterprise leaves `ONBOARDING` for `ACTIVE` only when it has at least one Site in any non-terminal state; the activation is performed by a `NetworkArchitect`, is rejected with `ERR_INVALID_STATE` when the Enterprise is not `ONBOARDING` or has no non-terminal Site, and increments the Enterprise's `version`. From `ACTIVE`, the enterprise may later be suspended, resumed, or — once everything is wound down — offboarded; those flows are covered in §3.10. The Enterprise's full status progression is `ONBOARDING → ACTIVE → SUSPENDED → OFFBOARDED`, with `SUSPENDED → ACTIVE` as the resume path and `OFFBOARDED` terminal.

### 3.2. The Site Survey: Measuring Before Designing

No design work may rest on guesswork. A `FieldTechnician` visits the site and records a SiteSurvey in `DRAFT`, supplying their own operator identifier as `surveyor_id`, the `survey_date` of the physical visit, the median reference signal received power `measured_rsrp_dbm` (an integer), the median signal-to-interference-plus-noise ratio `measured_sinr_db` (an integer), the measured indoor `floor_plan_area_sqm`, and a `building_material_class` of `OPEN`, `WOOD`, `CONCRETE`, `STEEL`, or `MIXED`. The moment the survey is created — and again whenever its `building_material_class` changes — the server derives `attenuation_factor_db` from the material class: `OPEN` maps to 3 dB, `WOOD` to 6 dB, `CONCRETE` to 12 dB, `STEEL` to 18 dB, and `MIXED` to 10 dB.

Submitting the survey moves it from `DRAFT` to `SUBMITTED` and is restricted to the technician who performed it: `surveyor_id` must equal the caller's `X-User-ID`. Approval belongs to a different pair of hands — an `RFEngineer` — and the approving engineer may not be the same operator who submitted it; a self-approval is rejected with `ERR_SEGREGATION_OF_DUTY`. Two further conditions bind at approval: the survey's `measured_rsrp_dbm` must be at least -110 dBm — a weaker median signal is rejected with `ERR_SURVEY_SIGNAL_TOO_WEAK` (HTTP 422) — and any other survey for the same site that is already `APPROVED` is superseded by the approval, as described below. An `RFEngineer` may instead reject a `SUBMITTED` survey, moving it to `REJECTED` with no further effect.

Approving a survey is the hinge that moves the whole site forward: if the parent Site is `PLANNED` it transitions `PLANNED → SURVEYED` and its `posture` becomes `DESIGNING`; if the Site is already past `PLANNED` its status and posture are left unchanged. In either case the Site's `version` increments. If an earlier survey for the same site was already `APPROVED`, the act of approving the newer one automatically supersedes the older — the older survey moves to `SUPERSEDED` — and, critically, any coverage design that was based on the now-superseded survey is itself moved to `REJECTED`, because its measurement foundation has been invalidated. The SiteSurvey lifecycle is `DRAFT → SUBMITTED → APPROVED → SUPERSEDED`, with `REJECTED` as the alternative terminal state out of `SUBMITTED`.
### 3.3. Coverage Design: Proving Capacity Before Anything Is Built

With an approved survey in hand, an `RFEngineer` drafts a CoverageDesign for the site. The creation request names the `based_on_survey_id` — which must reference an existing survey of any status; the requirement that the base survey be `APPROVED` binds later, at submission — states whether `edge_compute_required` is true (it must be, whenever any latency-critical application is present), and optionally picks an `edge_compute_placement` of `NONE`, `ON_PREMISE`, `NEAR_EDGE`, or `FAR_EDGE` (defaulting to `NONE`). Because a design's validity depends on the site's state at the moment the engineer last read it, the creation also carries `expected_site_version` per the optimistic concurrency rule in §2.7; if the Site's `version` has since advanced — for instance because a newer survey was just approved — the create is refused with `ERR_STALE_SITE_VERSION`. Each new design receives a `design_revision` one greater than the highest revision previously issued for that site, the Site's `version` increments as a side effect of the creation, and the design is born in `DRAFT`.

At creation the server computes `predicted_capacity_mbps`, the provisional, optimistic estimate of aggregate downlink capacity. The estimate sums a per-cell contribution over every CellSector under the site in `PLANNED` or `CONFIGURED` status — cells in `DECOMMISSIONED` are excluded — where each cell contributes its slice-class base rate (900 Mbps for `EMBB` usage, 300 Mbps for `URLLC`, 60 Mbps for `MMTC`; capacity estimation defaults to the `EMBB` class), scaled by the ratio of the cell's `max_eirp_dbm` to the 40 dBm reference but never scaled above unity, and further scaled by one minus the ratio of the survey's `attenuation_factor_db` to the 30 dB full-loss reference. The provisional variant assumes the optimistic 6 dB interference margin and applies no neighbor-cell penalty. Each per-cell contribution is rounded half-up to a whole Mbps before the contributions are summed.

Submitting the design moves it `DRAFT → SUBMITTED`, and at that moment two more derived values are computed. First, `required_cell_count`: the site's `site_area_sqm` divided by an effective per-cell coverage of 5,000 square meters, where that per-cell figure is scaled down by a material penalty factor computed as one minus the survey's `attenuation_factor_db` over 30, with the factor floored at 0.25 so a very lossy building never reduces effective coverage below a quarter of nominal; the quotient is rounded up to a whole number, and the result is at least 1 — a submission with a `required_cell_count` below 1 cannot occur, and a submission whose base survey is not `APPROVED` is rejected with `ERR_INVALID_STATE`. Second, `capacity_shortfall_mbps`: the amount by which `predicted_capacity_mbps` falls short of the site's `target_capacity_mbps`, floored at zero so a design that exceeds its target reports a shortfall of zero. The provisional estimate is recomputed at submission — from the site's current set of `PLANNED` and `CONFIGURED` cells — so cells added after the design was drafted are counted before the shortfall is derived. Submission also enforces a minimum-viability floor: if the site's `target_capacity_mbps` is below 100 Mbps the submission is rejected with `ERR_TARGET_CAPACITY_TOO_LOW` (HTTP 422).

Approval of a `SUBMITTED` design belongs to the `NetworkArchitect` — note the deliberate hand-off: the `RFEngineer` authors and submits, the architect approves or rejects. Approval requires `capacity_shortfall_mbps` to be exactly zero; any positive shortfall is rejected with `ERR_CAPACITY_SHORTFALL` (HTTP 422), forcing the engineer to add cells or adjust the plan first. When approval succeeds, three things happen together: the parent Site moves `SURVEYED → DESIGNED` with `posture` becoming `COORDINATING` and its `version` incrementing as part of that transition (if the Site is already past `SURVEYED` — for instance because a prior design was approved — the Site's status, posture, and version are left unchanged); the design's `final_capacity_mbps` is computed by the conservative final variant described below; and any previously `APPROVED` design for the same site is superseded, moving to `SUPERSEDED`. Superseding a design — whether because a newer design was approved or because its base survey was superseded — also cascades to the physical plan: every CellSector still in `PLANNED` under the superseded design is moved to `DECOMMISSIONED`. `final_capacity_mbps` remains null until approval; it is computed only when the design is `APPROVED`.

The final, conservative capacity variant recomputes the same per-cell structure but with a 9 dB interference margin in place of the optimistic 6 dB, and additionally subtracts a five percent penalty for each `ON_AIR` neighbor cell within 500 meters, compounding multiplicatively and counting at most three neighbors — so one neighbor scales the contribution by 0.95, two by 0.95 squared, and three or more by 0.95 cubed. As with the provisional variant, each per-cell contribution is rounded half-up to a whole Mbps before summation. The CoverageDesign lifecycle mirrors the survey's: `DRAFT → SUBMITTED → APPROVED → SUPERSEDED`, with `REJECTED` reachable from `SUBMITTED`.

### 3.4. Spectrum: Leasing, Coordination, and Registration

A designed site needs authorized spectrum before any cell can transmit. Spectrum enters the system as a SpectrumLease, created by a `SpectrumCoordinator` under the Enterprise with a `band_class` of `LICENSED_C_BAND`, `SHARED_CBRS`, `UNLICENSED_5GHZ`, or `UNLICENSED_6GHZ`; a `center_frequency_mhz`; a total `bandwidth_mhz`; a half-open window from `lease_start_utc` (inclusive) to `lease_end_utc` (exclusive); and a `monthly_cost_cents`. For the `SHARED_CBRS` band only, a `priority_access_tier` of `PAL` (priority access license) or `GAA` (general authorized access) may be given, defaulting to `GAA`. A new lease starts `PENDING`; the coordinator activates it to `ACTIVE`, may later suspend it, and can cancel it from any non-terminal state — cancellation is the dangerous path, because every `ACTIVE` SpectrumAssignment backed by that lease is automatically `REVOKED`, each affected cell drops to `DEGRADED`, and the parent Site's `spectrum_utilization_mhz` is reduced by each revoked assignment's bandwidth. The same automatic revocation happens when a lease reaches its `lease_end_utc` under the logical clock and expires, and each revocation — whether caused by cancellation or by expiry — also raises a MonitoringAlert of class `OUTAGE` at severity `MAJOR` on the affected site. The lease lifecycle is `PENDING → ACTIVE → SUSPENDED → EXPIRED → CANCELLED`.

With a lease in place, the `SpectrumCoordinator` files a SpectrumCoordinationRequest against the site, recording their own operator id as `requesting_coordinator_id`, the `band_class`, the `requested_bandwidth_mhz`, and the desired half-open window from `requested_start_utc` to `requested_end_utc`. The request is created in `DRAFT`. Submitting it (`DRAFT → SUBMITTED`) is restricted to the filing coordinator — `requesting_coordinator_id` must equal `X-User-ID` — and requires the Site to be in `DESIGNED` status. Beginning coordination moves the request to `COORDINATING` and triggers the interference analysis: the server computes the request's `interference_report`, an object with `aggregate_margin_db`, `worst_case_margin_db`, and `neighbor_cells_checked`. For every `ON_AIR` cell sector within the 1,000-meter coordination radius of any `PLANNED` or `CONFIGURED` cell of this site, the path loss in decibels is computed as 20 times the base-10 logarithm of the distance in meters, plus 20 times the base-10 logarithm of the center frequency in megahertz, plus the 32.44 dB free-space constant — where the center frequency is taken from a non-terminal (`ACTIVE`, `PENDING`, or `SUSPENDED`) SpectrumLease of the site's Enterprise on the request's `band_class`, and when no such lease exists a band default is used: 3750 MHz for `LICENSED_C_BAND`, 3550 MHz for `SHARED_CBRS`, 5500 MHz for `UNLICENSED_5GHZ`, and 6500 MHz for `UNLICENSED_6GHZ`; the neighbor's received interference is its `max_eirp_dbm` minus that path loss, and the margin against that neighbor is the negation of the received interference minus the neighbor cell's `interference_margin_db`. `worst_case_margin_db` is the smallest margin across all such neighbors — defaulting to +99 when there are none — and `aggregate_margin_db` is the arithmetic mean of all margins, rounded half-up. Both are expressed to one decimal place.

Approval of a `COORDINATING` request belongs exclusively to the `SpectrumRegulator` — never to the coordinator who filed it; self-approval draws `ERR_SEGREGATION_OF_DUTY`. Three conditions bind at approval, evaluated after the state checks and in this order: the `interference_report`'s `worst_case_margin_db` must be at least 0, else the approval is rejected with `ERR_INTERFERENCE_MARGIN_EXCEEDED` (HTTP 422); for a `SHARED_CBRS` request at the `PAL` tier — a request counts as PAL-tier when a non-terminal (`ACTIVE`, `PENDING`, or `SUSPENDED`) PAL lease for the same `band_class` exists on the site's Enterprise — the requested window must not overlap any non-terminal `PAL` lease on the same `band_class` (across all Enterprises) whose center frequency falls within the same 10-megahertz bucket (center frequencies within ±10 MHz of each other), else the request fails with `ERR_SPECTRUM_OVERLAP` (HTTP 409) — and this same overlap rule is enforced symmetrically when a `PAL`-tier `SHARED_CBRS` lease is created, scoped there to other non-terminal PAL leases of the same Enterprise; and the optimistic-concurrency rule of §2.7 requires the approval to carry `expected_request_version` matching the request's current `version`, else it is refused with `ERR_STALE_REQUEST_VERSION`. On approval the server mints the request's `sas_registration_id` in the form SAS-XXXXXX, representing the Spectrum Access System registration. The regulator may instead reject the request outright, moving it to `REJECTED`.

An `APPROVED` request becomes `REGISTERED` when the coordinator registers it — which requires the `sas_registration_id` to be present and an `ACTIVE` SpectrumLease to exist for this Enterprise covering the requested `band_class` over a window that fully contains the requested window; absent such a lease the registration is rejected with `ERR_NO_ACTIVE_LEASE` (HTTP 422). The first request for a site to reach `REGISTERED` moves the Site `DESIGNED → COORDINATED`, sets `posture` to `DEPLOYING`, and bumps the Site's `version`; subsequent registrations do not repeat that transition. At any point before terminality — from `DRAFT`, `SUBMITTED`, `COORDINATING`, or `APPROVED` — the filing coordinator, and only the filing coordinator, may withdraw the request to `WITHDRAWN`. Every transition on a coordination request increments the request's own `version`. The full lifecycle is `DRAFT → SUBMITTED → COORDINATING → APPROVED → REGISTERED`, with `REJECTED` out of `COORDINATING` and `WITHDRAWN` out of any pre-terminal state.
### 3.5. Cell Sectors, Spectrum Assignment, and Turning the Site On

Cell sectors are the physical plan. An `RFEngineer` creates a CellSector under any site that is not `DECOMMISSIONED` — including a live site undergoing remediation — giving a `sector_label` (such as NE-A or SW-B, unique within the Site), an `azimuth_degrees` between 0 and 359, an antenna `height_m` above ground, and a `max_eirp_dbm` ceiling. The server derives `cell_radius_m` from `height_m` and `max_eirp_dbm` via its propagation model — `100 × √max(height_m, 1) × 10^((max_eirp_dbm − 30)/20)`, rounded half-up to a whole meter and floored at 1 — and initializes the cell's `interference_margin_db` to the optimistic 6 dB reserve against co-channel neighbors (the conservative variant used in final capacity computation is 9 dB). A `FieldTechnician` then walks the cell through `PLANNED → CONFIGURED → ON_AIR`, with `OFF_AIR` reachable only from `ON_AIR` and `DECOMMISSIONED` from any non-terminal state; a `DEGRADED` cell therefore has no path back on air through these transitions and may only be decommissioned. Decommissioning a cell releases its spectrum as described below — every `ACTIVE` assignment on the cell moves to `RELEASED` — while merely taking a cell off air leaves its assignments in place. A cell's full status chain is `PLANNED → CONFIGURED → ON_AIR → DEGRADED → OFF_AIR → DECOMMISSIONED`, where `DEGRADED` is entered automatically when its spectrum is revoked — that is, when the backing lease expires or is cancelled, a cell holding a revoked assignment and currently `ON_AIR` or `CONFIGURED` drops to `DEGRADED` (a cell in `PLANNED` remains `PLANNED`, and a cell already `OFF_AIR` remains `OFF_AIR`).

A cell may not go on air on hope alone — it needs assigned spectrum. The `SpectrumCoordinator` creates a SpectrumAssignment on the cell by naming a `coordination_request_id` (which must reference a request in `REGISTERED` status), a `spectrum_lease_id` (which must reference an `ACTIVE` lease), the `assigned_bandwidth_mhz` to consume, and a half-open usage window from `assignment_start_utc` to `assignment_end_utc`. Two fiscal guards apply at creation, in the temporal-then-fiscal order of §2.9: assignment windows on the same cell must be disjoint half-open intervals — an overlapping window is rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409) — and the sum of `assigned_bandwidth_mhz` across all `ACTIVE` assignments on the chosen lease, plus the new assignment, must not exceed the lease's total `bandwidth_mhz`, else the create fails with `ERR_LEASE_BANDWIDTH_EXCEEDED` (HTTP 422). A new assignment is immediately `ACTIVE`, and the site-level derived total reflects it at once: the parent Site's `spectrum_utilization_mhz` increases by the assigned bandwidth. Releasing an assignment (performed by a `FieldTechnician`, and only while the cell is `OFF_AIR` or `PLANNED` — releasing from an `ON_AIR` cell would require re-tuning and is not permitted) moves it to `RELEASED` and subtracts its bandwidth from the site's utilization. Whether computed incrementally on each create, release, or revocation, or recomputed from scratch across all of a site's `ACTIVE` assignments (as happens on site decommission or a periodic audit), `spectrum_utilization_mhz` must always equal the same sum; the two computation paths are required to agree. The assignment lifecycle is `ACTIVE → RELEASED → REVOKED`, with `REVOKED` reached only by the system when the backing lease expires or is cancelled.

Turning a cell on air — the `CONFIGURED → ON_AIR` step — requires an `ACTIVE` SpectrumAssignment on that cell, without which the transition is rejected with `ERR_INVALID_STATE`. When the transition succeeds and, as a result, every `PLANNED` cell under the site either holds an `ACTIVE` assignment or has been `DECOMMISSIONED`, and at least one cell is now `ON_AIR`, the Site itself advances `COORDINATED → DEPLOYED`.

The final step to revenue service is site activation by a `NetworkArchitect`: the Site moves `DEPLOYED → OPERATIONAL`, its `posture` becomes `OPERATIONAL`, and the Enterprise's `active_site_count` increases by 1. Activation is guarded twice: the Enterprise must be `ACTIVE`, and at least one `ACTIVE` ServiceContract must cover the site (contracts are Enterprise-scoped, so any `ACTIVE` contract on the parent Enterprise counts) — each failed guard is rejected with `ERR_INVALID_STATE`. A site without live contractual coverage cannot enter service.

### 3.6. Devices and SIM Profiles: Provisioning the Fleet

SIM profiles are the enterprise's identity pool. A `FieldTechnician` creates a SIMProfile under the Enterprise with a 19–20 digit `iccid` (globally unique), optionally a `subscription_profile` of `STANDARD`, `IOT_NBIOT`, `IOT_CATM`, or `PREMIUM_5G` (defaulting to `STANDARD`), and optionally a `monthly_quota_mb` data allowance defaulting to 10,240 MB. The server mints a unique 15-digit `imsi` and a `ki_key_ref` — a reference into the HSM vault that is never returned raw in any response. A new profile is `UNASSIGNED`; its lifecycle is `UNASSIGNED → BOUND → ACTIVE → SUSPENDED → RETIRED`.

Devices are registered by a `FieldTechnician` against a specific cell sector — permitted whatever the cell's current status — entering `INVENTORY` with a globally unique `serial_number`, a `device_type` of `CPE`, `SENSOR`, `HANDSET`, `AGV`, `CAMERA`, or `GATEWAY`, and a unique 15-digit `imei`. The device's `site_id` is denormalized from the parent cell's site at registration so site-level device listings can filter without traversal.

Binding a SIM to a device is the provisioning hinge: the caller supplies `sim_profile_id`, and the bind succeeds only when the named SIMProfile exists, is `UNASSIGNED`, and belongs to the same Enterprise as the device's site — a cross-enterprise bind is rejected with `ERR_CROSS_ENTERPRISE_REFERENCE` (HTTP 422) — and when the parent cell is `CONFIGURED` or `ON_AIR`. On success the device moves `INVENTORY → PROVISIONING`, its `sim_profile_id` is set, and the SIM moves to `BOUND`. Activation then moves the device `PROVISIONING → ACTIVE`, requires the Site to be `DEPLOYED` or `OPERATIONAL` and the cell to be `ON_AIR`, stamps `provisioned_at_utc` from the logical clock, flips the SIM to `ACTIVE`, and increments the Site's `device_count` by 1.

Suspending an `ACTIVE` device also suspends its SIM, and tears down any live slice binding — the binding's `unbound_at_utc` is stamped and the slice's `bound_device_count` decreases by 1. Resuming a suspended device requires the Site to be `DEPLOYED`, `OPERATIONAL`, or `REMEDIATION_REQUIRED` and returns the SIM to `ACTIVE`. Decommissioning — permitted from `INVENTORY`, `PROVISIONING`, `ACTIVE`, or `SUSPENDED` — retires the bound SIM to `RETIRED`, tears down any active slice binding, and decrements the site's `device_count` if the device was `ACTIVE` at the time. Decommissioned devices remain queryable; they are soft-deleted, not erased.

### 3.7. Network Slicing and Quality of Service

Once a site is live, a `NetworkArchitect` may carve it into slices. A NetworkSlice is created under a Site in `DEFINED` status with a `slice_name` unique within the site, a `slice_type` of `EMBB`, `URLLC`, or `MMTC`, a reserved `guaranteed_bandwidth_mbps` (integer, at least 0), an SLA latency bound `max_latency_ms` (integer, at least 0), and a `max_devices` cap on concurrent bindings (integer, at least 0); its `bound_device_count` starts at 0.

Activating a slice (`DEFINED → ACTIVATED`, or `SUSPENDED → ACTIVATED` on resume) is where the capacity bookkeeping bites. The site must be `OPERATIONAL`. The sum of `guaranteed_bandwidth_mbps` across all currently `ACTIVATED` slices on the site plus the slice being activated must be at most the site's `target_capacity_mbps` — equality is permitted, but exceeding the target by even 1 Mbps is rejected with `ERR_SLICE_BANDWIDTH_EXCEEDED` (HTTP 422). And a `URLLC` slice additionally demands edge placement: the site's approved CoverageDesign must have an `edge_compute_placement` of `ON_PREMISE` or `NEAR_EDGE`; activating a `URLLC` slice on a design placed `NONE` or `FAR_EDGE` is rejected with `ERR_URLLC_REQUIRES_EDGE` (HTTP 422).

Binding devices is field work: a `FieldTechnician` binds an `ACTIVE` device to an `ACTIVATED` slice by supplying `device_id` in the request body, which creates a SliceBinding stamped with `bound_at_utc` from the logical clock and increments the slice's `bound_device_count`; a `device_id` that does not reference an existing device of the same Site is rejected with `ERR_REFERENCE_NOT_FOUND`. Re-binding a device that already has an active binding on the same slice is idempotent: no new binding is created, the count is unchanged, and the existing binding is returned with HTTP 201. Unbinding takes the same `device_id` body field; it stamps the binding's `unbound_at_utc` and decrements the count, and is rejected with `ERR_INVALID_STATE` when no active binding exists for that device on that slice. The device must belong to the same Site as the slice, and the bind is refused with `ERR_SLICE_DEVICE_CAP_EXCEEDED` (HTTP 422) when the slice's `bound_device_count` has already reached `max_devices`. A binding with a null `unbound_at_utc` is the active one. Suspending a slice tears down all of its active bindings at once and zeroes `bound_device_count`. Retiring a slice — from `DEFINED`, `ACTIVATED`, or `SUSPENDED` — is only permitted when `bound_device_count` is 0, and `RETIRED` is terminal.
### 3.8. Service Contracts, Monitoring, and SLA Credits

A ServiceContract is drafted by a `NetworkArchitect` under the Enterprise with a unique `contract_code`, an `sla_tier` of `STANDARD`, `ENHANCED`, or `MISSION_CRITICAL`, a `contracted_availability_pct` (such as 99.9, 99.95, or 99.99), a `contracted_max_outage_minutes_per_month` budget, an `onsite_support_window` of `NEXT_BUSINESS_DAY`, `FOUR_HOUR`, or `TWO_HOUR`, and a half-open term from `contract_start_utc` to `contract_end_utc`. Activating a `DRAFT` contract requires the Enterprise to be `ACTIVE` and forbids tier collisions: no other `ACTIVE` contract on the same Enterprise may have an overlapping term at the same `sla_tier` — such a collision is rejected with `ERR_CONTRACT_OVERLAP` (HTTP 409). The contract lifecycle is `DRAFT → ACTIVE → BREACHED → RENEWED → TERMINATED`, with `TERMINATED` also reachable directly from `DRAFT` or `ACTIVE`, and both `RENEWED` and `TERMINATED` terminal.

Renewal is available only in the contract's final month: the logical current time must be within 30 days of `contract_end_utc` (that is, at or after the instant 30 days before the end). Renewing moves the existing contract to `RENEWED` and creates a fresh contract in `DRAFT` whose start equals the old contract's end and which inherits the old contract's `sla_tier`, `contracted_availability_pct`, `contracted_max_outage_minutes_per_month`, and `onsite_support_window`; the renewal request supplies the new term's `new_contract_end_utc`, which must be strictly later than the current `contract_end_utc` (else `ERR_INVALID_TIME_WINDOW`). The new contract's `contract_code` is derived server-side as the old code suffixed `-R1`, `-R2`, and so on, taking the first suffix not already in use; the renew operation returns HTTP 201 with the newly created contract in the data field. Terminating a contract has teeth: if the terminated contract was the last `ACTIVE` coverage for any Site in `OPERATIONAL`, those sites drop to `REMEDIATION_REQUIRED` with `posture` becoming `REMEDIATING`, because live service without contractual coverage is not permitted to stand.

Operational truth arrives as MonitoringAlerts. A `FieldTechnician` raises an alert on a site with an `alert_class` of `OUTAGE`, `DEGRADATION`, `INTERFERENCE`, `CAPACITY`, or `SECURITY` and a `severity` of `INFO`, `MINOR`, `MAJOR`, or `CRITICAL`; the alert opens in `OPEN` with `raised_at_utc` stamped from the logical clock. Acknowledging an alert moves it to `ACKNOWLEDGED` — and when the severity is `MAJOR` or `CRITICAL` and the Site is `OPERATIONAL`, the acknowledgment also moves the Site to `REMEDIATION_REQUIRED` with `posture` becoming `REMEDIATING`, because a major operational event on a live site demands a remediation plan. The technician then moves the alert through `ACKNOWLEDGED → MITIGATING → RESOLVED`; from `OPEN` or `ACKNOWLEDGED` it may instead be dismissed as `FALSE_ALARM`.

Resolution is where the money moves. Resolving requires that no CoverageRemediation referencing this alert is still open — one whose status is `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or `VERIFYING` blocks resolution with `ERR_REMEDIATION_OPEN` (HTTP 422); only a `COMPLETED` remediation clears the way. On resolution the alert's `resolved_at_utc` is stamped. When the alert is an `OUTAGE` at `CRITICAL` severity, the downtime in minutes from `raised_at_utc` to `resolved_at_utc` is added to the running total of CRITICAL outage minutes for the UTC calendar month of the resolution instant, tracked per Enterprise, and if that cumulative total exceeds the covering contract's `contracted_max_outage_minutes_per_month` — the covering contract being the Enterprise's contract in `ACTIVE` or `BREACHED` status (the earliest-created such contract, when several exist) — the contract automatically flips from `ACTIVE` to `BREACHED` and an SLA credit is applied. The credit is applied per breach event — that is, only on a resolution event at which the cumulative monthly total crosses the budget; resolution events whose cumulative total remains at or below the budget carry no credit. Once the contract is `BREACHED`, further `CRITICAL` outage resolutions in the same calendar month each apply the per-event credit again, since the cumulative total already exceeds the budget. The credit per breach event is a percentage of the contract's monthly fee — taken as a flat 100,000 cents per month for this platform — with the rate tiered by `sla_tier`: 5 percent for `STANDARD`, 10 percent for `ENHANCED`, and 20 percent for `MISSION_CRITICAL`. Each event's credit is rounded half-up to a whole cent, then the per-event credits for the month are summed; the resulting `sla_credit_applied_cents` is recorded on the alert and added to the Enterprise's `sla_credit_balance_cents`.

### 3.9. Coverage Remediation: Closing the Loop After Operational Feedback

When an alert exposes a coverage or capacity gap, an `RFEngineer` files a CoverageRemediation against the site, naming the `triggered_by_alert_id` that prompted it, an optional `supersedes_remediation_id` chaining it to an earlier remediation it replaces (null for the first in a chain), a free-text `remediation_plan`, the `additional_cells_planned` count (an integer, at least 0), and optionally `additional_spectrum_mhz` (an integer, at least 0) defaulting to 0. The remediation is born in `PROPOSED`, and its `in_progress_started_at_utc` is null until work begins.

Approval moves it `PROPOSED → APPROVED` under a `NetworkArchitect`; starting work moves it to `IN_PROGRESS` under an `RFEngineer` and stamps `in_progress_started_at_utc`. Verification — a `FieldTechnician` moving it `IN_PROGRESS → VERIFYING` — is the audit step: the number of CellSectors under the site created at or after `in_progress_started_at_utc` that are currently `ON_AIR` must equal exactly `additional_cells_planned`; a mismatch is rejected with `ERR_REMEDIATION_CELLS_MISSING` (HTTP 422). Completion (`VERIFYING → COMPLETED`, by a `NetworkArchitect`) returns the Site from `REMEDIATION_REQUIRED` to `OPERATIONAL` and restores `posture` to `OPERATIONAL`. If verification reveals the plan was wrong, the architect may instead reopen the remediation (`VERIFYING → REOPENED`), from which an `RFEngineer` starts it again back into `IN_PROGRESS` — the cycle can repeat until the plan and the physical reality agree. `COMPLETED` is terminal.

Remediation is also the re-entry point into the earlier lifecycle stages: a remediation that adds cells or spectrum may require a fresh survey, a revised coverage design, and new spectrum coordination, and those flows follow the same rules as the original pass — including the optimistic-concurrency guard on design creation, since a site whose `version` moved during remediation invalidates stale design drafts.

### 3.10. Suspension, Decommissioning, and Offboarding

Suspending an `ACTIVE` Enterprise is a broad-axe operation performed by a `NetworkArchitect`: every `ON_AIR` cell under the enterprise's deployed sites — that is, Sites in `DEPLOYED` or `OPERATIONAL` status — transitions to `OFF_AIR`, every `ACTIVE` device under any of the enterprise's sites moves to `SUSPENDED` (its bound SIM moving to `SUSPENDED` with it and any live slice binding torn down), and every `ACTIVE` SpectrumLease moves to `SUSPENDED`. Resuming reverses the posture at the site level — sites that were `OPERATIONAL` before the suspension return to `OPERATIONAL` — and both transitions increment the Enterprise's `version`.

Decommissioning a Site requires that all of its CellSectors are `OFF_AIR` or `DECOMMISSIONED` and all of its Devices are `DECOMMISSIONED`; any straggler rejects the operation with `ERR_CHILDREN_ACTIVE` (HTTP 422). On success, every `ACTIVE` SpectrumAssignment on the site's cells is `RELEASED`, the site's `posture` returns to `DORMANT`, and the Enterprise's `active_site_count` decreases by 1 when the site was `OPERATIONAL` or `REMEDIATION_REQUIRED` at the time (a site decommissioned before activation never counted). Decommissioned cells and devices remain queryable as historical records.

Offboarding an Enterprise is the final act and is permitted only from `ACTIVE`, only when every Site is `DECOMMISSIONED` and every ServiceContract is `TERMINATED` or `RENEWED`; otherwise the request is rejected with `ERR_ENTERPRISE_CHILDREN_ACTIVE` (HTTP 422). Offboarding moves the Enterprise to `OFFBOARDED` and retires every SIMProfile it owns to `RETIRED`.
### 3.11. Reading State: Summaries, Filters, and Cross-References

Beyond the lifecycle writes, the API provides broad read access. A site summary capability returns a computed rollup for one Site — an object with `site_id`, `status`, `posture`, `capacity_shortfall_mbps` (taken from the site's currently `APPROVED` CoverageDesign, or null when there is none), `spectrum_utilization_mhz`, `device_count`, `open_alert_count` (alerts in `OPEN`, `ACKNOWLEDGED`, or `MITIGATING`), and `active_slice_count` (slices in `ACTIVATED`) — for the `NetworkArchitect`, `RFEngineer`, `SpectrumCoordinator`, and `FieldTechnician` roles. Flat single-resource reads exist for every entity so a holder of an identifier can reach the resource without knowing its full containment path, and filtered list reads support reverse-reachability along every foreign key: surveys filterable by `site_id`, `surveyor_id`, and `status`; designs by `site_id`, `based_on_survey_id`, and `status`; coordination requests by `site_id`, `requesting_coordinator_id`, `band_class`, and `status`; spectrum assignments by `cell_sector_id`, `coordination_request_id`, `spectrum_lease_id`, and `status`; devices by `cell_sector_id`, `site_id`, `sim_profile_id`, `status`, and `device_type`; slice bindings by `slice_id`, `device_id`, and an `active_only` flag; slices by `site_id`, `status`, and `slice_type`; contracts by `enterprise_id`, `status`, and `sla_tier`; alerts by `site_id`, `status`, `severity`, and `alert_class`; remediations by `site_id`, `triggered_by_alert_id`, `supersedes_remediation_id`, and `status`; sites by `enterprise_id`, `status`, and `posture`; cells by `site_id` and `status`; leases by `enterprise_id`, `status`, and `band_class`; SIM profiles by `enterprise_id` and `status`; and enterprises by `status` and `industry_vertical`. All list reads accept `limit` and `offset` per §2.3.

## 4. Endpoint Definitions

All endpoints are mounted under the `/private-wireless` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify, transition, or read an existing resource return HTTP 200. Request and response payloads are not repeated here — the fields, preconditions, and side effects of each operation are defined in the narratives of §2 and §3, and the tables below exist to fix the method, path, and authorized roles of each operation.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /private-wireless/_clock/set_current_utc | Advance the logical clock to `to_iso8601`; re-evaluate all time-derived rules | NetworkArchitect |
| POST | /private-wireless/enterprises | Create an Enterprise | NetworkArchitect |
| GET | /private-wireless/enterprises | List enterprises with pagination and filters | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| GET | /private-wireless/enterprises/{id} | Get one enterprise | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| POST | /private-wireless/enterprises/{id}/activate | Enterprise ONBOARDING → ACTIVE | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/suspend | Enterprise ACTIVE → SUSPENDED, cascading to sites, devices, leases | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/resume | Enterprise SUSPENDED → ACTIVE | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/offboard | Enterprise ACTIVE → OFFBOARDED; retires SIM profiles | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/sites | Create a Site under an Enterprise | NetworkArchitect |
| GET | /private-wireless/enterprises/{id}/sites | List sites for an enterprise | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| GET | /private-wireless/sites/{id} | Get one Site | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| POST | /private-wireless/sites/{id}/activate | Site DEPLOYED → OPERATIONAL | NetworkArchitect |
| POST | /private-wireless/sites/{id}/decommission | Site → DECOMMISSIONED; releases spectrum assignments | NetworkArchitect |
| POST | /private-wireless/sites/{id}/surveys | Create a SiteSurvey in DRAFT | FieldTechnician |
| GET | /private-wireless/sites/{id}/surveys | List surveys for a site | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| GET | /private-wireless/sites/{id}/surveys/{id2} | Get one survey | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| POST | /private-wireless/sites/{id}/surveys/{id2}/submit | Survey DRAFT → SUBMITTED | FieldTechnician |
| POST | /private-wireless/sites/{id}/surveys/{id2}/approve | Survey SUBMITTED → APPROVED; drives Site PLANNED → SURVEYED | RFEngineer |
| POST | /private-wireless/sites/{id}/surveys/{id2}/reject | Survey SUBMITTED → REJECTED | RFEngineer |
| POST | /private-wireless/sites/{id}/designs | Create a CoverageDesign in DRAFT (OCC-guarded) | RFEngineer |
| GET | /private-wireless/sites/{id}/designs | List designs for a site | NetworkArchitect, RFEngineer |
| GET | /private-wireless/sites/{id}/designs/{id2} | Get one design | NetworkArchitect, RFEngineer |
| POST | /private-wireless/sites/{id}/designs/{id2}/submit | Design DRAFT → SUBMITTED; computes required cells and shortfall | RFEngineer |
| POST | /private-wireless/sites/{id}/designs/{id2}/approve | Design SUBMITTED → APPROVED; drives Site SURVEYED → DESIGNED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/designs/{id2}/reject | Design SUBMITTED → REJECTED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/cells | Create a CellSector in PLANNED | RFEngineer |
| GET | /private-wireless/sites/{id}/cells | List cells for a site | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| GET | /private-wireless/cells/{id} | Get one cell | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| POST | /private-wireless/sites/{id}/cells/{id2}/configure | Cell PLANNED → CONFIGURED | FieldTechnician |
| POST | /private-wireless/sites/{id}/cells/{id2}/on-air | Cell CONFIGURED → ON_AIR; may drive Site COORDINATED → DEPLOYED | FieldTechnician |
| POST | /private-wireless/sites/{id}/cells/{id2}/off-air | Cell ON_AIR → OFF_AIR | FieldTechnician |
| POST | /private-wireless/sites/{id}/cells/{id2}/decommission | Cell any non-terminal → DECOMMISSIONED | FieldTechnician |
| POST | /private-wireless/enterprises/{id}/spectrum-leases | Create a SpectrumLease in PENDING | SpectrumCoordinator |
| GET | /private-wireless/enterprises/{id}/spectrum-leases | List leases for an enterprise | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| GET | /private-wireless/spectrum-leases/{id} | Get one lease | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| POST | /private-wireless/spectrum-leases/{id}/activate | Lease PENDING → ACTIVE | SpectrumCoordinator |
| POST | /private-wireless/spectrum-leases/{id}/cancel | Lease any non-terminal → CANCELLED; revokes assignments | SpectrumCoordinator |
| POST | /private-wireless/sites/{id}/coordination-requests | Create a SpectrumCoordinationRequest in DRAFT | SpectrumCoordinator |
| GET | /private-wireless/sites/{id}/coordination-requests | List coordination requests for a site | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| GET | /private-wireless/sites/{id}/coordination-requests/{id2} | Get one coordination request | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/submit | Request DRAFT → SUBMITTED | SpectrumCoordinator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/begin-coordination | Request SUBMITTED → COORDINATING; computes interference report | SpectrumCoordinator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/approve | Request COORDINATING → APPROVED (OCC-guarded); mints SAS registration | SpectrumRegulator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/reject | Request COORDINATING → REJECTED | SpectrumRegulator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/register | Request APPROVED → REGISTERED; drives Site DESIGNED → COORDINATED | SpectrumCoordinator |
| POST | /private-wireless/sites/{id}/coordination-requests/{id2}/withdraw | Request DRAFT/SUBMITTED/COORDINATING/APPROVED → WITHDRAWN | SpectrumCoordinator |
| POST | /private-wireless/cells/{id}/spectrum-assignments | Create a SpectrumAssignment (immediately ACTIVE) | SpectrumCoordinator |
| GET | /private-wireless/cells/{id}/spectrum-assignments | List assignments for a cell | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| POST | /private-wireless/cells/{id}/spectrum-assignments/{id2}/release | Assignment ACTIVE → RELEASED | FieldTechnician |
| POST | /private-wireless/enterprises/{id}/sim-profiles | Create a SIMProfile in UNASSIGNED | FieldTechnician |
| GET | /private-wireless/enterprises/{id}/sim-profiles | List SIM profiles for an enterprise | NetworkArchitect, FieldTechnician |
| GET | /private-wireless/sim-profiles/{id} | Get one SIM profile | NetworkArchitect, FieldTechnician |
| POST | /private-wireless/cells/{id}/devices | Register a Device in INVENTORY | FieldTechnician |
| GET | /private-wireless/cells/{id}/devices | List devices for a cell | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/sites/{id}/devices | List devices for a site across cells | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/devices/{id} | Get one device | NetworkArchitect, RFEngineer, FieldTechnician |
| POST | /private-wireless/cells/{id}/devices/{id2}/bind-sim | Device INVENTORY → PROVISIONING; SIM UNASSIGNED → BOUND | FieldTechnician |
| POST | /private-wireless/cells/{id}/devices/{id2}/activate | Device PROVISIONING → ACTIVE | FieldTechnician |
| POST | /private-wireless/cells/{id}/devices/{id2}/suspend | Device ACTIVE → SUSPENDED; tears down bindings | FieldTechnician |
| POST | /private-wireless/cells/{id}/devices/{id2}/resume | Device SUSPENDED → ACTIVE | FieldTechnician |
| POST | /private-wireless/cells/{id}/devices/{id2}/decommission | Device any non-terminal → DECOMMISSIONED | FieldTechnician |
| POST | /private-wireless/sites/{id}/slices | Create a NetworkSlice in DEFINED | NetworkArchitect |
| GET | /private-wireless/sites/{id}/slices | List slices for a site | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/sites/{id}/slices/{id2} | Get one slice | NetworkArchitect, RFEngineer, FieldTechnician |
| POST | /private-wireless/sites/{id}/slices/{id2}/activate | Slice DEFINED/SUSPENDED → ACTIVATED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/slices/{id2}/suspend | Slice ACTIVATED → SUSPENDED; tears down bindings | NetworkArchitect |
| POST | /private-wireless/sites/{id}/slices/{id2}/retire | Slice DEFINED/ACTIVATED/SUSPENDED → RETIRED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/slices/{id2}/bind-device | Bind an ACTIVE device to the slice (creates SliceBinding) | FieldTechnician |
| POST | /private-wireless/sites/{id}/slices/{id2}/unbind-device | Tear down a SliceBinding | FieldTechnician |
| GET | /private-wireless/sites/{id}/slices/{id2}/bindings | List bindings for a slice | NetworkArchitect, FieldTechnician |
| POST | /private-wireless/enterprises/{id}/contracts | Create a ServiceContract in DRAFT | NetworkArchitect |
| GET | /private-wireless/enterprises/{id}/contracts | List contracts for an enterprise | NetworkArchitect, SpectrumRegulator |
| GET | /private-wireless/enterprises/{id}/contracts/{id2} | Get one contract | NetworkArchitect, SpectrumRegulator |
| POST | /private-wireless/enterprises/{id}/contracts/{id2}/activate | Contract DRAFT → ACTIVE | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/contracts/{id2}/renew | Contract ACTIVE → RENEWED; creates chained DRAFT contract | NetworkArchitect |
| POST | /private-wireless/enterprises/{id}/contracts/{id2}/terminate | Contract DRAFT/ACTIVE/BREACHED → TERMINATED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/alerts | Raise a MonitoringAlert in OPEN | FieldTechnician |
| GET | /private-wireless/sites/{id}/alerts | List alerts for a site | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/sites/{id}/alerts/{id2} | Get one alert | NetworkArchitect, RFEngineer, FieldTechnician |
| POST | /private-wireless/sites/{id}/alerts/{id2}/acknowledge | Alert OPEN → ACKNOWLEDGED; may move Site to REMEDIATION_REQUIRED | FieldTechnician |
| POST | /private-wireless/sites/{id}/alerts/{id2}/mitigate | Alert ACKNOWLEDGED → MITIGATING | FieldTechnician |
| POST | /private-wireless/sites/{id}/alerts/{id2}/resolve | Alert MITIGATING → RESOLVED; may trigger SLA credit and breach | FieldTechnician |
| POST | /private-wireless/sites/{id}/alerts/{id2}/mark-false-alarm | Alert OPEN/ACKNOWLEDGED → FALSE_ALARM | FieldTechnician |
| POST | /private-wireless/sites/{id}/remediations | Create a CoverageRemediation in PROPOSED | RFEngineer |
| GET | /private-wireless/sites/{id}/remediations | List remediations for a site | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/sites/{id}/remediations/{id2} | Get one remediation | NetworkArchitect, RFEngineer, FieldTechnician |
| POST | /private-wireless/sites/{id}/remediations/{id2}/approve | Remediation PROPOSED → APPROVED | NetworkArchitect |
| POST | /private-wireless/sites/{id}/remediations/{id2}/start | Remediation APPROVED/REOPENED → IN_PROGRESS | RFEngineer |
| POST | /private-wireless/sites/{id}/remediations/{id2}/verify | Remediation IN_PROGRESS → VERIFYING; audits new ON_AIR cells | FieldTechnician |
| POST | /private-wireless/sites/{id}/remediations/{id2}/complete | Remediation VERIFYING → COMPLETED; Site → OPERATIONAL | NetworkArchitect |
| POST | /private-wireless/sites/{id}/remediations/{id2}/reopen | Remediation VERIFYING → REOPENED | NetworkArchitect |
| GET | /private-wireless/sites/{id}/summary | Computed site summary: posture, capacity shortfall, spectrum utilization, device count, open alerts, active slices | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| GET | /private-wireless/surveys/{id} | Get one SiteSurvey by id | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| GET | /private-wireless/designs/{id} | Get one CoverageDesign by id | NetworkArchitect, RFEngineer |
| GET | /private-wireless/coordination-requests/{id} | Get one SpectrumCoordinationRequest by id | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| GET | /private-wireless/spectrum-assignments/{id} | Get one SpectrumAssignment by id | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| GET | /private-wireless/slices/{id} | Get one NetworkSlice by id | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/slice-bindings/{id} | Get one SliceBinding by id | NetworkArchitect, FieldTechnician |
| GET | /private-wireless/contracts/{id} | Get one ServiceContract by id | NetworkArchitect, SpectrumRegulator |
| GET | /private-wireless/alerts/{id} | Get one MonitoringAlert by id | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/remediations/{id} | Get one CoverageRemediation by id | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/surveys | Filtered list of SiteSurveys by site_id, surveyor_id, status | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/designs | Filtered list of CoverageDesigns by site_id, based_on_survey_id, status | NetworkArchitect, RFEngineer |
| GET | /private-wireless/coordination-requests | Filtered list of SpectrumCoordinationRequests by site_id, requesting_coordinator_id, status | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| GET | /private-wireless/spectrum-assignments | Filtered list of SpectrumAssignments by cell_sector_id, coordination_request_id, spectrum_lease_id, status | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| GET | /private-wireless/devices | Filtered list of Devices by cell_sector_id, site_id, sim_profile_id, status, device_type | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/slice-bindings | Filtered list of SliceBindings by slice_id, device_id, active_only | NetworkArchitect, FieldTechnician |
| GET | /private-wireless/slices | Filtered list of NetworkSlices by site_id, status, slice_type | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/contracts | Filtered list of ServiceContracts by enterprise_id, status, sla_tier | NetworkArchitect, SpectrumRegulator |
| GET | /private-wireless/alerts | Filtered list of MonitoringAlerts by site_id, status, severity, alert_class | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/remediations | Filtered list of CoverageRemediations by site_id, triggered_by_alert_id, supersedes_remediation_id, status | NetworkArchitect, RFEngineer, FieldTechnician |
| GET | /private-wireless/sites | Filtered list of Sites by enterprise_id, status, posture | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator, FieldTechnician |
| GET | /private-wireless/cells | Filtered list of CellSectors by site_id, status | NetworkArchitect, RFEngineer, SpectrumCoordinator, FieldTechnician |
| GET | /private-wireless/spectrum-leases | Filtered list of SpectrumLeases by enterprise_id, status, band_class | NetworkArchitect, RFEngineer, SpectrumCoordinator, SpectrumRegulator |
| GET | /private-wireless/sim-profiles | Filtered list of SIMProfiles by enterprise_id, status | NetworkArchitect, FieldTechnician |
## 5. Error Code Catalogue

The trigger condition for each error is defined in the narratives of §2 and §3 alongside the workflow it guards; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTY | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_INVALID_TIME_WINDOW | 400 |
| ERR_DUPLICATE_IDENTIFIER | 409 |
| ERR_CAPACITY_SHORTFALL | 422 |
| ERR_TARGET_CAPACITY_TOO_LOW | 422 |
| ERR_SURVEY_SIGNAL_TOO_WEAK | 422 |
| ERR_INTERFERENCE_MARGIN_EXCEEDED | 422 |
| ERR_SPECTRUM_OVERLAP | 409 |
| ERR_NO_ACTIVE_LEASE | 422 |
| ERR_ASSIGNMENT_OVERLAP | 409 |
| ERR_LEASE_BANDWIDTH_EXCEEDED | 422 |
| ERR_CONTRACT_OVERLAP | 409 |
| ERR_SLICE_BANDWIDTH_EXCEEDED | 422 |
| ERR_SLICE_DEVICE_CAP_EXCEEDED | 422 |
| ERR_URLLC_REQUIRES_EDGE | 422 |
| ERR_REMEDIATION_CELLS_MISSING | 422 |
| ERR_REMEDIATION_OPEN | 422 |
| ERR_CROSS_ENTERPRISE_REFERENCE | 422 |
| ERR_CHILDREN_ACTIVE | 422 |
| ERR_ENTERPRISE_CHILDREN_ACTIVE | 422 |
| ERR_STALE_SITE_VERSION | 412 |
| ERR_STALE_REQUEST_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
