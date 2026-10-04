# Doughnut Hub Spoke API — Product Requirements Document

## 1. Introduction

Fresh doughnut retail operates on an unforgiving clock: product fried and glazed in the early hours must reach theater stores, spoke shops, grocery cabinets, and partner counters while it is still worth eating, and anything left standing at close of business becomes a same-day stale pull that someone has to pay for. This document specifies the Doughnut Hub Spoke API, the operational backbone for a network in which high-capacity hub kitchens bake for satellite doors, theater stores run visible production lines beneath the famous hot light, and a fundraising channel moves bulk dozens on reserved capacity.

The API governs the full daily cycle. A `NetworkAdmin` stands up networks, hubs, doors, and variety catalogs; a `HubManager` runs equipment lines and production batches against a hard daily capacity; a `RoutePlanner` builds, locks, dispatches, and reconciles delivery routes; a `RouteDriver` executes stops and records deliveries; and a `DoorManager` plans variety mixes, reports stale pulls, runs fundraiser orders, and conducts the hot-light theater. Cross-cutting all of it is a network posture engine that degrades or suspends operations in response to line failures, batch shortfalls, and dispute pileups, and a freshness regime in which every completed batch carries a hard twelve-hour freshness horizon.

Two design commitments shape everything below. First, freshness and fiscal liability are first-class: every stale pull generates a provisional credit that is only finalized at route reconciliation, and disputes over credits can suspend a door. Second, the system is checkpoint-driven: an ops-run checkpoint recomputes network posture from scratch, expires stale work, and gives the network a monotonic heartbeat that operators can reason about.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their capacity. The recognized roles are `NetworkAdmin`, `HubManager`, `RoutePlanner`, `RouteDriver`, and `DoorManager`. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the requested operation — per the role column of the endpoint table in §4 — is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Independently of role checks, any request carrying a missing required field, a malformed value, or an enum value outside its declared range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Independently of role checks, any request carrying a missing required field, a malformed value, or an enum value outside its declared range is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Role identity semantics differ by role. When `X-User-Role` is `DoorManager`, `X-User-ID` is the `id` of the acting `Door`; ownership checks on any resource that references a `Door` compare the resource's `door_id` foreign key to `X-User-ID`, so a door manager can only operate on mix plans, fundraiser orders, stale credits, and hot-light windows belonging to their own door. When `X-User-Role` is `NetworkAdmin`, `HubManager`, `RoutePlanner`, or `RouteDriver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter bounds the number of returned items: it defaults to 10 when omitted, and must lie between a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. Paginated responses expose `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity and Common Properties

Every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` is refreshed on any mutation of the resource. The `version` field is an integer that starts at its initial value on creation and increments by exactly one on every mutation of the resource — including mutations performed by system cascades rather than direct client writes. All thirteen resource kinds in this domain — networks, hubs, doors, equipment lines, varieties, mix plans, mix plan lines, production batches, routes, route stops, shipments, stale credits, fundraiser orders, and hot-light windows — carry this full common set; no resource in the system omits `updated_at` or `version`. Timestamps that encode client-supplied instants or values derived from them — a variety's `active_from` and `active_until`, a stop's `window_start` and `window_end`, a fundraiser order's `pickup_at`, and a hot-light window's `lit_start` and `lit_end` — are rendered as ISO 8601 UTC timestamps without fractional digits.

Because cascades mutate parents as well as children, a client must never assume a resource's `version` is stable across operations it did not itself perform: committing a batch increments the parent hub's `version`, dispatching a route increments the route's `version`, and so on.

### 2.5. The Logical Clock and Time-Driven Transitions

The system runs on a logical clock, not wall-clock time. At server startup the clock reads exactly `2026-09-01T00:00:00Z`, and before any clock-set call it continues to read that default — it never silently falls back to the host's wall clock. A `NetworkAdmin` advances time through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value and returns the resulting `current_utc`. Setting the clock re-evaluates time-based system transitions at the new instant: varieties whose selling window has passed flip to `EXPIRED` immediately on clock-set, and dispatched routes are re-checked for auto-completion against their stops. The remaining time-driven transitions are checkpoint- or event-driven rather than clock-set-driven: stop auto-missing, `READY` fundraiser order auto-expiry, and hot-light auto-ignition or auto-completion fire at ops-run checkpoints (§3.9) or at the endpoint calls that touch those resources, per the rules in §3 — never silently on the clock tick itself.

All deadline arithmetic in this document — freshness horizons, same-day pull deadlines, dispute windows, lead times, and pickup grace — is expressed against this logical clock.

### 2.6. Network Posture Derivation

Every network carries a derived `network_posture` with values `OPEN`, `DEGRADED`, `SUSPENDED`, and `CLOSED`. Posture is recomputed whenever an equipment line changes state, whenever a batch falls into shortfall, whenever a door suspension pushes the dispute threshold, and at every ops-run checkpoint. The derivation follows a pinned evaluation order, checked in exactly this sequence:

1. If any hub in the network has zero equipment lines in `OPERATIONAL` or `DEGRADED` status, the posture is `SUSPENDED`.
2. Otherwise, if at least two production batches have entered `SHORTFALL` today, or if any door in the network is `SUSPENDED`, the posture is `DEGRADED`.
3. Otherwise, if the network has been explicitly closed by a `NetworkAdmin`, the posture is `CLOSED` — a terminal condition.
4. Otherwise the posture is `OPEN`.

`CLOSED` is sticky: once a network is closed it remains `CLOSED`, and the `SUSPENDED` and `DEGRADED` recomputation above applies only while the posture is not `CLOSED`. Posture gates production work — batch commits are only accepted while the network is `OPEN` or `DEGRADED` — so the posture engine is a safety valve, not a report.

### 2.7. Nested Resource Retrieval and Path Validation

Most resources live beneath a network in the URL hierarchy — a batch under a hub under a network, a stop under a route under a hub under a network. For any request targeting a nested path, the server validates path identifiers strictly left to right: the network first, then the hub or door, then the child resource. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later segment is consulted. A request for a batch under a nonexistent hub therefore fails on the hub lookup before the batch id is ever examined. Parent-child scoping is enforced as part of this walk: a child resource addressed beneath the wrong parent is treated as not found within that path.

### 2.8. Precision, Rounding, and Monetary Conventions

All monetary amounts are integer cents. Credit calculations are rounded exactly once per credit — never per dozen — using round-half-up to zero decimal places, and this rounding order is pinned: the tier rate and any variant multipliers are applied to the raw credit first, and the single rounding step happens last. Fundraiser quotes use the opposite pinned order: the per-dozen price line is rounded half-up to integer cents first, and those rounded line amounts are then summed. Allocation arithmetic works in whole dozens with no rounding at all — grants are computed with a minimum-of operation and remainders are never rounded up. Hot-light demand-response grants are integer minutes. The yield rate recorded on a completed batch is a ratio computed from actual over planned dozens.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and the guard is mandatory — the version field is a non-optional input on these requests.

Publishing a mix plan requires the request to carry `expected_mix_plan_version` holding the client's last observed `version` of the target mix plan. If the plan's current `version` has advanced since that observation — for example because another writer published a newer plan for the same door and date, legitimately superseding the prior published plan — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a plan state it has not observed.

Committing a production batch requires the request to carry `expected_hub_version` holding the client's last observed `version` of the parent hub. Because every batch commit, cancel, or completion rewrites the hub's `committed_dozens_today`, a stale hub view would run the capacity check against stale data; a mismatch with the hub's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Requests to any other operation must not include an expected-version parameter, and the server does not perform an optimistic check there.

### 2.10. Validation Precedence

When several checks could reject the same request, the server applies them in a fixed precedence order, and the earliest failing check determines the error returned. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint (`ERR_UNAUTHORIZED`); third, existence of every path resource, validated left to right (`ERR_NOT_FOUND`); fourth, state admissibility of the target resource for the requested transition (`ERR_INVALID_STATE`, with the special case that a transition attempted against a resource already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`, also HTTP 409); fifth, freshness safety (`ERR_FRESHNESS_VIOLATION`); sixth, temporal window conflicts (`ERR_WINDOW_OVERLAP`); seventh, territory integrity (`ERR_TERRITORY_VIOLATION`); eighth, the mix license quota (`ERR_LICENSE_QUOTA_EXCEEDED`); ninth, capacity limits (`ERR_CAPACITY_EXCEEDED`); tenth, cross-scope referential integrity (`ERR_CROSS_SCOPE_REFERENCE`); and eleventh, optimistic-concurrency version checks (`ERR_STALE_VERSION`). The cross-scope rule applies to every endpoint that takes an entity reference in its request body: the referenced entity must exist and must belong to the same network scope as the resource being written — a batch reference must resolve to a batch of the operating hub, a variety reference must resolve to a variety of the operating network, and a shipment's batch must come from the same hub as the route it is staged on. The cross-scope rule applies to every endpoint that takes an entity reference in its request body: the referenced entity must exist and must belong to the same network scope as the resource being written — a batch reference must resolve to a batch of the operating hub, a variety reference must resolve to a variety of the operating network, and a shipment's batch must come from the same hub as the route it is staged on. A request that fails two checks always surfaces the earlier one — a stale pull attempted after the deadline on a shipment in the wrong state reports the state error, not the freshness error.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Network: Networks, Hubs, and Doors

A `NetworkAdmin` begins by creating a network with a globally unique `network_code` and a human-readable `display_name`. The new network starts with `network_posture` set to `OPEN` and an `ops_run_index` of zero — a monotonic heartbeat counter that only advances at ops-run checkpoints. The network also carries a `stale_credit_pool_cents`, the running total of uncredited stale-pull liability across the network, which starts at zero and is never allowed to go negative.

Hubs come next. Each hub is created inside a network — the system records the owning `network_id` — with a `hub_code` unique within the network, a `daily_capacity_dozens` ceiling that must be greater than zero, and a `territory_region` key used for door territory allocation. The hub also tracks `committed_dozens_today`, the dozens committed by batches against the current calendar day; this figure is recomputed on every batch commit, cancel, or completion and is the pivot of the capacity check at commit time.

Doors are the retail endpoints of the network. A door is created with a `door_kind` of `THEATER`, `SPOKE`, `GROCERY`, or `PARTNER`, an `ownership` of `COMPANY` or `FRANCHISE`, and its own `territory_region`. Territory integrity is enforced at door creation: a `FRANCHISE` door's `territory_region` must equal the `territory_region` of its supplying hub, while `COMPANY` doors are exempt from that match. Theater stores are self-supplied — a `THEATER` door must be created with a null `hub_id` — while `SPOKE`, `GROCERY`, and `PARTNER` doors name the hub that supplies them through `hub_id`. Violating any of these territory rules is rejected with `ERR_TERRITORY_VIOLATION` (HTTP 422). A door's derived `door_status` starts at `ACTIVE`; its compound derivation is described in §3.2 and §3.6. Like the other status fields in the system — a line's `line_status`, a batch's `batch_status`, a plan's `mix_plan_status`, a route's `route_status`, a stop's `stop_status`, a fundraiser order's `fundraiser_status`, a credit's `credit_state`, and a hot-light window's `window_status` — the door's status is computed by the system from the lifecycle transitions described in §3 and is never set directly by a client payload. Like the other status fields in the system — a line's `line_status`, a batch's `batch_status`, a plan's `mix_plan_status`, a route's `route_status`, a stop's `stop_status`, a fundraiser order's `fundraiser_status`, a credit's `credit_state`, and a hot-light window's `window_status` — the door's status is computed by the system from the lifecycle transitions described in §3 and is never set directly by a client payload. Doors also carry `credit_balance_cents`, the stale-pull credit currently owed to the door and never negative, and `open_dispute_count`, the number of stale credits for this door currently sitting in `DISPUTED`.

Closing a door is deliberately hard. A `NetworkAdmin` may close an `ACTIVE` or `SUSPENDED` door only when no fundraiser order for the door sits in `SUBMITTED`, `APPROVED`, `SCHEDULED`, or `READY`; when no route stop for the door sits in `PENDING` or `ARRIVED`; and when no stale credit for the door sits in `PROVISIONAL` or `DISPUTED`. Closing is terminal — the door moves to `CLOSED` and any future-dated mix plans for the door are superseded. A suspended door can be reinstated by a `NetworkAdmin` only when its `open_dispute_count` has dropped below three and its supplying hub has at least one line in `OPERATIONAL` or `DEGRADED`; reinstatement returns the door to `ACTIVE`. A `NetworkAdmin` may also suspend a door manually, which triggers a posture recompute; while suspended, the door's published mix plans for future dates remain on record but batch allocation to the door halts.

### 3.2. Equipment Lines, Maintenance, and the Cascades They Trigger

Within each hub a `HubManager` registers equipment lines. A line has a `line_kind` of `CONTINUOUS_FRYER` or `GLAZE_WATERFALL`, a `rated_dozens_per_hour` throughput that must be greater than zero, and a `service_interval_hours` cadence, also greater than zero, defining the hours allowed between mandatory services. Lines are born `OPERATIONAL`, and the derived `effective_dozens_per_hour` equals the rated throughput while operational, drops to the rated throughput multiplied by 0.6 and rounded down to a whole number while `DEGRADED`, and is zero while in `MAINTENANCE` or `DECOMMISSIONED`. The line's `hours_since_service` accumulates production hours as batches complete and drives the maintenance regime.

A `HubManager` may mark an `OPERATIONAL` line `DEGRADED` once the line has worked at least half of its service interval — that is, when `hours_since_service` has reached at least 0.5 times `service_interval_hours`. Degradation recomputes the effective throughput and increments the line's `version`.

Maintenance can be entered from either `OPERATIONAL` or `DEGRADED`, but only when no batch is currently `RUNNING` on the line — attempting it while a batch runs is a state error. Starting maintenance fires a broad cascade: every batch `SCHEDULED` on the line for today is moved to `CANCELLED`; each such batch that had been `COMMITTED` decrements the hub's `committed_dozens_today` by its `planned_dozens`; and the network's posture is recomputed. Completing maintenance returns the line to `OPERATIONAL`, resets `hours_since_service` to zero, restores the effective throughput to the rated figure, and recomputes posture again. The system can also force a line into maintenance itself: at each ops-run checkpoint, any line whose `hours_since_service` has reached or passed its `service_interval_hours` auto-enters maintenance with the same cancel cascade.

Decommissioning is the terminal act. From `OPERATIONAL` or `DEGRADED`, a `HubManager` may decommission a line only when no batch on it is in `SCHEDULED`, `COMMITTED`, or `RUNNING`. The line becomes `DECOMMISSIONED`, posture is recomputed, and — critically — if the decommission leaves the hub with no remaining line in `OPERATIONAL` or `DEGRADED`, every door supplied exclusively by that hub flips to `SUSPENDED`. That door cascade is the mechanism by which posture rule 1 (a hub with no working lines suspends the network) and door suspension travel together.

### 3.3. Varieties, Production Batches, and the Allocation Waterfall

The variety catalog lives at network scope. A `NetworkAdmin` creates a variety with a `variety_code` unique within the network, a `collection_kind` of `CORE`, `SEASONAL`, or `LICENSED`, a selling window from `active_from` (inclusive) to `active_until` (exclusive, and strictly later than `active_from` — an inverted window is rejected with `ERR_WINDOW_OVERLAP`), and a `unit_cost_cents` production cost that may be zero but not negative. A variety's `variety_status` is `ACTIVE` until the logical clock reaches `active_until`, at which point the variety becomes `EXPIRED`; a variety whose `active_until` is already at or behind the current clock at creation is born `EXPIRED`.

Production happens in batches. A `HubManager` schedules a batch by naming the `equipment_line_id` it will run on, the `production_date`, and a `planned_dozens` size that must be greater than zero; the batch starts in `SCHEDULED`, with `produced_dozens`, `fresh_until`, and `yield_rate` all unset. Scheduling alone commits nothing against hub capacity.

Committing a batch — moving it from `SCHEDULED` to `COMMITTED` — is the capacity gate, and it is OCC-guarded as described in §2.9 via `expected_hub_version`. Commit is permitted only when the batch's line is `OPERATIONAL` or `DEGRADED`, when the hub's `committed_dozens_today` plus the batch's `planned_dozens` does not exceed the hub's `daily_capacity_dozens` (violations are rejected with `ERR_CAPACITY_EXCEEDED`), and when the network posture is `OPEN` or `DEGRADED`. A successful commit adds `planned_dozens` to `committed_dozens_today` and bumps both the hub's and the batch's `version`.

Starting a committed batch moves it to `RUNNING`; the line must be `OPERATIONAL` or `DEGRADED`, and no other batch may be `RUNNING` on the same line — a second start on a busy line is rejected with `ERR_LINE_BUSY` (HTTP 409). Completion is where the batch forks. The `HubManager` completes a running batch by supplying the actual `produced_dozens` count. If the produced dozens reach at least 0.85 times the planned dozens — the minimum yield rate — the batch lands in `COMPLETED`: `fresh_until` is set to the completion time plus twelve hours, `yield_rate` is recorded as produced over planned, the line's `hours_since_service` grows by the elapsed production hours (the planned dozens divided by the line's effective hourly throughput), the hub's `committed_dozens_today` is decremented by `planned_dozens`, and the mix allocation waterfall runs for that production date across the hub's doors. If produced dozens fall short of the 0.85 yield floor, the batch lands in `SHORTFALL` instead: the hub's committed figure is still decremented, the allocation waterfall runs in its shortfall redistribution mode, and network posture is recomputed because shortfalls feed the `DEGRADED` rule. Either way the batch's and hub's `version` increment. A batch in `SCHEDULED` or `COMMITTED` may instead be cancelled outright — by the `HubManager` or by the maintenance cascade — and a cancelled `COMMITTED` batch decrements `committed_dozens_today` by its planned size.

The allocation waterfall determines how completed production reaches plans and orders. For a hub and production date, the available pool is the sum of `produced_dozens` over all `COMPLETED` batches minus dozens already allocated to mix allocations and fundraiser reservations for that date. Allocation proceeds in a pinned order — fixed before any remainder is computed: first, fundraiser reservations in `READY` or `SCHEDULED`, ordered by `pickup_at` ascending, with ties broken by the fundraiser order's `created_at` ascending (never by id); second, mix plan lines of `PUBLISHED` or `LOCKED` plans, ordered by the plan's `effective_date` ascending, then the door's `created_at` ascending, then the line's own `created_at` ascending. Each bucket in turn takes the smaller of its remaining need and the remaining available dozens; remainders never round up. The resulting figures land in each mix plan line's `allocated_dozens`, recomputed on every run.

### 3.4. Mix Plans and the License Quota

Each door's daily assortment is expressed as a mix plan. A `DoorManager` creates a plan for their door by supplying the `effective_date` it takes effect; the plan starts in `DRAFT`, with `total_planned_dozens` at zero and `license_quota_dozens` at zero. Lines are upserted into the draft one variety at a time: each line names a `variety_id` and a non-negative `planned_dozens`, and the system records the owning `mix_plan_id` on every line. Every upsert or removal recomputes the plan's `total_planned_dozens` (the sum of all line dozens) and `license_quota_dozens` (the sum over lines whose variety is `LICENSED`). Lines carry `allocated_dozens`, which starts at zero and is filled in by the allocation waterfall, not by the door manager.

Publishing is the plan's moment of truth, and it is OCC-guarded via `expected_mix_plan_version` as described in §2.9. Publish is permitted only when the door is `ACTIVE`, when every line's variety is `ACTIVE` for the plan's effective date — a line pointing at a variety whose window has expired for that date is rejected with `ERR_VARIETY_EXPIRED` — and when the license quota holds: with a non-empty plan, `license_quota_dozens` must not exceed one quarter of `total_planned_dozens` rounded down to a whole number, and a breach is rejected with `ERR_LICENSE_QUOTA_EXCEEDED`. When the publish succeeds, any previously `PUBLISHED` plan for the same door and the same `effective_date` is cascaded to `SUPERSEDED`, and its lines' `allocated_dozens` are reset to zero — the newer plan inherits the day's allocation.

Plans lock as reality catches up with them. A published plan transitions `PUBLISHED` → `LOCKED` automatically when a route covering that door with a `service_date` matching the plan's `effective_date` is dispatched, and a `DoorManager` may also lock a published plan manually, provided at least one route stop for the door exists on a `LOCKED` or `DISPATCHED` route whose service date equals the effective date. Locking makes the plan immutable: line upserts against a `LOCKED` or `SUPERSEDED` plan are rejected with `ERR_MIX_PLAN_LOCKED` (HTTP 409). `SUPERSEDED` and `LOCKED` are the terminal states of the plan lifecycle.

### 3.5. Routes, Stops, and Shipments

A `RoutePlanner` builds each day's distribution as a route out of a hub, created with a `route_code` unique within the hub, the `service_date` it will run, and a `vehicle_capacity_dozens` limit that must be greater than zero. Routes start in `PLANNING`. Stops are added while the route plans: each stop names the `door_id` served — the system records the owning `route_id` on the stop — a `sequence_no` that must be at least 1 and unique within the route — duplicates are rejected with `ERR_DUPLICATE_SEQUENCE` — and a half-open delivery window from `window_start` (inclusive) to `window_end` (exclusive, strictly later than `window_start`). Two stops on the same route that share a door must not have overlapping windows; the half-open convention means adjacency — one window's `window_end` equal to the next stop's `window_start` — is allowed. An overlap is rejected with `ERR_WINDOW_OVERLAP`. Once a route is locked, no new stops are accepted.

Locking the route (`PLANNING` → `LOCKED`) requires at least one stop and requires the stops' window spans to total at least 30 minutes; a route failing either condition is rejected with `ERR_ROUTE_NOT_LOCKABLE` (HTTP 422). Dispatching (`LOCKED` → `DISPATCHED`) is the point of no return: the route's `loaded_dozens` — the sum of `dozens_shipped` across its shipments — must not exceed `vehicle_capacity_dozens` (`ERR_CAPACITY_EXCEEDED` otherwise), every shipment on the route must be `STAGED`, and every referenced batch must be `COMPLETED` with its `fresh_until` set. Dispatch cascades: every shipment moves `STAGED` → `IN_TRANSIT`, and every mix plan for the stops' doors whose `effective_date` equals the route's `service_date` moves `PUBLISHED` → `LOCKED`.

Shipments are staged against stops before dispatch by a `RoutePlanner`, each naming the `production_batch_id` goods were drawn from and a `dozens_shipped` count greater than zero; the system records the receiving `route_stop_id` on the shipment, and staging adds to the route's `loaded_dozens`. Every shipment lives on two independent state dimensions. The first, `delivery_status`, runs `STAGED` → `IN_TRANSIT` → one of `DELIVERED`, `PARTIAL`, or `FAILED`. The second, `credit_status`, runs `NONE` → `PENDING_PULL` → one of `CREDITED` or `DISPUTED`, tracking the stale-credit lifecycle described in §3.6. The two dimensions evolve independently on the same entity. A shipment also carries `freshness_override`, a boolean defaulting to false that records whether the receiver accepted goods past their `fresh_until` under a documented override — this flag feeds the provisional credit calculation.

On the road, a `RouteDriver` works the stops. Arriving is permitted only while the route is `DISPATCHED` and only within the stop's window, with a 45-minute late-arrival grace: an arrival attempted before `window_start` is rejected as a state error, an arrival attempted at or after `window_end` but before 45 minutes past it is accepted and the late arrival is recorded, and an arrival attempted at or beyond 45 minutes past `window_end` — when the stop is no longer late-arrival-eligible — is rejected with `ERR_STOP_WINDOW_PASSED`. Before a stop can be delivered, the driver records the accepted count on each of the stop's shipments via `dozens_delivered`. Delivering the stop then moves it `ARRIVED` → `DELIVERED` and cascades each shipment: where `dozens_delivered` equals `dozens_shipped` the shipment becomes `DELIVERED`; where fewer dozens were accepted the shipment becomes `PARTIAL` and the undelivered dozens become eligible for stale pull. A stop can also be missed — either marked missed by the driver, or auto-missed by the system when the clock passes `window_end` with the stop still undelivered (a stop still `PENDING` at that moment is auto-missed as well). Missing a stop fails all of its shipments — `delivery_status` becomes `FAILED`, making every shipped dozen eligible for stale pull — and reruns the allocation waterfall so the returned dozens flow back to hub availability. When every stop on a dispatched route has reached `DELIVERED`, `MISSED`, or `CREDITED`, the system moves the route to `COMPLETED` and recomputes network posture. A delivered stop can still move `DELIVERED` → `CREDITED` once at least one stale credit exists for its shipments and all of those credits have been resolved.

Reconciliation closes the loop. A `RoutePlanner` reconciles a `COMPLETED` route, and the cascade reaches back through the day: every stale credit in `PROVISIONAL` tied to the route's shipments is recomputed under the final variant of the credit calculation and transitions `PROVISIONAL` → `FINALIZED`; each affected door's `credit_balance_cents` is adjusted by the per-credit delta between `final_credit_cents` and `provisional_credit_cents`; and the network's `stale_credit_pool_cents` is recomputed as the sum of `final_credit_cents` over `FINALIZED` credits minus payouts already made on `RESOLVED` credits. A shipment whose credit finalized without dispute also moves its `credit_status` from `PENDING_PULL` to `CREDITED`. Reconciliation is terminal for the route: it lands in `RECONCILED`, and `RECONCILED` is the route's only terminal state. Reconciliation is terminal for the route: it lands in `RECONCILED`, and `RECONCILED` is the route's only terminal state.

### 3.6. Stale Pulls, Credits, and Disputes

Freshness is enforced in hours: a completed batch's `fresh_until` is its completion time plus twelve hours, and the same-day pull regime gives doors until 23:59 local time on the batch's `production_date` to report stale product. When a `DoorManager` reports a pull, they name the `shipment_id` and the `pulled_dozens` (greater than zero). The pull is admissible only when the shipment's `delivery_status` is `DELIVERED`, `PARTIAL`, or `FAILED`, and only while the logical clock is still before the same-day deadline — a pull attempted after 23:59 on the production date is rejected with `ERR_FRESHNESS_VIOLATION` (HTTP 422). A valid pull creates a stale credit in `PROVISIONAL`, computes `provisional_credit_cents` under the provisional variant, and moves the shipment's `credit_status` from `NONE` to `PENDING_PULL`.

The credit amount is tiered on volume. The base value is `pulled_dozens` multiplied by 1200 cents per dozen. The tier rate depends on the pull size: pulls of at least 24 dozen use a rate of 0.80; pulls of at least 6 dozen but fewer than 24 use 0.65; anything smaller uses 0.50. The raw credit is the base multiplied by the applicable rate, and the rounding order is pinned — the credit is rounded once, half-up, to integer cents, per credit and never per dozen. The provisional variant, computed at pull time, uses the pulled dozens as reported and, when the shipment's `freshness_override` flag is set, halves the applicable rate before the single rounding step. The final variant, computed at route reconciliation or dispute resolution, ignores `freshness_override` entirely but applies a late-delivery penalty: if the stop arrived after its `window_end`, the credit is multiplied by 0.9 before the same single rounding step. `final_credit_cents` stays unset until finalization.

Disputes give the door recourse and give the network a governance lever. A `DoorManager` may dispute a credit only while it is `PROVISIONAL` and only within 48 hours of the pull time; the credit moves to `DISPUTED`, the door's `open_dispute_count` increments, and if that count reaches three the door is automatically suspended — the conditional cascade that makes dispute hygiene an operational concern. A `NetworkAdmin` resolves a disputed credit by supplying a `resolution_credit_cents` amount: the credit's `final_credit_cents` is set to that amount, the door's `credit_balance_cents` is adjusted to the final figure, the dispute count decrements, and a door that was suspended solely because of disputes returns to `ACTIVE` once the count drops below three and its supplying hub has a working line. Resolving a `FINALIZED` credit instead pays it out: the network's `stale_credit_pool_cents` is decremented by `final_credit_cents`, and a resolution that would push the pool negative is rejected with `ERR_CAPACITY_EXCEEDED`. `FINALIZED` and `RESOLVED` are terminal for the credit.

### 3.7. Fundraiser Orders

The fundraising channel lets organizations pre-book dozens for pickup at a theater or spoke door. A `DoorManager` submits an order with the `organization_name`, the `requested_dozens` (greater than zero), and the scheduled `pickup_at`. The lead-time rule bites at submission: `pickup_at` must be at least the configured lead-time horizon `LEAD_TIME_HOURS` — 8 hours — after the submission moment, and a submission inside the lead time is rejected with `ERR_FRESHNESS_VIOLATION`. The order starts in `SUBMITTED`.

Approval rechecks the lead time, requires the door to be `ACTIVE`, and requires that `requested_dozens` not exceed the door's share of hub capacity on the pickup date. On approval the system computes `quoted_total_cents` under the fundraiser pricing schedule. Pricing is marginal and tiered by cumulative dozens: the first 25 dozen of the order price at 700 cents per dozen, dozens 26 through 100 price at 650 cents per dozen, and every dozen beyond 100 prices at 600 cents. The rounding order is pinned and nested: each implied dozen line is priced at its tier rate, any organization discount is applied to that line, and the line is rounded half-up to integer cents before the lines are summed into the quote. The discount is an `organization_discount_pct` that defaults to zero; the organization is treated as a registered licensed charity when its `organization_name` contains the substring "charity" (case-insensitive), and for such an organization a 0.10 discount applies per dozen line before rounding. Approval is not a dead end: a `DoorManager` can return an approved order for changes, cycling it back to `SUBMITTED` and clearing `quoted_total_cents` to null — it is recomputed from current tiers on the next approval, which is the intended renegotiation loop.

Scheduling an approved order requires a covering batch: a `COMMITTED` or `COMPLETED` batch at the supplying hub for the pickup date whose coverage reaches `requested_dozens`. Scheduling reserves the dozens — if the covering batch does not already account for them, the hub's `committed_dozens_today` for the pickup date grows by `requested_dozens`. Marking the order ready requires the covering batch to be `COMPLETED` with `produced_dozens` at least `requested_dozens`; at that moment the system mints the order's `pickup_code`. Fulfillment is the handshake: the driver of the pickup presents the code, the request carries `pickup_code`, a mismatch is rejected with `ERR_PICKUP_CODE_MISMATCH` (HTTP 422), and fulfillment must happen no later than the configured grace `PICKUP_GRACE_HOURS` — 4 hours — after `pickup_at`; a fulfillment attempted strictly past that grace deadline is a freshness violation (fulfillment exactly at the deadline is still admissible). Orders still `READY` when the clock passes `pickup_at` plus the grace window expire automatically, releasing their reserved dozens back to hub availability. An order may be cancelled by the `DoorManager` from either `SUBMITTED` or `APPROVED`; `FULFILLED`, `CANCELLED`, and `EXPIRED` are terminal.

### 3.8. Hot-Light Theater Windows

The hot light is the theater store's demand signal, and only `THEATER` doors may have windows — scheduling one against any other door kind is a territory violation. A `DoorManager` schedules a window with `lit_start` (inclusive) and `lit_end` (exclusive, strictly later), plus an optional `demand_response_extend_minutes` that defaults to zero and must lie between 0 and 90. Windows for the same door must not overlap, on the same half-open convention as route stops. Overlap is judged against each existing window's originally scheduled span: a later demand-response extension that pushes a window's `lit_end` out does not retroactively invalidate another window that was non-overlapping at creation. Only non-terminal windows — those not yet `COMPLETED` or `CANCELLED` — participate in the overlap check. The window starts `SCHEDULED`.

Ignition — `SCHEDULED` → `LIT` — happens automatically when the clock reaches `lit_start`, or early at the door manager's hand, but only when at least one batch completed today at the door's hub still has `fresh_until` in the future, and only when no other window for the door is currently `LIT` or `EXTENDED`. Lighting without a fresh batch behind it is rejected with `ERR_FRESHNESS_VIOLATION`. While lit, the door manager may request a demand-response extension, supplying `demand_response_extend_minutes` between 1 and 90. The grant is capped by the fresh stock on hand: the system sums, across today's `COMPLETED` batches at the door's hub whose `fresh_until` is still in the future, the produced dozens minus already-allocated dozens; when that fresh figure reaches at least 120 dozen the cap is 90 minutes, when it reaches at least 30 dozen but fewer than 120 the cap is 45 minutes, and below 30 dozen the cap is zero. The granted extension is the smaller of the request and the cap; a request exceeding the cap is rejected with `ERR_DEMAND_CAP_EXCEEDED` (HTTP 422). A granted extension moves the window to `EXTENDED` and pushes `lit_end` out by the granted minutes. Whether `LIT` or `EXTENDED`, the window completes automatically when the clock reaches `lit_end`; a still-`SCHEDULED` window may be cancelled. `COMPLETED` and `CANCELLED` are terminal.

### 3.9. Ops-Run Checkpoints

The ops-run checkpoint is the network's periodic full reset, run by a `NetworkAdmin`. Each checkpoint performs a full posture recompute from scratch rather than an incremental update, auto-cancels any `SCHEDULED` batches whose `production_date` has fallen in the past, auto-expires any `READY` fundraiser orders whose pickup grace has elapsed, forces any equipment line whose `hours_since_service` has reached its `service_interval_hours` into maintenance with the standard cancel cascade, recomputes the network's `stale_credit_pool_cents`, advances the network's `ops_run_index` by one, and increments the network's `version`. The checkpoint reports back the new `ops_run_index`, the `expired_batch_count`, the `expired_order_count`, and the recomputed `network_posture`. Because checkpoints are the only mechanism that sweeps expired scheduled work, operators should treat them as the daily close of the production book.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, cascades triggered by explicit calls, and the ops-run checkpoint — return `200 OK`. All resources are mounted under the `/networks` prefix. Request payloads, derived fields, and side effects for each operation are defined in the narratives of §2 and §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/networks/_clock/set_current_utc` | Set the logical clock | NetworkAdmin |
| POST | `/networks` | Create a network | NetworkAdmin |
| GET | `/networks/{id}` | Get a network | NetworkAdmin, HubManager, RoutePlanner, DoorManager, RouteDriver |
| GET | `/networks` | List networks (paginated) | NetworkAdmin |
| POST | `/networks/{id}/ops-runs` | Run ops-run checkpoint | NetworkAdmin |
| POST | `/networks/{nid}/hubs` | Create a hub | NetworkAdmin |
| GET | `/networks/{nid}/hubs/{id}` | Get a hub | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/{nid}/hubs` | List hubs in network | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/hubs` | Flat filtered list of hubs across networks | NetworkAdmin |
| GET | `/networks/hubs/{id}` | Get hub by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/hubs/{hid}/lines` | Create equipment line | HubManager |
| GET | `/networks/{nid}/hubs/{hid}/lines/{id}` | Get equipment line | NetworkAdmin, HubManager |
| GET | `/networks/{nid}/hubs/{hid}/lines` | List lines for hub | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/lines` | Flat filtered list of equipment lines across hubs | NetworkAdmin, HubManager |
| GET | `/networks/lines/{id}` | Get equipment line by id (flat) | NetworkAdmin, HubManager |
| POST | `/networks/{nid}/hubs/{hid}/lines/{id}/degrade` | Mark line DEGRADED | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/lines/{id}/maintenance/start` | Start maintenance; cancels today's scheduled batches on the line | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/lines/{id}/maintenance/complete` | Complete maintenance | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/lines/{id}/decommission` | Decommission line | HubManager |
| POST | `/networks/{nid}/doors` | Create a door | NetworkAdmin |
| GET | `/networks/{nid}/doors/{id}` | Get a door | NetworkAdmin, HubManager, RoutePlanner, DoorManager |
| GET | `/networks/{nid}/doors` | List doors (filterable) | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/doors` | Flat filtered list of doors across networks | NetworkAdmin |
| GET | `/networks/doors/{id}` | Get door by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{id}/suspend` | Manually suspend door | NetworkAdmin |
| POST | `/networks/{nid}/doors/{id}/reinstate` | Reinstate suspended door | NetworkAdmin |
| POST | `/networks/{nid}/doors/{id}/close` | Close door | NetworkAdmin |
| POST | `/networks/{nid}/varieties` | Create variety | NetworkAdmin |
| GET | `/networks/{nid}/varieties/{id}` | Get variety | NetworkAdmin, DoorManager, HubManager |
| GET | `/networks/{nid}/varieties` | List varieties | NetworkAdmin, DoorManager, HubManager |
| GET | `/networks/varieties` | Flat filtered list of varieties across networks | NetworkAdmin |
| GET | `/networks/varieties/{id}` | Get variety by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{did}/mix-plans` | Create mix plan (DRAFT) | DoorManager |
| GET | `/networks/{nid}/doors/{did}/mix-plans/{id}` | Get mix plan | NetworkAdmin, DoorManager |
| GET | `/networks/{nid}/doors/{did}/mix-plans` | List mix plans for door | NetworkAdmin, DoorManager |
| POST | `/networks/{nid}/doors/{did}/mix-plans/{mpid}/lines` | Upsert a mix plan line | DoorManager |
| GET | `/networks/{nid}/doors/{did}/mix-plans/{mpid}/lines` | List lines of a mix plan | NetworkAdmin, DoorManager |
| GET | `/networks/mix-plans` | Flat filtered list of mix plans across doors | NetworkAdmin |
| GET | `/networks/mix-plans/{id}` | Get mix plan by id (flat) | NetworkAdmin |
| GET | `/networks/mix-plan-lines` | Flat filtered list of mix plan lines | NetworkAdmin |
| GET | `/networks/mix-plan-lines/{id}` | Get mix plan line by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{did}/mix-plans/{id}/publish` | Publish mix plan (OCC-guarded) | DoorManager |
| POST | `/networks/{nid}/doors/{did}/mix-plans/{id}/lock` | Manually lock a published mix plan | DoorManager |
| POST | `/networks/{nid}/hubs/{hid}/batches` | Schedule production batch | HubManager |
| GET | `/networks/{nid}/hubs/{hid}/batches/{id}` | Get batch | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/{nid}/hubs/{hid}/batches` | List batches for hub | NetworkAdmin, HubManager, RoutePlanner |
| GET | `/networks/batches` | Flat filtered list of batches across hubs | NetworkAdmin |
| GET | `/networks/batches/{id}` | Get batch by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/hubs/{hid}/batches/{id}/commit` | Commit batch against hub capacity (OCC-guarded) | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/batches/{id}/start` | Start running a committed batch | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/batches/{id}/complete` | Complete batch; yields COMPLETED or SHORTFALL | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/batches/{id}/cancel` | Cancel batch | HubManager |
| POST | `/networks/{nid}/hubs/{hid}/routes` | Create route (PLANNING) | RoutePlanner |
| GET | `/networks/{nid}/hubs/{hid}/routes/{id}` | Get route | NetworkAdmin, RoutePlanner, RouteDriver |
| GET | `/networks/{nid}/hubs/{hid}/routes` | List routes for hub | NetworkAdmin, RoutePlanner, RouteDriver |
| GET | `/networks/routes` | Flat filtered list of routes across hubs | NetworkAdmin |
| GET | `/networks/routes/{id}` | Get route by id (flat) | NetworkAdmin |
| GET | `/networks/route-stops` | Flat filtered list of route stops | NetworkAdmin |
| GET | `/networks/route-stops/{id}` | Get route stop by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops` | Add stop to route (PLANNING only) | RoutePlanner |
| GET | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops` | List stops of route | NetworkAdmin, RoutePlanner, RouteDriver |
| GET | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{id}` | Get a stop | NetworkAdmin, RoutePlanner, RouteDriver |
| POST | `/networks/{nid}/hubs/{hid}/routes/{id}/lock` | Lock route | RoutePlanner |
| POST | `/networks/{nid}/hubs/{hid}/routes/{id}/dispatch` | Dispatch route; shipments go IN_TRANSIT; mix plans lock | RoutePlanner |
| POST | `/networks/{nid}/hubs/{hid}/routes/{id}/reconcile` | Reconcile completed route; finalize stale credits | RoutePlanner |
| POST | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{id}/arrive` | Mark stop arrived | RouteDriver |
| POST | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{id}/deliver` | Deliver stop; all stop shipments recorded | RouteDriver |
| POST | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{id}/miss` | Mark stop missed | RouteDriver |
| POST | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{sid}/shipments` | Stage a shipment at a stop | RoutePlanner |
| GET | `/networks/{nid}/hubs/{hid}/routes/{rid}/stops/{sid}/shipments` | List shipments at stop | NetworkAdmin, RoutePlanner, RouteDriver, DoorManager |
| GET | `/networks/{nid}/shipments/{id}` | Get shipment by id | NetworkAdmin, RoutePlanner, DoorManager |
| GET | `/networks/shipments` | Flat filtered list of shipments | NetworkAdmin |
| GET | `/networks/shipments/{id}` | Get shipment by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/shipments/{id}/record-delivery` | Record dozens_delivered for a shipment | RouteDriver |
| POST | `/networks/{nid}/doors/{did}/stale-credits` | Report same-day stale pull; creates PROVISIONAL credit | DoorManager |
| GET | `/networks/{nid}/doors/{did}/stale-credits` | List stale credits for door | NetworkAdmin, DoorManager |
| GET | `/networks/{nid}/doors/{did}/stale-credits/{id}` | Get stale credit | NetworkAdmin, DoorManager |
| GET | `/networks/stale-credits` | Flat filtered list of stale credits | NetworkAdmin |
| GET | `/networks/stale-credits/{id}` | Get stale credit by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{did}/stale-credits/{id}/dispute` | Dispute a provisional credit | DoorManager |
| POST | `/networks/{nid}/doors/{did}/stale-credits/{id}/resolve` | Resolve a disputed or finalized credit (payout) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders` | Submit fundraiser order | DoorManager |
| GET | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}` | Get fundraiser order | NetworkAdmin, DoorManager |
| GET | `/networks/fundraiser-orders` | Flat filtered list of fundraiser orders | NetworkAdmin |
| GET | `/networks/fundraiser-orders/{id}` | Get fundraiser order by id (flat) | NetworkAdmin |
| GET | `/networks/{nid}/doors/{did}/fundraiser-orders` | List fundraiser orders for door | NetworkAdmin, DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/approve` | Approve fundraiser order; computes quote | DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/return-for-changes` | Return approved order to SUBMITTED | DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/schedule` | Schedule against a covering batch | DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/ready` | Mark order ready; issues pickup code | DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/fulfill` | Fulfill with pickup code | DoorManager |
| POST | `/networks/{nid}/doors/{did}/fundraiser-orders/{id}/cancel` | Cancel fundraiser order | DoorManager |
| POST | `/networks/{nid}/doors/{did}/hot-light-windows` | Schedule hot-light window (THEATER doors only) | DoorManager |
| GET | `/networks/{nid}/doors/{did}/hot-light-windows` | List hot-light windows for door | NetworkAdmin, DoorManager |
| GET | `/networks/{nid}/doors/{did}/hot-light-windows/{id}` | Get hot-light window | NetworkAdmin, DoorManager |
| GET | `/networks/hot-light-windows` | Flat filtered list of hot-light windows | NetworkAdmin |
| GET | `/networks/hot-light-windows/{id}` | Get hot-light window by id (flat) | NetworkAdmin |
| POST | `/networks/{nid}/doors/{did}/hot-light-windows/{id}/ignite` | Manually light window | DoorManager |
| POST | `/networks/{nid}/doors/{did}/hot-light-windows/{id}/extend` | Demand-response extension | DoorManager |
| POST | `/networks/{nid}/doors/{did}/hot-light-windows/{id}/cancel` | Cancel scheduled window | DoorManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FRESHNESS_VIOLATION` | 422 |
| `ERR_WINDOW_OVERLAP` | 422 |
| `ERR_TERRITORY_VIOLATION` | 422 |
| `ERR_LICENSE_QUOTA_EXCEEDED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_CROSS_SCOPE_REFERENCE` | 422 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_LINE_BUSY` | 409 |
| `ERR_PICKUP_CODE_MISMATCH` | 422 |
| `ERR_ROUTE_NOT_LOCKABLE` | 422 |
| `ERR_STOP_WINDOW_PASSED` | 422 |
| `ERR_DEMAND_CAP_EXCEEDED` | 422 |
| `ERR_VARIETY_EXPIRED` | 422 |
| `ERR_DUPLICATE_SEQUENCE` | 422 |
| `ERR_MIX_PLAN_LOCKED` | 409 |
