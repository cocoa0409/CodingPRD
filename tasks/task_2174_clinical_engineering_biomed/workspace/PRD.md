# Clinical Engineering & Biomedical Equipment Management API — Product Requirements Document

## 1. Introduction

Hospital clinical engineering departments live at the intersection of patient safety, regulatory exposure and capital finance. A single infusion pump carries a maintenance calendar that a surveyor will audit, a cyber-security posture that a network team must attest to, a manufacturer recall history that a regulator may act on, and a book value that a capital committee will eventually retire. Today those four narratives are kept in four disconnected systems, and the department discovers their contradictions only when an inspector asks why a preventive-maintenance task was deferred three times on a device that was simultaneously under a Class I removal order.

This document specifies a single service that carries all four narratives on one inventory record. The service tracks equipment inventory and its risk classification, schedules and audits preventive maintenance against a regulatory completion-rate target, runs corrective work orders from intake through verified repair to a costed departmental charge, matches manufacturer recall and hazard alerts against live inventory, covers downed equipment from a loaner pool or an external rental, coordinates network-connected device security findings, and ranks the fleet for capital replacement by age, condition, maintenance burden and clinical risk.

Two design commitments shape everything that follows. First, **money and time are computed, never asserted** — every cost figure, compliance percentage and turnaround measurement in the system is derived by a rule stated in this document, and no client may supply one. Second, **safety states are independent of availability states** — a device's cyber posture evolves on its own axis from its operational availability, and the two dimensions interact only through the explicit cascades described in §2.8 and §3.8. The API is mounted under the `/clinical-engineering` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the service must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs. If both headers are present but the named role is not among the roles authorized for the endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows.

**`CEManager`** — the clinical-engineering manager. This role owns inventory registration, the money, capital planning, vendor contracts, recall governance and the facility posture. When `X-User-Role` is `CEManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `assigned_user_id` or `verified_by_user_id` on a work order, where a transition writes it) but never compares it to any entity's `id`.

**`BiomedTech`** — the in-house biomedical equipment technician who performs repairs and preventive maintenance. When `X-User-Role` is `BiomedTech`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is recorded on work orders and PM tasks (as `assigned_user_id`, `repaired_by_user_id`, `verified_by_user_id`, `completed_by_user_id` and `disposed_by_user_id`) but never resolved against an entity's `id`.

**`SecurityOfficer`** — the medical-device security coordinator, who owns the cyber dimension of the device state machine and the security-finding lifecycle. When `X-User-Role` is `SecurityOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it may be recorded on the resources the officer touches but is not compared to any entity's `id`.

**`DeptSteward`** — the clinical department representative who reports faults on its own department's equipment, may request loaner coverage and may cancel its own orders. When `X-User-Role` is `DeptSteward`, `X-User-ID` is the `id` of the acting `Department`; ownership checks on any resource that references a `Department` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `DeptSteward` may act on a device only when that device's `department_id` equals `X-User-ID`, and may read a department only when that department's own `id` equals `X-User-ID`. A violation is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

**`VendorRep`** — the external vendor service representative, who may complete repairs only on work orders assigned to its own vendor record. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's foreign-key field to `X-User-ID`. A `VendorRep` may therefore act on a work order only when that order's `vendor_id` equals `X-User-ID`, and on a service contract only when that contract's `vendor_id` equals `X-User-ID`. A violation is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

Ownership evaluation happens after authentication and role authorization and before any existence check on the URL path — see §2.11 for the complete ordering.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, must be at least 1, and must be at most 100. `offset` controls the starting position in the result set: it defaults to 0 and must be 0 or greater. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states a different ordering, list results are sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of records matching the filter before pagination was applied, and `has_more` indicating whether any records remain beyond the current page.

### 2.4. Record Identity, Timestamps and Versioning

Every resource in this system carries four common properties. The `id` is a server-minted UUID with no type prefix — clients never supply one. The `created_at` timestamp records when the row was first written, and `updated_at` records the most recent mutation; both are ISO 8601 UTC strings with three fractional-second digits. The `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row, whether the mutation was requested directly or caused by a cascade from another resource.

All twelve resource types — `Facility`, `Department`, `Vendor`, `DeviceModel`, `Device`, `PMTask`, `WorkOrder`, `LoanerAssignment`, `RecallNotice`, `RecallMatch`, `ServiceContract` and `SecurityFinding` — carry the full set: `id`, `created_at`, `updated_at` and `version`. There are no identity-only resources in this domain.

Fields whose values the system derives are never accepted from a client. Any request body that carries an unknown key, or that attempts to set a computed or system-maintained field, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Required fields that are absent, enum values outside their declared set, and integers outside their declared range all produce the same rejection.

### 2.5. The Logical Clock and Temporal Semantics

The service runs on a logical UTC clock rather than wall-clock time, so that maintenance windows, coverage intervals and rental durations can be exercised deterministically. At server start the clock reads `2026-08-01T00:00:00Z`, and it must not fall back to real wall-clock time before it has been explicitly set. A `CEManager` may advance or rewind it by supplying a `to_iso8601` instant; the endpoint answers with the resulting `current_utc`.

Every instant the server records reads from this clock: `reported_at`, `repair_started_at`, `repair_completed_at`, `closed_at`, `completed_at`, `discovered_at`, `resolved_at`, `returned_at`, `disposed_at` and `published_at` alike. Client-supplied instants — `window_start`, `window_end`, `new_window_start`, `new_window_end`, `start_at`, `end_at`, `coverage_start`, `coverage_end` and `response_due_at` — are taken at face value and are not adjusted against the clock. Wherever a duration must be measured, it is measured between two of these instants, never against the host operating system.

### 2.6. Cent Arithmetic, Percentages and Rounding Discipline

Every monetary field in the system is an integer count of whole cents, and every monetary field name ends in `_cents`. Percentages and hour figures that admit fractions — `pm_compliance_pct_strict`, `pm_compliance_pct_operational`, `pm_compliance_target_pct`, `replacement_priority_score`, `active_repair_hours` and `turnaround_hours` — are carried to exactly two decimal places.

Rounding throughout the service is **round half up**: a value exactly on the midpoint rounds away from zero, so a third decimal of 5 pushes the second decimal up, and an exact half-cent becomes a whole cent up. Where a formula in §3 pins the order in which rounding is applied — rounding each day of a rental separately before summing, or building a labour numerator in full before a single divide and a single rounding — that pinned order is normative and produces a different figure from any other order. Implementations must follow the stated order rather than an algebraically equivalent rearrangement.

### 2.7. Stale-Version Guards on Cross-Aggregate Writes

Two operations in this system write into an aggregate other than the one they address, and both are guarded by an optimistic-concurrency check against the parent's `version`.

Creating a loaner assignment requires a non-optional `expected_work_order_version` field carrying the client's last observed `version` of the covered `WorkOrder`. If that value does not equal the work order's current `version`, the creation is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412). A second loaner legitimately supersedes the coverage recorded by the first, so no state precondition blocks the write; the stale-version check is what makes the outcome deterministic, ensuring a client never records coverage against a work order whose state it has not observed.

Closing a work order requires a non-optional `expected_department_version` field carrying the client's last observed `version` of the charged `Department`. If that value does not equal the department's current `version`, the close is rejected with `ERR_STALE_DEPARTMENT_VERSION` (HTTP 412). The reason is fiscal rather than cosmetic: the overhead tier applied at close is keyed on the department's pre-debit spend, so a close computed against a superseded spend figure would charge the wrong overhead.

No other endpoint takes a version field. Requests to endpoints outside these two must not carry `expected_work_order_version` or `expected_department_version`, and supplying one is an unknown body key.

### 2.8. The Two State Dimensions of a Device

A `Device` row carries two independent state dimensions simultaneously. The **availability dimension**, `operational_state`, takes the values `IN_SERVICE`, `DOWN`, `ON_LOAN` and `RETIRED`; a new unit starts `IN_SERVICE`, and `RETIRED` is terminal. The **cyber dimension**, `security_state`, takes the values `UNASSESSED`, `ASSESSED_OK`, `VULNERABLE`, `QUARANTINED` and `REMEDIATED`; a new unit starts `UNASSESSED`, and no cyber state is terminal — the cycle `UNASSESSED` → … → `REMEDIATED` → `ASSESSED_OK` → `VULNERABLE` → … may repeat indefinitely.

The two dimensions evolve on separate axes. Moving a unit to `ASSESSED_OK`, to `VULNERABLE`, or from `VULNERABLE` to `REMEDIATED` leaves `operational_state` untouched. Only two cyber transitions reach across: a move into `QUARANTINED` forces an `IN_SERVICE` or `ON_LOAN` unit to `DOWN`, and a move into `REMEDIATED` from `QUARANTINED` restores a `DOWN` unit to `IN_SERVICE` — but only when nothing else is holding it down. Symmetrically, work-order and recall activity moves `operational_state` without ever changing `security_state`.

A third safety flag, `recall_hold`, sits beside both dimensions. It is `true` for as long as at least one recall match on the unit still carries a `PENDING` disposition, and it participates in restoration decisions and loaner eligibility without being a state in either machine.

### 2.9. Posture, Budget State and Operational Gating

Each `Facility` carries a clinical-engineering posture, `ce_posture`, with values `NORMAL`, `HEIGHTENED` and `LOCKDOWN`. New campuses open at `NORMAL`. The system escalates a `NORMAL` posture to `HEIGHTENED` automatically in three circumstances described in §3, but it never sets `LOCKDOWN` on its own — `LOCKDOWN` is reachable only through the explicit posture-setting capability, where a `CEManager` supplies `to_posture` and an optional `note`. While a facility is in `LOCKDOWN`, no work order on any of its devices may be assigned for repair; the attempt is rejected with `ERR_FACILITY_LOCKDOWN` (HTTP 409).

Each `Department` carries a fiscal gate. `downtime_budget_cents` is the annual ceiling set at creation and must be greater than zero; `downtime_spend_cents` accumulates the charges actually posted by work-order closes and starts at 0. From the two, the system derives `budget_state`: it is `ON_HOLD` when `downtime_spend_cents` has reached or passed `downtime_budget_cents`; otherwise it is `WARNING` when `downtime_spend_cents` multiplied by 100 has reached or passed `downtime_budget_cents` multiplied by 80 — that is, when spending stands at eighty percent of the ceiling or above; otherwise it is `OPEN`. A new department opens at `OPEN`.

A department in `ON_HOLD` may not open new corrective work orders and may not take on new loaner coverage; both attempts are rejected with `ERR_DEPARTMENT_BUDGET_ON_HOLD` (HTTP 402). Note the asymmetry that follows from this: repairs already under way continue to completion and closure, and a close still posts its charge even though the department has passed its ceiling.

### 2.10. Cascade Semantics and Conditional Restoration

Several operations in this system mutate more than one row. When they do, every touched row has its `updated_at` refreshed and its `version` incremented by 1 — the cascade target as much as the addressed resource. A client that holds a stale copy of a cascade target will therefore fail the guards in §2.7 on its next cross-aggregate write, which is the intended serialization point.

Restoring a downed unit is **conditional, never automatic**. Whenever a work-order close, a work-order cancellation, a recall disposition or a security resolution would return a unit from `DOWN` to `IN_SERVICE`, the restoration happens only when all three of the following hold: no other work order on that device is in `INTAKE`, `IN_REPAIR`, `AWAITING_PARTS`, `REPAIR_COMPLETE` or `VERIFIED`; the device's `recall_hold` is `false`; and the device's `security_state` is not `QUARANTINED`. If any of the three fails, the unit stays `DOWN` and only the addressed resource advances to its own terminal state. This is the single most consequential rule in the cascade set: an implementation that restores unconditionally will report the wrong availability after every overlapping fault.

### 2.11. Request Rejection Order

When more than one rule could reject a request, the rules are evaluated in a fixed order and the **first** failing rule alone decides the response. That order is:

1. Header presence — `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — `ERR_UNAUTHORIZED`.
3. Ownership for the entity-backed roles, `DeptSteward` and `VendorRep` — `ERR_OWNERSHIP_VIOLATION`. This check applies on every endpoint those two roles can reach.
4. Existence of every resource named in the URL path, validated left to right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`, `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404.
5. Request-body and query-parameter well-formedness — `ERR_INVALID_REQUEST`. This covers missing required fields, unknown body keys, client-supplied computed or system fields, enum values outside their declared sets, `function_code` outside 1 through 10, `physical_risk_code` outside 1 through 5, `maintenance_requirement_code` outside 1 through 5, `condition_score` outside 1 through 5, a `window_end` that is not strictly after `window_start`, an `end_at` that is not strictly after `start_at`, a `coverage_end` that is not strictly after `coverage_start`, a `limit` outside 1 through 100, and a negative `offset`. It applies to every write endpoint and to every list endpoint that takes pagination parameters.
6. Existence of every foreign key supplied in the request body — again the matching not-found code from the set `ERR_FACILITY_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND` and `ERR_SECURITY_FINDING_NOT_FOUND`. This step guards device creation, department creation, PM-task creation, work-order intake, loaner creation, recall-notice filing, service-contract creation and security-finding filing.
7. Facility code uniqueness on campus registration — `ERR_DUPLICATE_FACILITY_CODE`.
8. The stale-version guards of §2.7 — `ERR_STALE_WORK_ORDER_VERSION` on loaner creation and `ERR_STALE_DEPARTMENT_VERSION` on work-order close.
9. State legality — whether the target resource is in a state from which the requested transition is declared: `ERR_INVALID_WORK_ORDER_STATE`, `ERR_INVALID_PM_TASK_STATE`, `ERR_INVALID_RECALL_STATE`, `ERR_INVALID_LOANER_STATE`, `ERR_INVALID_SECURITY_STATE` or `ERR_INVALID_RECALL_MATCH_STATE`, each HTTP 409. This applies on every action endpoint.
10. Device retirement — `ERR_DEVICE_RETIRED` (HTTP 409) when the device addressed directly or through a child resource has `operational_state` equal to `RETIRED`. This guards work-order intake, PM-task creation, PM completion, loaner creation and device update.
11. Quarantine safety — `ERR_DEVICE_QUARANTINED` (HTTP 422) when the device under service is quarantined, and, on loaner creation, when the named loaner unit's `security_state` is `VULNERABLE` or `QUARANTINED`. This guards PM completion, loaner creation and work-order close.
12. Cyber-assessment safety — `ERR_SECURITY_FINDING_OPEN` (HTTP 422) when a move to `ASSESSED_OK` is attempted while some security finding on the device is `OPEN` or `REMEDIATION_SCHEDULED`. This guards the security-state capability.
13. Facility lockdown — `ERR_FACILITY_LOCKDOWN` on work-order assignment.
14. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) on work-order verification.
15. Loaner pool membership — `ERR_LOANER_NOT_IN_POOL` (HTTP 422) on loaner creation.
16. Loaner cyber eligibility — `ERR_LOANER_SECURITY_INELIGIBLE` (HTTP 422) on loaner creation.
17. Loaner availability — `ERR_LOANER_UNAVAILABLE` (HTTP 409) on loaner creation.
18. Loaner occupancy overlap — `ERR_LOANER_INTERVAL_CONFLICT` (HTTP 409) on loaner creation.
19. Contract coverage overlap — `ERR_CONTRACT_COVERAGE_OVERLAP` (HTTP 409) on service-contract creation.
20. PM window — `ERR_PM_OUTSIDE_WINDOW` (HTTP 422) on PM completion.
21. Deferral cap — `ERR_DEFERRAL_LIMIT_EXCEEDED` (HTTP 422) on PM deferral.
22. Pending recall matches — `ERR_RECALL_MATCHES_PENDING` (HTTP 409) on recall closure.
23. Empty loaner candidate set — `ERR_NO_LOANER_AVAILABLE` (HTTP 409) on loaner creation.
24. Vendor approval — `ERR_VENDOR_NOT_APPROVED` (HTTP 422) on work-order assignment.
25. Deployed loaner blocking closure — `ERR_INVALID_LOANER_STATE` (HTTP 409) on work-order close.
26. Departmental budget hold — `ERR_DEPARTMENT_BUDGET_ON_HOLD` (HTTP 402) on work-order intake and on loaner creation.

The consequences of this ordering are worth spelling out. On loaner creation, six loaner-specific checks fire in the sequence pool membership, cyber eligibility, availability, occupancy overlap, empty candidate set, budget hold — so a unit that is both outside the pool and already occupied reports `ERR_LOANER_NOT_IN_POOL`, not the interval conflict. On work-order close, the department stale-version guard precedes the state check, which precedes the quarantine check, which precedes the deployed-loaner check. And because ownership sits at position 3, a `DeptSteward` addressing another department's device is told about the ownership violation rather than about any business rule the request would also have broken.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Campus: Facilities, Departments, Vendors and the Catalogue

Before any equipment can be tracked, a `CEManager` registers the hospital campus itself. Registration takes a display `name`, a short campus code supplied as `facility_code`, and the regulatory PM completion-rate target expressed in percent as `pm_compliance_target_pct` — a value carried to two decimals and constrained to the range from 0.00 through 100.00 inclusive. The `facility_code` must be unique across every campus already registered and must be between 1 and 16 characters long; a collision is rejected with `ERR_DUPLICATE_FACILITY_CODE`. A newly registered campus opens with `ce_posture` set to `NORMAL`, `pm_audit_index` at 0, `open_class_i_recall_count` at 0, `departments_on_hold_count` at 0, `pm_compliance_pct_strict` at 0.00 and `pm_compliance_pct_operational` at 100.00. Those two starting compliance figures are deliberately asymmetric, and the audit epoch below explains why.

Clinical departments hang off the campus. Creating one takes the owning campus in `facility_id`, a `name`, a finance `cost_center_code` and the annual equipment-downtime ceiling `downtime_budget_cents`, which must be strictly greater than zero. The department opens with `downtime_spend_cents` at 0 and `budget_state` at `OPEN`. Departments can be listed and filtered by owning campus and by budget state; the department read is also how a manager obtains the `version` needed for the fiscal guard described in §2.7.

Service vendors are registered independently of any campus. A vendor record carries a legal `name`, a short `vendor_code`, the list labour rate per hour in `hourly_rate_cents`, and a flat trip charge in `travel_flat_cents` that is added exactly once to a vendor-performed repair. Both money figures must be zero or greater. Two optional booleans complete the record: `security_attestation_on_file`, recording whether the vendor holds a current medical-device security attestation, and `is_approved`, recording whether the vendor sits on the approved service list. Both default to a sensible starting position — the attestation flag to `false`, the approval flag to `true` — and the approval flag is consulted every time a repair is handed to that vendor.

The equipment catalogue is a separate registry from the inventory itself. A catalogue model records the `manufacturer`, the `model_number`, an equipment family label in `device_family` (a value such as `INFUSION_PUMP`), the manufacturer's expected useful life in whole years as `expected_life_years`, and the current like-for-like `replacement_cost_cents`; both of the latter must be strictly greater than zero. The optional `is_network_connected` flag, defaulting to `false`, declares that units of this model attach to the hospital network — a single boolean that will go on to raise every such unit's risk score, gate its eligibility as a loaner, and bring it into the security coordinator's remit.

### 3.2. Inventory Registration and Risk Classification

Adding a unit to inventory means naming where it lives, what it is, and how dangerous its failure would be. The registration payload carries the campus in `facility_id`, the owning clinical department in `department_id` — which is also the cost centre charged when a repair on this unit is closed — and the catalogue model in `device_model_id`. It carries the manufacturer's `serial_number`, an optional manufacturing `lot_number` used later for lot-scoped recall matching, the date the unit was placed in service as `acquisition_date` in `YYYY-MM-DD` form, and the capitalised `acquisition_cost_cents`, which must be zero or greater. Three integer weights describe the unit's clinical profile: `function_code`, the clinical-function weight, an integer from 1 through 10; `physical_risk_code`, the physical risk of a failure, an integer from 1 through 5; and `maintenance_requirement_code`, the maintenance burden, likewise an integer from 1 through 5. Three further optional inputs round out the record: `condition_score`, an integer from 1 through 5 where 1 is as-new and 5 is end of life, defaulting to 1; `utilization_hours`, the cumulative run hours, defaulting to 0; and `is_loaner_pool`, declaring the unit part of the loaner pool, defaulting to `false`. The unit is created with `operational_state` at `IN_SERVICE` and `security_state` at `UNASSESSED`.

**Risk classification** runs the instant a unit is registered, and again whenever any of `condition_score`, `utilization_hours` or `is_loaner_pool` is supplied on an update. It begins with age. The unit's age in whole days is the difference between the current logical-clock date and `acquisition_date`; its age in whole years is that day count divided by 365 and rounded down to a whole number. Two adders follow from that: a network adder of 4 points when the unit's catalogue model has `is_network_connected` set to `true`, and 0 points otherwise; and an age adder of 3 points when the unit is at least 8 years old, 1 point when it is at least 5 years old but less than 8, and 0 points otherwise. The `risk_score` is then the `function_code` multiplied by 2, plus the `physical_risk_code` multiplied by 3, plus the `maintenance_requirement_code` multiplied by 1, plus the network adder, plus the age adder. It is an exact integer.

The `risk_class` follows from the score by inclusive lower bounds: `CRITICAL` when `risk_score` is 34 or more, `HIGH` when it is 26 or more but below 34, `MEDIUM` when it is 16 or more but below 26, and `LOW` otherwise. The boundaries are inclusive on the lower side, so a score of exactly 26 is `HIGH` while 25 is `MEDIUM`. From the band comes the preventive-maintenance cadence `pm_interval_days`: 90 days for a `CRITICAL` unit, 180 days for a `HIGH` unit, 270 days for a `MEDIUM` unit, and 365 days for a `LOW` unit.

One consequence deserves emphasis. The score is **frozen at each write**. Advancing the logical clock does not re-age an untouched device; a unit that crossed its fifth anniversary yesterday keeps yesterday's `risk_score` until some write touches it. Only registration and update recompute the classification.

Updating a unit accepts exactly three mutable attributes — `condition_score`, `utilization_hours` and `is_loaner_pool` — and every supplied field re-runs both the risk classification and the capital-replacement score of §3.9, incrementing the device's `version` by 1. A unit whose `operational_state` is `RETIRED` may not be updated at all. Inventory can be listed and narrowed by `facility_id`, `department_id`, `device_model_id`, either state dimension via `operational_state` or `security_state`, by `risk_class`, or by `is_loaner_pool` membership. Beside the classification fields, each unit also exposes the running `lifetime_maintenance_cost_cents`, the capital-planning `replacement_priority_score`, `plan_rank` and `plan_funded`, and the `recall_hold` safety flag.

### 3.3. The Preventive Maintenance Calendar

A PM task is scheduled against one unit inside a window. Creation takes the `device_id`, a `window_start` and a `window_end`; the closing instant must be strictly after the opening one. The task is created with `status` at `SCHEDULED` and `deferral_count` at 0, and with **both** `due_at` and `original_due_at` set to `window_end`. That duplication is the heart of the compliance model: `due_at` tracks the current, possibly deferred deadline, while `original_due_at` is captured once at creation and is never rewritten by anything.

A `BiomedTech` records completion inside the window, supplying the outcome as `result` — one of `PASS`, `FAIL` or `PASS_WITH_DEFECT` — together with the technician minutes spent, as `labor_minutes`. Completion is accepted only from `SCHEDULED` or `DEFERRED`; a task that has already reached `COMPLETED` or `MISSED` is rejected with `ERR_INVALID_PM_TASK_STATE`. Three further guards apply, in the order of §2.11: the device must not be `RETIRED` (`ERR_DEVICE_RETIRED`), the device's `security_state` must not be `QUARANTINED` (`ERR_DEVICE_QUARANTINED`), and the logical clock must lie at or after `window_start` and at or before `window_end` of the task's **current** window — a completion attempt outside that closed interval is rejected with `ERR_PM_OUTSIDE_WINDOW`. On success the system records `completed_at` from the logical clock, `completed_by_user_id` from `X-User-ID` (an opaque operator identifier, not a foreign key), the supplied `result` and `labor_minutes`, and sets the task to `COMPLETED`. It then derives `on_time`, which is `true` when `completed_at` is at or before `original_due_at` — against the *original* deadline, never the deferred one.

The outcome branches. A `PASS` completion has no further effect. A `FAIL` completion takes the device to `DOWN` and automatically opens a follow-on corrective work order in `INTAKE` with `reported_severity` set to `CLINICAL_IMPACT` and `problem_summary` set to the text "PM failure on " followed by the unit's `serial_number`; that cascade-created order is returned by no create call and is discoverable only through the filtered work-order listing. A `PASS_WITH_DEFECT` completion leaves the device in service but ages it: `condition_score` becomes the smaller of 5 and its current value plus 1 — so a unit already at 5 stays at 5 — and the capital-replacement score of §3.9 is recomputed.

Deferral is a manager's decision, not a technician's. A `CEManager` pushes a task to a later window by supplying `new_window_start`, `new_window_end` and a `reason`; the new closing instant must be strictly after the new opening one. Deferral is accepted only from `SCHEDULED` or `DEFERRED` and only while `deferral_count` is below 2. On success, `window_start`, `window_end` and `due_at` are all rewritten to the new window, `original_due_at` is left exactly as it was, `deferral_count` increases by 1, and the task's `status` becomes `DEFERRED`. The transition `DEFERRED` → `DEFERRED` is a legitimate self-loop for the second deferral; a third attempt, made when `deferral_count` already stands at 2, is rejected with `ERR_DEFERRAL_LIMIT_EXCEEDED`. PM tasks can be read individually and listed filtered by `device_id` and by `status`.

#### The Audit Epoch: Measuring Compliance

Compliance is not measured continuously. It is measured in epochs, each triggered when a `CEManager` runs the campus PM audit, which is the **only** writer of `pm_compliance_pct_strict` and `pm_compliance_pct_operational`. An epoch runs four steps in a fixed order.

The first step is a **sweep**. Every PM task whose device belongs to this campus, whose `status` is `SCHEDULED` or `DEFERRED`, and whose `due_at` lies strictly before the current logical clock is moved to `MISSED`. Tasks are processed in ascending `due_at` order, and where two share a due instant, in ascending `created_at` order. Note that the sweep reads the *current* deadline: a task that has been deferred past the clock survives the sweep.

The second step is the **measurement**, and it keys on a different field. The measured window is every PM task whose device belongs to this campus and whose `original_due_at` is at or before the current clock — the original deadline, so deferring a task cannot remove it from the population that judges the campus. Within that window, the numerator is the count of tasks that are `COMPLETED` and whose `completed_at` is at or before their own `original_due_at`. Two denominators are then formed over the same window. The **strict** denominator counts every task whose `status` is `COMPLETED`, `MISSED` or `DEFERRED` — every deferral counts against the campus, which is what a regulator asks for. The **operational** denominator counts every task whose `status` is `COMPLETED` or `MISSED`, plus those tasks that are `DEFERRED` and whose `deferral_count` is 2 or more — a first, approved deferral is forgiven, which is what the internal operations dashboard shows. Tasks still `SCHEDULED` after the sweep appear in neither denominator.

The two rates diverge on the empty case as well as on the deferred population. `pm_compliance_pct_strict` is 0.00 when the strict denominator is zero, and otherwise 100 multiplied by the numerator divided by the strict denominator, rounded half up to two decimal places. `pm_compliance_pct_operational` is 100.00 when the operational denominator is zero, and otherwise 100 multiplied by the numerator divided by the operational denominator, rounded half up to two decimal places. A campus with no measurable history therefore reports a pessimistic regulatory figure and an optimistic operational one — precisely the asymmetry noted in §3.1.

The third step is **posture escalation**, and it is guarded by a non-empty denominator. When the strict denominator is greater than zero, and `pm_compliance_pct_strict` is strictly below the campus `pm_compliance_target_pct`, and `ce_posture` is currently `NORMAL`, the posture escalates to `HEIGHTENED`. A campus with an empty strict denominator never escalates on this path, however low the reported figure looks. A posture already at `HEIGHTENED` or `LOCKDOWN` is left alone.

The fourth step increments `pm_audit_index` by 1, giving every epoch a monotonic sequence number.

### 3.4. Corrective Work Orders: Intake, Assignment and the Two Repair Cycles

Faults enter the system as work orders. Intake is open to a `DeptSteward` (for its own department's equipment only), a `BiomedTech`, a `CEManager` or a `SecurityOfficer`, and takes the `device_id`, the clinical severity reported as `reported_severity` — one of `PATIENT_HARM`, `CLINICAL_IMPACT` or `ROUTINE` — a free-text `problem_summary`, and optionally an `origin_security_finding_id` when the order exists to remediate a cyber advisory. The order is created with `status` at `INTAKE`, `reported_at` read from the logical clock, `loaner_status` at `NONE`, and every cost, timing and counter field at its zero value: `active_repair_seconds` at 0, `active_repair_hours` at 0.00, `turnaround_hours` at 0.00, `labor_minutes` at 0, `parts_cost_cents` at 0, `estimated_cost_cents` at 0, `final_cost_cents` at 0, `department_charge_cents` at 0, `verify_fail_count` at 0, `sla_met` at `false`, `shift_multiplier_applied` at 1.0, and `vendor_id`, `service_contract_id`, `service_mode`, `assigned_user_id`, `repaired_by_user_id`, `verified_by_user_id`, `repair_started_at`, `repair_completed_at` and `closed_at` all null.

Intake takes the unit `DOWN`. It is accepted from `IN_SERVICE`, from `ON_LOAN` (a unit that is itself out on loan can still be reported faulty) and from `DOWN` (a second, concurrent fault on an already-downed unit); in all three cases the resulting `operational_state` is `DOWN`, and the device's `version` increases by 1. Only a `RETIRED` unit refuses intake, with `ERR_DEVICE_RETIRED`. A department already at `budget_state` `ON_HOLD` also refuses intake, with `ERR_DEPARTMENT_BUDGET_ON_HOLD`. When `origin_security_finding_id` is supplied, the referenced finding moves `OPEN` → `REMEDIATION_SCHEDULED` as part of the same request, and the resulting remediation order is discoverable afterwards only through the work-order listing filtered on that originating finding.

**Priority** is derived, never supplied. An order becomes `P1` when its `reported_severity` is `PATIENT_HARM` or the device's frozen `risk_class` is `CRITICAL`; failing that, it becomes `P2` when its `reported_severity` is `CLINICAL_IMPACT` or the device's `risk_class` is `HIGH`; otherwise it is `P3`. The `sla_hours` allowance follows directly from the band: 4 hours for `P1`, 24 hours for `P2`, 72 hours for `P3` — a `P3` order is given three full days of active repair time, a `P1` order barely half a shift. One later event overrides this derivation, and it is described in §3.6.

Assignment starts the repair. A `CEManager` or `BiomedTech` names the `service_mode` — either `IN_HOUSE` or `VENDOR` — and, for vendor work, the `vendor_id`. Three preconditions guard the move `INTAKE` → `IN_REPAIR`: the device's campus must not be in `LOCKDOWN` posture (`ERR_FACILITY_LOCKDOWN`), the device must not be `RETIRED`, and vendor-mode assignment must name an existing vendor whose `is_approved` is `true` (`ERR_VENDOR_NOT_APPROVED`). On success the system sets `repair_started_at` from the logical clock, records `assigned_user_id` from `X-User-ID` as an opaque identifier, stores the `service_mode` and `vendor_id`, opens the first active-repair segment at that instant, and increments the order's `version` by 1.

The instant of that first assignment does something else that lasts for the life of the order: it **pins the shift multiplier**. `shift_multiplier_applied` is set to 1.5 when the UTC hour of `repair_started_at` is before 7 or is 19 or later — that is, when the repair began outside the twelve-hour day shift running from 07:00 up to but not including 19:00 — and to 1.0 otherwise. The multiplier is pinned once, at the first assignment, and is never recomputed afterwards, no matter how many parts holds, resumptions or failed verifications the order goes through.

Two cycles are built into the repair lifecycle. The first is the **parts-hold loop**. Placing an order on hold moves it `IN_REPAIR` → `AWAITING_PARTS`, optionally recording a `note`; the open active-repair segment is closed and its elapsed seconds are added to `active_repair_seconds`. Resuming moves it `AWAITING_PARTS` → `IN_REPAIR` and opens a fresh segment at the logical clock. The loop may repeat any number of times, and the crucial property is that the `AWAITING_PARTS` spans are **excluded** from active repair time — a repair that waits three days for a part is not penalised for the wait.

Recording a repair pass moves the order `IN_REPAIR` → `REPAIR_COMPLETE`. Either a `BiomedTech` or, on a vendor-mode order, the `VendorRep` whose `X-User-ID` equals the order's `vendor_id`, supplies the `labor_minutes` and `parts_cost_cents` for the pass. These figures **accumulate**: each call adds its `labor_minutes` to the order's running total and its `parts_cost_cents` to the running parts spend, rather than replacing them. The open segment is closed and accumulated, `repaired_by_user_id` is set from `X-User-ID`, `repair_completed_at` is set from the logical clock, `estimated_cost_cents` is recomputed from the cumulative totals as described below, and the order's `version` increments by 1.

The **provisional cost** written at each repair pass is a list-rate figure that consults no contract. The hourly rate is 9,000 cents when `service_mode` is `IN_HOUSE`, and the vendor's own `hourly_rate_cents` when it is `VENDOR`. The labour term is computed in a pinned order: multiply the cumulative `labor_minutes` by that rate, multiply the product by `shift_multiplier_applied`, **then** divide by 60, **then** round half up to whole cents — exactly one rounding, applied at the end. Dividing by 60 first and rounding the intermediate product is a different rule and yields a different figure: 95 minutes at 18,500 cents per hour with a 1.5 multiplier gives the exact rational two million six hundred thirty-six thousand two hundred fifty divided by sixty, which is 43,937.5 cents and rounds half up to 43,938. For an in-house order, `estimated_cost_cents` is that labour figure plus the cumulative `parts_cost_cents`. For a vendor order, it is the labour figure plus the cumulative `parts_cost_cents` plus the vendor's `travel_flat_cents`, the flat trip charge being added exactly once regardless of how many passes the repair took.

The second cycle is the **verification loop**, and it enforces segregation of duties. A `BiomedTech` or `CEManager` verifies a `REPAIR_COMPLETE` order by supplying a `result` of `PASS` or `FAIL` and an optional `note`. The verifier's `X-User-ID` must differ from the order's `repaired_by_user_id`; if they match, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`, because the technician who performed a repair may not sign it off. A `PASS` moves the order `REPAIR_COMPLETE` → `VERIFIED` and records `verified_by_user_id` from `X-User-ID`. A `FAIL` sends the order back: `REPAIR_COMPLETE` → `IN_REPAIR`, `verify_fail_count` increases by 1, a new active-repair segment opens at the logical clock, and — as stated above — `shift_multiplier_applied` is *not* recomputed even though repair is resuming at a new hour of day. Either outcome increments the order's `version` by 1.

Cancellation is the escape hatch. A `CEManager` or `DeptSteward` may cancel an order from `INTAKE`, `IN_REPAIR` or `AWAITING_PARTS`, supplying a `reason`; the order moves to `CANCELLED` in every case with an identical effect set. No money moves: `final_cost_cents` and `department_charge_cents` stay 0, and the department's `downtime_spend_cents` is not touched at all — a compensating invariant that keeps the fiscal ledger consistent with the work actually performed. Every loaner assignment on the cancelled order that is still `DEPLOYED` moves to `CANCELLED` with `billable_days` 0 and `rental_cost_cents` 0, releasing any pool unit from `ON_LOAN` back to `IN_SERVICE`. `closed_at` is set from the logical clock, and the downed unit returns from `DOWN` to `IN_SERVICE` subject to the three conditional-restoration preconditions of §2.10. An order already `CLOSED` or `CANCELLED`, or one in `REPAIR_COMPLETE` or `VERIFIED`, cannot be cancelled and reports `ERR_INVALID_WORK_ORDER_STATE`.

Work orders can be read individually and listed with filters on `device_id`, `vendor_id`, `service_contract_id`, `origin_security_finding_id`, `status` and `priority`. That listing is the only discovery channel for orders the system creates by cascade — the follow-on order from a failed PM in particular.

### 3.5. Closure: Contract Selection, Final Cost and the Departmental Debit

Before closure can consult one, a service contract has to exist. A `CEManager` creates one against a single vendor and a single catalogue model, supplying the `vendor_id`, the `device_model_id`, the coverage interval as `coverage_start` and `coverage_end` — both instants **inclusive**, with the end strictly after the start — the `annual_premium_cents`, the flat per-event `deductible_cents` that will replace list-rate cost whenever the contract covers a repair, and the `covered_event_cap`, the maximum number of repairs the contract absorbs, which must be at least 1. Both money figures must be zero or greater. The contract opens with `status` `ACTIVE` and `covered_events_used` at 0. Coverage for a given vendor-and-model pair may not be double-booked: if any other `ACTIVE` contract on the same `vendor_id` and `device_model_id` already covers a closed interval that intersects the requested one, the creation is rejected with `ERR_CONTRACT_COVERAGE_OVERLAP`. Because both intervals are closed, two contracts that merely touch — one ending on the instant the next begins — **do** overlap, which is the opposite convention from loaner occupancy in §3.6. Contracts can be read individually and listed with filters on `vendor_id`, `device_model_id` and `status`.

Only a `CEManager` closes a work order, and only from `VERIFIED`. The close request carries exactly one field, `expected_department_version`, whose role as a stale-version guard is described in §2.7. Two further preconditions apply: the device under service must not be `QUARANTINED` (`ERR_DEVICE_QUARANTINED`), and no loaner assignment on this order may still be `DEPLOYED` — an outstanding loaner blocks closure with `ERR_INVALID_LOANER_STATE`, because the rental it may still be accruing has not been settled.

Closure runs contract selection first. The candidate set is every service contract whose `device_model_id` equals the model of the order's device, whose `vendor_id` equals the order's `vendor_id`, whose `status` is `ACTIVE`, whose inclusive coverage interval contains the order's `repair_started_at` — that is, `coverage_start` is at or before `repair_started_at` and `coverage_end` is at or after it — and whose `covered_events_used` is strictly less than its `covered_event_cap`. Candidates are ranked by ascending `deductible_cents`, then by ascending `coverage_end`, then by ascending `created_at`, and the first is selected. All three ranking keys are entity fields; the random `id` never participates in the decision. An empty candidate set is **not** an error: the order simply falls back to the list rate and its `service_contract_id` stays null.

The **final cost** is then computed. When the order was performed in `VENDOR` mode and a covering contract was selected, `final_cost_cents` is that contract's flat `deductible_cents` — the whole list-rate figure is replaced, not discounted — and the contract's `covered_events_used` increases by 1. A contract whose `covered_events_used` reaches its `covered_event_cap` auto-transitions `ACTIVE` → `EXHAUSTED` and leaves the candidate set for every later close. In every other case — in-house work, or vendor work with no covering contract — `final_cost_cents` is the list-rate figure recomputed identically from the cumulative `labor_minutes`, `parts_cost_cents`, pinned multiplier and rate card, so it equals `estimated_cost_cents`. A contract-covered order is therefore the one case where `final_cost_cents` and `estimated_cost_cents` differ for the same inputs, and both figures remain readable on the order.

The **departmental debit** follows, in three ordered steps that must not be iterated to a fixed point. Step one captures the department's `downtime_spend_cents` as it stands *before* this close. Step two keys the overhead tier on that pre-debit figure: the tier is T0 when the pre-debit spend multiplied by 100 is strictly less than `downtime_budget_cents` multiplied by 50; failing that it is T1 when the pre-debit spend multiplied by 100 is strictly less than `downtime_budget_cents` multiplied by 80; otherwise it is T2. The overhead rate is zero percent at T0, five percent at T1 and twelve percent at T2. In plain terms: a department under half its ceiling pays no overhead, one between half and four-fifths pays five percent, and one at four-fifths or beyond pays twelve. Step three assembles the charge: sum the `rental_cost_cents` of every loaner assignment on this order whose `status` is `RETURNED` — deployed ones have already blocked the close, and cancelled ones contribute nothing — then take `final_cost_cents` multiplied by one plus the overhead rate, round that half up to whole cents, and add the loaner total *after* the rounding. The result is `department_charge_cents`, and it is added to the department's `downtime_spend_cents`, whose new value is the pre-debit figure plus the charge. The department's `version` increments by 1.

That debit cascades twice more. The department's `budget_state` is re-derived from the **post**-debit spend by the rule in §2.9, so a close can move a department `OPEN` → `WARNING` or straight to `ON_HOLD`. When a department enters `ON_HOLD`, the campus `departments_on_hold_count` increments by 1; and when that count moves from 0 to 1 while `ce_posture` is `NORMAL`, the posture escalates to `HEIGHTENED`. A second department entering `ON_HOLD` raises the count again but changes nothing about a posture that is already `HEIGHTENED`.

Closure also settles the device and the clock. The device's `lifetime_maintenance_cost_cents` grows by this order's `final_cost_cents`, and its `replacement_priority_score` is recomputed on the new burden. The timing fields are finalised: `closed_at` is read from the logical clock; `active_repair_hours` is the total `active_repair_seconds` — the sum, in seconds, of every closed active-repair segment, `AWAITING_PARTS` spans excluded and each failed-verification segment included — divided by 3,600 and rounded half up to two decimal places, with the summation done in seconds and the rounding applied once at the end rather than per segment; `turnaround_hours` is the wall-clock span from `reported_at` to `closed_at` in seconds, divided by 3,600 and rounded half up to two decimal places; and `sla_met` is `true` exactly when `active_repair_hours` is less than or equal to `sla_hours`. Finally the unit returns from `DOWN` to `IN_SERVICE`, subject to the three conditional-restoration preconditions of §2.10 — and if the order being closed is a security remediation order, the originating finding moves `REMEDIATION_SCHEDULED` → `MITIGATED` with its `resolved_at` set. The order's own `version` increments by 1 and its `status` becomes `CLOSED`.

### 3.6. Loaner Coverage and Rental Billing

When a unit goes down, the clinical department still needs a machine. Coverage is recorded as a loaner assignment against the open work order, and it may come from the hospital's own pool or from an external rental. A `CEManager`, `BiomedTech` or `DeptSteward` creates one by supplying the `work_order_id`, the `source` — either `POOL` or `RENTAL` — the occupation interval as `start_at` and `end_at` (the end instant must be strictly after the start), the stale-version guard `expected_work_order_version` described in §2.7, and, optionally, an explicit `loaner_device_id`. The assignment is created with `status` `DEPLOYED`, `returned_at` null, `billable_days` 0 and `rental_cost_cents` 0, the covered order's `loaner_status` becomes `COVERED`, and the order's `version` increments by 1. A department at `budget_state` `ON_HOLD` may not take on loaner coverage at all, and is refused with `ERR_DEPARTMENT_BUDGET_ON_HOLD`.

Naming a unit explicitly subjects it to four checks in the order set out in §2.11. First, the named unit must have `is_loaner_pool` set to `true`, must sit at the same `facility_id` as the downed unit, and must be on the same `device_model_id`; and a `RENTAL`-sourced assignment must not name a `loaner_device_id` at all, since a rental unit is external and has no inventory row. Any of those failures yields `ERR_LOANER_NOT_IN_POOL`. Second, when the named unit's catalogue model has `is_network_connected` set to `true`, that unit's `security_state` must be `ASSESSED_OK` or `REMEDIATED`; anything else yields `ERR_LOANER_SECURITY_INELIGIBLE` — an unassessed networked pump does not go to a bedside as a substitute. Third, the named unit's `operational_state` must be `IN_SERVICE` and its `recall_hold` must be `false`, failing which the response is `ERR_LOANER_UNAVAILABLE`. Fourth, the requested occupancy must be free.

**Occupancy is half-open.** The requested interval runs from `start_at` up to but not including `end_at`, and each existing assignment on the same loaner unit whose `status` is `DEPLOYED` or `RETURNED` occupies the interval from its own `start_at` up to but not including its `returned_at` if it has one, or its `end_at` if it has not. Two intervals that merely touch — one ending exactly where the next begins — do **not** overlap. A genuine intersection is rejected with `ERR_LOANER_INTERVAL_CONFLICT`. Assignments that have been `CANCELLED` occupy nothing.

Omitting `loaner_device_id` on a `POOL` request asks the server to choose. The eligibility filter admits a unit only when all of the following hold: it sits at the same `facility_id` as the downed unit; it is on the same `device_model_id`; its `is_loaner_pool` is `true`; its `operational_state` is `IN_SERVICE`; its `recall_hold` is `false`; its `security_state` is neither `VULNERABLE` nor `QUARANTINED`; either its catalogue model is not network-connected or its `security_state` is `ASSESSED_OK` or `REMEDIATED`; it is not the downed unit itself; and its occupancy across the requested half-open interval is free by the rule just stated. Surviving candidates are ranked by ascending `condition_score`, then by ascending `utilization_hours`, then — as the final, exhaustive tie-break — by ascending `created_at`, compared at millisecond resolution. The first candidate is taken; the unit's random `id` never participates in the choice. When the filter admits nobody, the request is rejected with `ERR_NO_LOANER_AVAILABLE` — the hospital would rather be told it has no spare than be given an ineligible one. A `POOL` assignment, however selected, moves the lending unit `IN_SERVICE` → `ON_LOAN`.

Returning the loaner is where the money is computed. Return is accepted only from `DEPLOYED`; anything else reports `ERR_INVALID_LOANER_STATE`. The system stamps `returned_at` from the logical clock and derives `billable_days` as the elapsed seconds from `start_at` to `returned_at` divided by 86,400 and rounded **up** to a whole number, with a floor of 1 — any return, however prompt, bills at least one day. A `POOL` assignment costs nothing: its `rental_cost_cents` stays 0, because the pool consumes capacity rather than cash. The assignment moves to `RETURNED`, a `POOL` unit goes `ON_LOAN` → `IN_SERVICE`, restoring the pool's available-unit count, and the covered order's `loaner_status` stays `COVERED`.

A `RENTAL` return is priced day by day. The base daily charge is 24,333 cents. A risk surcharge is read from the **downed** unit's `risk_class`, never from the substitute's: twenty-five percent for a `CRITICAL` unit, fifteen percent for a `HIGH` unit, five percent for a `MEDIUM` unit and nothing for a `LOW` one. The total is then accumulated over the billable days in a pinned order: for each day, numbered 1 through `billable_days`, take the base daily charge multiplied by one plus the surcharge rate; if that day's number is greater than 7, multiply the result by one minus a long-term discount of ten percent; round that day's charge half up to whole cents; and add it to the running total. Rounding happens **per day, before summation** — summing the exact per-day rationals and rounding once at the end is the wrong order and produces a different cent figure. The accumulated total becomes `rental_cost_cents`, and it will be added to the department's charge when the covered order closes.

Loaner assignments also end without a return. When the covered work order is cancelled, or when the lending unit is taken down by a Class I recall match or by a quarantine, every `DEPLOYED` assignment involved moves `DEPLOYED` → `CANCELLED`; `billable_days` stays 0 and `rental_cost_cents` stays 0, so no money is conjured by a cancellation. A `POOL` unit released by a work-order cancellation goes `ON_LOAN` → `IN_SERVICE`. Crucially, the covered order's `loaner_status` becomes `UNCOVERED`, and when that order's `status` is still `INTAKE`, `IN_REPAIR` or `AWAITING_PARTS`, its `priority` is forced to `P1` and its `sla_hours` to 4 regardless of what the derivation in §3.4 originally produced — a department left with no substitute machine is now the most urgent repair in the shop. Assignments can be read individually and listed with filters on `loaner_device_id`, `work_order_id` and `status`.

### 3.7. Recall and Hazard Alert Governance

Recall notices are filed per campus, per catalogue model. A `CEManager` files one with the `facility_id` whose inventory is to be scanned, the `device_model_id` named by the alert, the issuing authority's `source_reference` (a string such as `FDA-2026-1188`), the `hazard_class` — `CLASS_I`, `CLASS_II` or `CLASS_III` — the regulatory `response_due_at` deadline, and optionally `affected_lot_numbers`, an array of lot identifiers that defaults to the empty array. The notice is created in `DRAFT` with `published_at` null, `matched_device_count` 0 and `pending_match_count` 0. Notices can be read individually and listed with filters on `facility_id`, `device_model_id` and `status`.

Publishing runs the inventory scan and is accepted only from `DRAFT`; a notice already past that point reports `ERR_INVALID_RECALL_STATE`. The scan considers every device at the notice's campus that is on the notice's exact model and whose `operational_state` is not `RETIRED`. When `affected_lot_numbers` is empty, **all** of those candidates match — an empty array means a whole-model recall, not a match-nothing recall — and each resulting match records a `match_basis` of `MODEL_ONLY`. When the array is non-empty, only candidates whose `lot_number` appears in it match, and each match records a `match_basis` of `MODEL_AND_LOT`. One `RecallMatch` row is created per matched unit, in candidate order by ascending `acquisition_date` and then by ascending `created_at`; each carries the `recall_notice_id` of the notice that produced it, the `device_id` of the matched unit, a `disposition` of `PENDING`, and null `disposed_at` and `disposed_by_user_id`. The notice's `matched_device_count` and `pending_match_count` are both set to the number of matches, and `published_at` is stamped from the logical clock.

The notice then **auto-branches on the same request**; it never rests in `PUBLISHED`. A `CLASS_I` notice takes the `PUBLISHED` → `MANDATORY_REMOVAL` branch, and its side-effect set is the heavy one. Every matched device has `recall_hold` set to `true`. Every matched device whose `operational_state` is `IN_SERVICE` or `ON_LOAN` is taken to `DOWN`, with its `version` incremented. Every `DEPLOYED` loaner assignment whose `loaner_device_id` is one of those newly downed units moves to `CANCELLED` with `billable_days` 0 and `rental_cost_cents` 0, and each such cancellation sets its own work order's `loaner_status` to `UNCOVERED` and escalates a still-open order to `P1` with `sla_hours` 4, exactly as described in §3.6. Every matched device that has a `SCHEDULED` PM task whose `deferral_count` is below 2 has that task moved `SCHEDULED` → `DEFERRED`, with `window_start`, `window_end` and `due_at` all shifted forward by 30 days, `original_due_at` left untouched, and `deferral_count` incremented by 1 — a unit under removal order cannot be maintained, but the compliance clock still remembers when it was originally due. The campus `open_class_i_recall_count` increases by 1, and `ce_posture` moves `NORMAL` → `HEIGHTENED`.

A `CLASS_II` or `CLASS_III` notice takes the `PUBLISHED` → `MONITORING` branch instead, and its side-effect set is deliberately disjoint. Every matched device has `recall_hold` set to `true`, and that is all: no matched device's `operational_state` changes, no loaner assignment is cancelled, no PM task is deferred, `open_class_i_recall_count` is not changed, and `ce_posture` is not changed. The same publish request, on the same inventory, therefore produces two very different worlds depending on one enum value.

Each match is then dispositioned individually by a `CEManager` or `BiomedTech`, who supplies a `disposition` of `REMOVED`, `REMEDIATED` or `EXEMPTED` and an optional `note`. Only a match still at `PENDING` may be dispositioned; one that already carries a terminal disposition reports `ERR_INVALID_RECALL_MATCH_STATE`. In every case `disposed_at` is stamped from the logical clock, `disposed_by_user_id` records the caller's opaque `X-User-ID`, and the notice's `pending_match_count` decreases by 1. A `REMOVED` disposition retires the unit: its `operational_state` becomes `RETIRED` from wherever it stood, and a retired unit is excluded from every future recall scan, from every loaner candidate set and from every replacement plan. A `REMEDIATED` or `EXEMPTED` disposition instead clears the unit's `recall_hold` — but only when this was its last `PENDING` match, since a unit may be matched by more than one notice — and then returns it from `DOWN` to `IN_SERVICE` subject to the three conditional-restoration preconditions of §2.10.

Closing the notice is the join point where both branches converge. A `CEManager` closes it from either `MANDATORY_REMOVAL` or `MONITORING`, and the close is refused with `ERR_RECALL_MATCHES_PENDING` while `pending_match_count` is greater than zero. On success the notice's `status` becomes `CLOSED`; a notice that came through the `MANDATORY_REMOVAL` branch also decrements the campus `open_class_i_recall_count` by 1, while one that came through `MONITORING` changes no campus counter. Matches can be read individually and listed with filters on `recall_notice_id`, `device_id` and `disposition`; that listing is the only discovery channel for the matches a publish creates.

### 3.8. Medical-Device Security Coordination

The `SecurityOfficer` owns the cyber dimension described in §2.8. Findings are filed against one unit with the `device_id`, a `severity` of `CRITICAL`, `HIGH`, `MEDIUM` or `LOW`, an `advisory_reference` naming the advisory or CVE, and an optional `requires_downtime` flag — defaulting to `false` — recording whether remediation will need the unit taken out of service. The finding is created with `status` `OPEN`, `discovered_at` from the logical clock, and null `resolution_note` and `resolved_at`. Its `remediation_due_at` is derived by adding whole days to `discovered_at` according to the severity band: 7 days for `CRITICAL`, 30 days for `HIGH`, 90 days for `MEDIUM` and 180 days for `LOW`.

Filing the finding may itself move the cyber dimension, keyed on the same severity band. A `CRITICAL` finding sets the device's `security_state` to `QUARANTINED` from whatever state it was in, and brings the full quarantine cascade with it. A `HIGH` finding sets the device's `security_state` to `VULNERABLE`, but only when it currently stands at `UNASSESSED` or `ASSESSED_OK`; a unit already `VULNERABLE`, `QUARANTINED` or `REMEDIATED` is left alone. A `MEDIUM` or `LOW` finding changes `security_state` not at all.

The officer may also drive the cyber dimension directly, supplying a `to_state` and an optional `note`. Seven transitions are declared, and any request for a pair not on this list is rejected with `ERR_INVALID_SECURITY_STATE`. From `UNASSESSED` the unit may move to `ASSESSED_OK` or to `VULNERABLE`. From `ASSESSED_OK` it may move to `VULNERABLE`, which removes it from the loaner candidate set from that instant on but leaves `operational_state` untouched. From `VULNERABLE` it may move to `QUARANTINED` or to `REMEDIATED`, the latter putting it back into the loaner candidate set. From `QUARANTINED` it may move to `REMEDIATED`. From `REMEDIATED` it may move to `ASSESSED_OK`, closing the cycle. Both moves into `ASSESSED_OK` — the one from `UNASSESSED` and the one from `REMEDIATED` — carry the same precondition: no finding on that device may be `OPEN` or `REMEDIATION_SCHEDULED`, or the attempt is rejected with `ERR_SECURITY_FINDING_OPEN`. Every accepted transition increments the device's `version` by 1.

The **quarantine cascade** is the heaviest cross-dimension effect in the system, and it fires identically whether quarantine arrives through a `CRITICAL` finding or through a direct move to `QUARANTINED`. A device whose `operational_state` is `IN_SERVICE` or `ON_LOAN` is taken to `DOWN`. Every `DEPLOYED` loaner assignment whose `loaner_device_id` is this unit moves to `CANCELLED` with `rental_cost_cents` 0 and `billable_days` 0. Each such cancellation sets its own work order's `loaner_status` to `UNCOVERED` and, when that work order's `status` is `INTAKE`, `IN_REPAIR` or `AWAITING_PARTS`, forces its `priority` to `P1` and its `sla_hours` to 4. The reverse move — into `REMEDIATED` from `QUARANTINED` — restores the unit from `DOWN` to `IN_SERVICE`, but only when no work order on it stands in `INTAKE`, `IN_REPAIR`, `AWAITING_PARTS`, `REPAIR_COMPLETE` or `VERIFIED` and its `recall_hold` is `false`.

Findings are closed out by a `SecurityOfficer` or `CEManager`, who supplies a `resolution` of `MITIGATED` or `ACCEPTED_RISK` and an optional `note` recorded as the finding's `resolution_note`. Resolution is accepted from `OPEN` or from `REMEDIATION_SCHEDULED`; a finding already at `MITIGATED` or `ACCEPTED_RISK` is terminal. A `MITIGATED` resolution stamps `resolved_at`, sets the finding's `status` to `MITIGATED`, moves a device that this finding had quarantined `QUARANTINED` → `REMEDIATED`, and restores that device from `DOWN` to `IN_SERVICE` when nothing else holds it down — no non-terminal work order and no recall hold. An `ACCEPTED_RISK` resolution stamps `resolved_at` and sets the finding's `status` to `ACCEPTED_RISK`, but leaves `security_state` exactly as it was: an accepted risk leaves a quarantined unit quarantined, and therefore leaves it `DOWN`. The other path to `MITIGATED` runs through the repair shop — closing a remediation work order whose `origin_security_finding_id` names the finding moves it `REMEDIATION_SCHEDULED` → `MITIGATED` with the same device consequences. Findings can be read individually and listed with filters on `device_id`, `status` and `severity`.

### 3.9. Capital Replacement Planning

Every unit carries a `replacement_priority_score`, a two-decimal figure between 0.00 and 100.00 that ranks it for capital replacement. It is recomputed at five moments: when a unit is registered, when a unit is updated, when a work order on it is closed, when a PM on it completes with `PASS_WITH_DEFECT`, and on every replacement-plan read.

The score blends four factors. The **age factor** is the unit's age in whole years — the whole-day difference between the current logical-clock date and `acquisition_date`, divided by 365 and rounded down — divided by the catalogue model's `expected_life_years`, capped at 1.0, so a unit past its expected life contributes a full share and no more. The **condition factor** is `condition_score` minus 1, divided by 4, so an as-new unit contributes 0 and an end-of-life unit contributes 1. The **burden factor** is the unit's `lifetime_maintenance_cost_cents` divided by the model's `replacement_cost_cents`, capped at 1.0 — a unit that has cost more in repairs than a new one would cost contributes a full share. The **risk weight** is read from the frozen `risk_class`: 1.0 for `CRITICAL`, 0.75 for `HIGH`, 0.5 for `MEDIUM` and 0.25 for `LOW`. The score is 100 multiplied by the sum of the age factor times 0.35, the condition factor times 0.30, the burden factor times 0.20 and the risk weight times 0.15, rounded half up to two decimal places — so a third decimal of exactly 5 rounds the second decimal up. The `lifetime_maintenance_cost_cents` used here is the persisted running total of `final_cost_cents` over the unit's closed work orders; it is never recomputed from scratch at scoring time.

The plan itself is a `CEManager` read over one campus. It returns every device at that campus whose `operational_state` is not `RETIRED`, ranked by descending `replacement_priority_score`, then by ascending `acquisition_date`, then by ascending `created_at`, and it recomputes each returned unit's score against the current logical clock before ranking. Each returned unit's `plan_rank` is written as its 1-based position in that ranking — a device that has never appeared in a plan read carries `plan_rank` 0. The read accepts `limit` and `offset` for paging as well.

Supplying `fiscal_budget_cents` turns the read into a funding waterfall. Starting from the full budget, the ranked units are walked in order; for each, the cost considered is that unit's catalogue model `replacement_cost_cents`. When that cost is less than or equal to the remaining budget, the unit's `plan_funded` is set to `true` and the cost is subtracted from the remaining budget. When it is greater, the unit's `plan_funded` is set to `false` and the walk **continues to the next unit** — it does not stop at the first miss, so a cheap low-priority unit can be funded after an expensive high-priority one was skipped. The comparison is inclusive: a unit costing exactly the remaining budget is funded. When `fiscal_budget_cents` is omitted, every returned unit keeps `plan_funded` at `false`. Both `plan_rank` and `plan_funded` are **persisted** on the device rows by this read, so the plan is not a transient projection but a recorded decision.

## 4. Endpoint Definitions

All endpoints are mounted under the `/clinical-engineering` prefix. Creating a new resource answers with HTTP 201; every other successful call — reads, updates and state-machine actions alike — answers with HTTP 200. Successful responses carry the affected resource in `data`, wrapped in the envelope of §2.2. The table below fixes only the HTTP contract and the authorized roles; the request payload, the response effects and the rules that govern each call are given in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clinical-engineering/facilities` | Register a hospital campus under clinical-engineering management | `CEManager` |
| GET | `/clinical-engineering/facilities/{id}` | Read one facility including both PM compliance variants and the current posture | `CEManager`, `BiomedTech`, `SecurityOfficer`, `DeptSteward`, `VendorRep` |
| POST | `/clinical-engineering/facilities/{id}/posture` | Set the clinical-engineering posture manually; LOCKDOWN is reachable only here | `CEManager` |
| POST | `/clinical-engineering/facilities/{id}/pm-audit` | Run the PM compliance audit epoch: sweep overdue PM tasks to MISSED, recompute both compliance variants, escalate posture, advance pm_audit_index | `CEManager` |
| GET | `/clinical-engineering/facilities/{id}/replacement-plan` | Capital replacement plan: non-retired devices ranked by replacement_priority_score DESC, acquisition_date ASC, created_at ASC. Supplying fiscal_budget_cents runs the skip-and-continue waterfall and persists plan_rank / plan_funded on every returned device. | `CEManager` |
| POST | `/clinical-engineering/departments` | Create a clinical department with its downtime budget | `CEManager` |
| GET | `/clinical-engineering/departments/{id}` | Read one department, including the version needed for the close OCC check | `CEManager`, `DeptSteward`, `BiomedTech` |
| GET | `/clinical-engineering/departments` | List departments, filterable by owning facility and budget state | `CEManager`, `DeptSteward`, `BiomedTech` |
| POST | `/clinical-engineering/vendors` | Register a service vendor and its rate card | `CEManager` |
| GET | `/clinical-engineering/vendors/{id}` | Read one vendor | `CEManager`, `BiomedTech`, `VendorRep` |
| POST | `/clinical-engineering/device-models` | Register a catalogue model, including whether its units attach to the hospital network | `CEManager` |
| GET | `/clinical-engineering/device-models/{id}` | Read one catalogue model | `CEManager`, `BiomedTech`, `SecurityOfficer` |
| POST | `/clinical-engineering/devices` | Add a unit to inventory; risk classification runs on creation | `CEManager` |
| GET | `/clinical-engineering/devices/{id}` | Read one unit, including both state dimensions and the capital-planning fields | `CEManager`, `BiomedTech`, `SecurityOfficer`, `DeptSteward` |
| GET | `/clinical-engineering/devices` | List inventory filtered by facility, department, model, either state dimension, risk band or loaner-pool membership | `CEManager`, `BiomedTech`, `SecurityOfficer`, `DeptSteward` |
| PATCH | `/clinical-engineering/devices/{id}` | Update the mutable inventory attributes of a unit; every supplied field re-runs risk classification and the replacement score | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/devices/{id}/security-state` | Drive the cyber dimension of the device state machine; operational_state is only touched by the QUARANTINED and REMEDIATED transitions | `SecurityOfficer` |
| POST | `/clinical-engineering/pm-tasks` | Schedule a preventive-maintenance task in a window; due_at and original_due_at are both set to window_end | `CEManager`, `BiomedTech` |
| GET | `/clinical-engineering/pm-tasks/{id}` | Read one PM task | `CEManager`, `BiomedTech` |
| GET | `/clinical-engineering/pm-tasks` | List PM tasks filtered by device and status | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/pm-tasks/{id}/complete` | Record PM completion inside the current window | `BiomedTech` |
| POST | `/clinical-engineering/pm-tasks/{id}/defer` | Push a PM task to a later window; original_due_at is preserved so the compliance denominator still sees it | `CEManager` |
| POST | `/clinical-engineering/work-orders` | Intake a corrective work order against a unit; the unit goes DOWN | `DeptSteward`, `BiomedTech`, `CEManager`, `SecurityOfficer` |
| GET | `/clinical-engineering/work-orders/{id}` | Read one work order including every cost and turnaround field | `CEManager`, `BiomedTech`, `DeptSteward`, `VendorRep`, `SecurityOfficer` |
| GET | `/clinical-engineering/work-orders` | List work orders filtered by device, vendor, selected contract, originating security finding, status or priority. This is the only discovery channel for cascade-created work orders. | `CEManager`, `BiomedTech`, `DeptSteward`, `VendorRep`, `SecurityOfficer` |
| POST | `/clinical-engineering/work-orders/{id}/assign` | Assign the order to in-house engineering or to a vendor and start the first active-repair segment | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/work-orders/{id}/parts-hold` | Suspend the repair pending parts; the AWAITING_PARTS span is excluded from active repair time | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/work-orders/{id}/resume` | Resume a held repair and open a new active-repair segment | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/work-orders/{id}/complete-repair` | Record labour and parts for the current repair pass; values ACCUMULATE across repeated calls | `BiomedTech`, `VendorRep` |
| POST | `/clinical-engineering/work-orders/{id}/verify` | Quality-verify the repair. The verifier may not be the technician who performed it. | `BiomedTech`, `CEManager` |
| POST | `/clinical-engineering/work-orders/{id}/close` | Close the order: select a service contract, compute the final cost, debit the department under the pre-debit overhead tier, and cascade the budget state to the facility posture | `CEManager` |
| POST | `/clinical-engineering/work-orders/{id}/cancel` | Cancel a non-terminal order; no money moves and every deployed loaner is released | `CEManager`, `DeptSteward` |
| POST | `/clinical-engineering/loaner-assignments` | Cover a downed unit from the loaner pool or with an external rental. Omitting loaner_device_id with source == POOL asks the server to select from the pool by the pinned eligibility filter and ranking. | `CEManager`, `BiomedTech`, `DeptSteward` |
| GET | `/clinical-engineering/loaner-assignments/{id}` | Read one loaner assignment | `CEManager`, `BiomedTech`, `DeptSteward` |
| GET | `/clinical-engineering/loaner-assignments` | List loaner assignments filtered by loaner unit, covered work order or status | `CEManager`, `BiomedTech`, `DeptSteward` |
| POST | `/clinical-engineering/loaner-assignments/{id}/return` | Return the loaner; billable_days and rental_cost_cents are computed here | `CEManager`, `BiomedTech`, `DeptSteward` |
| POST | `/clinical-engineering/recall-notices` | File a recall / hazard alert against a catalogue model for one campus | `CEManager` |
| GET | `/clinical-engineering/recall-notices/{id}` | Read one recall notice including its match counts | `CEManager`, `BiomedTech` |
| GET | `/clinical-engineering/recall-notices` | List recall notices filtered by facility, model or status | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/recall-notices/{id}/publish` | Publish the notice: scan inventory, create one RecallMatch per matched unit, then auto-branch on hazard_class | `CEManager` |
| POST | `/clinical-engineering/recall-notices/{id}/close` | Close a recall once every match has a terminal disposition | `CEManager` |
| GET | `/clinical-engineering/recall-matches/{id}` | Read one recall match | `CEManager`, `BiomedTech` |
| GET | `/clinical-engineering/recall-matches` | List recall matches filtered by notice, device or disposition. Cascade-created matches are discoverable only here. | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/recall-matches/{id}/disposition` | Record the per-unit recall disposition | `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/service-contracts` | Create a vendor service contract for one model with an inclusive coverage interval | `CEManager` |
| GET | `/clinical-engineering/service-contracts/{id}` | Read one service contract | `CEManager`, `VendorRep` |
| GET | `/clinical-engineering/service-contracts` | List service contracts filtered by vendor, model or status | `CEManager`, `VendorRep` |
| POST | `/clinical-engineering/security-findings` | File a cyber advisory against a unit; CRITICAL quarantines it immediately | `SecurityOfficer` |
| GET | `/clinical-engineering/security-findings/{id}` | Read one security finding | `SecurityOfficer`, `CEManager`, `BiomedTech` |
| GET | `/clinical-engineering/security-findings` | List security findings filtered by device, status or severity | `SecurityOfficer`, `CEManager`, `BiomedTech` |
| POST | `/clinical-engineering/security-findings/{id}/resolve` | Close a finding as remediated or as an accepted risk | `SecurityOfficer`, `CEManager` |
| POST | `/clinical-engineering/_clock/set_current_utc` | Set the server's logical UTC clock. The clock defaults to 2026-08-01T00:00:00Z at server start and MUST NOT fall back to real wall-clock time before this endpoint is first called. | `CEManager` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_DEVICE_MODEL_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_PM_TASK_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_LOANER_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_RECALL_NOTICE_NOT_FOUND` | 404 |
| `ERR_RECALL_MATCH_NOT_FOUND` | 404 |
| `ERR_SERVICE_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SECURITY_FINDING_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_FACILITY_CODE` | 409 |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 |
| `ERR_STALE_DEPARTMENT_VERSION` | 412 |
| `ERR_INVALID_WORK_ORDER_STATE` | 409 |
| `ERR_INVALID_PM_TASK_STATE` | 409 |
| `ERR_INVALID_RECALL_STATE` | 409 |
| `ERR_INVALID_RECALL_MATCH_STATE` | 409 |
| `ERR_INVALID_LOANER_STATE` | 409 |
| `ERR_INVALID_SECURITY_STATE` | 409 |
| `ERR_DEVICE_RETIRED` | 409 |
| `ERR_DEVICE_QUARANTINED` | 422 |
| `ERR_SECURITY_FINDING_OPEN` | 422 |
| `ERR_FACILITY_LOCKDOWN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LOANER_NOT_IN_POOL` | 422 |
| `ERR_LOANER_SECURITY_INELIGIBLE` | 422 |
| `ERR_LOANER_UNAVAILABLE` | 409 |
| `ERR_LOANER_INTERVAL_CONFLICT` | 409 |
| `ERR_NO_LOANER_AVAILABLE` | 409 |
| `ERR_CONTRACT_COVERAGE_OVERLAP` | 409 |
| `ERR_PM_OUTSIDE_WINDOW` | 422 |
| `ERR_DEFERRAL_LIMIT_EXCEEDED` | 422 |
| `ERR_RECALL_MATCHES_PENDING` | 409 |
| `ERR_VENDOR_NOT_APPROVED` | 422 |
| `ERR_DEPARTMENT_BUDGET_ON_HOLD` | 402 |

