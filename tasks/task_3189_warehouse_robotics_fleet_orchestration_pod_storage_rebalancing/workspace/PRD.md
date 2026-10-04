# Warehouse Robotics Fleet Orchestration & Pod Storage Rebalancing API — Product Requirements Document

## 1. Introduction

Modern fulfillment centers built on mobile-robot goods-to-person architectures face a compounding coordination problem: a fleet of drive units must ferry storage pods to human pick stations, chargers must be rationed against dispatch demand, inbound inventory must be scattered across pods with an eye to both density and ergonomics, and every one of those flows shares the same gridded floor — a floor that can be suddenly compromised by dropped debris, blocked aisles, or a stranded robot. Layered on top are the realities of shift labor planning against order cutoffs, and a software pipeline whose every release must clear safety validation before it is allowed to move a single physical robot.

This document specifies the Warehouse Robotics Fleet Orchestration API, mounted under `/fleet`, the control plane through which operators register floor topology, drive pick and stow work through its lifecycle, manage charging and maintenance of the drive fleet, handle floor exceptions under strict human-entry safety protocol, plan shift throughput, and govern software promotion. The API is the single source of truth for robot status, pod reservations, station queues, inventory accounting, and release safety state. Because multiple control loops (sequencing, dispatch, exception response, clock-driven cascades) act on the same entities, the API leans on optimistic concurrency for queue- and SKU-mutating writes, and on explicit segregation-of-duties rules wherever a safety decision could otherwise be self-approved.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the calling operator, and `X-User-Role` declares the role under which the operator is acting. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint per the authorization matrix is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are exactly: `FleetAdmin`, `FlowController`, `StationOperator`, `FloorSupervisor`, `SafetyOfficer`, `MaintenanceTech`, and `ReleaseEngineer`.

- A `FleetAdmin` owns fleet configuration: zones, drive units, chargers, pods, SKUs, pick stations, shift plans, and software promotion and rollback.
- A `FlowController` orchestrates work: customer orders, pick tasks, stow tasks, charging sessions, station pause and reopen, and may also report floor exceptions.
- A `StationOperator` works at a pick station: beginning and completing picks and confirming stows.
- A `FloorSupervisor` reports, triages, and resolves floor exceptions and requests human-entry permits.
- A `SafetyOfficer` grants and releases human-entry permits and records software validation outcomes; this role is deliberately segregated from `FloorSupervisor` and `ReleaseEngineer`.
- A `MaintenanceTech` schedules, completes, and cancels maintenance windows.
- A `ReleaseEngineer` authors software releases and drives the validation loop.

For every role, `X-User-ID` is an **opaque** operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution — notably the triage attribution on a `FloorException` and the validation-initiation attribution on a `SoftwareRelease`, both of which feed segregation-of-duties comparisons — but never compares it to any entity's `id` for ownership purposes. Segregation-of-duties checks compare the acting `X-User-ID` against the recorded `X-User-ID` of the earlier step (see §2.9 and §3.6).

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and must not exceed 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending.

### 2.4. Logical Clock and Time-Driven Cascades

The system maintains a **logical clock** rather than wall-clock time. Before any clock-driving call, the logical clock reads exactly `2026-09-01T00:00:00Z` and must never fall back to real wall-clock time. A `FleetAdmin` may advance the clock to an arbitrary ISO 8601 UTC instant by supplying `to_iso8601` to the clock-driving capability (see §4), and the response echoes the resulting `current_utc`. Advancing the clock re-evaluates every time-driven cascade in one sweep: maintenance windows whose half-open interval has been entered activate, orders whose `cutoff_at` has been strictly passed transition to `CUTOFF_MISSED`, and human-entry permits whose `ends_at` has been reached become eligible for release.

Two interval conventions coexist and must not be confused. `MaintenanceWindow.starts_at` and `MaintenanceWindow.ends_at` describe a **half-open** interval — the start is inclusive, the end is exclusive, and `ends_at` must be strictly greater than `starts_at`. `HumanEntryPermit.starts_at` and `HumanEntryPermit.ends_at` describe a **closed** interval — both endpoints inclusive — and `ends_at` must be greater than or equal to `starts_at`. An order still in `RECEIVED` whose `cutoff_at` equals the current logical clock exactly is **not** yet missed; only a clock strictly later than `cutoff_at` triggers `CUTOFF_MISSED`.

### 2.5. Common Resource Properties

Every resource carries an `id` (a server-minted UUID with no type prefix), a `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and an integer `version` starting at 1. Every mutation of a resource increments its `version` by exactly 1 and refreshes `updated_at`; this includes implicit mutations such as the firmware bump applied to every drive unit during release promotion. All entities in this system carry the full common-field set.

### 2.6. Validation Pipeline and Priority Ordering

Requests are validated in a fixed priority order, and the first failing check determines the error returned. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` headers present and the role recognized (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization** — the role is permitted for the endpoint (`ERR_FORBIDDEN`, 403).
3. **Path existence** — every path-templated identifier resolves to an existing entity, evaluated left to right (`ERR_NOT_FOUND`, 404).
4. **Body reference existence** — every body-referenced foreign key (`pod_id`, `sku_id`, `station_id`, `zone_id`, `exception_id`, `charger_id`, `drive_unit_id`, `line_id`, `order_id`) resolves (`ERR_NOT_FOUND`, 404).
5. **State legality** — the target entity is in a status from which the requested transition is defined (`ERR_INVALID_STATE`, 409).
6. **Safety interlocks** — no FROZEN-zone entry, open-exception gating, stranded-robot, or segregation-of-duties violation (`ERR_SAFETY_INTERLOCK`, 422); applies to granting a human-entry permit, promoting a software release, and resolving a floor exception.
7. **Referential shape** — a pick task's line must belong to its order; a human-entry permit's exception must be `TRIAGED_HUMAN`; a floor exception must carry `drive_unit_id` exactly when `kind` is `STRANDED_ROBOT` (`ERR_REFERENTIAL_MISMATCH`, 422); applies to creating pick tasks, human-entry permits, and floor exceptions.
8. **Temporal validity** — interval endpoints valid per §2.4, and a new maintenance window must leave at least 15 minutes of gap to any existing non-cancelled window for the same unit under half-open semantics (adjacency with an exactly 15-minute gap is allowed) (`ERR_TEMPORAL_CONFLICT`, 422); applies to creating maintenance windows, human-entry permits, and charging sessions.
9. **Capacity** — station queue length below `max_queue` on sequencing; charger `slots_in_use` below `slot_count` on session open; pod capacity for a new slot; zone `ACTIVE` permit count below `max_human_occupancy` (`ERR_CAPACITY_EXCEEDED`, 422); applies to sequencing a pick task, opening a charging session, placing a stow task, and granting a permit.
10. **Inventory availability** — available units (on-hand minus reserved) cover the requested quantity (`ERR_INSUFFICIENT_INVENTORY`, 422); applies to creating and sequencing pick tasks.
11. **Optimistic concurrency** — `expected_<parent>_version` matches the parent's current `version` (`ERR_STALE_VERSION`, 412); applies to sequencing a pick task and placing a stow task.

Generic request-shape failures — a missing required field, a bad enum value, a type mismatch, or a negative quantity — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Two write operations are OCC-guarded. A request to sequence a pick task into a station queue must carry `expected_station_version` equal to the station's current `version`; if another sequencing decision has advanced the station's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the queue snapshot the client used to pick the station is stale. A request to place a stow task must carry `expected_sku_version` equal to the SKU's current `version`; placement decisions depend on the current on-hand and reserved counters, so a stale view is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.8. Numeric Precision

Monetary-style computed quantities in this system are travel costs and placement scores. All travel-cost figures (`est_cost`, `actual_cost`, and the battery/odometer adjustments derived from them) are computed to 2 decimal places with round-half-up rounding. Stow placement scores are computed to 4 decimal places with round-half-up rounding. Charge credits are computed as whole percentage points, with round-half-up applied **per tier before summation** — summing first and rounding once is forbidden. Throughput projections and sequence indices are whole integers. No approximation language in this document implies tolerance: every threshold and boundary is exact.

### 2.9. Safety Posture, Human Entry, and Segregation of Duties

Each `FloorZone` has a derived `posture` gating robot traffic: `OPEN` means robots may enter and traverse; `RESTRICTED` means robots already inside must park and no new entries are permitted; `FROZEN` means all motion is forbidden because a human-entry permit is active. Posture changes cascade immediately to the drive units homed in the zone (§3.5).

Two workflows are guarded by segregation of duties. Granting a human-entry permit requires that the acting `SafetyOfficer`'s `X-User-ID` differ from the `X-User-ID` of the `FloorSupervisor` who triaged the governing exception. Recording a passing validation outcome on a software release requires that the acting `SafetyOfficer`'s `X-User-ID` differ from the `X-User-ID` of the `ReleaseEngineer` who initiated validation. Violations are rejected with `ERR_SAFETY_INTERLOCK` (HTTP 422).

### 2.10. Nested Resource Retrieval

Nested list endpoints resolve their path parameters left to right: each path-templated identifier is validated for existence before the next is considered, and the first unresolvable identifier yields `ERR_NOT_FOUND`. Reverse-reachability listings exist for the chargers, pods, pick stations, and human-entry permits of a zone; the charging sessions of a charger; the inventory slots of a pod; the inventory slots and order lines of a SKU; the pick tasks of a station; and the lines and pick tasks of an order.

## 3. Business Logic & Workflows

### 3.1. Floor Topology: Zones, Chargers, Pods, and Stations

A `FleetAdmin` begins by carving the floor into `FloorZone`s. A zone is created with a unique human-readable `zone_code` (immutable after creation), its grid origin `grid_x` and `grid_y` in cells (each at least 0), its `width` and `height` in cells (each at least 1), and a `max_human_occupancy` (at least 1) bounding how many `ACTIVE` human-entry permits may cover it simultaneously. New zones are born with `posture` `OPEN`. Manhattan distances used throughout this document are computed between zone grid origins — between the pod's zone and the station's zone for travel cost, and between a unit's home zone and the pod's zone for fleet selection.

Chargers, pods, and pick stations are registered into zones. A `Charger` is created with its `zone_id` and a `slot_count` of at least 1, and tracks `slots_in_use` — the count of `OPEN` charging sessions on it, recomputed on every session open and close. A `Pod` is created with a unique immutable `pod_code`, its `zone_id`, and a `slot_capacity` of at least 1; its derived `slots_used` counts the `InventorySlot` rows with `quantity` greater than 0 on the pod, and its `status` begins `IN_STORAGE`. A `PickStation` is created with a unique immutable `station_code`, the `zone_id` whose approach lane it attaches to, and a `max_queue` of at least 1; its derived `queue_length` counts its pick tasks in `QUEUED` or `DELIVERED`, and its `status` begins `OPEN`. A `FlowController` may pause an `OPEN` station (status becomes `PAUSED`, station `version` increments) and later reopen it (status returns to `OPEN`); `CLOSED` is terminal for the shift.

Drive units are registered with a unique immutable `unit_code` and a `home_zone_id`. A unit is born `ACTIVE` with `battery_pct` 100, `odometer_cells` 0, and `charge_cycle_count` 0. Its `firmware_release_id` records which software release it is running and is advanced only by a successful deployment sweep (§3.7). A `FleetAdmin` may retire an `ACTIVE` unit — provided no non-terminal pick task references it — moving it to the terminal `RETIRED` status and incrementing its `version`. Drive-unit listings may be filtered by `status`, `home_zone_id`, and `firmware_release_id`.

### 3.2. Inventory Model: SKUs, Slots, and Availability Accounting

A `Sku` is created with a unique immutable `sku_code` and a `velocity_class` of `HIGH`, `MEDIUM`, or `LOW`, which steers stow placement (§3.4). Two derived counters track the SKU's global position: `total_units_on_hand`, the sum of `quantity` across all its inventory slots, recomputed on every stow or pick; and `total_units_reserved`, the sum of `quantity` across slots reserved by non-terminal pick tasks. SKU listings may be filtered by `velocity_class`.

An `InventorySlot` joins a pod and a SKU (`pod_id`, `sku_id`) and carries three numbers: `quantity`, the physical units currently present, incremented by stow completion and decremented by pick completion; `quantity_reserved`, the units claimed by non-terminal pick tasks; and `accessibility_rank`, an integer at least 1 where 1 is most accessible (waist height) and higher is worse. A slot's availability is always `quantity` minus `quantity_reserved`, and both task creation and task sequencing reject a request whose quantity exceeds available units with `ERR_INSUFFICIENT_INVENTORY` — at creation, the SKU-wide availability (`total_units_on_hand` minus `total_units_reserved`) must cover the line remainder, and at sequencing, the specific slot on the chosen pod for the line's SKU must have available units covering the task's quantity. Inventory slots may be listed with optional `pod_id` and `sku_id` filters; order lines with optional `order_id` and `sku_id` filters.

### 3.3. From Order to Pick: Task Creation, Sequencing, and Dispatch

A `FlowController` creates a `CustomerOrder` in a single call with a unique immutable `order_code`, an ISO 8601 UTC `cutoff_at`, an optional `priority` (default 0, higher meaning more urgent and serving as the primary ranking key in task assignment), and its `lines`. The call creates the `OrderLine` children — each carrying the `order_id`, the demanded `sku_id`, a `quantity` of at least 1, and a `quantity_picked` that starts at 0 — and recomputes the throughput projection for any matching shift plan. The order is born `RECEIVED`. Orders may be listed with an optional `status` filter.

Against an order line, the `FlowController` creates a `PickTask` supplying `order_id`, `line_id`, `pod_id`, `station_id`, and a `quantity` of at least 1. The line must belong to the order (`ERR_REFERENTIAL_MISMATCH`). A task is born `CREATED` with no `sequence_index` and no `drive_unit_id`. Pick tasks may be listed with optional filters `order_id`, `line_id`, `pod_id`, `station_id`, `drive_unit_id`, and `status`.

**Sequencing.** A `FlowController` sequences a `CREATED` task into its station's queue; this is the OCC-guarded write requiring `expected_station_version` (§2.7). Sequencing is legal only while the station is `OPEN` with `queue_length` below `max_queue`, the pod is `IN_STORAGE` or `RESERVED` in a zone whose posture is not `FROZEN`, and the slot for the line's SKU on that pod has sufficient available units. On success the workload-smoothing sequencer assigns `sequence_index`; the station's `queue_length` and `version` each increase by 1; a pod that was `IN_STORAGE` becomes `RESERVED` and stays `RESERVED` while any non-terminal task references it; the slot's `quantity_reserved` and the SKU's `total_units_reserved` each increase by the task's `quantity`; and an order still `RECEIVED` cascades to `PLANNED`. A `QUARANTINED` pod is not eligible — it is neither `IN_STORAGE` nor `RESERVED` — and attempting the transition from a task state other than `CREATED` is rejected with `ERR_INVALID_STATE`.

The sequencer considers insertion positions from the front of the queue through one past its end. For a candidate position, the estimated finish time is the station's base rate of 120 seconds per task multiplied by the position index plus one. Lateness is the amount by which the estimated finish exceeds the seconds remaining until the order's `cutoff_at`, floored at zero. Disruption is the sum, over every existing queued task, of the absolute shift between its current `sequence_index` and where it would land after insertion. Fatigue is the station's count of tasks completed today, multiplied by a weight of 1 per position walked. The score is 5 times the lateness plus 2 times the disruption plus the fatigue, and the task is inserted at the position minimizing that score; ties resolve to the larger position index, which is the least disruptive.

**Dispatch.** A `FlowController` dispatches a `QUEUED` task, which runs the fleet selector (§3.5). The chosen unit transitions `ACTIVE` → `EN_ROUTE`, its `version` increments, the task records its `drive_unit_id` and moves to `DISPATCHED`, the pod becomes `RESERVED`, and the planning variant of the travel-cost estimate is written to the task's `est_cost`. If the selector's candidate pool is empty, dispatch fails with `ERR_NO_ELIGIBLE_DRIVE_UNIT` (HTTP 422).

**Travel cost.** The base cost is the Manhattan distance between the pod's zone origin and the station's zone origin. Congestion counts the drive units currently `EN_ROUTE` whose in-flight task's pod zone intersects the straight-line corridor bounding box. The planning variant adds ten hundredths of the base per congesting unit, with the congestion count capped at 3. The execution variant — computed on delivery, written to `actual_cost`, and also subtracted from the unit's `battery_pct` and added to its `odometer_cells` — adds twenty-five hundredths of the base per congesting unit with **no cap**, and adds a flat 4-cell detour surcharge when the carrying unit's home zone was `RESTRICTED` at dispatch time. Both variants round half-up to 2 decimal places.

**Delivery, picking, completion.** A `FlowController` records pod arrival, moving the task `DISPATCHED` → `DELIVERED` and the unit `EN_ROUTE` → `AT_STATION` (with the battery and odometer adjustments above), the pod `RESERVED` → `AT_STATION`, and the unit's `version` increments. A `StationOperator` then begins the pick (`DELIVERED` → `PICKING`) — legal only when the operator's `X-User-ID` is rostered on the current shift plan, meaning the plan for the date has `staffed_pickers` greater than 0. Completing the pick (`PICKING` → `COMPLETE`) cascades broadly: the slot's `quantity` and `quantity_reserved` each decrease by the task's `quantity`; the pod's `slots_used` is recomputed and the pod returns to `IN_STORAGE`; the SKU's `total_units_on_hand` and `total_units_reserved` are recomputed; the line's `quantity_picked` increases by the task's `quantity`; the station's `queue_length` decreases by 1 and its `version` increments; the unit returns `AT_STATION` → `ACTIVE` with a version increment; and the order advances — `PLANNED` → `IN_PROGRESS` on the first completed pick, and `IN_PROGRESS` → `COMPLETE` once every line has `quantity_picked` equal to its `quantity`.

**Cancellation.** A `FlowController` may cancel a task in `CREATED` or `QUEUED`; from `QUEUED` the cancellation releases everything sequencing claimed: station `queue_length` decreases by 1, the pod returns `RESERVED` → `IN_STORAGE`, and the slot's `quantity_reserved` and the SKU's `total_units_reserved` each decrease by the task's quantity. Cancelling a whole order is legal from `RECEIVED` or `PLANNED` provided none of its tasks is `PICKING`, `DISPATCHED`, or `DELIVERED`; every task in `CREATED` or `QUEUED` is cancelled with full reservation release and the order's `version` increments. Separately, if the logical clock advances strictly past `cutoff_at` while the order is still `RECEIVED`, the order auto-transitions to the terminal `CUTOFF_MISSED`.

### 3.4. Stow Placement: Density vs. Accessibility

Inbound units arrive as a `StowTask` created by a `FlowController` with a `sku_id` and a `quantity` of at least 1; the task is born `PENDING` with no `pod_id`. Stow tasks may be listed with optional `sku_id`, `pod_id`, and `status` filters.

Placement is run by a `FlowController` and is the second OCC-guarded write, requiring `expected_sku_version` (§2.7). The placement selector considers every pod in `IN_STORAGE` or `RESERVED` whose zone posture is not `FROZEN` and that can physically take the stow — meaning either an inventory slot for the SKU already exists on the pod, or the pod's `slots_used` is below its `slot_capacity`. Each candidate is scored from three terms: a density term, the pod's `slots_used` divided by its `slot_capacity`; a distance term, the Manhattan distance from the pod's zone origin to grid origin zero-zero; and an access term, the mean `accessibility_rank` over the SKU's existing slots on the pod — or a baseline of 3 when no such slot exists.

Two scoring variants apply. For a `LOW`-velocity SKU the density-first variant scores a candidate as 0.6 times the density term, minus 0.3 times the distance term times one hundredth, minus 0.1 times the access term times one tenth. For a `HIGH` or `MEDIUM`-velocity SKU the accessibility-first variant scores 0.6 times one minus the access term times one tenth, minus 0.3 times the distance term times one hundredth, plus 0.1 times the density term. The pod with the highest score wins; ties break by the pod's `created_at` ascending, never by `id`. Scores are rounded half-up to 4 decimal places. When no candidate pod exists, placement transitions the task to the terminal `REJECTED` and the request fails with `ERR_NO_ELIGIBLE_POD` (HTTP 422). On success the task moves `PENDING` → `PLACED`, records its `pod_id` and the winning score in `placement_score`, the selected pod becomes `RESERVED` if it was `IN_STORAGE`, and the SKU's `version` increments.

Physical confirmation is performed by a `StationOperator`. A `PLACED` task confirms provided the pod still has room — `slots_used` below `slot_capacity` — unless an inventory slot for the SKU already exists on the pod, in which case the stow always fits; a pod at capacity is rejected with `ERR_CAPACITY_EXCEEDED`. Confirmation adds the task's `quantity` to the slot's `quantity` (creating the slot row with `quantity` 0 first when absent), recomputes the pod's `slots_used`, adds the quantity to the SKU's `total_units_on_hand`, returns the pod `RESERVED` → `IN_STORAGE`, and completes the task (`PLACED` → `COMPLETE`).

### 3.5. Fleet Lifecycle: Dispatch Eligibility, Charging, and Maintenance

The **fleet selector** runs at dispatch. A drive unit is eligible when it is `ACTIVE`, its `battery_pct` is at least 20 (the minimum dispatch battery), no `ACTIVE` maintenance window covers it at the current logical clock, and its home zone's posture is not `FROZEN`. Eligible units are ranked by a score of twice the `battery_pct`, minus the Manhattan distance between the unit's home zone and the pod's zone, minus the `charge_cycle_count` (a cycle penalty of 1 per completed charge). The highest score wins; exact ties break by the unit's `created_at` ascending, never by `id`. An empty pool rejects the dispatch with `ERR_NO_ELIGIBLE_DRIVE_UNIT`.

**Charging.** A `FlowController` opens a `ChargingSession` by supplying `charger_id` and `drive_unit_id`; the unit must be `ACTIVE`, the charger's `slots_in_use` below its `slot_count` (`ERR_CAPACITY_EXCEEDED`), and the charger's zone not `FROZEN`. Opening transitions the unit `ACTIVE` → `CHARGING`, increments the charger's `slots_in_use` by 1, and increments the unit's `version`. The session records `started_at` from the logical clock; `ended_at` stays null while `OPEN`. Sessions may be listed with optional `charger_id`, `drive_unit_id`, and `status` filters.

Closing an `OPEN` session computes `charge_credit_pct` from the session's whole-minute duration (elapsed time floored to minutes): the first 30 minutes earn half a percentage point per minute, the minutes from 31 through 90 earn three tenths of a point per minute, and every minute beyond 90 earns one tenth of a point per minute — each tier rounded half-up to a whole percentage point **before** the tiers are summed. Closing transitions the session `OPEN` → `CLOSED`, restores the unit's `battery_pct` to the smaller of 100 and the current level plus the credit, increments `charge_cycle_count` by 1, decrements the charger's `slots_in_use` by 1, returns the unit `CHARGING` → `ACTIVE`, and increments the unit's `version`. When a unit's `charge_cycle_count` reaches 5 (the maintenance cycle threshold), a `PREVENTIVE` `MaintenanceWindow` is auto-created, `SCHEDULED` to start 60 minutes after the current clock with a 30-minute duration.

**Maintenance.** A `MaintenanceTech` schedules a `MaintenanceWindow` with `drive_unit_id`, `starts_at`, `ends_at`, and `kind` (`PREVENTIVE` or `CORRECTIVE`). The half-open interval must satisfy the §2.4 shape, and a new window must leave at least 15 minutes to any existing non-cancelled window for the same unit, with an exactly-15-minute adjacency allowed (`ERR_TEMPORAL_CONFLICT`). Windows may be listed with optional `drive_unit_id` and `status` filters. A window is born `SCHEDULED` and becomes `ACTIVE` automatically when the logical clock enters its half-open interval; activation pulls a unit in `ACTIVE` or `CHARGING` into `MAINTENANCE`. If the unit was charging, the open session is `ABORTED` — `ended_at` is set and the charger's `slots_in_use` decrements — as the corrective window activates. While a unit is `MAINTENANCE`, any `QUEUED` pick task that would have selected it simply excludes it from the selector. Completing an `ACTIVE` window transitions it to `COMPLETE`, returns the unit `MAINTENANCE` → `ACTIVE`, and increments the unit's `version`. A `SCHEDULED` window may be cancelled (`CANCELLED`) only while the logical clock is still before `starts_at`.

### 3.6. Floor Exceptions and Human-Entry Protocol

A `FloorSupervisor` (or a `FlowController`) reports a `FloorException` with a `kind` — `DROPPED_ITEM` (debris on the floor), `BLOCKED_PATH` (aisle obstruction), or `STRANDED_ROBOT` (an immobilized drive unit) — and the `zone_id` where it occurred. A `pod_id` is recorded only for `DROPPED_ITEM` when the debris belongs to a pod, and a `drive_unit_id` is required exactly when `kind` is `STRANDED_ROBOT`; any other combination is rejected with `ERR_REFERENTIAL_MISMATCH`. Reporting a `STRANDED_ROBOT` against an `EN_ROUTE` unit cascades immediately: the unit becomes `STRANDED`, its in-flight task becomes `FAILED` (station `queue_length` decrements, the pod becomes `QUARANTINED`, and the slot's `quantity_reserved` and SKU's `total_units_reserved` release the task's quantity). Exceptions are born `OPEN` and may be listed with optional `zone_id`, `status`, `pod_id`, and `drive_unit_id` filters.

**Triage** is performed by a `FloorSupervisor` and takes a `branch`. The robotic branch is available only for `DROPPED_ITEM` and `BLOCKED_PATH` exceptions, moving the exception `OPEN` → `TRIAGED_ROBOT`; the human branch (`OPEN` → `TRIAGED_HUMAN`) is available for any kind. Either triage cascades the zone's `posture` to `RESTRICTED`, parking every `ACTIVE` unit homed in the zone (`ACTIVE` → `PARKED`) and triggering the workload-smoothing sequencer to recompute the `QUEUED` tasks referencing pods in that zone.

**Robotic resolution** of a `TRIAGED_ROBOT` exception takes `corrective_outcome` `RESTORE` and requires that no `ACTIVE` human-entry permit covers the zone (`ERR_SAFETY_INTERLOCK`). Resolution moves the exception to the terminal `RESOLVED` state, restores the zone's `posture` to `OPEN`, returns parked units in the zone `PARKED` → `ACTIVE`, and, when a `pod_id` was recorded, returns the pod `QUARANTINED` → `IN_STORAGE`.

**Human resolution** requires the permit protocol first. A `FloorSupervisor` requests a `HumanEntryPermit` with `zone_id`, `exception_id`, and the closed interval `starts_at`/`ends_at`; the referenced exception must be `TRIAGED_HUMAN` (`ERR_REFERENTIAL_MISMATCH`). Permits are born `REQUESTED` and may be listed with optional `zone_id`, `exception_id`, and `status` filters. A `SafetyOfficer` — whose `X-User-ID` must differ from the triaging supervisor's (§2.9) — grants a `REQUESTED` permit provided the exception is `TRIAGED_HUMAN` and the count of `ACTIVE` permits for the zone with overlapping closed intervals is below the zone's `max_human_occupancy` (`ERR_CAPACITY_EXCEEDED`). Granting cascades: the permit becomes `ACTIVE`, the zone's `posture` becomes `FROZEN` and its `version` increments, every unit in the zone not already `CHARGING`, `MAINTENANCE`, or `STRANDED` parks, and `QUEUED` tasks on pods in the zone are resequenced to other stations when any exist, otherwise they remain queued with status unchanged. After the clock reaches `ends_at`, a `SafetyOfficer` releases the permit (`ACTIVE` → `RELEASED`); when no other `ACTIVE` permit covers the zone, the zone's posture falls back to `RESTRICTED` while the governing exception remains `TRIAGED_HUMAN`.

With every permit authorizing the exception `RELEASED`, a `FloorSupervisor` resolves the `TRIAGED_HUMAN` exception with `corrective_outcome` `RESTORE` or `MAINTENANCE`; `MAINTENANCE` is valid only for `STRANDED_ROBOT` exceptions. Resolution moves the exception to `RESOLVED` and restores the zone's `posture` to `OPEN`; with `MAINTENANCE` the stranded unit moves `STRANDED` → `MAINTENANCE`; with `RESTORE` on a `STRANDED_ROBOT` exception the unit moves `STRANDED` → `ACTIVE`; and a recorded pod returns `QUARANTINED` → `IN_STORAGE`.

### 3.7. Software Releases: Validation, Promotion, and Rollback

A `ReleaseEngineer` authors a `SoftwareRelease` with a unique immutable `release_code` (a semver string); the release is born `DRAFT` with `safety_check_passed` false. Releases may be listed with an optional `status` filter, and drive units running a given release are reachable through the drive-unit listing's `firmware_release_id` filter.

Validation begins with the `ReleaseEngineer` moving the release `DRAFT` → `VALIDATING`; only one release may be `VALIDATING` at a time, and a second attempt is rejected (`ERR_INVALID_STATE`). A `SafetyOfficer` — segregated from the initiating `ReleaseEngineer` per §2.9 — then records the `outcome`. An `outcome` of `PASS` moves the release to `VALIDATED` and sets `safety_check_passed` true. An `outcome` of `FAIL` requires non-empty `defect_notes`, moves the release to `FAILED`, and sets `safety_check_passed` false; the `ReleaseEngineer` may then revise the release back to `DRAFT`.

Promotion is performed by a `FleetAdmin` on a `VALIDATED` release whose `safety_check_passed` is true, and only while the floor is clean: no `FloorException` in `OPEN` or `TRIAGED_HUMAN` anywhere, and no drive unit `STRANDED` — a violation is rejected with `ERR_SAFETY_INTERLOCK`. Promotion moves the release `VALIDATED` → `FLOOR_LIVE`, rolls any prior `FLOOR_LIVE` release back to `ROLLED_BACK`, and sweeps the fleet: every drive unit's `firmware_release_id` is set to the promoted release and every unit's `version` increments. A `FleetAdmin` may also roll back the `FLOOR_LIVE` release directly (`FLOOR_LIVE` → `ROLLED_BACK`); each unit's `firmware_release_id` is restored to the previous `FLOOR_LIVE` release if one exists, otherwise it is left unchanged. `FLOOR_LIVE` and `ROLLED_BACK` are terminal states.

### 3.8. Shift Planning and Throughput Projection

A `FleetAdmin` creates a `ShiftPlan` for a `plan_date` (an ISO 8601 date, unique across plans) with `staffed_pickers` and `planned_units`, each at least 0. Creation runs the throughput projection and records its outputs in `projected_units` and `feasible`.

The projection evaluates in a pinned order to keep the circular-looking dependency well-defined. First, the active fleet counts every drive unit in `ACTIVE`, `EN_ROUTE`, `AT_STATION`, or `PARKED`. Second, picker capacity is the `staffed_pickers` multiplied by 120 picks per picker-hour and by the 8 hours in a shift. Third, fleet capacity is the active fleet multiplied by 6 units per trip, by 4 trips per hour, and by the same 8 hours. Fourth, open demand is the sum of each line's remaining quantity (`quantity` minus `quantity_picked`) over orders in `RECEIVED`, `PLANNED`, or `IN_PROGRESS` whose `cutoff_at` falls on the plan's UTC calendar date — computed **before** the projection so that orders depending on feasibility cannot feed back into it. Fifth, `projected_units` is the smallest of picker capacity, fleet capacity, and open demand. Finally, `feasible` is true exactly when `projected_units` is at least `planned_units`. The pessimistic variant — the one used for `feasible` — excludes units in `CHARGING` or `MAINTENANCE` from the active fleet; an optimistic variant used only for management reporting counts `CHARGING` units at half rate. The projection recomputes whenever a plan is created and whenever orders, stations, or fleet for the plan date mutate.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 and the created resource; endpoints that modify an existing resource (including all state-transition actions) respond with HTTP 200 and the updated resource; list and fetch endpoints respond with HTTP 200. Request and response shapes for each endpoint are reconstructed from §2 and §3; this table is deliberately minimal.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /fleet/_clock/set_current_utc | Advance the logical clock; re-evaluate time-driven cascades | FleetAdmin |
| POST | /fleet/zones | Create a FloorZone | FleetAdmin |
| GET | /fleet/zones | List FloorZones | FleetAdmin, FlowController, FloorSupervisor, SafetyOfficer, MaintenanceTech, ReleaseEngineer, StationOperator |
| GET | /fleet/zones/{id} | Fetch a FloorZone | FleetAdmin, FlowController, FloorSupervisor, SafetyOfficer, MaintenanceTech, ReleaseEngineer, StationOperator |
| GET | /fleet/zones/{id}/chargers | List Chargers in a zone | FleetAdmin, FlowController, MaintenanceTech |
| GET | /fleet/zones/{id}/pods | List Pods in a zone | FleetAdmin, FlowController, FloorSupervisor, StationOperator |
| GET | /fleet/zones/{id}/pick-stations | List PickStations in a zone | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/zones/{id}/human-entry-permits | List HumanEntryPermits for a zone | FleetAdmin, FloorSupervisor, SafetyOfficer |
| POST | /fleet/drive-units | Register a DriveUnit | FleetAdmin |
| GET | /fleet/drive-units | List DriveUnits (filters: status, home_zone_id, firmware_release_id) | FleetAdmin, FlowController, MaintenanceTech, FloorSupervisor |
| GET | /fleet/drive-units/{id} | Fetch a DriveUnit | FleetAdmin, FlowController, MaintenanceTech, FloorSupervisor |
| POST | /fleet/drive-units/{id}/retire | Retire an ACTIVE DriveUnit | FleetAdmin |
| POST | /fleet/chargers | Create a Charger in a zone | FleetAdmin |
| GET | /fleet/chargers/{id} | Fetch a Charger | FleetAdmin, FlowController, MaintenanceTech |
| GET | /fleet/chargers/{id}/charging-sessions | List ChargingSessions on a charger | FleetAdmin, FlowController, MaintenanceTech |
| POST | /fleet/charging-sessions | Open a ChargingSession for a DriveUnit | FlowController |
| GET | /fleet/charging-sessions | List ChargingSessions (filters: charger_id, drive_unit_id, status) | FleetAdmin, FlowController, MaintenanceTech |
| GET | /fleet/charging-sessions/{id} | Fetch a ChargingSession | FleetAdmin, FlowController, MaintenanceTech |
| POST | /fleet/charging-sessions/{id}/close | Close an OPEN ChargingSession | FlowController |
| POST | /fleet/pods | Create a Pod | FleetAdmin |
| GET | /fleet/pods/{id} | Fetch a Pod | FleetAdmin, FlowController, FloorSupervisor, StationOperator |
| GET | /fleet/pods/{id}/inventory-slots | List InventorySlots on a pod | FleetAdmin, FlowController, StationOperator |
| POST | /fleet/skus | Create a Sku | FleetAdmin |
| GET | /fleet/skus | List Skus (filter: velocity_class) | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/skus/{id} | Fetch a Sku | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/skus/{id}/inventory-slots | List InventorySlots holding this SKU | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/skus/{id}/order-lines | List OrderLines demanding this SKU | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/inventory-slots | List InventorySlots (filters: pod_id, sku_id) | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/order-lines | List OrderLines across orders (filters: order_id, sku_id) | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/pick-tasks | List PickTasks (filters: order_id, line_id, pod_id, station_id, drive_unit_id, status) | FleetAdmin, FlowController, StationOperator, FloorSupervisor |
| GET | /fleet/stow-tasks | List StowTasks (filters: sku_id, pod_id, status) | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/human-entry-permits | List HumanEntryPermits (filters: zone_id, exception_id, status) | FleetAdmin, FloorSupervisor, SafetyOfficer |
| GET | /fleet/software-releases | List SoftwareReleases (filter: status) | FleetAdmin, ReleaseEngineer, SafetyOfficer |
| POST | /fleet/pick-stations | Create a PickStation | FleetAdmin |
| GET | /fleet/pick-stations/{id} | Fetch a PickStation | FleetAdmin, FlowController, StationOperator |
| POST | /fleet/pick-stations/{id}/pause | Pause an OPEN PickStation | FlowController |
| POST | /fleet/pick-stations/{id}/reopen | Reopen a PAUSED PickStation | FlowController |
| GET | /fleet/pick-stations/{id}/pick-tasks | List PickTasks queued at a station | FleetAdmin, FlowController, StationOperator |
| POST | /fleet/customer-orders | Create a CustomerOrder with its lines | FlowController |
| GET | /fleet/customer-orders | List CustomerOrders (filter: status) | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/customer-orders/{id} | Fetch a CustomerOrder | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/customer-orders/{id}/lines | List OrderLines of an order | FleetAdmin, FlowController, StationOperator |
| GET | /fleet/customer-orders/{id}/pick-tasks | List PickTasks of an order | FleetAdmin, FlowController, StationOperator |
| POST | /fleet/customer-orders/{id}/cancel | Cancel a CustomerOrder from RECEIVED or PLANNED | FlowController |
| POST | /fleet/pick-tasks | Create a PickTask against an order line | FlowController |
| GET | /fleet/pick-tasks/{id} | Fetch a PickTask | FleetAdmin, FlowController, StationOperator, FloorSupervisor |
| POST | /fleet/pick-tasks/{id}/sequence | Sequence a CREATED PickTask (OCC on PickStation) | FlowController |
| POST | /fleet/pick-tasks/{id}/dispatch | Dispatch a QUEUED PickTask; runs the fleet selector | FlowController |
| POST | /fleet/pick-tasks/{id}/deliver | Record pod arrival at the station | FlowController |
| POST | /fleet/pick-tasks/{id}/begin-pick | Station operator begins picking | StationOperator |
| POST | /fleet/pick-tasks/{id}/complete | Complete the pick | StationOperator |
| POST | /fleet/pick-tasks/{id}/cancel | Cancel a CREATED or QUEUED PickTask | FlowController |
| POST | /fleet/stow-tasks | Create a StowTask for incoming units | FlowController |
| GET | /fleet/stow-tasks/{id} | Fetch a StowTask | FleetAdmin, FlowController, StationOperator |
| POST | /fleet/stow-tasks/{id}/place | Run the stow-placement selector (OCC on Sku) | FlowController |
| POST | /fleet/stow-tasks/{id}/confirm | Confirm physical stow | StationOperator |
| POST | /fleet/maintenance-windows | Schedule a MaintenanceWindow | MaintenanceTech |
| GET | /fleet/maintenance-windows | List MaintenanceWindows (filters: drive_unit_id, status) | FleetAdmin, MaintenanceTech, FlowController |
| GET | /fleet/maintenance-windows/{id} | Fetch a MaintenanceWindow | FleetAdmin, MaintenanceTech, FlowController |
| POST | /fleet/maintenance-windows/{id}/complete | Complete an ACTIVE MaintenanceWindow | MaintenanceTech |
| POST | /fleet/maintenance-windows/{id}/cancel | Cancel a SCHEDULED MaintenanceWindow | MaintenanceTech |
| POST | /fleet/floor-exceptions | Report a FloorException | FloorSupervisor, FlowController |
| GET | /fleet/floor-exceptions | List FloorExceptions (filters: zone_id, status, pod_id, drive_unit_id) | FleetAdmin, FloorSupervisor, SafetyOfficer |
| GET | /fleet/floor-exceptions/{id} | Fetch a FloorException | FleetAdmin, FloorSupervisor, SafetyOfficer |
| POST | /fleet/floor-exceptions/{id}/triage | Triage an OPEN FloorException | FloorSupervisor |
| POST | /fleet/floor-exceptions/{id}/resolve | Resolve a triaged FloorException | FloorSupervisor |
| POST | /fleet/human-entry-permits | Request a HumanEntryPermit | FloorSupervisor |
| GET | /fleet/human-entry-permits/{id} | Fetch a HumanEntryPermit | FleetAdmin, FloorSupervisor, SafetyOfficer |
| POST | /fleet/human-entry-permits/{id}/grant | Grant a permit; freezes the zone | SafetyOfficer |
| POST | /fleet/human-entry-permits/{id}/release | Release an ACTIVE permit after ends_at | SafetyOfficer |
| POST | /fleet/shift-plans | Create a ShiftPlan | FleetAdmin |
| GET | /fleet/shift-plans/{id} | Fetch a ShiftPlan | FleetAdmin, FlowController |
| POST | /fleet/software-releases | Create a SoftwareRelease | ReleaseEngineer |
| GET | /fleet/software-releases/{id} | Fetch a SoftwareRelease | FleetAdmin, ReleaseEngineer, SafetyOfficer |
| POST | /fleet/software-releases/{id}/validate | Begin validation on a DRAFT release | ReleaseEngineer |
| POST | /fleet/software-releases/{id}/record-validation | Record validation outcome | SafetyOfficer |
| POST | /fleet/software-releases/{id}/revise | Return a FAILED release to DRAFT | ReleaseEngineer |
| POST | /fleet/software-releases/{id}/promote | Promote a VALIDATED release to FLOOR_LIVE | FleetAdmin |
| POST | /fleet/software-releases/{id}/rollback | Roll back the FLOOR_LIVE release | FleetAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SAFETY_INTERLOCK | 422 |
| ERR_REFERENTIAL_MISMATCH | 422 |
| ERR_TEMPORAL_CONFLICT | 422 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_INSUFFICIENT_INVENTORY | 422 |
| ERR_NO_ELIGIBLE_DRIVE_UNIT | 422 |
| ERR_NO_ELIGIBLE_POD | 422 |
| ERR_VALIDATION | 400 |
