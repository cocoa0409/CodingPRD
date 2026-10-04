# Multimodal Shipment Visibility API — Product Requirements Document

## 1. Introduction

Shippers lose visibility the moment freight leaves the dock. A single order may travel by ocean container, rail, parcel, and truckload under four different carriers, each reporting through a different channel — a telematics provider, a transportation management system, or nothing more structured than a phone call typed in by hand. This document specifies the Multimodal Shipment Visibility API: a network platform that onboards carrier data connections, certifies their feed quality before they carry production traffic, resolves which shipment belongs to which purchase order, predicts arrival times with explicit confidence intervals, and routes delay exceptions to customer-service queues before the consignee calls asking where their freight is.

The platform treats carrier data quality as a first-class operational concern rather than an afterthought. Every connection is scored on a recurring checkpoint across timeliness, payload completeness, and cadence adherence; connections that go silent are suspended automatically, and every shipment they feed is marked stale and re-planned with widened arrival uncertainty. Arrival estimates are computed from an event-sourced model: the shipment's current tracking state is derived by replaying its carrier-reported tracking events in a pinned order, so retroactive corrections (voiding an event) re-derive downstream state deterministically.

Access is partitioned across peer operational roles — network onboarding operators, carrier representatives, shipper representatives, customer-service agents, consignee viewers, and platform administrators — with an explicit data-sharing grant layer governing what carriers and consignees may see of a shipper's freight. This document is the sole specification of the system's externally visible behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The platform recognizes exactly six roles, spelled as follows: `PlatformAdmin`, `NetworkOps`, `CarrierRep`, `ShipperRep`, `CustomerService`, and `ConsigneeRep`. A request with either header missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the endpoint — or whose entity-backed ownership check fails — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a carrier (connections, shipments, appointments) compare the resource's carrier foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ShipperRep`, `X-User-ID` is the `id` of the acting `Shipper`; ownership checks on any resource that references a shipper (consignees, purchase orders, shipments, data-share grants, identity-link decisions) compare the resource's shipper foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ConsigneeRep`, `X-User-ID` is the `id` of the acting `Consignee`; the role is read-only, and every read it performs of another shipper's shipment data must be covered by an active data-share grant naming that consignee as grantee.
- When `X-User-Role` is `PlatformAdmin`, `NetworkOps`, or `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Ops-Run Epoch

The platform runs on a logical clock, not wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and the server never falls back to wall-clock time. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the clock never moves backwards, and attempting to set it to an instant earlier than the current logical time is rejected with `ERR_INVALID_REQUEST`. Everywhere this document says "now", it means the logical clock.

A second admin-only capability, the **ops-run checkpoint**, advances the quality and ETA epoch. Each invocation produces an `OpsRun` record carrying a monotonic `run_index` starting at 1, the logical-clock `executed_at` timestamp, and per-run counters: `connections_degraded` (connections auto-suspended for staleness in this run), `testing_connections_reset` (testing connections reset for expired windows), `etas_recomputed` (shipments whose ETA was recomputed), `alerts_created` (exception alerts created), and `alerts_escalated` (open high-severity alerts escalated). `OpsRun` records carry only `id` and `created_at` as common properties; they have no `updated_at` and no `version`.

### 2.5. Common Resource Properties and Identity

Primary resources — carriers, shippers, consignees, connections, purchase orders, facilities, shipments, identity links, exception alerts, appointments, and data-share grants — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation.
- `version` (integer): starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource, including mutations performed by cascading side effects.

Two entity kinds are deliberately lighter. `TrackingEvent` and `HeartbeatRecord` are append-only child records: each carries `id` and `created_at` only — both `updated_at` and `version` are absent from them.

### 2.6. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, the server validates path identifiers strictly left to right: each identifier must resolve to an existing resource before the next identifier to its right is examined, and the request is rejected with the not-found error for the first identifier that fails. A request that names a nonexistent shipper and a nonexistent purchase order beneath it fails with `ERR_SHIPPER_NOT_FOUND` (HTTP 404), never `ERR_PURCHASE_ORDER_NOT_FOUND`. The per-entity not-found errors are `ERR_CARRIER_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`, `ERR_CONSIGNEE_NOT_FOUND`, `ERR_CONNECTION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_IDENTITY_LINK_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, and `ERR_DATA_SHARE_GRANT_NOT_FOUND`, each with HTTP status 404.

### 2.7. Precision, Rounding, and Evaluation Order

All scores, percentages, and durations that the platform derives are integers expressed in whole units — whole minutes, whole percent, whole quality points. Wherever a rounding step is specified, the rounding method is **round half up**. Two calculations pin their rounding order explicitly and must be implemented exactly as described: the connection quality score rounds each of its three dimension values individually to a whole number before combining them and rounding the final result (nested rounding), and the ETA confidence halfwidth rounds only once, at the final step. The identity match score is the exception to the integer convention: it is a decimal with exactly two decimal places, and threshold comparisons against it are performed against exact decimal constants.

### 2.8. Optimistic Concurrency Control

Two write operations in the platform take a mandatory optimistic-concurrency field; no other endpoint takes a version field.

- Creating an identity link on a shipment requires the request to carry `expected_po_version`, holding the client's last observed `version` of the target purchase order. If the purchase order's current `version` has advanced beyond what the client observed — because another link was proposed, confirmed, or a confirmed link was rejected in the meantime — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A purchase order legitimately accumulates multiple links (multi-shipment orders), so no state precondition rejects a second proposal; the stale-version check is the only guard against acting on an outdated view of the order.
- Booking an appointment at a facility requires the request to carry `expected_facility_version`, holding the client's last observed `version` of the facility. A mismatch against the facility's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A facility legitimately accumulates many disjoint appointments, so again the stale-version check is the only guard.

Successful execution of either operation itself bumps the parent resource's `version` by 1 (the OCC parent bump), so any other client holding the pre-write version becomes stale.

### 2.9. Event-Sourced Tracking State

A shipment's `tracking_status` is never set directly by a client. It is **derived by replaying** the shipment's non-voided tracking events in a pinned order: ascending `event_time`, with ties broken by ascending `created_at` of the event record (never by `id`). The latest event in that order — the *effective event* — determines the status. Voiding an event is a retroactive correction: the event is excluded from the replay set and the shipment's status is re-derived from what remains. The same replay order governs which event counts as the latest position for ETA projection.

### 2.10. Channel Cadence and Connection Health

Each connection channel imposes a required heartbeat cadence, stored on the connection as `cadence_minutes`: a `TELEMATICS` connection must report every 15 minutes, a `TMS` connection every 240 minutes (4 hours), and a `MANUAL` connection every 1440 minutes (once a day). A heartbeat is considered `on_time` when the gap between its `recorded_at` ingest timestamp and the carrier-claimed `reported_at` send time is at most the connection's cadence. Connections carry two deliberately different quality views: `data_quality_score`, the authoritative epoch-windowed score recomputed only at ops-run checkpoints, and `instantaneous_quality_score`, recomputed from the latest heartbeat alone after every heartbeat ingest; both are null until their first computation. The connection's `health_status` is derived from the authoritative score: `HEALTHY` when the score is at least 70, `DEGRADED` when at least 40 but below 70, and `CRITICAL` when below 40; it is null until the connection has been scored.

### 2.11. Data-Share Visibility Between Parties

Shippers decide which outside parties may observe their freight. A `DataShareGrant` created by a shipper names a `grantee_type` (either `CARRIER` or `CONSIGNEE`), a `grantee_id` that resolves polymorphically — to a carrier `id` when the type is `CARRIER`, or to a consignee `id` belonging to the granting shipper when the type is `CONSIGNEE` — plus a `scope` of `ETA_ONLY` or `FULL_TRACE`, an `effective_from` start, and an `expires_at` end that must be strictly after `effective_from`. A `CarrierRep` or `ConsigneeRep` reading another shipper's shipment detail, tracking events, or alerts must be covered by an `ACTIVE` grant whose `grantee_id` matches their `X-User-ID` and whose window contains the current logical time; otherwise the read fails with `ERR_DATA_SHARE_FORBIDDEN` (HTTP 403). An `ETA_ONLY` scope bars the tracking-event list specifically — a grantee limited to `ETA_ONLY` may read the shipment (and its ETA fields) and its alerts, but not its event stream. Revocation takes effect immediately: subsequent reads by the former grantee fail the visibility check.

### 2.12. Validation Ordering Across a Request

When several checks could reject the same request, the server applies them in a fixed priority order, so that the surfaced error is deterministic. The order is: (1) presence and well-formedness of the user-context headers; (2) role authorization and entity-backed ownership; (3) data-share visibility for cross-party reads; (4) existence of path resources, validated left to right; (5) request-shape validity — required fields, enum membership, interval ordering, and mode-configuration rules; (6) state preconditions of the target resource; (7) interval-occupation conflicts (appointment windows and testing windows); (8) threshold gates (the activation quality gate and the identity-match confirm gate); and (9) optimistic-concurrency and grantee referential checks. A request that fails an earlier check never reaches a later one — for example, a stale `expected_facility_version` on an appointment booking that also names a nonexistent shipment surfaces `ERR_SHIPMENT_NOT_FOUND`, not `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

### 3.1. Registering the Network: Carriers, Shippers, and Consignees

A `NetworkOps` operator registers a carrier organization by supplying its `carrier_name` and its Standard Carrier Alpha Code, `scac_code`; the carrier's `version` starts at 1. A `PlatformAdmin` registers a shipper organization with its `company_name`. Under an existing shipper, that shipper's `ShipperRep` registers consignees — the shipper's customers who will eventually receive freight and view it through grants — by providing each consignee's `company_name` and `destination_code`; the acting representative's `X-User-ID` must equal the shipper's `id`, or the registration is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. The consignee's `shipper_id` is taken from the path. All three organization kinds are readable by every role.

A `PlatformAdmin` also registers facilities — the docks, terminals, and warehouses where appointments occur — by providing a `facility_name` and a `facility_type` of `ORIGIN`, `DESTINATION`, or `BOTH`. A new facility starts `ACTIVE` with `total_dwell_minutes` at 0, `detention_exposure_minutes` at 0, and `appointment_adherence_pct` null. The administrator may later toggle a facility between `ACTIVE` and `SUSPENDED` by patching its `status`; the transition bumps the facility's `version`, and a patch whose target status equals the current status is rejected with `ERR_INVALID_REQUEST`. Appointment booking requires the facility to be `ACTIVE` — booking against a suspended facility fails with `ERR_FACILITY_NOT_ACTIVE` — but a suspended facility's existing appointments are otherwise untouched.

### 3.2. The Carrier Connection Lifecycle

Every data feed into the platform flows through a `CarrierConnection`. A `NetworkOps` operator creates a connection under a carrier by naming its `channel` — one of `TELEMATICS`, `TMS`, or `MANUAL` — and its `supported_modes`, a non-empty subset of the four transport modes `OCEAN`, `RAIL`, `PARCEL`, and `TRUCKLOAD`. Two mode-configuration rules are enforced at this boundary and again wherever modes are named: a `MANUAL` connection must not include `PARCEL` among its supported modes (manual entry cannot keep pace with parcel scan volume), and every mode list must be a non-empty subset of the four mode enums. Violations of either rule are rejected with `ERR_INVALID_MODE_CONFIG` (HTTP 400). The new connection starts in `DRAFT` with its cadence derived from the channel (§2.10), its `credential_ref`, `testing_window_start`, `testing_window_end`, both quality scores, `last_heartbeat_at`, and `suspended_at` all null, and `missed_heartbeat_streak` at 0.

From `DRAFT`, the carrier's own `CarrierRep` submits credentials: the request carries a `credential_ref`, which is recorded on the connection as the transition to `CREDENTIALS_SUBMITTED` takes effect. The acting representative's `X-User-ID` must equal the connection's `carrier_id`, and the connection must currently be `DRAFT`; a state mismatch is rejected with `ERR_CONNECTION_INVALID_STATE` (HTTP 409).

With credentials on file, `NetworkOps` opens a certification window by supplying `testing_window_start` and `testing_window_end`, transitioning the connection to `TESTING`. The end must be strictly after the start (`ERR_INVALID_REQUEST` otherwise). Certification windows are **closed intervals on both ends**, and no two connections of the *same carrier* may be in `TESTING` with intersecting windows — because the interval is closed, windows that merely touch at an endpoint conflict just as overlapping windows do; a conflicting request is rejected with `ERR_TESTING_WINDOW_CONFLICT` (HTTP 409). If a connection is still sitting in `TESTING` when its `testing_window_end` has passed the current logical time, the next ops-run checkpoint resets it to `DRAFT`: both window timestamps and the `credential_ref` are cleared to null, and the run's `testing_connections_reset` counter is incremented. The carrier must then resubmit credentials and negotiate a fresh window.

Activation is the quality gate of the whole onboarding flow: `NetworkOps` may transition a `TESTING` connection to `ACTIVE` only when its authoritative `data_quality_score` is at least 70. A connection whose score is below 70 — or whose score is still null because no checkpoint has ever scored it — is rejected with `ERR_QUALITY_GATE_NOT_MET` (HTTP 422). On activation, `health_status` is recomputed.

An `ACTIVE` connection may be suspended in two ways. `NetworkOps` may suspend it manually, supplying a `reason` for the record. The system also suspends it automatically: at each ops-run checkpoint, any `ACTIVE` connection whose most recent heartbeat is more than twice its cadence old — that is, the gap between now and `last_heartbeat_at` exceeds two times `cadence_minutes` — is suspended, and the run's `connections_degraded` counter is incremented. Either way, the transition from `ACTIVE` to `SUSPENDED` requires the connection to actually be `ACTIVE` (`ERR_CONNECTION_INVALID_STATE` otherwise), records `suspended_at` as the current logical time, and fires the three-link staleness cascade described in §3.5 and §3.7: every shipment fed by this connection whose `tracking_status` is `IN_TRANSIT` or `EXCEPTION` has its `data_freshness` set to `STALE`; each such shipment's ETA is recomputed with the stale confidence multiplier; and the delay-risk assessment runs per affected shipment, opening an alert where warranted.

Resuming a `SUSPENDED` connection requires proof of remediation: the carrier must have posted a heartbeat *after* the suspension — concretely, the connection's `last_heartbeat_at` must be strictly later than its `suspended_at` — or the resume is rejected with `ERR_REMEDIATION_NOT_PROVEN` (HTTP 409). A successful resume transitions the connection back to `ACTIVE`, clears `suspended_at` to null, and restores every shipment of this connection whose `data_freshness` was `STALE` back to `FRESH`, recomputing each such shipment's ETA without the stale multiplier.

Finally, a connection in `DRAFT` or `SUSPENDED` may be retired by `NetworkOps`, moving it to the terminal `RETIRED` state; retirement from any other state is rejected with `ERR_CONNECTION_INVALID_STATE`. Retired connections are excluded from checkpoint scoring.

### 3.3. Heartbeats and the Two Quality Scores

A carrier keeps its connection alive by posting heartbeats. Each heartbeat carries the carrier-claimed `reported_at` send time and a `payload_completeness_pct` between 0 and 100 inclusive; the server stamps `recorded_at` with the current logical time and derives `on_time` per the cadence rule in §2.10. Heartbeats are accepted while the connection is `TESTING`, `ACTIVE`, or `SUSPENDED` — this is what makes remediation provable — and rejected with `ERR_CONNECTION_INVALID_STATE` from any other state. Only the carrier's own `CarrierRep` may post them. Each ingest updates the connection's `last_heartbeat_at` and recomputes the `instantaneous_quality_score`.

The instantaneous view uses only the latest heartbeat record (chosen by `recorded_at`, ties broken by ascending `created_at`): it is the round-half-up of 60 percent of the timeliness component — 100 when the heartbeat was `on_time`, 0 otherwise — plus 40 percent of the heartbeat's `payload_completeness_pct`. It is deliberately a different instrument from the authoritative score: for identical raw data the two views can and do diverge, and only the authoritative one gates activation, feeds confidence intervals, and colors `health_status`.

The authoritative `data_quality_score` is computed per non-`RETIRED` connection at each ops-run checkpoint. The scoring window runs from just after the later of the connection's `created_at` and the previous run's execution time, up to and including now, selecting heartbeat records by `recorded_at`. Three dimension values are computed over that window, then each is individually rounded half-up to a whole number before being combined (nested rounding — this order is pinned): timeliness is the percentage of in-window heartbeats that were `on_time`; completeness is the average `payload_completeness_pct` across in-window heartbeats; cadence adherence compares the heartbeat count against the expected count, where the expected count is the whole-window minutes divided by `cadence_minutes` rounded down, and the adherence percentage is the actual count divided by the expected count capped at 1, times 100. When the window holds no heartbeats, timeliness and completeness are 0; when the expected count is 0, cadence adherence is 0. The final score is the round-half-up of the weighted blend: 40 percent timeliness, 35 percent completeness, 25 percent cadence. A window with zero heartbeats also increments the connection's `missed_heartbeat_streak`; any window with at least one heartbeat resets the streak to 0. `health_status` is then re-derived from the new score per §2.10.

### 3.4. Booking Shipments and Ingesting Tracking Events

A shipper's `ShipperRep` books a shipment under their own shipper by naming the carrying `carrier_id`, the feed `connection_id`, the transport `mode`, a `tracking_reference`, a mode-specific `mode_reference` (the container number for `OCEAN`, the railcar number for `RAIL`, the parcel tracking number for `PARCEL`, the PRO number for `TRUCKLOAD`), the `destination_code`, an optional `po_reference_claim` (the carrier-claimed purchase-order number used later for identity matching; it defaults to the empty string when unknown), and the planned `planned_departure_at` and `planned_arrival_at` timestamps, with arrival strictly after departure (`ERR_INVALID_REQUEST` otherwise). The named connection must be `TESTING` or `ACTIVE` — a shipment cannot be booked onto a draft, suspended, or retired feed, and the attempt fails with `ERR_CONNECTION_NOT_ACTIVE` (HTTP 409) — and the shipment's `mode` must appear among the connection's `supported_modes` (`ERR_INVALID_MODE_CONFIG` otherwise). A new shipment starts with `tracking_status` `BOOKED`, `identity_state` `UNRESOLVED`, `data_freshness` `FRESH`, and `actual_delay_minutes` 0; creation immediately runs the ETA prediction in its baseline variant (§3.5) and computes the confidence halfwidth.

From then on, the shipment's carrier feeds tracking events. Each event carries an `event_time` (when the event occurred at the carrier), an `event_type` — one of `DEPARTED`, `ARRIVED_WAYPOINT`, `POSITION_UPDATE`, `DELAY_REPORTED`, `RECOVERED`, `OUT_FOR_DELIVERY`, or `DELIVERED` — and an optional `delay_minutes` magnitude meaningful only on `DELAY_REPORTED` and `RECOVERED` events (default 0). Ingest is restricted to the shipment's own carrier, requires the feed connection to be `ACTIVE` (a `TESTING` feed can certify but not carry live traffic, and any other state also fails with `ERR_CONNECTION_NOT_ACTIVE`), and requires the shipment not to be terminal — ingesting an event onto a `DELIVERED` or `CANCELLED` shipment is rejected with `ERR_SHIPMENT_NOT_TRACKABLE` (HTTP 409).

At ingest, the server flags the event `is_late` when its `event_time` is earlier than the greatest `event_time` already applied to the shipment — late-arriving telemetry is stored but marked. The shipment's `tracking_status` is then re-derived by replaying all non-voided events per §2.9: `DEPARTED` as the effective event moves `BOOKED` to `IN_TRANSIT`; `DELAY_REPORTED` moves `IN_TRANSIT` to `EXCEPTION`; `RECOVERED` moves `EXCEPTION` back to `IN_TRANSIT`; `OUT_FOR_DELIVERY` moves either `IN_TRANSIT` or `EXCEPTION` to `OUT_FOR_DELIVERY`; and `DELIVERED` as the effective event terminates the shipment at `DELIVERED` from `BOOKED`, `IN_TRANSIT`, or `OUT_FOR_DELIVERY` — the direct `BOOKED` to `DELIVERED` path exists for small parcel flows where a delivery scan is the first and only event. On every `DELIVERED` transition, `eta_at` is frozen at the actual delivery event's `event_time`. Each ingest also reruns the ETA prediction and confidence halfwidth, runs the delay-risk assessment (§3.7), and bumps the shipment's `version`. Transitions into `EXCEPTION` increase the shipment's open delay by the event's `delay_minutes`; transitions out of `EXCEPTION` via `RECOVERED` decrease it by the event's `delay_minutes`, floored at zero.

When a carrier report turns out to be wrong, `NetworkOps` voids the event: its `voided` flag becomes true, it drops out of the replay set, and the shipment's status, ETA, confidence, and delay risk are all re-derived without it. `NetworkOps` may also trigger an on-demand ETA recompute for a shipment — running the prediction, the confidence halfwidth, and the delay-risk assessment without any new event — which is how operators refresh estimates after, say, a checkpoint has moved quality scores.

A shipper's `ShipperRep` may cancel their own shipment while its `tracking_status` is `BOOKED`, `IN_TRANSIT`, or `EXCEPTION`, moving it to the terminal `CANCELLED` state; cancelling from `OUT_FOR_DELIVERY` or from a terminal state is rejected with `ERR_SHIPMENT_NOT_CANCELLABLE` (HTTP 409). Cancellation cascades to the alert queue: every `OPEN` or `ESCALATED` exception alert on the shipment auto-transitions to `RESOLVED` with `resolution` `FALSE_ALARM`.

### 3.5. Arrival Prediction and Its Confidence Interval

The ETA model has two pinned variants, selected mechanically. When a shipment has no non-voided tracking events, the `SCHEDULED_BASELINE` variant applies: `eta_at` equals `planned_arrival_at`, ignoring telemetry entirely, and `eta_variant` reads `SCHEDULED_BASELINE`. As soon as at least one non-voided event exists, the `TELEMETRY_BLENDED` variant applies and `eta_variant` reads `TELEMETRY_BLENDED`. The blended variant reasons in minutes over the planned run length — the difference between `planned_arrival_at` and `planned_departure_at`, which is strictly positive. It locates the latest event position as the greatest `event_time` among non-voided events, computes the fraction of the planned run already elapsed as that position's distance from planned departure divided by the planned run length, clamped so it never falls below 0 or rises above 1, and adds up the *open delay*: the sum of `delay_minutes` over non-voided `DELAY_REPORTED` events minus the sum over non-voided `RECOVERED` events, floored at zero. The predicted arrival is then the latest event position, plus the not-yet-elapsed fraction of the planned run length, plus the open delay — all in minutes, rounded half-up to whole minutes.

Every ETA carries an explicit uncertainty: `eta_confidence_halfwidth_minutes` bounds the estimate on both sides. The halfwidth starts from a per-mode base — 720 minutes (twelve hours) for `OCEAN`, 360 for `RAIL`, 60 for `PARCEL`, and 120 for `TRUCKLOAD` — then widens in inverse proportion to feed quality: it is multiplied by one plus the shortfall of the quality input below 100, expressed as a fraction of 100. The quality input is the feed connection's authoritative `data_quality_score` **as of the last completed ops-run checkpoint** — the evaluation order is pinned so that the quality computed in the current run never feeds the same run's confidence intervals — and a connection that has never been scored contributes a neutral 50. When the shipment's `data_freshness` is `STALE`, the whole halfwidth is then multiplied by 1.5. The result is rounded half-up to integer minutes, rounding only at this final step. The halfwidth is recomputed whenever the ETA is recomputed.

### 3.6. Identity Resolution: Matching Shipments to Purchase Orders

Carriers and shippers rarely reference the same identifiers, so the platform resolves identity explicitly. A shipper's `ShipperRep` first creates purchase orders under their own shipper, each with a `po_number`, a `destination_code`, and the carrier-side `booking_reference`; each order's `confirmed_link_count` starts at 0. Identity links between a shipment and a purchase order are then proposed by `NetworkOps`, naming the `purchase_order_id` and carrying the OCC field `expected_po_version` per §2.8.

At proposal time, the platform computes the link's `match_score`, a decimal with exactly two decimal places blending three signals: half of the weight goes to whether the shipment's `po_reference_claim` equals the order's `po_number` while being non-empty (an empty claim contributes nothing); two-fifths go to whether the shipment's `tracking_reference` equals the order's `booking_reference`; and one-tenth goes to whether the shipment's `destination_code` equals the order's `destination_code`. Each signal contributes its full weight when true and nothing when false. The link is stored in `PROPOSED` status with its score, the shipment's `identity_state` moves from `UNRESOLVED` to `MATCHED_PROVISIONAL`, and the purchase order's `version` bumps by 1 (the OCC parent bump — which is precisely what makes a second proposer's stale `expected_po_version` fail with `ERR_STALE_VERSION`).

Confirmation belongs to the shipper: the `ShipperRep` whose `X-User-ID` equals the order's `shipper_id` confirms a `PROPOSED` link, but only when three conditions hold — the link is still `PROPOSED` (otherwise `ERR_LINK_NOT_PROPOSED`, HTTP 409), the shipment's `tracking_status` is neither `DELIVERED` nor `CANCELLED` (otherwise `ERR_SHIPMENT_TERMINAL`, HTTP 409), and the `match_score` is strictly greater than 0.90 — a score of exactly 0.90 is *not* sufficient and is rejected with `ERR_MATCH_SCORE_BELOW_THRESHOLD` (HTTP 422). Confirming increments the order's `confirmed_link_count` by 1, bumps the order's `version`, and moves the shipment's `identity_state` to `MATCHED_CONFIRMED` with a `version` bump of its own.

Rejection is symmetric and compensating. The same `ShipperRep` may reject a link in `PROPOSED` or `CONFIRMED` status (any other status draws `ERR_LINK_NOT_PROPOSED`), moving it to the terminal `REJECTED` state. Rejecting a `CONFIRMED` link decrements the order's `confirmed_link_count` by 1 and bumps its `version`, restoring the count; rejecting a merely `PROPOSED` link touches no count. Either way the shipment's `identity_state` is re-derived from what remains: it falls back from `MATCHED_CONFIRMED` to `MATCHED_PROVISIONAL` when the last confirmed link is rejected while other non-rejected links remain, drops to `UNRESOLVED` when no non-`REJECTED` links remain at all, and returns from `MATCHED_PROVISIONAL` to `UNRESOLVED` when the last non-rejected link becomes `REJECTED` with none confirmed.

### 3.7. Delay-Risk Alerts and the Customer-Service Workflow

The delay-risk assessment runs after every ETA recompute — event ingest, event void, on-demand recompute, checkpoint, connection suspend, and connection resume. It compares the recomputed `eta_at` against `planned_arrival_at`: the projected delay in minutes is the amount by which the ETA exceeds the plan. Each mode tolerates some lateness before an alert fires — 720 minutes for `OCEAN`, 360 for `RAIL`, 30 for `PARCEL`, 60 for `TRUCKLOAD` — and an alert is created only when the projected delay is **strictly greater** than the mode tolerance, while the shipment's `tracking_status` is `BOOKED`, `IN_TRANSIT`, `EXCEPTION`, or `OUT_FOR_DELIVERY`, and no `DELAY_RISK` alert for the shipment is already sitting in `OPEN`, `ESCALATED`, or `ACKNOWLEDGED`. Alerts are system-created only; each carries an `alert_type` — `DELAY_RISK` for alerts opened by this assessment, with `CONNECTION_DEGRADED` reserved as the type for connection-health alerts. The new alert opens in `OPEN` status with `opened_at` stamped from the logical clock; its `severity` is `HIGH` when the projected delay is strictly greater than twice the mode tolerance and `MEDIUM` otherwise, and its `assigned_queue` follows severity — `CS_TIER2` for `HIGH`, `CS_TIER1` for `MEDIUM`.

Customer-service agents work the queue through two filters — `status` and `severity` — alongside the usual pagination. An alert may be escalated by the system: at each ops-run checkpoint, any `HIGH`-severity alert still `OPEN` whose age exceeds 240 minutes (four hours) moves to `ESCALATED`, counted in the run's `alerts_escalated`. A `CustomerService` agent acknowledges an alert in `OPEN` or `ESCALATED` status, moving it to `ACKNOWLEDGED`; acknowledging from any other status is rejected with `ERR_ALERT_INVALID_STATE` (HTTP 409). Resolution requires the alert to be `ACKNOWLEDGED` and carries a mandatory `resolution` — one of `DELAY_CONFIRMED`, `FALSE_ALARM`, or `DELIVERY_OBSERVED`; a missing or invalid resolution value is `ERR_INVALID_REQUEST`, and resolving from a non-acknowledged status is `ERR_ALERT_INVALID_STATE`. Resolution stamps `resolved_at` from the logical clock.

Resolving with `DELAY_CONFIRMED` fires a three-step cascade. First, the shipment's `actual_delay_minutes` is recorded as the ETA's overrun beyond `planned_arrival_at`, floored at zero. Second, every `SCHEDULED` appointment of that shipment whose `window_end` is earlier than the shipment's `eta_at` — the truck can no longer make the window — transitions to `MISSED`. Third, each affected appointment's facility has its `appointment_adherence_pct` recomputed with the miss counted (§3.8). Alerts also resolve without agent action: cancelling a shipment auto-resolves its `OPEN` or `ESCALATED` alerts as `FALSE_ALARM` (§3.4).

### 3.8. Facility Appointments, Dwell, and Detention Exposure

Carriers book dock appointments at facilities for their shipments. The booking, made by the carrying carrier's `CarrierRep`, names the `shipment_id`, the appointment `window_start` and `window_end`, and the OCC field `expected_facility_version` per §2.8; the facility's `version` bumps by 1 on a successful booking. Appointment windows are **half-open intervals**: an arrival at exactly `window_start` counts as within the window, an arrival at exactly `window_end` does not. The end must be strictly after the start (`ERR_INVALID_REQUEST`). Two appointments at the same facility conflict when their half-open windows overlap and the existing one is still `SCHEDULED`; the conflicting booking is rejected with `ERR_APPOINTMENT_WINDOW_CONFLICT` (HTTP 409) — and note that because these windows are half-open, adjacent windows that merely touch do *not* conflict, unlike the closed certification windows of §3.2. A new appointment starts `SCHEDULED` with `actual_arrival_at`, `actual_departure_at`, `dwell_minutes`, `adherent`, and `exposure_minutes` all null.

When the truck shows up and leaves, the carrier's `CarrierRep` completes the appointment by recording `actual_arrival_at` and `actual_departure_at`, with departure strictly after arrival (`ERR_INVALID_REQUEST`); completion requires the appointment still `SCHEDULED`, else `ERR_APPOINTMENT_INVALID_STATE`. Completion derives three values: `dwell_minutes` is the whole-minute difference between departure and arrival; `adherent` is true exactly when the actual arrival falls within the half-open window — on or after `window_start` and strictly before `window_end`; and `exposure_minutes` is the detention exposure. Detention works from a per-mode free-time allowance — 240 minutes for `OCEAN`, 360 for `RAIL`, 0 for `PARCEL`, and 120 for `TRUCKLOAD` — to which an adherent arrival adds a 15-minute grace; the exposure is the dwell minus that allowance, floored at zero. Completion then rolls up to the facility: `total_dwell_minutes` increases by the appointment's dwell, `detention_exposure_minutes` increases by its exposure, `appointment_adherence_pct` is recomputed, and the facility's `version` bumps.

A completion entered in error is unwound by `NetworkOps` voiding it, which requires the appointment to be `COMPLETED` (`ERR_APPOINTMENT_INVALID_STATE` otherwise) and moves it to the terminal `VOIDED` state with full compensation: the facility's dwell and detention aggregates are decremented by exactly the amounts the completion added, the adherence percentage is recomputed excluding the voided completion, and the facility's `version` bumps again. The other way an appointment leaves `SCHEDULED` is the delay-confirmation cascade of §3.7, which moves it to `MISSED`.

The facility's `appointment_adherence_pct` aggregates outcomes across the facility: it is the round-half-up integer percentage of adherent completions among all resolved appointments — those `COMPLETED` or `MISSED`; `VOIDED` and still-`SCHEDULED` appointments are excluded from both numerator and denominator — and it is null whenever no appointment has resolved yet. It is recomputed on each completion, on each cascade-driven miss, and on each voided completion.

### 3.9. Sharing Visibility with Carriers and Consignees

A shipper's `ShipperRep` extends read access to an outside party by creating a data-share grant under their own shipper, naming the `grantee_type`, `grantee_id`, `scope`, `effective_from`, and `expires_at` per §2.11. The grantee reference is validated at creation against its type: a `CARRIER` grantee must resolve to an existing carrier (`ERR_CARRIER_NOT_FOUND` if not), and a `CONSIGNEE` grantee must resolve to an existing consignee of the granting shipper (`ERR_CONSIGNEE_NOT_FOUND` if not). The grant starts `ACTIVE`. Revoking it — again only by the granting shipper's own representative — requires it still be `ACTIVE`; revoking an already-revoked grant is rejected with `ERR_GRANT_ALREADY_REVOKED` (HTTP 409), and revocation cuts access immediately, so the next read by the former grantee fails with `ERR_DATA_SHARE_FORBIDDEN`.

### 3.10. The Ops-Run Checkpoint, End to End

The checkpoint is the platform's periodic reconciliation sweep, and its four duties run over the whole network in one logical instant. It scores every non-`RETIRED` connection's authoritative quality per §3.3. It resets every `TESTING` connection whose certification window has expired back to `DRAFT`, clearing window and credentials. It suspends every `ACTIVE` connection that has missed two full cadence periods, firing the staleness cascade — shipments to `STALE`, ETAs recomputed with the stale multiplier, delay-risk assessed per affected shipment — and it escalates every overdue `HIGH`-severity open alert per §3.7. The returned `OpsRun` summarizes the sweep through its counters, and the quality scores it produces become the input to *subsequent* runs' confidence intervals, never its own.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource (including state transitions) return `200 OK`. All endpoints are mounted at the API root. Request bodies, preconditions, side effects, and visibility scoping are defined in §2 and §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/carriers` | Create a carrier organization | NetworkOps |
| GET | `/carriers/{id}` | Get a carrier | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/carriers/{id}/connections` | List connections of a carrier | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/carriers/{id}/shipments` | List shipments carried by a carrier | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/shippers` | Create a shipper organization | PlatformAdmin |
| GET | `/shippers/{id}` | Get a shipper | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/shippers/{id}/consignees` | List consignees of a shipper | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/shippers/{id}/purchase-orders` | List purchase orders of a shipper | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/shippers/{id}/shipments` | List shipments of a shipper | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/shippers/{id}/data-share-grants` | List data-share grants of a shipper | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/shippers/{id}/consignees` | Register a consignee under a shipper | ShipperRep (own shipper) |
| POST | `/carriers/{id}/connections` | Create a carrier connection in DRAFT | NetworkOps |
| GET | `/connections/{id}` | Get a carrier connection | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/connections/{id}/submit-credentials` | Submit connection credentials (DRAFT to CREDENTIALS_SUBMITTED) | CarrierRep (own carrier) |
| POST | `/connections/{id}/begin-testing` | Open the certification testing window (CREDENTIALS_SUBMITTED to TESTING) | NetworkOps |
| POST | `/connections/{id}/activate` | Activate a TESTING connection gated on epoch quality score at least 70 | NetworkOps |
| POST | `/connections/{id}/suspend` | Manually suspend an ACTIVE connection | NetworkOps |
| POST | `/connections/{id}/resume` | Resume a SUSPENDED connection after proven remediation | NetworkOps |
| POST | `/connections/{id}/retire` | Retire a DRAFT or SUSPENDED connection | NetworkOps |
| POST | `/connections/{id}/heartbeats` | Post a connection heartbeat (TESTING, ACTIVE, or SUSPENDED) | CarrierRep (own carrier) |
| GET | `/connections/{id}/heartbeats` | List heartbeat records of a connection | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/shippers/{id}/purchase-orders` | Create a purchase order | ShipperRep (own shipper) |
| GET | `/purchase-orders/{id}` | Get a purchase order | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/purchase-orders/{id}/identity-links` | List identity links pointing at a purchase order | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/facilities` | Create a facility (ACTIVE) | PlatformAdmin |
| GET | `/facilities/{id}` | Get a facility | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| PATCH | `/facilities/{id}` | Toggle facility status (ACTIVE or SUSPENDED) | PlatformAdmin |
| POST | `/shippers/{id}/shipments` | Create a shipment (BOOKED, identity UNRESOLVED) | ShipperRep (own shipper) |
| GET | `/shipments` | List shipments with filters (`connection_id`, `mode`, `tracking_status`) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/shipments/{id}` | Get a shipment (visibility-scoped) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/shipments/{id}/events` | Ingest a carrier tracking event; status re-derived by replay | CarrierRep (own carrier's shipment) |
| GET | `/shipments/{id}/events` | List tracking events of a shipment (barred for ETA_ONLY grantees) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/shipments/{id}/events/{eventId}/void` | Void a tracking event (retroactive correction) | NetworkOps |
| POST | `/shipments/{id}/recompute-eta` | On-demand ETA recompute with delay-risk assessment | NetworkOps |
| POST | `/shipments/{id}/cancel` | Cancel a shipment (BOOKED, IN_TRANSIT, or EXCEPTION only) | ShipperRep (own shipment) |
| POST | `/shipments/{id}/identity-links` | Propose an identity link (OCC on purchase-order version) | NetworkOps |
| GET | `/shipments/{id}/identity-links` | List identity links of a shipment | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/identity-links/{id}/confirm` | Confirm a PROPOSED link (score strictly above 0.90; shipment non-terminal) | ShipperRep (own purchase order) |
| POST | `/identity-links/{id}/reject` | Reject a PROPOSED or CONFIRMED link (compensating) | ShipperRep (own purchase order) |
| GET | `/alerts` | Customer-service alert queue with filters (`status`, `severity`) | CustomerService, NetworkOps, PlatformAdmin |
| GET | `/shipments/{id}/alerts` | List alerts of a shipment (visibility-scoped) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/alerts/{id}/acknowledge` | Acknowledge an OPEN or ESCALATED alert | CustomerService |
| POST | `/alerts/{id}/resolve` | Resolve an ACKNOWLEDGED alert; DELAY_CONFIRMED fires the appointment-miss cascade | CustomerService |
| POST | `/facilities/{id}/appointments` | Book an appointment (half-open window; OCC on facility version) | CarrierRep (own carrier's shipment) |
| GET | `/facilities/{id}/appointments` | List appointments at a facility (filter `status`) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/appointments` | List appointments with filters (`shipment_id`, `facility_id`) | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| GET | `/appointments/{id}` | Get an appointment | PlatformAdmin, NetworkOps, CarrierRep, ShipperRep, CustomerService, ConsigneeRep |
| POST | `/appointments/{id}/complete` | Record arrival/departure; computes dwell, adherence, detention exposure | CarrierRep (own carrier's shipment) |
| POST | `/appointments/{id}/void-completion` | Void a completion (compensating; restores facility aggregates) | NetworkOps |
| POST | `/shippers/{id}/data-share-grants` | Grant a carrier or consignee scoped read access | ShipperRep (own shipper) |
| POST | `/data-share-grants/{id}/revoke` | Revoke an ACTIVE grant | ShipperRep (own grant) |
| POST | `/_clock/set_current_utc` | Set the logical clock (never backwards; startup default 2026-09-01T00:00:00Z) | PlatformAdmin |
| POST | `/_ops/run-checkpoint` | Ops-run checkpoint: quality scoring, window resets, staleness suspensions, alert escalation | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3; this table is the index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_DATA_SHARE_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_MODE_CONFIG` | 400 Bad Request |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_CONSIGNEE_NOT_FOUND` | 404 Not Found |
| `ERR_CONNECTION_NOT_FOUND` | 404 Not Found |
| `ERR_PURCHASE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_IDENTITY_LINK_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DATA_SHARE_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_CONNECTION_INVALID_STATE` | 409 Conflict |
| `ERR_CONNECTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_REMEDIATION_NOT_PROVEN` | 409 Conflict |
| `ERR_TESTING_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_QUALITY_GATE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_NOT_TRACKABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPMENT_TERMINAL` | 409 Conflict |
| `ERR_MATCH_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_LINK_NOT_PROPOSED` | 409 Conflict |
| `ERR_ALERT_INVALID_STATE` | 409 Conflict |
| `ERR_FACILITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_APPOINTMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_GRANT_ALREADY_REVOKED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
