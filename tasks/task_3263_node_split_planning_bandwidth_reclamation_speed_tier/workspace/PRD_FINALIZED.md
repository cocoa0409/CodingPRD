# Node Split Planning, Bandwidth Reclamation & Speed Tier Provisioning API — Product Requirements Document

## 1. Introduction

Cable MSO access networks are finite. Every optical node serves a fixed number of homes over a fixed slice of downstream spectrum and a fixed upstream band, and every gigabit sold above what that plant can deliver eventually becomes a congestion complaint, a churn event, or a franchise violation. This document specifies the capacity-engineering operations API used to keep that plant healthy: monitoring service-group utilization against operator-set thresholds, engineering node splits when homes-per-node grows too dense, reclaiming legacy video QAM spectrum to expand DOCSIS data capacity, and provisioning new speed tiers only when the customer's modem and the serving node's upstream configuration can actually sustain them.

The system serves six distinct working roles, from the capacity planner who designs a node-split project to the franchise administrator who adjudicates its construction permit, to the care agent investigating a subscriber's congestion complaint and needing to distinguish plant-side congestion from in-home wiring faults from destination-network issues. A single logical clock drives all time-window arithmetic (trailing seven-day load windows, migration-wave spacing, blackout moratoria), so the entire operations surface is deterministic and replayable.

What makes this domain hard is that every lever interacts. Reclaiming spectrum raises downstream capacity, which can de-escalate a service group out of its CRITICAL posture before the planner finishes permitting the split that the same CRITICAL breach auto-proposed. Cutting a node over to child service groups retires the parent and freezes its load history. Upgrading upstream from LEGACY to MID_SPLIT changes which speed tiers are sellable on every premise fed by that node. The sections below pin down those interactions precisely: §2 covers the system-wide contract, §3 the business workflows, §4 the endpoint surface, and §5 the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contract that applies to every endpoint in the API: identity and authorization, the response envelope, pagination, the resource model, the arithmetic conventions, optimistic concurrency, and the domain invariants around spectrum, homes, and capacity.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. A request missing either header is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400). The system recognizes eight role values. The operational roles are `PlatformAdmin` (platform operator: owns franchise-area setup, the speed-tier catalog, telemetry ingest, and the logical clock), `NetworkPlanner` (capacity planner: designs optical nodes and proposes capacity actions, node-split projects, and migration waves), `CapacityEngineer` (owns spectrum blocks, service groups, and the capacity-action approval lifecycle), `FieldOpsCoordinator` (runs construction and migration-wave execution), `FranchiseAdmin` (the municipal franchise authority; adjudicates construction permits), `ProvisioningAgent` (owns customer premises, customer premises equipment, provisioning requests, and refresh campaigns), and `CustomerCare` (owns congestion-complaint investigation). The eighth role value, `Any`, denotes that every authenticated role may use the endpoint; it is the authorization label on all read-only GET endpoints and is never sent as an actual `X-User-Role` value. When a request's role is not among the endpoint's declared roles, the server rejects it with `ERR_FORBIDDEN_ROLE` (HTTP 403).

For all eight roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it against any resource's `id`; ownership and authorization are decided purely by `X-User-Role`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, and its accepted range runs from a minimum of 1 to a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Both are optional.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time Windows

All time-window arithmetic in the system — the trailing seven-day utilization window, the seven-day separation between migration waves, franchise blackout moratoria, and construction-window overlap checks — is evaluated against a server-held logical clock, not wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` may set the logical clock to a supplied `current_utc` instant through an admin-only test-driving capability; setting the clock recomputes no entities, but every subsequent window-based calculation reads the new value. All datetime inputs and outputs across the API are ISO 8601 UTC timestamps, and window arithmetic is evaluated at second precision.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — a system-managed integer that increments on every mutation; it is the handle used by optimistic concurrency control.

One exception: a `UtilizationSample` is an append-only telemetry record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent on samples. Any mutation of a resource — including system-side recomputation of its derived fields — refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Precision, Rounding, and Units

Numeric conventions are pinned so every implementation produces bit-identical values. `current_utilization_pct` on a service group is a number expressed with exactly 1 decimal place, produced by rounding half up. Complaint cause scores (`score_plant`, `score_in_home`, `score_destination`) are likewise numbers with 1 decimal place, rounded half up. `current_load_mbps` is always an integer; when an averaging step produces a fractional mean, the value is truncated down to the next whole number. Channel counts, capacity figures, homes counts, and the upstream capacity lookup are all integers. Datetime comparisons use second precision. There is no floating-point tolerance anywhere: thresholds compare exactly, and boundary inclusivity is spelled out at each rule.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control on their parent resource, and only those three. A request to manually propose a capacity action against a service group must carry `expected_service_group_version` equal to the service group's current `version`. A request to create a provisioning request against a customer premise must carry `expected_customer_premise_version` equal to the premise's current `version`. A request to schedule a node-split project's construction window must carry `expected_node_split_project_version` equal to the project's current `version`. In each case the field is mandatory, and a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The OCC field carries the version the client last observed; if any other write has advanced the parent's version since that observation, the client is acting on a stale view of the remediation or provisioning pipeline and must re-read before writing. Endpoints not named in this section take no version field at all.

### 2.8. Nested Resource Retrieval and Validation Order

For any endpoint whose URL nests one resource beneath another (for example, an optical node beneath a franchise area, or a spectrum block beneath a node), the server validates the existence of path identifiers strictly left to right. A request whose outermost identifier does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404) before the inner identifier is even examined, and the first unresolvable identifier in the path determines the rejection. The same ordered discipline governs request processing generally: authentication-context presence is checked first (missing headers surface as `ERR_MISSING_AUTH_CONTEXT`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path- and body-referenced resources (`ERR_NOT_FOUND`), then basic request shape — parseable body, required fields present, enum values legal (`ERR_VALIDATION`, HTTP 400) — then optimistic-concurrency version checks (`ERR_STALE_VERSION`), then lifecycle-state permissibility (`ERR_INVALID_STATE`, HTTP 409), then cross-entity state gates, then temporal-window rules, then referential and capability rules, then capacity and conservation constraints, and finally domain scoring checks. When several violations are present at once, the earliest check in this ordering is the one that surfaces.

### 2.9. Spectrum Conservation and Channel Arithmetic

An optical node owns a fixed total `downstream_spectrum_mhz`, and that total is conserved for the node's entire life: spectrum blocks may be created, reclaimed from legacy video to data, or reverted, but the sum of block widths on a node may never exceed the node's declared spectrum, and a block creation that would push the sum past the limit is rejected with `ERR_SPECTRUM_OVERALLOCATED` (HTTP 422).

Downstream capacity derives from blocks through a pinned arithmetic order. Each block yields a whole number of 6 MHz QAM channels: the block's width in MHz is divided by 6 and truncated down to a whole channel count, per block, never from summed MHz. Each channel on a data-active block carries 38 Mbps, so a block's `capacity_mbps` is its channel count multiplied by 38 while the block is `DATA_ACTIVE`, and 0 while the block is `VIDEO_ACTIVE` or `RECLAIM_PENDING`. A service group's `downstream_capacity_mbps` is the sum of `capacity_mbps` over the parent node's `DATA_ACTIVE` blocks. The truncation order is authoritative: a node holding a 21 MHz block and a 15 MHz block yields 3 channels (114 Mbps) plus 2 channels (76 Mbps) for 190 Mbps — not 228 Mbps, which is what summing the widths first would produce.

Upstream capacity is not computed from blocks at all; it is a lookup from the node's `upstream_config`. A `LEGACY` upstream yields 27 Mbps per service group, `MID_SPLIT` yields 108 Mbps, and `HIGH_SPLIT` yields 204 Mbps. When an upgrade capacity action completes and moves the node's `upstream_config` to its target, every non-retired service group on that node adopts the new value.

### 2.10. Homes, Build-Out Obligations, and Franchise Blackouts

A franchise area carries a municipal build-out obligation: `obligation_homes_required` homes must be serviceable by `obligation_deadline`. The area's `homes_built_progress` is computed on read as the sum of `homes_passed` over all service groups whose posture is not `SPLIT_RETIRED`, across every optical node of the area regardless of node status; the obligation counts as met once `homes_built_progress` reaches `obligation_homes_required`. The progress figure is recomputed when a node-split cutover moves homes to child service groups and when a service group is created.

Two independent constraints police the homes ledger. First, the homes served by a node's non-retired service groups may never exceed the node's own `homes_passed`; creating a service group that would breach this is rejected with `ERR_HOMES_EXCEED_NODE` (HTTP 422). Second, node-split cutover conserves homes exactly: the sum of homes allocated to the child service groups equals the parent service group's `homes_passed` with no remainder and no invention.

Franchise areas may also declare `blackout_windows` — moratorium intervals, each an inclusive-on-both-ends pair of ISO 8601 instants, during which no construction may be scheduled. Blackout windows default to an empty list when not supplied at franchise-area creation.

### 2.11. Cascades and Hierarchical Consistency

The plant model is a tree — franchise area, optical node, service group, premise, equipment — with cross-cutting references from premises and provisioning requests to the speed-tier catalog. Mutations at one level routinely reconcile other levels. A node-split cutover creates a child node and child service groups, retires the parent service group and parent node, and completes the parent capacity action in a single cascade. Completing a spectrum-reclaim action flips its target blocks to `DATA_ACTIVE` and recomputes downstream capacity and posture on every affected service group. Cancelling or revising a capacity action cancels its non-terminal node-split projects and its planned migration waves, and — for a reclaim — returns every `RECLAIM_PENDING` block to `VIDEO_ACTIVE` so the spectrum ledger never leaks. Activating a provisioning request supersedes the premise's previously active request and recomputes the service group's provisioned downstream total. Each such reconciliation is itself a mutation on the touched resource: `updated_at` refreshes and `version` increments.

## 3. Business Logic & Workflows

### 3.1. Modeling the Plant: Franchise Areas, Nodes, Blocks, and Service Groups

Every deployment begins when a `PlatformAdmin` registers a **franchise area**, supplying its display `name`, the municipal `region_code`, and the build-out obligation as `obligation_homes_required` homes by an `obligation_deadline`, optionally with `blackout_windows`. A new area starts with `homes_built_progress` at 0. Under the area, a `NetworkPlanner` lays out **optical nodes** — each tied to its parent through `franchise_area_id` — identified by a `node_code` that is unique within its franchise area, declared with the `homes_passed` the node serves, its total `downstream_spectrum_mhz`, and an initial `upstream_config` of `LEGACY`, `MID_SPLIT`, or `HIGH_SPLIT` — if the planner does not specify one, the node starts `LEGACY`. A node's `status` is `ACTIVE` from creation and becomes `SPLIT_RETIRED` only through a node-split cutover; no new blocks, service groups, or capacity actions may be created against a `SPLIT_RETIRED` node, and attempts are rejected with `ERR_NODE_RETIRED` (HTTP 409). A node's `upstream_config` is accepted as input at creation and thereafter is mutated only by the system, when an upgrade capacity action completes.

A `CapacityEngineer` carves the node's downstream spectrum into **spectrum blocks**, each created against its parent `optical_node_id`. Each block is created with a `block_type` of `LEGACY_VIDEO` or `DATA` and a width `mhz`; a `DATA` block is born in `DATA_ACTIVE` status, while a `LEGACY_VIDEO` block is born in `VIDEO_ACTIVE`. The per-block derived figures — `channels` (the width divided by 6, truncated down per block) and `capacity_mbps` (channels times 38 while `DATA_ACTIVE`, 0 otherwise) — follow the arithmetic of §2.9, and `DATA` blocks contribute capacity to the node's service groups immediately upon creation. Creating a block that would push the node's total block width past `downstream_spectrum_mhz` is rejected with `ERR_SPECTRUM_OVERALLOCATED`.

Service groups are the unit of capacity accounting; each is anchored to its parent through `optical_node_id`. A `CapacityEngineer` creates one on a node with a `sg_code` unique within the node, the `homes_passed` it serves, a `warn_threshold_pct` and a `critical_threshold_pct`, and a `utilization_method` of `PEAK_PCT95` or `SUSTAINED_AVG` selecting how load is aggregated. Creating a service group whose addition would push the node's non-retired service-group homes past the node's `homes_passed` is rejected with `ERR_HOMES_EXCEED_NODE`. A new service group's `posture` is `NORMAL`, its `downstream_capacity_mbps` is the sum over the node's `DATA_ACTIVE` blocks, its `upstream_capacity_mbps` comes from the node's upstream lookup, and its `provisioned_downstream_mbps` is the sum of the provisioned downstream rates of its premises, starting at 0.

### 3.2. Telemetry Ingest, Utilization Posture, and Automatic Remediation

Load enters the system as **utilization samples**. A `PlatformAdmin` ingests a sample against a service group, supplying the `measured_at` timestamp and the observed `downstream_mbps` and `upstream_mbps`; the sample names its parent through the `service_group_id` it is created under. Every ingest recomputes the service group's load picture, and the same recomputation also runs — without a new sample — whenever the service group's `downstream_capacity_mbps` changes, because a capacity change can move the posture line just as surely as a load change can.

The aggregation works over the trailing seven-day window: only samples whose `measured_at` falls inside the closed interval from seven days before the logical clock's current instant up to that instant count. If the window is empty, `current_load_mbps` is 0. Otherwise the service group's `utilization_method` selects the variant. Under `PEAK_PCT95`, the window's samples are sorted ascending by `downstream_mbps`, the rank is computed as the 95th percentile rank using the nearest-rank method — the count of samples is multiplied by 0.95 and rounded up to a whole rank — and `current_load_mbps` is the value at that 1-indexed rank, so spikes dominate. Under `SUSTAINED_AVG`, only samples whose `downstream_mbps` is at least half of `downstream_capacity_mbps` are eligible; if no sample qualifies, all samples in the window become eligible; `current_load_mbps` is the mean of the eligible samples' `downstream_mbps`, truncated down to an integer, so brief spikes are diluted. The utilization percentage `current_utilization_pct` is the load multiplied by 100 and divided by `downstream_capacity_mbps`, rounded half up to 1 decimal place — and is 0.0 when capacity is 0.

Posture is a derived band over that percentage. Below `warn_threshold_pct` the posture is `NORMAL`; at or above `warn_threshold_pct` but below `critical_threshold_pct` it is `ELEVATED`; at or above `critical_threshold_pct` it is `CRITICAL`. A recompute that lands the service group in `CRITICAL` from `NORMAL` or `ELEVATED` fires the system's automatic remediation: if the service group has no capacity action in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`, the system creates one with `origin` recorded as `SYSTEM`, choosing the remediation type by inspecting the plant — `SPECTRUM_RECLAIM` when the node still has at least 2 blocks in `VIDEO_ACTIVE`, else `MID_SPLIT_UPGRADE` when the node's `upstream_config` is `LEGACY`, else `HIGH_SPLIT_UPGRADE` when it is `MID_SPLIT`, else `NODE_SPLIT`. When a later recompute — after fresh samples or after a capacity change such as a reclaim completion — drops the percentage back below `warn_threshold_pct`, the posture relaxes from `CRITICAL` or `ELEVATED` to `NORMAL`; a recompute landing between the two thresholds moves `CRITICAL` down to `ELEVATED`. Posture is terminal only at `SPLIT_RETIRED`, which arrives solely through node-split cutover: the retired service group's `homes_passed` is set to 0 and its `current_load_mbps` and `current_utilization_pct` are frozen at 0 and 0.0.

### 3.3. The Capacity-Action Lifecycle

A **capacity action** is the umbrella under which all remediation executes, with an `action_type` of `NODE_SPLIT`, `SPECTRUM_RECLAIM`, `MID_SPLIT_UPGRADE`, or `HIGH_SPLIT_UPGRADE`. Actions arise two ways: automatically, with `origin` `SYSTEM`, on a `CRITICAL` breach as described above; or manually, when a `NetworkPlanner` proposes one against a service group. A manual proposal carries the `action_type`, an optional planner `note`, the OCC field `expected_service_group_version`, and — depending on type — the `target_block_ids` for a reclaim or the `target_upstream_config` for an upgrade. Manually created actions carry `origin` `MANUAL` and start in `PROPOSED`. Creating a new action supersedes any existing `PROPOSED` action of the same service group: the older one is cancelled and its `superseded_by_id` is set to the newer action's id. The creation itself is a mutation on the service group, incrementing its `version`.

Two guards apply at proposal time. For `SPECTRUM_RECLAIM`, every id in `target_block_ids` must name a `VIDEO_ACTIVE` block on the service group's node, and at least one `VIDEO_ACTIVE` block on the node must remain untargeted — a proposal that would target every remaining video block is rejected with `ERR_LAST_VIDEO_BLOCK` (HTTP 422). For the upgrade types, `target_upstream_config` must be exactly one step above the node's current `upstream_config` — `LEGACY` upgrades only to `MID_SPLIT`, and `MID_SPLIT` only to `HIGH_SPLIT`; anything else is rejected with `ERR_UPGRADE_PATH_INVALID` (HTTP 422).

Approval moves a `PROPOSED` action to `APPROVED` and is performed by a `CapacityEngineer`; an action whose service group has posture `SPLIT_RETIRED` may not be approved. The lifecycle deliberately includes a revision loop: a `CapacityEngineer` may send an `APPROVED` action back to `PROPOSED` for rework, optionally recording a fresh `note`. Revision cascades — any linked node-split project in `PERMIT_REVIEW`, `PERMIT_GRANTED`, `PERMIT_DENIED`, or `SCHEDULED` is cancelled, and any linked migration wave still `PLANNED` is cancelled.

Beginning an `APPROVED` action moves it to `IN_PROGRESS`, again by a `CapacityEngineer`, and is where the type-specific preconditions bind: a reclaim may begin only when every target block is still `VIDEO_ACTIVE` on the action's node and at least one `VIDEO_ACTIVE` block on that node is not targeted; a `MID_SPLIT_UPGRADE` may begin only while the node's `upstream_config` is `LEGACY`; a `HIGH_SPLIT_UPGRADE` only while it is `MID_SPLIT`. Beginning a reclaim immediately moves each target block from `VIDEO_ACTIVE` to `RECLAIM_PENDING`, during which the block contributes 0 capacity — so a service group lives with temporarily reduced headroom between begin and complete.

Completion splits by type. A reclaim or upgrade is completed explicitly by a `CapacityEngineer`; a node split completes automatically at cutover. A reclaim may complete only when every linked migration wave is `EXECUTED` or `CANCELLED` and at least one is `EXECUTED` — the video spectrum is not freed until the subscribers have actually been migrated off it. Completing a reclaim moves each target block to `DATA_ACTIVE`, recomputes the affected service groups' `downstream_capacity_mbps`, and recomputes posture, which may de-escalate the service group out of `CRITICAL`. Completing an upgrade sets the node's `upstream_config` to the action's `target_upstream_config` and recomputes `upstream_capacity_mbps` on every non-retired service group of the node.

Cancellation is possible from `PROPOSED`, `APPROVED`, or `IN_PROGRESS`, and the request may carry a free-form `reason`. A manual cancel is permitted only from `PROPOSED` or `APPROVED`; an `IN_PROGRESS` action may be cancelled only while no linked node-split project is `IN_CONSTRUCTION`. Cancelling unwinds everything the action set in motion: any target block still `RECLAIM_PENDING` returns to `VIDEO_ACTIVE`, restoring the spectrum ledger; any linked node-split project in a non-terminal state is cancelled; any linked `PLANNED` migration wave is cancelled. `COMPLETED` and `CANCELLED` are terminal.

### 3.4. Node-Split Engineering: Permits, Windows, and Cutover

A node split is the heaviest remediation: it physically divides the homes on a node across a new child node. Engineering begins when a `NetworkPlanner` files a **node-split project** under a capacity action whose `action_type` is `NODE_SPLIT` — filing one under any other action type is rejected with `ERR_ACTION_TYPE_MISMATCH` (HTTP 422). The payload names the parent through `capacity_action_id`. The project declares `child_count` (between 2 and 4 child service groups), and the `min_homes_per_child` and `max_homes_per_child` bounds each child must respect. A new project enters `PERMIT_REVIEW`, representing the municipal permit application.

Permitting belongs to the `FranchiseAdmin`. Adjudication takes a `decision`: `GRANTED` moves the project `PERMIT_REVIEW → PERMIT_GRANTED`; `DENIED` moves it `PERMIT_REVIEW → PERMIT_DENIED`. Denial is not terminal — a denied application may be refiled, returning the project `PERMIT_DENIED → PERMIT_REVIEW`, and the refile cycle can repeat indefinitely.

Once granted, a `NetworkPlanner` schedules the construction window, supplying `window_start` and `window_end` plus the OCC field `expected_node_split_project_version`. Scheduling is the most heavily guarded transition in the system, and its checks are evaluated in a fixed order: the permit state must be `PERMIT_GRANTED` (a project in any other state is rejected — surfaced as `ERR_PERMIT_NOT_GRANTED`, HTTP 409, the scheduling-specific face of the lifecycle guard); then the OCC version must match, with a mismatch rejected as `ERR_STALE_VERSION`; then the window itself must be well-formed, with `window_start` strictly earlier than `window_end`; then the calendar checks. The construction window is a half-open interval — it occupies every instant from `window_start` up to but not including `window_end`. It may not overlap the window of any other node-split project in `SCHEDULED` or `IN_CONSTRUCTION` under the same franchise area, where two half-open windows that merely touch — one's `window_end` equal to the other's `window_start` — do not overlap. It may also not intersect any entry in the franchise area's `blackout_windows`, and blackout intervals are closed on both ends, so a construction window that merely touches a blackout's start or end instant does intersect it. Either calendar violation is rejected with `ERR_WINDOW_CONFLICT` (HTTP 409). A successful schedule moves the project `PERMIT_GRANTED → SCHEDULED` and increments the project's `version` by 1 — which is exactly why the OCC guard exists: a client whose `expected_node_split_project_version` predates a prior successful schedule is working from a stale build calendar, and the rejection forces a re-read.

A `FieldOpsCoordinator` begins construction, moving the project `SCHEDULED → IN_CONSTRUCTION`; this is gated on the parent capacity action being `IN_PROGRESS`, and a project whose parent action is in any other status is rejected with `ERR_INVALID_STATE`.

Cutover is the point of no return, executed by a `FieldOpsCoordinator`, and it carries two hard preconditions. First, the split source node must have exactly one service group whose posture is not `SPLIT_RETIRED`. Second, the homes waterfall must close. The allocation walks the children in creation order from 1 up to one short of `child_count`: for each child, the remaining homes are divided by the number of children not yet allocated (including this one), truncated down to a whole number, and the result is clamped — raised to `min_homes_per_child` if below it, capped at `max_homes_per_child` if above it — before being subtracted from the remainder. The final child receives whatever remains, and if that remainder falls outside the inclusive range from `min_homes_per_child` to `max_homes_per_child`, the cutover is rejected with `ERR_ALLOCATION_INVALID` (HTTP 422): homes are conserved exactly, and a split that would strand or invent homes never executes. Because clamping an early child shifts the remainder for every later child, the waterfall interacts non-linearly with the bounds — for instance, 1000 homes across 3 children with bounds 200–400 allocates 333, 333, and 334, while a minimum of 350 against 1050 homes yields 350, 350, 350.

A successful cutover records the per-child homes on the project's `child_allocations` and fires the full cascade. A new child optical node is created whose `node_code` is the parent's code suffixed with `-S1`, inheriting the parent's `downstream_spectrum_mhz` and `upstream_config`, with duplicated copies of the parent's spectrum blocks preserving each block's `DATA_ACTIVE` or `VIDEO_ACTIVE` status; its id is recorded on the project as `child_node_id`. Beneath it, `child_count` child service groups are created, each inheriting the parent's thresholds and `utilization_method` and receiving its allocated homes, with their ids recorded as `child_service_group_ids`. The parent service group's `homes_passed` drops to 0 and its posture becomes `SPLIT_RETIRED`. The parent optical node's `status` becomes `SPLIT_RETIRED`. The parent capacity action auto-completes, moving to `COMPLETED` without an explicit completion call. The project itself lands in `COMPLETED`, which is terminal, as is `CANCELLED` — a project in `PERMIT_REVIEW`, `PERMIT_GRANTED`, `PERMIT_DENIED`, or `SCHEDULED` is cancelled automatically when its parent action is cancelled or revised.

### 3.5. Spectrum Reclamation and Migration Waves

Reclaiming legacy video spectrum requires moving the subscribers who still consume it. Under a capacity action whose `action_type` is `SPECTRUM_RECLAIM` — again, any other type is `ERR_ACTION_TYPE_MISMATCH`, and the wave's payload likewise carries `capacity_action_id` — a `NetworkPlanner` plans **migration waves**, each with a `wave_code` unique within the parent action, an execution window from `window_start` to `window_end`, and the `target_cpe_ids` naming the customer equipment to migrate off legacy video. A wave starts `PLANNED`.

Wave windows must be spread out: between the new wave's window and the window of every sibling wave in `PLANNED` or `EXECUTED` under the same action, there must be a separation of at least 7 full days in one direction or the other — the new window's start at or after the sibling's end plus 7 days, or the new window's end at or before the sibling's start minus 7 days. A gap of exactly 7 days is permitted; a gap one second short of 7 days is not, and a violation is rejected with `ERR_WAVE_GAP_VIOLATION` (HTTP 409).

A `FieldOpsCoordinator` executes a planned wave. Execution requires the parent capacity action to be `IN_PROGRESS` (else `ERR_INVALID_STATE`) and requires every id in `target_cpe_ids` to name equipment that exists, is `ACTIVE`, and still has `video_legacy` true; a target that is missing, retired, or already migrated is rejected with `ERR_CPE_NOT_ELIGIBLE` (HTTP 422). On execution, each targeted unit's `video_legacy` flips to false, the wave's `migrated_count` is set to the number of targeted units, and the wave moves `PLANNED → EXECUTED`. A wave may instead be cancelled while `PLANNED`, either directly by a `FieldOpsCoordinator` or by the system when the parent action is cancelled or revised; `EXECUTED` and `CANCELLED` are terminal. The action-level completion guard of §3.3 ties it together: the reclaim completes only when every wave has resolved and at least one has actually executed, at which point the target blocks go `DATA_ACTIVE` and capacity is recomputed.

### 3.6. Premises, Equipment, and the Speed-Tier Catalog

The subscriber side of the model begins with the **customer premise**, created by a `ProvisioningAgent` under a service group with a billing `premise_ref` and a service `address`. A new premise has `current_tier_id` null and `provisioned_downstream_mbps` 0 — it consumes nothing until a provisioning request activates. Premises can be listed for a service group, or filtered system-wide by `service_group_id` or `current_tier_id`.

A premise's modems are **customer equipment** records, installed by a `ProvisioningAgent` with a `model` string, a `docsis_version` label such as 3.0, 3.1, or 4.0, a `capability_class` of `D30`, `D31`, or `D40` (ranked in that order, `D30` lowest), a hardware ceiling `max_downstream_mbps`, and a `video_legacy` flag recording whether the unit still consumes legacy video QAM. Equipment is born `ACTIVE`; the only transition is to `RETIRED`, which happens through a swap. A swap retires the old unit and creates its replacement in one call: the new unit takes its `model`, `docsis_version`, `capability_class`, and `max_downstream_mbps` from the request, starts `ACTIVE`, and inherits `video_legacy` from the retired unit. If the swap supplies a `refresh_campaign_id`, the named campaign must be `LAUNCHED` — otherwise the swap is rejected with `ERR_CAMPAIGN_NOT_LAUNCHED` (HTTP 409) — and the campaign's `swapped_count` increments by 1. Because a swap creates the replacement unit as its response body, it returns `201 Created` under §4 even though it also retires the old unit.

The **speed-tier catalog** is owned by the `PlatformAdmin`. Each tier is published with a globally unique `tier_code`, its `downstream_mbps` and `upstream_mbps` rates, the `min_capability_class` a modem must carry (`D30`, `D31`, or `D40`), and the `min_upstream_config` the serving node must reach (`LEGACY`, `MID_SPLIT`, or `HIGH_SPLIT`). A tier is `PUBLISHED` from creation; retirement moves it to `RETIRED`, which is terminal. Validation of any new provisioning request against a `RETIRED` tier is rejected with `ERR_TIER_RETIRED` (HTTP 409).

### 3.7. Provisioning a Tier: Request, Validate, Activate

Selling a tier is a staged workflow so that capability and capacity checks happen exactly once, at validation, against the plant state at that moment. A `ProvisioningAgent` opens a **provisioning request** on a premise, supplying the `speed_tier_id` and the OCC field `expected_customer_premise_version`. Creation is blocked outright while the premise's service group posture is `CRITICAL` — a congested service group takes no new sales, and the attempt is rejected with `ERR_SG_CONGESTED` (HTTP 409). Creating a request supersedes any existing `PENDING`, `VALIDATED`, or `FAILED` request of the same premise, cancelling it, and the creation increments the premise's `version` — which is why a second agent holding an older `expected_customer_premise_version` is then rejected with `ERR_STALE_VERSION`: their view of the premise's provisioning pipeline no longer reflects reality. A new request starts `PENDING` with `config_file_content` and `failure_reason` both null.

Validation is the gate, performed by a `ProvisioningAgent`, and its checks are evaluated in order so that the first failure is the one reported. First, the referenced tier must be `PUBLISHED` (else `ERR_TIER_RETIRED`). Second, the premise must hold an `ACTIVE` equipment unit whose `capability_class` ranks at or above the tier's `min_capability_class` and whose `max_downstream_mbps` is at least the tier's `downstream_mbps` (else `ERR_CAPABILITY_INSUFFICIENT`, HTTP 422). Third, the serving node's `upstream_config` must rank at or above the tier's `min_upstream_config` under the ordering `LEGACY` below `MID_SPLIT` below `HIGH_SPLIT` (else `ERR_UPSTREAM_CONFIG_INSUFFICIENT`, HTTP 422). Fourth, the capacity projection must pass, evaluated in a pinned order so the circular-looking dependency between load and capacity is well-defined: take the service group's current `downstream_capacity_mbps` from its `DATA_ACTIVE` blocks, take its `current_load_mbps` under the service group's aggregation variant, add the tier's `downstream_mbps` to obtain the projected load, and reject with `ERR_CAPACITY_EXCEEDED` (HTTP 422) when the projected load multiplied by 100 reaches or exceeds `critical_threshold_pct` times the capacity — landing exactly on the critical line rejects — or when capacity is 0 at all.

A request that passes every check moves `PENDING → VALIDATED`, and the modem configuration file is generated as `config_file_content` in the exact format `TIER=<tier_code>;DS=<downstream_mbps>;US=<upstream_mbps>;CPE=<capability_class>`. A request that fails any check moves `PENDING → FAILED`, the failing check's error id is recorded as `failure_reason`, and the validate response itself carries that error (as a 4xx). Failure is recoverable: after corrective action — typically an equipment swap — a `ProvisioningAgent` may retry, returning the request `FAILED → PENDING` and clearing `failure_reason` to null, ready to validate again. The retry cycle can repeat as often as needed.

Activation, by a `ProvisioningAgent`, moves a `VALIDATED` request to `ACTIVE` and applies the tier: the premise's `current_tier_id` becomes the request's `speed_tier_id`, its `provisioned_downstream_mbps` becomes the tier's `downstream_mbps`, and the service group's aggregate `provisioned_downstream_mbps` is recomputed. If the premise already had an `ACTIVE` request, that request is superseded to `CANCELLED` as part of the same activation. `ACTIVE` and `CANCELLED` are the terminal states.

A request in `PENDING`, `VALIDATED`, `FAILED`, or `ACTIVE` may be cancelled by a `ProvisioningAgent`. Cancelling a request that was never `ACTIVE` simply terminates it. Cancelling the `ACTIVE` request deprovisions the tier: the premise's `current_tier_id` returns to null, its `provisioned_downstream_mbps` returns to 0, and the service group's provisioned total is recomputed. Requests can be listed filtered by `customer_premise_id`, `speed_tier_id`, or `status`.

### 3.8. Equipment Refresh Campaigns

When a new tier demands hardware the installed base lacks, a `ProvisioningAgent` organizes a **refresh campaign** under a franchise area, referenced through its `franchise_area_id`. The campaign carries a `campaign_code` unique within the area and a `target_capability_class` of `D31` or `D40`. It starts `DRAFT` with both counters at 0. Launching moves it `DRAFT → LAUNCHED` and computes `targeted_count`: the number of `ACTIVE` equipment units anywhere in the franchise area whose `capability_class` ranks strictly below the campaign's `target_capability_class`. From then on, every swap that names the campaign through `refresh_campaign_id` — while it remains `LAUNCHED` — advances `swapped_count` by 1. Closing moves the campaign `LAUNCHED → CLOSED`, which is terminal; no further swaps credit it.

### 3.9. Congestion Complaints: Investigation, Classification, Resolution

The subscriber-visible side of congestion is the **complaint**, filed by a `CustomerCare` agent against a premise with a free-text `description` and three diagnostic signal strengths, each an integer from 0 to 100: `plant_signal` from field plant diagnostics, `home_signal` from in-home wiring, and `destination_signal` from the destination or network peer. A complaint starts `INVESTIGATING` with `reopen_count` 0 and its scores and `cause_category` unset.

Classification is an assertion-checked computation, performed by a `CustomerCare` agent who submits a `scoring_variant` — `EVIDENCE_WEIGHTED` or `RECENCY_WEIGHTED` — together with the `cause_category` they assert (`PLANT`, `IN_HOME`, or `DESTINATION`). The system computes the three scores under the requested variant and records the variant as `scoring_variant_used`. Under `EVIDENCE_WEIGHTED`, the scores are simply the raw signals: `score_plant` is `plant_signal`, `score_in_home` is `home_signal`, and `score_destination` is `destination_signal`, with history ignored. Under `RECENCY_WEIGHTED`, the system finds the premise's most recent complaint in `RESOLVED` or `CLOSED` status by creation timestamp, and each score is six-tenths of the corresponding raw signal plus a flat boost of 40 when that prior complaint exists and its `cause_category` matches the score's cause — the boost can flip the outcome relative to the raw signals. In both variants the computed cause is the highest of the three scores, and an exact tie resolves by the fixed priority `PLANT` over `IN_HOME` over `DESTINATION`. Scores are recorded with 1 decimal place, rounded half up.

The agent's asserted `cause_category` must equal the computed cause. If it does not, the classification is rejected with `ERR_CAUSE_MISMATCH` (HTTP 422) and the complaint remains `INVESTIGATING` — the system will not record a cause the evidence does not support. A matching assertion moves the complaint `INVESTIGATING → CLASSIFIED` with `score_plant`, `score_in_home`, `score_destination`, and `scoring_variant_used` all recorded.

Resolution, by a `CustomerCare` agent, records a `resolution_note` and moves the complaint `CLASSIFIED → RESOLVED`. Resolution can feed back into capacity engineering: when the recorded `cause_category` is `PLANT` and the premise's service group has no capacity action in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`, the system automatically creates one — `origin` `SYSTEM`, type `NODE_SPLIT` — so a plant-side congestion finding seeds the remediation pipeline even when telemetry thresholds have not yet breached.

The complaint lifecycle includes a reopen cycle. A `RESOLVED` complaint may be reopened by a `CustomerCare` agent, returning it to `INVESTIGATING`: `reopen_count` increments by 1, `cause_category` resets to null, and the three scores reset to null — reinvestigation starts from a clean slate. Alternatively, a `RESOLVED` complaint may be closed permanently, moving `RESOLVED → CLOSED`, which is terminal. Complaints can be listed filtered by `customer_premise_id` or `status`.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource or drive a state transition return `200 OK`. List endpoints return `200 OK` with the paginated envelope of §2.3. All request and response bodies follow the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/franchise-areas` | Create a franchise area | PlatformAdmin |
| GET | `/franchise-areas/{id}` | Get a franchise area (includes computed homes_built_progress) | Any |
| GET | `/franchise-areas` | List franchise areas | Any |
| POST | `/franchise-areas/{id}/optical-nodes` | Create an optical node under a franchise area | NetworkPlanner |
| GET | `/optical-nodes/{id}` | Get an optical node | Any |
| GET | `/franchise-areas/{id}/optical-nodes` | List optical nodes of a franchise area | Any |
| POST | `/optical-nodes/{id}/spectrum-blocks` | Create a spectrum block on a node | CapacityEngineer |
| GET | `/spectrum-blocks/{id}` | Get a spectrum block | Any |
| GET | `/optical-nodes/{id}/spectrum-blocks` | List spectrum blocks of a node | Any |
| POST | `/optical-nodes/{id}/service-groups` | Create a service group on a node | CapacityEngineer |
| GET | `/service-groups/{id}` | Get a service group (includes computed capacity, load, pct, posture) | Any |
| GET | `/optical-nodes/{id}/service-groups` | List service groups of a node | Any |
| POST | `/service-groups/{id}/utilization-samples` | Ingest a utilization sample; recomputes load/pct/posture | PlatformAdmin |
| GET | `/service-groups/{id}/utilization-samples` | List utilization samples of a service group | Any |
| POST | `/service-groups/{id}/capacity-actions` | Manually propose a capacity action | NetworkPlanner |
| GET | `/capacity-actions/{id}` | Get a capacity action | Any |
| GET | `/service-groups/{id}/capacity-actions` | List capacity actions of a service group (filter by status) | Any |
| POST | `/capacity-actions/{id}/approve` | Approve a proposed capacity action | CapacityEngineer |
| POST | `/capacity-actions/{id}/revise` | Send an approved action back for rework | CapacityEngineer |
| POST | `/capacity-actions/{id}/begin` | Begin an approved action | CapacityEngineer |
| POST | `/capacity-actions/{id}/complete` | Complete a reclaim or upgrade action | CapacityEngineer |
| POST | `/capacity-actions/{id}/cancel` | Cancel an action | CapacityEngineer |
| POST | `/capacity-actions/{id}/node-split-projects` | Create a node-split project under a NODE_SPLIT action | NetworkPlanner |
| GET | `/node-split-projects/{id}` | Get a node-split project | Any |
| GET | `/capacity-actions/{id}/node-split-projects` | List node-split projects of a capacity action | Any |
| POST | `/node-split-projects/{id}/adjudicate-permit` | Grant or deny the construction permit | FranchiseAdmin |
| POST | `/node-split-projects/{id}/refile-permit` | Refile a denied permit application | FranchiseAdmin |
| POST | `/node-split-projects/{id}/schedule` | Schedule the construction window | NetworkPlanner |
| POST | `/node-split-projects/{id}/begin-construction` | Begin construction | FieldOpsCoordinator |
| POST | `/node-split-projects/{id}/cutover` | Execute the split cutover | FieldOpsCoordinator |
| POST | `/capacity-actions/{id}/migration-waves` | Plan a migration wave under a SPECTRUM_RECLAIM action | NetworkPlanner |
| GET | `/migration-waves/{id}` | Get a migration wave | Any |
| GET | `/capacity-actions/{id}/migration-waves` | List migration waves of a capacity action | Any |
| POST | `/migration-waves/{id}/execute` | Execute a wave | FieldOpsCoordinator |
| POST | `/migration-waves/{id}/cancel` | Cancel a planned wave | FieldOpsCoordinator |
| POST | `/service-groups/{id}/customer-premises` | Create a customer premise on a service group | ProvisioningAgent |
| GET | `/customer-premises/{id}` | Get a customer premise | Any |
| GET | `/service-groups/{id}/customer-premises` | List premises of a service group | Any |
| GET | `/customer-premises` | List premises filtered by service group or current tier | Any |
| POST | `/customer-premises/{id}/equipment` | Install customer premises equipment | ProvisioningAgent |
| GET | `/equipment/{id}` | Get a CPE record | Any |
| GET | `/customer-premises/{id}/equipment` | List equipment of a premise | Any |
| POST | `/equipment/{id}/swap` | Swap CPE for a new unit | ProvisioningAgent |
| POST | `/speed-tiers` | Publish a speed tier | PlatformAdmin |
| GET | `/speed-tiers/{id}` | Get a speed tier | Any |
| POST | `/speed-tiers/{id}/retire` | Retire a speed tier | PlatformAdmin |
| POST | `/customer-premises/{id}/provisioning-requests` | Create a provisioning request | ProvisioningAgent |
| GET | `/provisioning-requests/{id}` | Get a provisioning request | Any |
| GET | `/provisioning-requests` | List provisioning requests filtered by premise, tier, or status | Any |
| POST | `/provisioning-requests/{id}/validate` | Validate the request and generate the config file | ProvisioningAgent |
| POST | `/provisioning-requests/{id}/activate` | Activate a validated request | ProvisioningAgent |
| POST | `/provisioning-requests/{id}/retry` | Retry a failed request | ProvisioningAgent |
| POST | `/provisioning-requests/{id}/cancel` | Cancel a request | ProvisioningAgent |
| POST | `/franchise-areas/{id}/refresh-campaigns` | Create a CPE refresh campaign | ProvisioningAgent |
| GET | `/refresh-campaigns/{id}` | Get a refresh campaign | Any |
| GET | `/franchise-areas/{id}/refresh-campaigns` | List refresh campaigns of a franchise area | Any |
| POST | `/refresh-campaigns/{id}/launch` | Launch the campaign and compute targeted_count | ProvisioningAgent |
| POST | `/refresh-campaigns/{id}/close` | Close the campaign | ProvisioningAgent |
| POST | `/customer-premises/{id}/congestion-complaints` | File a congestion complaint with diagnostic signals | CustomerCare |
| GET | `/congestion-complaints/{id}` | Get a complaint | Any |
| GET | `/congestion-complaints` | List complaints filtered by premise or status | Any |
| POST | `/congestion-complaints/{id}/classify` | Classify the cause under a scoring variant | CustomerCare |
| POST | `/congestion-complaints/{id}/resolve` | Resolve a classified complaint | CustomerCare |
| POST | `/congestion-complaints/{id}/reopen` | Reopen a resolved complaint | CustomerCare |
| POST | `/congestion-complaints/{id}/close` | Close a resolved complaint permanently | CustomerCare |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SG_CONGESTED` | 409 Conflict |
| `ERR_TIER_RETIRED` | 409 Conflict |
| `ERR_NODE_RETIRED` | 409 Conflict |
| `ERR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_WAVE_GAP_VIOLATION` | 409 Conflict |
| `ERR_PERMIT_NOT_GRANTED` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_LAUNCHED` | 409 Conflict |
| `ERR_CAPABILITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_UPSTREAM_CONFIG_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LAST_VIDEO_BLOCK` | 422 Unprocessable Entity |
| `ERR_HOMES_EXCEED_NODE` | 422 Unprocessable Entity |
| `ERR_SPECTRUM_OVERALLOCATED` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_INVALID` | 422 Unprocessable Entity |
| `ERR_CAUSE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ACTION_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UPGRADE_PATH_INVALID` | 422 Unprocessable Entity |
| `ERR_CPE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
